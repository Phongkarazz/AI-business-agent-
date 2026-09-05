"""
Veraxus for SQL - Streamlit Application Entry Point.
Featuring standalone Onboarding, interactive Explorer Sidebar, direct History Inspection,
Smart Starter Cards (1-Click), and Follow-up Question Suggestions.
"""

import re
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.config_store import load_saved_config
from src.database.schema import get_table_names
from src.analytics.heuristics import generate_starter_prompts
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
        db_host = saved.get("db_host", "")
        db_user = saved.get("db_user", "")
        db_name = saved.get("db_name", "")

        can_connect = clean_api_key and (use_demo or bool(db_host and db_user and db_name))

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
                    use_ssl=saved.get("use_ssl", False),
                    run_local=saved.get("run_local", False),
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
    pending_prompt = st.session_state.get("pending_prompt")
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
            render_result(turn, turn_id=f"focused_{focused_turn_idx}")
    else:
        # Hiển thị toàn bộ lịch sử hội thoại
        for i, turn in enumerate(history):
            st.chat_message("user").write(turn["query"])
            with st.chat_message("assistant"):
                render_result(turn, turn_id=f"hist{i}")

    # 4.3 Hiển thị Thẻ Gợi ý Câu hỏi Nhanh (Starter Cards) khi chưa có tin nhắn nào VÀ không có câu hỏi đang chạy
    if not history and focused_turn_idx is None and not prompt_to_run:
        st.markdown("""
        <div class="hero-container">
            <div class="hero-badge">
                ✨ Trợ Lý Phân Tích Dữ Liệu Doanh Nghiệp • Text-to-SQL Agent
            </div>
            <div class="hero-title">
                Khám Phá Dữ Liệu Doanh Nghiệp
            </div>
            <div class="hero-subtitle">
                Đặt câu hỏi tự nhiên bằng tiếng Việt — AI sẽ tự động lập trình SQL tối ưu, truy xuất dữ liệu tức thời, vẽ biểu đồ trực quan và phát hiện Insight quản trị.
            </div>
        </div>
        """, unsafe_allow_html=True)

        engine = st.session_state.get("engine")
        tables = get_table_names(engine)
        schema_context = st.session_state.get("schema_context", "")
        provider_name = str(st.session_state.get("provider", "Ollama"))
        model_disp = str(st.session_state.get("model_name", "qwen2.5-coder:3b"))

        tbl_low = [t.lower() for t in tables]
        is_emp = "employees" in tbl_low and "departments" in tbl_low

        pill1 = "👥 <b>300,024</b> Nhân sự" if is_emp else f"📋 <b>{len(tables)}</b> Bảng CSDL"
        pill2 = "🏢 <b>9</b> Phòng ban" if is_emp else "⚡ <b>MySQL</b> Kết nối an toàn"
        pill3 = "📅 <b>18 Năm</b> Dữ liệu (1985–2002)" if is_emp else "🛡️ <b>Chế độ Chỉ đọc</b> Bảo mật"
        pill4 = f"🤖 <b>Local AI</b> ({model_disp})" if "ollama" in provider_name.lower() else f"🤖 <b>AI</b> ({model_disp})"

        st.markdown(f"""
        <div class="snapshot-bar">
            <div class="snapshot-pill">{pill1}</div>
            <div class="snapshot-pill">{pill2}</div>
            <div class="snapshot-pill">{pill3}</div>
            <div class="snapshot-pill">{pill4}</div>
        </div>
        """, unsafe_allow_html=True)

        starter_cards = generate_starter_prompts(tables, schema_context)
        cards_to_show = starter_cards[:4]

        # Category mapping for badges
        category_map = {
            "⚖️": "Công Bằng Thu Nhập",
            "💰": "Khối Kinh Doanh",
            "📅": "Quy Mô Tuyển Dụng",
            "🚻": "Đa Dạng Giới Tính",
            "🏢": "Nội Bộ Phòng Ban",
            "👔": "Hồ Sơ Lãnh Đạo",
            "📦": "Danh Mục Sản Phẩm",
            "🏆": "Hiệu Suất Bán Hàng",
            "🌍": "Thị Trường Quốc Tế",
        }

        col_s1, col_s2 = st.columns(2, gap="medium")
        for idx, card in enumerate(cards_to_show):
            target_col = col_s1 if idx % 2 == 0 else col_s2
            with target_col:
                with st.container(border=True):
                    tag_name = category_map.get(card.get("icon", ""), "Phân Tích")
                    c_tag1, c_tag2 = st.columns([3, 1])
                    with c_tag1:
                        st.markdown(
                            f"<span style='background: #F1F5F9; color: #475569; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 6px; letter-spacing: 0.04em; text-transform: uppercase;'>"
                            f"{tag_name}</span>",
                            unsafe_allow_html=True
                        )
                    with c_tag2:
                        st.markdown(
                            f"<div style='text-align: right; color: #94A3B8; font-size: 0.75rem; font-weight: 600;'>#{idx+1}</div>",
                            unsafe_allow_html=True
                        )

                    st.markdown(f"<div style='font-size: 1.05rem; font-weight: 700; color: #0F172A; margin: 6px 0 3px 0;'>{card['icon']} {card['title']}</div>", unsafe_allow_html=True)
                    st.caption(card["desc"])

                    st.markdown(
                        f"<div style='background: #F8FAFC; border-left: 3px solid #2563EB; padding: 7px 11px; border-radius: 6px; font-size: 0.83rem; color: #334155; margin: 8px 0 10px 0; font-style: italic; line-height: 1.4;'>"
                        f"“{card['prompt']}”"
                        f"</div>",
                        unsafe_allow_html=True
                    )

                    def _on_starter_click(p_text=card["prompt"]):
                        st.session_state["pending_prompt"] = p_text

                    st.button(
                        "⚡ Khám phá ngay ↗",
                        key=f"btn_starter_card_{idx}",
                        use_container_width=True,
                        type="secondary",
                        on_click=_on_starter_click
                    )

        st.markdown("<div style='margin-top: 14px; margin-bottom: 4px;'>", unsafe_allow_html=True)
        col_v1, col_v2, col_v3 = st.columns([1, 2, 1])
        with col_v2:
            render_voice_input_button()
            st.caption("💡 *Mẹo: Nhấp vào thẻ bất kỳ ở trên, gõ câu hỏi vào khung chat hoặc bấm micro để nói tiếng Việt.*")
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
