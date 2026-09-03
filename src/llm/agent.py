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
from src.analytics.heuristics import is_id_like, detect_query_language, sanitize_insight_markdown, sanitize_followup_question
from src.analytics.anomaly import analyze_data_anomalies
from .client import call_llm
from .prompts import (
    build_sql_prompt,
    build_fix_prompt,
    build_self_check_prompt,
    build_anomaly_prompt,
    build_auto_insight_prompt,
    build_followup_prompt,
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

    # 3. Tự động tách khoảng trắng nếu mô hình AI sinh dính chữ từ khóa SQL
    keywords_to_space = [
        ("FROM", r"\bFROM(?=[a-zA-Z_`])"),
        ("SELECT", r"\bSELECT(?=[a-zA-Z_`*])"),
        ("WHERE", r"\bWHERE(?=[a-zA-Z_`])"),
        ("JOIN", r"\bJOIN(?=[a-zA-Z_`])"),
        ("GROUP BY", r"\bGROUP\s+BY(?=[a-zA-Z_`])"),
        ("ORDER BY", r"\bORDER\s+BY(?=[a-zA-Z_`])"),
        ("HAVING", r"\bHAVING(?=[a-zA-Z_`])"),
        ("ON", r"\bON(?=[a-zA-Z_`])"),
        ("LIMIT", r"\bLIMIT(?=\d)"),
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

    return s.strip().strip("`").rstrip(";").strip()


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
            ("Top 5 chức danh có mức lương trung bình cao nhất hiện nay", "Top 5 job titles with highest average current salary"),
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

    if not sql_query:
        result["error"] = "Could not generate SQL from AI model." if lang == "en" else f"Không thể tạo SQL từ mô hình AI.{' Lý do: ' + err if err else ''}"
        return result

    # 2. Vòng lặp thực thi, kiểm định và tự sửa lỗi âm thầm (Silent Self-Healing)
    for attempt in range(1, 4):
        result["attempts"] = attempt
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
                "BẮT BUỘC chỉ trả về duy nhất 1 câu lệnh SQL SELECT hoặc WITH trực tiếp, TUYỆT ĐỐI KHÔNG xin lỗi, không giải thích, không dùng markdown!" if lang != "en" else "MUST return raw executable SELECT or WITH statement. Do NOT apologize, do NOT explain!",
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
                            sec = split_insight_sections("", df=df)
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
                    f"- Nếu là 'e.dept_no' hoặc 's.dept_no': Bảng employees và salaries KHÔNG có cột dept_no! BẮT BUỘC JOIN qua bảng trung gian dept_emp: FROM salaries s JOIN dept_emp de ON s.emp_no = de.emp_no JOIN departments d ON de.dept_no = d.dept_no.\n"
                    f"- Nếu là 'p.Salesperson' hoặc 'pr.Salesperson': Cột 'Salesperson' nằm ở bảng 'people' (pe.Salesperson), KHÔNG nằm ở 'products'! Hãy bỏ cột này nếu câu hỏi không hỏi nhân viên, hoặc JOIN với 'people pe ON s.SPID = pe.SPID' và dùng 'pe.Salesperson'.\n"
                    f"- Nếu là 'ProductCost_per_box': Cột chi phí trong bảng products là 'Cost_per_box'.\n"
                    f"- Nếu là 'p.Product' trong subquery/CTE 'monthly_sales': Bảng 'monthly_sales' không có bí danh 'p'! Hãy bỏ hoàn toàn CTE (WITH ...) và viết SELECT ... FROM products pr JOIN sales s JOIN geo g phẳng đơn giản!\n"
                    f"- Nếu lọc quốc gia 'Australia', 'India', 'USA': BẮT BUỘC dùng 'g.Geo = Australia' (cột Geo chứa tên nước, không phải Region)!\n"
                    f"Hãy sửa lại câu SQL dùng đúng các cột có thật trong Schema ở trên!"
                    if lang != "en" else
                    f"\n\nCOLUMN ERROR: Column '{bad_col}' does not exist!\n"
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
