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
        asked_for_employees = any(k in q_low for k in ["nhân viên", "nhân sự", "danh sách", "liệt kê", "ai là", "employee", "employees"])
        has_employee_col = (
            any(k in cols_low for k in ["fullname", "full_name", "first_name", "last_name", "emp_no", "empno", "name", "tên nhân viên", "họ và tên"])
            or any(is_id_like(c) for c in df.columns)
        )
        is_asking_only_dept_count = any(k in q_low for k in ["phòng ban nào", "mỗi phòng ban", "theo phòng ban", "từng phòng ban", "quy mô"]) and not any(k in q_low for k in ["những nhân viên", "các nhân viên", "danh sách nhân viên"])

        if asked_for_employees and not has_employee_col and not is_asking_only_dept_count:
            criteria["semantic_alignment"]["passed"] = False
            msg = "Người dùng hỏi thông tin nhân sự nhưng dữ liệu chỉ trả về cấp phòng ban/đơn vị." if not is_en else "User queried employee-level records but result only provided department aggregates."
            criteria["semantic_alignment"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                "BẮT BUỘC thêm thông tin cá nhân nhân viên (e.emp_no, CONCAT(e.first_name, ' ', e.last_name) AS FullName) vào câu lệnh SELECT."
                if not is_en else "MUST include individual employee attributes (e.emp_no, FullName) in SELECT statement."
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
        asked_multi_dept = any(k in q_low for k in ["nhiều phòng ban", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng"]) and asked_for_employees
        has_dept_count = any(k in cols_low for k in ["departmentcount", "dept_count", "department_count", "số phòng ban", "count"])
        if asked_multi_dept and not has_dept_count:
            criteria["semantic_alignment"]["passed"] = False
            msg = "Thiếu chỉ số đếm số phòng ban đã trải qua (COUNT(DISTINCT de.dept_no))." if not is_en else "Missing distinct department count metric (COUNT(DISTINCT de.dept_no))."
            criteria["semantic_alignment"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                "BẮT BUỘC đếm số phòng ban qua COUNT(DISTINCT de.dept_no) AS DepartmentCount và lọc HAVING COUNT(DISTINCT de.dept_no) >= 2."
                if not is_en else "MUST include COUNT(DISTINCT de.dept_no) AS DepartmentCount and HAVING COUNT(DISTINCT de.dept_no) >= 2."
            )

    # -------------------------------------------------------------
    # PILLAR 3: COMPARATIVE SUFFICIENCY (ĐỘ ĐẦY ĐỦ CÁC VẾ SO SÁNH & CỰC TRỊ)
    # -------------------------------------------------------------
    if df is not None and not df.empty:
        # Kiểm tra 3.1: Người dùng hỏi CẢ LỚN NHẤT VÀ NHỎ NHẤT nhưng chỉ trả về 1 dòng
        has_largest = any(k in q_low for k in ["lớn nhất", "cao nhất", "nhiều nhất", "highest", "largest"])
        has_smallest = any(k in q_low for k in ["nhỏ nhất", "thấp nhất", "ít nhất", "lowest", "smallest"])
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
        asked_current = any(k in q_low for k in ["hiện tại", "hiện nay", "đang", "đang giữ", "currently", "active"])
        has_current_filter = "9999-01-01" in sql_low
        if asked_current and not has_current_filter:
            criteria["temporal_validity"]["passed"] = False
            msg = "Câu hỏi yêu cầu thông tin hiện tại nhưng câu lệnh SQL thiếu điều kiện lọc to_date = '9999-01-01'." if not is_en else "User requested current active status, but SQL lacks to_date = '9999-01-01' filter."
            criteria["temporal_validity"]["detail"] = msg
            fails.append(msg)
            actionable_feedbacks.append(
                "BẮT BUỘC bổ sung điều kiện to_date = '9999-01-01' để chỉ lấy trạng thái nhân sự / hợp đồng hiện hành!"
                if not is_en else "MUST add to_date = '9999-01-01' to filter active contracts."
            )

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
