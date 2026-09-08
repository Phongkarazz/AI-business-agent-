"""
Veraxus for SQL - Streamlit Application Entry Point.
Featuring standalone Onboarding, interactive Explorer Sidebar, direct History Inspection,
Smart Starter Cards (1-Click), and Follow-up Question Suggestions.
"""

import re
import sys
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
from src.ui.components import render_result, render_voice_input_button
from src.llm.agent import run_agent

# ---------------------------------------------------------
# 1. Cấu hình Trang Streamlit & Custom CSS Giao Diện Doanh Nghiệp
# ---------------------------------------------------------
st.set_page_config(
    page_title="Veraxus for SQL",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    
    /* Ẩn triệt để thanh Chrome thừa mặc định của Streamlit */
    #MainMenu {visibility: hidden; display: none !important;}
    footer {visibility: hidden; display: none !important;}
    .stDeployButton {display: none !important;}
    div[data-testid="stDecoration"] {display: none !important;}
    div[data-testid="stToolbar"] {display: none !important;}
    div[data-testid="stStatusWidget"] {display: none !important;}
    header {background-color: transparent !important;}
    header [data-testid="stToolbarActions"] {display: none !important;}

    /* Tối ưu khoảng đệm trên cùng của trang để nội dung hiển thị ngay trong tầm mắt */
    .block-container {
        padding-top: 1.25rem !important;
        padding-bottom: 2.5rem !important;
    }
    
    /* Modern KPI Cards */
    div[data-testid="stMetric"] {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        padding: 14px 18px;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        transition: all 0.2s ease-in-out;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #CBD5E1;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
        transform: translateY(-1px);
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        color: #64748B !important;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.45rem !important;
        font-weight: 700 !important;
        color: #0F172A !important;
    }

    /* Sleek, readable buttons */
    .stButton > button {
        border-radius: 10px !important;
        font-weight: 500 !important;
        font-size: 0.88rem !important;
        line-height: 1.45 !important;
        letter-spacing: 0.015em !important;
        padding: 10px 14px !important;
        min-height: 56px !important;
        height: auto !important;
        transition: all 0.15s ease-in-out !important;
        white-space: normal !important;
        word-break: break-word !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
    }
    .stButton > button p {
        font-size: 0.88rem !important;
        font-weight: 500 !important;
        line-height: 1.45 !important;
        letter-spacing: 0.015em !important;
        margin: 0 !important;
    }
    .stButton > button:hover {
        border-color: #2563EB !important;
        background-color: #F8FAFC !important;
        color: #1E40AF !important;
        box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08) !important;
        transform: translateY(-1px) !important;
    }

    /* Hero Section & Database Live Snapshot */
    .hero-container {
        text-align: center;
        padding: 20px 10px 6px 10px;
        max-width: 860px;
        margin: 0 auto;
    }
    .hero-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
        border: 1px solid #BFDBFE;
        color: #1E40AF;
        font-size: 0.82rem;
        font-weight: 600;
        padding: 5px 14px;
        border-radius: 9999px;
        letter-spacing: 0.02em;
        margin-bottom: 12px;
    }
    .hero-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #0F172A;
        letter-spacing: -0.025em;
        line-height: 1.25;
        margin-bottom: 8px;
    }
    .hero-subtitle {
        font-size: 0.98rem;
        color: #64748B;
        line-height: 1.5;
        max-width: 660px;
        margin: 0 auto 18px auto;
    }
    .snapshot-bar {
        display: flex;
        justify-content: center;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 24px;
    }
    .snapshot-pill {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 6px 14px;
        font-size: 0.84rem;
        color: #334155;
        font-weight: 500;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        transition: all 0.2s ease;
    }
    .snapshot-pill:hover {
        border-color: #CBD5E1;
        background: #FFFFFF;
        box-shadow: 0 3px 8px rgba(0,0,0,0.05);
        transform: translateY(-1px);
    }
    .snapshot-pill b {
        color: #0F172A;
        font-weight: 700;
    }

    /* Agent Loading Spinner */
    .agent-loading-card {
        display: inline-flex;
        align-items: center;
        gap: 12px;
        padding: 12px 20px;
        background: linear-gradient(135deg, #EFF6FF 0%, #F8FAFC 100%);
        border: 1.5px solid #BFDBFE;
        border-radius: 12px;
        margin: 8px 0;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
    }
    .agent-spinner {
        width: 20px;
        height: 20px;
        border: 2.5px solid #DBEAFE;
        border-top: 2.5px solid #2563EB;
        border-radius: 50%;
        animation: agent-spin 0.8s linear infinite;
        flex-shrink: 0;
    }
    .agent-spinner-text {
        color: #1E40AF;
        font-weight: 600;
        font-size: 0.94rem;
        letter-spacing: -0.01em;
    }
    @keyframes agent-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    /* Quick Action Chip Buttons & Central Search */
    .quick-chip-container .stButton > button {
        border-radius: 9999px !important;
        min-height: 44px !important;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
        background-color: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        color: #1E293B !important;
        padding: 8px 16px !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03) !important;
    }
    .quick-chip-container .stButton > button:hover {
        border-color: #2563EB !important;
        background-color: #EFF6FF !important;
        color: #1D4ED8 !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1) !important;
        transform: translateY(-1px) !important;
    }
    .center-search-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 16px;
        padding: 16px 20px 12px 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
        margin-bottom: 18px;
    }

    /* 3 Live Data Health KPI Cards */
    .data-health-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
        margin-bottom: 18px;
    }
    @media (max-width: 768px) {
        .data-health-grid {
            grid-template-columns: 1fr;
        }
    }
    .health-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 13px 16px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        transition: all 0.2s ease-in-out;
        text-align: left;
    }
    .health-card:hover {
        border-color: #CBD5E1;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        transform: translateY(-1px);
    }
    .health-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
    }
    .health-card-title {
        font-size: 0.74rem;
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
        padding: 2px 8px;
        border-radius: 9999px;
    }
    .health-badge-green {
        background: #F0FDF4;
        color: #166534;
        border: 1px solid #BBF7D0;
    }
    .health-badge-blue {
        background: #EFF6FF;
        color: #1D4ED8;
        border: 1px solid #BFDBFE;
    }
    .health-badge-purple {
        background: #FAF5FF;
        color: #6B21A8;
        border: 1px solid #E9D5FF;
    }
    .health-card-value {
        font-size: 1.15rem;
        font-weight: 800;
        color: #0F172A;
        line-height: 1.25;
        margin-bottom: 3px;
        letter-spacing: -0.01em;
    }
    .health-card-sub {
        font-size: 0.78rem;
        color: #64748B;
        line-height: 1.35;
    }

    /* Categorized Prompt Tabs Styling */
    .prompt-tab-intro {
        margin-top: 14px;
        margin-bottom: 8px;
        font-size: 0.85rem;
        font-weight: 600;
        color: #475569;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        margin-bottom: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 6px 14px;
        border-radius: 8px;
        font-size: 0.86rem;
        font-weight: 600;
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
                    selected_model=saved.get("model_name", "deepseek/deepseek-chat"),
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

    history = st.session_state.get("history", [])
    focused_turn_idx = st.session_state.get("focused_turn_idx", None)

    # Tiếp nhận câu hỏi từ Chat Input hoặc Pending Prompt (từ Thẻ Starter / Gợi ý tiếp nối)
    has_active_conversation = bool(history) or (focused_turn_idx is not None)
    pending_prompt = st.session_state.get("pending_prompt")

    # Chỉ hiển thị chat_input ở chân trang khi ĐÃ CÓ lịch sử trò chuyện (tránh trùng lặp với Hero Search)
    user_input = None
    if has_active_conversation:
        user_input = st.chat_input("Hỏi bất kỳ điều gì về dữ liệu kinh doanh của bạn...")

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
            clean_model = "Gemini 2.0 Flash"
        elif "claude" in model_disp.lower():
            clean_model = "Claude 3.5 Sonnet"

        # Scale metrics
        if is_emp:
            scale_val = f"{len(tables)} Bảng • 300,000+ Hồ sơ"
            scale_sub = "Quan hệ N-N: Lương, Phòng ban, Chức danh"
        elif is_choc:
            scale_val = f"{len(tables)} Bảng • Đơn hàng Bán lẻ"
            scale_sub = "Doanh thu, Chi phí, Đội ngũ, Sản phẩm"
        else:
            scale_val = f"{len(tables)} Bảng Cơ Sở Dữ Liệu"
            scale_sub = "Sẵn sàng truy vấn và tổng hợp dữ liệu"

        # Security & engine
        if is_demo:
            sec_val = "SQLite In-Memory"
            sec_badge = "🟢 Sẵn sàng"
            sec_sub = "Độ trễ < 5ms • 100% Cục bộ Offline"
        else:
            sec_val = "MySQL Enterprise"
            sec_badge = "🟢 Live"
            sec_sub = "Độ trễ < 15ms • Zero Data Leakage"

        prov_clean = provider_name.split()[0]

        # Hero Header
        st.markdown("""
        <div class="hero-container" style="padding: 8px 10px 14px 10px;">
            <div class="hero-title" style="font-size: 2.25rem; font-weight: 800; color: #0F172A; margin-bottom: 6px; letter-spacing: -0.025em;">
                VERAXUS AI
            </div>
            <div class="hero-subtitle" style="font-size: 1.02rem; color: #64748B; margin-bottom: 12px;">
                Trợ lý Điều hành & Phân tích Dữ liệu Kinh doanh Độc lập
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_c_l, col_c_mid, col_c_r = st.columns([1, 8, 1])
        with col_c_mid:
            # 3 Thẻ Sức Khỏe Dữ Liệu Live Snapshot
            st.markdown(f"""
            <div class="data-health-grid">
                <div class="health-card">
                    <div class="health-card-header">
                        <span class="health-card-title">🗄️ QUY MÔ DỮ LIỆU</span>
                        <span class="health-badge health-badge-blue">Ready</span>
                    </div>
                    <div class="health-card-value">{scale_val}</div>
                    <div class="health-card-sub">{scale_sub}</div>
                </div>
                <div class="health-card">
                    <div class="health-card-header">
                        <span class="health-card-title">🛡️ ĐỘ TIN CẬY & AN TOÀN</span>
                        <span class="health-badge health-badge-green">{sec_badge}</span>
                    </div>
                    <div class="health-card-value">{sec_val}</div>
                    <div class="health-card-sub">{sec_sub}</div>
                </div>
                <div class="health-card">
                    <div class="health-card-header">
                        <span class="health-card-title">🧠 TRÍ TUỆ NHÂN TẠO</span>
                        <span class="health-badge health-badge-purple">{prov_clean}</span>
                    </div>
                    <div class="health-card-value">{clean_model}</div>
                    <div class="health-card-sub">Schema Injected • Tự sửa lỗi 3 chu kỳ</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Trục tương tác chính: Thanh Tìm kiếm Lớn tại Trung tâm
            with st.container():
                st.markdown('<div class="center-search-card">', unsafe_allow_html=True)
                with st.form(key="center_hero_search_form", clear_on_submit=True, border=False):
                    c_in, c_btn = st.columns([5.8, 1.2])
                    with c_in:
                        hero_query = st.text_input(
                            "Search",
                            placeholder="🔍 Hỏi bất kỳ điều gì về doanh thu, chi phí, P&L, nhân sự...",
                            label_visibility="collapsed",
                            key="hero_search_input"
                        )
                    with c_btn:
                        hero_submit = st.form_submit_button("Hỏi AI ↗", type="primary", use_container_width=True)
                    if hero_submit and hero_query.strip():
                        st.session_state["pending_prompt"] = hero_query.strip()
                        st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

            # Khám phá câu hỏi theo 3 lăng kính điều hành (Categorized Smart Prompts Tabs)
            categorized = generate_categorized_starter_prompts(tables, schema_context)
            cat_keys = list(categorized.keys())

            st.markdown("""
            <div class="prompt-tab-intro">
                <span>🎯</span> <span><b>Khám phá nhanh theo lăng kính điều hành:</b></span>
            </div>
            """, unsafe_allow_html=True)

            prompt_tabs = st.tabs(cat_keys)
            for tab_idx, cat_name in enumerate(cat_keys):
                with prompt_tabs[tab_idx]:
                    card_list = categorized[cat_name]
                    cols = st.columns(len(card_list), gap="small")
                    for card_idx, card in enumerate(card_list):
                        with cols[card_idx]:
                            with st.container(border=True):
                                st.markdown(f"""
                                <div style="font-size: 0.92rem; font-weight: 700; color: #0F172A; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                                    <span>{card['icon']}</span> <span>{card['title']}</span>
                                </div>
                                <div style="font-size: 0.8rem; color: #64748B; min-height: 42px; line-height: 1.4; margin-bottom: 8px;">
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

            st.markdown("<div style='margin-top: 18px; display: flex; justify-content: center;'>", unsafe_allow_html=True)
            render_voice_input_button()
            st.markdown("</div>", unsafe_allow_html=True)
    elif not prompt_to_run:
        render_voice_input_button()


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
                        f"""
                        <div class="agent-loading-card">
                            <div class="agent-spinner"></div>
                            <span class="agent-spinner-text">{text}</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                update_status("🤖 Đang phân tích câu hỏi & tạo câu lệnh SQL tối ưu...")
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
