"""
Column classification, language detection, starter prompts generator, and heuristic utilities for business datasets.
"""

import re
import pandas as pd
from src.config import ID_LIKE_REGEX, NAME_LIKE_REGEX, TIME_KEYWORDS, INDIVIDUAL_ENTITY_REGEX

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

    # 0.1 Nếu có cột thuộc về thực thể cá nhân (Salesperson, Product, Employee, Customer...)
    # BẮT BUỘC ưu tiên thực thể cá nhân này làm trục X thay vì cột nhóm phân loại (Team, Region, Category)
    individual_candidates = [c for c in label_cols if INDIVIDUAL_ENTITY_REGEX.search(str(c))]
    if individual_candidates:
        chosen_ind = sorted(individual_candidates, key=lambda c: df[c].nunique(dropna=True), reverse=True)[0]
        return chosen_ind, df[chosen_ind].astype(str), [chosen_ind]

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
        cards.append({
            "icon": "⚖️",
            "title": "So Sánh Lương Nam vs Nữ Theo Chức Danh",
            "prompt": "So sánh mức lương trung bình giữa nhân viên nam và nữ theo từng chức danh",
            "desc": "Phân tích đối chuẩn công bằng thu nhập và thu hẹp khoảng cách giới"
        })
        cards.append({
            "icon": "💰",
            "title": "Top 10 Lương Cao Nhất Phòng Sales",
            "prompt": "Top 10 nhân viên có mức lương cao nhất trong phòng ban Sales",
            "desc": "Danh sách nhân sự xuất sắc có thu nhập cao nhất khối Kinh doanh"
        })
        cards.append({
            "icon": "📅",
            "title": "Xu Hướng Tuyển Dụng Theo Từng Năm",
            "prompt": "Thống kê số lượng nhân viên được tuyển dụng theo từng năm từ trước đến nay",
            "desc": "Phân tích tốc độ tăng trưởng quy mô tổ chức qua các thời kỳ"
        })
        cards.append({
            "icon": "🚻",
            "title": "Tỷ Lệ Giới Tính Ban Quản Lý (Manager)",
            "prompt": "Tỷ lệ nam và nữ trong ban quản lý (dept_manager) của từng phòng ban",
            "desc": "Đo lường cơ cấu đa dạng giới trong đội ngũ lãnh đạo phòng ban"
        })
        cards.append({
            "icon": "🏢",
            "title": "Chênh Lệch Lương Nội Bộ Phòng Ban",
            "prompt": "Phòng ban nào có mức chênh lệch lương giữa người cao nhất và thấp nhất lớn nhất?",
            "desc": "Phát hiện khoảng cách phân hóa thu nhập nội bộ từng đơn vị"
        })
        cards.append({
            "icon": "👔",
            "title": "Danh Sách Trưởng Phòng & Mức Lương",
            "prompt": "Danh sách các Manager hiện tại của từng phòng ban kèm mức lương mới nhất",
            "desc": "Tổng hợp hồ sơ đãi ngộ của toàn bộ ban lãnh đạo quản lý"
        })

    # 3. Miền Bán hàng & Sản phẩm (như CSDL Awesome Chocolates)
    elif has_sales and has_product:
        cards.append({
            "icon": "📦",
            "title": "Tỷ Lệ Đóng Góp Doanh Thu Nhóm Hàng",
            "prompt": "Tỷ lệ đóng góp doanh thu của từng nhóm sản phẩm (Category) vào tổng doanh thu",
            "desc": "Phân tích cơ cấu danh mục hàng hóa và tỷ trọng doanh thu"
        })
        cards.append({
            "icon": "🏆",
            "title": "So Sánh Hiệu Suất Các Team Bán Hàng",
            "prompt": "So sánh tổng doanh số và số lượng hộp bán ra giữa các Team kinh doanh",
            "desc": "Đánh giá hiệu suất cạnh tranh giữa các đội ngũ bán hàng"
        })
        cards.append({
            "icon": "🌍",
            "title": "Xu Hướng Doanh Thu Từng Quốc Gia",
            "prompt": "Doanh thu theo từng quốc gia (Country) thay đổi như thế nào qua các tháng?",
            "desc": "Theo dõi biểu đồ tăng trưởng thị trường quốc tế theo chuỗi thời gian"
        })
        cards.append({
            "icon": "🏷️",
            "title": "Lợi Nhuận Trung Bình Mỗi Hộp Sô-cô-la",
            "prompt": "Mức lợi nhuận trung bình trên mỗi hộp (Profit per box) của từng dòng sản phẩm",
            "desc": "Xác định các mặt hàng có biên lợi nhuận cao nhất"
        })
        cards.append({
            "icon": "👥",
            "title": "Chuyên Viên Đạt Doanh Số > 50,000 USD",
            "prompt": "Những nhân viên bán hàng có tổng doanh số vượt mức 50,000 USD",
            "desc": "Vinh danh các chuyên viên kinh doanh đạt mốc doanh số ấn tượng"
        })
        cards.append({
            "icon": "🍫",
            "title": "Top 10 Sản Phẩm Bán Chạy Nhất",
            "prompt": "Top 10 sản phẩm có tổng doanh số bán ra cao nhất",
            "desc": "Xếp hạng các sản phẩm chủ lực mang lại nguồn thu lớn nhất"
        })
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

    # 0. Sửa lỗi số tiền có khoảng trắng thừa sau dấu phẩy: 1, 837, 388.00 -> 1,837,388.00
    for _ in range(4):
        text = re.sub(r"(\d{1,3}),\s+(\d{3})", r"\g<1>,\g<2>", text)

    # 0.1 Chuẩn hóa tiêu đề 2.1, 2.2, 2.3 thành ### trước khi xử lý (chấp nhận cả bullet •, -, *, số thứ tự 1., 2., 3.)
    text = re.sub(r"^[•\-\*#\s]*(?:1|2\.1)?[\.\)]?\s*(?:🚨\s*)?(Phát hiện Bất thường.*)", r"### 2.1. 🚨 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^[•\-\*#\s]*(?:2|2\.2)?[\.\)]?\s*(?:🔍\s*)?(Giả thuyết & Nguyên nhân.*)", r"### 2.2. 🔍 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^[•\-\*#\s]*(?:3|2\.3)?[\.\)]?\s*(?:🎯\s*)?(Đề xuất Hành động.*)", r"### 2.3. 🎯 \g<1>", text, flags=re.IGNORECASE | re.MULTILINE)

    # 1. Thay thế ký tự bullet lạ tiếng Trung 。・ thành ký hiệu thụt lề chuẩn
    text = re.sub(r"^[。・]\s*", "   - ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[。・]\s*", "   - ", text, flags=re.MULTILINE)

    # 2. Xóa các tiền tố #### trước nhãn ưu tiên và sửa lỗi 2 dấu hai chấm
    text = re.sub(r"#+\s*(\[(?:Ưu tiên|High Priority|Medium Priority|Low Priority))", r"\g<1>", text)
    text = re.sub(r"\]\s*:\s*:\s*", "]: ", text)
    text = re.sub(r"\s*:\s*:\s*", ": ", text)
    text = re.sub(r":\s*:\s*", ": ", text)

    # 3. Sửa lỗi chính tả phổ biến
    text = text.replace("đư ợc", "được").replace("đư ọc", "được")

    # 4. Tự động tách dòng cho các ý phân tích bị dính liền trên cùng 1 đoạn văn
    text = re.sub(r"(?<=[^\n])\s+•\s*", "\n\n• ", text)
    text = re.sub(r"(?<=[^\n•\-\*\s🔴🟡🟢])\s+(\[(?:Ưu tiên|High Priority|Medium Priority|Low Priority))", r"\n\n• \g<1>", text)

    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = []
    i = 0
    while i < len(raw_lines):
        curr = raw_lines[i]
        if i + 1 < len(raw_lines):
            next_l = raw_lines[i + 1]
            p_curr = next((p for p in ['Ưu tiên Cao', 'Ưu tiên Trung bình', 'Ưu tiên Thấp', 'High Priority', 'Medium Priority', 'Low Priority'] if p in curr), None)
            p_next = next((p for p in ['Ưu tiên Cao', 'Ưu tiên Trung bình', 'Ưu tiên Thấp', 'High Priority', 'Medium Priority', 'Low Priority'] if p in next_l), None)

            # Nếu 2 dòng liên tiếp cùng 1 mức ưu tiên và dòng 1 là tiêu đề ngắn
            if p_curr and p_curr == p_next:
                body_curr = re.sub(r"^.*\]\s*:?\s*:?\s*", "", curr).strip()
                body_curr = re.sub(r"^\d+[\.\)]\s*", "", body_curr).strip()
                body_curr = re.sub(r"^[:\s\-\•\*\.]+", "", body_curr).strip()
                body_curr = re.sub(r"[:\s]+$", "", body_curr).strip()

                body_next = re.sub(r"^.*\]\s*:?\s*:?\s*", "", next_l).strip()
                body_next = re.sub(r"^\d+[\.\)]\s*", "", body_next).strip()
                body_next = re.sub(r"^[:\s\-\•\*\.]+", "", body_next).strip()

                tag_part = curr.split("]")[0] + "]"
                if body_curr and body_next:
                    curr = f"{tag_part}: {body_curr} - {body_next}"
                else:
                    curr = f"{tag_part}: {body_curr or body_next}"
                i += 2
                lines.append(curr)
                continue
        lines.append(curr)
        i += 1
    cleaned_lines = []
    skip_example_block = False

    for line in lines:
        l = line.strip()
        if not l:
            continue

        # Giữ nguyên các tiêu đề Markdown lớn
        if l.startswith("#"):
            skip_example_block = False
            cleaned_lines.append(l)
            continue

        # Nếu đang trong khối ví dụ mẫu của AI chép lại -> bỏ qua
        if skip_example_block:
            continue

        # Bỏ dòng rác chỉ chứa bullet, icon hoặc đường kẻ phân cách bảng (+---+, |)
        if re.fullmatch(r"[•\-\*🔴🟡🟢\s\.\:\+\|_=]+", l):
            continue

        # Bỏ qua các dòng ví dụ mẫu bị AI sao chép: Ví dụ chuẩn:, Ví dụ:... và bỏ toàn bộ các dòng ví dụ theo sau
        if re.search(r"^[•\-\*#\s]*(?:ví dụ chuẩn|ví dụ|example)[:\s]*", l, re.IGNORECASE):
            skip_example_block = True
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
        kpi_match = re.search(r"(?:,\s*)?(?:với\s+)?((?:KPI|Mục tiêu|Chỉ số)\s+(?:đo lường|kỳ vọng|đo lường kỳ vọng|dự kiến))\s*(?:là|:)\s*(.*)$", l, flags=re.IGNORECASE)
        if kpi_match and len(kpi_match.group(2).strip()) > 3:
            kpi_title = kpi_match.group(1).strip()
            kpi_desc = kpi_match.group(2).strip().rstrip(".").replace("**", "").replace("*", "")
            if kpi_desc:
                kpi_desc = kpi_desc[0].upper() + kpi_desc[1:]
            kpi_part = f"  - **{kpi_title}**: {kpi_desc}."
            l = l[:kpi_match.start()].strip()
            if not l.endswith("."):
                l += "."

        # Bỏ qua các tiêu đề phụ thừa thãi không có nội dung: Xu hướng Chính, Giả thuyết:, Ghi Chép Nguyên Nhân...
        l_clean = l.lower().strip(":-•* ")
        if l_clean in [
            "xu hướng chính", "giả thuyết", "ghi chép nguyên nhân rất đáng phán hướng",
            "ghi chép nguyên nhân", "kết quả kinh doanh", "nguyên nhân tiềm năng", "nguyên nhân"
        ]:
            continue

        # Bóc tách và chuyển đổi các dòng bảng ASCII méo mó (- | Dự Án | Tiêu Định | Thời Gian |)
        if "|" in l:
            # Bỏ qua dòng ranh giới bảng: +----+ hoặc |
            if re.search(r"^[\|\+\-\s=]+$", l):
                continue
            cells = [c.strip() for c in l.split("|") if c.strip() and not set(c.strip()).issubset({'-', '+', '=', ' '})]
            # Bỏ qua dòng tiêu đề cột: | Dự Án | Tiêu Định | Thời Gian |
            if any(h in "".join(cells).lower() for h in ["dự án", "tiêu định", "thời gian", "kế hoạch", "action", "timeframe"]):
                continue
            if len(cells) >= 2:
                time_cell = cells[-1].lower() if len(cells) >= 3 else ""
                action_cell = cells[0].lstrip("-•* ")
                goal_cell = cells[1].lstrip("-•* ") if len(cells) >= 2 else ""

                p_level = "Cao"
                if any(k in time_cell for k in ["trung bình", "quý", "next quarter", "medium"]):
                    p_level = "Trung bình"
                elif any(k in time_cell for k in ["thấp", "long-term", "dài hạn", "low"]):
                    p_level = "Thấp"
                elif any(k in time_cell for k in ["ngay", "immediate", "cao", "gấp"]):
                    p_level = "Cao"

                detail_text = f"{action_cell} - {goal_cell}".strip(" -")
                if p_level == "Cao":
                    l = f"• 🔴 **[Ưu tiên Cao - Thực hiện Ngay]**: {detail_text}"
                elif p_level == "Trung bình":
                    l = f"• 🟡 **[Ưu tiên Trung bình - Quý tiếp theo]**: {detail_text}"
                else:
                    l = f"• 🟢 **[Ưu tiên Thấp / Dài hạn]**: {detail_text}"
            else:
                continue

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
            # Dọn sạch triệt để mọi dấu hai chấm kép, số thứ tự và dấu gạch thừa
            body = re.sub(r"^[:\s\-\•\*\.]+", "", body).strip()
            body = re.sub(r"^\d+[\.\)]\s*", "", body).strip()
            body = re.sub(r"^[:\s\-\•\*\.]+", "", body).strip()
            body = re.sub(r"\s*:\s*:\s*", ": ", body)
            body = re.sub(r":\s*:\s*", ": ", body)

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


def sanitize_followup_question(q: str) -> str:
    """Làm sạch câu hỏi gợi ý phân tích tiếp nối:
    - Bóc tách cấu trúc dict rác nếu AI trả về string dạng {'question': '...'}
    - Chuyển đổi ký tự tiếng Hàn/Trung lạ (như '각' -> 'từng')
    - Tách từ dính tiếng Việt và tiếng Anh (mụcBars -> mục Bars)
    - Tách từ tiếng Anh và từ nối tiếng Việt (Barsvà -> Bars và)
    """
    if not q:
        return ""
    q = str(q).strip()

    # Bóc tách nếu là chuỗi dict hoặc json string: {'question': '...'} hoặc {"question": "..."}
    m_dict = re.match(r"^\{['\"](?:question|prompt|query)['\"]\s*:\s*['\"](.*)['\"]\}$", q, re.DOTALL)
    if m_dict:
        q = m_dict.group(1).strip()
    else:
        # Nếu chỉ có tiền tố/hậu tố {'question':
        q = re.sub(r"^\{['\"](?:question|prompt|query)['\"]\s*:\s*['\"]?", "", q)
        q = re.sub(r"['\"]?\}$", "", q).strip()

    q = q.replace("각", "từng")
    q = re.sub(r"[\u4e00-\u9fff\uac00-\ud7af]+", "", q)
    q = re.sub(r"([a-zà-ỹ])([A-Z])", r"\g<1> \g<2>", q)
    q = re.sub(r"([a-zA-Z]{2,})(để|và|với|chiếm|trong|của|cho|tại|theo|đạt|có|so)", r"\g<1> \g<2>", q)
    q = re.sub(r"(để|và|với|chiếm|trong|của|cho|tại|theo|đạt|có|so)([a-zA-Z]{3,})", r"\g<1> \g<2>", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def generate_data_grounded_action_plan(df: pd.DataFrame, is_en: bool = False) -> str:
    """Tự động sinh Đề xuất Chiến lược AI phân cấp 3 bậc (Cấp bách, Trung hạn, Dài hạn) bám chặt vào số liệu thực tế từ DataFrame."""
    if df is None or df.empty:
        if is_en:
            return (
                "• 🔴 **[High Priority - Immediate Action / 0-30 Days]**: Audit operational anomalies and establish a rapid response taskforce.\n\n"
                "• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Standardize resource allocation and optimize workflow benchmarks.\n\n"
                "• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Drive digital transformation and implement sustainable policy frameworks."
            )
        return (
            "• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát các điểm bất thường vận hành và thành lập tổ công tác phản ứng nhanh.\n\n"
            "• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa quy trình phân bổ nguồn lực và định mức chi phí theo thực tế.\n\n"
            "• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách tổng thể, đẩy mạnh chuyển đổi số và nâng cao năng lực cạnh tranh dài hạn."
        )

    cols = df.columns.tolist()
    num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [c for c in cols if c not in num_cols]

    val_col = num_cols[-1] if num_cols else None
    name_col = cat_cols[0] if cat_cols else (num_cols[0] if len(num_cols) > 1 else None)

    if not val_col or not name_col:
        return (
            "• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Thiết lập cơ chế kiểm soát tức thời và ngăn ngừa rủi ro dữ liệu sai lệch.\n\n"
            "• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa hệ thống báo cáo và liên kết chỉ tiêu KPI với hiệu quả thực tế.\n\n"
            "• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Đầu tư mở rộng danh mục chiến lược và xây dựng hệ thống quản trị chủ động."
        )

    sorted_df = df.sort_values(by=val_col, ascending=False)
    top_row = sorted_df.iloc[0]
    bot_row = sorted_df.iloc[-1]
    top_name, top_val = str(top_row[name_col]), top_row[val_col]
    bot_name, bot_val = str(bot_row[name_col]), bot_row[val_col]

    mean_val = df[val_col].mean()
    median_val = df[val_col].median()
    diff = top_val - bot_val
    spread_pct = (diff / bot_val * 100) if bot_val != 0 else 0

    cols_str = " ".join(str(c).lower() for c in cols)
    is_time_series = any(k in cols_str for k in ["year", "month", "date", "năm", "tháng", "ngày", "hire", "hiredate", "hireyear"])
    is_salary = any(k in cols_str for k in ["salary", "lương", "wage", "pay", "thu_nhập", "raisecount", "raise"])

    if is_en:
        if is_time_series:
            urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Investigate root causes behind the sharpest volume decline ({bot_name}: {bot_val:,.0f} vs peak {top_name}: {top_val:,.0f}); coordinate with HR/Operations to mitigate operational bottlenecks."
            medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Standardize resource allocation around the benchmark average of {mean_val:,.0f} units per period; build proactive contingency staffing plans."
            longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Transition from reactive hiring to AI-driven predictive workforce planning; strengthen employer branding and long-term talent retention."
        elif is_salary:
            urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit compensation parity across roles with the widest disparity ({top_name}: {top_val:,.0f} USD vs {bot_name}: {bot_val:,.0f} USD, spread {spread_pct:.1f}%); curb flight risk among key talent."
            medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Benchmark career progression bands against the median baseline of {median_val:,.0f} USD; rebalance department budget pools for internal equity."
            longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Overhaul the Total Rewards framework, combining market-competitive compensation with transparent merit-based promotions."
        else:
            urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Allocate focused resources to protect and scale the market leader {top_name} ({top_val:,.0f}), while remediating underperformance in {bot_name} ({bot_val:,.0f})."
            medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Realign portfolio performance targets around the group average of {mean_val:,.0f}; institutionalize leading practices across all units."
            longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Invest in strategic market expansion, automated analytics infrastructure, and sustained competitive positioning."
    else:
        if is_time_series:
            urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát khẩn cấp nguyên nhân kỳ sụt giảm sâu nhất ({bot_name}: {bot_val:,.0f} so với đỉnh {top_name}: {top_val:,.0f}); tổ chức đối thoại với các đơn vị liên quan để kiểm soát rủi ro gián đoạn vận hành."
            medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa kế hoạch tuyển dụng và định mức ngân sách quanh mức trung bình {mean_val:,.0f} nhân sự/kỳ; thiết lập kịch bản dự phòng linh hoạt theo từng quý."
            longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Chuyển đổi mô hình quản trị nhân tài sang hoạch định dự báo bằng AI; xây dựng thương hiệu tuyển dụng bền vững và tối ưu hóa năng suất dài hạn."
        elif is_salary:
            urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát khung đãi ngộ tại nhóm có chênh lệch lớn nhất ({top_name} đạt {top_val:,.0f} USD so với {bot_name} là {bot_val:,.0f} USD, chênh lệch {spread_pct:.1f}%); ngăn chặn rủi ro chảy máu chất xám ở vị trí chủ chốt."
            medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Thiết lập cơ chế đánh giá năng lực gắn liền với mức trung vị tham chiếu {median_val:,.0f} USD; tái cân bằng quỹ lương giữa các khối để đảm bảo công bằng nội bộ."
            longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách đãi ngộ tổng thể (Total Rewards), kết hợp lương cạnh tranh và lộ trình thăng tiến minh bạch để thu hút nhân tài cấp cao."
        else:
            urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Tập trung nguồn lực bảo vệ và mở rộng vị thế dẫn đầu của {top_name} ({top_val:,.0f}), đồng thời đánh giá nguyên nhân kém hiệu quả tại nhóm {bot_name} ({bot_val:,.0f})."
            medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Tái cấu trúc quy trình phân bổ nguồn lực dựa trên mức trung bình {mean_val:,.0f}; nhân rộng kinh nghiệm thành công của nhóm dẫn đầu sang toàn hệ thống."
            longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Đầu tư mở rộng danh mục chiến lược, tự động hóa quy trình phân tích và nâng cao năng lực cạnh tranh dài hạn trên thị trường."

    return f"{urgent}\n\n{medium}\n\n{longterm}"


def split_insight_sections(markdown_text: str, df: pd.DataFrame = None) -> dict[str, str]:
    """Bóc tách nội dung insight thành 3 phần riêng biệt để hiển thị dạng 3 Card UI chuyên nghiệp."""
    if not markdown_text:
        # Nếu không có text (chạy Ollama cục bộ), tự động sinh đầy đủ 3 phần từ dữ liệu thực tế
        part_21 = ""
        part_22 = ""
        if df is not None and not df.empty:
            cols = df.columns.tolist()
            num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
            cat_cols = [c for c in cols if c not in num_cols]
            if num_cols and cat_cols:
                val_col = num_cols[-1]
                name_col = cat_cols[0]
                sorted_df = df.sort_values(by=val_col, ascending=False)
                top_row = sorted_df.iloc[0]
                bot_row = sorted_df.iloc[-1]
                top_name, top_val = top_row[name_col], top_row[val_col]
                bot_name, bot_val = bot_row[name_col], bot_row[val_col]
                spread_diff = top_val - bot_val
                spread_pct = (spread_diff / bot_val) * 100 if bot_val != 0 else 0
                median_val = df[val_col].median()
                part_21 = (
                    f"• **Dẫn đầu toàn diện**: Nhóm **{top_name}** đạt mức cao nhất ({top_val:,.2f}), thể hiện vai trò nòng cốt.\n\n"
                    f"• **Khoảng cách phân bổ**: Nhóm **{bot_name}** ở mức {bot_val:,.2f} (chênh lệch {spread_pct:.1f}% tương đương {spread_diff:,.2f} so với nhóm dẫn đầu).\n\n"
                    f"• **Mức trung vị tham chiếu**: Thu nhập/quy mô trung vị toàn bảng là {median_val:,.2f}, phản ánh mặt bằng chung ổn định."
                )
            cols_str = " ".join([str(c).lower() for c in df.columns])
            if any(k in cols_str for k in ["salary", "department", "emp", "title", "lương", "hire", "tuyển", "nhân_sự", "nhan_vien"]):
                part_22 = (
                    "• **Trách nhiệm & Quy mô đơn vị**: Các phòng ban/chức danh dẫn đầu có tính chất cạnh tranh cao, quy mô lớn và đóng góp trực tiếp vào mục tiêu cốt lõi nên có mức đãi ngộ vượt trội.\n\n"
                    "• **Chính sách đãi ngộ & Cạnh tranh nhân tài**: Sự chênh lệch thu nhập phản ánh định hướng của tổ chức trong việc thu hút nhân sự chuyên môn giỏi và giữ chân các vị trí nòng cốt."
                )
            else:
                part_22 = (
                    "• **Nhu cầu thị trường & Mùa vụ**: Nhóm sản phẩm/thị trường dẫn đầu đáp ứng tốt thị hiếu tiêu dùng và đón đầu hiệu quả các đợt cao điểm mua sắm.\n\n"
                    "• **Hiệu quả kênh phân phối**: Doanh số cao là kết quả của chiến lược xúc tiến thương mại mạnh mẽ và độ phủ sóng rộng khắp của đội ngũ bán hàng."
                )
        part_23 = generate_data_grounded_action_plan(df)
        return {"anomaly": part_21, "hypothesis": part_22, "action_plan": part_23}

    cleaned = sanitize_insight_markdown(markdown_text)

    # Tìm vị trí các header
    m21 = re.search(r"### 2\.1\.\s*🚨[^\n]*\n?", cleaned)
    m22 = re.search(r"### 2\.2\.\s*🔍[^\n]*\n?", cleaned)
    m23 = re.search(r"### 2\.3\.\s*🎯[^\n]*\n?", cleaned)

    idx21 = m21.start() if m21 else -1
    idx22 = m22.start() if m22 else -1
    idx23 = m23.start() if m23 else -1

    part_21 = ""
    part_22 = ""
    part_23 = ""

    if idx21 != -1:
        end21 = idx22 if idx22 != -1 else (idx23 if idx23 != -1 else len(cleaned))
        part_21 = cleaned[m21.end():end21].strip()

    if idx22 != -1:
        end22 = idx23 if idx23 != -1 else len(cleaned)
        part_22 = cleaned[m22.end():end22].strip()

    if idx23 != -1:
        part_23 = cleaned[m23.end():].strip()

    # 1. Làm sạch mục Phát hiện Bất thường & Xu hướng (part_21)
    noise_keywords = [
        "hiểu lý", "hiệu quả:", "một số thực tế", "nhà hàng", "đặt đơn hàng trực tuyến",
        "đặt hàng trực tuyến", "marketing nội hàng", "giảm chi phí vận hành", "bảo vệ khách hàng", "bán vé",
        "use ai", "machine learning", "tối ưuuize", "giảm giá sản phẩm",
        "thuật ngữ", "dịch không phù hợp", "chỉ số tham khảo", "tiếng anh", "nếu chúng ta tiếp tục",
        "bàn giao", "giả sử là", "tác dụng chính", "khắc chế", "stability", "производ", "trajectory", "fluctuate",
        "avgsalary", "averagesalary", "employee salary overview", "change from prev period", "difference from mean",
        "rank 1:", "difference from", "prev period", "from mean"
    ]

    def is_noise(text_line: str) -> bool:
        low = text_line.lower()
        return any(k in low for k in noise_keywords)

    def is_english_line(text_line: str) -> bool:
        """Kiểm tra nếu dòng văn bản chứa nhiều từ tiếng Anh (khi ngôn ngữ yêu cầu là tiếng Việt)."""
        english_indicators = [
            "department", "sales department", "finance department", "employee benefits",
            "is growing", "difference from", "change from", "average salary", "rank ",
            "out of", "with experience", "risk management", "financial planning",
            "market research", "accounting", "actively adapting", "growing steadily"
        ]
        low = text_line.lower()
        if any(ind in low for ind in english_indicators):
            return True
        words = low.split()
        if len(words) >= 4:
            common_en = {"is", "are", "the", "and", "in", "of", "to", "with", "for", "from", "by", "has", "have", "that"}
            en_matches = sum(1 for w in words if w in common_en)
            if en_matches >= 2:
                return True
        return False

    if part_21:
        lines_21 = [l.strip() for l in part_21.split("\n") if l.strip()]
        cleaned_21 = []
        for l in lines_21:
            if l.startswith("#") or "##" in l:
                continue
            clean_check = l.replace("**", "").replace("*", "").strip("•-* :")
            if is_noise(clean_check) or is_english_line(clean_check):
                continue
            # Loại bỏ các subheader gây lặp lại "Nguyên nhân tiềm năng" ở Thẻ 1
            if re.search(r"^(?:kỹ thuật\s*&\s*)?nguyên nhân(?:\s*tiềm năng)?$", clean_check, re.IGNORECASE):
                continue
            if re.search(r"^xu hướng(?:\s*chính)?$", clean_check, re.IGNORECASE):
                continue
            if re.search(r"^(?:phát hiện bất thường|xu hướng chính|bất thường & xu hướng)", clean_check, re.IGNORECASE):
                continue
            # Loại bỏ các dòng đọc vẹt thống kê Min/Max/Mean/Median/Bản ghi
            if re.search(r"tổng\s*(?:thống\s*kê|kết|hợp)?\s*dữ\s*liệu.*(?:mean|median|min|max|bản\s*ghi)", clean_check, re.IGNORECASE):
                continue
            if re.search(r"^(?:hai|các|những)?\s*điểm\s*bất\s*thường\s*(?:nhất)?\s*đã\s*được\s*(?:nhận\s*thấy|phát\s*hiện):?$", clean_check, re.IGNORECASE):
                continue
            if re.search(r"^(?:\d+[\.\)]\s*)?điểm\s+(?:thấp nhất|cao nhất|trung bình|trung vị)\s*\([A-Za-z]+\)\s*:\s*[\d,\.]+\s*-\s*không có dấu hiệu bất thường", clean_check, re.IGNORECASE):
                continue
            # Loại bỏ các dòng rời rạc giá trị nhỏ nhất / doanh thu thấp nhất
            if re.search(r"^(?:đơn giá thấp nhất|giá trị nhỏ nhất|doanh thu thấp nhất)\s*:\s*[\d,\.]+", clean_check, re.IGNORECASE):
                continue
            # Làm sạch tiền tố giả thuyết thừa nếu có
            l = re.sub(r"^[•\-\*]?\s*(?:Giả thuyết \d+:?\s*)+", "• ", l)
            if not l.startswith("•"):
                l = "• " + l
            cleaned_21.append(l)
        part_21 = "\n\n".join(cleaned_21)

    # Nếu part_21 rỗng hoặc bị lọc hết rác -> tự động tính toán số liệu thực tế từ DataFrame
    if (not part_21 or len([l for l in part_21.split("\n") if l.strip()]) < 2) and df is not None and not df.empty:
        cols = df.columns.tolist()
        num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        cat_cols = [c for c in cols if c not in num_cols]
        if num_cols and cat_cols:
            val_col = num_cols[0]
            name_col = cat_cols[0]
            sorted_df = df.sort_values(by=val_col, ascending=False)
            top_row = sorted_df.iloc[0]
            bot_row = sorted_df.iloc[-1]
            top_name, top_val = top_row[name_col], top_row[val_col]
            bot_name, bot_val = bot_row[name_col], bot_row[val_col]
            spread_diff = top_val - bot_val
            spread_pct = (spread_diff / bot_val) * 100 if bot_val != 0 else 0
            median_val = df[val_col].median()

            part_21 = (
                f"• **Dẫn đầu toàn diện**: Nhóm **{top_name}** đạt mức cao nhất ({top_val:,.2f}), thể hiện vai trò nòng cốt.\n\n"
                f"• **Khoảng cách phân bổ**: Nhóm **{bot_name}** ở mức {bot_val:,.2f} (chênh lệch {spread_pct:.1f}% tương đương {spread_diff:,.2f} so với nhóm dẫn đầu).\n\n"
                f"• **Mức trung vị tham chiếu**: Thu nhập trung vị toàn bảng là {median_val:,.2f}, phản ánh mặt bằng chung ổn định."
            )

    # 2. Làm sạch mục Giả thuyết & Nguyên nhân (part_22)
    if part_22:
        lines_22 = [l.strip() for l in part_22.split("\n") if l.strip()]
        cleaned_22 = []
        for l in lines_22:
            if l.startswith("#") or "##" in l:
                continue
            if re.search(r"^###?\s*2\.2", l, re.IGNORECASE):
                continue
            if is_noise(l) or is_english_line(l):
                continue
            clean_check = l.replace("**", "").replace("*", "").strip("•-* :")
            if re.search(r"^(?:giả thuyết|nguyên nhân|nguyên nhân tiềm năng)", clean_check, re.IGNORECASE):
                continue
            # Loại bỏ các nhãn ưu tiên rò rỉ vào Card 2
            if re.search(r"\[ưu\s*tiên\s*(?:cao|trung\s*bình|thấp)\]", l, re.IGNORECASE) or any(c in l for c in ["🔴", "🟡", "🟢"]):
                continue
            # Loại bỏ câu tiếng Anh lai tạp hoặc từ bịa đặt
            if re.search(r"\b(?:between|maintained|trajectory|fluctuate|consistent|trajectory)\b", l, re.IGNORECASE):
                continue
            if "kinh thuần" in l.lower() or "mùa thu mới" in l.lower():
                continue

            # Làm sạch triệt để các tiền tố lặp: Giả thuyết 1: Giả thuyết:, Nguyên nhân: Hiểu lý:
            l = re.sub(r"^[•\-\*]?\s*(?:Giả thuyết \d+:?\s*)+", "• ", l)
            l = re.sub(r"^[•\-\*]?\s*(?:Nguyên nhân:?\s*)+", "• ", l)
            l = re.sub(r"^[•\-\*]?\s*(?:Hiểu lý:?\s*)+", "• ", l)
            l = re.sub(r"^[•\-\*]?\s*Giả thuyết:?\s*", "• ", l)
            l = re.sub(r"^•\s*-\s*", "• ", l)
            clean_check = l.replace("**", "").replace("*", "").strip("•-* :")
            # Loại bỏ các tiêu đề mồ côi (chỉ có tiêu đề không có nội dung phân tích)
            if clean_check.endswith(":") or len(clean_check) < 30 or re.search(r"^(?:\d+[\.\)]\s*)?(?:quy mô|chính sách|tính chất|thị trường|đặc thù)", clean_check, re.IGNORECASE):
                continue
            if not l.startswith("•"):
                l = "• " + l
            cleaned_22.append(l)
        part_22 = "\n\n".join(cleaned_22)

    # Nếu part_22 rỗng do bị lọc hết rác/tiếng Anh -> tạo 2 giả thuyết executive chuẩn mực
    if not part_22 or len([l for l in part_22.split("\n") if l.strip()]) < 2:
        is_hr = False
        if df is not None and not df.empty:
            cols_str = " ".join([str(c).lower() for c in df.columns])
            if any(k in cols_str for k in ["salary", "department", "emp", "title", "lương", "hire", "tuyển", "nhân_sự", "nhan_vien"]):
                is_hr = True

        if is_hr:
            part_22 = (
                "• **Trách nhiệm & Quy mô đơn vị**: Các phòng ban/chức danh dẫn đầu có tính chất cạnh tranh cao, quy mô lớn và đóng góp trực tiếp vào mục tiêu cốt lõi nên có mức đãi ngộ vượt trội.\n\n"
                "• **Chính sách đãi ngộ & Cạnh tranh nhân tài**: Sự chênh lệch thu nhập phản ánh định hướng của tổ chức trong việc thu hút nhân sự chuyên môn giỏi và giữ chân các vị trí nòng cốt."
            )
        else:
            part_22 = (
                "• **Nhu cầu thị trường & Mùa vụ**: Nhóm sản phẩm/thị trường dẫn đầu đáp ứng tốt thị hiếu tiêu dùng và đón đầu hiệu quả các đợt cao điểm mua sắm.\n\n"
                "• **Hiệu quả kênh phân phối**: Doanh số cao là kết quả của chiến lược xúc tiến thương mại mạnh mẽ và độ phủ sóng rộng khắp của đội ngũ bán hàng."
            )

    # 3. Đảm bảo mục Kế hoạch Hành động (part_23) luôn có đủ 3 ý: Cao 🔴, Trung bình 🟡, Thấp 🟢
    if part_23:
        lines_23 = [l.strip() for l in part_23.split("\n") if l.strip()]
        cleaned_23 = []
        for l in lines_23:
            if l.startswith("#") or "##" in l:
                continue
            if is_noise(l):
                continue
            clean_check = l.replace("**", "").replace("*", "").strip("•-* :")
            if re.search(r"^(?:đề xuất|hành động|kế hoạch hành động|action plan)", clean_check, re.IGNORECASE):
                continue
            # Dọn sạch các icon cũ, nhãn cũ và dấu gạch ở đầu câu để định dạng chuẩn
            clean_body = re.sub(r"^[•\-\*]?\s*(?:\*\*)?\s*[🔴🟡🟢]?\s*(?:\*\*)?\s*", "", l).strip()
            clean_body = re.sub(r"^\[?(?:Ưu\s*tiên\s*(?:Cao|Trung\s*bình|Thấp)|High\s*Priority|Medium\s*Priority|Low\s*Priority)[^\]:]*\]?:?\s*", "", clean_body, flags=re.IGNORECASE).strip()
            clean_body = clean_body.lstrip("•-* :").strip()
            clean_body = clean_body.replace("**", "").strip()

            if "ưu tiên cao" in l.lower() or "cấp bách" in l.lower() or "thực hiện ngay" in l.lower():
                if any(c in clean_body for c in ["🟡", "🟢"]) or len(clean_body) < 15:
                    clean_body = "Rà soát chính sách đãi ngộ và kiểm soát tức thời các điểm bất thường vận hành."
                l = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: {clean_body}"
            elif "ưu tiên trung bình" in l.lower() or "trung hạn" in l.lower() or "quý tiếp theo" in l.lower():
                if any(c in clean_body for c in ["🔴", "🟢"]) or len(clean_body) < 15:
                    clean_body = "Tối ưu hóa quy trình phân bổ nguồn lực và chuẩn hóa định mức ngân sách theo thực tế."
                l = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: {clean_body}"
            elif "ưu tiên thấp" in l.lower() or "dài hạn" in l.lower() or "chiến lược" in l.lower():
                if any(c in clean_body for c in ["🔴", "🟡"]) or len(clean_body) < 15:
                    clean_body = "Hoàn thiện chính sách tổng thể, đẩy mạnh chuyển đổi số và nâng cao năng lực cạnh tranh dài hạn."
                l = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: {clean_body}"

            # Sửa câu bị cụt lửng ở đuôi
            if l.startswith("•") and not l.endswith((".", "!", "?", ":")):
                l += "."
            cleaned_23.append(l)

        # Luôn đảm bảo đúng 3 gạch đầu dòng chuẩn mực hoặc fallback sang data-grounded engine
        if len(cleaned_23) >= 2:
            high_item = next((l for l in cleaned_23 if "🔴" in l), "• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát chính sách đãi ngộ và kiểm soát tức thời các điểm bất thường vận hành.")
            med_item = next((l for l in cleaned_23 if "🟡" in l), "• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Tối ưu hóa quy trình phân bổ nguồn lực và chuẩn hóa định mức ngân sách theo thực tế.")
            low_item = next((l for l in cleaned_23 if "🟢" in l), "• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách tổng thể, đẩy mạnh chuyển đổi số và nâng cao năng lực cạnh tranh dài hạn.")
            part_23 = f"{high_item}\n\n{med_item}\n\n{low_item}"
        elif df is not None and not df.empty:
            part_23 = generate_data_grounded_action_plan(df)

    if not part_23 and df is not None and not df.empty:
        part_23 = generate_data_grounded_action_plan(df)

    if not part_21 and not part_22 and not part_23:
        lines_fallback = [re.sub(r"^#+\s*", "", l).strip() for l in cleaned.split("\n") if l.strip() and not l.strip().startswith("#")]
        part_21 = "\n\n".join(lines_fallback)

    return {
        "anomaly": part_21,
        "hypothesis": part_22,
        "action_plan": part_23,
    }
