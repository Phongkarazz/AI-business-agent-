"""Domain-agnostic schema profiling, capability detection, and Vietnamese entity grounding."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from datamate.loader import BusinessWorkspace, TableProfile
from datamate.sql_executor import norm_vn
from datamate.temporal import normalize_nfc

# Columns representing demographic/static/future attributes rather than transaction dates
_NON_TX_DATE_RE = re.compile(
    r"(?:^|_)(?:sinh|sinh_nhat|ngay_sinh|han_su_dung|han_dung|het_han|ngay_het_han|han_tra|han_no|han_thanh_toan|hsd|khai_truong|nhan_viec|thoi_viec|tao_luc|ngay_tao|thoi_gian_tao|ngay_cap_nhat)(?:$|_)",
    re.IGNORECASE,
)

# Master/static metadata tables whose date range is setup/lot-expiry time, not transactional history
_MASTER_TABLE_RE = re.compile(
    r"(?:san_?pham|hang_?hoa|khach_?hang|nhan_?vien|chi_?nhanh|nha_?cung_?cap|thuoc|quy_?doi|don_?vi|danh_?muc|bang_?gia|lo_?hang)",
    re.IGNORECASE,
)

_CATEGORICAL_COL_RE = re.compile(
    r"(?:trang_?thai|status|tinh_?trang|ket_?qua|xu_?ly|ghi_?chu_?tt|kenh(?:_?ban)?|ban_?qua|nguon_?don|channel|"
    r"phuong_?thuc(?:_?tt|_?thanh_?toan)?|hinh_?thuc(?:_?tt|_?thanh_?toan)?|pttt|cach_?hoan|cach_?tt|"
    r"nhom|group|loai|danh_?muc|don_?vi|dvt|ban_?theo_?don|thuoc_?ke_?don|ke_?don|kieu|chuc_?vu|nguyen_?nhan|ly_?do|khu_?vuc|hang$)",
    re.IGNORECASE,
)

_SKIP_CAT_COL_RE = re.compile(
    r"(?:^|_)(?:ma_?so_?thue|mst|dien_?thoai|sdt|phone|so_?dien_?thoai|email|e_mail|cccd|cmnd|ma_?kh|ma_?hang|ma_?sku|ma_?vach|barcode|nguoi_?tao|picture|photo|image|img|avatar|thumbnail|blob|binary)(?:$|_)",
    re.IGNORECASE,
)


def _safe_preview_val(v: Any, max_len: int = 64) -> Optional[str]:
    """Filter out binary/JPEG BLOB payloads and clip overly long cell text for prompt safety."""
    if v is None or isinstance(v, (bytes, bytearray, memoryview)):
        return None
    s = normalize_nfc(str(v)).strip()
    if not s or s == "<binary>":
        return None
    if s.startswith(("b'\\x", 'b"\\x', "\\xff\\xd8", "\\x89PNG")):
        return None
    if len(s) > 180 and ("\\x" in s[:80] or " " not in s[:100]):
        return None
    return (s[: max_len - 1] + "…") if len(s) > max_len else s

_ORDER_STATUS_COL_RE = re.compile(
    r"(?:^|_)(?:status|trang_?thai(?:_?don(?:_?hang)?|_?xu_?ly)?|ket_?qua|tinh_?trang(?:_?don)?|ghi_?chu_?tt|xu_?ly)(?:$|_)",
    re.IGNORECASE,
)

_ORDER_ID_NAME_RE = re.compile(
    r"(?:^|_)(?:ma_?(?:hoa_?don|don(?:_?hang)?|phieu|bill|chung_?tu|gd)|so_?(?:hoa_?don|ct|bill|phieu)|order_?id)(?:$|_)",
    re.IGNORECASE,
)

_ENTITY_COL_RE = re.compile(
    r"(?:ten|name|hang|mon|san_?pham|product|khach|customer|hoat_?chat|thanh_?phan|nhom|danh_?muc|"
    r"loai|nha_?cung_?cap|nhan_?vien|ncc|sku|ma_hang|ma_khach|nguyen_?nhan|doi_?tac|ben_?mua|"
    r"(?:^|_)(?:sp|hoa|m_?hoa|mon_?cam|phong|ma_?do|dich_?vu|mua_?o|nguon_?thu|khoan_?chi|vua|nguoi_?(?:dat|mua|nhan|ban|giao|chi)|ten_?goi|biet_?danh|lop|mon|tho|tai_?xe)(?:$|_))",
    re.IGNORECASE,
)

_IGNORE_VALUE_TOKENS = frozenset(
    {"", "none", "null", "nan", "khach le", "vang lai", "khong", "co", "binh thuong"}
)


@dataclass
class EntityEntry:
    table: str
    column: str
    raw_value: str
    norm_value: str
    tokens: Tuple[str, ...]


@dataclass
class WorkspaceKnowledge:
    workspace: BusinessWorkspace
    schema_prompt: str
    table_date_ranges: Dict[str, Tuple[str, str]]
    data_min_date: Optional[str]
    data_max_date: Optional[str]
    capabilities: Dict[str, bool]
    categorical_values: Dict[str, List[Tuple[str, int]]]
    entity_entries: List[EntityEntry] = field(default_factory=list)
    valid_tables: List[str] = field(default_factory=list)
    order_status_targets: List[Dict[str, Any]] = field(default_factory=list)
    semantic_summary: str = ""
    table_grains: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    datetime_columns: Set[str] = field(default_factory=set)
    join_graph: List[str] = field(default_factory=list)
    dictionary_summary: str = ""
    profiler_alerts: List[str] = field(default_factory=list)


def _active_columns(tp: TableProfile) -> List[Any]:
    """Return columns that actually contain at least one non-null value."""
    if tp.row_count <= 0:
        return []
    return [cp for cp in tp.columns if cp.distinct_count > 0 and cp.null_count < tp.row_count]


def _detect_capabilities(ws: BusinessWorkspace) -> Dict[str, bool]:
    """Infer shop schema capabilities strictly from populated columns and non-empty tables."""
    active_col_tokens: List[str] = []
    customer_table_cols: List[str] = []
    has_nonempty_cust_values = False

    for tname, tp in ws.tables.items():
        if tp.row_count <= 0:
            continue
        is_cust_tbl = bool(
            re.search(
                r"khach|customer|hoa_?don|don_?hang|ban_?hang|so_?chi_?tiet|sobanhang|"
                r"lich_?thue|tra_?do|danh_?ba|socamdo|thelieutrinh|lichhen|dondat|sothu|sothutien|ds_?lop",
                tname,
                re.I,
            )
        )
        is_named_person_tbl = bool(
            re.search(r"danh_?ba|khach|lich_?thue|socamdo|thelieutrinh|lichhen|sothutien|ds_?lop", tname, re.I)
        )
        for cp in _active_columns(tp):
            active_col_tokens.append(f"{tname}.{cp.sql_name}".lower())
            if is_cust_tbl:
                customer_table_cols.append(f"{tname}.{cp.sql_name}".lower())
            is_cust_col = bool(
                re.search(
                    r"^(?:khach|khach_?thue)$|(?:^|_)(?:ten_?kh(?:ach(?:_?hang)?)?|tenkh|khach_?hang|khach_?thue|"
                    r"ma_?kh(?:ach(?:_?hang)?)?|ma_kh_mua|customer_?id|customer_?name|customer|client_?name|"
                    r"ben_?mua|doi_?tac|so_?kh|nguoi_?(?:mua|nhan|dat)|ten_?hs|hoc_?sinh)(?:$|_)",
                    cp.sql_name,
                    re.I,
                )
                or (is_named_person_tbl and cp.sql_name.lower() in {"ten", "ho_ten", "ho_va_ten"})
            )
            if is_cust_col:
                non_anon = [
                    str(v) for v, _ in cp.top_values
                    if v is not None and norm_vn(v) not in {"", "khach le", "vang lai", "khach vang lai", "null", "none"}
                ]
                if non_anon or cp.distinct_count >= 2:
                    has_nonempty_cust_values = True

    active_combined = " ".join(active_col_tokens)
    cust_combined = " ".join(customer_table_cols)
    readme_low = norm_vn(ws.readme_text)

    def _has_col(pattern: str, text: str = active_combined) -> bool:
        return bool(re.search(pattern, text, re.IGNORECASE))

    # Import tables & price columns
    has_import = _has_col(
        r"(?:^|[.\s_])(?:nhap_?hang|phieu_?nhap|chi_?tiet_?nhap|don_?nhap|so_?nhap|sl_?nhap|so_luong_?nhap|gia_?nhap|nha_?cung_?cap|ncc)(?:$|[.\s_])"
    ) or any(re.search(r"nhap", t, re.I) and tp.row_count > 0 for t, tp in ws.tables.items())

    import_price_ok = False
    for tname, tp in ws.tables.items():
        if tp.row_count > 0 and re.search(r"nhap|import", tname, re.I):
            for c in _active_columns(tp):
                if re.search(r"(?:^|_)(?:gia_?nhap|don_?gia(?:_?nhap)?|dg_?nhap|can_?tra(?:_?ncc)?|thanh_?tien|tong_?tien|t_?tien|tong_?gia_?tri|gia)(?:$|_)", c.sql_name, re.I):
                    import_price_ok = True
                    break

    # Inventory can live in stock snapshot tables OR be tracked via import lots + order lot consumption
    has_stock_table = _has_col(
        r"(?:^|[.\s_])(?:ton_?kho|ton_?cuoi(?:_?ky)?|ton_?thuc|the_?kho|sl_?ton|so_luong_?ton|bao_?cao_?ton|baocaoton)(?:$|[.\s_])"
    ) or any(
        tp.row_count > 0
        and re.search(
            r"^(?:nv_?xuatnhapton|dm_?solo|ct_?nhapkho|kho_?do|nhap_?vuon|nhap_?hoa|nhap_?nguyen_?lieu|xuat_?banh_?theo_?lo|ton_?cuoi_?ky)$",
            t,
            re.I,
        )
        for t, tp in ws.tables.items()
    )
    has_lot_allocation = has_import and any(
        tp.row_count > 0 and re.search(r"don_?hang_?lo|chi_?tiet_?don_?lo|ban_?theo_?lo|ct_?banhang_?lo|nv_?xuatnhapton|dm_?solo", t, re.I)
        for t, tp in ws.tables.items()
    )
    has_inventory = has_stock_table or has_lot_allocation or bool(
        re.search(r"(?:^|\s)(?:the_?kho|baocaoton|sotay_?tonkho|ton_?thuc)(?:\s|$)", readme_low)
    )

    has_lot_cost_tables = any(
        tp.row_count > 0 and re.search(r"(?:nv_?xuatnhapton|ct_?nhapkho|dm_?solo|lo_?hang|chi_?tiet_?don_?lo)", t, re.I)
        for t, tp in ws.tables.items()
    )
    has_cost = _has_col(r"(?:^|[.\s_])(?:gia_?von|gia_?von_?luc_?ban|gia_?von_?hien_?tai|tien_?von)(?:$|[.\s_])") or (
        has_lot_cost_tables and _has_col(r"(?:^|[.\s_])(?:gia_?nhap|don_?gia_?nhap|dg_?nhap|tien_?von)(?:$|[.\s_])")
    )

    # Customer group requires >=2 non-empty values on a customer/order column (prevents 'nhom_hang' & single-value 'loai_hinh_khach' FPs)
    has_cust_group = False
    for tname, tp in ws.tables.items():
        if tp.row_count <= 0 or not re.search(r"khach|customer|hoa_?don|don_?hang|ban_?hang", tname, re.I):
            continue
        is_kh_tbl = bool(re.search(r"khach|customer", tname, re.I))
        for cp in _active_columns(tp):
            pat = r"(?:^|_)(?:nhom_?kh(?:ach_?hang)?|loai_?khach|hang_?khach|loai_?hinh_?kh(?:ach)?|phan_?loai_?kh)(?:$|_)"
            if is_kh_tbl:
                pat = r"(?:^(?:nhom|hang|phan_loai)$|(?:^|_)(?:nhom_?kh(?:ach_?hang)?|loai_?khach|hang_?khach|loai_?hinh_?kh(?:ach)?|phan_?loai_?kh)(?:$|_))"
            if re.search(pat, cp.sql_name, re.I) and cp.distinct_count >= 2:
                has_cust_group = True
                break

    has_gender = _has_col(r"(?:^|[.\s])(?:gioi_?tinh|gender|sex|nam_?nu|namnu|phai)(?:$|\s)|(?:^|[.\s_])(?:gioi_?tinh|gender|sex|nam_?nu)(?:$|[.\s_])")
    has_address = _has_col(
        r"(?:^|[.\s_])(?:dia_?chi|addr|address|duong|phuong_?xa|quan_?huyen|tinh_?thanh)(?:$|[.\s_])",
        cust_combined,
    )
    has_debt = _has_col(
        r"(?:^|[.\s_])(?:cong_?no|phai_?thu|con_?no|da_?tra|da_?thu|khach_?da_?tra|khach_?tra|chua_?tra|con_?lai|phieu_?thu|so_?quy|tien_?thu|so_?tien_?thu|no_?cu|tien_?coc|tra_?lien)(?:$|[.\s_])"
    ) or any(
        tp.row_count > 0
        and re.search(r"^(?:so_?quy|thanh_?toan|phieu_?thu|cong_?no|sono|thu_?no|socamdo|sothuchi|sothutien|unggiup|saokethanhtoan)", t, re.I)
        for t, tp in ws.tables.items()
    )
    has_unit_conv = _has_col(r"(?:^|[.\s_])(?:quy_?doi|ti_?le_?quy_?doi|he_?so_?qd|he_?so|dv_?lon|don_?vi_?quy_?doi|danhsachdonvitinh)(?:$|[.\s_])")
    has_expiry = _has_col(r"(?:^|[.\s_])(?:han_?su_?dung|han_?dung|het_?han|ngay_?het_?han|hsd)(?:$|[.\s_])")
    has_channel = _has_col(r"(?:^|[.\s_])(?:kenh|kenh_?ban|channel|ban_?qua|nguon_?don|noi_?ban)(?:$|[.\s_])")
    has_payment = _has_col(
        r"(?:^|[.\s_])(?:phuong_?thuc(?:_?tt|_?thanh_?toan)?|hinh_?thuc(?:_?tt|_?thanh_?toan)?|pttt|cach_?tt)(?:$|[.\s_])"
    )
    has_return_reason = _has_col(r"(?:^|[.\s_])(?:nguyen_?nhan|ly_?do)(?:$|[.\s_])")
    has_staff = _has_col(
        r"(?:^|[.\s_])(?:nhan_?vien|nhan_?su|ma_?nv|ma_?nv_?ban|ten_?nv|ho_?ten_?nv|nguoi_?ban|nguoi_?giao_?hang|nguoi_?chi|tai_?xe|tho|chuc_?vu|chuc_?danh|"
        r"thu_?ngan|employee(?:s|_?id|_?name)?|emp_?no|staff|salesperson|sales_?rep|spid|job_?title|cashier|worker)(?:$|[.\s_])"
    ) or any(
        tp.row_count > 0 and re.search(r"^(?:nhan_?vien|nhan_?su|danh_?sach_?nv|danhsachtho|dm_?nhansu|employees?|staff|people|salaries|titles|dept_?emp)$", t, re.I)
        for t, tp in ws.tables.items()
    )
    has_attendance = _has_col(
        r"(?:^|[.\s_])(?:cham_?cong|nghi_?phep|ngay_?phep|lich_?ca|diem_?danh|vao_?ra|gio_?ot|overtime|tang_?ca|attendance|absent|leave_?days)(?:$|[.\s_])"
    ) or any(
        tp.row_count > 0 and re.search(r"^(?:cham_?cong|nghi_?phep|lich_?ca|dd|diem_?danh)$", t, re.I)
        for t, tp in ws.tables.items()
    )
    has_pharmacy_rx = _has_col(
        r"(?:^|[.\s_])(?:ke_?don|ban_?theo_?don|thuoc_?ke_?don|hoat_?chat|thanh_?phan_?chinh|danhsachthuoc|banhang_?thuoc|thong_?tin_?thuoc)(?:$|[.\s_])"
    )
    has_expenses = _has_col(r"(?:^|[.\s_])(?:chi_?phi|sotay_?chiphi|ngay_?chi|khoan_?chi)(?:$|[.\s_])") or any(
        tp.row_count > 0 and re.search(r"(?:chi_?phi|so_?chi|sothuchi)", t, re.I) for t, tp in ws.tables.items()
    )
    has_price_hist = _has_col(r"(?:^|[.\s_])(?:lich_?su_?gia|bang_?gia|banggia|gia_?moi|ngay_?ap_dung)(?:$|[.\s_])")
    has_delivery = _has_col(
        r"(?:^|[.\s_])(?:so_?giao_?hang|sogiaohang|bang_?ke_?phieu_?giao_?hang|luot_?giao|dot_?giao|lan_?giao|ngay_?cho|so_?xe|bien_?so_?xe)(?:$|[.\s_])"
    ) or any(
        tp.row_count > 0 and re.search(r"^(?:nhattrinhxe|hanhtrinhvandon|van_?don)$", t, re.I)
        for t, tp in ws.tables.items()
    )

    return {
        "has_import": has_import,
        "has_import_price": import_price_ok,
        "has_inventory": has_inventory,
        "has_cost_price": has_cost,
        "has_customers": has_nonempty_cust_values,
        "has_customer_group": has_cust_group,
        "has_customer_gender": has_gender,
        "has_customer_address": has_address,
        "has_debt_or_payments": has_debt,
        "has_unit_conversion": has_unit_conv,
        "has_expiry": has_expiry,
        "has_channel": has_channel,
        "has_payment_method": has_payment,
        "has_return_reason": has_return_reason,
        "has_staff": has_staff,
        "has_attendance": has_attendance,
        "has_pharmacy_rx": has_pharmacy_rx,
        "has_expenses": has_expenses,
        "has_price_history": has_price_hist,
        "has_delivery_schedule": has_delivery,
    }


def _collect_table_date_ranges(
    conn: sqlite3.Connection, tables: Dict[str, TableProfile]
) -> Tuple[Dict[str, Tuple[str, str]], Optional[str], Optional[str]]:
    per_table: Dict[str, Tuple[str, str]] = {}
    tx_mins: List[str] = []
    tx_maxs: List[str] = []

    for tname, tp in tables.items():
        is_master = bool(_MASTER_TABLE_RE.search(tname))
        for cp in tp.columns:
            if cp.inferred_type not in ("date", "datetime"):
                continue
            if _NON_TX_DATE_RE.search(cp.sql_name):
                continue
            row = conn.execute(
                f'SELECT MIN(substr("{cp.sql_name}", 1, 10)), MAX(substr("{cp.sql_name}", 1, 10)) '
                f'FROM "{tname}" WHERE "{cp.sql_name}" IS NOT NULL AND length("{cp.sql_name}") >= 10'
            ).fetchone()
            if not row or not row[0] or not row[1]:
                continue
            mn, mx = str(row[0])[:10], str(row[1])[:10]
            if not (re.match(r"^\d{4}-\d{2}-\d{2}$", mn) and re.match(r"^\d{4}-\d{2}-\d{2}$", mx)):
                continue
            per_table[f"{tname}.{cp.sql_name}"] = (mn, mx)
            if not is_master:
                tx_mins.append(mn)
                tx_maxs.append(mx)

    if not tx_mins and per_table:
        tx_mins = [v[0] for v in per_table.values()]
        tx_maxs = [v[1] for v in per_table.values()]

    data_min = min(tx_mins) if tx_mins else None
    data_max = max(tx_maxs) if tx_maxs else None
    return per_table, data_min, data_max


def _index_entities_and_categories(
    conn: sqlite3.Connection, tables: Dict[str, TableProfile]
) -> Tuple[Dict[str, List[Tuple[str, int]]], List[EntityEntry]]:
    categorical: Dict[str, List[Tuple[str, int]]] = {}
    entries: List[EntityEntry] = []
    seen_entry: Set[Tuple[str, str, str]] = set()

    for tname, tp in tables.items():
        if tp.row_count <= 0:
            continue
        for cp in _active_columns(tp):
            # Categorical distribution (query exact counts for status cols; reuse top_values otherwise)
            is_status = bool(_ORDER_STATUS_COL_RE.search(cp.sql_name))
            if (
                not _SKIP_CAT_COL_RE.search(cp.sql_name)
                and 1 <= cp.distinct_count <= 25
                and (
                    is_status
                    or _CATEGORICAL_COL_RE.search(cp.sql_name)
                    or (cp.inferred_type == "text" and cp.distinct_count <= 15)
                )
            ):
                if is_status or cp.distinct_count > len(cp.top_values):
                    cat_rows = conn.execute(
                        f'SELECT "{cp.sql_name}", COUNT(*) FROM "{tname}" '
                        f'WHERE "{cp.sql_name}" IS NOT NULL GROUP BY "{cp.sql_name}" ORDER BY COUNT(*) DESC'
                    ).fetchall()
                    safe_cats = [
                        (pv, int(cnt))
                        for v, cnt in cat_rows
                        if v is not None and (pv := _safe_preview_val(v, max_len=80)) is not None
                    ]
                else:
                    safe_cats = [
                        (pv, int(cnt))
                        for v, cnt in cp.top_values
                        if v is not None and (pv := _safe_preview_val(v, max_len=80)) is not None
                    ]
                if safe_cats:
                    categorical[f"{tname}.{cp.sql_name}"] = safe_cats

            # Entity lookup values for product / customer / category / active ingredient / unit grounding
            if (
                cp.inferred_type == "text"
                and 1 <= cp.distinct_count <= 5000
                and (_ENTITY_COL_RE.search(cp.sql_name) or _CATEGORICAL_COL_RE.search(cp.sql_name))
            ):
                rows = conn.execute(
                    f'SELECT DISTINCT "{cp.sql_name}" FROM "{tname}" '
                    f'WHERE "{cp.sql_name}" IS NOT NULL'
                ).fetchall()
                for (raw_val,) in rows:
                    s_raw = _safe_preview_val(raw_val, max_len=120) or ""
                    if not s_raw:
                        continue
                    s_norm = norm_vn(s_raw)
                    if not s_norm or len(s_norm) < 2 or s_norm in _IGNORE_VALUE_TOKENS:
                        continue
                    key = (tname, cp.sql_name, s_raw)
                    if key in seen_entry:
                        continue
                    seen_entry.add(key)
                    toks = tuple(t for t in re.split(r"[^a-z0-9]+", s_norm) if t)
                    if toks:
                        entries.append(
                            EntityEntry(
                                table=tname,
                                column=cp.sql_name,
                                raw_value=s_raw,
                                norm_value=s_norm,
                                tokens=toks,
                            )
                        )
    return categorical, entries


def _classify_status_values(values: Sequence[str]) -> Tuple[List[str], List[str], List[str]]:
    """Classify order status strings into (valid_sales, cancelled, returned)."""
    valid: List[str] = []
    cancelled: List[str] = []
    returned: List[str] = []
    for raw in values:
        nv = norm_vn(raw)
        if re.search(r"huy|cancel|khong giao duoc|that bai", nv):
            cancelled.append(raw)
        elif re.search(r"tra\s*hang|tra\s*lai|doi\s*tra|hoan\s*tra|hoan\s*hang|hoan\s*don|hang\s*tra\s*ve|returned", nv):
            returned.append(raw)
        else:
            valid.append(raw)
    return valid, cancelled, returned


def _build_order_semantics(
    ws: BusinessWorkspace,
    categorical: Dict[str, List[Tuple[str, int]]],
    date_ranges: Dict[str, Tuple[str, str]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], str]:
    """Derive generic SQL grain, status filter, and metric hints directly from profiled tables."""
    targets: List[Dict[str, Any]] = []
    grains: Dict[str, Dict[str, Any]] = {}
    hint_lines: List[str] = []

    for tname, tp in ws.tables.items():
        if tp.row_count <= 0:
            continue
        active = _active_columns(tp)
        order_col: Optional[Any] = None
        date_col: Optional[str] = None
        status_col: Optional[str] = None
        rev_cols: List[str] = []
        debt_cols: List[str] = []

        for cp in active:
            if order_col is None and _ORDER_ID_NAME_RE.search(cp.sql_name):
                order_col = cp
            if date_col is None and f"{tname}.{cp.sql_name}" in date_ranges:
                date_col = cp.sql_name
            if status_col is None and _ORDER_STATUS_COL_RE.search(cp.sql_name) and not re.search(r"khach|nhap", tname, re.I):
                status_col = cp.sql_name
            if re.search(r"(?:^|_)(?:tien_?hang|thanh_?tien|tt_?dong|tong_?tien_?hang|tong_?tien|tong_?bill|tien)(?:$|_)", cp.sql_name, re.I):
                rev_cols.append(cp.sql_name)
            if re.search(r"(?:^|_)(?:da_?tra|da_?thu|chua_?tra|con_?no|con_?lai|khach_?da_?tra|khach_?tra)(?:$|_)", cp.sql_name, re.I):
                debt_cols.append(cp.sql_name)

        has_rep = bool(order_col is not None and order_col.distinct_count < tp.row_count)
        grains[tname] = {
            "row_count": tp.row_count,
            "order_id_col": order_col.sql_name if order_col else None,
            "distinct_orders": order_col.distinct_count if order_col else tp.row_count,
            "has_repeating_orders": has_rep,
            "date_col": date_col,
        }

        is_sales_tbl = bool(status_col) and not _MASTER_TABLE_RE.search(tname) and not re.search(r"nhap|khach|chi_?phi|so_?quy|thanh_?toan|giao_?hang", tname, re.I)
        if not is_sales_tbl:
            continue

        cat_vals = [v for v, _ in categorical.get(f"{tname}.{status_col}", [])]
        valid, cancelled, returned = _classify_status_values(cat_vals)
        bad_all = cancelled + returned
        valid_filter = (
            f"{status_col} NOT IN ({', '.join(repr(v) for v in bad_all)})"
            if bad_all
            else ""
        )
        targets.append(
            {
                "table": tname,
                "status_col": status_col,
                "valid_values": valid,
                "cancelled_values": cancelled,
                "returned_values": returned,
                "valid_filter": valid_filter,
                "order_id_col": order_col.sql_name if order_col else None,
                "has_repeating_orders": has_rep,
                "date_col": date_col,
                "revenue_cols": rev_cols,
                "debt_cols": debt_cols,
            }
        )

        grain_desc = (
            f"1 dòng = 1 mặt hàng trong đơn -> đếm số đơn dùng COUNT(DISTINCT {order_col.sql_name})"
            if has_rep and order_col
            else "1 dòng = 1 đơn hàng -> đếm số đơn dùng COUNT(*)"
        )
        line = f"- Bảng bán hàng `{tname}` ({grain_desc}"
        if date_col:
            line += f"; cột ngày = `{date_col}`"
        if valid_filter:
            line += (
                f"; lọc đơn thành công (CHỈ dùng khi tính doanh thu/số đơn thành công; "
                f"TUYỆT ĐỐI KHÔNG lọc khi hỏi đơn huỷ/tỷ lệ huỷ/trả hàng): `{valid_filter}` [giữ cả đang giao: {valid}]"
            )
        if cancelled:
            line += f"; đơn HUỶ = {cancelled}"
        if returned:
            line += f"; đơn TRẢ = {returned}"
        line += ")."
        hint_lines.append(line)
        if debt_cols:
            hint_lines.append(
                f"  Lưu ý: chỉ dùng các cột nợ/thu {debt_cols} khi câu hỏi hỏi công nợ/trả nợ/đã trả; TUYỆT ĐỐI KHÔNG tự lọc `= 0` khi tính doanh thu hoặc số đơn."
            )

    target_tables = {t["table"] for t in targets}
    for tname, tp in ws.tables.items():
        if tp.row_count <= 0 or tname in target_tables:
            continue
        active = _active_columns(tp)
        has_date_col = any(f"{tname}.{cp.sql_name}" in date_ranges for cp in active)
        if has_date_col:
            continue
        cols_csv = ", ".join(cp.sql_name for cp in active)
        hint_lines.append(
            f"- Bảng danh mục/tra cứu `{tname}` ({cols_csv}): dùng trực tiếp khi hỏi danh sách/thuộc tính/đơn giá mà không hỏi doanh thu hay giao dịch."
        )

    for tname, tp in ws.tables.items():
        if tp.row_count <= 0:
            continue
        sheet_cp = next((c for c in _active_columns(tp) if c.sql_name.lower() == "source_sheet"), None)
        if sheet_cp is not None and sheet_cp.distinct_count >= 2:
            samples = ", ".join(repr(v) for v, _ in sheet_cp.top_values[:4])
            hint_lines.append(
                f"- Bảng `{tname}` gộp dữ liệu từ nhiều kỳ/sheet trong cột `source_sheet` (VD: {samples}) "
                f"-> Khi câu hỏi hỏi lịch sử/diễn biến qua các kỳ hoặc từng tháng, BẮT BUỘC `SELECT source_sheet, ...` (TUYỆT ĐỐI KHÔNG `SUM` gộp mất `source_sheet` thành 1 dòng!)."
            )

    return targets, grains, "\n".join(hint_lines)


_JOIN_KEY_RE = re.compile(
    r"^(?:ma_[a-z0-9_]+|so_bn|so_hd|so_ct|so_phieu|phieu|phong|sdt|dien_?thoai|di_?dong|phone|sku|barcode|khach|ten_khach|ma_nv|ma_hs|tho|tho_chinh|ma_do|dich_vu|[a-z0-9_]+_id|[a-z0-9_]+_code)$",
    re.IGNORECASE,
)
_DICT_TABLE_RE = re.compile(
    r"(?:ghi_?tat|quy_?doi|quy_?cach|tru_?bi|ca_?lam|lich_?nghi|ds_?phong|dm_?coso)",
    re.IGNORECASE,
)


_OVERLAP_FK_COL_RE = re.compile(
    r"^(?:ma|ma_[a-z0-9_]+|so_[a-z0-9_]+|id$|customer_id|phieu|phong|khach|ten_khach|khach_hang|ho_ten|ten_goi|hay_goi|biet_danh|tho|tho_chinh|tho_phu|hen_tho|nhan_vien|dich_vu|ten_sp|ten_mon|ten_hang|ma_do|m_hoa|sdt|dien_thoai|di_dong)|(?:_id|_code|_ban|_tu|_ct)$",
    re.IGNORECASE,
)
_DIRECTORY_TABLE_RE = re.compile(
    r"^(?:danh_?ba|danh_?sach|khach_?hang|dm_|nhan_?vien|tho|banggia|bang_?gia|san_?pham|hang_?hoa)",
    re.IGNORECASE,
)


def _annotate_optional_directory_edge(
    conn: Optional[sqlite3.Connection],
    t1: str,
    c1: str,
    t2: str,
    c2: str,
) -> str:
    """Append a LEFT JOIN + COALESCE note when transaction rows exist without a directory match."""
    edge = f"{t1}.{c1} = {t2}.{c2}"
    if conn is None:
        return edge
    is_d1 = bool(_DIRECTORY_TABLE_RE.search(t1))
    is_d2 = bool(_DIRECTORY_TABLE_RE.search(t2))
    if is_d1 == is_d2:
        return edge
    t_dir, c_dir, t_tx, c_tx = (t1, c1, t2, c2) if is_d1 else (t2, c2, t1, c1)
    try:
        tx_rows = conn.execute(
            f'SELECT DISTINCT trim(CAST(v AS TEXT)) FROM ('
            f'SELECT "{c_tx}" AS v FROM "{t_tx}" WHERE "{c_tx}" IS NOT NULL LIMIT 3000'
            f') WHERE trim(CAST(v AS TEXT)) != \'\' LIMIT 600'
        ).fetchall()
        tx_vals = {str(r[0]).strip() for r in tx_rows if r and r[0] is not None and str(r[0]).strip()}
        if not tx_vals:
            return edge
        dir_rows = conn.execute(
            f'SELECT DISTINCT trim(CAST("{c_dir}" AS TEXT)) FROM "{t_dir}" '
            f'WHERE "{c_dir}" IS NOT NULL LIMIT 10000'
        ).fetchall()
        dir_vals = {str(r[0]).strip() for r in dir_rows if r and r[0] is not None and str(r[0]).strip()}
        if tx_vals - dir_vals:
            return f"{edge} (dùng LEFT JOIN {t_dir} + COALESCE vì có dòng ở {t_tx} chưa có trong {t_dir})"
    except sqlite3.Error:
        pass
    return edge


def _extract_join_graph(
    ws: BusinessWorkspace,
    conn: Optional[sqlite3.Connection] = None,
    max_edges: int = 16,
) -> List[str]:
    """Identify shared candidate foreign-key links (exact column match + cross-table value overlap)."""
    col_to_tables: Dict[str, List[str]] = {}
    cand_overlap_cols: List[Tuple[str, str]] = []
    for tname, tp in ws.tables.items():
        if tp.row_count <= 0:
            continue
        for cp in _active_columns(tp):
            cname = cp.sql_name
            if _JOIN_KEY_RE.match(cname):
                col_to_tables.setdefault(cname.lower(), []).append(tname)
            if (
                conn is not None
                and cp.inferred_type in ("text", "integer")
                and cp.distinct_count >= 2
                and _OVERLAP_FK_COL_RE.search(cname)
            ):
                cand_overlap_cols.append((tname, cname))

    edges: List[Tuple[int, str]] = []
    seen_pairs: Set[Tuple[str, str, str]] = set()
    seen_tbl_pairs: Set[Tuple[str, str]] = set()
    for key_low, tbls in col_to_tables.items():
        if len(tbls) < 2 or len(tbls) > 6:
            continue
        prio = 0 if key_low in {"so_bn", "phieu", "ma_hoa_don", "ma_don_hang", "ma_don", "ma_hang", "ma_khach", "ma_nv"} else 1
        for i in range(len(tbls)):
            for j in range(i + 1, len(tbls)):
                t1, t2 = tbls[i], tbls[j]
                pair_k = (min(t1, t2), max(t1, t2), key_low)
                if pair_k in seen_pairs:
                    continue
                seen_pairs.add(pair_k)
                seen_tbl_pairs.add((min(t1, t2), max(t1, t2)))
                edges.append((prio, _annotate_optional_directory_edge(conn, t1, key_low, t2, key_low)))

    # Value-overlap discovery for differently named foreign keys (e.g. ma_don_hang = ma_chung_tu, sothu.tho = danhsachtho.ten_goi)
    if conn is not None and len(cand_overlap_cols) >= 2:
        col_vals: Dict[Tuple[str, str], Set[str]] = {}
        for tname, cname in cand_overlap_cols[:60]:
            try:
                rows = conn.execute(
                    f'SELECT DISTINCT trim(CAST(v AS TEXT)) FROM ('
                    f'SELECT "{cname}" AS v FROM "{tname}" WHERE "{cname}" IS NOT NULL LIMIT 2500'
                    f') WHERE length(trim(CAST(v AS TEXT))) >= 1 LIMIT 150'
                ).fetchall()
            except sqlite3.Error:
                continue
            vals = {
                str(r[0]).strip()
                for r in rows
                if r and r[0] is not None
                and not re.match(r"^\d{4}-\d{2}-\d{2}", str(r[0]).strip())
                and (len(str(r[0]).strip()) >= 2 or not str(r[0]).strip().isdigit())
            }
            # Guard against plain small integer sequences ('1', '2', ...) colliding across unrelated tables
            if len(vals) >= 2 and not all(v.isdigit() and len(v) < 3 for v in vals):
                col_vals[(tname, cname)] = vals

        keys_list = list(col_vals.keys())
        for i in range(len(keys_list)):
            t1, c1 = keys_list[i]
            v1 = col_vals[(t1, c1)]
            for j in range(i + 1, len(keys_list)):
                t2, c2 = keys_list[j]
                if t1 == t2 or c1.lower() == c2.lower():
                    continue
                if (min(t1, t2), max(t1, t2)) in seen_tbl_pairs:
                    continue
                v2 = col_vals[(t2, c2)]
                ov = v1 & v2
                ci_only = False
                if len(ov) < 2:
                    v1_low = {v.lower() for v in v1 if not v.isdigit()}
                    v2_low = {v.lower() for v in v2 if not v.isdigit()}
                    ov_low = v1_low & v2_low
                    if len(ov_low) >= 2 and (len(ov_low) / max(1, min(len(v1_low), len(v2_low)))) >= 0.35:
                        ov = ov_low
                        ci_only = True
                    else:
                        continue
                if all(x.isdigit() and len(x) < 3 for x in ov) and len(ov) < 4:
                    continue
                ratio = len(ov) / max(1, min(len(v1), len(v2)))
                if ratio >= 0.2:
                    seen_tbl_pairs.add((min(t1, t2), max(t1, t2)))
                    edge_str = _annotate_optional_directory_edge(conn, t1, c1, t2, c2)
                    if ci_only and " (" not in edge_str:
                        edge_str += " (dùng NORM_VN(...) để khớp không phân biệt hoa/thường)"
                    edges.append((0, edge_str))

    edges.sort(key=lambda x: (x[0], x[1]))
    return [e for _, e in edges[:max_edges]]


def _extract_dictionary_summary(conn: sqlite3.Connection, ws: BusinessWorkspace) -> str:
    """Compactly materialize small dictionary/abbreviation/conversion tables directly into context."""
    parts: List[str] = []
    for tname, tp in ws.tables.items():
        if not (1 <= tp.row_count <= 40) or not _DICT_TABLE_RE.search(tname):
            continue
        active_cols = [c.sql_name for c in _active_columns(tp)][:8]
        if not active_cols:
            continue
        cols_sql = ", ".join(f'"{c}"' for c in active_cols)
        try:
            rows = conn.execute(f'SELECT {cols_sql} FROM "{tname}" LIMIT 15').fetchall()
        except sqlite3.Error:
            continue
        clean_rows = [
            tuple(_safe_preview_val(v, max_len=36) if isinstance(v, str) else v for v in r)
            for r in rows
        ]
        if clean_rows:
            preview = "; ".join(str(r) for r in clean_rows)
            if len(preview) > 360:
                preview = preview[:357] + "..."
            parts.append(f"- `{tname}` ({', '.join(active_cols)}): {preview}")
    return "\n".join(parts[:6])


def _extract_profiler_alerts(ws: BusinessWorkspace) -> List[str]:
    """Surface Phase-1 structural hints (compound cells, wide day matrices, sheet tariff rules)."""
    alerts: List[str] = []
    for tname, tp in ws.tables.items():
        if tp.row_count <= 0 or not tp.notes:
            continue
        for note in tp.notes:
            if note.startswith("compound_cols="):
                cols = note.split("=", 1)[1]
                alerts.append(
                    f"Bảng `{tname}` có cột bán cấu trúc `{cols}` (VD `lẻ 12k, thùng 276k` / `527k + 338000`) -> ưu tiên dùng Python Sandbox với `sum_compound_vn_nums` / tách regex."
                )
            elif note == "wide_day_matrix=true":
                alerts.append(
                    f"Bảng `{tname}` là ma trận nhiều cột ngày 1..31 -> ưu tiên Python Sandbox để duyệt từng cột ngày/đếm ký hiệu (`P`, `K`, `x`)."
                )
            elif note.startswith("notes:"):
                txt = note.split(":", 1)[1].strip()
                if re.search(r"(?:\d+[.,]\d+\s*đ/|số âm|P:|K:|hạn đóng|đầu kỳ|nghỉ)", txt, re.I):
                    alerts.append(f"Ghi chú sheet `{tname}`: {txt[:240]}")
    return alerts[:8]


def _render_table_block(
    tname: str,
    tp: TableProfile,
    date_ranges: Dict[str, Tuple[str, str]],
    categorical: Dict[str, List[Tuple[str, int]]],
    compact: bool = False,
) -> List[str]:
    """Render one table's schema lines (full or compact 1-line summary)."""
    active_cols: List[str] = []
    col_parts: List[str] = []
    empty_cols: List[str] = []
    for cp in tp.columns:
        if tp.row_count > 0 and (cp.distinct_count == 0 or cp.null_count >= tp.row_count):
            empty_cols.append(cp.sql_name)
            continue
        active_cols.append(cp.sql_name)
        if compact:
            continue
        tag = cp.inferred_type
        dr = date_ranges.get(f"{tname}.{cp.sql_name}")
        if dr:
            tag = f"{tag}[{dr[0]}..{dr[1]}]"
        cat = categorical.get(f"{tname}.{cp.sql_name}")
        if cat:
            preview_lim = 25 if _ORDER_STATUS_COL_RE.search(cp.sql_name) else 12
            vals_preview = ", ".join(repr(v) for v, _ in cat[:preview_lim])
            col_parts.append(f"{cp.sql_name} ({tag}; values: {vals_preview})")
        else:
            safe_samps = [
                pv for v in (cp.sample_values or [])[:4] if (pv := _safe_preview_val(v, max_len=64)) is not None
            ][:2]
            samp = ", ".join(repr(v) for v in safe_samps)
            col_parts.append(f"{cp.sql_name} ({tag}" + (f"; e.g. {samp}" if samp else "") + ")")

    if compact:
        cols_preview = ", ".join(active_cols[:24]) + (f" ... (+{len(active_cols) - 24})" if len(active_cols) > 24 else "")
        return [f"- Bảng `{tname}` ({tp.row_count} dòng, tóm tắt): {cols_preview}"]

    note_str = f" [notes: {', '.join(tp.notes)}]" if tp.notes else ""
    out = [f"- Bảng `{tname}` ({tp.row_count} dòng){note_str}:"]
    out.append("  Cột: " + " | ".join(col_parts))
    if empty_cols:
        out.append(f"  [Cột trống 100% không có dữ liệu: {', '.join(empty_cols)}]")
    return out


def build_workspace_knowledge(ws: BusinessWorkspace) -> WorkspaceKnowledge:
    """Build compact, cached schema summary, capability flags, date bounds, and entity index."""
    conn = ws.open_connection()
    try:
        date_ranges, data_min, data_max = _collect_table_date_ranges(conn, ws.tables)
        categorical, entity_entries = _index_entities_and_categories(conn, ws.tables)
        dict_summary = _extract_dictionary_summary(conn, ws)
        join_graph = _extract_join_graph(ws, conn=conn)
    finally:
        conn.close()

    caps = _detect_capabilities(ws)
    status_targets, table_grains, sem_summary = _build_order_semantics(ws, categorical, date_ranges)
    profiler_alerts = _extract_profiler_alerts(ws)
    datetime_cols = {
        cp.sql_name
        for tp in ws.tables.values()
        for cp in tp.columns
        if cp.inferred_type == "datetime"
    }

    lines: List[str] = []
    if data_min and data_max:
        lines.append(f"Khoảng ngày dữ liệu giao dịch của shop: {data_min} đến {data_max}")
    if sem_summary:
        lines.append("Gợi ý kỹ thuật tự động từ lược đồ:")
        lines.append(sem_summary)
    if join_graph:
        lines.append("Liên kết khoá giữa các bảng (JOIN gợi ý): " + "; ".join(join_graph[:10]))
    if profiler_alerts:
        lines.append("Cảnh báo cấu trúc đặc biệt:")
        lines.extend(f"- {a}" for a in profiler_alerts)
    if dict_summary:
        lines.append("Bảng từ điển / quy đổi nhanh:")
        lines.append(dict_summary)
    lines.append("Danh sách bảng SQLite (ngày đã chuẩn hoá YYYY-MM-DD; tiền là số nguyên VND):")

    for tname, tp in ws.tables.items():
        lines.extend(_render_table_block(tname, tp, date_ranges, categorical, compact=False))

    return WorkspaceKnowledge(
        workspace=ws,
        schema_prompt="\n".join(lines),
        table_date_ranges=date_ranges,
        data_min_date=data_min,
        data_max_date=data_max,
        capabilities=caps,
        categorical_values=categorical,
        entity_entries=entity_entries,
        valid_tables=list(ws.tables.keys()),
        order_status_targets=status_targets,
        semantic_summary=sem_summary,
        table_grains=table_grains,
        datetime_columns=datetime_cols,
        join_graph=join_graph,
        dictionary_summary=dict_summary,
        profiler_alerts=profiler_alerts,
    )


def build_focused_schema_prompt(
    question: str,
    knowledge: WorkspaceKnowledge,
    entity_matches: Sequence[Tuple[str, str, str]] = (),
    max_full_tables: int = 8,
) -> str:
    """
    Focus prompt budget on the top relevant tables (full columns) when workspace has >8 tables,
    keeping a 1-line column index for remaining tables so small/local LLMs never choke on context.
    """
    tables = knowledge.workspace.tables
    if len(tables) <= max_full_tables:
        return knowledge.schema_prompt

    q_tokens = set(re.findall(r"[a-z0-9]+", norm_vn(question)))
    matched_tbls = {t for t, _, _ in entity_matches}
    sales_tbls = {t.get("table") for t in knowledge.order_status_targets}

    scores: Dict[str, float] = {}
    for tname, tp in tables.items():
        if tp.row_count <= 0:
            scores[tname] = -10.0
            continue
        sc = 0.0
        if tname in matched_tbls:
            sc += 50.0
        t_toks = set(re.split(r"[^a-z0-9]+", tname.lower()))
        sc += 18.0 * len(t_toks & q_tokens)
        col_toks = {
            sub
            for cp in _active_columns(tp)
            for sub in re.split(r"[^a-z0-9]+", cp.sql_name.lower())
            if len(sub) >= 2
        }
        sc += 6.0 * len(col_toks & q_tokens)
        if tname in sales_tbls:
            sc += 12.0
        if _DICT_TABLE_RE.search(tname):
            sc += 8.0
        if tp.notes:
            sc += 4.0
        scores[tname] = sc

    # 1-hop join neighbor boost from top scored tables
    top_initial = {t for t, _ in sorted(scores.items(), key=lambda x: -x[1])[:4]}
    for edge in knowledge.join_graph:
        edge_clean = edge.split(" (", 1)[0]
        if " = " not in edge_clean:
            continue
        left, right = edge_clean.split(" = ", 1)
        t1, t2 = left.strip().split(".", 1)[0], right.strip().split(".", 1)[0]
        if t1 in top_initial and t2 in scores:
            scores[t2] += 18.0
        if t2 in top_initial and t1 in scores:
            scores[t1] += 18.0

    ranked = sorted(tables.keys(), key=lambda t: (-scores.get(t, 0.0), t))
    full_set = set(ranked[:max_full_tables])

    lines: List[str] = []
    if knowledge.data_min_date and knowledge.data_max_date:
        lines.append(f"Khoảng ngày dữ liệu giao dịch của shop: {knowledge.data_min_date} đến {knowledge.data_max_date}")
    if knowledge.semantic_summary:
        lines.append("Gợi ý kỹ thuật tự động từ lược đồ:")
        lines.append(knowledge.semantic_summary)
    if knowledge.join_graph:
        lines.append("Liên kết khoá giữa các bảng (JOIN gợi ý): " + "; ".join(knowledge.join_graph[:10]))
    if knowledge.profiler_alerts:
        lines.append("Cảnh báo cấu trúc đặc biệt:")
        lines.extend(f"- {a}" for a in knowledge.profiler_alerts)
    if knowledge.dictionary_summary:
        lines.append("Bảng từ điển / quy đổi nhanh:")
        lines.append(knowledge.dictionary_summary)
    lines.append(f"Danh sách bảng SQLite (chi tiết {len(full_set)} bảng trọng tâm + tóm tắt {len(tables) - len(full_set)} bảng phụ):")

    for tname in ranked:
        tp = tables[tname]
        lines.extend(
            _render_table_block(
                tname,
                tp,
                knowledge.table_date_ranges,
                knowledge.categorical_values,
                compact=(tname not in full_set),
            )
        )
    return "\n".join(lines)


_PROBE_KEY_COL_RE = re.compile(r"^(?:ma_[a-z0-9_]+|so_bn|so_hd|so_ct|phieu|phong|id)$", re.IGNORECASE)


def run_deterministic_probes(
    question: str,
    knowledge: WorkspaceKnowledge,
    entity_matches: Sequence[Tuple[str, str, str]] = (),
    max_rows_per_probe: int = 4,
) -> str:
    """
    Fast read-only micro-probe (<25ms) fetching real matching rows + 1-hop FK sibling rows
    so the agent never guesses column values or misses cross-table links (e.g. socamdo -> sothuchi).
    """
    ws = knowledge.workspace
    if not ws.db_path or not ws.db_path.exists():
        return ""

    # Extract explicit dd/mm/yyyy date hints for prioritizing relevant sample rows
    date_hints: List[str] = []
    for d_s, m_s, y_s in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", question or ""):
        di, mi, yi = int(d_s), int(m_s), int(y_s)
        if 1 <= mi <= 12 and 1 <= di <= 31:
            date_hints.append(f"{yi:04d}-{mi:02d}-{di:02d}")

    probes: List[Tuple[str, str, str]] = []
    seen_targets: Set[Tuple[str, str, str]] = set()
    for tbl, col, val in entity_matches:
        if _ORDER_STATUS_COL_RE.search(col):
            continue
        k = (tbl, col, val)
        if k in seen_targets:
            continue
        seen_targets.add(k)
        probes.append(k)
        if len(probes) >= 3:
            break

    sections: List[str] = []
    conn = ws.open_connection()
    start_t = time.monotonic()
    conn.set_progress_handler(lambda: 1 if time.monotonic() - start_t > 0.35 else 0, 20000)
    try:
        for tbl, col, val in probes:
            tp = ws.tables.get(tbl)
            if not tp or tp.row_count <= 0:
                continue
            active_cols = [c.sql_name for c in _active_columns(tp)]
            if len(active_cols) > 12:
                # Keep primary key/date/matched col compactly
                keep = [c for c in active_cols[:6]]
                for c in active_cols:
                    if c == col or _PROBE_KEY_COL_RE.match(c) or f"{tbl}.{c}" in knowledge.table_date_ranges:
                        if c not in keep:
                            keep.append(c)
                show_cols = keep[:12]
            else:
                show_cols = active_cols
            if not show_cols:
                continue
            cols_sql = ", ".join(f'"{c}"' for c in show_cols)
            date_col = next((c for c in active_cols if f"{tbl}.{c}" in knowledge.table_date_ranges), None)
            rows: List[Tuple[Any, ...]] = []
            if date_col and date_hints:
                d_iso = date_hints[0]
                rows = conn.execute(
                    f'SELECT {cols_sql} FROM "{tbl}" WHERE "{col}" = ? AND substr("{date_col}", 1, 10) = ? LIMIT ?',
                    (val, d_iso, max_rows_per_probe),
                ).fetchall()
            if not rows:
                rows = conn.execute(
                    f'SELECT {cols_sql} FROM "{tbl}" WHERE "{col}" = ? LIMIT ?',
                    (val, max_rows_per_probe),
                ).fetchall()
            if not rows:
                continue

            clean_rows = [
                tuple(_safe_preview_val(c, max_len=44) if isinstance(c, str) else c for c in r)
                for r in rows
            ]
            sections.append(f"- `{tbl}` WHERE `{col} = {val!r}` (cột {show_cols}): {clean_rows}")

            # 1-hop sibling lookup via ID/key columns found in probed rows
            sib_checked = 0
            for c_idx, cname in enumerate(show_cols):
                if not _PROBE_KEY_COL_RE.match(cname) or cname.lower() == col.lower():
                    continue
                key_vals = list(dict.fromkeys(r[c_idx] for r in rows if r[c_idx] is not None))[:4]
                if not key_vals:
                    continue
                for other_t, other_tp in ws.tables.items():
                    if other_t == tbl or other_tp.row_count <= 0:
                        continue
                    other_cols = [c.sql_name for c in _active_columns(other_tp)]
                    if cname not in other_cols:
                        continue
                    o_show = other_cols[:10]
                    o_sql = ", ".join(f'"{c}"' for c in o_show)
                    ph = ", ".join("?" for _ in key_vals)
                    o_rows = conn.execute(
                        f'SELECT {o_sql} FROM "{other_t}" WHERE "{cname}" IN ({ph}) LIMIT ?',
                        (*key_vals, max_rows_per_probe),
                    ).fetchall()
                    if o_rows:
                        clean_o = [
                            tuple(_safe_preview_val(c, max_len=44) if isinstance(c, str) else c for c in r)
                            for r in o_rows
                        ]
                        sections.append(
                            f"  ↳ Bảng liên kết `{other_t}` theo `{cname}` (cột {o_show}): {clean_o}"
                        )
                        sib_checked += 1
                        if sib_checked >= 2:
                            break
                if sib_checked >= 2:
                    break

        # Fallback sample if no entity matched: inspect 2 sample rows from top query-relevant non-wide table
        if not sections:
            q_toks = set(re.findall(r"[a-z0-9]+", norm_vn(question)))
            best_tbl: Optional[Tuple[float, str, TableProfile]] = None
            for tname, tp in ws.tables.items():
                if tp.row_count <= 0 or len(tp.columns) > 18 or tp.notes and "wide_day_matrix=true" in tp.notes:
                    continue
                t_toks = set(re.split(r"[^a-z0-9]+", tname.lower()))
                c_toks = {sub for cp in _active_columns(tp) for sub in re.split(r"[^a-z0-9]+", cp.sql_name.lower())}
                sc = 3.0 * len(t_toks & q_toks) + len(c_toks & q_toks)
                if best_tbl is None or sc > best_tbl[0]:
                    best_tbl = (sc, tname, tp)
            if best_tbl and best_tbl[0] > 0:
                _, tname, tp = best_tbl
                s_cols = [c.sql_name for c in _active_columns(tp)][:10]
                if s_cols:
                    cols_sql = ", ".join(f'"{c}"' for c in s_cols)
                    d_col = next((c for c in s_cols if f"{tname}.{c}" in knowledge.table_date_ranges), None)
                    s_rows: List[Tuple[Any, ...]] = []
                    if d_col and date_hints:
                        s_rows = conn.execute(
                            f'SELECT {cols_sql} FROM "{tname}" WHERE substr("{d_col}", 1, 10) = ? LIMIT 3',
                            (date_hints[0],),
                        ).fetchall()
                    if not s_rows:
                        s_rows = conn.execute(f'SELECT {cols_sql} FROM "{tname}" LIMIT 2').fetchall()
                    if s_rows:
                        clean_s = [
                            tuple(_safe_preview_val(c, max_len=44) if isinstance(c, str) else c for c in r)
                            for r in s_rows
                        ]
                        sections.append(f"- Mẫu dữ liệu `{tname}` (cột {s_cols}): {clean_s}")
    except sqlite3.Error:
        pass
    finally:
        try:
            conn.set_progress_handler(None, 0)
        except Exception:
            pass
        conn.close()

    return "\n".join(sections)


_ENTITY_STOPWORDS = frozenset({
    "qua", "hom", "nay", "ngay", "thang", "nam", "quy", "tuan", "gio", "bao",
    "nhieu", "may", "don", "hang", "ban", "mua", "nhap", "xuat", "ton", "kho",
    "con", "het", "lai", "von", "no", "tra", "thu", "chi", "phi", "cao", "thap",
    "nhat", "nho", "lon", "moi", "cu", "mot", "hai", "bon", "sau", "bay", "tam",
    "chin", "muoi", "cai", "cua", "cho", "tai", "den", "truoc", "trong", "ngoai",
    "tong", "binh", "quan", "trung", "phan", "tram", "khach", "ten", "loai", "nhom",
    "hoan", "thanh", "huy", "giao", "dang",
})


_FUZZY_NOISE_TOKENS = _ENTITY_STOPWORDS | frozenset({
    "la", "ti", "ty", "le", "dc", "duoc", "ze", "nha", "vay", "tinh", "xem", "giup", "kiem", "coi",
})


def _norm_unit_code_variant(text: str) -> str:
    s = re.sub(r"\b(?:phong|p)[.\s_-]*0*(\d+)\b", r"phong \1", text)
    s = re.sub(r"\b(lop|tang|lau|ban|t)[.\s_-]*0*(\d+)\b", r"\1 \2", s)
    return s


def ground_query_entities(
    query: str,
    knowledge: WorkspaceKnowledge,
    max_matches: int = 12,
) -> List[Tuple[str, str, str]]:
    """
    Match Vietnamese product, ingredient, category, customer, or channel mentions in the query
    against actual database string values (accent-insensitive & punctuation-tolerant).
    Returns list of (table, column, exact_db_value).
    """
    q_norm = norm_vn(query)
    if not q_norm:
        return []
    q_unit = _norm_unit_code_variant(q_norm)
    q_nfc_low = normalize_nfc(query).lower()
    q_fuzzy_text = re.sub(
        r"\b(?:san pham|mat hang|khach hang|doanh thu|doanh so|don hang|hoa don|gia tri|bao nhieu|cao nhat|thap nhat|nhieu nhat)\b",
        " ",
        q_norm,
    )
    q_tokens = {
        tok for tok in re.findall(r"[a-z0-9]+", q_fuzzy_text) if tok not in _FUZZY_NOISE_TOKENS
    }
    scored: List[Tuple[float, str, str, str]] = []

    for ent in knowledge.entity_entries:
        # Word-boundary normalized phrase check (prevents substring hallucinations like 'qua' inside 'hom qua')
        if len(ent.norm_value) >= 3 and re.search(
            rf"(?<![a-z0-9]){re.escape(ent.norm_value)}(?![a-z0-9])",
            q_norm,
        ):
            if len(ent.tokens) == 1:
                tok = ent.tokens[0]
                if tok in _ENTITY_STOPWORDS:
                    continue
                # For short 1-word values (<=4 chars, e.g. 'quả', 'kg', 'ly'), require exact accented word match
                if len(ent.norm_value) <= 4:
                    raw_low = normalize_nfc(ent.raw_value).lower()
                    if not re.search(rf"(?<!\w){re.escape(raw_low)}(?!\w)", q_nfc_low):
                        continue
            score = 100.0 + len(ent.norm_value)
            scored.append((score, ent.table, ent.column, ent.raw_value))
            continue

        # Zero-padded unit/room code variant matching (e.g. 'phòng 9' <-> 'P.09 (lầu 2)')
        ent_unit = _norm_unit_code_variant(ent.norm_value)
        if ent_unit != ent.norm_value:
            m_u = re.search(r"\b(?:phong|lop|tang|lau|ban)\s+\d+\b", ent_unit)
            if m_u and re.search(rf"(?<![a-z0-9]){re.escape(m_u.group(0))}(?![a-z0-9])", q_unit):
                scored.append((90.0 + len(m_u.group(0)), ent.table, ent.column, ent.raw_value))
                continue

        # Token overlap for slightly abbreviated/reordered mentions (need >=2 tokens overlap and >=60% coverage)
        ent_toks = set(ent.tokens)
        overlap = ent_toks & q_tokens
        if not overlap:
            continue
        if len(ent_toks) >= 2:
            cov_ent = len(overlap) / len(ent_toks)
            if len(overlap) >= 2 and cov_ent >= 0.6:
                score = 40.0 * cov_ent + len(overlap) * 4.0 + (2.0 if _ENTITY_COL_RE.search(ent.column) else 0.0)
                scored.append((score, ent.table, ent.column, ent.raw_value))

    scored.sort(key=lambda x: (-x[0], len(x[3]), x[3]))
    results: List[Tuple[str, str, str]] = []
    seen_vals: Set[Tuple[str, str, str]] = set()
    for _, tbl, col, val in scored:
        key = (tbl, col, val)
        if key in seen_vals:
            continue
        seen_vals.add(key)
        results.append(key)
        if len(results) >= max_matches:
            break
    return results
