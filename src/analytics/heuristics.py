"""
Column classification and heuristic utilities for business datasets.
"""

import re
import pandas as pd
from src.config import ID_LIKE_REGEX, NAME_LIKE_REGEX, TIME_KEYWORDS


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


def pick_label_column(df: pd.DataFrame, label_cols: list):
    """Chọn cột nhãn tốt nhất cho trục X:
    1) Gộp first_name + last_name nếu có
    2) Cột có tên nghiệp vụ gợi ý (name, product,...)
    3) Cột text thông thường
    4) Cột ID
    """
    if not label_cols:
        return None, None, []

    cols_lower = {str(c).lower(): c for c in label_cols}
    if "first_name" in cols_lower and "last_name" in cols_lower:
        fn, ln = cols_lower["first_name"], cols_lower["last_name"]
        merged = (df[fn].astype(str) + " " + df[ln].astype(str))
        return "Họ và tên", merged, [fn, ln]

    text_like = [c for c in label_cols if not is_id_like(c)]
    name_hint = [c for c in text_like if NAME_LIKE_REGEX.search(str(c))]
    rest_text = [c for c in text_like if c not in name_hint]
    id_like_cols = [c for c in label_cols if c not in text_like]

    ordered_candidates = name_hint + rest_text + id_like_cols
    if not ordered_candidates:
        return None, None, []
    chosen = ordered_candidates[0]
    return chosen, df[chosen].astype(str), [chosen]
