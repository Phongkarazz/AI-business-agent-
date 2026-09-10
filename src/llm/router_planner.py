"""
Router and Task Planner Module (Tầng 1: Phân luồng & Lập kế hoạch thực thi - Chia để trị)
Phân loại độ phức tạp của câu hỏi người dùng (Direct vs Multi-step Analytic),
trích xuất thực thể, thước đo, điều kiện thời gian và phân rã thành chuỗi nhiệm vụ con (Sub-tasks Decomposition)
cho hệ thống Autonomous Data Agent Veraxus.
"""

import re
from typing import Dict, Any, List, Optional
from src.analytics.heuristics import detect_query_language
from .client import call_llm


def classify_query_complexity(user_query: str) -> str:
    """Phân loại độ phức tạp của câu hỏi:
    - MULTI_STEP_ANALYTIC: Tăng trưởng theo thời gian, so sánh chéo đa cấp, tỷ lệ Pareto 80/20, nhân viên đa phòng ban.
    - BENCHMARK_EXTREMES: Tìm đồng thời 2 cực trị (lớn nhất VÀ nhỏ nhất, khoảng cách chênh lệch cực trị).
    - TIME_SERIES_COHORT: Tuyển dụng qua các năm, chuỗi thời gian nhiều mốc.
    - DIRECT_SQL: Truy vấn trực tiếp 1 bước (xếp hạng đơn, lọc điều kiện, xem danh sách).
    """
    if not user_query:
        return "DIRECT_SQL"
    q_low = user_query.lower()

    # 1. Nhận diện bài toán phân tích tăng trưởng hoặc chênh lệch lương đa mốc
    if any(k in q_low for k in ["tăng trưởng", "tốc độ tăng", "mỗi năm", "annual growth", "growth rate", "so sánh mức lương", "chênh lệch lương giữa", "cấp dưới", "lương thấp hơn"]):
        return "MULTI_STEP_ANALYTIC"

    # 1.1 Nhận diện bài toán phân tích phân vị kết hợp lịch sử tăng lương (Percentile Cohort / Low raises with top salary)
    if (
        any(k in q_low for k in ["top 10%", "top 5%", "top 20%", "top %", "percentile", "bách phân vị"])
        or (any(k in q_low for k in ["tăng lương", "lần tăng"]) and any(k in q_low for k in ["ít hơn", "dưới", "nhỏ hơn", "nhưng"]))
    ):
        return "MULTI_STEP_ANALYTIC"

    # 2. Nhận diện bài toán đa phòng ban hoặc chuyển đổi trạng thái
    if (
        any(k in q_low for k in ["nhiều phòng ban", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng", "luân chuyển", "chuyển phòng"])
        and any(k in q_low for k in ["nhân viên", "nhân sự", "ai", "danh sách", "liệt kê"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 3. Nhận diện bài toán Pareto 80/20
    if any(k in q_low for k in ["80/20", "pareto", "80% doanh", "tích lũy", "cumulative"]):
        return "MULTI_STEP_ANALYTIC"

    # 4. Nhận diện bài toán so sánh cực trị (Lớn nhất VÀ nhỏ nhất)
    has_largest = any(k in q_low for k in ["lớn nhất", "cao nhất", "nhiều nhất", "đông nhất", "highest", "largest"])
    has_smallest = any(k in q_low for k in ["nhỏ nhất", "thấp nhất", "lowest", "smallest"]) or bool(re.search(r"\bít nhất\b(?!\s*\d+)", q_low))
    if has_largest and has_smallest:
        return "BENCHMARK_EXTREMES"

    # 5. Nhận diện bài toán xu hướng chuỗi thời gian dài hạn
    if any(k in q_low for k in ["qua các năm", "theo từng năm", "theo từng tháng", "hàng năm", "biến động tổng", "over time", "yearly trend"]):
        return "TIME_SERIES_COHORT"

    return "DIRECT_SQL"


def decompose_subtasks(user_query: str, complexity: str, lang: str = "vi") -> List[Dict[str, Any]]:
    """Phân rã câu hỏi thành chuỗi các nhiệm vụ con (Sub-tasks Decomposition) theo nguyên lý Chia để trị."""
    q_low = (user_query or "").lower()
    is_en = (lang == "en")

    # Mẫu 0: Nhân viên có số lần tăng lương ít nhưng lương thuộc top cao nhất (Low Raises & Top Percentile Cohort)
    if any(k in q_low for k in ["tăng lương", "lần tăng"]) and any(k in q_low for k in ["ít hơn", "dưới", "nhỏ hơn", "chưa quá", "tối đa"]):
        m_r = re.search(r"(\d+)\s*lần", q_low)
        limit_raises_str = m_r.group(1) if m_r else "5"
        m_p = re.search(r"top\s*(\d+)\s*%", q_low)
        pct_str = m_p.group(1) if m_p else "10"
        return [
            {
                "step": 1,
                "name": "Xác định phân vị lương hiện tại toàn công ty" if not is_en else "Compute company-wide salary percentile",
                "desc": f"Tính toán phân vị PERCENT_RANK() cho nhân viên đang công tác (to_date = '9999-01-01') để định vị nhóm top {pct_str}% cao nhất." if not is_en else f"Compute PERCENT_RANK() for active employees to isolate top {pct_str}% earners.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Thống kê số lần tăng lương trong lịch sử" if not is_en else "Aggregate historical salary raises",
                "desc": f"Đếm số lần điều chỉnh lương trong lịch sử từ bảng salaries và lọc nhóm có số lần tăng lương ít hơn {limit_raises_str} lần: HAVING COUNT(s.salary) < {limit_raises_str}." if not is_en else f"Count distinct salary adjustments and filter: HAVING COUNT(s.salary) < {limit_raises_str}.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Giao thoa đối chiếu 2 điều kiện nghiệp vụ" if not is_en else "Cross-reference cohort conditions",
                "desc": f"Kết hợp nhóm nhân viên thuộc top {pct_str}% lương cao nhất với nhóm nhân viên có số lần tăng lương ít hơn {limit_raises_str} lần." if not is_en else f"Intersect top {pct_str}% salary cohort with employees having fewer than {limit_raises_str} raises.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trích xuất danh sách nhân sự & xếp hạng" if not is_en else "Extract ranked employee roster",
                "desc": "Hiển thị họ tên, phòng ban, mức lương hiện tại, số lần tăng lương và bách phân vị lương, sắp xếp theo mức lương giảm dần." if not is_en else "Display FullName, Department, CurrentSalary, RaiseCount, and Percentile ordered by salary DESC.",
                "status": "done"
            }
        ]

    # Mẫu 1: Tăng trưởng lương nhân viên theo thời gian (Salary Growth Rate)
    if any(k in q_low for k in ["tăng trưởng", "mỗi năm", "tốc độ"]) and any(k in q_low for k in ["lương", "salary"]):
        dept_match = "phòng ban mục tiêu"
        for d in ["sales", "marketing", "development", "research", "finance", "human resources", "customer service", "production", "quality management"]:
            if d in q_low:
                dept_match = f"phòng ban {d.title()}"
                break
        return [
            {
                "step": 1,
                "name": "Xác định mốc khởi điểm (Baseline)" if not is_en else "Identify Baseline Starting Salary",
                "desc": f"Trích xuất mức lương khởi điểm từ bảng salaries tại ngày tuyển dụng (s_start.from_date = e.hire_date) của nhân viên {dept_match}."
                if not is_en else f"Extract starting salary from salaries table at hire date (s_start.from_date = e.hire_date) for {dept_match}."
            },
            {
                "step": 2,
                "name": "Xác định mốc hiện hành (Current State)" if not is_en else "Identify Current Compensation",
                "desc": "Lấy mức lương mới nhất đang hưởng (s_curr.to_date = '9999-01-01') và xác thực nhân viên vẫn đang công tác (de.to_date = '9999-01-01')."
                if not is_en else "Retrieve latest salary (s_curr.to_date = '9999-01-01') and verify active employment (de.to_date = '9999-01-01')."
            },
            {
                "step": 3,
                "name": "Tính toán tốc độ tăng trưởng hàng năm (Growth Delta)" if not is_en else "Calculate Annualized Growth Rate",
                "desc": "Tính chênh lệch lương chia cho số năm công tác thực tế: (s_curr.salary - s_start.salary) / (DATEDIFF / 365.25)."
                if not is_en else "Calculate annualized growth: (s_curr.salary - s_start.salary) / (DATEDIFF / 365.25)."
            },
            {
                "step": 4,
                "name": "Xếp hạng & Giới hạn Top N" if not is_en else "Rank & Filter Top N",
                "desc": "Sắp xếp giảm dần theo tốc độ tăng trưởng trung bình mỗi năm (ORDER BY AvgAnnualSalaryGrowth DESC) và giới hạn số lượng kết quả."
                if not is_en else "Order descending by annual growth rate and cap requested limit."
            }
        ]

    # Mẫu 2: Nhân viên từng công tác qua nhiều phòng ban (Multi-department Employees)
    if any(k in q_low for k in ["nhiều phòng", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng", "2 phòng ban"]) and any(k in q_low for k in ["nhân viên", "nhân sự", "liệt kê"]):
        target_title = "chức danh yêu cầu"
        if "senior engineer" in q_low:
            target_title = "Senior Engineer"
        elif "engineer" in q_low:
            target_title = "Engineer"
        elif "manager" in q_low:
            target_title = "Manager"
        elif "staff" in q_low:
            target_title = "Staff"
        return [
            {
                "step": 1,
                "name": "Lọc chức danh hiện hành" if not is_en else "Filter Current Job Title",
                "desc": f"Xác thực nhân viên hiện đang giữ chức danh {target_title} (titles.to_date = '9999-01-01')."
                if not is_en else f"Filter active employees holding title {target_title} (titles.to_date = '9999-01-01')."
            },
            {
                "step": 2,
                "name": "Gom nhóm lịch sử luân chuyển phòng ban" if not is_en else "Aggregate Department History",
                "desc": "Đếm số lượng phòng ban phân biệt mà mỗi nhân viên từng trải qua: COUNT(DISTINCT de.dept_no) >= 2."
                if not is_en else "Count distinct departments worked across entire tenure: COUNT(DISTINCT de.dept_no) >= 2."
            },
            {
                "step": 3,
                "name": "Ánh xạ phòng ban công tác hiện tại" if not is_en else "Map Current Active Department",
                "desc": "Liên kết với hợp đồng phòng ban hiện hành (dept_emp.to_date = '9999-01-01') để lấy tên phòng hiện tại."
                if not is_en else "Join active department assignment (dept_emp.to_date = '9999-01-01') to fetch current department name."
            },
            {
                "step": 4,
                "name": "Xuất danh sách nhân sự đối soát" if not is_en else "Project & Order Final Cohort",
                "desc": "Sắp xếp theo số phòng ban giảm dần và mã nhân viên, giới hạn kết quả trả về."
                if not is_en else "Order by department count descending and employee number, applying requested limit."
            }
        ]

    # Mẫu 3: So sánh Cực trị (Lớn nhất VÀ Nhỏ nhất - Benchmark Extremes)
    if complexity == "BENCHMARK_EXTREMES":
        return [
            {
                "step": 1,
                "name": "Tổng hợp chỉ số theo từng thực thể" if not is_en else "Aggregate Entity Metrics",
                "desc": "Gom nhóm dữ liệu theo từng phòng ban/đơn vị và tính tổng chỉ số đo lường (Headcount / Quỹ lương / Doanh số)."
                if not is_en else "Group by entity and compute aggregated metric (Headcount / Salary / Sales)."
            },
            {
                "step": 2,
                "name": "Xác định 2 giá trị cực trị (Max & Min)" if not is_en else "Identify Extreme Values (Max & Min)",
                "desc": "Sử dụng CTE hoặc Subquery để tìm chính xác giá trị Lớn nhất (MAX) và Nhỏ nhất (MIN) trên toàn bộ danh mục."
                if not is_en else "Use CTE/Subquery to isolate exact Maximum and Minimum values across all entities."
            },
            {
                "step": 3,
                "name": "Lọc đối chiếu song song 2 thực thể cực trị" if not is_en else "Filter Dual Extreme Benchmarks",
                "desc": "Chỉ lấy các đơn vị thỏa mãn điều kiện cực đại HOẶC cực tiểu, loại bỏ các đơn vị trung gian để làm nổi bật khoảng cách."
                if not is_en else "Select only entities matching MAX or MIN, filtering out intermediate records."
            }
        ]

    # Mẫu 4: Quản lý có lương thấp hơn nhân viên cấp dưới (Hierarchical Compensation Inversion)
    if any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"]) and any(k in q_low for k in ["cấp dưới", "nhân viên", "dưới quyền"]) and any(k in q_low for k in ["thấp hơn", "cao hơn", "vượt", "chênh lệch"]):
        return [
            {
                "step": 1,
                "name": "Xác định Trưởng phòng đương nhiệm" if not is_en else "Identify Active Department Managers",
                "desc": "Lấy danh sách các Trưởng phòng hiện tại (dept_manager.to_date = '9999-01-01') kèm mức lương mới nhất."
                if not is_en else "Fetch active managers (dept_manager.to_date = '9999-01-01') and their current salaries."
            },
            {
                "step": 2,
                "name": "Liên kết nhân viên trực thuộc cùng phòng" if not is_en else "Join Direct Department Subordinates",
                "desc": "Liên kết với các nhân viên đang công tác cùng phòng ban (dept_emp.to_date = '9999-01-01') loại trừ chính quản lý."
                if not is_en else "Join active department employees (dept_emp.to_date = '9999-01-01') excluding the manager."
            },
            {
                "step": 3,
                "name": "Lọc điều kiện nghịch đảo thu nhập" if not is_en else "Filter Compensation Inversion",
                "desc": "So khớp điều kiện lương cấp dưới cao hơn lương quản lý (se.salary > sm.salary) và tính khoảng chênh lệch."
                if not is_en else "Apply condition subordinate salary > manager salary (se.salary > sm.salary) and compute delta."
            },
            {
                "step": 4,
                "name": "Tổng hợp đối chiếu chênh lệch" if not is_en else "Synthesize Pay Discrepancy",
                "desc": "Sắp xếp theo độ lệch giảm dần để xác định phòng ban có hiện tượng phân hóa đãi ngộ mạnh nhất."
                if not is_en else "Order by salary gap descending to highlight key compensation inversion areas."
            }
        ]

    # Mẫu 5: Chuỗi thời gian theo năm / tháng (Time Series Cohort)
    if complexity == "TIME_SERIES_COHORT":
        return [
            {
                "step": 1,
                "name": "Chuẩn hóa trục thời gian" if not is_en else "Standardize Time Axis",
                "desc": "Trích xuất mốc năm/tháng bằng hàm YEAR/DATE_FORMAT và xác thực tính liên tục của dữ liệu lịch sử."
                if not is_en else "Extract year/month components and verify historical continuity."
            },
            {
                "step": 2,
                "name": "Tính toán chỉ số lũy kế / tổng hợp theo kỳ" if not is_en else "Aggregate Periodic Metrics",
                "desc": "Tính tổng hoặc mức trung bình chỉ số cho từng kỳ thời gian."
                if not is_en else "Compute periodic aggregations (SUM/AVG/COUNT) per time bucket."
            },
            {
                "step": 3,
                "name": "Sắp xếp theo thứ tự thời gian tuần tự" if not is_en else "Chronological Ordering",
                "desc": "Sắp xếp tăng dần theo mốc thời gian (ORDER BY Year ASC) để phục vụ phân tích xu hướng và dự báo."
                if not is_en else "Sort chronologically (ORDER BY Year ASC) to feed trend analysis and forecasting."
            }
        ]

    # Mặc định: Truy vấn trực tiếp đơn giản (Direct SQL Execution)
    return [
        {
            "step": 1,
            "name": "Xác định bảng & trường dữ liệu trọng tâm" if not is_en else "Identify Target Tables & Attributes",
            "desc": "Xác định các bảng liên quan trong CSDL và lọc các trường dữ liệu cần thiết cho câu hỏi."
            if not is_en else "Resolve target database tables and attributes required for the query."
        },
        {
            "step": 2,
            "name": "Thực thi truy vấn & Sắp xếp tối ưu" if not is_en else "Execute Query & Optimize Ordering",
            "desc": "Áp dụng điều kiện WHERE, gom nhóm GROUP BY và giới hạn số bản ghi thích hợp để tối ưu tốc độ."
            if not is_en else "Apply WHERE filters, GROUP BY grouping, and optimal ordering with LIMIT."
        }
    ]


def route_and_plan(
    user_query: str,
    schema_context: str = "",
    dialect: str = "MySQL",
    client: Any = None,
    provider: str = "",
    model_name: str = "",
    lang: str = "vi"
) -> Dict[str, Any]:
    """Tác tử Router & Task Planner:
    1. Phân loại độ phức tạp câu hỏi.
    2. Trích xuất mục tiêu phân tích (Entities, Metrics, Filters, Time Horizon).
    3. Phân rã bài toán thành chuỗi nhiệm vụ con (Sub-tasks Execution Plan).
    4. Sinh chỉ dẫn tối ưu cho bước sinh SQL.
    """
    if not user_query:
        return {
            "complexity": "DIRECT_SQL",
            "intent": "Không xác định",
            "sub_tasks": [],
            "target_entities": [],
            "target_metrics": [],
            "time_horizon": "N/A",
            "execution_strategy": "Direct Query"
        }

    lang = detect_query_language(user_query) if not lang else lang
    is_en = (lang == "en")
    q_low = user_query.lower()

    # 1. Phân loại độ phức tạp
    complexity = classify_query_complexity(user_query)

    # 2. Phân rã nhiệm vụ con (Sub-tasks)
    sub_tasks = decompose_subtasks(user_query, complexity, lang=lang)

    # 3. Trích xuất thực thể và thước đo mục tiêu
    entities = []
    if any(k in q_low for k in ["nhân viên", "nhân sự", "người", "employee"]):
        entities.append("employees")
    if any(k in q_low for k in ["phòng ban", "phòng", "department"]):
        entities.append("departments")
    if any(k in q_low for k in ["lương", "thu nhập", "salary", "bảng lương"]):
        entities.append("salaries")
    if any(k in q_low for k in ["chức danh", "vị trí", "title"]):
        entities.append("titles")
    if any(k in q_low for k in ["quản lý", "trưởng phòng", "manager"]):
        entities.append("dept_manager")
    if any(k in q_low for k in ["sản phẩm", "product", "kẹo", "hộp"]):
        entities.append("products")
    if any(k in q_low for k in ["bán hàng", "doanh số", "sales"]):
        entities.append("sales")

    metrics = []
    if any(k in q_low for k in ["tăng trưởng", "growth"]):
        metrics.append("Tốc độ tăng trưởng hàng năm (AvgAnnualSalaryGrowth)")
    elif any(k in q_low for k in ["lương trung bình", "avg salary"]):
        metrics.append("Lương trung bình (AvgSalary)")
    elif any(k in q_low for k in ["lương", "salary"]):
        metrics.append("Mức lương (Salary)")
    if any(k in q_low for k in ["quy mô", "nhân sự", "số lượng", "headcount", "đông nhất"]):
        metrics.append("Quy mô nhân sự (Headcount)")
    if any(k in q_low for k in ["thâm niên", "tenure", "năm làm việc"]):
        metrics.append("Thâm niên công tác (YearsOfService)")
    if any(k in q_low for k in ["lần tăng lương", "số lần tăng"]):
        metrics.append("Số lần tăng lương (RaiseCount)")

    # 4. Xác định mốc thời gian
    if any(k in q_low for k in ["hiện tại", "hiện nay", "đang", "đương nhiệm", "current"]):
        time_horizon = "Thời điểm hiện tại (to_date = '9999-01-01')" if not is_en else "Current active state (to_date = '9999-01-01')"
    elif any(k in q_low for k in ["2002", "năm 2002"]):
        time_horizon = "Mốc lịch sử 2002 (Cut-off 2002-08-01)" if not is_en else "Historical benchmark year 2002"
    elif any(k in q_low for k in ["toàn bộ lịch sử", "lịch sử", "từng làm", "all time"]):
        time_horizon = "Toàn bộ lịch sử hoạt động" if not is_en else "All-time historical records"
    else:
        time_horizon = "Mặc định theo phạm vi dữ liệu" if not is_en else "Default data boundary"

    # 5. Xác định chiến lược thực thi
    if complexity == "MULTI_STEP_ANALYTIC":
        strategy = "Sử dụng CTE / Index Join tối ưu qua Primary Key để tính toán đa bước trong < 1.0s" if not is_en else "Use optimized index joins / CTE to execute multi-step computation in < 1.0s"
    elif complexity == "BENCHMARK_EXTREMES":
        strategy = "Truy vấn 2 cực trị độc lập và kết hợp đối chiếu song song" if not is_en else "Isolate dual extremes and synthesize side-by-side"
    else:
        strategy = "Truy vấn trực tiếp có chỉ mục và giới hạn kết quả phù hợp" if not is_en else "Direct indexed query with optimal limit"

    intent_summary = f"Phân tích {complexity.lower()}: {user_query}" if not is_en else f"Analyze {complexity.lower()}: {user_query}"

    return {
        "complexity": complexity,
        "intent": intent_summary,
        "sub_tasks": sub_tasks,
        "target_entities": entities,
        "target_metrics": metrics,
        "time_horizon": time_horizon,
        "execution_strategy": strategy,
        "num_steps": len(sub_tasks)
    }
