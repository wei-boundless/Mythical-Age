from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import TaskEnvironmentDefinition
from .registry import TaskEnvironmentRegistry, default_task_environment_registry
from .spec_resolver import ResolvedTaskEnvironment, resolve_task_environment


@dataclass(frozen=True, slots=True)
class TaskEnvironmentCatalogItem:
    definition: TaskEnvironmentDefinition
    resolved: ResolvedTaskEnvironment
    task_library: dict[str, Any]
    definition_source: str = "unknown"
    authority: str = "task_system.task_environment_catalog_item"

    def runtime_payload(self) -> dict[str, Any]:
        resolved_payload = self.resolved.to_dict()
        return {
            "environment_id": self.resolved.spec.environment_id,
            "title": self.definition.record.title,
            "description": self.definition.record.description,
            "environment_kind": self.definition.record.environment_kind,
            "group": resolved_payload.get("group") or {},
            "environment_prompts": resolved_payload.get("environment_prompts") or [],
            "environment_boundary": resolved_payload.get("environment_boundary") or {},
            "sandbox_policy": resolved_payload.get("sandbox_policy") or {},
            "storage_space": resolved_payload.get("storage_space") or {},
            "resource_space": self.resolved.spec.resource_space.to_dict(),
            "file_management": self.resolved.spec.file_management.to_dict(),
            "file_access_tables": resolved_payload.get("file_access_tables") or [],
            "memory_space": self.resolved.spec.memory_space.to_dict(),
            "artifact_policy": self.resolved.spec.artifact_policy.to_dict(),
            "execution_policy": self.resolved.spec.execution_policy.to_dict(),
            "risk_policy": self.resolved.spec.risk_policy.to_dict(),
            "observability_policy": dict(self.resolved.spec.observability_policy),
            "lifecycle_policy": dict(self.resolved.spec.lifecycle_policy),
            "authority": self.resolved.authority,
        }

    def management_payload(self) -> dict[str, Any]:
        runtime_payload = self.runtime_payload()
        management_scope = _environment_management_scope(
            definition=self.definition,
            definition_source=self.definition_source,
        )
        return {
            **self.definition.to_dict(),
            "definition_source": self.definition_source,
            "management_scope": management_scope,
            "group": runtime_payload["group"],
            "environment_prompts": runtime_payload["environment_prompts"],
            "environment_boundary": runtime_payload["environment_boundary"],
            "sandbox_policy": runtime_payload["sandbox_policy"],
            "storage_space": runtime_payload["storage_space"],
            "resource_space": runtime_payload["resource_space"],
            "file_management": runtime_payload["file_management"],
            "file_access_tables": runtime_payload["file_access_tables"],
            "memory_space": runtime_payload["memory_space"],
            "artifact_policy": runtime_payload["artifact_policy"],
            "execution_policy": runtime_payload["execution_policy"],
            "risk_policy": runtime_payload["risk_policy"],
            "observability_policy": runtime_payload["observability_policy"],
            "lifecycle_policy": runtime_payload["lifecycle_policy"],
            "task_library": dict(self.task_library),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class TaskEnvironmentCatalog:
    groups: tuple[dict[str, Any], ...]
    items: tuple[TaskEnvironmentCatalogItem, ...]
    summary: dict[str, Any]
    authority: str = "task_system.task_environment_catalog"

    def runtime_environment_payload(self, environment_id: str) -> dict[str, Any]:
        resolved_id = str(environment_id or "").strip()
        for item in self.items:
            if item.resolved.spec.environment_id == resolved_id:
                return item.runtime_payload()
        raise KeyError(f"unknown task environment: {environment_id}")

    def management_payload(self) -> dict[str, Any]:
        environments = [item.management_payload() for item in self.items]
        records = []
        for item in environments:
            record = dict(item["record"])
            record["definition_source"] = item["definition_source"]
            record["management_scope"] = item["management_scope"]
            records.append(record)
        return {
            "authority": self.authority,
            "groups": [dict(item) for item in self.groups],
            "environments": environments,
            "records": records,
            "summary": dict(self.summary),
        }


def build_task_environment_catalog(
    *,
    registry: TaskEnvironmentRegistry | None = None,
    engagement_plans: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
) -> TaskEnvironmentCatalog:
    active_registry = registry or default_task_environment_registry()
    plans = [dict(item) for item in list(engagement_plans or [])]
    items: list[TaskEnvironmentCatalogItem] = []
    for definition in active_registry.list():
        environment_id = str(definition.record.environment_id or "")
        resolved = resolve_task_environment(environment_id, registry=active_registry)
        storage_space = dict(resolved.to_dict().get("storage_space") or {})
        plan_ids = [
            str(item.get("plan_id") or "")
            for item in plans
            if _engagement_plan_environment_id(item, registry=active_registry) == environment_id
        ]
        items.append(
            TaskEnvironmentCatalogItem(
                definition=definition,
                resolved=resolved,
                task_library={
                    "environment_id": environment_id,
                    "engagement_plan_ids": plan_ids,
                    "task_ids": plan_ids,
                    "task_count": len(plan_ids),
                    "task_library_root": str(storage_space.get("task_library_root") or ""),
                    "authority": "task_system.environment_task_library",
                },
                definition_source=active_registry.definition_source(environment_id),
            )
        )
    scope_by_environment_id = {
        item.definition.record.environment_id: _environment_management_scope(
            definition=item.definition,
            definition_source=item.definition_source,
        )
        for item in items
    }
    summary = {
        "environment_count": len(items),
        "environment_group_count": len(active_registry.list_groups()),
        "enabled_environment_count": sum(1 for item in items if item.definition.record.enabled is True),
        "builtin_template_count": sum(1 for item in scope_by_environment_id.values() if item == "builtin_template"),
        "workspace_environment_count": sum(1 for item in scope_by_environment_id.values() if item == "workspace"),
        "system_internal_environment_count": sum(1 for item in scope_by_environment_id.values() if item == "system_internal"),
        "task_library_count": sum(int(item.task_library.get("task_count") or 0) for item in items),
    }
    return TaskEnvironmentCatalog(
        groups=tuple(item.to_dict() for item in active_registry.list_groups()),
        items=tuple(items),
        summary=summary,
    )


def _engagement_plan_environment_id(plan: dict[str, object], *, registry: TaskEnvironmentRegistry) -> str:
    raw = str(plan.get("task_environment_id") or "").strip()
    if not raw:
        return ""
    registry.require(raw)
    return raw


def _environment_management_scope(*, definition: TaskEnvironmentDefinition, definition_source: str) -> str:
    if definition_source == "builtin_default":
        return "builtin_template"
    record = definition.record
    metadata = dict(record.metadata or {})
    managed_by = str(metadata.get("managed_by") or "").strip()
    if (
        record.owner == "system"
        or record.default_visibility == "system"
        or managed_by.startswith("codex_system")
    ):
        return "system_internal"
    return "workspace"
