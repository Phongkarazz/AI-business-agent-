"""
Smart Plotly charting module with automatic visualization selection and edge-case guards.
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
    """Vẽ biểu đồ thông minh dựa trên đặc tính dữ liệu với các lớp bảo vệ chống nhầm lẫn."""
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

        if chosen == "Line" and time_col and measure_cols:
            fig = px.line(
                df.sort_values(time_col),
                x=time_col,
                y=measure_cols,
                markers=True,
                title=f"Xu hướng theo {time_col}",
                template="plotly_white"
            )
        elif chosen == "Area" and time_col and measure_cols:
            fig = px.area(
                df.sort_values(time_col),
                x=time_col,
                y=measure_cols,
                title=f"Xu hướng (Area) theo {time_col}",
                template="plotly_white"
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
                and n_unique_labels < MAX_BAR_CATEGORIES
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
                fig.update_xaxes(type="category")
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

                was_truncated = total_rows > MAX_BAR_CATEGORIES
                if was_truncated:
                    plot_df = plot_df.head(MAX_BAR_CATEGORIES)

                category_order = list(dict.fromkeys(plot_df[label_name].tolist()))

                color_col = None
                candidate_color_cols = [c for c in label_cols if c not in consumed_cols and c in plot_df.columns]
                for c in candidate_color_cols:
                    if not is_id_like(c) and df[c].nunique(dropna=True) <= 8:
                        color_col = c
                        break

                fig = px.bar(
                    plot_df, x=label_name, y=measure_cols[0], color=color_col,
                    title=f"{measure_cols[0]} theo {label_name}",
                    category_orders={label_name: category_order},
                    template="plotly_white"
                )
                fig.update_xaxes(type="category")
                if was_truncated:
                    st.caption(
                        f"📊 Đang hiển thị {MAX_BAR_CATEGORIES}/{total_rows} dòng đầu tiên để biểu đồ dễ đọc — "
                        f"xem đầy đủ {total_rows} dòng trong bảng dữ liệu phía trên."
                    )
        elif chosen == "Scatter" and len(measure_cols) >= 2:
            fig = px.scatter(
                df, x=measure_cols[0], y=measure_cols[1],
                title="Biểu đồ phân tích tương quan",
                template="plotly_white"
            )
        elif len(measure_cols) >= 2:
            fig = px.scatter(
                df, x=measure_cols[0], y=measure_cols[1],
                title="Biểu đồ phân tích tương quan",
                template="plotly_white"
            )
        else:
            st.info("Không đủ dữ liệu phù hợp cho loại biểu đồ đã chọn (thiếu chỉ số đo lường số học).")
            return

        st.plotly_chart(fig, width='stretch', key=f"chart_{turn_id}")
    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {e}")
