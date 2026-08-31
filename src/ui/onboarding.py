"""
Dedicated full-screen Onboarding and Settings Wizard UI component with Loading Dialog.
"""

import streamlit as st
from src.config import (
    PROVIDER_CONFIGS,
    DASHSCOPE_BASE_URL,
    OPENROUTER_BASE_URL,
)
from src.config_store import load_saved_config, save_user_config, clear_saved_config
from src.ui.connection_dialog import show_connecting_dialog


def render_onboarding():
    """Hiển thị màn hình Onboarding / Cài đặt cấu hình độc lập toàn trang."""
    saved = load_saved_config()
    is_already_connected = st.session_state.get("connected", False)

    # Header điều hướng
    col_title, col_back = st.columns([3, 1])
    with col_title:
        if is_already_connected:
            st.title("⚙️ Cài đặt & Cấu hình Kết nối")
            st.caption("Thay đổi nguồn dữ liệu, nhà cung cấp AI hoặc tùy chỉnh các tham số phân tích.")
        else:
            st.title("🗄️ Chào mừng đến với Veraxus for SQL!")
            st.caption("Hãy thiết lập nguồn dữ liệu và nhà cung cấp AI để bắt đầu truy vấn và phân tích dữ liệu kinh doanh.")

    with col_back:
        if is_already_connected:
            st.write("")
            if st.button("← Quay lại Chat", type="secondary", use_container_width=True, key="btn_back_to_chat_top"):
                st.session_state["view_mode"] = "chat"
                st.rerun()

    # Thông báo nếu vừa tự động kết nối thất bại (do đổi link Pinggy/Host/Port)
    auto_err = st.session_state.get("_auto_connect_error")
    if auto_err and not is_already_connected:
        st.warning(
            f"⚠️ **Không thể kết nối Database với cấu hình đã lưu**: `{auto_err}`\n\n"
            "👉 Vui lòng kiểm tra và cập nhật lại **Host**, **Port** hoặc mật khẩu MySQL ở bảng bên dưới rồi bấm **'🚀 Kết nối ngay'**."
        )

    st.markdown("---")

    # Form nhập liệu 2 cột trực quan
    col_left, col_right = st.columns(2, gap="large")

    with col_left:
        st.subheader("1. 🗄️ Nguồn Dữ liệu Database")

        data_mode_options = [
            "🎮 Dùng dữ liệu mẫu (SQLite Demo, không cần MySQL)",
            "🔌 Kết nối MySQL Database của tôi"
        ]
        saved_mode_idx = saved.get("data_mode_index", 0)
        if saved_mode_idx >= len(data_mode_options):
            saved_mode_idx = 0

        data_mode = st.radio(
            "Chọn kiểu dữ liệu",
            data_mode_options,
            index=saved_mode_idx,
            key="onboarding_data_mode",
            help="Dữ liệu mẫu chứa 1,000+ giao dịch kinh doanh chocolate 2023 với nhân viên, sản phẩm, doanh số."
        )
        use_demo = data_mode.startswith("🎮")

        if use_demo:
            st.info("💡 **Dữ liệu mẫu (In-Memory SQLite)**: Đã tích hợp sẵn các bảng `sales`, `products`, `salespersons`, `regions` với dữ liệu doanh số thực tế 2023. Không cần cấu hình gì thêm!")
            db_host = db_port = db_user = db_pass = db_name = ""
            use_ssl = False
            run_local = False
        else:
            run_local = st.checkbox(
                "🖥️ Database chạy trên máy Local (localhost)",
                value=saved.get("run_local", False),
                key="onboarding_run_local",
                help="Tự động điền Host = localhost và thử các alias (127.0.0.1, host.docker.internal)."
            )

            if run_local:
                st.caption("ℹ️ **Lưu ý:** `localhost` chỉ hoạt động khi bạn đang chạy app trên cùng máy tính với MySQL.")
                db_host = st.text_input("Host", value=saved.get("db_host", "localhost") or "localhost", key="onboarding_db_host")
            else:
                default_host = saved.get("db_host", "")
                if default_host in ("localhost", "127.0.0.1"):
                    default_host = ""
                db_host = st.text_input("Host", value=default_host, placeholder="VD: mysql-xxx.aivencloud.com", key="onboarding_db_host")

            c_p1, c_p2 = st.columns([1, 2])
            with c_p1:
                db_port_raw = st.text_input("Port", value=saved.get("db_port", "3306"), key="onboarding_db_port")
            with c_p2:
                db_user = st.text_input("User", value=saved.get("db_user", "root"), key="onboarding_db_user")

            db_pass = st.text_input("Password", value=saved.get("db_pass", ""), type="password", key="onboarding_db_pass")
            db_name = st.text_input("Database Name", value=saved.get("db_name", ""), placeholder="VD: my_company_db", key="onboarding_db_name")
            use_ssl = st.checkbox(
                "Dùng SSL (Bắt buộc với hầu hết MySQL Cloud: Aiven, Railway...)",
                value=saved.get("use_ssl", not run_local),
                key="onboarding_use_ssl"
            )

            db_host = db_host.strip()
            db_user = db_user.strip()
            db_name = db_name.strip()
            db_port_digits = "".join(ch for ch in db_port_raw if ch.isdigit())
            db_port = db_port_digits or "3306"

    with col_right:
        st.subheader("2. 🤖 Nhà cung cấp AI (Provider)")

        provider_list = list(PROVIDER_CONFIGS.keys())
        saved_provider = saved.get("provider", "OpenRouter")
        provider_idx = provider_list.index(saved_provider) if saved_provider in provider_list else 0

        provider = st.selectbox("Chọn Provider AI", provider_list, index=provider_idx, key="onboarding_provider")
        provider_cfg = PROVIDER_CONFIGS[provider]

        # Lấy API Key đã lưu
        if provider == "OpenRouter":
            default_key = saved.get("api_key_openrouter", "")
        elif provider == "Gemini (Google)":
            default_key = saved.get("api_key_gemini", "")
        else:
            default_key = saved.get("api_key_qwen", "")

        api_key = st.text_input(
            f"API Key cho {provider}",
            value=default_key,
            type="password",
            help=provider_cfg["key_help"],
            placeholder=provider_cfg["key_placeholder"],
            key="onboarding_api_key"
        )

        clean_api_key = api_key.strip()
        is_openrouter_key = clean_api_key.startswith("sk-or-v1-")

        if is_openrouter_key and provider != "OpenRouter":
            st.info("💡 Phát hiện API Key của **OpenRouter**. Hệ thống sẽ tự động định tuyến qua OpenRouter Base URL (`https://openrouter.ai/api/v1`).")

        model_options = provider_cfg["models"]
        saved_model = saved.get("model_name", "")
        model_idx = model_options.index(saved_model) if saved_model in model_options else 0
        selected_model = st.selectbox("Chọn Model AI", model_options, index=model_idx, key="onboarding_model")

        custom_base_url = ""
        custom_model_input = ""
        if provider == "OpenRouter" or is_openrouter_key:
            with st.expander("🔧 Cấu hình nâng cao OpenRouter", expanded=False):
                custom_base_url = st.text_input(
                    "Base URL",
                    value=saved.get("openrouter_base_url", OPENROUTER_BASE_URL),
                    help="Mặc định là https://openrouter.ai/api/v1",
                    key="onboarding_openrouter_base_url"
                ).strip() or OPENROUTER_BASE_URL
                custom_model_input = st.text_input(
                    "Nhập Model ID tùy chỉnh (VD: deepseek/deepseek-r1)",
                    value=saved.get("custom_openrouter_model", ""),
                    help="Để trống nếu dùng model đã chọn trong danh sách ở trên.",
                    key="onboarding_custom_openrouter_model"
                ).strip()
                if custom_model_input:
                    selected_model = custom_model_input

        elif provider == "Qwen (Alibaba Cloud)":
            with st.expander("🔧 Base URL nâng cao (Qwen)", expanded=False):
                custom_base_url = st.text_input(
                    "Base URL",
                    value=saved.get("qwen_base_url", DASHSCOPE_BASE_URL),
                    key="onboarding_qwen_base_url"
                ).strip() or DASHSCOPE_BASE_URL

    st.markdown("---")

    # 3. Tùy chọn nâng cao & Lưu trữ
    st.subheader("3. ⚡ Tùy chọn Phân tích & Lưu trữ Cấu hình")
    c_opt1, c_opt2 = st.columns(2, gap="large")

    with c_opt1:
        remember_config = st.checkbox(
            "💾 Tự động lưu cấu hình trên máy này (không cần nhập lại)",
            value=saved.get("remember_config", True),
            help="Lưu vào file cục bộ an toàn, không đẩy lên Git.",
            key="onboarding_remember_config"
        )
        auto_connect = st.checkbox(
            "⚡ Tự động kết nối & bỏ qua màn hình này ở các lần mở app sau",
            value=saved.get("auto_connect", True),
            help="Mở app là vào thẳng màn hình Chat phân tích dữ liệu ngay.",
            key="onboarding_auto_connect"
        )
        enable_auto_insights = st.checkbox(
            "💡 Tự động tìm Insight & Bất thường (AI)",
            value=saved.get("enable_auto_insights", True),
            help="Tự động phân tích sâu và đề xuất kế hoạch hành động khi có xu hướng bất thường.",
            key="onboarding_enable_auto_insights"
        )

    with c_opt2:
        enable_self_check = st.checkbox(
            "🛡️ Bật kiểm định SQL bằng AI (self-check)",
            value=saved.get("enable_self_check", True),
            help="Tự kiểm tra độ chính xác của SQL trước khi trả về kết quả.",
            key="onboarding_enable_self_check"
        )
        enable_cache = st.checkbox(
            "♻️ Dùng lại kết quả cho câu hỏi trùng lặp (cache)",
            value=saved.get("enable_cache", True),
            help="Tiết kiệm quota API khi hỏi lại các câu hỏi cũ trong phiên.",
            key="onboarding_enable_cache"
        )
        forecast_periods = st.slider(
            "Số kỳ dự báo xu hướng tương lai", 1, 12, saved.get("forecast_periods", 3),
            key="onboarding_forecast_periods"
        )

    with st.expander("📤 Cấu hình Gửi Báo Cáo Doanh Nghiệp (Telegram / Email) [Tùy chọn]", expanded=False):
        st.markdown("##### 🚀 Kênh 1: Telegram Bot (Gửi Báo Cáo PDF vào Nhóm/Kênh)")
        c_tg1, c_tg2 = st.columns(2)
        with c_tg1:
            telegram_bot_token = st.text_input(
                "Telegram Bot Token",
                value=saved.get("telegram_bot_token", ""),
                type="password",
                placeholder="123456789:ABCdef...",
                key="onboarding_telegram_bot_token"
            )
        with c_tg2:
            telegram_chat_id = st.text_input(
                "Telegram Chat ID / Group ID",
                value=saved.get("telegram_chat_id", ""),
                placeholder="-100123456789 hoặc @channel_name",
                key="onboarding_telegram_chat_id"
            )

        st.markdown("##### 📧 Kênh 2: Email SMTP (Gmail / Outlook / Công ty)")
        c_em1, c_em2 = st.columns(2)
        with c_em1:
            smtp_server = st.text_input("SMTP Server", value=saved.get("smtp_server", "smtp.gmail.com"), key="onboarding_smtp_server")
            smtp_user = st.text_input("Email Người gửi", value=saved.get("smtp_user", ""), placeholder="sender@company.com", key="onboarding_smtp_user")
        with c_em2:
            smtp_port = st.text_input("SMTP Port", value=saved.get("smtp_port", "587"), key="onboarding_smtp_port")
            smtp_pass = st.text_input("Mật khẩu Ứng dụng (App Password)", value=saved.get("smtp_pass", ""), type="password", key="onboarding_smtp_pass")

        email_receivers = st.text_input(
            "Danh sách Email Người nhận mặc định (Cách nhau bằng dấu phẩy)",
            value=saved.get("email_receivers", ""),
            placeholder="boss@company.com, leads@company.com",
            key="onboarding_email_receivers"
        )

    with st.expander("📝 Mô tả Schema / Quy tắc Nghiệp vụ Bổ sung (Tùy chọn)", expanded=False):
        schema_context_input = st.text_area(
            "Mô tả nghiệp vụ hoặc chú thích thêm về cấu trúc bảng (Hệ thống sẽ tự trích xuất nếu để trống)",
            value=st.session_state.get("schema_context", ""),
            height=120,
            key="onboarding_schema_context_input"
        )

    # Nút hành động chính
    st.markdown("###")
    col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 1])

    with col_btn1:
        connect_btn = st.button(
            "🚀 Bắt đầu Sử dụng & Kết nối",
            type="primary",
            use_container_width=True,
            key="btn_onboarding_connect"
        )

    with col_btn2:
        if is_already_connected:
            if st.button("← Quay lại Chat", use_container_width=True, key="btn_back_to_chat_bottom"):
                st.session_state["view_mode"] = "chat"
                st.rerun()

    with col_btn3:
        if st.button("🗑️ Xóa cấu hình đã lưu", use_container_width=True, key="btn_onboarding_clear_config"):
            clear_saved_config()
            st.session_state["_auto_connect_attempted"] = True
            st.session_state["connected"] = False
            st.success("✅ Đã xóa toàn bộ cấu hình đã lưu!")
            st.rerun()

    # Đồng bộ session state
    st.session_state["enable_auto_insights"] = enable_auto_insights
    st.session_state["enable_self_check"] = enable_self_check
    st.session_state["enable_cache"] = enable_cache
    st.session_state["forecast_periods"] = forecast_periods
    st.session_state["telegram_bot_token"] = telegram_bot_token
    st.session_state["telegram_chat_id"] = telegram_chat_id
    st.session_state["smtp_server"] = smtp_server
    st.session_state["smtp_port"] = smtp_port
    st.session_state["smtp_user"] = smtp_user
    st.session_state["smtp_pass"] = smtp_pass
    st.session_state["email_receivers"] = email_receivers

    effective_provider = "OpenRouter" if is_openrouter_key else provider

    if connect_btn:
        if not clean_api_key:
            st.error(f"❌ Vui lòng nhập API Key cho {effective_provider}!")
        elif not use_demo and not (db_host and db_user and db_name):
            st.error("❌ Vui lòng điền đầy đủ Host, User, Database Name!")
        else:
            def on_success(model_used):
                if remember_config:
                    config_to_save = saved.copy()
                    config_to_save.update({
                        "data_mode_index": 0 if use_demo else 1,
                        "run_local": run_local,
                        "db_host": db_host,
                        "db_port": db_port,
                        "db_user": db_user,
                        "db_pass": db_pass,
                        "db_name": db_name,
                        "use_ssl": use_ssl,
                        "provider": effective_provider,
                        "model_name": model_used,
                        "enable_auto_insights": enable_auto_insights,
                        "enable_self_check": enable_self_check,
                        "enable_cache": enable_cache,
                        "forecast_periods": forecast_periods,
                        "remember_config": True,
                        "auto_connect": auto_connect,
                        "telegram_bot_token": telegram_bot_token,
                        "telegram_chat_id": telegram_chat_id,
                        "smtp_server": smtp_server,
                        "smtp_port": smtp_port,
                        "smtp_user": smtp_user,
                        "smtp_pass": smtp_pass,
                        "email_receivers": email_receivers,
                    })
                    if effective_provider == "OpenRouter":
                        config_to_save["api_key_openrouter"] = clean_api_key
                        config_to_save["openrouter_base_url"] = custom_base_url
                        config_to_save["custom_openrouter_model"] = custom_model_input
                    elif effective_provider == "Gemini (Google)":
                        config_to_save["api_key_gemini"] = clean_api_key
                    elif effective_provider == "Qwen (Alibaba Cloud)":
                        config_to_save["api_key_qwen"] = clean_api_key
                        config_to_save["qwen_base_url"] = custom_base_url

                    save_user_config(config_to_save)

            show_connecting_dialog(
                use_demo=use_demo,
                db_host=db_host,
                db_port=db_port,
                db_user=db_user,
                db_pass=db_pass,
                db_name=db_name,
                use_ssl=use_ssl,
                run_local=run_local,
                effective_provider=effective_provider,
                clean_api_key=clean_api_key,
                custom_base_url=custom_base_url,
                selected_model=selected_model,
                schema_context_input=schema_context_input,
                on_success_callback=on_success,
            )
