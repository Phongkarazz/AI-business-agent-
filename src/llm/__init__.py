"""
LLM package for multi-provider AI communication, SQL generation agent, and automated business insights.
"""

from .client import get_llm_client, call_llm, normalize_model_for_openrouter
from .router_planner import route_and_plan, classify_query_complexity, decompose_subtasks
from .evaluator import evaluate_execution
from .agent import (
    run_agent,
    is_safe_select,
    detect_duplicate_entity_warning,
    generate_auto_insights,
    explain_anomalies_agent,
)
from .prompts import (
    build_sql_prompt,
    build_self_check_prompt,
    build_anomaly_prompt,
    build_auto_insight_prompt,
)

__all__ = [
    "get_llm_client",
    "call_llm",
    "normalize_model_for_openrouter",
    "route_and_plan",
    "classify_query_complexity",
    "decompose_subtasks",
    "evaluate_execution",
    "run_agent",
    "is_safe_select",
    "detect_duplicate_entity_warning",
    "generate_auto_insights",
    "explain_anomalies_agent",
    "build_sql_prompt",
    "build_self_check_prompt",
    "build_anomaly_prompt",
    "build_auto_insight_prompt",
]
