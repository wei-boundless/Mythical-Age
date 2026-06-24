from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from file_management import default_file_environment_registry
from core.json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, json_file_lock, read_json_dict, write_json_dict
from prompt_library.migrations import migrate_prompt_ref

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

class TaskEnvironmentConfigError(ValueError):
    pass


class TaskEnvironmentRepository:
    def __init__(self, backend_dir: Path | str) -> None:
        self.backend_dir = Path(backend_dir)

    @property
    def config_path(self) -> Path:
        return self.backend_dir / DEFAULT_ENVIRONMENT_CONFIG_PATH

    def load(self) -> tuple[tuple[TaskEnvironmentGroup, ...], tuple[TaskEnvironmentDefinition, ...]]:
        with json_file_lock(self.config_path):
            payload = self._read_payload()
            normalized_payload = _normalize_environment_config_prompt_refs(payload)
            if normalized_payload != payload:
                self._write_payload(normalized_payload)
                payload = normalized_payload
        groups = tuple(_group_from_payload(item) for item in _list_payload(payload.get("groups"), path="$.groups"))
        environments = tuple(
            _definition_from_payload(item)
            for item in _list_payload(payload.get("environments"), path="$.environments")
        )
        return groups, environments

    def upsert_group(self, group: TaskEnvironmentGroup | dict[str, Any]) -> dict[str, Any]:
        with json_file_lock(self.config_path):
            payload = self._read_payload()
            group_model = group if isinstance(group, TaskEnvironmentGroup) else _group_from_payload(group)
            groups = [
                item
                for item in _list_payload(payload.get("groups"), path="$.groups")
                if str(dict(item).get("group_id") or "") != group_model.group_id
            ]
            groups.append(group_model.to_dict())
            payload["groups"] = sorted(groups, key=lambda item: str(dict(item).get("group_id") or ""))
            self._write_payload(payload)
            return payload

    def upsert_environment(self, environment: TaskEnvironmentDefinition | dict[str, Any]) -> dict[str, Any]:
        with json_file_lock(self.config_path):
            payload = self._read_payload()
            definition_payload = environment.to_dict() if isinstance(environment, TaskEnvironmentDefinition) else dict(environment)
            definition = _definition_from_payload(_normalize_environment_payload_prompt_refs(definition_payload))
            groups = tuple(_group_from_payload(item) for item in _list_payload(payload.get("groups"), path="$.groups"))
            group_ids = {group.group_id for group in groups}
            if definition.record.group_id not in group_ids and not _is_default_group_id(definition.record.group_id):
                raise TaskEnvironmentConfigError(f"unknown task environment group: {definition.record.group_id}")
            environments = [
                item
                for item in _list_payload(payload.get("environments"), path="$.environments")
                if str(_environment_id_from_payload(item) or "") != definition.record.environment_id
            ]
            environments.append(definition.to_dict())
            payload["environments"] = sorted(environments, key=lambda item: str(_environment_id_from_payload(item) or ""))
            self._write_payload(payload)
            return payload

    def delete_environment(self, environment_id: str) -> dict[str, Any]:
        target = str(environment_id or "").strip()
        if not target:
            raise TaskEnvironmentConfigError("environment_id is required")
        with json_file_lock(self.config_path):
            payload = self._read_payload()
            environments = _list_payload(payload.get("environments"), path="$.environments")
            next_environments = [
                item
                for item in environments
                if str(_environment_id_from_payload(item) or "") != target
            ]
            if len(next_environments) == len(environments):
                raise KeyError(f"configured task environment not found: {target}")
            payload["environments"] = next_environments
            self._write_payload(payload)
            return payload

    def _read_payload(self) -> dict[str, Any]:
        path = self.config_path
        try:
            payload = read_json_dict(
                path,
                label="task environment config",
                missing_factory=lambda: {"groups": [], "environments": []},
            )
        except (JsonFileStoreError, JsonFilePayloadCorrupt) as exc:
            raise TaskEnvironmentConfigError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise TaskEnvironmentConfigError("task environment config root must be an object")
        payload.setdefault("groups", [])
        payload.setdefault("environments", [])
        return payload

    def _write_payload(self, payload: dict[str, Any]) -> None:
        path = self.config_path
        try:
            write_json_dict(path, payload, label="task environment config", sort_keys=True)
        except JsonFileStoreError as exc:
            raise TaskEnvironmentConfigError(str(exc)) from exc


def load_configured_task_environments(
    backend_dir: Path | str,
) -> tuple[tuple[TaskEnvironmentGroup, ...], tuple[TaskEnvironmentDefinition, ...]]:
    return TaskEnvironmentRepository(backend_dir).load()


def _definition_from_payload(payload: Any) -> TaskEnvironmentDefinition:
    if not isinstance(payload, dict):
        raise TaskEnvironmentConfigError("environment item must be an object")
    record_payload = dict(payload.get("record") or {})
    spec_payload = dict(payload.get("spec") or {})
    _reject_unknown_flat_environment_keys(payload, has_nested_payload=bool(record_payload or spec_payload))
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
    record = _dataclass_from_payload(TaskEnvironmentRecord, record_payload, path="environment.record")
    spec_payload.setdefault("environment_id", record.environment_id)
    spec_payload.setdefault("spec_id", f"envspec.{record.environment_id}.configured")
    spec = TaskEnvironmentSpec(
        spec_id=str(spec_payload.get("spec_id") or ""),
        environment_id=str(spec_payload.get("environment_id") or ""),
        environment_prompts=tuple(
            _dataclass_from_payload(
                EnvironmentPrompt,
                _normalize_environment_prompt_payload(item),
                path="environment.spec.environment_prompts",
            )
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
    return _dataclass_from_payload(TaskEnvironmentGroup, payload, path="environment.group")


def _normalize_environment_config_prompt_refs(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["environments"] = [
        _normalize_environment_payload_prompt_refs(item) if isinstance(item, dict) else item
        for item in _list_payload(payload.get("environments"), path="$.environments")
    ]
    return normalized


def _normalize_environment_payload_prompt_refs(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if isinstance(normalized.get("spec"), dict):
        spec = dict(normalized.get("spec") or {})
        if "environment_prompts" in spec:
            spec["environment_prompts"] = [
                _normalize_environment_prompt_payload(item)
                for item in _list_payload(spec.get("environment_prompts"), path="environment.spec.environment_prompts")
            ]
        normalized["spec"] = spec
        return normalized
    if "environment_prompts" in normalized:
        normalized["environment_prompts"] = [
            _normalize_environment_prompt_payload(item)
            for item in _list_payload(normalized.get("environment_prompts"), path="environment.environment_prompts")
        ]
    return normalized


def _normalize_environment_prompt_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    if "prompt_id" in normalized:
        normalized["prompt_id"] = migrate_prompt_ref(normalized.get("prompt_id"))
    return normalized


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


def _environment_id_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
    return str(
        dict(record).get("environment_id")
        or dict(spec).get("environment_id")
        or payload.get("environment_id")
        or ""
    ).strip()


def _is_default_group_id(group_id: str) -> bool:
    return str(group_id or "").strip() in {
        "environment_group.coding",
        "environment_group.office",
        "environment_group.general",
    }


def _reject_unknown_flat_environment_keys(payload: dict[str, Any], *, has_nested_payload: bool) -> None:
    if has_nested_payload:
        allowed = {"record", "spec"}
    else:
        allowed = {
            "environment_id",
            "title",
            "description",
            "group_id",
            "enabled",
            "owner",
            "environment_kind",
            "default_visibility",
            "metadata",
            "spec_id",
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
        }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise TaskEnvironmentConfigError(f"environment has unknown keys: {', '.join(unknown)}")


def _list_payload(value: Any, *, path: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskEnvironmentConfigError(f"{path} must be a list")
    return list(value)

