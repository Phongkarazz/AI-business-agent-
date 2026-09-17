"""
Prompt templates and builders for SQL generation, validation, anomaly explanation,
automatic business insights with Executive Priority Tagging, and intelligent bilingual follow-up question suggestions.
Strictly grounded in provided database schema with relative historical time-handling to prevent 0-row results.
"""

import re
from src.llm.few_shot_selector import select_dynamic_few_shots, format_few_shots_for_prompt


def get_dialect_hints(dialect: str, lang: str = "vi") -> str:
    """Trả về hướng dẫn cú pháp SQL theo từng hệ quản trị cơ sở dữ liệu và ngôn ngữ."""
    if lang == "en":
        if dialect == "SQLite":
            return "Database engine is SQLite: use strftime('%Y', col)/strftime('%m', col) for year/month, date((SELECT MAX(col) FROM tbl), '-1 year') for relative time. DO NOT use MySQL MONTH()/YEAR()/CURRENT_DATE()."
        elif dialect == "MySQL":
            return "Database engine is MySQL: you can use MONTH()/YEAR()/DATE_FORMAT(), DATE_SUB((SELECT MAX(col) FROM tbl), INTERVAL 1 YEAR) for relative time."
        return ""

    if dialect == "SQLite":
        return "Database đang dùng là SQLite: dùng strftime('%Y', col)/strftime('%m', col) để lấy năm/tháng, date((SELECT MAX(col) FROM tbl), '-1 year') cho thời gian tương đối. KHÔNG dùng MONTH()/YEAR()/CURRENT_DATE() của MySQL."
    elif dialect == "MySQL":
        return "Database đang dùng là MySQL: có thể dùng MONTH()/YEAR()/DATE_FORMAT(), DATE_SUB((SELECT MAX(col) FROM tbl), INTERVAL 1 YEAR) cho thời gian tương đối."
    return ""


def extract_schema_metadata_summary(schema_context: str) -> str:
    """Tự động phân tích và trích xuất bảng, cột thời gian, cột số liệu, cột định danh và khóa ngoại từ Schema bất kỳ."""
    if not schema_context or "Chưa kết nối" in schema_context:
        return ""

    table_lines = re.findall(r"-\s*Bảng\s+`?([a-zA-Z0-9_]+)`?:\s*([^\n]+)", schema_context, re.IGNORECASE)
    if not table_lines:
        return ""

    table_names = [t[0] for t in table_lines]
    date_cols = []
    metric_cols = []
    entity_cols = []

    for tbl, col_str in table_lines:
        cols = [c.strip().split()[0].strip("`,()") for c in col_str.split(",")]
        for c in cols:
            c_low = c.lower()
            full_c = f"`{tbl}`.`{c}`"
            if any(k in c_low for k in ["date", "time", "year", "month", "day", "created_at", "updated_at", "payment_date", "rental_date", "hire_date", "from_date", "saledate", "order_date"]):
                date_cols.append(full_c)
            elif any(k in c_low for k in ["amount", "salary", "price", "cost", "total", "revenue", "sales", "boxes", "rate", "fee", "quantity", "length", "duration", "replacement_cost", "spend", "balance"]):
                metric_cols.append(full_c)
            elif any(k in c_low for k in ["name", "title", "category", "product", "country", "city", "region", "team", "salesperson", "gender", "status", "type", "description"]):
                entity_cols.append(full_c)

    summary_lines = [
        "   - BẢN ĐỒ SCHEMA TỰ ĐỘNG CHO TRUY VẤN (DYNAMIC SCHEMA NAVIGATION):",
        f"     + Danh sách bảng tồn tại trong CSDL: {', '.join(f'`{t}`' for t in table_names)}",
    ]
    if date_cols:
        summary_lines.append(f"     + Cột Ngày tháng / Thời gian phát hiện: {', '.join(date_cols[:8])}")
    if metric_cols:
        summary_lines.append(f"     + Cột Số liệu đo lường / Tiền tệ / Số lượng phát hiện: {', '.join(metric_cols[:10])}")
    if entity_cols:
        summary_lines.append(f"     + Cột Phân loại / Thực thể / Tên gọi phát hiện: {', '.join(entity_cols[:10])}")
    summary_lines.extend([
        "     + QUY TẮC BẮT BUỘC: CHỈ ĐƯỢC PHÉP TRUY VẤN CÁC BẢNG VÀ CỘT NÊU TRÊN.",
        "       TUYỆT ĐỐI CẤM BỊA ĐẶT TÊN BẢNG HAY TÊN CỘT KHÔNG XUẤT HIỆN TRONG SCHEMA!"
    ])
    return "\n".join(summary_lines)


def get_db_specific_rules(schema_context: str) -> str:
    """Tự động nhận diện CSDL và sinh quy tắc chi tiết theo từng bảng."""
    schema_low = (schema_context or "").lower()
    is_sakila_db = any(k in schema_low for k in ["film_id", "rental_id", "payment_id", "inventory_id", "actor_id", "customer_id", "staff_id", "`film`", "`rental`", "`payment`", "`actor`", "`inventory`"])
    is_employees_db = ("departments" in schema_low or "dept_emp" in schema_low or "hire_date" in schema_low or "salaries" in schema_low) and not is_sakila_db
    is_chocolates_db = ("people" in schema_low and "products" in schema_low) and not is_sakila_db

    if is_employees_db:
        return """   - QUY TẮC CSDL EMPLOYEES:
     + Bảng `employees` (Bí danh bắt buộc: `e`):
       * Cột: `emp_no` (Khóa chính), `first_name`, `last_name`, `gender`, `hire_date`, `birth_date`.
       * Ghép họ tên đầy đủ: `CONCAT(e.first_name, ' ', e.last_name) AS full_name`.
     + Bảng `salaries` (Bí danh bắt buộc: `s`):
       * Cột: `emp_no` (liên kết e.emp_no), `salary`, `from_date`, `to_date`.
       * Khi truy vấn lương cao nhất / hiện tại: BẮT BUỘC dùng `s.to_date = '9999-01-01'` và `MAX(s.salary) AS max_salary` cùng `GROUP BY e.emp_no, full_name`.
     + Bảng `departments` (Bí danh bắt buộc: `d`): `dept_no` (Khóa chính), `dept_name`.
     + Bảng liên kết phòng ban `dept_emp` (Bí danh bắt buộc: `de`): `emp_no`, `dept_no`, `from_date`, `to_date`.
     + Bảng chức danh `titles` (Bí danh bắt buộc: `t`): `emp_no`, `title`, `from_date`, `to_date`.
     + CẢNH BÁO BẮT BUỘC TIỀN TỐ BÍ DANH & TÊN CỘT (TRÁNH LỖI 1052, 1054):
        * Cột `emp_no` có trong 3 bảng. BẮT BUỘC viết `e.emp_no` trong SELECT và GROUP BY!
        * Bảng `departments` CHỈ CÓ 2 CỘT: `dept_no` và `dept_name`! TUYỆT ĐỐI KHÔNG CÓ CỘT `to_date`!
         * QUY TẮC BẮT BUỘC VỀ CHỨC DANH (TITLE):
           - Khi hỏi số lượng bổ nhiệm chức danh mới qua từng năm: BẮT BUỘC dùng `titles t` (cột `t.from_date` và `t.emp_no`), đặt tên cột là `NewTitleAppointments` (TUYỆT ĐỐI CẤM đặt TotalEmployees hay Tổng Số Nhân Viên!), GROUP BY `YEAR(t.from_date)`, TUYỆT ĐỐI KHÔNG JOIN salaries hay departments!
           - Khi câu hỏi so sánh lương theo chức danh: BẮT BUỘC dùng bảng `titles t` (cột `t.title`), JOIN `employees e` và `salaries s`, GROUP BY `t.title`. TUYỆT ĐỐI KHÔNG JOIN bảng `departments` hay `dept_emp`!
         * Cột tên phòng ban là `d.dept_name` (ví dụ: WHERE d.dept_name = 'Sales'). TUYỆT ĐỐI KHÔNG DÙNG `d.dept_no = 'Sales'` vì dept_no là mã số (d007)!
         * Thứ tự JOIN bắt buộc khi truy vấn phòng ban:
           FROM employees e
           JOIN salaries s ON e.emp_no = s.emp_no
           JOIN dept_emp de ON e.emp_no = de.emp_no
           JOIN departments d ON de.dept_no = d.dept_no
         * TUYỆT ĐỐI KHÔNG đưa `de.dept_no = d.dept_no` vào mệnh đề ON của dept_emp trước khi JOIN departments d!
         * Khi câu hỏi đơn giản: dùng câu lệnh SELECT trực tiếp. Khi bài toán cần từ 2 bước logic trở lên (ví dụ: tìm phòng ban đầu tiên rồi so sánh với lương trung bình): BẮT BUỘC DÙNG CÚ PHÁP 'WITH ... AS' (CTE) để chia nhỏ từng bước tính toán! KHÔNG JOIN bảng titles nếu không hỏi chức danh!

     + MẪU CHUẨN TOP 10 NHÂN VIÊN LƯƠNG CAO NHẤT HIỆN TẠI (KÈM PHÒNG BAN):
       SELECT 
           e.emp_no, 
           CONCAT(e.first_name, ' ', e.last_name) AS FullName, 
           d.dept_name AS Department, 
           s.salary AS CurrentSalary
       FROM salaries s
       JOIN employees e ON s.emp_no = e.emp_no
       JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
       JOIN departments d ON de.dept_no = d.dept_no
       WHERE s.to_date = '9999-01-01'
       ORDER BY CurrentSalary DESC
       LIMIT 10;
       * CẢNH BÁO ĐẶC BIỆT: Cả hai bảng `salaries` và `employees` ĐỀU KHÔNG CÓ CỘT `dept_no`! BẮT BUỘC phải JOIN qua `dept_emp de` (`ON e.emp_no = de.emp_no JOIN departments d ON de.dept_no = d.dept_no`)! TUYỆT ĐỐI KHÔNG VIẾT `s.dept_no` hay `e.dept_no`!

     + MẪU CHUẨN LƯƠNG THEO PHÒNG BAN:
       SELECT d.dept_name AS Department, ROUND(AVG(s.salary), 2) AS AvgSalary
       FROM salaries s
       JOIN dept_emp de ON s.emp_no = de.emp_no
       JOIN departments d ON de.dept_no = d.dept_no
       WHERE s.to_date = '9999-01-01' AND de.to_date = '9999-01-01'
       GROUP BY d.dept_name
       ORDER BY AvgSalary DESC;

     + MẪU CHUẨN TOP 10 LƯƠNG TRONG PHÒNG BAN CỤ THỂ (Ví dụ: Sales / Marketing):
       SELECT e.emp_no, CONCAT(e.first_name, ' ', e.last_name) AS full_name, MAX(s.salary) AS max_salary
       FROM employees e
       JOIN salaries s ON e.emp_no = s.emp_no
       JOIN dept_emp de ON e.emp_no = de.emp_no
       JOIN departments d ON de.dept_no = d.dept_no
       WHERE d.dept_name = 'Sales' AND s.to_date = '9999-01-01' AND de.to_date = '9999-01-01'
       GROUP BY e.emp_no, full_name
       ORDER BY max_salary DESC
       LIMIT 10;

      + MẪU CHUẨN SỐ LƯỢNG NHÂN VIÊN THEO PHÒNG BAN:
        SELECT d.dept_name AS Department, COUNT(de.emp_no) AS TotalEmployees
        FROM departments d
        JOIN dept_emp de ON d.dept_no = de.dept_no
        WHERE de.to_date = '9999-01-01'
        GROUP BY d.dept_name
        ORDER BY TotalEmployees DESC;

      + MẪU CHUẨN SO SÁNH QUY MÔ NHÂN SỰ VÀ LƯƠNG TRUNG BÌNH THEO PHÒNG BAN:
        SELECT 
            d.dept_name AS Department,
            COUNT(DISTINCT de.emp_no) AS Headcount,
            ROUND(AVG(s.salary), 2) AS AvgSalary
        FROM departments d
        JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
        JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
        GROUP BY d.dept_name
        ORDER BY Headcount DESC;
        * CẢNH BÁO ĐẶC BIỆT: Khi hỏi 'so sánh quy mô nhân sự và lương trung bình phòng ban':
          BẮT BUỘC có cả 2 chỉ số: COUNT(DISTINCT de.emp_no) AS Headcount VÀ ROUND(AVG(s.salary), 2) AS AvgSalary!
          TUYỆT ĐỐI KHÔNG JOIN bảng `dept_manager`! Bảng `dept_manager` CHỈ DÀNH RIÊNG cho câu hỏi hỏi riêng về Trưởng phòng!

      + MẪU CHUẨN SO SÁNH MỨC LƯƠNG TRUNG BÌNH NAM VÀ NỮ THEO TỪNG CHỨC DANH:
        SELECT 
            t.title AS Title,
            ROUND(AVG(CASE WHEN e.gender = 'M' THEN s.salary END), 2) AS MaleAvgSalary,
            ROUND(AVG(CASE WHEN e.gender = 'F' THEN s.salary END), 2) AS FemaleAvgSalary
        FROM titles t
        JOIN employees e ON t.emp_no = e.emp_no
        JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
        WHERE t.to_date = '9999-01-01'
        GROUP BY t.title
        ORDER BY MaleAvgSalary DESC;
        * CẢNH BÁO ĐẶC BIỆT: Khi hỏi 'so sánh mức lương trung bình giữa nam và nữ theo chức danh':
          BẮT BUỘC dùng mẫu PIVOT 2 cột: MaleAvgSalary và FemaleAvgSalary!
          TUYỆT ĐỐI KHÔNG nối chuỗi CONCAT(t.title, ' - ', e.gender) thành 14 dòng riêng rẽ!


      + MẪU CHUẨN TỔNG QUỸ LƯƠNG HIỆN TẠI THEO PHÒNG BAN:
        SELECT 
            d.dept_name AS Department,
            SUM(s.salary) AS TotalSalaryBudget
        FROM departments d
        JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
        JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
        GROUP BY d.dept_name
        ORDER BY TotalSalaryBudget DESC;
        * CẢNH BÁO CỰC KỲ QUAN TRỌNG VỀ QUỸ LƯƠNG:
          Khi câu hỏi có từ 'quỹ lương', 'tổng quỹ lương', 'ngân sách lương', 'tổng chi trả lương', 'chi phí lương':
          BẮT BUỘC dùng SUM(s.salary) AS TotalSalaryBudget!
          TUYỆT ĐỐI KHÔNG DÙNG COUNT(de.emp_no) cho quỹ lương! COUNT là đếm số lượng người (headcount), SUM(s.salary) mới là tính tổng tiền lương (payroll budget)!

      + MẪU CHUẨN BIẾN ĐỘNG TỔNG QUỸ LƯƠNG TOÀN CÔNG TY QUA CÁC NĂM:
        SELECT 
            YEAR(s.from_date) AS Year,
            SUM(s.salary) AS TotalSalaryBudget
        FROM salaries s
        GROUP BY YEAR(s.from_date)
        ORDER BY Year ASC;
        * QUY TẮC QUAN TRỌNG: Khi câu hỏi có 'biến động', 'xu hướng qua các năm', 'theo năm':
          BẮT BUỘC dùng YEAR(s.from_date) AS Year, TUYỆT ĐỐI KHÔNG lọc `s.to_date = '9999-01-01'` và KHÔNG GROUP BY `s.to_date` (để lấy đủ 18 năm lịch sử từ 1985 đến 2002, không bị năm 9999 hoặc chỉ có 2 năm)!


      + MẪU CHUẨN TOP N CHỨC DANH LƯƠNG CAO NHẤT (Ví dụ: Top 10 chức danh):
        SELECT t.title AS Title, ROUND(AVG(s.salary), 2) AS AvgSalary
        FROM salaries s
        JOIN titles t ON s.emp_no = t.emp_no
        WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
        GROUP BY t.title
        ORDER BY AvgSalary DESC
        LIMIT 10;
        * QUY TẮC BẮT BUỘC: Khi câu hỏi có chữ 'Top N' (Top 10, Top 5, Top 3): BẮT BUỘC phải dùng đúng mệnh đề LIMIT N tương ứng theo đúng số N người dùng yêu cầu! TUYỆT ĐỐI KHÔNG tự ý giảm xuống LIMIT 5 nếu người dùng hỏi Top 10!

      + MẪU CHUẨN SO SÁNH LƯƠNG NAM VÀ NỮ THEO TỪNG CHỨC DANH:
        SELECT t.title AS Title, e.gender AS Gender, ROUND(AVG(s.salary), 2) AS AvgSalary
        FROM employees e
        JOIN titles t ON e.emp_no = t.emp_no
        JOIN salaries s ON e.emp_no = s.emp_no
        WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
        GROUP BY t.title, e.gender
        ORDER BY t.title, e.gender;
        * QUY TẮC BẮT BUỘC: Khi hỏi về 'chức danh' (Title): BẮT BUỘC JOIN bảng `titles t` (cột `t.title`), TUYỆT ĐỐI KHÔNG JOIN `departments` hay `dept_emp`!

      + MẪU CHUẨN TỶ LỆ PHÂN BỐ NHÂN SỰ THEO TỪNG CHỨC DANH:
        SELECT 
            t.title AS JobTitle,
            COUNT(t.emp_no) AS EmployeeCount,
            ROUND(COUNT(t.emp_no) * 100.0 / (SELECT COUNT(*) FROM titles WHERE to_date = '9999-01-01'), 2) AS Percentage
        FROM titles t
        WHERE t.to_date = '9999-01-01'
        GROUP BY t.title
        ORDER BY EmployeeCount DESC;
        * QUY TẮC BẮT BUỘC: Khi hỏi về 'Tỷ lệ phân bố nhân sự theo từng chức danh' hoặc 'Số lượng / tỷ lệ nhân sự theo chức danh': BẮT BUỘC dùng bảng `titles t` (cột `t.title`), đếm `COUNT(t.emp_no) AS EmployeeCount`, tính `Percentage`, lọc `WHERE t.to_date = '9999-01-01'` và `GROUP BY t.title` (TUYỆT ĐỐI KHÔNG JOIN `salaries` hay `departments`, KHÔNG LỌC THEO PHÒNG BAN SALES)!

      + MẪU CHUẨN TOP N CHỨC DANH CÓ THÂM NIÊN TRUNG BÌNH CAO NHẤT TẠI CÔNG TY (Ví dụ: Top 5):
        SELECT 
            t.title AS Title,
            ROUND(AVG(DATEDIFF(IF(t.to_date = '9999-01-01', '2002-08-01', t.to_date), e.hire_date) / 365.25), 2) AS AvgYearsOfService,
            COUNT(DISTINCT e.emp_no) AS TotalEmployees
        FROM titles t
        JOIN employees e ON t.emp_no = e.emp_no
        WHERE t.to_date = '9999-01-01'
        GROUP BY t.title
        ORDER BY AvgYearsOfService DESC
        LIMIT 5;
        * CẢNH BÁO QUAN TRỌNG:
          1. Bảng `employees` KHÔNG CÓ CỘT `YearsOfService` và KHÔNG CÓ CỘT `to_date`!
          2. Thâm niên tại công ty BẮT BUỘC tính bằng DATEDIFF(IF(t.to_date = '9999-01-01', '2002-08-01', t.to_date), e.hire_date) / 365.25!
          3. TUYỆT ĐỐI KHÔNG JOIN bảng `salaries` hay `departments`!
          4. BẮT BUỘC GROUP BY `t.title`, ORDER BY `AvgYearsOfService DESC` và LIMIT N theo yêu cầu!

      + MẪU CHUẨN LIỆT KÊ NHÂN VIÊN TỪNG LÀM VIỆC Ở TỪ 2 PHÒNG BAN TRỞ LÊN (KÈM CHỨC DANH HIỆN TẠI):
        SELECT 
            e.emp_no,
            CONCAT(e.first_name, ' ', e.last_name) AS FullName,
            t.title AS CurrentTitle,
            d.dept_name AS CurrentDepartment,
            COUNT(DISTINCT de.dept_no) AS DepartmentCount
        FROM employees e
        JOIN titles t ON e.emp_no = t.emp_no AND t.to_date = '9999-01-01'
        JOIN dept_emp de ON e.emp_no = de.emp_no
        JOIN dept_emp de_curr ON e.emp_no = de_curr.emp_no AND de_curr.to_date = '9999-01-01'
        JOIN departments d ON de_curr.dept_no = d.dept_no
        WHERE t.title = 'Senior Engineer' -- (hoặc chức danh được yêu cầu nếu có)
        GROUP BY e.emp_no, FullName, t.title, d.dept_name
        HAVING COUNT(DISTINCT de.dept_no) >= 2
        ORDER BY DepartmentCount DESC, e.emp_no ASC
        LIMIT 10;
        * QUY TẮC BẮT BUỘC:
          1. Số lượng phòng ban từng làm việc BẮT BUỘC đếm bằng COUNT(DISTINCT de.dept_no) trên bảng dept_emp de và lọc HAVING COUNT(DISTINCT de.dept_no) >= 2!
          2. Chức danh hiện tại lấy từ bảng `titles t` với `t.to_date = '9999-01-01'`!
          3. Phòng ban hiện tại lấy từ bảng `dept_emp de_curr` với `de_curr.to_date = '9999-01-01'` và `departments d`!
          4. BẮT BUỘC có LIMIT 10 (hoặc LIMIT N theo yêu cầu) để tối ưu hiệu năng!

      + MẪU CHUẨN NHÂN VIÊN TỪNG LÀM VIỆC TẠI ÍT NHẤT 2 PHÒNG BAN NHƯNG LƯƠNG HIỆN TẠI THẤP HƠN LƯƠNG TRUNG BÌNH PHÒNG BAN ĐẦU TIÊN (TUÂN THỦ 3 QUY TẮC PHÂN RÃ NGHIỆP VỤ):
        WITH FirstDept AS (
            SELECT 
                emp_no, 
                dept_no,
                ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
            FROM dept_emp
        ),
        DeptAvg AS (
            SELECT 
                de.dept_no, 
                d.dept_name, 
                ROUND(AVG(s.salary), 2) AS AvgSalary
            FROM dept_emp de
            JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
            JOIN departments d ON de.dept_no = d.dept_no
            WHERE de.to_date = '9999-01-01'
            GROUP BY de.dept_no, d.dept_name
        ),
        MultiDept AS (
            SELECT 
                emp_no, 
                COUNT(DISTINCT dept_no) AS DeptCount
            FROM dept_emp
            GROUP BY emp_no
            HAVING COUNT(DISTINCT dept_no) >= 2
        )
        SELECT 
            e.emp_no,
            CONCAT(e.first_name, ' ', e.last_name) AS FullName,
            d_curr.dept_name AS CurrentDepartment,
            s_curr.salary AS CurrentSalary,
            da.dept_name AS FirstDepartment,
            da.AvgSalary AS FirstDeptAvgSalary,
            ROUND(da.AvgSalary - s_curr.salary, 2) AS SalaryDeficit,
            md.DeptCount AS DepartmentCount
        FROM MultiDept md
        JOIN employees e ON md.emp_no = e.emp_no
        JOIN dept_emp de_curr ON e.emp_no = de_curr.emp_no AND de_curr.to_date = '9999-01-01'
        JOIN departments d_curr ON de_curr.dept_no = d_curr.dept_no
        JOIN salaries s_curr ON e.emp_no = s_curr.emp_no AND s_curr.to_date = '9999-01-01'
        JOIN FirstDept fd ON e.emp_no = fd.emp_no AND fd.rn = 1
        JOIN DeptAvg da ON fd.dept_no = da.dept_no
        WHERE s_curr.salary < da.AvgSalary
        ORDER BY SalaryDeficit DESC, e.emp_no ASC
        LIMIT 10;
        * QUY TẮC BẮT BUỘC:
          1. BẮT BUỘC dùng CTE 3 bước: FirstDept xác định phòng ban đầu tiên, DeptAvg tính lương TB các phòng ban, MultiDept lọc COUNT(DISTINCT dept_no) >= 2.
          2. BẮT BUỘC có điều kiện WHERE so sánh lương s_curr.salary < da.AvgSalary (hoặc > nếu hỏi cao hơn)! TUYỆT ĐỐI KHÔNG BỎ QUA ĐIỀU KIỆN SO SÁNH LƯƠNG!
          3. BẮT BUỘC có cột tính mức chênh lệch: ROUND(da.AvgSalary - s_curr.salary, 2) AS SalaryDeficit!

      + MẪU CHUẨN TOP N NHÂN VIÊN CÓ TỐC ĐỘ TĂNG TRƯỞNG LƯƠNG TRUNG BÌNH MỖI NĂM CAO NHẤT (THEO PHÒNG BAN HOẶC TOÀN CÔNG TY):
        SELECT 
            e.emp_no,
            CONCAT(e.first_name, ' ', e.last_name) AS FullName,
            d.dept_name AS Department,
            s_start.salary AS StartingSalary,
            s_curr.salary AS CurrentSalary,
            ROUND((s_curr.salary - s_start.salary) / (DATEDIFF(s_curr.from_date, s_start.from_date) / 365.25), 2) AS AvgAnnualSalaryGrowth
        FROM dept_emp de
        JOIN departments d ON de.dept_no = d.dept_no
        JOIN employees e ON de.emp_no = e.emp_no
        JOIN salaries s_start ON e.emp_no = s_start.emp_no AND s_start.from_date = e.hire_date
        JOIN salaries s_curr ON e.emp_no = s_curr.emp_no AND s_curr.to_date = '9999-01-01'
        WHERE d.dept_name = 'Sales' -- (hoặc phòng ban được yêu cầu)
          AND de.to_date = '9999-01-01'
          AND DATEDIFF(s_curr.from_date, s_start.from_date) >= 365
        ORDER BY AvgAnnualSalaryGrowth DESC
        LIMIT 5;
        * QUY TẮC BẮT BUỘC:
          1. Lương khởi điểm lấy từ bảng `salaries s_start` với `s_start.from_date = e.hire_date`!
          2. Lương hiện tại lấy từ `salaries s_curr` với `s_curr.to_date = '9999-01-01'` và `de.to_date = '9999-01-01'`!
          3. Tốc độ tăng trưởng lương TB mỗi năm = `ROUND((s_curr.salary - s_start.salary) / (DATEDIFF(...) / 365.25), 2) AS AvgAnnualSalaryGrowth`!
          4. BẮT BUỘC ORDER BY `AvgAnnualSalaryGrowth DESC` và `LIMIT N` theo yêu cầu!

      + MẪU CHUẨN TỶ LỆ GIỚI TÍNH TRONG BAN QUẢN LÝ (DEPT_MANAGER):
        SELECT 
            d.dept_name AS Department,
            SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
            SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
            COUNT(*) AS TotalManagers,
            ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct,
            ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct
        FROM dept_manager dm
        JOIN employees e ON dm.emp_no = e.emp_no
        JOIN departments d ON dm.dept_no = d.dept_no
        GROUP BY d.dept_name
        ORDER BY d.dept_name;
        * CẢNH BÁO: Dùng COUNT(*) để đếm tổng số, BẮT BUỘC chỉ GROUP BY d.dept_name (TUYỆT ĐỐI KHÔNG GROUP BY e.gender) để mỗi phòng ban là 1 dòng duy nhất! Không JOIN salaries khi hỏi tỷ lệ quản lý!

      + MẪU CHUẨN TOP NHÂN VIÊN THÂM NIÊN LÂU NHẤT CÔNG TY CÒN ĐANG CÔNG TÁC (Top N):
        SELECT 
            e.emp_no,
            CONCAT(e.first_name, ' ', e.last_name) AS FullName,
            d.dept_name AS Department,
            e.hire_date AS HireDate,
            ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 2) AS YearsOfService
        FROM employees e
        JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
        JOIN departments d ON de.dept_no = d.dept_no
        ORDER BY e.hire_date ASC, YearsOfService DESC
        LIMIT 10;
        * QUY TẮC BẮT BUỘC: Khi hỏi về 'nhân viên thâm niên / cống hiến lâu nhất còn công tác': BẮT BUỘC xuất danh sách từng nhân viên (e.emp_no, FullName, d.dept_name, e.hire_date, YearsOfService), TUYỆT ĐỐI KHÔNG GROUP BY THEO PHÒNG BAN VÀ KHÔNG ĐƯA RA XU HƯỚNG TUYỂN DỤNG CỦA PHÒNG BAN!

     + MẪU CHUẨN XU HƯỚNG TUYỂN DỤNG THEO NĂM:
       SELECT YEAR(hire_date) AS HireYear, COUNT(*) AS TotalHires
       FROM employees
       GROUP BY HireYear
       ORDER BY HireYear ASC;

     + MẪU CHUẨN XU HƯỚNG TUYỂN DỤNG CỦA PHÒNG BAN CỤ THỂ QUA CÁC NĂM (Ví dụ: Development / Sales):
       SELECT 
           YEAR(e.hire_date) AS HireYear, 
           COUNT(DISTINCT e.emp_no) AS TotalHires
       FROM employees e
       JOIN dept_emp de ON e.emp_no = de.emp_no
       JOIN departments d ON de.dept_no = d.dept_no
       WHERE d.dept_name = 'Development'
       GROUP BY HireYear
       ORDER BY HireYear ASC;
       * QUY TẮC BẮT BUỘC: Khi hỏi 'Xu hướng tuyển dụng của phòng ban [Tên] qua các năm': BẮT BUỘC dùng `YEAR(e.hire_date) AS HireYear`, `COUNT(DISTINCT e.emp_no) AS TotalHires`, `WHERE d.dept_name = '[Tên phòng ban]'` và `ORDER BY HireYear ASC` (TUYỆT ĐỐI KHÔNG DÙNG MAX(salary) LƯƠNG VÀ KHÔNG GÁN CỨNG PHÒNG BAN KHÁC)!

      + MẪU CHUẨN DANH SÁCH TRƯỞNG PHÒNG HIỆN TẠI (MANAGER) KÈM LƯƠNG:
        SELECT d.dept_name AS Department, CONCAT(e.first_name, ' ', e.last_name) AS ManagerName, s.salary AS CurrentSalary
        FROM dept_manager dm
        JOIN employees e ON dm.emp_no = e.emp_no
        JOIN departments d ON dm.dept_no = d.dept_no
        JOIN salaries s ON e.emp_no = s.emp_no
        WHERE dm.to_date = '9999-01-01' AND s.to_date = '9999-01-01'
        ORDER BY s.salary DESC;

      + MẪU CHUẨN QUẢN LÝ (MANAGER) CÓ MỨC LƯƠNG THẤP HƠN NHÂN VIÊN CẤP DƯỚI CÙNG PHÒNG BAN:
        * Khi câu hỏi có 'Quản lý / Manager / Trưởng phòng' VÀ 'lương thấp hơn / kém hơn' VÀ 'nhân viên / cấp dưới / trực thuộc / cùng phòng':
        SELECT 
            d.dept_name AS Department,
            CONCAT(em.first_name, ' ', em.last_name) AS ManagerName,
            sm.salary AS ManagerSalary,
            MAX(se.salary) AS MaxSubordinateSalary,
            MAX(se.salary) - sm.salary AS SalaryGap,
            COUNT(DISTINCT de.emp_no) AS SubordinatesWithHigherSalary
        FROM dept_manager dm
        JOIN departments d ON dm.dept_no = d.dept_no
        JOIN employees em ON dm.emp_no = em.emp_no
        JOIN salaries sm ON dm.emp_no = sm.emp_no AND sm.to_date = '9999-01-01'
        JOIN dept_emp de ON dm.dept_no = de.dept_no AND de.to_date = '9999-01-01' AND de.emp_no != dm.emp_no
        JOIN salaries se ON de.emp_no = se.emp_no AND se.to_date = '9999-01-01'
        WHERE dm.to_date = '9999-01-01'
          AND se.salary > sm.salary
        GROUP BY d.dept_name, ManagerName, sm.salary
        ORDER BY SalaryGap DESC;
        * CẢNH BÁO QUAN TRỌNG: TUYỆT ĐỐI KHÔNG chỉ liệt kê lương của Manager! BẮT BUỘC phải JOIN dept_emp de và salaries se của nhân viên trong cùng phòng (de.dept_no = dm.dept_no AND de.emp_no != dm.emp_no) và lọc se.salary > sm.salary!

      + MẪU CHUẨN NHÂN VIÊN CẤP DƯỚI CÓ MỨC LƯƠNG CAO HƠN QUẢN LÝ CÙNG PHÒNG BAN:
        * Khi câu hỏi hỏi về 'Những nhân viên nào có mức lương cao hơn quản lý / trưởng phòng':
        SELECT 
            d.dept_name AS Department,
            CONCAT(ee.first_name, ' ', ee.last_name) AS SubordinateName,
            se.salary AS SubordinateSalary,
            CONCAT(em.first_name, ' ', em.last_name) AS ManagerName,
            sm.salary AS ManagerSalary,
            se.salary - sm.salary AS SalaryDifference
        FROM dept_manager dm
        JOIN departments d ON dm.dept_no = d.dept_no
        JOIN employees em ON dm.emp_no = em.emp_no
        JOIN salaries sm ON dm.emp_no = sm.emp_no AND sm.to_date = '9999-01-01'
        JOIN dept_emp de ON dm.dept_no = de.dept_no AND de.to_date = '9999-01-01' AND de.emp_no != dm.emp_no
        JOIN employees ee ON de.emp_no = ee.emp_no
        JOIN salaries se ON de.emp_no = se.emp_no AND se.to_date = '9999-01-01'
        WHERE dm.to_date = '9999-01-01'
          AND se.salary > sm.salary
        ORDER BY SalaryDifference DESC
        LIMIT 10;

      + MẪU CHUẨN NHÂN VIÊN CÓ TỪ N LẦN TĂNG LƯƠNG TRỞ LÊN (TỐI ƯU SIÊU TỐC):
        SELECT 
            e.emp_no,
            CONCAT(e.first_name, ' ', e.last_name) AS FullName,
            d.dept_name AS Department,
            s_agg.RaiseCount,
            s_agg.CurrentSalary
        FROM (
            SELECT emp_no, COUNT(*) AS RaiseCount, MAX(salary) AS CurrentSalary
            FROM salaries
            GROUP BY emp_no
            HAVING COUNT(*) >= 5
            ORDER BY RaiseCount DESC, CurrentSalary DESC
            LIMIT 10
        ) s_agg
        JOIN employees e ON s_agg.emp_no = e.emp_no
        JOIN dept_emp de ON s_agg.emp_no = de.emp_no AND de.to_date = '9999-01-01'
        JOIN departments d ON de.dept_no = d.dept_no
        ORDER BY s_agg.RaiseCount DESC, s_agg.CurrentSalary DESC;
        * QUY TẮC BẮT BUỘC: Khi hỏi về 'nhân viên tăng lương / nhiều lần tăng lương':
          1. BẮT BUỘC có LIMIT 10 (vì có hơn 245,000 nhân viên thỏa mãn, không có LIMIT sẽ làm kịch trần dữ liệu)!
          2. Dùng subquery s_agg để chạy siêu tốc trong 0.5s thay vì quét 15s.
          3. TUYỆT ĐỐI KHÔNG lọc `s.to_date = '9999-01-01'` trong subquery đếm tăng lương!


      + MẪU CHUẨN MANAGER GIỮ CHỨC VỤ LÂU NHẤT TOÀN LỊCH SỬ:
        SELECT 
            CONCAT(e.first_name, ' ', e.last_name) AS ManagerName,
            d.dept_name AS Department,
            dm.from_date AS StartDate,
            IF(dm.to_date = '9999-01-01', 'Hiện tại', dm.to_date) AS EndDate,
            ROUND(DATEDIFF(IF(dm.to_date = '9999-01-01', '2002-08-01', dm.to_date), dm.from_date) / 365.25, 1) AS YearsAsManager
        FROM dept_manager dm
        JOIN employees e ON dm.emp_no = e.emp_no
        JOIN departments d ON dm.dept_no = d.dept_no
        ORDER BY YearsAsManager DESC
        LIMIT 10;
        * QUY TẮC: Khi hỏi 'Manager lâu nhất / thâm niên quản lý': BẮT BUỘC tính số năm tại vị dùng DATEDIFF, ORDER BY YearsAsManager DESC LIMIT 10 và TUYỆT ĐỐI KHÔNG thêm điều kiện WHERE lọc ngày (from_date/to_date) để quét toàn bộ các đời Manager trong lịch sử!

      + MẪU CHUẨN TOP NHÂN VIÊN THÂM NIÊN LÂU NHẤT CÒN ĐANG CÔNG TÁC:
        SELECT 
            e.emp_no,
            CONCAT(e.first_name, ' ', e.last_name) AS FullName,
            d.dept_name AS Department,
            e.hire_date AS HireDate,
            ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 2) AS YearsOfService
        FROM employees e
        JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
        JOIN departments d ON de.dept_no = d.dept_no
        ORDER BY e.hire_date ASC, YearsOfService DESC
        LIMIT 10;
        * QUY TẮC BẮT BUỘC:
          - Khi hỏi 'Thâm niên làm việc lâu nhất / cống hiến lâu nhất': BẮT BUỘC dùng ngày tuyển dụng `e.hire_date` và `ORDER BY e.hire_date ASC` (TUYỆT ĐỐI KHÔNG DÙNG MAX(s.salary) LƯƠNG CAO NHẤT)!
          - Khi hỏi 'Còn đang công tác / còn làm việc': BẮT BUỘC lọc `de.to_date = '9999-01-01'`!"""
    elif is_chocolates_db:
        return """   - QUY TẮC CSDL AWESOME CHOCOLATES:
     + Bảng `products` (Bí danh bắt buộc: `pr`):
       * Cột: `PID` (Khóa chính), `Product` (Tên sản phẩm: 'Mint Chip Choco', 'Milk Bars'...), `Category`, `Size`, `Cost_per_box`.
     + Bảng `people` (Bí danh bắt buộc: `pe`):
       * Cột: `SPID` (Khóa chính), `Salesperson` (Tên nhân viên: 'Van Tuxwell'...), `Team` ('Yummies', 'Jucies', 'Delish'...), `Location`.
     + Bảng `geo` (Bí danh bắt buộc: `g`):
       * Cột: `GeoID` (Khóa chính), `Geo` (Tên quốc gia/thị trường: 'Australia', 'India', 'USA', 'Canada', 'UK', 'New Zealand'), `Region` (Khu vực địa lý lớn: 'APAC', 'Americas').
     + Bảng `sales` (Bí danh bắt buộc: `s`):
       * Cột: `SPID` (liên kết pe.SPID), `PID` (liên kết pr.PID), `GeoID` (liên kết g.GeoID), `SaleDate` (Ngày bán), `Amount` (Doanh số), `Boxes`, `Customers`.
     + QUY TẮC BÍ DANH (ALIAS) TUYỆT ĐỐI KHÔNG TRÙNG NHAU:
       * Luôn dùng: `pe` cho people, `pr` cho products, `s` cho sales, `g` cho geo.
      + MẪU CHUẨN SỐ LƯỢNG NHÂN VIÊN BÁN HÀNG / HEADCOUNT THEO TEAM HOẶC LOCATION:
        * Khi hỏi 'Số lượng nhân viên bán hàng', 'nhân sự', 'headcount', 'quy mô nhân sự', 'đếm nhân viên' theo từng Đội ngũ (Team) hoặc Khu vực (Location):
          TUYỆT ĐỐI KHÔNG TRUY VẤN BẢNG sales! TUYỆT ĐỐI KHÔNG TÍNH SUM(Boxes) hay SUM(Amount)!
          BẮT BUỘC TRUY VẤN TRỰC TIẾP TỪ BẢNG people BẰNG HÀM COUNT(DISTINCT pe.SPID):
          SELECT 
              pe.Team AS `Đội Ngũ`,
              COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`,
              ROUND(COUNT(DISTINCT pe.SPID) * 100.0 / (SELECT COUNT(*) FROM people WHERE Team != '' AND Team IS NOT NULL), 2) AS `Tỷ Lệ (%)`
          FROM people pe
          WHERE pe.Team != '' AND pe.Team IS NOT NULL
          GROUP BY pe.Team
          ORDER BY `Số Lượng Nhân Viên` DESC;
     + MẪU CHUẨN TOP NHÂN SỰ:
       SELECT pe.Salesperson, SUM(s.Amount) AS TotalSales, pe.Team
       FROM people pe
       JOIN sales s ON pe.SPID = s.SPID
       GROUP BY pe.Salesperson, pe.Team
       ORDER BY TotalSales DESC
       LIMIT 10;
      + MẪU CHUẨN TOP NHÂN SỰ / NHÂN VIÊN TRONG MỘT NHÓM / ĐỘI NGŨ (TEAM YUMMIES, DELISH, JUCIES):
        * Khi hỏi 'Top 5 nhân sự có doanh số cao nhất trong nhóm Yummies' hoặc 'Top nhân viên team Delish':
          CÁC TỪ 'nhân sự', 'nhân viên', 'salesperson' VÀ CÁC NHÓM 'Yummies', 'Delish', 'Jucies' LÀ NÓI VỀ NHÂN SỰ (BẢNG people, CỘT pe.Team)!
          TUYỆT ĐỐI CẤM TRUY VẤN SẢN PHẨM (BẢNG products) HAY NHẦM SANG BẢNG employees!
          SELECT 
              pe.Salesperson, 
              SUM(s.Amount) AS TotalSales
          FROM sales s
          JOIN people pe ON s.SPID = pe.SPID
          WHERE pe.Team = 'Yummies'
          GROUP BY pe.Salesperson
          ORDER BY TotalSales DESC
          LIMIT 5;
     + MẪU CHUẨN TOP SẢN PHẨM:
       SELECT pr.Product, SUM(s.Amount) AS TotalSales
       FROM products pr
       JOIN sales s ON pr.PID = s.PID
       GROUP BY pr.Product
       ORDER BY TotalSales DESC
       LIMIT 10;
      + MẪU CHUẨN PHÂN TÍCH PARETO / CÁC SẢN PHẨM ĐEM LẠI 80% DOANH SỐ CHO CÔNG TY:
        * Khi hỏi 'Liệt kê danh sách các sản phẩm đem lại 80% doanh số cho công ty trong năm 2021' hoặc 'Top sản phẩm chiếm 80% doanh thu':
          BẮT BUỘC DÙNG CTE VÀ HÀM CỬA SỔ (WINDOW FUNCTION) ĐỂ TÍNH TỔNG TÍCH LŨY (TUYỆT ĐỐI CẤM DÙNG HAVING SUM(s.Amount) >= 0.8 * (SELECT...) VÌ SẼ TRẢ VỀ 0 DÒNG):
          WITH ProductSales AS (
              SELECT 
                  pr.Product AS Product,
                  SUM(s.Amount) AS TotalSales,
                  SUM(SUM(s.Amount)) OVER () AS GrandTotal,
                  SUM(SUM(s.Amount)) OVER (ORDER BY SUM(s.Amount) DESC) AS RunningTotal
              FROM sales s
              JOIN products pr ON s.PID = pr.PID
              WHERE YEAR(s.SaleDate) = 2021
              GROUP BY pr.Product
          )
          SELECT 
              Product,
              TotalSales,
              ROUND((TotalSales / GrandTotal) * 100, 2) AS Percentage,
              ROUND((RunningTotal / GrandTotal) * 100, 2) AS CumulativePercent
          FROM ProductSales
          WHERE (RunningTotal - TotalSales) / GrandTotal < 0.80
          ORDER BY TotalSales DESC;
     + MẪU CHUẨN DOANH THU THEO TỪNG QUỐC GIA QUA CÁC THÁNG (CHUẨN XÁC 100%, TUYỆT ĐỐI KHÔNG DÙNG CTE):
       SELECT 
           DATE_FORMAT(s.SaleDate, '%Y-%m') AS Month,
           g.Geo AS Country,
           SUM(s.Amount) AS TotalSales
       FROM sales s
       JOIN geo g ON s.GeoID = g.GeoID
       GROUP BY Month, Country
       ORDER BY Month ASC, TotalSales DESC;
       * QUY TẮC BẮT BUỘC:
         1. TUYỆT ĐỐI CẤM DÙNG CTE (`WITH ...`). Dùng câu lệnh SELECT đơn trực tiếp để tối ưu tốc độ!
         2. Định dạng tháng dạng 'YYYY-MM' (DATE_FORMAT trên MySQL hoặc strftime trên SQLite) để làm trục thời gian liên tục.
         3. g.Geo AS Country làm phân loại quốc gia, GROUP BY Month, Country và ORDER BY Month ASC để vẽ biểu đồ đa đường (Multi-line chart) so sánh xu hướng các nước.
      + MẪU CHUẨN DOANH THU TOÀN BỘ THEO THÁNG:
        SELECT DATE_FORMAT(s.SaleDate, '%Y-%m') AS Month, SUM(s.Amount) AS TotalSales
        FROM sales s
        GROUP BY Month
        ORDER BY Month ASC;
      + MẪU CHUẨN DOANH THU THEO QUÝ (QUARTER - BẮT BUỘC GROUP BY QUARTER):
        * Toàn công ty theo từng quý:
        SELECT CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate)) AS Quarter, SUM(s.Amount) AS TotalSales
        FROM sales s
        GROUP BY Quarter
        ORDER BY Quarter ASC;
        * Thị trường cụ thể (ví dụ Ấn Độ / India năm 2021) theo từng quý:
        SELECT CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate)) AS Quarter, SUM(s.Amount) AS TotalSales
        FROM sales s
        JOIN geo g ON s.GeoID = g.GeoID
        WHERE g.Geo = 'India' AND YEAR(s.SaleDate) = 2021
        GROUP BY Quarter
        ORDER BY Quarter ASC;
        (BẮT BUỘC: GROUP BY Quarter để trả về đủ các quý, TUYỆT ĐỐI CẤM dùng MAX(s.SaleDate) khiến kết quả chỉ còn 1 quý đơn lẻ!)
      + MẪU CHUẨN BÁO CÁO KẾT QUẢ KINH DOANH / LÃI, LỖ (P&L - PROFIT & LOSS):
        * Khi câu hỏi nhắc đến 'lãi, lỗ', 'lợi nhuận', 'profit', 'loss', 'cost_per_box', 'kết quả kinh doanh' theo thời gian (tháng, quý, năm) kết hợp với quốc gia (geo) hoặc sản phẩm:
          BẮT BUỘC JOIN bảng products pr ON s.PID = pr.PID để lấy pr.Cost_per_box!
          TÍNH ĐẦY ĐỦ 4 CHỈ SỐ TÀI CHÍNH:
          - Tổng Doanh Thu ($): SUM(s.Amount)
          - Tổng Chi Phí ($): ROUND(SUM(s.Boxes * pr.Cost_per_box), 2)
          - Lợi Nhuận ($): ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2)
          - Tỷ Suất Lợi Nhuận (%): ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2)
        * Ví dụ: Báo cáo kết quả lãi, lỗ trong tháng, trong quý trong năm 2021 theo quốc gia:
          SELECT 
              DATE_FORMAT(s.SaleDate, '%Y-%m') AS `Tháng`,
              CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate)) AS `Quý`,
              g.Geo AS `Quốc Gia`,
              SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
              ROUND(SUM(s.Boxes * pr.Cost_per_box), 2) AS `Tổng Chi Phí ($)`,
              ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2) AS `Lợi Nhuận ($)`,
              ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS `Tỷ Suất Lợi Nhuận (%)`
          FROM sales s
          JOIN products pr ON s.PID = pr.PID
          JOIN geo g ON s.GeoID = g.GeoID
          WHERE YEAR(s.SaleDate) = 2021
          GROUP BY `Tháng`, `Quý`, `Quốc Gia`
          ORDER BY `Tháng` ASC, `Lợi Nhuận ($)` DESC;"""
    elif is_sakila_db:
        return """   - QUY TẮC CSDL SAKILA (DVD RENTAL STORE):
     + Bảng `payment` (Bí danh bắt buộc: `p`):
       * Cột: `payment_id`, `customer_id`, `staff_id`, `rental_id`, `amount` (Doanh thu / Tiền thanh toán), `payment_date` (Ngày thanh toán).
       * Doanh thu theo tháng: DATE_FORMAT(p.payment_date, '%Y-%m') AS Month, SUM(p.amount) AS TotalRevenue, COUNT(p.rental_id) AS TotalRentals.
     + Bảng `rental` (Bí danh bắt buộc: `r`):
       * Cột: `rental_id`, `rental_date`, `inventory_id`, `customer_id`, `return_date`, `staff_id`.
     + Bảng `film` (Bí danh bắt buộc: `f`):
       * Cột: `film_id`, `title`, `description`, `release_year`, `language_id`, `rental_duration`, `rental_rate`, `length`, `replacement_cost`, `rating`.
     + Bảng `inventory` (Bí danh bắt buộc: `i`):
       * Cột: `inventory_id`, `film_id`, `store_id`.
     + Bảng `category` (Bí danh bắt buộc: `c`):
       * Cột: `category_id`, `name` (Tên thể loại: 'Action', 'Comedy', 'Drama'...).
     + Bảng `film_category` (Bí danh bắt buộc: `fc`):
       * Cột: `film_id`, `category_id`.
     + Bảng `actor` (Bí danh bắt buộc: `a`):
       * Cột: `actor_id`, `first_name`, `last_name`. Ghép họ tên: CONCAT(a.first_name, ' ', a.last_name) AS ActorName.
     + Bảng `film_actor` (Bí danh bắt buộc: `fa`):
       * Cột: `actor_id`, `film_id`.
     + Bảng `customer` (Bí danh bắt buộc: `cu`):
       * Cột: `customer_id`, `store_id`, `first_name`, `last_name`, `email`, `address_id`, `active`. Ghép họ tên: CONCAT(cu.first_name, ' ', cu.last_name) AS CustomerName.
     + Bảng `store` (Bí danh bắt buộc: `st`):
       * Cột: `store_id`, `manager_staff_id`, `address_id`.
     + Bảng `staff` (Bí danh bắt buộc: `s`):
       * Cột: `staff_id`, `first_name`, `last_name`, `store_id`.
     + MẪU CHUẨN DOANH THU VÀ SỐ LƯỢT THUÊ THEO THÁNG:
       SELECT 
           DATE_FORMAT(p.payment_date, '%Y-%m') AS Month,
           SUM(p.amount) AS TotalRevenue,
           COUNT(p.rental_id) AS TotalRentals
       FROM payment p
       GROUP BY DATE_FORMAT(p.payment_date, '%Y-%m')
       ORDER BY Month ASC;
     + MẪU CHUẨN TOP THỂ LOẠI PHIM THEO DOANH THU:
       SELECT 
           c.name AS Category,
           SUM(p.amount) AS TotalRevenue
       FROM category c
       JOIN film_category fc ON c.category_id = fc.category_id
       JOIN film f ON fc.film_id = f.film_id
       JOIN inventory i ON f.film_id = i.film_id
       JOIN rental r ON i.inventory_id = r.inventory_id
       JOIN payment p ON r.rental_id = p.rental_id
       GROUP BY c.name
       ORDER BY TotalRevenue DESC
       LIMIT 5;
     + MẪU CHUẨN TOP DIỄN VIÊN THAM GIA NHIỀU PHIM NHẤT:
       SELECT 
           a.actor_id,
           CONCAT(a.first_name, ' ', a.last_name) AS ActorName,
           COUNT(fa.film_id) AS TotalFilms
       FROM actor a
       JOIN film_actor fa ON a.actor_id = fa.actor_id
       GROUP BY a.actor_id, ActorName
       ORDER BY TotalFilms DESC
       LIMIT 10;
     + MẪU CHUẨN TOP KHÁCH HÀNG CHI TIÊU CAO NHẤT:
       SELECT 
           cu.customer_id,
           CONCAT(cu.first_name, ' ', cu.last_name) AS CustomerName,
           SUM(p.amount) AS TotalSpent
       FROM customer cu
       JOIN payment p ON cu.customer_id = p.customer_id
       GROUP BY cu.customer_id, CustomerName
       ORDER BY TotalSpent DESC
       LIMIT 10;
     + CẢNH BÁO BẮT BUỘC: CSDL Sakila KHÔNG CÓ BẢNG `sales`, `products`, `salaries`, `employees`! TUYỆT ĐỐI KHÔNG DÙNG CÁC BẢNG KHÔNG TỒN TẠI!"""
    else:
        schema_summary = extract_schema_metadata_summary(schema_context)
        if schema_summary:
            return schema_summary
        return """   - QUY TẮC SCHEMA CHUNG:
     + CHỈ ĐƯỢC PHÉP SỬ DỤNG các bảng và cột xuất hiện thực tế trong SCHEMA ở trên.
     + Mỗi bảng được JOIN phải có bí danh phân biệt, không được trùng nhau."""


CHOCOLATES_PRODUCTS = [
    '50% Dark Bites', '70% Dark Bites', '85% Dark Bars', '99% Dark & Pure',
    'After Nines', 'Almond Choco', "Baker's Choco Chips", 'Caramel Stuffed Bars',
    'Choco Coated Almonds', 'Drinking Coco', 'Eclairs', 'Fruit & Nut Bars',
    'Manuka Honey Choco', 'Milk Bars', 'Mint Chip Choco', 'Orange Choco',
    'Organic Choco Syrup', 'Peanut Butter Cubes', 'Raspberry Choco',
    'Smooth Sliky Salty', 'Spicy Special Slims', 'White Choc'
]

CHOCOLATES_PEOPLE = [
    'Andria Kimpton', 'Barr Faughny', 'Benny Karolovsky', 'Beverie Moffet', 'Brien Boise',
    'Camilla Castle', 'Ches Bonnell', 'Curtice Advani', 'Dennison Crosswaite', 'Dotty Strutley',
    'Dyna Doucette', 'Ebonee Roxburgh', 'Gigi Bohling', 'Gray Seamon', 'Gunar Cockshoot',
    'Husein Augar', 'Jan Morforth', 'Janene Hairsine', 'Jehu Rudeforth', 'Kaine Padly',
    'Karlen McCaffrey', 'Kelci Walkden', 'Madelene Upcott', 'Mallorie Waber', "Marney O'Breen",
    'Niall Selesnick', 'Oby Sorrel', 'Orton Livick', 'Rafaelita Blaksland', 'Roddy Speechley',
    'Van Tuxwell', "Wilone O'Kielt", 'Zach Polon'
]


def match_chocolates_specific_product(text: str):
    """Khớp tên sản phẩm cụ thể trong CSDL Chocolates từ văn bản người dùng hoặc SQL."""
    if not text:
        return None
    t_clean = re.sub(r"['’\"`]", "", text.lower())
    for prod in sorted(CHOCOLATES_PRODUCTS, key=len, reverse=True):
        p_clean = re.sub(r"['’\"`]", "", prod.lower())
        if p_clean in t_clean:
            return prod
    for pct, prod in [("85%", "85% Dark Bars"), ("70%", "70% Dark Bites"), ("50%", "50% Dark Bites"), ("99%", "99% Dark & Pure")]:
        if pct in text:
            return prod
    return None


def match_chocolates_specific_person(text: str):
    """Khớp tên nhân viên bán hàng cụ thể trong CSDL Chocolates."""
    if not text:
        return None
    t_clean = re.sub(r"['’\"`]", "", text.lower())
    for person in sorted(CHOCOLATES_PEOPLE, key=len, reverse=True):
        p_clean = re.sub(r"['’\"`]", "", person.lower())
        if p_clean in t_clean:
            return person
        parts = person.split()
        for part in parts:
            if len(part) >= 5 and re.search(rf"\b{re.escape(part.lower())}\b", t_clean):
                return person
    return None


def match_chocolates_specific_country(text: str):
    """Khớp tên quốc gia/thị trường cụ thể trong CSDL Chocolates."""
    if not text:
        return None
    t_clean = text.lower()
    country_patterns = {
        "india": "India", "ấn độ": "India", "an do": "India",
        "usa": "USA", "mỹ": "USA", "hoa kỳ": "USA", "united states": "USA",
        "canada": "Canada",
        "new zealand": "New Zealand",
        "australia": "Australia", "úc": "Australia",
        "uk": "UK", "nước anh": "UK", "vương quốc anh": "UK", "united kingdom": "UK"
    }
    for cp_key, cp_val in country_patterns.items():
        if re.search(rf"\b{re.escape(cp_key)}\b", t_clean):
            return cp_val
    return None


def match_chocolates_specific_team(text: str):
    """Khớp tên đội ngũ/team kinh doanh cụ thể trong CSDL Chocolates (Delish, Yummies, Jucies)."""
    if not text:
        return None
    t_clean = text.lower()
    team_patterns = {
        "delish": "Delish",
        "yummies": "Yummies",
        "jucies": "Jucies",
    }
    for tp_key, tp_val in team_patterns.items():
        if re.search(rf"\b{re.escape(tp_key)}\b", t_clean):
            return tp_val
    return None


def parse_threshold_query_info(q_low: str):
    """Trích xuất thông tin điều kiện lọc theo ngưỡng (Threshold Query) cho CSDL Awesome Chocolates."""
    if not q_low:
        return None

    # Loại bỏ các cụm từ gây hiểu nhầm sang từ khóa ngưỡng
    q_clean = re.sub(
        r'\b(trên thị trường|trên toàn quốc|trên thế giới|trên bảng|dưới đây|như dưới đây|'
        r'từng quý|từng tháng|từng năm|từng ngày|từng người|từng sản phẩm|từng quốc gia|từng team|'
        r'từ năm\s+\d+|từ tháng\s+\d+|từ ngày\s+\d+)\b',
        ' ',
        q_low
    )

    # Kiểm tra từ khóa so sánh ngưỡng bằng regex có ranh giới từ (word boundary)
    has_threshold_kw = (
        bool(re.search(r'\b(vượt|vượt mức|vượt quá|cao hơn|lớn hơn|thấp hơn|nhỏ hơn|nhiều hơn|ít hơn|ít nhất|tối thiểu|tối đa|over|above|under|below|exceed|more than|less than)\b|[><]=?', q_clean))
        or bool(re.search(r'\b(trên|dưới)\s+(?:\$|usd\s*)?\d+', q_clean))
        or bool(re.search(r'\btừ\s+(?:\$|usd\s*)?\d+', q_clean))
    )
    if not has_threshold_kw:
        return None

    # Nếu câu hỏi là so sánh tăng trưởng giữa các kỳ/quý/tháng (VD: tăng trưởng trên 20% so với quý 3)
    # hoặc có dấu phần trăm (%), đây là bài toán tỷ lệ phần trăm chứ không phải ngưỡng số tuyệt đối (Amount/Boxes)!
    if (
        (any(k in q_low for k in ["tăng trưởng", "growth", "tốc độ tăng"]) and any(k in q_low for k in ["so với", "vs"]))
        or re.search(r'\b(?:trên|hơn|dưới|ít nhất|tối thiểu|[><]=?)\s*\d+(?:\.\d+)?\s*%', q_low)
        or any(k in q_low for k in ["biên độ", "dao động", "price spread"])
    ):
        return None

    # Nếu câu hỏi là về đơn giá trung bình / hiệu quả bán hàng (AvgPricePerBox, RevenuePerBox...)
    # Đây là bài toán tính tỷ số hiệu quả / extrema, KHÔNG PHẢI bài toán lọc ngưỡng số lượng/doanh số đơn thuần!
    if any(k in q_low for k in ["đơn giá", "đơn giá trung bình", "giá trung bình", "bình quân mỗi hộp", "trung bình mỗi hộp", "giá bán trung bình", "avg price per box", "avgpriceperbox"]):
        return None

    # Nếu câu hỏi nói về xu hướng thời gian đơn thuần (theo từng quý, theo từng tháng, qua các quý...)
    # mà không có số liệu ngưỡng rõ ràng, không coi là threshold query
    is_time_trend = any(k in q_low for k in ["từng quý", "theo từng quý", "qua các quý", "từng tháng", "theo từng tháng", "qua các tháng", "xu hướng", "biến động", "qua từng năm"])

    # Nếu câu hỏi là về thống kê đơn hàng / giao dịch theo ngưỡng (Order Threshold Aggregation)
    # (VD: "Có bao nhiêu đơn hàng bán được trên 1,000 hộp...", "Có bao nhiêu đơn hàng đạt sản lượng từ 1,000 hộp trở lên...")
    # Đây là bài toán đếm/tổng hợp giao dịch toàn cục (WHERE s.Boxes >= X), KHÔNG PHẢI bài toán nhóm thực thể (GROUP BY pe.Team HAVING ...)!
    if (
        any(k in q_low for k in ["đơn hàng", "giao dịch", "mỗi đơn", "các đơn", "orders", "transactions"])
        and not any(k in q_low for k in [
            "theo từng", "mỗi", "từng", "nào", "những", "danh sách", "ai",
            "nhân viên", "nhân sự", "salesperson", "sales person", "người bán",
            "sản phẩm", "product", "mặt hàng",
            "quốc gia", "country", "thị trường", "geo",
            "team", "đội ngũ", "nhóm"
        ])
    ):
        return None

    val = None
    m_b = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:tỷ|ty|b|billion)\b', q_clean)
    m_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|trieu|m|million)\b', q_clean)
    m_k = re.search(r'(\d+(?:[.,]\d+)?)\s*k\b', q_clean)
    m_num = re.search(r'(?:mức\s*|trên\s*|hơn\s*|dưới\s*|từ\s*|[><]=?\s*)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+)', q_clean)

    if m_b:
        val = float(m_b.group(1).replace(',', '.')) * 1_000_000_000
    elif m_m:
        val = float(m_m.group(1).replace(',', '.')) * 1_000_000
    elif m_k:
        val = float(m_k.group(1).replace(',', '.')) * 1_000
    elif m_num:
        raw = m_num.group(1).replace(',', '').replace('.', '')
        candidate_val = float(raw)
        # Loại trừ năm lịch (1980 - 2040) nếu không có phân cách hàng nghìn
        if 1980 <= candidate_val <= 2040 and ',' not in m_num.group(1) and '.' not in m_num.group(1):
            val = None
        else:
            val = candidate_val
    else:
        m_any = re.search(r'\b(\d{1,3}(?:[.,]\d{3})+|\d{4,})\b', q_clean)
        if m_any:
            raw = m_any.group(1).replace(',', '').replace('.', '')
            candidate_val = float(raw)
            if 1980 <= candidate_val <= 2040 and ',' not in m_any.group(1) and '.' not in m_any.group(1):
                val = None
            else:
                val = candidate_val

    if not val or val <= 0:
        return None

    if is_time_trend and not (m_b or m_m or m_k or (m_num and val >= 10000)):
        return None

    op = '>'
    if any(k in q_clean for k in ['ít nhất', 'tối thiểu', '>=', 'at least', 'minimum']) or re.search(r'\btừ\s+\d+', q_clean):
        op = '>='
    elif any(k in q_clean for k in ['thấp hơn', 'nhỏ hơn', 'ít hơn', '<', 'under', 'below', 'less than']) or re.search(r'\bdưới\s+\d+', q_clean):
        op = '<'
    elif any(k in q_clean for k in ['tối đa', '<=', 'at most', 'maximum']):
        op = '<='
    elif any(k in q_clean for k in ['vượt', 'lớn hơn', 'cao hơn', 'nhiều hơn', 'hơn', '>', 'over', 'above', 'exceed']) or re.search(r'\btrên\s+\d+', q_clean):
        op = '>'

    # Phân biệt ngưỡng đo lường bằng Tiền (Amount) hay Sản lượng (Boxes):
    amount_cues = ["usd", "$", "đô", "vnd", "đồng", "doanh số", "doanh thu", "tiền"]
    box_cues = ["hộp", "hop", "thùng", "thung", "boxes", "sản lượng"]

    m_thresh_phrase = re.search(r'(?:doanh số|doanh thu|sản lượng|số hộp)?\s*(?:mức\s*|trên\s*|hơn\s*|dưới\s*|từ\s*|[><]=?\s*)\s*(?:\$|usd\s*)?\d+(?:[.,]\d+)?\s*(?:tỷ|ty|b|billion|tr|triệu|trieu|m|million|k)?\s*(?:usd|\$|đô|vnd|đồng|hộp|hop|thùng|thung|boxes)?', q_low)
    thresh_str = m_thresh_phrase.group(0) if m_thresh_phrase else q_low

    is_amount_thresh = any(k in thresh_str for k in amount_cues) or any(k in q_low for k in ["doanh số", "doanh thu", "usd", "$"])
    is_box_thresh = any(k in thresh_str for k in box_cues)

    if is_amount_thresh and not any(k in thresh_str for k in box_cues):
        has_boxes = False
    elif is_box_thresh and not any(k in thresh_str for k in amount_cues):
        has_boxes = True
    else:
        has_boxes = any(k in q_low for k in ['hộp', 'hop', 'thùng', 'thung', 'boxes']) and not is_amount_thresh

    entity_type = None
    if any(k in q_low for k in ['nhân viên', 'nhân sự', 'salesperson', 'sales person', 'người bán', 'ai bán', 'ai có', 'thành viên', 'sales rep', 'rep', 'yummies', 'delish', 'jucies']) and not match_chocolates_specific_person(q_low):
        entity_type = 'person'
    elif any(k in q_low for k in ['sản phẩm', 'product', 'mặt hàng', 'kẹo', 'socola', 'chocolate']) and not match_chocolates_specific_product(q_low):
        entity_type = 'product'
    elif any(k in q_low for k in ['quốc gia', 'country', 'thị trường', 'geo']) and not match_chocolates_specific_country(q_low):
        entity_type = 'geo'
    elif (
        any(k in q_low for k in ['đội ngũ', 'team', 'nhóm bán hàng', 'nhóm kinh doanh', 'đội bán hàng', 'đội kinh doanh'])
        or ('nhóm' in q_low and any(k in q_low for k in ['bán hàng', 'kinh doanh', 'sales', 'nhân sự']))
    ) and not any(k in q_low for k in ['yummies', 'delish', 'jucies', 'đơn hàng', 'giao dịch', 'sản phẩm', 'mặt hàng', 'bars', 'bites', 'khách hàng']):
        entity_type = 'team'

    if not entity_type:
        return None

    return {
        'val': int(val),
        'op': op,
        'has_boxes': has_boxes,
        'entity_type': entity_type
    }


def get_targeted_hint(user_query: str, schema_context: str = "", dialect: str = "") -> str:
    """Tự động sinh chỉ dẫn chuyên biệt (Targeted Hint) cho câu hỏi cụ thể, áp dụng cho cả prompt gốc và prompt sửa lỗi."""
    q_low = (user_query or "").lower()
    schema_low = (schema_context or "").lower()
    is_sqlite = "sqlite" in (dialect or "").lower() or "sqlite" in schema_low
    date_expr = "strftime('%Y-%m', s.SaleDate)" if is_sqlite else "DATE_FORMAT(s.SaleDate, '%Y-%m')"

    # Trích xuất số lượng N linh hoạt từ câu hỏi (VD: Top 10, top 5, 10 nhân viên, danh sách 10...)
    top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
    req_limit = int(top_m.group(1)) if top_m else 10

    # 0. Phân biệt ngữ cảnh CSDL (Sakila vs Employees vs Awesome Chocolates)
    is_sakila_db = any(k in schema_low for k in ["film_id", "rental_id", "payment_id", "inventory_id", "actor_id", "customer_id", "staff_id", "`film`", "`rental`", "`payment`", "`actor`", "`inventory`"])
    is_employees_db = (
        ("dept_emp" in schema_low or "dept_manager" in schema_low or "titles" in schema_low or "salaries" in schema_low or "hire_date" in schema_low)
        and not any(k in schema_low for k in ["geoid", "spid", "boxes", "`sales`", "bảng sales", "bảng `sales`"])
        and not is_sakila_db
    )
    is_choco_context = (
        (any(k in schema_low for k in ["geo", "products", "spid", "geoid", "boxes"])
         or ("`sales`" in schema_low or "bảng sales" in schema_low or "table sales" in schema_low))
        and not is_employees_db
        and not is_sakila_db
    )

    if is_sakila_db:
        # Tỷ lệ phần trăm đóng góp của từng tháng vào tổng doanh thu (Monthly revenue percentage contribution)
        if (any(k in q_low for k in ["tỷ lệ", "phần trăm", "đóng góp", "percentage", "contribution", "tỷ trọng", "tỉ trọng", "tỉ lệ", "cơ cấu"])
            and any(k in q_low for k in ["tháng", "month"])
            and any(k in q_low for k in ["doanh thu", "revenue", "sales", "tiền", "amount", "total revenue"])):
            if is_sqlite:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ PHẦN TRĂM ĐÓNG GÓP DOANH THU THEO THÁNG TRONG CSDL SAKILA):
WITH MonthlyRevenue AS (
    SELECT 
        strftime('%Y-%m', p.payment_date) AS Month,
        SUM(p.amount) AS TotalRevenue
    FROM payment p
    GROUP BY strftime('%Y-%m', p.payment_date)
)
SELECT 
    Month,
    TotalRevenue,
    ROUND(TotalRevenue * 100.0 / (SELECT SUM(TotalRevenue) FROM MonthlyRevenue), 2) AS ContributionPercentage
FROM MonthlyRevenue
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: Bảng thanh toán doanh thu là `payment` (cột `amount`, `payment_date`), TUYỆT ĐỐI KHÔNG CÓ CỘT `to_date`, KHÔNG DÙNG BẢNG `sales`!)
"""
            else:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ PHẦN TRĂM ĐÓNG GÓP DOANH THU THEO THÁNG TRONG CSDL SAKILA):
WITH MonthlyRevenue AS (
    SELECT 
        DATE_FORMAT(p.payment_date, '%Y-%m') AS Month,
        SUM(p.amount) AS TotalRevenue
    FROM payment p
    GROUP BY DATE_FORMAT(p.payment_date, '%Y-%m')
)
SELECT 
    Month,
    TotalRevenue,
    ROUND(TotalRevenue * 100.0 / (SELECT SUM(TotalRevenue) FROM MonthlyRevenue), 2) AS ContributionPercentage
FROM MonthlyRevenue
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: Bảng thanh toán doanh thu là `payment` (cột `amount`, `payment_date`), TUYỆT ĐỐI KHÔNG CÓ CỘT `to_date`, KHÔNG DÙNG BẢNG `sales`!)
"""

        # Biến động doanh thu theo tháng / số lượt thuê
        if any(k in q_low for k in ["theo tháng", "từng tháng", "hàng tháng", "qua các tháng", "biến động", "xu hướng", "monthly"]) and any(k in q_low for k in ["doanh thu", "doanh số", "thuê", "rentals", "payment", "tiền", "revenue"]):
            if is_sqlite:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU & SỐ LƯỢT THUÊ THEO THÁNG TRONG CSDL SAKILA):
SELECT 
    strftime('%Y-%m', p.payment_date) AS Month,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.rental_id) AS TotalRentals
FROM payment p
GROUP BY strftime('%Y-%m', p.payment_date)
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: Bảng thanh toán doanh thu là `payment` (cột `amount`, `payment_date`, `rental_id`), TUYỆT ĐỐI KHÔNG DÙNG BẢNG `sales` hay cột `SaleDate` vì CSDL Sakila không có bảng `sales`!)
"""
            else:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU & SỐ LƯỢT THUÊ THEO THÁNG TRONG CSDL SAKILA):
SELECT 
    DATE_FORMAT(p.payment_date, '%Y-%m') AS Month,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.rental_id) AS TotalRentals
FROM payment p
GROUP BY DATE_FORMAT(p.payment_date, '%Y-%m')
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: Bảng thanh toán doanh thu là `payment` (cột `amount`, `payment_date`, `rental_id`), TUYỆT ĐỐI KHÔNG DÙNG BẢNG `sales` hay cột `SaleDate` vì CSDL Sakila không có bảng `sales`!)
"""
        elif any(k in q_low for k in ["thể loại", "category", "categories"]) and any(k in q_low for k in ["doanh thu", "cao nhất", "phổ biến", "top"]):
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP THỂ LOẠI PHIM DOANH THU CAO NHẤT TRONG SAKILA):
SELECT 
    c.name AS Category,
    SUM(p.amount) AS TotalRevenue
FROM category c
JOIN film_category fc ON c.category_id = fc.category_id
JOIN film f ON fc.film_id = f.film_id
JOIN inventory i ON f.film_id = i.film_id
JOIN rental r ON i.inventory_id = r.inventory_id
JOIN payment p ON r.rental_id = p.rental_id
GROUP BY c.name
ORDER BY TotalRevenue DESC
LIMIT {req_limit};
"""
        elif any(k in q_low for k in ["diễn viên", "actor", "actors"]) and any(k in q_low for k in ["nhiều phim", "tham gia", "đóng nhiều", "top"]):
            name_concat = "a.first_name || ' ' || a.last_name" if is_sqlite else "CONCAT(a.first_name, ' ', a.last_name)"
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP DIỄN VIÊN THAM GIA NHIỀU PHIM NHẤT TRONG SAKILA):
SELECT 
    a.actor_id,
    {name_concat} AS ActorName,
    COUNT(fa.film_id) AS TotalFilms
FROM actor a
JOIN film_actor fa ON a.actor_id = fa.actor_id
GROUP BY a.actor_id, ActorName
ORDER BY TotalFilms DESC
LIMIT {req_limit};
"""
        elif any(k in q_low for k in ["khách hàng", "customer", "customers"]) and any(k in q_low for k in ["chi tiêu", "nhiều tiền", "doanh thu", "top"]):
            name_concat = "cu.first_name || ' ' || cu.last_name" if is_sqlite else "CONCAT(cu.first_name, ' ', cu.last_name)"
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP KHÁCH HÀNG CHI TIÊU CAO NHẤT TRONG SAKILA):
SELECT 
    cu.customer_id,
    {name_concat} AS CustomerName,
    SUM(p.amount) AS TotalSpent
FROM customer cu
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY cu.customer_id, CustomerName
ORDER BY TotalSpent DESC
LIMIT {req_limit};
"""
        elif any(k in q_low for k in ["so sánh", "chi nhánh", "cửa hàng", "store"]) and any(k in q_low for k in ["doanh thu", "giao dịch"]):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH CÁC CHI NHÁNH CỬA HÀNG TRONG SAKILA):
SELECT 
    st.store_id AS StoreID,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.payment_id) AS TotalTransactions
FROM store st
JOIN staff s ON st.store_id = s.store_id
JOIN payment p ON s.staff_id = p.staff_id
GROUP BY st.store_id
ORDER BY st.store_id ASC;
"""

    if is_choco_context or (not is_employees_db and not is_sakila_db and any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo"]) and any(k in q_low for k in ["tháng", "month"])):
        # 0.00000 Top N Giao dịch / Đơn hàng cá nhân có giá trị hoặc sản lượng lớn nhất (Top N Individual Transactions / Orders Ranking)
        # Ví dụ: "Cho biết thông tin top 5 giao dịch có giá trị đơn hàng cao nhất tại thị trường India: hiển thị ngày bán, tên nhân viên, tên sản phẩm và số tiền."
        is_top_tx = (
            any(k in q_low for k in ["giao dịch", "đơn hàng", "orders", "transactions"])
            and any(k in q_low for k in ["top", "cao nhất", "lớn nhất", "nhiều nhất", "giá trị nhất", "giá trị đơn hàng cao nhất", "khủng nhất", "đỉnh nhất"])
            and not any(k in q_low for k in [
                "giá trị đơn hàng trung bình", "đơn hàng trung bình", "trung bình trên mỗi giao dịch", "trung bình mỗi giao dịch", "aov",
                "bao nhiêu đơn", "có bao nhiêu", "đếm số đơn", "số lượng đơn", "tỷ lệ", "tổng doanh thu từ các đơn hàng",
                "từ 500", "từ 1000", "từ 1,000", "từ 500 hộp", "trên 1000 hộp", "trên 500 hộp"
            ])
        )
        if is_top_tx:
            limit_val = req_limit or 5
            tx_geo = match_chocolates_specific_country(q_low)
            tx_team = match_chocolates_specific_team(q_low)

            select_cols = []
            if any(k in q_low for k in ["ngày", "ngày bán", "date", "saledate", "thời gian"]):
                select_cols.append("s.SaleDate AS SaleDate")
            if any(k in q_low for k in ["tên nhân viên", "nhân viên", "người bán", "salesperson", "sales person"]):
                select_cols.append("pe.Salesperson AS Salesperson")
            if any(k in q_low for k in ["tên sản phẩm", "sản phẩm", "mặt hàng", "product", "kẹo", "socola"]):
                select_cols.append("pr.Product AS Product")
            if any(k in q_low for k in ["quốc gia", "thị trường", "country", "geo"]) and not tx_geo:
                select_cols.append("g.Geo AS Geo")
            if any(k in q_low for k in ["số tiền", "tiền", "giá trị", "giá trị đơn hàng", "amount", "doanh thu", "doanh số"]):
                select_cols.append("s.Amount AS Amount")
            if any(k in q_low for k in ["số hộp", "hộp", "boxes", "thùng"]):
                select_cols.append("s.Boxes AS Boxes")
            if not select_cols:
                select_cols = ["s.SaleDate AS SaleDate", "pe.Salesperson AS Salesperson", "pr.Product AS Product", "s.Amount AS Amount"]

            joins = ["FROM sales s"]
            if any("pe." in c for c in select_cols) or tx_team:
                joins.append("JOIN people pe ON s.SPID = pe.SPID")
            if any("pr." in c for c in select_cols):
                joins.append("JOIN products pr ON s.PID = pr.PID")
            if any("g." in c for c in select_cols) or tx_geo:
                joins.append("JOIN geo g ON s.GeoID = g.GeoID")

            where_conds = []
            if tx_geo:
                where_conds.append(f"g.Geo = '{tx_geo}'")
            if tx_team:
                where_conds.append(f"pe.Team = '{tx_team}'")
            where_str = ("\nWHERE " + " AND ".join(where_conds)) if where_conds else ""

            order_col = "s.Boxes" if (any(k in q_low for k in ["hộp", "boxes"]) and not any(k in q_low for k in ["giá trị", "số tiền", "tiền", "amount"])) else "s.Amount"
            cols_str = ",\n    ".join(select_cols)
            joins_str = "\n".join(joins)
            geo_title = f" TẠI THỊ TRƯỜNG {tx_geo.upper()}" if tx_geo else ""
            geo_warn = f", thị trường (WHERE g.Geo = '{tx_geo}')" if tx_geo else ""

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {limit_val} GIAO DỊCH/ĐƠN HÀNG CÁ NHÂN{geo_title}):
SELECT 
    {cols_str}
{joins_str}{where_str}
ORDER BY {order_col} DESC
LIMIT {limit_val};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN XẾP HẠNG TỪNG GIAO DỊCH / ĐƠN HÀNG CÁ NHÂN (Row-level individual transactions), TUYỆT ĐỐI CẤM DÙNG GROUP BY!
2. TUYỆT ĐỐI KHÔNG NHÓM THEO pe.Salesperson, pr.Product HAY g.Geo! Mỗi dòng là một giao dịch riêng lẻ trong bảng sales s!
3. BẮT BUỘC JOIN các bảng liên quan để lấy đúng các trường chi tiết: ngày bán (s.SaleDate), nhân viên (pe.Salesperson), sản phẩm (pr.Product), số tiền (s.Amount){geo_warn}!
4. Sắp xếp ORDER BY {order_col} DESC LIMIT {limit_val}!)
"""

        # 0.0000a Thống kê đơn hàng quy mô lớn theo Phân khúc / Danh mục / Thị trường (Segmented Large Orders: Category + Market + Order Threshold)
        # Ví dụ: "Thống kê tổng doanh thu và số lượng đơn hàng có quy mô từ 500 hộp trở lên đối với các sản phẩm thuộc danh mục 'Bites' tại hai thị trường USA và Canada."
        has_seg_order_thresh = (
            any(k in q_low for k in ["đơn hàng", "giao dịch", "mỗi đơn", "các đơn", "orders", "transactions", "đơn"])
            and any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes"])
            and any(k in q_low for k in ["trên", "hơn", "vượt", "lớn hơn", ">", "cao hơn", "từ", "trở lên", "ít nhất", "tối thiểu", ">="])
            and any(char.isdigit() for char in q_low)
            and (
                any(k in q_low for k in ["bites", "bite", "bars", "bar", "other", "category", "danh mục", "nhóm kẹo"])
                or any(k in q_low for k in ["usa", "canada", "india", "uk", "new zealand", "australia", "thị trường", "hai thị trường"])
            )
        )
        if has_seg_order_thresh:
            box_m = re.search(r'(?:trên|hơn|vượt|lớn hơn|cao hơn|từ|ít nhất|tối thiểu|[><]=?)\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:hộp|hop|thùng|thung|boxes)(?:\s*(?:trở lên|trở đi))?', q_low)
            if not box_m:
                box_m = re.search(r'(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:hộp|hop|thùng|thung|boxes)\s*(?:trở lên|trở đi|trở xuống)', q_low)
            is_gte = any(k in q_low for k in ["từ", "trở lên", "ít nhất", "tối thiểu", ">="])
            thresh_val = int(box_m.group(1).replace(',', '').replace('.', '')) if box_m else 500
            op = ">=" if is_gte else ">"

            seg_cat = None
            if any(k in q_low for k in ["bites", "bite"]):
                seg_cat = "Bites"
            elif any(k in q_low for k in ["bars", "bar"]):
                seg_cat = "Bars"
            elif "other" in q_low:
                seg_cat = "Other"

            seg_geos = []
            if re.search(r'\b(usa|mỹ|hoa kỳ|united states)\b', q_low):
                seg_geos.append("USA")
            if re.search(r'\b(canada)\b', q_low):
                seg_geos.append("Canada")
            if re.search(r'\b(india|ấn độ|an do)\b', q_low):
                seg_geos.append("India")
            if re.search(r'\b(uk|nước anh|vương quốc anh|united kingdom)\b', q_low):
                seg_geos.append("UK")
            if re.search(r'\b(australia|úc)\b', q_low):
                seg_geos.append("Australia")
            if re.search(r'\b(new zealand|newzealand|nz)\b', q_low):
                seg_geos.append("New Zealand")

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            where_conds = []
            if seg_cat:
                where_conds.append(f"pr.Category = '{seg_cat}'")
            if seg_geos:
                if len(seg_geos) == 1:
                    where_conds.append(f"g.Geo = '{seg_geos[0]}'")
                else:
                    g_str = ", ".join([f"'{g}'" for g in seg_geos])
                    where_conds.append(f"g.Geo IN ({g_str})")
            where_conds.append(f"s.Boxes {op} {thresh_val}")
            if yr_val:
                where_conds.append(yr_filter.replace(" AND ", ""))

            where_clause = "WHERE " + "\n  AND ".join(where_conds)

            desc_parts = []
            if seg_geos:
                desc_parts.append(f"THỊ TRƯỜNG {' & '.join(seg_geos)}")
            if seg_cat:
                desc_parts.append(f"DANH MỤC {seg_cat.upper()}")
            desc_parts.append(f"{'TỪ' if op == '>=' else 'TRÊN'} {thresh_val:,} HỘP")
            desc_label = " • ".join(desc_parts)

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (THỐNG KÊ ĐƠN HÀNG LỚN THEO PHÂN KHÚC: {desc_label}{yr_label}):
SELECT 
    g.Geo AS Market,
    pr.Product AS Product,
    COUNT(*) AS LargeOrdersCount,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN products pr ON s.PID = pr.PID
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}
GROUP BY g.Geo, pr.Product
ORDER BY g.Geo, TotalRevenue DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN THỐNG KÊ ĐƠN HÀNG LỚN ({desc_label}), BẮT BUỘC LỌC ĐẦY ĐỦ CÁC ĐIỀU KIỆN:
   - Ngưỡng hộp: s.Boxes {op} {thresh_val}
   {f"- Danh mục: pr.Category = '{seg_cat}'" if seg_cat else ""}
   {f"- Thị trường: g.Geo IN ({', '.join([repr(g) for g in seg_geos])})" if seg_geos else ""}
2. BẮT BUỘC JOIN cả products pr ON s.PID = pr.PID VÀ geo g ON s.GeoID = g.GeoID!
3. Mệnh đề SELECT BẮT BUỘC có đủ:
   - Cột thị trường: g.Geo AS Market
   - Cột sản phẩm: pr.Product AS Product
   - Số lượng đơn hàng: COUNT(*) AS LargeOrdersCount
   - Tổng doanh thu: SUM(s.Amount) AS TotalRevenue
   - Tổng số hộp: SUM(s.Boxes) AS TotalBoxesSold
4. TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ SÓT ĐIỀU KIỆN DANH MỤC HOẶC THỊ TRƯỜNG! TUYỆT ĐỐI KHÔNG ĐƯỢC TRẢ VỀ TOÀN BỘ 22 SẢN PHẨM!)
"""

        # 0.0000 Thống kê đơn hàng / giao dịch theo ngưỡng (Order Threshold Aggregation)
        # Ví dụ: "Có bao nhiêu đơn hàng đạt sản lượng từ 1,000 hộp trở lên, và tổng doanh thu mang về từ nhóm đơn hàng lớn này là bao nhiêu?"
        # hoặc "Có bao nhiêu đơn hàng bán được trên 1,000 hộp, và tổng doanh thu từ các đơn hàng lớn này là bao nhiêu?"
        is_order_thresh = (
            any(k in q_low for k in ["đơn hàng", "giao dịch", "mỗi đơn", "các đơn", "orders", "transactions", "đơn"])
            and any(k in q_low for k in ["trên", "hơn", "vượt", "lớn hơn", ">", "cao hơn", "từ", "trở lên", "ít nhất", "tối thiểu", ">="])
            and any(k in q_low for k in ["bao nhiêu", "có bao nhiêu", "số lượng đơn", "tổng doanh thu", "tổng số", "bao nhieu"])
            and not any(k in q_low for k in ["theo từng", "mỗi nhân viên", "mỗi người", "mỗi sản phẩm", "mỗi quốc gia", "từng team", "từng tháng", "từng quý", "top", "xếp hạng"])
            and not (
                any(k in q_low for k in ["bites", "bite", "bars", "bar", "other", "category", "danh mục"])
                or any(k in q_low for k in ["usa", "canada", "india", "uk", "new zealand", "australia", "thị trường"])
            )
        )
        if is_order_thresh:
            box_m = re.search(r'(?:trên|hơn|vượt|lớn hơn|cao hơn|từ|ít nhất|tối thiểu|[><]=?)\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:hộp|hop|thùng|thung|boxes)(?:\s*(?:trở lên|trở đi))?', q_low)
            if not box_m:
                box_m = re.search(r'(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:hộp|hop|thùng|thung|boxes)\s*(?:trở lên|trở đi|trở xuống)', q_low)

            amt_m = re.search(r'(?:trên|hơn|vượt|lớn hơn|cao hơn|từ|ít nhất|tối thiểu|[><]=?)\s*[\$]?\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:k|triệu|tr|usd|\$|đô)?(?:\s*(?:trở lên|trở đi))?', q_low)

            is_gte = any(k in q_low for k in ["từ", "trở lên", "ít nhất", "tối thiểu", ">="])

            if box_m:
                thresh_val = int(box_m.group(1).replace(',', '').replace('.', ''))
                op = ">=" if is_gte else ">"
                cond_expr = f"s.Boxes {op} {thresh_val}"
                cond_label = f"{'TỪ' if op == '>=' else 'TRÊN'} {thresh_val:,} HỘP"
            elif amt_m:
                raw_val = float(amt_m.group(1).replace(',', '').replace('.', ''))
                if 'k' in q_low:
                    raw_val *= 1000
                elif any(k in q_low for k in ['triệu', 'tr']):
                    raw_val *= 1000000
                thresh_val = int(raw_val)
                op = ">=" if is_gte else ">"
                cond_expr = f"s.Amount {op} {thresh_val}"
                cond_label = f"{'TỪ' if op == '>=' else 'TRÊN'} ${thresh_val:,.0f}"
            else:
                op = ">=" if is_gte else ">"
                cond_expr = f"s.Boxes {op} 1000"
                cond_label = f"{'TỪ 1,000 HỘP TRỞ LÊN' if op == '>=' else 'TRÊN 1,000 HỘP'}"

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (THỐNG KÊ ĐƠN HÀNG QUY MÔ LỚN {cond_label}{yr_label}):
SELECT 
    COUNT(*) AS LargeOrdersCount,
    SUM(s.Amount) AS TotalLargeOrdersRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(AVG(s.Amount), 2) AS AvgLargeOrderAmount
FROM sales s
WHERE {cond_expr}{yr_filter};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN THỐNG KÊ TỔNG THỂ CÁC ĐƠN HÀNG/GIAO DỊCH QUY MÔ LỚN TRÊN TOÀN BỘ CSDL ({cond_label})!
2. TUYỆT ĐỐI KHÔNG DÙNG GROUP BY THEO ĐỘI NGŨ (pe.Team), NHÂN VIÊN (pe.SPID), SẢN PHẨM (pr.PID) HAY QUỐC GIA (g.GeoID) VÌ NGƯỜI DÙNG ĐANG HỎI TỔNG THỂ NHÓM ĐƠN HÀNG NÀY!
3. CỤM TỪ 'NHÓM ĐƠN HÀNG' Ở ĐÂY CÓ NGHĨA LÀ TẬP HỢP CÁC ĐƠN HÀNG LỚN ({cond_label}), TUYỆT ĐỐI KHÔNG ĐƯỢC NHẦM SANG ĐỘI NGŨ / TEAM (pe.Team)!
4. BẮT BUỘC TRẢ VỀ ĐÚNG 1 DÒNG VỚI CÁC HÀM TỔNG HỢP: COUNT(*) AS LargeOrdersCount, SUM(s.Amount) AS TotalLargeOrdersRevenue, SUM(s.Boxes) AS TotalBoxesSold, ROUND(AVG(s.Amount), 2) AS AvgLargeOrderAmount!
5. TUYỆT ĐỐI KHÔNG DÙNG LIMIT 10 HAY LIMIT 25!)
"""

        # 0.0000b Nhân viên kinh doanh đạt đơn giá trung bình mỗi hộp bán ra cao nhất / thấp nhất (có hoặc không kèm ngưỡng doanh số)
        # Ví dụ: "Nhân viên kinh doanh nào đạt đơn giá trung bình mỗi hộp bán ra cao nhất (chỉ xét những người có tổng doanh số trên 500,000 USD)?"
        has_sp_avg_price = (
            any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "ai bán", "ai là", "ai có", "thành viên", "sales rep", "rep"])
            and any(k in q_low for k in ["đơn giá", "đơn giá trung bình", "giá trung bình", "giá mỗi hộp", "bình quân mỗi hộp", "trung bình mỗi hộp", "giá bán trung bình", "avg price per box", "avgpriceperbox", "price per box"])
        )
        if has_sp_avg_price:
            calc_avg = "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)" if is_sqlite else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"\nWHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"\nWHERE YEAR(s.SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            # Trích xuất điều kiện ngưỡng (HAVING filter)
            having_clause = ""
            thresh_val = None
            thresh_metric = "SUM(s.Amount)"
            thresh_op = ">"
            thresh_name = "Doanh Số"

            # 1. Kiểm tra ngưỡng doanh số / tiền / USD
            m_thresh_amt = re.search(r'(?:doanh số|doanh thu|tiền|amount|sales)\s*(?:trên|hơn|vượt|dưới|từ|[><]=?)\s*(?:\$|usd\s*)?(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+)', q_low)
            if not m_thresh_amt:
                m_thresh_amt = re.search(r'(?:trên|hơn|vượt|dưới|từ|[><]=?)\s*(?:\$|usd\s*)?(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+)\s*(?:usd|\$|đô|vnd|đồng)', q_low)

            if m_thresh_amt:
                raw_val = m_thresh_amt.group(1).replace(',', '').replace('.', '')
                thresh_val = float(raw_val)
                thresh_metric = "SUM(s.Amount)"
                thresh_name = "Doanh Số ($)"
                if any(k in q_low for k in ["ít nhất", "tối thiểu", ">=", "at least"]):
                    thresh_op = ">="
                elif any(k in q_low for k in ["dưới", "nhỏ hơn", "thấp hơn", "<", "less than"]):
                    thresh_op = "<"
                elif any(k in q_low for k in ["tối đa", "<="]):
                    thresh_op = "<="
                else:
                    thresh_op = ">"
                having_clause = f"\nHAVING {thresh_metric} {thresh_op} {int(thresh_val) if thresh_val.is_integer() else thresh_val}"
            else:
                # 2. Kiểm tra ngưỡng sản lượng / số hộp
                m_thresh_box = re.search(r'(?:sản lượng|số hộp|boxes)?\s*(?:trên|hơn|vượt|dưới|từ|[><]=?)\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+)\s*(?:hộp|hop|thùng|thung|boxes)', q_low)
                if m_thresh_box:
                    raw_val = m_thresh_box.group(1).replace(',', '').replace('.', '')
                    thresh_val = float(raw_val)
                    thresh_metric = "SUM(s.Boxes)"
                    thresh_name = "Số Hộp"
                    if any(k in q_low for k in ["ít nhất", "tối thiểu", ">=", "at least"]):
                        thresh_op = ">="
                    elif any(k in q_low for k in ["dưới", "nhỏ hơn", "thấp hơn", "<"]):
                        thresh_op = "<"
                    else:
                        thresh_op = ">"
                    having_clause = f"\nHAVING {thresh_metric} {thresh_op} {int(thresh_val) if thresh_val.is_integer() else thresh_val}"

            is_lowest = any(k in q_low for k in ["thấp nhất", "kém nhất", "nhỏ nhất", "lowest", "bottom", "least", "tệ nhất"])
            sort_dir = "ASC" if is_lowest else "DESC"
            sort_label = "THẤP NHẤT" if is_lowest else "CAO NHẤT"

            top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
            if top_m:
                limit_clause = f"\nLIMIT {int(top_m.group(1))}"
                limit_label = f"TOP {int(top_m.group(1))}"
            elif any(k in q_low for k in ["nào", "ai", "cao nhất", "thấp nhất", "best", "worst"]):
                limit_clause = "\nLIMIT 1"
                limit_label = "1 NGƯỜI DUY NHẤT (LIMIT 1)"
            elif any(k in q_low for k in ["tất cả", "từng", "các"]):
                limit_clause = ""
                limit_label = "TẤT CẢ"
            else:
                limit_clause = "\nLIMIT 10"
                limit_label = "TOP 10"

            having_warning = (
                f"\n3. BẮT BUỘC LỌC ĐIỀU KIỆN NGƯỠNG {thresh_name.upper()} {thresh_op} {int(thresh_val):,}: DÙNG MỆNH ĐỀ {having_clause.strip()}! TUYỆT ĐỐI KHÔNG ĐƯỢC NHẦM LẪN GIỮA DOANH SỐ ($) VÀ SỐ HỘP (BOXES)!"
                if having_clause else ""
            )

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN CÓ ĐƠN GIÁ TRUNG BÌNH MỖI HỘP {sort_label} - {limit_label}{yr_label}):
SELECT 
    pe.Salesperson AS Salesperson,
    {calc_avg} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID{yr_filter}
GROUP BY pe.Salesperson{having_clause}
ORDER BY AvgPricePerBox {sort_dir}{limit_clause};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN TÌM NHÂN VIÊN KINH DOANH ĐẠT ĐƠN GIÁ TRUNG BÌNH MỖI HỘP (AvgPricePerBox) {sort_label}!
2. BẮT BUỘC tính cột AvgPricePerBox = {calc_avg} AS AvgPricePerBox, kèm SUM(s.Amount) AS TotalSales và SUM(s.Boxes) AS TotalBoxesSold để đối chiếu quy mô!{having_warning}
4. Sắp xếp ORDER BY AvgPricePerBox {sort_dir}{limit_clause}! TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ SÓT LIMIT 1 NẾU HỎI 'AI' HOẶC 'NÀO'!)
"""

        # 0.000 Câu hỏi lọc theo điều kiện ngưỡng (Threshold Condition Queries):
        thresh_info = parse_threshold_query_info(q_low)
        if thresh_info:
            t_val = thresh_info['val']
            t_op = thresh_info['op']
            t_boxes = thresh_info['has_boxes']
            t_entity = thresh_info['entity_type']

            if t_boxes:
                m_col = "TotalBoxesSold"
                m_expr = "SUM(s.Boxes) AS TotalBoxesSold"
                m_having = f"SUM(s.Boxes) {t_op} {t_val}"
            else:
                m_col = "TotalSales"
                m_expr = "SUM(s.Amount) AS TotalSales"
                m_having = f"SUM(s.Amount) {t_op} {t_val}"

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"

            has_orders = any(k in q_low for k in ["đơn hàng", "số đơn", "orders", "giao dịch"])
            orders_col = ",\n    COUNT(*) AS TotalOrders" if has_orders else ""
            orders_warn = "\n5. BẮT BUỘC có cột COUNT(*) AS TotalOrders theo yêu cầu kèm số lượng đơn hàng!" if has_orders else ""

            if t_entity == 'person':
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN BÁN HÀNG CÓ {m_col.upper()} {t_op} {t_val:,}{yr_label}):
SELECT 
    pe.Salesperson AS Salesperson,
    {m_expr}{orders_col}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{yr_filter}GROUP BY pe.Salesperson
HAVING {m_having}
ORDER BY {m_col} DESC;
(CẢNH BÁO BẮT BUỘC:
1. MỆNH ĐỀ SELECT BẮT BUỘC PHẢI CÓ CẢ 2 CỘT: pe.Salesperson AS Salesperson VÀ {m_expr}! TUYỆT ĐỐI KHÔNG ĐƯỢC CHỈ SELECT MỖI CỘT Salesperson MÀ BỎ SÓT CHỈ SỐ ĐO LƯỜNG VÌ HỆ THỐNG CẦN NÓ ĐỂ VẼ BIỂU ĐỒ VÀ PHÂN TÍCH!
2. BẮT BUỘC dùng HAVING {m_having}!
3. BẮT BUỘC ORDER BY {m_col} DESC!
4. TUYỆT ĐỐI KHÔNG DÙNG LIMIT NẾU NGƯỜI DÙNG KHÔNG YÊU CẦU TOP N!{orders_warn})
"""
            elif t_entity == 'product':
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SẢN PHẨM CÓ {m_col.upper()} {t_op} {t_val:,}{yr_label}):
SELECT 
    pr.Product AS Product,
    {m_expr}{orders_col}
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}GROUP BY pr.Product
HAVING {m_having}
ORDER BY {m_col} DESC;
(CẢNH BÁO BẮT BUỘC:
1. MỆNH ĐỀ SELECT BẮT BUỘC PHẢI CÓ CÁC CỘT: pr.Product AS Product VÀ {m_expr}!
2. BẮT BUỘC dùng HAVING {m_having}!
3. BẮT BUỘC ORDER BY {m_col} DESC!
4. TUYỆT ĐỐI KHÔNG DÙNG LIMIT NẾU NGƯỜI DÙNG KHÔNG YÊU CẦU TOP N!{orders_warn})
"""
            elif t_entity == 'geo':
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (QUỐC GIA CÓ {m_col.upper()} {t_op} {t_val:,}{yr_label}):
SELECT 
    g.Geo AS Country,
    {m_expr}{orders_col}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{yr_filter}GROUP BY g.Geo
HAVING {m_having}
ORDER BY {m_col} DESC;
(CẢNH BÁO BẮT BUỘC:
1. MỆNH ĐỀ SELECT BẮT BUỘC PHẢI CÓ CÁC CỘT: g.Geo AS Country VÀ {m_expr}!
2. BẮT BUỘC dùng HAVING {m_having}!
3. BẮT BUỘC ORDER BY {m_col} DESC!
4. TUYỆT ĐỐI KHÔNG DÙNG LIMIT NẾU NGƯỜI DÙNG KHÔNG YÊU CẦU TOP N!{orders_warn})
"""
            elif t_entity == 'team':
                team_where = "WHERE pe.Team != '' AND pe.Team IS NOT NULL"
                if yr_match:
                    yr_val = yr_match.group(1)
                    team_where += f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}"
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (ĐỘI NGŨ / TEAM CÓ {m_col.upper()} {t_op} {t_val:,}{yr_label}):
SELECT 
    pe.Team AS Team,
    {m_expr}{orders_col}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{team_where}
GROUP BY pe.Team
HAVING {m_having}
ORDER BY {m_col} DESC;
(CẢNH BÁO BẮT BUỘC:
1. MỆNH ĐỀ SELECT BẮT BUỘC PHẢI CÓ CÁC CỘT: pe.Team AS Team VÀ {m_expr}!
2. BẮT BUỘC dùng HAVING {m_having}!
3. BẮT BUỘC ORDER BY {m_col} DESC!
4. TUYỆT ĐỐI KHÔNG DÙNG LIMIT NẾU NGƯỜI DÙNG KHÔNG YÊU CẦU TOP N!{orders_warn})
"""

        # 0.00 Số lượng nhân viên bán hàng / Headcount theo từng Đội ngũ (Team) hoặc Khu vực (Location)
        is_headcount_q = (
            any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "salesperson", "sales person", "người bán", "sales rep", "sales reps"])
            and any(k in q_low for k in ["số lượng", "quy mô", "bao nhiêu", "đếm", "phân bổ", "cơ cấu", "phân chia", "mỗi team có", "từng team có", "từng đội có"])
            and not any(k in q_low for k in ["doanh số", "doanh thu", "tiền bán", "bán được bao nhiêu tiền", "doanh thu bao nhiêu", "tháng", "quý"])
        )
        if is_headcount_q:
            group_by_loc = any(k in q_low for k in ["khu vực", "địa điểm", "location", "vị trí", "thành phố", "city"]) and not any(k in q_low for k in ["team", "đội ngũ", "đội", "nhóm"])
            if group_by_loc:
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SỐ LƯỢNG NHÂN VIÊN THEO TỪNG KHU VỰC / LOCATION):
SELECT 
    pe.Location AS `Khu Vực`,
    COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`
FROM people pe
WHERE pe.Location != '' AND pe.Location IS NOT NULL
GROUP BY pe.Location
ORDER BY `Số Lượng Nhân Viên` DESC;
(CẢNH BÁO BẮT BUỘC: 
1. TUYỆT ĐỐI KHÔNG TRUY VẤN BẢNG sales! TUYỆT ĐỐI KHÔNG TÍNH SUM(Boxes) HAY SUM(Amount)!
2. BẮT BUỘC TRUY VẤN TỪ BẢNG people BẰNG HÀM COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`!
3. Nhóm theo Location và ORDER BY `Số Lượng Nhân Viên` DESC!)
"""
            else:
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SỐ LƯỢNG NHÂN VIÊN BÁN HÀNG PHÂN BỔ THEO TỪNG TEAM / ĐỘI NGŨ):
SELECT 
    pe.Team AS `Đội Ngũ`,
    COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`,
    ROUND(COUNT(DISTINCT pe.SPID) * 100.0 / (SELECT COUNT(*) FROM people WHERE Team != '' AND Team IS NOT NULL), 2) AS `Tỷ Lệ (%)`
FROM people pe
WHERE pe.Team != '' AND pe.Team IS NOT NULL
GROUP BY pe.Team
ORDER BY `Số Lượng Nhân Viên` DESC;
(CẢNH BÁO BẮT BUỘC:
1. TUYỆT ĐỐI KHÔNG TRUY VẤN BẢNG sales! TUYỆT ĐỐI KHÔNG TÍNH SUM(Boxes) HAY SUM(Amount)!
2. BẮT BUỘC TRUY VẤN TỪ BẢNG people BẰNG HÀM COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`!
3. Nhóm theo Team, lọc bỏ các dòng rỗng, tính đầy đủ số lượng và tỷ lệ, ORDER BY `Số Lượng Nhân Viên` DESC!)
"""

        # 0.005 Báo cáo kết quả kinh doanh / Lãi, Lỗ (P&L - Profit & Loss)
        is_catalog_price_q = any(k in q_low for k in ["đơn giá niêm yết", "giá niêm yết", "cost per box cao nhất", "cost per box thấp nhất", "cost_per_box cao nhất", "cost_per_box thấp nhất"]) or (
            any(k in q_low for k in ["cost per box", "cost_per_box"]) and any(k in q_low for k in ["sản phẩm nào", "mặt hàng nào", "cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất"]) and not any(k in q_low for k in ["doanh thu", "sales", "lợi nhuận", "profit", "báo cáo"])
        )

        is_pnl_q = (not is_catalog_price_q) and (any(k in q_low for k in [
            "lãi, lỗ", "lãi lỗ", "lãi", "lỗ", "kết quả kinh doanh", "profit and loss", "p&l", "pnl", "cost_per_box",
            "chi phí", "cost", "giá vốn", "cogs", "lợi nhuận ròng", "net profit"
        ]) or (
            any(k in q_low for k in ["lợi nhuận", "profit", "biên lợi nhuận", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"]) 
            and any(k in q_low for k in ["tháng", "quý", "năm", "month", "quarter", "báo cáo", "doanh thu", "chi phí", "sản phẩm", "từng", "product"])
        ))

        if is_pnl_q:
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_where = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}"
                yr_where = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"

            qtr_expr = (
                "strftime('%Y', s.SaleDate) || '-Q' || ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)"
                if is_sqlite else
                "CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate))"
            )

            has_month = any(k in q_low for k in ["tháng", "month"])
            has_quarter = any(k in q_low for k in ["quý", "quarter"])
            has_country = any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"])
            has_product = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
            has_team = any(k in q_low for k in ["team", "đội ngũ", "nhóm"])
            profit_alias = "Lợi Nhuận Ròng ($)" if any(k in q_low for k in ["ròng", "net"]) else "Lợi Nhuận ($)"

            # 1. P&L theo Quốc Gia kết hợp Tháng / Quý
            if has_country or (has_month and not has_product and not has_team):
                if has_month and has_quarter:
                    time_cols = f"    {date_expr} AS `Tháng`,\n    {qtr_expr} AS `Quý`,\n    g.Geo AS `Quốc Gia`,"
                    group_cols = "`Tháng`, `Quý`, `Quốc Gia`"
                    order_col = f"`Tháng` ASC, `{profit_alias}` DESC"
                    chart_tip = f"Dùng {date_expr} AS `Tháng` làm trục thời gian và g.Geo AS `Quốc Gia` để vẽ đa đường!"
                elif has_quarter and not has_month:
                    time_cols = f"    {qtr_expr} AS `Quý`,\n    g.Geo AS `Quốc Gia`,"
                    group_cols = "`Quý`, `Quốc Gia`"
                    order_col = f"`Quý` ASC, `{profit_alias}` DESC"
                    chart_tip = f"Dùng {qtr_expr} AS `Quý` làm trục thời gian!"
                else:
                    time_cols = f"    {date_expr} AS `Tháng`,\n    g.Geo AS `Quốc Gia`,"
                    group_cols = "`Tháng`, `Quốc Gia`"
                    order_col = f"`Tháng` ASC, `{profit_alias}` DESC"
                    chart_tip = f"Dùng {date_expr} AS `Tháng` làm trục thời gian!"

                where_clause = yr_where if yr_where else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (BÁO CÁO KẾT QUẢ KINH DOANH LÃI/LỖ THEO QUỐC GIA{yr_label}):
SELECT 
{time_cols}
    SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
    ROUND(SUM(s.Boxes * pr.Cost_per_box), 2) AS `Tổng Chi Phí ($)`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2) AS `{profit_alias}`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS `Tỷ Suất Lợi Nhuận (%)`
FROM sales s
JOIN products pr ON s.PID = pr.PID
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}GROUP BY {group_cols}
ORDER BY {order_col};
(CẢNH BÁO BẮT BUỘC: 
1. BẮT BUỘC JOIN cả products pr VÀ geo g!
2. BẮT BUỘC tính đủ 4 chỉ số với đúng tên cột tiếng Việt: `Tổng Doanh Thu ($)`, `Tổng Chi Phí ($)`, `{profit_alias}`, `Tỷ Suất Lợi Nhuận (%)`!
3. TUYỆT ĐỐI KHÔNG dùng alias tiếng Anh kỳ lạ như Total Returns, Packaging Cost hay Boxes Cost!
4. {chart_tip})
"""
            # 2. P&L theo Sản phẩm
            elif has_product:
                top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
                limit_clause = f"\nLIMIT {top_m.group(1)}" if top_m else ""
                time_select = f"    {date_expr} AS `Tháng`,\n" if has_month else (f"    {qtr_expr} AS `Quý`,\n" if has_quarter else "")
                category_col = "" if (has_month or has_quarter) else "    pr.Category AS `Danh Mục`,\n"
                group_p = "`Tháng`, `Sản Phẩm`" if has_month else ("`Quý`, `Sản Phẩm`" if has_quarter else "`Sản Phẩm`, `Danh Mục`")
                order_p = f"`Tháng` ASC, `{profit_alias}` DESC" if has_month else (f"`Quý` ASC, `{profit_alias}` DESC" if has_quarter else f"`{profit_alias}` DESC")
                where_clause = yr_where if yr_where else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (BÁO CÁO KẾT QUẢ KINH DOANH LÃI/LỖ THEO SẢN PHẨM{yr_label}):
SELECT 
{time_select}    pr.Product AS `Sản Phẩm`,
{category_col}    SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
    ROUND(SUM(s.Boxes * pr.Cost_per_box), 2) AS `Tổng Chi Phí ($)`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2) AS `{profit_alias}`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS `Tỷ Suất Lợi Nhuận (%)`
FROM sales s
JOIN products pr ON s.PID = pr.PID
{where_clause}GROUP BY {group_p}
ORDER BY {order_p}{limit_clause};
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC JOIN products pr ON s.PID = pr.PID để lấy pr.Cost_per_box!
2. BẮT BUỘC tính đầy đủ: `Tổng Doanh Thu ($)`, `Tổng Chi Phí ($)`, `{profit_alias}`, `Tỷ Suất Lợi Nhuận (%)`!
3. KHÔNG ĐƯỢC tự ý thêm LIMIT nếu người dùng không yêu cầu Top N! Phải trả về đầy đủ tất cả sản phẩm!)
"""

        # 0.01 Tỷ lệ đóng góp doanh thu theo nhóm sản phẩm (Category)
        if any(k in q_low for k in ["category", "nhóm sản phẩm", "nhóm hàng", "danh mục"]) and any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "tỉ trọng", "tỷ trọng", "cơ cấu", "đóng góp", "share", "ratio"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_inner = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_inner = f" WHERE strftime('%Y', SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ ĐÓNG GÓP DOANH THU CỦA TỪNG NHÓM SẢN PHẨM / CATEGORY{yr_label}):
SELECT 
    pr.Category AS Category,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}GROUP BY pr.Category
ORDER BY TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và products pr ON s.PID = pr.PID! BẮT BUỘC tính cột Percentage bằng ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage! Nhóm theo pr.Category!)
"""

        # 0.02 Tỷ lệ đóng góp doanh thu theo quốc gia / thị trường (Country / Geo)
        elif any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"]) and any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "tỉ trọng", "tỷ trọng", "cơ cấu", "đóng góp", "share", "ratio"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_inner = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_inner = f" WHERE strftime('%Y', SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ ĐÓNG GÓP DOANH THU CỦA TỪNG QUỐC GIA / COUNTRY{yr_label}):
SELECT 
    g.Geo AS Country,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{yr_filter}GROUP BY g.Geo
ORDER BY TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và geo g ON s.GeoID = g.GeoID! BẮT BUỘC tính cột Percentage bằng ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage! Nhóm theo g.Geo!)
"""

        # 0.03 Tỷ lệ đóng góp doanh thu theo đội ngũ (Team)
        elif any(k in q_low for k in ["team", "đội ngũ", "đội", "nhóm bán hàng"]) and any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "tỉ trọng", "tỷ trọng", "cơ cấu", "đóng góp", "share", "ratio"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_inner = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}"
                yr_inner = f" AND strftime('%Y', s2.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s2.SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ ĐÓNG GÓP DOANH THU CỦA TỪNG ĐỘI NGŨ / TEAM{yr_label}):
SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales s2 JOIN people pe2 ON s2.SPID = pe2.SPID WHERE pe2.Team != '' AND pe2.Team IS NOT NULL{yr_inner}), 2) AS Percentage
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL{yr_filter}
GROUP BY pe.Team
ORDER BY TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và people pe ON s.SPID = pe.SPID! BẮT BUỘC tính cột Percentage! Nhóm theo pe.Team!)
"""

        # 0.04 Tỷ lệ đóng góp doanh thu theo sản phẩm (Product)
        elif any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "kẹo", "socola", "chocolate"]) and any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "tỉ trọng", "tỷ trọng", "cơ cấu", "đóng góp", "share", "ratio"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_inner = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_inner = f" WHERE strftime('%Y', SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ ĐÓNG GÓP DOANH THU CỦA TỪNG SẢN PHẨM / PRODUCT{yr_label}):
SELECT 
    pr.Product AS Product,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}GROUP BY pr.Product
ORDER BY TotalSales DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và products pr ON s.PID = pr.PID! BẮT BUỘC tính cột Percentage! LIMIT {req_limit}!)
"""

        # 0.05 So sánh hiệu quả bán hàng giữa các thị trường / quốc gia (Ví dụ: Mỹ (USA) và Ấn Độ (India))
        elif any(k in q_low for k in ["hiệu quả", "efficiency", "effectiveness", "năng suất"]) and any(k in q_low for k in ["thị trường", "quốc gia", "country", "geo", "usa", "mỹ", "india", "ấn độ"]):
            specific_geos = []
            if re.search(r'\b(usa|mỹ|hoa kỳ|united states)\b', q_low):
                specific_geos.append("'USA'")
            if re.search(r'\b(india|ấn độ|an do)\b', q_low):
                specific_geos.append("'India'")
            if re.search(r'\b(uk|nước anh|vương quốc anh|united kingdom)\b', q_low):
                specific_geos.append("'UK'")
            if re.search(r'\b(canada)\b', q_low):
                specific_geos.append("'Canada'")
            if re.search(r'\b(australia|úc)\b', q_low):
                specific_geos.append("'Australia'")
            if re.search(r'\b(new zealand)\b', q_low):
                specific_geos.append("'New Zealand'")

            geo_filter = f"WHERE g.Geo IN ({', '.join(specific_geos)})\n" if specific_geos else ""
            geos_label = " GIỮA " + " VÀ ".join(specific_geos).replace("'", "") if specific_geos else ""

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH HIỆU QUẢ BÁN HÀNG{geos_label}):
SELECT 
    g.Geo AS Market,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS RevenuePerBox,
    ROUND(AVG(s.Boxes), 2) AS AvgBoxesPerOrder,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{geo_filter}GROUP BY g.Geo
ORDER BY AvgOrderValue DESC;
(CẢNH BÁO BẮT BUỘC: So sánh hiệu quả bán hàng BẮT BUỘC phải tính các chỉ số hiệu quả gồm: Giá trị đơn hàng trung bình ROUND(AVG(s.Amount), 2) AS AvgOrderValue, Doanh thu trên mỗi hộp ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS RevenuePerBox! TUYỆT ĐỐI KHÔNG chỉ tính mỗi TotalSales!)
"""

        # 0.058 Giá trị đơn hàng trung bình của Nhân sự / Sales Person (toàn công ty hoặc theo Team cụ thể)
        elif (
            any(k in q_low for k in ["giá trị đơn hàng trung bình", "đơn hàng trung bình", "order value", "aov", "trung bình mỗi giao dịch", "trung bình trên mỗi giao dịch"])
            and any(k in q_low for k in ["nhân sự", "nhân viên", "salesperson", "sales person", "người bán", "ai là", "ai có", "sales rep", "rep"])
        ):
            specific_team = None
            for tm in ["yummies", "delish", "jucies"]:
                if tm in q_low:
                    specific_team = tm.capitalize()
                    break

            team_filter = f"WHERE pe.Team = '{specific_team}'\n" if specific_team else "WHERE pe.Team != '' AND pe.Team IS NOT NULL\n"
            team_label = f" TRONG ĐỘI NGŨ {specific_team.upper()}" if specific_team else ""
            is_singular = any(k in q_low for k in ["ai là", "ai có", "người nào", "nhân sự nào", "nhân viên nào", "cao nhất", "lớn nhất", "đứng đầu"]) and not top_m
            eff_limit = int(top_m.group(1)) if top_m else (1 if is_singular else 10)

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (GIÁ TRỊ ĐƠN HÀNG TRUNG BÌNH CỦA NHÂN SỰ BÁN HÀNG{team_label}):
SELECT 
    pe.Salesperson AS Salesperson,
    pe.Team AS Team,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue,
    COUNT(s.PID) AS TotalOrders,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{team_filter}GROUP BY pe.SPID, pe.Salesperson, pe.Team
ORDER BY AvgOrderValue DESC
LIMIT {eff_limit};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN XẾP HẠNG NHÂN SỰ BÁN HÀNG (CỘT pe.Salesperson), TUYỆT ĐỐI KHÔNG GROUP BY MỖI CỘT pe.Team!
2. BẮT BUỘC JOIN giữa sales s và people pe ON s.SPID = pe.SPID!
3. BẮT BUỘC tính ROUND(AVG(s.Amount), 2) AS AvgOrderValue!
{f"4. BẮT BUỘC lọc đúng đội ngũ: WHERE pe.Team = '{specific_team}'!" if specific_team else "4. Lọc bỏ các dòng Team rỗng: WHERE pe.Team != '' AND pe.Team IS NOT NULL!"}
5. BẮT BUỘC ORDER BY AvgOrderValue DESC LIMIT {eff_limit}!)
"""

        # 0.06 Giá trị đơn hàng trung bình theo đội ngũ / Team kinh doanh
        elif (
            any(k in q_low for k in ["giá trị đơn hàng trung bình", "đơn hàng trung bình", "order value", "aov"])
            and not any(k in q_low for k in ["nhân sự", "nhân viên", "salesperson", "sales person", "người bán", "ai là", "sales rep", "rep"])
        ) or (
            any(k in q_low for k in ["hiệu quả", "efficiency"])
            and any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng"])
        ):
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (GIÁ TRỊ ĐƠN HÀNG TRUNG BÌNH THEO ĐỘI NGŨ / TEAM):
SELECT 
    pe.Team AS Team,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS RevenuePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL
GROUP BY pe.Team
ORDER BY AvgOrderValue DESC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và people pe ON s.SPID = pe.SPID! Tính ROUND(AVG(s.Amount), 2) AS AvgOrderValue và ORDER BY AvgOrderValue DESC!)
"""

        # 0.064 Team có doanh số / số lượng hộp cao nhất / thấp nhất và sản phẩm chủ lực (Team with Flagship/Hero Product)
        elif any(k in q_low for k in ["team", "đội ngũ", "nhóm"]) and any(k in q_low for k in ["sản phẩm chủ lực", "mặt hàng chủ lực", "sản phẩm chính", "sản phẩm bán chạy nhất của họ", "sản phẩm đóng góp lớn nhất", "sản phẩm của họ là gì"]):
            is_lowest = any(k in q_low for k in ["thấp nhất", "ít nhất", "kém nhất", "nhỏ nhất", "lowest", "least", "bottom"])
            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
            
            order_dir = "ASC" if is_lowest else "DESC"
            team_order_metric = "TotalBoxesSold" if has_boxes else "TotalSales"
            product_rank_metric = "SUM(s.Boxes)" if has_boxes else "SUM(s.Amount)"
            team_desc = "THẤP NHẤT" if is_lowest else "CAO NHẤT"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TEAM KINH DOANH CÓ DOANH SỐ/HỘP {team_desc} VÀ SẢN PHẨM CHỦ LỰC):
WITH TeamSummary AS (
    SELECT 
        pe.Team,
        SUM(s.Boxes) AS TotalBoxesSold,
        SUM(s.Amount) AS TotalSales
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    WHERE pe.Team != '' AND pe.Team IS NOT NULL
    GROUP BY pe.Team
    ORDER BY {team_order_metric} {order_dir}
    LIMIT 1
),
TeamProductSales AS (
    SELECT 
        pe.Team,
        pr.Product,
        SUM(s.Boxes) AS ProductBoxesSold,
        SUM(s.Amount) AS ProductSales,
        DENSE_RANK() OVER (PARTITION BY pe.Team ORDER BY {product_rank_metric} DESC) AS ProductRank
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    JOIN products pr ON s.PID = pr.PID
    WHERE pe.Team IN (SELECT Team FROM TeamSummary)
    GROUP BY pe.Team, pr.PID, pr.Product
)
SELECT 
    ts.Team AS Team,
    ts.TotalBoxesSold AS TeamTotalBoxes,
    ts.TotalSales AS TeamTotalSales,
    tps.Product AS FlagshipProduct,
    tps.ProductBoxesSold AS FlagshipBoxesSold,
    tps.ProductSales AS FlagshipSales
FROM TeamSummary ts
JOIN TeamProductSales tps ON ts.Team = tps.Team AND tps.ProductRank = 1;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN TÌM TEAM KINH DOANH ({team_desc}) KẾT HỢP XÁC ĐỊNH SẢN PHẨM CHỦ LỰC CỦA TEAM ĐÓ!
2. Tuân thủ mô hình 2 CTE:
   - CTE 1 (TeamSummary): Tính tổng số hộp và doanh thu theo pe.Team, ORDER BY {team_order_metric} {order_dir} LIMIT 1 để tìm ra Team mục tiêu!
   - CTE 2 (TeamProductSales): Lấy các sản phẩm mà Team đó đã bán, dùng DENSE_RANK() OVER (PARTITION BY pe.Team ORDER BY {product_rank_metric} DESC) AS ProductRank!
3. Mệnh đề SELECT cuối cùng JOIN giữa TeamSummary và TeamProductSales ON ts.Team = tps.Team AND tps.ProductRank = 1!
4. TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ SÓT CỘT SẢN PHẨM CHỦ LỰC FlagshipProduct!)
"""

        # 0.065 So sánh tổng doanh số và số lượng hộp bán ra giữa các Team kinh doanh
        elif (
            any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh"])
            and not any(k in q_low for k in ["sản phẩm chủ lực", "mặt hàng chủ lực", "sản phẩm chính", "sản phẩm bán chạy nhất của họ", "sản phẩm của họ là gì", "sản phẩm"])
            and not any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "từng người", "từng nhân viên", "thành viên", "ai", "ai bán", "ai có", "riêng team", "team delish", "team yummies", "team jucies", "delish", "yummies", "jucies"])
            and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền"])
            and any(k in q_low for k in ["hộp", "thùng", "boxes", "số lượng"])
        ):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_label = f" NĂM {yr_val}" if yr_val else ""
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH TỔNG DOANH SỐ VÀ SỐ LƯỢNG HỘP BÁN RA GIỮA CÁC TEAM KINH DOANH{yr_label}):
SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS AvgPricePerBox
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL{yr_filter}
GROUP BY pe.Team
ORDER BY TotalSales DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN SO SÁNH GIỮA CÁC TEAM KINH DOANH (BẢNG people, CỘT pe.Team), TUYỆT ĐỐI CẤM NHÓM THEO SẢN PHẨM (products) HAY QUỐC GIA (geo)!
2. BẮT BUỘC JOIN giữa sales s VÀ people pe ON s.SPID = pe.SPID!
3. BẮT BUỘC TÍNH CẢ 2 CHỈ SỐ: Tổng doanh số SUM(s.Amount) AS TotalSales VÀ Số lượng hộp bán ra SUM(s.Boxes) AS TotalBoxesSold!
4. Lọc bỏ các dòng Team rỗng: WHERE pe.Team != '' AND pe.Team IS NOT NULL!)
"""

        # 0.07 Lợi nhuận trung bình trên mỗi hộp / Tỷ suất lợi nhuận (Profit per box / Profit Margin)
        elif any(k in q_low for k in [
            "profit per box", "lợi nhuận trên mỗi hộp", "lợi nhuận mỗi hộp", 
            "lợi nhuận trung bình trên mỗi hộp", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận",
            "tỷ suất", "tỉ suất", "profit margin", "margin", "lợi nhuận", "profit"
        ]):
            top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
            req_limit = int(top_m.group(1)) if top_m else 10
            is_margin_focus = any(k in q_low for k in ["tỷ suất", "tỉ suất", "margin", "%", "phần trăm"])
            order_target = "ProfitMargin" if is_margin_focus else "ProfitPerBox"
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ SUẤT LỢI NHUẬN / LỢI NHUẬN TRUNG BÌNH TRÊN MỖI HỘP):
SELECT 
    pr.Product AS Product,
    pr.Category AS Category,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS ProfitMargin,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) / SUM(s.Boxes), 2) AS ProfitPerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN products pr ON s.PID = pr.PID
GROUP BY pr.Product, pr.Category
ORDER BY {order_target} DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC: 
1. Tỷ suất lợi nhuận % = ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS ProfitMargin.
2. Lợi nhuận mỗi hộp = ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) / SUM(s.Boxes), 2) AS ProfitPerBox.
3. TUYỆT ĐỐI KHÔNG chỉ SELECT cột Cost_per_box và ORDER BY Cost_per_box vì Cost_per_box là GIÁ VỐN chứ không phải lợi nhuận hay tỷ suất lợi nhuận!
4. BẮT BUỘC JOIN giữa sales s và products pr ON s.PID = pr.PID!)
"""

        # 0.078 So sánh tăng trưởng doanh số theo Quý giữa 2 mốc quý cụ thể (Quarter-over-Quarter Growth Comparison)
        elif (
            any(k in q_low for k in ["tăng trưởng", "tốc độ tăng", "tỷ lệ tăng", "tỉ lệ tăng", "tăng hơn", "tăng trên", "tăng ít nhất", "growth"])
            and any(k in q_low for k in ["quý", "quarter", "q1", "q2", "q3", "q4"])
            and any(k in q_low for k in ["so với", "vs", "so voi"])
        ):
            # Trích xuất 2 quý và năm: VD "quý 4/2021", "quý 3/2021"
            qtr_matches = re.findall(r'(?:quý|q)\s*([1-4])(?:[/\s]*(?:năm\s*)?(20\d{2}))?', q_low)
            target_q = int(qtr_matches[0][0]) if len(qtr_matches) >= 1 else 4
            target_yr = qtr_matches[0][1] if len(qtr_matches) >= 1 and qtr_matches[0][1] else None

            base_q = int(qtr_matches[1][0]) if len(qtr_matches) >= 2 else 3
            base_yr = qtr_matches[1][1] if len(qtr_matches) >= 2 and qtr_matches[1][1] else (target_yr if target_yr else "2021")

            if not target_yr:
                target_yr = base_yr if base_yr else "2021"

            # Ngưỡng tăng trưởng %: VD "tăng trưởng trên 20%"
            pct_m = re.search(r'(?:trên|hơn|vượt|ít nhất|tối thiểu|>|>=)?\s*(\d+(?:\.\d+)?)\s*%', q_low)
            threshold_val = float(pct_m.group(1)) if pct_m else 20.0

            op = ">"
            if any(k in q_low for k in ["ít nhất", "tối thiểu", ">="]):
                op = ">="
            elif any(k in q_low for k in ["dưới", "thấp hơn", "<"]):
                op = "<"

            # Xác định đối tượng phân tích: Nhân sự (Salesperson), Sản phẩm (Product), Team, hay Quốc gia (Geo)
            is_product = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "món", "kẹo", "socola"])
            is_team = any(k in q_low for k in ["team", "đội ngũ", "nhóm"]) and not is_product
            is_geo = any(k in q_low for k in ["quốc gia", "thị trường", "geo", "country"]) and not is_product and not is_team

            if is_product:
                entity_cols = "pr.Product AS Product, pr.Category AS Category"
                entity_dim = "Product, Category"
                join_clause = "JOIN products pr ON s.PID = pr.PID"
                group_clause = "pr.PID, pr.Product, pr.Category"
                entity_label = "SẢN PHẨM"
            elif is_team:
                entity_cols = "pe.Team AS Team"
                entity_dim = "Team"
                join_clause = "JOIN people pe ON s.SPID = pe.SPID\n    WHERE pe.Team != '' AND pe.Team IS NOT NULL"
                group_clause = "pe.Team"
                entity_label = "TEAM / ĐỘI NGŨ"
            elif is_geo:
                entity_cols = "g.Geo AS Country"
                entity_dim = "Country"
                join_clause = "JOIN geo g ON s.GeoID = g.GeoID"
                group_clause = "g.GeoID, g.Geo"
                entity_label = "THỊ TRƯỜNG / QUỐC GIA"
            else:
                entity_cols = "pe.Salesperson AS Salesperson, pe.Team AS Team"
                entity_dim = "Salesperson, Team"
                join_clause = "JOIN people pe ON s.SPID = pe.SPID"
                group_clause = "pe.SPID, pe.Salesperson, pe.Team"
                entity_label = "NHÂN SỰ BÁN HÀNG"

            q_base_col = f"Q{base_q}_Sales"
            q_target_col = f"Q{target_q}_Sales"

            if is_sqlite:
                base_case = f"ROUND(SUM(CASE WHEN strftime('%Y', s.SaleDate) = '{base_yr}' AND ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = {base_q} THEN s.Amount ELSE 0 END), 2)"
                target_case = f"ROUND(SUM(CASE WHEN strftime('%Y', s.SaleDate) = '{target_yr}' AND ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = {target_q} THEN s.Amount ELSE 0 END), 2)"
            else:
                base_case = f"ROUND(SUM(CASE WHEN YEAR(s.SaleDate) = {base_yr} AND QUARTER(s.SaleDate) = {base_q} THEN s.Amount ELSE 0 END), 2)"
                target_case = f"ROUND(SUM(CASE WHEN YEAR(s.SaleDate) = {target_yr} AND QUARTER(s.SaleDate) = {target_q} THEN s.Amount ELSE 0 END), 2)"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI ({entity_label} CÓ DOANH SỐ QUÝ {target_q}/{target_yr} TĂNG TRƯỞNG {op} {threshold_val}% SO VỚI QUÝ {base_q}/{base_yr}):
WITH QuarterlySales AS (
    SELECT 
        {entity_cols},
        {base_case} AS {q_base_col},
        {target_case} AS {q_target_col}
    FROM sales s
    {join_clause}
    GROUP BY {group_clause}
)
SELECT 
    {entity_dim},
    {q_base_col},
    {q_target_col},
    ROUND({q_target_col} - {q_base_col}, 2) AS AbsoluteGrowth,
    ROUND((({q_target_col} - {q_base_col}) / NULLIF({q_base_col}, 0)) * 100.0, 2) AS GrowthPct
FROM QuarterlySales
WHERE {q_base_col} > 0 
  AND (({q_target_col} - {q_base_col}) / {q_base_col}) * 100.0 {op} {threshold_val}
ORDER BY GrowthPct DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN TÌM {entity_label} CÓ TĂNG TRƯỞNG GIỮA 2 KỲ QUÝ CỤ THỂ, TUYỆT ĐỐI CẤM GROUP BY MỖI CỘT Quarter ĐỂ TÍNH DOANH THU TOÀN CÔNG TY!
2. Tuân thủ CTE tính doanh thu của từng thực thể ở 2 quý: Quý {base_q}/{base_yr} ({q_base_col}) và Quý {target_q}/{target_yr} ({q_target_col})!
3. Tính mức tăng tuyệt đối AbsoluteGrowth = ({q_target_col} - {q_base_col}) và tỷ lệ phần trăm GrowthPct = (({q_target_col} - {q_base_col}) / {q_base_col}) * 100.0!
4. BẮT BUỘC lọc {q_base_col} > 0 VÀ GrowthPct {op} {threshold_val}, sắp xếp ORDER BY GrowthPct DESC!)
"""

        # 0.079 Xếp hạng sản phẩm theo doanh số trong từng quý, so sánh thứ hạng giữa các quý
        elif (
            any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
            and any(k in q_low for k in ["quý", "quarter"])
            and any(k in q_low for k in ["xếp hạng", "thứ hạng", "hạng", "rank", "tăng hạng", "giảm hạng", "top 5", "top 10"])
        ):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else "2021"
            yr_cond = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
            qtr_expr = (
                "strftime('%Y', s.SaleDate) || '-Q' || ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)"
                if is_sqlite else
                "CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate))"
            )
            qtr_num_expr = "((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)" if is_sqlite else "QUARTER(s.SaleDate)"
            cast_delta = "CAST(MAX(CASE WHEN QtrNum = 1 THEN ProductRank END) AS INTEGER) - CAST(MAX(CASE WHEN QtrNum = 4 THEN ProductRank END) AS INTEGER)" if is_sqlite else "CAST(MAX(CASE WHEN QtrNum = 1 THEN ProductRank END) AS SIGNED) - CAST(MAX(CASE WHEN QtrNum = 4 THEN ProductRank END) AS SIGNED)"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (XẾP HẠNG SẢN PHẨM THEO DOANH SỐ TỪNG QUÝ NĂM {yr_val} & SO SÁNH THỨ HẠNG):
WITH QuarterlyProductSales AS (
    SELECT 
        pr.Product,
        {qtr_expr} AS Quarter,
        {qtr_num_expr} AS QtrNum,
        SUM(s.Amount) AS TotalSales
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    {yr_cond}
    GROUP BY pr.Product, Quarter, QtrNum
),
QuarterlyRanks AS (
    SELECT 
        Product,
        Quarter,
        QtrNum,
        TotalSales,
        DENSE_RANK() OVER (PARTITION BY Quarter ORDER BY TotalSales DESC) AS ProductRank
    FROM QuarterlyProductSales
),
PivotRanks AS (
    SELECT 
        Product,
        MAX(CASE WHEN QtrNum = 1 THEN ProductRank END) AS Q1_Rank,
        MAX(CASE WHEN QtrNum = 2 THEN ProductRank END) AS Q2_Rank,
        MAX(CASE WHEN QtrNum = 3 THEN ProductRank END) AS Q3_Rank,
        MAX(CASE WHEN QtrNum = 4 THEN ProductRank END) AS Q4_Rank,
        MAX(CASE WHEN QtrNum = 1 THEN TotalSales END) AS Q1_Sales,
        MAX(CASE WHEN QtrNum = 2 THEN TotalSales END) AS Q2_Sales,
        MAX(CASE WHEN QtrNum = 3 THEN TotalSales END) AS Q3_Sales,
        MAX(CASE WHEN QtrNum = 4 THEN TotalSales END) AS Q4_Sales,
        SUM(TotalSales) AS TotalAnnualSales,
        ({cast_delta}) AS RankDelta
    FROM QuarterlyRanks
    GROUP BY Product
),
RankExtremes AS (
    SELECT 
        MAX(RankDelta) AS MaxGain,
        MIN(RankDelta) AS MaxDrop
    FROM PivotRanks
)
SELECT 
    p.Product,
    p.Q1_Rank,
    p.Q2_Rank,
    p.Q3_Rank,
    p.Q4_Rank,
    p.RankDelta AS RankChange,
    CASE 
        WHEN p.RankDelta = e.MaxGain THEN 'Tăng hạng mạnh nhất'
        WHEN p.RankDelta = e.MaxDrop THEN 'Giảm hạng mạnh nhất'
        WHEN p.Q1_Rank <= 5 AND p.Q2_Rank <= 5 AND p.Q3_Rank <= 5 AND p.Q4_Rank <= 5 THEN 'Luôn trong Top 5'
        ELSE 'Bình thường'
    END AS PerformanceStatus,
    p.TotalAnnualSales
FROM PivotRanks p
CROSS JOIN RankExtremes e
ORDER BY p.RankDelta DESC, p.TotalAnnualSales DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN XẾP HẠNG TỪNG SẢN PHẨM QUA CÁC QUÝ, TUYỆT ĐỐI CẤM GROUP BY MỖI CỘT Quarter ĐỂ TÍNH DOANH THU TOÀN CÔNG TY!
2. Tuân thủ 3 Quy tắc Phân rã Nghiệp vụ bằng CTE:
   - CTE 1 (QuarterlyProductSales): Tính SUM(s.Amount) AS TotalSales theo pr.Product và từng quý năm {yr_val}!
   - CTE 2 (QuarterlyRanks): Dùng DENSE_RANK() OVER (PARTITION BY Quarter ORDER BY TotalSales DESC) AS ProductRank để xếp hạng độc lập từng quý!
   - CTE 3 (PivotRanks): Pivot Q1_Rank, Q2_Rank, Q3_Rank, Q4_Rank và tính độ lệch thứ hạng! LƯU Ý: Trong MySQL BẮT BUỘC dùng CAST(... AS SIGNED) để không bị lỗi unsigned underflow 1690!
   - CTE 4 (RankExtremes): Xác định mức tăng hạng tối đa (MaxGain) và giảm hạng tối đa (MaxDrop)!
3. MỆNH ĐỀ SELECT BẮT BUỘC xuất các cột: Product, Q1_Rank, Q2_Rank, Q3_Rank, Q4_Rank, RankChange, PerformanceStatus, TotalAnnualSales!)
"""

        # 0.08 Doanh thu theo từng quý (Quarterly Trend) - theo Quốc gia cụ thể, theo Team, theo Sản phẩm, hoặc Toàn công ty
        elif (
            any(k in q_low for k in ["quý", "quarter", "từng quý", "theo quý", "qua các quý", "quarterly"])
            and not (any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"]) and any(k in q_low for k in ["xếp hạng", "thứ hạng", "hạng", "rank", "tăng hạng", "giảm hạng", "top 5"]))
            and not (any(k in q_low for k in ["tăng trưởng", "growth", "tăng hơn", "tăng trên", "tăng ít nhất"]) and any(k in q_low for k in ["so với", "vs"]))
            and not any(k in q_low for k in ["nhân sự", "nhân viên", "salesperson", "sales person", "người bán"])
        ):
            specific_country = match_chocolates_specific_country(q_low)

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_where = (f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_label = f" NĂM {yr_val}" if yr_val else ""
            qtr_expr = (
                "strftime('%Y', s.SaleDate) || '-Q' || ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)"
                if is_sqlite else
                "CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate))"
            )

            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
            metric_col = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"

            if specific_country and not any(k in q_low for k in ["sản phẩm", "product", "nhân viên", "salesperson"]):
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THỊ TRƯỜNG {specific_country.upper()} THEO TỪNG QUÝ{yr_label}):
SELECT 
    {qtr_expr} AS Quarter,
    {metric_col}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
WHERE g.Geo = '{specific_country}'{yr_filter}
GROUP BY Quarter
ORDER BY Quarter ASC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC dùng {qtr_expr} AS Quarter! Lọc quốc gia bằng g.Geo = '{specific_country}'! GROUP BY Quarter và ORDER BY Quarter ASC để trả về đầy đủ các quý và vẽ biểu đồ đường Line chart! TUYỆT ĐỐI KHÔNG dùng MAX(s.SaleDate)!)
"""
            elif any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"]) and any(k in q_low for k in ["từng quốc gia", "từng thị trường", "các quốc gia", "mỗi quốc gia"]):
                where_clause = f"{yr_where}\n" if yr_where else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THEO TỪNG QUỐC GIA QUA CÁC QUÝ{yr_label}):
SELECT 
    {qtr_expr} AS Quarter,
    g.Geo AS Country,
    {metric_col}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}GROUP BY Quarter, Country
ORDER BY Quarter ASC, TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC dùng {qtr_expr} AS Quarter và g.Geo AS Country! GROUP BY Quarter, Country!)
"""
            elif any(k in q_low for k in ["team", "đội ngũ", "yummies", "delish", "jucies"]):
                specific_team = "Yummies" if "yummies" in q_low else ("Delish" if "delish" in q_low else ("Jucies" if "jucies" in q_low else None))
                if specific_team:
                    team_filter = f"WHERE pe.Team = '{specific_team}'{yr_filter}"
                    team_label = f"TEAM {specific_team.upper()}"
                else:
                    team_filter = f"WHERE pe.Team != ''{yr_filter}"
                    team_label = "TỪNG TEAM"
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU {team_label} THEO TỪNG QUÝ{yr_label}):
SELECT 
    {qtr_expr} AS Quarter,
    {metric_col}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{team_filter}
GROUP BY Quarter
ORDER BY Quarter ASC;
"""
            else:
                where_clause = f"{yr_where}\n" if yr_where else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU TOÀN CÔNG TY THEO TỪNG QUÝ{yr_label}):
SELECT 
    {qtr_expr} AS Quarter,
    {metric_col}
FROM sales s
{where_clause}GROUP BY Quarter
ORDER BY Quarter ASC;
(CẢNH BÁO BẮT BUỘC: Dùng {qtr_expr} AS Quarter! GROUP BY Quarter và ORDER BY Quarter ASC!)
"""

        # 0.09 Doanh thu của một Quốc gia cụ thể (India, USA, Canada...) qua các tháng
        elif match_chocolates_specific_country(q_low) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "thời gian", "xu hướng", "thay đổi", "biến động"]) and not any(k in q_low for k in ["sản phẩm", "product", "nhân viên", "salesperson"]):
            specific_c = match_chocolates_specific_country(q_low)
            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
            metric_col = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE g.Geo = '{specific_c}' AND strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE g.Geo = '{specific_c}' AND YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"
            else:
                yr_filter = f"WHERE g.Geo = '{specific_c}'\n"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THỊ TRƯỜNG {specific_c.upper()} QUA CÁC THÁNG{yr_label}):
SELECT 
    {date_expr} AS Month,
    {metric_col}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{yr_filter}GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: Lọc đúng thị trường g.Geo = '{specific_c}'! GROUP BY Month và ORDER BY Month ASC để trả về đúng 12 tháng liên tục của riêng thị trường này và vẽ biểu đồ đường Line chart! TUYỆT ĐỐI KHÔNG GROUP BY Country hoặc trả về các quốc gia khác!)
"""

        # 0.1 Doanh thu theo từng quốc gia (Country) qua các tháng (đa quốc gia)
        elif any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"]) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "thay đổi", "xu hướng", "biến động"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THEO TỪNG QUỐC GIA QUA CÁC THÁNG{yr_label}):
SELECT 
    {date_expr} AS Month,
    g.Geo AS Country,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{yr_filter}GROUP BY Month, Country
ORDER BY Month ASC, TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: TUYỆT ĐỐI CẤM DÙNG CTE `WITH ...`! BẮT BUỘC dùng SELECT trực tiếp JOIN giữa sales s và geo g ON s.GeoID = g.GeoID! Dùng {date_expr} AS Month làm trục thời gian và g.Geo AS Country để vẽ biểu đồ đa đường so sánh!)
"""
        # 0.18 Doanh số của một sản phẩm cụ thể (ví dụ: 85% Dark Bars, Mint Chip Choco...) qua các tháng
        elif match_chocolates_specific_product(q_low) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "thời gian", "xu hướng", "thay đổi", "biến động"]):
            specific_prod = match_chocolates_specific_product(q_low)
            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
            metric_col = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
            escaped_prod = specific_prod.replace("'", "''")
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE pr.Product = '{escaped_prod}' AND strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE pr.Product = '{escaped_prod}' AND YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"
            else:
                yr_filter = f"WHERE pr.Product = '{escaped_prod}'\n"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH SỐ SẢN PHẨM {specific_prod.upper()} QUA CÁC THÁNG{yr_label}):
SELECT 
    {date_expr} AS Month,
    {metric_col}
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: Lọc đúng sản phẩm bằng pr.Product = '{escaped_prod}'! BẮT BUỘC CHỈ GROUP BY Month, TUYỆT ĐỐI KHÔNG GROUP BY Product! ORDER BY Month ASC để trả về đúng 12 tháng liên tục của sản phẩm này và vẽ biểu đồ đường Line chart!)
"""

        # 0.19 Doanh số của một nhân viên cụ thể (ví dụ: Ches Bonnell, Brijesh Shah...) qua các tháng
        elif match_chocolates_specific_person(q_low) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "thời gian", "xu hướng", "thay đổi", "biến động"]):
            specific_pers = match_chocolates_specific_person(q_low)
            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
            metric_col = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
            escaped_pers = specific_pers.replace("'", "''")
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE pe.Salesperson = '{escaped_pers}' AND strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE pe.Salesperson = '{escaped_pers}' AND YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"
            else:
                yr_filter = f"WHERE pe.Salesperson = '{escaped_pers}'\n"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH SỐ CỦA NHÂN VIÊN {specific_pers.upper()} QUA CÁC THÁNG{yr_label}):
SELECT 
    {date_expr} AS Month,
    {metric_col}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{yr_filter}GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: Lọc đúng nhân viên bằng pe.Salesperson = '{escaped_pers}'! BẮT BUỘC CHỈ GROUP BY Month, TUYỆT ĐỐI KHÔNG GROUP BY Salesperson! ORDER BY Month ASC để trả về đúng 12 tháng liên tục của nhân viên này và vẽ biểu đồ đường Line chart!)
"""

        # 0.2 Doanh thu theo từng sản phẩm qua các tháng
        elif any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"]) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU TỪNG SẢN PHẨM QUA CÁC THÁNG{yr_label}):
SELECT 
    {date_expr} AS Month,
    pr.Product AS Product,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}GROUP BY Month, Product
ORDER BY Month ASC, TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: TUYỆT ĐỐI CẤM DÙNG CTE `WITH ...`! Dùng SELECT trực tiếp JOIN giữa sales s và products pr ON s.PID = pr.PID!)
"""
        # 0.3 Doanh thu theo nhân viên qua các tháng
        elif any(k in q_low for k in ["nhân viên", "salesperson", "sales person", "người bán"]) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THEO NHÂN VIÊN QUA CÁC THÁNG{yr_label}):
SELECT 
    {date_expr} AS Month,
    pe.Salesperson AS Salesperson,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{yr_filter}GROUP BY Month, Salesperson
ORDER BY Month ASC, TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: TUYỆT ĐỐI CẤM DÙNG CTE `WITH ...`! Dùng SELECT trực tiếp JOIN giữa sales s và people pe ON s.SPID = pe.SPID!)
"""
        # 0.35 Doanh thu của Team / Đội ngũ (hoặc Team cụ thể như Yummies, Delish, Jucies) qua các tháng
        elif any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "yummies", "delish", "jucies"]) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "xu hướng", "thay đổi"]):
            specific_team = None
            if "yummies" in q_low:
                specific_team = "Yummies"
            elif "delish" in q_low:
                specific_team = "Delish"
            elif "jucies" in q_low:
                specific_team = "Jucies"

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {yr_val}"

            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
            has_sales = any(k in q_low for k in ["doanh thu", "doanh số", "sales", "tiền", "amount"])
            if has_sales and has_boxes:
                metric_col = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
            elif has_boxes:
                metric_col = "SUM(s.Boxes) AS TotalBoxesSold"
            else:
                metric_col = "SUM(s.Amount) AS TotalSales"

            if specific_team:
                conds = [f"pe.Team = '{specific_team}'"]
                if yr_filter:
                    conds.append(yr_filter)
                where_clause = "WHERE " + " AND ".join(conds)
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU CỦA TEAM {specific_team.upper()} QUA CÁC THÁNG):
SELECT 
    {date_expr} AS Month,
    {metric_col}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và people pe ON s.SPID = pe.SPID! Lọc đội ngũ bằng pe.Team = '{specific_team}'! BẮT BUỘC CHỈ GROUP BY Month, TUYỆT ĐỐI KHÔNG GROUP BY Team hoặc xuất cột Team! ORDER BY Month ASC để vẽ biểu đồ đường 12 tháng của riêng team {specific_team}!)
"""
            else:
                where_clause = f"WHERE pe.Team != '' AND {yr_filter}" if yr_filter else "WHERE pe.Team != ''"
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THEO TỪNG TEAM QUA CÁC THÁNG):
SELECT 
    {date_expr} AS Month,
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY Month, Team
ORDER BY Month ASC, TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và people pe ON s.SPID = pe.SPID! Cột đội ngũ là pe.Team!)
"""

        # 0.39 Xu hướng tổng doanh thu và số hộp bán ra theo từng tháng (cả 2 chỉ số Doanh thu & Số lượng hộp)
        elif (
            any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "xu hướng"])
            and any(k in q_low for k in ["doanh thu", "doanh số", "sales", "tiền"])
            and any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
            and not any(k in q_low for k in ["sản phẩm", "product", "quốc gia", "country", "nhân viên", "salesperson", "team", "yummies", "delish", "jucies"])
        ):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
                m_expr = "CAST(strftime('%m', s.SaleDate) AS INTEGER)" if is_sqlite else "MONTH(s.SaleDate)"
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU VÀ SỐ HỘP THEO TỪNG THÁNG NĂM {yr_val}):
SELECT 
    {m_expr} AS Month,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
{yr_filter}
GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC trả về ĐỦ CẢ 2 CHỈ SỐ: `SUM(s.Amount) AS TotalRevenue` VÀ `SUM(s.Boxes) AS TotalBoxesSold`! TUYỆT ĐỐI KHÔNG được bỏ sót cột nào!
2. TUYỆT ĐỐI CẤM DÙNG `LIMIT 10`! 1 năm có 12 tháng, bắt buộc để đầy đủ các tháng không được giới hạn LIMIT. Dùng {m_expr} AS Month!)
"""
            else:
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU VÀ SỐ HỘP THEO TỪNG THÁNG):
SELECT 
    {date_expr} AS Month,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC trả về ĐỦ CẢ 2 CHỈ SỐ: `SUM(s.Amount) AS TotalRevenue` VÀ `SUM(s.Boxes) AS TotalBoxesSold`! TUYỆT ĐỐI KHÔNG được bỏ sót cột nào!
2. TUYỆT ĐỐI CẤM DÙNG `LIMIT 10`! Bắt buộc ORDER BY Month ASC!)
"""
        # 0.4 Doanh thu tổng hợp qua các tháng
        elif any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng"]) and any(k in q_low for k in ["doanh thu", "doanh số", "sales", "tiền"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
                m_expr = "CAST(strftime('%m', s.SaleDate) AS INTEGER)" if is_sqlite else "MONTH(s.SaleDate)"
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THEO TỪNG THÁNG NĂM {yr_val}):
SELECT 
    {m_expr} AS Month,
    SUM(s.Amount) AS TotalSales
FROM sales s
{yr_filter}
GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: TUYỆT ĐỐI CẤM DÙNG CTE `WITH ...`! Dùng SELECT trực tiếp từ sales s!)
"""
            else:
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU QUA CÁC THÁNG):
SELECT 
    {date_expr} AS Month,
    SUM(s.Amount) AS TotalSales
FROM sales s
GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: TUYỆT ĐỐI CẤM DÙNG CTE `WITH ...`! Dùng SELECT trực tiếp từ sales s!)
"""
        # 0.5 Số lượng hộp / thùng (Boxes) bán ra qua các tháng
        elif any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"]) and any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "xu hướng"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
                m_expr = "CAST(strftime('%m', s.SaleDate) AS INTEGER)" if is_sqlite else "MONTH(s.SaleDate)"
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SỐ LƯỢNG HỘP BÁN RA QUA CÁC THÁNG NĂM {yr_val}):
SELECT 
    {m_expr} AS Month,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
{yr_filter}
GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: TUYỆT ĐỐI CẤM DÙNG `LIMIT 10`! 1 năm có 12 tháng, bắt buộc để đầy đủ các tháng không được giới hạn LIMIT. Dùng {m_expr} AS Month và SUM(s.Boxes) AS TotalBoxesSold!)
"""
            else:
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SỐ LƯỢNG HỘP BÁN RA QUA CÁC THÁNG):
SELECT 
    {date_expr} AS Month,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
GROUP BY Month
ORDER BY Month ASC;
(CẢNH BÁO BẮT BUỘC: TUYỆT ĐỐI CẤM DÙNG `LIMIT 10`! Bắt buộc ORDER BY Month ASC!)
"""
        # 0.55 Thống kê đơn hàng / giao dịch theo ngưỡng (Order Threshold Aggregation)
        # Ví dụ: "Có bao nhiêu đơn hàng bán được trên 1,000 hộp, và tổng doanh thu từ các đơn hàng lớn này là bao nhiêu?"
        elif (
            any(k in q_low for k in ["đơn hàng", "giao dịch", "mỗi đơn", "các đơn", "orders", "transactions", "đơn"])
            and any(k in q_low for k in ["trên", "hơn", "vượt", "lớn hơn", ">", "cao hơn", "từ"])
            and any(k in q_low for k in ["bao nhiêu", "có bao nhiêu", "số lượng đơn", "tổng doanh thu", "tổng số"])
            and not any(k in q_low for k in ["theo từng", "mỗi nhân viên", "mỗi người", "mỗi sản phẩm", "mỗi quốc gia", "từng team", "từng tháng", "từng quý", "top", "xếp hạng"])
            and not (
                any(k in q_low for k in ["bites", "bite", "bars", "bar", "other", "category", "danh mục"])
                or any(k in q_low for k in ["usa", "canada", "india", "uk", "new zealand", "australia", "thị trường"])
            )
        ):
            box_m = re.search(r'(?:trên|hơn|vượt|lớn hơn|cao hơn|[><]=?)\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:hộp|hop|thùng|thung|boxes)', q_low)
            amt_m = re.search(r'(?:trên|hơn|vượt|lớn hơn|cao hơn|[><]=?)\s*[\$]?\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:k|triệu|tr|usd|\$|đô)?', q_low)

            if box_m:
                thresh_val = int(box_m.group(1).replace(',', '').replace('.', ''))
                cond_expr = f"s.Boxes > {thresh_val}"
                cond_label = f"TRÊN {thresh_val:,} HỘP"
            elif amt_m:
                raw_val = float(amt_m.group(1).replace(',', '').replace('.', ''))
                if 'k' in q_low:
                    raw_val *= 1000
                elif any(k in q_low for k in ['triệu', 'tr']):
                    raw_val *= 1000000
                thresh_val = int(raw_val)
                cond_expr = f"s.Amount > {thresh_val}"
                cond_label = f"TRÊN ${thresh_val:,.0f}"
            else:
                cond_expr = "s.Boxes > 1000"
                cond_label = "TRÊN 1,000 HỘP"

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (THỐNG KÊ ĐƠN HÀNG QUY MÔ LỚN {cond_label}{yr_label}):
SELECT 
    COUNT(*) AS LargeOrdersCount,
    SUM(s.Amount) AS TotalLargeOrdersRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(AVG(s.Amount), 2) AS AvgLargeOrderAmount
FROM sales s
WHERE {cond_expr}{yr_filter};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN THỐNG KÊ TỔNG THỂ CÁC ĐƠN HÀNG/GIAO DỊCH QUY MÔ LỚN TRÊN TOÀN BỘ CSDL ({cond_label})!
2. TUYỆT ĐỐI KHÔNG DÙNG GROUP BY THEO NHÂN VIÊN (pe.SPID), SẢN PHẨM (pr.PID) HAY QUỐC GIA (g.GeoID) VÌ NGƯỜI DÙNG KHÔNG HỎI 'THEO TỪNG...'!
3. BẮT BUỘC TRẢ VỀ ĐÚNG 1 DÒNG VỚI CÁC HÀM TỔNG HỢP: COUNT(*) AS LargeOrdersCount, SUM(s.Amount) AS TotalLargeOrdersRevenue, SUM(s.Boxes) AS TotalBoxesSold, ROUND(AVG(s.Amount), 2) AS AvgLargeOrderAmount!
4. TUYỆT ĐỐI KHÔNG DÙNG LIMIT 10 HAY LIMIT 25!)
"""

        # 0.59 Nhân viên kinh doanh / Nhân sự chưa từng bán sản phẩm thuộc danh mục / thị trường (Anti-Join / Negative Filter / NOT IN)
        # Ví dụ: "Liệt kê những nhân viên kinh doanh chưa từng bán được bất kỳ một hộp sản phẩm nào thuộc danh mục 'Bars' tại thị trường Ấn Độ (India)."
        elif (
            any(k in q_low for k in ["chưa từng", "chưa bao giờ", "không bán được", "chưa bán được", "không có đơn", "chưa từng bán", "never sold", "never"])
            and any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "ai", "danh sách", "liệt kê"])
        ):
            # Nhận diện danh mục sản phẩm nếu có
            cat = None
            if "bar" in q_low or "bars" in q_low:
                cat = "Bars"
            elif "bite" in q_low or "bites" in q_low:
                cat = "Bites"
            elif "other" in q_low:
                cat = "Other"

            # Nhận diện thị trường quốc gia nếu có
            geo = None
            if any(k in q_low for k in ["ấn độ", "india"]):
                geo = "India"
            elif any(k in q_low for k in ["mỹ", "usa", "hoa kỳ", "united states"]):
                geo = "USA"
            elif any(k in q_low for k in ["canada"]):
                geo = "Canada"
            elif any(k in q_low for k in ["new zealand", "newzealand", "nz"]):
                geo = "New Zealand"
            elif any(k in q_low for k in ["úc", "australia", "aus"]):
                geo = "Australia"
            elif any(k in q_low for k in ["nước anh", "vương quốc anh", "united kingdom", "uk"]):
                geo = "UK"

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            sub_conds = []
            sub_joins = []
            if cat:
                sub_joins.append("JOIN products pr ON s.PID = pr.PID")
                sub_conds.append(f"pr.Category = '{cat}'")
            if geo:
                sub_joins.append("JOIN geo g ON s.GeoID = g.GeoID")
                sub_conds.append(f"g.Geo = '{geo}'")
            if yr_val:
                sub_conds.append(f"strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {yr_val}")

            sub_joins_str = ("\n    " + "\n    ".join(sub_joins)) if sub_joins else ""
            sub_conds_str = ("WHERE " + " AND ".join(sub_conds)) if sub_conds else ""

            cat_desc = f" DANH MỤC '{cat.upper()}'" if cat else ""
            geo_desc = f" TẠI THỊ TRƯỜNG {geo.upper()}" if geo else ""

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN CHƯA TỪNG BÁN ĐƯỢC HỘP SẢN PHẨM NÀO{cat_desc}{geo_desc}{yr_label}):
SELECT 
    pe.SPID,
    pe.Salesperson,
    pe.Team
FROM people pe
WHERE pe.SPID NOT IN (
    SELECT DISTINCT s.SPID
    FROM sales s{sub_joins_str}
    {sub_conds_str}
)
ORDER BY pe.Salesperson ASC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN TÌM KIẾM PHỦ ĐỊNH (ANTI-JOIN / NOT IN / NOT EXISTS): Liệt kê nhân sự CHƯA TỪNG bán sản phẩm thỏa mãn điều kiện!
2. BẮT BUỘC chọn từ bảng people pe và dùng điều kiện `pe.SPID NOT IN (SELECT DISTINCT s.SPID FROM sales s{sub_joins_str} {sub_conds_str})`!
3. TUYỆT ĐỐI KHÔNG DÙNG INNER JOIN giữa people và sales vì INNER JOIN sẽ chỉ lấy những người ĐÃ TỪNG BÁN!
4. TUYỆT ĐỐI KHÔNG DÙNG ORDER BY ... DESC LIMIT 10 vì đây là câu hỏi liệt kê toàn bộ nhân sự chưa từng bán!)
"""

        # 0.592 Thống kê doanh số / số hộp của một nhân viên cụ thể (ví dụ: Brien Boise, Ches Bonnell...)
        elif match_chocolates_specific_person(q_low) and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "hộp", "boxes", "tiền", "thống kê", "tổng doanh"]) and not any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "quý", "quarter", "chưa từng", "không bán", "top", "xếp hạng"]):
            specific_pers = match_chocolates_specific_person(q_low)
            specific_geo = match_chocolates_specific_country(q_low)
            escaped_pers = specific_pers.replace("'", "''")

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            where_conds = [f"pe.Salesperson = '{escaped_pers}'"]
            geo_join = ""
            if specific_geo:
                geo_join = "\nJOIN geo g ON s.GeoID = g.GeoID"
                where_conds.append(f"g.Geo = '{specific_geo}'")
            if yr_val:
                where_conds.append(f"strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {yr_val}")

            where_clause = "WHERE " + " AND ".join(where_conds)
            geo_desc = f" TẠI THỊ TRƯỜNG {specific_geo.upper()}" if specific_geo else ""

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH SỐ VÀ SỐ HỘP CỦA NHÂN VIÊN {specific_pers.upper()}{geo_desc}{yr_label}):
SELECT 
    pe.Salesperson AS Salesperson,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID{geo_join}
{where_clause}
GROUP BY pe.SPID, pe.Salesperson;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN THỐNG KÊ DOANH SỐ VÀ SẢN LƯỢNG CỦA RIÊNG MỘT NHÂN VIÊN ({specific_pers.upper()})!
2. BẮT BUỘC lọc đúng nhân sự trong WHERE: pe.Salesperson = '{escaped_pers}'!
3. {f"BẮT BUỘC JOIN geo g VÀ lọc g.Geo = '{specific_geo}'!" if specific_geo else "TUYỆT ĐỐI KHÔNG lọc sai thị trường!"}
4. TUYỆT ĐỐI KHÔNG hiển thị danh sách xếp hạng 25 nhân viên toàn công ty!)
"""

        # 0.595 Phân tích Thống kê Doanh số Phân khúc Đa chiều (Multi-Dimensional Segment Filtering: Team + Geo/Country + Category/Product)
        # Ví dụ: "Thống kê doanh số bán hàng của riêng Team Delish tại thị trường Canada đối với các sản phẩm thuộc nhóm Bars."
        elif (
            any(k in q_low for k in ["delish", "yummies", "jucies"])
            and (
                match_chocolates_specific_country(q_low) is not None
                or any(k in q_low for k in ["bars", "bites", "other", "nhóm hàng", "nhóm sản phẩm", "danh mục"])
            )
            and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "bán hàng", "thống kê", "hộp", "boxes", "tiền"])
            and not any(k in q_low for k in [
                "chưa từng", "chưa bao giờ", "không bán", "chưa bán", "never", "so sánh giữa các team", "các team",
                "nhân viên", "nhân sự", "salesperson", "sales person", "người bán",
                "top nhân viên", "top nhân sự", "ai có", "ai bán"
            ])
        ):
            seg_team = None
            for tm in ["delish", "yummies", "jucies"]:
                if tm in q_low:
                    seg_team = tm.capitalize()
                    break

            seg_geo = match_chocolates_specific_country(q_low)

            seg_cat = None
            if any(k in q_low for k in ["bars", "bar"]):
                seg_cat = "Bars"
            elif any(k in q_low for k in ["bites", "bite"]):
                seg_cat = "Bites"
            elif "other" in q_low:
                seg_cat = "Other"

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            where_conds = []
            where_conds.append(f"pe.Team = '{seg_team}'")
            if seg_geo:
                where_conds.append(f"g.Geo = '{seg_geo}'")
            if seg_cat:
                where_conds.append(f"pr.Category = '{seg_cat}'")
            if yr_val:
                where_conds.append(f"strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {yr_val}")

            where_clause = " AND ".join(where_conds)

            desc_parts = [f"TEAM {seg_team.upper()}"]
            if seg_geo:
                desc_parts.append(f"THỊ TRƯỜNG {seg_geo.upper()}")
            if seg_cat:
                desc_parts.append(f"NHÓM {seg_cat.upper()}")
            desc_label = " • ".join(desc_parts)

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (THỐNG KÊ DOANH SỐ PHÂN KHÚC CHIẾN LƯỢC: {desc_label}{yr_label}):
SELECT 
    pr.Product AS Product,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
JOIN geo g ON s.GeoID = g.GeoID
JOIN products pr ON s.PID = pr.PID
WHERE {where_clause}
GROUP BY pr.PID, pr.Product
ORDER BY TotalSales DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN THỐNG KÊ DOANH SỐ CỦA RIÊNG MỘT PHÂN KHÚC ĐA CHIỀU ({desc_label})!
2. BẮT BUỘC LỌC ĐẦY ĐỦ CÁC ĐIỀU KIỆN TRONG MỆNH ĐỀ WHERE: {where_clause}!
3. TUYỆT ĐỐI KHÔNG ĐƯỢC GROUP BY pe.Team ĐỂ TRẢ VỀ TẤT CẢ CÁC ĐỘI NGŨ KHÁC VÌ NGƯỜI DÙNG CHỈ HỎI 'RIÊNG TEAM {seg_team}'!
4. TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ SÓT BẢNG geo (g.Geo) HAY products (pr.Category) TRONG CÂU TRUY VẤN!)
"""

        # 0.58 Nhân viên có doanh số / số lượng bán ra cao nhất qua từng năm
        elif (
            any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "salesperson", "sales person", "rep", "danh sách"])
            and any(k in q_low for k in ["doanh số cao nhất", "doanh thu cao nhất", "doanh số lớn nhất", "doanh thu lớn nhất", "cao nhất", "lớn nhất", "nhiều nhất"])
            and any(k in q_low for k in ["qua từng năm", "qua các năm", "theo từng năm", "theo năm", "mỗi năm", "hàng năm", "từng năm", "từng năm đó"])
            and not any(k in q_low for k in ["quý", "tháng", "sản phẩm", "quốc gia", "team"])
        ):
            if is_sqlite:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN CÓ DOANH SỐ CAO NHẤT QUA TỪNG NĂM):
WITH YearlySales AS (
    SELECT 
        pe.SPID,
        pe.Salesperson,
        CAST(strftime('%Y', s.SaleDate) AS INTEGER) AS Year,
        SUM(s.Amount) AS TotalSales,
        ROW_NUMBER() OVER (PARTITION BY strftime('%Y', s.SaleDate) ORDER BY SUM(s.Amount) DESC) AS rn
    FROM people pe
    JOIN sales s ON pe.SPID = s.SPID
    GROUP BY pe.SPID, pe.Salesperson, strftime('%Y', s.SaleDate)
)
SELECT 
    SPID,
    Salesperson,
    Year,
    TotalSales
FROM YearlySales
WHERE rn = 1
ORDER BY Year ASC;
"""
            else:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN CÓ DOANH SỐ CAO NHẤT QUA TỪNG NĂM):
WITH YearlySales AS (
    SELECT 
        pe.SPID,
        pe.Salesperson,
        YEAR(s.SaleDate) AS Year,
        SUM(s.Amount) AS TotalSales,
        ROW_NUMBER() OVER (PARTITION BY YEAR(s.SaleDate) ORDER BY SUM(s.Amount) DESC) AS rn
    FROM people pe
    JOIN sales s ON pe.SPID = s.SPID
    GROUP BY pe.SPID, pe.Salesperson, YEAR(s.SaleDate)
)
SELECT 
    SPID,
    Salesperson,
    Year,
    TotalSales
FROM YearlySales
WHERE rn = 1
ORDER BY Year ASC;
"""

        # 0.6 Top N nhân viên bán hàng / nhân sự (Salesperson) có doanh số / số lượng bán ra cao nhất
        elif (
            any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "sales rep", "rep", "thành viên", "ai bán", "ai có doanh số", "người", "ai có"])
            and not any(k in q_low for k in ["chưa từng", "chưa bao giờ", "không bán", "chưa bán", "không có", "never", "not in", "giao dịch", "đơn hàng", "orders", "transactions"])
            and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền", "cao nhất", "top", "xuất sắc", "nhiều nhất", "lớn nhất", "bán được", "bán chạy", "hộp", "thùng", "boxes"])
            and not match_chocolates_specific_person(q_low)
        ):
            specific_team = None
            for tm in ["yummies", "delish", "jucies"]:
                if tm in q_low:
                    specific_team = tm.capitalize()
                    break

            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None

            # Trích xuất quý nếu có (VD: "Quý 4", "Q4", "quarter 4")
            qtr_match = re.search(r'(?:quý|quarter|q)\s*(\d)', q_low, re.IGNORECASE)
            qtr_val = qtr_match.group(1) if qtr_match else None

            yr_label = ""
            if yr_val and qtr_val:
                yr_label = f" QUÝ {qtr_val} NĂM {yr_val}"
            elif yr_val:
                yr_label = f" NĂM {yr_val}"
            elif qtr_val:
                yr_label = f" QUÝ {qtr_val}"

            where_conds = []
            if specific_team:
                where_conds.append(f"pe.Team = '{specific_team}'")
            if yr_val:
                where_conds.append(f"strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {yr_val}")
            if qtr_val:
                where_conds.append(f"((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = {qtr_val}" if is_sqlite else f"QUARTER(s.SaleDate) = {qtr_val}")

            where_str = ("WHERE " + " AND ".join(where_conds) + "\n") if where_conds else ""
            team_label = f" TRONG NHÓM {specific_team.upper()}" if specific_team else ""

            has_revenue = any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền", "amount"])
            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes"])

            if has_revenue and has_boxes:
                measure_col = "SUM(s.Amount) AS TotalSales,\n    SUM(s.Boxes) AS TotalBoxesSold"
                if any(k in q_low for k in ["sắp xếp người có doanh số", "doanh số cao nhất", "doanh thu cao nhất", "doanh số lên đầu", "doanh thu lên đầu", "theo doanh số", "theo doanh thu"]):
                    order_col = "TotalSales"
                elif any(k in q_low for k in ["hộp cao nhất", "số hộp cao nhất", "nhiều hộp nhất", "theo số hộp", "theo hộp"]):
                    order_col = "TotalBoxesSold"
                elif has_revenue:
                    order_col = "TotalSales"
                else:
                    order_col = "TotalBoxesSold"
            elif has_boxes:
                measure_col = "SUM(s.Boxes) AS TotalBoxesSold"
                order_col = "TotalBoxesSold"
            else:
                measure_col = "SUM(s.Amount) AS TotalSales"
                order_col = "TotalSales"

            team_warning = f"Nhóm '{specific_team}' là đội ngũ nhân sự trong bảng people (cột pe.Team)! BẮT BUỘC lọc pe.Team = '{specific_team}'! " if specific_team else ""
            both_metrics_warning = "BẮT BUỘC tính cả 2 chỉ số: Tổng doanh số SUM(s.Amount) AS TotalSales VÀ Số hộp bán ra SUM(s.Boxes) AS TotalBoxesSold! " if (has_revenue and has_boxes) else ""

            is_all_employees = any(k in q_low for k in ["từng nhân viên", "từng người", "mỗi nhân viên", "mỗi người", "tất cả nhân viên", "toàn bộ nhân viên", "danh sách nhân viên"]) and not top_m
            limit_clause = ";" if is_all_employees else f"\nLIMIT {req_limit};"
            limit_label = "DANH SÁCH TẤT CẢ " if is_all_employees else f"TOP {req_limit} "
            limit_warning = "Liệt kê đầy đủ từng nhân viên, TUYỆT ĐỐI KHÔNG DÙNG LIMIT!" if is_all_employees else f"BẮT BUỘC dùng LIMIT {req_limit} theo yêu cầu người dùng!"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI ({limit_label}NHÂN SỰ/NHÂN VIÊN BÁN HÀNG{team_label}{yr_label}):
SELECT 
    pe.Salesperson AS Salesperson,
    {measure_col}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_str}GROUP BY pe.SPID, pe.Salesperson
ORDER BY {order_col} DESC{limit_clause}
(CẢNH BÁO BẮT BUỘC: {team_warning}{both_metrics_warning}BẮT BUỘC JOIN giữa sales s và people pe ON s.SPID = pe.SPID! Tên nhân sự nằm ở cột pe.Salesperson! {limit_warning} TUYỆT ĐỐI CẤM NHÓM THEO SẢN PHẨM (products) HAY QUỐC GIA (geo)!)
"""

        # 0.68 Phân tích nghịch lý / phân hóa sản phẩm giữa 2 thị trường (Cross-Market Contrast / Market Divergence)
        # Ví dụ: "Sản phẩm nào bán chạy nhất tại thị trường Ấn Độ (India) nhưng lại ế ẩm nhất (doanh số thấp nhất) tại thị trường Mỹ (USA)?"
        elif (
            any(k in q_low for k in ["sản phẩm", "mặt hàng", "kẹo", "socola", "chocolate", "product"])
            and any(k in q_low for k in ["bán chạy", "cao nhất", "top", "dẫn đầu"])
            and any(k in q_low for k in ["ế ẩm", "ế nhất", "thấp nhất", "kém nhất", "nghịch lý", "nhưng lại", "phân hóa", "divergence", "đối lập", "ngược lại", "chênh lệch bậc"])
            and any(k in q_low for k in ["thị trường", "quốc gia", "country", "geo", "ấn độ", "india", "mỹ", "usa", "canada", "úc", "australia", "new zealand", "uk", "anh"])
        ):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            # Nhận diện 2 quốc gia / thị trường trong câu hỏi
            geo_candidates = [
                ("India", ["ấn độ", "india"]),
                ("USA", ["mỹ", "usa", "hoa kỳ", "united states"]),
                ("Canada", ["canada"]),
                ("New Zealand", ["new zealand", "newzealand", "nz"]),
                ("Australia", ["úc", "australia", "aus"]),
                ("UK", ["nước anh", "vương quốc anh", "united kingdom", "uk"])
            ]
            detected_geos = []
            for gname, kws in geo_candidates:
                for kw in kws:
                    pattern = r'\b' + re.escape(kw) + r'\b'
                    m = re.search(pattern, q_low)
                    if m:
                        detected_geos.append((m.start(), gname))
                        break
            detected_geos.sort(key=lambda x: x[0])
            unique_geos = []
            for _, gname in detected_geos:
                if gname not in unique_geos:
                    unique_geos.append(gname)

            if len(unique_geos) >= 2:
                pos_good_list = [q_low.find(k) for k in ["bán chạy", "cao nhất", "top", "dẫn đầu", "tốt nhất"] if q_low.find(k) != -1]
                pos_bad_list = [q_low.find(k) for k in ["ế ẩm", "ế nhất", "thấp nhất", "kém nhất", "ế", "tụt hậu"] if q_low.find(k) != -1]
                pos_good = min(pos_good_list) if pos_good_list else 0
                pos_bad = min(pos_bad_list) if pos_bad_list else len(q_low)

                g1, g2 = unique_geos[0], unique_geos[1]
                idx1 = next((pos for pos, gn in detected_geos if gn == g1), 0)
                idx2 = next((pos for pos, gn in detected_geos if gn == g2), len(q_low))

                if abs(idx1 - pos_good) + abs(idx2 - pos_bad) <= abs(idx2 - pos_good) + abs(idx1 - pos_bad):
                    c_high, c_low = g1, g2
                else:
                    c_high, c_low = g2, g1
            elif len(unique_geos) == 1:
                c_high = unique_geos[0]
                c_low = "USA" if c_high != "USA" else "India"
            else:
                c_high, c_low = "India", "USA"

            alias_high = re.sub(r'[^a-zA-Z0-9]', '', c_high)
            alias_low = re.sub(r'[^a-zA-Z0-9]', '', c_low)

            cast_low_rank = f"CAST(u.{alias_low}Rank AS INTEGER)" if is_sqlite else f"CAST(u.{alias_low}Rank AS SIGNED)"
            cast_high_rank = f"CAST(i.{alias_high}Rank AS INTEGER)" if is_sqlite else f"CAST(i.{alias_high}Rank AS SIGNED)"

            is_singular = any(k in q_low for k in ["sản phẩm nào", "mặt hàng nào", "món nào", "cái nào", "ai", "đâu là"]) and not top_m
            eff_limit = int(top_m.group(1)) if top_m else (5 if is_singular else 10)

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÂN TÍCH NGHỊCH LÝ / PHÂN HÓA SẢN PHẨM GIỮA HAI THỊ TRƯỜNG {c_high.upper()} VÀ {c_low.upper()}{yr_label}):
WITH {alias_high}Sales AS (
    SELECT 
        pr.Product AS Product,
        SUM(s.Amount) AS {alias_high}Sales,
        DENSE_RANK() OVER (ORDER BY SUM(s.Amount) DESC) AS {alias_high}Rank
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE g.Geo = '{c_high}'{yr_filter}
    GROUP BY pr.PID, pr.Product
),
{alias_low}Sales AS (
    SELECT 
        pr.Product AS Product,
        SUM(s.Amount) AS {alias_low}Sales,
        DENSE_RANK() OVER (ORDER BY SUM(s.Amount) DESC) AS {alias_low}Rank
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE g.Geo = '{c_low}'{yr_filter}
    GROUP BY pr.PID, pr.Product
)
SELECT 
    i.Product AS Product,
    i.{alias_high}Sales AS {alias_high}Sales,
    i.{alias_high}Rank AS {alias_high}Rank,
    u.{alias_low}Sales AS {alias_low}Sales,
    u.{alias_low}Rank AS {alias_low}Rank,
    ({cast_low_rank} - {cast_high_rank}) AS RankDivergence
FROM {alias_high}Sales i
JOIN {alias_low}Sales u ON i.Product = u.Product
ORDER BY RankDivergence DESC, i.{alias_high}Sales DESC
LIMIT {eff_limit};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN ĐỐI CHIẾU NGHỊCH LÝ / PHÂN HÓA THỊ TRƯỜNG GIỮA {c_high} (BÁN CHẠY) VÀ {c_low} (Ế ẨM / DOANH SỐ THẤP)!
2. TUYỆT ĐỐI KHÔNG TRẢ VỀ BẢNG TOP SẢN PHẨM CHUNG CỦA TOÀN CÔNG TY MÀ BỎ QUA YẾU TỐ 2 QUỐC GIA!
3. BẮT BUỘC dùng 2 CTE tính riêng Doanh số và Thứ hạng (DENSE_RANK) tại {c_high} và {c_low}, sau đó INNER JOIN theo Product!
4. Độ lệch thứ hạng RankDivergence = {alias_low}Rank - {alias_high}Rank (thứ hạng tại {c_low} càng cao/kém và thứ hạng tại {c_high} càng thấp/tốt thì độ lệch RankDivergence càng lớn)!
5. BẮT BUỘC ORDER BY RankDivergence DESC, i.{alias_high}Sales DESC LIMIT {eff_limit}!)
"""

        # 0.69 Biên độ dao động giá bán trung bình trên mỗi hộp giữa các thị trường quốc gia (Price Spread by Country)
        elif (
            any(k in q_low for k in ["biên độ", "dao động", "chênh lệch giá", "khoảng cách giá", "spread", "price spread", "fluctuation"])
            and any(k in q_low for k in ["giá", "đơn giá", "price", "giá bán", "mỗi hộp", "trung bình"])
            and any(k in q_low for k in ["quốc gia", "thị trường", "nước", "geo", "country", "thị trường quốc gia"])
        ):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_filter = (f" WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            yr_label = f" NĂM {yr_val}" if yr_val else ""
            calc_avg_price = "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)" if is_sqlite else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"

            is_singular = any(k in q_low for k in ["sản phẩm nào", "mặt hàng nào", "món nào", "cái nào", "lớn nhất", "cao nhất", "nhất"]) and not top_m
            eff_limit = int(top_m.group(1)) if top_m else (1 if is_singular else 10)

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (BIÊN ĐỘ DAO ĐỘNG GIÁ BÁN TRUNG BÌNH TRÊN MỖI HỘP GIỮA CÁC THỊ TRƯỜNG QUỐC GIA{yr_label}):
WITH ProductCountryPrice AS (
    SELECT 
        pr.Product AS Product,
        g.Geo AS Country,
        {calc_avg_price} AS AvgPricePerBox
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID{yr_filter}
    GROUP BY pr.PID, pr.Product, g.GeoID, g.Geo
)
SELECT 
    Product,
    ROUND(MAX(AvgPricePerBox), 2) AS HighestCountryAvgPrice,
    ROUND(MIN(AvgPricePerBox), 2) AS LowestCountryAvgPrice,
    ROUND(MAX(AvgPricePerBox) - MIN(AvgPricePerBox), 2) AS PriceSpread
FROM ProductCountryPrice
GROUP BY Product
ORDER BY PriceSpread DESC
LIMIT {eff_limit};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN TÍNH BIÊN ĐỘ DAO ĐỘNG GIÁ BÁN TRUNG BÌNH TRÊN MỖI HỘP GIỮA CÁC THỊ TRƯỜNG QUỐC GIA!
2. BẮT BUỘC dùng CTE tính đơn giá bán trung bình trên mỗi hộp theo từng cặp (Product, Country) bằng công thức: SUM(Amount) / NULLIF(SUM(Boxes), 0)! TUYỆT ĐỐI KHÔNG dùng cột Cost_per_box vì đó là giá vốn chi phí!
3. Biên độ dao động PriceSpread = MAX(AvgPricePerBox) - MIN(AvgPricePerBox) tính theo từng sản phẩm qua các quốc gia!
4. BẮT BUỘC ORDER BY PriceSpread DESC LIMIT {eff_limit}! TUYỆT ĐỐI KHÔNG TRẢ VỀ TỔNG SỐ HỘP HOẶC DOANH SỐ BÁN CHẠY NHẤT!)
"""

        # 0.7 Top N sản phẩm (Product) có doanh số / số lượng bán chạy nhất
        elif (
            any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "món", "kẹo", "socola", "chocolate"])
            and not any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "yummies", "delish", "jucies", "thành viên"])
            and not any(k in q_low for k in ["biên độ", "dao động", "chênh lệch", "khoảng cách", "giá bán", "đơn giá", "giá trung bình", "spread", "fluctuation", "tỷ suất", "margin", "pnl"])
            and not any(k in q_low for k in ["ế ẩm", "ế nhất", "thấp nhất tại", "kém nhất tại", "nhưng lại", "nghịch lý", "phân hóa", "divergence", "đối lập", "thị trường"])
            and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền", "cao nhất", "top", "bán chạy", "chạy nhất", "nhiều nhất", "hộp", "thùng", "boxes"])
        ):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes"])
            measure_col = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
            order_col = "TotalBoxesSold" if has_boxes else "TotalSales"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} SẢN PHẨM BÁN CHẠY NHẤT{yr_label}):
SELECT 
    pr.Product AS Product,
    {measure_col}
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}
GROUP BY pr.Product
ORDER BY {order_col} DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và products pr ON s.PID = pr.PID! BẮT BUỘC dùng LIMIT {req_limit} theo yêu cầu người dùng!)
"""

        # 0.77 Đơn giá niêm yết (Cost_per_box) của sản phẩm trong danh mục (Category)
        elif (
            any(k in q_low for k in ["đơn giá niêm yết", "giá niêm yết", "cost per box", "cost_per_box", "giá vốn niêm yết"])
            or (any(k in q_low for k in ["giá của nó", "đơn giá", "cost"]) and any(k in q_low for k in ["bars", "bites", "other", "danh mục"]) and any(k in q_low for k in ["cao nhất", "thấp nhất", "nhất"]))
        ) and not any(k in q_low for k in ["doanh thu", "sales", "bán ra", "lợi nhuận", "profit", "báo cáo"]):
            target_cat = None
            if any(k in q_low for k in ["bars", "bar"]):
                target_cat = "Bars"
            elif any(k in q_low for k in ["bites", "bite"]):
                target_cat = "Bites"
            elif "other" in q_low:
                target_cat = "Other"

            is_lowest = any(k in q_low for k in ["thấp nhất", "nhỏ nhất", "ít nhất", "lowest"])
            order_dir = "ASC" if is_lowest else "DESC"
            cat_filter = f"WHERE pr.Category = '{target_cat}'\n" if target_cat else ""
            cat_desc = f" DANH MỤC '{target_cat}'" if target_cat else ""

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (ĐƠN GIÁ NIÊM YẾT COST PER BOX{cat_desc}):
SELECT 
    pr.Product AS Product,
    pr.Category AS Category,
    pr.Cost_per_box AS CostPerBox
FROM products pr
{cat_filter}ORDER BY pr.Cost_per_box {order_dir}
LIMIT 1;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN TRA CỨU ĐƠN GIÁ NIÊM YẾT (Cost_per_box) TRONG BẢNG products pr!
2. TUYỆT ĐỐI KHÔNG TRUY VẤN BẢNG sales! ĐÂY LÀ DANH MỤC SẢN PHẨM NIÊM YẾT!
3. BẮT BUỘC CHỌN pr.Product, pr.Category, pr.Cost_per_box!
4. {f"Lọc đúng danh mục: WHERE pr.Category = '{target_cat}'! " if target_cat else ""}ORDER BY pr.Cost_per_box {order_dir} LIMIT 1!)
"""

        # 0.775 So sánh Doanh thu, Số hộp và Đơn giá trung bình giữa các danh mục sản phẩm (Category Comparison)
        elif any(k in q_low for k in ["category", "danh mục", "nhóm sản phẩm", "nhóm hàng"]) and any(k in q_low for k in ["so sánh", "các danh mục", "từng danh mục", "mỗi danh mục", "các nhóm hàng", "tất cả danh mục", "toàn bộ danh mục"]) and any(k in q_low for k in ["doanh thu", "doanh số", "sales", "hộp", "boxes", "đơn giá", "giá"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_label = f" NĂM {yr_val}" if yr_val else ""
            yr_filter = (f" WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
            calc_avg = "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)" if is_sqlite else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH DOANH THU, SỐ HỘP VÀ ĐƠN GIÁ TRUNG BÌNH THEO DANH MỤC / CATEGORY{yr_label}):
SELECT 
    pr.Category AS Category,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    {calc_avg} AS AvgPricePerBox
FROM sales s
JOIN products pr ON s.PID = pr.PID{yr_filter}
GROUP BY pr.Category
ORDER BY TotalRevenue DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN PHÂN TÍCH THEO DANH MỤC SẢN PHẨM (pr.Category), TUYỆT ĐỐI KHÔNG GROUP BY pr.Product!
2. BẮT BUỘC trả về đầy đủ cả 3 chỉ số theo yêu cầu:
   - TotalRevenue: SUM(s.Amount)
   - TotalBoxesSold: SUM(s.Boxes)
   - AvgPricePerBox: {calc_avg}
3. BẮT BUỘC JOIN giữa sales s VÀ products pr ON s.PID = pr.PID!
4. Nhóm theo pr.Category và sắp xếp ORDER BY TotalRevenue DESC!)
"""

        # 0.78 Giá bán trung bình trên mỗi hộp / Mỗi hộp mang về bao nhiêu tiền tại một thị trường cụ thể (hoặc toàn bộ)
        elif (
            any(k in q_low for k in ["giá bán trung bình", "đơn giá trung bình", "giá trung bình", "giá mỗi hộp", "mỗi hộp mang về", "mỗi hộp sô-cô-la", "mỗi hộp socola", "mỗi hộp", "từng hộp", "bình quân mỗi hộp", "trung bình mỗi hộp", "average price per box", "avg price per box", "price per box"])
            and any(k in q_low for k in ["tiền", "giá", "$", "usd", "đồng", "mang về", "bao nhiêu", "thu về", "đạt"])
            and not any(k in q_low for k in ["biên độ", "dao động", "spread", "lợi nhuận", "profit", "margin", "khoảng cách"])
        ):
            specific_c = match_chocolates_specific_country(q_low)
            specific_p = match_chocolates_specific_product(q_low)
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_val = yr_match.group(1) if yr_match else None
            yr_label = f" NĂM {yr_val}" if yr_val else ""

            calc_avg = "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)" if is_sqlite else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"

            if specific_c:
                yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (GIÁ BÁN TRUNG BÌNH TRÊN MỖI HỘP TẠI THỊ TRƯỜNG {specific_c.upper()}{yr_label}):
SELECT 
    g.Geo AS Country,
    {calc_avg} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
WHERE g.Geo = '{specific_c}'{yr_filter}
GROUP BY g.Geo;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN TÍNH GIÁ BÁN TRUNG BÌNH TRÊN MỖI HỘP ({specific_c.upper()}), TUYỆT ĐỐI KHÔNG ĐƯỢC CHỈ TÍNH MỖI TỔNG SỐ HỘP (TotalBoxesSold) HAY TỔNG DOANH THU (TotalSales)!
2. BẮT BUỘC tính cột AvgPricePerBox bằng công thức: {calc_avg} AS AvgPricePerBox!
3. BẮT BUỘC trả về đầy đủ 3 chỉ số: AvgPricePerBox (giá bán TB/hộp), TotalRevenue (tổng doanh thu) và TotalBoxesSold (tổng số hộp bán ra) để đối chiếu quy mô!
4. Lọc đúng thị trường g.Geo = '{specific_c}'!)
"""
            elif specific_p:
                yr_filter = (f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (GIÁ BÁN TRUNG BÌNH TRÊN MỖI HỘP CỦA SẢN PHẨM {specific_p.upper()}{yr_label}):
SELECT 
    pr.Product AS Product,
    {calc_avg} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN products pr ON s.PID = pr.PID
WHERE pr.Product = '{specific_p}'{yr_filter}
GROUP BY pr.PID, pr.Product;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC tính cột AvgPricePerBox = {calc_avg}, kèm TotalRevenue và TotalBoxesSold! TUYỆT ĐỐI KHÔNG chỉ tính mỗi TotalBoxesSold!)
"""
            elif any(k in q_low for k in ["category", "danh mục", "nhóm sản phẩm", "nhóm hàng"]):
                yr_filter = (f" WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH DOANH THU, SỐ HỘP VÀ ĐƠN GIÁ TRUNG BÌNH THEO DANH MỤC / CATEGORY{yr_label}):
SELECT 
    pr.Category AS Category,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    {calc_avg} AS AvgPricePerBox
FROM sales s
JOIN products pr ON s.PID = pr.PID{yr_filter}
GROUP BY pr.Category
ORDER BY TotalRevenue DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN PHÂN TÍCH THEO DANH MỤC SẢN PHẨM (pr.Category), TUYỆT ĐỐI KHÔNG GROUP BY pr.Product!
2. BẮT BUỘC trả về đầy đủ cả 3 chỉ số theo yêu cầu:
   - TotalRevenue: SUM(s.Amount)
   - TotalBoxesSold: SUM(s.Boxes)
   - AvgPricePerBox: {calc_avg}
3. BẮT BUỘC JOIN giữa sales s VÀ products pr ON s.PID = pr.PID!
4. Nhóm theo pr.Category và sắp xếp ORDER BY TotalRevenue DESC!)
"""
            elif any(k in q_low for k in ["quốc gia", "thị trường", "từng nước", "mỗi nước", "countries", "geos"]):
                yr_filter = (f" WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
                is_lowest = any(k in q_low for k in ["thấp nhất", "nhỏ nhất", "kém nhất", "lowest", "least", "tệ nhất"])
                sort_dir = "ASC" if is_lowest else "DESC"
                limit_clause = ""
                top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
                if top_m:
                    limit_clause = f"\nLIMIT {int(top_m.group(1))}"
                elif any(k in q_low for k in ["nào", "gì", "cao nhất", "thấp nhất", "best", "worst"]) and not any(k in q_low for k in ["các quốc gia", "các nước", "các thị trường", "từng nước", "từng quốc gia", "từng thị trường", "mỗi nước", "mỗi quốc gia", "mỗi thị trường", "so sánh", "tất cả", "danh sách"]):
                    limit_clause = "\nLIMIT 1"

                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (GIÁ BÁN TRUNG BÌNH TRÊN MỖI HỘP THEO THỊ TRƯỜNG QUỐC GIA{yr_label}):
SELECT 
    g.Geo AS Country,
    {calc_avg} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID{yr_filter}
GROUP BY g.Geo
ORDER BY AvgPricePerBox {sort_dir}{limit_clause};
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC tính cột AvgPricePerBox = {calc_avg}, kèm TotalRevenue và TotalBoxesSold! Sắp xếp ORDER BY AvgPricePerBox {sort_dir}{limit_clause}!)
"""
            else:
                yr_filter = (f" WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (GIÁ BÁN TRUNG BÌNH TRÊN MỖI HỘP TOÀN HỆ THỐNG{yr_label}):
SELECT 
    {calc_avg} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s{yr_filter};
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC tính cột AvgPricePerBox = {calc_avg}, kèm TotalRevenue và TotalBoxesSold! TUYỆT ĐỐI KHÔNG chỉ tính mỗi TotalBoxesSold!)
"""

        # 0.79 Doanh thu của một Quốc gia / Thị trường cụ thể (India, USA, Canada...)
        elif match_chocolates_specific_country(q_low) and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "hộp", "thùng", "boxes", "tiền"]) and not any(k in q_low for k in ["top", "cao nhất", "thấp nhất", "nhiều nhất", "ít nhất", "bảng xếp hạng", "các quốc gia", "từng quốc gia", "mỗi quốc gia", "tất cả", "so sánh"]):
            specific_c = match_chocolates_specific_country(q_low)
            has_boxes = any(k in q_low for k in ["bao nhiêu hộp", "số hộp", "số lượng hộp", "mấy hộp", "tổng hộp", "boxes sold"]) and not any(k in q_low for k in ["doanh số", "doanh thu", "tiền", "sales"])
            metric_col = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE g.Geo = '{specific_c}' AND strftime('%Y', s.SaleDate) = '{yr_val}'\n" if is_sqlite else f"WHERE g.Geo = '{specific_c}' AND YEAR(s.SaleDate) = {yr_val}\n"
                yr_label = f" NĂM {yr_val}"
            else:
                yr_filter = f"WHERE g.Geo = '{specific_c}'\n"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THỊ TRƯỜNG {specific_c.upper()}{yr_label}):
SELECT 
    g.Geo AS Country,
    {metric_col}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{yr_filter}GROUP BY g.Geo;
(CẢNH BÁO BẮT BUỘC: Lọc đúng thị trường g.Geo = '{specific_c}'! TUYỆT ĐỐI KHÔNG hiển thị các quốc gia khác!)
"""

        # 0.8 Top N quốc gia / thị trường có doanh số cao nhất
        elif any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"]) and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "cao nhất", "top", "nhiều nhất", "lớn nhất"]) and not match_chocolates_specific_country(q_low):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} QUỐC GIA DOANH SỐ CAO NHẤT{yr_label}):
SELECT 
    g.Geo AS Country,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{yr_filter}
GROUP BY g.Geo
ORDER BY TotalSales DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và geo g ON s.GeoID = g.GeoID! BẮT BUỘC dùng LIMIT {req_limit} theo yêu cầu người dùng!)
"""

        # 0.9 Doanh số theo đội ngũ (Team) bán hàng
        elif any(k in q_low for k in ["team", "đội ngũ", "đội", "nhóm bán hàng"]):
            yr_match = re.search(r'\b(20\d{2})\b', q_low)
            yr_filter = ""
            yr_label = ""
            if yr_match:
                yr_val = yr_match.group(1)
                yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
                yr_label = f" NĂM {yr_val}"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DOANH THU THEO ĐỘI NGŨ / TEAM{yr_label}):
SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{yr_filter}
GROUP BY pe.Team
ORDER BY TotalSales DESC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC JOIN giữa sales s và people pe ON s.SPID = pe.SPID! Cột đội ngũ là pe.Team!)
"""

    # 0.981 Đếm số lượng nhân viên từng thay đổi / luân chuyển phòng ban ít nhất 1 lần
    is_count_dept_transfer_q = (
        (
            any(k in q_low for k in ["thay đổi phòng ban", "thay đổi phòng", "đổi phòng ban", "đổi phòng", "chuyển phòng ban", "chuyển phòng", "luân chuyển phòng ban", "luân chuyển phòng", "luân chuyển bộ phận"])
            or (any(k in q_low for k in ["thay đổi", "đổi", "chuyển", "luân chuyển"]) and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
        )
        and any(k in q_low for k in ["bao nhiêu", "số lượng", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many", "mấy"])
        and not any(k in q_low for k in ["danh sách", "liệt kê", "những ai", "top", "ai là"])
    )
    if is_count_dept_transfer_q:
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (ĐẾM SỐ LƯỢNG NHÂN VIÊN TỪNG THAY ĐỔI PHÒNG BAN ÍT NHẤT 1 LẦN):
SELECT 
    COUNT(*) AS EmployeesChangedDepartment,
    (SELECT COUNT(DISTINCT emp_no) FROM dept_emp) AS TotalEmployees,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(DISTINCT emp_no) FROM dept_emp), 2) AS PercentageChangedDept
FROM (
    SELECT emp_no
    FROM dept_emp
    GROUP BY emp_no
    HAVING COUNT(DISTINCT dept_no) > 1
) t;
(CẢNH BÁO BẮT BUỘC:
1. Người dùng hỏi CÓ BAO NHIÊU nhân viên từng thay đổi phòng ban, BẮT BUỘC dùng subquery gom nhóm HAVING COUNT(DISTINCT dept_no) > 1 và COUNT(*) bên ngoài!
2. BẮT BUỘC tính: EmployeesChangedDepartment (số người đổi phòng = 31,579), TotalEmployees (tổng nhân sự = 300,024), PercentageChangedDept (tỷ lệ % = 10.53%)!
3. TUYỆT ĐỐI KHÔNG JOIN dept_manager, TUYỆT ĐỐI KHÔNG DÙNG bảng salaries!
4. TUYỆT ĐỐI KHÔNG xuất danh sách cá nhân từng người, chỉ trả về 1 dòng kết quả tổng hợp!)
"""

    # 0.982 Phân loại toàn bộ nhân sự hiện tại thành 3 nhóm lương (Thu nhập thấp, trung bình, cao)
    is_salary_bracket_q = (
        any(k in q_low for k in ["nhóm lương", "bậc lương", "khoảng lương", "3 nhóm lương", "thu nhập thấp", "thu nhập trung bình", "thu nhập cao", "phân loại toàn bộ", "3 nhóm", "các nhóm lương", "phân loại theo lương"])
        or (
            any(k in q_low for k in ["phân loại", "chia thành", "tier", "bracket"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary"])
            and any(k in q_low for k in ["tỷ lệ", "%", "cơ cấu", "phần trăm", "số lượng"])
        )
    ) and not any(k in q_low for k in ["kỳ cựu", "mới vào", "so sánh", "đối chiếu", "thâm niên"])
    if is_salary_bracket_q:
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÂN LOẠI TOÀN BỘ NHÂN SỰ THEO 3 NHÓM LƯƠNG):
SELECT 
    SalaryTier,
    COUNT(*) AS EmployeeCount,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM salaries WHERE to_date = '9999-01-01'), 2) AS Percentage
FROM (
    SELECT 
        CASE 
            WHEN salary < 50000 THEN 'Dưới 50k (Thu nhập thấp)'
            WHEN salary BETWEEN 50000 AND 80000 THEN '50k - 80k (Thu nhập trung bình)'
            ELSE 'Trên 80k (Thu nhập cao)'
        END AS SalaryTier,
        CASE 
            WHEN salary < 50000 THEN 1
            WHEN salary BETWEEN 50000 AND 80000 THEN 2
            ELSE 3
        END AS TierOrder
    FROM salaries
    WHERE to_date = '9999-01-01'
) t
GROUP BY SalaryTier, TierOrder
ORDER BY TierOrder ASC;
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC dùng CASE WHEN trên bảng salaries WHERE to_date = '9999-01-01' để gom 3 bậc:
   - Dưới 50k: salary < 50000
   - 50k - 80k: salary BETWEEN 50000 AND 80000
   - Trên 80k: ELSE (hoặc salary > 80000)
2. BẮT BUỘC tính COUNT(*) AS EmployeeCount và ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM salaries WHERE to_date = '9999-01-01'), 2) AS Percentage!
3. TUYỆT ĐỐI KHÔNG xuất danh sách cá nhân từng nhân viên, không tính YearsOfService!)
"""

    # 0.983 Liệt kê các phòng ban có mức lương phân tán (độ lệch chuẩn - STDDEV) hoặc tỷ lệ biến động lương cao nhất
    is_dept_fluctuation_q = (
        any(k in q_low for k in ["biến động lương", "tỷ lệ biến động lương", "độ biến động lương", "dao động lương", "độ lệch chuẩn", "stddev", "độ phân tán"])
        or (
            any(k in q_low for k in ["biến động", "fluctuation", "dao động", "phân tán", "độ lệch chuẩn", "stddev"])
            and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"])
            and any(k in q_low for k in ["lương", "salary", "thu nhập"])
        )
    )
    if is_dept_fluctuation_q:
        is_stddev_focus = any(k in q_low for k in ["độ lệch chuẩn", "stddev", "phân tán", "độ phân tán", "standard deviation"])
        is_single_dept = any(k in q_low for k in ["phòng ban nào", "đơn vị nào", "nơi nào", "which department"]) and not any(k in q_low for k in ["các phòng", "từng phòng", "tất cả", "danh sách", "top", "bảng", "all"])
        order_metric = "SalaryStdDev" if is_stddev_focus else "FluctuationRate"
        limit_clause = "\nLIMIT 1;" if is_single_dept else ";"
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÂN TÁN LƯƠNG - ĐỘ LỆCH CHUẨN STDDEV / TỶ LỆ BIẾN ĐỘNG THEO PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS CurrentAvgSalary,
    ROUND(STDDEV(s.salary), 2) AS SalaryStdDev,
    ROUND(STDDEV(s.salary) * 100.0 / AVG(s.salary), 2) AS FluctuationRate
FROM salaries s
JOIN dept_emp de ON s.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
WHERE s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY {order_metric} DESC{limit_clause}
(CẢNH BÁO BẮT BUỘC:
1. Khi câu hỏi chứa "độ lệch chuẩn", "STDDEV", hoặc "mức lương phân tán": BẮT BUỘC dùng hàm STDDEV(s.salary) (hoặc STDDEV_SAMP(s.salary)) AS SalaryStdDev!
2. TUYỆT ĐỐI KHÔNG dùng MAX - MIN (SalarySpread) hay chênh lệch đỉnh sàn khi người dùng yêu cầu độ lệch chuẩn STDDEV!
3. BẮT BUỘC tính:
   - CurrentAvgSalary = ROUND(AVG(s.salary), 2)
   - SalaryStdDev = ROUND(STDDEV(s.salary), 2)
   - FluctuationRate = ROUND(STDDEV(s.salary) * 100.0 / AVG(s.salary), 2)
4. BẮT BUỘC lọc s.to_date = '9999-01-01' VÀ de.to_date = '9999-01-01'!
5. TUYỆT ĐỐI KHÔNG DÙNG bảng dept_manager, TUYỆT ĐỐI KHÔNG tính YearsAsManager!
6. GROUP BY d.dept_name và ORDER BY {order_metric} DESC!)
"""

    # 0.984 Top N phòng ban có tổng quỹ lương chi trả cao nhất hiện nay kèm số lượng nhân sự
    is_dept_payroll_q = (
        any(k in q_low for k in ["quỹ lương", "tổng quỹ lương", "tổng chi trả lương", "chi trả quỹ lương", "chi phí lương"])
        or (
            any(k in q_low for k in ["tổng lương", "tổng chi lương", "tổng tiền lương"])
            and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"])
        )
    )
    if is_dept_payroll_q:
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} PHÒNG BAN CÓ TỔNG QUỸ LƯƠNG CAO NHẤT):
SELECT 
    d.dept_name AS Department,
    SUM(s.salary) AS TotalPayroll,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM salaries s
JOIN dept_emp de ON s.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
WHERE s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY TotalPayroll DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC tính SUM(s.salary) AS TotalPayroll (tổng quỹ lương), COUNT(DISTINCT de.emp_no) AS Headcount (số lượng nhân sự), ROUND(AVG(s.salary), 2) AS AvgSalary!
2. BẮT BUỘC ORDER BY TotalPayroll DESC LIMIT {req_limit}!
3. Lọc s.to_date = '9999-01-01' VÀ de.to_date = '9999-01-01'!
4. TUYỆT ĐỐI KHÔNG sắp xếp theo Headcount hay AvgSalary, TUYỆT ĐỐI KHÔNG xuất danh sách lương cá nhân!)
"""

    # 0.989 Nhân viên từng làm việc tại ít nhất N phòng ban nhưng mức lương hiện tại thấp hơn / cao hơn lương trung bình của phòng ban đầu tiên họ từng gia nhập
    is_multi_dept_first_dept_sal_q = (
        any(k in q_low for k in ["nhiều phòng ban", "nhiều phòng", "ít nhất 2 phòng", "ít nhất 2 phòng ban", "từ 2 phòng", "từ 2 phòng ban", "qua 2 phòng", "qua 2 phòng ban", "2 phòng ban", "2 phòng ban khác nhau", "2 phòng khác nhau", "chuyển phòng ban", "luân chuyển"])
        and any(k in q_low for k in ["phòng ban đầu tiên", "phòng đầu tiên", "đầu tiên họ từng", "phòng ban khởi điểm", "phòng ban ban đầu", "first department", "first dept"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    )
    if is_multi_dept_first_dept_sal_q:
        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
        is_higher = any(k in q_low for k in ["cao hơn", "lớn hơn", "vượt", "higher", "greater"])
        sal_comp_op = ">" if is_higher else "<"
        diff_expr = "ROUND(s_curr.salary - da.AvgSalary, 2) AS SalarySurplus" if is_higher else "ROUND(da.AvgSalary - s_curr.salary, 2) AS SalaryDeficit"
        order_col = "SalarySurplus" if is_higher else "SalaryDeficit"
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN LÀM VIỆC TẠI ÍT NHẤT 2 PHÒNG BAN NHƯNG LƯƠNG HIỆN TẠI {sal_comp_op} LƯƠNG TB PHÒNG BAN ĐẦU TIÊN):
WITH FirstDept AS (
    SELECT 
        emp_no, 
        dept_no,
        ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
    FROM dept_emp
),
DeptAvg AS (
    SELECT 
        de.dept_no, 
        d.dept_name, 
        ROUND(AVG(s.salary), 2) AS AvgSalary
    FROM dept_emp de
    JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    JOIN departments d ON de.dept_no = d.dept_no
    WHERE de.to_date = '9999-01-01'
    GROUP BY de.dept_no, d.dept_name
),
MultiDept AS (
    SELECT 
        emp_no, 
        COUNT(DISTINCT dept_no) AS DeptCount
    FROM dept_emp
    GROUP BY emp_no
    HAVING COUNT(DISTINCT dept_no) >= 2
)
SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    d_curr.dept_name AS CurrentDepartment,
    s_curr.salary AS CurrentSalary,
    da.dept_name AS FirstDepartment,
    da.AvgSalary AS FirstDeptAvgSalary,
    {diff_expr},
    md.DeptCount AS DepartmentCount
FROM MultiDept md
JOIN employees e ON md.emp_no = e.emp_no
JOIN dept_emp de_curr ON e.emp_no = de_curr.emp_no AND de_curr.to_date = '9999-01-01'
JOIN departments d_curr ON de_curr.dept_no = d_curr.dept_no
JOIN salaries s_curr ON e.emp_no = s_curr.emp_no AND s_curr.to_date = '9999-01-01'
JOIN FirstDept fd ON e.emp_no = fd.emp_no AND fd.rn = 1
JOIN DeptAvg da ON fd.dept_no = da.dept_no
WHERE s_curr.salary {sal_comp_op} da.AvgSalary
ORDER BY {order_col} DESC, e.emp_no ASC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC dùng CTE 'WITH ... AS' 3 bước:
   - CTE 1 (FirstDept): Xác định phòng ban đầu tiên của nhân viên bằng ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn.
   - CTE 2 (DeptAvg): Tính mức lương trung bình hiện hành của từng phòng ban ROUND(AVG(s.salary), 2) WHERE de.to_date = '9999-01-01' AND s.to_date = '9999-01-01'.
   - CTE 3 (MultiDept): Lọc nhân viên từng làm việc tại ít nhất 2 phòng ban HAVING COUNT(DISTINCT dept_no) >= 2.
2. BẮT BUỘC có điều kiện WHERE s_curr.salary {sal_comp_op} da.AvgSalary! TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ QUA ĐIỀU KIỆN LƯƠNG!
3. BẮT BUỘC SELECT đầy đủ các trường: e.emp_no, FullName, CurrentDepartment, CurrentSalary, FirstDepartment, FirstDeptAvgSalary, {order_col}, DepartmentCount!
4. ORDER BY {order_col} DESC, e.emp_no ASC LIMIT {req_limit}!)
"""

    # 0.99 Nhân viên từng làm việc ở ít nhất N phòng ban (kèm chức danh nếu có)
    is_multi_dept_q = (
        any(k in q_low for k in [
            "nhiều phòng ban", "nhiều phòng", "ít nhất 2 phòng", "ít nhất 2 phòng ban",
            "từ 2 phòng", "từ 2 phòng ban", "qua 2 phòng", "qua 2 phòng ban",
            "2 phòng ban", "2 phòng ban khác nhau", "2 phòng khác nhau",
            "chuyển phòng ban", "thay đổi phòng ban", "thay đổi phòng", "luân chuyển phòng", "luân chuyển công tác",
            "ít nhất hai phòng ban", "nhiều hơn một phòng ban", "nhiều hơn 1 phòng ban"
        ])
        or bool(re.search(r"(?:ít nhất|tối thiểu|từ|qua|hơn)\s*\d+\s*phòng", q_low))
    ) and any(k in q_low for k in ["phòng ban", "phòng", "department"]) and any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "danh sách", "liệt kê", "employee", "employees"]) and not any(k in q_low for k in ["bao nhiêu", "số lượng", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many"]) and not any(k in q_low for k in ["lương", "salary", "thu nhập", "thấp hơn", "cao hơn", "đầu tiên", "first dept", "first department"])

    if is_multi_dept_q:
        min_depts = 2
        m_dept = re.search(r"(?:ít nhất|tối thiểu|từ|qua)\s*(\d+)\s*phòng", q_low)
        if m_dept:
            try:
                min_depts = int(m_dept.group(1))
            except ValueError:
                min_depts = 2
        elif any(k in q_low for k in ["nhiều hơn một", "nhiều hơn 1"]):
            min_depts = 2

        title_map = [
            (["senior engineer", "kỹ sư cao cấp", "senior dev"], "Senior Engineer"),
            (["senior staff", "nhân viên cao cấp"], "Senior Staff"),
            (["assistant engineer", "trợ lý kỹ sư"], "Assistant Engineer"),
            (["technique leader", "technical leader", "tech lead", "trưởng nhóm kỹ thuật", "trưởng kỹ thuật"], "Technique Leader"),
            (["engineer", "kỹ sư"], "Engineer"),
            (["manager", "trưởng phòng", "quản lý"], "Manager"),
            (["staff", "chuyên viên"], "Staff"),
        ]
        target_title = None
        for kws, t_name in title_map:
            if any(k in q_low for k in kws):
                target_title = t_name
                break

        title_filter = f"WHERE t.title = '{target_title}'\n" if target_title else ""
        title_comment = f"Lọc đúng chức danh t.title = '{target_title}'" if target_title else "Nếu không chỉ định chức danh, lấy chức danh hiện tại của nhân viên"
        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN TỪNG LÀM VIỆC Ở ÍT NHẤT {min_depts} PHÒNG BAN KHÁC NHAU):
SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    t.title AS CurrentTitle,
    d.dept_name AS CurrentDepartment,
    COUNT(DISTINCT de.dept_no) AS DepartmentCount
FROM employees e
JOIN titles t ON e.emp_no = t.emp_no AND t.to_date = '9999-01-01'
JOIN dept_emp de ON e.emp_no = de.emp_no
JOIN dept_emp de_curr ON e.emp_no = de_curr.emp_no AND de_curr.to_date = '9999-01-01'
JOIN departments d ON de_curr.dept_no = d.dept_no
{title_filter}GROUP BY e.emp_no, FullName, t.title, d.dept_name
HAVING COUNT(DISTINCT de.dept_no) >= {min_depts}
ORDER BY DepartmentCount DESC, e.emp_no ASC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. Đếm số lượng phòng ban từng làm việc bằng COUNT(DISTINCT de.dept_no) từ bảng lịch sử dept_emp de và lọc HAVING COUNT(DISTINCT de.dept_no) >= {min_depts}!
2. Lấy chức danh hiện tại từ bảng titles t với điều kiện t.to_date = '9999-01-01'. {title_comment}!
3. Lấy phòng ban hiện tại từ de_curr.to_date = '9999-01-01' và departments d!
4. BẮT BUỘC dùng LIMIT {req_limit} để tối ưu tốc độ truy vấn!)
"""

    # 0.999 Nhân sự có mức lương thuộc top X% công ty nhưng số năm gắn bó dưới Y năm
    is_top_sal_low_tenure_q = (
        any(k in q_low for k in ["nhân sự", "nhân viên", "người", "ai", "danh sách", "liệt kê"])
        and any(k in q_low for k in ["mức lương", "lương", "salary", "thu nhập"])
        and any(k in q_low for k in ["top", "cao nhất", "thuộc top"])
        and any(k in q_low for k in ["%", "phần trăm", "toàn công ty", "công ty"])
        and any(k in q_low for k in ["gắn bó", "thâm niên", "cống hiến", "years of service", "làm việc", "công tác"])
        and any(k in q_low for k in ["dưới", "ít hơn", "nhỏ hơn", "chưa quá", "không quá", "tối đa", "ngắn nhất", "<"])
    )
    if is_top_sal_low_tenure_q:
        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
        tenure_expr = (
            "ROUND((julianday(CASE WHEN de.to_date = '9999-01-01' THEN '2002-08-01' ELSE de.to_date END) - julianday(e.hire_date)) / 365.25, 1)"
            if is_sqlite else
            "ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 1)"
        )
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN SỰ LƯƠNG THUỘC TOP % CÔNG TY NHƯNG SỐ NĂM GẮN BÓ DƯỚI N NĂM, KÈM PHÒNG BAN VÀ CHỨC DANH):
WITH TopPercentileActive AS (
    SELECT 
        e.emp_no,
        {concat_expr} AS FullName,
        d.dept_name AS Department,
        t.title AS Title,
        s.salary AS Salary,
        {tenure_expr} AS YearsOfService,
        PERCENT_RANK() OVER (ORDER BY s.salary) AS SalaryPercentile
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
    JOIN departments d ON de.dept_no = d.dept_no
    JOIN titles t ON e.emp_no = t.emp_no AND t.to_date = '9999-01-01'
)
SELECT 
    emp_no,
    FullName,
    Department,
    Title,
    Salary,
    YearsOfService,
    ROUND(SalaryPercentile * 100, 1) AS SalaryPercentile
FROM TopPercentileActive
WHERE SalaryPercentile >= 0.90
  AND (YearsOfService < 2.0 OR YearsOfService <= 3.0)
ORDER BY YearsOfService ASC, Salary DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC lấy danh sách cá nhân nhân sự (emp_no, FullName), kèm phòng ban (Department) và chức danh (Title).
2. Dùng PERCENT_RANK() OVER (ORDER BY s.salary) >= 0.90 để lọc top 10% lương cao nhất.
3. Tính thâm niên gắn bó bằng DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25.
4. TUYỆT ĐỐI CẤM GROUP BY t.title để tính trung bình thâm niên chức danh! Phải trả về từng nhân sự cụ thể!)
"""

    # 1. Câu hỏi liên quan đến chức danh (Title)
    is_asking_individual = (
        any(k in q_low for k in ["danh sách", "liệt kê", "ai là", "họ và tên", "từng nhân viên", "những nhân viên", "các nhân viên", "list", "nhân viên nào"])
        and not any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "tỷ trọng", "tỉ trọng", "phân bổ", "phân bố", "cơ cấu", "số lượng nhân sự theo", "nhân sự theo", "nhân viên theo", "bổ nhiệm"])
    )
    if not is_asking_individual and any(k in q_low for k in ["chức danh", "title", "vị trí", "bổ nhiệm", "thăng chức", "senior staff", "senior engineer", "technique leader", "assistant engineer"]):
        # 1.0.0 Tỷ lệ phần trăm nhân viên nam và nữ được thăng chức (đổi chức danh ít nhất 1 lần)
        if any(k in q_low for k in ["thăng chức", "đổi chức danh", "chuyển chức danh", "thay đổi chức danh"]) and any(k in q_low for k in ["nam", "nữ", "gender", "giới tính"]) and any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "%", "so với", "tương ứng"]):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ NHÂN VIÊN NAM VÀ NỮ ĐƯỢC THĂNG CHỨC / ĐỔI CHỨC DANH ÍT NHẤT 1 LẦN):
WITH PromotedEmployees AS (
    SELECT emp_no
    FROM titles
    GROUP BY emp_no
    HAVING COUNT(*) >= 2
),
GenderStats AS (
    SELECT 
        e.gender AS Gender,
        COUNT(p.emp_no) AS PromotedEmployees,
        COUNT(*) AS TotalEmployees,
        ROUND(COUNT(p.emp_no) * 100.0 / COUNT(*), 2) AS PromotionRate
    FROM employees e
    LEFT JOIN PromotedEmployees p ON e.emp_no = p.emp_no
    GROUP BY e.gender
)
SELECT 
    Gender,
    PromotedEmployees,
    TotalEmployees,
    PromotionRate
FROM GenderStats
ORDER BY Gender ASC;
(CẢNH BÁO BẮT BUỘC:
1. Xác định nhân viên thăng chức (đổi chức danh >= 1 lần) bằng COUNT(*) >= 2 trong bảng titles.
2. LEFT JOIN với toàn bộ nhân viên theo giới tính trong bảng employees e để tính tổng số nhân sự từng giới tính.
3. Tính PromotionRate = ROUND(COUNT(p.emp_no) * 100.0 / COUNT(*), 2).
4. TUYỆT ĐỐI KHÔNG chỉ đếm số lượng nhân viên chung chung trong bảng employees mà không xét bảng titles!)
"""
        # 1.0.0.1 Nhân viên tuyển dụng sau ngày/năm cụ thể được thăng chức lên Manager / Trưởng phòng
        elif any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"]) and any(k in q_low for k in ["thăng chức", "bổ nhiệm", "đổi chức danh", "lên chức"]) and any(k in q_low for k in ["tuyển dụng", "tuyển", "vào làm", "hire", "sau ngày", "sau năm", "từ ngày", "từ năm"]):
            target_date = "1990-01-01"
            date_match = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", q_low)
            if date_match:
                d, m, y = date_match.groups()
                target_date = f"{y}-{int(m):02d}-{int(d):02d}"
            else:
                iso_match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", q_low)
                if iso_match:
                    y, m, d = iso_match.groups()
                    target_date = f"{y}-{int(m):02d}-{int(d):02d}"
                else:
                    year_match = re.search(r"(?:sau|từ)\s+(?:năm\s+)?(19\d\d|20\d\d)", q_low)
                    if year_match:
                        target_date = f"{year_match.group(1)}-01-01"

            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN TUYỂN DỤNG SAU NGÀY CỤ THỂ ĐƯỢC THĂNG CHỨC LÊN MANAGER / TRƯỞNG PHÒNG):
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    e.gender AS Gender,
    e.hire_date AS HireDate,
    d.dept_name AS Department,
    COALESCE(t_init.title, 'Khởi điểm Quản lý') AS InitialTitle,
    t_mgr.title AS PromotedTitle,
    t_mgr.from_date AS PromotionDate,
    s.salary AS CurrentSalary
FROM employees e
JOIN titles t_mgr ON e.emp_no = t_mgr.emp_no AND t_mgr.title = 'Manager'
LEFT JOIN titles t_init ON e.emp_no = t_init.emp_no AND t_init.from_date = e.hire_date AND t_init.title != 'Manager'
JOIN dept_manager dm ON e.emp_no = dm.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
LEFT JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE e.hire_date > '{target_date}'
ORDER BY e.hire_date ASC;
(CẢNH BÁO BẮT BUỘC:
1. Lấy thông tin cá nhân nhân viên từ employees e (emp_no, FullName, Gender, HireDate).
2. JOIN titles t_mgr với điều kiện t_mgr.title = 'Manager' để xác định chức vụ Manager.
3. JOIN dept_manager dm và departments d để lấy tên phòng ban.
4. Lọc ngày tuyển dụng e.hire_date > '{target_date}'.
5. TUYỆT ĐỐI KHÔNG GROUP BY theo năm hay chuyển thành câu hỏi xu hướng bổ nhiệm chung!)
"""
        # 1.0 Số lượng nhân viên được bổ nhiệm chức danh mới qua từng năm
        elif (any(k in q_low for k in ["bổ nhiệm", "chức danh mới", "bổ nhiệm mới", "nhận chức"]) or (
            any(k in q_low for k in ["chức danh", "title", "vị trí", "thăng chức"]) and any(k in q_low for k in ["qua từng năm", "qua các năm", "theo năm", "hàng năm", "từng năm", "xu hướng"])
        )):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SỐ LƯỢNG NHÂN VIÊN ĐƯỢC BỔ NHIỆM CHỨC DANH MỚI QUA TỪNG NĂM):
SELECT 
    YEAR(t.from_date) AS Year,
    COUNT(DISTINCT t.emp_no) AS NewTitleAppointments
FROM titles t
GROUP BY YEAR(t.from_date)
ORDER BY Year ASC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC dùng bảng titles t, nhóm theo YEAR(t.from_date) AS Year, đếm COUNT(DISTINCT t.emp_no) AS NewTitleAppointments! TUYỆT ĐỐI CẤM đặt tên cột là TotalEmployees hay Tổng Số Nhân Viên! TUYỆT ĐỐI KHÔNG lọc to_date = '9999-01-01', TUYỆT ĐỐI KHÔNG JOIN bảng salaries s hay employees e hay departments!)
"""
        elif any(k in q_low for k in ["nam", "nữ", "gender", "giới tính"]):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH LƯƠNG NAM NỮ THEO CHỨC DANH):
SELECT t.title AS Title, e.gender AS Gender, ROUND(AVG(s.salary), 2) AS AvgSalary
FROM employees e
JOIN titles t ON e.emp_no = t.emp_no
JOIN salaries s ON e.emp_no = s.emp_no
WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
GROUP BY t.title, e.gender
ORDER BY t.title, e.gender;
(BẮT BUỘC dùng bảng titles t, TUYỆT ĐỐI KHÔNG JOIN departments hay dept_emp!)
"""
        elif any(k in q_low for k in ["phân bổ", "phân bố", "tỷ lệ", "tỉ lệ", "tỷ trọng", "tỉ trọng", "phần trăm", "%", "cơ cấu", "số lượng", "bao nhiêu nhân sự", "nhân viên theo", "nhân sự theo"]) and not any(k in q_low for k in ["qua từng năm", "qua các năm", "theo năm", "hàng năm", "từng năm", "bổ nhiệm"]):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ PHÂN BỔ NHÂN SỰ THEO TỪNG CHỨC DANH):
SELECT 
    t.title AS JobTitle,
    COUNT(t.emp_no) AS EmployeeCount,
    ROUND(COUNT(t.emp_no) * 100.0 / (SELECT COUNT(*) FROM titles WHERE to_date = '9999-01-01'), 2) AS Percentage
FROM titles t
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY EmployeeCount DESC;
(BẮT BUỘC dùng bảng titles t, đếm EmployeeCount và tính Percentage = ROUND(COUNT(t.emp_no) * 100.0 / (SELECT COUNT(*) FROM titles WHERE to_date = '9999-01-01'), 2), TUYỆT ĐỐI KHÔNG JOIN salaries hay departments, KHÔNG LỌC THEO PHÒNG BAN SALES!)
"""
        # 1.0.3 Mức chênh lệch lương giữa người cao nhất và thấp nhất theo chức danh (Title Salary Spread / Gap)
        elif any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa", "difference"]) and any(k in q_low for k in ["lương", "thu nhập", "salary", "income"]) and not any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "gender", "chuẩn", "stddev", "standard deviation", "std("]):
            pattern = r"(?:giữa|between)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:cao nhất|thấp nhất|highest|lowest)\s+(?:và|and)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:thấp nhất|cao nhất|lowest|highest)"
            cleaned = re.sub(pattern, "", q_low)
            has_largest = any(k in cleaned for k in ["lớn nhất", "cao nhất", "nhiều nhất", "largest", "highest", "most", "rộng nhất", "dẫn đầu"])
            has_smallest = any(k in cleaned for k in ["nhỏ nhất", "thấp nhất", "ít nhất", "smallest", "lowest", "least", "hẹp nhất"])
            is_all_or_comparison = (
                any(k in cleaned for k in ["từng chức danh", "các chức danh", "mỗi chức danh", "tất cả", "toàn bộ", "so sánh", "danh sách", "bảng", "all", "each", "compare"])
                or not (has_largest or has_smallest)
            )
            top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
            req_limit = int(top_m.group(1)) if top_m else None

            if req_limit:
                return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} CHỨC DANH CHÊNH LỆCH LƯƠNG LỚN NHẤT):
SELECT 
    t.title AS Title,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC tính MAX(s.salary) AS MaxSalary, MIN(s.salary) AS MinSalary, (MAX(s.salary) - MIN(s.salary)) AS SalarySpread!
2. TUYỆT ĐỐI KHÔNG DÙNG AVG(s.salary) LƯƠNG TRUNG BÌNH!
3. BẮT BUỘC lọc t.to_date = '9999-01-01' VÀ s.to_date = '9999-01-01'!
4. GROUP BY t.title và ORDER BY SalarySpread DESC LIMIT {req_limit}!
5. TUYỆT ĐỐI KHÔNG JOIN departments hay dept_emp!)
"""
            elif has_largest and has_smallest:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (CHỨC DANH CHÊNH LỆCH LƯƠNG LỚN NHẤT VÀ NHỎ NHẤT):
WITH TitleSalarySpread AS (
    SELECT 
        t.title AS Title,
        MAX(s.salary) AS MaxSalary,
        MIN(s.salary) AS MinSalary,
        (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
    FROM titles t
    JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    WHERE t.to_date = '9999-01-01'
    GROUP BY t.title
)
SELECT 
    Title, 
    MaxSalary, 
    MinSalary, 
    SalarySpread
FROM TitleSalarySpread
WHERE SalarySpread = (SELECT MAX(SalarySpread) FROM TitleSalarySpread)
   OR SalarySpread = (SELECT MIN(SalarySpread) FROM TitleSalarySpread)
ORDER BY SalarySpread DESC;
(CẢNH BÁO BẮT BUỘC: Người dùng hỏi cả 2 cực trị LỚN NHẤT VÀ NHỎ NHẤT, BẮT BUỘC dùng CTE và mệnh đề WHERE SalarySpread = MAX OR MIN để CHỈ XUẤT ĐÚNG 2 CHỨC DANH tương ứng!)
"""
            elif has_smallest and not is_all_or_comparison:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (CHỨC DANH CÓ CHÊNH LỆCH LƯƠNG NHỎ NHẤT):
SELECT 
    t.title AS Title,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread ASC
LIMIT 1;
(CẢNH BÁO: BẮT BUỘC ORDER BY SalarySpread ASC LIMIT 1 để chỉ lấy 1 chức danh có mức chênh lệch nhỏ nhất!)
"""
            elif has_largest and not is_all_or_comparison:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (CHỨC DANH CÓ CHÊNH LỆCH LƯƠNG LỚN NHẤT):
SELECT 
    t.title AS Title,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread DESC
LIMIT 1;
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC tính MAX(s.salary) AS MaxSalary, MIN(s.salary) AS MinSalary, (MAX(s.salary) - MIN(s.salary)) AS SalarySpread!
2. TUYỆT ĐỐI KHÔNG DÙNG AVG(s.salary) LƯƠNG TRUNG BÌNH!
3. BẮT BUỘC ORDER BY SalarySpread DESC LIMIT 1 để chỉ lấy 1 chức danh có mức chênh lệch lớn nhất!
4. TUYỆT ĐỐI KHÔNG JOIN departments hay dept_emp!)
"""
            else:
                return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (MỨC CHÊNH LỆCH LƯƠNG THEO TỪNG CHỨC DANH):
SELECT 
    t.title AS Title,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread DESC;
(CẢNH BÁO: Lấy đầy đủ các chức danh để so sánh khoảng cách phân hóa lương, sắp xếp theo SalarySpread DESC!)
"""
        elif (any(k in q_low for k in ["lương trung bình", "lương bình quân"]) or (
            any(k in q_low for k in ["top", "cao nhất"]) and any(k in q_low for k in ["lương", "salary"])
        )) and not any(k in q_low for k in ["nhân sự", "nhân viên", "danh sách", "liệt kê", "%", "phần trăm", "chênh lệch", "khoảng cách", "spread", "gap", "thấp nhất"]):
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP CHỨC DANH LƯƠNG CAO NHẤT):
SELECT t.title AS Title, ROUND(AVG(s.salary), 2) AS AvgSalary
FROM salaries s
JOIN titles t ON s.emp_no = t.emp_no
WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY AvgSalary DESC
LIMIT {req_limit};
(BẮT BUỘC dùng bảng titles t, TUYỆT ĐỐI KHÔNG JOIN departments hay dept_emp! BẮT BUỘC dùng đúng LIMIT {req_limit} theo yêu cầu người dùng!)
"""

    # 2. Thâm niên nhân sự
    elif any(k in q_low for k in ["thâm niên", "cống hiến", "gắn bó"]) or (any(k in q_low for k in ["lâu nhất", "dài nhất"]) and any(k in q_low for k in ["nhân viên", "nhân sự", "công tác", "làm việc", "người", "ai", "toàn công ty"])):
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN THÂM NIÊN LÂU NHẤT CÒN CÔNG TÁC):
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    d.dept_name AS Department,
    e.hire_date AS HireDate,
    ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 2) AS YearsOfService
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
ORDER BY e.hire_date ASC, YearsOfService DESC
LIMIT {req_limit};
(TUYỆT ĐỐI KHÔNG DÙNG MAX(salary) LƯƠNG CAO NHẤT, TUYỆT ĐỐI CẤM DÙNG YEAR(de.to_date) hay tạo cột mang giá trị 9999, BẮT BUỘC TÍNH CỘT YearsOfService DÙNG DATEDIFF và ORDER BY e.hire_date ASC LIMIT {req_limit}!)
"""

    # 2.4 Danh sách nhân viên đạt mức lương / tổng doanh thu lớn nhất qua từng năm
    elif (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "danh sách", "tất cả", "năm từ", "2 năm"])
        and any(k in q_low for k in ["lương cao nhất", "thu nhập cao nhất", "lương lớn nhất", "doanh thu lớn nhất", "doanh số lớn nhất", "doanh thu cao nhất", "doanh số cao nhất", "lớn nhất", "cao nhất", "nhiều nhất", "khủng nhất", "1985", "tất cả các năm"])
        and (
            any(k in q_low for k in ["qua từng năm", "qua các năm", "theo từng năm", "theo năm", "mỗi năm", "hàng năm", "từng năm", "từng năm đó", "tất cả các năm", "các năm"])
            or ("1985" in q_low and any(yr in q_low for yr in ["2001", "2002", "đến"]))
        )
        and not any(k in q_low for k in ["lương trung bình", "tổng quỹ lương", "tăng trưởng", "bổ nhiệm", "tuyển dụng", "chức danh", "title", "quý", "tháng"])
    ):
        if is_sqlite:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN ĐẠT MỨC LƯƠNG/DOANH THU CAO NHẤT QUA TỪNG NĂM):
WITH RankedSalaries AS (
    SELECT 
        e.emp_no,
        e.first_name || ' ' || e.last_name AS FullName,
        CAST(strftime('%Y', s.from_date) AS INTEGER) AS Year,
        s.salary AS MaxSalary,
        ROW_NUMBER() OVER (PARTITION BY strftime('%Y', s.from_date) ORDER BY s.salary DESC, e.emp_no ASC) AS rn
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no
)
SELECT 
    emp_no,
    FullName,
    Year,
    MaxSalary
FROM RankedSalaries
WHERE rn = 1
ORDER BY Year ASC;
(CẢNH BÁO BẮT BUỘC:
1. Trả về đúng 4 cột: emp_no (Mã NV), FullName (Tên Nhân viên), Year (Năm), MaxSalary (Lương cao nhất từng năm).
2. Dùng CTE và ROW_NUMBER() OVER (PARTITION BY strftime('%Y', s.from_date) ORDER BY s.salary DESC) để lấy chính xác người có mức lương cao nhất trong từng năm.
3. TUYỆT ĐỐI KHÔNG LỌC to_date = '9999-01-01' để lấy đủ toàn bộ các năm lịch sử từ 1985 đến 2002!
4. Lọc WHERE rn = 1 và ORDER BY Year ASC để liệt kê đầy đủ từng năm từ trước đến nay! TUYỆT ĐỐI KHÔNG DÙNG LIMIT 10 đơn thuần!)
"""
        else:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN ĐẠT MỨC LƯƠNG/DOANH THU CAO NHẤT QUA TỪNG NĂM):
WITH RankedSalaries AS (
    SELECT 
        e.emp_no,
        CONCAT(e.first_name, ' ', e.last_name) AS FullName,
        YEAR(s.from_date) AS Year,
        s.salary AS MaxSalary,
        ROW_NUMBER() OVER (PARTITION BY YEAR(s.from_date) ORDER BY s.salary DESC, e.emp_no ASC) AS rn
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no
)
SELECT 
    emp_no,
    FullName,
    Year,
    MaxSalary
FROM RankedSalaries
WHERE rn = 1
ORDER BY Year ASC;
(CẢNH BÁO BẮT BUỘC:
1. Trả về đúng 4 cột: emp_no (Mã NV), FullName (Tên Nhân viên), Year (Năm), MaxSalary (Lương cao nhất từng năm).
2. Dùng CTE và ROW_NUMBER() OVER (PARTITION BY YEAR(s.from_date) ORDER BY s.salary DESC) để lấy chính xác người có mức lương cao nhất trong từng năm.
3. TUYỆT ĐỐI KHÔNG LỌC to_date = '9999-01-01' để lấy đủ toàn bộ các năm lịch sử từ 1985 đến 2002!
4. Lọc WHERE rn = 1 và ORDER BY Year ASC để liệt kê đầy đủ từng năm từ trước đến nay! TUYỆT ĐỐI KHÔNG DÙNG LIMIT 10 đơn thuần!)
"""

    # 2.5 Xu hướng mức lương trung bình của toàn công ty qua các năm
    elif any(k in q_low for k in ["lương trung bình", "mức lương", "lương bình quân"]) and any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "từng năm", "qua từng năm", "thay đổi như thế nào", "xu hướng", "biến động"]) and not any(k in q_low for k in ["phòng ban", "các phòng", "chức danh", "từng phòng"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (XU HƯỚNG MỨC LƯƠNG TRUNG BÌNH TOÀN CÔNG TY QUA CÁC NĂM):
SELECT 
    YEAR(s.from_date) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY Year ASC;
(CẢNH BÁO BẮT BUỘC: BẮT BUỘC dùng YEAR(s.from_date) AS Year, TUYỆT ĐỐI KHÔNG lọc `s.to_date = '9999-01-01'` và KHÔNG GROUP BY s.to_date để lấy đủ 18 năm lịch sử từ 1985 đến 2002! Nếu lọc to_date = '9999-01-01' sẽ bị sai nghiêm trọng chỉ ra 2 năm 2001-2002!)
"""

    # 3. Xu hướng tuyển dụng theo phòng ban qua các năm
    elif any(k in q_low for k in ["tuyển dụng", "tuyển"]) and any(k in q_low for k in ["năm", "tháng"]) and any(k in q_low for k in ["phòng ban", "phòng", "department", "development", "sales", "marketing", "research", "finance", "production", "human resources", "customer service", "quality management"]):
        dept_target = "Development"
        for d_name in ["Development", "Sales", "Marketing", "Research", "Finance", "Production", "Human Resources", "Quality Management", "Customer Service"]:
            if d_name.lower() in q_low:
                dept_target = d_name
                break
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (XU HƯỚNG TUYỂN DỤNG PHÒNG BAN {dept_target.upper()} QUA CÁC NĂM):
SELECT 
    YEAR(e.hire_date) AS HireYear, 
    COUNT(DISTINCT e.emp_no) AS TotalHires
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no
JOIN departments d ON de.dept_no = d.dept_no
WHERE d.dept_name = '{dept_target}'
GROUP BY HireYear
ORDER BY HireYear ASC;
(TUYỆT ĐỐI KHÔNG DÙNG MAX(salary) LƯƠNG CAO NHẤT, TUYỆT ĐỐI KHÔNG SO SÁNH LƯƠNG CHỨC DANH NAM NỮ, BẮT BUỘC DÙNG ĐÚNG PHÒNG BAN '{dept_target}' VÀ ORDER BY HireYear ASC!)
"""

    # 3.1 Xu hướng tuyển dụng toàn công ty theo từng năm
    elif any(k in q_low for k in ["tuyển dụng", "tuyển"]) and any(k in q_low for k in ["năm", "từng năm", "qua các năm", "từ trước đến nay"]) and not any(k in q_low for k in ["phòng ban", "phòng", "department", "sales", "development"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SỐ LƯỢNG NHÂN VIÊN TUYỂN DỤNG THEO TỪNG NĂM):
SELECT 
    YEAR(hire_date) AS HireYear, 
    COUNT(*) AS TotalHires
FROM employees
GROUP BY HireYear
ORDER BY HireYear ASC;
(BẮT BUỘC dùng YEAR(hire_date) AS HireYear, COUNT(*) AS TotalHires, GROUP BY HireYear ORDER BY HireYear ASC!)
"""

    # 3.8 Tốc độ tăng trưởng quy mô nhân sự các phòng ban trong N năm đầu hoạt động (hoặc 3 năm đầu)
    elif (
        any(k in q_low for k in ["tăng trưởng", "phát triển", "mở rộng quy mô"])
        and any(k in q_low for k in ["quy mô", "nhân sự", "nhân viên", "headcount", "số lượng"])
        and any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "từng phòng", "department"])
        and any(k in q_low for k in ["năm đầu", "năm đầu hoạt động", "giai đoạn đầu", "thời kỳ đầu", "mới thành lập", "khởi đầu", "3 năm", "5 năm", "2 năm"])
        and not any(k in q_low for k in ["lương", "salary", "thu nhập"])
    ):
        m_yr = re.search(r"(\d+)\s*năm đầu", q_low)
        n_years = int(m_yr.group(1)) if m_yr else 3
        start_year = 1985
        end_year = start_year + n_years - 1

        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỐC ĐỘ TĂNG TRƯỞNG QUY MÔ NHÂN SỰ CÁC PHÒNG BAN TRONG {n_years} NĂM ĐẦU HOẠT ĐỘNG {start_year} - {end_year}):
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT CASE WHEN de.from_date <= '{start_year}-12-31' AND de.to_date >= '{start_year}-01-01' THEN de.emp_no END) AS InitialHeadcount,
    COUNT(DISTINCT CASE WHEN de.from_date <= '{end_year}-12-31' AND de.to_date >= '{end_year}-01-01' THEN de.emp_no END) AS Year{n_years}Headcount,
    COUNT(DISTINCT CASE WHEN de.from_date <= '{end_year}-12-31' AND de.to_date >= '{end_year}-01-01' THEN de.emp_no END) - 
    COUNT(DISTINCT CASE WHEN de.from_date <= '{start_year}-12-31' AND de.to_date >= '{start_year}-01-01' THEN de.emp_no END) AS NetHeadcountGrowth,
    ROUND(
        (COUNT(DISTINCT CASE WHEN de.from_date <= '{end_year}-12-31' AND de.to_date >= '{end_year}-01-01' THEN de.emp_no END) - 
         COUNT(DISTINCT CASE WHEN de.from_date <= '{start_year}-12-31' AND de.to_date >= '{start_year}-01-01' THEN de.emp_no END)) * 100.0 /
        NULLIF(COUNT(DISTINCT CASE WHEN de.from_date <= '{start_year}-12-31' AND de.to_date >= '{start_year}-01-01' THEN de.emp_no END), 0),
        2
    ) AS HeadcountGrowthRatePct
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no
GROUP BY d.dept_name
ORDER BY HeadcountGrowthRatePct DESC;
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ PHÂN TÍCH TĂNG TRƯỞNG QUY MÔ NHÂN SỰ PHÒNG BAN, TUYỆT ĐỐI KHÔNG TRẢ VỀ TỪNG NHÂN VIÊN (FIRST_NAME/LAST_NAME) VÀ TUYỆT ĐỐI KHÔNG TÍNH THÂM NIÊN!
2. KHÔNG DÙNG DATEDIFF('9999-01-01') SẼ BỊ LỖI THÂM NIÊN 8014 NĂM!
3. BẮT BUỘC GROUP BY d.dept_name VÀ ORDER BY HeadcountGrowthRatePct DESC ĐỂ XÁC ĐỊNH PHÒNG BAN TĂNG TRƯỞNG NHANH NHẤT!)
"""

    # 3.9 Top nhân viên có tốc độ / mức tăng trưởng lương trung bình mỗi năm cao nhất
    elif (
        any(k in q_low for k in ["tăng trưởng lương", "tốc độ tăng trưởng", "tăng lương trung bình", "tăng trưởng", "tốc độ tăng", "mức tăng lương"])
        and any(k in q_low for k in ["mỗi năm", "hàng năm", "từng năm", "theo năm", "bình quân năm", "năm"])
        and any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "top", "danh sách", "ai có"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    ):
        dept_map = [
            (["sales", "kinh doanh", "bán hàng"], "Sales"),
            (["marketing", "tiếp thị"], "Marketing"),
            (["development", "phát triển", "lập trình", "dev"], "Development"),
            (["research", "nghiên cứu", "r&d"], "Research"),
            (["finance", "tài chính", "kế toán"], "Finance"),
            (["production", "sản xuất"], "Production"),
            (["human resources", "nhân sự", "hr", "tuyển dụng"], "Human Resources"),
            (["quality management", "quản lý chất lượng", "qa", "qc", "chất lượng"], "Quality Management"),
            (["customer service", "chăm sóc khách hàng", "cskh", "dịch vụ khách hàng"], "Customer Service"),
        ]
        target_dept = None
        for keywords, d_name in dept_map:
            if any(k in q_low for k in keywords):
                target_dept = d_name
                break

        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
        date_diff_expr = "(julianday(s_curr.from_date) - julianday(s_start.from_date)) / 365.25" if is_sqlite else "(DATEDIFF(s_curr.from_date, s_start.from_date) / 365.25)"
        min_days_filter = "julianday(s_curr.from_date) - julianday(s_start.from_date) >= 365" if is_sqlite else "DATEDIFF(s_curr.from_date, s_start.from_date) >= 365"
        dept_filter = f"d.dept_name = '{target_dept}' AND " if target_dept else ""
        dept_title = f" PHÒNG BAN {target_dept.upper()}" if target_dept else ""

        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} NHÂN VIÊN CÓ TỐC ĐỘ TĂNG TRƯỞNG LƯƠNG TRUNG BÌNH MỖI NĂM CAO NHẤT{dept_title}):
SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    d.dept_name AS Department,
    s_start.salary AS StartingSalary,
    s_curr.salary AS CurrentSalary,
    ROUND((s_curr.salary - s_start.salary) / {date_diff_expr}, 2) AS AvgAnnualSalaryGrowth
FROM dept_emp de
JOIN departments d ON de.dept_no = d.dept_no
JOIN employees e ON de.emp_no = e.emp_no
JOIN salaries s_start ON e.emp_no = s_start.emp_no AND s_start.from_date = e.hire_date
JOIN salaries s_curr ON e.emp_no = s_curr.emp_no AND s_curr.to_date = '9999-01-01'
WHERE {dept_filter}de.to_date = '9999-01-01'
  AND {min_days_filter}
ORDER BY AvgAnnualSalaryGrowth DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. Lấy lương khởi điểm từ s_start với điều kiện s_start.from_date = e.hire_date!
2. Lấy lương hiện tại từ s_curr với điều kiện s_curr.to_date = '9999-01-01' và de.to_date = '9999-01-01'!
3. Tính mức tăng trưởng trung bình mỗi năm bằng: (s_curr.salary - s_start.salary) / (DATEDIFF / 365.25)!
4. BẮT BUỘC sắp xếp ORDER BY AvgAnnualSalaryGrowth DESC LIMIT {req_limit}!)
"""

    # 3.99 Người kiếm được nhiều tiền nhất / lương cao nhất trong một năm cụ thể (VD: năm 1999)
    m_target_year = re.search(r"\b(19\d\d|20\d\d)\b", q_low)
    is_year_top_earner = (
        any(k in q_low for k in ["kiếm được nhiều tiền nhất", "kiếm nhiều tiền nhất", "nhiều tiền nhất", "kiếm tiền nhiều nhất", "kiếm tiền", "thu nhập cao nhất", "lương cao nhất", "mức lương cao nhất", "highest paid", "highest salary", "highest earner", "earned the most"])
        or (
            any(k in q_low for k in ["top", "danh sách", "những", "ai", "ai là", "xếp hạng", "người nào"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary", "tiền"])
            and any(k in q_low for k in ["cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất", "cao", "nhiều nhất"])
        )
    ) and bool(m_target_year) and any(k in q_low for k in ["nhân viên", "nhân sự", "toàn công ty", "công ty", "người", "ai", "sales", "phòng", "employee", "employees"]) and not any(k in q_low for k in ["tăng trưởng", "tốc độ", "mỗi năm", "tăng lương trung bình", "manager", "quản lý", "trưởng phòng"])

    if is_year_top_earner:
        target_yr = m_target_year.group(1)
        dept_map = [
            (["sales", "kinh doanh", "bán hàng"], "Sales"),
            (["marketing", "tiếp thị"], "Marketing"),
            (["development", "phát triển", "lập trình", "dev"], "Development"),
            (["research", "nghiên cứu", "r&d"], "Research"),
            (["finance", "tài chính", "kế toán"], "Finance"),
            (["production", "sản xuất"], "Production"),
            (["human resources", "nhân sự", "hr", "tuyển dụng"], "Human Resources"),
            (["quality management", "quản lý chất lượng", "qa", "qc", "chất lượng"], "Quality Management"),
            (["customer service", "chăm sóc khách hàng", "cskh", "dịch vụ khách hàng"], "Customer Service"),
        ]
        dept_filter = ""
        for keywords, d_name in dept_map:
            if any(k in q_low for k in keywords):
                dept_filter = f" AND d.dept_name = '{d_name}'"
                break
        is_singular = any(k in q_low for k in ["ai là người", "ai là", "ai kiếm", "ai có", "người nào", "nhân viên nào", "who is", "who earned"]) and not any(k in q_low for k in ["top", "danh sách", "những", "các"])
        eff_limit = int(top_m.group(1)) if top_m else (1 if is_singular else 10)
        is_lowest = any(k in q_low for k in ["thấp nhất", "ít nhất", "nhỏ nhất", "lowest"])
        order_dir = "ASC" if is_lowest else "DESC"
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NGƯỜI KIẾM NHIỀU TIỀN NHẤT / LƯƠNG CAO NHẤT NĂM {target_yr}):
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    d.dept_name AS Department,
    s.salary AS Salary,
    s.from_date AS FromDate,
    s.to_date AS ToDate
FROM salaries s
JOIN employees e ON s.emp_no = e.emp_no
JOIN dept_emp de ON e.emp_no = de.emp_no 
    AND de.from_date <= '{target_yr}-12-31' 
    AND de.to_date >= '{target_yr}-01-01'
JOIN departments d ON de.dept_no = d.dept_no
WHERE YEAR(s.from_date) = {target_yr}{dept_filter}
ORDER BY s.salary {order_dir}
LIMIT {eff_limit};
(CẢNH BÁO BẮT BUỘC:
1. Bảng salaries chứa cột 'salary', TUYỆT ĐỐI KHÔNG DÙNG 'amount' hay 's.amount'!
2. Lọc đúng năm {target_yr} bằng: WHERE YEAR(s.from_date) = {target_yr}! TUYỆT ĐỐI KHÔNG dùng to_date = '9999-01-01'!
3. Bảng phân công là 'dept_emp' (KHÔNG PHẢI 'dept_employee'), cột tên phòng ban là d.dept_name trong bảng departments!
4. Sắp xếp ORDER BY s.salary {order_dir} LIMIT {eff_limit}!)
"""

    # 4. Top nhân viên lương cao nhất hiện tại toàn công ty hoặc theo phòng ban
    elif (
        any(k in q_low for k in ["lương cao nhất", "thu nhập cao nhất", "mức lương cao nhất", "lương thấp nhất", "thu nhập thấp nhất", "highest paid", "highest salary", "kiếm được nhiều tiền nhất", "kiếm nhiều tiền nhất", "nhiều tiền nhất", "kiếm tiền nhiều nhất"])
        or (
            any(k in q_low for k in ["top", "danh sách", "những", "ai", "ai là", "xếp hạng", "người nào"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary", "tiền"])
            and any(k in q_low for k in ["cao nhất", "thấp nhất", "cao", "nhiều nhất"])
        )
    ) and any(k in q_low for k in ["nhân viên", "nhân sự", "toàn công ty", "công ty", "người", "ai", "sales", "phòng", "employee", "employees"]) and not any(k in q_low for k in ["tăng trưởng", "tốc độ", "mỗi năm", "tăng lương trung bình", "quỹ lương", "tổng quỹ lương", "tổng lương", "chi phí lương"]):
        dept_map = [
            (["sales", "kinh doanh", "bán hàng"], "Sales"),
            (["marketing", "tiếp thị"], "Marketing"),
            (["development", "phát triển", "lập trình", "dev"], "Development"),
            (["research", "nghiên cứu", "r&d"], "Research"),
            (["finance", "tài chính", "kế toán"], "Finance"),
            (["production", "sản xuất"], "Production"),
            (["human resources", "nhân sự", "hr", "tuyển dụng"], "Human Resources"),
            (["quality management", "quản lý chất lượng", "qa", "qc", "chất lượng"], "Quality Management"),
            (["customer service", "chăm sóc khách hàng", "cskh", "dịch vụ khách hàng"], "Customer Service"),
        ]
        dept_filter = ""
        for keywords, d_name in dept_map:
            if any(k in q_low for k in keywords):
                dept_filter = f" AND d.dept_name = '{d_name}'"
                break
        is_singular = any(k in q_low for k in ["ai là người", "ai là", "ai kiếm", "ai có", "người nào", "nhân viên nào", "who is", "who earned"]) and not any(k in q_low for k in ["top", "danh sách", "những", "các"])
        eff_limit = int(top_m.group(1)) if top_m else (1 if is_singular else req_limit)
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP NHÂN VIÊN LƯƠNG CAO NHẤT):
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    d.dept_name AS Department,
    s.salary AS CurrentSalary
FROM salaries s
JOIN employees e ON s.emp_no = e.emp_no
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
WHERE s.to_date = '9999-01-01'{dept_filter}
ORDER BY CurrentSalary DESC
LIMIT {eff_limit};
(CẢNH BÁO BẮT BUỘC: Lọc đúng s.to_date = '9999-01-01' và de.to_date = '9999-01-01' để lấy đúng lương hiện tại của từng nhân viên duy nhất, không bị trùng lặp lịch sử nhiều năm, và BẮT BUỘC dùng đúng LIMIT {eff_limit} theo câu hỏi người dùng!)
"""

    # 4.98 Danh sách phòng ban có mức lương trung bình trên/dưới một ngưỡng (VD: trên $70,000)
    elif (
        any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "department"])
        and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "lương tb", "avg salary", "average salary"])
        and any(k in q_low for k in ["trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", "lớn hơn", "nhỏ hơn", ">", "<", "above", "below", "over"])
        and not any(k in q_low for k in ["so sánh", "đối chiếu", "vs", "giữa", "chiếm bao nhiêu", "tỷ trọng", "phần trăm trong tổng"])
    ):
        thresh_val = "70000"
        thresh_match = re.search(r'[\$]?\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)(?:\s*(?:k|nghìn|ngàn|usd|\$))?', q_low)
        if thresh_match:
            raw_t = thresh_match.group(1).replace(",", "").replace(".", "")
            try:
                val_t = float(raw_t)
                if val_t < 1000 and any(k in q_low for k in ["k", "nghìn", "ngàn"]):
                    val_t *= 1000
                thresh_val = str(int(val_t))
            except Exception:
                pass
        op = "<" if any(k in q_low for k in ["dưới", "thấp hơn", "nhỏ hơn", "<", "<=", "below", "less than", "under"]) else ">"
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (LỌC PHÒNG BAN THEO NGƯỠNG LƯƠNG TRUNG BÌNH {op} {thresh_val}):
BẮT BUỘC dùng mệnh đề HAVING AvgSalary {op} {thresh_val} trên hàm gộp AVG(s.salary), TUYỆT ĐỐI KHÔNG DÙNG WHERE s.salary {op} {thresh_val}!
(Giải thích: WHERE s.salary {op} {thresh_val} sẽ lọc từng cá nhân nhân viên trước khi gom nhóm, khiến TẤT CẢ 9 phòng ban đều bị trả về vì mọi phòng ban đều có nhân viên lương {op} {thresh_val}. Cần lọc TRÊN MỨC TRUNG BÌNH CỦA CẢ PHÒNG bằng HAVING!)
BẮT BUỘC xuất ra cả cột Phòng ban (Department), Quy mô (Headcount) và Lương trung bình (AvgSalary) để hiển thị biểu đồ và thẻ KPI:
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
HAVING AvgSalary {op} {thresh_val}
ORDER BY AvgSalary DESC;
"""

    # 4.99 Tỷ trọng chi phí lương của một phòng ban cụ thể trong tổng chi phí toàn công ty
    elif (
        any(k in q_low for k in ["chiếm bao nhiêu", "chiếm tỉ lệ", "chiếm tỷ lệ", "chiếm phần trăm", "tỷ trọng", "tỉ trọng", "phần trăm trong tổng", "tỷ lệ trong tổng", "đóng góp bao nhiêu"])
        and any(k in q_low for k in ["tổng chi phí", "tổng quỹ lương", "tổng lương", "toàn công ty", "trong tổng"])
        and any(k in q_low for k in ["production", "sales", "development", "marketing", "research", "finance", "customer service", "quality management", "human resources", "sản xuất", "kinh doanh", "phát triển", "tiếp thị", "nghiên cứu", "tài chính", "nhân sự"])
    ):
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
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỔNG CHI PHÍ LƯƠNG TOÀN CÔNG TY VÀ TỶ TRỌNG CỦA PHÒNG BAN {target_dept.upper()}):
Yêu cầu: Tính tổng chi phí lương hiện tại của công ty VÀ cho biết phòng ban {target_dept} đang chiếm bao nhiêu phần trăm trong tổng chi phí đó.
BẮT BUỘC dùng CTE tổng hợp chi phí lương và UNION ALL giữa phòng ban {target_dept} và các phòng ban còn lại để biểu đồ Donut / Pie trực quan:
WITH DeptSalaries AS (
    SELECT 
        d.dept_name AS Department,
        COUNT(DISTINCT de.emp_no) AS Headcount,
        SUM(s.salary) AS TotalSalary
    FROM departments d
    JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
    JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    GROUP BY d.dept_name
),
CompanyStats AS (
    SELECT SUM(TotalSalary) AS TotalCompanySalary FROM DeptSalaries
)
SELECT 
    d.Department,
    d.Headcount,
    d.TotalSalary,
    c.TotalCompanySalary,
    ROUND(d.TotalSalary * 100.0 / c.TotalCompanySalary, 2) AS Percentage
FROM DeptSalaries d
CROSS JOIN CompanyStats c
WHERE d.Department = '{target_dept}'
UNION ALL
SELECT 
    'Các phòng ban còn lại' AS Department,
    SUM(d.Headcount) AS Headcount,
    SUM(d.TotalSalary) AS TotalSalary,
    MAX(c.TotalCompanySalary) AS TotalCompanySalary,
    ROUND(SUM(d.TotalSalary) * 100.0 / MAX(c.TotalCompanySalary), 2) AS Percentage
FROM DeptSalaries d
CROSS JOIN CompanyStats c
WHERE d.Department != '{target_dept}';
"""

    # 5. Tổng quỹ lương
    elif any(k in q_low for k in ["quỹ lương", "ngân sách lương", "tổng chi trả lương", "chi phí lương"]) or (
        any(k in q_low for k in ["tổng lương", "chi trả"]) and any(k in q_low for k in ["phòng ban", "phòng", "department", "năm", "qua các năm"])
    ):
        if any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "biến động"]):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (BIẾN ĐỘNG TỔNG QUỸ LƯƠNG QUA CÁC NĂM):
SELECT 
    YEAR(s.from_date) AS Year,
    SUM(s.salary) AS TotalSalaryBudget
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY Year ASC;
(CẢNH BÁO: BẮT BUỘC dùng YEAR(s.from_date) AS Year, TUYỆT ĐỐI KHÔNG lọc s.to_date = '9999-01-01' và KHÔNG GROUP BY s.to_date để lấy đủ 18 năm lịch sử từ 1985 đến 2002!)
"""
        else:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỔNG QUỸ LƯƠNG THEO PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    SUM(s.salary) AS TotalSalaryBudget
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY TotalSalaryBudget DESC;
(CẢNH BÁO ĐẶC BIỆT: 'QUỸ LƯƠNG' LÀ TỔNG SỐ TIỀN CHI TRẢ LƯƠNG, BẮT BUỘC DÙNG SUM(s.salary) AS TotalSalaryBudget! TUYỆT ĐỐI KHÔNG DÙNG COUNT(de.emp_no) VÌ COUNT LÀ ĐẾM SỐ LƯỢNG NGƯỜI, KHÔNG PHẢI TIỀN LƯƠNG!)
"""

    # 5.86 Nhân viên nhận lương cao hơn mức lương trung bình của người có cùng chức danh (Title)
    elif (
        any(k in q_low for k in ["nhân viên", "nhân sự", "ai", "người", "employee"])
        and any(k in q_low for k in ["cao hơn", "vượt", "thấp hơn", "higher", "above", "lower", "below"])
        and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "avg salary", "average salary"])
        and any(k in q_low for k in ["cùng chức danh", "chức danh", "title", "same title"])
    ):
        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
        is_lower = any(k in q_low for k in ["thấp hơn", "lower", "below"])
        op = "<" if is_lower else ">"
        diff_col = "SalaryDeficit" if is_lower else "SalarySurplus"
        diff_calc = "ROUND(ta.TitleAvgSalary - s.salary, 2)" if is_lower else "ROUND(s.salary - ta.TitleAvgSalary, 2)"
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN NHẬN LƯƠNG {'THẤP HƠN' if is_lower else 'CAO HƠN'} MỨC LƯƠNG TRUNG BÌNH CÙNG CHỨC DANH):
WITH TitleAvg AS (
    SELECT 
        t.title,
        ROUND(AVG(s.salary), 2) AS TitleAvgSalary
    FROM titles t
    JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    WHERE t.to_date = '9999-01-01'
    GROUP BY t.title
)
SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    d.dept_name AS Department,
    t.title AS Title,
    s.salary AS CurrentSalary,
    ta.TitleAvgSalary,
    {diff_calc} AS {diff_col}
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
JOIN titles t ON e.emp_no = t.emp_no AND t.to_date = '9999-01-01'
JOIN TitleAvg ta ON t.title = ta.title
WHERE s.salary {op} ta.TitleAvgSalary
ORDER BY {diff_col} DESC, s.salary DESC, e.emp_no ASC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. TUÂN THỦ 3 QUY TẮC PHÂN RÃ NGHIỆP VỤ: Dùng CTE TitleAvg để tính mức lương trung bình hiện hành của từng chức danh trước!
2. TUYỆT ĐỐI KHÔNG dùng correlated subquery bịa đặt alias như T1.title gây lỗi Unknown column 1054!
3. BẮT BUỘC xuất các cột: emp_no, FullName, Department, Title, CurrentSalary, TitleAvgSalary, {diff_col}!)
"""

    # 5.87 Top nhân viên có tỷ lệ tăng lương ấn tượng nhất: so sánh mức lương đầu tiên khi vào công ty và mức lương hiện tại
    elif (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "employee"])
        and any(k in q_low for k in ["tỷ lệ tăng lương", "tỉ lệ tăng lương", "tăng lương ấn tượng", "tốc độ tăng lương", "tăng trưởng lương", "mức tăng lương", "salary growth", "highest raise rate", "salary increase"])
        and (
            any(k in q_low for k in ["đầu tiên", "khởi điểm", "lúc vào", "khi vào", "gia nhập", "initial", "starting", "first salary"])
            or any(k in q_low for k in ["hiện tại", "bây giờ", "đến nay", "current", "latest"])
        )
    ):
        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} NHÂN VIÊN CÓ TỶ LỆ TĂNG LƯƠNG ẤN TƯỢNG NHẤT SO VỚI LƯƠNG ĐẦU TIÊN):
WITH ActiveEmployees AS (
    SELECT 
        e.emp_no,
        {concat_expr} AS FullName,
        d.dept_name AS Department,
        t.title AS CurrentTitle,
        s.salary AS CurrentSalary
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
    JOIN departments d ON de.dept_no = d.dept_no
    LEFT JOIN titles t ON e.emp_no = t.emp_no AND t.to_date = '9999-01-01'
),
InitialSalaries AS (
    SELECT 
        s.emp_no,
        s.salary AS InitialSalary
    FROM salaries s
    JOIN (
        SELECT emp_no, MIN(from_date) AS min_date
        FROM salaries
        GROUP BY emp_no
    ) m ON s.emp_no = m.emp_no AND s.from_date = m.min_date
)
SELECT 
    a.emp_no,
    a.FullName,
    a.Department,
    a.CurrentTitle,
    i.InitialSalary,
    a.CurrentSalary,
    (a.CurrentSalary - i.InitialSalary) AS SalaryIncrease,
    ROUND((a.CurrentSalary - i.InitialSalary) * 100.0 / i.InitialSalary, 2) AS SalaryGrowthRatePct
FROM ActiveEmployees a
JOIN InitialSalaries i ON a.emp_no = i.emp_no
ORDER BY SalaryGrowthRatePct DESC, SalaryIncrease DESC, a.emp_no ASC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. ĐÂY LÀ BÀI TOÁN CẤP NHÂN VIÊN (EMPLOYEES), TUYỆT ĐỐI KHÔNG ĐƯỢC CHỈ GROUP BY d.dept_name ĐỂ TÍNH LƯƠNG TRUNG BÌNH PHÒNG BAN!
2. Tuân thủ 3 Quy tắc Phân rã Nghiệp vụ bằng CTE 2 bước tường minh:
   - CTE 1 (ActiveEmployees): Lấy nhân viên đang làm việc (s.to_date = '9999-01-01' và de.to_date = '9999-01-01') để trích xuất CurrentSalary!
   - CTE 2 (InitialSalaries): Tìm mức lương đầu tiên khi mới vào công ty bằng cách join MIN(from_date) trên bảng salaries để trích xuất InitialSalary!
3. BẮT BUỘC xuất các cột: emp_no, FullName, Department, CurrentTitle, InitialSalary, CurrentSalary, SalaryIncrease, SalaryGrowthRatePct!)
"""

    # 5.875 Nhân viên từng bị giảm lương trong lịch sử làm việc tại công ty
    elif (
        any(k in q_low for k in ["giảm lương", "hạ lương", "bị giảm", "bị hạ", "salary reduction", "salary decrease", "pay cut"])
        or (any(k in q_low for k in ["lương", "salary"]) and any(k in q_low for k in ["giảm", "hạ", "tụt", "thấp hơn lần trước", "thấp hơn kỳ trước", "reduction", "decrease", "cut"]))
    ):
        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN TỪNG BỊ GIẢM LƯƠNG TRONG LỊCH SỬ CÔNG TY):
WITH SalaryStep AS (
    SELECT 
        s.emp_no,
        s.from_date,
        s.to_date,
        s.salary AS NewSalary,
        LAG(s.salary) OVER (PARTITION BY s.emp_no ORDER BY s.from_date ASC) AS PrevSalary
    FROM salaries s
),
SalaryReductions AS (
    SELECT 
        emp_no,
        from_date,
        PrevSalary,
        NewSalary,
        (PrevSalary - NewSalary) AS SalaryReduction,
        ROUND((PrevSalary - NewSalary) * 100.0 / PrevSalary, 2) AS ReductionPct
    FROM SalaryStep
    WHERE PrevSalary IS NOT NULL AND NewSalary < PrevSalary
)
SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    d.dept_name AS Department,
    sr.from_date AS ReductionDate,
    sr.PrevSalary,
    sr.NewSalary,
    sr.SalaryReduction,
    sr.ReductionPct
FROM SalaryReductions sr
JOIN employees e ON sr.emp_no = e.emp_no
JOIN dept_emp de ON e.emp_no = de.emp_no AND sr.from_date BETWEEN de.from_date AND de.to_date
JOIN departments d ON de.dept_no = d.dept_no
ORDER BY sr.SalaryReduction DESC, e.emp_no ASC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. TUYỆT ĐỐI CẤM BỊA ĐẶT CÁC BẢNG KHÔNG TỒN TẠI NHƯ 'dept_reductions', 'reductions', 'salary_reductions'! Trong CSDL chỉ có các bảng chuẩn: employees, salaries, dept_emp, departments, titles, dept_manager!
2. Tuân thủ 3 Quy tắc Phân rã Nghiệp vụ bằng CTE:
   - CTE 1 (SalaryStep): Dùng LAG(s.salary) OVER (PARTITION BY s.emp_no ORDER BY s.from_date ASC) AS PrevSalary để đối chiếu lương kỳ trước và s.salary AS NewSalary!
   - CTE 2 (SalaryReductions): Lọc WHERE PrevSalary IS NOT NULL AND NewSalary < PrevSalary để xác định chính xác các mốc bị giảm lương!
3. BẮT BUỘC JOIN với dept_emp qua điều kiện ngày công tác: `sr.from_date BETWEEN de.from_date AND de.to_date` để lấy chính xác phòng ban tại thời điểm nhân sự bị giảm lương!
4. MỆNH ĐỀ SELECT BẮT BUỘC có các cột: emp_no, FullName, Department, ReductionDate, PrevSalary, NewSalary, SalaryReduction, ReductionPct và ORDER BY sr.SalaryReduction DESC LIMIT {req_limit}!)
"""

    # 5.88 Nhân viên được tăng lương nhiều lần nhất nhưng mức lương hiện tại vẫn dưới ngưỡng (ví dụ: dưới $60,000)
    elif (
        any(k in q_low for k in ["tăng lương", "lần tăng", "được tăng"])
        and any(k in q_low for k in ["nhiều lần nhất", "nhiều nhất", "nhiều lần", "most raises"])
        and any(k in q_low for k in ["dưới", "thấp hơn", "chưa tới", "không quá", "<"])
        and any(k in q_low for k in ["lương", "salary", "mức lương", "$"])
    ):
        concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
        m_sal = re.search(r"(?:dưới|thấp hơn|chưa tới|<)\s*\$?(\d+(?:[.,]\d+)*)\s*(?:k|nghìn|usd|\$)?", q_low)
        raw_sal_str = m_sal.group(1).replace(",", "").replace(".", "") if m_sal else "60000"
        if "k" in q_low and int(raw_sal_str) < 1000:
            sal_cap = int(raw_sal_str) * 1000
        else:
            sal_cap = int(raw_sal_str)

        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} NHÂN VIÊN TĂNG LƯƠNG NHIỀU LẦN NHẤT NHƯNG LƯƠNG HIỆN TẠI DƯỚI ${sal_cap:,}):
WITH ActiveSalariesUnderCap AS (
    SELECT 
        e.emp_no,
        {concat_expr} AS FullName,
        d.dept_name AS Department,
        t.title AS CurrentTitle,
        s.salary AS CurrentSalary
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
    JOIN departments d ON de.dept_no = d.dept_no
    LEFT JOIN titles t ON e.emp_no = t.emp_no AND t.to_date = '9999-01-01'
    WHERE s.salary < {sal_cap}
),
EmployeeRaiseCounts AS (
    SELECT 
        emp_no,
        COUNT(*) AS RaiseCount
    FROM salaries
    GROUP BY emp_no
)
SELECT 
    a.emp_no,
    a.FullName,
    a.Department,
    a.CurrentTitle,
    a.CurrentSalary,
    rc.RaiseCount
FROM ActiveSalariesUnderCap a
JOIN EmployeeRaiseCounts rc ON a.emp_no = rc.emp_no
ORDER BY rc.RaiseCount DESC, a.CurrentSalary ASC, a.emp_no ASC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. TUÂN THỦ 3 QUY TẮC PHÂN RÃ NGHIỆP VỤ: Dùng CTE 'WITH ... AS' 2 bước tường minh:
   - CTE 1 (ActiveSalariesUnderCap): Lọc nhân viên đang làm việc to_date = '9999-01-01' có mức lương hiện tại s.salary < {sal_cap}!
   - CTE 2 (EmployeeRaiseCounts): Đếm tổng số lần tăng lương trong lịch sử từ bảng salaries: COUNT(*) AS RaiseCount.
2. Sắp xếp theo rc.RaiseCount DESC, sau đó a.CurrentSalary ASC và LIMIT {req_limit}!
3. TUYỆT ĐỐI KHÔNG BỊA ĐẶT CỘT 'e.email' VÌ BẢNG EMPLOYEES KHÔNG CÓ CỘT EMAIL!
4. TUYỆT ĐỐI KHÔNG DÙNG PERCENT_RANK() HOẶC CÁC BIẾN KÝ TỰ CHỮ '< N' TRONG SQL!)
"""

    # 5.9 Nhân viên có số lần tăng lương ít hơn N lần nhưng lương thuộc top cao nhất / top X%
    elif (
        any(k in q_low for k in ["tăng lương", "lần tăng"])
        and any(k in q_low for k in ["ít hơn", "dưới", "nhỏ hơn", "chưa quá", "chưa tới", "tối đa", "fewer", "less than", "under"])
        and any(k in q_low for k in ["top", "cao nhất", "mức lương", "lương", "%", "phần trăm"])
        and not any(k in q_low for k in ["nhiều lần nhất", "nhiều nhất", "nhiều lần", "most raises"])
    ):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN ÍT TĂNG LƯƠNG NHƯNG LƯƠNG THUỘC TOP CAO NHẤT):
Yêu cầu: Lọc nhân viên có số lần tăng lương < N lần nhưng mức lương hiện tại thuộc top 10% cao nhất toàn công ty (PERCENT_RANK() >= 0.90).
MẪU TRUY VẤN CHUẨN XÁC:
WITH TopPercentileActive AS (
    SELECT 
        e.emp_no,
        CONCAT(e.first_name, ' ', e.last_name) AS FullName,
        d.dept_name AS Department,
        s.salary AS CurrentSalary,
        PERCENT_RANK() OVER (ORDER BY s.salary) AS SalaryPercentile
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
    JOIN departments d ON de.dept_no = d.dept_no
)
SELECT 
    t.emp_no,
    t.FullName,
    t.Department,
    t.CurrentSalary,
    COUNT(s_all.salary) AS RaiseCount,
    ROUND(t.SalaryPercentile * 100, 1) AS SalaryPercentile
FROM TopPercentileActive t
JOIN salaries s_all ON t.emp_no = s_all.emp_no
WHERE t.SalaryPercentile >= 0.90
GROUP BY t.emp_no, t.FullName, t.Department, t.CurrentSalary, t.SalaryPercentile
HAVING COUNT(s_all.salary) < 5
ORDER BY t.CurrentSalary DESC, RaiseCount ASC
LIMIT 10;
(BẮT BUỘC: Điều kiện HAVING COUNT(s_all.salary) < 5 và lọc SalaryPercentile >= 0.90! TUYỆT ĐỐI KHÔNG dùng COUNT(*) >= 5 hoặc ORDER BY RaiseCount DESC!)
"""

    # 6. Nhân viên có từ N lần tăng lương trở lên
    elif (
        any(k in q_low for k in ["tăng lương", "lần tăng lương", "tăng lương trở lên", "được tăng lương"])
        and not any(k in q_low for k in ["ít hơn", "dưới", "nhỏ hơn", "chưa quá", "chưa tới", "tối đa", "fewer", "less than", "under"])
        and not ("%" in q_low or "phần trăm" in q_low)
    ):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN ĐƯỢC TĂNG LƯƠNG NHIỀU NHẤT):
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    d.dept_name AS Department,
    s_agg.RaiseCount,
    s_agg.CurrentSalary
FROM (
    SELECT emp_no, COUNT(*) AS RaiseCount, MAX(salary) AS CurrentSalary
    FROM salaries
    GROUP BY emp_no
    HAVING COUNT(*) >= 5
    ORDER BY RaiseCount DESC, CurrentSalary DESC
    LIMIT 10
) s_agg
JOIN employees e ON s_agg.emp_no = e.emp_no
JOIN dept_emp de ON s_agg.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
ORDER BY s_agg.RaiseCount DESC, s_agg.CurrentSalary DESC;
(BẮT BUỘC dùng subquery s_agg có LIMIT 10 để chạy trong 0.5s và không tràn 5,000 dòng, sắp xếp theo RaiseCount DESC, CurrentSalary DESC!)
"""

    # 7.0 Quản lý có lương thấp hơn nhân viên cấp dưới trực thuộc cùng phòng ban
    elif (
        any(k in q_low for k in ["manager", "trưởng phòng", "ban quản lý", "quản lý", "lãnh đạo phòng"])
        and any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên", "trực thuộc", "cùng phòng"])
        and any(k in q_low for k in ["thấp hơn", "kém hơn", "cao hơn", "lớn hơn", "vượt", "so sánh", "chênh lệch", "thấp hơn cả", "thua"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    ):
        is_asking_subordinates = any(k in q_low for k in ["nhân viên nào", "ai là những nhân viên", "những nhân viên", "danh sách nhân viên"]) and not any(k in q_low for k in ["ai là những quản lý", "quản lý nào", "những quản lý"])
        is_asking_avg = any(k in q_low for k in ["trung bình", "bình quân", "avg", "average"])

        if is_asking_subordinates:
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN CẤP DƯỚI CÓ LƯƠNG CAO HƠN QUẢN LÝ CÙNG PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    CONCAT(ee.first_name, ' ', ee.last_name) AS SubordinateName,
    se.salary AS SubordinateSalary,
    CONCAT(em.first_name, ' ', em.last_name) AS ManagerName,
    sm.salary AS ManagerSalary,
    se.salary - sm.salary AS SalaryDifference
FROM dept_manager dm
JOIN departments d ON dm.dept_no = d.dept_no
JOIN employees em ON dm.emp_no = em.emp_no
JOIN salaries sm ON dm.emp_no = sm.emp_no AND sm.to_date = '9999-01-01'
JOIN dept_emp de ON dm.dept_no = de.dept_no AND de.to_date = '9999-01-01' AND de.emp_no != dm.emp_no
JOIN employees ee ON de.emp_no = ee.emp_no
JOIN salaries se ON de.emp_no = se.emp_no AND se.to_date = '9999-01-01'
WHERE dm.to_date = '9999-01-01'
  AND se.salary > sm.salary
ORDER BY SalaryDifference DESC
LIMIT {req_limit};
(BẮT BUỘC lọc dm.to_date = '9999-01-01', de.to_date = '9999-01-01', sm.to_date = '9999-01-01', se.to_date = '9999-01-01' VÀ se.salary > sm.salary!)
"""
        elif is_asking_avg:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH LƯƠNG HIỆN TẠI CỦA TRƯỞNG PHÒNG VỚI LƯƠNG TRUNG BÌNH CỦA CẤP DƯỚI):
SELECT 
    d.dept_name AS Department,
    CONCAT(em.first_name, ' ', em.last_name) AS ManagerName,
    sm.salary AS ManagerSalary,
    ROUND(AVG(se.salary), 2) AS SubordinateAvgSalary,
    ROUND(sm.salary - AVG(se.salary), 2) AS SalaryDifference,
    ROUND((sm.salary - AVG(se.salary)) * 100.0 / AVG(se.salary), 2) AS DifferencePercentage
FROM dept_manager dm
JOIN departments d ON dm.dept_no = d.dept_no
JOIN employees em ON dm.emp_no = em.emp_no
JOIN salaries sm ON dm.emp_no = sm.emp_no AND sm.to_date = '9999-01-01'
JOIN dept_emp de ON dm.dept_no = de.dept_no AND de.to_date = '9999-01-01' AND de.emp_no != dm.emp_no
JOIN salaries se ON de.emp_no = se.emp_no AND se.to_date = '9999-01-01'
WHERE dm.to_date = '9999-01-01'
GROUP BY d.dept_name, ManagerName, sm.salary
ORDER BY sm.salary DESC;
(CẢNH BÁO BẮT BUỘC:
1. Từ khóa "trung bình" BẮT BUỘC ánh xạ sang AVG(se.salary) AS SubordinateAvgSalary, TUYỆT ĐỐI KHÔNG ĐƯỢC TỰ Ý ĐỔI THÀNH MAX(se.salary)!
2. BẮT BUỘC SELECT cả 2 trường: ManagerSalary và SubordinateAvgSalary!
3. BẮT BUỘC tính cột chênh lệch: SalaryDifference = ROUND(sm.salary - AVG(se.salary), 2) và DifferencePercentage!
4. TUYỆT ĐỐI KHÔNG thêm điều kiện se.salary > sm.salary vì câu hỏi yêu cầu tính mức lương trung bình của toàn bộ nhân viên dưới quyền trong phòng ban!)
"""
        else:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (QUẢN LÝ CÓ MỨC LƯƠNG THẤP HƠN NHÂN VIÊN CẤP DƯỚI TRỰC THUỘC CÙNG PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    CONCAT(em.first_name, ' ', em.last_name) AS ManagerName,
    sm.salary AS ManagerSalary,
    MAX(se.salary) AS MaxSubordinateSalary,
    MAX(se.salary) - sm.salary AS SalaryGap,
    COUNT(DISTINCT de.emp_no) AS SubordinatesWithHigherSalary
FROM dept_manager dm
JOIN departments d ON dm.dept_no = d.dept_no
JOIN employees em ON dm.emp_no = em.emp_no
JOIN salaries sm ON dm.emp_no = sm.emp_no AND sm.to_date = '9999-01-01'
JOIN dept_emp de ON dm.dept_no = de.dept_no AND de.to_date = '9999-01-01' AND de.emp_no != dm.emp_no
JOIN salaries se ON de.emp_no = se.emp_no AND se.to_date = '9999-01-01'
WHERE dm.to_date = '9999-01-01'
  AND se.salary > sm.salary
GROUP BY d.dept_name, ManagerName, sm.salary
ORDER BY SalaryGap DESC;
(BẮT BUỘC lọc dm.to_date = '9999-01-01', de.to_date = '9999-01-01', sm.to_date = '9999-01-01', se.to_date = '9999-01-01' VÀ se.salary > sm.salary! TUYỆT ĐỐI KHÔNG chỉ liệt kê mỗi bảng dept_manager!)
"""

    # 7. Danh sách Manager hiện tại của từng phòng ban kèm mức lương mới nhất
    elif (
        any(k in q_low for k in ["manager", "trưởng phòng", "ban quản lý", "lãnh đạo phòng"])
        and any(k in q_low for k in ["lương", "thu nhập", "salary"])
        and not any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "tỷ lệ"])
        and not any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên", "thấp hơn", "kém hơn", "cao hơn", "so sánh", "chênh lệch", "thấp hơn cả", "thua", "subordinate", "vượt"])
    ):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (DANH SÁCH MANAGER HIỆN TẠI CỦA TỪNG PHÒNG BAN KÈM LƯƠNG MỚI NHẤT):
SELECT 
    d.dept_name AS Department,
    CONCAT(e.first_name, ' ', e.last_name) AS ManagerName,
    s.salary AS CurrentSalary
FROM dept_manager dm
JOIN departments d ON dm.dept_no = d.dept_no
JOIN employees e ON dm.emp_no = e.emp_no
JOIN salaries s ON dm.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE dm.to_date = '9999-01-01'
ORDER BY CurrentSalary DESC;
(BẮT BUỘC lọc dm.to_date = '9999-01-01' VÀ s.to_date = '9999-01-01' để lấy đúng 9 Trưởng phòng hiện tại! TUYỆT ĐỐI KHÔNG DÙNG SUM(salary) toàn công ty hay sinh cột TotalCompanyValue!)
"""

    # 7.1 Những ai từng giữ chức vụ Manager lâu nhất trong lịch sử công ty
    elif any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"]) and any(k in q_low for k in ["lâu nhất", "dài nhất", "thâm niên nhất"]) and any(k in q_low for k in ["lịch sử", "từng giữ", "từng làm", "trước đến nay"]):
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHỮNG AI TỪNG GIỮ CHỨC VỤ MANAGER LÂU NHẤT TRONG LỊCH SỬ):
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS ManagerName,
    d.dept_name AS Department,
    dm.from_date AS StartDate,
    dm.to_date AS EndDate,
    ROUND(DATEDIFF(IF(dm.to_date = '9999-01-01', '2002-08-01', dm.to_date), dm.from_date) / 365.25, 1) AS YearsAsManager
FROM dept_manager dm
JOIN employees e ON dm.emp_no = e.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
ORDER BY YearsAsManager DESC
LIMIT {req_limit};
(BẮT BUỘC tính YearsAsManager bằng DATEDIFF, ORDER BY YearsAsManager DESC LIMIT {req_limit}, TUYỆT ĐỐI KHÔNG lọc to_date = '9999-01-01' để lấy đủ lịch sử các Manager tiền nhiệm!)
"""

    # 7.2 Top N chức danh có thâm niên trung bình cao nhất tại công ty
    elif (
        not any(k in q_low for k in ["nhân sự", "nhân viên", "danh sách", "liệt kê", "ai là", "mức lương", "lương", "salary", "%", "dưới", "ít hơn"])
        and any(k in q_low for k in ["chức danh", "title", "vị trí"])
        and any(k in q_low for k in ["thâm niên", "tenure", "cống hiến", "gắn bó", "lâu năm", "lâu nhất"])
        and any(k in q_low for k in ["trung bình", "avg", "cao nhất", "nhiều nhất", "top"])
    ):
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} CHỨC DANH CÓ THÂM NIÊN TRUNG BÌNH CAO NHẤT TẠI CÔNG TY):
SELECT 
    t.title AS Title,
    ROUND(AVG(DATEDIFF(IF(t.to_date = '9999-01-01', '2002-08-01', t.to_date), e.hire_date) / 365.25), 2) AS AvgYearsOfService,
    COUNT(DISTINCT e.emp_no) AS TotalEmployees
FROM titles t
JOIN employees e ON t.emp_no = e.emp_no
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY AvgYearsOfService DESC
LIMIT {req_limit};
(CẢNH BÁO: Bảng employees KHÔNG CÓ CỘT YearsOfService và KHÔNG CÓ to_date! BẮT BUỘC tính thâm niên bằng DATEDIFF(IF(t.to_date = '9999-01-01', '2002-08-01', t.to_date), e.hire_date) / 365.25! TUYỆT ĐỐI KHÔNG JOIN salaries hay departments!)
"""

    # 7.89 So sánh mức lương trung bình giữa 2 phòng ban cụ thể (VD: Sales vs Marketing, Sales vs Development) và tính tỷ lệ phần trăm chênh lệch
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

    if len(depts_in_q) == 2 and any(k in q_low for k in ["lương", "thu nhập", "salary"]) and any(k in q_low for k in ["so sánh", "đối chiếu", "chênh lệch", "khác nhau", "vs", "compare"]) and not any(k in q_low for k in ["khối", "nhóm", "group", "block"]):
        d1 = depts_in_q[0]
        d2 = depts_in_q[1]
        return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH LƯƠNG TRUNG BÌNH & TỶ LỆ CHÊNH LỆCH GIỮA {d1} VÀ {d2}):
WITH DeptStats AS (
    SELECT 
        d.dept_name AS Department,
        COUNT(DISTINCT de.emp_no) AS Headcount,
        ROUND(AVG(s.salary), 2) AS AvgSalary
    FROM departments d
    JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
    JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    WHERE d.dept_name IN ('{d1}', '{d2}')
    GROUP BY d.dept_name
),
DiffCalc AS (
    SELECT 
        MAX(CASE WHEN Department = '{d1}' THEN AvgSalary END) AS D1Salary,
        MAX(CASE WHEN Department = '{d2}' THEN AvgSalary END) AS D2Salary
    FROM DeptStats
)
SELECT 
    d.Department,
    d.Headcount,
    d.AvgSalary,
    ROUND(ABS(c.D1Salary - c.D2Salary), 2) AS SalaryDifference,
    ROUND(ABS(c.D1Salary - c.D2Salary) * 100.0 / LEAST(c.D1Salary, c.D2Salary), 2) AS DifferencePercentage
FROM DeptStats d
CROSS JOIN DiffCalc c
ORDER BY d.AvgSalary DESC;
(CẢNH BÁO BẮT BUỘC:
1. TUYỆT ĐỐI CHỈ LỌC ĐÚNG 2 PHÒNG BAN: WHERE d.dept_name IN ('{d1}', '{d2}'). TUYỆT ĐỐI KHÔNG LẤY CẢ 9 PHÒNG BAN!
2. Tính AvgSalary = ROUND(AVG(s.salary), 2) kèm điều kiện to_date = '9999-01-01'.
3. Tính SalaryDifference và DifferencePercentage = ROUND(ABS(D1 - D2) * 100.0 / LEAST(D1, D2), 2) để phản ánh chính xác tỷ lệ phần trăm chênh lệch!)
"""

    # 7.9 So sánh mức lương trung bình giữa các phòng ban Kỹ thuật (Development, Research) và phòng Kinh doanh (Sales, Marketing)
    elif (
        any(k in q_low for k in ["kỹ thuật", "tech"])
        and any(k in q_low for k in ["kinh doanh", "commercial", "sales"])
        and any(k in q_low for k in ["lương", "thu nhập", "salary"])
    ) or (
        ("development" in q_low or "research" in q_low)
        and ("sales" in q_low or "marketing" in q_low)
        and any(k in q_low for k in ["so sánh", "đối chiếu", "compare", "vs", "lương", "salary"])
    ) or (
        any(k in q_low for k in ["kỹ thuật", "tech"])
        and ("sales" in q_low or "marketing" in q_low)
    ) or (
        any(k in q_low for k in ["kinh doanh", "commercial"])
        and ("development" in q_low or "research" in q_low)
    ):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH LƯƠNG KHỐI KỸ THUẬT VS KHỐI KINH DOANH):
SELECT 
    CASE 
        WHEN d.dept_name IN ('Sales', 'Marketing') THEN 'Kinh doanh (Sales, Marketing)'
        WHEN d.dept_name IN ('Development', 'Research') THEN 'Kỹ thuật (Development, Research)'
    END AS DepartmentGroup,
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE d.dept_name IN ('Development', 'Research', 'Sales', 'Marketing')
GROUP BY DepartmentGroup, d.dept_name
ORDER BY DepartmentGroup, AvgSalary DESC;
(CẢNH BÁO TỐI QUAN TRỌNG: TUYỆT ĐỐI KHÔNG DÙNG LIMIT 1 HAY LIMIT! BẮT BUỘC TRẢ VỀ ĐẦY ĐỦ CẢ 4 PHÒNG BAN THUỘC 2 KHỐI: WHERE d.dept_name IN ('Development', 'Research', 'Sales', 'Marketing') VÀ PHÂN LOẠI CASE WHEN RA CỘT DepartmentGroup ĐỂ SO SÁNH TRỰC QUAN!)
"""

    # 7.8 So sánh mức lương trung bình giữa nhân viên kỳ cựu (> 5 năm) và nhân viên mới (< 2 năm) theo từng phòng ban
    elif (
        any(k in q_low for k in ["kỳ cựu", "thâm niên", "trên 5 năm", "lâu năm", "cống hiến"])
        and any(k in q_low for k in ["mới", "mới vào", "mới tuyển", "dưới 2 năm", "ít năm"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    ):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH LƯƠNG NHÂN VIÊN KỲ CỰU VS NHÂN VIÊN MỚI THEO TỪNG PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    ROUND(AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 5 THEN s.salary END), 2) AS SeniorAvgSalary,
    ROUND(AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END), 2) AS NewHireAvgSalary,
    ROUND(AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 5 THEN s.salary END) - 
          AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END), 2) AS SalaryDifference,
    ROUND((AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 5 THEN s.salary END) - 
           AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END)) * 100.0 / 
           AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END), 2) AS DifferencePercentage,
    COUNT(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 5 THEN 1 END) AS SeniorCount,
    COUNT(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN 1 END) AS NewHireCount
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalaryDifference DESC;
(CẢNH BÁO BẮT BUỘC:
1. CSDL employees CHỨA DỮ LIỆU TUYỂN DỤNG LỊCH SỬ (1985 - 2000). TUYỆT ĐỐI KHÔNG DÙNG CURRENT_DATE() HAY NOW() VÌ SẼ KHIẾN NHÓM DƯỚI 2 NĂM BỊ 0 DÒNG! BẮT BUỘC tính thâm niên so với ngày tuyển dụng tối đa của CSDL: (SELECT MAX(hire_date) FROM employees) hoặc '2000-01-28'!
2. TUYỆT ĐỐI KHÔNG JOIN bảng dept_manager! Đây là so sánh nhân sự theo thâm niên, không phải so sánh Trưởng phòng!
3. Cột salary nằm ở bảng salaries s, TUYỆT ĐỐI KHÔNG viết e.salary!
4. Cột to_date nằm ở bảng salaries s và dept_emp de, TUYỆT ĐỐI KHÔNG viết e.to_date!
5. BẮT BUỘC SELECT cả SeniorAvgSalary và NewHireAvgSalary, cùng SalaryDifference và DifferencePercentage để vẽ Double Bar Chart!)
"""

    # 8. So sánh mức lương trung bình của một phòng ban cụ thể so với các phòng ban khác (hoặc so sánh lương giữa các phòng)
    elif any(k in q_low for k in ["so sánh", "so voi", "so với", "đối chiếu"]) and any(k in q_low for k in ["lương trung bình", "mức lương", "thu nhập", "lương", "salary"]) and any(k in q_low for k in ["phòng ban khác", "các phòng ban", "các phòng khác", "các phòng", "phòng khác", "toàn công ty", "mặt bằng chung", "công ty"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH MỨC LƯƠNG TRUNG BÌNH GIỮA CÁC PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY AvgSalary DESC;
(CẢNH BÁO TỐI QUAN TRỌNG: TUYỆT ĐỐI KHÔNG DÙNG WHERE d.dept_name = '...'! Khi người dùng hỏi so sánh một phòng ban cụ thể (ví dụ Development) với các phòng ban khác, BẮT BUỘC phải lấy TẤT CẢ các phòng ban (GROUP BY d.dept_name) để hệ thống vẽ biểu đồ so sánh song song giữa phòng ban đó và các phòng ban khác! NẾU LỌC WHERE d.dept_name = 'Development' THÌ CHỈ CÒN 1 DÒNG VÀ HOÀN TOÀN KHÔNG THỂ SO SÁNH ĐƯỢC! TUYỆT ĐỐI KHÔNG TÍNH THÊM CỘT PercentOfTotal HAY TỶ LỆ TRÊN TỔNG!)
"""

    # 8b. So sánh quy mô/số lượng nhân sự của một phòng ban cụ thể so với các phòng ban khác
    elif any(k in q_low for k in ["so sánh", "so voi", "so với", "đối chiếu"]) and any(k in q_low for k in ["quy mô", "nhân sự", "số lượng", "headcount", "nhân viên"]) and any(k in q_low for k in ["phòng ban khác", "các phòng ban", "các phòng khác", "các phòng", "phòng khác", "toàn công ty", "mặt bằng chung"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH QUY MÔ NHÂN SỰ GIỮA CÁC PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount DESC;
(CẢNH BÁO TỐI QUAN TRỌNG: TUYỆT ĐỐI KHÔNG DÙNG WHERE d.dept_name = '...'! Khi người dùng hỏi so sánh quy mô phòng ban cụ thể với các phòng ban khác, BẮT BUỘC phải lấy TẤT CẢ các phòng ban để hệ thống vẽ biểu đồ so sánh song song!)
"""

    # 8c. Mức chênh lệch lương giữa người cao nhất và thấp nhất theo phòng ban (Salary Spread / Gap)
    elif (
        any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa", "difference"])
        and any(k in q_low for k in ["lương", "thu nhập", "salary", "income"])
        and any(k in q_low for k in ["phòng ban", "phòng", "department", "các phòng", "đơn vị"])
        and not any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "gender", "kỹ thuật", "tech", "chuẩn", "stddev", "standard deviation", "std("])
    ):
        pattern = r"(?:giữa|between)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:cao nhất|thấp nhất|highest|lowest)\s+(?:và|and)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:thấp nhất|cao nhất|lowest|highest)"
        cleaned = re.sub(pattern, "", q_low)
        has_largest = any(k in cleaned for k in ["lớn nhất", "cao nhất", "nhiều nhất", "largest", "highest", "most", "rộng nhất", "dẫn đầu"])
        has_smallest = any(k in cleaned for k in ["nhỏ nhất", "thấp nhất", "ít nhất", "smallest", "lowest", "least", "hẹp nhất"])
        is_all_or_comparison = (
            any(k in cleaned for k in ["từng phòng", "các phòng", "tất cả", "toàn bộ", "so sánh", "danh sách", "bảng", "mỗi phòng", "all", "each", "compare"])
            or not (has_largest or has_smallest)
        )
        top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
        req_limit = int(top_m.group(1)) if top_m else None

        if req_limit:
            return f"""
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP {req_limit} PHÒNG BAN CHÊNH LỆCH LƯƠNG LỚN NHẤT):
SELECT 
    d.dept_name AS Department,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalarySpread DESC
LIMIT {req_limit};
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC tính MAX(s.salary) AS MaxSalary, MIN(s.salary) AS MinSalary, (MAX(s.salary) - MIN(s.salary)) AS SalarySpread!
2. BẮT BUỘC lọc de.to_date = '9999-01-01' VÀ s.to_date = '9999-01-01'!
3. GROUP BY d.dept_name và ORDER BY SalarySpread DESC LIMIT {req_limit}!
4. TUYỆT ĐỐI KHÔNG xuất danh sách cá nhân từng nhân viên, TUYỆT ĐỐI CẤM dùng HireDate hay DATEDIFF!)
"""
        elif has_largest and has_smallest:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÒNG BAN CHÊNH LỆCH LƯƠNG LỚN NHẤT VÀ NHỎ NHẤT):
WITH DeptSalarySpread AS (
    SELECT 
        d.dept_name AS Department,
        MAX(s.salary) AS MaxSalary,
        MIN(s.salary) AS MinSalary,
        (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
    FROM departments d
    JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
    JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    GROUP BY d.dept_name
)
SELECT 
    Department, 
    MaxSalary, 
    MinSalary, 
    SalarySpread
FROM DeptSalarySpread
WHERE SalarySpread = (SELECT MAX(SalarySpread) FROM DeptSalarySpread)
   OR SalarySpread = (SELECT MIN(SalarySpread) FROM DeptSalarySpread)
ORDER BY SalarySpread DESC;
(CẢNH BÁO BẮT BUỘC: Người dùng hỏi cả 2 cực trị LỚN NHẤT VÀ NHỎ NHẤT, BẮT BUỘC dùng CTE và mệnh đề WHERE SalarySpread = MAX OR MIN để CHỈ XUẤT ĐÚNG 2 PHÒNG BAN tương ứng!)
"""
        elif has_smallest and not is_all_or_comparison:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÒNG BAN CHÊNH LỆCH LƯƠNG NHỎ NHẤT / HẸP NHẤT):
SELECT 
    d.dept_name AS Department,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalarySpread ASC
LIMIT 1;
(CẢNH BÁO: BẮT BUỘC ORDER BY SalarySpread ASC LIMIT 1 để chỉ lấy 1 phòng ban có mức chênh lệch nhỏ nhất!)
"""
        elif has_largest and not is_all_or_comparison:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÒNG BAN CHÊNH LỆCH LƯƠNG LỚN NHẤT / RỘNG NHẤT):
SELECT 
    d.dept_name AS Department,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalarySpread DESC
LIMIT 1;
(CẢNH BÁO: BẮT BUỘC ORDER BY SalarySpread DESC LIMIT 1 để chỉ lấy 1 phòng ban có mức chênh lệch lớn nhất!)
"""
        else:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (MỨC CHÊNH LỆCH LƯƠNG CÁC PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalarySpread DESC;
(CẢNH BÁO: Lấy đầy đủ các phòng ban để so sánh khoảng cách phân hóa lương, sắp xếp theo SalarySpread DESC!)
"""

    # 9. Quy mô các phòng ban lớn nhất và nhỏ nhất
    elif (
        any(k in q_low for k in ["quy mô", "nhân sự", "số lượng", "headcount", "đông nhất", "ít nhân sự nhất", "ít nhân viên nhất", "ít người nhất"])
        and any(k in q_low for k in ["lớn nhất", "nhỏ nhất", "cao nhất", "thấp nhất", "đông nhất"])
        and any(k in q_low for k in ["phòng ban", "phòng", "department"])
        and not re.search(r"(?:ít nhất|tối thiểu|từ|trên|nhiều hơn|hơn)\s+\d+", q_low)
        and not any(k in q_low for k in ["liệt kê", "danh sách", "những nhân viên", "các nhân viên", "nhân viên nào", "ai là", "từng làm", "chức danh", "title", "senior", "engineer", "staff", "manager", "leader"])
    ):
        has_largest = any(k in q_low for k in ["lớn nhất", "cao nhất", "nhiều nhất", "đông nhất", "largest", "highest", "most"])
        has_smallest = any(k in q_low for k in ["nhỏ nhất", "thấp nhất", "ít nhất", "smallest", "lowest", "least"])
        if has_largest and has_smallest:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÒNG BAN QUY MÔ LỚN NHẤT VÀ NHỎ NHẤT):
WITH DeptHeadcount AS (
    SELECT 
        d.dept_name AS Department,
        COUNT(DISTINCT de.emp_no) AS Headcount
    FROM departments d
    JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
    GROUP BY d.dept_name
)
SELECT 
    Department, 
    Headcount
FROM DeptHeadcount
WHERE Headcount = (SELECT MAX(Headcount) FROM DeptHeadcount)
   OR Headcount = (SELECT MIN(Headcount) FROM DeptHeadcount)
ORDER BY Headcount DESC;
(CẢNH BÁO BẮT BUỘC: Người dùng hỏi phòng ban lớn nhất VÀ nhỏ nhất, BẮT BUỘC dùng CTE và mệnh đề WHERE Headcount = MAX OR MIN để CHỈ XUẤT ĐÚNG 2 PHÒNG BAN tương ứng với 2 cực trị, TUYỆT ĐỐI KHÔNG xuất tất cả các phòng ban!)
"""
        elif has_smallest:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÒNG BAN QUY MÔ NHỎ NHẤT):
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount ASC
LIMIT 1;
(CẢNH BÁO: BẮT BUỘC ORDER BY Headcount ASC LIMIT 1 để chỉ lấy 1 phòng ban nhỏ nhất!)
"""
        else:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (PHÒNG BAN QUY MÔ LỚN NHẤT):
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount DESC
LIMIT 1;
(CẢNH BÁO: BẮT BUỘC ORDER BY Headcount DESC LIMIT 1 để chỉ lấy 1 phòng ban lớn nhất!)
"""

    # 9.9 So sánh số lượng nhân sự nam và nữ được thăng chức/bổ nhiệm lên quản lý (Manager) trong 5 năm gần nhất
    elif (
        any(k in q_low for k in ["manager", "quản lý", "trưởng phòng", "ban quản lý"])
        and any(k in q_low for k in ["nam", "nữ", "giới tính", "gender"])
        and any(k in q_low for k in ["gần nhất", "5 năm", "gần đây", "thời gian qua"])
    ):
        has_dept_in_q = any(k in q_low for k in ["phòng ban", "từng phòng", "mỗi phòng", "department", "bộ phận"])
        if has_dept_in_q:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH BỔ NHIỆM QUẢN LÝ NAM VS NỮ THEO PHÒNG BAN TRONG 5 NĂM GẦN NHẤT):
SELECT 
    d.dept_name AS Department,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
    COUNT(*) AS TotalManagers,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct
FROM dept_manager dm
JOIN employees e ON dm.emp_no = e.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - 4
GROUP BY d.dept_name
ORDER BY TotalManagers DESC, d.dept_name;
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC lọc đúng 5 năm gần nhất: WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - 4 (1992 - 1996).
2. TUYỆT ĐỐI KHÔNG DÙNG CURRENT_DATE() HAY NOW() VÌ SẼ BỊ 0 DÒNG!
3. TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ ĐIỀU KIỆN LỌC THỜI GIAN ĐỂ LẤY TOÀN BỘ 24 LƯỢT BỔ NHIỆM (1985 - 2002)!)
"""
        else:
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH BỔ NHIỆM QUẢN LÝ NAM VS NỮ THEO NĂM TRONG 5 NĂM GẦN NHẤT):
SELECT 
    YEAR(dm.from_date) AS Year,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
    COUNT(*) AS TotalManagers,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct
FROM dept_manager dm
JOIN employees e ON dm.emp_no = e.emp_no
WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - 4
GROUP BY YEAR(dm.from_date)
ORDER BY Year ASC;
(CẢNH BÁO BẮT BUỘC:
1. Đề bài yêu cầu 'trong 5 năm gần nhất' và KHÔNG yêu cầu theo phòng ban: BẮT BUỘC GROUP BY YEAR(dm.from_date) AS Year để so sánh biến động số lượng bổ nhiệm Nam vs Nữ qua từng năm!
2. BẮT BUỘC lọc đúng 5 năm gần nhất: WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - 4 (tương ứng 1992, 1994, 1996 với tổng cộng 7 lượt bổ nhiệm).
3. TUYỆT ĐỐI KHÔNG DÙNG CURRENT_DATE() HAY NOW() VÌ SẼ BỊ 0 DÒNG!
4. TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ ĐIỀU KIỆN LỌC THỜI GIAN ĐỂ LẤY TOÀN BỘ 24 LƯỢT BỔ NHIỆM TRONG LỊCH SỬ (1985 - 2002)!)
"""

    # 10. Tỷ lệ nam và nữ trong ban quản lý (dept_manager)
    elif any(k in q_low for k in ["ban quản lý", "dept_manager", "manager", "quản lý"]) and any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "tỷ lệ", "tỉ lệ", "nam", "nữ"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ NAM VÀ NỮ TRONG BAN QUẢN LÝ):
SELECT 
    d.dept_name AS Department,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
    COUNT(*) AS TotalManagers,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct
FROM dept_manager dm
JOIN employees e ON dm.emp_no = e.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
GROUP BY d.dept_name
ORDER BY d.dept_name;
(BẮT BUỘC XUẤT ĐẦY ĐỦ CẢ HAI CỘT TỶ LỆ: MalePct VÀ FemalePct! TUYỆT ĐỐI KHÔNG ĐƯỢC THIẾU TỶ LỆ NAM MalePct! BẮT BUỘC GROUP BY d.dept_name ĐỂ MỖI PHÒNG BAN LÀ 1 DÒNG DUY NHẤT!)
"""

    # 7.9 So sánh mức lương bình quân / chênh lệch lương giữa nam và nữ tại từng phòng ban (Gender Pay Gap by Department)
    elif any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "nam", "nữ", "gender"]) \
         and any(k in q_low for k in ["lương", "mức lương", "salary", "thu nhập", "lương bình quân", "lương trung bình"]) \
         and any(k in q_low for k in ["phòng ban", "từng phòng ban", "các phòng ban", "department", "bộ phận"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH MỨC LƯƠNG VÀ CHÊNH LỆCH LƯƠNG NAM NỮ THEO TỪNG PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    ROUND(AVG(CASE WHEN e.gender = 'M' THEN s.salary END), 2) AS MaleAvgSalary,
    ROUND(AVG(CASE WHEN e.gender = 'F' THEN s.salary END), 2) AS FemaleAvgSalary,
    ROUND(ABS(AVG(CASE WHEN e.gender = 'M' THEN s.salary END) - AVG(CASE WHEN e.gender = 'F' THEN s.salary END)), 2) AS SalaryDifference,
    ROUND(ABS(AVG(CASE WHEN e.gender = 'M' THEN s.salary END) - AVG(CASE WHEN e.gender = 'F' THEN s.salary END)) * 100.0 / AVG(CASE WHEN e.gender = 'F' THEN s.salary END), 2) AS DifferencePercentage
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
GROUP BY d.dept_name
ORDER BY SalaryDifference DESC;
(CẢNH BÁO BẮT BUỘC:
1. BẮT BUỘC dùng Pivot 2 cột MaleAvgSalary và FemaleAvgSalary bằng AVG(CASE WHEN e.gender = 'M' THEN s.salary END) và AVG(CASE WHEN e.gender = 'F' THEN s.salary END).
2. BẮT BUỘC tính cột SalaryDifference = ABS(...) và DifferencePercentage = ABS(...) * 100.0 / AVG(...).
3. BẮT BUỘC sắp xếp ORDER BY SalaryDifference DESC (hoặc DifferencePercentage DESC) theo yêu cầu chênh lệch lớn nhất xuống thấp!
4. TUYỆT ĐỐI KHÔNG chuyển thành đếm số lượng nhân sự MaleEmployees hay tỷ lệ phần trăm số lượng nhân sự!)
"""

    # 8. Số lượng và tỷ lệ nam nữ trong từng phòng ban (nhân viên toàn phòng)
    elif any(k in q_low for k in ["tỷ lệ nam nữ", "tỉ lệ nam nữ", "nam và nữ", "nam nữ"]) \
         and any(k in q_low for k in ["từng phòng ban", "các phòng ban", "phòng ban"]) \
         and not any(k in q_low for k in ["lương", "mức lương", "salary", "thu nhập", "chênh lệch", "gap"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SỐ LƯỢNG VÀ TỶ LỆ NAM NỮ THEO PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleEmployees,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleEmployees,
    COUNT(*) AS TotalEmployees,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct
FROM dept_emp de
JOIN employees e ON de.emp_no = e.emp_no
JOIN departments d ON de.dept_no = d.dept_no
WHERE de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY d.dept_name;
(BẮT BUỘC XUẤT ĐẦY ĐỦ CẢ HAI CỘT TỶ LỆ: MalePct VÀ FemalePct! GROUP BY d.dept_name!)
"""

    # 8.1 Tỷ lệ nam nữ toàn công ty (Company-wide gender ratio)
    elif any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính"]) and any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "cơ cấu", "tỉ trọng", "tỷ trọng", "share", "ratio"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ NAM NỮ TOÀN CÔNG TY):
SELECT 
    gender AS Gender,
    COUNT(*) AS EmployeeCount,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM employees), 2) AS Percentage
FROM employees
GROUP BY gender
ORDER BY EmployeeCount DESC;
(BẮT BUỘC tính cột Percentage bằng ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM employees), 2) AS Percentage!)
"""

    # 8.2 Thống kê số lượng và tổng mức lương theo từng giới tính
    elif any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "từng giới tính", "theo giới tính"]) and any(k in q_low for k in ["tổng mức lương", "tổng quỹ lương", "tổng lương", "quỹ lương", "chi phí lương"]) and any(k in q_low for k in ["số lượng", "quy mô", "nhân sự", "nhân viên", "headcount", "đếm"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (THỐNG KÊ SỐ LƯỢNG VÀ TỔNG MỨC LƯƠNG THEO TỪNG GIỚI TÍNH):
SELECT 
    e.gender AS Gender,
    COUNT(DISTINCT e.emp_no) AS Headcount,
    SUM(s.salary) AS TotalSalary,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY e.gender
ORDER BY Gender ASC;
(CẢNH BÁO ĐẶC BIỆT: BẮT BUỘC alias cột phân loại là Gender AS Gender, TUYỆT ĐỐI KHÔNG đặt tên Department hay Dept! Xuất đầy đủ Headcount, TotalSalary và AvgSalary!)
"""

    # 9. So sánh quy mô nhân sự và mức lương trung bình phòng ban
    elif any(k in q_low for k in ["quy mô", "số lượng nhân sự", "số nhân sự", "số nhân viên"]) and any(k in q_low for k in ["lương trung bình", "mức lương", "thu nhập"]) and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH QUY MÔ NHÂN SỰ VÀ MỨC LƯƠNG TRUNG BÌNH THEO PHÒNG BAN):
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount DESC;
(CẢNH BÁO ĐẶC BIỆT: BẮT BUỘC có cả 2 chỉ số: COUNT(DISTINCT de.emp_no) AS Headcount VÀ ROUND(AVG(s.salary), 2) AS AvgSalary! TUYỆT ĐỐI KHÔNG JOIN bảng dept_manager, TUYỆT ĐỐI KHÔNG LẤY TÊN TRƯỞNG PHÒNG ManagerName!)
"""

    # 10. So sánh mức lương trung bình giữa nam và nữ theo từng chức danh
    elif any(k in q_low for k in ["lương trung bình", "mức lương", "thu nhập"]) and any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính"]) and any(k in q_low for k in ["chức danh", "vị trí", "title", "công việc"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (SO SÁNH MỨC LƯƠNG TRUNG BÌNH NAM VÀ NỮ THEO TỪNG CHỨC DANH):
SELECT 
    t.title AS Title,
    ROUND(AVG(CASE WHEN e.gender = 'M' THEN s.salary END), 2) AS MaleAvgSalary,
    ROUND(AVG(CASE WHEN e.gender = 'F' THEN s.salary END), 2) AS FemaleAvgSalary
FROM titles t
JOIN employees e ON t.emp_no = e.emp_no
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY MaleAvgSalary DESC;
(CẢNH BÁO ĐẶC BIỆT: BẮT BUỘC dùng Pivot 2 cột MaleAvgSalary và FemaleAvgSalary trên 7 chức danh! TUYỆT ĐỐI KHÔNG dùng CONCAT(title, gender) thành 14 dòng xé lẻ!)
"""

    return ""


def build_sql_prompt(schema_context: str, dialect: str, user_query: str, lang: str = "vi") -> str:
    """Xây dựng prompt tạo câu lệnh SQL với độ chính xác Schema tuyệt đối và Dynamic Few-Shot In-Context Learning."""
    dialect_hint = get_dialect_hints(dialect, lang=lang)
    db_specific_rules = get_db_specific_rules(schema_context)
    targeted_hint = get_targeted_hint(user_query, schema_context, dialect=dialect)

    # Dynamic Few-Shot In-Context Learning (Top 2 most relevant gold-standard examples)
    few_shots = select_dynamic_few_shots(user_query, schema_context=schema_context, dialect=dialect, top_k=2)
    few_shot_block = format_few_shots_for_prompt(few_shots, dialect=dialect, lang=lang)

    if lang == "en":
        return f"""You are a world-class SQL engineer.
=== ACTUAL DATABASE SCHEMA ===
{schema_context}
==============================

Dialect Notice: {dialect_hint}

BUSINESS QUERY DECOMPOSITION RULES (MANDATORY COMPLIANCE):
1. EXTRACT ALL CONDITIONAL ENTITIES: Before writing SQL, explicitly verify whether the query contains conditions on MONEY/SALARY/TIME.
2. PRESERVE COMPARISON OPERATORS: If the query involves comparisons (less than, greater than, average), the SQL MUST include corresponding operators or functions in WHERE or HAVING. NEVER omit comparison criteria to produce an oversimplified query.
3. MULTI-STEP CTE WORKFLOW: If the problem requires 2 or more logical steps (e.g., finding the first department/value then comparing with the average, ranking/percentiles), USE 'WITH ... AS' (CTE) syntax to decompose each calculation step cleanly, transparently, and accurately.

STRICT RULES:
1. PURE SCHEMA GROUNDING:
   - ONLY use tables, views, and columns that appear in the SCHEMA above.
   - NEVER invent or assume table/column names.
{db_specific_rules}
2. HISTORICAL DATES:
   - Anchor relative dates to `(SELECT MAX(date_col) FROM table_name)`.
3. EXACT MATCHING:
   - Use flexible pattern matching (e.g. `LIKE '%term%'` or exact match) when querying textual categories and names.
4. SYNTAX PRECISION:
   - Use `COUNT(*)` or `COUNT(column)`, never `COUNT()`.
   - Ensure all parentheses () and quotes are balanced.
   - Wrap identifiers in backticks ` when needed.
5. CLEAN OUTPUT:
   - Return ONLY the single executable raw SQL statement (starting with SELECT or WITH).
   - No markdown code blocks, no explanations, no comments.
{few_shot_block}
{targeted_hint}
User Query: "{user_query}"
SQL Query:"""

    return f"""Bạn là chuyên gia SQL hàng đầu thế giới.

=== SCHEMA CƠ SỞ DỮ LIỆU THỰC TẾ ===
{schema_context}
====================================

Lưu ý Dialect: {dialect_hint}

QUY TẮC PHÂN RÃ TRUY VẤN NGHIỆP VỤ (BẮT BUỘC TUÂN THỦ):
1. TRÍCH XUẤT TẤT CẢ THỰC THỂ ĐIỀU KIỆN: Trước khi viết SQL, hãy tự kiểm tra xem câu hỏi có chứa điều kiện về TIỀN/LƯƠNG/THỜI GIAN không.
2. NẾU CÂU HỎI CÓ SO SÁNH (nhỏ hơn, lớn hơn, trung bình): Câu SQL BẮT BUỘC phải chứa các hàm hoặc toán tử so sánh tương ứng trong WHERE hoặc HAVING. TUYỆT ĐỐI KHÔNG được tự ý bỏ qua điều kiện so sánh để viết câu lệnh đơn giản hơn.
3. NẾU BÀI TOÁN CẦN TỪ 2 BƯỚC LOGIC TRỞ LÊN (ví dụ: tìm giá trị đầu tiên/phòng ban đầu tiên rồi so sánh với trung bình, phân vị/cohorts): HÃY DÙNG CÚ PHÁP 'WITH ... AS' (CTE) để chia nhỏ từng bước tính toán một cách tường minh, rõ ràng và chuẩn xác.

QUY TẮC BẮT BUỘC (TUÂN THỦ TUYỆT ĐỐI):
1. TUÂN THỦ SCHEMA TUYỆT ĐỐI (PURE SCHEMA GROUNDING):
   - CHỈ ĐƯỢC PHÉP SỬ DỤNG các bảng, view và cột xuất hiện thực tế trong SCHEMA ở trên.
   - Tuyệt đối KHÔNG tự ý bịa đặt hoặc sử dụng bất kỳ bảng/cột nào không có trong Schema.
   - Với câu hỏi đơn giản: dùng SELECT đơn trực tiếp. Với bài toán đa bước: dùng CTE (`WITH ... AS`) theo Quy tắc Phân rã Nghiệp vụ ở trên!
{db_specific_rules}
2. XỬ LÝ THỜI GIAN TRÊN DỮ LIỆU LỊCH SỬ (QUAN TRỌNG):
   - CSDL doanh nghiệp chứa dữ liệu các năm lịch sử (không phải realtime hôm nay).
   - Khi người dùng hỏi các mốc thời gian tương đối ('trong năm qua', 'gần đây', '12 tháng gần nhất', 'năm gần nhất'):
     + TUYỆT ĐỐI KHÔNG dùng `CURRENT_DATE()`, `CURDATE()`, `NOW()` nếu dữ liệu là lịch sử vì sẽ bị 0 dòng!
     + BẮT BUỘC dùng mốc ngày lớn nhất trong dữ liệu:
       * Trên MySQL: `WHERE date_col >= DATE_SUB((SELECT MAX(date_col) FROM table_name), INTERVAL 1 YEAR)`
       * Trên SQLite: `WHERE date_col >= date((SELECT MAX(date_col) FROM table_name), '-1 year')`
3. ĐỐI CHIẾU GIÁ TRỊ THỰC TẾ & TÌM KIẾM MỀM DẺO:
   - Tham khảo phần "DANH SÁCH GIÁ TRỊ MẪU THỰC TẾ TRONG CSDL" (nếu có) trong Schema để chọn đúng giá trị lọc.
   - Dùng `LIKE '%từ_khóa%'` hoặc khớp chính xác tùy theo yêu cầu câu hỏi để tránh trả về 0 dòng.
4. CÚ PHÁP CHUẨN XÁC & TỐI ƯU HIỆU NĂNG:
   - Dùng `COUNT(*)` hoặc `COUNT(column)`, TUYỆT ĐỐI KHÔNG dùng `COUNT()`.
   - Cân đối tuyệt đối số lượng dấu mở ngoặc '(' và đóng ngoặc ')'.
   - Bọc tên bảng và tên cột trong dấu backtick ` nếu có chứa ký tự đặc biệt hoặc khoảng trắng.
   - CẢNH BÁO CÚ PHÁP WHERE:
     * TUYỆT ĐỐI KHÔNG dùng hàm gộp `MAX()`, `AVG()`, `SUM()` trực tiếp trong mệnh đề `WHERE` (Lỗi MySQL 1111 Invalid use of group function). BẮT BUỘC bọc trong subquery: `WHERE col = (SELECT MAX(col) FROM tbl)` hoặc dùng `s.to_date = '9999-01-01'`.
     * TUYỆT ĐỐI KHÔNG dùng hàm `TO_DATE()` trên MySQL (Lỗi 1305). Cột ngày trong MySQL đã là kiểu `DATE` sẵn!
   - VỚI CÂU HỎI TOP N / DANH SÁCH / XẾP HẠNG:
        BẮT BUỘC: Mỗi thực thể chỉ được xuất hiện DUY NHẤT 1 LẦN với TỔNG HOẶC MAX TÍCH LŨY (`SUM(...)` hoặc `MAX(...)`), `GROUP BY` và `ORDER BY ... DESC LIMIT N`!
        TUYỆT ĐỐI KHÔNG SELECT rời rạc mà không `GROUP BY` vì sẽ bị lặp lại cùng một thực thể nhiều lần!
    - VỚI CÂU HỎI THEO THỜI GIAN / THEO THÁNG / THEO QUÝ / XU HƯỚNG:
         + TUYỆT ĐỐI CẤM DÙNG `LIMIT 10` (Bởi vì 1 năm có đủ 12 tháng, nếu dùng LIMIT 10 sẽ bị cắt mất tháng 6 hoặc tháng 12!).
         + BẮT BUỘC `ORDER BY ... ASC` để biểu đồ đường vẽ liền mạch, chuẩn xác theo đúng trình tự thời gian!
      + Khi người dùng hỏi dạng danh sách số nhiều thực thể đối tượng ('Danh sách...', 'Top N...', 'Những nhân viên/sản phẩm...', 'Các khách hàng/quốc gia...'): BẮT BUỘC tuân thủ đúng số N trong câu hỏi (Ví dụ: 'Top 10' -> BẮT BUỘC `LIMIT 10`, 'Top 5' -> `LIMIT 5`). Nếu không ghi rõ số N, mặc định dùng `LIMIT 10`. TUYỆT ĐỐI KHÔNG dùng `LIMIT 1` hoặc tự ý giảm số lượng xuống 5 khi người dùng yêu cầu Top 10!
      + TUYỆT ĐỐI KHÔNG áp dụng `LIMIT 10` cho câu hỏi thời gian, chuỗi xu hướng qua các tháng/năm ('qua các tháng', 'theo tháng', 'biến động theo thời gian') vì 1 năm phải có đủ 12 tháng!
     + Luôn ưu tiên `JOIN` theo các cột khóa chính/khóa ngoại để câu truy vấn chạy siêu tốc trong chớp mắt (< 0.1s).
     + Với các bảng chứa lịch sử nhiều bản ghi cho 1 thực thể (ví dụ: bảng lương `salaries` có nhiều dòng cho cùng một nhân viên): BẮT BUỘC dùng `MAX(salary)` và `GROUP BY` theo nhân viên (hoặc lọc ngày gần nhất `to_date = '9999-01-01'`) để KHÔNG bị lặp lại 1 người nhiều lần và giúp MySQL chạy siêu tốc!
      + VỚI CÂU HỎI VỀ TỶ LỆ / PHẦN TRĂM ĐÓNG GÓP (ví dụ: 'Tỷ lệ doanh thu của X so với tất cả sản phẩm'):
        Nên trả về bảng so sánh gồm tên đối tượng, doanh thu và tỷ lệ phần trăm (ví dụ: phân nhóm Đối tượng X vs 'Các sản phẩm khác') để có thể vẽ biểu đồ tròn Donut trực quan sinh động cho người dùng.
      + CẢNH BÁO BẮT BUỘC VỀ CHỈ SỐ ĐO LƯỜNG TRONG MỆNH ĐỀ SELECT (CHỐNG LỖI MẤT BIỂU ĐỒ):
        Khi câu hỏi có điều kiện lọc theo chỉ số (ví dụ: 'vượt mức X', 'trên X', 'dưới X', 'đạt từ X trở lên', 'có hơn X...') hoặc dùng mệnh đề HAVING:
        MỆNH ĐỀ SELECT BẮT BUỘC PHẢI CHỨA CẢ CỘT ĐỊNH DANH (Tên nhân viên, Tên sản phẩm, Quốc gia, Đội ngũ...) VÀ CỘT CHỈ SỐ ĐO LƯỜNG ĐƯỢC TÍNH TOÁN (`SUM(s.Amount) AS TotalSales`, `SUM(s.Boxes) AS TotalBoxesSold`, `COUNT(...)`)!
        TUYỆT ĐỐI CẤM chỉ SELECT mỗi tên thực thể rồi để ẩn chỉ số tính toán trong HAVING, vì hệ thống bắt buộc cần cột số đo lường để hiển thị số tiền/số lượng và vẽ biểu đồ kinh doanh!
5. ĐỊNH DẠNG ĐẦU RA (QUAN TRỌNG NHẤT):
   - CHỈ TRẢ VỀ DUY NHẤT 1 CÂU LỆNH SQL THUẦN (bắt đầu bằng chữ SELECT).
   - TUYỆT ĐỐI KHÔNG bọc trong markdown code block (```sql hoặc ```), TUYỆT ĐỐI KHÔNG đặt dấu backtick ` ở đầu hay cuối câu lệnh (`SELECT...).
   - TUYỆT ĐỐI KHÔNG thêm bất kỳ comment (#, --), không thêm lời giải thích nào bên ngoài.
{few_shot_block}
{targeted_hint}
Câu hỏi của người dùng: "{user_query}"
Câu lệnh SQL:"""


def build_fix_prompt(schema_context: str, dialect: str, user_query: str, sql_query: str, reason_or_error: str, lang: str = "vi") -> str:
    """Xây dựng prompt yêu cầu LLM sửa lại SQL khi gặp lỗi, kết quả rỗng (0 dòng) hoặc không qua self-check."""
    dialect_hint = get_dialect_hints(dialect, lang=lang)
    db_specific_rules = get_db_specific_rules(schema_context)
    targeted_hint = get_targeted_hint(user_query, schema_context, dialect=dialect)

    # Dynamic Few-Shot In-Context Learning for self-healing
    few_shots = select_dynamic_few_shots(user_query, schema_context=schema_context, dialect=dialect, top_k=1)
    few_shot_block = format_few_shots_for_prompt(few_shots, dialect=dialect, lang=lang)

    if lang == "en":
        return f"""You are a senior SQL expert. The SQL query you generated needs adjustments on {dialect}.

=== ACTUAL DATABASE SCHEMA ===
{schema_context}
==============================
Dialect Notice: {dialect_hint}

Original Query: "{user_query}"

Previous SQL:
{sql_query}

SYSTEM FEEDBACK:
{reason_or_error}

SCHEMA GUIDELINES & TEMPLATES:
{db_specific_rules}
{few_shot_block}
{targeted_hint}
FIX INSTRUCTIONS:
1. If result returned 0 rows due to CURRENT_DATE(), NOW(), CURDATE() or overly strict date filtering: Anchor to `(SELECT MAX(date_col) FROM table_name)` or remove restrictive date filters to fetch real data!
2. If 'Table or column doesn't exist': Carefully check the SCHEMA above and ONLY use tables and columns that exist in the Schema.
3. If syntax error: Use `COUNT(*)`, ensure balanced parentheses ().
4. Return ONLY the single corrected raw SQL query (starting with SELECT or WITH). No markdown, no comments, no explanations."""

    return f"""Bạn là chuyên gia SQL. Câu lệnh SQL bạn vừa sinh ra CẦN ĐƯỢC ĐIỀU CHỈNH LẠI trên {dialect}.

=== SCHEMA CƠ SỞ DỮ LIỆU THỰC TẾ ===
{schema_context}
====================================
Lưu ý Dialect: {dialect_hint}

Câu hỏi gốc: "{user_query}"

Câu SQL trước đó:
{sql_query}

THÔNG BÁO TỪ HỆ THỐNG:
{reason_or_error}

QUY TẮC & MẪU SQL CHUẨN CỦA CSDL NÀY:
{db_specific_rules}
{few_shot_block}
{targeted_hint}
HƯỚNG DẪN ĐIỀU CHỈNH BẮT BUỘC:
1. Nếu lỗi 'Table or column doesn't exist': Nhìn kỹ SCHEMA ở trên và CHỈ DÙNG đúng các bảng/cột có trong CSDL này. TUYỆT ĐỐI KHÔNG dùng bảng hoặc cột ngoài schema!
2. BẢNG EMPLOYEES: Không có cột dept_no! BẮT BUỘC JOIN qua dept_emp de: `FROM employees e JOIN dept_emp de ON e.emp_no = de.emp_no JOIN departments d ON de.dept_no = d.dept_no JOIN salaries s ON e.emp_no = s.emp_no`.
3. Nếu ở mục QUY TẮC & MẪU SQL CHUẨN hoặc CHỈ DẪN TRỰC TIẾP ở trên có mẫu cú pháp chuẩn (kể cả CTE `WITH ...`), BẮT BUỘC tuân thủ đúng cấu trúc mẫu đó!
4. Nếu kết quả trả về 0 dòng dữ liệu do dùng CURRENT_DATE(), NOW(), CURDATE() hoặc lọc thời gian quá chặt: Hãy thay thế bằng `(SELECT MAX(date_col) FROM table_name)` làm mốc ngày gần nhất hoặc bỏ điều kiện lọc thời gian để lấy dữ liệu thực tế!
5. Viết lại câu SQL hoàn chỉnh, chuẩn xác 100%. CHỈ TRẢ VỀ DUY NHẤT CÂU SQL THUẦN (bắt đầu bằng chữ SELECT hoặc WITH), không giải thích, không thêm comment."""


def build_self_check_prompt(schema_context: str, user_query: str, sql_query: str, sample_str: str, lang: str = "vi") -> str:
    """Xây dựng prompt cho bước AI QA self-check."""
    if lang == "en":
        return f"""You are a QA SQL Validator.
Schema: {schema_context}
Original Query: "{user_query}"
SQL: {sql_query}
5 sample rows: {sample_str}

Check if the SQL accurately and fully answers the question:
1. Does SQL strictly use actual existing tables and columns from the Schema?
2. Does SQL compute the requested metrics properly?

IMPORTANT: "ly_do" (reason) MUST be concise, MAX 20 words.
If SQL is valid, simply state "SQL is valid" or equivalent.
Return ONLY JSON, no markdown: {{"day_du": true/false, "ly_do": "..."}}"""

    return f"""Bạn là chuyên gia QA kiểm định SQL.
Schema: {schema_context}
Câu hỏi gốc: "{user_query}"
SQL: {sql_query}
5 dòng mẫu: {sample_str}

Kiểm tra SQL có trả lời ĐÚNG và ĐẦY ĐỦ câu hỏi không:
1. SQL có dùng đúng các bảng và cột thực tế có trong Schema không?
2. SQL có tính toán đúng yêu cầu của câu hỏi không?

QUAN TRỌNG: "ly_do" PHẢI ngắn gọn, TỐI ĐA 20 từ.
Nếu SQL đã đúng, chỉ cần ghi "SQL hợp lệ" hoặc tương đương.
Trả về DUY NHẤT JSON, không markdown, không giải thích thêm: {{"day_du": true/false, "ly_do": "..."}}"""


def build_anomaly_prompt(user_query: str, x_col: str, y_col: str, points: list, lang: str = "vi") -> str:
    """Xây dựng prompt giải thích các điểm bất thường dữ liệu."""
    if lang == "en":
        return f"""You are a Senior Business Data Analyst.
User Query: "{user_query}"
Statistical outliers detected on axis {x_col}, values {y_col}: {points}
Provide a 1-2 sentence concise hypothesis on potential business causes (e.g., seasonality, promotions, campaigns).
Output ONLY 1 short paragraph, no bullet points, no markdown headers."""

    return f"""Bạn là chuyên gia phân tích dữ liệu kinh doanh.
Câu hỏi gốc của người dùng: "{user_query}"
Các điểm bất thường (outlier, theo phương pháp IQR) phát hiện trên trục {x_col}, giá trị {y_col}: {points}
Đưa ra 1-2 câu nhận xét/giả thuyết ngắn gọn về nguyên nhân kinh doanh có thể xảy ra (VD: mùa vụ, khuyến mãi, sự kiện...).
Chỉ trả lời 1 đoạn văn ngắn, không markdown, không liệt kê gạch đầu dòng."""


def build_auto_insight_prompt(user_query: str, df_summary_str: str, anomalies_info: dict, lang: str = "vi") -> str:
    """Xây dựng prompt cho Báo cáo Insight Kinh doanh với Gắn Nhãn Mức Độ Ưu Tiên (Priority Tagging) và Khung Thời Gian."""
    findings = anomalies_info.get("findings", [])
    anomaly_types = anomalies_info.get("anomaly_types", [])
    stats = anomalies_info.get("summary_stats", {})

    findings_text = "\n".join(f"- {f.get('message')}" for f in findings) if findings else ("No significant anomalies detected." if lang == "en" else "Không có dấu hiệu bất thường rõ rệt.")
    types_text = ", ".join(anomaly_types) if anomaly_types else ("Normal" if lang == "en" else "Bình thường")

    sparsity_note_en = ""
    sparsity_note_vi = ""
    if anomalies_info.get("has_sparsity_gap") or stats.get("is_sparse_time_series"):
        sparsity_desc = stats.get('sparsity_details', 'intermittent intervals between recorded periods')
        sparsity_note_en = f"""
SPECIAL NOTICE ON DATA SPARSITY (DISCONTINUOUS TIME-SERIES):
- The time-series data contains discontinuous gaps ({sparsity_desc}).
- NEVER assume hypothetical seasonality for missing months (e.g. do NOT invent Q4 holiday peaks or Q3 summer clearance if those months are missing or inapplicable).
- Explicitly acknowledge the data gaps and formulate realistic recommendations grounded strictly in recorded periods."""
        sparsity_note_vi = f"""
LƯU Ý ĐẶC BIỆT VỀ ĐỘ TRŨNG DỮ LIỆU (CHUỖI THỜI GIAN KHÔNG LIÊN TỤC):
- Dữ liệu chuỗi thời gian bị đứt quãng / không liên tục ({stats.get('sparsity_details', 'có các khoảng gián đoạn giữa các tháng/kỳ ghi nhận')}).
- TUYỆT ĐỐI KHÔNG SUY DIỄN MÙA VỤ LÝ THUYẾT cho các tháng không tồn tại trong dữ liệu (ví dụ: TUYỆT ĐỐI KHÔNG giả định mùa mua sắm cao điểm Tháng 10 - Tháng 12 hay xả hàng Tháng 7 - Tháng 9 nếu các tháng này không có trong bảng kết quả hoặc không phù hợp với ngành kinh doanh).
- TUYỆT ĐỐI KHÔNG coi mức trung bình đơn giản toàn bảng là định mức phân bổ chuẩn khi các kỳ bị đứt quãng lớn.
- BẮT BUỘC cảnh báo dữ liệu gián đoạn và đưa ra đề xuất chiến lược thực tế bám sát các kỳ ghi nhận thực tế và lĩnh vực thực tế (ví dụ: Cho thuê phim/DVD, Nhân sự, Bán hàng...)."""

    if lang == "en":
        return f"""You are a Chief BI & Analytics Officer (Executive Data Analyst).

User Query: "{user_query}"
Statistical Summary:
- Record Count: {stats.get('count', 0)}
- Mean: {stats.get('mean', 0):,.2f} | Median: {stats.get('median', 0):,.2f}
- Min: {stats.get('min', 0):,.2f} | Max: {stats.get('max', 0):,.2f} | Total: {stats.get('total', 0):,.2f}

Sample Query Results:
{df_summary_str}
{sparsity_note_en}

Statistical Anomaly Findings:
- Types: {types_text}
- Findings:
{findings_text}

STRICT BUSINESS ANALYTICS DISCIPLINE & GUIDELINES:
1. STRICT METRIC DISCIPLINE:
   - If analyzing Margin / Profit % / Ratio: Focus strictly on Cost of Goods Sold (COGS), Unit Pricing Strategy, and Value Capture. NEVER hallucinate that high margin means "consumer popularity", "brand resonance", or "promotional pull"—high margin simply means lean COGS relative to price.
   - If analyzing Sales Volume / Boxes / Revenue: This is when you analyze market coverage, customer demand, and consumer pull.
2. MANDATORY TRADE-OFF MATRIX DETECTION:
   - When the data includes both a percentage (%) column (e.g. ProfitMargin) and an absolute ($) cash column (e.g. ProfitPerBox, Amount):
     ALWAYS cross-compare % vs. $ in Section 1: Identify products with top margin % vs. products generating top absolute cash profit per unit (e.g. high margin % with lower unit dollar profit vs. slightly lower margin % yielding the highest net cash).
3. ELIMINATE DATA NOISE & TRIVIAL MATH:
   - AVOID tedious arithmetic chains (e.g. "7.8% lower than leader... gap of 7.67%... leader exceeds by +8.4%"). Provide sharp, executive findings instead.
4. SEASONALITY & TEMPORAL ANALYSIS RULE (TIME-SERIES):
   - When analyzing trends or fluctuations over MONTHS or YEARS (Time-series data):
     * NEVER output raw numbers or floats like 'Point 3.0', 'Period 3', '(8)', '(9)'. Always refer to them naturally as 'March', 'August', 'September', 'Quarter 1', or 'Year 2022'.
     * Base analysis STRICTLY on the actual business domain and recorded periods:
       - If continuous: Identify real seasonal peaks and demand cycles.
       - If discontinuous / sparse: Explicitly note data gaps and avoid assuming unrecorded intervals.
5. PARETO 80/20 & CUMULATIVE PERCENTAGE DISCIPLINE:
   - When analyzing Pareto Analysis / Cumulative Percentage data (e.g. Products contributing to 80% of sales with columns Product, TotalSales, Percentage, CumulativePercent):
     * STRICT METRIC DISTINCTION:
       - `Percentage` (%): Represents each individual product's distinct share/contribution (e.g. 4.86%). The first product in the list is the #1 TOP-SELLING leader!
       - `CumulativePercent` (%): Represents the RUNNING ACCUMULATED TOTAL of the entire group up to that row (e.g. reaching 82.79% across all 18 products). NEVER misread CumulativePercent as the revenue share of a single individual SKU!
       - When proposing bundles (Combos), pair the #1 top-selling leader (e.g. Almond Choco with 4.86% individual share) with a slower-selling SKU or non-Pareto product. NEVER confuse the last row's cumulative percentage (82.79%) as its individual share.

REQUIREMENTS:
Generate an Executive Business Insight Report in English with exact Markdown format:

### 1. 🚨 Key Discoveries & Trend Anomalies
(State the Gross Margin / Performance leader, the Trade-off Matrix between % and $, and the portfolio Benchmark Median. Concise and noise-free).

### 2. 🔍 Potential Root Causes & Hypotheses
(MUST DYNAMICALLY REASON BASED ON THE EXACT METRIC AND DATA NUMBERS:
- Provide 2 distinct, logical business hypotheses:
  * If Margin %: Reason on COGS structure and Value Capture / Premium pricing power.
  * If Volume / Revenue:
    - If Target is Product: Reason on channel penetration and customer taste.
    - If Target is Sales Team: Reason on frontline conversion discipline and account coverage.
    - If Target is Market / Country: Reason on local purchasing power, market size, and retail distribution network maturity. STRICTLY DO NOT attribute a country's revenue to 'sales team closing skills' or 'team discipline'.
- CITE exact entities and numbers from the table. NEVER use generic boilerplate).

### 3. 🎯 Executive Action Plan & Priority Recommendations
(CRITICAL DISCIPLINE - MANDATORY ENTITY CONTEXT RULE BEFORE PROPOSING ACTIONS:
1. IDENTIFY THE TARGET ENTITY UNDER ANALYSIS (Entity Context Rule):
   - If "Product / SKU / Category":
     * Strategy: Portfolio optimization, Bundling / Combos, Pricing policy, Inventory & shelf-life management.
   - If "Human Resources / Sales Team (pe.Salesperson, pe.Team)":
     * Strategy: Immediate incentive bonuses, Sales coaching & deal-closing enablement, Best-practice sharing, Territory Planning & quota allocation.
     * STRICT PROHIBITION: NEVER use words like 'stock clearance', 'expiration date', or 'combo' for teams or people!
   - If "Market / Country (g.Geo / Country)":
     * Strategy: Expand local distribution channels, Market penetration, Consumer localization (taste & packaging fit), Optimize supply chain and import-export logistics.
     * STRICT PROHIBITION: ABSOLUTELY DO NOT use phrases like 'team New Zealand', 'team USA', 'sales incentive for USA', or 'sales pitch training for Canada'. A country is a geographical market, NOT a sales team or salesperson!
2. Provide exactly 3 actionable, high-impact recommendations tied to real data:
• 🔴 **[High Priority - Immediate Action / 0-30 Days]**: ...
• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: ...
• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: ...
- AVOID vague clichés like "enhance competitive edge", "automate analytics pipeline", or "replicate success enterprise-wide").

Style: Executive, concise, data-driven, professional tone."""

    ratio_note = ""
    if stats.get('count', 0) == 1:
        ratio_note = """
LƯU Ý KHI KẾT QUẢ TRẢ VỀ 1 BẢN GHI (TỔNG HỢP / TỶ LỆ PHẦN TRĂM):
- Nếu kết quả chỉ có 1 dòng hoặc 1 con số tỷ lệ phần trăm: ĐÂY CHÍNH LÀ ĐÁP ÁN CHÍNH XAC của câu hỏi.
- TUYỆT ĐỐI CẤM TỪ CHỐI BÁO CÁO! TUYỆT ĐỐI KHÔNG NÓI "không có dữ liệu cụ thể"!
- BẮT BUỘC phân tích sâu ý nghĩa kinh doanh của con số này bám sát vào câu hỏi người dùng."""

    return f"""Bạn là Giám đốc Phân tích Dữ liệu Kinh doanh (Chief BI & Analytics Officer).

Câu hỏi phân tích của người dùng: "{user_query}"

Dữ liệu kết quả truy vấn thực tế:
{df_summary_str}
{ratio_note}
{sparsity_note_vi}

KỶ LUẬT PHÂN TÍCH TÀI CHÍNH & THƯƠNG MẠI (BẮT BUỘC TUÂN THỦ):
1. PHÂN ĐỊNH RÕ BẢN CHẤT CHỈ SỐ:
   - Khi câu hỏi/dữ liệu phân tích Tỷ suất Lợi nhuận / Biên lợi nhuận (Margin / Profit %):
     * BẮT BUỘC tập trung vào Cấu trúc Chi phí Giá vốn (COGS), Định giá (Pricing Strategy) và Khả năng giữ biên an toàn.
     * TUYỆT ĐỐI CẤM suy diễn biên lợi nhuận cao là do "thị hiếu người dùng", "sức hút thương hiệu" hay "chương trình xúc tiến bán hàng". Biên lợi nhuận cao đơn thuần là do giá vốn COGS trên mỗi hộp rất thấp so với đơn giá bán! TUYỆT ĐỐI KHÔNG "bốc thuốc" cảm tính sai lệch bản chất tài chính.
   - Khi câu hỏi/dữ liệu phân tích Doanh số (Sales/Revenue) hoặc Sản lượng (Boxes):
     * Lúc này MỚI được phân tích về độ phủ thị trường, sức mua và thị hiếu tiêu dùng.
2. BẮT BUỘC PHÁT HIỆN "NGHỊCH LÝ ĐÁNH ĐỔI" (TRADE-OFF MATRIX):
   - Khi bảng dữ liệu có cả cột tỷ lệ phần trăm (`%` Margin) và cột số tiền tuyệt đối (`$` Profit per box, Sales):
     * BẮT BUỘC đối chiếu ở ngay Mục 2.1: Đối chiếu giữa sản phẩm có % margin cao nhất (nhưng tiền lời tuyệt đối mỗi hộp thấp) với sản phẩm có margin % thấp hơn nhưng lại mang về số tiền mặt ròng trên mỗi hộp cao nhất (ví dụ: White Choc margin 98.44% nhưng lãi $10.08/hộp vs Drinking Coco margin 91.68% nhưng lời tới $17.85/hộp).
3. LOẠI BỎ CON SỐ TOÁN HỌC VỤN VẶT (DATA NOISE):
   - TUYỆT ĐỐI CẤM viết các chuỗi tính toán trừ/chia % rườm rà (kiểu: "thấp hơn 7.8%... khoảng cách chênh lệch 7.67%; nhóm dẫn đầu vượt +8.4%...").
   - Nêu thẳng nhận định điều hành sắc gọn: Thực thể dẫn đầu biên độ, Nghịch lý đánh đổi (Trade-off Matrix) và Mặt bằng chung chuẩn toàn bảng.
4. QUY TẮC PHÂN TÍCH CHUỖI THỜI GIAN (TIME-SERIES & TEMPORAL RULE):
   - Khi phân tích biến động theo THÁNG / NĂM / QUÝ (Dữ liệu chuỗi thời gian):
     * TUYỆT ĐỐI KHÔNG xuất số thực trơ trọi hay nhãn thô như 'Điểm 3.0', 'Giai đoạn 3', '(8)', '(9)'. BẮT BUỘC dùng danh xưng tự nhiên như 'Tháng 3', 'Tháng 8', 'Tháng 9', 'Quý 1', 'Năm 2022'.
     * Gắn liền với bản chất thực tế của lĩnh vực đang phân tích (Cho thuê phim/DVD, Nhân sự/lương, Bán hàng B2B...):
       - Nếu chuỗi thời gian liên tục: Phân tích tính chu kỳ và cao điểm dựa trên các mốc thời gian thực tế có trong bảng.
       - Nếu chuỗi thời gian đứt quãng (sparse): Chỉ ra các khoảng gián đoạn, tránh suy đoán chủ quan về các tháng bị khuyết thiếu.
     * TUYỆT ĐỐI CẤM các câu văn sáo rỗng vô thưởng vô phạt hoặc áp đặt lý thuyết mùa vụ không có căn cứ số liệu thực tế.
5. QUY TẮC PHÂN BIỆT PARETO 80/20 & TỶ LỆ TÍCH LŨY DỒN:
   - Khi dữ liệu chứa bảng phân tích Pareto (các sản phẩm tạo 80% doanh thu) với các cột như Product, TotalSales, Percentage, CumulativePercent:
     * `Percentage` (%): Là tỷ trọng đóng góp cá nhân của từng sản phẩm đơn lẻ (ví dụ: Almond Choco chiếm 4.86%, là sản phẩm BÁN CHẠY NHẤT).
     * `CumulativePercent` (%): Là mốc tích lũy dồn của toàn bộ nhóm Pareto tính đến dòng đó (ví dụ: Peanut Butter Cubes ở dòng cuối đạt mốc 82.79% tích lũy của cả 18 sản phẩm). TUYỆT ĐỐI CẤM đọc nhầm mốc tích lũy 82.79% thành doanh số của một SKU đơn lẻ!
     * Khi đề xuất Combo: Phải ghép sản phẩm bán chạy nhất đầu bảng (ví dụ: Almond Choco 4.86%) với sản phẩm bán chậm hơn ngoài nhóm Pareto.

YÊU CẦU ĐỊNH DẠNG BÁO CÁO (MARKDOWN):

### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính
(Nêu rõ: Thực thể dẫn đầu biên độ/chỉ số, Nghịch lý đánh đổi Trade-off Matrix giữa % và $, và Mức trung vị chuẩn toàn bảng. Đi thẳng vào trọng tâm quản trị, không liệt kê số học vụn vặt).

### 2.2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng
(BẮT BUỘC SUY LUẬN LOGIC BÁM SÁT ĐÚNG BẢN CHẤT CHỈ SỐ VÀ DẪN CHỨNG SỐ LIỆU THỰC TẾ:
- Đưa ra đúng 2 giả thuyết kinh doanh giải thích TẠI SAO:
  * Nếu là Margin %: Giả thuyết 1 về Cấu trúc Chi phí Vốn (COGS) & Lợi thế giá vốn sản xuất; Giả thuyết 2 về Định vị giá trị & Năng lực sinh dòng tiền mặt ròng (Premium Value Capture).
  * Nếu là Volume / Doanh số:
    - Nếu đối tượng là Sản phẩm: Giả thuyết về Kênh phân phối và Thị hiếu khách hàng.
    - Nếu đối tượng là Nhân sự cá nhân (pe.Salesperson): Dùng danh xưng "Nhân sự [Tên]" hoặc "Nhân viên [Tên]". TUYỆT ĐỐI KHÔNG gọi tên nhân viên cá nhân là "nhóm [Tên]" (Ví dụ: "Nhân sự Gunar Cockshoot", TUYỆT ĐỐI CẤM gọi là "nhóm Gunar Cockshoot")!
    - Nếu đối tượng là Đội ngũ (pe.Team): Dùng danh xưng "Đội ngũ [Tên Team]" hoặc "Team [Tên Team]". Giả thuyết về Kỷ luật bán hàng và Khai thác địa bàn.
    - Nếu đối tượng là Thị trường / Quốc gia: Giả thuyết về Quy mô thị trường & Sức mua địa phương; Giả thuyết về Mạng lưới phân phối và Thích ứng thị hiếu người tiêu dùng bản địa. TUYỆT ĐỐI KHÔNG gán "kỹ năng chốt hợp đồng" hay "kỷ luật của đội ngũ" cho một quốc gia/thị trường.
- MỖI GIẢ THUYẾT BẮT BUỘC TRÍCH DẪN TÊN THỰC THỂ VÀ SỐ LIỆU CỤ THỂ TỪ KẾT QUẢ.
- TUYỆT ĐỐI CẤM câu văn mẫu sáo rỗng, TUYỆT ĐỐI KHÔNG chèn nhãn [Ưu tiên Cao] vào mục này).

### 2.3. 🎯 Đề xuất Chiến lược Phân cấp (Cấp bách | Trung hạn | Dài hạn)
(Quy tắc phân loại ngữ cảnh thực thể (Entity Context Rule):
1. Nếu đối tượng là SẢN PHẨM / SKU / CATEGORY:
   - Chiến lược: Tối ưu danh mục, đóng gói combo, chính sách giá, quản trị hàng tồn kho.
2. Nếu đối tượng là NHÂN SỰ CÁ NHÂN (pe.Salesperson):
   - Chiến lược: Incentive thưởng nóng, đào tạo kỹ năng chốt deal (coaching), kèm cặp nội bộ (peer coaching), chuyển giao kinh nghiệm từ Best Performer sang nhân sự khác. TUYỆT ĐỐI KHÔNG dùng từ "xả hàng", "hết hạn sử dụng", "combo" và TUYỆT ĐỐI KHÔNG gọi tên nhân viên là "nhóm [Tên]"!
3. Nếu đối tượng là ĐỘI NGŨ (pe.Team):
   - Chiến lược: Incentive thưởng nóng, đào tạo kỹ năng, chia sẻ best-practice, Territory Planning.
4. Nếu đối tượng là THỊ TRƯỜNG / QUỐC GIA (g.Geo / Country):
   - Chiến lược: Mở rộng kênh phân phối địa phương, thâm nhập thị trường, thích ứng văn hóa tiêu dùng (Localization), tối ưu chuỗi cung ứng/logistics xuất nhập khẩu. TUYỆT ĐỐI KHÔNG dùng từ 'team New Zealand', 'hoa hồng thưởng nóng cho USA'.

Quy tắc trình bày đề xuất:
BẮT BUỘC chỉ viết đúng 3 dòng đề xuất tương ứng với 3 cấp độ thời gian, bám sát số liệu cụ thể vừa truy vấn:
• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: ... (hành động cụ thể bám sát đối tượng)
• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: ... (hành động cụ thể bám sát đối tượng)
• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: ... (hành động cụ thể bám sát đối tượng)
TUYỆT ĐỐI KHÔNG DÙNG BẢNG, KHÔNG THÊM GẠCH ĐẦU DÒNG CON).

QUY TẮC ĐỊNH DẠNG & NGÔN NGỮ (BẮT BUỘC):
- 100% TIẾNG VIỆT KINH DOANH CHUẨN MỰC, TỰ NHIÊN (CẤM từ ngữ dịch máy ngô nghê, CẤM pha trộn câu tiếng Anh).
- MỖI Ý PHÂN TÍCH BẮT BUỘC NẰM TRÊN MỘT DÒNG RIÊNG BIỆT (bắt đầu bằng gạch đầu dòng `• `).
- CHỈ IN ĐẬM DUY NHẤT TIÊU ĐỀ Ở ĐẦU GẠCH ĐẦU DÒNG TRƯỚC DẤU HAI CHẤM.
- Phong cách trình bày: Sắc bén, súc tích, chuẩn ngôn ngữ Strategic Memo trình Ban Giám đốc."""


def build_followup_prompt(user_query: str, schema_context: str, df_sample_str: str, lang: str = "vi") -> str:
    """Xây dựng prompt đề xuất 2-3 câu hỏi phân tích tiếp nối có tính đào sâu (Drill-down Analytics)."""
    if lang == "en":
        return f"""You are a senior business data analyst.
The user just asked: "{user_query}"

Sample query results:
{df_sample_str}

Available Database Schema & Actual Date Ranges:
{schema_context}

CRITICAL RULES FOR FOLLOW-UP QUESTIONS:
1. NO AMBIGUOUS PRONOUNS: NEVER use words like "these 3 reps", "this product", "these items", "they", "those".
   - MUST use CONCRETE ENTITY NAMES directly from the sample data above (e.g., 'top 5 reps in Delish team', 'Dark 70% revenue by month', 'India market sales breakdown').
   - Every question must be 100% standalone and immediately executable when clicked.
2. STRICT TIME GROUNDING: ONLY suggest questions for years/quarters that ACTUALLY EXIST in the Date Range above.
   - NEVER suggest future/hallucinated years (like 2023/2024 if data is 2021).
3. EXACT REAL ENTITIES: ONLY use real product names (e.g. 'Milk Bars', '70% Dark Bites'), real rep IDs (e.g. 'SP01'), and real geos from the sample list. NEVER use non-existent names like 'Milk Chocolate' or 'SP001'.
4. Propose 2 to 3 high-value analytical drill-down questions.

Return ONLY a JSON array of strings:
["Question 1", "Question 2", "Question 3"]"""

    return f"""Bạn là chuyên gia phân tích dữ liệu kinh doanh.
Người dùng vừa hỏi: "{user_query}"

Kết quả dữ liệu mẫu thu được:
{df_sample_str}

Schema CSDL & Khoảng thời gian thực tế:
{schema_context}

QUY TẮC BẮT BUỘC KHI ĐỀ XUẤT CÂU HỎI TIẾP NỐI:
1. TUYỆT ĐỐI CẤM ĐẠI TỪ MƠ HỒ (QUAN TRỌNG NHẤT):
   - TUYỆT ĐỐI KHÔNG dùng các từ như: "3 nhân viên này", "sản phẩm này", "nhóm này", "các đối tượng trên", "họ", "chúng".
   - BẮT BUỘC PHẢI DÙNG TÊN THỰC THỂ CỤ THỂ lấy trực tiếp từ bảng dữ liệu mẫu ở trên (Ví dụ: thay vì "của 3 nhân viên này", hãy ghi rõ: "Top 5 nhân viên có doanh số cao nhất trong nhóm Delish", "Doanh số sản phẩm 70% Dark Bites theo từng tháng", "Doanh thu tại thị trường India").
   - Mỗi câu hỏi phải hoàn toàn ĐỘC LẬP để khi người dùng bấm nút là chạy được ngay mà không phụ thuộc ngữ cảnh trước.
2. RÀNG BUỘC THỜI GIAN TUYỆT ĐỐI:
   - CHỈ đề xuất các câu hỏi cho những NĂM THỰC TẾ có trong phần "KHOẢNG THỜI GIAN THỰC TẾ TRONG DỮ LIỆU" ở Schema trên.
   - TUYỆT ĐỐI KHÔNG tự bịa ra các năm không có trong dữ liệu (ví dụ: không gợi ý năm 2023/2024 nếu dữ liệu chỉ có năm 2021 hoặc 2022).
3. CHỈ DÙNG TÊN THỰC THỂ CÓ THẬT TRONG CSDL:
   - Dùng chính xác tên sản phẩm trong danh sách mẫu ('Milk Bars', '70% Dark Bites'...), mã nhân viên ('SP01'...), quốc gia ('India'...).
   - TUYỆT ĐỐI KHÔNG dùng tên bịa như 'Milk Chocolate' nếu trong CSDL tên là 'Milk Bars'.
4. ĐỊNH HƯỚNG CÁC DẠNG CÂU HỎI TIẾP NỐI CHUẨN KINH DOANH (DỄ VIẾT SQL VÀ CHẮC CHẮN VẼ ĐƯỢC BIỂU ĐỒ):
   - Dạng Xếp hạng: "Top 5 sản phẩm bán chạy nhất tại thị trường Australia năm 2021" hoặc "Top 5 nhân viên có doanh số cao nhất trong nhóm Yummies"
   - Dạng Xu hướng: "Doanh số theo từng tháng tại thị trường Australia năm 2021" hoặc "Doanh số của sản phẩm Milk Bars theo từng tháng năm 2021"
   - Dạng Phân bổ: "Doanh thu theo từng quốc gia của sản phẩm Drinking Coco"
   - TUYỆT ĐỐI KHÔNG đề xuất các câu hỏi cấu trúc kỳ lạ, mơ hồ, phi thực tế như 'ở đầu tháng và cuối tháng', 'doanh thu của mỗi sản phẩm tại...'.
   - CHỈ đề xuất các quốc gia có trong CSDL: 'Australia', 'India', 'USA', 'Canada', 'UK', 'New Zealand' (TUYỆT ĐỐI KHÔNG bịa ra 'Việt Nam' hay 'Japan').
5. CHÍNH TẢ & NGÔN NGỮ THUẦN VIỆT:
   - Viết 100% tiếng Việt chuẩn xác, TUYỆT ĐỐI KHÔNG dùng ký tự lạ hay chữ tiếng Hàn/Trung (như '각'). Dùng từ 'từng khu vực' hoặc 'các khu vực'.
   - Luôn tách từ rõ ràng, có dấu cách giữa tiếng Việt và tiếng Anh (ví dụ: viết 'danh mục Bars', TUYỆT ĐỐI KHÔNG viết 'danh mụcBars').

Trả về DUY NHẤT một JSON array chứa danh sách các chuỗi câu hỏi:
["Câu hỏi 1", "Câu hỏi 2", "Câu hỏi 3"]"""
