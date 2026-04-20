from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason: str
    allowed_tools: list[str] = field(default_factory=list)
    tool_name: str | None = None
    mode: str = "default"
    checks: list[str] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)
