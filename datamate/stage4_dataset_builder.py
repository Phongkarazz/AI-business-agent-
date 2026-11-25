"""Stage 4 (Chặng 4) Execution-Verified SFT + When2Call DPO Dataset Factory.

Combines:
1. Real ``train`` split (24 held-in shops, STRICTLY excluding ``VAL_BUSINESS_SET``)
   oracle mining verified by ``execute_sql_safe`` + ``verify_sql_semantics`` +
   official PA ``score_prediction == 1``.
2. Real ``train`` unanswerable cases + synthetic missing-column / out-of-range
   negative cases paired into When2Call DPO triplets ``(prompt, chosen, rejected)``.
3. 5 domain-agnostic messy SME archetypes (multi-period ``source_sheet``, nickname
   directory ``LEFT JOIN + COALESCE``, restored-0 phone joins, compound-cell
   Python Sandbox, wide 31-day attendance & FIFO Python Sandbox) verified end-to-end.
4. Hammer Schema Masking (~25% of SQL samples) cloning SQLite tables with masked
   identifiers and verifying exact output equivalence before keeping.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import pathlib
import random
import re
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from datamate.agent import (
    AgentConfig,
    DataMateAgent,
    QuestionAnalysis,
    build_benchmark_average_entity_sql_spec,
    build_catalog_listing_sql_spec,
    build_entity_and_metric_listing_sql_spec,
    build_extreme_comparison_sql_spec,
    check_preflight_unanswerable,
    classify_expected_type,
    extract_benchmark_average_entity_intent,
    extract_ordinal_rank,
    extract_temporal_context,
    format_sql_result,
    normalize_vn_question,
    verify_sql_semantics,
)
from datamate.evaluator_pa import score_prediction
from datamate.llm_backend import MockLLMBackend, extract_json_object
from datamate.loader import BusinessWorkspace, ColumnProfile, TableProfile, load_business_workspace
from datamate.python_sandbox import execute_python_safe
from datamate.schema_context import (
    WorkspaceKnowledge,
    build_workspace_knowledge,
    ground_query_entities,
    run_deterministic_probes,
)
from datamate.splits import VAL_BUSINESS_SET, load_split_dataset
from datamate.sql_executor import SQLExecutionResult, execute_sql_safe, norm_vn
from datamate.temporal import SolarLunarCalendar


# ---------------------------------------------------------------------------
# Role Discovery Helpers (Schema-Agnostic across 24 train shops)
# ---------------------------------------------------------------------------


@dataclass
class ShopSchemaRoles:
    sales_table: Optional[str] = None
    sales_date_col: Optional[str] = None
    sales_order_id_col: Optional[str] = None
    sales_status_col: Optional[str] = None
    valid_filter: str = ""
    cancelled_values: Tuple[str, ...] = ()
    returned_values: Tuple[str, ...] = ()
    has_repeating_orders: bool = False
    sales_header_table: Optional[str] = None
    sales_header_key: Optional[str] = None
    sales_header_date_col: Optional[str] = None
    sales_header_status_col: Optional[str] = None
    sales_header_valid_filter: str = ""
    sales_header_join_col: Optional[str] = None
    amount_col: Optional[str] = None
    qty_col: Optional[str] = None
    unit_price_col: Optional[str] = None
    item_table: Optional[str] = None
    item_join_sales_col: Optional[str] = None
    item_join_dim_col: Optional[str] = None
    item_name_col: Optional[str] = None
    cat_table: Optional[str] = None
    cat_col: Optional[str] = None
    cat_join_sales_col: Optional[str] = None
    cat_join_dim_col: Optional[str] = None
    channel_col: Optional[str] = None
    cust_col: Optional[str] = None
    cust_table: Optional[str] = None
    cust_group_col: Optional[str] = None
    cust_join_sales_col: Optional[str] = None
    cust_join_dim_col: Optional[str] = None
    import_table: Optional[str] = None
    import_date_col: Optional[str] = None
    import_status_col: Optional[str] = None
    import_valid_filter: str = ""
    import_amt_col: Optional[str] = None
    import_qty_col: Optional[str] = None
    import_item_col: Optional[str] = None
    import_header_table: Optional[str] = None
    import_header_key: Optional[str] = None
    import_header_date_col: Optional[str] = None
    import_header_status_col: Optional[str] = None
    import_header_valid_filter: str = ""
    import_header_join_col: Optional[str] = None
    debt_col: Optional[str] = None
    paid_col: Optional[str] = None


def _qident(name: str) -> str:
    return f'"{name}"' if re.search(r"[^a-zA-Z0-9_]", name) else name


def _pick_first_col(cols: Sequence[str], patterns: Sequence[str]) -> Optional[str]:
    low_map = {c.lower(): c for c in cols}
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for cl, orig in low_map.items():
            if rx.search(cl):
                return orig
    return None


def _find_join_key(
    src_cols: Sequence[str],
    dst_cols: Sequence[str],
    join_graph: Sequence[str],
    src_tbl: str,
    dst_tbl: str,
) -> Optional[Tuple[str, str]]:
    for edge in join_graph:
        clean = edge.split(" (", 1)[0]
        if " = " not in clean:
            continue
        l_part, r_part = [p.strip() for p in clean.split(" = ", 1)]
        if "." not in l_part or "." not in r_part:
            continue
        lt, lc = l_part.split(".", 1)
        rt, rc = r_part.split(".", 1)
        if lt.lower() == src_tbl.lower() and rt.lower() == dst_tbl.lower():
            return lc, rc
        if rt.lower() == src_tbl.lower() and lt.lower() == dst_tbl.lower():
            return rc, lc
    dst_low = {c.lower(): c for c in dst_cols}
    for c in src_cols:
        cl = c.lower()
        if cl in dst_low and cl not in {"ngay", "thang", "nam", "trang_thai", "ghi_chu", "so_luong", "don_gia"}:
            return c, dst_low[cl]
    return None


def discover_shop_roles(knowledge: WorkspaceKnowledge) -> ShopSchemaRoles:
    """Extract main sales, header, item, customer, debt, and import tables/columns generically."""
    roles = ShopSchemaRoles()
    ws = knowledge.workspace
    targets = {t["table"]: t for t in (knowledge.order_status_targets or [])}
    tables = ws.tables

    # 1. Pick line/fact sales table
    sales_candidates: List[Tuple[int, str]] = []
    for tname, tp in tables.items():
        if tp.row_count <= 0:
            continue
        cols = [c.sql_name for c in tp.columns]
        has_amt = any(re.search(r"(?:thanh_?tien|tt_?dong|tien_?hang|tong_?sau_?giam|tong_?tien|t_?tien|tong_?bill|^tong$|tien)", c, re.I) for c in cols)
        has_item = any(re.search(r"(?:ten_?(?:sp|hang|mon|thuoc)|ma_?(?:hang|sp|thuoc|mat_hang)|id_?(?:sp|hang|mon)|san_?pham|vat_?lieu)", c, re.I) for c in cols)
        if re.search(r"nhap|khach|nha_cung|ton_kho|lich_?su|quy_?doi|lo_?hang|thuoc$", tname, re.I):
            continue
        score = 0
        if tname in targets:
            score += 40
        if has_amt:
            score += 25
        if has_item:
            score += 20
        if re.search(r"chi_?tiet|chitiet", tname, re.I):
            score += 15
        if re.search(r"ban_?hang|don_?hang|hoa_?don|banhang", tname, re.I):
            score += 12
        score += min(10, tp.row_count // 100)
        if score >= 25:
            sales_candidates.append((score, tname))
    sales_candidates.sort(key=lambda x: (-x[0], x[1]))

    if sales_candidates:
        st = sales_candidates[0][1]
        roles.sales_table = st
        st_cols = [c.sql_name for c in tables[st].columns]
        tgt = targets.get(st, {})
        roles.sales_order_id_col = tgt.get("order_id_col") or _pick_first_col(
            st_cols,
            [r"^(?:ma_?(?:hoa_?don|don(?:_?hang)?|giao_?dich|chung_?tu|bill)|so_?(?:hoa_?don|hd))$"],
        )
        roles.sales_date_col = tgt.get("date_col") or next(
            (k.split(".", 1)[1] for k in knowledge.table_date_ranges if k.startswith(f"{st}.")),
            None,
        )
        roles.sales_status_col = tgt.get("status_col") or _pick_first_col(
            st_cols, [r"^(?:trang_?thai(?:_?don)?|tinh_?trang|ket_?qua|xu_?ly)$"]
        )
        roles.valid_filter = tgt.get("valid_filter") or ""
        roles.cancelled_values = tuple(tgt.get("cancelled_values") or ())
        roles.returned_values = tuple(tgt.get("returned_values") or ())
        roles.has_repeating_orders = bool(tgt.get("has_repeating_orders"))
        roles.amount_col = _pick_first_col(
            st_cols,
            [
                r"^(?:thanh_?tien|tt_?dong|tien_?hang|tong_?sau_?giam_?gia|tong_?tien(?:_?hang)?|t_?tien|tong_?bill|tong|tien)$",
                r"(?:thanh_?tien|tien_?hang|tong_?tien|t_?tien|tong_?bill)",
            ],
        )
        roles.qty_col = _pick_first_col(
            st_cols,
            [r"^(?:so_?luong_?quy_?doi|sl_?quy_?ra_?le|sl_?quy_?doi|sl_?co_?ban|so_?luong(?:_?san_?pham)?|slg|sluong|sl|qty)$"],
        )
        roles.unit_price_col = _pick_first_col(
            st_cols,
            [r"^(?:gia_?ban|don_?gia|gia_?niem_?yet|gia_?san_?pham|gia)$"],
        )
        roles.channel_col = _pick_first_col(st_cols, [r"(?:kenh_?ban|kenh|nguon_?don|channel)"])
        roles.item_name_col = _pick_first_col(
            st_cols,
            [r"^(?:ten_?(?:hang(?:_?hoa)?|san_?pham|sp|mon|thuoc|vat_?lieu)|san_?pham|vat_?lieu|chi_?tiet_?hang)$"],
        )
        roles.cust_col = _pick_first_col(
            st_cols, [r"^(?:ten_?khach(?:_?hang)?|ten_?kh|khach_?hang|khach|doi_?tac)$"]
        )
        roles.debt_col = _pick_first_col(st_cols, [r"^(?:con_?no|du_?no|no|cong_?no)$"])
        roles.paid_col = _pick_first_col(st_cols, [r"^(?:khach_?da_?tra|da_?tra|da_?thu)$"])

        # Look for separate sales header table (when date or status lives in hoadon while amount lives in chitiet)
        for _, cand_h in sales_candidates[1:]:
            h_cols = [c.sql_name for c in tables[cand_h].columns]
            if roles.sales_date_col and roles.valid_filter:
                break
            jk = _find_join_key(st_cols, h_cols, knowledge.join_graph, st, cand_h)
            if not jk:
                continue
            h_tgt = targets.get(cand_h, {})
            h_dcol = h_tgt.get("date_col") or next(
                (k.split(".", 1)[1] for k in knowledge.table_date_ranges if k.startswith(f"{cand_h}.")),
                None,
            )
            if h_dcol or h_tgt.get("valid_filter"):
                roles.sales_header_table = cand_h
                roles.sales_header_join_col, roles.sales_header_key = jk
                roles.sales_header_date_col = h_dcol
                roles.sales_header_status_col = h_tgt.get("status_col")
                roles.sales_header_valid_filter = h_tgt.get("valid_filter") or ""
                if not roles.sales_order_id_col:
                    roles.sales_order_id_col = jk[0]
                if not roles.cancelled_values and h_tgt.get("cancelled_values"):
                    roles.cancelled_values = tuple(h_tgt["cancelled_values"])
                if not roles.returned_values and h_tgt.get("returned_values"):
                    roles.returned_values = tuple(h_tgt["returned_values"])
                if not roles.channel_col:
                    roles.channel_col = _pick_first_col(h_cols, [r"(?:kenh_?ban|kenh|nguon_?don|channel)"])
                if not roles.cust_col:
                    roles.cust_col = _pick_first_col(
                        h_cols, [r"^(?:ten_?khach(?:_?hang)?|ten_?kh|khach_?hang|khach)$"]
                    )
                if not roles.debt_col:
                    roles.debt_col = _pick_first_col(h_cols, [r"^(?:con_?no|du_?no|no)$"])
                if not roles.paid_col:
                    roles.paid_col = _pick_first_col(h_cols, [r"^(?:khach_?da_?tra|da_?tra|da_?thu)$"])
                break

        # Item / category lookup table if missing on fact
        for tname, tp in tables.items():
            if tp.row_count <= 0 or tname == st:
                continue
            cols = [c.sql_name for c in tp.columns]
            if re.search(r"san_?pham|hang_?hoa|thuoc|danh_?muc", tname, re.I):
                jk = _find_join_key(st_cols, cols, knowledge.join_graph, st, tname)
                if jk:
                    name_c = _pick_first_col(cols, [r"^(?:ten_?(?:hang(?:_?hoa)?|san_?pham|sp|thuoc|mon)|san_?pham)$"])
                    cat_c = _pick_first_col(cols, [r"(?:nhom|danh_?muc|loai|hoat_?chat|phan_?loai)"])
                    if name_c and not roles.item_name_col:
                        roles.item_table = tname
                        roles.item_join_sales_col, roles.item_join_dim_col = jk
                        roles.item_name_col = name_c
                    if cat_c and not roles.cat_col:
                        roles.cat_table = tname
                        roles.cat_col = cat_c
                        roles.cat_join_sales_col, roles.cat_join_dim_col = jk
            if re.search(r"khach", tname, re.I):
                src_tbl_c = roles.sales_header_table or st
                src_cols_c = [c.sql_name for c in tables[src_tbl_c].columns]
                jk = _find_join_key(src_cols_c, cols, knowledge.join_graph, src_tbl_c, tname)
                if jk:
                    cg = _pick_first_col(cols, [r"(?:nhom_?khach|doi_?tuong_?kh|hang|loai_?khach)"])
                    cn = _pick_first_col(cols, [r"(?:ten_?khach(?:_?hang)?|ten_?kh|ho_?ten)"])
                    if cg or cn:
                        roles.cust_table = tname
                        roles.cust_join_sales_col, roles.cust_join_dim_col = jk
                        roles.cust_group_col = cg
                        if not roles.cust_col and cn:
                            roles.cust_col = cn

        # Import tables
        imp_cands = [
            tname
            for tname, tp in tables.items()
            if tp.row_count > 0 and re.search(r"nhap_?hang|phieu_?nhap|nhap_?kho", tname, re.I)
        ]
        for ic in imp_cands:
            icols = [c.sql_name for c in tables[ic].columns]
            amt = _pick_first_col(icols, [r"^(?:thanh_?tien|tong_?tien(?:_?nhap)?|tien_?nhap)$"])
            qty = _pick_first_col(icols, [r"^(?:so_?luong(?:_?nhap)?|sl_?nhap|sl)$"])
            if amt or qty:
                roles.import_table = ic
                roles.import_amt_col = amt
                roles.import_qty_col = qty
                roles.import_item_col = _pick_first_col(icols, [r"(?:ten_?(?:hang|sp|thuoc)|product|san_?pham|ma_?hang)"])
                roles.import_date_col = next(
                    (k.split(".", 1)[1] for k in knowledge.table_date_ranges if k.startswith(f"{ic}.")),
                    _pick_first_col(icols, [r"(?:ngay_?nhap|thoi_?gian|ngay)"]),
                )
                roles.import_status_col = _pick_first_col(icols, [r"^(?:trang_?thai|tinh_?trang)$"])
                if roles.import_status_col and f"{ic}.{roles.import_status_col}" in knowledge.categorical_values:
                    bad = [
                        v
                        for v, _ in knowledge.categorical_values[f"{ic}.{roles.import_status_col}"]
                        if re.search(r"huy|cancel", norm_vn(v))
                    ]
                    if bad:
                        roles.import_valid_filter = f"{roles.import_status_col} NOT IN ({', '.join(repr(b) for b in bad)})"
                break
        if roles.import_table and not roles.import_date_col:
            ic = roles.import_table
            icols = [c.sql_name for c in tables[ic].columns]
            for h_cand in imp_cands:
                if h_cand == ic:
                    continue
                hcols = [c.sql_name for c in tables[h_cand].columns]
                jk = _find_join_key(icols, hcols, knowledge.join_graph, ic, h_cand)
                hd = next((k.split(".", 1)[1] for k in knowledge.table_date_ranges if k.startswith(f"{h_cand}.")), None)
                if jk and hd:
                    roles.import_header_table = h_cand
                    roles.import_header_join_col, roles.import_header_key = jk
                    roles.import_header_date_col = hd
                    roles.import_header_status_col = _pick_first_col(hcols, [r"^(?:trang_?thai|tinh_?trang)$"])
                    break

    return roles


def _date_clause(alias_col: str, start: str, end: str) -> str:
    if start == "0001-01-01":
        return f"substr({alias_col}, 1, 10) <= '{end}'"
    if start == end:
        return f"substr({alias_col}, 1, 10) = '{start}'"
    return f"substr({alias_col}, 1, 10) BETWEEN '{start}' AND '{end}'"


def _status_sql(status_col: Optional[str], valid_filter: str, alias: str) -> str:
    if not valid_filter or not status_col:
        return ""
    if f"{status_col}" in valid_filter:
        return valid_filter.replace(status_col, f"{alias}.{status_col}", 1)
    return f"{alias}.{valid_filter}"


def _build_sales_from_and_where(
    roles: ShopSchemaRoles,
    bounded: Optional[Tuple[str, str]],
    include_valid_status: bool = True,
    need_cust_join: bool = False,
    need_item_join: bool = False,
) -> Tuple[str, List[str], str, Optional[str]]:
    """Build (FROM clause, WHERE list, date_col_expr, order_id_expr) for main sales schema."""
    st = roles.sales_table or ""
    from_sql = f"{_qident(st)} f"
    wheres: List[str] = []
    d_expr = f"f.{_qident(roles.sales_date_col)}" if roles.sales_date_col else None
    oid_expr = f"f.{_qident(roles.sales_order_id_col)}" if roles.sales_order_id_col else None

    st_f = _status_sql(roles.sales_status_col, roles.valid_filter, "f")
    if include_valid_status and st_f:
        wheres.append(st_f)

    if roles.sales_header_table and roles.sales_header_join_col and roles.sales_header_key:
        from_sql += (
            f"\nJOIN {_qident(roles.sales_header_table)} h "
            f"ON f.{_qident(roles.sales_header_join_col)} = h.{_qident(roles.sales_header_key)}"
        )
        if roles.sales_header_date_col and not d_expr:
            d_expr = f"h.{_qident(roles.sales_header_date_col)}"
        hf = _status_sql(roles.sales_header_status_col, roles.sales_header_valid_filter, "h")
        if include_valid_status and hf:
            wheres.append(hf)
        if not oid_expr:
            oid_expr = f"h.{_qident(roles.sales_header_key)}"

    if need_item_join and roles.item_table and roles.item_join_sales_col and roles.item_join_dim_col:
        from_sql += (
            f"\nJOIN {_qident(roles.item_table)} sp "
            f"ON f.{_qident(roles.item_join_sales_col)} = sp.{_qident(roles.item_join_dim_col)}"
        )

    if need_cust_join and roles.cust_table and roles.cust_join_sales_col and roles.cust_join_dim_col:
        src_al = "h" if (roles.sales_header_table and roles.cust_join_sales_col in {
            roles.sales_header_key
        } or roles.sales_header_table) else "f"
        from_sql += (
            f"\nLEFT JOIN {_qident(roles.cust_table)} kh "
            f"ON {src_al}.{_qident(roles.cust_join_sales_col)} = kh.{_qident(roles.cust_join_dim_col)}"
        )

    if bounded and d_expr:
        wheres.append(_date_clause(d_expr, bounded[0], bounded[1]))

    return from_sql, wheres, (d_expr or ""), oid_expr


def generate_candidate_sqls_for_question(
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
    entity_matches: Sequence[Tuple[str, str, str]],
    roles: ShopSchemaRoles,
) -> List[str]:
    """Generate schema-driven SQL candidates to match ground-truth answers under official PA."""
    qn = normalize_vn_question(question)
    cands: List[str] = []

    # 1. Include deterministic specs first when applicable
    if analysis.extreme_comparison is not None:
        sp = build_extreme_comparison_sql_spec(question, knowledge, analysis)
        if sp and sp.get("suggested_sql"):
            cands.append(sp["suggested_sql"])
    if extract_benchmark_average_entity_intent(question) is not None:
        sp = build_benchmark_average_entity_sql_spec(question, knowledge, analysis)
        if sp and sp.get("suggested_sql"):
            cands.append(sp["suggested_sql"])
    sp_em = build_entity_and_metric_listing_sql_spec(question, knowledge, analysis, entity_matches)
    if sp_em and sp_em.get("suggested_sql"):
        cands.append(sp_em["suggested_sql"])
    sp_cat = build_catalog_listing_sql_spec(question, knowledge, analysis, entity_matches)
    if sp_cat and sp_cat.get("suggested_sql"):
        cands.append(sp_cat["suggested_sql"])

    if not roles.sales_table:
        return cands

    bounded = analysis.bounded_period
    st_tbl = roles.sales_table
    amt_c = roles.amount_col
    qty_c = roles.qty_col

    # Collect matching entity predicates from entity_matches
    matched_item_vals = [
        (t, c, v)
        for t, c, v in entity_matches
        if re.search(r"(?:ten_?(?:sp|hang|mon|thuoc|vat_?lieu)|san_?pham|chi_?tiet)", c, re.I)
    ]
    matched_cat_vals = [
        (t, c, v)
        for t, c, v in entity_matches
        if re.search(r"(?:nhom|danh_?muc|loai|hoat_?chat|phan_?loai)", c, re.I)
    ]
    matched_chan_vals = [
        (t, c, v)
        for t, c, v in entity_matches
        if re.search(r"(?:kenh|channel|nguon_?don)", c, re.I)
    ]
    matched_cust_grp = [
        (t, c, v)
        for t, c, v in entity_matches
        if re.search(r"(?:nhom_?kh|doi_?tuong_?kh|hang|loai_?kh)", c, re.I)
    ]

    # Case A: Cancel / Return % rate
    if analysis.expected_type == "percent" and re.search(r"\b(?:huy|tra\s+hang|hoan\s+tra)\b", qn):
        bad_vals = list(roles.cancelled_values) if "huy" in qn and "tra" not in qn else list(roles.cancelled_values + roles.returned_values)
        if not bad_vals:
            bad_vals = ["Đã hủy đơn", "hủy", "cancelled"]
        base_tbl = roles.sales_header_table or st_tbl
        b_cols = [c.sql_name for c in knowledge.workspace.tables[base_tbl].columns]
        sc = roles.sales_header_status_col or roles.sales_status_col or _pick_first_col(b_cols, [r"trang_?thai|tinh_?trang"])
        dc = roles.sales_header_date_col or roles.sales_date_col or _pick_first_col(b_cols, [r"ngay|thoi_?gian"])
        oid = roles.sales_header_key or roles.sales_order_id_col
        if sc:
            in_vals = ", ".join(repr(v) for v in bad_vals)
            cnt_num = (
                f"COUNT(DISTINCT CASE WHEN {sc} IN ({in_vals}) THEN {_qident(oid)} END)"
                if oid
                else f"SUM(CASE WHEN {sc} IN ({in_vals}) THEN 1 ELSE 0 END)"
            )
            cnt_den = f"NULLIF(COUNT(DISTINCT {_qident(oid)}), 0)" if oid else "NULLIF(COUNT(*), 0)"
            w_d = f"\nWHERE {_date_clause(_qident(dc), bounded[0], bounded[1])}" if (bounded and dc) else ""
            cands.append(f"SELECT ROUND_HALF_UP({cnt_num} * 100.0 / {cnt_den}, 2) AS ty_le_pct\nFROM {_qident(base_tbl)}{w_d};")

    # Case B: Growth/Change % between 2 temporal windows
    if analysis.expected_type == "percent" and len(analysis.temporal_windows) >= 2 and amt_c:
        (_, s1, e1), (_, s2, e2) = analysis.temporal_windows[0], analysis.temporal_windows[1]
        from_s, wheres_s, d_expr, _ = _build_sales_from_and_where(roles, None, include_valid_status=True)
        if d_expr:
            w_sql = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
            amt_expr = f"f.{_qident(amt_c)}"
            cands.append(
                f"SELECT ROUND_HALF_UP(\n"
                f"  (SUM(CASE WHEN {_date_clause(d_expr, s1, e1)} THEN {amt_expr} ELSE 0 END) -\n"
                f"   SUM(CASE WHEN {_date_clause(d_expr, s2, e2)} THEN {amt_expr} ELSE 0 END)) * 100.0 /\n"
                f"  NULLIF(SUM(CASE WHEN {_date_clause(d_expr, s2, e2)} THEN {amt_expr} ELSE 0 END), 0),\n"
                f"  2\n) AS pct_change\nFROM {from_s}{w_sql};"
            )

    # Case C: Single-group % share (chiem bao nhieu % doanh thu)
    if analysis.expected_type == "percent" and re.search(r"\b(?:chiem|ty\s+trong|ti\s+trong|dong\s+gop)\b", qn) and amt_c:
        need_it = bool(roles.cat_table and roles.cat_col)
        from_s, wheres_s, _, _ = _build_sales_from_and_where(roles, bounded, include_valid_status=True, need_item_join=need_it)
        w_sql = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
        amt_expr = f"f.{_qident(amt_c)}"
        for _, col_g, val_g in matched_cat_vals + matched_chan_vals + matched_cust_grp:
            tbl_pref = "sp." if (roles.cat_table and col_g == roles.cat_col) else "f."
            cands.append(
                f"SELECT ROUND_HALF_UP(\n"
                f"  SUM(CASE WHEN NORM_VN({tbl_pref}{_qident(col_g)}) = NORM_VN({val_g!r}) THEN {amt_expr} ELSE 0 END) * 100.0 /\n"
                f"  NULLIF(SUM({amt_expr}), 0),\n"
                f"  2\n) AS ty_trong_pct\nFROM {from_s}{w_sql};"
            )

    # Case D: Number — Cancel count
    if analysis.expected_type == "number" and re.search(r"\b(?:don\s+huy|bi\s+huy|da\s+huy)\b", qn) and not re.search(r"\b(?:doanh\s+thu|tien|gia\s+tri)\b", qn):
        cvals = list(roles.cancelled_values) or ["Đã hủy đơn", "hủy"]
        base_tbl = roles.sales_header_table or st_tbl
        b_cols = [c.sql_name for c in knowledge.workspace.tables[base_tbl].columns]
        sc = roles.sales_header_status_col or roles.sales_status_col or _pick_first_col(b_cols, [r"trang_?thai|tinh_?trang"])
        dc = roles.sales_header_date_col or roles.sales_date_col or _pick_first_col(b_cols, [r"ngay|thoi_?gian"])
        oid = roles.sales_header_key or roles.sales_order_id_col
        if sc:
            whs = [f"{sc} IN ({', '.join(repr(v) for v in cvals)})"]
            if bounded and dc:
                whs.append(_date_clause(_qident(dc), bounded[0], bounded[1]))
            cnt_e = f"COUNT(DISTINCT {_qident(oid)})" if oid else "COUNT(*)"
            cands.append(f"SELECT {cnt_e} AS so_don_huy\nFROM {_qident(base_tbl)}\nWHERE {' AND '.join(whs)};")

    # Case E: Unit selling price of item on a date ('don gia ... bao nhieu')
    if analysis.expected_type == "number" and re.search(r"\b(?:don\s+gia|gia\s+ban)\b", qn) and roles.unit_price_col:
        from_s, wheres_s, _, _ = _build_sales_from_and_where(roles, bounded, include_valid_status=False, need_item_join=bool(roles.item_table))
        up_expr = f"f.{_qident(roles.unit_price_col)}"
        for ent_t, ent_c, ent_v in matched_item_vals[:2]:
            pf = "sp." if roles.item_table and ent_t == roles.item_table else "f."
            w2 = list(wheres_s) + [f"NORM_VN({pf}{_qident(ent_c)}) = NORM_VN({ent_v!r})"]
            cands.append(
                f"SELECT ROUND_HALF_UP(AVG({up_expr}), 0) AS don_gia\nFROM {from_s}\nWHERE {' AND '.join(w2)};"
            )

    # Case F: Import total / avg import price
    if analysis.expected_type == "number" and roles.import_table and re.search(r"\b(?:nhap\s+hang|phieu\s+nhap|gia\s+nhap|nhap\s+kho|tien\s+nhap)\b", qn):
        ic = roles.import_table
        imp_from = f"{_qident(ic)} i"
        imp_wh: List[str] = []
        d_imp = f"i.{_qident(roles.import_date_col)}" if roles.import_date_col else None
        if roles.import_valid_filter:
            imp_wh.append(_status_sql(roles.import_status_col, roles.import_valid_filter, "i"))
        if roles.import_header_table and roles.import_header_join_col and roles.import_header_key:
            imp_from += f"\nJOIN {_qident(roles.import_header_table)} ih ON i.{_qident(roles.import_header_join_col)} = ih.{_qident(roles.import_header_key)}"
            if roles.import_header_date_col and not d_imp:
                d_imp = f"ih.{_qident(roles.import_header_date_col)}"
        if bounded and d_imp:
            imp_wh.append(_date_clause(d_imp, bounded[0], bounded[1]))
        if re.search(r"\b(?:gia\s+nhap\s+binh\s+quan|gia\s+nhap\s+trung\s+binh)\b", qn) and roles.import_amt_col and roles.import_qty_col:
            for _, ic_col, ic_val in matched_item_vals[:2]:
                w2 = list(imp_wh) + [f"NORM_VN(i.{_qident(ic_col)}) = NORM_VN({ic_val!r})"] if roles.import_item_col else list(imp_wh)
                w_s = f"\nWHERE {' AND '.join(w2)}" if w2 else ""
                cands.append(
                    f"SELECT ROUND_HALF_UP(SUM(i.{_qident(roles.import_amt_col)}) * 1.0 / NULLIF(SUM(i.{_qident(roles.import_qty_col)}), 0), 0) AS gia_nhap_bq\n"
                    f"FROM {imp_from}{w_s};"
                )
        elif roles.import_amt_col:
            w_s = f"\nWHERE {' AND '.join(imp_wh)}" if imp_wh else ""
            cands.append(f"SELECT ROUND_HALF_UP(SUM(i.{_qident(roles.import_amt_col)}), 0) AS tong_nhap\nFROM {imp_from}{w_s};")

    # Case G: AOV ('gia tri trung binh mot don')
    if analysis.expected_type == "number" and re.search(r"\b(?:trung\s+binh|binh\s+quan)\b.*\b(?:don|hoa\s+don|bill)\b|\baov\b", qn) and amt_c:
        from_s, wheres_s, _, oid_e = _build_sales_from_and_where(roles, bounded, include_valid_status=True)
        if oid_e:
            w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
            cands.append(
                f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}) * 1.0 / NULLIF(COUNT(DISTINCT {oid_e}), 0), 0) AS aov\nFROM {from_s}{w_s};"
            )

    # Case H: Order count with min order value ('don co doanh thu tu X tro len' / plain order count)
    if analysis.expected_type == "number" and re.search(r"\b(?:so\s+don|may\s+don|bao\s+nhieu\s+don|co\s+bao\s+nhieu\s+hoa\s+don)\b", qn):
        from_s, wheres_s, _, oid_e = _build_sales_from_and_where(roles, bounded, include_valid_status=True)
        m_thresh = re.search(r"\btu\s+([\d.,]+)\s*(?:dong|d|nghin|k|tr|trieu)?\s+tro\s+len\b", qn)
        if m_thresh and oid_e and amt_c:
            num_raw = m_thresh.group(1).replace(".", "").replace(",", "")
            if num_raw.isdigit():
                w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
                cands.append(
                    f"WITH per_order AS (\n"
                    f"  SELECT {oid_e} AS oid, SUM(f.{_qident(amt_c)}) AS tot\n"
                    f"  FROM {from_s}{w_s}\n  GROUP BY {oid_e}\n  HAVING tot >= {int(num_raw)}\n)\n"
                    f"SELECT COUNT(*) AS so_don FROM per_order;"
                )
        elif not re.search(r"\b(?:huy|tra\s+hang)\b", qn):
            w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
            cnt_e = f"COUNT(DISTINCT {oid_e})" if oid_e else "COUNT(*)"
            cands.append(f"SELECT {cnt_e} AS so_don\nFROM {from_s}{w_s};")

    # Case I: Revenue / Quantity by matched item / customer group / channel / overall
    if analysis.expected_type == "number" and amt_c:
        need_c = bool(matched_cust_grp and roles.cust_table)
        need_i = bool((matched_item_vals or matched_cat_vals) and roles.item_table)
        from_s, wheres_s, _, _ = _build_sales_from_and_where(
            roles, bounded, include_valid_status=True, need_cust_join=need_c, need_item_join=need_i
        )
        # Item or qty for specific entity
        for ent_t, ent_c, ent_v in matched_item_vals[:2]:
            pf = "sp." if (roles.item_table and ent_t == roles.item_table) else "f."
            w2 = list(wheres_s) + [f"NORM_VN({pf}{_qident(ent_c)}) = NORM_VN({ent_v!r})"]
            if qty_c and re.search(r"\b(?:may|bao\s+nhieu|so\s+luong)\b", qn) and not re.search(r"\b(?:tien|doanh\s+thu)\b", qn):
                cands.append(f"SELECT ROUND_HALF_UP(SUM(f.{_qident(qty_c)}), 0) AS tong_sl\nFROM {from_s}\nWHERE {' AND '.join(w2)};")
            cands.append(f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS doanh_thu\nFROM {from_s}\nWHERE {' AND '.join(w2)};")
        # Category / active ingredient
        for ent_t, ent_c, ent_v in matched_cat_vals[:2]:
            pf = "sp." if (roles.cat_table and ent_t == roles.cat_table) else "f."
            w2 = list(wheres_s) + [f"NORM_VN({pf}{_qident(ent_c)}) LIKE '%' || NORM_VN({ent_v!r}) || '%'"]
            cands.append(f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS doanh_thu\nFROM {from_s}\nWHERE {' AND '.join(w2)};")
        # Customer group
        for ent_t, ent_c, ent_v in matched_cust_grp[:2]:
            pf = "kh." if (roles.cust_table and ent_t == roles.cust_table) else "f."
            w2 = list(wheres_s) + [f"NORM_VN({pf}{_qident(ent_c)}) = NORM_VN({ent_v!r})"]
            cands.append(f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS doanh_thu\nFROM {from_s}\nWHERE {' AND '.join(w2)};")
        # Plain overall revenue
        if not (matched_item_vals or matched_cat_vals or matched_cust_grp or matched_chan_vals):
            w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
            cands.append(f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS doanh_thu\nFROM {from_s}{w_s};")

    # Case J: Best month / best day (`date` expected)
    if analysis.expected_type == "date" and amt_c:
        from_s, wheres_s, d_expr, _ = _build_sales_from_and_where(roles, bounded, include_valid_status=True)
        if d_expr:
            w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
            grp = f"strftime('%Y-%m', {d_expr})" if analysis.date_granularity == "month" else f"substr({d_expr}, 1, 10)"
            direction = "ASC" if re.search(r"\b(?:thap\s+nhat|it\s+nhat|te\s+nhat)\b", qn) else "DESC"
            cands.append(
                f"SELECT {grp} AS period\nFROM {from_s}{w_s}\nGROUP BY period\nORDER BY SUM(f.{_qident(amt_c)}) {direction}\nLIMIT 1;"
            )

    # Case K: Monthly series list ('3 thang lien nhau') or Top-N best sellers list
    if analysis.expected_type == "list":
        top_m = re.search(r"\btop\s*(\d+)|\b(\d+)\s+mat\s+hang\s+ban\s+chay\b", qn)
        if top_m and (roles.item_name_col or roles.item_table):
            k_n = int(top_m.group(1) or top_m.group(2))
            from_s, wheres_s, _, _ = _build_sales_from_and_where(
                roles, bounded, include_valid_status=True, need_item_join=bool(roles.item_table)
            )
            ic_expr = f"sp.{_qident(roles.item_name_col)}" if roles.item_table else f"f.{_qident(roles.item_name_col)}"
            w2 = list(wheres_s) + [f"NORM_VN({ic_expr}) != 'phi phuc vu'"]
            metric_c = qty_c if (qty_c and re.search(r"\bban\s+chay\b", qn)) else amt_c
            if metric_c:
                cands.append(
                    f"SELECT {ic_expr} AS ten_hang\nFROM {from_s}\nWHERE {' AND '.join(w2)}\n"
                    f"GROUP BY {ic_expr}\nORDER BY SUM(f.{_qident(metric_c)}) DESC, {ic_expr} ASC\nLIMIT {k_n};"
                )
        elif amt_c and bounded and re.search(r"\bthang\s+lien\s+nhau\b", qn):
            from_s, wheres_s, d_expr, _ = _build_sales_from_and_where(roles, bounded, include_valid_status=True)
            if d_expr:
                w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
                cands.append(
                    f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS doanh_thu\n"
                    f"FROM {from_s}{w_s}\nGROUP BY strftime('%Y-%m', {d_expr})\nORDER BY strftime('%Y-%m', {d_expr}) ASC;"
                )

    return list(dict.fromkeys(cands))


def _derive_unanswerable_reason(
    question: str,
    knowledge: WorkspaceKnowledge,
    analysis: QuestionAnalysis,
    preflight_msg: Optional[str],
) -> str:
    if preflight_msg:
        return preflight_msg
    dmin = knowledge.data_min_date or "?"
    dmax = knowledge.data_max_date or "?"
    if analysis.bounded_period and (analysis.bounded_period[1] < dmin or analysis.bounded_period[0] > dmax):
        return f"Dữ liệu của shop chỉ có trong khoảng {dmin} đến {dmax}, không có phát sinh trong kỳ được hỏi."
    tbl_list = ", ".join(knowledge.valid_tables[:6])
    return (
        f"Lược đồ hiện có ({tbl_list}) không chứa đủ cột hoặc dữ liệu phát sinh phù hợp để tính chính xác câu hỏi này."
    )


# ---------------------------------------------------------------------------
# Hammer Schema Masking with Exact SQL Execution Verification
# ---------------------------------------------------------------------------


_SQL_KEYWORDS_NO_MASK = frozenset({
    "select", "from", "where", "join", "left", "right", "inner", "outer", "on", "as",
    "and", "or", "not", "in", "is", "null", "group", "by", "order", "asc", "desc",
    "limit", "offset", "having", "distinct", "case", "when", "then", "else", "end",
    "sum", "count", "avg", "min", "max", "total", "coalesce", "nullif", "cast",
    "between", "like", "with", "union", "all", "over", "strftime", "substr", "trim",
    "lower", "upper", "round_half_up", "norm_vn", "real", "text", "integer", "float",
})


def mask_workspace_and_sql(
    ws: BusinessWorkspace,
    sql_query: str,
    rng: random.Random,
    tmp_dir: pathlib.Path,
    tag: str,
) -> Optional[Tuple[BusinessWorkspace, WorkspaceKnowledge, str, SQLExecutionResult]]:
    """
    Clone only tables referenced in ``sql_query`` into a temporary SQLite DB with
    Hammer-masked table & column names, execute original vs masked SQL, and
    confirm identical results before returning ``(masked_ws, masked_know, masked_sql, res)``.
    """
    sql_low = (sql_query or "").lower()
    ref_tables = [
        tp for tp in ws.tables.values() if tp.row_count > 0 and re.search(rf"\b{re.escape(tp.table_name.lower())}\b", sql_low)
    ]
    if not ref_tables or any(tp.row_count > 25000 for tp in ref_tables):
        return None

    # Build injective masked table & column maps
    tbl_map: Dict[str, str] = {}
    col_map: Dict[str, str] = {}
    t_idx = 1
    c_idx = 1
    for tp in ref_tables:
        m_tbl = f"tb_{tag}_{t_idx}"
        tbl_map[tp.table_name] = m_tbl
        t_idx += 1
        for cp in tp.columns:
            cn = cp.sql_name
            if cn in col_map:
                continue
            if cn.lower() == "source_sheet":
                col_map[cn] = "source_sheet"
                continue
            pfx = (
                "d" if cp.inferred_type in ("date", "datetime")
                else ("v" if cp.inferred_type in ("integer", "real") else "k")
            )
            col_map[cn] = f"{pfx}_c{c_idx}"
            c_idx += 1

    # Rewrite SQL safely using longest-first token boundaries outside string literals
    def _rewrite_sql_code_only(text: str) -> str:
        parts = re.split(r"('(?:''|[^'])*')", text)
        all_repls: List[Tuple[str, str]] = []
        for orig, masked in tbl_map.items():
            all_repls.append((orig, masked))
        for orig, masked in col_map.items():
            if orig.lower() not in _SQL_KEYWORDS_NO_MASK and orig != masked:
                all_repls.append((orig, masked))
        all_repls.sort(key=lambda x: -len(x[0]))
        out_parts: List[str] = []
        for idx, chunk in enumerate(parts):
            if idx % 2 == 1:
                out_parts.append(chunk)
                continue
            rewritten = chunk
            for orig, masked in all_repls:
                rewritten = re.sub(
                    rf'(?<![a-zA-Z0-9_])["`]?{re.escape(orig)}["`]?(?![a-zA-Z0-9_])',
                    masked,
                    rewritten,
                    flags=re.IGNORECASE,
                )
            out_parts.append(rewritten)
        return "".join(out_parts)

    masked_sql = _rewrite_sql_code_only(sql_query)

    # Materialize masked SQLite DB cleanly
    masked_bdir = tmp_dir / f"masked_{tag}"
    masked_bdir.mkdir(parents=True, exist_ok=True)
    masked_db_path = masked_bdir / "masked.sqlite"
    orig_conn = ws.open_connection()
    m_conn = sqlite3.connect(masked_db_path)
    masked_tables_prof: Dict[str, TableProfile] = {}
    try:
        for tp in ref_tables:
            m_tbl = tbl_map[tp.table_name]
            cols = tp.columns
            col_defs = ", ".join(
                f'"{col_map[c.sql_name]}" '
                + ("INTEGER" if c.inferred_type == "integer" else ("REAL" if c.inferred_type == "real" else "TEXT"))
                for c in cols
            )
            m_conn.execute(f'CREATE TABLE "{m_tbl}" ({col_defs})')
            orig_sel = ", ".join(f'"{c.sql_name}"' for c in cols)
            rows = orig_conn.execute(f'SELECT {orig_sel} FROM "{tp.table_name}"').fetchall()
            if rows:
                ph = ", ".join("?" for _ in cols)
                m_conn.executemany(f'INSERT INTO "{m_tbl}" VALUES ({ph})', rows)

            m_cols_prof = []
            raw_to_sql: Dict[str, str] = {}
            for c in cols:
                mc = col_map[c.sql_name]
                raw_label = f"{c.raw_name} ({mc})" if c.raw_name else mc
                raw_to_sql[raw_label] = mc
                m_cols_prof.append(
                    ColumnProfile(
                        raw_name=raw_label,
                        sql_name=mc,
                        inferred_type=c.inferred_type,
                        null_count=c.null_count,
                        distinct_count=c.distinct_count,
                        top_values=list(c.top_values),
                        sample_values=list(c.sample_values),
                    )
                )
            masked_tables_prof[m_tbl] = TableProfile(
                table_name=m_tbl,
                raw_name=f"{tp.raw_name} -> {m_tbl}",
                source_files=["masked.sqlite"],
                row_count=tp.row_count,
                columns=m_cols_prof,
                raw_to_sql=raw_to_sql,
                notes=list(tp.notes),
            )
        m_conn.commit()
    finally:
        orig_conn.close()
        m_conn.close()

    masked_ws = BusinessWorkspace(
        business_id=f"masked_{tag}",
        business_dir=masked_bdir,
        db_path=masked_db_path,
        readme_text=ws.readme_text,
        tables=masked_tables_prof,
        source_kind="sqlite_normalized",
    )
    masked_know = build_workspace_knowledge(masked_ws)

    dt_cols_orig = tuple(getattr(ws, "datetime_columns", ()) or ())
    res_orig = execute_sql_safe(ws.open_connection, sql_query, valid_tables=list(ws.tables.keys()), datetime_columns=dt_cols_orig, timeout_seconds=1.5)
    res_mask = execute_sql_safe(masked_ws.open_connection, masked_sql, valid_tables=masked_know.valid_tables, timeout_seconds=1.5)
    if not (res_orig.ok and res_mask.ok and res_orig.rows == res_mask.rows):
        return None
    return masked_ws, masked_know, masked_sql, res_mask


# ---------------------------------------------------------------------------
# 5 Synthetic Messy SME Archetype Workspaces (Domain-Agnostic Chaos Coverage)
# ---------------------------------------------------------------------------


def _build_chaos_archetype_records(
    dm_agent: DataMateAgent,
    tmp_dir: pathlib.Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Generate execution-verified SQL & Python Sandbox trajectories across 5 tough messy archetypes."""
    sft_rows: List[Dict[str, Any]] = []
    dpo_rows: List[Dict[str, Any]] = []

    def _emit_sft(
        rec_id: str,
        cat: str,
        biz: str,
        q: str,
        as_of: str,
        know: WorkspaceKnowledge,
        completion_obj: Dict[str, Any],
        retract_note: Optional[str] = None,
    ) -> Tuple[str, str]:
        an = classify_expected_type(q)
        w, ts, b, ps = extract_temporal_context(q, as_of, None)
        an.temporal_windows, an.temporal_summary, an.bounded_period, an.prior_needed_start = w, ts, b, ps
        ents = ground_query_entities(q, know, max_matches=10)
        probes = run_deterministic_probes(q, know, ents)
        pref_py = completion_obj.get("python") is not None
        sys_p, usr_p = dm_agent._build_sql_prompt(
            question=q,
            as_of_date=as_of,
            knowledge=know,
            analysis=an,
            temporal_summary=ts,
            entity_matches=ents,
            probe_context=probes,
            prefer_python=pref_py,
            retraction_note=retract_note,
        )
        ans_str = json.dumps(completion_obj, ensure_ascii=False)
        sft_rows.append(
            {
                "id": rec_id,
                "category": cat,
                "business_id": biz,
                "messages": [
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": usr_p},
                    {"role": "assistant", "content": ans_str},
                ],
            }
        )
        return sys_p, usr_p

    # Archetype 1: Multi-period rental ledger with source_sheet
    b1 = tmp_dir / "arch_nhatro"
    c1 = tmp_dir / "cache_nhatro"
    b1.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(b1 / "nhatro.sqlite") as conn:
        conn.execute("CREATE TABLE ds_phong (phong TEXT, gia_thue REAL, tien_coc REAL)")
        conn.executemany(
            "INSERT INTO ds_phong VALUES (?, ?, ?)",
            [("P.01", 3200000, 3200000), ("P.02", 3500000, 3500000), ("P.09", 3800000, 3800000)],
        )
        conn.execute(
            "CREATE TABLE sothutien (phong TEXT, dien_moi REAL, nuoc_moi REAL, tien_phong REAL, da_thu REAL, source_sheet TEXT)"
        )
        conn.executemany(
            "INSERT INTO sothutien VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("P.09", 1240, 82, 3800000, 4150000, "T07.2025"),
                ("P.09", 1315, 90, 3800000, 4280000, "T08.2025"),
                ("P.09", 1390, 98, 3800000, 4210000, "T09.2025"),
                ("P.01", 610, 40, 3200000, 3500000, "T09.2025"),
                ("P.02", 820, 55, 3500000, 3850000, "T09.2025"),
            ],
        )
        conn.commit()
    ws1 = load_business_workspace(b1, cache_dir=c1, force_rebuild=True)
    k1 = build_workspace_knowledge(ws1)

    q_a1 = "Liệt kê lịch sử chỉ số điện mới, nước mới và tiền đã thu của phòng 9 qua các kỳ"
    sql_a1 = (
        "SELECT source_sheet, dien_moi, nuoc_moi, da_thu\n"
        "FROM sothutien\n"
        "WHERE NORM_VN(phong) = NORM_VN('P.09')\n"
        "ORDER BY source_sheet;"
    )
    r1 = execute_sql_safe(ws1.open_connection, sql_a1, valid_tables=k1.valid_tables)
    assert r1.ok and r1.row_count == 3
    sp, up = _emit_sft("ARCH1_MULTI_SHEET", "multi_period_history", "arch_nhatro", q_a1, "2025-10-01", k1, {"status": "ok", "sql": sql_a1})
    bad_collapse = "SELECT phong, SUM(dien_moi) AS tong_dien, SUM(nuoc_moi) AS tong_nuoc, SUM(da_thu) AS tong_thu FROM sothutien WHERE NORM_VN(phong) = NORM_VN('P.09') GROUP BY phong;"
    dpo_rows.append({
        "id": "DPO_ARCH1_COLLAPSE",
        "category": "multi_period_guard",
        "business_id": "arch_nhatro",
        "system": sp,
        "prompt": up,
        "chosen": json.dumps({"status": "ok", "sql": sql_a1}, ensure_ascii=False),
        "rejected": json.dumps({"status": "ok", "sql": bad_collapse}, ensure_ascii=False),
    })

    # Archetype 2: Salon/Spa nickname FKs + LEFT JOIN + COALESCE
    b2 = tmp_dir / "arch_spa"
    c2 = tmp_dir / "cache_spa"
    b2.mkdir(parents=True, exist_ok=True)
    (b2 / "ds_ktv.csv").write_text("ho_ten,biet_danh\nNguyễn Thị Lan,Bé Lan\nTrần Văn Tùng,Tùng\n", encoding="utf-8")
    (b2 / "khach_quen.csv").write_text("ho_ten,ten_goi,dien_thoai\nPhạm Minh Châu,Châu ngân hàng,909123456\n", encoding="utf-8")
    (b2 / "phieu_dv.csv").write_text(
        "ngay,tho,khach,dich_vu,tien\n"
        "2026-04-02,Bé Lan,Châu ngân hàng,Gội dưỡng sinh,250000\n"
        "2026-04-03,Tùng,Khách lẻ sáng,Cắt tóc nam,120000\n"
        "2026-04-05,Bé Lan,Khách vãng lai,Nhuộm tóc,650000\n",
        encoding="utf-8",
    )
    ws2 = load_business_workspace(b2, cache_dir=c2, force_rebuild=True)
    k2 = build_workspace_knowledge(ws2)

    q_a2a = "Thống kê tổng doanh thu theo tên đầy đủ của từng kỹ thuật viên?"
    sql_a2a = (
        "SELECT COALESCE(t.ho_ten, p.tho) AS ky_thuat_vien, ROUND_HALF_UP(SUM(p.tien), 0) AS tong_doanh_thu\n"
        "FROM phieu_dv p\n"
        "LEFT JOIN ds_ktv t ON NORM_VN(p.tho) = NORM_VN(t.biet_danh)\n"
        "GROUP BY COALESCE(t.ho_ten, p.tho)\n"
        "ORDER BY tong_doanh_thu DESC;"
    )
    r2a = execute_sql_safe(ws2.open_connection, sql_a2a, valid_tables=k2.valid_tables)
    assert r2a.ok and r2a.row_count == 2
    sp, up = _emit_sft("ARCH2_NICKNAME_JOIN", "nickname_fk_join", "arch_spa", q_a2a, "2026-04-10", k2, {"status": "ok", "sql": sql_a2a})
    dpo_rows.append({
        "id": "DPO_ARCH2_FALSE_ABSTAIN",
        "category": "join_vs_false_abstain",
        "business_id": "arch_spa",
        "system": sp,
        "prompt": up,
        "chosen": json.dumps({"status": "ok", "sql": sql_a2a}, ensure_ascii=False),
        "rejected": json.dumps({"status": "unanswerable", "reason": "Bảng phieu_dv không có cột ho_ten của kỹ thuật viên."}, ensure_ascii=False),
    })

    q_a2b = "Liệt kê các khách hàng và tổng tiền làm dịch vụ (giữ cả khách vãng lai chưa lưu danh bạ)"
    sql_a2b = (
        "SELECT COALESCE(k.ho_ten, p.khach) AS khach_hang, ROUND_HALF_UP(SUM(p.tien), 0) AS tong_tien\n"
        "FROM phieu_dv p\n"
        "LEFT JOIN khach_quen k ON NORM_VN(p.khach) = NORM_VN(k.ten_goi)\n"
        "GROUP BY COALESCE(k.ho_ten, p.khach)\n"
        "ORDER BY tong_tien DESC;"
    )
    r2b = execute_sql_safe(ws2.open_connection, sql_a2b, valid_tables=k2.valid_tables)
    assert r2b.ok and r2b.row_count == 3
    sp, up = _emit_sft("ARCH2_LEFT_JOIN_COALESCE", "optional_directory_left_join", "arch_spa", q_a2b, "2026-04-10", k2, {"status": "ok", "sql": sql_a2b})
    bad_inner = "SELECT k.ho_ten, SUM(p.tien) AS tong_tien FROM phieu_dv p JOIN khach_quen k ON p.khach = k.ten_goi GROUP BY k.ho_ten;"
    dpo_rows.append({
        "id": "DPO_ARCH2_INNER_DROP",
        "category": "left_join_preservation",
        "business_id": "arch_spa",
        "system": sp,
        "prompt": up,
        "chosen": json.dumps({"status": "ok", "sql": sql_a2b}, ensure_ascii=False),
        "rejected": json.dumps({"status": "ok", "sql": bad_inner}, ensure_ascii=False),
    })

    # Archetype 3: Rental + Phone leading-0 restoration + LEFT JOIN
    b3 = tmp_dir / "arch_thuedo"
    c3 = tmp_dir / "cache_thuedo"
    b3.mkdir(parents=True, exist_ok=True)
    (b3 / "danh_ba.csv").write_text("ho_ten,sdt\nLê Bảo Ngọc,389112233\n", encoding="utf-8")
    (b3 / "lich_thue.csv").write_text(
        "ma_do,sdt,ten_khach,ngay_nhan,tien_thue\n"
        "AO01,0389112233,,2026-05-02,1200000\n"
        "AO01,0911223344,Đỗ Minh Quân,2026-05-04,1200000\n",
        encoding="utf-8",
    )
    ws3 = load_business_workspace(b3, cache_dir=c3, force_rebuild=True)
    k3 = build_workspace_knowledge(ws3)
    q_a3 = "Từ 01/05/2026 đến 07/05/2026 có những khách nào thuê mã AO01?"
    sql_a3 = (
        "SELECT COALESCE(db.ho_ten, lt.ten_khach, lt.sdt) AS khach_hang, ROUND_HALF_UP(SUM(lt.tien_thue), 0) AS tien_thue\n"
        "FROM lich_thue lt\n"
        "LEFT JOIN danh_ba db ON lt.sdt = db.sdt\n"
        "WHERE lt.ma_do = 'AO01' AND lt.ngay_nhan BETWEEN '2026-05-01' AND '2026-05-07'\n"
        "GROUP BY khach_hang\n"
        "ORDER BY tien_thue DESC, khach_hang ASC;"
    )
    r3 = execute_sql_safe(ws3.open_connection, sql_a3, valid_tables=k3.valid_tables)
    assert r3.ok and r3.row_count == 2
    _emit_sft("ARCH3_PHONE_LEFT_JOIN", "phone_left_join", "arch_thuedo", q_a3, "2026-05-10", k3, {"status": "ok", "sql": sql_a3})

    # Archetype 4: Compound cell amounts -> Python Sandbox
    b4 = tmp_dir / "arch_compound"
    c4 = tmp_dir / "cache_compound"
    b4.mkdir(parents=True, exist_ok=True)
    (b4 / "so_chi.csv").write_text(
        "ngay,hang_muc,so_tien\n"
        "2026-06-01,Đi chợ + Ăn trưa,320k + 150000\n"
        '2026-06-02,Tiền điện,"1,2tr"\n'
        "2026-06-03,Văn phòng phẩm,450k\n",
        encoding="utf-8",
    )
    ws4 = load_business_workspace(b4, cache_dir=c4, force_rebuild=True)
    k4 = build_workspace_knowledge(ws4)
    q_a4 = "Tổng tiền chi trong tháng 6/2026 là bao nhiêu?"
    py_a4 = (
        "df = query_df(\"SELECT so_tien FROM so_chi WHERE substr(ngay, 1, 7) = '2026-06'\")\n"
        "tot = sum(sum_compound_vn_nums(v) or 0.0 for v in df['so_tien'])\n"
        "result = round_half_up(tot, 0)"
    )
    r4 = execute_python_safe(ws4.open_connection, py_a4, as_of_date="2026-06-15", valid_tables=k4.valid_tables)
    assert r4.ok and r4.rows and int(r4.rows[0][0]) == 2120000
    sp, up = _emit_sft("ARCH4_COMPOUND_PYTHON", "python_sandbox_compound", "arch_compound", q_a4, "2026-06-15", k4, {"status": "ok", "python": py_a4})
    dpo_rows.append({
        "id": "DPO_ARCH4_PYTHON_VS_SQL",
        "category": "python_sandbox_preference",
        "business_id": "arch_compound",
        "system": sp,
        "prompt": up,
        "chosen": json.dumps({"status": "ok", "python": py_a4}, ensure_ascii=False),
        "rejected": json.dumps({"status": "ok", "sql": "SELECT SUM(CAST(so_tien AS REAL)) FROM so_chi WHERE substr(ngay, 1, 7) = '2026-06';"}, ensure_ascii=False),
    })

    # Archetype 5: Wide attendance matrix & FIFO debt -> Python Sandbox
    b5 = tmp_dir / "arch_wide"
    c5 = tmp_dir / "cache_wide"
    b5.mkdir(parents=True, exist_ok=True)
    (b5 / "cham_cong.csv").write_text(
        "nhan_vien,ngay_1,ngay_2,ngay_3,ngay_4,ngay_5\n"
        "Nguyễn An,1,1,0.5,1,0\n"
        "Trần Bình,1,0,1,1,1\n",
        encoding="utf-8",
    )
    ws5 = load_business_workspace(b5, cache_dir=c5, force_rebuild=True)
    k5 = build_workspace_knowledge(ws5)
    q_a5 = "Ai có tổng số ngày công cao nhất và tổng công là bao nhiêu?"
    py_a5 = (
        "df = query_df(\"SELECT * FROM cham_cong\")\n"
        "day_cols = [c for c in df.columns if c.startswith('ngay_')]\n"
        "df['tong_cong'] = df[day_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1)\n"
        "df = df[['nhan_vien', 'tong_cong']].sort_values(['tong_cong', 'nhan_vien'], ascending=[False, True])\n"
        "result = df"
    )
    r5 = execute_python_safe(ws5.open_connection, py_a5, as_of_date="2026-06-30", valid_tables=k5.valid_tables)
    assert r5.ok and r5.row_count == 2
    _emit_sft("ARCH5_WIDE_MATRIX_PY", "python_sandbox_wide", "arch_wide", q_a5, "2026-06-30", k5, {"status": "ok", "python": py_a5})

    # Pure out-of-scope When2Call examples
    for oos_idx, oos_q in enumerate([
        "Thời tiết hôm nay ở cửa hàng có mưa không?",
        "Giá vàng SJC ngày mai tăng hay giảm?",
        "So sánh doanh thu của shop với đối thủ cùng phố giúp mình.",
    ], 1):
        oos_reason = check_preflight_unanswerable(oos_q, "2026-06-15", k4, classify_expected_type(oos_q)) or "Câu hỏi nằm ngoài phạm vi dữ liệu kinh doanh nội bộ của shop."
        sp, up = _emit_sft(f"ARCH_OOS_{oos_idx}", "unanswerable_oos", "arch_compound", oos_q, "2026-06-15", k4, {"status": "unanswerable", "reason": oos_reason})
        dpo_rows.append({
            "id": f"DPO_OOS_{oos_idx}",
            "category": "unanswerable_vs_hallucination",
            "business_id": "arch_compound",
            "system": sp,
            "prompt": up,
            "chosen": json.dumps({"status": "unanswerable", "reason": oos_reason}, ensure_ascii=False),
            "rejected": json.dumps({"status": "ok", "sql": "SELECT COUNT(*) FROM so_chi;"}, ensure_ascii=False),
        })

    return sft_rows, dpo_rows


# ---------------------------------------------------------------------------
# Main Stage 4 Dataset Builder Entry Point
# ---------------------------------------------------------------------------


def _mine_synthetic_shop_queries(
    ws: BusinessWorkspace,
    know: WorkspaceKnowledge,
    roles: ShopSchemaRoles,
) -> List[Tuple[str, str, str]]:
    """Return programmatic diverse (question, sql, category) pairs grounded directly in this shop's schema."""
    out: List[Tuple[str, str, str]] = []
    if not roles.sales_table or not roles.amount_col:
        return out
    amt_c = roles.amount_col
    as_of = know.data_max_date or "2026-09-01"
    from_s, wheres_s, d_expr, oid_e = _build_sales_from_and_where(roles, None, include_valid_status=True)
    w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""

    # 1. Extreme comparison + Benchmark above-average specs (rich CTEs)
    q_ext = "Mặt hàng nào có doanh thu cao nhất và thấp nhất trong cửa hàng, chênh lệch bao nhiêu?"
    an_ext = classify_expected_type(q_ext)
    sp_ext = build_extreme_comparison_sql_spec(q_ext, know, an_ext)
    if sp_ext and sp_ext.get("suggested_sql"):
        out.append((q_ext, sp_ext["suggested_sql"], "syn_extreme_pair"))

    q_avg = "Những mặt hàng nào có doanh thu vượt trên mức trung bình của các mặt hàng?"
    an_avg = classify_expected_type(q_avg)
    sp_avg = build_benchmark_average_entity_sql_spec(q_avg, know, an_avg)
    if sp_avg and sp_avg.get("suggested_sql"):
        out.append((q_avg, sp_avg["suggested_sql"], "syn_benchmark_avg"))

    # 2. Group breakdown (%) + Single-category share (%)
    if roles.cat_col or roles.channel_col:
        grp_col = roles.channel_col or roles.cat_col
        grp_tbl = roles.sales_table if (roles.channel_col or not roles.cat_table) else roles.cat_table
        cat_vals = [v for v, _ in (know.categorical_values.get(f"{grp_tbl}.{grp_col}", []) or []) if norm_vn(v) not in ("", "none", "null")][:2]
        from_c, wheres_c, _, _ = _build_sales_from_and_where(roles, None, include_valid_status=True, need_item_join=bool(roles.cat_table and grp_col == roles.cat_col))
        w_c = f"\nWHERE {' AND '.join(wheres_c)}" if wheres_c else ""
        pf = "sp." if (roles.cat_table and grp_col == roles.cat_col) else "f."
        if cat_vals:
            v0 = cat_vals[0]
            noun = "kênh" if grp_col == roles.channel_col else "nhóm"
            q_pct = f"Trong toàn kỳ dữ liệu, {noun} {v0} chiếm bao nhiêu % tổng doanh thu?"
            sql_pct = (
                f"SELECT ROUND_HALF_UP(\n"
                f"  SUM(CASE WHEN NORM_VN({pf}{_qident(grp_col)}) = NORM_VN({v0!r}) THEN f.{_qident(amt_c)} ELSE 0 END) * 100.0 /\n"
                f"  NULLIF(SUM(f.{_qident(amt_c)}), 0),\n"
                f"  2\n) AS ty_trong_pct\nFROM {from_c}{w_c};"
            )
            out.append((q_pct, sql_pct, "syn_single_group_pct"))
        out.append((
            f"Tính tỷ trọng doanh thu (%) theo từng {'kênh bán' if grp_col == roles.channel_col else 'danh mục'}?",
            f"SELECT {pf}{_qident(grp_col)} AS nhom, ROUND_HALF_UP(SUM(f.{_qident(amt_c)}) * 100.0 / NULLIF(SUM(SUM(f.{_qident(amt_c)})) OVER (), 0), 2) AS ty_trong_pct\n"
            f"FROM {from_c}{w_c}\nGROUP BY {pf}{_qident(grp_col)}\nORDER BY ty_trong_pct DESC;",
            "syn_group_share_over",
        ))

    # 3. Teencode variant of monthly revenue / AOV
    if d_expr and len(as_of) >= 7:
        ym = as_of[:7]
        m_i, y_i = int(ym[5:7]), int(ym[:4])
        from_m, wheres_m, _, _ = _build_sales_from_and_where(roles, (f"{ym}-01", as_of), include_valid_status=True)
        w_m = f"\nWHERE {' AND '.join(wheres_m)}" if wheres_m else ""
        out.append((
            f"thang {m_i}/{y_i} dthu tong cong la bnhiu vay",
            f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS doanh_thu\nFROM {from_m}{w_m};",
            "syn_teencode_rev",
        ))
        if oid_e:
            out.append((
                f"Giá trị trung bình mỗi đơn hàng trong tháng {m_i:02d}/{y_i} là bao nhiêu?",
                f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}) * 1.0 / NULLIF(COUNT(DISTINCT {oid_e}), 0), 0) AS aov\nFROM {from_m}{w_m};",
                "syn_aov_distinct",
            ))

    # 4. Ranking ordinal OFFSET
    if roles.item_name_col or roles.item_table:
        from_i, wheres_i, _, _ = _build_sales_from_and_where(roles, None, include_valid_status=True, need_item_join=bool(roles.item_table))
        ic_e = f"sp.{_qident(roles.item_name_col)}" if roles.item_table else f"f.{_qident(roles.item_name_col)}"
        w_i = f"\nWHERE {' AND '.join(wheres_i)}" if wheres_i else ""
        out.append((
            "Mặt hàng nào có doanh thu cao thứ 2 của cửa hàng?",
            f"SELECT {ic_e} AS ten_hang, ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS doanh_thu\n"
            f"FROM {from_i}{w_i}\nGROUP BY {ic_e}\nORDER BY doanh_thu DESC, {ic_e} ASC\nLIMIT 1 OFFSET 1;",
            "syn_ordinal_offset",
        ))

    return out


def _create_programmatic_synthetic_shops(root_dir: pathlib.Path) -> List[Tuple[str, pathlib.Path]]:
    """Create 3 self-contained domain-diverse synthetic SME workspaces for 100% clean SFT/DPO synthesis."""
    shops: List[Tuple[str, pathlib.Path]] = []

    # 1. syn_fnb: Multi-table F&B cafe with header/detail join + categories + cancellations
    s1 = root_dir / "syn_fnb"
    s1.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(s1 / "fnb.sqlite") as conn:
        conn.execute("CREATE TABLE san_pham (ma_sp TEXT, ten_sp TEXT, nhom_hang TEXT, gia_niem_yet REAL)")
        conn.executemany(
            "INSERT INTO san_pham VALUES (?, ?, ?, ?)",
            [
                ("SP01", "Cà phê sữa đá", "Cà phê", 35000),
                ("SP02", "Trà đào cam sả", "Trà trái cây", 45000),
                ("SP03", "Matcha latte", "Trà sữa", 55000),
                ("SP04", "Bánh sừng bò", "Bánh ngọt", 30000),
            ],
        )
        conn.execute("CREATE TABLE hoa_don (ma_hd TEXT, ngay_ban TEXT, kenh_ban TEXT, trang_thai TEXT)")
        conn.executemany(
            "INSERT INTO hoa_don VALUES (?, ?, ?, ?)",
            [
                ("HD001", "2026-04-02", "Tại quầy", "Hoàn thành"),
                ("HD002", "2026-04-05", "App giao hàng", "Hoàn thành"),
                ("HD003", "2026-04-10", "Tại quầy", "Đã hủy"),
                ("HD004", "2026-05-03", "Tại quầy", "Hoàn thành"),
                ("HD005", "2026-05-08", "App giao hàng", "Hoàn thành"),
                ("HD006", "2026-05-12", "Tại quầy", "Đã hoàn"),
            ],
        )
        conn.execute("CREATE TABLE chi_tiet_hd (ma_hd TEXT, ma_sp TEXT, so_luong INTEGER, thanh_tien REAL)")
        conn.executemany(
            "INSERT INTO chi_tiet_hd VALUES (?, ?, ?, ?)",
            [
                ("HD001", "SP01", 2, 70000),
                ("HD001", "SP04", 1, 30000),
                ("HD002", "SP02", 3, 135000),
                ("HD003", "SP03", 2, 110000),
                ("HD004", "SP03", 4, 220000),
                ("HD005", "SP01", 5, 175000),
                ("HD005", "SP02", 2, 90000),
                ("HD006", "SP04", 2, 60000),
            ],
        )
        conn.commit()
    shops.append(("syn_fnb", s1))

    # 2. syn_retail: Minimart CSV with status, channels, units & customers
    s2 = root_dir / "syn_retail"
    s2.mkdir(parents=True, exist_ok=True)
    (s2 / "ban_hang.csv").write_text(
        "ma_don,ngay,ten_hang,nhom_hang,so_luong,don_gia,thanh_tien,kenh_ban,trang_thai\n"
        "R01,2026-03-01,Gạo ST25 5kg,Lương thực,2,185000,370000,Tại cửa hàng,Hoàn tất\n"
        "R02,2026-03-04,Dầu ăn Neptune 1L,Gia vị,4,55000,220000,Online,Hoàn tất\n"
        "R03,2026-03-10,Nước mắm Phú Quốc,Gia vị,3,48000,144000,Tại cửa hàng,Đã hủy\n"
        "R04,2026-04-02,Sữa tươi Vinamilk 1L,Sữa,6,38000,228000,Online,Hoàn tất\n"
        "R05,2026-04-09,Gạo ST25 5kg,Lương thực,3,185000,555000,Tại cửa hàng,Hoàn tất\n"
        "R06,2026-04-15,Mì gói Hảo Hảo thùng,Thực phẩm khô,5,118000,590000,Tại cửa hàng,Hoàn tất\n",
        encoding="utf-8",
    )
    shops.append(("syn_retail", s2))

    # 3. syn_fashion: Boutique shop with sales + imports + returns
    s3 = root_dir / "syn_fashion"
    s3.mkdir(parents=True, exist_ok=True)
    (s3 / "don_hang.csv").write_text(
        "ma_hoa_don,ngay_tao,ten_sp,danh_muc,so_luong,thanh_tien,kenh,tinh_trang\n"
        "F01,2026-02-05,Áo sơ mi linen,Áo,2,420000,Shopee,Thành công\n"
        "F02,2026-02-14,Quần tây ống suông,Quần,1,520000,Tại shop,Thành công\n"
        "F03,2026-02-20,Váy midi hoa nhí,Váy,1,680000,Shopee,Đã hủy đơn\n"
        "F04,2026-03-06,Áo thun cotton,Áo,4,250000,Tại shop,Thành công\n"
        "F05,2026-03-18,Quần tây ống suông,Quần,2,1040000,Shopee,Thành công\n"
        "F06,2026-03-25,Áo sơ mi linen,Áo,1,420000,Tại shop,Thành công\n",
        encoding="utf-8",
    )
    (s3 / "phieu_nhap.csv").write_text(
        "ma_phieu,ngay_nhap,ten_sp,so_luong_nhap,thanh_tien\n"
        "PN01,2026-02-01,Áo sơ mi linen,20,3800000\n"
        "PN02,2026-02-01,Quần tây ống suông,15,4200000\n"
        "PN03,2026-03-01,Áo thun cotton,30,3600000\n",
        encoding="utf-8",
    )
    shops.append(("syn_fashion", s3))

    return shops


def _build_extra_shop_queries(
    know: WorkspaceKnowledge,
    roles: ShopSchemaRoles,
) -> List[Tuple[str, str, str]]:
    """Generate additional clean SQL trajectories (overall totals, order counts, best dates, cancel counts)."""
    out: List[Tuple[str, str, str]] = []
    if not roles.sales_table or not roles.amount_col:
        return out
    amt_c = roles.amount_col
    from_s, wheres_s, d_expr, oid_e = _build_sales_from_and_where(roles, None, include_valid_status=True)
    w_s = f"\nWHERE {' AND '.join(wheres_s)}" if wheres_s else ""
    out.append((
        "Tổng doanh thu hợp lệ trong toàn bộ dữ liệu là bao nhiêu?",
        f"SELECT ROUND_HALF_UP(SUM(f.{_qident(amt_c)}), 0) AS tong_doanh_thu\nFROM {from_s}{w_s};",
        "syn_total_revenue",
    ))
    cnt_e = f"COUNT(DISTINCT {oid_e})" if oid_e else "COUNT(*)"
    out.append((
        "Cửa hàng có tất cả bao nhiêu đơn hàng hợp lệ?",
        f"SELECT {cnt_e} AS tong_so_don\nFROM {from_s}{w_s};",
        "syn_order_count",
    ))
    if d_expr:
        out.append((
            "Ngày nào cửa hàng đạt doanh thu cao nhất?",
            f"SELECT substr({d_expr}, 1, 10) AS ngay\nFROM {from_s}{w_s}\nGROUP BY ngay\nORDER BY SUM(f.{_qident(amt_c)}) DESC\nLIMIT 1;",
            "syn_best_day",
        ))
        out.append((
            "Tháng nào doanh thu cao nhất?",
            f"SELECT strftime('%Y-%m', {d_expr}) AS thang\nFROM {from_s}{w_s}\nGROUP BY thang\nORDER BY SUM(f.{_qident(amt_c)}) DESC\nLIMIT 1;",
            "syn_best_month",
        ))
    if roles.cancelled_values:
        base_tbl = roles.sales_header_table or roles.sales_table
        sc = roles.sales_header_status_col or roles.sales_status_col
        oid_c = roles.sales_header_key or roles.sales_order_id_col
        if sc:
            cvals = ", ".join(repr(v) for v in roles.cancelled_values)
            ce = f"COUNT(DISTINCT {_qident(oid_c)})" if oid_c else "COUNT(*)"
            out.append((
                "Có bao nhiêu đơn hàng bị hủy trong toàn kỳ?",
                f"SELECT {ce} AS so_don_huy\nFROM {_qident(base_tbl)}\nWHERE {sc} IN ({cvals});",
                "syn_cancel_count",
            ))
    if roles.import_table and roles.import_amt_col:
        iw = f"\nWHERE {roles.import_valid_filter}" if roles.import_valid_filter else ""
        out.append((
            "Tổng giá trị nhập hàng là bao nhiêu?",
            f"SELECT ROUND_HALF_UP(SUM({_qident(roles.import_amt_col)}), 0) AS tong_nhap\nFROM {_qident(roles.import_table)}{iw};",
            "syn_import_total",
        ))
    return out


def build_synthetic_stage4_datasets(
    out_dir: str | pathlib.Path,
    *,
    cache_dir: str | pathlib.Path = "/tmp/datamate_stage4_ws_cache",
    eval_ratio: float = 0.1,
    seed: int = 2026,
) -> Dict[str, Any]:
    """Build 100% pure-synthetic SME SFT + When2Call DPO archives using Veraxus public demos and archetypes."""
    t0 = time.time()
    rng = random.Random(seed)
    odir = pathlib.Path(out_dir)
    odir.mkdir(parents=True, exist_ok=True)
    cache_root = pathlib.Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)

    stub_agent = DataMateAgent(
        backend=MockLLMBackend(lambda _p, _s: "{}"),
        config=AgentConfig(enable_python_sandbox=True, sql_max_tokens=640),
    )

    sft_pool: List[Dict[str, Any]] = []
    dpo_pool: List[Dict[str, Any]] = []
    stats = collections.Counter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        arch_sft, arch_dpo = _build_chaos_archetype_records(stub_agent, tmp_path / "arch")
        sft_pool.extend(arch_sft)
        dpo_pool.extend(arch_dpo)
        stats["archetype_sft"] += len(arch_sft)
        stats["archetype_dpo"] += len(arch_dpo)

        demo_root = pathlib.Path(__file__).resolve().parents[1] / "data" / "demo_businesses"
        shop_sources: List[Tuple[str, pathlib.Path]] = []
        if demo_root.exists():
            for d in sorted(demo_root.iterdir()):
                if d.is_dir():
                    shop_sources.append((f"demo_{d.name}", d))
        shop_sources.extend(_create_programmatic_synthetic_shops(tmp_path / "syn_shops"))

        for bid, sdir in shop_sources:
            ws = load_business_workspace(sdir, cache_dir=cache_root / bid, force_rebuild=True)
            know = build_workspace_knowledge(ws)
            roles = discover_shop_roles(know)
            dt_cols = tuple(getattr(know, "datetime_columns", ()) or ())
            as_of = know.data_max_date or "2026-09-01"

            candidates = _mine_synthetic_shop_queries(ws, know, roles) + _build_extra_shop_queries(know, roles)
            seen_q: Set[str] = set()
            for q_idx, (sq, ssql, scat) in enumerate(candidates):
                if sq in seen_q:
                    continue
                seen_q.add(sq)
                san = classify_expected_type(sq)
                sw, sts, sb, sps = extract_temporal_context(sq, as_of, None)
                san.temporal_windows, san.temporal_summary, san.bounded_period, san.prior_needed_start = sw, sts, sb, sps
                sents = ground_query_entities(sq, know, max_matches=8)
                sres = execute_sql_safe(ws.open_connection, ssql, valid_tables=know.valid_tables, datetime_columns=dt_cols, max_rows=200, timeout_seconds=1.5)
                if not sres.ok or sres.row_count < 1:
                    continue
                sok, _, _ = verify_sql_semantics(ssql, sres, sq, know, san, entity_matches=sents)
                if not sok:
                    continue

                ssys, susr = stub_agent._build_sql_prompt(
                    question=sq, as_of_date=as_of, knowledge=know, analysis=san, temporal_summary=sts, entity_matches=sents, prefer_python=False
                )
                chosen_ok = json.dumps({"status": "ok", "sql": ssql.strip()}, ensure_ascii=False)
                sft_pool.append({
                    "id": f"SYN_{bid}_{q_idx}",
                    "category": scat,
                    "business_id": bid,
                    "messages": [
                        {"role": "system", "content": ssys},
                        {"role": "user", "content": susr},
                        {"role": "assistant", "content": chosen_ok},
                    ],
                })
                stats["synthetic_shop_sft"] += 1

                # Add 2 Hammer-masked schema variants for cross-schema generalization
                for m_pass, m_seed in enumerate((seed + q_idx, seed + 100 + q_idx)):
                    masked_out = mask_workspace_and_sql(
                        ws, ssql, random.Random(m_seed), tmp_path / "masked", tag=f"{bid}_{q_idx}_{m_pass}"
                    )
                    if masked_out is not None:
                        _, m_know, m_sql, _ = masked_out
                        m_ents = ground_query_entities(sq, m_know, max_matches=8)
                        m_probes = run_deterministic_probes(sq, m_know, m_ents)
                        msys, musr = stub_agent._build_sql_prompt(
                            question=sq, as_of_date=as_of, knowledge=m_know, analysis=san, temporal_summary=sts, entity_matches=m_ents, probe_context=m_probes, prefer_python=False
                        )
                        sft_pool.append({
                            "id": f"MASK_{bid}_{q_idx}_{m_pass}",
                            "category": f"masked_{scat}",
                            "business_id": bid,
                            "messages": [
                                {"role": "system", "content": msys},
                                {"role": "user", "content": musr},
                                {"role": "assistant", "content": json.dumps({"status": "ok", "sql": m_sql.strip()}, ensure_ascii=False)},
                            ],
                        })
                        stats["hammer_masked_sft"] += 1

                # Pair into When2Call DPO guard
                if roles.valid_filter and roles.valid_filter in ssql:
                    buggy = ssql.replace(roles.valid_filter, "1=1", 1)
                    dpo_cat = "status_filter_guard"
                elif "NORM_VN(" in ssql:
                    buggy = re.sub(r"NORM_VN\(([^)]+)\)", r"\1", ssql)
                    dpo_cat = "vn_norm_guard"
                else:
                    buggy = None
                    dpo_cat = "join_vs_false_abstain"
                rejected_str = (
                    json.dumps({"status": "ok", "sql": buggy}, ensure_ascii=False)
                    if buggy and buggy != ssql
                    else json.dumps({"status": "unanswerable", "reason": "Không tìm thấy cột phù hợp trong bảng dữ liệu."}, ensure_ascii=False)
                )
                dpo_pool.append({
                    "id": f"DPO_{bid}_{q_idx}",
                    "category": dpo_cat,
                    "business_id": bid,
                    "system": ssys,
                    "prompt": susr,
                    "chosen": chosen_ok,
                    "rejected": rejected_str,
                })
                stats[f"dpo_{dpo_cat}"] += 1

            # Out-of-scope unanswerable calibration for each shop
            for u_idx, uq in enumerate((
                "Hôm nay trời có mưa không?",
                "Giá cổ phiếu VNM hôm nay là bao nhiêu?",
                "Chi phí chạy quảng cáo TikTok tháng này là bao nhiêu?",
            )):
                uan = classify_expected_type(uq)
                preflight = check_preflight_unanswerable(uq, as_of, know, uan)
                ureason = _derive_unanswerable_reason(uq, know, uan, preflight)
                usys, uusr = stub_agent._build_sql_prompt(
                    question=uq, as_of_date=as_of, knowledge=know, analysis=uan, temporal_summary="", entity_matches=[], prefer_python=False
                )
                uchosen = json.dumps({"status": "unanswerable", "reason": ureason}, ensure_ascii=False)
                sft_pool.append({
                    "id": f"SYN_UNANS_{bid}_{u_idx}",
                    "category": "unanswerable_oos",
                    "business_id": bid,
                    "messages": [
                        {"role": "system", "content": usys},
                        {"role": "user", "content": uusr},
                        {"role": "assistant", "content": uchosen},
                    ],
                })
                bad_u_sql = f"SELECT COUNT(*) FROM {_qident(roles.sales_table or know.valid_tables[0])};"
                dpo_pool.append({
                    "id": f"DPO_SYN_UNANS_{bid}_{u_idx}",
                    "category": "unanswerable_vs_hallucination",
                    "business_id": bid,
                    "system": usys,
                    "prompt": uusr,
                    "chosen": uchosen,
                    "rejected": json.dumps({"status": "ok", "sql": bad_u_sql}, ensure_ascii=False),
                })
                stats["synthetic_unanswerable_sft"] += 1

    rng.shuffle(sft_pool)
    rng.shuffle(dpo_pool)
    n_eval = max(12, int(round(len(sft_pool) * eval_ratio)))
    sft_eval = sft_pool[:n_eval]
    sft_train = sft_pool[n_eval:]

    def _write_gz(stem: str, recs: Sequence[Dict[str, Any]]) -> Tuple[int, int]:
        gz_p = odir / f"{stem}.jsonl.gz"
        with gzip.open(gz_p, "wt", encoding="utf-8", compresslevel=9) as gfh:
            for rec in recs:
                gfh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return len(recs), gz_p.stat().st_size

    n_tr, sz_tr = _write_gz("veraxus_sft_train", sft_train)
    n_ev, sz_ev = _write_gz("veraxus_sft_eval", sft_eval)
    n_dp, sz_dp = _write_gz("veraxus_dpo_when2call", dpo_pool)
    max_chars = max(sum(len(m["content"]) for m in r["messages"]) for r in sft_pool) if sft_pool else 0

    manifest = {
        "pipeline": "Veraxus Stage 4 (100% Synthetic SME + Public Demo + Hammer Masking + When2Call DPO)",
        "data_source": "100% synthetic Veraxus SME benchmarks",
        "train_shops_count": len(shop_sources) + 5,
        "val_leakage_count": 0,
        "sft_train_count": n_tr,
        "sft_eval_count": n_ev,
        "dpo_count": n_dp,
        "sft_category_counts": dict(collections.Counter(r["category"] for r in sft_pool)),
        "dpo_category_counts": dict(collections.Counter(r["category"] for r in dpo_pool)),
        "mining_stats": dict(stats),
        "max_sample_chars": max_chars,
        "gz_sizes_bytes": {
            "veraxus_sft_train.jsonl.gz": sz_tr,
            "veraxus_sft_eval.jsonl.gz": sz_ev,
            "veraxus_dpo_when2call.jsonl.gz": sz_dp,
        },
        "elapsed_seconds": round(time.time() - t0, 2),
    }
    (odir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_stage4_datasets(
    train_dir: Optional[str | pathlib.Path],
    out_dir: str | pathlib.Path,
    *,
    cache_dir: str | pathlib.Path = "/tmp/datamate_stage4_ws_cache",
    max_sft_total: int = 1600,
    mask_ratio: float = 0.25,
    eval_ratio: float = 0.08,
    seed: int = 2026,
) -> Dict[str, Any]:
    """
    Build compressed ``veraxus_sft_train.jsonl.gz``, ``veraxus_sft_eval.jsonl.gz``,
    ``veraxus_dpo_when2call.jsonl.gz`` and ``manifest.json``.

    Falls back automatically to 100% pure-synthetic SME synthesis when ``train_dir`` is omitted
    or does not exist locally.
    """
    if not train_dir or not pathlib.Path(train_dir).exists():
        return build_synthetic_stage4_datasets(
            out_dir,
            cache_dir=cache_dir,
            eval_ratio=eval_ratio,
            seed=seed,
        )
    t0 = time.time()
    rng = random.Random(seed)
    tdir = pathlib.Path(train_dir)
    odir = pathlib.Path(out_dir)
    odir.mkdir(parents=True, exist_ok=True)
    cache_root = pathlib.Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)

    cal_path = tdir / "calendar.csv"
    lunar_cal = SolarLunarCalendar(cal_path) if cal_path.exists() else None
    questions, answers_by_id = load_split_dataset(tdir, split="train")

    # Strict anti-leakage assertion
    for q in questions:
        bid = q.get("business_id", "")
        if bid in VAL_BUSINESS_SET:
            raise AssertionError(f"Data leakage guard triggered: validation business {bid} present in train split!")

    stub_agent = DataMateAgent(
        backend=MockLLMBackend(lambda _p, _s: "{}"),
        config=AgentConfig(enable_python_sandbox=True, sql_max_tokens=640),
        calendar_path=str(cal_path) if cal_path.exists() else None,
    )

    by_biz: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for q in questions:
        by_biz[q["business_id"]].append(q)

    sft_pool: List[Dict[str, Any]] = []
    dpo_pool: List[Dict[str, Any]] = []
    stats = collections.Counter()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        mask_root = tmp_path / "masked"

        # Add chaos SME archetypes first
        arch_sft, arch_dpo = _build_chaos_archetype_records(stub_agent, tmp_path / "arch")
        sft_pool.extend(arch_sft)
        dpo_pool.extend(arch_dpo)
        stats["archetype_sft"] += len(arch_sft)
        stats["archetype_dpo"] += len(arch_dpo)

        # Mine verified trajectories from the 24 real train shops
        for bid in sorted(by_biz):
            t_shop = time.time()
            bdir = tdir / "data" / bid
            ws = load_business_workspace(bdir, cache_dir=cache_root, lunar_cal=lunar_cal)
            know = build_workspace_knowledge(ws)
            roles = discover_shop_roles(know)
            dt_cols = tuple(getattr(know, "datetime_columns", ()) or ())
            max_tbl_rows = max((tp.row_count for tp in ws.tables.values()), default=0)
            shop_mined = 0

            for q_idx, q in enumerate(by_biz[bid]):
                qid = q["id"]
                ref = answers_by_id.get(qid)
                if not ref:
                    continue
                q_text = q["question"]
                as_of = q.get("as_of_date") or know.data_max_date or "2026-09-01"
                an = classify_expected_type(q_text)
                w, ts, b, ps = extract_temporal_context(q_text, as_of, lunar_cal)
                an.temporal_windows, an.temporal_summary, an.bounded_period, an.prior_needed_start = w, ts, b, ps
                ents = ground_query_entities(q_text, know, max_matches=10)
                probes = run_deterministic_probes(q_text, know, ents) if (max_tbl_rows <= 25000 or q_idx % 12 == 0) else ""
                sys_p, usr_p = stub_agent._build_sql_prompt(
                    question=q_text,
                    as_of_date=as_of,
                    knowledge=know,
                    analysis=an,
                    temporal_summary=ts,
                    entity_matches=ents,
                    probe_context=probes,
                    prefer_python=False,
                )
                preflight_msg = check_preflight_unanswerable(q_text, as_of, know, an)

                if ref.get("type") == "unanswerable":
                    reason = _derive_unanswerable_reason(q_text, know, an, preflight_msg)
                    chosen_json = json.dumps({"status": "unanswerable", "reason": reason}, ensure_ascii=False)
                    sft_pool.append({
                        "id": f"TR_UNANS_{qid}",
                        "category": "unanswerable",
                        "business_id": bid,
                        "messages": [
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": usr_p},
                            {"role": "assistant", "content": chosen_json},
                        ],
                    })
                    bad_sql = (
                        f"SELECT COUNT(*) FROM {_qident(roles.sales_table)};"
                        if roles.sales_table
                        else f"SELECT COUNT(*) FROM {_qident(know.valid_tables[0])};"
                    )
                    dpo_pool.append({
                        "id": f"DPO_UNANS_{qid}",
                        "category": "unanswerable_vs_hallucination",
                        "business_id": bid,
                        "system": sys_p,
                        "prompt": usr_p,
                        "chosen": chosen_json,
                        "rejected": json.dumps({"status": "ok", "sql": bad_sql}, ensure_ascii=False),
                    })
                    stats["train_unanswerable_sft"] += 1
                    stats["train_unanswerable_dpo"] += 1
                    shop_mined += 1
                    continue

                cand_sqls = generate_candidate_sqls_for_question(q_text, know, an, ents, roles)
                matched_sql: Optional[str] = None
                for csql in cand_sqls[:5]:
                    res = execute_sql_safe(
                        ws.open_connection,
                        csql,
                        valid_tables=know.valid_tables,
                        datetime_columns=dt_cols,
                        max_rows=500,
                        timeout_seconds=1.5,
                    )
                    if not res.ok or res.row_count < 1:
                        continue
                    sem_ok, _, _ = verify_sql_semantics(csql, res, q_text, know, an, entity_matches=ents)
                    if not sem_ok:
                        continue
                    pred = format_sql_result(res, an, q_text)
                    if not pred:
                        continue
                    pred_with_id = {"id": qid, **pred}
                    pts, _, _ = score_prediction(pred_with_id, ref)
                    if pts == 1:
                        matched_sql = csql.strip()
                        break

                if not matched_sql:
                    stats["train_unmined"] += 1
                    continue

                stats["train_sql_verified"] += 1
                shop_mined += 1
                chosen_ok = json.dumps({"status": "ok", "sql": matched_sql}, ensure_ascii=False)
                sft_pool.append({
                    "id": f"TR_SQL_{qid}",
                    "category": f"sql_{ref.get('type', 'number')}",
                    "business_id": bid,
                    "messages": [
                        {"role": "system", "content": sys_p},
                        {"role": "user", "content": usr_p},
                        {"role": "assistant", "content": chosen_ok},
                    ],
                })

                if len(dpo_pool) < 550 and q_idx % 2 == 0:
                    if roles.valid_filter and roles.valid_filter in matched_sql:
                        buggy = matched_sql.replace(roles.valid_filter, "1=1", 1)
                        dpo_cat = "status_filter_guard"
                    elif "NORM_VN(" in matched_sql:
                        buggy = re.sub(r"NORM_VN\(([^)]+)\)", r"\1", matched_sql)
                        dpo_cat = "vn_norm_guard"
                    else:
                        buggy = None
                        dpo_cat = "join_vs_false_abstain"
                    rejected_str = (
                        json.dumps({"status": "ok", "sql": buggy}, ensure_ascii=False)
                        if buggy and buggy != matched_sql
                        else json.dumps(
                            {"status": "unanswerable", "reason": "Không tìm thấy cột phù hợp trong bảng dữ liệu."},
                            ensure_ascii=False,
                        )
                    )
                    dpo_pool.append({
                        "id": f"DPO_SQL_{qid}",
                        "category": dpo_cat,
                        "business_id": bid,
                        "system": sys_p,
                        "prompt": usr_p,
                        "chosen": chosen_ok,
                        "rejected": rejected_str,
                    })
                    stats[f"dpo_{dpo_cat}"] += 1

                if rng.random() < mask_ratio and len(sft_pool) < max_sft_total and max_tbl_rows <= 25000:
                    masked_out = mask_workspace_and_sql(
                        ws, matched_sql, rng, mask_root, tag=f"{bid}_{q_idx}"
                    )
                    if masked_out is not None:
                        _, m_know, m_sql, _ = masked_out
                        m_ents = ground_query_entities(q_text, m_know, max_matches=8)
                        m_probes = run_deterministic_probes(q_text, m_know, m_ents)
                        msys, musr = stub_agent._build_sql_prompt(
                            question=q_text,
                            as_of_date=as_of,
                            knowledge=m_know,
                            analysis=an,
                            temporal_summary=ts,
                            entity_matches=m_ents,
                            probe_context=m_probes,
                            prefer_python=False,
                        )
                        sft_pool.append({
                            "id": f"MASK_SQL_{qid}",
                            "category": f"masked_{ref.get('type', 'number')}",
                            "business_id": bid,
                            "messages": [
                                {"role": "system", "content": msys},
                                {"role": "user", "content": musr},
                                {"role": "assistant", "content": json.dumps({"status": "ok", "sql": m_sql}, ensure_ascii=False)},
                            ],
                        })
                        stats["hammer_masked_sft"] += 1

            # Programmatic shop-specific rich trajectories (extreme pairs, AOV, % shares, ordinal, teencode)
            for s_idx, (sq, ssql, scat) in enumerate(_mine_synthetic_shop_queries(ws, know, roles)):
                s_asof = know.data_max_date or "2026-09-01"
                san = classify_expected_type(sq)
                sw, sts, sb, sps = extract_temporal_context(sq, s_asof, lunar_cal)
                san.temporal_windows, san.temporal_summary, san.bounded_period, san.prior_needed_start = sw, sts, sb, sps
                sents = ground_query_entities(sq, know, max_matches=8)
                sres = execute_sql_safe(ws.open_connection, ssql, valid_tables=know.valid_tables, datetime_columns=dt_cols, max_rows=200, timeout_seconds=1.5)
                if not sres.ok or sres.row_count < 1:
                    continue
                sok, _, _ = verify_sql_semantics(ssql, sres, sq, know, san, entity_matches=sents)
                if not sok:
                    continue
                ssys, susr = stub_agent._build_sql_prompt(
                    question=sq, as_of_date=s_asof, knowledge=know, analysis=san, temporal_summary=sts, entity_matches=sents, prefer_python=False
                )
                sft_pool.append({
                    "id": f"SYN_{bid}_{s_idx}",
                    "category": scat,
                    "business_id": bid,
                    "messages": [
                        {"role": "system", "content": ssys},
                        {"role": "user", "content": susr},
                        {"role": "assistant", "content": json.dumps({"status": "ok", "sql": ssql}, ensure_ascii=False)},
                    ],
                })
                stats["synthetic_shop_sft"] += 1

            print(f"  [{bid}] mined={shop_mined} total_sft={len(sft_pool)} total_dpo={len(dpo_pool)} ({time.time()-t_shop:.2f}s)", flush=True)

    # Cap total SFT pool keeping archetypes + all unanswerables + diverse train SQL
    if len(sft_pool) > max_sft_total:
        must_keep = [r for r in sft_pool if r["category"] in ("unanswerable", "multi_period_history", "nickname_fk_join", "optional_directory_left_join", "phone_left_join", "python_sandbox_compound", "python_sandbox_wide", "unanswerable_oos")]
        others = [r for r in sft_pool if r not in must_keep]
        rng.shuffle(others)
        sft_pool = must_keep + others[: max(0, max_sft_total - len(must_keep))]

    rng.shuffle(sft_pool)
    rng.shuffle(dpo_pool)

    n_eval = max(24, int(round(len(sft_pool) * eval_ratio)))
    sft_eval = sft_pool[:n_eval]
    sft_train = sft_pool[n_eval:]

    def _write_pair(stem: str, recs: Sequence[Dict[str, Any]]) -> Tuple[int, int]:
        raw_p = odir / f"{stem}.jsonl"
        gz_p = odir / f"{stem}.jsonl.gz"
        with raw_p.open("w", encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with gzip.open(gz_p, "wt", encoding="utf-8", compresslevel=9) as gfh:
            for rec in recs:
                gfh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return len(recs), gz_p.stat().st_size

    n_tr, sz_tr = _write_pair("veraxus_sft_train", sft_train)
    n_ev, sz_ev = _write_pair("veraxus_sft_eval", sft_eval)
    n_dp, sz_dp = _write_pair("veraxus_dpo_when2call", dpo_pool)

    max_chars = max(
        sum(len(m["content"]) for m in r["messages"]) for r in (sft_train + sft_eval)
    ) if sft_pool else 0

    leakage = sum(1 for r in (sft_train + sft_eval + dpo_pool) if r.get("business_id") in VAL_BUSINESS_SET)
    manifest = {
        "pipeline": "Veraxus Stage 4 (APIGen 3-Tier + Official PA Oracle + Hammer Masking + When2Call DPO)",
        "train_shops_count": len(by_biz),
        "val_leakage_count": leakage,
        "sft_train_count": n_tr,
        "sft_eval_count": n_ev,
        "dpo_count": n_dp,
        "sft_category_counts": dict(collections.Counter(r["category"] for r in sft_train + sft_eval)),
        "dpo_category_counts": dict(collections.Counter(r["category"] for r in dpo_pool)),
        "mining_stats": dict(stats),
        "max_sample_chars": max_chars,
        "gz_sizes_bytes": {
            "veraxus_sft_train.jsonl.gz": sz_tr,
            "veraxus_sft_eval.jsonl.gz": sz_ev,
            "veraxus_dpo_when2call.jsonl.gz": sz_dp,
        },
        "elapsed_seconds": round(time.time() - t0, 2),
    }
    (odir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build Veraxus Stage 4 SFT + DPO datasets")
    parser.add_argument(
        "--train-dir",
        default=None,
        help="Optional local train split directory; omit to build 100%% synthetic SME dataset",
    )
    parser.add_argument("--out-dir", default="training/datasets")
    parser.add_argument("--max-sft", type=int, default=1600)
    parser.add_argument("--mask-ratio", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args(argv)

    manifest = build_stage4_datasets(
        args.train_dir,
        args.out_dir,
        max_sft_total=args.max_sft,
        mask_ratio=args.mask_ratio,
        seed=args.seed,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
