import os
import re
import json
import time
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sqlite3
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
st.set_page_config(page_title="Universal AI Business Agent", page_icon="🤖", layout="wide")

FORBIDDEN_KEYWORDS = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke"]
# ---------------------------------------------------------
# 2. Hàm tự động trích xuất Schema từ Database của người dùng
# ---------------------------------------------------------
def auto_extract_schema(engine) -> str:
    """Tự động đọc danh sách Bảng và Cột từ MySQL để Gemini hiểu Database bất kỳ."""
    try:
        inspector = inspect(engine)
        schema_text = "Cơ sở dữ liệu bao gồm các bảng và cột sau:\n"
        for table_name in inspector.get_table_names():
            schema_text += f"- Bảng `{table_name}`: "
            columns = inspector.get_columns(table_name)
            col_names = [f"{col['name']} ({str(col['type'])})" for col in columns]
            schema_text += ", ".join(col_names) + "\n"
        return schema_text
    except Exception as e:
        return f"Không thể tự động đọc schema: {e}"

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

    st.subheader("2. Gemini API Key")
    api_key = st.text_input("API Key", type="password", help="Lấy key miễn phí tại Google AI Studio")
    model_name = st.selectbox("Model AI", ["gemini-2.5-flash", "gemini-3.6-flash"], index=0)
    
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
def try_connect(host, port, user, pw, name):
    engine = create_engine(
        f"mysql+mysqlconnector://{user}:{quote_plus(pw)}@{host}:{port}/{name}"
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine

if connect_btn:
    if not (db_host and db_user and db_name and api_key):
        st.sidebar.error("❌ Vui lòng điền đầy đủ Host, User, Database Name và API Key!")
    else:
        try:
            engine = try_connect(db_host, db_port, db_user, db_pass, db_name)
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
            })
            st.sidebar.success("✅ Kết nối thành công!")
            st.rerun()
        except Exception as e:
            st.session_state["connected"] = False
            st.sidebar.error(f"❌ Lỗi kết nối: {e}")

# ---------------------------------------------------------
# 5. Hàm xử lý Core Agent
# ---------------------------------------------------------
def is_safe_select(sql: str) -> bool:
    if not sql:
        return False
    lowered = sql.strip().lower()
    if not lowered.startswith("select") and not lowered.startswith("with"):
        return False
    if any(re.search(rf"\b{kw}\b", lowered) for kw in FORBIDDEN_KEYWORDS):
        return False
    return True


def call_gemini(prompt: str, max_retries: int = 3):
    client = st.session_state["client"]
    model_name = st.session_state["model_name"]
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

    prompt = f"Schema:\n{schema_context}\nViết 1 câu MySQL SELECT duy nhất cho câu hỏi: {user_query}. Chỉ trả về SQL thuần."
    sql_query = call_gemini(prompt)
    if not sql_query:
        result["error"] = "Không thể tạo SQL từ mô hình AI."
        return result

    for attempt in range(1, 4):
        result["logs"].append(f"[Lần {attempt}] SQL: {sql_query}")

        if not is_safe_select(sql_query):
            result["error"] = "Câu lệnh SQL không an toàn (Chỉ chấp nhận lệnh SELECT)."
            result["sql"] = sql_query
            return result

        try:
            df = pd.read_sql(sql_query, engine)
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
    time_hint = any(k in c.lower() for c in cols for k in ["date", "month", "thang", "quy", "quarter", "nam", "year"])

    try:
        if time_hint and num_cols:
            x_col = next(c for c in cols if any(k in c.lower() for k in ["date", "month", "thang", "quy", "quarter", "nam", "year"]))
            y_cols = [c for c in num_cols if c != x_col] or num_cols
            fig = px.line(df, x=x_col, y=y_cols, markers=True, title=f"Xu hướng theo {x_col}")
        elif cat_cols and num_cols:
            fig = px.bar(df, x=cat_cols[0], y=num_cols[0], title=f"{num_cols[0]} theo {cat_cols[0]}")
        elif len(num_cols) >= 2:
            fig = px.scatter(df, x=num_cols[0], y=num_cols[1], title="Biểu đồ phân tích tương quan")
        else:
            st.info("Không tìm thấy dạng biểu đồ phù hợp.")
            return
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {e}")


def forecast_series(df: pd.DataFrame, periods: int = 3):
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if not num_cols or len(df) < 3:
        return None, "Cần tối thiểu 3 dòng dữ liệu dạng số để dự báo."

    time_keywords = ["date", "month", "thang", "quy", "quarter", "nam", "year"]
    x_col = next((c for c in df.columns if any(k in c.lower() for k in time_keywords)), None)
    if x_col is None:
        non_numeric = [c for c in df.columns if c not in num_cols]
        x_col = non_numeric[0] if non_numeric else df.columns[0]

    y_candidates = [c for c in num_cols if c != x_col]
    y_col = y_candidates[0] if y_candidates else num_cols[0]

    df_sorted = df.copy().reset_index(drop=True)
    y = df_sorted[y_col].values.astype(float)
    n = len(y)
    x_idx = np.arange(n)
    coeffs = np.polyfit(x_idx, y, 1)
    future_idx = np.arange(n, n + periods)
    future_vals = np.polyval(coeffs, future_idx)

    # Nếu trục X là số (VD tháng 1-12), nối tiếp số thật để đường liền mạch
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
    # Nối điểm cuối thực tế làm điểm đầu dự báo -> 2 đường liền mạch, không đứt quãng
    bridge_x = [hist_x[-1]] + future_x
    bridge_y = [y[-1]] + list(future_vals)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_x, y=y, mode="lines+markers", name="Thực tế",
        line=dict(color="#4C9AFF")
    ))
    fig.add_trace(go.Scatter(
        x=bridge_x, y=bridge_y, mode="lines+markers", name="Dự báo",
        line=dict(color="#FF6B6B", dash="dash")
    ))
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

    st.dataframe(df, use_container_width=True)

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
