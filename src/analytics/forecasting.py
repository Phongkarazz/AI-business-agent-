"""
Deterministic time-series forecasting using linear regression.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from src.config import BOUNDED_PERIOD_KEYWORDS, FORECAST_METHOD_NAME
from .heuristics import find_time_column, get_axis_columns


def forecast_series(df: pd.DataFrame, periods: int = 3):
    """Thực hiện dự báo xu hướng tuyến tính trên chuỗi thời gian."""
    x_col = find_time_column(df)
    if not x_col:
        return None, "Dữ liệu không có cột thời gian hợp lệ (ngày/tháng/quý/năm) nên không thể dự báo xu hướng cho kết quả này."

    measure_cols, _, _ = get_axis_columns(df)
    if not measure_cols:
        return None, "Không tìm thấy chỉ số đo lường số học phù hợp để dự báo (các cột số hiện có là mã định danh, ví dụ ID/mã nhân viên)."
    if len(df) < 3:
        return None, "Cần tối thiểu 3 dòng dữ liệu để dự báo."

    y_col = measure_cols[0]

    df_sorted = df.copy()
    try:
        df_sorted = df_sorted.sort_values(x_col)
    except Exception:
        pass
    df_sorted = df_sorted.reset_index(drop=True)

    y = df_sorted[y_col].values.astype(float)
    n = len(y)
    x_idx = np.arange(n)
    coeffs = np.polyfit(x_idx, y, 1)
    future_idx = np.arange(n, n + periods)
    future_vals = np.polyval(coeffs, future_idx)

    is_bounded_period = any(k in str(x_col).lower() for k in BOUNDED_PERIOD_KEYWORDS)
    is_numeric_x = pd.api.types.is_numeric_dtype(df_sorted[x_col])

    if is_bounded_period:
        future_x = [f"Kỳ +{i+1}" for i in range(periods)]
    elif is_numeric_x:
        step = 1
        if n >= 2:
            step = df_sorted[x_col].iloc[-1] - df_sorted[x_col].iloc[-2]
            if step == 0:
                step = 1
        last_x = df_sorted[x_col].iloc[-1]
        future_x = [last_x + step * (i + 1) for i in range(periods)]
    else:
        future_x = [f"Kỳ +{i+1}" for i in range(periods)]

    hist_x = df_sorted[x_col].tolist()
    bridge_x = [hist_x[-1]] + future_x
    bridge_y = [y[-1]] + list(future_vals)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_x, y=y,
        mode="lines+markers",
        name="Thực tế",
        line=dict(color="#4C9AFF", width=2.5)
    ))
    fig.add_trace(go.Scatter(
        x=bridge_x, y=bridge_y,
        mode="lines+markers",
        name="Dự báo",
        line=dict(color="#FF6B6B", width=2.5, dash="dash")
    ))
    fig.update_layout(
        title=f"Dự báo xu hướng theo {x_col}",
        xaxis_title=x_col,
        yaxis_title=y_col,
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig, FORECAST_METHOD_NAME
