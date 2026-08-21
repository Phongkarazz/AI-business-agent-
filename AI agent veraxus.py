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
from sqlalchemy.pool import StaticPool
from google import genai
from urllib.parse import quote_plus

# ---------------------------------------------------------
# 1. Cấu hình trang & Hằng số
# ---------------------------------------------------------
st.set_page_config(page_title="Universal AI Business Agent", page_icon="🤖", layout="wide")

FORBIDDEN_KEYWORDS = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke"]
TIME_KEYWORDS = ["date", "month", "thang", "quy", "quarter", "nam", "year"]

MODEL_OPTIONS = ["gemini-3.6-flash", "gemini-2.5-flash"]
FORECAST_METHOD_NAME = "Hồi quy tuyến tính (Linear Regression)"  # nguồn duy nhất — tránh lệch nhãn với code thực tế

MAX_TABLES_SCHEMA = 30
MAX_ROWS_CAP = 3000
MAX_HISTORY_TURNS = 15

# ---------------------------------------------------------
# 2. Dữ liệu Demo (cho người dùng chưa có MySQL riêng)
# ---------------------------------------------------------
@st.cache_resource(show_spinner=False)
def build_demo_engine():
    """Tạo 1 SQLite in-memory với dữ liệu mẫu, để bất kỳ ai cũng test được ngay
    mà không cần tự có MySQL — quan trọng cho việc 'đóng gói cho mọi người xài free'."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    rng = np.random.default_rng(42)

    geo_df = pd.DataFrame({
        "GeoID": ["G1", "G2", "G3"],
        "Geo": ["Ha Noi", "Da Nang", "Ho Chi Minh"],
        "Region": ["North", "Central", "South"],
    })
    people_df = pd.DataFrame({
        "SPID": [f"P{i}" for i in range(1, 7)],
        "Salesperson": ["An", "Binh", "Chi", "Dung", "Em", "Phong"],
        "Team": ["Alpha", "Alpha", "Beta", "Beta", "Gamma", "Gamma"],
        "Location": ["Ha Noi", "Ha Noi", "Da Nang", "Da Nang", "Ho Chi Minh", "Ho Chi Minh"],
    })
    products_df = pd.DataFrame({
        "PID": [f"PR{i}" for i in range(1, 7)],
        "Product": ["Dark 70%", "Milk Classic", "White Choco", "Hazelnut", "Almond", "Orange Zest"],
        "Category": ["Dark", "Milk", "White", "Milk", "Dark", "White"],
        "Size": ["Small", "Medium", "Large", "Medium", "Small", "Medium"],
        "Cost_per_box": [3.5, 2.8, 3.0, 3.2, 3.8, 3.1],
    })

    dates = pd.date_range("2023-01-01", "2023-12-31", freq="3D")
    n = len(dates)
    sales_df = pd.DataFrame({
        "SPID": rng.choice(people_df["SPID"], n),
        "GeoID": rng.choice(geo_df["GeoID"], n),
        "PID": rng.choice(products_df["PID"], n),
        "SaleDate": dates,
        "Amount": rng.integers(2000, 15000, n),
        "Customers": rng.integers(5, 60, n),
        "Boxes": rng.integers(10, 200, n),
    })
    # tạo 1 điểm bất thường có chủ đích để test tính năng giải thích outlier
    sales_df.loc[sales_df["SaleDate"].dt.month == 6, "Amount"] *= 3

    geo_df.to_sql("geo", engine, index=False, if_exists="replace")
    people_df.to_sql("people", engine, index=False, if_exists="replace")
    products_df.to_sql("products", engine, index=False, if_exists="replace")
    sales_df.to_sql("sales", engine, index=False, if_exists="replace")
    return engine

# ---------------------------------------------------------
# 3. Hàm tự động trích xuất Schema
# ---------------------------------------------------------
def auto_extract_schema(engine, max_tables: int = MAX_TABLES_SCHEMA) -> str:
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
    if pw:
        msg = msg.replace(pw, "***")
        msg = msg.replace(quote_plus(pw), "***")
    return msg


def read_sql_capped(sql_query: str, engine, cap: int = MAX_ROWS_CAP, chunksize: int = 1000):
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
    return any(k in c.lower() for c in df.columns for k in TIME_KEYWORDS)


def strip_string_literals(sql: str) -> str:
    """Bỏ nội dung bên trong chuỗi ký tự trước khi kiểm tra an toàn — tránh chặn nhầm
    khi giá trị dữ liệu (VD: Product = 'Update Now') chứa từ khóa, hoặc chứa dấu ';' trong literal."""
    sql = re.sub(r"'[^']*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    return sql

# ---------------------------------------------------------
# 4. Sidebar: Cấu hình kết nối
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Cấu hình Kết nối")
    st.caption("Ứng dụng không lưu trữ tài khoản/API Key của bạn.")

    data_mode = st.radio(
        "Nguồn dữ liệu",
        ["🎮 Dùng dữ liệu mẫu (Demo, không cần MySQL)", "🔌 Kết nối MySQL của tôi"],
        index=0,
    )
    use_demo = data_mode.startswith("🎮")

    if not use_demo:
        st.subheader("1. MySQL Cloud Database")
        db_host = st.text_input("Host", placeholder="e.g., mysql-xxx.aivencloud.com")
        db_port = st.text_input("Port", value="3306")
        db_user = st.text_input("User", value="root")
        db_pass = st.text_input("Password", type="password")
        db_name = st.text_input("Database Name", placeholder="e.g., my_business_db")
        use_ssl = st.checkbox("Dùng SSL (bắt buộc với hầu hết MySQL cloud: Aiven, Railway...)", value=True)
    else:
        db_host = db_port = db_user = db_pass = db_name = ""
        use_ssl = False
        st.caption("Dữ liệu mẫu: doanh số chocolate theo tháng, nhân viên, khu vực, sản phẩm (năm 2023).")

    st.subheader("2. Gemini API Key")
    api_key = st.text_input(
        "API Key", type="password",
        help="Lấy key miễn phí tại https://aistudio.google.com/apikey — bấm 'Create API key', copy và dán vào đây."
    )
    model_name = st.selectbox("Model AI", MODEL_OPTIONS, index=0)

    schema_context_input = st.text_area(
        "Mô tả Schema / Nghiệp vụ (Tự động nạp sau khi bấm Kết nối)",
        value=st.session_state.get("schema_context", ""),
        height=180
    )

    forecast_periods = st.slider("Số kỳ dự báo xu hướng", 1, 12, 3)
    connect_btn = st.button("🔌 Kết nối Database & AI", type="primary", use_container_width=True)

# ---------------------------------------------------------
# 5. Kiểm tra Kết nối & Tự động quét Schema
# ---------------------------------------------------------
def try_connect(host, port, user, pw, name, use_ssl):
    connect_args = {"connection_timeout": 10}
    if use_ssl:
        connect_args["ssl_disabled"] = False
    engine = create_engine(
        f"mysql+mysqlconnector://{user}:{quote_plus(pw)}@{host}:{port}/{name}",
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine

if connect_btn:
    if not api_key:
        st.sidebar.error("❌ Vui lòng nhập Gemini API Key!")
    elif not use_demo and not (db_host and db_user and db_name):
        st.sidebar.error("❌ Vui lòng điền đầy đủ Host, User, Database Name!")
    else:
        try:
            if use_demo:
                engine = build_demo_engine()
            else:
                engine = try_connect(db_host, db_port, db_user, db_pass, db_name, use_ssl)

            client = genai.Client(api_key=api_key)
            extracted_schema = auto_extract_schema(engine)
            final_schema = schema_context_input if schema_context_input.strip() else extracted_schema

            st.session_state.update({
                "engine": engine,
                "client": client,
                "model_name": model_name,
                "schema_context": final_schema,
                "connected": True,
                "_db_pass_for_sanitize": db_pass,
                "is_demo": use_demo,
                "sql_dialect": "SQLite" if use_demo else "MySQL",
            })
            st.sidebar.success("✅ Kết nối thành công!")
            st.rerun()
        except Exception as e:
            st.session_state["connected"] = False
            err_display = sanitize_error(str(e), db_pass)
            if "429" in err_display or "RESOURCE_EXHAUSTED" in err_display:
                st.sidebar.error(
                    "🚫 API Key hết quota miễn phí hôm nay.\n\n"
                    "**Cách khắc phục:** vào https://aistudio.google.com/apikey → "
                    "tạo 1 API key mới (miễn phí, không cần thẻ) → dán lại vào ô trên."
                )
            else:
                st.sidebar.error(f"❌ Lỗi kết nối: {err_display}")

# ---------------------------------------------------------
# 6. Core Agent Logic
# ---------------------------------------------------------
def is_safe_select(sql: str) -> bool:
    if not sql:
        return False
    raw = sql.strip().rstrip(";")
    lowered = raw.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False

    no_literals = strip_string_literals(raw)
    if ";" in no_literals:  # chặn stacked queries thật sự, bỏ qua ';' nằm trong chuỗi ký tự
        return False
    no_literals_lower = no_literals.lower()
    if any(re.search(rf"\b{kw}\b", no_literals_lower) for kw in FORBIDDEN_KEYWORDS):
        return False
    return True


def extract_sql(raw: str) -> str:
    """Nếu Gemini trả về kèm giải thích/markdown quanh câu SQL (dễ xảy ra ở các prompt
    yêu cầu tự sửa lỗi), tìm và cắt lấy đúng phần bắt đầu từ SELECT/WITH — tránh bị
    is_safe_select() từ chối oan chỉ vì có chữ thừa ở đầu."""
    if not raw:
        return raw
    lowered = raw.lower()
    candidates = [i for i in (lowered.find("select"), lowered.find("with")) if i != -1]
    if candidates and min(candidates) > 0:
        return raw[min(candidates):].strip()
    return raw.strip()


def call_gemini(prompt: str, max_retries: int = 3):
    client = st.session_state.get("client")
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
                st.error(
                    "🚫 Hết quota Gemini API miễn phí hôm nay.\n\n"
                    "**Cách khắc phục nhanh:** vào https://aistudio.google.com/apikey → "
                    "tạo API key mới (miễn phí) → cập nhật lại ở sidebar và bấm Kết nối lại."
                )
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

    dialect = st.session_state.get("sql_dialect", "MySQL")
    prompt = f"""Dialect SQL: {dialect}
Schema:
{schema_context}
Viết 1 câu SQL SELECT duy nhất, đúng cú pháp {dialect}, cho câu hỏi: {user_query}
Nếu không có GROUP BY, bắt buộc thêm LIMIT 1000 để tránh trả về quá nhiều dữ liệu.
Chỉ trả về SQL thuần, không markdown, không giải thích."""
    sql_query = call_gemini(prompt)
    sql_query = extract_sql(sql_query) if sql_query else sql_query
    if not sql_query:
        result["error"] = "Không thể tạo SQL từ mô hình AI."
        return result

    for attempt in range(1, 4):
        result["logs"].append(f"[Lần {attempt}] SQL: {sql_query}")

        if not is_safe_select(sql_query):
            result["error"] = "Câu lệnh SQL không an toàn (Chỉ chấp nhận lệnh SELECT/WITH đơn, không nhiều câu lệnh)."
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

            fix_prompt = f"""Dialect SQL: {dialect}
Schema: {schema_context}
Câu hỏi: '{user_query}'
SQL lỗi/chưa đủ: {sql_query}
Lý do: {check.get('ly_do', '')}
Viết lại SQL chuẩn xác, đúng cú pháp {dialect}.
Chỉ trả về SQL thuần, không markdown, không giải thích, không thêm bất kỳ chữ nào khác ngoài câu lệnh SQL."""
            fixed = call_gemini(fix_prompt)
            sql_query = extract_sql(fixed) if fixed else sql_query

        except Exception as e:
            error_msg = sanitize_error(str(e), db_pass)
            result["logs"].append(f"❌ Lỗi thực thi SQL: {error_msg}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {error_msg}"
                result["sql"] = sql_query
                return result

            fix_prompt = f"""Dialect SQL: {dialect}
Schema: {schema_context}
SQL lỗi: {sql_query}
Lỗi: {error_msg}
Câu hỏi: '{user_query}'
Sửa lại SQL cho đúng cú pháp {dialect}.
Chỉ trả về SQL thuần, không markdown, không giải thích, không thêm bất kỳ chữ nào khác ngoài câu lệnh SQL."""
            fixed = call_gemini(fix_prompt)
            sql_query = extract_sql(fixed) if fixed else sql_query

    return result

# ---------------------------------------------------------
# 7. Trực quan hóa
# ---------------------------------------------------------
def get_axis_columns(df: pd.DataFrame):
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = [c for c in df.columns if c not in num_cols]
    time_col = next((c for c in df.columns if any(k in c.lower() for k in TIME_KEYWORDS)), None)
    return num_cols, cat_cols, time_col


def render_smart_chart(df: pd.DataFrame, chart_override: str, turn_id: str):
    cols = df.columns.tolist()
    if len(cols) < 2:
        st.info("Dữ liệu cần tối thiểu 2 cột để vẽ biểu đồ.")
        return

    num_cols, cat_cols, time_col = get_axis_columns(df)

    try:
        if chart_override == "Tự động":
            if time_col and num_cols:
                chosen = "Line"
            elif cat_cols and num_cols:
                chosen = "Bar"
            elif len(num_cols) >= 2:
                chosen = "Scatter"
            else:
                st.info("Không tìm thấy dạng biểu đồ phù hợp.")
                return
        else:
            chosen = chart_override

        if chosen == "Line" and (time_col or num_cols):
            x_col = time_col or (cat_cols[0] if cat_cols else df.columns[0])
            y_cols = [c for c in num_cols if c != x_col] or num_cols
            fig = px.line(df, x=x_col, y=y_cols, markers=True, title=f"Xu hướng theo {x_col}")
        elif chosen == "Area" and (time_col or num_cols):
            x_col = time_col or (cat_cols[0] if cat_cols else df.columns[0])
            y_cols = [c for c in num_cols if c != x_col] or num_cols
            fig = px.area(df, x=x_col, y=y_cols, title=f"Xu hướng (Area) theo {x_col}")
        elif chosen == "Bar" and cat_cols and num_cols:
            fig = px.bar(df, x=cat_cols[0], y=num_cols[0], title=f"{num_cols[0]} theo {cat_cols[0]}")
        elif len(num_cols) >= 2:
            fig = px.scatter(df, x=num_cols[0], y=num_cols[1], title="Biểu đồ phân tích tương quan")
        else:
            st.info("Không đủ dữ liệu phù hợp cho loại biểu đồ đã chọn.")
            return

        st.plotly_chart(fig, width='stretch', key=f"chart_{turn_id}")
    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {e}")

# ---------------------------------------------------------
# 8. Dự báo (thuật toán xác định) & Phát hiện bất thường (AI)
# ---------------------------------------------------------
def classify_x_axis(df_sorted: pd.DataFrame, x_col: str):
    """Phân loại trục X dựa trên GIÁ TRỊ thật, không chỉ tên cột — tránh nhầm giữa
    ngày tháng thật (VD '2023-01', có thể tính tiếp tương lai) với số nguyên bị giới hạn
    (VD tháng 1-12, quý 1-4 — không được cộng dồn vượt giới hạn)."""
    series = df_sorted[x_col]

    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.notna().all():
        return "date", parsed

    if pd.api.types.is_numeric_dtype(series):
        vals = series.dropna()
        name = x_col.lower()
        if not vals.empty and vals.min() >= 1 and vals.max() <= 12 and any(k in name for k in ["month", "thang"]):
            return "bounded_month", None
        if not vals.empty and vals.min() >= 1 and vals.max() <= 4 and any(k in name for k in ["quy", "quarter"]):
            return "bounded_quarter", None
        return "numeric", None

    return "categorical", None


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

    kind, parsed_dates = classify_x_axis(df_sorted, x_col)
    hist_x = df_sorted[x_col].tolist()

    if kind == "date":
        # Giữ đúng định dạng chuỗi gốc (VD "YYYY-MM" hay "YYYY-MM-DD") để trục X nhất quán
        sample = str(df_sorted[x_col].iloc[-1])
        date_fmt = "%Y-%m" if re.match(r"^\d{4}-\d{2}$", sample) else "%Y-%m-%d"

        last_date = parsed_dates.iloc[-1]
        freq = pd.infer_freq(parsed_dates)
        if not freq and n >= 2:
            diff = parsed_dates.iloc[-1] - parsed_dates.iloc[-2]
            future_dates = [last_date + diff * (i + 1) for i in range(periods)]
        elif freq:
            future_dates = pd.date_range(start=last_date, periods=periods + 1, freq=freq)[1:]
        else:
            future_dates = [last_date] * periods
        future_x = [d.strftime(date_fmt) for d in future_dates]

    elif kind in ("bounded_month", "bounded_quarter"):
        # Chu kỳ có giới hạn (tháng 1-12 / quý 1-4) — không được cộng dồn vượt giới hạn,
        # dùng nhãn tương đối thay vì số vô nghĩa (VD tháng "14")
        future_x = [f"Kỳ +{i+1}" for i in range(periods)]

    elif kind == "numeric":
        step = 1
        if n >= 2:
            step = df_sorted[x_col].iloc[-1] - df_sorted[x_col].iloc[-2]
            if step == 0:
                step = 1
        last_x = df_sorted[x_col].iloc[-1]
        future_x = [last_x + step * (i + 1) for i in range(periods)]

    else:  # categorical
        future_x = [f"Kỳ +{i+1}" for i in range(periods)]

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
    return fig, FORECAST_METHOD_NAME


def detect_outliers(df: pd.DataFrame, y_col: str) -> pd.DataFrame:
    q1, q3 = df[y_col].quantile([0.25, 0.75])
    iqr = q3 - q1
    if iqr == 0:
        return df.iloc[0:0]
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return df[(df[y_col] < lower) | (df[y_col] > upper)]


def explain_anomalies(user_query: str, x_col: str, y_col: str, outliers_df: pd.DataFrame):
    points = outliers_df[[x_col, y_col]].to_dict(orient="records")
    prompt = f"""
Bạn là chuyên gia phân tích dữ liệu kinh doanh.
Câu hỏi gốc của người dùng: "{user_query}"
Các điểm bất thường (outlier, theo phương pháp IQR) phát hiện trên trục {x_col}, giá trị {y_col}: {points}
Đưa ra 1-2 câu nhận xét/giả thuyết ngắn gọn về nguyên nhân kinh doanh có thể xảy ra (VD: mùa vụ, khuyến mãi, sự kiện...).
Chỉ trả lời 1 đoạn văn ngắn, không markdown, không liệt kê gạch đầu dòng.
"""
    return call_gemini(prompt)

# ---------------------------------------------------------
# 9. Hiển thị kết quả (mỗi lượt có turn_id riêng để widget không trùng key)
# ---------------------------------------------------------
def render_result(result: dict, turn_id: str):
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
    st.download_button("⬇️ Tải CSV", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"ket_qua_{turn_id}.csv", mime="text/csv", key=f"csv_{turn_id}")

    tab1, tab2 = st.tabs(["📊 Biểu đồ", "🔮 Dự báo"])

    with tab1:
        chart_override = st.selectbox(
            "Loại biểu đồ", ["Tự động", "Line", "Bar", "Area", "Scatter"],
            key=f"charttype_{turn_id}"
        )
        render_smart_chart(df, chart_override, turn_id)

        num_cols, _, time_col = get_axis_columns(df)
        if time_col and num_cols:
            y_col = next((c for c in num_cols if c != time_col), num_cols[0])
            outliers = detect_outliers(df, y_col)
            if not outliers.empty:
                if st.button(f"🔍 AI giải thích {len(outliers)} điểm bất thường", key=f"outlier_{turn_id}"):
                    with st.spinner("AI đang phân tích..."):
                        explanation = explain_anomalies(result["query"], time_col, y_col, outliers)
                    if explanation:
                        st.info(f"🤖 **Nhận xét AI:** {explanation}")

    with tab2:
        st.caption(
            "🧮 Dự báo dùng thuật toán hồi quy tuyến tính xác định (deterministic) — không phải AI 'đoán' số. "
            "Lựa chọn này đảm bảo kết quả nhất quán, có thể kiểm chứng bằng toán học. "
            "AI (Gemini) chỉ đảm nhiệm việc sinh SQL, tự sửa lỗi, kiểm định QA, và giải thích bất thường (tab Biểu đồ)."
        )
        fig, method = forecast_series(df, periods=st.session_state.get("forecast_periods", 3))
        if fig is None:
            st.info(method)
        else:
            st.plotly_chart(fig, width='stretch', key=f"forecast_{turn_id}")
            st.caption(f"Phương pháp: {method}")


# ---------------------------------------------------------
# 10. UI Chính
# ---------------------------------------------------------
st.title("🤖 AI Business Agent for SQL")
st.caption("Kết nối Database MySQL Cloud bất kỳ (hoặc dùng dữ liệu mẫu) để truy vấn ngôn ngữ tự nhiên, trực quan hóa và dự báo.")

st.session_state["forecast_periods"] = forecast_periods

if "history" not in st.session_state:
    st.session_state["history"] = []

if len(st.session_state["history"]) > MAX_HISTORY_TURNS:
    st.session_state["history"] = st.session_state["history"][-MAX_HISTORY_TURNS:]

for i, turn in enumerate(st.session_state["history"]):
    st.chat_message("user").write(turn["query"])
    with st.chat_message("assistant"):
        render_result(turn, turn_id=f"hist{i}")

if not st.session_state.get("connected"):
    st.info("👈 **Hướng dẫn:** Chọn nguồn dữ liệu (demo hoặc MySQL riêng), nhập Gemini API Key, rồi bấm Kết nối.")
else:
    if st.session_state.get("is_demo"):
        st.caption("🎮 Đang dùng dữ liệu mẫu — thử hỏi: *\"Doanh số theo từng tháng năm 2023\"*")
    user_input = st.chat_input("Hỏi bất kỳ điều gì về dữ liệu của bạn...")
    if user_input:
        st.chat_message("user").write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Đang truy vấn & phân tích..."):
                result = run_agent(user_input)
            render_result(result, turn_id=f"new{len(st.session_state['history'])}")
        st.session_state["history"].append(result)
