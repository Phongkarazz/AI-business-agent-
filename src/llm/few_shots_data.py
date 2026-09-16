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
        "tags": ["team", "đội ngũ", "so sánh", "doanh số", "số lượng hộp", "avg price", "hộp bán ra", "team kinh doanh"],
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
    }
]

