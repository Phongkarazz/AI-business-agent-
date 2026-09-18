"""
Sidebar UI component for Session Management, Database Table Explorer, and Interactive Chat History Navigation.
Allows clicking on any historical question to view its result directly.
"""

import textwrap
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
        extracted_schema = auto_extract_schema(engine, force_refresh=True)
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
        display_sample_df = sample_df.copy()
        for col in display_sample_df.columns:
            if col.lower() == "team":
                display_sample_df[col] = display_sample_df[col].fillna("(Chưa phân loại)").replace({"": "(Chưa phân loại)"})
        st.dataframe(display_sample_df, use_container_width=True)

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
        # --- PHẦN 1: TOP SIDEBAR (THƯƠNG HIỆU & ĐIỀU HÀNH) ---
        db_badge = "Dữ liệu Mẫu (Demo)" if is_demo else "CSDL Doanh Nghiệp"
        if "qwen" in model_name.lower() or "ollama" in provider.lower():
            engine_badge = "Nội bộ (Local Engine)"
        elif "deepseek" in model_name.lower():
            engine_badge = "DeepSeek V3"
        elif "gemini" in model_name.lower():
            engine_badge = "Gemini 3.7"
        elif "claude" in model_name.lower():
            engine_badge = "Claude 3.5"
        else:
            engine_badge = "Veraxus Engine"

        st.markdown(textwrap.dedent(f"""
        <div style="padding: 4px 4px 14px 4px;">
            <div style="font-size: 1.22rem; font-weight: 850; color: #0F172A; display: flex; align-items: center; gap: 8px;">
                <svg width="22" height="22" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" style="filter: drop-shadow(0 2px 6px rgba(0, 104, 255, 0.30)); flex-shrink: 0;">
                    <defs>
                        <linearGradient id="sbFacetLeftFront" x1="20%" y1="10%" x2="50%" y2="90%">
                            <stop offset="0%" stop-color="#38BDF8"/>
                            <stop offset="60%" stop-color="#0068FF"/>
                            <stop offset="100%" stop-color="#0047BA"/>
                        </linearGradient>
                        <linearGradient id="sbFacetLeftTop" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#BAE6FD"/>
                            <stop offset="100%" stop-color="#38BDF8"/>
                        </linearGradient>
                        <linearGradient id="sbFacetRightFront" x1="80%" y1="10%" x2="50%" y2="90%">
                            <stop offset="0%" stop-color="#00A3FF"/>
                            <stop offset="50%" stop-color="#0052CC"/>
                            <stop offset="100%" stop-color="#02388A"/>
                        </linearGradient>
                        <linearGradient id="sbFacetRightTop" x1="100%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#E0F2FE"/>
                            <stop offset="100%" stop-color="#7DD3FC"/>
                        </linearGradient>
                        <linearGradient id="sbFacetCenterGlow" x1="50%" y1="40%" x2="50%" y2="92%">
                            <stop offset="0%" stop-color="#67E8F9"/>
                            <stop offset="100%" stop-color="#0068FF"/>
                        </linearGradient>
                    </defs>
                    <polygon points="18,22 36,12 50,88 34,74" fill="url(#sbFacetLeftFront)"/>
                    <polygon points="18,22 36,12 48,22 30,32" fill="url(#sbFacetLeftTop)"/>
                    <polygon points="82,22 64,12 50,88 66,74" fill="url(#sbFacetRightFront)"/>
                    <polygon points="82,22 64,12 52,22 70,32" fill="url(#sbFacetRightTop)"/>
                    <polygon points="30,32 48,22 50,54 38,58" fill="#0052CC"/>
                    <polygon points="70,32 52,22 50,54 62,58" fill="#003D99"/>
                    <polygon points="38,58 50,54 62,58 50,88" fill="url(#sbFacetCenterGlow)"/>
                </svg>
                <span style="color: #0068FF; letter-spacing: -0.025em; font-weight: 900;">VERAXUS</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px; margin-top: 8px; padding-left: 2px;">
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #10B981; box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);"></span>
                <span style="font-size: 0.78rem; font-weight: 600; color: #15803D;">{db_badge}</span>
                <span style="font-size: 0.72rem; color: #CBD5E1;">•</span>
                <span style="font-size: 0.76rem; color: #64748B; font-weight: 500;">{engine_badge}</span>
            </div>
        </div>
        """).strip(), unsafe_allow_html=True)

        c_top1, c_top2 = st.columns(2)
        with c_top1:
            if st.button("➕ Chat Mới", type="primary", use_container_width=True, key="sidebar_btn_new_chat", help="Bắt đầu một phiên hội thoại mới"):
                st.session_state["history"] = []
                st.session_state["query_cache"] = {}
                st.session_state["focused_turn_idx"] = None
                st.rerun()

        with c_top2:
            if st.button("⚙️ Cấu hình", use_container_width=True, key="sidebar_btn_settings", help="Mở màn hình Cài đặt Database hoặc AI Provider"):
                st.session_state["view_mode"] = "settings"
                st.rerun()

        st.markdown("<hr style='margin: 12px 0; border: none; border-top: 1px solid #E2E8F0;' />", unsafe_allow_html=True)

        # --- PHẦN 2: KHÁM PHÁ BẢNG DỮ LIỆU ---
        st.markdown("<div style='font-size: 0.88rem; font-weight: 700; color: #334155; margin-bottom: 6px; padding-left: 2px;'>🗄️ Danh mục Bảng Dữ liệu</div>", unsafe_allow_html=True)

        if engine:
            tables = get_table_names(engine)
            if tables:
                st.caption(f"Cơ sở dữ liệu gồm **{len(tables)} danh mục** nghiệp vụ:")
                selected_table = st.selectbox(
                    "Chọn bảng",
                    tables,
                    key="sidebar_selected_table",
                    label_visibility="collapsed",
                    help="Chọn một bảng để xem cấu trúc schema và 10 dòng dữ liệu mẫu."
                )
                cols_info = get_table_columns_info(engine, selected_table)
                st.caption(f"📊 Bảng `{selected_table}`: **{len(cols_info)} trường thông tin**")

                if st.button(
                    f"👁️ Mở bảng `{selected_table}`",
                    key=f"sidebar_btn_preview_{selected_table}",
                    use_container_width=True,
                    type="secondary",
                    help=f"Xem cấu trúc schema và 10 dòng mẫu của bảng {selected_table}"
                ):
                    show_table_preview_dialog(engine, tables, selected_table)
            else:
                st.caption("Không tìm thấy bảng nào trong cơ sở dữ liệu.")
        else:
            st.caption("Chưa kết nối cơ sở dữ liệu.")

        st.markdown("<hr style='margin: 12px 0; border: none; border-top: 1px solid #E2E8F0;' />", unsafe_allow_html=True)

        # --- PHẦN 3: LỊCH SỬ HỘI THOẠI ---
        st.markdown("<div style='font-size: 0.88rem; font-weight: 700; color: #334155; margin-bottom: 6px; padding-left: 2px;'>💬 Lịch sử Hội thoại</div>", unsafe_allow_html=True)

        history = st.session_state.get("history", [])
        focused_turn_idx = st.session_state.get("focused_turn_idx", None)

        if history:
            if focused_turn_idx is not None:
                if st.button("🌐 Xem toàn bộ hội thoại", use_container_width=True, key="sidebar_btn_show_all_chat", type="secondary"):
                    st.session_state["focused_turn_idx"] = None
                    st.rerun()

            st.caption("💡 *Bấm vào câu hỏi để xem lại kết quả tức thì:*")

            for i, turn in enumerate(history):
                query_text = turn.get("query", "")
                short_q = query_text if len(query_text) <= 30 else query_text[:27] + "..."
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
            if st.button("🗑️ Dọn dẹp lịch sử", use_container_width=True, key="sidebar_btn_clear_history"):
                st.session_state["history"] = []
                st.session_state["query_cache"] = {}
                st.session_state["focused_turn_idx"] = None
                st.toast("🧹 Đã dọn dẹp toàn bộ lịch sử trò chuyện!", icon="🗑️")
                st.rerun()
        else:
            st.caption("Chưa có câu hỏi nào. Hãy nhập câu hỏi đầu tiên ở khung chat bên phải!")
