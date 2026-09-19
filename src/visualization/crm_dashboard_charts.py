"""
High-End Cyber/Neon Multi-Layer Dashboard Plotly Chart Builders.
Styled with glassmorphism aesthetics and glowing gradients.
"""

import plotly.graph_objects as go
import pandas as pd


def build_latency_wave_chart(
    df: pd.DataFrame,
    name_1: str = "First Reply (h)",
    name_2: str = "Full Resolve (h)",
    peak_text: str = "04 October<br><b>2.5 hours</b>"
) -> go.Figure:
    """Biểu đồ sóng kép (Top Right Wave Chart) hỗ trợ đa lĩnh vực."""
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
        
        display_peak = peak_text if ("<br>" in peak_text or "<b>" in peak_text) else f"Đỉnh: <b>{peak_text}</b>"
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
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=25, b=25),
        height=180,
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#64748B", size=9)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.06)",
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
            marker=dict(size=6, color="#00F0FF"),
            fill="tozeroy",
            fillcolor="rgba(0, 240, 255, 0.08)",
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
            line=dict(color="#C084FC", width=2.5, dash="dot", shape="spline", smoothing=1.2),
            marker=dict(size=5, color="#C084FC"),
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
            font=dict(color="#FFFFFF", size=11, family="Inter", weight=700),
            borderpad=5,
            bordercolor="#E879F9"
        )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=35, r=20, t=30, b=30),
        height=240,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color="#94A3B8", size=11)
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.06)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#94A3B8", size=11)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.06)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#94A3B8", size=10)
        ),
        hoverlabel=dict(
            bgcolor="#1E293B",
            font_size=12,
            font_family="Inter",
            bordercolor="#00F0FF"
        )
    )
    return fig


def build_tickets_by_type_donut(df: pd.DataFrame, label_col: str = "Department", val_col: str = "Headcount") -> go.Figure:
    """Biểu đồ Donut phân loại theo danh mục phòng ban hoặc type."""
    lbl_c = label_col if label_col in df.columns else ("Type" if "Type" in df.columns else df.columns[0])
    val_c = val_col if val_col in df.columns else ("Headcount" if "Headcount" in df.columns else ("Total" if "Total" in df.columns else df.columns[1]))
    
    labels = df[lbl_c].tolist()
    values = df[val_c].tolist()
    
    colors_map = {
        "Development": "#0068FF",
        "Production": "#00F0FF",
        "Sales": "#38BDF8",
        "Customer Service": "#818CF8",
        "Research": "#C084FC",
        "Marketing": "#F472B6",
        "Quality Management": "#34D399",
        "Human Resources": "#FBBF24",
        "Finance": "#FB7185",
        "Senior Engineer": "#0068FF",
        "Staff": "#00F0FF",
        "Engineer": "#38BDF8",
        "Senior Staff": "#818CF8",
        "Technique Leader": "#C084FC",
        "Assistant Engineer": "#F472B6",
        "Manager": "#34D399"
    }
    custom_colors = [colors_map.get(lbl, "#00A3FF") for lbl in labels]

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.68,
        sort=False,
        marker=dict(colors=custom_colors, line=dict(color="#161B33", width=3)),
        textinfo="percent",
        textposition="inside",
        textfont=dict(size=11, color="#FFFFFF", family="Inter", weight=700),
        hovertemplate="<b>%{label}</b><br>Số lượng: %{value:,}<br>Tỷ lệ: %{percent}<extra></extra>"
    )])

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        height=220,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            font=dict(color="#CBD5E1", size=10)
        )
    )
    return fig


def build_new_vs_returned_donut(
    df: pd.DataFrame,
    total_all: int = 1200,
    returned_count: int = 742,
    center_label: str = "Returned Tickets",
    center_val_override: int = None
) -> go.Figure:
    """Biểu đồ Concentric Donut: Cơ cấu Giới tính hoặc Khách hàng Mới/Quay lại."""
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

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.76,
        sort=False,
        marker=dict(colors=custom_colors, line=dict(color="#161B33", width=4)),
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>Số lượng: %{value:,}<br>Tỷ lệ: %{percent}<extra></extra>"
    )])

    disp_val = center_val_override if center_val_override is not None else returned_count
    fig.add_annotation(
        text=f"<span style='font-size:10px; color:#94A3B8; text-transform:uppercase;'>{center_label}</span><br><b style='font-size:18px; color:#FFFFFF;'>{disp_val:,}</b>",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(family="Inter"),
        align="center"
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        height=210,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            font=dict(color="#CBD5E1", size=11)
        )
    )
    return fig


def build_weekday_bar_chart(df: pd.DataFrame) -> go.Figure:
    """Biểu đồ Cột Gradient: Phân bổ số lượng theo danh mục/thứ."""
    days = df["WeekDay"].tolist() if "WeekDay" in df.columns else df.iloc[:, 0].tolist()
    totals = df["Total"].tolist() if "Total" in df.columns else df.iloc[:, 1].tolist()

    bar_colors = [
        "rgba(0, 240, 255, 0.95)",
        "rgba(0, 240, 255, 0.85)",
        "rgba(0, 240, 255, 0.75)",
        "rgba(0, 240, 255, 0.65)",
        "rgba(0, 240, 255, 0.55)",
        "rgba(0, 240, 255, 0.45)",
    ]

    fig = go.Figure(data=[go.Bar(
        x=days,
        y=totals,
        marker=dict(
            color=bar_colors[:len(days)],
            line=dict(color="#00F0FF", width=1)
        ),
        hovertemplate="<b>%{x}</b><br>Giá trị: <b>%{y:,.0f}</b><extra></extra>"
    )])

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=25, r=10, t=20, b=25),
        height=210,
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=11)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.06)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#94A3B8", size=9)
        ),
        hoverlabel=dict(
            bgcolor="#1E293B",
            font_size=11,
            font_family="Inter",
            bordercolor="#00F0FF"
        )
    )
    return fig


def build_horizontal_bar_chart(df: pd.DataFrame, x_col: str, y_col: str, color_hex: str = "#00F0FF") -> go.Figure:
    """Biểu đồ Thanh Ngang (Horizontal Bar Chart) tối ưu cho Top 5 phòng ban hoặc xếp hạng chức danh."""
    # Sắp xếp để thanh lớn nhất nằm trên cùng
    df_sorted = df.sort_values(x_col, ascending=True)
    y_vals = df_sorted[y_col].tolist()
    x_vals = df_sorted[x_col].tolist()

    fig = go.Figure(data=[go.Bar(
        x=x_vals,
        y=y_vals,
        orientation="h",
        marker=dict(
            color=color_hex,
            line=dict(color="#FFFFFF", width=1)
        ),
        text=[f"{v:,}" for v in x_vals],
        textposition="auto",
        textfont=dict(color="#FFFFFF", size=10, family="Inter"),
        hovertemplate=f"<b>%{{y}}</b><br>{x_col}: <b>%{{x:,.0f}}</b><extra></extra>"
    )])

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20),
        height=220,
        showlegend=False,
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.06)",
            showline=False,
            zeroline=False,
            tickfont=dict(color="#94A3B8", size=9)
        ),
        yaxis=dict(
            showgrid=False,
            showline=False,
            zeroline=False,
            tickfont=dict(color="#CBD5E1", size=10)
        )
    )
    return fig
