"""
Dedicated full-screen Onboarding and Settings Wizard UI component with Loading Dialog.
Optimized for 1-Click Judge Experience and Enterprise Configuration.
"""

import streamlit as st
from src.config import (
    PROVIDER_CONFIGS,
    DASHSCOPE_BASE_URL,
    OPENROUTER_BASE_URL,
    OLLAMA_BASE_URL,
)
from src.config_store import load_saved_config, save_user_config, clear_saved_config
from src.ui.connection_dialog import show_connecting_dialog
from src.database.connection import try_connect


def render_onboarding():
    """Hiển thị màn hình Onboarding / Cài đặt cấu hình độc lập toàn trang."""
    saved = load_saved_config()
    is_already_connected = st.session_state.get("connected", False)

    # 1. Header điều hướng & Badge trạng thái phong thái Enterprise SaaS
    col_head1, col_head2 = st.columns([3, 1])
    with col_head1:
        if is_already_connected:
            st.markdown("""
            <div style="margin-bottom: 8px;">
                <h1 style="font-size: 1.85rem; font-weight: 800; color: #0F172A; margin: 0 0 4px 0;">⚙️ Cài đặt & Cấu hình Kết nối</h1>
                <p style="color: #64748B; font-size: 0.92rem; margin: 0;">Thay đổi nguồn dữ liệu, nhà cung cấp AI hoặc tùy biến tham số phân tích.</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="margin-bottom: 8px;">
                <h1 style="font-size: 1.85rem; font-weight: 800; color: #0F172A; margin: 0 0 4px 0;">🗄️ Chào mừng đến với Veraxus AI</h1>
                <p style="color: #64748B; font-size: 0.92rem; margin: 0;">Trợ lý AI phân tích và điều hành dữ liệu kinh doanh thông minh</p>
            </div>
            """, unsafe_allow_html=True)

    with col_head2:
        st.markdown("""
        <div style="text-align: right; padding-top: 6px;">
            <span style="background: #F1F5F9; color: #334155; border: 1px solid #E2E8F0; padding: 5px 12px; border-radius: 9999px; font-size: 0.78rem; font-weight: 600; letter-spacing: 0.02em;">
                • Local Engine (Offline & Secured)
            </span>
        </div>
        """, unsafe_allow_html=True)
        if is_already_connected:
            st.write("")
            if st.button("← Quay lại Chat", type="secondary", use_container_width=True, key="btn_back_to_chat_top"):
                st.session_state["view_mode"] = "chat"
                st.rerun()

    # Thông báo cảnh báo nếu vừa tự động kết nối thất bại
    auto_err = st.session_state.get("_auto_connect_error")
    if auto_err and not is_already_connected:
        st.warning(
            f"⚠️ **Không thể kết nối Database với cấu hình đã lưu**: `{auto_err}`\n\n"
            "👉 Vui lòng kiểm tra và cập nhật lại thông tin MySQL ở bảng **Chế độ Doanh nghiệp** bên dưới."
        )

    st.markdown("---")

    # 2. Hai chế độ trải nghiệm rõ ràng (Triết lý 1-Click Connect)
    col_demo, col_enterprise = st.columns(2, gap="large")

    # =========================================================
    # CỘT 1: CHẾ ĐỘ THẨM ĐỊNH (DEMO DÀNH CHO GIÁM KHẢO)
    # =========================================================
    with col_demo:
        with st.container(border=True):
            st.markdown("### ⚡ Chế độ Thẩm định (Demo)")
            st.caption("Dành cho Ban Giám khảo & Người dùng muốn trải nghiệm ngay tức thì.")

            st.markdown("""
            <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 14px 16px; margin: 12px 0 16px 0;">
                <div style="margin-bottom: 8px; font-size: 0.88rem; color: #1E293B;">
                    📊 <b>CSDL Mẫu:</b> Awesome Chocolates (Sales, P&L, Nhân sự thực tế)
                </div>
                <div style="margin-bottom: 8px; font-size: 0.88rem; color: #1E293B;">
                    🛡️ <b>Mô hình AI:</b> Local Qwen 2.5 / Ollama (100% Cục bộ & Bảo mật)
                </div>
                <div style="font-size: 0.88rem; color: #1E293B;">
                    ⏱️ <b>Thời gian khởi tạo:</b> <b>1 Click • 1 Giây</b> (Zero-Friction)
                </div>
            </div>
            """, unsafe_allow_html=True)

            btn_demo_connect = st.button(
                "🚀 Khám phá ngay (Demo 1-Click)",
                type="primary",
                use_container_width=True,
                key="btn_demo_1click",
                help="Tự động kết nối cơ sở dữ liệu mẫu Awesome Chocolates và mô hình AI để bắt đầu hỏi đáp ngay lập tức."
            )

            st.caption("🔒 *Không yêu cầu nhập API Key. Không gửi dữ liệu tài chính ra ngoài internet.*")

    # =========================================================
    # CỘT 2: CHẾ ĐỘ TÙY CHỈNH DOANH NGHIỆP (ENTERPRISE MODE)
    # =========================================================
    with col_enterprise:
        with st.container(border=True):
            st.markdown("### 🏢 Chế độ Doanh nghiệp")
            st.caption("Kết nối MySQL Database thực tế và tùy biến thông số AI nâng cao.")

            # Giá trị mặc định an toàn cho các tùy chọn
            telegram_bot_token = saved.get("telegram_bot_token", "")
            telegram_chat_id = saved.get("telegram_chat_id", "")
            smtp_server = saved.get("smtp_server", "smtp.gmail.com")
            smtp_port = saved.get("smtp_port", "587")
            smtp_user = saved.get("smtp_user", "")
            smtp_pass = saved.get("smtp_pass", "")
            email_receivers = saved.get("email_receivers", "")
            remember_config = saved.get("remember_config", True)
            auto_connect = saved.get("auto_connect", True)
            enable_auto_insights = saved.get("enable_auto_insights", True)
            enable_self_check = saved.get("enable_self_check", True)
            enable_cache = saved.get("enable_cache", True)
            forecast_periods = saved.get("forecast_periods", 3)
            schema_context_input = ""

            tab_mysql, tab_ai, tab_opts = st.tabs(["🔌 CSDL MySQL", "🤖 Cấu hình AI", "⚡ Tham số & Kênh"])

            with tab_mysql:
                is_local_saved = saved.get("run_local", True) or (saved.get("db_host", "") in ("localhost", "127.0.0.1", ""))
                conn_mode = st.radio(
                    "Môi trường MySQL Database",
                    ["🖥️ Máy tính này (Localhost)", "☁️ Máy chủ / Cloud (Từ xa)"],
                    index=0 if is_local_saved else 1,
                    horizontal=True,
                    key="onboarding_conn_mode"
                )
                run_local = (conn_mode == "🖥️ Máy tính này (Localhost)")

                if run_local:
                    db_host = "localhost"
                    use_ssl = False

                    st.markdown("""
                    <div style="background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; font-size: 0.84rem; color: #166534; display: flex; align-items: center; gap: 8px;">
                        <span>🟢</span> <span><b>Chế độ Cục bộ (Localhost):</b> <code>127.0.0.1:3306</code> (Không cần cấu hình mạng).</span>
                    </div>
                    """, unsafe_allow_html=True)

                    c_u1, c_u2 = st.columns([1, 2])
                    with c_u1:
                        db_user = st.text_input("User", value=saved.get("db_user", "root") or "root", key="onboarding_db_user_local")
                    with c_u2:
                        db_pass = st.text_input("Password", value=saved.get("db_pass", ""), type="password", key="onboarding_db_pass_local")

                    db_name = st.text_input("Database Name", value=saved.get("db_name", "employees") or "employees", placeholder="VD: employees", key="onboarding_db_name_local")

                    with st.expander("⚙️ Tùy chọn Port nâng cao (Mặc định: 3306)", expanded=False):
                        db_port_raw = st.text_input("Port", value=saved.get("db_port", "3306") or "3306", key="onboarding_db_port_local")
                else:
                    default_cloud_host = saved.get("db_host", "")
                    if default_cloud_host in ("localhost", "127.0.0.1"):
                        default_cloud_host = ""
                    db_host = st.text_input("Host máy chủ MySQL", value=default_cloud_host, placeholder="VD: mysql-xxx.aivencloud.com", key="onboarding_db_host")

                    c_p1, c_p2 = st.columns([1, 2])
                    with c_p1:
                        db_port_raw = st.text_input("Port", value=saved.get("db_port", "3306") or "3306", key="onboarding_db_port_remote")
                    with c_p2:
                        db_user = st.text_input("User", value=saved.get("db_user", "root") or "root", key="onboarding_db_user_remote")

                    db_pass = st.text_input("Password", value=saved.get("db_pass", ""), type="password", key="onboarding_db_pass_remote")
                    db_name = st.text_input("Database Name", value=saved.get("db_name", ""), placeholder="VD: my_company_db", key="onboarding_db_name_remote")
                    use_ssl = st.checkbox(
                        "Dùng SSL (Bắt buộc với hầu hết MySQL Cloud: Aiven, Railway...)",
                        value=saved.get("use_ssl", True),
                        key="onboarding_use_ssl"
                    )

                db_host = (db_host or "localhost" if run_local else db_host or "").strip()
                db_user = db_user.strip()
                db_name = db_name.strip()
                db_port_digits = "".join(ch for ch in str(db_port_raw) if ch.isdigit())
                db_port = db_port_digits or "3306"

                # Nút kiểm tra kết nối nhanh (Ping Test)
                if st.button("🔍 Kiểm tra kết nối MySQL (Ping Test)", use_container_width=True, key="btn_ping_mysql"):
                    if not db_user or not db_name or (not run_local and not db_host):
                        st.warning("⚠️ Vui lòng điền đủ User và Database Name trước khi kiểm tra.")
                    else:
                        try:
                            with st.spinner(f"Đang kiểm tra kết nối tới MySQL ({db_host}:{db_port})..."):
                                test_eng = try_connect(db_host, db_port, db_user, db_pass, db_name, use_ssl, run_local=run_local)
                                test_eng.dispose()
                            st.success(f"✅ Kết nối thành công tới database `{db_name}` ({db_host}:{db_port})!")
                        except Exception as p_err:
                            st.error(f"❌ Kết nối thất bại: {p_err}")

            with tab_ai:
                provider_list = list(PROVIDER_CONFIGS.keys())
                saved_provider = saved.get("provider", "OpenRouter")
                provider_idx = provider_list.index(saved_provider) if saved_provider in provider_list else 0

                provider = st.selectbox("Chọn Provider AI", provider_list, index=provider_idx, key="onboarding_provider")
                provider_cfg = PROVIDER_CONFIGS[provider]

                if provider == "OpenRouter":
                    default_key = saved.get("api_key_openrouter", "")
                elif provider == "Gemini (Google)":
                    default_key = saved.get("api_key_gemini", "")
                elif provider == "Ollama (Local AI Offline)":
                    default_key = saved.get("api_key_ollama", "ollama")
                else:
                    default_key = saved.get("api_key_qwen", "")

                if provider == "Ollama (Local AI Offline)":
                    api_key = default_key or "ollama"
                    st.caption("ℹ️ *Ollama chạy cục bộ trên máy tính (100% Offline, không cần API Key).*")
                else:
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

                model_options = list(provider_cfg["models"])
                if provider == "Ollama (Local AI Offline)":
                    try:
                        import json
                        import urllib.request
                        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "Veraxus"})
                        with urllib.request.urlopen(req, timeout=0.6) as response:
                            data = json.loads(response.read().decode())
                            installed = [m["name"] for m in data.get("models", []) if "name" in m]
                            for inst in reversed(installed):
                                if inst in model_options:
                                    model_options.remove(inst)
                                model_options.insert(0, inst)
                    except Exception:
                        pass

                saved_model = saved.get("model_name", "")
                model_idx = model_options.index(saved_model) if saved_model in model_options else 0
                selected_model = st.selectbox("Chọn Model AI", model_options, index=model_idx, key="onboarding_model")

                custom_base_url = ""
                if provider == "OpenRouter" or is_openrouter_key:
                    custom_base_url = st.text_input(
                        "Base URL",
                        value=saved.get("openrouter_base_url", OPENROUTER_BASE_URL),
                        help="Mặc định là https://openrouter.ai/api/v1",
                        key="onboarding_openrouter_base_url"
                    ).strip() or OPENROUTER_BASE_URL
                elif provider == "Ollama (Local AI Offline)":
                    custom_base_url = st.text_input(
                        "Base URL Ollama",
                        value=saved.get("ollama_base_url", OLLAMA_BASE_URL),
                        help="Mặc định là http://localhost:11434/v1",
                        key="onboarding_ollama_base_url"
                    ).strip() or OLLAMA_BASE_URL

            with tab_opts:
                c_opt1, c_opt2 = st.columns(2)
                with c_opt1:
                    remember_config = st.checkbox(
                        "💾 Tự động lưu cấu hình trên máy này",
                        value=saved.get("remember_config", True),
                        key="onboarding_remember_config"
                    )
                    auto_connect = st.checkbox(
                        "⚡ Tự động kết nối ở các lần mở app sau",
                        value=saved.get("auto_connect", True),
                        key="onboarding_auto_connect"
                    )
                    enable_auto_insights = st.checkbox(
                        "💡 Tự động tìm Insight & Bất thường (AI)",
                        value=saved.get("enable_auto_insights", True),
                        key="onboarding_enable_auto_insights"
                    )
                with c_opt2:
                    enable_self_check = st.checkbox(
                        "🛡️ Bật kiểm định SQL bằng AI (self-check)",
                        value=saved.get("enable_self_check", True),
                        key="onboarding_enable_self_check"
                    )
                    enable_cache = st.checkbox(
                        "♻️ Dùng lại kết quả cho câu hỏi trùng lặp (cache)",
                        value=saved.get("enable_cache", True),
                        key="onboarding_enable_cache"
                    )
                    forecast_periods = st.slider(
                        "Số kỳ dự báo xu hướng", 1, 12, saved.get("forecast_periods", 3),
                        key="onboarding_forecast_periods"
                    )

                raw_saved_notes = saved.get("custom_business_notes", "")
                if raw_saved_notes.startswith("Cơ sở dữ liệu bao gồm"):
                    raw_saved_notes = ""
                schema_context_input = st.text_area(
                    "Ghi chú Quy tắc Nghiệp vụ bổ sung (Tùy chọn)",
                    value=raw_saved_notes,
                    placeholder="VD: Chỉ tính nhân viên chính thức, Lương chưa bao gồm phụ cấp...",
                    height=65,
                    key="onboarding_schema_context_input"
                )

                with st.expander("📤 Kênh chia sẻ Báo cáo (Telegram / Email SMTP)", expanded=False):
                    telegram_bot_token = st.text_input("Telegram Bot Token", value=saved.get("telegram_bot_token", ""), type="password", key="onboarding_telegram_bot_token")
                    telegram_chat_id = st.text_input("Telegram Chat ID", value=saved.get("telegram_chat_id", ""), key="onboarding_telegram_chat_id")
                    smtp_server = st.text_input("SMTP Server", value=saved.get("smtp_server", "smtp.gmail.com"), key="onboarding_smtp_server")
                    smtp_port = st.text_input("SMTP Port", value=saved.get("smtp_port", "587"), key="onboarding_smtp_port")
                    smtp_user = st.text_input("Email Người gửi", value=saved.get("smtp_user", ""), key="onboarding_smtp_user")
                    smtp_pass = st.text_input("Mật khẩu Ứng dụng SMTP", value=saved.get("smtp_pass", ""), type="password", key="onboarding_smtp_pass")
                    email_receivers = st.text_input("Email Người nhận", value=saved.get("email_receivers", ""), key="onboarding_email_receivers")

            st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
            btn_custom_connect = st.button(
                "🚀 Kết nối MySQL Doanh nghiệp",
                type="primary",
                use_container_width=True,
                key="btn_onboarding_connect"
            )

    # 3. Nút phụ trợ phía dưới
    st.markdown("###")
    c_sub1, c_sub2, c_sub3 = st.columns([2, 1, 1])
    with c_sub3:
        if st.button("🗑️ Xóa cấu hình đã lưu", use_container_width=True, key="btn_onboarding_clear_config"):
            clear_saved_config()
            st.session_state["_auto_connect_attempted"] = True
            st.session_state["connected"] = False
            st.success("✅ Đã xóa toàn bộ cấu hình đã lưu!")
            st.rerun()

    # 4. Xử lý Logic Kết nối khi bấm nút
    # A. Xử lý nút 1-Click Demo
    if btn_demo_connect:
        effective_provider = saved.get("provider", "Ollama (Local AI Offline)")
        clean_api_key = saved.get("api_key_ollama", "ollama")
        custom_base_url = saved.get("ollama_base_url", OLLAMA_BASE_URL)
        selected_model = saved.get("model_name", "qwen2.5-coder:3b")

        def on_demo_success(model_used):
            config_to_save = saved.copy()
            config_to_save.update({
                "data_mode_index": 0,
                "run_local": False,
                "provider": effective_provider,
                "model_name": model_used,
                "remember_config": True,
                "auto_connect": True,
            })
            save_user_config(config_to_save)

        show_connecting_dialog(
            use_demo=True,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="",
            use_ssl=False,
            run_local=False,
            effective_provider=effective_provider,
            clean_api_key=clean_api_key,
            custom_base_url=custom_base_url,
            selected_model=selected_model,
            schema_context_input="",
            on_success_callback=on_demo_success,
        )

    # B. Xử lý nút Kết nối Tùy chỉnh (Enterprise Mode)
    if btn_custom_connect:
        effective_provider = "OpenRouter" if is_openrouter_key else provider
        if effective_provider == "Ollama (Local AI Offline)" and not clean_api_key:
            clean_api_key = "ollama"

        if not clean_api_key and effective_provider != "Ollama (Local AI Offline)":
            st.error(f"❌ Vui lòng nhập API Key cho {effective_provider}!")
        elif run_local and not db_name:
            st.error("❌ Vui lòng nhập Database Name (VD: employees)!")
        elif run_local and not db_user:
            st.error("❌ Vui lòng nhập User MySQL (mặc định: root)!")
        elif not run_local and not db_host:
            st.error("❌ Vui lòng nhập Host máy chủ MySQL Cloud (hoặc chọn 'Máy tính này (Localhost)')!")
        elif not run_local and not (db_user and db_name):
            st.error("❌ Vui lòng điền đầy đủ User và Database Name!")
        else:
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

            def on_custom_success(model_used):
                if remember_config:
                    config_to_save = saved.copy()
                    config_to_save.update({
                        "data_mode_index": 1,
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
                    elif effective_provider == "Gemini (Google)":
                        config_to_save["api_key_gemini"] = clean_api_key
                    elif effective_provider == "Ollama (Local AI Offline)":
                        config_to_save["api_key_ollama"] = clean_api_key
                        config_to_save["ollama_base_url"] = custom_base_url
                    elif effective_provider == "Qwen (Alibaba Cloud)":
                        config_to_save["api_key_qwen"] = clean_api_key
                        config_to_save["qwen_base_url"] = custom_base_url

                    save_user_config(config_to_save)

            show_connecting_dialog(
                use_demo=False,
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
                on_success_callback=on_custom_success,
            )
