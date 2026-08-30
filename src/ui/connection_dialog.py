"""
Connection progress and loading modal/view manager with cancellation and retry handling.
"""

import streamlit as st
from src.database.connection import try_connect
from src.database.demo_data import build_demo_engine
from src.database.schema import auto_extract_schema
from src.database.query_runner import sanitize_error
from src.llm.client import get_llm_client, normalize_model_for_openrouter


def render_auto_connect_failed_view(error_msg: str):
    """Hiển thị giao diện thông báo khi tự động kết nối thất bại hoặc bị người dùng hủy."""
    st.markdown("###")
    col_l, col_center, col_r = st.columns([1, 2, 1])

    with col_center:
        st.markdown("### ⚠️ Không thể tự động kết nối Database")
        st.warning(f"**Chi tiết:** {error_msg}")
        st.caption("Nguyên nhân có thể do Database Cloud đang cold-start, sai thông tin đăng nhập hoặc kết nối mạng không ổn định.")

        st.markdown("###")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Thử kết nối lại", type="primary", use_container_width=True):
                st.session_state["_auto_connect_attempted"] = False
                st.session_state["_auto_connect_error"] = None
                st.rerun()

        with c2:
            if st.button("⚙️ Mở Cấu hình để chỉnh sửa", use_container_width=True):
                st.session_state["view_mode"] = "settings"
                st.session_state["_auto_connect_error"] = None
                st.rerun()


@st.dialog("🔌 Đang thiết lập kết nối...", width="medium")
def show_connecting_dialog(
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
    on_success_callback=None,
):
    """Dialog hiển thị trạng thái kết nối với thanh tiến trình và nút Hủy."""
    st.write("Vui lòng đợi trong giây lát trong khi hệ thống thiết lập kết nối và trích xuất Schema.")

    status_placeholder = st.empty()
    progress_bar = st.progress(20, text="Khởi tạo AI Client...")

    # Nút hủy kết nối
    if st.button("❌ Hủy kết nối", use_container_width=True):
        st.session_state["_connecting_in_progress"] = False
        st.warning("⚠️ Đã hủy quá trình kết nối.")
        st.rerun()

    try:
        # Bước 1: AI Client
        progress_bar.progress(40, text=f"1/3: Đang kết nối tới AI Provider ({effective_provider})...")
        client = get_llm_client(effective_provider, clean_api_key, custom_base_url)

        # Bước 2: Database Engine
        db_desc = "SQLite In-Memory Demo" if use_demo else f"MySQL ({db_host}:{db_port})"
        progress_bar.progress(70, text=f"2/3: Đang kết nối Cơ sở dữ liệu: {db_desc}...")
        if use_demo:
            engine = build_demo_engine()
        else:
            engine = try_connect(
                db_host, db_port, db_user, db_pass, db_name, use_ssl, run_local=run_local
            )

        # Bước 3: Schema Extraction
        progress_bar.progress(90, text="3/3: Đang trích xuất cấu trúc bảng (Schema)...")
        extracted_schema = auto_extract_schema(engine)
        final_schema = schema_context_input if schema_context_input.strip() else extracted_schema

        final_model_name = selected_model
        if effective_provider == "OpenRouter":
            final_model_name = normalize_model_for_openrouter(selected_model)

        progress_bar.progress(100, text="Hoàn tất!")

        # Cập nhật state
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
            "view_mode": "chat",
            "_connecting_in_progress": False,
        })

        if on_success_callback:
            on_success_callback(final_model_name)

        st.toast(f"✅ Kết nối thành công! (AI: {effective_provider} — {final_model_name})", icon="🚀")
        st.rerun()

    except Exception as e:
        st.session_state["connected"] = False
        st.session_state["_connecting_in_progress"] = False
        err_display = sanitize_error(str(e), db_pass)
        status_placeholder.error(f"❌ Kết nối thất bại: {err_display}")
        st.caption("Hãy kiểm tra lại thông tin Host, User, Password hoặc đổi sang SQLite Demo.")
