"""
Streamlit session state initialization and management.
"""

import streamlit as st
from src.config import MAX_HISTORY_TURNS


def init_session_state():
    """Khởi tạo các biến mặc định trong st.session_state."""
    defaults = {
        "history": [],
        "query_cache": {},
        "connected": False,
        "engine": None,
        "client": None,
        "provider": "Gemini (Google)",
        "model_name": "gemini-2.5-flash",
        "schema_context": "",
        "is_demo": True,
        "db_dialect": "SQLite",
        "enable_self_check": True,
        "enable_cache": True,
        "forecast_periods": 3,
        "_db_pass_for_sanitize": "",
    }

    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Cắt gọn lịch sử nếu vượt quá giới hạn
    if len(st.session_state["history"]) > MAX_HISTORY_TURNS:
        st.session_state["history"] = st.session_state["history"][-MAX_HISTORY_TURNS:]
