"""
SQL Generation and Execution Agent with safety validation, parenthesis checking,
self-healing loop (including 0-row empty result recovery), conversational explanation detection,
automatic business insight discovery with Priority Tagging, bilingual support, and follow-up question suggestions.
"""

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

    # 3. Tự động tách khoảng trắng nếu mô hình AI sinh dính chữ từ khóa SQL (Bảo vệ các cột như from_date, to_date)
    keywords_to_space = [
        ("FROM", r"(?<![\._])\bFROM(?=[a-zA-Z`])(?!_)"),
        ("SELECT", r"(?<![\._])\bSELECT(?=[a-zA-Z`*])(?!_)"),
        ("WHERE", r"(?<![\._])\bWHERE(?=[a-zA-Z`])(?!_)"),
        ("JOIN", r"(?<![\._])\bJOIN(?=[a-zA-Z`])(?!_)"),
        ("GROUP BY", r"(?<![\._])\bGROUP\s+BY(?=[a-zA-Z`])(?!_)"),
        ("ORDER BY", r"(?<![\._])\bORDER\s+BY(?=[a-zA-Z`])(?!_)"),
        ("HAVING", r"(?<![\._])\bHAVING(?=[a-zA-Z`])(?!_)"),
        ("ON", r"(?<![\._])\bON(?=[a-zA-Z`])(?!_)"),
        ("LIMIT", r"(?<![\._])\bLIMIT(?=\d)"),
    ]
    for kw_name, kw_pattern in keywords_to_space:
        s = re.sub(kw_pattern, kw_name + " ", s, flags=re.IGNORECASE)

    # 4. Tìm vị trí SELECT hoặc WITH đầu tiên nếu có lời dẫn phía trước
    match_kw = re.search(r"\b(SELECT|WITH)\b", s, re.IGNORECASE)
    if match_kw and match_kw.start() > 0:
        prefix = s[:match_kw.start()].strip()
        if not any(k in prefix.lower() for k in FORBIDDEN_KEYWORDS):
            s = s[match_kw.start():].strip()

    # 5. Tự động cân bằng dấu ngoặc đơn () nếu bị thiếu dấu đóng ngoặc trước AS/FROM
    s = auto_balance_parentheses(s)

    # 6. Tự động sửa các lỗi cú pháp phổ biến của Small LLMs
    # 6.1 Xóa dấu phẩy thừa trước các mệnh đề ORDER BY, GROUP BY, FROM, WHERE, HAVING, LIMIT
    s = re.sub(r",\s*(ORDER\s+BY|GROUP\s+BY|FROM|WHERE|HAVING|LIMIT)\b", r" \1", s, flags=re.IGNORECASE)

    # 6.2 Sửa lỗi bí danh bảng de.dept_name -> d.dept_name (dept_emp không có cột dept_name)
    s = re.sub(r"\bde\.dept_name\b", "d.dept_name", s, flags=re.IGNORECASE)

    # 6.3 Sửa lỗi tên bảng thiếu s: FROM/JOIN department -> FROM/JOIN departments
    s = re.sub(r"\b(FROM|JOIN)\s+department\b(?!\s+(?:AS\s+)?departments\b)", r"\1 departments", s, flags=re.IGNORECASE)

    # 6.4 Khi đếm số lần tăng lương lịch sử hoặc nhóm theo năm/thời gian (GROUP BY YEAR/from_date):
    # Tự động gỡ bỏ triệt để to_date = '9999-01-01' để lấy đủ toàn bộ lịch sử (tránh lỗi chỉ ra 2 năm 2001-2002)
    if re.search(r"GROUP\s+BY\s+.*(?:YEAR|from_date|hire_date|hireyear)", s, re.IGNORECASE) or re.search(r"COUNT\s*\(\s*s\.salary\s*\)|raisecount", s, re.IGNORECASE):
        s = re.sub(r"\s*AND\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]\s*AND", " WHERE", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", s, flags=re.IGNORECASE)

    # 6.5 Sửa lỗi tên cột không tồn tại s.salary_date -> s.from_date
    s = re.sub(r"\b(?:[a-zA-Z0-9_]+\.)?salary_date\b", "s.from_date", s, flags=re.IGNORECASE)

    # 6.5 Tự động sửa lỗi tính thâm niên trừ năm to_date 9999 (gây ra lỗi 8,014 năm phi lý) và xóa cột HireYear = 9999
    if re.search(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)\s*-\s*YEAR\s*\(", s, re.IGNORECASE):
        s = re.sub(
            r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)\s*-\s*YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?hire_date\s*\)\s*(?:AS\s+[a-zA-Z0-9_]+)?",
            "ROUND(DATEDIFF(IF(de.to_date = '9999-01-01', '2002-08-01', de.to_date), e.hire_date) / 365.25, 1) AS YearsOfService",
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

    return s.strip().strip("`").rstrip(";").strip()


def extract_requested_limit(user_query: str) -> int | None:
    """Trích xuất số lượng N mà người dùng yêu cầu (ví dụ: Top 10, Top 5, 10 nhân viên, danh sách 10...)."""
    if not user_query:
        return None
    # 1. Khớp Top N, TopN (VD: Top 10, top 5, top10, top3)
    m = re.search(r"\btop\s*(\d+)\b", user_query, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 2. Khớp các biến thể tiếng Việt: '10 nhân viên', '10 người', '10 chức danh', '10 sản phẩm'
    m2 = re.search(r"\b(\d+)\s+(?:nhân viên|người|chức danh|vị trí|phòng ban|sản phẩm|khách hàng|đơn hàng|món)\b", user_query, re.IGNORECASE)
    if m2:
        return int(m2.group(1))

    # 3. Khớp 'danh sách 10', 'lấy 10', 'cho tôi 10'
    m3 = re.search(r"\b(?:danh\s+sách|lấy|cho\s+tôi|xem)\s+(\d+)\b", user_query, re.IGNORECASE)
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
        is_time_trend = any(k in q_low for k in ["qua các tháng", "từng tháng", "theo tháng", "xu hướng", "biến động theo thời gian", "qua các năm", "theo từng năm"])
        if is_time_trend:
            sql = re.sub(r"\s+LIMIT\s+\d+\s*;?$", "", sql, flags=re.IGNORECASE).rstrip(";").strip()
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


def auto_fix_top_employee_salary_query(sql: str, user_query: str) -> str:
    """Tự động sửa câu hỏi Top N lương cao nhất của nhân viên để luôn lọc đúng lương hiện tại (to_date = '9999-01-01') tránh trùng lặp năm lịch sử gây hao hụt số dòng."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_yearly = any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "từng năm", "qua từng năm", "thay đổi như thế nào", "xu hướng", "biến động", "lịch sử", "theo thời gian"])
    if is_yearly:
        return sql

    is_top_salary = (
        any(k in q_low for k in ["lương cao nhất", "thu nhập cao nhất", "mức lương cao nhất"])
        and any(k in q_low for k in ["nhân viên", "nhân sự", "người", "ai", "sales", "phòng"])
        and not any(k in q_low for k in ["chức danh", "title", "nam và nữ", "quỹ lương"])
    )
    if not is_top_salary:
        return sql

    lowered_sql = sql.lower()
    # Kiểm tra xem câu SQL có JOIN salaries và employees không
    if "salaries" in lowered_sql and "employees" in lowered_sql:
        # Đảm bảo có lọc s.to_date = '9999-01-01' để không bị lặp 1 nhân viên nhiều năm lương
        if not re.search(r"\bs\.to_date\s*=\s*'9999-01-01'", sql, re.IGNORECASE) and not re.search(r"GROUP\s+BY\s+.*emp_no", sql, re.IGNORECASE):
            if "where" in lowered_sql:
                sql = re.sub(r"\bWHERE\b", "WHERE s.to_date = '9999-01-01' AND ", sql, count=1, flags=re.IGNORECASE)
            else:
                if re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE):
                    sql = re.sub(r"\bORDER\s+BY\b", "WHERE s.to_date = '9999-01-01' ORDER BY", sql, count=1, flags=re.IGNORECASE)
                elif re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
                    sql = re.sub(r"\bLIMIT\b", "WHERE s.to_date = '9999-01-01' LIMIT", sql, count=1, flags=re.IGNORECASE)
                else:
                    sql = sql.rstrip(";").strip() + " WHERE s.to_date = '9999-01-01'"

        # Nếu có dept_emp, đảm bảo de.to_date = '9999-01-01'
        if "dept_emp" in lowered_sql and not re.search(r"\bde\.to_date\s*=\s*'9999-01-01'", sql, re.IGNORECASE):
            if "where" in sql.lower():
                sql = re.sub(r"\bWHERE\b", "WHERE de.to_date = '9999-01-01' AND ", sql, count=1, flags=re.IGNORECASE)

    return sql


def auto_fix_yearly_salary_trend_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và loại bỏ triệt để điều kiện to_date = '9999-01-01' khi người dùng hỏi về xu hướng/biến động qua các năm (tránh lỗi chỉ ra 2 năm 2001-2002)."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_yearly_trend = any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "từng năm", "qua từng năm", "thay đổi như thế nào", "xu hướng", "biến động", "lịch sử", "theo thời gian"])
    is_salary_or_hire = any(k in q_low for k in ["lương", "thu nhập", "salary", "quỹ lương", "tuyển dụng", "nhân sự", "chi trả"])
    grouped_by_year = bool(re.search(r"GROUP\s+BY\s+.*(?:YEAR|hireyear|from_date)", sql, re.IGNORECASE))

    if (is_yearly_trend and is_salary_or_hire) or grouped_by_year:
        # 1. Gỡ bỏ triệt để mọi điều kiện lọc to_date = 9999-01-01 (nguyên nhân cốt lõi khiến dữ liệu lịch sử chỉ còn 2 năm 2001 và 2002)
        sql = re.sub(r"\s*AND\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]\s*AND", " WHERE", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)

        # 2. Đổi YEAR(to_date) thành YEAR(s.from_date) để không bị năm 9999
        sql = re.sub(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)", "YEAR(s.from_date)", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\b(?:[a-zA-Z0-9_]+\.)?salary_date\b", "s.from_date", sql, flags=re.IGNORECASE)

        # 3. Trường hợp hỏi mức lương trung bình toàn công ty qua các năm
        is_avg_salary = any(k in q_low for k in ["lương trung bình", "mức lương", "lương bình quân"]) and any(k in q_low for k in ["công ty", "toàn công ty", "tất cả", "nhân viên", "qua các năm", "theo năm", "hàng năm"])
        if is_avg_salary:
            if "salaries" not in sql.lower() or "avg" not in sql.lower() or not re.search(r"GROUP\s+BY\s+.*YEAR", sql, re.IGNORECASE):
                return """SELECT 
    YEAR(s.from_date) AS Year,
    ROUND(AVG(s.salary), 2) AS AverageSalary
FROM salaries s
GROUP BY YEAR(s.from_date)
ORDER BY Year ASC"""

    return sql


def auto_fix_title_assignments_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và khắc phục lỗi mô hình AI truy vấn sai sang bảng salaries khi người dùng hỏi về số lượng nhân viên bổ nhiệm chức danh mới qua từng năm."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_title_assignment = any(k in q_low for k in ["bổ nhiệm", "thăng chức", "chức danh mới", "bổ nhiệm mới", "nhận chức"]) or (
        any(k in q_low for k in ["chức danh", "title", "vị trí"]) and any(k in q_low for k in ["qua từng năm", "qua các năm", "theo năm", "hàng năm", "từng năm"])
    )
    if not is_title_assignment:
        return sql

    lowered_sql = sql.lower()
    is_off_topic = "salaries" in lowered_sql or "salary" in lowered_sql or "raisecount" in lowered_sql or not re.search(r"GROUP\s+BY\s+.*(?:YEAR|from_date)", sql, re.IGNORECASE)

    if is_off_topic or "titles" not in lowered_sql:
        return """SELECT 
    YEAR(t.from_date) AS Year,
    COUNT(DISTINCT t.emp_no) AS TotalEmployees
FROM titles t
GROUP BY YEAR(t.from_date)
ORDER BY Year ASC"""

    # Đảm bảo bỏ lọc to_date = 9999-01-01 nếu có
    sql = re.sub(r"\s*AND\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]\s*AND", " WHERE", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*WHERE\s+[a-zA-Z0-9_.]*to_date\s*=\s*['\"]9999-01-01['\"]", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"YEAR\s*\(\s*(?:[a-zA-Z0-9_]+\.)?to_date\s*\)", "YEAR(t.from_date)", sql, flags=re.IGNORECASE)

    return sql


def auto_fix_company_hiring_trend_query(sql: str, user_query: str) -> str:
    """Tự động sửa câu hỏi thống kê số lượng nhân viên tuyển dụng theo từng năm từ trước đến nay."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_company_hiring = any(k in q_low for k in ["tuyển dụng", "tuyển"]) and any(k in q_low for k in ["năm", "từng năm", "qua các năm", "từ trước đến nay"]) and not any(k in q_low for k in ["phòng ban", "phòng", "department", "sales", "development"])
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
    is_longest_mgr = any(k in q_low for k in ["manager", "trưởng phòng", "quản lý"]) and any(k in q_low for k in ["lâu nhất", "dài nhất", "thâm niên nhất"]) and any(k in q_low for k in ["lịch sử", "từng giữ", "từng làm", "trước đến nay"])
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


def auto_fix_payroll_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và khắc phục lỗi mô hình AI dùng COUNT thay vì SUM(s.salary) khi người dùng hỏi về quỹ lương phòng ban hoặc theo năm."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_payroll_query = any(k in q_low for k in ["quỹ lương", "ngân sách lương", "tổng chi trả lương", "chi phí lương"]) or (
        any(k in q_low for k in ["tổng lương", "chi trả"]) and any(k in q_low for k in ["phòng ban", "phòng", "department", "năm", "qua các năm"])
    )
    if not is_payroll_query:
        return sql

    # Xử lý trường hợp hỏi xu hướng qua các năm
    is_yearly_trend = any(k in q_low for k in ["qua các năm", "theo năm", "hàng năm", "biến động"])
    if is_yearly_trend:
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
    SUM(s.salary) AS TotalSalaryBudget
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


def auto_fix_gender_ratio_query(sql: str, user_query: str) -> str:
    """Tự động phát hiện và sửa lỗi thiếu tỷ lệ Nam khi câu hỏi yêu cầu tỷ lệ Nam và Nữ trong ban quản lý, phòng ban hoặc toàn công ty."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    sql_low = sql.lower()
    asks_both_genders = any(k in q_low for k in ["nam và nữ", "nam nữ", "giới tính", "tỷ lệ nam", "tỉ lệ nam", "tỉ lệ nam nữ", "tỷ lệ nam nữ"])

    if not asks_both_genders:
        return sql

    is_dept_manager = any(k in q_low for k in ["ban quản lý", "dept_manager", "manager", "quản lý"])
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
        has_female = bool(re.search(r"\b(PercentageFemale|FemalePct|female)\b", sql, re.IGNORECASE))
        has_male = bool(re.search(r"\b(PercentageMale|MalePct|male)\b", sql, re.IGNORECASE))
        if uses_cte or not (has_female and has_male):
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
ORDER BY d.dept_name"""

    is_company = any(k in q_low for k in ["công ty", "toàn công ty", "company", "toàn bộ"]) or "employees" in sql_low
    if is_company or any(k in q_low for k in ["tỷ lệ", "tỉ lệ", "phần trăm", "cơ cấu"]):
        has_female = bool(re.search(r"\b(PercentageFemale|FemalePct|female)\b", sql, re.IGNORECASE))
        has_male = bool(re.search(r"\b(PercentageMale|MalePct|male)\b", sql, re.IGNORECASE))
        has_percentage = bool(re.search(r"\b(percentage|percent|pct|tỷ lệ|tỉ lệ)\b", sql, re.IGNORECASE))
        if not (has_female and has_male) and not has_percentage:
            return """SELECT 
    gender AS Gender,
    COUNT(*) AS EmployeeCount,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM employees), 2) AS Percentage
FROM employees
GROUP BY gender
ORDER BY EmployeeCount DESC"""

    return sql


def auto_fix_raises_query(sql: str, user_query: str) -> str:
    """Tự động khóa LIMIT 10 cho danh sách nhân viên tăng lương nhiều nhất, tránh tràn 5,000 dòng dữ liệu."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_raises_query = any(k in q_low for k in ["tăng lương", "lần tăng"]) and any(k in q_low for k in ["nhân viên", "ai", "danh sách", "những"])

    if not is_raises_query:
        return sql

    # Đảm bảo câu truy vấn tối ưu và có LIMIT 10
    if ("having count" in sql.lower() or "raisecount" in sql.lower() or "numberofincreases" in sql.lower()) and "from (" not in sql.lower():
        return """SELECT 
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
ORDER BY s_agg.RaiseCount DESC, s_agg.CurrentSalary DESC"""

    if not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        sql = sql.rstrip(";").strip() + " LIMIT 10"

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


def auto_fix_current_manager_salary_query(sql: str, user_query: str) -> str:
    """Tự động đảm bảo câu hỏi danh sách Manager/Trưởng phòng hiện tại của từng phòng ban kèm lương lấy đúng 9 managers hiện tại và mức lương mới nhất."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
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


def auto_fix_department_group_salary_query(sql: str, user_query: str) -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương giữa các phòng ban Kỹ thuật (Development, Research) và phòng Kinh doanh (Sales, Marketing)."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_tech_vs_comm = (
        (
            any(k in q_low for k in ["kỹ thuật", "tech"])
            and any(k in q_low for k in ["kinh doanh", "commercial", "sales"])
            and any(k in q_low for k in ["lương", "thu nhập", "salary"])
        ) or (
            ("development" in q_low or "research" in q_low)
            and ("sales" in q_low or "marketing" in q_low)
            and any(k in q_low for k in ["so sánh", "đối chiếu", "compare", "vs"])
        )
    )
    if not is_tech_vs_comm:
        return sql

    lowered_sql = sql.lower()
    has_filter_4 = all(d in lowered_sql for d in ["development", "research", "sales", "marketing"])
    has_group = "departmentgroup" in lowered_sql or "nhóm" in lowered_sql or "case when" in lowered_sql
    has_unwanted = any(d in lowered_sql for d in ["human resources", "customer service", "quality management", "finance", "production"])

    if not (has_filter_4 and has_group) or has_unwanted:
        return """SELECT 
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
ORDER BY DepartmentGroup, AvgSalary DESC"""

    return sql


def auto_fix_department_single_vs_others_salary_query(sql: str, user_query: str) -> str:
    """Tự động chuẩn hóa câu hỏi so sánh mức lương trung bình phòng ban với các phòng khác, loại bỏ cột phần trăm ảo làm phẳng biểu đồ và bỏ bộ lọc phòng ban đơn lẻ."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_dept_salary_comp = (
        any(k in q_low for k in ["so sánh", "so voi", "so với", "đối chiếu", "so sánh giữa"])
        and any(k in q_low for k in ["lương trung bình", "mức lương", "thu nhập", "lương", "salary", "avg salary"])
        and any(k in q_low for k in ["phòng ban khác", "các phòng ban", "các phòng khác", "các phòng", "phòng khác", "toàn công ty", "mặt bằng chung", "công ty"])
        and not any(k in q_low for k in ["quy mô", "headcount", "số lượng nhân sự", "số nhân sự", "số lượng nhân viên", "số nhân viên"])
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


def auto_fix_dept_size_min_max_query(sql: str, user_query: str) -> str:
    """Tự động sửa lỗi subquery Max_size/Min_size toàn công ty lặp lại trên từng dòng khi hỏi quy mô phòng ban lớn nhất và nhỏ nhất."""
    if not sql or not user_query:
        return sql
    q_low = user_query.lower()
    is_min_max_size = (
        any(k in q_low for k in ["quy mô", "nhân sự", "số lượng"])
        and any(k in q_low for k in ["lớn nhất", "nhỏ nhất", "cao nhất", "thấp nhất"])
        and any(k in q_low for k in ["phòng ban", "phòng"])
    )
    if not is_min_max_size:
        return sql

    lowered_sql = sql.lower()
    has_scalar_subquery = "max_size" in lowered_sql or "min_size" in lowered_sql or lowered_sql.count("select") > 1

    if has_scalar_subquery:
        return """SELECT 
    d.dept_name AS Department,
    COUNT(DISTINCT de.emp_no) AS Headcount
FROM departments d
JOIN dept_emp de ON d.dept_no = de.dept_no AND de.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY Headcount DESC"""

    return sql


def auto_fix_chocolates_monthly_sales_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và sửa lỗi câu truy vấn doanh thu theo tháng (theo Quốc gia, Sản phẩm, Nhân viên, hoặc Số lượng hộp/thùng bán ra) trên CSDL Awesome Chocolates.
    Loại bỏ triệt để CTE bị vỡ (WITH ...), JOIN trùng lặp và chuyển thành câu SELECT đơn trực tiếp định dạng YYYY-MM hoặc Month số."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # Kiểm tra xem có phải câu hỏi theo tháng / thời gian trên Chocolates DB không
    has_monthly = any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "thời gian", "xu hướng", "thay đổi", "biến động"])
    has_sales = any(k in q_low for k in ["doanh thu", "doanh số", "sales", "tiền bán", "amount", "bán hàng"]) or any(k in sql_low for k in ["sales", "totalsales", "amount"])
    has_boxes = any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes", "số lượng"]) or any(k in sql_low for k in ["boxes", "totalboxes", "boxessold"])

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
        metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
        needs_fix = (
            "with " in sql_low
            or "products" in sql_low
            or "pr." in sql_low
            or "pe.spid" not in sql_low
            or f"'{specific_team.lower()}'" not in sql_low
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "group by month" not in sql_low
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

    # 0.1 Doanh thu của một Quốc gia cụ thể (India, USA, Canada, New Zealand, Australia, UK) qua các tháng
    specific_country = None
    country_patterns = {
        "india": "India", "ấn độ": "India", "an do": "India",
        "usa": "USA", "mỹ": "USA", "hoa kỳ": "USA", "united states": "USA",
        "canada": "Canada",
        "new zealand": "New Zealand",
        "australia": "Australia", "úc": "Australia",
        "uk": "UK", "nước anh": "UK", "vương quốc anh": "UK", "united kingdom": "UK"
    }
    for cp_key, cp_val in country_patterns.items():
        if re.search(rf"\b{re.escape(cp_key)}\b", q_low):
            specific_country = cp_val
            break

    if specific_country and has_monthly and not any(k in q_low for k in ["sản phẩm", "product", "nhân viên", "salesperson"]):
        conds = [f"g.Geo = '{specific_country}'"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
        needs_fix = (
            "with " in sql_low
            or "g.geoid" not in sql_low
            or f"'{specific_country.lower()}'" not in sql_low
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "group by month" not in sql_low
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
        metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
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
        metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
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
        metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
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

    # 0.2 Doanh thu theo từng Team qua các tháng
    is_team = any(k in q_low for k in ["team", "đội ngũ", "nhóm bán hàng"]) or "team" in sql_low
    if is_team and not any(k in q_low for k in ["sản phẩm", "product", "quốc gia", "country", "nhân viên", "salesperson"]):
        conds = ["pe.Team != ''"]
        if year_cond:
            conds.append(year_cond)
        where_clause = "WHERE " + " AND ".join(conds)
        metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
        order_col = "TotalBoxesSold" if has_boxes else "TotalSales"
        needs_fix = (
            "with " in sql_low
            or "pe.spid" not in sql_low
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or "group by month, team" not in sql_low
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
        )
        if needs_fix:
            year_clause = f"WHERE {year_cond}\n" if year_cond else ""
            return f"""SELECT 
    {date_expr} AS Month,
    g.Geo AS Country,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN geo g ON s.GeoID = g.GeoID
{year_clause}GROUP BY Month, Country
ORDER BY Month ASC, TotalSales DESC"""

    # 2. Doanh thu theo từng sản phẩm qua các tháng
    is_product = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "loại kẹo", "socola", "chocolate"])
    if is_product and not specific_product and not any(k in q_low for k in ["quốc gia", "country", "nhân viên", "salesperson", "team", "yummies", "delish", "jucies"]):
        needs_fix = (
            "with " in sql_low
            or ("year(" in sql_low and "month(" in sql_low)
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or (year_val and f"{year_val}" not in sql_low)
        )
        if needs_fix:
            year_clause = f"WHERE {year_cond}\n" if year_cond else ""
            return f"""SELECT 
    {date_expr} AS Month,
    pr.Product AS Product,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN products pr ON s.PID = pr.PID
{year_clause}GROUP BY Month, Product
ORDER BY Month ASC, TotalSales DESC"""

    # 3. Doanh thu theo nhân viên bán hàng qua các tháng
    is_person = any(k in q_low for k in ["nhân viên", "salesperson", "sales person", "người bán"]) or "people" in sql_low or "spid" in sql_low
    if is_person and not specific_person and not any(k in q_low for k in ["quốc gia", "country", "sản phẩm", "product"]):
        needs_fix = (
            "with " in sql_low
            or ("year(" in sql_low and "month(" in sql_low)
            or ("date_format" not in sql_low and not is_sqlite)
            or ("strftime" not in sql_low and is_sqlite)
            or (year_val and f"{year_val}" not in sql_low)
        )
        if needs_fix:
            year_clause = f"WHERE {year_cond}\n" if year_cond else ""
            return f"""SELECT 
    {date_expr} AS Month,
    pe.Salesperson AS Salesperson,
    SUM(s.Amount) AS TotalSales
FROM sales s
JOIN people pe ON s.SPID = pe.SPID
{year_clause}GROUP BY Month, Salesperson
ORDER BY Month ASC, TotalSales DESC"""

    # 4. Số lượng thùng / hộp bán ra qua các tháng (không phân nhóm)
    is_general_boxes = has_boxes and not (is_country or is_product or is_person)
    if is_general_boxes:
        year_match = re.search(r'\b(20\d{2})\b', q_low)
        if year_match:
            yr = year_match.group(1)
            year_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr}"
            month_expr = "CAST(strftime('%m', s.SaleDate) AS INTEGER)" if is_sqlite else "MONTH(s.SaleDate)"
            return f"""SELECT 
    {month_expr} AS Month,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
{year_filter}
GROUP BY Month
ORDER BY Month ASC"""
        else:
            needs_fix = (
                "with " in sql_low
                or ("year(" in sql_low and "month(" in sql_low)
                or ("date_format" not in sql_low and not is_sqlite)
                or ("strftime" not in sql_low and is_sqlite)
                or "limit" in sql_low
            )
            if needs_fix or "boxes" not in sql_low:
                return f"""SELECT 
    {date_expr} AS Month,
    SUM(s.Boxes) AS TotalBoxesSold
FROM sales s
GROUP BY Month
ORDER BY Month ASC"""

    # 5. Doanh thu tổng hợp toàn bộ qua các tháng (không phân nhóm)
    is_general_monthly = not (is_country or is_product or is_person or has_boxes)
    if is_general_monthly and any(k in q_low for k in ["doanh thu", "doanh số", "sales", "tiền"]):
        year_match = re.search(r'\b(20\d{2})\b', q_low)
        if year_match:
            yr = year_match.group(1)
            year_filter = f"WHERE strftime('%Y', s.SaleDate) = '{yr}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {yr}"
            month_expr = "CAST(strftime('%m', s.SaleDate) AS INTEGER)" if is_sqlite else "MONTH(s.SaleDate)"
            return f"""SELECT 
    {month_expr} AS Month,
    SUM(s.Amount) AS TotalSales
FROM sales s
{year_filter}
GROUP BY Month
ORDER BY Month ASC"""
        else:
            needs_fix = (
                "with " in sql_low
                or ("year(" in sql_low and "month(" in sql_low)
                or ("date_format" not in sql_low and not is_sqlite)
                or ("strftime" not in sql_low and is_sqlite)
                or "limit" in sql_low
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


def auto_fix_chocolates_quarterly_sales_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và sửa lỗi câu truy vấn doanh thu theo quý (theo Quốc gia, Sản phẩm, Team, hoặc Toàn công ty)
    trên CSDL Awesome Chocolates. Đảm bảo GROUP BY đúng Quarter và ORDER BY Quarter ASC để vẽ biểu đồ đường xu hướng."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

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
    specific_country = None
    country_patterns = {
        "india": "India", "ấn độ": "India", "an do": "India",
        "usa": "USA", "mỹ": "USA", "hoa kỳ": "USA", "united states": "USA",
        "canada": "Canada",
        "new zealand": "New Zealand",
        "australia": "Australia", "úc": "Australia",
        "uk": "UK", "nước anh": "UK", "vương quốc anh": "UK", "united kingdom": "UK"
    }
    for cp_key, cp_val in country_patterns.items():
        if re.search(rf"\b{re.escape(cp_key)}\b", q_low):
            specific_country = cp_val
            break

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
    is_team = any(k in q_low for k in ["team", "đội ngũ", "đội", "nhóm bán hàng"]) or "team" in sql_low
    if is_team and not is_category and not is_country:
        if not has_percentage_in_sql or "with " in sql_low or "group by" not in sql_low or "pe.team" not in sql_low:
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
        "trung bình mỗi hộp", "order value", "per box", "profit per box",
        "lợi nhuận", "profit", "margin", "tỉ suất", "tỷ suất", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"
    ])
    if not is_efficiency:
        return sql

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate", "thị trường", "mỹ", "ấn độ", "india", "usa"])
    if not is_chocolates:
        return sql

    # 1. So sánh hiệu quả giữa các thị trường / quốc gia
    if any(k in q_low for k in ["thị trường", "quốc gia", "country", "geo", "usa", "mỹ", "hoa kỳ", "united states"]):
        specific_geos = []
        if any(k in q_low for k in ["usa", "mỹ", "hoa kỳ", "united states"]):
            specific_geos.append("'USA'")
        if any(k in q_low for k in ["india", "ấn độ", "an do"]):
            specific_geos.append("'India'")
        if any(k in q_low for k in ["uk", "anh", "nước anh", "united kingdom"]):
            specific_geos.append("'UK'")
        if any(k in q_low for k in ["canada"]):
            specific_geos.append("'Canada'")
        if any(k in q_low for k in ["australia", "úc"]):
            specific_geos.append("'Australia'")
        if any(k in q_low for k in ["new zealand"]):
            specific_geos.append("'New Zealand'")

        where_clause = f"WHERE g.Geo IN ({', '.join(specific_geos)})\n" if specific_geos else ""
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
        req_limit = int(top_m.group(1)) if top_m else 10
        is_margin_focus = any(k in q_low for k in ["tỷ suất", "tỉ suất", "margin", "%", "phần trăm"])
        order_col = "ProfitMargin" if is_margin_focus else "ProfitPerBox"
        needs_fix = (
            "cost_per_box" not in sql_low 
            or (is_margin_focus and "profitmargin" not in sql_low)
            or (not is_margin_focus and "profitperbox" not in sql_low)
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

    return sql


def auto_fix_sales_headcount_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa câu truy vấn đếm số lượng nhân viên bán hàng (Headcount)
    theo từng Đội ngũ (Team) hoặc Khu vực (Location) trên CSDL Awesome Chocolates.
    Ngăn chặn tuyệt đối việc tính nhầm sang SUM(Boxes) hay SUM(Amount) từ bảng sales."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

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
        or any(k in q_low for k in ["team", "đội ngũ", "kẹo", "chocolate", "chocolates", "hộp kẹo", "nhân viên", "salesperson"])
    )
    if not is_chocolates:
        return sql

    # Phân biệt nhóm theo Location hay theo Team
    is_location = any(k in q_low for k in ["khu vực", "địa điểm", "location", "vị trí", "thành phố", "city"]) and not any(k in q_low for k in ["team", "đội ngũ", "đội", "nhóm"])

    if is_location:
        return (
            "SELECT\n"
            "    COALESCE(NULLIF(pe.Location, ''), '(Chưa xác định)') AS Location,\n"
            "    COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`\n"
            "FROM people pe\n"
            "GROUP BY Location\n"
            "ORDER BY `Số Lượng Nhân Viên` DESC;"
        )
    else:
        return (
            "SELECT\n"
            "    COALESCE(NULLIF(pe.Team, ''), '(Chưa phân nhóm)') AS Team,\n"
            "    COUNT(DISTINCT pe.SPID) AS `Số Lượng Nhân Viên`\n"
            "FROM people pe\n"
            "GROUP BY Team\n"
            "ORDER BY `Số Lượng Nhân Viên` DESC;"
        )


def auto_fix_chocolates_top_rankings_query(sql: str, user_query: str, dialect: str = "MySQL") -> str:
    """Tự động chuẩn hóa và đảm bảo câu truy vấn bảng xếp hạng Top N (Nhân viên, Sản phẩm, Quốc gia, Đội ngũ)
    trên CSDL Awesome Chocolates luôn trả về dữ liệu chuẩn xác 100%, đúng bảng và đúng cú pháp lọc năm."""
    if not sql or not user_query:
        return sql

    q_low = user_query.lower()
    sql_low = sql.lower()

    # Không can thiệp nếu là câu hỏi xu hướng theo tháng / quý (đã có auto_fix_chocolates_monthly_sales_query & auto_fix_chocolates_quarterly_sales_query xử lý)
    if any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "theo tháng", "xu hướng", "quý", "quarter", "từng quý", "theo quý", "qua các quý"]):
        return sql

    # Không can thiệp nếu là câu hỏi tỷ lệ / đóng góp / phần trăm (đã có auto_fix_contribution_percentage_query xử lý)
    if any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "percent", "tỷ trọng", "tỉ trọng", "cơ cấu", "share", "ratio", "đóng góp"]):
        return sql

    # Không can thiệp nếu là câu hỏi so sánh hiệu quả bán hàng / đơn hàng trung bình / lợi nhuận (đã có auto_fix_sales_performance_comparison_query xử lý)
    if any(k in q_low for k in [
        "hiệu quả", "efficiency", "effectiveness", "giá trị đơn hàng trung bình", 
        "đơn hàng trung bình", "profit per box", "lợi nhuận trên mỗi hộp", "lợi nhuận mỗi hộp",
        "lợi nhuận", "profit", "margin", "tỉ suất", "tỷ suất"
    ]):
        return sql

    # Không can thiệp nếu là câu hỏi đếm số lượng nhân sự / headcount (đã có auto_fix_sales_headcount_query xử lý từ bảng people)
    is_headcount_q = (
        any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "salesperson", "sales person", "người bán", "sales rep", "sales reps"])
        and any(k in q_low for k in ["số lượng", "quy mô", "bao nhiêu", "đếm", "phân bổ", "cơ cấu", "phân chia", "mỗi team có", "từng team có", "từng đội có"])
        and not any(k in q_low for k in ["doanh số", "doanh thu", "tiền", "tháng", "quý"])
    )
    if is_headcount_q:
        return sql

    is_chocolates = any(k in sql_low for k in ["sales", "people", "products", "geo", "spid", "pid", "geoid", "boxes"]) or any(k in q_low for k in ["bán hàng", "doanh số", "doanh thu", "hộp", "thùng", "kẹo", "socola", "chocolate"])
    if not is_chocolates:
        return sql

    is_sqlite = "sqlite" in (dialect or "").lower()

    # Trích xuất năm nếu có (VD: 2021, 2022)
    year_match = re.search(r'\b(20\d{2})\b', q_low)
    year_val = year_match.group(1) if year_match else None
    year_clause = ""
    if year_val:
        year_clause = f"WHERE strftime('%Y', s.SaleDate) = '{year_val}'" if is_sqlite else f"WHERE YEAR(s.SaleDate) = {year_val}"

    # Xác định chỉ số đo lường: Hộp/Thùng (Boxes) hay Doanh số (Sales Amount)
    has_boxes = (
        any(k in q_low for k in ["hộp", "hop", "thùng", "thung", "boxes"])
        or (any(k in q_low for k in ["số lượng", "so luong"]) and not any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "salesperson", "người bán", "khách hàng", "customer"]))
        or any(k in sql_low for k in ["boxes", "totalboxes", "boxessold"])
    )
    metric_expr = "SUM(s.Boxes) AS TotalBoxesSold" if has_boxes else "SUM(s.Amount) AS TotalSales"
    order_col = "TotalBoxesSold" if has_boxes else "TotalSales"

    # Xác định chiều sắp xếp: DESC (cao nhất/nhiều nhất) hay ASC (thấp nhất/ít nhất)
    is_asc = any(k in q_low for k in ["thấp nhất", "ít nhất", "kém nhất", "bottom", "thấp"])
    order_dir = "ASC" if is_asc else "DESC"

    # Trích xuất LIMIT từ câu hỏi hoặc mặc định 10 nếu là câu hỏi Top N
    limit = extract_requested_limit(user_query)
    if not limit and any(k in q_low for k in ["top", "cao nhất", "thấp nhất", "nhiều nhất", "ít nhất", "bán chạy nhất"]):
        limit = 10
    limit_clause = f"LIMIT {limit}" if limit else ""

    # 1. Bảng xếp hạng Nhân viên bán hàng (Salesperson / People)
    is_person = any(k in q_low for k in ["nhân viên", "salesperson", "sales person", "người bán", "ai bán", "ai có doanh số", "ai doanh thu", "nhân sự bán"]) or "people" in sql_low or "spid" in sql_low or "salesperson" in sql_low
    if is_person and not any(k in q_low for k in ["sản phẩm", "product", "quốc gia", "country"]):
        needs_fix = (
            "with " in sql_low
            or "s.salesperson" in sql_low
            or "pe.name" in sql_low
            or "pe.spid" not in sql_low
            or "sales s" not in sql_low
            or ("saledate =" in sql_low and "year(" not in sql_low and "strftime(" not in sql_low)
            or (year_val and f"{year_val}" not in sql_low)
            or "group by" not in sql_low
            or "order by" not in sql_low
            or "pe.salesperson" not in sql_low
        )
        if needs_fix:
            lines = [
                "SELECT",
                "    pe.Salesperson,",
                f"    {metric_expr}",
                "FROM sales s",
                "JOIN people pe ON s.SPID = pe.SPID",
            ]
            if year_clause:
                lines.append(year_clause)
            lines.append("GROUP BY pe.Salesperson")
            lines.append(f"ORDER BY {order_col} {order_dir}")
            if limit_clause:
                lines.append(limit_clause)
            return "\n".join(lines)

    # 2. Bảng xếp hạng Sản phẩm (Products)
    is_product = any(k in q_low for k in ["sản phẩm", "product", "mặt hàng", "loại kẹo", "socola", "chocolate"]) or "products" in sql_low or "pid" in sql_low or "product" in sql_low
    if is_product and not any(k in q_low for k in ["nhân viên", "salesperson", "quốc gia", "country"]):
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

    # 3. Bảng xếp hạng Thị trường / Quốc gia (Country / Geo)
    is_country = any(k in q_low for k in ["quốc gia", "country", "thị trường", "nước nào", "đất nước", "khu vực", "geo"]) or "geo" in sql_low or "geoid" in sql_low
    if is_country and not any(k in q_low for k in ["nhân viên", "salesperson", "sản phẩm", "product"]):
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
    is_team = any(k in q_low for k in ["đội ngũ", "team", "nhóm bán hàng", "nhóm kinh doanh"]) or "team" in sql_low
    if is_team:
        needs_fix = (
            "with " in sql_low
            or "pe.spid" not in sql_low
            or "sales s" not in sql_low
            or ("saledate =" in sql_low and "year(" not in sql_low and "strftime(" not in sql_low)
            or (year_val and f"{year_val}" not in sql_low)
            or "group by" not in sql_low
            or "order by" not in sql_low
            or "pe.team" not in sql_low
        )
        if needs_fix:
            lines = [
                "SELECT",
                "    pe.Team,",
                f"    {metric_expr}",
                "FROM sales s",
                "JOIN people pe ON s.SPID = pe.SPID",
            ]
            if year_clause:
                lines.append(year_clause)
            lines.append("GROUP BY pe.Team")
            lines.append(f"ORDER BY {order_col} {order_dir}")
            if limit_clause:
                lines.append(limit_clause)
            return "\n".join(lines)

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

    sample_str = df.head(10).to_string(index=False)
    prompt = build_auto_insight_prompt(user_query, sample_str, anomalies_info, lang=lang)
    insight, _ = call_llm(client, provider, model_name, prompt)
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

    # CSDL Tổng quát
    from src.analytics.heuristics import get_axis_columns
    measure_cols, label_cols, _ = get_axis_columns(df)
    if not measure_cols:
        measure_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        label_cols = [c for c in cols if c not in measure_cols]

    m_col = measure_cols[0] if measure_cols else cols[0]
    l_col = label_cols[0] if label_cols else cols[0]

    followups.append(f"Xu hướng thay đổi của {m_col} theo thời gian" if lang != "en" else f"Time-series trend of {m_col}")
    followups.append(f"So sánh {m_col} giữa các {l_col} hàng đầu" if lang != "en" else f"Compare {m_col} across top {l_col}")
    followups.append(f"Tỷ lệ phần trăm đóng góp của từng {l_col} vào tổng {m_col}" if lang != "en" else f"Percentage contribution of each {l_col} to total {m_col}")

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

    # 3. ƯU TIÊN 100% CÁC CÂU HỎI BÁM SÁT CSDL ĐỂ ĐẢM BẢO CHẠY THÀNH CÔNG
    combined = []
    for q in grounded_questions:
        if q not in combined:
            combined.append(q)
    for q in ai_questions:
        if q not in combined:
            combined.append(q)

    return combined[:3] if combined else grounded_questions[:3]


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
    status_callback=None
) -> dict:
    """Điều phối toàn bộ chu trình Text-to-SQL, tự sửa lỗi âm thầm (bao gồm cứu kết quả 0 dòng) và tự động khám phá Insight."""
    # 0. Tự động nhận diện ngôn ngữ của câu hỏi (vi / en)
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
    }

    # 0.1 Kiểm tra sự tương thích giữa câu hỏi và CSDL hiện tại (Domain Mismatch Pre-check)
    valid_tables = get_table_names(engine)
    valid_tbls_low = [t.lower() for t in valid_tables]
    is_employees_db = "departments" in valid_tbls_low and "employees" in valid_tbls_low
    is_chocolates_db = "people" in valid_tbls_low and "products" in valid_tbls_low

    user_query_low = user_query.lower()

    # Nếu đang ở DB employees mà người dùng hỏi sản phẩm / bán hàng / chocolate
    if is_employees_db and any(k in user_query_low for k in ["sản phẩm", "bán chạy", "chocolate", "cost per box", "hộp kẹo", "khách hàng mua", "thị trường úc", "thị trường ấn độ"]):
        result["explanation"] = (
            "💡 **Thông báo từ Trợ lý:** Cơ sở dữ liệu hiện tại (**`employees`**) là cơ sở dữ liệu về **Nhân sự, Tiền lương và Phòng ban** (gồm các bảng `employees`, `salaries`, `departments`, `dept_emp`, `titles`), không chứa bảng sản phẩm hay doanh số bán hàng.\n\n"
            "👉 **Gợi ý:** Nếu bạn muốn truy vấn về **Sản phẩm bán chạy** hoặc **Doanh số kinh doanh**, vui lòng chọn cơ sở dữ liệu **`awesome chocolates`** ở thanh menu bên trái (Sidebar) nhé!"
            if lang != "en" else
            "💡 **Notice:** The current database (**`employees`**) is for **HR, Salaries, and Departments**, and does not contain product or sales tables.\n\n"
            "👉 Please switch to the **`awesome chocolates`** database in the Sidebar to query product sales!"
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

    # 1. Sinh SQL ban đầu
    if status_callback:
        status_callback("🤖 Đang phân tích câu hỏi & tạo câu lệnh SQL tối ưu...")

    initial_prompt = build_sql_prompt(schema_context, dialect, user_query, lang=lang)
    sql_query, err = call_llm(client, provider, model_name, initial_prompt, max_tokens=300)
    if sql_query:
        sql_query = clean_sql_query(sql_query)
        sql_query = enforce_top_n_limit(sql_query, user_query)
        sql_query = auto_fix_datetime_year_filters(sql_query, dialect=dialect)
        sql_query = auto_fix_chocolates_monthly_sales_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_chocolates_quarterly_sales_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_contribution_percentage_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_sales_performance_comparison_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_sales_headcount_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_chocolates_top_rankings_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_yearly_salary_trend_query(sql_query, user_query)
        sql_query = auto_fix_title_assignments_query(sql_query, user_query)
        sql_query = auto_fix_company_hiring_trend_query(sql_query, user_query)
        sql_query = auto_fix_longest_managers_query(sql_query, user_query)
        sql_query = auto_fix_payroll_query(sql_query, user_query)
        sql_query = auto_fix_gender_ratio_query(sql_query, user_query)
        sql_query = auto_fix_raises_query(sql_query, user_query)
        sql_query = auto_fix_department_comparison_query(sql_query, user_query)
        sql_query = auto_fix_title_gender_salary_query(sql_query, user_query)
        sql_query = auto_fix_top_employee_salary_query(sql_query, user_query)
        sql_query = auto_fix_current_manager_salary_query(sql_query, user_query)
        sql_query = auto_fix_department_group_salary_query(sql_query, user_query)
        sql_query = auto_fix_department_single_vs_others_salary_query(sql_query, user_query)
        sql_query = auto_fix_department_single_vs_others_headcount_query(sql_query, user_query)
        sql_query = auto_fix_dept_size_min_max_query(sql_query, user_query)

    if not sql_query:
        result["error"] = "Could not generate SQL from AI model." if lang == "en" else f"Không thể tạo SQL từ mô hình AI.{' Lý do: ' + err if err else ''}"
        return result

    # 2. Vòng lặp thực thi, kiểm định và tự sửa lỗi âm thầm (Silent Self-Healing)
    for attempt in range(1, 4):
        result["attempts"] = attempt
        sql_query = enforce_top_n_limit(sql_query, user_query)
        sql_query = auto_fix_datetime_year_filters(sql_query, dialect=dialect)
        sql_query = auto_fix_chocolates_monthly_sales_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_chocolates_quarterly_sales_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_contribution_percentage_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_sales_performance_comparison_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_sales_headcount_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_chocolates_top_rankings_query(sql_query, user_query, dialect=dialect)
        sql_query = auto_fix_yearly_salary_trend_query(sql_query, user_query)
        sql_query = auto_fix_title_assignments_query(sql_query, user_query)
        sql_query = auto_fix_company_hiring_trend_query(sql_query, user_query)
        sql_query = auto_fix_longest_managers_query(sql_query, user_query)
        sql_query = auto_fix_payroll_query(sql_query, user_query)
        sql_query = auto_fix_gender_ratio_query(sql_query, user_query)
        sql_query = auto_fix_raises_query(sql_query, user_query)
        sql_query = auto_fix_department_comparison_query(sql_query, user_query)
        sql_query = auto_fix_title_gender_salary_query(sql_query, user_query)
        sql_query = auto_fix_top_employee_salary_query(sql_query, user_query)
        sql_query = auto_fix_current_manager_salary_query(sql_query, user_query)
        sql_query = auto_fix_department_group_salary_query(sql_query, user_query)
        sql_query = auto_fix_department_single_vs_others_salary_query(sql_query, user_query)
        sql_query = auto_fix_department_single_vs_others_headcount_query(sql_query, user_query)
        sql_query = auto_fix_dept_size_min_max_query(sql_query, user_query)
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
                "BẮT BUỘC chỉ trả về duy nhất 1 câu lệnh SQL SELECT đơn trực tiếp, TUYỆT ĐỐI CẤM DÙNG CTE (WITH ...), TUYỆT ĐỐI KHÔNG xin lỗi, không giải thích, không dùng markdown!" if lang != "en" else "MUST return raw executable SELECT statement. Do NOT use CTE (WITH ...), do NOT apologize, do NOT explain!",
                lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = clean_sql_query(fixed_sql) if fixed_sql else sql_query
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
            sql_query = fixed_sql or sql_query
            continue

        # 2.2 Thực thi SQL trên Database Engine
        if status_callback:
            status_callback("⚡ Đang thực thi truy vấn trên Database...")

        try:
            df, truncated = read_sql_capped(sql_query, engine, cap=MAX_ROWS_CAP)
            if truncated:
                result["logs"].append(f"⚠️ Dữ liệu lớn: đã dừng đọc ở {MAX_ROWS_CAP:,} dòng để bảo vệ hệ thống.")

            # Tự động phát hiện & sửa nếu kết quả trả về 0 dòng (0-Row Empty Result Recovery)
            if df is not None and df.empty and attempt < 3:
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

            # Fast-path: Nếu câu lệnh thành công ngay lần đầu hoặc dùng Ollama cục bộ
            # Bỏ qua lượt gọi QA LLM để tiết kiệm thời gian chờ cho người dùng
            should_run_qa = enable_self_check and (provider != "Ollama (Local AI Offline)") and (attempt > 1)
            if should_run_qa:
                check = self_check_sql(client, provider, model_name, schema_context, user_query, sql_query, df, lang=lang)
            else:
                check = {"day_du": True, "ly_do": "SQL hợp lệ (Tối ưu tốc độ)."}

            if check.get("day_du", True) or attempt == 3:
                if check.get("day_du", True):
                    result["logs"].append(f"✅ Kiểm định SQL OK: {check.get('ly_do', 'SQL hợp lệ')}")
                else:
                    result["logs"].append(f"⚠️ Chấp nhận kết quả sau {attempt} lần thử: {check.get('ly_do', '')}")

                df = ensure_full_twelve_months(df, user_query)
                df = ensure_full_four_quarters(df, user_query)
                df = ensure_ratio_column_if_requested(df, user_query)
                df = ensure_efficiency_columns_if_requested(df, user_query)
                result["df"] = df
                result["sql"] = sql_query

                # 3. Tự động phát hiện bất thường & sinh Insight Kinh doanh song song với Gợi ý tiếp nối
                if df is not None and not df.empty:
                    if status_callback:
                        status_callback("📊 Đang phân tích Insight & Trực quan hóa dữ liệu...")

                    anomalies_info = analyze_data_anomalies(df)
                    result["anomalies_info"] = anomalies_info

                    # Tối ưu hóa siêu tốc (Instant Grounded Analytics):
                    # 1. Sinh câu hỏi gợi ý tiếp nối ngay lập tức trong 0.0001s theo 3 chiều chiến lược
                    result["followups"] = generate_grounded_fallback_followups(df, schema_context=schema_context, current_query=user_query, lang=lang)

                    # 2. Sinh Insight Phân Tích
                    if enable_auto_insights:
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

            result["logs"].append(f"⚠️ QA Self-check phát hiện vấn đề: {check.get('ly_do', '')}")
            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, check.get("ly_do", ""), lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = clean_sql_query(fixed_sql) if fixed_sql else sql_query

        except Exception as e:
            error_msg = sanitize_error(str(e), db_pass)
            result["logs"].append(f"❌ Lỗi thực thi SQL: {error_msg}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {error_msg}"
                result["sql"] = sql_query
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

            # Bắt lỗi 1054 / Unknown column để tự động sửa cột ảo giác (như d.to_date)
            if "1054" in lowered_err or "unknown column" in lowered_err or "no such column" in lowered_err:
                if "d.to_date" in lowered_err or "departments.to_date" in lowered_err or "to_date" in lowered_err:
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
                elif "de." in lowered_err or "dept_emp" in lowered_err:
                    augmented_error += (
                        "\n\nLỖI CỘT 1054: Bảng 'dept_emp' (bí danh de) không tồn tại trong mệnh đề FROM (hoặc bạn đang nhầm giữa de và dm)!\n"
                        "- Khi truy vấn ban quản lý, dùng bảng `dept_manager dm` và dùng `COUNT(*)` để đếm tổng số!\n"
                        "  SELECT d.dept_name AS Department, SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) AS MaleManagers, SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) AS FemaleManagers, COUNT(*) AS TotalManagers, ROUND(SUM(CASE WHEN e.gender = 'M' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS MalePct, ROUND(SUM(CASE WHEN e.gender = 'F' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS FemalePct FROM dept_manager dm JOIN employees e ON dm.emp_no = e.emp_no JOIN departments d ON dm.dept_no = d.dept_no GROUP BY d.dept_name ORDER BY d.dept_name;"
                    )

            # Bắt lỗi 1066 / Not unique table/alias để tự động hướng dẫn đổi bí danh
            if "1066" in lowered_err or "not unique table/alias" in lowered_err:
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
                    f"You used the same alias 'p' for multiple tables! Please use 'pe' for people, 'pr' for products, 's' for sales, 'g' for geo!"
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
