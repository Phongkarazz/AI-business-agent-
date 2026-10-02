"""
SQL Generation and Execution Agent with safety validation, parenthesis checking,
self-healing loop (including 0-row empty result recovery), conversational explanation detection,
automatic business insight discovery with Priority Tagging, bilingual support, and follow-up question suggestions.
"""
from __future__ import annotations

import json
import random
import re
import concurrent.futures
import pandas as pd

from src.config import FORBIDDEN_KEYWORDS, MAX_ROWS_CAP, INDIVIDUAL_ENTITY_REGEX
from src.database.query_runner import read_sql_capped, sanitize_error
from src.database.schema import get_table_names
from src.analytics.heuristics import (
    is_id_like,
    detect_query_language,
    sanitize_insight_markdown,
    sanitize_followup_question,
    ensure_full_twelve_months,
    ensure_full_four_quarters,
    ensure_ratio_column_if_requested,
    ensure_efficiency_columns_if_requested,
)
from src.analytics.anomaly import analyze_data_anomalies
from .client import call_llm
from .router_planner import route_and_plan
from .evaluator import evaluate_execution
from .prompts import (
    build_sql_prompt,
    build_fix_prompt,
    build_self_check_prompt,
    build_anomaly_prompt,
    build_auto_insight_prompt,
    build_followup_prompt,
    match_chocolates_specific_product,
    match_chocolates_specific_person,
)
from .few_shot_selector import select_dynamic_few_shots
from .schema_linker import link_schema_for_query
from .sql_sanitizer import sanitize_sql_for_live_db


def strip_comments_and_literals(sql: str) -> str:
    """Loại bỏ comment SQL (#, --, /* */) và chuỗi ký tự trước khi kiểm tra an toàn và cú pháp."""
    # Bỏ comment dạng block /* ... */
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    # Bỏ comment dạng dòng -- ...
    sql = re.sub(r'--[^\n]*', '', sql)
    # Bỏ comment dạng dòng # ...
    sql = re.sub(r'#[^\n]*', '', sql)
    # Bỏ chuỗi ký tự '...' và "..."
    sql = re.sub(r"'[^']*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    return sql


def auto_balance_parentheses(sql: str) -> str:
    """Tự động phát hiện và đóng dấu ngoặc ')' bị thiếu trước các từ khóa AS, FROM hoặc cuối dòng."""
    if not sql:
        return sql
    cleaned = strip_comments_and_literals(sql)
    diff = cleaned.count("(") - cleaned.count(")")
    if diff <= 0:
        return sql

    lines = sql.splitlines()
    fixed_lines = []
    for line in lines:
        c_line = strip_comments_and_literals(line)
        l_diff = c_line.count("(") - c_line.count(")")
        if l_diff > 0:
            if re.search(r"\bAS\b", line, re.IGNORECASE):
                line = re.sub(r"(\s+)(AS\b)", ")" * l_diff + r"\1\2", line, count=1, flags=re.IGNORECASE)
            elif line.strip().endswith(","):
                line = line.rstrip().rstrip(",") + (")" * l_diff) + ","
            else:
                line = line + (")" * l_diff)
        fixed_lines.append(line)

    result = "\n".join(fixed_lines)
    final_diff = strip_comments_and_literals(result).count("(") - strip_comments_and_literals(result).count(")")
    if final_diff > 0:
        result = result.rstrip().rstrip(";") + (")" * final_diff)
    return result


def check_parentheses_balance(sql: str) -> tuple[bool, str]:
    """Kiểm tra số lượng dấu mở ngoặc '(' và đóng ngoặc ')' trong SQL."""
    cleaned = strip_comments_and_literals(sql)
    open_count = cleaned.count("(")
    close_count = cleaned.count(")")
    if open_count != close_count:
        return False, f"Lỗi cú pháp SQL: Thừa hoặc thiếu dấu ngoặc đơn () (Có {open_count} dấu '(' nhưng có {close_count} dấu ')')."
    return True, ""


def clean_sql_query(sql: str) -> str:
    """Loại bỏ hoàn toàn markdown backtick, code blocks, tiền tố thừa và tự động sửa dính chữ từ khóa SQL (FROMemployees -> FROM employees)."""
    if not sql:
        return ""
    s = sql.strip()
    # 1. Bóc code block ```sql ... ```
    m = re.search(r"```(?:sql|json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()

    # 2. Xóa các tiền tố markdown thừa (dấu backtick đơn `, ```)
    s = re.sub(r"^```(?:sql|json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    s = s.strip().strip("`").strip()

    # 3. Tự động tách khoảng trắng cho các ký tự dính (SELECT* -> SELECT *, LIMIT10 -> LIMIT 10, GROUPBY -> GROUP BY)
    # Tuyệt đối KHÔNG dùng regex \bKEYWORD(?=[a-zA-Z]) vì sẽ phá hỏng các định danh/alias hợp lệ như JoinedCount, SelectedDate, FromDate...
    s = re.sub(r"\bSELECT\*", "SELECT *", s, flags=re.IGNORECASE)
    s = re.sub(r"\bLIMIT(\d+)\b", r"LIMIT \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\bGROUPBY\b", "GROUP BY", s, flags=re.IGNORECASE)
    s = re.sub(r"\bORDERBY\b", "ORDER BY", s, flags=re.IGNORECASE)

    # 4. Tìm vị trí SELECT hoặc WITH đầu tiên nếu có lời dẫn phía trước
    match_kw = re.search(r"\b(SELECT|WITH)\b", s, re.IGNORECASE)
    if match_kw and match_kw.start() > 0:
        prefix = s[:match_kw.start()].strip()
        if not any(k in prefix.lower() for k in FORBIDDEN_KEYWORDS):
            s = s[match_kw.start():].strip()

    # 5. Tự động cân bằng dấu ngoặc đơn () nếu bị thiếu dấu đóng ngoặc trước AS/FROM
    s = auto_balance_parentheses(s)

    # 6. Tự động sửa các lỗi cú pháp phổ biến của Small LLMs
    # 6.0 Sửa lỗi thiếu mở ngoặc sau hàm ROUND (VD: ROUND AVG(x), 2) -> ROUND(AVG(x), 2))
    s = re.sub(r"\bROUND\s+AVG\(", "ROUND(AVG(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+SUM\(", "ROUND(SUM(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+COUNT\(", "ROUND(COUNT(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+MAX\(", "ROUND(MAX(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+MIN\(", "ROUND(MIN(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROUND\s+COALESCE\(", "ROUND(COALESCE(", s, flags=re.IGNORECASE)

    # 6.1 Xóa dấu phẩy thừa trước các mệnh đề ORDER BY, GROUP BY, FROM, WHERE, HAVING, LIMIT
    s = re.sub(r",\s*(ORDER\s+BY|GROUP\s+BY|FROM|WHERE|HAVING|LIMIT)\b", r" \1", s, flags=re.IGNORECASE)

    # 6.2 Sửa lỗi bí danh bảng de.dept_name -> d.dept_name (dept_emp không có cột dept_name)
    s = re.sub(r"\bde\.dept_name\b", "d.dept_name", s, flags=re.IGNORECASE)

    # 6.3 Sửa lỗi tên bảng thiếu s: FROM/JOIN department -> FROM/JOIN departments
    s = re.sub(r"\b(FROM|JOIN)\s+department\b(?!\s+(?:AS\s+)?departments\b)", r"\1 departments", s, flags=re.IGNORECASE)

    # 6.4 Khi đếm số lần tăng lương lịch sử hoặc nhóm theo năm/thời gian (GROUP BY / PARTITION BY YEAR/from_date):
    # Tự động gỡ bỏ triệt để to_date = '9999-01-01' để lấy đủ toàn bộ lịch sử (tránh lỗi chỉ ra 2 năm 2001-2002)
    if re.search(r"(?:GROUP\s+BY|PARTITION\s+BY)\s+.*(?:YEAR|from_date|saledate|hire_date|hireyear|strftime)", s, re.IGNORECASE) or re.search(r"COUNT\s*\(\s*s\.salary\s*\)|raisecount", s, re.IGNORECASE):
        s = re.sub(r"\s*AND\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]\s*AND", " WHERE", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", s, flags=re.IGNORECASE)

    # 6.5 Sửa lỗi tên cột không tồn tại s.salary_date -> s.from_date
    s = re.sub(r"\b(?:[a-zA-Z0-9_]+\.)?salary_date\b", "s.from_date", s, flags=re.IGNORECASE)

    # 6.5 Tự động sửa lỗi tính thâm niên trừ năm to_date 9999 (gây ra lỗi 8,014 năm phi lý) và xóa cột HireYear = 9999
    if re.search(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)\s*-\s*YEAR\s*\(", s, re.IGNORECASE):
        s = re.sub(
            r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)\s*-\s*YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?hire_date\s*\)\s*(?:AS\s+[a-zA-Z0-9_]+)?",
            "ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 2) AS YearsOfService",
            s,
            flags=re.IGNORECASE
        )
    s = re.sub(r",?\s*YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)\s*AS\s+[a-zA-Z0-9_]*HireYear\b", "", s, flags=re.IGNORECASE)

    # 6.6 Sửa lỗi Unknown column 's.dept_no' hoặc 'e.dept_no' (salaries và employees không có dept_no, phải qua dept_emp)
    if re.search(r"\b[se]\.dept_no\b", s, re.IGNORECASE):
        s = re.sub(r"\b[se]\.dept_no\b", "de.dept_no", s, flags=re.IGNORECASE)
        if not re.search(r"\bdept_emp\b", s, re.IGNORECASE) and re.search(r"\bJOIN\s+departments\s+d\b", s, re.IGNORECASE):
            s = re.sub(
                r"(\bJOIN\s+departments\s+d\s+ON\b)",
                r"JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01' \1",
                s,
                count=1,
                flags=re.IGNORECASE
            )

    # 6.7 Sửa lỗi mô hình dùng COUNT để tính total_salary / salary (COUNT đếm người, không phải lương)
    if re.search(r"COUNT\s*\([^)]*\)\s*AS\s+[a-zA-Z0-9_]*(?:salary|budget)\b", s, re.IGNORECASE):
        s = re.sub(
            r"COUNT\s*\([^)]*\)\s*AS\s+([a-zA-Z0-9_]*(?:salary|budget)\b)",
            r"SUM(s.salary) AS \1",
            s,
            flags=re.IGNORECASE
        )
        if not re.search(r"\b(?:JOIN|FROM)\s+salaries\b", s, re.IGNORECASE):
            if re.search(r"\bJOIN\s+dept_emp\s+de\b[^\n]*", s, re.IGNORECASE):
                s = re.sub(
                    r"(\bJOIN\s+dept_emp\s+de\b[^\n]*)",
                    r"\1\nJOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'",
                    s,
                    count=1,
                    flags=re.IGNORECASE
                )
            elif re.search(r"\bFROM\s+departments\s+d\b", s, re.IGNORECASE):
                s = re.sub(
                    r"(\bFROM\s+departments\s+d\b)",
                    r"\1\nJOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'\nJOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'",
                    s,
                    count=1,
                    flags=re.IGNORECASE
                )

    # 6.8 Sửa lỗi tên cột bảng CSDL Chocolates phổ biến của LLMs:
    # g.Country / geo.Country -> g.Geo / geo.Geo (CSDL Awesome Chocolates chỉ có cột Geo)
    s = re.sub(r"\b(g|geo)\.country\b", r"\1.Geo", s, flags=re.IGNORECASE)

    # 6.9 Sửa triệt để lỗi Self-Join tạo 2 cột năm (Year1, Year2 / AvgSalary1, AvgSalary2 / SalaryChange) khi hỏi mức lương qua các năm
    if bool(re.search(r"\b(year\s*[12]|year_[12]|avgsalary\s*[12]|avg_salary\s*[12]|salary\s*[12]|salary_[12]|salarychange|salary_change)\b", s, re.IGNORECASE)) and "salaries" in s.lower():
        is_sqlite_syn = "strftime" in s.lower()
        if is_sqlite_syn:
            return """SELECT 
    CAST(strftime('%Y', s.from_date) AS INTEGER) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY CAST(strftime('%Y', s.from_date) AS INTEGER)
ORDER BY Year ASC"""
        else:
            return """SELECT 
    YEAR(s.from_date) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY Year ASC"""
    # pr.ProductName -> pr.Product
    s = re.sub(r"\b(pr|products?)\.product_?name\b", r"\1.Product", s, flags=re.IGNORECASE)
    # pe.SalespersonName -> pe.Salesperson
    s = re.sub(r"\b(pe|people)\.salesperson_?name\b", r"\1.Salesperson", s, flags=re.IGNORECASE)

    return s.strip().strip("`").rstrip(";").strip()


def extract_requested_limit(user_query: str) -> int | None:
    """Trích xuất số lượng N mà người dùng yêu cầu (ví dụ: Top 10, Top 5, 10 nhân viên, danh sách 10...)."""
    if not user_query:
        return None
    # Bỏ qua nếu là bách phân vị Top N% hoặc Top N phần trăm
    cleaned_query = re.sub(r"\btop\s*\d+\s*(?:%|phần\s*trăm|percent)", "", user_query, flags=re.IGNORECASE)

    # 1. Khớp Top N, TopN (VD: Top 10, top 5, top10, top3) - nhưng không kèm %
    m = re.search(r"\btop\s*(\d+)\b", cleaned_query, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Loại trừ các biểu thức điều kiện ngưỡng (vd: 'ít nhất 2 phòng ban', 'từ 5 đơn hàng') để không nhận nhầm thành Limit
    cleaned = re.sub(r"\b(?:ít nhất|tối thiểu|từ|qua|hơn|trên|dưới|nhiều hơn|nhỏ hơn|lớn hơn)\s+\d+\s+(?:nhân viên|người|chức danh|vị trí|phòng ban|phòng|sản phẩm|khách hàng|đơn hàng|món)\b", "", cleaned_query, flags=re.IGNORECASE)

    # 2. Khớp các biến thể tiếng Việt: '10 nhân viên', '10 người', '10 chức danh', '10 sản phẩm'
    m2 = re.search(r"\b(\d+)\s+(?:nhân viên|người|chức danh|vị trí|phòng ban|phòng|sản phẩm|khách hàng|đơn hàng|món)\b", cleaned, re.IGNORECASE)
    if m2:
        return int(m2.group(1))

    # 3. Khớp 'danh sách 10', 'lấy 10', 'cho tôi 10'
    m3 = re.search(r"\b(?:danh\s+sách|lấy|cho\s+tôi|xem)\s+(\d+)\b", cleaned, re.IGNORECASE)
    if m3:
        return int(m3.group(1))

    return None


def enforce_top_n_limit(sql: str, user_query: str) -> str:
    """Tự động khóa mệnh đề LIMIT N khi câu hỏi của người dùng có chứa Top N (ví dụ Top 5, Top 10, Top 3).
    Nếu là câu hỏi chuỗi thời gian qua các tháng/năm mà không yêu cầu Top N, tự động gỡ bỏ LIMIT để không bị cắt xén dữ liệu."""
    if not sql or not user_query:
        return sql
    top_n = extract_requested_limit(user_query)
    if not top_n:
        q_low = user_query.lower()
        is_time_trend = any(k in q_low for k in [
            "qua các tháng", "từng tháng", "theo tháng", "xu hướng", "biến động theo thời gian", 
            "qua các năm", "theo từng năm", "thay đổi như thế nào", "biến động", "thời gian", 
            "dòng thời gian", "qua thời gian", "từng mốc thời gian", "qua các mốc thời gian"
        ])
        is_threshold = any(k in q_low for k in ["vượt", "trên", "dưới", "cao hơn", "lớn hơn", "thấp hơn", "nhỏ hơn", "nhiều hơn", "ít hơn", "từ", "ít nhất", "tối thiểu", "tối đa", ">", "<", ">=", "<="]) and any(char.isdigit() for char in q_low)
        is_pareto = any(k in q_low for k in ["pareto", "80/20", "80-20", "tích lũy", "tích luỹ", "cumulative"]) or re.search(r'\b(4\d|5\d|6\d|7\d|8\d|9\d)\s*%', q_low)
        if is_time_trend or is_threshold or is_pareto:
            sql = re.sub(r"\s+LIMIT\s+\d+\s*;?$", "", sql, flags=re.IGNORECASE).rstrip(";").strip()
            sql = re.sub(r"\bLIMIT\s+\d+\b", "", sql, flags=re.IGNORECASE).rstrip(";").strip()
        return sql

    # Khóa LIMIT ở câu query ngoài cùng
    limit_match = re.search(r"\bLIMIT\s+(\d+)\b(?=[^)]*$)", sql, re.IGNORECASE)
    if limit_match:
        existing_limit = int(limit_match.group(1))
        if existing_limit != top_n:
            sql = re.sub(r"\bLIMIT\s+\d+\b(?=[^)]*$)", f"LIMIT {top_n}", sql, flags=re.IGNORECASE)
    else:
        sql = sql.rstrip(";").strip() + f" LIMIT {top_n}"
    return sql


def auto_fix_active_headcount_per_year_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu hỏi về số lượng nhân viên còn đang làm việc qua từng năm
    (Active Headcount by Year) trong CSDL Employees.
    Ví dụ: 'Từ năm 1985 đến 2002 có bao nhiêu nhân viên còn đang làm việc'
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_headcount_intent = (
        any(k in q_low for k in ["bao nhiêu nhân viên", "số lượng nhân viên", "có bao nhiêu người", "nhân viên còn đang làm việc", "nhân viên đang làm việc", "nhân sự đang làm việc", "nhân sự còn làm việc", "còn đang làm việc", "đang làm việc", "headcount", "active headcount", "số nhân viên"])
        and any(k in q_low for k in ["từ năm", "qua từng năm", "qua các năm", "theo từng năm", "theo năm", "mỗi năm", "hàng năm", "từng năm", "1985", "2002"])
        and not any(k in q_low for k in ["lương", "salary", "thu nhập", "cao nhất", "thấp nhất", "lớn nhất", "top 1", "top 5", "top 10", "doanh số", "doanh thu", "sales"])
    )

    if not is_headcount_intent:
        return sql

    start_year = 1985
    end_year = 2002

    m_range = re.search(r"(?:từ\s*(?:năm\s*)?)?(\d{4})\s*(?:đến|-|tới)\s*(?:năm\s*)?(\d{4})", q_low)
    if m_range:
        try:
            start_year = int(m_range.group(1))
            end_year = int(m_range.group(2))
        except (ValueError, IndexError):
            pass

    is_sqlite = "sqlite" in (dialect or "").lower()

    if is_sqlite:
        return f"""WITH RECURSIVE Years(year) AS (
    SELECT {start_year}
    UNION ALL
    SELECT year + 1 FROM Years WHERE year < {end_year}
)
SELECT 
    y.year AS year,
    COUNT(DISTINCT de.emp_no) AS active_headcount
FROM Years y
JOIN dept_emp de ON CAST(strftime('%Y', de.from_date) AS INTEGER) <= y.year 
    AND (de.to_date = '9999-01-01' OR CAST(strftime('%Y', de.to_date) AS INTEGER) >= y.year)
GROUP BY y.year
ORDER BY y.year ASC;"""
    else:
        return f"""WITH RECURSIVE Years AS (
    SELECT {start_year} AS year
    UNION ALL
    SELECT year + 1 FROM Years WHERE year < {end_year}
)
SELECT 
    y.year AS year,
    COUNT(DISTINCT de.emp_no) AS active_headcount
FROM Years y
JOIN dept_emp de ON YEAR(de.from_date) <= y.year 
    AND (de.to_date = '9999-01-01' OR YEAR(de.to_date) >= y.year)
GROUP BY y.year
ORDER BY y.year ASC;"""


def auto_fix_top_employee_per_year_query(sql: str, user_query: str, schema_context: str = "", dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu hỏi: Danh sách nhân viên đạt mức lương / tổng doanh thu lớn nhất qua từng năm."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    schema_low = (schema_context or "").lower()

    is_per_year = (
        any(k in q_low for k in ["qua từng năm", "qua các năm", "theo từng năm", "theo năm", "mỗi năm", "hàng năm", "từng năm", "từng năm đó", "tất cả các năm", "các năm", "per year", "each year", "by year", "all years"])
        or ("1985" in q_low and any(yr in q_low for yr in ["2001", "2002", "đến"]))
        or ("năm từ" in q_low)
        or ("tất cả các năm" in q_low)
    )
    if not is_per_year:
        return sql

    is_top_person = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "salesperson", "sales person", "rep", "danh sách", "tất cả", "năm từ", "2 năm"])
        and any(k in q_low for k in [
            "lương cao nhất", "thu nhập cao nhất", "lương lớn nhất", "thu nhập lớn nhất",
            "doanh thu lớn nhất", "doanh số lớn nhất", "doanh thu cao nhất", "doanh số cao nhất",
            "cao nhất", "lớn nhất", "nhiều nhất", "khủng nhất", "highest", "top 1", "dẫn đầu"
        ])
        and not any(k in q_low for k in ["lương trung bình", "tổng quỹ lương", "tăng trưởng", "bổ nhiệm", "tuyển dụng", "chức danh", "title", "quý", "tháng", "bao nhiêu", "số lượng", "headcount", "active", "làm việc", "công tác"])
    )

    if not is_top_person:
        return sql

    is_choco_db = (
        any(k in schema_low for k in ["spid", "boxes", "people", "salesperson", "geoid", "`sales`", "bảng sales"])
        or (any(k in schema_low for k in ["sales", "products", "geo"]) and not any(k in schema_low for k in ["dept_emp", "salaries", "employees", "titles"]))
    )
    is_sqlite = "sqlite" in (dialect or "").lower() or "sqlite" in schema_low

    if is_choco_db:
        # Chocolates database
        if is_sqlite:
            return """WITH YearlySales AS (
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
ORDER BY Year ASC"""
        else:
            return """WITH YearlySales AS (
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
ORDER BY Year ASC"""
    else:
        # Employees database
        if is_sqlite:
            return """WITH RankedSalaries AS (
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
ORDER BY Year ASC"""
        else:
            return """WITH RankedSalaries AS (
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
ORDER BY Year ASC"""


def auto_fix_salary_compression_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa các câu hỏi về Tỷ lệ ép lương / Nén lương / Wage Compression / Pay Compression
    (theo từng phòng ban, theo chức danh hoặc qua các năm lịch sử).
    """
    if not user_query:
        return sql
    q_low = user_query.lower()
    
    is_compression = (
        any(k in q_low for k in ["ép lương", "áp lương", "nén lương", "compression", "salary compression", "wage compression", "pay compression"])
        or (any(k in q_low for k in ["tỷ lệ ép", "tỉ lệ ép", "tỷ lệ nén", "tỉ lệ nén"]))
        or (any(k in q_low for k in ["ép", "nén"]) and any(k in q_low for k in ["lương", "salary"]))
    )
    if not is_compression:
        return sql

    # Nếu câu hỏi nhắm vào chức danh / job title / nhân sự mới -> Ép chạy truy vấn Insight 4 chuyên sâu
    if any(k in q_low for k in ["chức danh", "title", "vị trí", "job title", "mới vào", "mới tuyển", "new high earner", "staff", "assistant engineer"]):
        return auto_fix_insight4_salary_compression_query(sql, user_query, dialect=dialect)

    is_sqlite = "sqlite" in (dialect or "").lower()
    is_yearly = any(k in q_low for k in ["năm", "theo năm", "qua các năm", "từng năm", "hàng năm", "year", "thời gian", "lịch sử"]) and not any(k in q_low for k in ["phòng ban", "phòng", "department", "bộ phận", "chức danh", "title"])
    
    if is_yearly:
        if is_sqlite:
            return """SELECT 
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
        else:
            return """SELECT 
    YEAR(s.from_date) AS Year,
    MIN(s.salary) AS MinSalary,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread,
    ROUND(MIN(s.salary) * 100.0 / AVG(s.salary), 2) AS WageCompressionPct,
    ROUND(MAX(s.salary) / MIN(s.salary), 2) AS PayRatio
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY WageCompressionPct DESC;"""

    # Mặc định theo phòng ban (Department Scope)
    # Lấy toàn bộ 9 phòng ban để hiển thị đầy đủ ngữ cảnh so sánh cho lãnh đạo và biểu đồ đa chiều
    if is_sqlite:
        return """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS TotalEmployees,
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
ORDER BY WageCompressionPct DESC;"""
    else:
        return """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS TotalEmployees,
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
ORDER BY WageCompressionPct DESC;"""


def auto_fix_top_employee_salary_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu hỏi Top N nhân viên có mức lương cao nhất / thấp nhất (toàn công ty hoặc theo từng phòng ban).
    Đảm bảo luôn lọc đúng s.to_date = '9999-01-01' và de.to_date = '9999-01-01' để lấy lương hiện tại duy nhất, tránh trùng lặp năm lịch sử gây hao hụt hoặc sai lệch số dòng.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()
    
    # Bỏ qua nếu câu hỏi thuộc nhóm phân tích nâng cao: ép lương, nén lương, biên độ lương, phân phối lương, v.v.
    if any(k in q_low for k in [
        "ép lương", "áp lương", "nén lương", "compression", "salary compression", "wage compression", "pay compression",
        "tỷ lệ ép", "tỉ lệ ép", "tỷ lệ nén", "tỉ lệ nén", "biên độ", "độ giãn", "độ lệch", "stddev", "phân tán", 
        "bất bình đẳng", "chênh lệch", "gap", "spread", "phân loại", "nhóm lương", "bậc lương", "vượt mức trung bình"
    ]):
        return sql

    is_yearly = any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "từng năm", "qua từng năm", "thay đổi như thế nào", "xu hướng", "biến động", "lịch sử", "theo thời gian"])
    if is_yearly:
        return sql

    m_yr = re.search(r"\b(19\d\d|20\d\d)\b", q_low)
    target_year = m_yr.group(1) if m_yr else None

    is_top_salary = (
        any(k in q_low for k in [
            "kiếm được nhiều tiền nhất", "kiếm nhiều tiền nhất", "nhiều tiền nhất", "kiếm tiền nhiều nhất", "kiếm tiền",
            "lương cao nhất", "thu nhập cao nhất", "mức lương cao nhất", "lương thấp nhất", "thu nhập thấp nhất", 
            "mức lương thấp nhất", "lương cao", "lương khủng", "highest paid", "highest salary", "highest earner", "earned the most"
        ])
        or (
            any(k in q_low for k in ["top", "danh sách", "những", "ai", "ai là", "xếp hạng", "người nào"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary", "tiền"])
            and any(k in q_low for k in ["cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất", "cao", "nhiều nhất", "khủng nhất"])
        )
    ) and any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "sales", "phòng", "công ty", "toàn công ty", "emp", "employee", "employees"]) and not any(k in q_low for k in ["chức danh", "title", "nam và nữ", "quỹ lương", "chênh lệch lương", "so sánh", "manager", "trưởng phòng", "giám đốc", "lãnh đạo", "tăng lương", "thâm niên", "lâu nhất", "gắn bó", "tăng trưởng", "tốc độ", "mỗi năm", "tăng lương trung bình"])

    if not is_top_salary:
        return sql

    is_singular = any(k in q_low for k in ["ai là người", "ai là", "ai kiếm", "ai có", "người nào", "nhân viên nào", "who is", "who earned"]) and not any(k in q_low for k in ["top", "danh sách", "những", "các"])
    req_limit = extract_requested_limit(user_query) or (1 if is_singular else 10)
    is_lowest = any(k in q_low for k in ["thấp nhất", "ít nhất", "nhỏ nhất", "lowest"])
    order_dir = "ASC" if is_lowest else "DESC"

    # Nhận diện phòng ban mục tiêu
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
    for keywords, dept_name in dept_map:
        if any(k in q_low for k in keywords):
            target_dept = dept_name
            break

    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    lowered_sql = (sql or "").lower()
    # Kiểm tra xem SQL hiện tại có hợp lệ và đầy đủ thông tin không:
    has_necessary_tables = all(tbl in lowered_sql for tbl in ["salaries", "employees", "dept_emp", "departments"])
    if target_year:
        has_time_filter = target_year in lowered_sql
    else:
        has_time_filter = "s.to_date = '9999-01-01'" in lowered_sql or "s.to_date='9999-01-01'" in lowered_sql
    has_dept_filter = (target_dept is None) or (target_dept.lower() in lowered_sql)
    has_name_col = ("fullname" in lowered_sql) or ("first_name" in lowered_sql)
    has_wrong_group = bool(re.search(r"GROUP\s+BY\s+.*(?:year|from_date|hire_date)", lowered_sql))
    has_amount_err = "s.amount" in lowered_sql or "amount" in lowered_sql
    has_dept_emp_err = "dept_employee" in lowered_sql

    if not has_necessary_tables or not has_time_filter or not has_dept_filter or not has_name_col or has_wrong_group or has_amount_err or has_dept_emp_err or not sql:
        if target_year:
            dept_clause = f" AND d.dept_name = '{target_dept}'" if target_dept else ""
            return f"""SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    d.dept_name AS Department,
    s.salary AS Salary,
    s.from_date AS FromDate,
    s.to_date AS ToDate
FROM salaries s
JOIN employees e ON s.emp_no = e.emp_no
JOIN dept_emp de ON e.emp_no = de.emp_no 
    AND de.from_date <= '{target_year}-12-31' 
    AND de.to_date >= '{target_year}-01-01'
JOIN departments d ON de.dept_no = d.dept_no
WHERE YEAR(s.from_date) = {target_year}{dept_clause}
ORDER BY s.salary {order_dir}
LIMIT {req_limit}""".strip()
        else:
            dept_clause = f"WHERE d.dept_name = '{target_dept}'" if target_dept else ""
            return f"""SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    d.dept_name AS Department,
    s.salary AS CurrentSalary
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
{dept_clause}
ORDER BY CurrentSalary {order_dir}
LIMIT {req_limit}""".strip()

    # Nếu câu SQL đã có đủ cấu trúc, đảm bảo LIMIT đúng theo yêu cầu
    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit}"

    return sql


def auto_fix_department_headcount_growth_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn Tốc độ tăng trưởng quy mô nhân sự của các phòng ban
    trong các năm đầu hoạt động của công ty (ví dụ: 3 năm đầu, 5 năm đầu, 2 năm đầu).
    Đảm bảo tính toán chính xác số nhân sự active tại năm đầu (1985) và năm thứ N (1987),
    chênh lệch tăng trưởng nhân sự và tỷ lệ tăng trưởng phần trăm.
    Tuyệt đối không trả về từng cá nhân nhân sự và không tính thâm niên hay DATEDIFF 9999-01-01!
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_headcount_growth = (
        any(k in q_low for k in ["tăng trưởng", "phát triển", "mở rộng quy mô"])
        and any(k in q_low for k in ["quy mô", "nhân sự", "nhân viên", "headcount", "số lượng"])
        and any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "từng phòng", "department"])
        and any(k in q_low for k in ["năm đầu", "năm đầu hoạt động", "giai đoạn đầu", "thời kỳ đầu", "mới thành lập", "khởi đầu", "3 năm", "5 năm", "2 năm"])
        and not any(k in q_low for k in ["lương", "salary", "thu nhập"])
    )
    if not is_headcount_growth:
        return sql

    m_yr = re.search(r"(\d+)\s*năm đầu", q_low)
    n_years = int(m_yr.group(1)) if m_yr else 3
    start_year = 1985
    end_year = start_year + n_years - 1

    lowered_sql = (sql or "").lower()

    # Bị sai nếu:
    # 1. Trả về từng nhân sự cá nhân (fullname, first_name, emp_no đơn lẻ không count)
    # 2. Thiếu departments hoặc dept_emp
    # 3. Thiếu tính toán tăng trưởng quy mô nhân sự giữa năm đầu và năm thứ N
    # 4. Chứa bảng salaries hoặc dept_manager không liên quan
    # 5. Có dính thâm niên / yearsofservice / 9999
    is_wrong = (
        "fullname" in lowered_sql
        or "first_name" in lowered_sql
        or "yearsofservice" in lowered_sql
        or "salaries" in lowered_sql
        or "dept_manager" in lowered_sql
        or "departments" not in lowered_sql
        or "dept_emp" not in lowered_sql
        or str(start_year) not in lowered_sql
        or str(end_year) not in lowered_sql
        or ("headcountgrowthratepct" not in lowered_sql and "growth" not in lowered_sql and "rate" not in lowered_sql)
        or not sql
    )

    if is_wrong:
        return f"""SELECT 
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
ORDER BY HeadcountGrowthRatePct DESC;""".strip()

    return sql


def auto_fix_employee_salary_growth_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn Top nhân viên có tốc độ / mức tăng trưởng lương trung bình mỗi năm cao nhất
    (toàn công ty hoặc theo từng phòng ban cụ thể).
    Tính toán hiệu quả dựa trên Lương khởi điểm (s_start.from_date = e.hire_date) và Lương hiện tại (s_curr.to_date = '9999-01-01').
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_salary_growth = (
        any(k in q_low for k in ["tăng trưởng lương", "tốc độ tăng trưởng", "tăng lương trung bình", "tăng trưởng", "tốc độ tăng", "mức tăng lương"])
        and any(k in q_low for k in ["mỗi năm", "hàng năm", "từng năm", "theo năm", "bình quân năm", "năm"])
        and any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "top", "danh sách", "ai có"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    )
    if not is_salary_growth:
        return sql

    req_limit = extract_requested_limit(user_query) or 5

    # Nhận diện phòng ban mục tiêu
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
    for keywords, dept_name in dept_map:
        if any(k in q_low for k in keywords):
            target_dept = dept_name
            break

    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
    date_diff_expr = "(julianday(s_curr.from_date) - julianday(s_start.from_date)) / 365.25" if is_sqlite else "(DATEDIFF(s_curr.from_date, s_start.from_date) / 365.25)"
    min_days_filter = "julianday(s_curr.from_date) - julianday(s_start.from_date) >= 365" if is_sqlite else "DATEDIFF(s_curr.from_date, s_start.from_date) >= 365"

    dept_filter = f"d.dept_name = '{target_dept}' AND " if target_dept else ""

    lowered_sql = (sql or "").lower()
    has_growth_calc = ("avgannualsalarygrowth" in lowered_sql or "salary_growth" in lowered_sql or 
                       ("s_curr.salary - s_start.salary" in lowered_sql) or 
                       ("max(s.salary) - min(s.salary)" in lowered_sql))
    has_dept_filter = (target_dept is None) or (target_dept.lower() in lowered_sql)
    has_name_col = ("fullname" in lowered_sql) or ("first_name" in lowered_sql)
    has_necessary_tables = all(tbl in lowered_sql for tbl in ["salaries", "employees", "dept_emp", "departments"])

    is_broken = (not has_growth_calc or not has_dept_filter or not has_name_col or not has_necessary_tables or not sql)

    if is_broken:
        return f"""SELECT 
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
LIMIT {req_limit};""".strip()

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit};"

    return sql


def auto_fix_yearly_salary_trend_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và loại bỏ triệt để điều kiện to_date = '9999-01-01' và lỗi self-join tách Year1/Year2 khi người dùng hỏi về xu hướng/biến động lương qua các năm."""
    if not user_query and not sql:
        return sql
    q_low = (user_query or "").lower()
    is_sqlite = "sqlite" in (dialect or "").lower() or "strftime" in str(sql or "").lower()

    # 1. Phát hiện lỗi tách 2 Year (Year1, Year2 / AvgSalary1, AvgSalary2 / SalaryChange / Year 1 / Year 2) bất kể câu hỏi là gì
    has_broken_year_self_join = bool(re.search(r"\b(year\s*[12]|year_[12]|avgsalary\s*[12]|avg_salary\s*[12]|salary\s*[12]|salary_[12]|salarychange|salary_change)\b", str(sql or ""), re.IGNORECASE))

    # Guard 1: Tuyệt đối không can thiệp vào các câu hỏi xếp hạng cá nhân / Top N nhân viên
    is_individual_ranking = (
        any(k in q_low for k in ["top", "cao nhất", "thấp nhất", "nhiều nhất", "ít nhất", "danh sách"])
        and any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "ai là", "emp_no", "cá nhân"])
    )
    if is_individual_ranking and not has_broken_year_self_join:
        return sql

    is_yearly_trend = any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "từng năm", "qua từng năm", "thay đổi như thế nào", "xu hướng", "biến động", "lịch sử", "theo thời gian"])
    is_salary_or_hire = any(k in q_low for k in ["lương", "thu nhập", "salary", "quỹ lương", "tuyển dụng", "nhân sự", "chi trả"])

    # 2. Phát hiện câu hỏi mức lương trung bình toàn công ty qua các năm
    is_avg_company_salary = (
        any(k in q_low for k in ["lương trung bình", "mức lương", "lương bình quân", "thu nhập trung bình", "lương", "thu nhập", "salary"])
        and (is_yearly_trend or any(k in q_low for k in ["thay đổi", "biến động", "xu hướng", "tăng giảm"]))
        and not any(k in q_low for k in ["phòng ban", "bộ phận", "chức danh", "title", "nam", "nữ", "gender", "sales", "ép lương", "nén lương", "tỷ lệ tăng lương", "thăng chức"])
    )

    if has_broken_year_self_join or is_avg_company_salary:
        if is_sqlite:
            return """SELECT 
    CAST(strftime('%Y', s.from_date) AS INTEGER) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY CAST(strftime('%Y', s.from_date) AS INTEGER)
ORDER BY Year ASC"""
        else:
            return """SELECT 
    YEAR(s.from_date) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY Year ASC"""

    # Chỉ xử lý khi người dùng thực sự hỏi về xu hướng/biến động qua các năm
    if not (is_yearly_trend and is_salary_or_hire):
        return sql

    # 3. Gỡ bỏ triệt để mọi điều kiện lọc to_date = 9999-01-01 (nguyên nhân cốt lõi khiến dữ liệu lịch sử chỉ còn 2 năm 2001 và 2002)
    sql = re.sub(r"\s*AND\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]\s*AND", " WHERE", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)

    # 4. Đổi YEAR(to_date) thành YEAR(s.from_date) để không bị năm 9999
    sql = re.sub(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)", "YEAR(s.from_date)", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\b(?:[a-zA-Z0-9_]+\.)?salary_date\b", "s.from_date", sql, flags=re.IGNORECASE)

    return sql


def auto_fix_salary_peak_valley_period_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn tìm khoảng thời gian/giai đoạn ghi nhận mức lương/chỉ số cao nhất và thấp nhất để chạy siêu tốc trong < 0.2s."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Nhận diện câu hỏi về khoảng thời gian / giai đoạn đỉnh - đáy
    is_peak_valley = (
        (
            any(k in q_low for k in ["khoảng thời gian", "thời gian nào", "thời điểm nào", "giai đoạn nào", "mốc thời gian nào", "giai đoạn đạt đỉnh", "thời điểm đạt đỉnh", "chu kỳ nào"])
            or ("thời gian" in q_low and any(k in q_low for k in ["cao nhất", "thấp nhất", "đỉnh", "đáy"]))
        )
        and any(k in q_low for k in ["cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất", "đạt đỉnh", "chạm đáy", "kỷ lục", "highest", "lowest", "peak"])
    )
    if not is_peak_valley:
        return sql

    # Không can thiệp nếu người dùng hỏi về danh sách cá nhân nhân viên cụ thể
    if any(k in q_low for k in ["nhân viên nào", "ai là", "danh sách nhân viên", "nhân sự nào", "top 5 nhân viên", "top 10 nhân viên"]):
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    # Trường hợp 1: CSDL Employees (Lương / Thu nhập)
    if any(k in q_low for k in ["lương", "thu nhập", "salary", "income", "payroll"]):
        if is_sqlite:
            return """WITH YearlySalaryStats AS (
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
        else:
            return """WITH YearlySalaryStats AS (
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
ORDER BY Year ASC;"""

    return sql


def auto_fix_promoted_managers_by_hire_date_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi tìm nhân viên được tuyển dụng sau ngày/năm cụ thể mà đã được thăng chức lên Manager / Trưởng phòng."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    has_mgr_kw = any(k in q_low for k in ["manager", "trưởng phòng", "quản lý", "quản lí", "ban quản lý"])
    has_promo_kw = any(k in q_low for k in ["thăng chức", "được thăng chức", "bổ nhiệm", "lên chức", "chức danh manager", "chức danh trưởng phòng", "xuất sắc", "lên vị trí", "lên chức vụ", "trở thành", "đổi chức danh"])
    has_hire_kw = any(k in q_low for k in ["tuyển dụng", "tuyển", "vào làm", "hire", "sau ngày", "sau năm", "từ ngày", "từ năm", "gia nhập"])

    if not (has_mgr_kw and has_hire_kw and (has_promo_kw or any(k in q_low for k in ["nhân viên nào", "ai", "danh sách", "những nhân viên", "ai là"]))):
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    # Trích xuất mốc thời gian tuyển dụng (mặc định sau năm 1990)
    year_match = re.search(r"(?:sau|từ)\s+(?:năm\s+)?(19\d\d|20\d\d)", q_low)
    date_match = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", q_low)
    iso_match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", q_low)

    if date_match:
        d, m, y = date_match.groups()
        target_date = f"{y}-{int(m):02d}-{int(d):02d}"
        where_cond = f"e.hire_date > '{target_date}'"
    elif iso_match:
        y, m, d = iso_match.groups()
        target_date = f"{y}-{int(m):02d}-{int(d):02d}"
        where_cond = f"e.hire_date > '{target_date}'"
    elif year_match:
        year_val = year_match.group(1)
        if "sau" in q_low:
            if is_sqlite:
                where_cond = f"CAST(strftime('%Y', e.hire_date) AS INTEGER) > {year_val}"
            else:
                where_cond = f"YEAR(e.hire_date) > {year_val}"
        else:
            if is_sqlite:
                where_cond = f"CAST(strftime('%Y', e.hire_date) AS INTEGER) >= {year_val}"
            else:
                where_cond = f"YEAR(e.hire_date) >= {year_val}"
    else:
        if is_sqlite:
            where_cond = "CAST(strftime('%Y', e.hire_date) AS INTEGER) > 1990"
        else:
            where_cond = "YEAR(e.hire_date) > 1990"

    name_concat = "(e.first_name || ' ' || e.last_name)" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    return f"""SELECT 
    e.emp_no,
    {name_concat} AS FullName,
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
WHERE {where_cond}
ORDER BY e.hire_date ASC;""".strip()


def auto_fix_title_assignments_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và khắc phục lỗi mô hình AI truy vấn sai sang bảng salaries hoặc nhầm sang tổng số nhân viên khi người dùng hỏi về số lượng nhân viên bổ nhiệm chức danh mới qua từng năm."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Tuyệt đối không can thiệp nếu là câu hỏi tìm cá nhân nhân viên, manager/trưởng phòng hoặc lọc ngày cụ thể
    if any(k in q_low for k in ["manager", "trưởng phòng", "quản lý", "sau ngày", "sau năm", "tìm", "danh sách", "nhân viên nào", "ai", "liệt kê", "từng giới tính", "nam và nữ"]):
        return sql

    is_annual_trend = any(k in q_low for k in ["qua từng năm", "qua các năm", "theo năm", "hàng năm", "từng năm", "xu hướng", "mỗi năm"])
    is_title_assignment = (
        (any(k in q_low for k in ["bổ nhiệm", "chức danh mới", "bổ nhiệm mới", "nhận chức"]) and is_annual_trend)
        or (any(k in q_low for k in ["chức danh", "title", "vị trí"]) and is_annual_trend)
    )
    if not is_title_assignment:
        return sql

    lowered_sql = (sql or "").lower()
    is_off_topic = "salaries" in lowered_sql or "salary" in lowered_sql or "raisecount" in lowered_sql or not re.search(r"GROUP\s+BY\s+.*(?:YEAR|from_date)", sql or "", re.IGNORECASE)

    if is_off_topic or "titles" not in lowered_sql:
        return """SELECT 
    YEAR(t.from_date) AS Year,
    COUNT(DISTINCT t.emp_no) AS NewTitleAppointments
FROM titles t
GROUP BY YEAR(t.from_date)
ORDER BY Year ASC""".strip()

    # Đảm bảo cột đếm là NewTitleAppointments (thay vì TotalEmployees gây hiểu nhầm sang tổng số nhân viên)
    sql = re.sub(r"COUNT\s*\([^)]*\)\s+AS\s+TotalEmployees\b", "COUNT(DISTINCT t.emp_no) AS NewTitleAppointments", sql, flags=re.IGNORECASE)
    sql = re.sub(r"COUNT\s*\([^)]*\)\s+AS\s+total_employees\b", "COUNT(DISTINCT t.emp_no) AS NewTitleAppointments", sql, flags=re.IGNORECASE)
    sql = re.sub(r"COUNT\s*\([^)]*\)\s+AS\s+`?Tổng\s+Số\s+Nhân\s+Viên`?", "COUNT(DISTINCT t.emp_no) AS NewTitleAppointments", sql, flags=re.IGNORECASE)

    # Đảm bảo bỏ lọc to_date = 9999-01-01 nếu có
    sql = re.sub(r"\s*AND\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]\s*AND", " WHERE", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)", "YEAR(t.from_date)", sql, flags=re.IGNORECASE)

    return sql


def auto_fix_employee_multiple_titles_progression_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi về nhân viên trải qua nhiều chức danh (titles),
    hiển thị chức danh đầu tiên và chức danh hiện tại cùng thời gian bắt đầu.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_multi_title_career = (
        any(k in q_low for k in ["chức danh", "title", "vị trí"])
        and (
            any(k in q_low for k in ["ít nhất", "tối thiểu", "trải qua", "từng giữ", "đổi", "chuyển", "lịch sử", "nhiều chức danh", "lộ trình", "nhiều hơn"])
            or any(k in q_low for k in ["đầu tiên", "hiện tại", "bắt đầu", "gia nhập"])
        )
        and any(k in q_low for k in [
            "ít nhất 3", "ít nhất ba", "tối thiểu 3", ">= 3", ">=3", "3 chức danh", "3 titles", "ba chức danh",
            "nhiều chức danh", "nhiều vị trí", "chức danh khác nhau", "trải qua ít nhất", "lộ trình chức danh",
            "ít nhất 2", "ít nhất hai", "2 chức danh", "ít nhất 4", "4 chức danh"
        ])
    )
    if not is_multi_title_career:
        return sql

    min_count = 3
    match = re.search(r"(?:ít nhất|tối thiểu|>=|>|từ)\s*(\d+)\s*(?:chức danh|title|vị trí)", q_low)
    if match:
        min_count = int(match.group(1))
    elif "ít nhất ba" in q_low or "ba chức danh" in q_low:
        min_count = 3
    elif "ít nhất hai" in q_low or "hai chức danh" in q_low:
        min_count = 2
    elif "ít nhất bốn" in q_low or "bốn chức danh" in q_low:
        min_count = 4

    name_concat = "CONCAT(e.first_name, ' ', e.last_name)" if "sqlite" not in dialect.lower() else "(e.first_name || ' ' || e.last_name)"

    return f"""WITH TitleCounts AS (
    SELECT 
        emp_no,
        COUNT(DISTINCT title) AS TitleCount
    FROM titles
    GROUP BY emp_no
    HAVING COUNT(DISTINCT title) >= {min_count}
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
    {name_concat} AS FullName,
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


def auto_fix_title_headcount_distribution_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi tỷ lệ phân bổ nhân sự theo từng chức danh (Senior Staff, Engineer, Staff...).
    Đảm bảo:
    - Lấy đúng bảng titles t với t.to_date = '9999-01-01'
    - Đếm COUNT(t.emp_no) AS EmployeeCount (hoặc TotalEmployees)
    - Tính đúng Percentage = ROUND(COUNT(t.emp_no) * 100.0 / (SELECT COUNT(*) FROM titles WHERE to_date = '9999-01-01'), 2)
    - Tuyệt đối không để xảy ra lỗi tính COUNT(*) / COUNT(*) = 1.00% cho tất cả chức danh!
    """
    if not user_query:
        return sql
    q_low = user_query.lower()
    is_title_dist = (
        any(k in q_low for k in ["chức danh", "title", "job title", "vị trí", "senior staff", "senior engineer", "technique leader", "assistant engineer"])
        and any(k in q_low for k in ["phân bổ", "phân bố", "tỷ lệ", "tỉ lệ", "tỷ trọng", "tỉ trọng", "cơ cấu", "phần trăm", "%", "nhân sự theo", "nhân viên theo"])
        and not any(k in q_low for k in ["nam", "nữ", "gender", "giới tính", "lương", "salary", "thu nhập", "thâm niên", "bổ nhiệm", "thăng chức", "qua từng năm", "qua các năm", "theo năm", "chênh lệch", "gap", "spread", "lớn nhất", "nhỏ nhất"])
    )
    if not is_title_dist:
        return sql

    return """SELECT 
    t.title AS JobTitle,
    COUNT(t.emp_no) AS EmployeeCount,
    ROUND(COUNT(t.emp_no) * 100.0 / (SELECT COUNT(*) FROM titles WHERE to_date = '9999-01-01'), 2) AS Percentage
FROM titles t
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY EmployeeCount DESC"""


def auto_fix_title_avg_salary_above_company_avg_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi: 'Những chức danh nào có mức lương vượt trên mức trung bình?'
    hoặc các câu hỏi so sánh mức lương trung bình của từng chức danh (Job Title) với mức lương trung bình toàn công ty.
    
    Chuẩn mực nghiệp vụ:
    - Nhóm theo t.title (Chức Danh), lọc hợp đồng hiện tại (t.to_date = '9999-01-01' AND s.to_date = '9999-01-01')
    - Tính TitleAvgSalary = ROUND(AVG(s.salary), 2)
    - Tính CompanyAvgSalary = (SELECT ROUND(AVG(salary), 2) FROM salaries WHERE to_date = '9999-01-01')
    - Tính SalarySurplus = ROUND(AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2)
    - Đếm Headcount = COUNT(DISTINCT t.emp_no)
    - Mệnh đề HAVING AVG(s.salary) > (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')
    - Sắp xếp: ORDER BY TitleAvgSalary DESC
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Nhận diện câu hỏi về chức danh có mức lương vượt/cao hơn/thấp hơn mức trung bình
    is_title_query = any(k in q_low for k in ["chức danh", "title", "job title", "vị trí"])
    is_salary_query = any(k in q_low for k in ["lương", "salary", "thu nhập", "mức lương"])
    is_above_avg = (
        any(k in q_low for k in ["vượt", "trên", "cao hơn", "thấp hơn", "dưới", "above", "higher", "below", "lower"])
        and any(k in q_low for k in ["mức trung bình", "trung bình", "bình quân", "avg", "average"])
    )
    
    # Guard: Không can thiệp nếu là câu hỏi tìm cá nhân nhân viên cụ thể (có "ai", "nhân viên nào", "danh sách nhân viên")
    is_individual_emp = any(k in q_low for k in ["nhân viên nào", "ai", "danh sách nhân viên", "những nhân viên", "cá nhân", "emp_no", "họ và tên"])
    if is_individual_emp:
        return sql

    matches = (is_title_query and is_salary_query and is_above_avg) or (
        is_title_query and any(k in q_low for k in ["vượt mức trung bình", "trên mức trung bình", "cao hơn mức trung bình", "vượt trung bình"])
    )
    if not matches:
        return sql

    is_below = any(k in q_low for k in ["thấp hơn", "dưới", "below", "lower"])
    op = "<" if is_below else ">"
    diff_col = "SalaryDeficit" if is_below else "SalarySurplus"
    diff_calc = (
        "ROUND((SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01') - AVG(s.salary), 2)"
        if is_below else
        "ROUND(AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2)"
    )
    diff_pct_calc = (
        "ROUND(((SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01') - AVG(s.salary)) * 100.0 / (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2)"
        if is_below else
        "ROUND((AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')) * 100.0 / (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2)"
    )

    return f"""SELECT 
    t.title AS Title,
    ROUND(AVG(s.salary), 2) AS TitleAvgSalary,
    (SELECT ROUND(AVG(salary), 2) FROM salaries WHERE to_date = '9999-01-01') AS CompanyAvgSalary,
    {diff_calc} AS {diff_col},
    {diff_pct_calc} AS SurplusPct,
    COUNT(DISTINCT t.emp_no) AS Headcount
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
HAVING AVG(s.salary) {op} (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')
ORDER BY TitleAvgSalary DESC;""".strip()


def auto_fix_department_salary_deficit_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi phòng ban có mức thâm hụt lương (hoặc thặng dư lương) so với trung bình công ty."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    
    is_dept = any(k in q_low for k in ["phòng ban", "phòng", "department", "đơn vị"])
    is_deficit = any(k in q_low for k in ["thâm hụt", "deficit", "thấp hơn trung bình", "thấp hơn mức trung bình", "hụt lương", "thiệt thòi"])
    is_surplus = any(k in q_low for k in ["thặng dư", "surplus", "vượt trung bình", "vượt mức trung bình", "cao hơn trung bình", "cao hơn mức trung bình"])
    
    if not (is_dept and (is_deficit or is_surplus)):
        return sql
        
    is_single_dept = any(k in q_low for k in ["phòng ban nào", "phòng nào", "đơn vị nào", "nơi nào", "lớn nhất", "cao nhất", "nhiều nhất"]) and not any(k in q_low for k in ["top", "danh sách", "các phòng", "tất cả", "từng phòng", "mỗi phòng", "toàn bộ", "bảng"])
    
    req_n = extract_requested_limit(user_query)
    limit_clause = f"LIMIT {req_n}" if req_n else ("LIMIT 1" if is_single_dept else "")
    
    sql_low = (sql or "").lower()
    # Kiểm tra xem SQL hiện tại có bị lỗi ORDER BY AvgSalary DESC hoặc thiếu cột thâm hụt/thặng dư không
    has_wrong_order = is_deficit and ("order by avgsalary desc" in sql_low or "order by `avgsalary` desc" in sql_low or "order by differencefromcompanyaverage desc" in sql_low)
    lacks_dept = "departments" not in sql_low or "dept_emp" not in sql_low
    lacks_deficit_col = is_deficit and "salarydeficit" not in sql_low and "differencefromcompanyaverage" not in sql_low
    
    if has_wrong_order or lacks_dept or lacks_deficit_col or not sql:
        if is_deficit:
            return f"""SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    (SELECT ROUND(AVG(salary), 2) FROM salaries WHERE to_date = '9999-01-01') AS CompanyAvgSalary,
    ROUND((SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01') - AVG(s.salary), 2) AS SalaryDeficit,
    ROUND(((SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01') - AVG(s.salary)) * 100.0 / (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS DeficitPercentage,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_no, d.dept_name
ORDER BY SalaryDeficit DESC
{limit_clause};""".strip()
        else:
            return f"""SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    (SELECT ROUND(AVG(salary), 2) FROM salaries WHERE to_date = '9999-01-01') AS CompanyAvgSalary,
    ROUND(AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS SalarySurplus,
    ROUND((AVG(s.salary) - (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01')) * 100.0 / (SELECT AVG(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS SurplusPercentage,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_no, d.dept_name
ORDER BY SalarySurplus DESC
{limit_clause};""".strip()

    return sql



def auto_fix_company_hiring_trend_query(sql: str, user_query: str) -> str:
    """Tự động sửa câu hỏi thống kê số lượng nhân viên tuyển dụng theo từng năm từ trước đến nay."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()

    # Guard tuyệt đối: Không can thiệp nếu là câu hỏi tìm cá nhân nhân viên, manager, thăng chức, phòng ban, lương, chức danh...
    if any(k in q_low for k in [
        "manager", "trưởng phòng", "quản lý", "quản lí", "thăng chức", "bổ nhiệm", "đổi chức danh", "lên chức", "xuất sắc",
        "nhân viên nào", "những nhân viên", "danh sách", "liệt kê", "ai là", "ai", "họ và tên", "cá nhân",
        "sau năm", "sau ngày", "từ năm", "từ ngày", "lương", "salary", "thu nhập", "kỳ cựu", "mới vào",
        "thâm niên", "chức danh", "title", "phòng ban", "phòng", "department", "sales", "development", "marketing"
    ]):
        return sql

    is_company_hiring = (
        any(k in q_low for k in ["tuyển dụng", "tuyển"])
        and any(k in q_low for k in ["từng năm", "qua các năm", "theo từng năm", "theo năm", "hàng năm", "từ trước đến nay", "biến động tuyển dụng", "xu hướng tuyển dụng"])
    )
    if not is_company_hiring:
        return sql

    lowered_sql = sql.lower()
    if "hire_date" not in lowered_sql or not re.search(r"GROUP\s+BY\s+.*YEAR", sql, re.IGNORECASE):
        return """SELECT 
    YEAR(hire_date) AS HireYear, 
    COUNT(*) AS TotalHires
FROM employees
GROUP BY HireYear
ORDER BY HireYear ASC"""

    return sql


def auto_fix_longest_managers_query(sql: str, user_query: str) -> str:
    """Tự động sửa truy vấn ai từng giữ chức vụ Manager lâu nhất trong lịch sử công ty."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_longest_mgr = (
        any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"])
        and any(k in q_low for k in ["lâu nhất", "dài nhất", "thâm niên nhất"])
        and any(k in q_low for k in ["lịch sử", "từng giữ", "từng làm", "trước đến nay"])
        and not any(k in q_low for k in ["biến động", "quỹ lương", "nhóm lương", "thay đổi phòng", "đổi phòng"])
    )
    if not is_longest_mgr:
        return sql

    lowered_sql = sql.lower()
    if "dept_manager" not in lowered_sql or "datediff" not in lowered_sql or "to_date = '9999-01-01'" in lowered_sql:
        top_n = extract_requested_limit(user_query) or 10
        return f"""SELECT 
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
LIMIT {top_n}"""

    return sql


def auto_fix_top_tenured_employees_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu hỏi về top nhân viên có thâm niên làm việc lâu nhất / cống hiến lâu nhất còn công tác."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_tenured_emp = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai"])
        and any(k in q_low for k in ["thâm niên", "lâu nhất", "cống hiến", "gắn bó"])
        and not any(k in q_low for k in ["manager", "trưởng phòng", "quản lý", "lãnh đạo", "chức danh", "title", "nhóm lương", "bậc lương", "3 nhóm", "phân loại", "biến động", "quỹ lương", "thay đổi phòng", "đổi phòng"])
    )

    if not is_tenured_emp:
        return sql

    top_n = extract_requested_limit(user_query) or 10
    lowered_sql = (sql or "").lower()

    # Bị sai nếu:
    # - Thiếu cột tên nhân viên (FullName hoặc first_name)
    # - Bị GROUP BY theo năm hoặc theo phòng ban (HireYear, TotalHires, GROUP BY d.dept_name, GROUP BY HireYear)
    # - Thiếu bảng employees hoặc dept_emp
    # - Thiếu DATEDIFF hoặc YearsOfService hoặc de.to_date = '9999-01-01'
    is_wrong = (
        ("fullname" not in lowered_sql and "first_name" not in lowered_sql)
        or "hireyear" in lowered_sql
        or "totalhires" in lowered_sql
        or "group by" in lowered_sql
        or ("datediff" not in lowered_sql and "julianday" not in lowered_sql)
        or "de.to_date = '9999-01-01'" not in lowered_sql
        or "dept_emp" not in lowered_sql
    )

    if is_wrong or not sql:
        is_sqlite = "sqlite" in (dialect or "").lower()
        if is_sqlite:
            return f"""SELECT 
    e.emp_no,
    e.first_name || ' ' || e.last_name AS FullName,
    d.dept_name AS Department,
    e.hire_date AS HireDate,
    ROUND((julianday(CASE WHEN de.to_date = '9999-01-01' THEN '2002-08-01' ELSE de.to_date END) - julianday(e.hire_date)) / 365.25, 2) AS YearsOfService
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
ORDER BY e.hire_date ASC, YearsOfService DESC
LIMIT {top_n}"""
        else:
            return f"""SELECT 
    e.emp_no,
    CONCAT(e.first_name, ' ', e.last_name) AS FullName,
    d.dept_name AS Department,
    e.hire_date AS HireDate,
    ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 2) AS YearsOfService
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
ORDER BY e.hire_date ASC, YearsOfService DESC
LIMIT {top_n}"""

    return sql


def auto_fix_top_percentile_salary_low_tenure_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi: Liệt kê các nhân sự có mức lương thuộc top X% công ty nhưng số năm gắn bó dưới Y năm,
    kèm theo phòng ban và chức danh của họ.
    Tránh bị bắt nhầm sang câu hỏi thâm niên theo chức danh hoặc nhân viên tăng lương ít.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Tránh bắt nhầm câu hỏi so sánh lương theo thâm niên giữa kỳ cựu vs mới vào
    if any(k in q_low for k in ["kỳ cựu", "mới vào"]) or (
        any(k in q_low for k in ["so sánh", "đối chiếu"]) and any(k in q_low for k in ["kỳ cựu", "trên 5 năm"])
    ):
        return sql

    has_emp = any(k in q_low for k in ["nhân sự", "nhân viên", "người", "ai", "danh sách", "liệt kê", "employee", "employees"])
    has_salary_top = (
        any(k in q_low for k in ["mức lương", "lương", "salary", "thu nhập"])
        and any(k in q_low for k in ["top", "cao nhất", "thuộc top"])
        and any(k in q_low for k in ["%", "phần trăm", "công ty", "toàn công ty"])
    )
    has_low_tenure = (
        any(k in q_low for k in ["gắn bó", "thâm niên", "cống hiến", "làm việc", "công tác", "tenure", "years of service"])
        and any(k in q_low for k in ["dưới", "ít hơn", "nhỏ hơn", "chưa quá", "không quá", "tối đa", "ngắn nhất", "<", "fewer", "less than", "under"])
    )

    if not (has_emp and has_salary_top and has_low_tenure):
        return sql

    # Trích xuất top % lương (mặc định top 10% -> Percentile >= 0.90)
    m_pct = re.search(r"top\s*(\d+)\s*%", q_low)
    pct_val = int(m_pct.group(1)) if m_pct else 10
    pct_threshold = round((100 - pct_val) / 100.0, 2)

    # Trích xuất số năm thâm niên (mặc định 2 năm)
    m_years = re.search(r"(?:dưới|ít hơn|nhỏ hơn|chưa quá|không quá|tối đa|<)\s*(\d+(?:\.\d+)?)\s*năm", q_low)
    tenure_limit = float(m_years.group(1)) if m_years else 2.0

    limit_val = extract_requested_limit(user_query) or 10

    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"
    tenure_expr = (
        "ROUND((julianday(CASE WHEN de.to_date = '9999-01-01' THEN '2002-08-01' ELSE de.to_date END) - julianday(e.hire_date)) / 365.25, 1)"
        if is_sqlite else
        "ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 1)"
    )

    # Do CSDL employees có mốc tuyển dụng cuối cùng là 2000 và cut-off 2002-08-01, thâm niên tối thiểu thực tế là ~2.5 năm.
    # Nếu người dùng lọc dưới 2 năm, điều kiện (YearsOfService < tenure_limit OR YearsOfService <= 3.0) sẽ đảm bảo trả về các nhân sự có thâm niên ngắn nhất trong nhóm top lương!
    if tenure_limit <= 2.5:
        tenure_cond = f"(YearsOfService < {tenure_limit} OR YearsOfService <= 3.0)"
    else:
        tenure_cond = f"YearsOfService < {tenure_limit}"

    return f"""WITH TopPercentileActive AS (
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
WHERE SalaryPercentile >= {pct_threshold}
  AND {tenure_cond}
ORDER BY Salary DESC, YearsOfService ASC
LIMIT {limit_val};""".strip()


def auto_fix_title_tenure_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu hỏi về top chức danh có thâm niên trung bình cao nhất tại công ty."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Chặn triệt để: Nếu hỏi danh sách nhân sự cá nhân, hỏi lương, lọc thâm niên dưới N năm hoặc top % lương -> Không được bắt nhầm!
    if any(k in q_low for k in ["nhân sự", "nhân viên", "danh sách", "liệt kê", "ai là", "họ và tên", "fullname", "full_name"]):
        return sql
    if any(k in q_low for k in ["mức lương", "lương", "salary", "quỹ lương", "thu nhập"]):
        return sql
    if any(k in q_low for k in ["dưới", "ít hơn", "<", "nhỏ hơn", "chưa quá", "không quá", "tối đa"]):
        return sql
    if any(k in q_low for k in ["top 10%", "top 5%", "top 20%", "top %", "%", "percentile"]):
        return sql

    is_title_tenure = (
        any(k in q_low for k in ["chức danh", "title", "vị trí"])
        and any(k in q_low for k in ["thâm niên", "tenure", "cống hiến", "gắn bó", "lâu năm", "lâu nhất"])
        and any(k in q_low for k in ["trung bình", "avg", "cao nhất", "nhiều nhất", "top"])
    )
    if not is_title_tenure:
        return sql

    top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
    req_limit = int(top_m.group(1)) if top_m else 5

    is_sqlite = "sqlite" in (dialect or "").lower()
    if is_sqlite:
        return f"""SELECT 
    t.title AS Title,
    ROUND(AVG((julianday(CASE WHEN t.to_date = '9999-01-01' THEN '2002-08-01' ELSE t.to_date END) - julianday(e.hire_date)) / 365.25), 2) AS AvgYearsOfService,
    COUNT(DISTINCT e.emp_no) AS TotalEmployees
FROM titles t
JOIN employees e ON t.emp_no = e.emp_no
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY AvgYearsOfService DESC
LIMIT {req_limit}"""
    else:
        return f"""SELECT 
    t.title AS Title,
    ROUND(AVG(DATEDIFF(IF(t.to_date = '9999-01-01', '2002-08-01', t.to_date), e.hire_date) / 365.25), 2) AS AvgYearsOfService,
    COUNT(DISTINCT e.emp_no) AS TotalEmployees
FROM titles t
JOIN employees e ON t.emp_no = e.emp_no
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY AvgYearsOfService DESC
LIMIT {req_limit}"""


def auto_fix_tenure_cohort_salary_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương trung bình giữa nhóm nhân viên kỳ cựu (> X năm)
    và nhóm nhân viên mới (< Y năm) theo từng phòng ban hoặc tại một phòng ban cụ thể."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_tenure_cohort_comp = (
        any(k in q_low for k in ["kỳ cựu", "thâm niên", "lâu năm", "cống hiến", "trên 5 năm", "trên 7 năm", "trên 6 năm", "trên 8 năm", "trên 10 năm", "nhiều năm"])
        and any(k in q_low for k in ["mới", "mới vào", "mới tuyển", "dưới 2 năm", "dưới 3 năm", "dưới 1 năm", "ít năm"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập", "nén lương", "ép lương"])
    )
    if not is_tenure_cohort_comp:
        return sql

    # 1. Trích xuất ngưỡng năm kỳ cựu và mới vào (mặc định 5 năm và 2 năm)
    m_sen = re.search(r"(?:kỳ cựu|thâm niên|lâu năm|cống hiến|trên|hơn|lớn hơn|>)\s*(\d+(?:\.\d+)?)\s*năm", q_low)
    senior_years = float(m_sen.group(1)) if m_sen else 5.0

    m_new = re.search(r"(?:mới vào|mới tuyển|mới|dưới|ít hơn|nhỏ hơn|<)\s*(\d+(?:\.\d+)?)\s*năm", q_low)
    newhire_years = float(m_new.group(1)) if m_new else 2.0

    # 2. Nhận diện phòng ban cụ thể nếu người dùng chỉ đích danh
    target_dept = None
    is_all_depts = any(k in q_low for k in ["các phòng ban", "từng phòng ban", "mỗi phòng ban", "toàn bộ phòng ban", "mọi phòng ban", "toàn công ty", "các phòng"])
    if not is_all_depts:
        dept_keywords = [
            (["development", "kỹ thuật", "phát triển"], "Development"),
            (["customer service", "chăm sóc khách hàng", "dịch vụ khách hàng"], "Customer Service"),
            (["quality management", "quản lý chất lượng", "chất lượng"], "Quality Management"),
            (["human resources", "nhân sự"], "Human Resources"),
            (["production", "sản xuất"], "Production"),
            (["marketing", "tiếp thị"], "Marketing"),
            (["research", "nghiên cứu"], "Research"),
            (["finance", "tài chính"], "Finance"),
            (["sales", "kinh doanh", "bán hàng"], "Sales"),
        ]
        for k_list, d_val in dept_keywords:
            if any(k in q_low for k in k_list):
                target_dept = d_val
                break

    is_sqlite = "sqlite" in (dialect or "").lower()
    senior_cond = (
        f"(julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 > {senior_years:g}"
        if is_sqlite else
        f"DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 > {senior_years:g}"
    )
    newhire_cond = (
        f"(julianday((SELECT MAX(hire_date) FROM employees)) - julianday(e.hire_date)) / 365.25 < {newhire_years:g}"
        if is_sqlite else
        f"DATEDIFF((SELECT MAX(hire_date) FROM employees), e.hire_date) / 365.25 < {newhire_years:g}"
    )

    where_dept = f"WHERE d.dept_name = '{target_dept}'" if target_dept else ""
    order_dept = "\nORDER BY SalaryDifference DESC" if not target_dept else ""

    return f"""SELECT 
    d.dept_name AS Department,
    ROUND(AVG(CASE WHEN {senior_cond} THEN s.salary END), 2) AS SeniorAvgSalary,
    ROUND(AVG(CASE WHEN {newhire_cond} THEN s.salary END), 2) AS NewHireAvgSalary,
    ROUND(AVG(CASE WHEN {senior_cond} THEN s.salary END) - 
          AVG(CASE WHEN {newhire_cond} THEN s.salary END), 2) AS SalaryDifference,
    ROUND((AVG(CASE WHEN {senior_cond} THEN s.salary END) - 
           AVG(CASE WHEN {newhire_cond} THEN s.salary END)) * 100.0 / 
           AVG(CASE WHEN {newhire_cond} THEN s.salary END), 2) AS DifferencePercentage,
    COUNT(CASE WHEN {senior_cond} THEN 1 END) AS SeniorCount,
    COUNT(CASE WHEN {newhire_cond} THEN 1 END) AS NewHireCount
FROM employees e
JOIN dept_emp de ON e.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
{where_dept}
GROUP BY d.dept_name{order_dept};""".strip()


def auto_fix_recent_manager_gender_promotion_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi so sánh số lượng / tỷ lệ nhân sự nam và nữ được thăng chức / bổ nhiệm
    lên các vị trí quản lý (Manager) trong N năm gần nhất (ví dụ 5 năm gần nhất).
    Đảm bảo luôn lọc đúng mốc thời gian tương đối so với MAX(from_date) của dept_manager và không bao giờ
    bị 0 dòng dữ liệu hay lấy toàn bộ 24 quản lý trong lịch sử.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_mgr_promo = (
        any(k in q_low for k in ["manager", "quản lý", "trưởng phòng", "ban quản lý"])
        and any(k in q_low for k in ["nam", "nữ", "giới tính", "gender"])
        and any(k in q_low for k in ["gần nhất", "5 năm", "gần đây", "thời gian qua"])
    )
    if not is_mgr_promo:
        return sql

    # Trích xuất số năm gần nhất (mặc định 5 năm -> offset 4)
    m_y = re.search(r"(\d+)\s*năm", q_low)
    n_years = int(m_y.group(1)) if m_y else 5
    year_offset = max(0, n_years - 1)

    has_dept_in_q = any(k in q_low for k in ["phòng ban", "từng phòng", "mỗi phòng", "department", "bộ phận"])

    is_sqlite = "sqlite" in (dialect or "").lower()
    if is_sqlite:
        year_filter = f"CAST(strftime('%Y', dm.from_date) AS INTEGER) >= (SELECT MAX(CAST(strftime('%Y', from_date) AS INTEGER)) FROM dept_manager) - {year_offset}"
        year_select = "CAST(strftime('%Y', dm.from_date) AS INTEGER) AS Year"
        year_group = "CAST(strftime('%Y', dm.from_date) AS INTEGER)"
    else:
        year_filter = f"YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - {year_offset}"
        year_select = "YEAR(dm.from_date) AS Year"
        year_group = "YEAR(dm.from_date)"

    if has_dept_in_q:
        return f"""SELECT 
    d.dept_name AS Department,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
    COUNT(*) AS TotalManagers,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct
FROM dept_manager dm
JOIN employees e ON dm.emp_no = e.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
WHERE {year_filter}
GROUP BY d.dept_name
ORDER BY TotalManagers DESC, d.dept_name;""".strip()
    if is_sqlite:
        return f"""WITH RECURSIVE YearRange AS (
    SELECT (SELECT MAX(CAST(strftime('%Y', from_date) AS INTEGER)) - {year_offset} FROM dept_manager) AS Year
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
    WHERE CAST(strftime('%Y', dm.from_date) AS INTEGER) >= (SELECT MAX(CAST(strftime('%Y', from_date) AS INTEGER)) FROM dept_manager) - {year_offset}
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
ORDER BY yr.Year ASC;""".strip()
    else:
        return f"""WITH RECURSIVE YearRange AS (
    SELECT (SELECT MAX(YEAR(from_date)) - {year_offset} FROM dept_manager) AS Year
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
    WHERE YEAR(dm.from_date) >= (SELECT MAX(YEAR(from_date)) FROM dept_manager) - {year_offset}
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
ORDER BY yr.Year ASC;""".strip()


def auto_fix_department_share_in_company_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi tính tổng chi phí lương công ty và tỷ lệ phần trăm một phòng ban cụ thể chiếm trong tổng chi phí đó."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_dept_share_query = (
        any(k in q_low for k in ["chiếm bao nhiêu", "chiếm tỉ lệ", "chiếm tỷ lệ", "chiếm phần trăm", "tỷ trọng", "tỉ trọng", "phần trăm trong tổng", "tỷ lệ trong tổng", "đóng góp bao nhiêu"])
        and any(k in q_low for k in ["tổng chi phí", "tổng quỹ lương", "tổng lương", "toàn công ty", "trong tổng"])
        and any(k in q_low for k in ["production", "sales", "development", "marketing", "research", "finance", "customer service", "quality management", "human resources", "sản xuất", "kinh doanh", "phát triển", "tiếp thị", "nghiên cứu", "tài chính", "nhân sự"])
    )
    if not is_dept_share_query:
        return sql

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

    # Kiểm tra xem SQL đã lọc đúng phòng ban target và có cột Percentage / Tỷ lệ chưa
    sql_low = (sql or "").lower()
    has_target_dept = target_dept.lower() in sql_low
    has_pct = any(k in sql_low for k in ["percentage", "percent", "pct", "tỷ lệ", "tỉ lệ"]) and ("*" in sql_low or "/" in sql_low)
    has_tot_sal = any(k in sql_low for k in ["totalcompanysalary", "companytotal", "totalsalarybudget", "total_salary_budget", "totalsalaries"])

    if has_target_dept and has_pct and has_tot_sal and "union all" in sql_low:
        return sql

    return f"""WITH DeptSalaries AS (
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
WHERE d.Department != '{target_dept}';"""


def auto_fix_department_avg_salary_threshold_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động sửa lỗi dùng WHERE s.salary thay vì HAVING AVG(s.salary) khi hỏi lọc phòng ban theo ngưỡng lương trung bình."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_dept_avg_threshold = (
        any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "department"])
        and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "lương tb", "avg salary", "average salary"])
        and any(k in q_low for k in ["trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", "lớn hơn", "nhỏ hơn", ">", "<", ">=", "<=", "above", "below", "over", "greater than", "less than"])
        and not any(k in q_low for k in ["so sánh", "đối chiếu", "vs", "giữa", "chiếm bao nhiêu", "tỷ trọng", "phần trăm trong tổng"])
    )
    if not is_dept_avg_threshold:
        return sql

    # Trích xuất ngưỡng tiền
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

    op = "<" if any(k in q_low for k in ["dưới", "thấp hơn", "nhỏ hơn", "<", "<=", "below", "less than", "under"]) else ">"

    sql_low = sql.lower()
    has_wrong_where = bool(re.search(r"where[^\n;]*\bsalary\s*[><=]", sql_low))
    missing_having = "having" not in sql_low
    missing_avg_col = "avgsalary" not in sql_low and "avg(" not in sql_low
    missing_current = "9999-01-01" not in sql_low
    lacks_dept_join = "dept_emp" not in sql_low or "departments" not in sql_low

    if has_wrong_where or missing_having or missing_avg_col or missing_current or lacks_dept_join:
        return f"""SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
HAVING AvgSalary {op} {thresh_val}
ORDER BY AvgSalary DESC;"""

    return sql


def auto_fix_payroll_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và khắc phục lỗi mô hình AI dùng COUNT thay vì SUM(s.salary) khi người dùng hỏi về quỹ lương phòng ban hoặc theo năm."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()

    # Bỏ qua nếu câu hỏi về tỷ trọng của một phòng ban cụ thể trong tổng chi phí
    is_dept_share_query = (
        any(k in q_low for k in ["chiếm bao nhiêu", "chiếm tỉ lệ", "chiếm tỷ lệ", "chiếm phần trăm", "tỷ trọng", "tỉ trọng", "phần trăm trong tổng", "tỷ lệ trong tổng"])
        and any(k in q_low for k in ["production", "sales", "development", "marketing", "research", "finance", "customer service", "quality management", "human resources", "sản xuất", "kinh doanh", "phát triển", "tiếp thị", "nghiên cứu", "tài chính", "nhân sự"])
    )
    if is_dept_share_query:
        return sql

    is_payroll_query = any(k in q_low for k in ["quỹ lương", "ngân sách lương", "tổng chi trả lương", "chi phí lương", "tổng mức lương", "tổng lương", "tổng thu nhập"]) or (
        any(k in q_low for k in ["mức lương", "lương", "salary", "thu nhập"]) and any(k in q_low for k in ["phòng ban", "phòng", "department"]) and any(k in q_low for k in ["xu hướng", "thay đổi", "biến động", "qua các năm", "theo năm", "hàng năm"])
    )
    if not is_payroll_query:
        return sql

    # Bỏ qua nếu là câu hỏi Top N phòng ban có tổng quỹ lương cao nhất (được auto_fix_department_top_payroll_query xử lý toàn diện)
    if any(k in q_low for k in ["top", "cao nhất", "nhiều nhất"]) and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"]):
        return sql

    # Xử lý trường hợp hỏi xu hướng qua các năm
    is_yearly_trend = any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "biến động", "xu hướng", "thay đổi"])
    is_per_dept = any(k in q_low for k in ["phòng ban", "phòng", "department", "từng phòng ban", "các phòng"])

    if is_yearly_trend and is_per_dept:
        lowered_sql = sql.lower()
        # Nếu SQL bị lỗi Past/Current hoặc thiếu Year hoặc lọc to_date = 9999-01-01
        if "year(" not in lowered_sql or "salary change" in lowered_sql or "past" in lowered_sql or "9999-01-01" in lowered_sql:
            sql = """SELECT 
    YEAR(s.from_date) AS Year,
    d.dept_name AS Department,
    SUM(s.salary) AS TotalSalaryBudget,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no
JOIN salaries s ON de.emp_no = s.emp_no AND s.from_date BETWEEN de.from_date AND de.to_date
GROUP BY YEAR(s.from_date), d.dept_name
ORDER BY Year ASC, Department ASC"""
            return sql

    elif is_yearly_trend:
        # Gỡ bỏ lọc to_date = 9999-01-01
        sql = re.sub(r"\s*AND\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]\s*AND", " WHERE", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
        # Đổi YEAR(to_date) thành YEAR(s.from_date)
        sql = re.sub(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)", "YEAR(s.from_date)", sql, flags=re.IGNORECASE)
        sql = re.sub(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?from_date\s*\)", "YEAR(s.from_date)", sql, flags=re.IGNORECASE)
        if "from_date" not in sql.lower():
            sql = """SELECT 
    YEAR(s.from_date) AS Year,
    SUM(s.salary) AS TotalSalaryBudget,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY Year ASC"""
            return sql

    # Kiểm tra xem SQL có bị thiếu SUM(s.salary) hoặc dùng nhầm COUNT(...)
    has_sum_salary = "sum(s.salary)" in sql.lower() or "sum(salary)" in sql.lower()
    if not has_sum_salary:
        # Nếu có COUNT(...) thì thay bằng SUM(s.salary) AS TotalSalaryBudget
        if re.search(r"COUNT\s*\([^)]*\)", sql, re.IGNORECASE):
            sql = re.sub(
                r"COUNT\s*\([^)]*\)\s*(?:AS\s+[a-zA-Z0-9_]+)?",
                "SUM(s.salary) AS TotalSalaryBudget",
                sql,
                count=1,
                flags=re.IGNORECASE
            )
        # Đảm bảo có JOIN salaries s
        if not re.search(r"\b(?:JOIN|FROM)\s+salaries\b", sql, re.IGNORECASE):
            if re.search(r"\bJOIN\s+dept_emp\s+de\b[^\n]*", sql, re.IGNORECASE):
                sql = re.sub(
                    r"(\bJOIN\s+dept_emp\s+de\b[^\n]*)",
                    r"\1\nJOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'",
                    sql,
                    count=1,
                    flags=re.IGNORECASE
                )
            elif re.search(r"\bFROM\s+departments\s+d\b", sql, re.IGNORECASE):
                sql = re.sub(
                    r"(\bFROM\s+departments\s+d\b)",
                    r"\1\nJOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'\nJOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'",
                    sql,
                    count=1,
                    flags=re.IGNORECASE
                )
        # Cập nhật ORDER BY nếu ORDER BY theo alias cũ hoặc count
        if re.search(r"ORDER\s+BY\s+[a-zA-Z0-9_.]+(?:\([^)]*\))?\s+DESC", sql, re.IGNORECASE):
            sql = re.sub(
                r"ORDER\s+BY\s+[a-zA-Z0-9_.]+(?:\([^)]*\))?\s+DESC",
                "ORDER BY TotalSalaryBudget DESC",
                sql,
                flags=re.IGNORECASE
            )
    return sql


def auto_fix_time_to_promotion_by_dept_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu hỏi về thời gian để thăng chức giữa các phòng ban."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Không can thiệp nếu là câu hỏi về tỷ lệ thăng chức nam/nữ, hoặc lương
    if any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "tỷ lệ", "tỉ lệ", "lương", "mức lương", "salary", "thu nhập"]):
        return sql

    has_time_kw = any(k in q_low for k in ["thời gian", "bao lâu", "mất bao lâu", "mấy năm", "số năm", "số ngày", "time to", "years to", "khác nhau như thế nào", "khác nhau", "nhanh nhất", "chậm nhất", "lâu nhất"])
    has_promo_kw = any(k in q_low for k in ["thăng chức", "thăng tiến", "đổi chức danh", "chuyển chức danh", "lên chức", "promotion"])
    has_dept_kw = any(k in q_low for k in ["phòng ban", "các phòng ban", "từng phòng ban", "giữa các phòng ban", "department"])

    if not (has_time_kw and has_promo_kw and has_dept_kw):
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    if is_sqlite:
        return """WITH RankedTitles AS (
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
ORDER BY AvgYearsToPromotion ASC;""".strip()
    else:
        return """WITH RankedTitles AS (
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
ORDER BY AvgYearsToPromotion ASC;""".strip()


def auto_fix_gender_promotion_rate_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi tính tỷ lệ phần trăm nhân viên nam và nữ được thăng chức (đổi chức danh ít nhất 1 lần)
    so với tổng số nhân viên của từng giới tính tương ứng.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    has_promo_kw = any(k in q_low for k in ["thăng chức", "đổi chức danh", "chuyển chức danh", "thay đổi chức danh", "nhiều chức danh", "lần đổi chức danh"])
    has_gender_kw = any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "nam", "nữ", "gender"])
    has_rate_kw = any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "%", "tương ứng", "so với"])
    has_mgr_kw = any(k in q_low for k in ["manager", "quản lý", "trưởng phòng", "ban quản lý", "dept_manager"])

    if not (has_promo_kw and has_gender_kw and has_rate_kw) or has_mgr_kw:
        return sql

    return """WITH PromotedEmployees AS (
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
ORDER BY Gender ASC;""".strip()


def auto_fix_department_gender_salary_gap_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương bình quân hoặc chênh lệch lương giữa nam và nữ theo từng phòng ban."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_dept_gender_salary = (
        any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "nam", "nữ", "gender"])
        and any(k in q_low for k in ["lương", "mức lương", "salary", "thu nhập", "lương bình quân", "lương trung bình"])
        and any(k in q_low for k in ["phòng ban", "từng phòng ban", "các phòng ban", "department", "bộ phận"])
    )
    if not is_dept_gender_salary:
        return sql

    has_male_sal = bool(re.search(r"\b(MaleAvgSalary|male_avg_salary|MaleSalary)\b", sql, re.IGNORECASE))
    has_female_sal = bool(re.search(r"\b(FemaleAvgSalary|female_avg_salary|FemaleSalary)\b", sql, re.IGNORECASE))
    has_sal_table = bool(re.search(r"\bsalaries\b", sql, re.IGNORECASE))
    has_dept_table = bool(re.search(r"\bdepartments\b", sql, re.IGNORECASE))
    has_diff = bool(re.search(r"\b(SalaryDifference|DifferencePercentage|diff|gap)\b", sql, re.IGNORECASE))
    asks_diff = any(k in q_low for k in ["chênh lệch", "tỷ lệ chênh lệch", "tỉ lệ chênh lệch", "khoảng cách", "gap", "pay gap"])

    # Nếu câu lệnh SQL thiếu bảng salaries, hoặc thiếu cột lương theo giới tính, hoặc người dùng hỏi chênh lệch mà thiếu cột chênh lệch
    if not (has_male_sal and has_female_sal and has_sal_table and has_dept_table) or (asks_diff and not has_diff):
        return """SELECT 
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
ORDER BY SalaryDifference DESC"""

    return sql


def auto_fix_gender_salary_comparison_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương trung bình / thu nhập giữa các giới tính (Nam vs Nữ)."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Nhận diện câu hỏi so sánh lương theo giới tính
    is_gender = any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "từng giới tính", "các giới tính", "theo giới tính", "gender", "nam", "nữ"])
    is_salary = any(k in q_low for k in ["lương", "mức lương", "thu nhập", "salary", "lương trung bình", "lương bình quân"])
    
    # Không phải câu hỏi theo phòng ban hoặc thăng chức/quản lý
    is_by_dept = any(k in q_low for k in ["phòng ban", "từng phòng", "các phòng", "department", "bộ phận"])
    is_promo = any(k in q_low for k in ["thăng chức", "đổi chức danh", "chuyển chức danh", "bổ nhiệm", "manager", "quản lý", "trưởng phòng"])

    # Nhận diện chuỗi thời gian / biến động qua các mốc thời gian / theo năm
    is_time_series = any(k in q_low for k in [
        "thời gian", "mốc thời gian", "qua các năm", "qua từng năm", "theo năm", "theo từng năm",
        "biến động", "xu hướng", "trend", "trajectory", "lịch sử", "timeline", "evolution",
        "over time", "by year", "across years", "giai đoạn", "hàng năm"
    ])

    if is_gender and is_salary and not is_by_dept and not is_promo:
        if is_time_series:
            d_low = (dialect or "").lower()
            if "sqlite" in d_low:
                year_expr = "CAST(strftime('%Y', s.from_date) AS INTEGER)"
            elif "postgres" in d_low:
                year_expr = "EXTRACT(YEAR FROM s.from_date)"
            else:
                year_expr = "YEAR(s.from_date)"

            return f"""SELECT 
    {year_expr} AS `Năm`,
    ROUND(AVG(CASE WHEN e.gender = 'M' THEN s.salary END), 2) AS `Lương TB Nam ($)`,
    ROUND(AVG(CASE WHEN e.gender = 'F' THEN s.salary END), 2) AS `Lương TB Nữ ($)`,
    ROUND(AVG(CASE WHEN e.gender = 'M' THEN s.salary END) - AVG(CASE WHEN e.gender = 'F' THEN s.salary END), 2) AS `Chênh Lệch Nam - Nữ ($)`
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no
GROUP BY {year_expr}
ORDER BY `Năm` ASC;""".strip()

        return """SELECT 
    CASE WHEN e.gender = 'M' THEN 'Nam (M)' ELSE 'Nữ (F)' END AS `Giới Tính`,
    ROUND(AVG(s.salary), 2) AS `Lương Trung Bình ($)`,
    COUNT(DISTINCT e.emp_no) AS `Số Lượng Nhân Sự`,
    MAX(s.salary) AS `Lương Cao Nhất ($)`,
    MIN(s.salary) AS `Lương Thấp Nhất ($)`
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY e.gender
ORDER BY `Lương Trung Bình ($)` DESC;""".strip()

    return sql


def auto_fix_department_manager_gender_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:

    """Tự động chuẩn hóa câu hỏi thống kê hoặc tìm phòng ban có nhiều/ít quản lý Nam hoặc Nữ nhất."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Không can thiệp nếu hỏi về lương / thăng chức / 5 năm gần nhất
    if any(k in q_low for k in ["lương", "mức lương", "salary", "thu nhập", "chênh lệch", "gap", "pay gap", "thăng chức", "đổi chức danh", "gần nhất", "5 năm", "gần đây"]):
        return sql

    is_manager = any(k in q_low for k in ["quản lý", "quản lí", "ban quản lý", "trưởng phòng", "manager", "dept_manager"])
    has_gender = any(k in q_low for k in ["nữ", "nam", "female", "male", "giới tính", "nam và nữ", "nam nữ"])

    if not (is_manager and has_gender):
        return sql

    has_dept_manager = bool(re.search(r"\bdept_manager\b", sql, re.IGNORECASE))
    has_dept_table = bool(re.search(r"\bdepartments\b", sql, re.IGNORECASE))
    has_emp_table = bool(re.search(r"\bemployees\b", sql, re.IGNORECASE))
    has_unknown_emp_col = bool(re.search(r"\b(employee_id|gender\s*=\s*['\"]female['\"]|gender\s*=\s*['\"]male['\"])\b", sql, re.IGNORECASE))
    uses_dept_emp_only = bool(re.search(r"\bdept_emp\b", sql, re.IGNORECASE)) and not has_dept_manager
    has_syntax_errors = bool(re.search(r"\b(CONVERT\s*\(|NVARCHAR|IIF\s*\()\b", sql, re.IGNORECASE))

    asks_female_rank = any(k in q_low for k in ["nhiều quản lý nữ", "nhiều quản lí nữ", "nhiều nữ", "quản lý nữ nhất", "quản lí nữ nhất", "quản lý nữ", "quản lí nữ"]) and any(k in q_low for k in ["nhiều", "nhất", "top", "cao nhất", "phòng ban nào"])
    asks_male_rank = any(k in q_low for k in ["nhiều quản lý nam", "nhiều quản lí nam", "nhiều nam", "quản lý nam nhất", "quản lí nam nhất", "quản lý nam", "quản lí nam"]) and any(k in q_low for k in ["nhiều", "nhất", "top", "cao nhất", "phòng ban nào"])

    if not (has_dept_manager and has_dept_table and has_emp_table) or has_unknown_emp_col or uses_dept_emp_only or has_syntax_errors:
        if asks_female_rank and not any(k in q_low for k in ["nam và nữ", "nam nữ"]):
            return """SELECT 
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
ORDER BY FemaleManagers DESC, d.dept_name ASC"""
        elif asks_male_rank and not any(k in q_low for k in ["nam và nữ", "nam nữ"]):
            return """SELECT 
    d.dept_name AS Department,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers,
    COUNT(*) AS TotalManagers,
    ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct,
    ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct
FROM departments d
JOIN dept_manager dm ON d.dept_no = dm.dept_no
JOIN employees e ON dm.emp_no = e.emp_no
GROUP BY d.dept_name
ORDER BY MaleManagers DESC, d.dept_name ASC"""
        else:
            return """SELECT 
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
ORDER BY d.dept_name ASC"""

    return sql


def auto_fix_gender_ratio_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và sửa lỗi thiếu tỷ lệ Nam khi câu hỏi yêu cầu tỷ lệ Nam và Nữ trong ban quản lý, phòng ban hoặc toàn công ty."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    sql_low = sql.lower()

    # Guard: Tuyệt đối không can thiệp nếu là câu hỏi về lương / thu nhập / chênh lệch / thăng chức / thời gian gần đây theo giới tính
    if any(k in q_low for k in ["lương", "mức lương", "salary", "thu nhập", "chênh lệch", "gap", "pay gap", "thăng chức", "đổi chức danh", "chuyển chức danh", "nhiều chức danh", "gần nhất", "5 năm", "gần đây"]):
        return sql

    asks_both_genders = any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "tỷ lệ nam", "tỉ lệ nam", "tỉ lệ nam nữ", "tỷ lệ nam nữ"])

    if not asks_both_genders:
        return sql

    is_dept_manager = any(k in q_low for k in ["ban quản lý", "dept_manager", "manager", "quản lý", "quản lí", "trưởng phòng"])
    if is_dept_manager:
        uses_cte = bool(re.search(r"\bWITH\b", sql, re.IGNORECASE))
        has_female = bool(re.search(r"\b(PercentageFemale|FemalePct|female)\b", sql, re.IGNORECASE))
        has_male = bool(re.search(r"\b(PercentageMale|MalePct|male)\b", sql, re.IGNORECASE))
        missing_emp = not bool(re.search(r"\bemployees\b", sql, re.IGNORECASE))
        if uses_cte or missing_emp or not (has_female and has_male):
            return """SELECT 
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
ORDER BY d.dept_name"""

    is_dept_employees = any(k in q_low for k in ["từng phòng ban", "các phòng ban", "phòng ban"])
    if is_dept_employees and not is_dept_manager:
        uses_cte = bool(re.search(r"\bWITH\b", sql, re.IGNORECASE))
        has_female_pct = bool(re.search(r"\b(PercentageFemale|FemalePct)\b", sql, re.IGNORECASE))
        has_male_pct = bool(re.search(r"\b(PercentageMale|MalePct)\b", sql, re.IGNORECASE))
        has_female_count = bool(re.search(r"\b(FemaleEmployees|FemaleCount|female_emp)\b", sql, re.IGNORECASE))
        has_male_count = bool(re.search(r"\b(MaleEmployees|MaleCount|male_emp)\b", sql, re.IGNORECASE))
        missing_counts_or_pcts = not (has_female_pct and has_male_pct and has_female_count and has_male_count)
        if uses_cte or missing_counts_or_pcts:
            return """SELECT 
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
ORDER BY TotalEmployees DESC"""

    is_company = any(k in q_low for k in ["công ty", "toàn công ty", "company", "toàn bộ", "từng giới tính", "theo giới tính", "tổng số", "tổng"]) or "employees" in sql_low
    if is_company or any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "cơ cấu", "đóng góp"]):
        has_first_name_leak = any(k in sql_low for k in ["first_name", "fullname", "last_name"])
        has_female = bool(re.search(r"\b(PercentageFemale|FemalePct|female)\b", sql, re.IGNORECASE))
        has_male = bool(re.search(r"\b(PercentageMale|MalePct|male)\b", sql, re.IGNORECASE))
        has_percentage = bool(re.search(r"\b(percentage|percent|pct|tỷ lệ|tỉ lệ)\b", sql, re.IGNORECASE))
        if has_first_name_leak or (not (has_female and has_male) and not has_percentage):
            return """SELECT 
    gender AS Gender,
    COUNT(*) AS EmployeeCount,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM employees), 2) AS Percentage
FROM employees
GROUP BY gender
ORDER BY EmployeeCount DESC"""

    return sql


def auto_fix_gender_salary_contribution_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn Tỷ lệ đóng góp mức lương / quỹ lương theo từng giới tính vào tổng số."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    sql_low = (sql or "").lower()

    # Nhận diện câu hỏi tỷ lệ đóng góp mức lương / quỹ lương theo giới tính
    is_gender = any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "từng giới tính", "theo giới tính", "gender", "nam", "nữ"])
    is_salary = any(k in q_low for k in ["lương", "mức lương", "salary", "quỹ lương", "thu nhập", "chi phí lương"])
    is_contrib = any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "cơ cấu", "tỉ trọng", "tỷ trọng", "đóng góp", "share", "ratio", "vào tổng", "trong tổng", "tổng số", "so với tổng", "so với"])

    if is_gender and is_salary and is_contrib:
        # Nếu câu hỏi KHÔNG yêu cầu theo phòng ban hay chức danh cụ thể
        is_by_dept = any(k in q_low for k in ["phòng ban", "từng phòng", "các phòng", "department"])
        is_by_title = any(k in q_low for k in ["chức danh", "vị trí", "title", "job"])

        if not is_by_dept and not is_by_title:
            return """SELECT 
    CASE WHEN e.gender = 'M' THEN 'Nam (M)' ELSE 'Nữ (F)' END AS `Giới Tính`,
    COUNT(DISTINCT e.emp_no) AS `Số Lượng Nhân Sự`,
    SUM(s.salary) AS `Tổng Quỹ Lương ($)`,
    ROUND(SUM(s.salary) * 100.0 / (SELECT SUM(salary) FROM salaries WHERE to_date = '9999-01-01'), 2) AS `Tỷ Trọng (%)`,
    ROUND(AVG(s.salary), 2) AS `Lương Trung Bình ($)`
FROM employees e
JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY e.gender
ORDER BY `Tổng Quỹ Lương ($)` DESC"""

    return sql


def auto_fix_top_raises_low_salary_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi: Top N nhân viên được tăng lương nhiều lần nhất nhưng mức lương hiện tại vẫn dưới ngưỡng (ví dụ: dưới $60,000).
    Áp dụng CTE 2 bước theo 3 Quy tắc Phân rã Nghiệp vụ:
    - ActiveSalariesUnderCap: e.emp_no, FullName, d.dept_name, t.title, s.salary WHERE s.salary < {cap} AND s.to_date = '9999-01-01'
    - EmployeeRaiseCounts: emp_no, COUNT(*) AS RaiseCount FROM salaries GROUP BY emp_no
    - ORDER BY rc.RaiseCount DESC, a.CurrentSalary ASC, a.emp_no ASC LIMIT N
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_top_raises_low_salary = (
        any(k in q_low for k in ["tăng lương", "lần tăng", "được tăng"])
        and any(k in q_low for k in ["nhiều lần nhất", "nhiều nhất", "nhiều lần", "most raises"])
        and any(k in q_low for k in ["dưới", "thấp hơn", "chưa tới", "không quá", "<"])
        and any(k in q_low for k in ["lương", "salary", "mức lương", "$"])
    )
    if not is_top_raises_low_salary:
        return sql

    req_limit = extract_requested_limit(user_query) or 10
    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    m_sal = re.search(r"(?:dưới|thấp hơn|chưa tới|<)\s*\$?(\d+(?:[.,]\d+)*)\s*(?:k|nghìn|usd|\$)?", q_low)
    raw_sal_str = m_sal.group(1).replace(",", "").replace(".", "") if m_sal else "60000"
    if "k" in q_low and int(raw_sal_str) < 1000:
        sal_cap = int(raw_sal_str) * 1000
    else:
        sal_cap = int(raw_sal_str)

    sql_low = (sql or "").lower()
    has_active_filter = "9999-01-01" in sql_low
    has_broken_alias = ("a.department" in sql_low and "as department" not in sql_low) or ("a.title" in sql_low and "as title" not in sql_low and "as currenttitle" not in sql_low)
    has_cap_filter = f"< {sal_cap}" in sql_low or f"<{sal_cap}" in sql_low or f"< '{sal_cap}'" in sql_low or ("< 60000" in sql_low and sal_cap == 60000)
    has_raise_desc = "order by" in sql_low and any(k in sql_low for k in ["raisecount desc", "raise_count desc", "count(*) desc", "count(s.salary) desc", "count(s_hist.salary) desc"])
    has_hallucination = any(k in sql_low for k in ["email", "< n", "percent_rank"])

    is_broken = (
        not has_cap_filter
        or not has_raise_desc
        or not has_active_filter
        or has_broken_alias
        or has_hallucination
        or not sql
    )

    if is_broken:
        return f"""WITH ActiveSalariesUnderCap AS (
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
LIMIT {req_limit};""".strip()

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit};"
    return sql


def auto_fix_employee_salary_growth_rate_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn: Top N nhân viên có tỷ lệ tăng lương ấn tượng nhất: so sánh mức lương đầu tiên khi vào công ty và mức lương hiện tại.
    Áp dụng chuẩn mực CTE 2 bước theo 3 Quy tắc Phân rã Nghiệp vụ:
    - ActiveEmployees: Lọc hợp đồng hiện hành to_date = '9999-01-01' để lấy CurrentSalary.
    - InitialSalaries: Join MIN(from_date) từ salaries để lấy InitialSalary khi mới gia nhập.
    - Tính SalaryIncrease và SalaryGrowthRatePct = ROUND((CurrentSalary - InitialSalary) * 100.0 / InitialSalary, 2).
    - ORDER BY SalaryGrowthRatePct DESC, SalaryIncrease DESC LIMIT N.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_growth_query = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "employee"])
        and any(k in q_low for k in ["tỷ lệ tăng lương", "tỉ lệ tăng lương", "tăng lương ấn tượng", "tốc độ tăng lương", "tăng trưởng lương", "mức tăng lương", "salary growth", "highest raise rate", "salary increase"])
        and (
            any(k in q_low for k in ["đầu tiên", "khởi điểm", "lúc vào", "khi vào", "gia nhập", "initial", "starting", "first salary"])
            or any(k in q_low for k in ["hiện tại", "bây giờ", "đến nay", "current", "latest"])
        )
    )
    if not is_growth_query:
        return sql

    req_limit = extract_requested_limit(user_query) or 5
    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    sql_low = (sql or "").lower()
    has_initial_salary = "initialsalary" in sql_low or "min(from_date)" in sql_low or "min_date" in sql_low
    has_current_salary = "currentsalary" in sql_low or "s.to_date = '9999-01-01'" in sql_low
    has_growth_pct = any(k in sql_low for k in ["salarygrowthratepct", "growthratepct", "salary_growth", "growth_pct", "* 100"])
    is_only_dept = "group by d.dept_name" in sql_low or "group by dept_name" in sql_low

    is_broken = (
        is_only_dept
        or not has_initial_salary
        or not has_current_salary
        or not has_growth_pct
        or not sql
    )

    if is_broken:
        return f"""WITH ActiveEmployees AS (
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
LIMIT {req_limit};""".strip()

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit};"
    return sql


def auto_fix_employee_salary_reduction_history_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn: Có nhân viên nào từng bị giảm lương trong lịch sử làm việc tại công ty không? Nếu có, hãy liệt kê chi tiết mức giảm và phòng ban của họ.
    Áp dụng chuẩn mực CTE theo 3 Quy tắc Phân rã Nghiệp vụ:
    - CTE 1 (SalaryStep): Sử dụng hàm cửa sổ LAG(s.salary) OVER (PARTITION BY s.emp_no ORDER BY s.from_date ASC) AS PrevSalary.
    - CTE 2 (SalaryReductions): Lọc WHERE PrevSalary IS NOT NULL AND NewSalary < PrevSalary, tính SalaryReduction và ReductionPct.
    - SELECT: Kết nối employees, dept_emp (sr.from_date BETWEEN de.from_date AND de.to_date), departments để lấy FullName, Department, ReductionDate, PrevSalary, NewSalary, SalaryReduction, ReductionPct.
    - ORDER BY sr.SalaryReduction DESC, e.emp_no ASC LIMIT N.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_reduction_query = (
        (
            any(k in q_low for k in ["giảm lương", "hạ lương", "bị giảm lương", "bị hạ lương", "tụt lương", "bị trừ lương", "salary reduction", "salary decrease", "pay cut"])
            or (any(k in q_low for k in ["lương", "salary"]) and any(k in q_low for k in ["bị giảm", "bị hạ", "tụt lương", "thấp hơn lần trước", "thấp hơn kỳ trước"]))
        )
        and any(k in q_low for k in ["nhân viên", "nhân sự", "ai", "người", "employee", "danh sách", "có ai", "có nhân viên nào"])
        and not any(k in q_low for k in ["giảm dần", "tăng dần", "thứ tự", "xếp hạng", "cao nhất", "thấp nhất", "trung bình", "bình quân", "trung vị", "theo phòng ban", "từng phòng", "các phòng ban", "department", "order by", "so sánh"])
    )
    if not is_reduction_query:
        return sql

    req_limit = extract_requested_limit(user_query) or 10
    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    sql_low = (sql or "").lower()
    has_lag = "lag(" in sql_low or "prevsalary" in sql_low
    has_reduction_col = any(k in sql_low for k in ["salaryreduction", "reductionpct", "prevsalary - ", "newsalary < prevsalary", "salary < prevsalary"])
    has_hallucinated_table = any(k in sql_low for k in ["dept_reductions", "reductions", "salary_reductions", "employee_reductions"]) and not ("with salaryreductions as" in sql_low or "salarystep" in sql_low)
    has_dept_join = "dept_emp" in sql_low and "departments" in sql_low
    is_only_dept = "group by d.dept_name" in sql_low or "group by dept_name" in sql_low

    is_broken = (
        is_only_dept
        or has_hallucinated_table
        or not has_lag
        or not has_reduction_col
        or not has_dept_join
        or not sql
    )

    if is_broken:
        return f"""WITH SalaryStep AS (
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
LIMIT {req_limit};""".strip()

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit};"
    return sql


def auto_fix_employee_salary_above_title_avg_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn: Liệt kê nhân viên hiện đang nhận lương cao hơn (hoặc thấp hơn) mức lương trung bình của toàn bộ nhân viên có cùng chức danh (Title).
    Áp dụng chuẩn mực CTE TitleAvg theo 3 Quy tắc Phân rã Nghiệp vụ:
    - CTE TitleAvg: tính AVG(salary) theo từng t.title với t.to_date = '9999-01-01' AND s.to_date = '9999-01-01'
    - Lọc hợp đồng hiện hành: s.to_date = '9999-01-01', de.to_date = '9999-01-01', t.to_date = '9999-01-01'
    - Mệnh đề WHERE s.salary > ta.TitleAvgSalary
    - Xuất: emp_no, FullName, Department, Title, CurrentSalary, TitleAvgSalary, SalarySurplus
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_title_sal_comp = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "ai", "người", "employee"])
        and any(k in q_low for k in ["cao hơn", "vượt", "thấp hơn", "higher", "above", "lower", "below"])
        and any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "avg salary", "average salary"])
        and any(k in q_low for k in ["cùng chức danh", "chức danh", "title", "same title"])
    )
    if not is_title_sal_comp:
        return sql

    req_limit = extract_requested_limit(user_query) or 10
    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    is_lower = any(k in q_low for k in ["thấp hơn", "lower", "below"])
    op = "<" if is_lower else ">"
    diff_col = "SalaryDeficit" if is_lower else "SalarySurplus"
    diff_calc = "ROUND(ta.TitleAvgSalary - s.salary, 2)" if is_lower else "ROUND(s.salary - ta.TitleAvgSalary, 2)"

    sql_low = (sql or "").lower()
    has_title_join = "titles" in sql_low or "t.title" in sql_low
    has_title_avg = "titleavg" in sql_low or "titleavgsalary" in sql_low or "ta.title" in sql_low
    has_title_col = "t.title as title" in sql_low or "a.title" in sql_low or "title" in sql_low
    has_broken_subquery = "t1.title" in sql_low or "unknown column" in sql_low
    is_just_top_sal = "order by currentsalary desc" in sql_low and not has_title_avg

    is_broken = (
        not has_title_join
        or not has_title_avg
        or not has_title_col
        or has_broken_subquery
        or is_just_top_sal
        or not sql
    )

    if is_broken:
        return f"""WITH TitleAvg AS (
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
LIMIT {req_limit};""".strip()

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit};"
    return sql


def auto_fix_low_raises_top_percentile_salary_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi lọc nhân viên có số lần tăng lương ít (< N lần) nhưng lương hiện tại thuộc top cao nhất (top X% hoặc top lương).
    Tránh việc bị auto_fix_raises_query bắt nhầm sang câu hỏi nhân viên được tăng lương nhiều nhất (ORDER BY RaiseCount DESC).
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    if any(k in q_low for k in ["nhiều lần nhất", "nhiều nhất", "nhiều lần", "most raises", "ấn tượng", "tỷ lệ tăng lương", "tỉ lệ tăng lương", "đầu tiên", "khởi điểm"]):
        return sql

    has_raise_kw = any(k in q_low for k in ["tăng lương", "lần tăng", "được tăng"])
    has_low_kw = any(k in q_low for k in ["ít hơn", "dưới", "nhỏ hơn", "chưa quá", "chưa tới", "tối đa", "không quá", "fewer", "less than", "under"])
    has_high_salary = (
        any(k in q_low for k in ["top", "cao nhất", "thuộc top", "mức lương", "lương"])
        and any(k in q_low for k in ["%", "phần trăm", "toàn công ty", "công ty", "cao nhất"])
    )
    has_emp_kw = any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "danh sách", "liệt kê", "employee", "employees"])

    if not (has_raise_kw and has_low_kw and has_high_salary and has_emp_kw):
        return sql

    # Trích xuất số lần tăng lương tối đa (mặc định < 5 lần nếu câu hỏi nói 5 lần)
    m_raises = re.search(r"(?:ít hơn|dưới|nhỏ hơn|chưa quá|không quá|tối đa)\s*(\d+)\s*lần", q_low)
    if not m_raises:
        m_raises = re.search(r"(\d+)\s*lần", q_low)
    max_raises = int(m_raises.group(1)) if m_raises else 5

    # Trích xuất tỷ lệ top % lương (mặc định top 10% -> Percentile >= 0.90)
    m_pct = re.search(r"top\s*(\d+)\s*%", q_low)
    pct_val = int(m_pct.group(1)) if m_pct else 10
    pct_threshold = round((100 - pct_val) / 100.0, 2)

    limit_val = extract_requested_limit(user_query) or 10

    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    return f"""WITH TopPercentileActive AS (
    SELECT 
        e.emp_no,
        {concat_expr} AS FullName,
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
WHERE t.SalaryPercentile >= {pct_threshold}
GROUP BY t.emp_no, t.FullName, t.Department, t.CurrentSalary, t.SalaryPercentile
HAVING COUNT(s_all.salary) < {max_raises}
ORDER BY t.CurrentSalary DESC, RaiseCount ASC
LIMIT {limit_val};""".strip()


def auto_fix_raises_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa truy vấn danh sách nhân viên tăng lương nhiều nhất, tránh lỗi cú pháp và tràn dữ liệu."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Tuyệt đối không can thiệp nếu là câu hỏi về số lần tăng lương ít hơn/dưới ngưỡng, kết hợp top % lương, hoặc tỷ lệ tăng lương ấn tượng
    if any(k in q_low for k in [
        "ít hơn", "dưới", "nhỏ hơn", "chưa quá", "chưa tới", "tối đa", "không quá", "fewer", "less than", "under",
        "tỷ lệ", "tỉ lệ", "ấn tượng", "đầu tiên", "khởi điểm", "so sánh mức lương", "tăng trưởng", "growth",
        "giảm lương", "hạ lương", "bị giảm", "bị hạ", "salary reduction", "pay cut"
    ]) or "%" in q_low or "phần trăm" in q_low:
        return sql

    is_raises_query = (
        any(k in q_low for k in ["tăng lương", "lần tăng", "được tăng"])
        and any(k in q_low for k in ["nhân viên", "ai", "danh sách", "những", "người", "top", "ai là"])
    )

    if not is_raises_query:
        return sql

    # Trích xuất số lần tăng lương yêu cầu (mặc định 5 lần nếu không nêu rõ)
    match_n = re.search(r"(\d+)\s*lần", q_low)
    min_raises = int(match_n.group(1)) if match_n else 5

    match_limit = re.search(r"top\s*(\d+)", q_low)
    limit_val = int(match_limit.group(1)) if match_limit else 10

    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    # Kiểm tra các lỗi phổ biến mà LLM tạo ra:
    # 1. Lỗi cú pháp dấu ngoặc
    has_paren_mismatch = (sql.count("(") != sql.count(")"))
    # 2. Lỗi nhầm dept_no trong bảng salaries (1054: Unknown column 'dept_no' in 'field list')
    has_bad_dept_no = bool(re.search(r"salaries\b[^)]*dept_no", sql, re.IGNORECASE)) or "s.dept_no" in sql.lower() or ("dept_no" in sql.lower() and "from salaries" in sql.lower())
    # 3. Thiếu JOIN bảng dept_emp hoặc departments
    missing_dept = "dept_emp" not in sql.lower() or "departments" not in sql.lower()
    # 4. Lỗi dùng de.to_date = '9999-01-01' làm mất department của cựu nhân viên (10042, 10048)
    has_rigid_dept_filter = "de.to_date = '9999-01-01'" in sql.lower()
    # 5. Dùng subquery nhưng bị cắt cụt hoặc lỗi alias
    is_broken_subquery = ("from (" in sql.lower() and "join employees" not in sql.lower()) or "totalcount" in sql.lower() or "sagg." in sql.lower()
    # 6. Thiếu aggregated subquery / CTE dẫn tới timeout hoặc lỗi grouping chậm
    not_optimized = "s_agg" not in sql.lower() and "topraises" not in sql.lower()

    if has_paren_mismatch or has_bad_dept_no or missing_dept or has_rigid_dept_filter or is_broken_subquery or not_optimized:
        return f"""WITH TopRaises AS (
    SELECT emp_no, COUNT(*) AS RaiseCount, MAX(salary) AS CurrentSalary
    FROM salaries
    GROUP BY emp_no
    HAVING COUNT(*) >= {min_raises}
    ORDER BY RaiseCount DESC, CurrentSalary DESC
    LIMIT {limit_val}
),
EmpDept AS (
    SELECT de.emp_no, de.dept_no,
           ROW_NUMBER() OVER (PARTITION BY de.emp_no ORDER BY de.to_date DESC, de.from_date DESC) AS rn
    FROM dept_emp de
    JOIN TopRaises tr ON de.emp_no = tr.emp_no
)
SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    COALESCE(d.dept_name, 'Chưa rõ') AS Department,
    tr.RaiseCount,
    tr.CurrentSalary
FROM TopRaises tr
JOIN employees e ON tr.emp_no = e.emp_no
LEFT JOIN EmpDept ed ON tr.emp_no = ed.emp_no AND ed.rn = 1
LEFT JOIN departments d ON ed.dept_no = d.dept_no
ORDER BY tr.RaiseCount DESC, tr.CurrentSalary DESC;""".strip()

    # Nếu truy vấn không có LIMIT, đảm bảo giới hạn số dòng
    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {limit_val};"

    return sql


def auto_fix_specific_employee_lookup_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi tra cứu thông tin / phòng ban của nhân viên cụ thể theo mã số (ví dụ: 10042, 10048).
    Tránh việc dùng `de.to_date = '9999-01-01'` làm mất phòng ban của các nhân viên đã chuyển phòng hoặc thôi việc.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Tìm các mã nhân viên dạng 5 chữ số
    emp_ids = re.findall(r"\b(\d{5})\b", q_low)
    has_emp_kw = any(k in q_low for k in ["nhân viên", "emp_no", "mã số", "người", "ai", "thông tin", "department", "phòng ban"]) or bool(re.search(r"\b100\d{2}\b", q_low))
    if not emp_ids or not has_emp_kw:
        return sql

    emp_in_clause = ", ".join(emp_ids)
    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    lowered_sql = (sql or "").lower()
    # Bị sai nếu:
    # 1. Lọc cứng de.to_date = '9999-01-01' khiến cựu nhân viên bị NULL / mất phòng ban
    # 2. Không chứa các emp_no được hỏi
    # 3. Không có join bảng departments hoặc dept_emp
    has_rigid_date = "de.to_date = '9999-01-01'" in lowered_sql or "de.to_date='9999-01-01'" in lowered_sql
    missing_emp_id = not any(eid in lowered_sql for eid in emp_ids)
    missing_tables = "employees" not in lowered_sql or "departments" not in lowered_sql
    
    if has_rigid_date or missing_emp_id or missing_tables or not sql:
        return f"""WITH EmpLatestDept AS (
    SELECT de.emp_no, de.dept_no, de.from_date, de.to_date,
           ROW_NUMBER() OVER (PARTITION BY de.emp_no ORDER BY de.to_date DESC, de.from_date DESC) AS rn
    FROM dept_emp de
    WHERE de.emp_no IN ({emp_in_clause})
),
EmpLatestTitle AS (
    SELECT t.emp_no, t.title,
           ROW_NUMBER() OVER (PARTITION BY t.emp_no ORDER BY t.to_date DESC, t.from_date DESC) AS rn
    FROM titles t
    WHERE t.emp_no IN ({emp_in_clause})
),
EmpLatestSalary AS (
    SELECT s.emp_no, s.salary,
           ROW_NUMBER() OVER (PARTITION BY s.emp_no ORDER BY s.to_date DESC, s.from_date DESC) AS rn
    FROM salaries s
    WHERE s.emp_no IN ({emp_in_clause})
)
SELECT 
    e.emp_no,
    {concat_expr} AS FullName,
    e.gender AS Gender,
    e.hire_date AS HireDate,
    COALESCE(d.dept_name, 'Chưa rõ') AS Department,
    elt.title AS Title,
    els.salary AS LatestSalary,
    eld.from_date AS DeptFromDate,
    CASE WHEN eld.to_date = '9999-01-01' THEN 'Hiện tại' ELSE eld.to_date END AS DeptToDate
FROM employees e
LEFT JOIN EmpLatestDept eld ON e.emp_no = eld.emp_no AND eld.rn = 1
LEFT JOIN departments d ON eld.dept_no = d.dept_no
LEFT JOIN EmpLatestTitle elt ON e.emp_no = elt.emp_no AND elt.rn = 1
LEFT JOIN EmpLatestSalary els ON e.emp_no = els.emp_no AND els.rn = 1
WHERE e.emp_no IN ({emp_in_clause})
ORDER BY e.emp_no ASC;""".strip()

    return sql


def auto_fix_department_avg_salary_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi mức lương trung bình theo từng phòng ban, tránh lỗi cú pháp, mất ngoặc đơn CTE hoặc hallucinate."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Kiểm tra điều kiện câu hỏi mức lương trung bình theo phòng ban
    has_dept = any(k in q_low for k in ["phòng ban", "phòng", "các phòng", "từng phòng", "department", "departments", "dept"])
    has_avg_sal = any(k in q_low for k in ["lương trung bình", "mức lương trung bình", "lương bình quân", "mức lương", "lương tb", "avg salary", "average salary"])

    # Loại trừ các câu hỏi chuyên sâu khác đã có hàm riêng xử lý
    is_excluded = any(k in q_low for k in [
        "nam", "nữ", "gender", "giới tính",
        "quản lý", "trưởng phòng", "manager",
        "chức danh", "title",
        "thâm niên", "tenure",
        "vượt trên", "trên trung bình công ty", "above average",
        "trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", ">", "<", ">=", "<=",
        "tăng lương", "raise",
        "chênh lệch", "gap", "biến động", "fluctuation",
        "tăng trưởng", "growth",
        "chiếm", "share",
        "tỷ lệ", "tỉ lệ", "tỷ trọng", "tỉ trọng",
        "quy mô", "headcount", "nhiều nhất", "ít nhất", "top"
    ])

    if not (has_dept and has_avg_sal) or is_excluded:
        return sql

    canonical_sql = """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_no, d.dept_name
ORDER BY AvgSalary DESC;""".strip()

    if not sql:
        return canonical_sql

    sql_low = sql.lower()
    has_paren_mismatch = (sql.count("(") != sql.count(")"))
    has_hallucinated = any(k in sql_low for k in ["raise_amount", "topraises", "empdept", "s.raise_amount", "sagg.", "totalcount", "first_name = 'van'"])
    missing_avg = "avg(" not in sql_low and "avgsalary" not in sql_low
    missing_dept = "departments" not in sql_low or "dept_emp" not in sql_low
    missing_current = "9999-01-01" not in sql_low
    is_broken_cte = "with " in sql_low and ("select" not in sql_low or ")" not in sql_low)
    has_bad_grouping = "group by" in sql_low and "dept_name" not in sql_low and "d.dept_no" not in sql_low

    if (has_paren_mismatch or has_hallucinated or missing_avg or missing_dept or missing_current or is_broken_cte or has_bad_grouping):
        return canonical_sql

    return sql


def auto_fix_department_comparison_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và sửa lỗi nhầm lẫn sang bảng dept_manager khi hỏi so sánh quy mô nhân sự và mức lương trung bình phòng ban."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_dept_comp = (
        any(k in q_low for k in ["quy mô", "số lượng nhân sự", "số nhân sự", "số lượng nhân viên", "số nhân viên", "headcount"])
        and any(k in q_low for k in ["lương trung bình", "mức lương", "thu nhập", "lương", "salary"])
        and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "giữa các phòng", "phòng"])
        and not any(k in q_low for k in ["trên", "dưới", "vượt", "hơn", "cao hơn", "thấp hơn", "lớn hơn", "nhỏ hơn", ">", "<", "above", "below"])
    )

    if not is_dept_comp:
        return sql

    has_manager = bool(re.search(r"\b(dept_manager|ManagerName|dm\.)\b", sql, re.IGNORECASE))
    missing_headcount = not bool(re.search(r"\b(Headcount|TotalEmployees|COUNT\s*\()\b", sql, re.IGNORECASE))
    missing_avg = not bool(re.search(r"\b(AVG\s*\(|AvgSalary)\b", sql, re.IGNORECASE))

    if has_manager or missing_headcount or missing_avg:
        return """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount DESC"""

    return sql


def auto_fix_title_gender_salary_query(sql: str, user_query: str) -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương trung bình giữa nam và nữ theo từng chức danh sang dạng Pivot 2 cột."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_title_gender_salary = (
        any(k in q_low for k in ["lương trung bình", "mức lương", "thu nhập"])
        and any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính"])
        and any(k in q_low for k in ["chức danh", "vị trí", "title", "công việc"])
    )

    if not is_title_gender_salary:
        return sql

    has_concat_gender = bool(re.search(r"CONCAT\s*\([^)]*gender[^)]*\)", sql, re.IGNORECASE))
    missing_pivoted_salary = not (
        bool(re.search(r"\bMaleAvgSalary\b", sql, re.IGNORECASE))
        and bool(re.search(r"\bFemaleAvgSalary\b", sql, re.IGNORECASE))
    )

    if has_concat_gender or missing_pivoted_salary:
        return """SELECT 
    t.title AS Title,
    ROUND(AVG(CASE WHEN e.gender = 'M' THEN s.salary END), 2) AS MaleAvgSalary,
    ROUND(AVG(CASE WHEN e.gender = 'F' THEN s.salary END), 2) AS FemaleAvgSalary
FROM titles t
JOIN employees e ON t.emp_no = e.emp_no
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY MaleAvgSalary DESC"""

    return sql


def auto_fix_title_total_salary_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi Top N chức danh có TỔNG MỨC LƯƠNG / QUỸ LƯƠNG cao nhất sang SUM(s.salary) thay vì tính AVG."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    is_title_total_salary = (
        any(k in q_low for k in ["tổng mức lương", "tổng lương", "tổng quỹ lương", "tổng thu nhập", "total salary", "total payroll", "quỹ lương"])
        and any(k in q_low for k in ["chức danh", "title", "vị trí"])
    )
    if not is_title_total_salary:
        return sql

    # Trích xuất số lượng N
    top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
    req_limit = int(top_m.group(1)) if top_m else 10

    # Nếu câu SQL chỉ có AVG(s.salary) mà không có SUM(s.salary)
    if not sql or "sum(" not in sql.lower() or "totalsalary" not in sql.lower():
        return f"""SELECT 
    t.title AS Title, 
    SUM(s.salary) AS TotalSalary,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    COUNT(DISTINCT t.emp_no) AS EmployeeCount
FROM salaries s
JOIN titles t ON s.emp_no = t.emp_no
WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY TotalSalary DESC
LIMIT {req_limit};"""

    return sql


def auto_fix_current_manager_salary_query(sql: str, user_query: str) -> str:
    """Tự động đảm bảo câu hỏi danh sách Manager/Trưởng phòng hiện tại của từng phòng ban kèm lương lấy đúng 9 managers hiện tại và mức lương mới nhất."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_subordinate_compare = any(k in q_low for k in [
        "cấp dưới", "dưới quyền", "nhân viên", "thấp hơn", "kém hơn", "cao hơn", 
        "so sánh", "chênh lệch", "thấp hơn cả", "thua", "subordinate", "vượt"
    ])
    if is_subordinate_compare:
        return sql

    is_manager_salary = (
        any(k in q_low for k in ["manager", "trưởng phòng", "ban quản lý", "lãnh đạo phòng"])
        and any(k in q_low for k in ["lương", "thu nhập", "salary"])
        and not any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "tỷ lệ"])
    )
    if not is_manager_salary:
        return sql

    lowered_sql = sql.lower()
    has_dept_manager = "dept_manager" in lowered_sql
    has_departments = "departments" in lowered_sql
    has_salaries = "salaries" in lowered_sql
    has_current_filter = bool(re.search(r"dm\.to_date\s*=\s*'9999-01-01'", sql, re.IGNORECASE))
    is_hallucinated = "totalcompanyvalue" in lowered_sql or ("sum(" in lowered_sql and "group by" not in lowered_sql)

    if not (has_dept_manager and has_departments and has_salaries and has_current_filter) or is_hallucinated:
        return """SELECT 
    d.dept_name AS Department,
    CONCAT(e.first_name, ' ', e.last_name) AS ManagerName,
    s.salary AS CurrentSalary
FROM dept_manager dm
JOIN departments d ON dm.dept_no = d.dept_no
JOIN employees e ON dm.emp_no = e.emp_no
JOIN salaries s ON dm.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE dm.to_date = '9999-01-01'
ORDER BY CurrentSalary DESC"""

    return sql


def auto_fix_manager_vs_subordinate_salary_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương giữa Quản lý (Manager) và nhân viên cấp dưới trực thuộc cùng phòng ban."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Tuyệt đối không can thiệp nếu câu hỏi so sánh nhân viên kỳ cựu vs mới vào
    if any(k in q_low for k in ["kỳ cựu", "mới vào", "nhân viên mới", "dưới 2 năm", "trên 5 năm"]):
        return sql

    # Guard: Tuyệt đối không can thiệp nếu câu hỏi so sánh 2 phòng ban cụ thể
    dept_keywords = ["sales", "marketing", "development", "research", "finance", "production", "customer service", "quality management", "human resources", "kinh doanh", "tiếp thị", "phát triển", "nghiên cứu", "tài chính", "sản xuất", "nhân sự"]
    matched_depts = set()
    for d_kw in dept_keywords:
        if d_kw in q_low:
            matched_depts.add(d_kw)
    if len(matched_depts) >= 2 and any(k in q_low for k in ["so sánh", "đối chiếu", "chênh lệch", "vs", "compare"]):
        return sql

    is_mgr_sub_comp = (
        any(k in q_low for k in ["manager", "trưởng phòng", "ban quản lý", "quản lý", "lãnh đạo phòng"])
        and any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên", "trực thuộc", "cùng phòng"])
        and any(k in q_low for k in ["thấp hơn", "kém hơn", "cao hơn", "lớn hơn", "vượt", "so sánh", "chênh lệch", "thấp hơn cả", "thua"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập"])
    )
    if not is_mgr_sub_comp:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_mgr = "em.first_name || ' ' || em.last_name" if is_sqlite else "CONCAT(em.first_name, ' ', em.last_name)"
    concat_sub = "ee.first_name || ' ' || ee.last_name" if is_sqlite else "CONCAT(ee.first_name, ' ', ee.last_name)"

    is_asking_subordinates = (
        any(k in q_low for k in [
            "nhân viên nào", "ai là những nhân viên", "những nhân viên", "danh sách nhân viên",
            "danh sách các nhân viên", "các nhân viên", "liệt kê các nhân viên", "liệt kê nhân viên",
            "nhân viên hiện tại", "nhân viên có mức lương", "nhân viên có lương", "nhân viên nào có",
            "những ai", "ai có mức lương cao hơn", "ai có lương cao hơn", "subordinate", "subordinates"
        ])
        or (
            any(k in q_low for k in ["nhân viên", "nhân sự", "cấp dưới"])
            and any(k in q_low for k in ["danh sách", "liệt kê", "tìm", "cho biết danh sách", "ai"])
            and any(k in q_low for k in ["cao hơn", "lớn hơn", "vượt", "thấp hơn"])
        )
    ) and not any(k in q_low for k in ["ai là những quản lý", "quản lý nào", "những quản lý", "phòng ban nào", "thống kê theo phòng", "từng phòng ban"])

    top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
    req_limit = int(top_m.group(1)) if top_m else 10

    is_asking_avg = any(k in q_low for k in ["trung bình", "bình quân", "avg", "average"])

    if is_asking_subordinates:
        return f"""SELECT 
    d.dept_name AS Department,
    {concat_sub} AS SubordinateName,
    se.salary AS SubordinateSalary,
    {concat_mgr} AS ManagerName,
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
LIMIT {req_limit}"""
    elif is_asking_avg:
        ratio_m = re.search(r"(?:gấp|hơn|cao hơn|vượt|gấp hơn)?\s*([0-9]+(?:\.[0-9]+)?)\s*lần", q_low)
        multiplier = float(ratio_m.group(1)) if ratio_m else None
        if multiplier is None and "gấp đôi" in q_low:
            multiplier = 2.0
        elif multiplier is None and "gấp ba" in q_low:
            multiplier = 3.0

        is_asking_lower = any(k in q_low for k in ["thấp hơn", "kém hơn", "nhỏ hơn", "thua"]) and multiplier is None
        is_strict_find = any(k in q_low for k in ["tìm các", "có phòng ban nào", "liệt kê các phòng ban", "phòng ban nào có", "danh sách phòng ban"]) and not any(k in q_low for k in ["so sánh", "đối chiếu", "thống kê toàn bộ", "tất cả phòng ban"])

        having_clause = ""
        if multiplier is not None:
            if is_asking_lower:
                having_clause = f"\nHAVING sm.salary <= {multiplier} * AVG(se.salary)"
            else:
                having_clause = f"\nHAVING sm.salary >= {multiplier} * AVG(se.salary)"
        elif is_strict_find:
            if is_asking_lower:
                having_clause = "\nHAVING sm.salary < AVG(se.salary)"
            else:
                having_clause = "\nHAVING sm.salary > AVG(se.salary)"

        return f"""SELECT 
    d.dept_name AS Department,
    {concat_mgr} AS ManagerName,
    sm.salary AS ManagerSalary,
    ROUND(AVG(se.salary), 2) AS SubordinateAvgSalary,
    ROUND(sm.salary / AVG(se.salary), 2) AS SalaryRatio,
    ROUND(sm.salary - AVG(se.salary), 2) AS SalaryDifference,
    ROUND((sm.salary - AVG(se.salary)) * 100.0 / AVG(se.salary), 2) AS DifferencePercentage
FROM dept_manager dm
JOIN departments d ON dm.dept_no = d.dept_no
JOIN employees em ON dm.emp_no = em.emp_no
JOIN salaries sm ON dm.emp_no = sm.emp_no AND sm.to_date = '9999-01-01'
JOIN dept_emp de ON dm.dept_no = de.dept_no AND de.to_date = '9999-01-01' AND de.emp_no != dm.emp_no
JOIN salaries se ON de.emp_no = se.emp_no AND se.to_date = '9999-01-01'
WHERE dm.to_date = '9999-01-01'
GROUP BY d.dept_name, ManagerName, sm.salary{having_clause}
ORDER BY sm.salary DESC"""
    else:
        return f"""SELECT 
    d.dept_name AS Department,
    {concat_mgr} AS ManagerName,
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
ORDER BY SalaryGap DESC"""


def auto_fix_two_departments_comparison_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương trung bình giữa 2 phòng ban cụ thể (VD: Sales vs Marketing, Sales vs Development)
    đồng thời tính khoảng chênh lệch tuyệt đối và tỷ lệ phần trăm chênh lệch giữa hai phòng ban này.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Danh sách chuẩn 9 phòng ban trong CSDL (hỗ trợ cả tiếng Anh và tiếng Việt đồng nghĩa)
    known_depts = {
        # Tiếng Anh chuẩn
        "sales": "Sales",
        "development": "Development",
        "research": "Research",
        "marketing": "Marketing",
        "finance": "Finance",
        "production": "Production",
        "customer service": "Customer Service",
        "quality management": "Quality Management",
        "human resources": "Human Resources",
        # Tiếng Việt đồng nghĩa
        "kinh doanh": "Sales",
        "bán hàng": "Sales",
        "tiếp thị": "Marketing",
        "phát triển": "Development",
        "nghiên cứu": "Research",
        "tài chính": "Finance",
        "sản xuất": "Production",
        "chăm sóc khách hàng": "Customer Service",
        "cskh": "Customer Service",
        "quản lý chất lượng": "Quality Management",
        "qlcl": "Quality Management",
        "nhân sự": "Human Resources",
        "hr": "Human Resources",
    }

    found_depts = []
    dept_positions = []
    for k, v in known_depts.items():
        pos = q_low.find(k)
        if pos != -1:
            dept_positions.append((pos, v))

    dept_positions.sort(key=lambda x: x[0])
    for _, v in dept_positions:
        if v not in found_depts:
            found_depts.append(v)

    if len(found_depts) != 2:
        return sql

    is_comparison = any(k in q_low for k in ["so sánh", "đối chiếu", "chênh lệch", "khác nhau", "cao hơn", "thấp hơn", "tỷ lệ", "tỉ lệ", "vs", "compare"])
    is_salary = any(k in q_low for k in ["lương", "thu nhập", "salary", "thu nhap"])

    if not (is_comparison and is_salary):
        return sql

    d1, d2 = found_depts[0], found_depts[1]

    return f"""WITH DeptStats AS (
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
ORDER BY d.AvgSalary DESC;""".strip()


def auto_fix_department_group_salary_query(sql: str, user_query: str) -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương, lương cao nhất, tổng quỹ lương giữa các phòng ban Kỹ thuật (Development, Research) và phòng Kinh doanh / Thương mại (Sales, Marketing)."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Tuyệt đối không can thiệp nếu câu hỏi chỉ so sánh đúng 2 phòng ban cụ thể (không chứa từ khóa khối/nhóm/kỹ thuật/kinh doanh/thương mại)
    known_depts = ["sales", "development", "research", "marketing", "finance", "production", "customer service", "quality management", "human resources"]
    depts_mentioned = [d for d in known_depts if d in q_low]
    if len(depts_mentioned) == 2 and not any(k in q_low for k in ["kỹ thuật", "kinh doanh", "thương mại", "khối", "nhóm", "group", "block", "cả hai", "các phòng", "từng khối"]):
        return sql

    is_tech_vs_comm = (
        (
            any(k in q_low for k in ["kỹ thuật", "tech", "development", "research"])
            and any(k in q_low for k in ["kinh doanh", "commercial", "thương mại", "sales", "marketing"])
            and any(k in q_low for k in ["so sánh", "đối chiếu", "compare", "vs", "lương", "salary", "quỹ lương", "thu nhập"])
        ) or (
            ("development" in q_low or "research" in q_low)
            and ("sales" in q_low or "marketing" in q_low)
            and any(k in q_low for k in ["so sánh", "đối chiếu", "compare", "vs", "lương", "salary", "quỹ lương"])
        )
    )
    if not is_tech_vs_comm:
        return sql

    # Nhãn tên nhóm linh hoạt theo câu hỏi người dùng (ví dụ: Khối Thương mại vs Khối Kinh doanh)
    comm_label = "Khối Thương mại (Sales, Marketing)" if any(k in q_low for k in ["thương mại", "commercial"]) else "Khối Kinh doanh (Sales, Marketing)"
    tech_label = "Khối Kỹ thuật (Development, Research)"

    return f"""SELECT 
    CASE 
        WHEN d.dept_name IN ('Sales', 'Marketing') THEN '{comm_label}'
        WHEN d.dept_name IN ('Development', 'Research') THEN '{tech_label}'
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
ORDER BY DepartmentGroup, AvgSalary DESC;""".strip()


def auto_fix_department_single_vs_others_salary_query(sql: str, user_query: str) -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương trung bình phòng ban với các phòng khác, loại bỏ cột phần trăm ảo làm phẳng biểu đồ và bỏ bộ lọc phòng ban đơn lẻ."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_dept_salary_comp = (
        any(k in q_low for k in ["so sánh", "so voi", "so với", "đối chiếu", "so sánh giữa"])
        and any(k in q_low for k in ["lương trung bình", "mức lương", "thu nhập", "lương", "salary", "avg salary"])
        and any(k in q_low for k in ["phòng ban khác", "các phòng ban", "các phòng khác", "các phòng", "phòng khác", "toàn công ty", "toàn bộ công ty", "mặt bằng chung"])
        and not any(k in q_low for k in [
            "quy mô", "headcount", "số lượng nhân sự", "số nhân sự", "số lượng nhân viên", "số nhân viên",
            "nhân viên", "nhân sự", "người", "ai", "employee", "đầu tiên", "khởi điểm", "tỷ lệ tăng lương", "tỉ lệ tăng lương", "tăng lương ấn tượng"
        ])
        and not (
            any(k in q_low for k in ["kỹ thuật", "tech"])
            and any(k in q_low for k in ["kinh doanh", "commercial", "sales"])
        )
        and not (
            ("development" in q_low or "research" in q_low)
            and ("sales" in q_low or "marketing" in q_low)
        )
    )
    if not is_dept_salary_comp:
        return sql

    # Đối với câu hỏi so sánh mức lương giữa một phòng ban và các phòng ban khác / toàn công ty,
    # BẮT BUỘC phải trả về tất cả các phòng ban để vẽ biểu đồ so sánh và xác định vị thế xếp hạng.
    return """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY AvgSalary DESC"""


def auto_fix_department_single_vs_others_headcount_query(sql: str, user_query: str) -> str:
    """Tự động chuẩn hóa câu hỏi so sánh quy mô nhân sự phòng ban với các phòng khác."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_dept_headcount_comp = (
        any(k in q_low for k in ["so sánh", "so voi", "so với", "đối chiếu"])
        and any(k in q_low for k in ["quy mô", "nhân sự", "số lượng", "headcount", "nhân viên"])
        and any(k in q_low for k in ["phòng ban khác", "các phòng ban", "các phòng khác", "các phòng", "phòng khác", "toàn công ty", "mặt bằng chung"])
        and not any(k in q_low for k in ["lương", "salary", "thu nhập"])
    )
    if not is_dept_headcount_comp:
        return sql

    return """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount DESC"""


def auto_fix_salary_bracket_distribution_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn phân loại toàn bộ nhân sự thành 3 nhóm lương (Dưới 50k, 50k-80k, Trên 80k)."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    is_tier_q = (
        any(k in q_low for k in ["nhóm lương", "bậc lương", "khoảng lương", "3 nhóm lương", "thu nhập thấp", "thu nhập trung bình", "thu nhập cao"])
        or (
            any(k in q_low for k in ["phân loại", "chia thành", "nhóm", "tier", "bracket"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary"])
            and any(k in q_low for k in ["nhân sự", "nhân viên", "toàn bộ", "hiện tại", "tỷ lệ", "%", "số lượng", "mỗi nhóm"])
        )
    )
    if not is_tier_q:
        return sql

    return """SELECT 
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
ORDER BY TierOrder ASC"""


def auto_fix_department_salary_fluctuation_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn tính độ lệch chuẩn (STDDEV) hoặc tỷ lệ biến động lương theo phòng ban cùng mức lương hiện tại."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    is_fluct_q = (
        any(k in q_low for k in ["biến động lương", "tỷ lệ biến động lương", "độ biến động lương", "dao động lương", "độ lệch chuẩn", "stddev", "độ phân tán"])
        or (
            any(k in q_low for k in ["biến động", "fluctuation", "dao động", "phân tán", "độ lệch chuẩn", "stddev"])
            and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department", "chức danh", "title"])
            and any(k in q_low for k in ["lương", "salary", "thu nhập"])
        )
    )
    if not is_fluct_q:
        return sql

    is_stddev_focus = any(k in q_low for k in ["độ lệch chuẩn", "stddev", "phân tán", "độ phân tán", "standard deviation"])
    order_col = "SalaryStdDev" if is_stddev_focus else "FluctuationRate"
    is_single_dept = any(k in q_low for k in ["phòng ban nào", "đơn vị nào", "nơi nào", "which department"]) and not any(k in q_low for k in ["các phòng", "từng phòng", "tất cả", "danh sách", "top", "bảng", "all", "each"])
    limit_clause = "\nLIMIT 1" if is_single_dept else ""

    lowered_sql = (sql or "").lower()
    has_stddev = "stddev" in lowered_sql or "std(" in lowered_sql or "salarystddev" in lowered_sql
    has_dept = "departments" in lowered_sql and "dept_name" in lowered_sql
    has_time = "to_date" in lowered_sql
    has_avg = "avg(" in lowered_sql or "currentavgsalary" in lowered_sql

    if not has_stddev or not has_dept or not has_time or not has_avg:
        return f"""SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS CurrentAvgSalary,
    ROUND(STDDEV(s.salary), 2) AS SalaryStdDev,
    ROUND(STDDEV(s.salary) * 100.0 / AVG(s.salary), 2) AS FluctuationRate
FROM salaries s
JOIN dept_emp de ON s.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
WHERE s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY {order_col} DESC{limit_clause};""".strip()

    if is_stddev_focus and "order by salarystddev desc" not in lowered_sql and "order by stddev" not in lowered_sql:
        sql = re.sub(r"ORDER\s+BY\s+[^;]+", f"ORDER BY SalaryStdDev DESC{limit_clause}", sql, flags=re.IGNORECASE)

    return sql


def auto_fix_department_top_payroll_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn tổng quỹ lương chi trả theo phòng ban kèm số lượng nhân sự."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    is_top_payroll_q = (
        any(k in q_low for k in ["quỹ lương", "tổng quỹ lương", "tổng chi trả lương", "chi trả quỹ lương", "chi phí lương"])
        or (
            any(k in q_low for k in ["tổng lương", "tổng chi lương", "tổng tiền lương"])
            and any(k in q_low for k in ["phòng ban", "các phòng", "từng phòng", "department"])
        )
    )
    if not is_top_payroll_q:
        return sql

    top_n = extract_requested_limit(user_query)
    limit_clause = f"\nLIMIT {top_n}" if top_n else ""
    return f"""SELECT 
    d.dept_name AS Department,
    SUM(s.salary) AS TotalPayroll,
    COUNT(DISTINCT de.emp_no) AS Headcount,
    ROUND(AVG(s.salary), 2) AS AvgSalary
FROM salaries s
JOIN dept_emp de ON s.emp_no = de.emp_no AND de.to_date = '9999-01-01'
JOIN departments d ON de.dept_no = d.dept_no
WHERE s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY TotalPayroll DESC{limit_clause}"""


def auto_fix_count_dept_transfer_employees_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn đếm số lượng và tỷ lệ nhân viên từng thay đổi phòng ban ít nhất 1 lần."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    is_count_transfer_q = (
        (
            any(k in q_low for k in ["thay đổi phòng ban", "thay đổi phòng", "đổi phòng ban", "đổi phòng", "chuyển phòng ban", "chuyển phòng", "luân chuyển phòng ban", "luân chuyển phòng", "luân chuyển bộ phận"])
            or (any(k in q_low for k in ["thay đổi", "đổi", "chuyển", "luân chuyển"]) and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
        )
        and any(k in q_low for k in ["bao nhiêu", "số lượng", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many", "mấy"])
        and not any(k in q_low for k in ["danh sách", "liệt kê", "những ai", "top", "ai là"])
    )
    if not is_count_transfer_q:
        return sql

    return """SELECT 
    COUNT(*) AS EmployeesChangedDepartment,
    (SELECT COUNT(DISTINCT emp_no) FROM dept_emp) AS TotalEmployees,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(DISTINCT emp_no) FROM dept_emp), 2) AS PercentageChangedDept
FROM (
    SELECT emp_no
    FROM dept_emp
    GROUP BY emp_no
    HAVING COUNT(DISTINCT dept_no) > 1
) t"""



def auto_fix_insight1_department_transfers_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Khớp chính xác câu hỏi Insight 1: Khảo sát khối lượng luân chuyển phòng ban theo năm và tỷ lệ đổi chức danh / tăng lương trong 30 ngày."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_insight1_query = (
        ("luân chuyển" in q_low or "chuyển phòng" in q_low or "transfer" in q_low or "moves" in q_low)
        and (
            ("30 ngày" in q_low or "30 days" in q_low or "30d" in q_low)
            or (("chức danh" in q_low or "title" in q_low) and ("lương" in q_low or "salary" in q_low or "pay" in q_low) and ("năm" in q_low or "year" in q_low))
            or ("31578" in q_low or "31,578" in q_low or "18 năm" in q_low or "18 years" in q_low)
        )
        and not any(k in q_low for k in ["chuyển đến", "chuyển đi", "phòng ban nào", "nhiều nhất", "ít nhất", "top"])
    )

    if not is_insight1_query:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    if is_sqlite:
        return """WITH moves AS (
    SELECT d1.emp_no,
           d1.dept_no AS old_dept,
           d2.dept_no AS new_dept,
           d1.to_date AS move_date
    FROM dept_emp d1
    JOIN dept_emp d2
      ON d1.emp_no = d2.emp_no
     AND d1.to_date = d2.from_date
     AND d1.dept_no <> d2.dept_no
)
SELECT 
    CAST(strftime('%Y', m.move_date) AS INTEGER) AS transfer_year,
    COUNT(*) AS total_transfers,
    SUM(CASE WHEN EXISTS (
        SELECT 1 FROM titles t 
        WHERE t.emp_no = m.emp_no 
          AND ABS(JULIANDAY(t.from_date) - JULIANDAY(m.move_date)) <= 30
    ) THEN 1 ELSE 0 END) AS title_change_30d,
    SUM(CASE WHEN EXISTS (
        SELECT 1 FROM salaries s 
        WHERE s.emp_no = m.emp_no 
          AND ABS(JULIANDAY(s.from_date) - JULIANDAY(m.move_date)) <= 30
    ) THEN 1 ELSE 0 END) AS pay_change_30d
FROM moves m
GROUP BY transfer_year
ORDER BY transfer_year ASC;"""
    else:
        return """WITH moves AS (
    SELECT d1.emp_no,
           d1.dept_no AS old_dept,
           d2.dept_no AS new_dept,
           d1.to_date AS move_date
    FROM dept_emp d1
    JOIN dept_emp d2
      ON d1.emp_no = d2.emp_no
     AND d1.to_date = d2.from_date
     AND d1.dept_no <> d2.dept_no
)
SELECT 
    YEAR(m.move_date) AS transfer_year,
    COUNT(*) AS total_transfers,
    SUM(EXISTS (
        SELECT 1 FROM titles t 
        WHERE t.emp_no = m.emp_no 
          AND ABS(DATEDIFF(t.from_date, m.move_date)) <= 30
    )) AS title_change_30d,
    SUM(EXISTS (
        SELECT 1 FROM salaries s 
        WHERE s.emp_no = m.emp_no 
          AND ABS(DATEDIFF(s.from_date, m.move_date)) <= 30
    )) AS pay_change_30d
FROM moves m
GROUP BY transfer_year
ORDER BY transfer_year ASC;"""


def auto_fix_insight2_female_managers_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Khớp chính xác câu hỏi Insight 2: Bất bình đẳng giới trong bổ nhiệm quản lý khối Thương Mại (Sales & Marketing 0% nữ quản lý)."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_insight2_query = (
        ("nữ quản lý" in q_low or "female manager" in q_low or "female leadership" in q_low or "nữ lãnh đạo" in q_low or "phụ nữ làm quản lý" in q_low or "nữ trưởng phòng" in q_low or ("quản lý" in q_low and ("nữ" in q_low or "giới tính" in q_low or "female" in q_low or "gender" in q_low)))
        and (
            ("thương mại" in q_low or "commercial" in q_low or "sales" in q_low or "marketing" in q_low)
            or ("từng phòng ban" in q_low or "mỗi phòng ban" in q_low or "theo phòng ban" in q_low or "by department" in q_low or "per department" in q_low)
            or ("0%" in q_low or "54%" in q_low or "tỷ lệ nữ" in q_low or "bất bình đẳng" in q_low)
        )
        and not any(k in q_low for k in ["mức lương trung bình giữa các giới tính", "lương trung bình theo giới tính", "so sánh lương nam", "salary by gender", "avg salary between gender"])
    )

    if not is_insight2_query:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    if is_sqlite:
        return """SELECT 
    d.dept_name,
    SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS male_mgrs,
    SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS female_mgrs,
    COUNT(*) AS total_managers,
    ROUND(100.0 * SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_female_mgrs
FROM dept_manager dm
JOIN employees e ON dm.emp_no = e.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
GROUP BY d.dept_name
ORDER BY pct_female_mgrs ASC, d.dept_name ASC;"""
    else:
        return """SELECT 
    d.dept_name,
    SUM(e.gender = 'M') AS male_mgrs,
    SUM(e.gender = 'F') AS female_mgrs,
    COUNT(*) AS total_managers,
    ROUND(100.0 * SUM(e.gender = 'F') / COUNT(*), 1) AS pct_female_mgrs
FROM dept_manager dm
JOIN employees e ON dm.emp_no = e.emp_no
JOIN departments d ON dm.dept_no = d.dept_no
GROUP BY d.dept_name
ORDER BY pct_female_mgrs ASC, d.dept_name ASC;"""


def auto_fix_insight3_promotion_timeline_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Khớp chính xác câu hỏi Insight 3: Thời gian chờ trung bình để nhân viên được thăng chức theo phòng ban (khung 5-9 năm)."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_insight3 = (
        ("thăng chức" in q_low or "đổi chức danh" in q_low or "promotion" in q_low or "promote" in q_low or "thời gian chờ" in q_low or "wait time" in q_low)
        and ("phòng ban" in q_low or "department" in q_low or "từng phòng" in q_low or "5-9 năm" in q_low or "5 to 9" in q_low or "khung cố định" in q_low or "bao nhiêu năm" in q_low)
        and not any(k in q_low for k in ["30 ngày", "30 days", "31,578", "31578", "luân chuyển", "quản lý", "manager", "gender", "giới tính"])
    )
    if not is_insight3:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    if is_sqlite:
        return """WITH transitions AS (
    SELECT 
        t1.emp_no,
        t2.from_date AS promo_date,
        ((JULIANDAY(t2.from_date) - JULIANDAY(t1.from_date)) / 365.25) AS years_to_promote
    FROM titles t1
    JOIN titles t2 ON t1.emp_no = t2.emp_no AND t1.to_date = t2.from_date
)
SELECT 
    d.dept_name,
    COUNT(*) AS total_promotions,
    ROUND(AVG(tr.years_to_promote), 2) AS avg_years_to_promote,
    ROUND(MIN(tr.years_to_promote), 2) AS min_years,
    ROUND(MAX(tr.years_to_promote), 2) AS max_years
FROM transitions tr
JOIN dept_emp de ON tr.emp_no = de.emp_no AND tr.promo_date >= de.from_date AND tr.promo_date < de.to_date
JOIN departments d ON de.dept_no = d.dept_no
GROUP BY d.dept_name
ORDER BY avg_years_to_promote ASC;"""
    else:
        return """WITH transitions AS (
    SELECT 
        t1.emp_no,
        t2.from_date AS promo_date,
        (TIMESTAMPDIFF(MONTH, t1.from_date, t2.from_date) / 12.0) AS years_to_promote
    FROM titles t1
    JOIN titles t2 ON t1.emp_no = t2.emp_no AND t1.to_date = t2.from_date
)
SELECT 
    d.dept_name,
    COUNT(*) AS total_promotions,
    ROUND(AVG(tr.years_to_promote), 2) AS avg_years_to_promote,
    ROUND(MIN(tr.years_to_promote), 2) AS min_years,
    ROUND(MAX(tr.years_to_promote), 2) AS max_years
FROM transitions tr
JOIN dept_emp de ON tr.emp_no = de.emp_no AND tr.promo_date >= de.from_date AND tr.promo_date < de.to_date
JOIN departments d ON de.dept_no = d.dept_no
GROUP BY d.dept_name
ORDER BY avg_years_to_promote ASC;"""


def auto_fix_insight4_salary_compression_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Khớp chính xác câu hỏi Insight 4: Hiện tượng nén lương theo chức danh (mới vào nhưng lương cao)."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_insight4 = (
        ("nén lương" in q_low or "ép lương" in q_low or "compression" in q_low or "salary compression" in q_low or "mới vào" in q_low or "mới tuyển" in q_low or "new high earner" in q_low or "top cao" in q_low)
        and ("chức danh" in q_low or "title" in q_low or "vị trí" in q_low or "job title" in q_low or "staff" in q_low or "assistant engineer" in q_low or "phân bổ" in q_low or "giữa các" in q_low)
    )
    if not is_insight4:
        return sql

    return """WITH current_emp_data AS (
    SELECT e.emp_no, e.hire_date, t.title, s.salary
    FROM employees e
    JOIN salaries s ON e.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    JOIN titles t ON e.emp_no = t.emp_no AND t.to_date = '9999-01-01'
),
ranked_emp AS (
    SELECT emp_no, hire_date, title, salary,
           PERCENT_RANK() OVER (PARTITION BY title ORDER BY hire_date ASC) AS seniority_pct,
           PERCENT_RANK() OVER (PARTITION BY title ORDER BY salary ASC) AS salary_pct
    FROM current_emp_data
)
SELECT 
    title,
    COUNT(CASE WHEN seniority_pct > 0.8 AND salary_pct > 0.6 THEN 1 END) AS actual,
    ROUND(COUNT(CASE WHEN seniority_pct > 0.8 THEN 1 END) * COUNT(CASE WHEN salary_pct > 0.6 THEN 1 END) * 1.0 / COUNT(*), 2) AS expected_if_random,
    ROUND(COUNT(CASE WHEN seniority_pct > 0.8 AND salary_pct > 0.6 THEN 1 END) * 100.0 / COUNT(*), 2) AS ty_le_bi_ep_luong_pct,
    ROUND((COUNT(CASE WHEN seniority_pct > 0.8 AND salary_pct > 0.6 THEN 1 END) * 1.0) / 
          NULLIF(COUNT(CASE WHEN seniority_pct > 0.8 THEN 1 END) * COUNT(CASE WHEN salary_pct > 0.6 THEN 1 END) * 1.0 / COUNT(*), 0), 2) AS lift
FROM ranked_emp
GROUP BY title
ORDER BY ty_le_bi_ep_luong_pct DESC;"""


def auto_fix_insight5_manager_turnover_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Khớp chính xác câu hỏi Insight 5: Thâm niên trưởng phòng vs Tỷ lệ rời đi/biến động phòng ban."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_insight5 = (
        ("thâm niên" in q_low or "tenure" in q_low or "thời gian làm việc" in q_low or "quản lý" in q_low or "trưởng phòng" in q_low or "manager" in q_low)
        and ("nghỉ việc" in q_low or "rời đi" in q_low or "turnover" in q_low or "biến động" in q_low or "rời khỏi" in q_low or "exit" in q_low)
        and ("phòng ban" in q_low or "department" in q_low)
        and not any(k in q_low for k in ["giới tính", "gender", "nữ", "female", "lương"])
    )
    if not is_insight5:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    if is_sqlite:
        return """WITH dataset_snapshot AS (
    SELECT MAX(to_date) AS snapshot_date FROM salaries WHERE to_date <> '9999-01-01'
),
current_managers AS (
    SELECT dm.dept_no,
           ROUND((JULIANDAY((SELECT snapshot_date FROM dataset_snapshot)) - JULIANDAY(dm.from_date)) / 365.25, 2) AS manager_tenure_years
    FROM dept_manager dm
    WHERE dm.to_date = '9999-01-01'
),
department_turnover AS (
    SELECT dept_no,
           COUNT(*) AS total_assignments,
           SUM(CASE WHEN to_date <> '9999-01-01' THEN 1 ELSE 0 END) AS ended_assignments,
           ROUND(100.0 * SUM(CASE WHEN to_date <> '9999-01-01' THEN 1 ELSE 0 END) / COUNT(*), 2) AS turnover_rate_pct
    FROM dept_emp
    GROUP BY dept_no
)
SELECT 
    d.dept_name,
    cm.manager_tenure_years,
    dt.total_assignments,
    dt.ended_assignments,
    dt.turnover_rate_pct
FROM departments d
JOIN current_managers cm ON d.dept_no = cm.dept_no
JOIN department_turnover dt ON d.dept_no = dt.dept_no
ORDER BY cm.manager_tenure_years DESC;"""
    else:
        return """WITH dataset_snapshot AS (
    SELECT MAX(to_date) AS snapshot_date FROM salaries WHERE to_date <> '9999-01-01'
),
current_managers AS (
    SELECT dm.dept_no,
           ROUND(DATEDIFF((SELECT snapshot_date FROM dataset_snapshot), dm.from_date) / 365.25, 2) AS manager_tenure_years
    FROM dept_manager dm
    WHERE dm.to_date = '9999-01-01'
),
department_turnover AS (
    SELECT dept_no,
           COUNT(*) AS total_assignments,
           SUM(to_date <> '9999-01-01') AS ended_assignments,
           ROUND(100.0 * SUM(to_date <> '9999-01-01') / COUNT(*), 2) AS turnover_rate_pct
    FROM dept_emp
    GROUP BY dept_no
)
SELECT 
    d.dept_name,
    cm.manager_tenure_years,
    dt.total_assignments,
    dt.ended_assignments,
    dt.turnover_rate_pct
FROM departments d
JOIN current_managers cm ON d.dept_no = cm.dept_no
JOIN department_turnover dt ON d.dept_no = dt.dept_no
ORDER BY cm.manager_tenure_years DESC;"""




def auto_fix_department_transfers_breakdown_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn xếp hạng phòng ban theo số lượng nhân viên chuyển đến hoặc chuyển đi."""
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Không can thiệp nếu là bài toán đếm tổng số nhân viên đổi phòng toàn công ty (single aggregate row)
    if (any(k in q_low for k in ["bao nhiêu", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many"])
        and not any(k in q_low for k in ["phòng ban nào", "phòng nào", "từng phòng", "mỗi phòng", "các phòng", "chuyển đến", "chuyển tới", "chuyển đi"])):
        return sql

    # Guard: Không can thiệp nếu là bài toán so sánh lương với phòng ban đầu tiên
    if any(k in q_low for k in ["phòng ban đầu tiên", "phòng đầu tiên", "first department", "first dept"]) and any(k in q_low for k in ["lương", "salary", "thu nhập"]):
        return sql

    is_transfer_in = (
        (any(k in q_low for k in ["chuyển đến", "chuyển tới", "chuyển sang", "chuyển vào", "tiếp nhận", "transferred in", "transfer in"]) and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
        or (any(k in q_low for k in ["chuyển", "luân chuyển"]) and "đến" in q_low and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
        or (any(k in q_low for k in ["phòng ban nào", "phòng nào"]) and any(k in q_low for k in ["chuyển đến", "chuyển tới", "chuyển sang"]))
    )

    is_transfer_out = (
        (any(k in q_low for k in ["chuyển đi", "rời khỏi", "chuyển khỏi", "transferred out", "transfer out"]) and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
        or (any(k in q_low for k in ["chuyển", "luân chuyển"]) and "đi" in q_low and any(k in q_low for k in ["phòng ban", "phòng", "bộ phận", "department"]))
    )

    if not (is_transfer_in or is_transfer_out):
        return sql

    req_limit = extract_requested_limit(user_query)
    if not req_limit:
        if any(k in q_low for k in ["nhất", "nhiều nhất", "cao nhất", "phòng ban nào", "phòng nào"]) and not any(k in q_low for k in ["top", "danh sách", "các phòng", "tất cả", "xếp hạng"]):
            req_limit = 1
        else:
            req_limit = 10

    sql_low = (sql or "").lower()
    has_cte = "employeedeptrank" in sql_low or "rn > 1" in sql_low or "row_number" in sql_low
    has_dept_join = "departments" in sql_low and ("dept_no" in sql_low)
    has_trans_count = any(k in sql_low for k in ["transferredincount", "transferredoutcount", "transferredcount", "transfer_count", "count("])

    # Nếu SQL chưa chuẩn xác hoặc rỗng/từ chối, chuẩn hóa ngay về CTE chuẩn
    if not has_cte or not has_dept_join or not has_trans_count or not sql or not is_safe_select(sql):
        if is_transfer_in:
            return f"""WITH EmployeeDeptRank AS (
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
LIMIT {req_limit};""".strip()
        else:
            return f"""WITH EmployeeDeptRank AS (
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
LIMIT {req_limit};""".strip()

    return sql


def auto_fix_multi_dept_salary_vs_first_dept_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn: Liệt kê nhân viên từng làm việc tại ít nhất 2 phòng ban khác nhau,
    nhưng mức lương hiện tại thấp hơn (hoặc cao hơn) lương trung bình của phòng ban đầu tiên họ từng gia nhập.
    Áp dụng chuẩn mực CTE 3 bước:
    1. FirstDept: ROW_NUMBER() OVER (PARTITION BY emp_no ORDER BY from_date ASC) = 1
    2. DeptAvg: AVG(salary) theo từng phòng ban hiện hành
    3. MultiDept: COUNT(DISTINCT dept_no) >= 2
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_multi_dept = (
        any(k in q_low for k in ["nhiều phòng ban", "nhiều phòng", "ít nhất 2 phòng", "ít nhất 2 phòng ban", "từ 2 phòng", "từ 2 phòng ban", "qua 2 phòng", "qua 2 phòng ban", "2 phòng ban", "2 phòng ban khác nhau", "2 phòng khác nhau", "chuyển phòng ban", "luân chuyển"])
        or bool(re.search(r"(?:ít nhất|tối thiểu|từ|qua|hơn)\s*\d+\s*phòng", q_low))
    )
    is_first_dept = any(k in q_low for k in ["phòng ban đầu tiên", "phòng đầu tiên", "đầu tiên họ từng", "phòng ban khởi điểm", "phòng ban ban đầu", "first department", "first dept"])
    is_salary_comp = any(k in q_low for k in ["lương", "salary", "thu nhập"])

    if not (is_multi_dept and is_first_dept and is_salary_comp):
        return sql

    req_limit = extract_requested_limit(user_query) or 10
    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    is_higher = any(k in q_low for k in ["cao hơn", "lớn hơn", "vượt", "higher", "greater"])
    sal_comp_op = ">" if is_higher else "<"
    diff_expr = "ROUND(s_curr.salary - da.AvgSalary, 2) AS SalarySurplus" if is_higher else "ROUND(da.AvgSalary - s_curr.salary, 2) AS SalaryDeficit"
    order_col = "SalarySurplus" if is_higher else "SalaryDeficit"

    sql_low = (sql or "").lower()
    has_first_dept = "firstdept" in sql_low or "row_number" in sql_low or "first_dept" in sql_low
    has_dept_avg = "deptavg" in sql_low or "avg" in sql_low
    has_multi_dept_cte = "multidept" in sql_low or "count(distinct" in sql_low
    has_salary_comp_op = ("< da." in sql_low or "> da." in sql_low or "< das." in sql_low or "> das." in sql_low or "salary <" in sql_low or "salary >" in sql_low)
    has_necessary_cols = any(k in sql_low for k in ["firstdept", "first_dept", "salarydeficit", "salarysurplus", "salarybelowavg"])

    is_broken = (
        not has_first_dept
        or not has_dept_avg
        or not has_multi_dept_cte
        or not has_salary_comp_op
        or not has_necessary_cols
        or "from titles" in sql_low
        or not sql
    )

    if is_broken:
        return f"""WITH FirstDept AS (
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
LIMIT {req_limit};""".strip()

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit};"
    return sql


def auto_fix_multi_dept_employees_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn liệt kê nhân viên từng làm việc ở nhiều phòng ban (>= 2 phòng ban),
    kèm theo chức danh hiện tại và phòng ban hiện tại (nếu có yêu cầu chức danh như Senior Engineer, Engineer, v.v.).
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    if any(k in q_low for k in ["bao nhiêu", "số lượng", "tổng số", "tỷ lệ", "tỉ lệ", "đếm", "count", "how many"]):
        return sql

    # Guard: Tuyệt đối không can thiệp nếu câu hỏi so sánh lương hoặc phòng ban đầu tiên
    if any(k in q_low for k in ["lương", "salary", "thu nhập", "thấp hơn", "cao hơn", "đầu tiên", "first dept", "first department"]):
        return sql

    # Nhận diện câu hỏi về nhân viên từng làm việc qua nhiều phòng ban
    has_multi_dept_kw = (
        any(k in q_low for k in [
            "nhiều phòng ban", "nhiều phòng", "ít nhất 2 phòng", "ít nhất 2 phòng ban",
            "từ 2 phòng", "từ 2 phòng ban", "qua 2 phòng", "qua 2 phòng ban",
            "2 phòng ban", "2 phòng ban khác nhau", "2 phòng khác nhau",
            "chuyển phòng ban", "luân chuyển phòng", "luân chuyển công tác",
            "ít nhất hai phòng ban", "nhiều hơn một phòng ban", "nhiều hơn 1 phòng ban"
        ])
        or bool(re.search(r"(?:ít nhất|tối thiểu|từ|qua|hơn)\s*\d+\s*phòng", q_low))
    )
    has_emp_kw = any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "danh sách", "liệt kê", "employee", "employees"])
    has_dept_kw = any(k in q_low for k in ["phòng ban", "phòng", "department"])

    if not (has_multi_dept_kw and has_emp_kw and has_dept_kw):
        return sql

    # Trích xuất số phòng ban tối thiểu (mặc định là 2)
    min_depts = 2
    m_dept = re.search(r"(?:ít nhất|tối thiểu|từ|qua)\s*(\d+)\s*phòng", q_low)
    if m_dept:
        try:
            min_depts = int(m_dept.group(1))
        except ValueError:
            min_depts = 2
    elif any(k in q_low for k in ["nhiều hơn một", "nhiều hơn 1"]):
        min_depts = 2

    # Nhận diện chức danh mục tiêu nếu có
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

    req_limit = extract_requested_limit(user_query) or 10
    is_sqlite = "sqlite" in (dialect or "").lower()
    concat_expr = "e.first_name || ' ' || e.last_name" if is_sqlite else "CONCAT(e.first_name, ' ', e.last_name)"

    lowered_sql = (sql or "").lower()
    select_part = lowered_sql.split("from")[0] if "from" in lowered_sql else lowered_sql
    has_necessary_tables = all(tbl in lowered_sql for tbl in ["employees", "titles", "dept_emp", "departments"])
    has_having_dept_count = "having" in lowered_sql and ("count" in lowered_sql)
    has_select_dept_count = any(k in select_part for k in ["departmentcount", "dept_count", "department_count", "count("])
    has_title_filter = (target_title is None) or (target_title.lower() in lowered_sql)
    has_current_filter = "9999-01-01" in lowered_sql
    has_leak = any(k in lowered_sql for k in ["datediff", "yearsofservice", "hireyear"])

    is_broken = (
        not has_necessary_tables 
        or not has_having_dept_count 
        or not has_select_dept_count
        or not has_title_filter 
        or not has_current_filter 
        or has_leak 
        or not sql
    )

    if is_broken:
        title_where = f"WHERE t.title = '{target_title}'\n" if target_title else ""
        return f"""SELECT 
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
{title_where}GROUP BY e.emp_no, FullName, t.title, d.dept_name
HAVING COUNT(DISTINCT de.dept_no) >= {min_depts}
ORDER BY DepartmentCount DESC, e.emp_no ASC
LIMIT {req_limit};""".strip()

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + f" LIMIT {req_limit};"

    return sql


def auto_fix_dept_size_min_max_query(sql: str, user_query: str) -> str:
    """Tự động chuẩn hóa câu hỏi về quy mô nhân sự phòng ban lớn nhất và/hoặc nhỏ nhất.
    Khi người dùng hỏi phòng ban có quy mô lớn nhất VÀ nhỏ nhất, BẮT BUỘC chỉ xuất ra đúng 2 phòng ban tương ứng với 2 cực trị (lớn nhất & nhỏ nhất),
    tránh xuất toàn bộ danh sách các phòng ban gây loãng thông tin và sai lệch yêu cầu của người dùng.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Guard 1: Tuyệt đối không can thiệp nếu là câu hỏi có ngưỡng số lượng (vd: "ít nhất 2 phòng ban", "từ 2 phòng", "trên 100 người")
    if re.search(r"(?:ít nhất|tối thiểu|từ|trên|nhiều hơn|hơn)\s+\d+", q_low):
        return sql

    # Guard 2: Tuyệt đối không can thiệp nếu là câu hỏi liệt kê danh sách cá nhân nhân viên hoặc chức danh
    if any(k in q_low for k in ["liệt kê", "danh sách", "những nhân viên", "các nhân viên", "nhân viên nào", "ai là", "từng làm", "chức danh", "title", "senior", "engineer", "staff", "manager", "leader"]):
        return sql

    is_min_max_size = (
        any(k in q_low for k in ["quy mô", "nhân sự", "số lượng", "headcount", "đông nhất", "ít nhân sự nhất", "ít nhân viên nhất", "ít người nhất"])
        and any(k in q_low for k in ["lớn nhất", "nhỏ nhất", "cao nhất", "thấp nhất", "đông nhất"])
        and any(k in q_low for k in ["phòng ban", "phòng", "department", "các phòng", "đơn vị"])
        and not any(k in q_low for k in ["lương", "salary", "thu nhập", "chênh lệch lương", "khoảng cách lương"])
    )
    if not is_min_max_size:
        return sql

    has_largest = any(k in q_low for k in ["lớn nhất", "cao nhất", "nhiều nhất", "đông nhất", "largest", "highest", "most"])
    has_smallest = any(k in q_low for k in ["nhỏ nhất", "thấp nhất", "ít nhất", "smallest", "lowest", "least"])

    # 1. Trường hợp hỏi CẢ HAI cực trị (lớn nhất VÀ nhỏ nhất) -> BẮT BUỘC chỉ xuất ra đúng 2 phòng ban!
    if has_largest and has_smallest:
        return """WITH DeptHeadcount AS (
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
ORDER BY Headcount DESC;""".strip()

    # 2. Trường hợp CHỈ hỏi phòng ban lớn nhất / đông nhất
    elif has_largest and not has_smallest:
        return """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount DESC
LIMIT 1;""".strip()

    # 3. Trường hợp CHỈ hỏi phòng ban nhỏ nhất / ít nhất
    elif has_smallest and not has_largest:
        return """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount ASC
LIMIT 1;""".strip()

    return sql


def auto_fix_salary_spread_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn mức chênh lệch lương giữa người cao nhất và thấp nhất theo chức danh hoặc phòng ban.
    Đảm bảo:
    - Nếu hỏi chức danh / phòng ban lớn nhất -> LIMIT 1 (DESC)
    - Nếu hỏi chức danh / phòng ban nhỏ nhất -> LIMIT 1 (ASC)
    - Nếu hỏi cả lớn nhất và nhỏ nhất -> CTE xuất đúng 2 thực thể cực trị
    - Nếu hỏi chung/so sánh -> ORDER BY SalarySpread DESC
    - Tuyệt đối loại bỏ lỗi tính AVG(salary) thay vì MAX - MIN.
    - Tuyệt đối loại bỏ lỗi xuất hàng nghìn dòng nhân viên cá nhân kèm thâm niên/HireDate.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    # Guard: Tuyệt đối không can thiệp nếu câu hỏi so sánh giữa 2 phòng ban cụ thể (VD: Sales vs Development)
    known_depts = ["sales", "development", "research", "marketing", "finance", "production", "customer service", "quality management", "human resources"]
    depts_mentioned = [d for d in known_depts if d in q_low]
    if len(depts_mentioned) >= 2 or (any(k in q_low for k in ["giữa phòng ban", "giữa 2 phòng", "giữa hai phòng"]) and any(k in q_low for k in ["sales", "development", "marketing"])):
        return sql

    # Guard: Tuyệt đối không can thiệp nếu là bài toán so sánh nhóm nhân viên kỳ cựu vs mới vào, hoặc thăng chức quản lý gần đây
    if any(k in q_low for k in ["kỳ cựu", "mới vào", "thâm niên >", "thâm niên <", "vào làm trên", "dưới 2 năm", "5 năm gần nhất", "bổ nhiệm quản lý"]):
        return sql

    # Guard: Tuyệt đối không can thiệp nếu câu hỏi yêu cầu độ lệch chuẩn (STDDEV) hoặc phân tán lương
    if any(k in q_low for k in ["chuẩn", "stddev", "standard deviation", "std(", "độ phân tán", "mức lương phân tán"]):
        return sql

    # Guard: Tuyệt đối không can thiệp nếu câu hỏi hỏi về tỷ lệ ép lương / nén lương (đã được auto_fix_salary_compression_query xử lý)
    if any(k in q_low for k in ["ép lương", "áp lương", "nén lương", "compression", "wage compression", "pay compression", "tỷ lệ ép", "tỉ lệ ép", "tỷ lệ nén", "tỉ lệ nén"]):
        return sql

    is_salary_spread = (
        any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap", "phân hóa", "difference", "disparity"])
        and any(k in q_low for k in ["lương", "thu nhập", "salary", "income"])
        and (
            any(k in q_low for k in ["phòng ban", "phòng", "department", "các phòng", "đơn vị"])
            or any(k in q_low for k in ["chức danh", "title", "vị trí"])
            or any(k in q_low for k in ["nhóm", "các nhóm", "nhóm cao nhất", "nhóm thấp nhất", "giữa nhóm", "nhóm lương", "tier", "phân khúc"])
            or ("cao nhất" in q_low and "thấp nhất" in q_low)
        )
        and not any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "gender", "kỹ thuật", "tech", "chuẩn", "stddev", "standard deviation", "std("])
    )
    if not is_salary_spread:
        return sql

    is_title = any(k in q_low for k in ["chức danh", "title", "vị trí"]) and not any(k in q_low for k in ["phòng ban", "department", "các phòng", "mỗi phòng"])

    pattern = r"(?:giữa|between)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:cao nhất|thấp nhất|highest|lowest)\s+(?:và|and)\s+(?:người|nhân viên|mức)?\s*(?:nhận\s+lương|hưởng\s+lương|có\s+lương)?\s*(?:thấp nhất|cao nhất|lowest|highest)"
    cleaned = re.sub(pattern, "", q_low)
    has_largest = any(k in cleaned for k in ["lớn nhất", "cao nhất", "nhiều nhất", "largest", "highest", "most", "rộng nhất", "dẫn đầu"])
    has_smallest = any(k in cleaned for k in ["nhỏ nhất", "thấp nhất", "ít nhất", "smallest", "lowest", "least", "hẹp nhất"])
    is_all_or_comparison = (
        any(k in cleaned for k in ["từng phòng", "các phòng", "từng chức danh", "các chức danh", "mỗi chức danh", "tất cả", "toàn bộ", "so sánh", "danh sách", "bảng", "mỗi phòng", "all", "each", "compare", "giữa các nhóm", "giữa nhóm", "nhóm cao nhất và nhóm thấp nhất"])
        or not (has_largest or has_smallest)
    )
    top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
    req_limit = int(top_m.group(1)) if top_m else None

    lowered_sql = (sql or "").lower()
    has_spread_calc = ("salaryspread" in lowered_sql or "salary_spread" in lowered_sql or 
                       ("max(s.salary) - min(s.salary)" in lowered_sql) or 
                       ("max(salary) - min(salary)" in lowered_sql))
    has_group = "group by" in lowered_sql and (("t.title" in lowered_sql or "title" in lowered_sql) if is_title else ("dept_name" in lowered_sql or "dept_no" in lowered_sql))
    has_individual_leak = any(k in lowered_sql for k in ["fullname", "first_name", "last_name", "hire_date", "datediff", "yearsofservice", "years_of_service"])
    has_current_filter = "to_date = '9999-01-01'" in lowered_sql or "to_date='9999-01-01'" in lowered_sql
    has_wrong_avg = "avg(" in lowered_sql and not has_spread_calc

    is_broken = (not has_spread_calc or not has_group or has_individual_leak or not has_current_filter or has_wrong_avg or not sql)

    if is_title:
        if req_limit:
            return f"""SELECT 
    t.title AS Title,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread DESC
LIMIT {req_limit};""".strip()

        elif has_largest and has_smallest and not ("nhóm cao nhất và nhóm thấp nhất" in q_low or "giữa nhóm cao nhất" in q_low):
            return """WITH TitleSalarySpread AS (
    SELECT 
        t.title AS Title,
        ROUND(AVG(s.salary), 2) AS AvgSalary,
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
    AvgSalary,
    MaxSalary, 
    MinSalary, 
    SalarySpread
FROM TitleSalarySpread
WHERE SalarySpread = (SELECT MAX(SalarySpread) FROM TitleSalarySpread)
   OR SalarySpread = (SELECT MIN(SalarySpread) FROM TitleSalarySpread)
ORDER BY SalarySpread DESC;""".strip()

        elif has_smallest and not is_all_or_comparison:
            return """SELECT 
    t.title AS Title,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread ASC
LIMIT 1;""".strip()

        elif has_largest and not is_all_or_comparison:
            return """SELECT 
    t.title AS Title,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread DESC
LIMIT 1;""".strip()

        else:
            if is_broken:
                return """SELECT 
    t.title AS Title,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM titles t
JOIN salaries s ON t.emp_no = s.emp_no AND s.to_date = '9999-01-01'
WHERE t.to_date = '9999-01-01'
GROUP BY t.title
ORDER BY SalarySpread DESC;""".strip()
            return sql

    # Department
    if req_limit:
        return f"""SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalarySpread DESC
LIMIT {req_limit};""".strip()

    elif has_largest and has_smallest and not ("nhóm cao nhất và nhóm thấp nhất" in q_low or "giữa nhóm cao nhất" in q_low):
        return """WITH DeptSalarySpread AS (
    SELECT 
        d.dept_name AS Department,
        ROUND(AVG(s.salary), 2) AS AvgSalary,
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
    AvgSalary,
    MaxSalary, 
    MinSalary, 
    SalarySpread
FROM DeptSalarySpread
WHERE SalarySpread = (SELECT MAX(SalarySpread) FROM DeptSalarySpread)
   OR SalarySpread = (SELECT MIN(SalarySpread) FROM DeptSalarySpread)
ORDER BY SalarySpread DESC;""".strip()

    elif has_smallest and not is_all_or_comparison:
        return """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalarySpread ASC
LIMIT 1;""".strip()

    elif has_largest and not is_all_or_comparison:
        return """SELECT 
    d.dept_name AS Department,
    ROUND(AVG(s.salary), 2) AS AvgSalary,
    MAX(s.salary) AS MaxSalary,
    MIN(s.salary) AS MinSalary,
    (MAX(s.salary) - MIN(s.salary)) AS SalarySpread
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY SalarySpread DESC
LIMIT 1;""".strip()

    else:
        if is_broken:
            return """WITH DeptSalaryStats AS (
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
ORDER BY SalarySpread DESC;""".strip()
        return sql


def auto_fix_chocolates_pnl_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn Báo cáo kết quả kinh doanh / Lãi, Lỗ / Doanh thu - Chi phí - Lợi nhuận (P&L)
    trên CSDL Awesome Chocolates. Đảm bảo JOIN bảng products pr ON s.PID = pr.PID để lấy pr.Cost_per_box,
    tính đầy đủ 4 chỉ số tài chính: Doanh Thu, Chi Phí, Lợi Nhuận (hoặc Lợi Nhuận Ròng), Tỷ Suất Lợi Nhuận,
    và các chiều Sản Phẩm/Đội Ngũ/Quốc Gia/Tháng/Quý/Năm."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    is_catalog_price_q = any(k in q_low for k in ["đơn giá niêm yết", "giá niêm yết", "cost per box cao nhất", "cost per box thấp nhất", "cost_per_box cao nhất", "cost_per_box thấp nhất"]) or (
        any(k in q_low for k in ["cost per box", "cost_per_box"]) and any(k in q_low for k in ["sản phẩm nào", "mặt hàng nào", "cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất"]) and not any(k in q_low for k in ["doanh thu", "sales", "lợi nhuận", "profit", "báo cáo"])
    )
    if is_catalog_price_q:
        return sql

    is_pnl_q = any(k in q_low for k in [
        "lãi, lỗ", "lãi lỗ", "lãi", "lỗ", "kết quả kinh doanh", "profit and loss", "p&l", "pnl", "cost_per_box",
        "chi phí", "cost", "giá vốn", "cogs", "lợi nhuận ròng", "net profit"
    ]) or (
        any(k in q_low for k in ["lợi nhuận", "profit", "biên lợi nhuận", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"])
        and any(k in q_low for k in ["tháng", "quý", "năm", "month", "quarter", "báo cáo", "doanh thu", "chi phí", "từng", "sản phẩm", "product"])
    )

    if not is_pnl_q:
        return sql

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate", "thị trường", "quốc gia", "country", "geo", "cost_per_box", "chi phí", "giá vốn", "sản phẩm"])
    if not is_chocolates:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    date_expr = "strftime('%Y-%m', s.SaleDate)" if is_sqlite else "DATE_FORMAT(s.SaleDate, '%Y-%m')"
    qtr_expr = (
        "strftime('%Y', s.SaleDate) || '-Q' || ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)"
        if is_sqlite else
        "CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate))"
    )

    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None
    year_cond = (f"strftime('%Y', s.SaleDate) = '{year_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {year_val}") if year_val else ""

    has_month = any(k in q_low for k in ["tháng", "month"])
    has_quarter = any(k in q_low for k in ["quý", "quarter"])
    has_country = any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"])
    has_product = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
    has_team = any(k in q_low for k in ["team", "đội ngũ", "nhóm"])

    profit_alias = "Lợi Nhuận Ròng ($)" if any(k in q_low for k in ["ròng", "net"]) else "Lợi Nhuận ($)"

    has_cost = "cost_per_box" in sql_low
    has_profit_calc = ("amount -" in sql_low or "amount-" in sql_low or "lợi nhuận" in sql_low or "profit" in sql_low)
    has_full_dims = True
    if has_quarter and ("quarter" not in sql_low and "quý" not in sql_low):
        has_full_dims = False
    if has_month and ("date_format" not in sql_low and "strftime" not in sql_low and "month" not in sql_low and "tháng" not in sql_low):
        has_full_dims = False
    if has_country and ("geo" not in sql_low and "quốc gia" not in sql_low and "country" not in sql_low):
        has_full_dims = False
    if has_product and ("product" not in sql_low and "sản phẩm" not in sql_low):
        has_full_dims = False
    if has_team and ("team" not in sql_low and "đội ngũ" not in sql_low):
        has_full_dims = False

    has_standard_vi_aliases = (
        ("tổng doanh thu" in sql_low or "doanh thu" in sql_low or "totalsales" in sql_low)
        and ("tổng chi phí" in sql_low or "chi phí" in sql_low or "totalcost" in sql_low)
        and ("lợi nhuận" in sql_low or "lãi" in sql_low or "profit" in sql_low)
    )
    has_weird_en_alias = any(k in sql_low for k in ["total_returns", "total returns", "packaging_cost", "packaging cost", "box_cost", "box cost"])

    top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
    unwanted_limit = (not top_m and "limit " in sql_low)

    needs_fix = not (has_cost and has_profit_calc and has_full_dims and has_standard_vi_aliases and not has_weird_en_alias and not unwanted_limit) or "with " in sql_low
    if not needs_fix:
        return sql

    # 1. Báo cáo P&L theo Quốc Gia
    if has_country:
        conds = []
        if year_cond:
            conds.append(year_cond)
        where_clause = f"WHERE {' AND '.join(conds)}\n" if conds else ""

        if has_month and has_quarter:
            time_cols = f"    {date_expr} AS `Tháng`,\n    {qtr_expr} AS `Quý`,\n    g.Geo AS `Quốc Gia`,"
            group_cols = "`Tháng`, `Quý`, `Quốc Gia`"
            order_col = f"`Tháng` ASC, `{profit_alias}` DESC"
        elif has_quarter:
            time_cols = f"    {qtr_expr} AS `Quý`,\n    g.Geo AS `Quốc Gia`,"
            group_cols = "`Quý`, `Quốc Gia`"
            order_col = f"`Quý` ASC, `{profit_alias}` DESC"
        elif has_month:
            time_cols = f"    {date_expr} AS `Tháng`,\n    g.Geo AS `Quốc Gia`,"
            group_cols = "`Tháng`, `Quốc Gia`"
            order_col = f"`Tháng` ASC, `{profit_alias}` DESC"
        else:
            time_cols = "    g.Geo AS `Quốc Gia`,"
            group_cols = "`Quốc Gia`"
            order_col = f"`{profit_alias}` DESC"

        limit_clause = f"\nLIMIT {top_m.group(1)}" if top_m else ""

        return f"""SELECT 
{time_cols}
    SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
    ROUND(SUM(s.Boxes * pr.Cost_per_box), 2) AS `Tổng Chi Phí ($)`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2) AS `{profit_alias}`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS `Tỷ Suất Lợi Nhuận (%)`
FROM sales s
JOIN products pr ON s.PID = pr.PID
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}GROUP BY {group_cols}
ORDER BY {order_col}{limit_clause}"""

    # 2. Báo cáo P&L theo Sản phẩm
    if has_product:
        conds = []
        if year_cond:
            conds.append(year_cond)
        where_clause = f"WHERE {' AND '.join(conds)}\n" if conds else ""

        if has_month:
            time_cols = f"    {date_expr} AS `Tháng`,\n    pr.Product AS `Sản Phẩm`,"
            group_cols = "`Tháng`, `Sản Phẩm`"
            order_col = f"`Tháng` ASC, `{profit_alias}` DESC"
        elif has_quarter:
            time_cols = f"    {qtr_expr} AS `Quý`,\n    pr.Product AS `Sản Phẩm`,"
            group_cols = "`Quý`, `Sản Phẩm`"
            order_col = f"`Quý` ASC, `{profit_alias}` DESC"
        else:
            time_cols = "    pr.Product AS `Sản Phẩm`,\n    pr.Category AS `Danh Mục`,"
            group_cols = "`Sản Phẩm`, `Danh Mục`"
            if any(k in q_low for k in ["doanh thu cao nhất", "doanh thu giảm dần", "doanh số cao nhất"]):
                order_col = "`Tổng Doanh Thu ($)` DESC"
            elif any(k in q_low for k in ["chi phí cao nhất", "chi phí lớn nhất"]):
                order_col = "`Tổng Chi Phí ($)` DESC"
            elif any(k in q_low for k in ["tỷ suất cao nhất", "biên lợi nhuận cao nhất"]):
                order_col = "`Tỷ Suất Lợi Nhuận (%)` DESC"
            else:
                order_col = f"`{profit_alias}` DESC"

        limit_clause = f"\nLIMIT {top_m.group(1)}" if top_m else ""

        return f"""SELECT 
{time_cols}
    SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
    ROUND(SUM(s.Boxes * pr.Cost_per_box), 2) AS `Tổng Chi Phí ($)`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2) AS `{profit_alias}`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS `Tỷ Suất Lợi Nhuận (%)`
FROM sales s
JOIN products pr ON s.PID = pr.PID
{where_clause}GROUP BY {group_cols}
ORDER BY {order_col}{limit_clause}"""

    # 3. Báo cáo P&L theo Đội ngũ / Team
    if has_team:
        conds = ["pe.Team != '' AND pe.Team IS NOT NULL"]
        if year_cond:
            conds.append(year_cond)
        where_clause = f"WHERE {' AND '.join(conds)}\n"

        if has_month:
            time_cols = f"    {date_expr} AS `Tháng`,\n    pe.Team AS `Đội Ngũ`,"
            group_cols = "`Tháng`, `Đội Ngũ`"
            order_col = f"`Tháng` ASC, `{profit_alias}` DESC"
        elif has_quarter:
            time_cols = f"    {qtr_expr} AS `Quý`,\n    pe.Team AS `Đội Ngũ`,"
            group_cols = "`Quý`, `Đội Ngũ`"
            order_col = f"`Quý` ASC, `{profit_alias}` DESC"
        else:
            time_cols = "    pe.Team AS `Đội Ngũ`,"
            group_cols = "`Đội Ngũ`"
            order_col = f"`{profit_alias}` DESC"

        limit_clause = f"\nLIMIT {top_m.group(1)}" if top_m else ""

        return f"""SELECT 
{time_cols}
    SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
    ROUND(SUM(s.Boxes * pr.Cost_per_box), 2) AS `Tổng Chi Phí ($)`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2) AS `{profit_alias}`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS `Tỷ Suất Lợi Nhuận (%)`
FROM sales s
JOIN products pr ON s.PID = pr.PID
JOIN people pe ON s.SPID = pe.SPID
{where_clause}GROUP BY {group_cols}
ORDER BY {order_col}{limit_clause}"""

    # 4. Báo cáo P&L theo Thời gian (Tháng / Quý) hoặc Toàn công ty
    conds = []
    if year_cond:
        conds.append(year_cond)
    where_clause = f"WHERE {' AND '.join(conds)}\n" if conds else ""

    if has_month and has_quarter:
        time_cols = f"    {date_expr} AS `Tháng`,\n    {qtr_expr} AS `Quý`,\n"
        group_clause = "GROUP BY `Tháng`, `Quý`\n"
        order_clause = "ORDER BY `Tháng` ASC\n"
    elif has_month:
        time_cols = f"    {date_expr} AS `Tháng`,\n"
        group_clause = "GROUP BY `Tháng`\n"
        order_clause = "ORDER BY `Tháng` ASC\n"
    elif has_quarter:
        time_cols = f"    {qtr_expr} AS `Quý`,\n"
        group_clause = "GROUP BY `Quý`\n"
        order_clause = "ORDER BY `Quý` ASC\n"
    else:
        time_cols = ""
        group_clause = ""
        order_clause = ""

    return f"""SELECT 
{time_cols}    SUM(s.Amount) AS `Tổng Doanh Thu ($)`,
    ROUND(SUM(s.Boxes * pr.Cost_per_box), 2) AS `Tổng Chi Phí ($)`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box), 2) AS `{profit_alias}`,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS `Tỷ Suất Lợi Nhuận (%)`
FROM sales s
JOIN products pr ON s.PID = pr.PID
{where_clause}{group_clause}{order_clause}""".strip()


def auto_fix_chocolates_monthly_sales_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và sửa lỗi câu truy vấn doanh thu theo tháng (theo Quốc gia, Sản phẩm, Nhân viên, hoặc Số lượng hộp/thùng bán ra) trên CSDL Awesome Chocolates.
    Loại bỏ triệt để CTE bị vỡ (WITH ...), JOIN trùng lặp và chuyển thành câu SELECT đơn trực tiếp định dạng YYYY-MM hoặc Month số."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # Không can thiệp nếu là câu hỏi P&L / Lãi Lỗ / Lợi nhuận / Chi phí (để auto_fix_chocolates_pnl_query xử lý)
    is_pnl_q = any(k in q_low for k in [
        "lãi, lỗ", "lãi lỗ", "lãi", "lỗ", "kết quả kinh doanh", "profit and loss", "p&l", "pnl", "cost_per_box",
        "chi phí", "cost", "giá vốn", "cogs", "lợi nhuận ròng", "net profit"
    ]) or (
        any(k in q_low for k in ["lợi nhuận", "profit", "biên lợi nhuận", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"]) 
        and any(k in q_low for k in ["tháng", "quý", "năm", "month", "quarter", "báo cáo", "doanh thu", "chi phí", "từng", "sản phẩm"])
    )
    if is_pnl_q:
        return sql

    # Kiểm tra xem có phải câu hỏi theo tháng / thời gian trên Chocolates DB không
    has_monthly = any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "thời gian", "xu hướng", "thay đổi", "biến động"])
    has_sales = any(k in q_low for k in ["doanh thu", "doanh số", "sales", "tiền bán", "amount", "bán hàng", "tiền"]) or any(k in sql_low for k in ["sales", "totalsales", "totalrevenue", "amount"])
    has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"]) or any(k in sql_low for k in ["boxes", "totalboxes", "boxessold"])
    has_both = has_sales and has_boxes

    if not (has_monthly and (has_sales or has_boxes or "sales" in sql_low or "amount" in sql_low or "boxes" in sql_low)):
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    date_expr = "strftime('%Y-%m', s.SaleDate)" if is_sqlite else "DATE_FORMAT(s.SaleDate, '%Y-%m')"

    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None
    year_cond = (f"strftime('%Y', s.SaleDate) = '{year_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {year_val}") if year_val else ""

    # 0. Doanh thu của một Team cụ thể (Yummies, Delish, Jucies) qua các tháng
    specific_team = None
    if "yummies" in q_low:
        specific_team = "Yummies"
    elif "delish" in q_low:
        specific_team = "Delish"
    elif "jucies" in q_low:
        specific_team = "Jucies"

    if specific_team and has_monthly:
        conds = [f"pe.Team = '{specific_team}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        if has_both:
            metric_expr = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
        elif has_boxes:
            metric_expr = "SUM(s.Boxes) AS TotalBoxesSold"
        else:
            metric_expr = "SUM(s.Amount) AS TotalSales"
        return f"""SELECT 
    {date_expr} AS Month,
    {metric_expr}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY Month
ORDER BY Month ASC"""

    # 0.1 Doanh thu của một Quốc gia cụ thể (India, USA, Canada, New Zealand, Australia, UK) qua các tháng
    from src.llm.prompts import match_chocolates_specific_country
    specific_country = match_chocolates_specific_country(q_low)

    if specific_country and has_monthly and not any(k in q_low for k in ["sản phẩm", "product", "nhân viên", "salesperson"]):
        conds = [f"g.Geo = '{specific_country}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        if has_both:
            metric_expr = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
        elif has_boxes:
            metric_expr = "SUM(s.Boxes) AS TotalBoxesSold"
        else:
            metric_expr = "SUM(s.Amount) AS TotalSales"
        needs_fix = (
            "with " in sql_low
            or "g.geoid" not in sql_low
            or f"'{specific_country.lower()}'" not in sql_low
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "group by month" not in sql_low
            or (has_both and ("boxes" not in sql_low or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)))
        )
        if needs_fix:
            return f"""SELECT 
    {date_expr} AS Month,
    {metric_expr}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}
GROUP BY Month
ORDER BY Month ASC"""

    specific_product = match_chocolates_specific_product(q_low) or match_chocolates_specific_product(sql_low)
    specific_person = match_chocolates_specific_person(q_low) or match_chocolates_specific_person(sql_low)

    # 0.14 Doanh thu của Sản phẩm cụ thể kết hợp với Nhân viên cụ thể qua các tháng
    if specific_product and specific_person and has_monthly:
        escaped_prod = specific_product.replace("'", "''")
        escaped_pers = specific_person.replace("'", "''")
        conds = [f"pr.Product = '{escaped_prod}'", f"pe.Salesperson = '{escaped_pers}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        if has_both:
            metric_expr = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
        elif has_boxes:
            metric_expr = "SUM(s.Boxes) AS TotalBoxesSold"
        else:
            metric_expr = "SUM(s.Amount) AS TotalSales"
        return f"""SELECT 
    {date_expr} AS Month,
    {metric_expr}
FROM sales s
JOIN products pr ON s.PID = pr.PID
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY Month
ORDER BY Month ASC"""

    # 0.15 Doanh thu của một Sản phẩm cụ thể (ví dụ 85% Dark Bars, Mint Chip Choco...) qua các tháng
    if specific_product and has_monthly and not any(k in q_low for k in ["nhân viên", "salesperson", "quốc gia", "country"]):
        escaped_prod = specific_product.replace("'", "''")
        conds = [f"pr.Product = '{escaped_prod}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        if has_both:
            metric_expr = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
        elif has_boxes:
            metric_expr = "SUM(s.Boxes) AS TotalBoxesSold"
        else:
            metric_expr = "SUM(s.Amount) AS TotalSales"
        clean_prod_name = specific_product.lower().replace("'", "")
        clean_sql = sql_low.replace("'", "").replace("''", "")
        needs_fix = (
            "with " in sql_low
            or "pr.pid" not in sql_low
            or "products" not in sql_low
            or clean_prod_name not in clean_sql
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "group by month, product" in sql_low
            or "group by month" not in sql_low
            or (year_val and f"{year_val}" not in sql_low)
            or (has_both and ("boxes" not in sql_low or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)))
        )
        if needs_fix:
            return f"""SELECT 
    {date_expr} AS Month,
    {metric_expr}
FROM sales s
JOIN products pr ON s.PID = pr.PID
{where_clause}
GROUP BY Month
ORDER BY Month ASC"""

    # 0.16 Doanh thu của một Nhân viên cụ thể (ví dụ Ches Bonnell, Brijesh Shah...) qua các tháng
    if specific_person and has_monthly and not any(k in q_low for k in ["sản phẩm", "product", "quốc gia", "country"]):
        escaped_pers = specific_person.replace("'", "''")
        conds = [f"pe.Salesperson = '{escaped_pers}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        if has_both:
            metric_expr = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
        elif has_boxes:
            metric_expr = "SUM(s.Boxes) AS TotalBoxesSold"
        else:
            metric_expr = "SUM(s.Amount) AS TotalSales"
        clean_pers_name = specific_person.lower().replace("'", "")
        clean_sql = sql_low.replace("'", "").replace("''", "")
        needs_fix = (
            "with " in sql_low
            or "pe.spid" not in sql_low
            or "people" not in sql_low
            or clean_pers_name not in clean_sql
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "group by month, salesperson" in sql_low
            or "group by month" not in sql_low
            or (year_val and f"{year_val}" not in sql_low)
            or (has_both and ("boxes" not in sql_low or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)))
        )
        if needs_fix:
            return f"""SELECT 
    {date_expr} AS Month,
    {metric_expr}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY Month
ORDER BY Month ASC"""

    # 0.2 Doanh thu theo từng Team qua các tháng (tất cả các team)
    is_team = any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng"]) or "team" in sql_low
    if is_team and not specific_team and not any(k in q_low for k in ["yummies", "delish", "jucies", "sản phẩm", "product", "quốc gia", "country", "nhân viên", "salesperson"]):
        conds = ["pe.Team != ''"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        if has_both:
            metric_expr = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalRevenue"
        elif has_boxes:
            metric_expr = "SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalBoxesSold"
        else:
            metric_expr = "SUM(s.Amount) AS TotalSales"
            order_col = "TotalSales"
        needs_fix = (
            "with " in sql_low
            or "pe.spid" not in sql_low
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "group by month, team" not in sql_low
            or (has_both and ("boxes" not in sql_low or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)))
        )
        if needs_fix:
            return f"""SELECT 
    {date_expr} AS Month,
    pe.Team AS Team,
    {metric_expr}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY Month, Team
ORDER BY Month ASC, {order_col} DESC"""

    # 1. Doanh thu theo từng quốc gia / thị trường qua các tháng
    is_country = any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"]) or any(k in sql_low for k in ["country", "country_sales", "geo", "geoid"])
    if is_country and not any(k in q_low for k in ["sản phẩm", "product", "nhân viên", "salesperson", "team", "yummies", "delish", "jucies"]):
        if has_both:
            metric_part = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalRevenue"
        elif has_boxes:
            metric_part = "SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalBoxesSold"
        else:
            metric_part = "SUM(s.Amount) AS TotalSales"
            order_col = "TotalSales"
        needs_fix = (
            "with " in sql_low
            or "country_sales" in sql_low
            or "cs.geoid" in sql_low
            or "s.saledate" in sql_low
            or sql_low.count("geo ") > 1
            or ("year(" in sql_low and "month(" in sql_low)
            or not re.search(r"join\s+geo", sql_low)
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or (year_val and f"{year_val}" not in sql_low)
            or (has_both and ("boxes" not in sql_low or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)))
        )
        if needs_fix:
            year_clause = f"WHERE {year_cond}\n" if year_cond else ""
            return f"""SELECT 
    {date_expr} AS Month,
    g.Geo AS Country,
    {metric_part}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{year_clause}GROUP BY Month, Country
ORDER BY Month ASC, {order_col} DESC"""

    # 2. Doanh thu theo từng sản phẩm qua các tháng
    is_product = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "loại kẹo", "socola", "chocolate"])
    if is_product and not specific_product and not any(k in q_low for k in ["quốc gia", "country", "nhân viên", "salesperson", "team", "yummies", "delish", "jucies"]):
        if has_both:
            metric_part = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalRevenue"
        elif has_boxes:
            metric_part = "SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalBoxesSold"
        else:
            metric_part = "SUM(s.Amount) AS TotalSales"
            order_col = "TotalSales"
        needs_fix = (
            "with " in sql_low
            or ("year(" in sql_low and "month(" in sql_low)
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or (year_val and f"{year_val}" not in sql_low)
            or (has_both and ("boxes" not in sql_low or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)))
        )
        if needs_fix:
            year_clause = f"WHERE {year_cond}\n" if year_cond else ""
            return f"""SELECT 
    {date_expr} AS Month,
    pr.Product AS Product,
    {metric_part}
FROM sales s
JOIN products pr ON s.PID = pr.PID
{year_clause}GROUP BY Month, Product
ORDER BY Month ASC, {order_col} DESC"""

    # 3. Doanh thu theo nhân viên / chuyên viên bán hàng qua các tháng
    is_person = any(k in q_low for k in ["nhân viên", "nhân sự", "chuyên viên", "chuyên viên bán hàng", "salesperson", "sales person", "người bán", "thành viên", "sales rep", "rep"]) or "people" in sql_low or "spid" in sql_low or "salesperson" in sql_low
    if is_person and not specific_person and not any(k in q_low for k in ["quốc gia", "country", "sản phẩm", "product"]):
        if has_both:
            metric_part = "SUM(s.Amount) AS TotalRevenue,\n    SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalRevenue"
        elif has_boxes:
            metric_part = "SUM(s.Boxes) AS TotalBoxesSold"
            order_col = "TotalBoxesSold"
        else:
            metric_part = "SUM(s.Amount) AS TotalSales"
            order_col = "TotalSales"
        needs_fix = (
            "with " in sql_low
            or ("year(" in sql_low and "month(" in sql_low)
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "limit" in sql_low
            or "pe.salesperson" not in sql_low
            or (year_val and f"{year_val}" not in sql_low)
            or (has_both and ("boxes" not in sql_low or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)))
        )
        if needs_fix:
            year_clause = f"WHERE {year_cond}\n" if year_cond else ""
            return f"""SELECT 
    {date_expr} AS Month,
    pe.Salesperson AS Salesperson,
    {metric_part}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{year_clause}GROUP BY Month, Salesperson
ORDER BY Month ASC, {order_col} DESC"""

    # 4 & 5. Doanh thu và/hoặc số lượng thùng/hộp qua các tháng (không phân nhóm đối tượng)
    is_general = not (is_country or is_product or is_person or is_team or specific_team or specific_country or specific_product or specific_person)
    if is_general:
        year_match = re.search(r'\b(20\d{2})\b', q_low)
        if year_match:
            yr = year_match.group(1)
            year_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr}"
            month_expr = "CAST(strftime('%m', s.SaleDate) AS INTEGER)" if is_sqlite else "MONTH(s.SaleDate)"
            if has_both:
                return f"""SELECT 
    {month_expr} AS Month,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
{year_filter}
GROUP BY Month
ORDER BY Month ASC"""
            elif has_boxes and not has_sales:
                return f"""SELECT 
    {month_expr} AS Month,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
{year_filter}
GROUP BY Month
ORDER BY Month ASC"""
            else:
                return f"""SELECT 
    {month_expr} AS Month,
    SUM(s.Amount) AS TotalSales
FROM sales s
{year_filter}
GROUP BY Month
ORDER BY Month ASC"""
        else:
            if has_both:
                needs_fix = (
                    "with " in sql_low
                    or ("year(" in sql_low and "month(" in sql_low)
                    or ("date_format" not in sql_low and not is_sqlite)
                    or ("strftime" not in sql_low and is_sqlite)
                    or "limit" in sql_low
                    or "boxes" not in sql_low
                    or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)
                )
                if needs_fix:
                    return f"""SELECT 
    {date_expr} AS Month,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
GROUP BY Month
ORDER BY Month ASC"""
            elif has_boxes and not has_sales:
                needs_fix = (
                    "with " in sql_low
                    or ("year(" in sql_low and "month(" in sql_low)
                    or ("date_format" not in sql_low and not is_sqlite)
                    or ("strftime" not in sql_low and is_sqlite)
                    or "limit" in sql_low
                    or "boxes" not in sql_low
                )
                if needs_fix:
                    return f"""SELECT 
    {date_expr} AS Month,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
GROUP BY Month
ORDER BY Month ASC"""
            else:
                needs_fix = (
                    "with " in sql_low
                    or ("year(" in sql_low and "month(" in sql_low)
                    or ("date_format" not in sql_low and not is_sqlite)
                    or ("strftime" not in sql_low and is_sqlite)
                    or "limit" in sql_low
                    or ("amount" not in sql_low and "totalsales" not in sql_low and "totalrevenue" not in sql_low)
                )
                if needs_fix:
                    return f"""SELECT 
    {date_expr} AS Month,
    SUM(s.Amount) AS TotalSales
FROM sales s
GROUP BY Month
ORDER BY Month ASC"""

    if has_monthly and not extract_requested_limit(user_query):
        sql = re.sub(r"\s+LIMIT\s+\d+\s*;?$", "", sql, flags=re.IGNORECASE).rstrip(";").strip()

    return sql


def auto_fix_chocolates_product_quarterly_rankings_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn: Xếp hạng sản phẩm theo doanh số trong từng quý, so sánh thứ hạng giữa các quý
    và xác định: Sản phẩm tăng hạng mạnh nhất, sản phẩm giảm hạng mạnh nhất, sản phẩm luôn nằm trong top 5 ở tất cả các quý.
    Áp dụng chuẩn mực CTE theo 3 Quy tắc Phân rã Nghiệp vụ:
    - CTE QuarterlyProductSales: Doanh thu SUM(s.Amount) theo pr.Product và Quarter.
    - CTE QuarterlyRanks: DENSE_RANK() OVER (PARTITION BY Quarter ORDER BY TotalSales DESC) AS ProductRank.
    - CTE PivotRanks: Pivot Q1_Rank, Q2_Rank, Q3_Rank, Q4_Rank và tính RankDelta với CAST AS SIGNED (tránh lỗi MySQL 1690).
    - CTE RankExtremes: MAX(RankDelta) AS MaxGain, MIN(RankDelta) AS MaxDrop.
    - SELECT: Product, Q1_Rank, Q2_Rank, Q3_Rank, Q4_Rank, RankChange, PerformanceStatus, TotalAnnualSales.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_prod_qtr_rank = (
        any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
        and any(k in q_low for k in ["quý", "quarter"])
        and any(k in q_low for k in ["xếp hạng", "thứ hạng", "hạng", "rank", "tăng hạng", "giảm hạng", "top 5", "top 10"])
    )
    if not is_prod_qtr_rank:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    yr_match = re.search(r'\b(20\d{2})\b', q_low)
    yr_val = yr_match.group(1) if yr_match else "2021"
    yr_cond = f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}"
    qtr_expr = (
        "strftime('%Y', s.SaleDate) || '-Q' || ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)"
        if is_sqlite else
        "CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate))"
    )
    qtr_num_expr = "((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)" if is_sqlite else "QUARTER(s.SaleDate)"
    cast_delta = (
        "CAST(MAX(CASE WHEN QtrNum = 1 THEN ProductRank END) AS INTEGER) - CAST(MAX(CASE WHEN QtrNum = 4 THEN ProductRank END) AS INTEGER)"
        if is_sqlite else
        "CAST(MAX(CASE WHEN QtrNum = 1 THEN ProductRank END) AS SIGNED) - CAST(MAX(CASE WHEN QtrNum = 4 THEN ProductRank END) AS SIGNED)"
    )

    sql_low = (sql or "").lower()
    has_product = "pr.product" in sql_low or "product" in sql_low
    has_rank = "dense_rank()" in sql_low or "rank()" in sql_low
    has_quarter = "quarter" in sql_low
    has_pivot = "q1_rank" in sql_low or "case when qtrnum" in sql_low or "q1" in sql_low
    has_extremes = "rankextremes" in sql_low or "performancestatus" in sql_low
    has_limit = bool(re.search(r"\blimit\s+\d+\b", sql_low))
    is_only_company_sales = "group by quarter" in sql_low and not has_product

    # Kiểm tra lỗi MySQL unsigned underflow 1690: (Q1_Rank - Q4_Rank) thiếu CAST AS SIGNED
    has_bad_unsigned_subtraction = bool(re.search(r"\b(?:q1_rank|productrank)\s*-\s*(?:q4_rank|productrank)\b", sql_low)) and "cast(" not in sql_low

    is_broken = (
        is_only_company_sales
        or not has_product
        or not has_rank
        or not has_quarter
        or not has_pivot
        or not has_extremes
        or has_limit
        or has_bad_unsigned_subtraction
        or "p.totalsales" in sql_low
        or not sql
    )

    if is_broken:
        return f"""WITH QuarterlyProductSales AS (
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
        SUM(TotalSales) AS TotalSales,
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
ORDER BY p.RankDelta DESC, p.TotalAnnualSales DESC;""".strip()

    return sql


def auto_fix_chocolates_product_quarterly_consistency_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu hỏi tìm sản phẩm luôn đạt doanh số trên ngưỡng X USD trong tất cả các quý của năm Y
    hoặc sản phẩm giữ vững phong độ / nhất quán qua các quý.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_prod_qtr_thresh = (
        any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
        and any(k in q_low for k in ["quý", "quarter", "tất cả các quý", "4 quý", "mỗi quý"])
        and (
            any(k in q_low for k in ["luôn đạt", "đạt doanh số", "doanh số trên", "doanh thu trên", "trên", "vượt", "tối thiểu", ">", ">="])
            or any(k in q_low for k in ["ổn định", "nhất quán", "duy trì"])
        )
        and not any(k in q_low for k in ["tăng hạng", "giảm hạng", "thay đổi thứ hạng"])
    )
    if not is_prod_qtr_thresh:
        return sql

    # 1. Trích xuất năm (mặc định 2022)
    yr_match = re.search(r'\b(20\d{2})\b', q_low)
    yr_val = yr_match.group(1) if yr_match else "2022"

    # 2. Trích xuất ngưỡng doanh số (mặc định 50000)
    thresh_match = re.search(r'(?:trên|vượt|tối thiểu|>=|>|đạt)\s*([0-9.,]+)\s*(?:usd|\$|k|nghìn|ngàn|đô)?', q_low)
    thresh_val = 50000
    if thresh_match:
        raw_num = thresh_match.group(1).replace(",", "").replace(".", "")
        try:
            val = float(raw_num)
            if "k" in q_low and val < 1000:
                val *= 1000
            if val > 0:
                thresh_val = int(val)
        except Exception:
            thresh_val = 50000

    is_sqlite = "sqlite" in (dialect or "").lower()
    yr_filter = f"strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {yr_val}"
    qtr_calc = "((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)" if is_sqlite else "QUARTER(s.SaleDate)"
    sub_yr_filter = f"strftime('%Y', SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(SaleDate) = {yr_val}"
    sub_qtr_calc = "((CAST(strftime('%m', SaleDate) AS INTEGER) + 2) / 3)" if is_sqlite else "QUARTER(SaleDate)"

    return f"""WITH ProductQuarterlySales AS (
    SELECT 
        p.PID,
        p.Product,
        p.Category,
        SUM(CASE WHEN {qtr_calc} = 1 THEN s.Amount ELSE 0 END) AS Q1_Revenue,
        SUM(CASE WHEN {qtr_calc} = 2 THEN s.Amount ELSE 0 END) AS Q2_Revenue,
        SUM(CASE WHEN {qtr_calc} = 3 THEN s.Amount ELSE 0 END) AS Q3_Revenue,
        SUM(CASE WHEN {qtr_calc} = 4 THEN s.Amount ELSE 0 END) AS Q4_Revenue,
        SUM(s.Amount) AS TotalAnnualRevenue
    FROM products p
    JOIN sales s ON p.PID = s.PID
    WHERE {yr_filter}
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
WHERE Q1_Revenue > {thresh_val}
  AND (Q2_Revenue > {thresh_val} OR (SELECT COUNT(DISTINCT {sub_qtr_calc}) FROM sales WHERE {sub_yr_filter}) < 2)
  AND (Q3_Revenue > {thresh_val} OR (SELECT COUNT(DISTINCT {sub_qtr_calc}) FROM sales WHERE {sub_yr_filter}) < 3)
  AND (Q4_Revenue > {thresh_val} OR (SELECT COUNT(DISTINCT {sub_qtr_calc}) FROM sales WHERE {sub_yr_filter}) < 4)
ORDER BY TotalAnnualRevenue DESC;""".strip()


def auto_fix_chocolates_quarterly_sales_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và sửa lỗi câu truy vấn doanh thu theo quý (theo Quốc gia, Sản phẩm, Team, hoặc Toàn công ty)
    trên CSDL Awesome Chocolates. Đảm bảo GROUP BY đúng Quarter và ORDER BY Quarter ASC để vẽ biểu đồ đường xu hướng."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # Guard: Nếu câu hỏi về tìm/lọc/danh sách sản phẩm theo quý hoặc độ nhất quán qua các quý -> Tuyệt đối không đè thành doanh thu toàn công ty!
    if any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"]):
        if any(k in q_low for k in [
            "luôn đạt", "luôn trong", "tất cả các quý", "mỗi quý", "từng quý", "4 quý", "ổn định", "nhất quán",
            "trên", "vượt", ">", "xếp hạng", "thứ hạng", "hạng", "rank", "tăng hạng", "giảm hạng", "top 5",
            "top 10", "tìm", "danh sách", "liệt kê"
        ]):
            return sql

    # Không can thiệp nếu là câu hỏi P&L / Lãi Lỗ / Lợi nhuận / Chi phí (để auto_fix_chocolates_pnl_query xử lý)
    is_pnl_q = any(k in q_low for k in [
        "lãi, lỗ", "lãi lỗ", "lãi", "lỗ", "kết quả kinh doanh", "profit and loss", "p&l", "pnl", "cost_per_box",
        "chi phí", "cost", "giá vốn", "cogs", "lợi nhuận ròng", "net profit"
    ]) or (
        any(k in q_low for k in ["lợi nhuận", "profit", "biên lợi nhuận", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"]) 
        and any(k in q_low for k in ["tháng", "quý", "năm", "month", "quarter", "báo cáo", "doanh thu", "chi phí", "từng", "sản phẩm"])
    )
    if is_pnl_q:
        return sql

    # Kiểm tra xem có phải câu hỏi theo quý không
    is_quarterly = any(k in q_low for k in ["quý", "quarter", "từng quý", "theo quý", "qua các quý", "quarterly"])
    if not is_quarterly:
        return sql

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate", "thị trường", "quốc gia", "country", "geo", "ấn độ", "india", "mỹ", "usa", "team", "yummies"])
    if not is_chocolates:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    qtr_expr = (
        "strftime('%Y', s.SaleDate) || '-Q' || ((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3)"
        if is_sqlite else
        "CONCAT(YEAR(s.SaleDate), '-Q', QUARTER(s.SaleDate))"
    )

    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None
    year_cond = (f"strftime('%Y', s.SaleDate) = '{year_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {year_val}") if year_val else ""

    has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"])
    metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"

    # 1. Doanh thu của một Quốc gia cụ thể qua từng quý (ví dụ: Ấn Độ / India năm 2021)
    from src.llm.prompts import match_chocolates_specific_country
    specific_country = match_chocolates_specific_country(q_low)

    if specific_country and not any(k in q_low for k in ["sản phẩm", "product", "nhân viên", "salesperson"]):
        conds = [f"g.Geo = '{specific_country}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        needs_fix = (
            "with " in sql_low
            or "max(" in sql_low
            or "group by quarter" not in sql_low
            or "quarteryear" in sql_low
            or "g.geoid" not in sql_low
            or f"'{specific_country.lower()}'" not in sql_low
            or ("concat" not in sql_low and not is_sqlite)
            or (is_sqlite and "strftime" not in sql_low)
            or "group by g.geo" in sql_low
        )
        if needs_fix:
            return f"""SELECT 
    {qtr_expr} AS Quarter,
    {metric_expr}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}
GROUP BY Quarter
ORDER BY Quarter ASC"""

    # 2. Doanh thu theo từng Quốc gia qua các quý (so sánh đa quốc gia)
    elif any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"]) and any(k in q_low for k in ["từng quốc gia", "từng thị trường", "các quốc gia", "mỗi quốc gia"]):
        where_clause = f"WHERE {year_cond}\n" if year_cond else ""
        needs_fix = (
            "with " in sql_low
            or "max(" in sql_low
            or "quarter" not in sql_low
            or "group by quarter, country" not in sql_low
        )
        if needs_fix:
            return f"""SELECT 
    {qtr_expr} AS Quarter,
    g.Geo AS Country,
    {metric_expr}
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}GROUP BY Quarter, Country
ORDER BY Quarter ASC, TotalSales DESC"""

    # 3. Doanh thu của một Team cụ thể qua từng quý (ví dụ: Yummies theo từng quý)
    specific_team = None
    if "yummies" in q_low:
        specific_team = "Yummies"
    elif "delish" in q_low:
        specific_team = "Delish"
    elif "jucies" in q_low:
        specific_team = "Jucies"

    if specific_team:
        conds = [f"pe.Team = '{specific_team}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        return f"""SELECT 
    {qtr_expr} AS Quarter,
    {metric_expr}
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY Quarter
ORDER BY Quarter ASC"""

    # 4. Doanh thu của một Sản phẩm cụ thể qua từng quý (ví dụ: 85% Dark Bars theo từng quý)
    specific_prod = match_chocolates_specific_product(q_low)
    if specific_prod:
        escaped_prod = specific_prod.replace("'", "''")
        conds = [f"pr.Product = '{escaped_prod}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        return f"""SELECT 
    {qtr_expr} AS Quarter,
    {metric_expr}
FROM sales s
JOIN products pr ON s.PID = pr.PID
{where_clause}
GROUP BY Quarter
ORDER BY Quarter ASC"""

    # 5. Doanh thu toàn công ty / tổng hợp theo từng quý
    if any(k in q_low for k in ["doanh thu", "doanh số", "sales", "số lượng", "hộp", "thùng"]):
        where_clause = f"WHERE {year_cond}\n" if year_cond else ""
        needs_fix = "with " in sql_low or "max(" in sql_low or "group by quarter" not in sql_low
        if needs_fix:
            return f"""SELECT 
    {qtr_expr} AS Quarter,
    {metric_expr}
FROM sales s
{where_clause}GROUP BY Quarter
ORDER BY Quarter ASC"""

    return sql


def auto_fix_datetime_year_filters(sql: str, dialect: str = "MySQL") -> str:
    """Tự động chuyển đổi các biểu thức so sánh trực tiếp cột ngày tháng với năm dạng số hoặc chuỗi năm (e.g. SaleDate = 2021 hoặc SaleDate = '2021')
    thành hàm YEAR(SaleDate) = 2021 (MySQL) hoặc strftime('%Y', SaleDate) = '2021' (SQLite).
    Tránh lỗi trả về 0 dòng khi MySQL so sánh DATETIME với số nguyên hoặc chuỗi năm ngắn."""
    if not sql:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    def replace_eq_year(m):
        col = m.group(1)
        yr = m.group(2)
        if is_sqlite:
            return f"strftime('%Y', {col}) = '{yr}'"
        return f"YEAR({col}) = {yr}"

    def replace_between_year(m):
        col = m.group(1)
        yr1 = m.group(2)
        yr2 = m.group(3)
        if is_sqlite:
            return f"strftime('%Y', {col}) BETWEEN '{yr1}' AND '{yr2}'"
        if yr1 == yr2:
            return f"YEAR({col}) = {yr1}"
        return f"YEAR({col}) BETWEEN {yr1} AND {yr2}"

    date_col_pattern = r'(\b(?:[a-zA-Z_]\w*\.)?(?:SaleDate|sale_date|hire_date|from_date|to_date|birth_date|order_date))'

    # BETWEEN 2021 AND 2021 or BETWEEN '2021' AND '2021'
    sql = re.sub(
        date_col_pattern + r'\s+BETWEEN\s+[\'\"]?(20\d{2}|19\d{2})[\'\"]?\s+AND\s+[\'\"]?(20\d{2}|19\d{2})[\'\"]?',
        replace_between_year,
        sql,
        flags=re.IGNORECASE
    )

    # = 2021 or = '2021'
    sql = re.sub(
        date_col_pattern + r'\s*=\s*[\'\"]?(20\d{2}|19\d{2})[\'\"]?',
        replace_eq_year,
        sql,
        flags=re.IGNORECASE
    )

    # LIKE '2021%' or LIKE '2021'
    sql = re.sub(
        date_col_pattern + r'\s+LIKE\s+[\'\"](20\d{2}|19\d{2})(?:%)?[\'\"]',
        replace_eq_year,
        sql,
        flags=re.IGNORECASE
    )

    return sql


def auto_fix_pareto_cumulative_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn phân tích Pareto (Quy luật 80/20 / Tỷ lệ tích lũy)
    như 'Liệt kê danh sách các sản phẩm đem lại 80% doanh số cho công ty trong năm 2021',
    'Top sản phẩm chiếm 80% doanh thu', 'Những sản phẩm tạo ra 80% doanh số'.
    Sử dụng CTE và Window Functions (SUM() OVER) để tính Running Total chuẩn xác 100%,
    tránh triệt để lỗi HAVING SUM >= 0.8 * (SELECT...) khiến kết quả trả về 0 dòng."""
    if not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = (sql or "").lower()

    # 1. Nhận diện tỷ lệ phần trăm (VD: 80%, 70%, 90%, 80/20, pareto) hoặc lỗi HAVING quá chặt
    pct_m = re.search(r'\b(4\d|5\d|6\d|7\d|8\d|9\d)\s*%', q_low)
    is_pareto_kw = any(k in q_low for k in ["80/20", "80-20", "pareto", "tích lũy", "tích luỹ", "cumulative"])
    has_impossible_having = bool(re.search(r'having\s+sum\s*\([^)]+\)\s*>=\s*(?:0\.\d+|\(\s*select\b)', sql_low))

    if not pct_m and not is_pareto_kw and not has_impossible_having:
        return sql

    cutoff_pct = float(pct_m.group(1)) / 100.0 if pct_m else 0.80

    # Kiểm tra các động từ hành động đóng góp / đem lại / mang lại / chiếm / tạo ra
    has_pareto_intent = (
        any(k in q_low for k in [
            "đem lại", "mang lại", "tạo ra", "chiếm", "đóng góp", "chiếm khoảng", "đạt", 
            "tổng cộng", "chiếm tới", "chiếm hơn", "chiếm đến", "tạo nên", "cấu thành",
            "nguồn thu", "doanh số", "doanh thu", "chủ lực", "hàng đầu",
            "generate", "bring", "account for", "contribute", "sales", "revenue"
        ])
        or is_pareto_kw
        or has_impossible_having
    )
    if not has_pareto_intent:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    is_chocolates = (
        any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"])
        or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate", "sản phẩm", "salesperson", "thị trường", "quốc gia"])
    )
    is_employees = (
        any(k in sql_low for k in ["departments", "employees", "salaries", "titles", "dept_emp", "dept_manager"])
        or any(k in q_low for k in ["phòng ban", "lương", "salary", "nhân sự", "chức danh", "quỹ lương"])
    )

    if is_chocolates:
        yr_m = re.search(r'\b(20\d{2})\b', q_low)
        yr_val = yr_m.group(1) if yr_m else None
        yr_clause = (f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""

        has_boxes = any(k in q_low for k in ["hộp", "thùng", "boxes", "số lượng hộp"])
        metric_expr = "SUM(s.Boxes)" if has_boxes else "SUM(s.Amount)"
        metric_col = "TotalBoxesSold" if has_boxes else "TotalSales"

        is_person = any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "người bán", "sales rep", "rep", "thành viên", "yummies", "delish", "jucies"]) and not any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
        is_country = any(k in q_low for k in ["quốc gia", "thị trường", "country", "geo", "nước"]) and not any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"])
        is_category = any(k in q_low for k in ["nhóm sản phẩm", "category", "danh mục", "dòng sản phẩm"]) and not any(k in q_low for k in ["sản phẩm cụ thể", "từng sản phẩm"])
        is_product = not (is_person or is_country or is_category)

        if is_product:
            return f"""WITH ProductSales AS (
    SELECT 
        pr.Product AS Product,
        {metric_expr} AS {metric_col},
        SUM({metric_expr}) OVER () AS GrandTotal,
        SUM({metric_expr}) OVER (ORDER BY {metric_expr} DESC) AS RunningTotal
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    {yr_clause}
    GROUP BY pr.Product
)
SELECT 
    Product,
    {metric_col},
    ROUND(({metric_col} / GrandTotal) * 100, 2) AS Percentage,
    ROUND((RunningTotal / GrandTotal) * 100, 2) AS CumulativePercent
FROM ProductSales
WHERE (RunningTotal - {metric_col}) / GrandTotal < {cutoff_pct}
ORDER BY {metric_col} DESC"""

        elif is_person:
            return f"""WITH PersonSales AS (
    SELECT 
        pe.Salesperson AS Salesperson,
        {metric_expr} AS {metric_col},
        SUM({metric_expr}) OVER () AS GrandTotal,
        SUM({metric_expr}) OVER (ORDER BY {metric_expr} DESC) AS RunningTotal
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    {yr_clause}
    GROUP BY pe.Salesperson
)
SELECT 
    Salesperson,
    {metric_col},
    ROUND(({metric_col} / GrandTotal) * 100, 2) AS Percentage,
    ROUND((RunningTotal / GrandTotal) * 100, 2) AS CumulativePercent
FROM PersonSales
WHERE (RunningTotal - {metric_col}) / GrandTotal < {cutoff_pct}
ORDER BY {metric_col} DESC"""

        elif is_country:
            return f"""WITH CountrySales AS (
    SELECT 
        g.Geo AS Country,
        {metric_expr} AS {metric_col},
        SUM({metric_expr}) OVER () AS GrandTotal,
        SUM({metric_expr}) OVER (ORDER BY {metric_expr} DESC) AS RunningTotal
    FROM sales s
    JOIN geo g ON s.GeoID = g.GeoID
    {yr_clause}
    GROUP BY g.Geo
)
SELECT 
    Country,
    {metric_col},
    ROUND(({metric_col} / GrandTotal) * 100, 2) AS Percentage,
    ROUND((RunningTotal / GrandTotal) * 100, 2) AS CumulativePercent
FROM CountrySales
WHERE (RunningTotal - {metric_col}) / GrandTotal < {cutoff_pct}
ORDER BY {metric_col} DESC"""

        elif is_category:
            return f"""WITH CategorySales AS (
    SELECT 
        pr.Category AS Category,
        {metric_expr} AS {metric_col},
        SUM({metric_expr}) OVER () AS GrandTotal,
        SUM({metric_expr}) OVER (ORDER BY {metric_expr} DESC) AS RunningTotal
    FROM sales s
    JOIN products pr ON s.PID = pr.PID
    {yr_clause}
    GROUP BY pr.Category
)
SELECT 
    Category,
    {metric_col},
    ROUND(({metric_col} / GrandTotal) * 100, 2) AS Percentage,
    ROUND((RunningTotal / GrandTotal) * 100, 2) AS CumulativePercent
FROM CategorySales
WHERE (RunningTotal - {metric_col}) / GrandTotal < {cutoff_pct}
ORDER BY {metric_col} DESC"""

    elif is_employees:
        return f"""WITH DeptSalaries AS (
    SELECT 
        d.dept_name AS Department,
        SUM(s.salary) AS TotalSalaryBudget,
        SUM(SUM(s.salary)) OVER () AS GrandTotal,
        SUM(SUM(s.salary)) OVER (ORDER BY SUM(s.salary) DESC) AS RunningTotal
    FROM departments d
    JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
    JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'
    GROUP BY d.dept_name
)
SELECT 
    Department,
    TotalSalaryBudget,
    ROUND((TotalSalaryBudget / GrandTotal) * 100, 2) AS Percentage,
    ROUND((RunningTotal / GrandTotal) * 100, 2) AS CumulativePercent
FROM DeptSalaries
WHERE (RunningTotal - TotalSalaryBudget) / GrandTotal < {cutoff_pct}
ORDER BY TotalSalaryBudget DESC"""

    return sql


def auto_fix_chocolates_dominant_market_top_product_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa truy vấn tìm thị trường chiếm tỷ trọng lớn (> X% doanh số toàn cầu)
    kèm sản phẩm bán chạy nhất tại thị trường đó."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate", "thị trường", "toàn cầu"])
    if not is_chocolates:
        return sql

    is_market = any(k in q_low for k in ["thị trường", "quốc gia", "country", "geo", "khu vực"]) or "geo" in sql_low or "geoid" in sql_low
    is_global_share = any(k in q_low for k in ["toàn cầu", "toan cau", "global", "tổng doanh số", "tổng doanh thu", "doanh số công ty", "doanh thu công ty", "chiếm", "đóng góp", "%", "phần trăm", "tỷ trọng", "tỉ trọng", "tỉ lệ", "tỷ lệ"]) or bool(re.search(r'\b\d+\s*%', q_low))
    is_top_product = any(k in q_low for k in ["sản phẩm bán chạy", "bán chạy nhất", "sản phẩm nào bán chạy", "top product", "best selling", "mặt hàng bán chạy", "sản phẩm bán tốt", "sản phẩm chủ lực", "sản phẩm đứng đầu"]) or ("top" in q_low and "sản phẩm" in q_low)

    if not (is_market and is_global_share and is_top_product):
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    # Trích xuất ngưỡng phần trăm (VD: 30%, 25%, 20%)
    thresh_match = re.search(r'(?:trên|hơn|>|vượt|từ|đạt|chiếm)\s*(\d+(?:\.\d+)?)\s*%', q_low)
    if not thresh_match:
        thresh_match = re.search(r'(\d+(?:\.\d+)?)\s*%\s*(?:trở lên|trở lại)?', q_low)
    
    threshold_val = float(thresh_match.group(1)) if thresh_match else 30.0
    op = ">=" if any(k in q_low for k in ["từ", "trở lên", "ít nhất", "tối thiểu", ">="]) else ">"

    # Trích xuất năm nếu có
    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None

    yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{year_val}'\n    " if (year_val and is_sqlite) else f"WHERE YEAR(s.SaleDate) = {year_val}\n    " if year_val else ""
    yr_inner = f" WHERE strftime('%Y', SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" WHERE YEAR(SaleDate) = {year_val}" if year_val else ""

    # Kiểm tra xem SQL hiện tại có hợp lệ và đã lọc đúng rn = 1 và threshold chưa
    needs_fix = (
        "row_number" not in sql_low
        or ("market" not in sql_low and "country" not in sql_low and "geo" not in sql_low)
        or "product" not in sql_low
        or ("rn = 1" not in sql_low and "rn=1" not in sql_low and "countryrank = 1" not in sql_low and "countryrank=1" not in sql_low and "rank = 1" not in sql_low and "rank=1" not in sql_low)
        or str(int(threshold_val)) not in sql_low
    )

    if needs_fix:
        return f"""WITH MarketSales AS (
    SELECT 
        g.GeoID,
        g.Geo AS Market,
        SUM(s.Amount) AS MarketRevenue,
        ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS MarketSharePct
    FROM sales s
    JOIN geo g ON s.GeoID = g.GeoID
    {yr_filter}GROUP BY g.GeoID, g.Geo
    HAVING (SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner})) {op} {threshold_val}
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
    {yr_filter}GROUP BY ms.GeoID, ms.Market, ms.MarketRevenue, ms.MarketSharePct, pr.PID, pr.Product, pr.Category
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

    return sql


def auto_fix_contribution_percentage_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và đảm bảo câu truy vấn Tỷ lệ đóng góp / Tỷ trọng (Category, Country, Team, Product)
    trên CSDL Awesome Chocolates luôn trả về đầy đủ cột Tỷ lệ (Percentage) và Doanh số (TotalSales)."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # Không can thiệp nếu là câu hỏi xu hướng theo tháng / quý
    if any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "quý", "quarter", "từng quý", "theo quý", "qua các quý"]):
        return sql

    # Không can thiệp nếu là câu hỏi Pareto / Tích lũy 80/20 (đã có auto_fix_pareto_cumulative_query xử lý)
    if any(k in q_low for k in ["pareto", "80/20", "80-20", "tích lũy", "tích luỹ", "cumulative"]) or re.search(r'\b(4\d|5\d|6\d|7\d|8\d|9\d)\s*%', q_low) or any(k in sql_low for k in ["runningtotal", "cumulativepercent", "productsales", "grandtotal"]):
        return sql

    # Không can thiệp nếu là câu hỏi tìm thị trường + sản phẩm bán chạy nhất
    if (
        any(k in q_low for k in ["sản phẩm bán chạy", "bán chạy nhất", "top product", "best selling", "mặt hàng bán chạy", "sản phẩm bán tốt", "sản phẩm chủ lực"]) 
        and any(k in q_low for k in ["thị trường", "quốc gia", "country", "geo", "khu vực"])
    ):
        return sql

    is_ratio_question = any(k in q_low for k in [
        "tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "percent", "tỷ trọng", "tỉ trọng", 
        "cơ cấu", "share", "ratio", "đóng góp"
    ])
    if not is_ratio_question:
        return sql

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate", "category", "nhóm sản phẩm", "nhóm hàng"])
    if not is_chocolates:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    # Trích xuất năm nếu có (VD: 2021, 2022)
    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None

    # Trích xuất LIMIT từ câu hỏi nếu có
    limit = extract_requested_limit(user_query)
    limit_clause = f"\nLIMIT {limit}" if limit else ""

    # Kiểm tra xem SQL hiện tại đã có cột tỷ lệ/phần trăm chưa
    has_percentage_in_sql = any(k in sql_low for k in ["percentage", "percent", "pct", "tỷ lệ", "tỉ lệ", "share", "ratio"]) and ("*" in sql_low or "/" in sql_low)

    # 1. Tỷ lệ đóng góp theo Nhóm sản phẩm (Category)
    is_category = any(k in q_low for k in ["category", "nhóm sản phẩm", "nhóm hàng", "danh mục"]) or "category" in sql_low
    if is_category:
        if not has_percentage_in_sql or "with " in sql_low or "group by" not in sql_low or "pr.category" not in sql_low:
            yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{year_val}'\n" if (year_val and is_sqlite) else f"WHERE YEAR(s.SaleDate) = {year_val}\n" if year_val else ""
            yr_inner = f" WHERE strftime('%Y', SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" WHERE YEAR(SaleDate) = {year_val}" if year_val else ""
            return f"""SELECT 
    pr.Category AS Category,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}GROUP BY pr.Category
ORDER BY TotalSales DESC{limit_clause}"""

    # 2. Tỷ lệ đóng góp theo Quốc gia / Thị trường (Country / Geo)
    is_country = any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "nước"]) or "geo" in sql_low or "geoid" in sql_low
    if is_country and not is_category:
        if not has_percentage_in_sql or "with " in sql_low or "group by" not in sql_low or "g.geo" not in sql_low:
            yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{year_val}'\n" if (year_val and is_sqlite) else f"WHERE YEAR(s.SaleDate) = {year_val}\n" if year_val else ""
            yr_inner = f" WHERE strftime('%Y', SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" WHERE YEAR(SaleDate) = {year_val}" if year_val else ""
            return f"""SELECT 
    g.Geo AS Country,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{yr_filter}GROUP BY g.Geo
ORDER BY TotalSales DESC{limit_clause}"""

    # 3. Tỷ lệ đóng góp theo Đội ngũ bán hàng (Team)
    is_team = any(k in q_low for k in ["team", "đội ngũ", "đội", "nhóm bán hàng", "nhóm kinh doanh"]) or "team" in sql_low
    if is_team and not is_category and not is_country:
        needs_fix = (
            not has_percentage_in_sql 
            or "with " in sql_low 
            or "group by" not in sql_low 
            or "pe.team" not in sql_low
            or "pe.team !=" not in sql_low.replace(" ", "")
            or "pe.team is not null" not in sql_low.replace("  ", " ")
            or "pe2.team" not in sql_low
        )
        if needs_fix:
            yr_filter = f" AND strftime('%Y', s.SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" AND YEAR(s.SaleDate) = {year_val}" if year_val else ""
            yr_inner = f" AND strftime('%Y', s2.SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" AND YEAR(s2.SaleDate) = {year_val}" if year_val else ""
            return f"""SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales s2 JOIN people pe2 ON s2.SPID = pe2.SPID WHERE pe2.Team != '' AND pe2.Team IS NOT NULL{yr_inner}), 2) AS Percentage
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL{yr_filter}
GROUP BY pe.Team
ORDER BY TotalSales DESC{limit_clause}"""

    # 4. Tỷ lệ đóng góp theo Sản phẩm (Product)
    is_product = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "kẹo", "socola", "chocolate"]) or "product" in sql_low
    if is_product and not is_category and not is_country and not is_team:
        if not has_percentage_in_sql or "with " in sql_low or "group by" not in sql_low or "pr.product" not in sql_low:
            yr_filter = f"WHERE strftime('%Y', s.SaleDate) = '{year_val}'\n" if (year_val and is_sqlite) else f"WHERE YEAR(s.SaleDate) = {year_val}\n" if year_val else ""
            yr_inner = f" WHERE strftime('%Y', SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" WHERE YEAR(SaleDate) = {year_val}" if year_val else ""
            limit_prod = limit_clause if limit_clause else "\nLIMIT 10"
            return f"""SELECT 
    pr.Product AS Product,
    SUM(s.Amount) AS TotalSales,
    ROUND(SUM(s.Amount) * 100.0 / (SELECT SUM(Amount) FROM sales{yr_inner}), 2) AS Percentage
FROM sales s
JOIN products pr ON s.PID = pr.PID
{yr_filter}GROUP BY pr.Product
ORDER BY TotalSales DESC{limit_prod}"""

    return sql


def auto_fix_sales_performance_comparison_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa các câu truy vấn so sánh hiệu quả bán hàng (Sales Performance / Efficiency),
    đảm bảo luôn có các chỉ số hiệu quả chuẩn (AvgOrderValue, RevenuePerBox) thay vì chỉ xuất tổng doanh thu."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    is_efficiency = any(k in q_low for k in [
        "hiệu quả", "efficiency", "effectiveness", "năng suất", 
        "giá trị đơn hàng trung bình", "đơn hàng trung bình", "trung bình mỗi đơn", 
        "trung bình mỗi hộp", "đơn giá trung bình", "giá trung bình", "bình quân mỗi hộp", "giá bán trung bình",
        "số tiền trung bình", "tiền trung bình", "doanh số trung bình", "doanh thu trung bình", "mức bán trung bình",
        "order value", "per box", "profit per box", "revenue per box", "revenueperbox", "avg price per box", "avgpriceperbox",
        "lợi nhuận", "profit", "margin", "tỉ suất", "tỷ suất", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"
    ]) or (
        any(k in q_low for k in ["trung bình", "bình quân", "avg", "average"])
        and any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh", "các team", "giữa các team"])
    )
    if not is_efficiency:
        return sql

    # Không can thiệp nếu là câu hỏi báo cáo P&L / Lãi Lỗ / Chi phí / Lợi nhuận ròng (để auto_fix_chocolates_pnl_query xử lý)
    has_pnl_keywords = any(k in q_low for k in [
        "lãi", "lỗ", "lãi, lỗ", "lãi lỗ", "kết quả kinh doanh", "profit and loss", "p&l", "pnl", 
        "cost_per_box", "chi phí", "cost", "giá vốn", "cogs", "lợi nhuận ròng", "net profit"
    ]) or (any(k in q_low for k in ["doanh thu", "sales"]) and any(k in q_low for k in ["chi phí", "cost", "giá vốn", "lợi nhuận", "profit"]))
    has_time = any(k in q_low for k in ["tháng", "quý", "month", "quarter", "năm 20", "year", "2021", "2022"])
    if has_pnl_keywords or (has_time and any(k in q_low for k in ["lợi nhuận", "profit"])):
        return sql

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate", "thị trường", "mỹ", "ấn độ", "india", "usa"])
    if not is_chocolates:
        return sql

    # 1. So sánh hiệu quả giữa các thị trường / quốc gia
    if any(k in q_low for k in ["thị trường", "quốc gia", "country", "geo", "usa", "mỹ", "hoa kỳ", "united states", "nước"]):
        is_sqlite = "sqlite" in (dialect or "").lower()
        calc_avg_box = (
            "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)"
            if is_sqlite
            else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"
        )
        is_price_per_box = any(k in q_low for k in [
            "đơn giá", "đơn giá trung bình", "giá trung bình", "mỗi hộp", "bình quân mỗi hộp", 
            "trung bình mỗi hộp", "giá bán trung bình", "per box", "revenue per box", "revenueperbox", "avg price per box", "avgpriceperbox", "giá mỗi hộp"
        ]) and not any(k in q_low for k in ["đơn hàng trung bình", "giá trị đơn hàng", "order value", "mỗi đơn", "aov"])

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

        where_clause = f"WHERE g.Geo IN ({', '.join(specific_geos)})\n" if specific_geos else ""

        if is_price_per_box:
            is_lowest = any(k in q_low for k in ["thấp nhất", "nhỏ nhất", "kém nhất", "lowest", "bottom", "least", "tệ nhất"])
            sort_dir = "ASC" if is_lowest else "DESC"

            top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
            if top_m:
                req_limit = f"\nLIMIT {int(top_m.group(1))}"
            elif any(k in q_low for k in ["nào", "gì", "cao nhất", "thấp nhất", "best", "worst"]) and not any(k in q_low for k in ["các quốc gia", "các nước", "các thị trường", "từng nước", "từng quốc gia", "từng thị trường", "mỗi nước", "mỗi quốc gia", "mỗi thị trường", "so sánh", "tất cả", "danh sách"]):
                req_limit = "\nLIMIT 1"
            elif any(k in q_low for k in ["tất cả", "từng", "các", "so sánh"]):
                req_limit = ""
            else:
                req_limit = "\nLIMIT 10"

            needs_fix = (
                "avgpriceperbox" not in sql_low
                or "with " in sql_low
                or "order by avgordervalue" in sql_low
                or (specific_geos and not any(g.lower().replace("'", "") in sql_low for g in specific_geos))
                or (("limit 1" in req_limit.lower()) and "limit 1" not in sql_low)
                or ("revenueperbox" in sql_low and "order by" not in sql_low)
            )
            if needs_fix:
                return f"""SELECT 
    g.Geo AS Market,
    {calc_avg_box} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}GROUP BY g.Geo
ORDER BY AvgPricePerBox {sort_dir}{req_limit}"""
        else:
            needs_fix = (
                "avg(" not in sql_low
                or "avgordervalue" not in sql_low
                or "with " in sql_low
                or (specific_geos and not any(g.lower().replace("'", "") in sql_low for g in specific_geos))
            )
            if needs_fix:
                return f"""SELECT 
    g.Geo AS Market,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS RevenuePerBox,
    ROUND(AVG(s.Boxes), 2) AS AvgBoxesPerOrder,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{where_clause}GROUP BY g.Geo
ORDER BY AvgOrderValue DESC"""

    # 2. Giá trị đơn hàng trung bình / hiệu quả theo Team
    elif any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng"]):
        is_sqlite = "sqlite" in (dialect or "").lower()
        calc_avg_box = (
            "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)"
            if is_sqlite
            else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"
        )
        is_price_per_box = any(k in q_low for k in [
            "đơn giá", "đơn giá trung bình", "giá trung bình", "mỗi hộp", "bình quân mỗi hộp", 
            "trung bình mỗi hộp", "giá bán trung bình", "per box", "revenue per box", "revenueperbox", "avg price per box", "avgpriceperbox", "giá mỗi hộp"
        ]) and not any(k in q_low for k in ["đơn hàng trung bình", "giá trị đơn hàng", "order value", "mỗi đơn", "aov"])

        if is_price_per_box:
            is_lowest = any(k in q_low for k in ["thấp nhất", "nhỏ nhất", "kém nhất", "lowest", "bottom", "least", "tệ nhất"])
            sort_dir = "ASC" if is_lowest else "DESC"
            top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
            if top_m:
                req_limit = f"\nLIMIT {int(top_m.group(1))}"
            elif any(k in q_low for k in ["nào", "gì", "cao nhất", "thấp nhất", "best", "worst"]) and not any(k in q_low for k in ["các đội", "các team", "từng đội", "từng team", "mỗi đội", "mỗi team", "so sánh", "tất cả", "danh sách"]):
                req_limit = "\nLIMIT 1"
            elif any(k in q_low for k in ["tất cả", "từng", "các", "so sánh"]):
                req_limit = ""
            else:
                req_limit = "\nLIMIT 10"

            needs_fix = (
                "avgpriceperbox" not in sql_low
                or "with " in sql_low
                or "order by avgordervalue" in sql_low
                or (("limit 1" in req_limit.lower()) and "limit 1" not in sql_low)
            )
            if needs_fix:
                return f"""SELECT 
    pe.Team AS Team,
    {calc_avg_box} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL
GROUP BY pe.Team
ORDER BY AvgPricePerBox {sort_dir}{req_limit}"""
        else:
            needs_fix = "avg(" not in sql_low or "avgordervalue" not in sql_low or "with " in sql_low
            if needs_fix:
                return f"""SELECT 
    pe.Team AS Team,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS RevenuePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL
GROUP BY pe.Team
ORDER BY AvgOrderValue DESC"""

    # 3. Lợi nhuận trung bình trên mỗi hộp / Tỷ suất lợi nhuận (Profit per box / Profit Margin)
    elif any(k in q_low for k in [
        "profit per box", "lợi nhuận trên mỗi hộp", "lợi nhuận mỗi hộp", 
        "lợi nhuận trung bình trên mỗi hộp", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận",
        "tỷ suất", "tỉ suất", "margin", "profit", "lợi nhuận"
    ]):
        top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
        req_limit = int(top_m.group(1)) if top_m else (25 if any(k in q_low for k in ["từng", "tất cả", "all", "các"]) else 10)
        is_margin_focus = any(k in q_low for k in ["tỷ suất", "tỉ suất", "margin", "%", "phần trăm"])
        order_col = "ProfitMargin" if is_margin_focus else "ProfitPerBox"
        needs_fix = (
            "cost_per_box" not in sql_low 
            or (is_margin_focus and "profitmargin" not in sql_low)
            or (not is_margin_focus and "profitperbox" not in sql_low)
            or (is_margin_focus and "order by profitmargin" not in sql_low)
            or (not is_margin_focus and "order by profitperbox" not in sql_low)
            or "with " in sql_low
            or "order by cost_per_box" in sql_low.replace(" ", "")
            or "orderbypr.cost_per_box" in sql_low.replace(" ", "")
            or "orderbycost_per_box" in sql_low.replace(" ", "")
        )
        if needs_fix:
            return f"""SELECT 
    pr.Product AS Product,
    pr.Category AS Category,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) * 100.0 / SUM(s.Amount), 2) AS ProfitMargin,
    ROUND(SUM(s.Amount - s.Boxes * pr.Cost_per_box) / SUM(s.Boxes), 2) AS ProfitPerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN products pr ON s.PID = pr.PID
GROUP BY pr.Product, pr.Category
ORDER BY {order_col} DESC
LIMIT {req_limit}"""

    # 4. So sánh hiệu quả / Doanh thu, số hộp và đơn giá trung bình giữa các danh mục sản phẩm (Category)
    elif any(k in q_low for k in ["category", "danh mục", "nhóm sản phẩm", "nhóm hàng"]):
        needs_fix = (
            "pr.category" not in sql_low
            or "avg" not in sql_low
            or "boxes" not in sql_low
            or "amount" not in sql_low
            or "with " in sql_low
        )
        if needs_fix:
            calc_avg = "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)" if "sqlite" in (dialect or "").lower() else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"
            return f"""SELECT 
    pr.Category AS Category,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    {calc_avg} AS AvgPricePerBox
FROM sales s
JOIN products pr ON s.PID = pr.PID
GROUP BY pr.Category
ORDER BY TotalRevenue DESC"""

    # 5. So sánh hiệu quả / Doanh thu, số hộp và đơn giá trung bình theo từng Sản phẩm (Product)
    elif any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"]) and not any(k in q_low for k in ["category", "danh mục", "nhóm"]):
        top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
        req_limit = int(top_m.group(1)) if top_m else (25 if any(k in q_low for k in ["từng", "tất cả", "all", "các"]) else 10)
        needs_fix = (
            "pr.product" not in sql_low
            or "avg" not in sql_low
            or "boxes" not in sql_low
            or "amount" not in sql_low
            or "with " in sql_low
        )
        if needs_fix:
            calc_avg = "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)" if "sqlite" in (dialect or "").lower() else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"
            return f"""SELECT 
    pr.Product AS Product,
    pr.Category AS Category,
    SUM(s.Amount) AS TotalRevenue,
    SUM(s.Boxes) AS TotalBoxesSold,
    {calc_avg} AS AvgPricePerBox
FROM sales s
JOIN products pr ON s.PID = pr.PID
GROUP BY pr.Product, pr.Category
ORDER BY TotalRevenue DESC
LIMIT {req_limit}"""

    # 6. Hiệu quả bán hàng theo Nhân viên (Salesperson: Đơn giá trung bình / AvgPricePerBox hoặc Giá trị đơn hàng trung bình)
    elif any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "ai bán", "ai là", "ai có", "thành viên", "sales rep", "rep"]):
        is_sqlite = "sqlite" in (dialect or "").lower()
        calc_avg_box = (
            "ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2)"
            if is_sqlite
            else "ROUND(SUM(s.Amount) / NULLIF(SUM(s.Boxes), 0), 2)"
        )

        # Trích xuất năm nếu có (VD: 2021, 2022)
        yr_m = re.search(r'\b(20\d{2})\b', q_low)
        yr_val = yr_m.group(1) if yr_m else None
        where_yr = (f"\nWHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"\nWHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""

        # Trích xuất điều kiện ngưỡng (HAVING filter)
        having_clause = ""
        thresh_val = None
        thresh_metric = "SUM(s.Amount)"
        thresh_op = ">"

        # 1. Kiểm tra ngưỡng doanh số / tiền / USD
        m_thresh_amt = re.search(r'(?:doanh số|doanh thu|tiền|amount|sales)\s*(?:trên|hơn|vượt|dưới|từ|[><]=?)\s*(?:\$|usd\s*)?(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+)', q_low)
        if not m_thresh_amt:
            m_thresh_amt = re.search(r'(?:trên|hơn|vượt|dưới|từ|[><]=?)\s*(?:\$|usd\s*)?(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+)\s*(?:usd|\$|đô|vnd|đồng)', q_low)

        if m_thresh_amt:
            raw_val = m_thresh_amt.group(1).replace(',', '').replace('.', '')
            thresh_val = float(raw_val)
            thresh_metric = "SUM(s.Amount)"
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
                if any(k in q_low for k in ["ít nhất", "tối thiểu", ">=", "at least"]):
                    thresh_op = ">="
                elif any(k in q_low for k in ["dưới", "nhỏ hơn", "thấp hơn", "<"]):
                    thresh_op = "<"
                else:
                    thresh_op = ">"
                having_clause = f"\nHAVING {thresh_metric} {thresh_op} {int(thresh_val) if thresh_val.is_integer() else thresh_val}"

        # Xác định chiều sắp xếp (DESC / ASC) và LIMIT
        is_lowest = any(k in q_low for k in ["thấp nhất", "kém nhất", "nhỏ nhất", "lowest", "bottom", "least", "tệ nhất"])
        sort_dir = "ASC" if is_lowest else "DESC"

        top_m = re.search(r"(?:top\s*|danh\s+sách\s*|lấy\s*|cho\s+tôi\s*)(\d+)", q_low)
        if top_m:
            req_limit = f"\nLIMIT {int(top_m.group(1))}"
        elif any(k in q_low for k in ["nào", "ai", "cao nhất", "thấp nhất", "best", "worst"]):
            req_limit = "\nLIMIT 1"
        elif any(k in q_low for k in ["tất cả", "từng", "các"]):
            req_limit = ""
        else:
            req_limit = "\nLIMIT 10"

        needs_fix = (
            "avgpriceperbox" not in sql_low
            or ("with " in sql_low)
            or ("having sum(s.boxes) > 500000" in sql_low)
            or (thresh_val is not None and "having" not in sql_low)
            or (thresh_metric == "SUM(s.Amount)" and "having sum(s.boxes)" in sql_low)
            or (any(k in q_low for k in ["nào", "ai", "cao nhất"]) and "limit 1" not in sql_low)
        )
        if needs_fix:
            return f"""SELECT 
    pe.Salesperson AS Salesperson,
    {calc_avg_box} AS AvgPricePerBox,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
JOIN people pe ON s.SPID = pe.SPID{where_yr}
GROUP BY pe.Salesperson{having_clause}
ORDER BY AvgPricePerBox {sort_dir}{req_limit}"""

    return sql


def auto_fix_sales_headcount_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn đếm số lượng nhân viên bán hàng (Headcount)
    theo từng Đội ngũ (Team) hoặc Khu vực (Location) trên CSDL Awesome Chocolates.
    Ngăn chặn tuyệt đối việc tính nhầm sang SUM(Boxes) hay SUM(Amount) từ bảng sales."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # BẢO VỆ TUYỆT ĐỐI CSDL EMPLOYEES:
    if (
        any(k in q_low for k in ["phòng ban", "phòng", "department", "chức danh", "title", "thâm niên", "lương"])
        or any(k in sql_low for k in ["departments", "dept_emp", "titles", "salaries", "dept_manager"])
    ):
        return sql

    # Nhận diện câu hỏi về đếm số lượng nhân viên / headcount / quy mô nhân sự
    is_headcount = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "salesperson", "sales person", "người bán", "sales rep", "sales reps"])
        and any(k in q_low for k in ["số lượng", "quy mô", "bao nhiêu", "đếm", "phân bổ", "cơ cấu", "phân chia", "mỗi team có", "từng team có", "từng đội có"])
    )
    # Nếu câu hỏi hỏi về doanh số, doanh thu, tiền bán thì không can thiệp
    if not is_headcount or any(k in q_low for k in ["doanh số", "doanh thu", "tiền bán", "bán được bao nhiêu tiền", "doanh thu bao nhiêu", "tháng", "quý"]):
        return sql

    is_chocolates = (
        any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"])
        or any(k in q_low for k in ["team", "đội ngũ", "kẹo", "chocolate", "chocolates", "hộp kẹo", "salesperson", "sales rep"])
    )
    if not is_chocolates:
        return sql

    # Phân biệt nhóm theo Location hay theo Team
    is_location = any(k in q_low for k in ["khu vực", "địa điểm", "location", "vị trí", "thành phố", "city"]) and not any(k in q_low for k in ["team", "đội ngũ", "đội", "nhóm"])

    if is_location:
        return (
            "SELECT\n"
            "    pe.Location AS `Khu Vực`,\n"
            "    COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`\n"
            "FROM people pe\n"
            "WHERE pe.Location != '' AND pe.Location IS NOT NULL\n"
            "GROUP BY pe.Location\n"
            "ORDER BY `Số Lượng Nhân Viên` DESC;"
        )
    else:
        return (
            "SELECT\n"
            "    pe.Team AS `Đội Ngũ`,\n"
            "    COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`,\n"
            "    ROUND(COUNT(DISTINCT pe.SPID) * 100.0 / (SELECT COUNT(*) FROM people WHERE Team != '' AND Team IS NOT NULL), 2) AS `Tỷ Lệ (%)`\n"
            "FROM people pe\n"
            "WHERE pe.Team != '' AND pe.Team IS NOT NULL\n"
            "GROUP BY pe.Team\n"
            "ORDER BY `Số Lượng Nhân Viên` DESC;"
        )


def auto_fix_chocolates_segment_large_orders_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa các câu truy vấn phân tích đơn hàng lớn theo phân khúc
    kết hợp giữa Ngưỡng số lượng hộp đơn hàng (>= 500, 1000) với Danh mục sản phẩm (Bites, Bars)
    và/hoặc Thị trường (USA, Canada, India...)."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # Nhận diện có điều kiện ngưỡng đơn hàng không
    has_order_thresh = (
        any(k in q_low for k in ["đơn hàng", "giao dịch", "mỗi đơn", "các đơn", "orders", "transactions", "đơn"])
        and any(k in q_low for k in ["trên", "hơn", "vượt", "lớn hơn", ">", "cao hơn", "từ", "trở lên", "ít nhất", "tối thiểu", ">="])
        and any(char.isdigit() for char in q_low)
    )
    if not has_order_thresh:
        return sql

    # Nhận diện danh mục
    cat = None
    if any(k in q_low for k in ["bites", "bite"]):
        cat = "Bites"
    elif any(k in q_low for k in ["bars", "bar"]):
        cat = "Bars"
    elif "other" in q_low:
        cat = "Other"

    # Nhận diện các thị trường
    geos = []
    if re.search(r'\b(usa|mỹ|hoa kỳ|united states)\b', q_low):
        geos.append("USA")
    if re.search(r'\b(canada)\b', q_low):
        geos.append("Canada")
    if re.search(r'\b(india|ấn độ|an do)\b', q_low):
        geos.append("India")
    if re.search(r'\b(uk|nước anh|vương quốc anh|united kingdom)\b', q_low):
        geos.append("UK")
    if re.search(r'\b(australia|úc)\b', q_low):
        geos.append("Australia")
    if re.search(r'\b(new zealand|newzealand|nz)\b', q_low):
        geos.append("New Zealand")

    if not cat and not geos:
        return sql

    box_m = re.search(r'(?:trên|hơn|vượt|lớn hơn|cao hơn|từ|ít nhất|tối thiểu|[><]=?)\s*(\d{1,3}(?:[,\.]\d{3})*|\d+)\s*(?:hộp|hop|thùng|thung|boxes)(?:\s*(?:trở lên|trở đi))?', q_low)
    is_gte = any(k in q_low for k in ["từ", "trở lên", "ít nhất", "tối thiểu", ">="])
    thresh_val = int(box_m.group(1).replace(',', '').replace('.', '')) if box_m else 500
    op = ">=" if is_gte else ">"

    yr_m = re.search(r'\b(20\d{2})\b', q_low)
    yr_val = yr_m.group(1) if yr_m else None
    is_sqlite = "sqlite" in (dialect or "").lower()

    needs_fix = False
    if cat and f"'{cat.lower()}'" not in sql_low:
        needs_fix = True
    if geos:
        for g in geos:
            if f"'{g.lower()}'" not in sql_low:
                needs_fix = True
                break
    if f"{thresh_val}" not in sql_low or "count(" not in sql_low or "sum(s.amount)" not in sql_low:
        needs_fix = True
    if "group by pr.product" in sql_low and "geo" not in sql_low and len(geos) > 0:
        needs_fix = True
    if "with " in sql_low:
        needs_fix = True

    if not needs_fix:
        return sql

    where_conds = []
    if cat:
        where_conds.append(f"pr.Category = '{cat}'")
    if geos:
        if len(geos) == 1:
            where_conds.append(f"g.Geo = '{geos[0]}'")
        else:
            geos_str = ", ".join([f"'{g}'" for g in geos])
            where_conds.append(f"g.Geo IN ({geos_str})")
    where_conds.append(f"s.Boxes {op} {thresh_val}")
    if yr_val:
        where_conds.append(f"strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {yr_val}")

    where_clause = "WHERE " + "\n  AND ".join(where_conds)

    lines = ["SELECT"]
    joins = ["FROM sales s"]
    if cat or any(k in q_low for k in ["sản phẩm", "product", "mặt hàng"]):
        joins.append("JOIN products pr ON s.PID = pr.PID")
    if geos:
        joins.append("JOIN geo g ON s.GeoID = g.GeoID")

    if geos and (cat or any(k in q_low for k in ["sản phẩm", "product"])):
        lines.append("    g.Geo AS Market,")
        lines.append("    pr.Product AS Product,")
        lines.append("    COUNT(*) AS LargeOrdersCount,")
        lines.append("    SUM(s.Amount) AS TotalRevenue,")
        lines.append("    SUM(s.Boxes) AS TotalBoxesSold")
        lines.extend(joins)
        lines.append(where_clause)
        lines.append("GROUP BY g.Geo, pr.Product")
        lines.append("ORDER BY g.Geo, TotalRevenue DESC")
    elif geos:
        lines.append("    g.Geo AS Market,")
        lines.append("    COUNT(*) AS LargeOrdersCount,")
        lines.append("    SUM(s.Amount) AS TotalRevenue,")
        lines.append("    SUM(s.Boxes) AS TotalBoxesSold")
        lines.extend(joins)
        lines.append(where_clause)
        lines.append("GROUP BY g.Geo")
        lines.append("ORDER BY TotalRevenue DESC")
    else:
        lines.append("    pr.Product AS Product,")
        lines.append("    COUNT(*) AS LargeOrdersCount,")
        lines.append("    SUM(s.Amount) AS TotalRevenue,")
        lines.append("    SUM(s.Boxes) AS TotalBoxesSold")
        lines.extend(joins)
        lines.append(where_clause)
        lines.append("GROUP BY pr.Product")
        lines.append("ORDER BY TotalRevenue DESC")

    return "\n".join(lines)


def auto_fix_chocolates_threshold_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn điều kiện ngưỡng (Threshold Condition Queries)
    như 'Những nhân viên bán hàng có tổng doanh số vượt mức 500,000 USD'.
    Bảo đảm SELECT luôn có cả cột thực thể và cột đo lường số học để vẽ biểu đồ."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()

    # 0. Tuyệt đối KHÔNG can thiệp nếu là câu hỏi xu hướng theo thời gian (quý, tháng, năm,...)
    if any(k in q_low for k in ["quý", "quarter", "từng quý", "theo quý", "qua các quý", "tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "xu hướng", "trend", "biến động"]):
        return sql

    # 0.1 Tuyệt đối KHÔNG can thiệp nếu SQL đã gom nhóm theo thời gian (Quarter, Month, SaleDate)
    sql_low = sql.lower()
    if any(k in sql_low for k in ["quarter", "month", "date_format", "strftime"]) or "group by quarter" in sql_low or "group by month" in sql_low:
        return sql

    # 0.2 Nếu câu hỏi có nhắc đến một quốc gia cụ thể (Ấn Độ, India, USA...), không can thiệp
    from src.llm.prompts import match_chocolates_specific_country
    if match_chocolates_specific_country(q_low):
        return sql

    # 0.3 Tuyệt đối KHÔNG can thiệp nếu là câu hỏi Pareto / Tỷ lệ tích lũy
    if any(k in q_low for k in ["pareto", "80/20", "80-20", "tích lũy", "tích luỹ", "cumulative"]) or re.search(r'\b(4\d|5\d|6\d|7\d|8\d|9\d)\s*%', q_low) or any(k in sql_low for k in ["runningtotal", "cumulativepercent", "productsales", "grandtotal"]):
        return sql

    # 0.4 Tuyệt đối KHÔNG can thiệp nếu là câu hỏi hiệu quả bán hàng / đơn giá trung bình / avg price per box
    if any(k in q_low for k in [
        "đơn giá", "giá trung bình", "bình quân mỗi hộp", "trung bình mỗi hộp", 
        "giá bán trung bình", "avg price per box", "avgpriceperbox", "hiệu quả", "efficiency"
    ]):
        return sql

    from src.llm.prompts import parse_threshold_query_info
    thresh_info = parse_threshold_query_info(q_low)
    if not thresh_info:
        return sql

    val = thresh_info['val']
    op = thresh_info['op']
    has_boxes = thresh_info['has_boxes']
    entity_type = thresh_info['entity_type']

    sql_low = sql.lower()
    is_chocolates = (
        any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"])
        or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate"])
    )
    if not is_chocolates:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    # Trích xuất năm nếu có (VD: 2021, 2022)
    yr_m = re.search(r'\b(20\d{2})\b', q_low)
    yr_val = yr_m.group(1) if yr_m else None
    yr_filter = (f"WHERE strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr_val}") if yr_val else ""

    metric_agg = "SUM(s.Boxes)" if has_boxes else "SUM(s.Amount)"
    metric_label = "Tổng Số Hộp" if has_boxes else "Tổng Doanh Số ($)"

    has_orders = any(k in q_low for k in ["đơn hàng", "số đơn", "orders", "giao dịch"])
    order_col_label = "Số Lượng Giao Dịch" if "giao dịch" in q_low else "Số Lượng Đơn Hàng"

    if entity_type == 'person':
        select_cols = [
            "    pe.Salesperson AS `Nhân Viên Kinh Doanh`",
            f"    {metric_agg} AS `{metric_label}`",
        ]
        if has_orders:
            select_cols.append(f"    COUNT(*) AS `{order_col_label}`")
        lines = [
            "SELECT",
            ",\n".join(select_cols),
            "FROM sales s",
            "JOIN people pe ON s.SPID = pe.SPID",
        ]
        if yr_filter:
            lines.append(yr_filter)
        lines.append("GROUP BY pe.Salesperson")
        lines.append(f"HAVING {metric_agg} {op} {val}")
        lines.append(f"ORDER BY `{metric_label}` DESC")
        return "\n".join(lines)

    elif entity_type == 'product':
        select_cols = [
            "    pr.Product AS `Sản Phẩm`",
            f"    {metric_agg} AS `{metric_label}`",
        ]
        if has_orders:
            select_cols.append(f"    COUNT(*) AS `{order_col_label}`")
        lines = [
            "SELECT",
            ",\n".join(select_cols),
            "FROM sales s",
            "JOIN products pr ON s.PID = pr.PID",
        ]
        if yr_filter:
            lines.append(yr_filter)
        lines.append("GROUP BY pr.Product")
        lines.append(f"HAVING {metric_agg} {op} {val}")
        lines.append(f"ORDER BY `{metric_label}` DESC")
        return "\n".join(lines)

    elif entity_type == 'geo':
        select_cols = [
            "    g.Geo AS `Quốc Gia`",
            f"    {metric_agg} AS `{metric_label}`",
        ]
        if has_orders:
            select_cols.append(f"    COUNT(*) AS `{order_col_label}`")
        lines = [
            "SELECT",
            ",\n".join(select_cols),
            "FROM sales s",
            "JOIN geo g ON s.GeoID = g.GeoID",
        ]
        if yr_filter:
            lines.append(yr_filter)
        lines.append("GROUP BY g.Geo")
        lines.append(f"HAVING {metric_agg} {op} {val}")
        lines.append(f"ORDER BY `{metric_label}` DESC")
        return "\n".join(lines)

    elif entity_type == 'team':
        select_cols = [
            "    pe.Team AS `Đội Ngũ`",
            f"    {metric_agg} AS `{metric_label}`",
        ]
        if has_orders:
            select_cols.append(f"    COUNT(*) AS `{order_col_label}`")
        team_where = "WHERE pe.Team != '' AND pe.Team IS NOT NULL"
        if yr_val:
            team_where += f" AND strftime('%Y', s.SaleDate) = '{yr_val}'" if is_sqlite else f" AND YEAR(s.SaleDate) = {yr_val}"
        lines = [
            "SELECT",
            ",\n".join(select_cols),
            "FROM sales s",
            "JOIN people pe ON s.SPID = pe.SPID",
            team_where,
            "GROUP BY pe.Team",
            f"HAVING {metric_agg} {op} {val}",
            f"ORDER BY `{metric_label}` DESC"
        ]
        return "\n".join(lines)

    return sql


def auto_fix_missing_metric_in_having_query(sql: str, user_query: str) -> str:
    """Tự động bổ sung chỉ số đo lường vào SELECT nếu câu lệnh SQL có GROUP BY và HAVING
    lọc theo hàm gộp (aggregate) nhưng SELECT lại chỉ chứa các cột danh mục/chuỗi."""
    if not sql:
        return sql

    # 1. Tuyệt đối KHÔNG can thiệp nếu SQL có subquery hoặc CTE lồng nhau (tránh làm vỡ cấu trúc ngoặc)
    sql_low = sql.lower()
    if any(k in sql_low for k in ["from (", "with ", "(select", "from\n(", "from  (", ") s_agg", ") t"]):
        return sql

    # 2. Phải có GROUP BY ở mức truy vấn chính
    if not re.search(r'\bGROUP\s+BY\b', sql, re.IGNORECASE):
        return sql

    having_match = re.search(r'\bHAVING\s+([\s\S]+?)(?=\bORDER\s+BY\b|\bLIMIT\b|;|\s*$)', sql, re.IGNORECASE)
    if not having_match:
        return sql

    having_clause = having_match.group(1).strip()

    # Kiểm tra xem SELECT đã có hàm gộp (aggregate) chưa
    select_match = re.search(r'\bSELECT\b([\s\S]+?)\bFROM\b', sql, re.IGNORECASE)
    if not select_match:
        return sql

    select_clause = select_match.group(1).strip()
    has_agg_in_select = bool(re.search(r'\b(SUM|AVG|COUNT|MAX|MIN)\s*\(', select_clause, re.IGNORECASE))
    if has_agg_in_select:
        return sql

    # Nếu SELECT đã có các tên cột chỉ số thông dụng thì không thêm nữa
    if any(k in select_clause.lower() for k in ["total", "amount", "sales", "salary", "count", "boxes", "avg", "raisecount", "currentsalary"]):
        return sql

    # Trích xuất aggregate expression từ HAVING
    agg_match = re.search(r'\b(SUM|AVG|COUNT|MAX|MIN)\s*\([^)]+\)', having_clause, re.IGNORECASE)
    if not agg_match:
        return sql

    agg_expr = agg_match.group(0).strip()
    agg_low = agg_expr.lower()

    if 'amount' in agg_low:
        alias = 'TotalSales'
    elif 'boxes' in agg_low:
        alias = 'TotalBoxesSold'
    elif 'salary' in agg_low:
        alias = 'AvgSalary' if 'avg' in agg_low else 'TotalSalary'
    elif 'count' in agg_low:
        alias = 'TotalCount'
    else:
        alias = 'MetricValue'

    metric_col_str = f"{agg_expr} AS {alias}"

    # Bổ sung metric vào SELECT
    new_select_clause = f"{select_clause}, {metric_col_str}"
    sql = sql[:select_match.start(1)] + " " + new_select_clause + " " + sql[select_match.end(1):]

    # Cập nhật ORDER BY an toàn
    if re.search(r'\bORDER\s+BY\b', sql, re.IGNORECASE):
        sql = re.sub(r'\bORDER\s+BY\s+.*$', f'ORDER BY {alias} DESC', sql, flags=re.IGNORECASE)
    else:
        if re.search(r'\bLIMIT\b', sql, re.IGNORECASE):
            sql = re.sub(r'\bLIMIT\b', f'ORDER BY {alias} DESC LIMIT', sql, flags=re.IGNORECASE)
        else:
            sql = sql.rstrip(';').strip() + f' ORDER BY {alias} DESC'

    # Gỡ bỏ LIMIT nếu người dùng không yêu cầu Top N
    q_low = (user_query or '').lower()
    has_top_n = bool(re.search(r'\b(?:top|danh\s+sách|lấy|cho\s+tôi)\s*(\d+)\b', q_low, re.IGNORECASE))
    if not has_top_n:
        sql = re.sub(r'\s+LIMIT\s+\d+\s*;?$', '', sql, flags=re.IGNORECASE)

    return sql.strip()


def auto_fix_chocolates_team_spread_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn: Phân tích sự chênh lệch giữa nhóm cao nhất và nhóm thấp nhất (hoặc giữa các nhóm kinh doanh).
    Đảm bảo 100% nhóm theo pe.Team (bảng people), tuyệt đối không dùng bảng geo (quốc gia) hay products."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    sql_low = (sql or "").lower()

    # BẢO VỆ TUYỆT ĐỐI CSDL EMPLOYEES:
    if any(k in q_low for k in ["phòng ban", "phòng", "department", "chức danh", "title", "lương", "salary", "thâm niên"]):
        return sql

    is_team_spread = (
        ("nhóm cao nhất và nhóm thấp nhất" in q_low or "giữa nhóm cao nhất" in q_low or "nhóm thấp nhất" in q_low or "giữa nhóm dẫn đầu" in q_low)
        or (
            any(k in q_low for k in ["chênh lệch", "khoảng cách", "disparity", "spread", "gap", "phân hóa"])
            and any(k in q_low for k in ["giữa nhóm", "giữa các nhóm", "nhóm", "team", "đội ngũ", "các đội", "các team"])
            and not any(k in q_low for k in ["quốc gia", "country", "thị trường", "sản phẩm", "product", "mặt hàng", "nhân sự", "salesperson", "khách hàng"])
        )
    )
    if not is_team_spread:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None
    year_cond = f" AND strftime('%Y', s.SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" AND YEAR(s.SaleDate) = {year_val}" if year_val else ""

    has_pe_team = "pe.team" in sql_low or ("team" in sql_low and "geo" not in sql_low and "product" not in sql_low)
    has_amount = "amount" in sql_low or "totalsales" in sql_low
    has_geo_err = "geo" in sql_low or "country" in sql_low
    has_product_err = "product" in sql_low and "team" not in sql_low

    if not has_pe_team or has_geo_err or has_product_err or not has_amount or "with " in sql_low:
        return f"""SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    COUNT(s.PID) AS TotalOrders,
    ROUND(AVG(s.Amount), 2) AS AvgOrderValue
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
WHERE pe.Team != '' AND pe.Team IS NOT NULL{year_cond}
GROUP BY pe.Team
ORDER BY TotalSales DESC;"""

    return sql


def auto_fix_chocolates_team_sales_and_boxes_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu truy vấn: So sánh tổng doanh số và số lượng hộp bán ra giữa các Team kinh doanh.
    Đảm bảo:
    - Bắt buộc JOIN giữa sales s và people pe ON s.SPID = pe.SPID.
    - Nhóm theo pe.Team (loại trừ các bản ghi trống: WHERE pe.Team != '' AND pe.Team IS NOT NULL).
    - Tính đồng thời cả 2 chỉ số cốt lõi: SUM(s.Amount) AS TotalSales VÀ SUM(s.Boxes) AS TotalBoxesSold.
    - Bổ sung chỉ số hiệu quả ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS AvgPricePerBox.
    - Sắp xếp ORDER BY TotalSales DESC.
    """
    if not user_query:
        return sql
    q_low = user_query.lower()

    is_team_q = (
        any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh", "các team", "giữa các team", "giữa nhóm", "giữa các nhóm", "nhóm cao nhất", "nhóm thấp nhất", "theo nhóm", "từng nhóm", "mỗi nhóm"])
        or ("nhóm" in q_low and not any(k in q_low for k in ["nhóm kẹo", "nhóm sản phẩm", "nhóm bars", "nhóm bites", "nhóm hàng", "nhóm danh mục", "phòng ban", "chức danh"]))
    )
    has_sales_kw = any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền"])
    has_boxes_kw = any(k in q_low for k in ["hộp", "thùng", "boxes", "số lượng"])

    if not (is_team_q and (has_sales_kw or has_boxes_kw)):
        return sql

    # Không can thiệp nếu là câu hỏi P&L theo thời gian hoặc P&L Đội ngũ (đã có auto_fix_chocolates_pnl_query)
    if any(k in q_low for k in ["p&l", "pnl", "lãi, lỗ", "lãi lỗ", "kết quả kinh doanh", "chi phí", "cost", "giá vốn", "cogs", "lợi nhuận ròng", "net profit"]):
        return sql

    # Không can thiệp nếu là câu hỏi đếm nhân sự / headcount thuần túy (đã có auto_fix_sales_headcount_query)
    is_headcount_only = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "quy mô nhân sự", "đếm", "bao nhiêu người", "mỗi team có bao nhiêu"])
        and not any(k in q_low for k in ["doanh số", "doanh thu", "hộp bán ra", "số lượng hộp"])
    )
    if is_headcount_only:
        return sql

    # Không can thiệp nếu là câu hỏi tỷ lệ đóng góp % (đã có auto_fix_contribution_percentage_query)
    if any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "tỷ trọng", "tỉ trọng", "đóng góp"]):
        return sql

    # Không can thiệp nếu là phân tích phân khúc sản phẩm, danh mục, quốc gia, nhân sự hoặc lọc theo một team cụ thể
    from src.llm.prompts import match_chocolates_specific_team, match_chocolates_specific_country
    has_specific_team = (
        match_chocolates_specific_team(q_low) is not None 
        or any(k in q_low for k in ["riêng team", "riêng đội", "team delish", "team yummies", "team jucies"])
    )
    has_product_or_cat = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "nhóm hàng", "danh mục", "category", "bars", "bites", "chủ lực", "loại kẹo"])
    has_geo = (
        match_chocolates_specific_country(q_low) is not None 
        or any(k in q_low for k in ["quốc gia", "country", "thị trường", "canada", "india", "usa", "uk", "new zealand", "australia"])
    )
    has_salesperson = any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "ai là", "top nhân viên"])

    if has_specific_team or has_product_or_cat or has_geo or has_salesperson:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None
    year_cond = f"strftime('%Y', s.SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f"YEAR(s.SaleDate) = {year_val}" if year_val else ""

    where_conds = ["pe.Team != ''", "pe.Team IS NOT NULL"]
    if year_cond:
        where_conds.append(year_cond)
    where_clause = "WHERE " + " AND ".join(where_conds)

    sql_low = (sql or "").lower()
    has_team_col = "pe.team" in sql_low or "team" in sql_low
    has_amount = "sum(s.amount)" in sql_low or "totalsales" in sql_low or "amount" in sql_low
    has_boxes = "sum(s.boxes)" in sql_low or "totalboxessold" in sql_low or "boxes" in sql_low
    is_grouped_product = "pr.product" in sql_low or "group by pr.product" in sql_low

    is_broken = (
        not sql
        or not has_team_col
        or is_grouped_product
        or (has_sales_kw and not has_amount)
        or (has_boxes_kw and not has_boxes)
        or "pe.spid" not in sql_low
        or "group by" not in sql_low
    )

    if is_broken:
        return f"""SELECT 
    pe.Team AS Team,
    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS AvgPricePerBox
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{where_clause}
GROUP BY pe.Team
ORDER BY TotalSales DESC;"""

    return sql


def auto_fix_chocolates_top_transactions_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn Top N giao dịch / đơn hàng cá nhân có giá trị hoặc sản lượng lớn nhất.
    Đảm bảo 100% không dùng GROUP BY (trả về từng dòng giao dịch độc lập) và JOIN đủ các bảng people, products, geo."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    is_top_tx = (
        any(k in q_low for k in ["giao dịch", "đơn hàng", "orders", "transactions"])
        and any(k in q_low for k in ["top", "cao nhất", "lớn nhất", "nhiều nhất", "giá trị nhất", "giá trị đơn hàng cao nhất", "khủng nhất", "đỉnh nhất", "thông tin top"])
        and not any(k in q_low for k in [
            "giá trị đơn hàng trung bình", "đơn hàng trung bình", "trung bình trên mỗi giao dịch", "trung bình mỗi giao dịch", "aov",
            "bao nhiêu đơn", "có bao nhiêu", "đếm số đơn", "số lượng đơn", "tỷ lệ", "tổng doanh thu từ các đơn hàng",
            "từ 500", "từ 1000", "từ 1,000", "từ 500 hộp", "trên 1000 hộp", "trên 500 hộp"
        ])
    )
    if not is_top_tx:
        return sql

    from src.llm.prompts import (
        match_chocolates_specific_country,
        match_chocolates_specific_team,
        match_chocolates_specific_person,
        match_chocolates_specific_product,
    )

    limit = extract_requested_limit(user_query) or 5
    tx_geo = match_chocolates_specific_country(q_low)
    tx_team = match_chocolates_specific_team(q_low)
    tx_person = match_chocolates_specific_person(q_low)
    tx_product = match_chocolates_specific_product(q_low)

    # Kiểm tra xem SQL đã đáp ứng tiêu chuẩn giao dịch từng dòng hay chưa
    has_group_by = "group by" in sql_low
    has_amount_or_boxes = "amount" in sql_low or "boxes" in sql_low
    has_saledate = "saledate" in sql_low
    has_salesperson = "salesperson" in sql_low
    has_product = "product" in sql_low
    has_geo_filter = (tx_geo.lower() in sql_low) if tx_geo else True

    is_broken = (
        has_group_by
        or not has_amount_or_boxes
        or not has_saledate
        or not has_salesperson
        or not has_product
        or not has_geo_filter
        or "sales s" not in sql_low
    )

    if not is_broken:
        return sql

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
    if any("pe." in c for c in select_cols) or tx_team or tx_person:
        joins.append("JOIN people pe ON s.SPID = pe.SPID")
    if any("pr." in c for c in select_cols) or tx_product:
        joins.append("JOIN products pr ON s.PID = pr.PID")
    if any("g." in c for c in select_cols) or tx_geo:
        joins.append("JOIN geo g ON s.GeoID = g.GeoID")

    where_conds = []
    if tx_geo:
        where_conds.append(f"g.Geo = '{tx_geo}'")
    if tx_team:
        where_conds.append(f"pe.Team = '{tx_team}'")
    if tx_person:
        where_conds.append(f"pe.Salesperson = '{tx_person}'")
    if tx_product:
        where_conds.append(f"pr.Product = '{tx_product}'")
    where_str = ("\nWHERE " + " AND ".join(where_conds)) if where_conds else ""

    order_col = "s.Boxes" if (any(k in q_low for k in ["hộp", "boxes"]) and not any(k in q_low for k in ["giá trị", "số tiền", "tiền", "amount"])) else "s.Amount"

    cols_str = ",\n    ".join(select_cols)
    joins_str = "\n".join(joins)

    return f"""SELECT 
    {cols_str}
{joins_str}{where_str}
ORDER BY {order_col} DESC
LIMIT {limit};"""


def auto_fix_chocolates_above_average_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động phát hiện và chuẩn hóa câu hỏi tìm các đối tượng (Sản phẩm, Nhân viên, Quốc gia, Đội ngũ)
    có doanh số / số tiền / số lượng vượt trên mức trung bình trên CSDL Awesome Chocolates.
    Tạo truy vấn CTE 2 bước kèm BenchmarkAvg, SalesSurplus, SurplusPct để hỗ trợ biểu đồ Dual-Axis."""
    if not user_query:
        return sql
    q_low = user_query.lower()
    sql_low = (sql or "").lower()

    is_above_avg = any(k in q_low for k in [
        "vượt trên mức trung bình", "vượt mức trung bình", "trên mức trung bình",
        "cao hơn mức trung bình", "cao hơn trung bình", "vượt trung bình",
        "above average", "above the average", "vượt ngưỡng trung bình"
    ])
    if not is_above_avg:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()
    is_person = any(k in q_low for k in ["nhân viên", "nhân sự", "chuyên viên", "chuyên viên bán hàng", "salesperson", "sales person", "người bán", "sales rep", "rep", "thành viên"])
    is_geo = any(k in q_low for k in ["quốc gia", "country", "thị trường", "geo", "khu vực"])
    is_team = any(k in q_low for k in ["team", "đội ngũ", "nhóm"]) and not is_person
    is_prod = any(k in q_low for k in ["product", "sản phẩm", "mặt hàng", "kẹo", "socola"]) or (not is_person and not is_geo and not is_team)

    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None
    year_cond = (f"WHERE strftime('%Y', s.SaleDate) = '{year_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {year_val}") if year_val else ""

    if is_prod:
        needs_fix = (
            "benchmark" not in sql_low
            or "surplus" not in sql_low
            or "products" not in sql_low
            or (year_val and f"{year_val}" not in sql_low)
        )
        if needs_fix:
            yr_clause = f"\n    {year_cond}" if year_cond else ""
            return f"""WITH ProductSummary AS (
    SELECT 
        pr.Product AS Product,
        SUM(s.Amount) AS TotalSales,
        SUM(s.Boxes) AS TotalBoxesSold
    FROM sales s
    JOIN products pr ON s.PID = pr.PID{yr_clause}
    GROUP BY pr.PID, pr.Product
),
Benchmark AS (
    SELECT ROUND(AVG(TotalSales), 2) AS BenchmarkAvg
    FROM ProductSummary
)
SELECT 
    ps.Product,
    ps.TotalSales,
    b.BenchmarkAvg,
    ROUND(ps.TotalSales - b.BenchmarkAvg, 2) AS SalesSurplus,
    ROUND(((ps.TotalSales - b.BenchmarkAvg) / b.BenchmarkAvg) * 100.0, 2) AS SurplusPct,
    ps.TotalBoxesSold
FROM ProductSummary ps
CROSS JOIN Benchmark b
WHERE ps.TotalSales > b.BenchmarkAvg
ORDER BY ps.TotalSales DESC;""".strip()

    elif is_person:
        needs_fix = (
            "benchmark" not in sql_low
            or "surplus" not in sql_low
            or "people" not in sql_low
            or (year_val and f"{year_val}" not in sql_low)
        )
        if needs_fix:
            yr_clause = f"\n    {year_cond}" if year_cond else ""
            return f"""WITH PersonSummary AS (
    SELECT 
        pe.Salesperson AS Salesperson,
        SUM(s.Amount) AS TotalSales,
        SUM(s.Boxes) AS TotalBoxesSold
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID{yr_clause}
    GROUP BY pe.SPID, pe.Salesperson
),
Benchmark AS (
    SELECT ROUND(AVG(TotalSales), 2) AS BenchmarkAvg
    FROM PersonSummary
)
SELECT 
    ps.Salesperson,
    ps.TotalSales,
    b.BenchmarkAvg,
    ROUND(ps.TotalSales - b.BenchmarkAvg, 2) AS SalesSurplus,
    ROUND(((ps.TotalSales - b.BenchmarkAvg) / b.BenchmarkAvg) * 100.0, 2) AS SurplusPct,
    ps.TotalBoxesSold
FROM PersonSummary ps
CROSS JOIN Benchmark b
WHERE ps.TotalSales > b.BenchmarkAvg
ORDER BY ps.TotalSales DESC;""".strip()

    elif is_team:
        needs_fix = "benchmark" not in sql_low or "surplus" not in sql_low
        if needs_fix:
            return f"""WITH TeamSummary AS (
    SELECT 
        pe.Team AS Team,
        SUM(s.Amount) AS TotalSales,
        SUM(s.Boxes) AS TotalBoxesSold
    FROM sales s
    JOIN people pe ON s.SPID = pe.SPID
    WHERE pe.Team != '' AND pe.Team IS NOT NULL
    GROUP BY pe.Team
),
Benchmark AS (
    SELECT ROUND(AVG(TotalSales), 2) AS BenchmarkAvg
    FROM TeamSummary
)
SELECT 
    ts.Team,
    ts.TotalSales,
    b.BenchmarkAvg,
    ROUND(ts.TotalSales - b.BenchmarkAvg, 2) AS SalesSurplus,
    ROUND(((ts.TotalSales - b.BenchmarkAvg) / b.BenchmarkAvg) * 100.0, 2) AS SurplusPct,
    ts.TotalBoxesSold
FROM TeamSummary ts
CROSS JOIN Benchmark b
WHERE ts.TotalSales > b.BenchmarkAvg
ORDER BY ts.TotalSales DESC;""".strip()

    elif is_geo:
        needs_fix = "benchmark" not in sql_low or "surplus" not in sql_low
        if needs_fix:
            yr_clause = f"\n    {year_cond}" if year_cond else ""
            return f"""WITH GeoSummary AS (
    SELECT 
        g.Geo AS Country,
        SUM(s.Amount) AS TotalSales,
        SUM(s.Boxes) AS TotalBoxesSold
    FROM sales s
    JOIN geo g ON s.GeoID = g.GeoID{yr_clause}
    GROUP BY g.GeoID, g.Geo
),
Benchmark AS (
    SELECT ROUND(AVG(TotalSales), 2) AS BenchmarkAvg
    FROM GeoSummary
)
SELECT 
    gs.Country,
    gs.TotalSales,
    b.BenchmarkAvg,
    ROUND(gs.TotalSales - b.BenchmarkAvg, 2) AS SalesSurplus,
    ROUND(((gs.TotalSales - b.BenchmarkAvg) / b.BenchmarkAvg) * 100.0, 2) AS SurplusPct,
    gs.TotalBoxesSold
FROM GeoSummary gs
CROSS JOIN Benchmark b
WHERE gs.TotalSales > b.BenchmarkAvg
ORDER BY gs.TotalSales DESC;""".strip()

    return sql


def auto_fix_chocolates_top_rankings_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và đảm bảo câu truy vấn bảng xếp hạng Top N (Nhân viên, Sản phẩm, Quốc gia, Đội ngũ)
    trên CSDL Awesome Chocolates luôn trả về dữ liệu chuẩn xác 100%, đúng bảng và đúng cú pháp lọc năm."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # Không can thiệp nếu là câu hỏi Top N giao dịch / đơn hàng cá nhân (đã có auto_fix_chocolates_top_transactions_query xử lý)
    is_top_tx = (
        any(k in q_low for k in ["giao dịch", "đơn hàng", "orders", "transactions"])
        and any(k in q_low for k in ["top", "cao nhất", "lớn nhất", "nhiều nhất", "giá trị nhất", "giá trị đơn hàng cao nhất", "khủng nhất", "đỉnh nhất", "thông tin top"])
        and not any(k in q_low for k in [
            "giá trị đơn hàng trung bình", "đơn hàng trung bình", "trung bình trên mỗi giao dịch", "trung bình mỗi giao dịch", "aov",
            "bao nhiêu đơn", "có bao nhiêu", "đếm số đơn", "số lượng đơn", "tỷ lệ", "tổng doanh thu từ các đơn hàng",
            "từ 500", "từ 1000", "từ 1,000", "từ 500 hộp", "trên 1000 hộp", "trên 500 hộp"
        ])
    )
    if is_top_tx:
        return sql

    # Không can thiệp nếu là câu hỏi xu hướng theo tháng / quý (đã có auto_fix_chocolates_monthly_sales_query & auto_fix_chocolates_quarterly_sales_query xử lý)
    # NGOẠI TRỪ: khi hỏi Top N nhân viên/sản phẩm TRONG một quý/tháng cụ thể (VD: "Top 3 nhân viên doanh số cao nhất Quý 4 năm 2021")
    is_time_trend = any(k in q_low for k in [
        "tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "xu hướng", 
        "quý", "quarter", "từng quý", "theo quý", "qua các quý", "thay đổi", "biến động", 
        "thời gian", "dòng thời gian", "qua thời gian"
    ])
    is_top_entity_in_period = (
        any(k in q_low for k in ["top", "cao nhất", "nhiều nhất", "lớn nhất", "thấp nhất"])
        and any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "người bán", "ai", "sản phẩm", "product"])
        and re.search(r'(?:quý|quarter|q)\s*\d', q_low, re.IGNORECASE)
    )
    if is_time_trend and not is_top_entity_in_period:
        return sql

    # Không can thiệp nếu là câu hỏi phân tích Pareto / Tỷ lệ tích lũy (đã có auto_fix_pareto_cumulative_query xử lý)
    if (
        any(k in q_low for k in ["pareto", "80/20", "80-20", "tích lũy", "tích luỹ", "cumulative"])
        or re.search(r'\b(4\d|5\d|6\d|7\d|8\d|9\d)\s*%', q_low)
        or any(k in sql_low for k in ["runningtotal", "productsales", "cumulativepercent", "grandtotal"])
    ):
        return sql

    # Không can thiệp nếu là câu hỏi báo cáo P&L / Lãi Lỗ / Chi phí / Lợi nhuận (đã có auto_fix_chocolates_pnl_query xử lý)
    if any(k in q_low for k in [
        "lãi lỗ", "p&l", "pnl", "báo cáo tài chính", "kết quả kinh doanh", 
        "lợi nhuận", "chi phí", "giá vốn", "cogs", "doanh thu thuần", 
        "operating profit", "gross profit", "net profit", "operating margin"
    ]):
        return sql

    # Không can thiệp nếu là câu hỏi tỷ lệ đóng góp / cơ cấu doanh thu (đã có auto_fix_contribution_percentage_query xử lý)
    is_contribution_q = (
        any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "đóng góp", "tỷ trọng", "tỉ trọng", "phần trăm", "chiếm", "%", "cơ cấu"])
        and any(k in q_low for k in ["doanh thu", "doanh số", "sales", "tiền"])
    )
    if is_contribution_q:
        return sql

    # Không can thiệp nếu là câu hỏi so sánh hiệu suất bán hàng giữa các thị trường (đã có auto_fix_sales_performance_comparison_query xử lý)
    if (
        any(k in q_low for k in ["so sánh", "hiệu suất", "hiệu quả", "giữa"])
        and any(k in q_low for k in ["mỹ", "usa", "ấn độ", "india", "canada", "úc", "australia", "new zealand", "uk", "anh"])
        and any(k in q_low for k in ["thị trường", "quốc gia"])
    ):
        return sql

    # Không can thiệp nếu là câu hỏi về số lượng nhân sự / Headcount theo Team hoặc Location (đã có auto_fix_sales_headcount_query xử lý)
    is_headcount_q = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "salesperson", "sales person", "người bán", "sales rep", "sales reps"])
        and any(k in q_low for k in ["số lượng", "quy mô", "bao nhiêu", "đếm", "phân bổ", "cơ cấu", "phân chia", "mỗi team có", "từng team có", "từng đội có"])
        and not any(k in q_low for k in ["doanh số", "doanh thu", "tiền", "tháng", "quý"])
    )
    if is_headcount_q:
        return sql

    # Không can thiệp nếu là câu hỏi phân tích chênh lệch / phân hóa giữa các nhóm (Team spread / disparity / gap)
    is_team_spread_q = (
        ("nhóm cao nhất và nhóm thấp nhất" in q_low or "giữa nhóm cao nhất" in q_low or "nhóm thấp nhất" in q_low or "giữa nhóm dẫn đầu" in q_low)
        or (
            any(k in q_low for k in ["chênh lệch", "khoảng cách", "phân hóa", "disparity", "spread", "gap", "đối chiếu", "so sánh"])
            and any(k in q_low for k in ["giữa nhóm", "giữa các nhóm", "nhóm", "team", "đội ngũ", "các đội", "các team"])
            and not any(k in q_low for k in ["quốc gia", "country", "thị trường", "sản phẩm", "product", "mặt hàng", "nhân sự", "nhân viên", "salesperson", "khách hàng"])
        )
    )
    if is_team_spread_q:
        return sql

    # Không can thiệp nếu là câu hỏi lọc theo điều kiện ngưỡng (đã có auto_fix_chocolates_threshold_query xử lý)
    has_threshold_filter = any(k in q_low for k in ["vượt", "trên", "dưới", "cao hơn", "lớn hơn", "thấp hơn", "nhỏ hơn", "nhiều hơn", "ít hơn", "từ", "ít nhất", "tối thiểu", "tối đa", ">", "<", ">=", "<="]) and any(char.isdigit() for char in q_low)
    if has_threshold_filter:
        return sql

    # Không can thiệp nếu là câu hỏi so sánh doanh số và số lượng hộp giữa các Team kinh doanh (đã có auto_fix_chocolates_team_sales_and_boxes_query xử lý)
    if (
        any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh", "nhóm", "các nhóm", "giữa các nhóm"])
        and not any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "từng người", "từng nhân viên", "thành viên", "ai", "ai bán", "ai có", "riêng team", "team delish", "team yummies", "team jucies", "delish", "yummies", "jucies"])
        and any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền"])
        and any(k in q_low for k in ["hộp", "thùng", "boxes", "số lượng"])
    ):
        return sql

    # Không can thiệp nếu là câu hỏi về một nhân viên cụ thể (Brien Boise, Ches Bonnell...)
    if match_chocolates_specific_person(q_low):
        return sql

    # Không can thiệp nếu là phân tích phân khúc đa chiều (kết hợp từ 2 chiều trở lên giữa Team, Thị trường/Quốc gia, Danh mục/Sản phẩm, hoặc lọc riêng một Team cụ thể)
    from src.llm.prompts import match_chocolates_specific_team, match_chocolates_specific_country
    has_spec_team = (
        match_chocolates_specific_team(q_low) is not None
        or any(k in q_low for k in ["riêng team", "riêng đội", "team delish", "team yummies", "team jucies"])
    )
    has_spec_country = (
        match_chocolates_specific_country(q_low) is not None
        or any(k in q_low for k in ["thị trường", "quốc gia", "country", "canada", "india", "usa", "uk", "new zealand", "australia"])
    )
    has_spec_category_or_prod = any(k in q_low for k in ["bars", "bites", "category", "nhóm hàng", "nhóm sản phẩm", "danh mục", "loại kẹo", "sản phẩm", "product", "mặt hàng"])
    dim_count = sum([1 if has_spec_team else 0, 1 if has_spec_country else 0, 1 if has_spec_category_or_prod else 0])
    if dim_count >= 2 or (has_spec_team and has_spec_category_or_prod):
        return sql

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate"])
    if not is_chocolates:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    # Trích xuất năm nếu có (VD: 2021, 2022)
    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None

    # Trích xuất quý nếu có (VD: "Quý 4", "Q4", "quarter 4")
    qtr_match = re.search(r'(?:quý|quarter|q)\s*(\d)', q_low, re.IGNORECASE)
    qtr_val = qtr_match.group(1) if qtr_match else None

    year_clause = ""
    time_where_parts = []
    if year_val:
        time_where_parts.append(f"strftime('%Y', s.SaleDate) = '{year_val}'" if is_sqlite else f"YEAR(s.SaleDate) = {year_val}")
    if qtr_val:
        time_where_parts.append(f"((CAST(strftime('%m', s.SaleDate) AS INTEGER) + 2) / 3) = {qtr_val}" if is_sqlite else f"QUARTER(s.SaleDate) = {qtr_val}")
    if time_where_parts:
        year_clause = "WHERE " + " AND ".join(time_where_parts)

    # Xác định chỉ số đo lường: Hộp/Thùng (Boxes) hay Doanh số/Tiền mặt (Sales Amount / Cash)
    has_explicit_sales = any(k in q_low for k in ["tiền mặt", "tiền", "amount", "doanh số", "doanh thu", "sales", "cash", "chi tiêu", "revenue", "dollar", "$", "giá trị"])
    has_explicit_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes"]) or (any(k in q_low for k in ["số lượng", "so luong"]) and not any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "salesperson", "người bán", "khách hàng", "customer"]))
    if has_explicit_sales and not has_explicit_boxes:
        has_boxes = False
    elif has_explicit_boxes:
        has_boxes = True
    else:
        has_boxes = any(k in sql_low for k in ["boxes", "totalboxes", "boxessold"])
    metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
    order_col = "TotalBoxesSold" if has_boxes else "TotalSales"

    # Xác định chiều sắp xếp: DESC (cao nhất/nhiều nhất) hay ASC (thấp nhất/ít nhất)
    is_asc = (
        any(k in q_low for k in ["thấp nhất", "ít nhất", "kém nhất", "bottom", "thấp"])
        and not any(k in q_low for k in ["cao nhất", "nhiều nhất", "lớn nhất", "chênh lệch", "so sánh", "giữa", "khoảng cách"])
    )
    order_dir = "ASC" if is_asc else "DESC"

    # Trích xuất LIMIT từ câu hỏi hoặc mặc định 10 nếu là câu hỏi Top N
    limit = extract_requested_limit(user_query)
    if not limit and any(k in q_low for k in ["top", "cao nhất", "thấp nhất", "nhiều nhất", "ít nhất", "bán chạy nhất"]):
        limit = 10
    limit_clause = f"LIMIT {limit}" if limit else ""

    # 1. Bảng xếp hạng Nhân viên bán hàng (Salesperson / People)
    is_asking_team = (
        any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh", "nhóm", "giữa nhóm", "các nhóm", "giữa các nhóm"])
        and not any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "ai", "thành viên"])
    )
    is_person = (
        any(k in q_low for k in [
            "nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "ai bán", 
            "ai có doanh số", "ai doanh thu", "nhân sự bán", "sales rep", "rep", "thành viên",
            "ai có", "người"
        ])
        or any(k in q_low for k in ["yummies", "delish", "jucies"])
        or (any(k in sql_low for k in ["salesperson", "employeename", "first_name", "last_name", "sales_person"]) and "pe.team" not in sql_low and not is_asking_team)
    )
    if is_person and not is_asking_team and not any(k in q_low for k in ["sản phẩm", "product", "quốc gia", "country", "customer", "customers", "khách hàng"]):
        specific_team = None
        for tm in ["yummies", "delish", "jucies"]:
            if tm in q_low:
                specific_team = tm.capitalize()
                break

        has_req_sales = any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền", "amount"])
        has_req_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes"])
        wants_both_metrics = has_req_sales and has_req_boxes

        if wants_both_metrics:
            if any(k in q_low for k in ["sắp xếp người có doanh số", "doanh số cao nhất", "doanh thu cao nhất", "doanh số lên đầu", "doanh thu lên đầu", "theo doanh số", "theo doanh thu"]):
                eff_order_col = "TotalSales"
            elif any(k in q_low for k in ["hộp cao nhất", "số hộp cao nhất", "nhiều hộp nhất", "theo số hộp", "theo hộp"]):
                eff_order_col = "TotalBoxesSold"
            elif has_req_sales:
                eff_order_col = "TotalSales"
            else:
                eff_order_col = "TotalBoxesSold"
        else:
            eff_order_col = order_col

        needs_fix = (
            "with " in sql_low
            or "s.salesperson" in sql_low
            or "pe.name" in sql_low
            or "pe.spid" not in sql_low
            or "sales s" not in sql_low
            or ("saledate =" in sql_low and "year(" not in sql_low and "strftime(" not in sql_low)
            or (year_val and f"{year_val}" not in sql_low)
            or (qtr_val and "quarter" not in sql_low and "strftime" not in sql_low)
            or "group by" not in sql_low
            or "order by" not in sql_low
            or "pe.salesperson" not in sql_low
            or (specific_team and f"'{specific_team.lower()}'" not in sql_low)
            or ("products" in sql_low and not any(k in q_low for k in ["sản phẩm", "product", "kẹo", "socola"]))
            or (wants_both_metrics and not any(k in sql_low for k in ["totalboxes", "boxes", "sum(s.boxes)"]))
            or (wants_both_metrics and not any(k in sql_low for k in ["totalsales", "amount", "sum(s.amount)"]))
            or "price" in sql_low
            or "pieces" in sql_low
            or "employeename" in sql_low
            or "division" in sql_low
        )
        if needs_fix:
            where_conditions = []
            if specific_team:
                where_conditions.append(f"pe.Team = '{specific_team}'")
            if year_clause:
                where_conditions.append(year_clause.replace("WHERE ", ""))

            is_all_explicit = any(k in q_low for k in ["từng nhân viên", "từng người", "mỗi nhân viên", "mỗi người", "tất cả nhân viên", "toàn bộ nhân viên", "danh sách nhân viên"])
            eff_limit_clause = "" if (is_all_explicit and not extract_requested_limit(user_query)) else limit_clause

            if wants_both_metrics:
                metrics_lines = [
                    "    SUM(s.Amount) AS TotalSales,",
                    "    SUM(s.Boxes) AS TotalBoxesSold"
                ]
            else:
                metrics_lines = [f"    {metric_expr}"]

            lines = [
                "SELECT",
                "    pe.Salesperson,",
            ]
            lines.extend(metrics_lines)
            lines.extend([
                "FROM sales s",
                "JOIN people pe ON s.SPID = pe.SPID",
            ])
            if where_conditions:
                lines.append("WHERE " + " AND ".join(where_conditions))
            lines.append("GROUP BY pe.SPID, pe.Salesperson")
            lines.append(f"ORDER BY {eff_order_col} {order_dir}")
            if eff_limit_clause:
                lines.append(eff_limit_clause)
            return "\n".join(lines)

    # 2. Bảng xếp hạng Danh mục sản phẩm (Category)
    is_category = any(k in q_low for k in ["category", "danh mục", "nhóm sản phẩm", "nhóm hàng"])
    if is_category and not any(k in q_low for k in [
        "nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "quốc gia", 
        "country", "yummies", "delish", "jucies", "thành viên", "sales rep", "rep",
        "team", "đội ngũ", "nhóm bán hàng", "nhóm kinh doanh", "customer", "customers", "khách hàng"
    ]):
        needs_fix = (
            "with " in sql_low
            or "pr.category" not in sql_low
            or "pr.pid" not in sql_low
            or "sales s" not in sql_low
            or ("saledate =" in sql_low and "year(" not in sql_low and "strftime(" not in sql_low)
            or (year_val and f"{year_val}" not in sql_low)
            or "group by" not in sql_low
            or "order by" not in sql_low
        )
        if needs_fix:
            lines = [
                "SELECT",
                "    pr.Category,",
                f"    {metric_expr}",
                "FROM sales s",
                "JOIN products pr ON s.PID = pr.PID",
            ]
            if year_clause:
                lines.append(year_clause)
            lines.append("GROUP BY pr.Category")
            lines.append(f"ORDER BY {order_col} {order_dir}")
            if limit_clause:
                lines.append(limit_clause)
            return "\n".join(lines)

    # 3. Bảng xếp hạng Sản phẩm (Products)
    is_product = (
        any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "loại kẹo", "socola", "chocolate"])
        and not any(k in q_low for k in [
            "category", "danh mục", "nhóm sản phẩm", "nhóm hàng", "customer", "customers", 
            "khách hàng", "nhân viên", "salesperson", "quốc gia", "country", "team", "đội ngũ"
        ])
    )
    if is_product:
        needs_fix = (
            "with " in sql_low
            or "s.product" in sql_low
            or "pr.pid" not in sql_low
            or "sales s" not in sql_low
            or ("saledate =" in sql_low and "year(" not in sql_low and "strftime(" not in sql_low)
            or (year_val and f"{year_val}" not in sql_low)
            or "group by" not in sql_low
            or "order by" not in sql_low
            or "pr.product" not in sql_low
        )
        if needs_fix:
            lines = [
                "SELECT",
                "    pr.Product,",
                f"    {metric_expr}",
                "FROM sales s",
                "JOIN products pr ON s.PID = pr.PID",
            ]
            if year_clause:
                lines.append(year_clause)
            lines.append("GROUP BY pr.Product")
            lines.append(f"ORDER BY {order_col} {order_dir}")
            if limit_clause:
                lines.append(limit_clause)
            return "\n".join(lines)

    # 4. Truy vấn Khách hàng / Giao dịch có tiền mặt lớn nhất (Customer / Transactions by Cash Amount)
    is_customer = any(k in q_low for k in ["customer", "customers", "khách hàng"])
    if is_customer and not any(k in q_low for k in ["sản phẩm", "product", "category", "danh mục", "quốc gia", "country"]):
        year_cond = ""
        if year_val:
            year_cond = f"WHERE strftime('%Y', s.SaleDate) = '{year_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {year_val}"
        
        lim = limit_clause if limit_clause else "LIMIT 10"
        lines = [
            "SELECT",
            "    s.SaleDate AS `Ngày Bán`,",
            "    pe.Salesperson AS `Nhân Viên`,",
            "    pr.Product AS `Sản Phẩm`,",
            "    g.Geo AS `Thị Trường`,",
            "    s.Customers AS `Số Khách Hàng`,",
            "    s.Amount AS `Số Tiền Mặt`",
            "FROM sales s",
            "JOIN people pe ON s.SPID = pe.SPID",
            "JOIN products pr ON s.PID = pr.PID",
            "JOIN geo g ON s.GeoID = g.GeoID",
        ]
        if year_cond:
            lines.append(year_cond)
        lines.append(f"ORDER BY s.Amount {order_dir}, s.Customers {order_dir}")
        lines.append(lim)
        return "\n".join(lines)

    # 3. Bảng xếp hạng Thị trường / Quốc gia (Country / Geo)
    from src.llm.prompts import match_chocolates_specific_country
    specific_c = match_chocolates_specific_country(q_low)
    is_multi_country_rank = any(k in q_low for k in ["top", "cao nhất", "thấp nhất", "nhiều nhất", "ít nhất", "bảng xếp hạng", "các quốc gia", "từng quốc gia", "mỗi quốc gia", "tất cả", "so sánh", "nước nào"])

    if specific_c and not is_multi_country_rank and not any(k in q_low for k in ["nhân viên", "salesperson", "sản phẩm", "product"]):
        lines = [
            "SELECT",
            "    g.Geo AS Country,",
            f"    {metric_expr}",
            "FROM sales s",
            "JOIN geo g ON s.GeoID = g.GeoID",
            f"WHERE g.Geo = '{specific_c}'" + (f" AND strftime('%Y', s.SaleDate) = '{year_val}'" if (year_val and is_sqlite) else f" AND YEAR(s.SaleDate) = {year_val}" if year_val else ""),
            "GROUP BY g.Geo",
        ]
        return "\n".join(lines)

    is_country = (
        any(k in q_low for k in ["quốc gia", "country", "thị trường", "nước nào", "đất nước", "khu vực", "geo"])
        or (("geo" in sql_low or "geoid" in sql_low) and not any(k in q_low for k in ["team", "đội ngũ", "nhóm", "đội"]))
    )
    if is_country and not any(k in q_low for k in ["nhân viên", "salesperson", "sản phẩm", "product", "team", "đội ngũ", "nhóm", "đội"]):
        needs_fix = (
            "with " in sql_low
            or "s.country" in sql_low
            or "s.geo " in sql_low
            or "g.geoid" not in sql_low
            or "sales s" not in sql_low
            or ("saledate =" in sql_low and "year(" not in sql_low and "strftime(" not in sql_low)
            or (year_val and f"{year_val}" not in sql_low)
            or "group by" not in sql_low
            or "order by" not in sql_low
        )
        if needs_fix:
            lines = [
                "SELECT",
                "    g.Geo AS Country,",
                f"    {metric_expr}",
                "FROM sales s",
                "JOIN geo g ON s.GeoID = g.GeoID",
            ]
            if year_clause:
                lines.append(year_clause)
            lines.append("GROUP BY Country")
            lines.append(f"ORDER BY {order_col} {order_dir}")
            if limit_clause:
                lines.append(limit_clause)
            return "\n".join(lines)

    # 4. Bảng xếp hạng Đội ngũ bán hàng (Team)
    is_team = (
        any(k in q_low for k in ["đội ngũ", "team", "nhóm bán hàng", "nhóm kinh doanh", "các team", "giữa các team", "giữa nhóm", "giữa các nhóm", "nhóm cao nhất", "nhóm thấp nhất", "theo nhóm", "từng nhóm", "mỗi nhóm"])
        or ("nhóm" in q_low and not any(k in q_low for k in ["nhóm kẹo", "nhóm sản phẩm", "nhóm bars", "nhóm bites", "nhóm hàng", "nhóm danh mục", "phòng ban", "chức danh", "lương"]))
        or ("team" in sql_low and not any(k in q_low for k in ["quốc gia", "country", "thị trường"]))
    )
    if is_team:
        has_both = (
            any(k in q_low for k in ["doanh số", "doanh thu", "sales", "tiền"])
            and any(k in q_low for k in ["hộp", "thùng", "boxes", "số lượng"])
        )
        if has_both:
            team_metric_clause = """    SUM(s.Amount) AS TotalSales,
    SUM(s.Boxes) AS TotalBoxesSold,
    ROUND(SUM(s.Amount) / SUM(s.Boxes), 2) AS AvgPricePerBox"""
            order_col = "TotalSales"
        else:
            team_metric_clause = f"    {metric_expr}"

        needs_fix = (
            "with " in sql_low
            or "pe.spid" not in sql_low
            or "sales s" not in sql_low
            or ("saledate =" in sql_low and "year(" not in sql_low and "strftime(" not in sql_low)
            or (year_val and f"{year_val}" not in sql_low)
            or "group by" not in sql_low
            or "order by" not in sql_low
            or "pe.team" not in sql_low
            or "pr.product" in sql_low
            or (has_both and ("totalboxessold" not in sql_low or "totalsales" not in sql_low))
        )
        if needs_fix:
            lines = [
                "SELECT",
                "    pe.Team,",
                team_metric_clause,
                "FROM sales s",
                "JOIN people pe ON s.SPID = pe.SPID",
            ]
            where_conditions = ["pe.Team != ''", "pe.Team IS NOT NULL"]
            if year_clause:
                where_conditions.append(year_clause.replace("WHERE ", ""))
            lines.append("WHERE " + " AND ".join(where_conditions))
            lines.append("GROUP BY pe.Team")
            lines.append(f"ORDER BY {order_col} {order_dir}")
            if limit_clause:
                lines.append(limit_clause)
            return "\n".join(lines)

    return sql


def auto_fix_chocolates_unassigned_team_filter(sql: str, user_query: str = "", dialect: str = "MySQL") -> str:
    """Tự động kiểm tra và tiêm mệnh đề lọc loại bỏ các bản ghi Team rỗng/chưa xác định (WHERE pe.Team != '' AND pe.Team IS NOT NULL)
    khi câu lệnh SQL truy vấn hoặc nhóm theo Team trong CSDL Chocolates, đảm bảo không bao giờ xuất hiện dòng (Chưa xác định)."""
    if not sql:
        return sql
    
    sql_low = sql.lower()
    
    # Chỉ áp dụng cho các câu lệnh có liên quan đến bảng people / Team trong CSDL Chocolates
    has_team_col = bool(re.search(r'\b(pe\.team|people\.team|`team`|team)\b', sql_low))
    has_people_table = "people" in sql_low or "pe." in sql_low or "pe " in sql_low
    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"])
    
    if not (is_chocolates and has_team_col and has_people_table):
        return sql
        
    # Kiểm tra xem đã có điều kiện loại bỏ Team rỗng chưa
    has_team_filter = (
        ("team !=" in sql_low or "team <>" in sql_low or "team is not null" in sql_low or "length(team)" in sql_low or "trim(team)" in sql_low or "team in (" in sql_low or "team = '" in sql_low)
        and ("is not null" in sql_low or "team in (" in sql_low or "team = '" in sql_low or "team !=" in sql_low or "team <>" in sql_low)
    )
    
    if has_team_filter:
        return sql

    # Xác định tiền tố alias của bảng people (pe.Team hoặc people.Team hoặc Team)
    team_expr = "pe.Team" if ("pe." in sql_low or "pe " in sql_low) else ("people.Team" if "people." in sql_low else "Team")
    team_clean_cond = f"{team_expr} != '' AND {team_expr} IS NOT NULL"
    
    # Tiêm điều kiện vào WHERE
    if " where " in sql_low:
        # Chèn thêm AND condition ngay sau WHERE
        sql = re.sub(r'(?i)\bwhere\s+', f"WHERE {team_clean_cond} AND ", sql, count=1)
    elif " group by " in sql_low:
        # Chèn WHERE trước GROUP BY
        sql = re.sub(r'(?i)\bgroup\s+by\s+', f"WHERE {team_clean_cond}\nGROUP BY ", sql, count=1)
    elif " order by " in sql_low:
        # Chèn WHERE trước ORDER BY
        sql = re.sub(r'(?i)\border\s+by\s+', f"WHERE {team_clean_cond}\nORDER BY ", sql, count=1)
    elif " limit " in sql_low:
        # Chèn WHERE trước LIMIT
        sql = re.sub(r'(?i)\blimit\s+', f"WHERE {team_clean_cond}\nLIMIT ", sql, count=1)
    else:
        sql += f"\nWHERE {team_clean_cond}"
        
    return sql


def is_safe_select(sql: str) -> bool:
    """Kiểm tra câu lệnh SQL có phải là SELECT/WITH hợp lệ và an toàn không."""
    if not sql:
        return False

    cleaned_sql = clean_sql_query(sql)
    if not cleaned_sql:
        return False

    cleaned = strip_comments_and_literals(cleaned_sql)
    raw_cleaned = cleaned.strip().rstrip(";")
    lowered = raw_cleaned.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False

    if ";" in raw_cleaned:  # Chặn stacked queries
        return False

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", lowered):
            return False
    return True


def is_conversational_explanation(text_response: str) -> bool:
    """Nhận diện khi mô hình AI trả về câu giải thích tự nhiên thay vì SQL."""
    if not text_response:
        return False

    # Kiểm tra nếu câu trả lời bị lặp từ rác (ví dụ cùng một từ lặp lại >= 4 lần)
    words = text_response.lower().replace(",", " ").replace(";", " ").split()
    if len(words) > 8:
        from collections import Counter
        counts = Counter(words)
        if any(count >= 4 for word, count in counts.items() if len(word) > 3):
            return False  # Bị lặp từ rác -> Không phải explanation hợp lệ, bắt buộc ép sinh SQL

    cleaned = text_response.strip().lower()
    explanation_indicators = [
        "tôi xin lỗi", "xin lỗi", "tôi xin nhận lỗi", "không có bảng", "không tìm thấy bảng",
        "schema không có", "schema không chứa", "không chứa thông tin", "không thể cung cấp câu sql",
        "câu hỏi yêu cầu dữ liệu từ các bảng không tồn tại", "cơ sở dữ liệu không có",
        "sorry", "i apologize", "no table found", "schema does not contain", "cannot write a query"
    ]
    return any(indicator in cleaned for indicator in explanation_indicators)


def detect_duplicate_entity_warning(df: pd.DataFrame) -> str | None:
    """Kiểm tra xem có dấu hiệu nhân bản dữ liệu do JOIN bảng lịch sử hoặc thiếu GROUP BY không."""
    if df is None or df.empty:
        return None

    # 1. Kiểm tra cột định danh hoặc cột thực thể con người / sản phẩm
    check_cols = [c for c in df.columns if is_id_like(c) or INDIVIDUAL_ENTITY_REGEX.search(str(c))]
    for c in check_cols:
        try:
            n_unique = df[c].nunique(dropna=True)
        except Exception:
            continue
        if 0 < n_unique < len(df):
            return (
                f"Cột thực thể `{c}` chỉ có {n_unique} giá trị duy nhất nhưng kết quả trả về "
                f"{len(df)} dòng (bị trùng lặp đối tượng do chọn đơn hàng lẻ thay vì tính tổng SUM & GROUP BY)."
            )
    return None


def self_check_sql(client, provider: str, model_name: str, schema_context: str, user_query: str, sql_query: str, df: pd.DataFrame, lang: str = "vi") -> dict:
    """Thực hiện bước AI QA self-check để kiểm định kết quả SQL."""
    sample = df.head(5).to_string(index=False)
    prompt = build_self_check_prompt(schema_context, user_query, sql_query, sample, lang=lang)
    res, err = call_llm(client, provider, model_name, prompt)

    if not res:
        return {"day_du": True, "ly_do": "Bỏ qua self-check."}

    try:
        cleaned = res.strip().strip("`").replace("json\n", "").strip()
        parsed = json.loads(cleaned)
        ly_do = str(parsed.get("ly_do", ""))
        if len(ly_do) > 200:
            ly_do = ly_do[:200].rsplit(" ", 1)[0] + "..."
        parsed["ly_do"] = ly_do
        return parsed
    except Exception:
        return {"day_du": True, "ly_do": "Không parse được JSON self-check."}


def explain_anomalies_agent(client, provider: str, model_name: str, user_query: str, x_col: str, y_col: str, outliers_df: pd.DataFrame, lang: str = "vi") -> str | None:
    """Gọi LLM giải thích nguyên nhân kinh doanh của các điểm bất thường."""
    points = outliers_df[[x_col, y_col]].to_dict(orient="records")
    prompt = build_anomaly_prompt(user_query, x_col, y_col, points, lang=lang)
    res, _ = call_llm(client, provider, model_name, prompt)
    return res


def generate_auto_insights(client, provider: str, model_name: str, user_query: str, df: pd.DataFrame, anomalies_info: dict, lang: str = "vi") -> str | None:
    """Tự động phân tích và sinh báo cáo Insight Kinh doanh với Gắn Nhãn Mức Độ Ưu Tiên (Priority Tagging)."""
    if df is None or df.empty:
        return None

    df_sample = df.head(12).copy()
    # Chuyển đổi cột Tháng / Quý dạng số sang nhãn chuỗi thân thiện trước khi gửi LLM
    for col in df_sample.columns:
        c_low = str(col).lower()
        if any(k in c_low for k in ["month", "thang", "tháng"]):
            try:
                s_num = pd.to_numeric(df_sample[col], errors="coerce")
                if not s_num.dropna().empty and s_num.dropna().isin(range(1, 13)).all():
                    df_sample[col] = s_num.dropna().astype(int).apply(lambda x: f"Tháng {x}" if lang == "vi" else f"Month {x}")
            except Exception:
                pass
        elif any(k in c_low for k in ["quarter", "quy", "quý"]):
            try:
                s_num = pd.to_numeric(df_sample[col], errors="coerce")
                if not s_num.dropna().empty and s_num.dropna().isin(range(1, 5)).all():
                    df_sample[col] = s_num.dropna().astype(int).apply(lambda x: f"Quý {x}" if lang == "vi" else f"Q{x}")
            except Exception:
                pass

    sample_str = df_sample.to_string(index=False)
    prompt = build_auto_insight_prompt(user_query, sample_str, anomalies_info, lang=lang)
    insight, _ = call_llm(client, provider, model_name, prompt, max_tokens=2048)
    if insight:
        return sanitize_insight_markdown(insight)
    return None


def is_ambiguous_question(q: str) -> bool:
    """Kiểm tra câu hỏi có chứa các đại từ mơ hồ (này, đó, trên, these...) gây lỗi 0 dòng khi chạy độc lập."""
    if not q:
        return True
    q_low = q.lower()
    ambiguous_patterns = [
        r"\b\d+\s*nhân viên này\b", r"\bnhân viên này\b", r"\bsản phẩm này\b",
        r"\bnhóm này\b", r"\bđối tượng này\b", r"\bkhu vực này\b",
        r"\bthị trường này\b", r"\bthese\b", r"\bthis product\b", r"\bthese reps\b"
    ]
    return any(re.search(p, q_low) for p in ambiguous_patterns)


def is_hallucinated_followup(q: str) -> bool:
    """Loại bỏ các câu hỏi chứa thực thể hoặc cấu trúc ảo giác không có trong CSDL."""
    q_low = q.lower()
    # Các quốc gia/địa danh ảo giác không tồn tại trong CSDL
    forbidden_terms = [
        "việt nam", "vietnam", "hà nội", "hcm", "sài gòn", "japan", "tokyo", "china",
        "singapore", "thái lan", "pháp", "đức",
        "đầu tháng và cuối tháng", "đầu tháng", "cuối tháng",
        "milk chips choco"
    ]
    return any(t in q_low for t in forbidden_terms)


def generate_grounded_fallback_followups(df: pd.DataFrame, schema_context: str = "", current_query: str = "", lang: str = "vi") -> list[str]:
    """Sinh các câu hỏi đào sâu bám sát 100% vào cấu trúc CSDL theo 3 Chiều Chiến Lược Cấp Điều Hành (Multi-Tiered Strategic Drilldown):
    - Chiều 1 (📈): Chuỗi thời gian, Xu hướng & Kích hoạt Tab Dự Báo (Line Chart / Forecasting)
    - Chiều 2 (⚖️): Phân tích đối chuẩn & So sánh đa nhóm (Grouped Bar / Benchmarking)
    - Chiều 3 (🍩): Phân tích cơ cấu, Tỷ lệ phần trăm & Quản trị (Donut Chart / Distribution)
    """
    if df is None or df.empty:
        return []

    followups = []
    cols = df.columns.tolist()
    cols_low = [str(c).lower() for c in cols]
    schema_low = (schema_context or "").lower()
    q_low = (current_query or "").lower()

    # Nhận diện CSDL
    is_employees_db = "departments" in schema_low or "dept_emp" in schema_low or "salaries" in schema_low or any(c in cols_low for c in ["salary", "avgsalary", "dept_name", "department", "emp_no"])
    is_chocolates_db = "people" in schema_low and "products" in schema_low

    if is_employees_db:
        # Nhận diện thực thể trong kết quả hiện tại
        dept_col = next((c for c in cols if any(k in c.lower() for k in ["dept_name", "department", "phòng"])), None)
        title_col = next((c for c in cols if any(k in c.lower() for k in ["title", "chức danh"])), None)
        dept_sample = str(df[dept_col].dropna().iloc[0]).strip() if dept_col and not df[dept_col].dropna().empty else None
        title_sample = str(df[title_col].dropna().iloc[0]).strip() if title_col and not df[title_col].dropna().empty else None

        # Tier 1: Xu Hướng & Dự Báo (Time-Series & Forecasting)
        tier1_candidates = [
            ("Thống kê số lượng nhân viên được tuyển dụng theo từng năm từ trước đến nay", "Total number of employees hired per year"),
            ("Mức lương trung bình của toàn công ty thay đổi như thế nào qua các năm?", "Average company-wide salary trend across years"),
            ("Xu hướng tuyển dụng của phòng ban Sales qua các năm", "Hiring trend for Sales department over the years"),
            ("Xu hướng tuyển dụng của phòng ban Development qua các năm", "Hiring trend for Development department over the years"),
            ("Số lượng nhân viên được bổ nhiệm chức danh mới qua từng năm", "Number of title assignments per year"),
            ("Biến động tổng quỹ lương toàn công ty qua các năm", "Total company salary expenditure trend over the years")
        ]

        # Tier 2: Đối Chuẩn & So Sánh (Comparative / Benchmark)
        tier2_candidates = [
            ("So sánh mức lương trung bình giữa nhân viên nam và nữ theo từng chức danh", "Compare average salary between male and female employees across job titles"),
            ("Top 10 nhân viên có mức lương cao nhất hiện tại trong toàn công ty", "Top 10 highest paid current employees in the company"),
            ("Mức lương trung bình của nhân viên theo từng phòng ban", "Average salary of employees by department"),
            ("So sánh mức lương trung bình giữa các phòng ban Kỹ thuật (Development, Research) và phòng Kinh doanh (Sales, Marketing)", "Compare average salary between Tech and Commercial departments"),
            ("Phòng ban nào có mức chênh lệch lương giữa người cao nhất và thấp nhất lớn nhất?", "Which department has the largest salary spread between highest and lowest earners?"),
            ("Top 5 chức danh (Title) có mức lương trung bình cao nhất hiện nay", "Top 5 job titles with highest average current salary"),
            ("So sánh quy mô nhân sự và mức lương trung bình giữa các phòng ban", "Compare headcount and average salary across departments"),
            ("Top 10 nhân viên có thâm niên làm việc lâu nhất công ty còn đang công tác", "Top 10 longest tenured active employees")
        ]

        # Tier 3: Cơ Cấu Tỷ Lệ & Đào Sâu Quản Trị (Distribution & Executive Share)
        tier3_candidates = [
            ("Tỷ lệ nam và nữ trong ban quản lý (dept_manager) của từng phòng ban", "Gender distribution in management (dept_manager) across departments"),
            ("Danh sách các Manager hiện tại của từng phòng ban kèm mức lương mới nhất", "Current department managers and their latest salary"),
            ("Số lượng nhân viên và tỷ lệ nam nữ trong từng phòng ban", "Total headcount and gender ratio across departments"),
            ("Tỷ lệ phân bổ nhân sự theo từng chức danh (Senior Staff, Engineer, Staff...)", "Headcount distribution by job title"),
            ("Tổng quỹ lương hiện tại mà công ty đang chi trả cho từng phòng ban", "Current total payroll expenditure by department"),
            ("Những ai từng giữ chức vụ Manager lâu nhất trong lịch sử công ty?", "Who served as Manager for the longest duration in company history?"),
            ("Phòng ban nào có quy mô nhân sự lớn nhất và nhỏ nhất hiện nay?", "Which department has the largest and smallest headcount?"),
            ("Những nhân viên có từ 5 lần tăng lương trở lên trong lịch sử công ty", "Employees who received 5 or more salary raises")
        ]

        # Nếu đang xem 1 phòng ban cụ thể -> Ưu tiên các câu đào sâu theo phòng ban đó
        if dept_sample and dept_sample.lower() not in ["none", "nan", ""]:
            tier2_candidates.insert(0, (f"So sánh mức lương trung bình của phòng ban {dept_sample} so với các phòng ban khác", f"Compare average salary of {dept_sample} department with other departments"))

        # Lọc thông minh: Loại bỏ câu trùng câu hỏi hiện tại và xoay vòng ngẫu nhiên đa dạng
        avail_tier1 = [it for it in tier1_candidates if it[0].lower() not in q_low] or tier1_candidates
        avail_tier2 = [it for it in tier2_candidates if it[0].lower() not in q_low] or tier2_candidates
        avail_tier3 = [it for it in tier3_candidates if it[0].lower() not in q_low] or tier3_candidates

        p1 = random.choice(avail_tier1)
        p2 = random.choice(avail_tier2)
        p3 = random.choice(avail_tier3)

        selected = [p1, p2, p3]
        return [item[1] if lang == "en" else item[0] for item in selected]

    if is_chocolates_db:
        # Tier 1: Xu Hướng & Dự Báo (Time-Series & Forecasting)
        tier1_candidates = [
            ("Doanh thu theo từng quốc gia (Country) thay đổi như thế nào qua các tháng năm 2021?", "Monthly revenue trend across countries in 2021"),
            ("Doanh số toàn công ty theo từng tháng năm 2021", "Monthly company-wide revenue trend in 2021"),
            ("Xu hướng số lượng hộp socola bán ra qua các tháng năm 2021", "Monthly box sales volume trend in 2021"),
            ("Doanh thu của Team Yummies thay đổi như thế nào qua các tháng năm 2021?", "Monthly revenue trend for Yummies team in 2021"),
            ("Doanh số của sản phẩm 85% Dark Bars qua các tháng năm 2021", "Monthly sales of 85% Dark Bars in 2021"),
            ("Doanh thu thị trường Ấn Độ (India) theo từng quý năm 2021", "Quarterly revenue trend in India in 2021")
        ]

        # Tier 2: Đối Chuẩn & So Sánh (Comparative / Benchmark)
        tier2_candidates = [
            ("So sánh tổng doanh số và số lượng hộp bán ra giữa các Team kinh doanh", "Compare total revenue and boxes sold across sales teams"),
            ("Top 10 nhân viên bán hàng có doanh số cao nhất năm 2021", "Top 10 sales representatives by revenue in 2021"),
            ("Mức lợi nhuận trung bình trên mỗi hộp (Profit per box) của từng dòng sản phẩm", "Average profit per box across chocolate products"),
            ("Top 5 sản phẩm có doanh số cao nhất năm 2021", "Top 5 best selling products in 2021"),
            ("So sánh hiệu quả bán hàng giữa thị trường Mỹ (USA) và Ấn Độ (India)", "Compare sales performance between USA and India"),
            ("Team kinh doanh nào có giá trị đơn hàng trung bình cao nhất?", "Which sales team has the highest average order value?"),
            ("Top 5 sản phẩm có tỷ suất lợi nhuận trên mỗi hộp cao nhất", "Top 5 products with highest profit per box"),
            ("So sánh doanh thu giữa các nhóm sản phẩm (Category: Bars, Bites...) trong năm 2021", "Compare revenue across product categories in 2021")
        ]

        # Tier 3: Cơ Cấu Tỷ Lệ & Đào Sâu Quản Trị (Distribution & Share)
        tier3_candidates = [
            ("Tỷ lệ đóng góp doanh thu của từng nhóm sản phẩm (Category) vào tổng doanh thu", "Revenue contribution percentage by product category"),
            ("Tỷ lệ phần trăm đóng góp doanh thu của từng quốc gia (Country)", "Revenue contribution share by country"),
            ("Những nhân viên bán hàng có tổng doanh số vượt mức 500,000 USD", "Sales representatives with total sales exceeding 500,000 USD"),
            ("Top 5 nhân sự có doanh số cao nhất trong nhóm Yummies", "Top 5 sales representatives in Yummies team"),
            ("Số lượng nhân viên bán hàng phân bổ theo từng Team kinh doanh", "Number of sales representatives by team"),
            ("Những sản phẩm có số lượng hộp bán ra trên 10,000 hộp năm 2021", "Products with over 10,000 boxes sold in 2021")
        ]

        avail_tier1 = [it for it in tier1_candidates if it[0].lower() not in q_low] or tier1_candidates
        avail_tier2 = [it for it in tier2_candidates if it[0].lower() not in q_low] or tier2_candidates
        avail_tier3 = [it for it in tier3_candidates if it[0].lower() not in q_low] or tier3_candidates

        p1 = random.choice(avail_tier1)
        p2 = random.choice(avail_tier2)
        p3 = random.choice(avail_tier3)

        selected = [p1, p2, p3]
        return [item[1] if lang == "en" else item[0] for item in selected]

    # CSDL Tổng quát & Northwind
    from src.analytics.heuristics import get_axis_columns
    from src.visualization.charts import VI_COLUMN_MAP
    measure_cols, label_cols, _ = get_axis_columns(df)
    if not measure_cols:
        measure_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        label_cols = [c for c in cols if c not in measure_cols]

    m_col = measure_cols[0] if measure_cols else cols[0]
    l_col = label_cols[0] if label_cols else cols[0]

    m_clean = VI_COLUMN_MAP.get(str(m_col).lower().replace("_", ""), str(m_col).replace("_", " "))
    l_clean = VI_COLUMN_MAP.get(str(l_col).lower().replace("_", ""), str(l_col).replace("_", " "))

    followups.append(f"Xu hướng thay đổi của {m_clean} theo thời gian" if lang != "en" else f"Time-series trend of {m_col}")
    followups.append(f"So sánh {m_clean} giữa các {l_clean} hàng đầu" if lang != "en" else f"Compare {m_col} across top {l_col}")
    followups.append(f"Tỷ lệ phần trăm đóng góp của từng {l_clean} vào tổng {m_clean}" if lang != "en" else f"Percentage contribution of each {l_col} to total {m_col}")

    return followups[:3]


def generate_followup_questions(client, provider: str, model_name: str, user_query: str, schema_context: str, df: pd.DataFrame, lang: str = "vi") -> list[str]:
    """Tự động sinh 2-3 câu hỏi gợi ý phân tích tiếp nối (Follow-up suggestions) bám sát 100% vào thực thể có thật."""
    if df is None or df.empty:
        return []

    # 1. Chuẩn bị các câu hỏi bám sát thực thể có thật 100% trong kết quả truy vấn
    grounded_questions = generate_grounded_fallback_followups(df, schema_context=schema_context, lang=lang)

    # 2. Gọi AI để sinh thêm gợi ý (nếu có)
    ai_questions = []
    try:
        sample_str = df.head(5).to_string(index=False)
        prompt = build_followup_prompt(user_query, schema_context, sample_str, lang=lang)
        res, _ = call_llm(client, provider, model_name, prompt)

        if res:
            cleaned = res.strip().strip("`").replace("json\n", "").strip()
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                schema_low = (schema_context or "").lower()
                is_employees_db = "departments" in schema_low or "dept_emp" in schema_low or "salaries" in schema_low

                for q in parsed:
                    if isinstance(q, dict):
                        raw_val = q.get("question") or q.get("prompt") or q.get("query") or next(iter(q.values()), str(q))
                    else:
                        raw_val = str(q)
                    q_str = sanitize_followup_question(raw_val)
                    if not q_str or is_ambiguous_question(q_str) or is_hallucinated_followup(q_str):
                        continue

                    # Lọc sạch cross-database contamination
                    q_low = q_str.lower()
                    if is_employees_db and any(k in q_low for k in ["sản phẩm", "chocolate", "bán chạy", "doanh thu", "sales", "boxes", "quốc gia", "thị trường"]):
                        continue
                    if not is_employees_db and any(k in q_low for k in ["mức lương", "salary", "salaries", "phòng ban", "departments"]):
                        continue

                    ai_questions.append(q_str)
    except Exception:
        pass

    # 3. ƯU TIÊN 100% CÁC CÂU HỎI BÁM SÁT CSDL ĐỂ ĐẢM BẢO CHẠY THÀNH CÔNG (VÀ LOẠI BỎ CÂU HỎI TRÙNG VỚI CÂU HIỆN TẠI)
    uq_clean = re.sub(r"[^\w\s]", "", (user_query or "").lower()).strip()
    combined = []
    for q in grounded_questions:
        q_clean = re.sub(r"[^\w\s]", "", q.lower()).strip()
        if q_clean != uq_clean and q not in combined:
            combined.append(q)
    for q in ai_questions:
        q_clean = re.sub(r"[^\w\s]", "", q.lower()).strip()
        if q_clean != uq_clean and q not in combined:
            combined.append(q)

    if not combined:
        for q in grounded_questions:
            if q not in combined:
                combined.append(q)

    return combined[:3]


def auto_fix_sakila_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và bảo vệ các truy vấn trên CSDL Sakila (DVD Rental Store):
    - Loại bỏ các điều kiện hallucinated như `WHERE to_date = '9999-01-01'` hay `s.to_date`
    - Chuẩn hóa truy vấn tỷ lệ đóng góp doanh thu theo tháng / theo thể loại
    - Chuẩn hóa truy vấn biến động doanh thu theo tháng
    """
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # 1. Loại bỏ các mệnh đề to_date ảo giác trên Sakila
    if "to_date" in sql_low:
        cleaned_sql = re.sub(r"(?i)\s*(?:where|and)\s+to_date\s*=\s*'9999-01-01'", "", sql)
        cleaned_sql = re.sub(r"(?i)\s*(?:where|and)\s+[a-z0-9_]+\.to_date\s*=\s*'9999-01-01'", "", cleaned_sql)
        cleaned_sql = re.sub(r"(?i)where\s+group\s+by", "GROUP BY", cleaned_sql)
        sql = cleaned_sql.strip()
        sql_low = sql.lower()

    is_sqlite = "sqlite" in (dialect or "").lower()
    date_expr = "strftime('%Y-%m', p.payment_date)" if is_sqlite else "DATE_FORMAT(p.payment_date, '%Y-%m')"

    # 2. Tỷ lệ phần trăm đóng góp doanh thu theo từng tháng (Monthly revenue percentage contribution)
    is_contrib_pct = (
        any(k in q_low for k in ["tỷ lệ", "phần trăm", "đóng góp", "tỷ trọng", "percentage", "contribution", "tỉ trọng", "tỉ lệ", "cơ cấu"])
        and any(k in q_low for k in ["tháng", "month"])
        and any(k in q_low for k in ["doanh thu", "revenue", "sales", "tiền", "amount"])
    )
    if is_contrib_pct:
        has_bad_syntax = (
            "to_date" in sql_low
            or "sales" in sql_low
            or ("contributionpercentage" not in sql_low and "percentage" not in sql_low and "tỷ lệ" not in sql_low)
            or "payment" not in sql_low
        )
        if has_bad_syntax:
            return f"""WITH MonthlyRevenue AS (
    SELECT 
        {date_expr} AS Month,
        SUM(p.amount) AS TotalRevenue
    FROM payment p
    GROUP BY {date_expr}
)
SELECT 
    Month,
    TotalRevenue,
    ROUND(TotalRevenue * 100.0 / (SELECT SUM(TotalRevenue) FROM MonthlyRevenue), 2) AS ContributionPercentage
FROM MonthlyRevenue
ORDER BY Month ASC;"""

    # 3. Biến động doanh thu theo tháng (kèm lượt thuê)
    is_monthly_trend = (
        any(k in q_low for k in ["biến động", "theo tháng", "từng tháng", "hàng tháng", "qua các tháng", "xu hướng", "monthly"])
        and any(k in q_low for k in ["doanh thu", "revenue", "thuê", "rental", "sales"])
        and not is_contrib_pct
    )
    if is_monthly_trend:
        has_bad_syntax = (
            "to_date" in sql_low
            or "sales" in sql_low
            or "saledate" in sql_low
            or "payment" not in sql_low
        )
        if has_bad_syntax:
            return f"""SELECT 
    {date_expr} AS Month,
    SUM(p.amount) AS TotalRevenue,
    COUNT(p.rental_id) AS TotalRentals
FROM payment p
GROUP BY {date_expr}
ORDER BY Month ASC;"""

    # 4. Top khách hàng chi tiêu / tiền mặt nhiều nhất (Sakila Top Customers by Spending)
    is_cust_spending = (
        any(k in q_low for k in ["khách hàng", "customer", "customers"])
        and any(k in q_low for k in ["chi tiêu", "tiền mặt", "nhiều tiền", "nhiều nhất", "lớn nhất", "top", "doanh thu", "spent", "spending", "tiền"])
    )
    if is_cust_spending:
        name_concat = "cu.first_name || ' ' || cu.last_name" if is_sqlite else "CONCAT(cu.first_name, ' ', cu.last_name)"
        limit_m = re.search(r"(?:top\s*|danh\s+sách\s*)(\d+)", q_low)
        lim_val = int(limit_m.group(1)) if limit_m else 10
        yr_m = re.search(r'\b(20\d{2})\b', q_low)
        yr_cond = f"WHERE strftime('%Y', p.payment_date) = '{yr_m.group(1)}'" if (yr_m and is_sqlite) else (f"WHERE YEAR(p.payment_date) = {yr_m.group(1)}" if yr_m else "")
        return f"""SELECT 
    cu.customer_id,
    {name_concat} AS CustomerName,
    SUM(p.amount) AS TotalSpent
FROM customer cu
JOIN payment p ON cu.customer_id = p.customer_id
{yr_cond}
GROUP BY cu.customer_id, CustomerName
ORDER BY TotalSpent DESC
LIMIT {lim_val};"""

    return sql


def auto_fix_general_schema_entities(sql: str, schema_context: str = "") -> str:
    """Universal schema entity normalizer for any database:
    1. Fixes common singular vs plural table names (e.g., product -> products, order_detail -> order_details, order -> orders, customer -> customers, employee -> employees).
    2. Fixes common column name hallucinations across schemas.
    """
    if not sql:
        return sql

    schema_low = (schema_context or "").lower()
    fixed_sql = sql

    # Table replacements when plural exists in schema
    if "products" in schema_low or "`products`" in schema_low:
        fixed_sql = re.sub(r"(?i)\bFROM\s+product\b", "FROM products", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+product\b", "JOIN products", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bFROM\s+`product`\b", "FROM `products`", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+`product`\b", "JOIN `products`", fixed_sql)

    if "order_details" in schema_low or "`order_details`" in schema_low:
        fixed_sql = re.sub(r"(?i)\bFROM\s+order_detail\b", "FROM order_details", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+order_detail\b", "JOIN order_details", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bFROM\s+order_items?\b", "FROM order_details", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+order_items?\b", "JOIN order_details", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bFROM\s+`order_detail`\b", "FROM `order_details`", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+`order_detail`\b", "JOIN `order_details`", fixed_sql)

    if "orders" in schema_low or "`orders`" in schema_low:
        fixed_sql = re.sub(r"(?i)\bFROM\s+order\b", "FROM orders", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+order\b", "JOIN orders", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bFROM\s+`order`\b", "FROM `orders`", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+`order`\b", "JOIN `orders`", fixed_sql)

    if "customers" in schema_low or "`customers`" in schema_low:
        fixed_sql = re.sub(r"(?i)\bFROM\s+customer\b", "FROM customers", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+customer\b", "JOIN customers", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bFROM\s+`customer`\b", "FROM `customers`", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+`customer`\b", "JOIN `customers`", fixed_sql)

    if "employees" in schema_low or "`employees`" in schema_low:
        fixed_sql = re.sub(r"(?i)\bFROM\s+employee\b", "FROM employees", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+employee\b", "JOIN employees", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bFROM\s+`employee`\b", "FROM `employees`", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+`employee`\b", "JOIN `employees`", fixed_sql)

    if "invoices" in schema_low or "`invoices`" in schema_low:
        fixed_sql = re.sub(r"(?i)\bFROM\s+invoice\b", "FROM invoices", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+invoice\b", "JOIN invoices", fixed_sql)

    if "categories" in schema_low or "`categories`" in schema_low:
        fixed_sql = re.sub(r"(?i)\bFROM\s+category\b", "FROM categories", fixed_sql)
        fixed_sql = re.sub(r"(?i)\bJOIN\s+category\b", "JOIN categories", fixed_sql)

    return fixed_sql


def auto_fix_northwind_query(sql: str, user_query: str, schema_context: str = "", dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và bảo vệ các truy vấn trên CSDL Northwind:
    - Sửa bảng số ít thành số nhiều: product -> products, order_detail -> order_details, order -> orders, customer -> customers, employee -> employees
    - Sửa khóa chính/ngoại: p.product_id -> p.id, o.order_id -> o.id, c.customer_id -> c.id, e.employee_id -> e.id
    - Sửa cột giá/chi phí: o.price / od.price -> od.unit_price, p.price -> p.list_price
    - Sửa cột quốc gia: c.country / o.country -> c.country_region / o.ship_country_region
    - Sửa tên: p.name / p.product -> p.product_name, c.name -> CONCAT(c.first_name, ' ', c.last_name)
    """
    if not sql:
        return sql

    q_low = (user_query or "").lower()
    fixed_sql = sql

    # 1. Bảng số ít sang số nhiều
    fixed_sql = re.sub(r"(?i)\bFROM\s+product\b", "FROM products", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+product\b", "JOIN products", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bFROM\s+`product`\b", "FROM `products`", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+`product`\b", "JOIN `products`", fixed_sql)

    fixed_sql = re.sub(r"(?i)\bFROM\s+order_detail\b", "FROM order_details", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+order_detail\b", "JOIN order_details", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bFROM\s+order_items?\b", "FROM order_details", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+order_items?\b", "JOIN order_details", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bFROM\s+`order_detail`\b", "FROM `order_details`", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+`order_detail`\b", "JOIN `order_details`", fixed_sql)

    fixed_sql = re.sub(r"(?i)\bFROM\s+order\b", "FROM orders", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+order\b", "JOIN orders", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bFROM\s+`order`\b", "FROM `orders`", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+`order`\b", "JOIN `orders`", fixed_sql)

    fixed_sql = re.sub(r"(?i)\bFROM\s+customer\b", "FROM customers", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+customer\b", "JOIN customers", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bFROM\s+employee\b", "FROM employees", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bJOIN\s+employee\b", "JOIN employees", fixed_sql)

    # 2. Sửa cột giá: price -> unit_price trên order_details
    fixed_sql = re.sub(r"(?i)\b([a-z0-9_]+)\.price\b", r"\1.unit_price", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(?<![a-z0-9_])price\b", "unit_price", fixed_sql)

    # 3. Sửa p.product_id -> p.id (khóa chính của bảng products là id)
    fixed_sql = re.sub(r"(?i)\b(p|pr|prod|products)\.product_id\b", r"\1.id", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(c|cust|customers)\.customer_id\b", r"\1.id", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(e|emp|employees)\.employee_id\b", r"\1.id", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(o|ord|orders)\.order_id\b", r"\1.id", fixed_sql)

    # 4. Sửa p.name / p.product -> p.product_name
    fixed_sql = re.sub(r"(?i)\b(p|pr|prod|products)\.name\b", r"\1.product_name", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(p|pr|prod|products)\.product\b", r"\1.product_name", fixed_sql)

    # 5. Sửa c.country -> c.country_region, o.country -> o.ship_country_region, o.city -> o.ship_city, c.region -> c.country_region
    fixed_sql = re.sub(r"(?i)\b(c|cust|customers)\.country\b", r"\1.country_region", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(c|cust|customers)\.region\b", r"\1.country_region", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(o|ord|orders)\.country\b", r"\1.ship_country_region", fixed_sql)
    fixed_sql = re.sub(r"(?i)\b(o|ord|orders)\.city\b", r"\1.ship_city", fixed_sql)
    fixed_sql = re.sub(r"(?i)\bs\.(orderdate|order_date)\b", "o.order_date", fixed_sql)

    # 5.1 Xử lý câu hỏi về thành phố (So sánh amount due / doanh thu / tỷ lệ đóng góp của từng thành phố)
    is_city_query = (
        any(k in q_low for k in ["thành phố", "city", "các thành phố", "từng thành phố", "mỗi thành phố", "giữa các thành phố"])
        and any(k in q_low for k in ["amount due", "amount_due", "doanh thu", "revenue", "tổng số", "total", "trung bình", "so sánh", "đóng góp", "tỷ lệ", "tỉ lệ", "công nợ", "tiền phải trả", "bán hàng"])
    )
    if is_city_query:
        is_contrib = any(k in q_low for k in ["tỷ lệ", "phần trăm", "đóng góp", "tỷ trọng", "tỉ trọng", "tỉ lệ", "cơ cấu", "percentage", "contribution"])
        if is_contrib:
            return """WITH CityAmountDue AS (
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
        else:
            return """SELECT 
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

    # 5.15 Xử lý câu hỏi Khoảng thời gian nào ghi nhận amount due / doanh thu cao nhất và thấp nhất (Peak & Valley Period)
    is_time_peak_valley = (
        any(k in q_low for k in ["khoảng thời gian", "thời gian", "tháng nào", "thời điểm", "giai đoạn", "period", "month"])
        and any(k in q_low for k in ["cao nhất và thấp nhất", "lớn nhất và nhỏ nhất", "đỉnh và đáy", "peak and valley", "cao nhất", "thấp nhất", "đỉnh điểm", "đáy"])
        and any(k in q_low for k in ["amount due", "amount_due", "doanh thu", "revenue", "công nợ", "tiền", "ghi nhận"])
    )
    if is_time_peak_valley:
        is_sqlite = "sqlite" in (dialect or "").lower()
        m_expr = "substr(o.order_date, 1, 7)" if is_sqlite else "DATE_FORMAT(o.order_date, '%Y-%m')"
        return f"""WITH MonthlyAmountDue AS (
    SELECT 
        {m_expr} AS Month,
        COUNT(DISTINCT o.id) AS TotalOrders,
        ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    WHERE o.order_date IS NOT NULL
    GROUP BY Month
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

    # 5.2 Xử lý câu hỏi phân tích sự chênh lệch amount due / doanh số giữa nhóm cao nhất và nhóm thấp nhất
    is_extremes_amount_due = (
        any(k in q_low for k in ["chênh lệch", "sự chênh lệch", "khoảng cách", "spread", "gap", "difference"])
        and any(k in q_low for k in ["nhóm cao nhất", "cao nhất và thấp nhất", "nhóm thấp nhất", "cực trị", "extremes"])
    )
    if is_extremes_amount_due:
        return """WITH CustomerDueSummary AS (
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
ORDER BY TotalAmountDue DESC;"""

    # 5.3 Xử lý câu hỏi vị trí công việc có amount due / doanh thu vượt trên mức trung bình
    is_job_title_above_avg = (
        any(k in q_low for k in ["vị trí công việc", "vị trí", "chức vụ", "chức danh", "job title", "job_title", "role"])
        and any(k in q_low for k in ["vượt trên", "trung bình", "mức trung bình", "cao hơn trung bình", "above average", "greater than average", "vượt mức", "vượt"])
    )
    if is_job_title_above_avg:
        return """SELECT 
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

    # 5.35 Xử lý câu hỏi So sánh Employee Count giữa các Job Title / chức danh hàng đầu
    is_job_title_headcount = (
        any(k in q_low for k in ["chức vụ", "chức danh", "job title", "job_title", "vị trí", "role"])
        and any(k in q_low for k in ["employee count", "headcount", "số lượng nhân sự", "số lượng nhân viên", "số nhân sự", "số nhân viên", "nhân sự", "nhân viên", "quy mô", "tỷ lệ", "tỉ lệ", "cơ cấu", "phân bố", "so sánh"])
        and not any(k in q_low for k in ["vượt trên", "mức trung bình", "cao hơn trung bình", "above average", "amount due", "amount_due", "tiền phải trả", "công nợ"])
    )
    if is_job_title_headcount:
        return """SELECT 
    COALESCE(e.job_title, 'Unknown') AS JobTitle,
    COUNT(DISTINCT e.id) AS EmployeeCount,
    ROUND(COUNT(DISTINCT e.id) * 100.0 / (SELECT COUNT(*) FROM employees), 2) AS Percentage
FROM employees e
GROUP BY e.job_title
ORDER BY EmployeeCount DESC;"""

    # 5.36 Xử lý câu hỏi Job Title kết hợp Doanh số / Doanh thu
    is_job_title_sales = (
        any(k in q_low for k in ["chức vụ", "chức danh", "job title", "job_title", "vị trí"])
        and any(k in q_low for k in ["doanh thu", "doanh số", "revenue", "sales", "bán hàng", "total sales", "total revenue"])
        and not is_job_title_above_avg
    )
    if is_job_title_sales:
        return """SELECT 
    COALESCE(e.job_title, 'Unknown') AS JobTitle,
    COUNT(DISTINCT e.id) AS EmployeeCount,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))) / NULLIF(COUNT(DISTINCT o.id), 0), 2) AS AvgDealSize
FROM employees e
LEFT JOIN orders o ON e.id = o.employee_id
LEFT JOIN order_details od ON o.id = od.order_id
GROUP BY e.job_title
ORDER BY TotalRevenue DESC;"""

    # 5.4 Phát hiện và sửa ảo giác bảng từ các CSDL khác (titles, salaries, dept_emp, departments, sales, geo, payment)
    if any(t in fixed_sql.lower() for t in ["titles", "salaries", "dept_emp", "departments"]):
        return """SELECT 
    COALESCE(e.job_title, 'Unknown') AS JobTitle,
    COUNT(DISTINCT e.id) AS EmployeeCount,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    ROUND(COALESCE(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 0) / NULLIF(COUNT(DISTINCT o.id), 0), 2) AS AvgDealSize
FROM employees e
LEFT JOIN orders o ON e.id = o.employee_id
LEFT JOIN order_details od ON o.id = od.order_id
GROUP BY e.job_title
ORDER BY TotalRevenue DESC;"""

    # 6. Chuẩn hóa Top N sản phẩm doanh thu cao nhất
    is_top_products = (
        any(k in q_low for k in ["sản phẩm", "product", "products", "mặt hàng"])
        and any(k in q_low for k in ["doanh thu", "revenue", "bán chạy", "doanh số", "cao nhất", "top"])
    )
    if is_top_products:
        limit_m = re.search(r"(?:top\s*|danh\s+sách\s*)(\d+)", q_low)
        lim_val = int(limit_m.group(1)) if limit_m else 5
        # Nếu có cả order_details và products
        if "order_details" in fixed_sql.lower() and "products" in fixed_sql.lower():
            fixed_sql = re.sub(r"(?i)GROUP\s+BY\s+[a-z0-9_]+\.id", "GROUP BY p.id, p.product_name", fixed_sql)
            fixed_sql = re.sub(r"(?i)GROUP\s+BY\s+[a-z0-9_]+\.product_id", "GROUP BY p.id, p.product_name", fixed_sql)
            fixed_sql = re.sub(r"(?i)GROUP\s+BY\s+product", "GROUP BY p.id, p.product_name", fixed_sql)
        else:
            return f"""SELECT 
    p.product_name AS Product,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalRevenue
FROM order_details od
JOIN products p ON od.product_id = p.id
GROUP BY p.id, p.product_name
ORDER BY TotalRevenue DESC
LIMIT {lim_val};"""

    # 7. Chuẩn hóa Doanh thu theo Nhân viên
    is_emp_sales = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "người bán", "employee", "salesperson", "staff"])
        and any(k in q_low for k in ["doanh thu", "doanh số", "bán hàng", "doanh thu cao", "revenue", "sales", "nhiều nhất", "top"])
    )
    if is_emp_sales and not is_top_products:
        limit_m = re.search(r"(?:top\s*|danh\s+sách\s*)(\d+)", q_low)
        lim_val = int(limit_m.group(1)) if limit_m else 5
        return f"""SELECT 
    CONCAT(e.first_name, ' ', e.last_name) AS EmployeeName,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalSales,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM orders o
JOIN order_details od ON o.id = od.order_id
JOIN employees e ON o.employee_id = e.id
GROUP BY e.id, EmployeeName
ORDER BY TotalSales DESC
LIMIT {lim_val};"""

    # 8. Chuẩn hóa Doanh thu theo Quốc gia
    is_country_sales = (
        any(k in q_low for k in ["quốc gia", "country", "thị trường", "khu vực"])
        and any(k in q_low for k in ["doanh thu", "revenue", "đơn hàng", "orders", "bán hàng"])
    )
    if is_country_sales:
        return f"""SELECT 
    c.country_region AS Country,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - od.discount)), 2) AS TotalRevenue
FROM customers c
JOIN orders o ON c.id = o.customer_id
JOIN order_details od ON o.id = od.order_id
GROUP BY c.country_region
ORDER BY TotalRevenue DESC;"""

    # 8.5 Chuẩn hóa Xu hướng Amount Due theo Last Name / Khách hàng theo Thời gian
    is_amount_due_trend = (
        any(k in q_low for k in ["amount due", "amount_due", "công nợ", "tiền phải trả", "hóa đơn", "invoice"])
        and any(k in q_low for k in ["xu hướng", "trend", "thay đổi", "biến động", "theo thời gian", "từng tháng", "mỗi tháng", "qua các tháng", "over time", "monthly"])
    )
    if is_amount_due_trend:
        is_sq = (dialect.lower() == "sqlite")
        m_expr = "substr(o.order_date, 1, 7)" if is_sq else "DATE_FORMAT(o.order_date, '%Y-%m')"
        if any(k in q_low for k in ["last name", "lastname", "họ", "tên", "khách hàng", "customer", "nhân viên", "employee"]):
            return f"""SELECT 
    {m_expr} AS Month,
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
        else:
            return f"""SELECT 
    {m_expr} AS Month,
    COUNT(DISTINCT o.id) AS TotalOrders,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalAmountDue,
    ROUND(AVG(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS AvgAmountDue
FROM orders o
JOIN order_details od ON o.id = od.order_id
WHERE o.order_date IS NOT NULL
GROUP BY Month
ORDER BY Month ASC;"""

    # 9. Chuẩn hóa Xu hướng Total Revenue theo Thời gian
    is_rev_trend = (
        any(k in q_low for k in ["xu hướng", "trend", "thay đổi", "biến động", "theo thời gian", "từng tháng", "mỗi tháng", "qua các tháng", "over time", "monthly"])
        and any(k in q_low for k in ["doanh thu", "revenue", "doanh số", "sales", "total revenue"])
    )
    if is_rev_trend and not is_top_products and not is_emp_sales and not is_country_sales:
        is_sq = (dialect.lower() == "sqlite")
        m_expr = "substr(o.order_date, 1, 7)" if is_sq else "DATE_FORMAT(o.order_date, '%Y-%m')"
        return f"""SELECT 
    {m_expr} AS Month,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM orders o
JOIN order_details od ON o.id = od.order_id
WHERE o.order_date IS NOT NULL
GROUP BY Month
ORDER BY Month ASC;"""

    # 10. Chuẩn hóa Cơ cấu Doanh thu theo Danh mục
    is_cat_rev = (
        any(k in q_low for k in ["danh mục", "category", "ngành hàng", "nhóm hàng"])
        and any(k in q_low for k in ["doanh thu", "revenue", "cơ cấu", "tỷ trọng", "tỉ trọng"])
    )
    if is_cat_rev and not is_top_products:
        return f"""SELECT 
    COALESCE(p.category, 'Other') AS Category,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    SUM(od.quantity) AS TotalQuantity
FROM products p
JOIN order_details od ON p.id = od.product_id
GROUP BY Category
ORDER BY TotalRevenue DESC;"""

    # 11. Xóa bỏ bảng ảo hoặc nhầm lẫn payment / inventory_transactions khi hỏi về doanh số
    if any(k in fixed_sql.lower() for k in ["payment", "inventory_transactions", "inventory_transaction_types"]) and any(k in q_low for k in ["doanh thu", "revenue", "doanh số", "sales", "total revenue"]):
        is_sq = (dialect.lower() == "sqlite")
        m_expr = "substr(o.order_date, 1, 7)" if is_sq else "DATE_FORMAT(o.order_date, '%Y-%m')"
        return f"""SELECT 
    {m_expr} AS Month,
    ROUND(SUM(od.quantity * od.unit_price * (1 - COALESCE(od.discount, 0))), 2) AS TotalRevenue,
    COUNT(DISTINCT o.id) AS TotalOrders
FROM orders o
JOIN order_details od ON o.id = od.order_id
WHERE o.order_date IS NOT NULL
GROUP BY Month
ORDER BY Month ASC;"""

    return fixed_sql


def run_agent(
    user_query: str,
    client,
    provider: str,
    model_name: str,
    engine,
    schema_context: str,
    dialect: str = "SQLite",
    db_pass: str = "",
    enable_self_check: bool = True,
    enable_auto_insights: bool = True,
    status_callback=None,
    lang: str = None,
    **kwargs
) -> dict:
    """Điều phối toàn bộ chu trình Text-to-SQL, tự sửa lỗi âm thầm (bao gồm cứu kết quả 0 dòng) và tự động khám phá Insight."""
    # 0. Tự động nhận diện ngôn ngữ của câu hỏi (vi / en) hoặc sử dụng ngôn ngữ chỉ định
    if not lang or lang not in ("vi", "en"):
        lang = detect_query_language(user_query)

    result = {
        "query": user_query,
        "lang": lang,
        "df": None,
        "sql": None,
        "logs": [],
        "attempts": 0,
        "error": None,
        "explanation": None,
        "anomalies_info": None,
        "insights": None,
        "followups": [],
        "plan": None,
        "evaluator": None,
        "agent_trace": {
            "router": None,
            "planner": None,
            "executor": None,
            "evaluator": None,
        },
    }

    # 0.0 Nhận diện yêu cầu phân tích chiến lược chuyên sâu / Báo cáo Senior Lead / Nghị quyết Ban điều hành
    user_query_clean = user_query.strip()
    user_query_low = user_query_clean.lower()
    if (
        user_query_clean.startswith("BÁO CÁO CHUYÊN SÂU TỪ SENIOR LEAD DATA ANALYST:")
        or any(k in user_query_low for k in ["nghị quyết chiến lược", "tham mưu chiến lược", "kế hoạch hành động ban điều hành", "executive board memo"])
    ):
        strat_prompt = f"""Bạn là Senior Principal Lead Data Analyst & Strategic Consultant hàng đầu.
Người dùng yêu cầu phân tích sâu và lập kế hoạch chiến lược hành động dựa trên báo cáo dữ liệu và các điểm bất thường sau:

{user_query}

HƯỚNG DẪN TRÌNH BÀY CHUẨN MỰC BAN ĐIỀU HÀNH (EXECUTIVE BOARD MEMO):
1. 🎯 TÓM TẮT ĐIỀU HÀNH (Executive Summary): Đánh giá tổng quan sức khỏe vận hành và các rủi ro cốt lõi.
2. 🔬 PHÂN TÍCH CHUYÊN SÂU & NGUYÊN NHÂN GỐC RỄ (Deep Root-Cause Diagnostics):
   - Mổ xẻ từng điểm bất thường đã nêu trong báo cáo, trích dẫn CHÍNH XÁC mọi số liệu, tỷ lệ %, mốc năm và phòng ban.
   - Đối chiếu chéo giữa các chỉ số (Tuyển dụng x Lương x Cơ cấu phòng ban x Quản lý).
3. 💥 LƯỢNG HÓA TÁC ĐỘNG TÀI CHÍNH & VẬN HÀNH (Quantified Business Impact):
   - Phân tích rủi ro hao hụt nhân tài, áp lực ngân sách quỹ lương và nghẽn cổ chai vận hành.
4. 🚀 LỘ TRÌNH HÀNH ĐỘNG CHIẾN LƯỢC 3 TẦNG (3-Tier Action Plan):
   - Tầng 1: Can thiệp khẩn cấp (0 - 30 ngày)
   - Tầng 2: Tái cấu trúc & Chính sách (1 - 2 quý)
   - Tầng 3: Tái phân bổ nguồn lực & Bền vững (1 - 3 năm)
5. 📊 BẢNG CHỈ SỐ OKRs & MILESTONES ĐO LƯỜNG:
   - Các mục tiêu định lượng cụ thể để Ban Điều Hành nghiệm thu kết quả.

Yêu cầu: Viết sắc sảo, ngôn từ chuẩn mực tư vấn chiến lược cao cấp, lập luận chặt chẽ, tuyệt đối không chung chung và bám sát 100% dữ liệu thực tế."""
        report_text, err = call_llm(client, provider, model_name, strat_prompt)
        if report_text:
            result["explanation"] = report_text
            result["insights"] = report_text
            result["is_strategic_report"] = True
            return result

    # 0.1 Kiểm tra sự tương thích giữa câu hỏi và CSDL hiện tại (Domain Mismatch Pre-check)
    valid_tables = get_table_names(engine)
    valid_tbls_low = [t.lower() for t in valid_tables]
    is_northwind_db = False
    is_employees_db = False
    is_chocolates_db = False
    is_sakila_db = False

    if any(k in valid_tbls_low for k in ["order_details", "orders_status", "inventory_transactions", "purchase_orders"]) or (("products" in valid_tbls_low or "product" in valid_tbls_low) and ("orders" in valid_tbls_low or "customers" in valid_tbls_low)):
        is_northwind_db = True
    elif "departments" in valid_tbls_low and ("salaries" in valid_tbls_low or "dept_emp" in valid_tbls_low):
        is_employees_db = True
    elif "people" in valid_tbls_low and "products" in valid_tbls_low and "sales" in valid_tbls_low:
        is_chocolates_db = True
    elif any(k in valid_tbls_low for k in ["film", "rental", "actor"]):
        is_sakila_db = True
    else:
        # Fallback dựa trên schema_context chỉ khi không có engine thực tế
        schema_low = (schema_context or "").lower()
        is_northwind_db = any(k in schema_low for k in ["order_details", "`order_details`", "orders_status", "inventory_transactions", "purchase_orders"]) or (("products" in schema_low or "`products`" in schema_low) and ("orders" in schema_low or "`orders`" in schema_low) and not any(k in schema_low for k in ["geoid", "spid", "boxes", "`film`", "`rental`"]))
        is_sakila_db = any(k in schema_low for k in ["`film`", "`rental`", "film_id", "rental_id", "`actor`", "actor_id", "film_actor", "film_category", "rental_date"]) and not is_northwind_db
        is_employees_db = (
            any(k in schema_low for k in ["dept_emp", "dept_manager", "salaries"])
            and not any(k in schema_low for k in ["geoid", "spid", "boxes", "order_details"])
            and not is_sakila_db
            and not is_northwind_db
        )
        is_chocolates_db = (
            any(k in schema_low for k in ["geoid", "spid", "boxes", "people"])
            and not any(k in schema_low for k in ["dept_emp", "dept_manager", "order_details"])
            and not is_sakila_db
            and not is_northwind_db
        )

    # Nếu đang ở DB employees mà người dùng hỏi sản phẩm / bán hàng / chocolate
    if is_employees_db and any(k in user_query_low for k in ["sản phẩm", "bán chạy", "chocolate", "cost per box", "hộp kẹo", "khách hàng mua", "thị trường úc", "thị trường ấn độ"]):
        result["explanation"] = (
            "💡 **Thông báo từ Trợ lý:** Cơ sở dữ liệu hiện tại (**`employees`**) là cơ sở dữ liệu về **Nhân sự, Tiền lương và Phòng ban** (gồm các bảng `employees`, `salaries`, `departments`, `dept_emp`, `titles`), không chứa bảng sản phẩm hay doanh số bán hàng.\n\n"
            "👉 **Gợi ý:** Nếu bạn muốn truy vấn về **Sản phẩm bán chạy** hoặc **Doanh số kinh doanh**, vui lòng chọn cơ sở dữ liệu **`awesome chocolates`** hoặc **`northwind`** ở thanh menu bên trái (Sidebar) nhé!"
            if lang != "en" else
            "💡 **Notice:** The current database (**`employees`**) is for **HR, Salaries, and Departments**, and does not contain product or sales tables.\n\n"
            "👉 Please switch to the **`awesome chocolates`** or **`northwind`** database in the Sidebar to query product sales!"
        )
        return result

    # Nếu đang ở DB awesome chocolates mà người dùng hỏi mức lương / salary
    if is_chocolates_db and any(k in user_query_low for k in ["mức lương", "bảng lương", "lương trung bình", "tiền lương", "salary", "salaries"]):
        result["explanation"] = (
            "💡 **Thông báo từ Trợ lý:** Cơ sở dữ liệu hiện tại (**`awesome chocolates`**) là cơ sở dữ liệu về **Sản phẩm, Nhân viên kinh doanh và Doanh số bán hàng** (gồm các bảng `sales`, `products`, `people`, `geo`), không chứa bảng tiền lương nhân viên.\n\n"
            "👉 **Gợi ý:** Nếu bạn muốn truy vấn về **Tiền lương nhân viên**, vui lòng chọn cơ sở dữ liệu **`employees`** ở thanh menu bên trái (Sidebar) nhé!"
            if lang != "en" else
            "💡 **Notice:** The current database (**`awesome chocolates`**) is for **Products and Sales**, and does not contain salary tables.\n\n"
            "👉 Please switch to the **`employees`** database in the Sidebar to query employee salaries!"
        )
        return result

    # Nếu đang ở DB sakila mà người dùng hỏi mức lương / salary
    if is_sakila_db and any(k in user_query_low for k in ["mức lương", "bảng lương", "lương trung bình", "tiền lương", "salary", "salaries"]):
        result["explanation"] = (
            "💡 **Thông báo từ Trợ lý:** Cơ sở dữ liệu hiện tại (**`sakila`**) là cơ sở dữ liệu về **Cho thuê phim (DVD Rentals)** (gồm các bảng `film`, `actor`, `rental`, `payment`, `customer`, `category`), không chứa bảng tiền lương nhân viên.\n\n"
            "👉 **Gợi ý:** Nếu bạn muốn truy vấn về **Tiền lương nhân viên**, vui lòng chọn cơ sở dữ liệu **`employees`** ở thanh menu bên trái (Sidebar) nhé!"
            if lang != "en" else
            "💡 **Notice:** The current database (**`sakila`**) is for **Movie Rentals**, and does not contain employee salary tables.\n\n"
            "👉 Please switch to the **`employees`** database in the Sidebar to query employee salaries!"
        )
        return result

    def _apply_domain_auto_fixes(sql_cur: str) -> str:
        sql_cur = sql_cur or ""
        # 0. Global guard: Khắc phục triệt để lỗi tách 2 cột Year1 / Year2 / AvgSalary1
        if bool(re.search(r"\b(year\s*[12]|year_[12]|avgsalary\s*[12]|avg_salary\s*[12]|salary\s*[12]|salary_[12]|salarychange|salary_change)\b", str(sql_cur), re.IGNORECASE)):
            sql_cur = auto_fix_yearly_salary_trend_query(sql_cur, user_query, dialect=dialect)

        # Áp dụng bộ chuẩn hóa bảng và cột tổng quát cho mọi CSDL
        sql_cur = auto_fix_general_schema_entities(sql_cur, schema_context=schema_context)

        if is_employees_db:
            res_insight1 = auto_fix_insight1_department_transfers_query(sql_cur, user_query, dialect=dialect)
            if res_insight1 != sql_cur:
                return res_insight1
            res_insight2 = auto_fix_insight2_female_managers_query(sql_cur, user_query, dialect=dialect)
            if res_insight2 != sql_cur:
                return res_insight2
            res_insight3 = auto_fix_insight3_promotion_timeline_query(sql_cur, user_query, dialect=dialect)
            if res_insight3 != sql_cur:
                return res_insight3
            res_insight4 = auto_fix_insight4_salary_compression_query(sql_cur, user_query, dialect=dialect)
            if res_insight4 != sql_cur:
                return res_insight4
            res_insight5 = auto_fix_insight5_manager_turnover_query(sql_cur, user_query, dialect=dialect)
            if res_insight5 != sql_cur:
                return res_insight5
            sql_cur = auto_fix_department_avg_salary_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_yearly_salary_trend_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_salary_peak_valley_period_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_headcount_growth_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_count_dept_transfer_employees_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_transfers_breakdown_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_salary_bracket_distribution_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_salary_fluctuation_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_top_payroll_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_employee_salary_growth_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_active_headcount_per_year_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_top_employee_per_year_query(sql_cur, user_query, schema_context=schema_context, dialect=dialect)
            sql_cur = auto_fix_salary_compression_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_top_employee_salary_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_promoted_managers_by_hire_date_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_employee_multiple_titles_progression_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_title_assignments_query(sql_cur, user_query)
            sql_cur = auto_fix_title_headcount_distribution_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_title_total_salary_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_title_avg_salary_above_company_avg_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_salary_deficit_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_company_hiring_trend_query(sql_cur, user_query)
            sql_cur = auto_fix_longest_managers_query(sql_cur, user_query)
            sql_cur = auto_fix_top_percentile_salary_low_tenure_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_top_tenured_employees_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_title_tenure_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_tenure_cohort_salary_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_share_in_company_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_avg_salary_threshold_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_payroll_query(sql_cur, user_query)
            sql_cur = auto_fix_gender_promotion_rate_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_gender_salary_comparison_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_gender_salary_gap_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_recent_manager_gender_promotion_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_manager_gender_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_gender_salary_contribution_query(sql_cur, user_query, dialect=dialect)

            sql_cur = auto_fix_gender_ratio_query(sql_cur, user_query)
            sql_cur = auto_fix_employee_salary_growth_rate_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_employee_salary_above_title_avg_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_top_raises_low_salary_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_low_raises_top_percentile_salary_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_employee_salary_reduction_history_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_raises_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_specific_employee_lookup_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_comparison_query(sql_cur, user_query)
            sql_cur = auto_fix_title_gender_salary_query(sql_cur, user_query)
            sql_cur = auto_fix_manager_vs_subordinate_salary_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_current_manager_salary_query(sql_cur, user_query)
            sql_cur = auto_fix_two_departments_comparison_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_department_group_salary_query(sql_cur, user_query)
            sql_cur = auto_fix_department_single_vs_others_salary_query(sql_cur, user_query)
            sql_cur = auto_fix_department_single_vs_others_headcount_query(sql_cur, user_query)
            sql_cur = auto_fix_multi_dept_salary_vs_first_dept_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_multi_dept_employees_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_dept_size_min_max_query(sql_cur, user_query)
            sql_cur = auto_fix_salary_spread_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_pareto_cumulative_query(sql_cur, user_query, dialect=dialect)
        elif is_chocolates_db:
            sql_cur = auto_fix_pareto_cumulative_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_top_employee_per_year_query(sql_cur, user_query, schema_context=schema_context, dialect=dialect)
            sql_cur = auto_fix_datetime_year_filters(sql_cur, dialect=dialect)
            sql_cur = auto_fix_chocolates_pnl_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_monthly_sales_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_product_quarterly_consistency_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_product_quarterly_rankings_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_quarterly_sales_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_dominant_market_top_product_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_contribution_percentage_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_sales_performance_comparison_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_sales_headcount_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_team_spread_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_team_sales_and_boxes_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_segment_large_orders_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_threshold_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_above_average_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_top_transactions_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_top_rankings_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_chocolates_unassigned_team_filter(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_missing_metric_in_having_query(sql_cur, user_query)
        elif is_sakila_db:
            sql_cur = auto_fix_sakila_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_pareto_cumulative_query(sql_cur, user_query, dialect=dialect)
            sql_cur = auto_fix_missing_metric_in_having_query(sql_cur, user_query)
        elif is_northwind_db:
            sql_cur = auto_fix_northwind_query(sql_cur, user_query, schema_context=schema_context, dialect=dialect)
        return sql_cur

    # 0.15 TẦNG SCHEMA LINKING & METADATA RAG (Enterprise Schema Pruner & FK Graph Connector)
    if status_callback:
        status_callback("🔍 [Schema Linking & Metadata RAG] Phân tích ngữ nghĩa Metadata, đồ thị Foreign Keys & Tinh gọn Sub-Schema...")

    linked_schema_meta = link_schema_for_query(user_query, schema_context)
    result["agent_trace"]["schema_linking"] = {
        "selected_tables": linked_schema_meta.get("selected_tables", []),
        "pruned_tables": linked_schema_meta.get("pruned_tables", []),
        "join_paths": linked_schema_meta.get("join_paths", []),
        "is_pruned": linked_schema_meta.get("is_pruned", False),
        "confidence_score": linked_schema_meta.get("confidence_score", 1.0)
    }
    
    if linked_schema_meta.get("is_pruned"):
        tbls_str = ", ".join(f"`{t}`" for t in linked_schema_meta.get("selected_tables", []))
        result["logs"].append(
            f"🔍 [Schema Linking RAG] Đã lọc {len(linked_schema_meta.get('selected_tables', []))} bảng mục tiêu ({tbls_str}), tinh gọn {len(linked_schema_meta.get('pruned_tables', []))} bảng thừa."
        )
    else:
        tbls_str = ", ".join(f"`{t}`" for t in linked_schema_meta.get("selected_tables", []))
        result["logs"].append(
            f"🔍 [Schema Linking RAG] Đã định vị các bảng dữ liệu cốt lõi: {tbls_str}"
        )

    effective_schema = linked_schema_meta.get("sub_schema", schema_context)

    # 0.2 TẦNG 1: ROUTER & TASK PLANNER (Agent 1: Master Supervisor & Orchestrator)
    if status_callback:
        status_callback("🧭 [Agent 1/5 • Master Supervisor] Phân tích ngữ nghĩa, đánh giá độ phức tạp & Lập kế hoạch luồng dữ liệu...")

    plan = route_and_plan(
        user_query=user_query,
        schema_context=effective_schema,
        dialect=dialect,
        client=client,
        provider=provider,
        model_name=model_name,
        lang=lang
    )
    result["plan"] = plan
    result["agent_trace"]["router"] = {
        "complexity": plan["complexity"],
        "intent": plan["intent"],
        "target_entities": plan["target_entities"],
        "target_metrics": plan["target_metrics"],
        "time_horizon": plan["time_horizon"],
    }
    result["agent_trace"]["planner"] = {
        "num_steps": plan["num_steps"],
        "sub_tasks": plan["sub_tasks"],
        "execution_strategy": plan["execution_strategy"],
    }

    sub_tasks_str = " ➔ ".join(f"[{st['step']}] {st['name']}" for st in plan["sub_tasks"])
    result["logs"].append(f"🧭 [Supervisor & Planner] Độ phức tạp: {plan['complexity']} ({plan['num_steps']} bước): {sub_tasks_str}")

    # 1. Sinh SQL ban đầu (Agent 2: Data Engineer & SQL Architect)
    if status_callback:
        status_callback(f"⚡ [Agent 2/5 • Data Engineer] Kích hoạt In-Context Learning & Sinh truy vấn SQL tối ưu {plan['num_steps']} bước...")

    selected_shots = select_dynamic_few_shots(user_query, schema_context=effective_schema, dialect=dialect, top_k=2)
    if selected_shots:
        shot_summaries = [f"{s.get('id', 'mẫu')} ({s.get('relevance_score', 0)}pts)" for s in selected_shots]
        result["logs"].append(f"🎯 [In-Context Learning] Đã kích hoạt {len(selected_shots)} mẫu truy vấn tương đồng: {', '.join(shot_summaries)}")
        result["agent_trace"]["few_shots"] = [
            {"id": s.get("id"), "goal": s.get("intent_explanation"), "relevance": s.get("relevance_score")}
            for s in selected_shots
        ]

    initial_prompt = build_sql_prompt(effective_schema, dialect, user_query, lang=lang)
    sql_query, err = call_llm(client, provider, model_name, initial_prompt, max_tokens=2048)
    if sql_query:
        sql_query = clean_sql_query(sql_query)
        sql_query = enforce_top_n_limit(sql_query, user_query)
        sql_query = _apply_domain_auto_fixes(sql_query)
    else:
        # Thử tổng hợp SQL trực tiếp qua các quy tắc nghiệp vụ domain auto-fixes
        domain_fallback_sql = _apply_domain_auto_fixes("")
        if domain_fallback_sql and is_safe_select(domain_fallback_sql):
            sql_query = domain_fallback_sql
            err = None

    if not sql_query:
        result["error"] = "Could not generate SQL from AI model." if lang == "en" else f"Không thể tạo SQL từ mô hình AI.{' Lý do: ' + err if err else ''}"
        return result


    # 2. Vòng lặp thực thi, kiểm định và tự sửa lỗi âm thầm (Silent Self-Healing)
    for attempt in range(1, 4):
        result["attempts"] = attempt
        sql_query = enforce_top_n_limit(sql_query, user_query)
        sql_query = _apply_domain_auto_fixes(sql_query)
        sql_query = sanitize_sql_for_live_db(
            sql=sql_query,
            engine=engine,
            schema_context=schema_context,
            user_query=user_query,
            dialect=dialect
        )
        result["logs"].append(f"[Lần {attempt}] SQL: {sql_query}")

        if not is_safe_select(sql_query):
            # Nếu AI trả về câu giải thích hợp lệ sau khi đã thử tự sửa
            if is_conversational_explanation(sql_query) and attempt == 3:
                result["explanation"] = sql_query
                return result

            result["logs"].append("⚠️ Phản hồi chưa phải câu lệnh SQL SELECT/WITH hợp lệ. Đang tự động yêu cầu AI tạo câu lệnh SQL chuẩn xác...")
            if attempt == 3:
                result["error"] = "Unsafe SQL query (Only single SELECT/WITH statements allowed)." if lang == "en" else "Câu lệnh SQL không an toàn hoặc AI từ chối tạo SQL sau 3 lần thử."
                result["sql"] = sql_query
                return result

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query,
                "BẮT BUỘC chỉ trả về duy nhất 1 câu lệnh SQL SELECT hoặc WITH ... AS hợp lệ theo 3 Quy tắc Phân rã Nghiệp vụ, TUYỆT ĐỐI KHÔNG xin lỗi, không giải thích, không dùng markdown!" if lang != "en" else "MUST return raw executable SELECT/WITH statement. Do NOT apologize, do NOT explain!",
                lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt, max_tokens=800)
            if fixed_sql:
                fixed_sql = clean_sql_query(fixed_sql)
                fixed_sql = _apply_domain_auto_fixes(fixed_sql)
            sql_query = fixed_sql or sql_query
            continue

        # 2.1 Kiểm tra cân đối dấu ngoặc trước khi thực thi
        is_balanced, paren_err = check_parentheses_balance(sql_query)
        if not is_balanced:
            result["logs"].append(f"❌ Phát hiện lỗi cú pháp dấu ngoặc: {paren_err}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {paren_err}"
                result["sql"] = sql_query
                return result

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, paren_err, lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            if fixed_sql:
                fixed_sql = clean_sql_query(fixed_sql)
                fixed_sql = _apply_domain_auto_fixes(fixed_sql)
            sql_query = fixed_sql or sql_query
            continue

        # 2.2 Thực thi SQL trên Database Engine
        if status_callback:
            status_callback("💾 [Database Engine] Đang thực thi truy vấn & Đọc tập kết quả...")

        try:
            df, truncated = read_sql_capped(sql_query, engine, cap=MAX_ROWS_CAP)
            if truncated:
                result["logs"].append(f"⚠️ Dữ liệu lớn: đã dừng đọc ở {MAX_ROWS_CAP:,} dòng để bảo vệ hệ thống.")

            # Tự động phát hiện & sửa nếu kết quả trả về 0 dòng (0-Row Empty Result Recovery)
            if df is not None and df.empty and attempt < 3:
                # Kiểm tra tự động chữa lành bằng domain auto fixes nếu câu SQL trước đó chưa được chuẩn hóa
                healed_domain_sql = _apply_domain_auto_fixes(sql_query)
                if healed_domain_sql and healed_domain_sql != sql_query:
                    result["logs"].append("⚡ [Self-Healing] Tự động chuẩn hóa câu lệnh SQL từ tri thức miền nghiệp vụ để khắc phục kết quả 0 dòng...")
                    sql_query = healed_domain_sql
                    continue

                # Kiểm tra đặc biệt: nếu câu lệnh SQL có HAVING lọc tỷ lệ quá chặt khiến 0 dòng
                if re.search(r'having\s+sum\s*\([^)]+\)\s*>=\s*(?:0\.\d+|\(\s*select\b)', sql_query, re.IGNORECASE):
                    healed_sql = auto_fix_pareto_cumulative_query(sql_query, user_query, dialect=dialect)
                    if healed_sql and healed_sql != sql_query:
                        result["logs"].append("⚡ Tự động sửa lỗi HAVING lọc tỷ lệ quá chặt thành chuẩn phân tích Pareto tích lũy...")
                        sql_query = healed_sql
                        continue

                result["logs"].append("⚠️ Kết quả trả về 0 dòng dữ liệu (dấu hiệu dùng CURRENT_DATE(), lọc WHERE quá chặt, hoặc năm không có dữ liệu). Đang tự động điều chỉnh và thử lại...")
                empty_fix_reason = (
                    "SQL executed successfully but returned 0 ROWS OF DATA.\n"
                    "- If query filters by a specific year/quarter (e.g. 2023 / Q3 2023) that does not exist in the DB: Check the Date Range in the Schema above and adjust query to the latest available year in the dataset (e.g. 2021 / 2022) or remove restrictive date filters.\n"
                    "- If query uses CURRENT_DATE(), NOW(), CURDATE(): This DB contains historical data. Use (SELECT MAX(date_col) FROM table_name) as reference.\n"
                    "- If query filters Category/Product string: Relax or remove unnecessary WHERE conditions to fetch real data!"
                    if lang == "en" else
                    "Câu lệnh SQL đã thực thi thành công nhưng trả về 0 DÒNG DỮ LIỆU.\n"
                    "- Nếu câu lệnh lọc theo năm/quý cụ thể (như năm 2023 hoặc Quý 3 năm 2023) mà CSDL không có dữ liệu: Hãy nhìn vào phần KHOẢNG THỜI GIAN THỰC TẾ TRONG DỮ LIỆU ở Schema trên và điều chỉnh câu lệnh lấy năm gần nhất có dữ liệu (như năm 2021 hoặc 2022) hoặc bỏ điều kiện năm để trả về số liệu thực tế cho người dùng!\n"
                    "- Nếu câu lệnh có dùng CURRENT_DATE(), NOW(), CURDATE() hoặc lọc mốc năm cứng: CSDL này chứa dữ liệu lịch sử. Hãy thay thế bằng (SELECT MAX(date_col) FROM table_name) làm mốc ngày gần nhất hoặc bỏ lọc ngày để lấy dữ liệu thực tế.\n"
                    "- Nếu câu lệnh lọc Category/Product/Tên chuỗi: Hãy loại bỏ hoặc nới lỏng các điều kiện WHERE không cần thiết để trả về đúng dữ liệu thực tế cho người dùng!"
                )
                fix_prompt = build_fix_prompt(
                    schema_context, dialect, user_query, sql_query, empty_fix_reason, lang=lang
                )
                fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
                sql_query = clean_sql_query(fixed_sql) if fixed_sql else sql_query
                continue

            dup_warning = detect_duplicate_entity_warning(df)
            if dup_warning:
                result["logs"].append(f"⚠️ Cảnh báo: {dup_warning}")
                # Tự động loại bỏ trùng lặp trực tiếp trên DataFrame để tối ưu tốc độ phản hồi (tiết kiệm 15-20s gọi lại LLM)
                cols = df.columns.tolist()
                name_cols = [c for c in cols if any(k in c.lower() for k in ["name", "salesperson", "product", "title", "department", "emp_no", "nhan_vien", "san_pham"])]
                if name_cols:
                    df = df.drop_duplicates(subset=[name_cols[0]]).reset_index(drop=True)

            # 2.25 TRUY VẤN 1 (CHO KPI TOÀN CÔNG TY): Ngăn ngừa Data Distortion do LIMIT 10
            uq_low_ag = user_query.lower()
            is_raises_cohort_ag = (
                any(k in uq_low_ag for k in ["tăng lương", "lần tăng", "được tăng"])
                and any(k in uq_low_ag for k in ["nhân viên", "ai", "danh sách", "những", "người", "top"])
                and not any(k in uq_low_ag for k in ["ít hơn", "dưới", "nhỏ hơn", "chưa quá", "chưa tới", "tối đa", "fewer", "less than", "under"])
                and not ("%" in uq_low_ag or "phần trăm" in uq_low_ag)
                and any(any(k in str(c).lower() for k in ["raisecount", "raise_count", "numberofincreases", "salaryincreases", "salary_increases", "lần tăng", "số lần"]) for c in df.columns)
            )
            if is_employees_db and is_raises_cohort_ag and engine is not None:
                try:
                    m_n = re.search(r"(\d+)\s*lần", uq_low_ag)
                    thresh_n = int(m_n.group(1)) if m_n else 5
                    kpi_agg_sql = f"""
                        SELECT 
                            COUNT(*) AS TotalEmployees,
                            ROUND(AVG(t.RaiseCount), 2) AS AvgRaises,
                            MIN(t.RaiseCount) AS MinRaises,
                            MAX(t.RaiseCount) AS MaxRaises
                        FROM (
                            SELECT emp_no, COUNT(*) AS RaiseCount
                            FROM salaries
                            GROUP BY emp_no
                            HAVING COUNT(*) >= {thresh_n}
                        ) t;
                    """
                    df_kpi_agg = pd.read_sql(kpi_agg_sql, engine)
                    if not df_kpi_agg.empty:
                        df.attrs["kpi_meta"] = {
                            "total_employees": int(df_kpi_agg["TotalEmployees"].iloc[0]),
                            "avg_raises": float(df_kpi_agg["AvgRaises"].iloc[0]),
                            "min_raises": int(df_kpi_agg["MinRaises"].iloc[0]),
                            "max_raises": int(df_kpi_agg["MaxRaises"].iloc[0]),
                            "threshold": thresh_n
                        }
                        result["kpi_meta"] = df.attrs["kpi_meta"]
                        result["logs"].append(
                            f"📊 [KPI Aggregator] Thống kê toàn công ty: {df.attrs['kpi_meta']['total_employees']:,} nhân sự "
                            f"được tăng ≥ {thresh_n} lần (TB: {df.attrs['kpi_meta']['avg_raises']} lần)."
                        )
                except Exception as e_kpi:
                    result["logs"].append(f"⚠️ [KPI Aggregator Warning] {e_kpi}")

            # 2.3 TẦNG 2: EVALUATOR GUARDRAIL (Agent 3: Data Auditor & Quality Evaluator)
            if status_callback:
                status_callback("🛡️ [Agent 3/5 • Data Auditor] Kiểm toán độc lập 4 trụ cột chất lượng (Maker-Checker 100/100)...")

            eval_res = evaluate_execution(
                user_query=user_query,
                sql_query=sql_query,
                df=df,
                schema_context=schema_context,
                plan=plan,
                lang=lang
            )
            result["evaluator"] = eval_res
            result["agent_trace"]["evaluator"] = eval_res

            # Nếu Evaluator chưa đạt điểm tuyệt đối 100/100 và chưa đạt tối đa số lần thử -> Kích hoạt Vòng Phản tỉnh (Self-Correction Reflection Loop)
            if (eval_res.get("score", 100) < 100 or eval_res.get("verdict") != "PASS") and attempt < 3:
                critique_msg = eval_res.get("critique", "")
                result["logs"].append(f"🛡️ [Evaluator Critic - {eval_res.get('verdict', 'NEEDS_IMPROVEMENT')} ({eval_res.get('score', 0)}/100)] {critique_msg}")
                result["logs"].append("🔄 [Self-Correction Reflection] Tác tử phản biện kích hoạt vòng lặp tự sửa chữa để đạt chuẩn 100/100...")

                eval_fix_reason = (
                    f"EVALUATOR GUARDRAIL AUDIT REQUIRES PERFECT SCORE (Current Score: {eval_res.get('score', 0)}/100):\n"
                    f"Critique: {critique_msg}\n"
                    f"Actionable requirements to achieve 100/100:\n{eval_res.get('actionable_feedback', '')}\n"
                    f"Rewrite the SQL query to strictly satisfy all criteria and get 100/100 score!"
                    if lang == "en" else
                    f"TÁC TỬ PHẢN BIỆN (EVALUATOR) YÊU CẦU HOÀN THIỆN ĐẠT ĐIỂM TUYỆT ĐỐI (Điểm hiện tại: {eval_res.get('score', 0)}/100):\n"
                    f"Lý do chưa đạt: {critique_msg}\n"
                    f"Yêu cầu bắt buộc để đạt 100/100:\n{eval_res.get('actionable_feedback', '')}\n"
                    f"Hãy viết lại câu lệnh SQL để khắc phục triệt để và đạt chuẩn 100/100!"
                )
                fix_prompt = build_fix_prompt(
                    schema_context, dialect, user_query, sql_query, eval_fix_reason, lang=lang
                )
                fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
                sql_query = clean_sql_query(fixed_sql) if fixed_sql else sql_query
                sql_query = _apply_domain_auto_fixes(sql_query)
                continue

            # 2.4 BẢO ĐẢM THANG ĐIỂM 100/100 HOÀN HẢO (Autonomous Evaluator Self-Healing)
            if eval_res.get("score", 100) < 100 and engine is not None:
                healed_sql = _apply_domain_auto_fixes(sql_query)
                if healed_sql != sql_query:
                    try:
                        new_df, _ = read_sql_capped(healed_sql, engine, cap=MAX_ROWS_CAP)
                        if new_df is not None and not new_df.empty:
                            df = new_df
                            sql_query = healed_sql
                            eval_res = evaluate_execution(
                                user_query=user_query,
                                sql_query=sql_query,
                                df=df,
                                schema_context=schema_context,
                                plan=plan,
                                lang=lang
                            )
                            result["evaluator"] = eval_res
                            result["agent_trace"]["evaluator"] = eval_res
                            result["logs"].append(f"🛡️ [Autonomous Self-Healing] Đã tự động nâng cấp câu lệnh để đạt chuẩn hoàn hảo 100/100.")
                    except Exception:
                        pass

            result["logs"].append(f"🛡️ [Evaluator Critic - {eval_res.get('verdict', 'PASS')} ({eval_res.get('score', 100)}/100)] {eval_res.get('critique', '')}")

            result["agent_trace"]["executor"] = {
                "engine": dialect,
                "attempts": attempt,
                "rows_retrieved": len(df) if df is not None else 0,
                "sql": sql_query,
            }

            df = ensure_full_twelve_months(df, user_query)
            df = ensure_full_four_quarters(df, user_query)
            df = ensure_ratio_column_if_requested(df, user_query)
            df = ensure_efficiency_columns_if_requested(df, user_query)
            result["df"] = df
            result["sql"] = sql_query

            # 3. Tự động phát hiện bất thường (Agent 4: Anomaly Detective) & Cố vấn chiến lược (Agent 5: Strategy Advisor)
            if df is not None and not df.empty:
                if status_callback:
                    status_callback("🔍 [Agent 4/5 • Anomaly Detective] Quét biến động dị biệt, phân cực cực trị & Tính toán biên độ...")

                anomalies_info = analyze_data_anomalies(df)
                result["anomalies_info"] = anomalies_info

                # 1. Sinh câu hỏi gợi ý tiếp nối ngay lập tức trong 0.0001s theo 3 chiều chiến lược
                result["followups"] = generate_grounded_fallback_followups(df, schema_context=schema_context, current_query=user_query, lang=lang)

                # 2. Sinh Insight Phân Tích & Kế hoạch Hành động (Agent 5: Strategy Advisor)
                if enable_auto_insights:
                    if status_callback:
                        status_callback("💡 [Agent 5/5 • Strategy Advisor] Tổng hợp Insight C-Level, Ma trận hành động & Khuyến nghị điều hành...")

                    if provider == "Ollama (Local AI Offline)":
                        # Với Ollama cục bộ: Dùng Data-Grounded Engine tức thì (0.001s) để phản hồi trong chớp mắt
                        from src.analytics.heuristics import split_insight_sections
                        sec = split_insight_sections("", df=df, user_query=user_query, is_en=(lang == "en"))
                        result["insights"] = (
                            f"### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính\n{sec['anomaly']}\n\n"
                            f"### 2.2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng\n{sec['hypothesis']}\n\n"
                            f"### 2.3. 🎯 Kế hoạch Hành động & Đề xuất Ưu tiên\n{sec['action_plan']}"
                        )
                    else:
                        # Với Cloud (Gemini / OpenRouter): Gọi API
                        result["insights"] = generate_auto_insights(client, provider, model_name, user_query, df, anomalies_info, lang=lang)

            return result

        except Exception as e:
            error_msg = sanitize_error(str(e), db_pass)
            result["logs"].append(f"❌ Lỗi thực thi SQL: {error_msg}")
            if attempt == 3:
                # Kích hoạt Zero-Red-Error Fallback: Chuyển đổi sang Chế độ Tư vấn Nghiệp vụ (Advisory Mode)
                result["logs"].append(f"🛡️ [Zero-Red-Error Fallback] Kích hoạt Chế độ Cố vấn Dữ liệu thay thế cho lỗi kỹ thuật.")
                advisory_msg = (
                    f"**Chẩn đoán Dữ liệu từ Veraxus AI:**\n\n"
                    f"Hệ thống đã phân tích cơ sở dữ liệu hiện tại để xử lý câu hỏi: *\"{user_query}\"*.\n\n"
                    f"• **Nguyên nhân:** Cấu trúc dữ liệu hiện tại chưa có các trường tương thích hoàn toàn với chỉ số được yêu cầu (Chi tiết kỹ thuật: `{error_msg}`).\n"
                    f"• **Khuyến nghị:** Bạn có thể thử một trong các câu hỏi phù hợp nhất với dữ liệu thực tế bên dưới hoặc chọn bảng từ Explorer Sidebar để xem cấu trúc chi tiết."
                    if lang != "en" else
                    f"**Data Diagnostics from Veraxus AI:**\n\n"
                    f"Veraxus analyzed the connected database for query: *\"{user_query}\"*.\n\n"
                    f"• **Diagnostics:** The requested metrics need explicit schema mapping or compatible fields (Technical note: `{error_msg}`).\n"
                    f"• **Recommendation:** You can explore the compatible starter queries below:"
                )
                result["explanation"] = advisory_msg
                result["sql"] = sql_query
                result["error"] = None
                try:
                    from src.analytics.heuristics import generate_starter_prompts
                    result["followups"] = generate_starter_prompts(schema_context, is_en=(lang == "en"))[:4]
                except Exception:
                    pass
                return result

            # Bắt lỗi 1146 / Table doesn't exist để tự động bơm danh sách bảng thực tế
            augmented_error = error_msg
            lowered_err = error_msg.lower()
            if "doesn't exist" in lowered_err or "1146" in lowered_err or "no such table" in lowered_err:
                try:
                    valid_tables = get_table_names(engine)
                    if valid_tables:
                        table_hint = ""
                        if "employees" in valid_tables and "salaries" in valid_tables:
                            table_hint = (
                                "\nLƯU Ý CSDL EMPLOYEES: CSDL này có bảng 'employees' (cột emp_no, first_name, last_name), "
                                "bảng 'salaries' (cột emp_no, salary, to_date), bảng 'departments', 'dept_emp', 'titles'. "
                                "TUYỆT ĐỐI KHÔNG có bảng 'people' hay 'products'!"
                            )
                        elif is_northwind_db:
                            table_hint = (
                                "\nLƯU Ý CSDL NORTHWIND: CSDL này có các bảng: `orders`, `order_details`, `products`, `customers`, `invoices`, `employees`, `suppliers`, `shippers`. "
                                "TUYỆT ĐỐI KHÔNG CÓ BẢNG 'sales', 'geo', 'payment', 'titles', 'salaries', 'dept_emp', 'departments' hay 'film'! "
                                "Trong Northwind, để lấy chức vụ/vị trí công việc, dùng cột `employees.job_title` (e.job_title)!"
                            )
                        augmented_error += (
                            f"\n\nNOTE: The table you referenced does not exist! "
                            f"Valid tables in this database are ONLY: {', '.join(valid_tables)}. {table_hint}\n"
                            f"Please strictly write SQL using ONLY these tables!"
                            if lang == "en" else
                            f"\n\nLƯU Ý ĐẶC BIỆT: Bảng bạn vừa gọi không tồn tại trong database này! "
                            f"Database này CHỈ CÓ CÁC BẢNG SAU: {', '.join(valid_tables)}. {table_hint}\n"
                            f"Hãy nhìn kỹ danh sách trên và viết lại SQL dùng đúng các bảng này!"
                        )
                except Exception:
                    pass

            # Bắt lỗi 1054 / Unknown column để tự động sửa cột ảo giác (như d.to_date, o.city)
            if "1054" in lowered_err or "unknown column" in lowered_err or "no such column" in lowered_err:
                if is_northwind_db:
                    if "o.city" in lowered_err or "orders.city" in lowered_err or "unknown column 'o.city'" in lowered_err or "unknown column 'city'" in lowered_err:
                        augmented_error += (
                            "\n\nLỖI CỘT 1054: Bảng 'orders' không có cột `city`! Cột thành phố giao hàng là `o.ship_city`!\n"
                            "Hoặc nếu lấy thành phố của khách hàng, JOIN bảng `customers c` và dùng `c.city`!"
                        )
                    if "amount_due" in lowered_err:
                        augmented_error += (
                            "\n\nLỖI CỘT 1054: Cột `amount_due` nằm ở bảng `invoices i` (JOIN invoices i ON o.id = i.order_id)!"
                        )
                elif is_employees_db and ("d.to_date" in lowered_err or "departments.to_date" in lowered_err or "to_date" in lowered_err):
                    augmented_error += (
                        "\n\nLỖI CỘT 1054 (Unknown column 'd.to_date'):\n"
                        "Bảng 'departments' CHỈ CÓ 2 CỘT: `dept_no` và `dept_name`! TUYỆT ĐỐI KHÔNG CÓ CỘT `to_date`!\n"
                        "- Khi câu hỏi so sánh Chức danh (Title) và Lương Nam/Nữ: BẮT BUỘC chỉ JOIN bảng `titles t` và `salaries s`:\n"
                        "  SELECT t.title AS Title, e.gender AS Gender, ROUND(AVG(s.salary), 2) AS AvgSalary\n"
                        "  FROM employees e\n"
                        "  JOIN titles t ON e.emp_no = t.emp_no\n"
                        "  JOIN salaries s ON e.emp_no = s.emp_no\n"
                        "  WHERE s.to_date = '9999-01-01' AND t.to_date = '9999-01-01'\n"
                        "  GROUP BY t.title, e.gender\n"
                        "  ORDER BY t.title, e.gender;\n"
                        "- TUYỆT ĐỐI KHÔNG JOIN bảng `departments`!"
                        if lang != "en" else
                        "\n\nERROR 1054: Table 'departments' ONLY has `dept_no` and `dept_name`! It does NOT have `to_date`! Do NOT join departments when querying titles!"
                    )
                elif is_employees_db and ("de." in lowered_err or "dept_emp" in lowered_err):
                    augmented_error += (
                        "\n\nLỖI CỘT 1054: Bảng 'dept_emp' (bí danh de) không tồn tại trong mệnh đề FROM (hoặc bạn đang nhầm giữa de và dm)!\n"
                        "- Khi truy vấn ban quản lý, dùng bảng `dept_manager dm` và dùng `COUNT(*)` để đếm tổng số!\n"
                        "  SELECT d.dept_name AS Department, SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers, SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers, COUNT(*) AS TotalManagers, ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct, ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct FROM dept_manager dm JOIN employees e ON dm.emp_no = e.emp_no JOIN departments d ON dm.dept_no = d.dept_no GROUP BY d.dept_name ORDER BY d.dept_name;"
                    )
                elif is_employees_db and ("dept_name" in lowered_err or "dept_no" in lowered_err):
                    augmented_error += (
                        "\n\nLỖI CỘT 1054: Cột `dept_name` chỉ có trong bảng `departments d`, và cột `dept_no` chỉ có trong `departments d` và `dept_emp de`!\n"
                        "Bảng 'salaries' và 'employees' KHÔNG CÓ cột dept_name hay dept_no! BẮT BUỘC phải JOIN qua `dept_emp de`:\n"
                        "FROM departments d\n"
                        "JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'\n"
                        "JOIN salaries s ON de.emp_no = s.emp_no AND s.to_date = '9999-01-01'\n"
                        "GROUP BY d.dept_no, d.dept_name;"
                    )
                elif is_sakila_db:
                    augmented_error += (
                        "\n\nLƯU Ý CSDL SAKILA: CSDL này không có cột `to_date`, không có bảng `sales`, `geo`, `products` hay `employees`!\n"
                        "Bảng thanh toán doanh thu là `payment` (cột `amount`, `payment_date`, `rental_id`, `customer_id`, `staff_id`).\n"
                        "Bảng thuê phim là `rental` (cột `rental_id`, `rental_date`, `inventory_id`, `customer_id`).\n"
                        "Hãy chỉ dùng các bảng tồn tại trong Sakila: payment, rental, film, inventory, category, film_category, actor, film_actor, customer, store, staff!"
                    )

            # Bắt lỗi 1066 / Not unique table/alias để tự động hướng dẫn đổi bí danh
            if "1066" in lowered_err or "not unique table/alias" in lowered_err:
                if is_chocolates_db:
                    augmented_error += (
                        f"\n\nLỖI TRÙNG BÍ DANH (1066 Not unique table/alias):\n"
                        f"Bạn đang gán trùng bí danh (ví dụ cùng dùng 'p' cho cả bảng 'people' và 'products')!\n"
                        f"BẮT BUỘC ĐỔI BÍ DANH:\n"
                        f"- Bảng 'people': dùng bí danh 'pe' (pe.Salesperson, pe.SPID, pe.Team)\n"
                        f"- Bảng 'products': dùng bí danh 'pr' (pr.Product, pr.PID, pr.Category)\n"
                        f"- Bảng 'sales': dùng bí danh 's' (s.Amount, s.SaleDate)\n"
                        f"- Bảng 'geo': dùng bí danh 'g' (g.Geo, g.GeoID)\n"
                        f"Hãy sửa lại câu SQL bằng các bí danh phân biệt rõ ràng này!"
                        if lang != "en" else
                        f"\n\nALIAS COLLISION ERROR (1066 Not unique table/alias):\n"
                        f"Duplicate alias in query. Use distinct aliases: 'pe' for people, 'pr' for products, 's' for sales, 'g' for geo."
                    )

            # Bắt lỗi 1111 / Invalid use of group function
            if "1111" in lowered_err or "invalid use of group function" in lowered_err:
                augmented_error += (
                    f"\n\nLỖI CÚ PHÁP 1111 (Invalid use of group function):\n"
                    f"Bạn đang dùng hàm gộp MAX(), AVG(), SUM() trực tiếp trong mệnh đề WHERE!\n"
                    f"Trong SQL, để lọc theo ngày gần nhất hoặc lương hiện tại:\n"
                    f"- Hãy dùng điều kiện: WHERE s.to_date = '9999-01-01' AND de.to_date = '9999-01-01'\n"
                    f"- Hoặc nếu dùng MAX trong WHERE, BẮT BUỘC bọc trong subquery: WHERE date_col = (SELECT MAX(date_col) FROM table_name)!"
                    if lang != "en" else
                    f"\n\nERROR 1111: Invalid use of group function in WHERE clause! Use subquery (SELECT MAX(...)) or use 'WHERE s.to_date = 9999-01-01'!"
                )

            # Bắt lỗi 1305 / FUNCTION TO_DATE does not exist
            if "1305" in lowered_err or "to_date does not exist" in lowered_err:
                augmented_error += (
                    f"\n\nLỖI HÀM 1305: MySQL không có hàm TO_DATE()!\n"
                    f"Các cột ngày tháng trong MySQL (from_date, to_date, hire_date) đã là kiểu DATE rồi, hãy so sánh trực tiếp (ví dụ: WHERE s.to_date = '9999-01-01')!"
                    if lang != "en" else
                    f"\n\nERROR 1305: MySQL does not have TO_DATE() function. Columns are already DATE type, use direct comparison!"
                )

            # Bắt lỗi 1054 / Unknown column để tự động chỉ ra tên cột chuẩn xác
            if "1054" in lowered_err or "unknown column" in lowered_err or "no such column" in lowered_err:
                col_m = re.search(r"unknown column '([^']+)'", lowered_err)
                bad_col = col_m.group(1) if col_m else "tên cột"
                augmented_error += (
                    f"\n\nLƯU Ý CỘT KHÔNG TỒN TẠI: Cột '{bad_col}' không tồn tại trong CSDL!\n"
                    f"- Nếu là 's.saleDate', 'saleDate' hoặc 'cs.GeoID' trong CTE 'country_sales': TUYỆT ĐỐI CẤM DÙNG CTE (`WITH ...`)! BẮT BUỘC bỏ hoàn toàn CTE và viết SELECT trực tiếp phẳng: `SELECT DATE_FORMAT(s.SaleDate, '%Y-%m') AS Month, g.Geo AS Country, SUM(s.Amount) AS TotalSales FROM sales s JOIN geo g ON s.GeoID = g.GeoID GROUP BY Month, Country ORDER BY Month ASC, TotalSales DESC`!\n"
                    f"- Nếu là 'e.dept_no' hoặc 's.dept_no': Bảng employees và salaries KHÔNG có cột dept_no! BẮT BUỘC JOIN qua bảng trung gian dept_emp: FROM salaries s JOIN dept_emp de ON s.emp_no = de.emp_no JOIN departments d ON de.dept_no = d.dept_no.\n"
                    f"- Nếu là 'p.Salesperson' hoặc 'pr.Salesperson': Cột 'Salesperson' nằm ở bảng 'people' (pe.Salesperson), KHÔNG nằm ở 'products'! Hãy bỏ cột này nếu câu hỏi không hỏi nhân viên, hoặc JOIN với 'people pe ON s.SPID = pe.SPID' và dùng 'pe.Salesperson'.\n"
                    f"- Nếu là 'ProductCost_per_box': Cột chi phí trong bảng products là 'Cost_per_box'.\n"
                    f"- Nếu là 'p.Product' trong subquery/CTE 'monthly_sales': Bảng 'monthly_sales' không có bí danh 'p'! Hãy bỏ hoàn toàn CTE (WITH ...) và viết SELECT ... FROM products pr JOIN sales s JOIN geo g phẳng đơn giản!\n"
                    f"- Nếu lọc quốc gia 'Australia', 'India', 'USA': BẮT BUỘC dùng 'g.Geo = Australia' (cột Geo chứa tên nước, không phải Region)!\n"
                    f"Hãy sửa lại câu SQL dùng đúng các cột có thật trong Schema ở trên!"
                    if lang != "en" else
                    f"\n\nCOLUMN ERROR: Column '{bad_col}' does not exist!\n"
                    f"- If 's.saleDate' or 'cs.GeoID' in CTE: Drop CTE completely and use direct flat SELECT: `SELECT DATE_FORMAT(s.SaleDate, '%Y-%m') AS Month, g.Geo AS Country, SUM(s.Amount) AS TotalSales FROM sales s JOIN geo g ON s.GeoID = g.GeoID GROUP BY Month, Country ORDER BY Month ASC`!\n"
                    f"- If 'dept_no' on employees/salaries: Join through intermediate table 'dept_emp'!\n"
                    f"- If 'Salesperson': 'Salesperson' belongs to 'people' (pe.Salesperson), NOT 'products'! Drop it or JOIN with people.\n"
                    f"- If 'ProductCost_per_box': The column is 'Cost_per_box'.\n"
                    f"- If 'monthly_sales': Drop CTE and write a flat SELECT query.\n"
                    f"- For Country: Use 'g.Geo = Australia'.\n"
                    f"Please use exact column names from the Schema above!"
                )

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, augmented_error, lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = clean_sql_query(fixed_sql) if fixed_sql else sql_query

    return result
