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
    "largeorderscount": "Số Lượng Đơn Hàng Lớn",
    "large_orders_count": "Số Lượng Đơn Hàng Lớn",
    "totallargeordersrevenue": "Tổng Doanh Thu Đơn Lớn ($)",
    "total_large_orders_revenue": "Tổng Doanh Thu Đơn Lớn ($)",
    "avglargeorderamount": "Giá Trị TB/Đơn Lớn ($)",
    "avg_large_order_amount": "Giá Trị TB/Đơn Lớn ($)",
    "avgpriceperbox": "Giá Bán TB/Hộp ($)",
    "avg_price_per_box": "Giá Bán TB/Hộp ($)",
    "indiasales": "Doanh Số Ấn Độ ($)",
    "india_sales": "Doanh Số Ấn Độ ($)",
    "indiarank": "Thứ Hạng Ấn Độ",
    "india_rank": "Thứ Hạng Ấn Độ",
    "usasales": "Doanh Số Mỹ ($)",
    "usa_sales": "Doanh Số Mỹ ($)",
    "usarank": "Thứ Hạng Mỹ",
    "usa_rank": "Thứ Hạng Mỹ",
    "rankdivergence": "Độ Phân Hóa Thứ Hạng (Bậc)",
    "rank_divergence": "Độ Phân Hóa Thứ Hạng (Bậc)",
    "rankdifference": "Chênh Lệch Thứ Hạng (Bậc)",
    "rank_difference": "Chênh Lệch Thứ Hạng (Bậc)",
    "totalsales": "Tổng Doanh Thu ($)",
    "total_sales": "Tổng Doanh Thu ($)",
    "totalrevenue": "Tổng Doanh Thu ($)",
    "total_revenue": "Tổng Doanh Thu ($)",
    "product": "Sản Phẩm",
    "percentage": "Tỷ Trọng (%)",
    "percent": "Tỷ Trọng (%)",
    "cumulativepercent": "Tích Lũy Doanh Số (%)",
    "cumulative_percent": "Tích Lũy Doanh Số (%)",
    "cumulativepercentage": "Tích Lũy Doanh Số (%)",
    "cumulative_percentage": "Tích Lũy Doanh Số (%)",
    "departmentgroup": "Nhóm Phòng Ban",
    "department_group": "Nhóm Phòng Ban",
    "deptgroup": "Nhóm Phòng Ban",
    "dept_group": "Nhóm Phòng Ban",
    "headcount": "Quy Mô Nhân Sự",
    "initialheadcount": "Quy Mô Năm Đầu (1985)",
    "initial_headcount": "Quy Mô Năm Đầu (1985)",
    "year3headcount": "Quy Mô Năm 3 (1987)",
    "year3_headcount": "Quy Mô Năm 3 (1987)",
    "year5headcount": "Quy Mô Năm 5 (1989)",
    "year5_headcount": "Quy Mô Năm 5 (1989)",
    "netheadcountgrowth": "Tăng Trưởng Nhân Sự Ròng",
    "net_headcount_growth": "Tăng Trưởng Nhân Sự Ròng",
    "headcountgrowthratepct": "Tốc Độ Tăng Trưởng (%)",
    "headcount_growth_rate_pct": "Tốc Độ Tăng Trưởng (%)",
    "headcountgrowthrate": "Tốc Độ Tăng Trưởng (%)",
    "headcount_growth_rate": "Tốc Độ Tăng Trưởng (%)",
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
    "avgannualsalarygrowth": "Tăng Trưởng Lương TB/Năm ($)",
    "avg_annual_salary_growth": "Tăng Trưởng Lương TB/Năm ($)",
    "startingsalary": "Lương Khởi Điểm ($)",
    "starting_salary": "Lương Khởi Điểm ($)",
    "currentsalary": "Mức Lương Hiện Tại",
    "managersalary": "Lương Quản Lý ($)",
    "manager_salary": "Lương Quản Lý ($)",
    "maxsubordinatesalary": "Lương Cấp Dưới Cao Nhất ($)",
    "max_subordinate_salary": "Lương Cấp Dưới Cao Nhất ($)",
    "senioravgsalary": "Lương TB Kỳ Cựu ($)",
    "senior_avg_salary": "Lương TB Kỳ Cựu ($)",
    "newhireavgsalary": "Lương TB Mới Vào ($)",
    "new_hire_avg_salary": "Lương TB Mới Vào ($)",
    "seniorcount": "Số Lượng Kỳ Cựu (Người)",
    "senior_count": "Số Lượng Kỳ Cựu (Người)",
    "newhirecount": "Số Lượng Mới Vào (Người)",
    "new_hire_count": "Số Lượng Mới Vào (Người)",
    "salarygap": "Chênh Lệch Lương ($)",
    "salary_gap": "Chênh Lệch Lương ($)",
    "salarydeficit": "Mức Thâm Hụt Lương ($)",
    "salary_deficit": "Mức Thâm Hụt Lương ($)",
    "salarysurplus": "Mức Vượt Lương ($)",
    "salary_surplus": "Mức Vượt Lương ($)",
    "titleavgsalary": "Lương TB Chức Danh ($)",
    "title_avg_salary": "Lương TB Chức Danh ($)",
    "salarybelowavg": "Mức Thâm Hụt Lương ($)",
    "salary_below_avg": "Mức Thâm Hụt Lương ($)",
    "firstdepartment": "Phòng Ban Đầu Tiên",
    "first_department": "Phòng Ban Đầu Tiên",
    "firstdept": "Phòng Ban Đầu Tiên",
    "first_dept": "Phòng Ban Đầu Tiên",
    "firstdeptavgsalary": "Lương TB Phòng Đầu ($)",
    "first_dept_avg_salary": "Lương TB Phòng Đầu ($)",
    "currentdepartment": "Phòng Ban Hiện Tại",
    "current_department": "Phòng Ban Hiện Tại",
    "departmentcount": "Số Phòng Ban Từng Làm",
    "department_count": "Số Phòng Ban Từng Làm",
    "deptcount": "Số Phòng Ban Từng Làm",
    "dept_count": "Số Phòng Ban Từng Làm",
    "subordinateswithhighersalary": "Số Cấp Dưới Lương Cao Hơn",
    "subordinates_with_higher_salary": "Số Cấp Dưới Lương Cao Hơn",
    "subordinatename": "Tên Nhân Viên Cấp Dưới",
    "subordinate_name": "Tên Nhân Viên Cấp Dưới",
    "subordinatesalary": "Lương Cấp Dưới ($)",
    "subordinate_salary": "Lương Cấp Dưới ($)",
    "salarydifference": "Chênh Lệch Lương ($)",
    "salary_difference": "Chênh Lệch Lương ($)",
    "differencepercentage": "Tỷ Lệ Chênh Lệch (%)",
    "difference_percentage": "Tỷ Lệ Chênh Lệch (%)",
    "diffpercentage": "Tỷ Lệ Chênh Lệch (%)",
    "diff_percentage": "Tỷ Lệ Chênh Lệch (%)",
    "diffpercent": "Tỷ Lệ Chênh Lệch (%)",
    "diff_percent": "Tỷ Lệ Chênh Lệch (%)",
    "salarydiff": "Chênh Lệch Lương ($)",
    "salary_diff": "Chênh Lệch Lương ($)",
    "avgyearsofservice": "Thâm Niên Trung Bình (Năm)",
    "avg_years_of_service": "Thâm Niên Trung Bình (Năm)",
    "avgtenureyears": "Thâm Niên Trung Bình (Năm)",
    "avg_tenure_years": "Thâm Niên Trung Bình (Năm)",
    "avg_salary": "Lương Trung Bình",
    "avgsalary": "Lương Trung Bình",
    "averagesalary": "Lương Trung Bình",
    "salaryspread": "Chênh Lệch Lương ($)",
    "salary_spread": "Chênh Lệch Lương ($)",
    "maxsalary": "Lương Cao Nhất ($)",
    "max_salary": "Lương Cao Nhất ($)",
    "minsalary": "Lương Thấp Nhất ($)",
    "min_salary": "Lương Thấp Nhất ($)",
    "salarytier": "Nhóm Lương",
    "salary_tier": "Nhóm Lương",
    "employeecount": "Số Lượng Nhân Sự",
    "employee_count": "Số Lượng Nhân Sự",
    "currentavgsalary": "Lương Trung Bình Hiện Tại ($)",
    "current_avg_salary": "Lương Trung Bình Hiện Tại ($)",
    "salarystddev": "Độ Lệch Chuẩn Lương ($)",
    "salary_std_dev": "Độ Lệch Chuẩn Lương ($)",
    "stddev": "Độ Lệch Chuẩn Lương ($)",
    "salary_std": "Độ Lệch Chuẩn Lương ($)",
    "fluctuationrate": "Tỷ Lệ Biến Động (%)",
    "fluctuation_rate": "Tỷ Lệ Biến Động (%)",
    "totalpayroll": "Tổng Quỹ Lương ($)",
    "total_payroll": "Tổng Quỹ Lương ($)",
    "headcount": "Quy Mô Nhân Sự",
    "employeeschangeddepartment": "Nhân Viên Đổi Phòng Ban",
    "employees_changed_department": "Nhân Viên Đổi Phòng Ban",
    "percentagechangeddept": "Tỷ Lệ Đổi Phòng Ban (%)",
    "percentage_changed_dept": "Tỷ Lệ Đổi Phòng Ban (%)",
    "salarypercentile": "Bách Phân Vị Lương (%)",
    "salary_percentile": "Bách Phân Vị Lương (%)",
    "percentile": "Bách Phân Vị Lương (%)",
    "raisecount": "Số Lần Tăng Lương",
    "raise_count": "Số Lần Tăng Lương",
    "numberofincreases": "Số Lần Tăng Lương",
    "salaryincreases": "Số Lần Tăng Lương",
    "salary_increases": "Số Lần Tăng Lương",
    "num_raises": "Số Lần Tăng Lương",
    "raises": "Số Lần Tăng Lương",
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
    "totalsalary": "Tổng Quỹ Lương ($)",
    "total_salary": "Tổng Quỹ Lương ($)",
    "deptpayroll": "Tổng Quỹ Lương ($)",
    "dept_payroll": "Tổng Quỹ Lương ($)",
    "totalsalarycost": "Tổng Quỹ Lương ($)",
    "total_salary_cost": "Tổng Quỹ Lương ($)",
    "totalcompanysalary": "Tổng Chi Phí Lương Toàn Công Ty ($)",
    "total_company_salary": "Tổng Chi Phí Lương Toàn Công Ty ($)",
    "companytotalsalary": "Tổng Chi Phí Lương Toàn Công Ty ($)",
    "company_total_salary": "Tổng Chi Phí Lương Toàn Công Ty ($)",
    "companytotal": "Tổng Chi Phí Toàn Công Ty ($)",
    "company_total": "Tổng Chi Phí Toàn Công Ty ($)",
    "deptsalary": "Chi Phí Lương Phòng Ban ($)",
    "dept_salary": "Chi Phí Lương Phòng Ban ($)",
    "salarybudget": "Quỹ Lương ($)",
    "salary_budget": "Quỹ Lương ($)",
    "totalemployees": "Tổng Số Nhân Viên",
    "total_employees": "Tổng Số Nhân Viên",
    "newtitleappointments": "Số Lượng Bổ Nhiệm Chức Danh Mới",
    "new_title_appointments": "Số Lượng Bổ Nhiệm Chức Danh Mới",
    "titleappointments": "Số Lượng Bổ Nhiệm Chức Danh Mới",
    "title_appointments": "Số Lượng Bổ Nhiệm Chức Danh Mới",
    "titleassignments": "Số Lượng Bổ Nhiệm Chức Danh Mới",
    "title_assignments": "Số Lượng Bổ Nhiệm Chức Danh Mới",
    "appointedemployees": "Số Nhân Viên Được Bổ Nhiệm",
    "appointed_employees": "Số Nhân Viên Được Bổ Nhiệm",
    "promotedemployees": "Số Nhân Viên Thăng Chức",
    "promoted_employees": "Số Nhân Viên Thăng Chức",
    "promotionrate": "Tỷ Lệ Thăng Chức (%)",
    "promotion_rate": "Tỷ Lệ Thăng Chức (%)",
    "promotedcount": "Số Nhân Viên Thăng Chức",
    "promoted_count": "Số Nhân Viên Thăng Chức",
    "promotedpct": "Tỷ Lệ Thăng Chức (%)",
    "promoted_pct": "Tỷ Lệ Thăng Chức (%)",
    "promotionpct": "Tỷ Lệ Thăng Chức (%)",
    "initialsalary": "Lương Khởi Điểm ($)",
    "initial_salary": "Lương Khởi Điểm ($)",
    "currentsalary": "Lương Hiện Tại ($)",
    "current_salary": "Lương Hiện Tại ($)",
    "salaryincrease": "Mức Tăng Lương ($)",
    "salary_increase": "Mức Tăng Lương ($)",
    "salarygrowthratepct": "Tỷ Lệ Tăng Lương (%)",
    "salary_growth_rate_pct": "Tỷ Lệ Tăng Lương (%)",
    "growthratepct": "Tỷ Lệ Tăng Lương (%)",
    "salaryreduction": "Mức Giảm Lương ($)",
    "salary_reduction": "Mức Giảm Lương ($)",
    "reductionpct": "Tỷ Lệ Giảm Lương (%)",
    "reduction_pct": "Tỷ Lệ Giảm Lương (%)",
    "prevsalary": "Lương Trước Khi Giảm ($)",
    "prev_salary": "Lương Trước Khi Giảm ($)",
    "newsalary": "Lương Sau Khi Giảm ($)",
    "new_salary": "Lương Sau Khi Giảm ($)",
    "reductiondate": "Ngày Giảm Lương",
    "reduction_date": "Ngày Giảm Lương",
    "q1_rank": "Hạng Q1",
    "q2_rank": "Hạng Q2",
    "q3_rank": "Hạng Q3",
    "q4_rank": "Hạng Q4",
    "q1_sales": "Doanh Thu Q1 ($)",
    "q2_sales": "Doanh Thu Q2 ($)",
    "q3_sales": "Doanh Thu Q3 ($)",
    "q4_sales": "Doanh Thu Q4 ($)",
    "rankchange": "Biến Động Thứ Hạng (Bậc)",
    "rank_change": "Biến Động Thứ Hạng (Bậc)",
    "rankdelta": "Biến Động Thứ Hạng (Bậc)",
    "rank_delta": "Biến Động Thứ Hạng (Bậc)",
    "rankimprovement": "Mức Tăng Hạng (Bậc)",
    "performancestatus": "Phân Loại Biến Động",
    "performance_status": "Phân Loại Biến Động",
    "totalannualsales": "Tổng Doanh Thu Cả Năm ($)",
    "total_annual_sales": "Tổng Doanh Thu Cả Năm ($)",
    "initialtitle": "Chức Danh Khởi Điểm",
    "initial_title": "Chức Danh Khởi Điểm",
    "promotedtitle": "Chức Danh Bổ Nhiệm",
    "promoted_title": "Chức Danh Bổ Nhiệm",
    "promotiondate": "Ngày Thăng Chức",
    "promotion_date": "Ngày Thăng Chức",
    "promotedtomanagerdate": "Ngày Bổ Nhiệm Manager",
    "managertitle": "Chức Danh Quản Lý",
    "hiredate": "Ngày Tuyển Dụng",
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
    "profit": "Lợi Nhuận ($)",
    "totalprofit": "Tổng Lợi Nhuận ($)",
    "total_profit": "Tổng Lợi Nhuận ($)",
    "netprofit": "Lợi Nhuận Thuần ($)",
    "net_profit": "Lợi Nhuận Thuần ($)",
    "loinhuan": "Lợi Nhuận ($)",
    "loi_nhuan": "Lợi Nhuận ($)",
    "totalcost": "Tổng Chi Phí ($)",
    "total_cost": "Tổng Chi Phí ($)",
    "tongchiphi": "Tổng Chi Phí ($)",
    "tong_chi_phi": "Tổng Chi Phí ($)",
    "cogs": "Giá Vốn ($)",
    "giavon": "Giá Vốn ($)",
    "margin": "Tỷ Suất Lợi Nhuận (%)",
    "tysuatloinhuan": "Tỷ Suất Lợi Nhuận (%)",
    "ty_suat_loi_nhuan": "Tỷ Suất Lợi Nhuận (%)",
    "tongdoanhthu": "Tổng Doanh Thu ($)",
    "tong_doanh_thu": "Tổng Doanh Thu ($)",
    "totalreturns": "Tổng Doanh Thu ($)",
    "total_returns": "Tổng Doanh Thu ($)",
    "returns": "Tổng Doanh Thu ($)",
    "packagingcost": "Tổng Chi Phí ($)",
    "packaging_cost": "Tổng Chi Phí ($)",
    "totalpackagingcost": "Tổng Chi Phí ($)",
    "total_packaging_cost": "Tổng Chi Phí ($)",
    "boxcost": "Tổng Chi Phí ($)",
    "box_cost": "Tổng Chi Phí ($)",
    "totalboxcost": "Tổng Chi Phí ($)",
    "totalboxescost": "Tổng Chi Phí ($)",
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
    "salarydifference": "Chênh Lệch Lương ($)",
    "salary_difference": "Chênh Lệch Lương ($)",
    "differencepercentage": "Tỷ Lệ Chênh Lệch (%)",
    "difference_percentage": "Tỷ Lệ Chênh Lệch (%)",
    "diffpct": "Tỷ Lệ Chênh Lệch (%)",
    "diff_pct": "Tỷ Lệ Chênh Lệch (%)",
    "paygap": "Khoảng Cách Lương ($)",
    "pay_gap": "Khoảng Cách Lương ($)",
    "gap_pct": "Tỷ Lệ Chênh Lệch (%)",
    "gappct": "Tỷ Lệ Chênh Lệch (%)",
    "subordinateavgsalary": "Lương TB Cấp Dưới ($)",
    "subordinate_avg_salary": "Lương TB Cấp Dưới ($)",
    "avgsubordinatesalary": "Lương TB Cấp Dưới ($)",
    "avg_subordinate_salary": "Lương TB Cấp Dưới ($)",
    "maxsubordinatesalary": "Lương Cấp Dưới Cao Nhất ($)",
    "max_subordinate_salary": "Lương Cấp Dưới Cao Nhất ($)",
    "subordinatesalary": "Lương Cấp Dưới ($)",
    "subordinate_salary": "Lương Cấp Dưới ($)",
    "managersalary": "Lương Quản Lý ($)",
    "manager_salary": "Lương Quản Lý ($)",
    "managername": "Tên Quản Lý",
    "manager_name": "Tên Quản Lý",
    "subordinateswithhighersalary": "Số Cấp Dưới Lương Cao Hơn",
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


def clean_chart_title(title: str) -> str:
    """Loại bỏ các từ lặp lại hoặc thừa thãi trong tiêu đề biểu đồ (e.g. 'Tỷ trọng Tỷ Lệ', 'Tỷ trọng Tỷ Trọng')."""
    if not title:
        return ""
    res = title
    patterns = [
        (r"(?i)\btỷ\s*trọng\s+tỷ\s*trọng\b", "Tỷ Trọng"),
        (r"(?i)\btỷ\s*trọng\s+tỷ\s*lệ\b", "Tỷ Lệ"),
        (r"(?i)\btỷ\s*trọng\s+tỉ\s*trọng\b", "Tỷ Trọng"),
        (r"(?i)\btỷ\s*trọng\s+tỉ\s*lệ\b", "Tỷ Lệ"),
        (r"(?i)\btỷ\s*lệ\s+tỷ\s*lệ\b", "Tỷ Lệ"),
        (r"(?i)\btỷ\s*lệ\s+tỷ\s*trọng\b", "Tỷ Trọng"),
        (r"(?i)\btỉ\s*trọng\s+tỉ\s*trọng\b", "Tỉ Trọng"),
        (r"(?i)\btỉ\s*trọng\s+tỷ\s*trọng\b", "Tỷ Trọng"),
        (r"(?i)\btỉ\s*lệ\s+tỉ\s*lệ\b", "Tỉ Lệ"),
        (r"(?i)\bcơ\s*cấu\s+tỷ\s*lệ\s+phần\s*trăm\b", "Cơ Cấu Tỷ Lệ"),
        (r"(?i)\bcơ\s*cấu\s+tỷ\s*trọng\b", "Cơ Cấu"),
        (r"(?i)\bcơ\s*cấu\s+tỉ\s*trọng\b", "Cơ Cấu"),
        (r"(?i)\bcơ\s*cấu\s+cơ\s*cấu\b", "Cơ Cấu"),
        (r"(?i)\bso\s*sánh\s+so\s*sánh\b", "So Sánh"),
        (r"(?i)\bquy\s*mô\s+quy\s*mô\b", "Quy Mô"),
        (r"(?i)\bsố\s*lượng\s+số\s*lượng\b", "Số Lượng"),
    ]
    for pat, repl in patterns:
        res = re.sub(pat, repl, res)
    return res.strip()


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
        is_en = (st.session_state.get("lang") == "en") if hasattr(st, "session_state") else False
        n_time = df[time_col].nunique(dropna=True) if (time_col and time_col in df.columns) else 0

        if chart_override == "Tự động":
            # 0. QUY TẮC ADAPTIVE VIZ: Chặn vẽ biểu đồ vô nghĩa cho kết quả tổng hợp 1 dòng (Single-row metric aggregate)
            # Khi kết quả chỉ có đúng 1 dòng dữ liệu dạng tổng hợp (Single-row summary với nhiều chỉ số đa đơn vị: $, số lượng đơn, số hộp...),
            # việc gom các biến số khác bản chất và thang đo lên cùng một trục Y sẽ gây biến dạng trực quan nghiêm trọng (Scale Distortion).
            # Nguyên tắc chuẩn BI: Ẩn biểu đồ chính, chỉ tập trung hiển thị hàng thẻ KPI chất lượng cao cùng bảng tóm tắt số liệu.
            if len(df) == 1:
                is_single_pct = (
                    len(measure_cols) == 1
                    and any(k in str(measure_cols[0]).lower() for k in ["percent", "ratio", "rate", "tỷ lệ", "phan_tram", "%"])
                    and not any(k in str(measure_cols[0]).lower() for k in ["revenue", "sales", "amount", "salary", "lương", "boxes", "hộp"])
                )
                is_same_unit_benchmark = False
                if len(measure_cols) == 2:
                    m1_low = str(measure_cols[0]).lower()
                    m2_low = str(measure_cols[1]).lower()
                    is_both_sal = any(k in m1_low for k in ["salary", "lương"]) and any(k in m2_low for k in ["salary", "lương"])
                    is_both_rev = any(k in m1_low for k in ["revenue", "sales", "amount"]) and any(k in m2_low for k in ["revenue", "sales", "amount"])
                    is_both_boxes = any(k in m1_low for k in ["boxes", "box", "hộp"]) and any(k in m2_low for k in ["boxes", "box", "hộp"])
                    if (is_both_sal or is_both_rev or is_both_boxes) and ("team" in m1_low or "team" in m2_low or "avg" in m1_low or "avg" in m2_low):
                        is_same_unit_benchmark = True

                is_team_flagship = any("flagship" in c.lower() or "chủ lực" in c.lower() for c in (label_cols + list(df.columns))) and any("team" in c.lower() for c in (label_cols + list(df.columns)))

                if is_single_pct:
                    chosen = "Pie"
                elif is_same_unit_benchmark or is_team_flagship:
                    chosen = "Bar"
                else:
                    return None

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
            pct_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["percent", "percentage", "pct", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "phan_tram", "share", "ratio", "rate"])]
            has_single_pct_col = len(pct_cols) == 1
            uq_low = (user_query or "").lower()
            user_asked_pct = any(k in uq_low for k in [
                "tỷ lệ", "tỉ lệ", "phần trăm", "percent", "percentage", "pct", "%", 
                "share", "cơ cấu", "tỉ trọng", "tỷ trọng", "đóng góp"
            ])
            non_pct_cols = [c for c in measure_cols if c not in pct_cols]
            is_top_ranking = any(k in uq_low for k in ["top", "cao nhất", "thấp nhất", "lâu nhất", "xếp hạng", "danh sách", "liệt kê"])

            # Kiểm tra xem cột phần trăm có tổng xấp xỉ 100% (cơ cấu thành phần khép kín)
            pct_sum_approx_100 = False
            if has_single_pct_col and 2 <= len(df) <= 10:
                try:
                    s_val = float(pd.to_numeric(df[pct_cols[0]], errors="coerce").sum())
                    if abs(s_val - 100.0) <= 2.5:
                        pct_sum_approx_100 = True
                except Exception:
                    pass

            is_distribution_breakdown = (
                (
                    (len(measure_cols) == 1 and (user_asked_pct or (has_single_pct_col and not non_pct_cols)))
                    or (pct_sum_approx_100 and (user_asked_pct or has_single_pct_col))
                )
                and (2 <= len(df) <= 10)
                and (len(pct_cols) <= 1)
                and (not time_col or n_time <= 1)
                and not is_individual_entity
                and not is_top_ranking
                and not (len(measure_cols) == 1 and any(k in str(measure_cols[0]).lower() for k in ["rate", "thăng chức", "promotion"]))
                and not (len(measure_cols) == 1 and any(k in str(measure_cols[0]).lower() for k in ["salary", "lương", "thu nhập", "wage", "pay"]))
            )

            is_gender_compare = (
                any(k in uq_low for k in ["so sánh", "compare", "nam", "nữ", "giới tính", "gender"])
                and any(any(k in str(c).lower() for k in ["male", "nam"]) for c in measure_cols)
                and any(any(k in str(c).lower() for k in ["female", "nu", "nữ"]) for c in measure_cols)
            )
            is_multi_measure_compare = (
                any(k in uq_low for k in ["so sánh", "compare", "đối chiếu"])
                and len(measure_cols) >= 2
                and n_time <= 10
            )

            if is_distribution_breakdown:
                chosen = "Pie"
            elif is_individual_entity and measure_cols:
                if is_top_ranking and len(df) <= 15 and len(measure_cols) == 1:
                    chosen = "Bar Ngang"
                else:
                    chosen = "Bar"
            elif (is_gender_compare or is_multi_measure_compare) and measure_cols:
                chosen = "Bar"
            elif time_col and measure_cols and n_time > 1:
                chosen = "Line"
            elif len(df) == 1 and measure_cols and any(k in str(measure_cols[0]).lower() for k in ["percent", "ratio", "rate", "tỷ lệ", "phan_tram", "%"]):
                chosen = "Pie"
            elif measure_cols:
                chosen = "Bar"
            elif len(measure_cols) >= 2:
                chosen = "Scatter"
            else:
                # Kiểm tra nếu dataframe chỉ có cột danh mục / chuỗi (không có cột số)
                # Nhưng có ít nhất 1 cột có các giá trị lặp lại (1 < nunique < len)
                # -> Tự động tổng hợp đếm tần suất (Frequency count) để vẽ biểu đồ
                cat_candidates = [c for c in df.columns if not is_id_like(c)]
                is_anti_join_chart = any(k in (user_query or "").lower() for k in ["chưa từng", "chưa bao giờ", "không bán", "never", "chưa bán"])
                for c in cat_candidates:
                    n_unq = df[c].nunique(dropna=True)
                    if 1 < n_unq < len(df):
                        counts_df = df[c].replace("", "Chưa phân đội").value_counts().reset_index()
                        count_col_name = "Số lượng nhân sự" if any(k in (user_query or "").lower() for k in ["nhân viên", "nhân sự", "salesperson", "người"]) else "Số lượng đối tượng"
                        counts_df.columns = [c, count_col_name]
                        if is_anti_join_chart:
                            st.caption(f"ℹ️ Phân bổ nhân sự chưa từng phát sinh doanh số theo `{c}`.")
                        else:
                            st.caption(f"ℹ️ Dữ liệu dạng danh mục — tự động tổng hợp số lượng bản ghi theo `{c}` để trực quan hóa.")
                        return render_smart_chart(counts_df, chart_override="Bar", turn_id=f"{turn_id}_freq", user_query=user_query)

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

        # Xác định cột phân nhóm màu sắc cho Line/Area (ví dụ: phân loại theo Quốc Gia, Team, Sản Phẩm...)
        # CHÚ Ý QUAN TRỌNG: time_color_col TUYỆT ĐỐI KHÔNG ĐƯỢC TRÙNG VỚI time_col
        time_color_col = None
        if chosen in ("Line", "Area") and label_cols:
            other_labels = [c for c in label_cols if c != time_col]
            if other_labels:
                candidate_col, candidate_series, _ = pick_label_column(df, other_labels)
                if candidate_col and candidate_col != time_col:
                    if candidate_col not in df.columns and candidate_series is not None:
                        df = df.copy()
                        df[candidate_col] = candidate_series.values
                    if candidate_col in df.columns and 1 < df[candidate_col].nunique(dropna=True) <= 25:
                        time_color_col = candidate_col

        if chosen == "Line" and time_col and measure_cols:
            sorted_df = df.sort_values([time_color_col, time_col]) if time_color_col else df.sort_values(time_col)
            n_time_points = sorted_df[time_col].nunique(dropna=True)
            tick_angle = 0 if n_time_points <= 20 else -45

            if time_color_col:
                # Nếu có nhiều chỉ số (như P&L gồm Doanh Thu, Chi Phí, Lợi Nhuận, Tỷ Suất LN):
                if len(measure_cols) == 1:
                    active_measure = measure_cols[0]
                else:
                    uq_low = (user_query or "").lower()
                    target_m = None
                    if any(k in uq_low for k in ["lãi", "lỗ", "lợi nhuận", "profit", "net profit", "net_profit"]):
                        p_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["lợi nhuận", "profit", "lãi", "netprofit", "net_profit"]) and not any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất", "%"])]
                        if p_cols:
                            target_m = p_cols[0]
                    elif any(k in uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%", "biên lợi nhuận"]):
                        m_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất", "%"])]
                        if m_cols:
                            target_m = m_cols[0]
                    elif any(k in uq_low for k in ["chi phí", "giá vốn", "cost", "cogs"]):
                        c_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["chi phí", "cost", "giá vốn", "cogs"])]
                        if c_cols:
                            target_m = c_cols[0]
                    elif any(k in uq_low for k in ["hộp", "thùng", "boxes"]):
                        b_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["boxes", "hộp", "thùng"])]
                        if b_cols:
                            target_m = b_cols[0]

                    if not target_m:
                        p_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["lợi nhuận", "profit"]) and not any(k in str(c).lower() for k in ["margin", "tỷ suất", "%"])]
                        if p_cols:
                            target_m = p_cols[0]
                        else:
                            s_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["doanh thu", "sales", "amount"])]
                            target_m = s_cols[0] if s_cols else measure_cols[0]

                    options = [format_col_title(c) for c in measure_cols]
                    def_idx = measure_cols.index(target_m) if target_m in measure_cols else 0
                    sel_title = st.selectbox(
                        "Chọn chỉ số hiển thị trên biểu đồ xu hướng:" if not is_en else "Select metric to visualize:",
                        options=options,
                        index=def_idx,
                        key=f"metric_select_{turn_id}"
                    )
                    title_to_c = {format_col_title(c): c for c in measure_cols}
                    active_measure = title_to_c.get(sel_title, target_m)

                clean_m = format_col_title(active_measure)
                clean_time = format_col_title(time_col)
                clean_group = format_col_title(time_color_col)
                fig = px.line(
                    sorted_df,
                    x=time_col,
                    y=active_measure,
                    color=time_color_col,
                    markers=True,
                    title=f"Xu hướng {clean_m} theo {clean_time} (Phân loại theo {clean_group})",
                    template="plotly_white"
                )
                m_low = str(active_measure).lower()
                is_pct = any(k in m_low for k in ["margin", "tỷ suất", "tỉ suất", "%", "pct", "percent"])
                is_curr = (not is_pct) and any(k in m_low for k in ["sales", "amount", "salary", "budget", "revenue", "lương", "doanh", "lợi nhuận", "profit", "chi phí", "cost", "$"])
                if is_pct:
                    fig.update_traces(
                        line=dict(width=2.5),
                        marker=dict(size=7),
                        connectgaps=True,
                        hovertemplate=f"<b>%{{fullData.name}}</b><br>{clean_time}: %{{x}}<br>{clean_m}: %{{y:,.2f}}%<extra></extra>"
                    )
                else:
                    curr_sym = "$" if is_curr else ""
                    fig.update_traces(
                        line=dict(width=2.5),
                        marker=dict(size=7),
                        connectgaps=True,
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
                    line=dict(width=3, color="#0068FF"),
                    marker=dict(size=8, color="#0068FF")
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
                height=520,
                margin=dict(l=30, r=30, t=50, b=60)
            )

        elif chosen == "Area" and time_col and measure_cols:
            sorted_df = df.sort_values([time_color_col, time_col]) if time_color_col else df.sort_values(time_col)
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
            # 0. Trường hợp đặc biệt: Biểu đồ Pareto kết hợp 2 trục Y (Dual-Axis Pareto Combo Chart)
            cum_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["cumulative", "tích lũy", "tich_luy"])]
            main_meas_cols = [c for c in measure_cols if c not in cum_cols and not any(k in str(c).lower() for k in ["pct", "percent", "tỷ lệ", "tỉ lệ", "%"])]
            if cum_cols and main_meas_cols and label_cols:
                cum_col = cum_cols[0]
                val_col = main_meas_cols[0]
                lbl_col = label_cols[0]
                plot_df = df.copy()

                if len(plot_df) > 30:
                    plot_df = plot_df.head(30)

                tick_angle = 0 if len(plot_df) <= 8 else -35

                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_trace(
                    go.Bar(
                        x=plot_df[lbl_col],
                        y=plot_df[val_col],
                        name=format_col_title(val_col),
                        marker_color="#0068FF",
                        text=plot_df[val_col],
                        texttemplate="$%{text:,.0f}" if any(k in val_col.lower() for k in ["sales", "salary", "amount", "budget"]) else "%{text:,.0f}",
                        textposition="outside"
                    ),
                    secondary_y=False
                )
                fig.add_trace(
                    go.Scatter(
                        x=plot_df[lbl_col],
                        y=plot_df[cum_col],
                        name=format_col_title(cum_col),
                        mode="lines+markers+text",
                        marker=dict(size=8, color="#D97706"),
                        line=dict(width=3, color="#D97706"),
                        text=plot_df[cum_col],
                        texttemplate="%{text:.1f}%",
                        textposition="top center"
                    ),
                    secondary_y=True
                )
                fig.add_hline(
                    y=80,
                    line_dash="dash",
                    line_color="#EF4444",
                    annotation_text="Ngưỡng 80% Pareto",
                    annotation_position="bottom right",
                    secondary_y=True
                )
                fig.update_layout(
                    title=f"📊 Biểu Đồ Phân Tích Pareto 80/20: {format_col_title(val_col)} & {format_col_title(cum_col)} theo {format_col_title(lbl_col)}",
                    template="plotly_white",
                    xaxis=dict(type="category", tickangle=tick_angle, automargin=True, title=format_col_title(lbl_col)),
                    yaxis=dict(title=format_col_title(val_col), tickprefix="$" if any(k in val_col.lower() for k in ["sales", "salary", "amount", "budget"]) else ""),
                    yaxis2=dict(title=format_col_title(cum_col), ticksuffix="%", range=[0, 105], showgrid=False),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=40, r=40, t=60, b=85 if tick_angle != 0 else 50)
                )
                st.plotly_chart(fig, use_container_width=True)
                return fig

            # 1. Trường hợp đặc biệt: 1 dòng so sánh nhiều chỉ số (VD: Cá nhân vs Toàn đội / Benchmark)
            if len(df) == 1 and len(measure_cols) >= 2:
                entity_name = None
                if label_cols:
                    for c in label_cols:
                        if any(k in c.lower() for k in ["title", "chức danh", "job", "dept", "phòng", "department", "salesperson", "nhân viên", "employee", "people", "name", "tên", "group", "khối", "product", "sản phẩm", "item", "team", "đội ngũ", "country", "geo", "quốc gia", "thị trường"]):
                            entity_name = str(df[c].iloc[0])
                            break

                comp_labels = []
                comp_values = []
                for m in measure_cols:
                    try:
                        val_num = float(df[m].iloc[0])
                    except Exception:
                        val_num = 0.0

                    m_low = m.lower()
                    formatted_name = format_col_title(m)
                    if any(k in m_low for k in ["team_total", "teamtotal", "toàn đội"]) or ("team" in m_low and any(k in m_low for k in ["sales", "boxes", "amount"])):
                        comp_labels.append(f"Toàn đội ({formatted_name})")
                    elif entity_name and any(k in m_low for k in ["sold", "amount", "boxes", "sales", "qty", "hộp", "tiền"]) and not any(k in m_low for k in ["price", "giá"]):
                        comp_labels.append(f"{entity_name} ({formatted_name})")
                    else:
                        comp_labels.append(formatted_name)
                    comp_values.append(val_num)

                comp_df = pd.DataFrame({
                    "Chỉ số So sánh": comp_labels,
                    "Giá trị": comp_values
                })

                is_spread_chart = any("spread" in m.lower() or "chênh lệch" in m.lower() or "biên độ" in m.lower() or "dao động" in m.lower() for m in measure_cols)
                is_price_chart = any(k in "".join(measure_cols).lower() for k in ["price", "giá", "per_box", "cost_per_box", "avgprice"])
                is_team_flagship_chart = any("flagship" in c.lower() or "chủ lực" in c.lower() for c in (label_cols + list(df.columns))) and any("team" in c.lower() for c in (label_cols + list(df.columns)))
                is_gte_query = any(k in (user_query or "").lower() for k in ["từ", "trở lên", "ít nhất", "tối thiểu", ">="])
                is_large_order_chart = any("largeorder" in c.lower() for c in (label_cols + list(df.columns))) or (
                    any(k in (user_query or "").lower() for k in ["đơn hàng", "giao dịch", "order", "đơn"])
                    and any(k in (user_query or "").lower() for k in ["trên", "hơn", "vượt", ">", "từ", "trở lên", ">=", "ít nhất", "tối thiểu"])
                    and any(k in (user_query or "").lower() for k in ["hộp", "boxes", "1000", "1,000"])
                )
                is_unit_economics_chart = any(k in "".join(measure_cols).lower() for k in ["avgprice", "priceperbox", "avg_price"]) or (
                    any(k in (user_query or "").lower() for k in ["mỗi hộp", "từng hộp", "giá bán trung bình", "đơn giá trung bình"])
                    and any(k in (user_query or "").lower() for k in ["tiền", "giá", "mang về", "bao nhiêu"])
                )

                if is_large_order_chart:
                    sym = "≥" if is_gte_query else ">"
                    title_prefix = f"📊 Thống Kê Phân Khúc Đơn Hàng Lớn ({sym}1,000 Hộp) ("
                elif is_unit_economics_chart:
                    title_prefix = f"📊 Hiệu Quả Định Giá & Doanh Thu: {entity_name} (" if entity_name else "📊 Hiệu Quả Định Giá & Doanh Thu ("
                elif is_team_flagship_chart:
                    t_val = next((str(df[c].iloc[0]) for c in label_cols if "team" in c.lower()), "Team")
                    p_val = next((str(df[c].iloc[0]) for c in label_cols if any(k in c.lower() for k in ["flagship", "product", "sản phẩm"])), "")
                    title_prefix = f"📊 Phân Tích Đội Ngũ & Sản Phẩm Chủ Lực: Team {t_val}" + (f" - {p_val} (" if p_val else " (")
                elif entity_name and is_spread_chart:
                    if is_price_chart:
                        title_prefix = f"📊 Phân Tích Biên Độ Giá Bán: {entity_name} ("
                    else:
                        title_prefix = f"📊 Phân Tích Chênh Lệch Lương: {entity_name} ("
                elif entity_name:
                    title_prefix = f"📊 Biểu đồ Phân tích Chỉ số: {entity_name} ("
                else:
                    title_prefix = "📊 Biểu đồ So sánh Chỉ số: ("

                fig = px.bar(
                    comp_df,
                    x="Chỉ số So sánh",
                    y="Giá trị",
                    color="Chỉ số So sánh",
                    text="Giá trị",
                    title=title_prefix + (" vs ".join(comp_labels)) + ")",
                    template="plotly_white"
                )
                if is_price_chart:
                    txt_tmpl = "$%{text:,.2f}"
                elif any(k in "".join(measure_cols).lower() for k in ["salary", "lương", "spread", "chênh lệch", "amount", "sales", "tiền"]):
                    txt_tmpl = "$%{text:,.0f}"
                else:
                    txt_tmpl = "%{text:,.0f}"
                fig.update_traces(texttemplate=txt_tmpl, textposition='outside')
                fig.update_layout(
                    xaxis=dict(type="category", tickangle=0, automargin=True),
                    margin=dict(l=20, r=20, t=50, b=50),
                    showlegend=False
                )

            elif label_cols or time_col:
                effective_label_cols = label_cols if label_cols else ([time_col] if time_col else [])

                # Trường hợp đặc biệt: So sánh Quản lý vs Cấp dưới theo từng phòng ban
                # BẮT BUỘC ưu tiên chọn 'Department' làm trục X, không để ManagerName chiếm trục X rồi biến Department thành color_col
                is_mgr_sub_context = (
                    any(any(k in c.lower() for k in ["managersalary", "manager_salary", "quản lý", "trưởng phòng"]) for c in (measure_cols + list(df.columns)))
                    and any(any(k in c.lower() for k in ["subordinate", "cấp dưới"]) for c in (measure_cols + list(df.columns)))
                )
                dept_label_cand = [c for c in effective_label_cols if any(k in c.lower() for k in ["dept", "phòng ban", "phong_ban", "department"])]
                if is_mgr_sub_context and dept_label_cand:
                    label_name = dept_label_cand[0]
                    label_series = df[label_name].astype(str)
                    consumed_cols = [label_name]
                else:
                    label_name, label_series, consumed_cols = pick_label_column(df, effective_label_cols)

                if label_name is None:
                    st.info("Không tìm thấy cột phù hợp để làm nhãn trục X.")
                    return None

                plot_df = df.copy()
                plot_df[label_name] = label_series.values

                n_unique_labels = plot_df[label_name].nunique(dropna=True)
                total_rows = len(plot_df)

                color_col = None
                if not is_mgr_sub_context and total_rows > 1:
                    candidate_color_cols = [
                        c for c in label_cols
                        if c not in consumed_cols and c in plot_df.columns and not is_id_like(c)
                    ]
                    if candidate_color_cols:
                        cand = candidate_color_cols[0]
                        if plot_df[cand].nunique(dropna=True) <= 20:
                            color_col = cand

                # Không tự ý rút gọn measure_cols nếu đang trong bài toán so sánh nhiều biến số (như Manager vs Subordinates, Male vs Female, hoặc query có 'so sánh')
                is_direct_comparison = (
                    is_mgr_sub_context
                    or any(k in (user_query or "").lower() for k in ["so sánh", "đối chiếu", "compare", "vs"])
                    or any(any(m in c.lower() for m in ["male", "female", "nam", "nữ", "manager", "subordinate", "cấp dưới"]) for c in measure_cols)
                )

                zero_var_pivot_info = None
                # Nếu có cột phân nhóm (DepartmentGroup) và người dùng hỏi so sánh một chỉ số cụ thể (VD: Lương, Tăng lương),
                # ưu tiên vẽ chỉ số đó phân nhóm theo color_col thay vì vẽ gộp nhiều chỉ số khác thang đo
                if color_col and len(measure_cols) >= 2 and not is_direct_comparison:
                    uq_low = (user_query or "").lower()
                    user_asked_raises = any(k in uq_low for k in ["tăng lương", "lần tăng", "số lần", "được tăng"])
                    user_asked_salary = any(k in uq_low for k in ["lương", "salary", "thu nhập"]) and not user_asked_raises
                    user_asked_headcount = any(k in uq_low for k in ["quy mô", "headcount", "số lượng nhân sự", "số nhân sự", "số lượng nhân viên"])
                    if user_asked_raises:
                        raises_c = [c for c in measure_cols if any(k in c.lower() for k in ["raisecount", "raise_count", "numberofincreases", "salaryincreases", "salary_increases", "lần tăng", "số lần", "raises", "num_raises"])]
                        if raises_c:
                            # KIỂM TRA PHƯƠNG SAI (VARIANCE CHECK):
                            # Nếu tất cả đối tượng đều có cùng số lần tăng lương (variance = 0),
                            # vẽ biểu đồ cho đại lượng này là vô nghĩa (Visual Noise).
                            # Chuyển trục Y sang Mức lương hiện tại ($) để thể hiện sự chênh lệch rõ ràng!
                            sal_c = [c for c in measure_cols if any(k in c.lower() for k in ["salary", "lương", "thu nhập"])]
                            if plot_df[raises_c[0]].nunique() == 1 and sal_c and plot_df[sal_c[0]].nunique() > 1:
                                zero_var_pivot_info = {
                                    "orig_col": raises_c[0],
                                    "orig_val": plot_df[raises_c[0]].iloc[0],
                                    "pivot_col": sal_c[0]
                                }
                                measure_cols = [sal_c[0]]
                            else:
                                measure_cols = [raises_c[0]]
                    elif user_asked_salary and not user_asked_headcount:
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
                    user_asked_pnl = any(k in uq_low for k in [
                        "lãi", "lỗ", "lãi, lỗ", "lãi lỗ", "chi phí", "cost", "giá vốn", "cogs", 
                        "lợi nhuận ròng", "net profit", "kết quả kinh doanh", "p&l", "pnl"
                    ]) or (any(k in uq_low for k in ["doanh thu"]) and any(k in uq_low for k in ["chi phí", "giá vốn", "lợi nhuận"]))
                    user_asked_efficiency = any(k in uq_low for k in [
                        "hiệu quả", "efficiency", "effectiveness", "năng suất", 
                        "giá trị trung bình", "trung bình mỗi đơn", "trung bình mỗi hộp", 
                        "order value", "per box", "per order", "aov", "performance", "profit per box",
                        "lợi nhuận", "profit", "margin", "tỷ suất", "tỉ suất", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"
                    ]) and not user_asked_pnl

                    # Tìm các cột tiền tệ P&L (Doanh thu, Chi phí, Lợi nhuận)
                    monetary_pnl_cols = [c for c in measure_cols if any(k in c.lower() for k in [
                        "doanh thu", "sales", "revenue", "totalsales", "total_sales", "chi phí", "cost", "giá vốn", "cogs", "totalcost", "lợi nhuận", "profit", "lãi"
                    ]) and not any(k in c.lower() for k in ["margin", "tỷ suất", "tỉ suất", "%", "per box", "perbox", "mỗi hộp"])]

                    # Tìm các cột đo lường hiệu quả (Efficiency / Average / Margin / Profit) - LOẠI TRỪ các cột chi phí/giá vốn đơn thuần (Cost_per_box)
                    eff_cols = [c for c in measure_cols if (any(k in c.lower() for k in [
                        "avg", "ordervalue", "order_value", "profit", "margin", "lợi nhuận", "trung bình", "hiệu quả", "revenueperbox", "revenue_per_box"
                    ]) or any(k in c.lower() for k in ["perbox", "per_box"])) and not any(k in c.lower() for k in ["cost", "giá vốn", "gia_von"])]

                    # Tìm các cặp số lượng nhân sự Nam - Nữ tuyệt đối
                    male_emp_cols = [c for c in non_pct_cols if any(k in c.lower() for k in ["maleemployees", "male_emp", "malemanagers", "male", "nam"]) and not any(k in c.lower() for k in ["female", "nu", "nữ", "department"])]
                    female_emp_cols = [c for c in non_pct_cols if any(k in c.lower() for k in ["femaleemployees", "female_emp", "femalemanagers", "female", "nu", "nữ"])]

                    # Nếu không có cột số lượng Nam/Nữ nhưng có cột Tổng nhân sự và Tỷ lệ Nam/Nữ:
                    total_emp_col_cands = [c for c in non_pct_cols if any(k in c.lower() for k in ["totalemployees", "total_emp", "headcount", "tổng số", "total", "slngnhnvin", "count"]) and not any(k in c.lower() for k in ["male", "female", "nam", "nữ"])]
                    male_pct_cands = [c for c in pct_cols if any(k in c.lower() for k in ["male", "nam"]) and not any(k in c.lower() for k in ["female", "nu", "nữ", "department"])]
                    female_pct_cands = [c for c in pct_cols if any(k in c.lower() for k in ["female", "nu", "nữ"])]

                    if (not male_emp_cols or not female_emp_cols) and total_emp_col_cands and male_pct_cands and female_pct_cands:
                        tot_col_use = total_emp_col_cands[0]
                        m_p_col = male_pct_cands[0]
                        f_p_col = female_pct_cands[0]
                        plot_df["MaleEmployees"] = (plot_df[m_p_col] * plot_df[tot_col_use] / 100.0).round()
                        plot_df["FemaleEmployees"] = (plot_df[f_p_col] * plot_df[tot_col_use] / 100.0).round()
                        male_emp_cols = ["MaleEmployees"]
                        female_emp_cols = ["FemaleEmployees"]

                    # Nếu có cặp số lượng Nam/Nữ thực tế (hoặc vừa được tính từ Tổng * %):
                    is_pure_pct_only = any(k in uq_low for k in ["chỉ xem tỷ lệ", "chỉ xem phần trăm", "chỉ tỷ lệ"])
                    if male_emp_cols and female_emp_cols and not is_pure_pct_only:
                        active_measures = [male_emp_cols[0], female_emp_cols[0]]
                        chart_title = f"Quy mô & Cơ cấu Giới tính theo {format_col_title(label_name)} (Stacked Bar)"
                    elif user_asked_pnl and len(monetary_pnl_cols) >= 2:
                        active_measures = monetary_pnl_cols
                        chart_title = f"Báo cáo Doanh Thu - Chi Phí - Lợi Nhuận theo {format_col_title(label_name)} (Grouped Bar)"
                    # Ưu tiên vẽ Dual Axis khi người dùng hỏi so sánh Doanh số ($) và Số lượng hộp bán ra giữa các Team / đối tượng kinh doanh
                    elif any(k in uq_low for k in ["doanh số", "doanh thu", "sales", "tiền"]) and any(k in uq_low for k in ["hộp", "thùng", "boxes", "số lượng"]) and [c for c in non_pct_cols if any(k in c.lower() for k in ["totalsales", "sales", "amount", "revenue", "doanh thu", "doanh so"])] and [c for c in non_pct_cols if any(k in c.lower() for k in ["totalboxes", "boxes", "hộp", "thùng", "sản lượng"])]:
                        sales_c = [c for c in non_pct_cols if any(k in c.lower() for k in ["totalsales", "sales", "amount", "revenue", "doanh thu", "doanh so"])][0]
                        boxes_c = [c for c in non_pct_cols if any(k in c.lower() for k in ["totalboxes", "boxes", "hộp", "thùng", "sản lượng"])][0]

                        fig = make_subplots(specs=[[{"secondary_y": True}]])
                        fig.add_trace(
                            go.Bar(
                                x=plot_df[label_name],
                                y=plot_df[sales_c],
                                name=format_col_title(sales_c),
                                marker_color="#1E40AF",
                                text=plot_df[sales_c],
                                texttemplate="$%{text:,.0f}",
                                textposition="inside",
                                insidetextanchor="middle",
                                textfont=dict(color="#FFFFFF", size=11, family="sans-serif"),
                            ),
                            secondary_y=False,
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=plot_df[label_name],
                                y=plot_df[boxes_c],
                                name=format_col_title(boxes_c),
                                mode="lines+markers+text",
                                marker=dict(size=9, color="#D97706"),
                                line=dict(width=3, color="#D97706"),
                                text=plot_df[boxes_c],
                                texttemplate="%{text:,.0f} hộp",
                                textposition="top center",
                                textfont=dict(color="#B45309", size=11, family="sans-serif"),
                            ),
                            secondary_y=True,
                        )
                        try:
                            max_s = float(pd.to_numeric(plot_df[sales_c], errors="coerce").max() or 1000)
                        except Exception:
                            max_s = 1000.0
                        try:
                            max_b = float(pd.to_numeric(plot_df[boxes_c], errors="coerce").max() or 100)
                        except Exception:
                            max_b = 100.0

                        sales_title = format_col_title(sales_c).replace("($)", "").strip()
                        boxes_title = format_col_title(boxes_c).replace("(Hộp)", "").strip()
                        fig.update_layout(
                            title=f"Biểu đồ Kết Hợp (Dual Axis): {sales_title} ($) & {boxes_title} (Hộp) theo {format_col_title(label_name)}",
                            template="plotly_white",
                            xaxis=dict(type="category", automargin=True, title=format_col_title(label_name)),
                            yaxis=dict(title=format_col_title(sales_c), tickprefix="$", range=[0, max_s * 1.18]),
                            yaxis2=dict(title=format_col_title(boxes_c), ticksuffix=" hộp", range=[0, max_b * 1.40], showgrid=False),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            margin=dict(l=40, r=40, t=60, b=50)
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        return fig
                    # Ưu tiên vẽ Dual Axis khi có Tổng Quỹ Lương ($) và Lương Trung Bình ($) hoặc Quy Mô Nhân Sự (Người)
                    # Giúp hiển thị trực quan cả quy mô quỹ lương lẫn mức thu nhập bình quân/nhân sự mà không bị lệch thang đo (Visual Scale Contradiction)
                    elif (
                        [c for c in non_pct_cols if any(k in c.lower() for k in ["totalpayroll", "total_payroll", "totalsalarybudget", "total_salary_budget", "totalsalary", "total_salary", "quỹ lương", "tổng quỹ lương", "salarybudget", "salary_budget", "deptsalary", "dept_salary", "tổng chi phí lương", "totalcompanysalary", "total_company_salary", "companytotalsalary", "tổng quỹ"]) and not any(k in c.lower() for k in ["avg", "trung bình", "median", "mean"])]
                        and (
                            [c for c in non_pct_cols if any(k in c.lower() for k in ["avgsalary", "avg_salary", "averagesalary", "currentavgsalary", "current_avg_salary", "lương trung bình", "trung bình", "titleavgsalary", "title_avg_salary"]) and not any(k in c.lower() for k in ["totalpayroll", "total_payroll", "totalsalarybudget", "total_salary_budget", "totalsalary", "total_salary", "quỹ lương", "tổng quỹ lương", "salarybudget", "salary_budget", "deptsalary", "dept_salary", "tổng chi phí lương"])]
                            or [c for c in non_pct_cols if any(k in c.lower() for k in ["headcount", "employeecount", "employee_count", "totalemployees", "total_employees", "số lượng nhân sự", "nhân sự", "quy mô", "total_emp"]) and not any(k in c.lower() for k in ["totalpayroll", "total_payroll", "totalsalarybudget", "total_salary_budget", "totalsalary", "total_salary", "quỹ lương", "tổng quỹ lương", "salarybudget", "salary_budget", "deptsalary", "dept_salary", "tổng chi phí lương"])]
                        )
                    ):
                        p_cands = [c for c in non_pct_cols if any(k in c.lower() for k in ["totalpayroll", "total_payroll", "totalsalarybudget", "total_salary_budget", "totalsalary", "total_salary", "quỹ lương", "tổng quỹ lương", "salarybudget", "salary_budget", "deptsalary", "dept_salary", "tổng chi phí lương", "totalcompanysalary", "total_company_salary", "companytotalsalary", "tổng quỹ"]) and not any(k in c.lower() for k in ["avg", "trung bình", "median", "mean"])]
                        a_cands = [c for c in non_pct_cols if any(k in c.lower() for k in ["avgsalary", "avg_salary", "averagesalary", "currentavgsalary", "current_avg_salary", "lương trung bình", "trung bình", "titleavgsalary", "title_avg_salary"]) and c not in p_cands]
                        h_cands = [c for c in non_pct_cols if any(k in c.lower() for k in ["headcount", "employeecount", "employee_count", "totalemployees", "total_employees", "số lượng nhân sự", "nhân sự", "quy mô", "total_emp"]) and c not in p_cands and c not in a_cands]

                        payroll_c = p_cands[0]
                        if a_cands:
                            secondary_c = a_cands[0]
                            is_sec_sal = True
                        else:
                            secondary_c = h_cands[0]
                            is_sec_sal = False

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

                        bar_texts = []
                        for v in plot_df[payroll_c]:
                            try:
                                val = float(v) if pd.notna(v) else 0.0
                            except Exception:
                                val = 0.0
                            if abs(val) >= 1_000_000_000:
                                bar_texts.append(f"${val / 1e9:,.2f}B")
                            elif abs(val) >= 1_000_000:
                                bar_texts.append(f"${val / 1e6:,.1f}M")
                            else:
                                bar_texts.append(f"${val:,.0f}")

                        hover_bars = [
                            f"<b>{r[label_name]}</b><br>{format_col_title(payroll_c)}: <b>${float(r[payroll_c]):,.0f}</b>"
                            for _, r in plot_df.iterrows()
                        ]

                        fig.add_trace(
                            go.Bar(
                                x=plot_df[label_name],
                                y=plot_df[payroll_c],
                                name=format_col_title(payroll_c),
                                marker_color="#1E40AF",
                                text=bar_texts,
                                textposition="inside" if len(plot_df) <= 12 else "outside",
                                textfont=dict(color="#FFFFFF" if len(plot_df) <= 12 else "#1E40AF", size=11, family="sans-serif"),
                                hovertext=hover_bars,
                                hovertemplate="%{hovertext}<extra></extra>",
                            ),
                            secondary_y=False
                        )

                        if is_sec_sal:
                            sec_texts = [f"${float(v):,.0f}" if pd.notna(v) else "N/A" for v in plot_df[secondary_c]]
                            hover_sec = [
                                f"<b>{r[label_name]}</b><br>{format_col_title(secondary_c)}: <b>${float(r[secondary_c]):,.0f}</b>"
                                for _, r in plot_df.iterrows()
                            ]
                            sec_name = format_col_title(secondary_c)
                            sec_axis_title = format_col_title(secondary_c)
                            sec_tickprefix = "$"
                            sec_ticksuffix = ""
                        else:
                            sec_texts = [f"{float(v):,.0f} ng" if pd.notna(v) else "N/A" for v in plot_df[secondary_c]]
                            hover_sec = [
                                f"<b>{r[label_name]}</b><br>{format_col_title(secondary_c)}: <b>{float(r[secondary_c]):,.0f} người</b>"
                                for _, r in plot_df.iterrows()
                            ]
                            sec_name = format_col_title(secondary_c)
                            sec_axis_title = format_col_title(secondary_c)
                            sec_tickprefix = ""
                            sec_ticksuffix = " ng"

                        fig.add_trace(
                            go.Scatter(
                                x=plot_df[label_name],
                                y=plot_df[secondary_c],
                                name=sec_name,
                                mode="lines+markers+text",
                                marker=dict(size=9, color="#D97706"),
                                line=dict(width=3, color="#D97706"),
                                text=sec_texts,
                                textposition="top center",
                                hovertext=hover_sec,
                                hovertemplate="%{hovertext}<extra></extra>",
                                textfont=dict(color="#B45309", size=11, family="sans-serif"),
                            ),
                            secondary_y=True
                        )

                        try:
                            max_p = float(pd.to_numeric(plot_df[payroll_c], errors="coerce").max() or 1000)
                        except Exception:
                            max_p = 1000.0
                        try:
                            max_s = float(pd.to_numeric(plot_df[secondary_c], errors="coerce").max() or 100)
                        except Exception:
                            max_s = 100.0

                        fig.update_layout(
                            title=f"Biểu đồ Kết Hợp (Dual Axis): {format_col_title(payroll_c)} & {format_col_title(secondary_c)} theo {format_col_title(label_name)}",
                            template="plotly_white",
                            xaxis=dict(type="category", tickangle=tick_angle, automargin=True, title=format_col_title(label_name)),
                            yaxis=dict(title=format_col_title(payroll_c), tickprefix="$", range=[0, max_p * 1.22]),
                            yaxis2=dict(title=sec_axis_title, tickprefix=sec_tickprefix, ticksuffix=sec_ticksuffix, range=[0, max_s * 1.35], showgrid=False),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            margin=dict(l=40, r=40, t=60, b=85 if tick_angle != 0 else 50)
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        return fig
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
                                    textposition="inside",
                                    insidetextanchor="middle",
                                    textfont=dict(color="#FFFFFF", size=11, family="sans-serif"),
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
                                    textfont=dict(color="#B45309", size=11, family="sans-serif"),
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
                                yaxis=dict(title=format_col_title(pct_col), ticksuffix="%", range=[0, max(100.0, max_pct * 1.18)]),
                                yaxis2=dict(title=format_col_title(non_pct_col), tickprefix="$", range=[0, max_non_pct * 1.40], showgrid=False),
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


                    # Ưu tiên vẽ Chênh lệch lương khi người dùng hỏi về khoảng cách / chênh lệch lương
                    user_asked_spread = any(k in uq_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa"]) and not any(k in uq_low for k in ["chuẩn", "stddev", "standard deviation", "phân tán"])
                    spread_meas = [c for c in non_pct_cols if any(k in c.lower() for k in ["salaryspread", "salary_spread", "spread", "chênh lệch", "gap", "diff"])]
                    sal_meas = [c for c in non_pct_cols if any(k in c.lower() for k in ["salary", "lương", "thu nhập", "payroll", "quỹ"]) and not any(k in c.lower() for k in ["diff", "chênh lệch", "gap", "spread"])]
                    user_asked_salary = any(k in uq_low for k in ["lương", "salary", "thu nhập", "payroll", "quỹ lương"]) and not any(k in uq_low for k in ["tỷ lệ tăng", "tỉ lệ tăng", "số lần"])
                    user_asked_payroll = any(k in uq_low for k in ["tổng quỹ lương", "quỹ lương", "tổng chi phí lương", "tổng lương", "payroll", "salary budget", "total salary", "ngân sách lương", "chi phí lương"])
                    user_asked_avg_salary = any(k in uq_low for k in ["lương trung bình", "trung bình", "thu nhập bình quân", "average salary", "avg salary"])
                    
                    user_asked_stddev = any(k in uq_low for k in ["độ lệch chuẩn", "stddev", "phân tán", "độ phân tán", "standard deviation"])
                    has_stddev_sal = [c for c in non_pct_cols if any(k in c.lower() for k in ["salarystddev", "salary_std_dev", "stddev", "độ lệch chuẩn"])]

                    payroll_cands_meas = [c for c in sal_meas if any(k in c.lower() for k in ["totalpayroll", "total_payroll", "totalsalarybudget", "total_salary_budget", "totalsalary", "total_salary", "quỹ lương", "tổng quỹ lương", "salarybudget", "salary_budget", "deptsalary", "dept_salary", "tổng chi phí lương", "totalcompanysalary", "total_company_salary", "companytotalsalary", "tổng quỹ"]) and not any(k in c.lower() for k in ["avg", "trung bình", "median", "mean"])]

                    if user_asked_stddev and has_stddev_sal:
                        has_avg_sal = [c for c in sal_meas if any(k in c.lower() for k in ["avg", "trung bình"])]
                        if has_avg_sal:
                            active_measures = [has_avg_sal[0], has_stddev_sal[0]]
                            chart_title = f"So Sánh Lương Trung Bình vs Độ Lệch Chuẩn Lương theo {format_col_title(label_name)} (Grouped Bar)"
                        else:
                            active_measures = [has_stddev_sal[0]]
                            chart_title = f"Độ Lệch Chuẩn Lương ($) theo {format_col_title(label_name)}"
                    elif user_asked_spread and spread_meas:
                        active_measures = [spread_meas[0]]
                        chart_title = f"Chênh Lệch Lương ($) theo {format_col_title(label_name)}"
                    # Ưu tiên vẽ Lương (TotalPayroll / AvgSalary / Salary) khi người dùng hỏi so sánh Lương
                    elif user_asked_salary and sal_meas:
                        has_male_sal = [c for c in sal_meas if any(k in c.lower() for k in ["male", "nam"]) and not any(k in c.lower() for k in ["female", "nu", "nữ"])]
                        has_female_sal = [c for c in sal_meas if any(k in c.lower() for k in ["female", "nu", "nữ"])]
                        has_mgr_sal = [c for c in sal_meas if any(k in c.lower() for k in ["managersalary", "manager_salary", "quản lý", "trưởng phòng"])]
                        has_sub_sal = [c for c in sal_meas if any(k in c.lower() for k in ["subordinate", "cấp dưới"])]
                        has_senior_sal = [c for c in sal_meas if any(k in c.lower() for k in ["senior", "ky_cuu", "kỳ cựu", "lâu năm"])]
                        has_newhire_sal = [c for c in sal_meas if any(k in c.lower() for k in ["newhire", "new_hire", "moi_vao", "mới vào", "mới", "newbie"])]

                        has_init_sal = [c for c in sal_meas if any(k in c.lower() for k in ["initial", "khởi điểm", "đầu tiên", "starting", "first"])]
                        has_curr_sal = [c for c in sal_meas if any(k in c.lower() for k in ["current", "hiện tại", "bây giờ"])]
                        has_title_avg_sal = [c for c in sal_meas if any(k in c.lower() for k in ["titleavg", "title_avg", "chức danh"])]

                        if has_curr_sal and has_title_avg_sal:
                            active_measures = [has_curr_sal[0], has_title_avg_sal[0]]
                            chart_title = f"So Sánh Lương Hiện Tại vs Lương TB Chức Danh theo {format_col_title(label_name)} (Grouped Bar)"
                        elif has_init_sal and has_curr_sal:
                            active_measures = [has_init_sal[0], has_curr_sal[0]]
                            chart_title = f"So Sánh Lương Khởi Điểm vs Lương Hiện Tại theo {format_col_title(label_name)} (Grouped Bar)"
                        elif has_male_sal and has_female_sal:
                            active_measures = [has_male_sal[0], has_female_sal[0]]
                            chart_title = f"So Sánh Mức Lương Trung Bình Nam vs Nữ theo {format_col_title(label_name)} (Grouped Bar)"
                        elif has_mgr_sal and has_sub_sal:
                            active_measures = [has_mgr_sal[0], has_sub_sal[0]]
                            is_avg_sub = any("avg" in c.lower() for c in has_sub_sal)
                            sub_name = "Lương TB Cấp Dưới" if is_avg_sub else "Lương Cấp Dưới Cao Nhất"
                            chart_title = f"So Sánh Lương Quản Lý vs {sub_name} theo {format_col_title(label_name)} (Grouped Bar)"
                        elif has_senior_sal and has_newhire_sal:
                            active_measures = [has_senior_sal[0], has_newhire_sal[0]]
                            chart_title = f"So Sánh Lương TB Kỳ Cựu (>5 năm) vs Mới Vào (<2 năm) theo {format_col_title(label_name)} (Grouped Bar)"
                        elif any(k in uq_low for k in ["so sánh", "đối chiếu", "compare", "vs"]) and len(sal_meas) >= 2:
                            active_measures = sal_meas[:2]
                            chart_title = f"So Sánh ({', '.join([format_col_title(c) for c in active_measures])}) theo {format_col_title(label_name)} (Grouped Bar)"
                        else:
                            avg_sal_c = [c for c in sal_meas if any(k in c.lower() for k in ["avg", "trung bình"])]
                            if user_asked_payroll and payroll_cands_meas:
                                chosen_sal = payroll_cands_meas[0]
                            elif user_asked_avg_salary and avg_sal_c:
                                chosen_sal = avg_sal_c[0]
                            elif payroll_cands_meas:
                                chosen_sal = payroll_cands_meas[0]
                            elif avg_sal_c:
                                chosen_sal = avg_sal_c[0]
                            else:
                                chosen_sal = sal_meas[0]
                            active_measures = [chosen_sal]
                            chart_title = f"{format_col_title(chosen_sal)} theo {format_col_title(label_name)}"
                    elif pct_cols and (user_asked_pct or not non_pct_cols):
                        active_measures = pct_cols
                        pct_labels = [format_col_title(c) for c in pct_cols]
                        chart_title = clean_chart_title(f"Tỷ Lệ ({', '.join(pct_labels)}) theo {format_col_title(label_name)}")
                    elif non_pct_cols:
                        # Ưu tiên các cột giá trị thực tế (lương thực, quy mô...) thay vì phần trăm ảo
                        clean_non_pct = [c for c in non_pct_cols if not any(k in c.lower() for k in ["total", "tổng", "count_all", "all"])] or non_pct_cols
                        clean_labels = [format_col_title(c) for c in clean_non_pct]
                        if len(clean_non_pct) >= 2:
                            active_measures = clean_non_pct
                            chart_title = clean_chart_title(f"So Sánh ({', '.join(clean_labels)}) theo {format_col_title(label_name)}")
                        else:
                            active_measures = clean_non_pct
                            chart_title = clean_chart_title(f"{clean_labels[0]} theo {format_col_title(label_name)}")
                    elif pct_cols:
                        active_measures = pct_cols
                        pct_labels = [format_col_title(c) for c in pct_cols]
                        chart_title = clean_chart_title(f"Tỷ Lệ ({', '.join(pct_labels)}) theo {format_col_title(label_name)}")
                    else:
                        active_measures = measure_cols
                        meas_labels = [format_col_title(c) for c in measure_cols]
                        chart_title = clean_chart_title(f"So Sánh Các Chỉ Số ({', '.join(meas_labels)}) theo {format_col_title(label_name)}")

                    # Kiểm tra độ tương thích về thang đo (tránh vẽ lương 150,000 chung trục với số lần 18)
                    if len(active_measures) >= 2:
                        numeric_ms = [m for m in active_measures if pd.api.types.is_numeric_dtype(plot_df[m])]
                        has_mgr_sal = [c for c in numeric_ms if any(k in c.lower() for k in ["managersalary", "manager_salary"])]
                        has_sub_sal = [c for c in numeric_ms if any(k in c.lower() for k in ["maxsubordinatesalary", "max_subordinate_salary", "subordinatesalary", "subordinate_salary"])]
                        has_india_sales = [c for c in numeric_ms if any(k in c.lower() for k in ["indiasales", "india_sales"])]
                        has_usa_sales = [c for c in numeric_ms if any(k in c.lower() for k in ["usasales", "usa_sales"])]

                        if has_mgr_sal and has_sub_sal:
                            active_measures = [has_mgr_sal[0], has_sub_sal[0]]
                            chart_title = f"So Sánh Lương Quản Lý vs Lương Cấp Dưới Cao Nhất theo {format_col_title(label_name)} (Grouped Bar)"
                        elif has_india_sales and has_usa_sales:
                            active_measures = [has_india_sales[0], has_usa_sales[0]]
                            chart_title = f"So Sánh Doanh Số Thị Trường Ấn Độ vs Mỹ theo {format_col_title(label_name)} (Grouped Bar)"
                        else:
                            max_vals = [float(plot_df[m].abs().max()) for m in numeric_ms if float(plot_df[m].abs().max()) > 0]
                            if len(max_vals) >= 2 and (max(max_vals) / min(max_vals)) > 20 and not user_asked_pnl:
                                if user_asked_payroll and any(c in numeric_ms for c in payroll_cands_meas):
                                    primary_m = [c for c in numeric_ms if c in payroll_cands_meas][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif user_asked_efficiency and any(c in numeric_ms for c in eff_cols):
                                    # Khi hỏi hiệu quả, ưu tiên chọn chỉ số hiệu quả (AvgOrderValue, ProfitMargin, ProfitPerBox...) thay vì rơi về TotalSales
                                    candidate_effs = [c for c in eff_cols if c in numeric_ms]
                                    if any(k in uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%"]) and any(any(k in c.lower() for k in ["margin", "tỷ suất", "tỉ suất"]) for c in candidate_effs):
                                        primary_m = [c for c in candidate_effs if any(k in c.lower() for k in ["margin", "tỷ suất", "tỉ suất"])][0]
                                    elif any(k in uq_low for k in ["mỗi hộp", "per box", "hộp", "đơn giá"]) and any(any(k in c.lower() for k in ["perbox", "per_box", "avgprice"]) for c in candidate_effs):
                                        primary_m = [c for c in candidate_effs if any(k in c.lower() for k in ["perbox", "per_box", "avgprice"])][0]
                                    else:
                                        primary_m = candidate_effs[0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif any(k in uq_low for k in ["tăng trưởng", "tốc độ", "mức tăng"]) and any(any(k in c.lower() for k in ["headcountgrowthratepct", "headcount_growth_rate", "growthratepct"]) for c in numeric_ms):
                                    primary_m = [c for c in numeric_ms if any(k in c.lower() for k in ["headcountgrowthratepct", "headcount_growth_rate", "growthratepct"])][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif any(k in uq_low for k in ["tăng trưởng", "tốc độ", "mức tăng", "tăng lương trung bình", "mỗi năm"]) and any(any(k in c.lower() for k in ["avgannualsalarygrowth", "annualgrowth", "growth"]) for c in numeric_ms):
                                    primary_m = [c for c in numeric_ms if any(k in c.lower() for k in ["avgannualsalarygrowth", "annualgrowth", "growth"])][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif any(k in uq_low for k in ["tăng lương", "lần tăng", "số lần", "được tăng"]) and any(any(k in c.lower() for k in ["raisecount", "raise_count", "numberofincreases", "salaryincreases", "số lần", "lần tăng"]) for c in numeric_ms):
                                    primary_m = [c for c in numeric_ms if any(k in c.lower() for k in ["raisecount", "raise_count", "numberofincreases", "salaryincreases", "số lần", "lần tăng"])][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif any(any(k in c.lower() for k in ["salarydeficit", "salary_deficit", "salarysurplus", "salary_surplus", "salarybelowavg"]) for c in numeric_ms):
                                    primary_m = [c for c in numeric_ms if any(k in c.lower() for k in ["salarydeficit", "salary_deficit", "salarysurplus", "salary_surplus", "salarybelowavg"])][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif any(k in uq_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa"]) and any(any(k in c.lower() for k in ["salaryspread", "salary_spread", "spread", "chênh lệch"]) for c in numeric_ms):
                                    primary_m = [c for c in numeric_ms if any(k in c.lower() for k in ["salaryspread", "salary_spread", "spread", "chênh lệch"])][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif (any(k in uq_low for k in ["mức lương", "lương", "salary"]) and any(k in uq_low for k in ["top", "cao nhất", "top 10%", "top %"])) and any(any(k in c.lower() for k in ["salary", "currentsalary", "lương"]) for c in numeric_ms):
                                    primary_m = [c for c in numeric_ms if any(k in c.lower() for k in ["salary", "currentsalary", "lương"])][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                elif any(k in uq_low for k in ["thâm niên", "tenure", "years of service", "cống hiến", "gắn bó"]) and any(any(k in c.lower() for k in ["yearsofservice", "years_of_service", "avgyears", "tenure"]) for c in numeric_ms):
                                    primary_m = [c for c in numeric_ms if any(k in c.lower() for k in ["yearsofservice", "years_of_service", "avgyears", "tenure"])][0]
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"
                                else:
                                    # Chênh lệch trên 20 lần: Ưu tiên cột có độ lệch chuẩn và giá trị lớn nhất (ví dụ CurrentSalary)
                                    primary_m = max(numeric_ms, key=lambda m: (float(plot_df[m].std() or 0), float(plot_df[m].max() or 0)))
                                    active_measures = [primary_m]
                                    chart_title = f"{format_col_title(primary_m)} theo {format_col_title(label_name)}"


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

                    # Tùy chỉnh màu sắc chuyên nghiệp cho các phân loại đặc thù (như Giới tính Nam / Nữ, Quản lý / Cấp dưới, P&L)
                    color_map = {}
                    for col in active_measures:
                        cl = col.lower()
                        if any(k in cl for k in ["female", "nu", "nữ", "women"]):
                            color_map[col] = "#EC4899"  # Hồng/Cam san hô hiện đại cho Nữ
                        elif any(k in cl for k in ["male", "nam", "men"]):
                            color_map[col] = "#0068FF"  # Xanh Zalo Blue hiện đại cho Nam
                        elif any(k in cl for k in ["managersalary", "manager_salary", "manager"]):
                            color_map[col] = "#0068FF"  # Xanh Zalo Blue cho Quản lý
                        elif any(k in cl for k in ["maxsubordinatesalary", "max_subordinate_salary", "subordinatesalary", "subordinateavgsalary", "subordinate_avg_salary", "avgsubordinatesalary", "subordinate", "cấp dưới"]):
                            color_map[col] = "#10B981"  # Xanh lá ngọc cho Nhân viên cấp dưới (nổi bật hơn)
                        elif any(k in cl for k in ["senior", "ky_cuu", "kỳ cựu", "lâu năm"]):
                            color_map[col] = "#0068FF"  # Xanh Zalo Blue cho Kỳ cựu
                        elif any(k in cl for k in ["newhire", "new_hire", "moi_vao", "mới vào", "mới"]):
                            color_map[col] = "#10B981"  # Xanh lá ngọc cho Nhân viên mới
                        elif any(k in cl for k in ["doanh thu", "sales", "revenue", "totalsales"]):
                            color_map[col] = "#0068FF"  # Xanh Zalo Blue cho Doanh Thu
                        elif any(k in cl for k in ["chi phí", "cost", "giá vốn", "cogs", "totalcost"]):
                            color_map[col] = "#F59E0B"  # Cam Amber cho Chi Phí
                        elif any(k in cl for k in ["lợi nhuận", "profit", "lãi"]):
                            color_map[col] = "#10B981"  # Xanh Ngọc Emerald cho Lợi Nhuận

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

                    is_mgr_sub_salary_comp = (
                        len(active_measures) == 2 and
                        any(any(k in c.lower() for k in ["manager", "quản lý"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["subordinate", "cấp dưới"]) for c in active_measures)
                    )

                    is_tenure_cohort_salary_comp = (
                        len(active_measures) == 2 and
                        any(any(k in c.lower() for k in ["senior", "ky_cuu", "kỳ cựu", "lâu năm"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["newhire", "new_hire", "moi_vao", "mới vào", "mới", "newbie"]) for c in active_measures)
                    )

                    is_stddev_salary_comp = (
                        len(active_measures) == 2 and
                        any(any(k in c.lower() for k in ["stddev", "salarystddev", "độ lệch chuẩn"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["avg", "currentavg", "trung bình"]) for c in active_measures)
                    )

                    is_pnl_comp = (
                        len(active_measures) >= 2 and
                        any(any(k in c.lower() for k in ["doanh thu", "sales", "revenue", "totalsales"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["chi phí", "cost", "giá vốn", "cogs", "totalcost"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["lợi nhuận", "profit", "lãi"]) for c in active_measures)
                    )

                    is_employee_title_salary_comp = (
                        len(active_measures) == 2 and
                        any(any(k in c.lower() for k in ["current", "hiện tại", "salary", "lương"]) and not any(k in c.lower() for k in ["titleavg", "chức danh", "surplus", "vượt", "stddev", "chuẩn"]) for c in active_measures) and
                        any(any(k in c.lower() for k in ["titleavg", "title_avg", "chức danh"]) for c in active_measures)
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

                    is_compare_query = any(k in (user_query or "").lower() for k in ["so sánh", "đối chiếu", "compare", "vs"])
                    barmode_val = "stack" if is_composition_100 else ("group" if is_compare_query else ("stack" if is_headcount_stack else "group"))
                    if is_composition_100:
                        meas_labels = [format_col_title(c) for c in active_measures]
                        chart_title = f"Cơ Cấu Tỷ Lệ ({', '.join(meas_labels)}) theo {format_col_title(label_name)} (100% Stacked Bar)"
                    elif is_headcount_stack:
                        chart_type = "Grouped Bar" if barmode_val == "group" else "Stacked Bar"
                        chart_title = f"So Sánh Số Lượng Nam vs Nữ theo {format_col_title(label_name)} ({chart_type})" if is_compare_query else f"Quy mô & Cơ cấu Giới tính theo {format_col_title(label_name)} (Stacked Bar)"
                    elif is_stddev_salary_comp:
                        chart_title = f"So Sánh Lương Trung Bình vs Độ Lệch Chuẩn Lương theo {format_col_title(label_name)} (Grouped Bar)"
                    elif is_employee_title_salary_comp:
                        chart_title = f"So Sánh Lương Hiện Tại vs Lương TB Chức Danh theo {format_col_title(label_name)} (Grouped Bar)"
                    elif any(any(k in c.lower() for k in ["initial", "khởi điểm", "đầu tiên"]) for c in active_measures) and any(any(k in c.lower() for k in ["current", "hiện tại"]) for c in active_measures):
                        chart_title = f"So Sánh Lương Khởi Điểm vs Lương Hiện Tại theo {format_col_title(label_name)} (Grouped Bar)"
                    elif is_gender_salary_comp:
                        chart_title = f"So Sánh Mức Lương Trung Bình Nam vs Nữ theo {format_col_title(label_name)} (Grouped Bar)"
                    elif is_mgr_sub_salary_comp:
                        is_sub_avg = any(any(k in c.lower() for k in ["avg", "trung bình", "tb"]) for c in active_measures) or any(k in (user_query or "").lower() for k in ["trung bình", "avg"])
                        sub_term = "Lương TB Cấp Dưới" if is_sub_avg else "Lương Cấp Dưới Cao Nhất"
                        chart_title = f"So Sánh Lương Quản Lý vs {sub_term} theo {format_col_title(label_name)} (Grouped Bar)"
                    elif is_tenure_cohort_salary_comp:
                        chart_title = f"So Sánh Lương TB Kỳ Cựu (>5 năm) vs Mới Vào (<2 năm) theo {format_col_title(label_name)} (Grouped Bar)"
                    elif is_headcount_salary_comp:
                        chart_title = f"So Sánh Quy Mô Nhân Sự & Mức Lương Trung Bình theo {format_col_title(label_name)} (Grouped Bar)"
                    elif any(any(k in c.lower() for k in ["indiasales", "india_sales"]) for c in active_measures) and any(any(k in c.lower() for k in ["usasales", "usa_sales"]) for c in active_measures):
                        chart_title = f"So Sánh Doanh Số Thị Trường Ấn Độ vs Mỹ theo {format_col_title(label_name)} (Grouped Bar)"

                    chart_title = clean_chart_title(chart_title)

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
                        "y": active_measures if len(active_measures) > 1 or not color_col else active_measures[0],
                        "barmode": barmode_val,
                        "title": chart_title,
                        "category_orders": {label_name: category_order},
                        "template": "plotly_white",
                    }
                    if color_col and len(active_measures) == 1:
                        bar_kwargs["color"] = color_col
                        if any(k in color_col.lower() for k in ["group", "nhóm", "khối"]):
                            group_color_map = {}
                            for g in plot_df[color_col].dropna().unique():
                                g_str = str(g).lower()
                                if any(k in g_str for k in ["kinh doanh", "sales", "commercial"]):
                                    group_color_map[g] = "#0068FF"
                                elif any(k in g_str for k in ["kỹ thuật", "tech", "development", "research", "engineering"]):
                                    group_color_map[g] = "#8B5CF6"
                            if group_color_map:
                                bar_kwargs["color_discrete_map"] = group_color_map
                    elif color_map and len(color_map) == len(active_measures):
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

                        # Hiển thị nhãn trực tiếp bên trong từng phân đoạn (hoặc bên ngoài nếu Grouped Bar)
                        txt_tmpl = "%{y:.0f}%" if is_composition_100 else "%{y:,.0f}"
                        txt_pos = "inside" if barmode_val == "stack" else "outside"
                        fig.update_traces(texttemplate=txt_tmpl, textposition=txt_pos)
                        layout_kwargs = dict(
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.05 if barmode_val == "group" else 1.02, xanchor="right", x=1)
                        )
                        if is_composition_100:
                            layout_kwargs["yaxis"] = dict(range=[0, 100], ticksuffix="%", title="Tỷ lệ (%)")
                        else:
                            try:
                                max_val = float(plot_df[active_measures].max().max() or 0)
                            except Exception:
                                max_val = 10.0
                            y_range = [0, max(5.0, max_val * 1.25)] if barmode_val == "group" else None
                            layout_kwargs["yaxis"] = dict(title="Số Lượng Nhân Sự", range=y_range)
                        fig.update_layout(**layout_kwargs)

                    elif is_gender_salary_comp:
                        diff_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["salarydifference", "salary_difference", "diff", "gap"])), None)
                        pct_diff_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["differencepercentage", "difference_percentage", "diffpct", "pct_diff"])), None)

                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            is_f = any(k in tr_l for k in ["female", "nu", "nữ", "women"])
                            gender_label = "Nữ (Female)" if is_f else "Nam (Male)"
                            tr.name = gender_label
                            if diff_col and pct_diff_col:
                                m_col = next((c for c in active_measures if (("female" in c.lower() or "nữ" in c.lower()) if is_f else ("male" in c.lower() or "nam" in c.lower()))), None)
                                if m_col:
                                    hovers = []
                                    for _, r in plot_df.iterrows():
                                        hovers.append(f"<b>{r[label_name]}</b><br>{gender_label}: ${float(r[m_col]):,.0f}<br>Chênh lệch: ${float(r[diff_col]):,.0f} ({float(r[pct_diff_col]):.2f}%)")
                                    tr.hovertext = hovers
                                    tr.hovertemplate = "%{hovertext}<extra></extra>"

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

                    elif is_mgr_sub_salary_comp:
                        diff_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["salarydifference", "salary_difference", "diff", "gap", "chenh_lech", "chênh lệch"])), None)
                        pct_diff_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["differencepercentage", "difference_percentage", "diffpct", "pct_diff", "tỷ lệ"])), None)
                        mgr_name_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["managername", "manager_name", "quản lý", "trưởng phòng"])), None)

                        is_sub_avg = any(any(k in c.lower() for k in ["avg", "trung bình", "tb"]) for c in active_measures) or any(k in (user_query or "").lower() for k in ["trung bình", "avg"])
                        sub_display = "Lương TB Cấp Dưới ($)" if is_sub_avg else "Lương Cấp Dưới Cao Nhất ($)"

                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            is_mgr = any(k in tr_l for k in ["manager", "quản lý"])
                            tr.name = "Lương Quản Lý ($)" if is_mgr else sub_display
                            tr.marker.color = "#0068FF" if is_mgr else "#10B981"

                            hovers = []
                            m_col = next((c for c in active_measures if (any(k in c.lower() for k in ["manager", "quản lý"]) if is_mgr else any(k in c.lower() for k in ["subordinate", "cấp dưới"]))), None)
                            if m_col:
                                for _, r in plot_df.iterrows():
                                    mgr_info = f"<br>Trưởng phòng: <b>{r[mgr_name_col]}</b>" if (mgr_name_col and mgr_name_col in r) else ""
                                    gap_info = ""
                                    if diff_col and diff_col in r:
                                        try:
                                            diff_val = float(r[diff_col])
                                            pct_val = float(r[pct_diff_col]) if (pct_diff_col and pct_diff_col in r) else 0.0
                                            sign = "+" if diff_val > 0 else ""
                                            gap_info = f"<br>Chênh lệch: <b>{sign}${diff_val:,.0f} ({sign}{pct_val:.1f}%)</b>"
                                        except Exception:
                                            pass
                                    val_str = f"${float(r[m_col]):,.0f}" if pd.notna(r[m_col]) else "N/A"
                                    hovers.append(f"<b>{r[label_name]}</b>{mgr_info}<br>{tr.name}: {val_str}{gap_info}")
                                tr.hovertext = hovers
                                tr.hovertemplate = "%{hovertext}<extra></extra>"

                        fig.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
                        try:
                            max_val = float(plot_df[active_measures].max().max())
                        except Exception:
                            max_val = 120000.0
                        b_margin = 90 if tick_angle != 0 else 50
                        layout_kwargs = dict(
                            yaxis=dict(title="Mức Lương ($)", range=[0, max_val * 1.18]),
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0),
                            margin=dict(l=40, r=25, t=85, b=b_margin)
                        )
                        fig.update_layout(**layout_kwargs)

                    elif is_tenure_cohort_salary_comp:
                        diff_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["salarydifference", "salary_difference", "diff", "gap", "chenh_lech", "chênh lệch"])), None)
                        pct_diff_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["differencepercentage", "difference_percentage", "diffpct", "pct_diff", "tỷ lệ"])), None)
                        senior_cnt_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["seniorcount", "senior_count", "sl_ky_cuu"])), None)
                        newhire_cnt_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["newhirecount", "newhire_count", "sl_moi_vao"])), None)

                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            is_senior = any(k in tr_l for k in ["senior", "kỳ cựu", "ky_cuu", "cựu"])
                            tr.name = "Lương TB Kỳ Cựu (>5 năm) ($)" if is_senior else "Lương TB Mới Vào (<2 năm) ($)"
                            tr.marker.color = "#0068FF" if is_senior else "#10B981"

                            hovers = []
                            m_col = next((c for c in active_measures if (any(k in c.lower() for k in ["senior", "kỳ cựu", "ky_cuu"]) if is_senior else any(k in c.lower() for k in ["newhire", "mới", "moi"]))), None)
                            if m_col:
                                for _, r in plot_df.iterrows():
                                    cnt_str = ""
                                    if is_senior and senior_cnt_col and senior_cnt_col in r:
                                        try:
                                            cnt_str = f"<br>Quy mô: <b>{int(r[senior_cnt_col]):,} người</b>"
                                        except Exception:
                                            pass
                                    elif not is_senior and newhire_cnt_col and newhire_cnt_col in r:
                                        try:
                                            cnt_str = f"<br>Quy mô: <b>{int(r[newhire_cnt_col]):,} người</b>"
                                        except Exception:
                                            pass

                                    gap_info = ""
                                    if not is_senior and diff_col and diff_col in r:
                                        try:
                                            diff_val = float(r[diff_col])
                                            pct_val = float(r[pct_diff_col]) if (pct_diff_col and pct_diff_col in r) else 0.0
                                            sign = "+" if diff_val > 0 else ""
                                            gap_info = f"<br>Kỳ cựu cao hơn: <b>{sign}${diff_val:,.0f} ({sign}{pct_val:.1f}%)</b>"
                                        except Exception:
                                            pass

                                    val_str = f"${float(r[m_col]):,.0f}" if pd.notna(r[m_col]) else "N/A"
                                    hovers.append(f"<b>{r[label_name]}</b><br>{tr.name}: <b>{val_str}</b>{cnt_str}{gap_info}")
                                tr.hovertext = hovers
                                tr.hovertemplate = "%{hovertext}<extra></extra>"

                        fig.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
                        try:
                            max_val = float(plot_df[active_measures].max().max())
                        except Exception:
                            max_val = 100000.0
                        b_margin = 90 if tick_angle != 0 else 50
                        layout_kwargs = dict(
                            yaxis=dict(title="Mức Lương Trung Bình ($)", range=[0, max_val * 1.18]),
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0),
                            margin=dict(l=40, r=25, t=85, b=b_margin)
                        )
                        fig.update_layout(**layout_kwargs)

                    elif is_employee_title_salary_comp:
                        surplus_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["salarysurplus", "salary_surplus", "surplus", "chênh lệch", "vượt"])), None)
                        title_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["title", "chức danh"])), None)
                        dept_col = next((c for c in plot_df.columns if any(k in c.lower() for k in ["dept", "department", "phòng"])), None)

                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            is_emp_sal = any(k in tr_l for k in ["current", "hiện tại"]) or not any(k in tr_l for k in ["title", "tb", "chức danh", "avg"])
                            tr.name = "Lương Hiện Tại ($)" if is_emp_sal else "Lương TB Chức Danh ($)"
                            tr.marker.color = "#0068FF" if is_emp_sal else "#10B981"

                            hovers = []
                            m_col = next((c for c in active_measures if (("current" in c.lower() or "hiện tại" in c.lower()) if is_emp_sal else ("title" in c.lower() or "tb" in c.lower() or "chức danh" in c.lower()))), None)
                            if not m_col:
                                m_col = active_measures[0] if is_emp_sal else active_measures[1]

                            for _, r in plot_df.iterrows():
                                title_info = f"<br>Chức danh: <b>{r[title_col]}</b>" if (title_col and title_col in r) else ""
                                dept_info = f" ({r[dept_col]})" if (dept_col and dept_col in r) else ""
                                gap_info = ""
                                if is_emp_sal and surplus_col and surplus_col in r:
                                    try:
                                        s_val = float(r[surplus_col])
                                        gap_info = f"<br>Vượt chuẩn: <b>+${s_val:,.0f}</b>"
                                    except Exception:
                                        pass
                                val_str = f"${float(r[m_col]):,.0f}" if pd.notna(r[m_col]) else "N/A"
                                hovers.append(f"<b>{r[label_name]}</b>{dept_info}{title_info}<br>{tr.name}: <b>{val_str}</b>{gap_info}")
                            tr.hovertext = hovers
                            tr.hovertemplate = "%{hovertext}<extra></extra>"

                        fig.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
                        try:
                            max_val = float(plot_df[active_measures].max().max())
                        except Exception:
                            max_val = 150000.0
                        b_margin = 90 if tick_angle != 0 else 50
                        layout_kwargs = dict(
                            yaxis=dict(title="Mức Lương ($)", range=[0, max_val * 1.18]),
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0),
                            margin=dict(l=40, r=25, t=85, b=b_margin)
                        )
                        fig.update_layout(**layout_kwargs)

                    elif is_stddev_salary_comp:
                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            is_std = any(k in tr_l for k in ["std", "chuẩn", "độ lệch", "phân tán"])
                            tr.name = "Độ Lệch Chuẩn Lương ($)" if is_std else "Lương Trung Bình ($)"
                            tr.marker.color = "#EC4899" if is_std else "#0068FF"

                            m_col = next((c for c in active_measures if (("std" in c.lower() or "chuẩn" in c.lower()) if is_std else ("avg" in c.lower() or "trung bình" in c.lower()))), None)
                            if m_col:
                                hovers = []
                                for _, r in plot_df.iterrows():
                                    val_str = f"${float(r[m_col]):,.0f}" if pd.notna(r[m_col]) else "N/A"
                                    hovers.append(f"<b>{r[label_name]}</b><br>{tr.name}: <b>{val_str}</b>")
                                tr.hovertext = hovers
                                tr.hovertemplate = "%{hovertext}<extra></extra>"

                        fig.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
                        try:
                            max_val = float(plot_df[active_measures].max().max())
                        except Exception:
                            max_val = 100000.0
                        b_margin = 90 if tick_angle != 0 else 50
                        layout_kwargs = dict(
                            yaxis=dict(title="Mức Lương ($)", range=[0, max_val * 1.18]),
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0),
                            margin=dict(l=40, r=25, t=85, b=b_margin)
                        )
                        fig.update_layout(**layout_kwargs)

                    elif is_headcount_salary_comp:
                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            if any(k in tr_l for k in ["headcount", "nhân sự", "nhân viên", "employee", "totalemployees"]):
                                tr.name = "Quy Mô Nhân Sự (Người)"
                                tr.marker.color = "#0068FF"
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

                    elif is_pnl_comp:
                        for tr in fig.data:
                            tr_l = str(tr.name).lower()
                            if any(k in tr_l for k in ["doanh thu", "sales", "revenue", "totalsales"]):
                                tr.name = "Doanh Thu ($)" if not is_en else "Revenue ($)"
                                tr.marker.color = "#0068FF"
                            elif any(k in tr_l for k in ["chi phí", "cost", "giá vốn", "cogs", "totalcost"]):
                                tr.name = "Chi Phí ($)" if not is_en else "Cost ($)"
                                tr.marker.color = "#F59E0B"
                            elif any(k in tr_l for k in ["lợi nhuận", "profit", "lãi"]):
                                tr.name = "Lợi Nhuận Ròng ($)" if any(k in tr_l for k in ["ròng", "net"]) else ("Lợi Nhuận ($)" if not is_en else "Net Profit ($)")
                                tr.marker.color = "#10B981"

                        fig.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
                        try:
                            max_val = float(plot_df[active_measures].max().max())
                        except Exception:
                            max_val = 1000000.0
                        b_margin = 90 if tick_angle != 0 else 50
                        layout_kwargs = dict(
                            yaxis=dict(title="Số Tiền ($)", range=[0, max_val * 1.18]),
                            legend=dict(title=None, orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0),
                            margin=dict(l=40, r=25, t=85, b=b_margin)
                        )
                        fig.update_layout(**layout_kwargs)

                    if len(active_measures) == 1:
                        meas = active_measures[0]
                        meas_lower = str(meas).lower()
                        is_pct = any(k in meas_lower for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "%", "share", "ratio"])
                        is_curr = any(k in meas_lower for k in ["salary", "lương", "cost", "revenue", "sales", "amount", "profit", "ordervalue", "tiền", "price", "giá", "đơn giá", "dongia", "giaban", "spread", "delta"])
                        is_raises = any(k in meas_lower for k in ["raise", "tăng lương", "tang_luong", "tăng_lương", "salary_increase", "salaryincrease", "increases", "số lần", "so lan", "lần tăng", "lan tang"])
                        is_boxes = any(k in meas_lower for k in ["box", "thùng", "hộp", "thung", "hop"]) and not is_curr
                        is_orders = any(k in meas_lower for k in ["order", "đơn hàng", "don_hang", "giao dịch", "transaction"])
                        is_hc = (
                            any(k in meas_lower for k in ["headcount", "nhân sự", "nhan_su", "nhân viên", "nhan_vien", "totalemployees", "slngnhnvin", "emp_count", "employee_count", "staff_count", "quy mô nhân sự", "quymo", "người", "nguoi"])
                            or (any(k in meas_lower for k in ["count", "số lượng", "so_luong"]) and not any(k in meas_lower for k in ["box", "thùng", "hộp", "order", "đơn", "raise", "lần", "sản phẩm", "product", "item"]))
                        ) and not is_curr and not is_raises and not is_boxes and not is_orders

                        trace_up = {"textposition": "outside"}
                        if not color_col:
                            trace_up["marker_color"] = "#0068FF"

                        if is_pct:
                            trace_up["texttemplate"] = "%{y:.2f}%"
                            fig.update_traces(**trace_up)
                            try:
                                max_val = float(plot_df[meas].max() or 0)
                            except Exception:
                                max_val = 100.0
                            fig.update_layout(
                                showlegend=bool(color_col),
                                yaxis=dict(title=format_col_title(meas), ticksuffix="%", range=[0, max(100.0, max_val * 1.15)])
                            )
                        elif is_curr:
                            trace_up["texttemplate"] = "$%{y:,.2f}" if any('.' in str(v) for v in plot_df[meas]) else "$%{y:,.0f}"
                            fig.update_traces(**trace_up)
                            try:
                                max_val = float(plot_df[meas].max() or 0)
                            except Exception:
                                max_val = 100.0
                            fig.update_layout(
                                showlegend=bool(color_col),
                                yaxis=dict(title=format_col_title(meas), range=[0, max_val * 1.15])
                            )
                        elif is_raises:
                            u_r = " lần" if not is_en else " times"
                            trace_up["texttemplate"] = f"%{{y:,.0f}}{u_r}"
                            fig.update_traces(**trace_up)
                            fig.update_layout(
                                showlegend=bool(color_col),
                                yaxis=dict(title=format_col_title(meas))
                            )
                        elif is_boxes:
                            u_b = " hộp" if not is_en else " boxes"
                            trace_up["texttemplate"] = f"%{{y:,.0f}}{u_b}"
                            fig.update_traces(**trace_up)
                            fig.update_layout(
                                showlegend=bool(color_col),
                                yaxis=dict(title=format_col_title(meas))
                            )
                        elif is_orders:
                            u_o = " đơn" if not is_en else " orders"
                            trace_up["texttemplate"] = f"%{{y:,.0f}}{u_o}"
                            fig.update_traces(**trace_up)
                            fig.update_layout(
                                showlegend=bool(color_col),
                                yaxis=dict(title=format_col_title(meas))
                            )
                        elif is_hc:
                            u_h = " người" if not is_en else " reps"
                            trace_up["texttemplate"] = f"%{{y:,.0f}}{u_h}"
                            fig.update_traces(**trace_up)
                            fig.update_layout(
                                showlegend=bool(color_col),
                                yaxis=dict(title=format_col_title(meas))
                            )
                        else:
                            trace_up["texttemplate"] = "%{y:,.0f}"
                            fig.update_traces(**trace_up)
                            fig.update_layout(
                                showlegend=bool(color_col),
                                yaxis=dict(title=format_col_title(meas))
                            )

                    t_margin = 85 if (is_pnl_comp or is_mgr_sub_salary_comp or is_tenure_cohort_salary_comp or is_gender_salary_comp or is_headcount_salary_comp or is_composition_100 or is_headcount_stack) else 50
                    fig.update_layout(
                        xaxis=dict(title=format_col_title(label_name), type="category", tickangle=tick_angle, automargin=True),
                        margin=dict(l=40, r=25, t=t_margin, b=90 if tick_angle != 0 else 50)
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

                    zero_var_optimized = False
                    zero_var_orig_col = None
                    zero_var_val = None
                    if zero_var_pivot_info:
                        zero_var_optimized = True
                        zero_var_orig_col = zero_var_pivot_info["orig_col"]
                        zero_var_val = zero_var_pivot_info["orig_val"]
                        clean_orig_m = format_col_title(zero_var_orig_col)
                        st.caption(
                            f"ℹ️ **Tối ưu trực quan hóa**: Do tất cả {len(plot_df)} đối tượng hiển thị đều có cùng {clean_orig_m} = {int(zero_var_val):,} lần (phương sai = 0), "
                            f"biểu đồ tự động chuyển trục Y sang **{format_col_title(zero_var_pivot_info['pivot_col'])} ($)** để so sánh sự phân hóa thu nhập thực tế giữa các cá nhân xuất sắc này."
                            if not is_en else
                            f"ℹ️ **Visualization Optimization**: Because all {len(plot_df)} subjects have identical {clean_orig_m} = {int(zero_var_val):,} (zero variance), "
                            f"the chart automatically sets Y-axis to **{format_col_title(zero_var_pivot_info['pivot_col'])}** to highlight comparative compensation."
                        )
                    elif pd.api.types.is_numeric_dtype(plot_df[measure_cols[0]]) and plot_df[measure_cols[0]].nunique(dropna=True) == 1 and len(plot_df) > 1:
                        val_num = plot_df[measure_cols[0]].iloc[0]
                        orig_m_col = measure_cols[0]
                        clean_orig_m = format_col_title(orig_m_col)

                        # Kiểm tra xem có cột đo lường khác có độ biến thiên (variance > 0) để chuyển trục Y
                        alt_candidates = [
                            c for c in plot_df.columns
                            if c != orig_m_col and pd.api.types.is_numeric_dtype(plot_df[c]) and not is_id_like(c)
                            and plot_df[c].nunique(dropna=True) > 1
                            and not any(k in str(c).lower() for k in ["totalcohort", "overall", "year", "nam", "hireyear"])
                        ]

                        if alt_candidates:
                            sal_cands = [c for c in alt_candidates if any(k in c.lower() for k in ["salary", "lương", "thu nhập", "amount", "revenue"])]
                            chosen_alt = sal_cands[0] if sal_cands else alt_candidates[0]
                            zero_var_orig_col = orig_m_col
                            zero_var_val = val_num
                            measure_cols = [chosen_alt]
                            zero_var_optimized = True

                            st.caption(
                                f"ℹ️ **Tối ưu trực quan hóa**: Do tất cả {len(plot_df)} đối tượng hiển thị đều có cùng {clean_orig_m} = {int(val_num):,} lần (phương sai = 0), "
                                f"biểu đồ tự động chuyển trục Y sang **{format_col_title(chosen_alt)} ($)** để so sánh sự phân hóa thu nhập thực tế giữa các cá nhân xuất sắc này."
                                if not is_en else
                                f"ℹ️ **Visualization Optimization**: Because all {len(plot_df)} subjects have identical {clean_orig_m} = {int(val_num):,} (zero variance), "
                                f"the chart automatically sets Y-axis to **{format_col_title(chosen_alt)}** to highlight comparative compensation."
                            )
                        else:
                            m_low = str(measure_cols[0]).lower()
                            is_r = any(k in m_low for k in ["raise", "tăng lương", "tang_luong", "salary_increase", "salaryincrease", "increases", "số lần", "lần tăng"])
                            is_b = any(k in m_low for k in ["box", "thùng", "hộp"])
                            is_o = any(k in m_low for k in ["order", "đơn hàng"])
                            is_hc_val = any(k in m_low for k in ["headcount", "nhân viên", "nhan_vien", "nhân sự", "người", "slngnhnvin", "totalemployees"]) and not is_r
                            is_sal_val = any(k in m_low for k in ["salary", "lương", "budget", "cost", "revenue", "sales", "$"])
                            if is_r:
                                val_str = f"{val_num:,} Lần" if not is_en else f"{val_num:,} times"
                            elif is_b:
                                val_str = f"{val_num:,} Hộp" if not is_en else f"{val_num:,} boxes"
                            elif is_o:
                                val_str = f"{val_num:,} Đơn" if not is_en else f"{val_num:,} orders"
                            elif is_hc_val:
                                val_str = f"{val_num:,} Người" if not is_en else f"{val_num:,} reps"
                            elif is_sal_val:
                                val_str = f"${val_num:,}"
                            else:
                                val_str = f"{val_num:,}"
                            clean_m_name = format_col_title(measure_cols[0])
                            st.caption(f"ℹ️ Lưu ý: Tất cả {len(plot_df)} đối tượng hiển thị đều có cùng {clean_m_name} = {val_str}.")

                    m_lower = str(measure_cols[0]).lower()
                    is_years = any(k in m_lower for k in ["year", "thâm niên", "tham_nien", "tenure", "kinh nghiệm", "kinh_nghiem", "service"])
                    is_salary = any(k in m_lower for k in ["salary", "lương", "luong", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "doanh thu", "doanh số", "doanh so", "sales", "amount", "$", "usd", "price", "giá", "đơn giá", "dongia", "giaban", "spread", "delta"])
                    is_raises = any(k in m_lower for k in ["raise", "tăng lương", "tang_luong", "tăng_lương", "salary_increase", "salaryincrease", "increases", "số lần", "so lan", "lần tăng", "lan tang"])
                    is_boxes = any(k in m_lower for k in ["box", "thùng", "hộp", "thung", "hop"]) and not is_salary
                    is_orders = any(k in m_lower for k in ["order", "đơn hàng", "don_hang", "giao dịch", "transaction"])
                    is_headcount = (
                        any(k in m_lower for k in ["headcount", "nhân sự", "nhan_su", "nhân viên", "nhan_vien", "totalemployees", "slngnhnvin", "emp_count", "employee_count", "staff_count", "quy mô nhân sự", "quymo", "người", "nguoi"])
                        or (any(k in m_lower for k in ["count", "số lượng", "so_luong"]) and not any(k in m_lower for k in ["box", "thùng", "hộp", "order", "đơn", "raise", "lần", "sản phẩm", "product", "item"]))
                    ) and not is_years and not is_salary and not is_raises and not is_boxes and not is_orders

                    curr_sym = "$" if is_salary else ""
                    clean_m = format_col_title(measure_cols[0])
                    clean_lbl = format_col_title(label_name)

                    bar_title = f"{clean_m} theo {clean_lbl}" + (f" (Phân loại theo {format_col_title(color_col)})" if color_col else "")
                    if zero_var_optimized and zero_var_orig_col:
                        u_orig = "Lần Tăng Lương" if any(k in str(zero_var_orig_col).lower() for k in ["raise", "tăng"]) else format_col_title(zero_var_orig_col)
                        bar_title = f"{clean_m} của Top {len(plot_df)} Nhân Sự (Cùng Đạt {int(zero_var_val):,} {u_orig})" + (f" (Phân loại theo {format_col_title(color_col)})" if color_col else "")

                    hover_data_dict = {measure_cols[0]: ":,.0f" if is_salary else True}
                    if zero_var_orig_col and zero_var_orig_col in plot_df.columns:
                        hover_data_dict[zero_var_orig_col] = True
                    if color_col and color_col in plot_df.columns:
                        hover_data_dict[color_col] = True

                    bar_kwargs = dict(
                        data_frame=plot_df, x=label_name, y=measure_cols[0],
                        color=color_col,
                        barmode="group" if color_col else "relative",
                        title=bar_title,
                        category_orders={label_name: category_order},
                        hover_data=hover_data_dict,
                        template="plotly_white"
                    )

                    # Nếu phân nhóm theo Khối / Nhóm phòng ban, sử dụng bảng màu tương phản trực quan
                    if color_col and any(k in color_col.lower() for k in ["group", "nhóm", "khối"]):
                        group_color_map = {}
                        for g in plot_df[color_col].dropna().unique():
                            g_str = str(g).lower()
                            if any(k in g_str for k in ["kinh doanh", "sales", "commercial"]):
                                group_color_map[g] = "#0068FF"  # Xanh Zalo Blue cho Kinh doanh
                            elif any(k in g_str for k in ["kỹ thuật", "tech", "development", "research", "engineering"]):
                                group_color_map[g] = "#8B5CF6"  # Tím Violet hiện đại cho Kỹ thuật
                        if group_color_map:
                            bar_kwargs["color_discrete_map"] = group_color_map
                        else:
                            bar_kwargs["color_discrete_sequence"] = ["#0068FF", "#8B5CF6", "#10B981", "#F59E0B", "#EC4899"]

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
                        ttemplate = "%{y:.1f} năm" if not is_en else "%{y:.1f} yrs"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    elif is_raises:
                        u_raise = " lần" if not is_en else " times"
                        ttemplate = f"%{{y:,.0f}}{u_raise}"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    elif is_boxes:
                        u_box = " hộp" if not is_en else " boxes"
                        ttemplate = f"%{{y:,.0f}}{u_box}"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    elif is_orders:
                        u_order = " đơn" if not is_en else " orders"
                        ttemplate = f"%{{y:,.0f}}{u_order}"
                        trace_kwargs = {"texttemplate": ttemplate, "textposition": "outside"}
                    elif is_headcount:
                        u_hc = " người" if not is_en else " reps"
                        ttemplate = f"%{{y:,.0f}}{u_hc}"
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

                        _unassigned_labels = {"(chưa phân nhóm)", "(chưa xác định)", "(unassigned)", "chưa phân nhóm", "chưa xác định", "unassigned", "(trống)", "none", "n/a", ""}
                        if target_entity:
                            # Tô màu nổi bật Cam Đậm #F59E0B cho đối tượng được hỏi, màu Xanh #3B82F6 cho các đối tượng khác, màu xám cho nhóm chưa phân nhóm
                            colors = ['#F59E0B' if str(v).strip().lower() == target_entity.lower() else ('#94A3B8' if str(v).strip().lower() in _unassigned_labels else '#3B82F6') for v in plot_df[label_name]]
                            trace_kwargs["marker_color"] = colors
                        else:
                            # Kiểm tra xem có phải truy vấn xếp hạng Top N không
                            uq_low = (user_query or "").lower()
                            is_top_ranking = any(k in uq_low for k in ["top", "cao nhất", "thấp nhất", "lâu nhất", "xếp hạng", "dẫn đầu", "nhiều nhất", "ít nhất"])
                            has_unassigned_cat = any(str(v).strip().lower() in _unassigned_labels for v in plot_df[label_name])

                            if has_unassigned_cat:
                                colors = ['#94A3B8' if str(v).strip().lower() in _unassigned_labels else '#0068FF' for v in plot_df[label_name]]
                                trace_kwargs["marker_color"] = colors
                            elif is_top_ranking and 2 <= len(plot_df) <= 15:
                                # Highlight đối tượng dẫn đầu #1 bằng màu Vàng Gold #F59E0B, các đối tượng còn lại màu Zalo Blue #0068FF
                                colors = ['#F59E0B'] + ['#0068FF'] * (len(plot_df) - 1)
                                trace_kwargs["marker_color"] = colors
                            else:
                                trace_kwargs["marker_color"] = "#0068FF"

                    if len(plot_df) <= 2:
                        trace_kwargs["width"] = 0.35

                    fig.update_traces(**trace_kwargs)

                    # Đảm bảo không gian phía trên để nhãn ngoài (textposition='outside') không bị che
                    if not color_col and len(plot_df) >= 1 and pd.api.types.is_numeric_dtype(plot_df[measure_cols[0]]):
                        max_y = float(plot_df[measure_cols[0]].max())
                        if max_y > 0:
                            fig.update_yaxes(range=[0, max_y * 1.18])

                    # Thêm đường mốc ngưỡng chuẩn nếu người dùng có yêu cầu lọc theo ngưỡng
                    uq_thresh_low = (user_query or "").lower()
                    if is_salary and any(k in uq_thresh_low for k in ["trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", "lớn hơn", "nhỏ hơn", ">", "<", "above", "below"]):
                        th_m = re.search(r'[\$]?\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)(?:\s*(?:k|nghìn|ngàn|usd|\$))?', uq_thresh_low)
                        if th_m:
                            try:
                                raw_th = th_m.group(1).replace(",", "").replace(".", "")
                                v_th = float(raw_th)
                                if v_th < 1000 and any(k in uq_thresh_low for k in ["k", "nghìn", "ngàn"]):
                                    v_th *= 1000
                                if v_th > 0:
                                    fig.add_hline(
                                        y=v_th,
                                        line_dash="dash",
                                        line_color="#EF4444",
                                        annotation_text=f"Ngưỡng ${v_th:,.0f}" if not is_en else f"Threshold ${v_th:,.0f}",
                                        annotation_position="top right"
                                    )
                                    if not color_col and len(plot_df) >= 1 and pd.api.types.is_numeric_dtype(plot_df[measure_cols[0]]):
                                        max_val_th = max(float(plot_df[measure_cols[0]].max()), v_th)
                                        fig.update_yaxes(range=[0, max_val_th * 1.2])
                            except Exception:
                                pass

                    if len(plot_df) == 1 and label_name:
                        entity_name = str(plot_df[label_name].iloc[0])
                        dept_cands = [c for c in plot_df.columns if any(k in c.lower() for k in ["dept", "phòng", "department"]) and c != label_name]
                        dept_suffix = f" ({plot_df[dept_cands[0]].iloc[0]})" if dept_cands else ""
                        dyn_title = f"🏆 {clean_m}: {entity_name}{dept_suffix}"
                    elif target_entity and any(k in (user_query or "").lower() for k in ["so sánh", "so voi", "so với", "đối chiếu", "compare", "vs"]):
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
                    if zero_var_optimized and zero_var_orig_col:
                        u_orig = "Lần Tăng Lương" if any(k in str(zero_var_orig_col).lower() for k in ["raise", "tăng"]) else format_col_title(zero_var_orig_col)
                        dyn_title = f"{clean_m} của Top {len(plot_df)} Nhân Sự (Cùng Đạt {int(zero_var_val):,} {u_orig})" + (f" (Phân loại theo {format_col_title(color_col)})" if color_col else "")
                    if is_raises:
                        unit_str = "Lần" if not is_en else "Times"
                        yaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                    elif is_boxes:
                        unit_str = "Hộp" if not is_en else "Boxes"
                        yaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                    elif is_orders:
                        unit_str = "Đơn" if not is_en else "Orders"
                        yaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                    elif is_headcount:
                        unit_str = "Người" if not is_en else "People"
                        yaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                    else:
                        yaxis_title_str = clean_m
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
                    clean_m = format_col_title(m_name)
                    donut_title = (
                        f"Cơ Cấu {clean_m} ({pct_val:,.2f}%)"
                        if any(k in clean_m.lower() for k in ["tỷ trọng", "tỉ trọng", "tỷ lệ", "tỉ lệ", "cơ cấu"])
                        else f"Tỷ Trọng {clean_m} ({pct_val:,.2f}%)"
                    )
                    donut_title = clean_chart_title(donut_title)
                    fig = px.pie(
                        names=[f"{clean_m} ({pct_val:,.2f}%)", f"Còn lại ({rem_val:,.2f}%)"],
                        values=[pct_val, rem_val],
                        hole=0.55,
                        title=donut_title,
                        template="plotly_white",
                        color_discrete_sequence=["#0068FF", "#E2E8F0"]
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
                    name_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["fullname", "name", "tên", "employee", "salesperson"])]
                    dept_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["dept", "phòng", "department"])]
                    if name_cols:
                        entity_lbl = str(df[name_cols[0]].iloc[0])
                        if dept_cols:
                            entity_lbl += f" ({df[dept_cols[0]].iloc[0]})"
                        bar_x = [entity_lbl]
                        bar_title = f"Thu Nhập: {entity_lbl}" if any(k in m_lower for k in ["salary", "lương", "thu nhập"]) else f"{format_col_title(m_name)}: {entity_lbl}"
                    else:
                        bar_x = [format_col_title(m_name)]
                        bar_title = f"Chỉ số: {format_col_title(m_name)}"

                    curr_prefix = "$" if any(k in m_lower for k in ["salary", "lương", "sales", "amount", "budget"]) else ""
                    fig = px.bar(
                        x=bar_x,
                        y=[val_num],
                        text=[f"{curr_prefix}{val_num:,.0f}" if isinstance(val_num, (int, float)) else str(val_num)],
                        title=bar_title,
                        template="plotly_white"
                    )
                    fig.update_traces(textposition="outside", marker_color="#0068FF", width=0.35)
                    fig.update_layout(
                        xaxis_title="",
                        yaxis_title=format_col_title(m_name),
                        margin=dict(l=20, r=20, t=65, b=50),
                        yaxis=dict(range=[0, val_num * 1.25] if isinstance(val_num, (int, float)) and val_num > 0 else None)
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

                # Tìm cột giá trị tốt nhất cho Pie: Ưu tiên cột phần trăm/tỷ trọng, hoặc cột lương phòng ban
                pie_val_col = measure_cols[0]
                pct_candidates = [c for c in measure_cols if any(k in str(c).lower() for k in ["percent", "percentage", "pct", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "phan_tram", "share"])]
                if pct_candidates:
                    pie_val_col = pct_candidates[0]
                elif any(k in str(c).lower() for k in ["totalsalary", "total_salary", "salary", "lương"] for c in measure_cols) and any(k in (user_query or "").lower() for k in ["lương", "salary", "chi phí"]):
                    sal_candidates = [c for c in measure_cols if any(k in str(c).lower() for k in ["totalsalary", "total_salary", "salary", "lương"]) and not any(x in str(c).lower() for x in ["company", "cong_ty"])]
                    if sal_candidates:
                        pie_val_col = sal_candidates[0]

                # Nếu quá nhiều lát cắt (> 10), giữ top 9 và gộp phần còn lại vào 'Khác'
                if len(plot_df) > 10:
                    top_df = plot_df.sort_values(pie_val_col, ascending=False).head(9)
                    other_sum = plot_df.sort_values(pie_val_col, ascending=False).iloc[9:][pie_val_col].sum()
                    other_row = pd.DataFrame([{label_name: "Các đối tượng khác", pie_val_col: other_sum}])
                    plot_df = pd.concat([top_df, other_row], ignore_index=True)

                is_val_pct = any(k in str(pie_val_col).lower() for k in ["pct", "percent", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "%"])
                clean_pie_val = format_col_title(pie_val_col)
                clean_label = format_col_title(label_name)

                if is_val_pct and any(k in (user_query or "").lower() for k in ["lương", "salary", "chi phí"]):
                    chart_title = f"Cơ Cấu Chi Phí Lương theo {clean_label}"
                elif any(k in clean_pie_val.lower() for k in ["tỷ trọng", "tỉ trọng", "tỷ lệ", "tỉ lệ", "cơ cấu"]):
                    chart_title = f"{clean_pie_val} theo {clean_label}"
                else:
                    chart_title = f"Cơ Cấu {clean_pie_val} theo {clean_label}"

                chart_title = clean_chart_title(chart_title)
                fig = px.pie(
                    plot_df,
                    names=label_name,
                    values=pie_val_col,
                    hole=0.42,
                    title=chart_title,
                    template="plotly_white"
                )
                if is_val_pct:
                    fig.update_traces(
                        textposition='inside',
                        textinfo='percent+label',
                        hovertemplate="<b>%{label}</b><br>" + f"{format_col_title(pie_val_col)}: " + "%{value:,.2f}%<extra></extra>"
                    )
                else:
                    fig.update_traces(
                        textposition='inside',
                        textinfo='percent+label',
                        hovertemplate="<b>%{label}</b><br>" + f"{format_col_title(pie_val_col)}: " + "%{value:,.0f} (%{percent})<extra></extra>"
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
                clean_m = format_col_title(m_name)
                donut_title = (
                    f"Cơ Cấu {clean_m} ({pct_val:,.2f}%)"
                    if any(k in clean_m.lower() for k in ["tỷ trọng", "tỉ trọng", "tỷ lệ", "tỉ lệ", "cơ cấu"])
                    else f"Tỷ Trọng {clean_m} ({pct_val:,.2f}%)"
                )
                donut_title = clean_chart_title(donut_title)
                fig = px.pie(
                    names=[f"{clean_m} ({pct_val:,.2f}%)", f"Còn lại ({rem_val:,.2f}%)"],
                    values=[pct_val, rem_val],
                    hole=0.55,
                    title=donut_title,
                    template="plotly_white",
                    color_discrete_sequence=["#0068FF", "#E2E8F0"]
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

                # Kiểm tra độ biến thiên (variance) cho Bar Ngang
                if pd.api.types.is_numeric_dtype(plot_df[measure_cols[0]]) and plot_df[measure_cols[0]].nunique(dropna=True) == 1 and len(plot_df) > 1:
                    alt_cands = [
                        c for c in plot_df.columns
                        if c != measure_cols[0] and pd.api.types.is_numeric_dtype(plot_df[c]) and not is_id_like(c)
                        and plot_df[c].nunique(dropna=True) > 1
                        and not any(k in str(c).lower() for k in ["totalcohort", "overall", "year", "nam", "hireyear"])
                    ]
                    if alt_cands:
                        sal_cands = [c for c in alt_cands if any(k in c.lower() for k in ["salary", "lương", "thu nhập", "amount", "revenue"])]
                        measure_cols = [sal_cands[0] if sal_cands else alt_cands[0]]

                if len(plot_df) > 30:
                    plot_df = plot_df.head(30)

                # Sắp xếp tăng dần để khi vẽ từ dưới lên thì người cao nhất nằm trên cùng
                plot_df = plot_df.sort_values(measure_cols[0], ascending=True)

                m_lower = str(measure_cols[0]).lower()
                is_years = any(k in m_lower for k in ["year", "thâm niên", "tham_nien", "tenure", "kinh nghiệm", "kinh_nghiem", "service"])
                is_salary = any(k in m_lower for k in ["salary", "lương", "luong", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "doanh thu", "sales", "amount", "price", "giá", "đơn giá", "dongia", "giaban", "spread", "delta"])
                is_raises = any(k in m_lower for k in ["raise", "tăng lương", "tang_luong", "tăng_lương", "salary_increase", "salaryincrease", "increases", "số lần", "so lan", "lần tăng", "lan tang"])
                is_boxes = any(k in m_lower for k in ["box", "thùng", "hộp", "thung", "hop"]) and not is_salary
                is_orders = any(k in m_lower for k in ["order", "đơn hàng", "don_hang", "giao dịch", "transaction"])
                is_headcount = (
                    any(k in m_lower for k in ["headcount", "nhân sự", "nhan_su", "nhân viên", "nhan_vien", "totalemployees", "slngnhnvin", "emp_count", "employee_count", "staff_count", "quy mô nhân sự", "quymo", "người", "nguoi"])
                    or (any(k in m_lower for k in ["count", "số lượng", "so_luong"]) and not any(k in m_lower for k in ["box", "thùng", "hộp", "order", "đơn", "raise", "lần", "sản phẩm", "product", "item"]))
                ) and not is_years and not is_salary and not is_raises and not is_boxes and not is_orders

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
                    h_colors = ['#F59E0B' if str(v).strip().lower() == (target_entity or "").lower() else '#0068FF' for v in plot_df[label_name]]
                elif any(k in (user_query or "").lower() for k in ["top", "cao nhất", "nhất", "xếp hạng", "leading"]):
                    # Highlight #1 entity (last row in ascending sorted plot_df) in Gold #F59E0B, others in blue #0068FF
                    h_colors = ['#0068FF'] * len(plot_df)
                    if len(h_colors) > 0:
                        h_colors[-1] = '#F59E0B'
                else:
                    h_colors = '#0068FF'

                if is_years:
                    h_ttemplate = "%{x:.1f} năm" if not is_en else "%{x:.1f} yrs"
                elif is_raises:
                    u_raise = " lần" if not is_en else " times"
                    h_ttemplate = f"%{{x:,.0f}}{u_raise}"
                elif is_boxes:
                    u_box = " hộp" if not is_en else " boxes"
                    h_ttemplate = f"%{{x:,.0f}}{u_box}"
                elif is_orders:
                    u_order = " đơn" if not is_en else " orders"
                    h_ttemplate = f"%{{x:,.0f}}{u_order}"
                elif is_headcount:
                    u_hc = " người" if not is_en else " reps"
                    h_ttemplate = f"%{{x:,.0f}}{u_hc}"
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

                if is_raises:
                    unit_str = "Lần" if not is_en else "Times"
                    xaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                elif is_boxes:
                    unit_str = "Hộp" if not is_en else "Boxes"
                    xaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                elif is_orders:
                    unit_str = "Đơn" if not is_en else "Orders"
                    xaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                elif is_headcount:
                    unit_str = "Người" if not is_en else "People"
                    xaxis_title_str = f"{clean_m} ({unit_str})" if (unit_str.lower() not in clean_m.lower()) else clean_m
                else:
                    xaxis_title_str = clean_m

                fig.update_layout(
                    yaxis=dict(type="category", automargin=True),
                    xaxis_title=xaxis_title_str,
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

        if fig:
            fig.update_layout(
                font=dict(family="'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", size=12, color="#334155"),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )

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
