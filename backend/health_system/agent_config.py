from __future__ import annotations

from dataclasses import dataclass
from typing import Any


HEALTH_AGENT_ID = "agent:3"
HEALTH_SESSION_ID = "health-system"
HEALTH_AGENT_CONFIG_STATUS = "not_rebuilt"
HEALTH_AGENT_CONFIG_BLOCK_REASON = "health_agent_config_not_rebuilt"


@dataclass(frozen=True, slots=True)
class HealthAgentConfigUnavailable(RuntimeError):
    health_action: str = ""

    def __str__(self) -> str:
        suffix = f":{self.health_action}" if self.health_action else ""
        return f"{HEALTH_AGENT_CONFIG_BLOCK_REASON}{suffix}"


def health_agent_unavailable_diagnostics(*, health_action: str = "") -> dict[str, Any]:
    return {
        "authority": "health_system.agent_config",
        "status": HEALTH_AGENT_CONFIG_STATUS,
        "agent_id": HEALTH_AGENT_ID,
        "health_action": str(health_action or "").strip(),
        "blocked_reason": HEALTH_AGENT_CONFIG_BLOCK_REASON,
        "message": "Health agent runtime config was intentionally cleared; rebuild backend/health_system/agent_config.py before enabling agent execution.",
    }


