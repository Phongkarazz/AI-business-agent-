"""
Saved Query Templates & Feedback Management UI.
Accessible from Settings (`Thiết lập`) instead of cluttering the primary sidebar.
"""

import streamlit as st
from src.llm.dynamic_memory import (
    get_evolution_metrics,
    save_learned_case,
    init_memory_db,
)
from src.i18n import t, get_current_language


def render_evolution_dashboard():
    """Render clean Saved Query Templates & User Feedback History panel (Bilingual)."""
    init_memory_db()
    metrics = get_evolution_metrics()
    is_en = (get_current_language() == "en")

    # 1. Header Banner + Navigation
    col_hdr_main, col_hdr_nav = st.columns([5.0, 1.8])
    with col_hdr_main:
        title_text = t("evo_dash_title")
        subtitle_text = t("evo_dash_subtitle")
        st.markdown(f"""
        <div style="background: #11141C; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 18px 22px; margin-bottom: 18px;">
            <div>
                <h2 style="margin: 0 0 4px 0; color: #F8FAFC; font-weight: 700; font-size: 1.25rem; letter-spacing: -0.02em;">
                    {title_text}
                </h2>
                <div style="color: #94A3B8; font-size: 0.86rem; line-height: 1.4;">
                    {subtitle_text}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with col_hdr_nav:
        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
        if st.button(t("back_to_chat"), use_container_width=True, type="secondary", key="btn_evo_back_chat"):
            st.session_state["view_mode"] = "chat"
            st.rerun()
        settings_back_lbl = "⚙️ Back to Settings" if is_en else "⚙️ Về Thiết lập"
        if st.button(settings_back_lbl, use_container_width=True, type="secondary", key="btn_evo_back_settings"):
            st.session_state["view_mode"] = "settings"
            st.rerun()

    # 2. Factual Summary Metrics (No fabricated scores or jargon)
    total_saved = int(metrics.get("total_learned", 0) or 0)
    total_disliked = int(metrics.get("total_disliked", 0) or 0)
    recent_logs = metrics.get("recent_logs", []) or []
    positive_fb = sum(1 for l in recent_logs if "UP" in str(l.get("event_type", "")).upper() or "SAVE" in str(l.get("event_type", "")).upper())

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            label=t("evo_kpi_samples"),
            value=str(total_saved),
            help="Saved question-to-SQL pairs used as reference examples for similar queries." if is_en else "Các cặp câu hỏi và SQL chuẩn đã lưu để Veraxus tham khảo cho các câu hỏi tương tự."
        )
    with c2:
        st.metric(
            label="👍 " + ("Positive Feedback" if is_en else "Phản hồi hài lòng"),
            value=str(positive_fb),
        )
    with c3:
        st.metric(
            label="👎 " + ("Needs Correction" if is_en else "Phản hồi cần sửa"),
            value=str(total_disliked),
        )

    st.write("")

    # 3. Practical User Tabs
    tab_memory, tab_add, tab_logs = st.tabs([
        "📚 Saved Templates" if is_en else "📚 Mẫu truy vấn đã lưu",
        "➕ Add Template" if is_en else "➕ Thêm mẫu mới",
        "📋 Feedback History" if is_en else "📋 Lịch sử đánh giá",
    ])

    with tab_memory:
        st.markdown("### 📚 " + ("Verified Query Templates" if is_en else "Danh sách mẫu truy vấn đã lưu"))
        recent_cases = metrics.get("recent_cases", [])
        if recent_cases:
            for idx, item in enumerate(recent_cases, 1):
                case_title = f"🔹 **#{item['id']}**: *\"{item['user_query']}\"* (`{item['domain']}`)"
                with st.expander(case_title, expanded=(idx <= 2)):
                    c_det, c_del = st.columns([5, 1])
                    with c_det:
                        intent_lbl = "**Business Notes:**" if is_en else "**Ghi chú nghiệp vụ:**"
                        st.markdown(f"{intent_lbl} {item.get('intent_explanation') or '-'}")
                    with c_del:
                        del_btn_label = "🗑️ Delete" if is_en else "🗑️ Xóa"
                        del_btn_help = "Remove this saved template" if is_en else "Xóa mẫu truy vấn này"
                        if st.button(del_btn_label, key=f"btn_del_case_{item['id']}", help=del_btn_help):
                            from src.llm.dynamic_memory import delete_learned_case
                            delete_learned_case(item["id"])
                            st.toast(f"Deleted #{item['id']}" if is_en else f"Đã xóa mẫu #{item['id']}", icon="🗑️")
                            st.rerun()
                    st.code(item["sql_query"], language="sql")
                    time_lbl = "Saved at:" if is_en else "Thời gian:"
                    st.caption(f"{time_lbl} `{item.get('created_at', '')}`")
        else:
            st.info(
                "No saved templates yet. Rate an answer 👍 or adjust SQL from the ⋯ menu in Chat to save a reusable template!"
                if is_en else
                "Chưa có mẫu truy vấn nào được lưu. Bạn có thể bấm 👍 hoặc chỉnh sửa SQL trong menu ⋯ ở màn hình Chat để lưu mẫu chuẩn!"
            )

    with tab_add:
        st.markdown("### ➕ " + ("Add a Reusable Query Template" if is_en else "Thêm mẫu truy vấn chuẩn cho doanh nghiệp"))
        with st.form("form_add_manual_knowledge"):
            q_label = "Business Question:" if is_en else "Câu hỏi nghiệp vụ:"
            q_ph = "e.g. Monthly revenue by sales channel..." if is_en else "Ví dụ: Doanh thu theo từng kênh bán trong tháng 10/2026..."
            in_query = st.text_input(q_label, placeholder=q_ph)

            dom_label = "Workspace / Database:" if is_en else "Cơ sở dữ liệu áp dụng:"
            in_domain = st.selectbox(
                dom_label,
                ["generic", "nha_thuoc_an_tam", "cafe_pho_viet", "vlxd_minh_phat", "awesome_chocolates", "employees"],
            )

            intent_label = "Business Rule Notes (Optional):" if is_en else "Ghi chú quy tắc nghiệp vụ (Tùy chọn):"
            intent_ph = "e.g. Exclude canceled orders..." if is_en else "Ví dụ: Chỉ tính đơn Hoàn thành, không tính đơn đã hủy..."
            in_intent = st.text_input(intent_label, placeholder=intent_ph)

            sql_label = "Reference SQL Query:" if is_en else "Câu lệnh SQL chuẩn:"
            in_sql = st.text_area(sql_label, placeholder="SELECT ...", height=120)

            save_btn_label = "💾 Save Template" if is_en else "💾 Lưu mẫu truy vấn"
            btn_save = st.form_submit_button(save_btn_label, type="primary", use_container_width=True)

            if btn_save:
                if in_query.strip() and in_sql.strip():
                    new_id = save_learned_case(
                        user_query=in_query.strip(),
                        sql_query=in_sql.strip(),
                        intent_explanation=in_intent.strip(),
                        domain=in_domain,
                        source="manual_template"
                    )
                    st.success(f"✅ Saved template #{new_id}!" if is_en else f"✅ Đã lưu mẫu truy vấn #{new_id}!")
                    st.rerun()
                else:
                    st.error("Please enter both the question and SQL query." if is_en else "Vui lòng nhập đầy đủ câu hỏi và câu lệnh SQL chuẩn.")

    with tab_logs:
        st.markdown("### 📋 " + ("User Feedback & Edit History" if is_en else "Lịch sử đánh giá & chỉnh sửa"))
        if recent_logs:
            for l in recent_logs:
                evt_type = l.get("event_type", "")
                icon = "👍" if "UP" in str(evt_type).upper() else ("👎" if "DOWN" in str(evt_type).upper() else "📝")
                st.markdown(f"{icon} **[{l.get('timestamp', '')}]** — *{l.get('query_sample', '')}*: {l.get('detail', '')}")
        else:
            st.info("No feedback history recorded yet." if is_en else "Chưa có lịch sử đánh giá nào.")
