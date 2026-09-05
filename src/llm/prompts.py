"""
Prompt templates and builders for SQL generation, validation, anomaly explanation,
automatic business insights with Executive Priority Tagging, and intelligent bilingual follow-up question suggestions.
Strictly grounded in provided database schema with relative historical time-handling to prevent 0-row results.
"""


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


def build_sql_prompt(schema_context: str, dialect: str, user_query: str, lang: str = "vi") -> str:
    """Xây dựng prompt tạo câu lệnh SQL từ ngôn ngữ tự nhiên với Schema Grounding thuần khiết, linh hoạt cho mọi CSDL."""
    dialect_hint = get_dialect_hints(dialect, lang=lang)
    if lang == "en":
        return f"""You are a world-class senior SQL database architect.

=== ACTUAL DATABASE SCHEMA ===
{schema_context}
==============================

Dialect Notice: {dialect_hint}

MANDATORY RULES (STRICT COMPLIANCE):
1. PURE SCHEMA GROUNDING:
   - ONLY use the tables, views, and columns that explicitly appear in the Schema above.
   - NEVER invent or assume table or column names that are not in the Schema.
   - Determine the correct JOIN paths by matching primary and foreign keys provided in the Schema.
2. HISTORICAL RELATIVE TIME HANDLING:
   - Business databases often contain historical data.
   - When the user asks for relative time ('last year', 'past 12 months', 'recent period'):
     + NEVER use CURRENT_DATE(), CURDATE(), NOW() if the data is historical as it will return 0 rows.
     + Anchor to the MAX date in the target table:
       * MySQL: `WHERE date_col >= DATE_SUB((SELECT MAX(date_col) FROM table_name), INTERVAL 1 YEAR)`
       * SQLite: `WHERE date_col >= date((SELECT MAX(date_col) FROM table_name), '-1 year')`
3. DISTINCT VALUES & TEXT MATCHING:
   - Check against the 'DISTINCT SAMPLE VALUES' section in the Schema if present.
   - Use flexible pattern matching (e.g. `LIKE '%term%'` or exact match) when querying textual categories and names.
4. SYNTAX PRECISION:
   - Use `COUNT(*)` or `COUNT(column)`, never `COUNT()`.
   - Ensure all parentheses () and quotes are balanced.
   - Wrap identifiers in backticks ` when needed.
5. CLEAN OUTPUT:
   - Return ONLY the single executable raw SQL statement (starting with SELECT or WITH).
   - No markdown code blocks, no explanations, no comments.

User Query: "{user_query}"
SQL Query:"""

def get_db_specific_rules(schema_context: str) -> str:
    """Tự động nhận diện CSDL và sinh quy tắc chi tiết theo từng bảng."""
    schema_low = (schema_context or "").lower()
    is_employees_db = "departments" in schema_low or "dept_emp" in schema_low or "hire_date" in schema_low or "salaries" in schema_low
    is_chocolates_db = "people" in schema_low and "products" in schema_low

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
        * QUY TẮC BẮT BUỘC VỀ CHỨC DANH (TITLE): Khi câu hỏi có từ 'chức danh', 'vị trí', 'title' hoặc 'lương nam nữ theo chức danh': BẮT BUỘC dùng bảng `titles t` (cột `t.title`), JOIN `employees e` và `salaries s`, GROUP BY `t.title`. TUYỆT ĐỐI KHÔNG JOIN bảng `departments` hay `dept_emp`!
        * Cột tên phòng ban là `d.dept_name` (ví dụ: WHERE d.dept_name = 'Sales'). TUYỆT ĐỐI KHÔNG DÙNG `d.dept_no = 'Sales'` vì dept_no là mã số (d007)!
        * Thứ tự JOIN bắt buộc khi truy vấn phòng ban:
          FROM employees e
          JOIN salaries s ON e.emp_no = s.emp_no
          JOIN dept_emp de ON e.emp_no = de.emp_no
          JOIN departments d ON de.dept_no = d.dept_no
        * TUYỆT ĐỐI KHÔNG đưa `de.dept_no = d.dept_no` vào mệnh đề ON của dept_emp trước khi JOIN departments d!
        * TUYỆT ĐỐI KHÔNG dùng CTE (WITH ...), KHÔNG JOIN bảng titles nếu không hỏi chức danh!

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


      + MẪU CHUẨN TOP N CHỨC DANH LƯƠNG CAO NHẤT (Ví dụ: Top 5 chức danh):
        SELECT t.title AS Title, ROUND(AVG(s.salary), 2) AS AvgSalary
        FROM salaries s
        JOIN titles t ON s.emp_no = t.emp_no
        WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
        GROUP BY t.title
        ORDER BY AvgSalary DESC
        LIMIT 5;
        * QUY TẮC: Khi câu hỏi có chữ 'Top N' (Top 5, Top 10, Top 3): BẮT BUỘC phải có mệnh đề LIMIT N ở cuối câu SQL!

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
            ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 1) AS YearsOfService
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
     + MẪU CHUẨN TOP NHÂN SỰ:
       SELECT pe.Salesperson, SUM(s.Amount) AS TotalSales, pe.Team
       FROM people pe
       JOIN sales s ON pe.SPID = s.SPID
       GROUP BY pe.Salesperson, pe.Team
       ORDER BY TotalSales DESC
       LIMIT 10;
     + MẪU CHUẨN TOP SẢN PHẨM:
       SELECT pr.Product, SUM(s.Amount) AS TotalSales
       FROM products pr
       JOIN sales s ON pr.PID = s.PID
       GROUP BY pr.Product
       ORDER BY TotalSales DESC
       LIMIT 10;
     + MẪU CHUẨN DOANH THU THEO THÁNG:
       SELECT MONTH(s.SaleDate) AS Month, SUM(s.Amount) AS TotalSales
       FROM sales s
       WHERE YEAR(s.SaleDate) = 2021
       GROUP BY Month
       ORDER BY Month ASC;"""
    else:
        return """   - QUY TẮC SCHEMA CHUNG:
     + CHỈ ĐƯỢC PHÉP SỬ DỤNG các bảng và cột xuất hiện thực tế trong SCHEMA ở trên.
     + Mỗi bảng được JOIN phải có bí danh phân biệt, không được trùng nhau."""


def get_targeted_hint(user_query: str, schema_context: str = "") -> str:
    """Tự động sinh chỉ dẫn chuyên biệt (Targeted Hint) cho câu hỏi cụ thể, áp dụng cho cả prompt gốc và prompt sửa lỗi."""
    q_low = (user_query or "").lower()

    # 1. Câu hỏi liên quan đến chức danh (Title)
    if any(k in q_low for k in ["chức danh", "title", "vị trí", "senior staff", "senior engineer", "technique leader", "assistant engineer"]):
        if any(k in q_low for k in ["nam", "nữ", "gender", "giới tính"]):
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
        elif any(k in q_low for k in ["phân bố", "tỷ lệ", "tỷ trọng", "cơ cấu", "số lượng", "bao nhiêu nhân sự", "nhân viên theo", "nhân sự theo"]):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TỶ LỆ PHÂN BỐ NHÂN SỰ THEO TỪNG CHỨC DANH):
SELECT 
    t.title AS JobTitle,
    COUNT(t.emp_no) AS EmployeeCount,
    ROUND(COUNT(t.emp_no) * 100.0 / (SELECT COUNT(*) FROM titles WHERE to_date = '9999-01-01'), 2) AS Percentage
FROM titles t
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY EmployeeCount DESC;
(BẮT BUỘC dùng bảng titles t, đếm EmployeeCount và tính Percentage, TUYỆT ĐỐI KHÔNG JOIN salaries hay departments, KHÔNG LỌC THEO PHÒNG BAN SALES!)
"""
        elif any(k in q_low for k in ["top", "cao nhất", "lương trung bình"]):
            return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP CHỨC DANH LƯƠNG CAO NHẤT):
SELECT t.title AS Title, ROUND(AVG(s.salary), 2) AS AvgSalary
FROM salaries s
JOIN titles t ON s.emp_no = t.emp_no
WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY AvgSalary DESC
LIMIT 5;
(BẮT BUỘC dùng bảng titles t, TUYỆT ĐỐI KHÔNG JOIN departments hay dept_emp!)
"""

    # 2. Thâm niên nhân sự
    elif any(k in q_low for k in ["thâm niên", "cống hiến"]) or ("lâu nhất" in q_low and any(k in q_low for k in ["nhân viên", "công tác", "làm việc"])):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (NHÂN VIÊN THÂM NIÊN LÂU NHẤT CÒN CÔNG TÁC):
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    d.dept_name AS Department,
    e.hire_date AS HireDate,
    ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 1) AS YearsOfService
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
ORDER BY e.hire_date ASC, YearsOfService DESC
LIMIT 10;
(TUYỆT ĐỐI KHÔNG DÙNG MAX(salary) LƯƠNG CAO NHẤT, TUYỆT ĐỐI CẤM DÙNG YEAR(de.to_date) hay tạo cột mang giá trị 9999, BẮT BUỘC TÍNH CỘT YearsOfService DÙNG DATEDIFF và ORDER BY e.hire_date ASC!)
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

    # 4. Top nhân viên lương cao nhất hiện tại toàn công ty
    elif any(k in q_low for k in ["lương cao nhất", "thu nhập cao nhất", "mức lương cao nhất"]) and any(k in q_low for k in ["nhân viên", "nhân sự", "toàn công ty", "công ty", "người", "ai"]):
        return """
⚠️ CHỈ DẪN TRỰC TIẾP CHO CÂU HỎI HIỆN TẠI (TOP NHÂN VIÊN LƯƠNG CAO NHẤT HIỆN TẠI):
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
(CẢNH BÁO: Bảng salaries và employees KHÔNG CÓ CỘT dept_no! BẮT BUỘC JOIN QUA dept_emp de: ON e.emp_no = de.emp_no JOIN departments d ON de.dept_no = d.dept_no! TUYỆT ĐỐI KHÔNG VIẾT s.dept_no hay e.dept_no!)
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

    # 6. Nhân viên có từ N lần tăng lương trở lên
    elif any(k in q_low for k in ["tăng lương", "lần tăng lương", "tăng lương trở lên", "được tăng lương"]):
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

    # 7. Tỷ lệ nam và nữ trong ban quản lý (dept_manager)
    elif any(k in q_low for k in ["ban quản lý", "dept_manager", "manager", "quản lý"]) and any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "tỷ lệ", "nam", "nữ"]):
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

    # 8. Số lượng và tỷ lệ nam nữ trong từng phòng ban (nhân viên toàn phòng)
    elif any(k in q_low for k in ["tỷ lệ nam nữ", "nam và nữ", "nam nữ"]) and any(k in q_low for k in ["từng phòng ban", "các phòng ban", "phòng ban"]):
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
    """Xây dựng prompt tạo câu lệnh SQL với độ chính xác Schema tuyệt đối."""
    dialect_hint = get_dialect_hints(dialect, lang=lang)
    db_specific_rules = get_db_specific_rules(schema_context)
    targeted_hint = get_targeted_hint(user_query, schema_context)

    if lang == "en":
        return f"""You are a world-class SQL engineer.
=== ACTUAL DATABASE SCHEMA ===
{schema_context}
==============================

Dialect Notice: {dialect_hint}

STRICT RULES:
1. PURE SCHEMA GROUNDING:
   - ONLY use tables, views, and columns that appear in the SCHEMA above.
   - NEVER invent or assume table/column names.
   - NEVER use CTEs (`WITH ...`). Use flat direct SELECT statements!
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

User Query: "{user_query}"
SQL Query:"""

    return f"""Bạn là chuyên gia SQL hàng đầu thế giới.

=== SCHEMA CƠ SỞ DỮ LIỆU THỰC TẾ ===
{schema_context}
====================================

Lưu ý Dialect: {dialect_hint}

QUY TẮC BẮT BUỘC (TUÂN THỦ TUYỆT ĐỐI):
1. TUÂN THỦ SCHEMA TUYỆT ĐỐI (PURE SCHEMA GROUNDING):
   - CHỈ ĐƯỢC PHÉP SỬ DỤNG các bảng, view và cột xuất hiện thực tế trong SCHEMA ở trên.
   - Tuyệt đối KHÔNG tự ý bịa đặt hoặc sử dụng bất kỳ bảng/cột nào không có trong Schema.
   - TUYỆT ĐỐI CẤM DÙNG CTE (`WITH ...`). Dùng câu lệnh SELECT đơn trực tiếp để tối ưu tốc độ và độ tin cậy!
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
     + Khi người dùng hỏi dạng danh sách số nhiều ('Danh sách...', 'Top...', 'Những...', 'Các...') mà không phải theo chuỗi thời gian: BẮT BUỘC dùng `LIMIT 10` (hoặc `LIMIT 5`), TUYỆT ĐỐI KHÔNG dùng `LIMIT 1` để trả về đầy đủ danh sách trực quan cho người dùng.
     + Luôn ưu tiên `JOIN` theo các cột khóa chính/khóa ngoại để câu truy vấn chạy siêu tốc trong chớp mắt (< 0.1s).
     + Với các bảng chứa lịch sử nhiều bản ghi cho 1 thực thể (ví dụ: bảng lương `salaries` có nhiều dòng cho cùng một nhân viên): BẮT BUỘC dùng `MAX(salary)` và `GROUP BY` theo nhân viên (hoặc lọc ngày gần nhất `to_date = '9999-01-01'`) để KHÔNG bị lặp lại 1 người nhiều lần và giúp MySQL chạy siêu tốc!
     + VỚI CÂU HỎI VỀ TỶ LỆ / PHẦN TRĂM ĐÓNG GÓP (ví dụ: 'Tỷ lệ doanh thu của X so với tất cả sản phẩm'):
        Nên trả về bảng so sánh gồm tên đối tượng, doanh thu và tỷ lệ phần trăm (ví dụ: phân nhóm Đối tượng X vs 'Các sản phẩm khác') để có thể vẽ biểu đồ tròn Donut trực quan sinh động cho người dùng.
5. ĐỊNH DẠNG ĐẦU RA (QUAN TRỌNG NHẤT):
   - CHỈ TRẢ VỀ DUY NHẤT 1 CÂU LỆNH SQL THUẦN (bắt đầu bằng chữ SELECT hoặc WITH).
   - TUYỆT ĐỐI KHÔNG bọc trong markdown code block (```sql hoặc ```), TUYỆT ĐỐI KHÔNG đặt dấu backtick ` ở đầu hay cuối câu lệnh (`SELECT...).
   - TUYỆT ĐỐI KHÔNG thêm bất kỳ comment (#, --), không thêm lời giải thích nào bên ngoài.
{targeted_hint}
Câu hỏi của người dùng: "{user_query}"
Câu lệnh SQL:"""


def build_fix_prompt(schema_context: str, dialect: str, user_query: str, sql_query: str, reason_or_error: str, lang: str = "vi") -> str:
    """Xây dựng prompt yêu cầu LLM sửa lại SQL khi gặp lỗi, kết quả rỗng (0 dòng) hoặc không qua self-check."""
    dialect_hint = get_dialect_hints(dialect, lang=lang)
    db_specific_rules = get_db_specific_rules(schema_context)
    targeted_hint = get_targeted_hint(user_query, schema_context)

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
{targeted_hint}
FIX INSTRUCTIONS:
1. If result returned 0 rows due to CURRENT_DATE(), NOW(), CURDATE() or overly strict date filtering: Anchor to `(SELECT MAX(date_col) FROM table_name)` or remove restrictive date filters to fetch real data!
2. If 'Table or column doesn't exist': Carefully check the SCHEMA above and ONLY use tables and columns that exist in the Schema.
3. If syntax error: Use `COUNT(*)`, ensure balanced parentheses ().
4. Return ONLY the single corrected raw SQL query (SELECT or WITH). No markdown, no comments, no explanations."""

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
{targeted_hint}
HƯỚNG DẪN ĐIỀU CHỈNH BẮT BUỘC:
1. Nếu lỗi 'Table or column doesn't exist': Nhìn kỹ SCHEMA ở trên và CHỈ DÙNG đúng các bảng/cột có trong CSDL này. TUYỆT ĐỐI KHÔNG dùng bảng hoặc cột ngoài schema!
2. BẢNG EMPLOYEES: Không có cột dept_no! BẮT BUỘC JOIN qua dept_emp de: `FROM employees e JOIN dept_emp de ON e.emp_no = de.emp_no JOIN departments d ON de.dept_no = d.dept_no JOIN salaries s ON e.emp_no = s.emp_no`.
3. TUYỆT ĐỐI CẤM DÙNG CTE (`WITH ...`). BẮT BUỘC dùng duy nhất 1 câu SELECT trực tiếp!
4. Nếu kết quả trả về 0 dòng dữ liệu do dùng CURRENT_DATE(), NOW(), CURDATE() hoặc lọc thời gian quá chặt: Hãy thay thế bằng `(SELECT MAX(date_col) FROM table_name)` làm mốc ngày gần nhất hoặc bỏ điều kiện lọc thời gian để lấy dữ liệu thực tế!
5. Viết lại câu SQL hoàn chỉnh, chuẩn xác 100%. CHỈ TRẢ VỀ DUY NHẤT CÂU SQL THUẦN (bắt đầu bằng chữ SELECT), không giải thích, không thêm comment."""


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

    if lang == "en":
        return f"""You are a Chief BI & Analytics Officer (Executive Data Analyst).

User Query: "{user_query}"
Statistical Summary:
- Record Count: {stats.get('count', 0)}
- Mean: {stats.get('mean', 0):,.2f} | Median: {stats.get('median', 0):,.2f}
- Min: {stats.get('min', 0):,.2f} | Max: {stats.get('max', 0):,.2f} | Total: {stats.get('total', 0):,.2f}

Sample Query Results:
{df_summary_str}

Statistical Anomaly Findings:
- Types: {types_text}
- Findings:
{findings_text}

REQUIREMENTS:
Generate an Executive Business Insight Report in English with exact Markdown format:

### 1. 🚨 Key Discoveries & Trend Anomalies
(Highlight significant spikes, sharp increases/decreases, or concentration risks with exact numbers).

### 2. 🔍 Potential Root Causes & Hypotheses
(Provide 2-3 realistic business hypotheses: seasonality, marketing campaigns, supply chain, VIP accounts, pricing,...).

### 3. 🎯 Executive Action Plan & Priority Recommendations
(Provide 2-3 actionable, high-impact recommendations. MUST tag each action with Urgency and Execution Timeframe:
- 🔴 **[High Priority - Immediate Action]**: Urgent issue or immediate high-yield opportunity.
- 🟡 **[Medium Priority - Next Quarter]**: Mid-term operational or tactical optimization.
- 🟢 **[Low Priority / Long-term]**: Sustainable long-term strategic initiative.
Each recommendation must specify an expected measurable KPI/metric).

Style: Executive, concise, data-driven, professional tone."""

    ratio_note = ""
    if stats.get('count', 0) == 1:
        ratio_note = """
LƯU Ý KHI KẾT QUẢ TRẢ VỀ 1 BẢN GHI (TỔNG HỢP / TỶ LỆ PHẦN TRĂM):
- Nếu kết quả chỉ có 1 dòng hoặc 1 con số tỷ lệ phần trăm: ĐÂY CHÍNH LÀ ĐÁP ÁN CHÍNH XÁC của câu hỏi.
- TUYỆT ĐỐI CẤM TỪ CHỐI BÁO CÁO! TUYỆT ĐỐI KHÔNG NÓI "không có dữ liệu cụ thể"!
- BẮT BUỘC phân tích sâu ý nghĩa kinh doanh của con số này bám sát vào câu hỏi người dùng."""

    return f"""Bạn là Giám đốc Phân tích Dữ liệu Kinh doanh (Chief BI & Analytics Officer).

Câu hỏi phân tích của người dùng: "{user_query}"

Dữ liệu kết quả truy vấn thực tế:
{df_summary_str}
{ratio_note}

YÊU CẦU PHÂN TÍCH KINH DOANH:
Hãy đưa ra bản báo cáo Insight Kinh doanh ngắn gọn, sắc bén và mang tính điều hành thực chiến cao (định dạng Markdown):

### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính
(Nêu thẳng nhận định kinh doanh: Đơn vị/thực thể nào dẫn đầu (Top 1) với bao nhiêu, đơn vị nào thấp nhất, khoảng cách chênh lệch bao nhiêu %. TUYỆT ĐỐI CẤM liệt kê máy móc từng dòng Min, Max, Mean, Median, Sum, số bản ghi!).

### 2.2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng
(Đưa ra 2-3 giả thuyết kinh doanh thực tế giải thích nguyên nhân: Quy mô hoạt động, Chính sách đãi ngộ & cạnh tranh nhân tài, Tính chất chuyên môn phòng ban, Thị trường tiêu thụ,... TUYỆT ĐỐI KHÔNG chèn nhãn [Ưu tiên Cao] hay từ tiếng Anh vào mục này).

### 2.3. 🎯 Đề xuất Chiến lược Phân cấp (Cấp bách | Trung hạn | Dài hạn)
(BẮT BUỘC chỉ viết đúng 3 dòng đề xuất tương ứng với 3 cấp độ thời gian, bám sát số liệu cụ thể vừa truy vấn:
• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: [Can thiệp ngay vào điểm bất thường/sụt giảm sâu nhất hoặc chênh lệch lớn nhất trích dẫn số liệu]
• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: [Tối ưu quy trình, cân đối nguồn lực và chuẩn hóa ngân sách theo mức trung bình/trung vị]
• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: [Chính sách đãi ngộ, chuyển đổi số và định hướng quản trị vĩ mô lâu dài]
TUYỆT ĐỐI KHÔNG DÙNG BẢNG, KHÔNG THÊM GẠCH ĐẦU DÒNG CON).

QUY TẮC ĐỊNH DẠNG & NGÔN NGỮ (BẮT BUỘC):
- 100% TIẾNG VIỆT KINH DOANH CHUẨN MỰC, TỰ NHIÊN (TUYỆT ĐỐI CẤM từ ngữ dịch máy ngô nghê, CẤM pha trộn câu tiếng Anh, CẤM từ bịa như 'Kinh Thuần').
- MỖI Ý PHÂN TÍCH BẮT BUỘC NẰM TRÊN MỘT DÒNG RIÊNG BIỆT (bắt đầu bằng gạch đầu dòng `• `).
- CHỈ IN ĐẬM DUY NHẤT TIÊU ĐỀ Ở ĐẦU GẠCH ĐẦU DÒNG TRƯỚC DẤU HAI CHẤM.
- Phong cách trình bày: Sắc bén, súc tích, đi thẳng vào trọng tâm điều hành."""


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
