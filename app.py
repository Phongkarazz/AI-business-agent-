"""
Veraxus for SQL - Streamlit Application Entry Point.
Featuring standalone Onboarding, interactive Explorer Sidebar, direct History Inspection,
Smart Starter Cards (1-Click), and Follow-up Question Suggestions.
"""

import re
import sys
import textwrap
import streamlit as st

# Tự động giải phóng cache submodules trong src/ để Python luôn tải mã nguồn mới nhất từ ổ đĩa
for _mod in list(sys.modules.keys()):
    if _mod.startswith("src.") or _mod == "src":
        del sys.modules[_mod]

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.config_store import load_saved_config
from src.database.schema import get_table_names
from src.analytics.heuristics import generate_starter_prompts, generate_categorized_starter_prompts
from src.ui.state import init_session_state
from src.ui.onboarding import render_onboarding
from src.ui.sidebar import perform_connection, render_main_sidebar
from src.ui.components import render_result, render_voice_input_button, render_veraxus_loading_html
from src.llm.agent import run_agent

# ---------------------------------------------------------
# 1. Cấu hình Trang Streamlit & Custom CSS Giao Diện Doanh Nghiệp
# ---------------------------------------------------------
st.set_page_config(
    page_title="Veraxus - Enterprise Intelligence",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    
    /* Ẩn thanh Chrome thừa mặc định của Streamlit nhưng BẢO VỆ nút mở/đóng Sidebar */
    #MainMenu,
    [data-testid="stMainMenu"],
    footer,
    .stDeployButton,
    [data-testid="stAppDeployButton"],
    [data-testid="stToolbarActions"],
    [data-testid="stToolbarActionButton"],
    div[data-testid="stDecoration"],
    div[data-testid="stStatusWidget"] {
        display: none !important;
        visibility: hidden !important;
    }
    header { background-color: transparent !important; }

    /* Nút mở/đóng Sidebar tinh gọn, trực quan, luôn bấm được */
    [data-testid="stExpandSidebarButton"] {
        visibility: visible !important;
        display: inline-flex !important;
        opacity: 1 !important;
        position: fixed !important;
        top: 14px !important;
        left: 14px !important;
        z-index: 999999 !important;
        background: #FFFFFF !important;
        border: 1.5px solid #0068FF !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 8px rgba(0, 104, 255, 0.18) !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebarCollapseButton"] {
        visibility: visible !important;
        display: inline-flex !important;
        opacity: 1 !important;
    }

    /* Tinh chỉnh Sidebar - Thoáng đãng, Chống cắt viền & Tràn mép */
    section[data-testid="stSidebar"] {
        border-right: 1px solid #E2E8F0 !important;
        background-color: #FFFFFF !important;
        min-width: 320px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        padding-left: 1.65rem !important;
        padding-right: 1.25rem !important;
        padding-top: 1.25rem !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
    section[data-testid="stSidebar"] .stCaption {
        margin-left: 0 !important;
        padding-left: 2px !important;
    }

    /* Tối ưu khoảng đệm trên cùng & Căn giữa cân xứng khi full màn hình */
    .block-container {
        padding-top: 1.4rem !important;
        padding-bottom: 2.8rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 1040px !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }
    
    /* Thẻ Chỉ số Điều hành (Executive KPI Cards) - Tỷ lệ tiêu chuẩn & Thẩm mỹ hài hòa */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 12px 14px !important;
        border-radius: 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        transition: all 0.2s ease-in-out;
        min-width: 0 !important;
        overflow: hidden !important;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #CBD5E1;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.05);
        transform: translateY(-1px);
    }
    div[data-testid="stMetricLabel"] {
        font-size: clamp(0.7rem, 0.88vw, 0.74rem) !important;
        font-weight: 700 !important;
        color: #64748B !important;
        text-transform: uppercase;
        letter-spacing: 0.01em;
        margin-bottom: 4px;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    div[data-testid="stMetricLabel"] > div,
    div[data-testid="stMetricLabel"] p {
        font-size: clamp(0.7rem, 0.88vw, 0.74rem) !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        line-height: 1.3 !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: clamp(1.15rem, 1.4vw, 1.35rem) !important;
        font-weight: 800 !important;
        color: #0F172A !important;
        letter-spacing: -0.01em;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        line-height: 1.25 !important;
    }
    div[data-testid="stMetricValue"] > div {
        font-size: inherit !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    div[data-testid="stMetricDelta"] {
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }

    /* Hệ thống Nút bấm Chuẩn Zalo Blue (#0068FF) - Thao tác 1-Chạm Mượt mà */
    .stButton > button {
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
        line-height: 1.45 !important;
        padding: 9px 16px !important;
        min-height: 48px !important;
        height: auto !important;
        transition: all 0.15s ease-in-out !important;
        white-space: normal !important;
        word-break: break-word !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
    }
    .stButton > button[kind="primary"] {
        background-color: #0068FF !important;
        border-color: #0068FF !important;
        color: #FFFFFF !important;
        box-shadow: 0 2px 6px rgba(0, 104, 255, 0.2) !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #0056D6 !important;
        border-color: #0056D6 !important;
        box-shadow: 0 4px 12px rgba(0, 104, 255, 0.3) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button[kind="secondary"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        color: #334155 !important;
    }
    .stButton > button[kind="secondary"]:hover {
        border-color: #0068FF !important;
        background-color: #F8FAFC !important;
        color: #0068FF !important;
        box-shadow: 0 2px 8px rgba(0, 104, 255, 0.08) !important;
        transform: translateY(-1px) !important;
    }

    /* Hero Section - Tối giản, Tập trung, Tỷ lệ Cân đối (Chuẩn Zalo/CPO) */
    .hero-container {
        text-align: center;
        padding: 10px 10px 6px 10px;
        max-width: 860px;
        margin: 0 auto;
    }
    .hero-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #F0FDF4;
        color: #15803D;
        border: 1px solid #BBF7D0;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        margin-bottom: 10px;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
    }
    .hero-badge-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #10B981;
        box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.25);
    }
    .hero-title {
        font-size: 2.35rem;
        font-weight: 850;
        color: #0F172A;
        letter-spacing: -0.035em;
        line-height: 1.2;
        margin-bottom: 6px;
    }
    .hero-subtitle {
        font-size: 1.05rem;
        color: #64748B;
        line-height: 1.5;
        max-width: 640px;
        margin: 0 auto 18px auto;
        font-weight: 400;
    }

    /* 3 Thẻ Trạng thái Hệ thống Live Snapshot - Trực quan, Tin cậy, Riêng tư */
    .micro-trust-ribbon {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        margin: 4px auto 26px auto;
        font-size: 0.8rem;
        color: #64748B;
        font-weight: 500;
    }
    .micro-trust-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.76rem;
        color: #475569;
        transition: all 0.2s ease;
    }
    .micro-trust-pill:hover {
        background: #F1F5F9;
        border-color: #CBD5E1;
        color: #0F172A;
    }
    .health-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
    }
    .health-card-title {
        font-size: 0.76rem;
        font-weight: 700;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .health-badge {
        font-size: 0.72rem;
        font-weight: 600;
        padding: 2px 9px;
        border-radius: 9999px;
        white-space: nowrap;
    }
    .health-badge-green {
        background: #F0FDF4;
        color: #15803D;
        border: 1px solid #BBF7D0;
    }
    .health-badge-blue {
        background: #EFF6FF;
        color: #0068FF;
        border: 1px solid #BFDBFE;
    }
    .health-badge-purple {
        background: #FAF5FF;
        color: #7E22CE;
        border: 1px solid #E9D5FF;
    }
    .health-card-value {
        font-size: 1.15rem;
        font-weight: 750;
        color: #0F172A;
        line-height: 1.35;
        margin: 4px 0 2px 0;
        letter-spacing: -0.015em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .health-card-sub {
        font-size: 0.78rem;
        color: #64748B;
        line-height: 1.35;
    }

    /* Trục Tìm kiếm Trung tâm Hero Search - Tỷ lệ Vàng Căn giữa 760px, Thoáng đãng & Tinh tế (Chuẩn Vương Quang Khải) */
    form[data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
        background: transparent !important;
        margin: 20px auto 16px auto !important;
        max-width: 760px !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] {
        margin-bottom: 0 !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"],
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"] {
        border-radius: 16px !important;
        background-color: #FFFFFF !important;
        border: 1.5px solid #CBD5E1 !important;
        box-shadow: 0 4px 20px -2px rgba(0, 104, 255, 0.08), 0 2px 6px rgba(0, 0, 0, 0.03) !important;
        transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"]:hover,
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"]:hover {
        border-color: #94A3B8 !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"]:focus-within {
        border-color: #0068FF !important;
        box-shadow: 0 0 0 3px rgba(0, 104, 255, 0.18), 0 8px 24px -4px rgba(0, 104, 255, 0.15) !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] input {
        height: 52px !important;
        min-height: 52px !important;
        border-radius: 16px !important;
        background-color: transparent !important;
        border: none !important;
        font-size: 1.02rem !important;
        padding: 0 20px !important;
        color: #0F172A !important;
        box-shadow: none !important;
    }
    form[data-testid="stForm"] .stButton > button {
        height: 52px !important;
        min-height: 52px !important;
        border-radius: 16px !important;
        font-size: 0.98rem !important;
        font-weight: 700 !important;
        background-color: #0068FF !important;
        border: 1px solid #0068FF !important;
        color: #FFFFFF !important;
        white-space: nowrap !important;
        box-shadow: 0 4px 16px rgba(0, 104, 255, 0.28) !important;
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
    }
    form[data-testid="stForm"] .stButton > button:hover {
        background-color: #0056D6 !important;
        border-color: #0056D6 !important;
        box-shadow: 0 6px 22px rgba(0, 104, 255, 0.40) !important;
        transform: translateY(-2px) !important;
    }

    /* Khám phá Theo Lăng Kính Điều Hành (Tabs) - Nhẹ nhàng, Ngăn nắp */
    .prompt-tab-intro {
        margin: 18px auto 10px auto;
        max-width: 880px;
        font-size: 0.9rem;
        font-weight: 600;
        color: #334155;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .stTabs {
        max-width: 880px;
        margin: 0 auto;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        margin-bottom: 14px;
        border-bottom: 1px solid #E2E8F0;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 8px 8px 0 0;
        font-size: 0.88rem;
        font-weight: 600;
        color: #64748B;
    }
    .stTabs [aria-selected="true"] {
        color: #0068FF !important;
        border-bottom: 2px solid #0068FF !important;
    }

    /* Thẻ Gợi Ý Hành Động (Prompt Action Cards) - Hover lift & 1-Chạm mượt mà */
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        border: 1px solid #E2E8F0 !important;
        background: #FFFFFF !important;
        padding: 14px 16px !important;
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02) !important;
        min-height: 142px !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: #0068FF !important;
        box-shadow: 0 6px 18px rgba(0, 104, 255, 0.08) !important;
        transform: translateY(-2px);
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button {
        min-height: 38px !important;
        height: 38px !important;
        font-size: 0.84rem !important;
        font-weight: 600 !important;
        border-radius: 9px !important;
        background-color: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        color: #0068FF !important;
        white-space: nowrap !important;
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover {
        background-color: #0068FF !important;
        color: #FFFFFF !important;
        border-color: #0068FF !important;
        box-shadow: 0 2px 8px rgba(0, 104, 255, 0.22) !important;
    }

    /* Veraxus Signature Loading Animation - Mũi tên xoay đặc trưng & Lõi khiên pha lê */
    .veraxus-loading-card, .agent-loading-card {
        display: inline-flex;
        align-items: center;
        gap: 14px;
        padding: 12px 24px;
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.98) 0%, rgba(240, 247, 255, 0.95) 100%);
        border: 1.5px solid #BFDBFE;
        border-radius: 16px;
        margin: 12px 0;
        box-shadow: 0 6px 20px rgba(0, 104, 255, 0.10), 0 2px 6px rgba(15, 23, 42, 0.04);
        backdrop-filter: blur(10px);
    }
    .veraxus-spinner-wrapper {
        position: relative;
        width: 38px;
        height: 38px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    .veraxus-orbit-arrow {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        animation: veraxus-orbit-spin 1.05s cubic-bezier(0.4, 0, 0.2, 1) infinite;
        filter: drop-shadow(0 0 6px rgba(0, 104, 255, 0.35));
    }
    .veraxus-spinner-core {
        position: relative;
        z-index: 2;
        width: 20px;
        height: 20px;
        display: flex;
        align-items: center;
        justify-content: center;
        animation: veraxus-core-pulse 2.2s ease-in-out infinite;
    }
    .veraxus-spinner-text-wrap {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .veraxus-spinner-brand {
        font-size: 0.70rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        background: linear-gradient(135deg, #0068FF 0%, #00A3FF 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1;
    }
    .veraxus-spinner-status, .agent-spinner-text {
        color: #0F172A;
        font-weight: 600;
        font-size: 0.93rem;
        letter-spacing: -0.01em;
        line-height: 1.3;
    }
    @keyframes veraxus-orbit-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    @keyframes veraxus-core-pulse {
        0%, 100% { transform: scale(0.95); opacity: 0.92; }
        50% { transform: scale(1.06); opacity: 1; filter: drop-shadow(0 0 6px rgba(56, 189, 248, 0.6)); }
    }
    .agent-spinner {
        width: 22px;
        height: 22px;
        border: 2.5px solid #DBEAFE;
        border-top: 2.5px solid #0068FF;
        border-radius: 50%;
        animation: veraxus-orbit-spin 0.8s linear infinite;
        flex-shrink: 0;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. Khởi tạo Session State
# ---------------------------------------------------------
init_session_state()

# ---------------------------------------------------------
# 3. Tự động Kết nối (Auto-Connect on Startup)
# ---------------------------------------------------------
if (
    not st.session_state.get("connected")
    and not st.session_state.get("_auto_connect_attempted", False)
    and not st.session_state.get("_auto_connect_error")
):
    st.session_state["_auto_connect_attempted"] = True
    saved = load_saved_config()

    if saved.get("auto_connect", True):
        provider = saved.get("provider", "OpenRouter")
        if provider == "OpenRouter":
            api_key = saved.get("api_key_openrouter", "")
        elif provider == "Gemini (Google)":
            api_key = saved.get("api_key_gemini", "")
        else:
            api_key = saved.get("api_key_qwen", "")

        clean_api_key = api_key.strip()
        is_openrouter_key = clean_api_key.startswith("sk-or-v1-")
        effective_provider = "OpenRouter" if is_openrouter_key else provider

        use_demo = saved.get("data_mode_index", 0) == 0
        db_host = (saved.get("db_host", "") or "").strip()
        db_user = (saved.get("db_user", "") or "").strip()
        db_name = (saved.get("db_name", "") or "").strip()
        run_local = saved.get("run_local", True) or (db_host in ("localhost", "127.0.0.1", ""))

        if run_local and not db_host:
            db_host = "localhost"

        can_connect = clean_api_key and (use_demo or bool(db_user and db_name and (db_host or run_local)))

        if can_connect:
            custom_base_url = saved.get("openrouter_base_url" if effective_provider == "OpenRouter" else "qwen_base_url", "")
            default_model_for_p = "gemini-3.7-flash" if effective_provider == "Gemini (Google)" else ("deepseek/deepseek-chat" if effective_provider == "OpenRouter" else "qwen-plus")
            target_model = saved.get("model_name") or default_model_for_p
            if effective_provider == "Gemini (Google)" and "deepseek" in target_model.lower():
                target_model = "gemini-3.7-flash"

            with st.spinner(f"⚡ Đang tự động kết nối lại {effective_provider} & {'SQLite Demo' if use_demo else 'MySQL'}..."):
                success, detail = perform_connection(
                    use_demo=use_demo,
                    db_host=db_host,
                    db_port=saved.get("db_port", "3306"),
                    db_user=db_user,
                    db_pass=saved.get("db_pass", ""),
                    db_name=db_name,
                    use_ssl=saved.get("use_ssl", False) if not run_local else False,
                    run_local=run_local,
                    effective_provider=effective_provider,
                    clean_api_key=clean_api_key,
                    custom_base_url=custom_base_url,
                    selected_model=target_model,
                    schema_context_input="",
                )
                if success:
                    st.session_state["view_mode"] = "chat"
                    st.toast(f"⚡ Đã tự động kết nối {effective_provider} & {'SQLite Demo' if use_demo else 'MySQL'}!", icon="⚡")
                    st.rerun()
                else:
                    st.session_state["_auto_connect_error"] = detail
                    st.session_state["view_mode"] = "settings"
                    st.rerun()

# ---------------------------------------------------------
# 4. Điều hướng Giao diện (Routing)
# ---------------------------------------------------------
# Nếu chưa kết nối, kết nối thất bại hoặc người dùng đang ở Cài đặt: Hiển thị ngay màn hình Onboarding / Settings để chỉnh sửa
if not st.session_state.get("connected") or st.session_state.get("view_mode") == "settings":
    render_onboarding()

# Nếu đã kết nối: Hiển thị Sidebar & Màn hình Chat Phân tích chính
else:
    # 4.0 Xử lý câu hỏi bằng giọng nói từ Voice Input (nếu chuyển hướng qua URL)
    voice_q = st.query_params.get("voice_q")
    if voice_q:
        st.session_state["pending_prompt"] = str(voice_q)
        try:
            del st.query_params["voice_q"]
        except Exception:
            pass
        st.rerun()

    # 4.1 Hiển thị Sidebar tra cứu bảng và lịch sử chat
    render_main_sidebar()

    # Tự động khôi phục mở rộng Sidebar nếu bị thu gọn trong LocalStorage của trình duyệt
    import streamlit.components.v1 as _components
    _components.html("""
    <script>
        function autoExpandSidebar() {
            try {
                const pStorage = window.parent.localStorage;
                if (pStorage) {
                    for (let i = 0; i < pStorage.length; i++) {
                        const k = pStorage.key(i);
                        if (k && k.startsWith('stSidebarCollapsed')) {
                            pStorage.setItem(k, 'false');
                        }
                    }
                }
                const expandBtn = window.parent.document.querySelector('[data-testid="stExpandSidebarButton"] button, [data-testid="stExpandSidebarButton"]');
                if (expandBtn) {
                    expandBtn.click();
                }
            } catch(e) {}
        }
        setTimeout(autoExpandSidebar, 80);
        setTimeout(autoExpandSidebar, 400);
    </script>
    """, height=0, width=0)

    history = st.session_state.get("history", [])
    focused_turn_idx = st.session_state.get("focused_turn_idx", None)

    # Tiếp nhận câu hỏi từ Chat Input hoặc Pending Prompt (từ Thẻ Starter / Gợi ý tiếp nối)
    has_active_conversation = bool(history) or (focused_turn_idx is not None)
    pending_prompt = st.session_state.get("pending_prompt")

    # Chỉ hiển thị chat_input ở chân trang khi ĐÃ CÓ lịch sử trò chuyện (tránh trùng lặp với Hero Search)
    user_input = None
    if has_active_conversation:
        user_input = st.chat_input(" Ask Veraxus...")
        render_voice_input_button(compact=True)

    prompt_to_run = pending_prompt or user_input

    # 4.2 Hiển thị câu hỏi được chọn trực tiếp (Direct Focus View) hoặc toàn bộ hội thoại
    if focused_turn_idx is not None and 0 <= focused_turn_idx < len(history):
        turn = history[focused_turn_idx]
        col_focus1, col_focus2 = st.columns([5, 1])
        with col_focus1:
            st.info(f"📌 **Đang xem câu hỏi số {focused_turn_idx + 1}**: *\"{turn['query']}\"*")
        with col_focus2:
            if st.button("🌐 Xem tất cả", use_container_width=True, key="btn_exit_focus_top", type="secondary", help="Quay lại xem toàn bộ đoạn hội thoại"):
                st.session_state["focused_turn_idx"] = None
                st.rerun()

        st.chat_message("user").write(turn["query"])
        with st.chat_message("assistant"):
            try:
                render_result(turn, turn_id=f"focused_{focused_turn_idx}")
            except Exception as e:
                st.error(f"⚠️ Có lỗi nhỏ khi hiển thị kết quả lượt này: {e}")
                if st.button("🔄 Tải lại lượt này", key=f"retry_focus_{focused_turn_idx}"):
                    st.rerun()
    else:
        # Hiển thị toàn bộ lịch sử hội thoại
        for i, turn in enumerate(history):
            st.chat_message("user").write(turn["query"])
            with st.chat_message("assistant"):
                try:
                    render_result(turn, turn_id=f"hist{i}")
                except Exception as e:
                    st.error(f"⚠️ Có lỗi nhỏ khi hiển thị kết quả lượt này: {e}")
                    if st.button("🔄 Tải lại lượt này", key=f"retry_hist_{i}"):
                        st.rerun()

    # 4.3 Màn hình Khám phá Dữ liệu Chuẩn Thi đấu (Perplexity / CPO Standard)
    if not history and focused_turn_idx is None and not prompt_to_run:
        engine = st.session_state.get("engine")
        tables = get_table_names(engine)
        schema_context = st.session_state.get("schema_context", "")
        provider_name = str(st.session_state.get("provider", "Ollama"))
        model_disp = str(st.session_state.get("model_name", "qwen2.5-coder:3b"))
        is_demo = bool(st.session_state.get("is_demo", False))

        tbl_low = [t.lower() for t in tables]
        is_emp = "employees" in tbl_low and "departments" in tbl_low
        is_choc = any(t in tbl_low for t in ["sales", "products", "geo", "people"])

        # Model display name cleaning
        clean_model = model_disp.split("/")[-1].replace(":latest", "")
        if "deepseek-chat" in model_disp.lower() or "deepseek-v3" in model_disp.lower():
            clean_model = "DeepSeek V3"
        elif "deepseek-r1" in model_disp.lower():
            clean_model = "DeepSeek R1"
        elif "qwen2.5-coder" in model_disp.lower():
            clean_model = "Qwen 2.5 Coder"
        elif "gemini" in model_disp.lower():
            clean_model = "Gemini 2.5 Flash"
        elif "claude" in model_disp.lower():
            clean_model = "Claude 3.5 Sonnet"


        # Hero Header - Tối giản & Thẩm mỹ (Chuẩn Zalo/CPO)
        st.markdown(textwrap.dedent("""
        <div class="hero-container">
            <div class="hero-badge">
                <span class="hero-badge-dot"></span> <span>Doanh Nghiệp • Sẵn Sàng Phân Tích</span>
            </div>
            <div style="display: flex; align-items: center; justify-content: center; gap: 14px; margin: 4px 0 6px 0;">
                <svg width="44" height="44" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" style="filter: drop-shadow(0 6px 16px rgba(0, 104, 255, 0.32)); flex-shrink: 0;">
                    <defs>
                        <linearGradient id="heroFacetLeftFront" x1="20%" y1="10%" x2="50%" y2="90%">
                            <stop offset="0%" stop-color="#38BDF8"/>
                            <stop offset="60%" stop-color="#0068FF"/>
                            <stop offset="100%" stop-color="#0047BA"/>
                        </linearGradient>
                        <linearGradient id="heroFacetLeftTop" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#BAE6FD"/>
                            <stop offset="100%" stop-color="#38BDF8"/>
                        </linearGradient>
                        <linearGradient id="heroFacetRightFront" x1="80%" y1="10%" x2="50%" y2="90%">
                            <stop offset="0%" stop-color="#00A3FF"/>
                            <stop offset="50%" stop-color="#0052CC"/>
                            <stop offset="100%" stop-color="#02388A"/>
                        </linearGradient>
                        <linearGradient id="heroFacetRightTop" x1="100%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#E0F2FE"/>
                            <stop offset="100%" stop-color="#7DD3FC"/>
                        </linearGradient>
                        <linearGradient id="heroFacetCenterGlow" x1="50%" y1="40%" x2="50%" y2="92%">
                            <stop offset="0%" stop-color="#67E8F9"/>
                            <stop offset="100%" stop-color="#0068FF"/>
                        </linearGradient>
                    </defs>
                    <polygon points="18,22 36,12 50,88 34,74" fill="url(#heroFacetLeftFront)"/>
                    <polygon points="18,22 36,12 48,22 30,32" fill="url(#heroFacetLeftTop)"/>
                    <polygon points="82,22 64,12 50,88 66,74" fill="url(#heroFacetRightFront)"/>
                    <polygon points="82,22 64,12 52,22 70,32" fill="url(#heroFacetRightTop)"/>
                    <polygon points="30,32 48,22 50,54 38,58" fill="#0052CC"/>
                    <polygon points="70,32 52,22 50,54 62,58" fill="#003D99"/>
                    <polygon points="38,58 50,54 62,58 50,88" fill="url(#heroFacetCenterGlow)"/>
                </svg>
                <div class="hero-title" style="margin-bottom: 0;">
                    VERAXUS
                </div>
            </div>
            <div class="hero-subtitle">
                Trợ lý Dữ liệu Kinh doanh Thông minh • Trực quan, Tức thì & Tuyệt đối Tin cậy
            </div>
        </div>
        """).strip(), unsafe_allow_html=True)

        # Trục tương tác chính: Thanh Tìm kiếm Lớn tại Trung tâm (Spotlight Search)
        # Căn giữa tỷ lệ vàng cân xứng [1.1, 5.8, 1.1] tạo khoảng thở thoáng đãng hai bên
        col_sp_l, col_center_search, col_sp_r = st.columns([1.1, 5.8, 1.1])
        with col_center_search:
            with st.form(key="center_hero_search_form", clear_on_submit=True, border=False):
                c_in, c_btn = st.columns([4.4, 1.3], gap="small", vertical_alignment="center")
                with c_in:
                    hero_query = st.text_input(
                        "Search",
                        placeholder=" Ask Veraxus...",
                        label_visibility="collapsed",
                        key="hero_search_input"
                    )
                with c_btn:
                    hero_submit = st.form_submit_button("Phân tích ↗", type="primary", use_container_width=True)
                if hero_submit and hero_query.strip():
                    st.session_state["pending_prompt"] = hero_query.strip()
                    st.rerun()

            # Tích hợp Micro giọng nói tiếng Việt trực tiếp bên trong thanh tìm kiếm
            render_voice_input_button(compact=True)

        # Dải Nhận diện Tin cậy Vi mô (Micro-Trust Ribbon - Triết lý "Ẩn giấu công nghệ")
        # Thay thế 3 thẻ kỹ thuật cồng kềnh bằng chỉ báo trạng thái nhẹ nhàng, thanh lịch
        st.markdown(textwrap.dedent("""
        <div class="micro-trust-ribbon">
            <span class="micro-trust-pill">🔒 Bảo mật 100% nội bộ</span>
            <span style="color: #CBD5E1;">•</span>
            <span class="micro-trust-pill">⚡ Kết nối trực tiếp CSDL</span>
            <span style="color: #CBD5E1;">•</span>
            <span class="micro-trust-pill">✨ Sẵn sàng phân tích tức thì</span>
        </div>
        """).strip(), unsafe_allow_html=True)

        # Khám phá câu hỏi theo 3 lăng kính điều hành (Categorized Smart Prompts Tabs)
        categorized = generate_categorized_starter_prompts(tables, schema_context)
        cat_keys = list(categorized.keys())

        st.markdown("""
        <div class="prompt-tab-intro">
            <span>🎯</span> <span><b>Gợi ý phân tích theo lăng kính điều hành:</b></span>
        </div>
        """, unsafe_allow_html=True)

        prompt_tabs = st.tabs(cat_keys)
        for tab_idx, cat_name in enumerate(cat_keys):
            with prompt_tabs[tab_idx]:
                card_list = categorized[cat_name]
                cols = st.columns(len(card_list), gap="medium")
                for card_idx, card in enumerate(card_list):
                    with cols[card_idx]:
                        with st.container(border=True):
                            st.markdown(f"""
                            <div style="font-size: 0.92rem; font-weight: 700; color: #0F172A; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                                <span>{card['icon']}</span> <span>{card['title']}</span>
                            </div>
                            <div style="font-size: 0.8rem; color: #64748B; min-height: 40px; line-height: 1.4; margin-bottom: 8px;">
                                {card['desc']}
                            </div>
                            """, unsafe_allow_html=True)

                            def _make_click_handler(prompt_text=card["prompt"]):
                                def _handler():
                                    st.session_state["pending_prompt"] = prompt_text
                                return _handler

                            st.button(
                                "Phân tích ngay ⚡",
                                key=f"btn_cat_{tab_idx}_{card_idx}",
                                use_container_width=True,
                                help=f"Chạy truy vấn: \"{card['prompt']}\"",
                                on_click=_make_click_handler(card["prompt"])
                            )




    if prompt_to_run:
        # Xóa pending prompt và reset focus view
        st.session_state["pending_prompt"] = None
        st.session_state["focused_turn_idx"] = None

        cache_key = prompt_to_run.strip().lower()
        cached = st.session_state.get("query_cache", {}).get(cache_key)

        if st.session_state.get("enable_cache", True) and cached and not cached.get("error"):
            result = cached
        else:
            st.chat_message("user").write(prompt_to_run)
            with st.chat_message("assistant"):
                status_placeholder = st.empty()
                def update_status(text: str):
                    status_placeholder.markdown(
                        render_veraxus_loading_html(text),
                        unsafe_allow_html=True
                    )

                update_status("Đang phân tích câu hỏi & đối chiếu dữ liệu doanh nghiệp...")
                current_engine = st.session_state.get("engine")
                current_schema = st.session_state.get("schema_context", "")
                if current_engine and (not current_schema or not current_schema.strip()):
                    current_schema = auto_extract_schema(current_engine)
                    st.session_state["schema_context"] = current_schema

                result = run_agent(
                    user_query=prompt_to_run,
                    client=st.session_state.get("client"),
                    provider=st.session_state.get("provider"),
                    model_name=st.session_state.get("model_name"),
                    engine=current_engine,
                    schema_context=current_schema,
                    dialect=st.session_state.get("db_dialect", "SQLite"),
                    db_pass=st.session_state.get("_db_pass_for_sanitize", ""),
                    enable_self_check=st.session_state.get("enable_self_check", True),
                    enable_auto_insights=st.session_state.get("enable_auto_insights", True),
                    status_callback=update_status
                )
                status_placeholder.empty()
                if not result.get("error"):
                    st.session_state.setdefault("query_cache", {})[cache_key] = result

        st.session_state["history"].append(result)
        st.rerun()
