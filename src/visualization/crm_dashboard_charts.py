"""
High-End Cyber/Neon CRM Dashboard Plotly Chart Builders.
Styled to match the dark neon executive dashboard aesthetic with glowing gradients.
"""

import plotly.graph_objects as go
import pandas as pd


def build_latency_wave_chart(df: pd.DataFrame) -> go.Figure:
    """Biểu đồ sóng kép First Reply & Full Resolve Time (Top Right Wave Chart)."""
    fig = go.Figure()
    x_vals = df["DayLabel"].tolist() if "DayLabel" in df else [f"D{i+1}" for i in range(len(df))]
    
    # 1. First Reply Hours (Cyan Wave)
    if "ReplyHours" in df:
        y_rep = df["ReplyHours"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_rep,
            name="First Reply (h)",
            mode="lines",
            line=dict(color="#00F0FF", width=3, shape="spline", smoothing=1.3),
            fill="tozeroy",
            fillcolor="rgba(0, 240, 255, 0.22)",
            hoverinfo="x+y"
        ))
    
    # 2. Full Resolve Hours (Purple / Pink Wave)
    if "ResolveHours" in df:
        y_res = df["ResolveHours"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_res,
            name="Full Resolve (h)",
            mode="lines",
            line=dict(color="#B347EB", width=3, shape="spline", smoothing=1.3),
            fill="tonexty",
            fillcolor="rgba(179, 71, 235, 0.25)",
            hoverinfo="x+y"
        ))

    # Highlight Marker Peak (e.g. 04 Oct • 2.5 hours)
    if len(x_vals) >= 4:
        idx = min(3, len(x_vals) - 1)
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
        fig.add_annotation(
            x=pk_x,
            y=pk_y + 0.6,
            text="04 October<br><b>2.5 hours</b>",
            showarrow=True,
            arrowhead=2,
            arrowcolor="#00F0FF",
            arrowsize=0.8,
            ax=0,
            ay=-36,
            bgcolor="rgba(0, 240, 255, 0.85)",
            font=dict(color="#0A0E23", size=10, family="Inter"),
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


def build_created_vs_solved_chart(df: pd.DataFrame, max_point: dict = None) -> go.Figure:
    """Biểu đồ chính Tickets Created vs Tickets Solved (Wave Line & Area với Peak Max annotation)."""
    fig = go.Figure()
    x_vals = df["MonthName"].tolist() if "MonthName" in df else df.iloc[:, 0].tolist()
    
    # 1. Tickets Solved (Solid Cyan Glow)
    if "Tickets_Solved" in df:
        y_solved = df["Tickets_Solved"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_solved,
            name="Tickets Solved",
            mode="lines+markers",
            line=dict(color="#00F0FF", width=3.5, shape="spline", smoothing=1.2),
            marker=dict(size=6, color="#00F0FF"),
            fill="tozeroy",
            fillcolor="rgba(0, 240, 255, 0.08)",
            hovertemplate="<b>%{x}</b><br>Tickets Solved: <b>%{y}</b><extra></extra>"
        ))

    # 2. Tickets Created (Dotted / Dashed Magenta/Purple Line)
    if "Tickets_Created" in df:
        y_created = df["Tickets_Created"].tolist()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_created,
            name="Tickets Created",
            mode="lines+markers",
            line=dict(color="#C084FC", width=2.5, dash="dot", shape="spline", smoothing=1.2),
            marker=dict(size=5, color="#C084FC"),
            hovertemplate="<b>%{x}</b><br>Tickets Created: <b>%{y}</b><extra></extra>"
        ))

    # Peak Max Annotation
    if max_point and "month" in max_point and "val" in max_point:
        m_x = max_point["month"]
        m_y = max_point["val"]
        # Peak glowing dot
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
            text=f"<b>Max = {m_y}</b>",
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
            tickfont=dict(color="#94A3B8", size=10),
            dtick=10
        ),
        hoverlabel=dict(
            bgcolor="#1E293B",
            font_size=12,
            font_family="Inter",
            bordercolor="#00F0FF"
        )
    )
    return fig


def build_tickets_by_type_donut(df: pd.DataFrame) -> go.Figure:
    """Biểu đồ Donut phân loại Tickets theo Type (Sales, Setup, Bug, Features)."""
    labels = df["Type"].tolist()
    values = df["Total"].tolist()
    
    # Futuristic Neon Palette matching mockup
    colors_map = {
        "Sales": "#0068FF",     # Neon Blue
        "Features": "#00F0FF",  # Cyan
        "Setup": "#38BDF8",     # Sky Blue
        "Bug": "#818CF8"        # Indigo
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
        textfont=dict(size=12, color="#FFFFFF", family="Inter", weight=700),
        hovertemplate="<b>%{label}</b><br>Tickets: %{value:,}<br>Tỷ lệ: %{percent}<extra></extra>"
    )])

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


def build_new_vs_returned_donut(df: pd.DataFrame, total_all: int = 1200, returned_count: int = 742) -> go.Figure:
    """Biểu đồ Concentric Donut: Khách hàng Mới vs Khách hàng Quay lại (New vs Returned)."""
    labels = df["CustomerType"].tolist()
    values = df["Total"].tolist()

    # Magenta/Pink (#FF007A) for Returned, Dark Purple (#7C3AED) for New
    colors_map = {
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
        hovertemplate="<b>%{label} Tickets</b><br>Số lượng: %{value:,}<br>Tỷ lệ: %{percent}<extra></extra>"
    )])

    # Center Text in Donut: Returned Tickets 1,200
    fig.add_annotation(
        text=f"<span style='font-size:10px; color:#94A3B8; text-transform:uppercase;'>Returned Tickets</span><br><b style='font-size:20px; color:#FFFFFF;'>{returned_count:,}</b>",
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
    """Biểu đồ Cột Gradient: Phân bổ số lượng Ticket theo Thứ trong tuần (Mon -> Sat)."""
    days = df["WeekDay"].tolist()
    totals = df["Total"].tolist()

    # Gradient Cyan-to-Blue Bars
    bar_colors = [
        "rgba(0, 240, 255, 0.75)",
        "rgba(0, 240, 255, 0.45)",
        "rgba(0, 240, 255, 0.85)",
        "rgba(0, 240, 255, 0.60)",
        "rgba(0, 240, 255, 1.00)",  # Fri Peak
        "rgba(0, 240, 255, 0.70)",
    ]

    fig = go.Figure(data=[go.Bar(
        x=days,
        y=totals,
        marker=dict(
            color=bar_colors[:len(days)],
            line=dict(color="#00F0FF", width=1)
        ),
        hovertemplate="<b>Thứ: %{x}</b><br>Tickets: <b>%{y}</b><extra></extra>"
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
