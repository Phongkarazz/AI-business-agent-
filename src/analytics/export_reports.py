"""
Export utilities for Multi-format Reporting:
- Styled Excel (.xlsx) with custom headers, cell borders, and currency/date formatting.
- High-Resolution PNG (.png) for charts and slides.
- Executive PDF Report (.pdf) with 100% Vietnamese Unicode font support, clean typography,
  complete emoji stripping (no white boxes), and professional business layout.
"""

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
    """Loại bỏ triệt để các emoji gây lỗi ô vuông trắng và chuẩn hóa cú pháp XML an toàn cho ReportLab."""
    if not text:
        return ""

    text = str(text)

    # 1. Chuyển đổi / gỡ bỏ các biểu tượng ưu tiên, huy chương và ký tự glyph lạ
    for glyph in ["🔴", "🟡", "🟢", "🥇", "🥈", "🥉", "↳", "➔", "➜", "➡", "►", "□"]:
        text = text.replace(glyph, "")

    # 2. Xóa toàn bộ emoji unicode gây lỗi ô vuông tofu
    text = EMOJI_REGEX.sub("", text)

    # 3. Tách từ viết hoa dính liền với từ tiếng Việt an toàn (sử dụng bảng ký tự rõ ràng để tránh lỗi chia tách từ in hoa có dấu)
    vn_lower = "a-zàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    vn_upper = "A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ"
    text = re.sub(rf"([{vn_upper}]{{2,}})([{vn_upper}][{vn_lower}])", r"\1 \2", text)
    text = re.sub(rf"([{vn_upper}]{{2,}})([{vn_lower}])", r"\1 \2", text)

    # 4. Thêm khoảng trắng sau dấu hai chấm nếu bị dính số hoặc chữ và sửa lỗi 2 dấu hai chấm
    text = re.sub(r"\]\s*:\s*:\s*", "]: ", text)
    text = re.sub(r"\s*:\s*:\s*", ": ", text)
    text = re.sub(rf"([{vn_upper}{vn_lower}]):(\d)", r"\1: \2", text)
    text = re.sub(rf":([{vn_upper}{vn_lower}])", r": \1", text)

    # 5. Thoát các ký tự XML đặc biệt
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Chuyển đổi cú pháp markdown sang thẻ định dạng ReportLab
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.*?)`", r"<b>\1</b>", text)

    # Đảm bảo khoảng trắng hợp lý quanh thẻ in đậm nếu dính chữ/số
    text = re.sub(rf"</b>([{vn_upper}{vn_lower}0-9])", r"</b> \1", text)
    text = re.sub(rf"([{vn_upper}{vn_lower}0-9])<b>", r"\1 <b>", text)

    # 7. Xóa các ký tự markdown header #### dư thừa trong dòng
    text = re.sub(r"#+\s*", "", text)

    # 8. Dọn dẹp khoảng trắng thừa và ký tự rác đầu mục
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"^\s*[\.\-•]\s*", "", text.strip())

    return text.strip()


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
        output = io.BytesIO()
        df.to_excel(output, index=False)
        return output.getvalue()


# ---------------------------------------------------------
# 2. Xuất Ảnh Biểu Đồ PNG Độ Nét Cao
# ---------------------------------------------------------
def export_to_png(fig) -> bytes | None:
    """Xuất biểu đồ Plotly sang ảnh PNG.
    Đã tắt việc gọi Chrome headless ngầm để chống treo server (người dùng tải trực tiếp qua nút Camera 📷 trên biểu đồ).
    """
    return None


# ---------------------------------------------------------
# 3. Xuất Báo Cáo Quản Trị Executive PDF Chuẩn McKinsey / BCG
# ---------------------------------------------------------
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


class NumberedCanvas(canvas.Canvas):
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
                        break
                    except Exception:
                        pass

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
            textColor=MCK_NAVY, spaceBefore=14, spaceAfter=7
        )
        sub_section_style = ParagraphStyle(
            "SubSectionHead", parent=styles["Heading3"],
            fontName=font_name_bold, fontSize=9.5, leading=13.5,
            textColor=MCK_BLUE, spaceBefore=8, spaceAfter=4, leftIndent=2
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

                    def _fmt_val(v):
                        if is_pct:
                            return f"{float(v):.2f}%"
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
            preview_df = df.head(15)
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
                            if any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ"]):
                                formatted = f"{num_v:.2f}%"
                            elif any(k in c_low for k in ["salary", "lương", "cost", "revenue", "sales", "amount", "profit", "budget"]):
                                formatted = f"${num_v:,.2f}" if (not num_v.is_integer() and abs(num_v) < 1000) else f"${num_v:,.0f}"
                            elif any(k in c_low for k in ["boxes", "count", "số lượng", "headcount", "employees"]):
                                formatted = f"{num_v:,.0f}"
                            else:
                                formatted = f"{num_v:,.0f}" if num_v.is_integer() else f"{num_v:,.2f}"
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
                            if any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ", "avg", "per_box", "perbox", "cost"]):
                                avg_v = v_col.mean()
                                fmt_s = f"{avg_v:.2f}%" if any(k in c_low for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ"]) else f"${avg_v:,.2f}"
                            else:
                                sum_v = v_col.sum()
                                fmt_s = f"${sum_v:,.0f}" if any(k in c_low for k in ["salary", "sales", "revenue", "amount", "budget"]) else f"{sum_v:,.0f}"
                            summary_cells.append(Paragraph(f"<b>{fmt_s}</b>", table_cell_num_bold))
                        else:
                            summary_cells.append(Paragraph("", table_cell))
                    else:
                        summary_cells.append(Paragraph("", table_cell))
                table_rows.append(summary_cells)

            t = Table(table_rows, colWidths=final_widths)
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
            story.append(Spacer(1, 10))

        # 2. BIỂU ĐỒ TRỰC QUAN HÓA CHIẾN LƯỢC (nếu có ảnh chart)
        if chart_png_bytes:
            try:
                img_buffer = io.BytesIO(chart_png_bytes)
                img_obj = Image(img_buffer, width=515, height=230)
                sec_counter += 1
                story.append(Paragraph(f"{sec_counter}. BIỂU ĐỒ TRỰC QUAN HÓA CHIẾN LƯỢC (STRATEGIC VISUALIZATION)", section_style))
                story.append(img_obj)
                story.append(Spacer(1, 10))
            except Exception:
                pass

        # 3. PHÂN TÍCH INSIGHT CHIẾN LƯỢC & KẾ HOẠCH HÀNH ĐỘNG
        insights = result.get("insights")
        if insights:
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
                    l_clean = clean_text_for_pdf(line.strip())
                    if l_clean:
                        l_clean = re.sub(r"^[•\-\*]\s*", "", l_clean)
                        story.append(Paragraph(f"&bull; {l_clean}", bullet_style))
            else:
                story.append(Paragraph("&bull; Dữ liệu vận hành ổn định trong biên độ chuẩn.", bullet_style))
            story.append(Spacer(1, 5))

            # 2.2 Giả thuyết & Nguyên nhân
            story.append(Paragraph(f"<b>{sec_num}.2. Giả thuyết &amp; Nguyên nhân Tiềm năng</b>", sub_section_style))
            if p22:
                for line in p22.split("\n"):
                    l_clean = clean_text_for_pdf(line.strip())
                    if l_clean:
                        l_clean = re.sub(r"^[•\-\*]\s*", "", l_clean)
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
