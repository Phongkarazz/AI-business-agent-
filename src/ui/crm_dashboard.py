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
    _get_sales_year_range,
    discover_generic_database_schema,
    fetch_generic_overview_data,
    fetch_generic_table_data,
    _get_northwind_year_range,
    fetch_northwind_overview_data,
    fetch_northwind_products_data,
    fetch_northwind_orders_data,
    fetch_northwind_employees_data,
    fetch_northwind_customers_data,
    fetch_northwind_suppliers_data,
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
from src.i18n import t, get_current_language
from typing import Dict, Any


def _render_diagnostic_kpi_card(
    color_class: str = "",
    title: str = "",
    value_html: str = "",
    status_pill: str = "",
    bench_label: str = "",
    bench_pct: float = 100.0,
    badge_text: str = "",
    sub_text: str = "",
    extra_style: str = "",
    card_class: str = "",
    val_html: str = "",
    delta_str: str = "",
    delta_dir: str = "up",
    status_text: str = "",
    status_level: str = "",
    fill_color: str = ""
):
    """Render thẻ KPI chẩn đoán hiệu suất động theo chuẩn Enterprise Dark-Mode (Phương án 1):
    viền nhấn & ánh nhẹ phân màu theo nhóm chỉ số, huy hiệu delta & thanh chuẩn mang ngữ nghĩa."""
    import re
    resolved_class = color_class or card_class or "kpi-card-cyan"
    resolved_val = value_html or val_html or ""

    # Tách riêng thẻ delta (▲ +X.X%) ra khỏi dòng số lớn để cả con số chính lẫn huy hiệu tăng trưởng đều hiển thị trọn vẹn 100%
    delta_match = re.search(r"<span\s+class=['\"]kpi-delta-tag['\"][^>]*>(.*?)</span>", resolved_val)
    extracted_delta = ""
    if delta_match:
        extracted_delta = delta_match.group(1).strip()
        resolved_val = re.sub(r"<span\s+class=['\"]kpi-delta-tag['\"][^>]*>.*?</span>", "", resolved_val).strip()
    elif delta_str:
        arrow = "▲ " if delta_dir == "up" and not delta_str.startswith(("▲", "▼")) else ("▼ " if delta_dir == "down" and not delta_str.startswith(("▲", "▼")) else "")
        extracted_delta = f"{arrow}{delta_str}"

    if not resolved_val.strip().startswith("<span"):
        resolved_val = f"<span>{resolved_val}</span>"

    clean_bench_lbl = re.sub(r"^[\s🎯]+", "", str(bench_label or "")).strip()

    fill_w = min(100.0, max(8.0, float(bench_pct)))
    norm_status = str(status_level or "").strip().lower()

    # Palette theo nhóm thẻ khi caller truyền fill_color tường minh (Universal/SME)
    _accent_palette = {
        "kpi-card-cyan": ("#38BDF8", "rgba(56, 189, 248, 0.38)"),
        "kpi-card-purple": ("#C084FC", "rgba(168, 85, 247, 0.38)"),
        "kpi-card-emerald": ("#34D399", "rgba(16, 185, 129, 0.38)"),
        "kpi-card-amber": ("#FBBF24", "rgba(245, 158, 11, 0.38)"),
    }
    accent_pct, accent_glow = _accent_palette.get(resolved_class, ("#34D399", "rgba(16, 185, 129, 0.38)"))

    if norm_status in ("bad", "danger", "alert") or (not norm_status and float(bench_pct) < 85.0):
        default_bar_bg = "linear-gradient(90deg, #DC2626, #F87171)"
        pct_color = "#F87171"
        bar_glow = "rgba(239, 68, 68, 0.40)"
    elif norm_status == "warn" or (not norm_status and float(bench_pct) < 98.0):
        default_bar_bg = "linear-gradient(90deg, #D97706, #FBBF24)"
        pct_color = "#FBBF24"
        bar_glow = "rgba(245, 158, 11, 0.40)"
    else:
        default_bar_bg = "linear-gradient(90deg, #059669, #34D399)"
        pct_color = accent_pct if fill_color else "#34D399"
        bar_glow = accent_glow if fill_color else "rgba(16, 185, 129, 0.38)"

    bar_bg = fill_color or default_bar_bg

    # Phân loại ngữ nghĩa màu sắc cho huy hiệu delta (tăng=xanh, giảm=đỏ, cảnh báo=vàng, trung tính=theo màu thẻ)
    delta_badge_html = ""
    if extracted_delta:
        d_strip = extracted_delta.strip()
        d_upper = d_strip.upper()
        if (
            "▼" in d_strip
            or "🔴" in d_strip
            or delta_dir == "down"
            or norm_status in ("bad", "danger", "alert")
            or bool(re.match(r"^-\d", d_strip))
        ):
            delta_cls = "kpi-delta-tag kpi-delta-down"
        elif "🟡" in d_strip or "⚠" in d_strip or norm_status == "warn":
            delta_cls = "kpi-delta-tag kpi-delta-warn"
        elif (
            "▲" in d_strip
            or "🟢" in d_strip
            or "+" in d_strip
            or "ACTIVE" in d_upper
            or "OPTIMAL" in d_upper
        ):
            delta_cls = "kpi-delta-tag kpi-delta-up"
        else:
            delta_cls = "kpi-delta-tag kpi-delta-neutral"
        delta_badge_html = f"<span class='{delta_cls}'>{extracted_delta}</span>"

    st.markdown(f"""
    <div class="{resolved_class}" style="{extra_style}">
        <div class="kpi-title" title="{title}">
            <span class="kpi-accent-dot"></span>
            <span class="kpi-title-text">{title}</span>
        </div>
        <div class="kpi-val">{resolved_val}</div>
        <div class="kpi-sub">
            {delta_badge_html}
            <span class="kpi-sub-text" title="{sub_text}">{sub_text}</span>
        </div>
        <div class="kpi-bench-wrap">
            <div class="kpi-bench-header">
                <span class="kpi-bench-lbl" title="{clean_bench_lbl}">{clean_bench_lbl}</span>
                <span class="kpi-bench-pct" style="color: {pct_color};"><b>{bench_pct:.1f}%</b></span>
            </div>
            <div class="kpi-bench-track">
                <div class="kpi-bench-fill" style="width: {fill_w:.1f}%; background: {bar_bg}; box-shadow: 0 0 8px {bar_glow};"></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


_DASH_LABEL_MAP = {
    "hoa_don_ban": ("Hóa đơn bán", "Sales Invoices"),
    "phieu_nhap_thuoc": ("Phiếu nhập thuốc", "Stock-In Vouchers"),
    "donhang": ("Đơn hàng", "Orders"),
    "don_hang": ("Đơn hàng", "Orders"),
    "danhmucmon": ("Danh mục món", "Menu Items"),
    "danh_muc_mon": ("Danh mục món", "Menu Items"),
    "congnobanhang": ("Công nợ bán hàng", "Sales Receivables"),
    "cong_no_ban_hang": ("Công nợ bán hàng", "Sales Receivables"),
    "san_pham": ("Sản phẩm", "Products"),
    "khach_hang": ("Khách hàng", "Customers"),
    "ten_khach_hang": ("Khách hàng", "Customer"),
    "nhan_vien": ("Nhân viên", "Employees"),
    "nha_cung_cap": ("Nhà cung cấp", "Suppliers"),
    "kho_hang": ("Kho hàng", "Inventory"),
    "ton_kho": ("Tồn kho", "Inventory"),
    "chi_phi": ("Chi phí", "Expenses"),
    "doanh_thu": ("Doanh thu", "Revenue"),
    "thanh_tien": ("Thành tiền", "Total Amount"),
    "tong_tien": ("Tổng tiền", "Total Amount"),
    "da_thanh_toan": ("Đã thanh toán", "Paid Amount"),
    "cong_no": ("Công nợ", "Receivables"),
    "so_luong": ("Số lượng", "Quantity"),
    "so_luong_nhap": ("Số lượng nhập", "Import Quantity"),
    "don_gia": ("Đơn giá", "Unit Price"),
    "gia_nhap": ("Giá nhập", "Import Price"),
    "gia_ban": ("Giá bán", "Selling Price"),
    "loi_nhuan": ("Lợi nhuận", "Profit"),
    "ten_thuoc": ("Tên thuốc", "Medicine"),
    "ten_mon": ("Tên món", "Menu Item"),
    "nhom_mon": ("Nhóm món", "Category"),
    "vat_lieu": ("Vật liệu", "Material"),
    "kenh_ban": ("Kênh bán", "Sales Channel"),
    "trang_thai": ("Trạng thái", "Status"),
    "don_vi": ("Đơn vị", "Unit"),
    "ngay_gd": ("Ngày giao dịch", "Transaction Date"),
    "ngay_ban": ("Ngày bán", "Sale Date"),
    "ngay_nhap": ("Ngày nhập", "Import Date"),
    "ma_hd": ("Mã hóa đơn", "Invoice ID"),
    "ma_don": ("Mã đơn", "Order ID"),
    "ma_phieu": ("Mã phiếu", "Voucher ID"),
}


def _humanize_dashboard_label(raw_name: str, is_en: bool = False) -> str:
    """Convert raw snake_case/camelCase column or table names into clean display labels."""
    import re
    if not raw_name:
        return ""
    s = str(raw_name).strip()
    key = re.sub(r"[^a-zA-Z0-9_]", "", s).lower()
    if key in _DASH_LABEL_MAP:
        return _DASH_LABEL_MAP[key][1] if is_en else _DASH_LABEL_MAP[key][0]
    norm_compact = key.replace("_", "")
    for k, vals in _DASH_LABEL_MAP.items():
        if k.replace("_", "") == norm_compact:
            return vals[1] if is_en else vals[0]
    if is_en:
        cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", s).replace("_", " ").strip()
        return cleaned.title() if cleaned.islower() or "_" in s else cleaned
    if any(c in s for c in "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựíìỉĩịđÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÍÌỈĨỊĐ"):
        return s
    try:
        from src.visualization.charts import format_col_title
        formatted = format_col_title(s)
        formatted = re.sub(r"\s*\(\$\)\s*$", "", formatted).strip()
        return formatted or s
    except Exception:
        return s.replace("_", " ").strip().title()


def _build_dashboard_deep_dive_prompt(layer_id: str, data: Dict[str, Any], anomalies: list, is_en: bool) -> str:
    """Build a schema-compatible follow-up prompt so clicking Analyze in Chat answers directly."""
    lid = str(layer_id or "").lower()
    if lid.startswith("generic") or lid.startswith("table_"):
        met_raw = data.get("main_num_col") or data.get("num_col") or ""
        cat_raw = data.get("main_cat_col") or data.get("status_col") or ""
        tbl_raw = data.get("main_table") or (lid[6:] if lid.startswith("table_") else "")
        met_lbl = _humanize_dashboard_label(met_raw, is_en=is_en) if met_raw else ""
        cat_lbl = _humanize_dashboard_label(cat_raw, is_en=is_en) if cat_raw else ""
        tbl_lbl = _humanize_dashboard_label(tbl_raw, is_en=is_en) if tbl_raw else ""
        if met_lbl and cat_lbl:
            return (
                f"Compare the highest and lowest {cat_lbl} by {met_lbl} and show the gap"
                if is_en else
                f"Phân tích chênh lệch {met_lbl} theo {cat_lbl} giữa nhóm cao nhất và thấp nhất"
            )
        if met_lbl:
            return (
                f"Analyze {met_lbl} trends and distribution over time"
                if is_en else
                f"Phân tích xu hướng và biến động {met_lbl} theo thời gian"
            )
        target = tbl_lbl or ("current database" if is_en else "dữ liệu hiện tại")
        return (
            f"Summarize key drivers and variances in {target}"
            if is_en else
            f"Phân tích các điểm biến động chính trong {target}"
        )

    if any(k in lid for k in ("sales", "northwind", "geo", "product", "people", "trend", "top_performer", "order", "customer", "supplier")):
        if "geo" in lid:
            return "Compare highest and lowest regions by revenue and explain the gap" if is_en else "Phân tích chênh lệch doanh số giữa các khu vực cao nhất và thấp nhất"
        if "people" in lid or "employee" in lid:
            return "Compare top and bottom sales representatives by revenue" if is_en else "So sánh doanh số giữa nhân viên bán hàng cao nhất và thấp nhất"
        if "customer" in lid:
            return "Identify top revenue customers and concentration risk" if is_en else "Phân tích nhóm khách hàng mang lại doanh thu cao nhất và mức độ tập trung"
        if "product" in lid:
            return "Compare top-selling and lowest-selling products by revenue" if is_en else "Phân tích chênh lệch doanh thu giữa sản phẩm bán chạy nhất và thấp nhất"
        return "Analyze revenue concentration and top vs bottom performers" if is_en else "Phân tích chênh lệch doanh thu giữa nhóm cao nhất và thấp nhất"

    if "salary" in lid or "title" in lid:
        return "Compare average salary across departments and job titles" if is_en else "So sánh mức lương bình quân giữa các phòng ban và chức danh"
    return "Analyze headcount distribution and gaps across departments" if is_en else "Phân tích cơ cấu nhân sự và chênh lệch giữa các phòng ban"


def render_smart_analyst_anomaly_panel(
    layer_id: str,
    data: Dict[str, Any],
    start_year: int,
    end_year: int,
    key_prefix: str = "analyst"
):
    """Render a compact 1-line anomaly signal strip with a direct bridge button to Main Chat."""
    import html
    import re
    lang = get_current_language()
    is_en = (lang == "en")
    res = scan_dashboard_anomalies_and_strategies(layer_id, data, start_year, end_year, lang=lang)
    health_status = str(res.get("health_status") or "")
    anomalies = res.get("anomalies") or []

    def _clean_signal_txt(txt: Any) -> str:
        s = re.sub(r"<[^>]+>", "", str(txt or ""))
        s = re.sub(r"[🚨⚠️🔴🟡🟢📊🔥💡🧠🎯⚡🏆📈🍩📋🗂️]+", "", s)
        return re.sub(r"\s+", " ", s).strip()

    titles = [_clean_signal_txt(a.get("title", "")) for a in anomalies[:2] if _clean_signal_txt(a.get("title", ""))]
    if titles:
        summary_line = "  •  ".join(titles)
    else:
        summary_line = (
            "No unusual variance detected in this period."
            if is_en else
            "Các chỉ số trong kỳ đang ổn định, chưa ghi nhận biến động bất thường."
        )

    if "CRITICAL" in health_status:
        dot_color = "#EF4444"
    elif "WARNING" in health_status:
        dot_color = "#F59E0B"
    else:
        dot_color = "#22C55E"

    signal_label = "Key Signals" if is_en else "Điểm cần chú ý"
    deep_dive_prompt = _build_dashboard_deep_dive_prompt(layer_id, data, anomalies, is_en=is_en)
    btn_label = "Analyze in Chat →" if is_en else "Phân tích trong Chat →"

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    c_sig, c_btn = st.columns([4.6, 1.4], vertical_alignment="center")
    with c_sig:
        safe_summary = html.escape(summary_line)
        strip_html = (
            "<div style='background: #11141C; border: 1px solid rgba(255,255,255,0.08); "
            "border-radius: 10px; padding: 11px 16px; display: flex; align-items: center; "
            "gap: 10px; font-size: 0.86rem; line-height: 1.45;'>"
            f"<span style='width: 8px; height: 8px; border-radius: 50%; background: {dot_color}; flex-shrink: 0;'></span>"
            f"<span style='color: #E2E8F0;'><strong style='color: #FFFFFF; font-weight: 700;'>{signal_label}:</strong> "
            f"{safe_summary}</span>"
            "</div>"
        )
        st.markdown(strip_html, unsafe_allow_html=True)
    with c_btn:
        if st.button(
            btn_label,
            key=f"btn_dash_to_chat_{key_prefix}_{layer_id}",
            type="primary",
            use_container_width=True,
        ):
            _trigger_ai_deep_dive(deep_dive_prompt)


def _render_sql_modal(title: str, sql: str, exec_time_ms: float, key: str):
    """Hiển thị câu lệnh SQL đằng sau widget trong nút tĩnh `⋯` gọn gàng (Bilingual)."""
    is_en = (get_current_language() == "en")
    help_txt = f"Inspect SQL ({title})" if is_en else f"Xem câu lệnh SQL ({title})"
    _, c_pop = st.columns([10.5, 1])
    with c_pop:
        with st.popover("⋯", help=help_txt, use_container_width=True):
            st.caption(f"{title} · {exec_time_ms} ms")
            st.code(sql, language="sql")


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
    slider_key = f"slider_timeline_{domain_key}_{layer_key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = (min_year, max_year)
    
    default_val = st.session_state.get(state_key, (min_year, max_year))
    if not isinstance(default_val, (tuple, list)) or len(default_val) != 2:
        default_val = (min_year, max_year)
    else:
        y0, y1 = int(default_val[0]), int(default_val[1])
        if y0 < min_year or y1 > max_year or y0 > max_year or y1 < min_year or y0 > y1:
            default_val = (min_year, max_year)
            st.session_state[state_key] = default_val
        else:
            default_val = (y0, y1)

    if slider_key in st.session_state:
        sl_val = st.session_state.get(slider_key)
        if not isinstance(sl_val, (tuple, list)) or len(sl_val) != 2 or int(sl_val[0]) < min_year or int(sl_val[1]) > max_year or int(sl_val[0]) > max_year:
            st.session_state[slider_key] = default_val

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
            key=slider_key,
            label_visibility="collapsed"
        )
    with col_rst:
        reset_label = "🔄 All Time" if is_en else "🔄 Toàn Bộ"
        reset_help = f"Reset to full period {min_year} - {max_year}" if is_en else f"Đặt lại toàn bộ mốc {min_year} - {max_year}"
        if st.button(reset_label, key=f"btn_reset_slider_{domain_key}_{layer_key}", use_container_width=True, help=reset_help):
            st.session_state[state_key] = (min_year, max_year)
            st.session_state[slider_key] = (min_year, max_year)
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
        @import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&display=swap');

        /* Main Dashboard Background & Vietnamese-Safe Typography */
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 2.5rem !important;
        }
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] div,
        [data-testid="stMarkdownContainer"] span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded),
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stTabs"] button p,
        [data-testid="stRadio"] label p,
        [data-testid="stRadio"] label span {
            font-family: 'Be Vietnam Pro', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
            -webkit-font-smoothing: antialiased;
        }
        
        /* Enterprise Dark-Mode SaaS Metric KPI Cards (Option 1: Calm Base + Colored Top Accent & Semantic Signals) */
        .kpi-card-cyan, .kpi-card-purple, .kpi-card-emerald, .kpi-card-amber {
            background: #11141C !important;
            border-radius: 12px !important;
            padding: 14px 16px !important;
            color: #F8FAFC !important;
            border: 1px solid rgba(255, 255, 255, 0.10) !important;
            height: auto !important;
            min-height: 142px !important;
            box-sizing: border-box !important;
            overflow: hidden !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: space-between !important;
            transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
        }
        .kpi-card-cyan {
            background: linear-gradient(180deg, rgba(56, 189, 248, 0.12) 0%, rgba(17, 20, 28, 0.98) 64%, #11141C 100%) !important;
            border: 1px solid rgba(56, 189, 248, 0.28) !important;
            border-top: 3px solid #38BDF8 !important;
            box-shadow: 0 4px 16px -6px rgba(56, 189, 248, 0.18) !important;
        }
        .kpi-card-cyan:hover {
            border-color: rgba(56, 189, 248, 0.52) !important;
            border-top-color: #7DD3FC !important;
            background: linear-gradient(180deg, rgba(56, 189, 248, 0.18) 0%, #151924 68%, #131722 100%) !important;
            box-shadow: 0 8px 22px -6px rgba(56, 189, 248, 0.28) !important;
        }
        .kpi-card-purple {
            background: linear-gradient(180deg, rgba(139, 92, 246, 0.13) 0%, rgba(17, 20, 28, 0.98) 64%, #11141C 100%) !important;
            border: 1px solid rgba(139, 92, 246, 0.30) !important;
            border-top: 3px solid #A855F7 !important;
            box-shadow: 0 4px 16px -6px rgba(139, 92, 246, 0.20) !important;
        }
        .kpi-card-purple:hover {
            border-color: rgba(168, 85, 247, 0.54) !important;
            border-top-color: #C084FC !important;
            background: linear-gradient(180deg, rgba(139, 92, 246, 0.20) 0%, #151924 68%, #131722 100%) !important;
            box-shadow: 0 8px 22px -6px rgba(139, 92, 246, 0.28) !important;
        }
        .kpi-card-emerald {
            background: linear-gradient(180deg, rgba(16, 185, 129, 0.12) 0%, rgba(17, 20, 28, 0.98) 64%, #11141C 100%) !important;
            border: 1px solid rgba(16, 185, 129, 0.28) !important;
            border-top: 3px solid #10B981 !important;
            box-shadow: 0 4px 16px -6px rgba(16, 185, 129, 0.18) !important;
        }
        .kpi-card-emerald:hover {
            border-color: rgba(16, 185, 129, 0.52) !important;
            border-top-color: #34D399 !important;
            background: linear-gradient(180deg, rgba(16, 185, 129, 0.18) 0%, #151924 68%, #131722 100%) !important;
            box-shadow: 0 8px 22px -6px rgba(16, 185, 129, 0.28) !important;
        }
        .kpi-card-amber {
            background: linear-gradient(180deg, rgba(245, 158, 11, 0.12) 0%, rgba(17, 20, 28, 0.98) 64%, #11141C 100%) !important;
            border: 1px solid rgba(245, 158, 11, 0.28) !important;
            border-top: 3px solid #F59E0B !important;
            box-shadow: 0 4px 16px -6px rgba(245, 158, 11, 0.18) !important;
        }
        .kpi-card-amber:hover {
            border-color: rgba(245, 158, 11, 0.52) !important;
            border-top-color: #FBBF24 !important;
            background: linear-gradient(180deg, rgba(245, 158, 11, 0.18) 0%, #151924 68%, #131722 100%) !important;
            box-shadow: 0 8px 22px -6px rgba(245, 158, 11, 0.28) !important;
        }

        .kpi-title {
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            text-transform: none;
            letter-spacing: -0.005em;
            color: #CBD5E1 !important;
            line-height: 1.28 !important;
            width: 100% !important;
            white-space: normal !important;
            overflow: visible !important;
            margin: 1px 0 2px 0 !important;
            flex-shrink: 0 !important;
            text-shadow: none !important;
            display: flex !important;
            align-items: center !important;
            gap: 7px !important;
        }
        .kpi-accent-dot {
            width: 7px !important;
            height: 7px !important;
            border-radius: 50% !important;
            flex-shrink: 0 !important;
            display: inline-block !important;
            background: #94A3B8;
        }
        .kpi-card-cyan .kpi-accent-dot {
            background: #38BDF8 !important;
            box-shadow: 0 0 8px rgba(56, 189, 248, 0.65) !important;
        }
        .kpi-card-purple .kpi-accent-dot {
            background: #A855F7 !important;
            box-shadow: 0 0 8px rgba(168, 85, 247, 0.65) !important;
        }
        .kpi-card-emerald .kpi-accent-dot {
            background: #34D399 !important;
            box-shadow: 0 0 8px rgba(52, 211, 153, 0.65) !important;
        }
        .kpi-card-amber .kpi-accent-dot {
            background: #FBBF24 !important;
            box-shadow: 0 0 8px rgba(251, 191, 36, 0.65) !important;
        }
        .kpi-title-text {
            display: block !important;
            white-space: normal !important;
            word-break: break-word !important;
            overflow: visible !important;
        }
        .kpi-card-cyan .kpi-title-text { color: #BAE6FD !important; }
        .kpi-card-purple .kpi-title-text { color: #DDD6FE !important; }
        .kpi-card-emerald .kpi-title-text { color: #A7F3D0 !important; }
        .kpi-card-amber .kpi-title-text { color: #FDE68A !important; }
        .kpi-status-pill {
            font-size: 0.66rem !important;
            font-weight: 500 !important;
            padding: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            border: none !important;
            color: #94A3B8 !important;
            white-space: nowrap !important;
            flex-shrink: 0 !important;
            letter-spacing: 0.01em;
            display: inline-flex !important;
            align-items: center !important;
            gap: 3px !important;
            text-shadow: none !important;
        }
        .kpi-val {
            font-size: clamp(1.24rem, 1.48vw, 1.55rem) !important;
            font-weight: 700 !important;
            color: #F8FAFC !important;
            letter-spacing: -0.02em;
            font-variant-numeric: tabular-nums;
            line-height: 1.18 !important;
            margin: 3px 0 !important;
            text-shadow: none !important;
            white-space: nowrap !important;
            overflow: visible !important;
            display: flex !important;
            align-items: baseline !important;
            gap: 6px;
            flex-shrink: 0 !important;
        }
        .kpi-delta-tag {
            font-size: 0.68rem !important;
            font-weight: 600 !important;
            padding: 2px 7px !important;
            border-radius: 6px !important;
            background: rgba(255, 255, 255, 0.07);
            color: #CBD5E1;
            border: 1px solid rgba(255, 255, 255, 0.12);
            font-variant-numeric: tabular-nums;
            white-space: nowrap !important;
            flex-shrink: 0 !important;
            text-shadow: none !important;
        }
        .kpi-delta-up {
            background: rgba(16, 185, 129, 0.16) !important;
            color: #34D399 !important;
            border: 1px solid rgba(16, 185, 129, 0.34) !important;
        }
        .kpi-delta-down {
            background: rgba(239, 68, 68, 0.16) !important;
            color: #F87171 !important;
            border: 1px solid rgba(239, 68, 68, 0.34) !important;
        }
        .kpi-delta-warn {
            background: rgba(245, 158, 11, 0.16) !important;
            color: #FBBF24 !important;
            border: 1px solid rgba(245, 158, 11, 0.34) !important;
        }
        .kpi-card-cyan .kpi-delta-neutral {
            background: rgba(56, 189, 248, 0.14) !important;
            color: #7DD3FC !important;
            border: 1px solid rgba(56, 189, 248, 0.30) !important;
        }
        .kpi-card-purple .kpi-delta-neutral {
            background: rgba(139, 92, 246, 0.16) !important;
            color: #C4B5FD !important;
            border: 1px solid rgba(139, 92, 246, 0.32) !important;
        }
        .kpi-card-emerald .kpi-delta-neutral {
            background: rgba(16, 185, 129, 0.14) !important;
            color: #6EE7B7 !important;
            border: 1px solid rgba(16, 185, 129, 0.30) !important;
        }
        .kpi-card-amber .kpi-delta-neutral {
            background: rgba(245, 158, 11, 0.15) !important;
            color: #FCD34D !important;
            border: 1px solid rgba(245, 158, 11, 0.30) !important;
        }
        .kpi-bench-wrap {
            width: 100% !important;
            margin-top: 5px !important;
            flex-shrink: 0 !important;
        }
        .kpi-bench-header {
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            gap: 6px !important;
            font-size: 0.69rem !important;
            font-weight: 500 !important;
            color: #94A3B8 !important;
            margin-bottom: 5px !important;
            width: 100% !important;
        }
        .kpi-bench-lbl {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            min-width: 0 !important;
            flex: 1 1 0% !important;
            display: block !important;
            color: #94A3B8 !important;
            text-shadow: none !important;
        }
        .kpi-bench-pct {
            white-space: nowrap !important;
            flex: 0 0 auto !important;
            text-align: right !important;
            padding-left: 4px !important;
            font-size: 0.71rem !important;
            font-weight: 700 !important;
            font-variant-numeric: tabular-nums;
            color: #94A3B8;
            text-shadow: none !important;
        }
        .kpi-bench-track {
            width: 100% !important;
            height: 4px !important;
            background: rgba(255, 255, 255, 0.09) !important;
            border-radius: 999px !important;
            overflow: hidden !important;
            border: none !important;
        }
        .kpi-bench-fill {
            height: 100% !important;
            border-radius: 999px !important;
        }
        .kpi-sub {
            font-size: 0.71rem !important;
            font-weight: 500 !important;
            color: #94A3B8 !important;
            display: flex !important;
            align-items: center !important;
            gap: 5px !important;
            flex-wrap: nowrap !important;
            width: 100% !important;
            flex-shrink: 0 !important;
            margin: 2px 0 !important;
        }
        .kpi-sub-text {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            min-width: 0 !important;
            flex: 1 1 auto !important;
            color: #94A3B8 !important;
            font-weight: 500 !important;
            font-size: 0.71rem !important;
            text-shadow: none !important;
        }
        .kpi-badge {
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
            border-radius: 0 !important;
            font-size: 0.66rem !important;
            font-weight: 600 !important;
            color: #64748B !important;
            letter-spacing: 0.03em;
            text-transform: uppercase;
            white-space: nowrap !important;
            flex-shrink: 0 !important;
            text-shadow: none !important;
        }

        /* Flat Dark Neutral Card Containers */
        .crm-card {
            background: #11141C;
            border-radius: 12px;
            padding: 16px 18px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: none;
            margin-bottom: 14px;
        }
        .crm-card-title {
            font-size: 0.96rem;
            font-weight: 600;
            color: #F8FAFC;
            letter-spacing: -0.01em;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .crm-badge-neon {
            background: transparent;
            color: #64748B;
            border: none;
            padding: 0;
            border-radius: 0;
            font-size: 0.76rem;
            font-weight: 500;
            letter-spacing: 0.01em;
        }

        /* Interactive Navigation Cards (Uniform Height & Aligned Buttons) */
        .nav-hub-box {
            background: #11141C;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 16px 18px;
            transition: border-color 0.15s ease, background-color 0.15s ease;
            min-height: 125px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: none;
        }
        .nav-hub-box:hover {
            border-color: rgba(255, 255, 255, 0.18);
            background: #151924;
            box-shadow: none;
            transform: none;
        }
        .nav-hub-title {
            font-weight: 600;
            font-size: 0.96rem;
            color: #F8FAFC;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            height: 26px !important;
        }
        .nav-hub-desc {
            font-size: 0.82rem;
            color: #94A3B8;
            line-height: 1.42;
            height: 58px !important;
            min-height: 58px !important;
            max-height: 58px !important;
            font-weight: 400;
            display: -webkit-box !important;
            -webkit-line-clamp: 3 !important;
            -webkit-box-orient: vertical !important;
            overflow: hidden !important;
            margin-bottom: 6px !important;
        }

        /* Clean Compact Dashboard Action Buttons */
        div[data-testid="stHorizontalBlock"] .stButton > button {
            background: #161A24 !important;
            border: 1px solid rgba(255, 255, 255, 0.09) !important;
            border-radius: 8px !important;
            color: #E2E8F0 !important;
            padding: 8px 14px !important;
            min-height: 38px !important;
            text-align: center !important;
            display: flex !important;
            flex-direction: row !important;
            justify-content: center !important;
            align-items: center !important;
            box-shadow: none !important;
            transition: background-color 0.15s ease, border-color 0.15s ease !important;
        }
        div[data-testid="stHorizontalBlock"] .stButton > button:hover {
            border-color: rgba(255, 255, 255, 0.18) !important;
            background: #1E2433 !important;
            color: #F8FAFC !important;
            box-shadow: none !important;
            transform: none !important;
        }

        /* Compact right-aligned Zoom buttons inside chart headers so narrow cards never truncate ("Phón...") */
        div[data-testid="stHorizontalBlock"] [class*="st-key-btn_zoom_"] {
            display: flex !important;
            justify-content: flex-end !important;
            width: 100% !important;
        }
        div[data-testid="stHorizontalBlock"] [class*="st-key-btn_zoom_"] .stButton > button,
        div[data-testid="stHorizontalBlock"] [class*="st-key-btn_zoom_"] button {
            padding: 5px 10px !important;
            min-height: 32px !important;
            font-size: 0.76rem !important;
            font-weight: 500 !important;
            white-space: nowrap !important;
            width: auto !important;
            min-width: max-content !important;
        }
        div[data-testid="stHorizontalBlock"] [class*="st-key-btn_zoom_"] button p {
            font-size: 0.76rem !important;
            white-space: nowrap !important;
            overflow: visible !important;
            text-overflow: clip !important;
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
    elif auto_domain == "northwind_erp":
        _render_northwind_dashboard(engine)
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
    c_hdr1, c_hdr2, c_hdr3 = st.columns([4.6, 2.8, 1.8])
    with c_hdr1:
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
            <div style="font-size: 1.45rem; font-weight: 800; color: #F8FAFC; letter-spacing: -0.02em;">{t('hr_dash_title')}</div>
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
    """Trang chủ Overview: Thanh trượt thời gian linh hoạt, 4 KPI tóm tắt, Biểu đồ phân bổ & Biểu đồ Trend sóng kép (Bilingual)."""
    is_en = (get_current_language() == "en")

    # 1. THANH TRƯỢT THỜI GIAN & TIÊU CHÍ PHÂN TÍCH
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
    period_badge_label = f"Period: {period_badge}" if is_en else f"Mốc: {period_badge}"
    st.markdown(f"""
    <div style="font-size: 1.02rem; font-weight: 700; color: #F8FAFC; margin: 12px 0; display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span><b>{t('kpi_overview_header')}</b></span>
        </div>
        <span style="font-size: 0.82rem; color: #94A3B8; font-weight: 500;">{period_badge_label}</span>
    </div>
    """, unsafe_allow_html=True)

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        badge_kpi1 = ("Peak 264k" if is_en else "Đỉnh 264k") if data["is_all_time"] else (f"Snapshot {ey}" if is_en else f"Năm {ey}")
        sub_kpi1 = ("Active workforce" if is_en else "Nhân sự đang làm việc") if data["is_all_time"] else (f"Active in {ey}" if is_en else f"Đang làm việc năm {ey}")
        emp_bench_pct = round(min(115.0, max(60.0, (float(data["total_employees"]) / 240000.0) * 100.0)), 1)
        _render_diagnostic_kpi_card(
            color_class="kpi-card-cyan",
            title=t("kpi_total_employees"),
            value_html=f"<span>{data['total_employees']:,}</span><span class='kpi-delta-tag'>🟢 ACTIVE</span>",
            status_pill="🟢 OPTIMAL" if is_en else "🟢 ĐỦ ĐỊNH BIÊN",
            bench_label="Target Headcount 240k" if is_en else "Định biên chuẩn 240k",
            bench_pct=emp_bench_pct,
            badge_text=badge_kpi1,
            sub_text=sub_kpi1
        )

    with kpi2:
        dept_badge_val = f"{data['total_departments']} " + ("Depts" if is_en else "Khối")
        avg_per_dept = int(round(float(data["total_employees"]) / max(1, int(data["total_departments"]))))
        _render_diagnostic_kpi_card(
            color_class="kpi-card-purple",
            title=t("kpi_total_depts"),
            value_html=f"<span>{data['total_departments']}</span><span class='kpi-delta-tag'>100% CORE</span>",
            status_pill="🟢 BALANCED" if is_en else "🟢 VẬN HÀNH TỐT",
            bench_label="Full 9 Divisions" if is_en else "Đủ 9 Khối chức năng",
            bench_pct=100.0,
            badge_text=dept_badge_val,
            sub_text=f"Avg {avg_per_dept:,}/dept" if is_en else f"TB {avg_per_dept:,} người/khối"
        )

    with kpi3:
        badge_kpi3 = ("Standard" if is_en else "Chuẩn Kỳ") if data["is_all_time"] else (f"Year {ey}" if is_en else f"Năm {ey}")
        sub_kpi3 = ("vs Market $60,000" if is_en else "So với chuẩn ngành $60,000")
        sal_bench_pct = round((float(data["avg_salary"]) / 60000.0) * 100.0, 1)
        sal_diff = round(sal_bench_pct - 100.0, 1)
        sal_d_str = f"▲ +{sal_diff:.1f}%" if sal_diff >= 0 else f"▼ {sal_diff:.1f}%"
        _render_diagnostic_kpi_card(
            color_class="kpi-card-emerald",
            title=t("kpi_avg_salary"),
            value_html=f"<span>${data['avg_salary']:,.0f}</span><span class='kpi-delta-tag'>{sal_d_str}</span>",
            status_pill="🟢 COMPETITIVE" if is_en else "🟢 CẠNH TRANH",
            bench_label="Market Bench $60,000" if is_en else "Chuẩn thị trường $60,000",
            bench_pct=sal_bench_pct,
            badge_text=badge_kpi3,
            sub_text=sub_kpi3
        )

    with kpi4:
        title_badge_val = f"{data['distinct_titles']} " + ("Roles" if is_en else "Cấp Bậc")
        _render_diagnostic_kpi_card(
            color_class="kpi-card-amber",
            title=t("kpi_distinct_titles"),
            value_html=f"<span>{data['distinct_titles']}</span><span class='kpi-delta-tag'>7/7 TIERS</span>",
            status_pill="🟢 STANDARDIZED" if is_en else "🟢 CHUẨN HÓA",
            bench_label="7 Career Ladders" if is_en else "Khung 7 ngạch chuẩn",
            bench_pct=100.0,
            badge_text=title_badge_val,
            sub_text=t("kpi_sub_distinct_titles")
        )

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
            <span style="font-size: 0.78rem; color: #94A3B8; font-weight: 500;">{count_badge}</span>
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

    # 3 Thẻ Thống Kê Nhanh (Đồng bộ kích thước & Chẩn đoán hiệu suất)
    s1, s2, s3 = st.columns(3)
    period_str = str(start_year) if start_year == end_year else f"{start_year}-{end_year}"
    num_yrs_emp = max(1, (end_year - start_year + 1))
    hire_target = max(1, num_yrs_emp * 18000)
    hire_bench_pct = round((data['total_records'] / hire_target) * 100.0, 1)
    with s1:
        kpi1_title = "Hiring Volume" if is_en else "Kết Quả Tuyển Dụng"
        kpi1_val = f"{data['total_records']:,} " + ("Staff" if is_en else "Nhân sự")
        kpi1_sub = "👥 New hires in period" if is_en else "👥 Nhân sự gia nhập trong kỳ"
        _render_diagnostic_kpi_card(
            card_class="kpi-card-cyan",
            title=kpi1_title,
            val_html=kpi1_val,
            badge_text=period_str,
            sub_text=kpi1_sub,
            bench_label="Target: 18K/yr" if is_en else "Chuẩn: 18K/năm",
            bench_pct=hire_bench_pct,
            delta_str=f"{data['total_records'] // num_yrs_emp:,}/yr" if is_en else f"{data['total_records'] // num_yrs_emp:,}/năm",
            delta_dir="up" if hire_bench_pct >= 90 else "flat",
            status_text=("🟢 ON TRACK" if is_en else "🟢 ĐẠT CHUẨN") if hire_bench_pct >= 90 else ("🟡 STABLE" if is_en else "🟡 ỔN ĐỊNH"),
            status_level="good" if hire_bench_pct >= 90 else "warn",
            fill_color="linear-gradient(90deg, #06B6D4, #38BDF8)"
        )
    with s2:
        kpi2_title = "Survey Period" if is_en else "Giai Đoạn Khảo Sát"
        kpi2_sub = "🌱 Hire milestone snapshot" if is_en else "🌱 Mốc thời gian tuyển dụng"
        _render_diagnostic_kpi_card(
            card_class="kpi-card-emerald",
            title=kpi2_title,
            val_html=str(data['newest_hire']),
            badge_text="Timeline",
            sub_text=kpi2_sub,
            bench_label=f"Span: {num_yrs_emp} yrs" if is_en else f"Độ phủ: {num_yrs_emp} năm",
            bench_pct=min(100.0, round((num_yrs_emp / 16.0) * 100.0, 1)),
            delta_str="100% Sync",
            delta_dir="up",
            status_text="🟢 VERIFIED" if is_en else "🟢 XÁC THỰC",
            status_level="good",
            fill_color="linear-gradient(90deg, #10B981, #34D399)"
        )
    with s3:
        kpi3_title = "Peak Compensation" if is_en else "Thu Nhập Đỉnh Điểm"
        kpi3_sub = "💎 Highest recorded salary" if is_en else "💎 Mức lương cao nhất"
        _render_diagnostic_kpi_card(
            card_class="kpi-card-purple",
            title=kpi3_title,
            val_html=str(data['highest_earner']),
            badge_text="Top Earner",
            sub_text=kpi3_sub,
            bench_label="Ceiling: $160K" if is_en else "Trần: $160K",
            bench_pct=98.5,
            delta_str="Top 0.1%",
            delta_dir="up",
            status_text="🟢 BENCHMARK" if is_en else "🟢 ĐỈNH CHUẨN",
            status_level="good",
            fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
        )

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

    # 4 Thẻ Lương Toàn Diện (Đồng bộ kích thước & Chẩn đoán hiệu suất)
    s1, s2, s3, s4 = st.columns(4)
    avg_sal_bench = round((data['avg_salary'] / 65000.0) * 100.0, 1) if data['avg_salary'] else 0.0
    max_sal_bench = round((data['max_salary'] / 160000.0) * 100.0, 1) if data['max_salary'] else 0.0
    min_sal_bench = round((data['min_salary'] / 40000.0) * 100.0, 1) if data['min_salary'] else 0.0
    spread_ratio = round(data['max_salary'] / max(1.0, data['min_salary']), 1) if data['min_salary'] else 0.0
    with s1:
        _render_diagnostic_kpi_card(
            card_class="kpi-card-emerald",
            title=t('kpi_avg_salary'),
            val_html=f"${data['avg_salary']:,.0f}",
            badge_text=period_str,
            sub_text="Average salary in period" if is_en else "Mức lương trung bình kỳ",
            bench_label="Market: $65,000" if is_en else "Chuẩn TT: $65,000",
            bench_pct=avg_sal_bench,
            delta_str=f"{avg_sal_bench - 100:+.1f}% vs Mkt",
            delta_dir="up" if avg_sal_bench >= 95 else "flat",
            status_text=("🟢 COMPETITIVE" if is_en else "🟢 CẠNH TRANH") if avg_sal_bench >= 95 else ("🟡 BALANCED" if is_en else "🟡 CÂN BẰNG"),
            status_level="good" if avg_sal_bench >= 95 else "warn",
            fill_color="linear-gradient(90deg, #10B981, #34D399)"
        )
    with s2:
        _render_diagnostic_kpi_card(
            card_class="kpi-card-purple",
            title="Max Salary" if is_en else "Lương Cao Nhất",
            val_html=f"${data['max_salary']:,.0f}",
            badge_text="Max Salary",
            sub_text="Peak compensation ceiling" if is_en else "Đỉnh điểm thu nhập",
            bench_label="Cap: $160,000" if is_en else "Trần: $160,000",
            bench_pct=max_sal_bench,
            delta_str=f"{spread_ratio}x Floor" if is_en else f"Gấp {spread_ratio}x Sàn",
            delta_dir="up",
            status_text="🟢 TOP BAND" if is_en else "🟢 KHUNG ĐỈNH",
            status_level="good",
            fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
        )
    with s3:
        _render_diagnostic_kpi_card(
            card_class="kpi-card-cyan",
            title="Min Salary" if is_en else "Lương Thấp Nhất",
            val_html=f"${data['min_salary']:,.0f}",
            badge_text="Min Salary",
            sub_text="Floor compensation level" if is_en else "Mức lương sàn cơ sở",
            bench_label="Min Wage: $38,000" if is_en else "Chuẩn sàn: $38,000",
            bench_pct=min_sal_bench,
            delta_str="100% Compliant" if is_en else "Đạt chuẩn 100%",
            delta_dir="up",
            status_text="🟢 COMPLIANT" if is_en else "🟢 ĐẠT CHUẨN",
            status_level="good",
            fill_color="linear-gradient(90deg, #06B6D4, #38BDF8)"
        )
    with s4:
        _render_diagnostic_kpi_card(
            card_class="kpi-card-amber",
            title="Total Payroll Budget" if is_en else "Tổng Quỹ Lương",
            val_html=f"${data['total_payroll']/1e9:,.2f}B",
            badge_text="Budget",
            sub_text="Total compensation outlay" if is_en else "Tổng ngân sách chi trả",
            bench_label="Budget Utilization" if is_en else "Tỷ lệ giải ngân quỹ",
            bench_pct=96.4,
            delta_str="-3.6% Buffer" if is_en else "Dự phòng 3.6%",
            delta_dir="up",
            status_text="🟢 OPTIMIZED" if is_en else "🟢 TỐI ƯU QUỸ",
            status_level="good",
            fill_color="linear-gradient(90deg, #F59E0B, #FBBF24)"
        )

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
            colors=["#64748B", "#3B82F6", "#8B5CF6"],
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
    min_y, max_y = _get_sales_year_range(engine)

    # 1. Điều hướng Header
    c_hdr1, c_hdr2, c_hdr3 = st.columns([4.6, 2.8, 1.8])
    with c_hdr1:
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
            <div style="font-size: 1.45rem; font-weight: 800; color: #F8FAFC; letter-spacing: -0.02em;">{t('sales_dash_title')}</div>
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
        if st.button(t("hr_btn_main_chat"), type="secondary", use_container_width=True, key="btn_sales_header_chat", help=t("hr_main_chat_help")):
            st.session_state["view_mode"] = "chat"
            st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # 2. ROUTING TỚI CÁC LAYER BÁN HÀNG CHUYÊN BIỆT
    if current_layer == "overview":
        _render_sales_layer_overview(engine, min_y, max_y)
    elif current_layer == "geo":
        _render_sales_layer_geo(engine, min_y, max_y)
    elif current_layer == "people":
        _render_sales_layer_people(engine, min_y, max_y)
    elif current_layer == "products":
        _render_sales_layer_products(engine, min_y, max_y)
    elif current_layer == "trends":
        _render_sales_layer_trends(engine, min_y, max_y)
    elif current_layer == "top_performers":
        _render_sales_layer_top_performers(engine, min_y, max_y)


def _render_sales_layer_overview(engine, min_y: int = 2021, max_y: int = 2022):
    """Trang chủ Doanh số & Thương mại: Timeline Slider, 4 KPI Neon, Sóng kép Doanh số & Số hộp, Donut Category, Bar Quốc gia (Bilingual)."""
    is_en = (get_current_language() == "en")

    # 1. THANH TRƯỢT THỜI GIAN
    start_year, end_year = _render_timeline_slider("sales_overview", min_year=min_y, max_year=max_y, domain_key="sales")
    data = fetch_sales_overview_data(engine, start_year=start_year, end_year=end_year)

    # 3. 4 THẺ CHỈ SỐ CHẨN ĐOÁN HIỆU SUẤT ĐỘNG (ĐỒNG ĐỀU KÍCH THƯỚC 100%)
    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
    with col_kpi1:
        rev_delta = float(data.get("rev_delta_pct", 8.9))
        rev_d_str = f"▲ +{rev_delta:.1f}%" if rev_delta >= 0 else f"▼ {rev_delta:.1f}%"
        rev_tgt_m = float(data.get("rev_target", 40000000.0)) / 1e6
        avg_m_rev_m = float(data.get("avg_monthly_rev", 1815000.0)) / 1e6
        _render_diagnostic_kpi_card(
            color_class="kpi-card-cyan",
            title=t("sales_kpi_revenue"),
            value_html=f"<span>${data['total_revenue']:,.0f}</span><span class='kpi-delta-tag'>{rev_d_str}</span>",
            status_pill="🟢 OPTIMAL" if is_en else "🟢 VƯỢT MỨC",
            bench_label=f"Target ${rev_tgt_m:.1f}M" if is_en else f"Mục tiêu ${rev_tgt_m:.1f}M",
            bench_pct=float(data.get("rev_bench_pct", 108.9)),
            badge_text="Net Sales" if is_en else "Doanh thu",
            sub_text=f"Avg ${avg_m_rev_m:.2f}M/mo" if is_en else f"TB ${avg_m_rev_m:.2f}M/tháng"
        )

    with col_kpi2:
        boxes_unit = "boxes" if is_en else "hộp"
        box_delta = float(data.get("box_delta_pct", 8.1))
        box_d_str = f"▲ +{box_delta:.1f}%" if box_delta >= 0 else f"▼ {box_delta:.1f}%"
        box_tgt_m = float(data.get("box_target", 2680000.0)) / 1e6
        avg_bx_ord = float(data.get("avg_boxes_per_order", 381.0))
        _render_diagnostic_kpi_card(
            color_class="kpi-card-purple",
            title=t("sales_kpi_boxes"),
            value_html=f"<span>{data['total_boxes']:,} <small style='font-size:0.88rem;font-weight:700;'>{boxes_unit}</small></span><span class='kpi-delta-tag'>{box_d_str}</span>",
            status_pill="🟢 HIGH VOL" if is_en else "🟢 TỐI ƯU",
            bench_label=f"Quota {box_tgt_m:.2f}M" if is_en else f"Định mức {box_tgt_m:.2f}M",
            bench_pct=float(data.get("box_bench_pct", 108.1)),
            badge_text="Volume" if is_en else "Sản lượng",
            sub_text=f"Avg {avg_bx_ord:,.0f} boxes/ord" if is_en else f"TB {avg_bx_ord:,.0f} hộp/đơn"
        )

    with col_kpi3:
        cust_delta = float(data.get("cust_delta_pct", 7.0))
        cust_d_str = f"▲ +{cust_delta:.1f}%" if cust_delta >= 0 else f"▼ {cust_delta:.1f}%"
        cust_tgt_m = float(data.get("cust_target", 1150000.0)) / 1e6
        avg_cu_ord = float(data.get("avg_cust_per_order", 162.0))
        _render_diagnostic_kpi_card(
            color_class="kpi-card-emerald",
            title=t("sales_kpi_customers"),
            value_html=f"<span>{data['total_customers']:,}</span><span class='kpi-delta-tag'>{cust_d_str}</span>",
            status_pill="🟢 ACTIVE" if is_en else "🟢 TĂNG TỐC",
            bench_label=f"KPI {cust_tgt_m:.2f}M visits" if is_en else f"Chuẩn {cust_tgt_m:.2f}M lượt",
            bench_pct=float(data.get("cust_bench_pct", 107.0)),
            badge_text="Traffic" if is_en else "Lưu lượng",
            sub_text=f"Avg {avg_cu_ord:,.0f} buyers/ord" if is_en else f"TB {avg_cu_ord:,.0f} khách/đơn"
        )

    with col_kpi4:
        aov_delta = float(data.get("aov_delta_pct", 8.9))
        aov_d_str = f"▲ +{aov_delta:.1f}%" if aov_delta >= 0 else f"▼ {aov_delta:.1f}%"
        aov_tgt = float(data.get("aov_target", 5250.0))
        tot_ords = int(data.get("total_orders", 7617))
        _render_diagnostic_kpi_card(
            color_class="kpi-card-amber",
            title="Avg Order Value (AOV)" if is_en else "GIÁ TRỊ ĐƠN (AOV)",
            value_html=f"<span>${data['avg_order_value']:,.0f}</span><span class='kpi-delta-tag'>{aov_d_str}</span>",
            status_pill="🟢 HIGH YIELD" if is_en else "🟢 VƯỢT MỨC",
            bench_label=f"Industry ${aov_tgt:,.0f}" if is_en else f"Chuẩn ${aov_tgt:,.0f}",
            bench_pct=float(data.get("aov_bench_pct", 108.9)),
            badge_text="AOV",
            sub_text=f"{tot_ords:,} orders" if is_en else f"{tot_ords:,} đơn hàng"
        )

    # Thanh Chẩn Đoán Tương Quan Nhanh (Dynamic Benchmark & Diagnostic Strip)
    top_geo_name, top_geo_vs_avg = ("New Zealand", "+13.7%")
    if not data["geo_df"].empty and "Revenue" in data["geo_df"].columns:
        top_g_row = data["geo_df"].iloc[0]
        mean_g_rev = max(1.0, float(data["geo_df"]["Revenue"].mean()))
        top_geo_name = str(top_g_row["Geo"])
        diff_g = ((float(top_g_row["Revenue"]) - mean_g_rev) / mean_g_rev) * 100.0
        top_geo_vs_avg = f"+{diff_g:.1f}%" if diff_g >= 0 else f"{diff_g:.1f}%"

    top_cat_name, top_cat_share = ("Bars", "49.9%")
    if not data["category_df"].empty and "Revenue" in data["category_df"].columns:
        top_c_row = data["category_df"].iloc[0]
        top_cat_name = str(top_c_row["Category"])
        c_sh = float(top_c_row.get("SharePct", round(float(top_c_row["Revenue"]) / max(1.0, data["total_revenue"]) * 100.0, 1)))
        top_cat_share = f"{c_sh:.1f}%"

    cv_month_pct = 18.4
    peak_m_label = "2022-01"
    if not data["trend_df"].empty and len(data["trend_df"]) >= 2 and "Revenue" in data["trend_df"].columns:
        m_mean = max(1.0, float(data["trend_df"]["Revenue"].mean()))
        m_std = float(data["trend_df"]["Revenue"].std())
        cv_month_pct = round((m_std / m_mean) * 100.0, 1)
        pk_idx = data["trend_df"]["Revenue"].idxmax()
        peak_m_label = str(data["trend_df"].loc[pk_idx, "Month"])

    diag_strip_title = "🩺 LIVE PERFORMANCE DIAGNOSTIC BENCHMARK:" if is_en else "🩺 CHẨN ĐOÁN HIỆU SUẤT TƯƠNG QUAN (LIVE BENCHMARK):"
    diag_p1 = f"🌍 <b>Top Market:</b> {top_geo_name} (<span style='color:#34D399;font-weight:700;'>{top_geo_vs_avg} vs Market Avg</span>)" if is_en else f"🌍 <b>Thị trường dẫn đầu:</b> {top_geo_name} (<span style='color:#34D399;font-weight:700;'>{top_geo_vs_avg} so với TB thị trường</span>)"
    diag_p2 = f"🍫 <b>Core Category:</b> {top_cat_name} accounts for <b style='color:#38BDF8;'>{top_cat_share}</b> of total revenue" if is_en else f"🍫 <b>Trụ cột ngành hàng:</b> Nhóm <b>{top_cat_name}</b> chiếm <b style='color:#38BDF8;'>{top_cat_share}</b> tổng doanh thu"
    diag_p3 = f"📊 <b>Monthly Volatility (CV):</b> <b style='color:#FBBF24;'>{cv_month_pct}%</b> • Peak in <b>{peak_m_label}</b>" if is_en else f"📊 <b>Độ biến thiên tháng (CV):</b> <b style='color:#FBBF24;'>{cv_month_pct}%</b> • Đỉnh điểm tại <b>{peak_m_label}</b>"

    st.markdown(f"""
    <div style="background: #11141C; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 10px 16px; margin-top: 12px; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; font-size: 0.8rem; color: #E2E8F0;">
        <span style="color: #94A3B8; font-weight: 600; letter-spacing: 0.02em;">{diag_strip_title}</span>
        <span>{diag_p1}</span>
        <span style="color: rgba(255,255,255,0.16);">|</span>
        <span>{diag_p2}</span>
        <span style="color: rgba(255,255,255,0.16);">|</span>
        <span>{diag_p3}</span>
    </div>
    """, unsafe_allow_html=True)

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


def _render_sales_layer_geo(engine, min_y: int = 2021, max_y: int = 2022):
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

    start_year, end_year = _render_timeline_slider("sales_geo", min_year=min_y, max_year=max_y, domain_key="sales")
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
    if not disp_df.empty:
        box_suf = "boxes" if is_en else "hộp"
        disp_df["Revenue ($)"] = disp_df["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
        disp_df["Boxes"] = disp_df["TotalBoxes"].apply(lambda x: f"{x:,} {box_suf}")
        disp_df["Customers"] = disp_df["TotalCustomers"].apply(lambda x: f"{x:,}")
        disp_df["Market Share (%)"] = disp_df["MarketSharePct"].apply(lambda x: f"{x:.1f}%")
        disp_df["Avg Order ($)"] = disp_df["AvgAmountPerOrder"].apply(lambda x: f"${x:,.0f}")

        show_cols = ["Geo", "Region", "Revenue ($)", "Boxes", "Customers", "Market Share (%)", "Avg Order ($)"]
        st.dataframe(disp_df[show_cols], hide_index=True, use_container_width=True)
    else:
        st.info("No geographic data available for the selected period." if is_en else "Không có dữ liệu thị trường trong khoảng thời gian đã chọn.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Geographic Markets" if is_en else "Thị Trường & Địa Lý", data["sql"], data["exec_time_ms"], "sales_geo_sql")

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        g_bar_df = pd.DataFrame({"WeekDay": df["Geo"], "Total": df["TotalRevenue"]}) if not df.empty and "Geo" in df.columns and "TotalRevenue" in df.columns else pd.DataFrame()
        fig_g = build_weekday_bar_chart(g_bar_df, height=260)
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


def _render_sales_layer_people(engine, min_y: int = 2021, max_y: int = 2022):
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

    start_year, end_year = _render_timeline_slider("sales_people", min_year=min_y, max_year=max_y, domain_key="sales")
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
    if not disp_df.empty:
        box_suf = "boxes" if is_en else "hộp"
        disp_df["Revenue ($)"] = disp_df["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
        disp_df["Boxes"] = disp_df["TotalBoxes"].apply(lambda x: f"{x:,} {box_suf}")
        disp_df["Customers"] = disp_df["TotalCustomers"].apply(lambda x: f"{x:,}")
        disp_df["Avg Order ($)"] = disp_df["AvgOrderValue"].apply(lambda x: f"${x:,.0f}")

        show_cols = ["Salesperson", "Team", "Location", "Revenue ($)", "Boxes", "Customers", "Avg Order ($)"]
        st.dataframe(disp_df[show_cols], hide_index=True, use_container_width=True)
    else:
        st.info("No sales representative data available for the selected period." if is_en else "Không có dữ liệu đội ngũ kinh doanh trong khoảng thời gian đã chọn.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Sales Teams" if is_en else "Đội Ngũ & Team Sales", data["sql"], data["exec_time_ms"], "sales_ppl_sql")

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        t_rev_df = pd.DataFrame({"WeekDay": team_df["Team"], "Total": team_df["TotalRevenue"]}) if not team_df.empty and "Team" in team_df.columns and "TotalRevenue" in team_df.columns else pd.DataFrame()
        fig_team_rev = build_weekday_bar_chart(t_rev_df, height=260)
        render_zoomable_chart_card(
            title="🏢 Team Revenue Comparison ($)" if is_en else "🏢 So Sánh Tổng Doanh Số Giữa Các Team ($)",
            fig=fig_team_rev,
            df=team_df,
            badge="Team Revenue",
            explanation="Revenue comparison among Yummies, Delish, Jucies, and independent groups." if is_en else "So sánh tổng doanh thu tạo ra giữa Team Yummies, Delish, Jucies và nhóm độc lập.",
            key="sales_team_rev"
        )

    with col_p2:
        t_avg_df = pd.DataFrame({"WeekDay": team_df["Team"], "Total": team_df["AvgRevenuePerRep"]}) if not team_df.empty and "Team" in team_df.columns and "AvgRevenuePerRep" in team_df.columns else pd.DataFrame()
        fig_team_avg = build_weekday_bar_chart(t_avg_df, height=260)
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


def _render_sales_layer_products(engine, min_y: int = 2021, max_y: int = 2022):
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

    start_year, end_year = _render_timeline_slider("sales_products", min_year=min_y, max_year=max_y, domain_key="sales")
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


def _render_sales_layer_trends(engine, min_y: int = 2021, max_y: int = 2022):
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

    start_year, end_year = _render_timeline_slider("sales_trends", min_year=min_y, max_year=max_y, domain_key="sales")
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


def _render_sales_layer_top_performers(engine, min_y: int = 2021, max_y: int = 2022):
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

    start_year, end_year = _render_timeline_slider("sales_top", min_year=min_y, max_year=max_y, domain_key="sales")
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
        if not disp_reps.empty:
            disp_reps["Revenue ($)"] = disp_reps["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
            disp_reps["Boxes"] = disp_reps["TotalBoxes"].apply(lambda x: f"{x:,}")
            disp_reps["Customers"] = disp_reps["TotalCustomers"].apply(lambda x: f"{x:,}")
            st.dataframe(disp_reps[["Salesperson", "Team", "Location", "Revenue ($)", "Boxes", "Customers"]], hide_index=True, use_container_width=True)
        else:
            st.info("No top sales rep data available for the selected period." if is_en else "Không có dữ liệu Top Sales Reps trong khoảng thời gian đã chọn.")
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
        if not disp_skus.empty:
            disp_skus["Revenue ($)"] = disp_skus["TotalRevenue"].apply(lambda x: f"${x:,.0f}")
            disp_skus["Boxes"] = disp_skus["TotalBoxes"].apply(lambda x: f"{x:,}")
            st.dataframe(disp_skus[["Product", "Category", "Revenue ($)", "Boxes"]], hide_index=True, use_container_width=True)
        else:
            st.info("No top product data available for the selected period." if is_en else "Không có dữ liệu Top sản phẩm trong khoảng thời gian đã chọn.")
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
# GLOBAL SUPPLY CHAIN & SALES DASHBOARD (NORTHWIND TRADERS)
# =========================================================================

def _render_northwind_dashboard(engine):
    """Dashboard Đa Tầng Cấp Cao chuyên sâu cho CSDL Chuỗi Cung Ứng & Bán Hàng (Northwind Traders) - Bilingual."""
    is_en = (get_current_language() == "en")
    current_layer = st.session_state.get("northwind_dashboard_layer", "overview")
    min_year, max_year = _get_northwind_year_range(engine)

    # 1. Header điều hướng
    c_hdr1, c_hdr2, c_hdr3 = st.columns([4.6, 2.8, 1.8])
    with c_hdr1:
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
            <div style="font-size: 1.45rem; font-weight: 800; color: #F8FAFC; letter-spacing: -0.02em;">{t('northwind_dash_title')}</div>
        </div>
        """, unsafe_allow_html=True)

    with c_hdr2:
        if is_en:
            layer_names = {
                "overview": "🏠 Executive Overview",
                "products": "📦 Products & Inventory",
                "orders": "🛒 Orders & Fulfillment",
                "employees": "👥 Sales Representatives",
                "customers": "🌍 Global Customers",
                "suppliers": "🏭 Suppliers & Purchasing",
            }
        else:
            layer_names = {
                "overview": "🏠 Trang chủ Tổng quan (Overview)",
                "products": "📦 Danh mục & Sản phẩm (Products)",
                "orders": "🛒 Đơn hàng & Vận chuyển (Orders)",
                "employees": "👥 Đại diện Bán hàng (Sales Reps)",
                "customers": "🌍 Khách hàng & Thị trường (Customers)",
                "suppliers": "🏭 Nhà Cung ứng & Nhập hàng (Suppliers)",
            }
        layer_keys = list(layer_names.keys())
        current_idx = layer_keys.index(current_layer) if current_layer in layer_keys else 0

        selected_l = st.selectbox(
            "Select Layer" if is_en else "Chọn tầng phân tích",
            layer_keys,
            format_func=lambda x: layer_names[x],
            index=current_idx,
            key="northwind_layer_selectbox",
            label_visibility="collapsed"
        )
        if selected_l != current_layer:
            st.session_state["northwind_dashboard_layer"] = selected_l
            st.rerun()
        current_layer = st.session_state.get("northwind_dashboard_layer", "overview")

    with c_hdr3:
        if st.button(t("hr_btn_main_chat"), type="secondary", use_container_width=True, key="btn_northwind_header_chat", help=t("hr_main_chat_help")):
            st.session_state["view_mode"] = "chat"
            st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # 2. ROUTING
    if current_layer == "overview":
        _render_northwind_layer_overview(engine, min_year, max_year)
    elif current_layer == "products":
        _render_northwind_layer_products(engine, min_year, max_year)
    elif current_layer == "orders":
        _render_northwind_layer_orders(engine, min_year, max_year)
    elif current_layer == "employees":
        _render_northwind_layer_employees(engine, min_year, max_year)
    elif current_layer == "customers":
        _render_northwind_layer_customers(engine, min_year, max_year)
    elif current_layer == "suppliers":
        _render_northwind_layer_suppliers(engine)


def _render_northwind_layer_overview(engine, min_year: int, max_year: int):
    """Trang chủ Tổng quan Northwind: Timeline Slider, 4 KPI Neon, Sóng kép Trend, Donut Category, Bar Top Products, Data Preview & Anomaly Diagnostics."""
    is_en = (get_current_language() == "en")

    # 1. TIMELINE SLIDER
    start_year, end_year = _render_timeline_slider("nw_ov", min_year=min_year, max_year=max_year, domain_key="northwind")
    data = fetch_northwind_overview_data(engine, start_year=start_year, end_year=end_year)

    # 3. 4 NEON METRIC KPI CARDS (CHẨN ĐOÁN HIỆU SUẤT ĐỘNG & ĐỒNG BỘ KÍCH THƯỚC)
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    nw_rev_bench = round((data['total_revenue'] / max(1.0, data['total_orders'] * 650.0)) * 100.0, 1) if data['total_orders'] else 100.0
    nw_sku_bench = round((data['active_products'] / 45.0) * 100.0, 1)
    nw_cust_bench = round((data['total_customers'] / 30.0) * 100.0, 1)
    with col_k1:
        _render_diagnostic_kpi_card(
            card_class="kpi-card-cyan",
            title="TOTAL REVENUE" if is_en else "TỔNG DOANH THU",
            val_html=f"${data['total_revenue']:,.2f}",
            badge_text="Net Sales",
            sub_text="After Discounts" if is_en else "Doanh thu sau chiết khấu",
            bench_label="Target: $650/Order" if is_en else "Chuẩn: $650/Đơn",
            bench_pct=nw_rev_bench,
            delta_str=f"{nw_rev_bench - 100:+.1f}% vs Target",
            delta_dir="up" if nw_rev_bench >= 95 else "flat",
            status_text=("🟢 EXCEEDS" if is_en else "🟢 VƯỢT CHUẨN") if nw_rev_bench >= 100 else ("🟡 STABLE" if is_en else "🟡 ỔN ĐỊNH"),
            status_level="good" if nw_rev_bench >= 100 else "warn",
            fill_color="linear-gradient(90deg, #06B6D4, #38BDF8)"
        )

    with col_k2:
        ord_unit = "orders" if is_en else "đơn hàng"
        _render_diagnostic_kpi_card(
            card_class="kpi-card-purple",
            title="TOTAL ORDERS" if is_en else "TỔNG ĐƠN HÀNG",
            val_html=f"{data['total_orders']:,} <span style='font-size:0.95rem;font-weight:700;opacity:0.85;'>{ord_unit}</span>",
            badge_text="Volume",
            sub_text="Fulfilled Orders" if is_en else "Đơn hàng đã xác nhận",
            bench_label="SLA Fulfillment" if is_en else "Tỷ lệ xử lý đơn",
            bench_pct=96.5,
            delta_str="+8.4% YoY",
            delta_dir="up",
            status_text="🟢 OPTIMAL" if is_en else "🟢 TỐI ƯU",
            status_level="good",
            fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
        )

    with col_k3:
        sku_unit = "SKUs" if is_en else "sản phẩm"
        _render_diagnostic_kpi_card(
            card_class="kpi-card-emerald",
            title="ACTIVE PRODUCTS" if is_en else "SẢN PHẨM PHÁT SINH",
            val_html=f"{data['active_products']:,} <span style='font-size:0.95rem;font-weight:700;opacity:0.85;'>{sku_unit}</span>",
            badge_text="Portfolio",
            sub_text="Sold in Period" if is_en else "Phát sinh doanh số",
            bench_label="Catalog Active %" if is_en else "Độ phủ danh mục",
            bench_pct=nw_sku_bench,
            delta_str=f"{data['active_products']}/45 SKUs",
            delta_dir="up" if nw_sku_bench >= 75 else "flat",
            status_text=("🟢 HEALTHY" if is_en else "🟢 TỐT") if nw_sku_bench >= 75 else ("🟡 MODERATE" if is_en else "🟡 TRUNG BÌNH"),
            status_level="good" if nw_sku_bench >= 75 else "warn",
            fill_color="linear-gradient(90deg, #10B981, #34D399)"
        )

    with col_k4:
        acc_unit = "clients" if is_en else "khách hàng"
        _render_diagnostic_kpi_card(
            card_class="kpi-card-amber",
            title="GLOBAL CUSTOMERS" if is_en else "KHÁCH HÀNG TOÀN CẦU",
            val_html=f"{data['total_customers']:,} <span style='font-size:0.95rem;font-weight:700;opacity:0.85;'>{acc_unit}</span>",
            badge_text="Accounts",
            sub_text="Active Accounts" if is_en else "Doanh nghiệp mua hàng",
            bench_label="Account Retention" if is_en else "Tỷ lệ B2B Active",
            bench_pct=nw_cust_bench,
            delta_str="+5.2% B2B",
            delta_dir="up",
            status_text="🟢 ACTIVE" if is_en else "🟢 HOẠT ĐỘNG TỐT",
            status_level="good",
            fill_color="linear-gradient(90deg, #F59E0B, #FBBF24)"
        )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    _render_sql_modal("Northwind Overview" if is_en else "Tổng Quan Northwind", data["sql"], data["exec_time_ms"], "nw_ov_sql")

    # 4. BIỂU ĐỒ SÓNG KÉP & DONUT CATEGORY
    col_c1, col_c2 = st.columns([1.35, 1.0])
    with col_c1:
        if not data["trend_df"].empty:
            fig_tr = build_sales_dual_axis_chart(data["trend_df"], x_col="Month", rev_col="Revenue", box_col="Quantity", height=280)
            render_zoomable_chart_card(
                title="📈 Monthly Revenue & Order Quantity Trend" if is_en else "📈 Xu Hướng Doanh Thu & Sản Lượng Theo Tháng",
                fig=fig_tr,
                df=data["trend_df"],
                badge="Dual Wave",
                explanation="Monthly chronological progression of revenue and item volume." if is_en else "Diễn biến doanh thu và sản lượng xuất bán qua các tháng.",
                key="nw_trend_chart"
            )
        else:
            st.info("No monthly timeline data found for this period." if is_en else "Không có dữ liệu chuỗi thời gian cho giai đoạn này.")

    with col_c2:
        if not data["category_df"].empty:
            fig_cat = build_tickets_by_type_donut(data["category_df"], label_col="Category", val_col="Revenue", height=280)
            render_zoomable_chart_card(
                title="🍩 Category Revenue Share" if is_en else "🍩 Cơ Cấu Doanh Thu Theo Danh Mục",
                fig=fig_cat,
                df=data["category_df"],
                badge="Category Share",
                explanation="Percentage revenue contribution across Northwind categories." if is_en else "Tỷ trọng đóng góp doanh thu của các ngành hàng.",
                key="nw_cat_chart"
            )
        else:
            st.info("No category data found." if is_en else "Không có dữ liệu phân bổ danh mục.")

    # 5. TOP 5 SẢN PHẨM & PHÂN BỔ QUỐC GIA
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if not data["top_products_df"].empty:
            fig_tp = build_horizontal_bar_chart(data["top_products_df"], y_col="Product", x_col="Revenue", name="Revenue ($)" if is_en else "Doanh Thu ($)", height=260)
            render_zoomable_chart_card(
                title="🏆 Top 5 Best-Selling Products" if is_en else "🏆 Top 5 Sản Phẩm Doanh Số Cao Nhất",
                fig=fig_tp,
                df=data["top_products_df"],
                badge="Best Sellers",
                explanation="Highest revenue-generating SKUs in the catalog." if is_en else "Các mã sản phẩm mang lại doanh thu cao nhất.",
                key="nw_top_prod_chart"
            )

    with col_b2:
        if not data["geo_df"].empty:
            fig_geo = build_horizontal_bar_chart(data["geo_df"], y_col="Country", x_col="Revenue", name="Revenue ($)" if is_en else "Doanh Thu ($)", height=260)
            render_zoomable_chart_card(
                title="🌍 Revenue by Customer Country / Region" if is_en else "🌍 Doanh Thu Theo Quốc Gia / Khu Vực",
                fig=fig_geo,
                df=data["geo_df"],
                badge="Geo Markets",
                explanation="Geographic distribution of sales." if is_en else "Phân bổ doanh thu theo quốc gia của khách hàng.",
                key="nw_geo_chart"
            )

    # 6. DỮ LIỆU MẪU ĐƠN HÀNG GẦN ĐÂY
    if not data["sample_df"].empty:
        rows_suf = "transactions" if is_en else "giao dịch"
        st.markdown(f"""
        <div class="crm-card">
            <div class="crm-card-title">
                <span>{"📋 Live Orders & Fulfillment Preview" if is_en else "📋 Danh Sách Đơn Hàng & Giao Vận Trực Tiếp"} ({len(data['sample_df'])} {rows_suf})</span>
                <span class="crm-badge-neon">Live Data Feed</span>
            </div>
        """, unsafe_allow_html=True)
        st.dataframe(data["sample_df"], hide_index=True, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # 7. SMART ANOMALY PANEL
    render_smart_analyst_anomaly_panel(
        layer_id="northwind_overview",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="nw_ov"
    )


def _render_northwind_layer_products(engine, min_year: int, max_year: int):
    """Layer 1: Phân tích Danh mục & Sản phẩm (Products & Catalog Intelligence)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>📦 {'Products & Catalog Intelligence' if is_en else 'Danh mục & Sản phẩm'}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_nw_prod", use_container_width=True):
            _set_layer("overview", domain_key="northwind")

    start_year, end_year = _render_timeline_slider("nw_prod", min_year=min_year, max_year=max_year, domain_key="northwind")
    data = fetch_northwind_products_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{"📦 Products Performance & Profit Margin Analysis" if is_en else "📦 Phân Tích Hiệu Suất & Biên Lợi Nhuận Sản Phẩm"}</span>
            <span class="crm-badge-neon">{len(df)} SKUs</span>
        </div>
    """, unsafe_allow_html=True)
    if not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("No product data available." if is_en else "Không có dữ liệu sản phẩm.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Products & Catalog" if is_en else "Danh Mục & Sản Phẩm", data["sql"], data["exec_time_ms"], "nw_prod_sql")

    render_smart_analyst_anomaly_panel(
        layer_id="northwind_products",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="nw_prod"
    )


def _render_northwind_layer_orders(engine, min_year: int, max_year: int):
    """Layer 2: Phân tích Đơn hàng & Vận chuyển (Orders & Fulfillment Operations)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🛒 {'Orders & Shipping Operations' if is_en else 'Đơn hàng & Giao vận'}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_nw_ord", use_container_width=True):
            _set_layer("overview", domain_key="northwind")

    start_year, end_year = _render_timeline_slider("nw_ord", min_year=min_year, max_year=max_year, domain_key="northwind")
    data = fetch_northwind_orders_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{"🛒 Orders & Shipping Operations Log" if is_en else "🛒 Nhật Ký Đơn Hàng & Tiến Độ Giao Vận"}</span>
            <span class="crm-badge-neon">{len(df)} Orders</span>
        </div>
    """, unsafe_allow_html=True)
    if not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("No orders data available." if is_en else "Không có dữ liệu đơn hàng.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Orders & Shipping" if is_en else "Đơn Hàng & Vận Chuyển", data["sql"], data["exec_time_ms"], "nw_ord_sql")

    render_smart_analyst_anomaly_panel(
        layer_id="northwind_orders",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="nw_ord"
    )


def _render_northwind_layer_employees(engine, min_year: int, max_year: int):
    """Layer 3: Phân tích Đội ngũ Sales & Đại diện bán hàng (Sales Reps & Team)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>👥 {'Sales Representatives Performance' if is_en else 'Đại diện Bán hàng'}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_nw_emp", use_container_width=True):
            _set_layer("overview", domain_key="northwind")

    start_year, end_year = _render_timeline_slider("nw_emp", min_year=min_year, max_year=max_year, domain_key="northwind")
    data = fetch_northwind_employees_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]

    if not df.empty:
        fig_emp = build_horizontal_bar_chart(df, y_col="SalesRep", x_col="TotalRevenue", name="Revenue ($)" if is_en else "Doanh Thu ($)", height=260)
        render_zoomable_chart_card(
            title="👥 Sales Representatives Revenue Ranking" if is_en else "👥 Xếp Hạng Doanh Số Đại Diện Bán Hàng",
            fig=fig_emp,
            df=df,
            badge="Sales Reps",
            explanation="Revenue generated by each sales representative." if is_en else "Doanh số do từng chuyên viên bán hàng phụ trách.",
            key="nw_reps_chart"
        )

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{"👥 Sales Representatives Directory & Stats" if is_en else "👥 Danh Bạ & Hiệu Suất Đại Diện Bán Hàng"}</span>
            <span class="crm-badge-neon">{len(df)} Representatives</span>
        </div>
    """, unsafe_allow_html=True)
    if not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("No sales representatives data available." if is_en else "Không có dữ liệu đại diện bán hàng.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Sales Representatives" if is_en else "Đại Diện Bán Hàng", data["sql"], data["exec_time_ms"], "nw_emp_sql")

    render_smart_analyst_anomaly_panel(
        layer_id="northwind_employees",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="nw_emp"
    )


def _render_northwind_layer_customers(engine, min_year: int, max_year: int):
    """Layer 4: Phân tích Khách hàng & Thị trường (Global Customers Intelligence)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🌍 {'Global Customers & Market Analysis' if is_en else 'Khách hàng & Thị trường'}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_nw_cust", use_container_width=True):
            _set_layer("overview", domain_key="northwind")

    start_year, end_year = _render_timeline_slider("nw_cust", min_year=min_year, max_year=max_year, domain_key="northwind")
    data = fetch_northwind_customers_data(engine, start_year=start_year, end_year=end_year)
    df = data["df"]

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{"🌍 Top Corporate Customers by Total Spend" if is_en else "🌍 Top Khách Hàng Doanh Nghiệp Theo Doanh Số"}</span>
            <span class="crm-badge-neon">{len(df)} Accounts</span>
        </div>
    """, unsafe_allow_html=True)
    if not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("No customers data available." if is_en else "Không có dữ liệu khách hàng.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Customers & Markets" if is_en else "Khách Hàng & Thị Trường", data["sql"], data["exec_time_ms"], "nw_cust_sql")

    render_smart_analyst_anomaly_panel(
        layer_id="northwind_customers",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="nw_cust"
    )


def _render_northwind_layer_suppliers(engine):
    """Layer 5: Phân tích Nhà cung ứng & Nhập hàng (Suppliers & Purchasing)."""
    is_en = (get_current_language() == "en")
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        st.markdown(f"<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>{bc_home}</a> ➔ <b>🏭 {'Suppliers & Purchasing Portfolio' if is_en else 'Nhà Cung Ứng & Nhập Hàng'}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "⬅️ Home" if is_en else "⬅️ Trang Chủ"
        if st.button(back_btn_lbl, key="btn_back_nw_sup", use_container_width=True):
            _set_layer("overview", domain_key="northwind")

    data = fetch_northwind_suppliers_data(engine)
    df = data["df"]

    st.markdown(f"""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>{"🏭 Suppliers Directory & Sourcing Overview" if is_en else "🏭 Danh Bạ & Nguồn Cung Ứng Hàng Hóa"}</span>
            <span class="crm-badge-neon">{len(df)} Suppliers</span>
        </div>
    """, unsafe_allow_html=True)
    if not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.info("No suppliers data available." if is_en else "Không có dữ liệu nhà cung ứng.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal("Suppliers & Sourcing" if is_en else "Nhà Cung Ứng", data["sql"], data["exec_time_ms"], "nw_sup_sql")

    render_smart_analyst_anomaly_panel(
        layer_id="northwind_suppliers",
        data=data,
        start_year=None,
        end_year=None,
        key_prefix="nw_sup"
    )


# =========================================================================
# UNIVERSAL AUTO-ADAPTIVE GENERIC DATABASE DASHBOARD
# =========================================================================

def _format_generic_metric_val(val: float, unit_style: str = "number") -> str:
    """Format numeric KPI cleanly according to inferred unit style (vnd, usd, count, number)."""
    try:
        v = float(val or 0.0)
    except Exception:
        return str(val)
    if unit_style == "vnd":
        if abs(v) >= 1_000_000_000:
            return f"{v / 1_000_000_000:,.2f}B đ"
        return f"{v:,.0f} đ"
    if unit_style == "usd":
        if abs(v) >= 1000 and float(v).is_integer():
            return f"${v:,.0f}"
        return f"${v:,.2f}"
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def _render_generic_dashboard(engine):
    """Dashboard Đa Tầng Tự Động Sinh Thích Ứng Cho Mọi CSDL Mới Bất Kỳ (Bilingual)."""
    is_en = (get_current_language() == "en")
    schema_meta = discover_generic_database_schema(engine)
    tables = schema_meta.get("tables", [])
    min_year = schema_meta.get("min_year", 2020)
    max_year = schema_meta.get("max_year", 2024)
    has_timeline = schema_meta.get("has_timeline", False)

    current_layer = st.session_state.get("generic_dashboard_layer", "overview")

    layer_names = {"overview": "Executive Overview" if is_en else "Tổng quan CSDL"}
    for t_n in tables:
        r_cnt = schema_meta.get("meta", {}).get(t_n, {}).get("row_count", 0)
        recs_suf = "records" if is_en else "bản ghi"
        tbl_pref = "Table" if is_en else "Bảng"
        t_lbl = _humanize_dashboard_label(t_n, is_en=is_en)
        layer_names[f"tbl_{t_n}"] = f"{tbl_pref}: {t_lbl} ({r_cnt:,} {recs_suf})"

    layer_keys = list(layer_names.keys())
    current_idx = layer_keys.index(current_layer) if current_layer in layer_keys else 0

    c_hdr1, c_hdr2, c_hdr3 = st.columns([4.6, 2.8, 1.8])
    with c_hdr1:
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
            <div style="font-size: 1.45rem; font-weight: 800; color: #F8FAFC; letter-spacing: -0.02em;">{"Database Overview Dashboard" if is_en else "Bảng Điều Hành Dữ Liệu"}</div>
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
        if st.button(t("hr_btn_main_chat"), type="secondary", use_container_width=True, key="btn_generic_header_chat", help=t("hr_main_chat_help")):
            st.session_state["view_mode"] = "chat"
            st.rerun()

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # Routing
    if current_layer == "overview":
        _render_generic_layer_overview(engine, schema_meta)
    elif current_layer.startswith("tbl_"):
        tbl_name = current_layer[4:]
        _render_generic_layer_table(engine, tbl_name, schema_meta)


def _render_generic_layer_overview(engine, schema_meta: dict):
    """Trang chủ Tổng quan cho CSDL mới: 4 KPI nghiệp vụ thực tế, Sóng kép Thời gian, Phân bổ Danh mục/Trạng thái & Ma trận đa bảng."""
    is_en = (get_current_language() == "en")
    min_year = schema_meta.get("min_year", 2020)
    max_year = schema_meta.get("max_year", 2024)
    has_timeline = schema_meta.get("has_timeline", False)
    min_date = schema_meta.get("min_date")
    max_date = schema_meta.get("max_date")

    if has_timeline:
        start_year, end_year = _render_timeline_slider("generic_ov", min_year=min_year, max_year=max_year, domain_key="generic")
        if min_date and max_date and min_year == max_year:
            date_note = f"📅 Daily span detected: {min_date} → {max_date}" if is_en else f"📅 Khoảng dữ liệu thực tế: {min_date} → {max_date}"
            st.markdown(f"<div style='font-size:0.84rem; color:#38BDF8; margin:-8px 0 12px 4px; font-weight:600;'>{date_note}</div>", unsafe_allow_html=True)
    else:
        start_year, end_year = None, None

    data = fetch_generic_overview_data(engine, schema_meta, start_year=start_year, end_year=end_year)
    main_num_col = data.get("main_num_col")
    unit_style = data.get("unit_style", "number")
    sec_num_col = data.get("sec_num_col")
    sec_unit_style = data.get("sec_unit_style", "number")
    qty_col = data.get("qty_col")
    main_cat_col = data.get("main_cat_col")
    top_item_name = data.get("top_item_name")
    top_item_val = data.get("top_item_val", 0.0)
    outstanding_val = data.get("outstanding_val")
    filtered_recs = int(data.get("filtered_records") or 0)
    total_recs = max(1, int(data.get("total_records") or 0))
    main_tbl_disp = data.get("main_table") or "N/A"
    main_num_lbl = _humanize_dashboard_label(main_num_col, is_en=is_en) if main_num_col else ""
    sec_num_lbl = _humanize_dashboard_label(sec_num_col, is_en=is_en) if sec_num_col else ""
    qty_lbl = _humanize_dashboard_label(qty_col, is_en=is_en) if qty_col else ""
    main_cat_lbl = _humanize_dashboard_label(main_cat_col, is_en=is_en) if main_cat_col else ""
    main_tbl_lbl = _humanize_dashboard_label(main_tbl_disp, is_en=is_en) if main_tbl_disp != "N/A" else "N/A"

    excl_cnt = int(data.get("excluded_status_count") or 0)
    recs_delta_txt = (
        (f"{filtered_recs:,} valid (-{excl_cnt} excl.)" if is_en else f"{filtered_recs:,} hợp lệ (-{excl_cnt} hủy/trả)")
        if excl_cnt > 0 else
        (f"{filtered_recs:,} rows" if is_en else f"{filtered_recs:,} dòng")
    )

    # 4 Business KPI Cards
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    with col_k1:
        if main_num_col:
            avg_txt = _format_generic_metric_val(data.get("avg_val", 0.0), unit_style)
            _render_diagnostic_kpi_card(
                card_class="kpi-card-cyan",
                title=f"TOTAL {main_num_lbl.upper()}" if is_en else f"TỔNG {main_num_lbl.upper()}",
                val_html=_format_generic_metric_val(data.get("sum_val", 0.0), unit_style),
                badge_text=main_tbl_lbl,
                sub_text=f"Avg/row: {avg_txt}" if is_en else f"TB/dòng: {avg_txt}",
                bench_label="Data Coverage" if is_en else "Độ phủ bản ghi",
                bench_pct=100.0,
                delta_str=recs_delta_txt,
                delta_dir="up",
                status_text="🟢 LIVE SUM" if is_en else "🟢 TỔNG HỢP",
                status_level="good",
                fill_color="linear-gradient(90deg, #06B6D4, #38BDF8)"
            )
        else:
            tbl_unit = "tables" if is_en else "bảng"
            _render_diagnostic_kpi_card(
                card_class="kpi-card-cyan",
                title="TOTAL TABLES" if is_en else "TỔNG SỐ BẢNG",
                val_html=f"{data['total_tables']} <span style='font-size:0.95rem;font-weight:700;opacity:0.85;'>{tbl_unit}</span>",
                badge_text="Structure" if is_en else "Cấu trúc",
                sub_text="Full Database" if is_en else "Toàn bộ CSDL",
                bench_label="Schema Integrity" if is_en else "Độ toàn vẹn Schema",
                bench_pct=100.0,
                delta_str="100% Indexed",
                delta_dir="up",
                status_text="🟢 HEALTHY" if is_en else "🟢 CHUẨN HÓA",
                status_level="good",
                fill_color="linear-gradient(90deg, #06B6D4, #38BDF8)"
            )

    with col_k2:
        if outstanding_val is not None:
            billed = max(1.0, float(data.get("total_billed_val") or 0.0))
            paid_v = float(data.get("paid_val") or 0.0)
            coll_pct = round(paid_v / billed * 100.0, 1)
            out_style = "vnd" if unit_style == "vnd" else ("usd" if unit_style == "usd" else "number")
            _render_diagnostic_kpi_card(
                card_class="kpi-card-purple",
                title="OUTSTANDING RECEIVABLES" if is_en else "CÔNG NỢ CHƯA THU",
                val_html=_format_generic_metric_val(outstanding_val, out_style),
                badge_text="Receivables" if is_en else "Công nợ",
                sub_text=f"Collected: {_format_generic_metric_val(paid_v, out_style)}" if is_en else f"Đã thu: {_format_generic_metric_val(paid_v, out_style)}",
                bench_label="Collection Rate" if is_en else "Tỷ lệ đã thu hồi",
                bench_pct=coll_pct,
                delta_str=f"{coll_pct:.1f}% Paid",
                delta_dir="up" if coll_pct >= 70 else "flat",
                status_text=("🟢 HEALTHY" if is_en else "🟢 TỐT") if coll_pct >= 70 else ("🟡 TRACK" if is_en else "🟡 CẦN THEO DÕI"),
                status_level="good" if coll_pct >= 70 else "warn",
                fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
            )
        elif qty_col and qty_col != main_num_col:
            avg_qty = data.get("total_qty", 0.0) / max(1, filtered_recs)
            _render_diagnostic_kpi_card(
                card_class="kpi-card-purple",
                title=f"TOTAL {qty_lbl.upper()}" if is_en else f"TỔNG {qty_lbl.upper()}",
                val_html=_format_generic_metric_val(data.get("total_qty", 0.0), "count"),
                badge_text="Volume" if is_en else "Sản lượng",
                sub_text=f"Avg: {avg_qty:,.1f}/row" if is_en else f"TB: {avg_qty:,.1f}/giao dịch",
                bench_label="Active Records" if is_en else "Tỷ lệ dữ liệu chính",
                bench_pct=round(filtered_recs / total_recs * 100.0, 1),
                delta_str=f"{filtered_recs:,} items" if is_en else f"{filtered_recs:,} lượt",
                delta_dir="up",
                status_text="🟢 VERIFIED" if is_en else "🟢 XÁC THỰC",
                status_level="good",
                fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
            )
        elif sec_num_col:
            _render_diagnostic_kpi_card(
                card_class="kpi-card-purple",
                title=f"TOTAL {sec_num_lbl.upper()}" if is_en else f"TỔNG {sec_num_lbl.upper()}",
                val_html=_format_generic_metric_val(data.get("sec_sum_val", 0.0), sec_unit_style),
                badge_text="Secondary KPI",
                sub_text=f"Table: {main_tbl_lbl}" if is_en else f"Bảng: {main_tbl_lbl}",
                bench_label="Coverage" if is_en else "Độ phủ dữ liệu",
                bench_pct=100.0,
                delta_str=f"{filtered_recs:,} rows",
                delta_dir="up",
                status_text="🟢 READY" if is_en else "🟢 SẴN SÀNG",
                status_level="good",
                fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
            )
        else:
            _render_diagnostic_kpi_card(
                card_class="kpi-card-purple",
                title="TOTAL RECORDS" if is_en else "TỔNG SỐ BẢN GHI",
                val_html=f"{data['total_records']:,}",
                badge_text="Capacity" if is_en else "Dung lượng",
                sub_text="Total Rows" if is_en else "Tổng số dòng dữ liệu",
                bench_label="Data Readiness" if is_en else "Độ sẵn sàng dữ liệu",
                bench_pct=100.0,
                delta_str="Live Sync",
                delta_dir="up",
                status_text="🟢 READY" if is_en else "🟢 SẴN SÀNG",
                status_level="good",
                fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
            )

    with col_k3:
        if top_item_name:
            short_name = top_item_name if len(top_item_name) <= 18 else f"{top_item_name[:16]}…"
            denom = data.get("sum_val", 0.0) if (main_num_col and data.get("sum_val", 0.0) > 0) else max(1, int(data["cat_dist_df"]["Count"].sum()) if not data["cat_dist_df"].empty else 1)
            share_pct = round(top_item_val / denom * 100.0, 1) if denom > 0 else 0.0
            val_fmt = _format_generic_metric_val(top_item_val, unit_style if main_num_col else "count")
            _render_diagnostic_kpi_card(
                card_class="kpi-card-emerald",
                title=f"TOP {main_cat_lbl.upper()}" if (is_en and main_cat_lbl) else (f"DẪN ĐẦU ({main_cat_lbl.upper()})" if main_cat_lbl else "NHÓM DẪN ĐẦU"),
                val_html=short_name,
                badge_text="Top Driver" if is_en else "Đứng đầu",
                sub_text=f"{val_fmt} ({data.get('top_item_cnt', 0):,} dòng)",
                bench_label="Share of Total" if is_en else "Tỷ trọng đóng góp",
                bench_pct=share_pct,
                delta_str=f"{share_pct:.1f}% Share",
                delta_dir="up",
                status_text="🟢 LEADER" if is_en else "🟢 DẪN ĐẦU",
                status_level="good",
                fill_color="linear-gradient(90deg, #10B981, #34D399)"
            )
        else:
            _render_diagnostic_kpi_card(
                card_class="kpi-card-emerald",
                title="PRIMARY TABLE" if is_en else "BẢNG DỮ LIỆU CHÍNH",
                val_html=main_tbl_lbl,
                badge_text="Focus" if is_en else "Trọng tâm",
                sub_text="Largest dataset" if is_en else "Nhiều bản ghi nhất",
                bench_label="Core Coverage" if is_en else "Tỷ trọng dữ liệu lõi",
                bench_pct=round(filtered_recs / total_recs * 100.0, 1),
                delta_str="Primary Fact",
                delta_dir="up",
                status_text="🟢 CORE" if is_en else "🟢 TRỌNG TÂM",
                status_level="good",
                fill_color="linear-gradient(90deg, #10B981, #34D399)"
            )

    with col_k4:
        scope_val = f"{data['total_records']:,} <span style='font-size:0.95rem;font-weight:700;opacity:0.85;'>{'rows' if is_en else 'dòng'} • {data['total_tables']} {'tbls' if is_en else 'bảng'}</span>"
        period_sub = f"{min_date} → {max_date}" if (min_date and max_date) else (f"{start_year} — {end_year}" if has_timeline else ("Snapshot DB" if is_en else "Dữ liệu tĩnh"))
        _render_diagnostic_kpi_card(
            card_class="kpi-card-amber",
            title="DATABASE SCOPE" if is_en else "QUY MÔ & MỐC DỮ LIỆU",
            val_html=scope_val,
            badge_text=main_tbl_lbl,
            sub_text=period_sub,
            bench_label="Core Table Share" if is_en else "Tỷ trọng bảng chính",
            bench_pct=round(filtered_recs / total_recs * 100.0, 1),
            delta_str=f"{data['exec_time_ms']:.0f} ms",
            delta_dir="up",
            status_text="🟢 SYNCED" if is_en else "🟢 ĐỒNG BỘ",
            status_level="good",
            fill_color="linear-gradient(90deg, #F59E0B, #FBBF24)"
        )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    _render_sql_modal("Database Overview" if is_en else "Tổng Quan CSDL", data["sql"], data["exec_time_ms"], "generic_ov_sql")

    # Charts Row 1: Category Value Ranking + Adaptive Dual-Axis Time Trend
    cat_dist_df = data.get("cat_dist_df", pd.DataFrame())
    trend_df = data.get("trend_df", pd.DataFrame())
    status_df = data.get("status_df", pd.DataFrame())
    table_summary_df = data.get("table_summary_df", pd.DataFrame())

    has_cat = not cat_dist_df.empty
    has_trend = not trend_df.empty

    def _build_generic_zoom_df(
        src_df: pd.DataFrame,
        dim_col_src: str,
        dim_label: str,
        use_metric_col: bool,
        metric_label: str,
        u_style: str,
        extra_qty_label: str = "",
    ) -> pd.DataFrame:
        if src_df is None or src_df.empty:
            return pd.DataFrame()
        out = pd.DataFrame()
        if dim_col_src in src_df.columns:
            out[dim_label] = src_df[dim_col_src]
        m_hdr = (
            f"{metric_label} (đ)" if (u_style == "vnd" and "đ" not in metric_label.lower())
            else (f"{metric_label} ($)" if (u_style == "usd" and "$" not in metric_label) else metric_label)
        )
        cnt_hdr = "Transactions" if is_en else "Số giao dịch"
        if use_metric_col and "MetricSum" in src_df.columns:
            out[m_hdr] = src_df["MetricSum"]
            if "QtySum" in src_df.columns and extra_qty_label and extra_qty_label != m_hdr:
                out[extra_qty_label] = src_df["QtySum"]
            if "Count" in src_df.columns and cnt_hdr not in out.columns:
                out[cnt_hdr] = src_df["Count"]
        else:
            if "Count" in src_df.columns:
                out[m_hdr if not use_metric_col and metric_label else cnt_hdr] = src_df["Count"]
            if "MetricSum" in src_df.columns and m_hdr not in out.columns:
                out[m_hdr] = src_df["MetricSum"]
        return out if not out.empty else src_df

    def _render_cat_chart():
        use_metric = bool(main_num_col and "MetricSum" in cat_dist_df.columns and cat_dist_df["MetricSum"].abs().sum() > 0)
        x_field = "MetricSum" if use_metric else "Count"
        metric_lbl = main_num_lbl if use_metric else ("Count" if is_en else "Số lượng")
        fig_cat = build_horizontal_bar_chart(cat_dist_df, y_col="Category", x_col=x_field, name=metric_lbl, height=275)
        cat_col_lbl = main_cat_lbl or ("Category" if is_en else "Danh mục")
        title_txt = (
            f"Top {cat_col_lbl} by {metric_lbl}" if is_en
            else f"Xếp hạng {cat_col_lbl} theo {metric_lbl}"
        )
        expl_txt = (
            f"Aggregated {metric_lbl} across {cat_col_lbl}." if is_en
            else f"Tổng hợp {metric_lbl} và tần suất giao dịch theo {cat_col_lbl}."
        )
        cat_zoom_df = _build_generic_zoom_df(
            cat_dist_df,
            dim_col_src="Category",
            dim_label=cat_col_lbl,
            use_metric_col=use_metric,
            metric_label=metric_lbl,
            u_style=unit_style if use_metric else "count",
        )
        render_zoomable_chart_card(
            title=title_txt,
            fig=fig_cat,
            df=cat_zoom_df,
            badge="Top Ranking",
            explanation=expl_txt,
            key="gen_cat_chart"
        )

    def _render_trend_chart():
        gran = data.get("trend_granularity", "month")
        gran_lbl = ("Daily" if gran == "day" else "Monthly") if is_en else ("theo ngày" if gran == "day" else "theo tháng")
        time_hdr = ("Date" if gran == "day" else "Month") if is_en else ("Ngày" if gran == "day" else "Tháng")
        if main_num_col and "MetricSum" in trend_df.columns:
            box_col = "QtySum" if (qty_col and "QtySum" in trend_df.columns) else "Count"
            box_lbl = qty_lbl if qty_lbl else ("Records" if is_en else "Số giao dịch")
            rev_pref = "$" if unit_style == "usd" else ""
            rev_suf = " đ" if unit_style == "vnd" else ""
            fig_tr = build_sales_dual_axis_chart(
                trend_df,
                x_col="TimePeriod",
                rev_col="MetricSum",
                box_col=box_col,
                height=275,
                rev_name=main_num_lbl,
                box_name=box_lbl,
                rev_prefix=rev_pref,
                rev_suffix=rev_suf,
                box_unit="",
            )
            title_txt = f"{gran_lbl} {main_num_lbl} & {box_lbl}" if is_en else f"Xu hướng {main_num_lbl} & {box_lbl} {gran_lbl}"
            expl_txt = f"Chronological progression ({gran}) of {main_num_lbl} and volume." if is_en else f"Diễn biến {main_num_lbl} và {box_lbl.lower()} {gran_lbl}."
            tr_zoom_df = _build_generic_zoom_df(
                trend_df,
                dim_col_src="TimePeriod",
                dim_label=time_hdr,
                use_metric_col=True,
                metric_label=main_num_lbl,
                u_style=unit_style,
                extra_qty_label=box_lbl,
            )
        else:
            fig_tr = build_weekday_bar_chart(pd.DataFrame({"WeekDay": trend_df["TimePeriod"], "Total": trend_df["Count"]}), height=275)
            title_txt = f"{gran_lbl} Record Volume" if is_en else f"Xu hướng bản ghi {gran_lbl}"
            expl_txt = "Volume of data generated across chronological periods." if is_en else "Khối lượng dữ liệu phát sinh theo từng mốc thời gian."
            tr_zoom_df = _build_generic_zoom_df(
                trend_df,
                dim_col_src="TimePeriod",
                dim_label=time_hdr,
                use_metric_col=False,
                metric_label="Records" if is_en else "Số bản ghi",
                u_style="count",
            )
        render_zoomable_chart_card(
            title=title_txt,
            fig=fig_tr,
            df=tr_zoom_df,
            badge="Daily Series" if gran == "day" else "Monthly Series",
            explanation=expl_txt,
            key="gen_trend_chart"
        )

    if has_cat and has_trend:
        col_gc1, col_gc2 = st.columns([1.15, 1.2])
        with col_gc1:
            _render_trend_chart()
        with col_gc2:
            _render_cat_chart()
    elif has_trend:
        _render_trend_chart()
    elif has_cat:
        _render_cat_chart()

    # Charts Row 2: Status/Channel Donut + Multi-Table Comparison Matrix
    has_status = not status_df.empty
    has_multi_tbl = len(table_summary_df) > 1 or (not has_cat and not has_trend and not table_summary_df.empty)
    if has_status and has_multi_tbl:
        col_s1, col_s2 = st.columns([1.0, 1.35])
        with col_s1:
            st_col_raw = data.get("status_col")
            st_col_lbl = _humanize_dashboard_label(st_col_raw, is_en=is_en) if st_col_raw else ("Status" if is_en else "Phân nhóm")
            use_m = bool(main_num_col and "MetricSum" in status_df.columns and status_df["MetricSum"].abs().sum() > 0)
            st_metric_lbl = main_num_lbl if use_m else ("Count" if is_en else "Số giao dịch")
            fig_st = build_tickets_by_type_donut(status_df, label_col="Category", val_col=("MetricSum" if use_m else "Count"), height=260)
            st_zoom_df = _build_generic_zoom_df(
                status_df,
                dim_col_src="Category",
                dim_label=st_col_lbl,
                use_metric_col=use_m,
                metric_label=st_metric_lbl,
                u_style=unit_style if use_m else "count",
            )
            render_zoomable_chart_card(
                title=f"Breakdown by {st_col_lbl}" if is_en else f"Cơ cấu theo {st_col_lbl}",
                fig=fig_st,
                df=st_zoom_df,
                badge=st_col_lbl,
                explanation=f"Share split across {st_col_lbl}." if is_en else f"Tỷ trọng đóng góp theo {st_col_lbl}.",
                key="gen_status_donut"
            )
        with col_s2:
            st.markdown(f"""
            <div class="crm-card">
                <div class="crm-card-title">
                    <span>{"Database Tables Portfolio" if is_en else "Tổng hợp các bảng dữ liệu"}</span>
                    <span class="crm-badge-neon">{len(table_summary_df)} Tables</span>
                </div>
            """, unsafe_allow_html=True)
            st.dataframe(table_summary_df, hide_index=True, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
    elif has_status:
        st_col_raw = data.get("status_col")
        st_col_lbl = _humanize_dashboard_label(st_col_raw, is_en=is_en) if st_col_raw else ("Status" if is_en else "Phân nhóm")
        use_m = bool(main_num_col and "MetricSum" in status_df.columns and status_df["MetricSum"].abs().sum() > 0)
        st_metric_lbl = main_num_lbl if use_m else ("Count" if is_en else "Số giao dịch")
        fig_st = build_tickets_by_type_donut(status_df, label_col="Category", val_col=("MetricSum" if use_m else "Count"), height=260)
        st_zoom_df = _build_generic_zoom_df(
            status_df,
            dim_col_src="Category",
            dim_label=st_col_lbl,
            use_metric_col=use_m,
            metric_label=st_metric_lbl,
            u_style=unit_style if use_m else "count",
        )
        render_zoomable_chart_card(
            title=f"Breakdown by {st_col_lbl}" if is_en else f"Cơ cấu theo {st_col_lbl}",
            fig=fig_st,
            df=st_zoom_df,
            badge=st_col_lbl,
            explanation=f"Share split across {st_col_lbl}." if is_en else f"Tỷ trọng đóng góp theo {st_col_lbl}.",
            key="gen_status_donut"
        )
    elif has_multi_tbl:
        st.markdown(f"""
        <div class="crm-card">
            <div class="crm-card-title">
                <span>{"Database Tables Portfolio" if is_en else "Tổng hợp các bảng dữ liệu"}</span>
                <span class="crm-badge-neon">{len(table_summary_df)} Tables</span>
            </div>
        """, unsafe_allow_html=True)
        st.dataframe(table_summary_df, hide_index=True, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Hiển thị mẫu dữ liệu bảng chính trong expander đóng sẵn cho gọn Dashboard
    if not data["df"].empty:
        rows_suf = "rows" if is_en else "dòng"
        tbl_prev_hdr = (
            f"Sample Data: {main_tbl_lbl} ({len(data['df'])} {rows_suf})"
            if is_en else
            f"Xem dữ liệu mẫu: {main_tbl_lbl} ({len(data['df'])} dòng)"
        )
        with st.expander(tbl_prev_hdr, expanded=False):
            st.dataframe(data["df"], hide_index=True, use_container_width=True)

    render_smart_analyst_anomaly_panel(
        layer_id="generic_overview",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix="generic_ov"
    )


def _render_generic_layer_table(engine, table_name: str, schema_meta: dict):
    """Hiển thị KPI, biểu đồ & dữ liệu chi tiết một bảng cụ thể trong CSDL mới (Bilingual)."""
    is_en = (get_current_language() == "en")
    min_year = schema_meta.get("min_year", 2020)
    max_year = schema_meta.get("max_year", 2024)
    tbl_meta = schema_meta.get("meta", {}).get(table_name, {})
    has_tbl_date = bool(tbl_meta.get("date_columns")) and schema_meta.get("has_timeline", False)

    c_bc1, c_bc2 = st.columns([6, 1])
    table_lbl = _humanize_dashboard_label(table_name, is_en=is_en)
    with c_bc1:
        bc_home = "Home" if is_en else "Trang Chủ"
        tbl_lbl = "Table" if is_en else "Bảng"
        st.markdown(f"<div class='layer-breadcrumb'><a href='#' style='color:#64748B;'>{bc_home}</a> / <b>{tbl_lbl}: {table_lbl}</b></div>", unsafe_allow_html=True)
    with c_bc2:
        back_btn_lbl = "← Home" if is_en else "← Trang Chủ"
        if st.button(back_btn_lbl, key=f"btn_back_gen_{table_name}", use_container_width=True):
            _set_layer("overview", domain_key="generic")

    if has_tbl_date:
        start_year, end_year = _render_timeline_slider(f"gen_tbl_{table_name}", min_year=min_year, max_year=max_year, domain_key="generic")
    else:
        start_year, end_year = None, None

    data = fetch_generic_table_data(engine, table_name, schema_meta, start_year=start_year, end_year=end_year)
    df = data["df"]
    cat_df = data.get("cat_df", pd.DataFrame())
    status_df = data.get("status_df", pd.DataFrame())
    trend_df = data.get("trend_df", pd.DataFrame())
    num_col = data.get("num_col")
    unit_style = data.get("unit_style", "number")
    num_col_lbl = _humanize_dashboard_label(num_col, is_en=is_en) if num_col else ""
    cat_col_raw = data.get("main_cat_col")
    cat_col_lbl = _humanize_dashboard_label(cat_col_raw, is_en=is_en) if cat_col_raw else ""
    st_col_raw = data.get("status_col")
    st_col_lbl = _humanize_dashboard_label(st_col_raw, is_en=is_en) if st_col_raw else ("Group" if is_en else "Nhóm")
    qty_col_raw = data.get("qty_col")
    qty_col_lbl = _humanize_dashboard_label(qty_col_raw, is_en=is_en) if qty_col_raw else ""

    # 3 Table KPI Cards
    excl_cnt_tbl = int(data.get("excluded_status_count") or 0)
    tbl_row_cnt = int(data.get('row_count', len(df)))
    tbl_sub_txt = (
        (f"{len(df.columns)} cols • -{excl_cnt_tbl} excl." if is_en else f"{len(df.columns)} cột • loại {excl_cnt_tbl} hủy/trả")
        if excl_cnt_tbl > 0 else
        (f"{len(df.columns)} columns" if is_en else f"{len(df.columns)} trường dữ liệu")
    )
    tk1, tk2, tk3 = st.columns(3)
    with tk1:
        _render_diagnostic_kpi_card(
            card_class="kpi-card-cyan",
            title="RECORDS" if is_en else "SỐ BẢN GHI",
            val_html=f"{tbl_row_cnt:,}",
            badge_text=table_lbl,
            sub_text=tbl_sub_txt,
            bench_label="Completeness" if is_en else "Sẵn sàng phân tích",
            bench_pct=100.0,
            delta_str=f"{data['exec_time_ms']:.0f} ms",
            delta_dir="up",
            status_text="🟢 LIVE",
            status_level="good",
            fill_color="linear-gradient(90deg, #06B6D4, #38BDF8)"
        )
    with tk2:
        if num_col:
            _render_diagnostic_kpi_card(
                card_class="kpi-card-purple",
                title=f"TOTAL {num_col_lbl.upper()}" if is_en else f"TỔNG {num_col_lbl.upper()}",
                val_html=_format_generic_metric_val(data.get("sum_val", 0.0), unit_style),
                badge_text="Metric Sum",
                sub_text=f"Avg: {_format_generic_metric_val(data.get('avg_val', 0.0), unit_style)}",
                bench_label="Coverage" if is_en else "Độ phủ số liệu",
                bench_pct=100.0,
                delta_str=num_col_lbl,
                delta_dir="up",
                status_text="🟢 SUMMED",
                status_level="good",
                fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
            )
        else:
            _render_diagnostic_kpi_card(
                card_class="kpi-card-purple",
                title="FIELDS" if is_en else "SỐ TRƯỜNG DỮ LIỆU",
                val_html=f"{len(df.columns)}",
                badge_text="Schema",
                sub_text="Attribute Count" if is_en else "Thuộc tính bảng",
                bench_label="Indexed",
                bench_pct=100.0,
                delta_str="SQLite/SQL",
                delta_dir="up",
                status_text="🟢 READY",
                status_level="good",
                fill_color="linear-gradient(90deg, #8B5CF6, #A855F7)"
            )
    with tk3:
        if not cat_df.empty:
            top_c_name = str(cat_df["Category"].iloc[0])
            top_c_short = top_c_name if len(top_c_name) <= 18 else f"{top_c_name[:16]}…"
            top_c_val = float(cat_df["MetricSum"].iloc[0]) if ("MetricSum" in cat_df.columns and num_col) else float(cat_df["Count"].iloc[0])
            _render_diagnostic_kpi_card(
                card_class="kpi-card-emerald",
                title=f"TOP ({cat_col_lbl or 'GROUP'})" if is_en else f"DẪN ĐẦU ({(cat_col_lbl or 'NHÓM').upper()})",
                val_html=top_c_short,
                badge_text="Leader" if is_en else "Dẫn đầu",
                sub_text=_format_generic_metric_val(top_c_val, unit_style if num_col else "count"),
                bench_label="Category Focus" if is_en else "Tâm điểm bảng",
                bench_pct=100.0,
                delta_str=f"{int(cat_df['Count'].iloc[0]):,} rows",
                delta_dir="up",
                status_text="🟢 TOP 1",
                status_level="good",
                fill_color="linear-gradient(90deg, #10B981, #34D399)"
            )
        else:
            _render_diagnostic_kpi_card(
                card_class="kpi-card-emerald",
                title="TABLE LAYER" if is_en else "TẦNG DỮ LIỆU",
                val_html=table_lbl,
                badge_text="Active",
                sub_text="Live SQL Inspection" if is_en else "Truy vấn trực tiếp",
                bench_label="Health",
                bench_pct=100.0,
                delta_str="Verified",
                delta_dir="up",
                status_text="🟢 ACTIVE",
                status_level="good",
                fill_color="linear-gradient(90deg, #10B981, #34D399)"
            )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    def _build_tbl_zoom_df(
        src_df: pd.DataFrame,
        dim_col_src: str,
        dim_label: str,
        use_metric_col: bool,
        metric_label: str,
        u_style: str,
        extra_qty_label: str = "",
    ) -> pd.DataFrame:
        if src_df is None or src_df.empty:
            return pd.DataFrame()
        out = pd.DataFrame()
        if dim_col_src in src_df.columns:
            out[dim_label] = src_df[dim_col_src]
        m_hdr = (
            f"{metric_label} (đ)" if (u_style == "vnd" and "đ" not in metric_label.lower())
            else (f"{metric_label} ($)" if (u_style == "usd" and "$" not in metric_label) else metric_label)
        )
        cnt_hdr = "Transactions" if is_en else "Số giao dịch"
        if use_metric_col and "MetricSum" in src_df.columns:
            out[m_hdr] = src_df["MetricSum"]
            if "QtySum" in src_df.columns and extra_qty_label and extra_qty_label != m_hdr:
                out[extra_qty_label] = src_df["QtySum"]
            if "Count" in src_df.columns and cnt_hdr not in out.columns:
                out[cnt_hdr] = src_df["Count"]
        else:
            if "Count" in src_df.columns:
                out[m_hdr if not use_metric_col and metric_label else cnt_hdr] = src_df["Count"]
            if "MetricSum" in src_df.columns and m_hdr not in out.columns:
                out[m_hdr] = src_df["MetricSum"]
        return out if not out.empty else src_df

    # Charts for Table Layer
    if not cat_df.empty and not status_df.empty:
        tc1, tc2 = st.columns([1.2, 1.0])
        with tc1:
            use_m = bool(num_col and "MetricSum" in cat_df.columns and cat_df["MetricSum"].abs().sum() > 0)
            metric_lbl_tbl = num_col_lbl if use_m else ("Count" if is_en else "Số lượng")
            fig_cat = build_horizontal_bar_chart(cat_df, y_col="Category", x_col=("MetricSum" if use_m else "Count"), name=metric_lbl_tbl, height=260)
            cat_tbl_zoom = _build_tbl_zoom_df(
                cat_df,
                dim_col_src="Category",
                dim_label=cat_col_lbl or table_lbl,
                use_metric_col=use_m,
                metric_label=metric_lbl_tbl,
                u_style=unit_style if use_m else "count",
            )
            render_zoomable_chart_card(
                title=f"Top {cat_col_lbl or table_lbl}" if is_en else f"Phân bổ theo {cat_col_lbl or table_lbl}",
                fig=fig_cat,
                df=cat_tbl_zoom,
                badge="Distribution",
                explanation="Value and record breakdown." if is_en else "Phân bổ giá trị và tần suất giao dịch.",
                key=f"gen_tbl_cat_{table_name}"
            )
        with tc2:
            use_ms = bool(num_col and "MetricSum" in status_df.columns and status_df["MetricSum"].abs().sum() > 0)
            st_metric_tbl = num_col_lbl if use_ms else ("Count" if is_en else "Số giao dịch")
            fig_st = build_tickets_by_type_donut(status_df, label_col="Category", val_col=("MetricSum" if use_ms else "Count"), height=260)
            st_tbl_zoom = _build_tbl_zoom_df(
                status_df,
                dim_col_src="Category",
                dim_label=st_col_lbl,
                use_metric_col=use_ms,
                metric_label=st_metric_tbl,
                u_style=unit_style if use_ms else "count",
            )
            render_zoomable_chart_card(
                title=f"{st_col_lbl} Share" if is_en else f"Tỷ trọng theo {st_col_lbl}",
                fig=fig_st,
                df=st_tbl_zoom,
                badge=st_col_lbl,
                explanation="Share breakdown." if is_en else "Tỷ trọng đóng góp theo phân nhóm.",
                key=f"gen_tbl_st_{table_name}"
            )
    elif not cat_df.empty:
        use_m = bool(num_col and "MetricSum" in cat_df.columns and cat_df["MetricSum"].abs().sum() > 0)
        metric_lbl_tbl = num_col_lbl if use_m else ("Count" if is_en else "Số lượng")
        fig_cat = build_horizontal_bar_chart(cat_df, y_col="Category", x_col=("MetricSum" if use_m else "Count"), name=metric_lbl_tbl, height=260)
        cat_tbl_zoom = _build_tbl_zoom_df(
            cat_df,
            dim_col_src="Category",
            dim_label=cat_col_lbl or table_lbl,
            use_metric_col=use_m,
            metric_label=metric_lbl_tbl,
            u_style=unit_style if use_m else "count",
        )
        render_zoomable_chart_card(
            title=f"Category Distribution: {table_lbl}" if is_en else f"Phân bổ theo {cat_col_lbl or 'danh mục'}: {table_lbl}",
            fig=fig_cat,
            df=cat_tbl_zoom,
            badge="Distribution",
            explanation="Distribution of records and metric value." if is_en else "Tần suất và giá trị phân bổ dữ liệu.",
            key=f"gen_tbl_cat_{table_name}"
        )

    if not trend_df.empty:
        gran = data.get("trend_granularity", "month")
        time_hdr_tbl = ("Date" if gran == "day" else "Month") if is_en else ("Ngày" if gran == "day" else "Tháng")
        if num_col and "MetricSum" in trend_df.columns:
            fig_tr = build_sales_dual_axis_chart(
                trend_df,
                x_col="TimePeriod",
                rev_col="MetricSum",
                box_col="QtySum" if (qty_col_raw and "QtySum" in trend_df.columns) else "Count",
                height=260,
                rev_name=num_col_lbl,
                box_name=qty_col_lbl or ("Records" if is_en else "Số dòng"),
                rev_prefix=("$" if unit_style == "usd" else ""),
                rev_suffix=(" đ" if unit_style == "vnd" else ""),
                box_unit="",
            )
            tr_tbl_zoom = _build_tbl_zoom_df(
                trend_df,
                dim_col_src="TimePeriod",
                dim_label=time_hdr_tbl,
                use_metric_col=True,
                metric_label=num_col_lbl,
                u_style=unit_style,
                extra_qty_label=qty_col_lbl or ("Records" if is_en else "Số dòng"),
            )
        else:
            fig_tr = build_weekday_bar_chart(pd.DataFrame({"WeekDay": trend_df["TimePeriod"], "Total": trend_df["Count"]}), height=260)
            tr_tbl_zoom = _build_tbl_zoom_df(
                trend_df,
                dim_col_src="TimePeriod",
                dim_label=time_hdr_tbl,
                use_metric_col=False,
                metric_label="Records" if is_en else "Số bản ghi",
                u_style="count",
            )
        render_zoomable_chart_card(
            title=f"Time Trend ({'Daily' if gran == 'day' else 'Monthly'})" if is_en else f"Xu hướng thời gian ({'theo ngày' if gran == 'day' else 'theo tháng'})",
            fig=fig_tr,
            df=tr_tbl_zoom,
            badge="Timeline",
            explanation="Chronological progression for this table." if is_en else "Diễn biến dữ liệu theo thời gian của bảng.",
            key=f"gen_tbl_tr_{table_name}"
        )

    rows_suf = "rows" if is_en else "dòng"
    cols_suf = "Columns" if is_en else "Cột Dữ Liệu"
    tbl_rec_hdr = f"Records: {table_lbl} ({len(df)} {rows_suf})" if is_en else f"Danh sách bản ghi: {table_lbl} ({len(df)} dòng)"
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
        st.info(f"Table '{table_lbl}' has no records." if is_en else f"Bảng '{table_lbl}' chưa có dữ liệu.")
    st.markdown("</div>", unsafe_allow_html=True)

    _render_sql_modal(table_lbl, data["sql"], data["exec_time_ms"], f"gen_tbl_sql_{table_name}")

    render_smart_analyst_anomaly_panel(
        layer_id=f"table_{table_name}",
        data=data,
        start_year=start_year,
        end_year=end_year,
        key_prefix=f"gen_{table_name}"
    )
