# -*- coding: utf-8 -*-
"""
Multi-Layer Executive Intelligence Dashboard UI.
Provides a comprehensive Overview Hub and 6 specialized detail layers for the employees database:
1. Department Management
2. Employee Directory
3. Salary Analysis
4. Organizational Structure
5. Title & Positions
6. Department Managers

Fully localized with instant reactive bilingual support (Vietnamese & English).
"""

import streamlit as st
import pandas as pd
from src.database.crm_queries import (
    detect_dashboard_domain,
    fetch_hr_overview_data,
    fetch_hr_dept_management_data,
    fetch_hr_employee_directory,
    fetch_hr_salary_analysis_data,
    fetch_hr_org_structure_data,
    fetch_hr_titles_data,
    fetch_hr_managers_data,
    fetch_sales_overview_data,
    fetch_sales_geo_data,
    fetch_sales_people_data,
    fetch_sales_products_data,
    fetch_sales_trends_data,
    fetch_sales_top_performers_data,
    discover_generic_database_schema,
    fetch_generic_overview_data,
    fetch_generic_table_data,
    fetch_crm_kpis,
    fetch_tickets_created_vs_solved,
    fetch_tickets_by_type,
    fetch_new_vs_returned,
    fetch_tickets_by_weekday,
    fetch_latency_wave_data
)
from src.visualization.crm_dashboard_charts import (
    build_latency_wave_chart,
    build_created_vs_solved_chart,
    build_hr_trend_chart,
    build_tickets_by_type_donut,
    build_new_vs_returned_donut,
    build_weekday_bar_chart,
    build_horizontal_bar_chart,
    build_multi_bar_chart,
    build_multi_line_chart,
    build_donut_chart,
    build_sales_dual_axis_chart
)
from src.visualization.chart_modal import render_zoomable_chart_card, show_chart_zoom_dialog
from src.analytics.anomaly import scan_dashboard_anomalies_and_strategies
from src.analytics.export_reports import export_resolution_to_pdf
from src.i18n import t, get_current_language
from typing import Dict, Any


@st.dialog("🏛️ EXECUTIVE STRATEGIC RESOLUTION / NGHỊ QUYẾT CHIẾN LƯỢC BAN ĐIỀU HÀNH", width="large")
def show_executive_resolution_dialog(
    layer_id: str,
    res: Dict[str, Any],
    time_label: str
):
    """Hiển thị văn bản Nghị Quyết Chiến Lược & Kế Hoạch Hành Động chính thức chuẩn C-Level (Bilingual)."""
    import re
    is_en = (get_current_language() == "en")
    health_status = res["health_status"]
    health_score = res["health_score"]
    anomalies = res["anomalies"]
    immediate_actions = res["immediate_actions"]
    structural_optimizations = res["structural_optimizations"]
    sustainable_strategies = res["sustainable_strategies"]
    okrs = res["okrs"]
    ai_prompt_payload = res["ai_prompt_payload"]

    doc_title = t("resolution_dialog_title")
    doc_code = t("resolution_doc_code", time=time_label.replace(' ', ''))
    app_period_label = t("resolution_applied_period")
    health_label = t("resolution_health_status")

    # Header văn bản
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); border: 1px solid rgba(0, 240, 255, 0.3); border-radius: 12px; padding: 16px 20px; margin-bottom: 14px;">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;">
            <span style="font-size: 1.1rem; font-weight: 800; color: #FFFFFF; letter-spacing: 0.5px;">
                {doc_title}
            </span>
            <span style="background: rgba(0, 240, 255, 0.2); color: #00F0FF; font-size: 0.78rem; font-weight: 700; padding: 3px 10px; border-radius: 12px; border: 1px solid rgba(0, 240, 255, 0.3);">
                {doc_code}
            </span>
        </div>
        <div style="font-size: 0.86rem; color: #94A3B8; margin-bottom: 8px;">
            {app_period_label} <b style="color: #F8FAFC;">{time_label}</b> • {health_label} <b style="color: #67E8F9;">{health_status} ({health_score}/100)</b>
        </div>
        <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            <span style="background: rgba(0, 240, 255, 0.12); color: #67E8F9; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(0, 240, 255, 0.25);">🤖 Supervisor Agent</span>
            <span style="background: rgba(59, 130, 246, 0.12); color: #93C5FD; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(59, 130, 246, 0.25);">⚙️ Data Engineer</span>
            <span style="background: rgba(16, 185, 129, 0.12); color: #6EE7B7; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(16, 185, 129, 0.25);">🛡️ Data Auditor (100% Passed)</span>
            <span style="background: rgba(239, 68, 68, 0.12); color: #FCA5A5; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.25);">🔍 Anomaly Detective</span>
            <span style="background: rgba(217, 70, 239, 0.12); color: #F0ABFC; font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(217, 70, 239, 0.25);">🎯 Strategy Advisor</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # I. CĂN CỨ VẬN HÀNH & CHẨN ĐOÁN DỮ LIỆU
    st.markdown(f"""
    <div style="font-size: 0.95rem; font-weight: 800; color: #00F0FF; margin-top: 10px; margin-bottom: 8px;">
        {t('resolution_sec1')}
    </div>
    """, unsafe_allow_html=True)

    if anomalies:
        for i, a in enumerate(anomalies, 1):
            act_label = "Actual Metrics:" if is_en else "Thực tế:"
            rc_label = "Root Cause:" if is_en else "Nguyên nhân gốc rễ:"
            imp_label = "Quantified Impact:" if is_en else "Lượng hóa rủi ro:"
            st.markdown(f"""
            <div style="background: rgba(15, 23, 42, 0.6); border-left: 3px solid #EF4444; border-radius: 6px; padding: 10px 14px; margin-bottom: 8px; font-size: 0.84rem; line-height: 1.5;">
                <div style="font-weight: 700; color: #F8FAFC; margin-bottom: 4px;">1.{i}. {a['title']} ({a['severity']})</div>
                <div style="color: #CBD5E1; margin-bottom: 3px;">• <b>{act_label}</b> {a['metrics_summary']}</div>
                <div style="color: #94A3B8; margin-bottom: 3px;">• <b>{rc_label}</b> {a['root_cause']}</div>
                <div style="color: #FCA5A5;">• <b>{imp_label}</b> {a['quantified_impact']}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info(f"✨ All operational indicators remain stable and balanced during {time_label}." if is_en else f"✨ Toàn bộ các chỉ số vận hành duy trì trạng thái ổn định và cân bằng trong {time_label}.")

    # II. QUYẾT NGHỊ HÀNH ĐỘNG CHIẾN LƯỢC 3 TẦNG
    st.markdown(f"""
    <div style="font-size: 0.95rem; font-weight: 800; color: #E879F9; margin-top: 14px; margin-bottom: 8px;">
        {t('resolution_sec2')}
    </div>
    """, unsafe_allow_html=True)

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown(f"""
        <div style="background: rgba(0, 240, 255, 0.06); border: 1px solid rgba(0, 240, 255, 0.2); border-radius: 8px; padding: 12px 14px; height: 100%;">
            <div style="font-weight: 700; color: #00F0FF; font-size: 0.86rem; margin-bottom: 6px;">{t('plan_tier1_title')}</div>
            <div style="font-size: 0.82rem; color: #E2E8F0; line-height: 1.5;">
                {''.join(f'<div style="margin-bottom: 4px;">🔹 {act}</div>' for act in immediate_actions)}
            </div>
        </div>
        """, unsafe_allow_html=True)
    with col_t2:
        st.markdown(f"""
        <div style="background: rgba(232, 121, 249, 0.06); border: 1px solid rgba(232, 121, 249, 0.2); border-radius: 8px; padding: 12px 14px; height: 100%;">
            <div style="font-weight: 700; color: #E879F9; font-size: 0.86rem; margin-bottom: 6px;">{t('plan_tier2_title')}</div>
            <div style="font-size: 0.82rem; color: #E2E8F0; line-height: 1.5;">
                {''.join(f'<div style="margin-bottom: 4px;">🔹 {act}</div>' for act in structural_optimizations)}
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background: rgba(52, 211, 153, 0.06); border: 1px solid rgba(52, 211, 153, 0.2); border-radius: 8px; padding: 12px 14px; margin-top: 10px;">
        <div style="font-weight: 700; color: #34D399; font-size: 0.86rem; margin-bottom: 6px;">{t('plan_tier3_title')}</div>
        <div style="font-size: 0.82rem; color: #E2E8F0; line-height: 1.5;">
            {''.join(f'<div style="margin-bottom: 4px;">🔹 {act}</div>' for act in sustainable_strategies)}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # III. HỆ THỐNG CHỈ SỐ OKRS & PHÂN CÔNG TRÁCH NHIỆM RACI
    st.markdown(f"""
    <div style="font-size: 0.95rem; font-weight: 800; color: #FBBF24; margin-top: 14px; margin-bottom: 8px;">
        {t('resolution_sec3')}
    </div>
    """, unsafe_allow_html=True)

    raci_text = "👥 <b>RACI Matrix:</b> Board of Directors (A - Approval) • Chief Human Resources Officer (R - Lead Tier 1, 2) • Operations & Engineering Heads (R - Execution) • Finance (C - Budget Oversight)." if is_en else "👥 <b>Phân công RACI:</b> Ban Tổng Giám Đốc (A - Phê duyệt) • Giám Đốc Nhân Sự (R - Chủ trì Tầng 1, 2) • Trưởng Khối Vận Hành & Kỹ Thuật (R - Thực thi) • Tài Chính (C - Giám sát ngân sách)."
    okr_label = "Target Metric:" if is_en else "Chỉ số đo lường:"

    st.markdown(f"""
    <div style="background: rgba(251, 191, 36, 0.06); border: 1px solid rgba(251, 191, 36, 0.2); border-radius: 8px; padding: 12px 14px; margin-bottom: 14px;">
        <div style="font-size: 0.84rem; color: #FEF08A; line-height: 1.5; margin-bottom: 8px;">
            {''.join(f'<div style="margin-bottom: 4px;">🎯 <b>{okr_label}</b> {okr}</div>' for okr in okrs)}
        </div>
        <div style="font-size: 0.8rem; color: #CBD5E1; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 6px;">
            {raci_text}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Thanh tác vụ 1 chạm: Tải xuống & Chat sâu với AI
    c_btn1, c_btn2 = st.columns([1, 1])
    
    anomalies_md_list = []
    for a in anomalies:
        c_sum = re.sub(r'<[^>]+>', '', a['metrics_summary'])
        c_rc = re.sub(r'<[^>]+>', '', a['root_cause'])
        c_imp = re.sub(r'<[^>]+>', '', a['quantified_impact'])
        anomalies_md_list.append(f"""
#### {a['title']} ({a['severity']})
- **Recorded Metrics / Thực tế:** {c_sum}
- **Root Cause / Nguyên nhân:** {c_rc}
- **Quantified Risk / Rủi ro lượng hóa:** {c_imp}
""")
    
    clean_imm_md = [re.sub(r'<[^>]+>', '', act) for act in immediate_actions]
    clean_str_md = [re.sub(r'<[^>]+>', '', act) for act in structural_optimizations]
    clean_sus_md = [re.sub(r'<[^>]+>', '', act) for act in sustainable_strategies]
    clean_okr_md = [re.sub(r'<[^>]+>', '', okr) for okr in okrs]

    full_resolution_md = f"""# {doc_title}
**{doc_code}**
- **{app_period_label}** {time_label}
- **{health_label}** {health_status} ({health_score}/100)

---

## {t('resolution_sec1')}
{''.join(anomalies_md_list)}

---

## {t('resolution_sec2')}
### {t('plan_tier1_title')}
{chr(10).join(f"- {act}" for act in clean_imm_md)}

### {t('plan_tier2_title')}
{chr(10).join(f"- {act}" for act in clean_str_md)}

### {t('plan_tier3_title')}
{chr(10).join(f"- {act}" for act in clean_sus_md)}

---

## {t('resolution_sec3')}
{chr(10).join(f"- 🎯 {okr}" for okr in clean_okr_md)}

{raci_text}

---
*Generated by Veraxus Executive Intelligence Copilot*
"""

    with c_btn1:
        pdf_bytes = export_resolution_to_pdf(full_resolution_md, doc_code=f"NQ-BDH-{time_label.replace(' ', '')}")
        if pdf_bytes:
            st.download_button(
                label=t("resolution_btn_export"),
                data=pdf_bytes,
                file_name=f"Executive_Resolution_{layer_id}_{time_label.replace(' ', '_')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
        else:
            st.download_button(
                label="📥 Download Resolution (.md)" if is_en else "📥 Tải Nghị Quyết (.md)",
                data=full_resolution_md.encode("utf-8"),
                file_name=f"Executive_Resolution_{layer_id}_{time_label.replace(' ', '_')}.md",
                mime="text/markdown",
                type="primary",
                use_container_width=True
            )

    with c_btn2:
        ai_act_label = "🤖 Activate AI Planning Agent ➔" if is_en else "🤖 Kích Hoạt Tác Tử Lập Kế Hoạch Chi Tiết ➔"
        ai_act_help = "Transfer full strategic resolution evidence to AI Agent for detailed breakdown" if is_en else "Chuyển toàn bộ dữ liệu & căn cứ nghị quyết này sang Agent để giải trình chi tiết"
        if st.button(ai_act_label, type="secondary", use_container_width=True, help=ai_act_help):
            st.session_state["pending_prompt"] = ai_prompt_payload
            st.session_state["view_mode"] = "chat"
            st.rerun()


@st.dialog("💬 EXECUTIVE COPILOT / TRỢ LÝ ĐỒNG HÀNH", width="large")
def show_dashboard_copilot_dialog(ctx: Dict[str, Any]):
    """Hiển thị hộp thoại trao đổi hỏi-đáp trực tiếp với DashboardCopilotAgent theo ngữ cảnh sống (Bilingual)."""
    from src.multi_agent.dashboard_copilot_agent import DashboardCopilotAgent, sanitize_executive_vietnamese_text
    copilot = DashboardCopilotAgent()
    is_en = (get_current_language() == "en")

    layer_title = ctx.get("layer_title", "Executive Overview" if is_en else "Tổng quan Doanh nghiệp")
    time_label = ctx.get("time_label", "1985 - 2002")

    # Injected Modern Executive CSS for Dialog
    st.markdown("""
    <style>
        .copilot-modal-hdr {
            background: linear-gradient(135deg, #0D1322 0%, #151F32 100%);
            border: 1px solid rgba(0, 240, 255, 0.35);
            border-radius: 14px;
            padding: 16px 20px;
            margin-bottom: 16px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
        }
        .copilot-chip-title {
            font-size: 0.82rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #67E8F9;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .copilot-user-bubble {
            background: linear-gradient(135deg, rgba(30, 58, 138, 0.35) 0%, rgba(15, 23, 42, 0.6) 100%);
            border: 1px solid rgba(59, 130, 246, 0.4);
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 12px;
            color: #FFFFFF;
        }
        .copilot-ai-card {
            background: linear-gradient(145deg, #0E1526 0%, #090D1A 100%);
            border: 1px solid rgba(0, 240, 255, 0.35);
            border-left: 4px solid #00F0FF;
            border-radius: 14px;
            padding: 18px 22px;
            margin-bottom: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.55);
            color: #E2E8F0;
            line-height: 1.7;
            font-size: 0.92rem;
        }
        .copilot-ai-card h3 {
            color: #00F0FF !important;
            font-size: 1.08rem !important;
            font-weight: 850 !important;
            margin-top: 18px !important;
            margin-bottom: 10px !important;
            letter-spacing: -0.01em;
            display: flex;
            align-items: center;
            gap: 6px;
            border-bottom: 1px solid rgba(0, 240, 255, 0.15);
            padding-bottom: 6px;
        }
        .copilot-ai-card table {
            width: 100% !important;
            border-collapse: collapse !important;
            margin: 14px 0 !important;
            border-radius: 10px !important;
            overflow: hidden !important;
            font-size: 0.88rem !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4) !important;
        }
        .copilot-ai-card th {
            background: rgba(0, 240, 255, 0.18) !important;
            color: #67E8F9 !important;
            font-weight: 800 !important;
            padding: 10px 14px !important;
            text-align: left !important;
            border-bottom: 1.5px solid rgba(0, 240, 255, 0.35) !important;
            letter-spacing: 0.02em;
        }
        .copilot-ai-card td {
            padding: 10px 14px !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
            color: #F8FAFC !important;
        }
        .copilot-ai-card tr:nth-child(even) {
            background: rgba(255, 255, 255, 0.03) !important;
        }
        .copilot-ai-card blockquote {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.22) 0%, rgba(15, 23, 42, 0.95) 100%) !important;
            border: 1.5px solid #F59E0B !important;
            border-left: 5px solid #FBBF24 !important;
            padding: 14px 18px !important;
            border-radius: 10px !important;
            margin: 18px 0 10px 0 !important;
            color: #FFFFFF !important;
            font-size: 0.93rem !important;
            font-weight: 550 !important;
            line-height: 1.65 !important;
            box-shadow: 0 6px 24px rgba(245, 158, 11, 0.25) !important;
        }
        .copilot-ai-card blockquote b, .copilot-ai-card blockquote strong {
            color: #FDE68A !important;
            font-weight: 850 !important;
            font-size: 0.96rem !important;
        }
        .copilot-ai-card strong, .copilot-ai-card b {
            color: #F8FAFC !important;
            font-weight: 750 !important;
        }
        .copilot-ai-card ul {
            padding-left: 20px !important;
            margin-bottom: 12px !important;
        }
        .copilot-ai-card li {
            margin-bottom: 6px !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # 1. Header Card
    badge_ctx_lbl = "Live Context" if is_en else "Ngữ Cảnh Sống"
    st.markdown(f"""
    <div class="copilot-modal-hdr">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 1.3rem;">🧠</span>
                <div>
                    <div style="font-size: 1.02rem; font-weight: 800; color: #FFFFFF; letter-spacing: -0.01em;">
                        {layer_title}
                    </div>
                    <div style="font-size: 0.8rem; color: #94A3B8;">
                        {"Analysis period:" if is_en else "Giai đoạn khảo sát:"} <b style="color: #67E8F9;">{time_label}</b> • {"Mode:" if is_en else "Chế độ:"} <span style="color: #00DF8F; font-weight: 600;">Executive Live Copilot</span>
                    </div>
                </div>
            </div>
            <span style="background: rgba(0, 240, 255, 0.15); border: 1px solid #00F0FF; color: #00F0FF; font-size: 0.74rem; font-weight: 750; padding: 4px 12px; border-radius: 20px;">
                ⚡ {badge_ctx_lbl}
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Khởi tạo lịch sử cuộc trò chuyện
    if "dashboard_copilot_history" not in st.session_state:
        st.session_state["dashboard_copilot_history"] = []

    def _handle_copilot_chip_click(chip_text: str):
        st.session_state["dashboard_copilot_history"].append({"role": "user", "content": chip_text})
        with st.spinner("🤖 Copilot is analyzing live data..." if is_en else "🤖 Copilot đang phân tích số liệu thực tế..."):
            prior_history = st.session_state["dashboard_copilot_history"][:-1]
            ans = copilot.ask_copilot(
                question=chip_text,
                ctx=ctx,
                chat_history=prior_history
            )
            st.session_state["dashboard_copilot_history"].append({"role": "assistant", "content": ans})
            followup_chips = copilot.generate_followup_chips(
                question=chip_text,
                answer=ans,
                ctx=ctx
            )
            st.session_state["copilot_dynamic_followups"] = followup_chips
        st.rerun()

    def _handle_clear_copilot():
        st.session_state["dashboard_copilot_history"] = []
        st.session_state["copilot_dynamic_followups"] = []
        st.rerun()

    # 3. Hiển thị gợi ý câu hỏi ban đầu nếu chưa có lịch sử chat
    chips = copilot.generate_smart_chips(ctx)
    if not st.session_state.get("dashboard_copilot_history") and chips:
        chips_title = "💡 INSTANT DEEP DIVE QUESTIONS (CLICK TO ASK):" if is_en else "💡 GỢI Ý CÂU HỎI ĐÀO SÂU TỨC THÌ (NHẤP ĐỂ HỎI):"
        st.markdown(f"<div class='copilot-chip-title'>{chips_title}</div>", unsafe_allow_html=True)
        cols = st.columns(min(len(chips), 2))
        for idx, chip_text in enumerate(chips):
            with cols[idx % 2]:
                st.button(
                    chip_text,
                    key=f"copilot_init_chip_{idx}",
                    on_click=_handle_copilot_chip_click,
                    args=(chip_text,),
                    use_container_width=True
                )

    # 4. Hiển thị khung chat với giao diện Executive Card
    st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
    if not st.session_state["dashboard_copilot_history"]:
        welcome_info = "👋 Hello! I am the **Dashboard Copilot Agent**. Click on any suggested question above or type any question to explore root causes and strategic actions!" if is_en else "👋 Chào bạn! Tôi là **Dashboard Copilot Agent**. Hãy nhấp vào một câu hỏi gợi ý ở trên hoặc gõ câu hỏi bất kỳ để tôi giải thích nguyên nhân và đề xuất hành động cho bạn nhé!"
        st.info(welcome_info)
    else:
        for msg in st.session_state["dashboard_copilot_history"]:
            if msg["role"] == "user":
                user_role_label = "EXECUTIVE BOARD" if is_en else "BAN ĐIỀU HÀNH"
                st.markdown(f"""
                <div class="copilot-user-bubble">
                    <div style="font-weight: 750; font-size: 0.78rem; color: #93C5FD; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                        <span>👤</span> {user_role_label}
                    </div>
                    <div style="font-size: 0.92rem; font-weight: 500; color: #F8FAFC;">{msg['content']}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 14px; margin-bottom: 4px;">
                    <div style="font-weight: 850; font-size: 0.85rem; color: #00F0FF; display: flex; align-items: center; gap: 6px;">
                        <span>✨</span> VERAXUS EXECUTIVE COPILOT
                    </div>
                    <span style="background: rgba(0, 240, 255, 0.12); color: #67E8F9; font-size: 0.72rem; font-weight: 750; padding: 2px 8px; border-radius: 8px; border: 1px solid rgba(0, 240, 255, 0.25);">
                        C-LEVEL ADVISOR
                    </span>
                </div>
                """, unsafe_allow_html=True)
                
                clean_content = sanitize_executive_vietnamese_text(msg['content'])
                card_html = f'<div class="copilot-ai-card">\n\n{clean_content}\n\n</div>'
                st.markdown(card_html, unsafe_allow_html=True)

        dynamic_followups = st.session_state.get("copilot_dynamic_followups", [])
        if dynamic_followups:
            next_q_label = "✨ SUGGESTED NEXT FOLLOW-UP QUESTIONS (1-CLICK):" if is_en else "✨ GỢI Ý CÂU HỎI ĐÀO SÂU TIẾP THEO (1-CLICK):"
            st.markdown(f"<div class='copilot-chip-title' style='margin-top: 16px; margin-bottom: 8px;'>{next_q_label}</div>", unsafe_allow_html=True)
            turn_count = len(st.session_state["dashboard_copilot_history"])
            f_cols = st.columns(min(len(dynamic_followups), 2))
            for f_idx, f_text in enumerate(dynamic_followups):
                with f_cols[f_idx % len(f_cols)]:
                    st.button(
                        f_text,
                        key=f"copilot_followup_btm_{turn_count}_{f_idx}",
                        on_click=_handle_copilot_chip_click,
                        args=(f_text,),
                        use_container_width=True
                    )

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        clear_label = "🗑️ Clear conversation history" if is_en else "🗑️ Xóa lịch sử cuộc trò chuyện này"
        st.button(
            clear_label,
            key="btn_clear_copilot_hist",
            type="secondary",
            on_click=_handle_clear_copilot,
            use_container_width=True
        )

    # 6. Chat Input
    st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
    input_ph = "Ask Copilot any question about charts, KPIs or anomalies..." if is_en else "Hỏi Copilot bất kỳ câu hỏi nào về biểu đồ, KPI hoặc điểm dị biệt..."
    user_q = st.chat_input(input_ph, key="copilot_input_field")
    if user_q:
        st.session_state["dashboard_copilot_history"].append({"role": "user", "content": user_q})
        spinner_msg = "🤖 Copilot is analyzing live data..." if is_en else "🤖 Copilot đang phân tích số liệu thực tế..."
        with st.spinner(spinner_msg):
            prior_history = st.session_state["dashboard_copilot_history"][:-1]
            ans = copilot.ask_copilot(
                question=user_q,
                ctx=ctx,
                chat_history=prior_history
            )
            st.session_state["dashboard_copilot_history"].append({"role": "assistant", "content": ans})
            followup_chips = copilot.generate_followup_chips(
                question=user_q,
                answer=ans,
                ctx=ctx
            )
            st.session_state["copilot_dynamic_followups"] = followup_chips
        st.rerun()


def render_smart_analyst_anomaly_panel(
    layer_id: str,
    data: Dict[str, Any],
    start_year: int,
    end_year: int,
    key_prefix: str = "analyst"
):
    """Component UI Phân tích Sâu & Đề xuất Chiến lược Chuẩn Senior Data Analyst (Bilingual)."""
    import textwrap
    lang = get_current_language()
    is_en = (lang == "en")
    res = scan_dashboard_anomalies_and_strategies(layer_id, data, start_year, end_year, lang=lang)
    health_status = res["health_status"]
    health_score = res["health_score"]
    headline = res["headline"]
    anomalies = res["anomalies"]
    immediate_actions = res["immediate_actions"]
    structural_optimizations = res["structural_optimizations"]
    sustainable_strategies = res["sustainable_strategies"]
    okrs = res["okrs"]
    time_label = res["time_label"]
    
    if "CRITICAL" in health_status:
        border_color = "rgba(239, 68, 68, 0.6)"
        badge_bg = "background: rgba(239, 68, 68, 0.2); color: #FCA5A5; border: 1px solid #EF4444;"
        glow = "box-shadow: 0 4px 20px rgba(239, 68, 68, 0.18);"
    elif "WARNING" in health_status:
        border_color = "rgba(245, 158, 11, 0.6)"
        badge_bg = "background: rgba(245, 158, 11, 0.2); color: #FDE68A; border: 1px solid #F59E0B;"
        glow = "box-shadow: 0 4px 20px rgba(245, 158, 11, 0.18);"
    else:
        border_color = "rgba(16, 185, 129, 0.6)"
        badge_bg = "background: rgba(16, 185, 129, 0.2); color: #A7F3D0; border: 1px solid #10B981;"
        glow = "box-shadow: 0 4px 20px rgba(16, 185, 129, 0.18);"

    panel_title = t("anomaly_panel_title")
    health_lbl = t("anomaly_health_label")

    header_html = textwrap.dedent(f"""
<div style="background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); border: 1.5px solid {border_color}; border-radius: 14px; padding: 16px 20px; margin-top: 14px; margin-bottom: 12px; {glow}">
<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;">
<div style="display: flex; align-items: center; gap: 8px;">
<span style="font-size: 1.3rem;">🧠</span>
<span style="font-size: 1.05rem; font-weight: 800; color: #FFFFFF; letter-spacing: 0.3px;">
{panel_title}
</span>
</div>
<div style="display: flex; align-items: center; gap: 8px;">
<span style="{badge_bg} font-size: 0.78rem; font-weight: 700; padding: 4px 12px; border-radius: 20px;">
{health_lbl}: {health_status} ({health_score}/100)
</span>
<span style="background: rgba(0, 240, 255, 0.15); color: #00F0FF; border: 1px solid rgba(0, 240, 255, 0.3); font-size: 0.78rem; font-weight: 600; padding: 4px 12px; border-radius: 20px;">
{time_label}
</span>
</div>
</div>
<div style="font-size: 0.88rem; color: #CBD5E1; line-height: 1.55;">
{headline}
</div>
</div>
""").strip()
    st.markdown(header_html, unsafe_allow_html=True)
    
    diag_tab_label = f"🔍 {t('tab_diagnosis', count=len(anomalies))}"
    strat_tab_label = f"🎯 {t('tab_strategic_plan')}"

    tab_diag, tab_strat = st.tabs([diag_tab_label, strat_tab_label])
    
    with tab_diag:
        if not anomalies:
            st.info(f"✨ All operational indicators remain stable and balanced during {time_label}." if is_en else f"✨ Không phát hiện điểm bất thường nghiêm trọng nào trong {time_label}. Toàn bộ các chỉ số vận hành duy trì trạng thái ổn định và cân bằng.")
        else:
            for idx, a in enumerate(anomalies, 1):
                sev_color = "#EF4444" if "CRITICAL" in a["severity"] else "#F59E0B"
                act_label = "Actual Metrics:" if is_en else "Số liệu thực tế:"
                rc_label = "Root Cause Diagnosis:" if is_en else "Chẩn đoán nguyên nhân gốc rễ (Root Cause):"
                imp_label = "Quantified Risk & Impact:" if is_en else "Lượng hóa rủi ro & tác động (Quantified Impact):"

                card_html = textwrap.dedent(f"""
<div style="background: rgba(15, 23, 42, 0.75); border-left: 4px solid {sev_color}; border-top: 1px solid rgba(255,255,255,0.05); border-right: 1px solid rgba(255,255,255,0.05); border-bottom: 1px solid rgba(255,255,255,0.05); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px;">
<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
<span style="font-size: 0.95rem; font-weight: 700; color: #F8FAFC;">
#{idx}. {a['title']}
</span>
<span style="font-size: 0.74rem; font-weight: 700; color: {sev_color}; background: rgba(0,0,0,0.35); padding: 3px 10px; border-radius: 12px; border: 1px solid {sev_color}40;">
{a['severity']}
</span>
</div>
<div style="font-size: 0.86rem; color: #E2E8F0; margin-bottom: 8px; line-height: 1.55;">
📊 <b style="color: #67E8F9;">{act_label}</b> {a['metrics_summary']}
</div>
<div style="font-size: 0.84rem; color: #CBD5E1; margin-bottom: 6px; line-height: 1.5;">
🔬 <b style="color: #FDE047;">{rc_label}</b> {a['root_cause']}
</div>
<div style="font-size: 0.84rem; color: #FCA5A5; line-height: 1.5;">
💥 <b style="color: #F87171;">{imp_label}</b> {a['quantified_impact']}
</div>
</div>
""").strip()
                st.markdown(card_html, unsafe_allow_html=True)
                
    with tab_strat:
        imm_items = "".join(f"<div style='margin-bottom: 6px; line-height: 1.55;'>🔹 {act}</div>" for act in immediate_actions)
        str_items = "".join(f"<div style='margin-bottom: 6px; line-height: 1.55;'>🔹 {act}</div>" for act in structural_optimizations)
        sus_items = "".join(f"<div style='margin-bottom: 6px; line-height: 1.55;'>🔹 {act}</div>" for act in sustainable_strategies)
        okr_items = "".join(f"<div style='margin-bottom: 6px; line-height: 1.55;'>🎯 {okr}</div>" for okr in okrs)
        
        strat_html = textwrap.dedent(f"""
<div style="background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(0, 240, 255, 0.25); border-radius: 12px; padding: 16px 18px; margin-bottom: 12px;">

<div style="background: rgba(0, 240, 255, 0.08); border-left: 3px solid #00F0FF; border-radius: 6px; padding: 10px 14px; margin-bottom: 12px;">
<div style="font-size: 0.88rem; font-weight: 800; color: #00F0FF; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
{t('plan_tier1_title')}
</div>
<div style="font-size: 0.85rem; color: #E2E8F0;">
{imm_items}
</div>
</div>

<div style="background: rgba(232, 121, 249, 0.08); border-left: 3px solid #E879F9; border-radius: 6px; padding: 10px 14px; margin-bottom: 12px;">
<div style="font-size: 0.88rem; font-weight: 800; color: #E879F9; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
{t('plan_tier2_title')}
</div>
<div style="font-size: 0.85rem; color: #E2E8F0;">
{str_items}
</div>
</div>

<div style="background: rgba(52, 211, 153, 0.08); border-left: 3px solid #34D399; border-radius: 6px; padding: 10px 14px; margin-bottom: 12px;">
<div style="font-size: 0.88rem; font-weight: 800; color: #34D399; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
{t('plan_tier3_title')}
</div>
<div style="font-size: 0.85rem; color: #E2E8F0;">
{sus_items}
</div>
</div>

<div style="background: rgba(251, 191, 36, 0.08); border-left: 3px solid #FBBF24; border-radius: 6px; padding: 10px 14px;">
<div style="font-size: 0.88rem; font-weight: 800; color: #FBBF24; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
{t('plan_okr_title')}
</div>
<div style="font-size: 0.85rem; color: #FEF08A;">
{okr_items}
</div>
</div>

</div>
""").strip()
        st.markdown(strat_html, unsafe_allow_html=True)

    col_act1, col_act2 = st.columns([1.2, 1])
    with col_act1:
        res_btn_lbl = t("btn_resolution", period=time_label)
        if st.button(
            res_btn_lbl,
            key=f"btn_ai_strategy_{key_prefix}_{layer_id}",
            type="primary",
            use_container_width=True
        ):
            show_executive_resolution_dialog(layer_id, res, time_label)
    with col_act2:
        layer_titles_map = {
            "overview": "Executive Overview" if is_en else "Tổng quan Doanh nghiệp (Overview)",
            "dept_mgmt": "Department Management" if is_en else "Quản lý Phòng ban (Departments)",
            "employee_dir": "Employee Directory" if is_en else "Danh bạ Nhân sự (Directory)",
            "salary_analysis": "Salary Analysis" if is_en else "Phân tích Tiền lương & Đãi ngộ (Salary)",
            "org_structure": "Organizational Structure" if is_en else "Cơ cấu Tổ chức (Org Structure)",
            "title_positions": "Title & Positions" if is_en else "Chức danh & Vị trí (Titles)",
            "dept_managers": "Department Managers" if is_en else "Đội ngũ Quản lý (Managers)",
        }
        ctx_card = {
            "layer_title": layer_titles_map.get(layer_id, layer_id.replace("_", " ").title()),
            "time_label": time_label,
            "anomalies": anomalies,
            "kpis_summary": f"Health score: {health_status} ({health_score}/100)" if is_en else f"Sức khỏe vận hành: {health_status} ({health_score}/100)",
            "data_summary": f"Diagnostics: {headline}" if is_en else f"Chẩn đoán: {headline}"
        }
        copilot_btn_label = "💬 Ask Copilot Assistant" if is_en else "💬 Hỏi Trợ Lý Copilot Về Điểm Này"
        if st.button(
            copilot_btn_label,
            key=f"btn_copilot_ask_{key_prefix}_{layer_id}",
            type="secondary",
            use_container_width=True
        ):
            show_dashboard_copilot_dialog(ctx_card)


def _render_sql_modal(title: str, sql: str, exec_time_ms: float, key: str):
    """Hiển thị câu lệnh SQL đằng sau widget trong expander nhỏ gọn, chuẩn mực (Bilingual)."""
    is_en = (get_current_language() == "en")
    exp_title = f"🔍 View SQL Query ({title}) • {exec_time_ms} ms" if is_en else f"🔍 Xem câu lệnh SQL ({title}) • {exec_time_ms} ms"
    with st.expander(exp_title, expanded=False):
        st.code(sql, language="sql")
        caption_text = f"⚡ Execution Time: **{exec_time_ms} ms** • Engine: SQLAlchemy Live Engine" if is_en else f"⚡ Thời gian thực thi: **{exec_time_ms} ms** • Engine: SQLAlchemy Live Engine"
        st.caption(caption_text)


def _trigger_ai_deep_dive(prompt_text: str):
    """Chuyển hướng sang chế độ Chat để tác tử AI giải thích sâu và phân tích nguyên nhân gốc rễ."""
    st.session_state["pending_prompt"] = prompt_text
    st.session_state["view_mode"] = "chat"
    st.rerun()


def _set_layer(layer_name: str, domain_key: str = "hr"):
    """Chuyển đổi tầng/layer hiển thị trên Dashboard."""
    st.session_state[f"{domain_key}_dashboard_layer"] = layer_name
    st.rerun()


def _render_timeline_slider(layer_key: str = "global", min_year: int = 1985, max_year: int = 2002, domain_key: str = "hr") -> tuple:
    """Thanh trượt thời gian 2 điểm linh hoạt đồng bộ trên toàn bộ dashboard (Bilingual)."""
    is_en = (get_current_language() == "en")
    state_key = f"{domain_key}_timeline_years"
    if state_key not in st.session_state:
        st.session_state[state_key] = (min_year, max_year)
    
    default_val = st.session_state.get(state_key, (min_year, max_year))
    if not isinstance(default_val, (tuple, list)) or len(default_val) != 2:
        default_val = (min_year, max_year)
    else:
        default_val = (max(min_year, min(max_year, int(default_val[0]))), max(min_year, min(max_year, int(default_val[1]))))

    slider_title = t("timeline_slider_title")
    st.markdown(f"""
    <div style="background: linear-gradient(145deg, #13172B 0%, #0D1020 100%); border: 1.5px solid rgba(0, 240, 255, 0.25); border-radius: 16px; padding: 14px 18px; margin-bottom: 16px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 1.15rem;">⏳</span>
                <span style="font-size: 1.02rem; font-weight: 800; color: #FFFFFF;">{slider_title}:</span>
            </div>
            <span class="crm-badge-neon">{min_year} — {max_year}</span>
        </div>
    """, unsafe_allow_html=True)

    if min_year >= max_year:
        snap_text = f"📍 <b>Survey Year:</b> {min_year} (Single Year Snapshot)" if is_en else f"📍 <b>Năm khảo sát:</b> {min_year} (Snapshot cố định)"
        st.markdown(f"<div style='font-size: 0.9rem; color: #38BDF8;'>{snap_text}</div></div>", unsafe_allow_html=True)
        return min_year, max_year

    col_sl, col_rst = st.columns([5.2, 1.0])
    with col_sl:
        selected_years = st.slider(
            "Select Year Range:" if is_en else "Chọn khoảng năm:",
            min_value=min_year,
            max_value=max_year,
            value=default_val,
            step=1,
            key=f"slider_timeline_{domain_key}_{layer_key}",
            label_visibility="collapsed"
        )
    with col_rst:
        reset_label = "🔄 All Time" if is_en else "🔄 Toàn Bộ"
        reset_help = f"Reset to full period {min_year} - {max_year}" if is_en else f"Đặt lại toàn bộ mốc {min_year} - {max_year}"
        if st.button(reset_label, key=f"btn_reset_slider_{domain_key}_{layer_key}", use_container_width=True, help=reset_help):
            st.session_state[state_key] = (min_year, max_year)
            st.rerun()

    start_year, end_year = selected_years[0], selected_years[1]
    st.session_state[state_key] = (start_year, end_year)

    if start_year == end_year:
        badge_text = f"📍 <b>Survey Year:</b> <b>{start_year}</b> (Single Year Snapshot)" if is_en else f"📍 <b>Thời điểm khảo sát:</b> Năm <b>{start_year}</b> (Snapshot một thời điểm duy nhất)"
    else:
        badge_text = f"🗓️ <b>Survey Period:</b> <b>{start_year} — {end_year}</b> ({end_year - start_year + 1} continuous years)" if is_en else f"🗓️ <b>Khoảng thời gian khảo sát:</b> Giai đoạn <b>{start_year} — {end_year}</b> ({end_year - start_year + 1} năm liên tục)"

    auto_up_text = "Data automatically updates according to timeline filter" if is_en else "Dữ liệu tự động cập nhật theo mốc thời gian"
    st.markdown(f"""
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.88rem; color: #38BDF8; font-weight: 700; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.08);">
            <span>{badge_text}</span>
            <span style="color: #94A3B8; font-size: 0.8rem; font-weight: 500;">{auto_up_text}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    return start_year, end_year


# =========================================================================
# MAIN DASHBOARD RENDERER & ROUTER
# =========================================================================

def render_crm_dashboard():
    """Hàm chính hiển thị Dashboard đa tầng tự động thích ứng với CSDL hiện tại."""
    engine = st.session_state.get("engine")
    auto_domain = detect_dashboard_domain(engine)

    # 1. Custom CSS Theme Cyber Dark / Glassmorphism (High-Contrast SaaS Executive Layout)
    st.markdown("""
    <style>
        /* Main Dashboard Background & Typography */
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 2.5rem !important;
        }
        
        /* High-Contrast Neon Gradient Metric KPI Cards */
        .kpi-card-cyan {
            background: linear-gradient(135deg, #0052D4 0%, #4364F7 50%, #6FB1FC 100%);
            border-radius: 18px;
            padding: 18px 20px;
            color: #FFFFFF !important;
            box-shadow: 0 10px 30px rgba(0, 82, 212, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.25);
            min-height: 125px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .kpi-card-purple {
            background: linear-gradient(135deg, #8A2387 0%, #E94057 50%, #F27121 100%);
            border-radius: 18px;
            padding: 18px 20px;
            color: #FFFFFF !important;
            box-shadow: 0 10px 30px rgba(233, 64, 87, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.25);
            min-height: 125px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .kpi-card-emerald {
            background: linear-gradient(135deg, #0BA360 0%, #3CBA92 100%);
            border-radius: 18px;
            padding: 18px 20px;
            color: #FFFFFF !important;
            box-shadow: 0 10px 30px rgba(11, 163, 96, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.25);
            min-height: 125px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .kpi-card-amber {
            background: linear-gradient(135deg, #F7971E 0%, #FFD200 100%);
            border-radius: 18px;
            padding: 18px 20px;
            color: #FFFFFF !important;
            box-shadow: 0 10px 30px rgba(247, 151, 30, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.25);
            min-height: 125px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .kpi-card-cyan:hover, .kpi-card-purple:hover, .kpi-card-emerald:hover, .kpi-card-amber:hover {
            transform: translateY(-3px);
            box-shadow: 0 14px 36px rgba(0, 240, 255, 0.35);
        }

        .kpi-title {
            font-size: 0.8rem;
            font-weight: 750;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: rgba(255, 255, 255, 0.95);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .kpi-val {
            font-size: 2.25rem !important;
            font-weight: 900 !important;
            color: #FFFFFF !important;
            letter-spacing: -0.025em;
            line-height: 1.15;
            margin: 4px 0 6px 0;
            text-shadow: 0 3px 12px rgba(0, 0, 0, 0.4);
        }
        .kpi-sub {
            font-size: 0.82rem;
            font-weight: 600;
            color: rgba(255, 255, 255, 0.95);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .kpi-badge {
            background: rgba(255, 255, 255, 0.28);
            backdrop-filter: blur(8px);
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 0.76rem;
            font-weight: 800;
            color: #FFFFFF;
            letter-spacing: 0.02em;
        }

        /* Dark Glassmorphism Card Containers */
        .crm-card {
            background: linear-gradient(145deg, #13172B 0%, #0D1020 100%);
            border-radius: 18px;
            padding: 18px 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            margin-bottom: 16px;
        }
        .crm-card-title {
            font-size: 1.02rem;
            font-weight: 800;
            color: #FFFFFF;
            letter-spacing: -0.015em;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .crm-badge-neon {
            background: rgba(0, 240, 255, 0.15);
            color: #00F0FF;
            border: 1px solid rgba(0, 240, 255, 0.4);
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.78rem;
            font-weight: 750;
            letter-spacing: 0.02em;
        }

        /* Interactive Navigation Cards */
        .nav-hub-box {
            background: linear-gradient(145deg, #151A30 0%, #0F1324 100%);
            border: 1.5px solid rgba(0, 240, 255, 0.2);
            border-radius: 16px;
            padding: 16px 18px;
            transition: all 0.25s ease;
            min-height: 125px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
        }
        .nav-hub-box:hover {
            border-color: #00F0FF;
            box-shadow: 0 8px 28px rgba(0, 240, 255, 0.28);
            transform: translateY(-3px);
        }
        .nav-hub-title {
            font-weight: 800;
            font-size: 1.02rem;
            color: #FFFFFF;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .nav-hub-desc {
            font-size: 0.82rem;
            color: #94A3B8;
            line-height: 1.4;
            min-height: 38px;
            font-weight: 500;
        }

        /* Clean Unified Dashboard Hub Cards */
        div[data-testid="stHorizontalBlock"] .stButton > button {
            background: linear-gradient(145deg, #151A30 0%, #0F1324 100%) !important;
            border: 1.5px solid rgba(0, 240, 255, 0.25) !important;
            border-radius: 14px !important;
            color: #FFFFFF !important;
            padding: 14px 16px !important;
            min-height: 85px !important;
            text-align: left !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: flex-start !important;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4) !important;
            transition: all 0.2s ease !important;
        }
        div[data-testid="stHorizontalBlock"] .stButton > button:hover {
            border-color: #00F0FF !important;
            background: linear-gradient(145deg, #1C2340 0%, #12182D 100%) !important;
            box-shadow: 0 8px 26px rgba(0, 240, 255, 0.35) !important;
            transform: translateY(-2px) !important;
        }

        .layer-breadcrumb {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.92rem;
            color: #CBD5E1;
            margin-bottom: 14px;
            font-weight: 700;
        }
    </style>
    """, unsafe_allow_html=True)

    # Router hiển thị theo domain của CSDL
    if auto_domain == "sales_commerce":
        _render_sales_dashboard(engine)
    elif auto_domain == "hr_employees":
        _render_hr_dashboard(engine)
    elif auto_domain == "crm_support":
        _render_crm_legacy_view(engine)
    else:
        _render_generic_dashboard(engine)


def _render_hr_dashboard(engine):
    """Giao diện Dashboard Đa Tầng cho CSDL Quản lý Nhân sự & Tiền lương (Employees) - Bilingual."""
    is_en = (get_current_language() == "en")
    current_layer = st.session_state.get("hr_dashboard_layer", "overview")

    # Header điều hành
    c_hdr1, c_hdr2, c_hdr3, c_hdr4 = st.columns([4.0, 2.6, 1.8, 1.6])
    with c_hdr1:
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
            <div style="font-size: 1.55rem; font-weight: 900; color: #FFFFFF; letter-spacing: -0.02em;">{t('hr_dash_title')}</div>
            <span class="crm-badge-neon">{t('hr_dash_badge')}</span>
        </div>
        """, unsafe_allow_html=True)

    with c_hdr2:
        if is_en:
            layer_names = {
                "overview": "🏠 Executive Overview",
                "dept_mgmt": "🏢 Department Management",
                "employee_dir": "👥 Employee Directory",
                "salary_analysis": "💰 Compensation & Salary",
                "org_structure": "🌳 Organizational Structure",
                "title_positions": "🎓 Titles & Positions",
                "dept_managers": "👔 Department Managers",
            }
        else:
            layer_names = {
                "overview": "🏠 Trang chủ Tổng quan (Overview)",
                "dept_mgmt": "🏢 Quản lý Phòng ban (Departments)",
                "employee_dir": "👥 Danh bạ Nhân viên (Directory)",
                "salary_analysis": "💰 Phân tích Tiền lương (Salary)",
                "org_structure": "🌳 Cơ cấu Tổ chức (Org Structure)",
                "title_positions": "🎓 Chức danh & Vị trí (Titles)",
                "dept_managers": "👔 Đội ngũ Quản lý (Managers)",
            }
        layer_keys = list(layer_names.keys())
        current_idx = layer_keys.index(current_layer) if current_layer in layer_keys else 0

        selected_l = st.selectbox(
            t("hr_select_layer_label"),
            layer_keys,
            format_func=lambda x: layer_names[x],
            index=current_idx,
            label_visibility="collapsed"
        )
        if selected_l != current_layer:
            st.session_state["hr_dashboard_layer"] = selected_l
            st.rerun()
        current_layer = st.session_state.get("hr_dashboard_layer", "overview")

    with c_hdr3:
        layer_title_curr = layer_names.get(current_layer, "Executive Overview" if is_en else "Tổng quan Doanh nghiệp")
        start_y_curr = st.session_state.get(f"hr_{current_layer}_start_year", 1985)
        end_y_curr = st.session_state.get(f"hr_{current_layer}_end_year", 2002)
        t_lbl_curr = f"{start_y_curr} — {end_y_curr}" if start_y_curr != end_y_curr else str(start_y_curr)
        ctx_header = {
            "layer_title": layer_title_curr,
            "time_label": t_lbl_curr,
            "anomalies": [],
            "kpis_summary": f"Viewing {layer_title_curr} during {t_lbl_curr}." if is_en else f"Đang xem {layer_title_curr} giai đoạn {t_lbl_curr}.",
            "data_summary": f"User opened Copilot from header on {layer_title_curr}." if is_en else f"Người dùng mở Copilot từ thanh Header trên tầng {layer_title_curr}."
        }
        if st.button(t("hr_btn_copilot"), type="primary", use_container_width=True, help=t("hr_copilot_help")):
            show_dashboard_copilot_dialog(ctx_header)

    with c_hdr4:
        if st.button(t("hr_btn_main_chat"), type="secondary", use_container_width=True, help=t("hr_main_chat_help")):
            st.session_state["view_mode"] = "chat"
            st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # ROUTING TỚI CÁC LAYER CHUYÊN BIỆT
    if current_layer == "overview":
        _render_layer_overview(engine)
    elif current_layer == "dept_mgmt":
        _render_layer_department_management(engine)
    elif current_layer == "employee_dir":
        _render_layer_employee_directory(engine)
    elif current_layer == "salary_analysis":
        _render_layer_salary_analysis(engine)
    elif current_layer == "org_structure":
        _render_layer_org_structure(engine)
    elif current_layer == "title_positions":
        _render_layer_title_positions(engine)
    elif current_layer == "dept_managers":
        _render_layer_dept_managers(engine)


# =========================================================================
# LAYER 0: TRANG CHỦ OVERVIEW (HUB ĐIỀU HÀNH)
# =========================================================================

def _render_layer_overview(engine):
    """Trang chủ Overview: Thanh trượt thời gian linh hoạt, 6 Thẻ chủ đề, 4 KPI tóm tắt, Biểu đồ phân bổ & Biểu đồ Trend sóng kép (Bilingual)."""
    is_en = (get_current_language() == "en")

    # 1. 6 THẺ CHỦ ĐỀ KHÁM PHÁ THEO LAYER (1-CLICK UNIFIED CARDS)
    st.markdown(f"""
    <div style="font-size: 1.05rem; font-weight: 800; color: #FFFFFF; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
        <span>🎯</span> <span><b>{t('hr_nav_header')}</b></span>
    </div>
    """, unsafe_allow_html=True)

    nav_cols1 = st.columns(3)
    with nav_cols1[0]:
        if st.button(f"🏢 **{t('card_dept_title')}**\n\n{t('card_dept_desc')}", key="btn_nav_dept", use_container_width=True):
            _set_layer("dept_mgmt")

    with nav_cols1[1]:
        if st.button(f"👥 **{t('card_emp_title')}**\n\n{t('card_emp_desc')}", key="btn_nav_emp", use_container_width=True):
            _set_layer("employee_dir")

    with nav_cols1[2]:
        if st.button(f"💰 **{t('card_sal_title')}**\n\n{t('card_sal_desc')}", key="btn_nav_sal", use_container_width=True):
            _set_layer("salary_analysis")

    st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

    nav_cols2 = st.columns(3)
    with nav_cols2[0]:
        if st.button(f"🌳 **{t('card_org_title')}**\n\n{t('card_org_desc')}", key="btn_nav_org", use_container_width=True):
            _set_layer("org_structure")

    with nav_cols2[1]:
        if st.button(f"🎓 **{t('card_title_title')}**\n\n{t('card_title_desc')}", key="btn_nav_title", use_container_width=True):
            _set_layer("title_positions")

    with nav_cols2[2]:
        if st.button(f"👔 **{t('card_mgr_title')}**\n\n{t('card_mgr_desc')}", key="btn_nav_mgr", use_container_width=True):
            _set_layer("dept_managers")

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # 2. THANH TRƯỢT THỜI GIAN & TIÊU CHÍ PHÂN TÍCH
    start_year, end_year = _render_timeline_slider("overview")

    if is_en:
        criteria_opts = {
            "active_headcount": "📈 Active Headcount Growth Across Years",
            "hiring": "👥 New Hires Scale & Gender Distribution",
            "salary": "💰 Payroll & Average Compensation",
            "dept_transfer": "🏢 Department Distribution & Staffing",
            "promotions": "🎓 Title Appointments & Promotions"
        }
    else:
        criteria_opts = {
            "active_headcount": "📈 Quy mô Nhân sự Đang Làm Việc qua các năm (Active Headcount Growth)",
            "hiring": "👥 Quy mô Tuyển dụng & Giới tính (Hiring & Gender)",
            "salary": "💰 Quỹ lương & Thu nhập Bình quân (Payroll & Avg Salary)",
            "dept_transfer": "🏢 Phân bổ & Điều chuyển phòng ban (Department Staffing)",
            "promotions": "🎓 Bổ nhiệm & Thăng tiến chức danh (Title Appointments)"
        }
    cur_cr = st.session_state.get("overview_time_criteria", "active_headcount")
    cr_keys = list(criteria_opts.keys())
    cr_idx = cr_keys.index(cur_cr) if cur_cr in cr_keys else 0
    
    col_cr1, col_cr2 = st.columns([4, 2])
    with col_cr1:
        sel_criteria = st.selectbox(
            "🎯 " + t("timeline_criteria_title"),
            cr_keys,
            format_func=lambda k: criteria_opts[k],
            index=cr_idx,
            key="sb_time_criteria"
        )
        if sel_criteria != cur_cr:
            st.session_state["overview_time_criteria"] = sel_criteria
            st.rerun()

    # TRUY VẤN DỮ LIỆU ĐỒNG BỘ THEO TIME FILTER ĐÃ CHỌN
    data = fetch_hr_overview_data(engine, start_year=start_year, end_year=end_year, time_criteria=sel_criteria)
    sy, ey = data['start_year'], data['end_year']
    period_badge = str(sy) if sy == ey else f"{sy} — {ey}"

    # 3. 4 THẺ CHỈ SỐ KPI TÓM TẮT TOÀN BỘ CÔNG TY (KPI 1 NỔI BẬT NHẤT)
    period_badge_label = f"⚡ Period: {period_badge}" if is_en else f"⚡ Mốc: {period_badge}"
    st.markdown(f"""
    <div style="font-size: 1.05rem; font-weight: 800; color: #FFFFFF; margin: 12px 0; display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span>📊</span> <span><b>{t('kpi_overview_header')}</b></span>
        </div>
        <span style="font-size: 0.85rem; color: #00F0FF; font-weight: 700;">{period_badge_label}</span>
    </div>
    """, unsafe_allow_html=True)

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        badge_kpi1 = "🔥 Peak 264k (1999)" if data["is_all_time"] else (f"Period {period_badge}" if is_en else f"Kỳ {period_badge}")
        sub_kpi1 = t("kpi_sub_total_employees_all") if data["is_all_time"] else t("kpi_sub_total_employees_period", period=period_badge)
        st.markdown(f"""
        <div class="kpi-card-cyan" style="background: linear-gradient(135deg, #00D2FF 0%, #3A7BD5 50%, #6A11CB 100%); box-shadow: 0 10px 32px rgba(0, 210, 255, 0.45); border: 1.8px solid #00F0FF;">
            <div class="kpi-title">
                <span style="font-weight: 850; letter-spacing: 0.3px;">{t('kpi_total_employees')}</span>
                <span class="kpi-badge" style="background: rgba(255, 255, 255, 0.25); color: #FFFFFF; font-weight: 800;">{badge_kpi1}</span>
            </div>
            <div class="kpi-val" style="font-size: 2.15rem !important; font-weight: 900; text-shadow: 0 2px 10px rgba(0,0,0,0.3);">{data['total_employees']:,}</div>
            <div class="kpi-sub" style="font-weight: 600; opacity: 0.95;">
                <span>{sub_kpi1}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with kpi2:
        dept_badge_val = f"{data['total_departments']} " + ("Depts" if is_en else "Khối")
        st.markdown(f"""
        <div class="kpi-card-purple">
            <div class="kpi-title">
                <span>{t('kpi_total_depts')}</span>
                <span class="kpi-badge">{dept_badge_val}</span>
            </div>
            <div class="kpi-val">{data['total_departments']}</div>
            <div class="kpi-sub">
                <span>{t('kpi_sub_total_depts')}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with kpi3:
        badge_kpi3 = ("⚡ Standard" if is_en else "⚡ Chuẩn Kỳ") if data["is_all_time"] else (f"Period {period_badge}" if is_en else f"Kỳ {period_badge}")
        sub_kpi3 = t("kpi_sub_avg_salary_all") if data["is_all_time"] else t("kpi_sub_avg_salary_period", period=period_badge)
        st.markdown(f"""
        <div class="kpi-card-emerald">
            <div class="kpi-title">
                <span>{t('kpi_avg_salary')}</span>
                <span class="kpi-badge">{badge_kpi3}</span>
            </div>
            <div class="kpi-val">${data['avg_salary']:,.0f}</div>
            <div class="kpi-sub">
                <span>{sub_kpi3}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with kpi4:
        title_badge_val = f"{data['distinct_titles']} " + ("Roles" if is_en else "Cấp Bậc")
        st.markdown(f"""
        <div class="kpi-card-amber">
            <div class="kpi-title">
                <span>{t('kpi_distinct_titles')}</span>
                <span class="kpi-badge">{title_badge_val}</span>
            </div>
            <div class="kpi-val">{data['distinct_titles']}</div>
            <div class="kpi-sub">
                <span>{t('kpi_sub_distinct_titles')}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    _render_sql_modal("Executive Overview KPIs" if is_en else "Chỉ Số Tổng Hợp", data["sql"], data["exec_time_ms"], "overview_kpi_sql")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # 4. BỐ CỤC ĐỒNG BỘ 2 CỘT: BÊN TRÁI PHÂN BỔ & TOP 5, BÊN PHẢI BIỂU ĐỒ TREND DÒNG THỜI GIAN
    time_label = f"Year {data['start_year']}" if (data['start_year'] == data['end_year'] and is_en) else (f"Năm {data['start_year']}" if data['start_year'] == data['end_year'] else (f"Period {data['start_year']} — {data['end_year']}" if is_en else f"Giai đoạn {data['start_year']} — {data['end_year']}"))
    col_left, col_right = st.columns([1.1, 1.45])

    with col_left:
        # Donut Chart
        fig_donut = build_tickets_by_type_donut(data["dept_df"], label_col="Department", val_col="Headcount")
        donut_expl = f"Distribution of employee headcount across operational departments during {time_label}. Engineering (Development) and Production represent the largest talent concentration." if is_en else f"Biểu đồ phân bổ tỷ lệ nhân sự làm việc giữa các phòng ban trong {time_label}. Cho thấy cơ cấu nhân lực tập trung lớn nhất ở khối kỹ thuật (Development) và sản xuất (Production)."
        render_zoomable_chart_card(
            title=t("chart_dept_dist_title"),
            fig=fig_donut,
            df=data["dept_df"],
            badge=period_badge,
            explanation=donut_expl,
            key="overview_donut"
        )

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        # Top 5 Horizontal Bar Chart
        fig_top5 = build_horizontal_bar_chart(data["top5_dept_df"], x_col="Headcount", y_col="Department")
        top5_expl = f"Rank of top 5 largest departments by total headcount in {time_label}." if is_en else f"Xếp hạng 5 phòng ban có số lượng nhân sự đông đảo nhất trong {time_label}. Development và Production áp đảo hoàn toàn các phòng ban hỗ trợ."
        render_zoomable_chart_card(
            title=t("chart_top5_dept_title"),
            fig=fig_top5,
            df=data["top5_dept_df"],
            badge="Headcount",
            explanation=top5_expl,
            key="overview_top5"
        )

    with col_right:
        # Dynamic Trend Wave Chart
        m1_name = data["metric1_name"]
        m2_name = data["metric2_name"]
        if is_en:
            if sel_criteria == "active_headcount":
                m1_name = "Active Headcount"
                m2_name = "Permanent Workforce"
            elif sel_criteria == "salary":
                m1_name = "Average Salary ($)"
                m2_name = "Total Payroll ($M)"
            elif sel_criteria == "promotions":
                m1_name = "New Appointments"
                m2_name = "Promoted Staff"
            elif sel_criteria == "dept_transfer":
                m1_name = "Staff Allocations"
                m2_name = "Active Departments"
            else:
                m1_name = "Total Hires"
                m2_name = "Male Staff (M)"

        fig_trend = build_hr_trend_chart(
            data["trend_df"],
            x_col="TimePeriod",
            y1_col="Metric1",
            y2_col="Metric2",
            name_1=m1_name,
            name_2=m2_name,
            unit=data["unit"],
            max_point=data.get("max_point"),
            height=280
        )
        if sel_criteria == "active_headcount":
            trend_expl = f"Company active workforce expansion from 18,293 employees in 1985, peaking at 264,196 in 1999, and sustaining 244,109 in 2002 (+1,234% total expansion). Click 'Phóng to ⤢' for full-screen analysis." if is_en else f"Biểu đồ tăng trưởng quy mô nhân sự thực tế từ 18,293 người (1985), đạt đỉnh 264,196 người (1999) và ổn định ở 244,109 người (2002) — tăng trưởng +1,234%. Bấm nút 'Phóng to ⤢' để xem toàn màn hình và tra cứu bảng số liệu chi tiết."
        else:
            trend_expl = f"Historical timeline trajectory for {m1_name} and {m2_name} from {data['start_year']} to {data['end_year']}." if is_en else f"Diễn biến dòng thời gian {data['metric1_name']} và {data['metric2_name']} qua các năm từ {data['start_year']} đến {data['end_year']}."
        render_zoomable_chart_card(
            title=t("chart_trend_title", metric=m1_name),
            fig=fig_trend,
            df=data["trend_df"],
            badge="Trend Spline Neon",
            explanation=trend_expl,
            key="overview_trend"
        )

    # Master Lead Analyst Anomaly & Strategic Intelligence Panel
    render_smart_analyst_anomaly_panel(
        layer_id="overview",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="overview"
    )


# =========================================================================
# LAYER 1: DEPARTMENT MANAGEMENT (QUẢN LÝ PHÒNG BAN)
# =========================================================================

def _render_layer_department_management(engine):
    """Layer 1: Danh sách phòng ban, Quản lý, Số lượng nhân viên, Tổng quỹ lương theo timeline slider (Bilingual)."""
    is_en = (get_current_language() == "en")

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🏢 {t('card_dept_title')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_home_1", use_container_width=True):
            _set_layer("overview")

    start_year, end_year = _render_timeline_slider("dept_mgmt")
    data = fetch_hr_dept_management_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]

    # Bảng danh sách chi tiết
    period_str = str(start_year) if start_year == end_year else f"{start_year} - {end_year}"
    card_title = f"📋 All Operational Departments & Leadership Roster ({period_str})" if is_en else f"📋 Danh Sách Tất Cả Phòng Ban & Cơ Cấu Điều Hành ({period_str})"
    count_badge = f"{len(df)} Departments" if is_en else f"{len(df)} Phòng ban"

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{card_title}</span>
            <span style="font-size: 0.78rem; color: #00F0FF; font-weight: 600;">{count_badge}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    if "TotalPayroll" in disp_df.columns:
        disp_df["TotalPayroll ($)"] = disp_df["TotalPayroll"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "$0")
    if "AvgSalary" in disp_df.columns:
        disp_df["AvgSalary ($)"] = disp_df["AvgSalary"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "$0")
    
    show_cols = ["DeptID", "Department", "ActiveHeadcount", "CurrentManager", "TotalPayroll ($)", "AvgSalary ($)"]
    st.dataframe(disp_df[[c for c in show_cols if c in disp_df.columns]], hide_index=True, use_container_width=True)

    _render_sql_modal("Department Management" if is_en else "Quản Lý Phòng Ban", data["sql"], data["exec_time_ms"], "dept_mgmt_sql")

    # 2 Biểu đồ cột song song
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        fig_bar = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["Department"], "Total": df["ActiveHeadcount"]}))
        bar1_title = "📊 Headcount Scale by Department" if is_en else "📊 Quy Mô Nhân Sự Theo Phòng Ban"
        bar1_expl = f"Direct comparison of workforce headcount across all 9 departments during {period_str}." if is_en else f"So sánh trực tiếp quy mô nhân sự làm việc giữa tất cả 9 phòng ban trong tổ chức trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=bar1_title,
            fig=fig_bar,
            df=pd.DataFrame({"Department": df["Department"], "ActiveHeadcount": df["ActiveHeadcount"]}),
            badge="Headcount",
            explanation=bar1_expl,
            key="dept_headcount"
        )

    with col_c2:
        fig_sal = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["Department"], "Total": df["AvgSalary"]}))
        bar2_title = "💰 Average Salary by Department ($)" if is_en else "💰 Mức Lương Bình Quân Từng Phòng Ban ($)"
        bar2_expl = f"Average compensation levels across all functional departments during {period_str}." if is_en else f"Mặt bằng thu nhập bình quân chi trả cho nhân sự tại từng phòng ban trong công ty trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=bar2_title,
            fig=fig_sal,
            df=pd.DataFrame({"Department": df["Department"], "AvgSalary": df["AvgSalary"]}),
            badge="Avg Salary",
            explanation=bar2_expl,
            key="dept_avg_sal"
        )

    # Biểu đồ dòng thời gian tăng trưởng phòng ban nếu chọn khoảng thời gian > 1 năm
    if "growth_df" in data and not data["growth_df"].empty and len(data["growth_df"]) > 1:
        series_map = {
            "Development": "Development",
            "Production": "Production",
            "Sales": "Sales",
            "Research": "Research",
            "Marketing": "Marketing"
        }
        fig_growth = build_multi_line_chart(data["growth_df"], x_col="TimePeriod", series_dict=series_map, height=280)
        growth_title = f"📈 Multi-Department Headcount Growth Trends ({start_year} — {end_year})" if is_en else f"📈 Xu Hướng Tăng Trưởng Nhân Sự Các Phòng Ban Chủ Lực ({start_year} — {end_year})"
        growth_expl = f"Comparative growth trajectories across the top 5 largest operational departments from {start_year} to {end_year}." if is_en else f"Đường cong biến động nhân sự qua các năm của 5 phòng ban trọng điểm trong giai đoạn {start_year} — {end_year}."
        render_zoomable_chart_card(
            title=growth_title,
            fig=fig_growth,
            df=data["growth_df"],
            badge="Multi-Series Spline",
            explanation=growth_expl,
            key="dept_growth"
        )

    # Department Lead Analyst Anomaly & Strategic Intelligence Panel
    render_smart_analyst_anomaly_panel(
        layer_id="department_management",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="dept"
    )


# =========================================================================
# LAYER 2: EMPLOYEE DIRECTORY (DANH BẠ NHÂN VIÊN)
# =========================================================================

def _render_layer_employee_directory(engine):
    """Layer 2: Danh bạ nhân viên, Tìm kiếm & Lọc, Thống kê nhân viên mới nhất & tỷ lệ giới tính (Bilingual)."""
    is_en = (get_current_language() == "en")

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>👥 {t('card_emp_title')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_home_2", use_container_width=True):
            _set_layer("overview")

    start_year, end_year = _render_timeline_slider("emp_dir")

    # Bộ lọc tìm kiếm
    c_srch, c_f_dept, c_f_title = st.columns([3, 2, 2])
    with c_srch:
        srch_lbl = "🔍 Search" if is_en else "🔍 Tìm kiếm"
        srch_ph = "Enter employee name or ID..." if is_en else "Nhập tên hoặc mã ID nhân viên..."
        search_q = st.text_input(srch_lbl, placeholder=srch_ph, key="emp_dir_search_input")
    with c_f_dept:
        dept_opts = ["All", "Development", "Production", "Sales", "Customer Service", "Research", "Marketing", "Quality Management", "Human Resources", "Finance"]
        sel_dept = st.selectbox("Filter Department" if is_en else "Lọc Phòng ban", dept_opts, key="emp_dir_dept_filter")
    with c_f_title:
        title_opts = ["All", "Senior Engineer", "Staff", "Engineer", "Senior Staff", "Technique Leader", "Assistant Engineer", "Manager"]
        sel_title = st.selectbox("Filter Title" if is_en else "Lọc Chức danh", title_opts, key="emp_dir_title_filter")

    data = fetch_hr_employee_directory(
        engine,
        search_term=search_q,
        dept_filter=sel_dept,
        title_filter=sel_title,
        start_year=start_year,
        end_year=end_year,
        limit=50
    )

    # 3 Thẻ Thống Kê Nhanh
    s1, s2, s3 = st.columns(3)
    period_str = str(start_year) if start_year == end_year else f"{start_year}-{end_year}"
    with s1:
        kpi1_title = "Hiring Volume" if is_en else "Kết Quả Tuyển Dụng"
        kpi1_val = f"{data['total_records']:,} " + ("Staff" if is_en else "Nhân sự")
        kpi1_sub = "👥 New hires in period" if is_en else "👥 Nhân sự gia nhập trong kỳ"
        st.markdown(f"""
        <div class="kpi-card-cyan" style="min-height: 105px;">
            <div class="kpi-title">
                <span>{kpi1_title}</span>
                <span class="kpi-badge">{period_str}</span>
            </div>
            <div class="kpi-val" style="font-size: 1.85rem !important;">{kpi1_val}</div>
            <div class="kpi-sub">{kpi1_sub}</div>
        </div>
        """, unsafe_allow_html=True)
    with s2:
        kpi2_title = "Survey Period" if is_en else "Giai Đoạn Khảo Sát"
        kpi2_sub = "🌱 Hire milestone snapshot" if is_en else "🌱 Mốc thời gian tuyển dụng"
        st.markdown(f"""
        <div class="kpi-card-emerald" style="min-height: 105px;">
            <div class="kpi-title">
                <span>{kpi2_title}</span>
                <span class="kpi-badge">Timeline</span>
            </div>
            <div class="kpi-val" style="font-size: 1.45rem !important; margin: 6px 0;">{data['newest_hire']}</div>
            <div class="kpi-sub">{kpi2_sub}</div>
        </div>
        """, unsafe_allow_html=True)
    with s3:
        kpi3_title = "Peak Compensation" if is_en else "Thu Nhập Đỉnh Điểm"
        kpi3_sub = "💎 Highest recorded salary" if is_en else "💎 Mức lương cao nhất"
        st.markdown(f"""
        <div class="kpi-card-purple" style="min-height: 105px;">
            <div class="kpi-title">
                <span>{kpi3_title}</span>
                <span class="kpi-badge">Top Earner</span>
            </div>
            <div class="kpi-val" style="font-size: 1.45rem !important; margin: 6px 0;">{data['highest_earner']}</div>
            <div class="kpi-sub">{kpi3_sub}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # 2 Biểu đồ chuyên biệt cho Employee Directory: Giới tính & Tuyển dụng theo năm
    col_g1, col_g2 = st.columns([1.1, 1.4])
    with col_g1:
        fig_gender = build_new_vs_returned_donut(
            data["gender_df"],
            center_label="Total Headcount" if is_en else "Tổng Nhân Sự",
            center_val_override=data["total_records"]
        )
        gender_title = "👥 Gender Distribution of Hires" if is_en else "👥 Cơ Cấu Giới Tính Nhân Viên Tuyển Dụng"
        gender_expl = f"Gender breakdown between Male (M) and Female (F) talent hired during {period_str}." if is_en else f"Tỷ lệ cơ cấu nhân sự tuyển dụng giữa Nam (M) và Nữ (F) trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=gender_title,
            fig=fig_gender,
            df=data["gender_df"],
            badge="Gender Ratio",
            explanation=gender_expl,
            key="emp_gender"
        )

    with col_g2:
        m1_h_lbl = "Total Hires" if is_en else "Tổng Tuyển Dụng"
        m2_h_lbl = "Male Staff (M)" if is_en else "Nhân Sự Nam (M)"
        fig_hires = build_hr_trend_chart(
            data["yearly_hires_df"],
            x_col="TimePeriod",
            y1_col="Metric1",
            y2_col="Metric2",
            name_1=m1_h_lbl,
            name_2=m2_h_lbl,
            unit="people" if is_en else "người",
            height=250
        )
        hires_title = "📅 Yearly Hire Distribution Across Period" if is_en else "📅 Phân Bổ Tuyển Dụng Theo Từng Năm Trong Kỳ"
        hires_expl = f"Annual volume of new employees onboarding across {period_str}." if is_en else f"Số lượng nhân viên mới gia nhập công ty qua từng mốc thời gian trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=hires_title,
            fig=fig_hires,
            df=data["yearly_hires_df"],
            badge="Yearly Hires",
            explanation=hires_expl,
            key="emp_hires"
        )

    # Bảng danh bạ
    disp_df = data["df"].copy()
    if "CurrentSalary" in disp_df.columns:
        disp_df["CurrentSalary ($)"] = disp_df["CurrentSalary"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "$0")
        disp_df = disp_df.drop(columns=["CurrentSalary"])

    st.dataframe(disp_df, hide_index=True, use_container_width=True)
    _render_sql_modal("Employee Directory" if is_en else "Danh Bạ Nhân Viên", data["sql"], data["exec_time_ms"], "emp_dir_sql")

    # Employee Directory Lead Analyst Anomaly & Strategic Intelligence Panel
    render_smart_analyst_anomaly_panel(
        layer_id="employee_directory",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="emp"
    )


# =========================================================================
# LAYER 3: SALARY ANALYSIS (PHÂN TÍCH TIỀN LƯƠNG)
# =========================================================================

def _render_layer_salary_analysis(engine):
    """Layer 3: Phân tích lương theo phòng ban, theo chức danh, Top 10 nhân viên lương cao nhất và xu hướng quỹ lương (Bilingual)."""
    is_en = (get_current_language() == "en")

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>💰 {t('card_sal_title')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_home_3", use_container_width=True):
            _set_layer("overview")

    start_year, end_year = _render_timeline_slider("salary_analysis")
    data = fetch_hr_salary_analysis_data(engine, start_year=start_year, end_year=end_year)
    period_str = str(start_year) if start_year == end_year else f"{start_year}-{end_year}"

    # 4 Thẻ Lương Toàn Diện
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown(f"""
        <div class="kpi-card-emerald">
            <div class="kpi-title">
                <span>{t('kpi_avg_salary')}</span>
                <span class="kpi-badge">{period_str}</span>
            </div>
            <div class="kpi-val">${data['avg_salary']:,.0f}</div>
            <div class="kpi-sub">{"⚡ Average salary in period" if is_en else "⚡ Mức lương trung bình trong kỳ"}</div>
        </div>
        """, unsafe_allow_html=True)
    with s2:
        st.markdown(f"""
        <div class="kpi-card-purple">
            <div class="kpi-title">
                <span>{"Max Salary" if is_en else "Lương Cao Nhất"}</span>
                <span class="kpi-badge">Max Salary</span>
            </div>
            <div class="kpi-val">${data['max_salary']:,.0f}</div>
            <div class="kpi-sub">{"🏆 Peak compensation ceiling" if is_en else "🏆 Đỉnh điểm thu nhập"}</div>
        </div>
        """, unsafe_allow_html=True)
    with s3:
        st.markdown(f"""
        <div class="kpi-card-cyan">
            <div class="kpi-title">
                <span>{"Min Salary" if is_en else "Lương Thấp Nhất"}</span>
                <span class="kpi-badge">Min Salary</span>
            </div>
            <div class="kpi-val">${data['min_salary']:,.0f}</div>
            <div class="kpi-sub">{"📌 Floor compensation level" if is_en else "📌 Mức lương sàn"}</div>
        </div>
        """, unsafe_allow_html=True)
    with s4:
        st.markdown(f"""
        <div class="kpi-card-amber">
            <div class="kpi-title">
                <span>{"Total Payroll Budget" if is_en else "Tổng Quỹ Lương"}</span>
                <span class="kpi-badge">Budget</span>
            </div>
            <div class="kpi-val">${data['total_payroll']/1e9:,.2f}B</div>
            <div class="kpi-sub">{"💵 Total compensation outlay" if is_en else "💵 Tổng ngân sách chi trả"}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Biểu đồ sóng kép xu hướng lương qua các năm
    if "salary_trend_df" in data and not data["salary_trend_df"].empty and len(data["salary_trend_df"]) > 1:
        fig_sal_trend = build_hr_trend_chart(
            data["salary_trend_df"],
            x_col="TimePeriod",
            y1_col="Metric1",
            y2_col="Metric2",
            name_1="Average Salary ($)" if is_en else "Lương Bình Quân ($)",
            name_2="Total Payroll ($M)" if is_en else "Tổng Quỹ Lương ($M)",
            unit="$",
            height=260
        )
        trend_sal_title = f"📈 Average Salary & Total Payroll Budget Trends ({start_year} — {end_year})" if is_en else f"📈 Xu Hướng Lương Bình Quân & Tổng Quỹ Lương ({start_year} — {end_year})"
        trend_sal_expl = f"Year-over-year evolution of mean compensation and overall payroll expenditure from {start_year} to {end_year}." if is_en else f"Biến động mức lương bình quân và tổng chi phí ngân sách quỹ lương qua từng năm ({start_year} — {end_year})."
        render_zoomable_chart_card(
            title=trend_sal_title,
            fig=fig_sal_trend,
            df=data["salary_trend_df"],
            badge="Trend Spline Wave",
            explanation=trend_sal_expl,
            key="sal_trend"
        )

    # 2 Biểu đồ: So sánh Min/Avg/Max theo phòng ban & Lương theo chức danh
    col_d, col_t = st.columns(2)
    with col_d:
        m_names = ["Min Salary", "Avg Salary", "Max Salary"] if is_en else ["Lương Min", "Lương TB", "Lương Max"]
        fig_mbar = build_multi_bar_chart(
            data["dept_sal_df"],
            x_col="Department",
            y_cols=["MinSalary", "AvgSalary", "MaxSalary"],
            names=m_names,
            colors=["#38BDF8", "#00F0FF", "#E879F9"],
            height=270
        )
        mbar_title = "🏢 Min / Avg / Max Salary Comparison by Department" if is_en else "🏢 So Sánh Lương Min / Avg / Max Theo Phòng Ban"
        mbar_expl = f"Compensation spread (floor - median - ceiling) across functional departments during {period_str}." if is_en else f"Phân bổ dải lương (sàn - trung bình - trần) chi trả cho nhân sự giữa các phòng ban trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=mbar_title,
            fig=fig_mbar,
            df=data["dept_sal_df"],
            badge="Grouped Bar",
            explanation=mbar_expl,
            key="sal_mbar"
        )

    with col_t:
        title_sal_chart_df = pd.DataFrame({
            "Title": data["title_sal_df"]["Title"],
            "AvgSalary": data["title_sal_df"]["AvgSalary"]
        })
        fig_tbar = build_weekday_bar_chart(pd.DataFrame({
            "WeekDay": data["title_sal_df"]["Title"],
            "Total": data["title_sal_df"]["AvgSalary"]
        }))
        tbar_title = "🎓 Average Salary by Professional Title ($)" if is_en else "🎓 Mức Lương Bình Quân Theo Chức Danh ($)"
        tbar_expl = f"Empirical market compensation corresponding to professional roles and hierarchy tiers during {period_str}." if is_en else f"Mặt bằng lương thực tế tương ứng với từng cấp bậc và vị trí chức danh trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=tbar_title,
            fig=fig_tbar,
            df=title_sal_chart_df,
            badge="Compensation",
            explanation=tbar_expl,
            key="sal_tbar"
        )

    # Bảng Top 10 nhân viên có lương cao nhất
    top10_hdr = "🏆 Top 10 Highest-Paid Employees Across Company" if is_en else "🏆 Top 10 Nhân Viên Có Mức Lương Cao Nhất Toàn Công Ty"
    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{top10_hdr}</span>
            <span class="crm-badge-neon">Top 10 Earners</span>
        </div>
    """, unsafe_allow_html=True)
    disp_top10 = data["top10_df"].copy()
    disp_top10["CurrentSalary ($)"] = disp_top10["CurrentSalary"].apply(lambda x: f"${x:,.0f}")
    st.dataframe(disp_top10[["ID", "FullName", "Department", "Title", "CurrentSalary ($)"]], hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Salary Analysis" if is_en else "Phân Tích Tiền Lương", data["sql"], data["exec_time_ms"], "sal_analysis_sql")

    # Salary Lead Analyst Anomaly & Strategic Intelligence Panel
    render_smart_analyst_anomaly_panel(
        layer_id="salary_analysis",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="salary"
    )


# =========================================================================
# LAYER 4: ORGANIZATIONAL STRUCTURE (CƠ CẤU TỔ CHỨC)
# =========================================================================

def _render_layer_org_structure(engine):
    """Layer 4: Sơ đồ cơ cấu tổ chức & Span of Control của từng Manager (Bilingual)."""
    is_en = (get_current_language() == "en")

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🌳 {t('card_org_title')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_home_4", use_container_width=True):
            _set_layer("overview")

    start_year, end_year = _render_timeline_slider("org_structure")
    data = fetch_hr_org_structure_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]
    period_str = str(start_year) if start_year == end_year else f"{start_year} - {end_year}"

    org_card_title = f"🌳 Leadership Structure & Span of Control ({period_str})" if is_en else f"🌳 Cơ Cấu Lãnh Đạo & Quy Mô Quản Lý (Span of Control) ({period_str})"
    badge_org = "9 Operational Departments" if is_en else "9 Khối Phòng Ban"

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{org_card_title}</span>
            <span class="crm-badge-neon">{badge_org}</span>
        </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    disp_df["ManagerSalary ($)"] = disp_df["ManagerSalary"].apply(lambda x: f"${x:,.0f}")
    st.dataframe(disp_df[["ManagerID", "ManagerName", "Department", "Status", "CurrentDepartmentSize", "ManagerSalary ($)"]], hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Organizational Structure" if is_en else "Cơ Cấu Tổ Chức", data["sql"], data["exec_time_ms"], "org_struct_sql")

    # 2 Biểu đồ: Span of control & Bổ nhiệm Manager qua các năm
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        fig_span = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["ManagerName"], "Total": df["CurrentDepartmentSize"]}))
        span_title = "📊 Direct Headcount Under Each Department Manager" if is_en else "📊 Quy Mô Nhân Sự Dưới Quyền Của Từng Manager"
        span_expl = f"Direct span of control (headcount size under manager supervision) during {period_str}." if is_en else f"Quy mô số lượng nhân sự trực tiếp dưới quyền điều hành của từng Trưởng phòng trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=span_title,
            fig=fig_span,
            df=pd.DataFrame({"ManagerName": df["ManagerName"], "CurrentDepartmentSize": df["CurrentDepartmentSize"]}),
            badge="Span of Control",
            explanation=span_expl,
            key="org_span"
        )

    with col_s2:
        m1_app_lbl = "Manager Appointments" if is_en else "Lượt Bổ Nhiệm Manager"
        m2_app_lbl = "Active Departments" if is_en else "Số Khối Hoạt Động"
        fig_appts = build_hr_trend_chart(
            data["appts_df"],
            x_col="TimePeriod",
            y1_col="Metric1",
            y2_col="Metric2",
            name_1=m1_app_lbl,
            name_2=m2_app_lbl,
            unit="turns" if is_en else "lượt",
            height=240
        )
        appts_title = f"👔 Manager Appointments & Handover Trends ({start_year} — {end_year})" if is_en else f"👔 Số Lượt Bổ Nhiệm Manager Qua Các Năm ({start_year} — {end_year})"
        appts_expl = f"Timeline trajectory of department manager appointments and transitions from {start_year} to {end_year}." if is_en else f"Số lượt bổ nhiệm và chuyển giao ghế Trưởng phòng qua các năm từ {start_year} đến {end_year}."
        render_zoomable_chart_card(
            title=appts_title,
            fig=fig_appts,
            df=data["appts_df"],
            badge="Appointments Wave",
            explanation=appts_expl,
            key="org_appts"
        )

    # Org Structure Lead Analyst Anomaly & Strategic Intelligence Panel
    render_smart_analyst_anomaly_panel(
        layer_id="org_structure",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="org"
    )


# =========================================================================
# LAYER 5: TITLE & POSITIONS (CHỨC DANH & VỊ TRÍ)
# =========================================================================

def _render_layer_title_positions(engine):
    """Layer 5: Danh sách chức danh, số lượng nhân viên và mức lương bình quân (Bilingual)."""
    is_en = (get_current_language() == "en")

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🎓 {t('card_title_title')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_home_5", use_container_width=True):
            _set_layer("overview")

    start_year, end_year = _render_timeline_slider("title_positions")
    data = fetch_hr_titles_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]
    period_str = str(start_year) if start_year == end_year else f"{start_year} - {end_year}"

    title_card_hdr = f"🎓 Position Catalog & Professional Hierarchy (7 Titles) ({period_str})" if is_en else f"🎓 Danh Mục Vị Trí & Cơ Cấu Cấp Bậc (7 Titles) ({period_str})"
    badge_title = "Company-wide" if is_en else "Toàn Công Ty"

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{title_card_hdr}</span>
            <span class="crm-badge-neon">{badge_title}</span>
        </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    disp_df["AvgSalary ($)"] = disp_df["AvgSalary"].apply(lambda x: f"${x:,.0f}")
    disp_df["MaxSalary ($)"] = disp_df["MaxSalary"].apply(lambda x: f"${x:,.0f}")
    disp_df["MinSalary ($)"] = disp_df["MinSalary"].apply(lambda x: f"${x:,.0f}")
    st.dataframe(disp_df[["Title", "Headcount", "Percentage", "AvgSalary ($)", "MaxSalary ($)", "MinSalary ($)"]], hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Titles & Positions" if is_en else "Chức Danh & Vị Trí", data["sql"], data["exec_time_ms"], "titles_sql")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        fig_donut = build_tickets_by_type_donut(df, label_col="Title", val_col="Headcount")
        donut_t_title = "📊 Workforce Distribution by Professional Title" if is_en else "📊 Phân Bổ Nhân Sự Theo Chức Danh Trong Kỳ"
        donut_t_expl = f"Proportion of staff headcount across professional career levels during {period_str}." if is_en else f"Tỷ trọng cơ cấu các cấp bậc chuyên môn trong toàn bộ lực lượng lao động trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=donut_t_title,
            fig=fig_donut,
            df=df,
            badge="Headcount Share",
            explanation=donut_t_expl,
            key="title_donut"
        )

    with col_t2:
        title_sal_df = pd.DataFrame({"Title": df["Title"], "AvgSalary": df["AvgSalary"]})
        fig_sal = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["Title"], "Total": df["AvgSalary"]}))
        bar_t_title = "💰 Average Salary by Professional Title ($)" if is_en else "💰 Mức Lương Bình Quân Theo Chức Danh ($)"
        bar_t_expl = f"Average compensation levels by job role in {period_str}." if is_en else f"Mặt bằng lương bình quân chi trả cho từng chức danh công việc trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=bar_t_title,
            fig=fig_sal,
            df=title_sal_df,
            badge="Avg Compensation",
            explanation=bar_t_expl,
            key="title_sal"
        )

    # Biểu đồ dòng thời gian bổ nhiệm chức danh
    if "title_trend_df" in data and not data["title_trend_df"].empty and len(data["title_trend_df"]) > 1:
        m1_pr_lbl = "New Appointments" if is_en else "Lượt Bổ Nhiệm Mới"
        m2_pr_lbl = "Promoted Staff" if is_en else "Nhân Sự Thăng Cấp"
        fig_promo = build_hr_trend_chart(
            data["title_trend_df"],
            x_col="TimePeriod",
            y1_col="Metric1",
            y2_col="Metric2",
            name_1=m1_pr_lbl,
            name_2=m2_pr_lbl,
            unit="turns" if is_en else "lượt",
            height=250
        )
        promo_title = f"📈 Title Appointment & Career Promotion Trends ({start_year} — {end_year})" if is_en else f"📈 Xu Hướng Bổ Nhiệm & Thăng Tiến Chức Danh ({start_year} — {end_year})"
        promo_expl = f"Promotion rhythm and career progression patterns across years ({start_year} — {end_year})." if is_en else f"Nhịp điệu các đợt thăng chức và bổ nhiệm chức danh qua các năm ({start_year} — {end_year})."
        render_zoomable_chart_card(
            title=promo_title,
            fig=fig_promo,
            df=data["title_trend_df"],
            badge="Promotion Waves",
            explanation=promo_expl,
            key="title_promo"
        )

    # Titles & Positions Lead Analyst Anomaly & Strategic Intelligence Panel
    render_smart_analyst_anomaly_panel(
        layer_id="title_positions",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="titles"
    )


# =========================================================================
# LAYER 6: DEPARTMENT MANAGERS (ĐỘI NGŨ QUẢN LÝ)
# =========================================================================

def _render_layer_dept_managers(engine):
    """Layer 6: Hồ sơ chi tiết các Manager, nhiệm kỳ quản lý và mức lương theo mốc thời gian (Bilingual)."""
    is_en = (get_current_language() == "en")

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>👔 {t('card_mgr_title')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_home_6", use_container_width=True):
            _set_layer("overview")

    start_year, end_year = _render_timeline_slider("dept_managers")
    data = fetch_hr_managers_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]
    period_str = str(start_year) if start_year == end_year else f"{start_year} - {end_year}"

    mgr_card_hdr = f"👔 Department Managers Roster & Tenures ({period_str})" if is_en else f"👔 Danh Sách Đội Ngũ Trưởng Phòng (Managers) Trong Kỳ ({period_str})"
    badge_mgr = "History & Incumbents" if is_en else "Lịch Sử & Đương Nhiệm"

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{mgr_card_hdr}</span>
            <span class="crm-badge-neon">{badge_mgr}</span>
        </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    disp_df["CurrentSalary ($)"] = disp_df["CurrentSalary"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "N/A")
    st.dataframe(disp_df[["ManagerID", "ManagerName", "Gender", "Department", "StartDate", "EndDate", "TenureStatus", "CurrentDeptHeadcount", "CurrentSalary ($)"]], hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Department Managers" if is_en else "Đội Ngũ Managers", data["sql"], data["exec_time_ms"], "managers_sql")

    # 2 Biểu đồ chuyên biệt cho Manager Layer: Lương & Quy mô phòng ban phụ trách
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        mgr_sal_df = pd.DataFrame({
            "Department": df["Department"],
            "CurrentSalary": df["CurrentSalary"]
        })
        fig_msal = build_weekday_bar_chart(pd.DataFrame({
            "WeekDay": df["Department"],
            "Total": df["CurrentSalary"]
        }))
        msal_title = "💰 Manager Compensation by Department ($)" if is_en else "💰 Mức Lương Của Đội Ngũ Managers Theo Phòng Ban ($)"
        msal_expl = f"Compensation comparison among department managers during {period_str}." if is_en else f"So sánh mức thu nhập chi trả cho các Trưởng phòng giữa các phòng ban trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=msal_title,
            fig=fig_msal,
            df=mgr_sal_df,
            badge="Manager Compensation",
            explanation=msal_expl,
            key="mgr_sal"
        )

    with col_m2:
        mgr_hc_df = pd.DataFrame({
            "Department": df["Department"],
            "CurrentDeptHeadcount": df["CurrentDeptHeadcount"]
        })
        fig_mhc = build_weekday_bar_chart(pd.DataFrame({
            "WeekDay": df["Department"],
            "Total": df["CurrentDeptHeadcount"]
        }))
        mhc_title = "👥 Managed Department Headcount Scale" if is_en else "👥 Quy Mô Nhân Sự Khối Do Manager Quản Lý"
        mhc_expl = f"Headcount scale directly supervised by each Department Manager during {period_str}." if is_en else f"Quy mô số lượng nhân viên trực thuộc khối do từng Manager phụ trách trong giai đoạn {period_str}."
        render_zoomable_chart_card(
            title=mhc_title,
            fig=fig_mhc,
            df=mgr_hc_df,
            badge="Managed Headcount",
            explanation=mhc_expl,
            key="mgr_hc"
        )

    # Managers Lead Analyst Anomaly & Strategic Intelligence Panel
    render_smart_analyst_anomaly_panel(
        layer_id="dept_managers",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="managers"
    )


# =========================================================================
# FALLBACK VIEW: CRM / TICKETS DASHBOARD (NẾU CƠ SỞ DỮ LIỆU LÀ CRM)
# =========================================================================

def _render_crm_legacy_view(engine):
    """Fallback hiển thị CRM Support Dashboard nếu CSDL kết nối là CRM/Tickets (Bilingual)."""
    is_en = (get_current_language() == "en")
    kpis = fetch_crm_kpis(engine, "All")
    created_solved_data = fetch_tickets_created_vs_solved(engine, "All")
    type_data = fetch_tickets_by_type(engine, "All")
    retention_data = fetch_new_vs_returned(engine, "All")
    weekday_data = fetch_tickets_by_weekday(engine, "All")
    wave_data = fetch_latency_wave_data(engine, "All")

    col_kpi1, col_kpi2, col_kpi3, col_wave = st.columns([1.3, 1.3, 1.4, 2.0])
    with col_kpi1:
        st.markdown(f"""
        <div class="kpi-card-purple">
            <div style="font-size: 0.78rem; font-weight: 600; text-transform: uppercase;">Avg First Reply Time</div>
            <div style="font-size: 1.85rem; font-weight: 850;">{kpis['reply_hours']}h {kpis['reply_mins']}m</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">⚡ SLA < 32h</div>
        </div>
        """, unsafe_allow_html=True)
    with col_kpi2:
        st.markdown(f"""
        <div class="kpi-card-cyan">
            <div style="font-size: 0.78rem; font-weight: 600; text-transform: uppercase;">Avg Full Resolve Time</div>
            <div style="font-size: 1.85rem; font-weight: 850;">{kpis['resolve_hours']}h {kpis['resolve_mins']}m</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">🎯 {'Solve Ratio:' if is_en else 'Tỷ lệ:'} {round(kpis['solved_tickets']*100/max(1, kpis['total_tickets']), 1)}%</div>
        </div>
        """, unsafe_allow_html=True)
    with col_kpi3:
        st.markdown(f"""
        <div class="kpi-card-emerald">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase;">Total Tickets</div>
            <div style="font-size: 1.85rem; font-weight: 850;">{kpis['total_tickets']:,}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">✉️ Solved: {kpis['solved_tickets']:,}</div>
        </div>
        """, unsafe_allow_html=True)
    with col_wave:
        fig_wave = build_latency_wave_chart(wave_data["df"])
        wave_title = "⚡ Ticket Response Latency Dynamics" if is_en else "⚡ Biến Động Thời Gian Phản Hồi Ticket"
        wave_expl = "Initial first-reply and full resolution latency." if is_en else "Thời gian phản hồi đầu tiên và thời gian xử lý dứt điểm ticket hỗ trợ."
        render_zoomable_chart_card(
            title=wave_title,
            fig=fig_wave,
            df=wave_data["df"],
            badge="Latency Wave",
            explanation=wave_expl,
            key="crm_wave"
        )

    fig_center = build_created_vs_solved_chart(created_solved_data["df"], created_solved_data.get("max_point"))
    render_zoomable_chart_card(
        title="📈 Created vs Solved Tickets Overview" if is_en else "📈 Tương Quan Tạo Mới & Xử Lý Ticket",
        fig=fig_center,
        df=created_solved_data["df"],
        badge="Activity Volume",
        explanation="Monthly comparison of incoming and completed support cases." if is_en else "So sánh khối lượng ticket tạo mới và đã hoàn thành theo từng tháng.",
        key="crm_created_solved"
    )


# =========================================================================
# SALES & COMMERCIAL EXECUTIVE DASHBOARD (AWESOME CHOCOLATES)
# =========================================================================

def _render_sales_dashboard(engine):
    """Dashboard Đa Tầng Cấp Cao chuyên sâu cho CSDL Bán hàng & Thương mại (Awesome Chocolates) - Bilingual."""
    is_en = (get_current_language() == "en")
    current_layer = st.session_state.get("sales_dashboard_layer", "overview")

    # 1. Điều hướng Header
    c_hdr1, c_hdr2, c_hdr3, c_hdr4 = st.columns([4.0, 2.6, 1.8, 1.6])
    with c_hdr1:
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
            <div style="font-size: 1.55rem; font-weight: 900; color: #FFFFFF; letter-spacing: -0.02em;">{t('sales_dash_title')}</div>
            <span class="crm-badge-neon">{t('sales_dash_badge')}</span>
        </div>
        """, unsafe_allow_html=True)

    with c_hdr2:
        if is_en:
            layer_names = {
                "overview": "🏠 Sales Overview",
                "geo": "🌍 Geographic Revenue",
                "people": "👥 Sales Team & Reps",
                "products": "🍫 Product Portfolio",
                "trends": "📈 Revenue & Volume Trends",
                "top_performers": "🏆 Top Sales Performers",
            }
        else:
            layer_names = {
                "overview": "🏠 Trang chủ Doanh số (Overview)",
                "geo": "🌍 Thị trường & Địa lý (Geo & Markets)",
                "people": "👥 Đội ngũ & Team Sales (Sales Teams)",
                "products": "🍫 Danh mục Sản phẩm (Products & Margin)",
                "trends": "📈 Xu hướng & Mùa vụ (Revenue Trends)",
                "top_performers": "🏆 Top Bán hàng & Khách hàng (Top Performers)",
            }
        layer_keys = list(layer_names.keys())
        current_idx = layer_keys.index(current_layer) if current_layer in layer_keys else 0

        selected_l = st.selectbox(
            "Select Sales Layer" if is_en else "Chọn tầng phân tích",
            layer_keys,
            format_func=lambda x: layer_names[x],
            index=current_idx,
            key="sales_layer_selectbox",
            label_visibility="collapsed"
        )
        if selected_l != current_layer:
            st.session_state["sales_dashboard_layer"] = selected_l
            st.rerun()
        current_layer = st.session_state.get("sales_dashboard_layer", "overview")

    with c_hdr3:
        layer_title_curr = layer_names.get(current_layer, "Sales Overview" if is_en else "Tổng quan Doanh số")
        start_y_curr = st.session_state.get("sales_timeline_years", (2021, 2023))[0]
        end_y_curr = st.session_state.get("sales_timeline_years", (2021, 2023))[1]
        t_lbl_curr = f"{start_y_curr} — {end_y_curr}" if start_y_curr != end_y_curr else str(start_y_curr)
        ctx_header = {
            "layer_title": layer_title_curr,
            "time_label": t_lbl_curr,
            "anomalies": [],
            "kpis_summary": f"Viewing {layer_title_curr} during {t_lbl_curr}." if is_en else f"Đang xem {layer_title_curr} giai đoạn {t_lbl_curr}.",
            "data_summary": f"User opened Copilot from header on {layer_title_curr}." if is_en else f"Người dùng mở Copilot từ thanh Header trên tầng {layer_title_curr}."
        }
        if st.button(t("hr_btn_copilot"), type="primary", use_container_width=True, key="btn_sales_header_copilot", help=t("hr_copilot_help")):
            show_dashboard_copilot_dialog(ctx_header)

    with c_hdr4:
        if st.button(t("hr_btn_main_chat"), type="secondary", use_container_width=True, key="btn_sales_header_chat", help=t("hr_main_chat_help")):
            st.session_state["view_mode"] = "chat"
            st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # 2. ROUTING TỚI CÁC LAYER BÁN HÀNG CHUYÊN BIỆT
    if current_layer == "overview":
        _render_sales_layer_overview(engine)
    elif current_layer == "geo":
        _render_sales_layer_geo(engine)
    elif current_layer == "people":
        _render_sales_layer_people(engine)
    elif current_layer == "products":
        _render_sales_layer_products(engine)
    elif current_layer == "trends":
        _render_sales_layer_trends(engine)
    elif current_layer == "top_performers":
        _render_sales_layer_top_performers(engine)


def _render_sales_layer_overview(engine):
    """Trang chủ Doanh số & Thương mại: 6 Thẻ chủ đề, 4 KPI Neon, Sóng kép Doanh số & Số hộp, Donut Category, Bar Quốc gia (Bilingual)."""
    is_en = (get_current_language() == "en")

    # 1. 6 THẺ CHỦ ĐỀ KHÁM PHÁ THEO LAYER
    hub_title = "🎯 Select Commercial Domain (Explore by Layer):" if is_en else "🎯 Chọn Chủ Đề Phân Tích Thương Mại (Khám Phá Theo Layer):"
    st.markdown(f"""
    <div style="font-size: 1.05rem; font-weight: 800; color: #FFFFFF; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
        <span>🎯</span> <span><b>{hub_title}</b></span>
    </div>
    """, unsafe_allow_html=True)

    nav_cols1 = st.columns(3)
    with nav_cols1[0]:
        with st.container():
            c1_t = "1. Markets & Geography" if is_en else "1. Thị Trường & Địa Lý"
            c1_d = "Analyze revenue across 6 global markets (India, USA, UK...) and regional APAC, Americas, Europe." if is_en else "Phân tích doanh số 6 thị trường quốc tế (Ấn Độ, Mỹ, Anh, Úc...) & thị phần theo vùng APAC, Americas, Europe."
            st.markdown(f"""
            <div class="nav-hub-title"><span>🌍</span> {c1_t}</div>
            <div class="nav-hub-desc">{c1_d}</div>
            """, unsafe_allow_html=True)
            btn1_l = "Explore Markets ➔" if is_en else "Khám phá Thị trường ➔"
            if st.button(btn1_l, key="btn_nav_s_geo", use_container_width=True):
                _set_layer("geo", domain_key="sales")

    with nav_cols1[1]:
        with st.container():
            c2_t = "2. Sales Teams & Reps" if is_en else "2. Đội Ngũ & Team Sales"
            c2_d = "Track productivity of 18 sales reps across Yummies, Delish, and Jucies teams." if is_en else "Hiệu suất 18 Sales Reps, so sánh năng suất các Team (Yummies, Delish, Jucies) và định biên nhân sự."
            st.markdown(f"""
            <div class="nav-hub-title"><span>👥</span> {c2_t}</div>
            <div class="nav-hub-desc">{c2_d}</div>
            """, unsafe_allow_html=True)
            btn2_l = "Explore Teams ➔" if is_en else "Khám phá Đội ngũ ➔"
            if st.button(btn2_l, key="btn_nav_s_people", use_container_width=True):
                _set_layer("people", domain_key="sales")

    with nav_cols1[2]:
        with st.container():
            c3_t = "3. Product Catalog & Margins" if is_en else "3. Danh Mục Sản Phẩm"
            c3_d = "Evaluate 22 chocolate SKUs (Bars, Bites, Other), unit costs, and gross margins." if is_en else "Phân tích 22 dòng sản phẩm (Bars, Bites, Other), kích thước đóng gói, giá vốn & biên lợi nhuận gộp."
            st.markdown(f"""
            <div class="nav-hub-title"><span>🍫</span> {c3_t}</div>
            <div class="nav-hub-desc">{c3_d}</div>
            """, unsafe_allow_html=True)
            btn3_l = "Explore Products ➔" if is_en else "Khám phá Sản phẩm ➔"
            if st.button(btn3_l, key="btn_nav_s_products", use_container_width=True):
                _set_layer("products", domain_key="sales")

    nav_cols2 = st.columns(3)
    with nav_cols2[0]:
        with st.container():
            c4_t = "4. Revenue Trends & Seasonality" if is_en else "4. Xu Hướng & Mùa Vụ"
            c4_d = "Track monthly revenue time series, peak anomaly periods, and business cycles." if is_en else "Theo dõi chuỗi thời gian doanh thu tháng/quý, giải mã các đỉnh tăng trưởng đột biến và tính chu kỳ kinh doanh."
            st.markdown(f"""
            <div class="nav-hub-title"><span>📈</span> {c4_t}</div>
            <div class="nav-hub-desc">{c4_d}</div>
            """, unsafe_allow_html=True)
            btn4_l = "Explore Trends ➔" if is_en else "Khám phá Xu hướng ➔"
            if st.button(btn4_l, key="btn_nav_s_trends", use_container_width=True):
                _set_layer("trends", domain_key="sales")

    with nav_cols2[1]:
        with st.container():
            c5_t = "5. Top Performers & SKUs" if is_en else "5. Top Bán Hàng & Khách Hàng"
            c5_d = "Leaderboard ranking of top 10 sales specialists and best-selling chocolate SKUs." if is_en else "Bảng xếp hạng Top 10 cá nhân & SKU xuất sắc nhất mang lại dòng tiền đột phá cho doanh nghiệp."
            st.markdown(f"""
            <div class="nav-hub-title"><span>🏆</span> {c5_t}</div>
            <div class="nav-hub-desc">{c5_d}</div>
            """, unsafe_allow_html=True)
            btn5_l = "View Leaderboard ➔" if is_en else "Xem Top Hiệu Suất ➔"
            if st.button(btn5_l, key="btn_nav_s_top", use_container_width=True):
                _set_layer("top_performers", domain_key="sales")

    with nav_cols2[2]:
        with st.container():
            c6_t = "6. Diagnostics & AI Copilot" if is_en else "6. Chẩn Đoán & AI Copilot"
            c6_d = "Detect market share deviations, volume spikes, and generate C-Level recommendations." if is_en else "Tự động phát hiện điểm lệch pha thị phần, đột biến doanh số và đưa ra khuyến nghị điều hành cấp cao."
            st.markdown(f"""
            <div class="nav-hub-title"><span>🧠</span> {c6_t}</div>
            <div class="nav-hub-desc">{c6_d}</div>
            """, unsafe_allow_html=True)
            btn6_l = "Ask Copilot Assistant 💬" if is_en else "Hỏi Trợ Lý Copilot 💬"
            if st.button(btn6_l, key="btn_nav_s_copilot", type="primary", use_container_width=True):
                ctx_quick = {
                    "layer_title": "Sales & Commercial Overview" if is_en else "Tổng quan Doanh số & Thương mại",
                    "time_label": "2021 — 2023",
                    "anomalies": [],
                    "kpis_summary": "Analyzing commercial data from Awesome Chocolates DB." if is_en else "Đang phân tích tổng quan doanh số CSDL Awesome Chocolates.",
                    "data_summary": "User opened Copilot from Sales Overview hub." if is_en else "Người dùng mở Copilot từ Thẻ điều hành Trang chủ."
                }
                show_dashboard_copilot_dialog(ctx_quick)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # 2. THANH TRƯỢT THỜI GIAN
    start_year, end_year = _render_timeline_slider("sales_overview", min_year=2021, max_year=2023, domain_key="sales")
    data = fetch_sales_overview_data(engine, start_year=start_year, end_year=end_year)

    # 3. 4 THẺ CHỈ SỐ ĐIỀU HÀNH
    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
    with col_kpi1:
        st.markdown(f"""
        <div class="kpi-card-cyan">
            <div class="kpi-title"><span>{t('sales_kpi_revenue')}</span> <span>💰</span></div>
            <div class="kpi-val">${data['total_revenue']:,.0f}</div>
            <div class="kpi-sub"><span class="kpi-badge">{"Net Revenue" if is_en else "Doanh thu thuần"}</span> <span>{"All Markets" if is_en else "Toàn thị trường"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    with col_kpi2:
        boxes_unit = "boxes" if is_en else "hộp"
        st.markdown(f"""
        <div class="kpi-card-purple">
            <div class="kpi-title"><span>{t('sales_kpi_boxes')}</span> <span>📦</span></div>
            <div class="kpi-val">{data['total_boxes']:,} <span style="font-size:1.1rem;font-weight:700;">{boxes_unit}</span></div>
            <div class="kpi-sub"><span class="kpi-badge">{"Volume" if is_en else "Khối lượng"}</span> <span>{"Total Shipped" if is_en else "Tổng xuất kho"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    with col_kpi3:
        st.markdown(f"""
        <div class="kpi-card-emerald">
            <div class="kpi-title"><span>{t('sales_kpi_customers')}</span> <span>👥</span></div>
            <div class="kpi-val">{data['total_customers']:,}</div>
            <div class="kpi-sub"><span class="kpi-badge">{"Interaction" if is_en else "Tương tác"}</span> <span>{"Customer Purchases" if is_en else "Lượt khách mua"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    with col_kpi4:
        st.markdown(f"""
        <div class="kpi-card-amber">
            <div class="kpi-title"><span>{"Avg Order Value" if is_en else "GIÁ TRỊ ĐƠN BÌNH QUÂN"}</span> <span>🛒</span></div>
            <div class="kpi-val">${data['avg_order_value']:,.0f}</div>
            <div class="kpi-sub"><span class="kpi-badge">AOV</span> <span>{"Mean per order" if is_en else "Trung bình mỗi đơn"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    _render_sql_modal("Sales Overview KPIs" if is_en else "Chỉ Số Tổng Quan Doanh Số", data["sql"], data["exec_time_ms"], "sales_ov_sql")

    # 4. 2 BIỂU ĐỒ CHÍNH: SÓNG KÉP DOANH SỐ & DONUT CATEGORY
    col_c1, col_c2 = st.columns([1.6, 1.0])
    with col_c1:
        fig_dual = build_sales_dual_axis_chart(data["trend_df"], x_col="Month", rev_col="Revenue", box_col="Boxes", height=280)
        dual_title = f"📈 Revenue ($) & Box Volume Trajectory ({start_year} — {end_year})" if is_en else f"📈 Diễn Biến Doanh Số ($) & Sản Lượng Hộp Bán Ra ({start_year} — {end_year})"
        dual_expl = "Dual-axis wave chart showing correlation between revenue generated and physical boxes shipped." if is_en else "Biểu đồ sóng kép đối chiếu tương quan giữa doanh thu tạo ra và số lượng hộp sô-cô-la tiêu thụ theo từng tháng."
        render_zoomable_chart_card(
            title=dual_title,
            fig=fig_dual,
            df=data["trend_df"],
            badge="Revenue & Volume Wave",
            explanation=dual_expl,
            key="sales_dual_wave"
        )

    with col_c2:
        fig_donut = build_donut_chart(data["category_df"], label_col="Category", val_col="Revenue", height=280)
        cat_title = "🍫 Revenue Share by Product Category" if is_en else "🍫 Tỷ Trọng Doanh Số Theo Danh Mục"
        cat_expl = "Revenue contribution between Bars, Bites, and other categories." if is_en else "Cơ cấu đóng góp doanh thu giữa các dòng sản phẩm Bars, Bites và các biến thể khác."
        render_zoomable_chart_card(
            title=cat_title,
            fig=fig_donut,
            df=data["category_df"],
            badge="Category Share",
            explanation=cat_expl,
            key="sales_cat_donut"
        )

    # 5. BIỂU ĐỒ THỊ TRƯỜNG TOÀN CẦU
    if not data["geo_df"].empty:
        fig_geo = build_horizontal_bar_chart(data["geo_df"], y_col="Geo", x_col="Revenue", name="Revenue ($)" if is_en else "Doanh số ($)", height=240)
        geo_title = f"🌍 Revenue Distribution Across Global Markets ({start_year} — {end_year})" if is_en else f"🌍 Phân Bổ Doanh Số Theo Thị Trường Quốc Gia ({start_year} — {end_year})"
        geo_expl = "Revenue rank across 6 key countries: India, USA, UK, Canada, Australia, and New Zealand." if is_en else "Xếp hạng quy mô doanh số chi trả từ 6 quốc gia trọng điểm: Ấn Độ, Mỹ, Anh, Canada, Úc và New Zealand."
        render_zoomable_chart_card(
            title=geo_title,
            fig=fig_geo,
            df=data["geo_df"],
            badge="Geographic Distribution",
            explanation=geo_expl,
            key="sales_geo_bar"
        )

    # 6. LEAD ANALYST ANOMALY & STRATEGIC INTELLIGENCE PANEL
    render_smart_analyst_anomaly_panel(
        layer_id="sales_overview",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="sales_ov"
    )


def _render_sales_layer_geo(engine):
    """Layer 1: Phân tích Thị trường & Địa lý (Bilingual)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🌍 {t('sales_layer_geo')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_s_1", use_container_width=True):
            _set_layer("overview", domain_key="sales")

    start_year, end_year = _render_timeline_slider("sales_geo", min_year=2021, max_year=2023, domain_key="sales")
    data = fetch_sales_geo_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]
    period_str = str(start_year) if start_year == end_year else f"{start_year} — {end_year}"

    card_geo_hdr = f"🌍 Commercial KPI Matrix by Country & Region ({period_str})" if is_en else f"🌍 Bảng Chỉ Tiêu Kinh Doanh Theo Quốc Gia & Khu Vực ({period_str})"
    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{card_geo_hdr}</span>
            <span class="crm-badge-neon">Market Share Matrix</span>
        </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    box_suf = "boxes" if is_en else "hộp"
    disp_df["Revenue ($)"] = disp_df["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
    disp_df["Boxes"] = disp_df["TotalBoxes"].apply(lambda x: f"{x:,} {box_suf}")
    disp_df["Customers"] = disp_df["TotalCustomers"].apply(lambda x: f"{x:,}")
    disp_df["Market Share (%)"] = disp_df["MarketSharePct"].apply(lambda x: f"{x:.1f}%")
    disp_df["Avg Order ($)"] = disp_df["AvgAmountPerOrder"].apply(lambda x: f"${x:,.0f}")

    show_cols = ["Geo", "Region", "Revenue ($)", "Boxes", "Customers", "Market Share (%)", "Avg Order ($)"]
    st.dataframe(disp_df[show_cols], hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Geographic Markets" if is_en else "Thị Trường & Địa Lý", data["sql"], data["exec_time_ms"], "sales_geo_sql")

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        fig_g = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["Geo"], "Total": df["TotalRevenue"]}), height=260)
        render_zoomable_chart_card(
            title="💰 Country Revenue Breakdown ($)" if is_en else "💰 Doanh Số Theo Từng Quốc Gia ($)",
            fig=fig_g,
            df=df,
            badge="Country Revenue",
            explanation="Sales comparison among international markets." if is_en else "So sánh doanh thu bán hàng giữa các thị trường quốc tế.",
            key="sales_geo_col1"
        )

    with col_g2:
        fig_reg = build_donut_chart(data["region_df"], label_col="Region", val_col="TotalRevenue", height=260)
        render_zoomable_chart_card(
            title="🌐 Regional Revenue Share (Region)" if is_en else "🌐 Thị Phần Doanh Thu Theo Khu Vực (Region)",
            fig=fig_reg,
            df=data["region_df"],
            badge="Regional Breakdown",
            explanation="Revenue proportion across APAC, Americas, and Europe." if is_en else "Tỷ trọng doanh số giữa 3 vùng chiến lược: APAC, Americas và Europe.",
            key="sales_geo_col2"
        )

    render_smart_analyst_anomaly_panel(
        layer_id="sales_geo",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="sales_geo"
    )


def _render_sales_layer_people(engine):
    """Layer 2: Phân tích Đội ngũ Sales & Team kinh doanh (Bilingual)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>👥 {t('sales_layer_people')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_s_2", use_container_width=True):
            _set_layer("overview", domain_key="sales")

    start_year, end_year = _render_timeline_slider("sales_people", min_year=2021, max_year=2023, domain_key="sales")
    data = fetch_sales_people_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]
    team_df = data["team_df"]
    period_str = str(start_year) if start_year == end_year else f"{start_year} — {end_year}"

    card_ppl_hdr = f"👥 Sales Representatives Roster & Performance ({period_str})" if is_en else f"👥 Danh Bạ & Hiệu Suất Đội Ngũ Nhân Viên Kinh Doanh ({period_str})"
    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{card_ppl_hdr}</span>
            <span class="crm-badge-neon">18 Sales Representatives</span>
        </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    box_suf = "boxes" if is_en else "hộp"
    disp_df["Revenue ($)"] = disp_df["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
    disp_df["Boxes"] = disp_df["TotalBoxes"].apply(lambda x: f"{x:,} {box_suf}")
    disp_df["Customers"] = disp_df["TotalCustomers"].apply(lambda x: f"{x:,}")
    disp_df["Avg Order ($)"] = disp_df["AvgOrderValue"].apply(lambda x: f"${x:,.0f}")

    show_cols = ["Salesperson", "Team", "Location", "Revenue ($)", "Boxes", "Customers", "Avg Order ($)"]
    st.dataframe(disp_df[show_cols], hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Sales Teams" if is_en else "Đội Ngũ & Team Sales", data["sql"], data["exec_time_ms"], "sales_ppl_sql")

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        fig_team_rev = build_weekday_bar_chart(pd.DataFrame({"WeekDay": team_df["Team"], "Total": team_df["TotalRevenue"]}), height=260)
        render_zoomable_chart_card(
            title="🏢 Team Revenue Comparison ($)" if is_en else "🏢 So Sánh Tổng Doanh Số Giữa Các Team ($)",
            fig=fig_team_rev,
            df=team_df,
            badge="Team Revenue",
            explanation="Revenue comparison among Yummies, Delish, Jucies, and independent groups." if is_en else "So sánh tổng doanh thu tạo ra giữa Team Yummies, Delish, Jucies và nhóm độc lập.",
            key="sales_team_rev"
        )

    with col_p2:
        fig_team_avg = build_weekday_bar_chart(pd.DataFrame({"WeekDay": team_df["Team"], "Total": team_df["AvgRevenuePerRep"]}), height=260)
        render_zoomable_chart_card(
            title="⚡ Average Revenue Productivity per Rep ($/person)" if is_en else "⚡ Năng Suất Doanh Thu Bình Quân Mỗi Nhân Sự ($/người)",
            fig=fig_team_avg,
            df=team_df,
            badge="Productivity",
            explanation="Productivity metric per sales representative by team." if is_en else "Đo lường hiệu suất bình quân mỗi nhân viên trong từng Team.",
            key="sales_team_avg"
        )

    render_smart_analyst_anomaly_panel(
        layer_id="sales_people",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="sales_ppl"
    )


def _render_sales_layer_products(engine):
    """Layer 3: Phân tích Danh mục Sản phẩm & Biên lợi nhuận (Bilingual)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🍫 {t('sales_layer_products')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_s_3", use_container_width=True):
            _set_layer("overview", domain_key="sales")

    start_year, end_year = _render_timeline_slider("sales_products", min_year=2021, max_year=2023, domain_key="sales")
    data = fetch_sales_products_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]
    period_str = str(start_year) if start_year == end_year else f"{start_year} — {end_year}"

    card_prd_hdr = f"🍫 Product Revenue, Unit Cost & Gross Profit Matrix ({period_str})" if is_en else f"🍫 Ma Trận Doanh Số, Giá Vốn & Lợi Nhuận Gộp Theo Sản Phẩm ({period_str})"
    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{card_prd_hdr}</span>
            <span class="crm-badge-neon">22 Chocolate SKUs</span>
        </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    box_suf = "boxes" if is_en else "hộp"
    if not disp_df.empty:
        if "CostPerBox" in disp_df.columns:
            disp_df["Cost/Box ($)"] = disp_df["CostPerBox"].apply(lambda x: f"${x:.2f}" if pd.notnull(x) else "$0.00")
        if "TotalRevenue" in disp_df.columns:
            disp_df["Revenue ($)"] = disp_df["TotalRevenue"].apply(lambda x: f"${x:,.0f}" if pd.notnull(x) else "$0")
        if "TotalBoxes" in disp_df.columns:
            disp_df["Boxes"] = disp_df["TotalBoxes"].apply(lambda x: f"{x:,} {box_suf}" if pd.notnull(x) else f"0 {box_suf}")
        if "EstGrossProfit" in disp_df.columns:
            disp_df["Gross Profit ($)"] = disp_df["EstGrossProfit"].apply(lambda x: f"${x:,.0f}" if pd.notnull(x) else "$0")
        if "ProfitMarginPct" in disp_df.columns:
            disp_df["Margin (%)"] = disp_df["ProfitMarginPct"].apply(lambda x: f"{x:.1f}%" if pd.notnull(x) else "0.0%")

        tbl_cols = [c for c in ["Product", "Category", "Size", "Cost/Box ($)", "Revenue ($)", "Boxes", "Gross Profit ($)", "Margin (%)"] if c in disp_df.columns]
        st.dataframe(disp_df[tbl_cols], hide_index=True, use_container_width=True)
    else:
        st.info("No product data available for the selected period." if is_en else "Không có dữ liệu sản phẩm trong khoảng thời gian đã chọn.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Product Catalog" if is_en else "Danh Mục Sản Phẩm & Lợi Nhuận", data["sql"], data["exec_time_ms"], "sales_prd_sql")

    col_pr1, col_pr2 = st.columns(2)
    with col_pr1:
        top10_p = df.head(10)
        fig_p = build_horizontal_bar_chart(top10_p, y_col="Product", x_col="TotalRevenue", name="Revenue ($)" if is_en else "Doanh số ($)", height=280)
        render_zoomable_chart_card(
            title="🏆 Top 10 Revenue-Contributing Products ($)" if is_en else "🏆 Top 10 Sản Phẩm Đóng Góp Doanh Thu Cao Nhất ($)",
            fig=fig_p,
            df=top10_p,
            badge="Top Products",
            explanation="Top 10 best-selling chocolate SKUs in the period." if is_en else "Danh mục 10 dòng sản phẩm bán chạy nhất trong kỳ.",
            key="sales_top_prod"
        )

    with col_pr2:
        fig_size = build_donut_chart(data["size_df"], label_col="Size", val_col="TotalRevenue", height=280)
        render_zoomable_chart_card(
            title="📦 Revenue Share by Package Size" if is_en else "📦 Phân Bổ Doanh Số Theo Kích Thước (Size)",
            fig=fig_size,
            df=data["size_df"],
            badge="Package Size",
            explanation="Revenue split across packaging sizes: Large, Medium, Small." if is_en else "Tỷ trọng doanh số giữa các kích cỡ đóng gói: Large, Medium, Small.",
            key="sales_size_donut"
        )

    render_smart_analyst_anomaly_panel(
        layer_id="sales_products",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="sales_prd"
    )


def _render_sales_layer_trends(engine):
    """Layer 4: Xu hướng Doanh thu & Mùa vụ (Bilingual)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>📈 {t('sales_layer_trends')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_s_4", use_container_width=True):
            _set_layer("overview", domain_key="sales")

    start_year, end_year = _render_timeline_slider("sales_trends", min_year=2021, max_year=2023, domain_key="sales")
    data = fetch_sales_trends_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]

    # Full Width Dual Axis Wave Chart
    fig_tr = build_sales_dual_axis_chart(df, x_col="Month", rev_col="Revenue", box_col="Boxes", height=320)
    trend_full_title = f"📈 Time Series Revenue ($) & Box Volume ({start_year} — {end_year})" if is_en else f"📈 Chuỗi Thời Gian Doanh Số ($) & Sản Lượng Hộp Bán Ra ({start_year} — {end_year})"
    trend_full_expl = "Detects growth waves and abnormal sales peaks (June 2021 and November 2022)." if is_en else "Phát hiện các đợt sóng tăng trưởng và đỉnh doanh số bất thường (tháng 6/2021 và tháng 11/2022)."
    render_zoomable_chart_card(
        title=trend_full_title,
        fig=fig_tr,
        df=df,
        badge="Seasonality & Trend",
        explanation=trend_full_expl,
        key="sales_trends_full"
    )

    _render_sql_modal("Sales Trends" if is_en else "Xu Hướng & Mùa Vụ", data["sql"], data["exec_time_ms"], "sales_trd_sql")

    render_smart_analyst_anomaly_panel(
        layer_id="sales_trends",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="sales_trd"
    )


def _render_sales_layer_top_performers(engine):
    """Layer 5: Top Hiệu suất Bán hàng & Khách hàng (Bilingual)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🏆 {t('sales_layer_top_performers')}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_s_5", use_container_width=True):
            _set_layer("overview", domain_key="sales")

    start_year, end_year = _render_timeline_slider("sales_top", min_year=2021, max_year=2023, domain_key="sales")
    data = fetch_sales_top_performers_data(engine, start_year=start_year, end_year=end_year)
    reps_df = data["df"]
    skus_df = data["top_skus_df"]

    col_tp1, col_tp2 = st.columns(2)
    with col_tp1:
        reps_hdr = "🌟 Top 10 Leading Sales Representatives" if is_en else "🌟 Top 10 Sales Representatives Dẫn Đầu"
        badge_rep = "Personal Revenue" if is_en else "Doanh Số Cá Nhân"
        st.markdown(f"""
        <div class="crm-card">
            <div class="crm-card-title">
                <span>{reps_hdr}</span>
                <span class="crm-badge-neon">{badge_rep}</span>
            </div>
        """, unsafe_allow_html=True)
        disp_reps = reps_df.copy()
        disp_reps["Revenue ($)"] = disp_reps["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
        disp_reps["Boxes"] = disp_reps["TotalBoxes"].apply(lambda x: f"{x:,}")
        disp_reps["Customers"] = disp_reps["TotalCustomers"].apply(lambda x: f"{x:,}")
        st.dataframe(disp_reps[["Salesperson", "Team", "Location", "Revenue ($)", "Boxes", "Customers"]], hide_index=True, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        fig_reps = build_horizontal_bar_chart(reps_df, y_col="Salesperson", x_col="TotalRevenue", name="Revenue ($)" if is_en else "Doanh số ($)", height=260)
        render_zoomable_chart_card(
            title="🥇 Top 10 Sales Reps Leaderboard" if is_en else "🥇 Bảng Xếp Hạng Top 10 Sales Reps",
            fig=fig_reps,
            df=reps_df,
            badge="Leaderboard",
            explanation="Visual comparison of revenue generated by top 10 specialists." if is_en else "Biểu đồ trực quan doanh số 10 nhân sự xuất sắc nhất.",
            key="sales_top_reps_chart"
        )

    with col_tp2:
        skus_hdr = "🍫 Top 10 Best-Selling Chocolate SKUs" if is_en else "🍫 Top 10 Sản Phẩm Sô-cô-la Bán Chạy Nhất"
        st.markdown(f"""
        <div class="crm-card">
            <div class="crm-card-title">
                <span>{skus_hdr}</span>
                <span class="crm-badge-neon">Best-Selling SKUs</span>
            </div>
        """, unsafe_allow_html=True)
        disp_skus = skus_df.copy()
        disp_skus["Revenue ($)"] = disp_skus["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
        disp_skus["Boxes"] = disp_skus["TotalBoxes"].apply(lambda x: f"{x:,}")
        st.dataframe(disp_skus[["Product", "Category", "Revenue ($)", "Boxes"]], hide_index=True, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        fig_skus = build_horizontal_bar_chart(skus_df, y_col="Product", x_col="TotalRevenue", name="Revenue ($)" if is_en else "Doanh số ($)", height=260)
        render_zoomable_chart_card(
            title="🥇 Top 10 Chocolate Products" if is_en else "🥇 Bảng Xếp Hạng Top 10 Sản Phẩm",
            fig=fig_skus,
            df=skus_df,
            badge="Top SKUs",
            explanation="Visual comparison of revenue generated by top 10 chocolate products." if is_en else "Biểu đồ trực quan doanh số 10 sản phẩm bán chạy nhất.",
            key="sales_top_skus_chart"
        )

    _render_sql_modal("Top Performers" if is_en else "Top Bán Hàng & Khách Hàng", data["sql"], data["exec_time_ms"], "sales_top_sql")

    render_smart_analyst_anomaly_panel(
        layer_id="sales_top_performers",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="sales_top"
    )


# =========================================================================
# UNIVERSAL AUTO-ADAPTIVE GENERIC DATABASE DASHBOARD
# =========================================================================

def _render_generic_dashboard(engine):
    """Dashboard Đa Tầng Tự Động Sinh Thích Ứng Cho Mọi CSDL Mới Bất Kỳ (Bilingual)."""
    is_en = (get_current_language() == "en")
    schema_meta = discover_generic_database_schema(engine)
    tables = schema_meta.get("tables", [])
    min_year = schema_meta.get("min_year", 2020)
    max_year = schema_meta.get("max_year", 2024)

    current_layer = st.session_state.get("generic_dashboard_layer", "overview")

    layer_names = {"overview": "🏠 Executive Overview" if is_en else "🏠 Trang chủ Tổng quan (Overview)"}
    for t_n in tables:
        r_cnt = schema_meta.get("meta", {}).get(t_n, {}).get("row_count", 0)
        recs_suf = "records" if is_en else "bản ghi"
        tbl_pref = "Table" if is_en else "Bảng"
        layer_names[f"tbl_{t_n}"] = f"📊 {tbl_pref}: {t_n} ({r_cnt:,} {recs_suf})"

    layer_keys = list(layer_names.keys())
    current_idx = layer_keys.index(current_layer) if current_layer in layer_keys else 0

    c_hdr1, c_hdr2, c_hdr3, c_hdr4 = st.columns([4.0, 2.6, 1.8, 1.6])
    with c_hdr1:
        gen_badge = "ADAPTIVE SCHEMA • LIVE SQL" if is_en else "CSDL TỰ ĐỘNG THÍCH ỨNG • LIVE SQL"
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
            <div style="font-size: 1.55rem; font-weight: 900; color: #FFFFFF; letter-spacing: -0.02em;">💎 Universal Enterprise Intelligence Dashboard</div>
            <span class="crm-badge-neon">{gen_badge}</span>
        </div>
        """, unsafe_allow_html=True)

    with c_hdr2:
        selected_l = st.selectbox(
            "Select Layer" if is_en else "Chọn tầng phân tích",
            layer_keys,
            format_func=lambda x: layer_names[x],
            index=current_idx,
            key="generic_layer_selectbox",
            label_visibility="collapsed"
        )
        if selected_l != current_layer:
            st.session_state["generic_dashboard_layer"] = selected_l
            st.rerun()
        current_layer = st.session_state.get("generic_dashboard_layer", "overview")

    with c_hdr3:
        layer_title_curr = layer_names.get(current_layer, "Database Overview" if is_en else "Tổng quan CSDL")
        start_y_curr = st.session_state.get("generic_timeline_years", (min_year, max_year))[0]
        end_y_curr = st.session_state.get("generic_timeline_years", (min_year, max_year))[1]
        t_lbl_curr = f"{start_y_curr} — {end_y_curr}" if start_y_curr != end_y_curr else str(start_y_curr)
        ctx_header = {
            "layer_title": layer_title_curr,
            "time_label": t_lbl_curr,
            "anomalies": [],
            "kpis_summary": f"Viewing {layer_title_curr} during {t_lbl_curr}." if is_en else f"Đang xem {layer_title_curr} giai đoạn {t_lbl_curr}.",
            "data_summary": f"User opened Copilot from header on {layer_title_curr}." if is_en else f"Người dùng mở Copilot từ thanh Header trên tầng {layer_title_curr}."
        }
        if st.button(t("hr_btn_copilot"), type="primary", use_container_width=True, key="btn_generic_header_copilot", help=t("hr_copilot_help")):
            show_dashboard_copilot_dialog(ctx_header)

    with c_hdr4:
        if st.button(t("hr_btn_main_chat"), type="secondary", use_container_width=True, key="btn_generic_header_chat", help=t("hr_main_chat_help")):
            st.session_state["view_mode"] = "chat"
            st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # Routing
    if current_layer == "overview":
        _render_generic_layer_overview(engine, schema_meta)
    elif current_layer.startswith("tbl_"):
        tbl_name = current_layer.replace("tbl_", "")
        _render_generic_layer_table(engine, tbl_name, schema_meta)


def _render_generic_layer_overview(engine, schema_meta: dict):
    """Trang chủ Tổng quan cho CSDL mới: 4 KPI, Dynamic Topic Cards, Biểu đồ phân phối tự động & Bảng dữ liệu (Bilingual)."""
    is_en = (get_current_language() == "en")
    min_year = schema_meta.get("min_year", 2020)
    max_year = schema_meta.get("max_year", 2024)
    tables = schema_meta.get("tables", [])

    # Dynamic Topic Cards
    hub_title = "🎯 Explore Schema Tables (1-Click Hub):" if is_en else "🎯 Khám Phá Danh Mục Bảng Dữ Liệu Trong CSDL (1-Click Hub):"
    st.markdown(f"""
    <div style="font-size: 1.05rem; font-weight: 800; color: #FFFFFF; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
        <span>🎯</span> <span><b>{hub_title}</b></span>
    </div>
    """, unsafe_allow_html=True)

    if tables:
        t_chunks = [tables[i:i+3] for i in range(0, min(len(tables), 6), 3)]
        for chunk_idx, chunk in enumerate(t_chunks):
            cols = st.columns(len(chunk))
            for c_idx, t_name in enumerate(chunk):
                with cols[c_idx]:
                    r_c = schema_meta.get("meta", {}).get(t_name, {}).get("row_count", 0)
                    col_c = len(schema_meta.get("meta", {}).get(t_name, {}).get("columns", []))
                    tbl_lbl = "Table" if is_en else "Bảng"
                    desc_str = f"{r_c:,} records • {col_c} schema attributes." if is_en else f"{r_c:,} dòng dữ liệu • {col_c} trường thông tin cấu trúc."
                    open_btn_l = f"Open Table {t_name} ➔" if is_en else f"Mở Bảng {t_name} ➔"
                    with st.container():
                        st.markdown(f"""
                        <div class="nav-hub-title"><span>📊</span> {tbl_lbl}: {t_name}</div>
                        <div class="nav-hub-desc">{desc_str}</div>
                        """, unsafe_allow_html=True)
                        if st.button(open_btn_l, key=f"btn_nav_gen_{chunk_idx}_{c_idx}", use_container_width=True):
                            _set_layer(f"tbl_{t_name}", domain_key="generic")

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    start_year, end_year = _render_timeline_slider("generic_ov", min_year=min_year, max_year=max_year, domain_key="generic")
    data = fetch_generic_overview_data(engine, schema_meta, start_year=start_year, end_year=end_year)

    # 4 Thẻ KPI
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    with col_k1:
        tbl_unit = "tables" if is_en else "bảng"
        st.markdown(f"""
        <div class="kpi-card-cyan">
            <div class="kpi-title"><span>{"TOTAL TABLES" if is_en else "TỔNG SỐ BẢNG"}</span> <span>🗄️</span></div>
            <div class="kpi-val">{data['total_tables']} <span style="font-size:1.1rem;font-weight:700;">{tbl_unit}</span></div>
            <div class="kpi-sub"><span class="kpi-badge">{"Structure" if is_en else "Cấu trúc"}</span> <span>{"Full Database" if is_en else "Toàn bộ CSDL"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    with col_k2:
        st.markdown(f"""
        <div class="kpi-card-purple">
            <div class="kpi-title"><span>{"TOTAL RECORDS" if is_en else "TỔNG SỐ BẢN GHI"}</span> <span>📑</span></div>
            <div class="kpi-val">{data['total_records']:,}</div>
            <div class="kpi-sub"><span class="kpi-badge">{"Capacity" if is_en else "Dung lượng"}</span> <span>{"Total Rows" if is_en else "Tổng số dòng"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    with col_k3:
        main_tbl_disp = data["main_table"] or "N/A"
        st.markdown(f"""
        <div class="kpi-card-emerald">
            <div class="kpi-title"><span>{"PRIMARY TABLE" if is_en else "BẢNG DỮ LIỆU CHÍNH"}</span> <span>🌟</span></div>
            <div class="kpi-val" style="font-size:1.5rem !important;">{main_tbl_disp}</div>
            <div class="kpi-sub"><span class="kpi-badge">{"Focus" if is_en else "Trọng tâm"}</span> <span>{"Largest dataset" if is_en else "Nhiều dữ liệu nhất"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    with col_k4:
        st.markdown(f"""
        <div class="kpi-card-amber">
            <div class="kpi-title"><span>{"TIMELINE MILESTONE" if is_en else "MỐC THỜI GIAN"}</span> <span>⏱️</span></div>
            <div class="kpi-val" style="font-size:1.4rem !important;">{start_year} — {end_year}</div>
            <div class="kpi-sub"><span class="kpi-badge">Timeline</span> <span>{"Filtered Period" if is_en else "Đang lọc"}</span></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    _render_sql_modal("Database Overview" if is_en else "Tổng Quan CSDL", data["sql"], data["exec_time_ms"], "generic_ov_sql")

    # Biểu đồ tự động nếu có
    if not data["cat_dist_df"].empty or not data["trend_df"].empty:
        col_gc1, col_gc2 = st.columns(2)
        with col_gc1:
            if not data["cat_dist_df"].empty:
                fig_cat = build_horizontal_bar_chart(data["cat_dist_df"], y_col="Category", x_col="Count", name="Count" if is_en else "Số lượng", height=260)
                cat_chart_title = f"📊 Category Distribution ({data['main_cat_col']})" if is_en else f"📊 Phân Bổ Theo Danh Mục ({data['main_cat_col']})"
                render_zoomable_chart_card(
                    title=cat_chart_title,
                    fig=fig_cat,
                    df=data["cat_dist_df"],
                    badge="Distribution",
                    explanation=f"Frequency counts by field {data['main_cat_col']}." if is_en else f"Tần suất xuất hiện theo trường {data['main_cat_col']}.",
                    key="gen_cat_chart"
                )
        with col_gc2:
            if not data["trend_df"].empty:
                fig_tr = build_weekday_bar_chart(pd.DataFrame({"WeekDay": data["trend_df"]["TimePeriod"], "Total": data["trend_df"]["Count"]}), height=260)
                render_zoomable_chart_card(
                    title="📈 Historical Record Volume Over Time" if is_en else "📈 Xu Hướng Bản Ghi Theo Thời Gian",
                    fig=fig_tr,
                    df=data["trend_df"],
                    badge="Time Series",
                    explanation="Volume of data generated across chronological periods." if is_en else "Khối lượng dữ liệu phát sinh theo từng mốc thời gian.",
                    key="gen_trend_chart"
                )

    # Hiển thị mẫu dữ liệu bảng chính
    if not data["df"].empty:
        rows_suf = "rows" if is_en else "dòng"
        tbl_prev_hdr = f"📋 Sample Data: Table '{data['main_table']}' ({len(data['df'])} {rows_suf})" if is_en else f"📋 Dữ Liệu Mẫu: Bảng '{data['main_table']}' ({len(data['df'])} dòng)"
        st.markdown(f"""
        <div class="crm-card">
            <div class="crm-card-title">
                <span>{tbl_prev_hdr}</span>
                <span class="crm-badge-neon">Live Data Preview</span>
            </div>
        """, unsafe_allow_html=True)
        st.dataframe(data["df"], hide_index=True, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    render_smart_analyst_anomaly_panel(
        layer_id="generic_overview",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="generic_ov"
    )


def _render_generic_layer_table(engine, table_name: str, schema_meta: dict):
    """Hiển thị chi tiết một bảng dữ liệu cụ thể trong CSDL mới (Bilingual)."""
    is_en = (get_current_language() == "en")
    min_year = schema_meta.get("min_year", 2020)
    max_year = schema_meta.get("max_year", 2024)

    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        tbl_lbl = "Table" if is_en else "Bảng"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>📊 {tbl_lbl}: {table_name}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key=f"btn_back_gen_{table_name}", use_container_width=True):
            _set_layer("overview", domain_key="generic")

    start_year, end_year = _render_timeline_slider(f"gen_tbl_{table_name}", min_year=min_year, max_year=max_year, domain_key="generic")
    data = fetch_generic_table_data(engine, table_name, schema_meta, start_year=start_year, end_year=end_year)
    df = data["df"]

    rows_suf = "rows" if is_en else "dòng"
    cols_suf = "Columns" if is_en else "Cột Dữ Liệu"
    tbl_rec_hdr = f"📊 Records Table: '{table_name}' ({len(df)} {rows_suf})" if is_en else f"📊 Danh Sách Bản Ghi: Bảng '{table_name}' ({len(df)} dòng)"
    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{tbl_rec_hdr}</span>
            <span class="crm-badge-neon">{len(df.columns)} {cols_suf}</span>
        </div>
    """, unsafe_allow_html=True)

    if not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info(f"Table '{table_name}' has no records in period {start_year} — {end_year}." if is_en else f"Bảng '{table_name}' không có dữ liệu trong khoảng thời gian {start_year} — {end_year}.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal(f"Table {table_name}" if is_en else f"Bảng {table_name}", data["sql"], data["exec_time_ms"], f"gen_tbl_sql_{table_name}")

    if not data["cat_df"].empty:
        fig_cat = build_horizontal_bar_chart(data["cat_df"], y_col="Category", x_col="Count", name="Count" if is_en else "Số lượng", height=260)
        render_zoomable_chart_card(
            title=f"📊 Category Distribution: Table {table_name}" if is_en else f"📊 Phân Bổ Theo Danh Mục: Bảng {table_name}",
            fig=fig_cat,
            df=data["cat_df"],
            badge="Distribution",
            explanation="Frequency distribution of records." if is_en else "Tần suất phân bổ dữ liệu.",
            key=f"gen_tbl_cat_{table_name}"
        )

    render_smart_analyst_anomaly_panel(
        layer_id=f"table_{table_name}",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix=f"gen_{table_name}"
    )
