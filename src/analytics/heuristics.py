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
    - Nếu có cả first_name và last_name, ưu tiên ghép lại làm nhãn 'Họ và Tên'.
    - Nếu có cột name-like (Product, Country, Quốc gia, etc.), ưu tiên chọn.
    - Nếu có nhiều cột text, ưu tiên cột có độ phân biệt (unique) cao hơn làm trục X.
    - Trả về (label_name, label_series, consumed_cols).
    """
    if df is None or df.empty or not label_cols:
        return None, None, []

    # 0. Nếu có cả first_name và last_name, ưu tiên ghép lại làm nhãn đầy đủ
    c_low_map = {c.lower(): c for c in label_cols}
    if "first_name" in c_low_map and "last_name" in c_low_map:
        f_col = c_low_map["first_name"]
        l_col = c_low_map["last_name"]
        full_name_series = df[f_col].astype(str) + " " + df[l_col].astype(str)
        return "Họ và Tên", full_name_series, [f_col, l_col]

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


def generate_starter_prompts(tables: list[str], schema_context: str = "") -> list[dict]:
    """Tự động sinh 4 thẻ gợi ý câu hỏi thông minh 1-chạm bám sát chính xác nghiệp vụ và cấu trúc bảng của CSDL."""
    tables_lower = [t.lower() for t in tables]
    all_text = (" ".join(tables_lower) + " " + (schema_context or "").lower()).strip()

    cards = []

    # 1. Nhận diện các miền dữ liệu (Domains)
    has_hr = any(t in tables_lower for t in ["employees", "nhan_vien", "salaries", "luong", "departments", "phong_ban", "titles", "dept_emp", "staff", "payroll"])
    has_sales = any(t in tables_lower for t in ["sales", "orders", "don_hang", "order_details", "transactions", "invoices", "hoa_don"])
    has_product = any(t in tables_lower for t in ["products", "san_pham", "items", "hang_hoa"])
    has_education = any(t in tables_lower for t in ["students", "hoc_sinh", "courses", "khoa_hoc", "classes", "lop_hoc", "grades", "diem_thi"])
    has_healthcare = any(t in tables_lower for t in ["patients", "benh_nhan", "doctors", "bac_si", "appointments", "lich_kham"])
    has_finance = any(t in tables_lower for t in ["accounts", "tai_khoan", "loans", "vay_von", "cards", "the_ngan_hang"])

    # 2. Miền HR / Nhân sự / Tiền lương (như CSDL employees)
    if has_hr and not has_sales:
        if "salaries" in tables_lower or "luong" in tables_lower or "salary" in all_text:
            cards.append({
                "icon": "💰",
                "title": "Mức Lương Trung Bình Theo Phòng Ban",
                "prompt": "Mức lương trung bình của nhân viên theo từng phòng ban",
                "desc": "So sánh thu nhập bình quân giữa các đơn vị và phòng ban"
            })
            cards.append({
                "icon": "🏆",
                "title": "Top 10 Nhân Viên Lương Cao Nhất",
                "prompt": "Top 10 nhân viên có mức lương cao nhất",
                "desc": "Danh sách nhân sự có đãi ngộ và thu nhập cao nhất"
            })
        if "titles" in tables_lower or "chuc_danh" in tables_lower or "title" in all_text:
            cards.append({
                "icon": "👔",
                "title": "Cơ Cấu Nhân Sự Theo Chức Danh",
                "prompt": "Thống kê số lượng nhân viên theo từng chức danh (title)",
                "desc": "Phân bổ nhân sự theo các vị trí công việc"
            })
        if "departments" in tables_lower or "phong_ban" in tables_lower or "dept" in all_text:
            cards.append({
                "icon": "🏢",
                "title": "Quy Mô Nhân Sự Từng Phòng Ban",
                "prompt": "Số lượng nhân viên đang làm việc tại mỗi phòng ban",
                "desc": "Đánh giá quy mô nhân lực của từng bộ phận"
            })
        while len(cards) < 4:
            cards.append({
                "icon": "👥",
                "title": "Danh Sách Nhân Sự",
                "prompt": "Top 10 nhân viên mới nhất trong hệ thống",
                "desc": "Xem danh sách và thông tin hồ sơ nhân sự"
            })

    # 3. Miền Giáo dục / Trường học
    elif has_education:
        cards.append({
            "icon": "🎓",
            "title": "Điểm Số Trung Bình Theo Môn Học",
            "prompt": "Điểm số trung bình của học viên theo từng môn học",
            "desc": "Đánh giá kết quả học tập và phân bố điểm số"
        })
        cards.append({
            "icon": "📚",
            "title": "Số Lượng Học Viên Đăng Ký",
            "prompt": "Thống kê số lượng học viên theo từng khóa học",
            "desc": "Xác định các khóa học thu hút nhiều học viên nhất"
        })
        cards.append({
            "icon": "🏆",
            "title": "Top 10 Học Viên Xuất Sắc",
            "prompt": "Top 10 học viên có điểm số cao nhất",
            "desc": "Bảng vinh danh các cá nhân có thành tích cao"
        })
        cards.append({
            "icon": "🏫",
            "title": "Quy Mô Đào Tạo Theo Khoa / Lớp",
            "prompt": "Số lượng học viên phân bổ theo từng lớp",
            "desc": "Thống kê sĩ số và quy mô tổ chức các lớp học"
        })

    # 4. Miền Y tế / Bệnh viện
    elif has_healthcare:
        cards.append({
            "icon": "🏥",
            "title": "Số Lượng Bệnh Nhân Theo Chuyên Khoa",
            "prompt": "Thống kê số lượng bệnh nhân theo từng chuyên khoa",
            "desc": "Phân tích lưu lượng bệnh nhân khám và điều trị"
        })
        cards.append({
            "icon": "📅",
            "title": "Lượt Khám Bệnh Theo Tháng",
            "prompt": "Tổng số lượt khám bệnh theo từng tháng",
            "desc": "Theo dõi biến động số ca khám theo thời gian"
        })
        cards.append({
            "icon": "🩺",
            "title": "Top Bác Sĩ Tiếp Nhận Nhiều Ca Nhất",
            "prompt": "Top 10 bác sĩ có số lượt khám cao nhất",
            "desc": "Đánh giá công suất phục vụ của đội ngũ y bác sĩ"
        })
        cards.append({
            "icon": "📋",
            "title": "Thống Kê Ca Khám Mới Nhất",
            "prompt": "Danh sách 10 lượt khám mới nhất",
            "desc": "Xem chi tiết nhật ký tiếp nhận bệnh nhân"
        })

    # 5. Miền Bán hàng / Kinh doanh / Thương mại (Sales & Retail)
    elif has_sales or has_product:
        if has_product:
            cards.append({
                "icon": "📦",
                "title": "Top Sản Phẩm Doanh Thu Cao Nhất",
                "prompt": "Top 5 sản phẩm mang lại doanh thu cao nhất",
                "desc": "Xếp hạng sản phẩm theo tổng số tiền bán được"
            })
        else:
            cards.append({
                "icon": "📊",
                "title": "Tổng Quan Doanh Thu",
                "prompt": "Tổng doanh thu và số lượng đơn hàng đã bán",
                "desc": "Thống kê toàn diện hiệu quả kinh doanh"
            })

        cards.append({
            "icon": "📈",
            "title": "Xu Hướng Doanh Thu Theo Tháng",
            "prompt": "Tổng doanh thu theo từng tháng",
            "desc": "Phân tích biến động doanh số và chu kỳ tăng trưởng"
        })

        if any(t in tables_lower for t in ["people", "salespersons", "nhan_vien", "employees", "customers", "khach_hang"]):
            cards.append({
                "icon": "👥",
                "title": "Xếp Hạng Người Bán Hàng Xuất Sắc",
                "prompt": "Top 10 nhân sự có doanh số bán hàng cao nhất",
                "desc": "Đánh giá hiệu suất kinh doanh của từng nhân sự"
            })

        if any(t in tables_lower for t in ["geo", "regions", "countries", "locations", "khu_vuc"]):
            cards.append({
                "icon": "🌍",
                "title": "Phân Bổ Doanh Thu Theo Thị Trường",
                "prompt": "Tổng doanh thu theo từng quốc gia và khu vực",
                "desc": "Biểu đồ so sánh doanh số giữa các thị trường địa lý"
            })

    # 6. Fallback linh hoạt dựa theo danh sách bảng thực tế của CSDL
    if len(cards) < 4:
        icons = ["📊", "🔍", "📈", "📁", "✨", "📌"]
        for i, t in enumerate(tables[:4]):
            if len(cards) >= 4:
                break
            icon = icons[i % len(icons)]
            cards.append({
                "icon": icon,
                "title": f"Thống Kê Bảng {t.title()}",
                "prompt": f"Thống kê tổng số lượng bản ghi và xem dữ liệu bảng {t}",
                "desc": f"Khám phá cấu trúc và dữ liệu thực tế của bảng {t}"
            })

    # Đảm bảo luôn có đủ 4 thẻ
    while len(cards) < 4:
        cards.append({
            "icon": "🔍",
            "title": "Tổng Quan Cơ Sở Dữ Liệu",
            "prompt": "Thống kê tổng số lượng bản ghi trên tất cả các bảng",
            "desc": "Tổng hợp bức tranh toàn cảnh về dữ liệu hiện tại"
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

    lines = text.splitlines()
    cleaned_lines = []

    for line in lines:
        l = line.strip()
        if not l:
            continue

        # Giữ nguyên các tiêu đề Markdown lớn
        if l.startswith("#"):
            cleaned_lines.append(l)
            continue

        # Bỏ dòng rác chỉ chứa bullet hoặc icon đơn độc
        if re.fullmatch(r"[•\-\*🔴🟡🟢\s\.\:]+", l):
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

        # F. Nếu là dòng KPI đứng riêng (VD: '• Chỉ số KPI / kết quả đo lường kỳ vọng: ...')
        kpi_standalone = re.match(r"^[•\-\*]?\s*(?:Chỉ số\s+)?KPI(?:\s*\/\s*kết quả đo lường kỳ vọng|\s+đo lường|\s+kỳ vọng)?\s*[:\s]+(.*)$", l, flags=re.IGNORECASE)
        if kpi_standalone:
            desc = kpi_standalone.group(1).replace("**", "").replace("*", "").strip()
            if desc:
                desc = desc[0].upper() + desc[1:]
            cleaned_lines.append(f"  - **KPI kỳ vọng**: {desc}")
            continue

        # G. Tách KPI nếu nằm trong câu hành động
        kpi_part = None
        kpi_match = re.search(r"(?:,\s*)?(?:với\s+)?(KPI\s+(?:đo lường|kỳ vọng|đo lường kỳ vọng|dự kiến))\s*(?:là|:)\s*(.*)$", l, flags=re.IGNORECASE)
        if kpi_match and len(kpi_match.group(2).strip()) > 3:
            kpi_title = kpi_match.group(1).strip()
            kpi_desc = kpi_match.group(2).strip().rstrip(".").replace("**", "").replace("*", "")
            if kpi_desc:
                kpi_desc = kpi_desc[0].upper() + kpi_desc[1:]
            kpi_part = f"  - **{kpi_title}**: {kpi_desc}."
            l = l[:kpi_match.start()].strip()
            if not l.endswith("."):
                l += "."

        # H. QUY TẮC: KHÔNG ĐƯỢC TỰ Ý IN ĐẬM Ở TRONG CÂU
        # Chuẩn hóa mục 2.3 với nhãn ưu tiên in đậm và biểu tượng màu
        p_type = None
        if "Ưu tiên Cao" in l or "High Priority" in l:
            p_type = "Cao"
        elif "Ưu tiên Trung bình" in l or "Medium Priority" in l:
            p_type = "Trung bình"
        elif "Ưu tiên Thấp" in l or "Low Priority" in l:
            p_type = "Thấp"

        if p_type:
            # Loại bỏ toàn bộ tiền tố ưu tiên bị lặp lại ở đầu câu
            body = l
            for _ in range(3):
                body = re.sub(r"^[•\-\*]?\s*(?:[🔴🟡🟢]\s*)?\[?(?:Ưu tiên (?:Cao|Trung bình|Thấp)|High Priority|Medium Priority|Low Priority)[^\]:]*\]?:?\s*", "", body, flags=re.IGNORECASE).strip()
                body = re.sub(r"^[•\-\*]?\s*(?:[🔴🟡🟢]\s*)?", "", body).strip()

            body = body.replace("**", "").replace("*", "").strip()
            # Nếu dòng chỉ là tiêu đề không có nội dung hành động -> bỏ qua dòng rác này
            if len(body) < 5 or body.lower() in ("[ưu tiên cao]", "[ưu tiên trung bình]", "[ưu tiên thấp]"):
                continue

            if p_type == "Cao":
                l = f"• 🔴 **[Ưu tiên Cao - Thực hiện Ngay]**: {body}"
            elif p_type == "Trung bình":
                l = f"• 🟡 **[Ưu tiên Trung bình - Quý tiếp theo]**: {body}"
            else:
                l = f"• 🟢 **[Ưu tiên Thấp / Dài hạn]**: {body}"

        elif ":" in l:
            prefix, rest = l.split(":", 1)
            clean_p = prefix.replace("**", "").replace("*", "").strip()

            bullet_char = "•"
            if clean_p.startswith("-") or clean_p.startswith("*"):
                bullet_char = clean_p[0]

            clean_tag = clean_p.lstrip("•-* ").strip()

            if clean_tag.lower().startswith("kpi") or "kpi" in clean_tag.lower():
                prefix_out = f"  - **{clean_tag}**"
            else:
                if len(clean_tag.split()) > 10:
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
        if kpi_part:
            cleaned_lines.append(kpi_part)

    text = "\n\n".join(cleaned_lines)

    # 6. Đảm bảo tiêu đề 2.1, 2.2, 2.3 luôn tồn tại và được định dạng chuẩn
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

    # Khôi phục các thuật ngữ viết tắt chuẩn xác
    text = re.sub(r"\bB\s*2\s*B\b", "B2B", text, flags=re.IGNORECASE)
    text = re.sub(r"\bB\s*2\s*C\b", "B2C", text, flags=re.IGNORECASE)

    # Dọn dẹp dòng trống thừa
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
