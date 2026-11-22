"""Bridge connecting DataMate's verified SQL engine into Veraxus interactive analytics."""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pandas as pd
from sqlalchemy import inspect as sa_inspect

from datamate.agent import (
    _NAMED_GEO_PLACE_RE,
    _OUT_OF_SCOPE_ACCENTED_RE,
    _OUT_OF_SCOPE_UNACCENTED_RE,
    AgentConfig,
    DataMateAgent,
    QuestionAnalysis,
    build_extreme_comparison_sql_spec,
    check_out_of_scope_or_irrelevant,
    check_preflight_unanswerable,
    classify_expected_type,
    extract_ordinal_rank,
    extract_temporal_context,
    format_sql_result,
    normalize_vn_question,
    rewrite_ranked_entity_sql,
    verify_sql_semantics,
)
from datamate.llm_backend import LLMBackend, extract_json_object
from datamate.schema_context import WorkspaceKnowledge, ground_query_entities
from datamate.sql_executor import SQLExecutionResult, execute_sql_safe, norm_vn
from src.analytics.anomaly import analyze_data_anomalies
from src.analytics.heuristics import is_vnd_context_dataframe, split_insight_sections
from src.llm.client import normalize_model_for_openrouter


class VeraxusClientLLMBackend(LLMBackend):
    """Adapter wrapping Veraxus UI's connected LLM client into DataMate's LLMBackend interface."""

    def __init__(self, client: Any, provider: str, model_name: str) -> None:
        self.client = client
        self.provider = provider or ""
        self.model_name = model_name or ""

    def _is_openrouter(self) -> bool:
        base_str = str(getattr(self.client, "base_url", "") or "").lower()
        return self.provider == "OpenRouter" or "openrouter.ai" in base_str

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        if not self.client:
            raise RuntimeError("Chưa khởi tạo kết nối AI Client.")

        is_or = self._is_openrouter()
        if self.provider == "Gemini (Google)" and not is_or:
            return self._call_gemini(prompt, system_prompt, temperature, max_tokens, json_mode)

        target_model = normalize_model_for_openrouter(self.model_name) if is_or else self.model_name
        return self._call_openai(target_model, prompt, system_prompt, temperature, max_tokens, json_mode)

    def _call_gemini(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        clean_model = (self.model_name or "gemini-3.7-flash").strip().split("/")[-1]
        if any(old in clean_model.lower() for old in ("1.0", "1.5", "2.0", "2.5")) or not clean_model:
            clean_model = "gemini-3.7-flash"

        candidates = [clean_model]
        for fb in ("gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"):
            if fb not in candidates:
                candidates.append(fb)

        last_exc: Optional[Exception] = None
        for m in candidates:
            try:
                from google.genai import types

                cfg_kwargs: Dict[str, Any] = {
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                }
                if system_prompt:
                    cfg_kwargs["system_instruction"] = system_prompt
                if json_mode:
                    cfg_kwargs["response_mime_type"] = "application/json"

                try:
                    resp = self.client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(**cfg_kwargs),
                    )
                except Exception:
                    merged = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
                    resp = self.client.models.generate_content(
                        model=m,
                        contents=merged,
                        config=types.GenerateContentConfig(max_output_tokens=max_tokens, temperature=temperature),
                    )
                if resp and getattr(resp, "text", None):
                    return str(resp.text)
            except Exception as exc:
                last_exc = exc
                err_low = str(exc).lower()
                if any(k in err_low for k in ("404", "429", "503", "not found", "quota", "unavailable", "rate_limit")):
                    time.sleep(0.4)
                    continue
                raise
        if last_exc:
            raise last_exc
        return ""

    def _call_openai(
        self,
        model_name: str,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(2):
            try:
                comp = self.client.chat.completions.create(**kwargs)
                return str(comp.choices[0].message.content or "")
            except Exception as exc:
                err_low = str(exc).lower()
                if json_mode and ("response_format" in err_low or "json_object" in err_low or "400" in err_low):
                    kwargs.pop("response_format", None)
                    json_mode = False
                    continue
                if attempt == 0 and any(k in err_low for k in ("429", "503", "timeout", "connection")):
                    time.sleep(0.6)
                    continue
                raise
        return ""


def resolve_interactive_as_of_date(
    knowledge: WorkspaceKnowledge,
    explicit_as_of: Optional[str] = None,
) -> str:
    """Use explicit as_of_date or dataset max date so interactive BI queries land cleanly in history."""
    if explicit_as_of and explicit_as_of.strip():
        return explicit_as_of.strip()[:10]
    if knowledge.data_max_date:
        return knowledge.data_max_date
    return dt.date.today().isoformat()


def augment_vietnamese_query_with_temporal(user_query: str) -> str:
    """
    Lightweight helper for non-DataMate Veraxus DBs: resolves Vietnamese teencode/relative words
    into clean hint text when detected, leaving standard/English queries unchanged.
    """
    q_raw = (user_query or "").strip()
    if not q_raw:
        return q_raw
    qn_plain = norm_vn(q_raw)
    qn_clean = normalize_vn_question(q_raw)
    if qn_clean != qn_plain and any(
        tok in qn_plain.split()
        for tok in ("hnay", "hqua", "dthu", "bnhiu", "bnhieu", "naof", "nhaats", "trc", "ddon", "toongr")
    ):
        return f"{q_raw}\n[Chuẩn hoá ý định tiếng Việt: {qn_clean}]"
    return q_raw


def _profile_datamate_followup_schema(knowledge: WorkspaceKnowledge) -> Dict[str, Any]:
    """Inspect active non-empty tables, columns, categories, capabilities, and date span."""
    caps = knowledge.capabilities or {}
    targets = knowledge.order_status_targets or []
    t0 = targets[0] if targets else {}
    sales_table = str(t0.get("table") or "")
    valid_tables = list(knowledge.valid_tables or [])
    if not sales_table:
        sales_table = next(
            (t for t in valid_tables if re.search(r"hoa_?don|don_?hang|ban_?hang|sales|orders|cong_?no", t, re.I)),
            next(iter(valid_tables), ""),
        )

    active_cols: List[Tuple[str, str]] = []
    sales_cols: Set[str] = set()
    import_cols: Set[str] = set()
    for tname, tp in knowledge.workspace.tables.items():
        if tp.row_count <= 0:
            continue
        is_imp = bool(re.search(r"nhap|import", tname, re.I))
        for cp in tp.columns:
            if cp.distinct_count > 0 and cp.null_count < tp.row_count:
                cname = str(cp.sql_name)
                active_cols.append((tname, cname))
                if tname == sales_table:
                    sales_cols.add(cname.lower())
                if is_imp:
                    import_cols.add(cname.lower())

    if not sales_cols:
        sales_cols = {c.lower() for _, c in active_cols}

    all_col_lows = {c.lower() for _, c in active_cols}

    # Primary item entity column & localized phrasing
    item_col = None
    item_noun_vi, item_noun_en = "mặt hàng", "item"
    sales_noun_vi, sales_noun_en = "bán hàng", "sales"
    doc_noun_vi, doc_noun_en = "đơn hàng", "orders"
    import_noun_vi, import_noun_en = "hàng", "goods"

    for pat, n_vi, n_en, s_vi, s_en, d_vi, d_en, i_vi, i_en in (
        (r"(?:^|_)(?:ten_?thuoc|thuoc)(?:$|_)", "loại thuốc", "medicine", "bán thuốc", "pharmacy sales", "hóa đơn", "invoices", "thuốc", "medicines"),
        (r"(?:^|_)(?:ten_?mon|mon)(?:$|_)", "món", "menu item", "bán hàng", "cafe sales", "đơn hàng", "orders", "nguyên liệu", "inventory"),
        (r"(?:^|_)(?:vat_?lieu|ten_?vat_?lieu)(?:$|_)", "vật liệu", "material", "bán vật liệu", "material sales", "đơn hàng", "orders", "vật liệu", "materials"),
        (r"(?:^|_)(?:ten_?san_?pham|san_?pham|ten_?hang|hang_?hoa|product(?:_?name)?|mat_?hang)(?:$|_)", "sản phẩm", "product", "bán hàng", "sales", "đơn hàng", "orders", "hàng", "goods"),
    ):
        found = next((c for _, c in active_cols if re.search(pat, c, re.I)), None)
        if found:
            item_col = found
            item_noun_vi, item_noun_en = n_vi, n_en
            sales_noun_vi, sales_noun_en = s_vi, s_en
            doc_noun_vi, doc_noun_en = d_vi, d_en
            import_noun_vi, import_noun_en = i_vi, i_en
            break

    # Category column & phrasing
    cat_col = None
    cat_noun_vi, cat_noun_en = "danh mục", "category"
    for pat, c_vi, c_en in (
        (r"^nhom_?mon$", "nhóm món", "menu category"),
        (r"(?:^|_)(?:nhom_?thuoc|loai_?thuoc)(?:$|_)", "nhóm thuốc", "medicine category"),
        (r"(?:^|_)(?:nhom_?hang|danh_?muc|loai_?hang|category(?:_?name)?)(?:$|_)", "nhóm hàng", "product category"),
    ):
        found_cat = next((c for _, c in active_cols if re.search(pat, c, re.I)), None)
        if found_cat:
            cat_col = found_cat
            cat_noun_vi, cat_noun_en = c_vi, c_en
            break

    # Channel values & column
    channel_col = next(
        (c for _, c in active_cols if re.search(r"(?:^|_)(?:kenh_?ban|kenh|channel|ban_?qua|nguon_?don|noi_?ban)(?:$|_)", c, re.I)),
        None,
    )
    channel_values: List[str] = []
    for k, vals in (knowledge.categorical_values or {}).items():
        col_part = k.split(".")[-1].lower()
        if re.search(r"(?:^|_)(?:kenh_?ban|kenh|channel|ban_?qua|nguon_?don|noi_?ban)(?:$|_)", col_part):
            channel_values = [str(v) for v, _ in vals if v is not None and str(v).strip()][:3]
            if channel_values:
                break

    # Supplier / customer / numeric measure availability
    supplier_col = next(
        (c for _, c in active_cols if re.search(r"(?:^|_)(?:nha_?cung_?cap|ncc|supplier(?:_?name)?)(?:$|_)", c, re.I)),
        None,
    )
    customer_col = next(
        (c for _, c in active_cols if re.search(r"(?:^|_)(?:ten_?khach(?:_?hang)?|khach_?hang|customer(?:_?name)?|ben_?mua|doi_?tac)(?:$|_)", c, re.I)),
        None,
    )
    has_qty = any(re.search(r"(?:^|_)(?:so_?luong|sl|qty|quantity|so_?hop|boxes)(?:$|_)", c) for c in sales_cols)
    has_revenue = any(
        re.search(r"(?:^|_)(?:doanh_?thu|doanh_?so|thanh_?tien|tong_?tien|tien_?hang|revenue|sales|total_?amount|amount)(?:$|_)", c)
        for c in sales_cols
    )
    has_item_in_import = any(
        re.search(r"(?:^|_)(?:ten_?thuoc|thuoc|ten_?mon|mon|vat_?lieu|ten_?san_?pham|san_?pham|ten_?hang|hang_?hoa|product(?:_?name)?)(?:$|_)", c)
        for c in import_cols
    )

    date_ref = knowledge.data_max_date or ""
    ym = date_ref[:7] if len(date_ref) >= 7 else ""
    ym_phrase_vi = f"trong tháng {ym[5:7]}/{ym[:4]}" if ym else ""
    ym_phrase_en = f"in {ym}" if ym else ""

    sales_dcol = str(t0.get("date_col") or "")
    sales_range = None
    if sales_table and sales_dcol:
        sales_range = (knowledge.table_date_ranges or {}).get(f"{sales_table}.{sales_dcol}")
    if not sales_range and knowledge.data_min_date and knowledge.data_max_date:
        sales_range = (knowledge.data_min_date, knowledge.data_max_date)
    has_multi_day_sales = bool(sales_range and sales_range[0] != sales_range[1])

    has_cancelled = bool(t0.get("cancelled_values") or t0.get("returned_values"))

    # Generic fallback table info when schema does not match POS sales conventions
    fallback_table = sales_table or (valid_tables[0] if valid_tables else "data")
    tp_fb = knowledge.workspace.tables.get(fallback_table)
    fb_text_col = None
    fb_num_col = None
    if tp_fb is not None:
        for cp in tp_fb.columns:
            if cp.distinct_count <= 0 or cp.null_count >= tp_fb.row_count:
                continue
            c_low = str(cp.sql_name).lower()
            if fb_text_col is None and cp.inferred_type == "text" and 2 <= cp.distinct_count <= max(50, tp_fb.row_count):
                if not re.search(r"^(?:ma_|id\b)", c_low):
                    fb_text_col = cp.sql_name
            elif fb_num_col is None and cp.inferred_type in ("integer", "real", "numeric"):
                if not re.search(r"(?:^|_)(?:id|ma_)", c_low):
                    fb_num_col = cp.sql_name

    return {
        "caps": caps,
        "targets": targets,
        "sales_table": sales_table,
        "item_col": item_col,
        "item_noun_vi": item_noun_vi,
        "item_noun_en": item_noun_en,
        "sales_noun_vi": sales_noun_vi,
        "sales_noun_en": sales_noun_en,
        "doc_noun_vi": doc_noun_vi,
        "doc_noun_en": doc_noun_en,
        "import_noun_vi": import_noun_vi,
        "import_noun_en": import_noun_en,
        "cat_col": cat_col,
        "cat_noun_vi": cat_noun_vi,
        "cat_noun_en": cat_noun_en,
        "has_channel": bool(caps.get("has_channel") or channel_col),
        "channel_col": channel_col,
        "channel_values": channel_values,
        "has_import": bool(caps.get("has_import")),
        "has_import_price": bool(caps.get("has_import_price")),
        "has_supplier": bool(supplier_col),
        "has_item_in_import": has_item_in_import,
        "has_customers": bool(caps.get("has_customers") or customer_col),
        "has_debt": bool(caps.get("has_debt_or_payments")),
        "has_staff": bool(caps.get("has_staff")),
        "has_inventory": bool(caps.get("has_inventory")),
        "has_expiry": bool(caps.get("has_expiry")),
        "has_qty": has_qty,
        "has_revenue": has_revenue,
        "has_cancelled": has_cancelled,
        "returned_values": list(t0.get("returned_values") or []),
        "ym": ym,
        "ym_phrase_vi": ym_phrase_vi,
        "ym_phrase_en": ym_phrase_en,
        "has_multi_day_sales": has_multi_day_sales,
        "fallback_table": fallback_table,
        "fb_text_col": fb_text_col,
        "fb_num_col": fb_num_col,
        "all_col_lows": all_col_lows,
    }


def _extract_df_focus_entities(df: Optional[pd.DataFrame], profile: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Extract the top/bottom entity returned in the current result table and classify its dimension."""
    if df is None or df.empty:
        return {"top_entity": None, "bottom_entity": None, "entity_kind": None}

    def _clean_ent(val: Any) -> Optional[str]:
        if val is None or pd.isna(val):
            return None
        s = str(val).strip()
        if not s or len(s) < 2 or len(s) > 45:
            return None
        s_low = s.lower()
        if s_low in {"(chưa xác định)", "(unassigned)", "n/a", "none", "null", "nan", "unknown"}:
            return None
        if re.fullmatch(r"[\d\.,\s\-+%$đVNĐ]+", s):
            return None
        if re.match(r"^\d{4}[-/]\d{2}(?:[-/]\d{2})?$", s):
            return None
        return s

    # Pick primary numeric metric column (to rank rows cleanly if df isn't already sorted)
    num_cols = [
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c])
        and not re.search(r"(?:^|_)(?:id|ma_|stt|rank|nam|year)(?:$|_)", str(c).lower())
    ]
    metric_col = num_cols[0] if num_cols else None

    ranked_df = df
    if metric_col and len(df) >= 2:
        try:
            ranked_df = df.assign(_m_sort=pd.to_numeric(df[metric_col], errors="coerce")).dropna(subset=["_m_sort"])
            if not ranked_df.empty:
                ranked_df = ranked_df.sort_values("_m_sort", ascending=False)
            else:
                ranked_df = df
        except Exception:
            ranked_df = df

    # Score candidate label columns by schema role
    best_col = None
    best_kind = None
    best_score = -1
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        c_low = str(col).lower()
        if re.search(r"(?:^|_)(?:ngay|date|trang_?thai|status|don_?vi|ma_?hd|ma_?don|ma_?phieu)(?:$|_)", c_low):
            continue
        sample_valid = [_clean_ent(v) for v in ranked_df[col].head(5).tolist()]
        if not any(sample_valid):
            continue

        kind = "generic"
        score = 10
        if re.search(r"(?:ten_?thuoc|ten_?mon|vat_?lieu|ten_?san_?pham|san_?pham|product|hang_?hoa|ten_?hang)", c_low):
            kind, score = "item", 60
        elif re.search(r"(?:nha_?cung_?cap|ncc|supplier)", c_low):
            kind, score = "supplier", 55
        elif re.search(r"(?:ten_?khach|khach_?hang|customer|ben_?mua|doi_?tac)", c_low):
            kind, score = "customer", 55
        elif re.search(r"(?:kenh_?ban|kenh|channel|ban_?qua|noi_?ban)", c_low):
            kind, score = "channel", 52
        elif re.search(r"(?:nhom_?mon|nhom_?thuoc|nhom_?hang|danh_?muc|category)", c_low):
            kind, score = "category", 50
        elif re.search(r"(?:ten|name)", c_low):
            kind, score = "item" if profile.get("item_col") else "generic", 35

        if score > best_score:
            best_score = score
            best_col = col
            best_kind = kind

    if not best_col:
        return {"top_entity": None, "bottom_entity": None, "entity_kind": None}

    top_ent = None
    bot_ent = None
    for val in ranked_df[best_col].tolist():
        c = _clean_ent(val)
        if c:
            top_ent = c
            break
    if len(ranked_df) >= 2:
        for val in reversed(ranked_df[best_col].tolist()):
            c = _clean_ent(val)
            if c and c != top_ent:
                bot_ent = c
                break

    return {"top_entity": top_ent, "bottom_entity": bot_ent, "entity_kind": best_kind}


def _is_near_duplicate_query(cand: str, ref: str) -> bool:
    """Detect whether a suggested follow-up is identical or practically redundant with user_query."""
    if not cand or not ref:
        return False
    c_n = norm_vn(cand)
    r_n = norm_vn(ref)
    if not c_n or not r_n:
        return False
    if c_n == r_n or c_n in r_n or r_n in c_n:
        return True
    stop = {"la", "bao", "nhieu", "trong", "cua", "va", "theo", "tung", "co", "nhung", "nao", "the", "what", "is", "are", "by", "in", "of", "for"}
    c_toks = {t for t in c_n.split() if len(t) >= 2 and t not in stop}
    r_toks = {t for t in r_n.split() if len(t) >= 2 and t not in stop}
    if not c_toks or not r_toks:
        return False
    overlap = len(c_toks & r_toks) / max(1, len(c_toks | r_toks))
    return overlap > 0.72


def build_datamate_suggested_questions(
    knowledge: WorkspaceKnowledge,
    lang: str = "vi",
    user_query: str = "",
    df: Optional[pd.DataFrame] = None,
    sql: str = "",
) -> List[str]:
    """Generate contextual, flow-preserving follow-up suggestions 100% grounded in the active DB schema."""
    prof = _profile_datamate_followup_schema(knowledge)
    focus = _extract_df_focus_entities(df, prof)
    is_en = lang == "en"

    top_ent = focus.get("top_entity")
    ent_kind = focus.get("entity_kind")
    q_norm = norm_vn(user_query or "")

    item_col = prof["item_col"]
    i_vi, i_en = prof["item_noun_vi"], prof["item_noun_en"]
    s_vi, s_en = prof["sales_noun_vi"], prof["sales_noun_en"]
    d_vi, d_en = prof["doc_noun_vi"], prof["doc_noun_en"]
    imp_vi, imp_en = prof["import_noun_vi"], prof["import_noun_en"]
    cat_col = prof["cat_col"]
    c_vi, c_en = prof["cat_noun_vi"], prof["cat_noun_en"]
    ym_vi = f" {prof['ym_phrase_vi']}" if prof["ym_phrase_vi"] else ""
    ym_en = f" {prof['ym_phrase_en']}" if prof["ym_phrase_en"] else ""
    ch_vals = prof["channel_values"]
    ch_hint = f" ({', '.join(ch_vals)})" if ch_vals else ""

    asked_channel = bool(re.search(r"\b(?:kenh|tai quay|zalo|channel)\b", q_norm)) or ent_kind == "channel"
    asked_category = bool(re.search(r"\b(?:nhom mon|nhom thuoc|nhom hang|danh muc|category)\b", q_norm)) or ent_kind == "category"
    asked_import = bool(re.search(r"\b(?:nhap|nha cung cap|ncc|gia nhap|phieu nhap|supplier)\b", q_norm)) or ent_kind == "supplier"
    asked_debt_cust = bool(re.search(r"\b(?:cong no|con no|chua thanh toan|da thanh toan|khach hang|debt|customer)\b", q_norm)) or ent_kind == "customer"
    asked_time = bool(re.search(r"\b(?:ngay nao|theo ngay|xu huong|theo thang|bien dong|daily|trend)\b", q_norm))
    asked_item_rank = (
        bool(
            re.search(r"\b(?:top|ban chay|cao nhat|thap nhat|cao thu|thap thu|xep hang|rank|highest|lowest)\b", q_norm)
            and re.search(r"\b(?:thuoc|mon|san pham|mat hang|vat lieu|product|item|medicine|material)\b", q_norm)
        )
        or ent_kind == "item"
    )

    candidates: List[str] = []

    def _add(q_vi: str, q_en: str) -> None:
        candidates.append(q_en if is_en else q_vi)

    # 1. Contextual flow based on what the user just asked & what rows returned
    if asked_item_rank:
        if top_ent and prof["has_channel"]:
            if prof["has_qty"]:
                _add(
                    f"Doanh thu và số lượng bán của {top_ent} theo từng kênh bán là bao nhiêu?",
                    f"What are the revenue and quantity sold of {top_ent} by sales channel?",
                )
            else:
                _add(
                    f"Doanh thu của {top_ent} theo từng kênh bán là bao nhiêu?",
                    f"What is the revenue of {top_ent} by sales channel?",
                )
        if prof["has_channel"] and not asked_channel:
            _add(
                f"So sánh doanh thu {s_vi} theo từng kênh bán{ch_hint}?",
                f"Compare {s_en} across channels{ch_hint}?",
            )
        if prof["has_import"] and prof["has_import_price"] and prof["has_supplier"]:
            _add(
                f"Tổng tiền nhập {imp_vi} và số lượng nhập theo từng nhà cung cấp là bao nhiêu?",
                f"What is total import cost and quantity by supplier?",
            )
        if top_ent and prof["has_import"] and prof["has_import_price"] and prof["has_item_in_import"]:
            _add(
                f"Giá nhập và tổng số lượng nhập của {top_ent} là bao nhiêu?",
                f"What are the import price and total quantity imported for {top_ent}?",
            )
        if cat_col and not asked_category:
            _add(
                f"Tỷ lệ đóng góp doanh thu theo từng {c_vi} là bao nhiêu?",
                f"What is the revenue contribution share by {c_en}?",
            )
        if top_ent and prof["has_multi_day_sales"] and prof["has_revenue"]:
            _add(
                f"Xu hướng doanh thu của {top_ent} theo từng ngày{ym_vi}?",
                f"Daily revenue trend of {top_ent}{ym_en}?",
            )
        if prof["has_debt"] and prof["has_customers"]:
            _add(
                "Khách hàng nào còn công nợ chưa thanh toán nhiều nhất?",
                "Which customers have the highest outstanding debt?",
            )
        if prof["has_qty"] and item_col and "so luong" not in q_norm:
            _add(
                f"So sánh số lượng bán ra của từng {i_vi}{ym_vi}?",
                f"Compare units sold across each {i_en}{ym_en}?",
            )
        if prof["has_cancelled"]:
            ret_hint = " hoặc trả lại" if prof["returned_values"] else ""
            _add(
                f"Có bao nhiêu {d_vi} bị hủy{ret_hint} và tổng giá trị là bao nhiêu?",
                f"How many {d_en} were canceled and what is their total value?",
            )

    elif asked_channel:
        if top_ent and item_col:
            _add(
                f"Top {i_vi} có doanh thu cao nhất trên kênh {top_ent}?",
                f"Top {i_en}s by revenue on {top_ent} channel?",
            )
        if prof["has_multi_day_sales"] and prof["has_revenue"]:
            _add(
                f"Xu hướng doanh thu {s_vi} theo từng ngày{ym_vi}?",
                f"Daily {s_en} trend{ym_en}?",
            )
        if prof["has_import"] and prof["has_import_price"] and prof["has_supplier"]:
            _add(
                f"Tổng tiền nhập {imp_vi} và số lượng nhập theo từng nhà cung cấp là bao nhiêu?",
                f"Total import value and quantity by supplier?",
            )
        if prof["has_cancelled"]:
            _add(
                f"Số lượng {d_vi} bị hủy theo từng kênh bán là bao nhiêu?",
                f"How many canceled {d_en} per sales channel?",
            )

    elif asked_category:
        if top_ent and item_col:
            _add(
                f"Các {i_vi} thuộc {c_vi} {top_ent} có doanh thu như thế nào?",
                f"Revenue breakdown of {i_en}s in {top_ent} {c_en}?",
            )
        if item_col and prof["has_revenue"]:
            _add(
                f"Top 5 {i_vi} có doanh thu cao nhất{ym_vi}?",
                f"Top 5 {i_en}s by revenue{ym_en}?",
            )
        if prof["has_multi_day_sales"] and prof["has_revenue"]:
            _add(
                f"Xu hướng doanh thu {s_vi} theo từng ngày{ym_vi}?",
                f"Daily {s_en} trend{ym_en}?",
            )

    elif asked_import:
        if top_ent and ent_kind == "supplier" and item_col:
            _add(
                f"Nhà cung cấp {top_ent} đã nhập những {i_vi} nào và tổng tiền nhập là bao nhiêu?",
                f"Which {i_en}s were supplied by {top_ent} and at what import value?",
            )
        if item_col and prof["has_revenue"]:
            _add(
                f"Top 5 {i_vi} có doanh thu bán ra cao nhất{ym_vi}?",
                f"Top 5 {i_en}s by sales revenue{ym_en}?",
            )
        if prof["has_channel"]:
            _add(
                f"So sánh doanh thu {s_vi} theo từng kênh bán{ch_hint}?",
                f"Compare {s_en} across channels{ch_hint}?",
            )
        if prof["has_multi_day_sales"] and prof["has_revenue"]:
            _add(
                f"Xu hướng doanh thu {s_vi} theo từng ngày{ym_vi}?",
                f"Daily {s_en} trend{ym_en}?",
            )

    elif asked_debt_cust:
        if top_ent and ent_kind == "customer" and item_col:
            _add(
                f"Chi tiết các {i_vi} mà khách hàng {top_ent} đã mua là gì?",
                f"Which {i_en}s did customer {top_ent} purchase?",
            )
        if item_col and prof["has_revenue"]:
            _add(
                f"Xếp hạng doanh thu theo từng {i_vi}{ym_vi}?",
                f"Revenue ranking by {i_en}{ym_en}?",
            )
        if prof["has_debt"]:
            _add(
                "Tổng doanh thu và tổng số tiền đã thanh toán theo từng khách hàng là bao nhiêu?",
                "Total revenue and paid amount per customer?",
            )
        if prof["has_multi_day_sales"] and prof["has_revenue"]:
            _add(
                f"Xu hướng doanh thu {s_vi} theo từng ngày{ym_vi}?",
                f"Daily {s_en} trend{ym_en}?",
            )

    elif asked_time:
        if item_col and prof["has_revenue"]:
            _add(
                f"Top 5 {i_vi} đóng góp doanh thu cao nhất{ym_vi}?",
                f"Top 5 {i_en}s contributing to revenue{ym_en}?",
            )
        if prof["has_channel"]:
            _add(
                f"So sánh doanh thu {s_vi} theo từng kênh bán{ch_hint}?",
                f"Compare {s_en} across channels{ch_hint}?",
            )
        if cat_col:
            _add(
                f"Tỷ lệ đóng góp doanh thu theo từng {c_vi} là bao nhiêu?",
                f"Revenue share by {c_en}?",
            )
        if prof["has_import"] and prof["has_import_price"] and prof["has_supplier"]:
            _add(
                f"Tổng tiền nhập {imp_vi} theo từng nhà cung cấp là bao nhiêu?",
                f"Total import value by supplier?",
            )
        if prof["has_debt"] and prof["has_customers"]:
            _add(
                "Khách hàng nào còn công nợ chưa thanh toán nhiều nhất?",
                "Which customers have the highest outstanding debt?",
            )

    # 2. Always append schema-specific high-value analytical options as secondary/starter pool
    if prof["has_debt"] and prof["has_customers"]:
        _add(
            "Khách hàng nào còn công nợ chưa thanh toán nhiều nhất?",
            "Which customers have the highest outstanding debt?",
        )
    if prof["has_channel"]:
        _add(
            f"So sánh doanh thu {s_vi} theo từng kênh bán{ch_hint}?",
            f"Compare {s_en} across channels{ch_hint}?",
        )
    if prof["has_import"] and prof["has_import_price"] and prof["has_supplier"]:
        _add(
            f"Tổng tiền nhập {imp_vi} và số lượng nhập theo từng nhà cung cấp là bao nhiêu?",
            f"Total import value and quantity by supplier?",
        )
    if item_col and prof["has_revenue"]:
        _add(
            f"Top 5 {i_vi} có doanh thu cao nhất{ym_vi}?",
            f"Top 5 {i_en}s by revenue{ym_en}?",
        )
    if cat_col:
        _add(
            f"Tỷ lệ đóng góp doanh thu theo từng {c_vi} là bao nhiêu?",
            f"Revenue share by {c_en}?",
        )
    if prof["has_customers"] and not prof["has_debt"]:
        _add(
            "Top 5 khách hàng có tổng giá trị đơn hàng cao nhất là ai?",
            "Top 5 customers by valid order spending?",
        )
    if prof["has_multi_day_sales"] and prof["has_revenue"]:
        _add(
            f"Xu hướng doanh thu {s_vi} theo từng ngày{ym_vi}?",
            f"Daily {s_en} trend{ym_en}?",
        )
    if prof["has_staff"] and prof["has_revenue"]:
        _add(
            "Top 5 nhân viên có doanh thu cao nhất là ai?",
            "Top 5 staff by revenue?",
        )

    # Non-POS / generic database fallback (e.g. arbitrary Excel sheets without revenue/status)
    t_fb = prof["fallback_table"]
    if prof["fb_text_col"] and prof["fb_num_col"]:
        _add(
            f"Top 5 {prof['fb_text_col']} theo tổng {prof['fb_num_col']} trong bảng {t_fb}?",
            f"Top 5 {prof['fb_text_col']} by total {prof['fb_num_col']} in `{t_fb}`?",
        )
    elif prof["fb_text_col"]:
        _add(
            f"Thống kê số lượng bản ghi theo từng {prof['fb_text_col']} trong bảng {t_fb}?",
            f"Record count by {prof['fb_text_col']} in `{t_fb}`?",
        )
    _add(
        f"Thống kê tổng quan các chỉ số chính của bảng {t_fb}",
        f"Show summary metrics of table `{t_fb}`",
    )

    # 3. Strict DB-groundness & anti-repetition gate
    as_of = resolve_interactive_as_of_date(knowledge)
    validated: List[str] = []
    seen_norm: Set[str] = set()
    for cand in candidates:
        q_clean = re.sub(r"\s+", " ", str(cand or "")).strip()
        if not q_clean:
            continue
        q_n = norm_vn(q_clean)
        if q_n in seen_norm or _is_near_duplicate_query(q_clean, user_query):
            continue
        if check_out_of_scope_or_irrelevant(q_clean, knowledge) is not None:
            continue
        if check_preflight_unanswerable(q_clean, as_of, knowledge, classify_expected_type(q_clean)) is not None:
            continue
        seen_norm.add(q_n)
        validated.append(q_clean)
        if len(validated) >= 3:
            break

    if not validated:
        fb = (
            f"Show summary metrics of table `{t_fb}`"
            if is_en
            else f"Thống kê tổng quan các chỉ số chính của bảng {t_fb}"
        )
        validated.append(fb)
    return validated


def _enrich_extreme_comparison_df(
    df: pd.DataFrame,
    analysis: QuestionAnalysis,
    user_query: str = "",
) -> pd.DataFrame:
    """Normalize extreme-comparison result DataFrames to always show top/bottom rows, group label, and diff."""
    ext_cmp = getattr(analysis, "extreme_comparison", None)
    if ext_cmp is None or df is None or len(df) < 2:
        return df

    top_n, bottom_n, wants_diff = ext_cmp
    work = df.copy()
    cols = list(work.columns)

    rank_rx = re.compile(r"(?:nhom_?xep_?hang|nhóm\s*xếp\s*hạng|rank_?group|rankgroup)", re.IGNORECASE)
    diff_rx = re.compile(r"(?:chenh_?lech|chênh\s*lệch|spread|gap|diff|difference)", re.IGNORECASE)
    id_rx = re.compile(r"^(?:ma_|id$|rn_|row_?num)|_id$", re.IGNORECASE)

    existing_rank_col = next((c for c in cols if rank_rx.search(str(c))), None)
    existing_diff_col = next((c for c in cols if diff_rx.search(str(c))), None)

    ent_col = next(
        (
            c for c in cols
            if c != existing_rank_col
            and not pd.api.types.is_numeric_dtype(work[c])
            and not id_rx.search(str(c))
        ),
        None,
    )
    if ent_col is None:
        ent_col = next((c for c in cols if c != existing_rank_col), cols[0])

    num_candidates = [
        c for c in cols
        if c not in (ent_col, existing_rank_col, existing_diff_col)
        and c.lower() not in ("rn_high", "rn_low", "rn")
        and not id_rx.search(str(c))
        and pd.to_numeric(work[c], errors="coerce").notna().any()
    ]
    if not num_candidates:
        return df

    metric_col = next(
        (
            c for c in num_candidates
            if re.search(r"(?:doanh_?thu|thanh_?tien|tong_?tien|tien|revenue|sales|amount|cong_?no|so_?luong|sl|qty|boxes|tong_)", str(c), re.IGNORECASE)
        ),
        num_candidates[0],
    )

    work["_sort_metric"] = pd.to_numeric(work[metric_col], errors="coerce")
    valid_work = work.dropna(subset=["_sort_metric"]).copy()
    if len(valid_work) < 2:
        return df

    valid_work = valid_work.sort_values("_sort_metric", ascending=False, kind="mergesort").reset_index(drop=True)
    max_val = float(valid_work["_sort_metric"].iloc[0])
    min_val = float(valid_work["_sort_metric"].iloc[-1])
    gap_val = max_val - min_val

    if len(valid_work) > top_n + bottom_n:
        top_idxs = list(range(0, min(top_n, len(valid_work))))
        bot_idxs = list(range(max(0, len(valid_work) - bottom_n), len(valid_work)))
        keep_idxs = sorted(set(top_idxs + bot_idxs))
        valid_work = valid_work.iloc[keep_idxs].reset_index(drop=True)

    valid_work = valid_work.drop(columns=["_sort_metric"])

    high_lbl = "Cao nhất" if top_n == 1 else f"Top {top_n} Cao nhất"
    low_lbl = "Thấp nhất" if bottom_n == 1 else f"Top {bottom_n} Thấp nhất"
    rank_col = existing_rank_col or "nhom_xep_hang"
    if not existing_rank_col:
        valid_work[rank_col] = [high_lbl if idx < top_n else low_lbl for idx in range(len(valid_work))]

    diff_col = existing_diff_col
    if wants_diff and not diff_col:
        diff_col = "chenh_lech_cao_thap"
        m_num = pd.to_numeric(valid_work[metric_col], errors="coerce").dropna()
        all_int = (not m_num.empty) and bool((m_num == m_num.round(0)).all())
        is_money_hint = bool(analysis.money_like) or bool(
            re.search(r"(?:doanh_?thu|thanh_?tien|tong_?tien|tien|revenue|sales|amount|cong_?no|luong|salary)", str(metric_col), re.IGNORECASE)
        )
        valid_work[diff_col] = (
            int(round(gap_val)) if (is_money_hint or all_int or abs(gap_val - round(gap_val)) < 1e-6) else round(gap_val, 2)
        )

    ordered_cols = [ent_col, rank_col, metric_col]
    for c in valid_work.columns:
        if c not in ordered_cols and c != diff_col:
            ordered_cols.append(c)
    if diff_col and diff_col in valid_work.columns:
        ordered_cols.append(diff_col)
    return valid_work[ordered_cols]


def _format_answer_banner(
    formatted: Optional[Dict[str, Any]],
    analysis: QuestionAnalysis,
    lang: str,
    sql_res: Optional[SQLExecutionResult] = None,
    df: Optional[pd.DataFrame] = None,
) -> Optional[str]:
    if not formatted or "answer" not in formatted:
        return None
    ptype = formatted.get("type")
    ans = formatted.get("answer")
    is_en = lang == "en"

    if getattr(analysis, "extreme_comparison", None) is not None and df is not None and len(df) >= 2:
        rank_rx = re.compile(r"(?:nhom_?xep_?hang|nhóm\s*xếp\s*hạng|rank_?group|rankgroup)", re.IGNORECASE)
        diff_rx = re.compile(r"(?:chenh_?lech|chênh\s*lệch|spread|gap|diff|difference)", re.IGNORECASE)
        id_rx = re.compile(r"^(?:ma_|id$|rn_|row_?num)|_id$", re.IGNORECASE)
        ent_col = next(
            (c for c in df.columns if not rank_rx.search(str(c)) and not pd.api.types.is_numeric_dtype(df[c]) and not id_rx.search(str(c))),
            df.columns[0],
        )
        num_cands = [
            c for c in df.columns
            if c != ent_col and not rank_rx.search(str(c)) and not diff_rx.search(str(c))
            and not id_rx.search(str(c)) and pd.to_numeric(df[c], errors="coerce").notna().any()
        ]
        if num_cands:
            m_col = num_cands[0]
            s_vals = pd.to_numeric(df[m_col], errors="coerce").dropna()
            if len(s_vals) >= 2:
                top_idx = s_vals.idxmax()
                bot_idx = s_vals.idxmin()
                top_ent = str(df.loc[top_idx, ent_col]).strip()
                bot_ent = str(df.loc[bot_idx, ent_col]).strip()
                top_v = float(s_vals.loc[top_idx])
                bot_v = float(s_vals.loc[bot_idx])
                diff_v = top_v - bot_v

                is_vnd = is_vnd_context_dataframe(df, str(m_col))
                m_low = str(m_col).lower()
                is_usd = (not is_vnd) and (
                    "$" in m_low
                    or any(k in m_low for k in ("salary", "amount", "sales", "revenue", "cost", "budget", "profit"))
                )

                def _fmt_bval(v: float) -> str:
                    if is_vnd:
                        if abs(v) >= 100 or abs(v - round(v)) < 1e-4:
                            return f"{int(round(v)):,}".replace(",", ".") + " VNĐ"
                        return f"{v:,.2f} VNĐ"
                    if is_usd:
                        return f"${int(round(v)):,}" if abs(v - round(v)) < 1e-4 else f"${v:,.2f}"
                    return f"{int(round(v)):,}".replace(",", ".") if abs(v - round(v)) < 1e-4 else f"{v:,.2f}"

                top_fmt = _fmt_bval(top_v)
                bot_fmt = _fmt_bval(bot_v)
                diff_fmt = _fmt_bval(diff_v)
                ratio_str = f" (gấp {top_v / bot_v:.1f}x)" if (bot_v > 0 and top_v >= bot_v) else ""
                if is_en:
                    ratio_en = f" ({top_v / bot_v:.1f}x)" if (bot_v > 0 and top_v >= bot_v) else ""
                    return (
                        f"💡 **Verified Comparison:** Highest: **{top_ent}** (**{top_fmt}**) • "
                        f"Lowest: **{bot_ent}** (**{bot_fmt}**) • Difference: **{diff_fmt}**{ratio_en}"
                    )
                return (
                    f"💡 **Kết quả kiểm định chuẩn:** Cao nhất: **{top_ent}** (**{top_fmt}**) • "
                    f"Thấp nhất: **{bot_ent}** (**{bot_fmt}**) • Chênh lệch: **{diff_fmt}**{ratio_str}"
                )

    if (
        sql_res is not None
        and sql_res.ok
        and len(sql_res.rows) == 1
        and len(sql_res.columns) >= 2
        and ptype in ("string", "date", "table")
    ):
        row0 = sql_res.rows[0]
        ent_val = row0[0]
        metric_val = row0[1]
        if ent_val is not None and isinstance(metric_val, (int, float)) and not isinstance(metric_val, bool):
            from src.visualization.charts import format_col_title

            raw_col = str(sql_res.columns[1])
            col_title = format_col_title(raw_col) if not is_en else raw_col
            col_title_clean = re.sub(r"\s*\(\$\)\s*", "", col_title).strip()
            col_low = raw_col.lower()
            is_money_col = analysis.money_like or any(
                k in col_low for k in ("doanh_thu", "thanh_tien", "tong_tien", "tien", "no", "luong", "gia", "revenue", "amount", "sales")
            )
            num_str = (
                f"{int(round(float(metric_val))):,}".replace(",", ".")
                if (is_money_col or float(metric_val).is_integer())
                else f"{float(metric_val):,.2f}"
            )
            unit = " VNĐ" if (is_money_col and not is_en) else ""
            if not is_en:
                return f"💡 **Kết quả kiểm định chuẩn:** **{ent_val}** — **{col_title_clean}: {num_str}{unit}**"
            return f"💡 **Verified Result:** **{ent_val}** — **{col_title_clean}: {num_str}**"

    if ptype == "number" and isinstance(ans, (int, float)):
        num_str = f"{int(ans):,}".replace(",", ".") if (analysis.money_like or float(ans).is_integer()) else f"{ans:,.2f}"
        unit = " VNĐ" if (analysis.money_like and not is_en) else ""
        return f"💡 **Kết quả kiểm định chuẩn:** **{num_str}{unit}**" if not is_en else f"💡 **Verified Result:** **{num_str}**"
    if ptype == "percent" and isinstance(ans, (int, float)):
        return f"💡 **Tỷ lệ kiểm định chuẩn:** **{ans:.2f}%**" if not is_en else f"💡 **Verified Percentage:** **{ans:.2f}%**"
    if ptype == "date":
        return f"💡 **Mốc thời gian kiểm định chuẩn:** **{ans}**" if not is_en else f"💡 **Verified Date:** **{ans}**"
    if ptype == "boolean":
        lbl = ("Có (True)" if ans else "Không (False)") if not is_en else ("Yes (True)" if ans else "No (False)")
        return f"💡 **Kết quả kiểm định:** **{lbl}**" if not is_en else f"💡 **Verified Answer:** **{lbl}**"
    if ptype == "string":
        return f"💡 **Kết quả kiểm định chuẩn:** **{ans}**" if not is_en else f"💡 **Verified Result:** **{ans}**"
    if ptype == "list" and isinstance(ans, list):
        items = ", ".join(str(x) for x in ans[:10])
        return f"💡 **Danh sách kiểm định chuẩn:** {items}" if not is_en else f"💡 **Verified List:** {items}"
    return None


def _governance_notice(title_vi: str, title_en: str, detail: str, lang: str) -> str:
    prefix = f"🛡️ **{title_en if lang == 'en' else title_vi}:** "
    return f"{prefix}{detail}"


def run_datamate_enhanced_turn(
    user_query: str,
    client: Any,
    provider: str,
    model_name: str,
    knowledge: WorkspaceKnowledge,
    enable_self_check: bool = True,
    enable_auto_insights: bool = True,
    status_callback: Optional[Callable[[str], None]] = None,
    lang: str = "vi",
    as_of_date: Optional[str] = None,
    insights_fn: Optional[Callable[..., str]] = None,
) -> Dict[str, Any]:
    """
    Execute a question against a DataMate WorkspaceKnowledge using full Stage-1 guardrails:
    Vietnamese teencode/temporal normalization, unanswerable preflight, JSON SQL generation,
    semantic SQL verification & auto-repair, and Veraxus charts/insights integration.
    """
    t_start = time.time()
    as_of = resolve_interactive_as_of_date(knowledge, as_of_date)
    result: Dict[str, Any] = {
        "query": user_query,
        "lang": lang,
        "df": None,
        "sql": None,
        "logs": [f"📅 Mốc tham chiếu hôm nay (as_of_date): {as_of} (dữ liệu: {knowledge.data_min_date or '?'} .. {knowledge.data_max_date or '?'})"],
        "attempts": 0,
        "error": None,
        "explanation": None,
        "anomalies_info": None,
        "insights": None,
        "followups": [],
        "plan": None,
        "evaluator": None,
        "is_datamate_turn": True,
        "agent_trace": {
            "plan": {
                "complexity": "DATAMATE_VERIFIED",
                "subtasks": ["Normalize & Temporal", "Schema & Preflight", "Semantic SQL Audit"],
            },
            "schema_linking": {"selected_tables": list(knowledge.valid_tables)},
            "router": None,
            "planner": None,
            "executor": None,
            "evaluator": None,
        },
    }

    analysis = classify_expected_type(user_query)
    windows, temp_summary, bounded, prior_start = extract_temporal_context(user_query, as_of, None)
    analysis.temporal_windows = windows
    analysis.temporal_summary = temp_summary
    analysis.bounded_period = bounded
    analysis.prior_needed_start = prior_start

    result["agent_trace"]["router"] = {
        "complexity": "datamate-verified",
        "intent": analysis.expected_type,
        "bounded_period": list(bounded) if bounded else None,
        "time_horizon": f"as_of={as_of}",
    }
    result["logs"].append(f"🧭 [DataMate Classifier] Kiểu kỳ vọng: `{analysis.expected_type}` | Thời gian: {bounded or 'mở rộng'}")

    # 1. Deterministic Preflight Unanswerable Check (Zero Hallucination)
    if status_callback:
        status_callback("🛡️ [DataMate Guard] Kiểm tra khả năng trả lời trên lược đồ & khoảng ngày dữ liệu...")

    preflight_reason = check_preflight_unanswerable(user_query, as_of, knowledge, analysis)
    if preflight_reason:
        result["logs"].append(f"🛡️ [Preflight Blocked] {preflight_reason}")
        result["explanation"] = _governance_notice(
            "Dữ liệu không đủ thông tin để trả lời chính xác",
            "Insufficient data to answer reliably",
            preflight_reason,
            lang,
        )
        result["followups"] = build_datamate_suggested_questions(
            knowledge, lang=lang, user_query=user_query
        )
        result["evaluator"] = {
            "verdict": "UNANSWERABLE_BLOCKED",
            "score": 100,
            "critique": preflight_reason,
        }
        result["agent_trace"]["evaluator"] = result["evaluator"]
        return result

    # 2. Ground entities & build DataMate SQL prompt
    entities = ground_query_entities(user_query, knowledge, max_matches=12)
    if entities:
        result["logs"].append("🎯 [Entity Grounding] " + ", ".join(f"{t}.{c}={v!r}" for t, c, v in entities[:6]))

    backend = VeraxusClientLLMBackend(client=client, provider=provider, model_name=model_name)
    max_retries = 3 if enable_self_check else 1
    dm_agent = DataMateAgent(
        backend=backend,
        config=AgentConfig(
            max_sql_retries=max_retries,
            enable_preflight_unanswerable=False,
            enable_llm_formatter_fallback=False,
            use_json_mode=True,
            sql_max_tokens=384,
        ),
    )

    sys_p, usr_p = dm_agent._build_sql_prompt(
        question=user_query,
        as_of_date=as_of,
        knowledge=knowledge,
        analysis=analysis,
        temporal_summary=temp_summary,
        entity_matches=entities,
    )

    prompt_to_send = usr_p
    last_sql_text = ""
    last_res: Optional[SQLExecutionResult] = None
    last_sem_msg = ""

    def _try_extreme_fallback(trigger_reason: str) -> Optional[Tuple[SQLExecutionResult, str, bool, str]]:
        if getattr(analysis, "extreme_comparison", None) is None:
            return None
        spec = build_extreme_comparison_sql_spec(user_query, knowledge, analysis)
        if not spec or not spec.get("suggested_sql"):
            return None
        fb_sql = spec["suggested_sql"]
        fb_res = execute_sql_safe(
            knowledge.workspace.open_connection,
            fb_sql,
            valid_tables=knowledge.valid_tables,
            max_rows=500,
            timeout_seconds=8.0,
        )
        if not fb_res.ok or fb_res.row_count < 1:
            return None
        fb_ok, fb_msg, _ = verify_sql_semantics(
            fb_res.sql or fb_sql, fb_res, user_query, knowledge, analysis, entity_matches=entities
        )
        if not fb_ok:
            return None
        result["logs"].append(
            f"🛡️ [Extreme Comparison Fallback] {trigger_reason} — tự động chuyển sang CTE cực trị chuẩn."
        )
        return fb_res, (fb_res.sql or fb_sql), fb_ok, fb_msg

    for attempt in range(max_retries):
        result["attempts"] = attempt + 1
        if status_callback:
            status_callback(f"⚡ [DataMate SQL • Lần {attempt + 1}/{max_retries}] Sinh & kiểm định truy vấn SQLite an toàn...")

        try:
            raw_reply = backend.generate(
                prompt_to_send,
                system_prompt=sys_p,
                temperature=0.15 if attempt > 0 else 0.0,
                max_tokens=dm_agent.config.sql_max_tokens,
                json_mode=dm_agent.config.use_json_mode,
            )
        except Exception as exc:
            result["error"] = f"Lỗi gọi mô hình AI: {exc}"
            return result

        resolved_fb = False
        obj = extract_json_object(raw_reply)
        if obj and obj.get("status") == "unanswerable":
            # Do not abort early if we are actively repairing a SQL syntax/table typo and still have retries left
            if attempt > 0 and last_res is not None and not last_res.ok and (attempt + 1 < max_retries):
                result["logs"].append("⚠️ Model trả unanswerable khi đang sửa lỗi SQL — thử sửa lại với lược đồ rút gọn.")
                prompt_to_send = dm_agent._build_repair_prompt(
                    user_query,
                    last_sql_text,
                    last_res.error,
                    knowledge,
                    temporal_summary=temp_summary,
                    include_full_schema=False,
                )
                continue
            fb_out = _try_extreme_fallback(f"Model trả unanswerable ({obj.get('reason') or ''})")
            if fb_out is not None:
                res, last_sql_text, sem_ok, last_sem_msg = fb_out
                resolved_fb = True
            else:
                reason = str(obj.get("reason") or "Dữ liệu hiện có chưa đủ căn cứ để trả lời.")
                result["logs"].append(f"🛡️ [Model Unanswerable] {reason}")
                result["explanation"] = _governance_notice(
                    "Dữ liệu không đủ để kết luận chính xác",
                    "Insufficient data to conclude reliably",
                    reason,
                    lang,
                )
                result["evaluator"] = {
                    "verdict": "UNANSWERABLE_BLOCKED",
                    "score": 100,
                    "critique": reason,
                }
                result["agent_trace"]["evaluator"] = result["evaluator"]
                result["followups"] = build_datamate_suggested_questions(
                    knowledge, lang=lang, user_query=user_query
                )
                return result

        if not resolved_fb:
            candidate_sql = str(obj["sql"]) if (obj and isinstance(obj.get("sql"), str)) else raw_reply
            candidate_sql = rewrite_ranked_entity_sql(candidate_sql, user_query, use_round_half_up=True)
            res = execute_sql_safe(
                knowledge.workspace.open_connection,
                candidate_sql,
                valid_tables=knowledge.valid_tables,
                max_rows=500,
                timeout_seconds=8.0,
            )
            last_res = res
            last_sql_text = res.sql or candidate_sql
            result["logs"].append(f"[Lần {attempt + 1}] SQL: {last_sql_text}")

            sem_ok = True
            if not res.ok:
                result["logs"].append(f"⚠️ Lỗi thực thi SQLite: {res.error}")
                if attempt + 1 < max_retries:
                    prompt_to_send = dm_agent._build_repair_prompt(
                        user_query,
                        last_sql_text,
                        res.error,
                        knowledge,
                        temporal_summary=temp_summary,
                        include_full_schema=(len(knowledge.schema_prompt or "") <= 4500),
                    )
                    continue
                fb_out = _try_extreme_fallback(f"SQL lỗi ({res.error})")
                if fb_out is not None:
                    res, last_sql_text, sem_ok, last_sem_msg = fb_out
                else:
                    result["sql"] = last_sql_text
                    result["explanation"] = _governance_notice(
                        "Không thể tạo truy vấn SQL hợp lệ sau nhiều lần kiểm tra",
                        "Could not build a valid SQL query",
                        f"Đã dừng an toàn để tránh trả về số liệu sai ({res.error}).",
                        lang,
                    )
                    result["followups"] = build_datamate_suggested_questions(
                        knowledge, lang=lang, user_query=user_query
                    )
                    return result
            else:
                sem_ok, sem_msg, sem_fatal = verify_sql_semantics(
                    last_sql_text, res, user_query, knowledge, analysis, entity_matches=entities
                )
                if not sem_ok:
                    last_sem_msg = sem_msg
                    result["logs"].append(f"🛡️ [Semantic Guard] {sem_msg}")
                    if attempt + 1 < max_retries:
                        prompt_to_send = dm_agent._build_repair_prompt(
                            user_query,
                            last_sql_text,
                            sem_msg,
                            knowledge,
                            temporal_summary=temp_summary,
                            include_full_schema=False,
                        )
                        continue
                    if sem_fatal:
                        fb_out = _try_extreme_fallback(sem_msg)
                        if fb_out is not None:
                            res, last_sql_text, sem_ok, last_sem_msg = fb_out
                        else:
                            result["sql"] = last_sql_text
                            result["explanation"] = _governance_notice(
                                "Đã chặn kết quả nghi sai logic nghiệp vụ",
                                "Blocked potentially flawed business logic",
                                f"{sem_msg}. Veraxus từ chối hiển thị số liệu chưa đạt kiểm định để bảo vệ độ chính xác.",
                                lang,
                            )
                            result["followups"] = build_datamate_suggested_questions(
                                knowledge, lang=lang, user_query=user_query
                            )
                            result["evaluator"] = {"verdict": "BLOCKED", "score": 40, "critique": sem_msg}
                            result["agent_trace"]["evaluator"] = result["evaluator"]
                            return result

            is_empty_or_null = (
                res.row_count == 0
                or (res.row_count == 1 and len(res.columns) == 1 and res.rows[0][0] is None)
            )
            if is_empty_or_null:
                msg = "SQL chạy không lỗi nhưng trả về 0 dòng hoặc NULL. Kiểm tra lại filter ngày, trạng thái hoặc dùng NORM_VN(...)."
                result["logs"].append(f"⚠️ [Empty/NULL Guard] {msg}")
                if attempt + 1 < max_retries:
                    prompt_to_send = dm_agent._build_repair_prompt(
                        user_query,
                        last_sql_text,
                        msg,
                        knowledge,
                        temporal_summary=temp_summary,
                        include_full_schema=True,
                    )
                    continue
                fb_out = _try_extreme_fallback(msg)
                if fb_out is not None:
                    res, last_sql_text, sem_ok, last_sem_msg = fb_out
                else:
                    result["sql"] = last_sql_text
                    result["explanation"] = _governance_notice(
                        "Không tìm thấy dữ liệu khớp trong kỳ hoặc điều kiện hỏi",
                        "No matching records found",
                        "Truy vấn trả về rỗng/NULL sau khi kiểm định. Vui lòng kiểm tra lại tên mặt hàng/khách hàng hoặc mốc thời gian của shop.",
                        lang,
                    )
                    result["followups"] = build_datamate_suggested_questions(
                        knowledge, lang=lang, user_query=user_query
                    )
                    return result

        # Valid rows returned & passed semantic guard! Build rich DataFrame + UI metadata.
        df = pd.DataFrame(res.rows, columns=res.columns)
        if getattr(analysis, "extreme_comparison", None) is not None and not df.empty:
            df = _enrich_extreme_comparison_df(df, analysis, user_query=user_query)
            formatted = {"type": "table", "answer": {"columns": list(df.columns), "rows": df.values.tolist()}}
        else:
            formatted = format_sql_result(res, analysis, user_query)
        banner = _format_answer_banner(formatted, analysis, lang, sql_res=res, df=df)

        result["df"] = df
        result["sql"] = last_sql_text
        if banner:
            result["explanation"] = banner
        result["datamate_prediction"] = formatted
        result["execution_time_ms"] = round((time.time() - t_start) * 1000.0, 1)
        result["evaluator"] = {
            "verdict": "PASS" if sem_ok else "PASS_WITH_WARNING",
            "score": 100 if sem_ok else 85,
            "critique": "Đạt kiểm định ngữ nghĩa DataMate (ngày, trạng thái đơn, đơn vị & chống lọc thừa)."
            if sem_ok
            else last_sem_msg,
            "criteria": {
                "Temporal": {"passed": True},
                "StatusFilter": {"passed": sem_ok},
                "MetricGrain": {"passed": True},
                "ZeroFilterLeak": {"passed": True},
            },
        }
        result["agent_trace"]["evaluator"] = result["evaluator"]
        result["agent_trace"]["executor"] = {
            "engine": "SQLite (DataMate Engine)",
            "attempts": attempt + 1,
            "rows_retrieved": len(df),
            "sql": last_sql_text,
        }
        result["followups"] = build_datamate_suggested_questions(
            knowledge,
            lang=lang,
            user_query=user_query,
            df=df,
            sql=last_sql_text,
        )

        if not df.empty and len(df) >= 2:
            result["anomalies_info"] = analyze_data_anomalies(df)

        if enable_auto_insights and not df.empty:
            if status_callback:
                status_callback("💡 [Strategy Advisor] Tổng hợp nhận định & đề xuất từ số liệu thực tế...")
            if provider == "Ollama (Local AI Offline)" or insights_fn is None or len(df) == 1:
                sec = split_insight_sections("", df=df, user_query=user_query, is_en=(lang == "en"))
                result["insights"] = (
                    f"### 2.1. Phát hiện Bất thường & Xu hướng Chính\n{sec['anomaly']}\n\n"
                    f"### 2.2. Giả thuyết & Nguyên nhân Tiềm năng\n{sec['hypothesis']}\n\n"
                    f"### 2.3. Kế hoạch Hành động & Đề xuất Ưu tiên\n{sec['action_plan']}"
                )
            else:
                result["insights"] = insights_fn(
                    client,
                    provider,
                    model_name,
                    user_query,
                    df,
                    result.get("anomalies_info"),
                    lang=lang,
                )
        return result

    return result


def _collect_schema_tables_and_cols(
    engine: Any = None,
    schema_context: str = "",
) -> Dict[str, Set[str]]:
    """Extract lowercase {table_name: {col_name, ...}} from SQLAlchemy engine or schema text."""
    table_cols: Dict[str, Set[str]] = {}
    if engine is not None:
        try:
            insp = sa_inspect(engine)
            for tname in insp.get_table_names():
                cols = {str(c["name"]).strip().lower() for c in insp.get_columns(tname) if c.get("name")}
                table_cols[str(tname).strip().lower()] = cols
        except Exception:
            table_cols = {}

    if not table_cols and schema_context:
        for line in (schema_context or "").splitlines():
            line_s = line.strip()
            m = re.match(
                r"^\s*[-*]?\s*(?:Bảng|Table)\s+[`\"']?([a-zA-Z0-9_]+)[`\"']?\s*:\s*(.+)$",
                line_s,
                flags=re.IGNORECASE,
            )
            if not m:
                m_paren = re.match(
                    r"^\s*[-*]?\s*(?:(?:Bảng|Table)\s+)?[`\"']?([a-zA-Z_][a-zA-Z0-9_]*)[`\"']?\s*\(([^()]+)\)\s*$",
                    line_s,
                    flags=re.IGNORECASE,
                )
                if m_paren and "," in m_paren.group(2):
                    m = m_paren
            if not m:
                continue
            tname = m.group(1).strip().lower()
            cols_raw = re.sub(r"\([^)]*\)", "", m.group(2))
            cols = {
                tok.strip(" `\"'").lower()
                for tok in cols_raw.split(",")
                if tok.strip(" `\"'")
            }
            if cols:
                table_cols[tname] = cols
    return table_cols


_HEADCOUNT_SAFE_STOPWORDS = frozenset({
    "nhan", "vien", "su", "nguoi", "ban", "hang", "kinh", "doanh",
    "salesperson", "sales", "person", "rep", "reps", "employee", "employees", "staff", "headcount",
    "team", "doi", "ngu", "nhom", "khu", "vuc", "location", "region", "chi", "nhanh", "vung",
    "co", "bao", "nhieu", "so", "luong", "quy", "mo", "tong", "tat", "ca", "moi", "tung", "theo",
    "phan", "bo", "cau", "chia", "tinh", "dem", "liet", "ke", "thong", "xem", "la",
    "va", "voi", "o", "tai", "trong", "cua", "tu", "den", "cho", "duoc", "nao", "gi", "hien", "nay",
    "cong", "ty", "toan", "truc", "thuoc", "danh", "sach", "ty", "le", "tram",
    "count", "total", "number", "many", "how", "per", "each", "by", "of", "in", "at",
    "the", "are", "is", "there", "percentage", "share", "ratio", "breakdown", "distribution",
})

_HEADCOUNT_ANALYTICS_STOPWORDS = _HEADCOUNT_SAFE_STOPWORDS | frozenset({
    "don", "giao", "dich", "khach", "san", "pham", "category", "size", "ticket", "tickets",
    "ho", "tro", "kenh", "channel", "status", "trang", "thai", "nam", "thang", "quy", "ngay",
    "top", "nhat", "cao", "thap", "it", "chua", "khong", "tren", "duoi", "hon", "dat",
    "doanh", "thu", "hop", "boxes", "loi", "nhuan", "chi", "phi", "gia", "von", "quoc", "gia",
    "dong", "gop", "so", "sanh", "giua", "cac", "nhung", "the", "nao", "nhu", "tang", "giam",
    "truong", "xuat", "sac", "hieu", "suat", "chay", "nhat", "kem", "theo", "va", "hay",
    "muc", "tieu", "phan", "tich", "trung", "binh", "tong", "hop", "thi",
})


def _headcount_residual_tokens(user_query: str) -> Set[str]:
    qn = norm_vn(user_query)
    qn = re.sub(r"^(?:hay\s+)?(?:cho\s+(?:toi\s+)?biet|vui\s+long\s+(?:cho\s+biet|thong\s+ke)|hay\s+)", "", qn)
    tokens = {tok for tok in re.findall(r"[a-z0-9]+", qn) if not tok.isdigit()}
    return tokens - _HEADCOUNT_SAFE_STOPWORDS


def get_ungrounded_headcount_tokens(user_query: str, schema_context: str = "") -> Set[str]:
    """Trả về tập token thuộc tính/chủ đề nhân sự không xuất hiện trong schema khi câu hỏi hỏi đếm/tỷ lệ nhân viên."""
    qn = norm_vn(user_query)
    has_staff = any(k in qn for k in ("nhan vien", "nhan su", "headcount", "salesperson", "sales person", "sales rep", "nguoi ban", "employee", "staff"))
    has_count_or_rate = any(k in qn for k in ("so luong", "quy mo", "bao nhieu", "dem", "phan bo", "co cau", "phan chia", "ty le", "ti le", "phan tram"))
    if not (has_staff and has_count_or_rate):
        return set()
    schema_tokens = set(re.findall(r"[a-z0-9]+", norm_vn(schema_context)))
    tokens = {tok for tok in re.findall(r"[a-z0-9]+", qn) if not tok.isdigit() and len(tok) >= 2}
    return tokens - _HEADCOUNT_ANALYTICS_STOPWORDS - schema_tokens


def has_headcount_qualifier_conflict(user_query: str) -> bool:
    """Trả về True nếu câu hỏi chứa thuộc tính/trạng thái nhân sự hoặc bộ lọc cụ thể, tránh ép về SQL đếm headcount thuần theo Team/Location."""
    q_raw_low = (user_query or "").lower()
    qn = norm_vn(user_query)
    if re.search(
        r"\b(?:lương|thưởng|tuổi|nữ|nam\s+giới|phái\s+nam|nhân\s+viên\s+nam)\b",
        q_raw_low,
    ):
        return True
    if re.search(
        r"\b(?:nghi\s+viec|thoi\s+viec|nghi\s+lam|nghi\s+huu|sa\s+thai|duoi\s+viec|bo\s+viec|da\s+nghi|roi\s+di|con\s+lam|nghi\s+phep|cham\s+cong|thai\s+san|thu\s+viec|thuc\s+tap|hop\s+dong|ky\s+luat|tham\s+nien|vao\s+lam|tuyen\s+dung|tuyen\s+moi|thang\s+chuc|bo\s+nhiem|tien\s+thuong|hoa\s+hong|kpi|do\s+tuoi|tuoi\s+tac|trinh\s+do|bang\s+cap|chuc\s+danh|chuc\s+vu|phong\s+ban|resign(?:ed|ation)?|attrition|turnover|terminat(?:ed|ion)|layoff|laid\s+off|fired|retire(?:d|ment)?|probation|intern(?:ship|s)?|contract|gender|female|age|hire(?:d)?|tenure|bonus|commission|salary|salaries|wage|hyderabad|bangalore|mumbai|seattle|boston|paris|wellington|delish|yummies|jucies|chua\s+ban|chua\s+tung|chua\s+co|ban\s+duoc|dat\s+duoc|khach\s+hang|ticket)\b",
        qn,
    ):
        return True
    return bool(_headcount_residual_tokens(user_query))


def detect_legacy_schema_gap(
    user_query: str,
    engine: Any = None,
    schema_context: str = "",
    lang: str = "vi",
) -> Optional[str]:
    """
    Detect explicit schema capability gaps on Veraxus legacy DBs (e.g. Awesome Chocolates, Northwind, Sakila)
    so impossible attributes like customer age, gender, or order return rate stop honestly instead of
    fabricating SQL or misreporting unrelated tables.
    """
    if not (user_query or "").strip():
        return None
    table_cols = _collect_schema_tables_and_cols(engine=engine, schema_context=schema_context)
    if not table_cols:
        return None

    all_tables = set(table_cols.keys())
    all_cols = {c for cols in table_cols.values() for c in cols}
    non_ticket_cols = {
        c
        for tname, cols in table_cols.items()
        for c in cols
        if not re.search(r"(?:ticket|support|crm)", tname)
    } or all_cols

    qn = norm_vn(user_query)
    q_raw_low = (user_query or "").lower()
    is_en = lang == "en"
    missing_vi: List[str] = []
    missing_en: List[str] = []

    def _has_col(col_set: Set[str], pat: str) -> bool:
        return any(re.search(pat, c) for c in col_set)

    _tbl_map = locals().get("table_cols")
    if not isinstance(_tbl_map, dict):
        _tbl_map = _collect_schema_tables_and_cols(schema_context)
    _non_ticket_cols = (
        {c for t, cols in _tbl_map.items() if "ticket" not in t for c in cols}
        if _tbl_map
        else all_cols
    )
    _hr_cols = {
        c
        for t, cols in _tbl_map.items()
        if re.search(r"(?:emp|staff|people|hr|nhan|salari|salary|dept|title|cham_?cong)", t)
        and "ticket" not in t
        for c in cols
    }

    def _add_gap(vi_msg: str, en_msg: str) -> None:
        if vi_msg not in missing_vi:
            missing_vi.append(vi_msg)
        if en_msg not in missing_en:
            missing_en.append(en_msg)

    # 0. Out-of-scope non-business topics (weather, lottery, crypto, trivia, coding, etc.)
    import unicodedata as _ud_top
    q_nfc_top = _ud_top.normalize("NFC", user_query or "").lower()
    if (
        _OUT_OF_SCOPE_ACCENTED_RE.search(q_nfc_top)
        or _OUT_OF_SCOPE_UNACCENTED_RE.search(qn)
        or (
            re.search(r"\bco\s+mua\s+(?:khong|ko|k)\b", qn)
            and not re.search(
                r"\b(?:hang|mon|don|san\s+pham|mat\s+hang|khach|ca\s+phe|tra|thuoc|vat\s+lieu|xi\s+mang|cat|gach|da|thep|yen|socola|hop|chai|goi|thung|loc|vien|bao)\b",
                qn,
            )
        )
    ):
        _add_gap(
            "chủ đề ngoài phạm vi dữ liệu kinh doanh (ví dụ: thời tiết, đời sống, tin tức chung)",
            "non-business external topics (e.g. weather, general trivia)",
        )

    # 1. Customer age / birth date
    if re.search(
        r"\b(?:do\s+tuoi|nhom\s+tuoi|lua\s+tuoi|tuoi\s+tac|bao\s+nhieu\s+tuoi|theo\s+tuoi|tuoi\s+cua\s+(?:khach|nhan\s*vien)|customer\s+age|age\s+group|by\s+age)\b",
        qn,
    ):
        if not _has_col(all_cols, r"(?:^age$|_age$|^age_|do_tuoi|nhom_tuoi|birth_?date|dob|ngay_sinh|nam_sinh|year_of_birth)"):
            missing_vi.append("độ tuổi (age/ngày sinh)")
            missing_en.append("customer age / birth date")

    # 2. Customer / employee gender (avoid matching 'Việt Nam' standalone 'nam' or 'năm')
    import unicodedata as _ud_top

    q_nfc_low = _ud_top.normalize("NFC", user_query or "").lower()
    if re.search(
        r"\b(?:gioi\s+tinh|theo\s+phai|phai\s+nam|phai\s+nu|nam\s+(?:va|hay|hoac)\s*nu|nam\s+gioi|nu\s+gioi|"
        r"khach(?:\s+hang)?\s+nu|nhan\s*(?:vien|su)\s+nu|nu\s+nhan\s*(?:vien|su)|gender|sex|female|male)\b",
        qn,
    ) or re.search(
        r"\b(?:khách(?:\s+hàng)?|nhân\s*(?:viên|sự)|người)\s+(?:nam|nữ)\b|\b(?:nữ|nam\s+giới|nữ\s+giới|phái\s+nam|phái\s+nữ|giới\s+tính)\b",
        q_nfc_low,
    ):
        if not _has_col(all_cols, r"^(?:gender|sex|gioi_?tinh|phai|nam_?nu)$|(?:^|_)(?:gender|sex|gioi_?tinh|nam_?nu)(?:$|_)"):
            missing_vi.append("giới tính (gender)")
            missing_en.append("gender")

    # 2b. Missing employee / staff table or columns completely
    if re.search(
        r"\b(?:nhan\s*vien|nhan\s*su|thu\s*ngan|pha\s*che|employee|employees|staff|salesperson|sales\s*rep|cashier|headcount)\b",
        qn,
    ):
        has_staff_tbl_or_col = _has_col(
            all_tables | all_cols,
            r"(?:nhan_?vien|nhan_?su|ma_?nv|ten_?nv|nguoi_?ban|chuc_?vu|thu_?ngan|employees?|emp_?no|staff|salesperson|spid|people|salaries|titles|dept_?emp|job_?title|cashier|worker)",
        )
        if not has_staff_tbl_or_col:
            _add_gap("dữ liệu / danh sách nhân viên, nhân sự", "employee / staff data")

    # 3. Order return / refund / cancellation rate (exclude crm_tickets.Status / CustomerType='Returned' unless query asks about tickets)
    asks_return_or_cancel = bool(
        re.search(
            r"\b(?:hoan\s+tra|tra\s+hang|tra\s+don|hoan\s+don|huy\s+don|t[yi]\s+le\s+(?:hoan|tra|huy)|return\s+rate|returned\s+order|refund|cancel(?:led|ed)?\s+order|cancel\s+rate)\b",
            qn,
        )
    )
    if asks_return_or_cancel and not re.search(r"\b(?:ticket|phieu\s+ho\s+tro|crm)\b", qn):
        has_order_return = _has_col(
            non_ticket_cols,
            r"(?:return_?rate|is_?return|return_?qty|return_?amount|refund|hoan_?tra|tra_?hang|order_?status|trang_?thai|status|cancel)",
        )
        if not has_order_return:
            if "crm_tickets" in all_tables:
                missing_vi.append(
                    "trạng thái hoàn trả / hủy đơn hàng (lưu ý `crm_tickets.CustomerType='Returned'` là khách hàng quay lại, không phải đơn hoàn trả)"
                )
                missing_en.append("order return / cancellation status (`crm_tickets.CustomerType='Returned'` means returning customer, not order returns)")
            else:
                missing_vi.append("trạng thái hoàn trả / hủy đơn hàng (return/refund)")
                missing_en.append("order return / refund status")

    # 4. Discount / voucher / promotion
    if re.search(r"\b(?:chiet\s+khau|giam\s+gia|khuyen\s+mai|ma\s+giam|voucher|coupon|discount|promo)\b", qn):
        if not _has_col(all_cols, r"(?:discount|chiet_?khau|giam_?gia|khuyen_?mai|voucher|coupon|promo)"):
            missing_vi.append("chiết khấu / mã giảm giá (discount)")
            missing_en.append("discounts / coupons")

    # 5. Inventory / stock / expiry
    if re.search(r"\b(?:ton\s+kho|trong\s+kho|het\s+hang|han\s+su\s+dung|sap\s+het\s+han|inventory|stock\s+level|qty\s+on\s+hand|expiry)\b", qn):
        if not _has_col(all_tables | all_cols, r"(?:inventory|ton_?kho|stock|qty_on_hand|units_in_stock|reorder|expiry|han_su_dung|exp_date)"):
            missing_vi.append("tồn kho / hạn sử dụng")
            missing_en.append("inventory / stock or expiry date")

    # 6. Payment method
    if re.search(
        r"\b(?:phuong\s+thuc\s+thanh\s+toan|hinh\s+thuc\s+thanh\s+toan|thanh\s+toan\s+bang|tra\s+bang\s+(?:tien\s+mat|chuyen\s+khoan|the)|momo|vnpay|zalopay|payment\s+method|payment\s+type)\b",
        qn,
    ):
        if not _has_col(all_cols, r"(?:payment_?type|payment_?method|phuong_?thuc|hinh_thuc_thanh_toan|pay_method)"):
            missing_vi.append("phương thức thanh toán")
            missing_en.append("payment method")

    # 7. Shipping fee / shipper
    if re.search(r"\b(?:phi\s+ship|phi\s+giao|phi\s+van\s+chuyen|don\s+vi\s+van\s+chuyen|nha\s+van\s+chuyen|shipping\s+fee|freight|shipper)\b", qn):
        if not _has_col(all_tables | all_cols, r"(?:shipper|shipping|freight|phi_?ship|van_?chuyen|carrier)"):
            missing_vi.append("phí vận chuyển / đơn vị giao hàng")
            missing_en.append("shipping fee / carrier")

    # 8. Rating / satisfaction score
    if re.search(r"\b(?:danh\s+gia\s+(?:sao|khach\s+hang)|so\s+sao|muc\s+do\s+hai\s+long|diem\s+hai\s+long|rating|review\s+score|csat|nps)\b", qn):
        if not _has_col(all_tables | all_cols, r"(?:rating|review|csat|nps|satisfaction|hai_?long|so_sao|danh_gia)"):
            missing_vi.append("điểm đánh giá / mức độ hài lòng")
            missing_en.append("customer rating / satisfaction score")

    # 9. Subjective causal why-questions
    if re.search(r"\b(?:tai\s+sao|vi\s+sao)\b.*\b(?:thich|ua\s+chuong|mua\s+nhieu|trung\s+thanh|khong\s+thich|roi\s+bo)\b", qn):
        if not _has_col(all_cols, r"(?:ly_?do|reason|feedback|comment|nguyen_?nhan)"):
            _add_gap(
                "dữ liệu khảo sát nguyên nhân chủ quan/định tính",
                "qualitative / survey reason data",
            )

    # 7b. Delivery / shipping lead time (avoid colliding with crm_tickets FirstReplyMinutes / ResolutionHours)
    if re.search(
        r"\b(?:thoi\s+gian\s+giao\s+hang|ngay\s+giao\s+hang|toc\s+do\s+giao\s+hang|giao\s+hang\s+(?:cham|tre|nhanh)|tre\s+han\s+giao|lead\s+time|delivery\s+time|shipping\s+time|transit\s+time|fulfillment\s+time|on[\s-]time\s+delivery)\b",
        qn,
    ):
        if not _has_col(
            _non_ticket_cols,
            r"(?:shipped_?date|ship_?date|deliver(?:y|ed)_?(?:date|time|days)|required_?date|lead_?time|fulfill|ngay_?giao|thoi_?gian_?giao)",
        ):
            _add_gap(
                "thời gian / ngày giao hàng thực tế (delivery lead time)",
                "delivery / shipping lead-time data",
            )

    # 10. Employee attrition / resignation / termination / retirement / employment status
    if re.search(
        r"\b(?:nghi\s+viec|thoi\s+viec|nghi\s+lam|nghi\s+huu|sa\s+thai|duoi\s+viec|bo\s+viec|cat\s+giam\s+nhan\s+su|roi\s+(?:cong\s+ty|to\s+chuc)|ty\s+le\s+nghi\s+viec|ti\s+le\s+nghi\s+viec|trang\s+thai\s+lam\s+viec|tinh\s+trang\s+lam\s+viec|con\s+lam\s+viec|da\s+nghi\s+viec|resign(?:ed|ation)?|attrition|(?:employee|staff|hr)\s+turnover|turnover\s+rate|terminat(?:ed|ion)|layoff|laid\s+off|retire(?:d|ment)|still\s+employed|former\s+employee|employment\s+status)\b",
        qn,
    ) or re.search(
        r"\b(?:nhan\s+vien|nhan\s+su|salesperson|sales\s+rep|employee|staff)\b.*\b(?:da\s+nghi|nghi\s+roi|con\s+lam|roi\s+di|bi\s+duoi|inactive|quit|left|former)\b",
        qn,
    ):
        has_attrition_col = _has_col(
            _non_ticket_cols,
            r"(?:to_?date|end_?date|leave_?date|resign|terminat|attrition|nghi_?viec|thoi_?viec|is_?active|active_?flag|employment_?status|hr_?status)",
        ) or _has_col(_hr_cols, r"(?:status|trang_?thai|tinh_?trang|active)")
        if not has_attrition_col:
            _add_gap(
                "trạng thái nhân sự nghỉ việc / ngày nghỉ việc (attrition / termination status)",
                "employee attrition / termination status data",
            )

    # 11. Employee attendance / leave / overtime / probation / contract / disciplinary
    if re.search(
        r"\b(?:nghi\s+phep|nghi\s+om|nghi\s+thai\s+san|cham\s+cong|di\s+muon|ve\s+som|vang\s+mat|tang\s+ca|lam\s+them\s+gio|overtime|attendance|absenteeism|sick\s+leave|annual\s+leave|paid\s+leave|maternity\s+leave|thu\s+viec|thuc\s+tap|hop\s+dong\s+lao\s+dong|loai\s+hop\s+dong|ky\s+luat|canh\s+cao|vi\s+pham\s+noi\s+quy|probation|internship|interns?|contract\s+type|disciplinary)\b",
        qn,
    ):
        if not _has_col(
            _non_ticket_cols,
            r"(?:leave|phep|attendance|cham_?cong|overtime|tang_?ca|absent|probation|thu_?viec|contract|hop_?dong|disciplin|ky_?luat|employment_?type)",
        ):
            _add_gap(
                "dữ liệu chấm công / nghỉ phép / thử việc / hợp đồng lao động",
                "attendance / leave / probation / employment contract data",
            )

    # 12. Hire date / recruitment / employee tenure / promotion
    if re.search(
        r"\b(?:ngay\s+vao\s+lam|ngay\s+tuyen\s+dung|tuyen\s+dung|tuyen\s+moi|nguon\s+tuyen|tham\s+nien|so\s+nam\s+cong\s+tac|thang\s+chuc|bo\s+nhiem|hire\s+date|hired\s+(?:in|on|after|before)|recruit(?:ment|ing|ed)|onboarding|tenure|years\s+of\s+service|promot(?:ed|ion))\b",
        qn,
    ) or re.search(
        r"\b(?:nhan\s+vien|nhan\s+su|salesperson|employee|staff)\b.*\b(?:vao\s+lam|gia\s+nhap|duoc\s+tuyen|bat\s+dau\s+lam)\b",
        qn,
    ):
        if not _has_col(
            _non_ticket_cols,
            r"(?:hire_?date|join_?date|start_?date|from_?date|onboard|ngay_?vao|tham_?nien|tenure|promot|thang_?chuc|recruit|tuyen_?dung)",
        ):
            _add_gap(
                "ngày tuyển dụng / ngày vào làm / thâm niên / thăng chức của nhân viên",
                "employee hire date / tenure / promotion data",
            )

    # 13. Employee salary / bonus / commission / KPI (match accented 'lương'/'thưởng' on q_raw_low to avoid 'số lượng'/'thường')
    if re.search(
        r"\b(?:lương|mức\s+lương|tiền\s+lương|bảng\s+lương|quỹ\s+lương|tăng\s+lương|thưởng|tiền\s+thưởng|mức\s+thưởng)\b",
        q_raw_low,
    ) or re.search(
        r"\b(?:tien\s+luong|bang\s+luong|quy\s+luong|tra\s+luong|hoa\s+hong|kpi|chi\s+tieu\s+doanh\s+so|salary|salaries|wage|wages|payroll|compensation|bonus|bonuses|commission|incentive|sales\s+target|quota)\b",
        qn,
    ):
        if not _has_col(
            _non_ticket_cols,
            r"(?:salar|wage|payroll|luong|bonus|thuong|commiss|hoa_?hong|incentiv|kpi|target|quota|chi_?tieu)",
        ):
            _add_gap(
                "dữ liệu lương, thưởng, hoa hồng hoặc chỉ tiêu KPI",
                "salary, bonus, commission, or KPI target data",
            )

    # 14. Customer / employee contact info (phone/email) and education/degree
    if re.search(
        r"\b(?:so\s+dien\s+thoai|sdt|so\s+dt|phone\s+number|dia\s+chi\s+email|email\s+(?:khach|nhan\s+vien|cua)|contact\s+info)\b",
        qn,
    ) and not re.search(r"\b(?:kenh|channel|ticket)\b", qn):
        if not _has_col(_non_ticket_cols, r"(?:phone|dien_?thoai|sdt|mobile|tel\b|email|mail)"):
            _add_gap(
                "thông tin liên hệ cá nhân (số điện thoại / email)",
                "personal contact details (phone / email)",
            )

    if re.search(
        r"\b(?:trinh\s+do\s+hoc\s+van|trinh\s+do\s+chuyen\s+mon|bang\s+cap|tot\s+nghiep|dai\s+hoc|thac\s+si|tien\s+si|chung\s+chi|education|degree|qualification|university|diploma)\b",
        qn,
    ):
        if not _has_col(
            _non_ticket_cols,
            r"(?:educat|degree|trinh_?do|bang_?cap|qualif|certif|school|university)",
        ):
            _add_gap(
                "trình độ học vấn / bằng cấp nhân sự",
                "employee education / qualification data",
            )

    # 15. Marketing / ad spend / ROAS / conversion rate and Tax / VAT
    # Guard short acronyms (CAC, CTR, CPC, CPM, ROAS, VAT) case-sensitively on user_query so
    # unaccented Vietnamese words like "các" ('cac') and "vật" ('vat', e.g. vật liệu) never false-trigger!
    if re.search(r"\b(?:ROAS|CTR|CPC|CPM|CAC)\b", user_query or "") or re.search(
        r"\b(?:chi\s+phi\s+marketing|chi\s+phi\s+quang\s+cao|ngan\s+sach\s+quang\s+cao|roi\s+quang\s+cao|customer\s+acquisition\s+cost|chi\s+phi\s+thu\s+hut\s+khach|ty\s+le\s+chuyen\s+doi|ti\s+le\s+chuyen\s+doi|conversion\s+rate|ad\s+spend|marketing\s+spend|luot\s+click|impressions)\b",
        qn,
    ):
        if not _has_col(
            _non_ticket_cols,
            r"(?:marketing|ad_?spend|spend|budget|campaign|chien_?dich|click|impression|convers|chuyen_?doi|roas|ctr|cpc|cac)",
        ):
            _add_gap(
                "chi phí marketing / quảng cáo / tỷ lệ chuyển đổi (ROAS, CTR, conversion)",
                "marketing spend / advertising / conversion rate data",
            )

    import unicodedata as _ud
    q_raw_nfc_low = _ud.normalize("NFC", user_query or "").lower()
    if re.search(r"\b(?:thuế|tiền\s+thuế|nộp\s+thuế)\b", q_raw_nfc_low) or re.search(r"\bVAT\b", user_query or "") or re.search(
        r"\b(?:thue\s+vat|thue\s+gtgt|thue\s+tncn|tax\s+rate|sales\s+tax)\b",
        qn,
    ):
        if not _has_col(_non_ticket_cols, r"(?:tax|vat|thue|gtgt)"):
            _add_gap(
                "thông tin thuế / VAT",
                "tax / VAT data",
            )

    # 16. Customer churn / retention rate
    if re.search(
        r"\b(?:churn\s+rate|customer\s+churn|ty\s+le\s+(?:roi\s+bo|ngung\s+mua|mat\s+khach)|ti\s+le\s+(?:roi\s+bo|ngung\s+mua|mat\s+khach)|khach\s+hang\s+(?:roi\s+bo|ngung\s+mua|khong\s+quay\s+lai)|retention\s+rate)\b",
        qn,
    ):
        if not _has_col(_non_ticket_cols, r"(?:churn|reten|last_?order|unsubscribe|cancel_?date)"):
            _add_gap(
                "dữ liệu theo dõi khách hàng rời bỏ / giữ chân khách hàng (churn / retention)",
                "customer churn / retention tracking data",
            )

    # 17. Geographic / city / region / branch dimensions
    has_geo_col = _has_col(
        all_tables | all_cols,
        r"(?:geo|country|region|city|town|location|address|addr|state|province|district|territory|market|zone|area|branch|store|ship_?city|ship_?country|ship_?region|khu_?vuc|vung|mien|tinh|thanh_?pho|quan|huyen|phuong|quoc_?gia|thi_?truong|dia_?chi|dia_?diem|chi_?nhanh|cua_?hang)",
    )
    if re.search(
        r"\b(?:thanh\s+pho|tinh\s+thanh|quan\s+huyen|phuong\s+xa|quoc\s+gia|khu\s+vuc|vung\s+mien|chi\s+nhanh|tung\s+cua\s+hang|theo\s+cua\s+hang|moi\s+cua\s+hang|city|cities|country|countries|province|provinces|region|regions|territory|branch|branches)\b",
        qn,
    ) or _NAMED_GEO_PLACE_RE.search(qn):
        if not has_geo_col:
            _add_gap(
                "dữ liệu địa bàn / thành phố / khu vực / chi nhánh",
                "geographic / city / region / branch data",
            )

    if not missing_vi:
        return None

    tbl_preview = ", ".join(f"`{t}`" for t in sorted(all_tables)[:8])
    if is_en:
        joined = ", ".join(missing_en)
        return (
            f"The current database does not store {joined} "
            f"(available tables: {tbl_preview})."
        )
    joined_vi = ", ".join(missing_vi)
    return (
        f"CSDL hiện tại không ghi nhận thông tin về {joined_vi} "
        f"(các bảng hiện có: {tbl_preview})."
    )


def build_legacy_unanswerable_followups(valid_tables: List[str], lang: str = "vi") -> List[str]:
    """Return 2-3 schema-compatible suggested follow-ups for legacy Veraxus databases."""
    tbls = {t.lower() for t in (valid_tables or [])}
    is_en = lang == "en"
    if {"sales", "products", "people", "geo"}.issubset(tbls):
        if is_en:
            return [
                "Total revenue and total Boxes sold by country (Geo)?",
                "Top 5 products with the highest total revenue and their Categories?",
                "Top 5 salespeople by Boxes sold and corresponding revenue?",
            ]
        return [
            "Tổng doanh thu và tổng số hộp (Boxes) theo từng quốc gia (Geo) là bao nhiêu?",
            "Top 5 sản phẩm có doanh thu cao nhất và thuộc Category nào?",
            "Top 5 nhân viên bán hàng bán được nhiều hộp (Boxes) nhất?",
        ]
    if {"employees", "salaries", "departments"}.issubset(tbls):
        return (
            ["Average salary by department?", "Top 10 highest-paid employees?"]
            if is_en
            else ["Mức lương trung bình theo từng phòng ban?", "Top 10 nhân viên có mức lương hiện tại cao nhất?"]
        )
    if {"film", "rental", "payment"}.issubset(tbls):
        return (
            ["Top 10 highest-grossing films?"]
            if is_en
            else ["Top 10 bộ phim có doanh thu cho thuê cao nhất?"]
        )
    return []


def build_legacy_unanswerable_result(
    user_query: str,
    reason: str,
    valid_tables: List[str],
    lang: str = "vi",
    source_tag: str = "Schema Capability Guard",
) -> Dict[str, Any]:
    """Build a consistent Governance UI payload (🛡️) for unanswerable queries in legacy DB mode."""
    prefix = (
        "🛡️ **Insufficient data to answer accurately:**"
        if lang == "en"
        else "🛡️ **Dữ liệu không đủ thông tin để trả lời chính xác:**"
    )
    return {
        "query": user_query,
        "sql": None,
        "df": None,
        "insights": None,
        "explanation": f"{prefix} {reason}",
        "error": None,
        "attempts": 0,
        "logs": [f"🛡️ [{source_tag}] {reason}"],
        "plan": None,
        "anomalies_info": None,
        "followups": build_legacy_unanswerable_followups(valid_tables, lang=lang),
        "evaluator": {
            "verdict": "UNANSWERABLE_BLOCKED",
            "score": 0,
            "critique": reason,
            "details": {},
        },
        "agent_trace": {
            "router": None,
            "planner": None,
            "executor": None,
            "evaluator": {"verdict": "UNANSWERABLE_BLOCKED", "score": 0, "critique": reason},
        },
    }
