"""Safe, AST-verified read-only Python/Pandas sandbox for stateful & semi-structured SME analytics."""

from __future__ import annotations

import ast
import collections
import datetime as dt
import decimal
import itertools
import math
import re
import sqlite3
import statistics
import threading
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from datamate.llm_backend import extract_json_object, strip_thinking
from datamate.loader import _parse_vn_number
from datamate.sql_executor import (
    SQLExecutionResult,
    adapt_sql_to_sqlite,
    heal_datetime_comparisons,
    heal_table_names,
    norm_vn,
    register_sqlite_udfs,
    round_half_up,
    validate_readonly_sql,
)

_ALLOWED_IMPORTS = frozenset({
    "math",
    "re",
    "datetime",
    "decimal",
    "collections",
    "itertools",
    "statistics",
    "pandas",
    "numpy",
})

_FORBIDDEN_NAMES = frozenset({
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "input",
    "breakpoint",
    "exit",
    "quit",
})

_PYTHON_FENCE_RE = re.compile(r"```(?:python|py)\s*([\s\S]*?)\s*```", re.IGNORECASE)
_NUM_UNIT_TOKEN_RE = re.compile(
    r"([+-]?\d+(?:[.,\s]\d+)*(?:\s*(?:tr\s*\d*|k|c[uủ]|x[iị]|l[ií]t|c[aà]nh|tri[eệ]u|ngh[iì]n|ng[aà]n|[dđ₫]))?(?:\s*[x×*]\s*\d+(?:[.,]\d+)?)?)",
    re.IGNORECASE,
)


def extract_python_from_response(raw: str) -> str:
    """Extract sandbox Python code from JSON `{\"python\": ...}` or ```python fenced block."""
    if not raw:
        return ""
    text = strip_thinking(raw)
    obj = extract_json_object(text)
    if obj and isinstance(obj.get("python"), str):
        code = obj["python"].strip()
        m_inner = _PYTHON_FENCE_RE.search(code)
        return m_inner.group(1).strip() if m_inner else code

    m = _PYTHON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return ""


def validate_sandbox_python(code: str) -> Optional[str]:
    """Statically verify AST safety before executing LLM-generated Python."""
    if not code or not code.strip():
        return "Empty Python script."
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Python syntax error: {exc.msg} (line {exc.lineno})"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top not in _ALLOWED_IMPORTS:
                    return f"Import not allowed in sandbox: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not node.module:
                return "Relative imports are not allowed in sandbox."
            top = node.module.split(".", 1)[0]
            if top not in _ALLOWED_IMPORTS:
                return f"Import not allowed in sandbox: {node.module}"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                return f"Private/dunder attribute access blocked: {node.attr}"
        elif isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES:
                return f"Builtin/symbol blocked in sandbox: {node.id}"
    return None


def parse_vn_num(val: Any) -> float:
    """Parse messy Vietnamese numeric/currency/expression strings into float (0.0 on failure)."""
    if val is None or isinstance(val, bool):
        return 0.0
    if isinstance(val, (int, float, np.integer, np.floating)):
        f = float(val)
        return f if math.isfinite(f) else 0.0
    s = str(val).strip()
    if not s:
        return 0.0
    parsed = _parse_vn_number(s, dot_is_thousands=True, allow_slang_money=True)
    if parsed is not None:
        return float(parsed)
    m = _NUM_UNIT_TOKEN_RE.search(s)
    if m:
        parsed2 = _parse_vn_number(m.group(1), dot_is_thousands=True, allow_slang_money=True)
        if parsed2 is not None:
            return float(parsed2)
    return 0.0


def sum_compound_vn_nums(val: Any) -> float:
    """Parse and sum compound cells like '527k + 338000' or '120.000; 80k'."""
    if val is None or isinstance(val, bool):
        return 0.0
    if isinstance(val, (int, float, np.integer, np.floating)):
        f = float(val)
        return f if math.isfinite(f) else 0.0
    s = str(val).strip()
    if not s:
        return 0.0
    parts = [p.strip() for p in re.split(r"[+;\n|]+", s) if p.strip()]
    if len(parts) <= 1:
        return parse_vn_num(s)
    return float(sum(parse_vn_num(p) for p in parts))


class _ReadOnlyCursorProxy:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cur = cursor

    @property
    def description(self):
        return self._cur.description

    def execute(self, sql: str, parameters: Any = ()):
        err = validate_readonly_sql(sql)
        if err:
            raise ValueError(f"Sandbox SQL blocked: {err}")
        return self._cur.execute(sql, parameters)

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size: Optional[int] = None):
        return self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()

    def fetchone(self):
        return self._cur.fetchone()

    def close(self):
        self._cur.close()


class _ReadOnlyConnProxy:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, parameters: Any = ()):
        err = validate_readonly_sql(sql)
        if err:
            raise ValueError(f"Sandbox SQL blocked: {err}")
        return self._conn.execute(sql, parameters)

    def cursor(self) -> _ReadOnlyCursorProxy:
        return _ReadOnlyCursorProxy(self._conn.cursor())


def _restricted_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
    if level != 0 or name.split(".", 1)[0] not in _ALLOWED_IMPORTS:
        raise ImportError(f"Module {name!r} is not allowed in Veraxus Python sandbox.")
    return __import__(name, globals, locals, fromlist, level)


def _to_python_scalar(v: Any) -> Any:
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _normalize_sandbox_result(val: Any, max_rows: int) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    if isinstance(val, dict) and "columns" in val and "rows" in val:
        cols = [str(c) for c in val["columns"]]
        rows = [
            tuple(_to_python_scalar(cell) for cell in r)
            for r in list(val["rows"])[:max_rows]
        ]
        return cols, rows

    if isinstance(val, dict) and "answer" in val:
        val = val["answer"]

    if isinstance(val, pd.DataFrame):
        cols = [str(c) for c in val.columns]
        rows = [
            tuple(_to_python_scalar(c) for c in r)
            for r in val.head(max_rows).itertuples(index=False, name=None)
        ]
        return cols, rows

    if isinstance(val, pd.Series):
        cols = [str(val.name or "result")]
        rows = [(_to_python_scalar(x),) for x in val.head(max_rows).tolist()]
        return cols, rows

    if isinstance(val, (list, tuple, np.ndarray)):
        seq = list(val)[:max_rows]
        if not seq:
            return ["result"], []
        first = seq[0]
        if isinstance(first, (list, tuple)) and len(first) >= 2 and all(
            isinstance(item, (list, tuple)) and len(item) == len(first) for item in seq
        ):
            cols = [f"col_{i + 1}" for i in range(len(first))]
            rows = [tuple(_to_python_scalar(c) for c in item) for item in seq]
            return cols, rows
        if isinstance(first, dict) and first:
            cols = [str(k) for k in first.keys()]
            rows = [tuple(_to_python_scalar(item.get(k)) for k in first.keys()) for item in seq]
            return cols, rows
        return ["val"], [(_to_python_scalar(x),) for x in seq]

    return ["result"], [(_to_python_scalar(val),)]


def execute_python_safe(
    conn_factory,
    raw_code: str,
    as_of_date: str = "",
    valid_tables: Sequence[str] = (),
    datetime_columns: Sequence[str] = (),
    max_rows: int = 500,
    timeout_seconds: float = 8.0,
) -> SQLExecutionResult:
    """Validate and execute read-only Python analytics code with hard timeout & AST isolation."""
    code = extract_python_from_response(raw_code) or (raw_code or "").strip()
    tag_sql = f"-- [PYTHON_SANDBOX]\n{code}"

    err = validate_sandbox_python(code)
    if err:
        return SQLExecutionResult(ok=False, sql=tag_sql, columns=[], rows=[], error=err)

    try:
        compiled = compile(code, "<veraxus_python_sandbox>", "exec")
    except SyntaxError as exc:
        return SQLExecutionResult(ok=False, sql=tag_sql, columns=[], rows=[], error=f"Syntax error: {exc}")

    cancel_ev = threading.Event()
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    outcome: Dict[str, Any] = {}

    def _runner() -> None:
        raw_conn = conn_factory()
        try:
            raw_conn.execute("PRAGMA query_only = ON")
            register_sqlite_udfs(raw_conn)
            raw_conn.set_progress_handler(
                lambda: 1 if (cancel_ev.is_set() or time.monotonic() > deadline) else 0,
                25000,
            )
            proxy_conn = _ReadOnlyConnProxy(raw_conn)

            def _query_df(sql_str: str) -> pd.DataFrame:
                s = adapt_sql_to_sqlite(sql_str)
                if valid_tables:
                    s = heal_table_names(s, valid_tables)
                if datetime_columns:
                    s = heal_datetime_comparisons(s, datetime_columns)
                q_err = validate_readonly_sql(s)
                if q_err:
                    raise ValueError(f"query_df blocked: {q_err}")
                return pd.read_sql_query(s, proxy_conn)

            safe_builtins = {
                "abs": abs,
                "all": all,
                "any": any,
                "bool": bool,
                "dict": dict,
                "enumerate": enumerate,
                "filter": filter,
                "float": float,
                "int": int,
                "isinstance": isinstance,
                "len": len,
                "list": list,
                "map": map,
                "max": max,
                "min": min,
                "next": next,
                "print": print,
                "range": range,
                "reversed": reversed,
                "round": round,
                "set": set,
                "sorted": sorted,
                "str": str,
                "sum": sum,
                "tuple": tuple,
                "zip": zip,
                "ValueError": ValueError,
                "TypeError": TypeError,
                "ZeroDivisionError": ZeroDivisionError,
                "KeyError": KeyError,
                "IndexError": IndexError,
                "Exception": Exception,
                "__import__": _restricted_import,
            }
            ns: Dict[str, Any] = {
                "__builtins__": safe_builtins,
                "conn": proxy_conn,
                "query_df": _query_df,
                "pd": pd,
                "np": np,
                "re": re,
                "math": math,
                "datetime": dt,
                "decimal": decimal,
                "collections": collections,
                "itertools": itertools,
                "statistics": statistics,
                "Decimal": Decimal,
                "ROUND_HALF_UP": ROUND_HALF_UP,
                "as_of_date": as_of_date,
                "norm_vn": norm_vn,
                "round_half_up": round_half_up,
                "parse_vn_num": parse_vn_num,
                "sum_compound_vn_nums": sum_compound_vn_nums,
            }
            exec(compiled, ns, ns)
            if "result" in ns:
                outcome["value"] = ns["result"]
            elif "answer" in ns:
                outcome["value"] = ns["answer"]
            elif "ans" in ns:
                outcome["value"] = ns["ans"]
            else:
                outcome["error"] = "Python script must assign output to `result` (e.g. `result = ...`)."
        except Exception as exc:
            outcome["error"] = f"Python sandbox runtime error: {exc}"
        finally:
            try:
                raw_conn.set_progress_handler(None, 0)
            except Exception:
                pass
            raw_conn.close()

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join(timeout=max(0.5, float(timeout_seconds)))
    if worker.is_alive():
        cancel_ev.set()
        worker.join(timeout=0.3)
        return SQLExecutionResult(
            ok=False,
            sql=tag_sql,
            columns=[],
            rows=[],
            error=f"Python sandbox timed out after {timeout_seconds:.1f}s.",
        )

    if "error" in outcome:
        return SQLExecutionResult(ok=False, sql=tag_sql, columns=[], rows=[], error=str(outcome["error"]))

    cols, rows = _normalize_sandbox_result(outcome.get("value"), max_rows=max_rows)
    return SQLExecutionResult(
        ok=True,
        sql=tag_sql,
        columns=cols,
        rows=rows,
        row_count=len(rows),
        truncated=False,
    )
