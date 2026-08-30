"""
Universal AI Business Agent - Streamlit Application Entry Point.
Featuring standalone Onboarding screen, top-right Settings navigation, and multi-turn chat analysis.
"""

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.config_store import load_saved_config
from src.ui.state import init_session_state
from src.ui.onboarding import render_onboarding
from src.ui.sidebar import perform_connection
from src.ui.components import render_result
from src.llm.agent import run_agent

# ---------------------------------------------------------
# 1. Cấu hình Trang Streamlit
# ---------------------------------------------------------
st.set_page_config(
    page_title="Universal AI Business Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# 2. Khởi tạo Session State
# ---------------------------------------------------------
init_session_state()

# ---------------------------------------------------------
# 3. Tự động Kết nối (Auto-Connect on Startup)
# ---------------------------------------------------------
if not st.session_state.get("connected") and not st.session_state.get("_auto_connect_attempted", False):
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

# ---------------------------------------------------------
# 4. Điều hướng Giao diện (Routing)
# ---------------------------------------------------------
# Nếu chưa kết nối hoặc người dùng bấm "Cài đặt": Hiển thị màn hình Onboarding / Settings
if not st.session_state.get("connected") or st.session_state.get("view_mode") == "settings":
    render_onboarding()

# Nếu đã kết nối: Hiển thị Màn hình Chat & Phân tích chính
else:
    # Top Header Bar với nút Cài đặt ở góc trên bên phải
    col_header, col_settings = st.columns([5, 1])

    with col_header:
        db_badge = "🎮 SQLite Demo (Chocolate 2023)" if st.session_state.get("is_demo") else "🔌 MySQL Database"
        ai_badge = f"🤖 {st.session_state.get('provider')} ({st.session_state.get('model_name')})"
        st.markdown(f"### 🤖 AI Business Agent for SQL &nbsp; <small style='font-size:14px; color:#22c55e;'>🟢 {db_badge} &nbsp;|&nbsp; {ai_badge}</small>", unsafe_allow_html=True)
        st.caption("Trò chuyện bằng ngôn ngữ tự nhiên để truy vấn SQL, tự phát hiện Insight kinh doanh, vẽ biểu đồ và dự báo xu hướng.")

    with col_settings:
        st.write("")
        if st.button("⚙️ Cài đặt", type="secondary", use_container_width=True, help="Thay đổi kết nối Database, AI Provider hoặc tùy chỉnh tham số"):
            st.session_state["view_mode"] = "settings"
            st.rerun()

    st.markdown("---")

    # Hiển thị lịch sử hội thoại
    for i, turn in enumerate(st.session_state["history"]):
        st.chat_message("user").write(turn["query"])
        with st.chat_message("assistant"):
            render_result(turn, turn_id=f"hist{i}")

    # Gợi ý câu hỏi khi dùng demo
    if st.session_state.get("is_demo") and not st.session_state["history"]:
        st.info("💡 **Gợi ý câu hỏi:** *\"Doanh số theo từng tháng năm 2023\"*, *\"Top 5 nhân viên bán chạy nhất\"*, *\"Sản phẩm nào mang lại doanh thu cao nhất?\"*")

    # Khung nhập câu hỏi
    user_input = st.chat_input("Hỏi bất kỳ điều gì về dữ liệu kinh doanh của bạn...")
    if user_input:
        st.chat_message("user").write(user_input)
        with st.chat_message("assistant"):
            cache_key = user_input.strip().lower()
            cached = st.session_state.get("query_cache", {}).get(cache_key)

            if st.session_state.get("enable_cache", True) and cached and not cached.get("error"):
                st.caption("♻️ Dùng lại kết quả đã hỏi trước đó trong phiên này (tiết kiệm quota API).")
                result = cached
                render_result(result, turn_id=f"new{len(st.session_state['history'])}")
            else:
                with st.spinner("Đang truy vấn & phân tích..."):
                    result = run_agent(
                        user_query=user_input,
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
