"""
Dashboard Copilot Sub-Agent (Tác tử Trợ lý Đồng hành Trực tiếp trên Dashboard).
Chịu trách nhiệm: Lắng nghe và giải đáp tức thì mọi thắc mắc của người dùng về các điểm số liệu,
biểu đồ xu hướng, chỉ số KPI và dị biệt trên Bảng điều khiển CRM Dashboard.
"""

from __future__ import annotations

import re
import json
from typing import Any, Dict, List, Optional
from .base_agent import BaseAgent
from .agent_state import AgentState
from src.llm.client import invoke_llm


def distill_executive_recommendation(raw_text: str, default_rec: str = "") -> str:
    """Tinh lọc nội dung khuyến nghị điều hành thành DUY NHẤT 1-2 câu quyết sách sắc bén, loại bỏ 100% hallucination, danh sách đánh số và lời thoại giả định."""
    if not raw_text:
        return default_rec or "Quyết liệt chỉ đạo rà soát định biên, tối ưu hóa phân bổ nguồn lực và thiết lập mốc kiểm soát tiến độ định kỳ hàng tuần để đảm bảo hiệu suất vận hành."
    
    text = raw_text.strip()
    
    # 1. Cắt bỏ triệt để mọi đoạn sinh tiếp lời thoại giả định của Người dùng / Khách hàng / Copilot
    dialogue_patterns = [
        r'(?:\s*[-—–_*=~#\.]*)*\s*(?:Người\s*dùng|Khách\s*hàng|User|Human|Lãnh\s*Đạo|Lãnh\s*đạo|Ban\s*Điều\s*Hành|Veraxus\s*Copilot|Copilot|AI\s*Copilot|Assistant|Client|Customer)\s*[:—\-].*$',
        r'(?:\s*[-—–_*=~#\.]*)*\s*(?:Mời\s*ai\s*phân\s*tích|Bạn\s*đã\s*cung\s*cấp|Bây\s*giờ,\s*tôi\s*muốn\s*hiểu|Hỏi\s*tiếp|Câu\s*hỏi\s*tiếp).*$',
    ]
    for dp in dialogue_patterns:
        text = re.sub(dp, '', text, flags=re.IGNORECASE | re.DOTALL).strip()

    # 2. Xóa các ký tự phân cách markdown và gạch ngang ở cuối/giữa
    text = re.sub(r'\s*[-—–_*=~#]{2,}\.?\s*$', '', text).strip()
    text = re.sub(r'\s+[-—–_*=~#]{2,}\s+', ' ', text).strip()
    text = re.sub(r'[\s\-—–_*]+$', '', text).strip()
    text = re.sub(r'\[.*?\]', '', text).strip()

    # 3. Loại bỏ lời mào đầu rườm rà
    preambles = [
        r'^(?:Cần\s+thực\s+hiện\s+(?:một\s+số\s+)?(?:bước\s+chính|các\s+bước|hành\s+động|khuyến\s+nghị|giải\s+pháp)|Dưới\s+đây\s+là|Sau\s+đây\s+là|Tôi\s+khuyến\s+nghị\s+rằng|Tôi\s+khuyến\s+nghị|Khuyến\s+nghị\s+rằng|Chúng\s+tôi\s+khuyến\s+nghị|Để\s+(?:khắc\s+phục|tối\s+ưu|giải\s+quyết|đảm\s+bảo)[^\:\,\.\n]+[\:\,\.]?)\s*[:—\-\.]*\s*',
        r'^(?:Các\s+hành\s+động\s+cần\s+làm|Quyết\s+sách\s+đề\s+xuất|Đề\s+xuất\s+hành\s+động)\s*[:—\-\.]*\s*'
    ]
    for p in preambles:
        text = re.sub(p, '', text, flags=re.IGNORECASE).strip()

    # 4. Xử lý trường hợp LLM sinh dạng danh sách đánh số 1. ... 2. ... 3. ...
    if re.search(r'\b1\.\s+', text):
        items = re.findall(r'(?:\d+\.|\*|\-)\s*(?:\*\*)?([^:\n\.\?]+)(?:\*\*)?(?:\s*:\s*|\s*—\s*|\.\s*)([^\n\d]+)?', text)
        if items:
            key_actions = []
            for item in items:
                act_title = item[0].strip()
                act_title = re.sub(r'^\d+[\.\)]\s*', '', act_title).strip()
                act_title = re.sub(r'[\*\#]', '', act_title).strip()
                if len(act_title) >= 5 and not any(k in act_title.lower() for k in ["bước", "giai đoạn", "hành động"]):
                    if act_title:
                        act_title = act_title[0].lower() + act_title[1:]
                    key_actions.append(act_title)
            
            if len(key_actions) >= 2:
                if len(key_actions) == 2:
                    text = f"Quyết liệt chỉ đạo {key_actions[0]} và {key_actions[1]} nhằm nhanh chóng tối ưu hóa hiệu suất và ổn định bộ máy."
                else:
                    text = f"Quyết liệt chỉ đạo {key_actions[0]}, {key_actions[1]} và {key_actions[2]} nhằm nhanh chóng tối ưu hóa hiệu suất và đảm bảo vận hành bền vững."
            elif len(key_actions) == 1:
                text = f"Quyết liệt chỉ đạo {key_actions[0]} để nhanh chóng tối ưu hóa hiệu suất vận hành."

    # 5. Dọn dẹp khoảng trắng, dấu ngoặc kép, dấu chấm
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[\s\.\,\;:\-—–_*\s]+$', '', text).strip()

    # 6. Giới hạn tối đa 1-2 câu mạch lạc, không vượt quá 220 ký tự
    sentences = [s.strip() for s in re.split(r'(?<=[\.\!\?])\s+', text) if s.strip()]
    if len(sentences) > 2:
        text = " ".join(sentences[:2])
    
    # 7. Fallback an toàn nếu sau khi dọn dẹp nội dung bị rỗng hoặc quá ngắn
    if not text or len(text) < 15:
        text = default_rec or "Quyết liệt chỉ đạo rà soát định biên, tối ưu hóa phân bổ nguồn lực và thiết lập mốc kiểm soát tiến độ định kỳ hàng tuần để đảm bảo hiệu suất vận hành."

    # Viết hoa chữ cái đầu và đảm bảo kết thúc bằng dấu chấm
    text = text[0].upper() + text[1:]
    if not text.endswith(('.', '!', '?')):
        text += '.'
        
    return text


def sanitize_executive_vietnamese_text(text: str, default_header: str = "", default_rec: str = "") -> str:
    """Làm sạch triệt để toàn bộ lỗi font, lỗi gõ Telex tokenization (HPANH -> HÀNH), ký tự chữ Hán, và đảm bảo tiêu đề đầy đủ, khử sạch 100% khuyến nghị trùng lặp."""
    if not text:
        return text
    
    clean_text = text.strip()

    # 1. Khắc phục triệt để các lỗi gõ Telex / tokenization glitch / dịch máy của LLM
    typo_map = {
        r'\bVẬN HPANH\b': 'VẬN HÀNH',
        r'\bvận hpanh\b': 'vận hành',
        r'\bVận hpanh\b': 'Vận hành',
        r'\bHPANH\b': 'HÀNH',
        r'\bhpanh\b': 'hành',
        r'\bHPanh\b': 'Hành',
        r'\bchậm lagg\b': 'chậm trễ',
        r'\blagg\b': 'trì trệ',
        r'\bnghi hưu\b': 'nghỉ hưu',
        r'\btrung trọng\b': 'quan trọng',
        r'\bbóc lấp\b': 'bộc lộ',
        r'\bnhân力\b': 'nhân lực',
        r'\bđầy đủg\b': 'đầy đủ',
        r'Tổng Chấn thương Lãnh đạo': 'Áp lực Quản trị Cấp cao',
        r'Chấn thương Lãnh đạo': 'Áp lực Quản trị',
        r'chấn thương lãnh đạo': 'áp lực quản trị',
        r'Hạn chế Tuyệt Khả': 'Định biên Nhân sự Cốt lõi',
        r'Tuyệt Khả': 'Khả thi',
        r'Tự do Giải quyết Lỗi': 'Tỷ lệ Tự động Xử lý Sự cố',
        r'Thời gian Đóng lỗi': 'Thời gian Xử lý Sự cố',
        r'mức độ NGAY\b': 'mức độ KHẨN CẤP',
        r'mức độ ngay\b': 'mức độ khẩn cấp',
        r'\bHàm chì\b': 'Hành động then chốt',
        r'\bhàm chì\b': 'hành động then chốt',
        r'\bnganh trừng\b': 'áp lực điểm nghẽn',
        r'\bNganh trừng\b': 'Áp lực điểm nghẽn',
        r'\bngành trừng\b': 'áp lực điểm nghẽn',
        r'\bbáo cáo cáo trạng\b': 'báo cáo hiện trạng',
        r'\bcáo trạng\b': 'hiện trạng',
        r'\bthiêm nghiệm\b': 'nghiệm thu',
        r'\bThiêm nghiệm\b': 'Nghiệm thu',
        r'\bcông suất người lao động\b': 'năng suất lao động',
        r'\bHàm chuyển đổi\b': 'Kế hoạch chuyển giao',
        r'\bHàm xác nhận\b': 'Kế hoạch nghiệm thu',
        r'\bKhởi nguồn lực\b': 'Huy động nguồn lực',
        r'\bLần 1\s*\(': 'Giai đoạn 1 (',
        r'\bLần 2\s*\(': 'Giai đoạn 2 (',
        r'\bLần 3\s*\(': 'Giai đoạn 3 (',
        r'\bLần 1\b': 'Giai đoạn 1',
        r'\bLần 2\b': 'Giai đoạn 2',
        r'\bLần 3\b': 'Giai đoạn 3',
    }
    for pattern, repl in typo_map.items():
        clean_text = re.sub(pattern, repl, clean_text)

    # 2. Xóa sạch các ký tự chữ Hán / CJK
    cjk_dict = {
        "力": "lực",
        "有 projector": "có",
        "有足够的": "đầy đủ",
        "足够": "đầy đủ",
        "凹I": "",
        "凹": "",
    }
    for c_k, c_v in cjk_dict.items():
        clean_text = clean_text.replace(c_k, c_v)
    clean_text = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', '', clean_text)

    # 3. Loại bỏ triệt để các ký tự ngoặc vuông [ ] thừa
    clean_text = re.sub(r'\[([^\]\n\r]+)\]', r'\1', clean_text)
    clean_text = clean_text.replace("[", "").replace("]", "")

    # 4. Xóa các thẻ HTML đóng/mở thừa
    clean_text = re.sub(r'</?(?:div|span|p)[^>]*>', '', clean_text, flags=re.IGNORECASE).strip()

    # 4.0.0. Xóa lời chào/tiêu đề vai trò ở ngay đầu phản hồi (không cắt cụt phần thân văn bản)
    clean_text = re.sub(r'^\s*(?:(?:Kính\s*gửi|Thưa)\s*)?(?:Người\s*dùng|Khách\s*hàng|User|Lãnh\s*Đạo|Ban\s*Điều\s*Hành|Human|AI\s*Copilot|Veraxus\s*Copilot|Copilot)\s*:\s*', '', clean_text, flags=re.IGNORECASE)

    # 4.0.1. Cắt bỏ triệt để nếu LLM tự sinh tiếp lượt hỏi giả định của Người dùng / Lãnh đạo / Khách hàng / Copilot
    dialogue_split = re.search(r'(?:(?:\n\s*[-—–_*=~#]{2,}\s*)*|\n+)\s*(?:Người\s*dùng|Khách\s*hàng|User|Human|Lãnh\s*Đạo|Lãnh\s*đạo|Ban\s*Điều\s*Hành|Veraxus\s*Copilot|Copilot|AI\s*Copilot|Assistant|Client|Customer)\s*[:—\-].*$', clean_text, flags=re.IGNORECASE | re.DOTALL)
    if dialogue_split:
        clean_text = clean_text[:dialogue_split.start()].strip()

    # 4.0.2. Xóa các dòng hướng dẫn prompt bị rò rỉ vào kết quả (Prompt Leakage Cleanup)
    clean_text = re.sub(r'(?:\n|^)\s*(?:Tạo\s+bảng\s+Markdown|BẮT\s+BUỘC\s+VẼ\s+BẢNG|BẮT\s+BUỘC\s+TRẢ\s+LỜI|HƯỚNG\s+DẪN\s+CẤU\s+TRÚC)[^\n]*', '', clean_text, flags=re.IGNORECASE)

    # 4.0.3. Xóa các đoạn hội thoại giả lập hoặc rò rỉ prompt (Lịch sử trao đổi trước đó / Truncate...)
    clean_text = re.sub(r'(?:\n|^)\s*Lịch\s*sử\s*trao\s*đổi\s*trước\s*đó:?[^\n]*(?:\n+[\*\-•\s>]+[^\n]+)*', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(?:Ghi\s*chú:\s*)?Truncate:?\s*', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bTruncate\b', '', clean_text, flags=re.IGNORECASE)

    # 4.0.4. Khắc phục triệt để lỗi placeholder vô nghĩa như 00, MM, (Một mốc kiểm soát tùy chỉnh), Mốc kiểm soát 00/MM
    clean_text = re.sub(r'\(Một\s*mốc\s*kiểm\s*soát\s*tùy\s*chỉnh\)', '', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bMốc\s*(?:kiểm\s*soát|KIỂM\s*SOÁT)?\s*00\b', 'Giai đoạn 1 (0 — 30 ngày)', clean_text)
    clean_text = re.sub(r'\bMốc\s*(?:kiểm\s*soát|KIỂM\s*SOÁT)?\s*MM\b', 'Giai đoạn 2 (30 — 60 ngày)', clean_text)
    clean_text = re.sub(r'\bMốc\s*(?:kiểm\s*soát|KIỂM\s*SOÁT)?\s*XX\b', 'Giai đoạn 3 (60 — 90 ngày)', clean_text)
    clean_text = re.sub(r'\bMốc\s*(?:kiểm\s*soát|KIỂM\s*SOÁT)?\s*YY\b', 'Giai đoạn 4 (Dài hạn)', clean_text)
    clean_text = re.sub(r'\bMốc\s*00\b', 'Mốc 30 ngày (Khẩn cấp)', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bMốc\s*MM\b', 'Mốc 60 ngày (Chuẩn hóa)', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bMốc\s*XX\b', 'Mốc 90 ngày (Tối ưu)', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bGiai\s*đoạn\s*00\b', 'Giai đoạn 1 (0 — 30 ngày)', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bGiai\s*đoạn\s*MM\b', 'Giai đoạn 2 (1 — 3 tháng)', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\bGiai\s*đoạn\s*XX\b', 'Giai đoạn 3 (3 — 6 tháng)', clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\b(KIỂM\s*SOÁT|kiểm\s*soát)\s+00\b', r'\1 30 Ngày', clean_text)
    clean_text = re.sub(r'\b(KIỂM\s*SOÁT|kiểm\s*soát)\s+MM\b', r'\1 60 Ngày', clean_text)
    clean_text = re.sub(r'[ \t]+:', ':', clean_text)

    # 4.1. Khắc phục lỗi ký tự blockquote '>' bị gắn nhầm vào tiêu đề và bảng biểu (Làm vỡ font & UI)
    fixed_lines = []
    for line in clean_text.splitlines():
        line_s = line.strip()
        if not line_s:
            fixed_lines.append("")
            continue

        # Giữ nguyên blockquote khuyến nghị hợp lệ ở cuối
        if line_s.startswith(">") and "💡" in line_s and "Khuyến nghị Trọng tâm" in line_s:
            fixed_lines.append(line_s)
            continue
        
        # Xóa dấu '>' đi lạc ở đầu các dòng tiêu đề hoặc nội dung thường
        if line_s.startswith(">"):
            line_s = re.sub(r"^>\s*", "", line_s)
            if re.match(r"^[^\w\s]*\s*\d+\.", line_s) and not line_s.startswith("#"):
                line_s = f"### {line_s}"

        # Tách tiêu đề Khối 3 bị dính liền với header bảng trên cùng một dòng
        if ("###" in line_s or re.match(r"^[^\w\s]*\s*\d+\.", line_s)) and "|" in line_s:
            pipe_idx = line_s.find("|")
            title_part = line_s[:pipe_idx].strip()
            table_part = line_s[pipe_idx:].strip()
            if not title_part.startswith("#"):
                title_part = f"### {title_part}"
            fixed_lines.append(title_part)
            fixed_lines.append("")
            table_part = re.sub(r"\|\s*\|", "|\n|", table_part)
            for t_line in table_part.splitlines():
                if t_line.strip():
                    fixed_lines.append(t_line.strip())
            continue

        # Tách các dòng bảng bị dính liền trên 1 dòng do || hoặc | |
        if "|" in line_s and ("||" in line_s or re.search(r"\|\s*\|", line_s)):
            table_part = re.sub(r"\|\s*\|", "|\n|", line_s)
            for t_line in table_part.splitlines():
                if t_line.strip():
                    fixed_lines.append(t_line.strip())
            continue

        fixed_lines.append(line_s)
    clean_text = "\n".join(fixed_lines).strip()

    # 4.2. Khắc phục & Tự động tạo bảng Markdown chuẩn xác (Đảm bảo có Header Separator `| :--- | :--- |`)
    lines = clean_text.splitlines()
    reconstructed_lines = []
    idx = 0
    while idx < len(lines):
        cur_line = lines[idx]
        cur_s = cur_line.strip()
        
        # Nhận diện khối Table bắt đầu và kết thúc bằng `|`
        if cur_s.startswith("|") and cur_s.endswith("|") and cur_s.count("|") >= 3:
            tbl_block = [cur_s]
            idx += 1
            while idx < len(lines) and lines[idx].strip().startswith("|") and lines[idx].strip().endswith("|"):
                tbl_block.append(lines[idx].strip())
                idx += 1
            
            # Kiểm tra xem dòng thứ 2 đã có separator (| --- | --- |) chưa
            if len(tbl_block) >= 1:
                has_separator = False
                if len(tbl_block) >= 2 and re.search(r'\|\s*:?-{2,}:?\s*\|', tbl_block[1]):
                    has_separator = True
                
                if not has_separator:
                    # Tự động tính số cột từ dòng tiêu đề và chèn dòng phân cách chuẩn
                    col_count = max(1, tbl_block[0].count("|") - 1)
                    sep_line = "| " + " | ".join([":---"] * col_count) + " |"
                    tbl_block.insert(1, sep_line)
            
            # Đảm bảo có dòng trống trước và sau table để Streamlit render hoàn hảo
            if reconstructed_lines and reconstructed_lines[-1] != "":
                reconstructed_lines.append("")
            reconstructed_lines.extend(tbl_block)
            reconstructed_lines.append("")
            continue
        else:
            reconstructed_lines.append(cur_line)
            idx += 1
    clean_text = "\n".join(reconstructed_lines).strip()

    # 5. Xử lý & Chuẩn hóa Thẻ Khuyến nghị Trọng tâm cho Ban Điều Hành (VIP Gold Card)
    rec_content = ""
    rec_start_pos = -1

    # Pattern A: Khối blockquote > 💡 ... (hỗ trợ mọi biến thể khuyến nghị / quyết sách của LLM)
    p_blockquote = re.search(r'(?:\n|^)\s*>\s*(?:💡\s*)?(?:\*\*)?(?:Khuyến\s*nghị(?:\s*Trọng\s*tâm)?(?:\s*cho)?(?:\s*Ban\s*Điều\s*Hành|\s*Ban\s*Giám\s*Đốc|\s*Lãnh\s*Đạo|\s*Điều\s*Hành|\s*Doanh\s*Nghiệp)?|Quyết\s*sách(?:\s*Trọng\s*tâm)?(?:\s*Điều\s*Hành)?|Đề\s*xuất(?:\s*cho)?(?:\s*Ban\s*Điều\s*Hành|\s*Ban\s*Giám\s*Đốc)?|Tóm\s*lại|Kết\s*luận(?:\s*&\s*Khuyến\s*nghị)?)\s*[:—\-\.]*\s*(?:\*\*)?\s*(.*)$', clean_text, flags=re.IGNORECASE | re.DOTALL)
    if p_blockquote:
        rec_start_pos = p_blockquote.start()
        raw_rec = p_blockquote.group(1).strip()
        lines_rec = []
        for r_line in raw_rec.splitlines():
            r_s = re.sub(r'^>\s*', '', r_line.strip()).strip()
            # Bỏ qua các dòng phân cách markdown (---, ***, ___, ===, ---., vv.)
            if re.match(r'^(?:[-—–_*\s=~#]{2,}|\.\.\.)\.?$', r_s):
                continue
            # Dừng lại nếu gặp lượt hỏi giả lập của Người dùng hoặc lặp lại tiêu đề
            if re.search(r'(?:Người\s*dùng|Khách\s*hàng|User|Human|Lãnh\s*Đạo|Lãnh\s*đạo|Ban\s*Điều\s*Hành|Veraxus\s*Copilot|Copilot|###\s*[^\n]*1\.)\s*[:—\-]', r_s, flags=re.IGNORECASE):
                r_s_clean = re.sub(r'(?:Người\s*dùng|Khách\s*hàng|User|Human|Lãnh\s*Đạo|Lãnh\s*đạo|Ban\s*Điều\s*Hành|Veraxus\s*Copilot|Copilot)\s*[:—\-].*$', '', r_s, flags=re.IGNORECASE).strip()
                if r_s_clean:
                    lines_rec.append(r_s_clean)
                break
            if r_s:
                lines_rec.append(r_s)
        rec_content = " ".join(lines_rec)

    # Pattern B: Plain-text hoặc Header ### Khuyến nghị Trọng tâm...
    if not rec_content and rec_start_pos == -1:
        p_plain = re.search(r'(?:\n|^)\s*(?:###|\*\*|\*)?\s*(?:💡\s*)?(?:Duy nhất,\s*)?(?:tôi\s+)?(?:khuyến\s*nghị(?:\s*trọng\s*tâm)?(?:\s*cho)?(?:\s*Ban\s*Điều\s*Hành|\s*Ban\s*Giám\s*Đốc|\s*Lãnh\s*Đạo|\s*Điều\s*Hành|\s*Doanh\s*Nghiệp)?|quyết\s*sách(?:\s*trọng\s*tâm)?(?:\s*điều\s*hành)?|đề\s*xuất(?:\s*cho)?(?:\s*Ban\s*Điều\s*Hành|\s*Ban\s*Giám\s*Đốc)?)\s*[:—\-\.]*\s*(?:\*\*|\*)?\s*(.*)$', clean_text, flags=re.IGNORECASE | re.DOTALL)
        if p_plain:
            rec_start_pos = p_plain.start()
            raw_rec = p_plain.group(1).strip()
            lines_rec = []
            for r_line in raw_rec.splitlines():
                r_s = re.sub(r'^>\s*', '', r_line.strip()).strip()
                # Bỏ qua các dòng phân cách markdown
                if re.match(r'^(?:[-—–_*\s=~#]{2,}|\.\.\.)\.?$', r_s):
                    continue
                if re.search(r'(?:Người\s*dùng|Khách\s*hàng|User|Human|Lãnh\s*Đạo|Lãnh\s*đạo|Ban\s*Điều\s*Hành|Veraxus\s*Copilot|Copilot|###\s*[^\n]*1\.)\s*[:—\-]', r_s, flags=re.IGNORECASE):
                    r_s_clean = re.sub(r'(?:Người\s*dùng|Khách\s*hàng|User|Human|Lãnh\s*Đạo|Lãnh\s*đạo|Ban\s*Điều\s*Hành|Veraxus\s*Copilot|Copilot)\s*[:—\-].*$', '', r_s, flags=re.IGNORECASE).strip()
                    if r_s_clean:
                        lines_rec.append(r_s_clean)
                    break
                if r_s:
                    lines_rec.append(r_s)
            rec_content = " ".join(lines_rec)

    # Cắt bỏ phần khuyến nghị cũ ra khỏi clean_text để tái cấu trúc lại chuẩn xác tuyệt đối
    if rec_start_pos != -1:
        clean_text = clean_text[:rec_start_pos].strip()

    # Dọn dẹp triệt để các đường kẻ ngang markdown hoặc dấu gạch thừa cuối clean_text
    clean_text = re.sub(r'(?:\n\s*[-—–_*=~#]{2,}\s*)+\s*$', '', clean_text).strip()
    clean_text = re.sub(r'\n\s*[-—–_*=~#]{3,}\s*\n', '\n\n', clean_text).strip()

    # Tinh lọc nội dung khuyến nghị điều hành thành 1 quyết sách sắc bén, sạch sẽ 100%
    rec_content = distill_executive_recommendation(rec_content, default_rec=default_rec)

    # 5.1. Loại bỏ triệt để mọi Prompt Leakage và đoạn lặp lại thừa trước và sau Khối 3
    # 5.1.1. Cắt bỏ nếu có tiêu đề bắt đầu bằng Khối 1 sau khi đã kết thúc Khối 3
    h3_match = re.search(r'(?:\n|^)\s*###\s*[^\n]*3\.', clean_text)
    if h3_match:
        dup_h1 = re.search(r'(?:\n|^)\s*###\s*[^\n]*1\.', clean_text[h3_match.end():])
        if dup_h1:
            clean_text = clean_text[:h3_match.end() + dup_h1.start()].strip()

    # 5.1.2. Nếu Khối 3 chứa Bảng Markdown, cắt bỏ toàn bộ văn bản rác / danh sách gạch đầu dòng lặp lại sau dòng cuối cùng của bảng
    h3_search = re.search(r'(?:\n|^)\s*###\s*[^\n]*3\.', clean_text)
    if h3_search:
        h3_start_idx = h3_search.start()
        lines_all = clean_text.splitlines()
        
        # Tìm các dòng thuộc bảng trong Khối 3
        h3_line_idx = -1
        last_table_line_idx = -1
        char_count = 0
        for l_idx, l_txt in enumerate(lines_all):
            if char_count >= h3_start_idx and h3_line_idx == -1:
                h3_line_idx = l_idx
            if h3_line_idx != -1 and l_txt.strip().startswith("|") and l_txt.strip().endswith("|"):
                last_table_line_idx = l_idx
            char_count += len(l_txt) + 1

        if last_table_line_idx != -1 and last_table_line_idx < len(lines_all) - 1:
            # Kiểm tra xem các dòng phía sau bảng có phải là prompt leakage / câu hỏi lặp / gạch đầu dòng trùng lặp không
            trailing_text = "\n".join(lines_all[last_table_line_idx + 1:]).strip()
            if any(k in trailing_text.lower() for k in ["câu hỏi", "lãnh đạo", "yêu cầu phân tích", "0 - 30", "0 — 30", "tuần 1", "mốc 30", "khuyến nghị"]):
                # Cắt sạch phần thừa sau bảng
                clean_text = "\n".join(lines_all[:last_table_line_idx + 1]).strip()

    # 5.1.3. Xóa mọi dòng rò rỉ prompt leakage còn sót lại
    clean_text = re.sub(r'(?:\n|^)\s*(?:CÂU\s*HỎI\s*(?:CỦA\s*LÃNH\s*ĐẠO|CẦN\s*PHÂN\s*TÍCH|VỀ\s*DASHBOARD)|YÊU\s*CẦU\s*PHÂN\s*TÍCH|Yêu\s*cầu\s*phân\s*tích|Câu\s*hỏi\s*cần\s*phân\s*tích)[^\n]*(?:\n+["\'].*?["\'])?', '', clean_text, flags=re.IGNORECASE)

    # 5.1.4. Cắt bỏ mọi văn bản rác trước Khối 1 để đảm bảo câu trả lời luôn bắt đầu trực diện bằng Khối 1
    h1_match = re.search(r'(?:\n|^)\s*(###\s*[^\n]*1\..*)$', clean_text, flags=re.DOTALL)
    if h1_match:
        clean_text = h1_match.group(1).strip()

    # 5.2. Đính kèm thẻ VIP Gold Card duy nhất ở cuối cùng của phản hồi
    clean_text = f"{clean_text}\n\n> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** {rec_content}"

    # 6. Đảm bảo tiêu đề khối 1 luôn hiện diện đầy đủ
    if not re.search(r'^\s*###\s*[^\n]*1\.', clean_text):
        if default_header:
            clean_text = f"{default_header}\n\n{clean_text}"
        else:
            clean_text = f"### 📊 1. TỔNG QUAN & ĐỘNG LỰC CỐT LÕI (Executive Summary)\n\n{clean_text}"

    # Dọn dẹp dòng trống thừa
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)
    return clean_text.strip()


class DashboardCopilotAgent(BaseAgent):
    """Dashboard Copilot Agent chuyên giải đáp trực tiếp theo ngữ cảnh thực tế của Dashboard."""

    def __init__(self):
        super().__init__(
            name="DashboardCopilotAgent",
            role="Trợ lý Đồng hành & Cố vấn Trực tiếp trên Dashboard",
            description="Tác tử phụ context-aware giải đáp chuyên sâu về biểu đồ, KPI và dị biệt đang hiển thị."
        )

    def run(self, state: AgentState) -> AgentState:
        """Thực thi tác vụ của Copilot thông qua AgentState chung."""
        self.log(state, f"Copilot tiếp nhận câu hỏi: '{state.user_query}'")
        return state

    def generate_smart_chips(self, ctx: Dict[str, Any], lang: str = "vi") -> List[str]:
        """Tự động sinh ra 3-4 câu hỏi đào sâu thông minh 1-click dựa trên dị biệt sống của Dashboard."""
        is_en = (lang == "en")
        chips = []
        anomalies = ctx.get("anomalies", [])
        layer_name = ctx.get("layer_title", "Tổng quan doanh nghiệp")
        time_label = ctx.get("time_label", "1985 - 2002")

        if anomalies:
            for a in anomalies[:3]:
                title = a.get("title", "")
                if title:
                    if is_en:
                        chips.append(f"Why is there {title.lower()} in {time_label}?")
                    else:
                        chips.append(f"💡 Vì sao xuất hiện '{title}' trong giai đoạn {time_label}?")

        if not chips:
            if is_en:
                chips = [
                    f"Explain the primary business drivers in {layer_name} for {time_label}.",
                    f"What actionable steps should leadership take regarding {time_label} metrics?",
                    f"Which department requires immediate resource reallocation?"
                ]
            else:
                chips = [
                    f"💡 Giải thích các động lực chính của {layer_name} trong kỳ {time_label}.",
                    f"💡 Ban điều hành cần ưu tiên hành động gì đối với các chỉ số hiện tại?",
                    f"💡 Đánh giá nguy cơ và giải pháp phân bổ nguồn lực tối ưu nhất."
                ]

        return chips[:4]

    def ask_copilot(
        self,
        question: str,
        ctx: Dict[str, Any],
        chat_history: Optional[List[Dict[str, str]]] = None,
        lang: str = "vi"
    ) -> str:
        """Trả lời câu hỏi của người dùng dựa trên 100% ngữ cảnh sống của Dashboard."""
        is_en = (lang == "en")
        
        # 1. Trích xuất ngữ cảnh Dashboard
        layer_title = ctx.get("layer_title", "Tổng quan Doanh nghiệp")
        time_label = ctx.get("time_label", "1985 - 2002")
        kpis_str = ctx.get("kpis_summary", "Không có tóm tắt KPI.")
        anomalies = ctx.get("anomalies", [])
        data_summary = ctx.get("data_summary", "")

        anomalies_text = ""
        if anomalies:
            for i, a in enumerate(anomalies, 1):
                anomalies_text += (
                    f"\n  - Dị biệt {i}: {a.get('title', '')} (Mức độ: {a.get('severity', 'WARNING')})"
                    f"\n    + Thực trạng: {a.get('metrics_summary', '')}"
                    f"\n    + Nguyên nhân gốc rễ: {a.get('root_cause', '')}"
                    f"\n    + Lượng hóa tác động: {a.get('quantified_impact', '')}"
                )
        else:
            anomalies_text = "Toàn bộ chỉ số vận hành duy trì trạng thái ổn định và cân bằng."

        # 2. Xây dựng lịch sử hội thoại nếu có (Chỉ truyền danh sách câu hỏi trước để LLM nắm ngữ cảnh)
        history_text = ""
        if chat_history:
            user_questions = [turn.get("content", "").strip() for turn in chat_history if turn.get("role") == "user" and turn.get("content", "").strip()]
            if user_questions:
                history_text = "Ngữ cảnh câu hỏi trước: " + " | ".join(user_questions[-2:])

        # 3. Phân loại ý định câu hỏi chính xác tuyệt đối
        q_lower = question.lower()
        
        # Nhóm 0A: Lộ trình & Hành động Khẩn cấp trong 30 ngày tới (30-Day Emergency Action & Priorities)
        # Bắt buộc ưu tiên cao nhất khi câu hỏi đề cập đến "30 ngày", "30 ngày tới", "ngay trong 30 ngày", "trong 30 ngày", "1 tháng tới", "tháng đầu", v.v.
        is_30day_emergency = (
            any(k in q_lower for k in [
                "30 ngày", "30 ngày tới", "trong 30", "ngay trong 30", "30-day", "30 day", 
                "1 tháng tới", "trong tháng tới", "tháng đầu", "khẩn cấp trong 30", "ưu tiên trong 30",
                "hành động trong 30", "làm gì trong 30", "30 ngày đầu"
            ]) and not any(k in q_lower for k in ["30-60-90", "60 ngày", "90 ngày", "mốc 60", "mốc 90"])
            and not any(k in q_lower for k in ["vì sao", "tại sao", "nguyên nhân", "lý do", "why"])
        )

        # Nhóm 0B: Chẩn đoán Nguyên nhân Gốc rễ & Cơ chế Dị biệt / Lệch pha (Top Priority khi hỏi "Vì sao", "Tại sao", "Nguyên nhân", "Lệch pha", "Bất thường", "Dị biệt", "Giải thích", v.v.)
        is_anomaly_root_cause = not is_30day_emergency and any(k in q_lower for k in [
            "vì sao", "tại sao", "nguyên nhân", "lý do", "giải thích", "động lực", "why", 
            "lệch pha", "dị biệt", "bất thường", "xuất hiện", "phát sinh", "điểm gãy"
        ])

        # Nhóm 0C: Hành động Ưu tiên cho Ban Điều Hành chung (Khi hỏi Ban điều hành cần làm gì / ưu tiên hành động gì chung theo lộ trình tổng thể)
        is_executive_actions = not is_30day_emergency and not is_anomaly_root_cause and any(k in q_lower for k in [
            "ưu tiên hành động", "hành động gì", "cần ưu tiên", "hành động ưu tiên", 
            "ưu tiên làm gì", "ưu tiên giải pháp", "cần làm gì", "hành động nào", "ưu tiên gì"
        ])

        # Nhóm 0D: Lượng hóa Tiết kiệm chi phí & Tối ưu ROI
        is_cost_roi = not is_30day_emergency and not is_anomaly_root_cause and not is_executive_actions and any(k in q_lower for k in [
            "tiết kiệm chi phí", "roi", "tối ưu roi", "hoàn vốn", "tối ưu chi phí", "lợi ích kinh tế", "cost saving", "return on investment", "hiệu quả chi phí"
        ])

        # Nhóm 1: Bộ chỉ số KPI theo các mốc 30 - 60 - 90 ngày
        is_milestone_kpi = not is_30day_emergency and not is_anomaly_root_cause and not is_executive_actions and not is_cost_roi and any(k in q_lower for k in [
            "30-60-90", "30 ngày", "60 ngày", "90 ngày", "mốc 30", "mốc 60", "mốc 90", "kiểm tra định kỳ"
        ]) and any(k in q_lower for k in ["kpi", "okr", "chỉ số", "đo lường", "mốc"])

        # Nhóm 2: Kiểm soát Rủi ro, Kế hoạch Dự phòng & Tác động tài chính
        is_risk_contingency = not is_30day_emergency and not is_anomaly_root_cause and not is_executive_actions and not is_cost_roi and not is_milestone_kpi and any(k in q_lower for k in [
            "kiểm soát rủi ro", "dự phòng", "phương án dự phòng", "kế hoạch dự phòng", 
            "rủi ro", "tác động", "tài chính", "hậu quả", "không xử lý", "cost of inaction", 
            "financial", "exposure", "thiệt hại", "tổn thất", "nguy cơ"
        ])
        # Nhóm 3: Bộ chỉ số KPI / OKR / Đo lường hiệu quả chung (Chỉ khi hỏi về đo lường KPI mà không phải hỏi hành động)
        is_kpi_metrics = not is_30day_emergency and not is_anomaly_root_cause and not is_executive_actions and not is_cost_roi and not is_milestone_kpi and any(k in q_lower for k in [
            "kpi", "okr", "đo lường", "đánh giá hiệu quả", "metrics", "measure", "scorecard", "chỉ số đo lường"
        ])
        # Nhóm 4: Lộ trình & Kế hoạch triển khai
        is_roadmap = not is_30day_emergency and not is_anomaly_root_cause and not is_executive_actions and not is_cost_roi and not is_milestone_kpi and any(k in q_lower for k in [
            "lộ trình", "mốc", "milestone", "kế hoạch triển khai", "tiến độ", "roadmap", "timeline"
        ])
        # Nhóm 5: Tái phân bổ ngân sách & Nhân sự
        is_reallocation = not is_30day_emergency and not is_anomaly_root_cause and not is_executive_actions and not is_cost_roi and not is_milestone_kpi and not is_risk_contingency and any(k in q_lower for k in [
            "phân bổ", "ngân sách", "bố trí", "budget", "reallocate", "headcount", "tái cấu trúc", "nguồn lực", "định biên"
        ])

        if is_30day_emergency:
            def_hdr = "### 🎯 1. DANH MỤC HÀNH ĐỘNG ƯU TIÊN TRONG 30 NGÀY TỚI (30-Day Executive Priorities)"
            topic_rec = f"Quyết liệt chỉ đạo thực thi lộ trình tác chiến 30 ngày, ưu tiên khoanh vùng điểm nóng và kích hoạt cơ chế giữ chân nhân sự cốt lõi cho {layer_title}."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM 100% VỀ CÁC HÀNH ĐỘNG ƯU TIÊN TRONG 30 NGÀY TỚI CHO {layer_title.upper()} (TUYỆT ĐỐI CHỈ TRÌNH BÀY PHẠM VI 30 NGÀY THEO CÁC TUẦN, NGHIÊM CẤM ĐƯA RA CÁC MỐC 1-3 THÁNG HAY 3-6 THÁNG):
### 🎯 1. DANH MỤC HÀNH ĐỘNG ƯU TIÊN THEO TỪNG TUẦN (Weekly 30-Day Priorities)
- **Tuần 1 (Ngày 1 — 7) - Rà soát Khẩn cấp & Khoanh vùng Điểm nóng (Audit & Containment):** Tập trung khoanh vùng các điểm gãy vận hành, ổn định tâm lý và kích hoạt ngay chính sách giữ chân nhân tài/chế độ trọng điểm.
- **Tuần 2 (Ngày 8 — 15) - Tái Cân bằng Nguồn lực & Xử lý Điểm nghẽn (Adjustment & Rebalancing):** Điều chỉnh nhanh các bất hợp lý, phân bổ lại nhân sự hỗ trợ khâu quá tải và ban hành cơ chế khuyến khích tức thì.
- **Tuần 3 & 4 (Ngày 16 — 30) - Chuẩn hóa Quy trình & Thiết lập Giám sát Tự động (Standardization & Governance):** Ban hành quy chế kiểm soát mới, thiết lập cơ chế cảnh báo sớm hàng tuần và nghiệm thu kết quả bình ổn sau 30 ngày.

### ⚡ 2. CƠ CHẾ ĐIỀU HÀNH & PHÂN CÔNG THỰC THI (Execution Governance & RACI)
- **Phân công đầu mối (Accountable Owner):** Chỉ định rõ Trưởng khối/phòng ban chịu trách nhiệm trực tiếp cho từng tuần hành động.
- **Giao ban tác chiến:** Thiết lập cơ chế họp giao ban tác chiến nhanh định kỳ hàng tuần trực tiếp với Ban Giám Đốc để kiểm soát tiến độ.

### 📋 3. MA TRẬN HÀNH ĐỘNG 30 NGÀY THEO TỪNG TUẦN (30-Day Action Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Khung Thời gian (30 Ngày) | Hành động Trọng tâm Đề xuất | Đơn vị Chủ trì | Mục tiêu & Kết quả Kỳ vọng |
| :--- | :--- | :--- | :--- |
| 🔴 **Tuần 1 (Ngày 1 — 7)** | Rà soát khẩn cấp & Kích hoạt đãi ngộ giữ chân | Khối Nhân sự & Khối Vận hành | 100% nhân sự cốt lõi cam kết đồng hành |
| 🟡 **Tuần 2 (Ngày 8 — 15)** | Điều chuyển nhân sự giải tỏa điểm nghẽn | Khối Vận hành & Các Trưởng bộ phận | Giải tỏa 80% điểm nghẽn, thông suốt quy trình |
| 🟢 **Tuần 3 & 4 (Ngày 16 — 30)** | Chuẩn hóa quy chế & Thiết lập cảnh báo sớm | Ban Điều Hành & Khối Quản trị | Nghiệm thu ổn định 100% bộ máy sau 30 ngày |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách thực thi 30 ngày, ưu tiên giải tỏa điểm nghẽn và giữ chân nhân tài]."""

        elif is_anomaly_root_cause:
            def_hdr = "### 🧠 1. CHẨN ĐOÁN NGUYÊN NHÂN GỐC RỄ & CƠ CHẾ PHÁT SINH (Root-Cause Diagnosis)"
            topic_rec = f"Khẩn trương rà soát toàn diện cơ chế định biên và chính sách đãi ngộ nhằm cân bằng lại các khối chức năng và chặn đứng nguy cơ đứt gãy vận hành."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM VỀ NGUYÊN NHÂN GỐC RỄ VÀ CƠ CHẾ PHÁT SINH CHO {layer_title.upper()}:
### 🧠 1. CHẨN ĐOÁN NGUYÊN NHÂN GỐC RỄ & CƠ CHẾ PHÁT SINH (Root-Cause Diagnosis)
- **Bản chất hiện tượng:** Phân tích trực diện lý do phát sinh lệch pha/dị biệt dựa trên dữ liệu thực tế của {layer_title} và giai đoạn {time_label}.
- **Cơ chế dẫn đến sự mất cân đối:** Nêu rõ 2-3 nhân tố cấu thành cốt lõi (tập trung nguồn lực quá mức vào một số vị trí/khối chức năng, chênh lệch dải lương hoặc sự gia tăng đột biến về quy mô/định biên).

### ⚠️ 2. ĐÁNH GIÁ TÁC ĐỘNG VẬN HÀNH & NGUY CƠ RỦI RO (Operational Impact & Risk Assessment)
- **Tác động ngắn hạn:** Áp lực vận hành dồn vào các khối cốt lõi, nguy cơ đứt gãy quy trình và tạo ra tâm lý bất an ở các bộ phận phụ trợ.
- **Rủi ro dài hạn:** Mất cân đối chi phí vận hành, giảm tính linh hoạt của tổ chức và nguy cơ thất thoát nhân tài nếu không tái cân bằng kịp thời.

### 🎯 3. MA TRẬN HÀNH ĐỘNG KHẮC PHỤC ĐIỂM NGHẼN (Mitigation & Action Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Cấp độ Ưu tiên | Khung Thời gian | Hành động Cụ thể Đề xuất | Mục tiêu & Kết quả Kỳ vọng |
| :--- | :--- | :--- | :--- |
| 🔴 **Khẩn cấp** | 0 — 30 ngày | Rà soát dải lương & giải tỏa áp lực cho khối trọng điểm | Ngăn ngừa đứt gãy và ổn định tâm lý nhân sự |
| 🟡 **Ngắn hạn** | 1 — 3 tháng | Chuẩn hóa quy chế định biên & tái phân bổ nguồn lực | Cân bằng tỷ trọng các khối, nâng cao 15% năng suất |
| 🟢 **Dài hạn** | 3 — 6 tháng | Tự động hóa cảnh báo sớm & thể chế hóa khung năng lực | Đảm bảo bộ máy vận hành cân bằng và bền vững |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách giải quyết nguyên nhân gốc rễ và cân bằng lại định biên cho {layer_title}]."""

        elif is_executive_actions:
            def_hdr = "### 🎯 1. DANH MỤC HÀNH ĐỘNG ƯU TIÊN CHO BAN ĐIỀU HÀNH (Executive Action Priorities)"
            topic_rec = f"Quyết liệt chỉ đạo các khối chức năng triển khai ngay danh mục hành động ưu tiên, tập trung giải tỏa điểm nghẽn và nâng cao năng suất toàn diện."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM VỀ CÁC HÀNH ĐỘNG ĐIỀU HÀNH CẦN ƯU TIÊN:
### 🎯 1. DANH MỤC HÀNH ĐỘNG ƯU TIÊN CHO BAN ĐIỀU HÀNH (Executive Action Priorities)
- **Hành động Khẩn cấp (0 — 30 ngày):** Tập trung xử lý ngay các điểm gãy vận hành, ổn định tâm lý và giữ chân nhân sự then chốt.
- **Hành động Trọng tâm (1 — 3 tháng):** Tái cơ cấu quy trình phân bổ nguồn lực, nâng cấp hệ thống đào tạo kèm cặp và kiểm soát chi phí.
- **Hành động Tối ưu hóa (3 — 6 tháng):** Đổi mới chiến lược, tăng năng suất lao động và mở rộng quy mô bền vững.

### ⚡ 2. CƠ CHẾ ĐIỀU HÀNH & PHÂN CÔNG THỰC THI (Execution Governance & RACI)
- Phân công rõ trách nhiệm cho từng khối/phòng ban, thiết lập đầu mối chịu trách nhiệm trực tiếp (Accountable Owner).
- Cơ chế họp giao ban rà soát tiến độ định kỳ hàng tuần trực tiếp với Ban Giám Đốc.

### 📋 3. MA TRẬN HÀNH ĐỘNG ĐIỀU HÀNH THEO CẤP ĐỘ ƯU TIÊN (Executive Action Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Cấp độ Ưu tiên | Khung Thời gian | Hành động Cụ thể Đề xuất | Mục tiêu & Kết quả Kỳ vọng |
| :--- | :--- | :--- | :--- |
| 🔴 **Khẩn cấp** | 0 — 30 ngày | Điều chuyển nhân sự hỗ trợ điểm nghẽn & kích hoạt đãi ngộ | Ngăn ngừa đứt gãy và ổn định chỉ số vận hành |
| 🟡 **Ngắn hạn** | 1 — 3 tháng | Chuẩn hóa quy trình vận hành & tái phân bổ ngân sách | Nâng cao 15% năng suất lao động và giảm tỷ lệ lỗi |
| 🟢 **Dài hạn** | 3 — 6 tháng | Thể chế hóa khung năng lực & tự động hóa giám sát | Đảm bảo tổ chức tăng trưởng quy mô bền vững |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách chỉ đạo ưu tiên hành động trọng tâm cho Ban Điều Hành]."""

        elif is_cost_roi:
            def_hdr = "### 💰 1. LƯỢNG HÓA MỨC ĐỘ TIẾT KIỆM CHI PHÍ & TỐI ƯU ROI (Cost Savings & ROI Quantification)"
            topic_rec = f"Tập trung tinh gọn các khâu trung gian kém hiệu quả nhằm cắt giảm chi phí lãng phí và tối đa hóa tỷ suất sinh lời ROI."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM VỀ TIẾT KIỆM CHI PHÍ & TỐI ƯU HÓA ROI:
### 💰 1. LƯỢNG HÓA MỨC ĐỘ TIẾT KIỆM CHI PHÍ & TỐI ƯU ROI (Cost Savings & ROI Quantification)
- **Cắt giảm lãng phí & Tiết kiệm chi phí trực tiếp:** Ước tính mức tiết kiệm 15 — 20% tổng chi phí vận hành nhờ tinh gọn các khâu trung gian và kiểm soát lỗi quy trình.
- **Tối ưu chi phí nhân sự & chi phí cơ hội:** Tiết kiệm hàng tỷ đồng chi phí tuyển dụng thay thế khẩn cấp nhờ chính sách giữ chân nhân sự cốt lõi và nâng cao năng suất lao động.

### 📈 2. ĐỘNG LỰC TẠO RA ROI & THỜI GIAN HOÀN VỐN (ROI Drivers & Payback Period)
- **Thời gian hoàn vốn dự kiến (Payback Period):** Dự kiến đạt điểm hòa vốn trong vòng 3 — 6 tháng sau khi tái cơ cấu nguồn lực.
- **Tỷ suất sinh lời ROI kỳ vọng:** Ước tính đạt 150% — 200% so với tổng chi phí đầu tư vào chuyển đổi quy trình và nâng cấp năng lực.

### ⚖️ 3. MA TRẬN LƯỢNG HÓA TÀI CHÍNH & ROI THEO HẠNG MỤC (Financial & ROI Matrix)
Tạo bảng Markdown gồm 4 cột phân tích tài chính rõ ràng:
| Hạng mục Tối ưu | Mức Tiết kiệm Chi phí Dự kiến | Chi phí Đầu tư Triển khai | Tỷ suất ROI Kỳ vọng |
| :--- | :--- | :--- | :--- |
| **Tinh gọn quy trình & Vận hành** | Tiết kiệm 15% chi phí quản lý | 5% tổng ngân sách | 200% sau 6 tháng |
| **Đào tạo & Giữ chân nhân sự cốt lõi** | Giảm 50% chi phí tuyển dụng lại | 10% tổng ngân sách | 180% sau 6 tháng |
| **Tự động hóa & Kiểm soát chất lượng** | Giảm 30% tổn thất do lỗi sự cố | 10% tổng ngân sách | 150% sau 9 tháng |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách tinh gọn chi phí và tối ưu hóa tỷ suất ROI]."""

        elif is_milestone_kpi:
            def_hdr = "### ⏱️ 1. BỘ CHỈ SỐ KPI & OKR THEO CÁC MỐC 30 — 60 — 90 NGÀY (Phased Milestone KPIs)"
            topic_rec = f"Thể chế hóa bộ chỉ số KPI định lượng và tiến hành kiểm toán tiến độ định kỳ tại các mốc 30 — 60 — 90 ngày để đảm bảo hoàn thành mục tiêu."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM THEO 3 MỐC 30 — 60 — 90 NGÀY:
### ⏱️ 1. BỘ CHỈ SỐ KPI & OKR THEO CÁC MỐC 30 — 60 — 90 NGÀY (Phased Milestone KPIs)
- **Mốc 30 Ngày (Kiểm soát Khẩn cấp & Ổn định Bộ máy):**
  - Tỷ lệ giữ chân nhân sự cốt lõi: Đạt $\ge 95\%$.
  - Tỷ lệ giải tỏa điểm nghẽn vận hành: Đạt $\ge 80\%$.
  - Hạn mức kiểm soát chi phí khẩn cấp: Đúng định mức phân bổ.
- **Mốc 60 Ngày (Chuẩn hóa Quy trình & Nâng cao Năng suất):**
  - Năng suất lao động trung bình: Tăng trưởng 10 — 15%.
  - Tỷ lệ nhân sự đạt chuẩn qua đào tạo: Đạt $\ge 90\%$.
  - Thời gian xử lý quy trình/sự cố: Giảm 20 — 25%.
- **Mốc 90 Ngày (Tối ưu Bền vững & Đo lường ROI Tổ chức):**
  - Điểm sức khỏe vận hành tổng thể: Phục hồi $\ge 85/100$.
  - Tối ưu hóa chi phí vận hành: Tiết kiệm bền vững 10 — 15%.
  - Tỷ lệ hoàn thành mục tiêu chiến lược: Đạt $\ge 90\%$.

### 📈 2. QUY TRÌNH KIỂM TRA ĐỊNH KỲ & CƠ CHẾ CẢNH BÁO SỚM (Review Schedule & Early Warnings)
- **Tần suất kiểm toán:** Báo cáo nhanh hàng tuần và kiểm toán nghiệm thu chính thức vào ngày thứ 30, 60 và 90.
- **Ngưỡng kích hoạt can thiệp:** Kích hoạt Tổ phản ứng nhanh nếu tỷ lệ hoàn thành KPI tại bất kỳ mốc nào dưới 80%.

### 🎯 3. MA TRẬN THEO DÕI KPI THEO CÁC MỐC THỜI GIAN (Milestone KPI Tracking Matrix)
Tạo bảng Markdown gồm 4 cột phân tích đúng 3 mốc:
| Mốc Thời gian | Nhóm Chỉ số Then chốt | Mục tiêu Định lượng (Target) | Hành động Can thiệp khi Chậm tiến độ |
| :--- | :--- | :--- | :--- |
| **Mốc 30 ngày** (Ổn định khẩn cấp) | Tỷ lệ giữ chân nhân sự & Điểm nghẽn | Giữ chân $\ge 95\%$ nhân sự chủ chốt | Kích hoạt quỹ đãi ngộ và điều động nhân sự dự phòng |
| **Mốc 60 ngày** (Chuẩn hóa quy trình) | Năng suất lao động & Đào tạo | Tăng 10 — 15% năng suất; 90% đạt chuẩn | Rà soát chương trình kèm cặp và tối ưu thao tác |
| **Mốc 90 ngày** (Tối ưu bền vững) | Điểm sức khỏe vận hành & ROI | Sức khỏe $\ge 85/100$; Tiết kiệm 15% chi phí | Tái cơ cấu định biên ngân sách cho kỳ tiếp theo |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách đo lường và kiểm toán các mốc KPI 30-60-90 ngày]."""

        elif is_risk_contingency:
            def_hdr = "### 🛡️ 1. KẾ HOẠCH KIỂM SOÁT RỦI RO TRỌNG YẾU (Core Risk Control Plan)"
            topic_rec = f"Thiết lập hệ thống cảnh báo sớm hàng tuần và ban hành phương án dự phòng khẩn cấp để chủ động kiểm soát rủi ro vận hành."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM VỀ KIỂM SOÁT RỦI RO & PHƯƠNG ÁN DỰ PHÒNG THEO CẤU TRÚC 3 KHỐI:
### 🛡️ 1. KẾ HOẠCH KIỂM SOÁT RỦI RO TRỌNG YẾU (Core Risk Control Plan)
- **Đề phòng rủi ro vận hành & đứt gãy:** Nêu rõ các biện pháp chủ động kiểm soát quy trình, tránh dồn áp lực hoặc chậm tiến độ.
- **Kiểm soát rủi ro tài chính & ngân sách:** Giám sát chặt chẽ chi phí phát sinh ngoài kế hoạch và lãng phí nguồn lực.

### 🚨 2. PHƯƠNG ÁN DỰ PHÒNG & PHẢN ỨNG NHANH (Contingency & Incident Response)
- **Kịch bản ứng phó sự cố:** Thiết lập cơ chế kích hoạt tổ phản ứng nhanh khi có điểm nghẽn hoặc sai số vượt ngưỡng.
- **Phương án bù đắp nguồn lực:** Điều động nhân sự dự phòng và giải tỏa các mắt xích quá tải.

### ⚠️ 3. MA TRẬN RỦI RO & BIỆN PHÁP ỨNG PHÓ (Risk & Mitigation Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Loại Rủi ro | Mức độ Tác động | Dấu hiệu Cảnh báo Sớm | Biện pháp Dự phòng & Ứng phó |
| :--- | :--- | :--- | :--- |
| **Rủi ro Vận hành** | 🔴 Nghiêm trọng | Điểm nghẽn tăng cao, tiến độ chậm $\ge 15\%$ | Kích hoạt đội phản ứng nhanh, điều chuyển nhân sự hỗ trợ |
| **Rủi ro Nhân sự** | 🟡 Trung bình | Tỷ lệ nghỉ việc tăng, quá tải công việc | Áp dụng chính sách đãi ngộ linh hoạt, kèm cặp 1-1 |
| **Rủi ro Tài chính** | 🟡 Trung bình | Chi phí phát sinh vượt dự toán $\ge 10\%$ | Tái cơ cấu ngân sách khẩn cấp, cắt giảm chi phí trung gian |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách kiểm soát rủi ro và kích hoạt phương án dự phòng]."""

        elif is_kpi_metrics:
            def_hdr = "### 📊 1. BỘ CHỈ SỐ KPI & OKR ĐO LƯỜNG TRỌNG TÂM (Key Performance Indicators & Metrics)"
            topic_rec = f"Ban hành quy chế theo dõi bộ chỉ số hiệu suất trọng yếu và thiết lập ngưỡng cảnh báo sớm hàng tuần để chủ động can thiệp kịp thời."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM VỀ BỘ CHỈ SỐ KPI, OKR VÀ ĐO LƯỜNG HIỆU QUẢ THEO CẤU TRÚC 3 KHỐI:
### 📊 1. BỘ CHỈ SỐ KPI & OKR ĐO LƯỜNG TRỌNG TÂM (Key Performance Indicators & Metrics)
- Nêu rõ 3-4 chỉ số định lượng cụ thể (về hiệu suất vận hành, chi phí/doanh thu, năng suất lao động, tỷ lệ giữ chân nhân sự).
- Kèm theo mục tiêu định lượng (Target %) và số liệu kỳ vọng rõ ràng.

### 📈 2. CƠ CHẾ GIÁM SÁT & TẦN SUẤT THEO DÕI (Governance & Tracking Mechanism)
- Quy định rõ tần suất cập nhật dữ liệu (hàng tuần, hàng tháng, hàng quý).
- Thiết lập ngưỡng cảnh báo sớm (Early Warning Triggers) để phát hiện sai lệch kịp thời.

### 🎯 3. MA TRẬN ĐO LƯỜNG HIỆU QUẢ THEO PHÂN HỆ (Performance Measurement Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Nhóm Chỉ số | Chỉ số Cụ thể & Mục tiêu | Tần suất Đo lường | Hành động khi Không đạt |
| :--- | :--- | :--- | :--- |
| **Vận hành & Năng suất** | Năng suất lao động tăng $\ge 15\%$ | Hàng tuần | Rà soát quy trình, đào tạo lại thao tác chuẩn |
| **Nhân sự & Gắn kết** | Tỷ lệ giữ chân nhân sự cốt lõi $\ge 95\%$ | Hàng tháng | Điều chỉnh chính sách đãi ngộ, lắng nghe phản hồi |
| **Tài chính & Chi phí** | Tiết kiệm chi phí vận hành $\ge 10\%$ | Hàng tháng | Tinh gọn quy trình, rà soát các khoản chi lãng phí |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách thể chế hóa bộ chỉ số đo lường hiệu suất]."""

        elif is_roadmap:
            def_hdr = "### 🎯 1. LỘ TRÌNH TRIỂN KHAI CHI TIẾT (Phased Execution Roadmap)"
            topic_rec = f"Phê duyệt lộ trình triển khai chi tiết theo 3 giai đoạn và gắn trách nhiệm người đứng đầu cho từng mốc hoàn thành."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM VỀ LỘ TRÌNH TRIỂN KHAI VÀ KẾ HOẠCH HÀNH ĐỘNG THEO CẤU TRÚC 3 KHỐI:
### 🎯 1. LỘ TRÌNH TRIỂN KHAI THEO TỪNG GIAI ĐOẠN (Phased Execution Roadmap)
- **Giai đoạn 1 (Ngày 1 — 30):** Các hành động ổn định khẩn cấp, rà soát hiện trạng và giải tỏa áp lực tức thì.
- **Giai đoạn 2 (Tháng 2 — 3):** Tái cơ cấu quy trình, tối ưu hóa phân bổ nguồn lực và chuẩn hóa vận hành.
- **Giai đoạn 3 (Tháng 4 — 6):** Thể chế hóa quy chuẩn, tự động hóa giám sát và tối ưu hóa chi phí bền vững.

### 🛡️ 2. PHƯƠNG ÁN ĐẢM BẢO TIẾN ĐỘ & PHÂN CÔNG (Execution & Accountability Plan)
- Các tình huống phát sinh ngoài dự kiến (chậm tiến độ, ngân sách biến động).
- Cơ chế phân công trách nhiệm và kiểm soát bàn giao từng khâu.

### 📋 3. MA TRẬN PHÂN CÔNG TRÁCH NHIỆM & MỐC KIỂM SOÁT (Accountability & Milestone Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Giai đoạn Triển khai | Nhiệm vụ Then chốt | Đơn vị Chủ trì | Tiêu chí Hoàn thành |
| :--- | :--- | :--- | :--- |
| **Giai đoạn 1 (0 — 30 ngày)** | Thiết lập Bảng điều khiển & Giải tỏa điểm nghẽn khẩn cấp | Ban Điều Hành & Khối Vận Hành | Bảng điều khiển hoạt động ổn định, giữ chân nhân sự |
| **Giai đoạn 2 (1 — 3 tháng)** | Đánh giá, chuẩn hóa quy trình và đào tạo nâng cao năng suất | Khối Vận Hành & Khối Nhân sự | Năng suất tăng 15%, 90% nhân sự đạt chuẩn |
| **Giai đoạn 3 (3 — 6 tháng)** | Tự động hóa hệ thống giám sát và tối ưu hóa chi phí bền vững | Ban Điều Hành & Khối Tài chính | Tiết kiệm 15% chi phí, hệ thống tự động cảnh báo |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách chỉ đạo lộ trình triển khai và phân công trách nhiệm]."""

        elif is_reallocation:
            def_hdr = "### 💰 1. CHIẾN LƯỢC TÁI PHÂN BỔ NGÂN SÁCH (Budget Reallocation Strategy)"
            topic_rec = f"Khẩn trương phê duyệt kế hoạch tái phân bổ ngân sách và điều động nhân sự có năng lực cao sang hỗ trợ các điểm nghẽn để tối ưu hóa hiệu suất vận hành."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI ĐÚNG TRỌNG TÂM VỀ PHÂN BỔ NGÂN SÁCH VÀ NHÂN SỰ THEO CẤU TRÚC 3 KHỐI:
### 💰 1. CHIẾN LƯỢC TÁI PHÂN BỔ NGÂN SÁCH (Budget Reallocation Strategy)
- **Tối ưu hóa dòng tiền:** Cắt giảm ngân sách ở các khâu trung gian kém hiệu quả hoặc chi phí dàn trải.
- **Tập trung đầu tư trọng điểm:** Dồn nguồn lực vào các phòng ban tạo ra giá trị gia tăng cốt lõi và giữ chân nhân tài.

### 👥 2. KẾ HOẠCH BỐ TRÍ & ĐIỀU ĐỘNG NHÂN LỰC (Workforce Deployment)
- **Cân bằng định biên:** Điều chuyển nhân sự có năng lực cao sang hỗ trợ các điểm nghẽn.
- **Chính sách phát triển nhân tài:** Thiết lập cơ chế kèm cặp (mentorship) và chuẩn hóa lộ trình thăng tiến.

### ⚖️ 3. MA TRẬN PHÂN BỔ NGUỒN LỰC THEO PHÒNG BAN (Resource Allocation Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Khối chức năng | Tỷ trọng Ngân sách Đề xuất | Định hướng Nhân sự & Tuyển dụng | Mục tiêu Kỳ vọng |
| :--- | :--- | :--- | :--- |
| **Khối Vận hành** | 45% tổng ngân sách | Bổ sung chuyên viên xử lý điểm nghẽn | Nâng cao 20% hiệu suất vận hành trực tiếp |
| **Khối Đào tạo & Nhân sự** | 30% tổng ngân sách | Kèm cặp thực chiến, giữ chân nhân tài | Giảm 50% tỷ lệ thôi việc, tăng độ gắn kết |
| **Khối Chuyển đổi Số** | 25% tổng ngân sách | Tự động hóa giám sát & cảnh báo sớm | Tiết kiệm 15% chi phí quản lý vận hành |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách phê duyệt kế hoạch tái phân bổ ngân sách và điều động nhân sự]."""

        else:
            def_hdr = "### 📊 1. TỔNG QUAN HIỆN TRẠNG & ĐỘNG LỰC CỐT LÕI (Executive Summary)"
            topic_rec = f"Quyết liệt chỉ đạo rà soát định biên, tối ưu hóa phân bổ nguồn lực và thiết lập mốc kiểm soát tiến độ định kỳ hàng tuần cho {layer_title}."
            structure_guide = f"""BẮT BUỘC TRẢ LỜI THEO CẤU TRÚC PHÂN TÍCH QUẢN TRỊ 3 KHỐI:
### 📊 1. TỔNG QUAN HIỆN TRẠNG & ĐỘNG LỰC CỐT LÕI (Executive Summary)
- **Hiện trạng:** Tóm lược 1-2 câu súc tích về tình hình vận hành và xu hướng chính dựa trên Dashboard.
- **Động lực chính:** 2-3 gạch đầu dòng nêu rõ các yếu tố thúc đẩy then chốt kèm số liệu định lượng.

### 🧠 2. CHẨN ĐOÁN GỐC RỄ & CƠ CHẾ VẬN HÀNH (Root-Cause Diagnosis)
- **Bản chất vận hành:** Lý giải cơ chế tại sao số liệu lại diễn tiến như vậy trong giai đoạn này.
- **Điểm nghẽn & Rủi ro tiềm ẩn:** Cảnh báo rủi ro cốt lõi nếu không can thiệp kịp thời.

### 🎯 3. MA TRẬN HÀNH ĐỘNG ĐIỀU HÀNH (Executive Action Matrix)
Tạo bảng Markdown gồm 4 cột cụ thể:
| Cấp độ Ưu tiên | Khung Thời gian | Hành động Cụ thể Đề xuất | Mục tiêu & Kết quả Kỳ vọng |
| :--- | :--- | :--- | :--- |
| 🔴 **Khẩn cấp** | 0 — 30 ngày | Điều chuyển nhân sự giải tỏa điểm nghẽn & ổn định tổ chức | Ngăn ngừa đứt gãy và khôi phục chỉ số vận hành |
| 🟡 **Ngắn hạn** | 1 — 3 tháng | Chuẩn hóa quy trình vận hành & tái phân bổ ngân sách | Nâng cao 15% năng suất lao động và giảm lỗi |
| 🟢 **Dài hạn** | 3 — 6 tháng | Thể chế hóa khung năng lực & tự động hóa giám sát | Đảm bảo tổ chức tăng trưởng quy mô bền vững |

> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách điều hành trọng tâm cho {layer_title}]."""

        # 4. Thiết kế System Prompt chuẩn Senior Executive BI Advisor
        system_instruction = f"""Bạn là **Veraxus In-Context Dashboard Copilot** — Cố vấn Điều hành Cấp cao (C-Level Executive BI Advisor) đồng hành trực tiếp trên Bảng Điều Khiển Quản Trị Doanh Nghiệp.

BỐI CẢNH SỐNG ĐANG HIỂN THỊ TRÊN MÀN HÌNH DASHBOARD:
================================================================================
• Chủ đề phân tích (Layer): {layer_title}
• Giai đoạn thời gian: {time_label}
• Tình trạng & Chỉ số KPI:
{kpis_str}
• Danh sách dị biệt / Điểm gãy vận hành đã phát hiện:
{anomalies_text}
• Tóm tắt dữ liệu biểu đồ:
{data_summary}
================================================================================

QUY CHUẨN ĐỊNH DẠNG VÀ VĂN PHONG QUẢN TRỊ BẮT BUỘC:
1. TRẢ LỜI TRỰC DIỆN, THỰC TẾ, ĐÚNG TRỌNG TÂM VÀ PHẠM VI THỜI GIAN ĐƯỢC HỎI:
   - TUÂN THỦ TUYỆT ĐỐI PHẠM VI THỜI GIAN CỦA CÂU HỎI: Khi câu hỏi yêu cầu hành động/ưu tiên trong "30 ngày" / "30 ngày tới", TUYỆT ĐỐI CHỈ TRÌNH BÀY kế hoạch 30 ngày (chia theo Tuần 1, Tuần 2, Tuần 3 & 4), TUYỆT ĐỐI KHÔNG ĐƯỢC đưa ra các mốc thời gian ngoài phạm vi 30 ngày (như 1 — 3 tháng hay 3 — 6 tháng).
   - TUYỆT ĐỐI KHÔNG dùng từ ngữ hàn lâm, máy móc, phi thực tế hoặc các từ dịch ngô nghê (như 'hàm chì', 'nganh trừng', 'thiêm nghiệm', 'công suất người lao động', 'cáo trạng', 'hàm xác nhận', 'Lần 1', 'Lần 2').
   - PHẢI DÙNG 100% THUẬT NGỮ QUẢN TRỊ DOANH NGHIỆP THỰC CHIẾN (như: Quỹ lương, Dải lương, Gói đãi ngộ giữ chân nhân tài, Hiệu suất làm việc, Bảng điều khiển giám sát, Điểm gãy vận hành, Giao ban định kỳ, Ban hành quy chế).
2. BẮT BUỘC tạo ĐẦY ĐỦ 3 khối nội dung với 3 tiêu đề `### ` (kèm icon và số thứ tự 1, 2, 3) và 1 bảng Markdown ở Khối 3.
3. TUYỆT ĐỐI SỬ DỤNG 100% TIẾNG VIỆT CHUẨN MỰC, TỰ NHIÊN, SẮC BÉN.
4. TUYỆT ĐỐI KHÔNG sử dụng các từ khóa vô nghĩa, ký tự đại diện (placeholder) như: '00', 'MM', 'XX', 'YY', 'Mốc 00', 'Mốc MM', 'Một mốc kiểm soát tùy chỉnh', 'placeholder'. Phải luôn dùng mốc thời gian thực tế rõ ràng (như: 'Tuần 1 (Ngày 1 — 7)', 'Giai đoạn 1 (0 — 30 ngày)', 'Giai đoạn 2 (1 — 3 tháng)').
5. TUYỆT ĐỐI KHÔNG sử dụng các ký tự ngoặc vuông [ ] trong bảng hoặc bất kỳ câu chữ nào.
6. Cuối câu trả lời LUÔN LUÔN kết thúc bằng DUY NHẤT 1 khối trích dẫn khuyến nghị điều hành:
> 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu đúc kết quyết sách đắt giá nhất cho Lãnh đạo, tối đa 25-35 từ].
QUY TẮC BẮT BUỘC CHO KHUYẾN NGHỊ:
- ĐÂY PHẢI LÀ DUY NHẤT 1 CÂU MỆNH LỆNH ĐIỀU HÀNH TRỰC DIỆN, SẮC BÉN DÀNH CHO LÃNH ĐẠO.
- TUYỆT ĐỐI NGHIÊM CẤM đánh số thứ tự (1., 2., 3.), TUYỆT ĐỐI KHÔNG dùng câu mào đầu dài dòng như 'Cần thực hiện một số bước chính:' hay 'Dưới đây là các bước:'.
- TUYỆT ĐỐI KHÔNG thêm bất kỳ tiêu đề, danh sách, hay các ký tự thừa như '---', '***', '___' ở cuối phản hồi.
7. QUY TẮC PHẠM VI TRẢ LỜI ĐƠN NHẤT & DỪNG NGAY LẬP TỨC (STRICT SINGLE-ANSWER BOUNDARY):
   - CHỈ TRẢ LỜI DUY NHẤT 1 CÂU HỎI HIỆN TẠI ĐƯỢC NÊU TRONG THẺ CÂU HỎI.
   - TUYỆT ĐỐI NGHIÊM CẤM tự bịa ra thêm câu hỏi tiếp theo của Người dùng ('Người dùng:', 'Lãnh Đạo:', 'User:', 'Ban Điều Hành:') hay tự đóng vai trả lời tiếp ('AI Copilot:', 'Veraxus Copilot:').
   - TUYỆT ĐỐI NGHIÊM CẤM lặp lại câu hỏi hoặc nội dung trả lời của các câu hỏi trước.
   - BẮT BUỘC DỪNG TOÀN BỘ CÂU TRẢ LỜI ngay sau khối trích dẫn duy nhất:
     > 💡 **Khuyến nghị Trọng tâm cho Ban Điều Hành:** [1 câu quyết sách].

HƯỚNG DẪN CẤU TRÚC CHO CÂU TRẢ LỜI NÀY:
{structure_guide}
"""

        history_section = f"{history_text}\n\n" if history_text.strip() else ""

        user_content = f"""{history_section}Yêu cầu phân tích:
"{question}"

Hãy phân tích dữ liệu thực tế và trả lời một cách thông minh, sắc bén, bám sát và ĐÚNG TRỰC DIỆN TRỌNG TÂM câu hỏi trên, tuân thủ đúng cấu trúc 3 khối được yêu cầu, sử dụng 100% tiếng Việt chuẩn mực, không dùng ngoặc vuông hay ký tự chữ Hán."""

        full_prompt = f"{system_instruction}\n\n{user_content}"

        try:
            response = invoke_llm(full_prompt, max_tokens=1500)
            clean_resp = sanitize_executive_vietnamese_text(response, default_header=def_hdr, default_rec=topic_rec)
            return clean_resp
            return clean_resp
        except Exception as e:
            return f"Xin lỗi, Copilot gặp gián đoạn tạm thời khi phân tích dữ liệu: {str(e)}. Vui lòng thử lại!"

    def generate_followup_chips(
        self,
        question: str,
        answer: str,
        ctx: Dict[str, Any],
        lang: str = "vi"
    ) -> List[str]:
        """Tự động sinh ra bộ câu hỏi đào sâu thông minh tiếp theo sau khi trả lời một câu hỏi."""
        is_en = (lang == "en")
        layer_name = ctx.get("layer_title", "Tổng quan Doanh nghiệp")
        time_label = ctx.get("time_label", "1985 - 2002")

        q_lower = question.lower()
        if is_en:
            if any(k in q_lower for k in ["why", "cause", "reason", "explain", "driver", "anomaly", "skew"]):
                return [
                    f"What immediate action should the Executive Board take in the next 30 days?",
                    f"What are the operational and financial risks if left unaddressed?",
                    f"How should executive leadership reallocate budget and headcount?"
                ]
            elif any(k in q_lower for k in ["kpi", "okr", "metric", "measure", "scorecard"]):
                return [
                    f"What is the risk contingency plan if targets are not met?",
                    f"What is the detailed month-by-month execution roadmap?",
                    f"How should executive leadership reallocate budget across teams?"
                ]
            elif any(k in q_lower for k in ["roadmap", "timeline", "milestone", "plan"]):
                return [
                    f"Which specific KPIs/OKRs will verify milestone completion?",
                    f"What contingency steps are triggered if milestones are delayed?",
                    f"What is the financial cost optimization achieved after this roadmap?"
                ]
            elif any(k in q_lower for k in ["risk", "impact", "financial", "exposure", "cost"]):
                return [
                    f"How should executive leadership reallocate budget and headcount to prevent this?",
                    f"Which early warning KPIs should leadership monitor weekly?",
                    f"What are the immediate 30-day emergency mitigation actions?"
                ]
            elif any(k in q_lower for k in ["budget", "reallocate", "headcount", "resource"]):
                return [
                    f"Which specific KPIs/OKRs will measure ROI after reallocation?",
                    f"What is the risk mitigation plan during resource restructuring?",
                    f"What is the detailed month-by-month execution roadmap?"
                ]
            else:
                return [
                    f"How should budget and headcount be reallocated for {layer_name}?",
                    f"What are the financial and operational risks if not fixed?",
                    f"What is the detailed 30-60-90 day execution roadmap?"
                ]
        else:
            # Nhóm 0: Câu hỏi vừa rồi về Chẩn đoán / Nguyên nhân / Dị biệt / Lệch pha -> Gợi ý Hành động ưu tiên, Kế hoạch rủi ro, Phân bổ lại ngân sách
            if any(k in q_lower for k in ["vì sao", "tại sao", "nguyên nhân", "lý do", "giải thích", "lệch pha", "dị biệt", "bất thường", "xuất hiện"]):
                return [
                    f"💡 Ban Giám Đốc cần ưu tiên hành động gì ngay trong 30 ngày tới?",
                    f"💡 Đánh giá tác động tài chính & nhân sự nếu không xử lý điểm gãy này?",
                    f"💡 Ban Giám Đốc nên phân bổ lại ngân sách và nhân sự như thế nào?"
                ]
            # Nhóm 1: Câu hỏi vừa rồi về KPI / Đo lường hiệu quả -> Gợi ý về Rủi ro dự phòng, Lộ trình, Tác động tài chính
            elif any(k in q_lower for k in ["kpi", "okr", "chỉ số", "đo lường", "đánh giá hiệu quả"]):
                return [
                    f"💡 Kế hoạch kiểm soát rủi ro và phương án dự phòng khi các chỉ số không đạt?",
                    f"💡 Lộ trình hành động chi tiết và phân công trách nhiệm theo từng mốc?",
                    f"💡 Đánh giá mức độ tiết kiệm chi phí và tối ưu ROI dự kiến?"
                ]
            # Nhóm 2: Câu hỏi vừa rồi về Lộ trình / Kế hoạch triển khai -> Gợi ý về KPI đo lường mốc, Phương án dự phòng, Tái phân bổ ngân sách
            elif any(k in q_lower for k in ["lộ trình", "mốc", "milestone", "kế hoạch triển khai", "tiến độ"]):
                return [
                    f"💡 Bộ chỉ số KPI kiểm tra định kỳ tại các mốc 30-60-90 ngày?",
                    f"💡 Kế hoạch dự phòng khẩn cấp nếu tiến độ bị chậm so với dự kiến?",
                    f"💡 Phương án phân bổ ngân sách tối ưu để đảm bảo đúng tiến độ?"
                ]
            # Nhóm 3: Câu hỏi vừa rồi về Tác động tài chính / Rủi ro -> Gợi ý về Phân bổ ngân sách, Cảnh báo sớm, Lộ trình khẩn cấp
            elif any(k in q_lower for k in ["tác động", "tài chính", "rủi ro", "hậu quả", "thiệt hại", "tổn thất"]):
                return [
                    f"💡 Ban Giám Đốc nên phân bổ lại ngân sách và nhân sự để chặn đứng rủi ro?",
                    f"💡 Bộ chỉ số cảnh báo sớm (Early Warning KPIs) cần theo dõi hàng tuần?",
                    f"💡 Lộ trình hành động khẩn cấp trong 30 ngày tới để kiểm soát tổn thất?"
                ]
            # Nhóm 4: Câu hỏi vừa rồi về Tái phân bổ ngân sách / Nhân sự -> Gợi ý về KPI đo lường hiệu quả, Kế hoạch rủi ro, Lộ trình
            elif any(k in q_lower for k in ["phân bổ", "ngân sách", "bố trí", "tái cấu trúc", "nguồn lực"]):
                return [
                    f"💡 Bộ chỉ số KPI đo lường hiệu quả sau khi tái phân bổ nguồn lực?",
                    f"💡 Kế hoạch kiểm soát rủi ro và phương án dự phòng khi tái cấu trúc?",
                    f"💡 Lộ trình triển khai chi tiết theo từng mốc (Tháng 1 — 3 — 6)?"
                ]
            # Nhóm 5: Câu hỏi chẩn đoán / Tổng quan / Mặc định -> Gợi ý phân bổ, rủi ro, lộ trình
            else:
                return [
                    f"💡 Ban Giám Đốc nên phân bổ lại ngân sách và nhân sự như thế nào?",
                    f"💡 Đánh giá tác động tài chính & nhân sự nếu không xử lý điểm gãy này?",
                    f"💡 Lộ trình hành động khẩn cấp trong 30 ngày tới cho {layer_name}?"
                ]

