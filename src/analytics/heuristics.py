"""
Column classification, language detection, starter prompts generator, and heuristic utilities for business datasets.
"""

import re
import pandas as pd
from src.config import ID_LIKE_REGEX, NAME_LIKE_REGEX, TIME_KEYWORDS

VI_CHAR_REGEX = re.compile(r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]', re.IGNORECASE)
EN_MARKERS = {
    "what", "which", "how", "many", "much", "best", "selling", "revenue", "sales",
    "product", "products", "rep", "reps", "salesperson", "salespersons", "employee",
    "employees", "by", "per", "in", "of", "and", "the", "for", "year", "years",
    "month", "months", "trend", "trends", "change", "over", "time", "highest",
    "lowest", "average", "total", "count", "country", "countries", "region", "regions",
    "show", "list", "give", "me", "find", "get", "who", "where", "when"
}
VI_MARKERS = {
    "la", "gi", "nao", "bao", "nhieu", "nhan", "vien", "san", "pham", "doanh",
    "thu", "ban", "hang", "thang", "nam", "quy", "khu", "vuc", "quoc", "gia",
    "tong", "nhat", "hop", "moi", "theo", "cac", "nhung", "co", "hay", "khong",
    "cho", "toi", "xem", "liet", "ke"
}


def detect_query_language(query: str) -> str:
    """Tự động phát hiện ngôn ngữ của câu hỏi: 'vi' (Tiếng Việt) hoặc 'en' (Tiếng Anh)."""
    if not query or not query.strip():
        return "vi"

    text = query.strip()
    # 1. Nếu có ký tự có dấu tiếng Việt
    if VI_CHAR_REGEX.search(text):
        return "vi"

    words = set(re.findall(r'\b[a-zA-Z]+\b', text.lower()))
    en_matches = len(words.intersection(EN_MARKERS))
    vi_matches = len(words.intersection(VI_MARKERS))

    if en_matches > vi_matches:
        return "en"

    return "vi"


def is_id_like(col_name: str) -> bool:
    """True nếu tên cột trông giống định danh (emp_no, GeoID, product_code...)."""
    return bool(ID_LIKE_REGEX.search(str(col_name).strip()))


def find_time_column(df: pd.DataFrame):
    """Tìm cột thời gian hợp lệ.
    Ưu tiên:
    1) dtype datetime gốc
    2) Tên khớp từ khóa thời gian VÀ parse thành công >= 80% giá trị.
    Luôn loại các cột dạng ID."""
    if df is None or df.empty:
        return None

    # 1. Cột có dtype datetime sẵn
    dt_cols = df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns.tolist()
    dt_cols = [c for c in dt_cols if not is_id_like(c)]
    if dt_cols:
        return dt_cols[0]

    # 2. Cột tên khớp từ khóa thời gian, không phải ID, và parse được thành ngày
    candidates = [c for c in df.columns if any(k in str(c).lower() for k in TIME_KEYWORDS) and not is_id_like(c)]
    for c in candidates:
        try:
            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                return c
        except Exception:
            continue
    return None


def has_time_dimension(df: pd.DataFrame) -> bool:
    """Kiểm tra dataframe có chiều thời gian không."""
    return find_time_column(df) is not None


def get_axis_columns(df: pd.DataFrame):
    """Phân loại cột:
    - measure_cols: cột số đo lường (đã loại bỏ ID)
    - cat_cols: cột danh mục/text
    - time_col: cột thời gian
    """
    all_num_cols = df.select_dtypes(include="number").columns.tolist()
    measure_cols = [c for c in all_num_cols if not is_id_like(c)]
    cat_cols = [c for c in df.columns if c not in measure_cols]
    time_col = find_time_column(df)

    if time_col in measure_cols:
        measure_cols.remove(time_col)
    return measure_cols, cat_cols, time_col


def get_row_identity_column(df: pd.DataFrame):
    """Tìm cột ID có số giá trị duy nhất bằng đúng số dòng của kết quả (mỗi dòng là 1 thực thể)."""
    for c in df.columns:
        if is_id_like(c):
            try:
                if df[c].nunique(dropna=True) == len(df):
                    return c
            except Exception:
                continue
    return None


def get_best_name_column(df: pd.DataFrame, exclude_cols: list = None):
    """Tìm cột tên người/sản phẩm/danh mục để làm nhãn hiển thị trực quan."""
    exclude = set(exclude_cols or [])
    for c in df.columns:
        if c not in exclude and NAME_LIKE_REGEX.search(str(c)):
            return c
    return None


def pick_label_column(df: pd.DataFrame, label_cols: list) -> tuple:
    """Chọn cột nhãn tốt nhất cho trục X:
    - Nếu có cột name-like (Product, Country, Quốc gia, etc.), ưu tiên chọn.
    - Nếu có nhiều cột text, ưu tiên cột có độ phân biệt (unique) cao hơn làm trục X.
    - Trả về (label_name, label_series, consumed_cols).
    """
    if df is None or df.empty or not label_cols:
        return None, None, []

    # 1. Tìm cột khớp pattern name-like
    best_name = get_best_name_column(df, exclude_cols=[])
    if best_name and best_name in label_cols:
        return best_name, df[best_name].astype(str), [best_name]

    # 2. Sắp xếp theo số lượng giá trị duy nhất giảm dần (cột chi tiết hơn làm trục X)
    try:
        sorted_by_unique = sorted(label_cols, key=lambda c: df[c].nunique(dropna=True), reverse=True)
        chosen_col = sorted_by_unique[0]
    except Exception:
        chosen_col = label_cols[0]

    return chosen_col, df[chosen_col].astype(str), [chosen_col]


def generate_starter_prompts(tables: list[str]) -> list[dict]:
    """Tự động sinh 4 thẻ gợi ý câu hỏi thông minh 1-chạm dựa trên cấu trúc bảng của CSDL."""
    tables_lower = [t.lower() for t in tables]

    cards = []

    # 1. Nếu có bảng sản phẩm & doanh số
    if any(t in tables_lower for t in ["products", "product", "items"]):
        cards.append({
            "icon": "🍫",
            "title": "Top Sản Phẩm Doanh Thu Cao Nhất",
            "prompt": "Top 5 sản phẩm mang lại doanh thu cao nhất",
            "desc": "Xếp hạng sản phẩm theo tổng số tiền bán được"
        })
    else:
        cards.append({
            "icon": "📊",
            "title": "Tổng Quan Doanh Số",
            "prompt": "Tổng doanh số và số lượng giao dịch",
            "desc": "Thống kê tổng thể toàn bộ dữ liệu kinh doanh"
        })

    # 2. Nếu có chiều thời gian hoặc sales
    if any(t in tables_lower for t in ["sales", "orders", "transactions", "invoices"]):
        cards.append({
            "icon": "📈",
            "title": "Xu Hướng Doanh Số Theo Tháng",
            "prompt": "Doanh số tổng theo từng tháng trong năm 2021",
            "desc": "Phân tích biến động doanh thu và dự báo xu hướng"
        })
    else:
        cards.append({
            "icon": "📈",
            "title": "Phân Tích Theo Thời Gian",
            "prompt": "Thống kê số lượng dữ liệu theo từng tháng",
            "desc": "Xem biểu đồ biến động theo các mốc thời gian"
        })

    # 3. Nếu có bảng nhân viên
    if any(t in tables_lower for t in ["people", "salespersons", "employees", "staff", "users"]):
        cards.append({
            "icon": "👥",
            "title": "Xếp Hạng Nhân Viên Bán Chạy Nhất",
            "prompt": "Top 10 nhân viên bán được nhiều hộp chocolate nhất",
            "desc": "Đánh giá hiệu suất kinh doanh của từng nhân sự"
        })
    else:
        cards.append({
            "icon": "🏆",
            "title": "Top Đối Tượng Nổi Bật",
            "prompt": "Top 10 đối tượng có chỉ số cao nhất",
            "desc": "Xếp hạng các mục dữ liệu quan trọng nhất"
        })

    # 4. Nếu có bảng địa lý / thị trường
    if any(t in tables_lower for t in ["geo", "regions", "countries", "locations", "stores"]):
        cards.append({
            "icon": "🌍",
            "title": "Phân Bổ Doanh Thu Theo Thị Trường",
            "prompt": "Tổng doanh thu theo từng quốc gia và khu vực",
            "desc": "Biểu đồ so sánh doanh số giữa các thị trường địa lý"
        })
    else:
        cards.append({
            "icon": "🔍",
            "title": "Khám Phá Dữ Liệu Chi Tiết",
            "prompt": "Thống kê số lượng bản ghi và giá trị trung bình",
            "desc": "Phân tích tổng hợp số liệu trên toàn bộ các bảng"
        })

    return cards[:4]


def sanitize_insight_markdown(text: str) -> str:
    """Tự động làm sạch hoàn toàn các lỗi định dạng markdown của AI:
    - Xóa khoảng trắng thừa bên trong thẻ in đậm: ** text ** hoặc **text ** -> **text**
    - Sửa dính thẻ: ]-** -> ] - **
    - Thay thế ký tự lạ 。・ thành ↳ cho dòng KPI
    - Khôi phục và chuẩn hóa tiêu đề ### 2.1. 🚨, ### 2.2. 🔍, ### 2.3. 🎯
    """
    if not text:
        return ""

    text = str(text)

    # 1. Thay thế ký tự bullet lạ tiếng Trung 。・ thành ký hiệu thụt lề ↳
    text = re.sub(r"^[。・]\s*", "   ↳ ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[。・]\s*", "   ↳ ", text, flags=re.MULTILINE)

    # 2. Gộp các dấu sao bị chèn khoảng trắng: * *, ** *, * ** -> **
    text = re.sub(r"\*\s+\*", r"**", text)

    # 3. Xóa khoảng trắng thừa bên trong thẻ in đậm/nghiêng: ** 123 ** hoặc **123 ** -> **123**
    for _ in range(2):
        text = re.sub(r"\*\*\s*([^\*\n]+?)\s*\*\*", r"**\1**", text)
        text = re.sub(r"\*\s*([^\*\n]+?)\s*\*", r"*\1*", text)

    # 4. Sửa dính thẻ sau nhãn ưu tiên: ]-** -> ] - **
    text = re.sub(r"\]\s*-\s*\*\*\s*", r"] - **", text)
    text = re.sub(r"\]\s*-\s*", r"] - ", text)

    # 5. Sửa khoảng trắng trước dấu hai chấm sau in đậm: **Text** : -> **Text**:
    text = re.sub(r"\*\*\s*:\s*", r"**: ", text)

    # 6. Sửa lỗi số phân tách hàng nghìn bị chèn dấu cách: 1, 299, 998 -> 1,299,998
    for _ in range(4):
        text = re.sub(r"(\d+),\s+(\d{3})", r"\1,\2", text)

    # 7. Xóa số thứ tự lặp lại sau bullet: • 1. -> •
    text = re.sub(r"^[•\-\*]\s*\d+[\.\)]\s*", "• ", text, flags=re.MULTILINE)

    # 8. Sửa dính chữ quanh thẻ in đậm (VD: **KHÔNG**Phát hiện -> **KHÔNG** Phát hiện, **USA**có -> **USA** có)
    text = re.sub(r"\*\*([^\*\n]+?)\*\*([a-zA-Zà-ỹÀ-Ỹ0-9])", r"**\1** \2", text)
    text = re.sub(r"([a-zA-Zà-ỹÀ-Ỹ0-9])\*\*([^\*\n]+?)\*\*", r"\1 **\2**", text)

    # 9. Tách từ viết hoa viết tắt dính liền với từ thường (VD: APACchiếm -> APAC chiếm, USACó -> USA Có)
    text = re.sub(r"([A-ZÀ-Ỹ]{2,})([A-ZÀ-Ỹ][a-zà-ỹ])", r"\1 \2", text)
    text = re.sub(r"([A-Z]{2,})([a-zà-ỹ])", r"\1 \2", text)

    # 10. Chuẩn hóa khoảng trắng sau dấu hai chấm
    text = re.sub(r"([a-zA-Zà-ỹÀ-Ỹ]):(\d)", r"\1: \2", text)
    text = re.sub(r":([A-ZÀ-Ỹa-zà-ỹ])", r": \1", text)
    text = re.sub(r"\bthấphơn\b", "thấp hơn", text)
    text = re.sub(r"\bcaohơn\b", "cao hơn", text)
    text = re.sub(r"\blớnhơn\b", "lớn hơn", text)
    text = re.sub(r"\bnhỏhơn\b", "nhỏ hơn", text)
    text = re.sub(r"#+\s*(\[(?:Ưu tiên|High Priority|Medium Priority|Low Priority))", r"\1", text)

    # 11. Đảm bảo tiêu đề 2.1, 2.2, 2.3 luôn tồn tại và được định dạng chuẩn
    has_head_21 = bool(re.search(r"^(?:#+\s*)?(?:1\.?\s*|2\.1\.?\s*)?(?:🚨\s*)?Phát hiện Bất thường", text, flags=re.IGNORECASE | re.MULTILINE))
    if not has_head_21:
        text = "### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính\n\n" + text

    text = re.sub(r"^(?:#+\s*)?(?:1\.?\s*|2\.1\.?\s*)?(?:🚨\s*)?(Phát hiện Bất thường.*)", r"### 2.1. 🚨 \1", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^(?:#+\s*)?(?:2\.?\s*|2\.2\.?\s*)?(?:🔍\s*)?(Giả thuyết & Nguyên nhân.*)", r"### 2.2. 🔍 \1", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^(?:#+\s*)?(?:3\.?\s*|2\.3\.?\s*)?(?:🎯\s*)?(Đề xuất Hành động.*)", r"### 2.3. 🎯 \1", text, flags=re.IGNORECASE | re.MULTILINE)

    # Dọn dẹp các tiền tố bị nhân đôi do regex
    text = re.sub(r"###\s*2\.(\d)\.\s*[🚨🔍🎯]\s*(?:2\.\d\.?\s*)?(?:[🚨🔍🎯]\s*)?", r"### 2.\1. ", text)
    text = text.replace("### 2.1. ", "### 2.1. 🚨 ")
    text = text.replace("### 2.2. ", "### 2.2. 🔍 ")
    text = text.replace("### 2.3. ", "### 2.3. 🎯 ")

    # 12. Dọn dẹp các dấu sao thừa liên tiếp
    text = re.sub(r"\*{3,}", r"**", text)

    return text.strip()
