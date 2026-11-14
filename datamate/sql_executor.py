"""Safe, read-only SQLite SQL extractor, universal rewriter, and executor."""

from __future__ import annotations

import decimal
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from src.config import FORBIDDEN_KEYWORDS
    from src.llm.sql_sanitizer import fuzzy_match_name, sanitize_common_sql_syntax
except ImportError:
    FORBIDDEN_KEYWORDS = [
        "insert", "update", "delete", "drop", "alter",
        "truncate", "create", "grant", "revoke", "exec", "execute",
    ]
    fuzzy_match_name = None
    sanitize_common_sql_syntax = None

from datamate.llm_backend import strip_thinking
from datamate.temporal import normalize_nfc

_SQL_FENCE_RE = re.compile(r"```(?:sql|sqlite)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_FIRST_SQL_KW_RE = re.compile(r"\b(WITH\s+[a-zA-Z_\"`][a-zA-Z0-9_\"`]*\s*(?:\([^)]*\)\s*)?AS\s*\(|SELECT\b)", re.IGNORECASE)
_FORBIDDEN_SQL_RE = re.compile(
    r"(?:^|[\s;(])(?:" + "|".join(re.escape(k) for k in FORBIDDEN_KEYWORDS) + r"|attach|detach|pragma\s+(?!query_only))\b",
    re.IGNORECASE,
)


def norm_vn(value: Any) -> str:
    """Accent-stripped lowercase single-space Vietnamese string for robust SQLite matching."""
    if value is None:
        return ""
    s = normalize_nfc(str(value)).replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def round_half_up(value: Any, digits: int = 0) -> Optional[int | float]:
    """Decimal ROUND_HALF_UP aligned with DataMate Rulebook §3 & §9."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = decimal.Decimal(str(float(value)))
    except (ValueError, decimal.InvalidOperation):
        return None
    if not d.is_finite():
        return None
    q = decimal.Decimal("1") if int(digits) <= 0 else decimal.Decimal("1e-" + str(int(digits)))
    # Positive numbers round 0.5 upward; symmetric for negatives
    if d >= 0:
        out = d.quantize(q, rounding=decimal.ROUND_HALF_UP)
    else:
        out = -((-d).quantize(q, rounding=decimal.ROUND_HALF_UP))
    return int(out) if int(digits) <= 0 else float(out)


@dataclass
class SQLExecutionResult:
    ok: bool
    sql: str
    columns: List[str]
    rows: List[Tuple[Any, ...]]
    row_count: int = 0
    truncated: bool = False
    error: str = ""


def extract_sql_from_response(raw: str) -> str:
    """Extract a clean single SQLite SELECT/WITH query from an LLM response."""
    if not raw:
        return ""
    text = strip_thinking(raw)
    m = _SQL_FENCE_RE.search(text)
    if m:
        candidate = m.group(1).strip()
    else:
        candidate = text.strip()

    if sanitize_common_sql_syntax is not None:
        candidate = sanitize_common_sql_syntax(candidate)

    m_kw = _FIRST_SQL_KW_RE.search(candidate)
    if m_kw and m_kw.start() > 0:
        candidate = candidate[m_kw.start() :].strip()

    # Keep only first SQL statement cleanly
    stmts = _split_top_level_semicolons(candidate)
    if stmts:
        candidate = stmts[0].strip()

    # Balance trailing parentheses if unbalanced by 1-2 closes from LLM truncation
    open_p = candidate.count("(")
    close_p = candidate.count(")")
    if open_p > close_p and (open_p - close_p) <= 3:
        candidate = candidate + (")" * (open_p - close_p))
    return candidate.strip()


def _split_top_level_semicolons(sql: str) -> List[str]:
    parts: List[str] = []
    cur: List[str] = []
    in_sq = False
    in_dq = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_dq:
            if in_sq and i + 1 < len(sql) and sql[i + 1] == "'":
                cur.append("''")
                i += 2
                continue
            in_sq = not in_sq
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
        elif ch == ";" and not in_sq and not in_dq:
            seg = "".join(cur).strip()
            if seg:
                parts.append(seg)
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def validate_readonly_sql(sql: str) -> Optional[str]:
    """Return error string if SQL is missing or violates read-only safety."""
    if not sql or not sql.strip():
        return "Empty SQL query."
    # Strip string literals before checking keywords
    stripped = re.sub(r"'(?:''|[^'])*'", "''", sql)
    stripped_no_comments = re.sub(r"--[^\n]*", " ", stripped)
    stripped_no_comments = re.sub(r"/\*[\s\S]*?\*/", " ", stripped_no_comments).strip()
    if not re.match(r"^(?:WITH|SELECT)\b", stripped_no_comments, re.IGNORECASE):
        return "Query must start with SELECT or WITH."
    if _FORBIDDEN_SQL_RE.search(stripped_no_comments):
        return "Query contains forbidden non-read-only keyword."
    return None


def adapt_sql_to_sqlite(sql: str) -> str:
    """Rewrite common MySQL/Postgres idioms emitted by smaller LLMs into valid SQLite."""
    s = sql
    s = re.sub(r"\bILIKE\b", "LIKE", s, flags=re.IGNORECASE)
    s = re.sub(r"\bNVL\s*\(", "COALESCE(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSTRING_AGG\s*\(", "GROUP_CONCAT(", s, flags=re.IGNORECASE)
    s = re.sub(r"\bYEAR\s*\(\s*([^)]+?)\s*\)", r"CAST(strftime('%Y', \1) AS INTEGER)", s, flags=re.IGNORECASE)
    s = re.sub(r"\bMONTH\s*\(\s*([^)]+?)\s*\)", r"CAST(strftime('%m', \1) AS INTEGER)", s, flags=re.IGNORECASE)
    s = re.sub(r"\bDAY\s*\(\s*([^)]+?)\s*\)", r"CAST(strftime('%d', \1) AS INTEGER)", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\bDATE_FORMAT\s*\(\s*([^,]+?)\s*,\s*'([^']+)'\s*\)",
        r"strftime('\2', \1)",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\bDATEDIFF\s*\(\s*([^,()]+(?:\([^)]*\))?)\s*,\s*([^,()]+(?:\([^)]*\))?)\s*\)",
        r"CAST(julianday(\1) - julianday(\2) AS REAL)",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\bTRUE\b", "1", s, flags=re.IGNORECASE)
    s = re.sub(r"\bFALSE\b", "0", s, flags=re.IGNORECASE)
    return s


def register_sqlite_udfs(conn: sqlite3.Connection) -> None:
    """Register domain-agnostic Vietnamese normalization & rounding UDFs on SQLite connection."""
    conn.create_function("NORM_VN", 1, norm_vn, deterministic=True)
    conn.create_function("UNACCENT", 1, norm_vn, deterministic=True)
    conn.create_function("ROUND_HALF_UP", 1, lambda x: round_half_up(x, 0), deterministic=True)
    conn.create_function("ROUND_HALF_UP", 2, round_half_up, deterministic=True)


def heal_table_names(sql: str, valid_tables: Sequence[str]) -> str:
    """Heal minor table-name typos (case, pluralization) against actual SQLite schema."""
    if not sql or not valid_tables:
        return sql
    lower_map = {t.lower(): t for t in valid_tables}
    cte_names = {
        m.group(1).lower()
        for m in re.finditer(r"(?:WITH|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(", sql, re.IGNORECASE)
    }

    def _repl(match: re.Match[str]) -> str:
        kw, q1, name, q2 = match.group(1), match.group(2) or "", match.group(3), match.group(4) or ""
        nl = name.lower()
        if nl in lower_map or nl in cte_names:
            canonical = lower_map.get(nl, name)
            return f"{kw} {q1}{canonical}{q2}"
        if fuzzy_match_name is not None:
            fixed = fuzzy_match_name(name, list(valid_tables), cutoff=0.78)
            if fixed:
                return f"{kw} {q1}{fixed}{q2}"
        return match.group(0)

    return re.sub(r"\b(FROM|JOIN)\s+([`\"]?)([a-zA-Z_][a-zA-Z0-9_]*)([`\"]?)", _repl, sql, flags=re.IGNORECASE)


def execute_sql_safe(
    conn_factory,
    raw_sql: str,
    valid_tables: Sequence[str] = (),
    max_rows: int = 1000,
    timeout_seconds: float = 8.0,
) -> SQLExecutionResult:
    """Sanitize, adapt, and execute read-only SQLite query with hard deadline protection."""
    sql = extract_sql_from_response(raw_sql)
    sql = adapt_sql_to_sqlite(sql)
    if valid_tables:
        sql = heal_table_names(sql, valid_tables)

    err = validate_readonly_sql(sql)
    if err:
        return SQLExecutionResult(ok=False, sql=sql, columns=[], rows=[], error=err)

    conn = conn_factory()
    start = time.monotonic()

    def _progress_cb() -> int:
        if time.monotonic() - start > timeout_seconds:
            return 1
        return 0

    try:
        conn.execute("PRAGMA query_only = ON")
        register_sqlite_udfs(conn)
        conn.set_progress_handler(_progress_cb, 50000)
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [tuple(r) for r in fetched[:max_rows]]
        return SQLExecutionResult(
            ok=True,
            sql=sql,
            columns=cols,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )
    except sqlite3.OperationalError as exc:
        msg = str(exc)
        if "interrupted" in msg.lower():
            msg = f"Query timed out after {timeout_seconds:.1f}s."
        return SQLExecutionResult(ok=False, sql=sql, columns=[], rows=[], error=msg)
    except sqlite3.Error as exc:
        return SQLExecutionResult(ok=False, sql=sql, columns=[], rows=[], error=str(exc))
    finally:
        try:
            conn.set_progress_handler(None, 0)
        except Exception:
            pass
        conn.close()
