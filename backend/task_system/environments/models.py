from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EnvironmentKind = Literal[
    "writing",
    "vibe_coding",
    "web_research",
    "data_analysis",
    "document_processing",
    "general_workspace",
    "custom",
]

PolicyMode = Literal["allowed", "denied", "ask", "task_decided", "sandboxed"]


@dataclass(frozen=True, slots=True)
class TaskEnvironmentRecord:
    environment_id: str
    title: str
    description: str = ""
    enabled: bool = True
    owner: str = "system"
    environment_kind: EnvironmentKind = "custom"
    default_visibility: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_environment"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PromptSpace:
    allowed_prompt_libraries: tuple[str, ...] = ()
    allowed_prompt_packs: tuple[str, ...] = ()
    default_prompt_pack_refs: tuple[str, ...] = ()
    flow_prompt_pack_refs: tuple[str, ...] = ()
    reviewer_prompt_pack_refs: tuple[str, ...] = ()
    prompt_selection_policy: str = "specific_task_selects"
    prompt_version_policy: str = "pinned_or_latest_stable"

    def to_dict(self) -> dict[str, Any]:
        return _tuple_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class SkillSpace:
    allowed_skill_refs: tuple[str, ...] = ()
    denied_skill_refs: tuple[str, ...] = ()
    skill_pack_refs: tuple[str, ...] = ()
    skill_loading_policy: str = "specific_task_selects"
    skill_version_policy: str = "pinned_or_latest_stable"
    skill_context_policy: str = "role_task_boundary_only"

    def to_dict(self) -> dict[str, Any]:
        return _tuple_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class ToolSpace:
    allowed_operation_market: tuple[str, ...] = ()
    denied_operation_refs: tuple[str, ...] = ()
    allowed_tool_market: tuple[str, ...] = ()
    denied_tool_refs: tuple[str, ...] = ()
    allowed_mcp_routes: tuple[str, ...] = ()
    browser_policy: PolicyMode = "denied"
    shell_policy: PolicyMode = "denied"
    network_policy: PolicyMode = "denied"
    tool_discovery_policy: str = "static_market"

    def to_dict(self) -> dict[str, Any]:
        return _tuple_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class FileManagementBinding:
    file_profile_refs: tuple[str, ...] = ()
    required_repository_kinds: tuple[str, ...] = ()
    canonical_write_policy: str = "commit_gate_required"
    artifact_projection_policy: str = "file_profile_projection"
    memory_projection_policy: str = "file_profile_projection"
    constraints: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_environment.file_management_binding"

    def to_dict(self) -> dict[str, Any]:
        return _tuple_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class ResourceSpace:
    workspace_policy: str = "none"
    material_mount_policy: str = "none"
    project_file_policy: str = "none"
    managed_file_environment_policy: str = "file_management_required"
    external_service_policy: str = "none"
    browser_environment_policy: str = "none"
    mcp_environment_policy: str = "none"
    artifact_root_policy: str = "file_management_projection"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemorySpace:
    environment_memory_refs: tuple[str, ...] = ()
    project_knowledge_refs: tuple[str, ...] = ()
    shared_context_refs: tuple[str, ...] = ()
    retrieval_index_refs: tuple[str, ...] = ()
    read_policy: str = "file_profile_projection"
    write_policy: str = "file_profile_projection"
    projection_policy: str = "from_file_management"

    def to_dict(self) -> dict[str, Any]:
        return _tuple_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    sandbox_required: bool | str = False
    sandbox_mode: str = "none"
    real_workspace_access: str = "none"
    write_scope_policy: str = "file_access_table"
    shell_execution_policy: PolicyMode = "denied"
    browser_execution_policy: PolicyMode = "denied"
    network_execution_policy: PolicyMode = "denied"
    side_effect_policy: str = "permission_context"
    max_runtime_policy: str = "task_decided"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    default_permission_mode: str = "deny_by_default"
    approval_required_risk_levels: tuple[str, ...] = ()
    auto_denied_risk_levels: tuple[str, ...] = ()
    reviewer_required_operations: tuple[str, ...] = ()
    denial_tracking_policy: str = "record_denials"
    audit_receipt_policy: str = "required"

    def to_dict(self) -> dict[str, Any]:
        return _tuple_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class ArtifactPolicy:
    artifact_root: str = "file_management_projection"
    naming_policy: str = "contract_scoped"
    version_policy: str = "file_profile_version_policy"
    overwrite_policy: str = "versioned_no_blind_overwrite"
    publish_policy: str = "commit_gate"
    cleanup_policy: str = "retention_policy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    allowed_runtime_lanes: tuple[str, ...] = ()
    preferred_runtime_lanes: tuple[str, ...] = ()
    forbidden_runtime_lanes: tuple[str, ...] = ()
    graph_allowed: bool = True
    delegation_allowed: bool = False
    human_gate_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _tuple_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class TaskEnvironmentSpec:
    spec_id: str
    environment_id: str
    prompt_space: PromptSpace = field(default_factory=PromptSpace)
    skill_space: SkillSpace = field(default_factory=SkillSpace)
    tool_space: ToolSpace = field(default_factory=ToolSpace)
    file_management: FileManagementBinding = field(default_factory=FileManagementBinding)
    resource_space: ResourceSpace = field(default_factory=ResourceSpace)
    memory_space: MemorySpace = field(default_factory=MemorySpace)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    risk_policy: RiskPolicy = field(default_factory=RiskPolicy)
    artifact_policy: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    observability_policy: dict[str, Any] = field(default_factory=dict)
    runtime_policy: RuntimePolicy = field(default_factory=RuntimePolicy)
    lifecycle_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_environment_spec"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "environment_id": self.environment_id,
            "prompt_space": self.prompt_space.to_dict(),
            "skill_space": self.skill_space.to_dict(),
            "tool_space": self.tool_space.to_dict(),
            "file_management": self.file_management.to_dict(),
            "resource_space": self.resource_space.to_dict(),
            "memory_space": self.memory_space.to_dict(),
            "execution_policy": self.execution_policy.to_dict(),
            "risk_policy": self.risk_policy.to_dict(),
            "artifact_policy": self.artifact_policy.to_dict(),
            "observability_policy": dict(self.observability_policy),
            "runtime_policy": self.runtime_policy.to_dict(),
            "lifecycle_policy": dict(self.lifecycle_policy),
            "metadata": dict(self.metadata),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class TaskEnvironmentDefinition:
    record: TaskEnvironmentRecord
    spec: TaskEnvironmentSpec

    def to_dict(self) -> dict[str, Any]:
        return {"record": self.record.to_dict(), "spec": self.spec.to_dict()}


def _tuple_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in payload.items()
    }


