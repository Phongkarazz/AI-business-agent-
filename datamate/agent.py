"""Headless, domain-agnostic DataMate analytics agent with strict output typing & risk-aware abstention."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from datamate.evaluator_pa import is_valid_submission_record
from datamate.llm_backend import LLMBackend, LLMConfig, MultiProviderLLMBackend, extract_json_object
from datamate.loader import BusinessWorkspace, load_business_workspace
from datamate.schema_context import WorkspaceKnowledge, build_workspace_knowledge, ground_query_entities
from datamate.sql_executor import SQLExecutionResult, execute_sql_safe, norm_vn, round_half_up
from datamate.temporal import SolarLunarCalendar, TemporalResolver, normalize_nfc, parse_date_value

_ENGLISH_KEEP_WORDS = frozenset(
    {
        "bill", "bills", "size", "combo", "order", "orders", "staff", "coffee",
        "milk", "juice", "latte", "tea", "plus", "kids", "cool", "box", "pack",
        "pcs", "ok", "cod", "vat", "zalo", "store", "cash", "phone", "mail",
        "admin", "soda", "extra", "special", "gold", "silver", "max", "mini",
        "pro", "care", "gel", "cream", "spray", "oil", "gas", "led", "pvc",
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
_RULE_RANKING = "- Xếp hạng & Đếm món: 'bán chạy' / 'hot nhất' = tổng SL quy về ĐƠN VỊ CƠ BẢN (bỏ đơn huỷ/trả). Bỏ qua dòng 'Phí phục vụ' khi xếp hạng món (vẫn tính vào doanh thu). Bằng nhau xếp theo mã (hoặc tên) tăng dần. Tồn theo đơn vị lớn trả 2 số `[nguyên, lẻ]`."
_RULE_INVENTORY_COST = "- Nhập/Kho/Giá vốn/Lãi: tiền nhập tính mọi phiếu nhập không huỷ (kể cả nhập đầu kỳ) theo ngày phiếu; giá nhập BQ = `SUM(thanh_tien)/SUM(so_luong)`. Lãi gộp = doanh thu - `SUM(so_luong * gia_von_dong)`. Lãi ròng = lãi gộp - chi phí. Giá bán ngày D tính cả đơn huỷ/trả."
_RULE_INDUSTRY_PHARMACY = "- Nhà thuốc: thuốc kê đơn lấy theo cột kê đơn trong danh mục thuốc; còn tồn hết hạn `D..D+N` tính theo giá nhập chính lô đó. Hoạt chất phối hợp là loại riêng."
_RULE_INDUSTRY_CAFE = "- Cà phê: size M/L = món có tên kết thúc bằng `(M)` hoặc `(L)` (không phân biệt hoa thường)."
_RULE_INDUSTRY_VLXD = "- VLXD giao nhiều đợt: mỗi đợt của mỗi đơn có ngày giao trong kỳ tính 1 đợt (kể cả đơn sau đó trả hàng)."


_SUBJECTIVE_RE = re.compile(
    r"(?:l[aà]nh ngh[eề]|tay ngh[eề]|l[eễ] ph[eé]p|chu [dđ][aá]o|qu[yý] m[eế]n|th[aá]i [dđ][oộ]|nhi[eệ]t t[iì]nh|ngoan|th[oô]ng minh"
    r"|(?:t[aạ]i sao|v[iì] sao|tai sao|vi sao|ly do|nguy[eê]n nh[aâ]n|nguyen nhan).*(?:th[ií]ch|thich|y[eê]u th[ií]ch|[uư]a chu[oộ]ng|ua chuong|h[aà]i l[oò]ng|hai long))",
    re.IGNORECASE,
)


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
    sql_max_tokens: int = 384


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


@dataclass
class AgentResult:
    question_id: str
    prediction: Dict[str, Any]
    confidence: float
    sql: str = ""
    sql_attempts: int = 0
    error: str = ""
    notes: List[str] = field(default_factory=list)


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

    # 1. Table (explicit table prompt or multi-metric per object)
    q_low_nfc = q_nfc.lower()
    if (
        re.search(r"\b(?:cho|xuất|lập|tạo)\s+bảng\b|\bbảng\s*\d+\b", q_low_nfc)
        or re.search(r"(?:kem so tien|so no cua tung|moi nguoi con no|kem doanh thu|kem so luong)", qn)
    ):
        cols = ["khach_hang", "so_tien_no"] if re.search(r"\bno\b", qn) else None
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
        return QuestionAnalysis(expected_type="date", date_granularity="month")
    if re.search(r"\b(?:ngay nao|hom nao|bua nao)\b", qn):
        return QuestionAnalysis(expected_type="date", date_granularity="day")

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
        r"(?:top\s*\d+|liet ke|nhung (?:mat )?hang nao|nhung san pham nao|nhung mon nao|nhung khach(?: hang)? nao|"
        r"(?<!/)(?<!\d)\b(?:[2-9]|1\d|20)\s+(?:mat hang|hang hoa|hang|mon|san pham|khach hang|khach|nhan vien|nha cung cap|nhom hang|lo\b(?!\s*x\s*\d)))",
        qn_for_topk,
    )
    if plural_top_match:
        return QuestionAnalysis(expected_type="list")

    # 6. String (single named customer/item/staff/supplier/batch)
    if (
        re.search(
            r"(?:la ai|ai la|ai trong|\bai\b.*\bnhat\b|khach(?: hang)? nao|mat hang nao|hang nao|san pham nao|mon nao|"
            r"nhan vien nao|nha cung cap nao|nhom hang nao|lo nao|"
            r"\b(?:san pham|mat hang|hang|mon|khach hang|nhan vien|nha cung cap)\b.*\b(?:la gi|la chi|la ai)\b)",
            qn,
        )
        and not re.search(r"\b(?:bao nhieu|may|nhung ai|top)\b", qn)
    ):
        return QuestionAnalysis(expected_type="string")

    return QuestionAnalysis(expected_type="number", money_like=money_like)


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

    # Explicit months tháng M/YYYY or tháng M năm YYYY
    explicit_months = re.findall(r"thang\s*(\d{1,2})\s*(?:/|\s*nam\s*)(\d{4})", qn)
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
    caps = knowledge.capabilities
    readme_n = norm_vn(knowledge.workspace.readme_text)

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

    # 3. Missing schema capability checks (using active-column capabilities + normalized question)
    if re.search(r"\bkhach(?:\s+hang)?\s+(?:nam|nu)\b", qn) and not caps["has_customer_gender"]:
        return "Dữ liệu shop không ghi thông tin giới tính khách hàng."
    if re.search(r"(?:o\s+duong\s+|dia\s+chi\b)", qn) and not caps["has_customer_address"]:
        return "Dữ liệu shop không ghi địa chỉ khách hàng."
    if re.search(r"(?:khach\s+nhom\s+|nhom\s+khach)", qn) and not caps["has_customer_group"]:
        return "Dữ liệu shop không có cột phân nhóm khách hàng."
    if re.search(r"(?:ban\s+qua\s+dien\s+thoai|ban\s+qua\s+zalo|kenh\s+ban|tai\s+quay)", qn) and not caps["has_channel"]:
        return "Dữ liệu shop không ghi kênh bán hàng."
    if re.search(r"(?:tra\s+bang\s+(?:cod|tien mat|chuyen khoan)|phuong\s+thuc\s+thanh\s+toan|hinh\s+thuc\s+thanh\s+toan)", qn) and not caps["has_payment_method"]:
        return "Dữ liệu shop không ghi hình thức thanh toán."
    if re.search(r"(?:tra\s+hang\s+vi|tra\s+vi\s+|ly\s+do\s+tra|nguyen\s+nhan\s+tra)", qn) and not caps["has_return_reason"]:
        return "Dữ liệu shop không ghi nguyên nhân trả hàng."
    if re.search(r"(?:han\s+dung|han\s+su\s+dung|het\s+han\s+trong)", qn) and not caps["has_expiry"]:
        return "Dữ liệu shop không ghi hạn sử dụng."
    if re.search(r"(?:ton\s+kho|ton\s+cuoi|trong\s+kho\s+con|con\s+lai\s+may|con\s+ton)", qn) and not caps["has_inventory"]:
        return "Dữ liệu shop không có bảng/cột theo dõi tồn kho."
    if re.search(r"(?:gia\s+von|lai\s+gop)", qn) and not caps["has_cost_price"]:
        return "Dữ liệu shop không ghi giá vốn nên không tính được lãi gộp/giá trị theo giá vốn."
    if re.search(r"\blai\s+rong\b", qn) and not (caps["has_cost_price"] and caps["has_expenses"]):
        return "Dữ liệu shop thiếu giá vốn hoặc sổ chi phí nên không tính được lãi ròng."
    if re.search(r"(?:tien\s+nhap|gia\s+nhap|phieu\s+nhap|nhap\s+vao\s+gia|nhap\s+.*binh\s+quan)", qn):
        if not caps["has_import"] or (
            re.search(r"(?:tien|gia|binh\s+quan)", qn) and not caps["has_import_price"] and "gia_nhap" not in readme_n
        ):
            return "Dữ liệu shop không ghi đơn giá/giá trị phiếu nhập hàng."
    if re.search(r"(?:con\s+thieu|con\s+no|ghi\s+no|mua\s+chiu|tra\s+no|thu\s+hoi.*no|tuoi\s+no|no\s+(?:nhieu|lon)\s+nhat|khach\s+no|so\s+tien\s+no)", qn) and not caps["has_debt_or_payments"]:
        return "Dữ liệu shop không có thông tin thu tiền/công nợ."
    if re.search(r"(?:\bkhach(?:\s+hang)?\s+nao|\bbao\s+nhieu\s+khach|so\s+khach|khach\s+da\s+mua|\bai\s+la\s+khach|chi\s+tieu\s+nhieu)", qn) and not caps["has_customers"]:
        return "Dữ liệu shop không lưu danh tính/mã khách hàng trên đơn."
    return None


def _select_rulebook_prompt(
    question: str,
    as_of_date: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
) -> str:
    """Assemble a concise, intent-specific rulebook prompt (cuts prefill tokens & prevents debt hallucination)."""
    qn = normalize_vn_question(question)
    caps = knowledge.capabilities
    sections: List[str] = [
        "Bạn là chuyên gia viết SQLite cho DataMate. CHỈ dùng tên bảng/cột có trong lược đồ. Có sẵn UDF: `NORM_VN(col)` và `ROUND_HALF_UP(val, d)`.",
        f"- Hôm nay (`as_of_date`) = `{as_of_date}`.",
    ]
    if not analysis.temporal_windows and analysis.bounded_period is None:
        sections.append(
            f"- QUAN TRỌNG: Câu hỏi KHÔNG hỏi riêng ngày hôm nay hay khoảng ngày cụ thể -> truy vấn TOÀN BỘ DỮ LIỆU lịch sử đến hết `{as_of_date}`. TUYỆT ĐỐI KHÔNG tự thêm `ngay = '{as_of_date}'`!"
        )
    if knowledge.data_max_date and knowledge.data_max_date > as_of_date:
        sections.append(
            f"- Phát sinh đơn sau `{as_of_date}` coi như chưa xảy ra (chỉ dùng `<= '{as_of_date}'` cho câu lũy kế/cutoff; riêng câu hỏi đúng ngày/tháng dùng `=` hoặc `BETWEEN`)."
        )
    sections.append(_RULE_CORE)

    if re.search(r"\b(?:khach|ai|top|nhom)\b", qn) and caps.get("has_customers"):
        sections.append(_RULE_CUSTOMERS)
    if caps.get("has_debt_or_payments") and re.search(
        r"\b(?:no|chua tra|da tra|da thu|con thieu|phai thu|tuoi no|ghi no|tra no|thu hoi|thu no|so quy|tien mat|chuyen khoan|cod|pttt)\b",
        qn,
    ):
        sections.append(_RULE_DEBT)
    if analysis.expected_type in ("string", "list", "table") or re.search(
        r"\b(?:ban chay|top|hot|xep hang|don vi|thung|hop|loc|chai|vien|goi|ong|tui|cay|tan|m3|bao|phuc vu|ton)\b",
        qn,
    ):
        sections.append(_RULE_RANKING)
    if re.search(r"\b(?:ton|kho|nhap|gia von|lai|han dung|het han|lo|gia ban|tang gia|khong ban duoc|hang e)\b", qn):
        sections.append(_RULE_INVENTORY_COST)
    if caps.get("has_pharmacy_rx") and re.search(r"\b(?:ke don|hoat chat|lo|han dung|het han|thuoc)\b", qn):
        sections.append(_RULE_INDUSTRY_PHARMACY)
    if re.search(r"\b(?:size|co)\s*(?:m|l)\b", qn):
        sections.append(_RULE_INDUSTRY_CAFE)
    if caps.get("has_delivery_schedule") and re.search(r"\b(?:dot|giao)\b", qn):
        sections.append(_RULE_INDUSTRY_VLXD)

    sections.append(
        'Trả về DUY NHẤT JSON hợp lệ: {"status": "ok", "sql": "SELECT ..."} '
        'hoặc {"status": "unanswerable", "reason": "..."}. Chỉ 1 câu SQL `SELECT` hoặc `WITH ... SELECT`.'
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

    # 4b. Entity-ranking 'string' queries ('khách hàng nào nợ nhiều nhất', 'món nào...') missing GROUP BY
    if (
        analysis.expected_type == "string"
        and "order by" in sql_low
        and "group by" not in sql_low
        and re.search(r"\b(?:khach hang nao|ai |san pham nao|mon nao|thuoc nao|nha cung cap nao|nhom nao|kenh nao)\b", qn)
        and re.search(r"\b(?:tong|doanh thu|no|nhieu nhat|cao nhat|lon nhat|thap nhat|it nhat|ban chay)\b", qn)
        and not re.search(r"\b(?:don hang nao|hoa don nao|ma don nao|phieu nao)\b", qn)
    ):
        return (
            False,
            "LỖI THIẾU GROUP BY: Một đối tượng (khách hàng/sản phẩm/kênh) có thể xuất hiện ở NHIỀU đơn hàng! Tìm tổng cao nhất/nhiều nhất BẮT BUỘC phải `GROUP BY` theo đối tượng và dùng `SUM(...)` (hoặc `COUNT(...)`), KHÔNG `ORDER BY` trên 1 dòng đơn lẻ!",
            True,
        )

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

    return True, "", False


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
        if len(cols) == 1:
            values = [r[0] for r in rows]
        elif len(rows) == 1 and len(cols) >= 2:
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

    def get_knowledge(
        self,
        business_dir: str,
        cache_dir: Optional[str] = None,
        force_rebuild: bool = False,
    ) -> WorkspaceKnowledge:
        key = str(business_dir)
        if not force_rebuild and key in self._knowledge_cache:
            return self._knowledge_cache[key]
        ws = load_business_workspace(business_dir, cache_dir=cache_dir, force_rebuild=force_rebuild)
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
    ) -> Tuple[str, str]:
        system_prompt = _select_rulebook_prompt(question, as_of_date, knowledge, analysis)

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
            type_guide += " (SQL trả 1 cột nhiều dòng theo đúng thứ tự, HOẶC 1 dòng nhiều cột nếu hỏi 2-3 số)"
        elif analysis.expected_type == "boolean":
            type_guide += " (SQL trả 1 hoặc 0)"

        effective_temp_summary = temporal_summary
        if not analysis.temporal_windows and analysis.bounded_period is None:
            effective_temp_summary = (
                f"{temporal_summary}\n"
                f"- Câu hỏi KHÔNG giới hạn ngày cụ thể -> tính trên TOÀN BỘ LỊCH SỬ đến hết `{as_of_date}`, TUYỆT ĐỐI KHÔNG tự lọc `ngay = '{as_of_date}'`."
            )

        norm_clean = normalize_vn_question(question)
        q_block = question
        if norm_clean and norm_clean != norm_vn(question):
            q_block = f"{question}\n- Ý định đã chuẩn hóa: {norm_clean}"

        user_prompt = (
            f"### CÂU HỎI\n{q_block}\n\n"
            f"### {type_guide}\n\n"
            f"### MỐC THỜI GIAN ĐÃ PHÂN GIẢI\n{effective_temp_summary}\n\n"
            f"### GIÁ TRỊ KHỚP TRONG CSDL\n{ent_text}\n\n"
            f"### README SHOP\n{readme_text}\n\n"
            f"### LƯỢC ĐỒ SQLITE\n{knowledge.schema_prompt}\n"
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
    ) -> str:
        schema_block = knowledge.schema_prompt if include_full_schema else knowledge.semantic_summary
        temp_block = f"Mốc thời gian:\n{temporal_summary}\n\n" if temporal_summary else ""
        tables = list(knowledge.workspace.tables.values())
        bad_low = (bad_sql or "").lower()
        referenced_tables = [
            t for t in tables if re.search(rf"\b{re.escape(t.table_name.lower())}\b", bad_low)
        ]

        def _suggest_join_sql(target_tbl_name: str) -> str:
            tgt = next((t for t in tables if t.table_name.lower() == target_tbl_name.lower()), None)
            if tgt is None:
                return ""
            tgt_cols = [getattr(c, "sql_name", str(c)) for c in tgt.columns]
            tgt_set = set(tgt_cols)
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
                suggestions.append(f"JOIN {tgt.table_name} ON {src.table_name}.{key} = {tgt.table_name}.{key}")
            if not suggestions:
                return ""
            return "Gợi ý JOIN tự động: `" + suggestions[0] + "`\n"

        repair_hints = []
        m_missing_tbl = re.search(r"no such table:\s*([a-zA-Z0-9_.]+)", reason or "", re.IGNORECASE)
        if m_missing_tbl:
            bad_tbl = m_missing_tbl.group(1)
            valid_tbls = [t.table_name for t in tables]
            tbl_cols_lines = [
                f"- `{t.table_name}` ({', '.join(getattr(c, 'sql_name', str(c)) for c in t.columns)})"
                for t in tables
            ]
            repair_hints.append(
                f"Cảnh báo bảng sai: Bảng `{bad_tbl}` KHÔNG TỒN TẠI! "
                f"CHỈ ĐƯỢC DÙNG đúng tên bảng sau (viết đúng chính tả, không tự thêm/bớt `_`): {', '.join(f'`{n}`' for n in valid_tbls)}.\n"
                + "\n".join(tbl_cols_lines)
            )

        m_join_req = re.search(r"Hãy\s+[`'\"]?JOIN\s+([a-zA-Z0-9_]+)[`'\"]?", reason or "", re.IGNORECASE)
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
            if "." in missing_col:
                tbl_prefix = missing_col.split(".", 1)[0].strip()
                if any(t.table_name.lower() == tbl_prefix.lower() for t in tables):
                    auto_join = _suggest_join_sql(tbl_prefix)
                    join_hint = (
                        f"CHÚ Ý: Bảng `{tbl_prefix}` CÓ tồn tại trong CSDL nhưng CHƯA ĐƯỢC `JOIN` trong `FROM`! "
                        f"Hãy thêm `JOIN` và GIỮ NGUYÊN điều kiện lọc thay vì xóa điều kiện lọc.\n"
                        + auto_join
                    )
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
            matched_tables = [
                f"- Bảng `{t.table_name}` CHỈ CÓ các cột: {', '.join(getattr(c, 'sql_name', str(c)) for c in t.columns)}"
                for t in tables
                if t in referenced_tables or (
                    "." in missing_col and t.table_name.lower() == missing_col.split(".", 1)[0].lower()
                )
            ]
            if not matched_tables:
                matched_tables = [
                    f"- Bảng `{t.table_name}`: {', '.join(getattr(c, 'sql_name', str(c)) for c in t.columns)}"
                    for t in tables
                ]
            repair_hints.append(
                f"Cảnh báo cột sai: `{missing_col}` KHÔNG tồn tại trong cấu trúc hiện tại!\n"
                + join_hint
                + "\n".join(matched_tables)
                + "\nNếu bảng chỉ có cột số lượng và đơn giá (`so_luong*` * `gia*`), hãy tự nhân 2 cột đó thay vì gọi cột không tồn tại."
            )
        col_hint = ("\n\n".join(repair_hints) + "\n\n") if repair_hints else ""
        norm_clean = normalize_vn_question(question)
        q_disp = f"{question} (ý định chuẩn hóa: {norm_clean})" if norm_clean and norm_clean != norm_vn(question) else question
        return (
            f"Câu SQL trước bị lỗi hoặc vi phạm nghiệp vụ/trả kết quả không hợp lệ.\n"
            f"Câu hỏi gốc: {q_disp}\n"
            f"SQL lỗi:\n```sql\n{bad_sql}\n```\n"
            f"Thông báo: {reason}\n\n"
            f"{col_hint}"
            f"{temp_block}"
            f"Tham khảo lược đồ & quy ước dưới đây để sửa SQL:\n"
            f"{schema_block}\n\n"
            'Trả về JSON duy nhất: {"status": "ok", "sql": "SELECT ..."} hoặc {"status": "unanswerable", "reason": "..."}.'
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

    def _finalize_prediction(
        self,
        qid: str,
        candidate: Dict[str, Any],
        sql_res: Optional[SQLExecutionResult],
        attempts: int,
        confidence: float,
    ) -> AgentResult:
        pred = dict(candidate)
        pred["id"] = qid
        ptype = pred.get("type")

        if ptype == "unanswerable":
            reason = pred.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                pred["reason"] = "Dữ liệu không đủ thông tin để kết luận."
            if not is_valid_submission_record(pred):
                return AgentResult(qid, {"id": qid, "type": "abstain"}, 0.0, sql_res.sql if sql_res else "", attempts, "Invalid unanswerable format")
            return AgentResult(qid, pred, confidence, sql_res.sql if sql_res else "", attempts)

        if ptype == "abstain" or confidence < self.config.abstain_threshold:
            return AgentResult(
                question_id=qid,
                prediction={"id": qid, "type": "abstain"},
                confidence=confidence,
                sql=sql_res.sql if sql_res else "",
                sql_attempts=attempts,
                notes=[f"Abstained (confidence={confidence:.2f} < {self.config.abstain_threshold:.2f})"],
            )

        if not is_valid_submission_record(pred):
            return AgentResult(
                question_id=qid,
                prediction={"id": qid, "type": "abstain"},
                confidence=0.0,
                sql=sql_res.sql if sql_res else "",
                sql_attempts=attempts,
                error="Prediction failed strict DataMate schema check; abstained.",
            )

        return AgentResult(
            question_id=qid,
            prediction=pred,
            confidence=confidence,
            sql=sql_res.sql if sql_res else "",
            sql_attempts=attempts,
        )

    def answer_question(
        self,
        question_record: Dict[str, Any],
        knowledge: WorkspaceKnowledge,
    ) -> AgentResult:
        qid = str(question_record.get("id") or question_record.get("question_id") or "")
        question = str(question_record.get("question", ""))
        as_of_date = str(question_record.get("as_of_date", ""))

        analysis = classify_expected_type(question)
        windows, temp_summary, bounded, prior_start = extract_temporal_context(
            question, as_of_date, self.calendar
        )
        analysis.temporal_windows = windows
        analysis.temporal_summary = temp_summary
        analysis.bounded_period = bounded
        analysis.prior_needed_start = prior_start

        if self.config.enable_preflight_unanswerable:
            unans_reason = check_preflight_unanswerable(question, as_of_date, knowledge, analysis)
            if unans_reason:
                return self._finalize_prediction(
                    qid,
                    {"type": "unanswerable", "reason": unans_reason},
                    sql_res=None,
                    attempts=0,
                    confidence=0.92,
                )

        entities = ground_query_entities(question, knowledge, max_matches=12)
        sys_p, usr_p = self._build_sql_prompt(
            question=question,
            as_of_date=as_of_date,
            knowledge=knowledge,
            analysis=analysis,
            temporal_summary=temp_summary,
            entity_matches=entities,
        )

        last_sql_res: Optional[SQLExecutionResult] = None
        last_sql_text = ""
        attempts = 0
        prompt_to_send = usr_p

        for attempt in range(self.config.max_sql_retries):
            attempts = attempt + 1
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

            obj = extract_json_object(raw_reply)
            if obj and obj.get("status") == "unanswerable":
                return self._finalize_prediction(
                    qid,
                    {"type": "unanswerable", "reason": str(obj.get("reason") or "Dữ liệu không đủ để trả lời.")},
                    sql_res=last_sql_res,
                    attempts=attempts,
                    confidence=0.75,
                )

            candidate_sql = str(obj["sql"]) if (obj and isinstance(obj.get("sql"), str)) else raw_reply
            res = execute_sql_safe(
                knowledge.workspace.open_connection,
                candidate_sql,
                valid_tables=knowledge.valid_tables,
                max_rows=self.config.max_rows,
                timeout_seconds=self.config.sql_timeout_seconds,
            )
            last_sql_res = res
            last_sql_text = res.sql or candidate_sql

            if not res.ok:
                if attempt + 1 < self.config.max_sql_retries:
                    prompt_to_send = self._build_repair_prompt(
                        question,
                        last_sql_text,
                        res.error,
                        knowledge,
                        temporal_summary=temp_summary,
                        include_full_schema=True,
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
                last_sql_text, res, question, knowledge, analysis, entity_matches=entities
            )
            if not sem_ok:
                if attempt + 1 < self.config.max_sql_retries:
                    prompt_to_send = self._build_repair_prompt(
                        question,
                        last_sql_text,
                        sem_msg,
                        knowledge,
                        temporal_summary=temp_summary,
                        include_full_schema=False,
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
                    prompt_to_send = self._build_repair_prompt(
                        question,
                        last_sql_text,
                        "SQL chạy không lỗi nhưng trả về 0 dòng hoặc NULL. Kiểm tra lại filter ngày, tên status thực tế hoặc dùng NORM_VN(...) để khớp chuỗi tiếng Việt.",
                        knowledge,
                        temporal_summary=temp_summary,
                        include_full_schema=True,
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

            formatted = format_sql_result(res, analysis, question)
            if formatted is not None:
                conf = max(0.55, 0.90 - 0.12 * attempt)
                return self._finalize_prediction(qid, formatted, res, attempts, conf)

            if attempt + 1 < self.config.max_sql_retries:
                prompt_to_send = self._build_repair_prompt(
                    question,
                    last_sql_text,
                    f"Kết quả trả {res.row_count} dòng x {len(res.columns)} cột không khớp dạng `{analysis.expected_type}` cần trả.",
                    knowledge,
                    temporal_summary=temp_summary,
                    include_full_schema=True,
                )
                continue

            # Exhausted SQL retries -> optional compact LLM formatter fallback
            if self.config.enable_llm_formatter_fallback and res.row_count > 0:
                fallback = self._fallback_llm_format(question, analysis, res)
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
