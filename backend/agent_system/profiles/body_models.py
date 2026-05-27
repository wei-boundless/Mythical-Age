from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentBodyProfile:
    body_profile_id: str
    agent_id: str
    default_prompt_structure_profile_id: str
    default_memory_scope_profile_id: str
    default_runtime_lane_profile_id: str
    default_output_boundary_profile_id: str
    default_operation_policy_mode: str = "fail_closed"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.agent_body_profile"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.agent_body_profile":
            raise ValueError("AgentBodyProfile authority must be orchestration.agent_body_profile")
        if not self.body_profile_id:
            raise ValueError("AgentBodyProfile requires body_profile_id")
        if not self.agent_id:
            raise ValueError("AgentBodyProfile requires agent_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PromptStructureProfile:
    profile_id: str
    section_order: tuple[str, ...]
    required_section_kinds: tuple[str, ...]
    optional_section_kinds: tuple[str, ...] = ()
    stage_projection_policy: str = "projection_snapshot_required"
    model_visible_rules: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.prompt_structure_profile"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.prompt_structure_profile":
            raise ValueError("PromptStructureProfile authority must be orchestration.prompt_structure_profile")
        if not self.profile_id:
            raise ValueError("PromptStructureProfile requires profile_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_order"] = list(self.section_order)
        payload["required_section_kinds"] = list(self.required_section_kinds)
        payload["optional_section_kinds"] = list(self.optional_section_kinds)
        return payload


@dataclass(frozen=True, slots=True)
class MemoryScopeProfile:
    profile_id: str
    allowed_memory_layers: tuple[str, ...]
    read_scope: str
    writeback_policy: str
    token_budget_policy: str = "context_package"
    restore_policy: str = "session_state_first"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.memory_scope_profile"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.memory_scope_profile":
            raise ValueError("MemoryScopeProfile authority must be orchestration.memory_scope_profile")
        if not self.profile_id:
            raise ValueError("MemoryScopeProfile requires profile_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_memory_layers"] = list(self.allowed_memory_layers)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeLaneProfile:
    profile_id: str
    lane_id: str
    execution_style: str
    tool_followup_policy: str
    checkpoint_policy: str
    resume_policy: str
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_lane_profile"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_lane_profile":
            raise ValueError("RuntimeLaneProfile authority must be orchestration.runtime_lane_profile")
        if not self.profile_id:
            raise ValueError("RuntimeLaneProfile requires profile_id")
        if not self.lane_id:
            raise ValueError("RuntimeLaneProfile requires lane_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OutputBoundaryProfile:
    profile_id: str
    allowed_output_contracts: tuple[str, ...]
    citation_policy: str
    artifact_commit_policy: str
    finalization_policy: str
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.output_boundary_profile"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.output_boundary_profile":
            raise ValueError("OutputBoundaryProfile authority must be orchestration.output_boundary_profile")
        if not self.profile_id:
            raise ValueError("OutputBoundaryProfile requires profile_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_output_contracts"] = list(self.allowed_output_contracts)
        return payload


