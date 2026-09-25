"""
Master Supervisor & Orchestrator Agent for Veraxus Multi-Agent System.
Chịu trách nhiệm: Tiếp nhận mục tiêu từ người dùng, lập kế hoạch phân rã, điều phối Maker-Checker loop
giữa Data Engineer & Auditor, và kích hoạt biệt đội BI & Strategy.
"""

from __future__ import annotations

import time
import concurrent.futures
from typing import Any, Dict, Optional
import pandas as pd

from .agent_state import AgentState, TaskPlan
from .base_agent import BaseAgent
from .data_engineer_agent import DataEngineerAgent
from .data_auditor_agent import DataAuditorAgent
from .anomaly_detective_agent import AnomalyDetectiveAgent
from .strategy_advisor_agent import StrategyAdvisorAgent
from src.llm.router_planner import classify_query_complexity, route_and_plan
from src.analytics.heuristics import detect_query_language


class SupervisorAgent(BaseAgent):
    """Master Supervisor Agent đóng vai trò Tổng quản điều phối toàn bộ hệ thống."""

    def __init__(self):
        super().__init__(
            name="SupervisorAgent",
            role="Tổng Quản Điều Phối & Nhạc Trưởng Multi-Agent",
            description="Lập kế hoạch phân rã, giám sát tiến trình, điều phối đàm thoại giữa các Agent chuyên trách."
        )
        self.data_engineer = DataEngineerAgent()
        self.data_auditor = DataAuditorAgent()
        self.anomaly_detective = AnomalyDetectiveAgent()
        self.strategy_advisor = StrategyAdvisorAgent()

    def run(self, state: AgentState) -> AgentState:
        """Điều phối toàn trình quy trình Multi-Agent."""
        self.log(state, f"Tiếp nhận yêu cầu: '{state.user_query}' | Khởi tạo quy trình Multi-Agent...")

        # BƯỚC 1: ROUTING & TASK PLANNING
        self.log(state, "Phân tích ngữ nghĩa & Lập kế hoạch thực thi (Task Planning)...")
        complexity = classify_query_complexity(state.user_query)
        plan_data = route_and_plan(state.user_query, state.schema_context)
        
        state.plan = TaskPlan(
            complexity=complexity,
            entities=plan_data.get("entities", []),
            metrics=plan_data.get("metrics", []),
            timeframe=plan_data.get("timeframe"),
            subtasks=plan_data.get("subtasks", []),
            guidance=plan_data.get("guidance", ""),
            is_chocolates_domain="sales" in (state.schema_context or "").lower() or "products" in (state.schema_context or "").lower(),
            is_employees_domain="employees" in (state.schema_context or "").lower() or "salaries" in (state.schema_context or "").lower()
        )
        self.log(state, f"Kế hoạch phân rã: Độ phức tạp [{complexity}], Phân nhánh: {len(state.plan.subtasks)} nhiệm vụ con.")

        # BƯỚC 2: MAKER-CHECKER COLLABORATION LOOP (Data Engineer <-> Data Auditor)
        while state.audit_attempts < state.max_audit_attempts:
            # 2.1 Data Engineer sinh / sửa SQL
            state = self.data_engineer.run(state)

            # 2.2 Data Auditor thẩm định độc lập 4 trụ cột dữ liệu
            state = self.data_auditor.run(state)

            if state.is_audit_passed:
                self.log(state, "Dữ liệu đã vượt qua vòng kiểm toán độc lập. Tiếp tục chuyển giao sang Intelligence Squad.", status="SUCCESS")
                break
            else:
                self.log(
                    state,
                    f"Vòng kiểm toán {state.audit_attempts}/{state.max_audit_attempts} chưa đạt. Kích hoạt Self-Correction Loop...",
                    status="RETRY"
                )

        # BƯỚC 3: INTELLIGENCE & STRATEGY SQUAD
        # Nếu có dữ liệu trả về, kích hoạt Anomaly Detective và Strategy Advisor
        if state.df_result is not None and not state.df_result.empty:
            # 3.1 Thám tử Dị biệt phân tích số liệu
            state = self.anomaly_detective.run(state)

            # 3.2 Cố vấn chiến lược xây dựng giải pháp và nghị quyết
            state = self.strategy_advisor.run(state)
        else:
            self.log(state, "Không có dữ liệu hợp lệ từ Database sau các vòng lặp sửa lỗi.", status="WARNING")

        self.log(state, "Hoàn tất toàn bộ quy trình Multi-Agent Pipeline.", status="FINISHED")
        return state


def run_multi_agent_pipeline(
    user_query: str,
    db_engine: Any,
    schema_context: str = "",
    lang: str = "vi"
) -> Dict[str, Any]:
    """Hàm facade tiện ích để chạy toàn bộ quy trình Multi-Agent và trả về kết quả chuẩn cho UI."""
    detected_lang = lang or detect_query_language(user_query)
    
    state = AgentState(
        user_query=user_query,
        db_engine=db_engine,
        schema_context=schema_context,
        lang=detected_lang
    )

    supervisor = SupervisorAgent()
    state = supervisor.run(state)

    # Đóng gói kết quả tương thích với toàn bộ hệ thống cũ
    return {
        "user_query": state.user_query,
        "sql": state.current_sql,
        "df": state.df_result,
        "error": state.execution_error,
        "evaluation": state.audit_report,
        "anomalies": state.anomalies,
        "trend_summary": state.trend_summary,
        "insight_markdown": state.executive_summary,
        "action_matrix": state.action_matrix,
        "resolution_markdown": state.resolution_markdown,
        "follow_up_questions": state.follow_up_questions,
        "activity_logs": state.activity_logs,
        "messages": [
            {
                "sender": m.sender,
                "recipient": m.recipient,
                "content": m.content,
                "type": m.message_type,
                "timestamp": m.timestamp
            }
            for m in state.messages
        ],
        "execution_time_ms": round((time.time() - state.start_time) * 1000, 2)
    }
