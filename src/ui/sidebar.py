"""
Sidebar UI component for Session Management, Database Table Explorer, and Interactive Chat History Navigation.
Allows clicking on any historical question to view its result directly.
"""

import streamlit as st
from src.database.connection import try_connect
from src.database.demo_data import build_demo_engine
from src.database.schema import (
    auto_extract_schema,
    get_table_names,
    get_table_columns_info,
    get_table_sample_df,
)
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
        custom_notes = (schema_context_input or "").strip()
        if custom_notes and not custom_notes.startswith("Cơ sở dữ liệu bao gồm") and custom_notes != extracted_schema:
            final_schema = f"{extracted_schema}\n\n=== GHI CHÚ NGHIỆP VỤ BỔ SUNG ===\n{custom_notes}"
        else:
            final_schema = extracted_schema

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
            "history": [],
            "query_cache": {},
            "focused_turn_idx": None,
            "pending_prompt": None,
        })
        return True, final_model_name
    except Exception as e:
        st.session_state["connected"] = False
        err_display = sanitize_error(str(e), db_pass)
        return False, err_display


@st.dialog("👁️ Khám Phá Cấu Trúc & Dữ Liệu Mẫu", width="large")
def show_table_preview_dialog(engine, tables: list[str], default_table: str = None):
    """Hộp thoại Modal toàn màn hình hiển thị cấu trúc schema và 10 dòng dữ liệu mẫu trực quan."""
    if not tables:
        st.info("Không tìm thấy bảng nào trong cơ sở dữ liệu.")
        return

    c_sel1, c_sel2 = st.columns([3, 1])
    with c_sel1:
        initial_idx = tables.index(default_table) if (default_table and default_table in tables) else 0
        selected_t = st.selectbox(
            "Chọn bảng dữ liệu để xem chi tiết:",
            tables,
            index=initial_idx,
            key="dialog_preview_selected_table"
        )
    with c_sel2:
        st.write("")
        st.write("")
        st.caption(f"Tổng số: **{len(tables)} bảng**")

    cols_info = get_table_columns_info(engine, selected_t)

    # 1. Hiển thị cấu trúc cột
    with st.expander(f"📋 Cấu trúc Schema bảng `{selected_t}` ({len(cols_info)} cột)", expanded=False):
        import pandas as pd
        col_rows = []
        for idx, c in enumerate(cols_info):
            col_rows.append({
                "STT": idx + 1,
                "Tên Cột": c["name"],
                "Kiểu Dữ Liệu": str(c["type"]),
                "Khóa / Ràng buộc": "🔑 Khóa Chính" if c.get("pk") else ("Bắt buộc (NOT NULL)" if not c.get("nullable") else "NULL")
            })
        if col_rows:
            st.dataframe(pd.DataFrame(col_rows), hide_index=True, use_container_width=True)

    # 2. Hiển thị 10 dòng mẫu
    sample_df = get_table_sample_df(engine, selected_t, limit=10)
    if not sample_df.empty:
        st.markdown(f"**👁️ 10 dòng dữ liệu mẫu bảng `{selected_t}`:**")
        st.dataframe(sample_df, use_container_width=True)

        c_dl, _ = st.columns([2, 3])
        with c_dl:
            csv_data = sample_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"📥 Tải mẫu `{selected_t}.csv`",
                data=csv_data,
                file_name=f"{selected_t}_sample.csv",
                mime="text/csv",
                key=f"dl_dialog_sample_{selected_t}"
            )
    else:
        st.caption("Bảng này hiện chưa có dữ liệu.")


def render_main_sidebar():
    """Hiển thị Sidebar với nút Cài đặt, Khám phá Bảng DB và Danh sách Lịch sử Chat tương tác (Click to View)."""
    engine = st.session_state.get("engine")
    is_demo = st.session_state.get("is_demo", True)
    provider = st.session_state.get("provider", "OpenRouter")
    model_name = st.session_state.get("model_name", "deepseek/deepseek-chat")

    with st.sidebar:
        # --- PHẦN 1: TOP SIDEBAR (NÚT CẤU HÌNH & TẠO CHAT MỚI) ---
        st.markdown("### 🗄️ Veraxus for SQL")
        db_badge = "🎮 SQLite Demo" if is_demo else "🔌 MySQL DB"
        st.caption(f"🟢 **{db_badge}** | {provider} (`{model_name}`)")

        c_top1, c_top2 = st.columns(2)
        with c_top1:
            if st.button("⚙️ Cấu hình", use_container_width=True, key="sidebar_btn_settings", help="Mở màn hình cài đặt để đổi Database hoặc AI Provider"):
                st.session_state["view_mode"] = "settings"
                st.rerun()

        with c_top2:
            if st.button("➕ Chat Mới", type="primary", use_container_width=True, key="sidebar_btn_new_chat", help="Bắt đầu một phiên hội thoại mới"):
                st.session_state["history"] = []
                st.session_state["query_cache"] = {}
                st.session_state["focused_turn_idx"] = None
                st.rerun()

        st.markdown("---")

        # --- PHẦN 2: BÊN DƯỚI TOP SIDEBAR (KHÁM PHÁ BẢNG DATABASE) ---
        st.subheader("🗄️ Khám phá Bảng DB")

        if engine:
            tables = get_table_names(engine)
            if tables:
                st.caption(f"Cơ sở dữ liệu gồm **{len(tables)} bảng** nghiệp vụ:")
                selected_table = st.selectbox(
                    "Chọn bảng",
                    tables,
                    key="sidebar_selected_table",
                    label_visibility="collapsed",
                    help="Chọn một bảng để xem cấu trúc và mẫu dữ liệu toàn màn hình."
                )
                cols_info = get_table_columns_info(engine, selected_table)
                st.caption(f"📊 Bảng `{selected_table}`: **{len(cols_info)} cột**")

                if st.button(
                    f"👁️ Mở bảng `{selected_table}`",
                    key=f"sidebar_btn_preview_{selected_table}",
                    use_container_width=True,
                    type="secondary",
                    help=f"Mở hộp thoại toàn màn hình xem cấu trúc schema và 10 dòng mẫu của bảng {selected_table}"
                ):
                    show_table_preview_dialog(engine, tables, selected_table)
            else:
                st.caption("Không tìm thấy bảng nào trong cơ sở dữ liệu.")
        else:
            st.caption("Chưa kết nối cơ sở dữ liệu.")

        st.markdown("---")

        # --- PHẦN 3: LỊCH SỬ CÁC CUỘC TRÒ CHUYỆN (INTERACTIVE CHAT HISTORY) ---
        st.subheader("💬 Lịch sử Trò chuyện")

        history = st.session_state.get("history", [])
        focused_turn_idx = st.session_state.get("focused_turn_idx", None)

        if history:
            # Nút quay về xem toàn bộ nếu đang ở chế độ xem tập trung 1 câu
            if focused_turn_idx is not None:
                if st.button("🌐 Xem toàn bộ hội thoại", use_container_width=True, key="sidebar_btn_show_all_chat", type="secondary"):
                    st.session_state["focused_turn_idx"] = None
                    st.rerun()

            st.caption("💡 *Nhấp vào câu hỏi bất kỳ để xem trực tiếp:*")

            for i, turn in enumerate(history):
                query_text = turn.get("query", "")
                short_q = query_text if len(query_text) <= 32 else query_text[:29] + "..."
                is_active = (focused_turn_idx == i)

                btn_label = f"👉 {i+1}. {short_q}" if is_active else f"💬 {i+1}. {short_q}"
                btn_type = "primary" if is_active else "secondary"

                if st.button(
                    btn_label,
                    key=f"sidebar_hist_btn_{i}",
                    use_container_width=True,
                    type=btn_type,
                    help=f"Xem trực tiếp câu hỏi: {query_text}"
                ):
                    st.session_state["focused_turn_idx"] = i
                    st.rerun()

            st.markdown("###")
            if st.button("🗑️ Xóa lịch sử chat", use_container_width=True, key="sidebar_btn_clear_history"):
                st.session_state["history"] = []
                st.session_state["query_cache"] = {}
                st.session_state["focused_turn_idx"] = None
                st.toast("🧹 Đã xóa toàn bộ lịch sử trò chuyện!", icon="🗑️")
                st.rerun()
        else:
            st.caption("Chưa có câu hỏi nào trong phiên này. Hãy đặt câu hỏi đầu tiên ở khung chat bên phải!")
