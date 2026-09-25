"""
Executive Strategy Advisor Agent (Cố vấn Chiến lược Cấp cao & Thư ký Ban Giám Đốc).
Chịu trách nhiệm: Tổng hợp nhận định kinh doanh dựa trên dữ liệu chuẩn xác và điểm bất thường,
xây dựng Ma trận Hành động C-Suite (Khẩn cấp / Ngắn hạn / Dài hạn) và soạn thảo Nghị quyết HĐQT.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List
import pandas as pd

from .base_agent import BaseAgent
from .agent_state import AgentState
from src.llm.client import invoke_llm
from src.llm.prompts import (
    build_auto_insight_prompt,
    build_followup_prompt,
)
from src.analytics.heuristics import (
    sanitize_insight_markdown,
    sanitize_followup_question,
)


class StrategyAdvisorAgent(BaseAgent):
    """Executive Strategy Advisor Agent chuyên hoạch định chiến lược và soạn thảo nghị quyết."""

    def __init__(self):
        super().__init__(
            name="StrategyAdvisorAgent",
            role="Cố vấn Chiến lược Cấp cao & Thư ký HĐQT",
            description="Chuyển hóa dữ liệu và dị biệt thành khuyến nghị quản trị thực chiến, ma trận hành động và nghị quyết chiến lược."
        )

    def run(self, state: AgentState) -> AgentState:
        """Sinh nhận định kinh doanh, ma trận giải pháp và soạn thảo nghị quyết."""
        self.log(state, "Bắt đầu tổng hợp nhận định kinh doanh và xây dựng chiến lược quản trị...")

        if state.df_result is None or state.df_result.empty:
            state.executive_summary = "Không có đủ dữ liệu để xây dựng chiến lược."
            return state

        df = state.df_result
        is_en = (state.lang == "en")

        # 1. Sinh Executive Insight & Business Recommendations
        try:
            insight_prompt = build_auto_insight_prompt(
                user_query=state.user_query,
                df=df,
                sql_query=state.current_sql,
                lang=state.lang
            )
            raw_insight = invoke_llm(insight_prompt)
            clean_insight = sanitize_insight_markdown(raw_insight, df, is_en=is_en)
            state.executive_summary = clean_insight
        except Exception as e:
            state.executive_summary = f"Tổng hợp nhận định kinh doanh cơ bản dựa trên {len(df)} dòng dữ liệu."

        # 2. Xây dựng Ma trận Hành động C-Suite (Action Matrix)
        action_matrix = {
            "urgent": [],
            "short_term": [],
            "long_term": []
        }
        
        # Nếu có điểm dị biệt từ AnomalyDetectiveAgent, đưa trực tiếp vào ma trận giải pháp
        if state.anomalies:
            for i, anom in enumerate(state.anomalies[:3]):
                desc = anom.get("description", "")
                metric = anom.get("metric", "")
                if i == 0:
                    action_matrix["urgent"].append(f"Xử lý dứt điểm dị biệt: {desc} (Ưu tiên kiểm soát biến động {metric}).")
                elif i == 1:
                    action_matrix["short_term"].append(f"Tái cấu trúc và tối ưu phân bổ: {desc}.")
                else:
                    action_matrix["long_term"].append(f"Thiết lập cơ chế giám sát tự động và quy chuẩn hóa: {desc}.")
        else:
            action_matrix["short_term"].append("Tối ưu hóa hiệu suất vận hành theo các nhóm dẫn đầu." if not is_en else "Optimize operational performance based on leading segments.")
            action_matrix["long_term"].append("Mở rộng quy mô và nhân rộng mô hình kinh doanh hiệu quả." if not is_en else "Scale up proven successful business models.")

        state.action_matrix = action_matrix

        # 3. Soạn thảo Dự thảo Nghị quyết Chiến lược (Board Resolution Markdown)
        resolution_md = self._generate_board_resolution(state, is_en=is_en)
        state.resolution_markdown = resolution_md

        # 4. Gợi ý câu hỏi đào sâu thông minh (Follow-up Questions)
        try:
            followup_prompt = build_followup_prompt(
                user_query=state.user_query,
                df=df,
                sql_query=state.current_sql,
                lang=state.lang
            )
            raw_followup = invoke_llm(followup_prompt)
            questions = [
                sanitize_followup_question(q.strip(), state.user_query, is_en=is_en)
                for q in raw_followup.split("\n")
                if q.strip() and not q.strip().startswith("#")
            ]
            state.follow_up_questions = [q for q in questions if len(q) > 8][:3]
        except Exception:
            state.follow_up_questions = []

        self.log(state, "Hoàn tất soạn thảo chiến lược và dự thảo nghị quyết điều hành.", status="SUCCESS")
        self.communicate(state, "SupervisorAgent", "Đã hoàn thành toàn bộ gói báo cáo chiến lược cấp cao.", message_type="RESULT")
        return state

    def _generate_board_resolution(self, state: AgentState, is_en: bool = False) -> str:
        """Tạo nội dung Nghị quyết Ban Giám Đốc chuẩn mực."""
        q = state.user_query
        df = state.df_result
        row_cnt = len(df) if df is not None else 0
        
        title = "NGHỊ QUYẾT HỘI ĐỒNG QUẢN TRỊ & BAN ĐIỀU HÀNH" if not is_en else "BOARD OF DIRECTORS & EXECUTIVE RESOLUTION"
        sub = f"V/v: Thông qua định hướng và kế hoạch hành động chiến lược cho chủ đề: '{q}'" if not is_en else f"Subj: Strategic Resolution on '{q}'"
        
        res = [
            f"# 📜 {title}",
            f"### *{sub}*",
            f"**Căn cứ thẩm định:** Hệ thống Multi-Agent Veraxus phân tích dựa trên {row_cnt} bản ghi dữ liệu thực chứng.",
            "",
            "---",
            "### ĐIỀU 1: GHI NHẬN THỰC TRẠNG VÀ CÁC ĐIỂM DỊ BIỆT CỐT LÕI",
            state.executive_summary or "Dữ liệu kinh doanh đã được kiểm toán và phản ánh trung thực hiện trạng vận hành.",
            "",
            "### ĐIỀU 2: PHÊ DUYỆT MA TRẬN KẾ HOẠCH HÀNH ĐỘNG C-SUITE",
        ]

        if state.action_matrix.get("urgent"):
            res.append("#### 🚨 1. Nhóm Hành Động Khẩn Cấp (Immediate Action)")
            for item in state.action_matrix["urgent"]:
                res.append(f"- {item}")

        if state.action_matrix.get("short_term"):
            res.append("#### ⚡ 2. Nhóm Tối Ưu Ngắn Hạn (Tactical Optimization)")
            for item in state.action_matrix["short_term"]:
                res.append(f"- {item}")

        if state.action_matrix.get("long_term"):
            res.append("#### 🎯 3. Nhóm Định Hướng Dài Hạn (Strategic Transformation)")
            for item in state.action_matrix["long_term"]:
                res.append(f"- {item}")

        res.extend([
            "",
            "### ĐIỀU 3: HIỆU LỰC THI HÀNH",
            "- Nghị quyết này có hiệu lực kể từ ngày ban hành. Toàn thể các khối phòng ban, nhân sự liên quan chịu trách nhiệm thi hành nghiêm túc.",
            "- Giao cho Trưởng các bộ phận chuyên trách định kỳ báo cáo tiến độ qua Bảng điều khiển Quản trị Veraxus."
        ])

        return "\n".join(res)
