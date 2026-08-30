"""
Sidebar UI component for Database and AI configuration with automatic persistence,
key auto-detection, and auto-connection on startup.
"""

import streamlit as st
from src.config import (
    PROVIDER_CONFIGS,
    DASHSCOPE_BASE_URL,
    OPENROUTER_BASE_URL,
    LOCAL_HOST_ALIASES,
)
from src.config_store import load_saved_config, save_user_config, clear_saved_config
from src.database.connection import try_connect
from src.database.demo_data import build_demo_engine
from src.database.schema import auto_extract_schema
from src.database.query_runner import sanitize_error
from src.llm.client import get_llm_client, normalize_model_for_openrouter


def perform_connection(
    use_demo: bool,
    db_host: str,
    db_port: str,
    db_user: str,
    db_pass: str,
    db_name: str,
    use_ssl: bool,
    run_local: bool,
    effective_provider: str,
    clean_api_key: str,
    custom_base_url: str,
    selected_model: str,
    schema_context_input: str,
) -> tuple[bool, str]:
    """Thực hiện kết nối tới Database và AI Provider, trích xuất schema và cập nhật session state."""
    try:
        if use_demo:
            engine = build_demo_engine()
        else:
            engine = try_connect(
                db_host, db_port, db_user, db_pass, db_name, use_ssl, run_local=run_local
            )

        client = get_llm_client(effective_provider, clean_api_key, custom_base_url)
        extracted_schema = auto_extract_schema(engine)
        final_schema = schema_context_input if schema_context_input.strip() else extracted_schema

        final_model_name = selected_model
        if effective_provider == "OpenRouter":
            final_model_name = normalize_model_for_openrouter(selected_model)

        st.session_state.update({
            "engine": engine,
            "client": client,
            "provider": effective_provider,
            "model_name": final_model_name,
            "schema_context": final_schema,
            "connected": True,
            "_db_pass_for_sanitize": db_pass,
            "is_demo": use_demo,
            "db_dialect": "SQLite" if use_demo else "MySQL",
        })
        return True, final_model_name
    except Exception as e:
        st.session_state["connected"] = False
        err_display = sanitize_error(str(e), db_pass)
        return False, err_display


def render_sidebar():
    """Hiển thị toàn bộ Sidebar cấu hình kết nối DB và AI với tính năng lưu và tự động kết nối."""
    saved = load_saved_config()

    with st.sidebar:
        st.header("⚙️ Cấu hình Kết nối")
        st.caption("Cấu hình được lưu an toàn trên máy của bạn (không commit vào Git).")

        # Hiển thị trạng thái kết nối nếu đã thành công
        if st.session_state.get("connected"):
            db_type = "🎮 SQLite Demo" if st.session_state.get("is_demo") else "🔌 MySQL"
            st.success(f"🟢 **Đã kết nối:** {db_type}\n\n🤖 **AI:** {st.session_state.get('provider')} — `{st.session_state.get('model_name')}`")

        data_mode_options = ["🎮 Dùng dữ liệu mẫu (Demo, không cần MySQL)", "🔌 Kết nối MySQL của tôi"]
        saved_mode_idx = saved.get("data_mode_index", 0)
        if saved_mode_idx >= len(data_mode_options):
            saved_mode_idx = 0

        data_mode = st.radio(
            "Nguồn dữ liệu",
            data_mode_options,
            index=saved_mode_idx,
        )
        use_demo = data_mode.startswith("🎮")

        if not use_demo:
            st.subheader("1. MySQL Database")
            run_local = st.checkbox(
                "🖥️ Database chạy trên máy Local (localhost)",
                value=saved.get("run_local", False),
                help="Tự động điền Host = localhost và thử các alias thay thế (127.0.0.1, host.docker.internal)."
            )

            if run_local:
                st.info(
                    "ℹ️ **Lưu ý:** \"localhost\" chỉ hoạt động khi app Streamlit đang chạy trên **cùng máy tính** "
                    "với MySQL (`streamlit run app.py`)."
                )
                db_host = st.text_input("Host", value=saved.get("db_host", "localhost") or "localhost")
            else:
                default_host = saved.get("db_host", "")
                if default_host in ("localhost", "127.0.0.1"):
                    default_host = ""
                db_host = st.text_input("Host", value=default_host, placeholder="e.g., mysql-xxx.aivencloud.com")

            db_port_raw = st.text_input("Port", value=saved.get("db_port", "3306"))
            db_user = st.text_input("User", value=saved.get("db_user", "root"))
            db_pass = st.text_input("Password", value=saved.get("db_pass", ""), type="password")
            db_name = st.text_input("Database Name", value=saved.get("db_name", ""), placeholder="e.g., my_business_db")
            use_ssl = st.checkbox(
                "Dùng SSL (bắt buộc với hầu hết MySQL cloud: Aiven, Railway...)",
                value=saved.get("use_ssl", not run_local)
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
        provider_list = list(PROVIDER_CONFIGS.keys())
        saved_provider = saved.get("provider", "OpenRouter")
        provider_idx = provider_list.index(saved_provider) if saved_provider in provider_list else 0

        provider = st.selectbox("Provider", provider_list, index=provider_idx)
        provider_cfg = PROVIDER_CONFIGS[provider]

        # Lấy API Key đã lưu tương ứng với provider
        if provider == "OpenRouter":
            default_key = saved.get("api_key_openrouter", "")
        elif provider == "Gemini (Google)":
            default_key = saved.get("api_key_gemini", "")
        else:
            default_key = saved.get("api_key_qwen", "")

        api_key = st.text_input(
            "API Key",
            value=default_key,
            type="password",
            help=provider_cfg["key_help"],
            placeholder=provider_cfg["key_placeholder"],
        )
        st.caption(f"💡 {provider_cfg['free_tier_note']}")

        # Nhận diện thông minh API Key
        clean_api_key = api_key.strip()
        is_openrouter_key = clean_api_key.startswith("sk-or-v1-")

        if is_openrouter_key and provider != "OpenRouter":
            st.info("💡 Phát hiện API Key của **OpenRouter**. Hệ thống sẽ tự động định tuyến qua OpenRouter Base URL (`https://openrouter.ai/api/v1`).")

        model_options = provider_cfg["models"]
        saved_model = saved.get("model_name", "")
        model_idx = model_options.index(saved_model) if saved_model in model_options else 0
        selected_model = st.selectbox("Model AI", model_options, index=model_idx)

        # Base URL và tuỳ chọn nâng cao
        custom_base_url = ""
        custom_model_input = ""
        if provider == "OpenRouter" or is_openrouter_key:
            custom_base_url = saved.get("openrouter_base_url", OPENROUTER_BASE_URL)
            with st.expander("🔧 Cấu hình nâng cao OpenRouter", expanded=False):
                st.caption("Base URL mặc định cho OpenRouter là `https://openrouter.ai/api/v1`.")
                custom_base_url = st.text_input(
                    "Base URL (OpenRouter)",
                    value=custom_base_url,
                    help="Mặc định là https://openrouter.ai/api/v1"
                ).strip() or OPENROUTER_BASE_URL
                custom_model_input = st.text_input(
                    "Hoặc nhập Model ID tùy chỉnh (VD: deepseek/deepseek-r1)",
                    value=saved.get("custom_openrouter_model", ""),
                    help="Để trống nếu dùng model đã chọn trong danh sách ở trên."
                ).strip()
                if custom_model_input:
                    selected_model = custom_model_input

        elif provider == "Qwen (Alibaba Cloud)":
            custom_base_url = saved.get("qwen_base_url", DASHSCOPE_BASE_URL)
            with st.expander("🔧 Base URL nâng cao (Qwen)", expanded=False):
                st.caption(
                    "Một số tài khoản Alibaba Cloud mới yêu cầu dùng domain riêng theo workspace. "
                    "Dán URL OpenAI-compatible tại đây nếu cần."
                )
                custom_base_url = st.text_input(
                    "Base URL", value=custom_base_url,
                    help="Mặc định là domain chung dashscope-intl."
                ).strip() or DASHSCOPE_BASE_URL

        with st.expander("⚡ Tối ưu Phân tích & Quota", expanded=False):
            enable_auto_insights = st.checkbox(
                "Tự động tìm Insight & Bất thường (AI)",
                value=saved.get("enable_auto_insights", True),
                help="Tự động phân tích sâu và đưa ra nhận định kinh doanh khi phát hiện xu hướng hoặc điểm bất thường."
            )
            enable_self_check = st.checkbox(
                "Bật kiểm định SQL bằng AI (self-check)",
                value=saved.get("enable_self_check", True),
                help="Mỗi câu hỏi tốn thêm 1 lượt gọi AI để tự kiểm tra lại SQL. Tắt đi để tiết kiệm ~50% quota."
            )
            enable_cache = st.checkbox(
                "Dùng lại kết quả cho câu hỏi trùng lặp (cache)",
                value=saved.get("enable_cache", True),
                help="Dùng lại kết quả cũ cho câu hỏi lặp lại trong cùng phiên."
            )

        schema_context_input = st.text_area(
            "Mô tả Schema / Nghiệp vụ (Tự động nạp sau khi bấm Kết nối)",
            value=st.session_state.get("schema_context", ""),
            height=180
        )

        forecast_periods = st.slider("Số kỳ dự báo xu hướng", 1, 12, saved.get("forecast_periods", 3))

        # Checkbox lưu thông tin & Tự động kết nối
        remember_config = st.checkbox(
            "💾 Tự động lưu cấu hình cho lần sau",
            value=saved.get("remember_config", True),
            help="Lưu thông tin đăng nhập và cài đặt vào file cục bộ để không cần nhập lại khi mở lại app."
        )

        auto_connect = st.checkbox(
            "⚡ Tự động kết nối khi mở trang",
            value=saved.get("auto_connect", True),
            help="Tự động kết nối Database & AI ngay khi mở web nếu thông tin cấu hình hợp lệ."
        )

        connect_btn = st.button("🔌 Kết nối Database & AI", type="primary", use_container_width=True)

        # Quản lý xóa cấu hình đã lưu
        with st.expander("⚙️ Quản lý Cấu hình Lưu trữ", expanded=False):
            if st.button("🗑️ Xóa toàn bộ cấu hình đã lưu", use_container_width=True):
                clear_saved_config()
                st.session_state["_auto_connect_attempted"] = True
                st.success("✅ Đã xóa cấu hình đã lưu. Hãy làm mới lại trang!")
                st.rerun()

    # Đồng bộ session state
    st.session_state["enable_auto_insights"] = enable_auto_insights
    st.session_state["enable_self_check"] = enable_self_check
    st.session_state["enable_cache"] = enable_cache
    st.session_state["forecast_periods"] = forecast_periods

    effective_provider = "OpenRouter" if is_openrouter_key else provider

    # --- TỰ ĐỘNG KẾT NỐI KHI MỞ TRANG (AUTO-CONNECT) ---
    if not st.session_state.get("connected") and not st.session_state.get("_auto_connect_attempted", False):
        st.session_state["_auto_connect_attempted"] = True
        if auto_connect and clean_api_key:
            can_auto_connect = use_demo or bool(db_host and db_user and db_name)
            if can_auto_connect:
                success, detail = perform_connection(
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
                )
                if success:
                    st.toast(f"⚡ Đã tự động kết nối {effective_provider} ({detail}) & {'SQLite Demo' if use_demo else 'MySQL'}!", icon="⚡")
                    st.rerun()

    # --- XỬ LÝ KHI BẤM NÚT KẾT NỐI THỦ CÔNG ---
    if connect_btn:
        if not clean_api_key:
            st.sidebar.error(f"❌ Vui lòng nhập API Key cho {effective_provider}!")
        elif not use_demo and not (db_host and db_user and db_name):
            st.sidebar.error("❌ Vui lòng điền đầy đủ Host, User, Database Name!")
        else:
            success, detail = perform_connection(
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
            )

            if success:
                # Lưu cấu hình nếu người dùng chọn ghi nhớ
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
                        "model_name": detail,
                        "enable_auto_insights": enable_auto_insights,
                        "enable_self_check": enable_self_check,
                        "enable_cache": enable_cache,
                        "forecast_periods": forecast_periods,
                        "remember_config": True,
                        "auto_connect": auto_connect,
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

                st.sidebar.success(f"✅ Kết nối thành công! (AI: {effective_provider} — {detail})")
                st.rerun()
            else:
                if "429" in detail or "RESOURCE_EXHAUSTED" in detail:
                    st.sidebar.error(
                        f"🚫 API Key {effective_provider} hết quota hôm nay. Vui lòng tạo key mới hoặc đổi Provider."
                    )
                elif not use_demo and run_local:
                    st.sidebar.error(
                        f"❌ Không kết nối được tới MySQL local (đã thử: {', '.join(LOCAL_HOST_ALIASES)}).\n\n"
                        f"Lỗi: {detail}"
                    )
                else:
                    st.sidebar.error(f"❌ Lỗi kết nối: {detail}")
