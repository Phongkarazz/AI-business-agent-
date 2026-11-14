"""
Universal messy spreadsheet/CSV/SQLite ingestion engine for DataMate.

Handles Vietnamese SME spreadsheet quirks empirically observed across DataMate:
- NFD/NFC Unicode normalization for file names, sheet names, and strings
- Multiple encodings/BOM and delimiters in CSV
- Streaming XML XLSX reader (~5-10x faster than pure openpyxl cell iteration)
  with openpyxl fallback
- Automatic header-row offset & super-header detection
- Multi-sheet classification: Type A (monthly sheet concatenation with
  sheet-year tracking for yearless dates) vs Type B (distinct entity sheets)
- Split file merging (_1, _2, _2025, _2026) by schema compatibility
- Embedded daily/monthly subtotal and footnote row removal
- Group-aware forward-fill for omitted order-level cells (Rulebook §8)
- Rulebook-compliant deduplication (only on order-keyed tables)
- Mixed currency ('45.000đ', '39k', '1tr140', '19,000.0000'), quantity-unit
  ('3 chai'), Excel serial datetime, and Vietnamese date normalization
- Read-only pass-through & profiling for existing SQLite databases
"""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import os
import pathlib
import re
import sqlite3
import tempfile
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from datamate.temporal import normalize_nfc, parse_date_value


_SPLIT_SUFFIX_RE = re.compile(r"(?:[_\-](?:part|p)?(?:\d{1,2}|20\d{2}))$", re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d{2})")

_SUMMARY_CELL_RE = re.compile(
    r"^(?:"
    r"t[oổ]ng(?:\s+(?:c[oộ]ng|ng[aà]y|th[aá]ng|qu[yý]|n[aă]m|bill|[dđ][oơ]n|ti[eề]n|h[oợ]p))?(?:\s*[:\-]|\s+[\d/.\-]+|\s*$)"
    r"|c[oộ]ng(?:\s+(?:ng[aà]y|th[aá]ng|t[aấ]t\s*c[aả]))?(?:\s*[:\-]|\s+[\d/.\-]+|\s*$)"
    r"|grand\s*total\b"
    r"|sub\s*total\b"
    r"|total\b(?:\s*[:\-]|\s*$)"
    r"|ghi\s*ch[uú]\s*:.*"
    r")$",
    re.IGNORECASE,
)
_BANNER_PREFIX_RE = re.compile(
    r"^(?:s[oổ]\s+chi\s+ti[eế]t|danh\s+s[aá]ch|b[aả]ng\s+k[eê]|s[oổ]\s+ghi|s[oổ]\s+chi\s+ph[ií]|k[yỳ]\s+b[aá]o\s+c[aá]o|tr[aạ]ng\s+th[aá]i\s+[dđ][oơ]n)",
    re.IGNORECASE,
)

_ORDER_ID_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:m[aã][\s_]*(?:h[oó]a[\s_]*[dđ][oơ]n|[dđ][oơ]n(?:[\s_]*h[aà]ng)?|phi[eế]u|gd|ch[uứ]ng[\s_]*t[uừ]|bill)|s[oố][\s_]*(?:phi[eế]u|ct|h[oó]a[\s_]*[dđ][oơ]n|bill|ch[uứ]ng[\s_]*t[uừ])|ma_don|ma_gd|so_ct|so_hoa_don)(?:[\s_.]|$)",
    re.IGNORECASE,
)
_DATE_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:ng[aà]y[\s_a-z0-9]*|th[oờ]i[\s_]*(?:gian|kh[aắ]c|[dđ]i[eể]m)[\s_a-z0-9]*|h[aạ]n[\s_]*(?:s[uử][\s_]*d[uù]ng|d[uù]ng|tr[aả]|thanh[\s_]*to[aá]n)|hsd|sinh[\s_]*nh[aậ]t|t[aạ]o[\s_]*l[uú]c|date|created|updated|ngayban)(?:[\s_.]|$)",
    re.IGNORECASE,
)
_TIME_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:gi[oờ]|gio|th[oờ]i[\s_]*(?:gian|[dđ]i[eể]m)|time)(?:[\s_.]|$)",
    re.IGNORECASE,
)
_QTY_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:s[oố][\s_]*l[uư][oợ]ng|soluong|sluong|sl|s\.l|qty|t[oồ]n[\s_]*(?:cu[oố]i|kho|th[uự]c))(?:[\s_.]|$)",
    re.IGNORECASE,
)
_MONEY_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:gi[aá]|ti[eề]n|tr[iị][\s_]*gi[aá]|amount|price|ph[ií]|n[oợ]|v[oố]n|chi[eế]t[\s_]*kh[aấ]u|gi[aả]m|thu|tr[aả]|c[oò]n[\s_]*l[aạ]i|t\.ti[eề]n)(?:[\s_.]|$)",
    re.IGNORECASE,
)
_ID_TEXT_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:m[aã]|id|sku|barcode|v[aạ]ch|[dđ]i[eệ]n[\s_]*tho[aạ]i|phone|s[dđ]t|di[\s_]*[dđ][oộ]ng|cccd|mst|m[aã][\s_]*s[oố][\s_]*thu[eế]|bi[eể]n[\s_]*s[oố]|s[oố][\s_]*[dđ]i[eệ]n[\s_]*tho[aạ]i|m[aã][\s_]*(?:v[aạ]ch[\s_a-z0-9]*|h[oó]a[\s_]*[dđ][oơ]n|kh[aá]ch[\s_]*h[aà]ng|h[aà]ng[\s_]*h[oó]a|nh[aâ]n[\s_]*vi[eê]n|chi[\s_]*nh[aá]nh|nh[aà][\s_]*cung[\s_]*c[aấ]p|phi[eế]u[\s_a-z0-9]*|ca[\s_]*l[aà]m|khuy[eế]n[\s_]*m[aã]i|giao[\s_]*d[iị]ch[\s_a-z0-9]*|ch[uứ]ng[\s_]*t[uừ]|l[oô]))(?:[\s_.]|$)",
    re.IGNORECASE,
)

_TR_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*tr\s*(\d*)\s*$", re.IGNORECASE)
_K_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*k(?:\s*[dđ])?\s*$", re.IGNORECASE)
_QTY_UNIT_RE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*([a-zA-ZÀ-ỹ][a-zA-ZÀ-ỹ²³0-9/]{0,14})\s*$",
    re.UNICODE,
)
_COL_REF_RE = re.compile(r"^([A-Z]+)")

_EXCEL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_BUILTIN_DATE_NUMFMTS = set(range(14, 23)) | set(range(45, 48))


@dataclass
class ColumnProfile:
    """Profile metadata for one SQL column in an ingested table."""

    raw_name: str
    sql_name: str
    inferred_type: str  # date | datetime | time | integer | real | boolean | text
    null_count: int
    distinct_count: int
    top_values: List[Tuple[Any, int]] = field(default_factory=list)
    sample_values: List[Any] = field(default_factory=list)


@dataclass
class TableProfile:
    """Profile metadata for one cleaned SQLite table."""

    table_name: str
    raw_name: str
    source_files: List[str]
    row_count: int
    columns: List[ColumnProfile]
    raw_to_sql: Dict[str, str]
    notes: List[str] = field(default_factory=list)


@dataclass
class BusinessWorkspace:
    """Self-contained queryable representation of one DataMate business package."""

    business_id: str
    business_dir: pathlib.Path
    db_path: pathlib.Path
    readme_text: str
    tables: Dict[str, TableProfile]
    source_kind: str  # tabular_files | sqlite_passthrough

    def open_connection(self) -> sqlite3.Connection:
        """Open a read-only SQLite connection to the ingested database."""
        uri = f"file:{self.db_path.resolve()}?mode=ro"
        return sqlite3.connect(uri, uri=True)


def _is_blank(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and val != val:  # NaN
        return True
    if isinstance(val, str):
        s = val.strip()
        return s == "" or s.lower() in {"nan", "none", "null", "nat"}
    return False


def to_sql_identifier(name: str, fallback: str = "col") -> str:
    """Convert Vietnamese header/table label into clean lowercase ASCII snake_case."""
    s = normalize_nfc(name).replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"
    return s


def _col_ref_to_idx(ref: str) -> Optional[int]:
    m = _COL_REF_RE.match(ref)
    if not m:
        return None
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _parse_xlsx_styles(zf: zipfile.ZipFile) -> set[int]:
    """Return set of cellXfs style indices formatted as dates/times."""
    date_styles: set[int] = set()
    if "xl/styles.xml" not in zf.namelist():
        return date_styles
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except ET.ParseError:
        return date_styles

    custom_date_fmts: set[int] = set()
    numfmts = root.find(_EXCEL_NS + "numFmts")
    if numfmts is not None:
        for nf in numfmts.findall(_EXCEL_NS + "numFmt"):
            fmt_id = int(nf.attrib.get("numFmtId", -1))
            code = nf.attrib.get("formatCode", "").lower()
            code_clean = re.sub(r'"[^"]*"', "", code)
            if any(tok in code_clean for tok in ("yy", "dd", "hh", "mm:ss")):
                custom_date_fmts.add(fmt_id)

    all_date_ids = _BUILTIN_DATE_NUMFMTS | custom_date_fmts
    cell_xfs = root.find(_EXCEL_NS + "cellXfs")
    if cell_xfs is not None:
        for idx, xf in enumerate(cell_xfs.findall(_EXCEL_NS + "xf")):
            nfid = int(xf.attrib.get("numFmtId", 0))
            if nfid in all_date_ids:
                date_styles.add(idx)
    return date_styles


def read_xlsx_sheets(path: pathlib.Path) -> Dict[str, List[List[Any]]]:
    """
    Read all sheets of an ``.xlsx`` workbook quickly via streaming XML parsing.
    Falls back to ``openpyxl`` if the XML structure is non-standard.
    """
    try:
        sheets: Dict[str, List[List[Any]]] = {}
        with zipfile.ZipFile(path) as zf:
            date_styles = _parse_xlsx_styles(zf)
            sst: List[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                sst_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in sst_root.iter(_EXCEL_NS + "si"):
                    sst.append("".join(t.text or "" for t in si.iter(_EXCEL_NS + "t")))

            wb_xml = ET.fromstring(zf.read("xl/workbook.xml"))
            rels_xml = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rid_to_target = {r.attrib["Id"]: r.attrib["Target"] for r in rels_xml}

            for sh in wb_xml.iter(_EXCEL_NS + "sheet"):
                sname = normalize_nfc(sh.attrib["name"])
                rid = sh.attrib.get(_REL_NS + "id")
                if not rid or rid not in rid_to_target:
                    continue
                target = rid_to_target[rid].lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target

                rows: List[List[Any]] = []
                with zf.open(target) as xf:
                    for _, el in ET.iterparse(xf, events=("end",)):
                        if el.tag == _EXCEL_NS + "row":
                            rvals: List[Any] = []
                            for cell in el.findall(_EXCEL_NS + "c"):
                                ref = cell.attrib.get("r")
                                idx = _col_ref_to_idx(ref) if ref else None
                                if idx is None:
                                    idx = len(rvals)
                                while len(rvals) < idx:
                                    rvals.append(None)

                                ctype = cell.attrib.get("t")
                                v_el = cell.find(_EXCEL_NS + "v")
                                is_el = cell.find(_EXCEL_NS + "is")
                                val: Any = None
                                if ctype == "s" and v_el is not None and v_el.text is not None:
                                    val = sst[int(v_el.text)]
                                elif ctype == "inlineStr" and is_el is not None:
                                    val = "".join(x.text or "" for x in is_el.iter(_EXCEL_NS + "t"))
                                elif ctype == "b" and v_el is not None and v_el.text is not None:
                                    val = v_el.text == "1"
                                elif ctype == "str" and v_el is not None:
                                    val = v_el.text or ""
                                elif ctype == "e":
                                    val = None
                                elif v_el is not None and v_el.text is not None:
                                    txt = v_el.text
                                    s_idx_raw = cell.attrib.get("s")
                                    is_dt_style = s_idx_raw is not None and int(s_idx_raw) in date_styles
                                    try:
                                        num_val: int | float = (
                                            int(txt) if ("." not in txt and "e" not in txt.lower()) else float(txt)
                                        )
                                        if is_dt_style and 0 <= num_val < 1.0:
                                            secs = round(float(num_val) * 86400)
                                            hh, rem = divmod(secs, 3600)
                                            mm, ss = divmod(rem, 60)
                                            val = f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
                                        else:
                                            val = num_val
                                    except ValueError:
                                        val = txt
                                rvals.append(val)
                            rows.append(rvals)
                            el.clear()
                sheets[sname] = rows
        return sheets
    except Exception:
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            return {
                normalize_nfc(name): [list(r) for r in wb[name].iter_rows(values_only=True)]
                for name in wb.sheetnames
            }
        finally:
            wb.close()


def read_csv_rows(path: pathlib.Path) -> List[List[Any]]:
    """Read a CSV file handling UTF-8 BOM, CRLF, and `,`/`;` delimiter detection."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    sample = "\n".join(text.splitlines()[:5])
    sep = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(text.splitlines(), delimiter=sep)
    return [list(row) for row in reader]


def _trim_row(row: Sequence[Any]) -> List[Any]:
    end = len(row)
    while end > 0 and _is_blank(row[end - 1]):
        end -= 1
    return list(row[:end])


def _looks_like_data_cell(val: Any) -> bool:
    if isinstance(val, (bool, int, float, dt.date, dt.datetime)):
        return True
    s = normalize_nfc(str(val))
    if not s:
        return False
    if re.match(r"^(?:ORD|PAY|PN|KH|SP|NV)\d+$", s, re.IGNORECASE):
        return True
    if _TR_RE.match(s) or _K_RE.match(s):
        return True
    if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", s):
        return True
    if re.match(r"^[+-]?\d[\d.,]*(?:đ|vnđ)?$", s, re.IGNORECASE):
        return True
    return False


def detect_header_row(rows: Sequence[Sequence[Any]], max_scan: int = 15) -> int:
    """
    Identify the true column-header row index in top rows of a sheet/CSV.
    Handles title banners, filter banners, blank spacers, and sparse super-headers.
    """
    candidates = rows[:max_scan]
    if not candidates:
        return 0

    best_idx = 0
    best_score = (-1, -1, -1.0, -1, 0)
    for idx, raw_row in enumerate(candidates):
        trimmed = _trim_row(raw_row)
        non_empty_vals = [normalize_nfc(str(c)) for c in trimmed if not _is_blank(c)]
        non_empty = len(non_empty_vals)
        if non_empty < 2:
            continue

        data_like_cnt = sum(1 for c in trimmed if not _is_blank(c) and _looks_like_data_cell(c))
        if data_like_cnt > 0:
            continue

        # Reject 2-cell metadata/filter rows like ["Trạng thái đơn hàng", "Đặt hàng (Đã duyệt)"]
        if non_empty == 2 and _BANNER_PREFIX_RE.match(non_empty_vals[0]):
            continue

        density = non_empty / max(1, len(trimmed))
        unique_cnt = len({v.lower() for v in non_empty_vals})
        # Prefer full-width, gap-free rows with unique labels and earlier placement once width ties
        is_dense = 1 if density >= 0.85 else 0
        is_all_unique = 1 if unique_cnt == non_empty else 0
        score = (is_dense, is_all_unique, round(density, 2), non_empty, -idx)
        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx


def _is_summary_or_note_row(trimmed_row: Sequence[Any], n_cols: int) -> bool:
    non_empty_idx = [i for i, c in enumerate(trimmed_row) if not _is_blank(c)]
    if not non_empty_idx:
        return True

    # Footnote or single-cell label row across multi-column table
    if len(non_empty_idx) == 1 and n_cols >= 3:
        s0 = normalize_nfc(str(trimmed_row[non_empty_idx[0]]))
        if _SUMMARY_CELL_RE.match(s0):
            return True

    matched_note = False
    matched_total = False
    for i in non_empty_idx:
        c = trimmed_row[i]
        if isinstance(c, str):
            s = normalize_nfc(c)
            if re.match(r"^ghi\s*ch[uú]\s*:", s, re.IGNORECASE):
                matched_note = True
                break
            if _SUMMARY_CELL_RE.match(s):
                matched_total = True

    if matched_note:
        return True
    if matched_total and len(non_empty_idx) <= max(2, n_cols - 2):
        return True
    return False


def _forward_fill_order_groups(headers: Sequence[str], rows: List[List[Any]]) -> Tuple[List[List[Any]], int]:
    """
    Implement Rulebook §8: when an order spans multiple rows and continuation lines
    leave order-level cells blank (including the group ID cell itself), inherit from
    the first line of that group. Never copy blank fields across distinct order IDs.
    """
    group_col: Optional[int] = None
    for idx, h in enumerate(headers):
        if _ORDER_ID_COL_RE.search(h):
            group_col = idx
            break
    if group_col is None:
        return rows, 0

    has_blank_group = any(_is_blank(r[group_col]) for r in rows)
    has_filled_group = any(not _is_blank(r[group_col]) for r in rows)
    if not (has_blank_group and has_filled_group):
        return rows, 0

    filled = 0
    prev_header_row: Optional[List[Any]] = None
    for row in rows:
        if not _is_blank(row[group_col]):
            prev_header_row = row
        elif prev_header_row is not None:
            # Copy empty leading/order-level columns from start of the same order group
            changed = False
            for j in range(len(headers)):
                if _is_blank(row[j]) and not _is_blank(prev_header_row[j]):
                    row[j] = prev_header_row[j]
                    changed = True
            if changed:
                filled += 1
    return rows, filled


def _parse_vn_number(val: Any, dot_is_thousands: bool) -> Optional[float | int]:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if val != val:
            return None
        return int(val) if val.is_integer() else val
    if not isinstance(val, str):
        return None

    s = normalize_nfc(val)
    if not s:
        return None
    # Preserve identifiers with leading zeros (phone numbers, zero-padded codes)
    if len(s) > 1 and s[0] == "0" and s.isdigit():
        return None

    m_tr = _TR_RE.match(s)
    if m_tr:
        head = m_tr.group(1).replace(",", ".")
        tail = m_tr.group(2)
        if tail and "." not in head:
            num = float(f"{head}.{tail}") * 1_000_000
        else:
            num = float(head) * 1_000_000
        return round(num) if abs(num - round(num)) < 1e-6 else num

    m_k = _K_RE.match(s)
    if m_k:
        head = m_k.group(1).replace(",", ".")
        num = float(head) * 1_000
        return round(num) if abs(num - round(num)) < 1e-6 else num

    # Strip trailing Vietnamese currency markers (đ, vnđ, vnd)
    s_cur = re.sub(r"(?:\s*(?:vn[dđ]|[dđ]))\s*$", "", s, flags=re.IGNORECASE).strip()
    if not s_cur:
        return None
    if len(s_cur) > 1 and s_cur[0] == "0" and s_cur.isdigit():
        return None

    if "," in s_cur and "." in s_cur:
        if re.match(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$", s_cur):
            s_cur = s_cur.replace(",", "")
        elif re.match(r"^[+-]?\d{1,3}(?:\.\d{3})+(?:,\d+)?$", s_cur):
            s_cur = s_cur.replace(".", "").replace(",", ".")
        else:
            return None
    elif "," in s_cur:
        if re.match(r"^[+-]?\d{1,3}(?:,\d{3})+$", s_cur):
            s_cur = s_cur.replace(",", "")
        elif s_cur.count(",") == 1:
            s_cur = s_cur.replace(",", ".")
        else:
            return None
    elif "." in s_cur:
        if s_cur.count(".") > 1 and re.match(r"^[+-]?\d{1,3}(?:\.\d{3})+$", s_cur):
            s_cur = s_cur.replace(".", "")
        elif dot_is_thousands and re.match(r"^[+-]?\d{1,3}\.\d{3}$", s_cur):
            s_cur = s_cur.replace(".", "")

    try:
        num = float(s_cur)
    except ValueError:
        return None
    if num != num:
        return None
    return round(num) if abs(num - round(num)) < 1e-9 and abs(num) < 1e15 else num


def _infer_dot_thousands(col_name: str, values: Sequence[Any]) -> bool:
    if _MONEY_COL_RE.search(col_name):
        return True
    has_vnd_or_multidot = False
    has_small_decimal = False
    for v in values[:300]:
        if not isinstance(v, str):
            continue
        s = normalize_nfc(v)
        if re.search(r"[dđ]$", s, re.IGNORECASE) or s.count(".") >= 2 or re.search(r",\d{3}$", s):
            has_vnd_or_multidot = True
        elif re.match(r"^[+-]?\d+\.\d{1,2}$", s):
            has_small_decimal = True
    return has_vnd_or_multidot and not has_small_decimal


def _extract_year_hint(name: str) -> Optional[int]:
    m = _YEAR_RE.search(name)
    return int(m.group(1)) if m else None


def _normalize_column_values(
    col_name: str,
    raw_values: List[Any],
    row_years: Sequence[Optional[int]],
) -> Tuple[str, List[Any]]:
    """Infer column SQL type and normalize all cell values cleanly."""
    non_blank = [(idx, v) for idx, v in enumerate(raw_values) if not _is_blank(v)]
    if not non_blank:
        return "text", [None] * len(raw_values)

    # Preserve phone/ID/code text columns strictly as trimmed NFC text
    if _ID_TEXT_COL_RE.search(col_name):
        out: List[Any] = [None] * len(raw_values)
        for idx, v in non_blank:
            if isinstance(v, bool):
                out[idx] = str(v)
            elif isinstance(v, float) and v.is_integer():
                out[idx] = str(int(v))
            else:
                out[idx] = normalize_nfc(str(v))
        return "text", out

    sample = non_blank[:300]

    # 1. Pure boolean check
    bool_cnt = sum(1 for _, v in sample if isinstance(v, bool))
    if bool_cnt == len(sample):
        out_b: List[Any] = [None] * len(raw_values)
        for idx, v in non_blank:
            out_b[idx] = 1 if v else 0
        return "boolean", out_b

    # 2. Pure time-of-day column (e.g. "Giờ" with 0<=float<1, "HH:MM:SS", or Excel datetimes)
    is_time_header = bool(_TIME_COL_RE.search(col_name))
    is_date_header = bool(_DATE_COL_RE.search(col_name)) and not re.search(r"s[oố][\s_]*ng[aà]y", col_name, re.I)

    if is_time_header and not is_date_header:
        time_parsed: List[Tuple[int, str]] = []
        time_ok = 0
        for idx, v in sample:
            if isinstance(v, str) and re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", v.strip()):
                time_ok += 1
            elif isinstance(v, float) and 0 <= v < 1.0:
                time_ok += 1
            else:
                d_iso, t_iso = parse_date_value(v, default_year=row_years[idx])
                if t_iso is not None or d_iso is not None:
                    time_ok += 1
        if time_ok / len(sample) >= 0.7:
            out_t: List[Any] = [None] * len(raw_values)
            has_date_part = False
            for idx, v in non_blank:
                if isinstance(v, str) and re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", v.strip()):
                    parts = v.strip().split(":")
                    hh, mm = int(parts[0]), int(parts[1])
                    ss = int(parts[2]) if len(parts) > 2 else 0
                    out_t[idx] = f"{hh:02d}:{mm:02d}:{ss:02d}"
                elif isinstance(v, float) and 0 <= v < 1.0:
                    secs = round(v * 86400)
                    hh, rem = divmod(secs, 3600)
                    mm, ss = divmod(rem, 60)
                    out_t[idx] = f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
                else:
                    d_iso, t_iso = parse_date_value(v, default_year=row_years[idx])
                    if d_iso and t_iso:
                        has_date_part = True
                        out_t[idx] = f"{d_iso} {t_iso}"
                    elif d_iso:
                        has_date_part = True
                        out_t[idx] = d_iso
                    elif t_iso:
                        out_t[idx] = t_iso
                    else:
                        out_t[idx] = normalize_nfc(str(v))
            return ("datetime" if has_date_part else "time"), out_t

    # 3. Date / Datetime column check (never coerce pure numeric serials on non-date/money cols)
    is_qty_col_hdr = bool(_QTY_COL_RE.search(col_name))
    is_money_or_qty = bool(_MONEY_COL_RE.search(col_name) or is_qty_col_hdr)
    explicit_date_cnt = 0
    for idx, v in sample:
        if isinstance(v, (dt.date, dt.datetime)):
            explicit_date_cnt += 1
        elif isinstance(v, str) and not re.match(r"^\s*\d+(?:\.\d+)?\s*$", v):
            d_iso, _ = parse_date_value(v, default_year=row_years[idx])
            if d_iso is not None:
                explicit_date_cnt += 1

    allow_serial_dates = (is_date_header and not is_qty_col_hdr) or (
        (not is_money_or_qty) and (is_time_header or explicit_date_cnt > 0)
    )
    date_ok = 0
    date_has_time = False
    if allow_serial_dates:
        for idx, v in sample:
            d_iso, t_iso = parse_date_value(v, default_year=row_years[idx])
            if d_iso is not None:
                date_ok += 1
                if t_iso is not None:
                    date_has_time = True
    date_ratio = date_ok / len(sample)
    if allow_serial_dates and (date_ratio >= 0.8 or (is_date_header and date_ratio >= 0.5)):
        out_d: List[Any] = [None] * len(raw_values)
        for idx, v in non_blank:
            d_iso, t_iso = parse_date_value(v, default_year=row_years[idx])
            if d_iso and t_iso:
                out_d[idx] = f"{d_iso} {t_iso}"
                date_has_time = True
            elif d_iso:
                out_d[idx] = d_iso
            else:
                out_d[idx] = normalize_nfc(str(v))
        return ("datetime" if date_has_time else "date"), out_d

    # 4. Money / Numeric column check
    dot_thousands = _infer_dot_thousands(col_name, [v for _, v in sample])
    num_ok = 0
    for _, v in sample:
        if _parse_vn_number(v, dot_thousands) is not None:
            num_ok += 1
    if num_ok / len(sample) >= 0.8:
        out_n: List[Any] = [None] * len(raw_values)
        all_ints = True
        for idx, v in non_blank:
            parsed = _parse_vn_number(v, dot_thousands)
            if parsed is not None:
                out_n[idx] = parsed
                if isinstance(parsed, float) and not parsed.is_integer():
                    all_ints = False
            else:
                # Fallback failed parse to None only if obvious noise, else keep text?
                # Better preserve text column if non-trivial unparsed values remain
                all_ints = False
                out_n[idx] = None
        valid_parsed = sum(1 for x in out_n if x is not None)
        if valid_parsed / len(non_blank) >= 0.85:
            if all_ints:
                out_n = [int(x) if x is not None else None for x in out_n]
                return "integer", out_n
            return "real", out_n

    # 5. Quantity with trailing unit (e.g. '3 chai', '2 gói')
    is_qty_col = bool(_QTY_COL_RE.search(col_name))
    qty_ok = 0
    for _, v in sample:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            qty_ok += 1
        elif isinstance(v, str) and _QTY_UNIT_RE.match(normalize_nfc(v)):
            qty_ok += 1
    if (is_qty_col and qty_ok / len(sample) >= 0.7) or (qty_ok / len(sample) >= 0.9):
        out_q: List[Any] = [None] * len(raw_values)
        all_ints = True
        for idx, v in non_blank:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                num_q: int | float = int(v) if isinstance(v, float) and v.is_integer() else v
                out_q[idx] = num_q
                if isinstance(num_q, float):
                    all_ints = False
            else:
                m_q = _QTY_UNIT_RE.match(normalize_nfc(str(v)))
                if m_q:
                    fval = float(m_q.group(1).replace(",", "."))
                    if fval.is_integer():
                        out_q[idx] = int(fval)
                    else:
                        out_q[idx] = fval
                        all_ints = False
        if sum(1 for x in out_q if x is not None) / len(non_blank) >= 0.85:
            return ("integer" if all_ints else "real"), out_q

    # 6. Default: NFC-normalized stripped text
    out_txt: List[Any] = [None] * len(raw_values)
    for idx, v in non_blank:
        if isinstance(v, float) and v.is_integer():
            out_txt[idx] = str(int(v))
        else:
            out_txt[idx] = normalize_nfc(str(v))
    return "text", out_txt


def _build_column_profiles(
    conn: sqlite3.Connection,
    table_name: str,
    raw_headers: Sequence[str],
    sql_headers: Sequence[str],
    col_types: Sequence[str],
) -> List[ColumnProfile]:
    cur = conn.cursor()
    profiles: List[ColumnProfile] = []
    for raw_h, sql_h, dtype in zip(raw_headers, sql_headers, col_types):
        q_col = f'"{sql_h}"'
        q_tbl = f'"{table_name}"'
        null_cnt = cur.execute(f"SELECT COUNT(*) FROM {q_tbl} WHERE {q_col} IS NULL").fetchone()[0]
        dist_cnt = cur.execute(f"SELECT COUNT(DISTINCT {q_col}) FROM {q_tbl} WHERE {q_col} IS NOT NULL").fetchone()[0]
        top_rows = cur.execute(
            f"SELECT {q_col}, COUNT(*) AS c FROM {q_tbl} WHERE {q_col} IS NOT NULL "
            f"GROUP BY {q_col} ORDER BY c DESC LIMIT 12"
        ).fetchall()
        samples = [r[0] for r in top_rows[:5]]
        profiles.append(
            ColumnProfile(
                raw_name=raw_h,
                sql_name=sql_h,
                inferred_type=dtype,
                null_count=null_cnt,
                distinct_count=dist_cnt,
                top_values=[(r[0], r[1]) for r in top_rows],
                sample_values=samples,
            )
        )
    return profiles


def _parse_raw_sheet(
    raw_rows: List[List[Any]],
    sheet_year: Optional[int],
) -> Optional[Tuple[List[str], List[List[Any]], List[Optional[int]], int, int]]:
    """Extract clean header + body rows (stripped of summary rows) + ffill count."""
    if not raw_rows:
        return None
    hdr_idx = detect_header_row(raw_rows)
    hdr_trim = _trim_row(raw_rows[hdr_idx])
    if not hdr_trim:
        return None

    headers: List[str] = []
    seen: Counter[str] = Counter()
    for i, c in enumerate(hdr_trim):
        lbl = f"col_{i+1}" if _is_blank(c) else normalize_nfc(str(c))
        seen[lbl] += 1
        if seen[lbl] > 1:
            lbl = f"{lbl}_{seen[lbl]}"
        headers.append(lbl)

    n_cols = len(headers)
    body: List[List[Any]] = []
    dropped_summary = 0
    for raw_row in raw_rows[hdr_idx + 1 :]:
        if not raw_row or all(_is_blank(c) for c in raw_row):
            continue
        padded = list(raw_row[:n_cols])
        if len(padded) < n_cols:
            padded.extend([None] * (n_cols - len(padded)))
        if _is_summary_or_note_row(raw_row, n_cols):
            dropped_summary += 1
            continue
        body.append(padded)

    body, ffilled = _forward_fill_order_groups(headers, body)
    row_years = [sheet_year] * len(body)
    return headers, body, row_years, dropped_summary, ffilled


def _strip_split_stem(stem: str) -> str:
    s = normalize_nfc(stem)
    while _SPLIT_SUFFIX_RE.search(s):
        s = _SPLIT_SUFFIX_RE.sub("", s)
    return s


def _create_table_from_parsed(
    conn: sqlite3.Connection,
    table_name: str,
    raw_table_name: str,
    headers: List[str],
    rows: List[List[Any]],
    row_years: List[Optional[int]],
    source_files: List[str],
    notes: List[str],
) -> TableProfile:
    # Make unique SQLite column identifiers
    sql_cols: List[str] = []
    used_sql: set[str] = set()
    raw_to_sql: Dict[str, str] = {}
    for idx, rh in enumerate(headers):
        base = to_sql_identifier(rh, fallback=f"col_{idx+1}")
        cand = base
        k = 2
        while cand in used_sql:
            cand = f"{base}_{k}"
            k += 1
        used_sql.add(cand)
        sql_cols.append(cand)
        raw_to_sql[rh] = cand

    # Transpose & normalize column by column
    col_types: List[str] = []
    norm_cols: List[List[Any]] = []
    n_rows = len(rows)
    for col_idx, rh in enumerate(headers):
        col_vals = [rows[r][col_idx] for r in range(n_rows)]
        dtype, norm_vals = _normalize_column_values(rh, col_vals, row_years)
        col_types.append(dtype)
        norm_cols.append(norm_vals)

    norm_rows = [tuple(norm_cols[c][r] for c in range(len(headers))) for r in range(n_rows)]

    # Deduplicate exact duplicates ONLY if an explicit order/voucher ID column exists (Rulebook §8)
    has_order_id = any(
        _ORDER_ID_COL_RE.search(h) and any(not _is_blank(rows[r][c]) for r in range(min(20, n_rows)))
        for c, h in enumerate(headers)
    )
    if has_order_id and n_rows > 0:
        deduped: List[Tuple[Any, ...]] = []
        seen_rows: set[Tuple[Any, ...]] = set()
        for row_tup in norm_rows:
            if row_tup not in seen_rows:
                seen_rows.add(row_tup)
                deduped.append(row_tup)
        dropped_dup = len(norm_rows) - len(deduped)
        if dropped_dup:
            notes.append(f"deduped_order_rows={dropped_dup}")
        norm_rows = deduped

    sqlite_type_map = {
        "integer": "INTEGER",
        "boolean": "INTEGER",
        "real": "REAL",
        "date": "TEXT",
        "datetime": "TEXT",
        "time": "TEXT",
        "text": "TEXT",
    }
    col_defs = ", ".join(f'"{sc}" {sqlite_type_map[dt_]}' for sc, dt_ in zip(sql_cols, col_types))
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')
    if norm_rows:
        placeholders = ", ".join("?" for _ in sql_cols)
        conn.executemany(f'INSERT INTO "{table_name}" VALUES ({placeholders})', norm_rows)
    conn.commit()

    col_profiles = _build_column_profiles(conn, table_name, headers, sql_cols, col_types)
    return TableProfile(
        table_name=table_name,
        raw_name=raw_table_name,
        source_files=source_files,
        row_count=len(norm_rows),
        columns=col_profiles,
        raw_to_sql=raw_to_sql,
        notes=notes,
    )


def _infer_cached_sqlite_col_type(
    conn: sqlite3.Connection,
    table_name: str,
    col_name: str,
    declared_type: str,
) -> str:
    st = (declared_type or "").upper()
    if "BOOL" in st:
        return "boolean"
    if "INT" in st:
        return "integer"
    if any(k in st for k in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return "real"

    if _DATE_COL_RE.search(col_name) or _TIME_COL_RE.search(col_name):
        rows = conn.execute(
            f'SELECT "{col_name}" FROM "{table_name}" WHERE "{col_name}" IS NOT NULL LIMIT 30'
        ).fetchall()
        vals = [str(r[0]) for r in rows]
        if vals:
            if all(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", v) for v in vals):
                return "datetime"
            if all(re.match(r"^\d{4}-\d{2}-\d{2}$", v) for v in vals):
                return "date"
            if all(re.match(r"^\d{2}:\d{2}:\d{2}$", v) for v in vals):
                return "time"
    return "text"


def _profile_existing_sqlite(
    db_path: pathlib.Path,
    source_files: List[str],
    notes: Optional[List[str]] = None,
) -> Dict[str, TableProfile]:
    """Profile an already-built clean SQLite database read-only."""
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tbl_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        profiles: Dict[str, TableProfile] = {}
        for (tname,) in tbl_rows:
            row_cnt = conn.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            pragma = conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
            raw_headers = [r[1] for r in pragma]
            col_types = [
                _infer_cached_sqlite_col_type(conn, tname, r[1], r[2])
                for r in pragma
            ]
            col_profiles = _build_column_profiles(conn, tname, raw_headers, raw_headers, col_types)
            profiles[tname] = TableProfile(
                table_name=tname,
                raw_name=tname,
                source_files=list(source_files),
                row_count=row_cnt,
                columns=col_profiles,
                raw_to_sql={h: h for h in raw_headers},
                notes=list(notes or []),
            )
        return profiles
    finally:
        conn.close()


def _ingest_sqlite_normalized(
    source_sqlite: pathlib.Path,
    dest_db: pathlib.Path,
) -> Dict[str, TableProfile]:
    """Copy a raw SQLite database into cache, normalizing messy date/number/NFC text columns."""
    if dest_db.exists():
        dest_db.unlink()
    uri = f"file:{source_sqlite.resolve()}?mode=ro"
    src_conn = sqlite3.connect(uri, uri=True)
    dest_conn = sqlite3.connect(dest_db)
    sqlite_type_map = {
        "integer": "INTEGER",
        "boolean": "INTEGER",
        "real": "REAL",
        "date": "TEXT",
        "datetime": "TEXT",
        "time": "TEXT",
        "text": "TEXT",
    }
    try:
        tbl_rows = src_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        profiles: Dict[str, TableProfile] = {}
        src_label = normalize_nfc(source_sqlite.name)
        for (tname,) in tbl_rows:
            pragma = src_conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
            headers = [r[1] for r in pragma]
            declared = [(r[2] or "").upper() for r in pragma]
            raw_rows = src_conn.execute(f'SELECT * FROM "{tname}"').fetchall()
            n_rows = len(raw_rows)

            col_types: List[str] = []
            norm_cols: List[List[Any]] = []
            norm_notes: List[str] = ["sqlite_normalized"]
            norm_year_hints: List[Optional[int]] = [None] * n_rows

            for c_idx, (col_name, decl) in enumerate(zip(headers, declared)):
                col_vals = [raw_rows[r][c_idx] for r in range(n_rows)]
                is_declared_int = "INT" in decl
                is_declared_real = any(k in decl for k in ("REAL", "FLOA", "DOUB", "NUM", "DEC"))
                is_declared_bool = "BOOL" in decl
                is_date_hdr = bool(_DATE_COL_RE.search(col_name))
                has_str = any(isinstance(v, str) for v in col_vals[:300] if v is not None)

                if is_declared_bool and not has_str:
                    col_types.append("boolean")
                    norm_cols.append([None if v is None else (1 if v else 0) for v in col_vals])
                elif is_declared_int and not has_str and not is_date_hdr:
                    col_types.append("integer")
                    norm_cols.append(col_vals)
                elif is_declared_real and not has_str and not is_date_hdr:
                    col_types.append("real")
                    norm_cols.append(col_vals)
                else:
                    dtype, norm_vals = _normalize_column_values(col_name, col_vals, norm_year_hints)
                    col_types.append(dtype)
                    norm_cols.append(norm_vals)

            norm_rows = [tuple(norm_cols[c][r] for c in range(len(headers))) for r in range(n_rows)]
            col_defs = ", ".join(f'"{h}" {sqlite_type_map[dt_]}' for h, dt_ in zip(headers, col_types))
            dest_conn.execute(f'DROP TABLE IF EXISTS "{tname}"')
            dest_conn.execute(f'CREATE TABLE "{tname}" ({col_defs})')
            if norm_rows:
                placeholders = ", ".join("?" for _ in headers)
                dest_conn.executemany(f'INSERT INTO "{tname}" VALUES ({placeholders})', norm_rows)
            dest_conn.commit()

            col_profiles = _build_column_profiles(dest_conn, tname, headers, headers, col_types)
            profiles[tname] = TableProfile(
                table_name=tname,
                raw_name=tname,
                source_files=[src_label],
                row_count=n_rows,
                columns=col_profiles,
                raw_to_sql={h: h for h in headers},
                notes=norm_notes,
            )
        return profiles
    finally:
        src_conn.close()
        dest_conn.close()


def load_business_workspace(
    business_dir: str | pathlib.Path,
    cache_dir: Optional[str | pathlib.Path] = None,
    force_rebuild: bool = False,
) -> BusinessWorkspace:
    """
    Ingest all tabular data files (CSV, XLSX, SQLite) of a business directory
    into a clean, normalized read-queryable SQLite database + schema profile.
    """
    bdir = pathlib.Path(business_dir)
    business_id = bdir.name
    readme_path = bdir / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    data_files = sorted(
        f for f in bdir.iterdir()
        if f.is_file() and not f.name.startswith(".") and f.name != "README.md"
    )
    sqlite_files = [f for f in data_files if f.suffix.lower() in {".sqlite", ".db"}]
    tabular_files = [f for f in data_files if f.suffix.lower() in {".csv", ".xlsx"}]

    out_dir = pathlib.Path(cache_dir) if cache_dir else pathlib.Path(tempfile.gettempdir()) / "datamate_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"{business_id}.sqlite"

    if sqlite_files and not tabular_files:
        db_file = sqlite_files[0]
        if not force_rebuild and db_path.exists() and db_path.stat().st_size > 0:
            try:
                profiles = _profile_existing_sqlite(
                    db_path,
                    source_files=[normalize_nfc(db_file.name)],
                    notes=["sqlite_normalized_cached"],
                )
                if profiles:
                    return BusinessWorkspace(
                        business_id=business_id,
                        business_dir=bdir,
                        db_path=db_path,
                        readme_text=readme_text,
                        tables=profiles,
                        source_kind="sqlite_normalized",
                    )
            except sqlite3.Error:
                pass
        profiles = _ingest_sqlite_normalized(db_file, db_path)
        return BusinessWorkspace(
            business_id=business_id,
            business_dir=bdir,
            db_path=db_path,
            readme_text=readme_text,
            tables=profiles,
            source_kind="sqlite_normalized",
        )

    # Fast cache check: reuse existing SQLite if non-empty and built cleanly, unless force_rebuild
    if not force_rebuild and db_path.exists() and db_path.stat().st_size > 0:
        try:
            profiles = _profile_existing_sqlite(
                db_path,
                source_files=[normalize_nfc(f.name) for f in tabular_files],
                notes=["tabular_cached"],
            )
            if profiles:
                return BusinessWorkspace(
                    business_id=business_id,
                    business_dir=bdir,
                    db_path=db_path,
                    readme_text=readme_text,
                    tables=profiles,
                    source_kind="tabular_files",
                )
        except sqlite3.Error:
            pass

    # Group parsed sheet tables by logical table key (merging Type-A monthly sheets & split files)
    # Keyed by (logical_raw_name, header_signature) so differing schemas stay separated cleanly
    groups: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}

    for fpath in tabular_files:
        fname_nfc = normalize_nfc(fpath.name)
        base_stem = _strip_split_stem(pathlib.Path(fname_nfc).stem)
        file_year = _extract_year_hint(fname_nfc)

        if fpath.suffix.lower() == ".csv":
            raw_rows = read_csv_rows(fpath)
            parsed = _parse_raw_sheet(raw_rows, sheet_year=file_year)
            if not parsed:
                continue
            headers, body, row_years, dropped_sum, ffilled = parsed
            sig = tuple(h.lower() for h in headers)
            gkey = (base_stem, sig)
            grp = groups.setdefault(
                gkey,
                {
                    "raw_name": base_stem,
                    "headers": headers,
                    "rows": [],
                    "row_years": [],
                    "sources": [],
                    "dropped_summary": 0,
                    "ffilled": 0,
                },
            )
            grp["rows"].extend(body)
            grp["row_years"].extend(row_years)
            grp["sources"].append(fname_nfc)
            grp["dropped_summary"] += dropped_sum
            grp["ffilled"] += ffilled

        elif fpath.suffix.lower() == ".xlsx":
            sheets = read_xlsx_sheets(fpath)
            parsed_sheets: List[Tuple[str, Tuple[List[str], List[List[Any]], List[Optional[int]], int, int]]] = []
            for sname, raw_rows in sheets.items():
                syear = _extract_year_hint(sname) or file_year
                parsed = _parse_raw_sheet(raw_rows, sheet_year=syear)
                if parsed is not None:
                    parsed_sheets.append((sname, parsed))

            if not parsed_sheets:
                continue

            # Determine if sheets within this workbook share one schema (Type A) vs multiple tables (Type B)
            sigs = {tuple(h.lower() for h in p[0]) for _, p in parsed_sheets}
            is_multi_table_wb = len(sigs) > 1 or (
                len(parsed_sheets) == 1
                and parsed_sheets[0][0].lower() not in {"sheet1", "sheet 1", "data"}
                and len(tabular_files) == 1
            )

            for sname, (headers, body, row_years, dropped_sum, ffilled) in parsed_sheets:
                logical_name = sname if is_multi_table_wb else base_stem
                sig = tuple(h.lower() for h in headers)
                gkey = (logical_name, sig)
                grp = groups.setdefault(
                    gkey,
                    {
                        "raw_name": logical_name,
                        "headers": headers,
                        "rows": [],
                        "row_years": [],
                        "sources": [],
                        "dropped_summary": 0,
                        "ffilled": 0,
                    },
                )
                # Align columns cleanly in case sheet column order differs while same header names
                if headers == grp["headers"]:
                    grp["rows"].extend(body)
                else:
                    col_map = [headers.index(h) for h in grp["headers"]]
                    grp["rows"].extend([[r[idx] for idx in col_map] for r in body])
                grp["row_years"].extend(row_years)
                src_label = f"{fname_nfc}[{sname}]" if len(parsed_sheets) > 1 else fname_nfc
                grp["sources"].append(src_label)
                grp["dropped_summary"] += dropped_sum
                grp["ffilled"] += ffilled

    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    profiles = {}
    used_table_names: set[str] = set()
    try:
        for (_, _), grp in groups.items():
            t_base = to_sql_identifier(grp["raw_name"], fallback="table")
            t_name = t_base
            k = 2
            while t_name in used_table_names:
                t_name = f"{t_base}_{k}"
                k += 1
            used_table_names.add(t_name)

            notes: List[str] = []
            if grp["dropped_summary"]:
                notes.append(f"dropped_summary_rows={grp['dropped_summary']}")
            if grp["ffilled"]:
                notes.append(f"forward_filled_rows={grp['ffilled']}")

            prof = _create_table_from_parsed(
                conn=conn,
                table_name=t_name,
                raw_table_name=grp["raw_name"],
                headers=grp["headers"],
                rows=grp["rows"],
                row_years=grp["row_years"],
                source_files=grp["sources"],
                notes=notes,
            )
            profiles[t_name] = prof
    finally:
        conn.close()

    return BusinessWorkspace(
        business_id=business_id,
        business_dir=bdir,
        db_path=db_path,
        readme_text=readme_text,
        tables=profiles,
        source_kind="tabular_files",
    )
