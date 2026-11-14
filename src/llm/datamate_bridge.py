"""Bridge connecting DataMate's verified SQL engine into Veraxus interactive analytics."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from datamate.agent import (
    AgentConfig,
    DataMateAgent,
    QuestionAnalysis,
    check_preflight_unanswerable,
    classify_expected_type,
    extract_temporal_context,
    format_sql_result,
    normalize_vn_question,
    verify_sql_semantics,
)
from datamate.llm_backend import LLMBackend, extract_json_object
from datamate.schema_context import WorkspaceKnowledge, ground_query_entities
from datamate.sql_executor import SQLExecutionResult, execute_sql_safe, norm_vn
from src.analytics.anomaly import analyze_data_anomalies
from src.analytics.heuristics import split_insight_sections
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


def build_datamate_suggested_questions(
    knowledge: WorkspaceKnowledge,
    lang: str = "vi",
) -> List[str]:
    """Generate grounded follow-up/starter questions strictly matching existing tables & columns."""
    caps = knowledge.capabilities
    targets = knowledge.order_status_targets or []
    date_ref = knowledge.data_max_date or ""
    ym = date_ref[:7] if len(date_ref) >= 7 else ""
    is_en = lang == "en"

    suggestions: List[str] = []
    if targets:
        if ym:
            suggestions.append(
                f"What was the total valid revenue and order count in {ym}?"
                if is_en
                else f"Tổng doanh thu và số đơn hợp lệ trong tháng {ym[5:7]}/{ym[:4]} là bao nhiêu?"
            )
            suggestions.append(
                f"Which day had the highest revenue in {ym}?"
                if is_en
                else f"Ngày nào có doanh thu cao nhất trong tháng {ym[5:7]}/{ym[:4]}?"
            )
        else:
            suggestions.append("Hôm nay cửa hàng bán được bao nhiêu tiền và mấy đơn?")
        if caps.get("has_customers"):
            suggestions.append(
                "Top 5 customers by valid spending"
                if is_en
                else "Top 5 khách hàng mua nhiều tiền nhất"
            )
        if caps.get("has_debt_or_payments"):
            suggestions.append(
                "Total outstanding customer debt to date"
                if is_en
                else "Tổng công nợ còn phải thu tính đến hết ngày dữ liệu"
            )

    if not suggestions:
        t0 = next(iter(knowledge.valid_tables), "data")
        suggestions.append(
            f"Show summary metrics of table `{t0}`"
            if is_en
            else f"Thống kê tổng quan các chỉ số chính của bảng {t0}"
        )
    return suggestions[:4]


def _format_answer_banner(
    formatted: Optional[Dict[str, Any]],
    analysis: QuestionAnalysis,
    lang: str,
) -> Optional[str]:
    if not formatted or "answer" not in formatted:
        return None
    ptype = formatted.get("type")
    ans = formatted.get("answer")
    is_en = lang == "en"

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
        result["followups"] = build_datamate_suggested_questions(knowledge, lang=lang)
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

        obj = extract_json_object(raw_reply)
        if obj and obj.get("status") == "unanswerable":
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
            result["followups"] = build_datamate_suggested_questions(knowledge, lang=lang)
            return result

        candidate_sql = str(obj["sql"]) if (obj and isinstance(obj.get("sql"), str)) else raw_reply
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

        if not res.ok:
            result["logs"].append(f"⚠️ Lỗi thực thi SQLite: {res.error}")
            if attempt + 1 < max_retries:
                prompt_to_send = dm_agent._build_repair_prompt(
                    user_query,
                    last_sql_text,
                    res.error,
                    knowledge,
                    temporal_summary=temp_summary,
                    include_full_schema=True,
                )
                continue
            result["sql"] = last_sql_text
            result["explanation"] = _governance_notice(
                "Không thể tạo truy vấn SQL hợp lệ sau nhiều lần kiểm tra",
                "Could not build a valid SQL query",
                f"Đã dừng an toàn để tránh trả về số liệu sai ({res.error}).",
                lang,
            )
            result["followups"] = build_datamate_suggested_questions(knowledge, lang=lang)
            return result

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
                result["sql"] = last_sql_text
                result["explanation"] = _governance_notice(
                    "Đã chặn kết quả nghi sai logic nghiệp vụ",
                    "Blocked potentially flawed business logic",
                    f"{sem_msg}. Veraxus từ chối hiển thị số liệu chưa đạt kiểm định để bảo vệ độ chính xác.",
                    lang,
                )
                result["followups"] = build_datamate_suggested_questions(knowledge, lang=lang)
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
            result["sql"] = last_sql_text
            result["explanation"] = _governance_notice(
                "Không tìm thấy dữ liệu khớp trong kỳ hoặc điều kiện hỏi",
                "No matching records found",
                "Truy vấn trả về rỗng/NULL sau khi kiểm định. Vui lòng kiểm tra lại tên mặt hàng/khách hàng hoặc mốc thời gian của shop.",
                lang,
            )
            result["followups"] = build_datamate_suggested_questions(knowledge, lang=lang)
            return result

        # Valid rows returned & passed semantic guard! Build rich DataFrame + UI metadata.
        df = pd.DataFrame(res.rows, columns=res.columns)
        formatted = format_sql_result(res, analysis, user_query)
        banner = _format_answer_banner(formatted, analysis, lang)

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
        result["followups"] = build_datamate_suggested_questions(knowledge, lang=lang)

        if not df.empty and len(df) >= 2:
            result["anomalies_info"] = analyze_data_anomalies(df)

        if enable_auto_insights and not df.empty:
            if status_callback:
                status_callback("💡 [Strategy Advisor] Tổng hợp nhận định & đề xuất từ số liệu thực tế...")
            if provider == "Ollama (Local AI Offline)" or insights_fn is None or len(df) == 1:
                sec = split_insight_sections("", df=df, user_query=user_query, is_en=(lang == "en"))
                result["insights"] = (
                    f"### 2.1. 🚨 Phát hiện Bất thường & Xu hướng Chính\n{sec['anomaly']}\n\n"
                    f"### 2.2. 🔍 Giả thuyết & Nguyên nhân Tiềm năng\n{sec['hypothesis']}\n\n"
                    f"### 2.3. 🎯 Kế hoạch Hành động & Đề xuất Ưu tiên\n{sec['action_plan']}"
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
