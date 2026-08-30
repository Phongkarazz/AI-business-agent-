"""
Configuration persistence manager for saving and loading user credentials and settings.
"""

import os
import json
from typing import Dict, Any

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".saved_config.json")


def load_saved_config() -> Dict[str, Any]:
    """Tải cấu hình đã lưu từ file .saved_config.json và fallback vào biến môi trường."""
    config: Dict[str, Any] = {
        "data_mode_index": 0,
        "run_local": False,
        "db_host": os.getenv("DB_HOST", "localhost"),
        "db_port": os.getenv("DB_PORT", "3306"),
        "db_user": os.getenv("DB_USER", "root"),
        "db_pass": os.getenv("DB_PASSWORD", ""),
        "db_name": os.getenv("DB_NAME", ""),
        "use_ssl": os.getenv("DB_USE_SSL", "false").lower() == "true",
        "provider": "OpenRouter",
        "api_key_openrouter": os.getenv("OPENROUTER_API_KEY", ""),
        "api_key_gemini": os.getenv("GEMINI_API_KEY", ""),
        "api_key_qwen": os.getenv("DASHSCOPE_API_KEY", ""),
        "model_name": "",
        "openrouter_base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        "custom_openrouter_model": "",
        "qwen_base_url": os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        "enable_self_check": True,
        "enable_cache": True,
        "enable_auto_insights": True,
        "forecast_periods": 3,
        "remember_config": True,
        "auto_connect": True,
    }

    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    config.update(saved)
        except Exception:
            pass

    return config


def save_user_config(config_data: Dict[str, Any]) -> bool:
    """Lưu cấu hình người dùng vào file .saved_config.json."""
    try:
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def clear_saved_config() -> bool:
    """Xóa file cấu hình đã lưu."""
    try:
        if os.path.exists(CONFIG_FILE_PATH):
            os.remove(CONFIG_FILE_PATH)
        return True
    except Exception:
        return False
