"""
Shared State & Protocol Data Structures for Veraxus Multi-Agent System (MAS).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd


@dataclass
class AgentMessage:
    """Tin nhắn giao tiếp chuẩn giữa các Agent."""
    sender: str
    recipient: str
    content: str
    message_type: str = "INFO"  # INFO, REQUEST, CRITIQUE, FEEDBACK, RESULT, ERROR
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskPlan:
    """Kế hoạch thực thi do Router / Supervisor Agent phân rã."""
    complexity: str = "DIRECT_SQL"  # DIRECT_SQL, MULTI_STEP_ANALYTIC, BENCHMARK_EXTREMES, TIME_SERIES_COHORT
    entities: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)
    timeframe: Optional[str] = None
    subtasks: List[str] = field(default_factory=list)
    guidance: str = ""
    is_chocolates_domain: bool = False
    is_employees_domain: bool = False


@dataclass
class AgentState:
    """Trạng thái tổng hợp chia sẻ (Shared State / Blackboard) giữa toàn bộ các Agent."""
    user_query: str
    db_engine: Any = None
    schema_context: str = ""
    lang: str = "vi"
    
    # 1. Router / Planner Output
    plan: Optional[TaskPlan] = None
    
    # 2. Data Engineer Output
    current_sql: str = ""
    sql_history: List[str] = field(default_factory=list)
    df_result: Optional[pd.DataFrame] = None
    execution_error: Optional[str] = None
    execution_time_ms: float = 0.0
    
    # 3. Data Auditor Output
    audit_report: Dict[str, Any] = field(default_factory=dict)
    is_audit_passed: bool = False
    audit_feedback: str = ""
    audit_attempts: int = 0
    max_audit_attempts: int = 3
    
    # 4. Anomaly Detective Output
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    trend_summary: Dict[str, Any] = field(default_factory=dict)
    
    # 5. Strategy Advisor Output
    executive_summary: str = ""
    strategic_recommendations: List[str] = field(default_factory=list)
    action_matrix: Dict[str, List[str]] = field(default_factory=dict)
    resolution_markdown: str = ""
    follow_up_questions: List[str] = field(default_factory=list)
    
    # Trace & Logs
    messages: List[AgentMessage] = field(default_factory=list)
    activity_logs: List[Dict[str, Any]] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    
    def log_activity(self, agent_name: str, action: str, status: str = "SUCCESS", details: str = ""):
        """Ghi vết hoạt động minh bạch của từng Agent."""
        self.activity_logs.append({
            "timestamp": time.time(),
            "agent": agent_name,
            "action": action,
            "status": status,
            "details": details,
            "elapsed_ms": round((time.time() - self.start_time) * 1000, 1)
        })

    def send_message(self, sender: str, recipient: str, content: str, message_type: str = "INFO", metadata: Optional[Dict[str, Any]] = None):
        """Gửi thông điệp giữa các Agent."""
        msg = AgentMessage(
            sender=sender,
            recipient=recipient,
            content=content,
            message_type=message_type,
            metadata=metadata or {}
        )
        self.messages.append(msg)
