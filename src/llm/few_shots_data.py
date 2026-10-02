"""
Kho Tri thức Mẫu Chuẩn mực (Ground Truth Few-Shot Repository) cho Text-to-SQL.
Bao gồm các bài toán từ cơ bản đến phức tạp nhất:
- Tính chênh lệch/biên độ lương (Spread / Gap / Range với CTE)
- Phân vị và xếp hạng nâng cao (Percentiles / Window Functions / NTILE)
- Tính nhất quán qua thời gian (Sản phẩm luôn nằm trong Top 5 ở tất cả các quý)
- Biên lợi nhuận và đơn vị kinh tế (Unit Economics & Profit Margin %)
- Neo mốc thời gian lịch sử tương đối (Historical Relative Time)
- So sánh với mặt bằng chung (Subquery CTE Benchmark)
- Lọc theo ngưỡng đo lường kết hợp (Threshold Aggregations)
Hỗ trợ song song cả hai dialect: MySQL và SQLite.
"""

FEW_SHOT_EXAMPLES = [
    # =========================================================================
    # NHÓM 1: CSDL EMPLOYEES (NHÂN SỰ & TIỀN LƯƠNG)
    # =========================================================================
    {
        "id": "emp_department_avg_salary",
        "domain": "employees",
        "category": "department_salary",
        "tags": [
            "mức lương trung bình của nhân viên theo từng phòng ban",
            "mức lương trung bình theo từng phòng ban",
            "mức lương trung bình của nhân viên",
            "lương trung bình theo phòng ban",
            "lương trung bình của nhân viên theo phòng ban",
            "mức lương trung bình",
            "theo từng phòng ban",
            "average salary of employees by department",
            "average salary by department"
        ],
        "question": "Mức lương trung bình của nhân viên theo từng phòng ban",
        "question_en": "Average salary of employees by department",
        "intent_explanation": "Join departments với dept_emp và salaries (lọc to_date = '9999-01-01' cho cả hai bảng để tính nhân sự và mức lương hiện tại), nhóm theo phòng ban để tính quy mô (Headcount) và mức lương trung bình (AvgSalary), sắp xếp giảm dần theo mức lương trung bình.",
        "sql_mysql": """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_no, d.dept_name
ORDER BY AvgSalary DESC;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_no, d.dept_name
ORDER BY AvgSalary DESC;"""
    },
    {
        "id": "emp_salary_spread_dept",
        "domain": "employees",
        "category": "salary_spread",
        "tags": ["chênh lệch lương", "khoảng cách lương", "salary spread", "phòng ban", "cte", "biên độ", "chênh lệch"],
        "question": "Phòng ban nào có mức chênh lệch lương lớn nhất giữa nhân viên cao nhất và thấp nhất?",
        "question_en": "Which department has the largest salary spread between its highest and lowest paid employee?",
        "intent_explanation": "Dùng CTE nhóm theo phòng ban, tính MAX(salary) - MIN(salary) của nhân sự đang làm việc (to_date = '9999-01-01'), sau đó ORDER BY DESC LIMIT 1.",
        "sql_mysql": """WITH DeptSalarySpread AS (
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
SELECT Department, MaxSalary, MinSalary, SalarySpread
FROM DeptSalarySpread
ORDER BY SalarySpread DESC
LIMIT 1;""",
        "sql_sqlite": """WITH DeptSalarySpread AS (
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
SELECT Department, MaxSalary, MinSalary, SalarySpread
FROM DeptSalarySpread
ORDER BY SalarySpread DESC
LIMIT 1;"""
    },
    {
        "id": "emp_salary_spread_group_comparison",
        "domain": "employees",
        "category": "salary_spread",
        "tags": [
            "chênh lệch mức lương", "chênh lệch lương", "nhóm cao nhất và nhóm thấp nhất",
            "nhóm cao nhất", "nhóm thấp nhất", "giữa nhóm cao nhất", "giữa nhóm", "khoảng cách lương",
            "phân tích sự chênh lệch", "salary spread", "phòng ban", "so sánh nhóm", "các nhóm"
        ],
        "question": "Phân tích sự chênh lệch mức lương giữa nhóm cao nhất và nhóm thấp nhất",
        "question_en": "Analyze the salary difference between the highest and lowest group",
        "intent_explanation": "Nhóm theo từng phòng ban (nhóm nhân sự), tính mức lương cao nhất, thấp nhất, trung bình và khoảng chênh lệch lương (SalarySpread = MAX - MIN), sau đó sắp xếp theo mức độ chênh lệch giảm dần để đối chiếu rõ nhóm cao nhất vs nhóm thấp nhất.",
        "sql_mysql": """WITH DeptSalaryStats AS (
    SELECT 
        d.dept_name AS Department,
        ROUND(AVG(s.salary), 2) AS AvgSalary,
        MAX(s.salary) AS MaxSalary,
        MIN(s.salary) AS MinSalary,
        (MAX(s.salary) - MIN(s.salary)) AS SalarySpread,
        COUNT(DISTINCT de.emp_no) AS Headcount
    FROM departments d
    JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
    JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    GROUP BY d.dept_name
)
SELECT 
    Department,
    AvgSalary,
    MaxSalary,
    MinSalary,
    SalarySpread,
    ROUND((MaxSalary - MinSalary) * 100.0 / MinSalary, 2) AS SpreadRatioPct,
    Headcount
FROM DeptSalaryStats
ORDER BY SalarySpread DESC;""",
        "sql_sqlite": """WITH DeptSalaryStats AS (
    SELECT 
        d.dept_name AS Department,
        ROUND(AVG(s.salary), 2) AS AvgSalary,
        MAX(s.salary) AS MaxSalary,
        MIN(s.salary) AS MinSalary,
        (MAX(s.salary) - MIN(s.salary)) AS SalarySpread,
        COUNT(DISTINCT de.emp_no) AS Headcount
    FROM departments d
    JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
    JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    GROUP BY d.dept_name
)
SELECT 
    Department,
    AvgSalary,
    MaxSalary,
    MinSalary,
    SalarySpread,
    ROUND((MaxSalary - MinSalary) * 100.0 / MinSalary, 2) AS SpreadRatioPct,
    Headcount
FROM DeptSalaryStats
ORDER BY SalarySpread DESC;"""
    },
    {
        "id": "emp_salary_peak_valley_period",
        "domain": "employees",
        "category": "time_peak_valley",
        "tags": ["khoảng thời gian", "thời gian nào", "thời điểm nào", "giai đoạn", "giai đoạn đạt đỉnh", "mức lương cao nhất và thấp nhất", "cao nhất và thấp nhất", "peak period", "chu kỳ lương", "năm đạt đỉnh", "đỉnh và đáy", "highest and lowest period"],
        "question": "Khoảng thời gian nào ghi nhận mức lương cao nhất và thấp nhất?",
        "question_en": "Which time period recorded the highest and lowest salary?",
        "intent_explanation": "Dùng CTE nhóm theo từng năm `YEAR(from_date)` trên bảng salaries để tính mức lương bình quân, cao nhất, thấp nhất và gán nhãn cực trị đỉnh - đáy qua các năm.",
        "sql_mysql": """WITH YearlySalaryStats AS (
    SELECT 
        YEAR(s.from_date) AS Year,
        ROUND(AVG(s.salary), 2) AS AverageSalary,
        MAX(s.salary) AS MaxSalary,
        MIN(s.salary) AS MinSalary,
        COUNT(*) AS TotalRecords
    FROM salaries s
    GROUP BY YEAR(s.from_date)
)
SELECT 
    Year,
    AverageSalary,
    MaxSalary,
    MinSalary,
    TotalRecords,
    CASE 
        WHEN AverageSalary = (SELECT MAX(AverageSalary) FROM YearlySalaryStats) THEN 'Mức lương TB cao nhất 🏆'
        WHEN AverageSalary = (SELECT MIN(AverageSalary) FROM YearlySalaryStats) THEN 'Mức lương TB thấp nhất 📉'
        ELSE 'Bình thường'
    END AS Evaluation
FROM YearlySalaryStats
ORDER BY Year ASC;""",
        "sql_sqlite": """WITH YearlySalaryStats AS (
    SELECT 
        CAST(strftime('%Y', s.from_date) AS INTEGER) AS Year,
        ROUND(AVG(s.salary), 2) AS AverageSalary,
        MAX(s.salary) AS MaxSalary,
        MIN(s.salary) AS MinSalary,
        COUNT(*) AS TotalRecords
    FROM salaries s
    GROUP BY CAST(strftime('%Y', s.from_date) AS INTEGER)
)
SELECT 
    Year,
    AverageSalary,
    MaxSalary,
    MinSalary,
    TotalRecords,
    CASE 
        WHEN AverageSalary = (SELECT MAX(AverageSalary) FROM YearlySalaryStats) THEN 'Mức lương TB cao nhất 🏆'
        WHEN AverageSalary = (SELECT MIN(AverageSalary) FROM YearlySalaryStats) THEN 'Mức lương TB thấp nhất 📉'
        ELSE 'Bình thường'
    END AS Evaluation
FROM YearlySalaryStats
ORDER BY Year ASC;"""
    },
    {
        "id": "emp_active_headcount_by_year_history",
        "domain": "employees",
        "category": "active_headcount_history",
        "tags": ["từ năm 1985 đến 2002 có bao nhiêu nhân viên còn đang làm việc", "từ năm 1985 đến năm 2002", "có bao nhiêu nhân viên còn đang làm việc", "nhân viên còn đang làm việc qua từng năm", "số lượng nhân viên đang làm việc theo từng năm", "headcount qua các năm", "active headcount by year", "làm việc từ năm 1985 đến 2002"],
        "question": "Từ năm 1985 đến năm 2002 có bao nhiêu nhân viên còn đang làm việc?",
        "question_en": "From 1985 to 2002, how many employees were active/working each year?",
        "intent_explanation": "Sử dụng CTE đệ quy tạo danh sách các năm từ 1985 đến 2002 rồi JOIN với bảng `dept_emp` với điều kiện năm bắt đầu làm việc `<= year` và ngày kết thúc `de.to_date = '9999-01-01' OR YEAR(de.to_date) >= year`. Trả về 2 cột: `year` và `active_headcount` sắp xếp tăng dần theo `year`.",
        "sql_mysql": """WITH RECURSIVE Years AS (
    SELECT 1985 AS year
    UNION ALL
    SELECT year + 1 FROM Years WHERE year < 2002
)
SELECT 
    y.year AS year,
    COUNT(DISTINCT de.emp_no) AS active_headcount
FROM Years y
JOIN dept_emp de ON YEAR(de.from_date) <= y.year 
    AND (de.to_date = '9999-01-01' OR YEAR(de.to_date) >= y.year)
GROUP BY y.year
ORDER BY y.year ASC;""",
        "sql_sqlite": """WITH RECURSIVE Years(year) AS (
    SELECT 1985
    UNION ALL
    SELECT year + 1 FROM Years WHERE year < 2002
)
SELECT 
    y.year AS year,
    COUNT(DISTINCT de.emp_no) AS active_headcount
FROM Years y
JOIN dept_emp de ON CAST(strftime('%Y', de.from_date) AS INTEGER) <= y.year 
    AND (de.to_date = '9999-01-01' OR CAST(strftime('%Y', de.to_date) AS INTEGER) >= y.year)
GROUP BY y.year
ORDER BY y.year ASC;"""
    },
    {
        "id": "emp_company_salary_trend_yearly",
        "domain": "employees",
        "category": "salary_trend",
        "tags": ["thay đổi như thế nào qua các năm", "mức lương trung bình của toàn công ty thay đổi như thế nào", "lương trung bình qua các năm", "lương thay đổi như thế nào qua các năm", "xu hướng lương qua các năm", "mức lương trung bình", "thay đổi như thế nào", "toàn công ty qua các năm", "average salary trend across years"],
        "question": "Mức lương trung bình của toàn công ty thay đổi như thế nào qua các năm?",
        "question_en": "How did the average salary of the entire company change over the years?",
        "intent_explanation": "Nhóm theo năm trên bảng salaries để tính mức lương trung bình (AverageSalary) của toàn công ty theo từng năm theo đúng thứ tự thời gian tuần tự từ 1985 đến 2002. TUYỆT ĐỐI KHÔNG TỰ JOIN BẢNG tạo cột Year1/Year2.",
        "sql_mysql": """SELECT 
    YEAR(s.from_date) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY Year ASC;""",
        "sql_sqlite": """SELECT 
    CAST(strftime('%Y', s.from_date) AS INTEGER) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY CAST(strftime('%Y', s.from_date) AS INTEGER)
ORDER BY Year ASC;"""
    },
    {
        "id": "emp_salary_compression_yearly",
        "domain": "employees",
        "category": "salary_compression",
        "tags": ["ép lương", "tỷ lệ ép lương", "nén lương", "tỷ lệ nén lương", "salary compression", "wage compression", "năm nào", "cao nhất", "pay compression", "biên độ lương"],
        "question": "Năm nào thể hiện tỷ lệ ép lương cao nhất?",
        "question_en": "Which year exhibits the highest wage/salary compression ratio?",
        "intent_explanation": "Nhóm theo năm trên bảng salaries để tính mức lương tối thiểu (MinSalary), trung bình (AvgSalary), tối đa (MaxSalary), khoảng chênh lệch (SalarySpread = MAX - MIN), tỷ lệ nén lương (WageCompressionPct = MIN * 100 / AVG) và tỷ số lương (PayRatio = MAX / MIN), sau đó ORDER BY WageCompressionPct DESC.",
        "sql_mysql": """SELECT 
    YEAR(s.from_date) AS Year,
    MIN(s.salary) AS MinSalary,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread,
    ROUND(MIN(s.salary) * 100.0 / AVG(s.salary), 2) AS WageCompressionPct,
    ROUND(MAX(s.salary) / MIN(s.salary), 2) AS PayRatio
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY WageCompressionPct DESC;""",
        "sql_sqlite": """SELECT 
    CAST(strftime('%Y', s.from_date) AS INTEGER) AS Year,
    MIN(s.salary) AS MinSalary,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread,
    ROUND(CAST(MIN(s.salary) AS FLOAT) * 100.0 / AVG(s.salary), 2) AS WageCompressionPct,
    ROUND(CAST(MAX(s.salary) AS FLOAT) / MIN(s.salary), 2) AS PayRatio
FROM salaries s
GROUP BY CAST(strftime('%Y', s.from_date) AS INTEGER)
ORDER BY WageCompressionPct DESC;"""
    },
    {
        "id": "emp_salary_compression_dept",
        "domain": "employees",
        "category": "salary_compression",
        "tags": ["ép lương", "tỷ lệ ép lương", "tỉ lệ ép lương", "bị ép lương", "nén lương", "tỷ lệ nén lương", "salary compression", "wage compression", "phòng ban", "phòng ban nào", "lớn nhất", "cao nhất", "pay compression"],
        "question": "Phòng ban nào có tỉ lệ bị ép lương lớn nhất?",
        "question_en": "Which department has the highest wage/salary compression ratio?",
        "intent_explanation": "Nhóm theo phòng ban trên bảng departments JOIN dept_emp và salaries với to_date = '9999-01-01' để tính quy mô (ActiveHeadcount), mức lương tối thiểu (MinSalary), trung bình (AvgSalary), tối đa (MaxSalary), khoảng chênh lệch (SalarySpread = MAX - MIN), tỷ lệ nén lương (WageCompressionPct = MIN * 100 / AVG) và tỷ số lương (PayRatio = MAX / MIN), sau đó ORDER BY WageCompressionPct DESC LIMIT 10.",
        "sql_mysql": """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS ActiveHeadcount,
    MIN(s.salary) AS MinSalary,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread,
    ROUND(MIN(s.salary) * 100.0 / AVG(s.salary), 2) AS WageCompressionPct,
    ROUND(MAX(s.salary) / MIN(s.salary), 2) AS PayRatio
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_no, d.dept_name
ORDER BY WageCompressionPct DESC
LIMIT 10;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS ActiveHeadcount,
    MIN(s.salary) AS MinSalary,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread,
    ROUND(CAST(MIN(s.salary) AS FLOAT) * 100.0 / AVG(s.salary), 2) AS WageCompressionPct,
    ROUND(CAST(MAX(s.salary) AS FLOAT) / MIN(s.salary), 2) AS PayRatio
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_no, d.dept_name
ORDER BY WageCompressionPct DESC
LIMIT 10;"""
    },
    {
        "id": "emp_top10_percent_salary",
        "domain": "employees",
        "category": "window_function",
        "tags": ["top 10%", "phân vị", "percentile", "thu nhập cao nhất", "window function", "ntile", "xếp hạng"],
        "question": "Danh sách nhân viên thuộc top 10% có thu nhập cao nhất hiện tại",
        "question_en": "List employees who fall into the top 10% highest salaries currently",
        "intent_explanation": "Sử dụng hàm phân vị NTILE(10) OVER (ORDER BY s.salary DESC) trên bảng lương hiện tại và lọc nhóm 1.",
        "sql_mysql": """WITH RankedSalaries AS (
    SELECT 
        e.emp_no,
        CONCAT(e.first_name, ' ', e.last_name) AS FullName,
        s.salary AS CurrentSalary,
        NTILE(10) OVER (ORDER BY s.salary DESC) AS SalaryDecile
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
)
SELECT emp_no, FullName, CurrentSalary
FROM RankedSalaries
WHERE SalaryDecile = 1
ORDER BY CurrentSalary DESC
LIMIT 10;""",
        "sql_sqlite": """WITH RankedSalaries AS (
    SELECT 
        e.emp_no,
        (e.first_name || ' ' || e.last_name) AS FullName,
        s.salary AS CurrentSalary,
        NTILE(10) OVER (ORDER BY s.salary DESC) AS SalaryDecile
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
)
SELECT emp_no, FullName, CurrentSalary
FROM RankedSalaries
WHERE SalaryDecile = 1
ORDER BY CurrentSalary DESC
LIMIT 10;"""
    },
    {
        "id": "emp_dept_avg_above_company",
        "domain": "employees",
        "category": "benchmark_comparison",
        "tags": ["cao hơn trung bình", "trung bình toàn công ty", "benchmark", "so sánh", "phòng ban", "lương", "lớn hơn trung bình"],
        "question": "Những phòng ban nào có mức lương trung bình cao hơn mức lương trung bình của toàn công ty?",
        "question_en": "Which departments have an average salary higher than the overall company average?",
        "intent_explanation": "So sánh AVG(salary) theo từng phòng ban với subquery tính lương bình quân toàn công ty.",
        "sql_mysql": """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS DeptAvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
HAVING AVG(s.salary) > (
    SELECT AVG(salary) 
    FROM salaries 
    WHERE to_date = '9999-01-01'
)
ORDER BY DeptAvgSalary DESC;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS DeptAvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
HAVING AVG(s.salary) > (
    SELECT AVG(salary) 
    FROM salaries 
    WHERE to_date = '9999-01-01'
)
ORDER BY DeptAvgSalary DESC;"""
    },
    {
        "id": "emp_raise_count_tenure",
        "domain": "employees",
        "category": "aggregation",
        "tags": ["số lần tăng lương", "tăng lương", "thâm niên", "nhiều lần nhất", "raisecount", "lần tăng"],
        "question": "Top 10 nhân viên được tăng lương nhiều lần nhất trong lịch sử",
        "question_en": "Top 10 employees who received the highest number of salary raises in history",
        "intent_explanation": "Đếm số bản ghi trong bảng salaries cho mỗi nhân viên trừ đi 1 (mức lương khởi điểm không tính là lần tăng).",
        "sql_mysql": """SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    (COUNT(s.salary) - 1) AS RaiseCount,
    MAX(s.salary) AS CurrentSalary
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no
GROUP BY e.emp_no, e.first_name, e.last_name
HAVING COUNT(s.salary) > 1
ORDER BY RaiseCount DESC, CurrentSalary DESC
LIMIT 10;""",
        "sql_sqlite": """SELECT 
    e.emp_no,
    (e.first_name || ' ' || e.last_name) AS FullName,
    (COUNT(s.salary) - 1) AS RaiseCount,
    MAX(s.salary) AS CurrentSalary
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no
GROUP BY e.emp_no, e.first_name, e.last_name
HAVING COUNT(s.salary) > 1
ORDER BY RaiseCount DESC, CurrentSalary DESC
LIMIT 10;"""
    },
    {
        "id": "emp_gender_salary_by_dept",
        "domain": "employees",
        "category": "comparison",
        "tags": ["giới tính", "nam", "nữ", "lương bình quân", "phòng ban", "gender", "so sánh"],
        "question": "So sánh mức lương trung bình giữa nam và nữ theo từng phòng ban",
        "question_en": "Compare average salary between male and female employees by department",
        "intent_explanation": "Nhóm theo phòng ban và giới tính, tính AVG(salary) hiện tại.",
        "sql_mysql": """SELECT 
    d.dept_name AS Department,
    e.gender AS Gender,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    COUNT(DISTINCT e.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN employees e ON de.emp_no = e.emp_no
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name, e.gender
ORDER BY d.dept_name, e.gender;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    e.gender AS Gender,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    COUNT(DISTINCT e.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN employees e ON de.emp_no = e.emp_no
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name, e.gender
ORDER BY d.dept_name, e.gender;"""
    },
    {
        "id": "emp_title_salary_above_company_avg",
        "domain": "employees",
        "category": "salary_comparison",
        "tags": ["chức danh", "title", "mức lương", "lương trung bình", "vượt mức trung bình", "trên mức trung bình", "cao hơn trung bình", "salary", "avg salary"],
        "question": "Những chức danh nào có mức lương vượt trên mức trung bình?",
        "question_en": "Which job titles have an average salary above the overall company average?",
        "intent_explanation": "Tính mức lương trung bình của từng chức danh hiện tại (TitleAvgSalary) và so sánh với mức lương trung bình toàn công ty (CompanyAvgSalary), chỉ lấy những chức danh có TitleAvgSalary > CompanyAvgSalary.",
        "sql_mysql": """SELECT 
    t.title AS Title,
    ROUND(AVG(s.salary), 2) AS TitleAvgSalary,
    (SELECT ROUND(AVG(salary), 2) FROM salaries WHERE to_date = '9999-01-01') AS CompanyAvgSalary,
    ROUND(AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS SalarySurplus,
    ROUND((AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')) * 100.0 / (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS SurplusPct,
    COUNT(DISTINCT t.emp_no) AS Headcount
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
HAVING AVG(s.salary) > (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')
ORDER BY TitleAvgSalary DESC;""",
        "sql_sqlite": """SELECT 
    t.title AS Title,
    ROUND(AVG(s.salary), 2) AS TitleAvgSalary,
    (SELECT ROUND(AVG(salary), 2) FROM salaries WHERE to_date = '9999-01-01') AS CompanyAvgSalary,
    ROUND(AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS SalarySurplus,
    ROUND((AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')) * 100.0 / (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS SurplusPct,
    COUNT(DISTINCT t.emp_no) AS Headcount
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
HAVING AVG(s.salary) > (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')
ORDER BY TitleAvgSalary DESC;"""
    },
    {
        "id": "emp_title_progression",
        "domain": "employees",
        "category": "progression",
        "tags": ["chức danh", "chuyển vị trí", "thăng chức", "số lần đổi chức danh", "titles", "bổ nhiệm"],
        "question": "Những nhân viên nào đã từng đảm nhiệm từ 3 chức danh trở lên trong công ty?",
        "question_en": "Which employees have held 3 or more distinct titles in the company?",
        "intent_explanation": "Đếm COUNT(DISTINCT title) trên bảng titles kèm danh sách chức danh hiện tại.",
        "sql_mysql": """SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    COUNT(DISTINCT t.title) AS DistinctTitleCount
FROM employees e
JOIN titles t ON e.emp_no = t.emp_no
GROUP BY e.emp_no, e.first_name, e.last_name
HAVING COUNT(DISTINCT t.title) >= 3
ORDER BY DistinctTitleCount DESC
LIMIT 10;""",
        "sql_sqlite": """SELECT 
    e.emp_no,
    (e.first_name || ' ' || e.last_name) AS FullName,
    COUNT(DISTINCT t.title) AS DistinctTitleCount
FROM employees e
JOIN titles t ON e.emp_no = t.emp_no
GROUP BY e.emp_no, e.first_name, e.last_name
HAVING COUNT(DISTINCT t.title) >= 3
ORDER BY DistinctTitleCount DESC
LIMIT 10;"""
    },
    {
        "id": "emp_hiring_trend_by_year",
        "domain": "employees",
        "category": "time_series",
        "tags": ["tuyển dụng", "theo năm", "qua các năm", "số lượng tuyển", "hire_date", "xu hướng"],
        "question": "Số lượng nhân viên được tuyển dụng qua từng năm và xu hướng biến động",
        "question_en": "Number of employees hired each year and historical recruitment trend",
        "intent_explanation": "Trích xuất YEAR từ hire_date và GROUP BY theo năm tăng dần, không dùng LIMIT 10.",
        "sql_mysql": """SELECT 
    YEAR(hire_date) AS HireYear,
    COUNT(*) AS NewHiresCount
FROM employees
GROUP BY YEAR(hire_date)
ORDER BY HireYear ASC;""",
        "sql_sqlite": """SELECT 
    strftime('%Y', hire_date) AS HireYear,
    COUNT(*) AS NewHiresCount
FROM employees
GROUP BY strftime('%Y', hire_date)
ORDER BY HireYear ASC;"""
    },
    {
        "id": "emp_dept_transfers_in_top",
        "domain": "employees",
        "category": "mobility",
        "tags": ["chuyển đến", "chuyển tới", "luân chuyển đến", "phòng ban", "nhiều nhân viên chuyển đến nhất", "transfer in", "transferred in"],
        "question": "Phòng ban nào có nhiều nhân viên chuyển đến nhất?",
        "question_en": "Which department has received the most transferred employees?",
        "intent_explanation": "Xác định các lượt chuyển phòng ban không phải là phòng ban đầu tiên (rn > 1) và gom nhóm theo phòng ban tiếp nhận.",
        "sql_mysql": """WITH EmployeeDeptRank AS (
    SELECT 
        emp_no, 
        dept_no, 
        ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
    FROM dept_emp
)
SELECT 
    d.dept_no,
    d.dept_name AS Department,
    COUNT(DISTINCT edr.emp_no) AS TransferredInCount
FROM EmployeeDeptRank edr
JOIN departments d ON edr.dept_no = d.dept_no
WHERE edr.rn > 1
GROUP BY d.dept_no, d.dept_name
ORDER BY TransferredInCount DESC
LIMIT 1;""",
        "sql_sqlite": """WITH EmployeeDeptRank AS (
    SELECT 
        emp_no, 
        dept_no, 
        ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
    FROM dept_emp
)
SELECT 
    d.dept_no,
    d.dept_name AS Department,
    COUNT(DISTINCT edr.emp_no) AS TransferredInCount
FROM EmployeeDeptRank edr
JOIN departments d ON edr.dept_no = d.dept_no
WHERE edr.rn > 1
GROUP BY d.dept_no, d.dept_name
ORDER BY TransferredInCount DESC
LIMIT 1;"""
    },
    {
        "id": "emp_dept_transfers_out_top",
        "domain": "employees",
        "category": "mobility",
        "tags": ["chuyển đi", "rời khỏi", "luân chuyển đi", "phòng ban", "nhiều nhân viên chuyển đi nhất", "transfer out", "transferred out"],
        "question": "Phòng ban nào có nhiều nhân viên chuyển đi nhất?",
        "question_en": "Which department had the most employees transfer out?",
        "intent_explanation": "Xác định phòng ban khởi đầu (rn = 1) của các nhân viên từng làm việc ở >= 2 phòng ban.",
        "sql_mysql": """WITH EmployeeDeptRank AS (
    SELECT 
        emp_no, 
        dept_no, 
        ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
    FROM dept_emp
),
MultiDeptEmployees AS (
    SELECT emp_no
    FROM dept_emp
    GROUP BY emp_no
    HAVING COUNT(DISTINCT dept_no) > 1
)
SELECT 
    d.dept_no,
    d.dept_name AS Department,
    COUNT(DISTINCT edr.emp_no) AS TransferredOutCount
FROM EmployeeDeptRank edr
JOIN MultiDeptEmployees mde ON edr.emp_no = mde.emp_no
JOIN departments d ON edr.dept_no = d.dept_no
WHERE edr.rn = 1
GROUP BY d.dept_no, d.dept_name
ORDER BY TransferredOutCount DESC
LIMIT 1;""",
        "sql_sqlite": """WITH EmployeeDeptRank AS (
    SELECT 
        emp_no, 
        dept_no, 
        ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
    FROM dept_emp
),
MultiDeptEmployees AS (
    SELECT emp_no
    FROM dept_emp
    GROUP BY emp_no
    HAVING COUNT(DISTINCT dept_no) > 1
)
SELECT 
    d.dept_no,
    d.dept_name AS Department,
    COUNT(DISTINCT edr.emp_no) AS TransferredOutCount
FROM EmployeeDeptRank edr
JOIN MultiDeptEmployees mde ON edr.emp_no = mde.emp_no
JOIN departments d ON edr.dept_no = d.dept_no
WHERE edr.rn = 1
GROUP BY d.dept_no, d.dept_name
ORDER BY TransferredOutCount DESC
LIMIT 1;"""
    },
    {
        "id": "emp_dept_manager_female_rank",
        "domain": "employees",
        "category": "manager_gender_rank",
        "tags": [
            "quản lý nữ", "quản lí nữ", "quản lý nam", "quản lí nam", "nhiều quản lý nữ nhất", "nhiều quản lí nữ nhất",
            "nhiều quản lý nam nhất", "nhiều quản lí nam nhất", "trưởng phòng nữ", "trưởng phòng nam", "ban quản lý", "dept_manager"
        ],
        "question": "Phòng ban nào có nhiều quản lí Nữ nhất?",
        "question_en": "Which department has the most female managers?",
        "intent_explanation": "Join departments với dept_manager và employees để thống kê số lượng và tỷ lệ quản lý Nam, Nữ theo từng phòng ban, sắp xếp theo số lượng quản lý Nữ giảm dần.",
        "sql_mysql": """SELECT 
    d.dept_name AS Department,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
    COUNT(*) AS TotalManagers,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct
FROM departments d
JOIN dept_manager dm ON d.dept_no = dm.dept_no
JOIN employees e ON dm.emp_no = e.emp_no
GROUP BY d.dept_name
ORDER BY FemaleManagers DESC, d.dept_name ASC;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
    COUNT(*) AS TotalManagers,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct
FROM departments d
JOIN dept_manager dm ON d.dept_no = dm.dept_no
JOIN employees e ON dm.emp_no = e.emp_no
GROUP BY d.dept_name
ORDER BY FemaleManagers DESC, d.dept_name ASC;"""
    },
    {
        "id": "emp_recent_manager_gender_promotion",
        "domain": "employees",
        "category": "manager_gender_promotion",
        "tags": [
            "so sánh số lượng nhân sự nam và nữ", "bổ nhiệm lên vị trí quản lý", "trong 5 năm gần nhất",
            "vị trí quản lý trong 5 năm gần nhất", "quản lý nam và nữ trong 5 năm", "bổ nhiệm quản lý",
            "5 năm gần nhất của công ty", "manager promotion recent 5 years"
        ],
        "question": "So sánh số lượng nhân sự nam và nữ được bổ nhiệm lên vị trí Quản lý (Manager) trong 5 năm gần nhất của công ty?",
        "question_en": "Compare the number of male and female personnel appointed to Manager positions in the company's last 5 years?",
        "intent_explanation": "Dùng recursive CTE để tạo danh sách 5 năm liên tục gần nhất so với mốc bổ nhiệm mới nhất trong dept_manager, sau đó LEFT JOIN với thống kê bổ nhiệm nam/nữ để đảm bảo không bị khuyết thiếu các năm có 0 lượt bổ nhiệm.",
        "sql_mysql": """WITH RECURSIVE YearRange AS (
    SELECT (SELECT MAX(YEAR(from_date)) - 4 FROM dept_manager) AS Year
    UNION ALL
    SELECT Year + 1 FROM YearRange WHERE Year < (SELECT MAX(YEAR(from_date)) FROM dept_manager)
),
ManagerPromotions AS (
    SELECT 
        YEAR(dm.from_date) AS PromoYear,
        SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
        SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
        COUNT(*) AS TotalManagers
    FROM dept_manager dm
    JOIN employees e ON dm.emp_no = e.emp_no
    WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - 4
    GROUP BY YEAR(dm.from_date)
)
SELECT 
    yr.Year,
    COALESCE(mp.MaleManagers, 0) AS MaleManagers,
    COALESCE(mp.FemaleManagers, 0) AS FemaleManagers,
    COALESCE(mp.TotalManagers, 0) AS TotalManagers,
    COALESCE(ROUND(mp.MaleManagers * 100.0 / NULLIF(mp.TotalManagers, 0), 1), 0.0) AS MalePct,
    COALESCE(ROUND(mp.FemaleManagers * 100.0 / NULLIF(mp.TotalManagers, 0), 1), 0.0) AS FemalePct
FROM YearRange yr
LEFT JOIN ManagerPromotions mp ON yr.Year = mp.PromoYear
ORDER BY yr.Year ASC;""",
        "sql_sqlite": """WITH RECURSIVE YearRange AS (
    SELECT (SELECT MAX(CAST(strftime('%Y', from_date) AS INTEGER)) - 4 FROM dept_manager) AS Year
    UNION ALL
    SELECT Year + 1 FROM YearRange WHERE Year < (SELECT MAX(CAST(strftime('%Y', from_date) AS INTEGER)) FROM dept_manager)
),
ManagerPromotions AS (
    SELECT 
        CAST(strftime('%Y', dm.from_date) AS INTEGER) AS PromoYear,
        SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
        SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
        COUNT(*) AS TotalManagers
    FROM dept_manager dm
    JOIN employees e ON dm.emp_no = e.emp_no
    WHERE CAST(strftime('%Y', dm.from_date) AS INTEGER) >= (SELECT MAX(CAST(strftime('%Y', from_date) AS INTEGER)) FROM dept_manager) - 4
    GROUP BY CAST(strftime('%Y', dm.from_date) AS INTEGER)
)
SELECT 
    yr.Year,
    COALESCE(mp.MaleManagers, 0) AS MaleManagers,
    COALESCE(mp.FemaleManagers, 0) AS FemaleManagers,
    COALESCE(mp.TotalManagers, 0) AS TotalManagers,
    COALESCE(ROUND(mp.MaleManagers * 100.0 / NULLIF(mp.TotalManagers, 0), 1), 0.0) AS MalePct,
    COALESCE(ROUND(mp.FemaleManagers * 100.0 / NULLIF(mp.TotalManagers, 0), 1), 0.0) AS FemalePct
FROM YearRange yr
LEFT JOIN ManagerPromotions mp ON yr.Year = mp.PromoYear
ORDER BY yr.Year ASC;"""
    },
    {
        "id": "emp_promoted_managers_after_year",
        "domain": "employees",
        "category": "promoted_managers",
        "tags": [
            "những nhân viên nào", "tuyển dụng sau năm 1990", "xuất sắc được thăng chức", "vị trí quản lý",
            "manager", "thăng chức lên vị trí quản lý", "tuyển dụng sau", "bổ nhiệm lên quản lý"
        ],
        "question": "Những nhân viên nào được tuyển dụng sau năm 1990 nhưng đã xuất sắc được thăng chức lên vị trí Quản lý (Manager)?",
        "question_en": "Which employees were hired after 1990 but were promoted to Manager positions?",
        "intent_explanation": "Trích xuất danh sách cá nhân nhân sự có ngày tuyển dụng sau năm 1990 (YEAR(e.hire_date) > 1990), join với bảng titles (title = 'Manager'), dept_manager và departments để lấy thông tin chi tiết về phòng ban quản lý và ngày bổ nhiệm.",
        "sql_mysql": """SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    e.gender AS Gender,
    e.hire_date AS HireDate,
    d.dept_name AS Department,
    COALESCE(t_init.title, 'Khởi điểm Quản lý') AS InitialTitle,
    t_mgr.title AS PromotedTitle,
    dm.from_date AS PromotionDate,
    s.salary AS CurrentSalary
FROM employees e
JOIN titles t_mgr ON e.emp_no = t_mgr.emp_no AND t_mgr.title = 'Manager'
LEFT JOIN titles t_init ON e.emp_no = t_init.emp_no AND t_init.from_date = e.hire_date AND t_init.title != 'Manager'
JOIN dept_manager dm ON e.emp_no = dm.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
LEFT JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE YEAR(e.hire_date) > 1990
ORDER BY e.hire_date ASC;""",
        "sql_sqlite": """SELECT 
    e.emp_no,
    (e.first_name || ' ' || e.last_name) AS FullName,
    e.gender AS Gender,
    e.hire_date AS HireDate,
    d.dept_name AS Department,
    COALESCE(t_init.title, 'Khởi điểm Quản lý') AS InitialTitle,
    t_mgr.title AS PromotedTitle,
    dm.from_date AS PromotionDate,
    s.salary AS CurrentSalary
FROM employees e
JOIN titles t_mgr ON e.emp_no = t_mgr.emp_no AND t_mgr.title = 'Manager'
LEFT JOIN titles t_init ON e.emp_no = t_init.emp_no AND t_init.from_date = e.hire_date AND t_init.title != 'Manager'
JOIN dept_manager dm ON e.emp_no = dm.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
LEFT JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE CAST(strftime('%Y', e.hire_date) AS INTEGER) > 1990
ORDER BY e.hire_date ASC;"""
    },
    {
        "id": "emp_time_to_promotion_by_dept",
        "domain": "employees",
        "category": "promotion_time_by_dept",
        "tags": [
            "thời gian để thăng chức", "thời gian thăng chức", "thăng chức khác nhau", "giữa các phòng ban",
            "thời gian thăng chức giữa các phòng ban", "thăng tiến", "thời gian thăng tiến", "time to promotion",
            "đổi chức danh", "thời gian chuyển chức danh", "bao lâu để thăng chức"
        ],
        "question": "Thời gian để thăng chức khác nhau như thế nào giữa các phòng ban",
        "question_en": "How does time to promotion differ across departments?",
        "intent_explanation": "Xác định các nhân viên đã được thăng chức (chuyển từ chức danh khởi đầu rn=1 sang chức danh tiếp theo rn=2), tính số ngày/năm thăng chức, sau đó join với dept_emp và departments để tính thời gian thăng chức trung bình theo từng phòng ban.",
        "sql_mysql": """WITH RankedTitles AS (
    SELECT 
        emp_no,
        title,
        from_date,
        ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
    FROM titles
),
PromotionTime AS (
    SELECT 
        t1.emp_no,
        t1.title AS InitialTitle,
        t2.title AS PromotedTitle,
        DATEDIFF(t2.from_date, t1.from_date) AS DaysToPromotion,
        ROUND(DATEDIFF(t2.from_date, t1.from_date) / 365.25, 2) AS YearsToPromotion
    FROM RankedTitles t1
    JOIN RankedTitles t2 ON t1.emp_no = t2.emp_no AND t1.rn = 1 AND t2.rn = 2
)
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT pt.emp_no) AS PromotedEmployeesCount,
    ROUND(AVG(pt.YearsToPromotion), 2) AS AvgYearsToPromotion,
    ROUND(AVG(pt.DaysToPromotion), 0) AS AvgDaysToPromotion,
    ROUND(MIN(pt.YearsToPromotion), 2) AS MinYearsToPromotion,
    ROUND(MAX(pt.YearsToPromotion), 2) AS MaxYearsToPromotion
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN PromotionTime pt ON de.emp_no = pt.emp_no
GROUP BY d.dept_name
ORDER BY AvgYearsToPromotion ASC;""",
        "sql_sqlite": """WITH RankedTitles AS (
    SELECT 
        emp_no,
        title,
        from_date,
        ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) AS rn
    FROM titles
),
PromotionTime AS (
    SELECT 
        t1.emp_no,
        t1.title AS InitialTitle,
        t2.title AS PromotedTitle,
        (julianday(t2.from_date) - julianday(t1.from_date)) AS DaysToPromotion,
        ROUND((julianday(t2.from_date) - julianday(t1.from_date)) / 365.25, 2) AS YearsToPromotion
    FROM RankedTitles t1
    JOIN RankedTitles t2 ON t1.emp_no = t2.emp_no AND t1.rn = 1 AND t2.rn = 2
)
SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT pt.emp_no) AS PromotedEmployeesCount,
    ROUND(AVG(pt.YearsToPromotion), 2) AS AvgYearsToPromotion,
    ROUND(AVG(pt.DaysToPromotion), 0) AS AvgDaysToPromotion,
    ROUND(MIN(pt.YearsToPromotion), 2) AS MinYearsToPromotion,
    ROUND(MAX(pt.YearsToPromotion), 2) AS MaxYearsToPromotion
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN PromotionTime pt ON de.emp_no = pt.emp_no
GROUP BY d.dept_name
ORDER BY AvgYearsToPromotion ASC;"""
    },
    {
        "id": "emp_multiple_titles_progression_detail",
        "domain": "employees",
        "category": "title_progression",
        "tags": [
            "trải qua ít nhất 3 chức danh", "ít nhất 3 chức danh", "nhiều chức danh", "lộ trình chức danh",
            "chức danh đầu tiên", "chức danh hiện tại", "thời gian bắt đầu", "3 titles", "career progression",
            "thay đổi chức danh", "ít nhất ba chức danh"
        ],
        "question": "Liệt kê những nhân viên đã từng trải qua ít nhất 3 chức danh (titles) khác nhau kể từ khi gia nhập công ty, hiển thị thời gian bắt đầu chức danh đầu tiên và chức danh hiện tại.",
        "question_en": "List employees who have held at least 3 distinct titles since joining the company, showing the start date of their initial title and current title.",
        "intent_explanation": "Đếm số chức danh khác nhau của mỗi nhân viên trong bảng titles (HAVING COUNT(DISTINCT title) >= 3), xếp hạng thứ tự thời gian chức danh (rn_first = 1 cho chức danh đầu tiên, rn_last = 1 cho chức danh hiện tại/mới nhất), sau đó kết hợp với bảng employees để lấy thông tin chi tiết.",
        "sql_mysql": """WITH TitleCounts AS (
    SELECT 
        emp_no,
        COUNT(DISTINCT title) AS TitleCount
    FROM titles
    GROUP BY emp_no
    HAVING COUNT(DISTINCT title) >= 3
),
RankedTitles AS (
    SELECT 
        t.emp_no,
        t.title,
        t.from_date,
        ROW_NUMBER() OVER (PARTITION BY t.emp_no ORDER BY t.from_date ASC) AS rn_first,
        ROW_NUMBER() OVER (PARTITION BY t.emp_no ORDER BY t.from_date DESC) AS rn_last
    FROM titles t
    JOIN TitleCounts tc ON t.emp_no = tc.emp_no
)
SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    tc.TitleCount,
    t_first.title AS InitialTitle,
    t_first.from_date AS InitialTitleStartDate,
    t_last.title AS CurrentTitle,
    t_last.from_date AS CurrentTitleStartDate
FROM TitleCounts tc
JOIN employees e ON tc.emp_no = e.emp_no
JOIN RankedTitles t_first ON tc.emp_no = t_first.emp_no AND t_first.rn_first = 1
JOIN RankedTitles t_last ON tc.emp_no = t_last.emp_no AND t_last.rn_last = 1
ORDER BY tc.TitleCount DESC, t_last.from_date DESC
LIMIT 10;""",
        "sql_sqlite": """WITH TitleCounts AS (
    SELECT 
        emp_no,
        COUNT(DISTINCT title) AS TitleCount
    FROM titles
    GROUP BY emp_no
    HAVING COUNT(DISTINCT title) >= 3
),
RankedTitles AS (
    SELECT 
        t.emp_no,
        t.title,
        t.from_date,
        ROW_NUMBER() OVER (PARTITION BY t.emp_no ORDER BY t.from_date ASC) AS rn_first,
        ROW_NUMBER() OVER (PARTITION BY t.emp_no ORDER BY t.from_date DESC) AS rn_last
    FROM titles t
    JOIN TitleCounts tc ON t.emp_no = tc.emp_no
)
SELECT 
    e.emp_no,
    (e.first_name || ' ' || e.last_name) AS FullName,
    tc.TitleCount,
    t_first.title AS InitialTitle,
    t_first.from_date AS InitialTitleStartDate,
    t_last.title AS CurrentTitle,
    t_last.from_date AS CurrentTitleStartDate
FROM TitleCounts tc
JOIN employees e ON tc.emp_no = e.emp_no
JOIN RankedTitles t_first ON tc.emp_no = t_first.emp_no AND t_first.rn_first = 1
JOIN RankedTitles t_last ON tc.emp_no = t_last.emp_no AND t_last.rn_last = 1
ORDER BY tc.TitleCount DESC, t_last.from_date DESC
LIMIT 10;"""
    },
    {
        "id": "emp_tenure_cohort_salary_dept",
        "domain": "employees",
        "category": "tenure_cohort_comparison",
        "tags": [
            "kỳ cựu", "mới vào", "dưới 2 năm", "trên 7 năm", "nén lương", "thâm niên", "phòng kỹ thuật",
            "development", "so sánh lương", "tenure cohort", "salary compression"
        ],
        "question": "So sánh mức lương trung bình của nhóm nhân viên mới vào dưới 2 năm với nhóm nhân viên kỳ cựu trên 7 năm tại phòng Kỹ thuật (Development) để đánh giá xem có hiện tượng nén lương không?",
        "question_en": "Compare average salaries between new hires (< 2 years) and senior employees (> 7 years) in the Development department to evaluate salary compression.",
        "intent_explanation": "Tính thâm niên nhân viên so với ngày tuyển dụng tối đa (SELECT MAX(hire_date) FROM employees), phân nhóm kỳ cựu (> 7 năm) và mới vào (< 2 năm), lọc chính xác phòng Development và tính chênh lệch lương.",
        "sql_mysql": """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 7 THEN s.salary END), 2) AS SeniorAvgSalary,
    ROUND(AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END), 2) AS NewHireAvgSalary,
    ROUND(AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 7 THEN s.salary END) - 
          AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END), 2) AS SalaryDifference,
    ROUND((AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 7 THEN s.salary END) - 
           AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END)) * 100.0 / 
           AVG(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN s.salary END), 2) AS DifferencePercentage,
    COUNT(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > 7 THEN 1 END) AS SeniorCount,
    COUNT(CASE WHEN DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < 2 THEN 1 END) AS NewHireCount
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE d.dept_name = 'Development'
GROUP BY d.dept_name;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 7 THEN s.salary END), 2) AS SeniorAvgSalary,
    ROUND(AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END), 2) AS NewHireAvgSalary,
    ROUND(AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 7 THEN s.salary END) - 
          AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END), 2) AS SalaryDifference,
    ROUND((AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 7 THEN s.salary END) - 
           AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END)) * 100.0 / 
           AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END), 2) AS DifferencePercentage,
    COUNT(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 7 THEN 1 END) AS SeniorCount,
    COUNT(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN 1 END) AS NewHireCount
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE d.dept_name = 'Development'
GROUP BY d.dept_name;"""
    },
    {
        "id": "emp_tenure_cohort_salary_all",
        "domain": "employees",
        "category": "tenure_cohort_comparison",
        "tags": [
            "kỳ cựu", "mới vào", "dưới 2 năm", "trên 5 năm", "thâm niên", "từng phòng ban",
            "so sánh lương", "tenure cohort", "nén lương"
        ],
        "question": "So sánh mức lương trung bình giữa nhân viên kỳ cựu trên 5 năm và nhân viên mới vào dưới 2 năm theo từng phòng ban",
        "question_en": "Compare average salary between senior employees (> 5 years) and new hires (< 2 years) across departments.",
        "intent_explanation": "Tính thâm niên nhân viên so với ngày tuyển dụng tối đa (SELECT MAX(hire_date) FROM employees), phân nhóm kỳ cựu (> 5 năm) và mới vào (< 2 năm) theo từng phòng ban, sắp xếp theo độ chênh lệch lương giảm dần.",
        "sql_mysql": """SELECT 
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
ORDER BY SalaryDifference DESC;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 5 THEN s.salary END), 2) AS SeniorAvgSalary,
    ROUND(AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END), 2) AS NewHireAvgSalary,
    ROUND(AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 5 THEN s.salary END) - 
          AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END), 2) AS SalaryDifference,
    ROUND((AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 5 THEN s.salary END) - 
           AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END)) * 100.0 / 
           AVG(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN s.salary END), 2) AS DifferencePercentage,
    COUNT(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > 5 THEN 1 END) AS SeniorCount,
    COUNT(CASE WHEN (julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < 2 THEN 1 END) AS NewHireCount
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalaryDifference DESC;"""
    },
    {
        "id": "emp_department_group_salary_comparison",
        "domain": "employees",
        "category": "department_group_comparison",
        "tags": [
            "khối kỹ thuật", "khối thương mại", "khối kinh doanh", "development, research", "sales, marketing",
            "so sánh mức lương trung bình", "lương cao nhất", "tổng quỹ lương", "quỹ lương", "departmentgroup",
            "giữa khối kỹ thuật và khối thương mại", "so sánh giữa hai khối"
        ],
        "question": "So sánh mức lương trung bình, lương cao nhất và tổng quỹ lương giữa Khối Kỹ thuật (Development, Research) và Khối Thương mại (Sales, Marketing).",
        "question_en": "Compare average salary, maximum salary, and total payroll between Technical Block (Development, Research) and Commercial Block (Sales, Marketing).",
        "intent_explanation": "Phân loại 4 phòng ban vào 2 Khối (DepartmentGroup) bằng CASE WHEN, kết hợp bảng dept_emp và salaries với to_date = '9999-01-01' để tính Quy mô nhân sự (Headcount), Lương trung bình (AvgSalary), Lương cao nhất (MaxSalary) và Tổng quỹ lương (TotalPayroll).",
        "sql_mysql": """SELECT 
    CASE 
        WHEN d.dept_name IN ('Sales', 'Marketing') THEN 'Khối Thương mại (Sales, Marketing)'
        WHEN d.dept_name IN ('Development', 'Research') THEN 'Khối Kỹ thuật (Development, Research)'
    END AS DepartmentGroup,
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    SUM(s.salary) AS TotalPayroll
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE d.dept_name IN ('Development', 'Research', 'Sales', 'Marketing')
GROUP BY DepartmentGroup, d.dept_name
ORDER BY DepartmentGroup, AvgSalary DESC;""",
        "sql_sqlite": """SELECT 
    CASE 
        WHEN d.dept_name IN ('Sales', 'Marketing') THEN 'Khối Thương mại (Sales, Marketing)'
        WHEN d.dept_name IN ('Development', 'Research') THEN 'Khối Kỹ thuật (Development, Research)'
    END AS DepartmentGroup,
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    SUM(s.salary) AS TotalPayroll
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE d.dept_name IN ('Development', 'Research', 'Sales', 'Marketing')
GROUP BY DepartmentGroup, d.dept_name
ORDER BY DepartmentGroup, AvgSalary DESC;"""
    },
    {
        "id": "emp_inflow_outflow_yearly",
        "domain": "employees",
        "category": "headcount_movement",
        "tags": ["nhân sự vào", "nhân sự ra", "vào và ra", "tuyển dụng", "rời đi", "biến động", "inflow", "outflow", "tăng giảm", "net change"],
        "question": "Thống kê nhân sự vào và nhân sự ra năm 1999 và năm 2000",
        "question_en": "Statistics of joined (hires) and left (departures) employees in 1999 and 2000",
        "intent_explanation": "Nhân sự vào (JoinedCount) tính từ hire_date trong bảng employees. Nhân sự ra (LeftCount) tính từ to_date != '9999-01-01' trong bảng dept_emp. Kết hợp qua CTE và lọc chính xác các năm được yêu cầu bằng WHERE ay.Year IN (1999, 2000).",
        "sql_mysql": """WITH YearlyJoined AS (
    SELECT 
        YEAR(e.hire_date) AS Year,
        COUNT(DISTINCT e.emp_no) AS JoinedCount
    FROM employees e
    GROUP BY YEAR(e.hire_date)
),
YearlyLeft AS (
    SELECT 
        YEAR(de.to_date) AS Year,
        COUNT(DISTINCT de.emp_no) AS LeftCount
    FROM dept_emp de
    WHERE de.to_date != '9999-01-01'
    GROUP BY YEAR(de.to_date)
),
AllYears AS (
    SELECT Year FROM YearlyJoined
    UNION
    SELECT Year FROM YearlyLeft
)
SELECT 
    ay.Year,
    COALESCE(yj.JoinedCount, 0) AS JoinedCount,
    COALESCE(yl.LeftCount, 0) AS LeftCount,
    (COALESCE(yj.JoinedCount, 0) - COALESCE(yl.LeftCount, 0)) AS NetChange
FROM AllYears ay
LEFT JOIN YearlyJoined yj ON ay.Year = yj.Year
LEFT JOIN YearlyLeft yl ON ay.Year = yl.Year
WHERE ay.Year IN (1999, 2000)
ORDER BY ay.Year ASC;""",
        "sql_sqlite": """WITH YearlyJoined AS (
    SELECT 
        CAST(strftime('%Y', e.hire_date) AS INTEGER) AS Year,
        COUNT(DISTINCT e.emp_no) AS JoinedCount
    FROM employees e
    GROUP BY CAST(strftime('%Y', e.hire_date) AS INTEGER)
),
YearlyLeft AS (
    SELECT 
        CAST(strftime('%Y', de.to_date) AS INTEGER) AS Year,
        COUNT(DISTINCT de.emp_no) AS LeftCount
    FROM dept_emp de
    WHERE de.to_date != '9999-01-01'
    GROUP BY CAST(strftime('%Y', de.to_date) AS INTEGER)
),
AllYears AS (
    SELECT Year FROM YearlyJoined
    UNION
    SELECT Year FROM YearlyLeft
)
SELECT 
    ay.Year,
    COALESCE(yj.JoinedCount, 0) AS JoinedCount,
    COALESCE(yl.LeftCount, 0) AS LeftCount,
    (COALESCE(yj.JoinedCount, 0) - COALESCE(yl.LeftCount, 0)) AS NetChange
FROM AllYears ay
LEFT JOIN YearlyJoined yj ON ay.Year = yj.Year
LEFT JOIN YearlyLeft yl ON ay.Year = yl.Year
WHERE ay.Year IN (1999, 2000)
ORDER BY ay.Year ASC;"""
    },
    {
        "id": "emp_manager_tenure_vs_turnover",
        "domain": "employees",
        "category": "manager_tenure_turnover",
        "tags": [
            "thâm niên của quản lý", "thâm niên quản lý", "tác động đến tỷ lệ", "ảnh hưởng đến tỷ lệ",
            "tỷ lệ nhân sự nghỉ việc", "tỉ lệ nhân sự nghỉ việc", "tỷ lệ nghỉ việc", "tỉ lệ nghỉ việc",
            "nghỉ việc", "rời đi", "rời khỏi", "turnover rate", "attrition rate", "resignation rate",
            "thâm niên quản lý và nghỉ việc", "tác động của thâm niên", "mối quan hệ giữa thâm niên và nghỉ việc"
        ],
        "question": "thâm niên của quản lý có tác động đến tỷ lệ nhân sự nghỉ việc không",
        "question_en": "Does manager tenure impact employee turnover rate across departments?",
        "intent_explanation": "Thống kê thâm niên của từng Trưởng phòng hiện tại (ManagerTenureYears) và tỷ lệ nhân sự nghỉ việc theo từng phòng ban (TurnoverRatePercent = ResignedEmployees / TotalEmployees * 100) để phân tích mối tương quan và tác động điều hành.",
        "sql_mysql": """WITH DeptTurnover AS (
    SELECT 
        de.dept_no,
        COUNT(DISTINCT de.emp_no) AS TotalEmployees,
        COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) AS ResignedEmployees,
        COUNT(DISTINCT CASE WHEN de.to_date = '9999-01-01' THEN de.emp_no END) AS ActiveEmployees,
        ROUND(COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) * 100.0 / COUNT(DISTINCT de.emp_no), 2) AS TurnoverRatePercent
    FROM dept_emp de
    GROUP BY de.dept_no
),
CurrentManager AS (
    SELECT 
        dm.dept_no,
        CONCAT(em.first_name, ' ', em.last_name) AS ManagerName,
        ROUND(DATEDIFF(IF(dm.to_date = '9999-01-01', '2002-08-01', dm.to_date), dm.from_date) / 365.25, 2) AS ManagerTenureYears,
        ROUND(DATEDIFF(IF(dm.to_date = '9999-01-01', '2002-08-01', dm.to_date), em.hire_date) / 365.25, 2) AS ManagerTotalTenureYears
    FROM dept_manager dm
    JOIN employees em ON dm.emp_no = em.emp_no
    WHERE dm.to_date = '9999-01-01'
)
SELECT 
    d.dept_name AS Department,
    cm.ManagerName,
    cm.ManagerTenureYears,
    dt.TotalEmployees,
    dt.ResignedEmployees,
    dt.ActiveEmployees,
    dt.TurnoverRatePercent
FROM departments d
JOIN DeptTurnover dt ON d.dept_no = dt.dept_no
JOIN CurrentManager cm ON d.dept_no = cm.dept_no
ORDER BY dt.TurnoverRatePercent DESC;""",
        "sql_sqlite": """WITH DeptTurnover AS (
    SELECT 
        de.dept_no,
        COUNT(DISTINCT de.emp_no) AS TotalEmployees,
        COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) AS ResignedEmployees,
        COUNT(DISTINCT CASE WHEN de.to_date = '9999-01-01' THEN de.emp_no END) AS ActiveEmployees,
        ROUND(COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) * 100.0 / COUNT(DISTINCT de.emp_no), 2) AS TurnoverRatePercent
    FROM dept_emp de
    GROUP BY de.dept_no
),
CurrentManager AS (
    SELECT 
        dm.dept_no,
        em.first_name || ' ' || em.last_name AS ManagerName,
        ROUND((julianday(CASE WHEN dm.to_date = '9999-01-01' THEN '2002-08-01' ELSE dm.to_date END) - julianday(dm.from_date)) / 365.25, 2) AS ManagerTenureYears,
        ROUND((julianday(CASE WHEN dm.to_date = '9999-01-01' THEN '2002-08-01' ELSE dm.to_date END) - julianday(em.hire_date)) / 365.25, 2) AS ManagerTotalTenureYears
    FROM dept_manager dm
    JOIN employees em ON dm.emp_no = em.emp_no
    WHERE dm.to_date = '9999-01-01'
)
SELECT 
    d.dept_name AS Department,
    cm.ManagerName,
    cm.ManagerTenureYears,
    dt.TotalEmployees,
    dt.ResignedEmployees,
    dt.ActiveEmployees,
    dt.TurnoverRatePercent
FROM departments d
JOIN DeptTurnover dt ON d.dept_no = dt.dept_no
JOIN CurrentManager cm ON d.dept_no = cm.dept_no
ORDER BY dt.TurnoverRatePercent DESC;"""
    },
    {
        "id": "emp_dept_turnover_rate",
        "domain": "employees",
        "category": "dept_turnover_rate",
        "tags": [
            "tỷ lệ nghỉ việc", "tỉ lệ nghỉ việc", "tỷ lệ nhân sự nghỉ việc", "tỉ lệ nhân sự nghỉ việc",
            "tỷ lệ rời đi", "tỉ lệ rời đi", "turnover rate", "attrition rate", "resignation rate",
            "phòng ban có tỷ lệ nghỉ việc cao nhất", "tỷ lệ nghỉ việc theo phòng ban"
        ],
        "question": "Tỷ lệ nhân sự nghỉ việc theo từng phòng ban là bao nhiêu?",
        "question_en": "What is the employee turnover rate by department?",
        "intent_explanation": "Join departments với dept_emp để đếm tổng số nhân sự từng thuộc phòng ban và số nhân sự đã rời đi (to_date != '9999-01-01'), từ đó tính tỷ lệ nghỉ việc (%) theo từng phòng ban.",
        "sql_mysql": """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS TotalEmployees,
    COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) AS ResignedEmployees,
    COUNT(DISTINCT CASE WHEN de.to_date = '9999-01-01' THEN de.emp_no END) AS ActiveEmployees,
    ROUND(COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) * 100.0 / COUNT(DISTINCT de.emp_no), 2) AS TurnoverRatePercent
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no
GROUP BY d.dept_no, d.dept_name
ORDER BY TurnoverRatePercent DESC;""",
        "sql_sqlite": """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS TotalEmployees,
    COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) AS ResignedEmployees,
    COUNT(DISTINCT CASE WHEN de.to_date = '9999-01-01' THEN de.emp_no END) AS ActiveEmployees,
    ROUND(COUNT(DISTINCT CASE WHEN de.to_date != '9999-01-01' THEN de.emp_no END) * 100.0 / COUNT(DISTINCT de.emp_no), 2) AS TurnoverRatePercent
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no
GROUP BY d.dept_no, d.dept_name
ORDER BY TurnoverRatePercent DESC;"""
    },

    # =========================================================================
    # NHÓM 2: CSDL AWESOME CHOCOLATES (KINH DOANH, ĐỘI NGŨ & SẢN PHẨM)
    # =========================================================================
    {
        "id": "choco_quarterly_top5_consistency",
        "domain": "awesome_chocolates",
        "category": "quarterly_consistency",
        "tags": ["top 5", "tất cả các quý", "4 quý", "quý", "sản phẩm", "ổn định", "nhất quán", "quarterly", "luôn nằm trong top 5"],
        "question": "Xác định sản phẩm luôn nằm trong top 5 ở tất cả các quý trong năm 2022",
        "question_en": "Identify products that consistently ranked in the top 5 across all 4 quarters of 2022",
        "intent_explanation": "Tính doanh số theo từng quý cho mỗi sản phẩm, dùng DENSE_RANK() để xếp hạng trong mỗi quý, sau đó lọc các sản phẩm có Rank <= 5 ở đủ cả 4 quý.",
        "sql_mysql": """WITH QuarterlyProductSales AS (
    SELECT 
        p.PID,
        p.Product,
        QUARTER(s.SaleDate) AS SalesQuarter,
        SUM(s.Amount) AS TotalRevenue,
        DENSE_RANK() OVER (
            PARTITION BY QUARTER(s.SaleDate) 
            ORDER BY SUM(s.Amount) DESC
        ) AS QtrRank
    FROM products p
    JOIN sales s ON p.PID = s.PID
    WHERE YEAR(s.SaleDate) = 2022
    GROUP BY p.PID, p.Product, QUARTER(s.SaleDate)
),
Top5Quarterly AS (
    SELECT PID, Product, SalesQuarter
    FROM QuarterlyProductSales
    WHERE QtrRank <= 5
)
SELECT 
    Product,
    COUNT(DISTINCT SalesQuarter) AS QuartersInTop5
FROM Top5Quarterly
GROUP BY PID, Product
HAVING COUNT(DISTINCT SalesQuarter) = 4;""",
        "sql_sqlite": """WITH QuarterlyProductSales AS (
    SELECT 
        p.PID,
        p.Product,
        CAST((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3 AS INTEGER) AS SalesQuarter,
        SUM(s.Amount) AS TotalRevenue,
        DENSE_RANK() OVER (
            PARTITION BY CAST((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3 AS INTEGER) 
            ORDER BY SUM(s.Amount) DESC
        ) AS QtrRank
    FROM products p
    JOIN sales s ON p.PID = s.PID
    WHERE strftime('%Y', s.SaleDate) = '2022'
    GROUP BY p.PID, p.Product, SalesQuarter
),
Top5Quarterly AS (
    SELECT PID, Product, SalesQuarter
    FROM QuarterlyProductSales
    WHERE QtrRank <= 5
)
SELECT 
    Product,
    COUNT(DISTINCT SalesQuarter) AS QuartersInTop5
FROM Top5Quarterly
GROUP BY PID, Product
HAVING COUNT(DISTINCT SalesQuarter) = 4;"""
    },
    {
        "id": "choco_product_quarterly_sales_threshold_consistency",
        "domain": "awesome_chocolates",
        "category": "quarterly_consistency",
        "tags": [
            "doanh số trên 50,000", "trên 50000", "tất cả các quý", "luôn đạt doanh số", "sản phẩm",
            "mỗi quý", "ổn định", "nhất quán", "quarterly sales threshold", "năm 2022", "năm 2021"
        ],
        "question": "Tìm các sản phẩm luôn đạt doanh số trên 50,000 USD trong tất cả các quý của năm 2022.",
        "question_en": "Find products that consistently achieved sales over 50,000 USD in all quarters of 2022.",
        "intent_explanation": "Pivot doanh thu từng quý (Q1, Q2, Q3, Q4) của mỗi sản phẩm trong năm 2022, lọc các sản phẩm luôn vượt ngưỡng $50,000 ở tất cả các quý có phát sinh dữ liệu trong năm.",
        "sql_mysql": """WITH ProductQuarterlySales AS (
    SELECT 
        p.PID,
        p.Product,
        p.Category,
        SUM(CASE WHEN QUARTER(s.SaleDate) = 1 THEN s.Amount ELSE 0 END) AS Q1_Revenue,
        SUM(CASE WHEN QUARTER(s.SaleDate) = 2 THEN s.Amount ELSE 0 END) AS Q2_Revenue,
        SUM(CASE WHEN QUARTER(s.SaleDate) = 3 THEN s.Amount ELSE 0 END) AS Q3_Revenue,
        SUM(CASE WHEN QUARTER(s.SaleDate) = 4 THEN s.Amount ELSE 0 END) AS Q4_Revenue,
        SUM(s.Amount) AS TotalAnnualRevenue
    FROM products p
    JOIN sales s ON p.PID = s.PID
    WHERE YEAR(s.SaleDate) = 2022
    GROUP BY p.PID, p.Product, p.Category
)
SELECT 
    Product,
    Category,
    Q1_Revenue,
    Q2_Revenue,
    Q3_Revenue,
    Q4_Revenue,
    TotalAnnualRevenue
FROM ProductQuarterlySales
WHERE Q1_Revenue > 50000
  AND (Q2_Revenue > 50000 OR (SELECT COUNT(DISTINCT QUARTER(SaleDate)) FROM sales WHERE YEAR(SaleDate) = 2022) < 2)
  AND (Q3_Revenue > 50000 OR (SELECT COUNT(DISTINCT QUARTER(SaleDate)) FROM sales WHERE YEAR(SaleDate) = 2022) < 3)
  AND (Q4_Revenue > 50000 OR (SELECT COUNT(DISTINCT QUARTER(SaleDate)) FROM sales WHERE YEAR(SaleDate) = 2022) < 4)
ORDER BY TotalAnnualRevenue DESC;""",
        "sql_sqlite": """WITH ProductQuarterlySales AS (
    SELECT 
        p.PID,
        p.Product,
        p.Category,
        SUM(CASE WHEN ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = 1 THEN s.Amount ELSE 0 END) AS Q1_Revenue,
        SUM(CASE WHEN ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = 2 THEN s.Amount ELSE 0 END) AS Q2_Revenue,
        SUM(CASE WHEN ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = 3 THEN s.Amount ELSE 0 END) AS Q3_Revenue,
        SUM(CASE WHEN ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = 4 THEN s.Amount ELSE 0 END) AS Q4_Revenue,
        SUM(s.Amount) AS TotalAnnualRevenue
    FROM products p
    JOIN sales s ON p.PID = s.PID
    WHERE strftime('%Y', s.SaleDate) = '2022'
    GROUP BY p.PID, p.Product, p.Category
)
SELECT 
    Product,
    Category,
    Q1_Revenue,
    Q2_Revenue,
    Q3_Revenue,
    Q4_Revenue,
    TotalAnnualRevenue
FROM ProductQuarterlySales
WHERE Q1_Revenue > 50000
  AND (Q2_Revenue > 50000 OR (SELECT COUNT(DISTINCT ((CAST(strftime('%m', SaleDate) AS INTEGER) + 2) / 3)) FROM sales WHERE strftime('%Y', SaleDate) = '2022') < 2)
  AND (Q3_Revenue > 50000 OR (SELECT COUNT(DISTINCT ((CAST(strftime('%m', SaleDate) AS INTEGER) + 2) / 3)) FROM sales WHERE strftime('%Y', SaleDate) = '2022') < 3)
  AND (Q4_Revenue > 50000 OR (SELECT COUNT(DISTINCT ((CAST(strftime('%m', SaleDate) AS INTEGER) + 2) / 3)) FROM sales WHERE strftime('%Y', SaleDate) = '2022') < 4)
ORDER BY TotalAnnualRevenue DESC;"""
    },
    {
        "id": "choco_product_margin_pnl",
        "domain": "awesome_chocolates",
        "category": "margin_pnl",
        "tags": ["tỷ suất lợi nhuận", "biên lợi nhuận", "margin", "lợi nhuận", "giá vốn", "cogs", "chi phí", "pnl", "tỉ suất"],
        "question": "Tính tỷ suất lợi nhuận và doanh thu, giá vốn của từng sản phẩm",
        "question_en": "Calculate profit margin %, revenue, and total cost (COGS) for each product",
        "intent_explanation": "Doanh thu = SUM(Amount), Chi phí giá vốn = SUM(Boxes * Cost_per_box), Lợi nhuận = Doanh thu - Chi phí, Margin % = (Lợi nhuận / Doanh thu) * 100.",
        "sql_mysql": """SELECT 
    p.Product,
    SUM(s.Amount) AS TotalRevenue,
    ROUND(SUM(s.Boxes * p.Cost_per_box), 2) AS TotalCost,
    ROUND(SUM(s.Amount) - SUM(s.Boxes * p.Cost_per_box), 2) AS TotalProfit,
    ROUND(((SUM(s.Amount) - SUM(s.Boxes * p.Cost_per_box)) / SUM(s.Amount)) * 100, 2) AS ProfitMarginPct
FROM products p
JOIN sales s ON p.PID = s.PID
GROUP BY p.PID, p.Product
ORDER BY ProfitMarginPct DESC;""",
        "sql_sqlite": """SELECT 
    p.Product,
    SUM(s.Amount) AS TotalRevenue,
    ROUND(SUM(s.Boxes * p.Cost_per_box), 2) AS TotalCost,
    ROUND(SUM(s.Amount) - SUM(s.Boxes * p.Cost_per_box), 2) AS TotalProfit,
    ROUND(((SUM(s.Amount) - SUM(s.Boxes * p.Cost_per_box)) / SUM(s.Amount)) * 100, 2) AS ProfitMarginPct
FROM products p
JOIN sales s ON p.PID = s.PID
GROUP BY p.PID, p.Product
ORDER BY ProfitMarginPct DESC;"""
    },
    {
        "id": "choco_team_revenue_boxes",
        "domain": "awesome_chocolates",
        "category": "team_comparison",
        "tags": ["team", "đội ngũ", "nhóm", "giữa các nhóm", "so sánh", "doanh số", "số lượng hộp", "avg price", "hộp bán ra", "team kinh doanh"],
        "question": "So sánh tổng doanh số và số lượng hộp bán ra giữa các Team kinh doanh",
        "question_en": "Compare total sales revenue and boxes sold across business teams",
        "intent_explanation": "Nhóm theo Team của bảng people, tính SUM(Amount), SUM(Boxes) và đơn giá bình quân SUM(Amount)/SUM(Boxes).",
        "sql_mysql": """SELECT 
    p.Team AS `Đội Ngũ`,
    SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
    SUM(s.Boxes) AS `Tổng Số Hộp Bán Ra`,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS `Avg Price Per Box`
FROM people p
JOIN sales s ON p.SPID = s.SPID
WHERE p.Team IS NOT NULL AND p.Team != ''
GROUP BY p.Team
ORDER BY `Tổng Doanh Thu ($)` DESC;""",
        "sql_sqlite": """SELECT 
    p.Team AS "Đội Ngũ",
    SUM(s.Amount) AS "Tổng Doanh Thu ($)",
    SUM(s.Boxes) AS "Tổng Số Hộp Bán Ra",
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS "Avg Price Per Box"
FROM people p
JOIN sales s ON p.SPID = s.SPID
WHERE p.Team IS NOT NULL AND p.Team != ''
GROUP BY p.Team
ORDER BY "Tổng Doanh Thu ($)" DESC;"""
    },
    {
        "id": "choco_team_disparity_spread",
        "domain": "awesome_chocolates",
        "category": "team_comparison",
        "tags": ["nhóm cao nhất", "nhóm thấp nhất", "chênh lệch", "sự chênh lệch", "giữa nhóm", "giữa các nhóm", "team", "đội ngũ", "nhóm bán hàng", "so sánh nhóm"],
        "question": "Phân tích sự chênh lệch số tiền giữa nhóm cao nhất và nhóm thấp nhất",
        "question_en": "Analyze the sales amount disparity between the highest and lowest business teams",
        "intent_explanation": "Nhóm theo Team của bảng people (loại bỏ Team rỗng), tính tổng doanh số SUM(Amount), tổng số hộp SUM(Boxes), số đơn hàng COUNT(PID) và giá trị đơn hàng trung bình AVG(Amount), sắp xếp theo TotalSales DESC để đối chiếu khoảng cách chênh lệch giữa nhóm dẫn đầu và nhóm thấp nhất.",
        "sql_mysql": """SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    COUNT(s.PID) AS TotalOrders,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL
GROUP BY pe.Team
ORDER BY TotalSales DESC;""",
        "sql_sqlite": """SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    COUNT(s.PID) AS TotalOrders,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL
GROUP BY pe.Team
ORDER BY TotalSales DESC;"""
    },
    {
        "id": "choco_team_headcount",
        "domain": "awesome_chocolates",
        "category": "headcount",
        "tags": ["nhân viên", "nhân sự", "phân bổ", "team", "số lượng nhân viên", "đội ngũ", "headcount"],
        "question": "Số lượng nhân viên bán hàng phân bổ theo từng Team kinh doanh",
        "question_en": "Salesperson headcount distribution across business teams",
        "intent_explanation": "Đếm COUNT(DISTINCT SPID) nhóm theo Team.",
        "sql_mysql": """SELECT 
    Team,
    COUNT(DISTINCT SPID) AS SalespersonCount
FROM people
WHERE Team IS NOT NULL AND Team != ''
GROUP BY Team
ORDER BY SalespersonCount DESC;""",
        "sql_sqlite": """SELECT 
    Team,
    COUNT(DISTINCT SPID) AS SalespersonCount
FROM people
WHERE Team IS NOT NULL AND Team != ''
GROUP BY Team
ORDER BY SalespersonCount DESC;"""
    },
    {
        "id": "choco_top_rep_per_team",
        "domain": "awesome_chocolates",
        "category": "window_function",
        "tags": ["nhân viên xuất sắc nhất", "top 1 mỗi team", "dẫn đầu từng đội", "salesperson", "team"],
        "question": "Tìm nhân viên bán hàng có doanh số cao nhất của từng Team kinh doanh",
        "question_en": "Find the top revenue-generating salesperson for each business team",
        "intent_explanation": "Dùng ROW_NUMBER() OVER (PARTITION BY Team ORDER BY SUM(Amount) DESC) để chọn đúng người đứng đầu mỗi đội.",
        "sql_mysql": """WITH RepSales AS (
    SELECT 
        p.Team,
        p.Salesperson,
        SUM(s.Amount) AS TotalSales,
        ROW_NUMBER() OVER (
            PARTITION BY p.Team 
            ORDER BY SUM(s.Amount) DESC
        ) AS TeamRank
    FROM people p
    JOIN sales s ON p.SPID = s.SPID
    WHERE p.Team IS NOT NULL AND p.Team != ''
    GROUP BY p.Team, p.Salesperson
)
SELECT Team, Salesperson, TotalSales
FROM RepSales
WHERE TeamRank = 1
ORDER BY TotalSales DESC;""",
        "sql_sqlite": """WITH RepSales AS (
    SELECT 
        p.Team,
        p.Salesperson,
        SUM(s.Amount) AS TotalSales,
        ROW_NUMBER() OVER (
            PARTITION BY p.Team 
            ORDER BY SUM(s.Amount) DESC
        ) AS TeamRank
    FROM people p
    JOIN sales s ON p.SPID = s.SPID
    WHERE p.Team IS NOT NULL AND p.Team != ''
    GROUP BY p.Team, p.Salesperson
)
SELECT Team, Salesperson, TotalSales
FROM RepSales
WHERE TeamRank = 1
ORDER BY TotalSales DESC;"""
    },
    {
        "id": "choco_relative_time_12m",
        "domain": "awesome_chocolates",
        "category": "time_series",
        "tags": ["12 tháng gần nhất", "năm gần nhất", "gần đây", "thời gian tương đối", "thời gian lịch sử", "qua các tháng"],
        "question": "Doanh thu theo từng tháng trong 12 tháng gần nhất của dữ liệu",
        "question_en": "Monthly revenue for the last 12 months anchored to latest data date",
        "intent_explanation": "Neo theo mốc (SELECT MAX(SaleDate) FROM sales) và lùi 1 năm, TUYỆT ĐỐI không dùng CURRENT_DATE().",
        "sql_mysql": """SELECT 
    DATE_FORMAT(s.SaleDate, '%Y-%m') AS SalesMonth,
    SUM(s.Amount) AS MonthlyRevenue,
    SUM(s.Boxes) AS TotalBoxes
FROM sales s
WHERE s.SaleDate >= DATE_SUB((SELECT MAX(SaleDate) FROM sales), INTERVAL 1 YEAR)
GROUP BY DATE_FORMAT(s.SaleDate, '%Y-%m')
ORDER BY SalesMonth ASC;""",
        "sql_sqlite": """SELECT 
    strftime('%Y-%m', s.SaleDate) AS SalesMonth,
    SUM(s.Amount) AS MonthlyRevenue,
    SUM(s.Boxes) AS TotalBoxes
FROM sales s
WHERE s.SaleDate >= date((SELECT MAX(SaleDate) FROM sales), '-1 year')
GROUP BY strftime('%Y-%m', s.SaleDate)
ORDER BY SalesMonth ASC;"""
    },
    {
        "id": "choco_large_orders_count_and_revenue",
        "domain": "awesome_chocolates",
        "category": "order_threshold_aggregation",
        "tags": ["đơn hàng lớn", "trên 1000 hộp", "trên 1,000 hộp", "từ 1000 hộp trở lên", "từ 1,000 hộp trở lên", "từ 1,000 hộp", "từ 1000 hộp", "hộp trở lên", "nhóm đơn hàng lớn", "đạt sản lượng từ", "số lượng đơn hàng", "tổng doanh thu đơn hàng lớn", "large orders", "order threshold", "boxes > 1000"],
        "question": "Có bao nhiêu đơn hàng bán được trên 1,000 hộp, và tổng doanh thu từ các đơn hàng lớn này là bao nhiêu?",
        "question_en": "How many orders had over 1,000 boxes sold, and what is the total revenue from these large orders?",
        "intent_explanation": "Truy vấn tổng hợp toàn cục (scalar aggregation) cho các đơn hàng thỏa mãn điều kiện ngưỡng s.Boxes > 1000. KHÔNG dùng GROUP BY, KHÔNG LIMIT vì câu hỏi hỏi toàn bộ tập đơn hàng lớn.",
        "sql_mysql": """SELECT 
    COUNT(*) AS LargeOrdersCount,
    SUM(s.Amount) AS TotalLargeOrdersRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(AVG(s.Amount), 2) AS AvgLargeOrderAmount
FROM sales s
WHERE s.Boxes > 1000;""",
        "sql_sqlite": """SELECT 
    COUNT(*) AS LargeOrdersCount,
    SUM(s.Amount) AS TotalLargeOrdersRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(AVG(s.Amount), 2) AS AvgLargeOrderAmount
FROM sales s
WHERE s.Boxes > 1000;"""
    },
    {
        "id": "choco_country_avg_price_per_box",
        "domain": "awesome_chocolates",
        "category": "avg_price_per_box",
        "tags": ["giá bán trung bình", "mỗi hộp sô-cô-la", "thị trường úc", "australia", "giá trung bình mỗi hộp", "đơn giá", "price per box", "avg price per box", "mỗi hộp mang về bao nhiêu"],
        "question": "Mỗi hộp sô-cô-la bán ra tại thị trường Úc (Australia) mang về giá bán trung bình là bao nhiêu tiền?",
        "question_en": "How much average selling price does each box of chocolate sold in Australia bring in?",
        "intent_explanation": "Tính đơn giá bán trung bình trên mỗi hộp AvgPricePerBox = ROUND(SUM(Amount) / NULLIF(SUM(Boxes), 0), 2) tại thị trường Úc (Australia), kèm TotalRevenue và TotalBoxesSold.",
        "sql_mysql": """SELECT 
    g.Geo AS Country,
    ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
WHERE g.Geo = 'Australia'
GROUP BY g.Geo;""",
        "sql_sqlite": """SELECT 
    g.Geo AS Country,
    ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
WHERE g.Geo = 'Australia'
GROUP BY g.Geo;"""
    },
    {
        "id": "choco_category_sales_boxes_avg_price",
        "domain": "awesome_chocolates",
        "category": "category_comparison",
        "tags": ["so sánh", "danh mục", "category", "tổng doanh thu", "số hộp bán ra", "đơn giá trung bình", "mỗi hộp", "danh mục sản phẩm", "giữa các danh mục sản phẩm"],
        "question": "So sánh tổng doanh thu, số hộp bán ra và đơn giá trung bình mỗi hộp giữa các danh mục sản phẩm (Category).",
        "question_en": "Compare total revenue, boxes sold, and average price per box across product categories.",
        "intent_explanation": "Nhóm theo pr.Category và tính đầy đủ 3 chỉ số: SUM(Amount) AS TotalRevenue, SUM(Boxes) AS TotalBoxesSold, và đơn giá trung bình AvgPricePerBox = ROUND(SUM(Amount) / NULLIF(SUM(Boxes), 0), 2).",
        "sql_mysql": """SELECT 
    pr.Category AS Category,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox
FROM sales s
JOIN products pr ON s.PID = pr.PID
GROUP BY pr.Category
ORDER BY TotalRevenue DESC;""",
        "sql_sqlite": """SELECT 
    pr.Category AS Category,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox
FROM sales s
JOIN products pr ON s.PID = pr.PID
GROUP BY pr.Category
ORDER BY TotalRevenue DESC;"""
    },
    {
        "id": "choco_team_geo_category_segment",
        "domain": "awesome_chocolates",
        "category": "multi_dim_segment",
        "tags": ["riêng team delish", "thị trường canada", "nhóm bars", "team và thị trường", "phân khúc đa chiều", "delish canada bars", "thống kê doanh số bán hàng của riêng team delish"],
        "question": "Thống kê doanh số bán hàng của riêng Team Delish tại thị trường Canada đối với các sản phẩm thuộc nhóm Bars.",
        "question_en": "Sales revenue statistics of only Team Delish in Canada for products in Bars category.",
        "intent_explanation": "Lọc đồng thời 3 điều kiện: pe.Team = 'Delish' AND g.Geo = 'Canada' AND pr.Category = 'Bars'. Nhóm theo từng sản phẩm để phân tích doanh số, sản lượng và đơn giá bình quân.",
        "sql_mysql": """SELECT 
    pr.Product AS Product,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
JOIN geo g ON s.GeoID = g.GeoID
JOIN products pr ON s.PID = pr.PID
WHERE pe.Team = 'Delish'
  AND g.Geo = 'Canada'
  AND pr.Category = 'Bars'
GROUP BY pr.PID, pr.Product
ORDER BY TotalSales DESC;""",
        "sql_sqlite": """SELECT 
    pr.Product AS Product,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
JOIN geo g ON s.GeoID = g.GeoID
JOIN products pr ON s.PID = pr.PID
WHERE pe.Team = 'Delish'
  AND g.Geo = 'Canada'
  AND pr.Category = 'Bars'
GROUP BY pr.PID, pr.Product
ORDER BY TotalSales DESC;"""
    },
    {
        "id": "choco_segment_large_orders_bites_usa_canada",
        "domain": "awesome_chocolates",
        "category": "multi_dim_segment",
        "tags": [
            "tổng doanh thu", "số lượng đơn hàng", "500 hộp", "500 hộp trở lên", "quy mô từ 500 hộp", 
            "danh mục bites", "bites", "hai thị trường usa và canada", "usa và canada", 
            "thống kê tổng doanh thu và số lượng đơn hàng", "large orders segment"
        ],
        "question": "Thống kê tổng doanh thu và số lượng đơn hàng có quy mô từ 500 hộp trở lên đối với các sản phẩm thuộc danh mục 'Bites' tại hai thị trường USA và Canada.",
        "question_en": "Statistics of total revenue and number of large orders (500+ boxes) for products in 'Bites' category across USA and Canada markets.",
        "intent_explanation": "Lọc các giao dịch đơn hàng lớn s.Boxes >= 500 của các sản phẩm thuộc danh mục pr.Category = 'Bites' tại hai thị trường g.Geo IN ('USA', 'Canada'). Nhóm theo g.Geo và pr.Product, tính COUNT(*) AS LargeOrdersCount, SUM(s.Amount) AS TotalRevenue, SUM(s.Boxes) AS TotalBoxesSold.",
        "sql_mysql": """SELECT 
    g.Geo AS Market,
    pr.Product AS Product,
    COUNT(*) AS LargeOrdersCount,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN products pr ON s.PID = pr.PID
JOIN geo g ON s.GeoID = g.GeoID
WHERE pr.Category = 'Bites'
  AND g.Geo IN ('USA', 'Canada')
  AND s.Boxes >= 500
GROUP BY g.Geo, pr.Product
ORDER BY g.Geo, TotalRevenue DESC;""",
        "sql_sqlite": """SELECT 
    g.Geo AS Market,
    pr.Product AS Product,
    COUNT(*) AS LargeOrdersCount,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN products pr ON s.PID = pr.PID
JOIN geo g ON s.GeoID = g.GeoID
WHERE pr.Category = 'Bites'
  AND g.Geo IN ('USA', 'Canada')
  AND s.Boxes >= 500
GROUP BY g.Geo, pr.Product
ORDER BY g.Geo, TotalRevenue DESC;"""
    },
    {
        "id": "choco_threshold_reps_above_500k",
        "domain": "awesome_chocolates",
        "category": "threshold",
        "tags": ["trên 500k", "doanh số vượt mức", "ngưỡng", "having", "salesperson", "hơn 500000"],
        "question": "Những nhân viên bán hàng có tổng doanh thu vượt trên $500,000 kèm tổng số hộp",
        "question_en": "Salespersons with total sales exceeding $500,000 along with total boxes sold",
        "intent_explanation": "Mệnh đề SELECT bắt buộc gồm cả tên nhân viên và SUM(Amount), SUM(Boxes), lọc bằng HAVING SUM(Amount) > 500000.",
        "sql_mysql": """SELECT 
    p.Salesperson,
    p.Team,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM people p
JOIN sales s ON p.SPID = s.SPID
GROUP BY p.SPID, p.Salesperson, p.Team
HAVING SUM(s.Amount) > 500000
ORDER BY TotalRevenue DESC;""",
        "sql_sqlite": """SELECT 
    p.Salesperson,
    p.Team,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM people p
JOIN sales s ON p.SPID = s.SPID
GROUP BY p.SPID, p.Salesperson, p.Team
HAVING SUM(s.Amount) > 500000
ORDER BY TotalRevenue DESC;"""
    },
    {
        "id": "choco_geo_threshold_with_transactions",
        "domain": "awesome_chocolates",
        "category": "threshold",
        "tags": [
            "thị trường quốc gia", "quốc gia", "doanh thu trên 7 triệu", "7 triệu usd",
            "số lượng giao dịch", "số đơn hàng", "ngưỡng", "having", "geo", "country", "trên 7 triệu"
        ],
        "question": "Những thị trường quốc gia nào đạt tổng doanh thu trên 7 triệu USD, hiển thị rõ tổng doanh thu và số lượng giao dịch tương ứng?",
        "question_en": "Which country markets achieved total revenue over 7 million USD, clearly display total revenue and corresponding number of transactions?",
        "intent_explanation": "Nhóm theo thị trường quốc gia (g.Geo), tính tổng doanh thu SUM(s.Amount) và số lượng giao dịch COUNT(*), lọc các thị trường đạt tổng doanh thu trên 7,000,000 USD bằng mệnh đề HAVING.",
        "sql_mysql": """SELECT 
    g.Geo AS `Quốc Gia`,
    SUM(s.Amount) AS `Tổng Doanh Số ($)`,
    COUNT(*) AS `Số Lượng Giao Dịch`
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
GROUP BY g.Geo
HAVING SUM(s.Amount) > 7000000
ORDER BY `Tổng Doanh Số ($)` DESC;""",
        "sql_sqlite": """SELECT 
    g.Geo AS "Quốc Gia",
    SUM(s.Amount) AS "Tổng Doanh Số ($)",
    COUNT(*) AS "Số Lượng Giao Dịch"
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
GROUP BY g.Geo
HAVING SUM(s.Amount) > 7000000
ORDER BY "Tổng Doanh Số ($)" DESC;"""
    },
    {
        "id": "choco_geo_product_matrix",
        "domain": "awesome_chocolates",
        "category": "geo_analysis",
        "tags": ["quốc gia", "thị trường", "sản phẩm bán chạy nhất theo nước", "geo", "country"],
        "question": "Sản phẩm bán chạy nhất tại mỗi quốc gia theo doanh thu",
        "question_en": "Best-selling product by revenue in each country/market",
        "intent_explanation": "Dùng ROW_NUMBER() OVER (PARTITION BY Geo ORDER BY SUM(Amount) DESC).",
        "sql_mysql": """WITH GeoProductSales AS (
    SELECT 
        g.Geo AS Country,
        pr.Product,
        SUM(s.Amount) AS TotalRevenue,
        ROW_NUMBER() OVER (
            PARTITION BY g.Geo 
            ORDER BY SUM(s.Amount) DESC
        ) AS CountryRank
    FROM geo g
    JOIN sales s ON g.GeoID = s.GeoID
    JOIN products pr ON s.PID = pr.PID
    GROUP BY g.Geo, pr.Product
)
SELECT Country, Product, TotalRevenue
FROM GeoProductSales
WHERE CountryRank = 1
ORDER BY TotalRevenue DESC;""",
        "sql_sqlite": """WITH GeoProductSales AS (
    SELECT 
        g.Geo AS Country,
        pr.Product,
        SUM(s.Amount) AS TotalRevenue,
        ROW_NUMBER() OVER (
            PARTITION BY g.Geo 
            ORDER BY SUM(s.Amount) DESC
        ) AS CountryRank
    FROM geo g
    JOIN sales s ON g.GeoID = s.GeoID
    JOIN products pr ON s.PID = pr.PID
    GROUP BY g.Geo, pr.Product
)
SELECT Country, Product, TotalRevenue
FROM GeoProductSales
WHERE CountryRank = 1
ORDER BY TotalRevenue DESC;"""
    },
    {
        "id": "choco_dominant_market_top_product",
        "domain": "awesome_chocolates",
        "category": "market_product_analysis",
        "tags": [
            "thị trường", "quốc gia", "chiếm trên 30%", "30%", "doanh số toàn cầu", 
            "sản phẩm bán chạy nhất", "sản phẩm bán chạy", "top product", "geo", "market share"
        ],
        "question": "Thị trường nào đang chiếm trên 30% tổng doanh số toàn cầu của công ty và sản phẩm bán chạy nhất tại thị trường đó là gì?",
        "question_en": "Which market accounts for over 30% of global total sales and what is the best-selling product in that market?",
        "intent_explanation": "Sử dụng 2 CTE: CTE 1 (MarketSales) tính doanh thu và tỷ trọng toàn cầu SUM(Amount)*100/(SELECT SUM(Amount) FROM sales) của từng thị trường, lọc HAVING tỷ trọng > 30%. CTE 2 (RankedMarketProducts) xếp hạng ROW_NUMBER() các sản phẩm theo doanh số trong từng thị trường. Cuối cùng lọc WHERE rn = 1 để lấy đúng sản phẩm dẫn đầu.",
        "sql_mysql": """WITH MarketSales AS (
    SELECT 
        g.GeoID,
        g.Geo AS Market,
        SUM(s.Amount) AS MarketRevenue,
        ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales), 2) AS MarketSharePct
    FROM sales s
    JOIN geo g ON s.GeoID = g.GeoID
    GROUP BY g.GeoID, g.Geo
    HAVING (SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales)) > 30
),
RankedMarketProducts AS (
    SELECT 
        ms.Market,
        ms.MarketRevenue,
        ms.MarketSharePct,
        pr.Product AS TopProduct,
        pr.Category AS ProductCategory,
        SUM(s.Amount) AS TopProductRevenue,
        ROW_NUMBER() OVER (PARTITION BY ms.GeoID ORDER BY SUM(s.Amount) DESC) AS rn
    FROM MarketSales ms
    JOIN sales s ON ms.GeoID = s.GeoID
    JOIN products pr ON s.PID = pr.PID
    GROUP BY ms.GeoID, ms.Market, ms.MarketRevenue, ms.MarketSharePct, pr.PID, pr.Product, pr.Category
)
SELECT 
    Market,
    MarketRevenue,
    MarketSharePct,
    TopProduct,
    ProductCategory,
    TopProductRevenue
FROM RankedMarketProducts
WHERE rn = 1
ORDER BY MarketRevenue DESC;""",
        "sql_sqlite": """WITH MarketSales AS (
    SELECT 
        g.GeoID,
        g.Geo AS Market,
        SUM(s.Amount) AS MarketRevenue,
        ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales), 2) AS MarketSharePct
    FROM sales s
    JOIN geo g ON s.GeoID = g.GeoID
    GROUP BY g.GeoID, g.Geo
    HAVING (SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales)) > 30
),
RankedMarketProducts AS (
    SELECT 
        ms.Market,
        ms.MarketRevenue,
        ms.MarketSharePct,
        pr.Product AS TopProduct,
        pr.Category AS ProductCategory,
        SUM(s.Amount) AS TopProductRevenue,
        ROW_NUMBER() OVER (PARTITION BY ms.GeoID ORDER BY SUM(s.Amount) DESC) AS rn
    FROM MarketSales ms
    JOIN sales s ON ms.GeoID = s.GeoID
    JOIN products pr ON s.PID = pr.PID
    GROUP BY ms.GeoID, ms.Market, ms.MarketRevenue, ms.MarketSharePct, pr.PID, pr.Product, pr.Category
)
SELECT 
    Market,
    MarketRevenue,
    MarketSharePct,
    TopProduct,
    ProductCategory,
    TopProductRevenue
FROM RankedMarketProducts
WHERE rn = 1
ORDER BY MarketRevenue DESC;"""
    },
    {
        "id": "choco_product_price_spread_by_geo",
        "domain": "awesome_chocolates",
        "category": "price_spread",
        "tags": [
            "biên độ", "dao động", "biên độ dao động", "giá bán trung bình", "trên mỗi hộp",
            "thị trường quốc gia", "giữa các quốc gia", "quốc gia", "geo", "chênh lệch giá",
            "price spread", "fluctuation", "country", "market"
        ],
        "question": "Sản phẩm nào có biên độ dao động giá bán trung bình trên mỗi hộp lớn nhất giữa các thị trường quốc gia?",
        "question_en": "Which product has the largest price fluctuation/spread in average selling price per box across country markets?",
        "intent_explanation": "Dùng CTE tính đơn giá bán trung bình SUM(Amount)/SUM(Boxes) theo từng sản phẩm và quốc gia (JOIN sales, products, geo). Sau đó tính MAX(AvgPrice) - MIN(AvgPrice) theo sản phẩm, sắp xếp giảm dần.",
        "sql_mysql": """WITH ProductCountryPrice AS (
    SELECT 
        pr.Product,
        g.Geo AS Country,
        ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
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
LIMIT 1;""",
        "sql_sqlite": """WITH ProductCountryPrice AS (
    SELECT 
        pr.Product,
        g.Geo AS Country,
        ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
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
LIMIT 1;"""
    },
    {
        "id": "choco_mom_growth_rate",
        "domain": "awesome_chocolates",
        "category": "growth_rate",
        "tags": ["tăng trưởng", "tháng trước", "mom", "tốc độ tăng trưởng", "doanh thu theo tháng", "lag"],
        "question": "Tốc độ tăng trưởng doanh thu theo từng tháng (MoM Growth Rate)",
        "question_en": "Month-over-month (MoM) revenue growth rate using LAG window function",
        "intent_explanation": "Dùng hàm LAG(Revenue) OVER (ORDER BY Month) trong CTE để tính chênh lệch phần trăm.",
        "sql_mysql": """WITH MonthlySales AS (
    SELECT 
        DATE_FORMAT(SaleDate, '%Y-%m') AS SalesMonth,
        SUM(Amount) AS Revenue
    FROM sales
    GROUP BY DATE_FORMAT(SaleDate, '%Y-%m')
)
SELECT 
    SalesMonth,
    Revenue,
    LAG(Revenue) OVER (ORDER BY SalesMonth) AS PrevMonthRevenue,
    ROUND(((Revenue - LAG(Revenue) OVER (ORDER BY SalesMonth)) / LAG(Revenue) OVER (ORDER BY SalesMonth)) * 100, 2) AS MoMGrowthPct
FROM MonthlySales
ORDER BY SalesMonth ASC;""",
        "sql_sqlite": """WITH MonthlySales AS (
    SELECT 
        strftime('%Y-%m', SaleDate) AS SalesMonth,
        SUM(Amount) AS Revenue
    FROM sales
    GROUP BY strftime('%Y-%m', SaleDate)
)
SELECT 
    SalesMonth,
    Revenue,
    LAG(Revenue) OVER (ORDER BY SalesMonth) AS PrevMonthRevenue,
    ROUND(((Revenue - LAG(Revenue) OVER (ORDER BY SalesMonth)) / LAG(Revenue) OVER (ORDER BY SalesMonth)) * 100, 2) AS MoMGrowthPct
FROM MonthlySales
ORDER BY SalesMonth ASC;"""
    },
    {
        "id": "choco_category_share_ratio",
        "domain": "awesome_chocolates",
        "category": "ratio_share",
        "tags": ["tỷ lệ", "tỷ trọng", "cơ cấu", "danh mục", "category", "share", "phần trăm"],
        "question": "Tỷ trọng đóng góp doanh thu của từng danh mục sản phẩm (Category Share %)",
        "question_en": "Revenue contribution percentage by product category (Category Share %)",
        "intent_explanation": "Tính doanh thu từng Category và chia cho tổng doanh thu toàn hệ thống.",
        "sql_mysql": """SELECT 
    p.Category,
    SUM(s.Amount) AS CategoryRevenue,
    ROUND((SUM(s.Amount) / (SELECT SUM(Amount) FROM sales)) * 100, 2) AS RevenueSharePct
FROM products p
JOIN sales s ON p.PID = s.PID
GROUP BY p.Category
ORDER BY CategoryRevenue DESC;""",
        "sql_sqlite": """SELECT 
    p.Category,
    SUM(s.Amount) AS CategoryRevenue,
    ROUND((SUM(s.Amount) / (SELECT SUM(Amount) FROM sales)) * 100, 2) AS RevenueSharePct
FROM products p
JOIN sales s ON p.PID = s.PID
GROUP BY p.Category
ORDER BY CategoryRevenue DESC;"""
    },
    {
        "id": "choco_salesperson_highest_aov_by_team",
        "domain": "awesome_chocolates",
        "category": "salesperson_aov",
        "tags": [
            "ai là", "nhân sự bán hàng", "sales person", "salesperson",
            "giá trị đơn hàng trung bình", "trung bình trên mỗi giao dịch", "đơn hàng trung bình", "aov",
            "delish", "yummies", "jucies", "đội ngũ", "team", "cao nhất"
        ],
        "question": "Ai là nhân sự bán hàng (Sales Person) có giá trị đơn hàng trung bình trên mỗi giao dịch cao nhất trong đội ngũ Delish?",
        "question_en": "Who is the salesperson with the highest average order value per transaction in the Delish team?",
        "intent_explanation": "Tính AVG(s.Amount) của từng nhân sự (pe.Salesperson) trong đội ngũ cụ thể (pe.Team = 'Delish'), sắp xếp giảm dần và LIMIT 1.",
        "sql_mysql": """SELECT 
    pe.Salesperson AS Salesperson,
    pe.Team AS Team,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue,
    COUNT(s.PID) AS TotalOrders,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team = 'Delish'
GROUP BY pe.SPID, pe.Salesperson, pe.Team
ORDER BY AvgOrderValue DESC
LIMIT 1;""",
        "sql_sqlite": """SELECT 
    pe.Salesperson AS Salesperson,
    pe.Team AS Team,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue,
    COUNT(s.PID) AS TotalOrders,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team = 'Delish'
GROUP BY pe.SPID, pe.Salesperson, pe.Team
ORDER BY AvgOrderValue DESC
LIMIT 1;"""
    },
    {
        "id": "choco_top_transactions_in_geo",
        "domain": "awesome_chocolates",
        "category": "top_transactions",
        "tags": [
            "giao dịch", "đơn hàng", "giá trị đơn hàng", "cao nhất", "thị trường india",
            "ngày bán", "tên nhân viên", "tên sản phẩm", "số tiền", "top 5 giao dịch",
            "không group by", "chi tiết giao dịch", "transactions", "orders", "india"
        ],
        "question": "Cho biết thông tin top 5 giao dịch có giá trị đơn hàng cao nhất tại thị trường India: hiển thị ngày bán, tên nhân viên, tên sản phẩm và số tiền.",
        "question_en": "Provide information for top 5 transactions with highest order value in India market: display sale date, salesperson name, product name, and amount.",
        "intent_explanation": "Truy vấn chi tiết từng giao dịch đơn lẻ (không dùng GROUP BY). Liên kết sales với people, products, geo; lọc g.Geo = 'India', sắp xếp theo s.Amount giảm dần và lấy LIMIT 5.",
        "sql_mysql": """SELECT 
    s.SaleDate,
    pe.Salesperson,
    pr.Product,
    s.Amount
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
JOIN products pr ON s.PID = pr.PID
JOIN geo g ON s.GeoID = g.GeoID
WHERE g.Geo = 'India'
ORDER BY s.Amount DESC
LIMIT 5;""",
        "sql_sqlite": """SELECT 
    s.SaleDate,
    pe.Salesperson,
    pr.Product,
    s.Amount
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
JOIN products pr ON s.PID = pr.PID
JOIN geo g ON s.GeoID = g.GeoID
WHERE g.Geo = 'India'
ORDER BY s.Amount DESC
LIMIT 5;"""
    },
    {
        "id": "choco_team_salespeople_revenue_and_boxes",
        "domain": "awesome_chocolates",
        "category": "team_salespeople",
        "tags": [
            "team delish", "delish", "yummies", "jucies", "từng nhân viên", "từng người",
            "nhân viên", "nhân sự", "salesperson", "doanh số", "số hộp", "hộp bán ra",
            "doanh số cao nhất", "sắp xếp"
        ],
        "question": "Trong Team Delish, liệt kê doanh số và số hộp bán ra của từng nhân viên, sắp xếp người có doanh số cao nhất lên đầu.",
        "question_en": "In Team Delish, list revenue and boxes sold of each salesperson, order by highest revenue first.",
        "intent_explanation": "Lọc nhân sự thuộc đội ngũ Delish (pe.Team = 'Delish'), nhóm theo từng nhân viên (pe.SPID, pe.Salesperson), tính cả SUM(s.Amount) AS TotalSales và SUM(s.Boxes) AS TotalBoxesSold, sắp xếp theo TotalSales giảm dần.",
        "sql_mysql": """SELECT 
    pe.Salesperson,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team = 'Delish'
GROUP BY pe.SPID, pe.Salesperson
ORDER BY TotalSales DESC;""",
        "sql_sqlite": """SELECT 
    pe.Salesperson,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team = 'Delish'
GROUP BY pe.SPID, pe.Salesperson
ORDER BY TotalSales DESC;"""
    },
    {
        "id": "choco_team_lowest_boxes_and_flagship_product",
        "domain": "awesome_chocolates",
        "category": "team_flagship_product",
        "tags": [
            "team kinh doanh", "đội ngũ", "nhóm", "thấp nhất", "tổng số lượng hộp bán ra",
            "hộp bán ra", "sản phẩm chủ lực", "mặt hàng chủ lực", "chủ lực của họ là gì",
            "boxes", "flagship product", "hero product"
        ],
        "question": "Team kinh doanh nào có tổng số lượng hộp bán ra thấp nhất và sản phẩm chủ lực của họ là gì?",
        "question_en": "Which sales team has the lowest total boxes sold and what is their flagship product?",
        "intent_explanation": "Dùng 2 CTE: CTE 1 tìm Team có tổng số hộp bán ra thấp nhất (ORDER BY SUM(Boxes) ASC LIMIT 1), CTE 2 xếp hạng sản phẩm của Team đó bằng DENSE_RANK() để lấy sản phẩm bán chạy nhất (ProductRank = 1).",
        "sql_mysql": """WITH TeamSummary AS (
    SELECT 
        pe.Team,
        SUM(s.Boxes) AS TotalBoxesSold,
        SUM(s.Amount) AS TotalSales
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    WHERE pe.Team != '' AND pe.Team IS NOT NULL
    GROUP BY pe.Team
    ORDER BY TotalBoxesSold ASC
    LIMIT 1
),
TeamProductSales AS (
    SELECT 
        pe.Team,
        pr.Product,
        SUM(s.Boxes) AS ProductBoxesSold,
        SUM(s.Amount) AS ProductSales,
        DENSE_RANK() OVER (PARTITION BY pe.Team ORDER BY SUM(s.Boxes) DESC) AS ProductRank
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
JOIN TeamProductSales tps ON ts.Team = tps.Team AND tps.ProductRank = 1;""",
        "sql_sqlite": """WITH TeamSummary AS (
    SELECT 
        pe.Team,
        SUM(s.Boxes) AS TotalBoxesSold,
        SUM(s.Amount) AS TotalSales
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    WHERE pe.Team != '' AND pe.Team IS NOT NULL
    GROUP BY pe.Team
    ORDER BY TotalBoxesSold ASC
    LIMIT 1
),
TeamProductSales AS (
    SELECT 
        pe.Team,
        pr.Product,
        SUM(s.Boxes) AS ProductBoxesSold,
        SUM(s.Amount) AS ProductSales,
        DENSE_RANK() OVER (PARTITION BY pe.Team ORDER BY SUM(s.Boxes) DESC) AS ProductRank
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
JOIN TeamProductSales tps ON ts.Team = tps.Team AND tps.ProductRank = 1;"""
    },
    {
        "id": "choco_salesperson_quarterly_growth",
        "domain": "awesome_chocolates",
        "category": "quarterly_growth",
        "tags": [
            "nhân sự", "nhân viên", "doanh số", "quý 4/2021", "quý 3/2021",
            "tăng trưởng", "trên 20%", "tăng trưởng trên 20%", "so với quý 3",
            "quarterly growth", "salesperson", "growth rate"
        ],
        "question": "Tìm những nhân sự có doanh số bán hàng quý 4/2021 tăng trưởng trên 20% so với quý 3/2021.",
        "question_en": "Find salespeople whose Q4/2021 sales grew by more than 20% compared to Q3/2021.",
        "intent_explanation": "Dùng CTE tính doanh số Q3/2021 và Q4/2021 theo từng nhân sự bằng SUM(CASE WHEN...), sau đó tính GrowthPct = ((Q4 - Q3)/Q3)*100 và lọc GrowthPct > 20.",
        "sql_mysql": """WITH SalespersonQuarterlySales AS (
    SELECT 
        pe.Salesperson AS Salesperson,
        pe.Team AS Team,
        ROUND(SUM(CASE WHEN YEAR(s.SaleDate) = 2021 AND QUARTER(s.SaleDate) = 3 THEN s.Amount ELSE 0 END), 2) AS Q3_Sales,
        ROUND(SUM(CASE WHEN YEAR(s.SaleDate) = 2021 AND QUARTER(s.SaleDate) = 4 THEN s.Amount ELSE 0 END), 2) AS Q4_Sales
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    WHERE YEAR(s.SaleDate) = 2021
    GROUP BY pe.SPID, pe.Salesperson, pe.Team
)
SELECT 
    Salesperson,
    Team,
    Q3_Sales,
    Q4_Sales,
    ROUND(Q4_Sales - Q3_Sales, 2) AS AbsoluteGrowth,
    ROUND(((Q4_Sales - Q3_Sales) / NULLIF(Q3_Sales, 0)) * 100.0, 2) AS GrowthPct
FROM SalespersonQuarterlySales
WHERE Q3_Sales > 0 
  AND ((Q4_Sales - Q3_Sales) / Q3_Sales) * 100.0 > 20
ORDER BY GrowthPct DESC;""",
        "sql_sqlite": """WITH SalespersonQuarterlySales AS (
    SELECT 
        pe.Salesperson AS Salesperson,
        pe.Team AS Team,
        ROUND(SUM(CASE WHEN strftime('%Y', s.SaleDate) = '2021' AND ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = 3 THEN s.Amount ELSE 0 END), 2) AS Q3_Sales,
        ROUND(SUM(CASE WHEN strftime('%Y', s.SaleDate) = '2021' AND ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = 4 THEN s.Amount ELSE 0 END), 2) AS Q4_Sales
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    WHERE strftime('%Y', s.SaleDate) = '2021'
    GROUP BY pe.SPID, pe.Salesperson, pe.Team
)
SELECT 
    Salesperson,
    Team,
    Q3_Sales,
    Q4_Sales,
    ROUND(Q4_Sales - Q3_Sales, 2) AS AbsoluteGrowth,
    ROUND(((Q4_Sales - Q3_Sales) / NULLIF(Q3_Sales, 0)) * 100.0, 2) AS GrowthPct
FROM SalespersonQuarterlySales
WHERE Q3_Sales > 0 
  AND ((Q4_Sales - Q3_Sales) / Q3_Sales) * 100.0 > 20
ORDER BY GrowthPct DESC;"""
    },
    {
        "id": "choco_market_divergence_cross_country",
        "domain": "awesome_chocolates",
        "category": "market_divergence",
        "tags": [
            "thị trường", "ấn độ", "india", "mỹ", "usa", "bán chạy nhất", "ế ẩm", "ế nhất",
            "doanh số thấp nhất", "nghịch lý", "nhưng lại", "phân hóa", "đối lập", "cross-market",
            "divergence", "xếp hạng", "rank", "rank divergence"
        ],
        "question": "Sản phẩm nào bán chạy nhất tại thị trường Ấn Độ (India) nhưng lại ế ẩm nhất (doanh số thấp nhất) tại thị trường Mỹ (USA)?",
        "question_en": "Which product is the best-selling in India but has the lowest sales (slowest-selling) in the USA market?",
        "intent_explanation": "Sử dụng 2 CTE tính tổng doanh số và thứ hạng DENSE_RANK() theo từng thị trường quốc gia (Ấn Độ và Mỹ). Sau đó tính RankDivergence = (USARank - IndiaRank) để tìm sản phẩm có thứ hạng cao tại Ấn Độ nhưng tụt hậu nhiều nhất tại Mỹ.",
        "sql_mysql": """WITH IndiaSales AS (
    SELECT 
        pr.Product AS Product,
        SUM(s.Amount) AS IndiaSales,
        DENSE_RANK() OVER (ORDER BY SUM(s.Amount) DESC) AS IndiaRank
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE g.Geo = 'India'
    GROUP BY pr.PID, pr.Product
),
USASales AS (
    SELECT 
        pr.Product AS Product,
        SUM(s.Amount) AS USASales,
        DENSE_RANK() OVER (ORDER BY SUM(s.Amount) DESC) AS USARank
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE g.Geo = 'USA'
    GROUP BY pr.PID, pr.Product
)
SELECT 
    i.Product AS Product,
    i.IndiaSales AS IndiaSales,
    i.IndiaRank AS IndiaRank,
    u.USASales AS USASales,
    u.USARank AS USARank,
    (CAST(u.USARank AS SIGNED) - CAST(i.IndiaRank AS SIGNED)) AS RankDivergence
FROM IndiaSales i
JOIN USASales u ON i.Product = u.Product
ORDER BY RankDivergence DESC, i.IndiaSales DESC
LIMIT 5;""",
        "sql_sqlite": """WITH IndiaSales AS (
    SELECT 
        pr.Product AS Product,
        SUM(s.Amount) AS IndiaSales,
        DENSE_RANK() OVER (ORDER BY SUM(s.Amount) DESC) AS IndiaRank
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE g.Geo = 'India'
    GROUP BY pr.PID, pr.Product
),
USASales AS (
    SELECT 
        pr.Product AS Product,
        SUM(s.Amount) AS USASales,
        DENSE_RANK() OVER (ORDER BY SUM(s.Amount) DESC) AS USARank
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE g.Geo = 'USA'
    GROUP BY pr.PID, pr.Product
)
SELECT 
    i.Product AS Product,
    i.IndiaSales AS IndiaSales,
    i.IndiaRank AS IndiaRank,
    u.USASales AS USASales,
    u.USARank AS USARank,
    (CAST(u.USARank AS INTEGER) - CAST(i.IndiaRank AS INTEGER)) AS RankDivergence
FROM IndiaSales i
JOIN USASales u ON i.Product = u.Product
ORDER BY RankDivergence DESC, i.IndiaSales DESC
LIMIT 5;"""
    },
    {
        "id": "choco_salesperson_never_sold_category_in_geo",
        "domain": "awesome_chocolates",
        "category": "anti_join",
        "tags": [
            "chưa từng", "chưa từng bán", "chưa bao giờ", "không bán được", "danh mục", "bars",
            "ấn độ", "india", "thị trường", "nhân viên", "nhân sự", "liệt kê", "anti-join", "not in", "not exists"
        ],
        "question": "Liệt kê những nhân viên kinh doanh chưa từng bán được bất kỳ một hộp sản phẩm nào thuộc danh mục 'Bars' tại thị trường Ấn Độ (India).",
        "question_en": "List salespersons who have never sold any boxes of products belonging to category 'Bars' in the India market.",
        "intent_explanation": "Sử dụng truy vấn phủ định NOT IN hoặc NOT EXISTS để lọc danh sách nhân sự trong bảng people mà mã SPID không xuất hiện trong các giao dịch bảng sales có sản phẩm thuộc Category 'Bars' tại Geo 'India'.",
        "sql_mysql": """SELECT 
    pe.SPID,
    pe.Salesperson,
    pe.Team
FROM people pe
WHERE pe.SPID NOT IN (
    SELECT DISTINCT s.SPID
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE pr.Category = 'Bars' AND g.Geo = 'India'
)
ORDER BY pe.Salesperson ASC;""",
        "sql_sqlite": """SELECT 
    pe.SPID,
    pe.Salesperson,
    pe.Team
FROM people pe
WHERE pe.SPID NOT IN (
    SELECT DISTINCT s.SPID
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    JOIN geo g ON s.GeoID = g.GeoID
    WHERE pr.Category = 'Bars' AND g.Geo = 'India'
)
ORDER BY pe.Salesperson ASC;"""
    },
    {
        "id": "choco_salesperson_highest_avg_price_per_box_threshold",
        "domain": "awesome_chocolates",
        "category": "salesperson_avg_price_per_box",
        "tags": [
            "nhân viên", "nhân sự", "salesperson", "đơn giá trung bình", "mỗi hộp", 
            "giá trung bình mỗi hộp", "cao nhất", "500000", "500,000 usd", "ngưỡng doanh số", 
            "avg price per box", "bán ra cao nhất", "hiệu quả"
        ],
        "question": "Nhân viên kinh doanh nào đạt đơn giá trung bình mỗi hộp bán ra cao nhất (chỉ xét những người có tổng doanh số trên 500,000 USD)?",
        "question_en": "Which salesperson achieved the highest average price per box sold (considering only those with total sales over 500,000 USD)?",
        "intent_explanation": "Nhóm theo pe.Salesperson, tính đơn giá trung bình mỗi hộp AvgPricePerBox = ROUND(SUM(s.Amount)/NULLIF(SUM(s.Boxes), 0), 2), lọc điều kiện ngưỡng doanh số HAVING SUM(s.Amount) > 500000, sắp xếp theo AvgPricePerBox giảm dần và LIMIT 1.",
        "sql_mysql": """SELECT 
    pe.Salesperson AS Salesperson,
    ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
GROUP BY pe.Salesperson
HAVING SUM(s.Amount) > 500000
ORDER BY AvgPricePerBox DESC
LIMIT 1;""",
        "sql_sqlite": """SELECT 
    pe.Salesperson AS Salesperson,
    ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
GROUP BY pe.Salesperson
HAVING SUM(s.Amount) > 500000
ORDER BY AvgPricePerBox DESC
LIMIT 1;"""
    },
    {
        "id": "choco_country_highest_avg_price_per_box",
        "domain": "awesome_chocolates",
        "category": "avg_price_per_box",
        "tags": [
            "thị trường", "quốc gia", "country", "đơn giá trung bình", "mỗi hộp", 
            "giá trung bình mỗi hộp", "cao nhất", "nào", "avg price per box", "giá bán trung bình", "hiệu quả"
        ],
        "question": "Thị trường quốc gia nào có đơn giá trung bình mỗi hộp bán ra cao nhất?",
        "question_en": "Which country market has the highest average price per box sold?",
        "intent_explanation": "Nhóm theo g.Geo, tính AvgPricePerBox = ROUND(SUM(s.Amount)/NULLIF(SUM(s.Boxes), 0), 2), sắp xếp ORDER BY AvgPricePerBox DESC LIMIT 1.",
        "sql_mysql": """SELECT 
    g.Geo AS Country,
    ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
GROUP BY g.Geo
ORDER BY AvgPricePerBox DESC
LIMIT 1;""",
        "sql_sqlite": """SELECT 
    g.Geo AS Country,
    ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
GROUP BY g.Geo
ORDER BY AvgPricePerBox DESC
LIMIT 1;"""
    },
    {
        "id": "choco_monthly_revenue_and_boxes_trend_2021",
        "domain": "awesome_chocolates",
        "category": "monthly_trend",
        "tags": [
            "xu hướng", "doanh thu", "số hộp", "theo từng tháng", "năm 2021", "tổng doanh thu", "hộp bán ra", "tháng",
            "biến động", "doanh số", "số lượng hộp"
        ],
        "question": "Xu hướng tổng doanh thu và số hộp bán ra theo từng tháng trong năm 2021 thay đổi như thế nào?",
        "question_en": "How did total revenue and boxes sold change by month in 2021?",
        "intent_explanation": "Tính xu hướng theo từng tháng trong năm 2021 cho cả 2 chỉ số: SUM(s.Amount) AS TotalRevenue và SUM(s.Boxes) AS TotalBoxesSold, lọc WHERE YEAR(s.SaleDate) = 2021, nhóm theo Month và sắp xếp tăng dần.",
        "sql_mysql": """SELECT 
    MONTH(s.SaleDate) AS Month,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
WHERE YEAR(s.SaleDate) = 2021
GROUP BY Month
ORDER BY Month ASC;""",
        "sql_sqlite": """SELECT 
    CAST(strftime('%m', s.SaleDate) AS INTEGER) AS Month,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
WHERE strftime('%Y', s.SaleDate) = '2021'
GROUP BY Month
ORDER BY Month ASC;"""
    },
    {
        "id": "choco_team_monthly_revenue_trend_2021",
        "domain": "awesome_chocolates",
        "category": "monthly_trend",
        "tags": [
            "team yummies", "yummies", "delish", "jucies", "doanh thu", "qua các tháng", "năm 2021",
            "thay đổi như thế nào", "xu hướng", "tháng", "đội ngũ", "team"
        ],
        "question": "Doanh thu của Team Yummies thay đổi như thế nào qua các tháng năm 2021?",
        "question_en": "How did revenue for Team Yummies change across months in 2021?",
        "intent_explanation": "Tính xu hướng doanh thu theo từng tháng trong năm 2021 của riêng Team Yummies. Liên kết sales s với people pe ON s.SPID = pe.SPID, lọc pe.Team = 'Yummies' VÀ YEAR(s.SaleDate) = 2021, nhóm theo Month và sắp xếp theo Month tăng dần.",
        "sql_mysql": """SELECT 
    DATE_FORMAT(s.SaleDate, '%Y-%m') AS Month,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team = 'Yummies' AND YEAR(s.SaleDate) = 2021
GROUP BY Month
ORDER BY Month ASC;""",
        "sql_sqlite": """SELECT 
    strftime('%Y-%m', s.SaleDate) AS Month,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team = 'Yummies' AND strftime('%Y', s.SaleDate) = '2021'
GROUP BY Month
ORDER BY Month ASC;"""
    },
    # =========================================================================
    # NHÓM 3: CSDL SAKILA (DVD RENTAL STORE)
    # =========================================================================
    {
        "id": "sakila_monthly_revenue_contribution_percentage",
        "domain": "sakila",
        "category": "contribution_percentage",
        "tags": [
            "tỷ lệ", "phần trăm", "đóng góp", "tỷ trọng", "tỉ lệ", "tỉ trọng", "percentage", "contribution",
            "từng tháng", "theo tháng", "month", "doanh thu", "total revenue", "revenue", "payment", "sakila"
        ],
        "question": "Tỷ lệ phần trăm đóng góp của từng Month vào tổng Total Revenue",
        "question_en": "Percentage contribution of each month to total revenue",
        "intent_explanation": "Dùng CTE tính TotalRevenue = SUM(p.amount) theo DATE_FORMAT(p.payment_date, '%Y-%m') từ bảng payment p, sau đó tính ContributionPercentage = ROUND(TotalRevenue * 100.0 / (SELECT SUM(TotalRevenue) FROM MonthlyRevenue), 2).",
        "sql_mysql": """WITH MonthlyRevenue AS (
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
ORDER BY Month ASC;""",
        "sql_sqlite": """WITH MonthlyRevenue AS (
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
ORDER BY Month ASC;"""
    },
    {
        "id": "sakila_monthly_revenue_and_rentals",
        "domain": "sakila",
        "category": "monthly_trend",
        "tags": [
            "biến động", "doanh thu", "từng tháng", "qua các tháng", "theo tháng",
            "số lượt thuê", "thuê phim", "payment", "rental", "sakila"
        ],
        "question": "Biến động tổng doanh thu theo từng tháng trong năm (kèm số lượt thuê phim)",
        "question_en": "Monthly total revenue and rental count trend over time",
        "intent_explanation": "Truy vấn bảng payment p của Sakila, định dạng tháng bằng DATE_FORMAT(p.payment_date, '%Y-%m') AS Month, tính SUM(p.amount) AS TotalRevenue và COUNT(p.rental_id) AS TotalRentals, nhóm theo Month và sắp xếp tăng dần.",
        "sql_mysql": """SELECT 
    DATE_FORMAT(p.payment_date, '%Y-%m') AS Month,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.rental_id) AS TotalRentals
FROM payment p
GROUP BY DATE_FORMAT(p.payment_date, '%Y-%m')
ORDER BY Month ASC;""",
        "sql_sqlite": """SELECT 
    strftime('%Y-%m', p.payment_date) AS Month,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.rental_id) AS TotalRentals
FROM payment p
GROUP BY strftime('%Y-%m', p.payment_date)
ORDER BY Month ASC;"""
    },
    {
        "id": "sakila_top_categories_by_revenue",
        "domain": "sakila",
        "category": "category_ranking",
        "tags": [
            "thể loại", "thể loại phim", "category", "doanh thu", "cao nhất", "top 5", "sakila"
        ],
        "question": "Top 5 thể loại phim có tổng doanh thu cho thuê cao nhất là những thể loại nào?",
        "question_en": "Top 5 film categories with the highest rental revenue",
        "intent_explanation": "JOIN category c -> film_category fc -> film f -> inventory i -> rental r -> payment p, tính SUM(p.amount) AS TotalRevenue theo từng c.name và lấy Top 5.",
        "sql_mysql": """SELECT 
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
LIMIT 5;""",
        "sql_sqlite": """SELECT 
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
LIMIT 5;"""
    },
    {
        "id": "sakila_top_actors_by_films",
        "domain": "sakila",
        "category": "actor_ranking",
        "tags": [
            "diễn viên", "actor", "tham gia nhiều phim", "đóng nhiều phim nhất", "top 10", "sakila"
        ],
        "question": "Top 10 diễn viên tham gia nhiều bộ phim nhất",
        "question_en": "Top 10 actors who have appeared in the most films",
        "intent_explanation": "JOIN actor a với film_actor fa ON a.actor_id = fa.actor_id, đếm COUNT(fa.film_id) AS TotalFilms, nhóm theo a.actor_id và CONCAT(a.first_name, ' ', a.last_name) AS ActorName, sắp xếp giảm dần LIMIT 10.",
        "sql_mysql": """SELECT 
    a.actor_id,
    CONCAT(a.first_name, ' ', a.last_name) AS ActorName,
    COUNT(fa.film_id) AS TotalFilms
FROM actor a
JOIN film_actor fa ON a.actor_id = fa.actor_id
GROUP BY a.actor_id, ActorName
ORDER BY TotalFilms DESC
LIMIT 10;""",
        "sql_sqlite": """SELECT 
    a.actor_id,
    a.first_name || ' ' || a.last_name AS ActorName,
    COUNT(fa.film_id) AS TotalFilms
FROM actor a
JOIN film_actor fa ON a.actor_id = fa.actor_id
GROUP BY a.actor_id, ActorName
ORDER BY TotalFilms DESC
LIMIT 10;"""
    },
    {
        "id": "sakila_top_customers_by_spent",
        "domain": "sakila",
        "category": "customer_ranking",
        "tags": [
            "khách hàng", "customer", "chi tiêu", "nhiều tiền nhất", "thuê phim", "top 10", "sakila"
        ],
        "question": "Top 10 khách hàng chi tiêu nhiều tiền nhất cho việc thuê phim",
        "question_en": "Top 10 customers who spent the most money on rentals",
        "intent_explanation": "JOIN customer cu với payment p ON cu.customer_id = p.customer_id, tính SUM(p.amount) AS TotalSpent, nhóm theo cu.customer_id và họ tên, sắp xếp giảm dần LIMIT 10.",
        "sql_mysql": """SELECT 
    cu.customer_id,
    CONCAT(cu.first_name, ' ', cu.last_name) AS CustomerName,
    SUM(p.amount) AS TotalSpent
FROM customer cu
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY cu.customer_id, CustomerName
ORDER BY TotalSpent DESC
LIMIT 10;""",
        "sql_sqlite": """SELECT 
    cu.customer_id,
    cu.first_name || ' ' || cu.last_name AS CustomerName,
    SUM(p.amount) AS TotalSpent
FROM customer cu
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY cu.customer_id, CustomerName
ORDER BY TotalSpent DESC
LIMIT 10;"""
    },
    {
        "id": "sakila_store_comparison",
        "domain": "sakila",
        "category": "store_comparison",
        "tags": [
            "so sánh", "chi nhánh", "cửa hàng", "store", "doanh thu", "giao dịch", "sakila"
        ],
        "question": "So sánh tổng doanh thu và số lượng giao dịch giữa 2 chi nhánh cửa hàng",
        "question_en": "Compare total revenue and transaction counts between the two stores",
        "intent_explanation": "JOIN store st với staff s ON st.store_id = s.store_id và payment p ON s.staff_id = p.staff_id, tính SUM(p.amount) AS TotalRevenue và COUNT(p.payment_id) AS TotalTransactions theo st.store_id.",
        "sql_mysql": """SELECT 
    st.store_id AS StoreID,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.payment_id) AS TotalTransactions
FROM store st
JOIN staff s ON st.store_id = s.store_id
JOIN payment p ON s.staff_id = p.staff_id
GROUP BY st.store_id
ORDER BY st.store_id ASC;""",
        "sql_sqlite": """SELECT 
    st.store_id AS StoreID,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.payment_id) AS TotalTransactions
FROM store st
JOIN staff s ON st.store_id = s.store_id
JOIN payment p ON s.staff_id = p.staff_id
GROUP BY st.store_id
ORDER BY st.store_id ASC;"""
    },
    # =========================================================================
    # NHÓM 4: CSDL TỔNG QUÁT / TÙY Ý (GENERIC / ARBITRARY DATABASE PATTERNS)
    # =========================================================================
    {
        "id": "generic_monthly_trend",
        "domain": "generic",
        "category": "monthly_trend",
        "tags": [
            "tháng", "từng tháng", "qua các tháng", "xu hướng", "biến động", "doanh thu", "số lượng"
        ],
        "question": "Biến động tổng doanh thu hoặc số lượng giao dịch theo từng tháng trong năm",
        "question_en": "Monthly total revenue and transaction volume trend over time",
        "intent_explanation": "Định dạng tháng (DATE_FORMAT hoặc strftime '%Y-%m') làm trục thời gian liên tục, tính tổng số tiền SUM(amount) và đếm số lượng COUNT(id), nhóm theo Month và sắp xếp tăng dần.",
        "sql_mysql": """SELECT 
    DATE_FORMAT(t.transaction_date, '%Y-%m') AS Month,
    SUM(t.amount) AS TotalRevenue,
    COUNT(t.id) AS TotalCount
FROM transactions t
GROUP BY DATE_FORMAT(t.transaction_date, '%Y-%m')
ORDER BY Month ASC;""",
        "sql_sqlite": """SELECT 
    strftime('%Y-%m', t.transaction_date) AS Month,
    SUM(t.amount) AS TotalRevenue,
    COUNT(t.id) AS TotalCount
FROM transactions t
GROUP BY strftime('%Y-%m', t.transaction_date)
ORDER BY Month ASC;"""
    },
    {
        "id": "generic_top_entities_ranking",
        "domain": "generic",
        "category": "ranking",
        "tags": [
            "top", "cao nhất", "lớn nhất", "nhiều nhất", "danh sách", "xếp hạng"
        ],
        "question": "Top 10 thực thể (khách hàng/sản phẩm/danh mục) có giá trị cao nhất",
        "question_en": "Top 10 entities (customers/products/categories) with the highest total value",
        "intent_explanation": "JOIN bảng danh mục/thực thể với bảng giao dịch, tính tổng SUM(amount) theo tên thực thể, sắp xếp giảm dần và lấy LIMIT N.",
        "sql_mysql": """SELECT 
    e.name AS EntityName,
    SUM(t.amount) AS TotalAmount
FROM entities e
JOIN transactions t ON e.id = t.entity_id
GROUP BY e.id, e.name
ORDER BY TotalAmount DESC
LIMIT 10;""",
        "sql_sqlite": """SELECT 
    e.name AS EntityName,
    SUM(t.amount) AS TotalAmount
FROM entities e
JOIN transactions t ON e.id = t.entity_id
GROUP BY e.id, e.name
ORDER BY TotalAmount DESC
LIMIT 10;"""
    },
    {
        "id": "generic_multi_step_cte_benchmark",
        "domain": "generic",
        "category": "benchmark_cte",
        "tags": [
            "cao hơn trung bình", "so với trung bình", "mức bình quân", "chênh lệch", "cte"
        ],
        "question": "Các đối tượng có giá trị cao hơn mức trung bình của toàn hệ thống",
        "question_en": "Items with values higher than the overall system average",
        "intent_explanation": "Sử dụng CTE để tính mức trung bình toàn hệ thống trước, sau đó JOIN/CROSS JOIN với dữ liệu chi tiết và lọc WHERE item_value > AvgValue.",
        "sql_mysql": """WITH SystemAvg AS (
    SELECT AVG(amount) AS AvgAmount
    FROM transactions
)
SELECT 
    t.name AS ItemName,
    t.amount AS ItemAmount,
    sa.AvgAmount AS BenchmarkAvg,
    (t.amount - sa.AvgAmount) AS Difference
FROM transactions t
CROSS JOIN SystemAvg sa
WHERE t.amount > sa.AvgAmount
ORDER BY Difference DESC;""",
        "sql_sqlite": """WITH SystemAvg AS (
    SELECT AVG(amount) AS AvgAmount
    FROM transactions
)
SELECT 
    t.name AS ItemName,
    t.amount AS ItemAmount,
    sa.AvgAmount AS BenchmarkAvg,
    (t.amount - sa.AvgAmount) AS Difference
FROM transactions t
CROSS JOIN SystemAvg sa
WHERE t.amount > sa.AvgAmount
ORDER BY Difference DESC;"""
    },
    {
        "id": "generic_category_distribution_percentage",
        "domain": "generic",
        "category": "distribution",
        "tags": [
            "tỷ lệ", "phân bố", "cơ cấu", "phần trăm", "tỉ trọng", "share"
        ],
        "question": "Tỷ lệ phân bố số lượng và phần trăm đóng góp theo từng danh mục",
        "question_en": "Distribution count and contribution percentage by category",
        "intent_explanation": "Nhóm theo danh mục, tính COUNT(item_id) và tính tỷ lệ phần trăm so với tổng thể bằng Subquery tính tổng toàn bộ bảng.",
        "sql_mysql": """SELECT 
    c.name AS CategoryName,
    COUNT(i.id) AS ItemCount,
    ROUND(COUNT(i.id) * 100.0 / (SELECT COUNT(*) FROM items), 2) AS Percentage
FROM categories c
JOIN items i ON c.id = i.category_id
GROUP BY c.id, c.name
ORDER BY ItemCount DESC;""",
        "sql_sqlite": """SELECT 
    c.name AS CategoryName,
    COUNT(i.id) AS ItemCount,
    ROUND(COUNT(i.id) * 100.0 / (SELECT COUNT(*) FROM items), 2) AS Percentage
FROM categories c
JOIN items i ON c.id = i.category_id
GROUP BY c.id, c.name
ORDER BY ItemCount DESC;"""
    },
    # =========================================================================
    # NHÓM: CSDL NORTHWIND TRADERS (ENTERPRISE ERP & SALES)
    # =========================================================================
    {
        "id": "northwind_top_products_by_revenue",
        "domain": "northwind",
        "category": "ranking",
        "tags": [
            "sản phẩm", "doanh thu", "bán chạy", "doanh số", "cao nhất", "top", "products", "revenue"
        ],
        "question": "Top 5 sản phẩm có doanh thu cao nhất của công ty?",
        "question_en": "Top 5 products by total revenue in the company?",
        "intent_explanation": "JOIN bảng order_details và products qua od.product_id = p.id, tính tổng doanh thu ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2), GROUP BY p.id, p.product_name và ORDER BY TotalRevenue DESC LIMIT 5.",
        "sql_mysql": """SELECT 
    p.product_name AS Product,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalRevenue
FROM order_details od
JOIN products p ON od.product_id = p.id
GROUP BY p.id, p.product_name
ORDER BY TotalRevenue DESC
LIMIT 5;""",
        "sql_sqlite": """SELECT 
    p.product_name AS Product,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalRevenue
FROM order_details od
JOIN products p ON od.product_id = p.id
GROUP BY p.id, p.product_name
ORDER BY TotalRevenue DESC
LIMIT 5;"""
    },
    {
        "id": "northwind_top_sales_employees",
        "domain": "northwind",
        "category": "ranking",
        "tags": [
            "nhân viên", "doanh thu", "bán hàng", "doanh số", "nhân sự", "employees", "sales"
        ],
        "question": "Nhân viên nào mang lại nhiều doanh thu nhất qua các năm?",
        "question_en": "Which employees generated the most revenue over the years?",
        "intent_explanation": "JOIN orders, order_details và employees qua o.id = od.order_id và o.employee_id = e.id, tính tổng doanh số và số lượng đơn hàng, sắp xếp giảm dần.",
        "sql_mysql": """SELECT 
    CONCAT(e.first_name, ' ', e.last_name) AS EmployeeName,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalSales,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM orders o
JOIN order_details od ON o.id = od.order_id
JOIN employees e ON o.employee_id = e.id
GROUP BY e.id, EmployeeName
ORDER BY TotalSales DESC
LIMIT 5;""",
        "sql_sqlite": """SELECT 
    e.first_name || ' ' || e.last_name AS EmployeeName,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalSales,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM orders o
JOIN order_details od ON o.id = od.order_id
JOIN employees e ON o.employee_id = e.id
GROUP BY e.id, EmployeeName
ORDER BY TotalSales DESC
LIMIT 5;"""
    },
    {
        "id": "northwind_country_orders_revenue",
        "domain": "northwind",
        "category": "geo_sales",
        "tags": [
            "quốc gia", "country", "thị trường", "doanh thu", "đơn hàng", "orders"
        ],
        "question": "Tổng doanh thu và số lượng đơn hàng theo từng quốc gia của khách hàng?",
        "question_en": "Total revenue and number of orders by customer country?",
        "intent_explanation": "JOIN customers, orders và order_details, nhóm theo c.country_region, đếm COUNT(DISTINCT o.id) và tính SUM doanh thu.",
        "sql_mysql": """SELECT 
    c.country_region AS Country,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalRevenue
FROM customers c
JOIN orders o ON c.id = o.customer_id
JOIN order_details od ON o.id = od.order_id
GROUP BY c.country_region
ORDER BY TotalRevenue DESC;""",
        "sql_sqlite": """SELECT 
    c.country_region AS Country,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalRevenue
FROM customers c
JOIN orders o ON c.id = o.customer_id
JOIN order_details od ON o.id = od.order_id
GROUP BY c.country_region
ORDER BY TotalRevenue DESC;"""
    },
    {
        "id": "northwind_monthly_revenue_trend",
        "domain": "northwind",
        "category": "time_series",
        "tags": [
            "xu hướng", "trend", "thay đổi", "thời gian", "doanh thu", "revenue", "total revenue", "tháng", "monthly"
        ],
        "question": "Xu hướng thay đổi của Total Revenue theo thời gian?",
        "question_en": "Trend of Total Revenue over time?",
        "intent_explanation": "JOIN orders và order_details, nhóm theo định dạng tháng của order_date, tính tổng doanh thu và số lượng đơn hàng.",
        "sql_mysql": """SELECT 
    DATE_FORMAT(o.order_date, '%Y-%m') AS Month,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM orders o
JOIN order_details od ON o.id = od.order_id
WHERE o.order_date IS NOT NULL
GROUP BY Month
ORDER BY Month ASC;""",
        "sql_sqlite": """SELECT 
    substr(o.order_date, 1, 7) AS Month,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM orders o
JOIN order_details od ON o.id = od.order_id
WHERE o.order_date IS NOT NULL
GROUP BY Month
ORDER BY Month ASC;"""
    },
    {
        "id": "northwind_category_revenue_breakdown",
        "domain": "northwind",
        "category": "category_breakdown",
        "tags": [
            "danh mục", "category", "cơ cấu", "doanh thu", "revenue", "tỷ trọng"
        ],
        "question": "Cơ cấu doanh thu theo từng danh mục sản phẩm của Northwind?",
        "question_en": "Revenue breakdown by product category in Northwind?",
        "intent_explanation": "JOIN products và order_details, nhóm theo p.category và tính tổng doanh thu cùng sản lượng.",
        "sql_mysql": """SELECT 
    COALESCE(p.category, 'Other') AS Category,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    SUM(od.quantity) AS TotalQuantity
FROM products p
JOIN order_details od ON p.id = od.product_id
GROUP BY Category
ORDER BY TotalRevenue DESC;""",
        "sql_sqlite": """SELECT 
    COALESCE(p.category, 'Other') AS Category,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    SUM(od.quantity) AS TotalQuantity
FROM products p
JOIN order_details od ON p.id = od.product_id
GROUP BY Category
ORDER BY TotalRevenue DESC;"""
    },
    {
        "id": "northwind_top_customers_by_spend",
        "domain": "northwind",
        "category": "ranking",
        "tags": [
            "khách hàng", "chi tiêu", "doanh số", "doanh thu", "customers", "spend"
        ],
        "question": "Top 5 khách hàng chi tiêu nhiều tiền nhất?",
        "question_en": "Top 5 customers by total spending?",
        "intent_explanation": "JOIN customers, orders và order_details, nhóm theo khách hàng và tính tổng chi tiêu.",
        "sql_mysql": """SELECT 
    c.company AS Company,
    CONCAT(c.first_name, ' ', c.last_name) AS CustomerName,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalSpend,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM customers c
JOIN orders o ON c.id = o.customer_id
JOIN order_details od ON o.id = od.order_id
GROUP BY c.id, c.company, CustomerName
ORDER BY TotalSpend DESC
LIMIT 5;""",
        "sql_sqlite": """SELECT 
    c.company AS Company,
    c.first_name || ' ' || c.last_name AS CustomerName,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalSpend,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM customers c
JOIN orders o ON c.id = o.customer_id
JOIN order_details od ON o.id = od.order_id
GROUP BY c.id, c.company, CustomerName
ORDER BY TotalSpend DESC
LIMIT 5;"""
    },
    {
        "id": "northwind_city_amount_due_contribution",
        "domain": "northwind",
        "category": "contribution_percentage",
        "tags": [
            "tỷ lệ", "đóng góp", "amount due", "amount_due", "thành phố", "city", "tổng số", "tỷ trọng", "phần trăm"
        ],
        "question": "Tỷ lệ đóng góp amount due của từng thành phố vào tổng số?",
        "question_en": "Percentage contribution of amount due by each city to the total?",
        "intent_explanation": "JOIN orders (o.ship_city) và order_details / customers (c.city), tính tổng amount_due từng thành phố bằng CTE, sau đó tính tỷ lệ % đóng góp trên tổng số toàn công ty.",
        "sql_mysql": """WITH CityAmountDue AS (
    SELECT 
        COALESCE(o.ship_city, c.city, 'Unknown') AS City,
        SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) AS TotalAmountDue
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    LEFT JOIN customers c ON o.customer_id = c.id
    WHERE o.ship_city IS NOT NULL OR c.city IS NOT NULL
    GROUP BY City
)
SELECT 
    City,
    ROUND(TotalAmountDue, 2) AS TotalAmountDue,
    ROUND(TotalAmountDue * 100.0 / (SELECT SUM(TotalAmountDue) FROM CityAmountDue), 2) AS ContributionPercentage
FROM CityAmountDue
ORDER BY ContributionPercentage DESC;""",
        "sql_sqlite": """WITH CityAmountDue AS (
    SELECT 
        COALESCE(o.ship_city, c.city, 'Unknown') AS City,
        SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) AS TotalAmountDue
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    LEFT JOIN customers c ON o.customer_id = c.id
    WHERE o.ship_city IS NOT NULL OR c.city IS NOT NULL
    GROUP BY City
)
SELECT 
    City,
    ROUND(TotalAmountDue, 2) AS TotalAmountDue,
    ROUND(TotalAmountDue * 100.0 / (SELECT SUM(TotalAmountDue) FROM CityAmountDue), 2) AS ContributionPercentage
FROM CityAmountDue
ORDER BY ContributionPercentage DESC;"""
    },
    {
        "id": "northwind_amount_due_extremes_comparison",
        "domain": "northwind",
        "category": "extremes",
        "tags": [
            "chênh lệch", "sự chênh lệch", "nhóm cao nhất và nhóm thấp nhất", "nhóm cao nhất", "nhóm thấp nhất",
            "khoảng cách", "amount due", "amount_due", "extremes", "spread", "cực trị"
        ],
        "question": "Phân tích sự chênh lệch amount due giữa nhóm cao nhất và nhóm thấp nhất?",
        "question_en": "Analyze the amount due difference between the highest and lowest groups?",
        "intent_explanation": "Nhóm theo khách hàng trên bảng orders JOIN order_details và customers, tính tổng, trung bình, lớn nhất, nhỏ nhất và độ chênh lệch (AmountSpread = MaxAmountDue - MinAmountDue), sắp xếp giảm dần theo TotalAmountDue.",
        "sql_mysql": """WITH CustomerDueSummary AS (
    SELECT 
        COALESCE(c.company, CONCAT(c.first_name, ' ', c.last_name), 'Unknown') AS CustomerGroup,
        COALESCE(c.country_region, 'Unknown') AS Country,
        COUNT(DISTINCT o.id) AS TotalOrders,
        ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
        ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDue,
        ROUND(MAX(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS MaxAmountDue,
        ROUND(MIN(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS MinAmountDue
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    LEFT JOIN customers c ON o.customer_id = c.id
    GROUP BY c.id, CustomerGroup, c.country_region
)
SELECT 
    CustomerGroup,
    Country,
    TotalOrders,
    TotalAmountDue,
    AvgAmountDue,
    MaxAmountDue,
    MinAmountDue,
    ROUND(MaxAmountDue - MinAmountDue, 2) AS AmountSpread
FROM CustomerDueSummary
ORDER BY TotalAmountDue DESC;""",
        "sql_sqlite": """WITH CustomerDueSummary AS (
    SELECT 
        COALESCE(c.company, c.first_name || ' ' || c.last_name, 'Unknown') AS CustomerGroup,
        COALESCE(c.country_region, 'Unknown') AS Country,
        COUNT(DISTINCT o.id) AS TotalOrders,
        ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
        ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDue,
        ROUND(MAX(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS MaxAmountDue,
        ROUND(MIN(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS MinAmountDue
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    LEFT JOIN customers c ON o.customer_id = c.id
    GROUP BY c.id, CustomerGroup, c.country_region
)
SELECT 
    CustomerGroup,
    Country,
    TotalOrders,
    TotalAmountDue,
    AvgAmountDue,
    MaxAmountDue,
    MinAmountDue,
    ROUND(MaxAmountDue - MinAmountDue, 2) AS AmountSpread
FROM CustomerDueSummary
ORDER BY TotalAmountDue DESC;"""
    },
    {
        "id": "northwind_job_title_amount_due_above_avg",
        "domain": "northwind",
        "category": "above_average",
        "tags": [
            "vị trí công việc", "vị trí", "chức vụ", "chức danh", "job_title", "job title",
            "amount due", "amount_due", "vượt trên mức trung bình", "mức trung bình", "trung bình", "above average"
        ],
        "question": "Những vị trí công việc nào có amount due vượt trên mức trung bình?",
        "question_en": "Which job titles have an amount due exceeding the average?",
        "intent_explanation": "Trong Northwind, chức vụ/vị trí công việc nằm ở cột employees.job_title (e.job_title), tính amount_due từ orders JOIN order_details. Liên kết employees -> orders -> order_details qua e.id = o.employee_id và o.id = od.order_id, gom nhóm theo e.job_title và lọc HAVING AVG(od.quantity * od.unit_price * (1 - od.discount)) > mức trung bình toàn bộ đơn hàng.",
        "sql_mysql": """SELECT 
    COALESCE(e.job_title, 'Unknown') AS JobTitle,
    COUNT(DISTINCT e.id) AS EmployeeCount,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDue,
    (SELECT ROUND(AVG(od2.quantity * od2.unit_price * (1 - COALESCE(od2.discount, 0))), 2) FROM order_details od2) AS CompanyAvgAmountDue,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) - (SELECT AVG(od2.quantity * od2.unit_price * (1 - COALESCE(od2.discount, 0))) FROM order_details od2), 2) AS AmountSurplus
FROM employees e
JOIN orders o ON e.id = o.employee_id
JOIN order_details od ON o.id = od.order_id
GROUP BY e.job_title
HAVING AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) > (SELECT AVG(od2.quantity * od2.unit_price * (1 - COALESCE(od2.discount, 0))) FROM order_details od2)
ORDER BY AvgAmountDue DESC;""",
        "sql_sqlite": """SELECT 
    COALESCE(e.job_title, 'Unknown') AS JobTitle,
    COUNT(DISTINCT e.id) AS EmployeeCount,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDue,
    (SELECT ROUND(AVG(od2.quantity * od2.unit_price * (1 - COALESCE(od2.discount, 0))), 2) FROM order_details od2) AS CompanyAvgAmountDue,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) - (SELECT AVG(od2.quantity * od2.unit_price * (1 - COALESCE(od2.discount, 0))) FROM order_details od2), 2) AS AmountSurplus
FROM employees e
JOIN orders o ON e.id = o.employee_id
JOIN order_details od ON o.id = od.order_id
GROUP BY e.job_title
HAVING AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) > (SELECT AVG(od2.quantity * od2.unit_price * (1 - COALESCE(od2.discount, 0))) FROM order_details od2)
ORDER BY AvgAmountDue DESC;"""
    },
    {
        "id": "northwind_job_title_headcount_comparison",
        "domain": "northwind",
        "category": "headcount",
        "tags": [
            "so sánh", "employee count", "headcount", "job title", "job_title", "chức danh", "chức vụ",
            "vị trí", "số lượng nhân sự", "số lượng nhân viên", "nhân sự", "nhân viên", "quy mô"
        ],
        "question": "So sánh Employee Count giữa các Job Title hàng đầu?",
        "question_en": "Compare Employee Count across top Job Titles?",
        "intent_explanation": "Trong Northwind, chức danh nằm ở employees.job_title, đếm số lượng nhân viên bằng COUNT(DISTINCT e.id), tính tỷ lệ % trên tổng nhân sự toàn công ty và gom nhóm theo e.job_title, sắp xếp giảm dần.",
        "sql_mysql": """SELECT 
    COALESCE(e.job_title, 'Unknown') AS JobTitle,
    COUNT(DISTINCT e.id) AS EmployeeCount,
    ROUND(COUNT(DISTINCT e.id) * 100.0 / (SELECT COUNT(*) FROM employees), 2) AS Percentage
FROM employees e
GROUP BY e.job_title
ORDER BY EmployeeCount DESC;""",
        "sql_sqlite": """SELECT 
    COALESCE(e.job_title, 'Unknown') AS JobTitle,
    COUNT(DISTINCT e.id) AS EmployeeCount,
    ROUND(COUNT(DISTINCT e.id) * 100.0 / (SELECT COUNT(*) FROM employees), 2) AS Percentage
FROM employees e
GROUP BY e.job_title
ORDER BY EmployeeCount DESC;"""
    },
    {
        "id": "northwind_amount_due_trend_by_lastname",
        "domain": "northwind",
        "category": "monthly_trend",
        "tags": [
            "xu hướng", "amount due", "amount_due", "last name", "lastname", "thay đổi", "theo thời gian", "từng tháng", "hóa đơn", "công nợ"
        ],
        "question": "Xu hướng tổng amount due theo từng last name thay đổi như thế nào?",
        "question_en": "How does the trend of total amount due change across each last name over time?",
        "intent_explanation": "Trong Northwind, tính amount_due từ bảng orders và order_details (od.quantity * od.unit_price * (1 - od.discount)), last_name nằm ở bảng customers (c.last_name) hoặc employees (e.last_name). Liên kết orders o JOIN order_details od ON o.id = od.order_id LEFT JOIN customers c ON o.customer_id = c.id, trích xuất tháng từ order_date, gom nhóm theo Month và LastName.",
        "sql_mysql": """SELECT 
    DATE_FORMAT(o.order_date, '%Y-%m') AS Month,
    COALESCE(c.last_name, e.last_name, 'Unknown') AS LastName,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue
FROM orders o
JOIN order_details od ON o.id = od.order_id
LEFT JOIN customers c ON o.customer_id = c.id
LEFT JOIN employees e ON o.employee_id = e.id
WHERE o.order_date IS NOT NULL
GROUP BY Month, LastName
ORDER BY Month ASC, TotalAmountDue DESC;""",
        "sql_sqlite": """SELECT 
    substr(o.order_date, 1, 7) AS Month,
    COALESCE(c.last_name, e.last_name, 'Unknown') AS LastName,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue
FROM orders o
JOIN order_details od ON o.id = od.order_id
LEFT JOIN customers c ON o.customer_id = c.id
LEFT JOIN employees e ON o.employee_id = e.id
WHERE o.order_date IS NOT NULL
GROUP BY Month, LastName
ORDER BY Month ASC, TotalAmountDue DESC;"""
    },
    {
        "id": "northwind_avg_amount_due_by_city_comparison",
        "domain": "northwind",
        "category": "comparison",
        "tags": [
            "so sánh", "amount due", "amount_due", "trung bình", "thành phố", "city", "giữa các thành phố",
            "doanh thu", "bình quân", "compare", "average"
        ],
        "question": "So sánh amount due trung bình giữa các thành phố",
        "question_en": "Compare average amount due across cities",
        "intent_explanation": "Trong CSDL Northwind, tính amount_due từ bảng orders JOIN order_details (od.quantity * od.unit_price * (1 - od.discount)), thành phố lấy từ COALESCE(o.ship_city, c.city, 'Unknown'). Nhóm theo City và tính TotalOrders, TotalAmountDue, AvgAmountDuePerOrder.",
        "sql_mysql": """SELECT 
    COALESCE(o.ship_city, c.city, 'Unknown') AS City,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) / NULLIF(COUNT(DISTINCT o.id), 0), 2) AS AvgAmountDuePerOrder,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDuePerItem
FROM orders o
JOIN order_details od ON o.id = od.order_id
LEFT JOIN customers c ON o.customer_id = c.id
WHERE o.ship_city IS NOT NULL OR c.city IS NOT NULL
GROUP BY City
ORDER BY AvgAmountDuePerOrder DESC;""",
        "sql_sqlite": """SELECT 
    COALESCE(o.ship_city, c.city, 'Unknown') AS City,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) / NULLIF(COUNT(DISTINCT o.id), 0), 2) AS AvgAmountDuePerOrder,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDuePerItem
FROM orders o
JOIN order_details od ON o.id = od.order_id
LEFT JOIN customers c ON o.customer_id = c.id
WHERE o.ship_city IS NOT NULL OR c.city IS NOT NULL
GROUP BY City
ORDER BY AvgAmountDuePerOrder DESC;"""
    },
    {
        "id": "northwind_monthly_amount_due_peak_valley",
        "domain": "northwind",
        "category": "extremes",
        "tags": [
            "khoảng thời gian", "thời gian", "tháng nào", "thời điểm", "cao nhất và thấp nhất", "đỉnh và đáy",
            "peak and valley", "amount due", "amount_due", "doanh thu", "ghi nhận"
        ],
        "question": "Khoảng thời gian nào ghi nhận amount due cao nhất và thấp nhất?",
        "question_en": "Which time period recorded the highest and lowest amount due?",
        "intent_explanation": "Trong CSDL Northwind, tổng hợp amount_due theo từng tháng từ orders JOIN order_details, sau đó dùng CTE Extremes để tìm tháng có doanh thu cao nhất (Peak) và thấp nhất (Valley).",
        "sql_mysql": """WITH MonthlyAmountDue AS (
    SELECT 
        DATE_FORMAT(o.order_date, '%Y-%m') AS Month,
        COUNT(DISTINCT o.id) AS TotalOrders,
        ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    WHERE o.order_date IS NOT NULL
    GROUP BY DATE_FORMAT(o.order_date, '%Y-%m')
),
Extremes AS (
    SELECT 
        MAX(TotalAmountDue) AS MaxAmountDue,
        MIN(TotalAmountDue) AS MinAmountDue
    FROM MonthlyAmountDue
)
SELECT 
    m.Month,
    m.TotalOrders,
    m.TotalAmountDue,
    CASE 
        WHEN m.TotalAmountDue = e.MaxAmountDue THEN 'Cao nhất (Peak)'
        WHEN m.TotalAmountDue = e.MinAmountDue THEN 'Thấp nhất (Valley)'
    END AS PeriodStatus
FROM MonthlyAmountDue m
CROSS JOIN Extremes e
WHERE m.TotalAmountDue = e.MaxAmountDue OR m.TotalAmountDue = e.MinAmountDue
ORDER BY m.TotalAmountDue DESC;""",
        "sql_sqlite": """WITH MonthlyAmountDue AS (
    SELECT 
        substr(o.order_date, 1, 7) AS Month,
        COUNT(DISTINCT o.id) AS TotalOrders,
        ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    WHERE o.order_date IS NOT NULL
    GROUP BY substr(o.order_date, 1, 7)
),
Extremes AS (
    SELECT 
        MAX(TotalAmountDue) AS MaxAmountDue,
        MIN(TotalAmountDue) AS MinAmountDue
    FROM MonthlyAmountDue
)
SELECT 
    m.Month,
    m.TotalOrders,
    m.TotalAmountDue,
    CASE 
        WHEN m.TotalAmountDue = e.MaxAmountDue THEN 'Cao nhất (Peak)'
        WHEN m.TotalAmountDue = e.MinAmountDue THEN 'Thấp nhất (Valley)'
    END AS PeriodStatus
FROM MonthlyAmountDue m
CROSS JOIN Extremes e
WHERE m.TotalAmountDue = e.MaxAmountDue OR m.TotalAmountDue = e.MinAmountDue
ORDER BY m.TotalAmountDue DESC;"""
    }
]




