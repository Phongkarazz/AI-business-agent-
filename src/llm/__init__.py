"""
LLM package for multi-provider AI communication and SQL generation agent.
"""

from .client import get_llm_client, call_llm
from .agent import run_agent, is_safe_select, detect_duplicate_entity_warning
from .prompts import build_sql_prompt, build_self_check_prompt, build_anomaly_prompt

__all__ = [
    "get_llm_client",
    "call_llm",
    "run_agent",
    "is_safe_select",
    "detect_duplicate_entity_warning",
    "build_sql_prompt",
    "build_self_check_prompt",
    "build_anomaly_prompt",
]
