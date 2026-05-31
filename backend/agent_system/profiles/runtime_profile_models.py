from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..models.model_profile_models import AgentModelProfile
from capability_system.tool_packages import ToolPackageSelection


@dataclass(frozen=True, slots=True)
class SubagentPolicy:
    enabled: bool = False
    allowed_subagent_ids: tuple[str, ...] = ()
    max_subagent_runs_per_task: int = 0
    max_active_subagents: int = 0
    context_policy: str = "summary_and_refs_only"
    result_policy: str = "observation_refs_only"
    allow_nested_subagents: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_subagent_ids"] = list(self.allowed_subagent_ids)
        return payload


@dataclass(frozen=True, slots=True)
class AgentRuntimeProfile:
    agent_profile_id: str
    agent_id: str
    allowed_tool_packages: tuple[ToolPackageSelection, ...] = ()
    extra_allowed_operations: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    blocked_operations: tuple[str, ...] = ()
    allowed_memory_scopes: tuple[str, ...] = ()
    allowed_context_sections: tuple[str, ...] = ()
    use_shared_contract: bool = True
    subagent_policy: SubagentPolicy = field(default_factory=SubagentPolicy)
    approval_policy: str = "default"
    trace_policy: str = "runtime_event_log"
    lifecycle_policy: str = "orchestration_managed"
    model_profile: AgentModelProfile = field(default_factory=AgentModelProfile)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def runtime_template_id(self) -> str:
        return str(self.metadata.get("runtime_template_id") or "").strip()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "extra_allowed_operations",
            "allowed_operations",
            "blocked_operations",
            "allowed_memory_scopes",
            "allowed_context_sections",
        ):
            payload[key] = list(payload[key])
        payload["subagent_policy"] = self.subagent_policy.to_dict()
        payload["allowed_tool_packages"] = [item.to_dict() for item in self.allowed_tool_packages]
        payload["final_allowed_operations"] = list(self.allowed_operations)
        payload["model_profile"] = self.model_profile.to_dict()
        payload["runtime_template_id"] = self.runtime_template_id
        return payload


