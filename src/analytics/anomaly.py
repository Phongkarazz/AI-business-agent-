"""
Comprehensive anomaly detection and trend disruption analysis module.
Detects IQR outliers, sudden rate spikes/dips, trend inversions, and concentration risks.
"""

import re
import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .heuristics import get_axis_columns, pick_label_column


def format_anomaly_label(val, col_name: str = "") -> str:
    """Chuyển đổi nhãn thời gian hoặc thực thể sang định dạng tự nhiên thân thiện kinh doanh:
    - Loại bỏ đuôi .0
    - Định dạng Tháng 1..12, Quý 1..4, Năm YYYY
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
            if any(k in c_low for k in ["month", "tháng", "thang"]) and 1 <= i_val <= 12:
                return f"Tháng {i_val}"
            elif any(k in c_low for k in ["quarter", "quý", "quy"]) and 1 <= i_val <= 4:
                return f"Quý {i_val}"
            elif any(k in c_low for k in ["year", "năm", "nam"]) and 1900 <= i_val <= 2100:
                return f"Năm {i_val}"
            elif 1 <= i_val <= 12 and "month" in c_low:
                return f"Tháng {i_val}"
            return str(i_val)
    except Exception:
        pass
    m_ym = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if m_ym:
        return f"Tháng {int(m_ym.group(2))}/{m_ym.group(1)}"
    return s


def detect_outliers(df: pd.DataFrame, y_col: str) -> pd.DataFrame:
    """Phát hiện các điểm bất thường (outlier) theo phương pháp IQR trên cột số được chọn."""
    if df is None or df.empty or y_col not in df.columns:
        return pd.DataFrame()

    try:
        numeric_series = pd.to_numeric(df[y_col], errors="coerce").dropna()
        if len(numeric_series) < 4:
            return df.iloc[0:0]

        q1, q3 = numeric_series.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            return df.iloc[0:0]

        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        return df[(df[y_col] < lower) | (df[y_col] > upper)]
    except Exception:
        return df.iloc[0:0]


def analyze_data_anomalies(df: pd.DataFrame) -> Dict[str, Any]:
    """Phân tích toàn diện dữ liệu để tìm các dấu hiệu bất thường:
    1. Đột biến giá trị (IQR Outliers)
    2. Tăng/giảm đột ngột theo chuỗi thời gian (Spikes & Drops)
    3. Rủi ro tập trung quá mức (Pareto / Concentration Anomaly)
    """
    analysis: Dict[str, Any] = {
        "has_anomaly": False,
        "anomaly_types": [],
        "findings": [],
        "metric_col": None,
        "time_col": None,
        "label_col": None,
        "summary_stats": {},
    }

    if df is None or df.empty or len(df) < 2:
        return analysis

    measure_cols, cat_cols, time_col = get_axis_columns(df)
    if not measure_cols:
        return analysis

    y_col = measure_cols[0]
    analysis["metric_col"] = y_col
    analysis["time_col"] = time_col

    # Tính các chỉ số thống kê cơ bản
    y_series = pd.to_numeric(df[y_col], errors="coerce").dropna()
    if y_series.empty:
        return analysis

    mean_val = float(y_series.mean())
    median_val = float(y_series.median())
    std_val = float(y_series.std()) if len(y_series) > 1 else 0.0
    min_val = float(y_series.min())
    max_val = float(y_series.max())
    total_val = float(y_series.sum())

    analysis["summary_stats"] = {
        "mean": mean_val,
        "median": median_val,
        "std": std_val,
        "min": min_val,
        "max": max_val,
        "total": total_val,
        "count": len(y_series),
    }

    # 1. Quét IQR Outliers
    outliers_df = detect_outliers(df, y_col)
    if not outliers_df.empty:
        analysis["has_anomaly"] = True
        analysis["anomaly_types"].append("Đột biến giá trị (Statistical Outlier)")
        label_col_name = time_col or (cat_cols[0] if cat_cols else "index")
        for _, row in outliers_df.iterrows():
            raw_lbl = row.get(label_col_name, "N/A")
            lbl = format_anomaly_label(raw_lbl, label_col_name)
            val = float(row[y_col])
            diff_pct = ((val - mean_val) / mean_val * 100) if mean_val != 0 else 0
            if any(lbl.startswith(k) for k in ["Tháng", "Quý", "Năm"]):
                prefix = lbl
            else:
                prefix = f"Đối tượng '{lbl}'"
            analysis["findings"].append({
                "type": "outlier",
                "label": lbl,
                "value": val,
                "message": f"{prefix} có giá trị {val:,.2f} lệch {diff_pct:+.1f}% so với trung bình ({mean_val:,.2f}).",
            })

    # 2. Phân tích chuỗi thời gian (nếu có time_col)
    if time_col and len(df) >= 3:
        try:
            df_time = df.copy()
            df_time = df_time.sort_values(time_col).reset_index(drop=True)
            y_time = pd.to_numeric(df_time[y_col], errors="coerce").values
            pct_changes = np.diff(y_time) / np.where(y_time[:-1] == 0, 1e-9, y_time[:-1]) * 100

            for i, pct in enumerate(pct_changes):
                prev_t = format_anomaly_label(df_time[time_col].iloc[i], time_col)
                curr_t = format_anomaly_label(df_time[time_col].iloc[i+1], time_col)
                curr_v = float(y_time[i+1])
                prev_v = float(y_time[i])

                curr_lbl = curr_t if any(curr_t.startswith(k) for k in ["Tháng", "Quý", "Năm"]) else f"Kỳ {curr_t}"
                prev_lbl = prev_t if any(prev_t.startswith(k) for k in ["Tháng", "Quý", "Năm"]) else f"kỳ trước ({prev_t})"

                if pct >= 100.0:  # Tăng gấp đôi trở lên
                    analysis["has_anomaly"] = True
                    if "Tăng trưởng đột biến (Growth Spike)" not in analysis["anomaly_types"]:
                        analysis["anomaly_types"].append("Tăng trưởng đột biến (Growth Spike)")
                    analysis["findings"].append({
                        "type": "spike",
                        "period": curr_t,
                        "pct_change": pct,
                        "message": f"{curr_lbl} tăng vọt {pct:+.1f}% (từ {prev_v:,.2f} lên {curr_v:,.2f}) so với {prev_lbl}.",
                    })
                elif pct <= -50.0:  # Giảm hơn 50%
                    analysis["has_anomaly"] = True
                    if "Sụt giảm nghiêm trọng (Severe Drop)" not in analysis["anomaly_types"]:
                        analysis["anomaly_types"].append("Sụt giảm nghiêm trọng (Severe Drop)")
                    analysis["findings"].append({
                        "type": "drop",
                        "period": curr_t,
                        "pct_change": pct,
                        "message": f"{curr_lbl} sụt giảm mạnh {pct:.1f}% (từ {prev_v:,.2f} xuống {curr_v:,.2f}) so với {prev_lbl}.",
                    })
        except Exception:
            pass

    # 3. Phân tích rủi ro tập trung (Concentration Risk / Dominance Anomaly)
    if not time_col and cat_cols and len(df) >= 3 and total_val > 0:
        try:
            label_name, label_series, _ = pick_label_column(df, cat_cols)
            if label_name:
                top_row = df.loc[df[y_col].idxmax()]
                top_name = str(top_row[label_name]) if label_name in df.columns else str(label_series.iloc[0])
                top_val = float(top_row[y_col])
                share = (top_val / total_val) * 100

                if share >= 50.0:  # 1 đối tượng chiếm trên 50% tổng
                    analysis["has_anomaly"] = True
                    analysis["anomaly_types"].append("Rủi ro tập trung cao (Concentration Anomaly)")
                    analysis["findings"].append({
                        "type": "concentration",
                        "entity": top_name,
                        "share": share,
                        "message": f"Đối tượng '{top_name}' chiếm đến {share:.1f}% tổng {y_col} toàn bộ danh sách ({top_val:,.2f}/{total_val:,.2f}).",
                    })
        except Exception:
            pass

    return analysis
