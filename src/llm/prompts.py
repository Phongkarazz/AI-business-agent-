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
    """Xây dựng prompt tạo câu lệnh SQL từ ngôn ngữ tự nhiên với Schema Grounding nghiêm ngặt."""
    dialect_hint = get_dialect_hints(dialect, lang=lang)
    if lang == "en":
        return f"""You are a world-class senior SQL expert.

=== ACTUAL DATABASE SCHEMA ===
{schema_context}
==============================

Dialect Notice: {dialect_hint}

MANDATORY RULES (STRICT COMPLIANCE):
1. SCHEMA GROUNDING: ONLY use tables and columns that explicitly appear in the Schema above.
   - NEVER hallucinate or assume tables not in the schema (such as `employees`, `salaries`, `titles`, `dept_emp`).
   - If the schema has `people` or `salespersons`, use that for staff/sales reps.
   - If the schema has `products`, use that for items/goods.
   - If the schema has `sales`, use that for transactions/revenue/boxes.
   - If the schema has `geo`, use that for countries/regions.
2. HISTORICAL RELATIVE TIME HANDLING:
   - Business databases contain historical data (not real-time today).
   - When the user asks relative time ('last year', 'past year', 'recent', 'past 12 months'):
     + NEVER use `CURRENT_DATE()`, `CURDATE()`, `NOW()` as it will return 0 rows!
     + MUST anchor to the MAX date in the database:
       * MySQL: `WHERE date_col >= DATE_SUB((SELECT MAX(date_col) FROM table_name), INTERVAL 1 YEAR)`
       * SQLite: `WHERE date_col >= date((SELECT MAX(date_col) FROM table_name), '-1 year')`
3. AVOID OVER-FILTERING:
   - When the user mentions general domain terms (e.g., 'boxes of chocolate', 'chocolate sales'): All records represent chocolate, calculate `SUM(Boxes)` or `SUM(Amount)`. DO NOT add `WHERE Category = 'Chocolate'` unless a specific category is requested.
   - For 'boxes'/'quantity': use `SUM(Boxes)`. For 'revenue'/'money': use `SUM(Amount)`.
4. PRECISE SYNTAX:
   - Use `COUNT(*)` or `COUNT(col)`, NEVER `COUNT()`.
   - Perfectly balance all parentheses '(' and ')'.
   - Wrap table/column names in backticks ` if they contain special characters or spaces.
5. CATEGORICAL NULL / BLANK HANDLING:
   - When GROUP BY a category column (like `Team`, `Category`, `Region`):
   - If the user asks about specific groups/teams, use `WHERE col != '' AND col IS NOT NULL` OR `COALESCE(NULLIF(col, ''), 'Unassigned') AS col` to avoid blank unnamed rows.
6. OUTPUT FORMAT:
   - Return ONLY the raw SQL query (starting with SELECT or WITH).
   - NO markdown code block, NO explanations, NO comments (#, --).

User Query: "{user_query}"
SQL Query:"""

    return f"""Bạn là chuyên gia SQL hàng đầu thế giới.

=== SCHEMA CƠ SỞ DỮ LIỆU THỰC TẾ ===
{schema_context}
====================================

Lưu ý Dialect: {dialect_hint}

QUY TẮC BẮT BUỘC (TUÂN THỦ TUYỆT ĐỐI):
1. SCHEMA GROUNDING: CHỈ ĐƯỢC PHÉP SỬ DỤNG CÁC BẢNG VÀ CỘT XUẤT HIỆN TRONG SCHEMA Ở TRÊN.
   - Tuyệt đối KHÔNG tự ý suy đoán hoặc bịa ra các bảng không có trong Schema (như `employees`, `salaries`, `titles`, `dept_emp`).
   - Nếu trong Schema có bảng `people` hoặc `salespersons`, hãy dùng bảng đó cho nhân viên/người bán.
   - Nếu trong Schema có bảng `products`, hãy dùng bảng đó cho sản phẩm.
   - Nếu trong Schema có bảng `sales`, hãy dùng bảng đó cho doanh số/giao dịch/hộp bán.
   - Nếu trong Schema có bảng `geo`, hãy dùng bảng đó cho quốc gia/khu vực.
2. XỬ LÝ THỜI GIAN TRÊN DỮ LIỆU LỊCH SỬ (QUAN TRỌNG):
   - CSDL doanh nghiệp chứa dữ liệu các năm lịch sử (không phải realtime hôm nay).
   - Khi người dùng hỏi các mốc thời gian tương đối ('trong năm qua', 'gần đây', '12 tháng gần nhất', 'năm gần nhất'):
     + TUYỆT ĐỐI KHÔNG dùng `CURRENT_DATE()`, `CURDATE()`, `NOW()` vì sẽ bị 0 dòng dữ liệu!
     + BẮT BUỘC dùng mốc ngày lớn nhất trong dữ liệu:
       * Trên MySQL: `WHERE date_col >= DATE_SUB((SELECT MAX(date_col) FROM table_name), INTERVAL 1 YEAR)`
       * Trên SQLite: `WHERE date_col >= date((SELECT MAX(date_col) FROM table_name), '-1 year')`
3. ĐỐI CHIẾU VÀ KHỚP GIÁ TRỊ THỰC TẾ (STRICT VALUE MAPPING):
   - Luôn đối chiếu tên sản phẩm, danh mục, nhóm, quốc gia người dùng hỏi với "DANH SÁCH GIÁ TRỊ MẪU THỰC TẾ TRONG CSDL" ở Schema trên.
   - Khi lọc theo tên sản phẩm (VD: 'Dark 70%', 'Orange Choco', 'Mint Chip'): BẮT BUỘC dùng tên chính xác trong danh sách mẫu (ví dụ: '70% Dark Bites') hoặc dùng `LIKE '%70% Dark%'` hoặc `LIKE '%Dark%'` linh hoạt, TUYỆT ĐỐI KHÔNG dùng tên tự bịa khiến điều kiện WHERE không khớp và bị 0 dòng!
4. TRÁNH LỌC CỨNG THỪA THÃI (OVER-FILTERING):
   - Khi người dùng hỏi từ ngữ chung của ngành hàng (VD: 'hộp chocolate', 'sản phẩm chocolate', 'bán chocolate'): Toàn bộ các bản ghi trong DB là chocolate, hãy tính `SUM(Boxes)` hoặc `SUM(Amount)` cho toàn bộ sản phẩm. TUYỆT ĐỐI KHÔNG thêm `WHERE Category = 'Chocolate'` hoặc `WHERE Product LIKE '%chocolate%'` trừ khi người dùng chỉ định rõ 1 danh mục cụ thể có trong Schema.
   - Khi hỏi về 'số hộp' / 'hộp': dùng `SUM(Boxes)`. Khi hỏi về 'doanh thu' / 'tiền': dùng `SUM(Amount)`.
5. CÚ PHÁP CHUẨN XÁC:
   - Dùng `COUNT(*)` hoặc `COUNT(column)`, TUYỆT ĐỐI KHÔNG dùng `COUNT()`.
   - Cân đối tuyệt đối số lượng dấu mở ngoặc '(' và đóng ngoặc ')'.
   - Bọc tên bảng và tên cột trong dấu backtick ` nếu có chứa ký tự đặc biệt hoặc khoảng trắng.
6. XỬ LÝ GIÁ TRỊ RỖNG KHI GOM NHÓM (GROUP BY):
   - Khi gom nhóm theo danh mục (như `Team`, `Category`, `Region`...):
   - Nếu câu hỏi hỏi về từng nhóm/team của nhân viên, hãy dùng `WHERE people.Team != '' AND people.Team IS NOT NULL` (nếu chỉ lấy các nhóm chính thức) hoặc dùng `COALESCE(NULLIF(people.Team, ''), 'Chưa phân nhóm') AS Team` để tránh dòng rỗng không có tên.
7. ĐỊNH DẠNG ĐẦU RA:
   - CHỈ TRẢ VỀ DUY NHẤT 1 CÂU LỆNH SQL THUẦN (bắt đầu bằng SELECT hoặc WITH).
   - TUYỆT ĐỐI KHÔNG thêm bất kỳ comment (#, --), không thêm lời giải thích hay markdown code block bên ngoài.

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
2. If result returned 0 rows due to filtering `Category = 'Chocolate'`: Remove it because all products in the DB are chocolate.
3. If 'Table doesn't exist': Strictly use only existing tables listed in the Schema.
4. If syntax error: Use `COUNT(*)`, ensure balanced parentheses ().
5. Return ONLY the single corrected raw SQL query (SELECT or WITH). No markdown, no comments, no explanations."""

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

HƯỚNG DẪN ĐIỀU CHỈNH:
1. Nếu kết quả trả về 0 dòng dữ liệu do dùng CURRENT_DATE(), NOW(), CURDATE() hoặc lọc thời gian quá chặt: Hãy thay thế bằng `(SELECT MAX(date_col) FROM table_name)` làm mốc ngày gần nhất hoặc bỏ điều kiện lọc thời gian để lấy dữ liệu thực tế!
2. Nếu kết quả trả về 0 dòng do lọc `Category = 'Chocolate'`: Hãy bỏ lọc vì toàn bộ sản phẩm trong DB là chocolate.
3. Nếu lỗi 'Table doesn't exist': Hãy nhìn kỹ SCHEMA ở trên và chỉ dùng đúng các bảng có thật trong danh sách.
4. Nếu lỗi cú pháp: Dùng `COUNT(*)`, kiểm tra cân đối dấu ngoặc đơn ().
5. Viết lại câu SQL hoàn chỉnh, chuẩn xác 100%. CHỈ TRẢ VỀ DUY NHẤT CÂU SQL THUẦN (SELECT hoặc WITH), không giải thích, không thêm comment."""


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

    return f"""Bạn là Giám đốc Phân tích Dữ liệu Kinh doanh (Chief BI & Analytics Officer).

Câu hỏi phân tích của người dùng: "{user_query}"
Tổng quan thống kê dữ liệu:
- Số bản ghi: {stats.get('count', 0)}
- Giá trị trung bình (Mean): {stats.get('mean', 0):,.2f}
- Giá trị trung vị (Median): {stats.get('median', 0):,.2f}
- Giá trị nhỏ nhất (Min): {stats.get('min', 0):,.2f} | Lớn nhất (Max): {stats.get('max', 0):,.2f} | Tổng (Sum): {stats.get('total', 0):,.2f}

Dữ liệu mẫu từ kết quả truy vấn:
{df_summary_str}

Các điểm bất thường đã được thuật toán thống kê phát hiện:
- Loại bất thường: {types_text}
- Chi tiết phát hiện:
{findings_text}

YÊU CẦU:
Hãy đưa ra bản báo cáo Insight Kinh doanh ngắn gọn, sâu sắc và mang tính điều hành thực chiến cao (định dạng Markdown):

### 1. 🚨 Phát hiện Bất thường & Xu hướng Chính
(Nêu rõ các điểm đột biến, kỳ tăng/giảm mạnh hoặc rủi ro tập trung nếu có. Đưa ra con số cụ thể).

### 2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng
(Đưa ra 2-3 giả thuyết kinh doanh sát thực tế: mùa vụ, chiến dịch marketing, đứt gãy vận hành, khách hàng VIP, chính sách giá,...).

### 3. 🎯 Đề xuất Hành động (Action Plan)
(Đưa ra 2-3 hành động cụ thể, thiết thực cho nhà quản lý / ban lãnh đạo. BẮT BUỘC gắn nhãn mức độ ưu tiên và khung thời gian thực thi cho từng hành động:
- 🔴 **[Ưu tiên Cao - Thực hiện Ngay / Immediate]**: Hành động khắc phục sự cố hoặc nắm bắt cơ hội cấp bách.
- 🟡 **[Ưu tiên Trung bình - Quý tiếp theo / Next Quarter]**: Chiến lược tối ưu hóa hoạt động trung hạn.
- 🟢 **[Ưu tiên Thấp / Dài hạn - Long-term]**: Định hướng chiến lược bền vững dài hạn.
Mỗi hành động phải nêu rõ chỉ số KPI / kết quả đo lường kỳ vọng).

QUY TẮC ĐỊNH DẠNG VĂN BẢN (BẮT BUỘC):
- Viết hoa, dấu câu và chính tả tiếng Việt chuẩn xác 100%. Tách từ chuẩn (viết "thấp hơn", "cao hơn", "lớn hơn", TUYỆT ĐỐI KHÔNG viết dính liền "thấphơn").
- Định dạng số và chữ in đậm: Viết liền không khoảng cách bên trong dấu sao, ví dụ: **1,299,998** (TUYỆT ĐỐI KHÔNG viết ** 1, 299, 998 ** hoặc * *).
- Phong cách trình bày: Chuyên nghiệp, súc tích, đi thẳng vào trọng tâm kinh doanh, không dùng từ ngữ sáo rỗng."""


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
3. Propose 2 to 3 high-value analytical drill-down questions.

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
   - BẮT BUỘC PHẢI DÙNG TÊN THỰC THỂ CỤ THỂ lấy trực tiếp từ bảng dữ liệu mẫu ở trên (Ví dụ: thay vì "của 3 nhân viên này", hãy ghi rõ: "Top 5 nhân viên có doanh số cao nhất trong nhóm Delish", "Doanh số sản phẩm Dark 70% theo từng tháng", "Doanh thu tại thị trường India").
   - Mỗi câu hỏi phải hoàn toàn ĐỘC LẬP để khi người dùng bấm nút là chạy được ngay mà không phụ thuộc ngữ cảnh trước.
2. RÀNG BUỘC THỜI GIAN TUYỆT ĐỐI:
   - CHỈ đề xuất các câu hỏi cho những NĂM THỰC TẾ có trong phần "KHOẢNG THỜI GIAN THỰC TẾ TRONG DỮ LIỆU" ở Schema trên.
   - TUYỆT ĐỐI KHÔNG tự bịa ra các năm không có trong dữ liệu (ví dụ: không gợi ý năm 2023/2024 nếu dữ liệu chỉ có năm 2021 hoặc 2022).
3. Đề xuất 2 đến 3 câu hỏi đào sâu thông minh, thiết thực và CHẮC CHẮN CÓ DỮ LIỆU TRUY VẤN ĐƯỢC 100%.

Trả về DUY NHẤT một JSON array chứa danh sách các chuỗi câu hỏi:
["Câu hỏi 1", "Câu hỏi 2", "Câu hỏi 3"]"""
