"""
Export utilities for Multi-format Reporting:
- Styled Excel (.xlsx) with custom headers, cell borders, and currency/date formatting.
- High-Resolution PNG (.png) for charts and slides.
- Executive PDF Report (.pdf) with 100% Vietnamese Unicode font support, clean typography,
  complete emoji stripping (no white boxes), and professional business layout.
"""
from __future__ import annotations

import io
import os
import re
import datetime
import pandas as pd

# Regex bắt toàn bộ các dải ký tự biểu tượng cảm xúc (Emoji) trong Unicode
EMOJI_REGEX = re.compile(
    r"[\U00010000-\U0010ffff]|[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]|[\u200D\uFE0F]|[\uFE00-\uFE0F]",
    flags=re.UNICODE
)


def clean_text_for_pdf(text: str) -> str:
    """Loại bỏ triệt để các emoji gây lỗi ô vuông trắng và chuẩn hóa cú pháp XML an toàn cho ReportLab:
    - Loại bỏ toàn bộ emoji và ký tự glyph lạ gây ô vuông tofu.
    - Chuyển đổi Markdown (**bold**, *italic*, `code`, \$) sang thẻ XML ReportLab (<b>, <i>, ...).
    - Bảo vệ các thẻ XML hợp lệ (<b>, <i>, <u>, <font>, <br/>, &bull;) để ReportLab render định dạng thay vì in chữ thô.
    - Tự động cân bằng các thẻ đóng/mở để đảm bảo tài liệu PDF không bị lỗi XML parsing.
    """
    if not text:
        return ""

    text = str(text)

    # 1. Chuyển đổi / gỡ bỏ các biểu tượng ưu tiên, huy chương và ký tự glyph lạ
    for glyph in ["🔴", "🟡", "🟢", "🥇", "🥈", "🥉", "↳", "➔", "➜", "➡", "►", "□", "🚨", "⚠️", "✅", "❌", "📌", "🎯", "⚡", "💡", "📊", "📈", "📉"]:
        text = text.replace(glyph, "")

    # 2. Xóa toàn bộ emoji unicode gây lỗi ô vuông tofu
    text = EMOJI_REGEX.sub("", text)

    # 3. Tách từ viết hoa dính liền với từ tiếng Việt an toàn
    vn_lower = "a-zàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    vn_upper = "A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ"
    text = re.sub(rf"([{vn_upper}]{{2,}})([{vn_upper}][{vn_lower}])", r"\1 \2", text)
    text = re.sub(rf"([{vn_upper}]{{2,}})([{vn_lower}])", r"\1 \2", text)

    # 4. Thêm khoảng trắng sau dấu hai chấm nếu bị dính số hoặc chữ và sửa lỗi 2 dấu hai chấm
    text = re.sub(r"\]\s*:\s*:\s*", "]: ", text)
    text = re.sub(r"\s*:\s*:\s*", ": ", text)
    text = re.sub(rf"([{vn_upper}{vn_lower}]):(\d)", r"\1: \2", text)
    text = re.sub(rf":([{vn_upper}{vn_lower}])", r": \1", text)

    # 5. Xóa các ký tự markdown header #### dư thừa trong dòng
    text = re.sub(r"#+\s*", "", text)

    # 5.5. Tự động phục hồi hoặc làm sạch dấu ** bị mồ côi (orphaned)
    text = re.sub(r"^(•\s*|&bull;\s*|\-\s*)?(?!\*\*)([^\n\*:]+)\*\*\s*:", r"\1**\2**:", text)

    # 6. Chuyển đổi cú pháp markdown sang thẻ định dạng ReportLab
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`(.*?)`", r"<b>\1</b>", text)
    # Xóa sạch toàn bộ ký hiệu ** thừa còn sót lại để xuất PDF luôn sạch đẹp
    text = text.replace("**", "").replace("\\$", "$")

    # 7. Bảo vệ các thẻ XML hợp lệ của ReportLab (kể cả thẻ đã bị escape trước đó)
    text = re.sub(r"&lt;(\/?[biu]|font[^&]*|\/font|br\s*\/?)&gt;", r"<\1>", text, flags=re.IGNORECASE)
    text = text.replace("&amp;", "&")

    tokens = []
    def save_tag(m):
        tokens.append(m.group(0))
        return f"__RLTAG_{len(tokens)-1}__"

    tag_pattern = re.compile(r"<\/?(?:b|i|u|font(?:\s+[a-zA-Z0-9_-]+=(?:'[^']*'|\"[^\"]*\"))*|br\s*\/?)>|&bull;", re.IGNORECASE)
    text = tag_pattern.sub(save_tag, text)

    # 8. Thoát các ký tự XML thuần túy còn lại để tránh lỗi vỡ cú pháp ReportLab
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 9. Khôi phục lại các thẻ ReportLab đã được bảo vệ
    for idx, tag in enumerate(tokens):
        text = text.replace(f"__RLTAG_{idx}__", tag)

    # 10. Đảm bảo khoảng trắng hợp lý quanh thẻ in đậm nếu dính chữ/số tiếng Việt
    text = re.sub(rf"</b>([{vn_upper}{vn_lower}0-9])", r"</b> \1", text)
    text = re.sub(rf"([{vn_upper}{vn_lower}0-9])<b>", r"\1 <b>", text)

    # 11. Tự động cân bằng các thẻ đóng/mở
    open_b = len(re.findall(r"<b>", text, re.IGNORECASE))
    close_b = len(re.findall(r"<\/b>", text, re.IGNORECASE))
    if open_b > close_b:
        text += "</b>" * (open_b - close_b)

    open_i = len(re.findall(r"<i>", text, re.IGNORECASE))
    close_i = len(re.findall(r"<\/i>", text, re.IGNORECASE))
    if open_i > close_i:
        text += "</i>" * (open_i - close_i)

    open_f = len(re.findall(r"<font\b", text, re.IGNORECASE))
    close_f = len(re.findall(r"<\/font>", text, re.IGNORECASE))
    if open_f > close_f:
        text += "</font>" * (open_f - close_f)

    # 12. Dọn dẹp khoảng trắng thừa và ký tự rác đầu mục
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"^\s*[\.\-•]\s*", "", text.strip())

    return text.strip()


def setup_pdf_fonts() -> tuple[str, str]:
    """Đăng ký phông chữ Unicode tiếng Việt và thiết lập Font Family chuẩn cho ReportLab."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled_font = os.path.join(base_dir, "assets", "fonts", "CustomUnicode.ttf")
    bundled_font_bold = os.path.join(base_dir, "assets", "fonts", "CustomUnicode-Bold.ttf")

    font_name = "Helvetica"
    font_name_bold = "Helvetica-Bold"

    if os.path.exists(bundled_font):
        try:
            pdfmetrics.registerFont(TTFont("CustomUnicode", bundled_font))
            font_name = "CustomUnicode"
            font_name_bold = "CustomUnicode"
            if os.path.exists(bundled_font_bold):
                pdfmetrics.registerFont(TTFont("CustomUnicodeBold", bundled_font_bold))
                font_name_bold = "CustomUnicodeBold"

            # Đăng ký Font Family để ReportLab tự động ánh xạ thẻ <b>, <i> khi dùng font CustomUnicode
            pdfmetrics.registerFontFamily(
                "CustomUnicode",
                normal="CustomUnicode",
                bold="CustomUnicodeBold" if "CustomUnicodeBold" in pdfmetrics.getRegisteredFontNames() else "CustomUnicode",
                italic="CustomUnicode",
                boldItalic="CustomUnicodeBold" if "CustomUnicodeBold" in pdfmetrics.getRegisteredFontNames() else "CustomUnicode"
            )
        except Exception:
            pass
    else:
        possible_fonts = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        ]
        for fpath in possible_fonts:
            if os.path.exists(fpath):
                try:
                    pdfmetrics.registerFont(TTFont("CustomUnicode", fpath))
                    font_name = "CustomUnicode"
                    font_name_bold = "CustomUnicode"
                    pdfmetrics.registerFontFamily(
                        "CustomUnicode",
                        normal="CustomUnicode",
                        bold="CustomUnicode",
                        italic="CustomUnicode",
                        boldItalic="CustomUnicode"
                    )
                    break
                except Exception:
                    pass
    return font_name, font_name_bold


# ---------------------------------------------------------
# 1. Xuất Excel (.xlsx) Định Dạng Chuyên Nghiệp
# ---------------------------------------------------------
def export_to_excel(df: pd.DataFrame, sheet_name: str = "Bao_Cao") -> bytes:
    """Tạo file Excel (.xlsx) có sẵn style header màu xanh Navy, viền ô và định dạng số phân cách hàng nghìn."""
    if df is None or df.empty:
        return b""

    output = io.BytesIO()
    try:
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            clean_sheet = "".join(c for c in sheet_name if c.isalnum() or c in (" ", "_"))[:30] or "Data"
            df.to_excel(writer, index=False, sheet_name=clean_sheet)
            ws = writer.sheets[clean_sheet]

            # Style Tiêu đề Header
            header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            border_thin = Border(
                left=Side(style="thin", color="D9D9D9"),
                right=Side(style="thin", color="D9D9D9"),
                top=Side(style="thin", color="D9D9D9"),
                bottom=Side(style="thin", color="D9D9D9")
            )

            for col_idx, col in enumerate(df.columns, 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

                # Tính độ rộng cột tự động
                max_val_len = df[col].astype(str).map(len).max() if not df[col].empty else 0
                max_len = max(max_val_len, len(str(col))) + 4
                col_letter = get_column_letter(col_idx)
                ws.column_dimensions[col_letter].width = max(max_len, 14)

                # Định dạng dữ liệu các dòng
                from src.analytics.heuristics import is_id_like
                is_num = pd.api.types.is_numeric_dtype(df[col])
                c_low = str(col).lower()
                is_year_or_id = is_id_like(col) or (
                    any(k in c_low for k in ["year", "năm", "nam", "hireyear", "hire_date", "tháng", "month", "emp_no", "mã", "id", "spid", "pid", "geoid"])
                    and not any(k in c_low for k in ["salary", "lương", "cost", "revenue", "amount", "profit", "budget", "tiền"])
                )
                for row_idx in range(2, len(df) + 2):
                    c = ws.cell(row=row_idx, column=col_idx)
                    c.border = border_thin
                    if is_year_or_id:
                        c.number_format = "0"
                        c.alignment = Alignment(horizontal="center")
                    elif is_num:
                        c.number_format = "#,##0"
                        c.alignment = Alignment(horizontal="right")
                    else:
                        c.alignment = Alignment(horizontal="left")

        return output.getvalue()
    except Exception:
        output = io.BytesIO()
        df.to_excel(output, index=False)
        return output.getvalue()


def prepare_figure_for_print(fig):
    """Chuyển đổi biểu đồ Plotly sang giao diện in ấn Executive White Theme (McKinsey/BCG) với độ tương phản cực cao.
    Khắc phục triệt để lỗi chữ trắng/mờ trên nền PDF trắng, làm cho tiêu đề, nhãn số liệu, chú thích và trục tọa độ sắc nét 100%.
    """
    if fig is None:
        return None
    import copy
    print_fig = copy.deepcopy(fig)

    # 1. Cấu hình nền trắng tinh và màu chữ xanh đen điều hành (Executive Navy #0F2042)
    print_fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(
            family="'Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans', sans-serif",
            size=12,
            color="#0F2042"
        ),
        title=dict(
            font=dict(
                family="'Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans', sans-serif",
                size=14,
                color="#0F2042"
            ),
            x=0.5,
            xanchor="center"
        ),
        legend=dict(
            font=dict(
                color="#0F2042",
                size=10,
                family="'Helvetica Neue', 'Helvetica', 'Arial', sans-serif"
            ),
            title=dict(
                font=dict(
                    color="#0F2042",
                    size=10.5,
                    family="'Helvetica Neue', 'Helvetica', 'Arial', sans-serif"
                )
            ),
            bgcolor="rgba(255, 255, 255, 0.95)",
            bordercolor="#CBD5E1",
            borderwidth=1,
            orientation="h",
            yanchor="bottom",
            y=-0.25,
            xanchor="center",
            x=0.5
        )
    )

    # 2. Cập nhật từng Trace (Pie, Bar, Line, Scatter...)
    for trace in print_fig.data:
        t_type = getattr(trace, "type", "")
        if t_type == "pie":
            # Donut & Pie Chart: chữ trong lát cắt màu trắng đậm, chữ ngoài lát cắt màu xanh đen đậm #0F2042
            try:
                trace.insidetextfont = dict(color="#FFFFFF", size=11, family="'Helvetica', 'Arial', sans-serif")
            except Exception:
                pass
            try:
                trace.outsidetextfont = dict(color="#0F2042", size=11, family="'Helvetica', 'Arial', sans-serif")
            except Exception:
                pass
            try:
                trace.textfont = dict(color="#0F2042", size=11, family="'Helvetica', 'Arial', sans-serif")
            except Exception:
                pass
            try:
                trace.marker = dict(line=dict(color="#FFFFFF", width=2.5))
            except Exception:
                pass
        else:
            # Bar / Line / Scatter / Histogram...
            try:
                if hasattr(trace, "outsidetextfont"):
                    trace.outsidetextfont = dict(color="#0F2042", size=10.5, family="'Helvetica', 'Arial', sans-serif")
            except Exception:
                pass
            try:
                if hasattr(trace, "textfont"):
                    pos = getattr(trace, "textposition", "")
                    if pos == "inside":
                        trace.textfont = dict(color="#FFFFFF", size=10.5, family="'Helvetica', 'Arial', sans-serif")
                    else:
                        trace.textfont = dict(color="#0F2042", size=10.5, family="'Helvetica', 'Arial', sans-serif")
            except Exception:
                pass

    # 3. Cập nhật toàn bộ các trục X & Y
    print_fig.update_xaxes(
        tickfont=dict(color="#334155", size=10, family="'Helvetica', 'Arial', sans-serif"),
        title_font=dict(color="#0F2042", size=11.5, family="'Helvetica', 'Arial', sans-serif"),
        gridcolor="#E2E8F0",
        linecolor="#94A3B8",
        zerolinecolor="#CBD5E1",
        showgrid=True
    )
    print_fig.update_yaxes(
        tickfont=dict(color="#334155", size=10, family="'Helvetica', 'Arial', sans-serif"),
        title_font=dict(color="#0F2042", size=11.5, family="'Helvetica', 'Arial', sans-serif"),
        gridcolor="#E2E8F0",
        linecolor="#94A3B8",
        zerolinecolor="#CBD5E1",
        showgrid=True
    )

    # 4. Cập nhật các Annotations (chú thích số liệu trên biểu đồ)
    if hasattr(print_fig.layout, "annotations") and print_fig.layout.annotations:
        for ann in print_fig.layout.annotations:
            try:
                if hasattr(ann, "font") and ann.font:
                    ann.font.color = "#0F2042"
                if hasattr(ann, "bgcolor") and ann.bgcolor:
                    ann.bgcolor = "rgba(255, 255, 255, 0.9)"
                if hasattr(ann, "bordercolor") and ann.bordercolor:
                    ann.bordercolor = "#CBD5E1"
            except Exception:
                pass

    return print_fig


# ---------------------------------------------------------
# 2. Xuất Ảnh Biểu Đồ PNG Độ Nét Cao & Nhúng Báo Cáo PDF
# ---------------------------------------------------------
def export_to_png(fig=None, df: pd.DataFrame = None, user_query: str = "") -> bytes | None:
    """Xuất biểu đồ sang ảnh PNG bytes độ nét cao (Ultra-Sharp High Contrast) để nhúng vào Báo cáo PDF.
    - Ưu tiên 1: Chuyển đổi Plotly Figure sang chuẩn White Print Theme và xuất qua kaleido (`scale=2.5`).
    - Ưu tiên 2: Tự động vẽ biểu đồ chuẩn McKinsey Executive (Donut/Bar/Line) bằng Matplotlib với độ phân giải cao 200 DPI.
    """
    # 1. Thử dùng Plotly + Kaleido với Print Theme độ tương phản cao
    if fig is not None:
        try:
            print_fig = prepare_figure_for_print(fig)
            img_bytes = print_fig.to_image(format="png", width=1100, height=480, scale=2.5, engine="kaleido")
            if img_bytes and len(img_bytes) > 500:
                return img_bytes
        except Exception:
            pass

    # 2. Fallback: Tự động vẽ biểu đồ bằng Matplotlib chuẩn Executive (Hỗ trợ Donut, Bar, Line)
    if df is not None and not df.empty:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from src.analytics.heuristics import get_axis_columns, is_id_like, pick_label_column
            from src.visualization.charts import format_col_title

            measure_cols, label_cols, time_col = get_axis_columns(df)
            if not measure_cols:
                return None

            plot_df = df.copy()
            if len(plot_df) > 20:
                plot_df = plot_df.head(20)

            fig_mpl, ax = plt.subplots(figsize=(9, 4.2), dpi=200)
            fig_mpl.patch.set_facecolor("#FFFFFF")
            ax.set_facecolor("#FFFFFF")

            # Cấu hình phong cách tối giản McKinsey
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color("#CBD5E1")
            ax.spines["bottom"].set_color("#CBD5E1")
            ax.grid(axis="y", linestyle="--", alpha=0.4, color="#E2E8F0")

            q_lower = (user_query or "").lower()
            is_pie_request = any(k in q_lower for k in ["tỷ trọng", "tỉ trọng", "cơ cấu", "pie", "donut", "phần trăm", "%", "share", "proportion"])

            if is_pie_request and label_cols and len(measure_cols) >= 1:
                # Vẽ biểu đồ Donut Chart chuẩn McKinsey độ tương phản cao
                label_col = label_cols[0]
                measure_col = measure_cols[0]
                top_pie_df = plot_df.sort_values(measure_col, ascending=False).head(7)
                pie_labels = [str(v)[:20] for v in top_pie_df[label_col]]
                pie_vals = pd.to_numeric(top_pie_df[measure_col], errors="coerce").fillna(0).tolist()
                
                palette = ["#2563EB", "#059669", "#D97706", "#7C3AED", "#DC2626", "#0891B2", "#475569"]
                wedges, texts, autotexts = ax.pie(
                    pie_vals,
                    labels=pie_labels,
                    autopct="%1.1f%%",
                    pctdistance=0.75,
                    colors=palette[:len(pie_vals)],
                    startangle=140,
                    wedgeprops=dict(width=0.45, edgecolor="#FFFFFF", linewidth=2.5),
                    textprops=dict(color="#0F2042", fontsize=9, fontweight="bold")
                )
                for autotext in autotexts:
                    autotext.set_color("#FFFFFF")
                    autotext.set_fontsize(8.5)
                    autotext.set_fontweight("bold")

                ax.set_title(f"Tỷ Trọng {format_col_title(measure_col)} theo {format_col_title(label_col)}", fontsize=11.5, fontweight="bold", pad=14, color="#0F2042")
            elif time_col and time_col in plot_df.columns:
                # Line Chart xu hướng thời gian
                x_vals = [str(v) for v in plot_df[time_col]]
                colors_list = ["#0068FF", "#DC2626", "#10B981", "#D97706"]
                for idx, m in enumerate(measure_cols[:3]):
                    y_vals = pd.to_numeric(plot_df[m], errors="coerce").fillna(0)
                    ax.plot(x_vals, y_vals, marker="o", linewidth=2.5, markersize=6, label=format_col_title(m), color=colors_list[idx % len(colors_list)])
                if len(measure_cols) > 1:
                    ax.legend(frameon=False, loc="upper right")
                ax.set_title(f"Xu hướng {format_col_title(measure_cols[0])} theo {format_col_title(time_col)}", fontsize=11.5, fontweight="bold", pad=12, color="#0F2042")
                plt.xticks(rotation=35 if len(x_vals) > 6 else 0, ha="right" if len(x_vals) > 6 else "center", fontsize=8.5, color="#0F2042")
            elif label_cols:
                label_col = label_cols[0]
                x_vals = [str(v)[:18] for v in plot_df[label_col]]

                if len(measure_cols) == 1:
                    y_vals = pd.to_numeric(plot_df[measure_cols[0]], errors="coerce").fillna(0)
                    bars = ax.bar(x_vals, y_vals, color="#1E40AF", width=0.55, edgecolor="none")
                    is_curr = any(k in str(measure_cols[0]).lower() for k in ["salary", "sales", "revenue", "amount", "$", "tiền", "lương", "cost", "profit"])
                    max_y = max(y_vals) if len(y_vals) > 0 and max(y_vals) > 0 else 1.0
                    for bar in bars:
                        yval = bar.get_height()
                        txt = f"${yval:,.0f}" if is_curr else (f"{yval:,.0f}" if yval >= 10 else f"{yval:,.1f}")
                        ax.text(bar.get_x() + bar.get_width() / 2.0, yval + max_y * 0.02, txt, ha="center", va="bottom", fontsize=8, color="#0F2042", fontweight="bold")
                    ax.set_title(f"{format_col_title(measure_cols[0])} theo {format_col_title(label_col)}", fontsize=11.5, fontweight="bold", pad=12, color="#0F2042")
                else:
                    import numpy as np
                    pct_cols = [c for c in measure_cols if any(k in c.lower() for k in ["pct", "percent", "tỷ lệ", "tỉ lệ", "%"])]
                    non_pct = [c for c in measure_cols if c not in pct_cols] or measure_cols
                    use_m = non_pct[:3] if len(non_pct) >= 2 else measure_cols[:3]
                    n_m = min(len(use_m), 3)
                    width = 0.8 / n_m
                    x_indices = np.arange(len(x_vals))
                    colors_list = ["#1E40AF", "#FF7A00", "#10B981"]
                    for idx, m in enumerate(use_m):
                        y_vals = pd.to_numeric(plot_df[m], errors="coerce").fillna(0)
                        offset = (idx - (n_m - 1) / 2) * width
                        ax.bar(x_indices + offset, y_vals, width=width, label=format_col_title(m), color=colors_list[idx % len(colors_list)])
                    ax.set_xticks(x_indices)
                    ax.set_xticklabels(x_vals, color="#0F2042")
                    ax.legend(frameon=False, loc="upper right")
                    ax.set_title(f"So sánh các chỉ số theo {format_col_title(label_col)}", fontsize=11.5, fontweight="bold", pad=12, color="#0F2042")

                plt.xticks(rotation=30 if len(x_vals) > 6 else 0, ha="right" if len(x_vals) > 6 else "center", fontsize=8.5, color="#0F2042")
            else:
                return None

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="#FFFFFF")
            plt.close(fig_mpl)
            return buf.getvalue()
        except Exception:
            return None

    return None


# ---------------------------------------------------------
# 3. Xuất Báo Cáo Quản Trị Executive PDF Chuẩn McKinsey / BCG
# ---------------------------------------------------------
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, HRFlowable
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    HAS_REPORTLAB = True
except ImportError:
    canvas = None
    A4 = None
    colors = None
    getSampleStyleSheet = None
    ParagraphStyle = None
    SimpleDocTemplate = None
    Paragraph = None
    Spacer = None
    Table = None
    TableStyle = None
    PageBreak = None
    Image = None
    HRFlowable = None
    pdfmetrics = None
    TTFont = None
    HAS_REPORTLAB = False


class NumberedCanvas(canvas.Canvas if canvas else object):
    """Hai lượt vẽ (two-pass canvas) để tính tổng số trang chính xác cho Báo Cáo Điều Hành (McKinsey / BCG Style).
    Trang 1 (Trang bìa) được giữ hoàn toàn sạch sẽ, không có running header và running footer.
    Từ trang 2 trở đi, hiển thị Header thanh lịch và Footer chứa số trang động dạng 'Trang X / Y'.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        if self._pageNumber == 1:
            # Trang bìa: Không vẽ running header/footer để giữ chuẩn ấn phẩm điều hành
            return

        self.saveState()
        reg_fonts = pdfmetrics.getRegisteredFontNames()
        fn = "CustomUnicode" if "CustomUnicode" in reg_fonts else "Helvetica"
        fn_bold = "CustomUnicodeBold" if "CustomUnicodeBold" in reg_fonts else ("CustomUnicode" if "CustomUnicode" in reg_fonts else "Helvetica-Bold")

        # Running Header (Trang 2 trở đi)
        self.setFont(fn, 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(40, 808, "BÁO CÁO QUẢN TRỊ ĐIỀU HÀNH | STRATEGIC MANAGEMENT REPORT")
        self.setFillColor(colors.HexColor("#0F2042"))
        self.setFont(fn_bold, 7.5)
        self.drawRightString(555, 808, "STRICTLY CONFIDENTIAL")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        self.line(40, 801, 555, 801)

        # Running Footer
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        self.line(40, 42, 555, 42)
        self.setFont(fn, 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(40, 30, "© 2026 Awesome Chocolates Strategic Intelligence Practice")
        self.drawRightString(555, 30, f"Trang {self._pageNumber} / {page_count}")
        self.restoreState()


def export_to_pdf(result: dict, df: pd.DataFrame, chart_png_bytes: bytes = None) -> bytes:
    """Tạo tài liệu Báo cáo Điều hành PDF (Executive Report) chuẩn McKinsey / BCG:
    - Trang bìa điều hành chuyên nghiệp (Cover Page) với tiêu đề, tóm tắt điều hành và bảng phân loại bảo mật.
    - Đánh số trang động tự động (Trang X / Y) với Header & Footer tinh tế từ trang 2.
    - Bảng dữ liệu quản trị chuẩn mực: tiêu đề tiếng Việt hóa, căn chỉnh số học kế toán, không đường kẻ dọc, zebra striping và dòng tổng kết.
    - Ma trận khuyến nghị hành động chiến lược phân cấp độ ưu tiên và phụ lục truy vấn dữ liệu gốc.
    """
    if result is None:
        return b""

    buffer = io.BytesIO()
    try:
        from src.visualization.charts import format_col_title

        # 1. Đăng ký Font Unicode Tiếng Việt từ thư mục dự án
        font_name, font_name_bold = setup_pdf_fonts()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=40,
            rightMargin=40,
            topMargin=45,
            bottomMargin=48
        )

        styles = getSampleStyleSheet()

        # Bảng màu sắc chuẩn McKinsey / BCG
        MCK_NAVY = colors.HexColor("#0F2042")      # Deep McKinsey Navy
        MCK_BLUE = colors.HexColor("#1E3A8A")      # Strategic Consulting Blue
        ACCENT_GOLD = colors.HexColor("#C5A059")   # Executive Gold / Champagne
        TEXT_DARK = colors.HexColor("#1E293B")     # Slate 800
        TEXT_MUTED = colors.HexColor("#64748B")    # Slate 500
        BG_LIGHT = colors.HexColor("#F8FAFC")      # Slate 50
        BORDER_LIGHT = colors.HexColor("#E2E8F0")  # Slate 200

        # Typography Styles - Trang Bìa
        cover_eyebrow = ParagraphStyle(
            "CoverEyebrow", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=8.5, leading=11,
            textColor=TEXT_MUTED, spaceAfter=6
        )
        cover_tag = ParagraphStyle(
            "CoverTag", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=8.5, leading=12,
            textColor=ACCENT_GOLD, spaceAfter=10
        )
        cover_title = ParagraphStyle(
            "CoverTitle", parent=styles["Heading1"],
            fontName=font_name_bold, fontSize=20, leading=26,
            textColor=MCK_NAVY, spaceAfter=8
        )
        cover_subtitle = ParagraphStyle(
            "CoverSubtitle", parent=styles["Normal"],
            fontName=font_name, fontSize=9.5, leading=14.5,
            textColor=colors.HexColor("#475569"), spaceAfter=14
        )
        cover_box_title = ParagraphStyle(
            "CoverBoxTitle", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=10, leading=14,
            textColor=MCK_NAVY, spaceAfter=6
        )
        cover_box_text = ParagraphStyle(
            "CoverBoxText", parent=styles["Normal"],
            fontName=font_name, fontSize=8.5, leading=13.5,
            textColor=colors.HexColor("#334155"), spaceAfter=4
        )
        cover_meta_label = ParagraphStyle(
            "CoverMetaLabel", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=8, leading=12,
            textColor=TEXT_MUTED
        )
        cover_meta_val = ParagraphStyle(
            "CoverMetaVal", parent=styles["Normal"],
            fontName=font_name, fontSize=8, leading=12,
            textColor=TEXT_DARK
        )

        # Typography Styles - Nội Dung Chính
        section_style = ParagraphStyle(
            "SectionHead", parent=styles["Heading2"],
            fontName=font_name_bold, fontSize=11.5, leading=15,
            textColor=MCK_NAVY, spaceBefore=14, spaceAfter=7,
            keepWithNext=True
        )
        sub_section_style = ParagraphStyle(
            "SubSectionHead", parent=styles["Heading3"],
            fontName=font_name_bold, fontSize=9.5, leading=13.5,
            textColor=MCK_BLUE, spaceBefore=8, spaceAfter=4, leftIndent=2,
            keepWithNext=True
        )
        body_style = ParagraphStyle(
            "BodyText", parent=styles["Normal"],
            fontName=font_name, fontSize=8.5, leading=12.5,
            textColor=TEXT_DARK, spaceAfter=3
        )
        bullet_style = ParagraphStyle(
            "BulletText", parent=styles["Normal"],
            fontName=font_name, fontSize=8.5, leading=13,
            textColor=TEXT_DARK, leftIndent=12, spaceAfter=3
        )
        kpi_style = ParagraphStyle(
            "KPIStyle", parent=styles["Normal"],
            fontName=font_name, fontSize=8.0, leading=12.0,
            textColor=TEXT_MUTED, leftIndent=18, spaceAfter=4
        )

        table_cell = ParagraphStyle(
            "TableCell", parent=styles["Normal"],
            fontName=font_name, fontSize=7.5, leading=10.5,
            textColor=TEXT_DARK
        )
        table_cell_bold = ParagraphStyle(
            "TableCellBold", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=7.5, leading=10.5,
            textColor=MCK_NAVY
        )
        table_cell_num = ParagraphStyle(
            "TableCellNum", parent=styles["Normal"],
            fontName=font_name, fontSize=7.5, leading=10.5,
            alignment=2, textColor=TEXT_DARK
        )
        table_cell_num_bold = ParagraphStyle(
            "TableCellNumBold", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=7.5, leading=10.5,
            alignment=2, textColor=MCK_NAVY
        )
        table_header = ParagraphStyle(
            "TableHead", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=7.5, leading=10.5,
            textColor=colors.white, alignment=0
        )
        table_header_num = ParagraphStyle(
            "TableHeadNum", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=7.5, leading=10.5,
            textColor=colors.white, alignment=2
        )

        story = []

        # =========================================================
        # TRANG BÌA (EXECUTIVE COVER PAGE) - MCKINSEY / BCG STYLE
        # =========================================================
        story.append(Paragraph("STRATEGIC BUSINESS INTELLIGENCE &amp; EXECUTIVE DECISION REPORT", cover_eyebrow))
        story.append(HRFlowable(width="100%", thickness=2.5, color=MCK_NAVY, spaceBefore=2, spaceAfter=22))

        story.append(Spacer(1, 15))
        story.append(Paragraph("EXECUTIVE BRIEFING &bull; CHIẾN LƯỢC QUẢN TRỊ KINH DOANH", cover_tag))

        raw_query = result.get("query", "")
        clean_q = clean_text_for_pdf(raw_query)
        query_title = clean_q.upper() if clean_q else "BÁO CÁO PHÂN TÍCH HIỆU SUẤT DOANH NGHIỆP"
        story.append(Paragraph(f"BÁO CÁO PHÂN TÍCH:<br/>{query_title}", cover_title))

        story.append(HRFlowable(width="80", thickness=3.0, color=ACCENT_GOLD, hAlign='LEFT', spaceBefore=8, spaceAfter=14))

        story.append(Paragraph(
            "Tài liệu phân tích chiến lược chuyên sâu về cơ cấu kinh doanh, biên lợi nhuận và hiệu quả vận hành, "
            "được tổng hợp từ cơ sở dữ liệu doanh nghiệp toàn diện phục vụ công tác điều hành cấp cao.",
            cover_subtitle
        ))

        story.append(Spacer(1, 20))

        # Executive Summary Callout Box trên trang bìa
        total_rows = len(df) if df is not None else 0
        now_dt = datetime.datetime.now()
        now_str = now_dt.strftime("%d/%m/%Y")
        now_full = now_dt.strftime("%d/%m/%Y - %H:%M")

        summary_box_content = [
            [Paragraph("<b>TÓM TẮT ĐIỀU HÀNH (EXECUTIVE SUMMARY)</b>", cover_box_title)],
            [Paragraph("&bull; <b>Mục tiêu &amp; Trọng tâm:</b> Phân tích đối sánh chuyên sâu các chỉ số hiệu quả kinh doanh cốt lõi theo thời gian thực.", cover_box_text)],
            [Paragraph(f"&bull; <b>Quy mô Tập dữ liệu:</b> Tổng hợp và xử lý dữ liệu từ {total_rows:,} đối tượng vận hành trên toàn hệ thống.", cover_box_text)],
            [Paragraph("&bull; <b>Giá trị Chiến lược:</b> Cung cấp luận cứ định lượng giúp Hội đồng Quản trị &amp; Ban Điều hành tối ưu hóa nguồn lực và gia tăng biên lợi nhuận.", cover_box_text)]
        ]
        summary_box = Table(summary_box_content, colWidths=[515])
        summary_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
            ("LINELEFT", (0, 0), (0, -1), 3.5, MCK_NAVY),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
            ("PADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ]))
        story.append(summary_box)

        story.append(Spacer(1, 40))

        # Metadata Box chân trang bìa
        meta_table_data = [
            [
                Paragraph("<b>Đơn vị thực hiện:</b>", cover_meta_label),
                Paragraph("Ban Phân Tích Dữ Liệu &amp; Tư Vấn Chiến Lược", cover_meta_val),
                Paragraph("<b>Phân loại bảo mật:</b>", cover_meta_label),
                Paragraph("<font color='#DC2626'><b>STRICTLY CONFIDENTIAL</b></font>", cover_meta_val),
            ],
            [
                Paragraph("<b>Cấp tiếp nhận:</b>", cover_meta_label),
                Paragraph("Hội Đồng Quản Trị &amp; Ban Giám Đốc", cover_meta_val),
                Paragraph("<b>Mã báo cáo:</b>", cover_meta_label),
                Paragraph(f"REP-{now_dt.strftime('%Y%m%d%H%M')}", cover_meta_val),
            ],
            [
                Paragraph("<b>Ngày phát hành:</b>", cover_meta_label),
                Paragraph(now_full, cover_meta_val),
                Paragraph("<b>Phiên bản:</b>", cover_meta_label),
                Paragraph("Official Release 1.0 (McKinsey Style)", cover_meta_val),
            ],
        ]
        meta_table = Table(meta_table_data, colWidths=[100, 160, 110, 145])
        meta_table.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 1.0, colors.HexColor("#CBD5E1")),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(meta_table)

        # NGẮT TRANG BÌA SANG TRANG NỘI DUNG CHÍNH
        story.append(PageBreak())

        # =========================================================
        # TRANG NỘI DUNG (PAGE 2+) - DATA & STRATEGIC INSIGHTS
        # =========================================================

        # 1. BẢNG TỔNG HỢP DỮ LIỆU ĐIỀU HÀNH
        sec_counter = 1
        story.append(Paragraph(f"{sec_counter}. BẢNG TỔNG HỢP DỮ LIỆU ĐIỀU HÀNH (EXECUTIVE PERFORMANCE DATA)", section_style))

        if df is not None and not df.empty:
            from src.analytics.heuristics import get_axis_columns, pick_label_column, is_id_like
            measure_cols, label_cols, _ = get_axis_columns(df)
            if not measure_cols:
                measure_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not is_id_like(c)]
                label_cols = [c for c in df.columns if c not in measure_cols]

            if measure_cols and len(df) > 1:
                m_col = measure_cols[0]
                v_series = pd.to_numeric(df[m_col], errors="coerce").dropna()
                if not v_series.empty:
                    avg_val = v_series.mean()
                    max_idx = v_series.idxmax()
                    peak_val = df.loc[max_idx, m_col]

                    _, label_series, _ = pick_label_column(df, label_cols)
                    peak_label = str(label_series.loc[max_idx]) if (label_series is not None and max_idx in label_series.index) else (str(df.loc[max_idx, label_cols[0]]) if label_cols else "#1")

                    m_title = format_col_title(m_col)
                    c_low = str(m_col).lower()
                    is_pct = any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ"])
                    is_curr = any(k in c_low for k in ["salary", "lương", "cost", "revenue", "sales", "amount", "profit", "budget"]) and not is_pct
                    is_count = any(k in c_low for k in ["box", "hộp", "thùng", "headcount", "nhân sự", "nhân viên", "slngnhnvin", "count", "số lượng", "employee", "customer", "đối tượng"])

                    def _fmt_val(v):
                        if is_pct:
                            return f"{float(v):.2f}%"
                        if is_count:
                            return f"{round(float(v)):,.0f}"
                        if is_curr:
                            return f"${float(v):,.2f}" if (not float(v).is_integer() and abs(float(v)) < 1000) else f"${float(v):,.0f}"
                        return f"{float(v):,.0f}" if float(v).is_integer() else f"{float(v):,.2f}"

                    kpi_box_data = [
                        [
                            Paragraph(f"<b>QUY MÔ / TẬP MẪU</b><br/><font size=12 color='#0F2042'><b>{len(df):,} Đối Tượng</b></font>", body_style),
                            Paragraph(f"<b>BÌNH QUÂN TOP ({m_title})</b><br/><font size=12 color='#0F2042'><b>{_fmt_val(avg_val)}</b></font>", body_style),
                            Paragraph(f"<b>DẪN ĐẦU / KỶ LỤC</b><br/><font size=12 color='#004731'><b>{peak_label} ({_fmt_val(peak_val)})</b></font>", body_style),
                        ]
                    ]
                    kpi_tbl = Table(kpi_box_data, colWidths=[171, 172, 172])
                    kpi_tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
                        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
                        ("LINEABOVE", (0, 0), (-1, 0), 2.0, MCK_NAVY),
                        ("PADDING", (0, 0), (-1, -1), 8),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]))
                    story.append(kpi_tbl)
                    story.append(Spacer(1, 8))

            # Bảng Dữ Liệu Clean Style McKinsey (No vertical lines, clean typography, localized headers)
            MAX_PDF_ROWS = 100
            is_truncated = len(df) > MAX_PDF_ROWS
            preview_df = df.head(MAX_PDF_ROWS) if is_truncated else df
            n_cols = len(preview_df.columns)
            available_w = 515.0

            # Tính độ rộng cột thông minh
            col_widths = []
            for c in preview_df.columns:
                c_title = format_col_title(c)
                max_len = max(len(c_title), preview_df[c].astype(str).map(len).max() if not preview_df.empty else 0)
                col_widths.append(max(max_len, 4))
            tot_len = sum(col_widths) or 1
            min_col_w = max(35.0, min(65.0, available_w / max(1, n_cols)))
            calc_widths = [max(min_col_w, (w / tot_len) * available_w) for w in col_widths]
            factor = available_w / sum(calc_widths)
            final_widths = [w * factor for w in calc_widths]

            # Header Row
            header_row = []
            for idx, col in enumerate(preview_df.columns):
                is_num = pd.api.types.is_numeric_dtype(preview_df[col])
                col_txt = f"<b>{clean_text_for_pdf(format_col_title(col))}</b>"
                header_row.append(Paragraph(col_txt, table_header_num if is_num else table_header))

            table_rows = [header_row]

            for _, row in preview_df.iterrows():
                row_cells = []
                for col in preview_df.columns:
                    val = row[col]
                    c_low = str(col).lower()
                    if pd.api.types.is_numeric_dtype(preview_df[col]):
                        try:
                            num_v = float(val)
                            # Kiểm tra nếu cột là năm / thời gian / mã ID (không được format dấu phẩy hàng nghìn 1,985)
                            is_year_or_id = is_id_like(col) or (
                                any(k in c_low for k in ["year", "năm", "nam", "hireyear", "hire_date", "tháng", "month", "emp_no", "mã", "id", "spid", "pid", "geoid"])
                                and not any(k in c_low for k in ["salary", "lương", "cost", "revenue", "amount", "profit", "budget", "tiền"])
                            )
                            if is_year_or_id:
                                formatted = str(int(round(num_v))) if (pd.notna(val) and not pd.isna(num_v)) else str(val)
                            elif any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ"]):
                                formatted = f"{num_v:.2f}%"
                            elif any(k in c_low for k in ["salary", "lương", "cost", "revenue", "sales", "amount", "profit", "budget"]):
                                formatted = f"${num_v:,.2f}" if (not num_v.is_integer() and abs(num_v) < 1000) else f"${num_v:,.0f}"
                            elif any(k in c_low for k in ["boxes", "box", "hộp", "thùng", "count", "số lượng", "headcount", "employees", "slngnhnvin", "đối tượng"]):
                                formatted = f"{round(num_v):,.0f}"
                            elif any(k in c_low for k in ["thâm niên", "service", "tenure"]):
                                formatted = f"{num_v:.1f} năm" if not num_v.is_integer() else f"{int(num_v)} năm"
                            else:
                                formatted = f"{round(num_v):,.0f}" if num_v.is_integer() else f"{num_v:,.2f}"
                        except Exception:
                            formatted = str(val)
                        row_cells.append(Paragraph(formatted, table_cell_num))
                    else:
                        row_cells.append(Paragraph(clean_text_for_pdf(str(val)), table_cell))
                table_rows.append(row_cells)

            # Summary Row (Tổng cộng / Bình quân) nếu len(preview_df) >= 2
            if len(preview_df) >= 2:
                summary_cells = []
                for idx, col in enumerate(preview_df.columns):
                    c_low = str(col).lower()
                    if idx == 0:
                        summary_cells.append(Paragraph("<b>Tổng / Bình quân</b>", table_cell_bold))
                    elif pd.api.types.is_numeric_dtype(preview_df[col]):
                        v_col = pd.to_numeric(preview_df[col], errors="coerce").dropna()
                        if not v_col.empty:
                            is_year_col = is_id_like(col) or (
                                any(k in c_low for k in ["year", "năm", "nam", "hireyear", "hire_date", "tháng", "month", "emp_no", "mã", "id", "spid", "pid", "geoid"])
                                and not any(k in c_low for k in ["salary", "lương", "cost", "revenue", "amount", "profit", "budget", "tiền"])
                            )
                            if is_year_col:
                                summary_cells.append(Paragraph("-", table_cell_num_bold))
                            elif any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ", "avg", "per_box", "perbox", "cost"]):
                                avg_v = v_col.mean()
                                fmt_s = f"{avg_v:.2f}%" if any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ"]) else f"${avg_v:,.2f}"
                                summary_cells.append(Paragraph(f"<b>{fmt_s}</b>", table_cell_num_bold))
                            elif any(k in c_low for k in ["boxes", "box", "hộp", "thùng", "count", "số lượng", "headcount", "employees", "slngnhnvin", "đối tượng"]):
                                sum_v = v_col.sum()
                                fmt_s = f"{round(sum_v):,.0f}"
                                summary_cells.append(Paragraph(f"<b>{fmt_s}</b>", table_cell_num_bold))
                            else:
                                sum_v = v_col.sum()
                                fmt_s = f"${sum_v:,.0f}" if any(k in c_low for k in ["salary", "sales", "revenue", "amount", "budget"]) else (f"{round(sum_v):,.0f}" if sum_v.is_integer() else f"{sum_v:,.2f}")
                                summary_cells.append(Paragraph(f"<b>{fmt_s}</b>", table_cell_num_bold))
                        else:
                            summary_cells.append(Paragraph("", table_cell))
                    else:
                        summary_cells.append(Paragraph("", table_cell))
                table_rows.append(summary_cells)

            t = Table(table_rows, colWidths=final_widths, repeatRows=1)
            t_style = [
                ("BACKGROUND", (0, 0), (-1, 0), MCK_NAVY),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("LINEABOVE", (0, 0), (-1, 0), 1.5, MCK_NAVY),
                ("LINEBELOW", (0, 0), (-1, 0), 1.2, MCK_NAVY),
                ("TOPPADDING", (0, 1), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 3.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
            # Zebra striping
            for r in range(1, len(preview_df) + 1):
                bg = BG_LIGHT if r % 2 == 0 else colors.white
                t_style.append(("BACKGROUND", (0, r), (-1, r), bg))
                t_style.append(("LINEBELOW", (0, r), (-1, r), 0.4, BORDER_LIGHT))

            # Style cho summary row
            if len(preview_df) >= 2:
                sum_idx = len(table_rows) - 1
                t_style.append(("BACKGROUND", (0, sum_idx), (-1, sum_idx), colors.HexColor("#F1F5F9")))
                t_style.append(("LINEABOVE", (0, sum_idx), (-1, sum_idx), 1.0, MCK_NAVY))
                t_style.append(("LINEBELOW", (0, sum_idx), (-1, sum_idx), 1.5, MCK_NAVY))
                t_style.append(("TOPPADDING", (0, sum_idx), (-1, sum_idx), 4))
                t_style.append(("BOTTOMPADDING", (0, sum_idx), (-1, sum_idx), 4))

            t.setStyle(TableStyle(t_style))
            story.append(t)
            if is_truncated:
                story.append(Spacer(1, 4))
                story.append(Paragraph(
                    f"<font color='#64748B'><i>* Ghi chú: Bảng PDF hiển thị {MAX_PDF_ROWS} dòng đầu tiên trong tổng số {len(df):,} dòng. Vui lòng tải file Excel (.xlsx) hoặc CSV để xem toàn bộ dữ liệu.</i></font>",
                    body_style
                ))
            story.append(Spacer(1, 10))

        # 2. BIỂU ĐỒ TRỰC QUAN HÓA CHIẾN LƯỢC (nếu có ảnh chart hoặc tự động vẽ)
        if chart_png_bytes is None and df is not None and not df.empty:
            chart_png_bytes = export_to_png(None, df=df, user_query=result.get("query", ""))

        if chart_png_bytes:
            try:
                img_buffer = io.BytesIO(chart_png_bytes)
                img_obj = Image(img_buffer, width=515, height=215)
                sec_counter += 1
                story.append(Paragraph(f"{sec_counter}. BIỂU ĐỒ TRỰC QUAN HÓA CHIẾN LƯỢC (STRATEGIC VISUALIZATION)", section_style))
                story.append(img_obj)
                story.append(Spacer(1, 10))
            except Exception:
                pass

        # 3. PHÂN TÍCH INSIGHT CHIẾN LƯỢC & KẾ HOẠCH HÀNH ĐỘNG
        insights = result.get("insights") or ""
        if insights or (df is not None and not df.empty):
            sec_counter += 1
            sec_num = str(sec_counter)
            story.append(Paragraph(f"{sec_num}. PHÂN TÍCH INSIGHT CHIẾN LƯỢC &amp; KẾ HOẠCH HÀNH ĐỘNG", section_style))

            from src.analytics.heuristics import split_insight_sections
            sec_dict = split_insight_sections(insights, df=df, user_query=result.get("query", ""))
            p21 = sec_dict.get("anomaly", "").strip()
            p22 = sec_dict.get("hypothesis", "").strip()
            p23 = sec_dict.get("action_plan", "").strip()

            # 2.1 Phát hiện cốt lõi
            story.append(Paragraph(f"<b>{sec_num}.1. Phát hiện Bất thường &amp; Xu hướng Cốt lõi</b>", sub_section_style))
            if p21:
                for line in p21.split("\n"):
                    l_str = re.sub(r"^[•\-\*]\s*", "", line.strip()).strip()
                    if not l_str:
                        continue
                    l_clean = clean_text_for_pdf(l_str)
                    if l_clean:
                        story.append(Paragraph(f"&bull; {l_clean}", bullet_style))
            else:
                story.append(Paragraph("&bull; Dữ liệu vận hành ổn định trong biên độ chuẩn.", bullet_style))
            story.append(Spacer(1, 5))

            # 2.2 Giả thuyết & Nguyên nhân
            story.append(Paragraph(f"<b>{sec_num}.2. Giả thuyết &amp; Nguyên nhân Tiềm năng</b>", sub_section_style))
            if p22:
                for line in p22.split("\n"):
                    l_str = re.sub(r"^[•\-\*]\s*", "", line.strip()).strip()
                    if not l_str:
                        continue
                    l_clean = clean_text_for_pdf(l_str)
                    if l_clean:
                        story.append(Paragraph(f"&bull; {l_clean}", bullet_style))
            else:
                story.append(Paragraph("&bull; Cơ cấu doanh thu và sản lượng phản ánh đúng nhu cầu thị trường.", bullet_style))
            story.append(Spacer(1, 5))

            # 2.3 Khuyến nghị hành động phân cấp ưu tiên (McKinsey Action Matrix)
            story.append(Paragraph(f"<b>{sec_num}.3. Ma trận Khuyến nghị &amp; Kế hoạch Thực thi (Action Matrix)</b>", sub_section_style))
            if p23:
                for line in p23.split("\n"):
                    clean_item = clean_text_for_pdf(line.strip())
                    if not clean_item:
                        continue
                    clean_item = re.sub(r"^[•\-\*]\s*", "", clean_item)
                    clean_item = re.sub(r"^#+\s*", "", clean_item).strip()
                    clean_item = re.sub(r"\]\s*:\s*:\s*", "]: ", clean_item)
                    clean_item = re.sub(r"\s*:\s*:\s*", ": ", clean_item)

                    if any(p in clean_item for p in ["[Ưu tiên", "[High Priority", "[Medium Priority", "[Low Priority", "[Cấp Bách", "[Trung Hạn", "[Dài Hạn"]):
                        tag_match = re.match(r"^(\[(?:Ưu tiên|High Priority|Medium Priority|Low Priority|Cấp Bách|Trung Hạn|Dài Hạn)[^\]]*\])\s*:?\s*(.*)$", clean_item, flags=re.IGNORECASE)
                        if tag_match:
                            tag_text = tag_match.group(1).strip()
                            body_text = tag_match.group(2).strip()
                            body_text = re.sub(r"^[:\s\-\•\*\.]+", "", body_text).strip()
                            body_text = re.sub(r"^\d+[\.\)]\s*", "", body_text).strip()
                            body_text = re.sub(r"^[:\s\-\•\*\.]+", "", body_text).strip()
                        else:
                            tag_text = clean_item
                            body_text = ""

                        if any(k in tag_text for k in ["Cao", "High", "Cấp Bách"]):
                            tag_color = "#DC2626"
                        elif any(k in tag_text for k in ["Trung bình", "Medium", "Trung Hạn"]):
                            tag_color = "#D97706"
                        else:
                            tag_color = "#16A34A"

                        if body_text:
                            story.append(Paragraph(f"&bull; <font color='{tag_color}'><b>{tag_text}</b></font>: {body_text}", bullet_style))
                        else:
                            story.append(Paragraph(f"&bull; <font color='{tag_color}'><b>{tag_text}</b></font>", bullet_style))

                    elif any(k in clean_item.lower() for k in ["kpi", "mục tiêu đo lường", "chỉ số đo lường"]):
                        clean_kpi = re.sub(r"^(?:kpi|mục tiêu đo lường|chỉ số đo lường|kpi đo lường)\s*:\s*", "", clean_item, flags=re.IGNORECASE).strip()
                        story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;&bull; <i><b>Mục tiêu đo lường (KPI):</b> {clean_kpi}</i>", kpi_style))
                    else:
                        story.append(Paragraph(f"&bull; {clean_item}", bullet_style))
            else:
                story.append(Paragraph("&bull; Tiếp tục theo dõi chỉ số và định kỳ đánh giá hiệu quả.", bullet_style))
            story.append(Spacer(1, 8))

        # 4. PHỤ LỤC: TRUY VẤN DỮ LIỆU GỐC (SQL AUDIT TRAIL)
        sql_text = result.get("sql")
        if sql_text:
            sec_counter += 1
            sec_sql_num = str(sec_counter)
            story.append(Paragraph(f"{sec_sql_num}. PHỤ LỤC KỸ THUẬT: TRUY VẤN DỮ LIỆU (SQL AUDIT TRAIL)", section_style))
            clean_sql = clean_text_for_pdf(sql_text)
            sql_box = Table([[Paragraph(f"<font color='#334155'>{clean_sql}</font>", table_cell)]], colWidths=[515])
            sql_box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(sql_box)

        doc.build(story, canvasmaker=NumberedCanvas)
        return buffer.getvalue()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return b""


def export_resolution_to_pdf(res: dict, layer_id: str = "overview", time_label: str = "") -> bytes:
    """Xuất văn bản Nghị Quyết Hội Đồng Quản Trị & Ban Điều Hành chuẩn mực sang định dạng PDF:
    - Tiêu đề văn bản, Căn cứ pháp lý & Mã văn bản chính thức
    - Căn cứ vận hành & Chẩn đoán dữ liệu thực tế (Điểm bất thường, lượng hóa rủi ro)
    - Quyết nghị kế hoạch hành động 3 tầng (Cấp bách, Tái cấu trúc, Bền vững)
    - Hệ thống chỉ số OKRs cam kết & Bảng phân công trách nhiệm RACI (Header tương phản cao sắc nét)
    - Điều khoản thi hành & Chữ ký ban hành
    - 100% hỗ trợ tiếng Việt Unicode sắc nét, không lỗi font hay rò rỉ thẻ XML/Markdown.
    """
    if res is None:
        return b""

    buffer = io.BytesIO()
    try:
        # 1. Đăng ký Font Unicode Tiếng Việt chuẩn Font Family
        font_name, font_name_bold = setup_pdf_fonts()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=38,
            rightMargin=38,
            topMargin=42,
            bottomMargin=45
        )

        styles = getSampleStyleSheet()

        # Bảng màu sắc chuẩn Executive
        MCK_NAVY = colors.HexColor("#0F2042")      # Deep McKinsey Navy
        MCK_BLUE = colors.HexColor("#1E3A8A")      # Strategic Consulting Blue
        ACCENT_GOLD = colors.HexColor("#C5A059")   # Executive Gold
        TEXT_DARK = colors.HexColor("#1E293B")     # Slate 800
        TEXT_MUTED = colors.HexColor("#64748B")    # Slate 500
        BG_LIGHT = colors.HexColor("#F8FAFC")      # Slate 50
        BORDER_LIGHT = colors.HexColor("#E2E8F0")  # Slate 200

        title_style = ParagraphStyle(
            "ResTitle", parent=styles["Heading1"],
            fontName=font_name_bold, fontSize=15, leading=20,
            textColor=MCK_NAVY, alignment=1, spaceAfter=4,
            keepWithNext=True
        )
        meta_style = ParagraphStyle(
            "ResMeta", parent=styles["Normal"],
            fontName=font_name, fontSize=8.0, leading=12,
            textColor=TEXT_MUTED, alignment=1, spaceAfter=10,
            keepWithNext=True
        )
        section_style = ParagraphStyle(
            "ResSection", parent=styles["Heading2"],
            fontName=font_name_bold, fontSize=10.5, leading=14,
            textColor=MCK_NAVY, spaceBefore=10, spaceAfter=5,
            keepWithNext=True
        )
        subsection_style = ParagraphStyle(
            "ResSubSection", parent=styles["Heading3"],
            fontName=font_name_bold, fontSize=9.0, leading=13,
            textColor=MCK_BLUE, spaceBefore=5, spaceAfter=3,
            keepWithNext=True
        )
        body_style = ParagraphStyle(
            "ResBody", parent=styles["Normal"],
            fontName=font_name, fontSize=8.0, leading=12.5,
            textColor=TEXT_DARK, spaceAfter=3
        )
        bullet_style = ParagraphStyle(
            "ResBullet", parent=styles["Normal"],
            fontName=font_name, fontSize=8.0, leading=12.5,
            textColor=TEXT_DARK, leftIndent=8, spaceAfter=3
        )
        legal_basis_style = ParagraphStyle(
            "ResLegal", parent=styles["Normal"],
            fontName=font_name, fontSize=7.5, leading=11.5,
            textColor=colors.HexColor("#475569"), leftIndent=6, spaceAfter=2
        )
        table_cell = ParagraphStyle(
            "ResCell", parent=styles["Normal"],
            fontName=font_name, fontSize=7.8, leading=11,
            textColor=TEXT_DARK
        )
        table_cell_bold = ParagraphStyle(
            "ResCellBold", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=7.8, leading=11,
            textColor=MCK_NAVY
        )
        table_header_cell = ParagraphStyle(
            "ResHeaderCell", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=8.0, leading=11.5,
            textColor=colors.white, alignment=0
        )
        table_header_cell_center = ParagraphStyle(
            "ResHeaderCellCenter", parent=styles["Normal"],
            fontName=font_name_bold, fontSize=8.0, leading=11.5,
            textColor=colors.white, alignment=1
        )

        story = []

        health_status = res.get("health_status", "OPTIMAL")
        health_score = res.get("health_score", 95)
        anomalies = res.get("anomalies", [])
        immediate_actions = res.get("immediate_actions", [])
        structural_optimizations = res.get("structural_optimizations", [])
        sustainable_strategies = res.get("sustainable_strategies", [])
        okrs = res.get("okrs", [])
        t_label = time_label or res.get("time_label", "")

        layer_names = {
            "hr": "Khối Nhân Sự & Tổ Chức (Human Resources)",
            "sales": "Khối Kinh Doanh & Bán Hàng (Sales Performance)",
            "finance": "Khối Tài Chính & Kế Toán (Finance & Controlling)",
            "operations": "Khối Vận Hành & Chuỗi Cung Ứng (Operations)",
            "overview": "Toàn Diện Doanh Nghiệp (Enterprise Overview)"
        }
        layer_display = layer_names.get(str(layer_id).lower(), "Toàn Diện Doanh Nghiệp (Enterprise Overview)")

        # 1. Header Quốc Hiệu & Tiêu Đề Văn Bản
        story.append(Paragraph("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", ParagraphStyle("VN1", fontName=font_name_bold, fontSize=8.5, alignment=1, textColor=MCK_NAVY)))
        story.append(Paragraph("Độc lập - Tự do - Hạnh phúc", ParagraphStyle("VN2", fontName=font_name, fontSize=8.0, alignment=1, textColor=TEXT_MUTED, spaceAfter=6)))
        story.append(HRFlowable(width="28%", thickness=0.8, color=ACCENT_GOLD, spaceAfter=10, hAlign="CENTER"))

        story.append(Paragraph("NGHỊ QUYẾT HỘI ĐỒNG QUẢN TRỊ & BAN ĐIỀU HÀNH", title_style))
        clean_t_code = t_label.replace(' ', '').replace('—', '_').replace('-', '_')
        doc_code = f"Mã văn bản: NQ-BĐH/{clean_t_code or 'STRAT'} &bull; Ngày ban hành: {datetime.date.today().strftime('%d/%m/%Y')}"
        story.append(Paragraph(doc_code, meta_style))

        # Khung tóm tắt sức khỏe vận hành & phạm vi quản trị
        clean_health_status = clean_text_for_pdf(health_status)
        health_color = "#DC2626" if "CRITICAL" in health_status else ("#D97706" if "WARNING" in health_status else "#16A34A")
        summary_table_data = [
            [
                Paragraph("<b>Kỳ Khảo Sát & Phạm Vi:</b>", table_cell_bold),
                Paragraph(t_label, table_cell),
                Paragraph("<b>Sức Khỏe Vận Hành:</b>", table_cell_bold),
                Paragraph(f"<font color='{health_color}'><b>{clean_health_status} ({health_score}/100)</b></font>", table_cell)
            ],
            [
                Paragraph("<b>Phân Hệ Quản Trị:</b>", table_cell_bold),
                Paragraph(layer_display, table_cell),
                Paragraph("<b>Cơ Chế Giám Sát:</b>", table_cell_bold),
                Paragraph("Ban Điều Hành &amp; HĐQT Giám Sát Trực Tiếp", table_cell)
            ]
        ]
        summary_table = Table(summary_table_data, colWidths=[115, 145, 115, 144])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.8, BORDER_LIGHT),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER_LIGHT),
            ("PADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 6))

        # Căn cứ pháp lý & Quy chế
        story.append(Paragraph("<i>&bull; Căn cứ Điều lệ Tổ chức &amp; Hoạt động của Doanh nghiệp;</i>", legal_basis_style))
        story.append(Paragraph("<i>&bull; Căn cứ Báo cáo Giám sát Vận hành &amp; Phân tích Dị thường Dữ liệu tự động Veraxus;</i>", legal_basis_style))
        story.append(Paragraph("<i>&bull; Căn cứ Biên bản họp thống nhất của Hội đồng Quản trị &amp; Ban Điều hành doanh nghiệp.</i>", legal_basis_style))
        story.append(Spacer(1, 6))

        # ĐIỀU 1. CĂN CỨ VẬN HÀNH & KẾT QUẢ CHẨN ĐOÁN DỮ LIỆU ĐỊNH LƯỢNG
        story.append(Paragraph("ĐIỀU 1. CĂN CỨ VẬN HÀNH & KẾT QUẢ CHẨN ĐOÁN DỮ LIỆU ĐỊNH LƯỢNG", section_style))
        story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER_LIGHT, spaceAfter=5))

        if anomalies:
            for idx, a in enumerate(anomalies, 1):
                clean_title = clean_text_for_pdf(a.get("title", ""))
                clean_sev = clean_text_for_pdf(a.get("severity", ""))
                clean_metrics = clean_text_for_pdf(a.get("metrics_summary", ""))
                clean_rc = clean_text_for_pdf(a.get("root_cause", ""))
                clean_imp = clean_text_for_pdf(a.get("quantified_impact", ""))

                sev_c = "#DC2626" if "CRITICAL" in a.get("severity", "") else "#D97706"

                story.append(Paragraph(f"<b>1.{idx}. {clean_title}</b> [<font color='{sev_c}'><b>{clean_sev}</b></font>]", subsection_style))
                story.append(Paragraph(f"&bull; <b>Số liệu thực tế:</b> {clean_metrics}", bullet_style))
                story.append(Paragraph(f"&bull; <b>Nguyên nhân gốc rễ (Root Cause):</b> {clean_rc}", bullet_style))
                story.append(Paragraph(f"&bull; <b>Lượng hóa rủi ro & tác động:</b> <font color='#DC2626'>{clean_imp}</font>", bullet_style))
                story.append(Spacer(1, 3))
        else:
            story.append(Paragraph(f"&bull; Toàn bộ các chỉ số vận hành duy trì trạng thái ổn định và cân bằng trong {t_label}.", body_style))

        # ĐIỀU 2. QUYẾT NGHỊ KẾ HOẠCH HÀNH ĐỘNG CHIẾN LƯỢC 3 TẦNG
        story.append(Spacer(1, 4))
        story.append(Paragraph("ĐIỀU 2. QUYẾT NGHỊ KẾ HOẠCH HÀNH ĐỘNG CHIẾN LƯỢC 3 TẦNG", section_style))
        story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER_LIGHT, spaceAfter=5))

        story.append(Paragraph("1. TẦNG 1: CAN THIỆP CẤP BÁCH (0 — 30 NGÀY)", subsection_style))
        for act in immediate_actions:
            story.append(Paragraph(f"&bull; {clean_text_for_pdf(act)}", bullet_style))
        story.append(Spacer(1, 3))

        story.append(Paragraph("2. TẦNG 2: TÁI CẤU TRÚC & HOÀN THIỆN CHÍNH SÁCH (1 — 2 QUÝ)", subsection_style))
        for act in structural_optimizations:
            story.append(Paragraph(f"&bull; {clean_text_for_pdf(act)}", bullet_style))
        story.append(Spacer(1, 3))

        story.append(Paragraph("3. TẦNG 3: QUY HOẠCH NGUỒN LỰC & PHÁT TRIỂN BỀN VỮNG (1 — 3 NĂM)", subsection_style))
        for act in sustainable_strategies:
            story.append(Paragraph(f"&bull; {clean_text_for_pdf(act)}", bullet_style))
        story.append(Spacer(1, 5))

        # ĐIỀU 3. HỆ THỐNG CHỈ SỐ CAM KẾT OKRS & PHÂN CÔNG TRÁCH NHIỆM RACI
        story.append(Paragraph("ĐIỀU 3. HỆ THỐNG CHỈ SỐ CAM KẾT OKRS & PHÂN CÔNG TRÁCH NHIỆM RACI", section_style))
        story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER_LIGHT, spaceAfter=5))

        for okr in okrs:
            story.append(Paragraph(f"&bull; <b>Chỉ số cam kết (OKR):</b> {clean_text_for_pdf(okr)}", bullet_style))
        story.append(Spacer(1, 5))

        # Bảng ma trận RACI với Header tương phản cao (chữ trắng trên nền Navy)
        raci_data = [
            [
                Paragraph("<b>Đơn Vị / Vị Trí Phụ Trách</b>", table_header_cell),
                Paragraph("<b>Vai Trò RACI</b>", table_header_cell_center),
                Paragraph("<b>Nội Dung Phụ Trách & Nhiệm Vụ Cốt Lõi</b>", table_header_cell)
            ],
            [
                Paragraph("<b>Ban Tổng Giám Đốc (CEO / Board)</b>", table_cell),
                Paragraph("<font color='#DC2626'><b>A</b> (Accountable)</font>", ParagraphStyle("R1", parent=table_cell, alignment=1)),
                Paragraph("Phê duyệt định biên ngân sách, quyết định tái cơ cấu và ký ban hành nghị quyết.", table_cell)
            ],
            [
                Paragraph("<b>Giám Đốc Nhân Sự (CHRO)</b>", table_cell),
                Paragraph("<font color='#1E40AF'><b>R</b> (Responsible)</font>", ParagraphStyle("R2", parent=table_cell, alignment=1)),
                Paragraph("Chủ trì thực thi Tầng 1 & Tầng 2, chuẩn hóa Salary Banding và lộ trình thăng tiến.", table_cell)
            ],
            [
                Paragraph("<b>Giám Đốc Vận Hành / Kỹ Thuật (COO/CTO)</b>", table_cell),
                Paragraph("<font color='#1E40AF'><b>R</b> (Responsible)</font>", ParagraphStyle("R3", parent=table_cell, alignment=1)),
                Paragraph("Tái bố trí định biên lao động, chuẩn hóa quy trình và kiện toàn đội ngũ Lead cấp trung.", table_cell)
            ],
            [
                Paragraph("<b>Giám Đốc Tài Chính (CFO)</b>", table_cell),
                Paragraph("<font color='#D97706'><b>C</b> (Consulted)</font>", ParagraphStyle("R4", parent=table_cell, alignment=1)),
                Paragraph("Thẩm định quỹ lương, mô phỏng chi phí tối ưu và kiểm soát ngân sách vận hành.", table_cell)
            ],
            [
                Paragraph("<b>Trưởng Bộ Phận / Line Managers</b>", table_cell),
                Paragraph("<font color='#64748B'><b>I</b> (Informed)</font>", ParagraphStyle("R5", parent=table_cell, alignment=1)),
                Paragraph("Tiếp nhận hướng dẫn, truyền thông chính sách mới và giám sát thực thi tại cơ sở.", table_cell)
            ],
        ]
        raci_table = Table(raci_data, colWidths=[135, 95, 289])
        raci_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2042")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.8, BORDER_LIGHT),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER_LIGHT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
            ("PADDING", (0, 0), (-1, -1), 4.5),
            ("TOPPADDING", (0, 0), (-1, 0), 5.5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5.5),
        ]))
        story.append(raci_table)
        story.append(Spacer(1, 6))

        # ĐIỀU 4. ĐIỀU KHOẢN THI HÀNH & HIỆU LỰC ÁP DỤNG
        story.append(Paragraph("ĐIỀU 4. ĐIỀU KHOẢN THI HÀNH & HIỆU LỰC ÁP DỤNG", section_style))
        story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER_LIGHT, spaceAfter=5))
        story.append(Paragraph(
            "Nghị quyết này có hiệu lực thi hành kể từ ngày ký. Ban Tổng Giám Đốc, các Giám đốc Khối chức năng và Trưởng các bộ phận "
            "trực thuộc chịu trách nhiệm tổ chức triển khai, định kỳ báo cáo tiến độ thực hiện các mục tiêu OKRs nêu trên về Văn phòng Điều hành.",
            body_style
        ))
        story.append(Spacer(1, 10))

        # Chữ ký / Ban hành
        sig_data = [
            [
                Paragraph("<b>ĐẠI DIỆN HỘI ĐỒNG QUẢN TRỊ</b><br/><font color='#64748B'><i>(Ký và đóng dấu)</i></font>", ParagraphStyle("Sig1", fontName=font_name, fontSize=8.0, alignment=1, leading=11)),
                Paragraph("<b>TỔNG GIÁM ĐỐC ĐIỀU HÀNH (CEO)</b><br/><font color='#64748B'><i>(Ký và ghi rõ họ tên)</i></font>", ParagraphStyle("Sig2", fontName=font_name, fontSize=8.0, alignment=1, leading=11))
            ]
        ]
        sig_table = Table(sig_data, colWidths=[255, 264])
        sig_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(sig_table)

        doc.build(story, canvasmaker=NumberedCanvas)
        return buffer.getvalue()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return b""
