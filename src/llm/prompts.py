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

    return f"""Bạn là chuyên gia SQL hàng đầu thế giới.

=== SCHEMA CƠ SỞ DỮ LIỆU THỰC TẾ ===
{schema_context}
====================================

Lưu ý Dialect: {dialect_hint}

QUY TẮC BẮT BUỘC (TUÂN THỦ TUYỆT ĐỐI):
1. TUÂN THỦ SCHEMA TUYỆT ĐỐI (PURE SCHEMA GROUNDING):
   - CHỈ ĐƯỢC PHÉP SỬ DỤNG các bảng, view và cột xuất hiện thực tế trong SCHEMA ở trên.
   - Tuyệt đối KHÔNG tự ý bịa đặt hoặc sử dụng bất kỳ bảng/cột nào không có trong Schema.
   - BẮT BUỘC KIỂM TRA KỸ TÊN CỘT TRONG SCHEMA KHI TRUY VẤN & JOIN:
     + Bảng nhân sự/người bán (people): Tên người bán là cột `Salesperson`, TUYỆT ĐỐI KHÔNG DÙNG `Name`, `Employee_Name` hay `Employee`! Mã nhân viên là `SPID`, nhóm là `Team`.
     + Bảng sản phẩm (products): Tên sản phẩm là cột `Product`, TUYỆT ĐỐI KHÔNG DÙNG `ProductName`! Mã sản phẩm là `PID`.
     + Bảng bán hàng (sales): Cột người bán là `SPID`, cột sản phẩm là `PID`, cột doanh số là `Amount`.
     + Mối quan hệ liên kết:
       * `people.SPID = sales.SPID`
       * `products.PID = sales.PID`
       * TUYỆT ĐỐI KHÔNG JOIN bảng people trực tiếp với products bằng PID!
     + Để lọc nhân viên trong một nhóm cụ thể (ví dụ nhóm 'Yummies'):
       Chỉ cần: `FROM people p JOIN sales s ON p.SPID = s.SPID WHERE p.Team = 'Yummies' GROUP BY p.Salesperson ORDER BY TotalSales DESC LIMIT 5`
       TUYỆT ĐỐI KHÔNG tự JOIN bảng people 2 lần!
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
   - VỚI CÂU HỎI TOP N / DANH SÁCH / XẾP HẠNG / BẢNG LỚN:
     + Khi người dùng hỏi dạng Top N ('Top 10 nhân sự có doanh số cao nhất'): BẮT BUỘC dùng `ORDER BY TotalSales DESC LIMIT 10`.
     + Khi người dùng hỏi dạng danh sách số nhiều ('Danh sách...', 'Top...', 'Những...', 'Các...') mà không ghi rõ số lượng cụ thể: BẮT BUỘC dùng `LIMIT 10` (hoặc `LIMIT 5`), TUYỆT ĐỐI KHÔNG dùng `LIMIT 1` để trả về đầy đủ danh sách trực quan cho người dùng.
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

HƯỚNG DẪN ĐIỀU CHỈNH:
1. Nếu kết quả trả về 0 dòng dữ liệu do dùng CURRENT_DATE(), NOW(), CURDATE() hoặc lọc thời gian quá chặt: Hãy thay thế bằng `(SELECT MAX(date_col) FROM table_name)` làm mốc ngày gần nhất hoặc bỏ điều kiện lọc thời gian để lấy dữ liệu thực tế!
2. Nếu lỗi 'Table or column doesn't exist': Hãy nhìn kỹ SCHEMA ở trên và CHỈ DÙNG đúng các bảng và cột có thật trong danh sách.
3. Nếu lỗi cú pháp: Dùng `COUNT(*)`, kiểm tra cân đối dấu ngoặc đơn ().
4. Viết lại câu SQL hoàn chỉnh, chuẩn xác 100%. CHỈ TRẢ VỀ DUY NHẤT CÂU SQL THUẦN (SELECT hoặc WITH), không giải thích, không thêm comment."""


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
{ratio_note}

YÊU CẦU:
Hãy đưa ra bản báo cáo Insight Kinh doanh ngắn gọn, sâu sắc và mang tính điều hành thực chiến cao (định dạng Markdown):

### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính
(Nêu rõ các điểm đột biến, kỳ tăng/giảm mạnh hoặc rủi ro tập trung nếu có. Đưa ra con số cụ thể).

### 2.2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng
(Đưa ra 2-3 giả thuyết kinh doanh sát thực tế: mùa vụ, chiến dịch marketing, đứt gãy vận hành, khách hàng VIP, chính sách giá,...).

### 2.3. 🎯 Đề xuất Hành động (Action Plan)
(Đưa ra 2-3 hành động cụ thể, thiết thực cho nhà quản lý / ban lãnh đạo. BẮT BUỘC gắn nhãn mức độ ưu tiên và khung thời gian thực thi cho từng hành động:
- 🔴 **[Ưu tiên Cao - Thực hiện Ngay / Immediate]**: Hành động khắc phục sự cố hoặc nắm bắt cơ hội cấp bách.
- 🟡 **[Ưu tiên Trung bình - Quý tiếp theo / Next Quarter]**: Chiến lược tối ưu hóa hoạt động trung hạn.
- 🟢 **[Ưu tiên Thấp / Dài hạn - Long-term]**: Định hướng chiến lược bền vững dài hạn.
TUYỆT ĐỐI KHÔNG DÙNG BẢNG (TUYỆT ĐỐI KHÔNG dùng dấu gạch đứng |, không dùng dấu +---+). BẮT BUỘC chỉ viết dưới dạng danh sách gạch đầu dòng bullet như trên! MỖI HÀNH ĐỘNG BẮT BUỘC VIẾT TRÊN 1 DÒNG DUY NHẤT.
Ví dụ chuẩn:
• 🔴 **[Ưu tiên Cao - Thực hiện Ngay]**: Tối ưu hóa quy trình bán hàng và chính sách hoa hồng. Mục tiêu đo lường: Tăng 10% doanh số tháng tới.
• 🟡 **[Ưu tiên Trung bình - Quý tiếp theo]**: Tổ chức đào tạo nâng cao kỹ năng cho đội ngũ kinh doanh. Mục tiêu đo lường: Hoàn thành đào tạo trong Quý 2.)

QUY TẮC ĐỊNH DẠNG VĂN BẢN (BẮT BUỘC):
- MỖI Ý PHÂN TÍCH BẮT BUỘC NẰM TRÊN MỘT DÒNG RIÊNG BIỆT (bắt đầu bằng gạch đầu dòng `• `). TUYỆT ĐỐI KHÔNG VIẾT CÁC Ý NỐI LIỀN NHAU TRÊN CÙNG 1 ĐOẠN VĂN!
- TUYỆT ĐỐI KHÔNG TỰ Ý IN ĐẬM Ở TRONG THÂN CÂU (CẤM dùng ** bên trong câu).
- CHỈ IN ĐẬM DUY NHẤT TIÊU ĐỀ Ở ĐẦU GẠCH ĐẦU DÒNG TRƯỚC DẤU HAI CHẤM (Ví dụ: `• **Tiêu đề phân tích**: Toàn bộ nội dung phân tích phía sau là chữ thường bình thường, không có bất kỳ dấu sao ** nào`).
- Tách từ và số chuẩn xác (viết "thấp hơn", "cao hơn", "lớn hơn", "đạt 28,490,175", "11.0% so với", TUYỆT ĐỐI KHÔNG viết dính liền).
- Phong cách trình bày: Chuyên nghiệp, súc tích, đi thẳng vào trọng tâm kinh doanh, văn phong giám đốc điều hành."""


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
4. Đề xuất 2 đến 3 câu hỏi đào sâu thông minh, thiết thực và CHẮC CHẮN CÓ DỮ LIỆU TRUY VẤN ĐƯỢC 100%.
5. CHÍNH TẢ & NGÔN NGỮ THUẦN VIỆT:
   - Viết 100% tiếng Việt chuẩn xác, TUYỆT ĐỐI KHÔNG dùng ký tự lạ hay chữ tiếng Hàn/Trung (như '각'). Dùng từ 'từng khu vực' hoặc 'các khu vực'.
   - Luôn tách từ rõ ràng, có dấu cách giữa tiếng Việt và tiếng Anh (ví dụ: viết 'danh mục Bars', TUYỆT ĐỐI KHÔNG viết 'danh mụcBars').

Trả về DUY NHẤT một JSON array chứa danh sách các chuỗi câu hỏi:
["Câu hỏi 1", "Câu hỏi 2", "Câu hỏi 3"]"""
