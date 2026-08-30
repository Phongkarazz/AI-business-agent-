"""
Configuration and Constants for Veraxus for SQL.
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
NAME_LIKE_REGEX = re.compile(
    r'(name|ten|title|category|product|team|region|department|dept|quoc_gia|quoc gia|country|geo|khu_vuc|khu vuc|tinh|thanh_pho|thanh pho|city)',
    re.IGNORECASE
)

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
        "key_placeholder": "AIzaSy...",
        "free_tier_note": "15 RPM miễn phí, dùng tốt nhất với gemini-2.5-flash.",
    },
    "Qwen (Alibaba Cloud)": {
        "models": ["qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct", "qwen-max"],
        "key_help": "Lấy API key tại alibabacloud.com (DashScope console).",
        "key_placeholder": "sk-...",
        "free_tier_note": "Model Qwen của Alibaba Cloud, tương thích OpenAI SDK.",
    },
}

# ---------------------------------------------------------
# Base URLs & Method Names
# ---------------------------------------------------------
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MAX_ROWS_CAP = 5000
MAX_TABLES_SCHEMA = 50
MAX_HISTORY_TURNS = 20
MAX_BAR_CATEGORIES = 100

FORECAST_METHOD_NAME = "Hồi quy tuyến tính (Linear Regression)"
