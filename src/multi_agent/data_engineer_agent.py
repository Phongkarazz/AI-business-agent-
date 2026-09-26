"""
Data Engineer Agent (Kỹ sư Truy vấn Dữ liệu Chuyên trách).
Chịu trách nhiệm: Hiểu Schema, chắt lọc Dynamic Few-shot, sinh câu lệnh SQL chuẩn xác,
tự động cân bằng cú pháp và thực thi an toàn trên Database Engine.
"""

from __future__ import annotations

import time
import re
from typing import Any, Dict, Optional
import pandas as pd

from .base_agent import BaseAgent
from .agent_state import AgentState
from src.database.query_runner import read_sql_capped, sanitize_error
from src.llm.client import invoke_llm
from src.llm.few_shot_selector import select_dynamic_few_shots
from src.llm.prompts import (
    build_sql_prompt,
    build_fix_prompt,
    match_chocolates_specific_product,
    match_chocolates_specific_person,
)
from src.analytics.heuristics import (
    ensure_full_twelve_months,
    ensure_full_four_quarters,
    ensure_ratio_column_if_requested,
    ensure_efficiency_columns_if_requested,
)


def strip_comments_and_literals(sql: str) -> str:
    """Loại bỏ comment SQL và chuỗi ký tự trước khi kiểm tra cú pháp."""
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'#[^\n]*', '', sql)
    sql = re.sub(r"'[^']*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    return sql


def auto_balance_parentheses(sql: str) -> str:
    """Tự động đóng dấu ngoặc thiếu."""
    if not sql:
        return sql
    cleaned = strip_comments_and_literals(sql)
    diff = cleaned.count("(") - cleaned.count(")")
    if diff <= 0:
        return sql

    lines = sql.splitlines()
    fixed_lines = []
    for line in lines:
        c_line = strip_comments_and_literals(line)
        l_diff = c_line.count("(") - c_line.count(")")
        if l_diff > 0:
            if re.search(r"\bAS\b", line, re.IGNORECASE):
                line = re.sub(r"(\s+)(AS\b)", ")" * l_diff + r"\1\2", line, count=1, flags=re.IGNORECASE)
            elif line.strip().endswith(","):
                line = line.rstrip().rstrip(",") + (")" * l_diff) + ","
            else:
                line = line + (")" * l_diff)
        fixed_lines.append(line)

    result = "\n".join(fixed_lines)
    final_diff = strip_comments_and_literals(result).count("(") - strip_comments_and_literals(result).count(")")
    if final_diff > 0:
        result = result.rstrip().rstrip(";") + (")" * final_diff)
    return result


def clean_sql_query(sql: str) -> str:
    """Làm sạch markdown backtick và tiền tố thừa."""
    if not sql:
        return ""
    sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"```\s*", "", sql)
    sql = re.sub(r"^SQLQuery:\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^SQL:\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^Query:\s*", "", sql, flags=re.IGNORECASE)
    return sql.strip()


class DataEngineerAgent(BaseAgent):
    """Data Engineer Agent chuyên sinh và thực thi SQL."""

    def __init__(self):
        super().__init__(
            name="DataEngineerAgent",
            role="Kỹ sư Dữ liệu & Chuyên gia SQL",
            description="Chuyên trách dịch câu hỏi sang SQL tối ưu, khớp schema chính xác và thực thi truy vấn."
        )

    def run(self, state: AgentState) -> AgentState:
        """Sinh hoặc sửa câu lệnh SQL dựa trên phản hồi của Auditor."""
        self.log(state, "Bắt đầu phân tích Schema và thiết kế câu lệnh SQL...")

        plan_dict = {
            "complexity": state.plan.complexity if state.plan else "DIRECT_SQL",
            "entities": state.plan.entities if state.plan else [],
            "metrics": state.plan.metrics if state.plan else [],
            "guidance": state.plan.guidance if state.plan else ""
        } if state.plan else None

        effective_schema = state.linked_sub_schema or state.schema_context

        # Trường hợp 1: Nhận yêu cầu sửa lại từ Data Auditor
        if state.audit_feedback and state.current_sql:
            self.log(state, f"Tiếp nhận phản biện từ Data Auditor (Lần {state.audit_attempts}): Tinh chỉnh SQL...", status="REFINING")
            prompt = build_fix_prompt(
                user_query=state.user_query,
                schema_context=effective_schema,
                bad_sql=state.current_sql,
                error_message=state.audit_feedback,
                plan=plan_dict,
                lang=state.lang
            )
        else:
            # Trường hợp 2: Sinh mới SQL lần đầu
            matched_person = match_chocolates_specific_person(state.user_query) if effective_schema else None
            matched_product = match_chocolates_specific_product(state.user_query) if effective_schema else None
            
            few_shots = select_dynamic_few_shots(
                user_query=state.user_query,
                schema_context=effective_schema,
                plan=plan_dict
            )
            
            prompt = build_sql_prompt(
                user_query=state.user_query,
                schema_context=effective_schema,
                plan=plan_dict,
                matched_person=matched_person,
                matched_product=matched_product,
                few_shots=few_shots,
                lang=state.lang
            )

        # Gọi LLM sinh SQL
        t0 = time.time()
        raw_sql = invoke_llm(prompt)
        cleaned_sql = clean_sql_query(raw_sql)
        balanced_sql = auto_balance_parentheses(cleaned_sql)

        state.current_sql = balanced_sql
        state.sql_history.append(balanced_sql)

        # Thực thi câu lệnh SQL trên database engine
        self.log(state, "Thực thi SQL an toàn trên Database Engine...")
        df, error = read_sql_capped(balanced_sql, state.db_engine)

        # Post-processing heuristics
        if df is not None and not df.empty:
            df = ensure_full_twelve_months(df, state.user_query)
            df = ensure_full_four_quarters(df, state.user_query)
            df = ensure_ratio_column_if_requested(df, state.user_query)
            df = ensure_efficiency_columns_if_requested(df, state.user_query)

        state.df_result = df
        state.execution_error = error
        state.execution_time_ms = round((time.time() - t0) * 1000, 2)

        if error:
            self.log(state, f"Thực thi SQL gặp lỗi cú pháp / schema: {error}", status="ERROR")
            self.communicate(state, "DataAuditorAgent", f"Thực thi SQL thất bại: {error}", message_type="ERROR")
        else:
            row_cnt = len(df) if df is not None else 0
            self.log(state, f"Thực thi thành công: Trả về {row_cnt} bản ghi trong {state.execution_time_ms}ms.", status="SUCCESS")
            self.communicate(state, "DataAuditorAgent", f"Đã sinh SQL và lấy về {row_cnt} dòng dữ liệu. Yêu cầu kiểm toán dữ liệu.", message_type="REQUEST")

        return state
