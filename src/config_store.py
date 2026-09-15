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
        "run_local": True,
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
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "smtp_server": os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": os.getenv("SMTP_PORT", "587"),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_pass": os.getenv("SMTP_PASSWORD", ""),
        "email_receivers": os.getenv("EMAIL_RECEIVERS", ""),
    }

    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    config.update(saved)
        except Exception:
            pass

    # Tự động đọc cấu hình từ Streamlit Cloud Secrets nếu có
    try:
        import streamlit as _st
        if hasattr(_st, "secrets"):
            sec = _st.secrets
            for k in sec:
                val = sec[k]
                if isinstance(val, str):
                    k_upper = k.upper()
                    if k_upper in ("OPENROUTER_API_KEY", "API_KEY_OPENROUTER"):
                        config["api_key_openrouter"] = val
                    elif k_upper in ("GEMINI_API_KEY", "API_KEY_GEMINI"):
                        config["api_key_gemini"] = val
                        if "provider" not in sec and "PROVIDER" not in sec:
                            config["provider"] = "Gemini (Google)"
                    elif k_upper in ("DEFAULT_PROVIDER", "PROVIDER"):
                        config["provider"] = val
                    elif k_upper in ("OPENROUTER_MODEL", "MODEL_NAME", "MODEL", "GEMINI_MODEL"):
                        config["model_name"] = val
                    elif k_upper in ("DB_HOST", "HOST"):
                        config["db_host"] = val
                    elif k_upper in ("DB_USER", "USER"):
                        config["db_user"] = val
                    elif k_upper in ("DB_PASSWORD", "DB_PASS", "PASSWORD"):
                        config["db_pass"] = val
                    elif k_upper in ("DB_NAME", "DATABASE"):
                        config["db_name"] = val
    except Exception:
        pass

    # Chuẩn hóa tên Provider
    p_val = str(config.get("provider", "")).strip()
    if p_val.lower() in ("gemini", "google", "google gemini", "gemini (google)"):
        config["provider"] = "Gemini (Google)"
    elif p_val.lower() in ("openrouter", "open router"):
        config["provider"] = "OpenRouter"

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
