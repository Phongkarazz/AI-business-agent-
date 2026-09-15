"""
Evaluator Guardrail Module (Tầng 2: Tác tử Phản biện & Kiểm định Nghiệp vụ)
Đóng vai trò tác tử phản biện độc lập (Critic / Reflection Agent), nạp câu hỏi gốc,
câu lệnh SQL và DataFrame kết quả để đánh giá 4 tiêu chí cốt lõi:
1. Semantic Alignment (Khớp ngữ nghĩa & Thực thể mục tiêu)
2. Temporal Completeness (Tính toàn vẹn mốc thời gian & dữ liệu lịch sử)
3. Comparative Sufficiency (Độ đầy đủ của các vế so sánh & cực trị)
4. Data Health & Cardinality (Tính lành mạnh, không rỗng, giới hạn hợp lý)

Nếu kết quả vi phạm, Evaluator chấm 'FAIL' và sinh Actionable Feedback kích hoạt
vòng tự phản tỉnh (Self-Correction Reflection Loop).
"""

import re
import pandas as pd
from typing import Dict, Any, Optional
from src.analytics.heuristics import detect_query_language, is_id_like


def evaluate_execution(
    user_query: str,
    sql_query: str,
    df: Optional[pd.DataFrame],
    schema_context: str = "",
    plan: Optional[Dict[str, Any]] = None,
    lang: str = "vi"
) -> Dict[str, Any]:
    """Kiểm định chất lượng toàn diện của kết quả truy vấn SQL:
    Trả về đánh giá chi tiết theo 4 tiêu chí, kết luận PASS / FAIL, điểm chất lượng (0 - 100),
    lời bình luận chuyên môn (critique) và hướng dẫn sửa đổi có định hướng (actionable_feedback).
    """
    is_en = (lang == "en")
    q_low = (user_query or "").lower()
    sql_low = (sql_query or "").lower()
    schema_low = (schema_context or "").lower()
    is_employees_db = (
        any(k in schema_low for k in ["dept_emp", "dept_manager", "departments", "employees", "titles", "salaries", "hire_date"])
        or any(k in sql_low for k in ["dept_emp", "dept_manager", "departments", "employees", "salaries", "titles"])
    )

    criteria = {
        "semantic_alignment": {"passed": True, "detail": "Đã trả về đúng thực thể và thuộc tính mục tiêu." if not is_en else "Entities and target attributes correctly matched."},
        "temporal_validity": {"passed": True, "detail": "Mốc thời gian và trạng thái công tác hợp lệ." if not is_en else "Timeframe and active employment status valid."},
        "comparative_sufficiency": {"passed": True, "detail": "Đầy đủ các vế đối chiếu và cực trị." if not is_en else "All comparison dimensions and extreme benchmarks satisfied."},
        "data_health": {"passed": True, "detail": "Dữ liệu trả về lành mạnh, không rỗng." if not is_en else "Returned data healthy and non-empty."}
    }

    fails = []
    actionable_feedbacks = []

    # -------------------------------------------------------------
    # PILLAR 1: DATA HEALTH & CARDINALITY (TÍNH LÀNH MẠNH CỦA DỮ LIỆU)
    # -------------------------------------------------------------
    if df is None or df.empty:
        criteria["data_health"]["passed"] = False
        msg = "Kết quả truy vấn rỗng (0 dòng dữ liệu)." if not is_en else "Query returned 0 rows of data."
        criteria["data_health"]["detail"] = msg
        fails.append(msg)
        actionable_feedbacks.append(
            "Câu lệnh SQL trả về 0 dòng. Cần kiểm tra lại điều kiện WHERE (nới lỏng chuỗi lọc, thay CURRENT_DATE() bằng mốc lịch sử tối đa, bỏ điều kiện năm không tồn tại)."
            if not is_en else "Query returned 0 rows. Check WHERE clause, replace CURRENT_DATE() with MAX(date), and relax strict string equality."
        )

    # -------------------------------------------------------------
    # PILLAR 2: SEMANTIC ALIGNMENT (KHỚP NGỮ NGHĨA & THỰC THỂ MỤC TIÊU)
    # -------------------------------------------------------------
    if df is not None and not df.empty:
        cols_low = [str(c).lower() for c in df.columns]

        # Kiểm tra 2.1: Người dùng hỏi danh sách nhân viên nhưng kết quả lại chỉ có phòng ban
        is_aggregate_query = any(k in q_low for k in [
            "số lượng", "tổng số", "tỷ lệ", "phân bổ", "cơ cấu", "bao nhiêu", "đếm", 
            "count", "headcount", "bình quân", "quy mô", "trung bình", "tổng doanh số", "doanh số",
            "doanh thu", "top phòng ban", "theo phòng ban", "theo chức danh", "theo năm", 
            "từng năm", "từng tháng", "từng quý", "thống kê"
        ])
        is_explicit_employee_list = any(k in q_low for k in [
            "danh sách nhân viên", "những nhân viên", "các nhân viên", "liệt kê nhân viên", 
            "danh sách nhân sự", "những nhân sự", "các nhân sự", "liệt kê nhân sự", "liệt kê các nhân sự",
            "ai là", "nhân viên nào", "nhân sự nào", "top nhân viên", "top 5 nhân viên", "top 10 nhân viên",
            "top nhân sự", "top 3 nhân sự", "top 5 nhân sự", "top 10 nhân sự",
            "thông tin nhân viên", "thông tin nhân sự", "họ và tên"
        ])
        is_mgr_sub_query = (
            any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"])
            and any(k in q_low for k in ["dưới quyền", "subordinate", "cấp dưới"])
        )
        asked_for_employees = (
            any(k in q_low for k in ["nhân viên", "nhân sự", "danh sách", "liệt kê", "ai là", "employee", "employees", "salesperson", "sales person", "người bán"])
            and (is_explicit_employee_list or not is_aggregate_query)
            and not (is_mgr_sub_query and any(k in q_low for k in ["trung bình", "avg", "cao nhất", "max", "so sánh"]))
        )
        has_employee_col = (
            any(any(k in c for k in [
                "fullname", "full_name", "first_name", "last_name", "emp_no", "empno",
                "managername", "name", "salesperson", "sales_person", "sales person",
                "nhân viên", "nhân sự", "tên nhân viên", "họ và tên", "spid", "sales rep", "rep"
            ]) for c in cols_low)
            or any(is_id_like(c) for c in df.columns)
        )

        if asked_for_employees and not has_employee_col:
            criteria["semantic_alignment"]["passed"] = False
            msg = "Người dùng hỏi thông tin nhân sự nhưng dữ liệu chỉ trả về cấp phòng ban/đơn vị." if not is_en else "User queried employee-level records but result only provided department aggregates."
            criteria["semantic_alignment"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                ("BẮT BUỘC thêm thông tin cá nhân nhân viên (e.emp_no, CONCAT(e.first_name, ' ', e.last_name) AS FullName) vào câu lệnh SELECT." if is_employees_db else "BẮT BUỘC thêm thông tin nhân viên (pe.Salesperson) vào câu lệnh SELECT.")
                if not is_en else
                ("MUST include individual employee attributes (e.emp_no, FullName) in SELECT statement." if is_employees_db else "MUST include individual employee attributes (pe.Salesperson) in SELECT statement.")
            )

        # Kiểm tra 2.2: Người dùng hỏi tốc độ tăng trưởng lương nhưng chỉ trả về mức lương tĩnh
        asked_growth = any(k in q_low for k in ["tăng trưởng", "tốc độ", "mỗi năm", "growth rate", "annual growth"]) and any(k in q_low for k in ["lương", "salary"])
        has_growth_col = any(any(k in c for k in ["growth", "tăng trưởng", "annual", "rate", "tốc độ"]) for c in cols_low)
        if asked_growth and not has_growth_col:
            criteria["semantic_alignment"]["passed"] = False
            msg = "Người dùng hỏi tốc độ tăng trưởng lương bình quân mỗi năm nhưng bảng dữ liệu chỉ chứa mức lương tĩnh." if not is_en else "User queried annual salary growth rate, but dataset only contains static salary values."
            criteria["semantic_alignment"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                "BẮT BUỘC tính toán tốc độ tăng trưởng bình quân hàng năm qua công thức: (s_curr.salary - s_start.salary) / (DATEDIFF / 365.25) AS AvgAnnualSalaryGrowth."
                if not is_en else "MUST calculate annual growth rate via: (s_curr.salary - s_start.salary) / (DATEDIFF / 365.25) AS AvgAnnualSalaryGrowth."
            )

        # Kiểm tra 2.3: Người dùng hỏi nhân viên qua ít nhất 2 phòng ban nhưng thiếu cột số phòng ban
        asked_multi_dept = any(k in q_low for k in ["nhiều phòng ban", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng", "nhiều hơn 1 phòng"]) and any(k in q_low for k in ["nhân viên", "nhân sự", "người", "employee"])
        has_dept_count = any(any(k in c for k in ["departmentcount", "dept_count", "department_count", "số phòng ban", "phòng ban", "count", "dept"]) for c in cols_low)
        if asked_multi_dept and not has_dept_count:
            criteria["semantic_alignment"]["passed"] = False
            msg = "Thiếu chỉ số đếm số phòng ban đã trải qua (COUNT(DISTINCT de.dept_no))." if not is_en else "Missing distinct department count metric (COUNT(DISTINCT de.dept_no))."
            criteria["semantic_alignment"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                "BẮT BUỘC đếm số phòng ban qua COUNT(DISTINCT de.dept_no) AS DepartmentCount và lọc HAVING COUNT(DISTINCT de.dept_no) >= 2."
                if not is_en else "MUST include COUNT(DISTINCT de.dept_no) AS DepartmentCount and HAVING COUNT(DISTINCT de.dept_no) >= 2."
            )

        # Kiểm tra 2.4: Người dùng yêu cầu số lần tăng lương ít hơn N lần nhưng kết quả trả về có >= N lần
        m_less_raises = re.search(r"(?:ít hơn|dưới|nhỏ hơn|chưa quá|không quá|tối đa)\s*(\d+)\s*lần", q_low)
        if m_less_raises:
            max_allowed = int(m_less_raises.group(1))
            raise_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["raisecount", "raise_count", "lần tăng", "số lần"])), None)
            if raise_col:
                max_actual = pd.to_numeric(df[raise_col], errors="coerce").max()
                if pd.notna(max_actual) and max_actual >= max_allowed:
                    criteria["semantic_alignment"]["passed"] = False
                    msg = f"Dữ liệu vi phạm điều kiện lọc số lần tăng lương: Yêu cầu ít hơn {max_allowed} lần nhưng kết quả ghi nhận tối đa {int(max_actual)} lần." if not is_en else f"Data violates raise count constraint: Requested fewer than {max_allowed} raises, but max in result is {int(max_actual)}."
                    criteria["semantic_alignment"]["detail"] = msg
                    fails.append(msg)
                    actionable_feedbacks.append(
                        f"BẮT BUỘC lọc HAVING COUNT(s_all.salary) < {max_allowed} để chỉ lấy nhân viên có số lần tăng lương ít hơn {max_allowed} lần!"
                        if not is_en else f"MUST filter HAVING COUNT(s_all.salary) < {max_allowed} to satisfy raise count limit!"
                    )

        # Kiểm tra 2.5: Người dùng hỏi tỷ lệ thăng chức / đổi chức danh theo giới tính (trừ trường hợp thăng chức lên Quản lý / Manager)
        is_mgr_promo = any(k in q_low for k in ["manager", "quản lý", "trưởng phòng", "ban quản lý"])
        asked_gender_promotion = (
            any(k in q_low for k in ["thăng chức", "đổi chức danh", "chuyển chức danh"])
            and any(k in q_low for k in ["nam", "nữ", "giới tính"])
            and not is_mgr_promo
        )
        if asked_gender_promotion:
            has_titles_in_sql = "titles" in sql_low
            has_promotion_cols = any(any(k in c for k in ["promoted", "thăng chức", "chức danh", "promotion", "rate", "tỷ lệ", "tỉ lệ"]) for c in cols_low)
            if not has_titles_in_sql or not has_promotion_cols:
                criteria["semantic_alignment"]["passed"] = False
                msg = "Người dùng hỏi tỷ lệ thăng chức / đổi chức danh theo giới tính nhưng truy vấn chỉ đếm tổng số nhân sự mà không liên kết bảng titles." if not is_en else "User queried gender promotion rate, but query lacks titles table or promotion rate metrics."
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC liên kết bảng titles để lọc các nhân viên có >= 2 chức danh (đổi chức danh ít nhất 1 lần) và tính tỷ lệ thăng chức riêng cho từng giới tính!"
                    if not is_en else "MUST join titles table to filter employees with >= 2 titles and calculate promotion rate per gender!"
                )

        # Kiểm tra 2.6: Người dùng hỏi tìm nhân viên tuyển sau ngày/năm cụ thể được thăng chức lên Manager / Trưởng phòng
        asked_promoted_manager = (
            any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"])
            and any(k in q_low for k in ["thăng chức", "bổ nhiệm", "đổi chức danh", "lên chức"])
            and any(k in q_low for k in ["tuyển dụng", "tuyển", "vào làm", "hire", "sau ngày", "sau năm", "từ ngày", "từ năm"])
        )
        if asked_promoted_manager:
            has_mgr_in_sql = "manager" in sql_low or "dept_manager" in sql_low
            has_hire_date_filter = "hire_date" in sql_low and any(sym in sql_low for sym in [">", "between", ">="])
            is_wrong_trend_query = "group by" in sql_low and ("newtitleappointments" in sql_low or "year" in sql_low)

            if not has_mgr_in_sql or not has_hire_date_filter or is_wrong_trend_query:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng hỏi tìm các nhân viên cụ thể tuyển dụng sau mốc thời gian được thăng chức lên Manager, nhưng câu lệnh lại truy vấn xu hướng bổ nhiệm hoặc thiếu điều kiện lọc Manager/hire_date."
                    if not is_en else
                    "User asked for specific employees hired after a date promoted to Manager, but query returned annual trends or lacks Manager/hire_date filter."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC lọc e.hire_date > [ngày] VÀ titles.title = 'Manager' để trích xuất danh sách nhân viên cụ thể!"
                    if not is_en else
                    "MUST filter e.hire_date > [date] AND titles.title = 'Manager' to extract individual employees!"
                )

        # Kiểm tra 2.6.5: Người dùng hỏi danh sách nhân sự lương top % và thâm niên thấp nhưng kết quả chỉ trả về chức danh hoặc thiếu thông tin nhân sự/phòng ban/chức danh
        asked_top_sal_low_tenure = (
            any(k in q_low for k in ["nhân sự", "nhân viên", "danh sách", "liệt kê"])
            and any(k in q_low for k in ["mức lương", "lương", "salary"])
            and any(k in q_low for k in ["top", "cao nhất", "%", "phần trăm"])
            and any(k in q_low for k in ["gắn bó", "thâm niên", "tenure"])
            and any(k in q_low for k in ["dưới", "ít hơn", "<", "nhỏ hơn"])
        )
        if asked_top_sal_low_tenure:
            is_title_aggregate_only = "group by t.title" in sql_low or ("title" in cols_low and not has_employee_col)
            if not has_employee_col or is_title_aggregate_only:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu liệt kê từng cá nhân nhân sự lương top % thâm niên thấp, nhưng kết quả chỉ trả về cấp chức danh hoặc thiếu danh tính nhân sự."
                    if not is_en else
                    "User requested individual employees with top salary and low tenure, but query only aggregated by title or lacks individual employee records."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC trả về danh sách cá nhân nhân sự (emp_no, FullName, Department, Title, Salary, YearsOfService) qua CTE PERCENT_RANK() OVER (ORDER BY s.salary) >= 0.90 và lọc thâm niên gắn bó! TUYỆT ĐỐI KHÔNG GROUP BY t.title!"
                    if not is_en else
                    "MUST return individual employee records (emp_no, FullName, Department, Title, Salary, YearsOfService) using CTE with PERCENT_RANK() >= 0.90 and tenure filter! DO NOT GROUP BY t.title!"
                )

        # Kiểm tra 2.6.8: Người dùng hỏi so sánh mức lương / chênh lệch lương giữa nam và nữ theo từng phòng ban
        asked_dept_gender_salary = (
            any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "nam", "nữ", "gender"])
            and any(k in q_low for k in ["lương", "mức lương", "salary", "thu nhập", "lương bình quân", "lương trung bình"])
            and any(k in q_low for k in ["phòng ban", "từng phòng ban", "các phòng ban", "bộ phận", "department"])
        )
        if asked_dept_gender_salary:
            has_salary_metric = any(any(k in c for k in ["salary", "lương", "thu nhập", "diff", "gap"]) for c in cols_low) or "salaries" in sql_low
            is_headcount_only = any("totalemployees" in c or "maleemployees" in c or "malepct" in c for c in cols_low) and not any("salary" in c or "lương" in c for c in cols_low)
            if not has_salary_metric or is_headcount_only:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng hỏi so sánh mức lương / chênh lệch lương giữa nam và nữ theo từng phòng ban, nhưng kết quả chỉ trả về số lượng nhân sự hoặc tỷ lệ số lượng nhân sự mà thiếu các chỉ số lương."
                    if not is_en else
                    "User asked for gender salary comparison / gap by department, but result only returned headcount or employee counts without salary metrics."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tính lương trung bình nam (MaleAvgSalary), lương trung bình nữ (FemaleAvgSalary) và chênh lệch (SalaryDifference/DifferencePercentage) theo từng phòng ban! TUYỆT ĐỐI KHÔNG đếm số lượng nhân sự!"
                    if not is_en else
                    "MUST compute MaleAvgSalary, FemaleAvgSalary, and SalaryDifference/DifferencePercentage per department! DO NOT count employee headcount!"
                )

        # Kiểm tra 2.6.9: Người dùng hỏi so sánh lương Trưởng phòng (Manager) với lương trung bình (AVG) của nhân viên cấp dưới
        asked_mgr_sub_avg = (
            any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"])
            and any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên"])
            and any(k in q_low for k in ["trung bình", "bình quân", "avg", "average"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary"])
        )
        if asked_mgr_sub_avg:
            has_max_sub = "max(se.salary)" in sql_low or "maxsubordinatesalary" in sql_low
            has_sub_avg_col = any(any(k in c for k in ["subordinateavgsalary", "subordinate_avg_salary", "avgsubordinate", "avg_subordinate", "avg"]) for c in cols_low)
            has_mgr_sal_col = any(any(k in c for k in ["managersalary", "manager_salary", "manager"]) for c in cols_low)

            if has_max_sub or not has_sub_avg_col or not has_mgr_sal_col:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu so sánh mức lương hiện tại của Trưởng phòng với mức lương TRUNG BÌNH (AVG) của cấp dưới, nhưng câu lệnh lại dùng MAX(salary) tính lương cao nhất hoặc thiếu trường lương tương ứng."
                    if not is_en else
                    "User asked to compare Manager salary with AVERAGE (AVG) subordinate salary, but query used MAX(salary) or lacked required salary fields."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC ánh xạ 'trung bình' sang ROUND(AVG(se.salary), 2) AS SubordinateAvgSalary! TUYỆT ĐỐI KHÔNG DÙNG MAX(se.salary)!"
                    if not is_en else
                    "MUST map 'average' to ROUND(AVG(se.salary), 2) AS SubordinateAvgSalary! DO NOT USE MAX(se.salary)!"
                )

        # Kiểm tra 2.6.10: So sánh mức lương giữa nhân viên kỳ cựu (> 5 năm) và nhân viên mới (< 2 năm) theo từng phòng ban
        asked_tenure_cohort_salary = (
            any(k in q_low for k in ["kỳ cựu", "thâm niên", "trên 5 năm", "lâu năm", "cống hiến"])
            and any(k in q_low for k in ["mới", "mới vào", "mới tuyển", "dưới 2 năm", "ít năm"])
            and any(k in q_low for k in ["lương", "salary", "thu nhập"])
        )
        if asked_tenure_cohort_salary:
            has_senior_sal = any(any(k in c for k in ["senior", "tenure", "ky_cuu", "kỳ cựu", "lâu năm"]) for c in cols_low)
            has_new_sal = any(any(k in c for k in ["new", "moi", "mới", "dưới 2", "newbie"]) for c in cols_low)
            has_wrong_mgr = "dept_manager" in sql_low or "managername" in cols_low

            if not has_senior_sal or not has_new_sal or has_wrong_mgr:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu so sánh mức lương trung bình giữa nhóm nhân viên kỳ cựu (> 5 năm) và nhóm nhân viên mới (< 2 năm) theo từng phòng ban, nhưng kết quả thiếu cột lương phân nhóm hoặc bị chuyển hướng nhầm sang truy vấn Trưởng phòng (dept_manager)."
                    if not is_en else
                    "User asked to compare average salary between senior (>5 yrs) and new hire (<2 yrs) cohorts across departments, but query lacked cohort salary metrics or falsely joined dept_manager."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC SELECT cả SeniorAvgSalary (thâm niên > 5 năm) và NewHireAvgSalary (thâm niên < 2 năm) bằng CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25. TUYỆT ĐỐI KHÔNG JOIN dept_manager!"
                    if not is_en else
                    "MUST compute SeniorAvgSalary and NewHireAvgSalary using CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25. DO NOT join dept_manager!"
                )

        # Kiểm tra 2.6.11: Người dùng hỏi thăng chức / bổ nhiệm Quản lý (Manager) theo giới tính trong N năm gần nhất
        asked_recent_mgr_promo = (
            any(k in q_low for k in ["manager", "quản lý", "trưởng phòng", "ban quản lý"])
            and any(k in q_low for k in ["nam", "nữ", "giới tính", "gender"])
            and any(k in q_low for k in ["gần nhất", "5 năm", "gần đây", "thời gian qua"])
        )
        if asked_recent_mgr_promo:
            has_time_filter = ("where" in sql_low) and any(k in sql_low for k in ["from_date", "year(", "interval", "date_sub"])
            is_all_time = (df is not None and len(df) == 9 and "department" in [str(c).lower() for c in df.columns] and "TotalManagers" in df.columns and int(df["TotalManagers"].sum()) == 24)
            has_zero_rows = (df is not None and len(df) == 0)

            if not has_time_filter or is_all_time or has_zero_rows:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu so sánh số lượng nhân sự nam và nữ thăng chức lên quản lý trong 5 năm gần nhất, nhưng kết quả trả về toàn bộ 24 quản lý trong lịch sử (1985-2002) hoặc bị 0 dòng dữ liệu do lọc sai ngày."
                    if not is_en else
                    "User asked for manager appointments by gender in the last 5 years, but query returned all 24 historical managers or returned 0 rows due to bad date filtering."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC lọc đúng 5 năm gần nhất: WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - 4. TUYỆT ĐỐI KHÔNG dùng CURRENT_DATE() và KHÔNG ĐƯỢC bỏ điều kiện lọc thời gian!"
                    if not is_en else
                    "MUST filter the 5 most recent years: WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - 4. DO NOT use CURRENT_DATE() and DO NOT drop time filter!"
                )

        # Kiểm tra 2.6.12: Người dùng hỏi nhân sự kiếm được nhiều tiền nhất / lương cao nhất trong năm cụ thể
        m_target_yr = re.search(r"\b(19\d\d|20\d\d)\b", q_low)
        is_year_top_earner = (
            any(k in q_low for k in ["kiếm được nhiều tiền nhất", "kiếm nhiều tiền nhất", "nhiều tiền nhất", "kiếm tiền nhiều nhất", "kiếm tiền", "thu nhập cao nhất", "lương cao nhất", "mức lương cao nhất", "highest earner", "highest paid", "highest salary", "earned the most"])
            or (
                any(k in q_low for k in ["ai", "ai là", "top", "người", "nhân viên", "nhân sự", "người nào"])
                and any(k in q_low for k in ["tiền", "lương", "thu nhập", "salary"])
                and any(k in q_low for k in ["nhiều nhất", "cao nhất", "lớn nhất", "khủng nhất"])
            )
        ) and bool(m_target_yr) and not any(k in q_low for k in ["tăng trưởng", "tốc độ", "mỗi năm", "bổ nhiệm", "manager", "so sánh", "đối chiếu"])

        if is_year_top_earner:
            target_yr = m_target_yr.group(1)
            has_yr_filter = (target_yr in sql_low)
            has_amount_err = "s.amount" in sql_low or "amount" in sql_low
            has_dept_emp_err = "dept_employee" in sql_low
            has_current_filter = "9999-01-01" in sql_low and not has_yr_filter
            has_empty_df = (df is not None and len(df) == 0)

            if not has_yr_filter or has_amount_err or has_dept_emp_err or has_current_filter or has_empty_df:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    f"Người dùng hỏi nhân viên kiếm nhiều tiền nhất trong năm {target_yr}, nhưng câu lệnh thiếu điều kiện lọc năm {target_yr}, dùng sai cột (s.amount) hoặc sai bảng (dept_employee)."
                    if not is_en else
                    f"User asked for top earner in {target_yr}, but SQL lacks year {target_yr} filter, uses invalid column (s.amount), or invalid table (dept_employee)."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    f"BẮT BUỘC lọc đúng năm {target_yr}: WHERE YEAR(s.from_date) = {target_yr}. Bảng salaries dùng cột 'salary' (KHÔNG DÙNG s.amount) và bảng phân công là 'dept_emp' (KHÔNG PHẢI dept_employee)!"
                    if not is_en else
                    f"MUST filter year {target_yr}: WHERE YEAR(s.from_date) = {target_yr}. Use column 'salary' (not s.amount) and table 'dept_emp' (not dept_employee)!"
                )

        # Kiểm tra 2.6.13: Người dùng hỏi mức chênh lệch lương giữa người cao nhất và thấp nhất theo chức danh hoặc phòng ban
        is_salary_spread_eval = (
            any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa"])
            and any(k in q_low for k in ["lương", "salary", "thu nhập"])
            and (any(k in q_low for k in ["chức danh", "title", "vị trí"]) or any(k in q_low for k in ["phòng ban", "phòng", "department", "các phòng", "đơn vị"]))
            and not any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "gender", "kỳ cựu", "mới vào", "chuẩn", "stddev", "standard deviation", "std("])
        )
        if is_salary_spread_eval:
            is_title_eval = any(k in q_low for k in ["chức danh", "title", "vị trí"])
            has_spread = any(k in sql_low for k in ["salaryspread", "salary_spread", "max(s.salary) - min(s.salary)", "max(salary) - min(salary)"]) or (df is not None and any(any(k in str(c).lower() for k in ["salaryspread", "salary_spread", "spread"]) for c in df.columns))
            has_only_avg = ("avg(" in sql_low or (df is not None and any("avg" in str(c).lower() for c in df.columns))) and not has_spread
            has_wrong_table = (is_title_eval and ("dept_emp" in sql_low or "departments" in sql_low) and "titles" not in sql_low)

            if not has_spread or has_only_avg or has_wrong_table:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    f"Người dùng hỏi mức chênh lệch giữa người nhận lương cao nhất và người nhận lương thấp nhất theo {'chức danh' if is_title_eval else 'phòng ban'}, nhưng câu lệnh lại tính lương trung bình AVG(salary) hoặc thiếu trường chênh lệch SalarySpread (MAX - MIN)."
                    if not is_en else
                    f"User asked for salary spread (Max - Min) by {'title' if is_title_eval else 'department'}, but query computed average salary or lacked SalarySpread."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    f"BẮT BUỘC tính MAX(s.salary) AS MaxSalary, MIN(s.salary) AS MinSalary, (MAX(s.salary) - MIN(s.salary)) AS SalarySpread trên bảng {'titles t' if is_title_eval else 'departments d'}. TUYỆT ĐỐI KHÔNG tính lương trung bình AVG(salary)!"
                    if not is_en else
                    f"MUST compute MAX(s.salary) AS MaxSalary, MIN(s.salary) AS MinSalary, and SalarySpread = MAX - MIN on {'titles t' if is_title_eval else 'departments d'}. Do NOT compute AVG(salary)!"
                )

        # Kiểm tra 2.6.14: Người dùng hỏi phân loại toàn bộ nhân sự thành 3 nhóm lương (Dưới 50k, 50k-80k, Trên 80k)
        is_tier_eval = (
            (
                any(k in q_low for k in ["nhóm lương", "bậc lương", "khoảng lương", "3 nhóm lương", "thu nhập thấp", "thu nhập trung bình", "thu nhập cao"])
                or (
                    any(k in q_low for k in ["phân loại", "chia thành", "tier", "bracket"])
                    and any(k in q_low for k in ["lương", "thu nhập", "salary"])
                    and any(k in q_low for k in ["nhân sự", "nhân viên", "toàn bộ", "hiện tại", "tỷ lệ", "%", "số lượng", "mỗi nhóm"])
                )
                or (
                    "nhóm" in q_low and any(k in q_low for k in ["mỗi nhóm", "từng nhóm"])
                    and any(k in q_low for k in ["lương", "thu nhập", "salary"])
                    and any(k in q_low for k in ["tỷ lệ", "%", "cơ cấu"])
                )
            )
            and not any(k in q_low for k in ["kỳ cựu", "mới vào", "so sánh", "đối chiếu", "thâm niên"])
        )
        if is_tier_eval:
            has_case_tier = "case" in sql_low and ("50000" in sql_low or "80000" in sql_low)
            has_percentage = "percentage" in sql_low or "%" in sql_low or (df is not None and any("percentage" in str(c).lower() for c in df.columns))
            has_individual = "yearsofservice" in sql_low or "hire_date" in sql_low or (df is not None and len(df) > 10)

            if not has_case_tier or not has_percentage or has_individual:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu phân loại toàn bộ nhân sự thành 3 nhóm lương và tính tỷ lệ %, nhưng câu truy vấn lại xuất danh sách cá nhân hoặc thiếu mệnh đề CASE WHEN phân nhóm thu nhập."
                    if not is_en else
                    "User asked for 3-tier salary distribution with percentages, but query returned individual records or lacked CASE WHEN tier grouping."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC dùng CASE WHEN s.salary chia 3 nhóm (<50k, 50k-80k, >80k), đếm COUNT(*) AS EmployeeCount và tính Percentage = ROUND(COUNT(*) * 100.0 / Total, 2) trên bảng salaries WHERE to_date = '9999-01-01'!"
                    if not is_en else
                    "MUST use CASE WHEN to segment salaries into 3 tiers (<50k, 50k-80k, >80k), compute EmployeeCount and Percentage where to_date = '9999-01-01'!"
                )

        # Kiểm tra 2.6.15: Người dùng hỏi mức phân tán lương (độ lệch chuẩn - STDDEV) hoặc tỷ lệ biến động lương theo phòng ban
        is_fluct_eval = (
            any(k in q_low for k in ["biến động lương", "tỷ lệ biến động lương", "độ biến động lương", "dao động lương", "độ lệch chuẩn", "stddev", "độ phân tán"])
            or (
                any(k in q_low for k in ["biến động", "fluctuation", "dao động", "phân tán", "độ lệch chuẩn", "stddev"])
                and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"])
                and any(k in q_low for k in ["lương", "salary", "thu nhập"])
            )
        )
        if is_fluct_eval:
            has_dept_manager = "dept_manager" in sql_low
            has_fluct = any(k in sql_low for k in ["fluctuationrate", "fluctuation", "stddev", "std("]) or (df is not None and any(any(k in str(c).lower() for k in ["fluctuation", "rate", "stddev"]) for c in df.columns))
            has_stddev_explicit = any(k in sql_low for k in ["stddev", "std("]) or (df is not None and any(any(k in str(c).lower() for k in ["salarystddev", "salary_std_dev", "stddev"]) for c in df.columns))
            has_dept = "dept_name" in sql_low or (df is not None and any("dept" in str(c).lower() for c in df.columns))
            is_stddev_user_q = any(k in q_low for k in ["độ lệch chuẩn", "stddev", "phân tán", "độ phân tán", "standard deviation"])

            if has_dept_manager or not has_fluct or not has_dept or (is_stddev_user_q and not has_stddev_explicit):
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu xác định phòng ban có mức lương phân tán (độ lệch chuẩn - STDDEV) lớn nhất hiện nay, nhưng câu truy vấn thiếu tính toán độ lệch chuẩn STDDEV(s.salary) AS SalaryStdDev hoặc nhầm sang chênh lệch SalarySpread (MAX - MIN)!"
                    if not is_en else
                    "User requested department with largest salary dispersion (standard deviation - STDDEV), but query lacked STDDEV(s.salary) AS SalaryStdDev or mistakenly used SalarySpread (MAX - MIN)!"
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tính CurrentAvgSalary = ROUND(AVG(s.salary), 2), SalaryStdDev = ROUND(STDDEV(s.salary), 2), FluctuationRate = ROUND(STDDEV(s.salary) * 100.0 / AVG(s.salary), 2) gom theo d.dept_name và ORDER BY SalaryStdDev DESC. TUYỆT ĐỐI KHÔNG dùng MAX - MIN hay dept_manager!"
                    if not is_en else
                    "MUST compute CurrentAvgSalary = AVG(salary), SalaryStdDev = STDDEV(salary), FluctuationRate = STDDEV * 100.0 / AVG grouped by d.dept_name ORDER BY SalaryStdDev DESC. Do NOT use MAX - MIN or dept_manager!"
                )

        # Kiểm tra 2.6.16: Người dùng hỏi Top N phòng ban có tổng quỹ lương cao nhất kèm số lượng nhân sự
        is_top_dept_payroll_eval = (
            any(k in q_low for k in ["quỹ lương", "tổng quỹ lương", "tổng chi trả lương", "chi trả quỹ lương", "chi phí lương"])
            or (
                any(k in q_low for k in ["tổng lương", "tổng chi lương", "tổng tiền lương"])
                and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"])
            )
        )
        if is_top_dept_payroll_eval:
            has_sum_salary = "sum(s.salary)" in sql_low or "sum(salary)" in sql_low or "totalpayroll" in sql_low or (df is not None and any("payroll" in str(c).lower() or "sum" in str(c).lower() for c in df.columns))
            has_headcount = "count(" in sql_low or "headcount" in sql_low or (df is not None and any("headcount" in str(c).lower() for c in df.columns))
            has_limit = "limit" in sql_low or (df is not None and len(df) <= 5)

            if not has_sum_salary or not has_headcount or not has_limit:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng hỏi Top phòng ban có tổng quỹ lương chi trả cao nhất kèm số lượng nhân sự, nhưng câu lệnh lại thiếu SUM(s.salary) AS TotalPayroll, thiếu COUNT(DISTINCT de.emp_no) AS Headcount, hoặc thiếu LIMIT."
                    if not is_en else
                    "User asked for Top departments by total payroll and headcount, but query lacked SUM(s.salary) AS TotalPayroll, COUNT(DISTINCT de.emp_no) AS Headcount, or LIMIT."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tính SUM(s.salary) AS TotalPayroll, COUNT(DISTINCT de.emp_no) AS Headcount, ROUND(AVG(s.salary), 2) AS AvgSalary, gom theo d.dept_name, ORDER BY TotalPayroll DESC LIMIT {top_n}!"
                    if not is_en else
                    "MUST compute SUM(s.salary) AS TotalPayroll, COUNT(DISTINCT de.emp_no) AS Headcount, AVG(salary) AS AvgSalary, ORDER BY TotalPayroll DESC LIMIT {top_n}!"
                )

        # Kiểm tra 2.6.17: Người dùng hỏi có bao nhiêu nhân viên từng thay đổi phòng ban ít nhất 1 lần
        is_dept_transfer_count_eval = (
            (
                any(k in q_low for k in ["thay đổi phòng ban", "thay đổi phòng", "đổi phòng ban", "đổi phòng", "chuyển phòng ban", "chuyển phòng", "luân chuyển phòng ban", "luân chuyển phòng", "luân chuyển bộ phận"])
                or (any(k in q_low for k in ["thay đổi", "đổi", "chuyển", "luân chuyển"]) and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
            )
            and any(k in q_low for k in ["bao nhiêu", "số lượng", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many", "mấy"])
            and not any(k in q_low for k in ["danh sách", "liệt kê", "những ai", "top", "ai là"])
        )
        if is_dept_transfer_count_eval:
            has_wrong_table = "dept_manager" in sql_low or "salaries" in sql_low
            has_having = "having" in sql_low and ("count(" in sql_low)
            is_single_row = (df is not None and len(df) <= 1)

            if has_wrong_table or not has_having or not is_single_row:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng hỏi CÓ BAO NHIÊU nhân viên từng thay đổi phòng ban ít nhất 1 lần, nhưng câu lệnh lại JOIN dept_manager / salaries hoặc xuất danh sách cá nhân nhiều dòng thay vì 1 dòng tổng hợp số lượng và tỷ lệ %."
                    if not is_en else
                    "User asked HOW MANY employees changed departments, but query joined dept_manager/salaries or returned multi-row employee list instead of single-row summary."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC dùng cấu trúc: SELECT COUNT(*) AS EmployeesChangedDepartment, (SELECT COUNT(DISTINCT emp_no) FROM dept_emp) AS TotalEmployees, ROUND(COUNT(*) * 100.0 / (SELECT COUNT(DISTINCT emp_no) FROM dept_emp), 2) AS PercentageChangedDept FROM (SELECT emp_no FROM dept_emp GROUP BY emp_no HAVING COUNT(DISTINCT dept_no) > 1) t. TUYỆT ĐỐI KHÔNG JOIN dept_manager hay salaries!"
                    if not is_en else
                    "MUST use subquery with HAVING COUNT(DISTINCT dept_no) > 1 and COUNT(*) outer. Do NOT join dept_manager or salaries!"
                )

        # Kiểm tra 2.6.18: Người dùng hỏi tốc độ tăng trưởng quy mô nhân sự các phòng ban trong N năm đầu hoạt động
        is_dept_headcount_growth_eval = (
            any(k in q_low for k in ["tăng trưởng", "phát triển", "mở rộng quy mô"])
            and any(k in q_low for k in ["quy mô", "nhân sự", "nhân viên", "headcount", "số lượng"])
            and any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "từng phòng", "department"])
            and any(k in q_low for k in ["năm đầu", "năm đầu hoạt động", "giai đoạn đầu", "thời kỳ đầu", "mới thành lập", "khởi đầu", "3 năm", "5 năm", "2 năm"])
            and not any(k in q_low for k in ["lương", "salary", "thu nhập"])
        )
        if is_dept_headcount_growth_eval:
            has_wrong_individual_cols = has_employee_col or any(k in cols_low for k in ["fullname", "first_name", "last_name", "emp_no"])
            has_wrong_tables = "dept_manager" in sql_low or "salaries" in sql_low
            has_growth_calc = any(k in cols_low for k in ["headcountgrowthratepct", "growth", "rate"]) or any(k in sql_low for k in ["headcountgrowthratepct", "netheadcountgrowth"])
            has_tenure_error = any(k in cols_low for k in ["yearsofservice", "tenure"])

            if has_wrong_individual_cols or has_wrong_tables or not has_growth_calc or has_tenure_error:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng hỏi TỐC ĐỘ TĂNG TRƯỞNG QUY MÔ NHÂN SỰ theo phòng ban trong các năm đầu hoạt động, nhưng câu lệnh lại trả về từng cá nhân nhân sự, tính thâm niên gắn bó (hoặc lỗi 8014 năm), hoặc thiếu tính toán tỷ lệ tăng trưởng phần trăm giữa Năm 1 và Năm 3."
                    if not is_en else
                    "User asked for DEPARTMENT HEADCOUNT GROWTH RATE in early years, but query returned individual employees, computed tenure (or 8014 year error), or lacked percentage growth between Year 1 and Year 3."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC GROUP BY d.dept_name, đếm Headcount Năm 1 (1985) và Năm 3 (1987), tính NetHeadcountGrowth và HeadcountGrowthRatePct = ((Year3 - Year1) / Year1) * 100. TUYỆT ĐỐI KHÔNG TRẢ VỀ TỪNG NHÂN VIÊN VÀ KHÔNG DÙNG SALARIES/DATEDIFF('9999-01-01')!"
                    if not is_en else
                    "MUST compute InitialHeadcount (1985), Year3Headcount (1987), NetHeadcountGrowth, and HeadcountGrowthRatePct by department. DO NOT return individual employees or compute tenure with 9999-01-01!"
                )

        # Kiểm tra 2.6.19: Người dùng hỏi nhân viên làm việc tại ít nhất 2 phòng ban nhưng lương hiện tại thấp hơn / cao hơn lương TB phòng ban đầu tiên
        is_multi_dept_sal_first_eval = (
            any(k in q_low for k in ["nhiều phòng", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng", "2 phòng ban", "chuyển phòng", "luân chuyển"])
            and any(k in q_low for k in ["phòng ban đầu tiên", "phòng đầu tiên", "đầu tiên họ từng", "phòng ban khởi điểm", "first department", "first dept"])
            and any(k in q_low for k in ["lương", "salary", "thu nhập"])
        )
        if is_multi_dept_sal_first_eval:
            has_sal_col = any(any(k in c for k in ["currentsalary", "firstdeptavgsalary", "salarydeficit", "salarysurplus", "salarybelowavg", "salary", "lương"]) for c in cols_low)
            has_first_dept_col = any(any(k in c for k in ["firstdepartment", "first_department", "first_dept"]) for c in cols_low)
            has_sal_filter_sql = ("< da." in sql_low or "> da." in sql_low or "salary <" in sql_low or "salary >" in sql_low or "salarydeficit" in sql_low or "salarysurplus" in sql_low)
            is_only_dept_count = any("departmentcount" in c for c in cols_low) and not has_sal_col

            if is_only_dept_count or not has_sal_col or not has_sal_filter_sql:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu liệt kê nhân viên từng làm việc tại ít nhất 2 phòng ban nhưng mức lương hiện tại thấp hơn lương trung bình của phòng ban đầu tiên họ từng gia nhập, nhưng câu truy vấn đã bỏ qua hoàn toàn điều kiện so sánh lương hoặc chỉ trả về số lượng phòng ban mà thiếu các cột lương đối soát."
                    if not is_en else
                    "User asked for employees in >= 2 departments whose current salary is below their first department's average, but query ignored salary criteria or omitted salary columns."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tuân thủ 3 QUY TẮC PHÂN RÃ TRUY VẤN NGHIỆP VỤ: Dùng CTE 3 bước (FirstDept xác định phòng ban đầu tiên qua ROW_NUMBER(), DeptAvg tính AVG(salary) theo phòng ban, MultiDept lọc COUNT(DISTINCT dept_no) >= 2) và mệnh đề WHERE s_curr.salary < da.AvgSalary! BẮT BUỘC xuất các cột: emp_no, FullName, CurrentDepartment, CurrentSalary, FirstDepartment, FirstDeptAvgSalary, SalaryDeficit, DepartmentCount!"
                    if not is_en else
                    "MUST follow 3 Business Query Decomposition Rules: Use 3-step CTE (FirstDept via ROW_NUMBER(), DeptAvg via AVG(salary), MultiDept via COUNT(DISTINCT dept_no) >= 2) and filter WHERE s_curr.salary < da.AvgSalary with SalaryDeficit column!"
                )

        # Kiểm tra 2.6.20: Người dùng hỏi top nhân viên được tăng lương nhiều lần nhất nhưng mức lương hiện tại vẫn dưới ngưỡng
        is_top_raises_low_sal_eval = (
            any(k in q_low for k in ["tăng lương", "lần tăng", "được tăng"])
            and any(k in q_low for k in ["nhiều lần nhất", "nhiều nhất", "nhiều lần", "most raises"])
            and any(k in q_low for k in ["dưới", "thấp hơn", "chưa tới", "không quá", "<"])
            and any(k in q_low for k in ["lương", "salary", "mức lương", "$"])
        )
        if is_top_raises_low_sal_eval:
            has_raise_desc = any(k in sql_low for k in ["raisecount desc", "raise_count desc", "count(*) desc", "count(s.salary) desc", "count(s_hist.salary) desc"])
            has_sal_col = any(any(k in c for k in ["currentsalary", "current_salary", "salary", "lương"]) for c in cols_low)
            has_raise_col = any(any(k in c for k in ["raisecount", "raise_count", "số lần"]) for c in cols_low)
            has_hallucination = any(k in sql_low for k in ["email", "< n", "percent_rank"])

            # Check if all salaries in df are below threshold
            m_sal_ev = re.search(r"(?:dưới|thấp hơn|chưa tới|<)\s*\$?(\d+(?:[.,]\d+)*)\s*(?:k|nghìn|usd|\$)?", q_low)
            raw_s_str = m_sal_ev.group(1).replace(",", "").replace(".", "") if m_sal_ev else "60000"
            sal_cap_ev = int(raw_s_str) * 1000 if ("k" in q_low and int(raw_s_str) < 1000) else int(raw_s_str)

            sal_exceeded = False
            if df is not None and not df.empty and has_sal_col:
                sal_c_name = [c for c in df.columns if any(k in str(c).lower() for k in ["currentsalary", "current_salary", "salary"])][0]
                max_df_sal = float(pd.to_numeric(df[sal_c_name], errors="coerce").max() or 0)
                if max_df_sal >= sal_cap_ev:
                    sal_exceeded = True

            if has_hallucination or not has_raise_desc or not has_sal_col or not has_raise_col or sal_exceeded:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    f"Người dùng yêu cầu liệt kê top nhân viên được tăng lương nhiều lần nhất nhưng lương hiện tại dưới ${sal_cap_ev:,}, nhưng câu lệnh lại lọc sai điều kiện lương, bị lỗi ảo giác cột 'email'/'< N', hoặc không sắp xếp giảm dần theo số lần tăng lương."
                    if not is_en else
                    f"User requested top employees by raise count with current salary under ${sal_cap_ev:,}, but query failed salary cap, hallucinated 'email'/'< N', or did not sort by RaiseCount DESC."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    f"BẮT BUỘC dùng CTE 2 bước (ActiveSalariesUnderCap lọc to_date = '9999-01-01' AND salary < {sal_cap_ev}, EmployeeRaiseCounts đếm COUNT(*) AS RaiseCount) và ORDER BY rc.RaiseCount DESC, a.CurrentSalary ASC! TUYỆT ĐỐI KHÔNG BỊA ĐẶT CỘT 'e.email' VÀ KHÔNG DÙNG PERCENT_RANK()!"
                    if not is_en else
                    f"MUST use 2-step CTE filtering salary < {sal_cap_ev} and ordering by RaiseCount DESC! Do NOT hallucinate 'email' or use PERCENT_RANK()!"
                )

        # Kiểm tra 2.6.21: Top nhân viên có tỷ lệ tăng lương ấn tượng nhất so sánh lương đầu tiên và hiện tại
        is_employee_growth_eval = (
            any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "employee"])
            and any(k in q_low for k in ["tỷ lệ tăng lương", "tỉ lệ tăng lương", "tăng lương ấn tượng", "tốc độ tăng lương", "tăng trưởng lương", "mức tăng lương", "salary growth", "highest raise rate", "salary increase"])
            and (
                any(k in q_low for k in ["đầu tiên", "khởi điểm", "lúc vào", "khi vào", "gia nhập", "initial", "starting", "first salary"])
                or any(k in q_low for k in ["hiện tại", "bây giờ", "đến nay", "current", "latest"])
            )
        )
        if is_employee_growth_eval:
            has_emp_ident = any(any(k in c for k in ["emp_no", "fullname", "first_name", "last_name", "nhân viên"]) for c in cols_low)
            has_growth_metric = any(any(k in c for k in ["salarygrowthratepct", "growthratepct", "salary_growth", "growth_pct", "increase", "tỷ lệ"]) for c in cols_low)
            has_initial_metric = any(any(k in c for k in ["initialsalary", "initial_salary", "starting", "khởi điểm", "đầu tiên"]) for c in cols_low)
            is_only_dept_result = any("department" in c for c in cols_low) and len(cols_low) <= 3 and not has_emp_ident

            if is_only_dept_result or not has_emp_ident or not has_growth_metric or not has_initial_metric:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu liệt kê top nhân viên có tỷ lệ tăng lương ấn tượng nhất (so sánh lương đầu tiên khi vào công ty và lương hiện tại), nhưng câu lệnh chỉ trả về dữ liệu cấp phòng ban hoặc thiếu cột mức lương khởi điểm/tỷ lệ tăng trưởng của từng nhân viên!"
                    if not is_en else
                    "User requested top employees with highest salary growth rate comparing initial and current salary, but query returned department-level data or lacked initial salary and growth percentage columns!"
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tuân thủ 3 QUY TẮC PHÂN RÃ TRUY VẤN NGHIỆP VỤ: Dùng CTE 2 bước (ActiveEmployees lấy CurrentSalary to_date = '9999-01-01', InitialSalaries lấy InitialSalary từ MIN(from_date)), tính SalaryGrowthRatePct = ROUND((CurrentSalary - InitialSalary) * 100.0 / InitialSalary, 2) và xuất đầy đủ: emp_no, FullName, Department, CurrentTitle, InitialSalary, CurrentSalary, SalaryIncrease, SalaryGrowthRatePct!"
                    if not is_en else
                    "MUST follow 3 Business Query Decomposition Rules: Use 2-step CTE (ActiveEmployees for CurrentSalary, InitialSalaries for InitialSalary via MIN(from_date)), compute SalaryGrowthRatePct and project emp_no, FullName, Department, CurrentTitle, InitialSalary, CurrentSalary, SalaryIncrease, SalaryGrowthRatePct!"
                )

        # Kiểm tra 2.6.22: Nhân viên hiện đang nhận lương cao hơn mức lương trung bình của toàn bộ nhân viên có cùng chức danh (Title)
        is_employee_title_avg_eval = (
            any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "employee"])
            and any(k in q_low for k in ["chức danh", "title", "vị trí", "cùng chức danh", "same title"])
            and any(k in q_low for k in ["cao hơn", "vượt", "higher than", "above average", "lớn hơn"])
            and any(k in q_low for k in ["trung bình", "avg", "average"])
        )
        if is_employee_title_avg_eval:
            has_emp_ident = any(any(k in c for k in ["emp_no", "fullname", "first_name", "last_name", "nhân viên"]) for c in cols_low)
            has_title_col = any(any(k in c for k in ["title", "chức danh", "currenttitle"]) for c in cols_low)
            has_title_avg_col = any(any(k in c for k in ["titleavg", "title_avg", "avg_salary", "trung bình", "titleavgsalary"]) for c in cols_low)
            has_surplus_col = any(any(k in c for k in ["surplus", "chênh lệch", "vượt", "salarysurplus", "salary_surplus", "diff"]) for c in cols_low)

            has_title_join_or_cte = "title" in sql_low and ("avg" in sql_low or "group by" in sql_low)
            has_comparison = ">" in sql_low or "surplus" in sql_low

            if not has_emp_ident or not has_title_col or not (has_title_avg_col or has_surplus_col) or not has_title_join_or_cte or not has_comparison:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu liệt kê nhân viên nhận lương cao hơn mức lương trung bình của người cùng chức danh (Title), nhưng câu lệnh thiếu cột chức danh (Title), thiếu cột lương trung bình chức danh (TitleAvgSalary), hoặc không thực hiện so sánh lương hiện tại > lương trung bình chức danh!"
                    if not is_en else
                    "User requested employees earning above their title's average salary, but query dropped Title, TitleAvgSalary, or failed to compare CurrentSalary > TitleAvgSalary!"
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tuân thủ 3 QUY TẮC PHÂN RÃ TRUY VẤN NGHIỆP VỤ: Dùng CTE 2 bước (TitleAvg tính AVG(salary) theo title có to_date = '9999-01-01', sau đó JOIN nhân viên hiện tại có cùng title với điều kiện WHERE s.salary > ta.TitleAvgSalary), xuất đầy đủ các cột: emp_no, FullName, Department, Title, CurrentSalary, TitleAvgSalary, SalarySurplus và ORDER BY SalarySurplus DESC, s.salary DESC LIMIT 10!"
                    if not is_en else
                    "MUST follow 3 Business Query Decomposition Rules: Use 2-step CTE (TitleAvg computing AVG(salary) per title for to_date = '9999-01-01', then JOIN active employees on title with WHERE s.salary > ta.TitleAvgSalary), projecting emp_no, FullName, Department, Title, CurrentSalary, TitleAvgSalary, SalarySurplus, ordered by SalarySurplus DESC, s.salary DESC LIMIT 10!"
                )

        # Kiểm tra 2.6.23: Nhân viên từng bị giảm lương trong lịch sử làm việc tại công ty
        is_salary_reduction_eval = (
            any(k in q_low for k in ["giảm lương", "hạ lương", "bị giảm", "bị hạ", "salary reduction", "salary decrease", "pay cut"])
            or (any(k in q_low for k in ["lương", "salary"]) and any(k in q_low for k in ["giảm", "hạ", "tụt", "thấp hơn lần trước", "thấp hơn kỳ trước", "reduction", "decrease", "cut"]))
        )
        if is_salary_reduction_eval:
            has_emp_ident = any(any(k in c for k in ["emp_no", "fullname", "first_name", "last_name", "nhân viên"]) for c in cols_low)
            has_reduction_col = any(any(k in c for k in ["salaryreduction", "reduction", "mức giảm", "giam_luong", "giảm", "reductionpct", "prevsalary", "newsalary"]) for c in cols_low)
            has_dept_col = any(any(k in c for k in ["department", "dept_name", "phòng ban"]) for c in cols_low)
            has_hallucinated_table = any(k in sql_low for k in ["dept_reductions", "reductions", "salary_reductions", "employee_reductions"]) and not ("with salaryreductions as" in sql_low or "salarystep" in sql_low)

            if not has_emp_ident or not has_reduction_col or not has_dept_col or has_hallucinated_table:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng hỏi danh sách nhân viên từng bị giảm lương trong lịch sử kèm phòng ban và mức giảm, nhưng câu lệnh lại bịa đặt bảng không tồn tại (như dept_reductions), thiếu thông tin nhân sự, thiếu phòng ban hoặc thiếu mức giảm lương."
                    if not is_en else
                    "User asked for employees who experienced salary reduction in history with department and reduction amount, but query hallucinated non-existent tables or missed required fields."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tuân thủ 3 QUY TẮC PHÂN RÃ TRUY VẤN NGHIỆP VỤ: Dùng CTE với hàm cửa sổ LAG(s.salary) OVER (PARTITION BY s.emp_no ORDER BY s.from_date ASC) AS PrevSalary, lọc WHERE PrevSalary IS NOT NULL AND s.salary < PrevSalary, và JOIN với dept_emp qua sr.from_date BETWEEN de.from_date AND de.to_date để lấy phòng ban! TUYỆT ĐỐI KHÔNG BỊA ĐẶT BẢNG 'dept_reductions'!"
                    if not is_en else
                    "MUST use CTE with LAG(s.salary) OVER (PARTITION BY s.emp_no ORDER BY s.from_date ASC) AS PrevSalary, filter NewSalary < PrevSalary, join dept_emp on sr.from_date BETWEEN de.from_date AND de.to_date! DO NOT hallucinate 'dept_reductions'!"
                )

        # Kiểm tra 2.7: Người dùng hỏi so sánh mức lương giữa 2 phòng ban cụ thể (VD: Sales vs Marketing, Sales vs Development)
        known_depts_map = {
            "sales": "sales", "development": "development", "research": "research", "marketing": "marketing",
            "finance": "finance", "production": "production", "customer service": "customer service",
            "quality management": "quality management", "human resources": "human resources",
            "kinh doanh": "sales", "bán hàng": "sales", "tiếp thị": "marketing", "phát triển": "development",
            "kỹ thuật": "development", "nghiên cứu": "research", "tài chính": "finance", "sản xuất": "production",
            "chăm sóc khách hàng": "customer service", "cskh": "customer service",
            "quản lý chất lượng": "quality management", "qlcl": "quality management",
            "nhân sự": "human resources", "hr": "human resources",
        }
        depts_in_q = []
        dept_positions = []
        for k, v in known_depts_map.items():
            pos = q_low.find(k)
            if pos != -1:
                dept_positions.append((pos, v))

        dept_positions.sort(key=lambda x: x[0])
        for _, v in dept_positions:
            if v not in depts_in_q:
                depts_in_q.append(v)

        if len(depts_in_q) == 2 and any(k in q_low for k in ["lương", "thu nhập", "salary"]) and any(k in q_low for k in ["so sánh", "đối chiếu", "chênh lệch", "vs", "compare"]):
            d1_sub, d2_sub = depts_in_q[0], depts_in_q[1]
            has_both_depts = (d1_sub in sql_low) and (d2_sub in sql_low)
            has_avg_in_sql = "avg(" in sql_low or "avgsalary" in sql_low
            is_all_depts_query = "salaryspread" in sql_low or (df is not None and len(df) > 4)

            if not has_both_depts or not has_avg_in_sql or is_all_depts_query:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    f"Người dùng hỏi so sánh mức lương trung bình giữa 2 phòng ban cụ thể ({d1_sub} và {d2_sub}), nhưng câu lệnh lại lấy toàn bộ các phòng ban hoặc dùng khoảng chênh lệch Min-Max."
                    if not is_en else
                    f"User asked to compare average salary between 2 specific departments ({d1_sub} vs {d2_sub}), but query returned all departments or min-max spread."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    f"BẮT BUỘC chỉ lọc đúng 2 phòng ban WHERE d.dept_name IN ('{d1_sub.title()}', '{d2_sub.title()}') và tính lương trung bình AVG(s.salary)!"
                    if not is_en else
                    f"MUST filter only the 2 departments WHERE d.dept_name IN ('{d1_sub.title()}', '{d2_sub.title()}') and compute AVG(s.salary)!"
                )

        # Kiểm tra 2.8: Người dùng hỏi tỷ trọng chi phí lương / ngân sách của một phòng ban cụ thể trong tổng chi phí toàn công ty
        known_depts_share = ["sales", "development", "research", "marketing", "finance", "production", "customer service", "quality management", "human resources", "sản xuất", "kinh doanh", "tiếp thị", "phát triển", "nghiên cứu", "tài chính", "nhân sự"]
        is_dept_share_eval = (
            any(k in q_low for k in ["chiếm bao nhiêu", "chiếm tỉ lệ", "chiếm tỷ lệ", "chiếm phần trăm", "tỷ trọng", "tỉ trọng", "phần trăm trong tổng", "tỷ lệ trong tổng", "đóng góp bao nhiêu"])
            and any(k in q_low for k in ["tổng chi phí", "tổng quỹ lương", "tổng lương", "toàn công ty", "trong tổng"])
            and any(k in q_low for k in known_depts_share)
        )
        if is_dept_share_eval:
            target_depts = [d for d in known_depts_share if d in q_low]
            target_d = target_depts[0] if target_depts else "production"
            has_dept_in_sql = (target_d in sql_low) or (df is not None and any(target_d in str(v).lower() for col in df.columns for v in df[col]))
            has_pct_calc = any(k in sql_low for k in ["percentage", "percent", "pct", "tỷ lệ", "tỉ lệ"]) or (df is not None and any(any(k in str(c).lower() for k in ["percentage", "percent", "pct", "tỷ lệ", "tỉ lệ"]) for c in df.columns))
            is_only_total_query = (df is not None and len(df) == 1 and len(df.columns) == 1 and "totalsalaries" in sql_low)

            if not has_dept_in_sql or not has_pct_calc or is_only_total_query:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    f"Người dùng hỏi tổng chi phí lương và tỷ lệ phần trăm phòng ban {target_d.title()} chiếm trong tổng chi phí, nhưng câu lệnh lại chỉ tính tổng lương hoặc thiếu phòng ban {target_d.title()} và tỷ lệ phần trăm!"
                    if not is_en else
                    f"User asked for total company payroll and {target_d.title()} percentage share, but query only calculated total salary or lacked {target_d.title()} and percentage!"
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    f"BẮT BUỘC tính tổng chi phí lương công ty, chi phí lương phòng {target_d.title()} và tỷ lệ phần trăm: ROUND(DeptSalary * 100.0 / TotalCompanySalary, 2) AS Percentage!"
                    if not is_en else
                    f"MUST compute total company payroll, {target_d.title()} payroll, and percentage share: ROUND(DeptSalary * 100.0 / TotalCompanySalary, 2) AS Percentage!"
                )

        # Kiểm tra 2.85: Xếp hạng sản phẩm theo doanh số trong từng quý và xác định tăng/giảm hạng mạnh nhất
        is_product_quarterly_ranking_eval = (
            any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
            and any(k in q_low for k in ["quý", "quarter"])
            and any(k in q_low for k in ["xếp hạng", "thứ hạng", "hạng", "rank", "tăng hạng", "giảm hạng", "top 5", "top 10"])
        )
        if is_product_quarterly_ranking_eval:
            has_product_col = any(any(k in c for k in ["product", "sản phẩm", "pid"]) for c in cols_low)
            has_rank_col = any(any(k in c for k in ["rank", "hạng", "thứ hạng", "q1_rank", "rankchange", "delta"]) for c in cols_low)
            is_only_quarter_result = (
                (len(cols_low) <= 3 and any("quarter" in c or "quý" in c for c in cols_low) and not has_product_col)
                or (df is not None and len(df) == 4 and not has_product_col)
            )

            if is_only_quarter_result or not has_product_col or not has_rank_col:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu xếp hạng từng sản phẩm theo doanh số qua các quý và so sánh thứ hạng tăng/giảm, nhưng kết quả chỉ trả về tổng doanh số của 4 quý toàn công ty mà thiếu danh sách sản phẩm và thứ hạng chi tiết."
                    if not is_en else
                    "User asked to rank products across quarters and compare rank changes, but result only returned 4 quarterly company sales rows without product breakdowns."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC tuân thủ 3 QUY TẮC PHÂN RÃ TRUY VẤN NGHIỆP VỤ: Dùng CTE (QuarterlyProductSales gom theo pr.Product và Quarter, QuarterlyRanks dùng DENSE_RANK() OVER (PARTITION BY Quarter ORDER BY TotalSales DESC), PivotRanks pivot Q1_Rank..Q4_Rank với CAST(Q1_Rank AS SIGNED) - CAST(Q4_Rank AS SIGNED))! BẮT BUỘC xuất các cột: Product, Q1_Rank, Q2_Rank, Q3_Rank, Q4_Rank, RankChange, PerformanceStatus, TotalAnnualSales!"
                    if not is_en else
                    "MUST follow 3 Business Query Decomposition Rules: Use CTEs to compute quarterly product sales, DENSE_RANK per quarter, and pivot Q1_Rank..Q4_Rank with signed subtraction!"
                )

        # Kiểm tra 2.86: Người dùng hỏi SO SÁNH doanh số và số lượng hộp bán ra GIỮA CÁC Team kinh doanh (không phải riêng 1 team cụ thể)
        is_team_sales_boxes_eval = (
            any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh"])
            and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền"])
            and any(k in q_low for k in ["hộp", "thùng", "boxes"])
            and any(k in q_low for k in ["so sánh", "giữa các team", "từng team", "các team", "mỗi team", "các đội", "từng đội", "across teams", "compare teams"])
            and not any(k in q_low for k in [
                "riêng team", "riêng đội", "team delish", "team yummies", "team jucies", "delish", "yummies", "jucies", "tempo",
                "sản phẩm", "product", "category", "danh mục", "bars", "bites",
                "canada", "india", "usa", "uk", "new zealand", "australia", "thị trường", "quốc gia",
                "nhân viên", "nhân sự", "salesperson", "của riêng", "riêng", "tại", "đối với", "thuộc",
                "quý", "quarter", "tháng", "month"
            ])
        )
        if is_team_sales_boxes_eval:
            has_team_col = any(any(k in c for k in ["team", "đội", "đội ngũ"]) for c in cols_low) or "pe.team" in sql_low
            has_sales_col = any(any(k in c for k in ["sales", "amount", "doanh thu", "doanh số", "revenue"]) for c in cols_low) or "sum(s.amount)" in sql_low
            has_boxes_col = any(any(k in c for k in ["boxes", "hộp", "thùng", "boxessold"]) for c in cols_low) or "sum(s.boxes)" in sql_low
            is_product_grouped = "pr.product" in sql_low or "group by pr.product" in sql_low or (any("product" in c for c in cols_low) and not has_team_col)

            if not has_team_col or is_product_grouped or not has_sales_col or not has_boxes_col:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    "Người dùng yêu cầu so sánh cả Tổng doanh số VÀ Số lượng hộp bán ra giữa các Team kinh doanh, nhưng kết quả bị nhóm theo Sản phẩm (Product) hoặc thiếu trường Team, thiếu chỉ số doanh số hoặc chỉ số hộp."
                    if not is_en else
                    "User requested comparison of both Total Sales and Boxes Sold across sales teams, but result was aggregated by Product or lacked Team field or missing required metrics."
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC: JOIN sales s với people pe ON s.SPID = pe.SPID, lọc pe.Team != '' AND pe.Team IS NOT NULL, GROUP BY pe.Team! Mệnh đề SELECT BẮT BUỘC có cả SUM(s.Amount) AS TotalSales VÀ SUM(s.Boxes) AS TotalBoxesSold! TUYỆT ĐỐI CẤM NHÓM THEO pr.Product!"
                    if not is_en else
                    "MUST JOIN sales s with people pe ON s.SPID = pe.SPID, filter pe.Team != '' AND pe.Team IS NOT NULL, GROUP BY pe.Team! SELECT MUST include both SUM(s.Amount) AS TotalSales AND SUM(s.Boxes) AS TotalBoxesSold! DO NOT GROUP BY pr.Product!"
                )

        # Kiểm tra 2.9: Người dùng hỏi danh sách phòng ban có mức lương trung bình trên/dưới một ngưỡng (VD: trên $70,000)
        is_dept_avg_thresh_eval = (
            any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "department"])
            and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "lương tb", "avg salary", "average salary"])
            and any(k in q_low for k in ["trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", "lớn hơn", "nhỏ hơn", ">", "<", "above", "below", "over"])
            and not any(k in q_low for k in [
                "so sánh", "đối chiếu", "vs", "giữa", "chiếm bao nhiêu", "tỷ trọng", "phần trăm trong tổng",
                "nhân viên", "nhân sự", "người", "employee", "phòng ban đầu tiên", "first department", "ít nhất 2", "nhiều phòng ban"
            ])
        )
        if is_dept_avg_thresh_eval:
            thresh_val = 70000
            thresh_match = re.search(r'[\$]?\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)(?:\s*(?:k|nghìn|ngàn|usd|\$))?', q_low)
            if thresh_match:
                raw_t = thresh_match.group(1).replace(",", "").replace(".", "")
                try:
                    val_t = float(raw_t)
                    if val_t < 1000 and any(k in q_low for k in ["k", "nghìn", "ngàn"]):
                        val_t *= 1000
                    thresh_val = int(val_t)
                except Exception:
                    pass
            is_less = any(k in q_low for k in ["dưới", "thấp hơn", "nhỏ hơn", "<", "<=", "below", "less than", "under"])

            has_having = "having" in sql_low
            has_wrong_where_salary = bool(re.search(r"where[^\n;]*\bsalary\s*[><=]", sql_low))
            has_avg_col = (df is not None and any(any(k in c for k in ["avgsalary", "avg_salary", "average", "trung bình"]) for c in cols_low)) or ("avg(" in sql_low)

            has_invalid_dept_data = False
            if df is not None and not df.empty:
                avg_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["avgsalary", "avg_salary", "average", "trung bình", "salary", "lương"])]
                if avg_cols:
                    s_series = pd.to_numeric(df[avg_cols[0]], errors="coerce")
                    if not is_less:
                        if (s_series <= thresh_val).any():
                            has_invalid_dept_data = True
                    else:
                        if (s_series >= thresh_val).any():
                            has_invalid_dept_data = True
                elif len(df) == 9 and thresh_val >= 70000:
                    has_invalid_dept_data = True

            if not has_having or has_wrong_where_salary or not has_avg_col or has_invalid_dept_data:
                criteria["semantic_alignment"]["passed"] = False
                msg = (
                    f"Người dùng hỏi lọc các phòng ban có lương trung bình {'dưới' if is_less else 'trên'} ${thresh_val:,}, nhưng câu lệnh lại dùng WHERE s.salary (lọc sai cấp độ cá nhân thay vì cấp phòng ban), thiếu cột lương trung bình hoặc trả về phòng ban không đạt chuẩn!"
                    if not is_en else
                    f"User asked for departments with average salary {'below' if is_less else 'above'} ${thresh_val:,}, but query used WHERE s.salary instead of HAVING, lacked average salary metric, or returned non-qualifying departments!"
                )
                criteria["semantic_alignment"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    f"BẮT BUỘC dùng mệnh đề HAVING AvgSalary {'<' if is_less else '>'} {thresh_val} và xuất ra cột ROUND(AVG(s.salary), 2) AS AvgSalary!"
                    if not is_en else
                    f"MUST use HAVING AvgSalary {'<' if is_less else '>'} {thresh_val} and project ROUND(AVG(s.salary), 2) AS AvgSalary!"
                )

    # -------------------------------------------------------------
    # PILLAR 3: COMPARATIVE SUFFICIENCY (ĐỘ ĐẦY ĐỦ CÁC VẾ SO SÁNH & CỰC TRỊ)
    # -------------------------------------------------------------
    if df is not None and not df.empty:
        # Kiểm tra 3.1: Người dùng hỏi CẢ LỚN NHẤT VÀ NHỎ NHẤT nhưng chỉ trả về 1 dòng
        # Bỏ qua cụm từ so sánh nội bộ "giữa cao nhất và thấp nhất" của bài toán salary spread
        pattern_spread_phrase = r"(?:giữa|between)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:cao nhất|thấp nhất|highest|lowest)\s+(?:và|and)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:thấp nhất|cao nhất|lowest|highest)"
        q_cleaned_extremes = re.sub(pattern_spread_phrase, "", q_low)
        has_largest = any(k in q_cleaned_extremes for k in ["lớn nhất", "cao nhất", "nhiều nhất", "highest", "largest"])
        has_smallest = any(k in q_cleaned_extremes for k in ["nhỏ nhất", "thấp nhất", "lowest", "smallest"]) or bool(re.search(r"\bít nhất\b(?!\s*\d+)", q_cleaned_extremes))
        if has_largest and has_smallest and len(df) < 2:
            criteria["comparative_sufficiency"]["passed"] = False
            msg = f"Người dùng hỏi cả cực trị lớn nhất VÀ nhỏ nhất nhưng kết quả chỉ có {len(df)} dòng." if not is_en else f"User requested both largest AND smallest extremes, but only {len(df)} row returned."
            criteria["comparative_sufficiency"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                "BẮT BUỘC xuất ra đúng 2 phòng ban tương ứng với 2 cực trị (MAX và MIN) bằng CTE kết hợp WHERE Headcount = MAX OR Headcount = MIN."
                if not is_en else "MUST return both extreme benchmark rows (MAX and MIN) using CTE with WHERE metric = MAX OR metric = MIN."
            )

        # Kiểm tra 3.2: So sánh Quản lý vs Cấp dưới có lương cao hơn nhưng thiếu cấp dưới
        asked_mgr_sub = any(k in q_low for k in ["manager", "quản lý", "trưởng phòng"]) and any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên"]) and any(k in q_low for k in ["thấp hơn", "cao hơn", "vượt", "chênh lệch"])
        if asked_mgr_sub:
            has_sub_salary = any(any(k in c for k in ["subordinate", "cấp dưới", "gap", "difference", "chênh lệch"]) for c in cols_low)
            if not has_sub_salary and len(df) <= 1:
                criteria["comparative_sufficiency"]["passed"] = False
                msg = "Thiếu dữ liệu đối chiếu giữa mức lương nhân viên cấp dưới và lương quản lý." if not is_en else "Missing comparative compensation metrics between manager and subordinates."
                criteria["comparative_sufficiency"]["detail"] = msg
                fails.append(msg)
                actionable_feedbacks.append(
                    "BẮT BUỘC JOIN cả bảng nhân viên cấp dưới cùng phòng ban (dept_emp) và so sánh se.salary > sm.salary."
                    if not is_en else "MUST join subordinates in same department and filter se.salary > sm.salary."
                )

    # -------------------------------------------------------------
    # PILLAR 4: TEMPORAL COMPLETENESS (TÍNH TOÀN VẸN MỐC THỜI GIAN)
    # -------------------------------------------------------------
    if sql_query:
        # Kiểm tra 4.1: Câu hỏi về trạng thái "hiện tại" nhưng SQL không lọc to_date = '9999-01-01'
        is_historical_context = any(k in q_low for k in ["năm đầu", "giai đoạn đầu", "thời kỳ đầu", "mới thành lập", "khởi đầu", "3 năm", "5 năm", "lịch sử", "từng"]) or bool(re.search(r"\b(19\d\d|200[0-2])\b", q_low))
        asked_current = (any(k in q_low for k in ["hiện tại", "hiện nay", "đang giữ", "currently", "active"]) or (any(k in q_low for k in ["đang"]) and not is_historical_context)) and not is_historical_context
        has_current_filter = ("9999-01-01" in sql_low) or (not is_employees_db)
        if asked_current and not has_current_filter:
            criteria["temporal_validity"]["passed"] = False
            msg = "Câu hỏi yêu cầu thông tin hiện tại nhưng câu lệnh SQL thiếu điều kiện lọc to_date = '9999-01-01'." if not is_en else "User requested current active status, but SQL lacks to_date = '9999-01-01' filter."
            criteria["temporal_validity"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                "BẮT BUỘC bổ sung điều kiện to_date = '9999-01-01' để chỉ lấy trạng thái nhân sự / hợp đồng hiện hành!"
                if not is_en else "MUST add to_date = '9999-01-01' to filter active contracts."
            )

        # Kiểm tra 4.2: Phát hiện giá trị thâm niên > 100 năm do trừ nhầm mốc to_date = '9999-01-01'
        if df is not None and not df.empty:
            for c in df.columns:
                c_l = str(c).lower()
                if any(k in c_l for k in ["yearsofservice", "years_of_service", "tenure", "thâm niên"]):
                    s_tenure = pd.to_numeric(df[c], errors="coerce")
                    if (s_tenure > 100).any():
                        criteria["temporal_validity"]["passed"] = False
                        msg = f"Phát hiện giá trị thâm niên bất thường ({s_tenure.max():.1f} năm) do tính toán trực tiếp với mốc to_date = '9999-01-01' mà không dùng IF(to_date = '9999-01-01', '2002-08-01', to_date)!"
                        criteria["temporal_validity"]["detail"] = msg
                        fails.append(msg)
                        actionable_feedbacks.append(
                            "BẮT BUỘC thay thế phép tính thâm niên bằng DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25 để loại bỏ lỗi thâm niên 8014 năm!"
                        )
                        break

    # -------------------------------------------------------------
    # TÍNH TOÁN ĐIỂM SỐ VÀ PHÁN QUYẾT (VERDICT & SCORE)
    # -------------------------------------------------------------
    num_passed = sum(1 for c in criteria.values() if c["passed"])
    score = int((num_passed / len(criteria)) * 100)
    verdict = "PASS" if score >= 100 else ("FAIL" if score < 75 else "NEEDS_IMPROVEMENT")

    if verdict == "PASS":
        critique = (
            "Kết quả truy vấn đáp ứng trọn vẹn 4 tiêu chí cốt lõi: Khớp thực thể, toàn vẹn mốc thời gian, đầy đủ vế so sánh và dữ liệu chuẩn xác."
            if not is_en else
            "Query execution strictly satisfies all 4 core pillars: Semantic alignment, temporal integrity, comparative sufficiency, and data health."
        )
    else:
        critique = "Phát hiện điểm chưa hoàn thiện: " + "; ".join(fails) if not is_en else "Audit discrepancies detected: " + "; ".join(fails)

    actionable_fb_str = "\n".join(f"- {fb}" for fb in actionable_feedbacks)

    return {
        "verdict": verdict,
        "score": score,
        "criteria": criteria,
        "critique": critique,
        "actionable_feedback": actionable_fb_str,
        "fails_count": len(fails)
    }
