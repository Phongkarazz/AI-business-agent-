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
    - CẤM TỰ Ý IN ĐẬM TRONG CÂU: Chỉ in đậm duy nhất Tiêu đề ở đầu gạch đầu dòng trước dấu hai chấm.
    - Xóa toàn bộ dấu ** thừa, mồ côi hoặc chèn lung tung trong thân câu.
    - Tách toàn bộ chữ dính với %, số, và tên riêng (Jucies để, đạt 28,490,175, 11.0% so).
    - Khôi phục và chuẩn hóa tiêu đề ### 2.1. 🚨, ### 2.2. 🔍, ### 2.3. 🎯
    """
    if not text:
        return ""

    # 0. Chuẩn hóa tiêu đề 2.1, 2.2, 2.3 thành ### trước khi xử lý
    text = re.sub(r"^(?:#+\s*)?(?:1\.?\s*|2\.1\.?\s*)?(?:🚨\s*)?(Phát hiện Bất thường.*)", r"### 2.1. 🚨 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^(?:#+\s*)?(?:2\.?\s*|2\.2\.?\s*)?(?:🔍\s*)?(Giả thuyết & Nguyên nhân.*)", r"### 2.2. 🔍 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^(?:#+\s*)?(?:3\.?\s*|2\.3\.?\s*)?(?:🎯\s*)?(Đề xuất Hành động.*)", r"### 2.3. 🎯 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)

    # 1. Thay thế ký tự bullet lạ tiếng Trung 。・ thành ký hiệu thụt lề chuẩn
    text = re.sub(r"^[。・]\s*", "   - ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[。・]\s*", "   - ", text, flags=re.MULTILINE)

    # 2. Xóa các tiền tố #### trước nhãn ưu tiên
    text = re.sub(r"#+\s*(\[(?:Ưu tiên|High Priority|Medium Priority|Low Priority))", r"\g<1>", text)

    # 3. Sửa lỗi chính tả phổ biến
    text = text.replace("đư ợc", "được").replace("đư ọc", "được")

    # 4. Tự động tách dòng cho các ý phân tích bị dính liền trên cùng 1 đoạn văn
    text = re.sub(r"(?<=[^\n])\s+•\s*", "\n\n• ", text)
    text = re.sub(r"(?<=[^\n•\-\*\s])\s+(\[(?:Ưu tiên|High Priority|Medium Priority|Low Priority))", r"\n\n• \g<1>", text)
    text = re.sub(r"(?<=[^\n])\s+(?:,\s*)?(?:với\s+)?(KPI\s+(?:đo lường|kỳ vọng|đo lường kỳ vọng)[^:\n]*:)", r"\n  - \g<1>", text, flags=re.IGNORECASE)

    lines = text.splitlines()
    cleaned_lines = []

    for line in lines:
        l = line.strip()
        if not l:
            cleaned_lines.append("")
            continue

        # Giữ nguyên các tiêu đề Markdown lớn
        if l.startswith("#"):
            cleaned_lines.append(l)
            continue

        # A. Sửa lỗi dính từ tiếng Anh/Tên riêng với các từ nối tiếng Việt: Juciesđể -> Jucies để, Delishvà -> Delish và
        l = re.sub(r"([a-zA-Z]{3,})(để|và|với|chiếm|trong|của|cho|tại|theo|đạt|có)", r"\g<1> \g<2>", l)

        # B. Sửa lỗi dính từ với số: đạt28,490,175 -> đạt 28,490,175, thiểu9,000,000 -> thiểu 9,000,000
        l = re.sub(r"([a-zA-Zà-ỹÀ-Ỹ])(\d{1,3}(?:,\d{3})+|\d+)", r"\g<1> \g<2>", l)
        l = re.sub(r"(\d{1,3}(?:,\d{3})+|\d+)([a-zA-Zà-ỹÀ-Ỹ])", r"\g<1> \g<2>", l)

        # C. Sửa dính % với từ: 11.0%so -> 11.0% so
        l = re.sub(r"(\d+(?:\.\d+)?%)([a-zA-Zà-ỹÀ-Ỹ])", r"\g<1> \g<2>", l)
        l = re.sub(r"([a-zA-Zà-ỹÀ-Ỹ])(\d+(?:\.\d+)?%)", r"\g<1> \g<2>", l)

        # D. Sửa lỗi khoảng trắng quanh dấu câu: 175 , với -> 175, với; ( 9,708,972 ) -> (9,708,972)
        l = re.sub(r"\s+([,\.:;])", r"\g<1>", l)
        l = re.sub(r"\(\s+", "(", l)
        l = re.sub(r"\s+\)", ")", l)

        # E. Xóa số thứ tự lặp lại sau bullet: • 1. -> •
        l = re.sub(r"^[•\-\*]\s*\d+[\.\)]\s*", "• ", l)

        # F. QUY TẮC: KHÔNG ĐƯỢC TỰ Ý IN ĐẬM Ở TRONG CÂU
        # Chỉ giữ in đậm ở tiêu đề trước dấu hai chấm: • **Tiêu đề**: hoặc • [Ưu tiên...]:
        if ":" in l:
            prefix, rest = l.split(":", 1)
            clean_p = prefix.replace("**", "").replace("*", "").strip()

            bullet_char = "•"
            if clean_p.startswith("-") or clean_p.startswith("*"):
                bullet_char = clean_p[0]

            clean_tag = clean_p.lstrip("•-* ").strip()

            if "[" in clean_tag and "]" in clean_tag:
                prefix_out = f"{bullet_char} {clean_tag}"
            elif clean_tag.lower().startswith("kpi") or "kpi" in clean_tag.lower():
                prefix_out = f"  - {clean_tag}"
            else:
                if len(clean_tag.split()) > 10 or clean_tag.lower().startswith("tổng doanh số") or clean_tag.lower().startswith("nhóm"):
                    prefix_out = f"• {clean_tag}"
                else:
                    prefix_out = f"• **{clean_tag}**"

            # XÓA SẠCH TOÀN BỘ DẤU ** TRONG THÂN CÂU (rest)
            clean_rest = rest.replace("**", "").replace("*", "").strip()
            l = f"{prefix_out}: {clean_rest}"
        else:
            # Dòng không có dấu hai chấm: Xóa TOÀN BỘ **
            clean_l = l.replace("**", "").replace("*", "").strip()
            if not clean_l.startswith("•") and not clean_l.startswith("-"):
                clean_l = f"• {clean_l}"
            l = clean_l

        # Dọn dẹp khoảng trắng thừa
        l = re.sub(r"[ \t]+", " ", l)
        cleaned_lines.append(l)

    text = "\n".join(cleaned_lines)

    # 4. Đảm bảo tiêu đề 2.1, 2.2, 2.3 luôn tồn tại và được định dạng chuẩn
    has_head_21 = bool(re.search(r"^(?:#+\s*)?(?:1\.?\s*|2\.1\.?\s*)?(?:🚨\s*)?Phát hiện Bất thường", text, flags=re.IGNORECASE | re.MULTILINE))
    if not has_head_21:
        text = "### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính\n\n" + text

    text = re.sub(r"^(?:#+\s*)?(?:1\.?\s*|2\.1\.?\s*)?(?:🚨\s*)?(Phát hiện Bất thường.*)", r"### 2.1. 🚨 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^(?:#+\s*)?(?:2\.?\s*|2\.2\.?\s*)?(?:🔍\s*)?(Giả thuyết & Nguyên nhân.*)", r"### 2.2. 🔍 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^(?:#+\s*)?(?:3\.?\s*|2\.3\.?\s*)?(?:🎯\s*)?(Đề xuất Hành động.*)", r"### 2.3. 🎯 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)

    # Dọn dẹp các tiền tố bị nhân đôi do regex
    text = re.sub(r"###\s*2\.(\d)\.\s*[🚨🔍🎯]\s*(?:2\.\d\.?\s*)?", r"### 2.\g<1>. ", text)
    text = text.replace("### 2.1. ", "### 2.1. 🚨 ")
    text = text.replace("### 2.2. ", "### 2.2. 🔍 ")
    text = text.replace("### 2.3. ", "### 2.3. 🎯 ")

    return text.strip()
