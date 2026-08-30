"""
Configuration and Constants for AI Business Agent.
"""

import os
import re
import sys

# ---------------------------------------------------------
# UTF-8 Environment Configuration
# ---------------------------------------------------------
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ---------------------------------------------------------
# SQL Security Keywords
# ---------------------------------------------------------
FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete", "drop", "alter",
    "truncate", "create", "grant", "revoke", "exec", "execute"
]

# ---------------------------------------------------------
# Column Classification Keywords and Regex
# ---------------------------------------------------------
TIME_KEYWORDS = ["date", "month", "thang", "quy", "quarter", "nam", "year"]
BOUNDED_PERIOD_KEYWORDS = ["month", "thang", "quy", "quarter"]

# ID-like column pattern (excluded from statistical Y-axes and forecasting)
ID_LIKE_REGEX = re.compile(r'(^|_)(id|no|code|key|num|sn)$', re.IGNORECASE)

# Business name-like column pattern (prioritized for X-axis labels)
NAME_LIKE_REGEX = re.compile(r'(name|ten|title|category|product|team|region|department|dept)', re.IGNORECASE)

# ---------------------------------------------------------
# AI Providers Configuration
# ---------------------------------------------------------
PROVIDER_CONFIGS = {
    "OpenRouter": {
        "models": [
            "deepseek/deepseek-chat",
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.0-flash-001",
            "meta-llama/llama-3.3-70b-instruct",
            "qwen/qwen-2.5-coder-32b-instruct",
            "deepseek/deepseek-r1",
        ],
        "key_help": "Lấy API key tại openrouter.ai/keys.",
        "key_placeholder": "sk-or-v1-...",
        "free_tier_note": "Tích hợp sẵn Base URL https://openrouter.ai/api/v1 — truy cập hàng trăm model AI hàng đầu.",
    },
    "Gemini (Google)": {
        "models": ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "key_help": "Lấy API key miễn phí tại aistudio.google.com/apikey.",
        "key_placeholder": "AIza...",
        "free_tier_note": "Free tier: giới hạn theo phút/ngày, dễ hết quota nếu dùng nhiều.",
    },
    "Qwen (Alibaba Cloud)": {
        "models": ["qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct", "qwen-max"],
        "key_help": "Lấy API key miễn phí tại bailian.console.alibabacloud.com (gói dùng thử ~1 triệu token miễn phí).",
        "key_placeholder": "sk-...",
        "free_tier_note": "Free tier hào phóng hơn Gemini — phù hợp để tránh hết quota khi test nhiều.",
    },
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# ---------------------------------------------------------
# Database & Network Constants
# ---------------------------------------------------------
LOCAL_HOST_ALIASES = ["localhost", "127.0.0.1", "host.docker.internal"]
MAX_TABLES_SCHEMA = 30
MAX_ROWS_CAP = 3000
MAX_BAR_CATEGORIES = 100
MAX_HISTORY_TURNS = 15
LOG_INLINE_MAX_CHARS = 220
FORECAST_METHOD_NAME = "Hồi quy tuyến tính (Linear Regression)"
