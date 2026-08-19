import os
import re
import json
import time
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text
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
st.set_page_config(page_title="Awesome Chocolates AI Agent", page_icon="🍫", layout="wide")

FORBIDDEN_KEYWORDS = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke"]
FORECAST_KEYWORDS = ["dự báo", "dự đoán", "forecast", "tương lai", "xu hướng"]

DEFAULT_SCHEMA = """Database có 4 bảng:
1. sales(SPID VARCHAR, GeoID VARCHAR, PID VARCHAR, SaleDate DATETIME, Amount INT, Customers INT, Boxes INT)
2. people(Salesperson TEXT, SPID VARCHAR PRIMARY KEY, Team TEXT, Location TEXT)
3. products(PID VARCHAR PRIMARY KEY, Product TEXT, Category TEXT, Size TEXT, Cost_per_box DOUBLE)
4. geo(GeoID VARCHAR PRIMARY KEY, Geo TEXT, Region TEXT)
Mối quan hệ:
- sales.SPID = people.SPID
- sales.PID = products.PID
- sales.GeoID = geo.GeoID

Lưu ý quan trọng: chỉ viết SQL để LẤY dữ liệu thực tế (SELECT thuần, không UNION thêm
dòng dự báo/giả định). Ứng dụng đã có tab "Dự báo" riêng để tự tính dự báo từ dữ liệu
trả về — vì vậy KHÔNG tự thêm các dòng dự báo/ước tính tương lai vào kết quả SQL."""

# ---------------------------------------------------------
# 2. Sidebar: cấu hình kết nối (KHÔNG hardcode key/mật khẩu)
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Cấu hình")

    st.subheader("MySQL")
    db_host = st.text_input("Host", value=os.getenv("DB_HOST", "localhost"),
                             help="Nếu app đã deploy công khai (Streamlit Cloud), 'localhost' KHÔNG hoạt động "
                                  "— cần host MySQL truy cập được qua internet (VD: MySQL cloud miễn phí).")
    db_user = st.text_input("User", value=os.getenv("DB_USER", "root"))
    db_pass = st.text_input("Password", type="password", value=os.getenv("DB_PASS", ""))
    db_name = st.text_input("Database", value=os.getenv("DB_NAME", "awesome chocolates"))

    st.subheader("Gemini API")
    api_key = st.text_input("API Key", type="password", value=os.getenv("GEMINI_API_KEY", ""))
    model_name = st.text_input("Model", value="gemini-3.6-flash")

    with st.expander("Schema context (nâng cao)"):
        schema_context = st.text_area("Mô tả bảng cho AI", value=DEFAULT_SCHEMA, height=180)

    forecast_periods = st.slider("Số kỳ dự báo", 1, 12, 3)
    connect_btn = st.button("🔌 Kết nối", width='stretch')

# ---------------------------------------------------------
# 3. Kết nối — có TEST THẬT, không chỉ tạo Engine
# ---------------------------------------------------------
def try_connect(host, user, pw, name):
    engine = create_engine(
        f"mysql+mysqlconnector://{user}:{quote_plus(pw)}@{host}",
        connect_args={"database": name}
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine

if connect_btn:
    try:
        engine = try_connect(db_host, db_user, db_pass, db_name)
        client = genai.Client(api_key=api_key)
        st.session_state.update({
            "engine": engine,
            "client": client,
            "model_name": model_name,
            "schema_context": schema_context,
            "connected": True,
        })
        st.sidebar.success("✅ Kết nối thành công!")
    except Exception as e:
        st.session_state["connected"] = False
        st.sidebar.error(f"❌ Lỗi kết nối: {e}")

# ---------------------------------------------------------
# 4. Hàm lõi Agent
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
                st.error("🚫 Đã hết quota Gemini API miễn phí hôm nay. Đợi reset hoặc bật billing tại "
                          "https://aistudio.google.com/apikey")
                return None
            if "503" in err or "UNAVAILABLE" in err:
                wait = 3 * (attempt + 1)
                st.toast(f"⏳ Server bận, thử lại sau {wait}s... ({attempt + 1}/{max_retries})")
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

Kiểm tra SQL có trả lời ĐẦY ĐỦ câu hỏi không (chú ý cột người dùng nhắc tới nhưng
SQL không dùng, có thể do không tồn tại và bị âm thầm bỏ qua).
Trả về DUY NHẤT JSON: {{"day_du": true/false, "ly_do": "..."}}
"""
    res = call_gemini(prompt)
    if not res:
        return {"day_du": True, "ly_do": "Bỏ qua self-check (lỗi/quota)."}
    try:
        cleaned = res.strip().strip("`").replace("json\n", "").strip()
        return json.loads(cleaned)
    except Exception:
        return {"day_du": True, "ly_do": "Không parse được self-check, bỏ qua."}


def run_agent(user_query: str):
    result = {"query": user_query, "df": None, "sql": None, "logs": [], "error": None}
    schema_context = st.session_state["schema_context"]
    engine = st.session_state["engine"]

    prompt = f"Schema:\n{schema_context}\nViết 1 câu MySQL SELECT duy nhất cho câu hỏi: {user_query}. " \
              f"Chỉ trả về SQL thuần, không markdown."
    sql_query = call_gemini(prompt)
    if not sql_query:
        result["error"] = "Không thể tạo SQL (model quá tải/hết quota)."
        return result

    for attempt in range(1, 4):
        result["logs"].append(f"[Lần {attempt}] SQL: {sql_query}")

        if not is_safe_select(sql_query):
            result["error"] = "Câu lệnh SQL không an toàn (không phải SELECT). Đã hủy."
            result["sql"] = sql_query
            return result

        try:
            df = pd.read_sql(sql_query, engine)
            check = self_check(user_query, sql_query, df)

            if check.get("day_du", True):
                result["logs"].append(f"✅ Self-check OK: {check.get('ly_do', '')}")
                result["df"] = df
                result["sql"] = sql_query
                return result

            result["logs"].append(f"⚠️ Self-check phát hiện vấn đề: {check.get('ly_do', '')}")
            if attempt == 3:
                result["df"] = df
                result["sql"] = sql_query
                result["logs"].append("Đã hết lần thử, trả kết quả hiện tại (có thể chưa đầy đủ).")
                return result

            fix_prompt = f"""Schema: {schema_context}
Câu hỏi gốc: "{user_query}"
SQL trước: {sql_query}
Reviewer đánh giá CHƯA đầy đủ vì: {check.get('ly_do', '')}
Viết lại SQL cho đúng và đầy đủ hơn. Chỉ trả về SQL, không markdown."""
            new_sql = call_gemini(fix_prompt)
            if not new_sql:
                result["df"] = df
                result["sql"] = sql_query
                result["logs"].append("Không thể sửa thêm (model quá tải). Trả kết quả hiện tại.")
                return result
            sql_query = new_sql

        except Exception as e:
            error_msg = str(e)
            result["logs"].append(f"❌ Lỗi SQL: {error_msg}")
            if attempt == 3:
                result["error"] = f"Đã thử sửa 3 lần nhưng vẫn lỗi: {error_msg}"
                result["sql"] = sql_query
                return result

            fix_prompt = f"""Schema: {schema_context}
SQL bị lỗi: {sql_query}
Lỗi MySQL: {error_msg}
Câu hỏi gốc: "{user_query}"
Sửa lại SQL cho đúng. Chỉ trả về SQL, không markdown."""
            new_sql = call_gemini(fix_prompt)
            if not new_sql:
                result["error"] = "Không thể sửa SQL (model quá tải/hết quota)."
                result["sql"] = sql_query
                return result
            sql_query = new_sql

    return result


# ---------------------------------------------------------
# 5. Trực quan hóa
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
            y_cols = [c for c in num_cols if c != x_col] or num_cols  # loại x_col khỏi trục Y nếu nó cũng là cột số
            fig = px.line(df, x=x_col, y=y_cols, markers=True, title=f"Xu hướng theo {x_col}")
        elif cat_cols and num_cols:
            fig = px.bar(df, x=cat_cols[0], y=num_cols[0], title=f"{num_cols[0]} theo {cat_cols[0]}")
        elif len(num_cols) >= 2:
            fig = px.scatter(df, x=num_cols[0], y=num_cols[1], title="Biểu đồ phân tích")
        else:
            st.info("Không xác định được dạng biểu đồ phù hợp cho dữ liệu này.")
            return
        st.plotly_chart(fig, width='stretch')
    except Exception as e:
        st.info(f"Không thể vẽ biểu đồ tự động: {e}")


# ---------------------------------------------------------
# 6. Dự báo — xử lý cả ngày thật lẫn cột tháng/quý dạng số
# ---------------------------------------------------------
def forecast_series(df: pd.DataFrame, periods: int = 3):
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if not num_cols or len(df) < 3:
        return None, "Cần ít nhất 3 dòng dữ liệu số để dự báo."

    time_keywords = ["date", "month", "thang", "quy", "quarter", "nam", "year"]
    x_col = next((c for c in df.columns if any(k in c.lower() for k in time_keywords)), None)
    if x_col is None:
        non_numeric = [c for c in df.columns if c not in num_cols]
        x_col = non_numeric[0] if non_numeric else df.columns[0]
    y_candidates = [c for c in num_cols if c != x_col]  # loại x_col khỏi ứng viên trục Y
    y_col = y_candidates[0] if y_candidates else num_cols[0]

    df_sorted = df.copy()
    is_real_date = pd.api.types.is_datetime64_any_dtype(df_sorted[x_col]) or "date" in x_col.lower()

    if is_real_date and HAS_STATSMODELS:
        try:
            df_sorted[x_col] = pd.to_datetime(df_sorted[x_col], errors="coerce")
            df_sorted = df_sorted.dropna(subset=[x_col]).sort_values(x_col)
            ts = df_sorted.set_index(x_col)[y_col]
            model = ExponentialSmoothing(ts, trend="add", initialization_method="estimated").fit()
            future_idx = pd.date_range(start=ts.index[-1], periods=periods + 1, freq="ME")[1:]
            future_vals = model.forecast(periods)

            hist = pd.DataFrame({x_col: ts.index, y_col: ts.values, "Loại": "Thực tế"})
            fut = pd.DataFrame({x_col: future_idx, y_col: future_vals.values, "Loại": "Dự báo"})
            combined = pd.concat([hist, fut], ignore_index=True)
            return combined, "Holt-Winters Exponential Smoothing"
        except Exception:
            pass

    df_sorted = df_sorted.reset_index(drop=True)
    y = df_sorted[y_col].values.astype(float)
    x_idx = np.arange(len(y))
    coeffs = np.polyfit(x_idx, y, 1)
    future_idx = np.arange(len(y), len(y) + periods)
    future_vals = np.polyval(coeffs, future_idx)

    x_labels_hist = df_sorted[x_col].astype(str).tolist()
    x_labels_future = [f"Kỳ +{i+1}" for i in range(periods)]

    hist = pd.DataFrame({x_col: x_labels_hist, y_col: y, "Loại": "Thực tế"})
    fut = pd.DataFrame({x_col: x_labels_future, y_col: future_vals, "Loại": "Dự báo"})
    combined = pd.concat([hist, fut], ignore_index=True)
    return combined, "Hồi quy tuyến tính (linear regression)"


# ---------------------------------------------------------
# 7. Hiển thị 1 lượt hỏi-đáp
# ---------------------------------------------------------
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
        combined, method = forecast_series(df, periods=st.session_state.get("forecast_periods", 3))
        if combined is None:
            st.info(method)
        else:
            x_col = [c for c in combined.columns if c != "Loại"][0]
            y_col = [c for c in combined.columns if c not in ("Loại", x_col)][0]
            fig = px.line(combined, x=x_col, y=y_col, color="Loại", markers=True,
                          title=f"Dự báo ({method})")
            st.plotly_chart(fig, width='stretch')
            st.caption(f"Phương pháp: {method}. Đây là ước tính xu hướng, chỉ mang tính tham khảo.")


# ---------------------------------------------------------
# 8. UI chính — có lưu lịch sử chat
# ---------------------------------------------------------
st.title("🍫 Awesome Chocolates - AI Business Agent")
st.caption("Trợ lý phân tích dữ liệu: tự động truy vấn SQL, tự sửa lỗi, trực quan hóa & dự báo.")

if not HAS_STATSMODELS:
    st.info("ℹ️ Chưa cài `statsmodels` — dự báo sẽ dùng hồi quy tuyến tính đơn giản thay vì Holt-Winters. "
            "Cài thêm bằng `pip install statsmodels` nếu muốn dự báo chính xác hơn cho dữ liệu theo ngày thật.")

st.session_state["forecast_periods"] = forecast_periods

with st.sidebar:
    st.divider()
    if st.session_state.get("connected"):
        st.success("Database: Kết nối thành công")
        st.info(f"Mô hình AI: {st.session_state.get('model_name', '')}")
    else:
        st.warning("Chưa kết nối. Nhập thông tin và bấm Kết nối.")

if "history" not in st.session_state:
    st.session_state["history"] = []

for turn in st.session_state["history"]:
    st.chat_message("user").write(turn["query"])
    with st.chat_message("assistant"):
        render_result(turn)

if not st.session_state.get("connected"):
    st.info("👈 Nhập thông tin kết nối MySQL và Gemini API Key ở sidebar, rồi bấm **Kết nối** để bắt đầu.")
else:
    user_input = st.chat_input("Nhập câu hỏi (VD: 'Thống kê doanh số theo tháng và dự báo tháng tới')...")
    if user_input:
        st.chat_message("user").write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Đang xử lý..."):
                result = run_agent(user_input)
            render_result(result)
        st.session_state["history"].append(result)
