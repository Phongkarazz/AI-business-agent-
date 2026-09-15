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

    # 0.85 Nhận diện bài toán phủ định / tập hợp loại trừ (Anti-Join / Negative Filter / NOT IN / NOT EXISTS)
    # Ví dụ: "Liệt kê những nhân viên kinh doanh chưa từng bán được bất kỳ một hộp sản phẩm nào thuộc danh mục 'Bars' tại thị trường Ấn Độ (India)."
    if any(k in q_low for k in ["chưa từng", "chưa bao giờ", "không bán được", "chưa bán được", "không có đơn", "chưa từng bán", "never sold", "never"]):
        return "MULTI_STEP_ANALYTIC"

    # 0.88 Nhận diện bài toán phân tích nghịch lý / phân hóa thị trường (Cross-Market Contrast / Market Divergence)
    # Ví dụ: "Sản phẩm nào bán chạy nhất tại thị trường Ấn Độ (India) nhưng lại ế ẩm nhất (doanh số thấp nhất) tại thị trường Mỹ (USA)?"
    geo_count = sum(1 for g in ["ấn độ", "india", "mỹ", "usa", "hoa kỳ", "canada", "new zealand", "úc", "australia", "nước anh", "uk"] if g in q_low)
    if (
        (geo_count >= 2 or any(k in q_low for k in ["hai thị trường", "2 thị trường", "giữa các thị trường", "hai quốc gia", "2 quốc gia"]))
        and any(k in q_low for k in ["sản phẩm", "mặt hàng", "kẹo", "socola", "chocolate", "product"])
        and any(k in q_low for k in ["bán chạy", "cao nhất", "top", "dẫn đầu"])
        and any(k in q_low for k in ["ế ẩm", "ế nhất", "thấp nhất", "kém nhất", "nghịch lý", "nhưng lại", "phân hóa", "divergence", "ngược lại", "chênh lệch bậc"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 0.9 Nhận diện bài toán biên độ dao động giá bán / chênh lệch giá giữa các thị trường quốc gia
    if (
        any(k in q_low for k in ["biên độ", "dao động", "chênh lệch", "khoảng cách", "phân hóa", "spread", "fluctuation"])
        and any(k in q_low for k in ["giá", "giá bán", "đơn giá", "price"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 0.94 Nhận diện bài toán phân tích phân khúc đa chiều (Multi-Dimensional Segment: Team + Geo + Category/Product)
    if (
        any(k in q_low for k in ["delish", "yummies", "jucies", "riêng team", "team"])
        and any(k in q_low for k in ["canada", "india", "usa", "uk", "new zealand", "australia", "thị trường"])
        and any(k in q_low for k in ["bars", "bites", "category", "nhóm", "loại"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 0.95 Nhận diện bài toán Team kinh doanh kết hợp Sản phẩm chủ lực
    if any(k in q_low for k in ["team", "đội ngũ", "nhóm"]) and any(k in q_low for k in ["sản phẩm chủ lực", "mặt hàng chủ lực", "sản phẩm chính", "sản phẩm bán chạy nhất của họ", "sản phẩm của họ là gì"]):
        return "MULTI_STEP_ANALYTIC"

    # 0.96 Nhận diện bài toán so sánh tăng trưởng doanh số theo Quý giữa 2 quý cụ thể
    if (
        any(k in q_low for k in ["tăng trưởng", "tốc độ tăng", "tỷ lệ tăng", "tỉ lệ tăng", "growth", "tăng hơn", "tăng trên", "tăng ít nhất"])
        and any(k in q_low for k in ["quý", "quarter", "q1", "q2", "q3", "q4"])
        and any(k in q_low for k in ["so với", "vs"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 1. Nhận diện bài toán phân tích tăng trưởng hoặc chênh lệch lương đa mốc
    if any(k in q_low for k in ["tăng trưởng", "tốc độ tăng", "mỗi năm", "annual growth", "growth rate", "so sánh mức lương", "chênh lệch lương giữa", "cấp dưới", "lương thấp hơn"]):
        return "MULTI_STEP_ANALYTIC"

    # 1.1 Nhận diện bài toán phân tích phân vị kết hợp lịch sử tăng lương (Percentile Cohort / Low raises with top salary)
    if (
        any(k in q_low for k in ["top 10%", "top 5%", "top 20%", "top %", "percentile", "bách phân vị"])
        or (any(k in q_low for k in ["tăng lương", "lần tăng"]) and any(k in q_low for k in ["ít hơn", "dưới", "nhỏ hơn", "nhưng"]))
    ):
        return "MULTI_STEP_ANALYTIC"

    # 1.2 Nhận diện bài toán thăng chức / đổi chức danh theo giới tính
    if any(k in q_low for k in ["thăng chức", "đổi chức danh", "chuyển chức danh"]) and any(k in q_low for k in ["nam", "nữ", "giới tính", "gender"]):
        return "MULTI_STEP_ANALYTIC"

    # 1.3 Nhận diện bài toán tỷ trọng chi phí lương / ngân sách phòng ban trong tổng công ty
    if any(k in q_low for k in ["chiếm bao nhiêu", "chiếm tỉ lệ", "chiếm tỷ lệ", "chiếm phần trăm", "tỷ trọng", "tỉ trọng", "phần trăm trong tổng", "tỷ lệ trong tổng"]) and any(k in q_low for k in ["tổng chi phí", "tổng quỹ lương", "tổng lương", "toàn công ty", "trong tổng"]):
        return "MULTI_STEP_ANALYTIC"

    # 1.4 Nhận diện bài toán lọc phòng ban theo ngưỡng lương trung bình / chỉ số tổng hợp
    if (
        any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "department"])
        and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "lương tb", "avg salary", "average salary"])
        and any(k in q_low for k in ["trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", "lớn hơn", "nhỏ hơn", ">", "<", "above", "below", "over"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 1.5 Nhận diện bài toán tỷ lệ tăng lương cá nhân / so sánh lương khởi điểm và lương hiện tại
    if (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "employee"])
        and any(k in q_low for k in ["tỷ lệ tăng lương", "tỉ lệ tăng lương", "tăng lương ấn tượng", "tốc độ tăng lương", "tăng trưởng lương", "mức tăng lương", "salary growth", "highest raise rate", "salary increase"])
        and (
            any(k in q_low for k in ["đầu tiên", "khởi điểm", "lúc vào", "khi vào", "gia nhập", "initial", "starting", "first salary"])
            or any(k in q_low for k in ["hiện tại", "bây giờ", "đến nay", "current", "latest"])
        )
    ):
        return "MULTI_STEP_ANALYTIC"

    # 1.6 Nhận diện bài toán so sánh lương nhân viên với mức lương trung bình của chức danh (Title) hoặc phòng ban
    if (
        any(k in q_low for k in ["nhân viên", "nhân sự", "ai", "người", "employee"])
        and any(k in q_low for k in ["lương cao hơn", "lương thấp hơn", "cao hơn mức lương", "thấp hơn mức lương", "vượt mức lương", "hơn mức lương"])
        and any(k in q_low for k in ["chức danh", "title", "cùng chức danh", "phòng ban đầu tiên"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 1.7 Nhận diện bài toán lịch sử giảm lương / bị hạ lương của nhân viên
    if (
        any(k in q_low for k in ["giảm lương", "hạ lương", "bị giảm", "bị hạ", "salary reduction", "salary decrease", "pay cut"])
        or (any(k in q_low for k in ["lương", "salary"]) and any(k in q_low for k in ["giảm", "hạ", "tụt", "thấp hơn lần trước", "thấp hơn kỳ trước", "reduction", "decrease", "cut"]))
    ):
        return "MULTI_STEP_ANALYTIC"

    # 1.8 Nhận diện bài toán xếp hạng sản phẩm theo từng quý và biến động thứ hạng (Quarterly Product Ranking & Rank Drift)
    if (
        any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
        and any(k in q_low for k in ["quý", "quarter"])
        and any(k in q_low for k in ["xếp hạng", "thứ hạng", "hạng", "rank", "tăng hạng", "giảm hạng", "top 5", "top 10"])
    ):
        return "MULTI_STEP_ANALYTIC"

    # 1.9 Nhận diện bài toán so sánh đa chỉ số (Doanh số & Hộp bán ra) giữa các Team kinh doanh
    if (
        any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh"])
        and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền"])
        and any(k in q_low for k in ["hộp", "thùng", "boxes", "số lượng"])
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
    # Loại trừ cụm so sánh nội bộ: "giữa người nhận lương cao nhất và người nhận lương thấp nhất lớn nhất"
    pattern_extremes = r"(?:giữa|between)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:cao nhất|thấp nhất|highest|lowest)\s+(?:và|and)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:thấp nhất|cao nhất|lowest|highest)"
    cleaned_extremes = re.sub(pattern_extremes, "", q_low)
    has_largest = any(k in cleaned_extremes for k in ["lớn nhất", "cao nhất", "nhiều nhất", "đông nhất", "highest", "largest"])
    has_smallest = any(k in cleaned_extremes for k in ["nhỏ nhất", "thấp nhất", "lowest", "smallest"]) or bool(re.search(r"\bít nhất\b(?!\s*\d+)", cleaned_extremes))
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

    # Mẫu 0.05: So sánh mức lương trung bình giữa 2 phòng ban cụ thể (VD: Sales vs Marketing, Sales vs Development)
    known_depts_map = {
        "sales": "Sales", "development": "Development", "research": "Research", "marketing": "Marketing",
        "finance": "Finance", "production": "Production", "customer service": "Customer Service",
        "quality management": "Quality Management", "human resources": "Human Resources",
        "kinh doanh": "Sales", "bán hàng": "Sales", "tiếp thị": "Marketing", "phát triển": "Development",
        "kỹ thuật": "Development", "nghiên cứu": "Research", "tài chính": "Finance", "sản xuất": "Production",
        "chăm sóc khách hàng": "Customer Service", "cskh": "Customer Service",
        "quản lý chất lượng": "Quality Management", "qlcl": "Quality Management",
        "nhân sự": "Human Resources", "hr": "Human Resources",
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

    if len(depts_in_q) == 2 and any(k in q_low for k in ["lương", "thu nhập", "salary"]) and any(k in q_low for k in ["so sánh", "đối chiếu", "chênh lệch", "khác nhau", "vs", "compare"]):
        d1 = depts_in_q[0]
        d2 = depts_in_q[1]
        return [
            {
                "step": 1,
                "name": f"Lọc nhân sự hiện tại của 2 phòng ban {d1} & {d2}" if not is_en else f"Filter active workforce for {d1} and {d2}",
                "desc": f"Lọc dữ liệu nhân viên đang làm việc (to_date = '9999-01-01') trong 2 phòng ban {d1} và {d2}." if not is_en else f"Filter active contracts for {d1} and {d2}.",
                "status": "done"
            },
            {
                "step": 2,
                "name": f"Tính toán lương trung bình & quy mô từng phòng" if not is_en else "Compute average salary and headcount",
                "desc": f"Tính AVG(salary) và COUNT(emp_no) cho từng phòng ban {d1} và {d2}." if not is_en else f"Compute AVG(salary) and COUNT(emp_no) for {d1} and {d2}.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tính chênh lệch tuyệt đối & tỷ lệ phần trăm" if not is_en else "Calculate absolute and percentage differences",
                "desc": "Tính chênh lệch thu nhập ABS(D1 - D2) và tỷ lệ phần trăm chênh lệch tương đối." if not is_en else "Calculate salary delta and relative percentage gap.",
                "status": "done"
            },
            {
                "step": 4,
                "name": f"Đối chiếu benchmark song song giữa {d1} và {d2}" if not is_en else f"Benchmark {d1} vs {d2}",
                "desc": f"Trực quan hóa so sánh mức thu nhập và tỷ lệ chênh lệch giữa 2 phòng ban." if not is_en else f"Visualize compensation and gap between the two departments.",
                "status": "done"
            }
        ]

    # Mẫu 0.06: Tỷ trọng chi phí lương / ngân sách của một phòng ban cụ thể trong tổng chi phí toàn công ty
    is_dept_share_query = (
        any(k in q_low for k in ["chiếm bao nhiêu", "chiếm tỉ lệ", "chiếm tỷ lệ", "chiếm phần trăm", "tỷ trọng", "tỉ trọng", "phần trăm trong tổng", "tỷ lệ trong tổng", "đóng góp bao nhiêu"])
        and any(k in q_low for k in ["tổng chi phí", "tổng quỹ lương", "tổng lương", "toàn công ty", "trong tổng"])
        and any(k in q_low for k in ["production", "sales", "development", "marketing", "research", "finance", "customer service", "quality management", "human resources", "sản xuất", "kinh doanh", "phát triển", "tiếp thị", "nghiên cứu", "tài chính", "nhân sự"])
    )
    if is_dept_share_query:
        target_dept = "Production"
        for k_d, v_d in [
            ("production", "Production"), ("sản xuất", "Production"),
            ("sales", "Sales"), ("kinh doanh", "Sales"), ("bán hàng", "Sales"),
            ("development", "Development"), ("phát triển", "Development"),
            ("marketing", "Marketing"), ("tiếp thị", "Marketing"),
            ("research", "Research"), ("nghiên cứu", "Research"),
            ("finance", "Finance"), ("tài chính", "Finance"),
            ("customer service", "Customer Service"), ("chăm sóc khách hàng", "Customer Service"),
            ("quality management", "Quality Management"), ("quản lý chất lượng", "Quality Management"),
            ("human resources", "Human Resources"), ("nhân sự", "Human Resources")
        ]:
            if k_d in q_low:
                target_dept = v_d
                break
        return [
            {
                "step": 1,
                "name": f"Tính chi phí lương hiện tại của phòng ban {target_dept}" if not is_en else f"Compute current payroll for {target_dept}",
                "desc": f"Tổng hợp SUM(salary) cho các hợp đồng hiện hành (to_date = '9999-01-01') của phòng {target_dept}." if not is_en else f"Sum active salaries for {target_dept}.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tính tổng chi phí lương toàn công ty" if not is_en else "Compute total company payroll",
                "desc": "Tính tổng chi phí lương hiện tại trên tất cả các phòng ban trong toàn bộ tổ chức." if not is_en else "Aggregate current salary expenditure across all departments.",
                "status": "done"
            },
            {
                "step": 3,
                "name": f"Tính tỷ lệ phần trăm đóng góp của {target_dept}" if not is_en else f"Calculate {target_dept} percentage share",
                "desc": f"Tính tỷ trọng: (Chi phí lương {target_dept} / Tổng chi phí lương công ty) * 100%." if not is_en else f"Calculate ({target_dept} payroll / Total company payroll) * 100%.",
                "status": "done"
            },
            {
                "step": 4,
                "name": f"Phân tích cơ cấu và trực quan hóa tỷ trọng {target_dept}" if not is_en else f"Visualize {target_dept} share breakdown",
                "desc": f"Trực quan hóa tỷ trọng phòng {target_dept} so với phần còn lại của công ty (Donut Chart)." if not is_en else f"Render donut chart comparing {target_dept} vs remaining departments.",
                "status": "done"
            }
        ]

    # Mẫu 0.065: So sánh mức lương giữa nhân viên kỳ cựu (> 5 năm) vs nhân viên mới (< 2 năm) theo từng phòng ban
    is_tenure_cohort_salary_comp = (
        any(k in q_low for k in ["kỳ cựu", "thâm niên", "lâu năm", "cống hiến", "trên 5 năm", "vào làm trên", "lâu hơn"])
        and any(k in q_low for k in ["mới", "mới vào", "mới tuyển", "dưới 2 năm", "ít năm"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
        and any(k in q_low for k in ["phòng ban", "từng phòng", "department", "dept"])
    )
    if is_tenure_cohort_salary_comp:
        return [
            {
                "step": 1,
                "name": "Lọc nhân sự và hợp đồng lương hiện hành tại các phòng ban" if not is_en else "Filter active employees and current compensation across departments",
                "desc": "Áp dụng điều kiện de.to_date = '9999-01-01' và s.to_date = '9999-01-01' để chỉ khảo sát nhân sự đang làm việc." if not is_en else "Filter active contracts with de.to_date = '9999-01-01' and s.to_date = '9999-01-01'.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Phân nhóm nhân viên kỳ cựu (>5 năm) và nhân viên mới (<2 năm)" if not is_en else "Segment senior (>5 years) and new hire (<2 years) cohorts",
                "desc": "Xác định thâm niên dựa trên ngày tuyển dụng e.hire_date so với mốc tuyển dụng tối đa của hệ thống (SELECT MAX(hire_date) FROM employees): kỳ cựu > 5 năm và mới vào < 2 năm." if not is_en else "Segment cohorts based on hire_date relative to max hire date: senior > 5 years and new hire < 2 years.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tính mức lương trung bình và độ chênh lệch lương từng phòng ban" if not is_en else "Compute average salary and salary difference by department",
                "desc": "Tính SeniorAvgSalary, NewHireAvgSalary, SalaryDifference (chênh lệch) và DifferencePercentage (%) gom nhóm theo d.dept_name." if not is_en else "Calculate SeniorAvgSalary, NewHireAvgSalary, and SalaryDifference grouped by department.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Sắp xếp theo độ chênh lệch lương giảm dần và trực quan hóa Double Bar Chart" if not is_en else "Sort by salary difference descending and render Double Bar Chart",
                "desc": "Sắp xếp ORDER BY SalaryDifference DESC và hiển thị biểu đồ cột kép đối chiếu song song giữa hai nhóm nhân sự." if not is_en else "Order by SalaryDifference DESC and render double grouped bar chart.",
                "status": "done"
            }
        ]

    # Mẫu 0.07: Lọc phòng ban theo ngưỡng lương trung bình (VD: lương trung bình trên $70,000)
    is_dept_thresh_query = (
        any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "department"])
        and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "lương tb", "avg salary", "average salary"])
        and any(k in q_low for k in ["trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", "lớn hơn", "nhỏ hơn", ">", "<", "above", "below", "over"])
        and not any(k in q_low for k in [
            "kỳ cựu", "mới vào", "nhân viên mới", "thâm niên", "năm làm việc", "gắn bó", "so sánh", "đối chiếu", "vs", "giữa",
            "nhân viên", "nhân sự", "người", "employee", "phòng ban đầu tiên", "first department", "ít nhất 2", "nhiều phòng ban"
        ])
    )
    if is_dept_thresh_query:
        thresh_match = re.search(r'[\$]?\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)(?:\s*(?:k|nghìn|ngàn|usd|\$))?', q_low)
        thresh_display = "$70,000"
        if thresh_match:
            raw_t = thresh_match.group(1).replace(",", "").replace(".", "")
            try:
                val_t = float(raw_t)
                if val_t < 1000 and any(k in q_low for k in ["k", "nghìn", "ngàn"]):
                    val_t *= 1000
                thresh_display = f"${val_t:,.0f}"
            except Exception:
                pass
        return [
            {
                "step": 1,
                "name": "Lọc hợp đồng hiện hành của toàn bộ nhân sự và phòng ban" if not is_en else "Filter active employee and department records",
                "desc": "Áp dụng điều kiện s.to_date = '9999-01-01' và de.to_date = '9999-01-01' để đảm bảo chỉ lấy mức lương hiện tại." if not is_en else "Apply s.to_date = '9999-01-01' and de.to_date = '9999-01-01' to filter active compensation.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tính toán lương trung bình & quy mô nhân sự từng phòng" if not is_en else "Compute average salary and headcount per department",
                "desc": "Tính ROUND(AVG(s.salary), 2) AS AvgSalary và COUNT(DISTINCT de.emp_no) AS Headcount gom nhóm theo d.dept_name." if not is_en else "Compute ROUND(AVG(s.salary), 2) and COUNT(DISTINCT de.emp_no) grouped by d.dept_name.",
                "status": "done"
            },
            {
                "step": 3,
                "name": f"Áp dụng điều kiện lọc ngưỡng HAVING AvgSalary vượt {thresh_display}" if not is_en else f"Apply HAVING AvgSalary threshold filter ({thresh_display})",
                "desc": "Sử dụng mệnh đề HAVING AvgSalary > [ngưỡng] (TUYỆT ĐỐI KHÔNG dùng WHERE s.salary) để lọc chính xác phòng ban đạt chuẩn." if not is_en else "Use HAVING AvgSalary > threshold to filter qualifying departments.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Sắp xếp theo thứ tự lương giảm dần và trực quan hóa Bar Chart" if not is_en else "Sort by salary descending and visualize Bar Chart",
                "desc": "Sắp xếp ORDER BY AvgSalary DESC và hiển thị biểu đồ đối chiếu cùng thẻ KPI điều hành." if not is_en else "Order by AvgSalary DESC and render comparative bar chart with executive KPIs.",
                "status": "done"
            }
        ]

    # Mẫu 0.08: Bổ nhiệm / Thăng chức Quản lý (Manager) theo giới tính trong N năm gần nhất
    is_recent_mgr_promo_plan = (
        any(k in q_low for k in ["manager", "quản lý", "trưởng phòng", "ban quản lý"])
        and any(k in q_low for k in ["nam", "nữ", "giới tính", "gender"])
        and any(k in q_low for k in ["gần nhất", "5 năm", "gần đây", "thời gian qua"])
    )
    if is_recent_mgr_promo_plan:
        m_y = re.search(r"(\d+)\s*năm", q_low)
        y_str = m_y.group(1) if m_y else "5"
        return [
            {
                "step": 1,
                "name": f"Xác định mốc bổ nhiệm Quản lý {y_str} năm gần nhất" if not is_en else f"Isolate {y_str}-year manager appointment window",
                "desc": f"Lọc các lượt bổ nhiệm từ bảng dept_manager trong {y_str} năm gần nhất theo ngày bổ nhiệm: YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - {int(y_str)-1}." if not is_en else f"Filter dept_manager appointments within the {y_str} most recent years: YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - {int(y_str)-1}.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Thống kê số lượng bổ nhiệm theo giới tính Nam vs Nữ" if not is_en else "Count appointments by Male vs Female",
                "desc": "Kết hợp với bảng employees để đếm số lượng Quản lý Nam (e.gender = 'M') và Nữ (e.gender = 'F')." if not is_en else "Join employees to aggregate Male (e.gender = 'M') and Female (e.gender = 'F') manager counts.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tính toán cơ cấu và tỷ lệ % phân bổ" if not is_en else "Compute gender share and appointment ratios",
                "desc": "Tính tổng số lượt bổ nhiệm và tỷ lệ % của từng giới tính (MalePct, FemalePct)." if not is_en else "Compute total appointments and gender percentages (MalePct, FemalePct).",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Đối chiếu và trực quan hóa biểu đồ Double Bar" if not is_en else "Benchmark and visualize Double Bar Chart",
                "desc": "Trực quan hóa diễn biến bổ nhiệm theo thời gian/đơn vị và xuất bộ thẻ KPI điều hành." if not is_en else "Visualize appointment trends and render executive KPI cards.",
                "status": "done"
            }
        ]

    # Mẫu 0.09: Top nhân sự kiếm được nhiều tiền nhất / lương cao nhất trong một năm cụ thể hoặc hiện tại
    m_yr = re.search(r"\b(19\d\d|20\d\d)\b", q_low)
    is_top_earner_plan = (
        any(k in q_low for k in ["kiếm được nhiều tiền nhất", "kiếm nhiều tiền nhất", "nhiều tiền nhất", "kiếm tiền nhiều nhất", "kiếm tiền", "thu nhập cao nhất", "lương cao nhất", "mức lương cao nhất", "highest earner", "highest paid", "highest salary", "earned the most"])
        or (
            any(k in q_low for k in ["ai", "ai là", "top", "người", "nhân viên", "nhân sự"])
            and any(k in q_low for k in ["tiền", "lương", "thu nhập", "salary"])
            and any(k in q_low for k in ["nhiều nhất", "cao nhất", "lớn nhất"])
        )
    ) and not any(k in q_low for k in ["tăng trưởng", "tốc độ", "mỗi năm", "bổ nhiệm", "manager", "so sánh", "đối chiếu", "chênh lệch", "khoảng cách", "spread", "gap", "phân hóa", "quỹ lương", "tổng quỹ lương", "tổng lương", "chi phí lương"])
    if is_top_earner_plan:
        yr_str = f"năm {m_yr.group(1)}" if m_yr else "thời điểm hiện tại"
        yr_filter_desc = f"Lọc theo YEAR(s.from_date) = {m_yr.group(1)} và thời gian phân công phòng ban trong năm {m_yr.group(1)}." if m_yr else "Lọc theo s.to_date = '9999-01-01' và de.to_date = '9999-01-01'."
        return [
            {
                "step": 1,
                "name": f"Xác định bản ghi thu nhập {yr_str}" if not is_en else f"Isolate compensation records for {yr_str}",
                "desc": f"Truy vấn bảng salaries với điều kiện: {yr_filter_desc}" if not is_en else f"Filter salaries table: {yr_filter_desc}",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Liên kết định danh nhân sự và phòng ban" if not is_en else "Join employee identity and department",
                "desc": "Kết hợp với bảng employees (FullName) và dept_emp + departments để xác định phòng ban công tác." if not is_en else "Join employees (FullName) and dept_emp + departments to identify assignment.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Sắp xếp theo mức thu nhập và xác định quán quân" if not is_en else "Rank by earnings and identify top earner",
                "desc": "Sắp xếp ORDER BY s.salary DESC và áp dụng LIMIT phù hợp theo yêu cầu người dùng." if not is_en else "Apply ORDER BY s.salary DESC with appropriate LIMIT.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Xuất bảng xếp hạng và thẻ KPI điều hành" if not is_en else "Render executive ranking and KPI cards",
                "desc": "Hiển thị thông tin người dẫn đầu, mức lương đạt được và phân tích cơ cấu thu nhập." if not is_en else "Render top earner identity, salary amount, and executive KPI summary.",
                "status": "done"
            }
        ]

    # Mẫu 0.095: Mức chênh lệch lương giữa người cao nhất và thấp nhất theo chức danh hoặc phòng ban (Salary Spread)
    is_salary_spread_plan = (
        any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa", "difference"])
        and any(k in q_low for k in ["lương", "thu nhập", "salary", "income"])
        and (any(k in q_low for k in ["chức danh", "title", "vị trí"]) or any(k in q_low for k in ["phòng ban", "phòng", "department", "các phòng", "đơn vị"]))
        and not any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "gender", "chuẩn", "stddev", "standard deviation", "std("])
    )
    if is_salary_spread_plan:
        is_title = any(k in q_low for k in ["chức danh", "title", "vị trí"])
        entity_label = "chức danh" if is_title else "phòng ban"
        tbl_info = "bảng titles t" if is_title else "bảng departments d và dept_emp de"
        col_group = "t.title" if is_title else "d.dept_name"
        return [
            {
                "step": 1,
                "name": f"Lọc hợp đồng hiệu lực hiện tại theo {entity_label}" if not is_en else f"Filter active contracts by {entity_label}",
                "desc": f"Kết hợp {tbl_info} với bảng salaries với điều kiện to_date = '9999-01-01' để xác định thu nhập hiện hành." if not is_en else f"Join {tbl_info} with salaries where to_date = '9999-01-01'.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tính toán mức lương đỉnh, sàn và khoảng chênh lệch" if not is_en else "Compute Max, Min, and Salary Spread",
                "desc": f"Gom nhóm theo {col_group}, tính MAX(s.salary) AS MaxSalary, MIN(s.salary) AS MinSalary và SalarySpread = (MAX - MIN)." if not is_en else f"Group by {col_group}, compute MAX, MIN, and SalarySpread = MAX - MIN.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Sắp xếp theo khoảng chênh lệch giảm dần" if not is_en else "Order by SalarySpread descending",
                "desc": "Sắp xếp ORDER BY SalarySpread DESC và áp dụng LIMIT phù hợp để xác định đơn vị có mức chênh lệch cao nhất." if not is_en else "Apply ORDER BY SalarySpread DESC and LIMIT to identify leading disparity.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trực quan hóa và hiển thị bộ thẻ KPI điều hành" if not is_en else "Visualize spread metrics and render KPI cards",
                "desc": "Hiển thị biểu đồ phân tích khoảng cách lương đỉnh - sàn và bộ 4 thẻ KPI phân hóa thu nhập." if not is_en else "Render spread chart and executive KPI cards.",
                "status": "done"
            }
        ]

    # Mẫu 0.096: Phân loại toàn bộ nhân sự hiện tại thành 3 nhóm lương (Salary Tier Distribution)
    is_salary_tier_plan = (
        any(k in q_low for k in ["nhóm lương", "bậc lương", "khoảng lương", "3 nhóm lương", "thu nhập thấp", "thu nhập trung bình", "thu nhập cao", "phân loại toàn bộ", "3 nhóm", "các nhóm lương", "phân loại theo lương"])
        or (
            any(k in q_low for k in ["phân loại", "chia thành", "tier", "bracket"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary"])
            and any(k in q_low for k in ["tỷ lệ", "%", "cơ cấu", "phần trăm", "số lượng"])
        )
    ) and not any(k in q_low for k in ["kỳ cựu", "mới vào", "so sánh", "đối chiếu", "thâm niên"])
    if is_salary_tier_plan:
        return [
            {
                "step": 1,
                "name": "Lọc toàn bộ hợp đồng lương hiện hành" if not is_en else "Filter active salary contracts",
                "desc": "Quét bảng salaries với điều kiện to_date = '9999-01-01' để xác định thu nhập hiện tại của toàn bộ nhân viên." if not is_en else "Scan salaries table where to_date = '9999-01-01' to capture current active income.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Phân loại 3 bậc thu nhập theo ngưỡng chuẩn" if not is_en else "Segment into 3 income tiers",
                "desc": "Sử dụng CASE WHEN để phân chia: Dưới 50k (Thấp), 50k - 80k (Trung bình), Trên 80k (Cao)." if not is_en else "Use CASE WHEN to segment: Under 50k (Low), 50k-80k (Medium), Over 80k (High).",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tính toán số lượng và tỷ lệ phần trăm mỗi nhóm" if not is_en else "Calculate headcount and percentage per tier",
                "desc": "Gom nhóm theo bậc lương, tính EmployeeCount và Percentage dựa trên tổng quy mô 240,124 nhân sự." if not is_en else "Group by tier, calculate EmployeeCount and Percentage over active headcount.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trực quan hóa cơ cấu và hiển thị KPI điều hành" if not is_en else "Visualize distribution and render executive KPIs",
                "desc": "Hiển thị biểu đồ phân bổ cơ cấu Donut Chart và bộ thẻ KPI 3 nhóm thu nhập." if not is_en else "Render distribution donut chart and executive KPI tier cards.",
                "status": "done"
            }
        ]

    # Mẫu 0.097: Liệt kê các phòng ban có mức lương phân tán (độ lệch chuẩn - STDDEV) hoặc tỷ lệ biến động lương cao nhất
    is_dept_fluctuation_plan = (
        any(k in q_low for k in ["biến động lương", "tỷ lệ biến động lương", "độ biến động lương", "dao động lương", "độ lệch chuẩn", "stddev", "độ phân tán"])
        or (
            any(k in q_low for k in ["biến động", "fluctuation", "dao động", "phân tán", "độ lệch chuẩn", "stddev"])
            and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"])
            and any(k in q_low for k in ["lương", "salary", "thu nhập"])
        )
    )
    if is_dept_fluctuation_plan:
        is_stddev_focus = any(k in q_low for k in ["độ lệch chuẩn", "stddev", "phân tán", "độ phân tán", "standard deviation"])
        order_name = "Sắp xếp theo độ lệch chuẩn (SalaryStdDev) giảm dần" if is_stddev_focus else "Xác định hệ số biến động lương (Fluctuation Rate)"
        order_desc = "Sắp xếp ORDER BY SalaryStdDev DESC để xác định phòng ban có mức phân tán lương rộng nhất." if is_stddev_focus else "Tính FluctuationRate = ROUND(STDDEV(s.salary) * 100.0 / AVG(s.salary), 2) và sắp xếp giảm dần."
        return [
            {
                "step": 1,
                "name": "Kết hợp dữ liệu lương hiện hành và phòng ban" if not is_en else "Join active salaries and departments",
                "desc": "Kết hợp salaries với dept_emp và departments với điều kiện to_date = '9999-01-01'." if not is_en else "Join salaries with dept_emp and departments where to_date = '9999-01-01'.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tính toán độ lệch chuẩn (STDDEV) và lương trung bình từng phòng" if not is_en else "Compute standard deviation (STDDEV) and average salary per department",
                "desc": "Gom nhóm theo d.dept_name, tính CurrentAvgSalary = AVG(s.salary), SalaryStdDev = STDDEV(s.salary) và FluctuationRate." if not is_en else "Group by d.dept_name, calculate CurrentAvgSalary, SalaryStdDev = STDDEV(s.salary), and FluctuationRate.",
                "status": "done"
            },
            {
                "step": 3,
                "name": order_name if not is_en else "Order by Salary Dispersion / Fluctuation",
                "desc": order_desc if not is_en else "Sort descending to determine leading department in salary dispersion.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trực quan hóa mức độ phân tán lương phòng ban" if not is_en else "Visualize salary dispersion across departments",
                "desc": "Xuất bảng đối chiếu độ lệch chuẩn và lương hiện tại kèm biểu đồ cột và KPI điều hành." if not is_en else "Render comparison table, bar chart, and executive KPIs.",
                "status": "done"
            }
        ]

    # Mẫu 0.0962: Đơn giá bán trung bình trên mỗi hộp tại thị trường quốc gia (Avg Price Per Box by Country/Market)
    is_avg_price_per_box_plan = (
        any(k in q_low for k in ["mỗi hộp", "từng hộp", "bình quân mỗi hộp", "trung bình mỗi hộp", "giá bán trung bình", "đơn giá trung bình", "price per box", "avg price per box"])
        and any(k in q_low for k in ["tiền", "giá", "$", "mang về", "bao nhiêu", "thu về"])
        and not any(k in q_low for k in ["biên độ", "dao động", "spread", "lợi nhuận", "profit", "margin"])
    )
    if is_avg_price_per_box_plan:
        c_name = "Australia (Úc)" if any(k in q_low for k in ["úc", "australia"]) else (
            "Ấn Độ (India)" if any(k in q_low for k in ["ấn độ", "india"]) else (
                "Mỹ (USA)" if any(k in q_low for k in ["mỹ", "usa"]) else (
                    "New Zealand" if "new zealand" in q_low else (
                        "Canada" if "canada" in q_low else (
                            "Vương quốc Anh (UK)" if re.search(r'\b(uk|nước anh|vương quốc anh|united kingdom)\b', q_low) else "thị trường mục tiêu"
                        )
                    )
                )
            )
        )
        return [
            {
                "step": 1,
                "name": f"Lọc dữ liệu bán hàng và tính đơn giá bình quân mỗi hộp tại {c_name}" if not is_en else f"Filter sales and compute average price per box in {c_name}",
                "desc": f"Dùng công thức ROUND(SUM(Amount) / NULLIF(SUM(Boxes), 0), 2) AS AvgPricePerBox để tính giá trị thu về trên mỗi hộp sô-cô-la bán ra tại {c_name}." if not is_en else f"Compute AvgPricePerBox = SUM(Amount)/SUM(Boxes) for {c_name}.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tổng hợp quy mô doanh thu và tổng sản lượng tiêu thụ" if not is_en else "Aggregate total revenue and boxes sold volume",
                "desc": "Truy xuất đồng thời SUM(Amount) AS TotalRevenue và SUM(Boxes) AS TotalBoxesSold để đối chiếu quy mô thị trường." if not is_en else "Retrieve TotalRevenue and TotalBoxesSold to contextualize market volume.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Trình bày thẻ KPI điều hành hiệu quả định giá và biểu đồ" if not is_en else "Render executive KPI scorecard and unit economics charts",
                "desc": "Hiển thị bộ 4 chỉ số điều hành: Đơn giá bình quân mỗi hộp, Doanh thu toàn thị trường, Sản lượng tiêu thụ và đánh giá hiệu quả định giá." if not is_en else "Display 4 executive KPI cards and pricing charts.",
                "status": "done"
            }
        ]

    # Mẫu 0.0965: Thống kê tổng hợp các đơn hàng lớn vượt ngưỡng (Order Threshold Aggregation)
    is_order_threshold_plan = (
        any(k in q_low for k in ["đơn hàng", "giao dịch", "order"])
        and any(k in q_low for k in ["trên", "hơn", "vượt", ">"])
        and any(k in q_low for k in ["hộp", "boxes", "$", "usd", "doanh thu"])
        and any(c.isdigit() for c in q_low)
        and not any(k in q_low for k in ["theo từng", "mỗi nhân sự", "mỗi sản phẩm", "mỗi quốc gia", "mỗi team", "theo nhân sự", "theo sản phẩm", "theo quốc gia"])
    )
    if is_order_threshold_plan:
        return [
            {
                "step": 1,
                "name": "Lọc các đơn hàng vượt ngưỡng và tổng hợp quy mô (Count, Sum, Avg)" if not is_en else "Filter orders exceeding threshold and aggregate metrics",
                "desc": "Truy vấn bảng sales với điều kiện lọc ngưỡng (WHERE s.Boxes > 1000 hoặc s.Amount > threshold), tính tổng số đơn, tổng doanh thu, tổng số hộp và giá trị trung bình." if not is_en else "Query sales table with threshold filter, computing order count, total revenue, boxes, and average amount.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Trình bày thẻ KPI điều hành phân khúc đơn hàng lớn" if not is_en else "Render executive KPI scorecard for large orders segment",
                "desc": "Hiển thị bộ 4 chỉ số điều hành: Số lượng đơn lớn, Tổng doanh thu phân khúc, Đơn giá trung bình và Tổng sản lượng hộp tiêu thụ." if not is_en else "Display executive KPI scorecard with order count, total revenue, average order value, and total volume.",
                "status": "done"
            }
        ]

    # Mẫu 0.0968: Bài toán nhân sự chưa từng bán sản phẩm thuộc danh mục / thị trường (Anti-Join)
    is_anti_join_plan = any(k in q_low for k in ["chưa từng", "chưa bao giờ", "không bán được", "chưa bán được", "không có đơn", "never"])
    if is_anti_join_plan:
        cat_term = "Bars" if "bars" in q_low or "bar" in q_low else ("Bites" if "bites" in q_low else "được chỉ định")
        geo_term = "Ấn Độ (India)" if any(k in q_low for k in ["ấn độ", "india"]) else ("Mỹ (USA)" if any(k in q_low for k in ["mỹ", "usa"]) else "thị trường mục tiêu")
        return [
            {
                "step": 1,
                "name": f"Xác định tập hợp nhân sự đã bán danh mục '{cat_term}' tại {geo_term}" if not is_en else f"Identify salespersons who sold '{cat_term}' in {geo_term}",
                "desc": f"Truy vấn bảng sales kết hợp products và geo để lấy danh sách SPID đã phát sinh giao dịch cho danh mục '{cat_term}' tại {geo_term}." if not is_en else f"Query sales joined with products and geo to get SPIDs selling '{cat_term}' in {geo_term}.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Áp dụng truy vấn phủ định NOT IN / NOT EXISTS trên bảng people" if not is_en else "Apply NOT IN / NOT EXISTS anti-join on people table",
                "desc": "Lọc các nhân sự có mã SPID không nằm trong tập hợp bán hàng trên để tìm nhân sự chưa từng bán." if not is_en else "Filter people records whose SPID is NOT IN the identified seller set.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Trích xuất danh sách nhân sự và phân nhóm theo đội ngũ (Team)" if not is_en else "Extract qualifying salespersons and team affiliations",
                "desc": "Lấy thông tin SPID, Salesperson, Team và sắp xếp theo tên nhân sự." if not is_en else "Select SPID, Salesperson, Team and sort by Salesperson.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Tổng hợp thẻ chỉ số KPI và biểu đồ cơ cấu nhân sự theo đội ngũ" if not is_en else "Summarize KPI scorecards and team breakdown chart",
                "desc": "Thống kê số lượng nhân sự chưa bán, tỷ lệ trên tổng nhân sự toàn công ty và phân bổ theo đội ngũ." if not is_en else "Display count of never-sold staff, percentage of company, and team distribution.",
                "status": "done"
            }
        ]

    # Mẫu 0.0972: Phân tích nghịch lý / phân hóa sản phẩm giữa hai thị trường quốc gia (Cross-Market Divergence)
    is_market_divergence_plan = (
        (sum(1 for g in ["ấn độ", "india", "mỹ", "usa", "hoa kỳ", "canada", "new zealand", "úc", "australia", "nước anh", "uk"] if g in q_low) >= 2
         or any(k in q_low for k in ["hai thị trường", "2 thị trường", "giữa các thị trường", "hai quốc gia", "2 quốc gia"]))
        and any(k in q_low for k in ["sản phẩm", "mặt hàng", "kẹo", "socola", "chocolate", "product"])
        and any(k in q_low for k in ["bán chạy", "cao nhất", "top", "dẫn đầu"])
        and any(k in q_low for k in ["ế ẩm", "ế nhất", "thấp nhất", "kém nhất", "nghịch lý", "nhưng lại", "phân hóa", "divergence", "ngược lại", "chênh lệch bậc"])
    )
    if is_market_divergence_plan:
        return [
            {
                "step": 1,
                "name": "Thống kê doanh số và xếp hạng sản phẩm tại thị trường dẫn đầu" if not is_en else "Compute sales and rank products in primary leading market",
                "desc": "Sử dụng CTE kết hợp DENSE_RANK() OVER (ORDER BY SUM(Amount) DESC) để xác định thứ hạng bán chạy của từng sản phẩm tại thị trường thứ nhất." if not is_en else "Use CTE and DENSE_RANK() to compute product ranks in the first country market.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Thống kê doanh số và xếp hạng sản phẩm tại thị trường đối lập" if not is_en else "Compute sales and rank products in contrasting market",
                "desc": "Sử dụng CTE thứ hai với DENSE_RANK() để xác định thứ hạng sản phẩm tại thị trường thứ hai (thị trường ế ẩm / đối lập)." if not is_en else "Use second CTE with DENSE_RANK() to compute product ranks in the second country market.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tính toán độ phân hóa thứ hạng RankDivergence giữa hai thị trường" if not is_en else "Calculate RankDivergence across both markets",
                "desc": "Kết nối hai CTE theo Product và tính toán độ chênh lệch RankDivergence = Rank_ThịTrường2 - Rank_ThịTrường1; sắp xếp giảm dần để tìm sản phẩm nghịch lý nhất." if not is_en else "Join CTEs on Product, calculate RankDivergence = Rank_Market2 - Rank_Market1, and order descending.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trực quan hóa biểu đồ Grouped Bar và trình bày thẻ KPI điều hành" if not is_en else "Render Grouped Bar chart and executive KPI scorecard",
                "desc": "Trực quan hóa doanh số song song giữa hai quốc gia, hiển thị sản phẩm quán quân nghịch lý, doanh số và thứ hạng từng thị trường." if not is_en else "Render dual-market grouped bar chart and scorecard metrics.",
                "status": "done"
            }
        ]

    # Mẫu 0.0975: Biên độ dao động giá bán trung bình trên mỗi hộp giữa các thị trường quốc gia
    is_price_spread_plan = (
        any(k in q_low for k in ["biên độ", "dao động", "chênh lệch", "khoảng cách", "phân hóa", "spread", "fluctuation"])
        and any(k in q_low for k in ["giá", "giá bán", "đơn giá", "price"])
    )
    if is_price_spread_plan:
        return [
            {
                "step": 1,
                "name": "Tính đơn giá bán trung bình trên mỗi hộp theo sản phẩm và quốc gia" if not is_en else "Compute avg price per box by product and country",
                "desc": "Dùng CTE kết nối bảng sales, products và geo; gom nhóm theo pr.Product và g.Geo để tính AvgPricePerBox = SUM(Amount) / SUM(Boxes)." if not is_en else "Join sales, products, geo; group by Product and Country to compute AvgPricePerBox = SUM(Amount)/SUM(Boxes).",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Xác định giá bán TB cao nhất và thấp nhất của từng sản phẩm" if not is_en else "Determine highest and lowest avg price for each product",
                "desc": "Gom nhóm theo Product để tính MAX(AvgPricePerBox) và MIN(AvgPricePerBox) giữa các thị trường quốc gia." if not is_en else "Group by Product to compute MAX(AvgPricePerBox) and MIN(AvgPricePerBox) across countries.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tính biên độ dao động giá và xếp hạng tìm sản phẩm biến động lớn nhất" if not is_en else "Compute price spread (MAX - MIN) and rank by highest spread",
                "desc": "Tính PriceSpread = MAX(AvgPricePerBox) - MIN(AvgPricePerBox), sắp xếp ORDER BY PriceSpread DESC để tìm sản phẩm có biên độ lớn nhất." if not is_en else "Calculate PriceSpread = MAX - MIN, order by PriceSpread DESC to find the largest spread product.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trình bày báo cáo biên độ giá và bộ thẻ KPI điều hành" if not is_en else "Present price dispersion report and KPI metrics",
                "desc": "Hiển thị sản phẩm quán quân biên độ, giá trần, giá sàn và mức chênh lệch giữa các thị trường quốc tế." if not is_en else "Display leading spread product, ceiling price, floor price, and spread metrics.",
                "status": "done"
            }
        ]

    # Mẫu 0.0977: Phân khúc đa chiều (Multi-Dimensional Segment: Team + Geo + Category/Product)
    is_multi_dim_segment_plan = (
        any(k in q_low for k in ["delish", "yummies", "jucies", "riêng team", "team"])
        and any(k in q_low for k in ["canada", "india", "usa", "uk", "new zealand", "australia", "thị trường"])
        and any(k in q_low for k in ["bars", "bites", "category", "nhóm", "loại"])
    )
    if is_multi_dim_segment_plan:
        target_team = "Delish" if "delish" in q_low else ("Yummies" if "yummies" in q_low else ("Jucies" if "jucies" in q_low else "Team"))
        target_geo = "Canada" if "canada" in q_low else ("India" if "india" in q_low else ("USA" if "usa" in q_low or "mỹ" in q_low else "Thị trường"))
        target_cat = "Bars" if "bars" in q_low else ("Bites" if "bites" in q_low else "Category")
        return [
            {
                "step": 1,
                "name": f"Liên kết 4 bảng và lọc phân khúc: Team {target_team} × Thị trường {target_geo} × Nhóm {target_cat}" if not is_en else f"Join 4 tables and filter segment: Team {target_team} × Market {target_geo} × Category {target_cat}",
                "desc": f"Kết nối sales với people, geo, products và áp dụng điều kiện lọc nghiêm ngặt WHERE pe.Team = '{target_team}' AND g.Geo = '{target_geo}' AND pr.Category = '{target_cat}'." if not is_en else f"Join sales with people, geo, products and apply WHERE pe.Team = '{target_team}' AND g.Geo = '{target_geo}' AND pr.Category = '{target_cat}'.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tổng hợp doanh thu, sản lượng hộp và đơn giá bình quân theo từng sản phẩm" if not is_en else "Aggregate revenue, box volume, and avg price per box by product",
                "desc": "Nhóm dữ liệu theo pr.PID, pr.Product; tính SUM(s.Amount), SUM(s.Boxes) và ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox, sắp xếp TotalSales giảm dần." if not is_en else "Group by pr.PID, pr.Product; compute SUM(Amount), SUM(Boxes), and AvgPricePerBox, ordered by TotalSales DESC.",
                "status": "done"
            },
            {
                "step": 3,
                "name": f"Trực quan hóa phân khúc và bộ thẻ điều hành cho Team {target_team} tại {target_geo}" if not is_en else f"Visualize segment and executive KPI scorecard for Team {target_team} in {target_geo}",
                "desc": f"Hiển thị tổng doanh thu phân khúc, tổng sản lượng hộp, đơn giá bình quân và sản phẩm đóng góp lớn nhất trong nhóm {target_cat}." if not is_en else f"Render total segment revenue, total boxes, avg price, and hero product in {target_cat}.",
                "status": "done"
            }
        ]

    # Mẫu 0.0978: Team kinh doanh có tổng sản lượng bán ra thấp nhất/cao nhất và sản phẩm chủ lực
    is_team_flagship_plan = (
        any(k in q_low for k in ["team", "đội ngũ", "nhóm"])
        and any(k in q_low for k in ["sản phẩm chủ lực", "mặt hàng chủ lực", "sản phẩm chính", "sản phẩm bán chạy nhất của họ", "sản phẩm của họ là gì"])
    )
    if is_team_flagship_plan:
        is_lowest = any(k in q_low for k in ["thấp nhất", "ít nhất", "kém nhất", "nhỏ nhất", "lowest", "least", "bottom"])
        team_desc = "thấp nhất" if is_lowest else "cao nhất"
        return [
            {
                "step": 1,
                "name": f"Xác định đội ngũ kinh doanh có tổng sản lượng bán ra {team_desc}" if not is_en else f"Identify sales team with {team_desc} total boxes sold",
                "desc": f"Kết nối bảng sales và people, tổng hợp SUM(Boxes) theo pe.Team và sắp xếp để chọn ra đội ngũ có sản lượng {team_desc}." if not is_en else f"Join sales and people, aggregate SUM(Boxes) by team and find the {team_desc} team.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tổng hợp doanh số và sản lượng từng sản phẩm của đội ngũ mục tiêu" if not is_en else "Aggregate product sales and volume for target team",
                "desc": "Kết nối bổ sung bảng products, nhóm theo từng sản phẩm của team và tính SUM(Boxes) cùng SUM(Amount)." if not is_en else "Join products table, group by product for target team and compute SUM(Boxes) and SUM(Amount).",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Xếp hạng và trích xuất sản phẩm chủ lực (Flagship Product)" if not is_en else "Rank and extract flagship product",
                "desc": "Dùng DENSE_RANK() để xác định mặt hàng đứng đầu về sản lượng bán ra của đội ngũ này." if not is_en else "Use DENSE_RANK() to identify top-selling product for this team.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Tổng hợp báo cáo điều hành và thẻ KPI chiến lược" if not is_en else "Synthesize executive report and KPI cards",
                "desc": "Trình bày đội ngũ mục tiêu, sản lượng hộp, doanh thu và tên sản phẩm chủ lực gánh vác doanh số của team." if not is_en else "Display target team, box volume, revenue, and key hero product.",
                "status": "done"
            }
        ]

    # Mẫu 0.0979: Tăng trưởng doanh số theo quý giữa 2 quý cụ thể
    is_quarterly_growth_plan = (
        any(k in q_low for k in ["tăng trưởng", "tốc độ tăng", "tỷ lệ tăng", "tỉ lệ tăng", "growth", "tăng hơn", "tăng trên", "tăng ít nhất"])
        and any(k in q_low for k in ["quý", "quarter", "q1", "q2", "q3", "q4"])
        and any(k in q_low for k in ["so với", "vs"])
    )
    if is_quarterly_growth_plan:
        qtr_matches = re.findall(r'(?:quý|q)\s*([1-4])(?:[/\s]*(?:năm\s*)?(20\d{2}))?', q_low)
        t_q = qtr_matches[0][0] if len(qtr_matches) >= 1 else "4"
        t_yr = qtr_matches[0][1] if len(qtr_matches) >= 1 and qtr_matches[0][1] else "2021"
        b_q = qtr_matches[1][0] if len(qtr_matches) >= 2 else "3"
        b_yr = qtr_matches[1][1] if len(qtr_matches) >= 2 and qtr_matches[1][1] else t_yr

        is_prod = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
        is_team = any(k in q_low for k in ["team", "đội ngũ", "nhóm"]) and not is_prod
        ent_desc = "sản phẩm" if is_prod else ("đội ngũ kinh doanh" if is_team else "nhân sự bán hàng")

        return [
            {
                "step": 1,
                "name": f"Tính doanh số Quý {b_q}/{b_yr} theo từng {ent_desc}" if not is_en else f"Compute Q{b_q}/{b_yr} sales for each {ent_desc}",
                "desc": f"Dùng biểu thức điều kiện SUM(CASE WHEN...) để tính tổng doanh thu bán được trong Quý {b_q}/{b_yr}." if not is_en else f"Aggregate Q{b_q}/{b_yr} revenue using conditional SUM(CASE WHEN...).",
                "status": "done"
            },
            {
                "step": 2,
                "name": f"Tính doanh số Quý {t_q}/{t_yr} theo từng {ent_desc}" if not is_en else f"Compute Q{t_q}/{t_yr} sales for each {ent_desc}",
                "desc": f"Dùng biểu thức điều kiện SUM(CASE WHEN...) để tính tổng doanh thu bán được trong Quý {t_q}/{t_yr}." if not is_en else f"Aggregate Q{t_q}/{t_yr} revenue using conditional SUM(CASE WHEN...).",
                "status": "done"
            },
            {
                "step": 3,
                "name": f"Tính tốc độ tăng trưởng % và lọc điều kiện" if not is_en else "Compute percentage growth and filter criteria",
                "desc": f"Tính GrowthPct = ((Q{t_q} - Q{b_q}) / Q{b_q}) * 100 và lọc các {ent_desc} thỏa mãn ngưỡng tăng trưởng." if not is_en else f"Calculate GrowthPct and filter entities meeting target threshold.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trình bày bảng xếp hạng tăng trưởng và bộ thẻ KPI điều hành" if not is_en else "Present growth rankings and KPI cards",
                "desc": "Hiển thị danh sách các trường hợp vượt trội, doanh số từng quý, mức tăng tuyệt đối và phần trăm." if not is_en else "Display leading growth performers, quarterly sales, and growth rates.",
                "status": "done"
            }
        ]

    # Mẫu 0.098: Top N phòng ban có tổng quỹ lương chi trả cao nhất hiện nay kèm số lượng nhân sự
    is_dept_top_payroll_plan = (
        any(k in q_low for k in ["quỹ lương", "tổng quỹ lương", "tổng chi trả lương", "chi trả quỹ lương", "chi phí lương"])
        or (
            any(k in q_low for k in ["tổng lương", "tổng chi lương", "tổng tiền lương"])
            and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"])
        )
    )
    if is_dept_top_payroll_plan:
        return [
            {
                "step": 1,
                "name": "Liên kết hợp đồng nhân sự và phòng ban hiện tại" if not is_en else "Link active employee contracts and departments",
                "desc": "Kết nối bảng salaries, dept_emp và departments với to_date = '9999-01-01'." if not is_en else "Link salaries, dept_emp, and departments with to_date = '9999-01-01'.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tổng hợp quỹ lương và quy mô nhân sự theo phòng" if not is_en else "Aggregate payroll budget and headcount per department",
                "desc": "Gom nhóm theo d.dept_name, tính TotalPayroll = SUM(s.salary), Headcount = COUNT(DISTINCT de.emp_no) và AvgSalary." if not is_en else "Group by d.dept_name, compute TotalPayroll = SUM(salary), Headcount, and AvgSalary.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Xếp hạng và lọc Top đơn vị chi trả cao nhất" if not is_en else "Rank and filter Top spending departments",
                "desc": "Sắp xếp ORDER BY TotalPayroll DESC và giới hạn Top theo yêu cầu người dùng (LIMIT N)." if not is_en else "Apply ORDER BY TotalPayroll DESC and LIMIT N.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trực quan hóa phân bổ quỹ lương và thẻ KPI" if not is_en else "Visualize payroll allocation and KPI cards",
                "desc": "Hiển thị biểu đồ xếp hạng quỹ lương Top phòng ban và bộ 4 thẻ KPI tài chính nhân sự." if not is_en else "Render payroll ranking chart and 4 executive KPI cards.",
                "status": "done"
            }
        ]

    # Mẫu 0.099: Đếm số lượng nhân viên từng thay đổi phòng ban ít nhất 1 lần
    is_dept_transfer_count_plan = (
        (
            any(k in q_low for k in ["thay đổi phòng ban", "thay đổi phòng", "đổi phòng ban", "đổi phòng", "chuyển phòng ban", "chuyển phòng", "luân chuyển phòng ban", "luân chuyển phòng", "luân chuyển bộ phận"])
            or (any(k in q_low for k in ["thay đổi", "đổi", "chuyển", "luân chuyển"]) and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
        )
        and any(k in q_low for k in ["bao nhiêu", "số lượng", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many", "mấy"])
        and not any(k in q_low for k in ["danh sách", "liệt kê", "những ai", "top", "ai là"])
    )
    if is_dept_transfer_count_plan:
        return [
            {
                "step": 1,
                "name": "Quét toàn bộ lịch sử luân chuyển phòng ban" if not is_en else "Scan complete department assignment history",
                "desc": "Truy vấn bảng dept_emp trên toàn bộ các thời kỳ công tác của nhân sự (không lọc to_date)." if not is_en else "Query dept_emp across all historical tenure without to_date filter.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Lọc nhân viên từng công tác từ 2 phòng ban trở lên" if not is_en else "Filter employees with >= 2 department assignments",
                "desc": "Gom nhóm theo emp_no và lọc điều kiện HAVING COUNT(DISTINCT dept_no) > 1." if not is_en else "Group by emp_no and apply HAVING COUNT(DISTINCT dept_no) > 1.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tổng hợp số lượng và tính tỷ lệ luân chuyển nội bộ" if not is_en else "Aggregate count and calculate transfer rate",
                "desc": "Đếm COUNT(*) số người đổi phòng và tính % so với tổng 300,024 nhân viên toàn lịch sử." if not is_en else "Count transferred employees and compute percentage of all-time 300,024 workforce.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Trình bày báo cáo tổng hợp và thẻ KPI tỷ lệ luân chuyển" if not is_en else "Present summary metrics and mobility KPI cards",
                "desc": "Xuất 1 dòng số liệu tổng hợp kèm bộ 4 thẻ KPI đo lường tính linh hoạt nhân sự." if not is_en else "Output 1-row summary and 4 executive internal mobility KPI cards.",
                "status": "done"
            }
        ]

    # Mẫu 0.1: Tỷ lệ thăng chức / đổi chức danh theo giới tính Nam vs Nữ
    if any(k in q_low for k in ["thăng chức", "đổi chức danh", "chuyển chức danh"]) and any(k in q_low for k in ["nam", "nữ", "giới tính"]):
        return [
            {
                "step": 1,
                "name": "Lọc danh sách nhân sự từng được thăng chức" if not is_en else "Isolate promoted employees cohort",
                "desc": "Gom nhóm bảng titles theo emp_no và lọc các nhân viên có từ 2 chức danh trở lên trong lịch sử: HAVING COUNT(*) >= 2." if not is_en else "Group titles by emp_no and filter employees having at least 2 title assignments: HAVING COUNT(*) >= 2.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Thống kê tổng số nhân sự theo từng giới tính" if not is_en else "Count total employees per gender",
                "desc": "Đếm tổng số nhân viên Nam (M) và Nữ (F) từ bảng employees để làm mẫu số tính tỷ lệ." if not is_en else "Count total Male and Female workforce from employees table to serve as calculation denominator.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Tính toán tỷ lệ phần trăm thăng chức chuẩn hóa" if not is_en else "Compute normalized promotion rate",
                "desc": "Tính tỷ lệ thăng chức riêng cho từng giới: PromotedEmployees * 100.0 / TotalEmployees." if not is_en else "Calculate gender-specific promotion rate: PromotedEmployees * 100.0 / TotalEmployees.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Đối chiếu tỷ lệ thăng chức Nam vs Nữ" if not is_en else "Benchmark Male vs Female promotion rates",
                "desc": "Trích xuất số lượng thăng chức, tổng nhân sự và tỷ lệ % thăng chức của từng giới tính để so sánh bình đẳng." if not is_en else "Output promoted count, total workforce, and promotion rate percentage for gender equity comparison.",
                "status": "done"
            }
        ]

    # Mẫu 0.44: Nhân viên nhận lương cao hơn mức lương trung bình của người cùng chức danh (Title)
    is_employee_above_title_avg = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "ai", "người", "employee"])
        and any(k in q_low for k in ["cao hơn", "vượt", "thấp hơn", "higher", "above", "lower", "below"])
        and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "avg salary", "average salary"])
        and any(k in q_low for k in ["cùng chức danh", "chức danh", "title", "same title"])
    )
    if is_employee_above_title_avg:
        m_lim = re.search(r"\b(?:top|đầu)\s*(\d+)\b", q_low)
        lim_str = m_lim.group(1) if m_lim else "10"
        return [
            {
                "step": 1,
                "name": "Tính toán lương trung bình hiện tại theo từng chức danh (CTE TitleAvg)" if not is_en else "Compute current average salary per title (CTE TitleAvg)",
                "desc": "Nhóm theo t.title từ bảng titles và tính ROUND(AVG(s.salary), 2) AS TitleAvgSalary với điều kiện t.to_date = '9999-01-01' và s.to_date = '9999-01-01'." if not is_en else "Group by t.title and compute current average salary.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Lọc hợp đồng và chức danh hiện hành của từng nhân sự" if not is_en else "Filter active employee contract and current title",
                "desc": "Kết nối bảng employees với salaries, dept_emp, departments và titles tại mốc to_date = '9999-01-01'." if not is_en else "Join employees with active salaries, departments, and titles.",
                "status": "done"
            },
            {
                "step": 3,
                "name": f"Đối chiếu lương cao hơn trung bình chức danh và xếp hạng Top {lim_str}" if not is_en else f"Benchmark salary above title average and rank Top {lim_str}",
                "desc": "Áp dụng điều kiện WHERE s.salary > ta.TitleAvgSalary, tính độ chênh lệch SalarySurplus = ROUND(s.salary - ta.TitleAvgSalary, 2) và sắp xếp giảm dần." if not is_en else "Filter WHERE s.salary > ta.TitleAvgSalary, compute SalarySurplus and sort DESC.",
                "status": "done"
            }
        ]

    # Mẫu 0.45: Top nhân viên có tỷ lệ tăng lương ấn tượng nhất: so sánh mức lương đầu tiên khi vào công ty và mức lương hiện tại
    is_employee_salary_growth = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "employee"])
        and any(k in q_low for k in ["tỷ lệ tăng lương", "tỉ lệ tăng lương", "tăng lương ấn tượng", "tốc độ tăng lương", "tăng trưởng lương", "mức tăng lương", "salary growth", "highest raise rate", "salary increase"])
        and (
            any(k in q_low for k in ["đầu tiên", "khởi điểm", "lúc vào", "khi vào", "gia nhập", "initial", "starting", "first salary"])
            or any(k in q_low for k in ["hiện tại", "bây giờ", "đến nay", "current", "latest"])
        )
    )
    if is_employee_salary_growth:
        m_lim = re.search(r"\b(?:top|đầu)\s*(\d+)\b", q_low)
        lim_str = m_lim.group(1) if m_lim else "5"
        return [
            {
                "step": 1,
                "name": "Lọc nhân sự hiện hành và mức lương hiện tại (CTE ActiveEmployees)" if not is_en else "Filter active employees and current compensation (CTE ActiveEmployees)",
                "desc": "Lọc nhân viên đang công tác (s.to_date = '9999-01-01' và de.to_date = '9999-01-01') để lấy FullName, Department, CurrentTitle và CurrentSalary." if not is_en else "Filter active employees with s.to_date = '9999-01-01' and de.to_date = '9999-01-01' for current salary.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Xác định mức lương khởi điểm đầu tiên khi vào công ty (CTE InitialSalaries)" if not is_en else "Determine starting salary at hire date (CTE InitialSalaries)",
                "desc": "Tìm bản ghi lương đầu tiên bằng cách nhóm emp_no lấy MIN(from_date) từ bảng salaries để trích xuất InitialSalary." if not is_en else "Find first salary record per emp_no using MIN(from_date) to extract InitialSalary.",
                "status": "done"
            },
            {
                "step": 3,
                "name": f"Tính toán tỷ lệ tăng lương phần trăm và xếp hạng Top {lim_str}" if not is_en else f"Compute percentage salary growth and rank Top {lim_str}",
                "desc": "Tính SalaryIncrease = CurrentSalary - InitialSalary và SalaryGrowthRatePct = ROUND((CurrentSalary - InitialSalary) * 100.0 / InitialSalary, 2), sắp xếp ORDER BY SalaryGrowthRatePct DESC." if not is_en else "Compute SalaryIncrease and SalaryGrowthRatePct = ROUND((CurrentSalary - InitialSalary) * 100.0 / InitialSalary, 2), sort DESC.",
                "status": "done"
            }
        ]

    # Mẫu 0.46: Nhân viên từng bị giảm lương trong lịch sử làm việc tại công ty
    is_salary_reduction_query = (
        any(k in q_low for k in ["giảm lương", "hạ lương", "bị giảm", "bị hạ", "salary reduction", "salary decrease", "pay cut"])
        or (any(k in q_low for k in ["lương", "salary"]) and any(k in q_low for k in ["giảm", "hạ", "tụt", "thấp hơn lần trước", "thấp hơn kỳ trước", "reduction", "decrease", "cut"]))
    )
    if is_salary_reduction_query:
        m_lim = re.search(r"\b(?:top|đầu)\s*(\d+)\b", q_low)
        lim_str = m_lim.group(1) if m_lim else "10"
        return [
            {
                "step": 1,
                "name": "Truy vết lịch sử thay đổi lương theo từng nhân viên (CTE SalaryStep)" if not is_en else "Track compensation history step per employee (CTE SalaryStep)",
                "desc": "Sử dụng hàm cửa sổ LAG(s.salary) OVER (PARTITION BY s.emp_no ORDER BY s.from_date ASC) AS PrevSalary để so sánh mức lương kỳ trước với s.salary AS NewSalary." if not is_en else "Use LAG window function to compare current salary with previous salary step.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Lọc các trường hợp bị giảm lương và tính biên độ giảm (CTE SalaryReductions)" if not is_en else "Filter salary reduction events and calculate reduction delta (CTE SalaryReductions)",
                "desc": "Áp dụng điều kiện WHERE PrevSalary IS NOT NULL AND NewSalary < PrevSalary, tính mức giảm tuyệt đối SalaryReduction = (PrevSalary - NewSalary) và tỷ lệ giảm ReductionPct." if not is_en else "Filter WHERE PrevSalary IS NOT NULL AND NewSalary < PrevSalary, compute SalaryReduction and ReductionPct.",
                "status": "done"
            },
            {
                "step": 3,
                "name": f"Kết nối thông tin nhân sự, phòng ban tương ứng và xếp hạng Top {lim_str}" if not is_en else f"Join employee profile, department at reduction date and rank Top {lim_str}",
                "desc": "Kết nối bảng employees, dept_emp (với sr.from_date BETWEEN de.from_date AND de.to_date) và departments để lấy FullName, Department, ReductionDate, sắp xếp ORDER BY SalaryReduction DESC." if not is_en else "Join employees, dept_emp, and departments to retrieve FullName, Department, ReductionDate, sort DESC.",
                "status": "done"
            }
        ]

    # Mẫu 0.5: Nhân viên được tăng lương nhiều lần nhất nhưng lương hiện tại dưới ngưỡng (Top Raises with Capped Salary)
    is_top_raises_low_salary = (
        any(k in q_low for k in ["tăng lương", "lần tăng", "được tăng"])
        and any(k in q_low for k in ["nhiều lần nhất", "nhiều nhất", "nhiều lần", "most raises"])
        and any(k in q_low for k in ["dưới", "thấp hơn", "chưa tới", "không quá", "<"])
        and any(k in q_low for k in ["lương", "salary", "mức lương", "$"])
    )
    if is_top_raises_low_salary:
        m_sal = re.search(r"(\$?\d+(?:[.,]\d+)*)\s*(?:k|nghìn|usd|\$)?", q_low)
        cap_val_str = m_sal.group(1) if m_sal else "60000"
        return [
            {
                "step": 1,
                "name": f"Lọc nhân sự hiện hành có lương dưới ngưỡng ({cap_val_str})" if not is_en else f"Filter active employees with salary under {cap_val_str}",
                "desc": f"Lọc nhân viên đang công tác (to_date = '9999-01-01') có mức lương hiện tại < {cap_val_str} (CTE ActiveSalariesUnderCap)." if not is_en else f"Filter active contracts with salary < {cap_val_str}.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Thống kê số lần tăng lương trong lịch sử" if not is_en else "Count historical salary raises",
                "desc": "Gom nhóm theo emp_no trên bảng salaries và đếm số lần điều chỉnh lương: COUNT(*) AS RaiseCount (CTE EmployeeRaiseCounts)." if not is_en else "Count salary adjustments per employee: COUNT(*) AS RaiseCount.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Đối chiếu giao thoa & Xếp hạng nhân sự theo số lần tăng nhiều nhất" if not is_en else "Join and rank by highest raise count",
                "desc": "Join 2 tập dữ liệu, sắp xếp theo RaiseCount DESC, CurrentSalary ASC và giới hạn Top 10." if not is_en else "Join CTEs, order by RaiseCount DESC, CurrentSalary ASC, LIMIT 10.",
                "status": "done"
            }
        ]

    # Mẫu 0: Nhân viên có số lần tăng lương ít nhưng lương thuộc top cao nhất (Low Raises & Top Percentile Cohort)
    if any(k in q_low for k in ["tăng lương", "lần tăng"]) and any(k in q_low for k in ["ít hơn", "dưới", "nhỏ hơn", "chưa quá", "tối đa"]) and not any(k in q_low for k in ["nhiều lần nhất", "nhiều nhất", "nhiều lần", "most raises"]):
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

    # Mẫu 1.0: Tăng trưởng quy mô nhân sự phòng ban trong các năm đầu hoạt động (Department Headcount Growth Rate)
    if any(k in q_low for k in ["tăng trưởng", "phát triển", "mở rộng quy mô"]) and any(k in q_low for k in ["quy mô", "nhân sự", "nhân viên", "headcount"]) and any(k in q_low for k in ["phòng ban", "phòng", "department"]) and not any(k in q_low for k in ["lương", "salary", "thu nhập"]):
        return [
            {
                "step": 1,
                "name": "Xác định quy mô nhân sự mốc ban đầu (Năm 1)" if not is_en else "Compute Baseline Headcount (Year 1)",
                "desc": "Tính số lượng nhân sự active theo từng phòng ban trong năm đầu hoạt động (1985) qua COUNT(DISTINCT CASE WHEN ...)."
                if not is_en else "Count distinct active personnel by department in Year 1."
            },
            {
                "step": 2,
                "name": "Xác định quy mô nhân sự mốc đối chiếu (Năm 3)" if not is_en else "Compute Target Headcount (Year 3)",
                "desc": "Tính số lượng nhân sự active theo từng phòng ban trong năm thứ 3 hoạt động (1987)."
                if not is_en else "Count distinct active personnel by department in Year 3."
            },
            {
                "step": 3,
                "name": "Tính tốc độ tăng trưởng phần trăm & Xếp hạng" if not is_en else "Compute Percentage Growth & Rank",
                "desc": "Tính tỷ lệ tăng trưởng: ((Year3 - Year1) / Year1) * 100%, sắp xếp giảm dần để tìm phòng ban tăng trưởng nhanh nhất."
                if not is_en else "Compute growth rate: ((Year3 - Year1) / Year1) * 100% and order descending."
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

    # Mẫu 1.99: Nhân viên từng công tác tại ít nhất N phòng ban kèm so sánh lương với phòng ban đầu tiên từng gia nhập
    is_multi_dept_first_dept_sal = (
        any(k in q_low for k in ["nhiều phòng", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng", "2 phòng ban", "chuyển phòng", "luân chuyển"])
        and any(k in q_low for k in ["phòng ban đầu tiên", "phòng đầu tiên", "đầu tiên họ từng", "phòng ban khởi điểm", "first department", "first dept"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    )
    if is_multi_dept_first_dept_sal:
        comp_dir = "thấp hơn" if any(k in q_low for k in ["thấp hơn", "nhỏ hơn", "lower", "below", "less"]) else "so sánh với"
        return [
            {
                "step": 1,
                "name": "Xác định phòng ban đầu tiên từng gia nhập (CTE FirstDept)" if not is_en else "Identify First Department (CTE FirstDept)",
                "desc": "Truy vấn bảng dept_emp dùng ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) để xác định phòng ban đầu tiên mà mỗi nhân viên từng gia nhập."
                if not is_en else "Query dept_emp using ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) to find the initial department of each employee.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tính mức lương trung bình hiện hành của các phòng ban (CTE DeptAvg)" if not is_en else "Calculate Department Current Average Salary (CTE DeptAvg)",
                "desc": "Tính AVG(salary) của nhân sự đang công tác (to_date = '9999-01-01') cho từng phòng ban."
                if not is_en else "Compute current AVG(salary) where to_date = '9999-01-01' for each department.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Lọc nhân sự từng làm việc tại ít nhất 2 phòng ban (CTE MultiDept)" if not is_en else "Filter Multi-Department Staff (CTE MultiDept)",
                "desc": "Gom nhóm theo emp_no trên dept_emp và áp dụng HAVING COUNT(DISTINCT dept_no) >= 2."
                if not is_en else "Group by emp_no in dept_emp and filter HAVING COUNT(DISTINCT dept_no) >= 2.",
                "status": "done"
            },
            {
                "step": 4,
                "name": f"Đối chiếu lương hiện tại {comp_dir} lương trung bình phòng ban đầu tiên" if not is_en else "Compare Current Salary vs First Dept Average",
                "desc": f"Lọc nhân sự có s_curr.salary < da.AvgSalary, tính mức thâm hụt lương (SalaryDeficit) và sắp xếp giảm dần."
                if not is_en else "Filter active salary vs first department average, compute SalaryDeficit and order descending.",
                "status": "done"
            }
        ]

    # Mẫu 2: Nhân viên từng công tác qua nhiều phòng ban (Multi-department Employees)
    if any(k in q_low for k in ["nhiều phòng", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng", "2 phòng ban"]) and any(k in q_low for k in ["nhân viên", "nhân sự", "liệt kê"]) and not any(k in q_low for k in ["lương", "salary", "thu nhập", "thấp hơn", "cao hơn", "đầu tiên", "first dept", "first department"]):
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

    # Mẫu 0.88: Xếp hạng sản phẩm theo doanh số trong từng quý và xác định tăng/giảm hạng mạnh nhất, luôn trong top 5
    is_product_quarterly_ranking = (
        any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
        and any(k in q_low for k in ["quý", "quarter"])
        and any(k in q_low for k in ["xếp hạng", "thứ hạng", "hạng", "rank", "tăng hạng", "giảm hạng", "top 5", "top 10"])
    )
    if is_product_quarterly_ranking:
        yr_m = re.search(r'\b(20\d{2})\b', q_low)
        yr_str = f" năm {yr_m.group(1)}" if yr_m else ""
        return [
            {
                "step": 1,
                "name": f"Tổng hợp doanh số sản phẩm theo từng quý{yr_str} (CTE QuarterlyProductSales)" if not is_en else "Aggregate product sales per quarter (CTE QuarterlyProductSales)",
                "desc": "Kết nối bảng sales với products, tính SUM(s.Amount) AS TotalSales nhóm theo pr.Product và Quarter." if not is_en else "Join sales and products, compute quarterly sales per product.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Xếp hạng sản phẩm độc lập trong từng quý (CTE QuarterlyRanks)" if not is_en else "Rank products per quarter independently (CTE QuarterlyRanks)",
                "desc": "Sử dụng DENSE_RANK() OVER (PARTITION BY Quarter ORDER BY TotalSales DESC) AS ProductRank để đánh số thứ hạng độc lập theo từng quý." if not is_en else "Compute dense rank per quarter independently.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "Chuyển ma trận thứ hạng ngang (Pivot) và tính độ biến động (CTE PivotRanks)" if not is_en else "Pivot quarterly ranks and compute rank delta (CTE PivotRanks)",
                "desc": "Pivot Q1_Rank, Q2_Rank, Q3_Rank, Q4_Rank và tính RankChange = (CAST(Q1_Rank AS SIGNED) - CAST(Q4_Rank AS SIGNED))." if not is_en else "Pivot ranks across quarters and calculate signed rank delta.",
                "status": "done"
            },
            {
                "step": 4,
                "name": "Xác định sản phẩm tăng/giảm hạng mạnh nhất và kiểm tra Top 5 tất cả các quý" if not is_en else "Identify extreme rank movers and Top 5 consistency",
                "desc": "Gắn nhãn phân loại 'Tăng hạng mạnh nhất', 'Giảm hạng mạnh nhất', 'Luôn trong Top 5' và sắp xếp theo độ biến động thứ hạng." if not is_en else "Classify highest gain, highest drop, and Top 5 consistency.",
                "status": "done"
            }
        ]

    # Mẫu 0.89: So sánh tổng doanh số và số lượng hộp bán ra giữa các Team kinh doanh
    is_team_sales_boxes = (
        any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh"])
        and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền"])
        and any(k in q_low for k in ["hộp", "thùng", "boxes", "số lượng"])
    )
    if is_team_sales_boxes:
        return [
            {
                "step": 1,
                "name": "Xác định thực thể Đội ngũ (Team) và liên kết bán hàng (JOIN people)" if not is_en else "Identify sales team entity and link sales (JOIN people)",
                "desc": "Kết nối bảng sales s với people pe qua SPID, lọc bỏ các dòng rỗng (WHERE pe.Team != '' AND pe.Team IS NOT NULL)." if not is_en else "Join sales with people via SPID, filter out blank teams.",
                "status": "done"
            },
            {
                "step": 2,
                "name": "Tổng hợp đa chỉ số: Doanh số ($) & Số lượng hộp bán ra" if not is_en else "Aggregate multi-metrics: Sales ($) & Boxes Sold",
                "desc": "Tính SUM(s.Amount) AS TotalSales, SUM(s.Boxes) AS TotalBoxesSold và ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS AvgPricePerBox." if not is_en else "Calculate TotalSales, TotalBoxesSold, and AvgPricePerBox.",
                "status": "done"
            },
            {
                "step": 3,
                "name": "So sánh quy mô và sắp xếp thứ bậc hiệu quả giữa các Team" if not is_en else "Compare scale and rank sales teams",
                "desc": "Nhóm theo pe.Team và sắp xếp theo TotalSales DESC để đối chiếu toàn diện giữa các đội ngũ." if not is_en else "Group by pe.Team and order by TotalSales DESC for comprehensive comparison.",
                "status": "done"
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
    if any(k in q_low for k in ["lương", "thu nhập", "salary", "bảng lương", "tiền", "kiếm tiền"]):
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
    if (
        any(k in q_low for k in ["nhóm lương", "bậc lương", "khoảng lương", "3 nhóm lương", "thu nhập thấp", "thu nhập trung bình", "thu nhập cao"])
        or (any(k in q_low for k in ["phân loại", "chia thành", "nhóm", "tier", "bracket"]) and any(k in q_low for k in ["lương", "thu nhập", "salary"]) and any(k in q_low for k in ["tỷ lệ", "%", "số lượng", "mỗi nhóm"]))
    ) and not any(k in q_low for k in ["kỳ cựu", "mới vào", "so sánh", "đối chiếu", "thâm niên"]):
        metrics.extend(["Số lượng nhân sự theo nhóm lương (EmployeeCount)", "Tỷ lệ cơ cấu thu nhập (Percentage)"])
    elif (
        any(k in q_low for k in ["biến động lương", "tỷ lệ biến động lương", "độ biến động lương", "dao động lương"])
        or (any(k in q_low for k in ["biến động", "fluctuation", "dao động", "phân tán"]) and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"]) and any(k in q_low for k in ["lương", "salary", "thu nhập"]))
    ):
        metrics.extend(["Hệ số biến động lương (FluctuationRate)", "Lương trung bình hiện tại (CurrentAvgSalary)", "Độ lệch chuẩn lương (SalaryStdDev)"])
    elif (
        any(k in q_low for k in ["quỹ lương", "tổng quỹ lương", "tổng chi trả lương", "chi trả quỹ lương", "chi phí lương"])
        or (any(k in q_low for k in ["tổng lương", "tổng chi lương", "tổng tiền lương"]) and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"]))
    ):
        metrics.extend(["Tổng quỹ lương chi trả (TotalPayroll)", "Quy mô nhân sự phòng ban (Headcount)", "Lương trung bình (AvgSalary)"])
    elif (
        (any(k in q_low for k in ["thay đổi phòng ban", "thay đổi phòng", "đổi phòng ban", "đổi phòng", "chuyển phòng ban", "chuyển phòng", "luân chuyển phòng ban", "luân chuyển phòng"])
         or (any(k in q_low for k in ["thay đổi", "đổi", "chuyển", "luân chuyển"]) and any(k in q_low for k in ["phòng ban", "phòng", "department"])))
        and any(k in q_low for k in ["bao nhiêu", "số lượng", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many", "mấy"])
    ):
        metrics.extend(["Số nhân viên từng đổi phòng ban (EmployeesChangedDepartment)", "Tổng nhân sự công ty (TotalEmployees)", "Tỷ lệ luân chuyển (PercentageChangedDept)"])
    elif (
        any(k in q_low for k in ["nhiều phòng", "ít nhất 2 phòng", "từ 2 phòng", "qua 2 phòng", "2 phòng ban", "chuyển phòng", "luân chuyển"])
        and any(k in q_low for k in ["phòng ban đầu tiên", "phòng đầu tiên", "đầu tiên họ từng", "phòng ban khởi điểm", "first department", "first dept"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    ):
        metrics.extend(["Lương hiện tại (CurrentSalary)", "Lương TB phòng ban đầu tiên (FirstDeptAvgSalary)", "Mức thâm hụt lương (SalaryDeficit)", "Số phòng ban từng làm (DepartmentCount)"])
    elif any(k in q_low for k in ["manager", "quản lý", "trưởng phòng"]) and any(k in q_low for k in ["nam", "nữ", "giới tính"]) and any(k in q_low for k in ["gần nhất", "5 năm", "thăng chức", "bổ nhiệm"]):
        metrics.append("Số lượng Quản lý bổ nhiệm Nam vs Nữ (MaleManagers & FemaleManagers)")
    elif any(k in q_low for k in ["kỳ cựu", "thâm niên", "trên 5 năm"]) and any(k in q_low for k in ["mới", "mới vào", "dưới 2 năm"]):
        metrics.append("Lương TB Kỳ Cựu vs Mới Vào (SeniorAvgSalary & NewHireAvgSalary)")
    elif any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa"]) and any(k in q_low for k in ["lương", "salary", "thu nhập"]):
        metrics.append("Độ chênh lệch lương nội bộ (SalarySpread = MaxSalary - MinSalary)")
    elif any(k in q_low for k in ["kiếm được nhiều tiền nhất", "kiếm nhiều tiền nhất", "nhiều tiền nhất", "kiếm tiền", "thu nhập cao nhất", "lương cao nhất"]):
        metrics.append("Mức thu nhập / Lương cao nhất (Salary)")
    elif any(k in q_low for k in ["quy mô", "nhân sự", "nhân viên", "headcount"]) and any(k in q_low for k in ["tăng trưởng", "growth", "tốc độ"]):
        metrics.append("Tốc độ tăng trưởng quy mô nhân sự (HeadcountGrowthRatePct)")
    elif any(k in q_low for k in ["tăng trưởng", "growth"]):
        metrics.append("Tốc độ tăng trưởng hàng năm (AvgAnnualSalaryGrowth)")
    elif any(k in q_low for k in ["lương trung bình", "avg salary"]):
        metrics.append("Lương trung bình (AvgSalary)")
    elif any(k in q_low for k in ["lương", "salary", "thu nhập"]):
        metrics.append("Mức lương (Salary)")
    if any(k in q_low for k in ["quy mô", "nhân sự", "số lượng", "headcount", "đông nhất"]) and "Tốc độ tăng trưởng quy mô nhân sự (HeadcountGrowthRatePct)" not in metrics:
        metrics.append("Quy mô nhân sự (Headcount)")
    if any(k in q_low for k in ["thâm niên", "tenure", "năm làm việc", "gắn bó", "cống hiến"]):
        metrics.append("Thâm niên công tác (YearsOfService)")
    if any(k in q_low for k in ["lần tăng lương", "số lần tăng"]):
        metrics.append("Số lần tăng lương (RaiseCount)")

    # 4. Xác định mốc thời gian
    m_yr_th = re.search(r"\b(19\d\d|20\d\d)\b", q_low)
    m_yr_op = re.search(r"(\d+)\s*năm đầu", q_low)
    if m_yr_op or any(k in q_low for k in ["năm đầu hoạt động", "giai đoạn đầu", "thời kỳ đầu", "mới thành lập", "khởi đầu"]):
        n_yr = int(m_yr_op.group(1)) if m_yr_op else 3
        time_horizon = f"{n_yr} năm đầu hoạt động công ty (1985 - {1985 + n_yr - 1})" if not is_en else f"First {n_yr} years of operations (1985 - {1985 + n_yr - 1})"
    elif any(k in q_low for k in ["hiện tại", "hiện nay", "đương nhiệm", "current"]) or (any(k in q_low for k in ["đang"]) and not any(k in q_low for k in ["năm đầu", "trước đây", "lịch sử"])):
        time_horizon = "Thời điểm hiện tại (to_date = '9999-01-01')" if not is_en else "Current active state (to_date = '9999-01-01')"
    elif m_yr_th and not any(k in q_low for k in ["5 năm", "gần nhất"]):
        time_horizon = f"Năm {m_yr_th.group(1)}" if not is_en else f"Year {m_yr_th.group(1)}"
    elif any(k in q_low for k in ["5 năm gần nhất", "5 năm gần đây", "gần nhất"]):
        time_horizon = "5 năm gần nhất (tương đối theo MAX(from_date) trong CSDL)" if not is_en else "Last 5 years (relative to MAX(from_date))"
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
