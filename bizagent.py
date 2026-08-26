import os
import sys
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

try:
    from openai import OpenAI as _OpenAIClient  # dùng cho Qwen (DashScope có API tương thích OpenAI)
except ImportError:
    _OpenAIClient = None

# ---------------------------------------------------------
# 0. Ép UTF-8 cho toàn bộ môi trường (tránh lỗi 'ascii' codec
#    với tiếng Việt trên các container có locale mặc định C/POSIX)
# ---------------------------------------------------------
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ---------------------------------------------------------
# 1. Cấu hình trang & Hằng số
# ---------------------------------------------------------
st.set_page_config(page_title="Universal AI Business Agent", page_icon="🤖", layout="wide")

FORBIDDEN_KEYWORDS = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke"]
TIME_KEYWORDS = ["date", "month", "thang", "quy", "quarter", "nam", "year"]
BOUNDED_PERIOD_KEYWORDS = ["month", "thang", "quy", "quarter"]  # chu kỳ có giới hạn (1-12, 1-4), không nên nối số thô khi dự báo

# Các cột dạng định danh (ID) — dù kiểu số nhưng KHÔNG mang ý nghĩa thống kê/đo lường,
# nên phải loại khỏi trục giá trị (Y) của biểu đồ và khỏi mô hình dự báo.
ID_LIKE_REGEX = re.compile(r'(^|_)(id|no|code|key|num|sn)$', re.IGNORECASE)

# Các cột có tên gợi ý là nhãn nghiệp vụ dễ đọc (ưu tiên làm label trục X thay vì cột ID)
NAME_LIKE_REGEX = re.compile(r'(name|ten|title|category|product|team|region|department|dept)', re.IGNORECASE)

PROVIDER_CONFIGS = {
    "Gemini (Google)": {
        "models": ["gemini-3.6-flash", "gemini-2.5-flash"],
        "key_help": "Lấy API key miễn phí tại aistudio.google.com/apikey.",
        "key_placeholder": "AIza...",
        "free_tier_note": "Free tier: giới hạn theo phút/ngày, dễ hết quota nếu dùng nhiều.",
    },
    "Qwen (Alibaba Cloud)": {
        "models": ["qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct", "qwen-max"],
        "key_help": "Lấy API key miễn phí tại bailian.console.alibabacloud.com (gói dùng thử ~1 triệu token miễn phí).",
        "key_placeholder": "sk-...",
        "free_tier_note": "Free tier hào phóng hơn Gemini — phù hợp để tránh 'đốt tiền'/hết quota khi test nhiều.",
    },
}
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"  # endpoint quốc tế cho Qwen

# Các alias host phổ biến khi kết nối MySQL "local" — thử lần lượt để tăng khả năng
# thành công tùy môi trường chạy (máy thật, Docker, WSL...).
LOCAL_HOST_ALIASES = ["localhost", "127.0.0.1", "host.docker.internal"]
FORECAST_METHOD_NAME = "Hồi quy tuyến tính (Linear Regression)"  # nguồn duy nhất — tránh lệch nhãn với code thực tế

MAX_TABLES_SCHEMA = 30
MAX_ROWS_CAP = 3000
MAX_BAR_CATEGORIES = 30  # Bar chart vẽ quá nhiều cột (VD: 1000 dòng) sẽ thành "bức tường vạch" không đọc được
MAX_HISTORY_TURNS = 15


def is_id_like(col_name: str) -> bool:
    """True nếu tên cột trông giống định danh (emp_no, GeoID, product_code...)."""
    return bool(ID_LIKE_REGEX.search(col_name.strip()))


def notify(message: str, detail: str = None, icon: str = "⚠️", toast_only: bool = False):
    """Hiển thị lỗi/cảnh báo gọn gàng bằng toast góc màn hình thay vì banner đỏ
    to chiếm giữa khung chat — giữ trải nghiệm UI sạch sẽ."""
    st.toast(message, icon=icon)
    if not toast_only:
        with st.chat_message("assistant") if False else st.container():
            st.caption(f"{icon} {message}")
            if detail:
                with st.expander("Xem chi tiết kỹ thuật", expanded=False):
                    st.code(detail)

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


def find_time_column(df: pd.DataFrame):
    """Tìm cột thời gian THẬT SỰ hợp lệ, thay vì chỉ khớp tên theo từ khóa.
    Ưu tiên: (1) dtype datetime gốc, (2) tên khớp từ khóa thời gian VÀ parse
    thành công phần lớn giá trị. Luôn loại các cột dạng ID (emp_no, GeoID...)
    để tránh vẽ/dự báo nhầm trên mã định danh."""
    # 1. Cột có dtype datetime sẵn
    dt_cols = df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns.tolist()
    dt_cols = [c for c in dt_cols if not is_id_like(c)]
    if dt_cols:
        return dt_cols[0]

    # 2. Cột tên khớp từ khóa thời gian, không phải ID, và parse được thành ngày
    candidates = [c for c in df.columns if any(k in c.lower() for k in TIME_KEYWORDS) and not is_id_like(c)]
    for c in candidates:
        try:
            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                return c
        except Exception:
            continue
    return None


def has_time_dimension(df: pd.DataFrame) -> bool:
    return find_time_column(df) is not None


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
        st.subheader("1. MySQL Database")
        run_local = st.checkbox(
            "🖥️ Database chạy trên máy Local (localhost)",
            value=False,
            help="Tự động điền Host = localhost và thử các alias thay thế (127.0.0.1, host.docker.internal)."
        )

        if run_local:
            st.info(
                "ℹ️ **Lưu ý quan trọng:** \"localhost\" chỉ hoạt động nếu **chính app Streamlit này** đang chạy "
                "trên **cùng máy tính** với MySQL — tức là bạn chạy bằng lệnh `streamlit run app.py` ngay trên "
                "máy của mình. Nếu app đang chạy trên Streamlit Community Cloud (server của Streamlit trên internet), "
                "server đó **không thể** thấy \"localhost\" của máy bạn — đây là giới hạn mạng vật lý, không phải lỗi code. "
                "Trong trường hợp đó, vẫn cần dùng tunnel (ngrok/Pinggy) hoặc MySQL cloud như trước."
            )
            db_host = st.text_input("Host", value="localhost")
        else:
            db_host = st.text_input("Host", placeholder="e.g., mysql-xxx.aivencloud.com")

        db_port_raw = st.text_input("Port", value="3306")
        db_user = st.text_input("User", value="root")
        db_pass = st.text_input("Password", type="password")
        db_name = st.text_input("Database Name", placeholder="e.g., my_business_db")
        use_ssl = st.checkbox(
            "Dùng SSL (bắt buộc với hầu hết MySQL cloud: Aiven, Railway...)",
            value=not run_local  # local thường không cần SSL
        )

        # Làm sạch input: loại khoảng trắng thừa và ký tự lạ hay bị dán nhầm
        # (VD: copy nguyên dòng log "Host | Port: 3306" khiến Port dính thêm dấu '|')
        db_host = db_host.strip()
        db_user = db_user.strip()
        db_name = db_name.strip()
        db_port_digits = "".join(ch for ch in db_port_raw if ch.isdigit())
        if db_port_raw.strip() and db_port_digits != db_port_raw.strip():
            st.caption(f"ℹ️ Đã tự động làm sạch Port thành `{db_port_digits}` (loại bỏ ký tự thừa khỏi `{db_port_raw.strip()}`).")
        db_port = db_port_digits or "3306"
    else:
        db_host = db_port = db_user = db_pass = db_name = ""
        use_ssl = False
        run_local = False
        st.caption("Dữ liệu mẫu: doanh số chocolate theo tháng, nhân viên, khu vực, sản phẩm (năm 2023).")

    st.subheader("2. Nhà cung cấp AI (Provider)")
    provider = st.selectbox("Provider", list(PROVIDER_CONFIGS.keys()), index=0)
    provider_cfg = PROVIDER_CONFIGS[provider]

    api_key = st.text_input(
        "API Key", type="password",
        help=provider_cfg["key_help"],
        placeholder=provider_cfg["key_placeholder"],
    )
    st.caption(f"💡 {provider_cfg['free_tier_note']}")
    model_name = st.selectbox("Model AI", provider_cfg["models"], index=0)

    qwen_base_url = DASHSCOPE_BASE_URL
    if provider == "Qwen (Alibaba Cloud)":
        with st.expander("🔧 Base URL nâng cao (Qwen)", expanded=False):
            st.caption(
                "Một số tài khoản Alibaba Cloud mới (gói Token Plan) yêu cầu dùng **domain riêng theo "
                "workspace** thay vì domain chung. Nếu gặp lỗi `AccessDenied.Unpurchased`, vào Model Studio "
                "Console → API Key → copy URL cạnh nhãn 'OpenAI compatible' và dán vào đây."
            )
            qwen_base_url = st.text_input(
                "Base URL", value=DASHSCOPE_BASE_URL,
                help="Mặc định là domain chung dashscope-intl. Dán domain riêng (dạng "
                     "https://ws-xxxx.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1) nếu domain chung bị từ chối."
            ).strip() or DASHSCOPE_BASE_URL

    with st.expander("⚡ Tối ưu Quota API", expanded=False):
        enable_self_check = st.checkbox(
            "Bật kiểm định SQL bằng AI (self-check)",
            value=True,
            help="Mỗi câu hỏi tốn thêm 1 lượt gọi AI để tự kiểm tra lại SQL. "
                 "Tắt đi để tiết kiệm ~50% quota mỗi câu hỏi (SQL vẫn được kiểm tra an toàn bằng code, chỉ bỏ bước AI double-check)."
        )
        enable_cache = st.checkbox(
            "Dùng lại kết quả cho câu hỏi trùng lặp (cache)",
            value=True,
            help="Nếu hỏi lại y hệt câu đã hỏi thành công trước đó trong phiên này, dùng lại kết quả cũ thay vì gọi AI lại."
        )

    schema_context_input = st.text_area(
        "Mô tả Schema / Nghiệp vụ (Tự động nạp sau khi bấm Kết nối)",
        value=st.session_state.get("schema_context", ""),
        height=180
    )

    forecast_periods = st.slider("Số kỳ dự báo xu hướng", 1, 12, 3)
    connect_btn = st.button("🔌 Kết nối Database & AI", type="primary", use_container_width=True)

# Đồng bộ toggle tối ưu quota ngay cả khi không bấm nút Kết nối lại
st.session_state["enable_self_check"] = enable_self_check
st.session_state["enable_cache"] = enable_cache

# ---------------------------------------------------------
# 5. Kiểm tra Kết nối & Tự động quét Schema
# ---------------------------------------------------------
def try_connect_single(host, port_int, user, pw, name, use_ssl):
    connect_args = {"connection_timeout": 6}
    if use_ssl:
        connect_args["ssl_disabled"] = False
    engine = create_engine(
        f"mysql+mysqlconnector://{user}:{quote_plus(pw)}@{host}:{port_int}/{name}",
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


def try_connect(host, port, user, pw, name, use_ssl, run_local=False):
    host = (host or "").strip()
    port_str = "".join(ch for ch in str(port) if ch.isdigit())
    if not port_str:
        raise ValueError(f"Port không hợp lệ: '{port}'. Vui lòng chỉ nhập số (VD: 3306), không dán kèm ký tự khác.")
    port_int = int(port_str)

    # Local Mode: thử lần lượt các alias phổ biến (localhost / 127.0.0.1 / host.docker.internal)
    # vì "localhost" có ý nghĩa khác nhau tùy môi trường chạy (máy thật vs. container Docker).
    candidate_hosts = LOCAL_HOST_ALIASES if (run_local and host.lower() in ("localhost", "127.0.0.1")) else [host]

    last_error = None
    for candidate in candidate_hosts:
        try:
            return try_connect_single(candidate, port_int, user, pw, name, use_ssl)
        except Exception as e:
            last_error = e
            continue
    raise last_error

if connect_btn:
    if not api_key:
        st.sidebar.error(f"❌ Vui lòng nhập API Key cho {provider}!")
    elif provider == "Qwen (Alibaba Cloud)" and _OpenAIClient is None:
        st.sidebar.error(
            "❌ Thiếu thư viện `openai` để gọi Qwen. Thêm dòng `openai` vào requirements.txt "
            "(hoặc chạy `pip install openai`) rồi khởi động lại app."
        )
    elif not use_demo and not (db_host and db_user and db_name):
        st.sidebar.error("❌ Vui lòng điền đầy đủ Host, User, Database Name!")
    else:
        try:
            if use_demo:
                engine = build_demo_engine()
            else:
                engine = try_connect(db_host, db_port, db_user, db_pass, db_name, use_ssl, run_local=run_local)

            if provider == "Gemini (Google)":
                client = genai.Client(api_key=api_key)
            else:
                client = _OpenAIClient(api_key=api_key, base_url=qwen_base_url)

            extracted_schema = auto_extract_schema(engine)
            final_schema = schema_context_input if schema_context_input.strip() else extracted_schema

            st.session_state.update({
                "engine": engine,
                "client": client,
                "provider": provider,
                "model_name": model_name,
                "schema_context": final_schema,
                "connected": True,
                "_db_pass_for_sanitize": db_pass,
                "is_demo": use_demo,
                "db_dialect": "SQLite" if use_demo else "MySQL",
                "enable_self_check": enable_self_check,
                "enable_cache": enable_cache,
            })
            st.sidebar.success(f"✅ Kết nối thành công! (AI: {provider} — {model_name})")
            st.rerun()
        except Exception as e:
            st.session_state["connected"] = False
            err_display = sanitize_error(str(e), db_pass)
            if "429" in err_display or "RESOURCE_EXHAUSTED" in err_display:
                st.sidebar.error(
                    f"🚫 API Key {provider} hết quota miễn phí hôm nay.\n\n"
                    "**Cách khắc phục:** tạo 1 API key mới, hoặc đổi sang Provider khác ở mục 2 rồi kết nối lại."
                )
            elif not use_demo and run_local:
                st.sidebar.error(
                    f"❌ Không kết nối được tới MySQL local (đã thử: {', '.join(LOCAL_HOST_ALIASES)}).\n\n"
                    f"Lỗi gốc: {err_display}\n\n"
                    "**Kiểm tra:** (1) MySQL đã bật chưa, (2) app này có đang chạy TRÊN CHÍNH máy có MySQL không "
                    "(local qua `streamlit run app.py`, không phải Streamlit Cloud), (3) User/Password/Database đúng chưa."
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


def detect_duplicate_entity_warning(df: pd.DataFrame):
    """Lớp bảo vệ ĐỘC LẬP với AI: nếu một cột định danh (ID) có số giá trị duy nhất
    nhỏ hơn tổng số dòng kết quả, khả năng cao dữ liệu bị nhân bản do JOIN với bảng
    lưu lịch sử theo thời gian (salaries, titles, dept_emp...) mà chưa lọc bản ghi
    hiện tại. Không phụ thuộc vào việc Gemini tự nhận ra lỗi này hay không."""
    id_cols = [c for c in df.columns if is_id_like(c)]
    for c in id_cols:
        try:
            n_unique = df[c].nunique(dropna=True)
        except Exception:
            continue
        if 0 < n_unique < len(df):
            return (
                f"⚠️ Cảnh báo tự động: cột `{c}` chỉ có {n_unique} giá trị duy nhất nhưng kết quả trả về "
                f"{len(df)} dòng. Đây thường là dấu hiệu dữ liệu bị nhân bản do JOIN với bảng lưu lịch sử "
                f"theo thời gian (VD: salaries, titles, dept_emp) mà chưa lọc bản ghi hiện tại. "
                f"Hãy diễn đạt lại câu hỏi rõ hơn (VD: 'lương hiện tại') hoặc kiểm tra SQL bên dưới."
            )
    return None


def _call_gemini_impl(client, model_name: str, prompt: str):
    response = client.models.generate_content(model=model_name, contents=prompt)
    return response.text


def _call_qwen_impl(client, model_name: str, prompt: str):
    completion = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content


def call_llm(prompt: str, max_retries: int = 3):
    """Lớp gọi AI đa nhà cung cấp (provider-agnostic): dispatch sang Gemini hoặc Qwen
    tùy theo lựa chọn của người dùng ở sidebar, dùng chung 1 logic retry/xử lý lỗi."""
    client = st.session_state.get("client")
    provider = st.session_state.get("provider", "Gemini (Google)")
    model_name = st.session_state.get("model_name", "gemini-3.6-flash")
    if not client:
        st.session_state["_last_gemini_error"] = "Chưa kết nối tới AI — vui lòng bấm 'Kết nối Database & AI' ở sidebar."
        return None

    impl = _call_gemini_impl if provider == "Gemini (Google)" else _call_qwen_impl

    for attempt in range(max_retries):
        try:
            raw = impl(client, model_name, prompt)
            return raw.strip().replace("```sql", "").replace("```", "").strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "RateLimit" in err or "Throttling" in err:
                msg = f"Hết quota {provider} hôm nay. Tạo API key mới hoặc đổi Provider ở sidebar rồi kết nối lại."
                st.session_state["_last_gemini_error"] = msg
                notify(msg, icon="🚫")
                return None
            if "503" in err or "UNAVAILABLE" in err or "Throttling" in err:
                wait = 3 * (attempt + 1)
                st.toast(f"⏳ Server {provider} bận, thử lại sau {wait}s...")
                time.sleep(wait)
            else:
                st.session_state["_last_gemini_error"] = err
                notify(f"Lỗi khi gọi {provider}.", detail=err, icon="❌")
                return None
    st.session_state["_last_gemini_error"] = f"Server {provider} quá tải sau nhiều lần thử."
    notify("Model quá tải sau nhiều lần thử. Hãy gửi lại câu hỏi sau ít phút.", icon="⏱️")
    return None


# Alias để tương thích ngược — toàn bộ code cũ gọi call_gemini() vẫn hoạt động,
# nhưng thực chất giờ đã dispatch đa nhà cung cấp qua call_llm().
call_gemini = call_llm


def self_check(user_query: str, sql_query: str, df: pd.DataFrame) -> dict:
    sample = df.head(5).to_string(index=False)
    prompt = f"""
Bạn là chuyên gia QA kiểm định SQL.
Schema: {st.session_state['schema_context']}
Câu hỏi gốc: "{user_query}"
SQL: {sql_query}
5 dòng mẫu: {sample}

Kiểm tra SQL có trả lời ĐẦY ĐỦ câu hỏi không.
Đặc biệt: nếu SQL JOIN với bảng lưu lịch sử theo thời gian (có cột from_date/to_date, ví dụ
salaries, titles, dept_emp...) mà KHÔNG lọc bản ghi hiện tại (to_date = '9999-01-01' hoặc
MAX(from_date) theo từng khóa chính), kết quả sẽ bị nhân bản dòng cho cùng 1 thực thể — hãy
coi đây là "day_du": false và nêu rõ trong "ly_do".

QUAN TRỌNG: "ly_do" PHẢI ngắn gọn, TỐI ĐA 20 từ, đi thẳng vào vấn đề — không lý luận dài dòng,
không liệt kê nhiều tình huống giả định, không giải thích ngữ nghĩa. Nếu SQL đã đúng, chỉ cần
ghi "SQL hợp lệ" hoặc tương đương.
Trả về DUY NHẤT JSON, không markdown, không giải thích thêm: {{"day_du": true/false, "ly_do": "..."}}
"""
    res = call_gemini(prompt)
    if not res:
        return {"day_du": True, "ly_do": "Bỏ qua self-check."}
    try:
        cleaned = res.strip().strip("`").replace("json\n", "").strip()
        parsed = json.loads(cleaned)
        # Phòng vệ tầng code: dù đã dặn AI ngắn gọn, vẫn cắt cứng "ly_do" quá dài để
        # đảm bảo UI không bao giờ bị vỡ layout bởi phản hồi dài dòng bất thường từ model.
        ly_do = str(parsed.get("ly_do", ""))
        if len(ly_do) > 200:
            ly_do = ly_do[:200].rsplit(" ", 1)[0] + "..."
        parsed["ly_do"] = ly_do
        return parsed
    except Exception:
        return {"day_du": True, "ly_do": "Không parse được JSON."}


def run_agent(user_query: str):
    result = {"query": user_query, "df": None, "sql": None, "logs": [], "error": None}
    schema_context = st.session_state["schema_context"]
    engine = st.session_state["engine"]
    db_pass = st.session_state.get("_db_pass_for_sanitize", "")
    dialect = st.session_state.get("db_dialect", "SQLite")

    dialect_hint = {
        "SQLite": "Database đang dùng là SQLite: dùng strftime('%Y', col)/strftime('%m', col) để lấy năm/tháng, KHÔNG dùng MONTH()/YEAR() của MySQL.",
        "MySQL": "Database đang dùng là MySQL: có thể dùng MONTH()/YEAR()/DATE_FORMAT() bình thường.",
    }.get(dialect, "")

    history_hint = (
        "Nếu có bảng lưu lịch sử theo thời gian (chứa cột from_date/to_date, ví dụ: salaries, "
        "titles, dept_emp...) và câu hỏi hỏi về giá trị/trạng thái HIỆN TẠI (VD: 'lương hiện tại', "
        "'phòng ban hiện tại', 'top N hiện nay'), chỉ lấy bản ghi đang hiệu lực (thường là "
        "to_date = '9999-01-01', hoặc dùng subquery lấy bản ghi có MAX(from_date) theo từng khóa "
        "chính) để tránh JOIN sinh ra nhiều dòng trùng lặp cho cùng 1 thực thể. "
        "NGƯỢC LẠI, nếu câu hỏi cần đếm/liệt kê SỐ LẦN THAY ĐỔI, LỊCH SỬ, hoặc 'đã từng' (VD: "
        "'đã từng đổi chức danh bao nhiêu lần', 'lịch sử lương'), TUYỆT ĐỐI KHÔNG lọc to_date — "
        "phải giữ nguyên toàn bộ các dòng lịch sử để đếm chính xác."
    )

    sql_suffix = "Chỉ trả về SQL thuần, không markdown, không giải thích."

    prompt = f"""Schema:
{schema_context}
Lưu ý dialect: {dialect_hint}
Lưu ý dữ liệu lịch sử: {history_hint}
Viết 1 câu SQL SELECT duy nhất cho câu hỏi: {user_query}
Nếu không có GROUP BY, bắt buộc thêm LIMIT 1000 để tránh trả về quá nhiều dữ liệu.
{sql_suffix}"""
    sql_query = call_gemini(prompt)
    if not sql_query:
        reason = st.session_state.get("_last_gemini_error", "")
        result["error"] = f"Không thể tạo SQL từ mô hình AI.{' Lý do: ' + reason if reason else ''}"
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

            dup_warning = detect_duplicate_entity_warning(df)
            if dup_warning:
                result["logs"].append(dup_warning)

            if st.session_state.get("enable_self_check", True):
                check = self_check(user_query, sql_query, df)
            else:
                check = {"day_du": True, "ly_do": "Đã tắt self-check để tiết kiệm quota."}

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

            fix_prompt = f"""Schema: {schema_context}
Lưu ý dialect: {dialect_hint}
Lưu ý dữ liệu lịch sử: {history_hint}
Câu hỏi: '{user_query}'
SQL lỗi/chưa đủ: {sql_query}
Lý do: {check.get('ly_do', '')}
Viết lại SQL chuẩn xác. {sql_suffix}"""
            sql_query = call_gemini(fix_prompt) or sql_query

        except Exception as e:
            error_msg = sanitize_error(str(e), db_pass)
            result["logs"].append(f"❌ Lỗi thực thi SQL: {error_msg}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {error_msg}"
                result["sql"] = sql_query
                return result

            fix_prompt = f"""Schema: {schema_context}
Lưu ý dialect: {dialect_hint}
Lưu ý dữ liệu lịch sử: {history_hint}
SQL lỗi: {sql_query}
Lỗi: {error_msg}
Câu hỏi: '{user_query}'
Sửa lại SQL. {sql_suffix}"""
            sql_query = call_gemini(fix_prompt) or sql_query

    return result

# ---------------------------------------------------------
# 7. Trực quan hóa
# ---------------------------------------------------------
def get_axis_columns(df: pd.DataFrame):
    """Trả về:
    - measure_cols: cột số THỰC SỰ mang ý nghĩa đo lường (đã loại bỏ cột ID như emp_no, GeoID...)
    - cat_cols: cột phân loại/text (bao gồm cả cột ID, dùng làm nhãn chứ không phải trục giá trị)
    - time_col: cột thời gian hợp lệ (None nếu không có)
    """
    all_num_cols = df.select_dtypes(include="number").columns.tolist()
    measure_cols = [c for c in all_num_cols if not is_id_like(c)]
    cat_cols = [c for c in df.columns if c not in measure_cols]
    time_col = find_time_column(df)
    # Nếu time_col vô tình lọt vào measure_cols (hiếm khi cột ngày là numeric epoch), loại ra
    if time_col in measure_cols:
        measure_cols.remove(time_col)
    return measure_cols, cat_cols, time_col


def pick_label_column(df: pd.DataFrame, label_cols: list):
    """Chọn cột nhãn TỐT NHẤT cho trục danh mục (X), ưu tiên theo thứ tự:
    1) Gộp first_name + last_name thành 1 cột 'Họ và tên' nếu cả hai đều có mặt.
    2) Cột text có tên gợi ý nghiệp vụ dễ đọc (name, product, category, team...).
    3) Bất kỳ cột text nào không phải ID.
    4) Cuối cùng mới dùng cột ID (ép về chuỗi để Plotly luôn hiểu là trục danh mục,
       không tự động chuyển thành trục số liên tục).
    Trả về (tên_cột_hiển_thị, Series_giá_trị_dạng_chuỗi, consumed_cols) hoặc (None, None, [])
    nếu không có gì phù hợp. consumed_cols là các cột gốc đã "dùng hết" vào label
    (VD: first_name + last_name khi gộp), giúp nơi gọi biết cột nào còn trống để tô màu.
    """
    if not label_cols:
        return None, None, []

    cols_lower = {c.lower(): c for c in label_cols}
    if "first_name" in cols_lower and "last_name" in cols_lower:
        fn, ln = cols_lower["first_name"], cols_lower["last_name"]
        merged = (df[fn].astype(str) + " " + df[ln].astype(str))
        return "Họ và tên", merged, [fn, ln]

    text_like = [c for c in label_cols if not is_id_like(c)]
    name_hint = [c for c in text_like if NAME_LIKE_REGEX.search(c)]
    rest_text = [c for c in text_like if c not in name_hint]
    id_like_cols = [c for c in label_cols if c not in text_like]

    ordered_candidates = name_hint + rest_text + id_like_cols
    chosen = ordered_candidates[0]
    return chosen, df[chosen].astype(str), [chosen]


def render_smart_chart(df: pd.DataFrame, chart_override: str, turn_id: str):
    cols = df.columns.tolist()
    if len(cols) < 2:
        st.info("Dữ liệu cần tối thiểu 2 cột để vẽ biểu đồ.")
        return

    if len(df) <= 1:
        # Chỉ 1 dòng dữ liệu: vẽ chart (đặc biệt Scatter 1 điểm) không mang ý nghĩa trực quan,
        # hiển thị thẳng giá trị dạng text cho dễ đọc thay vì ép vẽ biểu đồ.
        if len(df) == 1:
            row = df.iloc[0]
            summary = " · ".join(f"**{c}**: {row[c]}" for c in df.columns)
            st.info(f"📌 Chỉ có 1 dòng kết quả, không cần biểu đồ: {summary}")
        else:
            st.info("Không có dữ liệu để vẽ biểu đồ.")
        return

    measure_cols, cat_cols, time_col = get_axis_columns(df)
    # cat_cols dùng làm trục danh mục nên loại time_col ra khỏi đó (đã có vai trò riêng)
    label_cols = [c for c in cat_cols if c != time_col]

    try:
        if chart_override == "Tự động":
            if time_col and measure_cols:
                chosen = "Line"
            elif label_cols and measure_cols:
                chosen = "Bar"
            elif len(measure_cols) >= 2:
                chosen = "Scatter"
            else:
                st.info("Không tìm thấy dạng biểu đồ phù hợp — dữ liệu không có chỉ số đo lường số học rõ ràng (các cột số hiện có đều là mã định danh).")
                return
        else:
            chosen = chart_override

        # Guard: người dùng chọn tay "Line"/"Area" nhưng không có cột thời gian hợp lệ
        if chosen in ("Line", "Area") and not time_col:
            if label_cols and measure_cols:
                st.warning(
                    "⚠️ Biểu đồ Line/Area cần một cột thời gian hợp lệ, dữ liệu hiện tại không có. "
                    "Tự động chuyển sang Bar Chart để đảm bảo đúng ý nghĩa thống kê."
                )
                chosen = "Bar"
            else:
                st.info("Không có cột thời gian hợp lệ và không đủ dữ liệu để vẽ Bar/Scatter thay thế.")
                return

        if chosen == "Line" and time_col and measure_cols:
            fig = px.line(df.sort_values(time_col), x=time_col, y=measure_cols, markers=True,
                          title=f"Xu hướng theo {time_col}")
        elif chosen == "Area" and time_col and measure_cols:
            fig = px.area(df.sort_values(time_col), x=time_col, y=measure_cols,
                         title=f"Xu hướng (Area) theo {time_col}")
        elif chosen == "Bar" and label_cols and measure_cols:
            label_name, label_series, consumed_cols = pick_label_column(df, label_cols)
            if label_name is None:
                st.info("Không tìm thấy cột phù hợp để làm nhãn trục X.")
                return
            plot_df = df.copy()
            plot_df[label_name] = label_series.values

            # Giới hạn số cột hiển thị — Bar chart với hàng trăm/nghìn category (VD: kết quả
            # không GROUP BY, chạm LIMIT 1000) sẽ vẽ thành "bức tường vạch" dày đặc, nhãn trục X
            # chồng lấn hoàn toàn không đọc được. Cắt về top N đầu tiên (giữ nguyên thứ tự đã
            # ORDER BY từ SQL) và báo rõ cho người dùng biết đang xem một phần.
            total_rows = len(plot_df)
            was_truncated = total_rows > MAX_BAR_CATEGORIES
            if was_truncated:
                plot_df = plot_df.head(MAX_BAR_CATEGORIES)

            category_order = list(dict.fromkeys(plot_df[label_name].tolist()))

            # Tự động tìm cột phân loại còn lại (VD: đánh giá hiệu suất, phòng ban...) để tô màu,
            # giúp biểu đồ mang thêm insight thay vì chỉ 1 màu đơn điệu. Chỉ áp dụng nếu số lượng
            # nhóm màu đủ nhỏ để còn dễ đọc (<= 8 nhóm).
            color_col = None
            candidate_color_cols = [c for c in label_cols if c not in consumed_cols and c in plot_df.columns]
            for c in candidate_color_cols:
                if not is_id_like(c) and df[c].nunique(dropna=True) <= 8:
                    color_col = c
                    break

            fig = px.bar(
                plot_df, x=label_name, y=measure_cols[0], color=color_col,
                title=f"{measure_cols[0]} theo {label_name}",
                category_orders={label_name: category_order},
            )
            fig.update_xaxes(type="category")
            if was_truncated:
                st.caption(
                    f"📊 Đang hiển thị {MAX_BAR_CATEGORIES}/{total_rows} dòng đầu tiên để biểu đồ dễ đọc — "
                    f"xem đầy đủ {total_rows} dòng trong bảng dữ liệu phía trên, hoặc thu hẹp câu hỏi "
                    f"(VD: thêm 'Top 20', 'theo từng phòng ban') để có biểu đồ tổng hợp gọn hơn."
                )
        elif chosen == "Scatter" and len(measure_cols) >= 2:
            fig = px.scatter(df, x=measure_cols[0], y=measure_cols[1], title="Biểu đồ phân tích tương quan")
        elif len(measure_cols) >= 2:
            fig = px.scatter(df, x=measure_cols[0], y=measure_cols[1], title="Biểu đồ phân tích tương quan")
        else:
            st.info("Không đủ dữ liệu phù hợp cho loại biểu đồ đã chọn (thiếu chỉ số đo lường số học không phải mã ID).")
            return

        st.plotly_chart(fig, width='stretch', key=f"chart_{turn_id}")
    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {e}")

# ---------------------------------------------------------
# 8. Dự báo (thuật toán xác định) & Phát hiện bất thường (AI)
# ---------------------------------------------------------
def forecast_series(df: pd.DataFrame, periods: int = 3):
    x_col = find_time_column(df)
    if not x_col:
        return None, "Dữ liệu không có cột thời gian hợp lệ (ngày/tháng/quý/năm) nên không thể dự báo xu hướng cho kết quả này."

    measure_cols, _, _ = get_axis_columns(df)
    if not measure_cols:
        return None, "Không tìm thấy chỉ số đo lường số học phù hợp để dự báo (các cột số hiện có là mã định danh, ví dụ ID/mã nhân viên)."
    if len(df) < 3:
        return None, "Cần tối thiểu 3 dòng dữ liệu để dự báo."

    y_col = measure_cols[0]

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

    is_bounded_period = any(k in x_col.lower() for k in BOUNDED_PERIOD_KEYWORDS)
    is_numeric_x = pd.api.types.is_numeric_dtype(df_sorted[x_col])

    if is_bounded_period:
        # Tháng (1-12) / Quý (1-4) là chu kỳ có giới hạn — không nối số thô (VD tháng "14" vô nghĩa)
        future_x = [f"Kỳ +{i+1}" for i in range(periods)]
    elif is_numeric_x:
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
LOG_INLINE_MAX_CHARS = 220  # log dài hơn ngưỡng này sẽ thu gọn vào expander, tránh vỡ layout chat


def render_result(result: dict, turn_id: str):
    for i, line in enumerate(result["logs"]):
        if line.startswith("⚠️ Cảnh báo tự động"):
            st.warning(line)
        elif len(line) > LOG_INLINE_MAX_CHARS:
            # Bảo vệ UI độc lập với AI: dù đã dặn model trả lời ngắn gọn, một số model
            # (đặc biệt qua proxy như OpenRouter) vẫn có thể "nói nhiều" — luôn thu gọn
            # ở tầng code để chat không bao giờ bị tràn bởi 1 đoạn lý luận dài.
            short = line[:LOG_INLINE_MAX_CHARS].rsplit(" ", 1)[0] + "..."
            st.caption(short)
            with st.expander("Xem đầy đủ", expanded=False):
                st.write(line)
        else:
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

        measure_cols, _, time_col = get_axis_columns(df)
        if time_col and measure_cols:
            y_col = measure_cols[0]
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
            "AI chỉ đảm nhiệm việc sinh SQL, tự sửa lỗi, kiểm định QA, và giải thích bất thường (tab Biểu đồ). "
            "Dự báo chỉ khả dụng khi kết quả có cột thời gian hợp lệ và ít nhất một chỉ số đo lường số học (không phải mã ID)."
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
    st.info("👈 **Hướng dẫn:** Chọn nguồn dữ liệu (demo hoặc MySQL riêng), chọn Provider AI & nhập API Key, rồi bấm Kết nối.")
else:
    if st.session_state.get("is_demo"):
        st.caption("🎮 Đang dùng dữ liệu mẫu — thử hỏi: *\"Doanh số theo từng tháng năm 2023\"*")
    user_input = st.chat_input("Hỏi bất kỳ điều gì về dữ liệu của bạn...")
    if user_input:
        st.chat_message("user").write(user_input)
        with st.chat_message("assistant"):
            cache_key = user_input.strip().lower()
            cached = st.session_state.get("query_cache", {}).get(cache_key)

            if st.session_state.get("enable_cache", True) and cached and not cached.get("error"):
                st.caption("♻️ Dùng lại kết quả đã hỏi trước đó trong phiên này (tiết kiệm quota, không gọi lại AI).")
                result = cached
                render_result(result, turn_id=f"new{len(st.session_state['history'])}")
            else:
                with st.spinner("Đang truy vấn & phân tích..."):
                    result = run_agent(user_input)
                render_result(result, turn_id=f"new{len(st.session_state['history'])}")
                if not result.get("error"):
                    st.session_state.setdefault("query_cache", {})[cache_key] = result
        st.session_state["history"].append(result)
