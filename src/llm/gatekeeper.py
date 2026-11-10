"""
When2Call & BFCL Action Gatekeeper Module
Đóng vai trò Cổng kiểm soát hành vi (Action Gatekeeper) theo chuẩn nghiên cứu When2Call (NVIDIA 2025)
và Berkeley Function Calling Leaderboard (BFCL):
Phân định 3 ngã rẽ hành vi trước khi gọi SQL Generator:
1. Tool SQL (tool_sql): Câu hỏi nghiệp vụ hợp lệ -> Chuyển tiếp tới Multi-Agent SQL Pipeline.
2. Proactive Clarification (ask_missing_info): Câu hỏi mơ hồ thiếu chiều phân tích -> Chủ động hỏi lại & đề xuất nút bấm 1-click.
3. Safe Abstain (abstain): Câu hỏi nằm ngoài phạm vi CSDL (thời tiết, thơ văn, nấu ăn, tài chính bên ngoài...) -> Từ chối lịch sự, tránh ảo giác (Hallucination).
"""

import re
from typing import Dict, Any, List, Optional
from src.analytics.heuristics import detect_query_language


# =========================================================================
# 1. TỪ ĐIỂN TỪ KHÓA & REGEX NGOÀI PHẠM VI (OUT-OF-DOMAIN ABSTAIN)
# =========================================================================

WEATHER_PATTERNS = [
    r"\bthời\s*tiết\b", r"\bdự\s*báo\s*thời\s*tiết\b", r"\bmưa\b", r"\bnắng\b",
    r"\bnhiệt\s*độ\b", r"\bkhí\s*hậu\b", r"\bđộ\s*ẩm\b", r"\báp\s*suất\s*khí\s*quyển\b",
    r"\bbão\b", r"\báp\s*thấp\b", r"\bgió\s*mùa\b", r"\blốc\s*xoáy\b", r"\blũ\s*lụt\b",
    r"\bhạn\s*hán\b", r"\bweather\b", r"\bforecast\b", r"\brain\b", r"\braining\b",
    r"\btemperature\b", r"\bhumidity\b", r"\bclimate\b", r"\bsunny\b", r"\bstorm\b",
    r"\bprecipitation\b", r"\bwind\s*speed\b"
]

CREATIVE_PATTERNS = [
    r"\blàm\s*thơ\b", r"\bbài\s*thơ\b", r"\bthơ\s*tình\b", r"\bthơ\s*lục\s*bát\b",
    r"\bkể\s*chuyện\s*cười\b", r"\btruyện\s*cười\b", r"\bviết\s*thư\s*tình\b",
    r"\bthư\s*tình\b", r"\bviết\s*tiểu\s*thuyết\b", r"\btấu\s*hài\b", r"\bhát\b",
    r"\bbài\s*hát\b", r"\bviết\s*truyện\b", r"\bpoem\b", r"\bpoetry\b", r"\brhyme\b",
    r"\bjoke\b", r"\btell\s*me\s*a\s*joke\b", r"\bfunny\s*story\b", r"\blove\s*letter\b",
    r"\bwrite\s*a\s*poem\b", r"\bcompose\s*a\s*song\b", r"\bsong\s*lyrics\b"
]

COOKING_PATTERNS = [
    r"\bcông\s*thức\s*nấu\b", r"\bcách\s*nấu\b", r"\bcách\s*làm\s*bánh\b",
    r"\bcách\s*pha\s*chế\b", r"\bhướng\s*dẫn\s*nấu\b", r"\bcách\s*chế\s*biến\b",
    r"\bmón\s*ăn\b", r"\bnguyên\s*liệu\s*nấu\b", r"\bnấu\s*món\b", r"\brecipe\b",
    r"\bcook\b", r"\bbake\b", r"\bhow\s*to\s*cook\b", r"\bhow\s*to\s*bake\b",
    r"\bculinary\s*recipe\b", r"\bcooking\s*guide\b", r"\bingredients\s*for\s*cooking\b"
]

EXTERNAL_FINANCE_PATTERNS = [
    r"\bgiá\s*vàng\b", r"\bgiá\s*vàng\s*sjc\b", r"\bbitcoin\b", r"\bbtc\b",
    r"\bethereum\b", r"\beth\b", r"\btiền\s*ảo\b", r"\btiền\s*mã\s*hóa\b",
    r"\bcrypto\b", r"\btỷ\s*giá\s*ngoại\s*tệ\b", r"\bvé\s*số\b", r"\bxổ\s*số\b",
    r"\blô\s*đề\b", r"\bvietlott\b", r"\bgiá\s*cổ\s*phiếu\s*vinfast\b",
    r"\bchứng\s*khoán\s*phái\s*sinh\b", r"\bgold\s*price\b", r"\bsjc\s*gold\b",
    r"\bcryptocurrency\b", r"\bcrypto\s*price\b", r"\blottery\b",
    r"\bexchange\s*rate\s*usd\b", r"\bforeign\s*exchange\s*rate\b"
]

MEDICAL_PATTERNS = [
    r"\bchữa\s*bệnh\b", r"\buống\s*thuốc\b", r"\btriệu\s*chứng\b", r"\bbị\s*sốt\b",
    r"\bbị\s*ho\b", r"\bđau\s*đầu\b", r"\bbác\s*sĩ\b", r"\bkê\s*đơn\b", r"\bkhám\s*bệnh\b",
    r"\bmedical\s*advice\b", r"\bdiagnosis\b", r"\bsymptom\b", r"\bcure\s*for\b",
    r"\btreatment\s*for\b", r"\bprescription\b"
]

SPORTS_POLITICS_PATTERNS = [
    r"\bkết\s*quả\s*bóng\s*đá\b", r"\bbóng\s*đá\s*ngoại\s*hạng\b", r"\bvô\s*địch\s*world\s*cup\b",
    r"\bchính\s*trị\s*gia\b", r"\btổng\s*thống\s*mỹ\s*hiện\s*tại\b", r"\bdân\s*số\s*thế\s*giới\b",
    r"\bai\s*là\s*tổng\s*thống\b", r"\bpremier\s*league\s*standings\b",
    r"\bworld\s*cup\s*winner\b", r"\bwho\s*is\s*president\b", r"\bcurrent\s*president\s*of\b"
]

TIME_CLOCK_PATTERNS = [
    r"\bmấy\s*giờ\b", r"\bbây\s*giờ\s*là\s*mấy\s*giờ\b", r"\bthời\s*gian\s*hiện\s*tại\b",
    r"\bhôm\s*nay\s*là\s*ngày\s*mấy\b", r"\bhôm\s*nay\s*thứ\s*mấy\b",
    r"\bwhat\s*time\s*is\s*it\b", r"\bcurrent\s*time\b", r"\btoday\s*date\b"
]

GENERAL_TRIVIA_PATTERNS = [
    r"\bthủ\s*đô\s*của\b", r"\bcapital\s*of\b", r"\bdân\s*số\s*thế\s*giới\b",
    r"\bdân\s*số\s*của\b", r"\bpopulation\s*of\b", r"\bai\s*phát\s*minh\b",
    r"\bwho\s*invented\b", r"\bdịch\s*đoạn\s*văn\b", r"\bdịch\s*câu\s*này\b",
    r"\btranslate\s*this\b", r"\bhôm\s*nay\s*ăn\s*gì\b", r"\bgợi\s*ý\s*món\s*ăn\b",
    r"\băn\s*trưa\s*gì\b", r"\bwhat\s*should\s*i\s*eat\b"
]


# =========================================================================
# 2. HÀM KIỂM TRA ACTION GATEKEEPER
# =========================================================================

def classify_action_gate(
    user_query: str,
    schema_context: str = "",
    lang: str = "vi"
) -> Dict[str, Any]:
    """Phân loại câu hỏi thành một trong 3 nhánh When2Call:
    - tool_sql: Hợp lệ -> Tiếp tục chạy SQL
    - ask_missing_info: Mơ hồ -> Dừng lại và hỏi làm rõ
    - abstain: Ngoài phạm vi -> Dừng lại và từ chối an toàn
    """
    if not user_query or not user_query.strip():
        return {
            "action": "ask_missing_info",
            "category": "empty_query",
            "explanation": "Vui lòng nhập câu hỏi hoặc yêu cầu phân tích dữ liệu kinh doanh." if lang != "en" else "Please enter a business data question or analysis request.",
            "followups": [
                "Tổng doanh thu toàn hệ thống",
                "Top 5 sản phẩm bán chạy nhất",
                "Doanh số bán hàng theo quốc gia"
            ] if lang != "en" else [
                "Total system revenue",
                "Top 5 best-selling products",
                "Sales revenue by country"
            ]
        }

    q_clean = user_query.strip()
    q_low = q_clean.lower()
    is_en = (lang == "en")

    # -------------------------------------------------------------------------
    # BƯỚC 1: KIỂM TRA TỪ CHỐI AN TOÀN (OUT-OF-DOMAIN ABSTAIN)
    # -------------------------------------------------------------------------
    # Kiểm tra Thời tiết
    if any(re.search(pat, q_low) for pat in WEATHER_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_weather",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Tôi là **AI Business Analyst & Trợ lý Dữ liệu Doanh nghiệp**. Tôi chỉ hỗ trợ truy vấn, thống kê và phân tích các chỉ số trong cơ sở dữ liệu nội bộ của doanh nghiệp (như doanh số bán hàng, sản phẩm, nhân sự, đơn hàng, khách hàng, thị trường).\n\n"
                f"👉 Câu hỏi: *\"{q_clean}\"* liên quan đến **thời tiết & khí tượng**, nằm ngoài phạm vi dữ liệu vận hành doanh nghiệp.\n\n"
                f"**Gợi ý các câu hỏi dữ liệu kinh doanh bạn có thể thử ngay:**"
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"I am an **AI Business Analyst & Enterprise Data Assistant**. I only assist with querying, aggregating, and analyzing metrics from your internal business databases (sales, products, people, orders, customers, markets).\n\n"
                f"👉 The query: *\"{q_clean}\"* is about **weather/meteorology**, which is outside internal enterprise databases.\n\n"
                f"**Suggested business data queries you can explore:**"
            ),
            "followups": [
                "Tổng doanh thu và tổng số hộp bán ra toàn hệ thống" if not is_en else "Total revenue and total boxes sold",
                "Top 5 sản phẩm có doanh thu cao nhất năm 2022" if not is_en else "Top 5 products by revenue in 2022",
                "Doanh số bán hàng phân bổ theo từng quốc gia" if not is_en else "Sales distribution by country"
            ]
        }

    # Kiểm tra Sáng tác / Thơ văn / Truyện cười
    if any(re.search(pat, q_low) for pat in CREATIVE_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_creative",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Tôi được thiết lập chuyên sâu cho vai trò **Giám đốc Dữ liệu Điều hành (AI Business Analyst)**, hỗ trợ phân tích dữ liệu kinh doanh và báo cáo trực quan cho Ban Lãnh đạo.\n\n"
                f"👉 Tôi không hỗ trợ sáng tác thơ văn, kể chuyện cười hay viết nội dung giải trí bên ngoài CSDL doanh nghiệp."
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"I am dedicated to **Executive Business Data Analysis**, providing data insights and interactive charts for leadership.\n\n"
                f"👉 I do not generate creative writing, jokes, or fictional content outside enterprise business databases."
            ),
            "followups": [
                "Top 10 nhân sự bán hàng xuất sắc nhất" if not is_en else "Top 10 salespeople by box volume",
                "Hiệu suất doanh số của các Team kinh doanh" if not is_en else "Sales performance by business team",
                "Giá trị đơn hàng trung bình (AOV) trong năm 2021" if not is_en else "Average Order Value (AOV) in 2021"
            ]
        }

    # Kiểm tra Công thức nấu ăn / Chế biến ẩm thực
    if any(re.search(pat, q_low) for pat in COOKING_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_cooking",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Mặc dù doanh nghiệp kinh doanh các sản phẩm chocolate và bánh kẹo ngọt, cơ sở dữ liệu nội bộ chỉ lưu trữ thông tin về **mã sản phẩm, danh mục, giá bán và doanh số đơn hàng**, không lưu trữ công thức chế biến ẩm thực hay hướng dẫn làm bánh.\n\n"
                f"👉 Bạn có thể tra cứu thông tin doanh số, số lượng hộp bán hoặc giá tiền của các sản phẩm này."
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"Although the enterprise sells chocolate and confectionery products, the database stores **product codes, categories, pricing, and sales transactions**, not culinary recipes or cooking instructions.\n\n"
                f"👉 You can query sales revenue, box volume, or prices of these confectionery items."
            ),
            "followups": [
                "Doanh thu theo từng danh mục sản phẩm (Category)" if not is_en else "Revenue by product category",
                "Top 5 sản phẩm có doanh thu cao nhất" if not is_en else "Top 5 products by revenue",
                "Danh sách các sản phẩm và giá bán tương ứng" if not is_en else "List of products and unit prices"
            ]
        }

    # Kiểm tra Tài chính bên ngoài / Crypto / Giá vàng / Xổ số
    if any(re.search(pat, q_low) for pat in EXTERNAL_FINANCE_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_finance",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Cơ sở dữ liệu hiện tại chỉ lưu trữ số liệu giao dịch và vận hành nội bộ của doanh nghiệp, không kết nối luồng dữ liệu thời gian thực từ thị trường vàng, chứng khoán bên ngoài hay tiền mã hóa (crypto)."
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"The current database only stores internal enterprise operations and sales transactions. It is not connected to external real-time feeds for gold prices, stock tickers, or cryptocurrencies."
            ),
            "followups": [
                "Tổng doanh thu và tổng số hộp bán ra toàn hệ thống" if not is_en else "Total revenue and total boxes sold",
                "Các đơn hàng có giá trị lớn trên $10,000" if not is_en else "Large orders over $10,000",
                "Doanh thu trung bình mỗi tháng trong năm 2022" if not is_en else "Average monthly revenue in 2022"
            ]
        }

    # Kiểm tra Y tế / Khám bệnh / Thuốc men
    if any(re.search(pat, q_low) for pat in MEDICAL_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_medical",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Tôi là Trợ lý Dữ liệu Kinh doanh Doanh nghiệp và không cung cấp tư vấn y tế, chẩn đoán triệu chứng hay kê đơn thuốc."
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"I am an Enterprise Business Data Assistant and do not provide medical consultations, diagnosis, or drug prescriptions."
            ),
            "followups": [
                "Tổng doanh thu và số lượng đơn hàng" if not is_en else "Total revenue and order count",
                "Top 5 sản phẩm bán chạy nhất" if not is_en else "Top 5 best-selling products"
            ]
        }

    # Kiểm tra Thể thao bên ngoài / Chính trị gia / Showbiz
    if any(re.search(pat, q_low) for pat in SPORTS_POLITICS_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_general",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Câu hỏi của bạn nằm ngoài phạm vi cơ sở dữ liệu nội bộ của doanh nghiệp (thể thao, chính trị xã hội hoặc kiến thức đại chúng)."
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"Your query is outside the scope of internal enterprise databases (external sports, politics, or general web trivia)."
            ),
            "followups": [
                "Doanh số bán hàng phân bổ theo từng quốc gia" if not is_en else "Sales distribution by country",
                "Hiệu suất doanh số của các Team kinh doanh" if not is_en else "Sales performance by business team"
            ]
        }

    # Kiểm tra Thời gian / Đồng hồ / Lịch ngày
    if any(re.search(pat, q_low) for pat in TIME_CLOCK_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_time",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Tôi là Trợ lý Dữ liệu Doanh nghiệp và không cung cấp dịch vụ đồng hồ/lịch thời gian thực. Tôi hỗ trợ phân tích dữ liệu lịch sử các năm theo chuỗi thời gian (Time-series) trong CSDL."
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"I am an Enterprise Data Assistant and do not provide real-time clock or calendar services. I support historical time-series analytics in your database."
            ),
            "followups": [
                "Doanh thu trung bình mỗi tháng trong năm 2022" if not is_en else "Average monthly revenue in 2022",
                "Tổng doanh thu và tổng số hộp bán ra toàn hệ thống" if not is_en else "Total revenue and total boxes sold"
            ]
        }

    # Kiểm tra Kiến thức bách khoa / Dịch thuật / Ẩm thực ăn uống đại chúng
    if any(re.search(pat, q_low) for pat in GENERAL_TRIVIA_PATTERNS):
        return {
            "action": "abstain",
            "category": "out_of_domain_trivia",
            "explanation": (
                f"🛡️ **Thông báo từ Trợ lý Dữ liệu Veraxus (When2Call Gatekeeper):**\n\n"
                f"Câu hỏi của bạn mang tính chất kiến thức tổng quát hoặc trò chuyện thông thường, nằm ngoài phạm vi phân tích số liệu kinh doanh CSDL."
                if not is_en else
                f"🛡️ **Notice from Veraxus AI Assistant (When2Call Gatekeeper):**\n\n"
                f"Your query is general knowledge or casual conversation, outside enterprise database analytics."
            ),
            "followups": [
                "Top 5 sản phẩm có doanh thu cao nhất" if not is_en else "Top 5 products by revenue",
                "Doanh số bán hàng phân bổ theo từng quốc gia" if not is_en else "Sales distribution by country"
            ]
        }

    # -------------------------------------------------------------------------
    # BƯỚC 2: KIỂM TRA CÂU HỎI MƠ HỒ CẦN LÀM RÕ (ASK MISSING INFO)
    # -------------------------------------------------------------------------
    # Trường hợp 2.1: Vague sales comparison ("so sánh doanh số", "so sánh doanh thu") mà không nói rõ so sánh giữa cái gì
    if (
        any(k in q_low for k in ["so sánh doanh số", "so sánh doanh thu", "so sánh bán hàng", "compare sales", "sales comparison"])
        and not any(k in q_low for k in [
            "2020", "2021", "2022", "2023", "2024", "năm", "quý", "tháng", "year", "quarter", "month",
            "sản phẩm", "product", "danh mục", "category", "team", "đội ngũ", "nhân viên", "quốc gia",
            "thị trường", "geo", "country", "india", "usa", "canada", "úc", "uk", "new zealand"
        ])
    ):
        return {
            "action": "ask_missing_info",
            "category": "missing_comparison_target",
            "explanation": (
                f"💡 **Trợ lý Veraxus cần làm rõ chiều so sánh (Proactive Clarification):**\n\n"
                f"Bạn muốn so sánh doanh số theo chiều phân tích nào để tôi trích xuất số liệu chuẩn xác nhất từ CSDL?\n\n"
                f"1. 📅 **Theo thời gian:** So sánh doanh thu giữa các năm hoặc các quý gần nhất.\n"
                f"2. 📦 **Theo danh mục/sản phẩm:** So sánh doanh thu giữa các dòng sản phẩm.\n"
                f"3. 🌍 **Theo thị trường:** So sánh doanh số giữa các quốc gia.\n"
                f"4. 👥 **Theo đội ngũ:** So sánh hiệu suất giữa các Team bán hàng.\n\n"
                f"👉 Bấm chọn một trong các gợi ý bên dưới để xem báo cáo ngay:"
                if not is_en else
                f"💡 **Veraxus needs clarification on comparison dimensions:**\n\n"
                f"Which dimension would you like to compare sales across?\n\n"
                f"1. 📅 **By Time:** Compare revenue across years or quarters.\n"
                f"2. 📦 **By Category/Product:** Compare revenue across product lines.\n"
                f"3. 🌍 **By Geography:** Compare sales across countries.\n"
                f"4. 👥 **By Team:** Compare performance across sales teams.\n\n"
                f"👉 Click one of the suggestions below to analyze immediately:"
            ),
            "followups": [
                "So sánh doanh thu giữa năm 2021 và năm 2022" if not is_en else "Compare revenue between 2021 and 2022",
                "Doanh thu theo từng danh mục sản phẩm (Category)" if not is_en else "Revenue by product category",
                "Doanh số bán hàng phân bổ theo từng quốc gia" if not is_en else "Sales distribution by country",
                "Hiệu suất doanh số của các Team kinh doanh" if not is_en else "Sales performance by business team"
            ]
        }

    # Trường hợp 2.2: Vague top seller ("ai bán tốt nhất", "người bán tốt nhất") mà không có tiêu chí hoặc thời gian
    if (
        any(k in q_low for k in ["ai bán tốt nhất", "ai là người bán xuất sắc nhất", "người bán tốt nhất", "ai bán giỏi nhất", "top seller", "best salesperson"])
        and not any(k in q_low for k in ["2020", "2021", "2022", "2023", "2024", "năm", "tháng", "quý", "hộp", "boxes", "doanh thu", "tiền", "revenue", "amount"])
    ):
        return {
            "action": "ask_missing_info",
            "category": "missing_ranking_criteria",
            "explanation": (
                f"💡 **Trợ lý Veraxus cần làm rõ tiêu chí đánh giá (Proactive Clarification):**\n\n"
                f"Bạn muốn tìm người bán tốt nhất theo thước đo nào?\n\n"
                f"1. 💰 **Theo tổng doanh thu ($):** Nhân sự mang lại giá trị tiền tệ cao nhất.\n"
                f"2. 📦 **Theo số lượng hộp (Boxes):** Nhân sự bán được khối lượng sản phẩm nhiều nhất.\n"
                f"3. 📅 **Theo mốc thời gian:** Năm 2021, 2022 hay toàn bộ lịch sử?\n\n"
                f"👉 Vui lòng chọn một trong các góc nhìn bên dưới:"
                if not is_en else
                f"💡 **Veraxus needs clarification on ranking criteria:**\n\n"
                f"Which metric should define the top seller?\n\n"
                f"1. 💰 **By Total Revenue ($):** Salesperson generating the highest dollar sales.\n"
                f"2. 📦 **By Box Volume:** Salesperson selling the highest box count.\n"
                f"3. 📅 **By Time Period:** 2021, 2022, or all-time?\n\n"
                f"👉 Please select an option below:"
            ),
            "followups": [
                "Top 10 nhân sự bán hàng có doanh thu cao nhất" if not is_en else "Top 10 salespeople by revenue",
                "Top 10 nhân sự bán hàng xuất sắc nhất về số lượng hộp" if not is_en else "Top 10 salespeople by box volume",
                "Top nhân viên bán hàng xuất sắc nhất năm 2022" if not is_en else "Top salesperson in 2022"
            ]
        }

    # Trường hợp 2.3: Vague business report ("báo cáo tình hình kinh doanh", "tình hình kinh doanh gần đây")
    if (
        q_low in ["báo cáo tình hình kinh doanh", "báo cáo tình hình kinh doanh gần đây", "tình hình kinh doanh gần đây", "cho tôi xem tình hình kinh doanh", "recent business performance", "business overview"]
    ):
        return {
            "action": "ask_missing_info",
            "category": "vague_intent",
            "explanation": (
                f"💡 **Trợ lý Veraxus cần định hướng báo cáo (Proactive Clarification):**\n\n"
                f"Bạn muốn xem báo cáo tổng thể sức khỏe vận hành hay tập trung vào khía cạnh cụ thể?\n\n"
                f"1. 📊 **Tổng quan toàn diện:** Tổng doanh thu, số hộp bán và số lượng giao dịch.\n"
                f"2. 📈 **Chuỗi thời gian:** Xu hướng doanh thu theo từng tháng/quý.\n"
                f"3. 🏆 **Xếp hạng:** Top sản phẩm và thị trường dẫn đầu.\n\n"
                f"👉 Vui lòng bấm chọn hướng phân tích bạn mong muốn:"
                if not is_en else
                f"💡 **Veraxus needs orientation on report scope:**\n\n"
                f"Which business aspect would you like to focus on?\n\n"
                f"1. 📊 **Executive Overview:** Total revenue, box volume, and transaction count.\n"
                f"2. 📈 **Time Trend:** Monthly/Quarterly revenue trends.\n"
                f"3. 🏆 **Rankings:** Top products and leading markets.\n\n"
                f"👉 Please select a focus below:"
            ),
            "followups": [
                "Tổng doanh thu và tổng số hộp bán ra toàn hệ thống" if not is_en else "Total revenue and total boxes sold",
                "Doanh thu trung bình mỗi tháng trong năm 2022" if not is_en else "Average monthly revenue in 2022",
                "Top 5 sản phẩm có doanh thu cao nhất năm 2022" if not is_en else "Top 5 products by revenue in 2022"
            ]
        }

    # Trường hợp 2.4: Vague declining products ("sản phẩm nào đang bị giảm sút", "sản phẩm nào giảm sút")
    if (
        any(k in q_low for k in ["sản phẩm nào đang bị giảm sút", "sản phẩm nào giảm sút", "sản phẩm bị sụt giảm", "which products are declining"])
        and not any(k in q_low for k in ["2020", "2021", "2022", "2023", "quý", "năm", "tháng", "so với"])
    ):
        return {
            "action": "ask_missing_info",
            "category": "missing_time_window",
            "explanation": (
                f"💡 **Trợ lý Veraxus cần mốc thời gian đối chiếu (Proactive Clarification):**\n\n"
                f"Để tính toán tốc độ sụt giảm sản phẩm, bạn muốn so sánh giữa chu kỳ thời gian nào?\n\n"
                f"1. 📉 **Theo mốc năm:** So sánh doanh thu năm 2022 so với 2021.\n"
                f"2. 📊 **Theo sản phẩm doanh thu thấp nhất:** Xem các sản phẩm có đóng góp doanh số thấp nhất."
                if not is_en else
                f"💡 **Veraxus needs a baseline comparison timeframe:**\n\n"
                f"To determine declining product trends, which timeframe should be compared?\n\n"
                f"1. 📉 **By Year:** Compare 2022 revenue vs 2021.\n"
                f"2. 📊 **By Lowest Revenue:** View products with lowest sales volume."
            ),
            "followups": [
                "Top 5 sản phẩm có doanh thu thấp nhất năm 2022" if not is_en else "Top 5 products with lowest revenue in 2022",
                "Doanh thu theo từng danh mục sản phẩm (Category)" if not is_en else "Revenue by product category"
            ]
        }

    # -------------------------------------------------------------------------
    # BƯỚC 3: CÂU HỎI HỢP LỆ -> CHO PHÉP GỌI TOOL SQL (TOOL SQL)
    # -------------------------------------------------------------------------
    return {
        "action": "tool_sql",
        "category": "valid_business_query",
        "explanation": None,
        "followups": []
    }
