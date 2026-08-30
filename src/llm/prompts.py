"""
Prompt templates and builders for SQL generation, validation, anomaly explanation, and automatic business insights.
"""


def get_dialect_hints(dialect: str) -> str:
    """Trả về hướng dẫn cú pháp SQL theo từng hệ quản trị cơ sở dữ liệu."""
    if dialect == "SQLite":
        return "Database đang dùng là SQLite: dùng strftime('%Y', col)/strftime('%m', col) để lấy năm/tháng, KHÔNG dùng MONTH()/YEAR() của MySQL."
    elif dialect == "MySQL":
        return "Database đang dùng là MySQL: có thể dùng MONTH()/YEAR()/DATE_FORMAT(), DATEDIFF(), LEAST(), GREATEST() bình thường."
    return ""


HISTORY_HINT = (
    "Nếu có bảng lưu lịch sử theo thời gian (chứa cột from_date/to_date, ví dụ: salaries, "
    "titles, dept_emp...) và câu hỏi hỏi về giá trị/trạng thái HIỆN TẠI (VD: 'lương hiện tại', "
    "'phòng ban hiện tại', 'top N hiện nay'), chỉ lấy bản ghi đang hiệu lực (thường là "
    "to_date = '9999-01-01', hoặc dùng subquery lấy bản ghi có MAX(from_date) theo từng khóa "
    "chính) để tránh JOIN sinh ra nhiều dòng trùng lặp cho cùng 1 thực thể. "
    "NGƯỢC LẠI, nếu câu hỏi cần đếm/liệt kê SỐ LẦN THAY ĐỔI, LỊCH SỬ, hoặc 'đã từng' (VD: "
    "'đã từng đổi chức danh bao nhiêu lần', 'lịch sử lương'), TUYỆT ĐỐI KHÔNG lọc to_date — "
    "phải giữ nguyên toàn bộ các dòng lịch sử để đếm chính xác."
)


def build_sql_prompt(schema_context: str, dialect: str, user_query: str) -> str:
    """Xây dựng prompt tạo câu lệnh SQL từ ngôn ngữ tự nhiên."""
    dialect_hint = get_dialect_hints(dialect)
    return f"""Bạn là chuyên gia SQL hàng đầu thế giới.
Schema Database:
{schema_context}

Lưu ý Dialect: {dialect_hint}
Lưu ý Bảng Lịch sử & Dữ liệu thời gian: {HISTORY_HINT}

YÊU CẦU QUAN TRỌNG:
1. Viết 1 câu lệnh SQL SELECT duy nhất trả lời chính xác câu hỏi: "{user_query}"
2. Kiểm tra kỹ CÚ PHÁP: Mọi dấu ngoặc mở '(' và đóng ')' phải tuyệt đối cân đối, không được thừa hoặc thiếu dấu ngoặc.
3. Nếu tính toán phức tạp (nhân chia, DATEDIFF, LEAST, GREATEST,...), hãy gom nhóm dấu ngoặc chuẩn xác: ví dụ `SUM(s.salary * (DATEDIFF(LEAST(s.to_date, '2021-12-31'), GREATEST(s.from_date, '2021-01-01')) + 1) / 365.25)`.
4. Nếu không có GROUP BY, bắt buộc thêm LIMIT 1000 để tránh trả về quá nhiều dữ liệu.
5. CHỈ TRẢ VỀ DUY NHẤT CÂU LỆNH SQL THUẦN (bắt đầu bằng SELECT hoặc WITH), không giải thích, không markdown bên ngoài."""


def build_fix_prompt(schema_context: str, dialect: str, user_query: str, sql_query: str, reason_or_error: str) -> str:
    """Xây dựng prompt yêu cầu LLM sửa lại SQL khi gặp lỗi hoặc không qua bước self-check."""
    dialect_hint = get_dialect_hints(dialect)
    return f"""Bạn là chuyên gia SQL. Câu lệnh SQL bạn vừa sinh ra ĐÃ BỊ LỖI THỰC THI trên {dialect}.

Schema Database:
{schema_context}
Lưu ý Dialect: {dialect_hint}
Lưu ý Bảng Lịch sử: {HISTORY_HINT}

Câu hỏi gốc: "{user_query}"

Câu SQL bị lỗi:
{sql_query}

THÔNG BÁO LỖI TỪ DATABASE / HỆ THỐNG:
{reason_or_error}

HƯỚNG DẪN SỬA LỖI:
- Nếu lỗi Syntax Error gần dấu ngoặc ')': Hãy đếm và kiểm tra lại từng cặp dấu ngoặc '(' và ')' trong các hàm toán học, hàm tổng hợp (SUM, AVG) và hàm ngày tháng (DATEDIFF, LEAST, GREATEST) để đảm bảo không bị thừa/thiếu dấu ngoặc.
- Nếu lỗi tên bảng / tên cột: Kiểm tra lại chính xác tên bảng và tên cột trong Schema ở trên.
- Viết lại câu SQL hoàn chỉnh, chuẩn xác 100%. CHỈ TRẢ VỀ CÂU SQL, không giải thích."""


def build_self_check_prompt(schema_context: str, user_query: str, sql_query: str, sample_str: str) -> str:
    """Xây dựng prompt cho bước AI QA self-check."""
    return f"""Bạn là chuyên gia QA kiểm định SQL.
Schema: {schema_context}
Câu hỏi gốc: "{user_query}"
SQL: {sql_query}
5 dòng mẫu: {sample_str}

Kiểm tra SQL có trả lời ĐẦY ĐỦ câu hỏi không.
Đặc biệt: nếu SQL JOIN với bảng lưu lịch sử theo thời gian (có cột from_date/to_date, ví dụ
salaries, titles, dept_emp...) mà KHÔNG lọc bản ghi hiện tại (to_date = '9999-01-01' hoặc
MAX(from_date) theo từng khóa chính), kết quả sẽ bị nhân bản dòng cho cùng 1 thực thể — hãy
coi đây là "day_du": false và nêu rõ trong "ly_do".

QUAN TRỌNG: "ly_do" PHẢI ngắn gọn, TỐI ĐA 20 từ, đi thẳng vào vấn đề — không lý luận dài dòng.
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
