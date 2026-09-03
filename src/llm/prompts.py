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

    # Tự động nhận diện ngữ cảnh CSDL từ schema_context để hướng dẫn chính xác 100%
    is_employees_db = "departments" in schema_context.lower() or "dept_emp" in schema_context.lower() or "hire_date" in schema_context.lower()
    is_chocolates_db = "people" in schema_context.lower() and "products" in schema_context.lower()

    if is_employees_db:
        db_specific_rules = """   - QUY TẮC CSDL EMPLOYEES:
     + Bảng `employees` (Bí danh bắt buộc: `e`):
       * Cột: `emp_no` (Khóa chính), `first_name`, `last_name`, `gender`, `hire_date`, `birth_date`.
       * Ghép họ tên đầy đủ: `CONCAT(e.first_name, ' ', e.last_name) AS full_name`.
     + Bảng `salaries` (Bí danh bắt buộc: `s`):
       * Cột: `emp_no` (liên kết e.emp_no), `salary`, `from_date`, `to_date`.
       * Khi truy vấn lương cao nhất / hiện tại: BẮT BUỘC dùng `s.to_date = '9999-01-01'` và `MAX(s.salary) AS max_salary` cùng `GROUP BY e.emp_no, full_name`.
     + Bảng `departments` (Bí danh bắt buộc: `d`): `dept_no` (Khóa chính), `dept_name`.
     + Bảng liên kết phòng ban `dept_emp` (Bí danh bắt buộc: `de`): `emp_no`, `dept_no`, `from_date`, `to_date`.
     + Bảng chức danh `titles` (Bí danh bắt buộc: `t`): `emp_no`, `title`, `from_date`, `to_date`.
     + CẢNH BÁO LIÊN KẾT PHÒNG BAN: Bảng `employees` và `salaries` KHÔNG CÓ cột `dept_no`!
       Để nối tiền lương hoặc nhân viên với phòng ban (`departments d`), BẮT BUỘC JOIN qua bảng trung gian `dept_emp de`:
       `FROM salaries s JOIN dept_emp de ON s.emp_no = de.emp_no JOIN departments d ON de.dept_no = d.dept_no`
     + CẢNH BÁO BẮT BUỘC TIỀN TỐ BÍ DANH & TÊN CỘT (TRÁNH LỖI 1052, 1054):
       * Cột `emp_no` có trong 3 bảng. BẮT BUỘC viết `e.emp_no` trong SELECT và GROUP BY!
       * Cột tên phòng ban là `d.dept_name` (ví dụ: WHERE d.dept_name = 'Sales'). TUYỆT ĐỐI KHÔNG DÙNG `d.dept_no = 'Sales'` vì dept_no là mã số (d007)!
       * Thứ tự JOIN bắt buộc:
         FROM employees e
         JOIN salaries s ON e.emp_no = s.emp_no
         JOIN dept_emp de ON e.emp_no = de.emp_no
         JOIN departments d ON de.dept_no = d.dept_no
       * TUYỆT ĐỐI KHÔNG đưa `de.dept_no = d.dept_no` vào mệnh đề ON của dept_emp trước khi JOIN departments d!
       * TUYỆT ĐỐI KHÔNG dùng CTE (WITH ...), KHÔNG JOIN bảng titles nếu không hỏi chức danh!

     + MẪU CHUẨN TOP 10 NHÂN VIÊN LƯƠNG CAO NHẤT:
       SELECT e.emp_no, CONCAT(e.first_name, ' ', e.last_name) AS full_name, MAX(s.salary) AS max_salary
       FROM employees e
       JOIN salaries s ON e.emp_no = s.emp_no
       WHERE s.to_date = '9999-01-01'
       GROUP BY e.emp_no, full_name
       ORDER BY max_salary DESC
       LIMIT 10;

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

     + MẪU CHUẨN LƯƠNG THEO CHỨC DANH (TITLE):
       SELECT t.title AS Title, ROUND(AVG(s.salary), 2) AS AvgSalary
       FROM salaries s
       JOIN titles t ON s.emp_no = t.emp_no
       WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
       GROUP BY t.title
       ORDER BY AvgSalary DESC;

     + MẪU CHUẨN SO SÁNH LƯƠNG NAM VÀ NỮ THEO CHỨC DANH:
       SELECT t.title AS Title, e.gender AS Gender, ROUND(AVG(s.salary), 2) AS AvgSalary
       FROM employees e
       JOIN titles t ON e.emp_no = t.emp_no
       JOIN salaries s ON e.emp_no = s.emp_no
       WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
       GROUP BY t.title, e.gender
       ORDER BY t.title, e.gender;

     + MẪU CHUẨN TỶ LỆ GIỚI TÍNH TRONG BAN QUẢN LÝ (DEPT_MANAGER):
       SELECT d.dept_name AS Department, e.gender AS Gender, COUNT(*) AS TotalManagers
       FROM dept_manager dm
       JOIN employees e ON dm.emp_no = e.emp_no
       JOIN departments d ON dm.dept_no = d.dept_no
       WHERE dm.to_date = '9999-01-01'
       GROUP BY d.dept_name, e.gender
       ORDER BY d.dept_name;

     + MẪU CHUẨN XU HƯỚNG TUYỂN DỤNG THEO NĂM:
       SELECT YEAR(hire_date) AS HireYear, COUNT(*) AS TotalHires
       FROM employees
       GROUP BY HireYear
       ORDER BY HireYear ASC;

     + MẪU CHUẨN DANH SÁCH TRƯỞNG PHÒNG HIỆN TẠI (MANAGER) KÈM LƯƠNG:
       SELECT d.dept_name AS Department, CONCAT(e.first_name, ' ', e.last_name) AS ManagerName, s.salary AS CurrentSalary
       FROM dept_manager dm
       JOIN employees e ON dm.emp_no = e.emp_no
       JOIN departments d ON dm.dept_no = d.dept_no
       JOIN salaries s ON e.emp_no = s.emp_no
       WHERE dm.to_date = '9999-01-01' AND s.to_date = '9999-01-01'
       ORDER BY s.salary DESC;"""
    elif is_chocolates_db:
        db_specific_rules = """   - QUY TẮC CSDL AWESOME CHOCOLATES:
     + Bảng `products` (Bí danh bắt buộc: `pr`):
       * Cột: `PID` (Khóa chính), `Product` (Tên sản phẩm: 'Mint Chip Choco', 'Milk Bars'...), `Category`, `Size`, `Cost_per_box`.
       * CẢNH BÁO: TUYỆT ĐỐI KHÔNG DÙNG `pr.Salesperson` (Salesperson nằm ở bảng people, KHÔNG nằm ở products)! TUYỆT ĐỐI KHÔNG DÙNG `ProductCost_per_box` (cột chi phí là `Cost_per_box`)!
     + Bảng `people` (Bí danh bắt buộc: `pe`):
       * Cột: `SPID` (Khóa chính), `Salesperson` (Tên nhân viên: 'Van Tuxwell'...), `Team` ('Yummies', 'Jucies', 'Delish'...), `Location`.
       * CẢNH BÁO: Tên nhân viên là cột `Salesperson`, TUYỆT ĐỐI KHÔNG DÙNG `Name` hay `Employee`!
     + Bảng `geo` (Bí danh bắt buộc: `g`):
       * Cột: `GeoID` (Khóa chính), `Geo` (Tên quốc gia/thị trường: 'Australia', 'India', 'USA', 'Canada', 'UK', 'New Zealand'), `Region` (Khu vực địa lý lớn: 'APAC', 'Americas').
       * CẢNH BÁO: Khi lọc thị trường hoặc khu vực Australia, Ấn Độ (India), Mỹ (USA)... BẮT BUỘC DÙNG `g.Geo = 'Australia'` (hoặc `g.Geo = 'India'`)!
     + Bảng `sales` (Bí danh bắt buộc: `s`):
       * Cột: `SPID` (liên kết pe.SPID), `PID` (liên kết pr.PID), `GeoID` (liên kết g.GeoID), `SaleDate` (Ngày bán), `Amount` (Doanh số), `Boxes`, `Customers`.
     + QUY TẮC BÍ DANH (ALIAS) TUYỆT ĐỐI KHÔNG TRÙNG NHAU:
       * TUYỆT ĐỐI KHÔNG đặt cùng bí danh `p` cho cả people và products (sẽ gây lỗi MySQL 1066 Not unique table/alias)!
       * Luôn dùng: `pe` cho people, `pr` cho products, `s` cho sales, `g` cho geo.
     + Mối quan hệ liên kết:
       * `pr.PID = s.PID`
       * `pe.SPID = s.SPID`
       * `g.GeoID = s.GeoID`
     + TUYỆT ĐỐI KHÔNG DÙNG CTE (`WITH ...`) cho các truy vấn đơn giản. Hãy viết câu lệnh SELECT ... JOIN ... GROUP BY phẳng, trực tiếp và chạy siêu tốc!
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
       JOIN geo g ON s.GeoID = g.GeoID
       WHERE g.Geo = 'Australia' AND YEAR(s.SaleDate) = 2021
       GROUP BY pr.Product
       ORDER BY TotalSales DESC
       LIMIT 5;"""
    else:
        db_specific_rules = """   - QUY TẮC SCHEMA CHUNG:
     + CHỈ ĐƯỢC PHÉP SỬ DỤNG các bảng và cột xuất hiện thực tế trong SCHEMA ở trên.
     + Mỗi bảng được JOIN phải có bí danh phân biệt, không được trùng nhau."""

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

Câu hỏi của người dùng: "{user_query}"
Câu lệnh SQL:"""


def build_fix_prompt(schema_context: str, dialect: str, user_query: str, sql_query: str, reason_or_error: str, lang: str = "vi") -> str:
    """Xây dựng prompt yêu cầu LLM sửa lại SQL khi gặp lỗi, kết quả rỗng (0 dòng) hoặc không qua self-check."""
    dialect_hint = get_dialect_hints(dialect, lang=lang)
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

HƯỚNG DẪN ĐIỀU CHỈNH BẮT BUỘC:
1. Nếu lỗi 'Table or column doesn't exist': Nhìn kỹ SCHEMA ở trên và CHỈ DÙNG đúng các bảng/cột có trong CSDL này. TUYỆT ĐỐI KHÔNG dùng bảng ngoài schema!
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

### 2.3. 🎯 Đề xuất Hành động (Action Plan)
(BẮT BUỘC chỉ viết đúng 3 dòng hành động tương ứng với 3 mức độ ưu tiên, gắn chặt vào câu hỏi người dùng:
• 🔴 **[Ưu tiên Cao - Thực hiện Ngay]**: [Hành động cấp bách bám sát dữ liệu]
• 🟡 **[Ưu tiên Trung bình - Quý tiếp theo]**: [Chiến lược trung hạn]
• 🟢 **[Ưu tiên Thấp / Dài hạn]**: [Kế hoạch bền vững dài hạn]
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
