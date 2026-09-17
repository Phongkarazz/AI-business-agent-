"""
Enterprise-grade adaptive time-series forecasting using Holt-Winters & Exponential Smoothing (ETS).
Features 95% Confidence Interval Ribbons (Fan Charts), non-negative financial boundary constraints,
trend damping, and seamless categorical X-axis formatting.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from src.config import FORECAST_METHOD_NAME
from .heuristics import find_time_column, get_axis_columns


def _fit_adaptive_holt_winters(y: np.ndarray, periods: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """Khớp mô hình dự báo thích ứng Holt-Winters / ETS hoặc Holt Damped Smoothing
    kèm tính toán Dải khoảng tin cậy 95% (P10 - P50 - P90) chuẩn quản trị doanh nghiệp.
    """
    n = len(y)
    is_non_negative = bool(np.all(y >= 0))

    # Thử nghiệm sử dụng statsmodels ExponentialSmoothing nếu có sẵn
    statsmodels_success = False
    future_base = None
    se = None
    method_name = ""

    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        # Trường hợp N >= 8: Thử nghiệm Holt-Winters có Damped Trend
        if n >= 8:
            seasonal_periods = None
            if n >= 24:
                seasonal_periods = 12
            elif n >= 8 and n % 4 == 0:
                seasonal_periods = 4

            if seasonal_periods and n >= seasonal_periods * 2:
                model = ExponentialSmoothing(
                    y,
                    trend="add",
                    damped_trend=True,
                    seasonal="add",
                    seasonal_periods=seasonal_periods,
                    initialization_method="estimated"
                ).fit(optimized=True)
                method_name = f"Holt-Winters ETS (Trend Damped + Mùa vụ {seasonal_periods} kỳ) + Dải tin cậy 95%"
            else:
                model = ExponentialSmoothing(
                    y,
                    trend="add",
                    damped_trend=True,
                    initialization_method="estimated"
                ).fit(optimized=True)
                method_name = "Holt Damped Trend ETS (San bằng số mũ thích ứng) + Dải tin cậy 95%"

            future_base = model.forecast(periods)
            residuals = y - model.fittedvalues
            se = np.std(residuals, ddof=2) if n > 2 else np.std(residuals)
            statsmodels_success = True
        elif n >= 4:
            model = ExponentialSmoothing(
                y,
                trend="add",
                damped_trend=False,
                initialization_method="estimated"
            ).fit(optimized=True)
            method_name = "Holt Linear Smoothing (Xu thế san bằng số mũ) + Dải tin cậy 95%"
            future_base = model.forecast(periods)
            residuals = y - model.fittedvalues
            se = np.std(residuals, ddof=1) if n > 1 else np.std(residuals)
            statsmodels_success = True
    except Exception:
        statsmodels_success = False

    # Thuật toán thuần NumPy: Holt's Damped Trend Exponential Smoothing (Dự phòng độc lập)
    if not statsmodels_success or future_base is None:
        alpha = 0.4
        beta = 0.2
        phi = 0.90  # Hệ số suy giảm lực cản xu thế (Damping factor)

        level = np.zeros(n)
        trend = np.zeros(n)
        fitted = np.zeros(n)

        level[0] = y[0]
        trend[0] = y[1] - y[0] if n > 1 else 0
        fitted[0] = y[0]

        for t in range(1, n):
            fitted[t] = level[t - 1] + phi * trend[t - 1]
            level[t] = alpha * y[t] + (1 - alpha) * (level[t - 1] + phi * trend[t - 1])
            trend[t] = beta * (level[t] - level[t - 1]) + (1 - beta) * phi * trend[t - 1]

        future_base_list = []
        last_level = level[-1]
        last_trend = trend[-1]

        for h in range(1, periods + 1):
            damping_sum = sum(phi ** i for i in range(1, h + 1))
            y_h = last_level + damping_sum * last_trend
            future_base_list.append(y_h)

        future_base = np.array(future_base_list)
        residuals = y[1:] - fitted[1:] if n > 1 else np.zeros(1)
        se = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else (float(np.std(y)) * 0.1 if len(y) > 1 else 1.0)
        method_name = "Holt's Damped Exponential Smoothing (Chuẩn dự báo doanh nghiệp) + Dải tin cậy 95%"

    future_base = np.asarray(future_base, dtype=float)
    if se is None or np.isnan(se) or se <= 0:
        se = float(np.std(y)) * 0.15 if len(y) > 1 else 1.0

    # Tính toán dải khoảng tin cậy 95% (P10 sàn rủi ro - P90 trần tăng trưởng)
    future_lower_list = []
    future_upper_list = []

    for h in range(1, periods + 1):
        h_se = se * np.sqrt(h) * 1.96
        val_pred = future_base[h - 1]
        lower_val = val_pred - h_se
        upper_val = val_pred + h_se

        if is_non_negative:
            lower_val = max(0.0, lower_val)
            val_pred = max(0.0, val_pred)
            future_base[h - 1] = val_pred

        future_lower_list.append(lower_val)
        future_upper_list.append(upper_val)

    future_lower = np.array(future_lower_list)
    future_upper = np.array(future_upper_list)

    return future_base, future_lower, future_upper, method_name


def forecast_series(df: pd.DataFrame, periods: int = 3):
    """Thực hiện dự báo chuỗi thời gian thích ứng Holt-Winters & ETS kèm Dải khoảng tin cậy 95%
    với định dạng trục X đồng nhất và biểu đồ Plotly Fan Chart chuyên nghiệp.
    """
    x_col = find_time_column(df)
    if not x_col:
        return None, "Dữ liệu không có cột thời gian hợp lệ (ngày/tháng/quý/năm) nên không thể dự báo xu hướng cho kết quả này."

    measure_cols, _, _ = get_axis_columns(df)
    if not measure_cols:
        return None, "Không tìm thấy chỉ số đo lường số học phù hợp để dự báo (các cột số hiện có là mã định danh, ví dụ ID/mã nhân viên)."
    if len(df) < 3:
        return None, "Cần tối thiểu 3 điểm dữ liệu thời gian để tiến hành dự báo chuỗi thích ứng."

    y_col = measure_cols[0]

    df_sorted = df.copy()
    try:
        df_sorted = df_sorted.sort_values(x_col)
    except Exception:
        pass
    df_sorted = df_sorted.reset_index(drop=True)

    y = df_sorted[y_col].values.astype(float)
    future_base, future_lower, future_upper, method_name = _fit_adaptive_holt_winters(y, periods=periods)

    # 1. Chuẩn hóa nhãn trục X thành danh mục String đồng nhất
    raw_x_values = df_sorted[x_col].tolist()
    x_col_lower = str(x_col).lower()

    # Nhận diện nếu là cột Tháng số học (1 đến 12)
    is_month_num = (
        ("month" in x_col_lower or "thang" in x_col_lower or "tháng" in x_col_lower)
        and pd.api.types.is_numeric_dtype(df_sorted[x_col])
        and all(1 <= v <= 12 for v in raw_x_values if pd.notnull(v))
    )

    # Nhận diện nếu là cột Năm số học (VD: 2020, 2021, 2022)
    is_year_num = (
        ("year" in x_col_lower or "nam" in x_col_lower or "năm" in x_col_lower)
        and pd.api.types.is_numeric_dtype(df_sorted[x_col])
        and all(1900 <= v <= 2100 for v in raw_x_values if pd.notnull(v))
    )

    if is_month_num:
        hist_x = [f"T{int(v)}" for v in raw_x_values]
        future_x = [f"+{i+1} (Dự báo)" for i in range(periods)]
    elif is_year_num:
        hist_x = [str(int(v)) for v in raw_x_values]
        last_year = int(raw_x_values[-1])
        future_x = [f"{last_year + i + 1} (Dự báo)" for i in range(periods)]
    else:
        hist_x = [str(v) for v in raw_x_values]
        future_x = [f"+{i+1} (Dự báo)" for i in range(periods)]

    # Điểm cầu nối nối giữa Thực tế và Dự báo
    bridge_x = [hist_x[-1]] + future_x
    bridge_y_base = [y[-1]] + list(future_base)
    bridge_y_lower = [y[-1]] + list(future_lower)
    bridge_y_upper = [y[-1]] + list(future_upper)

    # 2. Khởi tạo biểu đồ Plotly Fan Chart với Dải tin cậy 95%
    fig = go.Figure()

    # 2.1 Đường Thực tế (Màu xanh dương đậm)
    fig.add_trace(go.Scatter(
        x=hist_x,
        y=y,
        mode="lines+markers",
        name="Thực tế (Historical)",
        line=dict(color="#2563EB", width=2.8),
        marker=dict(size=7, color="#2563EB"),
        hovertemplate="<b>Thực tế</b><br>%{x}<br>Giá trị: <b>%{y:,.2f}</b><extra></extra>"
    ))

    # 2.2 Trần Dải tin cậy Upper 95% (Invisible boundary line)
    fig.add_trace(go.Scatter(
        x=bridge_x,
        y=bridge_y_upper,
        mode="lines",
        name="Trần Lạc quan (+95%)",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip"
    ))

    # 2.3 Sàn Dải tin cậy Lower 95% + Tô màu bóng mờ Ribbon (Fan Chart Envelope)
    fig.add_trace(go.Scatter(
        x=bridge_x,
        y=bridge_y_lower,
        mode="lines",
        name="Dải tin cậy 95% (Risk Corridor)",
        fill="tonexty",
        fillcolor="rgba(239, 68, 68, 0.13)",
        line=dict(width=0),
        hovertemplate="<b>Dải biến động 95%</b><br>%{x}<br>Sàn thận trọng: %{y:,.2f}<extra></extra>"
    ))

    # 2.4 Đường Dự báo cơ sở Base Case (Nét đứt màu đỏ cam nổi bật)
    fig.add_trace(go.Scatter(
        x=bridge_x,
        y=bridge_y_base,
        mode="lines+markers",
        name="Dự báo cơ sở (Base Case P50)",
        line=dict(color="#EF4444", width=2.8, dash="dash"),
        marker=dict(size=8, color="#EF4444", symbol="circle"),
        hovertemplate="<b>Dự báo cơ sở (Base Case)</b><br>%{x}<br>Kỳ vọng: <b>%{y:,.2f}</b><extra></extra>"
    ))

    all_x_len = len(hist_x) + len(future_x)
    tick_angle = -45 if all_x_len >= 8 else 0

    fig.update_layout(
        title=f"📈 Biểu đồ Dự báo Xu hướng Thích ứng theo {x_col} (+{periods} kỳ tương lai)",
        xaxis_title=x_col,
        yaxis_title=y_col,
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=60 if tick_angle != 0 else 30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified"
    )

    # Ép kiểu trục X thành category và tự động xoay nghiêng để các mốc thời gian không bị đè chồng
    fig.update_xaxes(type="category", tickangle=tick_angle, automargin=True)

    return fig, method_name
