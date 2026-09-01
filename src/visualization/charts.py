"""
Intelligent chart generation and auto-visualization using Plotly Express with heuristic column classification,
multi-series color grouping for line/area charts, multi-metric benchmark comparison (Employee vs Team),
full category display (no skipped months), and straight horizontal ticks.
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from src.config import MAX_BAR_CATEGORIES
from src.analytics.heuristics import (
    get_axis_columns,
    get_row_identity_column,
    pick_label_column,
    is_id_like,
)


def render_smart_chart(df: pd.DataFrame, chart_override: str, turn_id: str):
    """Tự động phân loại cột và render biểu đồ phù hợp nhất:
    - Line/Area: Nếu có cột thời gian -> biểu đồ xu hướng theo thời gian, hiển thị đầy đủ 100% các tháng với số nằm ngang thẳng.
    - Bar:
        + Nếu có 1 dòng và nhiều chỉ số đo lường (VD: Nhân viên vs Toàn đội) -> Biểu đồ so sánh Benchmark trực quan.
        + Nếu có nhiều dòng và nhiều chỉ số đo lường -> Biểu đồ cột nhóm (Grouped Bar Chart).
        + Nếu có cột nhãn và cột đo lường -> Biểu đồ cột so sánh.
    - Scatter: Nếu có >= 2 cột số đo lường -> biểu đồ phân tán tương quan.
    """
    if df is None or df.empty:
        st.info("Không có dữ liệu để vẽ biểu đồ.")
        return None

    measure_cols, label_cols, time_col = get_axis_columns(df)
    row_identity_col = get_row_identity_column(df)

    try:
        n_time = df[time_col].nunique(dropna=True) if (time_col and time_col in df.columns) else 0

        if chart_override == "Tự động":
            # Chỉ chọn Line/Area khi có ít nhất 2 mốc thời gian khác nhau để tạo thành đường xu hướng
            if time_col and measure_cols and n_time > 1:
                chosen = "Line"
            elif measure_cols:
                chosen = "Bar"
            elif len(measure_cols) >= 2:
                chosen = "Scatter"
            else:
                st.info("Không tìm thấy dạng biểu đồ phù hợp — dữ liệu không có chỉ số đo lường số học rõ ràng (các cột số hiện có đều là mã định danh).")
                return None
        else:
            chosen = chart_override

        # Fallback nếu chọn Line/Area nhưng không có cột thời gian hoặc chỉ có 1 mốc thời gian
        if chosen in ("Line", "Area") and (not time_col or n_time <= 1):
            if measure_cols:
                if n_time == 1 and chart_override in ("Line", "Area"):
                    st.caption("ℹ️ Dữ liệu chỉ có 1 mốc thời gian duy nhất — tự động hiển thị dưới dạng Bar Chart để hiển thị rõ số liệu.")
                elif not time_col:
                    st.warning(
                        "⚠️ Biểu đồ Line/Area cần một cột thời gian hợp lệ, dữ liệu hiện tại không có. "
                        "Tự động chuyển sang Bar Chart để đảm bảo đúng ý nghĩa thống kê."
                    )
                chosen = "Bar"
            else:
                st.info("Không có cột thời gian hợp lệ và không đủ dữ liệu để vẽ Bar/Scatter thay thế.")
                return None

        # Xác định cột phân nhóm màu sắc cho Line/Area (ví dụ: phân loại theo Region, Product...)
        # CHÚ Ý QUAN TRỌNG: time_color_col TUYỆT ĐỐI KHÔNG ĐƯỢC TRÙNG VỚI time_col
        time_color_col = None
        if chosen in ("Line", "Area") and len(measure_cols) == 1 and label_cols:
            other_labels = [c for c in label_cols if c != time_col]
            if other_labels:
                candidate_col, _, _ = pick_label_column(df, other_labels)
                if candidate_col and candidate_col != time_col and 1 < df[candidate_col].nunique(dropna=True) <= 20:
                    time_color_col = candidate_col

        if chosen == "Line" and time_col and measure_cols:
            sorted_df = df.sort_values(time_col)
            n_time_points = sorted_df[time_col].nunique(dropna=True)
            tick_angle = 0 if n_time_points <= 20 else -45

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
                fig.update_traces(line=dict(width=2.5), marker=dict(size=7))
            else:
                fig = px.line(
                    sorted_df,
                    x=time_col,
                    y=measure_cols if len(measure_cols) > 1 else measure_cols[0],
                    markers=True,
                    title=f"Xu hướng {measure_cols[0]} theo {time_col}" if len(measure_cols) == 1 else f"Xu hướng theo {time_col}",
                    template="plotly_white"
                )
                fig.update_traces(
                    line=dict(width=3, color="#1F4E78"),
                    marker=dict(size=8, color="#1F4E78")
                )
            fig.update_layout(
                xaxis=dict(
                    type="category" if n_time_points <= 36 else None,
                    tickangle=tick_angle,
                    automargin=True
                ),
                margin=dict(l=20, r=20, t=50, b=50)
            )

        elif chosen == "Area" and time_col and measure_cols:
            sorted_df = df.sort_values(time_col)
            n_time_points = sorted_df[time_col].nunique(dropna=True)
            tick_angle = 0 if n_time_points <= 20 else -45

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
                xaxis=dict(
                    type="category" if n_time_points <= 36 else None,
                    tickangle=tick_angle,
                    automargin=True
                ),
                margin=dict(l=20, r=20, t=50, b=50)
            )

        elif chosen == "Bar" and measure_cols:
            # 1. Trường hợp đặc biệt: 1 dòng so sánh nhiều chỉ số (VD: Cá nhân vs Toàn đội / Benchmark)
            if len(df) == 1 and len(measure_cols) >= 2:
                person_name = None
                if label_cols:
                    for c in label_cols:
                        if any(k in c.lower() for k in ["salesperson", "nhân viên", "employee", "people", "name", "tên"]):
                            person_name = str(df[c].iloc[0])
                            break

                comp_labels = []
                comp_values = []
                for m in measure_cols:
                    try:
                        val_num = float(df[m].iloc[0])
                    except Exception:
                        val_num = 0.0

                    m_low = m.lower()
                    if any(k in m_low for k in ["team", "đội", "total", "toàn", "all"]):
                        comp_labels.append(f"Toàn đội ({m})")
                    elif person_name and any(k in m_low for k in ["sold", "amount", "boxes", "sales", "qty", "hộp", "tiền"]):
                        comp_labels.append(f"{person_name} ({m})")
                    else:
                        comp_labels.append(m)
                    comp_values.append(val_num)

                comp_df = pd.DataFrame({
                    "Chỉ số So sánh": comp_labels,
                    "Giá trị": comp_values
                })

                fig = px.bar(
                    comp_df,
                    x="Chỉ số So sánh",
                    y="Giá trị",
                    color="Chỉ số So sánh",
                    text="Giá trị",
                    title="📊 Biểu đồ So sánh Chỉ số: " + (" vs ".join(comp_labels)),
                    template="plotly_white"
                )
                fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                fig.update_layout(
                    xaxis=dict(type="category", tickangle=0, automargin=True),
                    margin=dict(l=20, r=20, t=50, b=50),
                    showlegend=False
                )

            elif label_cols:
                label_name, label_series, consumed_cols = pick_label_column(df, label_cols)
                if label_name is None:
                    st.info("Không tìm thấy cột phù hợp để làm nhãn trục X.")
                    return None

                plot_df = df.copy()
                plot_df[label_name] = label_series.values

                n_unique_labels = plot_df[label_name].nunique(dropna=True)
                total_rows = len(plot_df)

                # Phát hiện dữ liệu thô chưa GROUP BY cần tổng hợp
                needs_aggregation = (
                    row_identity_col is None
                    and n_unique_labels < total_rows
                    and (total_rows / max(1, n_unique_labels)) >= 2.0
                )

                if needs_aggregation:
                    grouped_df = plot_df.groupby(label_name, as_index=False)[measure_cols[0]].sum()
                    grouped_df = grouped_df.sort_values(measure_cols[0], ascending=False)
                    st.caption(
                        f"ℹ️ Dữ liệu thô gồm {total_rows:,} dòng có `{n_unique_labels}` giá trị `{label_name}` lặp lại "
                        f"— đã tự động tính tổng `{measure_cols[0]}` theo từng `{label_name}` để biểu đồ trực quan, chính xác."
                    )
                    plot_df = grouped_df
                    total_rows = len(plot_df)

                    if total_rows > 30:
                        max_display = st.slider(
                            f"Số lượng đối tượng hiển thị trên biểu đồ (Tổng: {total_rows:,})",
                            min_value=min(10, total_rows),
                            max_value=total_rows,
                            value=min(total_rows, MAX_BAR_CATEGORIES),
                            step=5 if total_rows <= 100 else 10,
                            key=f"bar_limit_{turn_id}"
                        )
                        plot_df = plot_df.head(max_display)

                    tick_angle = 0 if len(plot_df) <= 10 else -45
                    fig = px.bar(
                        plot_df, x=label_name, y=measure_cols[0],
                        title=f"Tổng {measure_cols[0]} theo {label_name}",
                        template="plotly_white"
                    )
                    fig.update_layout(
                        xaxis=dict(type="category", tickangle=tick_angle, automargin=True),
                        margin=dict(l=20, r=20, t=50, b=80 if tick_angle != 0 else 50)
                    )

                elif len(measure_cols) >= 2:
                    # So sánh nhiều chỉ số theo từng nhóm đối tượng (Grouped Bar Chart)
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

                    category_order = list(dict.fromkeys(plot_df[label_name].tolist()))
                    tick_angle = 0 if len(plot_df) <= 10 else -45
                    fig = px.bar(
                        plot_df, x=label_name, y=measure_cols,
                        barmode="group",
                        title=f"So sánh các chỉ số ({', '.join(measure_cols)}) theo {label_name}",
                        category_orders={label_name: category_order},
                        template="plotly_white"
                    )
                    fig.update_layout(
                        xaxis=dict(type="category", tickangle=tick_angle, automargin=True),
                        margin=dict(l=20, r=20, t=50, b=80 if tick_angle != 0 else 50)
                    )

                else:
                    has_duplicate_labels = n_unique_labels < total_rows
                    if has_duplicate_labels and row_identity_col and row_identity_col != label_name:
                        plot_df[label_name] = (
                            plot_df[label_name].astype(str) + " (#" + plot_df[row_identity_col].astype(str) + ")"
                        )
                        st.caption(
                            f"ℹ️ Một số dòng trùng nhãn `{label_name}` nhưng là các thực thể khác nhau "
                            f"(khác `{row_identity_col}`) — đã gắn thêm mã `{row_identity_col}` vào nhãn để phân biệt rõ."
                        )

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

                    category_order = list(dict.fromkeys(plot_df[label_name].tolist()))

                    color_col = None
                    candidate_color_cols = [c for c in label_cols if c not in consumed_cols and c in plot_df.columns]
                    if candidate_color_cols:
                        cand = candidate_color_cols[0]
                        if plot_df[cand].nunique(dropna=True) <= 20:
                            color_col = cand

                    tick_angle = 0 if len(plot_df) <= 10 else -45
                    fig = px.bar(
                        plot_df, x=label_name, y=measure_cols[0],
                        color=color_col,
                        title=f"{measure_cols[0]} theo {label_name}" + (f" (Phân loại theo {color_col})" if color_col else ""),
                        category_orders={label_name: category_order},
                        template="plotly_white"
                    )
                    fig.update_traces(
                        texttemplate='%{y:,.2f}' if any('.' in str(v) for v in plot_df[measure_cols[0]]) else '%{y:,.0f}',
                        textposition='outside',
                        width=0.35 if len(plot_df) <= 2 else None
                    )
                    fig.update_layout(
                        xaxis=dict(type="category", tickangle=tick_angle, automargin=True),
                        margin=dict(l=20, r=20, t=50, b=80 if tick_angle != 0 else 50)
                    )
            elif len(df) == 1 and len(measure_cols) == 1:
                val = df[measure_cols[0]].iloc[0]
                val_num = 0 if pd.isna(val) else val
                fig = px.bar(
                    x=[measure_cols[0]],
                    y=[val_num],
                    text=[f"{val_num:,.2f}" if isinstance(val_num, float) else f"{val_num:,.0f}" if isinstance(val_num, int) else str(val_num)],
                    title=f"Chỉ số: {measure_cols[0]}",
                    template="plotly_white"
                )
                fig.update_traces(textposition="outside", marker_color="#1F4E78", width=0.35)
                fig.update_layout(
                    xaxis_title="",
                    yaxis_title=measure_cols[0],
                    margin=dict(l=20, r=20, t=50, b=50)
                )
            else:
                st.info("Không tìm thấy cột phù hợp để làm nhãn trục X.")
                return None

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
        else:
            st.info("Không thể vẽ biểu đồ với các cột hiện có.")
            return None

        st.plotly_chart(fig, width='stretch', key=f"chart_{turn_id}")
        return fig

    except Exception as e:
        st.info(f"Chưa thể tự động vẽ biểu đồ: {str(e)}")
        return None
