"""
Veraxus for SQL - Streamlit Application Entry Point.
Featuring standalone Onboarding, interactive Explorer Sidebar, direct History Inspection,
Smart Starter Cards (1-Click), and Follow-up Question Suggestions.
"""

import pathlib
import re
import sys
import textwrap
import streamlit as st

# ---------------------------------------------------------
# 1. Cấu hình Trang Streamlit (BẮT BUỘC là lệnh Streamlit đầu tiên)
# ---------------------------------------------------------
st.set_page_config(
    page_title="Veraxus - Enterprise Intelligence",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import importlib
import src.i18n
import src.database.crm_queries
import src.database.business_upload
import src.analytics.heuristics
import src.analytics.anomaly
import src.ui.components
import src.ui.sidebar
import src.ui.crm_dashboard
import src.llm.prompts
import src.llm.few_shot_selector
import src.llm.router_planner
import src.llm.evaluator
import src.llm.datamate_bridge
import src.llm.agent
import src.llm

# Tự động xóa sạch query cache cũ & hot-reload các submodule khi cập nhật code mới
def _compute_backend_mtime_sig() -> str:
    """Compute a lightweight mtime signature across backend Python modules."""
    root = pathlib.Path(__file__).resolve().parent
    latest_ns = 0
    file_count = 0
    for pkg_dir in ("src", "datamate"):
        base = root / pkg_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            try:
                st_res = py_file.stat()
                file_count += 1
                if st_res.st_mtime_ns > latest_ns:
                    latest_ns = st_res.st_mtime_ns
            except OSError:
                continue
    return f"{file_count}:{latest_ns}"


CACHE_BUILD_ID = "20261119_datamate_veraxus_v237"
_EFFECTIVE_BUILD_ID = f"{CACHE_BUILD_ID}:{_compute_backend_mtime_sig()}"
_HOT_RELOAD_ORDER = (
    "src.i18n",
    "src.config",
    "src.config_store",
    "src.database.connection",
    "src.database.schema",
    "src.database.query_runner",
    "src.database.demo_data",
    "src.database.crm_queries",
    "src.database.business_upload",
    "src.analytics.heuristics",
    "src.analytics.anomaly",
    "src.analytics.forecasting",
    "src.analytics.export_reports",
    "src.analytics.share_report",
    "src.visualization.charts",
    "src.visualization.crm_dashboard_charts",
    "src.visualization.chart_modal",
    "src.visualization",
    "datamate.temporal",
    "datamate.loader",
    "datamate.schema_context",
    "datamate.knowledge_store",
    "datamate.sql_executor",
    "datamate.evaluator_pa",
    "datamate.splits",
    "datamate.llm_backend",
    "datamate.agent",
    "datamate",
    "src.llm.client",
    "src.llm.sql_sanitizer",
    "src.llm.schema_linker",
    "src.llm.few_shots_data",
    "src.llm.prompts",
    "src.llm.few_shot_selector",
    "src.llm.dynamic_memory",
    "src.llm.router_planner",
    "src.llm.datamate_bridge",
    "src.llm.evaluator",
    "src.llm.agent",
    "src.llm",
    "src.ui.state",
    "src.ui.components",
    "src.ui.connection_dialog",
    "src.ui.onboarding",
    "src.ui.sidebar",
    "src.ui.evolution_dashboard",
    "src.ui.crm_dashboard",
)
if getattr(sys, "_veraxus_loaded_build_id", None) != _EFFECTIVE_BUILD_ID:
    for _mod_name in _HOT_RELOAD_ORDER:
        _mod_obj = sys.modules.get(_mod_name)
        if _mod_obj is not None:
            importlib.reload(_mod_obj)
    try:
        st.cache_data.clear()
    except Exception:
        pass
    setattr(sys, "_veraxus_loaded_build_id", _EFFECTIVE_BUILD_ID)

from src.i18n import t, get_current_language, set_current_language
from src.config_store import load_saved_config
from src.database.schema import get_table_names, auto_extract_schema
from src.analytics.heuristics import (
    generate_starter_prompts,
    generate_categorized_starter_prompts,
    is_non_data_conversational
)
from src.ui.state import init_session_state
from src.ui.onboarding import render_onboarding
from src.ui.sidebar import perform_connection, render_main_sidebar
from src.ui.components import (
    render_result,
    render_voice_input_button,
    render_veraxus_loading_html,
    render_loading_stale_guard_css,
)
from src.ui.crm_dashboard import render_crm_dashboard
from src.llm.agent import run_agent

if st.session_state.get("_cache_build_id") != _EFFECTIVE_BUILD_ID:
    st.session_state["_cache_build_id"] = _EFFECTIVE_BUILD_ID
    st.session_state["query_cache"] = {}
    st.session_state["_needs_history_heal"] = True

    # Tự động chữa lành các lượt hội thoại phi dữ liệu trong history (xóa bỏ bảng, biểu đồ, SQL ảo)
    if "history" in st.session_state and st.session_state["history"]:
        cleaned_history = []
        for h in st.session_state["history"]:
            if not isinstance(h, dict):
                continue
            q_text = str(h.get("query", ""))
            if is_non_data_conversational(q_text):
                h["df"] = None
                h["sql"] = None
                h["insights"] = None
                h["anomalies_info"] = None
                h["agent_trace"] = None
                q_low = q_text.lower()
                if any(k in q_low for k in ["ốm", "sốt", "mệt", "đau", "bệnh", "sick", "tired"]):
                    h["explanation"] = (
                        "Tôi rất tiếc khi biết bạn không được khỏe! Bạn hãy nghỉ ngơi nhiều, giữ ấm và uống đủ nước ấm để mau hồi phục nhé. "
                        "Tôi là Trợ lý Dữ liệu Kinh doanh Veraxus — khi nào bạn khỏe lại và cần tra cứu, phân tích số liệu, tôi luôn sẵn sàng hỗ trợ bạn!"
                    )
                elif any(k in q_low for k in ["chào", "xin chào", "hello", "hi", "hey"]):
                    h["explanation"] = "Xin chào bạn! Tôi là Trợ lý Dữ liệu Kinh doanh Veraxus. Bạn cần tra cứu, phân tích hay lập báo cáo số liệu nào hôm nay?"
                elif any(k in q_low for k in ["bạn là ai", "tên gì", "who are you"]):
                    h["explanation"] = "Tôi là Veraxus — AI Data Analyst & Trợ lý Dữ liệu Kinh doanh. Tôi có thể hỗ trợ bạn truy vấn tự động, vẽ biểu đồ và phân tích chuyên sâu các số liệu từ cơ sở dữ liệu doanh nghiệp!"
                else:
                    h["explanation"] = (
                        "💡 **Thông báo từ Trợ lý:** Câu hỏi của bạn nằm ngoài phạm vi cơ sở dữ liệu doanh nghiệp hiện tại. "
                        "Tôi là Trợ lý Dữ liệu Kinh doanh, chuyên hỗ trợ phân tích các thông tin về bán hàng, sản phẩm, nhân sự, đơn hàng và khách hàng.\n\n"
                        "👉 Bạn có thể thử các câu hỏi về doanh số, sản phẩm hoặc thị trường để tôi hỗ trợ nhé!"
                    )
            cleaned_history.append(h)
        st.session_state["history"] = cleaned_history

    try:
        st.cache_data.clear()
    except Exception:
        pass

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&display=swap');
    
    html, body, .stApp, [class*="css"],
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] div,
    [data-testid="stMarkdownContainer"] span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded),
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stTabs"] button p,
    [data-testid="stRadio"] label p,
    [data-testid="stRadio"] label span {
        font-family: 'Be Vietnam Pro', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    
    /* Global Dark Neutral SaaS Theme (Linear / Vercel / Stripe Aesthetic) */
    :root {
        --vx-bg-page: #0B0D12;
        --vx-bg-sidebar: #0F1219;
        --vx-bg-surface: #11141C;
        --vx-bg-elevated: #171B26;
        --vx-border: rgba(255, 255, 255, 0.08);
        --vx-border-hover: rgba(255, 255, 255, 0.16);
        --vx-text-primary: #F8FAFC;
        --vx-text-secondary: #94A3B8;
        --vx-text-muted: #64748B;
        --vx-accent: #2563EB;
        --vx-accent-hover: #3B82F6;
        --vx-positive: #10B981;
        --vx-warning: #F59E0B;
        --vx-negative: #EF4444;
    }
    .stApp {
        background-color: #0B0D12 !important;
        color: #F8FAFC !important;
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
        background: #11141C !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 8px !important;
        box-shadow: none !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebarCollapseButton"] {
        visibility: visible !important;
        display: inline-flex !important;
        opacity: 1 !important;
    }

    /* Tinh chỉnh Sidebar - Dark Neutral (#0F1219) sắc nét & phân tách nhẹ nhàng */
    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(255, 255, 255, 0.07) !important;
        background-color: #0F1219 !important;
        min-width: 300px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        background-color: #0F1219 !important;
        padding-left: 1.4rem !important;
        padding-right: 1.2rem !important;
        padding-top: 1.1rem !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
    section[data-testid="stSidebar"] .stCaption {
        color: #E2E8F0 !important;
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
    
    /* Thẻ Chỉ số Điều hành (Executive KPI Cards) - Flat Neutral Surface & Tabular Nums */
    div[data-testid="stMetric"] {
        background-color: #11141C !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        padding: 12px 14px !important;
        border-radius: 12px !important;
        box-shadow: none !important;
        transition: border-color 0.15s ease, background-color 0.15s ease;
        min-width: 0 !important;
        overflow: hidden !important;
    }
    div[data-testid="stMetric"]:hover {
        border-color: rgba(255, 255, 255, 0.16) !important;
        background-color: #151924 !important;
        box-shadow: none !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: clamp(0.7rem, 0.88vw, 0.74rem) !important;
        font-weight: 600 !important;
        color: #94A3B8 !important;
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
        color: #94A3B8 !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: clamp(1.15rem, 1.4vw, 1.35rem) !important;
        font-weight: 700 !important;
        color: #F8FAFC !important;
        letter-spacing: -0.01em;
        font-variant-numeric: tabular-nums;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        line-height: 1.25 !important;
    }
    div[data-testid="stMetricValue"] > div {
        font-size: inherit !important;
        font-variant-numeric: tabular-nums;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        color: #F8FAFC !important;
    }
    div[data-testid="stMetricDelta"] {
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        font-variant-numeric: tabular-nums;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    [data-testid="stDataFrame"] {
        font-variant-numeric: tabular-nums;
    }

    /* Hệ thống Nút bấm Chuẩn SaaS Blue (#2563EB) - Tối giản, Không Phát Sáng */
    .stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.86rem !important;
        line-height: 1.4 !important;
        padding: 8px 14px !important;
        min-height: 40px !important;
        height: auto !important;
        transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
        white-space: normal !important;
        word-break: break-word !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
    }
    .stButton > button[kind="primary"] {
        background: #2563EB !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        color: #FFFFFF !important;
        box-shadow: none !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: #3B82F6 !important;
        color: #FFFFFF !important;
        box-shadow: none !important;
        transform: none !important;
    }
    .stButton > button[kind="secondary"] {
        background-color: #161A24 !important;
        border: 1px solid rgba(255, 255, 255, 0.09) !important;
        color: #E2E8F0 !important;
        box-shadow: none !important;
    }
    .stButton > button[kind="secondary"]:hover {
        border-color: rgba(255, 255, 255, 0.18) !important;
        background-color: #1E2433 !important;
        color: #F8FAFC !important;
        box-shadow: none !important;
        transform: none !important;
    }

    /* Hero Section - Tối giản, Tập trung, Tỷ lệ Cân đối */
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
        background: rgba(255, 255, 255, 0.04);
        color: #94A3B8;
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.76rem;
        font-weight: 600;
        letter-spacing: 0.01em;
        margin-bottom: 10px;
        box-shadow: none;
    }
    .hero-badge-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #10B981;
    }
    .hero-title {
        font-size: 2.35rem;
        font-weight: 800;
        color: #F8FAFC !important;
        letter-spacing: -0.03em;
        line-height: 1.2;
        margin-bottom: 6px;
    }
    .hero-subtitle {
        font-size: 1.02rem;
        color: #94A3B8 !important;
        line-height: 1.5;
        max-width: 640px;
        margin: 0 auto 18px auto;
        font-weight: 400;
    }

    /* 3 Thẻ Trạng thái Hệ thống Live Snapshot */
    .micro-trust-ribbon {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        margin: 4px auto 24px auto;
        font-size: 0.78rem;
        color: #94A3B8;
        font-weight: 500;
    }
    .micro-trust-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #11141C;
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 4px 11px;
        border-radius: 9999px;
        font-size: 0.75rem;
        color: #CBD5E1;
        transition: border-color 0.15s ease;
    }
    .micro-trust-pill:hover {
        background: #161A24;
        border-color: rgba(255, 255, 255, 0.16);
        color: #F8FAFC;
    }
    .health-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
    }
    .health-card-title {
        font-size: 0.75rem;
        font-weight: 600;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .health-badge {
        font-size: 0.72rem;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 6px;
        white-space: nowrap;
    }
    .health-badge-green {
        background: rgba(16, 185, 129, 0.1);
        color: #34D399;
        border: 1px solid rgba(16, 185, 129, 0.2);
    }
    .health-badge-blue {
        background: rgba(59, 130, 246, 0.1);
        color: #60A5FA;
        border: 1px solid rgba(59, 130, 246, 0.2);
    }
    .health-badge-purple {
        background: rgba(139, 92, 246, 0.1);
        color: #A78BFA;
        border: 1px solid rgba(139, 92, 246, 0.2);
    }
    .health-card-value {
        font-size: 1.15rem;
        font-weight: 700;
        color: #F8FAFC !important;
        line-height: 1.35;
        margin: 4px 0 2px 0;
        letter-spacing: -0.015em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .health-card-sub {
        font-size: 0.78rem;
        color: #94A3B8;
        line-height: 1.35;
    }

    /* Trục Tìm kiếm Trung tâm Hero Search - Tỷ lệ Chuẩn Claude & Linear (860px) */
    form[data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
        background: transparent !important;
        margin: 16px auto 20px auto !important;
        max-width: 860px !important;
        width: 100% !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] {
        margin-bottom: 0 !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"],
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"] {
        border-radius: 12px !important;
        background-color: #11141C !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25) !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"]:hover,
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"]:hover {
        border-color: rgba(255, 255, 255, 0.22) !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"]:focus-within {
        border-color: #3B82F6 !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.25) !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] input {
        height: 48px !important;
        min-height: 48px !important;
        border-radius: 12px !important;
        background-color: transparent !important;
        border: none !important;
        font-size: 0.98rem !important;
        padding: 0 18px !important;
        color: #F8FAFC !important;
        box-shadow: none !important;
    }
    form[data-testid="stForm"] .stButton > button {
        height: 48px !important;
        min-height: 48px !important;
        border-radius: 12px !important;
        font-size: 0.92rem !important;
        font-weight: 600 !important;
        background: #2563EB !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        color: #FFFFFF !important;
        white-space: nowrap !important;
        box-shadow: none !important;
        transition: background-color 0.15s ease !important;
    }
    form[data-testid="stForm"] .stButton > button:hover {
        background: #3B82F6 !important;
        color: #FFFFFF !important;
        box-shadow: none !important;
        transform: none !important;
    }
    /* Ẩn dòng chữ watermark submit instructions của Streamlit để thanh search đạt độ tinh gọn tuyệt đối */
    div[data-testid="InputInstructions"],
    span[data-testid="stFormSubmitInstructions"] {
        display: none !important;
        visibility: hidden !important;
        height: 0px !important;
    }

    /* Khám phá Theo Lăng Kính Điều Hành (Tabs) - Nhẹ nhàng, Ngăn nắp, Căn giữa 860px */
    .prompt-tab-intro {
        margin: 18px auto 10px auto;
        max-width: 860px;
        font-size: 0.86rem;
        font-weight: 600;
        color: #94A3B8 !important;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .stTabs {
        max-width: 860px;
        margin: 0 auto;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        margin-bottom: 14px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 14px;
        border-radius: 8px 8px 0 0;
        font-size: 0.86rem;
        font-weight: 500;
        color: #94A3B8 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #F8FAFC !important;
        font-weight: 600 !important;
        border-bottom: 2px solid #3B82F6 !important;
    }

    /* Thẻ Gợi Ý Hành Động (Prompt Action Cards) - Flat Surface & Clean Hover */
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        background: #11141C !important;
        padding: 14px 16px !important;
        transition: border-color 0.15s ease, background-color 0.15s ease !important;
        box-shadow: none !important;
        min-height: 142px !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: rgba(255, 255, 255, 0.18) !important;
        background: #151924 !important;
        box-shadow: none !important;
        transform: none;
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button {
        min-height: 36px !important;
        height: 36px !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        background-color: #171C28 !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: #E2E8F0 !important;
        white-space: nowrap !important;
        box-shadow: none !important;
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover {
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        border-color: #2563EB !important;
        box-shadow: none !important;
    }

    /* Minimalist 3-dot Orbiting Loading Indicator & Clean Popover Styling */
    .vx-loading-bar {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 8px 2px;
        margin: 4px 0;
    }
    .vx-orbit-dots {
        position: relative;
        display: inline-block;
        width: 16px;
        height: 16px;
        flex-shrink: 0;
        animation: vx-spin 1.05s linear infinite;
    }
    .vx-orbit-dots > span {
        position: absolute;
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: #60A5FA;
    }
    .vx-orbit-dots > span:nth-child(1) {
        top: 0.8px;
        left: 6px;
        opacity: 1;
    }
    .vx-orbit-dots > span:nth-child(2) {
        top: 8.6px;
        left: 10.5px;
        opacity: 0.62;
    }
    .vx-orbit-dots > span:nth-child(3) {
        top: 8.6px;
        left: 1.5px;
        opacity: 0.32;
    }
    .vx-loading-text {
        color: #94A3B8;
        font-size: 0.88rem;
        font-weight: 450;
        line-height: 1.4;
    }
    @keyframes vx-spin {
        to { transform: rotate(360deg); }
    }
    @media (prefers-reduced-motion: reduce) {
        .vx-orbit-dots {
            animation: none;
        }
    }
    [data-testid="stPopover"] > button {
        background-color: #161A24 !important;
        border: 1px solid rgba(255, 255, 255, 0.09) !important;
        border-radius: 8px !important;
        color: #94A3B8 !important;
        min-height: 40px !important;
        height: auto !important;
        padding: 6px 10px !important;
        box-shadow: none !important;
        transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
    }
    [data-testid="stPopover"] > button:hover {
        border-color: rgba(255, 255, 255, 0.18) !important;
        background-color: #1E2433 !important;
        color: #F8FAFC !important;
    }
    [data-testid="stPopover"] > button svg {
        width: 14px !important;
        height: 14px !important;
        opacity: 0.55 !important;
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
        elif provider == "Ollama (Local AI Offline)":
            api_key = saved.get("api_key_ollama", "") or "ollama"
        else:
            api_key = saved.get("api_key_qwen", "")

        clean_api_key = api_key.strip()
        is_openrouter_key = clean_api_key.startswith("sk-or-v1-")
        effective_provider = "OpenRouter" if is_openrouter_key else provider

        saved_mode_idx = saved.get("data_mode_index", 0)
        custom_workspace_dir = (saved.get("custom_workspace_dir", "") or "").strip() if saved_mode_idx == 2 else ""
        has_custom_ws = bool(custom_workspace_dir and pathlib.Path(custom_workspace_dir).is_dir())
        use_demo = (saved_mode_idx == 0)
        is_mysql_mode = (not use_demo) and (not has_custom_ws)

        db_host = (saved.get("db_host", "") or "").strip()
        db_user = (saved.get("db_user", "") or "").strip()
        db_name = (saved.get("db_name", "") or "").strip()
        run_local = saved.get("run_local", True) or (db_host in ("localhost", "127.0.0.1", ""))

        if is_mysql_mode and run_local and not db_host:
            db_host = "localhost"

        if effective_provider == "Ollama (Local AI Offline)" and not clean_api_key:
            clean_api_key = "ollama"
        has_provider_auth = bool(clean_api_key) or (effective_provider == "Ollama (Local AI Offline)")
        can_connect = has_provider_auth and (use_demo or has_custom_ws or bool(db_user and db_name and (db_host or run_local)))

        if can_connect:
            if effective_provider == "OpenRouter":
                custom_base_url = saved.get("openrouter_base_url", "")
                default_model_for_p = "deepseek/deepseek-chat"
            elif effective_provider == "Gemini (Google)":
                custom_base_url = ""
                default_model_for_p = "gemini-3.7-flash"
            elif effective_provider == "Ollama (Local AI Offline)":
                custom_base_url = saved.get("ollama_base_url", "")
                default_model_for_p = "qwen2.5-coder:3b"
            else:
                custom_base_url = saved.get("qwen_base_url", "")
                default_model_for_p = "qwen-plus"

            target_model = saved.get("model_name") or default_model_for_p
            if effective_provider == "Gemini (Google)" and "deepseek" in target_model.lower():
                target_model = "gemini-3.7-flash"

            mode_label = "DataMate Workspace" if has_custom_ws else ("SQLite Demo" if use_demo else "MySQL")
            with st.spinner(f"⚡ Đang tự động kết nối lại {effective_provider} & {mode_label}..."):
                success, detail = perform_connection(
                    use_demo=use_demo,
                    db_host=db_host if is_mysql_mode else "",
                    db_port=saved.get("db_port", "3306"),
                    db_user=db_user if is_mysql_mode else "",
                    db_pass=saved.get("db_pass", "") if is_mysql_mode else "",
                    db_name=db_name,
                    use_ssl=saved.get("use_ssl", False) if (is_mysql_mode and not run_local) else False,
                    run_local=run_local if is_mysql_mode else False,
                    effective_provider=effective_provider,
                    clean_api_key=clean_api_key,
                    custom_base_url=custom_base_url,
                    selected_model=target_model,
                    schema_context_input="",
                    custom_workspace_dir=custom_workspace_dir,
                )
                if success:
                    st.session_state["view_mode"] = "chat"
                    st.toast(f"⚡ Đã tự động kết nối {effective_provider} & {mode_label}!", icon="⚡")
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
    with st.container():
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


    def _format_user_chat_display(query: str) -> str:
        if not query:
            return ""
        q_strip = query.strip()
        if q_strip.startswith("BÁO CÁO CHUYÊN SÂU TỪ SENIOR LEAD DATA ANALYST:"):
            import re
            m = re.search(r"Thời gian khảo sát:\s*([^\n]+)", q_strip)
            t_str = f" ({m.group(1).strip()})" if m else ""
            return f"🏛️ **Yêu cầu Lập Kế Hoạch & Soạn Thảo Nghị Quyết Chiến Lược Ban Điều Hành{t_str}**"
        return query

    history = st.session_state.get("history", [])
    if history and st.session_state.get("engine") is not None:
        try:
            from src.llm.agent import (
                auto_fix_chocolates_half_year_comparison_query,
                auto_fix_chocolates_consecutive_growth_streak_query,
                auto_fix_chocolates_new_products_query,
                auto_fix_chocolates_monthly_spread_query,
                auto_fix_chocolates_quarterly_growth_comparison_query,
                auto_fix_chocolates_top_rankings_query,
            )
            from src.database.query_runner import read_sql_capped
            from src.analytics.anomaly import analyze_data_anomalies
            from src.analytics.heuristics import split_insight_sections
            _eng = st.session_state.get("engine")
            _dial = st.session_state.get("db_dialect", "MySQL")
            for _turn in history:
                if not isinstance(_turn, dict):
                    continue
                if st.session_state.get("datamate_knowledge") is not None or _turn.get("is_datamate_turn"):
                    _dm_know = st.session_state.get("datamate_knowledge")
                    _q_dm = str(_turn.get("query") or "")
                    _sql_dm = str(_turn.get("sql") or "")
                    if _dm_know is not None and _q_dm and _turn.get("df") is not None:
                        from datamate.agent import check_preflight_unanswerable, classify_expected_type
                        from src.llm.datamate_bridge import _governance_notice, resolve_interactive_as_of_date

                        _as_of_dm = resolve_interactive_as_of_date(_dm_know)
                        _pref_reason = check_preflight_unanswerable(
                            _q_dm,
                            _as_of_dm,
                            _dm_know,
                            classify_expected_type(_q_dm),
                        )
                        if _pref_reason:
                            _turn["df"] = None
                            _turn["sql"] = None
                            _turn["insights"] = None
                            _turn["anomalies_info"] = None
                            _turn["datamate_prediction"] = None
                            _turn["explanation"] = _governance_notice(
                                "Dữ liệu không đủ thông tin để trả lời chính xác",
                                "Insufficient data to answer reliably",
                                _pref_reason,
                                _turn.get("lang", "vi"),
                            )
                            _turn["evaluator"] = {
                                "verdict": "UNANSWERABLE_BLOCKED",
                                "score": 100,
                                "critique": _pref_reason,
                            }
                            continue
                    if _dm_know is not None and _q_dm and _sql_dm:
                        from datamate.agent import classify_expected_type, format_sql_result, rewrite_ranked_entity_sql
                        from datamate.sql_executor import execute_sql_safe
                        from src.llm.datamate_bridge import _format_answer_banner

                        _sql_dm_fixed = rewrite_ranked_entity_sql(_sql_dm, _q_dm, use_round_half_up=True)
                        if _sql_dm_fixed != _sql_dm:
                            _res_dm = execute_sql_safe(
                                _dm_know.workspace.open_connection,
                                _sql_dm_fixed,
                                valid_tables=_dm_know.valid_tables,
                                max_rows=500,
                                timeout_seconds=8.0,
                            )
                            if _res_dm.ok and _res_dm.rows:
                                _df_dm = pd.DataFrame(_res_dm.rows, columns=_res_dm.columns)
                                _an_dm = classify_expected_type(_q_dm)
                                _fmt_dm = format_sql_result(_res_dm, _an_dm, _q_dm)
                                _turn["sql"] = _res_dm.sql or _sql_dm_fixed
                                _turn["df"] = _df_dm
                                _turn["datamate_prediction"] = _fmt_dm
                                _turn["explanation"] = _format_answer_banner(_fmt_dm, _an_dm, _turn.get("lang", "vi"), sql_res=_res_dm)
                                _sec_dm = split_insight_sections("", df=_df_dm, user_query=_q_dm, is_en=(_turn.get("lang") == "en"))
                                _turn["insights"] = (
                                    f"### 2.1. Phát hiện Bất thường & Xu hướng Chính\n{_sec_dm['anomaly']}\n\n"
                                    f"### 2.2. Giả thuyết & Nguyên nhân Tiềm năng\n{_sec_dm['hypothesis']}\n\n"
                                    f"### 2.3. Kế hoạch Hành động & Đề xuất Ưu tiên\n{_sec_dm['action_plan']}"
                                )
                    if _turn.get("df") is not None and len(_turn["df"]) == 1 and "Thực thể Trọng tâm:" in (_turn.get("insights") or ""):
                        _sec_dm = split_insight_sections("", df=_turn["df"], user_query=_q_dm, is_en=(_turn.get("lang") == "en"))
                        _turn["insights"] = (
                            f"### 2.1. Phát hiện Bất thường & Xu hướng Chính\n{_sec_dm['anomaly']}\n\n"
                            f"### 2.2. Giả thuyết & Nguyên nhân Tiềm năng\n{_sec_dm['hypothesis']}\n\n"
                            f"### 2.3. Kế hoạch Hành động & Đề xuất Ưu tiên\n{_sec_dm['action_plan']}"
                        )
                    if _dm_know is not None and _turn.get("df") is not None and not _turn["df"].empty:
                        from src.analytics.heuristics import ensure_continuous_daily_series
                        _df_before_fill = _turn["df"]
                        _df_filled = ensure_continuous_daily_series(
                            _df_before_fill,
                            user_query=_q_dm,
                            min_date=_dm_know.data_min_date,
                            max_date=_dm_know.data_max_date,
                        )
                        if len(_df_filled) > len(_df_before_fill):
                            _turn["df"] = _df_filled
                            _sec_dm = split_insight_sections("", df=_df_filled, user_query=_q_dm, is_en=(_turn.get("lang") == "en"))
                            _turn["insights"] = (
                                f"### 2.1. Phát hiện Bất thường & Xu hướng Chính\n{_sec_dm['anomaly']}\n\n"
                                f"### 2.2. Giả thuyết & Nguyên nhân Tiềm năng\n{_sec_dm['hypothesis']}\n\n"
                                f"### 2.3. Kế hoạch Hành động & Đề xuất Ưu tiên\n{_sec_dm['action_plan']}"
                            )
                    if _dm_know is not None:
                        from src.llm.datamate_bridge import build_datamate_suggested_questions

                        _cur_fups = [str(f).lower() for f in (_turn.get("followups") or [])]
                        _has_legacy_static = any(
                            ("tổng doanh thu và số đơn hợp lệ trong tháng" in f)
                            or ("ngày nào có doanh thu cao nhất trong tháng" in f)
                            for f in _cur_fups
                        )
                        if not _cur_fups or _has_legacy_static:
                            _turn["followups"] = build_datamate_suggested_questions(
                                _dm_know,
                                lang=_turn.get("lang", "vi"),
                                user_query=_q_dm,
                                df=_turn.get("df"),
                                sql=str(_turn.get("sql") or ""),
                                asked_queries=[str(h.get("query") or "") for h in history if isinstance(h, dict) and h.get("query")],
                            )
                    continue
                _q = str(_turn.get("query") or "")
                _sql_orig = str(_turn.get("sql") or "")
                if not _q:
                    continue
                if is_non_data_conversational(_q):
                    _turn["df"] = None
                    _turn["sql"] = None
                    _turn["insights"] = None
                    _turn["anomalies_info"] = None
                    _turn["agent_trace"] = None
                    continue
                _sql_new = _sql_orig
                _sql_new = auto_fix_chocolates_half_year_comparison_query(_sql_new, _q, dialect=_dial)
                _sql_new = auto_fix_chocolates_consecutive_growth_streak_query(_sql_new, _q, dialect=_dial)
                _sql_new = auto_fix_chocolates_new_products_query(_sql_new, _q, dialect=_dial)
                _sql_new = auto_fix_chocolates_monthly_spread_query(_sql_new, _q, dialect=_dial)
                _sql_new = auto_fix_chocolates_quarterly_growth_comparison_query(_sql_new, _q, dialect=_dial)
                _sql_new = auto_fix_chocolates_top_rankings_query(_sql_new, _q, dialect=_dial)
                if _sql_new and _sql_new != _sql_orig:
                    _df_new, _ = read_sql_capped(_sql_new, _eng)
                    if _df_new is not None and not _df_new.empty:
                        _turn["sql"] = _sql_new
                        _turn["df"] = _df_new
                        _turn["explanation"] = None
                        _turn["anomalies_info"] = analyze_data_anomalies(_df_new)
                        _sec = split_insight_sections("", df=_df_new, user_query=_q, is_en=(_turn.get("lang") == "en"))
                        _turn["insights"] = (
                            f"### 2.1. Phát hiện Bất thường & Xu hướng Chính\n{_sec['anomaly']}\n\n"
                            f"### 2.2. Giả thuyết & Nguyên nhân Tiềm năng\n{_sec['hypothesis']}\n\n"
                            f"### 2.3. Kế hoạch Hành động & Đề xuất Ưu tiên\n{_sec['action_plan']}"
                        )
                else:
                    _ins = _turn.get("insights") or ""
                    if ("Đơn vị/ngạch" in _ins or "cho từng thành viên trong" in _ins) and _turn.get("df") is not None and not _turn["df"].empty:
                        _sec = split_insight_sections("", df=_turn["df"], user_query=_q, is_en=(_turn.get("lang") == "en"))
                        _turn["insights"] = (
                            f"### 2.1. Phát hiện Bất thường & Xu hướng Chính\n{_sec['anomaly']}\n\n"
                            f"### 2.2. Giả thuyết & Nguyên nhân Tiềm năng\n{_sec['hypothesis']}\n\n"
                            f"### 2.3. Kế hoạch Hành động & Đề xuất Ưu tiên\n{_sec['action_plan']}"
                        )
        except Exception:
            pass
    focused_turn_idx = st.session_state.get("focused_turn_idx", None)
    view_mode = st.session_state.get("view_mode", "chat")

    # Tiếp nhận câu hỏi từ Chat Input hoặc Pending Prompt (từ Thẻ Starter / Gợi ý tiếp nối)
    has_active_conversation = bool(history) or (focused_turn_idx is not None)
    pending_prompt = st.session_state.get("pending_prompt") or st.session_state.get("submitted_query")

    # Chỉ hiển thị chat_input ở chân trang khi ĐÃ CÓ lịch sử trò chuyện hoặc đang ở chế độ Chat
    user_input = None
    if has_active_conversation and view_mode == "chat":
        user_input = st.chat_input(" Ask Veraxus...")

    prompt_to_run = pending_prompt or user_input

    # Khi có câu hỏi mới sắp tính toán, chuyển thẳng sang chế độ Chat & gỡ focus cũ TRƯỚC khi render
    # để tránh hiển thị banner focus cũ hoặc giữ các phần tử thừa của Dashboard/Welcome ở phía dưới.
    if prompt_to_run:
        focused_turn_idx = None
        st.session_state["focused_turn_idx"] = None
        view_mode = "chat"
        st.session_state["view_mode"] = "chat"

    # Mỗi màn hình ngoài Chat (Dashboard / Evolution / Focused / Welcome) được gói trong 1 st.container()
    # duy nhất ở slot main[1], nên khi chuyển sang Chat (st.chat_message ở main[1]), Streamlit thay thế
    # toàn bộ cây DOM cũ ngay lập tức (0ms) thay vì để lại bóng mờ (stale) phía dưới lúc đang tính toán.
    if view_mode == "dashboard" and not prompt_to_run:
        with st.container():
            render_crm_dashboard()
    elif view_mode == "evolution" and not prompt_to_run:
        with st.container():
            from src.ui.evolution_dashboard import render_evolution_dashboard
            render_evolution_dashboard()

    # 4.2 Hiển thị câu hỏi được chọn trực tiếp (Direct Focus View) hoặc toàn bộ hội thoại
    elif focused_turn_idx is not None and 0 <= focused_turn_idx < len(history):
        with st.container():
            turn = history[focused_turn_idx]
            col_focus1, col_focus2 = st.columns([5, 1])
            with col_focus1:
                disp_title = _format_user_chat_display(turn['query'])
                st.info(f"📌 **Đang xem câu hỏi số {focused_turn_idx + 1}**: *\"{disp_title}\"*")
            with col_focus2:
                if st.button("🌐 Xem tất cả", use_container_width=True, key="btn_exit_focus_top", type="secondary", help="Quay lại xem toàn bộ đoạn hội thoại"):
                    st.session_state["focused_turn_idx"] = None
                    st.rerun()

            st.chat_message("user").write(_format_user_chat_display(turn["query"]))
            with st.chat_message("assistant"):
                try:
                    render_result(turn, turn_id=f"focused_{focused_turn_idx}")
                except Exception as e:
                    st.error(f"⚠️ Có lỗi nhỏ khi hiển thị kết quả lượt này: {e}")
                    if st.button("🔄 Tải lại lượt này", key=f"retry_focus_{focused_turn_idx}"):
                        st.rerun()
    elif history:
        # Hiển thị toàn bộ lịch sử hội thoại
        for i, turn in enumerate(history):
            st.chat_message("user").write(_format_user_chat_display(turn["query"]))
            with st.chat_message("assistant"):
                try:
                    render_result(turn, turn_id=f"hist{i}")
                except Exception as e:
                    st.error(f"⚠️ Có lỗi nhỏ khi hiển thị kết quả lượt này: {e}")
                    if st.button("🔄 Tải lại lượt này", key=f"retry_hist_{i}"):
                        st.rerun()

    # 4.3 Màn hình Khám phá Dữ liệu Chuẩn Thi đấu (Perplexity / CPO Standard)
    if not history and focused_turn_idx is None and not prompt_to_run and view_mode == "chat":
        with st.container():
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
                clean_model = "Gemini 3.7 Flash"
            elif "claude" in model_disp.lower():
                clean_model = "Claude 3.5 Sonnet"


            curr_lang = get_current_language()

            # Cấu hình phong cách Model AI (Claude / Gemini): Căn giữa chính giữa màn hình (Vertical & Horizontal Centering)
            st.markdown("""
            <style>
            /* Toàn bộ vùng hiển thị được căn giữa hoàn hảo theo chuẩn Claude & Gemini */
            .main .block-container {
                min-height: calc(100vh - 4.5rem) !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important;
                align-items: center !important;
                padding-top: 1rem !important;
                padding-bottom: 2.5rem !important;
                max-width: 900px !important;
            }
            .main .block-container > div[data-testid="stVerticalBlock"] {
                margin-top: auto !important;
                margin-bottom: auto !important;
                width: 100% !important;
                max-width: 860px !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important;
            }
            .hero-container {
                text-align: center !important;
                padding: 8px 0 14px 0 !important;
                width: 100% !important;
                margin: 0 auto !important;
            }
            .hero-title {
                font-size: clamp(2.4rem, 3.8vw, 3.1rem) !important;
                font-weight: 800 !important;
                color: #F8FAFC !important;
                letter-spacing: -0.03em !important;
                text-shadow: none !important;
            }
            </style>
            """, unsafe_allow_html=True)

            # Hero Header - Chữ Veraxus & Logo Kim Cương Chính Giữa Khung Hình (Chuẩn Claude / Gemini)
            st.markdown(textwrap.dedent(f"""
            <div class="hero-container">
                <div style="display: flex; align-items: center; justify-content: center; gap: 14px; margin: 0 0 4px 0;">
                    <svg width="42" height="42" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink: 0;">
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
                        {t("hero_title")}
                    </div>
                </div>
            </div>
            """).strip(), unsafe_allow_html=True)

            # Trục tương tác chính: Thanh Button Đặt Câu Hỏi Chuẩn Claude & Gemini
            with st.form(key="center_hero_search_form", clear_on_submit=True, border=False):
                c_in, c_btn = st.columns([5.2, 1.2], gap="small", vertical_alignment="center")
                with c_in:
                    hero_query = st.text_input(
                        "Search",
                        placeholder=f" {t('hero_input_placeholder')}",
                        label_visibility="collapsed",
                        key="hero_search_input"
                    )
                with c_btn:
                    hero_submit = st.form_submit_button(t("hero_btn_analyze"), type="primary", use_container_width=True)
                if hero_submit and hero_query.strip():
                    st.session_state["pending_prompt"] = hero_query.strip()
                    st.rerun()

            # Tích hợp Micro giọng nói trực tiếp bên trong thanh tìm kiếm
            render_voice_input_button(compact=True)

            # Khám phá câu hỏi theo 3 lăng kính điều hành (Categorized Smart Prompts Tabs)
            categorized = generate_categorized_starter_prompts(
                tables,
                schema_context,
                client=st.session_state.get("client"),
                model_name=model_disp,
                provider=provider_name,
                lang=curr_lang
            )
            if not categorized or not isinstance(categorized, dict):
                categorized = generate_dynamic_heuristic_prompts(tables, schema_context, lang=curr_lang) or {}
            if not categorized:
                fallback_title = "Database Overview" if curr_lang == "en" else "Tổng Quan Cơ Sở Dữ Liệu"
                fallback_prompt = "Show overview of all tables in the database" if curr_lang == "en" else "Hiển thị tổng quan các bảng trong cơ sở dữ liệu"
                fallback_desc = "Explore table structures" if curr_lang == "en" else "Khám phá cấu trúc bảng"
                categorized = {
                    t("starter_tab_trends"): [
                        {"icon": "", "title": fallback_title, "prompt": fallback_prompt, "desc": fallback_desc}
                    ]
                }
            cat_keys = list(categorized.keys())

            st.markdown(f"""
            <div class="prompt-tab-intro">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:6px;"><circle cx="12" cy="12" r="10"></circle><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon></svg>
                <span><b>{t("starter_framework_title")}</b></span>
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
                                <div style="font-size: 0.92rem; font-weight: 700; color: #FFFFFF !important; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; min-height: 44px;">
                                    <span>{card['icon']}</span> <span>{card['title']}</span>
                                </div>
                                <div style="font-size: 0.8rem; color: #CBD5E1 !important; min-height: 72px; line-height: 1.4; margin-bottom: 8px;">
                                    {card['desc']}
                                </div>
                                """, unsafe_allow_html=True)

                                def _make_click_handler(prompt_text=card["prompt"]):
                                    def _handler():
                                        st.session_state["pending_prompt"] = prompt_text
                                    return _handler

                                st.button(
                                    t("starter_btn_explore"),
                                    key=f"btn_cat_{tab_idx}_{card_idx}",
                                    use_container_width=True,
                                    help=f"Run query: \"{card['prompt']}\"" if curr_lang == "en" else f"Chạy truy vấn: \"{card['prompt']}\"",
                                    on_click=_make_click_handler(card["prompt"])
                                )

    # Gắn micro vào chat_input sau cùng khi đang ở chế độ Chat nghỉ (không chặn slot main[1])
    if has_active_conversation and view_mode == "chat" and not prompt_to_run:
        render_voice_input_button(compact=True)

    if prompt_to_run:
        # Xóa pending prompt và reset focus view, chuyển về chế độ chat
        st.session_state["pending_prompt"] = None
        st.session_state["submitted_query"] = None
        st.session_state["focused_turn_idx"] = None
        st.session_state["view_mode"] = "chat"

        cache_key = prompt_to_run.strip().lower()
        cached = st.session_state.get("query_cache", {}).get(cache_key)

        # Nếu là câu hỏi giao tiếp phi dữ liệu hoặc cache cũ vô tình dính df/sql, bỏ qua cache cũ
        if is_non_data_conversational(prompt_to_run) or (cached and is_non_data_conversational(cached.get("query", "")) and cached.get("df") is not None):
            cached = None

        # Bỏ qua cache nếu câu hỏi chạm ngưỡng schema không đủ thông tin nhưng cache cũ lại lưu DataFrame
        if cached and cached.get("df") is not None:
            _dm_know_cur = st.session_state.get("datamate_knowledge")
            if _dm_know_cur is not None:
                from datamate.agent import check_preflight_unanswerable, classify_expected_type
                if check_preflight_unanswerable(
                    prompt_to_run,
                    src.llm.datamate_bridge.resolve_interactive_as_of_date(_dm_know_cur),
                    _dm_know_cur,
                    classify_expected_type(prompt_to_run),
                ):
                    cached = None
            if cached and src.llm.datamate_bridge.detect_legacy_schema_gap(
                prompt_to_run,
                engine=st.session_state.get("engine"),
                schema_context=st.session_state.get("schema_context", ""),
                lang=get_current_language(),
            ):
                cached = None

        _asked_queries = [
            str(h.get("query") or "").strip()
            for h in st.session_state.get("history", [])
            if isinstance(h, dict) and h.get("query")
        ]

        if st.session_state.get("enable_cache", True) and cached and not cached.get("error"):
            result = dict(cached)
            _dm_know_hit = st.session_state.get("datamate_knowledge")
            if _dm_know_hit is not None:
                result["followups"] = src.llm.datamate_bridge.build_datamate_suggested_questions(
                    _dm_know_hit,
                    lang=result.get("lang") or get_current_language(),
                    user_query=prompt_to_run,
                    df=result.get("df"),
                    sql=str(result.get("sql") or ""),
                    asked_queries=_asked_queries,
                )
            elif result.get("df") is not None and not result["df"].empty:
                result["followups"] = src.llm.agent.generate_grounded_fallback_followups(
                    result["df"],
                    schema_context=st.session_state.get("schema_context", ""),
                    current_query=prompt_to_run,
                    lang=result.get("lang") or get_current_language(),
                    asked_queries=_asked_queries,
                )
        else:
            st.chat_message("user").write(_format_user_chat_display(prompt_to_run))
            with st.chat_message("assistant"):
                loading_guard_placeholder = st.empty()
                loading_guard_placeholder.markdown(render_loading_stale_guard_css(), unsafe_allow_html=True)
                status_placeholder = st.empty()
                active_lang = get_current_language()
                def update_status(text: str):
                    status_placeholder.markdown(
                        render_veraxus_loading_html(text, is_en=(active_lang == "en")),
                        unsafe_allow_html=True
                    )

                loading_msg = "Reading your data..." if active_lang == "en" else "Đang đọc dữ liệu..."
                update_status(loading_msg)
                current_engine = st.session_state.get("engine")
                current_schema = st.session_state.get("schema_context", "")
                if current_engine and (not current_schema or not current_schema.strip()):
                    current_schema = auto_extract_schema(current_engine)
                    st.session_state["schema_context"] = current_schema

                try:
                    result = src.llm.agent.run_agent(
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
                        status_callback=update_status,
                        lang=active_lang,
                        datamate_knowledge=st.session_state.get("datamate_knowledge"),
                        asked_queries=_asked_queries,
                    )
                finally:
                    status_placeholder.empty()
                    loading_guard_placeholder.empty()
                if not result.get("error"):
                    st.session_state.setdefault("query_cache", {})[cache_key] = result

        st.session_state["history"].append(result)
        st.rerun()
