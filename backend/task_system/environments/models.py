from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EnvironmentKind = Literal[
    "development",
    "creation",
    "general",
    "custom",
]

PolicyMode = Literal["allowed", "denied", "ask", "task_decided", "sandboxed"]


@dataclass(frozen=True, slots=True)
class TaskEnvironmentGroup:
    group_id: str
    title: str
    description: str = ""
    enabled: bool = True
    authority: str = "task_system.task_environment_group"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskEnvironmentRecord:
    environment_id: str
    title: str
    description: str = ""
    group_id: str = "environment_group.general"
    enabled: bool = True
    owner: str = "system"
    environment_kind: EnvironmentKind = "custom"
    default_visibility: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_environment"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EnvironmentPrompt:
    prompt_id: str
    content: str = ""
    version: str = "v1"
    prompt_kind: str = "orientation"
    cache_scope: str = "static_environment"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not str(self.content or "").strip():
            payload.pop("content", None)
        return payload


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    enabled: bool = False
    sandbox_mode: str = "none"
    workspace_access: str = "none"
    write_policy: str = "none"
    shell_policy: PolicyMode = "denied"
    browser_policy: PolicyMode = "denied"
    network_policy: PolicyMode = "denied"
    side_effect_policy: str = "environment_boundary"
    sandbox_root_policy: str = "runtime_allocated"
    side_effect_operations: tuple[str, ...] = ()

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
    storage_namespace: str = ""
    storage_root_policy: str = "environment_scoped"
    runtime_state_root_policy: str = "environment_scoped_runtime_state"
    artifact_storage_policy: str = "environment_scoped_artifacts"
    cache_storage_policy: str = "environment_scoped_cache"
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
class TaskEnvironmentSpec:
    spec_id: str
    environment_id: str
    environment_prompts: tuple[EnvironmentPrompt, ...] = ()
    sandbox_policy: SandboxPolicy = field(default_factory=SandboxPolicy)
    file_management: FileManagementBinding = field(default_factory=FileManagementBinding)
    resource_space: ResourceSpace = field(default_factory=ResourceSpace)
    memory_space: MemorySpace = field(default_factory=MemorySpace)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    risk_policy: RiskPolicy = field(default_factory=RiskPolicy)
    artifact_policy: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    observability_policy: dict[str, Any] = field(default_factory=dict)
    lifecycle_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_environment_spec"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "environment_id": self.environment_id,
            "environment_prompts": [item.to_dict() for item in self.environment_prompts],
            "sandbox_policy": self.sandbox_policy.to_dict(),
            "file_management": self.file_management.to_dict(),
            "resource_space": self.resource_space.to_dict(),
            "memory_space": self.memory_space.to_dict(),
            "execution_policy": self.execution_policy.to_dict(),
            "risk_policy": self.risk_policy.to_dict(),
            "artifact_policy": self.artifact_policy.to_dict(),
            "observability_policy": dict(self.observability_policy),
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


