"""
Column classification, language detection, starter prompts generator, and heuristic utilities for business datasets.
"""
from __future__ import annotations

import re
try:
    import pandas as pd
except ImportError:
    pd = None
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

            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
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
        if any(k in c_low for k in ["year", "nam", "năm"]) and not any(k in c_low for k in ["service", "tenure", "experience"]):
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
        if any(k in c_low for k in ["year", "hireyear", "nam", "năm"]) and not any(k in c_low for k in ["of_service", "service", "experience", "thâm_niên", "kinh_nghiệm", "thâm niên"]):
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


def select_primary_insight_columns(df: pd.DataFrame, user_query: str = "") -> tuple:
    """Chọn cột giá trị đo lường chính (val_col) và cột tên/nhãn (name_col) chính xác nhất cho bài toán phân tích insight,
    đặc biệt loại trừ các cột tích lũy dồn (CumulativePercent, RunningTotal) khỏi việc làm val_col."""
    if df is None or df.empty:
        return None, None
    cols = df.columns.tolist()
    measure_cols, cat_cols, time_col = get_axis_columns(df)

    # Loại bỏ các cột cộng dồn / tích lũy Pareto khỏi danh sách cột số đo lường chính
    non_cum_measures = [
        c for c in measure_cols
        if not any(k in str(c).lower() for k in ["cumulative", "tích lũy", "tich_luy", "runningtotal", "running_total", "cumpct"])
    ]

    q_low = (user_query or "").lower()

    # 1. Tìm val_col phù hợp
    val_col = None
    if non_cum_measures:
        # Nếu người dùng hỏi tiền tệ / sản lượng / quy mô cụ thể:
        if any(k in q_low for k in ["doanh số", "doanh thu", "sales", "revenue", "tiền"]):
            sales_c = [c for c in non_cum_measures if any(k in str(c).lower() for k in ["sales", "revenue", "amount", "doanh thu", "doanh so"])]
            if sales_c:
                val_col = sales_c[0]
        elif any(k in q_low for k in ["hộp", "thùng", "boxes", "sản lượng"]):
            box_c = [c for c in non_cum_measures if any(k in str(c).lower() for k in ["boxes", "hộp", "thùng", "sản lượng"])]
            if box_c:
                val_col = box_c[0]
        elif any(k in q_low for k in ["lương", "salary", "thu nhập"]):
            sal_c = [c for c in non_cum_measures if any(k in str(c).lower() for k in ["salary", "lương", "thu nhập"])]
            if sal_c:
                val_col = sal_c[0]
        elif any(k in q_low for k in ["tỷ suất", "tỉ suất", "margin"]):
            margin_c = [c for c in non_cum_measures if any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất"])]
            if margin_c:
                val_col = margin_c[0]
        elif any(k in q_low for k in ["nghỉ việc", "thôi việc", "turnover", "attrition", "rời đi", "rời khỏi"]):
            turnover_c = [c for c in non_cum_measures if any(k in str(c).lower() for k in ["turnover", "resigned", "left", "nghi_viec", "nghỉ", "rate"])]
            if turnover_c:
                val_col = turnover_c[0]

        elif any(k in q_low for k in ["thâm niên", "tenure", "service", "gắn bó", "kinh nghiệm", "lâu nhất", "năm công tác"]):
            tenure_c = [c for c in non_cum_measures if any(k in str(c).lower() for k in ["yearsofservice", "service", "tenure", "thâm_niên", "thâm niên", "years", "năm"])]
            if tenure_c:
                val_col = tenure_c[0]

        if not val_col:
            spread_candidate = next((c for c in non_cum_measures if any(k in str(c).lower() for k in ["salaryspread", "salary_spread", "chênh lệch lương", "khoảng cách lương"])), None)
            if spread_candidate:
                val_col = spread_candidate
            else:
                # Ưu tiên cột tiền tệ / số lượng trước cột phần trăm
                money_or_vol = [
                    c for c in non_cum_measures
                    if any(k in str(c).lower() for k in ["sales", "revenue", "amount", "boxes", "salary", "lương", "cost", "profit", "headcount", "nhân viên", "nhân sự", "count", "yearsofservice", "tenure"])
                    and not any(k in str(c).lower() for k in ["pct", "percent", "%", "margin", "rate", "tỷ lệ", "tỉ lệ"])
                ]
                if money_or_vol:
                    val_col = money_or_vol[0]
                else:
                    val_col = non_cum_measures[0]
    elif measure_cols:
        val_col = measure_cols[0]
    else:
        num_cols = df.select_dtypes(include="number").columns.tolist()
        num_non_cum = [c for c in num_cols if not any(k in str(c).lower() for k in ["cumulative", "tích lũy", "tich_luy", "runningtotal", "running_total"])]
        val_col = num_non_cum[0] if num_non_cum else (num_cols[0] if num_cols else None)

    # 2. Tìm name_col (Ưu tiên tuyệt đối cột tên thực thể như FullName, Salesperson, Department, Product, Customer trước các cột ID)
    best_name = get_best_name_column(df, exclude_cols=[val_col] if val_col else None)
    if best_name:
        name_col = best_name
    else:
        name_candidates = [c for c in cat_cols if c != val_col and not is_id_like(c)]
        if not name_candidates:
            name_candidates = [c for c in cols if c != val_col and not is_id_like(c)]
        name_col = name_candidates[0] if name_candidates else (cols[0] if cols else None)

    return val_col, name_col


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


_DYNAMIC_STARTER_CACHE = {}


def humanize_name_vi(name: str) -> str:
    """Chuyển đổi tên bảng hoặc tên cột kỹ thuật (e.g. order_date, total_amount) sang cụm từ tiếng Việt tự nhiên."""
    if not name:
        return ""
    s = str(name).strip()
    if any(c in s for c in "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựíìỉĩịđýỳỷỹỵÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÍÌỈĨỊĐÝỲỶỸỴ"):
        return s

    norm = re.sub(r"[^a-zA-Z0-9]", "", s).lower()
    vi_terms = {
        "sales": "Doanh số",
        "totalsales": "Tổng doanh số",
        "revenue": "Doanh thu",
        "amount": "Số tiền",
        "totalamount": "Tổng tiền",
        "price": "Đơn giá",
        "unitprice": "Đơn giá",
        "cost": "Chi phí",
        "totalcost": "Tổng chi phí",
        "profit": "Lợi nhuận",
        "netprofit": "Lợi nhuận ròng",
        "salary": "Mức lương",
        "currentsalary": "Lương hiện tại",
        "totalsalary": "Tổng quỹ lương",
        "payroll": "Quỹ lương",
        "boxes": "Số lượng hộp",
        "totalboxes": "Tổng số hộp",
        "quantity": "Số lượng",
        "qty": "Số lượng",
        "orders": "Đơn hàng",
        "ordercount": "Số lượng đơn",
        "products": "Sản phẩm",
        "productname": "Sản phẩm",
        "category": "Nhóm hàng",
        "categoryname": "Danh mục",
        "team": "Team kinh doanh",
        "teamname": "Đội ngũ",
        "geo": "Thị trường",
        "country": "Quốc gia",
        "city": "Thành phố",
        "region": "Khu vực",
        "location": "Địa điểm",
        "department": "Phòng ban",
        "deptname": "Phòng ban",
        "title": "Chức danh",
        "jobtitle": "Vị trí công việc",
        "employees": "Nhân sự",
        "employeeschangeddepartment": "Số nhân sự đổi phòng ban",
        "transferredincount": "Số nhân viên chuyển đến",
        "transferredoutcount": "Số nhân viên chuyển đi",
        "transferredcount": "Số lượng nhân sự chuyển phòng",
        "fullname": "Họ và tên",
        "salesperson": "Chuyên viên bán hàng",
        "customers": "Khách hàng",
        "customername": "Khách hàng",
        "students": "Học viên",
        "courses": "Khóa học",
        "grades": "Điểm số",
        "patients": "Bệnh nhân",
        "doctors": "Bác sĩ",
        "doctorname": "Bác sĩ",
        "appointments": "Lịch hẹn khám",
        "appointmentdate": "Ngày khám",
        "flights": "Chuyến bay",
        "flightnumber": "Mã chuyến bay",
        "airports": "Sân bay",
        "airline": "Hãng bay",
        "airlinename": "Hãng bay",
        "airlines": "Hãng bay",
        "tickets": "Vé máy bay",
        "ticketprice": "Giá vé",
        "farepaid": "Tiền vé",
        "fare": "Giá vé",
        "seatclass": "Hạng ghế",
        "durationminutes": "Thời lượng bay (Phút)",
        "duration": "Thời lượng",
        "departuretime": "Thời gian khởi hành",
        "arrivaltime": "Thời gian hạ cánh",
        "accounts": "Tài khoản",
        "transactions": "Giao dịch",
        "invoices": "Hóa đơn",
        "status": "Trạng thái",
        "type": "Loại hình",
        "branch": "Chi nhánh",
        "rating": "Điểm đánh giá",
        "score": "Điểm số",
        "balance": "Số dư",
        "gender": "Giới tính",
        "hiredate": "Năm tuyển dụng",
        "saledate": "Thời gian bán",
        "orderdate": "Ngày đặt hàng",
        "createdat": "Thời gian tạo",
        "date": "Thời gian",
        "year": "Năm",
        "month": "Tháng",
        "quarter": "Quý",
        "fee": "Phí dịch vụ",
        "age": "Độ tuổi",
    }
    if norm in vi_terms:
        return vi_terms[norm]

    # Nhận diện theo từ khóa thành phần
    if any(k in norm for k in ["price", "gia", "dongia"]):
        return "Đơn giá"
    if any(k in norm for k in ["cost", "chiphi", "giavon"]):
        return "Chi phí"
    if any(k in norm for k in ["profit", "loinhuan", "lai"]):
        return "Lợi nhuận"
    if any(k in norm for k in ["sales", "doanhso", "revenue", "doanhthu"]):
        return "Doanh số"
    if any(k in norm for k in ["salary", "luong", "payroll", "thunhap"]):
        return "Mức lương"
    if any(k in norm for k in ["count", "soluong", "qty", "quantity"]):
        return "Số lượng"
    if any(k in norm for k in ["date", "ngay"]):
        return "Ngày"
    if any(k in norm for k in ["time", "gio", "thoigian"]):
        return "Thời gian"

    clean = re.sub(r"([a-z])([A-Z])", r"\1 \2", s).replace("_", " ").strip().title()
    return clean


def humanize_name_en(name: str) -> str:
    """Chuyển đổi tên bảng hoặc tên cột kỹ thuật (e.g. order_date, total_amount) sang cụm từ tiếng Anh tự nhiên."""
    if not name:
        return ""
    s = str(name).strip()
    norm = re.sub(r"[^a-zA-Z0-9]", "", s).lower()
    en_terms = {
        "sales": "Sales",
        "totalsales": "Total Sales",
        "revenue": "Revenue",
        "amount": "Amount",
        "totalamount": "Total Amount",
        "price": "Price",
        "unitprice": "Unit Price",
        "cost": "Cost",
        "totalcost": "Total Cost",
        "profit": "Profit",
        "netprofit": "Net Profit",
        "salary": "Salary",
        "currentsalary": "Current Salary",
        "totalsalary": "Total Payroll",
        "payroll": "Payroll",
        "boxes": "Boxes",
        "totalboxes": "Total Boxes",
        "quantity": "Quantity",
        "qty": "Quantity",
        "orders": "Orders",
        "totalorders": "Total Orders",
        "count": "Count",
        "headcount": "Headcount",
        "employees": "Employees",
        "employee": "Employee",
        "departments": "Departments",
        "department": "Department",
        "deptname": "Department",
        "deptno": "Department Code",
        "empno": "Employee ID",
        "firstname": "First Name",
        "lastname": "Last Name",
        "gender": "Gender",
        "birthdate": "Birth Date",
        "hiredate": "Hire Date",
        "fromdate": "From Date",
        "todate": "To Date",
        "title": "Title",
        "product": "Product",
        "products": "Products",
        "category": "Category",
        "team": "Team",
        "salesperson": "Salesperson",
        "geo": "Region / Country",
        "customers": "Customers",
        "customer": "Customer",
        "date": "Date",
        "orderdate": "Order Date",
        "year": "Year",
        "month": "Month",
        "quarter": "Quarter",
        "fee": "Service Fee",
        "age": "Age",
    }
    if norm in en_terms:
        return en_terms[norm]
    clean = re.sub(r"([a-z])([A-Z])", r"\1 \2", s).replace("_", " ").strip().title()
    return clean


def parse_schema_elements(tables: list[str], schema_context: str = "") -> dict:
    """Tự động phân tích sâu toàn bộ CSDL đang kết nối: Trích xuất Bảng, Cột đo lường, Cột thời gian, Chiều phân loại và Dữ liệu mẫu."""
    tbl_cols_map = {}
    time_cols = []
    metric_cols = []
    dim_cols = []
    entity_cols = []
    sample_values = {}

    # 1. Bóc tách danh sách cột từ schema_context
    lines = (schema_context or "").splitlines()
    curr_tbl = None
    for line in lines:
        l_str = line.strip()
        tbl_match = re.match(r"^-\s*Bảng\s*[`'\"]?(\w+)[`'\"]?:\s*(.*)$", l_str, re.IGNORECASE)
        if tbl_match:
            t_name = tbl_match.group(1)
            raw_cols = tbl_match.group(2)
            curr_tbl = t_name
            cols = []
            for c_part in raw_cols.split(","):
                c_clean = c_part.split("(")[0].replace("`", "").replace("'", "").replace('"', "").strip()
                if c_clean:
                    cols.append(c_clean)
            tbl_cols_map[t_name] = cols
        elif l_str.startswith("• Bảng") and "cột" in l_str:
            # Trích xuất sample values: • Bảng `products` (cột `Category`): 'Bars', 'Bites'
            samp_match = re.search(r"Bảng\s*[`'\"]?(\w+)[`'\"]?\s*\(cột\s*[`'\"]?(\w+)[`'\"]?\):\s*(.*)$", l_str)
            if samp_match:
                c_name = samp_match.group(2)
                raw_samps = samp_match.group(3)
                s_list = [s.strip().strip("'\"`") for s in raw_samps.split(",") if s.strip()]
                if s_list:
                    sample_values[c_name.lower()] = s_list[:5]

    # Nếu không parse được từ text, dùng danh sách tables mặc định
    if not tbl_cols_map and tables:
        for t in tables:
            tbl_cols_map[t] = []

    # 2. Phân loại ngữ nghĩa cho tất cả các cột
    for t_name, cols in tbl_cols_map.items():
        for c in cols:
            c_low = c.lower()
            if is_id_like(c) and not any(k in c_low for k in ["name", "title", "spid", "pid"]):
                continue

            # Thời gian
            if any(k in c_low for k in ["date", "time", "year", "month", "quarter", "ngay", "nam", "thang", "created", "hire", "sale"]):
                if c not in time_cols:
                    time_cols.append(c)
            # Đo lường số liệu (Metrics)
            elif any(k in c_low for k in ["sales", "amount", "price", "cost", "profit", "salary", "boxes", "qty", "quantity", "revenue", "fee", "balance", "total", "spent", "fare", "count", "rating", "score", "duration", "hours", "tien", "luong", "doanh_thu", "chi_phi", "so_luong"]):
                if c not in metric_cols:
                    metric_cols.append(c)
            # Tên thực thể
            elif any(k in c_low for k in ["name", "title", "salesperson", "fullname", "product", "customer", "employee", "patient", "doctor", "student", "airline", "passenger", "ten"]):
                if c not in entity_cols:
                    entity_cols.append(c)
            # Chiều phân loại (Dimensions)
            elif any(k in c_low for k in ["category", "type", "status", "country", "city", "geo", "region", "team", "department", "dept", "branch", "gender", "segment", "class", "genre", "trang_thai", "loai", "phong_ban", "quoc_gia", "seat"]):
                if c not in dim_cols:
                    dim_cols.append(c)
            else:
                # Phân loại bổ sung
                if len(cols) <= 4 and c not in dim_cols:
                    dim_cols.append(c)

    # Sắp xếp ưu tiên: Các chỉ số tiền tệ / tài chính / số lượng chủ đạo lên đầu
    def _metric_priority(m: str) -> int:
        ml = m.lower()
        if any(k in ml for k in ["revenue", "sales", "totalamount", "amount", "totalsales", "salary", "totalsalary", "profit", "price", "ticket_price", "fare"]):
            return 0
        if any(k in ml for k in ["cost", "fee", "balance", "boxes", "quantity", "qty", "orders"]):
            return 1
        return 2

    metric_cols = sorted(metric_cols, key=_metric_priority)

    def _dim_priority(d: str) -> int:
        dl = d.lower()
        if any(k in dl for k in ["category", "department", "dept", "team", "airline", "country", "city", "branch", "type"]):
            return 0
        if any(k in dl for k in ["status", "gender", "seat", "role", "segment"]):
            return 1
        return 2

    dim_cols = sorted(dim_cols, key=_dim_priority)

    return {
        "tables": list(tbl_cols_map.keys()) or tables,
        "tbl_cols_map": tbl_cols_map,
        "time_cols": time_cols,
        "metric_cols": metric_cols,
        "dim_cols": dim_cols,
        "entity_cols": entity_cols,
        "sample_values": sample_values
    }


def _svg_icon(name: str, color: str = "#00F0FF") -> str:
    """Trả về SVG icon chuẩn Lucide tối giản, sắc nét cho SaaS cao cấp."""
    icons = {
        "trend": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>',
        "calendar": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>',
        "peak": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>',
        "ranking": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><circle cx="12" cy="8" r="7"></circle><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"></polyline></svg>',
        "layers": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>',
        "balance": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><line x1="12" y1="3" x2="12" y2="21"></line><path d="M17 7l4 4-4 4"></path><path d="M7 17l-4-4 4-4"></path></svg>',
        "target": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>',
        "dollar": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>',
        "search": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
        "chart": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>',
        "activity": f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px;"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>'
    }
    return icons.get(name, icons["chart"])


def generate_dynamic_heuristic_prompts(tables: list[str], schema_context: str = "", lang: str = "vi") -> dict[str, list[dict]]:
    """Tự động phân tích cấu trúc CSDL thực tế và sinh các câu hỏi phân tích thông minh theo 3 lăng kính điều hành mà KHÔNG bị code cứng."""
    meta = parse_schema_elements(tables, schema_context)
    tbl_list = meta["tables"]
    time_cols = meta["time_cols"]
    metric_cols = meta["metric_cols"]
    dim_cols = meta["dim_cols"]
    entity_cols = meta["entity_cols"]
    samples = meta["sample_values"]

    is_en = (lang == "en")

    # Chọn các phần tử chủ đạo
    main_time = time_cols[0] if time_cols else ("Time" if is_en else "Thời gian")
    main_metric = metric_cols[0] if metric_cols else (("Count" if tbl_list else "Value") if is_en else ("Số lượng" if tbl_list else "Giá trị"))
    sec_metric = metric_cols[1] if len(metric_cols) > 1 else main_metric
    main_dim = dim_cols[0] if dim_cols else (entity_cols[0] if entity_cols else (tbl_list[0] if tbl_list else ("Category" if is_en else "Phân loại")))
    sec_dim = dim_cols[1] if len(dim_cols) > 1 else main_dim
    main_entity = entity_cols[0] if entity_cols else (tbl_list[0] if tbl_list else ("Entity" if is_en else "Đối tượng"))
    main_table = tbl_list[0] if tbl_list else ("Data" if is_en else "Dữ liệu")

    # Nhãn thân thiện
    if is_en:
        h_time = humanize_name_en(main_time)
        h_metric = humanize_name_en(main_metric)
        h_sec_metric = humanize_name_en(sec_metric)
        h_dim = humanize_name_en(main_dim)
        h_sec_dim = humanize_name_en(sec_dim)
        h_entity = humanize_name_en(main_entity)
        h_table = humanize_name_en(main_table)

        # 1. LĂNG KÍNH 1: TRENDS & TIME
        trend_cards = []
        if time_cols:
            trend_cards.append({
                "icon": _svg_icon("trend", "#00F0FF"),
                "title": f"{h_metric} Trends Over {h_time}",
                "prompt": f"How has total {h_metric.lower()} changed over {h_time.lower()}?",
                "desc": f"Line chart tracking {h_metric.lower()} growth cycle across time"
            })
            if dim_cols:
                trend_cards.append({
                    "icon": _svg_icon("calendar", "#38BDF8"),
                    "title": f"Dynamics Across {h_dim}",
                    "prompt": f"Compare {h_metric.lower()} changes across {h_dim.lower()} over time",
                    "desc": f"Benchmark growth rate between {h_dim.lower()} segments"
                })
            else:
                trend_cards.append({
                    "icon": _svg_icon("chart", "#00F0FF"),
                    "title": f"Summary by {h_time}",
                    "prompt": f"Summary of total {h_metric.lower()} and record count by {h_time.lower()}",
                    "desc": f"Periodic report across {h_time.lower()} series"
                })
            trend_cards.append({
                "icon": _svg_icon("peak", "#F59E0B"),
                "title": f"Peak {h_metric} Periods",
                "prompt": f"Which time period recorded the highest and lowest {h_metric.lower()}?",
                "desc": f"Detect seasonal peaks or anomalous spikes"
            })
        else:
            trend_cards.append({
                "icon": _svg_icon("chart", "#00F0FF"),
                "title": f"Overall {h_metric} Overview",
                "prompt": f"Total {h_metric.lower()} and average value across all records",
                "desc": f"Holistic high-level picture of {h_metric.lower()}"
            })
            trend_cards.append({
                "icon": _svg_icon("trend", "#38BDF8"),
                "title": f"{h_metric} Breakdown by {h_dim}",
                "prompt": f"Breakdown of total {h_metric.lower()} by each {h_dim.lower()}",
                "desc": f"Identify distribution variance across {h_dim.lower()}"
            })
            trend_cards.append({
                "icon": _svg_icon("search", "#A855F7"),
                "title": f"Explore {h_table} Table",
                "prompt": f"Show record count and top 10 sample rows of {main_table} table",
                "desc": f"Preview underlying structured data in {main_table}"
            })

        # 2. LĂNG KÍNH 2: RANKING & SEGMENTATION
        rank_cards = []
        rank_cards.append({
            "icon": _svg_icon("ranking", "#F59E0B"),
            "title": f"Top 10 Highest {h_entity}",
            "prompt": f"Top 10 {h_entity.lower()} with highest total {h_metric.lower()}",
            "desc": f"Leaderboard of top-performing {h_entity.lower()} in {h_metric.lower()}"
        })
        if dim_cols:
            rank_cards.append({
                "icon": _svg_icon("layers", "#8B5CF6"),
                "title": f"{h_dim} Contribution Share",
                "prompt": f"Contribution percentage of each {h_dim.lower()} to total {h_metric.lower()}",
                "desc": f"Donut/pie breakdown of {h_dim.lower()} portfolio share"
            })
            rank_cards.append({
                "icon": _svg_icon("balance", "#00DF8F"),
                "title": f"Compare Across {h_dim}",
                "prompt": f"Compare average {h_metric.lower()} across different {h_dim.lower()}",
                "desc": f"Benchmark performance between {h_dim.lower()} segments"
            })
        else:
            rank_cards.append({
                "icon": _svg_icon("ranking", "#F59E0B"),
                "title": f"Top Performing Leaders",
                "prompt": f"List top 5 {h_entity.lower()} with the most outstanding results",
                "desc": f"Highlight standout individual entities"
            })
            rank_cards.append({
                "icon": _svg_icon("layers", "#8B5CF6"),
                "title": f"Full Ranking List",
                "prompt": f"Rank all records in descending order of {h_metric.lower()}",
                "desc": f"Complete ranking from highest to lowest"
            })

        # 3. LĂNG KÍNH 3: PERFORMANCE & STRUCTURE
        perf_cards = []
        perf_cards.append({
            "icon": _svg_icon("target", "#EF4444"),
            "title": f"{h_entity} Above Average",
            "prompt": f"Which {h_entity.lower()} have {h_metric.lower()} above average?",
            "desc": f"Filter out top-tier overperforming entities"
        })
        if len(metric_cols) >= 2:
            perf_cards.append({
                "icon": _svg_icon("dollar", "#00DF8F"),
                "title": f"{h_metric} & {h_sec_metric} Correlation",
                "prompt": f"Combined report of {h_metric.lower()} and {h_sec_metric.lower()} by {h_dim.lower()}",
                "desc": f"Multi-dimensional correlation between two key metrics"
            })
        else:
            perf_cards.append({
                "icon": _svg_icon("chart", "#00F0FF"),
                "title": f"{h_dim} Detailed Statistics",
                "prompt": f"Count and total {h_metric.lower()} grouped by each {h_dim.lower()}",
                "desc": f"Comprehensive aggregate statistics by group"
            })
        perf_cards.append({
            "icon": _svg_icon("search", "#38BDF8"),
            "title": f"Anomalies & Gap Analysis",
            "prompt": f"Analyze the {h_metric.lower()} spread between highest and lowest group",
            "desc": f"Measure disparity range and variance distribution"
        })

        return {
            "Trends & Time": trend_cards[:3],
            "Ranking & Segmentation": rank_cards[:3],
            "Performance & Structure": perf_cards[:3]
        }

    else:
        h_time = humanize_name_vi(main_time)
        h_metric = humanize_name_vi(main_metric)
        h_sec_metric = humanize_name_vi(sec_metric)
        h_dim = humanize_name_vi(main_dim)
        h_sec_dim = humanize_name_vi(sec_dim)
        h_entity = humanize_name_vi(main_entity)
        h_table = humanize_name_vi(main_table)

        # 1. LĂNG KÍNH 1: XU HƯỚNG & BIẾN ĐỘNG THỜI GIAN
        trend_cards = []
        if time_cols:
            trend_cards.append({
                "icon": _svg_icon("trend", "#00F0FF"),
                "title": f"Xu Hướng {h_metric} Theo {h_time}",
                "prompt": f"Xu hướng tổng {h_metric.lower()} theo từng {h_time.lower()} thay đổi như thế nào?",
                "desc": f"Biểu đồ đường theo dõi chu kỳ tăng trưởng {h_metric.lower()} qua thời gian"
            })
            if dim_cols:
                trend_cards.append({
                    "icon": _svg_icon("calendar", "#38BDF8"),
                    "title": f"Biến Động Theo {h_dim}",
                    "prompt": f"So sánh biến động {h_metric.lower()} giữa các {h_dim.lower()} qua các mốc thời gian",
                    "desc": f"Đối chiếu tốc độ tăng trưởng giữa các nhóm {h_dim.lower()}"
                })
            else:
                trend_cards.append({
                    "icon": _svg_icon("chart", "#00F0FF"),
                    "title": f"Tổng Hợp Theo {h_time}",
                    "prompt": f"Thống kê tổng {h_metric.lower()} và số lượng giao dịch theo từng {h_time.lower()}",
                    "desc": f"Báo cáo định kỳ theo chuỗi {h_time.lower()}"
                })
            trend_cards.append({
                "icon": _svg_icon("peak", "#F59E0B"),
                "title": f"Giai Đoạn Đạt Đỉnh {h_metric}",
                "prompt": f"Khoảng thời gian nào ghi nhận {h_metric.lower()} cao nhất và thấp nhất?",
                "desc": f"Phát hiện các mốc mùa vụ hoặc thời điểm đột biến"
            })
        else:
            trend_cards.append({
                "icon": _svg_icon("chart", "#00F0FF"),
                "title": f"Tổng Quan {h_metric} Toàn Hệ Thống",
                "prompt": f"Tổng {h_metric.lower()} và giá trị trung bình trên toàn bộ dữ liệu",
                "desc": f"Bức tranh tổng thể về chỉ số {h_metric.lower()}"
            })
            trend_cards.append({
                "icon": _svg_icon("trend", "#38BDF8"),
                "title": f"Phân Bổ {h_metric} Theo {h_dim}",
                "prompt": f"Phân bổ tổng {h_metric.lower()} theo từng {h_dim.lower()}",
                "desc": f"Xác định độ lệch phân bổ giữa các {h_dim.lower()}"
            })
            trend_cards.append({
                "icon": _svg_icon("search", "#A855F7"),
                "title": f"Khám Phá Dữ Liệu {h_table}",
                "prompt": f"Thống kê tổng số lượng bản ghi và xem 10 dòng tiêu biểu của bảng {main_table}",
                "desc": f"Xem trước dữ liệu chi tiết của bảng {main_table}"
            })

        # 2. LĂNG KÍNH 2: XẾP HẠNG & PHÂN KHÚC
        rank_cards = []
        rank_cards.append({
            "icon": _svg_icon("ranking", "#F59E0B"),
            "title": f"Top 10 {h_entity} Cao Nhất",
            "prompt": f"Top 10 {h_entity.lower()} có tổng {h_metric.lower()} cao nhất",
            "desc": f"Bảng xếp hạng những {h_entity.lower()} dẫn đầu về {h_metric.lower()}"
        })
        if dim_cols:
            rank_cards.append({
                "icon": _svg_icon("layers", "#8B5CF6"),
                "title": f"Tỷ Trọng Đóng Góp {h_dim}",
                "prompt": f"Tỷ lệ đóng góp {h_metric.lower()} của từng {h_dim.lower()} vào tổng số",
                "desc": f"Biểu đồ cơ cấu phân rã tỷ trọng của danh mục {h_dim.lower()}"
            })
            rank_cards.append({
                "icon": _svg_icon("balance", "#00DF8F"),
                "title": f"So Sánh Giữa Các {h_dim}",
                "prompt": f"So sánh {h_metric.lower()} trung bình giữa các {h_dim.lower()}",
                "desc": f"Đối chuẩn hiệu quả giữa các phân khúc {h_dim.lower()}"
            })
        else:
            rank_cards.append({
                "icon": _svg_icon("ranking", "#F59E0B"),
                "title": f"Top Đối Tượng Dẫn Đầu",
                "prompt": f"Danh sách 5 {h_entity.lower()} có kết quả nổi bật nhất",
                "desc": f"Vinh danh các cá nhân/thực thể xuất sắc"
            })
            rank_cards.append({
                "icon": _svg_icon("layers", "#8B5CF6"),
                "title": f"Xếp Hạng Phổ Biến",
                "prompt": f"Xếp hạng các bản ghi theo thứ tự giảm dần của {h_metric.lower()}",
                "desc": f"Danh sách đầy đủ từ cao xuống thấp"
            })

        # 3. LĂNG KÍNH 3: HIỆU SUẤT & CƠ CẤU
        perf_cards = []
        perf_cards.append({
            "icon": _svg_icon("target", "#EF4444"),
            "title": f"{h_entity} Vượt Mức Trung Bình",
            "prompt": f"Những {h_entity.lower()} nào có {h_metric.lower()} vượt trên mức trung bình?",
            "desc": f"Lọc ra nhóm đối tượng có hiệu năng cao vượt trội"
        })
        if len(metric_cols) >= 2:
            perf_cards.append({
                "icon": _svg_icon("dollar", "#00DF8F"),
                "title": f"Tương Quan {h_metric} & {h_sec_metric}",
                "prompt": f"Báo cáo kết hợp cả {h_metric.lower()} và {h_sec_metric.lower()} theo từng {h_dim.lower()}",
                "desc": f"Đối chiếu đa chiều giữa hai chỉ số đo lường chính"
            })
        else:
            perf_cards.append({
                "icon": _svg_icon("chart", "#00F0FF"),
                "title": f"Thống Kê Chi Tiết {h_dim}",
                "prompt": f"Thống kê số lượng và tổng {h_metric.lower()} theo từng {h_dim.lower()}",
                "desc": f"Tổng hợp số liệu chi tiết phân theo nhóm"
            })
        perf_cards.append({
            "icon": _svg_icon("search", "#38BDF8"),
            "title": f"Phân Tích Bất Thường & Chênh Lệch",
            "prompt": f"Phân tích sự chênh lệch {h_metric.lower()} giữa nhóm cao nhất và nhóm thấp nhất",
            "desc": f"Đo lường khoảng cách phân hóa trong dữ liệu"
        })

        return {
            "Xu hướng & Thời gian": trend_cards[:3],
            "Xếp hạng & Phân khúc": rank_cards[:3],
            "Hiệu suất & Cơ cấu": perf_cards[:3]
        }


def generate_categorized_starter_prompts(
    tables: list[str],
    schema_context: str = "",
    client=None,
    model_name: str = "",
    provider: str = "",
    lang: str = "vi"
) -> dict[str, list[dict]]:
    """Tự động sinh các thẻ gợi ý câu hỏi phân tích thông minh cho BẤT KỲ cơ sở dữ liệu nào:
    - Phân tích động 100% bám sát schema, bảng, cột thực tế của database hiện tại.
    - Hỗ trợ song ngữ Tiếng Việt và English theo tham số lang.
    """
    if not tables and not schema_context:
        if lang == "en":
            return {
                "📊 Explore": [
                    {"icon": "🔍", "title": "Database Overview", "prompt": "Show overview of all tables in the database", "desc": "Explore database structure"}
                ]
            }
        return {
            "📊 Khám phá": [
                {"icon": "🔍", "title": "Tổng Quan Cơ Sở Dữ Liệu", "prompt": "Hiển thị tổng quan các bảng trong cơ sở dữ liệu", "desc": "Khám phá cấu trúc bảng"}
            ]
        }

    schema_key = f"{lang}_{len(tables)}_{hash(schema_context)}"
    if schema_key in _DYNAMIC_STARTER_CACHE:
        return _DYNAMIC_STARTER_CACHE[schema_key]

    # 1. Sinh gợi ý phân tích động bám sát cấu trúc CSDL hiện tại
    categorized = generate_dynamic_heuristic_prompts(tables, schema_context, lang=lang)

    # Lưu cache để các lần chuyển tab hoặc rerun không bị tốn tài nguyên
    _DYNAMIC_STARTER_CACHE[schema_key] = categorized
    return categorized


def generate_starter_prompts(
    tables: list[str],
    schema_context: str = "",
    client=None,
    model_name: str = "",
    provider: str = "",
    lang: str = "vi"
) -> list[dict]:
    """Tự động sinh 4 thẻ gợi ý câu hỏi thông minh 1-chạm bám sát chính xác nghiệp vụ và cấu trúc bảng của CSDL."""
    cat = generate_categorized_starter_prompts(tables, schema_context, client=client, model_name=model_name, provider=provider, lang=lang)
    cards = []
    for cat_name, c_list in cat.items():
        if c_list:
            cards.append(c_list[0])
    first_cat = list(cat.values())[0] if cat else []
    if len(first_cat) > 1 and first_cat[1] not in cards:
        cards.append(first_cat[1])

    while len(cards) < 4:
        if lang == "en":
            cards.append({
                "icon": "🔍",
                "title": "Database Overview",
                "prompt": "Count total records across all tables in the database",
                "desc": "Holistic overview of current dataset"
            })
        else:
            cards.append({
                "icon": "🔍",
                "title": "Tổng Quan CSDL",
                "prompt": "Thống kê tổng số lượng bản ghi trên tất cả các bảng",
                "desc": "Tổng hợp bức tranh toàn cảnh về dữ liệu hiện tại"
            })
    return cards[:4]



def repair_truncated_text(text: str, is_en: bool = False) -> str:
    """Tự động phát hiện và hoàn thiện các câu bị cụt lửng / đứt gãy do LLM cạn token."""
    if not text:
        return text
    t = text.strip()
    # Loại bỏ dấu chấm tạm thời ở cuối nếu trước đó là từ nối/từ cụt lửng (VD: 'nhằm c.' -> 'nhằm c')
    t = re.sub(r"\.\s*$", "", t).strip()

    dangling_patterns_vi = [
        (r"(?i)\b(?:nhằm|để|và|với|tại|trong|cho|của|như|là|qua|bằng|do)\s+[a-zA-Zà-ỹÀ-Ỹ0-9]{1,3}$", "củng cố vị thế dẫn dắt và gia tăng hiệu quả vận hành"),
        (r"(?i)\b(?:nhằm|để)\s*$", "củng cố vị thế cạnh tranh và tối ưu hóa hiệu quả dài hạn"),
        (r"(?i)\b(?:và|với|tại|trong|cho|của|như|là|qua|bằng|do)\s*$", "các thị trường trọng điểm"),
    ]
    dangling_patterns_en = [
        (r"(?i)\b(?:to|in\s+order\s+to|and|with|at|in|for|of|as|is|by)\s+[a-zA-Z0-9]{1,3}$", "solidify market leadership and optimize operational efficiency"),
        (r"(?i)\b(?:to|in\s+order\s+to)\s*$", "solidify competitive advantage and optimize long-term output"),
        (r"(?i)\b(?:and|with|at|in|for|of|as|is|by)\s*$", "key priority markets"),
    ]

    patterns = dangling_patterns_en if is_en else dangling_patterns_vi
    for pat, fix in patterns:
        if re.search(pat, t):
            t = re.sub(pat, fix, t)
            break

    if not t.endswith((".", "!", "?")):
        t += "."
    return t


def sanitize_insight_markdown(text: str, is_en: bool = False) -> str:
    """Tự động làm sạch hoàn toàn các lỗi định dạng markdown của AI:
    - CẤM TỰ Ý IN ĐẬM TRONG CÂU: Chỉ in đậm duy nhất Tiêu đề ở đầu gạch đầu dòng trước dấu hai chấm.
    - Xóa toàn bộ dấu ** thừa, mồ côi hoặc chèn lung tung trong thân câu.
    - Tách toàn bộ chữ dính với %, số, và tên riêng (Jucies để, đạt 28,490,175, 11.0% so).
    - Khôi phục và chuẩn hóa tiêu đề ### 2.1. 🚨, ### 2.2. 🔍, ### 2.3. 🎯
    - Tự động phát hiện và vá các câu bị cắt cụt do cạn token.
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
            clean_rest = repair_truncated_text(clean_rest, is_en=is_en)
            l = f"{prefix_out}: {clean_rest}"
        else:
            # Dòng không có dấu hai chấm: Xóa TOÀN BỘ **
            clean_l = l.replace("**", "").replace("*", "").strip()
            clean_l = repair_truncated_text(clean_l, is_en=is_en)
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

    # Thoát ký tự $ để tránh lỗi font dính chữ LaTeX trên Streamlit KaTeX
    text = escape_markdown_currency_symbols(text)

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


def format_entity_label(val, col_name: str = "", lang: str = "vi") -> str:
    """Định dạng nhãn thực thể hoặc thời gian không bị đuôi số thập phân .0 và chuyển tháng/quý/năm sang nhãn thân thiện:
    - Tháng 1..12: 'Tháng 1', 'Tháng 2',..., 'Tháng 12' (hoặc 'Month 1' nếu tiếng Anh)
    - Quý 1..4: 'Quý 1',..., 'Quý 4' (hoặc 'Q1'..'Q4')
    - Năm YYYY: '2021'
    """
    if val is None or (hasattr(pd, "isna") and pd.isna(val) is True):
        return "N/A"
    s = str(val).strip()
    if re.match(r"^-?\d+\.0+$", s):
        s = s.split(".")[0]
    c_low = str(col_name).lower() if col_name else ""
    try:
        f_val = float(val)
        if f_val.is_integer():
            i_val = int(f_val)
            is_m_col = any(k in c_low for k in ["month", "tháng", "thang"])
            is_q_col = any(k in c_low for k in ["quarter", "quý", "quy"])
            is_y_col = any(k in c_low for k in ["year", "năm", "nam", "hireyear"])
            if is_m_col and 1 <= i_val <= 12:
                return f"Tháng {i_val}" if lang != "en" else f"Month {i_val}"
            elif is_q_col and 1 <= i_val <= 4:
                return f"Quý {i_val}" if lang != "en" else f"Q{i_val}"
            elif is_y_col and 1900 <= i_val <= 2100:
                return str(i_val)
            elif 1 <= i_val <= 12 and any(k in c_low for k in ["tháng", "month"]):
                return f"Tháng {i_val}" if lang != "en" else f"Month {i_val}"
            return str(i_val)
    except Exception:
        pass
    m_ym = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if m_ym:
        return f"Tháng {int(m_ym.group(2))}/{m_ym.group(1)}" if lang != "en" else f"Month {int(m_ym.group(2))}/{m_ym.group(1)}"
    return s


def format_metric_value(val, col_name: str = "") -> str:
    """Định dạng số liệu hiển thị trong Insight theo ngữ cảnh nghiệp vụ:
    - Boxes / Headcount / Count / Số lượng: Số nguyên có dấu phẩy phân cách hàng nghìn (117,165), tuyệt đối không để .00 hay .40.
    - Currency (Sales, Amount, Revenue, Profit, Cost, Salary, Lương): $165,736 hoặc $165,736.50 nếu có số lẻ.
    - Percent / Margin / Tỷ lệ: 40.8% hoặc 40.85%.
    """
    if val is None or pd.isna(val):
        return "N/A"
    try:
        f_val = float(val)
    except Exception:
        return str(val)

    c_low = str(col_name).lower() if col_name else ""
    is_pct = any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ", "share", "ratio"])
    if is_pct:
        return f"{f_val:.2f}%" if not f_val.is_integer() else f"{f_val:.1f}%"

    is_perbox_curr = any(k in c_low for k in ["profitperbox", "profit_per_box", "cost_per_box", "costperbox", "revenueperbox", "revenue_per_box", "priceperbox", "price_per_box", "perbox", "per_box"])
    if is_perbox_curr:
        return f"${f_val:.2f}" if not f_val.is_integer() else f"${f_val:,.0f}"

    is_count = any(k in c_low for k in ["totalboxes", "boxes", "box", "hộp", "thùng", "headcount", "nhân sự", "nhân viên", "slngnhnvin", "count", "số lượng", "employee", "customer", "đối tượng"]) and not is_perbox_curr
    if is_count:
        return f"{round(f_val):,.0f}"

    is_curr = any(k in c_low for k in ["salary", "lương", "cost", "revenue", "sales", "amount", "profit", "budget", "thu_nhập", "price", "giá", "đơn giá", "tiền", "spread", "delta", "dongia", "giaban"])
    if is_curr:
        if abs(f_val) >= 1000 or f_val.is_integer():
            return f"${round(f_val):,.0f}" if f_val.is_integer() else f"${f_val:,.2f}"
        return f"${f_val:,.2f}"

    if f_val.is_integer():
        return f"{int(f_val):,}"
    return f"{f_val:,.2f}"


def escape_markdown_currency_symbols(text: str) -> str:
    r"""Thoát ký tự đô-la ($) sang (\$ ) trong chuỗi Markdown để tránh bị KaTeX trên Streamlit
    hiểu nhầm hai số tiền là công thức toán học inline làm dính chữ, rụng khoảng trắng và nuốt mất ký hiệu $.
    """
    if not text:
        return ""
    # Thoát mọi ký tự $ chưa có dấu gạch chéo ngược đứng trước
    return re.sub(r'(?<!\\)\$', r'\$', str(text))


def detect_tradeoff_insight(df: pd.DataFrame, name_col: str = None, val_col: str = None, is_en: bool = False) -> str | None:
    """Phát hiện Nghịch lý Đánh đổi (Trade-off Matrix) giữa chỉ số tỷ lệ (%) và chỉ số tiền mặt tuyệt đối ($)."""
    if df is None or df.empty:
        return None
    try:
        if not name_col:
            cat_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
            name_col = cat_cols[0] if cat_cols else df.columns[0]

        pct_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất", "%"]) and pd.api.types.is_numeric_dtype(df[c])), None)
        cash_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["profitperbox", "profit_per_box", "profit", "lợi nhuận", "lãi", "amount", "revenue", "cost_per_box"]) 
                         and not any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất", "%"]) 
                         and pd.api.types.is_numeric_dtype(df[c])), None)

        if not pct_col or not cash_col:
            return None

        clean_pct = pd.to_numeric(df[pct_col], errors="coerce").dropna()
        clean_cash = pd.to_numeric(df[cash_col], errors="coerce").dropna()
        if clean_pct.empty or clean_cash.empty:
            return None

        top_pct_idx = clean_pct.idxmax()
        top_cash_idx = clean_cash.idxmax()

        top_pct_name = format_entity_label(df.loc[top_pct_idx, name_col])
        top_cash_name = format_entity_label(df.loc[top_cash_idx, name_col])

        top_pct_val = float(df.loc[top_pct_idx, pct_col])
        top_pct_cash = float(df.loc[top_pct_idx, cash_col])

        top_cash_val = float(df.loc[top_cash_idx, cash_col])
        top_cash_pct = float(df.loc[top_cash_idx, pct_col])

        if top_pct_name != top_cash_name:
            pct_cash_fmt = format_metric_value(top_pct_cash, cash_col)
            if not pct_cash_fmt.startswith("$") and not pct_cash_fmt.endswith("%"):
                pct_cash_fmt = f"${pct_cash_fmt}"
            cash_val_fmt = format_metric_value(top_cash_val, cash_col)
            if not cash_val_fmt.startswith("$") and not cash_val_fmt.endswith("%"):
                cash_val_fmt = f"${cash_val_fmt}"

            if is_en:
                return (
                    f"• **Trade-off Matrix (Margin % vs. Net Cash $)**: **{top_pct_name}** commands the highest margin ({top_pct_val:.2f}%) but yields the lowest net unit profit ({pct_cash_fmt}/box). "
                    f"Conversely, **{top_cash_name}** operates at a lower margin ({top_cash_pct:.2f}% but reaches {cash_val_fmt}/box)."
                )
            else:
                return (
                    f"• **Nghịch lý Đánh đổi (Trade-off Matrix)**: **{top_pct_name}** dẫn đầu về tỷ suất lợi nhuận ({top_pct_val:.2f}%) nhưng thu về mức tiền lời ròng mỗi hộp thấp nhất ({pct_cash_fmt}/hộp). "
                    f"Trái lại, **{top_cash_name}** có tỷ suất thấp hơn ({top_cash_pct:.2f}% nhưng đạt tới {cash_val_fmt}/hộp)."
                )
    except Exception:
        pass
    return None


def detect_analysis_entity_type(df: pd.DataFrame = None, user_query: str = "", name_col: str = None) -> str:
    """Xác định chính xác đối tượng đang phân tích trong bảng dữ liệu:
    - 'product': Sản phẩm, hàng hóa, SKU, danh mục hàng hóa (Chocolate, Bars, Bites, Category...)
    - 'team': Đội ngũ, chi nhánh, team kinh doanh (Delish, Jucies, Yummies, Branch, Chi nhánh...)
    - 'employee': Nhân sự, nhân viên, chức danh, phòng ban trong tổ chức (Salesperson, Title, Department...)
    - 'geo': Thị trường, quốc gia, vùng địa lý (New Zealand, USA, India, UK, Canada, Australia, g.Geo, Country...)
    - 'time_series': Chuỗi thời gian (Năm, Quý, Tháng, Ngày)
    - 'general': Chung / không xác định
    """
    q_low = (user_query or "").lower()
    ncol_low = str(name_col or "").lower()

    cols_str = ""
    if df is not None and not df.empty:
        cols_str = " ".join(str(c).lower() for c in df.columns)
        if not name_col:
            for c in df.columns:
                if not pd.api.types.is_numeric_dtype(df[c]):
                    name_col = c
                    ncol_low = str(c).lower()
                    break

    # 1. Nhận diện Time Series
    is_time_col = any(k in ncol_low for k in ["year", "month", "date", "năm", "tháng", "quý", "quarter", "kỳ"]) and not any(k in ncol_low for k in ["service", "tenure", "thâm niên", "tham_nien", "experience", "kinh nghiệm", "age", "tuoi"])
    is_time_query = any(k in q_low for k in ["qua các năm", "theo năm", "từng năm", "over time", "per year", "yearly", "xu hướng", "trend", "qua các tháng", "từng tháng", "theo quý", "qua các quý"])
    if is_time_col or (is_time_query and not any(k in cols_str for k in ["team", "đội ngũ", "product", "sản phẩm", "employee", "nhân viên", "salesperson", "geo", "country", "quốc gia", "thị trường", "dept", "phòng", "fullname", "họ và tên"])):
        return "time_series"

    # 2. Nhận diện Phòng ban (Department)
    is_dept_col = any(k in ncol_low for k in ["department", "dept_name", "dept_no", "dept", "phòng ban", "phòng", "bộ phận"])
    known_depts = ["customer service", "development", "finance", "human resources", "marketing", "production", "quality management", "research", "sales", "tiếp thị", "nhân sự", "kỹ thuật", "tài chính", "sản xuất", "kinh doanh", "cskh"]
    is_dept_values = False
    if df is not None and not df.empty and name_col and name_col in df.columns:
        sample_vals = [str(v).strip().lower() for v in df[name_col].dropna().head(10)]
        if any(v in known_depts for v in sample_vals):
            is_dept_values = True
    if is_dept_col or is_dept_values:
        return "department"

    # 3. Nhận diện Chức danh (Job Title)
    is_title_col = any(k in ncol_low for k in ["title", "chức danh", "vị trí", "chức vụ", "job"])
    known_titles = ["senior engineer", "staff engineer", "engineer", "assistant engineer", "senior staff", "technique leader", "manager", "chuyên viên", "kỹ sư"]
    is_title_values = False
    if df is not None and not df.empty and name_col and name_col in df.columns:
        sample_vals = [str(v).strip().lower() for v in df[name_col].dropna().head(10)]
        if any(v in known_titles for v in sample_vals):
            is_title_values = True
    if is_title_col or is_title_values:
        return "title"

    # 4. Nhận diện Giới tính (Gender)
    is_gen_col = any(k in ncol_low for k in ["gender", "giới tính", "gioi_tinh", "sex"])
    if df is not None and not df.empty and name_col and name_col in df.columns:
        raw_vals_upper = {str(v).strip().upper() for v in df[name_col].dropna()}
        if is_gen_col or raw_vals_upper.issubset({"M", "F", "MALE", "FEMALE", "NAM", "NỮ", "NU"}):
            return "gender"

    # 5. Nhận diện Nhân sự / Nhân viên bán hàng cá nhân (pe.Salesperson / Individual Employees)
    is_emp_col = any(k in ncol_low for k in ["fullname", "full_name", "họ và tên", "name", "tên", "salesperson", "sales_person", "sales person", "nhân viên", "nhân sự", "người bán", "emp_no", "first_name", "last_name", "rep", "spid"])
    
    known_salespeople = [
        "andria kimpton", "barr faughny", "benny karolovsky", "beverie moffet", "brien boise",
        "camilla castle", "ches bonnell", "curtice advani", "dennison crosswaite", "dotty strutley",
        "dyna doucette", "ebonee roxburgh", "gigi bohling", "gray seamon", "gunar cockshoot",
        "husein augar", "jan morforth", "janene hairsine", "jehu rudeforth", "kaine padly",
        "karlen mccaffrey", "kelci walkden", "madelene upcott", "mallorie waber", "marney o'breen",
        "niall selesnick", "oby sorrel", "orton livick", "rafaelita blaksland", "roddy speechley",
        "van tuxwell", "wilone o'kielt", "zach polon"
    ]
    is_emp_values = False
    if df is not None and not df.empty and name_col and name_col in df.columns:
        sample_vals = [str(v).strip().lower() for v in df[name_col].dropna().head(10)]
        if any(v in known_salespeople for v in sample_vals):
            is_emp_values = True

    is_emp_query = any(k in q_low for k in ["nhân viên", "nhân sự", "salesperson", "sales person", "người bán", "ai là", "top 5 nhân sự", "top nhân sự", "top nhân viên"])

    if is_emp_col or is_emp_values or (is_emp_query and not any(k in ncol_low for k in ["product", "sản phẩm", "sku", "geo", "country", "quốc gia", "team", "đội ngũ", "dept", "department", "phòng"])):
        return "employee"

    # 6. Nhận diện Thị trường / Quốc gia (Geo / Country / Market) - TUYỆT ĐỐI KHÔNG gộp với Team
    is_geo_col = any(k in ncol_low for k in ["geo", "country", "quốc gia", "thị trường", "market", "nation"])
    is_geo_query = any(k in q_low for k in ["thị trường", "quốc gia", "các nước", "từng nước", "country", "market", "geo"])
    
    known_geos = ["usa", "united states", "india", "uk", "united kingdom", "canada", "australia", "new zealand", "ấn độ", "mỹ", "úc"]
    is_geo_values = False
    if df is not None and not df.empty and name_col and name_col in df.columns:
        sample_vals = [str(v).strip().lower() for v in df[name_col].dropna().head(10)]
        if any(v in known_geos for v in sample_vals):
            is_geo_values = True

    if is_geo_col or is_geo_values or (is_geo_query and not any(k in ncol_low for k in ["team", "đội ngũ", "product", "sản phẩm", "sku", "salesperson", "nhân viên"])):
        return "geo"

    # 7. Nhận diện Đội ngũ / Chi nhánh / Team kinh doanh (pe.Team)
    is_team_col = any(k in ncol_low for k in ["team", "đội ngũ", "đội", "chinhanh", "chi nhánh", "branch"])
    is_team_query = any(k in q_low for k in ["team", "đội ngũ", "các đội", "từng đội", "chi nhánh", "branch", "giữa các team", "từng team", "các team"])

    is_team_values = False
    if df is not None and not df.empty and name_col and name_col in df.columns:
        sample_vals = [str(v).strip().lower() for v in df[name_col].dropna().head(10)]
        if any(v in ["delish", "jucies", "yummies"] for v in sample_vals):
            is_team_values = True

    if is_team_col or is_team_values or (is_team_query and not any(k in ncol_low for k in ["product", "sản phẩm", "sku", "geo", "country", "quốc gia", "salesperson", "nhân viên", "nhân sự"])):
        return "team"

    # 8. Nhận diện Sản phẩm / Hàng hóa
    is_prod_col = any(k in ncol_low for k in ["product", "sản phẩm", "category", "danh mục", "sku", "item", "hàng hóa", "pid", "mặt hàng"])
    is_prod_query = any(k in q_low for k in ["sản phẩm", "mặt hàng", "hàng hóa", "chocolate", "kẹo", "sku", "hộp", "thùng", "combo", "bao bì", "sản phẩm bán chạy"])
    is_prod_metric = any(k in cols_str for k in ["cost_per_box", "profit_per_box", "profitperbox"])
    if is_prod_col or is_prod_metric or is_prod_query:
        return "product"

    # Fallback cho CSDL thương mại: nếu có Amount / Boxes
    if any(k in cols_str for k in ["box", "hộp", "thùng", "product"]):
        return "product"

    return "general"


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

    val_col, name_col = select_primary_insight_columns(df, user_query=user_query)

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
    cols = df.columns.tolist()
    measure_cols, cat_cols, time_col_raw = get_axis_columns(df)
    cols_str = " ".join(str(c).lower() for c in cols)

    # 0.05 BÀI TOÁN THÂM NIÊN LÂU NHẤT / NHÂN SỰ KỲ CỰU (Longest-Tenured Veteran Employees)
    is_longest_tenure = (
        any(k in q_low for k in ["lâu nhất", "gắn bó lâu nhất", "thâm niên cao nhất", "thâm niên lớn nhất", "top thâm niên", "longest tenure", "highest tenure", "most tenured", "thâm niên làm việc lâu nhất"])
        or (
            any(k in q_low for k in ["thâm niên", "tenure", "gắn bó", "service", "năm"])
            and any(k in q_low for k in ["top", "cao nhất", "nhiều nhất", "lớn nhất", "dẫn đầu"])
            and not any(k in q_low for k in ["dưới", "ít hơn", "nhỏ hơn", "<", "mới vào", "mới gia nhập", "low tenure", "under 3", "under 5"])
            and not any(k in q_low for k in ["lương", "salary", "thu nhập", "tiền"])
        )
    ) or (
        any(k in str(val_col).lower() for k in ["yearsofservice", "service", "tenure", "thâm_niên", "thâm niên"])
        and not any(k in cols_str for k in ["salary", "currentsalary", "lương", "annualsalary"])
    )
    if is_longest_tenure:
        top_row_t = df.iloc[0] if not df.empty else None
        top_name_t = format_entity_label(top_row_t[name_col], col_name=name_col, lang="en" if is_en else "vi") if top_row_t is not None else ""
        top_v_t = float(pd.to_numeric(top_row_t[val_col], errors="coerce") or 0) if top_row_t is not None else 0
        if is_en:
            h1 = f"• **Organizational Retention Culture & Workplace Stability**: Exceptional tenure ({top_v_t:.2f} years for **{top_name_t}** and cohort peers) demonstrates strong organizational stability, effective long-term retention policies, and high employee loyalty."
            h2 = f"• **Preservation of Institutional Knowledge & Core Competencies**: Long-tenured personnel serve as vital anchors for institutional memory, operational standards, and deep enterprise knowledge."
        else:
            h1 = f"• **Văn hóa Gắn kết Doanh nghiệp & Môi trường Làm việc Ổn định**: Thâm niên cống hiến vượt bậc ({top_v_t:.2f} năm của nhân sự dẫn đầu **{top_name_t}** cùng toàn nhóm) khẳng định môi trường làm việc bền vững, chính sách giữ chân nhân tài hiệu quả và văn hóa tổ chức có độ gắn kết cao."
            h2 = f"• **Bảo tồn Tri thức Doanh nghiệp & Năng lực Cốt lõi**: Lực lượng nhân sự kỳ cựu đóng vai trò trụ cột trong việc lưu giữ bí quyết vận hành, chuẩn mực chất lượng và am hiểu sâu sắc quy trình nghiệp vụ nội bộ của tổ chức."
        return f"{h1}\n\n{h2}"

    # 0.1 BÀI TOÁN NHÂN SỰ NGOẠI LỆ: THÂM NIÊN THẤP NHƯNG LƯƠNG TOP % (Low Tenure & Top Percentile Outliers)
    has_valid_sal = any(k in cols_str for k in ["salary", "currentsalary", "lương", "annualsalary"])
    is_low_tenure_top_sal = (
        has_valid_sal
        and not is_longest_tenure
        and (
            (
                any(k in q_low for k in ["thâm niên", "gắn bó", "tenure", "năm"])
                and any(k in q_low for k in ["dưới", "ít hơn", "nhỏ hơn", "<", "under", "less than", "mới vào", "mới gia nhập"])
                and any(k in q_low for k in ["top", "cao nhất"])
                and any(k in q_low for k in ["%", "phần trăm", "percent", "lương", "salary", "thu nhập"])
            ) or (
                any(any(k in str(c).lower() for k in ["salarypercentile", "percentile", "bách phân vị"]) for c in df.columns)
                and any(any(k in str(c).lower() for k in ["yearsofservice", "thâm niên", "tenure"]) for c in df.columns)
            )
        )
    )
    if is_low_tenure_top_sal:
        top_row_sal = df.iloc[0] if not df.empty else None
        top_name_sal = str(top_row_sal.get(name_col, top_row_sal.get("FullName", top_row_sal.get("Họ và Tên", "Nhân sự dẫn đầu")))) if top_row_sal is not None else ""
        top_v_sal = float(pd.to_numeric(top_row_sal.get(val_col, top_row_sal.get("Salary", 0)), errors="coerce") or 0) if top_row_sal is not None else 0
        if top_v_sal > 0:
            if is_en:
                h1 = f"• **Lateral Senior Recruitment & High-Impact Talent Attraction**: Exceptional compensation ({format_metric_value(top_v_sal, val_col)}) observed in personnel with low tenure (<3 years) reflects strategic lateral hiring of seasoned industry specialists offering immediate execution power."
                h2 = f"• **Pay-for-Performance & Direct Commercial Contribution**: Concentration of top-percentile earners in frontline roles demonstrates direct linkage between compensation, quota overachievement, and tangible business output."
            else:
                h1 = f"• **Chiến lược Thu hút Nhân tài Cấp cao từ Thị trường (Lateral Senior Hiring)**: Mức thu nhập vượt bậc ({format_metric_value(top_v_sal, val_col)}) của nhóm nhân sự có thâm niên ngắn (<3 năm) phản ánh chính sách tuyển dụng nhân sự cấp cao từ thị trường với gói đãi ngộ cạnh tranh nhằm tạo đột phá nhanh chóng."
                h2 = f"• **Cơ chế Đãi ngộ Theo Năng lực Thực chiến (Pay-for-Performance)**: Sự hiện diện của nhóm nhân sự lương Top 5% tại khối Kinh doanh chứng minh cơ chế trả lương gắn chặt với hiệu quả đóng góp doanh số và năng lực mang lại giá trị thương mại tức thì."
            return f"{h1}\n\n{h2}"

    # 0.2 BÀI TOÁN TỶ LỆ ÉP LƯƠNG / NÉN LƯƠNG (Wage / Salary Compression)
    is_wage_compression = (
        any(k in q_low for k in ["ép lương", "áp lương", "nén lương", "compression", "wage compression", "salary compression"])
        or any(any(k in str(c).lower() for k in ["wagecompression", "compressionpct", "wage_compression"]) for c in df.columns)
    )
    if is_wage_compression:
        top_row_c = df.iloc[0] if not df.empty else None
        top_name_c = str(top_row_c.get(name_col, top_row_c.get("Department", "Phòng ban dẫn đầu"))) if top_row_c is not None else ""
        top_v_c = float(pd.to_numeric(top_row_c.get(val_col, 0), errors="coerce") or 0) if top_row_c is not None else 0
        if is_en:
            h1 = f"• **Entry-Level Clustering & Baseline Salary Density**: Department **{top_name_c}** exhibits the highest wage compression ({format_metric_value(top_v_c, val_col)}), driven by standardized operational roles clustered around the entry-level salary floor."
            h2 = f"• **Tenure-Based Pay Progression Bands**: Wider salary ranges in other departments reflect mature progression frameworks rewarding long-term specialist tenure and leadership accountability."
        else:
            h1 = f"• **Mật độ Bậc lương Khởi điểm & Quy chuẩn Hóa Chức năng**: Phòng ban **{top_name_c}** ghi nhận tỷ lệ nén lương cao nhất ({format_metric_value(top_v_c, val_col)}), xuất phát từ cơ cấu nhân sự tập trung lớn ở các bậc lương khởi điểm hoặc tính chất công việc có mức độ quy chuẩn hóa cao."
            h2 = f"• **Phân tầng Thu nhập Theo Thâm niên & Cấp bậc Quản lý**: Sự khác biệt về tỷ lệ nén giữa các phòng ban phản ánh chính sách giãn cách ngạch bậc lương theo mức độ đóng góp chuyên môn sâu và trách nhiệm quản trị."
        return f"{h1}\n\n{h2}"

    # 0.3 BÀI TOÁN LƯƠNG TRƯỞNG PHÒNG VS CẤP DƯỚI (Manager vs Subordinate Salary Comparison)
    is_mgr_sub_salary_comp = (
        any(k in q_low for k in ["trưởng phòng", "dept_manager", "manager", "quản lý", "quản lí"])
        and any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên", "toàn bộ nhân viên", "trực thuộc"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập", "gấp", "chênh lệch", "cao hơn", "thấp hơn", "so sánh"])
    ) or (
        any("managersalary" in str(c).lower() or "lương quản lý" in str(c).lower() for c in df.columns)
        and any("subordinate" in str(c).lower() or "cấp dưới" in str(c).lower() for c in df.columns)
    )
    if is_mgr_sub_salary_comp:
        if is_en:
            h1 = "• **Leadership Premium & Departmental Scale**: Managerial compensation differentials are strongest in commercial and revenue-driving units (Marketing, Sales), reflecting responsibility allowances tied to business KPIs and operational scope."
            h2 = "• **Tenure Compounding in Technical Roles (Inverted Pay)**: Parity or inverted salary ratios in Production and Customer Service stem from long-tenured senior specialists out-earning newly appointed operational managers."
        else:
            h1 = "• **Phụ cấp Trách nhiệm & Quy mô Điều hành (Leadership Premium)**: Mức thù lao Trưởng phòng cao vượt trội tập trung tại các khối kinh doanh và tăng trưởng (Marketing, Sales), phản ánh cơ chế đãi ngộ gắn liền với chỉ tiêu doanh thu và quy mô quản trị."
            h2 = "• **Tích lũy Thâm niên Chuyên gia Kỹ thuật (Hiện tượng Nghịch đảo Đãi ngộ)**: Hiện tượng lương Trưởng phòng tương đương hoặc thấp hơn cấp dưới tại các phòng ban vận hành (Production, Customer Service) bắt nguồn từ đội ngũ chuyên gia kỳ cựu có thâm niên 8-10 năm tích lũy bậc lương cao hơn so với quản lý mới được bổ nhiệm."
        return f"{h1}\n\n{h2}"

    # 1. NHẬN DIỆN CHUỖI THỜI GIAN (Time Series / Yearly Trend / Trend by Year / Monthly)
    time_col = find_time_column(df)
    is_time_series = (
        time_col is not None
        and not any(k in str(time_col).lower() for k in ["service", "tenure", "thâm niên", "tham_nien", "experience", "kinh nghiệm", "age", "tuoi"])
        and (
            any(k in q_low for k in ["qua các năm", "theo năm", "từng năm", "over time", "per year", "over the years", "yearly", "xu hướng", "trend", "biến động", "thay đổi như thế nào", "qua thời gian", "theo tháng", "từng tháng", "mỗi tháng", "hàng tháng", "theo quý", "từng quý"])
            or detect_analysis_entity_type(df, user_query=user_query) == "time_series"
        )
    )
    t_col = time_col

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
            peak_t = format_entity_label(peak_row[t_col], t_col, lang="en" if is_en else "vi")
            peak_v = float(peak_row[val_col])
            min_t = format_entity_label(min_row[t_col], t_col, lang="en" if is_en else "vi")
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
                        spike_t = format_entity_label(df_sorted.loc[max_jump_idx, t_col], t_col, lang="en" if is_en else "vi")
                        spike_pct = float(valid_pcts.loc[max_jump_idx])
                        spike_v = float(df_sorted.loc[max_jump_idx, val_col])

            mean_val = float(df_sorted[val_col].mean())

            is_payroll = any(k in q_low or k in cols_str for k in ["salary", "lương", "quỹ", "expenditure", "budget", "chi phí"])
            is_title_appointment = any(k in q_low or k in cols_str for k in ["appointment", "bổ nhiệm", "chức danh", "title", "newtitleappointments"])
            is_hiring = not is_title_appointment and any(k in q_low or k in cols_str for k in ["tuyển", "hire", "headcount", "nhân viên"])

            if is_en:
                if is_payroll:
                    h1 = f"• **Workforce Ramp-up & Budget Expansion in {spike_t}**: The significant jump of +{spike_pct:.1f}% (reaching {format_metric_value(spike_v, val_col)}) highlights aggressive hiring and corporate scaling during this period, establishing a larger baseline payroll expenditure."
                    h2 = f"• **Tenure Compounding & Budget Stabilization**: Total payroll peaked in {peak_t} ({format_metric_value(peak_v, val_col)}) and sustained around the mean of {format_metric_value(mean_val, val_col)}, driven by recurring merit increments for tenured talent paired with organizational salary caps."
                elif is_title_appointment:
                    h1 = f"• **Peak Organizational Restructuring & Title Promotion Wave ({spike_t})**: New title appointments surged to {peak_v:,.0f} promotions in {peak_t}, reflecting a major corporate restructuring, role reclassification, or accelerated internal mobility."
                    h2 = f"• **Career Path Stabilization & Succession Planning**: Post-peak title appointments normalized to {min_v:,.0f} promotions in {min_t} around an annual baseline of {mean_val:,.0f} promotions/year, indicating structured merit-based career progression rather than ad-hoc job title expansions."
                elif is_hiring:
                    h1 = f"• **Peak Recruitment Wave ({spike_t})**: New hiring surged to {peak_v:,.0f} employees in {peak_t}, aligning with corporate capacity expansion and critical project rollouts."
                    h2 = f"• **Headcount Stabilization & Selective Hiring**: Post-peak recruitment normalized to {min_v:,.0f} hires in {min_t} around a historical baseline of {mean_val:,.0f} hires/year, reflecting a strategic shift from rapid scaling to talent retention and internal productivity."
                else:
                    h1 = f"• **Growth Acceleration Phase ({spike_t})**: The performance surge of +{spike_pct:.1f}% to {format_metric_value(spike_v, val_col)} reflects synergistic execution of core strategic initiatives during this operational period."
                    h2 = f"• **Market Normalization & Operational Ceiling**: Trajectory from baseline {format_metric_value(min_v, val_col)} ({min_t}) to peak {format_metric_value(peak_v, val_col)} ({peak_t}) outlines typical industry demand cycles, settling around the mean of {format_metric_value(mean_val, val_col)}."
            else:
                if is_payroll:
                    h1 = f"• **Mở rộng Quy mô & Bước nhảy Ngân sách Giai đoạn {spike_t}**: Mức tăng vọt +{spike_pct:.1f}% (đạt {format_metric_value(spike_v, val_col)}) phản ánh giai đoạn doanh nghiệp ồ ạt mở rộng quy mô nhân sự hoặc sáp nhập các đơn vị lớn, tạo ra bước nhảy vọt về định biên chi phí lương."
                    h2 = f"• **Tích lũy Thâm niên & Cơ chế Trần Quỹ Lương**: Tổng quỹ lương đạt đỉnh vào năm {peak_t} ({format_metric_value(peak_v, val_col)}) và sau đó duy trì ổn định quanh mức trung bình {format_metric_value(mean_val, val_col)}, xuất phát từ chính sách tăng lương định kỳ tích lũy cho lực lượng nhân sự thâm niên kết hợp với việc kiểm soát trần ngân sách tổ chức."
                elif is_title_appointment:
                    h1 = f"• **Làn sóng Bổ nhiệm & Tái cơ cấu Chức danh Giai đoạn {spike_t}**: Số lượng nhân sự được bổ nhiệm chức danh mới đạt đỉnh {peak_v:,.0f} lượt vào năm {peak_t}, gắn liền với đợt chuẩn hóa chức danh, tái cơ cấu sơ đồ tổ chức hoặc luân chuyển cán bộ quy mô lớn."
                    h2 = f"• **Chuẩn hóa Lộ trình Thăng tiến & Ổn định Bộ máy**: Sau giai đoạn bổ nhiệm ồ ạt, hoạt động bổ nhiệm duy trì ổn định quanh mức bình quân {mean_val:,.0f} lượt/năm ({min_v:,.0f} lượt năm {min_t}), phản ánh quy trình đánh giá và thăng tiến chức danh đã đi vào nền nếp theo chu kỳ thẩm định định kỳ."
                elif is_hiring:
                    h1 = f"• **Làn sóng Tuyển dụng & Đột phá Quy mô ({spike_t})**: Số lượng nhân sự mới đạt đỉnh {peak_v:,.0f} người vào năm {peak_t}, gắn liền với giai đoạn mở rộng sản xuất kinh doanh và bổ sung nhân lực cho các dự án trọng điểm."
                    h2 = f"• **Tối ưu Định biên & Tinh gọn Bộ máy**: Sau giai đoạn cao điểm, quy mô tuyển dụng hạ nhiệt về {min_v:,.0f} nhân sự (năm {min_t}) và duy trì quanh mức bình quân {mean_val:,.0f} người/năm, phản ánh bước chuyển từ tuyển ồ ạt sang nâng cao chất lượng và ổn định đội ngũ."
                else:
                    h1 = f"• **Đột phá Tăng trưởng & Mở rộng Thị phần ({spike_t})**: Mức tăng trưởng +{spike_pct:.1f}% (đạt {format_metric_value(spike_v, val_col)}) chứng minh hiệu quả cộng hưởng từ các sáng kiến trọng tâm và mở rộng quy mô hoạt động trong giai đoạn này."
                    h2 = f"• **Chu kỳ Biến động & Ổn định Dài hạn**: Sự dịch chuyển từ mức sàn {format_metric_value(min_v, val_col)} ({min_t}) lên đỉnh {format_metric_value(peak_v, val_col)} ({peak_t}) phản ánh chu kỳ thị trường đặc thù, định hình mức nền tảng ổn định quanh giá trị trung bình {format_metric_value(mean_val, val_col)}."

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
    if not name_col:
        name_candidates = [c for c in cat_cols if c != val_col] or [c for c in cols if c != val_col]
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
            gap_vs_top = (spread_diff / top_v * 100) if top_v > 0 else 0
            lead_vs_bot = (spread_diff / bot_v * 100) if bot_v > 0 else 0
            is_single_or_tied = (len(df) == 1 or top_name == bot_name or spread_diff <= 0 or gap_vs_top < 0.01)

            # 3A1. Quản lý & Bình đẳng Giới trong Ban Quản lý / Trưởng phòng (Leadership Diversity & ESG Parity)
            is_mgr_diversity = (
                any(k in q_low for k in ["dept_manager", "manager", "quản lý", "trưởng phòng", "ban quản lý", "lãnh đạo"])
                or any("manager" in str(c).lower() for c in df.columns)
            ) and (
                any(k in cols_str for k in ["gender", "giới tính", "sex", "male", "female", "nam", "nữ"])
                or any(k in q_low for k in ["giới tính", "nam", "nữ", "gender", "male", "female"])
            )
            if is_mgr_diversity:
                if is_en:
                    h1 = f"• **Leadership Diversity & ESG Governance Parity**: Gender representation across departmental management cohorts ({top_name}: {format_metric_value(top_v, val_col)}) underscores enterprise governance alignment with modern ESG diversity benchmarks and meritocratic promotion pathways."
                    h2 = f"• **Historical Appointment Cycles & Succession Pipeline**: Differences across units reflect historical rotational appointment cycles and small managerial cohort sample sizes rather than systemic disparity, emphasizing the strategic value of a balanced leadership succession pipeline."
                else:
                    h1 = f"• **Cân bằng Bình đẳng Giới & Chuẩn mực Quản trị ESG (Leadership Diversity)**: Cơ cấu giới tính trong ban quản lý các phòng ban ({top_name}: {format_metric_value(top_v, val_col)}) phản ánh cam kết nhất quán của doanh nghiệp về bình đẳng cơ hội thăng tiến và phát triển nhân tài lãnh đạo dựa trên năng lực (Meritocracy)."
                    h2 = f"• **Đặc thù Quy mô Bổ nhiệm Lịch sử & Quy hoạch Kế thừa**: Sự phân bổ tại từng phòng ban bắt nguồn từ số lượng vị trí trưởng phòng hữu hạn qua các nhiệm kỳ lịch sử, khẳng định tầm quan trọng của việc xây dựng quy hoạch cán bộ nguồn (Succession Planning) bền vững."
                return f"{h1}\n\n{h2}"

            # 3A. Giới tính (Gender)
            is_gender = any(k in cols_str for k in ["gender", "giới tính", "sex"]) or any(k in q_low for k in ["giới tính", "nam", "nữ", "gender", "male", "female"])
            if is_gender:
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Job Family & Seniority Distribution**: The **{top_name}** group recorded at {format_metric_value(top_v, val_col)}, reflecting managerial tenure accumulation and specialist grade distribution."
                        h2 = f"• **Candidate Pipeline & Pay Equity Governance**: Reflects enterprise commitment to pay parity and career advancement governance."
                    else:
                        h1 = f"• **Cơ cấu Phân bổ Chức danh & Thâm niên Quản lý**: Nhóm **{top_name}** ghi nhận mức {format_metric_value(top_v, val_col)}, phản ánh tỷ lệ phân bổ các cấp bậc chuyên môn và số năm thâm niên tích lũy tại tổ chức."
                        h2 = f"• **Đặc thù Nguồn cung Ứng viên & Chính sách Bình đẳng**: Phản ánh cam kết của doanh nghiệp trong việc thúc đẩy công bằng cơ hội phát triển nghề nghiệp và đãi ngộ theo năng lực."
                    return f"{h1}\n\n{h2}"
                
                is_small_sample = (top_v <= 5 and float(top_v).is_integer()) or bot_v == 0
                if is_en:
                    gap_str = f"{format_metric_value(bot_v, val_col)} vs {format_metric_value(top_v, val_col)}" if is_small_sample else f"{format_metric_value(bot_v, val_col)}, {gap_vs_top:.1f}% lower than leader"
                    h1 = f"• **Job Family & Seniority Distribution**: The variance between **{top_name}** ({format_metric_value(top_v, val_col)}) and **{bot_name}** ({gap_str}) stems from historical tenure accumulation and specialist grade distribution."
                    h2 = f"• **Candidate Pipeline & Pay Equity Governance**: This distribution reflects external industry talent pools across specialized divisions and active enterprise governance around compensation parity."
                else:
                    gap_str = f"ở mức {format_metric_value(bot_v, val_col)} so với nhóm dẫn đầu {format_metric_value(top_v, val_col)}" if is_small_sample else f"thấp hơn {gap_vs_top:.1f}% so với nhóm dẫn đầu"
                    h1 = f"• **Cơ cấu Phân bổ Chức danh & Thâm niên Quản lý**: Chênh lệch giữa nhóm **{top_name}** ({format_metric_value(top_v, val_col)}) và nhóm **{bot_name}** ({format_metric_value(bot_v, val_col)}, {gap_str}) thường bắt nguồn từ tỷ lệ phân bổ các vị trí chuyên môn cao hoặc số năm thâm niên tích lũy tại tổ chức."
                    h2 = f"• **Đặc thù Nguồn cung Ứng viên & Chính sách Bình đẳng**: Tỷ lệ cơ cấu phản ánh nguồn cung ứng viên lịch sử trong từng chuyên ngành và cam kết của doanh nghiệp trong việc thúc đẩy công bằng cơ hội phát triển nghề nghiệp."
                return f"{h1}\n\n{h2}"

            # 3B. Chức danh (Titles / Roles)
            is_title = any(k in cols_str for k in ["title", "chức danh", "position"]) or any(k in q_low for k in ["chức danh", "vị trí", "title"])
            if is_title:
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Accountability Scope & Decision-Making Complexity**: Position **{top_name}** recorded at {format_metric_value(top_v, val_col)}, corresponding to specialized execution scope and decision-making complexity."
                        h2 = f"• **Merit Progression & Key Talent Retention**: Compensation benchmarks provide key financial incentives for career ladders and leadership retention."
                    else:
                        h1 = f"• **Phân cấp Trách nhiệm & Biên độ Quyết định Quản lý**: Vị trí **{top_name}** ghi nhận mức {format_metric_value(top_v, val_col)}, thể hiện mức độ rủi ro trách nhiệm cao và yêu cầu kinh nghiệm điều hành chuyên sâu."
                        h2 = f"• **Đòn bẩy Tài chính & Giữ chân Nhân sự Cốt lõi**: Mức thu nhập đóng vai trò đòn bẩy tài chính quan trọng để tạo động lực thăng tiến nội bộ và giữ chân nhân tài đầu ngành."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Accountability Scope & Decision-Making Complexity**: **{top_name}** ranks highest ({format_metric_value(top_v, val_col)}), corresponding to strategic decision risk and specialized leadership execution."
                    h2 = f"• **Merit Progression & Key Talent Retention**: The gap of {format_metric_value(spread_diff, val_col)} ({gap_vs_top:.1f}% lower than leader) against **{bot_name}** ({format_metric_value(bot_v, val_col)}) serves as a key financial incentive for career ladders and leadership retention."
                else:
                    h1 = f"• **Phân cấp Trách nhiệm & Biên độ Quyết định Quản lý**: Vị trí **{top_name}** dẫn đầu ({format_metric_value(top_v, val_col)}) thể hiện mức độ rủi ro trách nhiệm cao nhất và yêu cầu kinh nghiệm điều hành phức tạp."
                    h2 = f"• **Đòn bẩy Tài chính & Giữ chân Nhân sự Cốt lõi**: Biên độ thấp hơn {gap_vs_top:.1f}% ({format_metric_value(spread_diff, val_col)}) so với vị trí dẫn đầu (hoặc vị trí dẫn đầu vượt +{lead_vs_bot:.1f}% so với **{bot_name}** ở mức {format_metric_value(bot_v, val_col)}) là đòn bẩy tài chính quan trọng để tạo động lực thăng tiến nội bộ và giữ chân nhân tài đầu ngành."
                return f"{h1}\n\n{h2}"

            # 3C. Phòng ban (Departments)
            is_dept = (
                (any(k in cols_str for k in ["dept_name", "department_name", "phòng ban", "bộ phận"]) or any(k in q_low for k in ["phòng ban", "bộ phận"]))
                and not any(k in str(name_col).lower() for k in ["fullname", "full_name", "name", "tên", "họ và tên", "salesperson", "emp_no", "first_name", "last_name", "employee", "nhân sự", "nhân viên"])
                and not any(k in q_low for k in ["nhân viên", "nhân sự", "ai là", "top nhân viên", "thâm niên làm việc", "salesperson", "employee", "người"])
                and detect_analysis_entity_type(df, user_query=user_query, name_col=name_col) == "department"
            )
            if is_dept:
                if len(df) == 1:
                    if is_en:
                        h1 = f"• **Strategic Breadth & Functional Specialization**: **{top_name}** operates across highly varied job grades, causing a wide internal compensation spread between senior leads and operational staff."
                        h2 = f"• **Performance Incentive & Merit Progression**: The pay spread provides strong financial incentives for merit recognition and key talent retention in critical business workflows."
                    else:
                        h1 = f"• **Đa dạng Cấp bậc & Chuyên môn hóa Chức danh**: Phòng ban **{top_name}** tập hợp nhiều dải chức danh từ chuyên viên tác nghiệp đến chuyên gia cấp cao, tạo nên biên độ phân hóa thu nhập nội bộ sâu rộng."
                        h2 = f"• **Cơ chế Đãi ngộ Theo Hiệu suất & Giữ chân Nhân tài**: Khoảng cách thu nhập nội bộ là đòn bẩy tài chính quan trọng để thúc đẩy lộ trình thăng tiến và duy trì sự gắn bó của lực lượng nhân sự chủ chốt."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Strategic Contribution & Market Talent Competition**: **{top_name}** commands the top average ({format_metric_value(top_v, val_col)}), reflecting its direct impact on core value creation and strong competition in the external hiring market."
                    h2 = f"• **Seniority Ratio & Departmental Budget Framework**: The {gap_vs_top:.1f}% lower spread ({format_metric_value(spread_diff, val_col)}) compared to **{bot_name}** ({format_metric_value(bot_v, val_col)}) aligns with differing ratios of senior specialists and departmental operating caps."
                else:
                    h1 = f"• **Đóng góp Giá trị Cốt lõi & Tính Cạnh tranh Ngành nghề**: Phòng ban **{top_name}** đạt mức cao nhất ({format_metric_value(top_v, val_col)}), thể hiện vị thế đơn vị trọng yếu và tính chất cạnh tranh cao trong việc thu hút nhân lực giỏi trên thị trường lao động."
                    h2 = f"• **Cơ cấu Định biên Cấp bậc & Ngân sách Vận hành**: Mức thấp hơn {gap_vs_top:.1f}% ({format_metric_value(spread_diff, val_col)}) so với đơn vị dẫn đầu (hoặc đơn vị dẫn đầu vượt +{lead_vs_bot:.1f}% so với **{bot_name}** ở mức {format_metric_value(bot_v, val_col)}) phản ánh sự khác biệt về tỷ lệ nhân sự cao cấp (senior) và giới hạn trần ngân sách được phê duyệt giữa các đơn vị."
                return f"{h1}\n\n{h2}"

            # 3C1. Nhân sự / Nhân viên (Individual Employees / Salespeople)
            is_employee = (
                any(k in str(name_col).lower() for k in ["fullname", "full_name", "name", "tên", "họ và tên", "salesperson", "emp_no", "first_name", "last_name", "employee", "nhân sự", "nhân viên"])
                or any(k in q_low for k in ["nhân viên", "nhân sự", "ai là", "top nhân viên", "thâm niên làm việc", "salesperson", "employee", "người"])
                or detect_analysis_entity_type(df, user_query=user_query, name_col=name_col) == "employee"
            )
            if is_employee:
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Individual Performance & Role Specialization**: **{top_name}** leads at {format_metric_value(top_v, val_col)}, reflecting exceptional individual contribution and specialized competence."
                        h2 = f"• **Merit Alignment & Talent Retention**: Performance outcomes reinforce merit-based recognition and professional advancement."
                    else:
                        h1 = f"• **Năng lực Cá nhân & Hiệu quả Cống hiến Vượt bậc**: Nhân sự **{top_name}** dẫn đầu với mức {format_metric_value(top_v, val_col)}, thể hiện năng lực chuyên môn xuất sắc và hiệu quả đóng góp vượt trội."
                        h2 = f"• **Cơ chế Đãi ngộ Theo Năng lực & Động lực Phát triển**: Kết quả khẳng định chính sách ghi nhận minh bạch và tạo động lực phát triển bền vững cho nhân sự chủ chốt."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Top Performer Leadership & Work Output**: **{top_name}** leads the cohort ({format_metric_value(top_v, val_col)}), reflecting outstanding dedication and specialized execution capability."
                    h2 = f"• **Cohort Progression & Talent Balance**: The spread of {format_metric_value(spread_diff, val_col)} ({gap_vs_top:.1f}%) against **{bot_name}** ({format_metric_value(bot_v, val_col)}) provides clear performance benchmarks across the organizational cohort."
                else:
                    h1 = f"• **Vai trò Dẫn dắt & Đóng góp Của Nhân sự Xuất sắc**: Nhân sự **{top_name}** dẫn đầu toàn nhóm ({format_metric_value(top_v, val_col)}), thể hiện năng lực chuyên môn vững vàng và tinh thần trách nhiệm cao trong công việc."
                    h2 = f"• **Cân đối Năng lực & Chuẩn mực Đánh giá Nội bộ**: Biên độ chênh lệch {gap_vs_top:.1f}% ({format_metric_value(spread_diff, val_col)}) so với **{bot_name}** ({format_metric_value(bot_v, val_col)}) là cơ sở quan trọng để xây dựng chuẩn mực đánh giá và nhân rộng các điển hình tiên tiến trong tổ chức."
                return f"{h1}\n\n{h2}"

            # 3C2. Phân bổ nhân sự theo Team / Khu vực (Sales Team Headcount Distribution)
            is_team_headcount = (
                any(k in cols_str for k in ["team", "đội ngũ", "location", "khu vực"])
                and any(k in cols_str for k in ["số lượng nhân viên", "slngnhnvin", "headcount", "totalemployees", "nhân sự", "nhân viên"])
            ) or (
                any(k in q_low for k in ["nhân viên", "nhân sự", "headcount", "salesperson"])
                and any(k in q_low for k in ["team", "đội ngũ", "phân bổ", "đội"])
            )
            if is_team_headcount:
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Salesforce Distribution & Team Scale**: **{top_name}** maintains {format_metric_value(top_v, val_col)} personnel, establishing dedicated operational capacity."
                        h2 = f"• **Workforce Allocation**: Staffing levels are aligned with current territorial account workload and operational targets."
                    else:
                        h1 = f"• **Quy mô Lực lượng & Năng lực Bao phủ**: Đội ngũ **{top_name}** sở hữu quy mô {format_metric_value(top_v, val_col)} nhân sự, bảo đảm năng lực vận hành và bao phủ mạng lưới khách hàng trọng yếu."
                        h2 = f"• **Định biên Vận hành & Phân bổ Mục tiêu**: Quy mô nhân lực phù hợp với kế hoạch phân bổ hạn ngạch doanh số và dung lượng thị trường mục tiêu."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Salesforce Distribution & Team Scale**: **{top_name}** maintains the largest headcount with {format_metric_value(top_v, val_col)} sales professionals, positioning it as the primary frontline team driving account coverage."
                    h2 = f"• **Workforce Allocation & Onboarding Gap**: The spread against **{bot_name}** ({format_metric_value(bot_v, val_col)} reps) outlines differing regional workload demands and highlights an opportunity to reassign unallocated personnel to high-growth squads."
                else:
                    h1 = f"• **Quy mô Lực lượng & Phân bổ Đội ngũ Kinh doanh**: Đội ngũ **{top_name}** sở hữu quy mô nhân sự lớn nhất với {format_metric_value(top_v, val_col)} nhân viên kinh doanh, đóng vai trò mũi nhọn chủ lực phụ trách mạng lưới khách hàng trọng yếu."
                    h2 = f"• **Cân đối Định biên & Chuẩn hóa Phân bổ Nhóm**: Khoảng cách so với nhóm **{bot_name}** ({format_metric_value(bot_v, val_col)} nhân sự) phản ánh sự phân bố theo quy mô thị trường mục tiêu, đồng thời mở ra cơ hội rà soát và phân nhóm rõ ràng cho các nhân viên chưa được xếp đội để tối ưu hóa năng suất bán hàng."
                return f"{h1}\n\n{h2}"

            # 3D1. Phân tích Pareto 80/20 & Tích lũy dồn (Pareto 80/20 Analysis)
            is_pareto = (
                any(k in q_low for k in ["pareto", "80/20", "80-20", "tích lũy", "tích luỹ", "cumulative"])
                or any(k in cols_str for k in ["cumulative", "tích lũy", "runningtotal", "cumulativepercent", "cumpct"])
            )
            if is_pareto:
                cum_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["cumulative", "tích lũy", "running"])), None)
                pct_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["percentage", "percent", "pct", "tỷ lệ", "tỉ lệ", "share"]) and not any(k in str(c).lower() for k in ["cumulative", "tích lũy", "running"])), None)
                sales_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["totalsales", "total_sales", "sales", "revenue", "amount", "boxes", "doanh thu", "doanh so"])), None) or val_col

                top_pct_val = f"{float(top_r[pct_col]):.2f}%" if (pct_col and pct_col in top_r and pd.notna(top_r[pct_col])) else ""
                bot_pct_val = f"{float(bot_r[pct_col]):.2f}%" if (pct_col and pct_col in bot_r and pd.notna(bot_r[pct_col])) else ""
                cum_total_val = f"{float(bot_r[cum_col]):.2f}%" if (cum_col and cum_col in bot_r and pd.notna(bot_r[cum_col])) else "80%"
                n_items = len(df)

                top_sales_str = format_metric_value(top_v, sales_col)
                bot_sales_str = format_metric_value(bot_v, sales_col)

                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Core Revenue Anchor & Category Demand**: **{top_name}** commands the primary contribution ({top_sales_str}{f', {top_pct_val}' if top_pct_val else ''}), driven by strong consumer adoption."
                        h2 = f"• **Portfolio Focus**: Demonstrates strong performance concentration in key strategic SKUs."
                    else:
                        h1 = f"• **Trọng tâm Đóng góp Doanh số & Sức hút Thị trường**: Sản phẩm **{top_name}** ({top_sales_str}{f', {top_pct_val}' if top_pct_val else ''}) giữ vai trò chủ lực nhờ thị hiếu người tiêu dùng ưa chuộng."
                        h2 = f"• **Cơ cấu Doanh thu Trụ cột**: Khẳng định vai trò dẫn dắt doanh thu danh mục và sức hút thương hiệu bền vững."
                    return f"{h1}\n\n{h2}"

                if is_en:
                    h1 = f"• **Core Revenue Anchor & Category Demand**: **{top_name}** commands the #1 contribution ({top_sales_str}{f', {top_pct_val}' if top_pct_val else ''}), driven by widespread consumer taste adoption and consistent retail shelf placement."
                    h2 = f"• **Portfolio Spread & Risk Diversification (Pareto 80/20)**: Top {n_items} key products collectively generate {cum_total_val} of total company sales; the balanced individual share from **{top_name}** ({top_pct_val}) to **{bot_name}** ({bot_pct_val}) demonstrates a resilient, well-distributed revenue foundation across core SKUs."
                else:
                    h1 = f"• **Trọng tâm Đóng góp Doanh số & Sức hút Thị trường**: Sản phẩm **{top_name}** ({top_sales_str}{f', {top_pct_val}' if top_pct_val else ''}) dẫn đầu doanh thu nhờ thị hiếu người tiêu dùng ưa chuộng và độ phủ kênh bán lẻ vượt trội."
                    h2 = f"• **Cơ cấu Doanh thu Nhóm Trụ cột & Phân tán Rủi ro (Pareto 80/20)**: Danh mục {n_items} sản phẩm trọng điểm đóng góp {cum_total_val} tổng doanh số toàn công ty; khoảng cách tỷ trọng cá nhân từ **{top_name}** ({top_pct_val}) đến **{bot_name}** ({bot_pct_val}) cho thấy cơ cấu doanh thu khá đồng đều, giảm thiểu rủi ro phụ thuộc vào một SKU đơn lẻ."
                return f"{h1}\n\n{h2}"

            # 3D2. Tỷ lệ đóng góp / Cơ cấu tỷ trọng (Contribution / Ratio / Share)
            is_contribution = any(k in q_low for k in ["tỉ lệ", "tỷ lệ", "tỉ trọng", "tỷ trọng", "phần trăm", "cơ cấu", "đóng góp", "share", "ratio"])
            if is_contribution:
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Core Revenue Anchor & Contribution Share**: Group **{top_name}** accounts for the primary revenue stream, serving as the strategic growth pillar across business operations."
                        h2 = f"• **Portfolio Focus**: Reflects consistent commercial execution and market focus."
                    else:
                        h1 = f"• **Trọng tâm Đóng góp Doanh thu & Vị thế Trụ cột**: Nhóm **{top_name}** nắm giữ tỷ trọng đóng góp chủ lực, đóng vai trò đầu tàu dẫn dắt dòng tiền toàn hệ thống."
                        h2 = f"• **Tập trung Nguồn lực Chiến lược**: Phản ánh sự tập trung nguồn lực hiệu quả vào phân khúc kinh doanh cốt lõi."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Core Revenue Anchor & Portfolio Dominance**: **{top_name}** accounts for the primary revenue stream, serving as the strategic growth pillar across business operations."
                    h2 = f"• **Channel Diversification & Secondary Growth Levers**: The contribution variance highlights an opportunity to cross-sell and elevate **{bot_name}** to reduce single-segment dependency."
                else:
                    h1 = f"• **Trọng tâm Đóng góp Doanh thu & Vị thế Trụ cột**: Nhóm **{top_name}** nắm giữ tỷ trọng đóng góp chủ lực, đóng vai trò đầu tàu dẫn dắt dòng tiền và tăng trưởng quy mô toàn hệ thống."
                    h2 = f"• **Đa dạng hóa Danh mục & Khai phóng Tiềm năng Tăng trưởng**: Khoảng cách tỷ trọng so với nhóm **{bot_name}** cho thấy dư địa lớn để mở rộng chiến dịch xúc tiến bán chéo, giảm thiểu rủi ro phụ thuộc vào một phân khúc đơn lẻ."
                return f"{h1}\n\n{h2}"

            # 3E1. Tỷ suất Lợi nhuận / Biên lợi nhuận (Profit Margin / Margin % - Focus on COGS & Pricing Strategy)
            is_margin = (
                any(k in str(val_col).lower() for k in ["margin", "tỷ suất", "tỉ suất", "profit_margin", "profitmargin", "gross_margin", "grossmargin"])
                or (
                    any(k in q_low for k in ["tỷ suất lợi nhuận", "tỉ suất lợi nhuận", "biên lợi nhuận", "profit margin", "gross margin"])
                    and not any(k in q_low for k in ["doanh thu", "doanh số", "sales", "revenue", "hộp", "boxes", "nhân viên", "nhân sự", "lương"])
                    and not is_pareto
                )
            )
            if is_margin:
                cash_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["profitperbox", "profit_per_box", "profit", "lợi nhuận", "lãi"]) 
                                 and not any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất", "%"]) 
                                 and pd.api.types.is_numeric_dtype(df[c])), None)
                cash_top_name = None
                cash_top_val = None
                cash_top_margin = None
                if cash_col:
                    try:
                        clean_cash = pd.to_numeric(df[cash_col], errors="coerce").dropna()
                        if not clean_cash.empty:
                            top_c_idx = clean_cash.idxmax()
                            cash_top_name = format_entity_label(df.loc[top_c_idx, name_col])
                            cash_top_val = float(df.loc[top_c_idx, cash_col])
                            cash_top_margin = float(df.loc[top_c_idx, val_col])
                    except Exception:
                        pass

                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **COGS Structure & Cost Advantage**: The gross margin of **{top_name}** ({format_metric_value(top_v, val_col)}) reflects an optimized cost of goods sold (COGS) per unit relative to selling price."
                        h2 = f"• **Pricing Discipline & Margin Protection**: Demonstrates robust pricing discipline and strong category margin resilience."
                    else:
                        h1 = f"• **Cấu trúc Chi phí Vốn (COGS) & Lợi thế Biên Lợi nhuận**: Tỷ suất lợi nhuận của **{top_name}** ({format_metric_value(top_v, val_col)}) bắt nguồn từ cấu trúc giá vốn hàng bán (COGS) được tối ưu hóa so với đơn giá niêm yết."
                        h2 = f"• **Kỷ luật Định giá & Bảo vệ Biên An toàn**: Phản ánh kỷ luật định giá vững chắc và biên an toàn tài chính cao của danh mục sản phẩm."
                    return f"{h1}\n\n{h2}"

                if is_en:
                    h1 = f"• **COGS Structure & Cost Advantage**: The superior gross margin of **{top_name}** ({format_metric_value(top_v, val_col)}) reflects an exceptionally lean manufacturing cost of goods sold (COGS) per unit relative to selling price—representing a structural cost efficiency rather than consumer popularity or promotional pull."
                    if cash_top_name and cash_top_name != top_name:
                        h2 = f"• **Value Capture & Premium Cash Engine**: While **{top_name}** maximizes percentage margin, **{cash_top_name}** generates the highest absolute net cash profit ({format_metric_value(cash_top_val, cash_col)}/box at {cash_top_margin:.2f}% margin), successfully capturing premium customer segments with strong willingness to pay."
                    else:
                        h2 = f"• **Pricing Discipline & Margin Protection**: The strong spread above {bot_name} ({format_metric_value(bot_v, val_col)}) demonstrates robust pricing discipline and limited promotional discounting across top product tiers."
                else:
                    h1 = f"• **Cấu trúc Chi phí Vốn (COGS) & Lợi thế Biên Lợi nhuận**: Tỷ suất lợi nhuận vượt trội của **{top_name}** ({format_metric_value(top_v, val_col)}) bắt nguồn từ cấu trúc giá vốn hàng bán (COGS) trên mỗi hộp cực thấp so với đơn giá niêm yết, phản ánh ưu thế tối ưu hóa chi phí sản xuất thay vì thị hiếu người tiêu dùng hay tác động từ khuyến mãi."
                    if cash_top_name and cash_top_name != top_name:
                        h2 = f"• **Định vị Giá trị & Cỗ máy Tạo Tiền Mặt Ròng (Value Capture)**: Trong khi **{top_name}** tối ưu hóa tỷ lệ %, thì **{cash_top_name}** lại là mặt hàng mang về số tiền lời tuyệt đối lớn nhất ({format_metric_value(cash_top_val, cash_col)}/hộp với tỷ suất {cash_top_margin:.2f}%), khai thác hiệu quả phân khúc khách hàng cao cấp sẵn sàng chi trả mức giá cao."
                    else:
                        h2 = f"• **Kỷ luật Định giá & Bảo vệ Biên An toàn**: Khoảng cách so với **{bot_name}** ({format_metric_value(bot_v, val_col)}) cho thấy sự phân hóa về tỷ lệ chiết khấu thương mại và định mức chi phí nguyên vật liệu đầu vào giữa các dòng sản phẩm."
                return f"{h1}\n\n{h2}"

            # 3E1.5. Thị trường / Quốc gia (Geo / Country / Market), Đội ngũ kinh doanh (Sales Teams), hoặc Nhân sự (Salesperson)
            detected_ent = detect_analysis_entity_type(df, user_query=user_query, name_col=name_col)
            if detected_ent == "geo":
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Market Scale & Local Purchasing Power**: Market **{top_name}** commands sales volume of {format_metric_value(top_v, val_col)}, driven by solid consumer demand and local purchasing power."
                        h2 = f"• **Distribution Infrastructure**: Reflects active retail distribution partnerships and established regional logistics operations."
                    else:
                        h1 = f"• **Quy mô Thị trường & Sức mua Địa phương**: Thị trường **{top_name}** đạt quy mô doanh thu {format_metric_value(top_v, val_col)}, nhờ sức mua ổn định và sự đón nhận tích cực của người tiêu dùng bản địa."
                        h2 = f"• **Độ Phủ Mạng lưới Phân phối & Hiệu quả Kênh**: Phản ánh năng lực khai thác của hệ thống phân phối và các chuỗi đối tác bán lẻ địa phương."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Market Scale & Local Purchasing Power**: Market **{top_name}** commands the leading sales output ({format_metric_value(top_v, val_col)}), driven by high per-capita purchasing power and strong consumer affinity for chocolate confectionery."
                    h2 = f"• **Distribution Network & Market Penetration**: The {gap_vs_top:.1f}% variance against **{bot_name}** ({format_metric_value(bot_v, val_col)}) stems from differences in local retail network maturity, import-export logistics lead times, and consumer taste preferences, highlighting significant market penetration headroom in **{bot_name}**."
                else:
                    h1 = f"• **Quy mô Thị trường & Sức mua Địa phương**: Thị trường **{top_name}** giữ quy mô doanh thu dẫn đầu ({format_metric_value(top_v, val_col)}), nhờ sức mua bình quân đầu người cao và mức độ ưa chuộng sô-cô-la vượt trội của người tiêu dùng bản địa."
                    h2 = f"• **Độ Phủ Mạng lưới Phân phối & Rào cản Thâm nhập**: Khoảng cách {gap_vs_top:.1f}% so với thị trường **{bot_name}** ({format_metric_value(bot_v, val_col)}) phản ánh sự phân hóa về độ bao phủ kênh bán lẻ hiện đại (Modern Trade), hạ tầng logistics chuỗi lạnh và khẩu vị tiêu dùng địa phương, mở ra dư địa mở rộng thị phần lớn tại **{bot_name}**."
                return f"{h1}\n\n{h2}"
            elif detected_ent == "team":
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Sales Execution & Account Coverage**: Team **{top_name}** achieved {format_metric_value(top_v, val_col)}, driven by disciplined commercial execution and pipeline conversion."
                        h2 = f"• **Territory Management**: Reflects focused account management and effective sales process discipline."
                    else:
                        h1 = f"• **Năng lực Bán hàng & Khai thác Địa bàn**: Đội ngũ **{top_name}** đạt doanh số {format_metric_value(top_v, val_col)}, khẳng định kỷ luật thực thi kinh doanh và khả năng bao phủ khách hàng hiệu quả."
                        h2 = f"• **Quản trị Khách hàng & Kỷ luật Đội ngũ**: Phản ánh sự tập trung khai thác danh mục khách hàng trọng điểm và duy trì nhịp độ bán hàng ổn định."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Sales Execution & Account Coverage**: Team **{top_name}** commands the leading sales output ({format_metric_value(top_v, val_col)}), driven by high frontline conversion discipline and superior commercial execution."
                    h2 = f"• **Territory Potential & Capability Dispersion**: The {gap_vs_top:.1f}% variance against **{bot_name}** ({format_metric_value(bot_v, val_col)}) stems from uneven territory account density and tenure gaps, creating an immediate opportunity for best-practice replication."
                else:
                    h1 = f"• **Năng lực Bán hàng & Khai thác Địa bàn**: Đội ngũ **{top_name}** đạt doanh số dẫn đầu ({format_metric_value(top_v, val_col)}), khẳng định kỷ luật thực thi kinh doanh vượt trội, kỹ năng chốt hợp đồng sắc bén và khả năng bao phủ khách hàng hiệu quả."
                    h2 = f"• **Quy mô Thị trường & Dư địa Chuẩn hóa Năng lực**: Khoảng cách {gap_vs_top:.1f}% so với đội ngũ **{bot_name}** ({format_metric_value(bot_v, val_col)}) phản ánh sự phân hóa về tiềm năng khách hàng trên địa bàn phụ trách và độ đồng đều kinh nghiệm của nhân sự, mở ra cơ hội nhân rộng phương pháp từ đội ngũ dẫn đầu."
                return f"{h1}\n\n{h2}"
            elif detected_ent == "employee":
                is_salesperson_query = any(k in cols_str for k in ["sales", "amount", "boxes", "doanh số", "doanh thu", "hộp"]) or any(k in q_low for k in ["doanh số", "doanh thu", "bán hàng", "sales", "hộp"])
                if is_salesperson_query:
                    if is_single_or_tied:
                        if is_en:
                            h1 = f"• **Consultative Selling & Deal Conversion**: Sales representative **{top_name}** achieved {format_metric_value(top_v, val_col)}, reflecting consultative selling skills and disciplined deal closing."
                            h2 = f"• **Role Impact & Client Relationship**: Reflects strong relationship management and high customer satisfaction."
                        else:
                            h1 = f"• **Kỹ năng Bán hàng & Khai thác Khách hàng Trọng điểm**: Nhân sự **{top_name}** đạt doanh số {format_metric_value(top_v, val_col)}, thể hiện kỹ năng tư vấn giải pháp sắc bén và kỷ luật chốt đơn hàng hiệu quả."
                            h2 = f"• **Đóng góp Trọng yếu & Gắn kết Khách hàng**: Phản ánh sự tận tâm trong công tác chăm sóc đối tác và duy trì giá trị hợp đồng bền vững."
                        return f"{h1}\n\n{h2}"
                    if is_en:
                        h1 = f"• **Consultative Selling & High-Value Account Conversion**: Sales representative **{top_name}** leads performance ({format_metric_value(top_v, val_col)}), reflecting exceptional key-account management, consultative selling skills, and disciplined deal closing."
                        h2 = f"• **Territory Density & Peer Coaching Opportunities**: The {gap_vs_top:.1f}% variance compared to sales representative **{bot_name}** ({format_metric_value(bot_v, val_col)}) highlights differences in account portfolio maturity and sales tenure, creating a high-impact opportunity for peer coaching and best-practice sharing across the sales team."
                    else:
                        h1 = f"• **Kỹ năng Bán hàng & Khai thác Khách hàng Trọng điểm**: Nhân sự **{top_name}** đạt doanh số dẫn đầu ({format_metric_value(top_v, val_col)}), thể hiện kỹ năng tư vấn giải pháp sắc bén, khả năng duy trì quan hệ đối tác bền vững và kỷ luật chốt đơn hàng giá trị cao."
                        h2 = f"• **Độ Chín Danh mục Khách hàng & Dư địa Kèm cặp Nội bộ**: Khoảng cách {gap_vs_top:.1f}% so với nhân sự **{bot_name}** ({format_metric_value(bot_v, val_col)}) phản ánh sự phân hóa về độ bao phủ tệp khách hàng tiềm năng và kinh nghiệm thực chiến, mở ra cơ hội đẩy mạnh chuyển giao kỹ năng và kèm cặp nội bộ (peer coaching) để nâng cao đồng đều năng suất đội ngũ."
                else:
                    if is_single_or_tied:
                        if is_en:
                            h1 = f"• **Individual Performance & Role Value**: Personnel **{top_name}** recorded at {format_metric_value(top_v, val_col)}, reflecting specialized capabilities and strategic role impact."
                            h2 = f"• **Progression Framework**: Compensation reflects experience maturity and established performance bands."
                        else:
                            h1 = f"• **Hiệu quả Cá nhân & Đóng góp Chuyên môn**: Nhân sự **{top_name}** đạt mức {format_metric_value(top_v, val_col)}, thể hiện năng lực chuyên môn và đóng góp trọng yếu vào mục tiêu tổ chức."
                            h2 = f"• **Khung Lộ trình Đãi ngộ**: Mức thu nhập phản ánh sự phân tầng theo thâm niên và đóng vai trò đòn bẩy phát triển năng lực."
                        return f"{h1}\n\n{h2}"
                    if is_en:
                        h1 = f"• **Individual Performance & Role Value**: Personnel **{top_name}** achieves the highest benchmark ({format_metric_value(top_v, val_col)}), reflecting specialized capabilities and strategic role impact."
                        h2 = f"• **Compensation Spread & Progression Incentive**: The variance compared to **{bot_name}** ({format_metric_value(bot_v, val_col)}, {gap_vs_top:.1f}% lower than leader) aligns with experience maturity and performance-driven progression bands."
                    else:
                        h1 = f"• **Hiệu quả Cá nhân & Đóng góp Chuyên môn**: Nhân sự **{top_name}** đạt mức cao nhất ({format_metric_value(top_v, val_col)}), thể hiện năng lực chuyên môn vượt trội và đóng góp trọng yếu vào mục tiêu tổ chức."
                        h2 = f"• **Biên độ Phân hóa & Động lực Phát triển Nghề nghiệp**: Khoảng cách {gap_vs_top:.1f}% so với nhân sự **{bot_name}** ({format_metric_value(bot_v, val_col)}) phản ánh sự phân tầng theo mức độ thâm niên và đóng vai trò đòn bẩy tài chính tạo động lực phát triển năng lực cá nhân."
                return f"{h1}\n\n{h2}"

            # 3E2. Doanh số / Sản lượng / Bán hàng (Sales Volume / Revenue / Boxes - KHÔNG PHẢI MARGIN)
            is_sales = any(k in cols_str for k in ["product", "sản phẩm", "amount", "revenue", "boxes", "quốc gia", "country", "rep"]) or any(k in q_low for k in ["sản phẩm", "chocolate", "doanh thu", "bán chạy", "sales"])
            if is_sales:
                ent_lbl_en = "Product" if detected_ent == "product" else ("Sales representative" if detected_ent == "employee" else ("Market" if detected_ent == "geo" else "Team"))
                ent_lbl_vi = "Sản phẩm" if detected_ent == "product" else ("Nhân sự" if detected_ent == "employee" else ("Thị trường" if detected_ent == "geo" else "Đội ngũ"))
                if is_single_or_tied:
                    if is_en:
                        h1 = f"• **Consumer Preference & Market Demand**: {ent_lbl_en} **{top_name}** generated {format_metric_value(top_v, val_col)}, proving healthy market demand and consumer adoption."
                        h2 = f"• **Channel Execution**: Reflects solid shelf placement and consistent promotional execution across retail points."
                    else:
                        h1 = f"• **Thị hiếu Tiêu dùng & Sức Hút Thị trường**: {ent_lbl_vi} **{top_name}** đạt quy mô tiêu thụ {format_metric_value(top_v, val_col)}, chứng minh sự ưa chuộng và đón nhận tích cực từ thị trường."
                        h2 = f"• **Độ Phủ Phân phối & Hiệu quả Kênh**: Phản ánh sự bao phủ tốt trên các điểm bán và chính sách thương mại hiệu quả."
                    return f"{h1}\n\n{h2}"
                if is_en:
                    h1 = f"• **Consumer Preference & Market Demand**: {ent_lbl_en} **{top_name}** commands the leading sales volume ({format_metric_value(top_v, val_col)}), proving superior consumer adoption and strong frontline retail pull."
                    h2 = f"• **Distribution Penetration & Channel Variance**: Standing {gap_vs_top:.1f}% lower than market leader reflects varying channel distribution intensity, highlighting an opportunity to expand into secondary retail touchpoints."
                else:
                    h1 = f"• **Thị hiếu Tiêu dùng & Sức Hút Thị trường**: {ent_lbl_vi} **{top_name}** đạt quy mô tiêu thụ dẫn đầu ({format_metric_value(top_v, val_col)}), chứng minh sức hút mạnh mẽ và mức độ chấp nhận cao của người tiêu dùng đối với dòng sản phẩm này."
                    h2 = f"• **Độ Phủ Phân phối & Tiềm năng Kênh Thứ cấp**: Mức chênh lệch {gap_vs_top:.1f}% so với đơn vị dẫn đầu phản ánh độ thâm nhập kênh phân phối chưa đồng đều, mở ra dư địa thúc đẩy độ phủ tại các đại lý và điểm bán lẻ thứ cấp."
                return f"{h1}\n\n{h2}"

            # 3F. General Ranking
            ent_pfx_en = "Sales representative" if detected_ent == "employee" else ("Product" if detected_ent == "product" else ("Market" if detected_ent == "geo" else ("Team" if detected_ent == "team" else "Unit")))
            ent_pfx_vi = "Nhân sự" if detected_ent == "employee" else ("Sản phẩm" if detected_ent == "product" else ("Thị trường" if detected_ent == "geo" else ("Đội ngũ" if detected_ent == "team" else "Đơn vị")))
            if is_single_or_tied:
                if is_en:
                    h1 = f"• **Operational Focus & Capacity**: {ent_pfx_en} **{top_name}** recorded {format_metric_value(top_v, val_col)}, demonstrating dedicated execution capacity."
                    h2 = f"• **Governance & Alignment**: Reflects aligned operating plans and consistent resource dedication."
                else:
                    h1 = f"• **Trọng tâm Vận hành & Năng lực Thực thi**: {ent_pfx_vi} **{top_name}** đạt mức {format_metric_value(top_v, val_col)}, phản ánh năng lực vận hành và sự tập trung nguồn lực hiệu quả."
                    h2 = f"• **Kế hoạch Quản trị & Định hướng Vận hành**: Thể hiện sự nhất quán trong việc thực thi các mục tiêu đã đề ra theo kế hoạch."
                return f"{h1}\n\n{h2}"
            if is_en:
                h1 = f"• **Operational Leadership & Execution Focus**: {ent_pfx_en} **{top_name}** achieves the highest benchmark ({format_metric_value(top_v, val_col)}), demonstrating superior operational capacity and resource dedication."
                h2 = f"• **Performance Variance & Optimization Window**: Standing {gap_vs_top:.1f}% lower than leader (variance of -{format_metric_value(spread_diff, val_col)}; leader exceeds {ent_pfx_en.lower()} **{bot_name}** at {format_metric_value(bot_v, val_col)} by +{lead_vs_bot:.1f}%) highlights an operational optimization window to narrow performance dispersion across units."
            else:
                h1 = f"• **Vị thế Dẫn đầu & Hiệu quả Thực thi**: {ent_pfx_vi} **{top_name}** đạt mức cao nhất ({format_metric_value(top_v, val_col)}), phản ánh năng lực vận hành vượt trội và sự tập trung nguồn lực mạnh mẽ."
                h2 = f"• **Biên độ Phân hóa & Tiềm năng Tối ưu**: Khoảng cách thấp hơn {gap_vs_top:.1f}% ({format_metric_value(spread_diff, val_col)}) so với đơn vị dẫn đầu (hoặc đơn vị dẫn đầu vượt +{lead_vs_bot:.1f}% so với {ent_pfx_vi.lower()} **{bot_name}** ở mức {format_metric_value(bot_v, val_col)}) mở ra cơ hội chuẩn hóa quy trình và thu hẹp khoảng cách hiệu quả giữa các cá nhân/đơn vị."
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


def generate_data_grounded_action_plan(df: pd.DataFrame, is_en: bool = False, user_query: str = "") -> str:
    """Tự động sinh Đề xuất Chiến lược AI phân cấp 3 bậc (Cấp bách, Trung hạn, Dài hạn) bám chặt vào số liệu thực tế từ DataFrame
    và ĐÚNG BẢN CHẤT ĐỐI TƯỢNG (Sản phẩm vs Đội ngũ/Team vs Nhân sự/Phòng ban):
    1. Sản phẩm/Hàng hóa: Combo, định giá, tồn kho/xả hàng, bao bì.
    2. Đội ngũ/Chi nhánh/Team: Cơ chế hoa hồng (Incentive), đào tạo kỹ năng bán hàng, chia lại địa bàn (Territory planning), học hỏi best-practice. TUYỆT ĐỐI KHÔNG dùng từ xả hàng, hết hạn sử dụng, combo.
    3. Nhân sự/Phòng ban: Chính sách lương thưởng, lộ trình thăng tiến, tuyển dụng. TUYỆT ĐỐI KHÔNG dùng từ xả hàng, hết hạn sử dụng, combo.
    """
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

    val_col, name_col = select_primary_insight_columns(df, user_query=user_query)
    if not val_col or not name_col:
        cols = df.columns.tolist()
        num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
        cat_cols = [c for c in cols if c not in num_cols]
        val_col = val_col or (num_cols[0] if num_cols else None)
        name_col = name_col or (cat_cols[0] if cat_cols else (num_cols[1] if len(num_cols) > 1 else None))

    if not val_col or not name_col:
        return (
            "• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Thiết lập cơ chế kiểm soát tức thời và ngăn ngừa rủi ro dữ liệu sai lệch.\n\n"
            "• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa hệ thống báo cáo và liên kết chỉ tiêu KPI với hiệu quả thực tế.\n\n"
            "• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Đầu tư mở rộng danh mục chiến lược và xây dựng hệ thống quản trị chủ động."
        )

    sorted_df = df.sort_values(by=val_col, ascending=False)
    top_row = sorted_df.iloc[0]
    bot_row = sorted_df.iloc[-1]
    top_name = format_entity_label(top_row[name_col], col_name=name_col, lang="en" if is_en else "vi")
    top_val = top_row[val_col]
    bot_name = format_entity_label(bot_row[name_col], col_name=name_col, lang="en" if is_en else "vi")
    bot_val = bot_row[val_col]

    mean_val = df[val_col].mean()
    median_val = df[val_col].median()
    diff = top_val - bot_val
    gap_vs_top = (diff / top_val * 100) if top_val != 0 else 0
    lead_vs_bot = (diff / bot_val * 100) if bot_val != 0 else 0
    is_single_or_tied = (len(df) == 1 or top_name == bot_name or abs(diff) < 1e-6 or gap_vs_top < 0.01)

    has_max_min = any("max" in str(c).lower() for c in df.columns) and any("min" in str(c).lower() for c in df.columns)
    max_c = next((c for c in df.columns if "max" in str(c).lower()), None)
    min_c = next((c for c in df.columns if "min" in str(c).lower()), None)
    max_val = float(df[max_c].iloc[0]) if (has_max_min and max_c in df) else None
    min_val = float(df[min_c].iloc[0]) if (has_max_min and min_c in df) else None

    cols = df.columns.tolist()
    cols_str = " ".join(str(c).lower() for c in cols)
    q_low = (user_query or "").lower()

    # 0.05 BÀI TOÁN THÂM NIÊN LÂU NHẤT / NHÂN SỰ KỲ CỰU (Longest-Tenured Veteran Employees)
    is_longest_tenure = (
        any(k in q_low for k in ["lâu nhất", "gắn bó lâu nhất", "thâm niên cao nhất", "thâm niên lớn nhất", "top thâm niên", "longest tenure", "highest tenure", "most tenured", "thâm niên làm việc lâu nhất"])
        or (
            any(k in q_low for k in ["thâm niên", "tenure", "gắn bó", "service", "năm"])
            and any(k in q_low for k in ["top", "cao nhất", "nhiều nhất", "lớn nhất", "dẫn đầu"])
            and not any(k in q_low for k in ["dưới", "ít hơn", "nhỏ hơn", "<", "mới vào", "mới gia nhập", "low tenure", "under 3", "under 5"])
            and not any(k in q_low for k in ["lương", "salary", "thu nhập", "tiền"])
        )
    ) or (
        any(k in str(val_col).lower() for k in ["yearsofservice", "service", "tenure", "thâm_niên", "thâm niên"])
        and not any(k in cols_str for k in ["salary", "currentsalary", "lương", "annualsalary"])
    )
    if is_longest_tenure:
        if is_en:
            urgent = f"• 🟢 **[Maintain Stability / 0-30 Days]**: Formally recognize and honor the enduring contribution of veteran personnel (**{top_name}** and cohort peers, spread of only {gap_vs_top:.2f}%); maintain current seniority reward policies without costly interventions."
            medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Establish an Enterprise Mentorship Program to facilitate knowledge transfer from veteran leaders to emerging high-potential talent around median tenure {median_val:.2f} years."
            longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Institutionalize Long-term Loyalty & Retention frameworks, appointing senior contributors to advisory councils and specialized subject-matter expert roles."
        else:
            urgent = f"• 🟢 **[Duy Trì Ổn Định / 0 - 30 Ngày]**: Ghi nhận và tôn vinh sự cống hiến bền bỉ của đội ngũ nhân sự kỳ cựu (**{top_name}** cùng các nhân sự trong nhóm, chênh lệch thâm niên chỉ {gap_vs_top:.2f}%); tiếp tục duy trì chính sách đãi ngộ thâm niên hiện hành, không phát sinh chi phí can thiệp đột biến."
            medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Thiết lập chương trình Cố vấn Doanh nghiệp (Mentorship Program) để lực lượng nhân sự kỳ cựu chuyển giao kiến thức, kỹ năng và kinh nghiệm thực chiến cho thế hệ nhân sự kế cận quanh mức thâm niên trung vị {median_val:.2f} năm."
            longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách đãi ngộ trọn đời (Long-term Retention & Loyalty Awards), quy hoạch các nhân sự cống hiến lâu năm vào hội đồng chuyên môn hoặc vị trí cố vấn chiến lược cấp cao."
        return f"{urgent}\n\n{medium}\n\n{longterm}"

    # 0.1 BÀI TOÁN NHÂN SỰ NGOẠI LỆ: THÂM NIÊN THẤP NHƯNG LƯƠNG TOP % (Low Tenure & Top Percentile Outliers)
    has_valid_sal = any(k in cols_str for k in ["salary", "currentsalary", "lương", "annualsalary"])
    is_low_tenure_top_sal = (
        has_valid_sal
        and not is_longest_tenure
        and (
            (
                any(k in q_low for k in ["thâm niên", "gắn bó", "tenure", "năm"])
                and any(k in q_low for k in ["dưới", "ít hơn", "nhỏ hơn", "<", "under", "less than", "mới vào", "mới gia nhập"])
                and any(k in q_low for k in ["top", "cao nhất"])
                and any(k in q_low for k in ["%", "phần trăm", "percent", "lương", "salary", "thu nhập"])
            ) or (
                any(any(k in str(c).lower() for k in ["salarypercentile", "percentile", "bách phân vị"]) for c in df.columns)
                and any(any(k in str(c).lower() for k in ["yearsofservice", "thâm niên", "tenure"]) for c in df.columns)
            )
        )
    )
    if is_low_tenure_top_sal:
        if is_en:
            urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Conduct proactive stay-interviews and review compensation packages with key high-performing personnel (**{top_name}** and peers) to solidify long-term retention and mitigate key-talent flight risk."
            medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Audit internal pay equity between lateral senior hires and tenured staff to maintain organizational harmony while benchmarking progression bands."
            longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Institutionalize a Total Rewards Framework with fast-track leadership pathways for high-impact young contributors."
        else:
            urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Tiến hành phỏng vấn gắn kết (Stay-Interview) và rà soát thỏa thuận đãi ngộ với nhân sự chủ chốt (**{top_name}** cùng các nhân sự trong nhóm) nhằm ghi nhận đóng góp và củng cố cam kết đồng hành lâu dài."
            medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đánh giá tính công bằng nội bộ (Internal Pay Equity) giữa nhóm nhân sự mới có thu nhập cao và lực lượng kỳ cựu; chuẩn hóa khung thang bảng lương theo vị trí và năng lực thực tế."
            longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách đãi ngộ tổng thể (Total Rewards Framework), xây dựng lộ trình thăng tiến rõ ràng lên các vị trí quản trị cấp cao cho các nhân tài trẻ có đóng góp đột phá."
        return f"{urgent}\n\n{medium}\n\n{longterm}"

    # 0.2 BÀI TOÁN TỶ LỆ ÉP LƯƠNG / NÉN LƯƠNG (Wage / Salary Compression)
    is_wage_compression = (
        any(k in q_low for k in ["ép lương", "áp lương", "nén lương", "compression", "wage compression", "salary compression"])
        or any(any(k in str(c).lower() for k in ["wagecompression", "compressionpct", "wage_compression"]) for c in df.columns)
    )
    if is_wage_compression:
        if is_en:
            urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit baseline compensation at **{top_name}** against external market benchmarks to prevent turnover among entry-level talent."
            medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Restructure salary bands for **{top_name}**, introducing merit-based progression steps to widen compression gaps."
            longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Deploy competency-based compensation frameworks balancing corporate payroll affordability with internal equity."
        else:
            urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát các vị trí có mức lương sàn tại phòng **{top_name}** so với mặt bằng thị trường để chủ động ngăn ngừa nguy cơ dịch chuyển lao động."
            medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Tái cấu trúc khung bậc lương (Salary Bands) cho phòng **{top_name}**, mở rộng khoảng cách giữa các bậc để tạo động lực gia tăng hiệu suất làm việc."
            longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng ma trận đánh giá năng lực gắn liền với điều chỉnh lương định kỳ, đảm bảo hài hòa giữa kiểm soát quỹ lương và tính công bằng nội bộ."
        return f"{urgent}\n\n{medium}\n\n{longterm}"

    # 0.3 BÀI TOÁN LƯƠNG TRƯỞNG PHÒNG VS CẤP DƯỚI (Manager vs Subordinate Salary Comparison)
    is_mgr_sub_salary_comp = (
        any(k in q_low for k in ["trưởng phòng", "dept_manager", "manager", "quản lý", "quản lí"])
        and any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên", "toàn bộ nhân viên", "trực thuộc"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập", "gấp", "chênh lệch", "cao hơn", "thấp hơn", "so sánh"])
    ) or (
        any("managersalary" in str(c).lower() or "lương quản lý" in str(c).lower() for c in df.columns)
        and any("subordinate" in str(c).lower() or "cấp dưới" in str(c).lower() for c in df.columns)
    )
    if is_mgr_sub_salary_comp:
        if is_en:
            urgent = "• 🔴 **[High Priority - Immediate / 0-30 Days]**: Review leadership responsibility allowances in units with inverted pay ratios (Production, Customer Service) to ensure managers receive adequate compensation for governance scope."
            medium = "• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Standardize managerial salary bands (Management Compensation Framework) ensuring a minimum 15-20% leadership premium above team median salary."
            longterm = "• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Implement a Dual Career Ladder (parallel progression for Management vs Technical Experts) to prevent compensation compression."
        else:
            urgent = "• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát phụ cấp trách nhiệm quản trị tại các phòng ban có hiện tượng nghịch đảo thu nhập (Production, Customer Service) nhằm bảo đảm thù lao tương xứng với trách nhiệm điều hành."
            medium = "• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa khung thang bảng lương quản lý (Management Compensation Framework), bảo đảm mức lương Trưởng phòng duy trì biên độ cao hơn mức trung vị của cấp dưới trực thuộc tối thiểu 15-20%."
            longterm = "• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện mô hình thăng tiến kép (Dual Career Ladder) tách biệt rõ ràng giữa ngạch Chuyên gia Kỹ thuật và ngạch Quản lý điều hành để cân bằng quyền lợi dài hạn."
        return f"{urgent}\n\n{medium}\n\n{longterm}"

    time_col = find_time_column(df)
    is_time_series = (
        time_col is not None
        and not any(k in str(time_col).lower() for k in ["service", "tenure", "thâm niên", "tham_nien", "experience", "kinh nghiệm", "age", "tuoi"])
        and (
            any(k in q_low for k in ["qua các năm", "theo năm", "từng năm", "over time", "per year", "over the years", "yearly", "xu hướng", "trend", "biến động", "thay đổi như thế nào", "qua thời gian", "theo tháng", "từng tháng", "mỗi tháng", "hàng tháng", "theo quý", "từng quý"])
            or detect_analysis_entity_type(df, user_query=user_query) == "time_series"
        )
    )
    is_salary = any(k in cols_str for k in ["salary", "lương", "wage", "pay", "thu_nhập", "raisecount", "raise"])
    is_headcount = any(k in cols_str for k in ["headcount", "nhân viên", "nhân sự", "slngnhnvin", "totalemployees"]) and not is_salary
    is_pareto = any(k in str(c).lower() for c in cols for k in ["cumulative", "tích lũy", "tich_luy", "runningtotal"]) or any(k in q_low for k in ["pareto", "80/20", "80%", "80-20", "tích lũy", "cumulative"])
    cum_col = next((c for c in cols if any(k in str(c).lower() for k in ["cumulative", "tích lũy", "tich_luy"])), None)
    cum_val_str = f" ({format_metric_value(df[cum_col].iloc[-1], cum_col)})" if (cum_col and not df.empty) else ""

    entity_type = detect_analysis_entity_type(df, user_query=user_query, name_col=name_col)

    # Kiểm tra độ trũng dữ liệu (Sparse / Discontinuous Time Series)
    is_sparse_ts = False
    if is_time_series or entity_type == "time_series":
        try:
            from src.analytics.anomaly import parse_time_point_index
            t_col_name = name_col if any(k in str(name_col).lower() for k in ["year", "month", "date", "tháng", "năm"]) else next((c for c in cols if any(k in str(c).lower() for k in ["year", "month", "date", "tháng", "năm"])), None)
            if t_col_name:
                time_vals = df[t_col_name].dropna().tolist()
                indices = [parse_time_point_index(tv, t_col_name) for tv in time_vals]
                valid_indices = [idx for idx, u in indices if idx > 0 and u != "unknown"]
                if len(valid_indices) >= 2:
                    valid_sorted = sorted(valid_indices)
                    if any((valid_sorted[i+1] - valid_sorted[i]) > 1 for i in range(len(valid_sorted)-1)):
                        is_sparse_ts = True
        except Exception:
            pass

    if is_en:
        if is_time_series or entity_type == "time_series":
            if is_sparse_ts:
                urgent = (
                    f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit operational drivers behind data discontinuity and investigate business activity at {bot_name} ({format_metric_value(bot_val, val_col)} vs peak {top_name}: {format_metric_value(top_val, val_col)}); "
                    f"evaluate transactional consistency across recorded periods."
                )
                medium = (
                    f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Establish continuous period-over-period tracking mechanisms; "
                    f"avoid rigid adherence to the raw average benchmark of {format_metric_value(mean_val, val_col)} across sparse intervals and strengthen core product/service capacity."
                )
                longterm = (
                    f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Institutionalize an end-to-end enterprise data warehouse & BI analytics pipeline, "
                    f"standardize business reporting cycles, and sustain long-term operating resilience."
                )
            else:
                urgent = (
                    f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit sales cycles and investigate root causes behind the sharpest decline in {bot_name} ({format_metric_value(bot_val, val_col)} vs peak {top_name}: {format_metric_value(top_val, val_col)}); "
                    f"deploy targeted promotional campaigns during off-peak periods to protect working capital."
                )
                medium = (
                    f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Formulate inventory buildup and capacity schedules ahead of peak demand periods; "
                    f"standardize operational quotas around the period average of {format_metric_value(mean_val, val_col)} units and maintain flexible cross-quarter logistics capacity."
                )
                longterm = (
                    f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Institutionalize seasonality-adaptive demand forecasting and predictive supply chain planning; "
                    f"align operational batch schedules with channel purchasing cycles to sustainably mitigate cyclical disruptions."
                )
        elif entity_type == "geo":
            if is_single_or_tied:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit local distribution partner networks and optimize shipping lead times in market **{top_name}** ({format_metric_value(top_val, val_col)}) to minimize inventory holding costs."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Accelerate consumer localization strategies in **{top_name}** and expand shelf coverage across leading retail chains."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Establish long-term strategic distribution partnerships and reinforce brand equity in **{top_name}**."
            else:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit local distribution partner networks and optimize cross-border shipping/logistics lead times in market **{bot_name}** ({format_metric_value(bot_val, val_col)}) to minimize inventory holding costs and shorten delivery cycles."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Accelerate consumer localization strategies by tailoring packaging sizes and sweetness profiles to local cultural preferences; expand retail shelf coverage across leading supermarket chains in **{bot_name}** toward the benchmark average of {format_metric_value(mean_val, val_col)}."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Establish strategic regional distribution hubs and long-term joint ventures with prominent international retail conglomerates to solidify premium chocolate brand positioning across key global markets (spearheaded by **{top_name}**: {format_metric_value(top_val, val_col)})."
        elif entity_type == "team":
            if is_single_or_tied:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Review quarterly quota pacing and sales incentives for squad **{top_name}** ({format_metric_value(top_val, val_col)}) to sustain frontline selling momentum."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Optimize territory planning and account allocation for **{top_name}**; deploy consultative selling coaching."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Institutionalize sales competency frameworks and AI sales enablement tools for **{top_name}**."
            else:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Deploy immediate incentive bonuses and sales contests for squad **{bot_name}** ({format_metric_value(bot_val, val_col)}); organize a peer-led best-practice transfer workshop with market leader **{top_name}** ({format_metric_value(top_val, val_col)}) to replicate top-performing sales pitches across underperforming reps."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Re-evaluate and rebalance territory planning and sales quota allocations based on local market potential; launch targeted sales enablement programs on deal closing and objection handling to lift team averages toward {format_metric_value(mean_val, val_col)}."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Institutionalize a standardized sales competency framework, implement dynamic performance-tiered compensation plans, and deploy AI-assisted sales coaching tools to maximize long-term quota attainment per representative."
        elif entity_type == "employee" or entity_type == "department" or entity_type == "title" or entity_type == "gender" or is_salary or is_headcount:
            is_salesperson_perf = any(k in cols_str for k in ["sales", "amount", "boxes", "doanh số", "doanh thu", "hộp"]) or any(k in q_low for k in ["doanh số", "doanh thu", "bán hàng", "sales", "hộp"])
            is_mgr_diversity = (
                any(k in q_low for k in ["dept_manager", "manager", "quản lý", "trưởng phòng", "ban quản lý", "lãnh đạo"])
                or any("manager" in str(c).lower() for c in df.columns)
            ) and (
                any(k in cols_str for k in ["gender", "giới tính", "sex", "male", "female", "nam", "nữ"])
                or any(k in q_low for k in ["giới tính", "nam", "nữ", "gender", "male", "female"])
            )
            if is_mgr_diversity:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit managerial appointment criteria and review succession planning pipelines across all departments (spearheaded by {top_name}: {format_metric_value(top_val, val_col)})."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Establish targeted Leadership Development Programs to sustain leadership gender balance and support meritocratic progression."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Institutionalize an ESG Diversity & Inclusion Governance Framework and transparent executive promotion pathways."
            elif is_headcount:
                if is_single_or_tied:
                    urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Review workforce staffing capacity for {top_name} ({format_metric_value(top_val, val_col)} personnel); balance workload distribution across current team members."
                    medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Standardize headcount planning around operational targets for {top_name}."
                    longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Build dynamic talent mobility models and succession planning for {top_name}."
                else:
                    urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Finalize team allocation for {bot_name} ({format_metric_value(bot_val, val_col)} reps); align quarterly sales quotas with squad capacity led by {top_name} ({format_metric_value(top_val, val_col)} reps)."
                    medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Standardize team sizes around {format_metric_value(mean_val, val_col)} reps per squad; conduct uniform enablement training to lift mid-tier rep productivity."
                    longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Build dynamic territory rebalancing models and implement AI sales coaching tools to maximize sales output per representative."
            elif is_salesperson_perf and not is_salary:
                if is_single_or_tied:
                    urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Review priority customer deal pipeline for sales representative **{top_name}** ({format_metric_value(top_val, val_col)}); unblock pending high-value accounts."
                    medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Establish sales quotas and expand qualified prospect accounts for **{top_name}**."
                    longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Deploy performance-tiered commission incentives and AI sales enablement tools."
                else:
                    urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Organize a deal-closing best-practice transfer workshop from sales leader **{top_name}** ({format_metric_value(top_val, val_col)}) to sales representative **{bot_name}** ({format_metric_value(bot_val, val_col)}); audit and unblock pending deals across priority accounts."
                    medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Standardize sales quotas and rebalance account portfolios around the period average of {format_metric_value(mean_val, val_col)}; deploy consultative selling training to uplift underperforming reps."
                    longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Deploy tiered commission plans tied to margin contribution and integrate AI sales enablement tools to maximize sales output per representative."
            else:
                if is_single_or_tied:
                    if has_max_min and max_val is not None and min_val is not None:
                        urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Review internal compensation structure across unit **{top_name}** (peak compensation {format_metric_value(max_val, max_c)} vs floor {format_metric_value(min_val, min_c)}, spread of {format_metric_value(top_val, val_col)}); conduct proactive stay-interviews with key senior specialists."
                    else:
                        urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Review compensation structure and retention packages at unit **{top_name}** ({format_metric_value(top_val, val_col)}); conduct proactive stay-interviews to protect key talent."
                    medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Benchmark career progression bands and salary budget frameworks for unit **{top_name}** to ensure internal equity."
                    longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Overhaul the Total Rewards framework, combining market-competitive compensation with transparent merit-based promotions."
                else:
                    is_small_discrete = (top_val <= 5 and float(top_val).is_integer()) or bot_val == 0
                    comp_gap_str = f"{top_name}: {format_metric_value(top_val, val_col)} vs {bot_name}: {format_metric_value(bot_val, val_col)}" if is_small_discrete else f"{top_name}: {format_metric_value(top_val, val_col)} vs {bot_name}: {format_metric_value(bot_val, val_col)}, {gap_vs_top:.1f}% lower than leader"
                    if not is_small_discrete and gap_vs_top < 1.0:
                        urgent = f"• 🟢 **[Maintain Stability / 0-30 Days]**: Acknowledge near-absolute operational parity ({gap_vs_top:.2f}% gap between **{top_name}** and **{bot_name}** represents random statistical noise); continue current policy frameworks, **no costly intervention required**."
                        medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Maintain regular monitoring during upcoming performance appraisal cycles; benchmark career progression bands against median of {format_metric_value(median_val, val_col)}."
                        longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Sustain the Total Rewards framework and transparent merit-based promotions to maintain long-term equity."
                    elif not is_small_discrete and gap_vs_top <= 5.0:
                        urgent = f"• 🟡 **[Routine Monitoring / 0-30 Days]**: Minor variance detected ({gap_vs_top:.1f}% between **{top_name}** and **{bot_name}**), well within acceptable operational thresholds; no immediate emergency action required."
                        medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Conduct internal review during the next evaluation cycle; benchmark career progression bands against median baseline of {format_metric_value(median_val, val_col)}."
                        longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Overhaul the Total Rewards framework, combining market-competitive compensation with transparent merit-based promotions."
                    else:
                        urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Audit compensation parity across roles with the widest disparity ({comp_gap_str}); conduct proactive stay-interviews to curb flight risk among key talent."
                        medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Benchmark career progression bands against the median baseline of {format_metric_value(median_val, val_col)}; rebalance departmental salary budget pools and structured hiring plans for internal equity."
                        longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Overhaul the Total Rewards framework, combining market-competitive compensation with transparent merit-based promotions and employer branding."
        elif entity_type == "product":
            if is_single_or_tied:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Prioritize supply chain security and safety stock for key product **{top_name}** ({format_metric_value(top_val, val_col)}); control inventory replenishment cycles to meet demand."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Expand prime shelf placement, dynamic pricing, and cross-selling for **{top_name}**; optimize inventory turnover."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Optimize packaging tiering (SKU/Packaging) and develop derivative product lines based on **{top_name}**."
            elif is_pareto:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Prioritize supply chain security and safety stock for top-selling SKU **{top_name}** ({format_metric_value(top_val, val_col)}); design promotional bundling combos pairing **{top_name}** with slower-moving products outside the 80/20 Pareto core to stimulate demand and liberate working capital."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Expand prime shelf placement and cross-selling for the top {len(df)} core SKUs (contributing ~80% of total revenue{cum_val_str}); rebalance replenishment orders around the category average of {format_metric_value(mean_val, val_col)}."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Optimize packaging tiering (SKU/Packaging) and develop derivative product lines based on market leader **{top_name}**; establish an agile demand-driven supply chain to continuously protect category margin resilience."
            else:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Deploy promotional bundling campaigns (Combos) pairing top-performing SKU **{top_name}** ({format_metric_value(top_val, val_col)}) with slower-moving **{bot_name}** ({format_metric_value(bot_val, val_col)}); perform an immediate warehouse inventory audit on **{bot_name}** to expedite stock clearance and liberate working capital."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Scale dynamic pricing adjustments and cross-selling initiatives across primary distribution channels; re-align replenishment schedules and demand forecasting around the baseline average of {format_metric_value(mean_val, val_col)} to boost inventory turnover."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Re-engineer product packaging and portfolio tiering (SKU/Packaging); establish an agile, demand-driven supply chain to continuously protect category margin resilience."
        else:
            if is_single_or_tied:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Concentrate strategic resources to optimize performance in **{top_name}** ({format_metric_value(top_val, val_col)})."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Realign resource allocation frameworks around operational requirements for **{top_name}**."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Expand strategic portfolio initiatives and institutionalize enterprise risk governance."
            else:
                urgent = f"• 🔴 **[High Priority - Immediate / 0-30 Days]**: Concentrate strategic resources to scale market leader {top_name} ({format_metric_value(top_val, val_col)}), while addressing operational bottlenecks in {bot_name} ({format_metric_value(bot_val, val_col)})."
                medium = f"• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Realign resource allocation frameworks around the benchmark average of {format_metric_value(mean_val, val_col)}; standardize cross-unit operating protocols."
                longterm = f"• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Expand strategic portfolio initiatives, institutionalize enterprise risk governance, and sustain market leadership."
    else:
        if is_time_series or entity_type == "time_series":
            # Phân loại chuyên sâu theo nghiệp vụ để không bao giờ sinh nhầm thuật ngữ bán hàng cho nghiệp vụ nhân sự/quản lý
            is_hr_mgr_promo = (
                any(k in q_low for k in ["manager", "quản lý", "quản lí", "trưởng phòng", "ban quản lý", "bổ nhiệm", "thăng chức", "thăng tiến", "lãnh đạo", "leadership"])
                or any("manager" in str(c).lower() or "promot" in str(c).lower() for c in df.columns)
            )
            is_hr_hiring = (
                any(k in q_low for k in ["tuyển dụng", "tuyển", "hire", "headcount", "nhân sự vào", "nhân sự ra", "quy mô nhân sự"])
                or any(k in cols_str for k in ["totalhires", "hireyear", "hires"])
            )
            is_hr_salary = (
                any(k in q_low for k in ["lương", "salary", "quỹ lương", "thu nhập", "payroll", "thu nhập"])
                or any(k in cols_str for k in ["salary", "lương", "payroll", "quỹ lương"])
            )

            if is_hr_mgr_promo:
                urgent = (
                    f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát quy hoạch cán bộ nguồn và lộ trình bổ nhiệm nhân sự cấp Quản lý (Succession Planning) để đảm bảo tính liên tục của bộ máy lãnh đạo, đặc biệt chú trọng các năm có khoảng trũng bổ nhiệm như kỳ {bot_name} ({format_metric_value(bot_val, val_col)} so với đỉnh {top_name}: {format_metric_value(top_val, val_col)})."
                )
                medium = (
                    f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa quy trình đánh giá năng lực cán bộ và triển khai chương trình đào tạo quản lý kế cận (Leadership Pipeline), duy trì cơ cấu giới tính cân bằng (Gender Diversity) và minh bạch trong tiêu chuẩn thăng tiến quanh mức chuẩn {format_metric_value(mean_val, val_col)}/kỳ."
                )
                longterm = (
                    f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện khung quản trị nhân tài và lãnh đạo ESG (ESG Leadership & Meritocracy Framework), xây dựng đội ngũ kế cận chất lượng cao và sẵn sàng đáp ứng nhu cầu mở rộng quy mô doanh nghiệp."
                )
            elif is_hr_hiring:
                urgent = (
                    f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Ổn định quy mô tuyển dụng và thiết lập mức sàn định biên nhân sự tối thiểu để phòng ngừa nguy cơ đứt gãy thế hệ kế thừa (tại kỳ {bot_name}: {format_metric_value(bot_val, val_col)} so với đỉnh {top_name}: {format_metric_value(top_val, val_col)})."
                )
                medium = (
                    f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa định biên và lộ trình hội nhập, đào tạo nâng cao kỹ năng cho nhân sự mới theo mức chuẩn {format_metric_value(mean_val, val_col)}/kỳ."
                )
                longterm = (
                    f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng thương hiệu nhà tuyển dụng uy tín (Employer Branding) và chương trình phát triển nhân tài trẻ (Management Trainee) dài hạn."
                )
            elif is_hr_salary:
                urgent = (
                    f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát biến động quỹ lương và các khoản chi trả tại kỳ {bot_name} ({format_metric_value(bot_val, val_col)} so với đỉnh {top_name}: {format_metric_value(top_val, val_col)}) để tối ưu hóa chi phí vận hành."
                )
                medium = (
                    f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Tái cân bằng cấu trúc quỹ lương quanh mức trung bình {format_metric_value(mean_val, val_col)}/kỳ, gắn kết chặt chẽ mức tăng lương với hiệu quả công việc (Pay-for-Performance)."
                )
                longterm = (
                    f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách đãi ngộ tổng thể (Total Rewards Framework) đảm bảo tính công bằng nội bộ và cạnh tranh trên thị trường lao động."
                )
            elif is_sparse_ts:
                urgent = (
                    f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát nguyên nhân gián đoạn chu kỳ và phân tích chất lượng kinh doanh tại kỳ ghi nhận {bot_name} ({format_metric_value(bot_val, val_col)} so với đỉnh {top_name}: {format_metric_value(top_val, val_col)}); "
                    f"đánh giá mức độ ổn định của luồng giao dịch giữa các mốc phát sinh thực tế."
                )
                medium = (
                    f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Thiết lập cơ chế ghi nhận và theo dõi giao dịch liên tục qua từng tháng; "
                    f"tránh áp dụng máy móc định mức trung bình {format_metric_value(mean_val, val_col)}/kỳ cho các khoảng trũng dữ liệu, đồng thời củng cố năng lực khai thác các danh mục chủ lực."
                )
                longterm = (
                    f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện hệ thống quản trị dữ liệu kinh doanh tập trung (BI/Analytics Data Warehouse) đồng bộ xuyên suốt, "
                    f"chuẩn hóa chu kỳ vận hành và nâng cao khả năng giữ chân khách hàng dài hạn."
                )
            else:
                urgent = (
                    f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát chu kỳ bán hàng/hoạt động và nguyên nhân sụt giảm tại {bot_name} ({format_metric_value(bot_val, val_col)} so với đỉnh {top_name}: {format_metric_value(top_val, val_col)}); "
                    f"chủ động triển khai các chương trình kích cầu và tối ưu chi phí trong các kỳ thấp điểm để bảo toàn dòng tiền."
                )
                medium = (
                    f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Tối ưu hóa kế hoạch vận hành và cân đối nguồn lực đón đầu các đợt cao điểm; "
                    f"chuẩn hóa định mức quanh mức trung bình {format_metric_value(mean_val, val_col)}/kỳ và dự phòng công suất linh hoạt theo quý."
                )
                longterm = (
                    f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện mô hình hoạch định dự báo nhu cầu thích ứng theo chu kỳ (Dynamic Demand Forecasting); "
                    f"đồng bộ quy trình từ khâu cung ứng đến các kênh phân phối để chủ động thích ứng với biến động thị trường."
                )
        elif entity_type == "geo":
            if is_single_or_tied:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát mạng lưới đối tác phân phối địa phương tại thị trường **{top_name}** ({format_metric_value(top_val, val_col)}); tối ưu hóa chuỗi cung ứng và logistics xuất nhập khẩu để giảm thiểu chi phí lưu kho và rút ngắn thời gian giao hàng."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đẩy mạnh chiến lược bản địa hóa sản phẩm (Market Localization), điều chỉnh khẩu vị và quy cách đóng gói phù hợp với văn hóa tiêu dùng bản địa tại **{top_name}**; mở rộng độ phủ vào các chuỗi siêu thị/bán lẻ trọng điểm."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng quan hệ đối tác chiến lược dài hạn với các tập đoàn bán lẻ quốc tế lớn, thiết lập trung tâm điều phối kho vận khu vực tại **{top_name}** và củng cố vị thế thương hiệu."
            else:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát mạng lưới đối tác phân phối địa phương tại thị trường **{bot_name}** ({format_metric_value(bot_val, val_col)}); tối ưu hóa chuỗi cung ứng và logistics xuất nhập khẩu để giảm thiểu chi phí lưu kho và rút ngắn thời gian giao hàng."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đẩy mạnh chiến lược bản địa hóa sản phẩm (Market Localization), điều chỉnh khẩu vị và quy cách đóng gói phù hợp với văn hóa tiêu dùng bản địa; mở rộng độ phủ vào các chuỗi siêu thị/bán lẻ trọng điểm tại **{bot_name}** hướng tới mức chuẩn {format_metric_value(mean_val, val_col)}."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng quan hệ đối tác chiến lược dài hạn với các tập đoàn bán lẻ quốc tế lớn, thiết lập trung tâm điều phối kho vận khu vực (Regional Hub) và củng cố vị thế thương hiệu sô-cô-la cao cấp toàn cầu (dẫn dắt bởi **{top_name}**: {format_metric_value(top_val, val_col)})."
        elif entity_type == "team":
            if is_single_or_tied:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát tiến độ hoàn thành hạn ngạch doanh số của đội ngũ **{top_name}** ({format_metric_value(top_val, val_col)}); thiết lập cơ chế thi đua và hoa hồng thưởng nóng để kích hoạt động lực bán hàng của từng đại diện thương mại."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đánh giá và tối ưu hóa địa bàn kinh doanh (Territory Planning) cùng danh mục khách hàng phụ trách của **{top_name}**; tổ chức đào tạo chuyên sâu về kỹ năng chốt hợp đồng và mở rộng tài khoản doanh nghiệp."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Chuẩn hóa khung năng lực bán hàng (Sales Competency Framework), xây dựng chính sách đãi ngộ linh hoạt theo hiệu quả kinh doanh và trang bị công cụ hỗ trợ bán hàng AI."
            else:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Thiết lập cơ chế thi đua và hoa hồng thưởng nóng (Incentive) cho đội ngũ **{bot_name}** ({format_metric_value(bot_val, val_col)}); tổ chức ngay buổi chuyển giao kinh nghiệm thực chiến (Best-Practice Sharing) từ team dẫn đầu **{top_name}** ({format_metric_value(top_val, val_col)}) sang các thành viên có hiệu suất thấp nhất để kích hoạt năng suất bán hàng ngay trong tháng."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đánh giá và phân chia lại địa bàn kinh doanh (Territory Planning) cùng hạn ngạch doanh số (Quota Allocation) dựa trên tiềm năng thị trường; triển khai chương trình đào tạo kỹ năng bán hàng và xử lý từ chối chuyên sâu cho các đội ngũ bám sát mức chuẩn {format_metric_value(mean_val, val_col)}."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Chuẩn hóa khung năng lực bán hàng (Sales Competency Framework), xây dựng chính sách đãi ngộ linh hoạt theo hiệu quả kinh doanh và ứng dụng công cụ hỗ trợ bán hàng (Sales Enablement) bằng AI để nâng cao năng suất doanh thu bền vững trên từng đại diện thương mại."
        elif entity_type == "employee" or entity_type == "department" or entity_type == "title" or entity_type == "gender" or is_salary or is_headcount:
            is_salesperson_perf = any(k in cols_str for k in ["sales", "amount", "boxes", "doanh số", "doanh thu", "hộp"]) or any(k in q_low for k in ["doanh số", "doanh thu", "bán hàng", "sales", "hộp"])
            is_mgr_diversity = (
                any(k in q_low for k in ["dept_manager", "manager", "quản lý", "trưởng phòng", "ban quản lý", "lãnh đạo"])
                or any("manager" in str(c).lower() for c in df.columns)
            ) and (
                any(k in cols_str for k in ["gender", "giới tính", "sex", "male", "female", "nam", "nữ"])
                or any(k in q_low for k in ["giới tính", "nam", "nữ", "gender", "male", "female"])
            )
            if is_mgr_diversity:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát quy hoạch cán bộ kế thừa (Succession Planning) và chuẩn hóa tiêu chuẩn đánh giá bổ nhiệm cấp quản lý tại các phòng ban (dẫn dắt bởi {top_name}: {format_metric_value(top_val, val_col)})."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Triển khai chương trình phát triển năng lực lãnh đạo (Leadership Development Program) và duy trì chỉ số cân bằng giới trong quy hoạch nguồn cán bộ."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện khung quản trị nhân sự ESG (ESG Governance Framework) và chính sách đề bạt minh bạch nhằm xây dựng đội ngũ lãnh đạo bền vững."
            elif is_headcount:
                if is_single_or_tied:
                    urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát mức độ đáp ứng khối lượng công việc của đội ngũ **{top_name}** ({format_metric_value(top_val, val_col)} nhân sự); cân đối giao chỉ tiêu phù hợp với quy mô lực lượng thực tế."
                    medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa định biên nhân sự theo nhu cầu vận hành thực tế của **{top_name}**; triển khai đào tạo nâng cao kỹ năng nhằm gia tăng năng suất lao động bình quân."
                    longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng kế hoạch quy hoạch nhân sự dài hạn và cơ chế phát triển nhân tài kế thừa cho **{top_name}**."
                else:
                    urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát danh sách {bot_name} ({format_metric_value(bot_val, val_col)} nhân sự) để hoàn tất việc phân bổ đội ngũ chính thức; cân đối chỉ tiêu doanh số phù hợp với quy mô lực lượng bán hàng của từng team (dẫn đầu là {top_name}: {format_metric_value(top_val, val_col)} nhân viên)."
                    medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa định biên nhân sự quanh mức trung bình {format_metric_value(mean_val, val_col)} nhân viên/đội; triển khai chương trình đào tạo kỹ năng bán hàng đồng bộ nhằm thu hẹp khoảng cách năng suất."
                    longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Thiết lập cơ chế luân chuyển nhân sự linh hoạt theo mùa vụ và tiềm năng thị trường; ứng dụng hệ thống CRM/AI phân tích hiệu suất cá nhân để tối đa hóa doanh thu trên mỗi đại diện kinh doanh."
            elif is_salesperson_perf and not is_salary:
                if is_single_or_tied:
                    urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát chi tiết danh mục khách hàng và tiến độ xử lý cơ hội bán hàng của nhân sự **{top_name}** ({format_metric_value(top_val, val_col)}); tháo gỡ kịp thời các điểm nghẽn tại các khách hàng trọng điểm để đẩy nhanh tiến độ chốt deal."
                    medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Thiết lập hạn ngạch doanh số mục tiêu và kế hoạch mở rộng tệp khách hàng tiềm năng cho **{top_name}**; tối ưu hóa quy trình tư vấn giải pháp và chăm sóc khách hàng sau bán."
                    longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng chính sách hoa hồng lũy tiến gắn liền với hiệu quả kinh doanh và ứng dụng trợ lý AI hỗ trợ bán hàng để duy trì đà tăng trưởng doanh số cá nhân bền vững."
                else:
                    urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Tổ chức chương trình chuyển giao kinh nghiệm thực chiến từ nhân sự dẫn đầu **{top_name}** ({format_metric_value(top_val, val_col)}) cho nhân sự **{bot_name}** ({format_metric_value(bot_val, val_col)}); rà soát và tháo gỡ các vướng mắc tại các khách hàng trọng điểm để cải thiện tỷ lệ chốt deal ngay trong tháng."
                    medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa hạn ngạch doanh số và cân đối lại danh mục khách hàng phụ trách quanh mức trung bình {format_metric_value(mean_val, val_col)}; triển khai đào tạo kỹ năng tư vấn chuyên sâu và xử lý từ chối cho các nhân sự chưa đạt chỉ tiêu."
                    longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng chính sách thưởng hoa hồng lũy tiến gắn với hiệu quả kinh doanh cá nhân; ứng dụng trợ lý AI hỗ trợ bán hàng (Sales Enablement) để nâng cao năng suất doanh thu trên từng nhân sự."
            else:
                if is_single_or_tied:
                    if has_max_min and max_val is not None and min_val is not None:
                        urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát cơ cấu phân bổ thu nhập nội bộ tại đơn vị/vị trí **{top_name}** (mức lương cao nhất {format_metric_value(max_val, max_c)} so với mức lương sàn {format_metric_value(min_val, min_c)}, biên độ {format_metric_value(top_val, val_col)}); chủ động phỏng vấn gắn kết (stay-interview) và lắng nghe nguyện vọng nhân sự chủ chốt để phòng ngừa rủi ro biến động nhân tài."
                    else:
                        urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát chính sách lương thưởng và đãi ngộ tại đơn vị/vị trí **{top_name}** ({format_metric_value(top_val, val_col)}); chủ động đối thoại và lắng nghe nguyện vọng nhân sự để phòng ngừa rủi ro biến động nhân tài chủ chốt."
                    medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa khung bậc lương (Salary Bands) và lộ trình thăng tiến nghề nghiệp (Career Progression) theo năng lực cho đơn vị **{top_name}**; cân đối lại quỹ lương nội bộ nhằm đảm bảo tính công bằng và cạnh tranh."
                    longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách đãi ngộ tổng thể (Total Rewards), kết hợp chính sách bổ nhiệm minh bạch dựa trên năng lực (Merit-based Promotion) và xây dựng thương hiệu nhà tuyển dụng để thu hút nhân tài cấp cao."
                else:
                    is_small_discrete = (top_val <= 5 and float(top_val).is_integer()) or bot_val == 0
                    comp_gap_str = f"{bot_name}: {format_metric_value(bot_val, val_col)} so với {top_name}: {format_metric_value(top_val, val_col)}" if is_small_discrete else f"{bot_name}: {format_metric_value(bot_val, val_col)} so với {top_name}: {format_metric_value(top_val, val_col)}, thấp hơn {gap_vs_top:.1f}% so với vị trí dẫn đầu"
                    if not is_small_discrete and gap_vs_top < 1.0:
                        urgent = f"• 🟢 **[Duy Trì Ổn Định / 0 - 30 Ngày]**: Ghi nhận hệ thống vận hành xuất sắc và đạt độ bình đẳng/cân bằng gần như tuyệt đối (Chênh lệch chỉ {gap_vs_top:.2f}%, thuộc sai số thống kê ngẫu nhiên giữa **{bot_name}** và **{top_name}**); tiếp tục duy trì chính sách hiện hành, **không phát sinh hành động can thiệp tốn kém chi phí**."
                        medium = f"• 🟡 **[Trung Hạn - Giám Sát / 1 - 3 Quý Tới]**: Duy trì cơ chế theo dõi định kỳ trong các kỳ đánh giá tiếp theo; tiếp tục chuẩn hóa lộ trình thăng tiến và khung bậc lương quanh mức trung vị {format_metric_value(median_val, val_col)}."
                        longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Tiếp tục phát huy chính sách đãi ngộ tổng thể (Total Rewards) và cơ chế bổ nhiệm minh bạch dựa trên năng lực (Merit-based Promotion) để duy trì tính bình đẳng lâu dài."
                    elif not is_small_discrete and gap_vs_top <= 5.0:
                        urgent = f"• 🟡 **[Theo Dõi Định Kỳ / 0 - 30 Ngày]**: Ghi nhận mức chênh lệch nhẹ ({gap_vs_top:.1f}% giữa **{bot_name}** và **{top_name}**), nằm hoàn toàn trong biên độ kiểm soát cho phép; chưa cần can thiệp khẩn cấp."
                        medium = f"• 🟡 **[Trung Hạn - Rà Soát Nội Bộ / 1 - 3 Quý Tới]**: Tiến hành rà soát nội bộ trong kỳ đánh giá tiếp theo; chuẩn hóa lộ trình thăng tiến và cân đối lại quỹ lương quanh mức trung vị {format_metric_value(median_val, val_col)}."
                        longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách đãi ngộ tổng thể (Total Rewards), kết hợp chính sách bổ nhiệm minh bạch dựa trên năng lực (Merit-based Promotion) để đảm bảo tính cạnh tranh và công bằng bền vững."
                    else:
                        urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát chính sách lương thưởng và đãi ngộ tại đơn vị/vị trí ({comp_gap_str}); chủ động đối thoại và lắng nghe nguyện vọng nhân sự để ngăn ngừa rủi ro biến động nhân tài chủ chốt."
                        medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa lộ trình thăng tiến nghề nghiệp (Career Progression) và định biên tuyển dụng theo nhu cầu thực tế của từng đơn vị quanh mức trung vị {format_metric_value(median_val, val_col)}; tái cân bằng quỹ lương để đảm bảo tính công bằng nội bộ."
                        longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách đãi ngộ tổng thể (Total Rewards), kết hợp chính sách bổ nhiệm minh bạch dựa trên năng lực (Merit-based Promotion) và xây dựng thương hiệu nhà tuyển dụng để thu hút nhân tài cấp cao."
        elif entity_type == "product":
            if is_single_or_tied:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Ưu tiên bảo đảm nguồn cung ứng và duy trì mức tồn kho an toàn cho mặt hàng **{top_name}** ({format_metric_value(top_val, val_col)}); kiểm soát chặt chẽ kế hoạch luân chuyển hàng hóa để đáp ứng kịp thời nhu cầu thị trường."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đẩy mạnh các chương trình trưng bày ưu tiên, định giá linh hoạt và bán kèm (Cross-selling) cho sản phẩm **{top_name}**; tối ưu hóa vòng quay hàng tồn kho (Inventory Turnover)."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Cải tiến bao bì đóng gói (Packaging/SKU) và nghiên cứu mở rộng dòng sản phẩm phái sinh từ **{top_name}**; xây dựng chuỗi cung ứng phản ứng nhanh để bảo vệ biên lợi nhuận danh mục."
            elif is_pareto:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Ưu tiên bảo đảm nguồn cung ứng và tồn kho an toàn cho mặt hàng bán chạy nhất **{top_name}** ({format_metric_value(top_val, val_col)}); thiết lập gói sản phẩm ưu đãi kết hợp (Combo) giữa **{top_name}** với các sản phẩm bán chậm hơn ngoài nhóm Pareto để kích cầu và giải phóng vốn lưu động."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đẩy mạnh chương trình trưng bày ưu tiên và bán chéo (Cross-selling) cho top {len(df)} sản phẩm chủ lực (đóng góp ~80% tổng doanh số{cum_val_str}); tái cân đối kế hoạch mua hàng quanh mức trung bình {format_metric_value(mean_val, val_col)}."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Cải tiến bao bì đóng gói (Packaging/SKU) và nghiên cứu mở rộng dòng sản phẩm phái sinh từ mặt hàng dẫn đầu **{top_name}**; xây dựng chuỗi cung ứng phản ứng nhanh bám sát nhu cầu để bảo vệ biên lợi nhuận danh mục."
            else:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Thiết lập gói sản phẩm ưu đãi kết hợp (Combo) giữa mặt hàng bán chạy **{top_name}** ({format_metric_value(top_val, val_col)}) với sản phẩm bán chậm hơn **{bot_name}** ({format_metric_value(bot_val, val_col)}); đồng thời kiểm kê hạn sử dụng và đánh giá tồn kho kho vận của **{bot_name}** để kịp thời giải phóng vốn lưu động."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Đẩy mạnh chương trình định giá linh hoạt và bán chéo (Cross-selling) tại các kênh phân phối; tái cân đối kế hoạch mua hàng quanh mức trung bình {format_metric_value(mean_val, val_col)} để tối ưu hóa vòng quay hàng tồn kho (Inventory Turnover)."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Cải tiến bao bì đóng gói (Packaging/SKU), đa dạng hóa phân khúc giá và cơ cấu danh mục sản phẩm; xây dựng chuỗi cung ứng phản ứng nhanh bám sát sự thay đổi trong thị hiếu tiêu dùng để bảo vệ biên lợi nhuận danh mục."
        else:
            if is_single_or_tied:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Tập trung nguồn lực bảo vệ và phát huy hiệu quả hoạt động tại **{top_name}** ({format_metric_value(top_val, val_col)}); rà soát kịp thời các yếu tố phát sinh ảnh hưởng đến hiệu suất vận hành."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Chuẩn hóa quy trình vận hành và tối ưu hóa phân bổ ngân sách tại **{top_name}** dựa trên nhu cầu thực tế."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng lộ trình phát triển danh mục dài hạn, hoàn thiện hệ thống quản trị rủi ro và củng cố vị thế dẫn dắt."
            else:
                urgent = f"• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Tập trung nguồn lực bảo vệ và phát huy thế mạnh của {top_name} ({format_metric_value(top_val, val_col)}), đồng thời rà soát và khắc phục các điểm nghẽn hiệu quả tại nhóm {bot_name} ({format_metric_value(bot_val, val_col)})."
                medium = f"• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Tái cơ cấu quy trình phân bổ nguồn lực dựa trên mức trung bình {format_metric_value(mean_val, val_col)}; thiết lập các chuẩn mực vận hành đồng bộ giữa các đơn vị."
                longterm = f"• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Xây dựng lộ trình phát triển danh mục dài hạn, hoàn thiện hệ thống quản trị rủi ro và củng cố vị thế dẫn dắt thị trường."

    return f"{urgent}\n\n{medium}\n\n{longterm}"


def generate_data_grounded_anomaly(df: pd.DataFrame, user_query: str = "", is_en: bool = False) -> str:
    """Tự động sinh nội dung Phần 2.1 (Phát hiện Bất thường & Xu hướng Chính) chuẩn mực, bám sát 100% dữ liệu thực tế."""
    if df is None or df.empty:
        return ""
    q_low = (user_query or "").lower()
    cols_str = " ".join(str(c).lower() for c in df.columns)

    # 0.05 BÀI TOÁN THÂM NIÊN LÂU NHẤT / NHÂN SỰ KỲ CỰU (Longest-Tenured Veteran Employees)
    is_longest_tenure = (
        any(k in q_low for k in ["lâu nhất", "gắn bó lâu nhất", "thâm niên cao nhất", "thâm niên lớn nhất", "top thâm niên", "longest tenure", "highest tenure", "most tenured", "thâm niên làm việc lâu nhất"])
        or (
            any(k in q_low for k in ["thâm niên", "tenure", "gắn bó", "service", "năm"])
            and any(k in q_low for k in ["top", "cao nhất", "nhiều nhất", "lớn nhất", "dẫn đầu"])
            and not any(k in q_low for k in ["dưới", "ít hơn", "nhỏ hơn", "<", "mới vào", "mới gia nhập", "low tenure", "under 3", "under 5"])
            and not any(k in q_low for k in ["lương", "salary", "thu nhập", "tiền"])
        )
    ) or (
        any(k in cols_str for k in ["yearsofservice", "tenure", "thâm niên", "service_years"])
        and not any(k in cols_str for k in ["salary", "currentsalary", "lương", "annualsalary"])
    )
    if is_longest_tenure:
        try:
            tenure_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["yearsofservice", "tenure", "thâm niên", "service_years", "years", "năm"])), None)
            name_col = get_best_name_column(df, exclude_cols=[tenure_col] if tenure_col else None)
            if not name_col:
                name_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["fullname", "full_name", "name", "tên", "họ và tên", "salesperson"])), df.columns[0])

            df_eval = df.copy()
            if tenure_col:
                df_eval[tenure_col] = pd.to_numeric(df_eval[tenure_col], errors="coerce").fillna(0)
                df_eval = df_eval.sort_values(by=tenure_col, ascending=False)

            n_emps = len(df_eval)
            top_emp = df_eval.iloc[0]
            top_name = format_entity_label(top_emp[name_col], col_name=name_col, lang="en" if is_en else "vi")
            top_tenure_val = float(top_emp[tenure_col]) if tenure_col else 0

            min_tenure_val = float(df_eval[tenure_col].min()) if tenure_col else 0
            max_tenure_val = float(df_eval[tenure_col].max()) if tenure_col else 0
            avg_tenure_val = float(df_eval[tenure_col].mean()) if tenure_col else 0
            tenure_diff = max_tenure_val - min_tenure_val
            gap_pct = (tenure_diff / max_tenure_val * 100) if max_tenure_val > 0 else 0

            other_names = []
            for i in range(1, min(len(df_eval), 4)):
                row_i = df_eval.iloc[i]
                n_i = format_entity_label(row_i[name_col], col_name=name_col, lang="en" if is_en else "vi")
                t_i = f"{float(row_i[tenure_col]):.2f} năm" if tenure_col else ""
                other_names.append(f"**{n_i}** ({t_i})")

            other_str = ", ".join(other_names) if other_names else ""
            second_line_tail = f", tiếp sau là {other_str}" if other_str else ""

            if is_en:
                b1 = f"• **Longest-Tenured Workforce Confirmation**: Verified **{n_emps} veteran personnel** with the longest tenure in the enterprise (ranging from {min_tenure_val:.2f} to {max_tenure_val:.2f} years of service)."
                b2 = f"• **Lead Seniority Contributor**: **{top_name}** holds the longest tenure at **{top_tenure_val:.2f} years**{second_line_tail}."
                b3 = f"• **Organizational Stability & Loyalty Profile**: The veteran cohort averages **{avg_tenure_val:.2f} years** of service with a tight spread of only {gap_pct:.2f}% across the top cohort, confirming exceptional employee loyalty and workforce continuity."
            else:
                b1 = f"• **Xác nhận Top {n_emps} Nhân sự Kỳ cựu & Cống hiến Lâu năm**: Ghi nhận chính xác **{n_emps} nhân sự** có thâm niên công tác lâu nhất tại công ty (từ {min_tenure_val:.2f} đến {max_tenure_val:.2f} năm)."
                b2 = f"• **Nhân sự Dẫn đầu**: **{top_name}** có thâm niên cống hiến cao nhất đạt **{top_tenure_val:.2f} năm**{second_line_tail}."
                b3 = f"• **Độ Gắn Kết & Tính Ổn Định Tổ Chức**: Toàn bộ nhóm nhân sự kỳ cựu duy trì mức thâm niên bình quân **{avg_tenure_val:.2f} năm** (biên độ chênh lệch giữa người cao nhất và thấp nhất trong nhóm chỉ {gap_pct:.2f}%), phản ánh độ gắn bó bền chặt và sự ổn định cao của tổ chức."
            return f"{b1}\n\n{b2}\n\n{b3}"
        except Exception:
            pass

    # 1. SPECIALIZED HANDLER: THÂM NIÊN THẤP & LƯƠNG THUỘC TOP CAO (Talent Outliers / Lateral Senior Hiring)
    has_valid_sal = any(k in cols_str for k in ["salary", "currentsalary", "lương", "annualsalary"])
    is_low_tenure_top_sal = (
        has_valid_sal
        and not is_longest_tenure
        and (
            (
                any(k in q_low for k in ["thâm niên", "tenure", "service", "gắn bó"])
                and any(k in q_low for k in ["dưới 3 năm", "< 3", "ít năm", "mới vào", "mới gia nhập", "under 3", "under 5", "low tenure"])
                and any(k in q_low for k in ["top", "5%", "cao nhất", "highest", "lương", "salary", "ngoại lệ", "outlier"])
            ) or (
                any(k in cols_str for k in ["yearsofservice", "tenure", "thâm niên", "service_years"])
                and any(k in cols_str for k in ["salary", "currentsalary", "lương", "annualsalary"])
                and any(k in q_low for k in ["dưới", "ít hơn", "mới vào", "ngoại lệ"])
                and not any(k in q_low for k in ["nén lương", "compression", "khoảng cách"])
            )
        )
    )
    if is_low_tenure_top_sal:
        try:
            sal_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["salary", "currentsalary", "lương", "annualsalary"])), None)
            tenure_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["yearsofservice", "tenure", "thâm niên", "service_years", "years"])), None)
            name_col = get_best_name_column(df, exclude_cols=[sal_col, tenure_col] if sal_col and tenure_col else None)
            if not name_col:
                name_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["fullname", "full_name", "employeename", "name", "tên", "họ và tên"])), df.columns[0])

            df_eval = df.copy()
            if sal_col:
                df_eval[sal_col] = pd.to_numeric(df_eval[sal_col], errors="coerce").fillna(0)
                df_eval = df_eval.sort_values(by=sal_col, ascending=False)
            if tenure_col:
                df_eval[tenure_col] = pd.to_numeric(df_eval[tenure_col], errors="coerce").fillna(0)

            n_emps = len(df_eval)
            top_emp = df_eval.iloc[0]
            top_name = format_entity_label(top_emp[name_col], col_name=name_col, lang="en" if is_en else "vi")
            top_sal_val = float(top_emp[sal_col]) if sal_col else 0
            top_tenure_val = float(top_emp[tenure_col]) if tenure_col else 0

            min_sal_val = float(df_eval[sal_col].min()) if sal_col else 0
            max_sal_val = float(df_eval[sal_col].max()) if sal_col else 0
            avg_sal_val = float(df_eval[sal_col].mean()) if sal_col else 0
            min_tenure_val = float(df_eval[tenure_col].min()) if tenure_col else 0
            max_tenure_val = float(df_eval[tenure_col].max()) if tenure_col else 0
            avg_tenure_val = float(df_eval[tenure_col].mean()) if tenure_col else 0

            top_sal_fmt = format_metric_value(top_sal_val, sal_col or "salary")
            min_sal_fmt = format_metric_value(min_sal_val, sal_col or "salary")
            max_sal_fmt = format_metric_value(max_sal_val, sal_col or "salary")
            avg_sal_fmt = format_metric_value(avg_sal_val, sal_col or "salary")

            if top_sal_val > 0:
                # Liệt kê các nhân sự tiếp theo
                other_names = []
                for i in range(1, min(len(df_eval), 3)):
                    row_i = df_eval.iloc[i]
                    n_i = format_entity_label(row_i[name_col], col_name=name_col, lang="en" if is_en else "vi")
                    s_i = format_metric_value(float(row_i[sal_col]), sal_col or "salary") if sal_col else ""
                    t_i = f"{float(row_i[tenure_col]):.1f} năm" if tenure_col else ""
                    other_names.append(f"**{n_i}** ({s_i}, thâm niên {t_i})")

                other_str = ", ".join(other_names) if other_names else ""
                second_line_tail = f", tiếp sau là {other_str}" if other_str else ""

                if is_en:
                    b1 = f"• **High-Compensation Talent Outliers**: Formally identified **{n_emps} personnel** with under 3 years of tenure ({min_tenure_val:.1f} - {max_tenure_val:.1f} years) ranking in the company's top 5% compensation bracket ({min_sal_fmt} - {max_sal_fmt})."
                    b2 = f"• **Lead Compensation Outlier**: **{top_name}** commands the highest compensation of **{top_sal_fmt}** with {top_tenure_val:.1f} years of tenure{second_line_tail}."
                    b3 = f"• **Cohort Profile & Total Rewards**: This elite cohort averages {avg_tenure_val:.1f} years of service with an average compensation of **{avg_sal_fmt}**, demonstrating a pay-for-performance and lateral senior hiring model."
                else:
                    b1 = f"• **Xác nhận {n_emps} Nhân sự Ngoại lệ (High-Compensation Outliers)**: Ghi nhận chính xác **{n_emps} nhân sự** có thâm niên dưới 3 năm ({min_tenure_val:.1f} - {max_tenure_val:.1f} năm) nhưng mức lương nằm trong Top 5% cao nhất toàn công ty ({min_sal_fmt} - {max_sal_fmt})."
                    b2 = f"• **Nhân sự Dẫn đầu**: **{top_name}** đạt thu nhập cao nhất **{top_sal_fmt}** (thâm niên {top_tenure_val:.1f} năm){second_line_tail}."
                    b3 = f"• **Mặt bằng & Cơ cấu Đãi ngộ Toàn Nhóm**: Nhóm nhân sự ngoại lệ có thâm niên bình quân {avg_tenure_val:.1f} năm và mức thu nhập trung bình **{avg_sal_fmt}**, phản ánh chính sách đãi ngộ vượt trội cho nhân sự chất lượng cao và thu hút nhân tài từ thị trường (Lateral Senior Hiring)."
                return f"{b1}\n\n{b2}\n\n{b3}"
        except Exception:
            pass

    # 1.5 SPECIALIZED HANDLER: LƯƠNG TRƯỞNG PHÒNG VS CẤP DƯỚI (Manager vs Subordinate Compensation)
    is_mgr_sub_salary_comp = (
        any(k in q_low for k in ["trưởng phòng", "dept_manager", "manager", "quản lý", "quản lí"])
        and any(k in q_low for k in ["cấp dưới", "dưới quyền", "nhân viên", "toàn bộ nhân viên", "trực thuộc"])
        and any(k in q_low for k in ["lương", "salary", "thu nhập", "gấp", "chênh lệch", "cao hơn", "thấp hơn", "so sánh"])
    ) or (
        any("managersalary" in str(c).lower() or "lương quản lý" in str(c).lower() for c in df.columns)
        and any("subordinate" in str(c).lower() or "cấp dưới" in str(c).lower() for c in df.columns)
    )
    if is_mgr_sub_salary_comp:
        try:
            mgr_sal_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["managersalary", "lương quản lý", "lương_quản_lý"])), None)
            sub_sal_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["subordinateavgsalary", "lương tb cấp dưới", "lương_tb_cấp_dưới", "subordinatesalary"])), None)
            dept_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["department", "phòng ban", "dept_name", "dept"])), df.columns[0])
            mgr_name_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["managername", "tên quản lý", "manager"])), None)

            df_eval = df.copy()
            if mgr_sal_col and sub_sal_col:
                df_eval["_ratio"] = pd.to_numeric(df_eval[mgr_sal_col], errors="coerce") / pd.to_numeric(df_eval[sub_sal_col], errors="coerce")
                df_eval = df_eval.sort_values(by="_ratio", ascending=False)
                top_row = df_eval.iloc[0]
                bot_row = df_eval.iloc[-1]
                top_dept = top_row[dept_col]
                top_mgr = top_row[mgr_name_col] if mgr_name_col else "Trưởng phòng"
                top_mgr_s = format_metric_value(float(top_row[mgr_sal_col]), mgr_sal_col)
                top_sub_s = format_metric_value(float(top_row[sub_sal_col]), sub_sal_col)
                top_r = float(top_row["_ratio"])

                bot_dept = bot_row[dept_col]
                bot_mgr = bot_row[mgr_name_col] if mgr_name_col else "Trưởng phòng"
                bot_mgr_s = format_metric_value(float(bot_row[mgr_sal_col]), mgr_sal_col)
                bot_sub_s = format_metric_value(float(bot_row[sub_sal_col]), sub_sal_col)
                bot_r = float(bot_row["_ratio"])

                ratio_m = re.search(r"(?:gấp|hơn|cao hơn|vượt)?\s*([0-9]+(?:\.[0-9]+)?)\s*lần", q_low)
                multiplier_q = float(ratio_m.group(1)) if ratio_m else None
                if multiplier_q is None and "gấp đôi" in q_low:
                    multiplier_q = 2.0

                if multiplier_q and multiplier_q > top_r:
                    if is_en:
                        b1 = f"• **Zero-Match Threshold Audit**: None of the {len(df_eval)} departments exhibit a manager-to-subordinate pay ratio exceeding **{multiplier_q}x**."
                        b2 = f"• **Peak Organizational Ratio**: Department **{top_dept}** holds the highest ratio at **{top_r:.2f}x** (Manager {top_mgr}: {top_mgr_s} vs Staff Avg: {top_sub_s})."
                        b3 = f"• **Inverted Compensation Outliers**: Department **{bot_dept}** ({bot_r:.2f}x, {bot_mgr_s} vs {bot_sub_s}) records an inverted ratio where tenured technical staff out-earn managers."
                    else:
                        b1 = f"• **Xác nhận Kết quả Khảo sát Ngưỡng {multiplier_q} Lần**: Quét toàn bộ {len(df_eval)} phòng ban, **không có phòng ban nào** có mức lương Trưởng phòng vượt gấp {multiplier_q} lần mức lương trung bình của nhân viên cấp dưới."
                        b2 = f"• **Biên độ Chênh lệch Thực tế Cao nhất**: Phòng **{top_dept}** ghi nhận tỷ lệ cao nhất toàn công ty với mức lương Trưởng phòng ({top_mgr}: {top_mgr_s}) chỉ gấp **{top_r:.2f} lần** so với nhân viên ({top_sub_s}, chênh lệch +{((top_r - 1)*100):.1f}%)."
                        b3 = f"• **Hiện tượng Nghịch đảo Đãi ngộ (Inverted Pay)**: Tại phòng **{bot_dept}** ({bot_r:.2f} lần, {bot_mgr_s} so với {bot_sub_s}), mức lương Trưởng phòng hiện tại thấp hơn bình quân nhân viên cấp dưới do yếu tố tích lũy thâm niên chuyên gia."
                    return f"{b1}\n\n{b2}\n\n{b3}"
                else:
                    if is_en:
                        b1 = f"• **Management Compensation Spread**: Manager vs subordinate salary ratios range from {bot_r:.2f}x (**{bot_dept}**) to {top_r:.2f}x (**{top_dept}**)."
                        b2 = f"• **Lead Premium Department**: Department **{top_dept}** provides the highest leadership premium ({top_r:.2f}x, Manager: {top_mgr_s} vs Staff: {top_sub_s})."
                        b3 = f"• **Compensation Balance**: Internal pay equity is maintained within normal executive bounds across operations."
                    else:
                        b1 = f"• **Phân hóa Thu nhập Quản lý và Cấp dưới**: Tỷ lệ lương Trưởng phòng so với cấp dưới dao động từ {bot_r:.2f} lần (**{bot_dept}**) đến {top_r:.2f} lần (**{top_dept}**)."
                        b2 = f"• **Phòng ban Có Phụ cấp Quản lý Cao nhất**: Phòng **{top_dept}** ghi nhận mức thù lao lãnh đạo cao nhất ({top_r:.2f} lần, {top_mgr}: {top_mgr_s} so với cấp dưới {top_sub_s})."
                        b3 = f"• **Đánh giá Cấu trúc Bậc lương**: Khoảng cách đãi ngộ giữa cấp quản trị và chuyên viên duy trì trong biên độ ổn định toàn doanh nghiệp."
                    return f"{b1}\n\n{b2}\n\n{b3}"
        except Exception:
            pass

    # 2. SPECIALIZED HANDLER: NÉN LƯƠNG / SO SÁNH BẬC LƯƠNG (Wage Compression)
    is_wage_compression = (
        any(k in q_low for k in ["nén lương", "wage compression", "salary compression", "nén thu nhập"])
        or (
            any(k in q_low for k in ["thâm niên", "tenure", "kinh nghiệm", "năm"])
            and any(k in q_low for k in ["chênh lệch", "khoảng cách", "so sánh", "spread", "gap", "bậc lương"])
            and any(k in q_low for k in ["lương", "salary", "thu nhập"])
        )
    )
    if is_wage_compression:
        try:
            measure_cols, cat_cols, _ = get_axis_columns(df)
            val_col, name_col = select_primary_insight_columns(df, user_query=user_query)
            if not val_col:
                val_col = measure_cols[0] if measure_cols else None
            if not name_col:
                name_col = cat_cols[0] if cat_cols else df.columns[0]

            df_eval = df.copy()
            df_eval[val_col] = pd.to_numeric(df_eval[val_col], errors="coerce").fillna(0)
            sorted_df = df_eval.sort_values(by=val_col, ascending=False)
            top_row = sorted_df.iloc[0]
            bot_row = sorted_df.iloc[-1]
            top_name = format_entity_label(top_row[name_col], col_name=name_col, lang="en" if is_en else "vi")
            top_val = float(top_row[val_col])
            bot_name = format_entity_label(bot_row[name_col], col_name=name_col, lang="en" if is_en else "vi")
            bot_val = float(bot_row[val_col])
            spread_diff = top_val - bot_val
            median_val = float(df_eval[val_col].median())

            if is_en:
                b1 = f"• **Wage Compression Analysis**: Compensation spread across cohorts ranges from {format_metric_value(bot_val, val_col)} (**{bot_name}**) to {format_metric_value(top_val, val_col)} (**{top_name}**), with an absolute spread of {format_metric_value(spread_diff, val_col)}."
                b2 = f"• **Tenure Progression Differential**: Minimal pay gap between tenured and newly hired personnel highlights significant wage compression within the analyzed group."
                b3 = f"• **Benchmark Median**: Cohort median compensation stands at {format_metric_value(median_val, val_col)}, outlining the organizational reference baseline."
            else:
                b1 = f"• **Đánh giá Hiện tượng Nén Lương**: Biên độ thu nhập giữa các nhóm dao động từ {format_metric_value(bot_val, val_col)} (**{bot_name}**) đến {format_metric_value(top_val, val_col)} (**{top_name}**), với khoảng cách chênh lệch {format_metric_value(spread_diff, val_col)}."
                b2 = f"• **Mức độ Phân tầng Theo Thâm niên**: Khoảng cách thu nhập thu hẹp giữa nhân sự lâu năm và nhân sự mới gia nhập thể hiện hiện tượng nén lương (Wage Compression) cần được tối ưu."
                b3 = f"• **Mức Thu nhập Trung vị Tham chiếu**: Thu nhập trung vị của toàn bộ nhóm phân tích đạt {format_metric_value(median_val, val_col)}, thiết lập đường cơ sở chuẩn cho việc tái cơ cấu bậc lương."
            return f"{b1}\n\n{b2}\n\n{b3}"
        except Exception:
            pass

    # 3. STANDARD PATH: TIME SERIES, PARETO, MARGIN, OR GENERAL ENTITY
    measure_cols, cat_cols, time_col = get_axis_columns(df)
    val_col, name_col = select_primary_insight_columns(df, user_query=user_query)
    if not val_col:
        val_col = measure_cols[0] if measure_cols else None
    if not val_col:
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            val_col = num_cols[0]

    spread_candidate = next((c for c in df.columns if any(k in str(c).lower() for k in ["salaryspread", "salary_spread", "chênh lệch lương", "khoảng cách lương"])), None)
    if spread_candidate:
        val_col = spread_candidate

    time_col = find_time_column(df)
    is_time_series = (
        time_col is not None
        and not any(k in str(time_col).lower() for k in ["service", "tenure", "thâm niên", "tham_nien", "experience", "kinh nghiệm", "age", "tuoi"])
        and (
            any(k in q_low for k in ["qua các năm", "theo năm", "từng năm", "over time", "per year", "over the years", "yearly", "xu hướng", "trend", "biến động", "thay đổi như thế nào", "qua thời gian", "theo tháng", "từng tháng", "mỗi tháng", "hàng tháng", "theo quý", "từng quý"])
            or detect_analysis_entity_type(df, user_query=user_query) == "time_series"
        )
    )
    t_col = time_col

    if is_time_series and t_col and val_col and t_col != val_col:
        try:
            df_eval = df.copy()
            df_eval[val_col] = pd.to_numeric(df_eval[val_col], errors="coerce").fillna(0)
            peak_row = df_eval.loc[df_eval[val_col].idxmax()]
            min_row = df_eval.loc[df_eval[val_col].idxmin()]
            peak_t = format_entity_label(peak_row[t_col], col_name=t_col, lang="en" if is_en else "vi")
            peak_v = float(peak_row[val_col])
            min_t = format_entity_label(min_row[t_col], col_name=t_col, lang="en" if is_en else "vi")
            min_v = float(min_row[val_col])
            mean_val = float(df_eval[val_col].mean())
            peak_str = f"**{peak_t}**" if any(peak_t.lower().startswith(k) for k in ["tháng", "quý", "năm"]) else f"Giai đoạn **{peak_t}**"
            min_str = f"**{min_t}**" if any(min_t.lower().startswith(k) for k in ["tháng", "quý", "năm"]) else f"Giai đoạn **{min_t}**"
            peak_str_en = f"**{peak_t}**" if any(peak_t.lower().startswith(k) for k in ["month", "quarter", "year"]) else f"Period **{peak_t}**"
            min_str_en = f"**{min_t}**" if any(min_t.lower().startswith(k) for k in ["month", "quarter", "year"]) else f"Period **{min_t}**"
            if is_en:
                return (
                    f"• **Historical Peak**: {peak_str_en} reached the all-time peak ({format_metric_value(peak_v, val_col)}), reflecting maximum capacity scale.\n\n"
                    f"• **Baseline Trough**: {min_str_en} marked the lowest point ({format_metric_value(min_v, val_col)}), showing an overall gap of {format_metric_value(abs(peak_v - min_v), val_col)} from the peak.\n\n"
                    f"• **Period Benchmark Average**: Multi-year baseline average stands at {format_metric_value(mean_val, val_col)}, outlining long-term operational equilibrium."
                )
            else:
                return (
                    f"• **Thời điểm Đạt đỉnh**: {peak_str} ghi nhận mức cao nhất toàn chu kỳ ({format_metric_value(peak_v, val_col)}), thể hiện quy mô vận hành lớn nhất.\n\n"
                    f"• **Thời điểm Mức sàn**: {min_str} ở mức thấp nhất ({format_metric_value(min_v, val_col)}), chênh lệch {format_metric_value(abs(peak_v - min_v), val_col)} so với đỉnh.\n\n"
                    f"• **Mặt bằng Bình quân Chu kỳ**: Mức trung bình qua các kỳ là {format_metric_value(mean_val, val_col)}, tạo đường cơ sở ổn định dài hạn."
                )
        except Exception:
            pass

    if val_col:
        if not name_col:
            name_candidates = [c for c in cat_cols if c != val_col] or [c for c in df.columns if c != val_col]
            name_col = name_candidates[0] if name_candidates else None
        if name_col:
            try:
                df_eval = df.copy()
                df_eval[val_col] = pd.to_numeric(df_eval[val_col], errors="coerce").fillna(0)
                sorted_df = df_eval.sort_values(by=val_col, ascending=False)
                top_row = sorted_df.iloc[0]
                bot_row = sorted_df.iloc[-1]
                top_name = format_entity_label(top_row[name_col], col_name=name_col, lang="en" if is_en else "vi")
                top_val = float(top_row[val_col])
                bot_name = format_entity_label(bot_row[name_col], col_name=name_col, lang="en" if is_en else "vi")
                bot_val = float(bot_row[val_col])
                gap_vs_top = ((top_val - bot_val) / top_val * 100) if top_val > 0 else 0
                median_val = float(df_eval[val_col].median())
                is_salary = any(k in str(val_col).lower() for k in ["salary", "lương", "wage", "pay", "thu_nhập"])
                med_label = "Thu nhập trung vị" if is_salary else "Quy mô trung vị"

                is_pareto = any(k in str(c).lower() for c in df.columns for k in ["cumulative", "tích lũy", "tich_luy", "runningtotal"]) or any(k in q_low for k in ["pareto", "80/20", "80%", "80-20", "tích lũy", "cumulative"])
                pct_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["percentage", "tỷ trọng", "tỉ trọng", "pct", "percent"]) and not any(k in str(c).lower() for k in ["cumulative", "tích lũy", "tich_luy"])), None)
                cum_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["cumulative", "tích lũy", "tich_luy"])), None)

                if len(df) == 1:
                    has_max_min = any("max" in str(c).lower() for c in df.columns) and any("min" in str(c).lower() for c in df.columns)
                    if has_max_min:
                        max_c = next((c for c in df.columns if "max" in str(c).lower()), None)
                        min_c = next((c for c in df.columns if "min" in str(c).lower()), None)
                        max_v_fmt = format_metric_value(float(df[max_c].iloc[0]), max_c)
                        min_v_fmt = format_metric_value(float(df[min_c].iloc[0]), min_c)
                        val_fmt = format_metric_value(top_val, val_col)
                        if is_en:
                            return (
                                f"• **Leading Entity**: **{top_name}** exhibits the organization's largest salary spread of **{val_fmt}**.\n\n"
                                f"• **Internal Compensation Range**: Peak compensation reaches **{max_v_fmt}**, against a base floor of **{min_v_fmt}**.\n\n"
                                f"• **Structural Evaluation**: This wide variance highlights significant pay progression between entry levels and senior specialists."
                            )
                        else:
                            return (
                                f"• **Đơn vị Dẫn đầu**: Phòng ban **{top_name}** ghi nhận mức chênh lệch lương nội bộ lớn nhất toàn tổ chức với **{val_fmt}**.\n\n"
                                f"• **Biên độ Thu nhập Nội bộ**: Mức lương cao nhất tại phòng đạt **{max_v_fmt}**, trong khi mức lương sàn là **{min_v_fmt}**.\n\n"
                                f"• **Đánh giá Cấu trúc**: Khoảng cách thu nhập thể hiện chính sách phân tầng đãi ngộ rõ nét giữa cấp bậc chuyên môn và đội ngũ quản trị."
                            )
                    else:
                        val_fmt = format_metric_value(top_val, val_col)
                        if is_en:
                            return f"• **Target Entity**: **{top_name}** recorded at **{val_fmt}**, representing the primary metric extracted from the inquiry."
                        else:
                            return f"• **Thực thể Trọng tâm**: **{top_name}** đạt mức **{val_fmt}**, là chỉ số trọng tâm theo yêu cầu của câu hỏi điều hành."
                elif is_pareto:
                    top_pct_str = f" ({format_metric_value(top_row[pct_col], pct_col)} tổng doanh số)" if (pct_col and pct_col in top_row) else ""
                    cum_val = df[cum_col].iloc[-1] if cum_col else None
                    cum_str = format_metric_value(cum_val, cum_col) if cum_val is not None else "xấp xỉ 80%"
                    n_items = len(df)
                    if is_en:
                        b1 = f"• **Pareto Revenue Leader**: Product **{top_name}** commands the #1 position ({format_metric_value(top_val, val_col)}{top_pct_str}), acting as the primary revenue locomotive."
                        b2 = f"• **Cumulative Contribution (Pareto 80/20)**: Top {n_items} products account for a cumulative **{cum_str}** of total sales, demonstrating high revenue concentration in core SKUs."
                        b3 = f"• **Benchmark Median**: Core group median scale stands at {format_metric_value(median_val, val_col)}, establishing a baseline for inventory planning."
                        return f"{b1}\n\n{b2}\n\n{b3}"
                    else:
                        b1 = f"• **Dẫn đầu Doanh số Nhóm Pareto**: Sản phẩm **{top_name}** chiếm vị trí quán quân ({format_metric_value(top_val, val_col)}{top_pct_str}), giữ vai trò đầu tàu dẫn dắt doanh thu danh mục."
                        b2 = f"• **Tỷ lệ Đóng góp Tích lũy (Pareto 80/20)**: Top {n_items} sản phẩm trong nhóm đóng góp tích lũy **{cum_str}** tổng doanh số, khẳng định mức độ tập trung doanh thu cốt lõi vào nhóm sản phẩm chủ lực."
                        b3 = f"• **Mặt bằng Chuẩn Toàn Danh mục (Benchmark Median)**: Quy mô trung vị của nhóm chủ lực là {format_metric_value(median_val, val_col)}, thiết lập đường cơ sở chuẩn cho kế hoạch cung ứng và tồn kho."
                        return f"{b1}\n\n{b2}\n\n{b3}"
                else:
                    is_margin = (any(k in str(val_col).lower() for k in ["margin", "tỷ suất", "tỉ suất", "gross_margin", "profit_margin"]) or any(k in q_low for k in ["tỷ suất", "tỉ suất lợi nhuận", "gross margin", "profit margin"]))
                    tradeoff_line = detect_tradeoff_insight(df, name_col, val_col, is_en=is_en)
                    if is_margin:
                        if is_en:
                            b1 = f"• **Gross Margin Leader**: Group **{top_name}** commands the highest margin ({format_metric_value(top_val, val_col)}), indicating an optimized COGS cost structure per unit."
                            b2 = tradeoff_line if tradeoff_line else (
                                f"• **Margin Spread**: Standing {gap_vs_top:.1f}% above {bot_name} ({format_metric_value(bot_val, val_col)}), demonstrating strong pricing resilience across top tiers."
                                if (bot_name != top_name and gap_vs_top >= 0.01) else
                                f"• **Margin Stability**: Maintained consistent profitability benchmark across recorded operations."
                            )
                            b3 = f"• **Benchmark Median**: Portfolio median margin stands at {format_metric_value(median_val, val_col)}, establishing a solid profitability baseline."
                            return f"{b1}\n\n{b2}\n\n{b3}"
                        else:
                            b1 = f"• **Dẫn đầu Biên Lợi nhuận (Gross Margin Leader)**: Nhóm **{top_name}** đạt tỷ suất cao nhất ({format_metric_value(top_val, val_col)}), khẳng định lợi thế tối ưu hóa chi phí giá vốn (COGS) trên từng đơn vị sản phẩm."
                            b2 = tradeoff_line if tradeoff_line else (
                                f"• **Biên độ Phân hóa**: Duy trì khoảng cách {gap_vs_top:.1f}% so với nhóm thấp nhất ({bot_name}: {format_metric_value(bot_val, val_col)}), cho thấy toàn bộ danh mục duy trì kỷ luật định giá cao."
                                if (bot_name != top_name and gap_vs_top >= 0.01) else
                                f"• **Độ Ổn định Biên Lợi nhuận**: Duy trì tỷ suất lợi nhuận đồng đều và kỷ luật định giá cao."
                            )
                            b3 = f"• **Mặt bằng Chuẩn Toàn Danh mục (Benchmark Median)**: Tỷ suất lợi nhuận trung vị toàn bảng là {format_metric_value(median_val, val_col)}, phản ánh biên an toàn tài chính vững chắc."
                            return f"{b1}\n\n{b2}\n\n{b3}"
                    else:
                        detected_ent = detect_analysis_entity_type(df, user_query=user_query, name_col=name_col)
                        if detected_ent == "department":
                            ent_pfx_vi = "Phòng ban"
                            ent_pfx_en = "Department"
                        elif detected_ent == "title":
                            ent_pfx_vi = "Chức danh"
                            ent_pfx_en = "Job Title"
                        elif detected_ent == "gender":
                            ent_pfx_vi = "Giới tính"
                            ent_pfx_en = "Gender"
                        elif detected_ent == "geo":
                            ent_pfx_vi = "Thị trường"
                            ent_pfx_en = "Market"
                        elif detected_ent == "team":
                            ent_pfx_vi = "Đội ngũ"
                            ent_pfx_en = "Team"
                        elif detected_ent == "product":
                            ent_pfx_vi = "Sản phẩm"
                            ent_pfx_en = "Product"
                        elif detected_ent == "employee":
                            ent_pfx_vi = "Nhân sự"
                            ent_pfx_en = "Personnel"
                        else:
                            ent_pfx_vi = "Nhóm"
                            ent_pfx_en = "Group"

                        is_discrete_count = (top_val <= 5 and float(top_val).is_integer()) or bot_val == 0 or any(k in str(val_col).lower() for k in ["count", "số lượng", "headcount", "manager", "total", "lượt"])

                        if is_en:
                            if bot_name != top_name:
                                if bot_val == 0 or is_discrete_count:
                                    spread_line = f"• **Distribution by Unit**: {ent_pfx_en} **{bot_name}** records {format_metric_value(bot_val, val_col)} (compared to {format_metric_value(top_val, val_col)} in leader **{top_name}**).\n\n"
                                elif gap_vs_top < 1.0:
                                    spread_line = f"• **Near-Absolute Parity (Random Noise)**: {ent_pfx_en} **{bot_name}** records {format_metric_value(bot_val, val_col)} (variance of only {gap_vs_top:.2f}% vs {ent_pfx_en.lower()} **{top_name}**: {format_metric_value(top_val, val_col)}, representing balanced parity and statistical random variance).\n\n"
                                elif gap_vs_top <= 5.0:
                                    spread_line = f"• **Minor Controlled Fluctuation**: {ent_pfx_en} **{bot_name}** stands at {format_metric_value(bot_val, val_col)} ({gap_vs_top:.1f}% lower than {ent_pfx_en.lower()} leader **{top_name}**, well within acceptable variance thresholds).\n\n"
                                else:
                                    spread_line = f"• **Distribution Spread**: {ent_pfx_en} **{bot_name}** stands at {format_metric_value(bot_val, val_col)} ({gap_vs_top:.1f}% lower than {ent_pfx_en.lower()} leader **{top_name}**).\n\n"
                                return (
                                    f"• **Leading Position**: {ent_pfx_en} **{top_name}** achieved the top level ({format_metric_value(top_val, val_col)}), demonstrating primary contribution.\n\n"
                                    f"{spread_line}"
                                    f"• **Reference Median**: Overall median benchmark is {format_metric_value(median_val, val_col)}, representing organizational baseline."
                                )
                            else:
                                return (
                                    f"• **Target Metric**: {ent_pfx_en} **{top_name}** recorded at {format_metric_value(top_val, val_col)}, representing the primary operational scale.\n\n"
                                    f"• **Baseline Reference**: Benchmark baseline is {format_metric_value(median_val, val_col)}.\n\n"
                                    f"• **Operational Evaluation**: Performance reflects focused resource execution within {ent_pfx_en.lower()} **{top_name}**."
                                )
                        else:
                            if bot_name != top_name:
                                if bot_val == 0 or is_discrete_count:
                                    spread_line = f"• **Phân bổ Theo Đơn vị**: {ent_pfx_vi} **{bot_name}** ghi nhận mức {format_metric_value(bot_val, val_col)} (so với {format_metric_value(top_val, val_col)} tại {ent_pfx_vi.lower()} dẫn đầu **{top_name}**).\n\n"
                                elif gap_vs_top < 1.0:
                                    spread_line = f"• **Độ Cân Bằng Tuyệt Đối (Sai số ngẫu nhiên)**: {ent_pfx_vi} **{bot_name}** ghi nhận {format_metric_value(bot_val, val_col)} (chênh lệch chỉ {gap_vs_top:.2f}% so với {ent_pfx_vi.lower()} **{top_name}**: {format_metric_value(top_val, val_col)}, phản ánh trạng thái bình đẳng hoàn hảo và sai số thống kê ngẫu nhiên).\n\n"
                                elif gap_vs_top <= 5.0:
                                    spread_line = f"• **Biến Động Nhẹ trong Ngưỡng Kiểm Soát**: {ent_pfx_vi} **{bot_name}** ở mức {format_metric_value(bot_val, val_col)} (thấp hơn {gap_vs_top:.1f}% so với {ent_pfx_vi.lower()} dẫn đầu **{top_name}**, nằm hoàn toàn trong biên độ ổn định).\n\n"
                                else:
                                    spread_line = f"• **Biên độ Phân hóa**: {ent_pfx_vi} **{bot_name}** ở mức {format_metric_value(bot_val, val_col)} (thấp hơn {gap_vs_top:.1f}% so với {ent_pfx_vi.lower()} dẫn đầu **{top_name}**).\n\n"
                                return (
                                    f"• **Dẫn đầu Toàn diện**: {ent_pfx_vi} **{top_name}** đạt mức cao nhất ({format_metric_value(top_val, val_col)}), giữ vai trò đóng góp chủ lực.\n\n"
                                    f"{spread_line}"
                                    f"• **Mức trung vị tham chiếu**: {med_label} toàn bảng là {format_metric_value(median_val, val_col)}, phản ánh mặt bằng chung ổn định."
                                )
                            else:
                                return (
                                    f"• **Thực thể Trọng tâm**: {ent_pfx_vi} **{top_name}** đạt mức {format_metric_value(top_val, val_col)}, giữ vai trò trọng tâm trong phân tích.\n\n"
                                    f"• **Mức tham chiếu Chuẩn**: Mức chuẩn ghi nhận là {format_metric_value(median_val, val_col)}.\n\n"
                                    f"• **Đánh giá Vận hành**: Kết quả phản ánh sự tập trung nguồn lực và năng lực thực thi hiệu quả tại {ent_pfx_vi.lower()} **{top_name}**."
                                )
            except Exception:
                pass
    return ""


def split_insight_sections(markdown_text: str, df: pd.DataFrame = None, user_query: str = "", is_en: bool = False) -> dict[str, str]:
    """Bóc tách nội dung insight thành 3 phần riêng biệt để hiển thị dạng 3 Card UI chuyên nghiệp."""
    q_low = (user_query or "").lower()
    if not markdown_text:
        # Nếu không có text (chạy Ollama cục bộ hoặc fallback), tự động sinh đầy đủ 3 phần từ dữ liệu thực tế bám sát câu hỏi
        part_21 = generate_data_grounded_anomaly(df, user_query=user_query, is_en=is_en) if (df is not None and not df.empty) else ""
        part_22 = generate_data_grounded_hypotheses(df, user_query=user_query, is_en=is_en) if (df is not None and not df.empty) else ""
        part_23 = generate_data_grounded_action_plan(df, is_en=is_en, user_query=user_query) if (df is not None and not df.empty) else ""
        return {
            "anomaly": escape_markdown_currency_symbols(part_21),
            "hypothesis": escape_markdown_currency_symbols(part_22),
            "action_plan": escape_markdown_currency_symbols(part_23),
        }

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
        part_21 = generate_data_grounded_anomaly(df, user_query=user_query, is_en=is_en)

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
            clean_body = repair_truncated_text(clean_body, is_en=is_en)

            clean_low = l.lower()
            if "duy trì ổn định" in clean_low or "bình đẳng tuyệt đối" in clean_low or "maintain stability" in clean_low or "tôn vinh" in clean_low or "ổn định" in clean_low and ("0 - 30" in clean_low or "0-30" in clean_low):
                l = f"• 🟢 **[{'Maintain Stability / 0-30 Days' if is_en else 'Duy Trì Ổn Định / 0 - 30 Ngày'}]**: {clean_body}"
            elif "theo dõi định kỳ" in clean_low or "theo dõi" in clean_low or "routine monitoring" in clean_low:
                l = f"• 🟡 **[{'Routine Monitoring / 0-30 Days' if is_en else 'Theo Dõi Định Kỳ / 0 - 30 Ngày'}]**: {clean_body}"
            elif "ưu tiên cao" in clean_low or "cấp bách" in clean_low or "thực hiện ngay" in clean_low or "can thiệp ngay" in clean_low or "high priority" in clean_low or "immediate" in clean_low:
                if any(c in clean_body for c in ["🟡", "🟢"]) or len(clean_body) < 15:
                    clean_body = "Rà soát chính sách đãi ngộ và kiểm soát tức thời các điểm bất thường vận hành." if not is_en else "Review compensation policy and manage operational anomalies immediately."
                l = f"• 🔴 **[{'High Priority - Immediate / 0-30 Days' if is_en else 'Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày'}]**: {clean_body}"
            elif "ưu tiên trung bình" in clean_low or "trung hạn" in clean_low or "quý tiếp theo" in clean_low or "1 - 3 quý" in clean_low or "1-3 quarters" in clean_low or "medium priority" in clean_low or "tactical" in clean_low or "giám sát" in clean_low or "rà soát nội bộ" in clean_low:
                if any(c in clean_body for c in ["🔴", "🟢"]) or len(clean_body) < 15:
                    clean_body = "Tối ưu hóa quy trình phân bổ nguồn lực và chuẩn hóa định mức ngân sách theo thực tế." if not is_en else "Optimize resource allocation workflows and standardize baseline budgets."
                l = f"• 🟡 **[{'Medium Priority - Tactical / Next 1-3 Quarters' if is_en else 'Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới'}]**: {clean_body}"
            elif "ưu tiên thấp" in clean_low or "dài hạn" in clean_low or "chiến lược" in clean_low or "1 - 3 năm" in clean_low or "1-3 years" in clean_low or "low priority" in clean_low or "long-term" in clean_low or "bền vững" in clean_low:
                if any(c in clean_body for c in ["🔴", "🟡"]) or len(clean_body) < 15:
                    clean_body = "Hoàn thiện chính sách tổng thể, đẩy mạnh chuyển đổi số và nâng cao năng lực cạnh tranh dài hạn." if not is_en else "Overhaul total rewards framework and strengthen long-term competitiveness."
                l = f"• 🟢 **[{'Low Priority / Long-term Strategy / 1-3 Years' if is_en else 'Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm'}]**: {clean_body}"
            elif not l.startswith("•"):
                l = f"• {l}"

            # Sửa câu bị cụt lửng ở đuôi
            l = repair_truncated_text(l, is_en=is_en)
            cleaned_23.append(l)

        # Luôn đảm bảo đúng 3 gạch đầu dòng chuẩn mực theo 3 cấp độ thời gian mà không bị ghi đè lẫn nhau
        if len(cleaned_23) >= 2:
            tier1_match = next((l for l in cleaned_23 if any(tag in l for tag in ["0 - 30 Ngày", "0-30 Days", "Cấp Bách", "Duy Trì Ổn Định", "Theo Dõi", "High Priority", "Maintain Stability", "Routine Monitoring"])), None)
            tier2_match = next((l for l in cleaned_23 if any(tag in l for tag in ["1 - 3 Quý", "1-3 Quarters", "Trung Hạn", "Medium Priority", "Tactical"])), None)
            tier3_match = next((l for l in cleaned_23 if any(tag in l for tag in ["1 - 3 Năm", "1-3 Years", "Dài Hạn", "Low Priority", "Long-term", "Chiến Lược Bền Vững"])), None)

            def_tier1 = "• 🔴 **[Cấp Bách - Can thiệp Ngay / 0 - 30 Ngày]**: Rà soát chính sách đãi ngộ và kiểm soát tức thời các điểm bất thường vận hành." if not is_en else "• 🔴 **[High Priority - Immediate / 0-30 Days]**: Review compensation policy and manage operational anomalies immediately."
            def_tier2 = "• 🟡 **[Trung Hạn - Tối ưu Hóa / 1 - 3 Quý Tới]**: Tối ưu hóa quy trình phân bổ nguồn lực và chuẩn hóa định mức ngân sách theo thực tế." if not is_en else "• 🟡 **[Medium Priority - Tactical / Next 1-3 Quarters]**: Optimize resource allocation workflows and standardize baseline budgets."
            def_tier3 = "• 🟢 **[Dài Hạn - Chiến Lược Bền Vững / 1 - 3 Năm]**: Hoàn thiện chính sách tổng thể, đẩy mạnh chuyển đổi số và nâng cao năng lực cạnh tranh dài hạn." if not is_en else "• 🟢 **[Low Priority / Long-term Strategy / 1-3 Years]**: Overhaul total rewards framework and strengthen long-term competitiveness."

            tier1 = tier1_match or cleaned_23[0] or def_tier1
            tier2 = tier2_match or (cleaned_23[1] if len(cleaned_23) > 1 and cleaned_23[1] != tier1 else def_tier2)
            tier3 = tier3_match or (cleaned_23[2] if len(cleaned_23) > 2 and cleaned_23[2] not in (tier1, tier2) else def_tier3)
            part_23 = f"{tier1}\n\n{tier2}\n\n{tier3}"
        elif df is not None and not df.empty:
            part_23 = generate_data_grounded_action_plan(df, is_en=is_en, user_query=user_query)

    if not part_23 and df is not None and not df.empty:
        part_23 = generate_data_grounded_action_plan(df, is_en=is_en, user_query=user_query)

    # Kiểm soát kỷ luật phân loại đối tượng (Entity Context Rule & Seasonality Rule):
    cols_str = " ".join(str(c).lower() for c in df.columns) if (df is not None and not df.empty) else ""
    t_col = find_time_column(df) if (df is not None and not df.empty) else None
    if t_col and any(k in str(t_col).lower() for k in ["service", "tenure", "thâm niên", "tham_nien", "experience", "kinh nghiệm", "age", "tuoi"]):
        t_col = None
    is_time_series = (
        (t_col is not None or any(k in q_low for k in ["qua các năm", "theo năm", "từng năm", "over time", "per year", "over the years", "yearly", "xu hướng", "trend", "biến động", "thay đổi như thế nào", "qua thời gian", "theo tháng", "từng tháng", "mỗi tháng", "hàng tháng", "theo quý", "từng quý"]))
        and not any(k in q_low for k in ["dưới 3 năm", "thâm niên", "tenure", "5%"])
    )
    entity_type = detect_analysis_entity_type(df, user_query=user_query) if (df is not None and not df.empty) else ("time_series" if is_time_series else None)
    if entity_type == "geo":
        # 1. Regex sửa đổi nhầm lẫn danh xưng: 'đội ngũ New Zealand' -> 'thị trường New Zealand'
        geo_fix_regex = r"(?i)\b(?:đội ngũ|nhóm|team|squad|group)\s+(New Zealand|USA|Canada|India|UK|Australia|Ấn Độ|Mỹ|Vương quốc Anh|Úc)\b"
        part_21 = re.sub(geo_fix_regex, r"thị trường \1", part_21)
        part_22 = re.sub(geo_fix_regex, r"thị trường \1", part_22)
        part_23 = re.sub(geo_fix_regex, r"thị trường \1", part_23)

        # 2. Rà soát từ cấm cho Thị trường / Quốc gia: TUYỆT ĐỐI KHÔNG dùng hoa hồng, thưởng nóng, incentive, coaching, chốt hợp đồng, thi đua, xả hàng
        geo_forbidden_terms = [
            "hoa hồng", "thưởng nóng", "incentive", "chốt hợp đồng", "chốt sales", "kỹ năng chốt",
            "đào tạo kỹ năng", "coaching", "sales contest", "thi đua", "xả hàng", "hết hạn sử dụng",
            "salesperson", "chia sẻ best-practice", "best-practice sharing", "kỷ luật bán hàng"
        ]
        if any(term in part_23.lower() for term in geo_forbidden_terms):
            part_23 = generate_data_grounded_action_plan(df, is_en=is_en, user_query=user_query)

        geo_hypo_forbidden = ["kỹ năng chốt", "chốt hợp đồng", "chốt sales", "kỷ luật bán hàng của đội ngũ", "kỷ luật thực thi kinh doanh"]
        if any(term in part_22.lower() for term in geo_hypo_forbidden):
            part_22 = generate_data_grounded_hypotheses(df, user_query=user_query, is_en=is_en)

    elif entity_type in ["team", "employee", "department", "title"]:
        # TUYỆT ĐỐI KHÔNG dùng từ "xả hàng", "hết hạn sử dụng", "combo", "bao bì", "sáp nhập", "chu kỳ bán hàng" khi đối tượng là Đội ngũ/Nhân sự/Phòng ban
        forbidden_terms = [
            "xả hàng", "hạn sử dụng", "hết hạn", "combo", "đóng gói ưu đãi", "bao bì", "hàng tồn kho", 
            "vòng quay tồn kho", "vòng quay hàng tồn kho", "stock clearance", "expiration date", "shelf life",
            "chu kỳ bán hàng/hoạt động", "sáp nhập các đơn vị lớn", "giai đoạn 2.8"
        ]
        if any(term in part_23.lower() for term in forbidden_terms):
            part_23 = generate_data_grounded_action_plan(df, is_en=is_en, user_query=user_query)
        if any(term in part_22.lower() for term in ["sáp nhập các đơn vị lớn", "chu kỳ bán hàng", "giai đoạn 2.8"]):
            part_22 = generate_data_grounded_hypotheses(df, user_query=user_query, is_en=is_en)
        if any(term in part_21.lower() for term in ["giai đoạn 2.8", "thời điểm đạt đỉnh: giai đoạn"]):
            part_21 = generate_data_grounded_anomaly(df, user_query=user_query, is_en=is_en)

    elif entity_type == "time_series" or is_time_series:
        # 1. Làm sạch nhãn tháng/thời gian thô như "Điểm '3.0'", "Giai đoạn 3", "(8)", "(9)", v.v.
        def clean_time_labels(text: str) -> str:
            if not text:
                return text
            text = re.sub(r"(?i)\bĐiểm\s*['\"]?(\d{1,2})(?:\.0)?['\"]?\b", r"Tháng \1", text)
            text = re.sub(r"(?i)\bGiai đoạn\s+([1-9]|1[0-2])\b", r"Tháng \1", text)
            text = re.sub(r"(?<=\s)\(([1-9]|1[0-2])\)", r"(Tháng \1)", text)
            text = re.sub(r"\b([1-9]|1[0-2])\.0\b", r"\1", text)
            return text

        part_21 = clean_time_labels(part_21)
        part_22 = clean_time_labels(part_22)
        part_23 = clean_time_labels(part_23)

        # 2. Rà soát câu từ sáo rỗng chung chung cho chuỗi thời gian -> thay bằng action plan mùa vụ bán lẻ
        time_cliches = [
            "tổ chức đối thoại với các đơn vị liên quan",
            "kiểm soát rủi ro gián đoạn vận hành",
            "hoạch định dự báo nhu cầu bằng ai",
            "coordinate with operations to mitigate delivery bottlenecks",
            "transition from reactive adjustments to ai-driven predictive demand planning"
        ]
    # 4. Hậu xử lý chuẩn hóa CFO, loại bỏ hoàn toàn các so sánh phần trăm ngô nghê và sửa lỗi danh xưng
    dept_names = ["Sales", "Marketing", "Human Resources", "Production", "Development", "Quality Management", "Research", "Finance", "Customer Service"]
    dept_pattern = r"(?i)\bnhân sự\s+(" + "|".join(dept_names) + r")\b"

    def clean_cfo_artifacts(text: str) -> str:
        if not text:
            return text
        # Sửa "Nhân sự Sales" -> "Phòng ban Sales"
        text = re.sub(dept_pattern, r"Phòng ban \1", text)
        # Loại bỏ các so sánh ngô nghê "thấp hơn 100.0%" hoặc "thấp hơn 0.0%"
        text = re.sub(r"\s*\((?:thấp|kém|nhỏ|ít) hơn 100(?:\.0)?% so với [^\)]+\)", "", text)
        text = re.sub(r"\s*(?:thấp|kém|nhỏ|ít) hơn 100(?:\.0)?% so với [^\,\.\n\)]+", "", text)
        text = re.sub(r"(?:thấp|kém|nhỏ|ít) hơn 0(?:\.0)?% so với [^\,\.\n\)]+", "ở mức tương đương so với chuẩn dẫn đầu", text)
        # Sửa "thấp hơn 0.0%" độc lập
        text = re.sub(r"thấp hơn 0(?:\.0)?%", "ở mức tương đương", text)
        # Sửa khoảng trắng thừa hoặc ngoặc rỗng do regex tạo ra
        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        # BẮT BUỘC: Mỗi một ý (gạch đầu dòng • hoặc icon 🔴🟡🟢) phải xuống dòng cách đoạn (\n\n) rõ ràng
        text = re.sub(r"(?<=[^\n])\s*•\s*", "\n\n• ", text)
        text = re.sub(r"(?<=[^\n])\s*(?=[🔴🟡🟢])", "\n\n• ", text)
        # Chuẩn hóa từng dòng, loại bỏ bullet lặp, chấm thừa hoặc khoảng trắng ở đầu dòng
        raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
        formatted_lines = []
        for l in raw_lines:
            l = re.sub(r"^[•\.\-\*\s]+", "", l).strip()
            if not l:
                continue
            l = f"• {l}"
            formatted_lines.append(l)
        return "\n\n".join(formatted_lines)

    part_21 = clean_cfo_artifacts(part_21)
    part_22 = clean_cfo_artifacts(part_22)
    part_23 = clean_cfo_artifacts(part_23)

    # Nếu truy vấn về lãnh đạo/giới tính quản lý nhưng action plan bị nhiễm từ khóa khủng hoảng nhân sự ngô nghê -> ép dùng bộ tạo chuẩn CFO
    is_mgr_query = any(k in q_low for k in ["dept_manager", "quản lý", "trưởng phòng", "manager", "lãnh đạo", "giám đốc", "giới tính", "gender"])
    if is_mgr_query:
        hr_panic_terms = ["đãi ngộ", "stay-interview", "exit interview", "phỏng vấn thôi việc", "nguy cơ thôi việc", "chảy máu chất xám", "bù đắp thâm hụt"]
        if any(term in part_23.lower() for term in hr_panic_terms):
            part_23 = generate_data_grounded_action_plan(df, is_en=is_en, user_query=user_query)
        if any(term in part_22.lower() for term in ["chảy máu chất xám", "nguy cơ thôi việc"]):
            part_22 = generate_data_grounded_hypotheses(df, user_query=user_query, is_en=is_en)

    if not part_21 and not part_22 and not part_23:
        lines_fallback = [re.sub(r"^#+\s*", "", l).strip() for l in cleaned.split("\n") if l.strip() and not l.strip().startswith("#")]
        part_21 = "\n\n".join(lines_fallback)

    return {
        "anomaly": escape_markdown_currency_symbols(part_21),
        "hypothesis": escape_markdown_currency_symbols(part_22),
        "action_plan": escape_markdown_currency_symbols(part_23),
    }
