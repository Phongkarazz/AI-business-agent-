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

    # 2. Cột tên khớp từ khóa thời gian, không phải ID, và parse được thành ngày hoặc là số nguyên biểu diễn năm (1900 - 2100)
    duration_keywords = ["service", "tenure", "thâm niên", "tham_nien", "experience", "kinh nghiệm", "kinh_nghiem", "duration", "tuoi", "age", "spent", "count", "so_luong"]
    candidates = [
        c for c in df.columns
        if any(k in str(c).lower() for k in TIME_KEYWORDS)
        and not any(k in str(c).lower() for k in duration_keywords)
        and not is_id_like(c)
    ]
    for c in candidates:
        try:
            if pd.api.types.is_numeric_dtype(df[c]):
                vals = pd.to_numeric(df[c], errors="coerce").dropna()
                if not vals.empty and vals.min() >= 1900 and vals.max() <= 2100:
                    return c
                # Nhận diện cột Month dạng số (1..12) hoặc Quý dạng số (1..4)
                if any(k in str(c).lower() for k in ["month", "thang", "tháng"]) and not vals.empty and vals.min() >= 1 and vals.max() <= 12:
                    return c
                if any(k in str(c).lower() for k in ["quy", "quarter"]) and not vals.empty and vals.min() >= 1 and vals.max() <= 4:
                    return c
                # Cột số nhưng không phải năm/tháng/quý -> KHÔNG PHẢI cột thời gian lịch
                continue

            # Nhận diện chuỗi Quý: 2021-Q1, 2021-Q2... hoặc Q1, Q2, Q3, Q4
            c_str = df[c].astype(str).str.strip().str.upper()
            if any(k in str(c).lower() for k in ["quy", "quarter", "quý"]) and c_str.str.contains(r'Q[1-4]').mean() >= 0.8:
                return c

            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                return c
        except Exception:
            continue
    return None


def ensure_full_twelve_months(df: pd.DataFrame, user_query: str = "") -> pd.DataFrame:
    """Tự động đảm bảo đủ 12 tháng (từ tháng 1 đến tháng 12) khi người dùng truy vấn theo các tháng trong năm.
    Nếu dữ liệu thực tế bị thiếu một số tháng (ví dụ chỉ có tháng 3-12 do quý 1 chưa bán hoặc bị cắt xén),
    tự động bù đắp các tháng còn thiếu với giá trị 0 để biểu đồ và bảng hiển thị trọn vẹn 12 tháng."""
    if df is None or df.empty:
        return df

    # 1. Tìm cột Month (hoặc thang)
    month_col = None
    for c in df.columns:
        c_low = str(c).strip().lower()
        if any(k in c_low for k in ["month", "thang", "tháng"]):
            month_col = c
            break

    if not month_col:
        return df

    # Tìm cột Year nếu có duy nhất 1 năm (ví dụ câu lệnh SELECT YEAR(...) AS Year, MONTH(...) AS Month)
    year_col = None
    for c in df.columns:
        if c == month_col:
            continue
        c_low = str(c).strip().lower()
        if any(k in c_low for k in ["year", "nam"]) and not any(k in c_low for k in ["service", "tenure", "experience"]):
            vals_yr = pd.to_numeric(df[c], errors="coerce").dropna()
            if not vals_yr.empty and vals_yr.min() >= 1900 and vals_yr.max() <= 2100 and vals_yr.nunique() == 1:
                year_col = c
                break

    non_time_cols = [c for c in df.columns if c not in (month_col, year_col)]
    num_cols = df[non_time_cols].select_dtypes(include="number").columns.tolist()

    # Chỉ áp dụng khi là chuỗi thời gian đơn (không có cột phân loại thứ 2)
    if len(num_cols) != len(non_time_cols) or len(non_time_cols) == 0:
        return df

    q_low = (user_query or "").lower()
    is_monthly_query = any(k in q_low for k in ["tháng", "month", "qua các tháng", "từng tháng", "năm", "12 tháng", "xu hướng"]) or not user_query
    if not is_monthly_query:
        return df

    # Trường hợp A: Cột Month là số nguyên 1..12 (hoặc dạng chuỗi số '1'..'12')
    vals_num = pd.to_numeric(df[month_col], errors="coerce")
    if vals_num.notna().all() and (vals_num >= 1).all() and (vals_num <= 12).all() and len(df) < 12:
        orig_dtype = df[month_col].dtype
        df_temp = df.copy()
        df_temp[month_col] = vals_num.astype(int)
        all_months_df = pd.DataFrame({month_col: list(range(1, 13))})
        merged_df = pd.merge(all_months_df, df_temp, on=month_col, how="left")
        
        if year_col:
            fixed_year = int(pd.to_numeric(df[year_col], errors="coerce").dropna().iloc[0])
            merged_df[year_col] = merged_df[year_col].fillna(fixed_year).astype(int)

        for c in num_cols:
            merged_df[c] = merged_df[c].fillna(0)
            if pd.api.types.is_integer_dtype(df[c]):
                merged_df[c] = merged_df[c].astype(int)
                
        if str(orig_dtype) not in ("int64", "int32", "int16", "int8"):
            try:
                merged_df[month_col] = merged_df[month_col].astype(orig_dtype)
            except Exception:
                pass

        # Giữ nguyên thứ tự cột ban đầu
        return merged_df[df.columns]

    # Trường hợp B: Cột Month là chuỗi 'YYYY-MM' (cùng 1 năm và số tháng < 12)
    sample_vals = df[month_col].astype(str).tolist()
    ym_matches = [re.match(r"^(\d{4})[-/](0?[1-9]|1[0-2])$", s.strip()) for s in sample_vals]
    if all(m is not None for m in ym_matches) and len(df) < 12:
        years = {m.group(1) for m in ym_matches}
        if len(years) == 1:
            yr = list(years)[0]
            all_yms = [f"{yr}-{m:02d}" for m in range(1, 13)]
            all_months_df = pd.DataFrame({month_col: all_yms})
            merged_df = pd.merge(all_months_df, df, on=month_col, how="left")
            
            if year_col:
                merged_df[year_col] = merged_df[year_col].fillna(int(yr)).astype(int)

            for c in num_cols:
                merged_df[c] = merged_df[c].fillna(0)
                if pd.api.types.is_integer_dtype(df[c]):
                    merged_df[c] = merged_df[c].astype(int)
            return merged_df[df.columns]

    return df


def ensure_full_four_quarters(df: pd.DataFrame, user_query: str = "") -> pd.DataFrame:
    """Tự động đảm bảo đủ 4 quý (từ Q1 đến Q4) khi người dùng truy vấn theo các quý trong năm.
    Nếu dữ liệu thực tế bị thiếu một số quý do quý đó chưa có dữ liệu bán hàng,
    tự động bù đắp các quý còn thiếu với giá trị 0 để biểu đồ và bảng hiển thị trọn vẹn 4 quý."""
    if df is None or df.empty:
        return df

    # 1. Tìm cột Quarter (hoặc quy)
    qtr_col = None
    for c in df.columns:
        c_low = str(c).strip().lower()
        if any(k in c_low for k in ["quarter", "quarteryear", "quy", "quý", "qtr"]):
            qtr_col = c
            break

    if not qtr_col:
        return df

    # Tìm cột Year nếu có
    year_col = None
    for c in df.columns:
        if c == qtr_col:
            continue
        c_low = str(c).strip().lower()
        if any(k in c_low for k in ["year", "nam"]) and not any(k in c_low for k in ["service", "tenure", "experience"]):
            vals_yr = pd.to_numeric(df[c], errors="coerce").dropna()
            if not vals_yr.empty and vals_yr.min() >= 1900 and vals_yr.max() <= 2100 and vals_yr.nunique() == 1:
                year_col = c
                break

    non_time_cols = [c for c in df.columns if c not in (qtr_col, year_col)]
    num_cols = df[non_time_cols].select_dtypes(include="number").columns.tolist()

    # Chỉ áp dụng khi là chuỗi thời gian đơn (không có cột phân loại thứ 2)
    if len(num_cols) != len(non_time_cols) or len(non_time_cols) == 0:
        return df

    q_low = (user_query or "").lower()
    is_qtr_query = any(k in q_low for k in ["quý", "quarter", "từng quý", "theo quý", "qua các quý", "năm", "xu hướng"]) or not user_query
    if not is_qtr_query:
        return df

    # Trường hợp A: Cột Quarter là số nguyên 1..4
    vals_num = pd.to_numeric(df[qtr_col], errors="coerce")
    if vals_num.notna().all() and (vals_num >= 1).all() and (vals_num <= 4).all() and len(df) < 4:
        df_temp = df.copy()
        df_temp[qtr_col] = vals_num.astype(int)
        all_qtrs_df = pd.DataFrame({qtr_col: [1, 2, 3, 4]})
        merged_df = pd.merge(all_qtrs_df, df_temp, on=qtr_col, how="left")
        
        if year_col:
            fixed_year = int(pd.to_numeric(df[year_col], errors="coerce").dropna().iloc[0])
            merged_df[year_col] = merged_df[year_col].fillna(fixed_year).astype(int)

        for c in num_cols:
            merged_df[c] = merged_df[c].fillna(0)
            if pd.api.types.is_integer_dtype(df[c]):
                merged_df[c] = merged_df[c].astype(int)
        return merged_df[df.columns]

    # Trường hợp B: Cột Quarter là chuỗi 'YYYY-Q1'..'YYYY-Q4'
    sample_vals = df[qtr_col].astype(str).str.strip().tolist()
    yq_matches = [re.match(r"^(\d{4})[-_ ]?[Qq]([1-4])$", s) for s in sample_vals]
    if all(m is not None for m in yq_matches) and len(df) < 4:
        years = {m.group(1) for m in yq_matches}
        if len(years) == 1:
            yr = list(years)[0]
            all_yqs = [f"{yr}-Q{q}" for q in range(1, 5)]
            all_qtrs_df = pd.DataFrame({qtr_col: all_yqs})
            merged_df = pd.merge(all_qtrs_df, df, on=qtr_col, how="left")
            
            if year_col:
                merged_df[year_col] = merged_df[year_col].fillna(int(yr)).astype(int)

            for c in num_cols:
                merged_df[c] = merged_df[c].fillna(0)
                if pd.api.types.is_integer_dtype(df[c]):
                    merged_df[c] = merged_df[c].astype(int)
            return merged_df[df.columns]

    return df


def ensure_ratio_column_if_requested(df: pd.DataFrame, user_query: str = "") -> pd.DataFrame:
    """Đảm bảo kết quả DataFrame luôn có cột tỷ lệ / phần trăm khi người dùng yêu cầu bài toán tỷ lệ, tỷ trọng, cơ cấu.
    Nếu SQL chỉ trả về các số đo tuyệt đối (TotalSales, Headcount...), hàm này tự động bổ sung cột Tỷ lệ (%) chuẩn xác."""
    if df is None or df.empty or len(df) <= 1:
        return df

    q_low = (user_query or "").lower()
    ratio_keywords = [
        "tỉ lệ", "tỷ lệ", "phần trăm", "percentage", "percent", "tỷ trọng", "tỉ trọng", 
        "cơ cấu", "share", "ratio", "đóng góp"
    ]
    asks_ratio = any(k in q_low for k in ratio_keywords)
    if not asks_ratio:
        return df

    # Kiểm tra xem DataFrame đã có cột tỷ lệ/phần trăm chưa
    has_pct_col = any(
        any(k in str(c).lower() for k in ["pct", "percent", "percentage", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "share", "ratio", "%"])
        for c in df.columns
    )
    if has_pct_col:
        return df

    # Tìm các cột số hợp lệ (loại bỏ id-like, năm, tháng...)
    candidate_cols = []
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        c_low = str(c).lower()
        if any(k in c_low for k in ["id", "emp_no", "year", "nam", "month", "thang", "hireyear"]):
            continue
        candidate_cols.append(c)

    if not candidate_cols:
        return df

    # Ưu tiên cột đo lường chính (sales, amount, total, count, boxes, headcount...)
    primary_col = None
    for c in candidate_cols:
        c_low = str(c).lower()
        if any(k in c_low for k in ["sales", "amount", "total", "count", "boxes", "headcount", "employees", "doanh"]):
            primary_col = c
            break
    if not primary_col:
        primary_col = candidate_cols[0]

    try:
        col_sum = float(df[primary_col].sum())
        if col_sum > 0:
            df = df.copy()
            pct_col_name = "Tỷ lệ (%)"
            df[pct_col_name] = ((df[primary_col] / col_sum) * 100.0).round(2)
    except Exception:
        pass

    return df


def ensure_efficiency_columns_if_requested(df: pd.DataFrame, user_query: str = "") -> pd.DataFrame:
    """Tự động tính thêm các cột hiệu quả (AvgOrderValue, RevenuePerBox) nếu người dùng hỏi về hiệu quả bán hàng
    nhưng kết quả DataFrame chỉ mới có các cột tổng (TotalSales, TotalProductsSold, TotalBoxesSold)."""
    if df is None or df.empty:
        return df

    uq_low = (user_query or "").lower()
    is_efficiency = any(k in uq_low for k in [
        "hiệu quả", "efficiency", "effectiveness", "năng suất", 
        "giá trị đơn hàng trung bình", "đơn hàng trung bình", "trung bình mỗi đơn", 
        "trung bình mỗi hộp", "order value", "per box", "profit per box", "performance",
        "lợi nhuận", "profit", "margin", "tỷ suất", "tỉ suất", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"
    ])
    if not is_efficiency:
        return df

    cols_low = {str(c).lower(): c for c in df.columns}
    has_avg_col = any(
        (any(k in c for k in ["avg", "ordervalue", "profit", "margin", "trung bình", "revenueperbox"]) 
         or (any(k in c for k in ["perbox", "per_box"]) and not any(k in c for k in ["cost", "giá vốn", "gia_von"])))
        for c in cols_low.keys()
    )
    if has_avg_col:
        return df

    # Tìm cột sales/doanh thu
    sales_col = None
    for k in ["totalsales", "amount", "sales", "doanh_thu", "doanh_so"]:
        if k in cols_low:
            sales_col = cols_low[k]
            break

    # Tìm cột số lượng giao dịch / đơn hàng / sản phẩm
    count_col = None
    for k in ["totalproductssold", "totalorders", "orders", "count", "soluong"]:
        if k in cols_low:
            count_col = cols_low[k]
            break

    # Tìm cột số lượng thùng / hộp
    boxes_col = None
    for k in ["totalboxessold", "totalboxes", "boxes", "thung", "hop"]:
        if k in cols_low:
            boxes_col = cols_low[k]
            break

    # Tìm cột giá vốn / cost_per_box
    cost_col = None
    for k in ["cost_per_box", "costperbox", "cost"]:
        if k in cols_low:
            cost_col = cols_low[k]
            break

    df_mod = df.copy()
    added = False

    if sales_col and boxes_col and cost_col:
        try:
            s_val = pd.to_numeric(df_mod[sales_col], errors="coerce")
            b_val = pd.to_numeric(df_mod[boxes_col], errors="coerce")
            c_val = pd.to_numeric(df_mod[cost_col], errors="coerce")
            profit_val = s_val - b_val * c_val
            df_mod["ProfitMargin"] = ((profit_val * 100.0) / s_val.replace(0, pd.NA)).round(2).fillna(0.0)
            df_mod["ProfitPerBox"] = (profit_val / b_val.replace(0, pd.NA)).round(2).fillna(0.0)
            added = True
            if any(k in uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%"]):
                df_mod = df_mod.sort_values(by="ProfitMargin", ascending=False).reset_index(drop=True)
            elif any(k in uq_low for k in ["lợi nhuận", "profit"]):
                df_mod = df_mod.sort_values(by="ProfitPerBox", ascending=False).reset_index(drop=True)
        except Exception:
            pass

    if not added:
        if sales_col and count_col:
            try:
                s_val = pd.to_numeric(df_mod[sales_col], errors="coerce")
                c_val = pd.to_numeric(df_mod[count_col], errors="coerce")
                df_mod["AvgOrderValue"] = (s_val / c_val.replace(0, pd.NA)).round(2).fillna(0.0)
                added = True
            except Exception:
                pass

        if sales_col and boxes_col:
            try:
                s_val = pd.to_numeric(df_mod[sales_col], errors="coerce")
                b_val = pd.to_numeric(df_mod[boxes_col], errors="coerce")
                df_mod["RevenuePerBox"] = (s_val / b_val.replace(0, pd.NA)).round(2).fillna(0.0)
                added = True
            except Exception:
                pass

    if added:
        dim_cols = [c for c in df.columns if c not in (sales_col, count_col, boxes_col, cost_col)]
        first_dim = dim_cols[0] if dim_cols else df.columns[0]
        eff_new = [c for c in ["ProfitMargin", "ProfitPerBox", "AvgOrderValue", "RevenuePerBox"] if c in df_mod.columns]
        other_cols = [c for c in df_mod.columns if c not in eff_new and c != first_dim]
        df_mod = df_mod[[first_dim] + eff_new + other_cols]

    return df_mod


def unify_year_month_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Nếu dataframe chứa riêng biệt 2 cột Year (1900-2100) và Month (1-12),
    tự động hợp nhất thành cột Month chuẩn 'YYYY-MM' để biểu đồ trực quan hóa liền mạch theo thời gian."""
    if df is None or df.empty or len(df.columns) < 2:
        return df

    year_col = None
    month_col = None
    for c in df.columns:
        c_low = str(c).strip().lower()
        if any(k in c_low for k in ["year", "nam"]) and not any(k in c_low for k in ["of_service", "service", "experience", "thâm_niên", "kinh_nghiệm"]):
            vals = pd.to_numeric(df[c], errors="coerce").dropna()
            if not vals.empty and vals.min() >= 1900 and vals.max() <= 2100:
                year_col = c
        elif any(k in c_low for k in ["month", "thang", "tháng"]):
            vals = pd.to_numeric(df[c], errors="coerce").dropna()
            if not vals.empty and vals.min() >= 1 and vals.max() <= 12:
                month_col = c

    if year_col and month_col:
        df_copy = df.copy()
        y_series = pd.to_numeric(df_copy[year_col], errors="coerce").fillna(0).astype(int).astype(str)
        m_series = pd.to_numeric(df_copy[month_col], errors="coerce").fillna(0).astype(int).astype(str).str.zfill(2)
        df_copy["Month"] = y_series + "-" + m_series
        drop_cols = [c for c in [month_col, year_col] if c != "Month"]
        if drop_cols:
            df_copy = df_copy.drop(columns=drop_cols)
        return df_copy

    return df


def has_time_dimension(df: pd.DataFrame) -> bool:
    """Kiểm tra dataframe có chiều thời gian không."""
    return find_time_column(df) is not None


def get_axis_columns(df: pd.DataFrame):
    """Phân loại cột:
    - measure_cols: cột số đo lường (đã loại bỏ ID và các cột năm lịch sử/to_date)
    - cat_cols: cột danh mục/text
    - time_col: cột thời gian
    """
    time_col = find_time_column(df)
    all_num_cols = df.select_dtypes(include="number").columns.tolist()
    
    # Loại bỏ ID-like và các cột biểu diễn năm thuần túy (e.g. HireYear, Year, Nam, hoặc cột có toàn giá trị 9999)
    # cũng như cột Month dạng số (1-12)
    measure_cols = []
    for c in all_num_cols:
        if is_id_like(c):
            continue
        c_low = str(c).strip().lower()
        if any(k in c_low for k in ["year", "hireyear", "nam"]) and not any(k in c_low for k in ["of_service", "service", "experience", "thâm_niên", "kinh_nghiệm"]):
            vals = pd.to_numeric(df[c], errors="coerce").dropna()
            if not vals.empty and (vals.min() >= 1900 or (vals == 9999).all()):
                continue
        if any(k in c_low for k in ["month", "thang", "tháng"]):
            vals = pd.to_numeric(df[c], errors="coerce").dropna()
            if not vals.empty and vals.min() >= 1 and vals.max() <= 12:
                continue
        measure_cols.append(c)

    cat_cols = [c for c in df.columns if c not in measure_cols and c != time_col]

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
    # Ưu tiên các cột tên thực thể chi tiết (không chứa từ khóa group/nhóm/khối)
    for c in df.columns:
        c_low = str(c).lower()
        if c not in exclude and not any(k in c_low for k in ["group", "nhóm", "khối"]) and NAME_LIKE_REGEX.search(str(c)):
            return c
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
                if len(clean_tag.split()) > 25 or len(clean_tag) > 150:
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


def format_entity_label(val) -> str:
    """Định dạng nhãn thực thể hoặc năm không bị đuôi số thập phân .0."""
    s = str(val).strip()
    if re.match(r"^\d+\.0+$", s):
        return s.split(".")[0]
    return s


def generate_data_grounded_hypotheses(df: pd.DataFrame, user_query: str = "", is_en: bool = False) -> str:
    """Tự động sinh 2 Giả thuyết & Nguyên nhân Tiềm năng (Mục 2.2) suy luận sắc bén dựa trên đúng câu hỏi người dùng và số liệu thực tế."""
    if df is None or df.empty:
        if is_en:
            return (
                "• **Data Sufficiency & Baseline Operations**: Current results reflect baseline operating conditions without significant structural disruptions.\n\n"
                "• **Market Alignment & Governance**: Business performance remains aligned with planned operational capacity."
            )
        return (
            "• **Định biên Vận hành & Mặt bằng Cơ sở**: Kết quả phản ánh trạng thái vận hành ổn định, phù hợp với định biên hoạt động thực tế của tổ chức.\n\n"
            "• **Tuân thủ Mục tiêu & Kế hoạch Phân bổ**: Các chỉ số kinh doanh hiện tại bám sát kế hoạch điều hành và chưa ghi nhận áp lực đột biến từ ngoại cảnh."
        )

    cols = df.columns.tolist()
    measure_cols, cat_cols, time_col = get_axis_columns(df)
    val_col = measure_cols[0] if measure_cols else None

    # Nếu không tìm thấy measure_cols bằng get_axis_columns, lấy cột số cuối cùng
    if not val_col:
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            val_col = num_cols[-1]

    if not val_col:
        if is_en:
            return (
                "• **Operational Allocation**: Performance figures reflect approved resource plans and current organizational capacity.\n\n"
                "• **Target Alignment**: Departmental outcomes align closely with mid-term strategic governance priorities."
            )
        return (
            "• **Định biên Vận hành & Phân bổ Nguồn lực**: Số liệu phản ánh sự phân bố hiện tại phù hợp với kế hoạch nhân sự và ngân sách đã được phê duyệt.\n\n"
            "• **Cân đối Nhu cầu & Định hướng Phát triển**: Kết quả cho thấy sự tập trung vào các mục tiêu then chốt trong giai đoạn vận hành."
        )

    q_low = (user_query or "").lower()
    cols_str = " ".join(str(c).lower() for c in cols)

    # 1. NHẬN DIỆN CHUỖI THỜI GIAN (Time Series / Yearly Trend / Trend by Year)
    is_time_series = (
        time_col is not None
        or any(k in q_low for k in ["qua các năm", "theo năm", "từng năm", "over time", "per year", "over the years", "yearly", "xu hướng", "trend", "biến động", "thay đổi như thế nào", "qua thời gian"])
        or any(k in cols_str for k in ["year", "hireyear", "năm", "tháng", "month", "date"])
    )

    t_col = time_col or next((c for c in cols if any(k in str(c).lower() for k in ["year", "hireyear", "năm", "tháng", "month", "date"])), None)

    if is_time_series and t_col and t_col != val_col:
        try:
            df_sorted = df.copy()
            df_sorted[val_col] = pd.to_numeric(df_sorted[val_col], errors="coerce").fillna(0)
            try:
                df_sorted = df_sorted.sort_values(by=t_col)
            except Exception:
                pass

            peak_row = df_sorted.loc[df_sorted[val_col].idxmax()]
            min_row = df_sorted.loc[df_sorted[val_col].idxmin()]
            peak_t = format_entity_label(peak_row[t_col])
            peak_v = float(peak_row[val_col])
            min_t = format_entity_label(min_row[t_col])
            min_v = float(min_row[val_col])

            # Tính bước nhảy vọt (spike) lớn nhất giữa các kỳ liên tiếp
            spike_t = peak_t
            spike_v = peak_v
            spike_pct = ((peak_v - min_v) / min_v * 100) if min_v > 0 else 0

            if len(df_sorted) >= 2:
                pct_changes = df_sorted[val_col].pct_change() * 100
                valid_pcts = pct_changes.dropna()
                if not valid_pcts.empty:
                    max_jump_idx = valid_pcts.idxmax()
                    if valid_pcts.loc[max_jump_idx] > 15:
                        spike_t = format_entity_label(df_sorted.loc[max_jump_idx, t_col])
                        spike_pct = float(valid_pcts.loc[max_jump_idx])
                        spike_v = float(df_sorted.loc[max_jump_idx, val_col])

            mean_val = float(df_sorted[val_col].mean())

            is_payroll = any(k in q_low or k in cols_str for k in ["salary", "lương", "quỹ", "expenditure", "budget", "chi phí"])
            is_hiring = any(k in q_low or k in cols_str for k in ["tuyển", "hire", "headcount", "nhân viên"])

            if is_en:
                if is_payroll:
                    h1 = f"• **Workforce Ramp-up & Budget Expansion in {spike_t}**: The significant jump of +{spike_pct:.1f}% (reaching {spike_v:,.2f}) highlights aggressive hiring and corporate scaling during this period, establishing a larger baseline payroll expenditure."
                    h2 = f"• **Tenure Compounding & Budget Stabilization**: Total payroll peaked in {peak_t} ({peak_v:,.2f}) and sustained around the mean of {mean_val:,.2f}, driven by recurring merit increments for tenured talent paired with organizational salary caps."
                elif is_hiring:
                    h1 = f"• **Peak Recruitment Wave ({spike_t})**: New hiring surged to {peak_v:,.0f} employees in {peak_t}, aligning with corporate capacity expansion and critical project rollouts."
                    h2 = f"• **Headcount Stabilization & Selective Hiring**: Post-peak recruitment normalized to {min_v:,.0f} hires in {min_t} around a historical baseline of {mean_val:,.0f} hires/year, reflecting a strategic shift from rapid scaling to talent retention and internal productivity."
                else:
                    h1 = f"• **Growth Acceleration Phase ({spike_t})**: The performance surge of +{spike_pct:.1f}% to {spike_v:,.2f} reflects synergistic execution of core strategic initiatives during this operational period."
                    h2 = f"• **Market Normalization & Operational Ceiling**: Trajectory from baseline {min_v:,.2f} ({min_t}) to peak {peak_v:,.2f} ({peak_t}) outlines typical industry demand cycles, settling around the mean of {mean_val:,.2f}."
            else:
                if is_payroll:
                    h1 = f"• **Mở rộng Quy mô & Bước nhảy Ngân sách Giai đoạn {spike_t}**: Mức tăng vọt +{spike_pct:.1f}% (đạt {spike_v:,.2f}) phản ánh giai đoạn doanh nghiệp ồ ạt mở rộng quy mô nhân sự hoặc sáp nhập các đơn vị lớn, tạo ra bước nhảy vọt về định biên chi phí lương."
                    h2 = f"• **Tích lũy Thâm niên & Cơ chế Trần Quỹ Lương**: Tổng quỹ lương đạt đỉnh vào năm {peak_t} ({peak_v:,.2f}) và sau đó duy trì ổn định quanh mức trung bình {mean_val:,.2f}, xuất phát từ chính sách tăng lương định kỳ tích lũy cho lực lượng nhân sự thâm niên kết hợp với việc kiểm soát trần ngân sách tổ chức."
                elif is_hiring:
                    h1 = f"• **Làn sóng Tuyển dụng & Đột phá Quy mô ({spike_t})**: Số lượng nhân sự mới đạt đỉnh {peak_v:,.0f} người vào năm {peak_t}, gắn liền với giai đoạn mở rộng sản xuất kinh doanh và bổ sung nhân lực cho các dự án trọng điểm."
                    h2 = f"• **Tối ưu Định biên & Tinh gọn Bộ máy**: Sau giai đoạn cao điểm, quy mô tuyển dụng hạ nhiệt về {min_v:,.0f} nhân sự (năm {min_t}) và duy trì quanh mức bình quân {mean_val:,.0f} người/năm, phản ánh bước chuyển từ tuyển ồ ạt sang nâng cao chất lượng và ổn định đội ngũ."
                else:
                    h1 = f"• **Đột phá Tăng trưởng & Mở rộng Thị phần ({spike_t})**: Mức tăng trưởng +{spike_pct:.1f}% (đạt {spike_v:,.2f}) chứng minh hiệu quả cộng hưởng từ các sáng kiến trọng tâm và mở rộng quy mô hoạt động trong giai đoạn này."
                    h2 = f"• **Chu kỳ Biến động & Ổn định Dài hạn**: Sự dịch chuyển từ mức sàn {min_v:,.2f} ({min_t}) lên đỉnh {peak_v:,.2f} ({peak_t}) phản ánh chu kỳ thị trường đặc thù, định hình mức nền tảng ổn định quanh giá trị trung bình {mean_val:,.2f}."

            return f"{h1}\n\n{h2}"
        except Exception:
            pass

    # 2. SO SÁNH KHỐI / NHÓM PHÒNG BAN (Department Group: Tech vs Business)
    is_dept_group = (
        "departmentgroup" in cols_str
        or any(k in q_low for k in ["kỹ thuật", "kinh doanh", "technical", "business", "sales, marketing", "development, research"])
    )
    grp_col = next((c for c in cols if "departmentgroup" in str(c).lower() or "group" in str(c).lower()), None)
    if is_dept_group and grp_col and grp_col != val_col:
        try:
            grp_stats = df.groupby(grp_col)[val_col].mean().sort_values(ascending=False)
            if len(grp_stats) >= 2:
                top_grp = format_entity_label(grp_stats.index[0])
                top_grp_v = float(grp_stats.iloc[0])
                bot_grp = format_entity_label(grp_stats.index[1])
                bot_grp_v = float(grp_stats.iloc[1])
                diff_grp = top_grp_v - bot_grp_v
                pct_grp = (diff_grp / bot_grp_v * 100) if bot_grp_v > 0 else 0

                if is_en:
                    h1 = f"• **Revenue Target Pressure & Performance Incentives**: The **{top_grp}** cluster commands a higher compensation level ({top_grp_v:,.2f} vs {bot_grp_v:,.2f} for **{bot_grp}**, a +{pct_grp:.1f}% spread), driven by direct quota accountability, commercial risk, and performance commissions."
                    h2 = f"• **Talent Scarcity & Technical Compensation Models**: The gap of {diff_grp:,.2f} reflects distinct talent structures: commercial roles leverage commission-based market incentives, whereas engineering and research prioritize long-term salary stability and expert technical retention."
                else:
                    h1 = f"• **Áp lực Chỉ tiêu Doanh số & Cơ chế Thưởng Thương mại**: Khối **{top_grp}** đạt mức thu nhập trung bình cao hơn ({top_grp_v:,.2f} so với {bot_grp_v:,.2f} của khối **{bot_grp}**, chênh lệch +{pct_grp:.1f}%), bắt nguồn từ đặc thù gắn liền với chỉ tiêu tăng trưởng doanh thu trực tiếp và chính sách thưởng hoa hồng theo hiệu suất kinh doanh."
                    h2 = f"• **Chi phí Cơ hội & Độ Khan hiếm Kỹ năng Chuyên môn**: Khoảng cách {diff_grp:,.2f} phản ánh chiến lược cân đối nguồn lực: khối thương mại yêu cầu gói đãi ngộ linh hoạt theo thị trường, trong khi khối kỹ thuật/nghiên cứu ưu tiên tính ổn định lâu dài và bảo toàn năng lực công nghệ cốt lõi."
                return f"{h1}\n\n{h2}"
        except Exception:
            pass

    # 3. SO SÁNH PHÒNG BAN, CHỨC DANH, GIỚI TÍNH, SẢN PHẨM HOẶC XẾP HẠNG
    name_candidates = [c for c in cat_cols if c != val_col]
    if not name_candidates:
        name_candidates = [c for c in cols if c != val_col]
    name_col = name_candidates[0] if name_candidates else None

    if name_col and val_col:
        try:
            df_eval = df.copy()
            df_eval[val_col] = pd.to_numeric(df_eval[val_col], errors="coerce").fillna(0)
            sorted_eval = df_eval.sort_values(by=val_col, ascending=False)
            top_r = sorted_eval.iloc[0]
            bot_r = sorted_eval.iloc[-1]
            top_name = format_entity_label(top_r[name_col])
            top_v = float(top_r[val_col])
            bot_name = format_entity_label(bot_r[name_col])
            bot_v = float(bot_r[val_col])
            spread_diff = top_v - bot_v
            spread_pct = (spread_diff / bot_v * 100) if bot_v > 0 else 0

            # 3A. Giới tính (Gender)
            is_gender = any(k in cols_str for k in ["gender", "giới tính", "sex"]) or any(k in q_low for k in ["giới tính", "nam", "nữ", "gender", "male", "female"])
            if is_gender:
                if is_en:
                    h1 = f"• **Job Family & Seniority Distribution**: The variance between **{top_name}** ({top_v:,.2f}) and **{bot_name}** ({bot_v:,.2f}, spread {spread_pct:.1f}%) often stems from historical tenure accumulation and the distribution of senior managerial posts."
                    h2 = f"• **Candidate Pipeline & Pay Equity Governance**: This distribution reflects external industry talent pools across specialized divisions and active enterprise governance around compensation parity."
                else:
                    h1 = f"• **Cơ cấu Phân bổ Chức danh & Thâm niên Quản lý**: Chênh lệch giữa nhóm **{top_name}** ({top_v:,.2f}) và nhóm **{bot_name}** ({bot_v:,.2f}, chênh lệch {spread_pct:.1f}%) thường bắt nguồn từ tỷ lệ nắm giữ các vị trí lãnh đạo cấp cao hoặc số năm thâm niên tích lũy tại tổ chức."
                    h2 = f"• **Đặc thù Nguồn cung Ứng viên & Chính sách Bình đẳng**: Tỷ lệ cơ cấu phản ánh nguồn cung ứng viên lịch sử trong từng chuyên ngành và cam kết của doanh nghiệp trong việc thúc đẩy công bằng cơ hội phát triển nghề nghiệp."
                return f"{h1}\n\n{h2}"

            # 3B. Chức danh (Titles / Roles)
            is_title = any(k in cols_str for k in ["title", "chức danh", "position"]) or any(k in q_low for k in ["chức danh", "vị trí", "title"])
            if is_title:
                if is_en:
                    h1 = f"• **Accountability Scope & Decision-Making Complexity**: **{top_name}** ranks highest ({top_v:,.2f}), corresponding to strategic decision risk and specialized leadership execution."
                    h2 = f"• **Merit Progression & Key Talent Retention**: The gap of {spread_diff:,.2f} ({spread_pct:.1f}%) against **{bot_name}** ({bot_v:,.2f}) serves as a key financial incentive for career ladders and leadership retention."
                else:
                    h1 = f"• **Phân cấp Trách nhiệm & Biên độ Quyết định Quản lý**: Vị trí **{top_name}** dẫn đầu ({top_v:,.2f}) thể hiện mức độ rủi ro trách nhiệm cao nhất và yêu cầu kinh nghiệm điều hành phức tạp."
                    h2 = f"• **Đòn bẩy Tài chính & Giữ chân Nhân sự Cốt lõi**: Biên độ chênh lệch {spread_pct:.1f}% ({spread_diff:,.2f}) so với vị trí **{bot_name}** ({bot_v:,.2f}) là đòn bẩy tài chính quan trọng để tạo động lực thăng tiến nội bộ và giữ chân nhân tài đầu ngành."
                return f"{h1}\n\n{h2}"

            # 3C. Phòng ban (Departments)
            is_dept = any(k in cols_str for k in ["dept", "department", "phòng"]) or any(k in q_low for k in ["phòng ban", "bộ phận", "department"])
            if is_dept:
                if is_en:
                    h1 = f"• **Strategic Contribution & Market Talent Competition**: **{top_name}** commands the top average ({top_v:,.2f}), reflecting its direct impact on core value creation and strong competition in the external hiring market."
                    h2 = f"• **Seniority Ratio & Departmental Budget Framework**: The {spread_pct:.1f}% spread ({spread_diff:,.2f}) compared to **{bot_name}** ({bot_v:,.2f}) aligns with differing ratios of senior specialists and departmental operating caps."
                else:
                    h1 = f"• **Đóng góp Giá trị Cốt lõi & Tính Cạnh tranh Ngành nghề**: Phòng ban **{top_name}** đạt mức cao nhất ({top_v:,.2f}), thể hiện vị thế đơn vị trọng yếu và tính chất cạnh tranh cao trong việc thu hút nhân lực giỏi trên thị trường lao động."
                    h2 = f"• **Cơ cấu Định biên Cấp bậc & Ngân sách Vận hành**: Chênh lệch {spread_pct:.1f}% ({spread_diff:,.2f}) so với **{bot_name}** ({bot_v:,.2f}) phản ánh sự khác biệt về tỷ lệ nhân sự cao cấp (senior) và giới hạn trần ngân sách được phê duyệt giữa các đơn vị."
                return f"{h1}\n\n{h2}"

            # 3D. Tỷ lệ đóng góp / Cơ cấu tỷ trọng (Contribution / Ratio / Share)
            is_contribution = any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "tỉ trọng", "tỷ trọng", "phần trăm", "cơ cấu", "đóng góp", "share", "ratio"])
            if is_contribution:
                if is_en:
                    h1 = f"• **Core Revenue Anchor & Portfolio Dominance**: **{top_name}** accounts for the primary revenue stream, serving as the strategic growth pillar across business operations."
                    h2 = f"• **Channel Diversification & Secondary Growth Levers**: The contribution variance highlights an opportunity to cross-sell and elevate **{bot_name}** to reduce single-segment dependency."
                else:
                    h1 = f"• **Trọng tâm Đóng góp Doanh thu & Vị thế Trụ cột**: Nhóm **{top_name}** nắm giữ tỷ trọng đóng góp chủ lực, đóng vai trò đầu tàu dẫn dắt dòng tiền và tăng trưởng quy mô toàn hệ thống."
                    h2 = f"• **Đa dạng hóa Danh mục & Khai phóng Tiềm năng Tăng trưởng**: Khoảng cách tỷ trọng so với nhóm **{bot_name}** cho thấy dư địa lớn để mở rộng chiến dịch xúc tiến bán chéo, giảm thiểu rủi ro phụ thuộc vào một phân khúc đơn lẻ."
                return f"{h1}\n\n{h2}"

            # 3E. Sản phẩm / Thương mại (Chocolates DB)
            is_sales = any(k in cols_str for k in ["product", "sản phẩm", "amount", "revenue", "boxes", "quốc gia", "country", "rep"]) or any(k in q_low for k in ["sản phẩm", "chocolate", "doanh thu", "bán chạy", "sales"])
            if is_sales:
                if is_en:
                    h1 = f"• **Consumer Preference & Brand Resonance**: **{top_name}** outperforms ({top_v:,.2f}), proving superior product resonance and targeted campaign effectiveness."
                    h2 = f"• **Distribution Coverage & Market Penetration**: The {spread_pct:.1f}% gap against **{bot_name}** ({bot_v:,.2f}) indicates untapped potential in secondary channels, offering opportunities for supply chain optimization."
                else:
                    h1 = f"• **Thị hiếu Tiêu dùng & Độ Nhận diện Thương hiệu**: Nhóm **{top_name}** đạt kết quả vượt trội ({top_v:,.2f}), khẳng định ưu thế về sức hấp dẫn sản phẩm và hiệu quả của các chương trình xúc tiến bán hàng."
                    h2 = f"• **Khả năng Khai thác Kênh Phân phối & Độ Phủ Thị trường**: Khoảng cách {spread_pct:.1f}% so với nhóm **{bot_name}** ({bot_v:,.2f}) cho thấy tiềm năng tăng trưởng còn lớn tại các phân khúc ngách, mở ra cơ hội tối ưu hóa chuỗi cung ứng và mở rộng thị trường."
                return f"{h1}\n\n{h2}"

            # 3E. General Ranking
            if is_en:
                h1 = f"• **Operational Leadership & Execution Focus**: **{top_name}** achieves the highest benchmark ({top_v:,.2f}), demonstrating superior operational capacity and resource dedication."
                h2 = f"• **Performance Variance & Optimization Window**: The gap of {spread_diff:,.2f} ({spread_pct:.1f}%) versus **{bot_name}** ({bot_v:,.2f}) highlights an operational optimization window to narrow performance dispersion across units."
            else:
                h1 = f"• **Vị thế Dẫn đầu & Hiệu quả Thực thi**: Nhóm **{top_name}** đạt mức cao nhất ({top_v:,.2f}), phản ánh năng lực vận hành vượt trội và sự tập trung nguồn lực mạnh mẽ."
                h2 = f"• **Biên độ Phân hóa & Tiềm năng Tối ưu**: Khoảng cách {spread_diff:,.2f} ({spread_pct:.1f}%) so với nhóm **{bot_name}** ({bot_v:,.2f}) mở ra cơ hội chuẩn hóa quy trình và thu hẹp khoảng cách hiệu quả giữa các đơn vị."
            return f"{h1}\n\n{h2}"
        except Exception:
            pass

    if is_en:
        return (
            "• **Operational Allocation**: Performance figures reflect approved resource plans and current organizational capacity.\n\n"
            "• **Target Alignment**: Departmental outcomes align closely with mid-term strategic governance priorities."
        )
    return (
        "• **Định biên Vận hành & Phân bổ Nguồn lực**: Số liệu phản ánh sự phân bố hiện tại phù hợp với kế hoạch nhân sự và ngân sách đã được phê duyệt.\n\n"
        "• **Cân đối Nhu cầu & Định hướng Phát triển**: Kết quả cho thấy sự tập trung vào các mục tiêu then chốt trong giai đoạn vận hành."
    )


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
    top_name = format_entity_label(top_row[name_col])
    top_val = top_row[val_col]
    bot_name = format_entity_label(bot_row[name_col])
    bot_val = bot_row[val_col]

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


def split_insight_sections(markdown_text: str, df: pd.DataFrame = None, user_query: str = "", is_en: bool = False) -> dict[str, str]:
    """Bóc tách nội dung insight thành 3 phần riêng biệt để hiển thị dạng 3 Card UI chuyên nghiệp."""
    if not markdown_text:
        # Nếu không có text (chạy Ollama cục bộ hoặc fallback), tự động sinh đầy đủ 3 phần từ dữ liệu thực tế bám sát câu hỏi
        part_21 = ""
        part_22 = ""
        if df is not None and not df.empty:
            measure_cols, cat_cols, time_col = get_axis_columns(df)
            val_col = measure_cols[0] if measure_cols else None
            if not val_col:
                num_cols = df.select_dtypes(include="number").columns.tolist()
                if num_cols:
                    val_col = num_cols[-1]

            q_low = (user_query or "").lower()
            cols_str = " ".join(str(c).lower() for c in df.columns)
            is_time_series = (
                time_col is not None
                or any(k in q_low for k in ["qua các năm", "theo năm", "từng năm", "over time", "per year", "over the years", "yearly", "xu hướng", "trend", "biến động", "thay đổi như thế nào", "qua thời gian"])
                or any(k in cols_str for k in ["year", "hireyear", "năm", "tháng", "month", "date"])
            )
            t_col = time_col or next((c for c in df.columns if any(k in str(c).lower() for k in ["year", "hireyear", "năm", "tháng", "month", "date"])), None)

            if is_time_series and t_col and val_col and t_col != val_col:
                try:
                    df_eval = df.copy()
                    df_eval[val_col] = pd.to_numeric(df_eval[val_col], errors="coerce").fillna(0)
                    peak_row = df_eval.loc[df_eval[val_col].idxmax()]
                    min_row = df_eval.loc[df_eval[val_col].idxmin()]
                    peak_t = format_entity_label(peak_row[t_col])
                    peak_v = float(peak_row[val_col])
                    min_t = format_entity_label(min_row[t_col])
                    min_v = float(min_row[val_col])
                    mean_val = float(df_eval[val_col].mean())
                    if is_en:
                        part_21 = (
                            f"• **Historical Peak**: Period **{peak_t}** reached the all-time peak ({peak_v:,.2f}), reflecting maximum capacity scale.\n\n"
                            f"• **Baseline Trough**: Period **{min_t}** marked the lowest point ({min_v:,.2f}), showing an overall gap of {abs(peak_v - min_v):,.2f} from the peak.\n\n"
                            f"• **Period Benchmark Average**: Multi-year baseline average stands at {mean_val:,.2f}, outlining long-term operational equilibrium."
                        )
                    else:
                        part_21 = (
                            f"• **Thời điểm Đạt đỉnh**: Giai đoạn **{peak_t}** ghi nhận mức cao nhất toàn chu kỳ ({peak_v:,.2f}), thể hiện quy mô vận hành lớn nhất.\n\n"
                            f"• **Thời điểm Mức sàn**: Giai đoạn **{min_t}** ở mức thấp nhất ({min_v:,.2f}), chênh lệch {abs(peak_v - min_v):,.2f} so với đỉnh.\n\n"
                            f"• **Mặt bằng Bình quân Chu kỳ**: Mức trung bình qua các kỳ là {mean_val:,.2f}, tạo đường cơ sở ổn định dài hạn."
                        )
                except Exception:
                    pass
            elif val_col:
                name_candidates = [c for c in cat_cols if c != val_col] or [c for c in df.columns if c != val_col]
                name_col = name_candidates[0] if name_candidates else None
                if name_col:
                    try:
                        df_eval = df.copy()
                        df_eval[val_col] = pd.to_numeric(df_eval[val_col], errors="coerce").fillna(0)
                        sorted_df = df_eval.sort_values(by=val_col, ascending=False)
                        top_row = sorted_df.iloc[0]
                        bot_row = sorted_df.iloc[-1]
                        top_name = format_entity_label(top_row[name_col])
                        top_val = float(top_row[val_col])
                        bot_name = format_entity_label(bot_row[name_col])
                        bot_val = float(bot_row[val_col])
                        spread_diff = top_val - bot_val
                        spread_pct = (spread_diff / bot_val) * 100 if bot_val != 0 else 0
                        median_val = float(df_eval[val_col].median())
                        if is_en:
                            part_21 = (
                                f"• **Leading Position**: Group **{top_name}** achieved the top level ({top_val:,.2f}), demonstrating primary contribution.\n\n"
                                f"• **Distribution Spread**: Group **{bot_name}** stands at {bot_val:,.2f} (a {spread_pct:.1f}% spread or {spread_diff:,.2f} variance).\n\n"
                                f"• **Reference Median**: Overall median benchmark is {median_val:,.2f}, representing organizational baseline."
                            )
                        else:
                            part_21 = (
                                f"• **Dẫn đầu toàn diện**: Nhóm **{top_name}** đạt mức cao nhất ({top_val:,.2f}), thể hiện vai trò nòng cốt.\n\n"
                                f"• **Khoảng cách phân bổ**: Nhóm **{bot_name}** ở mức {bot_val:,.2f} (chênh lệch {spread_pct:.1f}% tương đương {spread_diff:,.2f} so với nhóm dẫn đầu).\n\n"
                                f"• **Mức trung vị tham chiếu**: Thu nhập/quy mô trung vị toàn bảng là {median_val:,.2f}, phản ánh mặt bằng chung ổn định."
                            )
                    except Exception:
                        pass
            part_22 = generate_data_grounded_hypotheses(df, user_query=user_query, is_en=is_en)
        part_23 = generate_data_grounded_action_plan(df, is_en=is_en)
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
            if ":" in l:
                prefix, rest = l.split(":", 1)
                tag = prefix.lstrip("•-* ").strip().replace("**", "")
                body = rest.strip()
                if tag and body and len(tag) <= 150 and len(tag.split()) <= 25:
                    l = f"• **{tag}**: {body}"
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
            if clean_check.endswith(":") or len(clean_check) < 25 or (len(clean_check) < 35 and ":" not in clean_check):
                continue
            if not l.startswith("•"):
                l = "• " + l
            if ":" in l:
                prefix, rest = l.split(":", 1)
                tag = prefix.lstrip("•-* ").strip().replace("**", "")
                body = rest.strip()
                if tag and body and len(tag) <= 150 and len(tag.split()) <= 25:
                    l = f"• **{tag}**: {body}"
            cleaned_22.append(l)
        part_22 = "\n\n".join(cleaned_22)

    # Nếu part_22 rỗng do bị lọc hết rác/tiếng Anh -> tạo 2 giả thuyết executive bám sát dữ liệu thực tế và yêu cầu câu hỏi
    if not part_22 or len([l for l in part_22.split("\n") if l.strip()]) < 2:
        part_22 = generate_data_grounded_hypotheses(df, user_query=user_query, is_en=is_en)

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
            # Bóc sạch mọi nhãn trong ngoặc vuông (kể cả lặp lại nhiều lần hoặc lồng nhau như [Cấp Bách...]: [Cấp Bách...]:)
            while re.match(r"^(?:\*\*)?\[[^\]]+\](?:\*\*)?:?\s*", clean_body):
                clean_body = re.sub(r"^(?:\*\*)?\[[^\]]+\](?:\*\*)?:?\s*", "", clean_body).strip()
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
