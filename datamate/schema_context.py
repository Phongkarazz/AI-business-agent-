"""Domain-agnostic schema profiling, capability detection, and Vietnamese entity grounding."""

from __future__ import annotations

import re
import sqlite3
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
    r"(?:^|_)(?:ma_?so_?thue|mst|dien_?thoai|sdt|phone|so_?dien_?thoai|email|e_mail|cccd|cmnd|ma_?kh|ma_?hang|ma_?sku|ma_?vach|barcode|nguoi_?tao)(?:$|_)",
    re.IGNORECASE,
)

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
    r"loai|nha_?cung_?cap|nhan_?vien|ncc|sku|ma_hang|ma_khach|nguyen_?nhan|doi_?tac|ben_?mua)",
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
        is_cust_tbl = bool(re.search(r"khach|customer|hoa_?don|don_?hang|ban_?hang|so_?chi_?tiet|sobanhang", tname, re.I))
        for cp in _active_columns(tp):
            active_col_tokens.append(f"{tname}.{cp.sql_name}".lower())
            if is_cust_tbl:
                customer_table_cols.append(f"{tname}.{cp.sql_name}".lower())
            if re.search(r"(?:^|_)(?:ten_?kh(?:ach(?:_?hang)?)?|tenkh|khach_?hang|ma_?kh(?:ach(?:_?hang)?)?|ma_kh_mua|customer_?id|ben_?mua|doi_?tac|so_?kh)(?:$|_)", cp.sql_name, re.I):
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
                if re.search(r"(?:^|_)(?:gia_?nhap|don_?gia(?:_?nhap)?|can_?tra(?:_?ncc)?|thanh_?tien|tong_?tien|tong_?gia_?tri|gia)(?:$|_)", c.sql_name, re.I):
                    import_price_ok = True
                    break

    # Inventory can live in stock snapshot tables OR be tracked via import lots + order lot consumption
    has_stock_table = _has_col(
        r"(?:^|[.\s_])(?:ton_?kho|ton_?cuoi(?:_?ky)?|ton_?thuc|the_?kho|sl_?ton|so_luong_?ton|bao_?cao_?ton|baocaoton)(?:$|[.\s_])"
    )
    has_lot_allocation = has_import and any(
        tp.row_count > 0 and re.search(r"don_?hang_?lo|chi_?tiet_?don_?lo|ban_?theo_?lo", t, re.I)
        for t, tp in ws.tables.items()
    )
    has_inventory = has_stock_table or has_lot_allocation or bool(
        re.search(r"(?:^|\s)(?:the_?kho|baocaoton|sotay_?tonkho|ton_?thuc)(?:\s|$)", readme_low)
    )

    has_cost = _has_col(r"(?:^|[.\s_])(?:gia_?von|gia_?von_?luc_?ban|gia_?von_?hien_?tai)(?:$|[.\s_])")

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

    has_gender = _has_col(r"(?:^|[.\s_])(?:gioi_?tinh|gender|nam_?nu|namnu|phai)(?:$|[.\s_])")
    has_address = _has_col(
        r"(?:^|[.\s_])(?:dia_?chi|addr|address|duong|phuong_?xa|quan_?huyen|tinh_?thanh)(?:$|[.\s_])",
        cust_combined,
    )
    has_debt = _has_col(
        r"(?:^|[.\s_])(?:cong_?no|phai_?thu|con_?no|da_?tra|da_?thu|khach_?da_?tra|khach_?tra|chua_?tra|con_?lai|phieu_?thu|so_?quy|tien_?thu|so_?tien_?thu)(?:$|[.\s_])"
    ) or any(
        tp.row_count > 0 and re.search(r"^(?:so_?quy|thanh_?toan|phieu_?thu|cong_?no)", t, re.I)
        for t, tp in ws.tables.items()
    )
    has_unit_conv = _has_col(r"(?:^|[.\s_])(?:quy_?doi|ti_?le_?quy_?doi|he_?so_?qd|he_?so|dv_?lon|don_?vi_?quy_?doi|danhsachdonvitinh)(?:$|[.\s_])")
    has_expiry = _has_col(r"(?:^|[.\s_])(?:han_?su_?dung|han_?dung|het_?han|ngay_?het_?han|hsd)(?:$|[.\s_])")
    has_channel = _has_col(r"(?:^|[.\s_])(?:kenh|kenh_?ban|channel|ban_?qua|nguon_?don|noi_?ban)(?:$|[.\s_])")
    has_payment = _has_col(
        r"(?:^|[.\s_])(?:phuong_?thuc(?:_?tt|_?thanh_?toan)?|hinh_?thuc(?:_?tt|_?thanh_?toan)?|pttt|cach_?tt)(?:$|[.\s_])"
    )
    has_return_reason = _has_col(r"(?:^|[.\s_])(?:nguyen_?nhan|ly_?do)(?:$|[.\s_])")
    has_staff = _has_col(r"(?:^|[.\s_])(?:nhan_?vien|ma_?nv|ma_?nv_?ban|nguoi_?ban|chuc_?vu)(?:$|[.\s_])")
    has_pharmacy_rx = _has_col(
        r"(?:^|[.\s_])(?:ke_?don|ban_?theo_?don|thuoc_?ke_?don|hoat_?chat|thanh_?phan_?chinh|danhsachthuoc|banhang_?thuoc|thong_?tin_?thuoc)(?:$|[.\s_])"
    )
    has_expenses = _has_col(r"(?:^|[.\s_])(?:chi_?phi|sotay_?chiphi|ngay_?chi)(?:$|[.\s_])") or any(
        tp.row_count > 0 and re.search(r"chi_?phi", t, re.I) for t, tp in ws.tables.items()
    )
    has_price_hist = _has_col(r"(?:^|[.\s_])(?:lich_?su_?gia|bang_?gia|banggia|gia_?moi|ngay_?ap_dung)(?:$|[.\s_])")
    has_delivery = _has_col(r"(?:^|[.\s_])(?:so_?giao_?hang|sogiaohang|bang_?ke_?phieu_?giao_?hang|luot_?giao|dot_?giao|ngay_?cho)(?:$|[.\s_])")

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
                    categorical[f"{tname}.{cp.sql_name}"] = [
                        (normalize_nfc(str(v)), int(cnt)) for v, cnt in cat_rows if v is not None
                    ]
                else:
                    categorical[f"{tname}.{cp.sql_name}"] = [
                        (normalize_nfc(str(v)), int(cnt)) for v, cnt in cp.top_values if v is not None
                    ]

            # Entity lookup values for product / customer / category / active ingredient / unit grounding
            if (
                cp.inferred_type == "text"
                and 1 <= cp.distinct_count <= 2500
                and (_ENTITY_COL_RE.search(cp.sql_name) or _CATEGORICAL_COL_RE.search(cp.sql_name))
            ):
                rows = conn.execute(
                    f'SELECT DISTINCT "{cp.sql_name}" FROM "{tname}" '
                    f'WHERE "{cp.sql_name}" IS NOT NULL'
                ).fetchall()
                for (raw_val,) in rows:
                    s_raw = normalize_nfc(str(raw_val))
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
            line += f"; lọc đơn tính doanh thu/số đơn: `{valid_filter}` [giữ cả đang giao: {valid}]"
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

    return targets, grains, "\n".join(hint_lines)


def build_workspace_knowledge(ws: BusinessWorkspace) -> WorkspaceKnowledge:
    """Build compact, cached schema summary, capability flags, date bounds, and entity index."""
    conn = ws.open_connection()
    try:
        date_ranges, data_min, data_max = _collect_table_date_ranges(conn, ws.tables)
        categorical, entity_entries = _index_entities_and_categories(conn, ws.tables)
    finally:
        conn.close()

    caps = _detect_capabilities(ws)
    status_targets, table_grains, sem_summary = _build_order_semantics(ws, categorical, date_ranges)

    lines: List[str] = []
    if data_min and data_max:
        lines.append(f"Khoảng ngày dữ liệu giao dịch của shop: {data_min} đến {data_max}")
    if sem_summary:
        lines.append("Gợi ý kỹ thuật tự động từ lược đồ:")
        lines.append(sem_summary)
    lines.append("Danh sách bảng SQLite (ngày đã chuẩn hoá YYYY-MM-DD; tiền là số nguyên VND):")

    for tname, tp in ws.tables.items():
        col_parts: List[str] = []
        empty_cols: List[str] = []
        for cp in tp.columns:
            if tp.row_count > 0 and (cp.distinct_count == 0 or cp.null_count >= tp.row_count):
                empty_cols.append(cp.sql_name)
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
                samp = ", ".join(repr(v) for v in cp.sample_values[:2]) if cp.sample_values else ""
                col_parts.append(f"{cp.sql_name} ({tag}" + (f"; e.g. {samp}" if samp else "") + ")")
        note_str = f" [notes: {', '.join(tp.notes)}]" if tp.notes else ""
        lines.append(f"- Bảng `{tname}` ({tp.row_count} dòng){note_str}:")
        lines.append("  Cột: " + " | ".join(col_parts))
        if empty_cols:
            lines.append(f"  [Cột trống 100% không có dữ liệu: {', '.join(empty_cols)}]")

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
    )


_ENTITY_STOPWORDS = frozenset({
    "qua", "hom", "nay", "ngay", "thang", "nam", "quy", "tuan", "gio", "bao",
    "nhieu", "may", "don", "hang", "ban", "mua", "nhap", "xuat", "ton", "kho",
    "con", "het", "lai", "von", "no", "tra", "thu", "chi", "phi", "cao", "thap",
    "nhat", "nho", "lon", "moi", "cu", "mot", "hai", "bon", "sau", "bay", "tam",
    "chin", "muoi", "cai", "cua", "cho", "tai", "den", "truoc", "trong", "ngoai",
    "tong", "binh", "quan", "trung", "phan", "tram", "khach", "ten", "loai", "nhom",
    "hoan", "thanh", "huy", "giao", "dang",
})


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
    q_nfc_low = normalize_nfc(query).lower()
    q_fuzzy_text = re.sub(
        r"\b(?:san pham|mat hang|khach hang|doanh thu|doanh so|don hang|hoa don|gia tri|bao nhieu|cao nhat|thap nhat|nhieu nhat)\b",
        " ",
        q_norm,
    )
    q_tokens = set(re.findall(r"[a-z0-9]+", q_fuzzy_text))
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
