"""
Bộ chọn Ví dụ Mẫu Động (Dynamic Few-Shot Selector) cho Text-to-SQL.
Thiết kế tối ưu:
- 0 MB RAM overhead (Pure Python, không phụ thuộc thư viện nặng như torch/transformers).
- Độ trễ siêu tốc (< 1ms).
- Tự động nhận diện ngữ cảnh CSDL (Domain Alignment).
- Kết hợp Lexical Token Overlap + Intent Tags Matching để trích xuất 2 ví dụ chuẩn mực nhất.
- Tự động chọn đúng Dialect (MySQL hoặc SQLite) cho câu SQL mẫu.
"""

import re
from src.llm.few_shots_data import FEW_SHOT_EXAMPLES

# Stop words cơ bản trong câu hỏi truy vấn dữ liệu kinh doanh tiếng Việt & tiếng Anh
STOP_WORDS = {
    "là", "của", "và", "các", "những", "cho", "tôi", "hãy", "xem", "lấy", "tìm", "biết", "với", "trong",
    "có", "được", "ra", "ở", "tại", "theo", "từng", "nào", "mấy", "bao", "nhiêu", "gì", "thế", "này",
    "đó", "về", "giữa", "toàn", "bộ", "hết", "show", "me", "find", "get", "list", "the", "and", "of", "in",
    "for", "with", "by", "to", "what", "which", "how", "many", "all"
}


def tokenize(text: str) -> set[str]:
    """Tách từ đơn giản và loại bỏ stop words."""
    if not text:
        return set()
    words = re.findall(r"[\w%]+", text.lower())
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}


def detect_database_domain(schema_context: str) -> str:
    """Phân loại CSDL hiện tại: 'employees', 'awesome_chocolates', hoặc 'generic'."""
    s_low = (schema_context or "").lower()
    
    is_employees = any(k in s_low for k in ["dept_emp", "dept_manager", "salaries", "titles", "birth_date", "emp_no"])
    is_choco = any(k in s_low for k in ["spid", "geoid", "boxes", "cost_per_box", "category", "salesperson"]) or (
        "`sales`" in s_low and "`products`" in s_low
    )
    
    if is_employees and not is_choco:
        return "employees"
    elif is_choco:
        return "awesome_chocolates"
    return "generic"


def score_few_shot_relevance(user_query: str, example: dict) -> float:
    """Chấm điểm độ tương đồng giữa câu hỏi người dùng và ví dụ mẫu.
    Score = Token Overlap (0.4) + Tag Match (0.4) + Intent Pattern Match (0.2).
    """
    q_low = (user_query or "").lower()
    q_tokens = tokenize(user_query)
    if not q_tokens:
        return 0.0

    ex_question = example.get("question", "")
    ex_question_en = example.get("question_en", "")
    ex_tokens = tokenize(ex_question) | tokenize(ex_question_en)

    # 1. Token Overlap (Jaccard-like score)
    common_tokens = q_tokens & ex_tokens
    token_score = (len(common_tokens) / max(len(q_tokens), 1)) * 40.0

    # 2. Tag Matching
    tag_score = 0.0
    matched_tags = 0
    for tag in example.get("tags", []):
        t_low = tag.lower()
        if t_low in q_low:
            matched_tags += 1
            # Các từ khóa nghiệp vụ đặc thù có trọng số cao
            if any(k in t_low for k in ["mỗi hộp sô-cô-la", "thị trường úc", "giá trung bình mỗi hộp", "mỗi hộp mang về", "đơn hàng lớn", "trên 1000 hộp", "trên 1,000 hộp", "từ 1000 hộp", "từ 1,000 hộp", "hộp trở lên", "nhóm đơn hàng lớn", "đạt sản lượng từ", "số lượng đơn hàng", "tổng doanh thu từ các đơn hàng", "đơn hàng bán được trên", "chênh lệch", "top 5", "tất cả các quý", "tỷ suất", "margin", "hoa hồng", "12 tháng", "quốc gia", "tăng lương", "biên độ", "dao động", "giá bán trung bình", "thị trường quốc gia", "giá trị đơn hàng trung bình", "trung bình trên mỗi giao dịch", "sản phẩm chủ lực", "mặt hàng chủ lực", "tăng trưởng trên", "so với quý", "quý 4/2021", "quý 3/2021", "bán chạy nhất", "ế ẩm", "ế nhất", "nghịch lý", "rank divergence", "chưa từng", "chưa bao giờ", "không bán", "chưa bán", "anti-join", "not in", "riêng team", "team delish", "canada", "nhóm bars", "multi-dimensional segment", "top 5 giao dịch", "chi tiết giao dịch", "không group by", "từng nhân viên"]):
                tag_score += 25.0
            else:
                tag_score += 15.0

    # 3. Intent Pattern Matching
    intent_score = 0.0
    cat = example.get("category", "")
    if cat == "top_transactions" and any(k in q_low for k in ["giao dịch", "đơn hàng", "orders", "transactions"]) and any(k in q_low for k in ["top", "cao nhất", "lớn nhất", "nhiều nhất", "giá trị nhất", "giá trị đơn hàng cao nhất"]):
        intent_score += 75.0
    elif cat == "team_salespeople" and (
        any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "từng người", "từng nhân viên"])
        and (
            any(k in q_low for k in ["delish", "yummies", "jucies", "team", "đội ngũ"])
            or any(k in q_low for k in ["doanh số", "doanh thu", "số hộp", "hộp"])
        )
    ):
        intent_score += 70.0
    elif cat == "multi_dim_segment" and (
        (
            any(k in q_low for k in ["delish", "yummies", "jucies", "riêng team", "team"])
            and any(k in q_low for k in ["canada", "india", "usa", "uk", "new zealand", "australia", "thị trường"])
            and any(k in q_low for k in ["bars", "bites", "category", "nhóm", "loại"])
        )
        or (
            any(k in q_low for k in ["canada", "india", "usa", "uk", "new zealand", "australia", "thị trường", "hai thị trường"])
            and any(k in q_low for k in ["bars", "bites", "category", "nhóm", "loại"])
            and any(k in q_low for k in ["đơn hàng", "orders", "500", "1000", "quy mô"])
        )
    ):
        intent_score += 65.0
    elif cat == "salesperson_avg_price_per_box" and any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "người bán", "ai"]) and any(k in q_low for k in ["đơn giá", "đơn giá trung bình", "giá trung bình", "mỗi hộp", "bình quân mỗi hộp", "trung bình mỗi hộp", "avg price per box"]):
        intent_score += 65.0
    elif cat == "avg_price_per_box" and any(k in q_low for k in ["mỗi hộp", "từng hộp", "bình quân mỗi hộp", "trung bình mỗi hộp", "price per box", "avg price per box", "giá bán trung bình", "đơn giá trung bình"]) and any(k in q_low for k in ["tiền", "giá", "$", "mang về", "bao nhiêu", "thu về"]):
        intent_score += 55.0
    elif cat == "order_threshold_aggregation" and any(k in q_low for k in ["đơn hàng", "giao dịch", "orders", "order", "nhóm đơn"]) and any(k in q_low for k in ["trên", "hơn", "vượt", ">", "từ", "trở lên", ">=", "ít nhất", "tối thiểu"]) and any(c.isdigit() for c in q_low):
        if any(k in q_low for k in ["canada", "india", "usa", "uk", "new zealand", "australia", "bars", "bites", "category", "top", "hiển thị ngày bán"]):
            intent_score -= 35.0
        else:
            intent_score += 55.0
    elif cat == "anti_join" and any(k in q_low for k in ["chưa từng", "chưa bao giờ", "không bán", "chưa bán", "không có đơn", "never"]):
        intent_score += 45.0
    elif cat == "market_divergence" and any(k in q_low for k in ["bán chạy", "cao nhất", "top", "dẫn đầu"]) and any(k in q_low for k in ["ế ẩm", "ế nhất", "thấp nhất", "kém nhất", "nghịch lý", "nhưng lại", "phân hóa", "divergence"]):
        intent_score += 45.0
    elif cat == "price_spread" and any(k in q_low for k in ["biên độ", "dao động", "chênh lệch", "spread", "khoảng cách"]) and any(k in q_low for k in ["giá", "price", "đơn giá"]):
        intent_score += 35.0
    elif cat == "salesperson_aov" and any(k in q_low for k in ["giá trị đơn hàng trung bình", "đơn hàng trung bình", "aov", "mỗi giao dịch"]) and any(k in q_low for k in ["nhân sự", "sales person", "salesperson", "người bán", "ai là"]):
        if any(k in q_low for k in ["top 5 giao dịch", "thông tin top", "hiển thị ngày bán"]):
            intent_score -= 35.0
        else:
            intent_score += 35.0
    elif cat == "team_flagship_product" and any(k in q_low for k in ["sản phẩm chủ lực", "mặt hàng chủ lực", "chủ lực của họ", "chủ lực"]) and any(k in q_low for k in ["team", "đội ngũ", "nhóm"]):
        intent_score += 35.0
    elif cat == "quarterly_growth" and any(k in q_low for k in ["tăng trưởng", "growth", "tăng"]) and any(k in q_low for k in ["quý", "quarter", "q4", "q3", "so với"]):
        intent_score += 35.0
    elif cat == "salary_spread" and any(k in q_low for k in ["chênh lệch", "khoảng cách", "spread", "gap"]):
        intent_score += 20.0
    elif cat == "quarterly_consistency" and any(k in q_low for k in ["tất cả các quý", "4 quý", "các quý", "quý nào cũng", "luôn nằm trong"]):
        intent_score += 30.0
    elif cat == "margin_pnl" and any(k in q_low for k in ["tỷ suất", "tỉ suất", "margin", "lợi nhuận", "giá vốn", "cogs"]):
        intent_score += 25.0
    elif cat == "team_comparison" and any(k in q_low for k in ["team", "đội ngũ", "các team"]) and any(k in q_low for k in ["doanh số", "hộp", "boxes", "so sánh"]):
        if any(k in q_low for k in ["riêng team", "thị trường", "canada", "bars", "bites", "nhân viên", "nhân sự", "salesperson", "từng nhân viên", "từng người", "delish", "yummies", "jucies", "giao dịch", "đơn hàng"]):
            intent_score -= 50.0
        else:
            intent_score += 25.0
    elif cat == "window_function" and any(k in q_low for k in ["top 10%", "top 1 mỗi", "nhất của từng", "dẫn đầu từng"]):
        intent_score += 20.0
    elif cat == "time_series" and any(k in q_low for k in ["gần nhất", "12 tháng", "qua các tháng", "theo năm", "xu hướng"]):
        intent_score += 20.0
    elif cat == "threshold" and any(k in q_low for k in ["vượt mức", "trên", "hơn", "đạt từ", "ngưỡng"]) and any(c.isdigit() for c in q_low):
        intent_score += 20.0

    total_score = token_score + tag_score + intent_score
    return total_score


def select_dynamic_few_shots(user_query: str, schema_context: str = "", dialect: str = "MySQL", top_k: int = 2) -> list[dict]:
    """Lựa chọn top_k ví dụ mẫu chuẩn mực tương đồng nhất với câu hỏi người dùng."""
    if not user_query:
        return []

    target_domain = detect_database_domain(schema_context)
    is_sqlite = "sqlite" in (dialect or "").lower()

    # Lọc ví dụ theo Domain CSDL (ưu tiên các ví dụ cùng domain nếu xác định được)
    candidate_examples = []
    for ex in FEW_SHOT_EXAMPLES:
        # Nếu đã xác định rõ domain (employees vs awesome_chocolates), chỉ chọn ví dụ thuộc domain đó
        if target_domain in ("employees", "awesome_chocolates"):
            if ex.get("domain") == target_domain:
                candidate_examples.append(ex)
        else:
            candidate_examples.append(ex)

    if not candidate_examples:
        candidate_examples = FEW_SHOT_EXAMPLES

    # Chấm điểm và sắp xếp
    scored_examples = []
    for ex in candidate_examples:
        score = score_few_shot_relevance(user_query, ex)
        scored_examples.append((score, ex))

    scored_examples.sort(key=lambda x: x[0], reverse=True)

    # Chọn top K ví dụ có điểm số cao nhất
    selected = []
    for score, ex in scored_examples[:top_k]:
        # Sao chép và chọn đúng câu SQL theo dialect
        ex_copy = dict(ex)
        ex_copy["selected_sql"] = ex.get("sql_sqlite" if is_sqlite else "sql_mysql", "").strip()
        ex_copy["relevance_score"] = round(score, 2)
        selected.append(ex_copy)

    return selected


def format_few_shots_for_prompt(selected_examples: list[dict], dialect: str = "MySQL", lang: str = "vi") -> str:
    """Format danh sách ví dụ được chọn thành khối hướng dẫn chuẩn mực nhúng vào System Prompt."""
    if not selected_examples:
        return ""

    is_en = (lang == "en")
    
    if is_en:
        lines = [
            "\n=== GROUND TRUTH FEW-SHOT EXAMPLES (PATTERNS TO EMULATE) ===",
            "Below are high-quality reference SQL queries designed for similar complex tasks on this database.",
            "Carefully follow their CTE decomposition logic, column joins, and syntax discipline:\n"
        ]
        for i, ex in enumerate(selected_examples, 1):
            lines.append(f"[Example {i}]")
            lines.append(f"• Target Goal: {ex.get('intent_explanation', '')}")
            lines.append(f"• Similar Question: \"{ex.get('question_en', ex.get('question', ''))}\"")
            lines.append(f"• Gold Standard SQL ({dialect}):")
            lines.append(ex.get("selected_sql", ""))
            lines.append("")
        lines.append("============================================================\n")
        return "\n".join(lines)

    lines = [
        "\n=== VÍ DỤ MẪU CHUẨN MỰC THỰC TẾ (GROUND TRUTH FEW-SHOT EXAMPLES) ===",
        "Dưới đây là các câu truy vấn SQL mẫu chuẩn mực đã được tối ưu hóa cấu trúc cho các bài toán tương tự.",
        "HÃY BẮT CHƯỚC theo cách phân rã CTE, cách JOIN khóa chính/ngoại và cú pháp chuẩn mực dưới đây:\n"
    ]
    for i, ex in enumerate(selected_examples, 1):
        lines.append(f"[Ví dụ {i}]")
        lines.append(f"• Ý đồ nghiệp vụ: {ex.get('intent_explanation', '')}")
        lines.append(f"• Câu hỏi tương tự: \"{ex.get('question', '')}\"")
        lines.append(f"• SQL Chuẩn mực ({dialect}):")
        lines.append(ex.get("selected_sql", ""))
        lines.append("")
    lines.append("====================================================================\n")
    return "\n".join(lines)
