"""
Universal Chart Zoom & In-Depth Anomaly Explanation Module.
Provides interactive fullscreen/dialog zoom for all charts with AI-driven explanations and anomaly insights.
Fully localized with instant reactive bilingual support (Vietnamese & English).
"""

import copy
import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from typing import Optional, List, Dict, Any
from src.analytics.anomaly import analyze_data_anomalies, format_anomaly_label
from src.analytics.heuristics import is_id_like, get_axis_columns, find_time_column
from src.i18n import get_current_language, t

# Module-level SVG icon helpers for recommendations and action items
SVG_SLUMP = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="2.2" style="vertical-align:-1px;"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"></polyline><polyline points="17 18 23 18 23 12"></polyline></svg>'
SVG_PEAK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2.2" style="vertical-align:-1px;"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>'
SVG_TARGET = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00F0FF" stroke-width="2.2" style="vertical-align:-1px;"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>'
SVG_RANK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2.2" style="vertical-align:-1px;"><circle cx="12" cy="8" r="7"></circle><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"></polyline></svg>'
SVG_BOX = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8B5CF6" stroke-width="2.2" style="vertical-align:-1px;"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>'
SVG_DOLLAR = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00DF8F" stroke-width="2.2" style="vertical-align:-1px;"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>'
SVG_BALANCE = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#38BDF8" stroke-width="2.2" style="vertical-align:-1px;"><line x1="12" y1="3" x2="12" y2="21"></line><path d="M17 7l4 4-4 4"></path><path d="M7 17l-4-4 4-4"></path></svg>'
SVG_ACTIVITY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#A855F7" stroke-width="2.2" style="vertical-align:-1px;"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>'

# Backward-compatible lowercase aliases
svg_slump = SVG_SLUMP
svg_peak = SVG_PEAK
svg_target = SVG_TARGET
svg_rank = SVG_RANK
svg_box = SVG_BOX
svg_dollar = SVG_DOLLAR
svg_balance = SVG_BALANCE
svg_activity = SVG_ACTIVITY


def _format_metric_val(val: float, metric_name: str = "") -> str:
    """Format numerical values smartly and context-sensitively in both EN and VI."""
    is_en = (get_current_language() == "en")
    m_lower = str(metric_name).lower()
    
    # 1. Tenure / Duration / Years / Age
    if any(k in m_lower for k in ["year", "năm", "thâm niên", "tham_nien", "tenure", "duration", "kinh nghiệm", "kinh_nghiem", "service", "age", "tuổi"]) and not any(k in m_lower for k in ["sales", "revenue", "salary", "lương", "cost", "doanh"]):
        unit = "years" if is_en else "năm"
        return f"{val:.1f} {unit}" if not val.is_integer() else f"{int(val)} {unit}"
    
    # 2. Percentage
    if any(k in m_lower for k in ["rate", "pct", "percent", "%", "tỷ lệ", "tỉ lệ", "tỷ trọng", "tỉ trọng", "margin", "tỷ suất", "tỉ suất"]):
        return f"{val:.2f}%" if abs(val) < 100 else f"{val:.1f}%"
        
    # 3. Headcount / People / Employees
    if any(k in m_lower for k in ["headcount", "nhân sự", "nhân viên", "employee", "người", "people", "count_emp", "promoted", "thăng chức"]):
        unit = "people" if is_en else "người"
        return f"{int(val):,} {unit}"
        
    # 4. Production boxes / units
    if any(k in m_lower for k in ["boxes", "box", "hộp", "thùng", "sản lượng"]):
        unit = "boxes" if is_en else "hộp"
        return f"{int(val):,} {unit}"
        
    # 5. Currency (Sales, Revenue, Salary, Cost, Profit)
    is_currency = any(k in m_lower for k in ["sales", "doanh", "thu", "lương", "salary", "payroll", "amount", "cost", "giá", "$", "tiền", "profit", "lợi nhuận", "budget", "quỹ"])
    prefix = "$" if is_currency and not any(k in m_lower for k in ["vnđ", "đồng"]) else ""
    
    abs_v = abs(val)
    if abs_v >= 1_000_000_000:
        return f"{prefix}{val/1_000_000_000:.2f}B"
    elif abs_v >= 1_000_000:
        return f"{prefix}{val/1_000_000:.2f}M"
    elif abs_v >= 1_000:
        return f"{prefix}{val/1_000:.1f}k"
    elif isinstance(val, int) or (isinstance(val, float) and val.is_integer()):
        return f"{prefix}{int(val):,}"
    else:
        return f"{prefix}{val:,.2f}"


def _get_effective_metric_and_label(df: pd.DataFrame, fig: Optional[go.Figure] = None) -> tuple[Optional[str], Optional[str], Optional[pd.Series]]:
    """Determine the primary measure column (excluding IDs) and corresponding label column."""
    if df is None or df.empty:
        return None, None, None

    # 1. Try extracting from Figure data traces if available
    fig_metric = None
    fig_label = None
    if fig is not None and hasattr(fig, "data") and len(fig.data) > 0:
        try:
            trace = fig.data[0]
            if getattr(trace, "orientation", "") == "h":
                cand_x_name = getattr(trace, "name", None)
                if hasattr(trace, "x") and hasattr(trace.x, "name") and trace.x.name in df.columns:
                    fig_metric = trace.x.name
                elif cand_x_name in df.columns:
                    fig_metric = cand_x_name
                if hasattr(trace, "y") and hasattr(trace.y, "name") and trace.y.name in df.columns:
                    fig_label = trace.y.name
            elif getattr(trace, "orientation", "") == "v" or not getattr(trace, "orientation", ""):
                if hasattr(trace, "x") and hasattr(trace.x, "name") and trace.x.name in df.columns:
                    fig_label = trace.x.name
                cand_y_name = getattr(trace, "name", None)
                if hasattr(trace, "y") and hasattr(trace.y, "name") and trace.y.name in df.columns:
                    fig_metric = trace.y.name
                elif cand_y_name in df.columns:
                    fig_metric = cand_y_name
        except Exception:
            pass

    measure_cols, cat_cols, time_col = get_axis_columns(df)
    
    # 2. Determine metric
    if fig_metric and fig_metric in df.columns and not is_id_like(fig_metric):
        main_metric = fig_metric
    elif measure_cols:
        main_metric = measure_cols[0]
    else:
        valid_num_cols = [c for c in df.select_dtypes(include="number").columns if not is_id_like(c)]
        main_metric = valid_num_cols[0] if valid_num_cols else None

    if not main_metric or main_metric not in df.columns:
        return None, None, None

    # 3. Determine label
    if fig_label and fig_label in df.columns and fig_label != main_metric:
        label_col = fig_label
    elif time_col and time_col != main_metric:
        label_col = time_col
    elif cat_cols:
        named_cols = [c for c in cat_cols if any(k in str(c).lower() for k in ["name", "tên", "manager", "salesperson", "employee", "dept", "phòng", "product", "sản phẩm", "country", "team", "title"])]
        label_col = named_cols[0] if named_cols else cat_cols[0]
    else:
        other_cols = [c for c in df.columns if c != main_metric and not is_id_like(c)]
        label_col = other_cols[0] if other_cols else (df.columns[0] if len(df.columns) > 1 else None)

    val_series = pd.to_numeric(df[main_metric], errors="coerce").dropna()
    return main_metric, label_col, val_series


def _is_time_column(col_name: str, series: Optional[pd.Series] = None) -> bool:
    """Check if a column is a temporal dimension (Quarter, Month, Year, Date)."""
    if is_id_like(col_name):
        return False
    name_lower = str(col_name).lower()
    
    duration_keywords = ["service", "tenure", "thâm niên", "tham_nien", "experience", "kinh nghiệm", "kinh_nghiem", "duration", "tuoi", "age", "years_as", "yearsas", "số năm", "thời gian"]
    if any(k in name_lower for k in duration_keywords):
        return False
        
    time_keywords = ["year", "time", "date", "period", "tháng", "năm", "quý", "quarter", "month", "qtr", "day", "ngày", "kỳ"]
    if any(k in name_lower for k in time_keywords):
        return True
    if series is not None and not series.empty:
        sample_vals = series.dropna().astype(str).head(10).tolist()
        pattern = re.compile(r"^(\d{4}-?Q[1-4]|Q[1-4]-?\d{4}|Q[1-4]|\d{4}-\d{2}|\d{4}/\d{2}|\d{4}|\d{2}/\d{4}|\d{2}-\d{4})$", re.IGNORECASE)
        match_count = sum(1 for v in sample_vals if pattern.match(v.strip()))
        if match_count >= max(1, len(sample_vals) * 0.5):
            return True
    return False


def _extract_query_context(query_str: str) -> Dict[str, Any]:
    """Extract market, entities, time scope, and domain topic from user query."""
    q = query_str.strip()
    q_lower = q.lower()
    
    # 1. Market / Country
    market = None
    market_matches = [
        ("Ấn Độ (India)", ["ấn độ", "india"]),
        ("Mỹ (USA)", ["mỹ", "usa", "united states", "hoa kỳ"]),
        ("Vương quốc Anh (UK)", ["anh", "uk", "united kingdom"]),
        ("Philippines", ["philippines", "philipin"]),
        ("New Zealand", ["new zealand", "nz"]),
        ("Canada", ["canada"]),
        ("Australia", ["australia", "úc"]),
        ("Việt Nam", ["việt nam", "vietnam", "vn"]),
    ]
    for standard_name, keywords in market_matches:
        if any(k in q_lower for k in keywords):
            market = standard_name
            break
            
    # 2. Time Scope
    time_scope = None
    if re.search(r"từng quý|các quý|quý\s*[1-4]|quarter|q[1-4]", q_lower):
        time_scope = "theo từng quý"
    elif re.search(r"từng tháng|các tháng|hàng tháng|month", q_lower):
        time_scope = "theo từng tháng"
    elif re.search(r"từng năm|các năm|hàng năm|year", q_lower):
        time_scope = "theo từng năm"

    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", q)
    year_val = year_match.group(1) if year_match else None

    # 3. Topic
    if any(k in q_lower for k in ["manager", "quản lý", "thâm niên", "nhiệm kỳ", "lâu nhất", "lãnh đạo", "trưởng phòng", "leader", "giám đốc", "bổ nhiệm", "giữ chức vụ", "công tác lâu nhất", "thời gian quản lý", "yearsasmanager", "phụ trách lâu nhất"]):
        topic = "hr_leadership"
    elif any(k in q_lower for k in ["thăng chức", "đổi chức danh", "chuyển chức danh", "promotion", "promoted", "bổ nhiệm", "luân chuyển", "tiến cử"]):
        topic = "hr_promotion"
    elif any(k in q_lower for k in ["lương", "salary", "thu nhập", "payroll", "quỹ lương", "tăng lương", "nén lương", "ép lương", "compensation", "đãi ngộ", "mức lương"]):
        topic = "hr_salary"
    elif any(k in q_lower for k in ["nhân viên", "nhân sự", "headcount", "quy mô", "phòng ban", "department", "giới tính", "gender", "nam", "nữ", "tuổi", "age", "nghỉ việc", "turnover", "sa thải", "tuyển dụng"]):
        topic = "hr_workforce"
    elif any(k in q_lower for k in ["salesperson", "sales person", "nhân viên bán hàng", "sales rep", "rep", "best seller", "người bán", "đại diện kinh doanh", "bán nhiều nhất", "bán ít nhất"]):
        topic = "sales_rep"
    elif any(k in q_lower for k in ["lợi nhuận", "biên lợi nhuận", "margin", "profit", "chi phí", "cost", "giá vốn", "cogs", "lãi", "lỗ", "p&l", "pnl"]):
        topic = "finance"
    elif any(k in q_lower for k in ["sản phẩm", "product", "chocolate", "danh mục", "category", "bars", "bites", "mặt hàng"]):
        topic = "product"
    elif any(k in q_lower for k in ["ticket", "khiếu nại", "hỗ trợ", "support", "khách hàng", "customer", "csat", "sla"]):
        topic = "customer_service"
    elif any(k in q_lower for k in ["doanh thu", "doanh số", "sales", "bán hàng", "hộp", "boxes", "amount", "revenue", "tăng trưởng"]):
        topic = "sales_trend"
    else:
        topic = "general"

    return {
        "market": market,
        "time_scope": time_scope,
        "year": year_val,
        "topic": topic,
        "raw_query": q
    }


def generate_chart_smart_explanation(
    title: str,
    df: Optional[pd.DataFrame],
    fig: Optional[go.Figure] = None,
    custom_explanation: str = ""
) -> tuple[str, List[Dict[str, str]], Dict[str, Any]]:
    """Automatically generate business interpretations and detected anomaly findings in both EN and VI."""
    is_en = (get_current_language() == "en")

    if custom_explanation:
        explanation = custom_explanation
    else:
        if is_en:
            explanation = f"The **{title}** chart visualizes distributions and trends of core key metrics, supporting performance evaluation, resource allocation, and timely detection of notable fluctuations."
        else:
            explanation = f"Biểu đồ **{title}** trực quan hóa phân bố và xu hướng của các chỉ số đo lường trọng yếu, hỗ trợ đánh giá hiệu suất, phân bổ nguồn lực và phát hiện kịp thời các biến động đáng chú ý."

    anomalies: List[Dict[str, str]] = []
    stats_summary: Dict[str, Any] = {}

    if df is None or df.empty:
        return explanation, anomalies, stats_summary

    try:
        analysis = analyze_data_anomalies(df)
        stats_summary = analysis.get("summary_stats", {})

        for finding in analysis.get("findings", []):
            msg = finding.get("message", "")
            f_type = finding.get("type", "")
            if "spike" in f_type:
                anomalies.append({
                    "badge": "Spike ↑" if is_en else "Đột Biến Tăng ↑",
                    "color": "#10B981",
                    "text": msg
                })
            elif "drop" in f_type or "sparsity" in f_type:
                anomalies.append({
                    "badge": "Sharp Drop ↓" if is_en else "Sụt Giảm Mạnh ↓",
                    "color": "#EF4444",
                    "text": msg
                })
            elif "outlier" in f_type:
                anomalies.append({
                    "badge": "Outlier" if is_en else "Ngoại Lai (Outlier)",
                    "color": "#F59E0B",
                    "text": msg
                })
            elif "concentration" in f_type:
                anomalies.append({
                    "badge": "Concentration Risk" if is_en else "Rủi Ro Tập Trung",
                    "color": "#8B5CF6",
                    "text": msg
                })
            else:
                anomalies.append({
                    "badge": "Notice" if is_en else "Lưu Ý",
                    "color": "#00F0FF",
                    "text": msg
                })

        main_metric, label_col, val_series = _get_effective_metric_and_label(df, fig)

        if main_metric and val_series is not None and not val_series.empty and len(val_series) >= 2:
            max_val = float(val_series.max())
            min_val = float(val_series.min())
            avg_val = float(val_series.mean())
            total_val = float(val_series.sum())

            max_row_idx = val_series.idxmax()
            min_row_idx = val_series.idxmin()
            max_lbl = str(df.loc[max_row_idx, label_col]) if label_col and label_col in df.columns else ("Maximum" if is_en else "Giá trị lớn nhất")
            min_lbl = str(df.loc[min_row_idx, label_col]) if label_col and label_col in df.columns else ("Minimum" if is_en else "Giá trị nhỏ nhất")
            is_time_period = _is_time_column(label_col, df[label_col]) if label_col and label_col in df.columns else False

            ratio = (max_val / min_val) if min_val > 0 else 0
            if ratio >= 1.5 and not any("Chênh lệch" in a["text"] or "Divergence" in a.get("badge", "") for a in anomalies):
                if is_en:
                    anomalies.append({
                        "badge": "Notable Divergence",
                        "color": "#00F0FF",
                        "text": f"Top position belongs to <b>{max_lbl}</b> ({_format_metric_val(max_val, main_metric)}), differing by <b>{ratio:.1f}x</b> compared to <b>{min_lbl}</b> ({_format_metric_val(min_val, main_metric)})."
                    })
                else:
                    anomalies.append({
                        "badge": "Phân Hóa Rõ Nét",
                        "color": "#00F0FF",
                        "text": f"Vị trí cao nhất thuộc về <b>{max_lbl}</b> ({_format_metric_val(max_val, main_metric)}), chênh lệch <b>{ratio:.1f} lần</b> so với <b>{min_lbl}</b> ({_format_metric_val(min_val, main_metric)})."
                    })

            if len(df) >= 3 and total_val > 0 and label_col and label_col in df.columns and not any(k in main_metric.lower() for k in ["year", "thâm niên", "năm", "rate", "pct", "%"]):
                sorted_df = df.sort_values(by=main_metric, ascending=False)
                top2_sum = float(pd.to_numeric(sorted_df[main_metric], errors="coerce").iloc[:2].sum())
                top2_pct = (top2_sum / total_val) * 100
                top2_names = " & ".join(sorted_df[label_col].iloc[:2].astype(str).tolist())
                if top2_pct >= 40.0 and not any(top2_names in a["text"] for a in anomalies):
                    if is_time_period:
                        if is_en:
                            anomalies.append({
                                "badge": "Key Peak Period",
                                "color": "#3B82F6",
                                "text": f"Two peak periods recorded outstanding volume (<b>{top2_names}</b>), contributing <b>{top2_pct:.1f}%</b> of total {main_metric} across the entire cycle."
                            })
                        else:
                            anomalies.append({
                                "badge": "Kỳ Cao Điểm Trọng Yếu",
                                "color": "#3B82F6",
                                "text": f"Hai kỳ cao điểm ghi nhận kết quả vượt bậc (<b>{top2_names}</b>), đóng góp tới <b>{top2_pct:.1f}%</b> tổng {main_metric} cả chu kỳ."
                            })
                    else:
                        if is_en:
                            anomalies.append({
                                "badge": "Core Contribution",
                                "color": "#3B82F6",
                                "text": f"The top 2 leaders (<b>{top2_names}</b>) account for <b>{top2_pct:.1f}%</b> of total {main_metric} across the whole portfolio."
                            })
                        else:
                            anomalies.append({
                                "badge": "Trọng Tâm Đóng Góp",
                                "color": "#3B82F6",
                                "text": f"Nhóm 2 đơn vị dẫn đầu (<b>{top2_names}</b>) chiếm tới <b>{top2_pct:.1f}%</b> tổng {main_metric} toàn bộ danh mục."
                            })

            if is_time_period and label_col and label_col in df.columns:
                first_val = float(val_series.iloc[0])
                last_val = float(val_series.iloc[-1])
                if first_val > 0:
                    overall_change = ((last_val - first_val) / first_val) * 100
                    t_start = str(df[label_col].iloc[0])
                    t_end = str(df[label_col].iloc[-1])
                    if is_en:
                        trend_word = "growth" if overall_change > 0 else "decline"
                        anomalies.append({
                            "badge": "Full Period Trend",
                            "color": "#10B981" if overall_change > 0 else "#EF4444",
                            "text": f"Across the entire period from {t_start} to {t_end}, metric {main_metric} showed a <b>{trend_word} of {abs(overall_change):.1f}%</b> (from {_format_metric_val(first_val, main_metric)} to {_format_metric_val(last_val, main_metric)})."
                        })
                    else:
                        trend_word = "tăng trưởng" if overall_change > 0 else "sụt giảm"
                        anomalies.append({
                            "badge": "Xu Hướng Toàn Kỳ",
                            "color": "#10B981" if overall_change > 0 else "#EF4444",
                            "text": f"Trong toàn bộ giai đoạn từ {t_start} đến {t_end}, chỉ số {main_metric} có biến động <b>{trend_word} {abs(overall_change):.1f}%</b> (từ {_format_metric_val(first_val, main_metric)} về {_format_metric_val(last_val, main_metric)})."
                        })

        seen_texts = set()
        deduped_anomalies = []
        for a in anomalies:
            clean_t = re.sub(r"<[^>]+>", "", a.get("text", "")).strip()
            sig = clean_t[:40].lower()
            if sig not in seen_texts:
                seen_texts.add(sig)
                deduped_anomalies.append(a)

        def _get_anomaly_rank(item: Dict[str, str]) -> int:
            b = item.get("badge", "")
            if "Phân Hóa" in b or "Divergence" in b:
                return 1
            if "Cao Điểm" in b or "Peak" in b or "Trọng Tâm" in b or "Core" in b:
                return 2
            if "Xu Hướng" in b or "Trend" in b:
                return 3
            if "Đột Biến" in b or "Spike" in b:
                return 4
            if "Sụt Giảm" in b or "Drop" in b:
                return 5
            if "Tập Trung" in b or "Concentration" in b:
                return 6
            if "Ngoại Lai" in b or "Outlier" in b:
                return 7
            return 8

        deduped_anomalies.sort(key=_get_anomaly_rank)
        anomalies = deduped_anomalies[:4] if deduped_anomalies else []

        if not anomalies:
            if is_en:
                anomalies.append({
                    "badge": "Stable Metrics",
                    "color": "#10B981",
                    "text": "The data demonstrates high stability without abrupt breakdowns or unexpected adverse deviations."
                })
            else:
                anomalies.append({
                    "badge": "Chỉ Số Ổn Định",
                    "color": "#10B981",
                    "text": "Dữ liệu thể hiện tính ổn định tương đối, không ghi nhận các điểm gãy đột ngột hoặc hiện tượng phân hóa tiêu cực ngoài dự kiến."
                })

    except Exception as e:
        if is_en:
            anomalies = [{
                "badge": "Observation",
                "color": "#00F0FF",
                "text": f"Chart reflects data from {len(df)} measured records with distinct stratifications."
            }]
        else:
            anomalies = [{
                "badge": "Nhận Xét",
                "color": "#00F0FF",
                "text": f"Biểu đồ phản ánh dữ liệu từ {len(df)} bản ghi đo lường với các phân tầng rõ rệt."
            }]

    return explanation, anomalies, stats_summary


def generate_contextual_action_recommendations(
    title: str,
    user_query: str,
    df: Optional[pd.DataFrame],
    anomalies: List[Dict[str, str]],
    stats_summary: Dict[str, Any],
    fig: Optional[go.Figure] = None
) -> List[Dict[str, str]]:
    """Automatically generate practical, sharp, contextual action recommendations in both EN and VI."""
    if df is None or df.empty:
        return []

    is_en = (get_current_language() == "en")

    effective_query = user_query.strip() if user_query else title
    effective_query = re.sub(r"^Biểu đồ được AI tự động tổng hợp.*cho câu hỏi:\s*[\*\^'\"]*", "", effective_query)
    effective_query = re.sub(r"^AI-generated chart.*for query:\s*[\*\^'\"]*", "", effective_query)
    effective_query = effective_query.replace("*", "").replace("^", "").strip()
    
    ctx = _extract_query_context(effective_query if effective_query else title)
    
    main_metric, label_col, val_series = _get_effective_metric_and_label(df, fig)
    if not main_metric or val_series is None or val_series.empty:
        return []

    is_time_series = _is_time_column(label_col, df[label_col]) if label_col and label_col in df.columns else False
    recs = []
    
    # -------------------------------------------------------------
    # CASE 1: HR LEADERSHIP & MANAGER TENURE
    # -------------------------------------------------------------
    if ctx["topic"] == "hr_leadership" or any(k in str(main_metric).lower() for k in ["yearsasmanager", "thâm niên", "năm quản lý", "tenure", "duration"]):
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        bot_row = sorted_df.iloc[-1]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else ("Senior Leader" if is_en else "Quản lý kỳ cựu nhất")
        bot_name = str(bot_row[label_col]) if label_col and label_col in df.columns else ("Newer Leader" if is_en else "Quản lý có thâm niên ngắn hơn")
        top1_val = float(top1_row[main_metric])
        bot_val = float(bot_row[main_metric])
        top1_fmt = _format_metric_val(top1_val, main_metric)
        bot_fmt = _format_metric_val(bot_val, main_metric)

        if is_en:
            recs.append({
                "icon": svg_target,
                "title": "Succession Planning & Knowledge Transfer",
                "action": f"For the longest-tenured management group (<b>{top1_name}</b>: {top1_fmt}), promptly establish shadowing and mentorship frameworks along with standardized operational knowledge bases to prevent Key-Person Risk during generational transitions."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Leadership Rotation & Strategic Renewal",
                "action": f"Evaluate periodic leadership rotation mechanisms across business units or assign strategic innovation transformation projects to refresh executive momentum and eliminate managerial inertia."
            })
            recs.append({
                "icon": svg_peak,
                "title": "Leadership Pipeline & Fast-Track Talent Pool",
                "action": "Build structured talent fast-tracking programs for high-potential deputies and team leads, ensuring seamless operational continuity and organizational stability."
            })
        else:
            recs.append({
                "icon": svg_target,
                "title": "Quy hoạch Kế thừa & Chuyển giao Tri thức (Succession Planning)",
                "action": f"Đối với nhóm quản lý có thâm niên cao nhất (<b>{top1_name}</b>: {top1_fmt}), doanh nghiệp cần khẩn trương thiết lập chương trình kèm cặp (Shadowing & Mentorship) và chuẩn hóa tài liệu tri thức quản trị nhằm chủ động phòng ngừa rủi ro phụ thuộc nhân sự chủ chốt (Key-Person Risk) khi chuyển giao thế hệ."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Đổi mới Động lực & Luân chuyển Quản lý (Leadership Rotation)",
                "action": f"Nghiên cứu áp dụng cơ chế luân chuyển lãnh đạo định kỳ giữa các bộ phận hoặc giao trọng trách phụ trách các dự án chuyển đổi chiến lược mới để tạo động lực đổi mới sáng tạo, khắc phục sức ỳ quản trị tại các đơn vị có thời gian lãnh đạo kéo dài."
            })
            recs.append({
                "icon": svg_peak,
                "title": "Xây dựng Nguồn Lãnh đạo Kế cận (Leadership Pipeline & Fast-Track)",
                "action": "Thiết lập chương trình bồi dưỡng cán bộ nguồn từ các cấp phó/trưởng nhóm tiềm năng (Talent Pool), sẵn sàng tiếp quản các vị trí then chốt để duy trì sự liên tục và ổn định trong vận hành tổ chức."
            })

    # -------------------------------------------------------------
    # CASE 2: HR PROMOTION & CAREER MOBILITY
    # -------------------------------------------------------------
    elif ctx["topic"] == "hr_promotion" or any(k in str(main_metric).lower() for k in ["promotionrate", "promoted", "thăng chức", "tỷ lệ thăng chức"]):
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else ("High Rate Group" if is_en else "Nhóm tỷ lệ cao")
        top1_val = float(top1_row[main_metric])
        top1_fmt = _format_metric_val(top1_val, main_metric)

        if is_en:
            recs.append({
                "icon": svg_target,
                "title": "Standardize Evaluation Criteria & Transparent Promotion Tracks",
                "action": f"Build competency matrices and transparent performance benchmarks (KPIs/OKRs) for every job family, ensuring equitable career mobility and promotional reviews across all business units."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Ensure Equal Growth Opportunity & DE&I Metrics",
                "action": "Regularly monitor promotion parity across genders and departments to cultivate an inclusive work environment that fosters long-term employee dedication."
            })
            recs.append({
                "icon": svg_peak,
                "title": "Career Mentorship & Leadership Upskilling Programs",
                "action": "Provide leadership and advanced professional upskilling tracks to prepare transitioning employees for elevated responsibilities in newly appointed titles."
            })
        else:
            recs.append({
                "icon": svg_target,
                "title": "Chuẩn hóa Tiêu chí Đánh giá & Lộ trình Thăng tiến Minh bạch",
                "action": f"Xây dựng khung năng lực và tiêu chuẩn đánh giá hiệu suất (KPIs/OKRs) rõ ràng cho từng bậc chức danh, đảm bảo cơ hội thăng tiến và bổ nhiệm được xét duyệt công bằng, minh bạch trên toàn tổ chức."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Đảm bảo Bình đẳng Cơ hội Phát triển & Đa dạng (DE&I)",
                "action": "Duy trì và theo dõi định kỳ tỷ lệ thăng chức giữa các nhóm giới tính và các khối phòng ban, đảm bảo môi trường làm việc hòa nhập, thúc đẩy động lực cống hiến lâu dài."
            })
            recs.append({
                "icon": svg_peak,
                "title": "Chương trình Cố vấn Nghề nghiệp & Đào tạo Nâng cao (Upskilling)",
                "action": "Cung cấp các khóa đào tạo nâng cao năng lực chuyên môn và kỹ năng lãnh đạo giúp nhân sự sẵn sàng đáp ứng tốt yêu cầu khi đảm nhận trọng trách ở vị trí chức danh mới."
            })

    # -------------------------------------------------------------
    # CASE 3: HR SALARY & PAY EQUITY
    # -------------------------------------------------------------
    elif ctx["topic"] == "hr_salary" or any(k in str(main_metric).lower() for k in ["salary", "lương", "payroll", "quỹ lương", "thu nhập"]):
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        bot_row = sorted_df.iloc[-1]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else ("Highest Tier" if is_en else "Mức cao nhất")
        bot_name = str(bot_row[label_col]) if label_col and label_col in df.columns else ("Lowest Tier" if is_en else "Mức thấp nhất")
        top1_val = float(top1_row[main_metric])
        bot_val = float(bot_row[main_metric])

        if is_en:
            recs.append({
                "icon": svg_dollar,
                "title": "Standardize Salary Bands & Market Benchmarking",
                "action": f"Review and calibrate salary bands across role grades (<b>{top1_name}</b> vs <b>{bot_name}</b>) against external market benchmarks to maintain recruitment competitiveness and internal equity."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Audit Salary Compression & Pay Inconsistencies",
                "action": "Audit salary compression gaps between new hires and seasoned staff; allocate targeted compensation adjustments to safeguard mission-critical talent."
            })
            recs.append({
                "icon": svg_target,
                "title": "Optimize Total Rewards Strategy",
                "action": "Combine fixed base salary with dynamic performance bonuses and flexible non-monetary benefits to maximize employee productivity and satisfaction."
            })
        else:
            recs.append({
                "icon": svg_dollar,
                "title": "Chuẩn hóa Khung Dải Lương & So chuẩn Thị trường (Salary Bands)",
                "action": f"Rà soát và cập nhật dải lương theo từng cấp bậc/vị trí (<b>{top1_name}</b> vs <b>{bot_name}</b>) so với mặt bằng thị trường để duy trì sức cạnh tranh tuyển dụng và đảm bảo công bằng nội bộ."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Kiểm soát Nén Lương & Rà soát Chênh lệch Bất thường",
                "action": "Kiểm tra hiện tượng nén lương (Salary Compression) giữa nhân sự mới và kỳ cựu; điều chỉnh ngân sách đãi ngộ hợp lý nhằm tránh tình trạng chảy máu chất xám tại các vị trí cốt lõi."
            })
            recs.append({
                "icon": svg_target,
                "title": "Tối ưu Cơ cấu Đãi ngộ Tổng thể (Total Rewards Strategy)",
                "action": "Kết hợp lương cứng với chính sách thưởng hiệu suất (Performance Bonus) và phúc lợi phi tài chính linh hoạt để kích thích năng suất lao động tối đa."
            })

    # -------------------------------------------------------------
    # CASE 4: HR WORKFORCE & HEADCOUNT
    # -------------------------------------------------------------
    elif ctx["topic"] == "hr_workforce" or any(k in str(main_metric).lower() for k in ["headcount", "nhân sự", "quy mô", "total_emp", "employeecount"]):
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else ("Largest Unit" if is_en else "Đơn vị quy mô lớn nhất")
        top1_val = float(top1_row[main_metric])

        if is_en:
            recs.append({
                "icon": svg_target,
                "title": f"Workforce Headcount & Productivity Optimization for {top1_name}",
                "action": f"Assess actual workload ratios and average productivity per FTE at <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) to right-size headcount and automate repetitive administrative workflows."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Inter-Departmental Resource Load Balancing",
                "action": "Enhance flexible cross-department resource sharing frameworks to alleviate localized capacity bottlenecks during peak demand cycles."
            })
            recs.append({
                "icon": svg_activity,
                "title": "Talent Retention & Proactive Turnover Mitigation",
                "action": "Conduct regular employee engagement (eNPS) pulses and resolve friction points early to sustain top-tier retention rates."
            })
        else:
            recs.append({
                "icon": svg_target,
                "title": f"Tối ưu Định biên & Năng suất Lao động cho {top1_name}",
                "action": f"Đánh giá khối lượng công việc thực tế và năng suất lao động bình quân tại <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) nhằm tối ưu định biên và tự động hóa các tác vụ lặp lại."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Cân đối Nguồn lực & Phối hợp Liên Phòng ban",
                "action": "Tăng cường cơ chế chia sẻ nguồn lực và phối hợp linh hoạt giữa các phòng ban, giải tỏa áp lực quá tải cục bộ trong các giai đoạn cao điểm."
            })
            recs.append({
                "icon": svg_activity,
                "title": "Chiến lược Giữ chân Nhân tài & Giảm Tỷ lệ Nghỉ việc (Retention)",
                "action": "Xây dựng môi trường làm việc hấp dẫn, khảo sát mức độ hài lòng định kỳ (eNPS) và kịp thời tháo gỡ khó khăn cho nhân viên để duy trì tỷ lệ gắn kết cao."
            })

    # -------------------------------------------------------------
    # CASE 5: TIME-SERIES TRENDS
    # -------------------------------------------------------------
    elif is_time_series and len(val_series) >= 2 and label_col and label_col in df.columns:
        max_idx = val_series.idxmax()
        min_idx = val_series.idxmin()
        max_lbl = str(df.loc[max_idx, label_col])
        min_lbl = str(df.loc[min_idx, label_col])
        max_val = float(val_series.max())
        min_val = float(val_series.min())

        max_fmt = _format_metric_val(max_val, main_metric)
        min_fmt = _format_metric_val(min_val, main_metric)
        target_name = ctx["market"] if ctx["market"] else ("market / category" if is_en else "thị trường / danh mục")
        year_ctx = f" ({ctx['year']})" if ctx['year'] else ""

        if is_en:
            if min_val < max_val * 0.9:
                drop_pct = ((max_val - min_val) / max_val) * 100
                recs.append({
                    "icon": svg_slump,
                    "title": f"Mitigate Seasonal Troughs in Period {min_lbl}",
                    "action": f"For <b>{target_name}</b>{year_ctx}, period <b>{min_lbl}</b> recorded the lowest volume ({min_fmt}, down <b>{drop_pct:.1f}%</b> from peak {max_lbl}). Investigate underlying demand slumps and launch mid-year trade incentive campaigns to bridge revenue gaps."
                })
            else:
                recs.append({
                    "icon": svg_balance,
                    "title": f"Smooth Periodical Volatility at {min_lbl}",
                    "action": f"Refine distribution and marketing calendars for <b>{target_name}</b> during <b>{min_lbl}</b> ({min_fmt}) to sustain steady sales velocity throughout the business year."
                })

            recs.append({
                "icon": svg_peak,
                "title": f"Prepare Resources Ahead of Peak Surge at {max_lbl}",
                "action": f"Period <b>{max_lbl}</b> achieved peak volume at <b>{max_fmt}</b>. Ensure advance supply chain procurement from preceding quarters, optimize safety stock, and expand retail distribution in <b>{target_name}</b>."
            })
            recs.append({
                "icon": svg_target,
                "title": "Promote High-Margin Product Lines & Strategic Channels",
                "action": f"Focus promotional investments on high-margin SKU portfolios and core commercial channels in <b>{target_name}</b> to drive profitable and sustainable growth."
            })
        else:
            if min_val < max_val * 0.9:
                drop_pct = ((max_val - min_val) / max_val) * 100
                recs.append({
                    "icon": svg_slump,
                    "title": f"Khắc phục điểm trũng mùa vụ tại kỳ {min_lbl}",
                    "action": f"Đối với <b>{target_name}</b>{year_ctx}, kỳ <b>{min_lbl}</b> ghi nhận mức thấp nhất ({min_fmt}, sụt giảm <b>{drop_pct:.1f}%</b> so với đỉnh {max_lbl}). Doanh nghiệp nên rà soát nguyên nhân giảm cầu cục bộ, triển khai các chương trình kích cầu giữa năm và chiết khấu thương mại nhằm bù đắp khoảng trũng doanh số."
                })
            else:
                recs.append({
                    "icon": svg_balance,
                    "title": f"Tối ưu biên độ dao động tại kỳ {min_lbl}",
                    "action": f"Rà soát kế hoạch tiếp thị và phân phối tại <b>{target_name}</b> trong kỳ <b>{min_lbl}</b> ({min_fmt}) để chủ động kích hoạt các gói ưu đãi, duy trì nhịp độ bán hàng ổn định giữa các kỳ."
                })

            recs.append({
                "icon": svg_peak,
                "title": f"Chuẩn bị nguồn lực đón đầu đà bùng nổ tại kỳ {max_lbl}",
                "action": f"Kỳ <b>{max_lbl}</b> đạt đỉnh cao nhất với <b>{max_fmt}</b>. Cần xây dựng kế hoạch cung ứng sớm từ cuối quý liền trước, tối ưu tồn kho an toàn và mở rộng kênh bán tại <b>{target_name}</b> để khai thác trọn vẹn sức mua tăng vọt trong mùa cao điểm."
            })
            recs.append({
                "icon": svg_target,
                "title": "Đẩy mạnh các dòng sản phẩm chủ lực & Kênh phân phối",
                "action": f"Tập trung phân bổ ngân sách xúc tiến bán hàng vào nhóm sản phẩm có biên lợi nhuận cao và các kênh phân phối trọng điểm tại <b>{target_name}</b> để thúc đẩy tăng trưởng bền vững."
            })

    # -------------------------------------------------------------
    # CASE 6: SALESPEOPLE / REPS / TEAMS PERFORMANCE
    # -------------------------------------------------------------
    elif ctx["topic"] in ("sales_rep", "sales_trend") and (any(k in effective_query.lower() for k in ["nhân viên", "sales", "rep", "người", "team", "đội"]) or (label_col and any(k in str(label_col).lower() for k in ["name", "salesperson", "rep", "person", "team"]))):
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        bot_row = sorted_df.iloc[-1]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else "Top 1"
        bot_name = str(bot_row[label_col]) if label_col and label_col in df.columns else ("Bottom Tier" if is_en else "Nhóm cuối")
        top1_val = float(top1_row[main_metric])
        bot_val = float(bot_row[main_metric])
        
        if is_en:
            recs.append({
                "icon": svg_rank,
                "title": f"Scale Best-Practice Sales Playbooks from {top1_name}",
                "action": f"Codify client engagement playbooks and closing methodologies from <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) into standardized training modules to upskill the entire sales force."
            })
            recs.append({
                "icon": svg_balance,
                "title": f"Territory Re-allocation & Enablement for {bot_name}",
                "action": f"Audit pipeline coverage, assigned territories, and conversion hurdles for lagging sales specialists ({bot_name}: {_format_metric_val(bot_val, main_metric)}) to deliver targeted coaching or re-align territory routing."
            })
            recs.append({
                "icon": svg_dollar,
                "title": "Refine Progressive Incentive Schemes",
                "action": "Implement tiered accelerator commission structures to motivate top-tier quotas while mitigating over-dependence on a few individual contributors."
            })
        else:
            recs.append({
                "icon": svg_rank,
                "title": f"Nhân rộng phương thức Best-Practice từ {top1_name}",
                "action": f"Đóng gói quy trình tiếp cận khách hàng và kỹ năng chốt đơn hiệu quả của <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) thành tài liệu chuẩn để chia sẻ và đào tạo chéo cho toàn đội ngũ bán hàng."
            })
            recs.append({
                "icon": svg_balance,
                "title": f"Tái cơ cấu tệp khách hàng & Hỗ trợ nhóm {bot_name}",
                "action": f"Rà soát danh mục khách hàng tiềm năng, địa bàn phân bổ và các rào cản chuyển đổi của nhóm nhân sự có kết quả thấp hơn ({bot_name}: {_format_metric_val(bot_val, main_metric)}) để có phương án can thiệp, đào tạo lại hoặc tái phân bổ tệp lead."
            })
            recs.append({
                "icon": svg_dollar,
                "title": "Tối ưu cơ chế hoa hồng lũy tiến (Incentive Scheme)",
                "action": "Áp dụng cơ cấu thưởng bậc thang theo các mốc doanh số để khuyến khích bứt phá mục tiêu cá nhân, đồng thời giảm mức độ phụ thuộc doanh thu vào một vài cá nhân chủ chốt."
            })

    # -------------------------------------------------------------
    # CASE 7: PRODUCTS & CATEGORIES
    # -------------------------------------------------------------
    elif ctx["topic"] == "product" or (label_col and any(k in str(label_col).lower() for k in ["product", "category", "danh mục", "sản phẩm", "item"])):
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        bot_row = sorted_df.iloc[-1]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else ("Top Product" if is_en else "Top sản phẩm")
        bot_name = str(bot_row[label_col]) if label_col and label_col in df.columns else ("Lowest SKU" if is_en else "Sản phẩm cuối")
        top1_val = float(top1_row[main_metric])
        bot_val = float(bot_row[main_metric])
        
        if is_en:
            recs.append({
                "icon": svg_box,
                "title": f"Cross-Selling & Bundle Strategy with {top1_name}",
                "action": f"Bundle high-performing hero SKU <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) with slower-moving products (<b>{bot_name}</b>) to maximize Average Order Value (AOV)."
            })
            recs.append({
                "icon": svg_dollar,
                "title": "COGS Optimization & Gross Margin Protection",
                "action": "Review manufacturing cost breakdowns and packaging supplier contracts for high-volume SKUs; renegotiate bulk purchase rates to expand gross margins."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Velocity-Based Inventory Management",
                "action": f"Adjust dynamic safety stock levels according to real-time sales velocity; run promotional clearance campaigns for slow-moving inventory ({bot_name})."
            })
        else:
            recs.append({
                "icon": svg_box,
                "title": f"Chiến lược Cross-Selling & Đóng gói combo với {top1_name}",
                "action": f"Kết hợp dòng sản phẩm chủ lực dẫn đầu <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) với các dòng sản phẩm có vòng quay chậm hơn (<b>{bot_name}</b>) thành combo ưu đãi nhằm tăng giá trị trung bình trên mỗi đơn hàng (AOV)."
            })
            recs.append({
                "icon": svg_dollar,
                "title": "Tối ưu giá vốn & Biên lợi nhuận (COGS Optimization)",
                "action": f"Rà soát lại cơ cấu giá thành sản xuất và chi phí đóng gói của nhóm sản phẩm chiếm sản lượng lớn nhất; đàm phán lại chiết khấu nguyên vật liệu đầu vào để mở rộng biên lợi nhuận gộp."
            })
            recs.append({
                "icon": svg_balance,
                "title": "Quản trị tồn kho theo tốc độ vòng quay",
                "action": f"Điều chỉnh định mức tồn kho an toàn linh hoạt theo sức tiêu thụ thực tế; chủ động giải phóng hàng tồn kho đối với các mã sản phẩm chậm luân chuyển ({bot_name}) bằng chính sách xúc tiến thương mại."
            })

    # -------------------------------------------------------------
    # CASE 8: CUSTOMER SERVICE / TICKETS
    # -------------------------------------------------------------
    elif ctx["topic"] == "customer_service" or (label_col and any(k in str(label_col).lower() for k in ["ticket", "type", "priority", "status", "agent"])):
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else ("Primary Ticket Type" if is_en else "Loại yêu cầu chính")
        top1_val = float(top1_row[main_metric])
        
        if is_en:
            recs.append({
                "icon": svg_activity,
                "title": f"SLA Optimization & Automated Routing for {top1_name}",
                "action": f"Prioritize fast-track routing workflows and canned responses for the highest volume ticket category (<b>{top1_name}</b>: {_format_metric_val(top1_val, main_metric)}); expand self-service FAQ portals to deflect call center load."
            })
            recs.append({
                "icon": svg_target,
                "title": "Root Cause Analysis (RCA) Feedback Loop",
                "action": "Route recurring ticket root causes directly to product and operations teams to resolve systemic glitches at the source."
            })
            recs.append({
                "icon": svg_slump,
                "title": "CSAT Monitoring & Early Escalation Alerts",
                "action": "Set automated early escalation alerts for tickets exceeding target resolution SLAs to preserve customer satisfaction."
            })
        else:
            recs.append({
                "icon": svg_activity,
                "title": f"Tối ưu SLA & Phân luồng tiếp nhận tự động cho {top1_name}",
                "action": f"Ưu tiên phân luồng và thiết lập kịch bản phản hồi nhanh đối với nhóm yêu cầu chiếm tỷ trọng cao nhất (<b>{top1_name}</b>: {_format_metric_val(top1_val, main_metric)}); xây dựng tài liệu trợ giúp tự phục vụ (Self-service/FAQ) để giảm tải cho tổng đài."
            })
            recs.append({
                "icon": svg_target,
                "title": "Xử lý triệt để nguyên nhân gốc rễ (Root Cause Analysis)",
                "action": "Chuyển giao phản hồi khiếu nại định kỳ cho đội ngũ vận hành/sản phẩm để xử lý dứt điểm các lỗi phát sinh thường xuyên, ngăn ngừa phát sinh ticket mới."
            })
            recs.append({
                "icon": svg_slump,
                "title": "Giám sát chỉ số hài lòng khách hàng (CSAT) & Cảnh báo sớm",
                "action": "Thiết lập hệ thống cảnh báo sớm đối với các yêu cầu có thời gian xử lý kéo dài hoặc khiếu nại mức độ nghiêm trọng để can thiệp kịp thời."
            })

    # -------------------------------------------------------------
    # DEFAULT CASE: GENERAL BALANCED DATA PATTERN
    # -------------------------------------------------------------
    else:
        sorted_df = df.sort_values(by=main_metric, ascending=False)
        top1_row = sorted_df.iloc[0]
        bot_row = sorted_df.iloc[-1]
        top1_name = str(top1_row[label_col]) if label_col and label_col in df.columns else ("Leading Segment" if is_en else "Nhóm dẫn đầu")
        bot_name = str(bot_row[label_col]) if label_col and label_col in df.columns else ("Lower Segment" if is_en else "Nhóm thấp hơn")
        top1_val = float(top1_row[main_metric])
        bot_val = float(bot_row[main_metric])
        
        if is_en:
            recs.append({
                "icon": svg_target,
                "title": f"Focus Core Resources on Top Contributors ({top1_name})",
                "action": f"Prioritize operational capacity and strategic investment for <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) to reinforce market dominance."
            })
            recs.append({
                "icon": svg_balance,
                "title": f"Investigate Divergence & Support {bot_name}",
                "action": f"Conduct in-depth performance reviews into friction points at <b>{bot_name}</b> ({_format_metric_val(bot_val, main_metric)}) to recalibrate targets or adjust execution."
            })
            recs.append({
                "icon": svg_activity,
                "title": "Early-Warning Thresholds & Ongoing Telemetry",
                "action": "Deploy continuous telemetry with proactive early-warning threshold triggers to address abnormal variations before business impact."
            })
        else:
            recs.append({
                "icon": svg_target,
                "title": f"Tập trung nguồn lực vào nhóm đóng góp chủ đạo ({top1_name})",
                "action": f"Ưu tiên phân bổ nguồn lực và hỗ trợ vận hành cho <b>{top1_name}</b> ({_format_metric_val(top1_val, main_metric)}) nhằm tối ưu hóa hiệu suất và duy trì vị thế dẫn đầu."
            })
            recs.append({
                "icon": svg_balance,
                "title": f"Rà soát nguyên nhân chênh lệch và hỗ trợ {bot_name}",
                "action": f"Tiến hành đánh giá chuyên sâu các yếu tố cản trở tại <b>{bot_name}</b> ({_format_metric_val(bot_val, main_metric)}) để có kế hoạch tái phân bổ chỉ tiêu hoặc điều chỉnh phương án triển khai phù hợp."
            })
            recs.append({
                "icon": svg_activity,
                "title": "Thiết lập cơ chế theo dõi định kỳ & Ngưỡng cảnh báo sớm",
                "action": "Xây dựng dashboard giám sát liên tục với ngưỡng cảnh báo sớm (Early-warning Thresholds) khi chỉ số có dấu hiệu suy giảm bất thường để kích hoạt hành động can thiệp kịp thời."
            })

    return recs


@st.dialog("Phân Tích Chi Tiết & Điểm Biến Động / In-Depth Chart Analysis", width="large")
def show_chart_zoom_dialog(
    title: str,
    fig: Optional[go.Figure],
    df: Optional[pd.DataFrame] = None,
    badge: str = "Zoom High-Res",
    explanation: str = "",
    custom_anomalies: Optional[List[Dict[str, str]]] = None,
    user_query: str = ""
):
    """Render interactive high-resolution chart modal with AI explanations, anomaly detections, and action plans."""
    is_en = (get_current_language() == "en")

    # Header
    st.markdown(f"""<div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px; margin-bottom: 14px;">
<span style="font-size: 1.15rem; font-weight: 800; color: #FFFFFF; display: flex; align-items: center; gap: 8px;">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#00F0FF" stroke-width="2.2" style="vertical-align:-2px;"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
{title}
</span>
<span class="crm-badge-neon">{badge}</span>
</div>""", unsafe_allow_html=True)

    # 1. High-resolution expanded chart
    if fig is not None:
        fig_large = copy.deepcopy(fig)
        fig_large.update_layout(
            height=640,
            margin=dict(l=35, r=35, t=50, b=65),
            paper_bgcolor="#0F1324",
            plot_bgcolor="#0F1324"
        )
        st.plotly_chart(
            fig_large,
            use_container_width=True,
            config={
                "displayModeBar": True,
                "toImageButtonOptions": {"format": "png", "filename": f"zoom_{title.lower().replace(' ', '_')}", "scale": 2}
            }
        )

    # 2. Generate explanations & anomalies
    smart_exp, auto_anomalies, stats = generate_chart_smart_explanation(title, df, fig, explanation)
    final_anomalies = custom_anomalies if custom_anomalies else auto_anomalies

    # 3. Business Explanation Section
    exp_header = "Business Interpretation & Meaning:" if is_en else "Ý Nghĩa & Diễn Giải Nghiệp Vụ:"
    st.markdown(f"""<div style="background: linear-gradient(145deg, #151A30 0%, #0D1020 100%); border: 1px solid rgba(0, 240, 255, 0.25); border-radius: 12px; padding: 14px 18px; margin-top: 10px; margin-bottom: 14px;">
<div style="font-size: 0.92rem; font-weight: 700; color: #00F0FF; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#00F0FF" stroke-width="2.2" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
<span>{exp_header}</span>
</div>
<div style="font-size: 0.86rem; color: #E2E8F0; line-height: 1.55;">
{smart_exp}
</div>
</div>""", unsafe_allow_html=True)

    # 4. Key Anomalies Section
    anom_header = "Key Anomalies & Notable Deviations:" if is_en else "Điểm Bất Thường & Biến Động Đáng Chú Ý:"
    st.markdown(f"""<div style="font-size: 0.95rem; font-weight: 800; color: #FFFFFF; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2.2" style="vertical-align:-2px;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
<span>{anom_header}</span>
</div>""", unsafe_allow_html=True)

    default_badge = "Notice" if is_en else "Lưu Ý"
    displayed_anomalies = (final_anomalies or [])[:4]
    for item in displayed_anomalies:
        badge_text = item.get("badge", default_badge)
        color = item.get("color", "#00F0FF")
        text = item.get("text", "")
        st.markdown(f"""<div style="background: rgba(255,255,255,0.03); border-left: 3px solid {color}; border-radius: 0 8px 8px 0; padding: 8px 12px; margin-bottom: 8px; display: flex; align-items: flex-start; gap: 10px;">
<span style="background: {color}22; color: {color}; font-size: 0.75rem; font-weight: 700; padding: 2px 8px; border-radius: 6px; white-space: nowrap; border: 1px solid {color}44;">
{badge_text}
</span>
<span style="font-size: 0.84rem; color: #CBD5E1; line-height: 1.45;">
{text}
</span>
</div>""", unsafe_allow_html=True)

    # 4.1 Context-Aware Action Recommendations
    query_for_recs = user_query if user_query else (explanation if "câu hỏi:" in explanation.lower() or "for query:" in explanation.lower() else title)
    recs = generate_contextual_action_recommendations(
        title=title,
        user_query=query_for_recs,
        df=df,
        anomalies=final_anomalies,
        stats_summary=stats,
        fig=fig
    )
    if recs:
        rec_items_html = ""
        for r in recs:
            icon = r.get("icon", SVG_TARGET)
            r_title = r.get("title", "")
            r_act = r.get("action", "")
            rec_items_html += f"""<div style="background: rgba(255,255,255,0.02); border-left: 3px solid #00F0FF; border-radius: 0 8px 8px 0; padding: 10px 14px; margin-bottom: 8px;">
<div style="font-size: 0.88rem; font-weight: 700; color: #00F0FF; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
<span>{icon}</span> <span>{r_title}</span>
</div>
<div style="font-size: 0.83rem; color: #CBD5E1; line-height: 1.5;">
{r_act}
</div>
</div>"""
        
        plan_header = "Direct Action Plan:" if is_en else "Đề Xuất Hành Động Trực Tiếp (Action Plan):"
        st.markdown(f"""<div style="background: linear-gradient(145deg, rgba(0, 240, 255, 0.06) 0%, rgba(15, 23, 42, 0.6) 100%); border: 1px solid rgba(0, 240, 255, 0.25); border-radius: 12px; padding: 14px 18px; margin-top: 10px; margin-bottom: 14px;">
<div style="font-size: 0.92rem; font-weight: 800; color: #FFFFFF; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#00F0FF" stroke-width="2.2" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>
<span>{plan_header}</span>
</div>
<div style="display: flex; flex-direction: column;">
{rec_items_html}
</div>
</div>""", unsafe_allow_html=True)

    # 5. Data table & CSV download
    if df is not None and not df.empty:
        tbl_label = f"View Detailed Data Table ({len(df)} rows)" if is_en else f"Xem Bảng Dữ Liệu Chi Tiết ({len(df)} dòng)"
        dl_label = "Download CSV Data" if is_en else "Tải dữ liệu CSV"
        with st.expander(tbl_label, expanded=False):
            st.dataframe(df, use_container_width=True, hide_index=True)
            csv_data = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=dl_label,
                data=csv_data,
                file_name=f"{title.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                key=f"dl_zoom_csv_{title}"
            )


def render_zoomable_chart_card(
    title: str,
    fig: go.Figure,
    df: Optional[pd.DataFrame] = None,
    badge: str = "Chart",
    explanation: str = "",
    custom_anomalies: Optional[List[Dict[str, str]]] = None,
    key: str = "chart_zoom",
    height: Optional[int] = None,
    user_query: str = ""
):
    """Render a complete cyber chart card with interactive Zoom & Analyze button and bilingual modal."""
    is_en = (get_current_language() == "en")
    zoom_label = "Zoom ↗" if is_en else "Phóng to ↗"
    zoom_help = "Zoom chart & view anomaly analysis" if is_en else "Phóng to biểu đồ & xem phân tích điểm bất thường"

    # Header bar of chart card
    c_head1, c_head2 = st.columns([5, 2])
    with c_head1:
        st.markdown(f"""<div style="display: flex; align-items: center; gap: 8px; padding: 4px 0;">
<span style="font-size: 0.95rem; font-weight: 800; color: #FFFFFF;">{title}</span>
<span class="crm-badge-neon">{badge}</span>
</div>""", unsafe_allow_html=True)
    with c_head2:
        zoom_clicked = st.button(zoom_label, key=f"btn_zoom_{key}", use_container_width=True, help=zoom_help)

    # Render Plotly chart
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Trigger zoom dialog on click
    if zoom_clicked:
        show_chart_zoom_dialog(
            title=title,
            fig=fig,
            df=df,
            badge=badge,
            explanation=explanation,
            custom_anomalies=custom_anomalies,
            user_query=user_query if user_query else title
        )
