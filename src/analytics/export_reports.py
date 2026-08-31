"""
Export utilities for Multi-format Reporting:
- Styled Excel (.xlsx) with custom headers, cell borders, and currency/date formatting.
- High-Resolution PNG (.png) for charts and slides.
- Executive PDF Report (.pdf) with summary metrics, data tables, strategic insights, and SQL queries.
"""

import io
import os
import re
import datetime
import pandas as pd


def clean_markdown_for_pdf(text: str) -> str:
    """Chuyển đổi markdown cơ bản (**, *, `, <, >) sang định dạng XML an toàn cho ReportLab Paragraph."""
    if not text:
        return ""
    # Thoát các ký tự đặc biệt XML trước
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Chuyển **bold** thành <b>bold</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Chuyển *italic* thành <i>italic</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    # Chuyển `code` thành <b>code</b>
    text = re.sub(r'`(.*?)`', r'<b>\1</b>', text)
    return text


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
                is_num = pd.api.types.is_numeric_dtype(df[col])
                for row_idx in range(2, len(df) + 2):
                    c = ws.cell(row=row_idx, column=col_idx)
                    c.border = border_thin
                    if is_num:
                        c.number_format = "#,##0"
                        c.alignment = Alignment(horizontal="right")
                    else:
                        c.alignment = Alignment(horizontal="left")

        return output.getvalue()
    except Exception:
        # Fallback xuất excel cơ bản nếu gặp sự cố styling
        output = io.BytesIO()
        df.to_excel(output, index=False)
        return output.getvalue()


# ---------------------------------------------------------
# 2. Xuất Ảnh Biểu Đồ PNG Độ Nét Cao
# ---------------------------------------------------------
def export_to_png(fig) -> bytes | None:
    """Xuất biểu đồ Plotly sang ảnh PNG độ phân giải cao (2x Resolution) để chèn PowerPoint."""
    if fig is None:
        return None
    try:
        return fig.to_image(format="png", width=1000, height=550, scale=2)
    except Exception:
        return None


# ---------------------------------------------------------
# 3. Xuất Tóm Tắt Báo Cáo Executive PDF (.pdf)
# ---------------------------------------------------------
def export_to_pdf(result: dict, df: pd.DataFrame, chart_png_bytes: bytes = None) -> bytes:
    """Tạo tài liệu Báo cáo Điều hành PDF (Executive Report) hoàn chỉnh."""
    if result is None:
        return b""

    buffer = io.BytesIO()
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_name = "Helvetica"
        font_name_bold = "Helvetica-Bold"

        # Đăng ký font Unicode nếu có trên hệ điều hành
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
                    break
                except Exception:
                    pass

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontName=font_name_bold,
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1F4E78"),
            spaceAfter=4
        )
        subtitle_style = ParagraphStyle(
            "DocSub",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#555555"),
            spaceAfter=8
        )
        section_style = ParagraphStyle(
            "SectionHead",
            parent=styles["Heading2"],
            fontName=font_name_bold,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#1F4E78"),
            spaceBefore=8,
            spaceAfter=5
        )
        body_style = ParagraphStyle(
            "BodyText",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=8.5,
            leading=12,
            spaceAfter=3
        )
        table_cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=8,
            leading=11,
        )
        table_cell_header = ParagraphStyle(
            "TableHead",
            parent=styles["Normal"],
            fontName=font_name_bold,
            fontSize=8,
            leading=11,
            textColor=colors.whitesmoke,
        )

        story = []

        # 1. Header Báo cáo
        story.append(Paragraph("Veraxus for SQL - Executive Business Report", title_style))
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        query_text = clean_markdown_for_pdf(result.get("query", ""))
        story.append(Paragraph(f"<b>Query:</b> {query_text} &nbsp;|&nbsp; <b>Exported at:</b> {now_str}", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1F4E78"), spaceAfter=8))

        # 2. Bảng Tóm Tắt Dữ liệu
        if df is not None and not df.empty:
            story.append(Paragraph(f"Summary Data Table (Top {min(10, len(df))} of {len(df)} rows)", section_style))
            preview_df = df.head(10)

            n_cols = len(preview_df.columns)
            col_w = max(45, min(140, 520 / max(1, n_cols)))

            table_data = [[Paragraph(f"<b>{clean_markdown_for_pdf(str(c))}</b>", table_cell_header) for c in preview_df.columns]]
            for _, row in preview_df.iterrows():
                row_cells = []
                for c in preview_df.columns:
                    val = row[c]
                    val_str = f"{val:,.0f}" if isinstance(val, (int, float)) else str(val)
                    row_cells.append(Paragraph(clean_markdown_for_pdf(val_str), table_cell_style))
                table_data.append(row_cells)

            t = Table(table_data, colWidths=[col_w] * n_cols)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
            ]))
            story.append(t)
            story.append(Spacer(1, 8))

        # 3. Ảnh Biểu đồ (nếu có)
        if chart_png_bytes:
            story.append(Paragraph("Visual Analysis Chart", section_style))
            img_buffer = io.BytesIO(chart_png_bytes)
            story.append(Image(img_buffer, width=500, height=250))
            story.append(Spacer(1, 8))

        # 4. Bản Phân Tích Insight Chiến Lược & Priority Action Plan
        insights = result.get("insights")
        if insights:
            story.append(Paragraph("Strategic Insights & Priority Action Plan", section_style))
            for line in insights.split("\n"):
                clean_line = line.strip()
                if not clean_line:
                    continue
                if clean_line.startswith("###"):
                    h_text = clean_line.replace("#", "").strip()
                    story.append(Paragraph(f"<b>{clean_markdown_for_pdf(h_text)}</b>", section_style))
                elif clean_line.startswith("-"):
                    item_text = clean_line[1:].strip()
                    story.append(Paragraph(f"• {clean_markdown_for_pdf(item_text)}", body_style))
                else:
                    story.append(Paragraph(clean_markdown_for_pdf(clean_line), body_style))
            story.append(Spacer(1, 8))

        # 5. Chi Tiết Câu Lệnh SQL
        sql_text = result.get("sql")
        if sql_text:
            story.append(Paragraph("Executed SQL Query", section_style))
            sql_box_data = [[Paragraph(f"<font color='#333333'>{clean_markdown_for_pdf(sql_text)}</font>", table_cell_style)]]
            sql_table = Table(sql_box_data, colWidths=[520])
            sql_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F4F7")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(sql_table)

        doc.build(story)
        return buffer.getvalue()
    except Exception as e:
        return b""
