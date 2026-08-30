"""
Sidebar UI component for Database and AI configuration.
"""

import streamlit as st
from src.config import (
    PROVIDER_CONFIGS,
    DASHSCOPE_BASE_URL,
    OPENROUTER_BASE_URL,
    LOCAL_HOST_ALIASES,
)
from src.database.connection import try_connect
from src.database.demo_data import build_demo_engine
from src.database.schema import auto_extract_schema
from src.database.query_runner import sanitize_error
from src.llm.client import get_llm_client


def render_sidebar():
    """Hiển thị toàn bộ Sidebar cấu hình kết nối DB và AI."""
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
                    "trên **cùng máy tính** với MySQL (`streamlit run app.py`). Nếu chạy trên Streamlit Cloud, "
                    "server không thể thấy localhost máy bạn — cần dùng Cloud DB hoặc Tunnel (Pinggy/ngrok)."
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
                value=not run_local
            )

            db_host = db_host.strip()
            db_user = db_user.strip()
            db_name = db_name.strip()
            db_port_digits = "".join(ch for ch in db_port_raw if ch.isdigit())
            if db_port_raw.strip() and db_port_digits != db_port_raw.strip():
                st.caption(f"ℹ️ Đã tự động làm sạch Port thành `{db_port_digits}`.")
            db_port = db_port_digits or "3306"
        else:
            db_host = db_port = db_user = db_pass = db_name = ""
            use_ssl = False
            run_local = False
            st.caption("Dữ liệu mẫu: Doanh số chocolate theo tháng, nhân viên, khu vực, sản phẩm (năm 2023).")

        st.subheader("2. Nhà cung cấp AI (Provider)")
        provider = st.selectbox("Provider", list(PROVIDER_CONFIGS.keys()), index=0)
        provider_cfg = PROVIDER_CONFIGS[provider]

        api_key = st.text_input(
            "API Key", type="password",
            help=provider_cfg["key_help"],
            placeholder=provider_cfg["key_placeholder"],
        )
        st.caption(f"💡 {provider_cfg['free_tier_note']}")

        model_options = provider_cfg["models"]
        selected_model = st.selectbox("Model AI", model_options, index=0)

        # Base URL và tuỳ chọn nâng cao
        custom_base_url = ""
        if provider == "OpenRouter":
            custom_base_url = OPENROUTER_BASE_URL
            with st.expander("🔧 Cấu hình nâng cao OpenRouter", expanded=False):
                st.caption("Base URL mặc định cho OpenRouter là `https://openrouter.ai/api/v1`.")
                custom_base_url = st.text_input(
                    "Base URL (OpenRouter)",
                    value=OPENROUTER_BASE_URL,
                    help="Mặc định là https://openrouter.ai/api/v1"
                ).strip() or OPENROUTER_BASE_URL
                custom_model_input = st.text_input(
                    "Hoặc nhập Model ID tùy chỉnh (VD: deepseek/deepseek-r1)",
                    value="",
                    help="Để trống nếu dùng model đã chọn trong danh sách ở trên."
                ).strip()
                if custom_model_input:
                    selected_model = custom_model_input

        elif provider == "Qwen (Alibaba Cloud)":
            custom_base_url = DASHSCOPE_BASE_URL
            with st.expander("🔧 Base URL nâng cao (Qwen)", expanded=False):
                st.caption(
                    "Một số tài khoản Alibaba Cloud mới yêu cầu dùng domain riêng theo workspace. "
                    "Dán URL OpenAI-compatible tại đây nếu cần."
                )
                custom_base_url = st.text_input(
                    "Base URL", value=DASHSCOPE_BASE_URL,
                    help="Mặc định là domain chung dashscope-intl."
                ).strip() or DASHSCOPE_BASE_URL

        with st.expander("⚡ Tối ưu Quota API", expanded=False):
            enable_self_check = st.checkbox(
                "Bật kiểm định SQL bằng AI (self-check)",
                value=True,
                help="Mỗi câu hỏi tốn thêm 1 lượt gọi AI để tự kiểm tra lại SQL. Tắt đi để tiết kiệm ~50% quota."
            )
            enable_cache = st.checkbox(
                "Dùng lại kết quả cho câu hỏi trùng lặp (cache)",
                value=True,
                help="Dùng lại kết quả cũ cho câu hỏi lặp lại trong cùng phiên."
            )

        schema_context_input = st.text_area(
            "Mô tả Schema / Nghiệp vụ (Tự động nạp sau khi bấm Kết nối)",
            value=st.session_state.get("schema_context", ""),
            height=180
        )

        forecast_periods = st.slider("Số kỳ dự báo xu hướng", 1, 12, 3)
        connect_btn = st.button("🔌 Kết nối Database & AI", type="primary", use_container_width=True)

    # Đồng bộ session state
    st.session_state["enable_self_check"] = enable_self_check
    st.session_state["enable_cache"] = enable_cache
    st.session_state["forecast_periods"] = forecast_periods

    if connect_btn:
        if not api_key:
            st.sidebar.error(f"❌ Vui lòng nhập API Key cho {provider}!")
        elif not use_demo and not (db_host and db_user and db_name):
            st.sidebar.error("❌ Vui lòng điền đầy đủ Host, User, Database Name!")
        else:
            try:
                if use_demo:
                    engine = build_demo_engine()
                else:
                    engine = try_connect(
                        db_host, db_port, db_user, db_pass, db_name, use_ssl, run_local=run_local
                    )

                client = get_llm_client(provider, api_key, custom_base_url)
                extracted_schema = auto_extract_schema(engine)
                final_schema = schema_context_input if schema_context_input.strip() else extracted_schema

                st.session_state.update({
                    "engine": engine,
                    "client": client,
                    "provider": provider,
                    "model_name": selected_model,
                    "schema_context": final_schema,
                    "connected": True,
                    "_db_pass_for_sanitize": db_pass,
                    "is_demo": use_demo,
                    "db_dialect": "SQLite" if use_demo else "MySQL",
                })
                st.sidebar.success(f"✅ Kết nối thành công! (AI: {provider} — {selected_model})")
                st.rerun()
            except Exception as e:
                st.session_state["connected"] = False
                err_display = sanitize_error(str(e), db_pass)
                if "429" in err_display or "RESOURCE_EXHAUSTED" in err_display:
                    st.sidebar.error(
                        f"🚫 API Key {provider} hết quota hôm nay. Vui lòng tạo key mới hoặc đổi Provider."
                    )
                elif not use_demo and run_local:
                    st.sidebar.error(
                        f"❌ Không kết nối được tới MySQL local (đã thử: {', '.join(LOCAL_HOST_ALIASES)}).\n\n"
                        f"Lỗi: {err_display}"
                    )
                else:
                    st.sidebar.error(f"❌ Lỗi kết nối: {err_display}")
