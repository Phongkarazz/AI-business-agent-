"""
Prompt templates and builders for SQL generation, validation, anomaly explanation, and automatic business insights.
Strictly grounded in provided database schema to prevent hallucination.
"""


def get_dialect_hints(dialect: str) -> str:
    """Trả về hướng dẫn cú pháp SQL theo từng hệ quản trị cơ sở dữ liệu."""
    if dialect == "SQLite":
        return "Database đang dùng là SQLite: dùng strftime('%Y', col)/strftime('%m', col) để lấy năm/tháng, KHÔNG dùng MONTH()/YEAR() của MySQL."
    elif dialect == "MySQL":
        return "Database đang dùng là MySQL: có thể dùng MONTH()/YEAR()/DATE_FORMAT(), DATEDIFF(), LEAST(), GREATEST() bình thường."
    return ""


def build_sql_prompt(schema_context: str, dialect: str, user_query: str) -> str:
    """Xây dựng prompt tạo câu lệnh SQL từ ngôn ngữ tự nhiên với Schema Grounding nghiêm ngặt."""
    dialect_hint = get_dialect_hints(dialect)
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
   - Nếu trong Schema có bảng `sales`, hãy dùng bảng đó cho doanh số/giao dịch.
2. CÚ PHÁP CHUẨN XÁC:
   - Dùng `COUNT(*)` hoặc `COUNT(column)`, TUYỆT ĐỐI KHÔNG dùng `COUNT()`.
   - Cân đối tuyệt đối số lượng dấu mở ngoặc '(' và đóng ngoặc ')'.
   - Bọc tên bảng và tên cột trong dấu backtick ` nếu có chứa ký tự đặc biệt hoặc khoảng trắng.
3. NẾU BẢNG CÓ CỘT HIỆU LỰC (from_date / to_date):
   - Nếu câu hỏi hỏi về GIÁ TRỊ HIỆN TẠI (VD: 'lương hiện tại', 'trạng thái hiện nay'): lọc bản ghi đang hiệu lực (`to_date = '9999-01-01'` hoặc `MAX(from_date)`).
   - Nếu câu hỏi hỏi về LỊCH SỬ / BIẾN ĐỘNG / MỐC NĂM CŨ (VD: 'năm 2021', 'biến động'): KHÔNG lọc `to_date = '9999-01-01'`, hãy lọc theo đúng mốc thời gian của câu hỏi.
4. ĐỊNH DẠNG ĐẦU RA:
   - CHỈ TRẢ VỀ DUY NHẤT 1 CÂU LỆNH SQL THUẦN (bắt đầu bằng SELECT hoặc WITH).
   - TUYỆT ĐỐI KHÔNG thêm bất kỳ comment (#, --), không thêm lời giải thích hay markdown code block bên ngoài.

Câu hỏi của người dùng: "{user_query}"
Câu lệnh SQL:"""


def build_fix_prompt(schema_context: str, dialect: str, user_query: str, sql_query: str, reason_or_error: str) -> str:
    """Xây dựng prompt yêu cầu LLM sửa lại SQL khi gặp lỗi hoặc không qua bước self-check."""
    dialect_hint = get_dialect_hints(dialect)
    return f"""Bạn là chuyên gia SQL. Câu lệnh SQL bạn vừa sinh ra ĐÃ BỊ LỖI THỰC THI trên {dialect}.

=== SCHEMA CƠ SỞ DỮ LIỆU THỰC TẾ ===
{schema_context}
====================================
Lưu ý Dialect: {dialect_hint}

Câu hỏi gốc: "{user_query}"

Câu SQL bị lỗi:
{sql_query}

THÔNG BÁO LỖI TỪ HỆ THỐNG:
{reason_or_error}

HƯỚNG DẪN SỬA LỖI:
1. Nếu lỗi 'Table doesn't exist' (Bảng không tồn tại): Hãy nhìn kỹ SCHEMA ở trên và chỉ dùng đúng các bảng có thật trong danh sách! Tuyệt đối không dùng các bảng ảo không có trong Schema.
2. Nếu lỗi cú pháp: Kiểm tra lại `COUNT(*)` (thay vì `COUNT()`), kiểm tra cân đối dấu ngoặc đơn () trong các hàm tổng hợp và ngày tháng.
3. Viết lại câu SQL hoàn chỉnh, chuẩn xác 100%. CHỈ TRẢ VỀ DUY NHẤT CÂU SQL THUẦN (SELECT hoặc WITH), không giải thích, không thêm comment."""


def build_self_check_prompt(schema_context: str, user_query: str, sql_query: str, sample_str: str) -> str:
    """Xây dựng prompt cho bước AI QA self-check."""
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


def build_anomaly_prompt(user_query: str, x_col: str, y_col: str, points: list) -> str:
    """Xây dựng prompt giải thích các điểm bất thường dữ liệu."""
    return f"""Bạn là chuyên gia phân tích dữ liệu kinh doanh.
Câu hỏi gốc của người dùng: "{user_query}"
Các điểm bất thường (outlier, theo phương pháp IQR) phát hiện trên trục {x_col}, giá trị {y_col}: {points}
Đưa ra 1-2 câu nhận xét/giả thuyết ngắn gọn về nguyên nhân kinh doanh có thể xảy ra (VD: mùa vụ, khuyến mãi, sự kiện...).
Chỉ trả lời 1 đoạn văn ngắn, không markdown, không liệt kê gạch đầu dòng."""


def build_auto_insight_prompt(user_query: str, df_summary_str: str, anomalies_info: dict) -> str:
    """Xây dựng prompt cho việc tự động phát hiện Insight kinh doanh và phân tích xu hướng bất thường."""
    findings = anomalies_info.get("findings", [])
    anomaly_types = anomalies_info.get("anomaly_types", [])
    stats = anomalies_info.get("summary_stats", {})

    findings_text = "\n".join(f"- {f.get('message')}" for f in findings) if findings else "Không có dấu hiệu bất thường rõ rệt."
    types_text = ", ".join(anomaly_types) if anomaly_types else "Bình thường"

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
Hãy đưa ra bản báo cáo Insight Kinh doanh ngắn gọn, sâu sắc và chuyên nghiệp (định dạng Markdown):

### 1. 🚨 Phát hiện Bất thường & Xu hướng Chính
(Nêu rõ các điểm đột biến, kỳ tăng/giảm mạnh hoặc rủi ro tập trung nếu có. Đưa ra con số cụ thể).

### 2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng
(Đưa ra 2-3 giả thuyết kinh doanh sát thực tế: mùa vụ, chiến dịch marketing, đứt gãy vận hành, khách hàng VIP, chính sách giá,...).

### 3. 🎯 Đề xuất Hành động (Action Plan)
(Đưa ra 2-3 hành động cụ thể, thiết thực cho nhà quản lý / ban lãnh đạo).

Phong cách trình bày: Chuyên nghiệp, súc tích, đi thẳng vào trọng tâm kinh doanh, không dùng từ ngữ sáo rỗng."""
