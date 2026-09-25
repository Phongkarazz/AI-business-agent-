"""
High-End Cyber/Neon Multi-Layer Dashboard Plotly Chart Builders.
Styled with glassmorphism aesthetics and glowing gradients.
Fully localized with instant reactive bilingual support (Vietnamese & English).
"""

import plotly.graph_objects as go
import pandas as pd
from src.i18n import get_current_language


def build_latency_wave_chart(
    df: pd.DataFrame,
    name_1: str = "First Reply (h)",
    name_2: str = "Full Resolve (h)",
    peak_text: str = "04 October<br><b>2.5 hours</b>"
) -> go.Figure:
    """Biểu đồ sóng kép (Top Right Wave Chart) hỗ trợ đa lĩnh vực."""
    is_en = (get_current_language() == "en")
    fig = go.Figure()
    x_vals = df["DayLabel"].tolist() if "DayLabel" in df else [f"D{i+1}" for i in range(len(df))]
    
    # 1. Curve 1 (Cyan Wave)
    if "ReplyHours" in df:
        y_rep = df["ReplyHours"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_rep,
            name=name_1,
            mode="lines",
            line=dict(color="#00F0FF", width=3, shape="spline", smoothing=1.3),
            fill="tozeroy",
            fillcolor="rgba(0, 240, 255, 0.22)",
            hoverinfo="x+y"
        ))
    
    # 2. Curve 2 (Purple / Pink Wave)
    if "ResolveHours" in df:
        y_res = df["ResolveHours"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_res,
            name=name_2,
            mode="lines",
            line=dict(color="#B347EB", width=3, shape="spline", smoothing=1.3),
            fill="tonexty",
            fillcolor="rgba(179, 71, 235, 0.25)",
            hoverinfo="x+y"
        ))

    # Highlight Marker Peak
    if len(x_vals) >= 1:
        idx = len(x_vals) - 1 if len(x_vals) <= 4 else min(3, len(x_vals) - 1)
        if "ReplyHours" in df and len(df["ReplyHours"]) > 0:
            idx = int(df["ReplyHours"].tolist().index(max(df["ReplyHours"])))
        pk_x = x_vals[idx]
        pk_y = df["ReplyHours"].iloc[idx] if "ReplyHours" in df else 2.5
        fig.add_trace(go.Scatter(
            x=[pk_x],
            y=[pk_y],
            mode="markers+text",
            marker=dict(size=12, color="#00F0FF", line=dict(color="#FFFFFF", width=2)),
            showlegend=False,
            hoverinfo="skip"
        ))
        
        peak_prefix = "Peak: " if is_en else "Đỉnh: "
        display_peak = peak_text if ("<br>" in peak_text or "<b>" in peak_text) else f"{peak_prefix}<b>{peak_text}</b>"
        fig.add_annotation(
            x=pk_x,
            y=pk_y * 1.05 if pk_y > 10 else pk_y + 0.6,
            text=display_peak,
            showarrow=True,
            arrowhead=2,
            arrowcolor="#00F0FF",
            arrowsize=0.8,
            ax=0,
            ay=-36,
            bgcolor="rgba(0, 240, 255, 0.85)",
            font=dict(color="#0A0E23", size=10, family="Inter", weight=700),
            borderpad=4,
            bordercolor="#00F0FF"
        )

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=10, r=10, t=25, b=25),
        height=180,
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter", weight=600)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            showticklabels=False
        )
    )
    return fig


def build_created_vs_solved_chart(
    df: pd.DataFrame,
    max_point: dict = None,
    name_solved: str = "Tickets Solved",
    name_created: str = "Tickets Created"
) -> go.Figure:
    """Biểu đồ chính Wave Line & Area với Peak Max annotation."""
    is_en = (get_current_language() == "en")
    fig = go.Figure()
    x_vals = df["MonthName"].tolist() if "MonthName" in df else df.iloc[:, 0].tolist()
    
    # 1. Primary Solid Cyan Line
    if "Tickets_Solved" in df:
        y_solved = df["Tickets_Solved"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_solved,
            name=name_solved,
            mode="lines+markers",
            line=dict(color="#00F0FF", width=3.5, shape="spline", smoothing=1.2),
            marker=dict(size=7, color="#00F0FF"),
            fill="tozeroy",
            fillcolor="rgba(0, 240, 255, 0.12)",
            hovertemplate=f"<b>%{{x}}</b><br>{name_solved}: <b>%{{y:,.0f}}</b><extra></extra>"
        ))

    # 2. Secondary Dashed Magenta Line
    if "Tickets_Created" in df:
        y_created = df["Tickets_Created"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_created,
            name=name_created,
            mode="lines+markers",
            line=dict(color="#E879F9", width=2.5, dash="dot", shape="spline", smoothing=1.2),
            marker=dict(size=6, color="#E879F9"),
            hovertemplate=f"<b>%{{x}}</b><br>{name_created}: <b>%{{y:,.0f}}</b><extra></extra>"
        ))

    # Peak Max Annotation
    if max_point and "month" in max_point and "val" in max_point:
        m_x = max_point["month"]
        m_y = max_point["val"]
        fig.add_trace(go.Scatter(
            x=[m_x],
            y=[m_y],
            mode="markers",
            marker=dict(size=14, color="#00F0FF", line=dict(color="#FFFFFF", width=2.5)),
            showlegend=False,
            hoverinfo="skip"
        ))
        fig.add_annotation(
            x=m_x,
            y=m_y,
            text=f"<b>Max = {m_y:,}</b>",
            showarrow=True,
            arrowhead=2,
            arrowcolor="#E879F9",
            arrowsize=0.8,
            ax=-25,
            ay=-30,
            bgcolor="#E879F9",
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=800),
            borderpad=5,
            bordercolor="#E879F9"
        )

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=35, r=20, t=30, b=30),
        height=240,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=700)
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=11, family="Inter", weight=600)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter")
        ),
        hoverlabel=dict(
            bgcolor="#0F1424",
            font_size=12,
            font_family="Inter",
            bordercolor="#00F0FF"
        )
    )
    return fig


def build_hr_trend_chart(
    df: pd.DataFrame,
    x_col: str = "TimePeriod",
    y1_col: str = "Metric1",
    y2_col: str = "Metric2",
    name_1: str = "Tuyển dụng mới",
    name_2: str = "Nhân sự Nam",
    unit: str = "người",
    max_point: dict = None,
    height: int = 280
) -> go.Figure:
    """Biểu đồ Trend đa đường Neon Spline/Wave đồng bộ trực tiếp với Time Filter."""
    is_en = (get_current_language() == "en")
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    xc = x_col if x_col in df.columns else df.columns[0]
    x_vals = [str(x) for x in df[xc].tolist()]
    peak_label = "Peak" if is_en else "Đỉnh"

    # 1. Primary Solid Cyan Line with Area Gradient Fill
    if y1_col in df.columns:
        y1_vals = df[y1_col].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y1_vals,
            name=name_1,
            mode="lines+markers",
            line=dict(color="#00F0FF", width=3.5, shape="spline", smoothing=1.3),
            marker=dict(size=7, color="#00F0FF", line=dict(color="#FFFFFF", width=1.5)),
            fill="tozeroy",
            fillcolor="rgba(0, 240, 255, 0.16)",
            hovertemplate=f"<b>%{{x}}</b><br>{name_1}: <b>%{{y:,.0f}} {unit}</b><extra></extra>"
        ))

    # 2. Secondary Glowing Magenta/Purple Line
    if y2_col in df.columns:
        y2_vals = df[y2_col].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y2_vals,
            name=name_2,
            mode="lines+markers",
            line=dict(color="#E879F9", width=2.8, dash="dot", shape="spline", smoothing=1.3),
            marker=dict(size=6, color="#E879F9"),
            fill="tonexty" if y1_col in df.columns else "tozeroy",
            fillcolor="rgba(232, 121, 249, 0.12)",
            hovertemplate=f"<b>%{{x}}</b><br>{name_2}: <b>%{{y:,.0f}} {unit}</b><extra></extra>"
        ))

    # Highlight Peak Max Callout Badge
    if max_point and "x" in max_point and "y" in max_point:
        m_x = str(max_point["x"])
        m_y = max_point["y"]
        fig.add_trace(go.Scatter(
            x=[m_x],
            y=[m_y],
            mode="markers",
            marker=dict(size=14, color="#00F0FF", line=dict(color="#FFFFFF", width=2.5)),
            showlegend=False,
            hoverinfo="skip"
        ))
        fig.add_annotation(
            x=m_x,
            y=m_y,
            text=f"<b>{peak_label}: {m_y:,.0f} {unit}</b>",
            showarrow=True,
            arrowhead=2,
            arrowcolor="#00F0FF",
            arrowsize=0.8,
            ax=-25,
            ay=-32,
            bgcolor="#00F0FF",
            font=dict(color="#0A0E23", size=11, family="Inter", weight=900),
            borderpad=5,
            bordercolor="#00F0FF"
        )
    elif y1_col in df.columns and len(df[y1_col]) > 0:
        max_idx = int(df[y1_col].tolist().index(max(df[y1_col])))
        m_x = x_vals[max_idx]
        m_y = df[y1_col].iloc[max_idx]
        fig.add_trace(go.Scatter(
            x=[m_x],
            y=[m_y],
            mode="markers",
            marker=dict(size=14, color="#00F0FF", line=dict(color="#FFFFFF", width=2.5)),
            showlegend=False,
            hoverinfo="skip"
        ))
        fig.add_annotation(
            x=m_x,
            y=m_y,
            text=f"<b>{peak_label}: {m_y:,.0f} {unit}</b>",
            showarrow=True,
            arrowhead=2,
            arrowcolor="#00F0FF",
            arrowsize=0.8,
            ax=-25,
            ay=-32,
            bgcolor="#00F0FF",
            font=dict(color="#0A0E23", size=11, family="Inter", weight=900),
            borderpad=5,
            bordercolor="#00F0FF"
        )

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=35, r=20, t=30, b=30),
        height=height,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=700)
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=11, family="Inter", weight=600)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter")
        ),
        hoverlabel=dict(
            bgcolor="#0F1424",
            font_size=12,
            font_family="Inter",
            bordercolor="#00F0FF"
        )
    )
    return fig


def build_tickets_by_type_donut(df: pd.DataFrame, label_col: str = "Department", val_col: str = "Headcount", height: int = 250, **kwargs) -> go.Figure:
    """Biểu đồ Donut phân loại theo danh mục phòng ban hoặc type với bảng màu Neon siêu nét."""
    is_en = (get_current_language() == "en")
    if df is None or df.empty:
        return go.Figure()

    lbl_c = label_col if label_col in df.columns else ("Type" if "Type" in df.columns else df.columns[0])
    val_c = val_col if val_col in df.columns else ("Headcount" if "Headcount" in df.columns else ("Total" if "Total" in df.columns else df.columns[1]))
    
    labels = df[lbl_c].tolist()
    values = df[val_c].tolist()
    
    colors_map = {
        "Development": "#00F0FF",
        "Production": "#7928CA",
        "Sales": "#FF0080",
        "Customer Service": "#00DF8F",
        "Research": "#FFBE0B",
        "Marketing": "#3A86FF",
        "Quality Management": "#FB5607",
        "Human Resources": "#F72585",
        "Finance": "#4CC9F0",
        "Senior Engineer": "#00F0FF",
        "Staff": "#7928CA",
        "Engineer": "#FF0080",
        "Senior Staff": "#00DF8F",
        "Technique Leader": "#FFBE0B",
        "Assistant Engineer": "#3A86FF",
        "Manager": "#FB5607"
    }
    palette = ["#00F0FF", "#7928CA", "#FF0080", "#00DF8F", "#FFBE0B", "#3A86FF", "#FB5607", "#F72585", "#4CC9F0"]
    custom_colors = [colors_map.get(lbl, palette[i % len(palette)]) for i, lbl in enumerate(labels)]

    qty_label = "Quantity: " if is_en else "Số lượng: "
    ratio_label = "Ratio: " if is_en else "Tỷ lệ: "

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.66,
        sort=False,
        marker=dict(colors=custom_colors, line=dict(color="#13172B", width=2.5)),
        textinfo="percent",
        textposition="inside",
        textfont=dict(size=12, color="#FFFFFF", family="Inter", weight=900),
        hovertemplate=f"<b>%{{label}}</b><br>{qty_label}<b>%{{value:,}}</b><br>{ratio_label}<b>%{{percent}}</b><extra></extra>"
    )])

    tot_val = sum(values) if values else 0
    center_text = "TOTAL" if is_en else "TỔNG SỐ"
    fig.add_annotation(
        text=center_text,
        x=0.5, y=0.58,
        showarrow=False,
        font=dict(size=11, color="#94A3B8", family="Inter", weight=800),
        align="center"
    )
    fig.add_annotation(
        text=f"<b>{tot_val:,}</b>",
        x=0.5, y=0.43,
        showarrow=False,
        font=dict(size=20, color="#FFFFFF", family="Inter", weight=900),
        align="center"
    )

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=15, r=15, t=15, b=15),
        height=height,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=700)
        )
    )
    return fig


def build_new_vs_returned_donut(
    df: pd.DataFrame,
    total_all: int = 1200,
    returned_count: int = 742,
    center_label: str = "Returned Tickets",
    center_val_override: int = None,
    height: int = 250,
    **kwargs
) -> go.Figure:
    """Biểu đồ Concentric Donut: Cơ cấu Giới tính hoặc Khách hàng Mới/Quay lại."""
    is_en = (get_current_language() == "en")
    if df is None or df.empty:
        return go.Figure()

    lbl_col = "CustomerType" if "CustomerType" in df.columns else df.columns[0]
    val_col = "Total" if "Total" in df.columns else df.columns[1]

    labels = df[lbl_col].tolist()
    values = df[val_col].tolist()

    colors_map = {
        "Nam (Male)": "#00F0FF",
        "Nữ (Female)": "#FF007A",
        "Returned": "#FF007A",
        "New": "#7C3AED"
    }
    custom_colors = [colors_map.get(lbl, "#EC4899") for lbl in labels]

    qty_label = "Quantity: " if is_en else "Số lượng: "
    ratio_label = "Ratio: " if is_en else "Tỷ lệ: "

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.72,
        sort=False,
        marker=dict(colors=custom_colors, line=dict(color="#13172B", width=3)),
        textinfo="percent",
        textposition="inside",
        textfont=dict(size=12, color="#FFFFFF", family="Inter", weight=900),
        hovertemplate=f"<b>%{{label}}</b><br>{qty_label}<b>%{{value:,}}</b><br>{ratio_label}<b>%{{percent}}</b><extra></extra>"
    )])

    disp_val = center_val_override if center_val_override is not None else returned_count
    fig.add_annotation(
        text=str(center_label).upper(),
        x=0.5, y=0.58,
        showarrow=False,
        font=dict(size=11, color="#94A3B8", family="Inter", weight=800),
        align="center"
    )
    fig.add_annotation(
        text=f"<b>{disp_val:,}</b>",
        x=0.5, y=0.43,
        showarrow=False,
        font=dict(size=20, color="#FFFFFF", family="Inter", weight=900),
        align="center"
    )

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=15, r=15, t=15, b=15),
        height=height,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=700)
        )
    )
    return fig


def build_weekday_bar_chart(df: pd.DataFrame, height: int = 240, **kwargs) -> go.Figure:
    """Biểu đồ Cột Gradient: Phân bổ số lượng theo danh mục với độ tương phản cao."""
    is_en = (get_current_language() == "en")
    if df is None or df.empty:
        return go.Figure()

    days = df["WeekDay"].tolist() if "WeekDay" in df.columns else df.iloc[:, 0].tolist()
    totals = df["Total"].tolist() if "Total" in df.columns else df.iloc[:, 1].tolist()

    bar_colors = [
        "#00F0FF",
        "#38BDF8",
        "#818CF8",
        "#A855F7",
        "#EC4899",
        "#F43F5E",
        "#FB923C",
        "#FBBF24",
        "#34D399"
    ]

    val_label = "Value: " if is_en else "Giá trị: "

    fig = go.Figure(data=[go.Bar(
        x=days,
        y=totals,
        marker=dict(
            color=bar_colors[:len(days)] if len(days) <= len(bar_colors) else [bar_colors[i % len(bar_colors)] for i in range(len(days))],
            line=dict(color="#FFFFFF", width=1.2)
        ),
        text=[f"{v:,.0f}" if isinstance(v, (int, float)) and v >= 100 else (f"{v:,.1f}" if isinstance(v, (int, float)) else f"{v}") for v in totals],
        textposition="outside",
        textfont=dict(color="#FFFFFF", size=11, family="Inter", weight=800),
        hovertemplate=f"<b>%{{x}}</b><br>{val_label}<b>%{{y:,.0f}}</b><extra></extra>"
    )])

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=25, r=15, t=25, b=30),
        height=height,
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#FFFFFF", size=11, family="Inter", weight=700)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter")
        ),
        hoverlabel=dict(
            bgcolor="#0E1326",
            font_size=12,
            font_family="Inter",
            bordercolor="#00F0FF"
        )
    )
    return fig


def build_horizontal_bar_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    name: str = "",
    color_hex: str = "rgba(0, 240, 255, 0.9)",
    height: int = 240,
    **kwargs
) -> go.Figure:
    """Biểu đồ Thanh Ngang (Horizontal Bar Chart) tối ưu cho Top phòng ban/sản phẩm/địa lý với độ sắc nét tuyệt đối."""
    if df is None or df.empty:
        return go.Figure()

    df_sorted = df.sort_values(x_col, ascending=True) if x_col in df.columns else df
    y_vals = df_sorted[y_col].tolist() if y_col in df_sorted.columns else df_sorted.iloc[:, 0].tolist()
    x_vals = df_sorted[x_col].tolist() if x_col in df_sorted.columns else df_sorted.iloc[:, 1].tolist()

    colors = [
        "rgba(56, 189, 248, 0.85)",
        "rgba(14, 165, 233, 0.9)",
        "rgba(6, 182, 212, 0.95)",
        "rgba(0, 240, 255, 0.98)",
        "#00F0FF"
    ]

    metric_name = name or x_col

    fig = go.Figure(data=[go.Bar(
        x=x_vals,
        y=y_vals,
        name=metric_name,
        orientation="h",
        marker=dict(
            color=colors[-len(x_vals):] if len(x_vals) <= len(colors) else color_hex,
            line=dict(color="#FFFFFF", width=1.2)
        ),
        text=[f"<b>{v:,.0f}</b>" if isinstance(v, (int, float)) else f"<b>{v}</b>" for v in x_vals],
        textposition="inside",
        textfont=dict(color="#090D1A", size=12, family="Inter", weight=900),
        insidetextanchor="middle",
        hovertemplate=f"<b>%{{y}}</b><br>{metric_name}: <b>%{{x:,.0f}}</b><extra></extra>"
    )])

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=20, r=20, t=15, b=15),
        height=height,
        showlegend=False,
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter")
        ),
        yaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#FFFFFF", size=11, family="Inter", weight=800)
        )
    )
    return fig


def build_multi_bar_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list,
    names: list,
    colors: list = None,
    height: int = 260
) -> go.Figure:
    """Biểu đồ Cột Nhóm Đa Chỉ Số (Grouped Bar Chart) so sánh Min/Avg/Max hoặc nhiều chỉ tiêu."""
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    default_colors = ["#38BDF8", "#00F0FF", "#E879F9", "#F59E0B"]
    bar_colors = colors or default_colors

    x_vals = df[x_col].tolist()
    for i, col in enumerate(y_cols):
        if col in df.columns:
            fig.add_trace(go.Bar(
                name=names[i] if i < len(names) else col,
                x=x_vals,
                y=df[col].tolist(),
                marker=dict(
                    color=bar_colors[i % len(bar_colors)],
                    line=dict(color="#FFFFFF", width=1)
                ),
                hovertemplate=f"<b>%{{x}}</b><br>{names[i] if i < len(names) else col}: <b>%{{y:,.0f}}</b><extra></extra>"
            ))

    fig.update_layout(
        barmode="group",
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=25, r=15, t=30, b=30),
        height=height,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=700)
        ),
        xaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#FFFFFF", size=10, family="Inter", weight=700)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter")
        )
    )
    return fig


def build_multi_line_chart(
    df: pd.DataFrame,
    x_col: str,
    series_dict: dict,
    height: int = 260
) -> go.Figure:
    """Biểu đồ đa đường Neon Spline hiển thị nhiều chuỗi dữ liệu (ví dụ: tăng trưởng theo phòng ban)."""
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    palette = ["#00F0FF", "#E879F9", "#38BDF8", "#F59E0B", "#10B981", "#A855F7", "#EC4899", "#3B82F6", "#F97316"]
    x_vals = [str(x) for x in df[x_col].tolist()]

    for i, (col_name, label) in enumerate(series_dict.items()):
        if col_name in df.columns:
            fig.add_trace(go.Scatter(
                x=x_vals,
                y=df[col_name].tolist(),
                name=label,
                mode="lines+markers",
                line=dict(color=palette[i % len(palette)], width=2.5, shape="spline", smoothing=1.2),
                marker=dict(size=5, color=palette[i % len(palette)]),
                hovertemplate=f"<b>%{{x}}</b><br>{label}: <b>%{{y:,.0f}}</b><extra></extra>"
            ))

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=30, r=15, t=30, b=30),
        height=height,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#FFFFFF", size=10, family="Inter", weight=600)
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter", weight=600)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10, family="Inter")
        )
    )
    return fig


def build_donut_chart(
    df: pd.DataFrame,
    label_col: str,
    val_col: str,
    colors: list = None,
    height: int = 250
) -> go.Figure:
    """Biểu đồ Donut phát sáng phân tích tỷ trọng theo danh mục/thị phần."""
    is_en = (get_current_language() == "en")
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    default_colors = ["#00F0FF", "#38BDF8", "#E879F9", "#F59E0B", "#10B981", "#A855F7", "#EC4899", "#F97316"]
    slice_colors = colors or default_colors
    val_label = "Value: " if is_en else "Giá trị: "

    fig.add_trace(go.Pie(
        labels=df[label_col].tolist(),
        values=df[val_col].tolist(),
        hole=0.55,
        marker=dict(colors=slice_colors, line=dict(color="#13172B", width=2)),
        textinfo="percent+label",
        textfont=dict(color="#FFFFFF", size=11, family="Inter", weight=700),
        hovertemplate=f"<b>%{{label}}</b><br>{val_label}<b>%{{value:,.0f}}</b> (%{{percent}})<extra></extra>"
    ))

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=15, r=15, t=20, b=20),
        height=height,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.15,
            xanchor="center",
            x=0.5,
            font=dict(color="#CBD5E1", size=10, family="Inter", weight=600)
        )
    )
    return fig


def build_sales_dual_axis_chart(
    df: pd.DataFrame,
    x_col: str = "Month",
    rev_col: str = "Revenue",
    box_col: str = "Boxes",
    height: int = 280
) -> go.Figure:
    """Biểu đồ sóng kép phối hợp Cột (Doanh số $) và Đường Spline (Số lượng hộp)."""
    is_en = (get_current_language() == "en")
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    x_vals = df[x_col].tolist()
    rev_name = "Revenue ($)" if is_en else "Doanh Số ($)"
    box_name = "Boxes Sold" if is_en else "Số Lượng Hộp"
    box_unit = "boxes" if is_en else "hộp"

    # 1. Bar Trace: Revenue ($)
    if rev_col in df.columns:
        fig.add_trace(go.Bar(
            x=x_vals,
            y=df[rev_col].tolist(),
            name=rev_name,
            marker=dict(
                color="#00F0FF",
                opacity=0.85,
                line=dict(color="#FFFFFF", width=1)
            ),
            yaxis="y",
            hovertemplate=f"<b>%{{x}}</b><br>{rev_name}: <b>$%{{y:,.0f}}</b><extra></extra>"
        ))

    # 2. Line Trace: Boxes Sold
    if box_col in df.columns:
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=df[box_col].tolist(),
            name=box_name,
            mode="lines+markers",
            line=dict(color="#E879F9", width=3, shape="spline", smoothing=1.3),
            marker=dict(size=7, color="#E879F9", line=dict(color="#FFFFFF", width=1.5)),
            yaxis="y2",
            hovertemplate=f"<b>%{{x}}</b><br>{box_name}: <b>%{{y:,.0f}} {box_unit}</b><extra></extra>"
        ))

    fig.update_layout(
        paper_bgcolor="#13172B",
        plot_bgcolor="#13172B",
        margin=dict(l=25, r=25, t=30, b=30),
        height=height,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=700)
        ),
        xaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#FFFFFF", size=10, family="Inter", weight=700)
        ),
        yaxis=dict(
            title=dict(text=rev_name, font=dict(color="#00F0FF", size=11, family="Inter", weight=700)),
            showgrid=True,
            gridcolor="rgba(255,255,255,0.08)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#00F0FF", size=10, family="Inter")
        ),
        yaxis2=dict(
            title=dict(text=box_name, font=dict(color="#E879F9", size=11, family="Inter", weight=700)),
            overlaying="y",
            side="right",
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#E879F9", size=10, family="Inter")
        )
    )
    return fig
