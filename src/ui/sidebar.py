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
from src.i18n import t, get_current_language, render_language_switcher_button


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
    """Hiển thị Sidebar tinh gọn, chuyên nghiệp, sắc nét của VERAXUS với Dark Theme (#12141C)."""
    engine = st.session_state.get("engine")
    is_demo = st.session_state.get("is_demo", True)
    provider = st.session_state.get("provider", "OpenRouter")
    model_name = st.session_state.get("model_name", "deepseek/deepseek-chat")

    with st.sidebar:
        # --- DARK THEME SIDEBAR CSS (#12141C) & VIBRANT HIGH-CONTRAST ACCENTS ---
        st.markdown("""
        <style>
            [data-testid="stSidebar"],
            [data-testid="stSidebar"] > div:first-child,
            [data-testid="stSidebarContent"],
            [data-testid="stSidebarUserContent"] {
                background-color: #12141C !important;
            }
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span {
                color: #FFFFFF !important;
            }
            .sidebar-section-hdr {
                font-size: 0.8rem;
                font-weight: 800;
                letter-spacing: 0.05em;
                text-transform: uppercase;
                color: #38BDF8 !important;
                margin: 16px 0 8px 2px;
                display: flex;
                align-items: center;
                gap: 6px;
            }
            [data-testid="stSidebar"] .stButton > button {
                border-radius: 9px !important;
                font-weight: 750 !important;
                font-size: 0.86rem !important;
            }
            [data-testid="stSidebar"] .stButton > button[kind="primary"] {
                background: linear-gradient(135deg, #0052D4 0%, #0068FF 100%) !important;
                color: #FFFFFF !important;
                border: 1px solid rgba(255, 255, 255, 0.25) !important;
                box-shadow: 0 4px 14px rgba(0, 104, 255, 0.4) !important;
            }
            [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
                background: linear-gradient(135deg, #0068FF 0%, #00F0FF 100%) !important;
                color: #090D1A !important;
                box-shadow: 0 6px 18px rgba(0, 240, 255, 0.5) !important;
                transform: translateY(-1px) !important;
            }
            [data-testid="stSidebar"] .stButton > button[kind="secondary"] {
                background: #181D2F !important;
                border: 1px solid rgba(255, 255, 255, 0.15) !important;
                color: #FFFFFF !important;
            }
            [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
                background: #232A42 !important;
                border-color: #00F0FF !important;
                color: #00F0FF !important;
                transform: translateY(-1px) !important;
            }
        </style>
        """, unsafe_allow_html=True)

        # --- PHẦN 1: TOP BRANDING, LANGUAGE SWITCHER & STATUS ---
        is_en = (get_current_language() == "en")
        db_badge = ("Demo DB (SQLite)" if is_en else "Dữ liệu Mẫu (Demo)") if is_demo else ("Enterprise DB" if is_en else "CSDL Doanh Nghiệp")
        if "qwen" in model_name.lower() or "ollama" in provider.lower():
            engine_badge = "Local Engine"
        elif "deepseek" in model_name.lower():
            engine_badge = "DeepSeek V3"
        elif "gemini" in model_name.lower():
            engine_badge = "Gemini 3.7"
        elif "claude" in model_name.lower():
            engine_badge = "Claude 3.5"
        else:
            engine_badge = "AI Engine"

        st.markdown(textwrap.dedent(f"""
        <div style="padding: 4px 4px 10px 4px;">
            <div style="font-size: 1.35rem; font-weight: 900; color: #FFFFFF; display: flex; align-items: center; gap: 9px;">
                <svg width="26" height="26" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" style="filter: drop-shadow(0 2px 8px rgba(0, 240, 255, 0.5)); flex-shrink: 0;">
                    <defs>
                        <linearGradient id="sbFacetLeftFront" x1="20%" y1="10%" x2="50%" y2="90%">
                            <stop offset="0%" stop-color="#00F0FF"/>
                            <stop offset="60%" stop-color="#0068FF"/>
                            <stop offset="100%" stop-color="#0047BA"/>
                        </linearGradient>
                        <linearGradient id="sbFacetRightFront" x1="80%" y1="10%" x2="50%" y2="90%">
                            <stop offset="0%" stop-color="#7928CA"/>
                            <stop offset="50%" stop-color="#FF0080"/>
                            <stop offset="100%" stop-color="#02388A"/>
                        </linearGradient>
                    </defs>
                    <polygon points="18,22 36,12 50,88 34,74" fill="url(#sbFacetLeftFront)"/>
                    <polygon points="18,22 36,12 48,22 30,32" fill="#38BDF8"/>
                    <polygon points="82,22 64,12 50,88 66,74" fill="url(#sbFacetRightFront)"/>
                    <polygon points="82,22 64,12 52,22 70,32" fill="#E0F2FE"/>
                    <polygon points="30,32 48,22 50,54 38,58" fill="#0052CC"/>
                    <polygon points="70,32 52,22 50,54 62,58" fill="#003D99"/>
                    <polygon points="38,58 50,54 62,58 50,88" fill="#00F0FF"/>
                </svg>
                <span style="background: linear-gradient(90deg, #FFFFFF, #00F0FF); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -0.02em; font-weight: 900;">VERAXUS</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px; margin-top: 6px; padding-left: 2px;">
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #00DF8F; box-shadow: 0 0 8px rgba(0, 223, 143, 0.7);"></span>
                <span style="font-size: 0.8rem; font-weight: 750; color: #00DF8F;">{db_badge}</span>
                <span style="font-size: 0.72rem; color: #64748B;">•</span>
                <span style="font-size: 0.78rem; color: #CBD5E1; font-weight: 600;">{engine_badge}</span>
            </div>
        </div>
        """).strip(), unsafe_allow_html=True)

        # Nút chuyển đổi ngôn ngữ gọn gàng trên thanh Sidebar
        render_language_switcher_button(key_suffix="sidebar")
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        # Action Buttons: New Chat & Settings
        c_top1, c_top2 = st.columns(2)
        with c_top1:
            if st.button(t("sidebar_btn_new_chat"), type="primary", use_container_width=True, key="sidebar_btn_new_chat", help="Start a new conversation" if is_en else "Bắt đầu một phiên hội thoại mới"):
                st.session_state["history"] = []
                st.session_state["query_cache"] = {}
                st.session_state["focused_turn_idx"] = None
                st.session_state["view_mode"] = "chat"
                st.rerun()

        with c_top2:
            if st.button(t("sidebar_btn_settings"), use_container_width=True, key="sidebar_btn_settings", help="Open Database / AI configuration" if is_en else "Mở màn hình Cài đặt Database hoặc AI Provider"):
                st.session_state["view_mode"] = "settings"
                st.rerun()

        # Nút chuyển đổi nhanh sang Executive Dashboard & Self-Evolution Dashboard
        current_vmode = st.session_state.get("view_mode", "chat")
        from src.database.crm_queries import detect_dashboard_domain
        detected_dom = detect_dashboard_domain(engine)
        if detected_dom == "hr_employees":
            dash_btn_label = t("sidebar_btn_hr_dashboard")
        elif detected_dom == "northwind_erp":
            dash_btn_label = t("sidebar_btn_northwind_dashboard")
        elif detected_dom == "sales_commerce":
            dash_btn_label = t("sidebar_btn_sales_dashboard")
        elif detected_dom == "sakila_rental":
            dash_btn_label = "🎬 Dashboard Sakila" if not is_en else "🎬 Sakila Dashboard"
        elif detected_dom == "crm_support":
            dash_btn_label = t("sidebar_btn_crm_dashboard")
        else:
            dash_btn_label = "💎 Dashboard CSDL" if not is_en else "💎 Universal Dashboard"

        if current_vmode in ("dashboard", "evolution"):
            if st.button(t("back_to_chat"), use_container_width=True, type="secondary", key="sidebar_btn_toggle_chat"):
                st.session_state["view_mode"] = "chat"
                st.rerun()
        else:
            c_dash1, c_dash2 = st.columns(2)
            with c_dash1:
                if st.button(dash_btn_label, use_container_width=True, type="secondary", key="sidebar_btn_toggle_dash", help="Open Executive Intelligence Dashboard" if is_en else "Mở Dashboard phân tích điều hành thông minh tự động theo cơ sở dữ liệu"):
                    st.session_state["view_mode"] = "dashboard"
                    st.rerun()
            with c_dash2:
                if st.button(t("sidebar_btn_evolution"), use_container_width=True, type="secondary", key="sidebar_btn_toggle_evo", help="Open Multi-Agent Self-Evolution Loop Dashboard" if is_en else "Mở Bảng Điều Khiển Tiến Hóa Đa Tác Tử & Ngân Hàng Tri Thức Động"):
                    st.session_state["view_mode"] = "evolution"
                    st.rerun()

        st.markdown("<hr style='margin: 14px 0 10px 0; border: none; border-top: 1px solid rgba(255,255,255,0.08);' />", unsafe_allow_html=True)

        # --- PHẦN 2: KHÁM PHÁ BẢNG DỮ LIỆU ---
        st.markdown(f"""
        <div class='sidebar-section-hdr'>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="vertical-align:-2px; margin-right:5px;"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>
            {t("sidebar_schema_title")}
        </div>
        """, unsafe_allow_html=True)

        if engine:
            tables = get_table_names(engine)
            if tables:
                selected_table = st.selectbox(
                    "Chọn bảng",
                    tables,
                    key="sidebar_selected_table",
                    label_visibility="collapsed",
                    help="Select a table to inspect schema and 10 sample records." if is_en else "Chọn một bảng để xem cấu trúc schema và 10 dòng dữ liệu mẫu."
                )
                cols_info = get_table_columns_info(engine, selected_table)
                st.markdown(f"""
                <div style='font-size:0.78rem; color:#94A3B8; margin-bottom:6px;'>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="vertical-align:-1px; margin-right:4px;"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
                    {t("sidebar_schema_table_info", table=selected_table, count=len(cols_info))}
                </div>
                """, unsafe_allow_html=True)

                if st.button(
                    t("sidebar_schema_open_table", table=selected_table),
                    key=f"sidebar_btn_preview_{selected_table}",
                    use_container_width=True,
                    type="secondary",
                    help=f"Inspect schema and 10 sample rows of {selected_table}" if is_en else f"Xem cấu trúc schema và 10 dòng mẫu của bảng {selected_table}"
                ):
                    show_table_preview_dialog(engine, tables, selected_table)
            else:
                st.caption("No tables found in the database." if is_en else "Không tìm thấy bảng nào trong cơ sở dữ liệu.")
        else:
            st.caption("Database disconnected." if is_en else "Chưa kết nối cơ sở dữ liệu.")

        st.markdown("<hr style='margin: 14px 0 10px 0; border: none; border-top: 1px solid rgba(255,255,255,0.08);' />", unsafe_allow_html=True)

        # --- PHẦN 3: LỊCH SỬ HỘI THOẠI ---
        st.markdown(f"""
        <div class='sidebar-section-hdr'>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="vertical-align:-2px; margin-right:5px;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 14 14"></polyline></svg>
            {t("sidebar_history_title")}
        </div>
        """, unsafe_allow_html=True)

        history = st.session_state.get("history", [])
        focused_turn_idx = st.session_state.get("focused_turn_idx", None)

        if history:
            if focused_turn_idx is not None:
                if st.button("All conversations" if is_en else "Toàn bộ cuộc trò chuyện", use_container_width=True, key="sidebar_btn_show_all_chat", type="secondary"):
                    st.session_state["focused_turn_idx"] = None
                    st.rerun()

            st.markdown(f"<div style='font-size:0.76rem; color:#64748B; margin-bottom:8px;'><i>{t('sidebar_history_click_hint')}</i></div>", unsafe_allow_html=True)

            for i, turn in enumerate(history):
                query_text = turn.get("query", "")
                short_q = query_text if len(query_text) <= 30 else query_text[:27] + "..."
                is_active = (focused_turn_idx == i)

                btn_label = f"› {i+1}. {short_q}" if is_active else f"  {i+1}. {short_q}"
                btn_type = "primary" if is_active else "secondary"

                if st.button(
                    btn_label,
                    key=f"sidebar_hist_btn_{i}",
                    use_container_width=True,
                    type=btn_type,
                    help=f"View query: {query_text}" if is_en else f"Xem trực tiếp câu hỏi: {query_text}"
                ):
                    st.session_state["focused_turn_idx"] = i
                    st.rerun()

            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            if st.button(t("sidebar_history_clear_btn"), use_container_width=True, key="sidebar_btn_clear_history"):
                st.session_state["history"] = []
                st.session_state["query_cache"] = {}
                st.session_state["focused_turn_idx"] = None
                st.toast(t("sidebar_history_clear_confirm"))
                st.rerun()
        else:
            st.markdown(f"<div style='font-size:0.8rem; color:#64748B; line-height:1.4;'>{t('sidebar_history_empty')}</div>", unsafe_allow_html=True)
