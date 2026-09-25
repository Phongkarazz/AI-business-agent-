"""
BI & Anomaly Detective Agent (Thám tử Dị biệt & Phân tích Xu hướng Chuyên sâu).
Chịu trách nhiệm: Tự động rà soát phân phối dữ liệu, phát hiện các điểm gãy bất thường (Spike/Drop),
phân hóa phòng ban/thị trường, và bất đối xứng trong chỉ số kinh doanh.
"""

from __future__ import annotations

from typing import Any, Dict, List
import pandas as pd

from .base_agent import BaseAgent
from .agent_state import AgentState
from src.analytics.anomaly import analyze_data_anomalies


class AnomalyDetectiveAgent(BaseAgent):
    """BI & Anomaly Detective Agent chuyên phát hiện dị biệt kinh doanh."""

    def __init__(self):
        super().__init__(
            name="AnomalyDetectiveAgent",
            role="Thám tử Dị biệt & Chuyên gia Phân tích BI",
            description="Phân tích thống kê nâng cao, quét tìm điểm bất thường, đứt gãy xu hướng và phân hóa cấu trúc dữ liệu."
        )

    def run(self, state: AgentState) -> AgentState:
        """Quét và trích xuất danh sách điểm bất thường từ kết quả dữ liệu."""
        self.log(state, "Bắt đầu rà soát thống kê và phát hiện dị biệt dữ liệu...")

        if state.df_result is None or state.df_result.empty:
            self.log(state, "Không có dữ liệu để phân tích dị biệt.", status="SKIPPED")
            return state

        df = state.df_result

        # Phân tích dị biệt bằng Anomaly Engine
        anomalies = analyze_data_anomalies(df)
        state.anomalies = anomalies

        # Tổng hợp tóm tắt xu hướng cơ bản
        summary = {
            "total_rows": len(df),
            "columns": list(df.columns),
            "anomaly_count": len(anomalies)
        }
        state.trend_summary = summary

        if anomalies:
            self.log(
                state,
                f"Đã phát hiện {len(anomalies)} điểm dị biệt nghiệp vụ (Mức độ tác động cao).",
                status="SUCCESS",
                details=f"Dị biệt chính: {anomalies[0].get('description', '')}"
            )
            self.communicate(
                state,
                "StrategyAdvisorAgent",
                f"Đã phát hiện {len(anomalies)} điểm bất thường cần lưu ý chiến lược.",
                message_type="RESULT",
                metadata={"anomalies": anomalies}
            )
        else:
            self.log(state, "Dữ liệu phân phối ổn định, không ghi nhận biến động cực đoan.", status="SUCCESS")
            self.communicate(state, "StrategyAdvisorAgent", "Dữ liệu ổn định, sẵn sàng tổng hợp báo cáo kinh doanh.", message_type="RESULT")

        return state
