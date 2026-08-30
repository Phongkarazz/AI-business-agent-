"""
SQL Generation and Execution Agent with safety validation, parenthesis checking, and self-healing loop.
"""

import json
import re
import pandas as pd

from src.config import FORBIDDEN_KEYWORDS, MAX_ROWS_CAP
from src.database.query_runner import read_sql_capped, sanitize_error
from src.analytics.heuristics import is_id_like
from .client import call_llm
from .prompts import (
    build_sql_prompt,
    build_fix_prompt,
    build_self_check_prompt,
    build_anomaly_prompt,
)


def strip_comments_and_literals(sql: str) -> str:
    """Loại bỏ comment SQL và chuỗi ký tự trước khi kiểm tra an toàn và cú pháp."""
    # Bỏ comment dạng block /* ... */
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    # Bỏ comment dạng dòng -- ...
    sql = re.sub(r'--[^\n]*', '', sql)
    # Bỏ chuỗi ký tự '...' và "..."
    sql = re.sub(r"'[^']*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    return sql


def check_parentheses_balance(sql: str) -> tuple[bool, str]:
    """Kiểm tra số lượng dấu mở ngoặc '(' và đóng ngoặc ')' trong SQL."""
    cleaned = strip_comments_and_literals(sql)
    open_count = cleaned.count("(")
    close_count = cleaned.count(")")
    if open_count != close_count:
        return False, f"Lỗi cú pháp SQL: Thừa hoặc thiếu dấu ngoặc đơn () (Có {open_count} dấu '(' nhưng có {close_count} dấu ')')."
    return True, ""


def is_safe_select(sql: str) -> bool:
    """Kiểm tra câu lệnh SQL có phải là SELECT/WITH hợp lệ và an toàn không."""
    if not sql:
        return False

    cleaned = strip_comments_and_literals(sql.strip())
    raw_cleaned = cleaned.strip().rstrip(";")
    lowered = raw_cleaned.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False

    if ";" in raw_cleaned:  # Chặn stacked queries
        return False

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", lowered):
            return False
    return True


def detect_duplicate_entity_warning(df: pd.DataFrame) -> str | None:
    """Kiểm tra xem có dấu hiệu nhân bản dữ liệu do JOIN bảng lịch sử không."""
    if df is None or df.empty:
        return None

    id_cols = [c for c in df.columns if is_id_like(c)]
    for c in id_cols:
        try:
            n_unique = df[c].nunique(dropna=True)
        except Exception:
            continue
        if 0 < n_unique < len(df):
            return (
                f"⚠️ Cảnh báo tự động: cột `{c}` chỉ có {n_unique} giá trị duy nhất nhưng kết quả trả về "
                f"{len(df)} dòng. Đây thường là dấu hiệu dữ liệu bị nhân bản do JOIN với bảng lưu lịch sử "
                f"theo thời gian (VD: salaries, titles, dept_emp) mà chưa lọc bản ghi hiện tại. "
                f"Hãy diễn đạt lại câu hỏi rõ hơn (VD: 'lương hiện tại') hoặc kiểm tra SQL bên dưới."
            )
    return None


def self_check_sql(client, provider: str, model_name: str, schema_context: str, user_query: str, sql_query: str, df: pd.DataFrame) -> dict:
    """Thực hiện bước AI QA self-check để kiểm định kết quả SQL."""
    sample = df.head(5).to_string(index=False)
    prompt = build_self_check_prompt(schema_context, user_query, sql_query, sample)
    res, err = call_llm(client, provider, model_name, prompt)

    if not res:
        return {"day_du": True, "ly_do": "Bỏ qua self-check."}

    try:
        cleaned = res.strip().strip("`").replace("json\n", "").strip()
        parsed = json.loads(cleaned)
        ly_do = str(parsed.get("ly_do", ""))
        if len(ly_do) > 200:
            ly_do = ly_do[:200].rsplit(" ", 1)[0] + "..."
        parsed["ly_do"] = ly_do
        return parsed
    except Exception:
        return {"day_du": True, "ly_do": "Không parse được JSON self-check."}


def explain_anomalies_agent(client, provider: str, model_name: str, user_query: str, x_col: str, y_col: str, outliers_df: pd.DataFrame) -> str | None:
    """Gọi LLM giải thích nguyên nhân kinh doanh của các điểm bất thường."""
    points = outliers_df[[x_col, y_col]].to_dict(orient="records")
    prompt = build_anomaly_prompt(user_query, x_col, y_col, points)
    res, _ = call_llm(client, provider, model_name, prompt)
    return res


def run_agent(
    user_query: str,
    client,
    provider: str,
    model_name: str,
    engine,
    schema_context: str,
    dialect: str = "SQLite",
    db_pass: str = "",
    enable_self_check: bool = True
) -> dict:
    """Điều phối toàn bộ chu trình Text-to-SQL với kiểm tra cú pháp và cơ chế tự sửa lỗi tối đa 3 lần."""
    result = {"query": user_query, "df": None, "sql": None, "logs": [], "error": None}

    # 1. Sinh SQL ban đầu
    initial_prompt = build_sql_prompt(schema_context, dialect, user_query)
    sql_query, err = call_llm(client, provider, model_name, initial_prompt)

    if not sql_query:
        result["error"] = f"Không thể tạo SQL từ mô hình AI.{' Lý do: ' + err if err else ''}"
        return result

    # 2. Vòng lặp thực thi, kiểm định và tự sửa lỗi
    for attempt in range(1, 4):
        result["logs"].append(f"[Lần {attempt}] SQL: {sql_query}")

        if not is_safe_select(sql_query):
            result["error"] = "Câu lệnh SQL không an toàn (Chỉ chấp nhận lệnh SELECT/WITH đơn, không nhiều câu lệnh)."
            result["sql"] = sql_query
            return result

        # 2.1 Kiểm tra cân đối dấu ngoặc trước khi thực thi
        is_balanced, paren_err = check_parentheses_balance(sql_query)
        if not is_balanced:
            result["logs"].append(f"❌ Phát hiện lỗi cú pháp dấu ngoặc: {paren_err}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {paren_err}"
                result["sql"] = sql_query
                return result

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, paren_err
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = fixed_sql or sql_query
            continue

        # 2.2 Thực thi SQL trên Database Engine
        try:
            df, truncated = read_sql_capped(sql_query, engine, cap=MAX_ROWS_CAP)
            if truncated:
                result["logs"].append(f"⚠️ Dữ liệu lớn: đã dừng đọc ở {MAX_ROWS_CAP:,} dòng để bảo vệ hệ thống.")

            dup_warning = detect_duplicate_entity_warning(df)
            if dup_warning:
                result["logs"].append(dup_warning)

            if enable_self_check:
                check = self_check_sql(client, provider, model_name, schema_context, user_query, sql_query, df)
            else:
                check = {"day_du": True, "ly_do": "Đã tắt self-check để tiết kiệm quota."}

            if check.get("day_du", True):
                result["logs"].append(f"✅ Kiểm định SQL OK: {check.get('ly_do', '')}")
                result["df"] = df
                result["sql"] = sql_query
                return result

            result["logs"].append(f"⚠️ Phát hiện vấn đề: {check.get('ly_do', '')}")
            if attempt == 3:
                result["df"] = df
                result["sql"] = sql_query
                return result

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, check.get("ly_do", "")
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = fixed_sql or sql_query

        except Exception as e:
            error_msg = sanitize_error(str(e), db_pass)
            result["logs"].append(f"❌ Lỗi thực thi SQL: {error_msg}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {error_msg}"
                result["sql"] = sql_query
                return result

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, error_msg
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = fixed_sql or sql_query

    return result
