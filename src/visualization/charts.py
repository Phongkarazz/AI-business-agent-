"""
Smart Plotly charting module with automatic visualization selection, multi-series grouping,
dynamic limit slider, and edge-case guards.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import MAX_BAR_CATEGORIES
from src.analytics.heuristics import (
    get_axis_columns,
    get_row_identity_column,
    pick_label_column,
    is_id_like,
)


def render_smart_chart(df: pd.DataFrame, chart_override: str, turn_id: str):
    """Vẽ biểu đồ thông minh dựa trên đặc tính dữ liệu với hỗ trợ phân nhóm đa tuyến (multi-series)."""
    if df is None or df.empty:
        st.info("Không có dữ liệu để vẽ biểu đồ.")
        return

    cols = df.columns.tolist()
    if len(cols) < 2:
        st.info("Dữ liệu cần tối thiểu 2 cột để vẽ biểu đồ.")
        return

    if len(df) <= 1:
        if len(df) == 1:
            row = df.iloc[0]
            summary = " · ".join(f"**{c}**: {row[c]}" for c in df.columns)
            st.info(f"📌 Chỉ có 1 dòng kết quả, không cần biểu đồ: {summary}")
        else:
            st.info("Không có dữ liệu để vẽ biểu đồ.")
        return

    measure_cols, cat_cols, time_col = get_axis_columns(df)
    label_cols = [c for c in cat_cols if c != time_col]
    row_identity_col = get_row_identity_column(df)

    try:
        if chart_override == "Tự động":
            if time_col and measure_cols:
                chosen = "Line"
            elif label_cols and measure_cols:
                chosen = "Bar"
            elif len(measure_cols) >= 2:
                chosen = "Scatter"
            else:
                st.info("Không tìm thấy dạng biểu đồ phù hợp — dữ liệu không có chỉ số đo lường số học rõ ràng (các cột số hiện có đều là mã định danh).")
                return
        else:
            chosen = chart_override

        # Fallback nếu chọn Line/Area nhưng không có cột thời gian
        if chosen in ("Line", "Area") and not time_col:
            if label_cols and measure_cols:
                st.warning(
                    "⚠️ Biểu đồ Line/Area cần một cột thời gian hợp lệ, dữ liệu hiện tại không có. "
                    "Tự động chuyển sang Bar Chart để đảm bảo đúng ý nghĩa thống kê."
                )
                chosen = "Bar"
            else:
                st.info("Không có cột thời gian hợp lệ và không đủ dữ liệu để vẽ Bar/Scatter thay thế.")
                return

        # Xác định cột phân nhóm màu sắc cho Line/Area (ví dụ: phân loại theo Region, Product...)
        time_color_col = None
        if chosen in ("Line", "Area") and len(measure_cols) == 1 and label_cols:
            candidate_col, _, _ = pick_label_column(df, label_cols)
            if candidate_col and df[candidate_col].nunique(dropna=True) <= 20:
                time_color_col = candidate_col

        if chosen == "Line" and time_col and measure_cols:
            sorted_df = df.sort_values(time_col)
            if time_color_col:
                fig = px.line(
                    sorted_df,
                    x=time_col,
                    y=measure_cols[0],
                    color=time_color_col,
                    markers=True,
                    title=f"Xu hướng {measure_cols[0]} theo {time_col} (Phân nhóm theo {time_color_col})",
                    template="plotly_white"
                )
            else:
                fig = px.line(
                    sorted_df,
                    x=time_col,
                    y=measure_cols if len(measure_cols) > 1 else measure_cols[0],
                    markers=True,
                    title=f"Xu hướng theo {time_col}",
                    template="plotly_white"
                )
            fig.update_layout(
                xaxis=dict(tickangle=-45, automargin=True),
                margin=dict(l=20, r=20, t=50, b=50)
            )

        elif chosen == "Area" and time_col and measure_cols:
            sorted_df = df.sort_values(time_col)
            if time_color_col:
                fig = px.area(
                    sorted_df,
                    x=time_col,
                    y=measure_cols[0],
                    color=time_color_col,
                    title=f"Xu hướng (Area) {measure_cols[0]} theo {time_col} (Phân nhóm theo {time_color_col})",
                    template="plotly_white"
                )
            else:
                fig = px.area(
                    sorted_df,
                    x=time_col,
                    y=measure_cols if len(measure_cols) > 1 else measure_cols[0],
                    title=f"Xu hướng (Area) theo {time_col}",
                    template="plotly_white"
                )
            fig.update_layout(
                xaxis=dict(tickangle=-45, automargin=True),
                margin=dict(l=20, r=20, t=50, b=50)
            )

        elif chosen == "Bar" and label_cols and measure_cols:
            label_name, label_series, consumed_cols = pick_label_column(df, label_cols)
            if label_name is None:
                st.info("Không tìm thấy cột phù hợp để làm nhãn trục X.")
                return

            plot_df = df.copy()
            plot_df[label_name] = label_series.values

            n_unique_labels = plot_df[label_name].nunique(dropna=True)
            total_rows = len(plot_df)

            # Phát hiện dữ liệu thô chưa GROUP BY cần tổng hợp
            needs_aggregation = (
                row_identity_col is None
                and n_unique_labels < total_rows * 0.7
                and n_unique_labels < 30
            )

            if needs_aggregation:
                agg_df = plot_df.groupby(label_name, as_index=False)[measure_cols[0]].mean()
                category_order = list(dict.fromkeys(agg_df[label_name].tolist()))
                fig = px.bar(
                    agg_df, x=label_name, y=measure_cols[0],
                    title=f"{measure_cols[0]} trung bình theo {label_name}",
                    category_orders={label_name: category_order},
                    template="plotly_white"
                )
                fig.update_layout(
                    xaxis=dict(type="category", tickangle=-45, automargin=True),
                    margin=dict(l=20, r=20, t=50, b=80)
                )
                st.caption(
                    f"📊 Dữ liệu có nhiều dòng trùng nhãn `{label_name}` ({n_unique_labels} nhãn / "
                    f"{total_rows} dòng) — biểu đồ hiển thị **giá trị trung bình** theo từng nhãn thay vì "
                    f"chồng toàn bộ dòng thô. Xem dữ liệu chi tiết trong bảng phía trên."
                )
            else:
                # Gắn ID vào nhãn nếu các thực thể khác nhau bị trùng tên
                if row_identity_col and plot_df[label_name].duplicated().any():
                    plot_df[label_name] = (
                        plot_df[label_name] + " (#" + plot_df[row_identity_col].astype(str) + ")"
                    )
                    st.caption(
                        f"ℹ️ Một số dòng trùng nhãn `{label_name}` nhưng là các thực thể khác nhau "
                        f"(khác `{row_identity_col}`) — đã gắn thêm mã `{row_identity_col}` vào nhãn để phân biệt rõ."
                    )

                # Cho phép người dùng tùy chọn số lượng cột hiển thị nếu kết quả lớn hơn 30 dòng
                if total_rows > 30:
                    max_display = st.slider(
                        f"Số lượng đối tượng hiển thị trên biểu đồ (Tổng kết quả: {total_rows:,} dòng)",
                        min_value=min(10, total_rows),
                        max_value=total_rows,
                        value=min(total_rows, MAX_BAR_CATEGORIES),
                        step=5 if total_rows <= 100 else 10,
                        key=f"bar_limit_{turn_id}"
                    )
                    plot_df = plot_df.head(max_display)
                else:
                    max_display = total_rows

                category_order = list(dict.fromkeys(plot_df[label_name].tolist()))

                color_col = None
                candidate_color_cols = [c for c in label_cols if c not in consumed_cols and c in plot_df.columns]
                if candidate_color_cols:
                    cand = candidate_color_cols[0]
                    if plot_df[cand].nunique(dropna=True) <= 20:
                        color_col = cand

                fig = px.bar(
                    plot_df, x=label_name, y=measure_cols[0],
                    color=color_col,
                    title=f"{measure_cols[0]} theo {label_name}" + (f" (Phân loại theo {color_col})" if color_col else ""),
                    category_orders={label_name: category_order},
                    template="plotly_white"
                )
                fig.update_layout(
                    xaxis=dict(type="category", tickangle=-45, automargin=True),
                    margin=dict(l=20, r=20, t=50, b=80)
                )

        elif chosen == "Scatter" and len(measure_cols) >= 2:
            x_m = measure_cols[0]
            y_m = measure_cols[1]
            hover_name = label_cols[0] if label_cols else None
            fig = px.scatter(
                df, x=x_m, y=y_m,
                hover_name=hover_name,
                title=f"Tương quan giữa {x_m} và {y_m}",
                template="plotly_white"
            )
            fig.update_layout(margin=dict(l=20, r=20, t=50, b=50))
        st.plotly_chart(fig, width='stretch', key=f"chart_{turn_id}")
        return fig

    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {str(e)}")
        return None
