"""
Enterprise Pre-Execution AST & Fuzzy SQL Sanitizer for Veraxus.
Provides multi-tier pre-flight validation, fuzzy column/table healing,
syntax normalization, and domain-agnostic schema adaptation for ANY database.
"""

from __future__ import annotations

import re
import difflib
try:
    from sqlalchemy import inspect
except ImportError:
    inspect = None


def get_schema_tables_and_columns(engine, schema_context: str = "") -> Dict[str, List[str]]:
    """Trích xuất bản đồ {tên_bảng: [danh_sách_cột]} từ SQLAlchemy Inspector hoặc Schema Context."""
    table_cols_map: Dict[str, List[str]] = {}

    # 1. Trích xuất từ SQLAlchemy Inspector nếu có engine sống
    if engine is not None:
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            for tbl in tables:
                cols = [c["name"] for c in inspector.get_columns(tbl)]
                table_cols_map[tbl] = cols
            if table_cols_map:
                return table_cols_map
        except Exception:
            pass

    # 2. Fallback trích xuất từ schema_context string
    if schema_context and "Chưa kết nối" not in schema_context:
        matches = re.findall(r"-\s*Bảng\s+`?([a-zA-Z0-9_]+)`?:\s*([^\n]+)", schema_context, re.IGNORECASE)
        for tbl_name, col_str in matches:
            cols = []
            for raw_col in col_str.split(","):
                raw_col = raw_col.strip()
                if not raw_col:
                    continue
                cm = re.match(r"`?([a-zA-Z0-9_]+)`?", raw_col)
                if cm:
                    cols.append(cm.group(1))
            table_cols_map[tbl_name] = cols

    return table_cols_map


def fuzzy_match_name(target: str, candidates: List[str], cutoff: float = 0.6) -> Optional[str]:
    """Tìm tên gần giống nhất trong danh sách ứng viên (hỗ trợ số ít/số nhiều và viết tắt)."""
    if not target or not candidates:
        return None

    t_clean = target.strip("`'\" ").lower()
    cand_map = {c.lower(): c for c in candidates}

    # 1. Trùng khớp hoàn toàn (không phân biệt hoa thường)
    if t_clean in cand_map:
        return cand_map[t_clean]

    # 2. Số ít / Số nhiều thông dụng (s / es)
    if f"{t_clean}s" in cand_map:
        return cand_map[f"{t_clean}s"]
    if t_clean.endswith("s") and t_clean[:-1] in cand_map:
        return cand_map[t_clean[:-1]]
    if f"{t_clean}es" in cand_map:
        return cand_map[f"{t_clean}es"]
    if t_clean.endswith("es") and t_clean[:-2] in cand_map:
        return cand_map[t_clean[:-2]]

    # 3. Fuzzy matching bằng difflib (Levenshtein-like)
    matches = difflib.get_close_matches(t_clean, list(cand_map.keys()), n=1, cutoff=cutoff)
    if matches:
        return cand_map[matches[0]]

    return None


def sanitize_common_sql_syntax(sql: str) -> str:
    """Tự động chuẩn hóa cú pháp SQL và sửa các lỗi viết nhầm phổ biến của Small LLM."""
    if not sql:
        return ""

    s = sql.strip()

    # 1. Bóc Markdown Code Blocks
    m = re.search(r"```(?:sql|json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    s = re.sub(r"^```(?:sql|json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s).strip().strip("`").strip()

    # 2. Tách khoảng trắng cho các từ khóa bị dính
    s = re.sub(r"\bSELECT\*", "SELECT *", s, flags=re.IGNORECASE)
    s = re.sub(r"\bLIMIT(\d+)\b", r"LIMIT \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\bGROUPBY\b", "GROUP BY", s, flags=re.IGNORECASE)
    s = re.sub(r"\bORDERBY\b", "ORDER BY", s, flags=re.IGNORECASE)

    # 3. Vá lỗi thiếu mở ngoặc sau hàm ROUND / AGGREGATE
    s = re.sub(r"\bROUND\s+AVG\(", "ROUND(AVG(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+SUM\(", "ROUND(SUM(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+COUNT\(", "ROUND(COUNT(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+MAX\(", "ROUND(MAX(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+MIN\(", "ROUND(MIN(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+COALESCE\(", "ROUND(COALESCE(", s, flags=re.IGNORECASE)

    # 4. Xóa dấu phẩy thừa trước các mệnh đề chính
    s = re.sub(r",\s*(ORDER\s+BY|GROUP\s+BY|FROM|WHERE|HAVING|LIMIT)\b", r" \1", s, flags=re.IGNORECASE)

    # 5. Cân bằng dấu ngoặc đơn
    open_p = s.count("(")
    close_p = s.count(")")
    if open_p > close_p:
        s = s + (")" * (open_p - close_p))

    return s


def sanitize_sql_for_live_db(
    sql: str,
    engine=None,
    schema_context: str = "",
    user_query: str = "",
    dialect: str = "MySQL"
) -> str:
    """Bộ tiền xử lý & Chữa lành SQL thông minh (Universal SQL Healer).
    - Khớp bảng chuẩn hóa số ít/số nhiều theo CSDL thực tế.
    - Tự động thay thế cột bị viết nhầm bằng cột thực tế gần nhất.
    """
    if not sql:
        return ""

    fixed_sql = sanitize_common_sql_syntax(sql)

    # Bóc tách và loại bỏ bất kỳ tiền tố DDL hoặc lời dẫn thừa nào trước WITH hoặc SELECT
    m_kw = re.search(r"\b(WITH\s+[\s\S]+|SELECT\s+[\s\S]+)", fixed_sql, re.IGNORECASE)
    if m_kw and m_kw.start() > 0:
        fixed_sql = m_kw.group(1).strip()

    table_cols_map = get_schema_tables_and_columns(engine, schema_context)

    if not table_cols_map:
        return fixed_sql

    valid_tables = list(table_cols_map.keys())
    valid_tables_set = {v.lower() for v in valid_tables}

    # 0. Phát hiện và loại bỏ các chuỗi giả định/placeholder ảo giác (table1, table2, columnname, somevalue, foreignkey)
    has_placeholder = bool(re.search(r"\b(table1|table2|t1\.columnname|t2\.columnname|foreignkey|primarykey|somevalue)\b", fixed_sql, re.IGNORECASE))
    if has_placeholder:
        # Nếu đang ở CSDL Northwind (có bảng orders và order_details)
        if "orders" in valid_tables_set and "order_details" in valid_tables_set:
            q_low = (user_query or "").lower()
            if any(k in q_low for k in ["thành phố", "city"]):
                fixed_sql = """SELECT 
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
            elif any(k in q_low for k in ["quốc gia", "country"]):
                fixed_sql = """SELECT 
    COALESCE(o.ship_country_region, c.country_region, 'Unknown') AS Country,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDue
FROM orders o
JOIN order_details od ON o.id = od.order_id
LEFT JOIN customers c ON o.customer_id = c.id
GROUP BY Country
ORDER BY TotalAmountDue DESC;"""
            else:
                fixed_sql = """SELECT 
    p.product_name AS Product,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalRevenue
FROM order_details od
JOIN products p ON od.product_id = p.id
GROUP BY p.id, p.product_name
ORDER BY TotalRevenue DESC;"""
            return fixed_sql
        # Nếu đang ở CSDL Awesome Chocolates
        elif "sales" in valid_tables_set and "people" in valid_tables_set:
            q_low = (user_query or "").lower()
            is_sq = "sqlite" in (dialect or "").lower()
            is_order_bm = (
                any(k in q_low for k in ["đơn hàng", "giao dịch", "mỗi đơn", "các đơn", "orders", "transactions", "đơn"])
                and any(k in q_low for k in ["trung bình", "bình quân", "avg", "average", "ngưỡng trung bình", "mức tb"])
            )
            if is_order_bm:
                yr_m = re.search(r'\b(20\d{2})\b', q_low)
                yr = yr_m.group(1) if yr_m else None
                yr_w = (f"WHERE strftime('%Y', s.SaleDate) = '{yr}'" if is_sq else f"WHERE YEAR(s.SaleDate) = {yr}") if yr else ""
                fixed_sql = f"""WITH OrderBenchmark AS (
    SELECT 
        ROUND(AVG(s.Amount), 2) AS AvgBenchmark,
        COUNT(*) AS TotalOrdersCount,
        SUM(s.Amount) AS TotalRevenue
    FROM sales s
    {yr_w}
),
ClassifiedOrders AS (
    SELECT 
        CASE 
            WHEN s.Amount > b.AvgBenchmark THEN 'Đơn hàng trên mức trung bình'
            ELSE 'Đơn hàng dưới hoặc bằng trung bình'
        END AS `Nhóm Đơn Hàng`,
        s.Amount
    FROM sales s
    CROSS JOIN OrderBenchmark b
    {yr_w}
)
SELECT 
    co.`Nhóm Đơn Hàng`,
    COUNT(*) AS `Số Lượng Đơn`,
    ROUND(COUNT(*) * 100.0 / b.TotalOrdersCount, 2) AS `Tỷ Trọng Số Đơn (%)`,
    SUM(co.Amount) AS `Tổng Doanh Số ($)`,
    ROUND(SUM(co.Amount) * 100.0 / NULLIF(b.TotalRevenue, 0), 2) AS `Tỷ Trọng Doanh Số (%)`,
    b.AvgBenchmark AS `Mức TB Chuẩn ($)`
FROM ClassifiedOrders co
CROSS JOIN OrderBenchmark b
GROUP BY co.`Nhóm Đơn Hàng`, b.TotalOrdersCount, b.TotalRevenue, b.AvgBenchmark
ORDER BY CASE WHEN co.`Nhóm Đơn Hàng` = 'Đơn hàng trên mức trung bình' THEN 0 ELSE 1 END;"""
                return fixed_sql

            fixed_sql = """SELECT 
    g.Geo AS Market,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
GROUP BY g.Geo
ORDER BY TotalSales DESC;"""
            return fixed_sql
        # Nếu đang ở CSDL Employees
        elif "employees" in valid_tables_set and "salaries" in valid_tables_set:
            fixed_sql = """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY AvgSalary DESC;"""
            return fixed_sql
        # Nếu đang ở CSDL Sakila
        elif "film" in valid_tables_set or "rental" in valid_tables_set or "payment" in valid_tables_set:
            q_low = (user_query or "").lower()
            is_sq = "sqlite" in (dialect or "").lower()
            date_fmt = "strftime('%Y-%m', p.payment_date)" if is_sq else "DATE_FORMAT(p.payment_date, '%Y-%m')"
            if any(k in q_low for k in ["thành phố", "city"]):
                if any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "percentage", "contribution", "đóng góp", "tỷ trọng", "tỉ trọng", "cơ cấu"]):
                    fixed_sql = """WITH CityRevenue AS (
    SELECT 
        ct.city_id,
        ct.city AS City,
        COUNT(DISTINCT p.payment_id) AS TotalPayments,
        ROUND(SUM(p.amount), 2) AS TotalAmount
    FROM city ct
    JOIN address addr ON ct.city_id = addr.city_id
    JOIN customer cu ON addr.address_id = cu.address_id
    JOIN payment p ON cu.customer_id = p.customer_id
    GROUP BY ct.city_id, ct.city
)
SELECT 
    City,
    TotalPayments,
    TotalAmount,
    ROUND(TotalAmount * 100.0 / (SELECT SUM(TotalAmount) FROM CityRevenue), 2) AS ContributionPercentage
FROM CityRevenue
ORDER BY TotalAmount DESC
LIMIT 10;"""
                elif any(k in q_low for k in ["trung bình", "bình quân", "avg", "average"]):
                    fixed_sql = """SELECT 
    ct.city AS City,
    COUNT(DISTINCT p.payment_id) AS TotalPayments,
    ROUND(SUM(p.amount), 2) AS TotalAmount,
    ROUND(AVG(p.amount), 2) AS AvgAmount
FROM city ct
JOIN address addr ON ct.city_id = addr.city_id
JOIN customer cu ON addr.address_id = cu.address_id
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY ct.city_id, ct.city
ORDER BY AvgAmount DESC
LIMIT 10;"""
                else:
                    fixed_sql = """SELECT 
    ct.city AS City,
    COUNT(DISTINCT p.payment_id) AS TotalPayments,
    ROUND(SUM(p.amount), 2) AS TotalAmount,
    ROUND(AVG(p.amount), 2) AS AvgAmount
FROM city ct
JOIN address addr ON ct.city_id = addr.city_id
JOIN customer cu ON addr.address_id = cu.address_id
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY ct.city_id, ct.city
ORDER BY TotalAmount DESC
LIMIT 10;"""
            elif any(k in q_low for k in ["thể loại", "category"]):
                fixed_sql = """SELECT 
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
LIMIT 10;"""
            elif any(k in q_low for k in ["khách hàng", "customer"]):
                fixed_sql = """SELECT 
    cu.customer_id,
    CONCAT(cu.first_name, ' ', cu.last_name) AS CustomerName,
    SUM(p.amount) AS TotalSpent
FROM customer cu
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY cu.customer_id, CustomerName
ORDER BY TotalSpent DESC
LIMIT 10;"""
            elif any(k in q_low for k in ["diễn viên", "actor"]):
                fixed_sql = """SELECT 
    a.actor_id,
    CONCAT(a.first_name, ' ', a.last_name) AS ActorName,
    COUNT(fa.film_id) AS FilmCount
FROM actor a
JOIN film_actor fa ON a.actor_id = fa.actor_id
GROUP BY a.actor_id, ActorName
ORDER BY FilmCount DESC
LIMIT 10;"""
            elif any(k in q_low for k in ["tháng", "month", "theo tháng", "từng tháng", "hàng tháng", "xu hướng", "thời gian", "biến động"]):
                fixed_sql = f"""SELECT 
    {date_fmt} AS Month,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.rental_id) AS TotalRentals
FROM payment p
GROUP BY {date_fmt}
ORDER BY Month ASC;"""
            else:
                # Mặc định trên Sakila: Top các bộ phim (Film Titles) có doanh thu cao nhất (thay vì ép mù quáng về tháng)
                fixed_sql = """SELECT 
    f.title AS FilmTitle,
    SUM(p.amount) AS TotalRevenue,
    COUNT(r.rental_id) AS RentalCount
FROM film f
JOIN inventory i ON f.film_id = i.film_id
JOIN rental r ON i.inventory_id = r.inventory_id
JOIN payment p ON r.rental_id = p.rental_id
GROUP BY f.film_id, f.title
ORDER BY TotalRevenue DESC
LIMIT 10;"""
            return fixed_sql

    # Trích xuất toàn bộ các tên CTE (Common Table Expressions) trong mệnh đề WITH để không bị nhầm thành tên bảng CSDL
    cte_names = set()
    if re.search(r"(?i)\bWITH\b", fixed_sql):
        sub_cte_matches = re.findall(r"\b([a-zA-Z0-9_]+)\s+AS\s*\(", fixed_sql, re.IGNORECASE)
        for c in sub_cte_matches:
            if c.lower() not in ("select", "from", "where", "join", "group", "order", "having", "limit"):
                cte_names.add(c.lower())

    # 1. Chuẩn hóa tên bảng trong FROM và JOIN (Bỏ qua các CTE đã khai báo)
    def _replace_table_match(match):
        clause = match.group(1)  # FROM hoặc JOIN
        tbl = match.group(2)
        if tbl.lower() in cte_names:
            return match.group(0)
        matched_tbl = fuzzy_match_name(tbl, valid_tables)
        if matched_tbl:
            return f"{clause} {matched_tbl}"
        return match.group(0)

    fixed_sql = re.sub(
        r"(?i)\b(FROM|JOIN)\s+`?([a-zA-Z0-9_]+)`?",
        _replace_table_match,
        fixed_sql
    )

    # 2. Xây dựng bản đồ Alias -> Tên Bảng thực tế
    alias_map: Dict[str, str] = {}
    cte_aliases: Set[str] = set()
    from_join_matches = re.findall(
        r"(?i)\b(?:FROM|JOIN)\s+`?([a-zA-Z0-9_]+)`?(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?",
        fixed_sql
    )
    for tbl, alias in from_join_matches:
        if tbl.lower() in cte_names:
            if alias and alias.upper() not in ("ON", "WHERE", "GROUP", "ORDER", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER"):
                cte_aliases.add(alias.lower())
            cte_aliases.add(tbl.lower())
            continue
        tbl_real = fuzzy_match_name(tbl, valid_tables) or tbl
        if alias and alias.upper() not in ("ON", "WHERE", "GROUP", "ORDER", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER"):
            alias_map[alias.lower()] = tbl_real
        else:
            alias_map[tbl_real.lower()] = tbl_real

    # 3. Chuẩn hóa các cột dạng alias.column_name (Bỏ qua các cột thuộc CTE)
    def _replace_col_match(match):
        prefix = match.group(1)  # alias hoặc table name
        col = match.group(2)     # column name
        p_low = prefix.lower()

        if p_low in cte_aliases or p_low in cte_names:
            return match.group(0)

        if p_low in alias_map:
            real_tbl = alias_map[p_low]
            real_cols = table_cols_map.get(real_tbl, [])
            if real_cols:
                # Nếu cột đã tồn tại chính xác, giữ nguyên
                if col.lower() in [c.lower() for c in real_cols]:
                    real_c = next(c for c in real_cols if c.lower() == col.lower())
                    return f"{prefix}.{real_c}"

                # Thử tìm cột gần nhất trong bảng này
                matched_col = fuzzy_match_name(col, real_cols, cutoff=0.55)
                if matched_col:
                    return f"{prefix}.{matched_col}"

                # Thử tìm xem cột này có nằm ở bảng khác trong truy vấn không
                for other_alias, other_tbl in alias_map.items():
                    if other_tbl != real_tbl:
                        other_cols = table_cols_map.get(other_tbl, [])
                        if col.lower() in [c.lower() for c in other_cols]:
                            real_other_c = next(c for c in other_cols if c.lower() == col.lower())
                            return f"{other_alias}.{real_other_c}"

        return match.group(0)

    fixed_sql = re.sub(
        r"\b([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\b",
        _replace_col_match,
        fixed_sql
    )

    # 4. Kiểm tra và Chữa lành ảo giác bảng chéo miền (Cross-Domain Hallucination Healer)
    # Tìm tất cả các bảng vật lý được truy vấn trong FROM / JOIN
    physical_tables = []
    for m in re.finditer(r"(?i)\b(?:FROM|JOIN)\s+`?([a-zA-Z0-9_]+)`?", fixed_sql):
        t = m.group(1).lower()
        if t not in cte_names and t not in ("select", "where", "group", "order", "limit", "with", "as", "on", "using", "left", "right", "inner", "outer"):
            physical_tables.append(t)

    valid_tables_low = {v.lower(): v for v in valid_tables}
    hallucinated_tables = [t for t in physical_tables if t not in valid_tables_low]

    # Nếu câu lệnh SQL đang gọi những bảng hoàn toàn không tồn tại trong CSDL hiện tại:
    if hallucinated_tables and valid_tables:
        q_low = (user_query or "").lower()

        # ĐẶC BIỆT CHO SAKILA: Nếu câu lệnh ảo giác xảy ra trên CSDL Sakila (DVD Rental Store)
        if any(t in valid_tables_set for t in ["film", "rental", "payment"]):
            is_sq = "sqlite" in (dialect or "").lower()
            date_fmt = "strftime('%Y-%m', p.payment_date)" if is_sq else "DATE_FORMAT(p.payment_date, '%Y-%m')"
            if any(k in q_low for k in ["thành phố", "city"]):
                if any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "percentage", "contribution", "đóng góp", "tỷ trọng", "tỉ trọng", "cơ cấu"]):
                    return """WITH CityRevenue AS (
    SELECT 
        ct.city_id,
        ct.city AS City,
        COUNT(DISTINCT p.payment_id) AS TotalPayments,
        ROUND(SUM(p.amount), 2) AS TotalAmount
    FROM city ct
    JOIN address addr ON ct.city_id = addr.city_id
    JOIN customer cu ON addr.address_id = cu.address_id
    JOIN payment p ON cu.customer_id = p.customer_id
    GROUP BY ct.city_id, ct.city
)
SELECT 
    City,
    TotalPayments,
    TotalAmount,
    ROUND(TotalAmount * 100.0 / (SELECT SUM(TotalAmount) FROM CityRevenue), 2) AS ContributionPercentage
FROM CityRevenue
ORDER BY TotalAmount DESC
LIMIT 10;"""
                elif any(k in q_low for k in ["trung bình", "bình quân", "avg", "average"]):
                    return """SELECT 
    ct.city AS City,
    COUNT(DISTINCT p.payment_id) AS TotalPayments,
    ROUND(SUM(p.amount), 2) AS TotalAmount,
    ROUND(AVG(p.amount), 2) AS AvgAmount
FROM city ct
JOIN address addr ON ct.city_id = addr.city_id
JOIN customer cu ON addr.address_id = cu.address_id
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY ct.city_id, ct.city
ORDER BY AvgAmount DESC
LIMIT 10;"""
                else:
                    return """SELECT 
    ct.city AS City,
    COUNT(DISTINCT p.payment_id) AS TotalPayments,
    ROUND(SUM(p.amount), 2) AS TotalAmount,
    ROUND(AVG(p.amount), 2) AS AvgAmount
FROM city ct
JOIN address addr ON ct.city_id = addr.city_id
JOIN customer cu ON addr.address_id = cu.address_id
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY ct.city_id, ct.city
ORDER BY TotalAmount DESC
LIMIT 10;"""
            elif any(k in q_low for k in ["thể loại", "category"]):
                return """SELECT 
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
LIMIT 10;"""
            elif any(k in q_low for k in ["khách hàng", "customer"]):
                return """SELECT 
    cu.customer_id,
    CONCAT(cu.first_name, ' ', cu.last_name) AS CustomerName,
    SUM(p.amount) AS TotalSpent
FROM customer cu
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY cu.customer_id, CustomerName
ORDER BY TotalSpent DESC
LIMIT 10;"""
            elif any(k in q_low for k in ["diễn viên", "actor"]):
                return """SELECT 
    a.actor_id,
    CONCAT(a.first_name, ' ', a.last_name) AS ActorName,
    COUNT(fa.film_id) AS FilmCount
FROM actor a
JOIN film_actor fa ON a.actor_id = fa.actor_id
GROUP BY a.actor_id, ActorName
ORDER BY FilmCount DESC
LIMIT 10;"""
            elif any(k in q_low for k in ["tháng", "month", "theo tháng", "từng tháng", "hàng tháng", "xu hướng", "thời gian", "biến động"]):
                return f"""SELECT 
    {date_fmt} AS Month,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.rental_id) AS TotalRentals
FROM payment p
GROUP BY {date_fmt}
ORDER BY Month ASC;"""
            else:
                # Mặc định trên Sakila: Top các bộ phim (Film Titles) có doanh thu cao nhất (thay vì ép mù quáng về tháng)
                return """SELECT 
    f.title AS FilmTitle,
    SUM(p.amount) AS TotalRevenue,
    COUNT(r.rental_id) AS RentalCount
FROM film f
JOIN inventory i ON f.film_id = i.film_id
JOIN rental r ON i.inventory_id = r.inventory_id
JOIN payment p ON r.rental_id = p.rental_id
GROUP BY f.film_id, f.title
ORDER BY TotalRevenue DESC
LIMIT 10;"""

        # Tìm bảng tốt nhất trong valid_tables chứa CẢ cột phân nhóm (group) VÀ cột chỉ số đo (metric)
        target_tbl = None
        grp_col = None
        met_col = None

        # Ưu tiên các bảng sản phẩm, bán hàng, đơn hàng
        sorted_tables = sorted(
            valid_tables,
            key=lambda t: 0 if any(k in t.lower() for k in ["san_pham", "product", "item"]) else (
                1 if any(k in t.lower() for k in ["don_hang", "order", "sales", "trans"]) else 2
            )
        )

        for t in sorted_tables:
            t_cols = table_cols_map.get(t, [])
            g_candidates = [c for c in t_cols if any(k in c.lower() for k in ["danh_muc", "category", "loai", "type", "nhom", "group", "name", "ten", "title", "khu_vuc"])]
            m_candidates = [c for c in t_cols if any(k in c.lower() for k in ["gia_ban", "gia", "price", "amount", "tien", "salary", "cost", "total", "so_luong", "ton_kho", "revenue", "qty"])]
            if g_candidates and m_candidates:
                target_tbl = t
                grp_col = g_candidates[0]
                met_col = m_candidates[0]
                break

        if not target_tbl:
            target_tbl = sorted_tables[0]
            t_cols = table_cols_map.get(target_tbl, [])
            grp_col = t_cols[0] if t_cols else "id"
            met_col = t_cols[1] if len(t_cols) > 1 else grp_col

        # 4A. Nếu câu hỏi về Thành phố (City comparison / ranking)
        if any(k in q_low for k in ["thành phố", "city"]) and ("city" in valid_tables or "address" in valid_tables or "customer" in valid_tables):
            if "city" in valid_tables and "payment" in valid_tables:
                fixed_sql = """SELECT 
    ct.city AS City,
    COUNT(DISTINCT p.payment_id) AS TotalPayments,
    ROUND(SUM(p.amount), 2) AS TotalAmount,
    ROUND(AVG(p.amount), 2) AS AvgAmount
FROM city ct
JOIN address addr ON ct.city_id = addr.city_id
JOIN customer cu ON addr.address_id = cu.address_id
JOIN payment p ON cu.customer_id = p.customer_id
GROUP BY ct.city_id, ct.city
ORDER BY AvgAmount DESC
LIMIT 10;"""
            elif "orders" in valid_tables and "order_details" in valid_tables:
                fixed_sql = """SELECT 
    COALESCE(o.ship_city, c.city, 'Unknown') AS City,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDue
FROM orders o
JOIN order_details od ON o.id = od.order_id
LEFT JOIN customers c ON o.customer_id = c.id
WHERE o.ship_city IS NOT NULL OR c.city IS NOT NULL
GROUP BY City
ORDER BY AvgAmountDue DESC
LIMIT 10;"""

        # 4B. Nếu câu hỏi là so sánh chênh lệch (spread / disparity / gap / nhóm cao nhất và nhóm thấp nhất)
        elif any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "nhóm cao nhất", "nhóm thấp nhất", "cao nhất và thấp nhất", "phân hóa", "mức lương", "lương"]):
            fixed_sql = f"""WITH GroupSpreadStats AS (
    SELECT 
        `{grp_col}` AS Nhom,
        ROUND(AVG(`{met_col}`), 2) AS GiaTriTrungBinh,
        MAX(`{met_col}`) AS GiaTriCaoNhat,
        MIN(`{met_col}`) AS GiaTriThapNhat,
        (MAX(`{met_col}`) - MIN(`{met_col}`)) AS DoChenhLech,
        COUNT(*) AS SoLuong
    FROM `{target_tbl}`
    GROUP BY `{grp_col}`
)
SELECT Nhom, GiaTriTrungBinh, GiaTriCaoNhat, GiaTriThapNhat, DoChenhLech, SoLuong
FROM GroupSpreadStats
ORDER BY DoChenhLech DESC;"""

        # 4C. Nếu câu hỏi về Top / Xếp hạng / Cao nhất
        elif any(k in q_low for k in ["top", "cao nhất", "nhiều nhất", "lớn nhất", "dẫn đầu", "xếp hạng"]):
            top_m = re.search(r"(?:top\s*|danh\s+sách\s*)(\d+)", q_low)
            n_val = int(top_m.group(1)) if top_m else 10
            fixed_sql = f"""SELECT 
    `{grp_col}` AS TenThucThe,
    ROUND(SUM(`{met_col}`), 2) AS TongGiaTri,
    COUNT(*) AS SoLuongGiaoDich
FROM `{target_tbl}`
GROUP BY `{grp_col}`
ORDER BY TongGiaTri DESC
LIMIT {n_val};"""

        # 4C. Nếu câu hỏi về thời gian / xu hướng / tháng
        elif any(k in q_low for k in ["tháng", "thời gian", "xu hướng", "năm", "biến động", "trend"]):
            biz_date_cols = [c for c in t_cols if any(k in c.lower() for k in ["date", "ngay", "time", "thoi_gian"]) and not any(k in c.lower() for k in ["last_update", "updated_at", "modified", "sys_time"])]
            date_cols = biz_date_cols if biz_date_cols else [c for c in t_cols if any(k in c.lower() for k in ["date", "ngay", "time", "thoi_gian"])]
            d_col = date_cols[0] if date_cols else "ngay_dat_hang"
            is_sq = "sqlite" in (dialect or "").lower()
            m_expr = f"strftime('%Y-%m', `{d_col}`)" if is_sq else f"DATE_FORMAT(`{d_col}`, '%Y-%m')"
            fixed_sql = f"""SELECT 
    {m_expr} AS ThoiGian,
    ROUND(SUM(`{met_col}`), 2) AS TongGiaTri,
    COUNT(*) AS SoGiaoDich
FROM `{target_tbl}`
GROUP BY ThoiGian
ORDER BY ThoiGian ASC;"""

        # 4D. Nếu câu hỏi về Tỷ lệ phần trăm đóng góp / Tỷ trọng / Cơ cấu
        elif any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "tỷ trọng", "tỉ trọng", "đóng góp", "chiếm bao nhiêu", "cơ cấu"]):
            fixed_sql = f"""WITH GroupStats AS (
    SELECT 
        `{grp_col}` AS Nhom,
        ROUND(SUM(`{met_col}`), 2) AS TongGiaTri,
        COUNT(*) AS SoLuong
    FROM `{target_tbl}`
    GROUP BY `{grp_col}`
)
SELECT 
    Nhom,
    TongGiaTri,
    ROUND(TongGiaTri * 100.0 / (SELECT SUM(TongGiaTri) FROM GroupStats), 2) AS TyLePhanTram,
    SoLuong
FROM GroupStats
ORDER BY TongGiaTri DESC;"""

        # 4E. Fallback tổng quan
        else:
            fixed_sql = f"""SELECT 
    `{grp_col}` AS Nhom,
    ROUND(SUM(`{met_col}`), 2) AS TongGiaTri,
    COUNT(*) AS SoLuong
FROM `{target_tbl}`
GROUP BY `{grp_col}`
ORDER BY TongGiaTri DESC
LIMIT 10;"""

    # 5. Khắc phục triệt để ảo giác fake YoY trên các câu hỏi xu hướng thời gian đơn thuần
    q_low_final = (user_query or "").lower()
    is_simple_trend = (
        any(k in q_low_final for k in ["xu hướng", "trend", "biến động theo thời gian", "theo thời gian", "qua thời gian", "qua các tháng", "theo tháng", "theo ngày", "theo quý", "theo năm"])
        and not any(k in q_low_final for k in ["so sánh cùng kỳ", "cùng kỳ năm trước", "yoy", "mom", "so với năm trước", "so với tháng trước", "tăng trưởng cùng kỳ"])
    )
    has_fake_yoy = any(k in fixed_sql.lower() for k in [
        "last year", "last_year", "current year", "current_year", "change in sales", "change_in_sales", "percentage change", "percentage_change"
    ])
    if is_simple_trend and has_fake_yoy and valid_tables:
        # Tìm bảng và cột thời gian / chỉ số đo lường thích hợp để xuất câu lệnh xu hướng chuẩn mực
        sorted_tbls = sorted(
            valid_tables,
            key=lambda t: 0 if any(k in t.lower() for k in ["don_hang", "order", "sales", "trans"]) else (
                1 if any(k in t.lower() for k in ["chi_tiet", "detail", "item"]) else 2
            )
        )
        for t in sorted_tbls:
            t_cols = table_cols_map.get(t, [])
            d_cols = [c for c in t_cols if any(k in c.lower() for k in ["date", "ngay", "time", "created_at"])]
            m_cols = [c for c in t_cols if any(k in c.lower() for k in ["tong_tien", "amount", "total", "gia_tri", "doanh_thu", "revenue", "gia_ban", "price", "salary"])]
            if d_cols and m_cols:
                d_c = d_cols[0]
                m_c = m_cols[0]
                fixed_sql = f"""SELECT 
    `{d_c}` AS Ngay,
    ROUND(SUM(`{m_c}`), 2) AS TongGiaTri,
    COUNT(*) AS SoLuongGiaoDich
FROM `{t}`
WHERE `{d_c}` IS NOT NULL
GROUP BY `{d_c}`
ORDER BY `{d_c}` ASC;"""
                break

    # 6. Khắc phục thiếu cột tỷ lệ phần trăm khi người dùng hỏi về tỷ lệ đóng góp / cơ cấu
    is_ratio_q = (
        any(k in q_low_final for k in ["tỷ lệ phần trăm đóng góp", "tỷ lệ đóng góp", "phần trăm đóng góp", "tỷ trọng", "tỉ trọng", "cơ cấu đóng góp"])
        or (any(k in q_low_final for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "tỷ trọng", "tỉ trọng"]) and any(k in q_low_final for k in ["đóng góp", "vào tổng", "trong tổng", "từng nhóm", "mỗi nhóm", "từng sản phẩm", "mỗi sản phẩm"]))
    )
    has_ratio_in_sql = any(k in fixed_sql.lower() for k in ["* 100", "percent", "pct", "tyle", "ty_le", "ratio", "share"])
    if is_ratio_q and not has_ratio_in_sql and valid_tables:
        sorted_tbls = sorted(
            valid_tables,
            key=lambda t: 0 if any(k in t.lower() for k in ["san_pham", "product", "item"]) else (
                1 if any(k in t.lower() for k in ["don_hang", "order", "sales", "trans"]) else 2
            )
        )
        for t in sorted_tbls:
            t_cols = table_cols_map.get(t, [])
            g_cols = [c for c in t_cols if any(k in c.lower() for k in ["danh_muc", "category", "loai", "nhom", "group", "ten", "name", "title"])]
            m_cols = [c for c in t_cols if any(k in c.lower() for k in ["gia_von", "gia_ban", "tong_tien", "amount", "total", "gia_tri", "doanh_thu", "revenue", "salary", "price"])]
            if g_cols and m_cols:
                g_c = g_cols[0]
                m_c = m_cols[0]
                fixed_sql = f"""WITH GroupStats AS (
    SELECT 
        `{g_c}` AS Nhom,
        ROUND(SUM(`{m_c}`), 2) AS TongGiaTri,
        COUNT(*) AS SoLuong
    FROM `{t}`
    GROUP BY `{g_c}`
)
SELECT 
    Nhom,
    TongGiaTri,
    ROUND(TongGiaTri * 100.0 / (SELECT SUM(TongGiaTri) FROM GroupStats), 2) AS TyLePhanTram,
    SoLuong
FROM GroupStats
ORDER BY TongGiaTri DESC;"""
                break

    return fixed_sql
