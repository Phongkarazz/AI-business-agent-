"""
Data Auditor Agent (Kiểm toán viên Dữ liệu & Tác tử Phản biện Độc lập).
Chịu trách nhiệm: Thẩm định 4 trụ cột chất lượng dữ liệu (Semantic, Temporal, Comparative, Data Health),
phát hiện sai lệch và cung cấp Actionable Feedback để Data Engineer hiệu chỉnh.
"""

from __future__ import annotations

from typing import Any, Dict
from .base_agent import BaseAgent
from .agent_state import AgentState
from src.llm.evaluator import evaluate_execution


class DataAuditorAgent(BaseAgent):
    """Data Auditor Agent chuyên kiểm toán độc lập kết quả truy vấn."""

    def __init__(self):
        super().__init__(
            name="DataAuditorAgent",
            role="Kiểm toán viên Dữ liệu & Phản biện Độc lập",
            description="Độc lập thẩm định kết quả SQL theo 4 trụ cột dữ liệu, ngăn chặn ảo giác và sai sót nghiệp vụ."
        )

    def run(self, state: AgentState) -> AgentState:
        """Thực hiện thẩm định kết quả từ Data Engineer."""
        self.log(state, "Bắt đầu kiểm toán 4 trụ cột dữ liệu...")
        state.audit_attempts += 1

        # Nếu có lỗi runtime SQL
        if state.execution_error:
            state.is_audit_passed = False
            state.audit_feedback = f"Lỗi thực thi SQL: {state.execution_error}. Vui lòng sửa lại câu lệnh SQL."
            state.audit_report = {
                "verdict": "FAIL",
                "score": 0,
                "critique": f"Truy vấn thất bại với lỗi runtime: {state.execution_error}",
                "actionable_feedback": state.audit_feedback,
                "criteria": {
                    "data_health": {"passed": False, "detail": state.execution_error},
                    "semantic_alignment": {"passed": False, "detail": "Chưa có dữ liệu."},
                    "temporal_validity": {"passed": False, "detail": "Chưa có dữ liệu."},
                    "comparative_sufficiency": {"passed": False, "detail": "Chưa có dữ liệu."}
                }
            }
            self.log(state, f"Kiểm toán thất bại: Lỗi runtime ({state.execution_error})", status="FAIL")
            self.communicate(state, "DataEngineerAgent", state.audit_feedback, message_type="CRITIQUE")
            return state

        plan_dict = {
            "complexity": state.plan.complexity if state.plan else "DIRECT_SQL",
            "entities": state.plan.entities if state.plan else [],
            "metrics": state.plan.metrics if state.plan else [],
            "guidance": state.plan.guidance if state.plan else ""
        } if state.plan else None

        # Đánh giá 4 trụ cột bằng Evaluator Engine
        eval_result = evaluate_execution(
            user_query=state.user_query,
            sql_query=state.current_sql,
            df=state.df_result,
            schema_context=state.schema_context,
            plan=plan_dict,
            lang=state.lang
        )

        state.audit_report = eval_result
        verdict = eval_result.get("verdict", "FAIL")
        score = eval_result.get("score", 0)
        feedback = eval_result.get("actionable_feedback", "")

        if verdict == "PASS" and score == 100:
            state.is_audit_passed = True
            state.audit_feedback = ""
            self.log(state, f"Kiểm toán ĐẠT TUYỆT ĐỐI (Điểm: {score}/100) - Toàn vẹn 4 trụ cột dữ liệu.", status="PASS")
            self.communicate(state, "SupervisorAgent", f"Dữ liệu đã được kiểm toán hoàn hảo (Điểm: {score}/100). Cho phép chuyển giao sang BI & Strategy Squad.", message_type="RESULT")
        else:
            state.is_audit_passed = False
            state.audit_feedback = feedback
            self.log(state, f"Kiểm toán CHƯA ĐẠT (Điểm: {score}/100) - {eval_result.get('critique', '')}", status="FAIL")
            self.communicate(state, "DataEngineerAgent", f"Yêu cầu sửa lại SQL: {feedback}", message_type="CRITIQUE")

        return state
