"""
Base Agent Abstract Class for Veraxus Multi-Agent System.
"""

from __future__ import annotations

import abc
import time
from typing import Any, Dict, Optional
from .agent_state import AgentState


class BaseAgent(abc.ABC):
    """Lớp cơ sở cho toàn bộ các Agent chuyên trách trong Veraxus."""

    def __init__(self, name: str, role: str, description: str):
        self.name = name
        self.role = role
        self.description = description

    @abc.abstractmethod
    def run(self, state: AgentState) -> AgentState:
        """Thực thi nhiệm vụ chuyên môn của Agent và cập nhật state."""
        pass

    def log(self, state: AgentState, action: str, status: str = "SUCCESS", details: str = ""):
        """Ghi nhận hành động vào trace của state."""
        state.log_activity(self.name, action, status, details)

    def communicate(self, state: AgentState, recipient: str, message: str, message_type: str = "INFO", metadata: Optional[Dict[str, Any]] = None):
        """Giao tiếp với agent khác trong hệ thống."""
        state.send_message(self.name, recipient, message, message_type, metadata)
