from __future__ import annotations

from .agent_config import HEALTH_AGENT_ID, HEALTH_SESSION_ID

HEALTH_TASK_ID_BY_ACTION: dict[str, str] = {}


def health_specific_task_id(health_action: str) -> str:
    _ = health_action
    return ""


