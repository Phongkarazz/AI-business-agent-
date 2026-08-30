"""
Universal AI Business Agent - Streamlit Application Entry Point.
"""

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.ui.state import init_session_state
from src.ui.sidebar import render_sidebar
from src.ui.components import render_result
from src.llm.agent import run_agent

# ---------------------------------------------------------
# 1. Cấu hình Trang Streamlit
# ---------------------------------------------------------
st.set_page_config(
    page_title="Universal AI Business Agent",
    page_icon="🤖",
    layout="wide"
)

# ---------------------------------------------------------
# 2. Khởi tạo Session State & Sidebar
# ---------------------------------------------------------
init_session_state()
render_sidebar()

# ---------------------------------------------------------
# 3. Giao diện Chính (Main Chat Area)
# ---------------------------------------------------------
st.title("🤖 AI Business Agent for SQL")
st.caption("Truy vấn cơ sở dữ liệu bằng ngôn ngữ tự nhiên, tự động phát hiện Insight bất thường, trực quan hóa và dự báo xu hướng.")

# Hiển thị lịch sử hội thoại
for i, turn in enumerate(st.session_state["history"]):
    st.chat_message("user").write(turn["query"])
    with st.chat_message("assistant"):
        render_result(turn, turn_id=f"hist{i}")

# Trạng thái kết nối & Khung nhập câu hỏi
if not st.session_state.get("connected"):
    st.info("👈 **Hướng dẫn:** Chọn nguồn dữ liệu (Demo hoặc MySQL), chọn AI Provider & nhập API Key ở thanh bên trái, sau đó bấm **'Kết nối Database & AI'**.")
else:
    if st.session_state.get("is_demo"):
        st.caption("🎮 Đang dùng dữ liệu mẫu — Gợi ý câu hỏi: *\"Doanh số theo từng tháng năm 2023\"*, *\"Top 5 nhân viên có doanh số cao nhất\"*")

    user_input = st.chat_input("Hỏi bất kỳ điều gì về dữ liệu của bạn...")
    if user_input:
        st.chat_message("user").write(user_input)
        with st.chat_message("assistant"):
            cache_key = user_input.strip().lower()
            cached = st.session_state.get("query_cache", {}).get(cache_key)

            if st.session_state.get("enable_cache", True) and cached and not cached.get("error"):
                st.caption("♻️ Dùng lại kết quả đã hỏi trước đó trong phiên này (tiết kiệm quota API).")
                result = cached
                render_result(result, turn_id=f"new{len(st.session_state['history'])}")
            else:
                with st.spinner("Đang truy vấn & phân tích..."):
                    result = run_agent(
                        user_query=user_input,
                        client=st.session_state.get("client"),
                        provider=st.session_state.get("provider"),
                        model_name=st.session_state.get("model_name"),
                        engine=st.session_state.get("engine"),
                        schema_context=st.session_state.get("schema_context"),
                        dialect=st.session_state.get("db_dialect", "SQLite"),
                        db_pass=st.session_state.get("_db_pass_for_sanitize", ""),
                        enable_self_check=st.session_state.get("enable_self_check", True),
                        enable_auto_insights=st.session_state.get("enable_auto_insights", True)
                    )
                render_result(result, turn_id=f"new{len(st.session_state['history'])}")
                if not result.get("error"):
                    st.session_state.setdefault("query_cache", {})[cache_key] = result

        st.session_state["history"].append(result)
