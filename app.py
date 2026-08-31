"""
Veraxus for SQL - Streamlit Application Entry Point.
Featuring standalone Onboarding, interactive Explorer Sidebar, direct History Inspection,
Smart Starter Cards (1-Click), and Follow-up Question Suggestions.
"""

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

    /* Sleek buttons */
    .stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.15s ease-in-out !important;
    }
    .stButton > button:hover {
        transform: translateY(-1px) !important;
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

    # 4.3 Hiển thị Thẻ Gợi ý Câu hỏi Nhanh (Starter Cards) khi chưa có tin nhắn nào
    if not history and focused_turn_idx is None:
        st.markdown("### 🚀 Chào mừng bạn đến với Veraxus for SQL!")
        st.caption("Khám phá dữ liệu kinh doanh của bạn bằng cách nhấp vào một câu hỏi gợi ý nhanh dưới đây hoặc gõ câu hỏi của riêng bạn:")
        st.markdown("###")

        engine = st.session_state.get("engine")
        tables = get_table_names(engine)
        starter_cards = generate_starter_prompts(tables)

        col_s1, col_s2 = st.columns(2, gap="medium")
        for idx, card in enumerate(starter_cards):
            target_col = col_s1 if idx % 2 == 0 else col_s2
            with target_col:
                with st.container(border=True):
                    st.markdown(f"**{card['icon']} {card['title']}**")
                    st.caption(card["desc"])
                    if st.button(f"🔍 \"{card['prompt']}\"", key=f"btn_starter_card_{idx}", use_container_width=True):
                        st.session_state["pending_prompt"] = card["prompt"]
                        st.rerun()

    # 4.4 Xử lý gửi câu hỏi (từ Chat Input, Giọng nói Micro hoặc từ nút bấm Starter / Follow-up)
    render_voice_input_button()
    pending_prompt = st.session_state.get("pending_prompt")
    user_input = st.chat_input("Hỏi bất kỳ điều gì về dữ liệu kinh doanh của bạn...")

    prompt_to_run = pending_prompt or user_input

    if prompt_to_run:
        # Xóa pending prompt và reset focus view
        st.session_state["pending_prompt"] = None
        st.session_state["focused_turn_idx"] = None

        st.chat_message("user").write(prompt_to_run)
        with st.chat_message("assistant"):
            cache_key = prompt_to_run.strip().lower()
            cached = st.session_state.get("query_cache", {}).get(cache_key)

            if st.session_state.get("enable_cache", True) and cached and not cached.get("error"):
                st.caption("♻️ Dùng lại kết quả đã hỏi trước đó trong phiên này (tiết kiệm quota API).")
                result = cached
                render_result(result, turn_id=f"new{len(st.session_state['history'])}")
            else:
                with st.spinner("Đang truy vấn & phân tích..."):
                    result = run_agent(
                        user_query=prompt_to_run,
                        client=st.session_state.get("client"),
                        provider=st.session_state.get("provider"),
                        model_name=st.session_state.get("model_name"),
                        engine=st.session_state.get("engine"),
                        schema_context=st.session_state.get("schema_context"),
                        dialect=st.session_state.get("db_dialect", "SQLite"),
                        db_pass=st.session_state.get("_db_pass_for_sanitize", ""),
                        enable_self_check=st.session_state.get("enable_self_check", True),
                        enable_auto_insights=st.session_state.get("enable_auto_insights", True)
                    )
                render_result(result, turn_id=f"new{len(st.session_state['history'])}")
                if not result.get("error"):
                    st.session_state.setdefault("query_cache", {})[cache_key] = result

        st.session_state["history"].append(result)
        st.rerun()
