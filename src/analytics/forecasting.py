"""
Deterministic time-series forecasting using linear regression.
Features unified categorical X-axis formatting to guarantee seamless chart rendering.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from src.config import BOUNDED_PERIOD_KEYWORDS, FORECAST_METHOD_NAME
from .heuristics import find_time_column, get_axis_columns


def forecast_series(df: pd.DataFrame, periods: int = 3):
    """Thực hiện dự báo xu hướng tuyến tính xác định trên chuỗi thời gian với định dạng trục X đồng nhất."""
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

    # 1. Chuẩn hóa nhãn trục X thành danh mục String đồng nhất
    raw_x_values = df_sorted[x_col].tolist()
    x_col_lower = str(x_col).lower()

    # Nhận diện nếu là cột Tháng số học (1 đến 12)
    is_month_num = (
        ("month" in x_col_lower or "thang" in x_col_lower)
        and pd.api.types.is_numeric_dtype(df_sorted[x_col])
        and all(1 <= v <= 12 for v in raw_x_values if pd.notnull(v))
    )

    # Nhận diện nếu là cột Năm số học (VD: 2020, 2021, 2022)
    is_year_num = (
        ("year" in x_col_lower or "nam" in x_col_lower)
        and pd.api.types.is_numeric_dtype(df_sorted[x_col])
        and all(1900 <= v <= 2100 for v in raw_x_values if pd.notnull(v))
    )

    if is_month_num:
        hist_x = [f"Tháng {int(v)}" for v in raw_x_values]
        future_x = [f"Kỳ +{i+1} (Dự báo)" for i in range(periods)]
    elif is_year_num:
        hist_x = [f"Năm {int(v)}" for v in raw_x_values]
        last_year = int(raw_x_values[-1])
        future_x = [f"Năm {last_year + i + 1} (Dự báo)" for i in range(periods)]
    else:
        hist_x = [str(v) for v in raw_x_values]
        future_x = [f"Kỳ +{i+1} (Dự báo)" for i in range(periods)]

    # Điểm cầu nối nối giữa Thực tế và Dự báo
    bridge_x = [hist_x[-1]] + future_x
    bridge_y = [y[-1]] + list(future_vals)

    # 2. Khởi tạo biểu đồ Plotly với định dạng chuyên nghiệp
    fig = go.Figure()

    # Đường Thực tế (Màu xanh dương)
    fig.add_trace(go.Scatter(
        x=hist_x,
        y=y,
        mode="lines+markers",
        name="Thực tế",
        line=dict(color="#2563EB", width=2.5),
        marker=dict(size=7, color="#2563EB"),
        hovertemplate="<b>Thực tế</b><br>%{x}<br>Giá trị: %{y:,.2f}<extra></extra>"
    ))

    # Đường Dự báo (Nét đứt màu đỏ cam)
    fig.add_trace(go.Scatter(
        x=bridge_x,
        y=bridge_y,
        mode="lines+markers",
        name="Dự báo",
        line=dict(color="#EF4444", width=2.5, dash="dash"),
        marker=dict(size=8, color="#EF4444", symbol="circle"),
        hovertemplate="<b>Dự báo</b><br>%{x}<br>Giá trị dự phòng: %{y:,.2f}<extra></extra>"
    ))

    fig.update_layout(
        title=f"📈 Biểu đồ Dự báo Xu hướng theo {x_col} (+{periods} kỳ tương lai)",
        xaxis_title=x_col,
        yaxis_title=y_col,
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified"
    )

    # Ép kiểu trục X thành category để Plotly luôn hiển thị đầy đủ mọi mốc dự báo với số thẳng hàng
    fig.update_xaxes(type="category", tickangle=0, automargin=True)

    return fig, FORECAST_METHOD_NAME
