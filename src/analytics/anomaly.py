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


def parse_time_point_index(val, col_name: str = "") -> tuple:
    """Chuyển đổi mốc thời gian thành chỉ số số học để tính khoảng cách bước nhảy (gap detection).
    Trả về (index, unit) ví dụ: (2005*12 + 5, 'month') hoặc (2005, 'year').
    """
    if val is None or (hasattr(pd, "isna") and pd.isna(val) is True):
        return -1, "unknown"
    s = str(val).strip()
    m_ym = re.match(r"^(\d{4})[-/](\d{1,2})$", s)
    if m_ym:
        return int(m_ym.group(1)) * 12 + int(m_ym.group(2)), "month"
    m_yq = re.match(r"^(\d{4})[-/]?Q(\d)$", s, re.IGNORECASE)
    if m_yq:
        return int(m_yq.group(1)) * 4 + int(m_yq.group(2)), "quarter"
    try:
        f_val = float(s)
        if f_val.is_integer():
            i_val = int(f_val)
            c_low = str(col_name).lower() if col_name else ""
            if any(k in c_low for k in ["year", "năm", "nam"]) or (1900 <= i_val <= 2100):
                return i_val, "year"
            if any(k in c_low for k in ["month", "tháng", "thang"]) or (1 <= i_val <= 12):
                return i_val, "month"
            if any(k in c_low for k in ["quarter", "quý", "quy"]) or (1 <= i_val <= 4):
                return i_val, "quarter"
    except Exception:
        pass
    return -1, "unknown"


def analyze_data_anomalies(df: pd.DataFrame) -> Dict[str, Any]:
    """Phân tích toàn diện dữ liệu để tìm các dấu hiệu bất thường:
    1. Đột biến giá trị (IQR Outliers)
    2. Tăng/giảm đột ngột theo chuỗi thời gian (Spikes & Drops) kèm phát hiện độ trũng dữ liệu (Sparse Time Series)
    3. Rủi ro tập trung quá mức (Pareto / Concentration Anomaly)
    """
    analysis: Dict[str, Any] = {
        "has_anomaly": False,
        "anomaly_types": [],
        "findings": [],
        "metric_col": None,
        "time_col": None,
        "label_col": None,
        "has_sparsity_gap": False,
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
        
        # Sắp xếp và chỉ chọn tối đa 1-2 điểm ngoại lai có mức độ lệch cao nhất
        outlier_records = []
        for _, row in outliers_df.iterrows():
            raw_lbl = row.get(label_col_name, "N/A")
            lbl = format_anomaly_label(raw_lbl, label_col_name)
            val = float(row[y_col])
            diff_pct = ((val - mean_val) / mean_val * 100) if mean_val != 0 else 0
            outlier_records.append((abs(diff_pct), lbl, val, diff_pct))
            
        outlier_records.sort(key=lambda x: x[0], reverse=True)
        top_outliers = outlier_records[:2]
        for _, lbl, val, diff_pct in top_outliers:
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
        if len(outlier_records) > 2:
            analysis["findings"].append({
                "type": "outlier_summary",
                "label": "Tổng hợp ngoại lai",
                "value": len(outlier_records),
                "message": f"Toàn bộ tập dữ liệu có {len(outlier_records)} điểm ngoại lai vượt ngưỡng chuẩn (đã chọn lọc các mốc có độ phân hóa mạnh nhất).",
            })

    # 2. Phân tích chuỗi thời gian (nếu có time_col)
    if time_col and len(df) >= 2:
        try:
            df_time = df.copy()
            df_time = df_time.sort_values(time_col).reset_index(drop=True)
            y_time = pd.to_numeric(df_time[y_col], errors="coerce").values

            def _fmt_val_clean(v: float) -> str:
                if abs(v - round(v)) < 1e-5:
                    return f"{int(round(v)):,d}"
                return f"{v:,.2f}"

            sparsity_gaps = []
            spikes_list = []
            drops_list = []
            gap_findings = []

            for i in range(len(y_time) - 1):
                prev_raw = df_time[time_col].iloc[i]
                curr_raw = df_time[time_col].iloc[i+1]
                prev_t = format_anomaly_label(prev_raw, time_col)
                curr_t = format_anomaly_label(curr_raw, time_col)
                curr_v = float(y_time[i+1])
                prev_v = float(y_time[i])

                curr_lbl = curr_t if any(curr_t.startswith(k) for k in ["Tháng", "Quý", "Năm"]) else f"Kỳ {curr_t}"
                prev_lbl = prev_t if any(prev_t.startswith(k) for k in ["Tháng", "Quý", "Năm"]) else f"kỳ trước ({prev_t})"

                prev_v_str = _fmt_val_clean(prev_v)
                curr_v_str = _fmt_val_clean(curr_v)

                # Kiểm tra xem giữa 2 kỳ có bị đứt quãng (sparsity gap) không
                prev_idx, prev_unit = parse_time_point_index(prev_raw, time_col)
                curr_idx, curr_unit = parse_time_point_index(curr_raw, time_col)
                is_gap = False
                gap_span = 0
                if prev_unit == curr_unit and prev_unit != "unknown" and prev_idx > 0 and curr_idx > 0:
                    diff_steps = curr_idx - prev_idx
                    if diff_steps > 1:
                        is_gap = True
                        gap_span = diff_steps
                        unit_str = "tháng" if prev_unit == "month" else ("quý" if prev_unit == "quarter" else "năm")
                        sparsity_gaps.append(f"{gap_span} {unit_str} giữa {prev_lbl} và {curr_lbl}")

                # Tính toán tỷ lệ % thay đổi an toàn, loại bỏ triệt để lỗi chia cho 0
                if prev_v == 0:
                    if curr_v > 0:
                        diff_v = curr_v - prev_v
                        diff_v_str = _fmt_val_clean(diff_v)
                        spikes_list.append({
                            "type": "spike",
                            "period": curr_t,
                            "pct_change": 100.0,
                            "message": f"{curr_lbl} tăng từ {prev_v_str} lên {curr_v_str} (+{diff_v_str}) so với {prev_lbl} (kỳ trước ghi nhận 0).",
                        })
                else:
                    pct = (curr_v - prev_v) / prev_v * 100.0
                    if is_gap:
                        analysis["has_anomaly"] = True
                        analysis["has_sparsity_gap"] = True
                        unit_str = "tháng" if prev_unit == "month" else ("quý" if prev_unit == "quarter" else "năm")
                        if "Độ trũng dữ liệu (Sparse Time-Series)" not in analysis["anomaly_types"]:
                            analysis["anomaly_types"].append("Độ trũng dữ liệu (Sparse Time-Series)")

                        if pct <= -50.0:
                            gap_findings.append({
                                "type": "sparsity_drop",
                                "period": curr_t,
                                "gap": gap_span,
                                "pct_change": pct,
                                "message": f"{curr_lbl} ghi nhận {curr_v_str} sau khoảng gián đoạn {gap_span} {unit_str} (so với {prev_lbl}: {prev_v_str}, không phải 2 kỳ liền kề).",
                            })
                        elif pct >= 100.0:
                            gap_findings.append({
                                "type": "sparsity_spike",
                                "period": curr_t,
                                "gap": gap_span,
                                "pct_change": pct,
                                "message": f"{curr_lbl} ghi nhận {curr_v_str} sau khoảng gián đoạn {gap_span} {unit_str} (so với {prev_lbl}: {prev_v_str}).",
                            })
                    else:
                        if pct >= 100.0:  # Tăng gấp đôi trở lên
                            spikes_list.append({
                                "type": "spike",
                                "period": curr_t,
                                "pct_change": pct,
                                "message": f"{curr_lbl} tăng vọt {pct:+.1f}% (từ {prev_v_str} lên {curr_v_str}) so với {prev_lbl}.",
                            })
                        elif pct <= -50.0:  # Giảm hơn 50%
                            drops_list.append({
                                "type": "drop",
                                "period": curr_t,
                                "pct_change": pct,
                                "message": f"{curr_lbl} sụt giảm mạnh {pct:.1f}% (từ {prev_v_str} xuống {curr_v_str}) so với {prev_lbl}.",
                            })

            # Chọn lọc tinh gọn các phát hiện gián đoạn (tối đa 1 mốc tiêu biểu)
            if gap_findings:
                gap_findings.sort(key=lambda x: abs(x["pct_change"]), reverse=True)
                analysis["findings"].append(gap_findings[0])

            # Chọn lọc tinh gọn các phát hiện tăng/giảm mạnh (tối đa 1 đợt tăng mạnh nhất và 1 đợt giảm mạnh nhất)
            if spikes_list:
                analysis["has_anomaly"] = True
                if "Tăng trưởng đột biến (Growth Spike)" not in analysis["anomaly_types"]:
                    analysis["anomaly_types"].append("Tăng trưởng đột biến (Growth Spike)")
                spikes_list.sort(key=lambda x: x["pct_change"], reverse=True)
                analysis["findings"].append(spikes_list[0])  # Đợt tăng đỉnh điểm nhất

            if drops_list:
                analysis["has_anomaly"] = True
                if "Sụt giảm nghiêm trọng (Severe Drop)" not in analysis["anomaly_types"]:
                    analysis["anomaly_types"].append("Sụt giảm nghiêm trọng (Severe Drop)")
                drops_list.sort(key=lambda x: x["pct_change"])  # Đợt giảm sâu nhất
                analysis["findings"].append(drops_list[0])

            if len(spikes_list) + len(drops_list) > 3:
                analysis["findings"].append({
                    "type": "volatility_summary",
                    "period": "Toàn chu kỳ",
                    "pct_change": 0,
                    "message": f"Dữ liệu có độ biến động chu kỳ cao với tổng cộng {len(spikes_list)} đợt tăng vọt và {len(drops_list)} đợt sụt giảm qua các mốc thời gian.",
                })

            if sparsity_gaps:
                analysis["summary_stats"]["is_sparse_time_series"] = True
                analysis["summary_stats"]["sparsity_details"] = "; ".join(sparsity_gaps)
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

                if share >= 40.0:  # 1 đối tượng chiếm từ 40% tổng trở lên
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


# =========================================================================
# PHÂN HỆ SENIOR LEAD DATA ANALYST: PHÁT HIỆN BẤT THƯỜNG & CHIẾN LƯỢC DỮ LIỆU
# =========================================================================

def detect_time_series_inflections(trend_df: pd.DataFrame, time_col: str, val_col: str) -> Dict[str, Any]:
    """Phân tích chuỗi thời gian sâu: Tìm đỉnh lịch sử, đáy, đợt suy giảm liên tục, tỷ lệ co hẹp và điểm uốn."""
    if trend_df is None or trend_df.empty or len(trend_df) < 2:
        return {}
    
    if time_col not in trend_df.columns or val_col not in trend_df.columns:
        return {}

    df = trend_df.copy().dropna(subset=[time_col, val_col])
    if len(df) < 2:
        return {}
    
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce").fillna(0)
    df = df.sort_values(time_col).reset_index(drop=True)
    
    peak_idx = df[val_col].idxmax()
    trough_idx = df[val_col].idxmin()
    
    peak_row = df.iloc[peak_idx]
    trough_row = df.iloc[trough_idx]
    
    peak_val = float(peak_row[val_col])
    peak_period = str(peak_row[time_col])
    
    trough_val = float(trough_row[val_col])
    trough_period = str(trough_row[time_col])
    
    first_row = df.iloc[0]
    last_row = df.iloc[-1]
    
    first_val = float(first_row[val_col])
    last_val = float(last_row[val_col])
    
    # Tính tỷ lệ biến động từ đầu đến cuối kỳ và từ đỉnh xuống đáy
    period_change_pct = ((last_val - first_val) / first_val * 100) if first_val > 0 else 0.0
    peak_to_trough_drop_pct = ((trough_val - peak_val) / peak_val * 100) if peak_val > 0 else 0.0
    
    # Kiểm tra xu hướng suy giảm kéo dài
    values = df[val_col].values
    diffs = np.diff(values)
    is_declining_trend = bool(sum(diffs < 0) >= (len(diffs) * 0.65))
    is_severe_contraction = bool(peak_to_trough_drop_pct <= -40.0)
    has_inflection = bool(is_declining_trend or is_severe_contraction or abs(period_change_pct) >= 30.0)
    
    return {
        "has_inflection": has_inflection,
        "peak_period": peak_period,
        "peak_val": peak_val,
        "trough_period": trough_period,
        "trough_val": trough_val,
        "start_period": str(first_row[time_col]),
        "start_val": first_val,
        "end_period": str(last_row[time_col]),
        "end_val": last_val,
        "period_change_pct": float(period_change_pct),
        "peak_to_trough_drop_pct": float(peak_to_trough_drop_pct),
        "is_declining_trend": is_declining_trend,
        "is_severe_contraction": is_severe_contraction,
    }


def detect_structural_imbalance(dept_df: pd.DataFrame, cat_col: str, val_col: str) -> Dict[str, Any]:
    """Phát hiện lệch pha cơ cấu: Top phòng ban chiếm tỷ trọng áp đảo (>40-50%) và các phòng ban teo tóp (<6%)."""
    if dept_df is None or dept_df.empty or len(dept_df) < 2:
        return {}
    if cat_col not in dept_df.columns or val_col not in dept_df.columns:
        return {}
        
    df = dept_df.copy().dropna(subset=[cat_col, val_col])
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce").fillna(0)
    df = df.sort_values(val_col, ascending=False).reset_index(drop=True)
    
    total = float(df[val_col].sum())
    if total <= 0:
        return {}
        
    top1 = df.iloc[0]
    top1_name = str(top1[cat_col])
    top1_val = float(top1[val_col])
    top1_share = (top1_val / total) * 100
    
    top2_share = 0.0
    top2_names = [top1_name]
    top2_val = top1_val
    if len(df) >= 2:
        top2 = df.iloc[1]
        top2_names.append(str(top2[cat_col]))
        top2_val += float(top2[val_col])
        top2_share = (top2_val / total) * 100
        
    bottom_df = df[df[val_col] / total < 0.06]
    bottom_names = [str(r[cat_col]) for _, r in bottom_df.iterrows()]
    
    is_imbalanced = bool(top1_share >= 35.0 or top2_share >= 45.0)
    
    return {
        "has_imbalance": is_imbalanced,
        "top1_name": top1_name,
        "top1_val": top1_val,
        "top1_share": float(top1_share),
        "top2_names": " & ".join(top2_names),
        "top2_val": float(top2_val),
        "top2_share": float(top2_share),
        "bottom_names": ", ".join(bottom_names) if bottom_names else "Không có",
        "total_val": float(total),
    }


def detect_compensation_disparity(df: pd.DataFrame, cat_col: str, salary_col: str) -> Dict[str, Any]:
    """Phát hiện bất bình đẳng lương: Khoảng cách giữa phòng ban/vị trí cao nhất và thấp nhất (Gap Ratio > 1.35x)."""
    if df is None or df.empty or len(df) < 2:
        return {}
    if cat_col not in df.columns or salary_col not in df.columns:
        return {}
        
    d = df.copy().dropna(subset=[cat_col, salary_col])
    d[salary_col] = pd.to_numeric(d[salary_col], errors="coerce").fillna(0)
    d = d[d[salary_col] > 0].sort_values(salary_col, ascending=False).reset_index(drop=True)
    
    if len(d) < 2:
        return {}
        
    highest = d.iloc[0]
    lowest = d.iloc[-1]
    
    max_val = float(highest[salary_col])
    min_val = float(lowest[salary_col])
    
    if min_val <= 0:
        return {}
        
    ratio = max_val / min_val
    gap_val = max_val - min_val
    
    return {
        "has_disparity": bool(ratio >= 1.30),
        "highest_entity": str(highest[cat_col]),
        "highest_salary": max_val,
        "lowest_entity": str(lowest[cat_col]),
        "lowest_salary": min_val,
        "gap_ratio": float(ratio),
        "absolute_gap": float(gap_val),
        "avg_salary": float(d[salary_col].mean()),
    }


def scan_dashboard_anomalies_and_strategies(
    layer_id: str,
    data: Dict[str, Any],
    start_year: int,
    end_year: int,
    lang: str = "vi"
) -> Dict[str, Any]:
    """Bộ Quét & Hoạch Định Chiến Lược Toàn Diện Chuẩn Senior Lead Data Analyst:
    1. Quét chuỗi thời gian (suy giảm, đỉnh-đáy, đứt gãy tuyển dụng)
    2. Quét cơ cấu (lệch pha nhân lực, tập trung phòng ban)
    3. Quét đãi ngộ (bất bình đẳng thu nhập, ép lương)
    4. Quét định biên quản trị (quá tải span of control)
    5. Tổng hợp chẩn đoán nguyên nhân gốc rễ (Root Cause) & Tác động lượng hóa (Impact)
    6. Sinh kế hoạch hành động chiến lược 3 tầng sắc bén gắn chặt với số liệu thực tế.
    Hỗ trợ song ngữ Tiếng Việt & English.
    """
    is_en = (lang == "en")
    if is_en:
        time_label = f"Year {start_year}" if start_year == end_year else f"Period {start_year} — {end_year}"
    else:
        time_label = f"Năm {start_year}" if start_year == end_year else f"Giai đoạn {start_year} — {end_year}"
    is_multi_year = (start_year != end_year)
    
    anomalies: List[Dict[str, Any]] = []
    
    # -------------------------------------------------------------
    # 1. Quét Chuỗi Thời Gian (Trend Analysis)
    # -------------------------------------------------------------
    trend_df = data.get("trend_df") if isinstance(data.get("trend_df"), pd.DataFrame) else None
    if trend_df is not None and not trend_df.empty:
        t_col = "TimePeriod" if "TimePeriod" in trend_df.columns else (trend_df.columns[0])
        v1_col = "Metric1" if "Metric1" in trend_df.columns else ("Headcount" if "Headcount" in trend_df.columns else trend_df.columns[1])
        metric1_name = data.get("metric1_name", "Quy mô Tuyển Dụng" if not is_en else "Hiring Headcount")
        
        t_res = detect_time_series_inflections(trend_df, t_col, v1_col)
        if t_res.get("has_inflection"):
            drop_pct = abs(t_res['peak_to_trough_drop_pct'])
            severity = "CRITICAL 🚨" if drop_pct >= 50.0 else "WARNING ⚠️"
            
            if is_en:
                anomalies.append({
                    "severity": severity,
                    "category": "Time Series & Hiring Trend",
                    "title": f"Hiring Cliff: -{drop_pct:.1f}% contraction from historical peak",
                    "metrics_summary": f"Hiring peaked at <b>{t_res['peak_val']:,.0f}</b> headcount ({t_res['peak_period']}) then plunged down to a trough of <b>{t_res['trough_val']:,.0f}</b> ({t_res['trough_period']}), representing a <b>-{drop_pct:.1f}%</b> decline.",
                    "root_cause": "The organization rapidly shifted from 'Hyper-growth Expansion' to 'Lean Operations & Productivity Consolidation'. However, multi-year excessive hiring freezes risk disrupting talent succession.",
                    "quantified_impact": f"Diminished influx of junior staff increases average employee age, elevating mid/senior talent shortage risks when natural retirements begin after {time_label}.",
                    "raw": t_res
                })
            else:
                anomalies.append({
                    "severity": severity,
                    "category": "Chuỗi Thời Gian & Xu Hướng Tuyển Dụng",
                    "title": f"Đứt gãy tuyển dụng: Co hẹp {drop_pct:.1f}% từ đỉnh lịch sử",
                    "metrics_summary": f"Tuyển dụng đạt đỉnh <b>{t_res['peak_val']:,.0f}</b> nhân sự ({t_res['peak_period']}) nhưng lao dốc liên tục xuống đáy <b>{t_res['trough_val']:,.0f}</b> nhân sự ({t_res['trough_period']}), tương ứng mức giảm <b>-{drop_pct:.1f}%</b>.",
                    "root_cause": "Doanh nghiệp dịch chuyển mạnh mẽ từ giai đoạn 'Siêu mở rộng quy mô' (Hyper-growth) sang giai đoạn 'Tối ưu hóa năng suất & Vận hành tinh gọn'. Tuy nhiên, việc siết tuyển dụng quá sâu trong nhiều năm liên tiếp dẫn đến nguy cơ đứt gãy thế hệ kế thừa.",
                    "quantified_impact": f"Hụt giảm dòng nhân sự mới khiến độ tuổi bình quân tăng lên, gia tăng rủi ro thiếu hụt nhân lực trung/cao cấp khi làn sóng nghỉ hưu tự nhiên bắt đầu sau {time_label}.",
                    "raw": t_res
                })

    # -------------------------------------------------------------
    # 2. Quét Cơ Cấu Phòng Ban & Tỷ Trọng Nhân Sự (Structural Imbalance)
    # -------------------------------------------------------------
    dept_df = data.get("dept_df") if isinstance(data.get("dept_df"), pd.DataFrame) else data.get("df")
    if dept_df is not None and isinstance(dept_df, pd.DataFrame) and not dept_df.empty:
        d_cat_col = "Department" if "Department" in dept_df.columns else dept_df.columns[0]
        d_val_col = "Headcount" if "Headcount" in dept_df.columns else ("ActiveHeadcount" if "ActiveHeadcount" in dept_df.columns else None)
        
        if d_val_col:
            s_res = detect_structural_imbalance(dept_df, d_cat_col, d_val_col)
            if s_res.get("has_imbalance"):
                if is_en:
                    anomalies.append({
                        "severity": "WARNING ⚠️",
                        "category": "Org Structure & Staffing Allocation",
                        "title": f"Staffing Skew: Top 2 core units comprise {s_res['top2_share']:.1f}% of total workforce",
                        "metrics_summary": f"Divisions <b>{s_res['top2_names']}</b> account for <b>{s_res['top2_share']:.1f}%</b> of total headcount ({s_res['top2_val']:,.0f}/{s_res['total_val']:,.0f} staff), while governance/support units like <b>{s_res['bottom_names']}</b> represent under 6%.",
                        "root_cause": "Heavy concentration on engineering and production without proportional allocation in quality management (QA) and market commercialization.",
                        "quantified_impact": "Operational Bottleneck risk where high engineering output cannot be adequately absorbed or verified by QA and sales channels.",
                        "raw": s_res
                    })
                else:
                    anomalies.append({
                        "severity": "WARNING ⚠️",
                        "category": "Cơ Cấu Tổ Chức & Tỷ Trọng Nhân Sự",
                        "title": f"Lệch pha định biên: 2 khối lõi chiếm {s_res['top2_share']:.1f}% toàn công ty",
                        "metrics_summary": f"Khối <b>{s_res['top2_names']}</b> chiếm <b>{s_res['top2_share']:.1f}%</b> tổng nhân sự ({s_res['top2_val']:,.0f}/{s_res['total_val']:,.0f} người), trong khi các khối kiểm soát/vận hành như <b>{s_res['bottom_names']}</b> chỉ chiếm dưới 6%.",
                        "root_cause": "Mô hình sản xuất phụ thuộc nặng vào lao động thủ công và R&D tập trung, nhưng hệ thống quản trị chất lượng (QA) và tiếp thị chưa được đầu tư tương xứng với quy mô phát triển sản phẩm.",
                        "quantified_impact": "Nguy cơ 'Nghẽn cổ chai vận hành' (Operational Bottleneck) khi khối kỹ thuật/sản xuất tạo ra khối lượng lớn nhưng khối quản lý chất lượng và bán hàng không kịp hấp thụ.",
                        "raw": s_res
                    })

    # -------------------------------------------------------------
    # 3. Quét Bất Bình Đẳng Thu Nhập & Chênh Lệch Lương (Compensation Disparity)
    # -------------------------------------------------------------
    salary_df = data.get("salary_df") if isinstance(data.get("salary_df"), pd.DataFrame) else (dept_df if dept_df is not None and "AvgSalary" in dept_df.columns else None)
    if salary_df is not None and isinstance(salary_df, pd.DataFrame) and not salary_df.empty:
        sal_cat = "Department" if "Department" in salary_df.columns else ("Title" if "Title" in salary_df.columns else salary_df.columns[0])
        sal_val = "AvgSalary" if "AvgSalary" in salary_df.columns else ("avg_salary" if "avg_salary" in salary_df.columns else None)
        
        if sal_val:
            sal_res = detect_compensation_disparity(salary_df, sal_cat, sal_val)
            if sal_res.get("has_disparity"):
                if is_en:
                    anomalies.append({
                        "severity": "WARNING ⚠️",
                        "category": "Compensation & Payroll Governance",
                        "title": f"Pay Disparity: {sal_res['gap_ratio']:.2f}x wage gap across divisions",
                        "metrics_summary": f"Highest average salary at <b>{sal_res['highest_entity']} (${sal_res['highest_salary']:,.0f})</b> is <b>{sal_res['gap_ratio']:.2f}x higher</b> than <b>{sal_res['lowest_entity']} (${sal_res['lowest_salary']:,.0f})</b>, representing a net gap of <b>${sal_res['absolute_gap']:,.0f}/person/year</b>.",
                        "root_cause": "Compensation policies skewed heavily toward Sales/Engineering with insufficient internal equity mechanisms for critical support functions like HR and QA.",
                        "quantified_impact": "Demotivation in key support functions, driving higher voluntary attrition among skilled professionals in lower-compensated departments.",
                        "raw": sal_res
                    })
                else:
                    anomalies.append({
                        "severity": "WARNING ⚠️",
                        "category": "Đãi Ngộ & Quản Trị Quỹ Lương",
                        "title": f"Chênh lệch đãi ngộ: Khoảng cách {sal_res['gap_ratio']:.2f}x giữa các khối",
                        "metrics_summary": f"Mức lương bình quân cao nhất tại <b>{sal_res['highest_entity']} (${sal_res['highest_salary']:,.0f})</b> gấp <b>{sal_res['gap_ratio']:.2f} lần</b> so với <b>{sal_res['lowest_entity']} (${sal_res['lowest_salary']:,.0f})</b>, chênh lệch tuyệt đối <b>${sal_res['absolute_gap']:,.0f}/người/năm</b>.",
                        "root_cause": "Chính sách đãi ngộ thiên lệch về phía Bán hàng/Kỹ thuật nhưng thiếu cơ chế cân bằng nội bộ (Internal Equity) cho các khối hỗ trợ trọng yếu như Nhân sự, Quản trị chất lượng.",
                        "quantified_impact": "Gây tâm lý mất động lực làm việc ở các khối hỗ trợ, dẫn đến tỷ lệ nhân viên giỏi tự nguyện nghỉ việc (Voluntary Turnover) tăng cao tại các phòng ban có lương bình quân thấp.",
                        "raw": sal_res
                    })

    # -------------------------------------------------------------
    # 4. Quét Định Biên Quản Trị (Span of Control)
    # -------------------------------------------------------------
    if dept_df is not None and isinstance(dept_df, pd.DataFrame) and "CurrentManager" in dept_df.columns and "ActiveHeadcount" in dept_df.columns:
        top_headcount_dept = dept_df.sort_values("ActiveHeadcount", ascending=False).iloc[0]
        max_hc = float(top_headcount_dept["ActiveHeadcount"])
        dept_n = str(top_headcount_dept["Department"])
        mgr_n = str(top_headcount_dept["CurrentManager"])
        
        if max_hc >= 20000:
            if is_en:
                anomalies.append({
                    "severity": "CRITICAL 🚨",
                    "category": "Organizational Span of Control",
                    "title": f"Span of Control Overload: 1 Manager oversees {max_hc:,.0f} employees",
                    "metrics_summary": f"In department <b>{dept_n}</b>, Manager (<b>{mgr_n}</b>) directly oversees a headcount of <b>{max_hc:,.0f} staff</b>, far exceeding standard governance thresholds (1:15 to 1:25).",
                    "root_cause": "Absence of structured mid-level management hierarchy (Team Leads / Sub-unit Managers) in the system schema, concentrating excessive decision overhead on single department heads.",
                    "quantified_impact": "Significant Key-Person Risk; slower strategic agility and reduced micro-level quality supervision across technical lines.",
                    "raw": {"dept": dept_n, "headcount": max_hc, "manager": mgr_n}
                })
            else:
                anomalies.append({
                    "severity": "CRITICAL 🚨",
                    "category": "Định Biên & Quản Trị Điều Hành",
                    "title": f"Quá tải Span of Control: 1 Quản lý phụ trách {max_hc:,.0f} nhân sự",
                    "metrics_summary": f"Tại phòng ban <b>{dept_n}</b>, Quản lý đương nhiệm (<b>{mgr_n}</b>) đang gánh vác trực tiếp định biên <b>{max_hc:,.0f} nhân viên</b>, vượt xa ngưỡng quản trị hiệu quả (1:15 đến 1:25).",
                    "root_cause": "Thiếu cấu trúc quản lý cấp trung (Team Lead / Sub-unit Managers) được phân bổ chính thức trong hệ thống cơ sở dữ liệu, dẫn đến tình trạng tập trung quyền lực và trách nhiệm quá mức vào cá nhân Trưởng bộ phận.",
                    "quantified_impact": "Rủi ro 'Key-Person Risk' cực lớn; giảm tốc độ ra quyết định và làm suy yếu khả năng giám sát chất lượng vi mô trên từng dây chuyền/nhóm kỹ thuật.",
                    "raw": {"dept": dept_n, "headcount": max_hc, "manager": mgr_n}
                })

    # -------------------------------------------------------------
    # TỔNG HỢP CHIẾN LƯỢC 3 TẦNG CHUẨN SENIOR DATA ANALYST
    # -------------------------------------------------------------
    has_critical = any(a["severity"].startswith("CRITICAL") for a in anomalies)
    health_status = "CRITICAL 🔴" if has_critical else ("WARNING 🟡" if anomalies else "OPTIMAL 🟢")
    health_score = 62 if has_critical else (78 if anomalies else 95)
    
    immediate_actions = []
    structural_optimizations = []
    sustainable_strategies = []
    okrs = []
    
    if anomalies:
        for a in anomalies:
            cat = a["category"]
            
            if "Tuyển Dụng" in cat or "Hiring" in cat or "Time Series" in cat or "Chuỗi Thời Gian" in cat:
                raw_t = a.get("raw", {})
                peak_p = raw_t.get("peak_period", "start")
                trough_p = raw_t.get("trough_period", "end")
                drop_val = abs(raw_t.get("peak_to_trough_drop_pct", 50.0))
                
                if is_en:
                    immediate_actions.append(f"<b>Stabilize Hiring Intake (0 - 30 Days)</b>: Halt the -{drop_val:.1f}% contraction by establishing a minimum headcount floor of {int(raw_t.get('trough_val', 10000) * 1.15):,d} new hires/year for core operations.")
                    structural_optimizations.append(f"<b>Restructure Talent Acquisition (1 - 2 Quarters)</b>: Pivot from volume hiring ({raw_t.get('peak_val', 36000):,.0f} staff in {peak_p}) to Targeted Specialized Hiring focused on R&D and senior engineering.")
                    sustainable_strategies.append(f"<b>3-Year Talent Succession Pipeline</b>: Build leadership pipelines to prevent generational skill gaps as the {peak_p} cohort approaches retirement age.")
                    okrs.append(f"Maintain Attrition Replacement Rate ≥ 100% and protect minimum operational headcount above {raw_t.get('trough_val', 10000):,.0f} staff/year.")
                else:
                    immediate_actions.append(f"<b>Ổn định quy mô tuyển dụng (0 - 30 ngày)</b>: Chặn đà suy giảm -{drop_val:.1f}% bằng cách thiết lập mức sàn định biên (Headcount Floor) tối thiểu {int(raw_t.get('trough_val', 10000) * 1.15):,d} nhân sự mới/năm cho các dự án trọng điểm.")
                    structural_optimizations.append(f"<b>Tái cấu trúc kế hoạch tuyển mộ (1 - 2 Quý)</b>: Chuyển dịch từ tuyển ồ ạt ({raw_t.get('peak_val', 36000):,.0f} người ở {peak_p}) sang tuyển chọn chất lượng cao (Targeted Specialized Hiring) tập trung vào R&D và Kỹ sư thâm niên.")
                    sustainable_strategies.append(f"<b>Chương trình Kế thừa Nhân tài 3 Năm</b>: Xây dựng 'Pipeline kế cận' nhằm phòng ngừa rủi ro đứt gãy thế hệ khi lứa nhân sự tuyển dụng đỉnh cao năm {peak_p} đạt thâm niên hưu trí.")
                    okrs.append(f"Duy trì tỷ lệ tuyển bù hao hụt tự nhiên (Attrition Replacement Rate) ≥ 100% và chặn mức giảm định biên dưới mốc {raw_t.get('trough_val', 10000):,.0f} người/năm.")

            elif "Cơ Cấu" in cat or "Structure" in cat:
                raw_s = a.get("raw", {})
                top2_n = raw_s.get("top2_names", "Engineering & Production")
                top2_s = raw_s.get("top2_share", 47.0)
                bot_n = raw_s.get("bottom_names", "Support Units")
                
                if is_en:
                    immediate_actions.append(f"<b>Audit Support Unit Workload (0 - 30 Days)</b>: Conduct an immediate workload review in lean support units ({bot_n}) to mitigate burnout risks.")
                    structural_optimizations.append(f"<b>Rebalance Budget Allocation (1 - 2 Quarters)</b>: Raise QA & Marketing workforce share from <6% to at least 8.5% to proportionately support core units {top2_n} ({top2_s:.1f}%).")
                    sustainable_strategies.append(f"<b>Agile Cross-Functional Pods</b>: Form cross-functional teams directly bridging Engineering with QA and Commercialization to shorten release cycles.")
                    okrs.append("Achieve a QA/Support to Engineering ratio of at least 1:8 within the next 12 months.")
                else:
                    immediate_actions.append(f"<b>Rà soát định biên khối hỗ trợ (0 - 30 ngày)</b>: Khảo sát ngay khối lượng công việc (Workload Audit) tại các phòng ban teo tóp ({bot_n}) để tránh tình trạng quá tải.")
                    structural_optimizations.append(f"<b>Cân bằng tỷ trọng ngân sách (1 - 2 Quý)</b>: Điều chỉnh cơ cấu phân bổ chi phí, nâng tỷ trọng nhân lực QA & Marketing từ mức dưới 6% hiện tại lên tối thiểu 8.5% để hỗ trợ tương xứng cho khối {top2_n} ({top2_s:.1f}%).")
                    sustainable_strategies.append(f"<b>Mô hình Agile Cross-functional</b>: Xây dựng các nhóm làm việc liên phòng ban kết nối trực tiếp Kỹ thuật ({raw_s.get('top1_name', 'Dev')}) với QA và Kinh doanh để rút ngắn chu kỳ tung sản phẩm.")
                    okrs.append(f"Nâng tỷ lệ nguồn lực khối Đảm bảo chất lượng (QA/Support) trên tổng khối Kỹ thuật đạt tối thiểu 1:8 trong 12 tháng tới.")

            elif "Đãi Ngộ" in cat or "Compensation" in cat:
                raw_c = a.get("raw", {})
                hi_e = raw_c.get("highest_entity", "Sales")
                lo_e = raw_c.get("lowest_entity", "HR")
                gap_r = raw_c.get("gap_ratio", 1.45)
                gap_a = raw_c.get("absolute_gap", 25000)
                
                if is_en:
                    immediate_actions.append(f"<b>Review Salary Bands (0 - 30 Days)</b>: Benchmark market competitiveness for {lo_e} (${raw_c.get('lowest_salary', 55000):,.0f}) to prevent key talent attrition.")
                    structural_optimizations.append(f"<b>Close Disparity Gap (1 - 2 Quarters)</b>: Rebalance performance bonuses over base pay, lowering the gap ratio between {hi_e} and {lo_e} from {gap_r:.2f}x to under 1.25x (narrowing ${gap_a:,.0f}).")
                    sustainable_strategies.append(f"<b>Total Rewards Framework</b>: Roll out non-cash benefits (specialized training, accelerated career paths, executive health) for lower-base departments.")
                    okrs.append("Reduce maximum disparity ratio below 1.25x and keep compensation-related voluntary attrition under 7%/year.")
                else:
                    immediate_actions.append(f"<b>Rà soát trần - sàn lương (0 - 30 ngày)</b>: Phân tích Salary Banding toàn công ty, kiểm tra mức độ cạnh tranh thị trường tại {lo_e} (${raw_c.get('lowest_salary', 55000):,.0f}) để tránh chảy máu chất xám.")
                    structural_optimizations.append(f"<b>Thu hẹp khoảng cách bất bình đẳng (1 - 2 Quý)</b>: Tái cấu trúc cơ chế thưởng hiệu suất (Performance-based Bonus) thay vì lương cứng, kiểm soát Gap Ratio giữa {hi_e} và {lo_e} từ {gap_r:.2f}x về dưới mức an toàn 1.25x (thu hẹp khoảng chênh ${gap_a:,.0f}).")
                    sustainable_strategies.append(f"<b>Hệ thống đãi ngộ tổng thể (Total Rewards Framework)</b>: Triển khai gói phúc lợi phi tiền tệ (đào tạo, lộ trình thăng tiến, bảo hiểm cao cấp) cho các khối có mức lương bình quân thấp hơn.")
                    okrs.append(f"Giảm mức chênh lệch lương tối đa (Disparity Ratio) về dưới 1.25x và kiểm soát tỷ lệ nhân viên nghỉ việc vì lý do đãi ngộ dưới 7%/năm.")

            elif "Quản Trị" in cat or "Span of Control" in cat:
                raw_m = a.get("raw", {})
                dept_m = raw_m.get("dept", "Production")
                hc_m = raw_m.get("headcount", 50000)
                
                if is_en:
                    immediate_actions.append(f"<b>Emergency Executive Delegation (0 - 30 Days)</b>: Appoint acting Deputy Leads in {dept_m} to distribute leadership load across {hc_m:,.0f} personnel.")
                    structural_optimizations.append(f"<b>Restructure Mid-Level Hierarchy (1 - 2 Quarters)</b>: Partition {dept_m} into autonomous sub-units with normalized Span of Control (1 Lead per 500 - 1,000 workers).")
                    sustainable_strategies.append(f"<b>Leadership Pipeline Program</b>: Annually train 50+ mid-level managers to ensure organizational scalability and resilience.")
                    okrs.append(f"Complete 100% team lead appointments in {dept_m} within 6 months.")
                else:
                    immediate_actions.append(f"<b>Ủy quyền điều hành khẩn cấp (0 - 30 ngày)</b>: Bổ nhiệm tạm thời các Deputy Lead tại {dept_m} để san sẻ áp lực quản lý trên quy mô {hc_m:,.0f} nhân sự.")
                    structural_optimizations.append(f"<b>Tái thiết lập Cấu trúc Quản lý Cấp Trung (1 - 2 Quý)</b>: Chia tách {dept_m} thành các Sub-units hoặc Plant/Division độc lập với Span of Control chuẩn (1 Quản lý / 500 - 1,000 công nhân).")
                    sustainable_strategies.append(f"<b>Chương trình Đào tạo Lãnh đạo Kế cận (Leadership Pipeline)</b>: Đào tạo định kỳ 50+ cán bộ quản lý cấp trung hàng năm để đảm bảo khả năng mở rộng quy mô bền vững.")
                    okrs.append(f"Hoàn tất phân bổ 100% định biên Trưởng nhóm/Phó phòng ban tại {dept_m} trong vòng 6 tháng tới.")

    else:
        if is_en:
            immediate_actions.append(f"<b>Sustain Operational Momentum (0 - 30 Days)</b>: Continue tracking established KPIs for {time_label}.")
            structural_optimizations.append("<b>Optimize Internal Processes (1 - 2 Quarters)</b>: Automate repetitive workflows to preserve high productivity.")
            sustainable_strategies.append("<b>Expand Competitive Moat (1 - 3 Years)</b>: Invest in talent upskilling and capability diversification.")
            okrs.append("Maintain business growth ≥ 12% and keep payroll expenditure variance within ± 5%.")
        else:
            immediate_actions.append(f"<b>Duy trì đà vận hành ổn định (0 - 30 ngày)</b>: Tiếp tục bám sát các chỉ số KPI hiện tại trong {time_label}.")
            structural_optimizations.append("<b>Tối ưu hóa quy trình nội bộ (1 - 2 Quý)</b>: Tự động hóa các tác vụ lặp lại để duy trì mức hiệu suất cao.")
            sustainable_strategies.append("<b>Mở rộng năng lực cạnh tranh (1 - 3 Năm)</b>: Đầu tư vào nâng cao chất lượng nguồn nhân lực và mở rộng danh mục.")
            okrs.append("Duy trì tốc độ tăng trưởng doanh nghiệp ≥ 12% và kiểm soát chi phí quỹ lương trong giới hạn ± 5%.")

    if is_en:
        headline = (
            f"Identified {len(anomalies)} key operational anomalies during {time_label}. Immediate intervention recommended for hiring trends and internal compensation equity."
            if anomalies else
            f"Operational structures and indicators during {time_label} remain stable and balanced."
        )
    else:
        headline = (
            f"Phát hiện {len(anomalies)} điểm bất thường trọng yếu trong {time_label}. Đề xuất can thiệp ngay vào xu hướng tuyển dụng và cân đối đãi ngộ nội bộ."
            if anomalies else
            f"Cơ cấu vận hành và các chỉ số trong {time_label} duy trì trạng thái ổn định và cân bằng."
        )

    # Đóng gói Prompt Payload cho AI Agent (làm sạch thẻ HTML trước khi gửi vào prompt)
    clean_anomalies_text = ""
    for i, a in enumerate(anomalies, 1):
        c_sum = re.sub(r'<[^>]+>', '', a['metrics_summary'])
        c_rc = re.sub(r'<[^>]+>', '', a['root_cause'])
        c_imp = re.sub(r'<[^>]+>', '', a['quantified_impact'])
        clean_anomalies_text += f"""
[{i}] {a['severity']} {a['title']}
- Số liệu ghi nhận / Recorded Metrics: {c_sum}
- Nguyên nhân gốc rễ / Root Cause: {c_rc}
- Tác động lượng hóa / Quantified Impact: {c_imp}
"""

    clean_imm = [re.sub(r'<[^>]+>', '', act) for act in immediate_actions]
    clean_str = [re.sub(r'<[^>]+>', '', act) for act in structural_optimizations]
    clean_sus = [re.sub(r'<[^>]+>', '', act) for act in sustainable_strategies]
    clean_okr = [re.sub(r'<[^>]+>', '', okr) for okr in okrs]

    if is_en:
        ai_prompt_payload = f"""SENIOR LEAD DATA ANALYST EXECUTIVE REPORT:
- Domain layer: {layer_id}
- Time period: {time_label}
- Operational health: {health_status} (Score: {health_score}/100)
- Detected anomalies: {len(anomalies)}

CRITICAL ANOMALIES:
{clean_anomalies_text}
STRATEGIC ACTION PLAN:
- Immediate (0-30 days): {'; '.join(clean_imm)}
- Restructuring (1-2 quarters): {'; '.join(clean_str)}
- Sustainability (1-3 years): {'; '.join(clean_sus)}
- OKR metrics: {'; '.join(clean_okr)}

Request: Perform deeper analytics on these findings, draft an Executive Board Memo and create a detailed RACI action matrix for leadership.
"""
    else:
        ai_prompt_payload = f"""BÁO CÁO CHUYÊN SÂU TỪ SENIOR LEAD DATA ANALYST:
- Phân hệ khảo sát: {layer_id}
- Thời gian khảo sát: {time_label}
- Trạng thái sức khỏe vận hành: {health_status} (Điểm số: {health_score}/100)
- Số điểm bất thường phát hiện: {len(anomalies)}

DANH SÁCH BẤT THƯỜNG TRỌNG YẾU:
{clean_anomalies_text}
ĐỀ XUẤT CHIẾN LƯỢC HÀNH ĐỘNG:
- Ngắn hạn (0-30 ngày): {'; '.join(clean_imm)}
- Trung hạn (1-2 quý): {'; '.join(clean_str)}
- Dài hạn (1-3 năm): {'; '.join(clean_sus)}
- Chỉ số OKR đo lường: {'; '.join(clean_okr)}

Yêu cầu: Hãy phân tích sâu hơn nữa về các điểm bất thường trên, soạn thảo văn bản tham mưu chiến lược (Executive Board Memo) và xây dựng bảng phân bổ hành động (Action Plan Gantt) chi tiết cho Ban Điều Hành.
"""

    return {
        "health_status": health_status,
        "health_score": health_score,
        "headline": headline,
        "anomalies": anomalies,
        "immediate_actions": immediate_actions,
        "structural_optimizations": structural_optimizations,
        "sustainable_strategies": sustainable_strategies,
        "okrs": okrs,
        "ai_prompt_payload": ai_prompt_payload.strip(),
        "time_label": time_label,
    }

