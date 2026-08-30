"""
Prompt templates and builders for SQL generation, validation, and anomaly explanation.
"""


def get_dialect_hints(dialect: str) -> str:
    """Trả về hướng dẫn cú pháp SQL theo từng hệ quản trị cơ sở dữ liệu."""
    if dialect == "SQLite":
        return "Database đang dùng là SQLite: dùng strftime('%Y', col)/strftime('%m', col) để lấy năm/tháng, KHÔNG dùng MONTH()/YEAR() của MySQL."
    elif dialect == "MySQL":
        return "Database đang dùng là MySQL: có thể dùng MONTH()/YEAR()/DATE_FORMAT() bình thường."
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
    return f"""Schema:
{schema_context}
Lưu ý dialect: {dialect_hint}
Lưu ý dữ liệu lịch sử: {HISTORY_HINT}
Viết 1 câu SQL SELECT duy nhất cho câu hỏi: {user_query}
Nếu không có GROUP BY, bắt buộc thêm LIMIT 1000 để tránh trả về quá nhiều dữ liệu.
Chỉ trả về SQL thuần, không markdown, không giải thích."""


def build_fix_prompt(schema_context: str, dialect: str, user_query: str, sql_query: str, reason_or_error: str) -> str:
    """Xây dựng prompt yêu cầu LLM sửa lại SQL khi gặp lỗi hoặc không qua bước self-check."""
    dialect_hint = get_dialect_hints(dialect)
    return f"""Schema: {schema_context}
Lưu ý dialect: {dialect_hint}
Lưu ý dữ liệu lịch sử: {HISTORY_HINT}
Câu hỏi: '{user_query}'
SQL lỗi/chưa đủ: {sql_query}
Vấn đề phát hiện: {reason_or_error}
Viết lại câu SQL chuẩn xác. Chỉ trả về SQL thuần, không markdown, không giải thích."""


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
