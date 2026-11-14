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
CACHE_BUILD_ID = "20261114_datamate_veraxus_step1_v225"
if getattr(sys, "_veraxus_loaded_build_id", None) != CACHE_BUILD_ID:
    importlib.reload(src.i18n)
    importlib.reload(src.database.crm_queries)
    importlib.reload(src.database.business_upload)
    importlib.reload(src.analytics.heuristics)
    importlib.reload(src.analytics.anomaly)
    importlib.reload(src.llm.prompts)
    importlib.reload(src.llm.few_shot_selector)
    importlib.reload(src.llm.router_planner)
    importlib.reload(src.llm.evaluator)
    importlib.reload(src.llm.datamate_bridge)
    importlib.reload(src.llm.agent)
    importlib.reload(src.llm)
    importlib.reload(src.ui.components)
    importlib.reload(src.ui.sidebar)
    importlib.reload(src.ui.crm_dashboard)
    try:
        st.cache_data.clear()
    except Exception:
        pass
    setattr(sys, "_veraxus_loaded_build_id", CACHE_BUILD_ID)

from src.i18n import t, get_current_language, set_current_language
from src.config_store import load_saved_config
from src.database.schema import get_table_names
from src.analytics.heuristics import (
    generate_starter_prompts,
    generate_categorized_starter_prompts,
    is_non_data_conversational
)
from src.ui.state import init_session_state
from src.ui.onboarding import render_onboarding
from src.ui.sidebar import perform_connection, render_main_sidebar
from src.ui.components import render_result, render_voice_input_button, render_veraxus_loading_html
from src.ui.crm_dashboard import render_crm_dashboard
from src.llm.agent import run_agent

if st.session_state.get("_cache_build_id") != CACHE_BUILD_ID:
    st.session_state["_cache_build_id"] = CACHE_BUILD_ID
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
    
    /* Global Dark Luxury Theme (#0B0E17) & Cyber Contrast */
    .stApp {
        background-color: #0B0E17 !important;
        color: #FFFFFF !important;
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
        background: #12141C !important;
        border: 1.5px solid #00F0FF !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 10px rgba(0, 240, 255, 0.3) !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebarCollapseButton"] {
        visibility: visible !important;
        display: inline-flex !important;
        opacity: 1 !important;
    }

    /* Tinh chỉnh Sidebar - Dark Theme (#12141C) sắc nét & không bị mờ */
    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
        background-color: #12141C !important;
        min-width: 320px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        background-color: #12141C !important;
        padding-left: 1.65rem !important;
        padding-right: 1.25rem !important;
        padding-top: 1.25rem !important;
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
    
    /* Thẻ Chỉ số Điều hành (Executive KPI Cards) - Tỷ lệ tiêu chuẩn & Thẩm mỹ hài hòa */
    div[data-testid="stMetric"] {
        background-color: #13172B !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        padding: 12px 14px !important;
        border-radius: 14px !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3) !important;
        transition: all 0.2s ease-in-out;
        min-width: 0 !important;
        overflow: hidden !important;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #00F0FF !important;
        box-shadow: 0 6px 20px rgba(0, 240, 255, 0.25) !important;
        transform: translateY(-1px);
    }
    div[data-testid="stMetricLabel"] {
        font-size: clamp(0.7rem, 0.88vw, 0.74rem) !important;
        font-weight: 700 !important;
        color: #CBD5E1 !important;
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
        color: #CBD5E1 !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: clamp(1.15rem, 1.4vw, 1.35rem) !important;
        font-weight: 800 !important;
        color: #FFFFFF !important;
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
        color: #FFFFFF !important;
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
        font-weight: 700 !important;
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
        background: linear-gradient(135deg, #0052D4 0%, #0068FF 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.25) !important;
        color: #FFFFFF !important;
        box-shadow: 0 4px 14px rgba(0, 104, 255, 0.35) !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #0068FF 0%, #00F0FF 100%) !important;
        color: #090D1A !important;
        box-shadow: 0 6px 20px rgba(0, 240, 255, 0.45) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button[kind="secondary"] {
        background-color: #181D2F !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        color: #FFFFFF !important;
    }
    .stButton > button[kind="secondary"]:hover {
        border-color: #00F0FF !important;
        background-color: #222942 !important;
        color: #00F0FF !important;
        box-shadow: 0 4px 14px rgba(0, 240, 255, 0.25) !important;
        transform: translateY(-1px) !important;
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
        background: rgba(0, 223, 143, 0.15);
        color: #00DF8F;
        border: 1px solid #00DF8F;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        margin-bottom: 10px;
        box-shadow: 0 0 10px rgba(0, 223, 143, 0.2);
    }
    .hero-badge-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #00DF8F;
        box-shadow: 0 0 0 2px rgba(0, 223, 143, 0.35);
    }
    .hero-title {
        font-size: 2.35rem;
        font-weight: 900;
        color: #FFFFFF !important;
        letter-spacing: -0.035em;
        line-height: 1.2;
        margin-bottom: 6px;
    }
    .hero-subtitle {
        font-size: 1.05rem;
        color: #CBD5E1 !important;
        line-height: 1.5;
        max-width: 640px;
        margin: 0 auto 18px auto;
        font-weight: 500;
    }

    /* 3 Thẻ Trạng thái Hệ thống Live Snapshot - Trực quan, Tin cậy, Riêng tư */
    .micro-trust-ribbon {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        margin: 4px auto 26px auto;
        font-size: 0.8rem;
        color: #CBD5E1;
        font-weight: 600;
    }
    .micro-trust-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #151A30;
        border: 1px solid rgba(255, 255, 255, 0.12);
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.76rem;
        color: #E2E8F0;
        transition: all 0.2s ease;
    }
    .micro-trust-pill:hover {
        background: #1D2440;
        border-color: #00F0FF;
        color: #00F0FF;
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
        color: #CBD5E1;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .health-badge {
        font-size: 0.72rem;
        font-weight: 700;
        padding: 2px 9px;
        border-radius: 9999px;
        white-space: nowrap;
    }
    .health-badge-green {
        background: rgba(0, 223, 143, 0.15);
        color: #00DF8F;
        border: 1px solid #00DF8F;
    }
    .health-badge-blue {
        background: rgba(0, 104, 255, 0.15);
        color: #38BDF8;
        border: 1px solid #38BDF8;
    }
    .health-badge-purple {
        background: rgba(121, 40, 202, 0.2);
        color: #C084FC;
        border: 1px solid #C084FC;
    }
    .health-card-value {
        font-size: 1.15rem;
        font-weight: 800;
        color: #FFFFFF !important;
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

    /* Trục Tìm kiếm Trung tâm Hero Search - Tỷ lệ Chuẩn Claude & Gemini (860px) */
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
        border-radius: 16px !important;
        background-color: #151A30 !important;
        border: 1.5px solid rgba(0, 240, 255, 0.32) !important;
        box-shadow: 0 6px 24px -2px rgba(0, 0, 0, 0.55), 0 0 16px rgba(0, 240, 255, 0.08) !important;
        transition: all 0.25s ease !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"]:hover,
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"]:hover {
        border-color: #00F0FF !important;
        box-shadow: 0 8px 28px -2px rgba(0, 0, 0, 0.6), 0 0 20px rgba(0, 240, 255, 0.2) !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
    form[data-testid="stForm"] div[data-testid="stTextInput"] div[data-baseweb="base-input"]:focus-within {
        border-color: #00F0FF !important;
        box-shadow: 0 0 0 3px rgba(0, 240, 255, 0.25), 0 10px 32px -4px rgba(0, 240, 255, 0.35) !important;
    }
    form[data-testid="stForm"] div[data-testid="stTextInput"] input {
        height: 52px !important;
        min-height: 52px !important;
        border-radius: 16px !important;
        background-color: transparent !important;
        border: none !important;
        font-size: 1.02rem !important;
        padding: 0 20px !important;
        color: #FFFFFF !important;
        box-shadow: none !important;
    }
    form[data-testid="stForm"] .stButton > button {
        height: 52px !important;
        min-height: 52px !important;
        border-radius: 16px !important;
        font-size: 0.98rem !important;
        font-weight: 700 !important;
        background: linear-gradient(135deg, #0052D4 0%, #0068FF 60%, #00F0FF 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        color: #FFFFFF !important;
        white-space: nowrap !important;
        box-shadow: 0 4px 18px rgba(0, 104, 255, 0.4) !important;
        transition: all 0.2s ease !important;
    }
    form[data-testid="stForm"] .stButton > button:hover {
        background: linear-gradient(135deg, #0068FF 0%, #00F0FF 100%) !important;
        color: #090D1A !important;
        box-shadow: 0 6px 24px rgba(0, 240, 255, 0.6) !important;
        transform: translateY(-2px) !important;
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
        font-size: 0.9rem;
        font-weight: 700;
        color: #FFFFFF !important;
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
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 8px 8px 0 0;
        font-size: 0.88rem;
        font-weight: 600;
        color: #CBD5E1 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #00F0FF !important;
        border-bottom: 2px solid #00F0FF !important;
    }

    /* Thẻ Gợi Ý Hành Động (Prompt Action Cards) - Hover lift & 1-Chạm mượt mà */
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        border: 1px solid rgba(0, 240, 255, 0.25) !important;
        background: #151A30 !important;
        padding: 14px 16px !important;
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25) !important;
        min-height: 142px !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: #00F0FF !important;
        box-shadow: 0 6px 20px rgba(0, 240, 255, 0.2) !important;
        transform: translateY(-2px);
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button {
        min-height: 38px !important;
        height: 38px !important;
        font-size: 0.84rem !important;
        font-weight: 600 !important;
        border-radius: 9px !important;
        background-color: #1E253E !important;
        border: 1px solid rgba(0, 240, 255, 0.35) !important;
        color: #00F0FF !important;
        white-space: nowrap !important;
    }
    div[data-testid="stTabsContent"] div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover {
        background-color: #00F0FF !important;
        color: #0B0E17 !important;
        border-color: #00F0FF !important;
        box-shadow: 0 2px 10px rgba(0, 240, 255, 0.35) !important;
    }

    /* ========================================================
       VERAXUS EXCLUSIVE SIGNATURE QUANTUM SPINNER & STATUS CARD
       ======================================================== */
    .veraxus-loading-card, .agent-loading-card {
        display: inline-flex;
        align-items: center;
        gap: 18px;
        padding: 16px 26px;
        background: linear-gradient(135deg, rgba(21, 26, 48, 0.96) 0%, rgba(11, 14, 23, 0.98) 100%) !important;
        border: 1.5px solid rgba(0, 240, 255, 0.45) !important;
        border-radius: 18px !important;
        margin: 16px 0 !important;
        box-shadow: 0 12px 36px rgba(0, 0, 0, 0.65), 0 0 28px rgba(0, 240, 255, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
        backdrop-filter: blur(16px) !important;
        position: relative;
        overflow: hidden;
    }
    .veraxus-loading-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 200%;
        height: 100%;
        background: linear-gradient(90deg, transparent 0%, rgba(0, 240, 255, 0.1) 50%, transparent 100%);
        animation: vx-shimmer-sweep 2.5s infinite linear;
        pointer-events: none;
    }
    @keyframes vx-shimmer-sweep {
        0% { transform: translateX(-50%); }
        100% { transform: translateX(50%); }
    }
    .veraxus-spinner-wrapper {
        position: relative;
        width: 48px;
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    .vx-ambient-glow {
        position: absolute;
        width: 36px;
        height: 36px;
        background: radial-gradient(circle, rgba(0, 240, 255, 0.5) 0%, rgba(0, 104, 255, 0.25) 60%, transparent 80%);
        border-radius: 50%;
        filter: blur(6px);
        animation: vx-pulse-ambient 1.8s ease-in-out infinite;
    }
    .vx-ring-outer {
        position: absolute;
        inset: 0;
        width: 48px;
        height: 48px;
        border-radius: 50%;
        border: 2.5px solid transparent;
        border-top: 2.5px solid #00F0FF;
        border-right: 2.5px solid #00DF8F;
        box-shadow: 0 0 14px rgba(0, 240, 255, 0.65), inset 0 0 8px rgba(0, 240, 255, 0.35);
        animation: vx-spin-cw 0.85s linear infinite;
    }
    .vx-ring-inner {
        position: absolute;
        inset: 6px;
        width: 36px;
        height: 36px;
        border-radius: 50%;
        border: 1.5px dashed rgba(0, 240, 255, 0.35);
        border-left: 2px solid #38BDF8;
        border-bottom: 2px solid #0068FF;
        animation: vx-spin-ccw 1.5s cubic-bezier(0.4, 0, 0.2, 1) infinite;
    }
    .vx-crystal-core {
        position: relative;
        z-index: 3;
        display: flex;
        align-items: center;
        justify-content: center;
        animation: vx-crystal-float 1.6s ease-in-out infinite;
    }
    .vx-crystal-svg {
        filter: drop-shadow(0 0 6px rgba(0, 240, 255, 0.85));
    }
    .veraxus-spinner-text-wrap {
        display: flex;
        flex-direction: column;
        gap: 5px;
        z-index: 2;
    }
    .veraxus-spinner-brand {
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        background: linear-gradient(135deg, #00F0FF 0%, #00DF8F 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1;
    }
    .vx-live-pulse-dot {
        display: inline-block;
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #00DF8F;
        box-shadow: 0 0 10px #00DF8F, 0 0 4px #00DF8F;
        animation: vx-live-dot-pulse 1.2s ease-in-out infinite;
    }
    .veraxus-spinner-status, .agent-spinner-text {
        color: #FFFFFF !important;
        font-weight: 600;
        font-size: 0.95rem;
        letter-spacing: -0.01em;
        line-height: 1.4;
        text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
    }
    @keyframes vx-spin-cw {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    @keyframes vx-spin-ccw {
        0% { transform: rotate(360deg); }
        100% { transform: rotate(0deg); }
    }
    @keyframes vx-crystal-float {
        0%, 100% { transform: scale(0.96) translateY(0); filter: drop-shadow(0 0 6px rgba(0, 240, 255, 0.7)); }
        50% { transform: scale(1.1) translateY(-1px); filter: drop-shadow(0 0 12px rgba(0, 240, 255, 1)) drop-shadow(0 0 4px #00DF8F); }
    }
    @keyframes vx-pulse-ambient {
        0%, 100% { transform: scale(0.85); opacity: 0.4; }
        50% { transform: scale(1.15); opacity: 0.8; }
    }
    @keyframes vx-live-dot-pulse {
        0%, 100% { transform: scale(0.9); opacity: 0.7; box-shadow: 0 0 6px #00DF8F; }
        50% { transform: scale(1.35); opacity: 1; box-shadow: 0 0 12px #00DF8F, 0 0 20px #00DF8F; }
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
                            f"### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính\n{_sec['anomaly']}\n\n"
                            f"### 2.2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng\n{_sec['hypothesis']}\n\n"
                            f"### 2.3. 🎯 Kế hoạch Hành động & Đề xuất Ưu tiên\n{_sec['action_plan']}"
                        )
                else:
                    _ins = _turn.get("insights") or ""
                    if ("Đơn vị/ngạch" in _ins or "cho từng thành viên trong" in _ins) and _turn.get("df") is not None and not _turn["df"].empty:
                        _sec = split_insight_sections("", df=_turn["df"], user_query=_q, is_en=(_turn.get("lang") == "en"))
                        _turn["insights"] = (
                            f"### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính\n{_sec['anomaly']}\n\n"
                            f"### 2.2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng\n{_sec['hypothesis']}\n\n"
                            f"### 2.3. 🎯 Kế hoạch Hành động & Đề xuất Ưu tiên\n{_sec['action_plan']}"
                        )
        except Exception:
            pass
    focused_turn_idx = st.session_state.get("focused_turn_idx", None)
    view_mode = st.session_state.get("view_mode", "chat")

    # Tiếp nhận câu hỏi từ Chat Input hoặc Pending Prompt (từ Thẻ Starter / Gợi ý tiếp nối)
    has_active_conversation = bool(history) or (focused_turn_idx is not None)
    pending_prompt = st.session_state.get("pending_prompt")

    # Chỉ hiển thị chat_input ở chân trang khi ĐÃ CÓ lịch sử trò chuyện hoặc đang ở chế độ Chat
    user_input = None
    if has_active_conversation and view_mode == "chat":
        user_input = st.chat_input(" Ask Veraxus...")
        render_voice_input_button(compact=True)

    prompt_to_run = pending_prompt or user_input

    # Nếu người dùng chọn xem CRM Executive Dashboard và không có prompt mới đang chờ chạy
    if view_mode == "dashboard" and not prompt_to_run:
        render_crm_dashboard()
    elif view_mode == "evolution" and not prompt_to_run:
        from src.ui.evolution_dashboard import render_evolution_dashboard
        render_evolution_dashboard()

    # 4.2 Hiển thị câu hỏi được chọn trực tiếp (Direct Focus View) hoặc toàn bộ hội thoại
    elif focused_turn_idx is not None and 0 <= focused_turn_idx < len(history):
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
            font-size: clamp(2.5rem, 4vw, 3.4rem) !important;
            font-weight: 900 !important;
            color: #FFFFFF !important;
            letter-spacing: -0.03em !important;
            text-shadow: 0 4px 24px rgba(0, 104, 255, 0.45) !important;
        }
        </style>
        """, unsafe_allow_html=True)

        # Hero Header - Chữ Veraxus & Logo Kim Cương Chính Giữa Khung Hình (Chuẩn Claude / Gemini)
        st.markdown(textwrap.dedent(f"""
        <div class="hero-container">
            <div style="display: flex; align-items: center; justify-content: center; gap: 16px; margin: 0 0 4px 0;">
                <svg width="48" height="48" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" style="filter: drop-shadow(0 8px 22px rgba(0, 104, 255, 0.45)); flex-shrink: 0;">
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
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#00F0FF" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:6px;"><circle cx="12" cy="12" r="10"></circle><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon></svg>
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

    if prompt_to_run:
        # Xóa pending prompt và reset focus view, chuyển về chế độ chat
        st.session_state["pending_prompt"] = None
        st.session_state["focused_turn_idx"] = None
        st.session_state["view_mode"] = "chat"

        cache_key = prompt_to_run.strip().lower()
        cached = st.session_state.get("query_cache", {}).get(cache_key)

        # Nếu là câu hỏi giao tiếp phi dữ liệu hoặc cache cũ vô tình dính df/sql, bỏ qua cache cũ
        if is_non_data_conversational(prompt_to_run) or (cached and is_non_data_conversational(cached.get("query", "")) and cached.get("df") is not None):
            cached = None

        if st.session_state.get("enable_cache", True) and cached and not cached.get("error"):
            result = cached
        else:
            st.chat_message("user").write(_format_user_chat_display(prompt_to_run))
            with st.chat_message("assistant"):
                status_placeholder = st.empty()
                def update_status(text: str):
                    status_placeholder.markdown(
                        render_veraxus_loading_html(text),
                        unsafe_allow_html=True
                    )

                active_lang = get_current_language()
                loading_msg = "Analyzing business data & executing query..." if active_lang == "en" else "Đang phân tích câu hỏi & đối chiếu dữ liệu doanh nghiệp..."
                update_status(loading_msg)
                current_engine = st.session_state.get("engine")
                current_schema = st.session_state.get("schema_context", "")
                if current_engine and (not current_schema or not current_schema.strip()):
                    current_schema = auto_extract_schema(current_engine)
                    st.session_state["schema_context"] = current_schema

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
                )
                status_placeholder.empty()
                if not result.get("error"):
                    st.session_state.setdefault("query_cache", {})[cache_key] = result

        st.session_state["history"].append(result)
        st.rerun()
