"""
Intelligent chart generation and auto-visualization using Plotly Express with heuristic column classification,
multi-series color grouping for line/area charts, multi-metric benchmark comparison (Employee vs Team),
full category display (no skipped months), and straight horizontal ticks.
"""

import re
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.config import MAX_BAR_CATEGORIES, INDIVIDUAL_ENTITY_REGEX
from src.analytics.heuristics import (
    get_axis_columns,
    get_row_identity_column,
    pick_label_column,
    is_id_like,
    unify_year_month_columns,
    ensure_full_twelve_months,
    ensure_full_four_quarters,
)

VI_COLUMN_MAP = {
    "departmentgroup": "Nhóm Phòng Ban",
    "department_group": "Nhóm Phòng Ban",
    "deptgroup": "Nhóm Phòng Ban",
    "dept_group": "Nhóm Phòng Ban",
    "headcount": "Quy Mô Nhân Sự",
    "yearsofservice": "Thâm Niên (Năm)",
    "years_of_service": "Thâm Niên (Năm)",
    "year_of_service": "Thâm Niên (Năm)",
    "yearsasmanager": "Thâm Niên Quản Lý (Năm)",
    "years_as_manager": "Thâm Niên Quản Lý (Năm)",
    "yearasmanager": "Thâm Niên Quản Lý (Năm)",
    "manageryears": "Thâm Niên Quản Lý (Năm)",
    "manager_years": "Thâm Niên Quản Lý (Năm)",
    "managertenure": "Thâm Niên Quản Lý (Năm)",
    "manager_tenure": "Thâm Niên Quản Lý (Năm)",
    "tenure": "Thâm Niên (Năm)",
    "experience": "Kinh Nghiệm (Năm)",
    "managername": "Tên Quản Lý",
    "manager_name": "Tên Quản Lý",
    "fullname": "Họ và Tên",
    "full_name": "Họ và Tên",
    "emp_name": "Họ và Tên",
    "employee_name": "Họ và Tên",
    "salary": "Mức Lương",
    "current_salary": "Mức Lương Hiện Tại",
    "currentsalary": "Mức Lương Hiện Tại",
    "avg_salary": "Lương Trung Bình",
    "avgsalary": "Lương Trung Bình",
    "averagesalary": "Lương Trung Bình",
    "department": "Phòng Ban",
    "dept_name": "Phòng Ban",
    "department_name": "Phòng Ban",
    "departmentname": "Phòng Ban",
    "title": "Chức Danh",
    "job_title": "Chức Danh",
    "gender": "Giới Tính",
    "hire_date": "Ngày Vào Làm",
    "birth_date": "Ngày Sinh",
    "age": "Tuổi",
    "totalsalarybudget": "Tổng Quỹ Lương ($)",
    "total_salary_budget": "Tổng Quỹ Lương ($)",
    "salarybudget": "Quỹ Lương ($)",
    "salary_budget": "Quỹ Lương ($)",
    "totalemployees": "Tổng Số Nhân Viên",
    "total_employees": "Tổng Số Nhân Viên",
    "maleemployees": "Nhân Viên Nam",
    "male_employees": "Nhân Viên Nam",
    "femaleemployees": "Nhân Viên Nữ",
    "female_employees": "Nhân Viên Nữ",
    "malemanagers": "Quản Lý Nam",
    "femalemanagers": "Quản Lý Nữ",
    "totalmanagers": "Tổng Số Quản Lý",
    "maleavgsalary": "Lương TB Nam ($)",
    "femaleavgsalary": "Lương TB Nữ ($)",
    "male_avg_salary": "Lương TB Nam ($)",
    "female_avg_salary": "Lương TB Nữ ($)",
    "malesalary": "Lương Nam ($)",
    "femalesalary": "Lương Nữ ($)",
    "male_salary": "Lương Nam ($)",
    "female_salary": "Lương Nữ ($)",
    "malepct": "Tỷ Lệ Nam (%)",
    "femalepct": "Tỷ Lệ Nữ (%)",
    "year": "Năm",
    "hireyear": "Năm Tuyển Dụng",
    "headcount": "Số Lượng Nhân Viên",
    "emp_count": "Số Lượng Nhân Viên",
    "count": "Số Lượng",
    "startdate": "Ngày Bắt Đầu",
    "start_date": "Ngày Bắt Đầu",
    "enddate": "Ngày Kết Thúc",
    "end_date": "Ngày Kết Thúc",
    "empno": "Mã NV",
    "emp_no": "Mã NV",
    # Chocolates & Sales Domain Mappings
    "country": "Quốc Gia",
    "geo": "Quốc Gia",
    "region": "Khu Vực",
    "totalsales": "Tổng Doanh Thu ($)",
    "total_sales": "Tổng Doanh Thu ($)",
    "amount": "Doanh Thu ($)",
    "sales": "Doanh Thu ($)",
    "boxes": "Số Thùng",
    "totalboxes": "Tổng Số Thùng",
    "total_boxes": "Tổng Số Thùng",
    "totalboxessold": "Tổng Số Hộp Bán Ra",
    "total_boxes_sold": "Tổng Số Hộp Bán Ra",
    "boxessold": "Số Hộp Bán Ra",
    "boxes_sold": "Số Hộp Bán Ra",
    "customers": "Khách Hàng",
    "totalcustomers": "Tổng Số Khách Hàng",
    "total_customers": "Tổng Số Khách Hàng",
    "product": "Sản Phẩm",
    "product_name": "Tên Sản Phẩm",
    "category": "Danh Mục",
    "size": "Kích Cỡ",
    "cost_per_box": "Giá Vốn/Thùng ($)",
    "costperbox": "Giá Vốn/Thùng ($)",
    "profitmargin": "Tỷ Suất Lợi Nhuận (%)",
    "profit_margin": "Tỷ Suất Lợi Nhuận (%)",
    "profitperbox": "Lợi Nhuận/Hộp ($)",
    "profit_per_box": "Lợi Nhuận/Hộp ($)",
    "revenueperbox": "Doanh Thu/Hộp ($)",
    "revenue_per_box": "Doanh Thu/Hộp ($)",
    "avgordervalue": "Giá Trị Đơn Trung Bình ($)",
    "avg_order_value": "Giá Trị Đơn Trung Bình ($)",
    "avgboxesperorder": "Số Hộp TB/Đơn",
    "avg_boxes_per_order": "Số Hộp TB/Đơn",
    "salesperson": "Nhân Viên Kinh Doanh",
    "team": "Đội Ngũ",
    "location": "Vị Trí/Khu Vực",
    "soluongnhanvien": "Số Lượng Nhân Viên",
    "slngnhnvin": "Số Lượng Nhân Viên",
    "soluongnhansu": "Số Lượng Nhân Sự",
    "quymonhansu": "Quy Mô Nhân Sự",
    "headcount": "Số Lượng Nhân Sự",
    "totalemployees": "Tổng Số Nhân Viên",
    "total_employees": "Tổng Số Nhân Viên",
    "saledate": "Ngày Bán",
    "sale_date": "Ngày Bán",
    "date": "Ngày",
    "month": "Tháng",
    "quarter": "Quý",
    "quarteryear": "Quý",
    "quy": "Quý",
}


def format_col_title(col_name: str) -> str:
    """Chuyển đổi tên cột kỹ thuật (e.g. YearsOfService, FullName) sang tên tiếng Việt dễ hiểu cho người dùng."""
    if not col_name:
        return ""
    col_str = str(col_name).strip()
    # Nếu tên cột đã có dấu tiếng Việt chuẩn xác (e.g. 'Số Lượng Nhân Viên', 'Đội Ngũ') -> giữ nguyên
    if any(c in col_str for c in "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựíìỉĩịđýỳỷỹỵÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÍÌỈĨỊĐÝỲỶỸỴ"):
        return col_str
    norm = re.sub(r"[^a-zA-Z0-9]", "", col_str).lower()
    if norm in VI_COLUMN_MAP:
        return VI_COLUMN_MAP[norm]
    # Fallback to readable title case
    clean = re.sub(r"([a-z])([A-Z])", r"\1 \2", col_str).replace("_", " ").strip().title()
    return clean


def render_smart_chart(df: pd.DataFrame, chart_override: str, turn_id: str, user_query: str = ""):
    """Tự động phân loại cột và render biểu đồ phù hợp nhất:
    - Line/Area: Nếu có cột thời gian -> biểu đồ xu hướng theo thời gian, hiển thị đầy đủ 100% các tháng với số nằm ngang thẳng.
    - Bar:
        + Nếu có 1 dòng và nhiều chỉ số đo lường (VD: Nhân viên vs Toàn đội) -> Biểu đồ so sánh Benchmark trực quan.
        + Nếu có nhiều dòng và nhiều chỉ số đo lường -> Biểu đồ cột nhóm (Grouped Bar Chart).
        + Nếu có cột nhãn và cột đo lường -> Biểu đồ cột so sánh.
    - Scatter: Nếu có >= 2 cột số đo lường -> biểu đồ phân tán tương quan.
    """
    if df is None or df.empty:
        st.info("Không có dữ liệu để vẽ biểu đồ.")
        return None

    df = ensure_full_twelve_months(df, user_query)
    df = ensure_full_four_quarters(df, user_query)
    df = unify_year_month_columns(df)

    measure_cols, label_cols, time_col = get_axis_columns(df)
    row_identity_col = get_row_identity_column(df)

    try:
        n_time = df[time_col].nunique(dropna=True) if (time_col and time_col in df.columns) else 0

        if chart_override == "Tự động":
            # 1. Nếu mỗi dòng là một cá nhân/thực thể độc lập (có row_identity_col hoặc có tên người first_name/last_name/FullName, Salesperson, Employee, Manager)
            # -> ĐÂY LÀ BẢNG XẾP HẠNG/SO SÁNH CÁ NHÂN, BẮT BUỘC dùng Bar Chart để so sánh giữa các cá nhân, TUYỆT ĐỐI KHÔNG DÙNG Line Chart!
            lbl_low = [str(c).lower() for c in label_cols]
            has_person_names = (
                ("first_name" in lbl_low and "last_name" in lbl_low)
                or any(k in lbl_low for k in ["fullname", "full_name", "họ và tên", "ho_va_ten", "ten_nhan_vien"])
            )
            is_individual_entity = (
                row_identity_col is not None
                or any(INDIVIDUAL_ENTITY_REGEX.search(str(c)) for c in label_cols)
                or has_person_names
            )

            # 2. Nếu có cột tỷ lệ/phần trăm/cơ cấu và số lượng danh mục từ 2 đến 10
            # CHÚ Ý: CHỈ chọn Pie khi có ĐÚNG 1 cột đo lường phân rã thành phần.
            # Nếu có từ 2 cột tỷ lệ/số đo trở lên (ví dụ: MalePct & FemalePct, hoặc MaleManagers & FemaleManagers),
            # BẮT BUỘC dùng Bar Chart (Grouped Bar Chart) để so sánh song song giữa các nhóm!
            pct_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["percent", "percentage", "pct", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "phan_tram", "share", "ratio"])]
            has_single_pct_col = len(pct_cols) == 1
            uq_low = (user_query or "").lower()
            user_asked_pct = any(k in uq_low for k in [
                "tỷ lệ", "tỉ lệ", "phần trăm", "percent", "percentage", "pct", "%", 
                "share", "cơ cấu", "tỉ trọng", "tỷ trọng", "đóng góp"
            ])
            is_distribution_breakdown = (
                (has_single_pct_col or user_asked_pct)
                and (2 <= len(df) <= 10)
                and (len(pct_cols) <= 1)
                and (not time_col or n_time <= 1)
            )

            if is_distribution_breakdown:
                chosen = "Pie"
            elif time_col and measure_cols and n_time > 1:
                chosen = "Line"
            elif is_individual_entity and measure_cols:
                uq_low = (user_query or "").lower()
                is_top_ranking = any(k in uq_low for k in ["top", "cao nhất", "thấp nhất", "lâu nhất", "xếp hạng", "danh sách"])
                if is_top_ranking and len(df) <= 15 and len(measure_cols) == 1:
                    chosen = "Bar Ngang"
                else:
                    chosen = "Bar"
            elif len(df) == 1 and measure_cols and any(k in str(measure_cols[0]).lower() for k in ["percent", "ratio", "rate", "tỷ lệ", "phan_tram", "%"]):
                chosen = "Pie"
            elif measure_cols:
                chosen = "Bar"
            elif len(measure_cols) >= 2:
                chosen = "Scatter"
            else:
                st.info("Không tìm thấy dạng biểu đồ phù hợp — dữ liệu không có chỉ số đo lường số học rõ ràng (các cột số hiện có đều là mã định danh).")
                return None
        else:
            chosen = chart_override

        # Fallback nếu chọn Line/Area nhưng không có cột thời gian hoặc chỉ có 1 mốc thời gian
        if chosen in ("Line", "Area") and (not time_col or n_time <= 1):
            if measure_cols:
                if n_time == 1 and chart_override in ("Line", "Area"):
                    st.caption("ℹ️ Dữ liệu chỉ có 1 mốc thời gian duy nhất — tự động hiển thị dưới dạng Bar Chart để hiển thị rõ số liệu.")
                elif not time_col:
                    st.warning(
                        "⚠️ Biểu đồ Line/Area cần một cột thời gian hợp lệ, dữ liệu hiện tại không có. "
                        "Tự động chuyển sang Bar Chart để đảm bảo đúng ý nghĩa thống kê."
                    )
                chosen = "Bar"
            else:
                st.info("Không có cột thời gian hợp lệ và không đủ dữ liệu để vẽ Bar/Scatter thay thế.")
                return None

        # Xác định cột phân nhóm màu sắc cho Line/Area (ví dụ: phân loại theo Region, Product...)
        # CHÚ Ý QUAN TRỌNG: time_color_col TUYỆT ĐỐI KHÔNG ĐƯỢC TRÙNG VỚI time_col
        time_color_col = None
        if chosen in ("Line", "Area") and len(measure_cols) == 1 and label_cols:
            other_labels = [c for c in label_cols if c != time_col]
            if other_labels:
                candidate_col, candidate_series, _ = pick_label_column(df, other_labels)
                if candidate_col and candidate_col != time_col:
                    if candidate_col not in df.columns and candidate_series is not None:
                        df = df.copy()
                        df[candidate_col] = candidate_series.values
                    if candidate_col in df.columns and 1 < df[candidate_col].nunique(dropna=True) <= 20:
                        time_color_col = candidate_col

        if chosen == "Line" and time_col and measure_cols:
            sorted_df = df.sort_values(time_col)
            n_time_points = sorted_df[time_col].nunique(dropna=True)
            tick_angle = 0 if n_time_points <= 20 else -45

            if time_color_col:
                clean_m = format_col_title(measure_cols[0])
                clean_time = format_col_title(time_col)
                clean_group = format_col_title(time_color_col)
                fig = px.line(
                    sorted_df,
                    x=time_col,
                    y=measure_cols[0],
                    color=time_color_col,
                    markers=True,
                    title=f"Xu hướng {clean_m} theo {clean_time} (Phân loại theo {clean_group})",
                    template="plotly_white"
                )
                m_low = str(measure_cols[0]).lower()
                is_curr = any(k in m_low for k in ["sales", "amount", "salary", "budget", "revenue", "lương", "doanh"])
                curr_sym = "$" if is_curr else ""
                fig.update_traces(
                    line=dict(width=2.5),
                    marker=dict(size=7),
                    hovertemplate=f"<b>%{{fullData.name}}</b><br>{clean_time}: %{{x}}<br>{clean_m}: {curr_sym}%{{y:,.0f}}<extra></extra>"
                )
            else:
                clean_m = format_col_title(measure_cols[0])
                clean_time = format_col_title(time_col)
                min_t = str(sorted_df[time_col].min())
                max_t = str(sorted_df[time_col].max())
                time_range_str = f" ({min_t} – {max_t})" if min_t != max_t else ""
                chart_title = f"Xu hướng {clean_m} qua từng {clean_time}{time_range_str}" if len(measure_cols) == 1 else f"Xu hướng qua từng {clean_time}{time_range_str}"

                fig = px.line(
                    sorted_df,
                    x=time_col,
                    y=measure_cols if len(measure_cols) > 1 else measure_cols[0],
                    markers=True,
                    title=chart_title,
                    template="plotly_white"
                )

                trace_kwargs = dict(
                    line=dict(width=3, color="#1F4E78"),
                    marker=dict(size=8, color="#1F4E78")
                )

                # Tính toán % tăng trưởng YoY (Year-over-Year) và Hover text chuyên sâu nếu là chuỗi thời gian 1 chỉ số
                if len(measure_cols) == 1 and pd.api.types.is_numeric_dtype(sorted_df[measure_cols[0]]):
                    m_c = measure_cols[0]
                    yoy_series = sorted_df[m_c].pct_change() * 100.0
                    m_low = str(m_c).lower()
                    is_curr = any(k in m_low for k in ["salary", "budget", "lương", "quỹ", "tiền", "sales", "amount", "revenue", "doanh", "cost", "profit", "$"])
                    is_monthly = any(k in str(time_col).lower() for k in ["month", "tháng"]) or any(re.match(r"^\d{4}-\d{2}$", str(x)) for x in sorted_df[time_col].dropna().head(3))
                    growth_label = "MoM" if is_monthly else "YoY"
                    hover_texts = []
                    for idx, (_, row) in enumerate(sorted_df.iterrows()):
                        val = float(row[m_c])
                        yoy_val = yoy_series.iloc[idx]
                        yoy_str = f" ({yoy_val:+.1f}% {growth_label})" if pd.notna(yoy_val) else " (Khởi đầu)"
                        if is_curr:
                            if abs(val) >= 1_000_000_000:
                                fmt_compact = f"${val / 1e9:,.2f} Tỷ"
                            elif abs(val) >= 1_000_000:
                                fmt_compact = f"${val / 1e6:,.2f} Tr"
                            else:
                                fmt_compact = f"${val:,.0f}"
                            val_detail = f" (${val:,.0f})" if abs(val) >= 1_000_000 else ""
                        else:
                            fmt_compact = f"{val:,.0f}"
                            val_detail = ""
                        hover_texts.append(f"<b>{clean_time} {row[time_col]}</b><br>{clean_m}: {fmt_compact}{val_detail}{yoy_str}")

                    trace_kwargs["text"] = hover_texts
                    trace_kwargs["hovertemplate"] = "%{text}<extra></extra>"

                fig.update_traces(**trace_kwargs)
            fig.update_layout(
                xaxis=dict(
                    type="category" if n_time_points <= 36 else None,
                    tickangle=tick_angle,
                    automargin=True
                ),
                margin=dict(l=20, r=20, t=50, b=50)
            )

        elif chosen == "Area" and time_col and measure_cols:
            sorted_df = df.sort_values(time_col)
            n_time_points = sorted_df[time_col].nunique(dropna=True)
            tick_angle = 0 if n_time_points <= 20 else -45

            if time_color_col:
                fig = px.area(
                    sorted_df,
                    x=time_col,
                    y=measure_cols[0],
                    color=time_color_col,
                    title=f"Xu hướng (Area) {measure_cols[0]} theo {time_col} (Phân nhóm theo {time_color_col})",
                    template="plotly_white"
                )
            else:
                fig = px.area(
                    sorted_df,
                    x=time_col,
                    y=measure_cols if len(measure_cols) > 1 else measure_cols[0],
                    title=f"Xu hướng (Area) theo {time_col}",
                    template="plotly_white"
                )
            fig.update_layout(
                xaxis=dict(
                    type="category" if n_time_points <= 36 else None,
                    tickangle=tick_angle,
                    automargin=True
                ),
                margin=dict(l=20, r=20, t=50, b=50)
            )

        elif chosen == "Bar" and measure_cols:
            # 1. Trường hợp đặc biệt: 1 dòng so sánh nhiều chỉ số (VD: Cá nhân vs Toàn đội / Benchmark)
            if len(df) == 1 and len(measure_cols) >= 2:
                person_name = None
                if label_cols:
                    for c in label_cols:
                        if any(k in c.lower() for k in ["salesperson", "nhân viên", "employee", "people", "name", "tên"]):
                            person_name = str(df[c].iloc[0])
                            break

                comp_labels = []
                comp_values = []
                for m in measure_cols:
                    try:
                        val_num = float(df[m].iloc[0])
                    except Exception:
                        val_num = 0.0

                    m_low = m.lower()
                    if any(k in m_low for k in ["team", "đội", "total", "toàn", "all"]):
                        comp_labels.append(f"Toàn đội ({m})")
                    elif person_name and any(k in m_low for k in ["sold", "amount", "boxes", "sales", "qty", "hộp", "tiền"]):
                        comp_labels.append(f"{person_name} ({m})")
                    else:
                        comp_labels.append(m)
                    comp_values.append(val_num)

                comp_df = pd.DataFrame({
                    "Chỉ số So sánh": comp_labels,
                    "Giá trị": comp_values
                })

                fig = px.bar(
                    comp_df,
                    x="Chỉ số So sánh",
                    y="Giá trị",
                    color="Chỉ số So sánh",
                    text="Giá trị",
                    title="📊 Biểu đồ So sánh Chỉ số: " + (" vs ".join(comp_labels)),
                    template="plotly_white"
                )
                fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                fig.update_layout(
                    xaxis=dict(type="category", tickangle=0, automargin=True),
                    margin=dict(l=20, r=20, t=50, b=50),
                    showlegend=False
                )

            elif label_cols or time_col:
                effective_label_cols = label_cols if label_cols else ([time_col] if time_col else [])
                label_name, label_series, consumed_cols = pick_label_column(df, effective_label_cols)
                if label_name is None:
                    st.info("Không tìm thấy cột phù hợp để làm nhãn trục X.")
                    return None

                plot_df = df.copy()
                plot_df[label_name] = label_series.values

                n_unique_labels = plot_df[label_name].nunique(dropna=True)
                total_rows = len(plot_df)

                color_col = None
                candidate_color_cols = [
                    c for c in label_cols
                    if c not in consumed_cols and c in plot_df.columns and not is_id_like(c)
                ]
                if candidate_color_cols:
                    cand = candidate_color_cols[0]
                    if plot_df[cand].nunique(dropna=True) <= 20:
                        color_col = cand

                # Nếu có cột phân nhóm (DepartmentGroup) và người dùng hỏi so sánh một chỉ số cụ thể (VD: Lương),
                # ưu tiên vẽ chỉ số đó phân nhóm theo color_col thay vì vẽ gộp nhiều chỉ số khác thang đo
                if color_col and len(measure_cols) >= 2:
                    uq_low = (user_query or "").lower()
                    user_asked_salary = any(k in uq_low for k in ["lương", "salary", "thu nhập"])
                    user_asked_headcount = any(k in uq_low for k in ["quy mô", "headcount", "số lượng nhân sự", "số nhân sự", "số lượng nhân viên"])
                    if user_asked_salary and not user_asked_headcount:
                        sal_cols = [c for c in measure_cols if any(k in c.lower() for k in ["salary", "lương", "thu nhập"])]
                        if sal_cols:
                            measure_cols = [sal_cols[0]]
                    elif user_asked_headcount and not user_asked_salary:
                        hc_cols = [c for c in measure_cols if any(k in c.lower() for k in ["headcount", "nhân sự", "nhân viên", "quy mô"])]
                        if hc_cols:
                            measure_cols = [hc_cols[0]]

                # Phát hiện dữ liệu thô chưa GROUP BY cần tổng hợp (chỉ khi không có cột phân nhóm màu)
                needs_aggregation = (
                    color_col is None
                    and row_identity_col is None
                    and n_unique_labels < total_rows
                    and (total_rows / max(1, n_unique_labels)) >= 2.0
                )

                if needs_aggregation:
                    grouped_df = plot_df.groupby(label_name, as_index=False)[measure_cols[0]].sum()
                    grouped_df = grouped_df.sort_values(measure_cols[0], ascending=False)
                    st.caption(
                        f"ℹ️ Dữ liệu thô gồm {total_rows:,} dòng có `{n_unique_labels}` giá trị `{label_name}` lặp lại "
                        f"— đã tự động tính tổng `{measure_cols[0]}` theo từng `{label_name}` để biểu đồ trực quan, chính xác."
                    )
                    plot_df = grouped_df
                    total_rows = len(plot_df)

                    if total_rows > 30:
                        max_display = st.slider(
                            f"Số lượng đối tượng hiển thị trên biểu đồ (Tổng: {total_rows:,})",
                            min_value=min(10, total_rows),
                            max_value=total_rows,
                            value=min(total_rows, MAX_BAR_CATEGORIES),
                            step=5 if total_rows <= 100 else 10,
                            key=f"bar_limit_{turn_id}"
                        )
                        plot_df = plot_df.head(max_display)

                    tick_angle = 0 if len(plot_df) <= 10 else -45
                    fig = px.bar(
                        plot_df, x=label_name, y=measure_cols[0],
                        title=f"{format_col_title(measure_cols[0])} theo {format_col_title(label_name)}",
                        template="plotly_white"
                    )
                    fig.update_layout(
                        xaxis=dict(type="category", tickangle=tick_angle, automargin=True),
                        margin=dict(l=20, r=20, t=50, b=80 if tick_angle != 0 else 50)
                    )

                elif len(measure_cols) >= 2:
                    # Lọc các chỉ số có cùng thang đo (tránh vẽ lẫn lộn số lượng 1,2 và phần trăm 100% trên cùng 1 trục)
                    pct_cols = [c for c in measure_cols if any(k in c.lower() for k in ["pct", "percent", "rate", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "phần trăm", "%"])]
                    non_total_cols = [c for c in measure_cols if not any(k in c.lower() for k in ["total", "tổng", "count_all", "all"])]
                    non_pct_cols = [c for c in measure_cols if c not in pct_cols]

                    # Kiểm tra xem người dùng có thực sự yêu cầu vẽ tỷ lệ/phần trăm, số lượng, hay hiệu quả kinh doanh không
                    uq_low = (user_query or "").lower()
                    user_asked_pct = any(k in uq_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "percent", "pct", "%", "share", "cơ cấu", "tỉ trọng", "tỷ trọng", "đóng góp"])
                    user_asked_count = any(k in uq_low for k in ["số lượng", "quy mô", "bao nhiêu", "count", "headcount", "nhân viên"])
                    user_asked_efficiency = any(k in uq_low for k in [
                        "hiệu quả", "efficiency", "effectiveness", "năng suất", 
                        "giá trị trung bình", "trung bình mỗi đơn", "trung bình mỗi hộp", 
                        "order value", "per box", "per order", "aov", "performance", "profit per box",
                        "lợi nhuận", "profit", "margin", "tỷ suất", "tỉ suất", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"
                    ])

                    # Tìm các cột đo lường hiệu quả (Efficiency / Average / Margin / Profit) - LOẠI TRỪ các cột chi phí/giá vốn đơn thuần (Cost_per_box)
                    eff_cols = [c for c in measure_cols if (any(k in c.lower() for k in [
                        "avg", "ordervalue", "order_value", "profit", "margin", "lợi nhuận", "trung bình", "hiệu quả", "revenueperbox", "revenue_per_box"
                    ]) or any(k in c.lower() for k in ["perbox", "per_box"])) and not any(k in c.lower() for k in ["cost", "giá vốn", "gia_von"])]

                    # Tìm các cặp số lượng nhân sự Nam - Nữ tuyệt đối
                    male_emp_cols = [c for c in non_pct_cols if any(k in c.lower() for k in ["maleemployees", "male_emp", "malemanagers", "male", "nam"]) and not any(k in c.lower() for k in ["female", "nu", "nữ", "department"])]
                    female_emp_cols = [c for c in non_pct_cols if any(k in c.lower() for k in ["femaleemployees", "female_emp", "femalemanagers", "female", "nu", "nữ"])]

                    # Nếu người dùng hỏi CẢ Số lượng VÀ Tỷ lệ, hoặc có cặp số lượng Nam/Nữ thực tế:
                    if user_asked_count and male_emp_cols and female_emp_cols:
                        active_measures = [male_emp_cols[0], female_emp_cols[0]]
                        chart_title = f"Quy mô & Cơ cấu Nhân sự theo {label_name} (Stacked Bar)"
                    elif user_asked_efficiency and eff_cols:
                        # Kiểm tra xem có sự xung đột đơn vị (% và $) giữa các cột hiệu quả không
                        has_pct_eff = [c for c in eff_cols if any(k in c.lower() for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ", "%"])]
                        has_non_pct_eff = [c for c in eff_cols if c not in has_pct_eff]
                        
                        is_margin_focus = any(k in uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%"])
                        is_box_focus = any(k in uq_low for k in ["mỗi hộp", "per box", "hộp", "thùng"]) and not is_margin_focus
                        
                        if has_pct_eff and has_non_pct_eff:
                            # Biểu đồ 2 trục Y (Dual Axis Combo Chart): Bar cho % và Line cho $
                            pct_col = has_pct_eff[0]
                            non_pct_col = has_non_pct_eff[0]

                            if total_rows > 30:
                                max_display = st.slider(
                                    f"Số lượng đối tượng hiển thị trên biểu đồ (Tổng: {total_rows:,})",
                                    min_value=min(10, total_rows),
                                    max_value=total_rows,
                                    value=min(total_rows, MAX_BAR_CATEGORIES),
                                    step=5 if total_rows <= 100 else 10,
                                    key=f"bar_limit_{turn_id}"
                                )
                                plot_df = plot_df.head(max_display)

                            max_label_len = max((len(str(v)) for v in plot_df[label_name]), default=0)
                            tick_angle = -35 if (max_label_len > 8 or len(plot_df) > 8) else 0

                            fig = make_subplots(specs=[[{"secondary_y": True}]])
                            fig.add_trace(
                                go.Bar(
                                    x=plot_df[label_name],
                                    y=plot_df[pct_col],
                                    name=format_col_title(pct_col),
                                    marker_color="#1E40AF",
                                    text=plot_df[pct_col],
                                    texttemplate="%{text:,.2f}%",
                                    textposition="outside",
                                ),
                                secondary_y=False,
                            )
                            fig.add_trace(
                                go.Scatter(
                                    x=plot_df[label_name],
                                    y=plot_df[non_pct_col],
                                    name=format_col_title(non_pct_col),
                                    mode="lines+markers+text",
                                    marker=dict(size=8, color="#D97706"),
                                    line=dict(width=3, color="#D97706"),
                                    text=plot_df[non_pct_col],
                                    texttemplate="$%{text:,.2f}",
                                    textposition="top center",
                                ),
                                secondary_y=True,
                            )
                            try:
                                max_pct = float(pd.to_numeric(plot_df[pct_col], errors="coerce").max() or 100)
                            except Exception:
                                max_pct = 100.0
                            try:
                                max_non_pct = float(pd.to_numeric(plot_df[non_pct_col], errors="coerce").max() or 10)
                            except Exception:
                                max_non_pct = 10.0

                            fig.update_layout(
                                title=f"Biểu đồ Kết Hợp (Dual Axis): {format_col_title(pct_col)} & {format_col_title(non_pct_col)} theo {format_col_title(label_name)}",
                                template="plotly_white",
                                xaxis=dict(type="category", tickangle=tick_angle, automargin=True, title=format_col_title(label_name)),
                                yaxis=dict(title=format_col_title(pct_col), ticksuffix="%", range=[0, max(100.0, max_pct * 1.25)]),
                                yaxis2=dict(title=format_col_title(non_pct_col), tickprefix="$", range=[0, max_non_pct * 1.3], showgrid=False),
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                                margin=dict(l=40, r=40, t=60, b=90 if tick_angle != 0 else 50)
                            )
                            st.plotly_chart(fig, use_container_width=True)
                            return fig
                        elif is_margin_focus and has_pct_eff:
                            active_measures = [has_pct_eff[0]]
                            chart_title = f"{format_col_title(has_pct_eff[0])} theo {format_col_title(label_name)}"
                        elif is_box_focus and has_non_pct_eff:
                            active_measures = [has_non_pct_eff[0]]
                            chart_title = f"{format_col_title(has_non_pct_eff[0])} theo {format_col_title(label_name)}"
                        else:
                            active_measures = eff_cols
                            chart_title = f"So sánh Hiệu quả ({', '.join([format_col_title(c) for c in eff_cols])}) theo {format_col_title(label_name)}"
                    elif pct_cols and (user_asked_pct or not non_pct_cols):
                        active_measures = pct_cols
                        chart_title = f"Tỷ lệ phần trăm ({', '.join(pct_cols)}) theo {label_name}"
                    elif non_pct_cols:
                        # Ưu tiên các cột giá trị thực tế (lương thực, quy mô...) thay vì phần trăm ảo
                        clean_non_pct = [c for c in non_pct_cols if not any(k in c.lower() for k in ["total", "tổng", "count_all", "all"])] or non_pct_cols
                        if len(clean_non_pct) >= 2:
                            active_measures = clean_non_pct
                            chart_title = f"So sánh ({', '.join(clean_non_pct)}) theo {label_name}"
                        else:
                            active_measures = clean_non_pct
                            chart_title = f"{clean_non_pct[0]} theo {label_name}"
                    elif pct_cols:
                        active_measures = pct_cols
                        chart_title = f"Tỷ lệ phần trăm ({', '.join(pct_cols)}) theo {label_name}"
                    else:
                        active_measures = measure_cols
                        chart_title = f"So sánh các chỉ số ({', '.join(measure_cols)}) theo {label_name}"

                    # Kiểm tra độ tương thích về thang đo (tránh vẽ lương 150,000 chung trục với số lần 18)
                    if len(active_measures) >= 2:
                        numeric_ms = [m for m in active_measures if pd.api.types.is_numeric_dtype(plot_df[m])]
                        max_vals = [float(plot_df[m].abs().max()) for m in numeric_ms if float(plot_df[m].abs().max()) > 0]
                        if len(max_vals) >= 2 and (max(max_vals) / min(max_vals)) > 20:
                            if user_asked_efficiency and any(c in numeric_ms for c in eff_cols):
                                # Khi hỏi hiệu quả, ưu tiên chọn chỉ số hiệu quả (AvgOrderValue, ProfitMargin, ProfitPerBox...) thay vì rơi về TotalSales
                                candidate_effs = [c for c in eff_cols if c in numeric_ms]
                                if any(k in uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%"]) and any(any(k in c.lower() for k in ["margin", "tỷ suất", "tỉ suất"]) for c in candidate_effs):
                                    primary_m = [c for c in candidate_effs if any(k in c.lower() for k in ["margin", "tỷ suất", "tỉ suất"])][0]
                                elif any(k in uq_low for k in ["mỗi hộp", "per box", "hộp"]) and any(any(k in c.lower() for k in ["perbox", "per_box"]) for c in candidate_effs):
                                    primary_m = [c for c in candidate_effs if any(k in c.lower() for k in ["perbox", "per_box"])][0]
                                else:
                                    primary_m = candidate_effs[0]
                                active_measures = [primary_m]
                                chart_title = f"So sánh Hiệu quả ({format_col_title(primary_m)}) theo {format_col_title(label_name)}"
                            else:
                                # Chênh lệch trên 20 lần: Ưu tiên cột có độ lệch chuẩn và giá trị lớn nhất (ví dụ CurrentSalary)
                                primary_m = max(numeric_ms, key=lambda m: (float(plot_df[m].std() or 0), float(plot_df[m].max() or 0)))
                                active_measures = [primary_m]
                                chart_title = f"{primary_m} theo {label_name}"


                    if total_rows > 30:
                        max_display = st.slider(
                            f"Số lượng đối tượng hiển thị trên biểu đồ (Tổng kết quả: {total_rows:,} dòng)",
                            min_value=min(10, total_rows),
                            max_value=total_rows,
                            value=min(total_rows, MAX_BAR_CATEGORIES),
                            step=5 if total_rows <= 100 else 10,
                            key=f"bar_limit_{turn_id}"
                        )
                        plot_df = plot_df.head(max_display)

                    category_order = list(dict.fromkeys(plot_df[label_name].tolist()))

                    # Kiểm tra xem có phải bài toán Tỷ lệ thành phần / Cơ cấu 100% không
                    is_composition_100 = False
                    pct_cols_active = [c for c in active_measures if any(k in c.lower() for k in ["pct", "percent", "rate", "tỷ lệ", "%"])]
                    if len(pct_cols_active) >= 2:
                        try:
                            row_sums = plot_df[pct_cols_active].sum(axis=1)
                            if not row_sums.empty and abs(row_sums.mean() - 100.0) < 5.0:
                                is_composition_100 = True
                        except Exception:
                            pass
                    if not is_composition_100 and any("malepct" in c.lower() for c in active_measures) and any("femalepct" in c.lower() for c in active_measures):
                        is_composition_100 = True

                    # Tùy chỉnh màu sắc chuyên nghiệp cho các phân loại đặc thù (như Giới tính Nam / Nữ)
                    color_map = {}
                    for col in active_measures:
                        cl = col.lower()
                        if any(k in cl for k in ["female", "nu", "nữ", "women"]):
                            color_map[col] = "#EC4899"  # Hồng/Cam san hô hiện đại cho Nữ
                        elif any(k in cl for k in ["male", "nam", "men"]):
                            color_map[col] = "#2563EB"  # Xanh dương hiện đại cho Nam

                    is_salary_measure = any(
                        any(k in c.lower() for k in ["salary", "lương", "luong", "pay", "income", "wage", "thu nhập", "budget", "quỹ", "cost", "tiền"])
                        for c in active_measures
                    ) or any(k in (user_query or "").lower() for k in ["lương", "salary", "thu nhập", "income", "pay"])

                    is_gender_salary_comp = (
                        len(active_measures) == 2 and
                        is_salary_measure and
                        any(any(k in c.lower() for k in ["female", "nu", "nữ"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["male", "nam"]) for c in active_measures)
                    )

                    is_headcount_salary_comp = (
                        len(active_measures) == 2 and
                        any(any(k in c.lower() for k in ["headcount", "totalemployees", "số lượng nhân sự", "nhân sự", "nhân viên", "employee"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["salary", "lương", "thu nhập"]) for c in active_measures)
                    )

                    is_headcount_stack = (
                        len(active_measures) == 2 and
                        not is_salary_measure and
                        any(any(k in c.lower() for k in ["female", "nu", "nữ"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["male", "nam"]) for c in active_measures) and
                        not any(any(k in c.lower() for k in ["pct", "percent", "rate", "%"]) for c in active_measures)
                    )

                    barmode_val = "stack" if (is_composition_100 or is_headcount_stack) else "group"
                    if is_composition_100:
                        chart_title = f"Cơ cấu Tỷ lệ Phần trăm ({', '.join(active_measures)}) theo {format_col_title(label_name)} (100% Stacked Bar)"
                    elif is_headcount_stack:
                        chart_title = f"Quy mô & Cơ cấu Giới tính theo {format_col_title(label_name)} (Stacked Bar)"
                    elif is_gender_salary_comp:
                        chart_title = f"So Sánh Mức Lương Trung Bình Nam vs Nữ theo {format_col_title(label_name)} (Grouped Bar)"
                    elif is_headcount_salary_comp:
                        chart_title = f"So Sánh Quy Mô Nhân Sự & Mức Lương Trung Bình theo {format_col_title(label_name)} (Grouped Bar)"

                    # Tự động tính góc nghiêng nhãn trục X nếu nhãn dài để không bao giờ bị cắt chữ
                    max_lbl_len = max([len(str(x)) for x in plot_df[label_name]] or [0])
                    if len(plot_df) <= 9 and max_lbl_len <= 18:
                        tick_angle = -25 if max_lbl_len > 12 else 0
                    elif max_lbl_len > 10:
                        tick_angle = -30 if len(plot_df) <= 10 else -45
                    else:
                        tick_angle = 0 if len(plot_df) <= 8 else -45

                    bar_kwargs = {
                        "data_frame": plot_df,
                        "x": label_name,
                        "y": active_measures,
                        "barmode": barmode_val,
                        "title": chart_title,
                        "category_orders": {label_name: category_order},
                        "template": "plotly_white",
                    }
                    if color_map and len(color_map) == len(active_measures):
                        bar_kwargs["color_discrete_map"] = color_map

                    fig = px.bar(**bar_kwargs)

                    if is_composition_100 or is_headcount_stack:
                        # Đổi tên hiển thị trên Legend cho thân thiện (kiểm tra Nữ trước Nam vì 'female' chứa 'male')
                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            if any(k in tr_l for k in ["female", "nu", "nữ", "women"]):
                                tr.name = "Nữ (Female %)" if is_composition_100 else "Nữ (Female)"
                            elif any(k in tr_l for k in ["male", "nam", "men"]):
                                tr.name = "Nam (Male %)" if is_composition_100 else "Nam (Male)"

                        # Hiển thị nhãn trực tiếp bên trong từng phân đoạn
                        txt_tmpl = "%{y:.0f}%" if is_composition_100 else "%{y:,.0f}"
                        fig.update_traces(texttemplate=txt_tmpl, textposition="inside", insidetextanchor="middle")
                        layout_kwargs = dict(
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        if is_composition_100:
                            layout_kwargs["yaxis"] = dict(range=[0, 100], ticksuffix="%", title="Tỷ lệ (%)")
                        else:
                            layout_kwargs["yaxis"] = dict(title="Số Lượng Nhân Sự")
                        fig.update_layout(**layout_kwargs)

                    elif is_gender_salary_comp:
                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            if any(k in tr_l for k in ["female", "nu", "nữ", "women"]):
                                tr.name = "Nữ (Female)"
                            elif any(k in tr_l for k in ["male", "nam", "men"]):
                                tr.name = "Nam (Male)"

                        fig.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
                        try:
                            max_val = float(plot_df[active_measures].max().max())
                        except Exception:
                            max_val = 100000.0
                        layout_kwargs = dict(
                            yaxis=dict(title="Mức Lương Trung Bình ($)", range=[0, max_val * 1.18]),
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        fig.update_layout(**layout_kwargs)

                    elif is_headcount_salary_comp:
                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            if any(k in tr_l for k in ["headcount", "nhân sự", "nhân viên", "employee", "totalemployees"]):
                                tr.name = "Quy Mô Nhân Sự (Người)"
                                tr.marker.color = "#2563EB"
                                tr.texttemplate = "%{y:,.0f} ng"
                                tr.textposition = "outside"
                            elif any(k in tr_l for k in ["salary", "lương", "thu nhập"]):
                                tr.name = "Lương Trung Bình ($)"
                                tr.marker.color = "#10B981"
                                tr.texttemplate = "$%{y:,.0f}"
                                tr.textposition = "outside"

                        try:
                            max_val = float(plot_df[active_measures].max().max())
                        except Exception:
                            max_val = 100000.0
                        layout_kwargs = dict(
                            yaxis=dict(title="Quy Mô (Người) / Mức Lương ($)", range=[0, max_val * 1.18]),
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        fig.update_layout(**layout_kwargs)

                    if len(active_measures) == 1:
                        meas = active_measures[0]
                        meas_lower = str(meas).lower()
                        is_pct = any(k in meas_lower for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "%", "share", "ratio"])
                        is_curr = any(k in meas_lower for k in ["salary", "lương", "cost", "revenue", "sales", "amount", "profit", "ordervalue", "tiền"])
                        
                        if is_pct:
                            fig.update_traces(texttemplate="%{y:.2f}%", textposition="outside", marker_color="#2563EB")
                            try:
                                max_val = float(plot_df[meas].max() or 0)
                            except Exception:
                                max_val = 100.0
                            fig.update_layout(
                                showlegend=False,
                                yaxis=dict(title=format_col_title(meas), ticksuffix="%", range=[0, max(100.0, max_val * 1.15)])
                            )
                        elif is_curr:
                            fig.update_traces(texttemplate="$%{y:,.2f}" if any('.' in str(v) for v in plot_df[meas]) else "$%{y:,.0f}", textposition="outside", marker_color="#2563EB")
                            try:
                                max_val = float(plot_df[meas].max() or 0)
                            except Exception:
                                max_val = 100.0
                            fig.update_layout(
                                showlegend=False,
                                yaxis=dict(title=format_col_title(meas), range=[0, max_val * 1.15])
                            )
                        else:
                            fig.update_traces(texttemplate="%{y:,.0f}", textposition="outside", marker_color="#2563EB")
                            fig.update_layout(
                                showlegend=False,
                                yaxis=dict(title=format_col_title(meas))
                            )

                    fig.update_layout(
                        xaxis=dict(title=format_col_title(label_name), type="category", tickangle=tick_angle, automargin=True),
                        margin=dict(l=40, r=25, t=50, b=90 if tick_angle != 0 else 50)
                    )

                else:
                    has_duplicate_labels = n_unique_labels < total_rows
                    if has_duplicate_labels and not color_col:
                        if row_identity_col and row_identity_col != label_name:
                            plot_df[label_name] = (
                                plot_df[label_name].astype(str) + " (#" + plot_df[row_identity_col].astype(str) + ")"
                            )
                            st.caption(
                                f"ℹ️ Một số dòng trùng nhãn `{label_name}` nhưng là các thực thể khác nhau "
                                f"(khác `{row_identity_col}`) — đã gắn thêm mã `{row_identity_col}` vào nhãn để phân biệt rõ."
                            )
                        else:
                            plot_df = plot_df.groupby([label_name], as_index=False)[measure_cols[0]].sum()
                            plot_df = plot_df.sort_values(measure_cols[0], ascending=False)
                            total_rows = len(plot_df)

                    if total_rows > 30:
                        max_display = st.slider(
                            f"Số lượng đối tượng hiển thị trên biểu đồ (Tổng kết quả: {total_rows:,} dòng)",
                            min_value=min(10, total_rows),
                            max_value=total_rows,
                            value=min(total_rows, MAX_BAR_CATEGORIES),
                            step=5 if total_rows <= 100 else 10,
                            key=f"bar_limit_{turn_id}"
                        )
                        plot_df = plot_df.head(max_display)

                    category_order = list(dict.fromkeys(plot_df[label_name].tolist()))

                    # Tự động đo độ dài tên lớn nhất để quyết định góc xoay nghiêng chống đè chữ
                    max_label_len = max((len(str(v)) for v in plot_df[label_name]), default=0)
                    if len(plot_df) <= 6:
                        tick_angle = 0
                    else:
                        tick_angle = -35 if (max_label_len > 8 or len(plot_df) > 8) else 0

                    if pd.api.types.is_numeric_dtype(plot_df[measure_cols[0]]) and plot_df[measure_cols[0]].nunique(dropna=True) == 1 and len(plot_df) > 1:
                        st.caption(f"ℹ️ Lưu ý: Tất cả {len(plot_df)} đối tượng hiển thị đều có cùng giá trị `{measure_cols[0]}` = {plot_df[measure_cols[0]].iloc[0]:,}.")

                    m_lower = str(measure_cols[0]).lower()
                    is_years = any(k in m_lower for k in ["year", "thâm niên", "tham_nien", "tenure", "kinh nghiệm", "kinh_nghiem", "service"])
                    is_salary = any(k in m_lower for k in ["salary", "lương", "luong", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "doanh thu"])
                    is_headcount = any(k in m_lower for k in ["headcount", "nhân viên", "nhan_vien", "nhân sự", "nhan_su", "người", "nguoi", "count", "số lượng", "so_luong", "slngnhnvin", "totalemployees"]) and not is_years and not is_salary

                    curr_sym = "$" if is_salary else ""
                    clean_m = format_col_title(measure_cols[0])
                    clean_lbl = format_col_title(label_name)

                    bar_kwargs = dict(
                        data_frame=plot_df, x=label_name, y=measure_cols[0],
                        color=color_col,
                        barmode="group" if color_col else "relative",
                        title=f"{clean_m} theo {clean_lbl}" + (f" (Phân loại theo {format_col_title(color_col)})" if color_col else ""),
                        category_orders={label_name: category_order},
                        template="plotly_white"
                    )

                    # Nếu phân nhóm theo Khối / Nhóm phòng ban, sử dụng bảng màu tương phản trực quan
                    if color_col and any(k in color_col.lower() for k in ["group", "nhóm", "khối"]):
                        group_color_map = {}
                        for g in plot_df[color_col].dropna().unique():
                            g_str = str(g).lower()
                            if any(k in g_str for k in ["kinh doanh", "sales", "commercial"]):
                                group_color_map[g] = "#2563EB"  # Xanh dương cho Kinh doanh
                            elif any(k in g_str for k in ["kỹ thuật", "tech", "development"]):
                                group_color_map[g] = "#10B981"  # Xanh ngọc cho Kỹ thuật
                        if group_color_map:
                            bar_kwargs["color_discrete_map"] = group_color_map
                        else:
                            bar_kwargs["color_discrete_sequence"] = ["#2563EB", "#10B981", "#F59E0B", "#8B5CF6"]

                    fig = px.bar(**bar_kwargs)

                    # Kiểm tra xem có cần format rút gọn tiền tệ (Tỷ / Tr) trên nhãn cột để không bị tràn chữ không
                    max_numeric_val = 0.0
                    try:
                        max_numeric_val = float(pd.to_numeric(plot_df[measure_cols[0]], errors="coerce").max() or 0)
                    except Exception:
                        pass

                    use_compact_currency = is_salary and max_numeric_val >= 10_000_000

                    is_pct = any(k in m_lower for k in ["pct", "percent", "percentage", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "%", "share", "ratio"])
                    if is_pct:
                        ttemplate = "%{y:.2f}%"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    elif is_years:
                        ttemplate = "%{y:.1f} năm"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    elif is_headcount:
                        ttemplate = "%{y:,.0f} người"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    elif use_compact_currency:
                        def _compact_currency_str(v):
                            try:
                                fv = float(v)
                                if abs(fv) >= 1_000_000_000:
                                    return f"${fv / 1_000_000_000:,.2f} Tỷ"
                                elif abs(fv) >= 1_000_000:
                                    return f"${fv / 1_000_000:,.2f} Tr"
                                return f"${fv:,.0f}"
                            except Exception:
                                return str(v)
                        compact_labels = [_compact_currency_str(v) for v in plot_df[measure_cols[0]]]
                        trace_kwargs = {
                            "text": compact_labels,
                            "textposition": "outside",
                            "hovertemplate": "%{x}<br><b>" + clean_m + "</b>: " + curr_sym + "%{y:,.2f}<extra></extra>",
                        }
                    elif is_salary and max_numeric_val >= 100:
                        # Mức lương/ngân sách trên $100: làm tròn số nguyên trên nhãn cột để giao diện gọn gàng, chi tiết lẻ xem khi hover
                        ttemplate = f"{curr_sym}%{{y:,.0f}}"
                        trace_kwargs = {
                            "texttemplate": ttemplate,
                            "textposition": "outside",
                            "hovertemplate": "%{x}<br><b>" + clean_m + "</b>: " + curr_sym + "%{y:,.2f}<extra></extra>",
                        }
                    elif any('.' in str(v) for v in plot_df[measure_cols[0]]):
                        ttemplate = f"{curr_sym}%{{y:,.2f}}"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    else:
                        ttemplate = f"{curr_sym}%{{y:,.0f}}"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}

                    target_entity = None
                    if not color_col:
                        # Kiểm tra xem người dùng có hỏi về một thực thể cụ thể không (Target Entity Accent Color)
                        if user_query:
                            uq_low = user_query.lower()
                            for v in plot_df[label_name]:
                                v_str = str(v).strip()
                                if len(v_str) >= 3 and v_str.lower() in uq_low:
                                    target_entity = v_str
                                    break

                        if target_entity:
                            # Tô màu nổi bật Cam Đậm #F59E0B cho đối tượng được hỏi, màu Xanh #3B82F6 cho các đối tượng khác
                            colors = ['#F59E0B' if str(v).strip().lower() == target_entity.lower() else '#3B82F6' for v in plot_df[label_name]]
                            trace_kwargs["marker_color"] = colors
                        else:
                            # Kiểm tra xem có phải truy vấn xếp hạng Top N không
                            uq_low = (user_query or "").lower()
                            is_top_ranking = any(k in uq_low for k in ["top", "cao nhất", "thấp nhất", "lâu nhất", "xếp hạng", "dẫn đầu", "nhiều nhất", "ít nhất"])
                            if is_top_ranking and 2 <= len(plot_df) <= 15:
                                # Highlight đối tượng dẫn đầu #1 bằng màu Vàng Gold #F59E0B, các đối tượng còn lại màu Xanh Hiện Đại #2563EB
                                colors = ['#F59E0B'] + ['#2563EB'] * (len(plot_df) - 1)
                                trace_kwargs["marker_color"] = colors
                            else:
                                trace_kwargs["marker_color"] = "#1F4E78"

                    if len(plot_df) <= 2:
                        trace_kwargs["width"] = 0.35

                    fig.update_traces(**trace_kwargs)

                    # Đảm bảo không gian phía trên để nhãn ngoài (textposition='outside') không bị che
                    if not color_col and len(plot_df) >= 1 and pd.api.types.is_numeric_dtype(plot_df[measure_cols[0]]):
                        max_y = float(plot_df[measure_cols[0]].max())
                        if max_y > 0:
                            fig.update_yaxes(range=[0, max_y * 1.18])

                    if target_entity and any(k in (user_query or "").lower() for k in ["so sánh", "so voi", "so với", "đối chiếu", "compare", "vs"]):
                        dyn_title = f"📊 So Sánh {clean_m}: {target_entity} vs Các {clean_lbl} Khác"
                    elif target_entity:
                        dyn_title = f"{clean_m} theo {clean_lbl} (Làm nổi bật: {target_entity})"
                    elif color_col and any(k in (user_query or "").lower() for k in ["so sánh", "so voi", "so với", "đối chiếu", "compare", "vs"]):
                        unique_groups = [str(g) for g in plot_df[color_col].unique() if pd.notna(g)]
                        if len(unique_groups) == 2:
                            g1_clean = unique_groups[0].split("(")[0].strip()
                            g2_clean = unique_groups[1].split("(")[0].strip()
                            dyn_title = f"📊 So Sánh {clean_m}: {g1_clean} vs {g2_clean}"
                        else:
                            dyn_title = f"📊 So Sánh {clean_m} theo {clean_lbl} (Phân loại theo {format_col_title(color_col)})"
                    else:
                        dyn_title = f"{clean_m} theo {clean_lbl}" + (f" (Phân loại theo {format_col_title(color_col)})" if color_col else "")

                    yaxis_title_str = f"{clean_m} (Người)" if (is_headcount and "người" not in clean_m.lower()) else clean_m
                    layout_updates = dict(
                        title=dyn_title,
                        xaxis=dict(type="category", tickangle=tick_angle, automargin=True),
                        xaxis_title=clean_lbl,
                        yaxis_title=yaxis_title_str,
                        margin=dict(l=40, r=25, t=50, b=90 if tick_angle != 0 else 50)
                    )
                    if color_col:
                        layout_updates["legend"] = dict(
                            title=None, orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
                        )
                        try:
                            max_val = float(pd.to_numeric(plot_df[measure_cols[0]], errors="coerce").max() or 0)
                            if max_val > 0:
                                layout_updates["yaxis"] = dict(title=clean_m, range=[0, max_val * 1.18])
                        except Exception:
                            pass
                    fig.update_layout(**layout_updates)
            elif len(df) == 1 and len(measure_cols) == 1:
                val = df[measure_cols[0]].iloc[0]
                val_num = 0 if pd.isna(val) else val
                m_name = str(measure_cols[0])
                m_lower = m_name.lower()
                is_pct = any(k in m_lower for k in ["percent", "ratio", "rate", "tỷ lệ", "phan_tram", "%"]) or (isinstance(val_num, (int, float)) and 0.0 < float(val_num) <= 100.0 and any(k in m_lower for k in ["pct", "share", "portion"]))

                if is_pct and isinstance(val_num, (int, float)) and 0.0 <= float(val_num) <= 100.0:
                    pct_val = float(val_num)
                    rem_val = max(0.0, 100.0 - pct_val)
                    fig = px.pie(
                        names=[f"{m_name} ({pct_val:,.2f}%)", f"Còn lại ({rem_val:,.2f}%)"],
                        values=[pct_val, rem_val],
                        hole=0.55,
                        title=f"Biểu đồ Tỷ trọng (Donut): {m_name} ({pct_val:,.2f}%)",
                        template="plotly_white",
                        color_discrete_sequence=["#1F4E78", "#E2E8F0"]
                    )
                    fig.update_traces(
                        textinfo="percent+label",
                        textposition="outside",
                        direction="clockwise"
                    )
                    fig.update_layout(
                        margin=dict(l=20, r=20, t=50, b=50),
                        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
                    )
                else:
                    fig = px.bar(
                        x=[m_name],
                        y=[val_num],
                        text=[f"{val_num:,.2f}" if isinstance(val_num, float) else f"{val_num:,.0f}" if isinstance(val_num, int) else str(val_num)],
                        title=f"Chỉ số: {m_name}",
                        template="plotly_white"
                    )
                    fig.update_traces(textposition="outside", marker_color="#1F4E78", width=0.35)
                    fig.update_layout(
                        xaxis_title="",
                        yaxis_title=m_name,
                        margin=dict(l=20, r=20, t=50, b=50)
                    )
            else:
                st.info("Không tìm thấy cột phù hợp để làm nhãn trục X.")
                return None

        elif chosen in ("Pie", "Biểu đồ tròn (Pie)", "Pie (Tròn)") and measure_cols:
            if label_cols:
                label_name, label_series, consumed_cols = pick_label_column(df, label_cols)
                if label_name is None:
                    st.info("Không tìm thấy cột phù hợp để phân loại lát cắt biểu đồ tròn.")
                    return None

                plot_df = df.copy()
                plot_df[label_name] = label_series.values

                # Nếu quá nhiều lát cắt (> 10), giữ top 9 và gộp phần còn lại vào 'Khác'
                if len(plot_df) > 10:
                    top_df = plot_df.sort_values(measure_cols[0], ascending=False).head(9)
                    other_sum = plot_df.sort_values(measure_cols[0], ascending=False).iloc[9:][measure_cols[0]].sum()
                    other_row = pd.DataFrame([{label_name: "Các đối tượng khác", measure_cols[0]: other_sum}])
                    plot_df = pd.concat([top_df, other_row], ignore_index=True)

                is_val_pct = any(k in str(measure_cols[0]).lower() for k in ["pct", "percent", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "%"])
                fig = px.pie(
                    plot_df,
                    names=label_name,
                    values=measure_cols[0],
                    hole=0.38,
                    title=f"Tỷ trọng {format_col_title(measure_cols[0])} theo {format_col_title(label_name)}",
                    template="plotly_white"
                )
                if is_val_pct:
                    fig.update_traces(
                        textposition='inside',
                        textinfo='percent+label',
                        hovertemplate="<b>%{label}</b><br>" + f"{format_col_title(measure_cols[0])}: " + "%{value:,.2f}%<extra></extra>"
                    )
                else:
                    fig.update_traces(
                        textposition='inside',
                        textinfo='percent+label',
                        hovertemplate="<b>%{label}</b><br>" + f"{format_col_title(measure_cols[0])}: " + "%{value:,.0f} (%{percent})<extra></extra>"
                    )
                fig.update_layout(
                    margin=dict(l=20, r=20, t=50, b=50),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
                )
            elif len(df) == 1:
                val = df[measure_cols[0]].iloc[0]
                val_num = 0 if pd.isna(val) else val
                m_name = str(measure_cols[0])
                try:
                    pct_val = float(val_num)
                except (ValueError, TypeError):
                    pct_val = 0.0

                rem_val = max(0.0, 100.0 - pct_val) if (0.0 <= pct_val <= 100.0) else 0.0
                fig = px.pie(
                    names=[f"{m_name} ({pct_val:,.2f}%)", f"Còn lại ({rem_val:,.2f}%)"],
                    values=[pct_val, rem_val],
                    hole=0.55,
                    title=f"Biểu đồ Tỷ trọng (Donut): {m_name} ({pct_val:,.2f}%)",
                    template="plotly_white",
                    color_discrete_sequence=["#1F4E78", "#E2E8F0"]
                )
                fig.update_traces(
                    textinfo="percent+label",
                    textposition="outside",
                    direction="clockwise"
                )
                fig.update_layout(
                    margin=dict(l=20, r=20, t=50, b=50),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
                )
            else:
                st.info("Biểu đồ tròn cần ít nhất một cột phân loại để chia lát cắt.")
                return None

        elif chosen in ("Bar Ngang", "Bar Cột Ngang", "Bar Ngang (Xếp hạng)", "Horizontal Bar") and measure_cols:
            if label_cols or time_col:
                effective_label_cols = label_cols if label_cols else ([time_col] if time_col else [])
                label_name, label_series, consumed_cols = pick_label_column(df, effective_label_cols)
                if label_name is None:
                    st.info("Không tìm thấy cột phù hợp để làm nhãn.")
                    return None

                plot_df = df.copy()
                plot_df[label_name] = label_series.values

                if len(plot_df) > 30:
                    plot_df = plot_df.head(30)

                # Sắp xếp tăng dần để khi vẽ từ dưới lên thì người cao nhất nằm trên cùng
                plot_df = plot_df.sort_values(measure_cols[0], ascending=True)

                m_lower = str(measure_cols[0]).lower()
                is_years = any(k in m_lower for k in ["year", "thâm niên", "tham_nien", "tenure", "kinh nghiệm", "kinh_nghiem", "service"])
                is_salary = any(k in m_lower for k in ["salary", "lương", "luong", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "doanh thu", "sales", "amount"])
                is_headcount = any(k in m_lower for k in ["headcount", "nhân viên", "nhan_vien", "người", "count", "số lượng", "so_luong"])

                curr_sym = "$" if is_salary else ""
                clean_m = format_col_title(measure_cols[0])
                clean_lbl = format_col_title(label_name)

                fig = px.bar(
                    plot_df,
                    x=measure_cols[0],
                    y=label_name,
                    orientation='h',
                    title=f"Xếp hạng {clean_m} theo {clean_lbl}",
                    template="plotly_white"
                )
                target_entity = None
                if user_query:
                    uq_low = user_query.lower()
                    for v in plot_df[label_name]:
                        v_str = str(v).strip()
                        if len(v_str) >= 3 and v_str.lower() in uq_low:
                            target_entity = v_str
                            break

                if target_entity:
                    h_colors = ['#F59E0B' if str(v).strip().lower() == (target_entity or "").lower() else '#2563EB' for v in plot_df[label_name]]
                elif any(k in (user_query or "").lower() for k in ["top", "cao nhất", "nhất", "xếp hạng", "leading"]):
                    # Highlight #1 entity (last row in ascending sorted plot_df) in Gold #F59E0B, others in blue #2563EB
                    h_colors = ['#2563EB'] * len(plot_df)
                    if len(h_colors) > 0:
                        h_colors[-1] = '#F59E0B'
                else:
                    h_colors = '#2563EB'

                if is_years:
                    h_ttemplate = "%{x:.1f} năm"
                elif is_headcount:
                    h_ttemplate = "%{x:,.0f} người"
                elif any('.' in str(v) for v in plot_df[measure_cols[0]]):
                    h_ttemplate = f"{curr_sym}%{{x:,.2f}}"
                else:
                    h_ttemplate = f"{curr_sym}%{{x:,.0f}}"

                fig.update_traces(
                    marker_color=h_colors,
                    texttemplate=h_ttemplate,
                    textposition='outside',
                    width=0.45 if len(plot_df) <= 3 else None
                )

                max_val = float(plot_df[measure_cols[0]].max()) if not plot_df.empty else 0

                # Dành không gian bên phải để nhãn text outside không bị cắt hay chạm biên
                if max_val > 0:
                    fig.update_xaxes(range=[0, max_val * 1.22])

                max_name_len = max((len(str(v)) for v in plot_df[label_name]), default=10)
                margin_left = max(130, min(250, max_name_len * 9))
                chart_height = max(400, len(plot_df) * 38 + 100)

                fig.update_layout(
                    yaxis=dict(type="category", automargin=True),
                    xaxis_title=clean_m,
                    yaxis_title="",
                    height=chart_height,
                    margin=dict(l=margin_left, r=60, t=60, b=50)
                )
            else:
                st.info("Không tìm thấy cột phù hợp để làm nhãn biểu đồ.")
                return None

        elif chosen == "Scatter" and len(measure_cols) >= 2:
            x_m = measure_cols[0]
            y_m = measure_cols[1]
            hover_name = label_cols[0] if label_cols else None
            fig = px.scatter(
                df, x=x_m, y=y_m,
                hover_name=hover_name,
                title=f"Tương quan giữa {x_m} và {y_m}",
                template="plotly_white"
            )
            fig.update_layout(margin=dict(l=20, r=20, t=50, b=50))
        else:
            st.info("Không thể vẽ biểu đồ với các cột hiện có.")
            return None

        st.plotly_chart(
            fig,
            width='stretch',
            key=f"chart_{turn_id}",
            config={"toImageButtonOptions": {"format": "png", "filename": f"chart_{turn_id}", "scale": 2}}
        )
        return fig

    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {str(e)}")
        return None
