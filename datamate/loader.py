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
import hashlib
import json
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

from datamate.temporal import SolarLunarCalendar, normalize_nfc, parse_date_value

_CALENDAR_CACHE: Dict[str, SolarLunarCalendar] = {}


def _discover_lunar_calendar(start_dir: pathlib.Path) -> Optional[SolarLunarCalendar]:
    """Locate and cache the split's ``calendar.csv`` if present at or near the workspace root."""
    cur = pathlib.Path(start_dir)
    for cand in (cur / "calendar.csv", cur.parent / "calendar.csv", cur.parent.parent / "calendar.csv"):
        if cand.is_file():
            key = str(cand.resolve())
            cal = _CALENDAR_CACHE.get(key)
            if cal is None:
                try:
                    cal = SolarLunarCalendar(cand)
                    _CALENDAR_CACHE[key] = cal
                except Exception:
                    return None
            return cal
    return None


_SPLIT_SUFFIX_RE = re.compile(
    r"(?:\s*\(\d+\)$|[._-]\d{6,8}[_-]\d{6,8}$|[._-](?:part|p|ky|k[yỳ]|t|thang|q)?(?:\d{1,2}|20\d{2})$)",
    re.IGNORECASE,
)
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
_SECTION_DIVIDER_RE = re.compile(
    r"^(?:k[yỳ]\s+k[eê]\s+khai\s*:|\d+\.\s*ng[aà]nh\s+ngh[eề]\s*:|ph[oò]ng\s+|b[oộ]\s+ph[aậ]n\s+|nh[oó]m\s+)",
    re.IGNORECASE,
)
_BANNER_PREFIX_RE = re.compile(
    r"^(?:s[oổ]\s+chi\s+ti[eế]t|danh\s+s[aá]ch|b[aả]ng\s+k[eê]|s[oổ]\s+ghi|s[oổ]\s+chi\s+ph[ií]|k[yỳ]\s+b[aá]o\s+c[aá]o|tr[aạ]ng\s+th[aá]i\s+[dđ][oơ]n)",
    re.IGNORECASE,
)

_ORDER_ID_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:"
    r"m[aã][\s_]*(?:h[oó]a[\s_]*[dđ][oôơ]n|[dđ][oôơ]n(?:[\s_]*h[aà]ng)?|phi[eế]u|gd|ch[uứ]ng[\s_]*t[uừ]|bill|[dđ]h|ph\.?nk)"
    r"|s[oố][\s_]*(?:phi[eế]u|ct|h[oó]a[\s_]*[dđ][oôơ]n|bill|ch[uứ]ng[\s_]*t[uừ]|hi[eệ]u|h[dđ])"
    r"|s\.[dđ]\.h[aà]ng|s\.h[dđ]|phi[eế]u"
    r"|ma_don|ma_gd|ma_dh|so_ct|so_hoa_don"
    r")(?:[\s_.]|$)",
    re.IGNORECASE,
)
_GROUP_ID_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:"
    r"m[aã][\s_]*(?:h[oó]a[\s_]*[dđ][oôơ]n|[dđ][oôơ]n(?:[\s_]*h[aà]ng)?|phi[eế]u|gd|ch[uứ]ng[\s_]*t[uừ]|bill|[dđ]h|ph\.?nk|nv|nh[aâ]n[\s_]*vi[eê]n|hs|h[oọ]c[\s_]*sinh|th[eẻ])"
    r"|s[oố][\s_]*(?:phi[eế]u|ct|h[oó]a[\s_]*[dđ][oôơ]n|bill|ch[uứ]ng[\s_]*t[uừ]|hi[eệ]u|h[dđ]|bn)"
    r"|s\.[dđ]\.h[aà]ng|s\.h[dđ]|phi[eế]u"
    r"|ma_don|ma_gd|ma_dh|ma_nv|ma_hs|so_ct|so_hoa_don|so_bn"
    r")(?:[\s_.]|$)",
    re.IGNORECASE,
)
_DATE_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:"
    r"ng[aà]y[\s_a-z0-9\-]*"
    r"|ng(?:\.?$|[\s_.]+(?:[dđ][oơ]n|h[dđ]|t\.?to[aá]n|nh[aậ]p|[dđ]i|[aá]p|l[aấ]y|tr[aả]|thu|[dđ][aặ]t)[a-zÀ-ỹ\s_.]*)"
    r"|th[oờ]i[\s_]*(?:gian|kh[aắ]c|[dđ]i[eể]m)[\s_a-z0-9]*"
    r"|t\.?gian[\s_a-z0-9.]*"
    r"|h[aạ]n[\s_]*(?:s[uử][\s_]*d[uù]ng|d[uù]ng|tr[aả]|thanh[\s_]*to[aá]n)"
    r"|hsd|sinh[\s_]*nh[aậ]t|t[aạ]o[\s_]*l[uú]c|date|created|updated|ngayban"
    r")(?:[\s_.]|$)",
    re.IGNORECASE,
)
_TIME_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:gi[oờ]|gio|th[oờ]i[\s_]*(?:gian|[dđ]i[eể]m)|time)(?:[\s_.]|$)",
    re.IGNORECASE,
)
_QTY_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:s[oố][\s_]*l[uư][oợ]ng|soluong|sluong|sl|s\.l|qty|t[oồ]n[\s_]*(?:cu[oố]i|kho|th[uự]c)|c[aâ]n[\s_]*\(?|s[oố][\s_]*ch[uụ]c|s[oố][\s_]*[dđ][oồ]|b[oỏ][\s_]*h[eé]o)(?:[\s_.]|$)",
    re.IGNORECASE,
)
_HOUR_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:gi[oờ][\s_]*(?:ot|t[aă]ng[\s_]*ca|l[aà]m)|ot|t[aă]ng[\s_]*ca)(?:[\s_.]|$)",
    re.IGNORECASE,
)
_MONEY_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:"
    r"gi[aá]|g\.c[uũ]|g\.m[oớ]i|g\.nh[aậ]p|[dđ]g|ti[eề]n|tr[iị][\s_]*gi[aá]|amount|price|ph[ií]"
    r"|n[oợ]|c[oó]|v[oố]n|chi[eế]t[\s_]*kh[aấ]u|gi[aả]m|thu|chi|tr[aả]|c[oò]n[\s_]*l[aạ]i"
    r"|t\.ti[eề]n|st(?:\s*\(|$)|t\.coc|[dđ][aã][\s_]*tr[aả]|tr[aả][\s_]*li[eề]n|ph[aạ]t|[dđ][eề]n|c[oọ]c"
    r"|l[uươ]+ng|luong|ph[uụ][\s_]*c[aấ]p|thu[\s_]*nh[aậ]p|t[aạ]m[\s_]*[uứ]ng|thu[eế][\s_]*tncn|tr[uừ][\s_]*[a-zÀ-ỹ0-9_]+|bh[\s_]*nv"
    r"|h[oọ]c[\s_]*ph[ií]|th[aà]nh[\s_]*ti[eề]n|t[oổ]ng[\s_]*t|t[oổ]ng[\s_]*thu[\s_]*nh[aậ]p"
    r")(?:[\s_.]|$)",
    re.IGNORECASE,
)
_ID_TEXT_COL_RE = re.compile(
    r"(?:^|[\s_.])(?:"
    r"m[aã]|id|sku|barcode|v[aạ]ch|[dđ]i[eệ]n[\s_]*tho[aạ]i|phone|s[dđ]t|di[\s_]*[dđ][oộ]ng|cccd|mst|m[aã][\s_]*s[oố][\s_]*thu[eế]|bi[eể]n[\s_]*s[oố]|s[oố][\s_]*[dđ]i[eệ]n[\s_]*tho[aạ]i"
    r"|k[yý][\s_]*hi[eệ]u[\s_a-z0-9]*|bks|l[oớ]p|t[oò]a"
    r"|s[oố][\s_]*(?:bn|h[oó]a[\s_]*[dđ][oôơ]n|hi[eệ]u|[dđ]t|tk)|s\.h[dđ]|s\.[dđ]\.h[aà]ng"
    r"|m[aã][\s_]*(?:v[aạ]ch[\s_a-z0-9]*|h[oó]a[\s_]*[dđ][oôơ]n|kh[aá]ch[\s_]*h[aà]ng|h[aà]ng[\s_]*h[oó]a|nh[aâ]n[\s_]*vi[eê]n|nv|hs|chi[\s_]*nh[aá]nh|nh[aà][\s_]*cung[\s_]*c[aấ]p|phi[eế]u[\s_a-z0-9]*|ca[\s_]*l[aà]m|khuy[eế]n[\s_]*m[aã]i|giao[\s_]*d[iị]ch[\s_a-z0-9]*|ch[uứ]ng[\s_]*t[uừ]|l[oô]|vd|v[aậ]n[\s_]*[dđ][oơ]n|[dđ]h|[dđ][oồ]|th[eẻ]|sp)"
    r")(?:[\s_.]|$)",
    re.IGNORECASE,
)

_TR_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*tr\s*(\d*)\s*$", re.IGNORECASE)
_K_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*k(?:\s*[dđ₫])?\s*$", re.IGNORECASE)
_CU_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*c[uủ]\s*$", re.IGNORECASE)
_XI_LIT_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:x[iị]|l[ií]t)\s*$", re.IGNORECASE)
_CANH_CA_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:c[aà]nh|c[aá])\s*$", re.IGNORECASE)
_MUL_EXPR_RE = re.compile(r"^\s*([+-]?[\d.,]+(?:\s*(?:k|tr))?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*$", re.IGNORECASE)
_SCI_NUM_RE = re.compile(r"^\s*[+-]?\d+(?:[.,]\d+)?[eE][+-]?\d+\s*$")
_SPACE_THOUSANDS_RE = re.compile(r"^\s*[+-]?\d{1,3}(?:[\s\u00a0]\d{3})+(?:[.,]\d+)?\s*$")
_QTY_UNIT_RE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*([a-zA-ZÀ-ỹ][a-zA-ZÀ-ỹ²³0-9/]{0,14})\s*$",
    re.UNICODE,
)
_KNOWN_MEAS_UNIT_RE = re.compile(
    r"^(?:h|gi[oờ]|c[aá]i|c[aâ]y|chai|ly|t[aá]ch|h[oộ]p|g[oó]i|lon|th[uù]ng|k[eé]t|b[oó]|c[aà]nh|t[uú]i|bao|v[iỉ]|vi[eê]n|t[aấ]m|cu[oộ]n|kg|g|gr|l|l[ií]t|ml|m|m2|m3|cm|mm|b[iì]nh|l[oố]c|c[aặ]p|b[oộ]|su[aấ]t|t[oô]|q[uủ]a|tr[aá]i|ch[uụ]c|tu[yý]p|l[oọ])$",
    re.IGNORECASE,
)
_COL_REF_RE = re.compile(r"^([A-Z]+)")
_CELL_REF_RC_RE = re.compile(r"^([A-Z]+)(\d+)$")
_COMPOUND_PLUS_RE = re.compile(r"\d+\s*[kK]?\s*\+\s*\d+")
_COMPOUND_TIER_PRICE_RE = re.compile(r"l[eẻ]\s+\d+\s*[kK]?\s*[,/;]\s*(?:th[uù]ng|c[aâ]y|h[oộ]p|l[oố]c)\s+\d+", re.IGNORECASE)
_PREHEADER_KV_KEYS_RE = re.compile(
    r"^(?:l[oớ]p|m[oô]n|h[oọ]c[\s_]*k[yỳ]|kho|chi[\s_]*nh[aá]nh|c[uử]a[\s_]*h[aà]ng|ch[uủ][\s_]*t[aà]i[\s_]*kho[aả]n|t[aà]i[\s_]*kho[aả]n|c[oơ][\s_]*s[oở]|b[oộ][\s_]*ph[aậ]n|nh[aâ]n[\s_]*vi[eê]n)$",
    re.IGNORECASE,
)

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


def _parse_cell_ref(ref: str) -> Optional[Tuple[int, int]]:
    """Parse an Excel cell reference like 'F12' into 0-based (row_idx, col_idx)."""
    m = _CELL_REF_RC_RE.match(ref.strip().upper())
    if not m:
        return None
    col_idx = 0
    for ch in m.group(1):
        col_idx = col_idx * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col_idx - 1


def _parse_merge_range(range_ref: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse an Excel merge range like 'F1:H1' into 0-based (r1, c1, r2, c2)."""
    parts = range_ref.split(":")
    if len(parts) != 2:
        return None
    p1 = _parse_cell_ref(parts[0])
    p2 = _parse_cell_ref(parts[1])
    if p1 is None or p2 is None:
        return None
    r1, c1 = p1
    r2, c2 = p2
    return (min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))


def _excel_serial_to_val(num_val: int | float) -> Any:
    """Convert an Excel date-styled serial number in [0, 80000] to ISO time/date string."""
    if 0 <= num_val < 1.0:
        secs = round(float(num_val) * 86400)
        hh, rem = divmod(secs, 3600)
        mm, ss = divmod(rem, 60)
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    if 20000 <= num_val <= 80000:
        days = int(num_val)
        frac = float(num_val) - days
        d = dt.date(1899, 12, 30) + dt.timedelta(days=days)
        if frac > 1e-6:
            secs = round(frac * 86400)
            t_obj = (dt.datetime.combine(d, dt.time.min) + dt.timedelta(seconds=secs)).time()
            return f"{d.isoformat()} {t_obj.strftime('%H:%M:%S')}"
        return d.isoformat()
    return num_val


def read_xlsx_sheets_with_merges(
    path: pathlib.Path,
) -> Dict[str, Tuple[List[List[Any]], List[Tuple[int, int, int, int]]]]:
    """
    Read all sheets of an ``.xlsx`` workbook quickly via streaming XML parsing,
    returning ``{sheet_name: (rows, merged_ranges)}`` with 0-based merge tuples.
    Falls back to ``openpyxl`` if the XML structure is non-standard.
    """
    try:
        sheets: Dict[str, Tuple[List[List[Any]], List[Tuple[int, int, int, int]]]] = {}
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
                merges: List[Tuple[int, int, int, int]] = []
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
                                        val = _excel_serial_to_val(num_val) if is_dt_style else num_val
                                    except ValueError:
                                        val = txt
                                rvals.append(val)
                            # Pad rows to exact Excel row index (handling skipped blank top rows!)
                            r_attr = el.attrib.get("r")
                            if r_attr and r_attr.isdigit():
                                r_zero = int(r_attr) - 1
                                while len(rows) < r_zero:
                                    rows.append([])
                            rows.append(rvals)
                            el.clear()
                        elif el.tag == _EXCEL_NS + "mergeCell":
                            mref = el.attrib.get("ref")
                            if mref:
                                parsed_m = _parse_merge_range(mref)
                                if parsed_m is not None:
                                    merges.append(parsed_m)
                            el.clear()
                sheets[sname] = (rows, merges)
        return sheets
    except Exception:
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=False, data_only=True)
        try:
            out: Dict[str, Tuple[List[List[Any]], List[Tuple[int, int, int, int]]]] = {}
            for name in wb.sheetnames:
                sh = wb[name]
                s_rows = [list(r) for r in sh.iter_rows(values_only=True)]
                s_merges = [
                    (rng.min_row - 1, rng.min_col - 1, rng.max_row - 1, rng.max_col - 1)
                    for rng in sh.merged_cells.ranges
                ]
                out[normalize_nfc(name)] = (s_rows, s_merges)
            return out
        finally:
            wb.close()


def read_xlsx_sheets(path: pathlib.Path) -> Dict[str, List[List[Any]]]:
    """
    Read all sheets of an ``.xlsx`` workbook quickly via streaming XML parsing.
    Falls back to ``openpyxl`` if the XML structure is non-standard.
    """
    return {sname: rows for sname, (rows, _) in read_xlsx_sheets_with_merges(path).items()}


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
    if re.match(r"^(?:ORD|PAY|PN|KH|SP|NV|HS|TH|BN|PK|VC)\d+$", s, re.IGNORECASE):
        return True
    if _TR_RE.match(s) or _K_RE.match(s):
        return True
    if re.match(r"^\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}$", s):
        return True
    if re.match(r"^\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$", s):
        return True
    if re.match(r"^[+-]?\d[\d.,\s]*(?:vn[dđ]|[dđ]|₫)?$", s, re.IGNORECASE):
        return True
    if _SCI_NUM_RE.match(s):
        return True
    return False


def _is_sequential_header_numbers(trimmed: Sequence[Any]) -> bool:
    """Detect wide matrix column headers like days 1..31 or months 1..12 alongside text labels."""
    seq_nums: List[int] = []
    text_labels = 0
    for c in trimmed:
        if _is_blank(c):
            continue
        if isinstance(c, int) and not isinstance(c, bool) and 1 <= c <= 31:
            seq_nums.append(c)
        elif isinstance(c, float) and c.is_integer() and 1 <= int(c) <= 31:
            seq_nums.append(int(c))
        elif isinstance(c, str) and normalize_nfc(c).isdigit():
            n = int(normalize_nfc(c))
            if 1 <= n <= 31:
                seq_nums.append(n)
            else:
                text_labels += 1
        else:
            text_labels += 1
    if len(seq_nums) < 5 or text_labels < 2:
        return False
    return all(seq_nums[i] + 1 == seq_nums[i + 1] for i in range(len(seq_nums) - 1))


def detect_header_row(
    rows: Sequence[Sequence[Any]],
    max_scan: int = 20,
    merges: Optional[List[Tuple[int, int, int, int]]] = None,
) -> int:
    """
    Identify the true column-header row index in top rows of a sheet/CSV.
    Handles title banners, legend/prose rows, sequential day matrix headers (1..31),
    filter banners, blank spacers, and horizontally merged super-headers.
    """
    candidates = rows[:max_scan]
    if not candidates:
        return 0

    # Estimate body width from lower rows so narrow legend/banner rows never outscore real wide headers
    body_widths = [
        len(_trim_row(r))
        for r in rows[2:50]
        if sum(1 for c in r if not _is_blank(c)) >= 2
    ]
    body_width = 0
    if body_widths:
        sorted_w = sorted(body_widths)
        body_width = sorted_w[int(0.75 * (len(sorted_w) - 1))]

    horiz_span_bonus: Dict[int, int] = Counter()
    if merges:
        for r1, c1, r2, c2 in merges:
            if r1 == r2 and c2 > c1:
                horiz_span_bonus[r1] += (c2 - c1)

    best_idx = 0
    best_score = (-1, -1, -1, -1, -1.0, -1, 0)
    for idx, raw_row in enumerate(candidates):
        trimmed = _trim_row(raw_row)
        non_empty_vals = [normalize_nfc(str(c)) for c in trimmed if not _is_blank(c)]
        non_empty = len(non_empty_vals)
        if non_empty < 2:
            continue

        allow_seq_nums = _is_sequential_header_numbers(trimmed)
        data_like_cnt = 0
        for c in trimmed:
            if _is_blank(c):
                continue
            if allow_seq_nums:
                cs = normalize_nfc(str(c)) if not isinstance(c, (int, float)) else str(int(c))
                if cs.isdigit() and 1 <= int(cs) <= 31:
                    continue
            if _looks_like_data_cell(c):
                data_like_cnt += 1
        if data_like_cnt > 0:
            continue

        # Reject 2-cell metadata/filter rows like ["Trạng thái đơn hàng", "Đặt hàng (Đã duyệt)"]
        if non_empty == 2 and _BANNER_PREFIX_RE.match(non_empty_vals[0]):
            continue
        # Reject key-value metadata lines like ["Lớp", "7A2", "Môn", "Công nghệ"] or ["Năm", "2026"]
        if non_empty in (2, 4) and all(_PREHEADER_KV_KEYS_RE.match(non_empty_vals[k]) for k in range(0, non_empty, 2)):
            continue

        colon_cnt = sum(1 for v in non_empty_vals if ":" in v)
        avg_len = sum(len(v) for v in non_empty_vals) / max(1, non_empty)
        is_prose_legend = (colon_cnt / max(1, non_empty) >= 0.4) or (avg_len > 28.0)

        effective_width = max(len(trimmed), max((c2 + 1 for r1, c1, r2, c2 in (merges or []) if r1 <= idx <= r2), default=0))
        effective_non_empty = min(effective_width, non_empty + horiz_span_bonus.get(idx, 0))
        density = effective_non_empty / max(1, effective_width)

        unique_cnt = len({v.lower() for v in non_empty_vals})
        not_prose = 0 if is_prose_legend else 1
        matches_width = 1 if (body_width < 4 or effective_width >= max(2, int(body_width * 0.6))) else 0
        is_dense = 1 if density >= 0.80 else 0
        is_all_unique = 1 if unique_cnt == non_empty else 0

        score = (not_prose, matches_width, is_dense, is_all_unique, round(density, 2), effective_non_empty, -idx)
        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx


def _resolve_hierarchical_headers(
    raw_rows: Sequence[Sequence[Any]],
    hdr_idx: int,
    merges: Optional[List[Tuple[int, int, int, int]]] = None,
) -> Tuple[List[str], int]:
    """
    Flatten 2-row merged/hierarchical headers and disambiguate duplicate sub-headers
    (e.g. `NGÀY -> Đặt/Lấy/Hẹn trả`, `HỌC KỲ I / HỌC KỲ II -> TX1..CK`) while leaving
    single-row headers with decorative super-headers completely unchanged.
    Returns ``(raw_headers, body_start_row_idx)``.
    """
    hdr_raw = _trim_row(raw_rows[hdr_idx])
    width = len(hdr_raw)
    if merges:
        for r1, c1, r2, c2 in merges:
            if r1 <= hdr_idx <= r2:
                width = max(width, c2 + 1)

    top = [raw_rows[hdr_idx][c] if c < len(raw_rows[hdr_idx]) else None for c in range(width)]

    # Expand horizontal merges across hdr_idx row
    horiz_merged_cols: set[int] = set()
    if merges:
        for r1, c1, r2, c2 in merges:
            if r1 == hdr_idx and r2 == hdr_idx and c2 > c1:
                anchor = top[c1] if c1 < len(top) else None
                for c in range(c1, min(width, c2 + 1)):
                    top[c] = anchor
                    horiz_merged_cols.add(c)

    # Rule A: Complementary sub-header directly below hdr_idx (e.g. pvt_024/Lịch thuê)
    if hdr_idx + 1 < len(raw_rows):
        sub_row_raw = raw_rows[hdr_idx + 1]
        sub = [sub_row_raw[c] if c < len(sub_row_raw) else None for c in range(width)]
        sub_non_empty = [c for c in range(width) if not _is_blank(sub[c])]
        if len(sub_non_empty) >= 2:
            sub_has_data = any(_looks_like_data_cell(sub[c]) for c in sub_non_empty)
            raw_hdr_row = raw_rows[hdr_idx]
            sub_over_merged_or_blank = all(
                (c in horiz_merged_cols) or (c >= len(raw_hdr_row) or _is_blank(raw_hdr_row[c]))
                for c in sub_non_empty
            )
            sub_blank_over_parent = sum(
                1 for c in range(width) if _is_blank(sub[c]) and (c not in horiz_merged_cols) and not _is_blank(top[c])
            )
            if (not sub_has_data) and sub_over_merged_or_blank and sub_blank_over_parent >= 2:
                combined: List[str] = []
                for c in range(width):
                    t_s = normalize_nfc(str(top[c])) if not _is_blank(top[c]) else ""
                    s_s = normalize_nfc(str(sub[c])) if not _is_blank(sub[c]) else ""
                    if t_s and s_s and t_s.lower() != s_s.lower():
                        combined.append(f"{t_s} - {s_s}")
                    elif t_s:
                        combined.append(t_s)
                    elif s_s:
                        combined.append(s_s)
                    else:
                        combined.append(f"col_{c+1}")
                # Deduplicate identical labels safely
                out_a: List[str] = []
                seen_a: Counter[str] = Counter()
                for lbl in combined:
                    seen_a[lbl] += 1
                    out_a.append(f"{lbl}_{seen_a[lbl]}" if seen_a[lbl] > 1 else lbl)
                return out_a, hdr_idx + 2

    # Base labels from hdr_idx
    base_labels: List[str] = []
    for c in range(width):
        base_labels.append(f"col_{c+1}" if _is_blank(top[c]) else normalize_nfc(str(top[c])))

    # Rule B: Disambiguate duplicated sub-headers using an ancestor group row (e.g. HỌC KỲ I / II)
    dup_counts = Counter(lbl.lower() for lbl in base_labels if not lbl.startswith("col_"))
    has_dups = any(cnt >= 2 for cnt in dup_counts.values())
    if has_dups and hdr_idx > 0:
        for anc_idx in (hdr_idx - 1, hdr_idx - 2):
            if anc_idx < 0:
                continue
            anc_raw = raw_rows[anc_idx]
            anc_non_blank = [(c, normalize_nfc(str(anc_raw[c]))) for c in range(min(width, len(anc_raw))) if not _is_blank(anc_raw[c])]
            distinct_anc = {v.lower() for _, v in anc_non_blank}
            # Ancestor must provide >= 2 distinct group labels spanning multiple columns
            if len(distinct_anc) >= 2:
                # Forward-fill ancestor group labels strictly rightward from first anchor
                anc_filled: List[str] = [""] * width
                cur_grp = ""
                for c in range(width):
                    if c < len(anc_raw) and not _is_blank(anc_raw[c]):
                        cur_grp = normalize_nfc(str(anc_raw[c]))
                    if cur_grp:
                        anc_filled[c] = cur_grp
                disambig = False
                new_labels = list(base_labels)
                for c, lbl in enumerate(base_labels):
                    if dup_counts.get(lbl.lower(), 0) >= 2 and anc_filled[c]:
                        new_labels[c] = f"{anc_filled[c]} - {lbl}"
                        disambig = True
                if disambig:
                    out_b: List[str] = []
                    seen_b: Counter[str] = Counter()
                    for lbl in new_labels:
                        seen_b[lbl] += 1
                        out_b.append(f"{lbl}_{seen_b[lbl]}" if seen_b[lbl] > 1 else lbl)
                    return out_b, hdr_idx + 1

    # Rule C: Standard flat single-row headers (uniquify any remaining collisions cleanly)
    out_c: List[str] = []
    seen_c: Counter[str] = Counter()
    for lbl in base_labels:
        seen_c[lbl] += 1
        out_c.append(f"{lbl}_{seen_c[lbl]}" if seen_c[lbl] > 1 else lbl)
    return out_c, hdr_idx + 1


def _split_horizontal_regions(
    raw_rows: List[List[Any]],
    merges: List[Tuple[int, int, int, int]],
) -> List[Tuple[Optional[str], List[List[Any]], List[Tuple[int, int, int, int]]]]:
    """
    Split a sheet into independent side-by-side table regions separated by at least
    one 100%-blank column (e.g. `SỔ CHI` on A:F and `THU` on H:L in `SoChiTieu.xlsx`).
    """
    max_width = max((len(r) for r in raw_rows), default=0)
    if max_width < 7:
        return [(None, raw_rows, merges)]

    non_empty_cols = [False] * max_width
    for r in raw_rows:
        limit = min(max_width, len(r))
        for c in range(limit):
            if not _is_blank(r[c]):
                non_empty_cols[c] = True

    intervals: List[Tuple[int, int]] = []
    c = 0
    while c < max_width:
        while c < max_width and not non_empty_cols[c]:
            c += 1
        if c >= max_width:
            break
        start = c
        while c < max_width and non_empty_cols[c]:
            c += 1
        intervals.append((start, c))

    valid_intervals = [(s, e) for s, e in intervals if (e - s) >= 3]
    if len(valid_intervals) < 2:
        return [(None, raw_rows, merges)]

    # Ensure no merge cell crosses an empty separator column
    for s_idx in range(len(valid_intervals) - 1):
        gap_start = valid_intervals[s_idx][1]
        gap_end = valid_intervals[s_idx + 1][0]
        for _, mc1, _, mc2 in merges:
            if mc1 < gap_end and mc2 >= gap_start:
                return [(None, raw_rows, merges)]

    regions: List[Tuple[Optional[str], List[List[Any]], List[Tuple[int, int, int, int]]]] = []
    for c_start, c_end in valid_intervals:
        sliced_rows: List[List[Any]] = []
        last_non_blank_row = -1
        populated_rows = 0
        for r_idx, row in enumerate(raw_rows):
            sub = [row[col_i] if col_i < len(row) else None for col_i in range(c_start, c_end)]
            if any(not _is_blank(v) for v in sub):
                last_non_blank_row = r_idx
                populated_rows += 1
            sliced_rows.append(sub)
        if populated_rows < 2:
            continue
        sliced_rows = sliced_rows[: last_non_blank_row + 1]
        reg_merges = [
            (r1, c1 - c_start, r2, c2 - c_start)
            for r1, c1, r2, c2 in merges
            if c1 >= c_start and c2 < c_end and r1 <= last_non_blank_row
        ]
        reg_title: Optional[str] = None
        for r in sliced_rows[:4]:
            vals = [normalize_nfc(str(v)) for v in r if not _is_blank(v)]
            if len(vals) == 1 and len(vals[0]) <= 40 and not _looks_like_data_cell(vals[0]):
                reg_title = vals[0]
                break
        regions.append((reg_title, sliced_rows, reg_merges))

    if len(regions) < 2:
        return [(None, raw_rows, merges)]
    return regions


def _extract_pre_header_metadata(
    raw_rows: Sequence[Sequence[Any]],
    hdr_idx: int,
) -> Tuple[Dict[str, str], List[str], Optional[int]]:
    """
    Extract structured key-value metadata (e.g. Lớp=7A1, Môn=Công nghệ, CHU TAI KHOAN=...),
    concise banner notes (electricity/water unit rates, currency unit), and explicit year hints
    from rows above the table header.
    """
    kv_meta: Dict[str, str] = {}
    banner_notes: List[str] = []
    year_hint: Optional[int] = None

    for r in raw_rows[:hdr_idx]:
        vals = [normalize_nfc(str(v)) for v in r if not _is_blank(v)]
        if not vals:
            continue
        joined = " | ".join(vals)
        # Skip boilerplate blank-template forms like "Địa chỉ: .........." or export timestamps
        if "...." in joined or "……" in joined or joined.lower().startswith("thời gian xuất:"):
            continue

        m_yr = re.match(r"^n[aă]m\s+(20\d{2})$", vals[0], re.IGNORECASE)
        if m_yr and len(vals) == 1:
            year_hint = int(m_yr.group(1))

        # Adjacent key-value pairs in rows of length 2 or 4 (e.g. ["Lớp", "7A2", "Môn", "Công nghệ"])
        if len(vals) in (2, 4) and all(_PREHEADER_KV_KEYS_RE.match(vals[k]) for k in range(0, len(vals), 2)):
            for k in range(0, len(vals), 2):
                k_clean = vals[k].rstrip(":").strip()
                v_clean = vals[k + 1].strip()
                if k_clean and v_clean:
                    kv_meta[k_clean] = v_clean
            continue

        # "KEY: VALUE" metadata lines (e.g. "CHU TAI KHOAN: MAI XUAN CANH")
        for cell_txt in vals:
            m_kv = re.match(r"^([^:]{2,32}):\s*(.+)$", cell_txt)
            if m_kv:
                k_clean = m_kv.group(1).strip()
                v_clean = m_kv.group(2).strip()
                if _PREHEADER_KV_KEYS_RE.match(k_clean) and v_clean:
                    kv_meta[k_clean] = v_clean

        if len(joined) <= 120 and len(banner_notes) < 5:
            banner_notes.append(joined)

    return kv_meta, banner_notes, year_hint


def _is_summary_or_note_row(trimmed_row: Sequence[Any], n_cols: int) -> bool:
    non_empty_idx = [i for i, c in enumerate(trimmed_row) if not _is_blank(c)]
    if not non_empty_idx:
        return True

    # Footnote or section-divider single-cell banner inside wide multi-column tables
    if len(non_empty_idx) == 1 and n_cols >= 3:
        col_pos = non_empty_idx[0]
        raw_cell = trimmed_row[col_pos]
        s0 = normalize_nfc(str(raw_cell))
        if _SUMMARY_CELL_RE.match(s0):
            return True
        if n_cols >= 4 and isinstance(raw_cell, str) and not _looks_like_data_cell(raw_cell):
            if _SECTION_DIVIDER_RE.match(s0):
                return True
            if col_pos == 0 and len(s0) >= 4 and s0 == s0.upper() and any(ch.isalpha() for ch in s0):
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


def _is_money_or_qty_header(header: str) -> bool:
    if re.match(
        r"^\s*(?:(?:ng[aà]y|h[aạ]n|th[oờ]i[\s_]*gian|date)(?=$|[\s_.\-])|ng\.)",
        header,
        re.IGNORECASE,
    ):
        return False
    return bool(_MONEY_COL_RE.search(header) or _QTY_COL_RE.search(header) or _HOUR_COL_RE.search(header))


def _forward_fill_order_groups(headers: Sequence[str], rows: List[List[Any]]) -> Tuple[List[List[Any]], int]:
    """
    Implement Rulebook §7/§8: when a multi-row order/voucher/employee group leaves
    group-level header cells blank on continuation lines (or repeats the group ID while
    leaving customer/date cells blank), inherit non-money/non-quantity group attributes
    from the first line of that group. Never forward-fill one-time amounts (`Cọc`, `Thành tiền`),
    quantity columns, or day-matrix cells (e.g. attendance `1..31`).
    """
    if not rows or not headers:
        return rows, 0

    group_col: Optional[int] = None
    for idx, h in enumerate(headers):
        if _GROUP_ID_COL_RE.search(h):
            group_col = idx
            break

    # Detect wide day-matrix tables (e.g. Chấm công 1..31) so we NEVER copy day values from Vào -> Ra rows!
    day_col_indices = {
        idx for idx, h in enumerate(headers) if normalize_nfc(h).isdigit() and 1 <= int(normalize_nfc(h)) <= 31
    }
    is_wide_day_matrix = len(day_col_indices) >= 5

    # Case A: Unkeyed table with leading primary transaction date column blank on continuation rows
    # (never trigger on due/return/expiry dates like han_tra, nor when another date column exists!)
    if group_col is None:
        is_due_or_alt_date = bool(re.search(r"h[aạ]n|tr[aả]|giao|sinh", headers[0], re.IGNORECASE))
        has_other_date_col = any(_DATE_COL_RE.search(h) for h in headers[1:])
        if _DATE_COL_RE.search(headers[0]) and not is_due_or_alt_date and not has_other_date_col:
            has_blank_d = any(_is_blank(r[0]) for r in rows)
            has_filled_d = any(not _is_blank(r[0]) for r in rows)
            if has_blank_d and has_filled_d:
                filled = 0
                prev_date: Any = None
                for row in rows:
                    if not _is_blank(row[0]):
                        prev_date = row[0]
                    elif prev_date is not None and any(not _is_blank(row[j]) for j in range(1, len(headers))):
                        row[0] = prev_date
                        filled += 1
                return rows, filled
        return rows, 0

    # Determine which columns may safely inherit within the same group
    forbidden_cols: set[int] = set(day_col_indices)
    for idx, h in enumerate(headers):
        if _is_money_or_qty_header(h):
            forbidden_cols.add(idx)
        elif is_wide_day_matrix and idx > group_col and re.search(r"v[aà]o|ra|ca|lo[aạ]i", h, re.IGNORECASE):
            forbidden_cols.add(idx)

    # Check if continuation lines either leave group_col blank OR repeat the same group ID with blank dates/customer
    has_blank_group = any(_is_blank(r[group_col]) for r in rows)
    has_filled_group = any(not _is_blank(r[group_col]) for r in rows)
    if not has_filled_group:
        return rows, 0

    has_repeat_group = False
    if not has_blank_group and len(rows) > 1:
        for r_i in range(1, len(rows)):
            cur_id = rows[r_i][group_col]
            prev_id = rows[r_i - 1][group_col]
            if not _is_blank(cur_id) and not _is_blank(prev_id) and normalize_nfc(str(cur_id)) == normalize_nfc(str(prev_id)):
                if any(_is_blank(rows[r_i][j]) and j not in forbidden_cols and not _is_blank(rows[r_i - 1][j]) for j in range(len(headers))):
                    has_repeat_group = True
                    break

    if not (has_blank_group or has_repeat_group):
        return rows, 0

    filled = 0
    prev_header_row: Optional[List[Any]] = None
    prev_group_key: Optional[str] = None
    for row in rows:
        cur_val = row[group_col]
        if not _is_blank(cur_val):
            cur_key = normalize_nfc(str(cur_val))
            if prev_header_row is not None and prev_group_key == cur_key:
                # Repeated group ID row (e.g. P0001 continuation row): inherit missing group metadata only
                changed = False
                for j in range(len(headers)):
                    if j == group_col or j in forbidden_cols:
                        continue
                    # Do not copy free-form Ghi chú onto explicit repeated ID lines
                    if re.search(r"ghi[\s_]*ch[uú]|^gc$", headers[j], re.IGNORECASE):
                        continue
                    if _is_blank(row[j]) and not _is_blank(prev_header_row[j]):
                        row[j] = prev_header_row[j]
                        changed = True
                if changed:
                    filled += 1
            else:
                prev_header_row = row
                prev_group_key = cur_key
        elif prev_header_row is not None:
            # Blank group ID continuation row: copy blank non-money/non-qty/non-day cells
            changed = False
            for j in range(len(headers)):
                if j in forbidden_cols:
                    continue
                if _is_blank(row[j]) and not _is_blank(prev_header_row[j]):
                    row[j] = prev_header_row[j]
                    changed = True
            if changed:
                filled += 1
    return rows, filled


_VI_WORD_DIGITS = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4,
    "năm": 5, "lăm": 5, "nhăm": 5, "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9,
}
_VI_WORD_SCALES = {
    "nghìn": 1_000, "ngàn": 1_000,
    "triệu": 1_000_000,
    "tỷ": 1_000_000_000, "tỉ": 1_000_000_000,
}


def _parse_vi_words_number(text: str) -> Optional[int]:
    """Parse spoken Vietnamese money/number phrases like 'hai triệu tám trăm nghìn'."""
    cleaned = re.sub(r"(?:\s*(?:vn[dđ]|[dđ]|đồng))+$", "", normalize_nfc(text).lower()).strip()
    if not cleaned or any(ch.isdigit() for ch in cleaned):
        return None
    tokens = [tok for tok in re.split(r"[\s,]+", cleaned) if tok]
    if len(tokens) < 2:
        return None

    has_scale = False
    total = 0
    group = 0
    last_unit = 0
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _VI_WORD_DIGITS:
            d = _VI_WORD_DIGITS[tok]
            if i + 1 < len(tokens) and tokens[i + 1] == "trăm":
                group += d * 100
                has_scale = True
                last_unit = 100
                i += 2
            elif i + 1 < len(tokens) and tokens[i + 1] == "mươi":
                group += d * 10
                has_scale = True
                last_unit = 10
                i += 2
            else:
                group += d
                last_unit = 1
                i += 1
        elif tok == "mười":
            group += 10
            has_scale = True
            last_unit = 10
            i += 1
        elif tok in {"linh", "lẻ"}:
            i += 1
        elif tok == "rưỡi":
            if last_unit >= 1000:
                total += last_unit // 2
            elif group > 0:
                group += 5 if last_unit == 10 else 50 if last_unit == 100 else 0
            i += 1
        elif tok in _VI_WORD_SCALES:
            scale = _VI_WORD_SCALES[tok]
            has_scale = True
            total += (group if group > 0 else 1) * scale
            group = 0
            last_unit = scale
            i += 1
        else:
            return None

    if not has_scale:
        return None
    return total + group


def _parse_vn_number(val: Any, dot_is_thousands: bool, allow_slang_money: bool = False) -> Optional[float | int]:
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

    if allow_slang_money:
        m_mul = _MUL_EXPR_RE.match(s)
        if m_mul:
            left_num = _parse_vn_number(m_mul.group(1), dot_is_thousands=dot_is_thousands, allow_slang_money=True)
            right_num = float(m_mul.group(2).replace(",", "."))
            if left_num is not None:
                prod = float(left_num) * right_num
                return round(prod) if abs(prod - round(prod)) < 1e-6 else prod
        spoken_val = _parse_vi_words_number(s)
        if spoken_val is not None:
            return spoken_val

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

    if allow_slang_money:
        m_cu = _CU_RE.match(s)
        if m_cu:
            num = float(m_cu.group(1).replace(",", ".")) * 1_000_000
            return round(num) if abs(num - round(num)) < 1e-6 else num
        m_xi = _XI_LIT_RE.match(s)
        if m_xi:
            num = float(m_xi.group(1).replace(",", ".")) * 100_000
            return round(num) if abs(num - round(num)) < 1e-6 else num
        m_canh = _CANH_CA_RE.match(s)
        if m_canh:
            num = float(m_canh.group(1).replace(",", ".")) * 1_000
            return round(num) if abs(num - round(num)) < 1e-6 else num

    # Strip trailing Vietnamese currency markers (đ, vnđ, vnd, ₫)
    s_cur = re.sub(r"(?:\s*(?:vn[dđ]|[dđ]|₫))\s*$", "", s, flags=re.IGNORECASE).strip()
    if not s_cur:
        return None
    if len(s_cur) > 1 and s_cur[0] == "0" and s_cur.isdigit():
        return None

    # Scientific notation strings (e.g. "2.25E+07", "1E+06")
    if _SCI_NUM_RE.match(s_cur):
        try:
            num = float(s_cur.replace(",", "."))
            if num != num:
                return None
            return round(num) if abs(num - round(num)) < 1e-9 and abs(num) < 1e15 else num
        except ValueError:
            return None

    # Whitespace/NBSP thousands separator (e.g. "17 500 000", "486 779", "60 000")
    if _SPACE_THOUSANDS_RE.match(s_cur):
        s_cur = re.sub(r"[\s\u00a0]+", "", s_cur)

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
    has_dot_3_thousands = False
    has_plain_4plus_int = False
    has_small_decimal = False
    for v in values[:300]:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if isinstance(v, int) and abs(v) >= 1000:
                has_plain_4plus_int = True
            elif isinstance(v, float) and not v.is_integer():
                has_small_decimal = True
            continue
        if not isinstance(v, str):
            continue
        s = normalize_nfc(v)
        if re.search(r"(?:[dđ]|₫)$", s, re.IGNORECASE) or s.count(".") >= 2 or re.search(r",\d{3}$", s):
            has_vnd_or_multidot = True
        elif re.match(r"^[+-]?\d{1,3}\.\d{3}$", s):
            has_dot_3_thousands = True
        elif re.match(r"^[+-]?\d{4,}$", s):
            has_plain_4plus_int = True
        elif re.match(r"^[+-]?\d+\.\d{1,2}$", s):
            has_small_decimal = True
    return (has_vnd_or_multidot or (has_dot_3_thousands and has_plain_4plus_int)) and not has_small_decimal


def _extract_year_hint(name: str) -> Optional[int]:
    m = _YEAR_RE.search(name)
    return int(m.group(1)) if m else None


def _normalize_column_values(
    col_name: str,
    raw_values: List[Any],
    row_years: Sequence[Optional[int]],
    lunar_cal: Optional[SolarLunarCalendar] = None,
    row_anchor_dates: Optional[Sequence[Optional[str]]] = None,
) -> Tuple[str, List[Any]]:
    """Infer column SQL type and normalize all cell values cleanly."""
    non_blank = [(idx, v) for idx, v in enumerate(raw_values) if not _is_blank(v)]
    if not non_blank:
        return "text", [None] * len(raw_values)

    def _anchor(i: int) -> Optional[str]:
        return row_anchor_dates[i] if (row_anchor_dates and i < len(row_anchor_dates)) else None

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
                d_iso, t_iso = parse_date_value(
                    v,
                    default_year=row_years[idx],
                    allow_unix_ts=True,
                    lunar_cal=lunar_cal,
                    anchor_date=_anchor(idx),
                )
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
                    d_iso, t_iso = parse_date_value(
                        v,
                        default_year=row_years[idx],
                        allow_unix_ts=True,
                        lunar_cal=lunar_cal,
                        anchor_date=_anchor(idx),
                    )
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
            d_iso, _ = parse_date_value(
                v,
                default_year=row_years[idx],
                allow_unix_ts=is_date_header,
                lunar_cal=lunar_cal,
                anchor_date=_anchor(idx),
            )
            if d_iso is not None:
                explicit_date_cnt += 1

    allow_serial_dates = (is_date_header and not is_qty_col_hdr) or (
        (not is_money_or_qty) and (is_time_header or explicit_date_cnt > 0)
    )
    date_ok = 0
    date_has_time = False
    if allow_serial_dates:
        for idx, v in sample:
            d_iso, t_iso = parse_date_value(
                v,
                default_year=row_years[idx],
                allow_unix_ts=is_date_header,
                lunar_cal=lunar_cal,
                anchor_date=_anchor(idx),
            )
            if d_iso is not None:
                date_ok += 1
                if t_iso is not None:
                    date_has_time = True
    date_ratio = date_ok / len(sample)
    if allow_serial_dates and (date_ratio >= 0.8 or (is_date_header and date_ratio >= 0.5)):
        out_d: List[Any] = [None] * len(raw_values)
        for idx, v in non_blank:
            d_iso, t_iso = parse_date_value(
                v,
                default_year=row_years[idx],
                allow_unix_ts=is_date_header,
                lunar_cal=lunar_cal,
                anchor_date=_anchor(idx),
            )
            if d_iso and t_iso:
                out_d[idx] = f"{d_iso} {t_iso}"
                date_has_time = True
            elif d_iso:
                out_d[idx] = d_iso
            else:
                out_d[idx] = normalize_nfc(str(v))
        return ("datetime" if date_has_time else "date"), out_d

    # 4. Money / Numeric column check (supporting slang ONLY on explicit money cols + '-' dash sentinels)
    is_money_col = bool(_MONEY_COL_RE.search(col_name) or re.fullmatch(r"t\.?t\.?", normalize_nfc(col_name), re.IGNORECASE))
    dot_thousands = _infer_dot_thousands(col_name, [v for _, v in sample])
    non_dash_sample = [
        (idx, v)
        for idx, v in sample
        if not (isinstance(v, str) and normalize_nfc(v) in {"-", "–", "—"})
    ]
    num_ok = 0
    for _, v in non_dash_sample:
        if _parse_vn_number(v, dot_thousands, allow_slang_money=is_money_col) is not None:
            num_ok += 1
    if non_dash_sample and num_ok / len(non_dash_sample) >= 0.8:
        out_n: List[Any] = [None] * len(raw_values)
        all_ints = True
        non_dash_total = 0
        for idx, v in non_blank:
            if isinstance(v, str) and normalize_nfc(v) in {"-", "–", "—"}:
                out_n[idx] = None
                continue
            non_dash_total += 1
            parsed = _parse_vn_number(v, dot_thousands, allow_slang_money=is_money_col)
            if parsed is not None:
                out_n[idx] = parsed
                if isinstance(parsed, float) and not parsed.is_integer():
                    all_ints = False
            else:
                all_ints = False
                out_n[idx] = None
        valid_parsed = sum(1 for x in out_n if x is not None)
        if non_dash_total > 0 and valid_parsed / non_dash_total >= 0.85:
            if all_ints:
                out_n = [int(x) if x is not None else None for x in out_n]
                return "integer", out_n
            return "real", out_n

    # 5. Quantity / Duration with trailing unit (e.g. '3 chai', '2 gói', '13h', mixed with '5,5' or '3')
    # Never strip units off alphanumeric identifiers like '1C25MAA' — require known measurement unit!
    is_qty_or_hour_col = bool((_QTY_COL_RE.search(col_name) or _HOUR_COL_RE.search(col_name)) and not is_money_col)
    non_dash_q_sample = [
        (idx, v)
        for idx, v in sample
        if not (isinstance(v, str) and normalize_nfc(v) in {"-", "–", "—"})
    ]
    qty_ok = 0
    for _, v in non_dash_q_sample:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            qty_ok += 1
        elif isinstance(v, str):
            s_v = normalize_nfc(v)
            if _parse_vn_number(s_v, False) is not None:
                qty_ok += 1
            else:
                m_q = _QTY_UNIT_RE.match(s_v)
                if m_q and (is_qty_or_hour_col or _KNOWN_MEAS_UNIT_RE.match(m_q.group(2))):
                    qty_ok += 1
    if non_dash_q_sample and ((is_qty_or_hour_col and qty_ok / len(non_dash_q_sample) >= 0.7) or ((not is_money_col) and qty_ok / len(non_dash_q_sample) >= 0.9)):
        out_q: List[Any] = [None] * len(raw_values)
        all_ints = True
        non_dash_q_total = 0
        for idx, v in non_blank:
            if isinstance(v, str) and normalize_nfc(v) in {"-", "–", "—"}:
                out_q[idx] = None
                continue
            non_dash_q_total += 1
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                num_q: int | float = int(v) if isinstance(v, float) and v.is_integer() else v
                out_q[idx] = num_q
                if isinstance(num_q, float):
                    all_ints = False
            else:
                s_v = normalize_nfc(str(v))
                num_direct = _parse_vn_number(s_v, False)
                if num_direct is not None:
                    out_q[idx] = num_direct
                    if isinstance(num_direct, float) and not num_direct.is_integer():
                        all_ints = False
                else:
                    m_q = _QTY_UNIT_RE.match(s_v)
                    if m_q and (is_qty_or_hour_col or _KNOWN_MEAS_UNIT_RE.match(m_q.group(2))):
                        fval = float(m_q.group(1).replace(",", "."))
                        if fval.is_integer():
                            out_q[idx] = int(fval)
                        else:
                            out_q[idx] = fval
                            all_ints = False
        if non_dash_q_total > 0 and sum(1 for x in out_q if x is not None) / non_dash_q_total >= 0.85:
            return ("integer" if all_ints else "real"), out_q

    # 6. Default: NFC-normalized stripped text
    out_txt: List[Any] = [None] * len(raw_values)
    for idx, v in non_blank:
        if isinstance(v, float) and v.is_integer():
            out_txt[idx] = str(int(v))
        else:
            out_txt[idx] = normalize_nfc(str(v))
    return "text", out_txt


def _is_binary_blob_value(v: Any) -> bool:
    """Detect raw binary bytes or hex/JPEG BLOB payloads so they never bloat LLM prompts."""
    if isinstance(v, (bytes, bytearray, memoryview)):
        return True
    if not isinstance(v, str):
        return False
    s = v.strip()
    if s.startswith(("b'\\x", 'b"\\x', "\\xff\\xd8", "\\x89PNG")):
        return True
    if len(s) > 180 and ("\\x" in s[:80] or " " not in s[:100]):
        return True
    return False


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
        safe_top = [
            ("<binary>" if _is_binary_blob_value(r[0]) else r[0], r[1])
            for r in top_rows
        ]
        samples = [v for v, _ in safe_top[:5] if v != "<binary>"]
        profiles.append(
            ColumnProfile(
                raw_name=raw_h,
                sql_name=sql_h,
                inferred_type=dtype,
                null_count=null_cnt,
                distinct_count=dist_cnt,
                top_values=safe_top,
                sample_values=samples,
            )
        )
    return profiles


@dataclass
class _ParsedRegionChunk:
    """Normalized parsed representation of one sheet/region before workbook/cross-file grouping."""

    file_name: str
    base_stem: str
    sheet_name: str
    region_title: Optional[str]
    headers: List[str]
    sql_cols: List[str]
    rows: List[List[Any]]
    row_years: List[Optional[int]]
    kv_meta: Dict[str, str]
    banner_notes: List[str]
    dropped_summary: int
    ffilled: int


def _uniquify_sql_cols(headers: Sequence[str]) -> Tuple[List[str], Dict[str, str]]:
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
    return sql_cols, raw_to_sql


def _header_jaccard(sql_cols_a: Sequence[str], sql_cols_b: Sequence[str]) -> float:
    sa, sb = set(sql_cols_a), set(sql_cols_b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _derive_common_sheet_prefix(sheet_names: Sequence[str]) -> Optional[str]:
    """Derive a clean shared logical prefix for monthly/numbered sheets (e.g. 'Sổ T02.2025' -> 'Sổ')."""
    cleaned: List[str] = []
    for s in sheet_names:
        stem = normalize_nfc(s)
        stem = re.sub(
            r"(?:[\s._\-]*(?:th[aá]ng|t|q)?\s*\d{1,2}(?:[.\-/\s]+20\d{2})?|(?:19|20)\d{2})$",
            "",
            stem,
            flags=re.IGNORECASE,
        ).strip(" ._-")
        if stem:
            cleaned.append(stem)
    if len(cleaned) != len(sheet_names):
        return None
    lows = {c.lower() for c in cleaned}
    if len(lows) == 1 and len(cleaned[0]) >= 2:
        return cleaned[0]
    return None


def _try_parse_kv_record_sheet(
    raw_rows: Sequence[Sequence[Any]],
    sheet_year: Optional[int],
) -> Optional[Tuple[List[str], List[List[Any]], List[Optional[int]], int, int, Dict[str, str], List[str]]]:
    """
    Parse single-column vertical Key: Value block sheets (e.g. receipt blocks separated by '-----'
    in `SoThu.xlsx [2026]`) into clean structured relational rows.
    """
    if not raw_rows:
        return None
    non_empty_widths = [len(_trim_row(r)) for r in raw_rows[:50] if any(not _is_blank(c) for c in r)]
    if not non_empty_widths or max(non_empty_widths) > 1:
        return None

    kv_lines = 0
    sep_lines = 0
    lines: List[str] = []
    for r in raw_rows:
        s = normalize_nfc(str(r[0])) if (r and not _is_blank(r[0])) else ""
        lines.append(s)
        if re.match(r"^(?:-{3,}|={3,}|\*{3,})$", s):
            sep_lines += 1
        elif re.match(r"^[^:]{1,28}:\s+.+$", s):
            kv_lines += 1

    if kv_lines < 6 or (sep_lines == 0 and kv_lines < 12):
        return None

    records: List[Dict[str, str]] = []
    ordered_keys: List[str] = []
    key_set: set[str] = set()
    cur: Dict[str, str] = {}
    anchor_key: Optional[str] = None
    banner_notes: List[str] = []

    for s in lines:
        if not s or re.match(r"^(?:-{3,}|={3,}|\*{3,})$", s):
            if cur:
                records.append(cur)
                cur = {}
            continue
        m_kv = re.match(r"^([^:]{1,28}):\s*(.*)$", s)
        if m_kv:
            k = m_kv.group(1).strip()
            v = m_kv.group(2).strip()
            if anchor_key is None and cur == {} and len(records) == 0:
                anchor_key = k
            elif anchor_key and k == anchor_key and cur and k in cur:
                records.append(cur)
                cur = {}
            cur[k] = v
            if k not in key_set:
                key_set.add(k)
                ordered_keys.append(k)
        elif not records and not cur and len(banner_notes) < 2 and len(s) <= 80:
            banner_notes.append(s)
    if cur:
        records.append(cur)

    if len(records) < 2 or len(ordered_keys) < 2:
        return None

    body = [[rec.get(k) for k in ordered_keys] for rec in records]
    return ordered_keys, body, [sheet_year] * len(body), 0, 0, {}, banner_notes


def _try_parse_embedded_kv_grid_sheet(
    raw_rows: Sequence[Sequence[Any]],
    sheet_year: Optional[int],
) -> Optional[Tuple[List[str], List[List[Any]], List[Optional[int]], int, int, Dict[str, str], List[str]]]:
    """
    Parse weekly calendar/schedule matrices (columns like 'Tuần', 'Thứ 2', ..., 'Chủ nhật')
    whose cells store newline-separated pipe-delimited `Key: Value | Key2: Value2` records
    (e.g. `DonDat.xlsx [T5.2026..T8.2026]`) into clean structured rows.
    """
    if len(raw_rows) < 2:
        return None
    hdr = [normalize_nfc(str(c)) if not _is_blank(c) else "" for c in _trim_row(raw_rows[0])]
    if len(hdr) < 4:
        return None
    has_weekday_cols = sum(
        1 for h in hdr if re.match(r"^(?:th[uứ]\s*[2-7]|ch[uủ]\s*nh[aậ]t|t[2-7]|cn)$", h, re.IGNORECASE)
    ) >= 3
    if not has_weekday_cols:
        return None

    records: List[Dict[str, str]] = []
    ordered_keys: List[str] = []
    key_set: set[str] = set()

    for r in raw_rows[1:]:
        for cell in r:
            if _is_blank(cell):
                continue
            cell_txt = str(cell)
            if "|" not in cell_txt or ":" not in cell_txt:
                continue
            for raw_line in cell_txt.splitlines():
                line = normalize_nfc(raw_line)
                if not line or "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|") if ":" in p]
                if len(parts) < 3:
                    continue
                rec: Dict[str, str] = {}
                for part in parts:
                    k, v = part.split(":", 1)
                    k_clean = k.strip()
                    v_clean = v.strip()
                    if k_clean and v_clean:
                        rec[k_clean] = v_clean
                        if k_clean not in key_set:
                            key_set.add(k_clean)
                            ordered_keys.append(k_clean)
                if len(rec) >= 3:
                    records.append(rec)

    if not records or len(ordered_keys) < 3:
        return None

    body = [[rec.get(k) for k in ordered_keys] for rec in records]
    return ordered_keys, body, [sheet_year] * len(body), 0, 0, {}, []


def _parse_raw_sheet(
    raw_rows: List[List[Any]],
    sheet_year: Optional[int],
    merges: Optional[List[Tuple[int, int, int, int]]] = None,
) -> Optional[Tuple[List[str], List[List[Any]], List[Optional[int]], int, int, Dict[str, str], List[str]]]:
    """
    Extract flattened headers, pre-header metadata, clean body rows (stripped of
    summary/divider rows), forward-fill count, and effective row year hints.
    Also transparently unpacks single-column KV receipt logs and pipe-KV calendar grids.
    """
    if not raw_rows:
        return None

    kv_block = _try_parse_kv_record_sheet(raw_rows, sheet_year)
    if kv_block is not None:
        return kv_block

    kv_grid = _try_parse_embedded_kv_grid_sheet(raw_rows, sheet_year)
    if kv_grid is not None:
        return kv_grid
    hdr_idx = detect_header_row(raw_rows, merges=merges)
    kv_meta, banner_notes, preheader_year = _extract_pre_header_metadata(raw_rows, hdr_idx)
    effective_year = sheet_year or preheader_year

    headers, body_start_idx = _resolve_hierarchical_headers(raw_rows, hdr_idx, merges=merges)
    if not headers:
        return None

    n_cols = len(headers)
    body: List[List[Any]] = []
    dropped_summary = 0
    for raw_row in raw_rows[body_start_idx:]:
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
    row_years = [effective_year] * len(body)
    return headers, body, row_years, dropped_summary, ffilled, kv_meta, banner_notes


def _strip_split_stem(stem: str) -> str:
    s = normalize_nfc(stem)
    while True:
        nxt = _SPLIT_SUFFIX_RE.sub("", s).strip(" _.-")
        if not nxt or nxt == s:
            break
        s = nxt
    return s


_INDEX_KEY_COL_RE = re.compile(
    r"^(?:ma_|so_|id$|phieu|phong|khach|source_sheet|ngay)|(?:_id|_code)$",
    re.IGNORECASE,
)


def _create_table_indexes(
    conn: sqlite3.Connection,
    table_name: str,
    columns: Sequence[ColumnProfile],
    row_count: int,
) -> None:
    """Create lightweight B-tree indexes on date/key columns for larger tables to avoid full-scan timeouts."""
    if row_count < 200:
        return
    indexed = 0
    for cp in columns:
        if cp.distinct_count <= 1:
            continue
        if cp.inferred_type not in ("date", "datetime") and not _INDEX_KEY_COL_RE.search(cp.sql_name):
            continue
        safe_idx = re.sub(r"[^a-zA-Z0-9_]", "_", f"idx_{table_name}_{cp.sql_name}")
        try:
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{safe_idx}" ON "{table_name}" ("{cp.sql_name}")')
            indexed += 1
        except sqlite3.Error:
            pass
        if indexed >= 6:
            break
    if indexed:
        conn.commit()


def _prescan_row_date_anchors(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    row_years: Optional[Sequence[Optional[int]]] = None,
) -> Tuple[List[Optional[int]], List[Optional[str]]]:
    """
    Pre-scan explicit solar dates across date columns per row so bare lunar dates
    (e.g. ``17/2 ÂL``) and yearless ``DD/MM`` cells inherit accurate row-level anchors.
    """
    n_rows = len(rows)
    eff_years: List[Optional[int]] = list(row_years) if row_years else [None] * n_rows
    if len(eff_years) < n_rows:
        eff_years.extend([None] * (n_rows - len(eff_years)))
    elif len(eff_years) > n_rows:
        eff_years = eff_years[:n_rows]

    anchors: List[Optional[str]] = [None] * n_rows
    date_indices = [
        idx
        for idx, rh in enumerate(headers)
        if _DATE_COL_RE.search(rh) and not re.search(r"s[oố][\s_]*ng[aà]y", rh, re.I)
    ]
    if not date_indices or n_rows == 0:
        return eff_years, anchors

    for r in range(n_rows):
        row = rows[r]
        for c_idx in date_indices:
            if c_idx >= len(row):
                continue
            cell = row[c_idx]
            if _is_blank(cell):
                continue
            d_iso, _ = parse_date_value(cell, default_year=None, allow_unix_ts=False)
            if d_iso and re.match(r"^\d{4}-\d{2}-\d{2}$", d_iso):
                if anchors[r] is None:
                    anchors[r] = d_iso
                if eff_years[r] is None:
                    eff_years[r] = int(d_iso[:4])

    last_y: Optional[int] = None
    for r in range(n_rows):
        if eff_years[r] is not None:
            last_y = eff_years[r]
        elif last_y is not None:
            eff_years[r] = last_y
    next_y: Optional[int] = None
    for r in range(n_rows - 1, -1, -1):
        if eff_years[r] is not None:
            next_y = eff_years[r]
        elif next_y is not None:
            eff_years[r] = next_y
    return eff_years, anchors


def _create_table_from_parsed(
    conn: sqlite3.Connection,
    table_name: str,
    raw_table_name: str,
    headers: List[str],
    rows: List[List[Any]],
    row_years: List[Optional[int]],
    source_files: List[str],
    notes: List[str],
    lunar_cal: Optional[SolarLunarCalendar] = None,
) -> TableProfile:
    sql_cols, raw_to_sql = _uniquify_sql_cols(headers)

    # Transpose & normalize column by column (with row-level date anchor & bare lunar calendar resolution)
    eff_row_years, row_anchor_dates = _prescan_row_date_anchors(headers, rows, row_years)
    col_types: List[str] = []
    norm_cols: List[List[Any]] = []
    n_rows = len(rows)
    for col_idx, rh in enumerate(headers):
        col_vals = [rows[r][col_idx] for r in range(n_rows)]
        dtype, norm_vals = _normalize_column_values(
            rh,
            col_vals,
            eff_row_years,
            lunar_cal=lunar_cal,
            row_anchor_dates=row_anchor_dates,
        )
        col_types.append(dtype)
        norm_cols.append(norm_vals)

    norm_rows = [tuple(norm_cols[c][r] for c in range(len(headers))) for r in range(n_rows)]

    # Deduplicate exact duplicates ONLY if an explicit order/voucher ID column exists (Rulebook §7/§8)
    # Exclude synthetic provenance columns (source_sheet, source_file) so overlapping dumps dedup cleanly
    provenance_indices = {idx for idx, sc in enumerate(sql_cols) if sc in {"source_sheet", "_source_sheet", "source_file", "_source_file"}}
    has_order_id = any(
        _ORDER_ID_COL_RE.search(h) and any(not _is_blank(rows[r][c]) for r in range(min(20, n_rows)))
        for c, h in enumerate(headers)
    )
    if has_order_id and n_rows > 0:
        deduped: List[Tuple[Any, ...]] = []
        seen_rows: set[Tuple[Any, ...]] = set()
        for row_tup in norm_rows:
            if provenance_indices:
                dedup_key = tuple(v for idx, v in enumerate(row_tup) if idx not in provenance_indices)
            else:
                dedup_key = row_tup
            if dedup_key not in seen_rows:
                seen_rows.add(dedup_key)
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
    _create_table_indexes(conn, table_name, col_profiles, len(norm_rows))

    # Bridge profiler hints for Phase 2 (compound expressions & wide day matrices)
    compound_cols: List[str] = []
    day_header_count = 0
    for rh, cp in zip(headers, col_profiles):
        if normalize_nfc(rh).isdigit() and 1 <= int(normalize_nfc(rh)) <= 31:
            day_header_count += 1
        if cp.inferred_type == "text":
            comp_hits = 0
            for sval, _cnt in cp.top_values:
                if isinstance(sval, str) and (_COMPOUND_PLUS_RE.search(sval) or _COMPOUND_TIER_PRICE_RE.search(sval)):
                    comp_hits += 1
            if comp_hits >= 1:
                compound_cols.append(cp.sql_name)
    if compound_cols:
        notes.append(f"compound_cols={','.join(compound_cols[:4])}")
    if day_header_count >= 20:
        notes.append("wide_day_matrix=true")

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
    saved_table_meta: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, TableProfile]:
    """Profile an already-built clean SQLite database read-only, restoring saved metadata if available."""
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    meta_map = saved_table_meta or {}
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
            tmeta = meta_map.get(tname, {})
            profiles[tname] = TableProfile(
                table_name=tname,
                raw_name=tmeta.get("raw_name") or tname,
                source_files=list(tmeta.get("source_files") or source_files),
                row_count=row_cnt,
                columns=col_profiles,
                raw_to_sql={h: h for h in raw_headers},
                notes=list(tmeta.get("notes") or notes or []),
            )
        return profiles
    finally:
        conn.close()


def _ingest_sqlite_normalized(
    source_sqlite: pathlib.Path,
    dest_db: Optional[pathlib.Path] = None,
    *,
    dest_conn: Optional[sqlite3.Connection] = None,
    used_table_names: Optional[set[str]] = None,
    lunar_cal: Optional[SolarLunarCalendar] = None,
) -> Dict[str, TableProfile]:
    """Copy a raw SQLite database into cache, normalizing messy date/number/NFC text columns."""
    if lunar_cal is None:
        lunar_cal = _discover_lunar_calendar(source_sqlite.parent)
    owns_dest = dest_conn is None
    if owns_dest:
        assert dest_db is not None
        if dest_db.exists():
            dest_db.unlink()
        dest_conn = sqlite3.connect(dest_db)
    assert dest_conn is not None
    used_names = used_table_names if used_table_names is not None else set()

    uri = f"file:{source_sqlite.resolve()}?mode=ro"
    src_conn = sqlite3.connect(uri, uri=True)
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
        src_prefix = to_sql_identifier(source_sqlite.stem, fallback="db")
        for (tname,) in tbl_rows:
            pragma = src_conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
            headers = [r[1] for r in pragma]
            declared = [(r[2] or "").upper() for r in pragma]
            raw_rows = src_conn.execute(f'SELECT * FROM "{tname}"').fetchall()
            n_rows = len(raw_rows)

            col_types: List[str] = []
            norm_cols: List[List[Any]] = []
            norm_notes: List[str] = ["sqlite_normalized"]
            norm_year_hints, row_anchor_dates = _prescan_row_date_anchors(headers, raw_rows)

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
                    dtype, norm_vals = _normalize_column_values(
                        col_name,
                        col_vals,
                        norm_year_hints,
                        lunar_cal=lunar_cal,
                        row_anchor_dates=row_anchor_dates,
                    )
                    col_types.append(dtype)
                    norm_cols.append(norm_vals)

            out_tname = tname
            if out_tname in used_names:
                out_tname = f"{src_prefix}_{tname}"
            k = 2
            while out_tname in used_names:
                out_tname = f"{tname}_{k}"
                k += 1
            used_names.add(out_tname)

            norm_rows = [tuple(norm_cols[c][r] for c in range(len(headers))) for r in range(n_rows)]
            col_defs = ", ".join(f'"{h}" {sqlite_type_map[dt_]}' for h, dt_ in zip(headers, col_types))
            dest_conn.execute(f'DROP TABLE IF EXISTS "{out_tname}"')
            dest_conn.execute(f'CREATE TABLE "{out_tname}" ({col_defs})')
            if norm_rows:
                placeholders = ", ".join("?" for _ in headers)
                dest_conn.executemany(f'INSERT INTO "{out_tname}" VALUES ({placeholders})', norm_rows)
            dest_conn.commit()

            col_profiles = _build_column_profiles(dest_conn, out_tname, headers, headers, col_types)
            _create_table_indexes(dest_conn, out_tname, col_profiles, n_rows)
            profiles[out_tname] = TableProfile(
                table_name=out_tname,
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
        if owns_dest:
            dest_conn.close()


def _compute_workspace_fingerprint(
    bdir: pathlib.Path,
    data_files: Sequence[pathlib.Path],
    readme_text: str,
) -> str:
    """Compute a deterministic fingerprint over all non-hidden source files and README in a workspace."""
    items = []
    for fpath in sorted(data_files, key=lambda p: p.name):
        try:
            st = fpath.stat()
            items.append([normalize_nfc(fpath.name), int(st.st_size), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))])
        except OSError:
            items.append([normalize_nfc(fpath.name), -1, -1])
    payload = json.dumps({"v": 5, "readme": readme_text, "files": items}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _merge_chunks_to_group_payload(
    logical_name: str,
    chunks: Sequence[_ParsedRegionChunk],
) -> Dict[str, Any]:
    """
    Merge compatible chunks (potentially with schema drift, reordered columns,
    distinguishing pre-header metadata, and multi-sheet entity provenance) into
    a unified table payload ready for `_create_table_from_parsed`.
    """
    # Build ordered union of columns matched cleanly by normalized sql_name
    union_headers: List[str] = []
    union_sql_cols: List[str] = []
    sql_to_union_idx: Dict[str, int] = {}

    # Seed column order from widest chunk (ties broken by earliest)
    ordered_chunks = sorted(range(len(chunks)), key=lambda i: (-len(chunks[i].headers), i))
    for ch_idx in ordered_chunks:
        ch = chunks[ch_idx]
        for rh, sc in zip(ch.headers, ch.sql_cols):
            if sc not in sql_to_union_idx:
                sql_to_union_idx[sc] = len(union_headers)
                union_headers.append(rh)
                union_sql_cols.append(sc)

    union_schema_sigs = {tuple(ch.sql_cols) for ch in chunks}
    has_schema_drift = len(union_schema_sigs) > 1

    # Detect metadata keys across chunks to promote to real columns if multi-chunk varying
    promoted_meta_keys: List[Tuple[str, str]] = []  # (raw_key_label, sql_key)
    all_meta_raw_keys: Dict[str, str] = {}
    for ch in chunks:
        for mk in ch.kv_meta:
            msql = to_sql_identifier(mk, fallback="meta")
            if msql not in all_meta_raw_keys and msql not in sql_to_union_idx:
                all_meta_raw_keys[msql] = mk

    if len(chunks) >= 2:
        for msql, mk_raw in all_meta_raw_keys.items():
            vals = {ch.kv_meta.get(k) for ch in chunks for k in ch.kv_meta if to_sql_identifier(k, fallback="meta") == msql}
            vals.discard(None)
            vals.discard("")
            if len(vals) >= 2:
                promoted_meta_keys.append((mk_raw, msql))
                sql_to_union_idx[msql] = len(union_headers)
                union_headers.append(mk_raw)
                union_sql_cols.append(msql)

    distinct_sheets = {ch.sheet_name for ch in chunks if ch.sheet_name}
    inject_source_sheet = len(chunks) >= 2 and len(distinct_sheets) >= 2 and "_source_sheet" not in sql_to_union_idx
    if inject_source_sheet:
        sql_to_union_idx["_source_sheet"] = len(union_headers)
        union_headers.append("_source_sheet")
        union_sql_cols.append("_source_sheet")

    total_width = len(union_headers)
    merged_rows: List[List[Any]] = []
    merged_years: List[Optional[int]] = []
    sources: List[str] = []
    dropped_summary = 0
    ffilled = 0
    banner_notes: List[str] = []
    seen_banners: set[str] = set()
    single_meta_notes: Dict[str, str] = {}

    for ch in chunks:
        col_dest = [sql_to_union_idx[sc] for sc in ch.sql_cols]
        extra_meta_vals: Dict[int, str] = {}
        for mk_raw, msql in promoted_meta_keys:
            mval = next((v for k, v in ch.kv_meta.items() if to_sql_identifier(k, fallback="meta") == msql and v), None)
            if mval is not None:
                extra_meta_vals[sql_to_union_idx[msql]] = mval
        src_sheet_idx = sql_to_union_idx.get("_source_sheet")

        for r in ch.rows:
            out_r = [None] * total_width
            for src_i, dst_i in enumerate(col_dest):
                if src_i < len(r):
                    out_r[dst_i] = r[src_i]
            for m_idx, mval in extra_meta_vals.items():
                out_r[m_idx] = mval
            if src_sheet_idx is not None:
                out_r[src_sheet_idx] = ch.sheet_name
            merged_rows.append(out_r)

        merged_years.extend(ch.row_years)
        src_lbl = f"{ch.file_name}[{ch.sheet_name}]" if ch.sheet_name and len(distinct_sheets) > 1 else ch.file_name
        if ch.region_title:
            src_lbl = f"{ch.file_name}[{ch.sheet_name}:{ch.region_title}]"
        if src_lbl not in sources:
            sources.append(src_lbl)
        dropped_summary += ch.dropped_summary
        ffilled += ch.ffilled
        for bn in ch.banner_notes:
            if bn not in seen_banners and len(banner_notes) < 3:
                seen_banners.add(bn)
                banner_notes.append(bn)
        for mk, mv in ch.kv_meta.items():
            msql = to_sql_identifier(mk, fallback="meta")
            if msql not in {pm[1] for pm in promoted_meta_keys} and mk not in single_meta_notes:
                single_meta_notes[mk] = mv

    notes: List[str] = []
    if dropped_summary:
        notes.append(f"dropped_summary_rows={dropped_summary}")
    if ffilled:
        notes.append(f"forward_filled_rows={ffilled}")
    if has_schema_drift:
        notes.append("schema_drift_aligned")
    if promoted_meta_keys:
        notes.append("meta_cols=" + ",".join(pm[1] for pm in promoted_meta_keys))
    if single_meta_notes:
        notes.append("meta: " + "; ".join(f"{k}={v}" for k, v in list(single_meta_notes.items())[:4]))
    if banner_notes:
        notes.append("notes: " + " | ".join(banner_notes[:2]))

    return {
        "raw_name": logical_name,
        "headers": union_headers,
        "sql_cols": union_sql_cols,
        "rows": merged_rows,
        "row_years": merged_years,
        "sources": sources,
        "notes": notes,
    }


def load_business_workspace(
    business_dir: str | pathlib.Path,
    cache_dir: Optional[str | pathlib.Path] = None,
    force_rebuild: bool = False,
    lunar_cal: Optional[SolarLunarCalendar] = None,
) -> BusinessWorkspace:
    """
    Ingest ALL data files (SQLite, XLSX, CSV — including hybrid SQLite + Excel workspaces,
    multi-region sheets, merged hierarchical headers, schema drift, and multi-sheet workbooks)
    into a clean, normalized read-queryable SQLite database + schema profile.
    """
    bdir = pathlib.Path(business_dir)
    if lunar_cal is None:
        lunar_cal = _discover_lunar_calendar(bdir)
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
    manifest_path = out_dir / f"{business_id}.manifest.json"
    current_fp = _compute_workspace_fingerprint(bdir, data_files, readme_text)

    def _read_manifest() -> Optional[Dict[str, Any]]:
        if force_rebuild or not db_path.exists() or db_path.stat().st_size <= 0 or not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if data.get("fingerprint") == current_fp:
                return data
        except Exception:
            return None
        return None

    def _write_manifest(source_kind_val: str, profs: Dict[str, TableProfile]) -> None:
        try:
            table_meta = {
                tn: {
                    "raw_name": tp.raw_name,
                    "source_files": tp.source_files,
                    "notes": tp.notes,
                }
                for tn, tp in profs.items()
            }
            manifest_path.write_text(
                json.dumps(
                    {
                        "fingerprint": current_fp,
                        "business_id": business_id,
                        "source_kind": source_kind_val,
                        "table_meta": table_meta,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    cached_manifest = _read_manifest()
    if cached_manifest is not None:
        default_kind = "sqlite_normalized" if (sqlite_files and not tabular_files) else (
            "hybrid_sqlite_tabular" if (sqlite_files and tabular_files) else "tabular_files"
        )
        saved_kind = str(cached_manifest.get("source_kind") or default_kind)
        try:
            profiles = _profile_existing_sqlite(
                db_path,
                source_files=[normalize_nfc(f.name) for f in (sqlite_files + tabular_files)],
                notes=[f"{saved_kind}_cached"],
                saved_table_meta=cached_manifest.get("table_meta"),
            )
            if profiles:
                return BusinessWorkspace(
                    business_id=business_id,
                    business_dir=bdir,
                    db_path=db_path,
                    readme_text=readme_text,
                    tables=profiles,
                    source_kind=saved_kind,
                )
        except sqlite3.Error:
            pass

    # Pure SQLite workspace shortcut (preserves source_kind="sqlite_normalized")
    if sqlite_files and not tabular_files:
        if db_path.exists():
            db_path.unlink()
        dest_conn = sqlite3.connect(db_path)
        used_sqlite_names: set[str] = set()
        profiles: Dict[str, TableProfile] = {}
        try:
            for db_file in sqlite_files:
                profs = _ingest_sqlite_normalized(
                    db_file,
                    dest_conn=dest_conn,
                    used_table_names=used_sqlite_names,
                    lunar_cal=lunar_cal,
                )
                profiles.update(profs)
        finally:
            dest_conn.close()
        _write_manifest("sqlite_normalized", profiles)
        return BusinessWorkspace(
            business_id=business_id,
            business_dir=bdir,
            db_path=db_path,
            readme_text=readme_text,
            tables=profiles,
            source_kind="sqlite_normalized",
        )

    # Parse tabular files into candidate logical groups (respecting multi-region sheets & schema drift)
    candidate_groups: List[Dict[str, Any]] = []  # {"logical_name": str, "chunks": List[_ParsedRegionChunk], "union_sql_cols": List[str]}

    for fpath in tabular_files:
        fname_nfc = normalize_nfc(fpath.name)
        base_stem = _strip_split_stem(pathlib.Path(fname_nfc).stem)
        file_year = _extract_year_hint(fname_nfc)

        if fpath.suffix.lower() == ".csv":
            raw_rows = read_csv_rows(fpath)
            for reg_title, reg_rows, reg_merges in _split_horizontal_regions(raw_rows, []):
                parsed = _parse_raw_sheet(reg_rows, sheet_year=file_year, merges=reg_merges)
                if not parsed:
                    continue
                headers, body, row_years, dropped_sum, ffilled, kv_meta, banner_notes = parsed
                sql_cols, _ = _uniquify_sql_cols(headers)
                chunk = _ParsedRegionChunk(
                    file_name=fname_nfc,
                    base_stem=base_stem,
                    sheet_name="",
                    region_title=reg_title,
                    headers=headers,
                    sql_cols=sql_cols,
                    rows=body,
                    row_years=row_years,
                    kv_meta=kv_meta,
                    banner_notes=banner_notes,
                    dropped_summary=dropped_sum,
                    ffilled=ffilled,
                )
                candidate_groups.append(
                    {
                        "logical_name": reg_title or base_stem,
                        "chunks": [chunk],
                        "union_sql_cols": list(sql_cols),
                    }
                )

        elif fpath.suffix.lower() == ".xlsx":
            sheets_with_merges = read_xlsx_sheets_with_merges(fpath)
            wb_chunks: List[_ParsedRegionChunk] = []
            for sname, (raw_rows, merges) in sheets_with_merges.items():
                syear = _extract_year_hint(sname) or file_year
                for reg_title, reg_rows, reg_merges in _split_horizontal_regions(raw_rows, merges):
                    parsed = _parse_raw_sheet(reg_rows, sheet_year=syear, merges=reg_merges)
                    if parsed is None:
                        continue
                    headers, body, row_years, dropped_sum, ffilled, kv_meta, banner_notes = parsed
                    sql_cols, _ = _uniquify_sql_cols(headers)
                    wb_chunks.append(
                        _ParsedRegionChunk(
                            file_name=fname_nfc,
                            base_stem=base_stem,
                            sheet_name=sname,
                            region_title=reg_title,
                            headers=headers,
                            sql_cols=sql_cols,
                            rows=body,
                            row_years=row_years,
                            kv_meta=kv_meta,
                            banner_notes=banner_notes,
                            dropped_summary=dropped_sum,
                            ffilled=ffilled,
                        )
                    )

            if not wb_chunks:
                continue

            # Cluster chunks WITHIN this workbook by (region_title, compatible normalized columns)
            wb_clusters: List[Dict[str, Any]] = []
            for ch in wb_chunks:
                matched_cl = None
                for cl in wb_clusters:
                    if (cl["region_title"] or "") != (ch.region_title or ""):
                        continue
                    if _header_jaccard(cl["union_sql_cols"], ch.sql_cols) >= 0.75:
                        matched_cl = cl
                        break
                if matched_cl is None:
                    wb_clusters.append(
                        {
                            "region_title": ch.region_title,
                            "chunks": [ch],
                            "union_sql_cols": list(ch.sql_cols),
                        }
                    )
                else:
                    matched_cl["chunks"].append(ch)
                    for sc in ch.sql_cols:
                        if sc not in matched_cl["union_sql_cols"]:
                            matched_cl["union_sql_cols"].append(sc)

            for cl in wb_clusters:
                cl_chunks: List[_ParsedRegionChunk] = cl["chunks"]
                cl_sheets = list(dict.fromkeys(c.sheet_name for c in cl_chunks if c.sheet_name))
                reg_t = cl["region_title"]
                if reg_t:
                    logical_name = reg_t
                elif len(wb_clusters) == 1:
                    if len(cl_sheets) == 1 and cl_sheets[0].lower() not in {"sheet1", "sheet 1", "data"} and len(tabular_files) == 1 and not sqlite_files:
                        logical_name = cl_sheets[0]
                    else:
                        logical_name = base_stem
                elif len(cl_sheets) >= 2:
                    common_pref = _derive_common_sheet_prefix(cl_sheets)
                    logical_name = common_pref if common_pref else base_stem
                else:
                    logical_name = cl_sheets[0] if cl_sheets else base_stem

                candidate_groups.append(
                    {
                        "logical_name": logical_name,
                        "chunks": cl_chunks,
                        "union_sql_cols": list(cl["union_sql_cols"]),
                    }
                )

    # Cross-file schema-drift merging across candidate groups with identical logical SQL name and Jaccard >= 0.70
    merged_groups: List[Dict[str, Any]] = []
    for cand in candidate_groups:
        cand_sql_name = to_sql_identifier(cand["logical_name"], fallback="table")
        matched_mg = None
        for mg in merged_groups:
            if mg["sql_name"] != cand_sql_name:
                continue
            if _header_jaccard(mg["union_sql_cols"], cand["union_sql_cols"]) >= 0.70:
                matched_mg = mg
                break
        if matched_mg is None:
            merged_groups.append(
                {
                    "logical_name": cand["logical_name"],
                    "sql_name": cand_sql_name,
                    "chunks": list(cand["chunks"]),
                    "union_sql_cols": list(cand["union_sql_cols"]),
                }
            )
        else:
            matched_mg["chunks"].extend(cand["chunks"])
            for sc in cand["union_sql_cols"]:
                if sc not in matched_mg["union_sql_cols"]:
                    matched_mg["union_sql_cols"].append(sc)

    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    profiles = {}
    used_table_names: set[str] = set()
    try:
        # Step A: Always ingest any SQLite databases present alongside tabular files
        for db_file in sqlite_files:
            profs = _ingest_sqlite_normalized(
                db_file,
                dest_conn=conn,
                used_table_names=used_table_names,
                lunar_cal=lunar_cal,
            )
            profiles.update(profs)

        # Step B: Ingest merged tabular groups into the same unified SQLite database
        for mg in merged_groups:
            payload = _merge_chunks_to_group_payload(mg["logical_name"], mg["chunks"])
            t_base = mg["sql_name"]
            t_name = t_base
            k = 2
            while t_name in used_table_names:
                t_name = f"{t_base}_{k}"
                k += 1
            used_table_names.add(t_name)

            prof = _create_table_from_parsed(
                conn=conn,
                table_name=t_name,
                raw_table_name=payload["raw_name"],
                headers=payload["headers"],
                rows=payload["rows"],
                row_years=payload["row_years"],
                source_files=payload["sources"],
                notes=payload["notes"],
                lunar_cal=lunar_cal,
            )
            profiles[t_name] = prof
    finally:
        conn.close()

    source_kind_final = "hybrid_sqlite_tabular" if sqlite_files else "tabular_files"
    _write_manifest(source_kind_final, profiles)
    return BusinessWorkspace(
        business_id=business_id,
        business_dir=bdir,
        db_path=db_path,
        readme_text=readme_text,
        tables=profiles,
        source_kind=source_kind_final,
    )
