"""
Multi-Layer Executive Intelligence Dashboard UI.
Provides a comprehensive Overview Hub and 6 specialized detail layers for the employees database:
1. Department Management
2. Employee Directory
3. Salary Analysis
4. Organizational Structure
5. Title & Positions
6. Department Managers
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
    build_tickets_by_type_donut,
    build_new_vs_returned_donut,
    build_weekday_bar_chart,
    build_horizontal_bar_chart
)


def _render_sql_modal(title: str, sql: str, exec_time_ms: float, key: str):
    """Hiển thị câu lệnh SQL đằng sau widget trong expander nhỏ gọn, chuẩn mực."""
    with st.expander(f"🔍 Xem câu lệnh SQL ({title}) • {exec_time_ms} ms", expanded=False):
        st.code(sql, language="sql")
        st.caption(f"⚡ Thời gian thực thi: **{exec_time_ms} ms** • Engine: SQLAlchemy Live Engine")


def _trigger_ai_deep_dive(prompt_text: str):
    """Chuyển hướng sang chế độ Chat để tác tử AI giải thích sâu và phân tích nguyên nhân gốc rễ."""
    st.session_state["pending_prompt"] = prompt_text
    st.session_state["view_mode"] = "chat"
    st.rerun()


def _set_layer(layer_name: str):
    """Chuyển đổi tầng/layer hiển thị trên Dashboard."""
    st.session_state["hr_dashboard_layer"] = layer_name
    st.rerun()


# =========================================================================
# MAIN DASHBOARD RENDERER & ROUTER
# =========================================================================

def render_crm_dashboard():
    """Hàm chính hiển thị Dashboard đa tầng tự động thích ứng với CSDL hiện tại."""
    engine = st.session_state.get("engine")
    auto_domain = detect_dashboard_domain(engine)

    # 1. Custom CSS Theme Cyber Dark / Glassmorphism
    st.markdown("""
    <style>
        .kpi-card-purple {
            background: linear-gradient(135deg, #D946EF 0%, #8B5CF6 100%);
            border-radius: 16px;
            padding: 16px 18px;
            color: #FFFFFF;
            box-shadow: 0 8px 24px rgba(217, 70, 239, 0.28);
            min-height: 115px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .kpi-card-cyan {
            background: linear-gradient(135deg, #06B6D4 0%, #3B82F6 100%);
            border-radius: 16px;
            padding: 16px 18px;
            color: #FFFFFF;
            box-shadow: 0 8px 24px rgba(6, 182, 212, 0.28);
            min-height: 115px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .kpi-card-emerald {
            background: linear-gradient(135deg, #10B981 0%, #059669 100%);
            border-radius: 16px;
            padding: 16px 18px;
            color: #FFFFFF;
            box-shadow: 0 8px 24px rgba(16, 185, 129, 0.28);
            min-height: 115px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .kpi-card-amber {
            background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%);
            border-radius: 16px;
            padding: 16px 18px;
            color: #FFFFFF;
            box-shadow: 0 8px 24px rgba(245, 158, 11, 0.28);
            min-height: 115px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .crm-card {
            background: #161B33;
            border-radius: 16px;
            padding: 16px 18px;
            border: 1px solid #232A4D;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
            margin-bottom: 14px;
        }
        .crm-card-title {
            font-size: 0.92rem;
            font-weight: 700;
            color: #F8FAFC;
            letter-spacing: -0.01em;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .nav-hub-card {
            background: linear-gradient(135deg, #1E2442 0%, #161B33 100%);
            border: 1.5px solid #2D3766;
            border-radius: 16px;
            padding: 14px 16px;
            transition: all 0.2s ease;
            min-height: 120px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .nav-hub-card:hover {
            border-color: #00F0FF;
            box-shadow: 0 6px 20px rgba(0, 240, 255, 0.2);
            transform: translateY(-2px);
        }
        .layer-breadcrumb {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.88rem;
            color: #94A3B8;
            margin-bottom: 12px;
        }
    </style>
    """, unsafe_allow_html=True)

    # Nếu đang ở CSDL CRM / Support, chuyển về view CRM
    if auto_domain != "hr_employees":
        _render_crm_legacy_view(engine)
        return

    # Khởi tạo state layer hiện tại (mặc định: 'overview')
    current_layer = st.session_state.get("hr_dashboard_layer", "overview")

    # 2. Điều hướng Header
    c_hdr1, c_hdr2, c_hdr3 = st.columns([5, 2, 1.5])
    with c_hdr1:
        st.markdown("""
        <div style="display: flex; align-items: center; gap: 10px;">
            <div style="font-size: 1.6rem; font-weight: 850; color: #0F172A;">👥 HR & Payroll Intelligence Dashboard</div>
            <span style="background: #E0E7FF; color: #4338CA; padding: 3px 10px; border-radius: 20px; font-size: 0.76rem; font-weight: 700;">CSDL Employees (Live SQL)</span>
        </div>
        """, unsafe_allow_html=True)

    with c_hdr2:
        layer_names = {
            "overview": "🏠 Trang chủ Tổng quan (Overview)",
            "dept_mgmt": "🏢 Quản lý Phòng ban (Departments)",
            "employee_dir": "👥 Danh bạ Nhân viên (Directory)",
            "salary_analysis": "💰 Phân tích Tiền lương (Salary)",
            "org_structure": "🌳 Cơ cấu Tổ chức (Org Structure)",
            "title_positions": "🎓 Chức danh & Vị trí (Titles)",
            "dept_managers": "👔 Đội ngũ Quản lý (Managers)",
        }
        selected_l = st.selectbox(
            "Chọn tầng phân tích",
            list(layer_names.keys()),
            format_func=lambda x: layer_names[x],
            index=list(layer_names.keys()).index(current_layer) if current_layer in layer_names else 0,
            key="sb_select_hr_layer",
            label_visibility="collapsed"
        )
        if selected_l != current_layer:
            st.session_state["hr_dashboard_layer"] = selected_l
            st.rerun()

    with c_hdr3:
        if st.button("💬 Chat với AI", type="secondary", use_container_width=True, help="Quay lại giao diện trò chuyện & hỏi tự do với Tác tử AI"):
            st.session_state["view_mode"] = "chat"
            st.rerun()

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # 3. ROUTING TỚI CÁC LAYER CHUYÊN BIỆT
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
    """Trang chủ Overview: Danh sách các thẻ chủ đề, 4 KPI tóm tắt, Biểu đồ phân bổ phòng ban & Top 5."""
    data = fetch_hr_overview_data(engine)

    # 1. KHỐI NÚT BẤM / CARDS CHUYỂN LAYER (6 CHỦ ĐỀ CHÍNH)
    st.markdown("""
    <div style="font-size: 0.95rem; font-weight: 700; color: #334155; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
        <span>🎯</span> <span><b>Chọn chủ đề phân tích chuyên sâu (Khám phá theo Layer):</b></span>
    </div>
    """, unsafe_allow_html=True)

    nav_cols1 = st.columns(3)
    with nav_cols1[0]:
        with st.container(border=True):
            st.markdown("""
            <div style="font-weight: 700; font-size: 0.95rem; color: #0F172A; margin-bottom: 2px;">🏢 Department Management</div>
            <div style="font-size: 0.8rem; color: #64748B; min-height: 38px; line-height: 1.35;">Danh sách phòng ban, quản lý, quy mô nhân sự và tổng quỹ lương chi trả.</div>
            """, unsafe_allow_html=True)
            if st.button("Mở Phòng Ban ➔", key="btn_nav_dept", use_container_width=True, type="secondary"):
                _set_layer("dept_mgmt")

    with nav_cols1[1]:
        with st.container(border=True):
            st.markdown("""
            <div style="font-weight: 700; font-size: 0.95rem; color: #0F172A; margin-bottom: 2px;">👥 Employee Directory</div>
            <div style="font-size: 0.8rem; color: #64748B; min-height: 38px; line-height: 1.35;">Danh bạ toàn bộ nhân viên, tìm kiếm theo ID/Tên, lọc phòng ban & chức danh.</div>
            """, unsafe_allow_html=True)
            if st.button("Mở Danh Bạ ➔", key="btn_nav_emp", use_container_width=True, type="secondary"):
                _set_layer("employee_dir")

    with nav_cols1[2]:
        with st.container(border=True):
            st.markdown("""
            <div style="font-weight: 700; font-size: 0.95rem; color: #0F172A; margin-bottom: 2px;">💰 Salary Analysis</div>
            <div style="font-size: 0.8rem; color: #64748B; min-height: 38px; line-height: 1.35;">Phân bố mức lương theo phòng ban, theo chức danh và Top 10 thu nhập cao nhất.</div>
            """, unsafe_allow_html=True)
            if st.button("Mở Tiền Lương ➔", key="btn_nav_sal", use_container_width=True, type="secondary"):
                _set_layer("salary_analysis")

    nav_cols2 = st.columns(3)
    with nav_cols2[0]:
        with st.container(border=True):
            st.markdown("""
            <div style="font-weight: 700; font-size: 0.95rem; color: #0F172A; margin-bottom: 2px;">🌳 Organizational Structure</div>
            <div style="font-size: 0.8rem; color: #64748B; min-height: 38px; line-height: 1.35;">Sơ đồ cơ cấu tổ chức, quy mô nhân sự trực tiếp dưới quyền của từng Manager.</div>
            """, unsafe_allow_html=True)
            if st.button("Mở Cơ Cấu ➔", key="btn_nav_org", use_container_width=True, type="secondary"):
                _set_layer("org_structure")

    with nav_cols2[1]:
        with st.container(border=True):
            st.markdown("""
            <div style="font-weight: 700; font-size: 0.95rem; color: #0F172A; margin-bottom: 2px;">🎓 Title & Positions</div>
            <div style="font-size: 0.8rem; color: #64748B; min-height: 38px; line-height: 1.35;">Danh mục chức danh công việc, phân bổ nhân sự và thu nhập bình quân từng vị trí.</div>
            """, unsafe_allow_html=True)
            if st.button("Mở Chức Danh ➔", key="btn_nav_title", use_container_width=True, type="secondary"):
                _set_layer("title_positions")

    with nav_cols2[2]:
        with st.container(border=True):
            st.markdown("""
            <div style="font-weight: 700; font-size: 0.95rem; color: #0F172A; margin-bottom: 2px;">👔 Department Managers</div>
            <div style="font-size: 0.8rem; color: #64748B; min-height: 38px; line-height: 1.35;">Hồ sơ chi tiết đội ngũ Manager, phòng ban quản lý, nhiệm kỳ và mức lương.</div>
            """, unsafe_allow_html=True)
            if st.button("Mở Managers ➔", key="btn_nav_mgr", use_container_width=True, type="secondary"):
                _set_layer("dept_managers")

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # 2. 4 THẺ CHỈ SỐ KPI TÓM TẮT TOÀN BỘ CÔNG TY
    st.markdown("""
    <div style="font-size: 0.95rem; font-weight: 700; color: #334155; margin-bottom: 8px;">
        📊 <b>Chỉ số Tổng hợp Doanh nghiệp (Company Overview KPIs):</b>
    </div>
    """, unsafe_allow_html=True)

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.markdown(f"""
        <div class="kpi-card-cyan">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase; opacity: 0.9;">Tổng Số Nhân Viên</div>
            <div style="font-size: 1.85rem; font-weight: 850;">{data['total_employees']:,}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">👥 Quy mô toàn công ty</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi2:
        st.markdown(f"""
        <div class="kpi-card-purple">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase; opacity: 0.9;">Số Department</div>
            <div style="font-size: 1.85rem; font-weight: 850;">{data['total_departments']}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">🏢 Khối phòng ban nghiệp vụ</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi3:
        st.markdown(f"""
        <div class="kpi-card-emerald">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase; opacity: 0.9;">Mức Lương Bình Quân</div>
            <div style="font-size: 1.85rem; font-weight: 850;">${data['avg_salary']:,.0f}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">⚡ Quỹ lương hiện tại</div>
        </div>
        """, unsafe_allow_html=True)

    with kpi4:
        st.markdown(f"""
        <div class="kpi-card-amber">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase; opacity: 0.9;">Số Vị Trí / Title</div>
            <div style="font-size: 1.85rem; font-weight: 850;">{data['distinct_titles']}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">🎓 Cấp bậc & chức danh</div>
        </div>
        """, unsafe_allow_html=True)

    _render_sql_modal("Chỉ Số Tổng Hợp", data["sql"], data["exec_time_ms"], "overview_kpi_sql")

    # 3. 2 BIỂU ĐỒ TRUNG TÂM: PHÂN BỔ PHÒNG BAN & TOP 5 PHÒNG BAN LỚN NHẤT
    col_ch1, col_ch2 = st.columns([1.2, 1.0])
    with col_ch1:
        st.markdown("""
        <div class="crm-card">
            <div class="crm-card-title">
                <span>🎯 Phân Bổ Nhân Viên Theo Department</span>
                <span style="font-size: 0.75rem; color: #00F0FF; font-weight: 600;">9 Phòng ban</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        fig_donut = build_tickets_by_type_donut(data["dept_df"], label_col="Department", val_col="Headcount")
        st.plotly_chart(fig_donut, use_container_width=True, config={"displayModeBar": False})

    with col_ch2:
        st.markdown("""
        <div class="crm-card">
            <div class="crm-card-title">
                <span>🏆 Top 5 Department Quy Mô Lớn Nhất</span>
                <span style="font-size: 0.75rem; color: #38BDF8; font-weight: 600;">Headcount</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        fig_top5 = build_horizontal_bar_chart(data["top5_dept_df"], x_col="Headcount", y_col="Department", color_hex="rgba(0, 240, 255, 0.85)")
        st.plotly_chart(fig_top5, use_container_width=True, config={"displayModeBar": False})


# =========================================================================
# LAYER 1: DEPARTMENT MANAGEMENT (QUẢN LÝ PHÒNG BAN)
# =========================================================================

def _render_layer_department_management(engine):
    """Layer 1: Danh sách phòng ban, Quản lý, Số lượng nhân viên, Tổng quỹ lương."""
    data = fetch_hr_dept_management_data(engine)
    df = data["df"]

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        st.markdown("<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>Trang Chủ</a> ➔ <b>🏢 Department Management</b></div>", unsafe_allow_html=True)
    with c_bc2:
        if st.button("⬅️ Trang Chủ", key="btn_back_home_1", use_container_width=True):
            _set_layer("overview")

    # Bảng danh sách chi tiết
    st.markdown("""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>📋 Danh Sách Tất Cả Phòng Ban & Cơ Cấu Điều Hành</span>
            <span style="font-size: 0.78rem; color: #00F0FF; font-weight: 600;">9 Phòng ban</span>
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

    _render_sql_modal("Quản Lý Phòng Ban", data["sql"], data["exec_time_ms"], "dept_mgmt_sql")

    # Biểu đồ so sánh
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("<div class='crm-card-title' style='color:#334155;'>📊 Quy Mô Nhân Sự Theo Phòng Ban</div>", unsafe_allow_html=True)
        fig_bar = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["Department"], "Total": df["ActiveHeadcount"]}))
        st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})
    with col_c2:
        st.markdown("<div class='crm-card-title' style='color:#334155;'>💰 Mức Lương Bình Quân Từng Phòng Ban ($)</div>", unsafe_allow_html=True)
        fig_sal = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["Department"], "Total": df["AvgSalary"]}))
        st.plotly_chart(fig_sal, use_container_width=True, config={"displayModeBar": False})

    if st.button("💬 Phân tích Hiệu quả Phòng ban cùng AI", key="btn_ai_dept_layer", type="secondary"):
        _trigger_ai_deep_dive("Phân tích cơ cấu quy mô nhân sự và tổng quỹ lương chi trả giữa 9 phòng ban trong công ty. Phòng ban nào có chi phí lương trên đầu người cao nhất?")


# =========================================================================
# LAYER 2: EMPLOYEE DIRECTORY (DANH BẠ NHÂN VIÊN)
# =========================================================================

def _render_layer_employee_directory(engine):
    """Layer 2: Danh bạ nhân viên, Tìm kiếm & Lọc, Thống kê nhân viên mới nhất & lương cao nhất."""
    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        st.markdown("<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>Trang Chủ</a> ➔ <b>👥 Employee Directory</b></div>", unsafe_allow_html=True)
    with c_bc2:
        if st.button("⬅️ Trang Chủ", key="btn_back_home_2", use_container_width=True):
            _set_layer("overview")

    # Bộ lọc tìm kiếm
    c_srch, c_f_dept, c_f_title = st.columns([3, 2, 2])
    with c_srch:
        search_q = st.text_input("🔍 Tìm kiếm", placeholder="Nhập tên hoặc mã ID nhân viên...", key="emp_dir_search_input")
    with c_f_dept:
        dept_opts = ["All", "Development", "Production", "Sales", "Customer Service", "Research", "Marketing", "Quality Management", "Human Resources", "Finance"]
        sel_dept = st.selectbox("Lọc Phòng ban", dept_opts, key="emp_dir_dept_filter")
    with c_f_title:
        title_opts = ["All", "Senior Engineer", "Staff", "Engineer", "Senior Staff", "Technique Leader", "Assistant Engineer", "Manager"]
        sel_title = st.selectbox("Lọc Chức danh", title_opts, key="emp_dir_title_filter")

    data = fetch_hr_employee_directory(engine, search_term=search_q, dept_filter=sel_dept, title_filter=sel_title, limit=50)

    # 3 Thẻ Thống Kê Nhanh
    s1, s2, s3 = st.columns(3)
    with s1:
        st.info(f"👥 **Kết quả hiển thị**: **{data['total_records']} nhân viên**")
    with s2:
        st.success(f"🌱 **Mới gia nhập**: **{data['newest_hire']}**")
    with s3:
        st.warning(f"💎 **Thu nhập cao nhất**: **{data['highest_earner']}**")

    disp_df = data["df"].copy()
    if "CurrentSalary" in disp_df.columns:
        disp_df["CurrentSalary ($)"] = disp_df["CurrentSalary"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "$0")
        disp_df = disp_df.drop(columns=["CurrentSalary"])

    st.dataframe(disp_df, hide_index=True, use_container_width=True)
    _render_sql_modal("Danh Bạ Nhân Viên", data["sql"], data["exec_time_ms"], "emp_dir_sql")


# =========================================================================
# LAYER 3: SALARY ANALYSIS (PHÂN TÍCH TIỀN LƯƠNG)
# =========================================================================

def _render_layer_salary_analysis(engine):
    """Layer 3: Phân tích lương theo phòng ban, theo chức danh, Top 10 nhân viên lương cao nhất."""
    data = fetch_hr_salary_analysis_data(engine)

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        st.markdown("<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>Trang Chủ</a> ➔ <b>💰 Salary Analysis</b></div>", unsafe_allow_html=True)
    with c_bc2:
        if st.button("⬅️ Trang Chủ", key="btn_back_home_3", use_container_width=True):
            _set_layer("overview")

    # 4 Thẻ Lương Toàn Diện
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown(f"""
        <div class="kpi-card-emerald">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase;">Lương Bình Quân</div>
            <div style="font-size: 1.85rem; font-weight: 850;">${data['avg_salary']:,.0f}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">⚡ Toàn doanh nghiệp</div>
        </div>
        """, unsafe_allow_html=True)
    with s2:
        st.markdown(f"""
        <div class="kpi-card-purple">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase;">Lương Cao Nhất</div>
            <div style="font-size: 1.85rem; font-weight: 850;">${data['max_salary']:,.0f}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">🏆 Đỉnh điểm thu nhập</div>
        </div>
        """, unsafe_allow_html=True)
    with s3:
        st.markdown(f"""
        <div class="kpi-card-cyan">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase;">Lương Thấp Nhất</div>
            <div style="font-size: 1.85rem; font-weight: 850;">${data['min_salary']:,.0f}</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">📌 Mức lương sàn</div>
        </div>
        """, unsafe_allow_html=True)
    with s4:
        st.markdown(f"""
        <div class="kpi-card-amber">
            <div style="font-size: 0.76rem; font-weight: 600; text-transform: uppercase;">Tổng Quỹ Lương Hiện Tại</div>
            <div style="font-size: 1.85rem; font-weight: 850;">${data['total_payroll']/1e9:,.2f}B</div>
            <div style="font-size: 0.75rem; opacity: 0.85;">💵 Ngân sách chi trả</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # 2 Bảng: Phân bố Lương theo Phòng Ban & Theo Title
    col_d, col_t = st.columns(2)
    with col_d:
        st.markdown("<div class='crm-card-title' style='color:#334155;'>🏢 Phân Bố Lương Theo Phòng Ban</div>", unsafe_allow_html=True)
        disp_dept = data["dept_sal_df"].copy()
        disp_dept["Avg ($)"] = disp_dept["AvgSalary"].apply(lambda x: f"${x:,.0f}")
        disp_dept["Max ($)"] = disp_dept["MaxSalary"].apply(lambda x: f"${x:,.0f}")
        st.dataframe(disp_dept[["Department", "Headcount", "Avg ($)", "Max ($)"]], hide_index=True, use_container_width=True)

    with col_t:
        st.markdown("<div class='crm-card-title' style='color:#334155;'>🎓 Phân Bố Lương Theo Chức Danh (Title)</div>", unsafe_allow_html=True)
        disp_title = data["title_sal_df"].copy()
        disp_title["Avg ($)"] = disp_title["AvgSalary"].apply(lambda x: f"${x:,.0f}")
        disp_title["Max ($)"] = disp_title["MaxSalary"].apply(lambda x: f"${x:,.0f}")
        st.dataframe(disp_title[["Title", "Headcount", "Avg ($)", "Max ($)"]], hide_index=True, use_container_width=True)

    # Bảng Top 10 nhân viên có lương cao nhất
    st.markdown("<div class='crm-card-title' style='color:#334155; margin-top: 14px;'>🏆 Top 10 Nhân Viên Có Mức Lương Cao Nhất Toàn Công Ty</div>", unsafe_allow_html=True)
    disp_top10 = data["top10_df"].copy()
    disp_top10["CurrentSalary ($)"] = disp_top10["CurrentSalary"].apply(lambda x: f"${x:,.0f}")
    st.dataframe(disp_top10[["ID", "FullName", "Department", "Title", "CurrentSalary ($)"]], hide_index=True, use_container_width=True)

    _render_sql_modal("Phân Tích Tiền Lương", data["sql"], data["exec_time_ms"], "sal_analysis_sql")


# =========================================================================
# LAYER 4: ORGANIZATIONAL STRUCTURE (CƠ CẤU TỔ CHỨC)
# =========================================================================

def _render_layer_org_structure(engine):
    """Layer 4: Sơ đồ cơ cấu tổ chức & Span of Control của từng Manager."""
    data = fetch_hr_org_structure_data(engine)
    df = data["df"]

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        st.markdown("<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>Trang Chủ</a> ➔ <b>🌳 Organizational Structure</b></div>", unsafe_allow_html=True)
    with c_bc2:
        if st.button("⬅️ Trang Chủ", key="btn_back_home_4", use_container_width=True):
            _set_layer("overview")

    st.markdown("""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>🌳 Cơ Cấu Lãnh Đạo & Quy Mô Quản Lý (Span of Control)</span>
            <span style="font-size: 0.78rem; color: #00F0FF; font-weight: 600;">9 Khối phòng ban</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    disp_df["ManagerSalary ($)"] = disp_df["ManagerSalary"].apply(lambda x: f"${x:,.0f}")
    st.dataframe(disp_df[["ManagerID", "ManagerName", "Department", "Status", "CurrentDepartmentSize", "ManagerSalary ($)"]], hide_index=True, use_container_width=True)

    _render_sql_modal("Cơ Cấu Tổ Chức", data["sql"], data["exec_time_ms"], "org_struct_sql")

    # Biểu đồ so sánh số lượng nhân sự trực tiếp dưới quyền của Manager
    st.markdown("<div class='crm-card-title' style='color:#334155; margin-top: 12px;'>📊 Quy Mô Nhân Sự Dưới Quyền Của Từng Manager</div>", unsafe_allow_html=True)
    fig_span = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["ManagerName"], "Total": df["CurrentDepartmentSize"]}))
    st.plotly_chart(fig_span, use_container_width=True, config={"displayModeBar": False})


# =========================================================================
# LAYER 5: TITLE & POSITIONS (CHỨC DANH & VỊ TRÍ)
# =========================================================================

def _render_layer_title_positions(engine):
    """Layer 5: Danh sách chức danh, số lượng nhân viên và mức lương bình quân."""
    data = fetch_hr_titles_data(engine)
    df = data["df"]

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        st.markdown("<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>Trang Chủ</a> ➔ <b>🎓 Title & Positions</b></div>", unsafe_allow_html=True)
    with c_bc2:
        if st.button("⬅️ Trang Chủ", key="btn_back_home_5", use_container_width=True):
            _set_layer("overview")

    st.markdown("""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>🎓 Danh Mục Vị Trí & Cơ Cấu Cấp Bậc (7 Titles)</span>
            <span style="font-size: 0.78rem; color: #00F0FF; font-weight: 600;">Toàn công ty</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    disp_df["AvgSalary ($)"] = disp_df["AvgSalary"].apply(lambda x: f"${x:,.0f}")
    disp_df["MaxSalary ($)"] = disp_df["MaxSalary"].apply(lambda x: f"${x:,.0f}")
    disp_df["MinSalary ($)"] = disp_df["MinSalary"].apply(lambda x: f"${x:,.0f}")
    st.dataframe(disp_df[["Title", "Headcount", "Percentage", "AvgSalary ($)", "MaxSalary ($)", "MinSalary ($)"]], hide_index=True, use_container_width=True)

    _render_sql_modal("Chức Danh & Vị Trí", data["sql"], data["exec_time_ms"], "titles_sql")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown("<div class='crm-card-title' style='color:#334155;'>📊 Phân Bổ Nhân Sự Theo Chức Danh</div>", unsafe_allow_html=True)
        fig_donut = build_tickets_by_type_donut(df, label_col="Title", val_col="Headcount")
        st.plotly_chart(fig_donut, use_container_width=True, config={"displayModeBar": False})
    with col_t2:
        st.markdown("<div class='crm-card-title' style='color:#334155;'>💰 Mức Lương Bình Quân Theo Chức Danh ($)</div>", unsafe_allow_html=True)
        fig_sal = build_weekday_bar_chart(pd.DataFrame({"WeekDay": df["Title"], "Total": df["AvgSalary"]}))
        st.plotly_chart(fig_sal, use_container_width=True, config={"displayModeBar": False})


# =========================================================================
# LAYER 6: DEPARTMENT MANAGERS (ĐỘI NGŨ QUẢN LÝ)
# =========================================================================

def _render_layer_dept_managers(engine):
    """Layer 6: Hồ sơ chi tiết các Manager, nhiệm kỳ quản lý và mức lương."""
    data = fetch_hr_managers_data(engine)
    df = data["df"]

    # Breadcrumb
    c_bc1, c_bc2 = st.columns([6, 1])
    with c_bc1:
        st.markdown("<div class='layer-breadcrumb'>🏠 <a href='#' style='color:#64748B;'>Trang Chủ</a> ➔ <b>👔 Department Managers</b></div>", unsafe_allow_html=True)
    with c_bc2:
        if st.button("⬅️ Trang Chủ", key="btn_back_home_6", use_container_width=True):
            _set_layer("overview")

    st.markdown("""
    <div class="crm-card">
        <div class="crm-card-title">
            <span>👔 Danh Sách Đội Ngũ Trưởng Phòng (Managers) Qua Các Thời Kỳ</span>
            <span style="font-size: 0.78rem; color: #00F0FF; font-weight: 600;">Lịch sử & Đương nhiệm</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    disp_df = df.copy()
    disp_df["CurrentSalary ($)"] = disp_df["CurrentSalary"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "N/A")
    st.dataframe(disp_df[["ManagerID", "ManagerName", "Gender", "Department", "StartDate", "EndDate", "TenureStatus", "CurrentDeptHeadcount", "CurrentSalary ($)"]], hide_index=True, use_container_width=True)

    _render_sql_modal("Đội Ngũ Managers", data["sql"], data["exec_time_ms"], "managers_sql")

    if st.button("💬 Phân tích Lương và Nhiệm kỳ Managers cùng AI", key="btn_ai_mgr_layer", type="secondary"):
        _trigger_ai_deep_dive("Phân tích danh sách các Manager của các phòng ban: So sánh mức lương của các Trưởng phòng đương nhiệm và đánh giá thâm niên quản lý của từng người.")


# =========================================================================
# FALLBACK VIEW: CRM / TICKETS DASHBOARD (NẾU CƠ SỞ DỮ LIỆU LÀ CRM)
# =========================================================================

def _render_crm_legacy_view(engine):
    """Fallback hiển thị CRM Support Dashboard nếu CSDL kết nối là CRM/Tickets."""
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
            <div style="font-size: 0.75rem; opacity: 0.85;">🎯 Tỷ lệ: {round(kpis['solved_tickets']*100/max(1, kpis['total_tickets']), 1)}%</div>
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
        st.plotly_chart(fig_wave, use_container_width=True, config={"displayModeBar": False})

    fig_center = build_created_vs_solved_chart(created_solved_data["df"], created_solved_data.get("max_point"))
    st.plotly_chart(fig_center, use_container_width=True, config={"displayModeBar": False})
