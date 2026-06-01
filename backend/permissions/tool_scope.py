from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal


ToolScopeSource = Literal["global", "skill", "agent", "session", "explicit_user"]
ToolScopeTrustLevel = Literal["system", "project", "user", "external", "unknown"]


@dataclass(frozen=True, slots=True)
class ToolScope:
    source: ToolScopeSource = "global"
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    capability_constraints: tuple[str, ...] = ()
    trust_level: ToolScopeTrustLevel = "unknown"
    reason: str = ""

    @classmethod
    def from_allowed_tools(
        cls,
        allowed_tools: Iterable[str] | None,
        *,
        source: ToolScopeSource = "global",
        trust_level: ToolScopeTrustLevel = "unknown",
        reason: str = "",
    ) -> "ToolScope":
        return cls(
            source=source,
            allowed_tools=_normalize_names(allowed_tools),
            trust_level=trust_level,
            reason=reason,
        )

    @property
    def has_allowed_filter(self) -> bool:
        return bool(self.allowed_tools)

    def allows(self, tool_name: str | None) -> bool:
        normalized = str(tool_name or "").strip()
        if not normalized:
            return False
        if normalized in set(self.denied_tools):
            return False
        if self.allowed_tools and normalized not in set(self.allowed_tools):
            return False
        return True

    def to_allowed_tools(self) -> list[str]:
        return list(self.allowed_tools)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillToolScope(ToolScope):
    skill_name: str = ""
    activation_policy: str = "model_visible"
    context_mode: str = "inline"


def _normalize_names(values: Iterable[str] | None) -> tuple[str, ...]:
    names = []
    seen = set()
    for value in values or []:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return tuple(names)


def coerce_tool_scope(
    scope: ToolScope | Iterable[str] | None,
    *,
    source: ToolScopeSource = "global",
    trust_level: ToolScopeTrustLevel = "unknown",
    reason: str = "",
) -> ToolScope:
    if isinstance(scope, ToolScope):
        return scope
    return ToolScope.from_allowed_tools(
        scope,
        source=source,
        trust_level=trust_level,
        reason=reason,
    )
