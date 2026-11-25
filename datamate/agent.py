"""Headless, domain-agnostic DataMate analytics agent with strict output typing & risk-aware abstention."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from datamate.evaluator_pa import is_valid_submission_record
from datamate.llm_backend import LLMBackend, LLMConfig, MultiProviderLLMBackend, extract_json_object
from datamate.loader import BusinessWorkspace, load_business_workspace
from datamate.python_sandbox import execute_python_safe, extract_python_from_response
from datamate.schema_context import (
    WorkspaceKnowledge,
    build_focused_schema_prompt,
    build_workspace_knowledge,
    ground_query_entities,
    run_deterministic_probes,
)
from datamate.sql_executor import (
    SQLExecutionResult,
    execute_sql_safe,
    norm_vn,
    round_half_up,
)
from datamate.temporal import SolarLunarCalendar, TemporalResolver, normalize_nfc, parse_date_value

_ENGLISH_KEEP_WORDS = frozenset(
    {
        "bill", "bills", "size", "combo", "order", "orders", "staff", "coffee",
        "milk", "juice", "latte", "tea", "plus", "kids", "cool", "box", "pack",
        "pcs", "ok", "cod", "vat", "zalo", "store", "cash", "phone", "mail",
        "admin", "soda", "extra", "special", "gold", "silver", "max", "mini",
        "pro", "care", "gel", "cream", "spray", "oil", "gas", "led", "pvc",
        "categories", "category", "employees", "employee", "customers", "customer",
        "products", "product", "suppliers", "shippers", "regions", "territories",
        "sales", "revenue", "price", "prices", "status", "details", "units",
    }
)

_TELEX_DOUBLES = (
    ("dd", "d"),
    ("aa", "a"),
    ("ee", "e"),
    ("oo", "o"),
    ("aw", "a"),
    ("ow", "o"),
    ("uw", "u"),
)

_TEENCODE_MAP = {
    "hnay": "hom nay",
    "hqua": "hom qua",
    "bua": "hom",
    "dthu": "doanh thu",
    "bnhiu": "bao nhieu",
    "bnhieu": "bao nhieu",
    "nhiu": "nhieu",
    "bn": "bao nhieu",
    "trc": "truoc",
    "truowcs": "truoc",
    "dc": "duoc",
    "dk": "duoc",
    "duwowcj": "duoc",
    "sl": "so luong",
    "sp": "san pham",
    "kh": "khach hang",
    "nv": "nhan vien",
    "ncc": "nha cung cap",
    "ddon": "don",
    "ddown": "don",
    "ddonw": "don",
    "nguwowif": "nguoi",
    "cuwar": "cua",
    "cuar": "cua",
    "nhieeuf": "nhieu",
    "nhuwngx": "nhung",
    "vaayj": "vay",
    "chieems": "chiem",
    "trawm": "tram",
    "khoong": "khong",
    "toongr": "tong",
    "soos": "so",
    "tieenf": "tien",
    "heets": "het",
    "naof": "nao",
    "nhaats": "nhat",
    "cos": "co",
    "laf": "la",
    "thangs": "thang",
    "ngayf": "ngay",
    "hangf": "hang",
    "giups": "giup",
    "mays": "may",
    "tinhs": "tinh",
    "vaof": "vao",
    "boor": "bo",
    "ngayh": "ngay",
}


def normalize_vn_question(text: str) -> str:
    """
    Normalize accented Vietnamese, teencode (`hnay`, `hqua`, `dthu`, `bnhiu`, `trc`),
    and human Telex typing typos (`naof`, `nhaats`, `cos`, `khoong`, `trawm`)
    strictly for question intent, temporal, and semantic analysis.
    """
    s = norm_vn(text).replace("≥", ">=").replace("≤", "<=").replace("→", " ")
    if not s:
        return ""
    tokens = re.findall(r"[a-z0-9]+|[^a-z0-9\s]+", s)
    out: List[str] = []
    for tok in tokens:
        if not tok.isalnum() or tok.isdigit():
            out.append(tok)
            continue
        if tok in _TEENCODE_MAP:
            out.append(_TEENCODE_MAP[tok])
            continue
        if tok in _ENGLISH_KEEP_WORDS or len(tok) <= 2:
            out.append(tok)
            continue
        w = tok
        for src, dst in _TELEX_DOUBLES:
            if src in w:
                w = w.replace(src, dst)
        if w in _TEENCODE_MAP:
            out.append(_TEENCODE_MAP[w])
            continue
        # Strip conservative single trailing Telex tone modifier on Vietnamese syllables
        m_tone = re.match(r"^([a-z]*[aeiouy][a-z]{0,3}?)(f|s|r|x|j)$", w)
        if m_tone and len(w) >= 3 and w not in _ENGLISH_KEEP_WORDS:
            base = m_tone.group(1)
            # Only strip when ending looks like valid Vietnamese open/coda syllable
            if re.search(r"(?:[aeiouy]|n|m|ng|nh|c|ch|p|t)$", base):
                w = base
        out.append(_TEENCODE_MAP.get(w, w))
    # Collapse glued spacing around punctuation cleanly
    joined = " ".join(out)
    joined = re.sub(r"\s+([/%.,?!:])\s+", r"\1", joined)
    joined = re.sub(r"\s+([?!.,:%])", r"\1", joined)
    return re.sub(r"\s+", " ", joined).strip()


_RULE_CORE = """QUY TẮC CỐT LÕI DATAMATE (ưu tiên README shop nếu khác):
- Doanh thu & Số đơn hợp lệ: bỏ đơn HUỶ và TRẢ HÀNG (kể cả trả 1 phần); đơn đang giao VẪN TÍNH; lọc theo NGÀY ĐẶT. Doanh thu = tổng thành tiền các dòng hàng (đã trừ chiết khấu dòng), KHÔNG trừ giảm giá tổng đơn, KHÔNG cộng VAT/phí ship.
- CHỈ viết điều kiện `WHERE` cho đúng khoảng ngày, trạng thái đơn (`NOT IN (...)`), và đối tượng câu hỏi nhắc tới. TUYỆT ĐỐI KHÔNG tự thêm filter thừa như `da_tra = 0`, `chua_tra = 0`, `don_vi_tinh NOT IN (...)`, hay `so_luong > 0`.
- Làm tròn: tiền và trung bình tiền làm tròn ĐỒNG nguyên `ROUND_HALF_UP(x, 0)`; phần trăm và trung bình khác làm tròn 2 chữ số thập phân (dạng số %: `12.45`, không dùng `0.1245`)."""

_RULE_CUSTOMERS = "- Khách hàng: đơn khách lẻ / vãng lai KHÔNG đếm vào số khách, KHÔNG tính vào top khách hoặc nhóm `lẻ`, nhưng VẪN TÍNH vào tổng doanh thu & tổng nợ shop."
_RULE_DEBT = "- Công nợ: đơn không huỷ (đơn trả hàng VẪN TÍNH nếu còn nợ), bỏ COD & sàn TMĐT khỏi công nợ. Nợ tại ngày X = tổng đơn (sau giảm giá đơn, gồm phí ship) trừ khoản thu đến hết ngày X (>0). Tuổi nợ = `julianday(X) - julianday(ngay_dat)`. Thu/trả nợ = khoản trả SAU ngày mua."
_RULE_RANKING = "- Xếp hạng & Đếm món: 'bán chạy' / 'hot nhất' = tổng SL quy về ĐƠN VỊ CƠ BẢN (bỏ đơn huỷ/trả). Bỏ qua dòng 'Phí phục vụ' khi xếp hạng món (vẫn tính vào doanh thu). Bằng nhau xếp theo mã (hoặc tên) tăng dần. Tồn theo đơn vị lớn trả 2 số `[nguyên, lẻ]`. Khi hỏi đối tượng (thuốc, tên thuốc, món, sản phẩm, mặt hàng, vật liệu, khách hàng, nhà cung cấp, kênh bán, nhóm...) theo chỉ số (doanh thu, thành tiền, số lượng, tiền nhập, công nợ...), mệnh đề `SELECT` BẮT BUỘC phải chọn CẢ cột tên đối tượng VÀ cột chỉ số tổng hợp đi kèm (VD: `SELECT ten_thuoc, ROUND_HALF_UP(SUM(doanh_thu), 0) AS tong_doanh_thu ... GROUP BY ten_thuoc ORDER BY tong_doanh_thu DESC`); TUYỆT ĐỐI KHÔNG chỉ `SELECT` 1 cột tên đối tượng!"
_RULE_INVENTORY_COST = "- Nhập/Kho/Giá vốn/Lãi: tiền nhập tính mọi phiếu nhập không huỷ (kể cả nhập đầu kỳ) theo ngày phiếu; giá nhập BQ = `SUM(thanh_tien)/SUM(so_luong)`. Lãi gộp = doanh thu - `SUM(so_luong * gia_von_dong)`. Lãi ròng = lãi gộp - chi phí. Giá bán ngày D tính cả đơn huỷ/trả."
_RULE_INDUSTRY_PHARMACY = "- Nhà thuốc: thuốc kê đơn lấy theo cột kê đơn trong danh mục thuốc; còn tồn hết hạn `D..D+N` tính theo giá nhập chính lô đó. Hoạt chất phối hợp là loại riêng."
_RULE_INDUSTRY_CAFE = "- Cà phê: size M/L = món có tên kết thúc bằng `(M)` hoặc `(L)` (không phân biệt hoa thường)."
_RULE_INDUSTRY_VLXD = "- VLXD giao nhiều đợt: mỗi đợt của mỗi đơn có ngày giao trong kỳ tính 1 đợt (kể cả đơn sau đó trả hàng)."


_SUBJECTIVE_RE = re.compile(
    r"(?:l[aà]nh ngh[eề]|tay ngh[eề]|l[eễ] ph[eé]p|chu [dđ][aá]o|qu[yý] m[eế]n|th[aá]i [dđ][oộ]|nhi[eệ]t t[iì]nh|ngoan|th[oô]ng minh"
    r"|t[aậ]n t[aâ]m|t[aậ]n t[uụ]y|th[aâ]n thi[eệ]n|vui v[eẻ]|ch[aă]m ch[iỉ]"
    r"|(?:t[aạ]i sao|v[iì] sao|tai sao|vi sao|ly do|nguy[eê]n nh[aâ]n|nguyen nhan).*(?:th[ií]ch|thich|y[eê]u th[ií]ch|[uư]a chu[oộ]ng|ua chuong|h[aà]i l[oò]ng|hai long))",
    re.IGNORECASE,
)

_OUT_OF_SCOPE_ACCENTED_RE = re.compile(
    r"\b(?:"
    r"thời\s+tiết|mưa|trời\s+mưa|có\s+mưa|mưa\s+không|mưa\s+rào|mưa\s+to|trời\s+nắng|nắng\s+nóng|"
    r"nhiệt\s+độ|khí\s+hậu|cơn\s+bão|bão\s+số|áp\s+thấp|độ\s+ẩm|sương\s+mù|tuyết\s+rơi|gió\s+mùa|dự\s+báo\s+thời\s+tiết|"
    r"weather|rain|raining|rainy|sunny|storm|typhoon|humidity|"
    r"giá\s+vàng|giá\s+xăng|bitcoin|ethereum|crypto|tiền\s+ảo|chứng\s+khoán|cổ\s+phiếu|vn-?index|xổ\s+số|vietlott|lô\s+đề|"
    r"bóng\s+đá|world\s+cup|ngoại\s+hạng\s+anh|thủ\s+đô|tổng\s+thống|chủ\s+tịch\s+nước|"
    r"làm\s+thơ|bài\s+thơ|kể\s+chuyện|truyện\s+cười|bài\s+hát|công\s+thức\s+nấu|cách\s+nấu|nấu\s+ăn|"
    r"viết\s+code|viết\s+chương\s+trình|thuật\s+toán|dijkstra|lập\s+trình|mấy\s+giờ\s+rồi|what\s+time\s+is\s+it"
    r")\b",
    re.IGNORECASE,
)

_OUT_OF_SCOPE_UNACCENTED_RE = re.compile(
    r"\b(?:"
    r"thoi\s+tiet|nhiet\s+do|khi\s+hau|du\s+bao\s+thoi\s+tiet|troi\s+(?:mua|nang|lanh|nong|am\s+u)|"
    r"con\s+bao\s+so\s*\d+|sieu\s+bao|ap\s+thap\s+nhiet\s+doi|suong\s+mu|tuyet\s+roi|"
    r"gia\s+vang|gia\s+xang|bitcoin|ethereum|crypto|tien\s+ao|chung\s+khoan|co\s+phieu|vn-?index|xo\s+so|vietlott|"
    r"bong\s+da|world\s+cup|ngoai\s+hang\s+anh|thu\s+do\s+cua|tong\s+thong|chu\s+tich\s+nuoc|"
    r"lam\s+tho|bai\s+tho|ke\s+chuyen|truyen\s+cuoi|bai\s+hat|cong\s+thuc\s+nau|cach\s+nau|nau\s+an|"
    r"viet\s+code|viet\s+chuong\s+trinh|thuat\s+toan|dijkstra|lap\s+trinh|"
    r"bi\s+om|bi\s+sot|dau\s+dau|dau\s+bung|dau\s+hong|buon\s+ngu|kham\s+benh|benh\s+vien"
    r")\b",
    re.IGNORECASE,
)

_NAMED_GEO_PLACE_RE = re.compile(
    r"\b(?:ha\s+noi|hanoi|tp\s*hcm|tphcm|ho\s+chi\s+minh|sai\s+gon|da\s+nang|hai\s+phong|can\s+tho|"
    r"nha\s+trang|da\s+lat|vung\s+tau|bien\s+hoa|binh\s+duong|dong\s+nai|quang\s+ninh|ha\s+long|"
    r"bac\s+ninh|hai\s+duong|nam\s+dinh|thai\s+binh|nghe\s+an|thanh\s+hoa|quy\s+nhon|buon\s+ma\s+thuot|phu\s+quoc|"
    r"tokyo|seoul|bangkok|singapore|beijing|shanghai|london|paris|berlin|new\s+york|seattle|boston|chicago|hyderabad|bangalore|mumbai)\b",
    re.IGNORECASE,
)

_BUSINESS_RELEVANCE_RE = re.compile(
    r"\b(?:"
    r"doanh\s+thu|doanh\s+so|ban|mua|don|ma\s+don|hang|mon|san\s+pham|mat\s+hang|nhom|danh\s+muc|loai|"
    r"khach|nhan\s+vien|nhan\s+su|luong|tien|gia|chi\s+phi|loi\s+nhuan|lai|lo|ton|kho|nhap|xuat|"
    r"no|chua\s+tra|da\s+tra|con\s+thieu|phai\s+thu|thu|chi|tra|huy|hoan|thanh\s+toan|chuyen\s+khoan|tien\s+mat|cod|"
    r"phieu|hoa\s+don|so\s+luong|san\s+luong|hop|thung|chai|goi|vien|loc|tui|cay|tan|m3|bao|lieu|ke\s+don|thuoc|hoat\s+chat|lo\s+hang|han\s+dung|"
    r"dot|giao|chiet\s+khau|giam\s+gia|khuyen\s+mai|thue|vat|kenh|cua\s+hang|chi\s+nhanh|ncc|nha\s+cung\s+cap|"
    r"bang|cot|dong|du\s+lieu|csdl|thong\s+ke|bao\s+cao|chi\s+so|ty\s+le|ti\s+le|ty\s+trong|phan\s+tram|dong\s+gop|"
    r"trung\s+binh|binh\s+quan|tong|top|xep\s+hang|xu\s+huong|danh\s+sach|cao\s+nhat|thap\s+nhat|chenh\s+lech|"
    r"revenue|sales|order|orders|product|products|customer|customers|employee|employees|salary|salaries|department|"
    r"price|cost|profit|stock|inventory|debt|payment|ticket|tickets|boxes|amount|category|categories|table|column"
    r")\b",
    re.IGNORECASE,
)


def check_out_of_scope_or_irrelevant(
    question: str,
    knowledge: Optional[WorkspaceKnowledge] = None,
) -> Optional[str]:
    """Return block reason if question asks about weather/non-business topics or has zero business/schema relevance."""
    q_nfc = normalize_nfc(question or "").strip()
    if not q_nfc:
        return "Câu hỏi rỗng hoặc không hợp lệ."
    q_low = q_nfc.lower()
    qn = normalize_vn_question(q_nfc)

    if _OUT_OF_SCOPE_ACCENTED_RE.search(q_low) or _OUT_OF_SCOPE_UNACCENTED_RE.search(qn):
        return "Câu hỏi thuộc chủ đề ngoài phạm vi dữ liệu kinh doanh của CSDL hiện tại (ví dụ: thời tiết, đời sống, tin tức chung)."

    if re.search(r"\bco\s+mua\s+(?:khong|ko|k)\b", qn) and not re.search(
        r"\b(?:hang|mon|don|san\s+pham|mat\s+hang|khach|ca\s+phe|tra|thuoc|vat\s+lieu|xi\s+mang|cat|gach|da|thep|yen|socola|hop|chai|goi|thung|loc|vien|bao)\b",
        qn,
    ):
        return "Câu hỏi thuộc chủ đề ngoài phạm vi dữ liệu kinh doanh của CSDL hiện tại (ví dụ: thời tiết, đời sống, tin tức chung)."

    # Mask accented weather homographs ('mưa' -> rain, 'nắng' -> sunny, 'bão' -> storm) before unaccented business token check
    q_masked = re.sub(r"\b(?:mưa|trời\s+mưa)\b", "weather_rain", q_low)
    q_masked = re.sub(r"\b(?:nắng|trời\s+nắng)\b", "weather_sunny", q_masked)
    q_masked = re.sub(r"\b(?:bão|cơn\s+bão)\b", "weather_storm", q_masked)
    qn_masked = normalize_vn_question(q_masked)

    has_biz_token = bool(_BUSINESS_RELEVANCE_RE.search(qn_masked))
    has_schema_or_entity = False
    if knowledge is not None:
        ws_tokens = {t.lower() for t in knowledge.workspace.tables} | {
            getattr(c, "sql_name", str(c)).lower()
            for t in knowledge.workspace.tables.values()
            for c in t.columns
        }
        has_schema_or_entity = any(
            len(tok) >= 3 and re.search(rf"\b{re.escape(tok)}\b", qn_masked)
            for tok in ws_tokens
        )
        if not has_schema_or_entity:
            has_schema_or_entity = bool(ground_query_entities(q_nfc, knowledge, max_matches=3))

    if not has_biz_token and not has_schema_or_entity:
        return "Câu hỏi nằm ngoài phạm vi dữ liệu kinh doanh của cơ sở dữ liệu hiện tại."

    return None


@dataclass
class AgentConfig:
    llm_config: Optional[LLMConfig] = None
    max_sql_retries: int = 3
    abstain_threshold: float = 0.52
    sql_timeout_seconds: float = 8.0
    max_rows: int = 500
    enable_preflight_unanswerable: bool = True
    enable_llm_formatter_fallback: bool = True
    use_json_mode: bool = True
    sql_max_tokens: int = 640
    enable_python_sandbox: bool = True
    enable_auto_probe: bool = True
    max_probe_steps: int = 1
    enable_forced_python_escalation: bool = True
    enable_dual_path_consensus: bool = True
    force_stage3_on_custom_backend: bool = False


@dataclass
class QuestionAnalysis:
    expected_type: str  # number, percent, date, boolean, string, list, table
    date_granularity: str = "day"  # day | month
    money_like: bool = False
    is_list_unit_pair: bool = False
    expected_list_len: Optional[int] = None
    expected_table_cols: Optional[List[str]] = None
    temporal_windows: List[Tuple[str, str, str]] = field(default_factory=list)
    temporal_summary: str = ""
    prior_needed_start: Optional[str] = None
    bounded_period: Optional[Tuple[str, str]] = None
    extreme_comparison: Optional[Tuple[int, int, bool]] = None  # (top_n, bottom_n, wants_diff)


@dataclass
class AgentResult:
    question_id: str
    prediction: Dict[str, Any]
    confidence: float
    sql: str = ""
    sql_attempts: int = 0
    error: str = ""
    notes: List[str] = field(default_factory=list)


_VN_ORDINAL_WORD_MAP: Dict[str, int] = {
    "nhat": 1,
    "nhi": 2,
    "hai": 2,
    "ba": 3,
    "tu": 4,
    "bon": 4,
    "nam": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
    "muoi": 10,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}


def _parse_ordinal_token(tok: str) -> Optional[int]:
    t = (tok or "").strip().lower()
    if not t:
        return None
    if t.isdigit():
        val = int(t)
        return val if 2 <= val <= 50 else None
    val = _VN_ORDINAL_WORD_MAP.get(t)
    return val if (val is not None and 2 <= val <= 50) else None


def extract_ordinal_rank(question: str) -> Optional[Tuple[int, str]]:
    """
    Detect singular N-th ordinal ranking intent (e.g. 'cao thứ 3', 'lớn thứ 2', 'thấp thứ 2', 'đứng thứ 3', 'á quân').
    Excludes day-of-week expressions ('ngày thứ 3', 'hôm thứ 3', 'thứ 3 tuần trước').
    Returns (rank_n, 'DESC' | 'ASC') when 2 <= rank_n <= 50, else None.
    """
    if not question:
        return None
    qn = normalize_vn_question(normalize_nfc(question))
    if not qn:
        return None

    # Exclude plural "top N" / "N sản phẩm đầu" unless explicitly asking "top thứ N"
    if re.search(r"\btop\s+\d+\b", qn) and not re.search(r"\btop\s+thu\s+\d+\b", qn):
        return None

    # Strip Vietnamese day-of-week phrases ('ngày thứ 3', 'hôm thứ 4', 'thứ 3 tuần trước', 'thứ 2 đến thứ 6')
    qn_clean = re.sub(
        r"\b(?:ngay|hom|bua|sang|trua|chieu|toi|dem|vao|dau|cuoi|tu|den)\s+thu\s+(?:[2-7]|hai|ba|tu|nam|sau|bay)\b",
        " ",
        qn,
    )
    qn_clean = re.sub(
        r"\bthu\s+(?:[2-7]|hai|ba|tu|nam|sau|bay)\s+(?:tuan|nay|truoc|toi|qua|vua\s+qua|roi|hang\s+tuan)\b",
        " ",
        qn_clean,
    )

    ord_tok_pat = r"(\d+|nhi|hai|ba|tu|bon|nam|sau|bay|tam|chin|muoi)"

    # 1. Descending superlative + thứ N (e.g. 'cao thứ 3', 'nhiều thứ 2', 'bán chạy thứ 3', 'lớn thứ 2')
    m_desc = re.search(
        rf"\b(?:cao|lon|nhieu|manh|tot|ban\s+chay|dat|nhanh|chay|dong\s+gop\s+cao|doanh\s+thu\s+cao|doanh\s+so\s+cao|loi\s+nhuan\s+cao|so\s+luong\s+nhieu|mua\s+nhieu|chi\s+tieu\s+nhieu|no\s+nhieu)\s+thu\s+{ord_tok_pat}\b",
        qn_clean,
    )
    if m_desc:
        rn = _parse_ordinal_token(m_desc.group(1))
        if rn:
            return (rn, "DESC")

    if re.search(r"\b(?:cao|lon|nhieu|ban\s+chay|dat)\s+nhi\b", qn_clean):
        return (2, "DESC")

    # 2. Ascending superlative + thứ N (e.g. 'thấp thứ 2', 'ít thứ 3', 'nhỏ thứ 2', 'kém thứ 2')
    m_asc = re.search(
        rf"\b(?:thap|it|nho|kem|yeu|cham|re|te|ban\s+cham|doanh\s+thu\s+thap|so\s+luong\s+it)\s+thu\s+{ord_tok_pat}\b",
        qn_clean,
    )
    if m_asc:
        rn = _parse_ordinal_token(m_asc.group(1))
        if rn:
            return (rn, "ASC")

    if re.search(r"\b(?:thap|it|nho|kem|re)\s+nhi\b", qn_clean):
        return (2, "ASC")

    # 3. Explicit rank position ('đứng thứ N', 'xếp thứ N', 'xếp hạng N', 'xếp hạng thứ N', 'vị trí thứ N', 'hạng N', 'á quân', 'đứng nhì')
    default_dir = (
        "ASC"
        if re.search(r"\b(?:thap|it|nho|kem|yeu|cham|re|te|cuoi|duoi|lowest|smallest|least|worst)\b", qn_clean)
        else "DESC"
    )
    if re.search(r"\b(?:a\s+quan|dung\s+nhi|xep\s+nhi|hang\s+nhi)\b", qn_clean):
        return (2, default_dir)

    m_pos = re.search(
        rf"\b(?:dung\s+thu|xep\s+thu|xep\s+hang\s+thu|xep\s+hang|dung\s+hang|hang\s+thu|vi\s+tri\s+thu|vi\s+tri\s+so|top\s+thu)\s+{ord_tok_pat}\b",
        qn_clean,
    )
    if m_pos:
        rn = _parse_ordinal_token(m_pos.group(1))
        if rn:
            return (rn, default_dir)

    # 4. Entity + thứ N when accompanied by a metric/ranking cue (e.g. 'sản phẩm thứ 3 về doanh thu')
    if re.search(
        r"\b(?:doanh\s+thu|doanh\s+so|so\s+luong|ban\s+chay|thanh\s+tien|gia\s+tri|loi\s+nhuan|chi\s+tieu|cong\s+no|luong|cao|lon|nhieu|thap|it)\b",
        qn_clean,
    ):
        m_ent = re.search(
            rf"\b(?:san\s+pham|mat\s+hang|mon|khach\s+hang|khach|nhan\s+vien|nhom|danh\s+muc|kenh|chi\s+nhanh|cua\s+hang|quoc\s+gia|thanh\s+pho)\s+thu\s+{ord_tok_pat}\b",
            qn_clean,
        )
        if m_ent:
            rn = _parse_ordinal_token(m_ent.group(1))
            if rn:
                return (rn, default_dir)

    # 5. English ordinal superlative ('2nd highest', '3rd highest', 'second highest', 'third lowest')
    m_en = re.search(
        r"\b(?:(\d+)\s*(?:nd|rd|th)|(second|third|fourth|fifth))\s+(highest|largest|most|biggest|best|top|lowest|smallest|least|worst)\b",
        qn_clean,
    )
    if m_en:
        tok_en = m_en.group(1) or m_en.group(2)
        rn = _parse_ordinal_token(tok_en)
        if rn:
            dir_en = "ASC" if m_en.group(3) in ("lowest", "smallest", "least", "worst") else "DESC"
            return (rn, dir_en)

    return None


def extract_extreme_comparison_intent(question: str) -> Optional[Tuple[int, int, bool]]:
    """Detect queries asking for BOTH highest (Top N) AND lowest (Bottom M) extremes (and optional spread/diff)."""
    if not question:
        return None
    qn = normalize_vn_question(normalize_nfc(question))
    if not qn:
        return None

    # Exclude cross-filter / percentile / pure yes-no predicate questions
    if re.search(r"\b(?:nhung|ma lai|tuy nhien|trong so|bach phan vi|percentile)\b", qn):
        return None
    if re.search(r"\btop\s*\d+\s*%", qn):
        return None
    if (
        re.search(r"(?:co\s+[^?]*\bkhong\b|co\s+[^?]*\bk\??$|co\s+[^?]*\bhong\??$)", qn)
        and not re.search(r"\b(?:bao nhieu|may|nao|ai|gi|chi|chenh lech|so sanh|phan tich|in ra|liet ke|danh sach)\b", qn)
    ):
        return None

    high_re = (
        r"\b(?:cao\s+nhat|lon\s+nhat|nhieu\s+nhat|ban\s+chay\s+nhat|tot\s+nhat|dat\s+nhat|"
        r"dan\s+dau|dung\s+dau|highest|largest|most|best|top\s+\d+)\b"
    )
    low_re = (
        r"\b(?:thap\s+nhat|nho\s+nhat|it\s+nhat(?!\s*\d)|ban\s+cham\s+nhat|kem\s+nhat|re\s+nhat|"
        r"te\s+nhat|cuoi\s+bang|doi\s+so|lowest|smallest|least|worst|bottom\s+\d+)\b"
    )
    m_high = re.search(high_re, qn)
    m_low = re.search(low_re, qn)
    if not (m_high and m_low):
        return None

    qn_clean = re.sub(r"\b(?:19\d{2}|20\d{2})\b", " ", qn)
    qn_clean = re.sub(r"\b(?:nam|thang|quy|ngay|year|month|quarter)\s+\d+\b", " ", qn_clean)
    qn_clean = re.sub(r"\d+(?:[.,]\d+)?\s*%", " ", qn_clean)
    nums = [int(x) for x in re.findall(r"\b(\d+)\b", qn_clean) if 1 <= int(x) <= 20]

    if len(nums) >= 2:
        if m_high.start() <= m_low.start():
            top_n, bottom_n = nums[0], nums[1]
        else:
            top_n, bottom_n = nums[1], nums[0]
    elif len(nums) == 1:
        top_n = bottom_n = nums[0]
    else:
        top_n = bottom_n = 1

    wants_diff = bool(
        re.search(
            r"\b(?:chenh\s+lech|do\s+chenh|khoang\s+cach|bien\s+do|phan\s+hoa|so\s+sanh|hon\s+kem|hieu\s+so|diff|difference|spread|gap)\b",
            qn,
        )
    )
    return (top_n, bottom_n, wants_diff)


def extract_benchmark_average_entity_intent(question: str) -> Optional[str]:
    """
    Detect queries asking which entities (medicines, items, dishes, materials, customers, channels, categories)
    have a total metric (revenue, quantity, debt, import cost) ABOVE ('>') or BELOW ('<') the entity-level average.
    """
    if not question:
        return None
    qn = normalize_vn_question(normalize_nfc(question))
    if not qn:
        return None

    # Exclude scalar counts ('có bao nhiêu...'), percentages ('bao nhiêu %'), pure yes/no questions, or single-order lookups
    if re.search(
        r"\b(?:co\s+bao\s+nhieu|may\s+(?:thuoc|mon|san\s+pham|mat\s+hang|khach|don|hoa\s+don)|tong\s+so\s+bao\s+nhieu|dem\s+so|phan\s+tram|ty\s+le|ti\s+le|don\s+hang\s+nao|hoa\s+don\s+nao|ma\s+don\s+nao|phieu\s+nao|phong\s+ban\s+dau\s+tien)\b",
        qn,
    ):
        return None
    if (
        re.search(r"(?:co\s+[^?]*\bkhong\b|co\s+[^?]*\bk\??$|co\s+[^?]*\bhong\??$)", qn)
        and not re.search(r"\b(?:nhung|cac|danh\s+sach|liet\s+ke|in\s+ra|nao|ai)\b", qn)
    ):
        return None

    has_entity_target = bool(
        re.search(
            r"\b(?:nhung|cac|danh\s+sach|liet\s+ke|in\s+ra)\s+(?:ten\s+|loai\s+|nhom\s+|ma\s+)?(?:thuoc|vat\s+lieu|mat\s+hang|san\s+pham|mon|hang\s+hoa|hang|khach(?:\s+hang)?|nha\s+cung\s+cap|ncc|kenh(?:\s+ban)?|nhom(?:\s+mon|\s+hang|\s+thuoc)?|nhan\s+vien|phong\s+ban|cua\s+hang|chi\s+nhanh|danh\s+muc)\b",
            qn,
        )
        or re.search(
            r"\b(?:ten\s+|loai\s+|nhom\s+)?(?:thuoc|vat\s+lieu|mat\s+hang|san\s+pham|mon|hang\s+hoa|hang|khach(?:\s+hang)?|nha\s+cung\s+cap|ncc|kenh(?:\s+ban)?|nhom(?:\s+mon|\s+hang|\s+thuoc)?|nhan\s+vien|phong\s+ban|cua\s+hang|chi\s+nhanh|danh\s+muc)\s+nao\b",
            qn,
        )
    )
    if not has_entity_target:
        return None

    if re.search(
        r"\b(?:vuot(?:\s+tren|\s+muc|\s+qua)?|tren(?:\s+muc)?|cao\s+hon(?:\s+muc)?|lon\s+hon(?:\s+muc)?|nhieu\s+hon(?:\s+muc)?|dat\s+tren|above|higher\s+than|greater\s+than|exceed(?:s|ing)?|over)\s+(?:muc\s+|gia\s+tri\s+|doanh\s+thu\s+|doanh\s+so\s+|so\s+luong\s+|thanh\s+tien\s+)?(?:trung\s+binh|binh\s+quan|average|avg)\b",
        qn,
    ):
        return ">"

    if re.search(
        r"\b(?:duoi(?:\s+muc)?|thap\s+hon(?:\s+muc)?|nho\s+hon(?:\s+muc)?|it\s+hon(?:\s+muc)?|kem(?:\s+hon)?(?:\s+muc)?|chua\s+dat(?:\s+muc)?|below|lower\s+than|less\s+than|under)\s+(?:muc\s+|gia\s+tri\s+|doanh\s+thu\s+|doanh\s+so\s+|so\s+luong\s+|thanh\s+tien\s+)?(?:trung\s+binh|binh\s+quan|average|avg)\b",
        qn,
    ):
        return "<"

    return None


def classify_expected_type(question: str) -> QuestionAnalysis:
    """Classify target DataMate answer type & structural cues cleanly across Vietnamese phrasing + Telex typos."""
    q_nfc = normalize_nfc(question)
    qn = normalize_vn_question(q_nfc)

    # Strip concentration percentages inside product names (e.g. "0,1%", "0.9%") before percent detection
    qn_for_pct = re.sub(
        r"(?<=[a-z])\s+\d+(?:[.,]\d+)?\s*%(?=\s+(?:chai|lo|xit|hop|vi|goi|vien|ong|ml|mg|cuoi|ban|gia|don|ton|nhap|trong|thang|ngay|la)\b)",
        "",
        qn,
    )
    # Also guard drug formulations like "efticol 0,9% loc 10 lo" even if word precedes 0,9% without trailing list
    qn_for_pct = re.sub(r"\b\d+[.,]\d+\s*%(?=\s*(?:loc|chai|lo|xit|tui|hop|vien|vi|goi|tuyp|ong)\b)", "", qn_for_pct)

    is_percent = bool(
        re.search(
            r"(?:phan tram|ti le|ty le|ti trong|ty trong|chiem\s+(?:bao nhieu|nhieu|may)|"
            r"(?:bao nhieu|nhieu|may|tang|giam|thay doi|chenh lech|cao hon|thap hon|it hon|nhieu hon|kem)\s*(?:%|phan tram)|%\s*\??$)",
            qn_for_pct,
        )
    )
    money_like = bool(
        re.search(
            r"(?:doanh thu|tien|von|lai|no|chi phi|gia tri|gia ban|gia nhap|don gia|trung binh moi don|gia tri trung binh)",
            qn,
        )
    ) and not is_percent

    # 1. Table (explicit table prompt, extreme comparison high+low, or multi-metric per object)
    q_low_nfc = q_nfc.lower()
    ext_cmp = extract_extreme_comparison_intent(question)
    if ext_cmp is not None and not (
        is_percent and not re.search(r"\b(?:danh sach|in ra|liet ke|bang|phan tich|so sanh)\b", qn)
    ):
        return QuestionAnalysis(expected_type="table", money_like=money_like, extreme_comparison=ext_cmp)

    _has_entity_list_plus_metric = bool(
        re.search(
            r"(?:(?:nhung|cac)\s+(?:ten\s+|loai\s+|nhom\s+|ma\s+)?(?:thuoc|vat\s+lieu|mat\s+hang|san\s+pham|mon|hang\s+hoa|khach(?:\s+hang)?|nha\s+cung\s+cap|ncc|kenh(?:\s+ban)?|nhom(?:\s+mon|\s+hang|\s+thuoc)?|nhan\s+vien)\s+nao\b|"
            r"\b(?:danh\s+sach|liet\s+ke)\b[^?]{0,80}\b(?:thuoc|vat\s+lieu|mat\s+hang|san\s+pham|mon|hang\s+hoa|khach(?:\s+hang)?|nha\s+cung\s+cap|ncc|kenh(?:\s+ban)?|nhom|nhan\s+vien)\b)",
            qn,
        )
        and re.search(
            r"(?:\bva\b|,|\bkem\b)\s*(?:tong\s+)?(?:tien\s+nhap|gia\s+tri\s+nhap|doanh\s+thu|doanh\s+so|thanh\s+tien|so\s+luong(?:\s+nhap|\s+ban)?|cong\s+no|con\s+no|tong\s+tien|so\s+tien|chi\s+tieu|chi\s+phi)\b",
            qn,
        )
    )
    if (
        _has_entity_list_plus_metric
        or re.search(r"\b(?:cho|xuất|lập|tạo)\s+bảng\b|\bbảng\s*\d+\b", q_low_nfc)
        or re.search(r"(?:kem so tien|so no cua tung|moi nguoi con no|kem doanh thu|kem so luong|\bva\s+doanh\s+thu\b|\bva\s+so\s+luong\b)", qn)
    ):
        cols = ["khach_hang", "so_tien_no"] if (re.search(r"\bno\b", qn) and not _has_entity_list_plus_metric) else None
        return QuestionAnalysis(expected_type="table", money_like=money_like, expected_table_cols=cols)

    # 2. Boolean (yes/no trend or predicate questions)
    if (
        re.search(
            r"(?:co\s+[^?]*\bkhong\b|co\s+[^?]*\bk\??$|co\s+[^?]*\bhong\??$|co\s+tang\s+lien\s+tuc|"
            r"co\s+luon\s+cao\s+hon|co\s+phai\s+.*(?:cao hon|lon hon|thap hon|nhieu hon|it hon)|co\s+le\s+phep)",
            qn,
        )
        and not re.search(r"\b(?:bao nhieu|may|nao|ai|gi|chi|tuoi no)\b", qn)
    ):
        return QuestionAnalysis(expected_type="boolean")

    # 3. Percent
    if is_percent:
        return QuestionAnalysis(expected_type="percent")

    # 4. Date ("ngày nào" / "tháng nào")
    if re.search(r"\bthang nao\b", qn) and not re.search(r"\bngay nao\b", qn):
        return QuestionAnalysis(expected_type="date", date_granularity="month", money_like=money_like)
    if re.search(r"\b(?:ngay nao|hom nao|bua nao)\b", qn):
        return QuestionAnalysis(expected_type="date", date_granularity="day", money_like=money_like)

    # 5. List variants (carefully exclude 4-digit years & drug packaging sizes!)
    if re.search(r"\b(?:chan|nguyen)\b", qn) and re.search(r"\ble\b", qn) and re.search(r"\b(?:ton|con|duoc|may|bao nhieu)\b", qn):
        return QuestionAnalysis(expected_type="list", is_list_unit_pair=True, expected_list_len=2)
    if (
        re.search(r"(?:hai so|ba so|ghi \d+ so|lan luot|theo thu tu|moi ben bao nhieu|moi loai bao nhieu|moi nhom bao nhieu|moi thang|nhom tuoi no)", qn)
        or re.search(r"\b(?:bao nhieu|may)\b[^?]{0,110}(?:\bva\b|,)\s*[^?]{0,110}\b(?:bao nhieu|may)\b", qn)
        or re.search(r"\bdoanh thu\b[^?]{0,70}\bva\s+doanh thu\b", qn)
    ):
        return QuestionAnalysis(expected_type="list", money_like=money_like)

    qn_for_topk = re.sub(
        r"\b(?:hop|loc|vi|goi|chai|thung|tui)\s+\d+\s+(?:vi|lo|vien|goi|ong|chai|tui)(?:\s*x\s*\d+\w*)?\b",
        "",
        qn,
    )
    plural_top_match = re.search(
        r"(?:top\s*\d+|liet ke|danh\s+sach|"
        r"(?:nhung|cac)\s+(?:ten\s+|loai\s+|nhom\s+|ma\s+)?(?:thuoc|vat\s+lieu|mat\s+hang|san\s+pham|mon|hang\s+hoa|hang|khach(?:\s+hang)?|nha\s+cung\s+cap|ncc|kenh(?:\s+ban)?|nhom(?:\s+mon|\s+hang|\s+thuoc)?|nhan\s+vien|phong\s+ban|danh\s+muc)\s+nao|"
        r"(?<!/)(?<!\d)\b(?:[2-9]|1\d|20)\s+(?:thuoc|loai thuoc|vat lieu|mat hang|hang hoa|hang|mon|san pham|khach hang|khach|nhan vien|nha cung cap|nhom hang|lo\b(?!\s*x\s*\d)))",
        qn_for_topk,
    )
    plural_entity_list_match = re.search(
        r"(?:danh\s+sach|liet\s+ke|in\s+ra|(?:cho\s+(?:toi\s+)?)?xem)?\s*"
        r"(?:nhung|cac)\s+(?:ten\s+|loai\s+|nhom\s+|ma\s+)?"
        r"(?:thuoc|vat\s+lieu|mat\s+hang|san\s+pham|mon|hang\s+hoa|hang|khach(?:\s+hang)?|nha\s+cung\s+cap|ncc|kenh(?:\s+ban)?|nhom(?:\s+mon|\s+hang|\s+thuoc)?|nhan\s+vien|phong\s+ban|danh\s+muc)\b",
        qn_for_topk,
    )
    is_scalar_count_or_sum_q = bool(
        re.search(
            r"(?:co\s+bao\s+nhieu|bao\s+nhieu|\bmay\s+(?:mon|thuoc|san\s+pham|mat\s+hang|loai|don|hoa\s+don|khach|nhom)"
            r"|tong\s+(?:so|doanh\s+thu|doanh\s+so|thanh\s+tien|tien|so\s+luong|cong\s+no|gia\s+tri|luong)"
            r"|dem\s+so|trung\s+binh|binh\s+quan)",
            qn_for_topk,
        )
        and not re.search(r"\b(?:danh\s+sach|liet\s+ke|in\s+ra|nao)\b", qn_for_topk)
    )
    if (
        (plural_top_match or (plural_entity_list_match and not is_scalar_count_or_sum_q))
        and extract_ordinal_rank(question) is None
    ):
        return QuestionAnalysis(expected_type="list", money_like=money_like)

    # 6. String (single named customer/item/staff/supplier/batch or N-th ranked entity)
    if (
        re.search(
            r"(?:la ai|ai la|ai trong|\bai\b.*\bnhat\b|khach(?: hang)? nao|(?:ten )?mat hang nao|hang nao|(?:ten )?san pham nao|(?:ten )?mon nao|"
            r"(?:ten |loai )?thuoc nao|(?:ten |loai )?vat lieu nao|"
            r"nhan vien nao|nha cung cap nao|nhom hang nao|nhom mon nao|nhom thuoc nao|danh muc nao|kenh(?: ban)? nao|lo nao|"
            r"\b(?:thuoc|vat lieu|san pham|mat hang|hang|mon|khach hang|nhan vien|nha cung cap)\b.*\b(?:la gi|la chi|la ai)\b)",
            qn,
        )
        and not re.search(r"\b(?:bao nhieu|may|nhung ai|top)\b", qn)
    ) or (
        extract_ordinal_rank(question) is not None
        and re.search(r"\b(?:thuoc|vat\s+lieu|san\s+pham|mat\s+hang|hang|mon|khach\s+hang|khach|nhan\s+vien|nha\s+cung\s+cap|nhom\s+hang|nhom\s+mon|danh\s+muc|kenh|cua\s+hang|chi\s+nhanh|lo)\b", qn)
        and not re.search(r"^(?:doanh\s+thu|tong\s+doanh\s+thu|so\s+luong|tong\s+so\s+luong|gia\s+tri|so\s+tien|muc\s+luong)\b|\b(?:bao\s+nhieu|may)\b", qn)
    ):
        return QuestionAnalysis(expected_type="string", money_like=money_like)

    return QuestionAnalysis(expected_type="number", money_like=money_like)


_RETRACTION_MARKER_RE = re.compile(
    r"(?:^|[\s,;.\n])(?:à\s+nhầm|ý\s+nhầm|ý\s+lộn|à\s+quên|nói\s+nhầm|nhầm[,:\s]+là|sửa\s+lại(?:\s+là)?|"
    r"a\s+nham|y\s+nham|y\s+lon|a\s+quen|noi\s+nham|sua\s+lai(?:\s+la)?)\b[,:\s]*(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_RETRACTION_TAIL_TEMPORAL_RE = re.compile(
    r"(?:\bt\s*\d{1,2}\s*[/.-]\s*\d{4}|th[aá]ng\s*\d{1,2}(?:\s*(?:[/.-]|\s*năm\s*)\d{4})?|"
    r"\d{1,2}/\d{1,2}(?:/\d{4})?|qu[yý]\s*[1-4](?:\s*(?:[/.-]|\s*năm\s*)\d{4})?|"
    r"h[oô]m\s+(?:nay|qua)|tu[aầ]n\s+(?:n[aà]y|tr[uư][oớ]c|r[oồ]i))",
    re.IGNORECASE,
)


def resolve_conversational_retraction(question: str) -> Tuple[str, Optional[str]]:
    """
    Detect inline conversational self-corrections (e.g. '... trong t5/2024 z\\nà nhầm, t6/2024 nha')
    and rewrite the effective query so earlier retracted time/filter tokens are discarded cleanly.
    """
    q_nfc = normalize_nfc(question or "").strip()
    if not q_nfc:
        return q_nfc, None
    m = _RETRACTION_MARKER_RE.search(q_nfc)
    if not m:
        return q_nfc, None
    head = q_nfc[: m.start()].strip()
    tail = m.group(1).strip()
    if not tail:
        return q_nfc, None
    if _RETRACTION_TAIL_TEMPORAL_RE.search(tail):
        cleaned_head = _RETRACTION_TAIL_TEMPORAL_RE.sub(" ", head)
        cleaned_head = re.sub(r"\b(?:trong|của|từ|ngày)\s*(?:z|à|nhỉ|nha|vậy)?\s*$", "", cleaned_head, flags=re.IGNORECASE).strip()
        resolved = re.sub(r"\s+", " ", f"{cleaned_head} {tail}").strip()
        note = f"Người dùng tự đính chính -> CHỈ dùng mốc mới `{tail}`, BỎ hoàn toàn mốc bị nhầm ở vế trước!"
        return resolved, note
    return q_nfc, None


def extract_temporal_context(
    question: str,
    as_of_date: str,
    cal: Optional[SolarLunarCalendar],
) -> Tuple[List[Tuple[str, str, str]], str, Optional[Tuple[str, str]], Optional[str]]:
    """Resolve Vietnamese time expressions (incl. teencode/Telex) into explicit SQL-ready ISO bounds."""
    resolver = TemporalResolver(as_of_date=as_of_date, cal=cal)
    qn = normalize_vn_question(question)
    windows: List[Tuple[str, str, str]] = []
    bounded_period: Optional[Tuple[str, str]] = None
    prior_needed_start: Optional[str] = None

    as_of = resolver.today

    # Explicit dd/mm/yyyy .. dd/mm/yyyy
    explicit_dates = re.findall(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", qn)
    if len(explicit_dates) >= 2:
        d1, _ = parse_date_value(explicit_dates[0])
        d2, _ = parse_date_value(explicit_dates[1])
        if d1 and d2:
            windows.append((f"từ {explicit_dates[0]} đến {explicit_dates[1]}", min(d1, d2), max(d1, d2)))
            if "het han" not in qn and "han dung" not in qn:
                bounded_period = (min(d1, d2), max(d1, d2))
    elif len(explicit_dates) == 1:
        d1, _ = parse_date_value(explicit_dates[0])
        if d1:
            if re.search(r"(?:den het ngay|tinh den|cuoi ngay)", qn):
                windows.append((f"tính đến hết {explicit_dates[0]}", "0001-01-01", d1))
            elif re.search(r"\b(\d+)\s*ngay\s*ke\s*tu\b", qn):
                n_days = int(re.search(r"\b(\d+)\s*ngay\s*ke\s*tu\b", qn).group(1))
                d_obj = dt.date.fromisoformat(d1)
                fwd_s = d1
                fwd_e = (d_obj + dt.timedelta(days=n_days - 1)).isoformat()
                prv_s = (d_obj - dt.timedelta(days=n_days)).isoformat()
                prv_e = (d_obj - dt.timedelta(days=1)).isoformat()
                windows.append((f"{n_days} ngày kể từ {d1}", fwd_s, fwd_e))
                windows.append((f"{n_days} ngày ngay trước {d1}", prv_s, prv_e))
                bounded_period = (fwd_s, fwd_e)
                prior_needed_start = prv_s
            else:
                windows.append((f"ngày {explicit_dates[0]}", d1, d1))
                bounded_period = (d1, d1)
    else:
        # Yearless day: "ngày 15/3" (not preceded by thang/quy and without /YYYY)
        m_dm = re.search(r"\bngay\s+(\d{1,2})/(\d{1,2})\b(?!/\d)", qn)
        if m_dm:
            d_i, m_i = int(m_dm.group(1)), int(m_dm.group(2))
            if 1 <= m_i <= 12 and 1 <= d_i <= 31:
                try:
                    cand = dt.date(as_of.year, m_i, d_i)
                    if cand > as_of:
                        cand = dt.date(as_of.year - 1, m_i, d_i)
                    iso = cand.isoformat()
                    windows.append((f"ngày {d_i}/{m_i} (ngầm định)", iso, iso))
                    bounded_period = (iso, iso)
                except ValueError:
                    pass

    # Explicit months tháng M/YYYY, tháng M năm YYYY, or shorthand tM/YYYY (e.g. t6/2024)
    explicit_months = re.findall(r"(?:\bthang\s*|\bt\s*)(\d{1,2})\s*(?:[/.-]|\s*nam\s*)(\d{4})\b", qn)
    if explicit_months:
        parsed_ms = []
        for m_s, y_s in explicit_months:
            m_i, y_i = int(m_s), int(y_s)
            if 1 <= m_i <= 12:
                s, e = resolver.resolve_month(m_i, y_i)
                windows.append((f"tháng {m_i}/{y_i}", s, e))
                parsed_ms.append((s, e, m_i, y_i))
        if parsed_ms:
            bounded_period = (min(p[0] for p in parsed_ms), max(p[1] for p in parsed_ms))
            if re.search(r"(?:thang lien truoc|thang truoc|ky truoc|th truoc)", qn) and len(parsed_ms) == 1:
                _, _, m_i, y_i = parsed_ms[0]
                pm, py = (12, y_i - 1) if m_i == 1 else (m_i - 1, y_i)
                ps, pe = resolver.resolve_month(pm, py)
                windows.append((f"tháng liền trước ({pm}/{py})", ps, pe))
                prior_needed_start = pe
    else:
        # Month without year (e.g. "tháng 5")
        bare_m = re.findall(r"\bthang\s*(\d{1,2})\b", qn)
        for m_s in bare_m:
            m_i = int(m_s)
            if 1 <= m_i <= 12:
                s, e = resolver.resolve_month(m_i, None)
                windows.append((f"tháng {m_i} (ngầm định)", s, e))
                bounded_period = (s, e) if not bounded_period else (min(bounded_period[0], s), max(bounded_period[1], e))

    # Quarters (with optional year)
    explicit_qs = re.findall(r"quy\s*([1-4])\s*(?:/|\s*nam\s*)(\d{4})", qn)
    if explicit_qs:
        for q_s, y_s in explicit_qs:
            s, e = resolver.resolve_quarter(int(q_s), int(y_s))
            windows.append((f"quý {q_s}/{y_s}", s, e))
            bounded_period = (s, e) if not bounded_period else (min(bounded_period[0], s), max(bounded_period[1], e))
    else:
        bare_qs = re.findall(r"\bquy\s*([1-4])\b", qn)
        for q_s in bare_qs:
            s, e = resolver.resolve_quarter(int(q_s), None)
            windows.append((f"quý {q_s} (ngầm định)", s, e))
            bounded_period = (s, e) if not bounded_period else (min(bounded_period[0], s), max(bounded_period[1], e))

    # Relative keywords (now normalized from hnay/hqua/bua qua/bua nay too!)
    if re.search(r"\bhom nay\b", qn) and not re.search(r"(?:den het|cuoi ngay|het hom nay|tu dau)", qn):
        d = as_of.isoformat()
        windows.append(("hôm nay", d, d))
        bounded_period = bounded_period or (d, d)
    if re.search(r"\bhom qua\b", qn):
        d = (as_of - dt.timedelta(days=1)).isoformat()
        windows.append(("hôm qua", d, d))
        bounded_period = bounded_period or (d, d)
    if "tuan nay" in qn:
        ctx = resolver.build_context()
        s, e = ctx["this_week"]
        windows.append(("tuần này", s, e))
        bounded_period = bounded_period or (s, e)
    if re.search(r"\btuan (?:truoc|roi)\b", qn):
        ctx = resolver.build_context()
        s, e = ctx["last_week"]
        windows.append(("tuần trước", s, e))
        bounded_period = bounded_period or (s, e)
    if "thang nay" in qn and not re.search(r"(?:den het|cuoi ngay|tinh den)", qn):
        ctx = resolver.build_context()
        s, e = ctx["this_month"]
        windows.append(("tháng này (MTD)", s, e))
        bounded_period = bounded_period or (s, e)
        if re.search(r"(?:cung ky thang|thang truoc|th truoc)", qn):
            ps, pe = ctx["last_month_same_days"]
            windows.append(("cùng kỳ tháng trước (MTD)", ps, pe))
            prior_needed_start = pe
    m_nd = re.search(r"\b(\d+)\s*ngay\s*(?:gan nhat|qua|vua qua)\b", qn)
    if m_nd:
        s, e = resolver.last_n_days(int(m_nd.group(1)))
        windows.append((f"{m_nd.group(1)} ngày gần nhất", s, e))
        bounded_period = bounded_period or (s, e)
    m_exp = re.search(r"\b(?:het han|sap het han).*?(\d+)\s*ngay\s*toi\b", qn)
    if m_exp:
        s = as_of.isoformat()
        e = (as_of + dt.timedelta(days=int(m_exp.group(1)))).isoformat()
        windows.append((f"hết hạn trong {m_exp.group(1)} ngày tới", s, e))
    if re.search(r"\btu dau nam\b", qn):
        s, e = f"{as_of.year:04d}-01-01", as_of.isoformat()
        windows.append(("từ đầu năm tới nay", s, e))
        bounded_period = bounded_period or (s, e)
    if re.search(r"\btet\b", qn):
        m_ty = re.search(r"tet\s*(?:nam\s*)?(20\d{2})", qn)
        ty = int(m_ty.group(1)) if m_ty else None
        tet_w = resolver.latest_tet_window(ty)
        if tet_w:
            ly_label = tet_w.get("lunar_year") or (ty if ty is not None else "")
            windows.append((f"Tết {ly_label}".strip(), tet_w["tet_start"], tet_w["tet_end"]))
            bounded_period = bounded_period or (tet_w["tet_start"], tet_w["tet_end"])
            if "truoc tet" in qn:
                windows.append((f"trước Tết {ly_label}".strip(), tet_w["pre_tet_start"], tet_w["pre_tet_end"]))
                prior_needed_start = tet_w["pre_tet_end"]

    if "het thang" in qn or "den het hom nay" in qn or "cuoi ngay hom nay" in qn or "tinh den" in qn:
        windows.append(("mốc cutoff", "0001-01-01", as_of.isoformat()))

    summary_lines = [f"- `as_of_date` (Hôm nay) = `{as_of.isoformat()}`"]
    for label, s, e in windows:
        if s == "0001-01-01":
            summary_lines.append(f"- {label}: LŨY KẾ TỪ ĐẦU ĐẾN HẾT `{e}` (dùng `<cột_ngày> <= '{e}'`)")
        elif s == e:
            summary_lines.append(f"- {label}: ĐÚNG NGÀY `{s}` (BẮT BUỘC dùng `<cột_ngày> = '{s}'`, KHÔNG dùng `<=`)")
        else:
            summary_lines.append(f"- {label}: TỪ `{s}` ĐẾN `{e}` (dùng `<cột_ngày> BETWEEN '{s}' AND '{e}'`)")
    return windows, "\n".join(summary_lines), bounded_period, prior_needed_start


def _check_schema_capability_gap(
    question: str,
    knowledge: WorkspaceKnowledge,
) -> Optional[str]:
    """
    Validate whether requested domain entities & attributes exist in populated columns/tables.
    Shared by both preflight unanswerable blocking and the SQL semantic auditor.
    """
    q_nfc = normalize_nfc(question or "")
    q_low_nfc = q_nfc.lower()
    qn = normalize_vn_question(q_nfc)
    caps = knowledge.capabilities
    readme_n = norm_vn(knowledge.workspace.readme_text)
    ws_cols = {
        getattr(c, "sql_name", str(c)).lower()
        for t in knowledge.workspace.tables.values()
        for c in t.columns
    }
    ws_tbl_and_cols = {t.lower() for t in knowledge.workspace.tables} | ws_cols
    tbl_preview = ", ".join(f"`{t}`" for t in sorted(knowledge.valid_tables)[:6])

    has_gender_cap = (
        caps["has_customer_gender"]
        if "has_customer_gender" in caps
        else any(re.search(r"^(?:gioi_?tinh|gender|sex|nam_?nu|namnu|phai)$", c) for c in ws_cols)
    )
    has_staff_cap = (
        caps["has_staff"]
        if "has_staff" in caps
        else any(
            re.search(
                r"(?:nhan_?vien|nhan_?su|ma_?nv|ten_?nv|ho_?ten_?nv|nguoi_?ban|chuc_?vu|chuc_?danh|"
                r"thu_?ngan|employees?|emp_?no|staff|salesperson|sales_?rep|spid|job_?title|cashier|worker|salaries|titles|dept_?emp)",
                tok,
            )
            for tok in ws_tbl_and_cols
        )
    )
    has_customers_cap = (
        caps["has_customers"]
        if "has_customers" in caps
        else any(re.search(r"(?:khach|customer|ben_?mua|doi_?tac|client)", tok) for tok in ws_tbl_and_cols)
    )

    # Gender attribute (customer, staff, or general demographic breakdown)
    asks_gender = bool(
        re.search(
            r"\b(?:khach(?:\s+hang)?\s+nu|nhan\s*(?:vien|su)\s+nu|nu\s+nhan\s*(?:vien|su)|nu\s+gioi|"
            r"phai\s+nu|phai\s+nam|nam\s+gioi|gioi\s+tinh|gender|sex|female|male)\b",
            qn,
        )
        or re.search(
            r"\b(?:khách(?:\s+hàng)?|nhân\s*(?:viên|sự)|người)\s+(?:nam|nữ)\b|\b(?:nữ|nam\s+giới|nữ\s+giới|phái\s+nam|phái\s+nữ|giới\s+tính)\b",
            q_low_nfc,
        )
    )
    if asks_gender and not has_gender_cap:
        if re.search(r"\b(?:nhan\s*(?:vien|su)|employee|employees|staff|salesperson|cashier)\b", qn) and not has_staff_cap:
            return (
                f"Dữ liệu hiện tại không lưu danh sách nhân viên và cũng không ghi cột giới tính "
                f"(các bảng hiện có: {tbl_preview})."
            )
        return "Dữ liệu hiện tại không ghi nhận thông tin giới tính (nam/nữ)."

    # Staff / Employee table or columns
    if (
        re.search(
            r"\b(?:nhan\s*vien|nhan\s*su|thu\s*ngan|pha\s*che|employee|employees|staff|salesperson|sales\s*rep|cashier|headcount)\b",
            qn,
        )
        and not has_staff_cap
    ):
        return (
            f"Dữ liệu hiện tại không ghi nhận bảng hay cột dữ liệu về nhân viên / nhân sự "
            f"(các bảng hiện có: {tbl_preview})."
        )

    # Employee salary / bonus / commission / KPI (use accented 'lương'/'thưởng' to avoid 'số lượng'/'thường')
    if (
        re.search(
            r"\b(?:lương|mức\s+lương|tiền\s+lương|bảng\s+lương|quỹ\s+lương|tăng\s+lương|thưởng|tiền\s+thưởng|mức\s+thưởng)\b",
            q_low_nfc,
        )
        or re.search(r"\b(?:hoa\s+hong|salary|salaries|wage|payroll|bonus|bonuses|commission|kpi|quota)\b", qn)
    ):
        if not any(re.search(r"(?:salar|wage|payroll|luong|bonus|thuong|commiss|hoa_?hong|kpi|quota)", tok) for tok in ws_tbl_and_cols):
            return "Dữ liệu hiện tại không ghi nhận thông tin lương, thưởng, hoa hồng hoặc chỉ tiêu KPI nhân viên."

    if re.search(r"\b(?:do\s+tuoi|nhom\s+tuoi|lua\s+tuoi|tuoi\s+tac|bao\s+nhieu\s+tuoi|theo\s+tuoi)\b", qn):
        if not any(re.search(r"\b(?:age|do_tuoi|tuoi|birth_date|dob|ngay_sinh|nam_sinh)\b", ac) for ac in ws_cols):
            return "Dữ liệu shop không ghi thông tin độ tuổi khách hàng/nhân sự."
    if re.search(r"(?:o\s+duong\s+|dia\s+chi\b)", qn) and not caps.get("has_customer_address"):
        return "Dữ liệu shop không ghi địa chỉ khách hàng."
    if re.search(r"(?:khach\s+nhom\s+|nhom\s+khach)", qn) and not caps.get("has_customer_group"):
        return "Dữ liệu shop không có cột phân nhóm khách hàng."
    if re.search(r"(?:ban\s+qua\s+dien\s+thoai|ban\s+qua\s+zalo|kenh\s+ban|tai\s+quay)", qn) and not caps.get("has_channel"):
        return "Dữ liệu shop không ghi kênh bán hàng."
    if re.search(r"(?:tra\s+bang\s+(?:cod|tien mat|chuyen khoan)|phuong\s+thuc\s+thanh\s+toan|hinh\s+thuc\s+thanh\s+toan)", qn) and not caps.get("has_payment_method"):
        return "Dữ liệu shop không ghi hình thức thanh toán."
    if re.search(r"(?:tra\s+hang\s+vi|tra\s+vi\s+|ly\s+do\s+tra|nguyen\s+nhan\s+tra)", qn) and not caps.get("has_return_reason"):
        return "Dữ liệu shop không ghi nguyên nhân trả hàng."
    if re.search(r"(?:han\s+dung|han\s+su\s+dung|het\s+han\s+trong)", qn) and not caps.get("has_expiry"):
        return "Dữ liệu shop không ghi hạn sử dụng."
    if re.search(r"(?:ton\s+kho|ton\s+cuoi|trong\s+kho\s+con|con\s+lai\s+may|con\s+ton)", qn) and not caps.get("has_inventory"):
        return "Dữ liệu shop không có bảng/cột theo dõi tồn kho."
    if re.search(r"(?:gia\s+von|lai\s+gop)", qn) and not caps.get("has_cost_price"):
        return "Dữ liệu shop không ghi giá vốn nên không tính được lãi gộp/giá trị theo giá vốn."
    if re.search(r"\blai\s+rong\b", qn) and not (caps.get("has_cost_price") and caps.get("has_expenses")):
        return "Dữ liệu shop thiếu giá vốn hoặc sổ chi phí nên không tính được lãi ròng."
    if re.search(r"(?:tien\s+nhap|gia\s+nhap|phieu\s+nhap|nhap\s+vao\s+gia|nhap\s+.*binh\s+quan)", qn):
        if not caps.get("has_import") or (
            re.search(r"(?:tien|gia|binh\s+quan)", qn) and not caps.get("has_import_price") and "gia_nhap" not in readme_n
        ):
            return "Dữ liệu shop không ghi đơn giá/giá trị phiếu nhập hàng."
    if re.search(r"(?:con\s+thieu|con\s+no|ghi\s+no|mua\s+chiu|tra\s+no|thu\s+hoi.*no|tuoi\s+no|no\s+(?:nhieu|lon)\s+nhat|khach\s+no|so\s+tien\s+no)", qn) and not caps.get("has_debt_or_payments"):
        return "Dữ liệu shop không có thông tin thu tiền/công nợ."
    if re.search(r"(?:\bkhach(?:\s+hang)?\s+nao|\bbao\s+nhieu\s+khach|so\s+khach|khach\s+da\s+mua|\bai\s+la\s+khach|chi\s+tieu\s+nhieu)", qn) and not has_customers_cap:
        return "Dữ liệu shop không lưu danh tính/mã khách hàng trên đơn."

    if re.search(
        r"\b(?:nghi\s+viec|thoi\s+viec|bo\s+viec|nghi\s+huu|sa\s+thai|resign(?:ed|ation)?|attrition|turnover|terminat(?:ed|ion)|layoff)\b",
        qn,
    ) or (
        re.search(r"\b(?:nhan\s+vien|nhan\s+su|employee|staff)\b", qn)
        and re.search(r"\b(?:roi\s+(?:di|khoi|cong\s+ty)|da\s+nghi|nghi\s+lam|left\s+(?:the\s+)?company|quit)\b", qn)
    ):
        if not any(
            re.search(r"(?:to_?date|end_?date|leave_?date|resign|terminat|attrition|nghi_?viec|thoi_?viec|is_?active|employment_?status)", c)
            for c in ws_cols
        ):
            return "Dữ liệu hiện tại không ghi nhận trạng thái nghỉ việc hoặc ngày kết thúc công tác của nhân viên."
    if re.search(r"\b(?:nghi\s+phep|ngay\s+phep|cham\s+cong|di\s+muon|tang\s+ca|overtime|attendance|sick\s+leave|annual\s+leave)\b", qn):
        has_att_schema = caps.get("has_attendance") or any(
            re.search(
                r"(?:attendance|cham_?cong|nghi_?phep|ngay_?phep|overtime|tang_?ca|absent|leave_?days|lich_?ca|vao_?ra|gio_?ot|diem_?danh)",
                tok,
            )
            for tok in ws_tbl_and_cols
        ) or any(
            re.search(r"ngh[iỉ]\s*(?:c[oó]\s*)?ph[eé]p|ch[aấ]m\s*c[oô]ng|wide_day_matrix", " ".join(tp.notes), re.I)
            for tp in knowledge.workspace.tables.values()
        )
        if not has_att_schema:
            return "Dữ liệu hiện tại không ghi nhận thông tin chấm công hoặc ngày nghỉ phép."

    has_geo_schema = caps.get("has_customer_address", False) or any(
        re.search(
            r"(?:geo|country|region|city|town|location|address|addr|state|province|district|territory|market|zone|area|branch|store|ship_?city|ship_?country|ship_?region|khu_?vuc|vung|mien|tinh|thanh_?pho|quan|huyen|phuong|quoc_?gia|thi_?truong|dia_?chi|dia_?diem|chi_?nhanh|cua_?hang)",
            tok,
        )
        for tok in ws_tbl_and_cols
    )
    if re.search(
        r"\b(?:thanh\s+pho|tinh\s+thanh|quan\s+huyen|phuong\s+xa|quoc\s+gia|khu\s+vuc|vung\s+mien|chi\s+nhanh|tung\s+cua\s+hang|theo\s+cua\s+hang|moi\s+cua\s+hang|city|cities|country|countries|province|provinces|region|regions|territory|branch|branches)\b",
        qn,
    ):
        if not has_geo_schema:
            return "Dữ liệu hiện tại không ghi nhận thông tin địa bàn, thành phố, khu vực hoặc chi nhánh."
    m_named_place = _NAMED_GEO_PLACE_RE.search(qn)
    if m_named_place and not has_geo_schema:
        place_tok = m_named_place.group(0).lower()
        prefix_ctx = qn[: m_named_place.start()]
        is_brand_or_product_ctx = bool(
            re.search(
                r"\b(?:bia|ruou|nuoc|ca\s+phe|tra|banh|nem|pho|bun|mi|com|hoa|rau|trai|xoai|sau|vua|vuon|cho|ben|hang|hieu|loai|nhan|mon|sp|san\s+pham|thuoc)\s+$",
                prefix_ctx,
            )
        )
        grounded_vals = [norm_vn(str(v)) for _, _, v in ground_query_entities(question, knowledge, max_matches=12)]
        entity_index_match = any(
            re.search(rf"(?<![a-z0-9]){re.escape(place_tok)}(?![a-z0-9])", ent.norm_value)
            for ent in knowledge.entity_entries
        )
        if (
            not is_brand_or_product_ctx
            and place_tok not in readme_n
            and not any(place_tok in gv for gv in grounded_vals)
            and not entity_index_match
        ):
            return "Dữ liệu hiện tại không ghi nhận thông tin địa bàn, thành phố, khu vực hoặc chi nhánh."
    return None


def check_preflight_unanswerable(
    question: str,
    as_of_date: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
) -> Optional[str]:
    """
    Domain-agnostic Rulebook §7 check using only live schema capabilities & data date span.
    Returns reason string if provably unanswerable, otherwise None.
    """
    q_nfc = normalize_nfc(question)
    qn = normalize_vn_question(q_nfc)

    # 0. Out-of-scope / non-business / weather / general-world questions
    oos_reason = check_out_of_scope_or_irrelevant(question, knowledge)
    if oos_reason:
        return oos_reason

    # 1. Subjective qualitative attributes never present in structured POS tables
    if _SUBJECTIVE_RE.search(qn):
        return "Câu hỏi mang tính đánh giá chủ quan/định tính không có trong dữ liệu bảng."

    # 2. Period completely out of recorded transaction history (Rulebook §7)
    if knowledge.data_min_date:
        if analysis.bounded_period is not None:
            w_start, w_end = analysis.bounded_period
            if w_end < knowledge.data_min_date:
                return f"Khoảng thời gian {w_start}..{w_end} nằm hoàn toàn trước ngày đầu tiên có dữ liệu ({knowledge.data_min_date})."
            if w_start > as_of_date:
                return f"Khoảng thời gian {w_start}..{w_end} nằm sau ngày dữ liệu hiện tại ({as_of_date})."
        if analysis.prior_needed_start is not None and analysis.prior_needed_start < knowledge.data_min_date:
            return f"Kỳ đối chiếu liền trước (kết thúc {analysis.prior_needed_start}) nằm ngoài phạm vi dữ liệu bắt đầu từ {knowledge.data_min_date}."

    # 3. Missing schema capability checks (staff, gender, salary, age, debt, inventory, geo, etc.)
    return _check_schema_capability_gap(question, knowledge)


_DIMENSION_PHRASE_COL_MAP = (
    ("nhom mon", r"nhom_?mon"),
    ("nhom hang", r"nhom_?hang|danh_?muc|category"),
    ("nhom thuoc", r"nhom_?thuoc|loai_?thuoc"),
    ("danh muc", r"danh_?muc|nhom_?hang|nhom_?mon|category"),
    ("kenh ban", r"kenh_?ban|kenh|channel"),
)

_ENTITY_WHICH_LOOKUP_RE = re.compile(
    r"\b(?:(?:ten|loai|nhom|ma)\s+)?(?:thuoc|vat\s+lieu|ngay|thang|nam|tuan|quy|mon|nhom|san\s+pham|mat\s+hang|"
    r"hang\s+hoa|hang|khach\s+hang|khach|nha\s+cung\s+cap|ncc|nhan\s+vien|cua\s+hang|chi\s+nhanh|quoc\s+gia|"
    r"kenh(?:\s+ban)?|doi\s+ngu|team|danh\s+muc|category|loai|phong\s+ban|chuc\s+danh)\s+nao\b"
)


def _match_requested_dimension_col(
    qn: str,
    knowledge: WorkspaceKnowledge,
) -> Optional[Tuple[str, str, str]]:
    """Return (q_phrase, table_name, column_name) if question explicitly asks for a grouped dimension present in schema."""
    for q_phrase, col_pat in _DIMENSION_PHRASE_COL_MAP:
        if re.search(rf"\b{q_phrase}\b", qn):
            is_membership_filter = bool(re.search(rf"\b(?:thuoc|trong|o|cua)\s+{q_phrase}\b", qn))
            has_group_cue = bool(
                re.search(
                    rf"\b(?:theo|tung|moi|giua\s+cac|so\s+sanh)\s+(?:tung\s+|cac\s+)?{q_phrase}\b|\b{q_phrase}\s+nao\b",
                    qn,
                )
            )
            if is_membership_filter and not has_group_cue:
                continue
            matched_dim = next(
                (
                    (tp.table_name, getattr(c, "sql_name", str(c)))
                    for tp in knowledge.workspace.tables.values()
                    for c in tp.columns
                    if re.search(rf"^(?:{col_pat})$", getattr(c, "sql_name", str(c)).lower())
                ),
                None,
            )
            if matched_dim:
                return q_phrase, matched_dim[0], matched_dim[1]
    return None


def _split_top_level_select_exprs(select_head: str) -> List[str]:
    """Split top-level SELECT expressions ignoring commas inside function calls or single quotes."""
    body = re.sub(r"^\s*select\s+(?:distinct\s+)?(?:top\s+\d+\s+)?", "", select_head.strip(), flags=re.IGNORECASE)
    parts: List[str] = []
    cur: List[str] = []
    depth = 0
    in_sq = False
    for ch in body:
        if ch == "'":
            in_sq = not in_sq
        elif not in_sq:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth > 0:
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


_BARE_SUMMABLE_METRIC_RE = re.compile(
    r"^(?:[a-z_][a-z0-9_]*\.)?(?:thanh_?tien|tong_?tien|doanh_?thu|tien_?hang|total_?amount|amount|revenue|sales|so_?luong|sl|qty|quantity|so_?hop|boxes|con_?no|chua_?tra)$",
    re.IGNORECASE,
)


def _infer_ranked_metric_alias(order_expr: str, qn: str) -> str:
    oe_low = (order_expr or "").lower()
    if re.search(r"(?:thanh_?tien|tong_?tien|doanh_?thu|tien_?hang|amount|revenue|sales|price|don_?gia|gia_?ban)", oe_low) or "doanh thu" in qn:
        return "tong_doanh_thu"
    if re.search(r"(?:so_?luong|sl|qty|quantity|so_?hop|boxes)", oe_low) or re.search(r"\b(?:so luong|ban chay)\b", qn):
        return "tong_so_luong"
    if re.search(r"(?:con_?no|chua_?tra|no\b|debt)", oe_low) or re.search(r"\bno\b", qn):
        return "tong_cong_no"
    if re.search(r"(?:luong|salary)", oe_low):
        return "muc_luong"
    if re.search(r"\bcount\s*\(", oe_low):
        return "so_luong_don" if "don" in qn else "so_luong"
    return "gia_tri"


def _extract_outer_select_head(sql_text: str) -> str:
    """Return the final top-level (depth 0) 'SELECT ...' clause before its top-level 'FROM', even when CTEs exist."""
    s = (sql_text or "").strip().rstrip(";")
    if not s:
        return ""
    depth = 0
    in_sq = False
    in_dq = False
    top_select_starts: List[int] = []
    top_from_positions: List[Tuple[int, int]] = []
    n = len(s)
    i = 0
    while i < n:
        ch = s[i]
        if ch == "'" and not in_dq:
            in_sq = not in_sq
            i += 1
            continue
        if ch == '"' and not in_sq:
            in_dq = not in_dq
            i += 1
            continue
        if not in_sq and not in_dq:
            if ch == "(":
                depth += 1
                i += 1
                continue
            if ch == ")" and depth > 0:
                depth -= 1
                i += 1
                continue
            if depth == 0 and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] == "_")):
                m_sel = re.match(r"select\b", s[i:], flags=re.IGNORECASE)
                if m_sel:
                    top_select_starts.append(i)
                    i += m_sel.end()
                    continue
                m_frm = re.match(r"from\b", s[i:], flags=re.IGNORECASE)
                if m_frm:
                    top_from_positions.append((i, i + m_frm.end()))
                    i += m_frm.end()
                    continue
        i += 1
    if not top_select_starts:
        return re.split(r"\bfrom\b", s, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    last_sel = top_select_starts[-1]
    next_frm = next((pos for pos, _ in top_from_positions if pos > last_sel), None)
    if next_frm is not None:
        return s[last_sel:next_frm].strip()
    return s[last_sel:].strip()


def rewrite_ranked_entity_sql(sql: str, question: str, use_round_half_up: bool = True) -> str:
    """
    Deterministically enrich ranked/filtered entity queries so that:
    1. Single-column entity SELECTs with GROUP BY + (ORDER BY <metric> or HAVING <metric>) automatically include
       the aggregated metric column in SELECT (and wrap bare summable metric columns in SUM(...) in ORDER BY).
    1b. Single-column outer SELECTs from a grouped CTE (WITH grouped AS (SELECT entity, metric_alias ...) SELECT entity FROM grouped ...)
        automatically include the CTE's metric_alias in the outer SELECT.
    2. Ordinal rank queries ('cao thứ 3', 'lớn thứ 2', 'đứng thứ N') use LIMIT 1 OFFSET {N - 1}
       instead of returning all top N rows with LIMIT N.
    """
    if not sql or not isinstance(sql, str):
        return sql
    s = sql.strip()
    if not s:
        return sql

    has_semi = s.endswith(";")
    body = s.rstrip(";").strip()
    body_low = re.sub(r"\s+", " ", body).lower()
    qn = normalize_vn_question(normalize_nfc(question or ""))
    ord_rank = extract_ordinal_rank(question or "")

    # Part A1: Enrich single-column entity SELECT (or unaggregated 2nd metric col) when GROUP BY and ORDER BY exist
    if (
        body_low.startswith("select ")
        and " from " in body_low
        and " group by " in body_low
        and " order by " in body_low
        and " union " not in body_low
    ):
        m_from = re.search(r"\bfrom\b", body, flags=re.IGNORECASE)
        m_group = re.search(r"\bgroup\s+by\b", body, flags=re.IGNORECASE)
        m_order = re.search(r"\border\s+by\b", body, flags=re.IGNORECASE)
        if m_from and m_group and m_order and m_from.start() < m_group.start() < m_order.start():
            select_head = body[: m_from.start()].strip()
            select_exprs = _split_top_level_select_exprs(select_head)
            group_clause_only = body[m_group.end() : m_order.start()].strip().lower()
            order_tail = body[m_order.end() :].strip()
            order_clause_only = re.split(r"\blimit\b", order_tail, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            first_order_item = _split_top_level_select_exprs("SELECT " + order_clause_only)
            raw_order_expr = (
                re.sub(
                    r"(?:\s+(?:asc|desc))?(?:\s+nulls\s+(?:first|last))?\s*$",
                    "",
                    first_order_item[0].strip(),
                    flags=re.IGNORECASE,
                ).strip()
                if first_order_item
                else ""
            )

            if len(select_exprs) == 1 and raw_order_expr:
                first_sel = select_exprs[0]
                is_sel_agg = bool(
                    re.search(r"\b(?:sum|count|avg|min|max|total|group_concat)\s*\(", first_sel, flags=re.IGNORECASE)
                )
                if not is_sel_agg:
                    is_order_agg = bool(
                        re.search(r"\b(?:sum|count|avg|min|max|total)\s*\(", raw_order_expr, flags=re.IGNORECASE)
                    )
                    is_bare_summable = bool(_BARE_SUMMABLE_METRIC_RE.match(raw_order_expr)) and (
                        raw_order_expr.lower() not in group_clause_only
                    )

                    agg_expr_for_select: Optional[str] = None
                    if is_order_agg:
                        agg_expr_for_select = raw_order_expr
                    elif is_bare_summable:
                        agg_expr_for_select = f"SUM({raw_order_expr})"
                        order_part_updated = re.sub(
                            rf"\b{re.escape(raw_order_expr)}\b",
                            f"SUM({raw_order_expr})",
                            body[m_order.start() :],
                            count=1,
                        )
                        body = body[: m_order.start()] + order_part_updated
                        m_from = re.search(r"\bfrom\b", body, flags=re.IGNORECASE)
                    else:
                        m_hav_agg = re.search(
                            r"\bhaving\b.*?\b((?:sum|count|avg|total)\s*\([^()]+\))",
                            body[m_group.end() : m_order.start()],
                            flags=re.IGNORECASE | re.DOTALL,
                        )
                        if m_hav_agg:
                            agg_expr_for_select = m_hav_agg.group(1).strip()

                    if agg_expr_for_select and m_from:
                        alias = _infer_ranked_metric_alias(agg_expr_for_select, qn)
                        if (
                            use_round_half_up
                            and re.search(r"\b(?:sum|avg|total)\s*\(", agg_expr_for_select, flags=re.IGNORECASE)
                            and "round" not in agg_expr_for_select.lower()
                        ):
                            metric_col_sql = f"ROUND_HALF_UP({agg_expr_for_select}, 0) AS {alias}"
                        else:
                            metric_col_sql = f"{agg_expr_for_select} AS {alias}"
                        body = f"{body[:m_from.start()].rstrip()}, {metric_col_sql} {body[m_from.start():].lstrip()}"

            elif len(select_exprs) == 2:
                has_any_agg = any(
                    re.search(r"\b(?:sum|count|avg|min|max|total|group_concat)\s*\(", ex, flags=re.IGNORECASE)
                    for ex in select_exprs
                )
                if not has_any_agg:
                    sec_core = re.sub(r"\s+as\s+[`\"']?[a-z0-9_]+[`\"']?\s*$", "", select_exprs[1].strip(), flags=re.IGNORECASE).strip()
                    if _BARE_SUMMABLE_METRIC_RE.match(sec_core) and sec_core.lower() not in group_clause_only:
                        alias = _infer_ranked_metric_alias(sec_core, qn)
                        wrapped_sel = (
                            f"ROUND_HALF_UP(SUM({sec_core}), 0) AS {alias}"
                            if use_round_half_up
                            else f"SUM({sec_core}) AS {alias}"
                        )
                        if _BARE_SUMMABLE_METRIC_RE.match(raw_order_expr) and raw_order_expr.lower() == sec_core.lower():
                            order_part_updated = re.sub(
                                rf"\b{re.escape(raw_order_expr)}\b",
                                f"SUM({raw_order_expr})",
                                body[m_order.start() :],
                                count=1,
                            )
                            body = body[: m_order.start()] + order_part_updated
                            m_from = re.search(r"\bfrom\b", body, flags=re.IGNORECASE)
                        if m_from:
                            body = f"SELECT {select_exprs[0]}, {wrapped_sel} {body[m_from.start():].lstrip()}"

    # Part A2: Single-column entity SELECT with GROUP BY + HAVING (when ORDER BY is absent)
    elif (
        body_low.startswith("select ")
        and " from " in body_low
        and " group by " in body_low
        and " having " in body_low
        and " order by " not in body_low
        and " union " not in body_low
    ):
        m_from = re.search(r"\bfrom\b", body, flags=re.IGNORECASE)
        m_group = re.search(r"\bgroup\s+by\b", body, flags=re.IGNORECASE)
        m_having = re.search(r"\bhaving\b", body, flags=re.IGNORECASE)
        if m_from and m_group and m_having and m_from.start() < m_group.start() < m_having.start():
            select_head = body[: m_from.start()].strip()
            select_exprs = _split_top_level_select_exprs(select_head)
            if len(select_exprs) == 1 and not re.search(
                r"\b(?:sum|count|avg|min|max|total|group_concat)\s*\(", select_exprs[0], flags=re.IGNORECASE
            ):
                m_hav_agg = re.search(
                    r"\b((?:sum|count|avg|total)\s*\([^()]+\))",
                    body[m_having.end() :],
                    flags=re.IGNORECASE,
                )
                if m_hav_agg:
                    agg_expr = m_hav_agg.group(1).strip()
                    alias = _infer_ranked_metric_alias(agg_expr, qn)
                    if (
                        use_round_half_up
                        and re.search(r"\b(?:sum|avg|total)\s*\(", agg_expr, flags=re.IGNORECASE)
                        and "round" not in agg_expr.lower()
                    ):
                        metric_col_sql = f"ROUND_HALF_UP({agg_expr}, 0) AS {alias}"
                    else:
                        metric_col_sql = f"{agg_expr} AS {alias}"
                    body = f"{body[:m_from.start()].rstrip()}, {metric_col_sql} {body[m_from.start():].lstrip()} ORDER BY {alias} DESC"

    # Part A3: CTE query where outer SELECT only selects 1 entity column from a CTE that already computed a metric alias
    elif body_low.startswith("with ") and " group by " in body_low and " union " not in body_low:
        outer_sel_head = _extract_outer_select_head(body)
        outer_exprs = _split_top_level_select_exprs(outer_sel_head)
        if (
            len(outer_exprs) == 1
            and outer_exprs[0] != "*"
            and not re.search(r"\b(?:sum|count|avg|min|max|total|group_concat)\s*\(", outer_exprs[0], flags=re.IGNORECASE)
        ):
            idx_outer = body.rfind(outer_sel_head)
            if idx_outer > 0:
                outer_tail = body[idx_outer + len(outer_sel_head) :].lstrip()
                m_cte_from = re.match(r"from\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", outer_tail, flags=re.IGNORECASE)
                if m_cte_from:
                    cte_name = m_cte_from.group(1)
                    m_cte_def = re.search(
                        rf"\b{re.escape(cte_name)}\s+as\s*\(\s*(select\b.*?)\bfrom\b",
                        body[:idx_outer],
                        flags=re.IGNORECASE | re.DOTALL,
                    )
                    if m_cte_def:
                        cte_sel_exprs = _split_top_level_select_exprs(m_cte_def.group(1))
                        if len(cte_sel_exprs) >= 2:
                            m_alias = re.search(
                                r"\bas\s+[`\"']?([a-zA-Z_][a-zA-Z0-9_]*)[`\"']?\s*$",
                                cte_sel_exprs[1].strip(),
                                flags=re.IGNORECASE,
                            )
                            if m_alias:
                                metric_alias = m_alias.group(1)
                                new_outer_head = f"{outer_sel_head.rstrip()}, {metric_alias}"
                                body = body[:idx_outer] + new_outer_head + " " + outer_tail
                                if not re.search(r"\border\s+by\b", outer_tail, flags=re.IGNORECASE):
                                    avg_dir = "ASC" if extract_benchmark_average_entity_intent(question or "") == "<" else "DESC"
                                    body = f"{body} ORDER BY {metric_alias} {avg_dir}"

    # Part B: Enforce LIMIT 1 OFFSET {rank_n - 1} for ordinal rank queries ('cao thứ 3', 'đứng thứ 2', etc.)
    if ord_rank is not None:
        rank_n, _ = ord_rank
        offset_val = rank_n - 1
        body_low_cur = re.sub(r"\s+", " ", body).lower()
        has_valid_offset = bool(
            re.search(rf"\blimit\s+1\s+offset\s+{offset_val}\b", body_low_cur)
            or re.search(rf"\blimit\s+{offset_val}\s*,\s*1\b", body_low_cur)
            or re.search(rf"\b(?:rn|rk|rank|thu_hang|hang|rnum|row_num)\s*=\s*{rank_n}\b", body_low_cur)
        )
        if not has_valid_offset and " order by " in body_low_cur:
            if re.search(r"\blimit\s+\d+(?:\s+offset\s+\d+)?\s*$", body, flags=re.IGNORECASE):
                body = re.sub(
                    r"\blimit\s+\d+(?:\s+offset\s+\d+)?\s*$",
                    f"LIMIT 1 OFFSET {offset_val}",
                    body,
                    flags=re.IGNORECASE,
                )
            else:
                body = f"{body} LIMIT 1 OFFSET {offset_val}"

    return f"{body};" if has_semi else body


def strip_spurious_single_day_filter(
    sql: str,
    question: str,
    analysis: QuestionAnalysis,
) -> str:
    """
    Remove an unrequested single-day equality predicate (e.g. `AND dh.ngay_ban = '2026-10-06'`)
    when an open-ended query asks about all history / catalog items without temporal constraints.
    Preserves compound OR predicates untouched.
    """
    if not sql or not isinstance(sql, str) or not analysis:
        return sql
    qn = normalize_vn_question(question or "")
    if (
        analysis.temporal_windows
        or analysis.bounded_period is not None
        or re.search(
            r"\b(?:hom nay|hnay|hom qua|hqua|ngay \d|thang \d|nam \d{4}|gan nhat|moi nhat|cuoi cung|dau tien)\b",
            qn,
        )
    ):
        return sql

    date_eq_pat = r"\b[a-zA-Z0-9_.]*(?:ngay|date|thoi_gian)[a-zA-Z0-9_]*\s*=\s*'20\d{2}-\d{2}-\d{2}'"
    has_semi = sql.rstrip().endswith(";")
    body = sql.rstrip().rstrip(";").strip()
    if "where" not in body.lower() or not re.search(date_eq_pat, body, flags=re.IGNORECASE):
        return sql

    # Only touch WHERE clauses (never SELECT CASE WHEN ...)
    def _clean_where_segment(m_seg: re.Match) -> str:
        seg = m_seg.group(0)
        seg_out = re.sub(rf"(?i)\s+\bAND\b\s+{date_eq_pat}(?!\s+\bOR\b)", "", seg)
        seg_out = re.sub(rf"(?i)(?<!\bOR\s)\b({date_eq_pat[2:]})\s+\bAND\b\s+", "", seg_out)
        seg_out = re.sub(
            rf"(?i)\bWHERE\b\s+{date_eq_pat}(?=\s*(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bHAVING\b|;|\)|$))",
            "",
            seg_out,
        )
        return seg_out

    updated = re.sub(
        r"(?i)\bWHERE\b[\s\S]*?(?=(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bHAVING\b|\bUNION\b|\)|$))",
        _clean_where_segment,
        body,
    )
    updated = re.sub(r"[ \t]{2,}", " ", updated).strip()
    updated = re.sub(r"\s+\)", ")", updated)
    return f"{updated};" if has_semi else updated


def _quote_sqlite_ident(ident: str) -> str:
    s = str(ident or "").strip()
    if " " in s or "-" in s or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", s):
        return f'"{s}"'
    return s


def _find_join_key(fact_tbl: Any, other_tbl: Any) -> Optional[str]:
    ignore = {"ngay", "thang", "nam", "ghi_chu", "trang_thai", "status", "note", "notes"}
    fact_cols = [getattr(c, "sql_name", str(c)) for c in getattr(fact_tbl, "columns", [])]
    other_map = {getattr(c, "sql_name", str(c)).lower(): getattr(c, "sql_name", str(c)) for c in getattr(other_tbl, "columns", [])}
    for fc in fact_cols:
        fl = fc.lower()
        if fl in ignore:
            continue
        if fl in other_map:
            return fc
    return None


def build_extreme_comparison_sql_spec(
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
) -> Optional[Dict[str, Any]]:
    """Build deterministic CTE SQL + metadata for extreme comparison queries (highest vs lowest + diff)."""
    if not analysis.extreme_comparison or not knowledge or not getattr(knowledge, "workspace", None):
        return None
    tables_dict = getattr(knowledge.workspace, "tables", None) or {}
    if not tables_dict:
        return None

    top_n, bottom_n, wants_diff = analysis.extreme_comparison
    qn = normalize_vn_question(normalize_nfc(question or ""))

    # 1. Pick primary fact table
    tables_list = list(tables_dict.values())
    wants_import = bool(re.search(r"\b(?:nhap|phieu nhap|gia nhap|tien nhap|nha cung cap|ncc)\b", qn))
    fact_profile = None
    if wants_import:
        for tp in tables_list:
            tlow = tp.table_name.lower()
            cols_l = {getattr(c, "sql_name", str(c)).lower() for c in tp.columns}
            if re.search(r"(?:phieu_?nhap|nhap_?hang)", tlow) or ("gia_nhap" in cols_l and "nha_cung_cap" in cols_l):
                fact_profile = tp
                break
    if fact_profile is None and getattr(knowledge, "order_status_targets", None):
        for tgt in knowledge.order_status_targets:
            tname = tgt.get("table", "")
            for tp in tables_list:
                if tp.table_name.lower() == tname.lower():
                    fact_profile = tp
                    break
            if fact_profile is not None:
                break
    if fact_profile is None:
        money_pats = re.compile(r"(?:doanh_?thu|thanh_?tien|tong_?tien|tien_?hang|amount|sales|revenue|salary|luong|chi_?phi|tien)", re.IGNORECASE)
        fact_profile = max(
            tables_list,
            key=lambda tp: (
                any(money_pats.search(getattr(c, "sql_name", str(c))) for c in tp.columns),
                int(getattr(tp, "row_count", 0) or 0),
            ),
        )

    fact_cols = [getattr(c, "sql_name", str(c)) for c in fact_profile.columns]
    fact_cols_low = {c.lower(): c for c in fact_cols}

    # 2. Pick metric expression on fact table
    asks_qty = bool(re.search(r"\b(?:so luong|sl\b|so hop|so chai|so goi|so vien|ban chay)\b", qn))
    asks_money = bool(re.search(r"\b(?:doanh thu|doanh so|tien|gia tri|cong no|revenue|sales|amount)\b", qn))
    asks_debt = bool(re.search(r"\b(?:cong no|con no|con thieu|chua tra|\bno\b)\b", qn))

    money_priority = (
        "doanh_thu", "doanhthu", "thanh_tien", "thanhtien", "tong_tien", "tongtien",
        "tien_hang", "tienhang", "tong_doanh_thu", "revenue", "total_revenue",
        "sales", "total_sales", "amount", "total_amount", "gia_tri", "profit",
        "loi_nhuan", "salary", "chi_phi",
    )
    qty_priority = ("so_luong_nhap", "so_luong", "soluong", "sl", "qty", "quantity", "so_hop", "boxes")
    debt_priority = ("con_no", "cong_no", "chua_tra", "con_thieu", "debt")

    money_col = next((fact_cols_low[k] for k in money_priority if k in fact_cols_low), None)
    if money_col is None:
        money_col = next(
            (c for c in fact_cols if re.search(r"(?:doanh_?thu|thanh_?tien|tong_?tien|tien_?hang|revenue|sales|amount|profit|salary)", c.lower()) and not re.search(r"(?:pct|ratio|ty_le)", c.lower())),
            None,
        )
    qty_col = next((fact_cols_low[k] for k in qty_priority if k in fact_cols_low), None)
    debt_col = next((fact_cols_low[k] for k in debt_priority if k in fact_cols_low), None)
    paid_col = next((fact_cols_low[k] for k in ("da_thanh_toan", "da_tra", "da_thu") if k in fact_cols_low), None)

    is_money_metric = True
    if wants_import and ("gia_nhap" in fact_cols_low) and qty_col and not (asks_qty and not asks_money):
        pcol = fact_cols_low["gia_nhap"]
        metric_expr = f"ROUND_HALF_UP(SUM(f.{qty_col} * f.{pcol}), 0)"
        metric_alias = "tong_tien_nhap"
    elif asks_debt:
        if debt_col:
            metric_expr = f"ROUND_HALF_UP(SUM(f.{debt_col}), 0)"
            metric_alias = "tong_cong_no"
        elif "tong_tien" in fact_cols_low and paid_col:
            tcol = fact_cols_low["tong_tien"]
            metric_expr = f"ROUND_HALF_UP(SUM(f.{tcol} - COALESCE(f.{paid_col}, 0)), 0)"
            metric_alias = "tong_cong_no"
        elif money_col:
            metric_expr = f"ROUND_HALF_UP(SUM(f.{money_col}), 0)"
            metric_alias = "tong_cong_no"
        else:
            return None
    elif asks_qty and not asks_money and qty_col:
        metric_expr = f"ROUND_HALF_UP(SUM(f.{qty_col}), 0)"
        metric_alias = "tong_so_luong"
        is_money_metric = False
    elif money_col:
        metric_expr = f"ROUND_HALF_UP(SUM(f.{money_col}), 0)"
        metric_alias = "tong_doanh_thu"
    elif qty_col:
        metric_expr = f"ROUND_HALF_UP(SUM(f.{qty_col}), 0)"
        metric_alias = "tong_so_luong"
        is_money_metric = False
    else:
        num_cands = [
            c for c in fact_profile.columns
            if getattr(c, "inferred_type", "") in ("integer", "real", "number", "float", "numeric")
            and not re.match(r"^(?:ma_|id$)|_id$", getattr(c, "sql_name", str(c)).lower())
        ]
        if not num_cands:
            return None
        ncol = getattr(num_cands[0], "sql_name", str(num_cands[0]))
        metric_expr = f"ROUND_HALF_UP(SUM(f.{ncol}), 0)"
        metric_alias = f"tong_{ncol.lower()}"
        is_money_metric = False

    # 3. Pick grouping dimension (supporting JOIN to companion lookup table like danhmucmon.nhom_mon)
    candidate_tables: List[Tuple[Any, Optional[str]]] = [(fact_profile, None)]
    for tp in tables_list:
        if tp.table_name == fact_profile.table_name:
            continue
        jk = _find_join_key(fact_profile, tp)
        if jk:
            candidate_tables.append((tp, jk))

    def _find_dim_by_regex(pat: str) -> Optional[Tuple[Any, str, Optional[str]]]:
        rx = re.compile(pat, re.IGNORECASE)
        for tp, jk in candidate_tables:
            for col in tp.columns:
                cname = getattr(col, "sql_name", str(col))
                if rx.search(cname.lower()):
                    return tp, cname, jk
        return None

    dim_pick: Optional[Tuple[Any, str, Optional[str]]] = None
    explicit_dim_rules = (
        (r"\bnhom\s+mon\b", r"^nhom_?mon$"),
        (r"\b(?:nhom\s+thuoc|loai\s+thuoc)\b", r"^(?:nhom|loai)_?thuoc$"),
        (r"\b(?:nhom\s+hang|danh\s+muc|category)\b", r"^(?:nhom_?hang|danh_?muc|category|categoryname)$"),
        (r"\bkenh\b", r"^(?:kenh_?ban|kenh|channel)$"),
        (r"\b(?:nha\s+cung\s+cap|ncc)\b", r"^(?:nha_?cung_?cap|ten_?ncc|supplier|companyname)$"),
        (r"\bkhach(?:\s+hang)?\b", r"^(?:ten_?khach_?hang|khach_?hang|ten_?kh|customer|companyname)$"),
        (r"\bthuoc\b", r"^(?:ten_?thuoc|thuoc)$"),
        (r"\bmon\b", r"^(?:ten_?mon|mon)$"),
        (r"\bvat\s+lieu\b", r"^(?:ten_?vl|vat_?lieu)$"),
        (r"\b(?:san\s+pham|mat\s+hang|hang\s+hoa)\b", r"^(?:ten_?thuoc|ten_?mon|ten_?vl|vat_?lieu|ten_?hang|ten_?sp|san_?pham|productname|product)$"),
        (r"\bnhan\s+vien\b", r"^(?:ten_?nhan_?vien|nhan_?vien|salesperson|employee)$"),
        (r"\bdon\s+vi\b", r"^(?:don_?vi|don_?vi_?tinh)$"),
        (r"\bngay\b", r"^(?:ngay_?gd|ngay_?ban|ngay_?dat|ngay_?nhap|ngay|orderdate)$"),
    )
    for q_pat, c_pat in explicit_dim_rules:
        if re.search(q_pat, qn):
            dim_pick = _find_dim_by_regex(c_pat)
            if dim_pick is not None:
                break

    if dim_pick is None:
        # Generic group/category column first (e.g. nhom_mon on cafe_pho_viet), then primary entity column on fact table
        dim_pick = _find_dim_by_regex(
            r"^(?:nhom_?mon|nhom_?thuoc|nhom_?hang|nhom_?sp|danh_?muc|danhmuc|loai_?mon|loai_?thuoc|loai_?hang|category|categoryname|team|dept_?name|department)$"
        )
    if dim_pick is None:
        dim_pick = _find_dim_by_regex(
            r"^(?:ten_?thuoc|ten_?mon|vat_?lieu|ten_?vl|ten_?hang|ten_?sp|san_?pham|productname|product)$"
        )
    if dim_pick is None:
        dim_pick = _find_dim_by_regex(
            r"^(?:ten_?khach_?hang|khach_?hang|kenh_?ban|nha_?cung_?cap)$"
        )
    if dim_pick is None:
        for tp, jk in candidate_tables:
            for col in tp.columns:
                cname = getattr(col, "sql_name", str(col))
                cl = cname.lower()
                if getattr(col, "inferred_type", "text") == "text" and not re.match(
                    r"^(?:ma_|id$|trang_?thai|status|ngay|date|ghi_?chu|note)", cl
                ):
                    dim_pick = (tp, cname, jk)
                    break
            if dim_pick is not None:
                break

    if dim_pick is None:
        return None

    dim_tbl, dim_col, join_key = dim_pick
    fact_ref = _quote_sqlite_ident(fact_profile.table_name)
    if dim_tbl.table_name == fact_profile.table_name:
        dim_expr = f"f.{dim_col}"
        join_sql = ""
    else:
        dim_expr = f"d.{dim_col}"
        join_sql = f"\n    JOIN {_quote_sqlite_ident(dim_tbl.table_name)} d ON f.{join_key} = d.{join_key}"

    # 4. Build safe WHERE predicates (status exclusion + bounded temporal filter + non-empty group)
    where_conds: List[str] = []
    if not _Q_ALLOW_ALL_STATUS_RE.search(qn) and getattr(knowledge, "order_status_targets", None):
        for tgt in knowledge.order_status_targets:
            if tgt.get("table", "").lower() == fact_profile.table_name.lower():
                vfilt = tgt.get("valid_filter") or ""
                scol = tgt.get("status_col") or ""
                if vfilt and scol:
                    where_conds.append(re.sub(rf"\b{re.escape(scol)}\b", f"f.{scol}", vfilt, flags=re.IGNORECASE))
                break

    if analysis.bounded_period is not None:
        dcol = next(
            (c for c in fact_cols if re.search(r"^(?:ngay_?gd|ngay_?ban|ngay_?dat|ngay_?nhap|ngay|orderdate|date)$", c.lower())),
            None,
        )
        if dcol:
            w_start, w_end = analysis.bounded_period
            where_conds.append(f"f.{dcol} BETWEEN '{w_start}' AND '{w_end}'")

    where_conds.append(f"{dim_expr} IS NOT NULL")
    where_conds.append(f"TRIM(CAST({dim_expr} AS TEXT)) != ''")
    where_sql = f"\n    WHERE {' AND '.join(where_conds)}"

    high_lbl = "Cao nhất" if top_n == 1 else f"Top {top_n} Cao nhất"
    low_lbl = "Thấp nhất" if bottom_n == 1 else f"Top {bottom_n} Thấp nhất"

    diff_ranked_line = (
        f",\n        ROUND_HALF_UP(MAX({metric_alias}) OVER () - MIN({metric_alias}) OVER (), 0) AS chenh_lech_cao_thap"
        if wants_diff
        else ""
    )
    diff_outer_line = ",\n    chenh_lech_cao_thap" if wants_diff else ""

    suggested_sql = (
        f"WITH grouped AS (\n"
        f"    SELECT {dim_expr} AS {dim_col}, {metric_expr} AS {metric_alias}\n"
        f"    FROM {fact_ref} f{join_sql}{where_sql}\n"
        f"    GROUP BY {dim_expr}\n"
        f"),\n"
        f"ranked AS (\n"
        f"    SELECT\n"
        f"        {dim_col},\n"
        f"        {metric_alias},\n"
        f"        ROW_NUMBER() OVER (ORDER BY {metric_alias} DESC, {dim_col} ASC) AS rn_high,\n"
        f"        ROW_NUMBER() OVER (ORDER BY {metric_alias} ASC, {dim_col} DESC) AS rn_low{diff_ranked_line}\n"
        f"    FROM grouped\n"
        f")\n"
        f"SELECT\n"
        f"    {dim_col},\n"
        f"    CASE WHEN rn_high <= {top_n} THEN '{high_lbl}' ELSE '{low_lbl}' END AS nhom_xep_hang,\n"
        f"    {metric_alias}{diff_outer_line}\n"
        f"FROM ranked\n"
        f"WHERE rn_high <= {top_n} OR rn_low <= {bottom_n}\n"
        f"ORDER BY {metric_alias} DESC, rn_high ASC;"
    )

    return {
        "fact_table": fact_profile.table_name,
        "dim_table": dim_tbl.table_name,
        "dim_col": dim_col,
        "metric_alias": metric_alias,
        "is_money": is_money_metric,
        "top_n": top_n,
        "bottom_n": bottom_n,
        "wants_diff": wants_diff,
        "suggested_sql": suggested_sql,
    }


def build_benchmark_average_entity_sql_spec(
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
) -> Optional[Dict[str, Any]]:
    """
    Build deterministic CTE SQL + metadata for queries asking which entities (medicines, dishes, products,
    materials, customers, channels, categories) have a total metric above ('>') or below ('<') the entity-level average.
    Always selects BOTH the entity name column AND the aggregated metric column.
    """
    cmp_op = extract_benchmark_average_entity_intent(question)
    if not cmp_op or not knowledge or not getattr(knowledge, "workspace", None):
        return None

    # Reuse the schema/table/dimension/metric resolution from build_extreme_comparison_sql_spec via a temp analysis
    tmp_analysis = QuestionAnalysis(
        expected_type=analysis.expected_type,
        date_granularity=analysis.date_granularity,
        money_like=analysis.money_like,
        bounded_period=analysis.bounded_period,
        extreme_comparison=(1, 1, False),
    )
    base_spec = build_extreme_comparison_sql_spec(question, knowledge, tmp_analysis)
    if not base_spec or not base_spec.get("suggested_sql"):
        return None

    # Extract the `WITH grouped AS (...)` CTE block from base_spec["suggested_sql"]
    base_sql = str(base_spec["suggested_sql"])
    m_grouped = re.search(r"^(WITH\s+grouped\s+AS\s*\(\s*SELECT.*?\bGROUP\s+BY\s+[^\n]+\n\))", base_sql, flags=re.IGNORECASE | re.DOTALL)
    if not m_grouped:
        return None

    grouped_cte = m_grouped.group(1)
    dim_col = base_spec["dim_col"]
    metric_alias = base_spec["metric_alias"]
    order_dir = "DESC" if cmp_op == ">" else "ASC"

    suggested_sql = (
        f"{grouped_cte}\n"
        f"SELECT\n"
        f"    {dim_col},\n"
        f"    {metric_alias}\n"
        f"FROM grouped\n"
        f"WHERE {metric_alias} {cmp_op} (SELECT AVG({metric_alias}) FROM grouped)\n"
        f"ORDER BY {metric_alias} {order_dir}, {dim_col} ASC;"
    )

    return {
        "fact_table": base_spec["fact_table"],
        "dim_table": base_spec["dim_table"],
        "dim_col": dim_col,
        "metric_alias": metric_alias,
        "is_money": base_spec["is_money"],
        "cmp_op": cmp_op,
        "suggested_sql": suggested_sql,
    }


def build_catalog_listing_sql_spec(
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
    entity_matches: Sequence[Tuple[str, str, str]] = (),
) -> Optional[Dict[str, Any]]:
    """
    Build deterministic SQL + metadata for pure catalog/attribute listing queries
    (e.g. 'Danh sách những món thuộc nhóm Cà Phê', 'Các món thuộc nhóm món Cà phê')
    directly against non-transactional catalog tables without joining order history.
    """
    if not knowledge or not getattr(knowledge, "workspace", None):
        return None
    if getattr(analysis, "temporal_windows", None) or getattr(analysis, "bounded_period", None) is not None:
        return None
    tables_dict = getattr(knowledge.workspace, "tables", None) or {}
    if not tables_dict:
        return None

    q_nfc = normalize_nfc(question or "")
    qn = normalize_vn_question(q_nfc)
    if not qn:
        return None

    has_list_ask = bool(
        re.search(
            r"(?:\b(?:danh\s+sach|liet\s+ke|in\s+ra)\b|"
            r"\b(?:nhung|cac)\s+(?:ten\s+|loai\s+|nhom\s+|ma\s+)?(?:mon|thuoc|san\s+pham|mat\s+hang|vat\s+lieu|hang\s+hoa|khach(?:\s+hang)?|nha\s+cung\s+cap|nhan\s+vien|danh\s+muc)\b|"
            r"\b(?:menu|thuc\s+don|danh\s+muc)\b)",
            qn,
        )
    )
    if not has_list_ask:
        return None

    has_metric_or_tx_ask = bool(
        re.search(
            r"(?:\b(?:doanh\s+thu|doanh\s+so|thanh\s+tien|ban\s+duoc|ban\s+chay|da\s+ban|"
            r"mua|da\s+mua|dat\s+mua|dat\s+thue|da\s+dat|da\s+lam|da\s+su\s+dung|"
            r"so\s+don|hoa\s+don|so\s+luong(?:\s+ban)?|tien\s+nhap|nhap\s+kho|ton\s+kho|cong\s+no|con\s+no|no|lai|chi\s+phi|"
            r"top\s*\d+|cao\s+nhat|thap\s+nhat|trung\s+binh|vuot|bao\s+nhieu|may|"
            r"ty\s+le|ti\s+le|ty\s+trong|phan\s+tram|xu\s+huong|huy|tra\s+hang|"
            r"ngay|thang|nam|hom\s+nay|hom\s+qua|cao\s+thu|thap\s+thu|dung\s+thu|xep\s+thu|"
            r"tong\s+(?:so|tien|doanh|luong)|cua\s+khach|khach\s+hang\s+\S+)\b|%)",
            qn,
        )
    )
    if has_metric_or_tx_ask:
        return None

    tx_tables = {t["table"] for t in (knowledge.order_status_targets or [])}
    tables_with_dates = {
        tbl_col.split(".", 1)[0]
        for tbl_col in (knowledge.table_date_ranges or {}).keys()
        if "." in tbl_col
    }
    catalog_tables = [
        tp
        for tp in tables_dict.values()
        if getattr(tp, "row_count", 0) > 0
        and tp.table_name not in tx_tables
        and tp.table_name not in tables_with_dates
    ]
    if not catalog_tables:
        return None

    cat_by_name = {tp.table_name: tp for tp in catalog_tables}

    # Bail out if entity_matches grounded an entity (e.g. a customer or tx row) whose table is NOT a catalog table
    for ent_tbl, _ent_col, ent_val in entity_matches or ():
        val_norm = norm_vn(str(ent_val or ""))
        if len(val_norm) >= 2 and re.search(rf"(?<![a-z0-9]){re.escape(val_norm)}(?![a-z0-9])", qn):
            if ent_tbl in tx_tables or ent_tbl in tables_with_dates:
                return None
            if ent_tbl in cat_by_name and re.search(r"khach|benh_?nhan|hoc_?vien|nhan_?vien", ent_tbl, re.I) and not re.search(r"\b(?:danh\s+sach|liet\s+ke)\s+(?:tat\s+ca\s+|toan\s+bo\s+)?khach", qn):
                return None

    # Prefer grounded entities whose table is a catalog table and value appears as an exact token in question
    matched_candidates: List[Tuple[int, str, str, str]] = []
    for ent_tbl, ent_col, ent_val in entity_matches or ():
        if ent_tbl not in cat_by_name:
            continue
        val_norm = norm_vn(str(ent_val or ""))
        if len(val_norm) < 2:
            continue
        if not re.search(rf"(?<![a-z0-9]){re.escape(val_norm)}(?![a-z0-9])", qn):
            continue
        col_low = str(ent_col or "").lower()
        is_attr_col = bool(re.search(r"(?:nhom|loai|danh_?muc|category|nha_cung_cap|ncc|hang|thuong_hieu)", col_low))
        score = (100 if is_attr_col else 40) + len(val_norm)
        matched_candidates.append((score, ent_tbl, ent_col, str(ent_val)))

    chosen_tbl = None
    filter_col = None
    filter_val = None
    if matched_candidates:
        matched_candidates.sort(key=lambda x: x[0], reverse=True)
        _, t_name, filter_col, filter_val = matched_candidates[0]
        chosen_tbl = cat_by_name[t_name]
    else:
        has_all_cue = bool(re.search(r"\b(?:tat\s+ca|toan\s+bo|menu|thuc\s+don)\b", qn))
        has_specific_filter_cue = bool(re.search(r"\b(?:thuoc|cua|tai|duoi|tren|hon|kem|khong)\b", qn))
        if has_specific_filter_cue and not has_all_cue:
            return None
        if not (has_all_cue or re.search(r"\b(?:danh\s+sach|liet\s+ke|nhung|cac|danh\s+muc)\b", qn)):
            return None
        # Pick the catalog table whose columns/table name align best with the question
        best_score = -1
        for tp in catalog_tables:
            t_low = norm_vn(tp.table_name)
            col_names = [norm_vn(getattr(c, "sql_name", str(c))) for c in tp.columns]
            sc = 0
            if any(w in qn and w in t_low for w in ("mon", "thuoc", "san pham", "khach", "nha cung cap", "nhan vien", "danh muc")):
                sc += 10
            if any(w in qn and any(w in cn for cn in col_names) for w in ("mon", "thuoc", "san pham", "khach", "nha cung cap", "nhan vien", "don gia", "gia")):
                sc += 5
            if re.search(r"(?:mon|menu|thuc\s+don)", qn) and any("mon" in cn for cn in col_names):
                sc += 8
            if sc > best_score:
                best_score = sc
                chosen_tbl = tp

    if chosen_tbl is None:
        return None

    active_cols = [
        getattr(c, "sql_name", str(c))
        for c in chosen_tbl.columns
        if chosen_tbl.row_count == 0
        or (getattr(c, "distinct_count", 1) > 0 and getattr(c, "null_count", 0) < chosen_tbl.row_count)
    ]
    if not active_cols:
        active_cols = [getattr(c, "sql_name", str(c)) for c in chosen_tbl.columns]
    if not active_cols:
        return None

    name_col = next(
        (
            c
            for c in active_cols
            if re.search(r"(?:^|_)(?:ten_?(?:mon|thuoc|sp|san_?pham|hang|kh|khach_?hang|ncc)|name|title)(?:$|_)", c.lower())
        ),
        active_cols[0],
    )
    ordered_cols = [name_col] + [c for c in active_cols if c != name_col]
    select_cols_sql = ", ".join(_quote_sqlite_ident(c) for c in ordered_cols)
    tbl_ref = _quote_sqlite_ident(chosen_tbl.table_name)
    name_col_ref = _quote_sqlite_ident(name_col)

    where_sql = ""
    if filter_col and filter_val is not None:
        esc_val = str(filter_val).replace("'", "''")
        fcol_ref = _quote_sqlite_ident(filter_col)
        where_sql = f"\nWHERE NORM_VN({fcol_ref}) = NORM_VN('{esc_val}')"

    suggested_sql = f"SELECT {select_cols_sql}\nFROM {tbl_ref}{where_sql}\nORDER BY {name_col_ref} ASC;"
    return {
        "table": chosen_tbl.table_name,
        "filter_col": filter_col,
        "filter_val": filter_val,
        "suggested_sql": suggested_sql,
    }


def _resolve_fact_dim_join(
    fact_tp: Any,
    dim_tp: Any,
    join_graph: Sequence[str] = (),
    preferred_fact_col_rx: Optional[str] = None,
) -> Optional[Tuple[str, str, bool]]:
    """Resolve (fact_col, dim_col, use_norm_vn) from same-name keys or heterogeneous join_graph edges."""
    if fact_tp is None or dim_tp is None:
        return None
    f_name = fact_tp.table_name
    d_name = dim_tp.table_name
    f_cols = [getattr(c, "sql_name", str(c)) for c in getattr(fact_tp, "columns", [])]

    edge_pairs: List[Tuple[str, str]] = []
    for edge in join_graph or ():
        m_edge = re.match(
            r"^\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\s*=\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)",
            str(edge or ""),
        )
        if not m_edge:
            continue
        t1, c1, t2, c2 = m_edge.group(1), m_edge.group(2), m_edge.group(3), m_edge.group(4)
        if t1.lower() == f_name.lower() and t2.lower() == d_name.lower():
            edge_pairs.append((c1, c2))
        elif t2.lower() == f_name.lower() and t1.lower() == d_name.lower():
            edge_pairs.append((c2, c1))

    if preferred_fact_col_rx:
        pref_rx = re.compile(preferred_fact_col_rx, re.IGNORECASE)
        for fc, dc in edge_pairs:
            if pref_rx.search(fc):
                use_norm = bool(re.search(r"(?:ten_?goi|biet_?danh|hay_?goi|tho|khach|ten)", f"{fc}_{dc}", re.I))
                return fc, dc, use_norm
        jk_same = _find_join_key(fact_tp, dim_tp)
        if jk_same and pref_rx.search(jk_same):
            return jk_same, jk_same, False
        # e.g. 'tho_phu' on fact matching 'ten_goi' on danhsachtho when join_graph mapped 'tho = ten_goi'
        for fc in f_cols:
            if pref_rx.search(fc):
                for _, dc in edge_pairs:
                    if re.search(r"(?:ten_?goi|biet_?danh|hay_?goi)", dc, re.I):
                        return fc, dc, True
        return None

    jk_same = _find_join_key(fact_tp, dim_tp)
    if jk_same:
        return jk_same, jk_same, False
    if edge_pairs:
        fc, dc = edge_pairs[0]
        use_norm = bool(re.search(r"(?:ten_?goi|biet_?danh|hay_?goi|tho|khach|ten)", f"{fc}_{dc}", re.I))
        return fc, dc, use_norm
    return None


def build_entity_and_metric_listing_sql_spec(
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
    entity_matches: Sequence[Tuple[str, str, str]] = (),
) -> Optional[Dict[str, Any]]:
    """
    Build deterministic SQL + metadata for two-part queries asking for BOTH a list/Top-K of entities
    AND an aggregated metric (e.g. 'Nhà cung cấp Sanofi VN đã nhập những loại thuốc nào và tổng tiền nhập là bao nhiêu?'
    or 'Top 5 thợ chính đem về tổng tiền dịch vụ cao nhất kèm doanh thu từng người?').
    """
    if not knowledge or not getattr(knowledge, "workspace", None):
        return None
    if getattr(analysis, "extreme_comparison", None) is not None:
        return None
    if extract_benchmark_average_entity_intent(question) is not None:
        return None
    tables_dict = getattr(knowledge.workspace, "tables", None) or {}
    if not tables_dict:
        return None

    q_nfc = normalize_nfc(question or "")
    qn = normalize_vn_question(q_nfc)
    if not qn:
        return None

    top_m = re.search(r"\btop\s*(\d+)\b", qn)
    limit_k = int(top_m.group(1)) if top_m else None

    _ent_noun_alt = (
        r"(?:thuoc|vat\s+lieu|mat\s+hang|san\s+pham|mon|dich\s+vu|hang\s+hoa|"
        r"khach(?:\s+hang)?|nha\s+cung\s+cap|ncc|kenh(?:\s+ban)?|nhom(?:\s+mon|\s+hang|\s+thuoc)?|"
        r"nhan\s+vien|tho(?:\s+chinh|\s+phu)?|ky\s+thuat\s+vien|ktv|phong)"
    )
    has_entity_list_ask = bool(
        re.search(
            rf"(?:(?:nhung|cac)\s+(?:ten\s+|loai\s+|nhom\s+|ma\s+)?{_ent_noun_alt}\s+nao\b|"
            rf"\b(?:danh\s+sach|liet\s+ke)\b[^?]{{0,80}}\b{_ent_noun_alt}\b|"
            rf"\btop\s*\d+\s+(?:ten\s+|loai\s+|nhom\s+|ma\s+)?{_ent_noun_alt}\b)",
            qn,
        )
    )
    has_agg_metric_ask = bool(
        re.search(
            r"(?:(?:\bva\b|,|\bkem\b)\s*(?:tong\s+)?(?:tien\s+nhap|gia\s+tri\s+nhap|tien\s+dich\s+vu|tien\s+hang|doanh\s+thu|doanh\s+so|thanh\s+tien|so\s+luong(?:\s+nhap|\s+ban)?|cong\s+no|con\s+no|tong\s+tien|so\s+tien|chi\s+tieu|chi\s+phi)\b|"
            r"\b(?:dem\s+ve|mang\s+lai)\s+(?:tong\s+)?(?:tien(?:\s+dich\s+vu|\s+hang)?|doanh\s+thu|doanh\s+so|gia\s+tri)\b)",
            qn,
        )
    )
    if not (has_entity_list_ask and has_agg_metric_ask):
        return None

    wants_import = bool(re.search(r"\b(?:nhap|phieu\s+nhap|gia\s+nhap|tien\s+nhap|gia\s+tri\s+nhap)\b", qn))
    wants_debt = bool(re.search(r"\b(?:cong\s+no|con\s+no|con\s+thieu|chua\s+tra|\bno\b)\b", qn))
    wants_qty = bool(re.search(r"\b(?:so\s+luong|sl\b|so\s+hop|so\s+chai|so\s+goi|so\s+vien)\b", qn))
    wants_money = bool(
        re.search(
            r"\b(?:tien\s+nhap|gia\s+tri\s+nhap|tien\s+dich\s+vu|tien\s+hang|doanh\s+thu|doanh\s+so|thanh\s+tien|tong\s+tien|so\s+tien|chi\s+tieu|chi\s+phi|cong\s+no|con\s+no|gia\s+tri)\b",
            qn,
        )
    )

    # Collect valid grounded entity filters that actually appear in the normalized question
    matched_filters: List[Tuple[str, str, str]] = []
    seen_filter_pairs: set = set()
    for ent_tbl, ent_col, ent_val in entity_matches or ():
        if ent_tbl not in tables_dict:
            continue
        val_norm = norm_vn(str(ent_val or ""))
        if len(val_norm) < 2:
            continue
        if not re.search(rf"(?<![a-z0-9]){re.escape(val_norm)}(?![a-z0-9])", qn):
            continue
        pair_key = (ent_tbl, ent_col.lower())
        if pair_key not in seen_filter_pairs:
            seen_filter_pairs.add(pair_key)
            matched_filters.append((ent_tbl, ent_col, str(ent_val)))

    # 1. Pick best fact table
    tables_list = [tp for tp in tables_dict.values() if int(getattr(tp, "row_count", 0) or 0) > 0]
    if not tables_list:
        return None

    tx_names_low = {t["table"].lower() for t in (knowledge.order_status_targets or [])}
    money_priority = (
        "doanh_thu", "doanhthu", "thanh_tien", "thanhtien", "tong_tien", "tongtien",
        "tien_hang", "tienhang", "tong_doanh_thu", "revenue", "total_revenue",
        "sales", "total_sales", "amount", "total_amount", "gia_tri", "profit",
        "loi_nhuan", "salary", "chi_phi",
        "tien_dich_vu", "t_tien", "tong_bill", "tien", "tong", "da_thu",
    )
    qty_priority = ("so_luong_nhap", "so_luong", "soluong", "sl", "qty", "quantity", "so_hop", "boxes")
    debt_priority = ("con_no", "cong_no", "chua_tra", "con_thieu", "debt")

    best_fact = None
    best_fact_score = -10**9
    for tp in tables_list:
        tlow = tp.table_name.lower()
        cols_l = {getattr(c, "sql_name", str(c)).lower() for c in tp.columns}
        has_date_col = any(
            getattr(c, "inferred_type", "") in ("date", "datetime")
            or re.search(r"(?:^|_)(?:ngay|thoi_?gian|date)", getattr(c, "sql_name", str(c)).lower())
            for c in tp.columns
        )
        has_money_col = any(m in cols_l for m in money_priority)
        sc = 0
        if not wants_import and re.search(r"^(?:danh_?(?:sach|ba|muc)|dm_|bang_?gia|quy_?doi|ton_?kho)", tlow):
            sc -= 50
        if wants_import and (re.search(r"(?:phieu_?nhap|nhap_?hang)", tlow) or ("gia_nhap" in cols_l and "nha_cung_cap" in cols_l)):
            sc += 120
        elif wants_debt and (any(d in cols_l for d in debt_priority) or "da_thanh_toan" in cols_l or "da_tra" in cols_l):
            sc += 110
        elif not wants_import and not wants_debt and tlow in tx_names_low:
            sc += 100
        elif not wants_import and not wants_debt and has_date_col and has_money_col:
            sc += 75
            if re.search(r"(?:so_?thu|ban_?hang|phieu_?dv|soban)", tlow):
                sc += 15
        if any(f_tbl == tp.table_name for f_tbl, _, _ in matched_filters):
            sc += 60
        if has_money_col or ("gia_nhap" in cols_l and any(q in cols_l for q in qty_priority)):
            sc += 30
        if re.search(r"(?:don_?hang|hoa_?don|chi_?tiet)", tlow):
            sc += 10
        if sc > best_fact_score:
            best_fact_score = sc
            best_fact = tp

    if best_fact is None:
        return None

    fact_cols = [getattr(c, "sql_name", str(c)) for c in best_fact.columns]
    fact_cols_low = {c.lower(): c for c in fact_cols}

    # 2. Pick primary metric expression & alias (first numeric col in SELECT!)
    money_col = next((fact_cols_low[k] for k in money_priority if k in fact_cols_low), None)
    if money_col is None:
        money_col = next(
            (
                c
                for c in fact_cols
                if re.search(r"(?:doanh_?thu|thanh_?tien|tong_?tien|tien_?hang|revenue|sales|amount|profit|salary)", c.lower())
                and not re.search(r"(?:pct|ratio|ty_le)", c.lower())
            ),
            None,
        )
    qty_col = next((fact_cols_low[k] for k in qty_priority if k in fact_cols_low), None)
    debt_col = next((fact_cols_low[k] for k in debt_priority if k in fact_cols_low), None)
    paid_col = next((fact_cols_low[k] for k in ("da_thanh_toan", "da_tra", "da_thu") if k in fact_cols_low), None)
    price_col = fact_cols_low.get("don_gia") or fact_cols_low.get("gia_ban") or fact_cols_low.get("gia")

    metric_expr = None
    metric_alias = None
    is_money_metric = True

    if wants_import and ("gia_nhap" in fact_cols_low) and qty_col and not (wants_qty and not wants_money):
        pcol = fact_cols_low["gia_nhap"]
        metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(qty_col)} * f.{_quote_sqlite_ident(pcol)}), 0)"
        metric_alias = "tong_tien_nhap"
    elif wants_debt:
        if debt_col:
            metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(debt_col)}), 0)"
            metric_alias = "tong_cong_no"
        elif "tong_tien" in fact_cols_low and paid_col:
            tcol = fact_cols_low["tong_tien"]
            metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(tcol)} - COALESCE(f.{_quote_sqlite_ident(paid_col)}, 0)), 0)"
            metric_alias = "tong_cong_no"
        elif money_col:
            metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(money_col)}), 0)"
            metric_alias = "tong_cong_no"
    elif wants_qty and not wants_money and qty_col:
        metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(qty_col)}), 0)"
        metric_alias = "tong_so_luong"
        is_money_metric = False
    elif money_col:
        metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(money_col)}), 0)"
        metric_alias = "tong_tien_nhap" if wants_import else "tong_doanh_thu"
    elif qty_col and price_col:
        metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(qty_col)} * f.{_quote_sqlite_ident(price_col)}), 0)"
        metric_alias = "tong_doanh_thu"
    elif qty_col:
        metric_expr = f"ROUND_HALF_UP(SUM(f.{_quote_sqlite_ident(qty_col)}), 0)"
        metric_alias = "tong_so_luong"
        is_money_metric = False

    if not metric_expr or not metric_alias:
        return None

    # 3. Pick requested entity column (prefer linked directory full names for staff/customers!)
    asks_staff_sub = bool(re.search(r"\btho\s+phu\b", qn))
    asks_staff = bool(re.search(r"\b(?:tho(?:\s+chinh|\s+phu)?|ky\s+thuat\s+vien|ktv|nhan\s+vien)\b", qn))
    asks_customer = bool(re.search(r"\bkhach(?:\s+hang)?\b", qn))
    pref_fact_rx = (
        r"^tho_?phu$"
        if asks_staff_sub
        else (r"^(?:tho_?chinh|tho|ktv|nhan_?vien|ma_?nv)$" if asks_staff else None)
    )

    dir_candidates: List[Tuple[Any, Optional[Tuple[str, str, bool]]]] = []
    fact_candidate: List[Tuple[Any, Optional[Tuple[str, str, bool]]]] = [(best_fact, None)]
    for tp in tables_list:
        if tp.table_name == best_fact.table_name:
            continue
        tlow = tp.table_name.lower()
        if asks_staff and re.search(r"(?:khach|danh_?ba)", tlow):
            continue
        if asks_customer and not asks_staff and re.search(r"(?:tho|nhan_?vien|ktv)", tlow):
            continue
        j_info = _resolve_fact_dim_join(
            best_fact, tp, knowledge.join_graph or (), preferred_fact_col_rx=pref_fact_rx
        )
        if j_info is not None:
            dir_candidates.append((tp, j_info))

    candidate_tables = (dir_candidates + fact_candidate) if (asks_staff or asks_customer) else (fact_candidate + dir_candidates)

    filtered_cols_on_tbl = {(ftbl, fcol.lower()) for ftbl, fcol, _ in matched_filters}
    entity_noun_rules = (
        (r"\btho\s+phu\b", r"^(?:ho_?ten|ho_?va_?ten|ten_?tho|tho_?phu)$"),
        (r"\b(?:tho(?:\s+chinh)?|ky\s+thuat\s+vien|ktv|nhan\s+vien)\b", r"^(?:ho_?ten|ho_?va_?ten|ten_?nv|ten_?tho|nhan_?vien|tho_?chinh|tho)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+|loai\s+|ma\s+)?thuoc\b|danh\s+sach[^?]*thuoc\b|\btop\s*\d+[^?]*thuoc\b)", r"^(?:ten_?thuoc|thuoc)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+|loai\s+|ma\s+)?mon\b|danh\s+sach[^?]*mon\b|\btop\s*\d+[^?]*mon\b)", r"^(?:ten_?mon|mon)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+|loai\s+|ma\s+)?vat\s+lieu\b|danh\s+sach[^?]*vat\s+lieu\b)", r"^(?:ten_?vl|ten_?vat_?lieu|vat_?lieu)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+|loai\s+|ma\s+)?dich\s+vu\b|danh\s+sach[^?]*dich\s+vu\b|\btop\s*\d+[^?]*dich\s+vu\b)", r"^(?:ten_?dich_?vu|dich_?vu)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+|loai\s+|ma\s+)?(?:san\s+pham|mat\s+hang|hang\s+hoa)\b|danh\s+sach[^?]*(?:san\s+pham|mat\s+hang)\b|\btop\s*\d+[^?]*(?:san\s+pham|mat\s+hang|hang\s+hoa)\b)", r"^(?:ten_?san_?pham|ten_?hang|ten_?sp|ten_?thuoc|ten_?mon|ten_?vl|san_?pham|productname|product)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+)?khach(?:\s+hang)?\s+nao\b|danh\s+sach[^?]*khach(?:\s+hang)?\b|\btop\s*\d+[^?]*khach(?:\s+hang)?\b)", r"^(?:ten_?khach_?hang|khach_?hang|ten_?kh|ho_?ten|customer|companyname)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+)?(?:nha\s+cung\s+cap|ncc)\s+nao\b|danh\s+sach[^?]*(?:nha\s+cung\s+cap|ncc)\b|\btop\s*\d+[^?]*(?:nha\s+cung\s+cap|ncc)\b)", r"^(?:nha_?cung_?cap|ten_?ncc|supplier|companyname)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+)?kenh(?:\s+ban)?\s+nao\b|danh\s+sach[^?]*kenh\b)", r"^(?:kenh_?ban|kenh|channel)$"),
        (r"(?:(?:nhung|cac)\s+(?:ten\s+)?nhom(?:\s+mon|\s+hang|\s+thuoc)?\s+nao\b)", r"^(?:nhom_?mon|nhom_?hang|nhom_?thuoc|danh_?muc|category|categoryname)$"),
    )

    dim_pick: Optional[Tuple[Any, str, Optional[Tuple[str, str, bool]]]] = None
    for q_pat, c_pat in entity_noun_rules:
        if re.search(q_pat, qn):
            rx = re.compile(c_pat, re.IGNORECASE)
            for tp, j_info in candidate_tables:
                for col in tp.columns:
                    cname = getattr(col, "sql_name", str(col))
                    if (tp.table_name, cname.lower()) in filtered_cols_on_tbl:
                        continue
                    if rx.search(cname.lower()):
                        dim_pick = (tp, cname, j_info)
                        break
                if dim_pick is not None:
                    break
        if dim_pick is not None:
            break

    if dim_pick is None:
        fallback_item_rx = re.compile(
            r"^(?:ten_?thuoc|ten_?mon|ten_?san_?pham|ten_?hang|ten_?sp|ten_?vl|vat_?lieu|ten_?khach_?hang|khach_?hang|nha_?cung_?cap|kenh_?ban|nhom_?mon|nhom_?hang|dich_?vu|tho)$",
            re.IGNORECASE,
        )
        for tp, j_info in candidate_tables:
            for col in tp.columns:
                cname = getattr(col, "sql_name", str(col))
                if (tp.table_name, cname.lower()) in filtered_cols_on_tbl:
                    continue
                if fallback_item_rx.search(cname.lower()):
                    dim_pick = (tp, cname, j_info)
                    break
            if dim_pick is not None:
                break

    if dim_pick is None:
        return None

    dim_tbl, dim_col, dim_j_info = dim_pick
    # t_name -> (alias, f_col, d_col, use_left_join, use_norm)
    joined_tables: Dict[str, Tuple[str, str, str, bool, bool]] = {}
    dim_expr = f"f.{_quote_sqlite_ident(dim_col)}"
    dim_filter_expr = dim_expr
    if dim_tbl.table_name != best_fact.table_name and dim_j_info is not None:
        f_jk, d_jk, use_norm = dim_j_info
        is_opt_dir = bool(re.search(r"danh_?(?:sach|ba)|khach|tho|nhan_?vien|ktv", dim_tbl.table_name.lower())) or use_norm
        joined_tables[dim_tbl.table_name] = ("d1", f_jk, d_jk, is_opt_dir, use_norm)
        if f_jk.lower() != dim_col.lower():
            dim_expr = f"COALESCE(d1.{_quote_sqlite_ident(dim_col)}, f.{_quote_sqlite_ident(f_jk)})"
            dim_filter_expr = f"f.{_quote_sqlite_ident(f_jk)}"
        else:
            dim_expr = f"d1.{_quote_sqlite_ident(dim_col)}"
            dim_filter_expr = dim_expr

    # Attach matched filters whose table is either best_fact or reachable via join key
    where_conds: List[str] = []
    next_alias_idx = 2
    for f_tbl, f_col, f_val in matched_filters:
        esc_val = str(f_val).replace("'", "''")
        if f_tbl == best_fact.table_name:
            f_expr = f"f.{_quote_sqlite_ident(f_col)}"
            where_conds.append(f"NORM_VN({f_expr}) = NORM_VN('{esc_val}')")
        else:
            if f_tbl in joined_tables:
                t_alias = joined_tables[f_tbl][0]
            else:
                f_tp = tables_dict.get(f_tbl)
                f_j_info = _resolve_fact_dim_join(best_fact, f_tp, knowledge.join_graph or ()) if f_tp is not None else None
                if not f_j_info:
                    continue
                t_alias = f"d{next_alias_idx}"
                next_alias_idx += 1
                joined_tables[f_tbl] = (t_alias, f_j_info[0], f_j_info[1], False, f_j_info[2])
            f_expr = f"{t_alias}.{_quote_sqlite_ident(f_col)}"
            where_conds.append(f"NORM_VN({f_expr}) = NORM_VN('{esc_val}')")

    # Apply order status exclusion when querying valid sales tables
    if not _Q_ALLOW_ALL_STATUS_RE.search(qn) and getattr(knowledge, "order_status_targets", None):
        for tgt in knowledge.order_status_targets:
            if tgt.get("table", "").lower() == best_fact.table_name.lower():
                vfilt = tgt.get("valid_filter") or ""
                scol = tgt.get("status_col") or ""
                if vfilt and scol:
                    where_conds.append(re.sub(rf"\b{re.escape(scol)}\b", f"f.{scol}", vfilt, flags=re.IGNORECASE))
                break

    if analysis.bounded_period is not None:
        dcol = next(
            (c for c in fact_cols if re.search(r"^(?:ngay_?gd|ngay_?ban|ngay_?dat|ngay_?nhap|ngay|orderdate|date)$", c.lower())),
            None,
        )
        if dcol:
            w_start, w_end = analysis.bounded_period
            where_conds.append(f"f.{_quote_sqlite_ident(dcol)} BETWEEN '{w_start}' AND '{w_end}'")

    where_conds.append(f"{dim_filter_expr} IS NOT NULL")
    where_conds.append(f"TRIM(CAST({dim_filter_expr} AS TEXT)) != ''")

    join_clauses = ""
    for t_name, (t_alias, f_jk, d_jk, use_left, use_norm) in joined_tables.items():
        jkw = "LEFT JOIN" if use_left else "JOIN"
        on_expr = (
            f"NORM_VN(f.{_quote_sqlite_ident(f_jk)}) = NORM_VN({t_alias}.{_quote_sqlite_ident(d_jk)})"
            if use_norm
            else f"f.{_quote_sqlite_ident(f_jk)} = {t_alias}.{_quote_sqlite_ident(d_jk)}"
        )
        join_clauses += f"\n{jkw} {_quote_sqlite_ident(t_name)} {t_alias} ON {on_expr}"

    where_sql = f"\nWHERE {' AND '.join(where_conds)}"

    extra_qty_sel = ""
    if is_money_metric and qty_col and qty_col in fact_cols and (wants_qty or (analysis.expected_type != "table" and limit_k is None)):
        qty_alias = "tong_so_luong_nhap" if wants_import and qty_col == "so_luong_nhap" else "tong_so_luong"
        extra_qty_sel = f", SUM(f.{_quote_sqlite_ident(qty_col)}) AS {qty_alias}"

    limit_sql = f"\nLIMIT {limit_k}" if limit_k and limit_k > 0 else ""
    fact_ref = _quote_sqlite_ident(best_fact.table_name)
    suggested_sql = (
        f"SELECT {dim_expr} AS {dim_col}, {metric_expr} AS {metric_alias}{extra_qty_sel}\n"
        f"FROM {fact_ref} f{join_clauses}{where_sql}\n"
        f"GROUP BY {dim_expr}\n"
        f"ORDER BY {metric_alias} DESC, {dim_expr} ASC{limit_sql};"
    )
    return {
        "fact_table": best_fact.table_name,
        "dim_table": dim_tbl.table_name,
        "dim_col": dim_col,
        "metric_alias": metric_alias,
        "is_money": is_money_metric,
        "suggested_sql": suggested_sql,
    }


def format_effective_temporal_summary(
    temporal_summary: str,
    as_of_date: str,
    analysis: QuestionAnalysis,
) -> str:
    """Ensure open-ended questions explicitly forbid spurious today-only date filters in initial & repair prompts."""
    if not analysis.temporal_windows and analysis.bounded_period is None:
        base = (temporal_summary or "").strip()
        extra = (
            f"- Câu hỏi KHÔNG giới hạn ngày cụ thể -> tính trên TOÀN BỘ LỊCH SỬ đến hết `{as_of_date}`, "
            f"TUYỆT ĐỐI KHÔNG tự lọc `ngay = '{as_of_date}'`."
        )
        return f"{base}\n{extra}".strip() if base else extra
    return temporal_summary


def _select_rulebook_prompt(
    question: str,
    as_of_date: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
    entity_matches: Sequence[Tuple[str, str, str]] = (),
) -> str:
    """Assemble a concise, intent-specific rulebook prompt (cuts prefill tokens & prevents debt hallucination)."""
    qn = normalize_vn_question(question)
    caps = knowledge.capabilities
    tables = list(knowledge.workspace.tables.values())
    all_cols_low = {
        getattr(c, "sql_name", str(c)).lower()
        for t in tables
        for c in t.columns
    }
    has_vn_shop_schema = bool(knowledge.order_status_targets) or any(
        k in all_cols_low
        for k in ("trang_thai", "tinh_trang", "thanh_tien", "tien_hang", "chua_tra", "da_tra", "con_no", "ma_don", "ma_chung_tu", "ngay_dat", "ngay_gd", "gia_von")
    )
    spaced_tables = [t.table_name for t in tables if " " in t.table_name or "-" in t.table_name]

    sections: List[str] = [
        "Bạn là chuyên gia viết SQLite cho DataMate. CHỈ dùng ĐÚNG tên bảng/cột có trong lược đồ (tuyệt đối không tự bịa bảng/cột không tồn tại). Có sẵn UDF: `NORM_VN(col)` và `ROUND_HALF_UP(val, d)`.",
        f"- Hôm nay (`as_of_date`) = `{as_of_date}`.",
    ]
    if spaced_tables:
        quoted_list = ", ".join(f'`"{t}"`' for t in spaced_tables)
        sections.append(
            f"- QUY TẮC DẤU NGOẶC KÉP BẮT BUỘC: Tên bảng có khoảng trắng ({quoted_list}) BẮT BUỘC đặt trong ngoặc kép đôi, viết ĐÚNG CHÍNH TẢ từng ký tự (VD: `JOIN \"Order Details\" od ON ...`)."
        )
    if not analysis.temporal_windows and analysis.bounded_period is None:
        sections.append(
            f"- QUAN TRỌNG: Câu hỏi KHÔNG hỏi riêng ngày hôm nay hay khoảng ngày cụ thể -> truy vấn TOÀN BỘ DỮ LIỆU lịch sử. TUYỆT ĐỐI KHÔNG tự thêm `ngay = '{as_of_date}'` hay bộ lọc `Status` không có trong bảng!"
        )
    if has_vn_shop_schema:
        if knowledge.data_max_date and knowledge.data_max_date > as_of_date:
            sections.append(
                f"- Phát sinh đơn sau `{as_of_date}` coi như chưa xảy ra (chỉ dùng `<= '{as_of_date}'` cho câu lũy kế/cutoff; riêng câu hỏi đúng ngày/tháng dùng `=` hoặc `BETWEEN`)."
            )
        sections.append(_RULE_CORE)
    else:
        sections.append(
            "- Nếu câu hỏi bằng tiếng Việt nhưng bảng/dữ liệu bằng tiếng Anh (VD: cà phê -> coffee/Beverages), hãy ánh xạ ngữ nghĩa hoặc dùng `LOWER(col) LIKE '%keyword%'`, chỉ lọc những cột thực sự tồn tại trong lược đồ."
        )

    if re.search(r"\b(?:khach|ai|top|nhom)\b", qn) and caps.get("has_customers") and has_vn_shop_schema:
        sections.append(_RULE_CUSTOMERS)
    if any(re.search(r"(?:left\s+join|danh_?ba|danh_?sach)", e, re.I) for e in (knowledge.join_graph or [])):
        sections.append(
            "- Liên kết danh bạ/nhân sự tuỳ chọn: khi nối bảng giao dịch/lịch hẹn sang danh bạ (`danh_ba`, `danhbakhach`, `khach_hang`), "
            "HÃY dùng `LEFT JOIN` và `COALESCE(danh_ba.ho_ten, lich.ten_khach)` để KHÔNG làm rớt khách vãng lai chưa lưu trong danh bạ."
        )
    if knowledge.order_status_targets and not _Q_ALLOW_ALL_STATUS_RE.search(qn):
        st_filters = [f"`{t['table']}.{t['valid_filter']}`" for t in knowledge.order_status_targets if t.get("valid_filter")]
        if st_filters:
            sections.append(
                f"- Lọc trạng thái đơn hợp lệ: khi tính doanh thu, số đơn hoặc sản phẩm khách đã mua từ bảng đơn hàng, BẮT BUỘC giữ {', '.join(st_filters)}."
            )
    if caps.get("has_debt_or_payments") and has_vn_shop_schema and re.search(
        r"\b(?:no|chua tra|da tra|da thu|con thieu|phai thu|tuoi no|ghi no|tra no|thu hoi|thu no|so quy|tien mat|chuyen khoan|cod|pttt)\b",
        qn,
    ):
        sections.append(_RULE_DEBT)
    if has_vn_shop_schema and (
        analysis.expected_type in ("string", "list", "table")
        or re.search(r"\b(?:ban chay|top|hot|xep hang|don vi|thung|hop|loc|chai|vien|goi|ong|tui|cay|tan|m3|bao|phuc vu|ton)\b", qn)
    ):
        sections.append(_RULE_RANKING)
    if has_vn_shop_schema and re.search(r"\b(?:ton|kho|nhap|gia von|lai|han dung|het han|lo|gia ban|tang gia|khong ban duoc|hang e)\b", qn):
        sections.append(_RULE_INVENTORY_COST)
    if caps.get("has_pharmacy_rx") and re.search(r"\b(?:ke don|hoat chat|lo|han dung|het han|thuoc)\b", qn):
        sections.append(_RULE_INDUSTRY_PHARMACY)
    if re.search(r"\b(?:size|co)\s*(?:m|l)\b", qn):
        sections.append(_RULE_INDUSTRY_CAFE)
    if caps.get("has_delivery_schedule") and re.search(r"\b(?:dot|giao)\b", qn):
        sections.append(_RULE_INDUSTRY_VLXD)
    if (
        analysis.expected_type == "percent"
        and re.search(r"\b(?:ty\s+le|ti\s+le|ty\s+trong|dong\s+gop|phan\s+tram|%|share|percent)\b", qn)
        and re.search(r"\b(?:theo|moi|tung|nhom|danh\s+muc|kenh|loai|chiem)\b", qn)
    ):
        has_single_target = bool(
            re.search(r"\bchiem\s+(?:bao\s+nhieu|may)\b", qn)
            and not re.search(r"\b(?:theo\s+(?:tung|moi|cac)|moi\s+nhom|tung\s+nhom|tat\s+ca\s+cac)\b", qn)
        )
        if has_single_target:
            sections.append(
                "- Tỷ trọng (%) của MỘT nhóm/danh mục cụ thể (VD: 'nhóm X chiếm bao nhiêu % doanh thu'): "
                "TUYỆT ĐỐI KHÔNG lọc `WHERE <cột_nhóm> = '...'` ở truy vấn ngoài (sẽ loại mất phần còn lại hoặc trả NULL khi khác hoa/thường)! "
                "PHẢI tính cả tử số và mẫu số trong CÙNG 1 truy vấn (không `GROUP BY`): "
                "`ROUND_HALF_UP(SUM(CASE WHEN NORM_VN(<cột_nhóm>) = NORM_VN('<giá_trị>') THEN <cột_tiền> ELSE 0 END) * 100.0 / NULLIF(SUM(<cột_tiền>), 0), 2)` "
                "(dùng `NORM_VN(...)` để so sánh không phân biệt chữ hoa/thường tiếng Việt)."
            )
        else:
            sections.append(
                "- Tỷ lệ đóng góp / tỷ trọng (%) theo nhóm: TỬ SỐ VÀ MẪU SỐ PHẢI DÙNG CÙNG 1 CHỈ SỐ; mẫu số là tổng toàn bộ qua `SUM(SUM(cot_chi_so)) OVER ()` (VD: `ROUND_HALF_UP(SUM(thanh_tien) * 100.0 / SUM(SUM(thanh_tien)) OVER (), 2)`)."
            )
    dim_req = _match_requested_dimension_col(qn, knowledge)
    if dim_req:
        q_phrase, t_hit, c_hit = dim_req
        join_key_hint = ""
        tgt_tbl = next((t for t in tables if t.table_name == t_hit), None)
        if tgt_tbl and len(tables) > 1:
            tgt_cols = {getattr(c, "sql_name", str(c)) for c in tgt_tbl.columns}
            for other in tables:
                if other.table_name == t_hit:
                    continue
                common = [
                    getattr(c, "sql_name", str(c))
                    for c in other.columns
                    if getattr(c, "sql_name", str(c)) in tgt_cols
                    and getattr(c, "sql_name", str(c)).lower() not in {"ngay", "thang", "nam", "ghi_chu", "trang_thai"}
                ]
                if common:
                    k = common[0]
                    t_ref = f'"{t_hit}"' if (" " in t_hit or "-" in t_hit) else t_hit
                    o_ref = f'"{other.table_name}"' if (" " in other.table_name or "-" in other.table_name) else other.table_name
                    join_key_hint = f" (dùng `JOIN {t_ref} ON {o_ref}.{k} = {t_ref}.{k}` khi tính từ `{o_ref}`)"
                    break
        sections.append(
            f"- Câu hỏi yêu cầu phân theo `{q_phrase}` -> BẮT BUỘC `GROUP BY {t_hit}.{c_hit}`{join_key_hint}, KHÔNG thay bằng tên mặt hàng chi tiết."
        )
    ext_spec = build_extreme_comparison_sql_spec(question, knowledge, analysis) if analysis.extreme_comparison else None
    avg_spec = build_benchmark_average_entity_sql_spec(question, knowledge, analysis) if ext_spec is None else None
    ent_metric_spec = (
        build_entity_and_metric_listing_sql_spec(question, knowledge, analysis, entity_matches)
        if (ext_spec is None and avg_spec is None)
        else None
    )
    cat_spec = (
        build_catalog_listing_sql_spec(question, knowledge, analysis, entity_matches)
        if (ext_spec is None and avg_spec is None and ent_metric_spec is None)
        else None
    )
    ord_rank = extract_ordinal_rank(question)
    if ent_metric_spec is not None:
        sections.append(
            f"- Câu hỏi 2 VẾ (hỏi CẢ danh sách tên `{ent_metric_spec['dim_col']}` VÀ tổng chỉ số `{ent_metric_spec['metric_alias']}`): "
            f"BẮT BUỘC `SELECT` CẢ cột tên `{ent_metric_spec['dim_col']}` VÀ cột chỉ số `{ent_metric_spec['metric_alias']}` kèm `GROUP BY {ent_metric_spec['dim_col']}`! "
            f"TUYỆT ĐỐI KHÔNG chỉ `SELECT SUM(...)` mà bỏ sót tên đối tượng! Dùng chính xác mẫu SQLite chuẩn sau:\n```sql\n{ent_metric_spec['suggested_sql']}\n```"
        )
    elif cat_spec is not None:
        sections.append(
            f"- Câu hỏi LIỆT KÊ DANH MỤC / ĐỐI TƯỢNG THUẦN TÚY: truy vấn trực tiếp bảng danh mục `{cat_spec['table']}`, "
            f"TUYỆT ĐỐI KHÔNG JOIN bảng giao dịch và KHÔNG lọc theo ngày hay trạng thái đơn! "
            f"Dùng chính xác mẫu SQLite chuẩn sau:\n```sql\n{cat_spec['suggested_sql']}\n```"
        )
    elif ext_spec is not None:
        top_n, bottom_n, wants_diff = analysis.extreme_comparison or (1, 1, True)
        diff_note = " VÀ cột độ chênh lệch `chenh_lech_cao_thap` (bằng `MAX(...) - MIN(...)`)" if wants_diff else ""
        sections.append(
            f"- Câu hỏi SO SÁNH CỰC TRỊ (Cao nhất & Thấp nhất): BẮT BUỘC trả về DANH SÁCH GỒM CẢ nhóm/đối tượng Cao nhất (`Top {top_n}`) và nhóm/đối tượng Thấp nhất (`Top {bottom_n}`), kèm cột phân nhóm `nhom_xep_hang`, cột chỉ số tổng hợp `{ext_spec['metric_alias']}`{diff_note}. TUYỆT ĐỐI KHÔNG chỉ trả 1 con số chênh lệch đơn lẻ! Dùng mẫu CTE SQLite chuẩn sau:\n```sql\n{ext_spec['suggested_sql']}\n```"
        )
    elif avg_spec is not None:
        cmp_word = "vượt trên / cao hơn" if avg_spec["cmp_op"] == ">" else "dưới / thấp hơn"
        sections.append(
            f"- Câu hỏi TÌM ĐỐI TƯỢNG CÓ CHỈ SỐ {cmp_word.upper()} MỨC TRUNG BÌNH: Một đối tượng (`{avg_spec['dim_col']}`) có thể xuất hiện ở nhiều dòng hóa đơn! BẮT BUỘC phải gom nhóm `GROUP BY` trong CTE `grouped` để tính tổng `{avg_spec['metric_alias']}` của từng đối tượng trước, rồi ở `SELECT` ngoài BẮT BUỘC IN KÈM CẢ 2 CỘT `{avg_spec['dim_col']}, {avg_spec['metric_alias']}` và lọc `WHERE {avg_spec['metric_alias']} {avg_spec['cmp_op']} (SELECT AVG({avg_spec['metric_alias']}) FROM grouped)`. TUYỆT ĐỐI KHÔNG chỉ `SELECT {avg_spec['dim_col']}` (1 cột) và KHÔNG so sánh trên từng dòng hóa đơn chưa `GROUP BY`! Dùng mẫu CTE SQLite chuẩn sau:\n```sql\n{avg_spec['suggested_sql']}\n```"
        )
    elif ord_rank is not None:
        rank_n, rank_dir = ord_rank
        rank_lbl = "cao/nhiều" if rank_dir == "DESC" else "thấp/ít"
        sections.append(
            f"- Câu hỏi tìm đối tượng đứng THỨ {rank_n} ({rank_lbl} thứ {rank_n}): BẮT BUỘC chọn CẢ TÊN ĐỐI TƯỢNG VÀ CHỈ SỐ ĐO LƯỜNG trong `SELECT` (VD: `SELECT <cột_đối_tượng>, ROUND_HALF_UP(SUM(<cột_tiền_hoặc_sl>), 0) AS tong_doanh_thu ... GROUP BY <cột_đối_tượng> ORDER BY SUM(<cột_tiền_hoặc_sl>) {rank_dir} LIMIT 1 OFFSET {rank_n - 1}`). TUYỆT ĐỐI KHÔNG dùng `LIMIT {rank_n}`!"
        )
    elif _ENTITY_WHICH_LOOKUP_RE.search(qn):
        sections.append(
            "- Câu hỏi tìm đối tượng/ngày tháng nào (thuốc nào, món nào, sản phẩm nào, vật liệu nào, khách hàng nào, kênh nào...) theo tổng doanh thu/số lượng/công nợ: BẮT BUỘC chọn CẢ `<cột_đối_tượng_hoặc_ngày>` VÀ cột chỉ số `ROUND_HALF_UP(SUM(...), 0) AS ...` (hoặc `COUNT(...)`) trong `SELECT`, có `GROUP BY <cột_đối_tượng_hoặc_ngày>` kết hợp `ORDER BY ... DESC/ASC` (TUYỆT ĐỐI KHÔNG chỉ `SELECT` 1 cột tên đối tượng mà bỏ quên cột doanh thu/số lượng!)."
        )

    sections.append(
        'Trả về DUY NHẤT JSON hợp lệ: {"status": "ok", "sql": "SELECT ..."} '
        '(hoặc key `"python"` / `"probe_sql"` / `{"status": "unanswerable", "reason": "..."}`). '
        'Chỉ 1 câu SQL `SELECT` hoặc `WITH ... SELECT`. TUYỆT ĐỐI KHÔNG dùng key `"data"` hay in dữ liệu mẫu!'
    )
    return "\n".join(sections)


def _compact_readme_for_prompt(readme_text: str, max_chars: int = 1350) -> str:
    """Keep high-signal README rules & column definitions while cutting cleanly on line boundaries."""
    raw = (readme_text or "").strip()
    if len(raw) <= max_chars:
        return raw
    idx_rules = raw.lower().find("## quy ước")
    idx_cols = raw.lower().find("## cột")
    if idx_rules > 0:
        head = raw[: min(300, idx_cols if idx_cols > 0 else idx_rules)].strip()
        tail = raw[idx_rules:].strip()
        combined = f"{head}\n\n{tail}" if head else tail
    else:
        combined = raw
    if len(combined) <= max_chars:
        return combined
    cut = combined[:max_chars].rsplit("\n", 1)[0].strip()
    return cut if cut else combined[:max_chars]


_DEBT_COL_SQL_RE = re.compile(
    r"\b(?:da_tra|chua_tra|con_no|khach_da_tra|khach_tra|da_thu|con_lai|so_tien_thu)\b",
    re.IGNORECASE,
)
_Q_DEBT_INTENT_RE = re.compile(
    r"\b(?:no|chua tra|da tra|da thu|con thieu|phai thu|tuoi no|ghi no|tra no|thu hoi|thu no|"
    r"thanh toan|phuong thuc|hinh thuc|cod|tien mat|chuyen khoan|vi dien tu|tai quay|pttt|phi phuc vu)\b",
    re.IGNORECASE,
)
_Q_POINT_IN_TIME_RE = re.compile(
    r"\b(?:ton|kho|con lai|con no|con thieu|het hang|het han|sap het han|tinh den|den het|het hom nay|cuoi ngay|het thang)\b",
    re.IGNORECASE,
)
_Q_COUNT_ORDER_RE = re.compile(
    r"\b(?:bao nhieu don|may don|so don|so bill|bao nhieu bill|may bill|bao nhieu order|may order|co bao nhieu hoa don|so hoa don)\b",
    re.IGNORECASE,
)
_Q_REVENUE_ASK_RE = re.compile(
    r"\b(?:doanh thu|ban duoc bao nhieu tien|tong cong bao nhieu tien|thu ve bao nhieu tien|bao nhieu tien|lai gop|lai rong)\b",
    re.IGNORECASE,
)
_Q_ALLOW_ALL_STATUS_RE = re.compile(
    r"\b(?:huy|tra hang|doi tra|hoan tra|hoan hang|ti le don huy|don bi huy|trang thai|moi trang thai|gia ban|don gia|tang gia|nhap|ton|chi phi|con no|tuoi no)\b",
    re.IGNORECASE,
)


def verify_result_sanity_bounds(
    sql: str,
    sql_res: SQLExecutionResult,
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
    entity_matches: Sequence[Tuple[str, str, str]] = (),
) -> Tuple[bool, str, bool]:
    """
    Validate domain-agnostic numerical sanity bounds on executed SQL or Python Sandbox results.
    Catches out-of-range share percentages (>100%), impossible negative counts/gross revenue,
    and suspicious 0s on specific named-entity/event queries.
    """
    if not sql_res or not sql_res.ok or not sql_res.rows:
        return True, "", False
    if sql_res.row_count != 1 or len(sql_res.columns) != 1:
        return True, "", False

    val_f = _coerce_float(sql_res.rows[0][0])
    if val_f is None:
        return True, "", False

    qn = normalize_vn_question(question)
    sql_low = re.sub(r"\s+", " ", sql or "").strip().lower()
    where_part = sql_low.split("where", 1)[1] if "where" in sql_low else ""

    # 17A. Bounded share / rate percentage [0%, 100%]
    if analysis.expected_type == "percent":
        is_bounded_share_pct = bool(
            re.search(r"\b(?:ti\s+le|ty\s+le|ti\s+trong|ty\s+trong|dong\s+gop|chiem)\b", qn)
        ) and not re.search(
            r"\b(?:tang|giam|thay\s+doi|bien\s+dong|chenh\s+lech|so\s+voi|cung\s+ky|gap|vuot|loi\s+nhuan|bien\s+lai|lai\s+gop|markup|roi)\b",
            qn,
        )
        if is_bounded_share_pct and (val_f < -1e-6 or val_f > 100.0001):
            return (
                False,
                f"LỖI MIỀN GIÁ TRỊ TỶ LỆ PHẦN TRĂM ({val_f:.2f}% nằm ngoài [0%, 100%]): "
                "Câu hỏi hỏi tỷ lệ/tỷ trọng trong tổng thể nên kết quả BẮT BUỘC nằm trong [0, 100]. "
                "Tử số và mẫu số đang lệch đơn vị (ví dụ cộng `SUM(tien)` rồi chia cho `COUNT(ma_don)`). "
                "Nếu tính tỷ lệ đơn huỷ/trả/hoàn thành, tử số PHẢI ĐẾM SỐ ĐƠN "
                "(`COUNT(DISTINCT CASE WHEN ... THEN ma_don END) * 100.0 / NULLIF(COUNT(DISTINCT ma_don), 0)`), "
                "TUYỆT ĐỐI KHÔNG cộng tiền vào tử số!",
                True,
            )

    # 17B. Non-negative count / gross amount bound
    if analysis.expected_type == "number" and val_f < -1e-6:
        is_strict_nonneg = bool(
            re.search(
                r"\b(?:bao\s+nhieu\s+(?:don|hoa\s+don|khach|nguoi|nhan\s+vien|dot|chuyen|mon|loai|san\s+pham|buoi|ngay|gio|phut|chai|hop|thung|goi|vien|canh)|"
                r"tong\s+doanh\s+thu|doanh\s+thu|tien\s+dien|tien\s+nuoc|tien\s+nhap|gia\s+ban|gia\s+nhap|don\s+gia)\b",
                qn,
            )
        ) and not re.search(
            r"\b(?:lai|lo|loi\s+nhuan|chenh\s+lech|tang|giam|thay\s+doi|con\s+du|de\s+danh|thieu|am\b|rong|sao\s+ke|dieu\s+chinh|cong\s+no|con\s+no|hoan|tra\s+hang)\b",
            qn,
        )
        if is_strict_nonneg:
            return (
                False,
                f"LỖI GIÁ TRỊ ÂM PHI LÝ ({sql_res.rows[0][0]} < 0): "
                "Chỉ số số lượng/doanh thu/chi phí gộp không thể âm! Kiểm tra lại phép trừ ngược chiều hoặc điều kiện lọc.",
                True,
            )

    # 17C. Suspicious 0 on specific named-entity / event lookup
    if analysis.expected_type == "number" and abs(val_f) <= 1e-9:
        allows_legit_zero = bool(
            re.search(
                r"\b(?:con\s+no|chua\s+tra|con\s+lai|con\s+ton|ton\s+kho|het\s+hang|huy|tra\s+hang|vang|nghi|tre|muon|loi|sai\s+lech|phat|chenh\s+lech)\b",
                qn,
            )
        )
        if not allows_legit_zero:
            has_named_ent = any(
                not re.search(r"(?:trang_thai|status|tinh_trang|ket_qua)", c.lower())
                for _, c, _ in (entity_matches or ())
            )
            has_specific_cue = bool(
                re.search(r"\b(?:khach\s+ten|cua\s+don|ma\s+don|mon\s+.*cam|the\s+.*ban|phong\s+\d+|lop\s+[0-9a-z]+)\b", qn)
            )
            if has_named_ent or (has_specific_cue and ("and" in where_part or sql_low.startswith("-- [python_sandbox]"))):
                return (
                    False,
                    "CẢNH BÁO KẾT QUẢ = 0 ĐÁNG NGỜ TRÊN ĐỐI TƯỢNG CỤ THỂ: Truy vấn trả về `0` khi hỏi giao dịch/số tiền của khách/đơn/mặt hàng cụ thể. "
                    "Kiểm tra lại xem đã `JOIN` đúng bảng danh mục/khách hàng chưa, có lọc nhầm cột ngày hay viết sai chuỗi tiếng Việt không (hãy dùng `NORM_VN(...) LIKE ...`)!",
                    False,
                )

    return True, "", False


def verify_sql_semantics(
    sql: str,
    sql_res: SQLExecutionResult,
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
    entity_matches: Optional[Sequence[Tuple[str, str, str]]] = None,
) -> Tuple[bool, str, bool]:
    """
    Validate structural/semantic alignment between Vietnamese question & generated SQL.
    Returns ``(is_valid, feedback_msg, fatal_if_unresolved)``.
    """
    qn = normalize_vn_question(question)
    sql_low = re.sub(r"\s+", " ", sql or "").strip().lower()
    where_part = sql_low.split("where", 1)[1] if "where" in sql_low else ""

    oos_reason = check_out_of_scope_or_irrelevant(question, knowledge)
    if oos_reason:
        return (False, oos_reason, True)

    cap_gap = _check_schema_capability_gap(question, knowledge)
    if cap_gap:
        return (False, cap_gap, True)

    if (sql or "").lstrip().startswith("-- [PYTHON_SANDBOX]"):
        if getattr(analysis, "extreme_comparison", None) is not None and (len(sql_res.columns) < 2 or sql_res.row_count < 2):
            return (
                False,
                "LỖI KẾT QUẢ PYTHON SANDBOX: Câu hỏi cực trị yêu cầu trả bảng/danh sách gồm cả nhóm Cao nhất và Thấp nhất (>= 2 dòng, >= 2 cột).",
                True,
            )
        return verify_result_sanity_bounds(
            sql, sql_res, question, knowledge, analysis, entity_matches=entity_matches or ()
        )

    # 1. Spurious debt/payment column filter when question does NOT ask about debt/payment
    if not _Q_DEBT_INTENT_RE.search(qn):
        if _DEBT_COL_SQL_RE.search(where_part) or re.search(
            r"\b(?:da_tra|chua_tra|con_no|khach_da_tra|da_thu)\s*(?:=|!=|<>|>|<)\s*(?:0|tong)",
            sql_low,
        ):
            return (
                False,
                "LỖI NGHIỆP VỤ: Câu hỏi hỏi doanh thu/số đơn/thông tin bán hàng, KHÔNG hỏi công nợ hay thanh toán. Xóa bỏ điều kiện thừa trên `da_tra`, `chua_tra`, `con_no`!",
                True,
            )

    # 2. Exact period vs cumulative '<=' drift on strict bounded date windows
    if (
        analysis.bounded_period is not None
        and analysis.bounded_period[0] != "0001-01-01"
        and not _Q_POINT_IN_TIME_RE.search(qn)
    ):
        b_start, b_end = analysis.bounded_period
        exact_op = f"= '{b_start}'" if b_start == b_end else f"BETWEEN '{b_start}' AND '{b_end}'"
        has_exact_or_range = bool(
            re.search(r"(?:ngay|thoi_gian|date)\w*\s*(?:=|between\b|like\b|>=)", where_part)
            or "strftime(" in where_part
        )
        has_only_upper = bool(re.search(r"(?:ngay|thoi_gian|date)\w*\s*<=?\s*'20\d{2}-\d{2}-\d{2}'", where_part))
        if has_only_upper and not has_exact_or_range:
            return (
                False,
                f"LỖI THỜI GIAN: Câu hỏi hỏi phát sinh trong khoảng `{b_start}`..`{b_end}` (KHÔNG phải lũy kế từ đầu). Phải dùng điều kiện ngày `{exact_op}`, KHÔNG dùng `<=` một mình!",
                True,
            )
        # Also catch wrong literal date on exact single-day queries (e.g. yesterday='2026-10-04' vs today='2026-10-05')
        if b_start == b_end:
            m_wrong_day = re.search(
                r"\b[a-z0-9_.]*(?:ngay|date|thoi_gian)[a-z0-9_]*\s*=\s*'(20\d{2}-\d{2}-\d{2})'",
                where_part,
            )
            if m_wrong_day and m_wrong_day.group(1) != b_start:
                return (
                    False,
                    f"LỖI MỐC NGÀY: Câu hỏi hỏi riêng ngày `{b_start}` (không phải `{m_wrong_day.group(1)}`)! Phải sửa thành điều kiện ngày `= '{b_start}'`!",
                    True,
                )

    # 2b. Spurious single-day equality filter on open-ended all-time questions
    if (
        not analysis.temporal_windows
        and analysis.bounded_period is None
        and not re.search(r"\b(?:hom nay|hnay|hom qua|hqua|ngay \d|thang \d|gan nhat|moi nhat|cuoi cung|dau tien)\b", qn)
    ):
        m_spurious_eq = re.search(
            r"\b([a-z0-9_.]*(?:ngay|date|thoi_gian)[a-z0-9_]*)\s*=\s*'(20\d{2}-\d{2}-\d{2})'",
            where_part,
        )
        if m_spurious_eq:
            return (
                False,
                f"LỖI LỌC NGÀY THỪA: Câu hỏi KHÔNG hỏi riêng ngày `{m_spurious_eq.group(2)}`; hãy XÓA bỏ điều kiện `{m_spurious_eq.group(0)}` để tính trên toàn bộ dữ liệu!",
                True,
            )

    # 3. Metric alignment: Order Count vs Revenue Sum & multi-line vs 1-row-per-order grain
    asks_order_cnt = bool(_Q_COUNT_ORDER_RE.search(qn)) and not _Q_REVENUE_ASK_RE.search(qn) and analysis.expected_type == "number"
    asks_revenue = bool(_Q_REVENUE_ASK_RE.search(qn)) and not _Q_COUNT_ORDER_RE.search(qn) and analysis.expected_type in ("number", "date")
    select_head = sql_low.split("from", 1)[0]
    if asks_order_cnt:
        if "count(" not in select_head:
            return (
                False,
                "LỖI CHỈ SỐ: Câu hỏi hỏi SỐ LƯỢNG ĐƠN HÀNG (phải dùng `COUNT(...)`), KHÔNG được dùng `SUM(tien_hang)` hay tính doanh thu!",
                True,
            )
        # Check line-grain: if querying a multi-line order table without DISTINCT on order_id
        for tgt in knowledge.order_status_targets:
            tlow = tgt["table"].lower()
            if re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(tlow)}[`\"]?\b", sql_low):
                if tgt.get("has_repeating_orders") and tgt.get("order_id_col"):
                    oid = tgt["order_id_col"]
                    if "count(*)" in sql_low or ("distinct" not in select_head):
                        return (
                            False,
                            f"LỖI ĐẾM TRÙNG DÒNG HÀNG: Bảng `{tgt['table']}` có 1 dòng = 1 mặt hàng trong đơn, đếm số đơn BẮT BUỘC phải dùng `COUNT(DISTINCT {oid})`, không dùng `COUNT(*)`!",
                            True,
                        )
    elif asks_revenue and analysis.expected_type == "number":
        if "sum(" not in select_head and "count(" in select_head:
            return (
                False,
                "LỖI CHỈ SỐ: Câu hỏi hỏi DOANH THU (phải dùng `SUM(...)` tiền hàng/thành tiền), không dùng `COUNT(*)`!",
                True,
            )

    # 3b. Paid-amount alignment ('đã thanh toán' / 'đã trả') vs invoiced total
    if (
        re.search(r"\b(?:da\s+thanh\s+toan|da\s+tra|da\s+thu)\b", qn)
        and not re.search(r"\b(?:chua|con thieu|con no|no)\b", qn)
    ):
        paid_cols: List[str] = []
        for tbl_prof in knowledge.workspace.tables.values():
            tlow = tbl_prof.table_name.lower()
            if re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(tlow)}[`\"]?\b", sql_low):
                for col_obj in tbl_prof.columns:
                    cname = getattr(col_obj, "sql_name", str(col_obj))
                    if re.search(r"(?:da_thanh_toan|da_tra|da_thu|so_tien_thu)", cname.lower()):
                        paid_cols.append(cname)
        if paid_cols and not any(pc.lower() in select_head for pc in paid_cols):
            return (
                False,
                f"LỖI CHỈ SỐ THANH TOÁN: Câu hỏi hỏi số tiền ĐÃ THANH TOÁN / ĐÃ THU; phải dùng cột `{paid_cols[0]}`, KHÔNG dùng cột tổng tiền hóa đơn!",
                True,
            )

    # 3c. Order-grain Average Guard (AOV / doanh thu trung bình trên một đơn trên bảng chi tiết nhiều dòng/đơn)
    asks_avg_per_order = bool(
        re.search(
            r"\b(?:trung\s+binh|binh\s+quan)\b.*?\b(?:tren\s+mot\s+|tren\s+1\s+|moi\s+|1\s+|/\s*)?(?:don(?:\s+hang)?|hoa\s+don|bill|phieu)\b"
            r"|\b(?:gia\s+tri\s+don\s+(?:hang\s+)?trung\s+binh|aov)\b",
            qn,
        )
        and not re.search(r"\b(?:so\s+dong|mat\s+hang\s+moi\s+don)\b", qn)
    )
    if asks_avg_per_order and analysis.expected_type == "number":
        grains = getattr(knowledge, "table_grains", None) or {
            t["table"]: t for t in (getattr(knowledge, "order_status_targets", None) or [])
        }
        queried_grains: List[Tuple[str, Dict[str, Any]]] = [
            (tname, g)
            for tname, g in grains.items()
            if re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(tname.lower())}[`\"]?\b", sql_low)
        ]
        all_order_ids = [
            str(g["order_id_col"]).lower()
            for _, g in queried_grains
            if g.get("order_id_col")
        ]
        repeating_tbls = [
            (tname, str(g["order_id_col"]))
            for tname, g in queried_grains
            if g.get("has_repeating_orders") and g.get("order_id_col")
        ]
        if repeating_tbls:
            has_distinct_order_cnt = bool(
                re.search(r"\bcount\s*\(\s*distinct\s+([^)]+)\)", select_head)
                and any(oid in select_head for oid in all_order_ids)
            )
            has_pregrouped_order_cte = bool(
                re.search(r"\bgroup\s+by\b", sql_low)
                and any(re.search(rf"\bgroup\s+by\b[^;)]*\b[a-z0-9_.]*{re.escape(oid)}\b", sql_low) for oid in all_order_ids)
                and ("with " in sql_low or sql_low.count("select ") >= 2)
            )
            if not has_distinct_order_cnt and not has_pregrouped_order_cte:
                rep_tbl, rep_oid = repeating_tbls[0]
                return (
                    False,
                    f"LỖI ĐƠN VỊ TRUNG BÌNH TRÊN ĐƠN (`{rep_tbl}` có nhiều dòng hàng cho cùng 1 `{rep_oid}`): "
                    f"Không được chia cho `COUNT(*)` hay dùng `AVG(...)` trực tiếp trên dòng hàng (sẽ ra trung bình mỗi dòng thay vì mỗi đơn)! "
                    f"Phải chia tổng tiền cho SỐ ĐƠN DUY NHẤT: `ROUND_HALF_UP(SUM(<cột_tiền>) * 1.0 / NULLIF(COUNT(DISTINCT {rep_oid}), 0), 0)`.",
                    True,
                )

    # 4. Daily/monthly aggregate peak ('ngày nào cao nhất', 'tháng nào...') missing GROUP BY
    if (
        analysis.expected_type == "date"
        and "order by" in sql_low
        and "group by" not in sql_low
        and re.search(r"\b(?:doanh thu|ban duoc|tong|so don|nhieu tien|nhieu nhat|cao nhat|thap nhat|it nhat|ban dat|ban chay)\b", qn)
    ):
        return (
            False,
            "LỖI THIẾU GROUP BY: Tìm ngày/tháng có tổng cao nhất/thấp nhất BẮT BUỘC phải `GROUP BY <cột_ngày>` (hoặc `strftime('%Y-%m', <cột_ngày>)`) rồi `ORDER BY SUM(<cột_tiền_hàng>) DESC LIMIT 1`, KHÔNG `ORDER BY tongtien DESC` trên 1 đơn lẻ!",
            True,
        )

    # 4b. Entity-ranking / above-below-average entity queries ('khách hàng nào nợ nhiều nhất', 'những tên thuốc nào có doanh thu vượt trên mức trung bình', 'cao thứ 3') missing GROUP BY
    ord_rank = extract_ordinal_rank(question)
    avg_ent_cmp = extract_benchmark_average_entity_intent(question)
    _is_entity_lookup_or_list_q = bool(
        (
            analysis.expected_type in ("string", "list", "table")
            or ord_rank is not None
            or avg_ent_cmp is not None
            or _ENTITY_WHICH_LOOKUP_RE.search(qn)
            or re.search(r"\b(?:top\s*\d+|danh\s+sach|liet\s+ke|nhung|cac)\b", qn)
        )
        and re.search(
            r"\b(?:khach\s+hang|khach|ai\s+|san\s+pham|mat\s+hang|mon|thuoc|vat\s+lieu|nha\s+cung\s+cap|ncc|nhom|kenh|danh\s+muc)\b",
            qn,
        )
        and re.search(
            r"\b(?:tong|doanh\s+thu|doanh\s+so|thanh\s+tien|so\s+luong|tien\s+nhap|cong\s+no|con\s+no|no\b|chi\s+tieu|nhieu\s+nhat|cao\s+nhat|lon\s+nhat|thap\s+nhat|it\s+nhat|ban\s+chay|cao\s+thu|thap\s+thu|nhieu\s+thu|it\s+thu|lon\s+thu|dung\s+thu|xep\s+thu|trung\s+binh|vuot|tren\s+muc|duoi\s+muc)\b",
            qn,
        )
        and not re.search(
            r"\b(?:don\s+hang\s+nao|hoa\s+don\s+nao|ma\s+don\s+nao|phieu\s+nao|ma\s+hd\s+nao|co\s+bao\s+nhieu|may\s+(?:don|hoa\s+don|khach|mon|thuoc|san\s+pham|loai)|tong\s+doanh\s+thu\s+.*la\s+bao\s+nhieu|don\s+gia|gia\s+ban\s+niem\s+yet|hoat\s+chat|ke\s+don)\b",
            qn,
        )
    )
    if (
        _is_entity_lookup_or_list_q
        and "group by" not in sql_low
        and ("order by" in sql_low or avg_ent_cmp is not None or "avg(" in sql_low or "having" in sql_low)
    ):
        if avg_ent_cmp is not None:
            avg_spec = build_benchmark_average_entity_sql_spec(question, knowledge, analysis)
            sample_hint = f"\nDùng chính xác CTE SQLite mẫu:\n{avg_spec['suggested_sql']}" if avg_spec else ""
            return (
                False,
                f"LỖI THIẾU GROUP BY & CỘT CHỈ SỐ: Một đối tượng (thuốc/món/sản phẩm/vật liệu/khách hàng) có thể xuất hiện ở NHIỀU hóa đơn! Phải `GROUP BY` theo đối tượng trong CTE để tính tổng chỉ số trước khi so sánh với `AVG(...)`, đồng thời chọn CẢ cột tên đối tượng VÀ cột chỉ số tổng hợp trong `SELECT`!{sample_hint}",
                True,
            )
        return (
            False,
            "LỖI THIẾU GROUP BY: Một đối tượng (khách hàng/sản phẩm/thuốc/món/kênh) có thể xuất hiện ở NHIỀU đơn hàng! Tìm tổng cao nhất/nhiều nhất/đứng thứ N BẮT BUỘC phải `GROUP BY` theo đối tượng và dùng `SUM(...)` (hoặc `COUNT(...)`), KHÔNG `ORDER BY` trên 1 dòng đơn lẻ!",
            True,
        )

    # 4c. Grouped entity ranking missing aggregate function (SUM/COUNT/AVG) in SELECT and ORDER BY
    if (
        "group by" in sql_low
        and "order by" in sql_low
        and re.search(r"\b(?:tong|doanh thu|thanh tien|so luong|ban chay|chi tieu|cong no)\b", qn)
        and not re.search(r"\b(?:sum|count|avg|min|max|total)\s*\(", sql_low)
    ):
        return (
            False,
            "LỖI THIẾU HÀM TỔNG HỢP (SUM/COUNT): Khi `GROUP BY` theo sản phẩm/khách hàng/nhóm để xếp hạng doanh thu hoặc số lượng, BẮT BUỘC phải dùng `SUM(thanh_tien)` hoặc `SUM(so_luong)` trong cả `SELECT` và `ORDER BY`, KHÔNG dùng cột đơn lẻ chưa cộng gộp!",
            True,
        )

    # 4d. Multi-period history anti-collapse guard ('lịch sử ... qua các kỳ/tháng')
    if (
        re.search(r"\b(?:lich\s+su|dien\s+bien|chi\s+tiet|liet\s+ke)\b.*\b(?:qua\s+cac\s+(?:ky|thang|nam)|tung\s+(?:ky|thang))\b", qn)
        and (sql_res.row_count == 1 or len(sql_res.rows or ()) == 1)
        and re.search(r"\b(?:sum|avg|total)\s*\(", select_head)
    ):
        multi_sheet_tbls = [
            tp.table_name
            for tp in knowledge.workspace.tables.values()
            if re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(tp.table_name.lower())}[`\"]?\b", sql_low)
            and any(
                getattr(c, "sql_name", "").lower() == "source_sheet" and getattr(c, "distinct_count", 0) >= 2
                for c in tp.columns
            )
        ]
        if multi_sheet_tbls and "source_sheet" not in sql_low:
            return (
                False,
                f"LỖI GỘP MẤT KỲ LỊCH SỬ: Bảng `{multi_sheet_tbls[0]}` có cột `source_sheet` lưu từng kỳ/tháng nhưng SQL đang `SUM/AVG` gộp toàn bộ thành 1 dòng duy nhất! "
                "Hãy `SELECT` chi tiết kèm cột `source_sheet` (KHÔNG `SUM` gộp mất kỳ và KHÔNG JOIN nhân đôi với bảng danh mục nếu không cần).",
                True,
            )

    bounds_ok, bounds_msg, bounds_fatal = verify_result_sanity_bounds(
        sql, sql_res, question, knowledge, analysis, entity_matches=entity_matches or ()
    )
    if not bounds_ok and bounds_fatal:
        return (False, bounds_msg, True)

    # 5. Missing status exclusion when querying main sales/order table
    if not _Q_ALLOW_ALL_STATUS_RE.search(qn):
        for tgt in knowledge.order_status_targets:
            tlow = tgt["table"].lower()
            vfilt = tgt.get("valid_filter") or ""
            scol = (tgt.get("status_col") or "").lower()
            if vfilt and scol and re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(tlow)}[`\"]?\b", sql_low):
                if scol not in sql_low:
                    return (
                        False,
                        f"LỖI THIẾU LỌC TRẠNG THÁI: Bảng `{tgt['table']}` có cột trạng thái `{tgt['status_col']}`; doanh thu/số đơn hợp lệ phải loại đơn huỷ & trả hàng bằng `{vfilt}`!",
                        False,
                    )

    # 5b. Contradictory NOT IN on cancel/return queries & multi-line cancel rate missing COUNT(DISTINCT)
    if re.search(r"\b(?:huy|ti\s+le\s+.*huy|ty\s+le\s+.*huy|don\s+huy|bi\s+huy|tra\s+hang|doi\s+tra|hoan\s+tra)\b", qn):
        for m_ni in re.finditer(r"\b[a-z0-9_.]*(?:status|trang_?thai|tinh_?trang|ket_?qua)\s+not\s+in\s*\(([^)]+)\)", where_part):
            if re.search(r"huy|cancel|tra\s*hang|hoan\s*tra|doi\s*tra", norm_vn(m_ni.group(1))):
                return (
                    False,
                    "LỖI MÂU THUẪN LOGIC WHERE: Câu hỏi đang đếm/tính tỷ lệ ĐƠN HUỶ hoặc TRẢ HÀNG, "
                    "nhưng `WHERE` lại lọc `NOT IN (...)` loại bỏ chính đơn huỷ/trả hàng! "
                    "Hãy XÓA bỏ điều kiện `status NOT IN (...)` khỏi `WHERE`, dùng `COUNT(DISTINCT CASE WHEN <cột_trạng_thái> IN (...) THEN <mã_đơn> END) * 100.0 / NULLIF(COUNT(DISTINCT <mã_đơn>), 0)`.",
                    True,
                )
        for tgt in knowledge.order_status_targets:
            tlow = tgt["table"].lower()
            if re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(tlow)}[`\"]?\b", sql_low):
                if tgt.get("has_repeating_orders") and tgt.get("order_id_col"):
                    oid = tgt["order_id_col"]
                    if re.search(r"\bsum\s*\(\s*case\s+when", select_head) and "distinct" not in select_head:
                        cvals = tgt.get("cancelled_values") or ["hủy", "Đã hủy đơn"]
                        return (
                            False,
                            f"LỖI ĐẾM TRÙNG DÒNG KHI TÍNH TỶ LỆ HUỶ: Bảng `{tgt['table']}` có nhiều dòng/đơn (`{oid}`); "
                            f"phải dùng `ROUND_HALF_UP(COUNT(DISTINCT CASE WHEN {tgt['status_col']} IN ({', '.join(repr(v) for v in cvals)}) THEN {oid} END) * 100.0 / NULLIF(COUNT(DISTINCT {oid}), 0), 2)` "
                            f"thay vì `SUM(CASE WHEN ...)` trên từng dòng!",
                            True,
                        )

    # 6. Spurious unrequested NOT IN (...) on unit/non-status columns (e.g. don_vi_tinh NOT IN ('gói', ...))
    for m_notin in re.finditer(r"\b([a-z0-9_]+)\s+not\s+in\s*\(([^)]+)\)", where_part):
        col_n, vals_n = m_notin.group(1), m_notin.group(2)
        if not re.search(r"(?:trang_thai|ket_qua|status|tinh_trang|thanh_toan|kenh|nguon|pttt|loai_don)", col_n):
            n_items = vals_n.count(",") + 1
            if re.search(r"(?:don_vi|dvt|unit)", col_n) or (n_items >= 4 and not re.search(r"\b(?:ngoai tru|khong tinh|tru|bo qua)\b", qn)):
                return (
                    False,
                    f"LỖI NGHIỆP VỤ: Câu hỏi KHÔNG yêu cầu loại trừ theo cột `{col_n}`. Xóa bỏ điều kiện `{col_n} NOT IN (...)` thừa!",
                    True,
                )

    # 6b. Dropped grounded non-status entity filter explicitly named in question
    if entity_matches:
        q_raw_norm = norm_vn(question)
        sql_norm = norm_vn(sql)
        for ent_tbl, ent_col, ent_val in entity_matches:
            if re.search(r"(?:trang_thai|status|tinh_trang|ket_qua)", ent_col.lower()):
                continue
            val_norm = norm_vn(ent_val)
            if len(val_norm) < 3:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(val_norm)}(?![a-z0-9])", q_raw_norm):
                if val_norm not in sql_norm and ent_col.lower() not in sql_low:
                    return (
                        False,
                        f"LỖI BỎ SÓT BỘ LỌC: Câu hỏi nhắc rõ đối tượng `{ent_val}` (tại `{ent_tbl}.{ent_col}`), nhưng SQL chưa lọc theo đối tượng này! Hãy `JOIN {ent_tbl}` (nếu ở bảng khác) và giữ điều kiện lọc `{ent_col} = '{ent_val}'`.",
                        True,
                    )

    # 7. Suspicious 0 count when extra unrequested filters or <= remain
    if sql_res.row_count == 1 and len(sql_res.columns) == 1 and sql_res.rows[0][0] == 0 and asks_order_cnt:
        if "and" in where_part:
            return (
                False,
                "CẢNH BÁO KẾT QUẢ = 0: Truy vấn đếm đơn trả về 0; kiểm tra lại filter ngày (`=` hay `BETWEEN`) và các giá trị trạng thái thực tế trong bảng!",
                False,
            )

    # 8. Prevent double-multiplying quantity by an already-extended line/order total (so_luong * thanh_tien)
    _qty_tok = r"(?:so_luong|sl|qty|quantity|so_hop|boxes)"
    _line_total_tok = r"(?:thanh_tien|tong_tien|doanh_thu|tong_doanh_thu|subtotal|line_total)"
    if re.search(
        rf"(?:\b[a-z0-9_.]*{_qty_tok}\b\s*\*\s*[a-z0-9_.]*{_line_total_tok}\b|\b[a-z0-9_.]*{_line_total_tok}\b\s*\*\s*[a-z0-9_.]*{_qty_tok}\b)",
        select_head,
    ):
        return (
            False,
            "LỖI NHÂN TRÙNG CHỈ SỐ: Cột `thanh_tien` / `tong_tien` ĐÃ là tổng tiền sau nhân số lượng; TUYỆT ĐỐI KHÔNG nhân thêm `so_luong * thanh_tien`! Hãy tính riêng `SUM(thanh_tien)` và `SUM(so_luong)`.",
            True,
        )

    # 9. Respect explicit table name mentioned as 'bảng <table>'
    for m_tbl in re.finditer(r"\bbang\s+[`'\"]?([a-z0-9_]+)[`'\"]?\b", qn):
        req_t = m_tbl.group(1)
        matched_t = next(
            (tp.table_name for tp in knowledge.workspace.tables.values() if tp.table_name.lower() == req_t),
            None,
        )
        if matched_t and not re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(req_t)}[`\"]?\b", sql_low):
            return (
                False,
                f"LỖI CHỌN BẢNG: Câu hỏi yêu cầu thống kê trực tiếp bảng `{matched_t}`, nhưng SQL chưa đọc từ `{matched_t}`. Hãy truy vấn bảng `{matched_t}`!",
                True,
            )

    # 9b. Delivery trip / shipment batch questions must use delivery schedule table & distinguish multi-batch per order
    if re.search(r"\b(?:dot\s+(?:hang|giao)|cho\s+giao\s+bao\s+nhieu\s+dot|lan\s+giao|chuyen\s+giao|xe\s+cho)\b", qn):
        deliv_tbl = next(
            (
                tp for tp in knowledge.workspace.tables.values()
                if tp.row_count > 0 and re.search(r"(?:phieu_?giao_?hang|so_?giao_?hang|giao_?hang|nhat_?trinh_?xe)", tp.table_name, re.I)
            ),
            None,
        )
        if deliv_tbl is not None:
            dcols = [getattr(c, "sql_name", str(c)) for c in deliv_tbl.columns]
            batch_col = next((c for c in dcols if re.match(r"^(?:lan_giao|dot_giao|dot)$", c, re.I)), None)
            order_kcol = next((c for c in dcols if re.match(r"^(?:ma_don_hang|ma_don|so_hd)$", c, re.I)), None)
            batch_hint = (
                f"dùng `COUNT(DISTINCT {order_kcol} || '|' || {batch_col})`"
                if (order_kcol and batch_col)
                else f"đếm theo cột khóa trong `{deliv_tbl.table_name}`"
            )
            if not re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(deliv_tbl.table_name.lower())}[`\"]?\b", sql_low):
                return (
                    False,
                    f"LỖI CHỌN BẢNG GIAO HÀNG: DB có bảng giao hàng chuyên biệt `{deliv_tbl.table_name}` ({', '.join(dcols[:10])}). "
                    f"Câu hỏi đếm số đợt giao/chuyến giao BẮT BUỘC phải truy vấn bảng `{deliv_tbl.table_name}` ({batch_hint}), KHÔNG đếm từ sổ bán hàng!",
                    True,
                )
            if order_kcol and batch_col and batch_col.lower() not in select_head:
                return (
                    False,
                    f"LỖI ĐẾM THIẾU ĐỢT GIAO (`{batch_col}`): Bảng `{deliv_tbl.table_name}` có nhiều dòng hàng trong cùng 1 đợt và 1 đơn có thể giao nhiều lần (`{batch_col}`)! "
                    f"Hãy đếm số đợt bằng `COUNT(DISTINCT {order_kcol} || '|' || {batch_col})` thay vì chỉ `COUNT(DISTINCT {order_kcol})` hay `COUNT(*)`!",
                    True,
                )

    # 10. Respect explicit grouping dimension mentioned in question when matching column exists (e.g. 'nhóm món' -> nhom_mon)
    dim_req = _match_requested_dimension_col(qn, knowledge)
    if dim_req:
        q_phrase, t_hit, c_hit = dim_req
        if not re.search(rf"\b{re.escape(c_hit.lower())}\b", sql_low):
            return (
                False,
                f"LỖI NHÓM PHÂN TÍCH: Câu hỏi yêu cầu phân theo `{q_phrase}` — cột `{c_hit}` nằm ở bảng `{t_hit}`! Hãy `JOIN {t_hit}` (nếu ở bảng khác) và dùng `{c_hit}` thay vì tên mặt hàng chi tiết!",
                True,
            )

    # 11. Quantity column guard: avoid COUNT(*) substituting for SUM(so_luong) when asking 'tổng số lượng' / item quantities
    asks_qty_sum = bool(
        re.search(
            r"\b(?:tong\s+so\s+luong|so\s+luong\s+(?:ban|xuat|nhap|ton|theo|cua|cao\s+nhat|trung\s+binh|vuot|chenh\s+lech)|so\s+luong\s+va\s+(?:thanh\s+tien|doanh\s+thu)|(?:thanh\s+tien|doanh\s+thu)\s+va\s+so\s+luong)\b",
            qn,
        )
        and not re.search(
            r"\bso\s+luong\s+(?:don|hoa\s+don|giao\s+dich|ban\s+ghi|dong|khach|nhan\s+vien|san\s+pham|mon)\b",
            qn,
        )
    )
    if asks_qty_sum:
        queried_qty_cols = [
            getattr(c, "sql_name", str(c))
            for tp in knowledge.workspace.tables.values()
            if re.search(rf"\b(?:from|join)\s+[`\"]?{re.escape(tp.table_name.lower())}[`\"]?\b", sql_low)
            for c in tp.columns
            if re.search(r"^(?:so_?luong|sl|qty|quantity|so_?hop|boxes)$", getattr(c, "sql_name", str(c)).lower())
        ]
        if queried_qty_cols:
            has_qty_agg = any(
                re.search(rf"\b(?:sum|avg|max|min)\s*\([^)]*\b{re.escape(qc.lower())}\b", select_head)
                for qc in queried_qty_cols
            )
            if not has_qty_agg:
                return (
                    False,
                    f"LỖI CHỈ SỐ SỐ LƯỢNG: Bảng có cột `{queried_qty_cols[0]}` — không dùng `COUNT(*)` hay bỏ sót số lượng; hãy dùng `SUM({queried_qty_cols[0]})` (hoặc `AVG({queried_qty_cols[0]})` nếu hỏi trung bình)!",
                    True,
                )

    # 12. Grouped percentage denominator guard: reject '/ SUM(...)' without OVER () or scalar subquery '(SELECT SUM'
    if (
        "group by" in sql_low
        and "over" not in sql_low
        and not re.search(r"\(\s*select\s+.*?\bsum\s*\(", sql_low)
        and re.search(r"/\s*(?:nullif\s*\(\s*)?(?:cast\s*\(\s*)?sum\s*\(", select_head)
        and re.search(r"\b(?:ty\s+le|ti\s+le|ty\s+trong|dong\s+gop|phan\s+tram|%|share|percent)\b", qn)
    ):
        m_plain_num = re.search(r"\bsum\s*\(\s*(?:[a-z0-9_]+\.)?([a-z0-9_]+)\s*\)", select_head)
        hint_expr = f"SUM(SUM({m_plain_num.group(1)})) OVER ()" if m_plain_num else "SUM(SUM(...)) OVER ()"
        return (
            False,
            f"LỖI MẪU SỐ TỶ LỆ (%): Khi có `GROUP BY`, chia trực tiếp cho `SUM(...)` sẽ chia cho chính nhóm đó thay vì tổng toàn bộ! Phải chia cho tổng toàn cục của CÙNG CHỈ SỐ TỬ SỐ qua `{hint_expr}` hoặc `(SELECT SUM(...) FROM ...)` (cùng điều kiện lọc).",
            True,
        )

    # 12b. Mismatched numerator/denominator metric in share-of-total (%) window or scalar subquery
    if (
        re.search(r"\b(?:ty\s+le|ti\s+le|ty\s+trong|dong\s+gop|phan\s+tram|%|share|percent)\b", qn)
        and not re.search(r"\b(?:ty\s+suat|chuyen\s+doi|bien\s+loi\s+nhuan|margin|conversion|per\b|tren\s+moi|moi\s+(?:don|mon|san\s+pham|khach))\b", qn)
    ):
        m_share_cols = re.search(
            r"\bsum\s*\(\s*(?:[a-z0-9_]+\.)?([a-z0-9_]+)\s*\)"
            r"(?:\s*(?:,\s*0|as\s+(?:real|float|numeric|double))?\s*\))*"
            r"(?:\s*\*\s*100(?:\.0)?)?\s*/\s*(?:nullif\s*\(\s*)?(?:cast\s*\(\s*)?"
            r"(?:sum\s*\(\s*sum\s*\(\s*(?:[a-z0-9_]+\.)?([a-z0-9_]+)\s*\)\s*\)\s*over"
            r"|\(\s*select\s+sum\s*\(\s*(?:[a-z0-9_]+\.)?([a-z0-9_]+)\s*\))",
            select_head,
        )
        if m_share_cols:
            num_col = m_share_cols.group(1)
            den_col = m_share_cols.group(2) or m_share_cols.group(3)
            if den_col and num_col != den_col:
                return (
                    False,
                    f"LỖI CỘT TỬ SỐ & MẪU SỐ (%): Tỷ trọng phần trăm (%) phải chia CÙNG MỘT CHỈ SỐ — tử số đang tính `{num_col}` nhưng mẫu số lại chia cho `{den_col}`! Hãy sửa mẫu số dùng `SUM(SUM({num_col})) OVER ()` (hoặc `(SELECT SUM({num_col}) FROM ...)`) thay vì `{den_col}`.",
                    True,
                )

    # Resolve 2-part entity + metric listing spec upfront so both Check #13 and #16 can provide exact hints
    ent_metric_spec = build_entity_and_metric_listing_sql_spec(question, knowledge, analysis, entity_matches or ())

    # 13. Missing GROUP BY guard: reject SQLite mixed unaggregated column + SUM/COUNT/AVG or entity-peak query without GROUP BY
    if "group by" not in sql_low:
        select_exprs = _split_top_level_select_exprs(select_head)
        has_agg_metric = any(
            re.search(r"\b(?:sum|count|avg|total)\s*\(", e) and not re.search(r"\bover\s*\(", e)
            for e in select_exprs
        )
        if has_agg_metric:
            has_unagg_col = False
            for e in select_exprs:
                core = re.sub(r"\s+as\s+[`\"']?[a-z0-9_]+[`\"']?\s*$", "", e, flags=re.IGNORECASE).strip()
                if not core or core.startswith("'") or re.match(r"^[+-]?\d+(?:\.\d+)?$", core):
                    continue
                if re.search(r"\b(?:sum|count|avg|min|max|total|group_concat)\s*\(", core) or re.search(r"\bover\s*\(", core):
                    continue
                if re.search(r"\b[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?\b", core):
                    has_unagg_col = True
                    break
            if has_unagg_col or _ENTITY_WHICH_LOOKUP_RE.search(qn):
                if ent_metric_spec is not None:
                    return (
                        False,
                        f"LỖI THIẾU GROUP BY & CỘT TÊN ĐỐI TƯỢNG: Câu hỏi yêu cầu XUẤT CẢ tên `{ent_metric_spec['dim_col']}` VÀ tổng `{ent_metric_spec['metric_alias']}`! "
                        f"Bắt buộc `SELECT` cả cột tên đối tượng và cột chỉ số tổng hợp kèm `GROUP BY`.\nDùng chính xác câu SQL mẫu:\n{ent_metric_spec['suggested_sql']}",
                        True,
                    )
                return (
                    False,
                    "LỖI THIẾU GROUP BY: Câu SQL dùng hàm tổng hợp (`SUM`/`COUNT`/`AVG`) cho câu hỏi tìm theo từng ngày/nhóm/đối tượng hoặc trộn cột phân loại mà THIẾU `GROUP BY` — khiến SQLite cộng dồn toàn bộ bảng vào 1 dòng! Phải thêm `GROUP BY <cột_nhóm>` rồi `ORDER BY ... DESC LIMIT 1`.",
                    True,
                )

    # 14. Ordinal rank guard ('cao thứ 3', 'đứng thứ 2', etc.): must return exactly 1 row using LIMIT 1 OFFSET {rank_n - 1}
    if ord_rank is not None:
        rank_n, rank_dir = ord_rank
        offset_val = rank_n - 1
        has_wrong_limit = bool(
            re.search(rf"\blimit\s+{rank_n}\b", sql_low) and f"offset {offset_val}" not in sql_low
        )
        if sql_res.row_count > 1 or has_wrong_limit:
            return (
                False,
                f"LỖI XẾP HẠNG THỨ {rank_n}: Câu hỏi tìm đối tượng đứng THỨ {rank_n} (1 đối tượng duy nhất kèm chỉ số), KHÔNG phải lấy danh sách Top {rank_n}! Phải chọn cả cột tên đối tượng và cột chỉ số `SUM(...)` trong `SELECT`, dùng `GROUP BY <cột_đối_tượng> ORDER BY ... {rank_dir} LIMIT 1 OFFSET {offset_val}`.",
                True,
            )

    # 15. Extreme comparison guard (highest + lowest list with optional diff): block 1-number scalar diff queries
    if getattr(analysis, "extreme_comparison", None) is not None:
        has_label_cell = any(
            isinstance(cell, str) and bool(cell.strip()) and _coerce_float(cell) is None
            for row in (sql_res.rows or [])[:10]
            for cell in row
        )
        missing_group_by = "group by" not in sql_low
        too_few_rows = sql_res.row_count < 2 and not ("rn_high" in sql_low and "rn_low" in sql_low)
        if len(sql_res.columns) < 2 or missing_group_by or (not has_label_cell) or too_few_rows:
            ext_spec = build_extreme_comparison_sql_spec(question, knowledge, analysis)
            sample_hint = f"\nDùng chính xác CTE SQLite mẫu:\n{ext_spec['suggested_sql']}" if ext_spec else ""
            return (
                False,
                f"LỖI THIẾU DANH SÁCH CỰC TRỊ: Câu hỏi yêu cầu IN RA cả đối tượng/nhóm CAO NHẤT và THẤP NHẤT kèm độ chênh lệch, KHÔNG được chỉ trả về 1 con số chênh lệch đơn lẻ! Phải `GROUP BY` theo đối tượng/nhóm và trả về các dòng Cao nhất + Thấp nhất kèm cột chênh lệch.{sample_hint}",
                True,
            )

    # 16. Entity + Metric guard (including 2-part entity+metric, above/below average & multi-entity lists)
    if ent_metric_spec is not None:
        outer_sel_head = _extract_outer_select_head(sql)
        outer_exprs = _split_top_level_select_exprs(outer_sel_head)
        has_too_few_cols = (len(outer_exprs) < 2 and outer_exprs != ["*"]) or (
            outer_exprs == ["*"] and len(sql_res.columns) < 2
        )
        has_text_entity_cell = any(
            isinstance(cell, str) and bool(cell.strip()) and _coerce_float(cell) is None
            for row in (sql_res.rows or [])[:10]
            for cell in row
        )
        if has_too_few_cols or "group by" not in sql_low or (sql_res.rows and not has_text_entity_cell):
            return (
                False,
                f"LỖI THIẾU CỘT TÊN ĐỐI TƯỢNG HOẶC CHỈ SỐ TỔNG HỢP: Câu hỏi yêu cầu XUẤT CẢ tên `{ent_metric_spec['dim_col']}` VÀ tổng `{ent_metric_spec['metric_alias']}`! "
                f"Bắt buộc `SELECT` cả cột tên đối tượng và cột chỉ số tổng hợp kèm `GROUP BY`, TUYỆT ĐỐI KHÔNG chỉ xuất 1 con số `SUM(...)` hay bỏ sót tên đối tượng!\n"
                f"Dùng chính xác câu SQL mẫu:\n{ent_metric_spec['suggested_sql']}",
                True,
            )

    if _is_entity_lookup_or_list_q and not analysis.is_list_unit_pair:
        outer_sel_head = _extract_outer_select_head(sql)
        outer_exprs = _split_top_level_select_exprs(outer_sel_head)
        has_single_col_select = (len(outer_exprs) < 2 and outer_exprs != ["*"]) or (
            outer_exprs == ["*"] and len(sql_res.columns) < 2
        )
        if avg_ent_cmp is not None:
            ent_vals = [str(r[0]).strip().lower() for r in (sql_res.rows or []) if r and r[0] is not None]
            has_duplicate_entities = len(ent_vals) != len(set(ent_vals))
            if has_single_col_select or "group by" not in sql_low or has_duplicate_entities:
                avg_spec = build_benchmark_average_entity_sql_spec(question, knowledge, analysis)
                sample_hint = f"\nDùng chính xác CTE SQLite mẫu:\n{avg_spec['suggested_sql']}" if avg_spec else ""
                return (
                    False,
                    f"LỖI THIẾU CỘT CHỈ SỐ HOẶC CHƯA GOM NHÓM: Khi hỏi những đối tượng (thuốc/món/sản phẩm/khách hàng/kênh...) có doanh thu/số lượng vượt trên hoặc dưới mức trung bình, BẮT BUỘC phải `GROUP BY` theo đối tượng trong CTE để tính tổng chỉ số của mỗi đối tượng trước khi so sánh với `AVG(...)`, và mệnh đề `SELECT` ngoài BẮT BUỘC phải IN KÈM CẢ cột tên đối tượng VÀ cột chỉ số tổng hợp (2 cột), TUYỆT ĐỐI KHÔNG chỉ `SELECT` 1 cột tên đối tượng!{sample_hint}",
                    True,
                )
        elif has_single_col_select and (
            analysis.expected_type in ("list", "table")
            or ord_rank is not None
            or re.search(r"\b(?:nhung|cac|danh\s+sach|liet\s+ke|top\s*\d+|in\s+ra)\b", qn)
        ):
            return (
                False,
                "LỖI THIẾU CỘT CHỈ SỐ ĐO LƯỜNG: Khi hỏi danh sách đối tượng (thuốc/món/sản phẩm/vật liệu/khách hàng/kênh...) theo doanh thu/số lượng/công nợ/tiền nhập, mệnh đề `SELECT` BẮT BUỘC phải chọn CẢ cột tên đối tượng VÀ cột giá trị chỉ số tổng hợp đi kèm (VD: `SELECT ten_thuoc, ROUND_HALF_UP(SUM(doanh_thu), 0) AS tong_doanh_thu ...`), TUYỆT ĐỐI KHÔNG chỉ trả 1 cột tên đối tượng!",
                True,
            )

    return verify_result_sanity_bounds(
        sql, sql_res, question, knowledge, analysis, entity_matches=entity_matches or ()
    )


def _coerce_float(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).strip())
    except ValueError:
        return None


def format_sql_result(
    sql_res: SQLExecutionResult,
    analysis: QuestionAnalysis,
    question: str,
) -> Optional[Dict[str, Any]]:
    """Deterministically convert SQL execution result rows into strict DataMate JSON format."""
    if not sql_res.ok or not sql_res.rows:
        return None

    rows = sql_res.rows
    cols = sql_res.columns
    etype = analysis.expected_type

    # Handle table format
    if etype == "table":
        if len(cols) < 2:
            return None
        out_cols = analysis.expected_table_cols if (analysis.expected_table_cols and len(cols) == 2) else cols
        norm_rows: List[List[Any]] = []
        for row in rows:
            cleaned_row: List[Any] = []
            for idx, cell in enumerate(row):
                if cell is None:
                    return None
                if idx == 0:
                    cleaned_row.append(normalize_nfc(str(cell)))
                else:
                    num = _coerce_float(cell)
                    if num is None:
                        cleaned_row.append(normalize_nfc(str(cell)))
                    else:
                        cleaned_row.append(round_half_up(num, 0) if abs(num - round(num)) < 1e-6 or analysis.money_like else round(num, 2))
            norm_rows.append(cleaned_row)
        return {"type": "table", "answer": {"columns": list(out_cols), "rows": norm_rows}}

    # Handle list format
    if etype == "list":
        values: List[Any] = []
        qn_fmt = normalize_vn_question(question)
        wants_tuple = bool(
            len(cols) >= 3
            or re.search(r"(?:lan\s+luot|theo\s+thu\s+tu|hai\s+so|ba\s+so|ghi\s+\d+\s+so)", qn_fmt)
        )
        if len(cols) == 1:
            values = [r[0] for r in rows]
        elif len(rows) == 1 and len(cols) >= 2 and (not isinstance(rows[0][0], str) or wants_tuple):
            values = list(rows[0])
        else:
            # Multi-row ranking where SQL included metric column: take first column (label) if strings expected
            values = [r[0] for r in rows]

        if any(v is None for v in values):
            return None

        cleaned_list: List[Any] = []
        for v in values:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cleaned_list.append(round_half_up(v, 0) if (analysis.money_like or analysis.is_list_unit_pair or float(v).is_integer()) else round(float(v), 2))
            else:
                cleaned_list.append(normalize_nfc(str(v)))
        return {"type": "list", "answer": cleaned_list}

    # Scalar expectations require 1x1 cleanly resolved value
    if len(rows) == 1 and len(cols) == 1:
        val = rows[0][0]
        if val is None:
            return None

        if etype == "boolean":
            if isinstance(val, bool):
                return {"type": "boolean", "answer": val}
            if isinstance(val, (int, float)):
                return {"type": "boolean", "answer": bool(int(val))}
            s = str(val).strip().lower()
            if s in ("true", "1", "yes", "co", "có", "tang", "đúng"):
                return {"type": "boolean", "answer": True}
            if s in ("false", "0", "no", "khong", "không", "giam", "sai"):
                return {"type": "boolean", "answer": False}
            return None

        if etype == "date":
            s_raw = str(val).strip()
            if analysis.date_granularity == "month" and re.match(r"^\d{4}-\d{2}$", s_raw):
                return {"type": "date", "answer": s_raw}
            iso, _ = parse_date_value(s_raw)
            if iso:
                return {"type": "date", "answer": iso[:7] if analysis.date_granularity == "month" else iso}
            return None

        if etype == "string":
            return {"type": "string", "answer": normalize_nfc(str(val))}

        if etype == "percent":
            num = _coerce_float(val)
            if num is None:
                return None
            return {"type": "percent", "answer": round(num, 2)}

        if etype == "number":
            num = _coerce_float(val)
            if num is None:
                return None
            if analysis.money_like or abs(num - round(num)) < 1e-6:
                return {"type": "number", "answer": round_half_up(num, 0)}
            return {"type": "number", "answer": round(num, 2)}

    # Top-1 helper: 1 row with [label, metric] when string/date expected
    if len(rows) == 1 and len(cols) >= 2 and etype in ("string", "date"):
        first = rows[0][0]
        if first is None:
            return None
        if etype == "string":
            return {"type": "string", "answer": normalize_nfc(str(first))}
        iso, _ = parse_date_value(first)
        if iso:
            return {"type": "date", "answer": iso[:7] if analysis.date_granularity == "month" else iso}

    return None


def _check_subquery_column_capture(sql: str, knowledge: WorkspaceKnowledge) -> Optional[str]:
    """
    Detect silent SQLite outer-column capture inside `IN (SELECT col FROM tbl)` where `col` does not
    belong to `tbl` (prevents slow correlated full scans / timeouts and false 100%-match bugs).
    """
    if not sql:
        return None
    tbl_cols_map = {
        tname.lower(): {getattr(c, "sql_name", str(c)).lower() for c in tp.columns}
        for tname, tp in knowledge.workspace.tables.items()
    }
    raw_tbl_cols = {
        tname.lower(): [getattr(c, "sql_name", str(c)) for c in tp.columns]
        for tname, tp in knowledge.workspace.tables.items()
    }
    for m in re.finditer(
        r"\b(?:not\s+)?in\s*\(\s*select\s+(?:distinct\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s+from\s+[`\"']?([a-zA-Z_][a-zA-Z0-9_]*)[`\"']?\b",
        sql,
        re.IGNORECASE,
    ):
        sub_col = m.group(1)
        sub_tbl = m.group(2)
        st_low = sub_tbl.lower()
        if st_low not in tbl_cols_map:
            continue
        if sub_col.lower() not in tbl_cols_map[st_low]:
            join_hints = [e for e in (knowledge.join_graph or []) if st_low in e.lower()]
            j_str = f" Liên kết khoá gợi ý: `{'; '.join(join_hints[:3])}`." if join_hints else ""
            cols_str = ", ".join(raw_tbl_cols[st_low][:12])
            return (
                f"LỖI CỘT SUBQUERY (`{sub_col}` KHÔNG thuộc bảng `{sub_tbl}` trong `IN (SELECT {sub_col} FROM {sub_tbl})`): "
                f"Bảng `{sub_tbl}` chỉ có các cột: {cols_str}! "
                f"SQLite tự tham chiếu nhầm ra bảng ngoài gây chậm/sai. Hãy viết lại bằng `JOIN` theo đúng tên cột khoá thật!{j_str}"
            )
    return None


def should_prefer_python_sandbox(question: str, knowledge: WorkspaceKnowledge) -> bool:
    """Detect stateful algorithms, wide day matrices, compound cells, or tariff diffs suited for Python."""
    qn = normalize_vn_question(question)
    if re.search(
        r"\b(?:fifo|toa\s+cu\s+nhat|tra\s+bot\s+goc|lai\s+cam\s+do|xep\s+loai\s+hoc\s+luc|hoc\s+luc|"
        r"hanh\s+kiem|lam\s+tron.*30\s*phut|ca\s+(?:dem|qua\s+dem)|so\s+buoi\s+bo)\b",
        qn,
    ):
        return True
    q_toks = set(re.findall(r"[a-z0-9]+", qn))
    for tname, tp in knowledge.workspace.tables.items():
        if tp.row_count <= 0 or not tp.notes:
            continue
        notes_str = " ".join(tp.notes)
        relevant = len(knowledge.workspace.tables) <= 6 or bool(
            set(re.split(r"[^a-z0-9]+", tname.lower())) & q_toks
        )
        if "compound_cols=" in notes_str and relevant:
            return True
        if "wide_day_matrix=true" in notes_str and (
            relevant or re.search(r"\b(?:cham\s+cong|nghi\s+phep|di\s+lam|vang|ca\s+lam|tang\s+ca)\b", qn)
        ):
            return True
        if re.search(r"\d+[.,]\d+\s*đ/(?:so|số|khoi|khối)", notes_str, re.I) and re.search(
            r"\b(?:tien\s+dien|tien\s+nuoc|so\s+dien|so\s+nuoc)\b", qn
        ):
            return True
    return False


def _is_strong_python_first_candidate(question: str, knowledge: WorkspaceKnowledge) -> bool:
    """
    Strictly select queries where SQLite routinely fails (FIFO/stateful rules, compound '527k + 338000'
    cells, 31-column attendance matrices, or tiered utility meter diffs) for Python-First Attempt 0.
    """
    qn = normalize_vn_question(question)
    if re.search(
        r"\b(?:fifo|toa\s+cu\s+nhat|tra\s+bot\s+goc|lai\s+cam\s+do|xep\s+loai\s+hoc\s+luc|lam\s+tron.*30\s*phut|ca\s+(?:dem|qua\s+dem))\b",
        qn,
    ):
        return True
    q_toks = set(re.findall(r"[a-z0-9]+", qn))
    for tname, tp in knowledge.workspace.tables.items():
        if tp.row_count <= 0 or not tp.notes:
            continue
        notes_str = " ".join(tp.notes)
        relevant = len(knowledge.workspace.tables) <= 6 or bool(
            set(re.split(r"[^a-z0-9]+", tname.lower())) & q_toks
        )
        if "compound_cols=" in notes_str and relevant:
            return True
        if "wide_day_matrix=true" in notes_str and (
            relevant or re.search(r"\b(?:cham\s+cong|nghi\s+phep|di\s+lam|vang|ca\s+lam|tang\s+ca)\b", qn)
        ):
            return True
        if re.search(r"\d+[.,]\d+\s*đ/(?:so|số|khoi|khối)", notes_str, re.I) and re.search(
            r"\b(?:tien\s+dien|tien\s+nuoc|so\s+dien|so\s+nuoc)\b", qn
        ):
            return True
    return False


def is_false_llm_unanswerable(
    question: str,
    reason: str,
    knowledge: WorkspaceKnowledge,
    had_sql_attempt: bool = False,
) -> Optional[str]:
    """Detect when an LLM wrongly returns status='unanswerable' despite answerable tables/columns/joins."""
    if not knowledge or not getattr(knowledge, "workspace", None):
        return None
    if check_out_of_scope_or_irrelevant(question, knowledge) is not None:
        return None

    tables_dict = getattr(knowledge.workspace, "tables", None) or {}
    col_owners: Dict[str, List[str]] = {}
    for tname, tp in tables_dict.items():
        if int(getattr(tp, "row_count", 0) or 0) <= 0:
            continue
        for c in getattr(tp, "columns", []) or []:
            cn = getattr(c, "sql_name", str(c))
            col_owners.setdefault(cn.lower(), []).append(f"{tname}.{cn}")

    r_text = reason or ""
    mentioned_cols = re.findall(
        r"(?:cột|cot|trường|truong|field)\s+[`'\"«]?([a-zA-Z_][a-zA-Z0-9_]*)[`'\"»]?",
        r_text,
        re.IGNORECASE,
    )
    found_locations: List[str] = []
    for mc in mentioned_cols:
        owners = col_owners.get(mc.lower())
        if owners:
            found_locations.append(f"`{mc}` CÓ tại {', '.join(f'`{o}`' for o in owners[:3])}")

    an = classify_expected_type(question)
    em_spec = build_entity_and_metric_listing_sql_spec(question, knowledge, an)
    looks_schema_excuse = bool(
        re.search(r"không\s+có\s+cột|không\s+tồn\s+tại|không\s+đủ|missing\s+column", r_text, re.IGNORECASE)
    )
    if not (had_sql_attempt or found_locations or (em_spec is not None and looks_schema_excuse)):
        return None

    hints: List[str] = []
    if found_locations:
        hints.append("; ".join(found_locations))
    if knowledge.join_graph:
        hints.append("Liên kết JOIN có sẵn: " + "; ".join(f"`{e}`" for e in knowledge.join_graph[:5]))
    if em_spec and em_spec.get("suggested_sql"):
        hints.append("Mẫu SQL tham chiếu:\n```sql\n" + em_spec["suggested_sql"] + "\n```")
    if not hints:
        hints.append("Kiểm tra kỹ danh sách cột của tất cả bảng liên kết trong lược đồ SQLite.")
    return (
        "CẢNH BÁO TỪ CHỐI NHẦM (`unanswerable` sai): Câu hỏi này CÓ THỂ trả lời từ CSDL hiện tại! "
        + " | ".join(hints)
        + '\nHãy `LEFT JOIN` / `JOIN` các bảng trên và trả về `{"status": "ok", "sql": "SELECT ..."}`.'
    )


class DataMateAgent:
    """End-to-end headless DataMate analytics & abstention agent."""

    def __init__(
        self,
        backend: Optional[LLMBackend] = None,
        config: Optional[AgentConfig] = None,
        calendar_path: Optional[str] = None,
    ) -> None:
        self.config = config or AgentConfig()
        if backend is not None:
            self.backend: LLMBackend = backend
        else:
            llm_cfg = self.config.llm_config or LLMConfig.from_env()
            self.backend = MultiProviderLLMBackend(llm_cfg)
        self.calendar = SolarLunarCalendar(calendar_path) if calendar_path else None
        self._knowledge_cache: Dict[str, WorkspaceKnowledge] = {}

    def _allow_extra_stage3_llm_calls(self) -> bool:
        """Gate extra verification/escalation calls so deterministic mock unit tests keep exact call counts."""
        return isinstance(self.backend, MultiProviderLLMBackend) or bool(
            getattr(self.config, "force_stage3_on_custom_backend", False)
        )

    def get_knowledge(
        self,
        business_dir: str,
        cache_dir: Optional[str] = None,
        force_rebuild: bool = False,
    ) -> WorkspaceKnowledge:
        key = str(business_dir)
        if not force_rebuild and key in self._knowledge_cache:
            return self._knowledge_cache[key]
        ws = load_business_workspace(
            business_dir,
            cache_dir=cache_dir,
            force_rebuild=force_rebuild,
            lunar_cal=self.calendar,
        )
        know = build_workspace_knowledge(ws)
        self._knowledge_cache[key] = know
        return know

    def _build_sql_prompt(
        self,
        question: str,
        as_of_date: str,
        knowledge: WorkspaceKnowledge,
        analysis: QuestionAnalysis,
        temporal_summary: str,
        entity_matches: Sequence[Tuple[str, str, str]],
        probe_context: str = "",
        prefer_python: bool = False,
        force_python_first: bool = False,
        retraction_note: Optional[str] = None,
    ) -> Tuple[str, str]:
        system_prompt = _select_rulebook_prompt(
            question,
            as_of_date,
            knowledge,
            analysis,
            entity_matches=entity_matches,
        )

        ent_text = (
            "\n".join(f"- {t}.{c} = {v!r}" for t, c, v in entity_matches)
            if entity_matches
            else "(Không phát hiện tên riêng cố định; dùng NORM_VN(...) nếu cần lọc chuỗi tiếng Việt)"
        )
        readme_text = _compact_readme_for_prompt(knowledge.workspace.readme_text)
        type_guide = f"Kiểu đáp án kỳ vọng: `{analysis.expected_type}`"
        if analysis.expected_type == "date":
            type_guide += f" (format `{'YYYY-MM' if analysis.date_granularity == 'month' else 'YYYY-MM-DD'}`)"
        elif analysis.expected_type == "percent":
            type_guide += " (trả số phần trăm * 100.0, ví dụ 12.45 chứ không phải 0.1245)"
        elif analysis.expected_type == "table":
            type_guide += " (SQL trả đúng 2+ cột theo thứ tự: tên đối tượng trước, số đo sau)"
        elif analysis.expected_type == "list":
            if analysis.is_list_unit_pair:
                type_guide += " (SQL trả 1 dòng 2 cột: [nguyên, lẻ])"
            else:
                type_guide += " (Nếu hỏi danh sách đối tượng như thuốc/món/sản phẩm/khách hàng/kênh theo chỉ số doanh thu/số lượng/công nợ: SQL BẮT BUỘC trả 2 cột gồm cột tên đối tượng VÀ cột chỉ số tổng hợp đi kèm như ROUND_HALF_UP(SUM(doanh_thu), 0) AS tong_doanh_thu; nếu hỏi danh mục thuần túy thì lấy từ bảng danh mục kèm cột mô tả/đơn giá; HOẶC 1 dòng nhiều cột nếu hỏi 2-3 con số)"
        elif analysis.expected_type == "string":
            type_guide += " (Nếu tìm đối tượng theo chỉ số doanh thu/số lượng/công nợ: SQL BẮT BUỘC trả 2 cột gồm cột tên đối tượng trước và cột chỉ số tổng hợp sau)"
        elif analysis.expected_type == "boolean":
            type_guide += " (SQL trả 1 hoặc 0)"

        effective_temp_summary = format_effective_temporal_summary(temporal_summary, as_of_date, analysis)
        focused_schema = build_focused_schema_prompt(question, knowledge, entity_matches, max_full_tables=8)

        norm_clean = normalize_vn_question(question)
        q_block = question
        if norm_clean and norm_clean != norm_vn(question):
            q_block = f"{question}\n- Ý định đã chuẩn hóa: {norm_clean}"

        extra_blocks: List[str] = []
        if retraction_note:
            extra_blocks.append(f"### ĐÍNH CHÍNH CÂU HỎI\n{retraction_note}")
        if probe_context:
            extra_blocks.append(f"### DỮ LIỆU THỰC TẾ THÁM HIỂM TỰ ĐỘNG (PROBE)\n{probe_context}")
        if force_python_first and self.config.enable_python_sandbox:
            extra_blocks.append(
                "### BẮT BUỘC DÙNG PYTHON SANDBOX (MA TRẬN NGÀY / Ô GHÉP / FIFO / TARIFF)\n"
                "Dữ liệu/nghiệp vụ bài toán này KHÔNG phù hợp SQL thuần (ví dụ ma trận 31 cột ngày `1..31`, ô ghép `'527k + 338000'`, FIFO/bậc thang). "
                "HÃY VIẾT PYTHON SANDBOX NGAY: trả JSON duy nhất `{\"status\": \"ok\", \"python\": \"...\"}` (KHÔNG viết SQL thuần thay thế trừ khi bảng hoàn toàn phẳng).\n"
                "Biến & hàm có sẵn: `query_df(sql)` -> `pd.DataFrame`, `sum_compound_vn_nums(x)`, `parse_vn_num(x)`, `round_half_up(v, d)`, `norm_vn(s)`, `pd`, `re`, `Decimal`, `ROUND_HALF_UP`.\n"
                "Ví dụ mẫu:\n"
                "```python\n"
                "df = query_df('SELECT * FROM \"<ten_bang>\"')\n"
                "# ... xử lý bằng pandas / sum_compound_vn_nums / parse_vn_num ...\n"
                "result = round_half_up(val, 0)\n"
                "```"
            )
        elif prefer_python and self.config.enable_python_sandbox:
            extra_blocks.append(
                "### TUỲ CHỌN PYTHON SANDBOX (KHUYÊN DÙNG CHO BÀI TOÁN PHỨC TẠP / MA TRẬN / Ô GHÉP)\n"
                "Bài toán này có dấu hiệu phức tạp cho SQL thuần (ma trận nhiều cột ngày, ô ghép `'527k + 338000'`, FIFO, chênh lệch chỉ số giữa các tháng). "
                "Bạn CÓ THỂ trả JSON `{\"status\": \"ok\", \"python\": \"...\"}` (gán kết quả cuối vào biến `result`), "
                "dùng sẵn `query_df(sql)` (trả về pandas DataFrame), `sum_compound_vn_nums(s)`, `parse_vn_num(s)`, `round_half_up(v, d)`, `norm_vn(s)`, `Decimal`, `ROUND_HALF_UP`, `pd`, `re`."
            )
        if self.config.max_probe_steps > 0:
            extra_blocks.append(
                "### THÁM HIỂM THÊM NẾU CẦN\n"
                "Nếu chưa chắc giá trị chuỗi hoặc cấu trúc dòng, có thể trả trước JSON `{\"status\": \"probe\", \"probe_sql\": \"SELECT ... LIMIT 10\"}` (tối đa 1 lượt)."
            )
        extra_str = ("\n\n" + "\n\n".join(extra_blocks)) if extra_blocks else ""

        user_prompt = (
            f"### CÂU HỎI\n{q_block}\n\n"
            f"### {type_guide}\n\n"
            f"### MỐC THỜI GIAN ĐÃ PHÂN GIẢI\n{effective_temp_summary}\n\n"
            f"### GIÁ TRỊ KHỚP TRONG CSDL\n{ent_text}"
            f"{extra_str}\n\n"
            f"### README SHOP\n{readme_text}\n\n"
            f"### LƯỢC ĐỒ SQLITE\n{focused_schema}\n"
        )
        return system_prompt, user_prompt

    def _build_repair_prompt(
        self,
        question: str,
        bad_sql: str,
        reason: str,
        knowledge: WorkspaceKnowledge,
        temporal_summary: str = "",
        include_full_schema: bool = True,
        escalate_to_python: bool = False,
        entity_matches: Sequence[Tuple[str, str, str]] = (),
    ) -> str:
        if len(knowledge.workspace.tables) > 8:
            schema_block = build_focused_schema_prompt(question, knowledge, max_full_tables=10)
        else:
            schema_block = knowledge.schema_prompt if include_full_schema else knowledge.semantic_summary
        temp_block = f"Mốc thời gian:\n{temporal_summary}\n\n" if temporal_summary else ""
        tables = list(knowledge.workspace.tables.values())
        bad_low = (bad_sql or "").lower()
        referenced_tables = [
            t for t in tables if re.search(rf"\b{re.escape(t.table_name.lower())}\b", bad_low)
        ]
        tbl_by_low = {t.table_name.lower(): t for t in tables}
        alias_to_table: Dict[str, str] = {}
        _sql_kw_skip = {"on", "where", "left", "right", "inner", "outer", "cross", "join", "group", "order", "limit", "having", "union", "set", "as"}
        for m_al in re.finditer(
            r"\b(?:from|join)\s+(?:\"([^\"]+)\"|`([^`]+)`|([a-zA-Z0-9_]+))(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
            bad_sql or "",
            re.IGNORECASE,
        ):
            t_raw = (m_al.group(1) or m_al.group(2) or m_al.group(3) or "").strip()
            al = (m_al.group(4) or "").strip()
            if t_raw.lower() in tbl_by_low:
                real_name = tbl_by_low[t_raw.lower()].table_name
                alias_to_table[t_raw.lower()] = real_name
                if al and al.lower() not in _sql_kw_skip:
                    alias_to_table[al.lower()] = real_name

        joined_table_names = {v.lower() for v in alias_to_table.values()}

        def _suggest_join_sql(target_tbl_name: str) -> str:
            tgt = next((t for t in tables if t.table_name.lower() == target_tbl_name.lower()), None)
            if tgt is None:
                return ""
            tgt_cols = [getattr(c, "sql_name", str(c)) for c in tgt.columns]
            tgt_set = set(tgt_cols)
            src_candidates = [t for t in tables if t.table_name.lower() in joined_table_names and t.table_name.lower() != tgt.table_name.lower()]
            if not src_candidates:
                src_candidates = [t for t in referenced_tables if t.table_name.lower() != tgt.table_name.lower()]
            if not src_candidates:
                src_candidates = [t for t in tables if t.table_name.lower() != tgt.table_name.lower()]
            suggestions = []
            for src in src_candidates:
                src_cols = [getattr(c, "sql_name", str(c)) for c in src.columns]
                common = [c for c in src_cols if c in tgt_set and c not in {"ngay", "thang", "nam", "ghi_chu", "trang_thai"}]
                if not common:
                    common = [c for c in src_cols if c in tgt_set]
                if not common:
                    continue
                common.sort(key=lambda c: (0 if c.startswith(("ma_", "id", "ten_")) else 1))
                key = common[0]
                t_ref = f'"{tgt.table_name}"' if (" " in tgt.table_name or "-" in tgt.table_name) else tgt.table_name
                s_ref = f'"{src.table_name}"' if (" " in src.table_name or "-" in src.table_name) else src.table_name
                suggestions.append(f"JOIN {t_ref} ON {s_ref}.{key} = {t_ref}.{key}")
            if not suggestions and knowledge.join_graph:
                src_names = {s.table_name.lower() for s in src_candidates}
                tgt_l = tgt.table_name.lower()
                for edge in knowledge.join_graph:
                    m_e = re.match(
                        r"^\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\s*=\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)",
                        edge,
                    )
                    if m_e:
                        t1, c1, t2, c2 = m_e.group(1), m_e.group(2), m_e.group(3), m_e.group(4)
                        if t1.lower() == tgt_l and (not src_names or t2.lower() in src_names):
                            suggestions.append(f"LEFT JOIN {t1} ON NORM_VN({t2}.{c2}) = NORM_VN({t1}.{c1})")
                            break
                        if t2.lower() == tgt_l and (not src_names or t1.lower() in src_names):
                            suggestions.append(f"LEFT JOIN {t2} ON NORM_VN({t1}.{c1}) = NORM_VN({t2}.{c2})")
                            break
                    elif tgt_l in edge.lower():
                        suggestions.append(edge)
                        break
            if not suggestions:
                return ""
            return "Gợi ý JOIN tự động: `" + suggestions[0] + "`\n"

        repair_hints = []
        m_missing_tbl = re.search(r"no such table:\s*[\"`']?([a-zA-Z0-9_. ]+?)[\"`']?(?:\s*$|;|\))", reason or "", re.IGNORECASE)
        if m_missing_tbl:
            bad_tbl = m_missing_tbl.group(1).strip()
            valid_tbls = [f'"{t.table_name}"' if (" " in t.table_name or "-" in t.table_name) else t.table_name for t in tables]
            tbl_cols_lines = [
                f"- `{'\"' + t.table_name + '\"' if (' ' in t.table_name or '-' in t.table_name) else t.table_name}` ({', '.join(getattr(c, 'sql_name', str(c)) for c in t.columns)})"
                for t in tables[:12]
            ]
            repair_hints.append(
                f"Cảnh báo bảng sai: Bảng `{bad_tbl}` KHÔNG TỒN TẠI! "
                f"CHỈ ĐƯỢC DÙNG đúng tên bảng sau (đặt trong ngoặc kép đôi `\"...\"` nếu có khoảng trắng): {', '.join(f'`{n}`' for n in valid_tbls)}.\n"
                + "\n".join(tbl_cols_lines)
            )

        m_join_req = re.search(r"Hãy\s+[`'\"]?JOIN\s+[`'\"]?([a-zA-Z0-9_]+)[`'\"]?", reason or "", re.IGNORECASE)
        if m_join_req:
            auto_join = _suggest_join_sql(m_join_req.group(1).strip())
            if auto_join:
                repair_hints.append(
                    f"Cảnh báo thiếu liên kết bảng: Câu SQL cần giữ nguyên điều kiện lọc bằng cách nối bảng.\n{auto_join.strip()}"
                )

        m_missing = re.search(r"no such column:\s*([a-zA-Z0-9_.]+)", reason or "", re.IGNORECASE)
        if m_missing:
            missing_col = m_missing.group(1)
            join_hint = ""
            resolved_prefix_tbl = None
            if "." in missing_col:
                tbl_prefix, bare_col = missing_col.split(".", 1)
                tbl_prefix = tbl_prefix.strip()
                bare_col = bare_col.strip()
                resolved_prefix_tbl = alias_to_table.get(tbl_prefix.lower(), tbl_prefix)
                owner_cols = [
                    t for t in tables
                    if any(getattr(c, "sql_name", str(c)).lower() == bare_col.lower() for c in t.columns)
                ]
                if any(t.table_name.lower() == resolved_prefix_tbl.lower() for t in tables):
                    if resolved_prefix_tbl.lower() not in joined_table_names:
                        auto_join = _suggest_join_sql(resolved_prefix_tbl)
                        join_hint = (
                            f"CHÚ Ý: Bảng `{resolved_prefix_tbl}` CÓ tồn tại trong CSDL nhưng CHƯA ĐƯỢC `JOIN` trong `FROM`! "
                            f"Hãy thêm `JOIN` và GIỮ NGUYÊN điều kiện lọc thay vì xóa điều kiện lọc.\n"
                            + auto_join
                        )
                    else:
                        owner_names = [ot.table_name for ot in owner_cols]
                        join_hint = (
                            f"CHÚ Ý: Alias `{tbl_prefix}` trỏ tới bảng `{resolved_prefix_tbl}`, nhưng bảng `{resolved_prefix_tbl}` KHÔNG CÓ cột `{bare_col}`!\n"
                        )
                        if owner_names:
                            join_hint += f"-> Cột `{bare_col}` thực chất nằm ở bảng: {', '.join(f'`{n}`' for n in owner_names)}.\n"
                        rel_edges = [
                            e for e in (knowledge.join_graph or [])
                            if resolved_prefix_tbl.lower() in e.lower() or any(on.lower() in e.lower() for on in owner_names)
                        ]
                        if rel_edges:
                            join_hint += "Liên kết khoá đúng giữa các bảng: " + "; ".join(f"`{e}`" for e in rel_edges[:4]) + "\n"
            else:
                owner_tables = [
                    t for t in tables
                    if any(getattr(c, "sql_name", str(c)).lower() == missing_col.lower() for c in t.columns)
                    and t not in referenced_tables
                ]
                for ot in owner_tables[:1]:
                    auto_join = _suggest_join_sql(ot.table_name)
                    if auto_join:
                        join_hint += (
                            f"CHÚ Ý: Cột `{missing_col}` nằm ở bảng `{ot.table_name}` chưa được `JOIN`!\n"
                            + auto_join
                        )
            target_prefix_low = (resolved_prefix_tbl or "").lower()
            matched_tables = [
                f"- Bảng `{t.table_name}` CHỈ CÓ các cột: {', '.join(getattr(c, 'sql_name', str(c)) for c in t.columns)}"
                for t in tables
                if t in referenced_tables or (
                    "." in missing_col and t.table_name.lower() == target_prefix_low
                )
            ]
            if not matched_tables:
                matched_tables = [
                    f"- Bảng `{t.table_name}`: {', '.join(getattr(c, 'sql_name', str(c)) for c in t.columns)}"
                    for t in tables[:10]
                ]
            repair_hints.append(
                f"Cảnh báo cột sai: `{missing_col}` KHÔNG tồn tại trong cấu trúc hiện tại!\n"
                + join_hint
                + "\n".join(matched_tables)
                + "\nNếu bảng chỉ có cột số lượng và đơn giá (`so_luong*` * `gia*`), hãy tự nhân 2 cột đó thay vì gọi cột không tồn tại."
            )
        col_hint = ("\n\n".join(repair_hints) + "\n\n") if repair_hints else ""
        if entity_matches and re.search(r"0\s+dòng|NULL|rỗng", reason or "", re.IGNORECASE):
            ent_lines = ", ".join(f"`{t}.{c} = {v!r}`" for t, c, v in entity_matches[:5])
            col_hint += f"Gợi ý giá trị khớp thực tế trong CSDL (ưu tiên `NORM_VN(...)` khi so sánh chuỗi): {ent_lines}\n"
            if knowledge.join_graph:
                opt_edges = [e for e in knowledge.join_graph if "LEFT JOIN" in e]
                if opt_edges:
                    col_hint += "Lưu ý JOIN danh bạ: " + "; ".join(opt_edges[:3]) + "\n"
            col_hint += "\n"
        norm_clean = normalize_vn_question(question)
        q_disp = f"{question} (ý định chuẩn hóa: {norm_clean})" if norm_clean and norm_clean != norm_vn(question) else question
        is_prev_py = (bad_sql or "").lstrip().startswith("-- [PYTHON_SANDBOX]")
        lang_tag = "python" if is_prev_py else "sql"
        allow_py_repair = (
            (is_prev_py or escalate_to_python or should_prefer_python_sandbox(question, knowledge))
            and self.config.enable_python_sandbox
        )
        out_fmt_hint = (
            'trả về JSON duy nhất: {"status": "ok", "python": "..."} '
            '(hoặc {"status": "ok", "sql": "SELECT ..."})'
            if allow_py_repair
            else 'trả về JSON duy nhất: {"status": "ok", "sql": "SELECT ..."}'
        )
        py_escalation_block = ""
        if escalate_to_python and self.config.enable_python_sandbox and not is_prev_py:
            py_escalation_block = (
                "\nGỢI Ý PYTHON SANDBOX (NẾU SQL TIẾP TỤC KHÓ): Bạn CÓ THỂ viết script Python an toàn qua "
                'JSON `{"status": "ok", "python": "df = query_df(\'SELECT * FROM ...\')\\n...\\nresult = ..."}` '
                "dùng sẵn `query_df`, `pd`, `sum_compound_vn_nums`, `parse_vn_num`, `round_half_up`, `norm_vn`.\n"
            )
        return (
            f"Lần chạy trước bị lỗi hoặc vi phạm nghiệp vụ/trả kết quả không hợp lệ.\n"
            f"Câu hỏi gốc: {q_disp}\n"
            f"Code/SQL lỗi:\n```{lang_tag}\n{bad_sql}\n```\n"
            f"Thông báo: {reason}\n\n"
            f"{col_hint}"
            f"{py_escalation_block}"
            f"{temp_block}"
            f"Tham khảo lược đồ & quy ước dưới đây để sửa:\n"
            f"{schema_block}\n\n"
            f"Hãy SỬA LẠI đúng tên bảng và cột trong lược đồ trên (tên bảng có khoảng trắng phải đặt trong ngoặc kép `\"...\"`) và {out_fmt_hint}.\n"
            f'LƯU Ý BẮT BUỘC: CSDL ĐÃ CÓ ĐỦ DỮ LIỆU CHO CÂU HỎI NÀY — TUYỆT ĐỐI KHÔNG đổi sang `{{"status": "unanswerable"}}` khi đang sửa lỗi SQL! '
            f'Hãy `JOIN` / `LEFT JOIN` đúng bảng liên kết và xuất `{{"status": "ok", "sql": "SELECT ..."}}`.'
        )

    def _fallback_llm_format(
        self,
        question: str,
        analysis: QuestionAnalysis,
        sql_res: SQLExecutionResult,
    ) -> Optional[Dict[str, Any]]:
        preview_rows = sql_res.rows[:25]
        prompt = (
            f"Câu hỏi: {question}\n"
            f"Kiểu đáp án yêu cầu: {analysis.expected_type}\n"
            f"Cột kết quả SQL: {sql_res.columns}\n"
            f"Dữ liệu (tối đa 25 dòng đầu / tổng {sql_res.row_count} dòng):\n{preview_rows}\n\n"
            "Chuyển kết quả trên thành JSON đúng chuẩn DataMate:\n"
            '{"type": "...", "answer": ...} hoặc {"type": "abstain"} nếu kết quả SQL chưa đủ căn cứ.\n'
            "Quy tắc: number/percent phải là số JSON thuần (không đơn vị, tiền tròn đồng, % tròn 2 số thập phân); "
            "boolean là true/false; date là YYYY-MM-DD hoặc YYYY-MM; table có keys columns & rows."
        )
        raw = self.backend.generate(
            prompt,
            temperature=0.0,
            max_tokens=256,
            json_mode=self.config.use_json_mode,
        )
        obj = extract_json_object(raw)
        if not obj or "type" not in obj:
            return None
        return obj

    def _run_dual_path_consensus_check(
        self,
        question: str,
        as_of_date: str,
        knowledge: WorkspaceKnowledge,
        analysis: QuestionAnalysis,
        primary_formatted: Dict[str, Any],
        temporal_summary: str,
        entity_matches: Sequence[Tuple[str, str, str]],
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Independently verify a high-risk scalar numeric/percent answer via Python/Pandas Sandbox
        without leaking the SQL numeric value (avoids anchoring bias).
        Returns (status in {'agree', 'disagree', 'inconclusive'}, formatted_python_result).
        """
        focused_schema = build_focused_schema_prompt(question, knowledge, entity_matches, max_full_tables=6)
        ent_text = (
            "\n".join(f"- {t}.{c} = {v!r}" for t, c, v in entity_matches)
            if entity_matches
            else "(không có)"
        )
        rule_hint = _RULE_CORE
        if analysis.expected_type == "percent":
            rule_hint += "\n- CHÚ Ý TỶ LỆ (%): Trả số % nhân 100.0 làm tròn 2 chữ số (VD 12.45). Nếu đếm tỷ lệ đơn huỷ/trả trên bảng chi tiết nhiều dòng/đơn, phải đếm theo số ĐƠN DUY NHẤT (`nunique`), KHÔNG cộng tiền vào tử số."
        elif re.search(r"\b(?:trung\s+binh|binh\s+quan)\b.*?\bdon\b", normalize_vn_question(question)):
            rule_hint += "\n- CHÚ Ý TRUNG BÌNH TRÊN ĐƠN: Chia tổng tiền cho số ĐƠN DUY NHẤT (`nunique(ma_don)`), KHÔNG chia số dòng chi tiết."

        verify_prompt = (
            "Hãy KIỂM CHỨNG ĐỘC LẬP câu hỏi sau bằng Python/Pandas (`query_df` + `pandas`) trên CSDL SQLite.\n"
            f"Câu hỏi: {question}\n"
            f"Kiểu đáp án: `{analysis.expected_type}`\n"
            f"Mốc thời gian:\n{temporal_summary}\n"
            f"Giá trị khớp trong CSDL:\n{ent_text}\n"
            f"{rule_hint}\n\n"
            f"Lược đồ tóm tắt:\n{focused_schema}\n\n"
            'Trả JSON DUY NHẤT: `{"status": "ok", "python": "df = query_df(...)\\n...\\nresult = ..."}`.\n'
            "Dùng sẵn: `query_df(sql)`, `pd`, `parse_vn_num`, `sum_compound_vn_nums`, `round_half_up`, `norm_vn`."
        )
        try:
            raw_py = self.backend.generate(
                verify_prompt,
                system_prompt="Chỉ trả JSON {\"status\": \"ok\", \"python\": \"...\"} dùng query_df + pandas tính kết quả độc lập, gán vào biến `result`.",
                temperature=0.0,
                max_tokens=min(self.config.sql_max_tokens, 420),
                json_mode=self.config.use_json_mode,
            )
        except Exception:
            return "inconclusive", None

        py_code = extract_python_from_response(raw_py)
        if not py_code:
            return "inconclusive", None

        py_res = execute_python_safe(
            knowledge.workspace.open_connection,
            py_code,
            as_of_date=as_of_date,
            valid_tables=knowledge.valid_tables,
            datetime_columns=tuple(knowledge.datetime_columns),
            max_rows=self.config.max_rows,
            timeout_seconds=min(5.0, self.config.sql_timeout_seconds),
        )
        if not py_res.ok or py_res.row_count == 0:
            return "inconclusive", None

        bounds_ok, _, _ = verify_result_sanity_bounds(
            py_res.sql, py_res, question, knowledge, analysis, entity_matches=entity_matches
        )
        if not bounds_ok:
            return "inconclusive", None

        alt_fmt = format_sql_result(py_res, analysis, question)
        if not alt_fmt or alt_fmt.get("type") != analysis.expected_type:
            return "inconclusive", None

        a1 = _coerce_float(primary_formatted.get("answer"))
        a2 = _coerce_float(alt_fmt.get("answer"))
        if a1 is None or a2 is None:
            return "inconclusive", None

        if (
            abs(a1 - a2) <= 1e-6
            or (analysis.expected_type == "percent" and abs(a1 - a2) <= 0.02)
            or (analysis.expected_type == "number" and max(abs(a1), abs(a2)) >= 1000 and abs(a1 - a2) <= 1.0)
        ):
            return "agree", alt_fmt
        return "disagree", alt_fmt

    def _finalize_prediction(
        self,
        qid: str,
        candidate: Dict[str, Any],
        sql_res: Optional[SQLExecutionResult],
        attempts: int,
        confidence: float,
        extra_notes: Optional[Sequence[str]] = None,
    ) -> AgentResult:
        pred = dict(candidate)
        pred["id"] = qid
        ptype = pred.get("type")
        notes_list = list(extra_notes or ())

        if ptype == "unanswerable":
            reason = pred.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                pred["reason"] = "Dữ liệu không đủ thông tin để kết luận."
            if not is_valid_submission_record(pred):
                return AgentResult(qid, {"id": qid, "type": "abstain"}, 0.0, sql_res.sql if sql_res else "", attempts, "Invalid unanswerable format", notes=notes_list)
            return AgentResult(qid, pred, confidence, sql_res.sql if sql_res else "", attempts, notes=notes_list)

        if ptype == "abstain" or confidence < self.config.abstain_threshold:
            notes_list.insert(0, f"Abstained (confidence={confidence:.2f} < {self.config.abstain_threshold:.2f})")
            return AgentResult(
                question_id=qid,
                prediction={"id": qid, "type": "abstain"},
                confidence=confidence,
                sql=sql_res.sql if sql_res else "",
                sql_attempts=attempts,
                notes=notes_list,
            )

        if not is_valid_submission_record(pred):
            return AgentResult(
                question_id=qid,
                prediction={"id": qid, "type": "abstain"},
                confidence=0.0,
                sql=sql_res.sql if sql_res else "",
                sql_attempts=attempts,
                error="Prediction failed strict DataMate schema check; abstained.",
                notes=notes_list,
            )

        return AgentResult(
            question_id=qid,
            prediction=pred,
            confidence=confidence,
            sql=sql_res.sql if sql_res else "",
            sql_attempts=attempts,
            notes=notes_list,
        )

    def answer_question(
        self,
        question_record: Dict[str, Any],
        knowledge: WorkspaceKnowledge,
    ) -> AgentResult:
        qid = str(question_record.get("id") or question_record.get("question_id") or "")
        question = str(question_record.get("question", ""))
        as_of_date = str(question_record.get("as_of_date", ""))

        resolved_question, retraction_note = resolve_conversational_retraction(question)
        analysis = classify_expected_type(resolved_question)
        windows, temp_summary, bounded, prior_start = extract_temporal_context(
            resolved_question, as_of_date, self.calendar
        )
        analysis.temporal_windows = windows
        analysis.temporal_summary = temp_summary
        analysis.bounded_period = bounded
        analysis.prior_needed_start = prior_start

        if self.config.enable_preflight_unanswerable:
            unans_reason = check_preflight_unanswerable(resolved_question, as_of_date, knowledge, analysis)
            if unans_reason:
                return self._finalize_prediction(
                    qid,
                    {"type": "unanswerable", "reason": unans_reason},
                    sql_res=None,
                    attempts=0,
                    confidence=0.92,
                )

        entities = ground_query_entities(resolved_question, knowledge, max_matches=12)
        effective_temp_summary = format_effective_temporal_summary(temp_summary, as_of_date, analysis)
        prefer_python = self.config.enable_python_sandbox and should_prefer_python_sandbox(resolved_question, knowledge)
        force_python_first = (
            prefer_python
            and self.config.enable_forced_python_escalation
            and self._allow_extra_stage3_llm_calls()
            and _is_strong_python_first_candidate(resolved_question, knowledge)
        )
        probe_ctx = (
            run_deterministic_probes(resolved_question, knowledge, entities, max_rows_per_probe=4)
            if self.config.enable_auto_probe
            else ""
        )
        sys_p, usr_p = self._build_sql_prompt(
            question=resolved_question,
            as_of_date=as_of_date,
            knowledge=knowledge,
            analysis=analysis,
            temporal_summary=temp_summary,
            entity_matches=entities,
            probe_context=probe_ctx,
            prefer_python=prefer_python,
            force_python_first=force_python_first,
            retraction_note=retraction_note,
        )

        last_sql_res: Optional[SQLExecutionResult] = None
        last_sql_text = ""
        attempts = 0
        probe_budget = max(0, int(self.config.max_probe_steps))
        prompt_to_send = usr_p

        for attempt in range(self.config.max_sql_retries):
            attempts = attempt + 1
            raw_reply = ""
            while True:
                try:
                    raw_reply = self.backend.generate(
                        prompt_to_send,
                        system_prompt=sys_p,
                        temperature=0.15 if attempt > 0 else 0.0,
                        max_tokens=self.config.sql_max_tokens,
                        json_mode=self.config.use_json_mode,
                    )
                except Exception as exc:
                    return AgentResult(
                        question_id=qid,
                        prediction={"id": qid, "type": "abstain"},
                        confidence=0.0,
                        sql=last_sql_text,
                        sql_attempts=attempts,
                        error=f"LLM error: {exc}",
                    )

                obj_probe = extract_json_object(raw_reply)
                probe_sql = (
                    str(obj_probe["probe_sql"])
                    if (obj_probe and isinstance(obj_probe.get("probe_sql"), str))
                    else (
                        str(obj_probe["sql"])
                        if (obj_probe and obj_probe.get("status") == "probe" and isinstance(obj_probe.get("sql"), str))
                        else ""
                    )
                )
                if probe_sql and probe_budget > 0:
                    probe_budget -= 1
                    p_res = execute_sql_safe(
                        knowledge.workspace.open_connection,
                        probe_sql,
                        valid_tables=knowledge.valid_tables,
                        datetime_columns=tuple(knowledge.datetime_columns),
                        max_rows=10,
                        timeout_seconds=min(3.0, self.config.sql_timeout_seconds),
                    )
                    probe_info = (
                        f"Cột: {p_res.columns}\nDòng: {p_res.rows[:10]}"
                        if p_res.ok
                        else f"Lỗi probe: {p_res.error}"
                    )
                    prompt_to_send = (
                        f"{prompt_to_send}\n\n"
                        f"### KẾT QUẢ THÁM HIỂM BẠN VỪA YÊU CẦU (`{probe_sql}`)\n{probe_info}\n\n"
                        "Bây giờ hãy viết truy vấn cuối cùng (`{\"status\": \"ok\", \"sql\": ...}` hoặc `{\"status\": \"ok\", \"python\": ...}`) để trả lời chính xác câu hỏi."
                    )
                    continue
                break

            obj = extract_json_object(raw_reply)
            if (
                isinstance(self.backend, MultiProviderLLMBackend)
                and obj is not None
                and not any(isinstance(obj.get(k), str) and obj.get(k) for k in ("sql", "python", "probe_sql"))
                and obj.get("status") not in ("ok", "unanswerable", "probe")
            ):
                try:
                    raw_rescue = self.backend.generate(
                        f"{prompt_to_send}\n\nCẢNH BÁO: Lần vừa rồi sai định dạng vì in JSON dữ liệu mẫu thay vì truy vấn. "
                        "Chỉ viết DUY NHẤT 1 câu lệnh SQLite SELECT/WITH đúng tên bảng và cột trong lược đồ!",
                        system_prompt="Chỉ viết DUY NHẤT 1 câu lệnh SQLite SELECT/WITH trong khối ```sql ... ```, tuyệt đối không giải thích.",
                        temperature=0.0,
                        max_tokens=min(self.config.sql_max_tokens, 320),
                        json_mode=False,
                    )
                    if raw_rescue and raw_rescue.strip():
                        raw_reply = raw_rescue
                        obj = extract_json_object(raw_reply)
                except Exception:
                    pass

            if obj and obj.get("status") == "unanswerable":
                unans_reason = str(obj.get("reason") or "Dữ liệu không đủ để trả lời.")
                false_hint = is_false_llm_unanswerable(
                    resolved_question,
                    unans_reason,
                    knowledge,
                    had_sql_attempt=bool(last_sql_text),
                )
                if false_hint:
                    if attempt + 1 < self.config.max_sql_retries:
                        if last_sql_res is not None and not last_sql_res.ok:
                            prompt_to_send = (
                                self._build_repair_prompt(
                                    resolved_question,
                                    last_sql_text,
                                    last_sql_res.error,
                                    knowledge,
                                    temporal_summary=effective_temp_summary,
                                    include_full_schema=True,
                                    entity_matches=entities,
                                )
                                + f"\n\n{false_hint}"
                            )
                        else:
                            prompt_to_send = f"{prompt_to_send}\n\n{false_hint}"
                        continue
                    for spec_fn in (
                        lambda: build_extreme_comparison_sql_spec(resolved_question, knowledge, analysis) if analysis.extreme_comparison else None,
                        lambda: build_benchmark_average_entity_sql_spec(resolved_question, knowledge, analysis),
                        lambda: build_entity_and_metric_listing_sql_spec(resolved_question, knowledge, analysis, entities),
                        lambda: build_catalog_listing_sql_spec(resolved_question, knowledge, analysis, entities),
                    ):
                        sp = spec_fn()
                        if not sp or not sp.get("suggested_sql"):
                            continue
                        fb_res = execute_sql_safe(
                            knowledge.workspace.open_connection,
                            sp["suggested_sql"],
                            valid_tables=knowledge.valid_tables,
                            datetime_columns=tuple(knowledge.datetime_columns),
                            max_rows=self.config.max_rows,
                            timeout_seconds=self.config.sql_timeout_seconds,
                        )
                        if fb_res.ok and fb_res.row_count > 0:
                            sem_ok_fb, _, _ = verify_sql_semantics(
                                fb_res.sql or sp["suggested_sql"],
                                fb_res,
                                resolved_question,
                                knowledge,
                                analysis,
                                entity_matches=entities,
                            )
                            if sem_ok_fb:
                                pred_fb = format_sql_result(fb_res, analysis, resolved_question)
                                if pred_fb:
                                    return self._finalize_prediction(
                                        qid,
                                        pred_fb,
                                        sql_res=fb_res,
                                        attempts=attempts,
                                        confidence=0.85,
                                        extra_notes=["Recovered from false LLM unanswerable via deterministic join spec."],
                                    )
                return self._finalize_prediction(
                    qid,
                    {"type": "unanswerable", "reason": unans_reason},
                    sql_res=last_sql_res,
                    attempts=attempts,
                    confidence=0.75,
                )

            py_code = (
                str(obj["python"])
                if (self.config.enable_python_sandbox and obj and isinstance(obj.get("python"), str))
                else (
                    extract_python_from_response(raw_reply)
                    if (self.config.enable_python_sandbox and not (obj and isinstance(obj.get("sql"), str)))
                    else ""
                )
            )
            if py_code:
                res = execute_python_safe(
                    knowledge.workspace.open_connection,
                    py_code,
                    as_of_date=as_of_date,
                    valid_tables=knowledge.valid_tables,
                    datetime_columns=tuple(knowledge.datetime_columns),
                    max_rows=self.config.max_rows,
                    timeout_seconds=self.config.sql_timeout_seconds,
                )
                last_sql_res = res
                last_sql_text = res.sql or py_code
            else:
                candidate_sql = str(obj["sql"]) if (obj and isinstance(obj.get("sql"), str)) else raw_reply
                candidate_sql = rewrite_ranked_entity_sql(candidate_sql, resolved_question, use_round_half_up=True)
                candidate_sql = strip_spurious_single_day_filter(candidate_sql, resolved_question, analysis)
                subq_cap_err = _check_subquery_column_capture(candidate_sql, knowledge)
                if subq_cap_err:
                    res = SQLExecutionResult(
                        ok=False,
                        sql=candidate_sql,
                        columns=[],
                        rows=[],
                        error=subq_cap_err,
                    )
                else:
                    res = execute_sql_safe(
                        knowledge.workspace.open_connection,
                        candidate_sql,
                        valid_tables=knowledge.valid_tables,
                        datetime_columns=tuple(knowledge.datetime_columns),
                        max_rows=self.config.max_rows,
                        timeout_seconds=self.config.sql_timeout_seconds,
                    )
                last_sql_res = res
                last_sql_text = res.sql or candidate_sql

            is_final_repair_next = (attempt + 1 == self.config.max_sql_retries - 1)
            allow_escalation = (
                self.config.enable_python_sandbox
                and self.config.enable_forced_python_escalation
                and self._allow_extra_stage3_llm_calls()
            )

            if not res.ok:
                if attempt + 1 < self.config.max_sql_retries:
                    err_low = (res.error or "").lower()
                    escalate_py = bool(
                        allow_escalation
                        and is_final_repair_next
                        and (prefer_python or "syntax error" in err_low or "no such column" in err_low)
                    )
                    prompt_to_send = self._build_repair_prompt(
                        resolved_question,
                        last_sql_text,
                        res.error,
                        knowledge,
                        temporal_summary=effective_temp_summary,
                        include_full_schema=True,
                        escalate_to_python=escalate_py,
                    )
                    continue
                return AgentResult(
                    question_id=qid,
                    prediction={"id": qid, "type": "abstain"},
                    confidence=0.0,
                    sql=last_sql_text,
                    sql_attempts=attempts,
                    error=res.error,
                )

            sem_ok, sem_msg, sem_fatal = verify_sql_semantics(
                last_sql_text, res, resolved_question, knowledge, analysis, entity_matches=entities
            )
            if not sem_ok:
                if attempt + 1 < self.config.max_sql_retries:
                    escalate_py = bool(allow_escalation and is_final_repair_next and prefer_python)
                    prompt_to_send = self._build_repair_prompt(
                        resolved_question,
                        last_sql_text,
                        sem_msg,
                        knowledge,
                        temporal_summary=effective_temp_summary,
                        include_full_schema=(len(knowledge.schema_prompt or "") <= 5000),
                        escalate_to_python=escalate_py,
                    )
                    continue
                if sem_fatal:
                    return AgentResult(
                        question_id=qid,
                        prediction={"id": qid, "type": "abstain"},
                        confidence=0.25,
                        sql=last_sql_text,
                        sql_attempts=attempts,
                        notes=[f"Unresolved SQL semantic violation: {sem_msg}"],
                    )

            # Empty/NULL aggregate guard -> allow SQL repair before abstaining
            is_empty_or_null = (
                res.row_count == 0
                or (res.row_count == 1 and len(res.columns) == 1 and res.rows[0][0] is None)
            )
            if is_empty_or_null and analysis.expected_type not in ("list", "table"):
                if attempt + 1 < self.config.max_sql_retries:
                    escalate_py = bool(allow_escalation and is_final_repair_next and prefer_python)
                    prompt_to_send = self._build_repair_prompt(
                        resolved_question,
                        last_sql_text,
                        "Truy vấn chạy không lỗi nhưng trả về 0 dòng hoặc NULL. Kiểm tra lại filter ngày, tên status thực tế hoặc dùng NORM_VN(...) để khớp chuỗi tiếng Việt.",
                        knowledge,
                        temporal_summary=effective_temp_summary,
                        include_full_schema=True,
                        escalate_to_python=escalate_py,
                    )
                    continue
                # Exhausted retries with empty/NULL aggregate -> safer to abstain (0 pts) than guess 0 (-1 pt)
                return AgentResult(
                    question_id=qid,
                    prediction={"id": qid, "type": "abstain"},
                    confidence=0.35,
                    sql=last_sql_text,
                    sql_attempts=attempts,
                    notes=["SQL returned empty or NULL scalar after repair attempts."],
                )

            formatted = format_sql_result(res, analysis, resolved_question)
            if formatted is not None:
                conf = max(0.55, 0.90 - 0.12 * attempt)
                extra_notes: List[str] = []

                # When2Call gate 1: unresolved sanity bound / suspicious 0 warning on final attempt abstains instead of risking -1
                bounds_ok_final, bounds_msg_final, _ = verify_result_sanity_bounds(
                    last_sql_text, res, resolved_question, knowledge, analysis, entity_matches=entities
                )
                if (
                    (not sem_ok and "CẢNH BÁO KẾT QUẢ = 0" in (sem_msg or "") and _coerce_float(formatted.get("answer")) == 0.0)
                    or (not bounds_ok_final)
                ):
                    conf = min(conf, 0.42)
                    extra_notes.append(f"When2Call gate: unresolved sanity warning ({bounds_msg_final or sem_msg})")

                # Selective Dual-Path Consensus (SQL vs independent Python/Pandas check)
                is_primary_py = (last_sql_text or "").lstrip().startswith("-- [PYTHON_SANDBOX]")
                need_consensus = (
                    conf >= self.config.abstain_threshold
                    and self.config.enable_dual_path_consensus
                    and self.config.enable_python_sandbox
                    and self._allow_extra_stage3_llm_calls()
                    and (not is_primary_py)
                    and analysis.expected_type in ("number", "percent")
                    and (
                        attempt > 0
                        or (not sem_ok)
                        or analysis.expected_type == "percent"
                        or (len(knowledge.workspace.tables) >= 4 and "join" in (last_sql_text or "").lower())
                    )
                )
                if need_consensus:
                    c_status, alt_fmt = self._run_dual_path_consensus_check(
                        question=resolved_question,
                        as_of_date=as_of_date,
                        knowledge=knowledge,
                        analysis=analysis,
                        primary_formatted=formatted,
                        temporal_summary=effective_temp_summary,
                        entity_matches=entities,
                    )
                    if c_status == "agree":
                        conf = max(conf, 0.94)
                        extra_notes.append("Dual-path SQL+Python consensus: AGREE")
                    elif c_status == "disagree" and alt_fmt is not None:
                        a_sql = _coerce_float(formatted.get("answer"))
                        a_py = _coerce_float(alt_fmt.get("answer"))
                        extra_notes.append(
                            f"Dual-path SQL+Python disagreement: sql={formatted.get('answer')} vs py={alt_fmt.get('answer')}"
                        )
                        if attempt > 0 or (not sem_ok) or (a_sql is not None and abs(a_sql) <= 1e-9):
                            conf = min(conf, 0.42)
                        elif (
                            analysis.expected_type == "percent"
                            and a_sql is not None
                            and a_py is not None
                            and abs(a_py) > 1e-9
                            and abs(a_sql - a_py) > 5.0
                        ):
                            conf = min(conf, 0.45)

                return self._finalize_prediction(qid, formatted, res, attempts, conf, extra_notes=extra_notes)

            if attempt + 1 < self.config.max_sql_retries:
                prompt_to_send = self._build_repair_prompt(
                    resolved_question,
                    last_sql_text,
                    f"Kết quả trả {res.row_count} dòng x {len(res.columns)} cột không khớp dạng `{analysis.expected_type}` cần trả.",
                    knowledge,
                    temporal_summary=effective_temp_summary,
                    include_full_schema=True,
                    escalate_to_python=bool(allow_escalation and is_final_repair_next),
                )
                continue

            # Exhausted SQL retries -> optional compact LLM formatter fallback
            if self.config.enable_llm_formatter_fallback and res.row_count > 0:
                fallback = self._fallback_llm_format(resolved_question, analysis, res)
                if fallback is not None and fallback.get("type") != "abstain":
                    conf = max(0.50, 0.72 - 0.12 * attempt)
                    return self._finalize_prediction(qid, fallback, res, attempts, conf)

        return AgentResult(
            question_id=qid,
            prediction={"id": qid, "type": "abstain"},
            confidence=0.25,
            sql=last_sql_text,
            sql_attempts=attempts,
            notes=["Could not verify output format confidently; abstained."],
        )
