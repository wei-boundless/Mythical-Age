from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from file_management import default_file_environment_registry

from .models import (
    ArtifactPolicy,
    EnvironmentPrompt,
    ExecutionPolicy,
    FileManagementBinding,
    MemorySpace,
    ResourceSpace,
    RiskPolicy,
    SandboxPolicy,
    TaskEnvironmentDefinition,
    TaskEnvironmentGroup,
    TaskEnvironmentRecord,
    TaskEnvironmentSpec,
)


DEFAULT_ENVIRONMENT_CONFIG_PATH = Path("task_system/storage/task_environments/environments.json")

_FORBIDDEN_ENVIRONMENT_KEYS = {
    "tools",
    "tool_names",
    "allowed_tools",
    "denied_tools",
    "skills",
    "skill_space",
    "skill_candidates",
    "runtime_mode",
    "mode",
    "agent_profile",
    "agent_profile_id",
    "memory_assembly",
}


class TaskEnvironmentConfigError(ValueError):
    pass


class TaskEnvironmentRepository:
    def __init__(self, backend_dir: Path | str) -> None:
        self.backend_dir = Path(backend_dir)

    @property
    def config_path(self) -> Path:
        return self.backend_dir / DEFAULT_ENVIRONMENT_CONFIG_PATH

    def load(self) -> tuple[tuple[TaskEnvironmentGroup, ...], tuple[TaskEnvironmentDefinition, ...]]:
        path = self.config_path
        if not path.exists():
            return (), ()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TaskEnvironmentConfigError("task environment config root must be an object")
        _reject_forbidden_keys(payload, path="$")
        groups = tuple(_group_from_payload(item) for item in _list_payload(payload.get("groups"), path="$.groups"))
        environments = tuple(
            _definition_from_payload(item)
            for item in _list_payload(payload.get("environments"), path="$.environments")
        )
        return groups, environments


def load_configured_task_environments(
    backend_dir: Path | str,
) -> tuple[tuple[TaskEnvironmentGroup, ...], tuple[TaskEnvironmentDefinition, ...]]:
    return TaskEnvironmentRepository(backend_dir).load()


def _definition_from_payload(payload: Any) -> TaskEnvironmentDefinition:
    if not isinstance(payload, dict):
        raise TaskEnvironmentConfigError("environment item must be an object")
    _reject_forbidden_keys(payload, path="environment")
    record_payload = dict(payload.get("record") or {})
    spec_payload = dict(payload.get("spec") or {})
    if not record_payload:
        record_payload = {
            key: payload.get(key)
            for key in (
                "environment_id",
                "title",
                "description",
                "group_id",
                "enabled",
                "owner",
                "environment_kind",
                "default_visibility",
                "metadata",
            )
            if key in payload
        }
    if not spec_payload:
        spec_payload = {
            key: payload.get(key)
            for key in (
                "spec_id",
                "environment_id",
                "environment_prompts",
                "sandbox_policy",
                "file_management",
                "resource_space",
                "memory_space",
                "execution_policy",
                "risk_policy",
                "artifact_policy",
                "observability_policy",
                "lifecycle_policy",
                "metadata",
            )
            if key in payload
        }
    _reject_forbidden_keys(record_payload, path="environment.record")
    _reject_forbidden_keys(spec_payload, path="environment.spec")
    record = _dataclass_from_payload(TaskEnvironmentRecord, record_payload, path="environment.record")
    spec_payload.setdefault("environment_id", record.environment_id)
    spec_payload.setdefault("spec_id", f"envspec.{record.environment_id}.configured")
    spec = TaskEnvironmentSpec(
        spec_id=str(spec_payload.get("spec_id") or ""),
        environment_id=str(spec_payload.get("environment_id") or ""),
        environment_prompts=tuple(
            _dataclass_from_payload(EnvironmentPrompt, item, path="environment.spec.environment_prompts")
            for item in _list_payload(spec_payload.get("environment_prompts"), path="environment.spec.environment_prompts")
        ),
        sandbox_policy=_dataclass_from_payload(
            SandboxPolicy,
            dict(spec_payload.get("sandbox_policy") or {}),
            path="environment.spec.sandbox_policy",
        ),
        file_management=_dataclass_from_payload(
            FileManagementBinding,
            dict(spec_payload.get("file_management") or {}),
            path="environment.spec.file_management",
        ),
        resource_space=_dataclass_from_payload(
            ResourceSpace,
            dict(spec_payload.get("resource_space") or {}),
            path="environment.spec.resource_space",
        ),
        memory_space=_dataclass_from_payload(
            MemorySpace,
            dict(spec_payload.get("memory_space") or {}),
            path="environment.spec.memory_space",
        ),
        execution_policy=_dataclass_from_payload(
            ExecutionPolicy,
            dict(spec_payload.get("execution_policy") or {}),
            path="environment.spec.execution_policy",
        ),
        risk_policy=_dataclass_from_payload(
            RiskPolicy,
            dict(spec_payload.get("risk_policy") or {}),
            path="environment.spec.risk_policy",
        ),
        artifact_policy=_dataclass_from_payload(
            ArtifactPolicy,
            dict(spec_payload.get("artifact_policy") or {}),
            path="environment.spec.artifact_policy",
        ),
        observability_policy=dict(spec_payload.get("observability_policy") or {}),
        lifecycle_policy=dict(spec_payload.get("lifecycle_policy") or {}),
        metadata=dict(spec_payload.get("metadata") or {}),
    )
    _validate_definition(TaskEnvironmentDefinition(record=record, spec=spec))
    return TaskEnvironmentDefinition(record=record, spec=spec)


def _group_from_payload(payload: Any) -> TaskEnvironmentGroup:
    if not isinstance(payload, dict):
        raise TaskEnvironmentConfigError("environment group item must be an object")
    _reject_forbidden_keys(payload, path="environment.group")
    return _dataclass_from_payload(TaskEnvironmentGroup, payload, path="environment.group")


def _dataclass_from_payload(model: type, payload: dict[str, Any], *, path: str):
    if not is_dataclass(model):
        raise TaskEnvironmentConfigError(f"{model!r} is not a dataclass")
    field_names = {item.name for item in fields(model)}
    unknown = sorted(set(payload) - field_names)
    if unknown:
        raise TaskEnvironmentConfigError(f"{path} has unknown keys: {', '.join(unknown)}")
    values: dict[str, Any] = {}
    tuple_fields = {
        item.name
        for item in fields(model)
        if getattr(item.type, "__origin__", None) is tuple or str(item.type).startswith("tuple[")
    }
    for key, value in payload.items():
        values[key] = tuple(value or ()) if key in tuple_fields else value
    return model(**values)


def _validate_definition(definition: TaskEnvironmentDefinition) -> None:
    if not definition.record.environment_id:
        raise TaskEnvironmentConfigError("environment_id is required")
    if definition.record.environment_id != definition.spec.environment_id:
        raise TaskEnvironmentConfigError("record.environment_id must equal spec.environment_id")
    if not definition.record.group_id:
        raise TaskEnvironmentConfigError(f"{definition.record.environment_id}: group_id is required")
    namespace = str(definition.spec.resource_space.storage_namespace or "").strip()
    if namespace.startswith("/") or "\\" in namespace or ".." in Path(namespace).parts:
        raise TaskEnvironmentConfigError(f"{definition.record.environment_id}: invalid storage_namespace")
    file_registry = default_file_environment_registry()
    for profile_ref in definition.spec.file_management.file_profile_refs:
        file_registry.require_profile(str(profile_ref))


def _reject_forbidden_keys(payload: dict[str, Any], *, path: str) -> None:
    found = sorted(set(payload) & _FORBIDDEN_ENVIRONMENT_KEYS)
    if found:
        raise TaskEnvironmentConfigError(
            f"{path} contains agent/runtime assembly keys that task environments may not own: {', '.join(found)}"
        )
    for key, value in payload.items():
        if isinstance(value, dict):
            _reject_forbidden_keys(value, path=f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    _reject_forbidden_keys(item, path=f"{path}.{key}[{index}]")


def _list_payload(value: Any, *, path: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskEnvironmentConfigError(f"{path} must be a list")
    return list(value)
