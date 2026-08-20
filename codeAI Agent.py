import os
import re
import json
import time
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text, inspect
from google import genai
from urllib.parse import quote_plus


try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

# ---------------------------------------------------------
# 1. Cấu hình trang
# ---------------------------------------------------------
st.set_page_config(page_title=" AI Business Agent for SQL", page_icon="🤖", layout="wide")

FORBIDDEN_KEYWORDS = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke"]
TIME_KEYWORDS = ["date", "month", "thang", "quy", "quarter", "nam", "year"]

MODEL_OPTIONS = ["gemini-3.6-flash", "gemini-2.5-flash"]

MAX_TABLES_SCHEMA = 30     # giới hạn số bảng khi tự động đọc schema
MAX_ROWS_CAP = 3000        # giới hạn cứng số dòng đọc về mỗi truy vấn
MAX_HISTORY_TURNS = 15     # giới hạn số lượt chat lưu trong session
# ---------------------------------------------------------
# 2. Hàm tự động trích xuất Schema từ Database của người dùng
# ---------------------------------------------------------
def auto_extract_schema(engine, max_tables: int = MAX_TABLES_SCHEMA) -> str:
    """Tự động đọc danh sách Bảng và Cột để Gemini hiểu Database bất kỳ.
    Giới hạn số bảng để tránh prompt quá dài và kết nối chậm trên DB có nhiều bảng."""
    try:
        inspector = inspect(engine)
        all_tables = inspector.get_table_names()
        tables = all_tables[:max_tables]
        schema_text = "Cơ sở dữ liệu bao gồm các bảng và cột sau:\n"
        for table_name in tables:
            schema_text += f"- Bảng `{table_name}`: "
            columns = inspector.get_columns(table_name)
            col_names = [f"{col['name']} ({str(col['type'])})" for col in columns]
            schema_text += ", ".join(col_names) + "\n"
        if len(all_tables) > max_tables:
             schema_text += f"\n(Lưu ý: DB có {len(all_tables)} bảng, chỉ hiển thị {max_tables} bảng đầu tiên.)\n"
        return schema_text
    except Exception as e:
        return f"Không thể tự động đọc schema: {e}"


def sanitize_error(msg: str, pw: str) -> str:
    """Che mật khẩu nếu vô tình xuất hiện trong thông báo lỗi kết nối."""
    if pw:
        msg = msg.replace(pw, "***")
        msg = msg.replace(quote_plus(pw), "***")
    return msg


def read_sql_capped(sql_query: str, engine, cap: int = MAX_ROWS_CAP, chunksize: int = 1000):
    """Đọc dữ liệu theo từng chunk, dừng ngay khi đạt giới hạn — bảo vệ app dùng chung
    khỏi bị treo nếu AI quên thêm LIMIT trên một bảng khổng lồ."""
    chunks, total, truncated = [], 0, False
    with engine.connect() as conn:
        for chunk in pd.read_sql(text(sql_query), conn, chunksize=chunksize):
            chunks.append(chunk)
            total += len(chunk)
            if total >= cap:
                truncated = True
                break
    if not chunks:
        return pd.DataFrame(), False
    df = pd.concat(chunks, ignore_index=True)
    if len(df) > cap:
        df = df.head(cap)
        truncated = True
    return df, truncated
    

def has_time_dimension(df: pd.DataFrame) -> bool:
    """Kiểm tra dữ liệu có thực sự mang tính chuỗi thời gian không —
    tránh vẽ 'dự báo' vô nghĩa trên dữ liệu categorical (VD: top nhân viên, top sản phẩm)."""
    return any(k in c.lower() for c in df.columns for k in TIME_KEYWORDS)
 
        
# ---------------------------------------------------------
# 3. Sidebar: Cấu hình linh hoạt cho người dùng cá nhân
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Cấu hình Kết nối")
    st.caption("Ứng dụng không lưu trữ tài khoản/API Key của bạn.")

    st.subheader("1. MySQL Cloud Database")
    db_host = st.text_input("Host", placeholder="e.g., mysql-xxx.aivencloud.com")
    db_port = st.text_input("Port", value="3306")
    db_user = st.text_input("User", value="root")
    db_pass = st.text_input("Password", type="password")
    db_name = st.text_input("Database Name", placeholder="e.g., my_business_db")
    use_ssl = st.checkbox("Dùng SSL (bắt buộc với hầu hết MySQL cloud: Aiven, Railway...)", value=True)

    st.subheader("2. Gemini API Key")
    api_key = st.text_input("API Key", type="password", help="Lấy key miễn phí tại Google AI Studio")
    model_name = st.selectbox("Model AI", MODEL_OPTIONS, index=0)
    
    # Nơi hiển thị Schema tự động trích xuất
    schema_context_input = st.text_area(
        "Mô tả Schema / Nghiệp vụ (Tự động nạp sau khi bấm Kết nối)", 
        value=st.session_state.get("schema_context", ""), 
        height=180
    )

    forecast_periods = st.slider("Số kỳ dự báo xu hướng", 1, 12, 3)
    connect_btn = st.button("🔌 Kết nối Database & AI", type="primary", use_container_width=True)

# ---------------------------------------------------------
# 4. Kiểm tra Kết nối & Tự động quét Schema
# ---------------------------------------------------------
def try_connect(host, port, user, pw, name, use_ssl):
    connect_args = {"connection_timeout": 10}
    if use_ssl:
        connect_args["ssl_disabled"] = False
    engine = create_engine(
        f"mysql+mysqlconnector://{user}:{quote_plus(pw)}@{host}:{port}/{name}",
        connect_args=connect_args,
        pool_pre_ping=True,   # tự phát hiện & loại bỏ kết nối "chết" (phổ biến với free-tier cloud DB hay ngắt idle)
        pool_recycle=3600,
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine

if connect_btn:
    if not (db_host and db_user and db_name and api_key):
        st.sidebar.error("❌ Vui lòng điền đầy đủ Host, User, Database Name và API Key!")
    else:
        try:
            engine = try_connect(db_host, db_port, db_user, db_pass, db_name, use_ssl)
            client = genai.Client(api_key=api_key)
            
            # Tự động quét Schema nếu người dùng không tự nhập schema tay
            extracted_schema = auto_extract_schema(engine)
            final_schema = schema_context_input if schema_context_input.strip() else extracted_schema

            st.session_state.update({
                "engine": engine,
                "client": client,
                "model_name": model_name,
                "schema_context": final_schema,
                "connected": True,
                "_db_pass_for_sanitize": db_pass,
            })
            st.sidebar.success("✅ Kết nối thành công!")
            st.rerun()
        except Exception as e:
            st.session_state["connected"] = False
            st.sidebar.error(f"❌ Lỗi kết nối: {sanitize_error(str(e), db_pass)}")

# ---------------------------------------------------------
# 5. Hàm xử lý Core Agent
# ---------------------------------------------------------
def is_safe_select(sql: str) -> bool:
    if not sql:
        return False
    lowered = sql.strip().rstrip(";").lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False
    if ";" in lowered:  # chặn stacked queries (nhiều câu lệnh nối nhau)
        return False
    if any(re.search(rf"\b{kw}\b", lowered) for kw in FORBIDDEN_KEYWORDS):
        return False
    return True


def call_gemini(prompt: str, max_retries: int = 3):
    client = st.session_state["client"]
    model_name = st.session_state.get("model_name", "gemini-3.6-flash")
    if not client:
        return None
        
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            return response.text.strip().replace("```sql", "").replace("```", "").strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                st.error("🚫 Hết quota Gemini API. Vui lòng kiểm tra lại Key hoặc chờ reset quota.")
                return None
            if "503" in err or "UNAVAILABLE" in err:
                wait = 3 * (attempt + 1)
                st.toast(f"⏳ Server bận, thử lại sau {wait}s...")
                time.sleep(wait)
            else:
                st.error(f"Lỗi Gemini API: {err}")
                return None
                st.error("Model quá tải sau nhiều lần thử. Hãy gửi lại câu hỏi sau ít phút.")
    return None


def self_check(user_query: str, sql_query: str, df: pd.DataFrame) -> dict:
    sample = df.head(5).to_string(index=False)
    prompt = f"""
Bạn là chuyên gia QA kiểm định SQL.
Schema: {st.session_state['schema_context']}
Câu hỏi gốc: "{user_query}"
SQL: {sql_query}
5 dòng mẫu: {sample}

Kiểm tra SQL có trả lời ĐẦY ĐỦ câu hỏi không.
Trả về DUY NHẤT JSON: {{"day_du": true/false, "ly_do": "..."}}
"""
    res = call_gemini(prompt)
    if not res:
        return {"day_du": True, "ly_do": "Bỏ qua self-check."}
    try:
        cleaned = res.strip().strip("`").replace("json\n", "").strip()
        return json.loads(cleaned)
    except Exception:
        return {"day_du": True, "ly_do": "Không parse được JSON."}


def run_agent(user_query: str):
    result = {"query": user_query, "df": None, "sql": None, "logs": [], "error": None}
    schema_context = st.session_state["schema_context"]
    engine = st.session_state["engine"]
    db_pass = st.session_state.get("_db_pass_for_sanitize", "")

    prompt = f"""Schema:
{schema_context}
Viết 1 câu MySQL SELECT duy nhất cho câu hỏi: {user_query}
Nếu không có GROUP BY, bắt buộc thêm LIMIT 1000 để tránh trả về quá nhiều dữ liệu.
Chỉ trả về SQL thuần, không markdown, không giải thích."""
    sql_query = call_gemini(prompt)
    if not sql_query:
        result["error"] = "Không thể tạo SQL từ mô hình AI."
        return result

    for attempt in range(1, 4):
        result["logs"].append(f"[Lần {attempt}] SQL: {sql_query}")

        if not is_safe_select(sql_query):
             result["error"] = "Câu lệnh SQL không an toàn (Chỉ chấp nhận lệnh SELECT đơn, không nhiều câu lệnh)."
             result["sql"] = sql_query
             return result

        try:
            df, truncated = read_sql_capped(sql_query, engine, cap=MAX_ROWS_CAP)
            if truncated:
                 result["logs"].append(f"⚠️ Dữ liệu lớn: đã dừng đọc ở {MAX_ROWS_CAP:,} dòng để bảo vệ hệ thống dùng chung.")

            check = self_check(user_query, sql_query, df)

            if check.get("day_du", True):
                result["logs"].append(f"✅ Kiểm định SQL OK: {check.get('ly_do', '')}")
                result["df"] = df
                result["sql"] = sql_query
                return result

            result["logs"].append(f"⚠️ Phát hiện vấn đề: {check.get('ly_do', '')}")
            if attempt == 3:
                result["df"] = df
                result["sql"] = sql_query
                return result

            fix_prompt = f"Schema: {schema_context}\nCâu hỏi: '{user_query}'\nSQL lỗi/chưa đủ: {sql_query}\nLý do: {check.get('ly_do', '')}\nViết lại SQL chuẩn xác."
            sql_query = call_gemini(fix_prompt) or sql_query

        except Exception as e:
            error_msg = str(e)
            result["logs"].append(f"❌ Lỗi thực thi MySQL: {error_msg}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {error_msg}"
                result["sql"] = sql_query
                return result

            fix_prompt = f"Schema: {schema_context}\nSQL lỗi: {sql_query}\nLỗi MySQL: {error_msg}\nCâu hỏi: '{user_query}'\nSửa lại SQL."
            sql_query = call_gemini(fix_prompt) or sql_query

    return result

# ---------------------------------------------------------
# 6. Hiển thị kết quả & Trực quan hóa
# ---------------------------------------------------------
def render_smart_chart(df: pd.DataFrame):
    cols = df.columns.tolist()
    if len(cols) < 2:
        st.info("Dữ liệu cần tối thiểu 2 cột để vẽ biểu đồ.")
        return

    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = [c for c in cols if c not in num_cols]
    time_hint = has_time_dimension(df)
    
    try:
        if time_hint and num_cols:
            x_col = next(c for c in cols if any(k in c.lower() for k in TIME_KEYWORDS))
            y_cols = [c for c in num_cols if c != x_col] or num_cols
            fig = px.line(df, x=x_col, y=y_cols, markers=True, title=f"Xu hướng theo {x_col}")
        elif cat_cols and num_cols:
            fig = px.bar(df, x=cat_cols[0], y=num_cols[0], title=f"{num_cols[0]} theo {cat_cols[0]}")
        elif len(num_cols) >= 2:
            fig = px.scatter(df, x=num_cols[0], y=num_cols[1], title="Biểu đồ phân tích tương quan")
        else:
            st.info("Không tìm thấy dạng biểu đồ phù hợp.")
            return
        st.plotly_chart(fig, width='stretch')
    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {e}")


def forecast_series(df: pd.DataFrame, periods: int = 3):
    if not has_time_dimension(df):
        return None, "Dữ liệu không có yếu tố thời gian (ngày/tháng/quý/năm) nên không thể dự báo xu hướng."
        
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if not num_cols or len(df) < 3:
        return None, "Cần tối thiểu 3 dòng dữ liệu dạng số để dự báo."

    x_col = next((c for c in df.columns if any(k in c.lower() for k in TIME_KEYWORDS)), None)
    y_candidates = [c for c in num_cols if c != x_col]
    y_col = y_candidates[0] if y_candidates else num_cols[0]

    df_sorted = df.copy()
    try:
        df_sorted = df_sorted.sort_values(x_col)
    except Exception:
        pass
    df_sorted = df_sorted.reset_index(drop=True)


    y = df_sorted[y_col].values.astype(float)
    n = len(y)
    x_idx = np.arange(n)
    coeffs = np.polyfit(x_idx, y, 1)
    future_idx = np.arange(n, n + periods)
    future_vals = np.polyval(coeffs, future_idx)


    is_numeric_x = pd.api.types.is_numeric_dtype(df_sorted[x_col])
    if is_numeric_x:
        step = 1
        if n >= 2:
               step = df_sorted[x_col].iloc[-1] - df_sorted[x_col].iloc[-2]
               if step == 0:
                   step = 1
        last_x = df_sorted[x_col].iloc[-1]
        future_x = [last_x + step * (i + 1) for i in range(periods)]
    else:
        future_x = [f"Kỳ +{i+1}" for i in range(periods)]


    hist_x = df_sorted[x_col].tolist()
    bridge_x = [hist_x[-1]] + future_x
    bridge_y = [y[-1]] + list(future_vals)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist_x, y=y, mode="lines+markers", name="Thực tế", line=dict(color="#4C9AFF")))
    fig.add_trace(go.Scatter(x=bridge_x, y=bridge_y, mode="lines+markers", name="Dự báo", line=dict(color="#FF6B6B", dash="dash")))
    fig.update_layout(
        title=f"Dự báo xu hướng theo {x_col}",
        xaxis_title=x_col, yaxis_title=y_col,
        margin=dict(l=20, r=20, t=50, b=20)
    )
     return fig, "Hồi quy tuyến tính (Linear Regression)"


def render_result(result: dict):
    for line in result["logs"]:
        st.caption(line)

    if result.get("error"):
        st.error(result["error"])
        if result.get("sql"):
            st.code(result["sql"], language="sql")
        return

    df = result["df"]
    sql_query = result["sql"]
    if sql_query:
        st.code(sql_query, language="sql")

    if df is None or df.empty:
        st.warning("Không có dữ liệu trả về.")
        return

    st.dataframe(df, width='stretch')

    tab1, tab2 = st.tabs(["📊 Biểu đồ", "🔮 Dự báo"])
    with tab1:
        render_smart_chart(df)
    with tab2:
        fig, method = forecast_series(df, periods=st.session_state.get("forecast_periods", 3))
        if fig is None:
         st.info(method)
        else:
         st.plotly_chart(fig, use_container_width=True)
         st.caption(f"Phương pháp: {method}")


# ---------------------------------------------------------
# 7. UI Chính
# ---------------------------------------------------------
st.title("🤖 AI Business Agent for SQL")
st.caption("Kết nối Database MySQL Cloud bất kỳ để truy vấn ngôn ngữ tự nhiên, trực quan hóa và dự báo.")

st.session_state["forecast_periods"] = forecast_periods

if "history" not in st.session_state:
    st.session_state["history"] = []

if len(st.session_state["history"]) > MAX_HISTORY_TURNS:
    st.session_state["history"] = st.session_state["history"][-MAX_HISTORY_TURNS:]

for turn in st.session_state["history"]:
    st.chat_message("user").write(turn["query"])
    with st.chat_message("assistant"):
        render_result(turn)

if not st.session_state.get("connected"):
    st.info("👈 **Hướng dẫn:** Vui lòng nhập thông tin kết nối MySQL Cloud và Gemini API Key ở thanh bên trái để khởi chạy Agent.")
else:
    user_input = st.chat_input("Hỏi bất kỳ điều gì về dữ liệu của bạn...")
    if user_input:
        st.chat_message("user").write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Đang truy vấn & phân tích..."):
                result = run_agent(user_input)
            render_result(result)
        st.session_state["history"].append(result)
