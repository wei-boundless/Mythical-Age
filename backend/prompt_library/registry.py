from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from prompt_ref_migrations import migrate_prompt_pack_payload, migrate_prompt_resource_payload

from .agent_prompts import list_builtin_agent_prompt_resources
from .general_lifecycle_prompts import list_builtin_general_lifecycle_prompt_resources
from .models import PromptPack, PromptResource, prompt_pack_from_dict, prompt_resource_from_dict
from .packs import list_builtin_prompt_packs, list_builtin_runtime_prompt_resources
from .personality_prompts import list_builtin_personality_prompt_resources
from .rules import list_builtin_prompt_rule_resources
from .rules import prompt_rule_from_resource
from .system_prompts import list_builtin_system_prompt_resources
from .tool_prompts import list_builtin_tool_prompt_resources
from .worker_prompts import list_builtin_worker_prompt_resources


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).storage_root / "prompt_library"


def _resources_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "prompt_resources.json"


def _packs_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "prompt_packs.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _stable_resource_id(*, workflow_id: str = "", task_id: str = "", node_id: str = "", resource_type: str = "graph_node.role") -> str:
    base = workflow_id or task_id or node_id
    normalized = ".".join(part for part in str(base or "runtime").replace(":", ".").split(".") if part)
    if normalized.startswith("workflow."):
        normalized = normalized.removeprefix("workflow.")
    return f"prompt.task_graph.{normalized}.{resource_type}"


def _node_id_from_workflow(workflow_id: str) -> str:
    value = str(workflow_id or "").strip()
    marker = ".node."
    if marker in value:
        return value.split(marker, 1)[1]
    return ""


def _task_id_from_workflow(workflow_id: str) -> str:
    value = str(workflow_id or "").strip()
    if value.startswith("workflow."):
        return "task." + value.removeprefix("workflow.")
    return ""


class PromptLibraryRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def list_resources(self) -> list[PromptResource]:
        builtin_resources = {
            item.resource_id: item
            for item in (
                *list_builtin_system_prompt_resources(),
                *list_builtin_runtime_prompt_resources(),
                *list_builtin_prompt_rule_resources(),
                *list_builtin_tool_prompt_resources(),
                *list_builtin_agent_prompt_resources(),
                *list_builtin_personality_prompt_resources(),
                *list_builtin_worker_prompt_resources(),
                *list_builtin_general_lifecycle_prompt_resources(),
                *list_builtin_environment_prompt_resources(),
                *list_environment_prompt_resources_from_backend_dir(self.base_dir),
            )
        }
        stored_resources = {item.resource_id: item for item in self._list_stored_resources(normalize=True)}
        merged = {**builtin_resources, **stored_resources}
        return sorted(merged.values(), key=lambda item: (item.resource_type, item.workflow_id, item.task_id, item.resource_id))

    def list_active_resources(
        self,
        *,
        category: str = "",
        subtype: str = "",
    ) -> list[PromptResource]:
        category_filter = str(category or "").strip()
        subtype_filter = str(subtype or "").strip()
        return [
            item
            for item in self.list_resources()
            if item.active
            and not item.deprecated_for_new_runtime
            and (not category_filter or item.category == category_filter)
            and (not subtype_filter or item.subtype == subtype_filter)
        ]

    def list_prompt_rules(self) -> list:
        rules = [prompt_rule_from_resource(resource) for resource in self.list_resources()]
        return sorted(
            [rule for rule in rules if rule is not None and rule.status == "active"],
            key=lambda item: (item.rule_kind, item.rule_id),
        )

    def upsert_resource(self, resource: PromptResource) -> PromptResource:
        normalized_resource = prompt_resource_from_dict(migrate_prompt_resource_payload(resource.to_dict()))
        target = str(normalized_resource.resource_id or "").strip()
        if not target:
            raise ValueError("PromptResource requires resource_id")
        resources = [item for item in self._list_stored_resources(normalize=True) if item.resource_id != target]
        resources.append(normalized_resource)
        resources.sort(key=lambda item: (item.resource_type, item.workflow_id, item.task_id, item.resource_id))
        _write_json(_resources_path(self.base_dir), {"resources": [item.to_dict() for item in resources]})
        return normalized_resource

    def upsert_resources(self, resources: list[PromptResource] | tuple[PromptResource, ...]) -> tuple[PromptResource, ...]:
        existing = {item.resource_id: item for item in self._list_stored_resources(normalize=True)}
        for resource in resources:
            normalized_resource = prompt_resource_from_dict(migrate_prompt_resource_payload(resource.to_dict()))
            if not str(normalized_resource.resource_id or "").strip():
                continue
            existing[normalized_resource.resource_id] = normalized_resource
        ordered = sorted(existing.values(), key=lambda item: (item.resource_type, item.workflow_id, item.task_id, item.resource_id))
        _write_json(_resources_path(self.base_dir), {"resources": [item.to_dict() for item in ordered]})
        return tuple(ordered)

    def get_resource(self, resource_id: str) -> PromptResource | None:
        target = str(resource_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list_resources() if item.resource_id == target and item.enabled), None)

    def get_active_resource(self, prompt_id: str) -> PromptResource | None:
        target = str(prompt_id or "").strip()
        if not target:
            return None
        return next(
            (
                item
                for item in self.list_resources()
                if item.prompt_id == target and item.active and not item.deprecated_for_new_runtime
            ),
            None,
        )

    def list_packs(self) -> list[PromptPack]:
        default_packs = {item.pack_id: item for item in list_builtin_prompt_packs()}
        stored_packs = {item.pack_id: item for item in self._list_stored_packs(normalize=True)}
        merged = {**default_packs, **stored_packs}
        return sorted(merged.values(), key=lambda item: (item.invocation_kind, item.pack_id))

    def get_pack(self, pack_id: str) -> PromptPack | None:
        target = str(pack_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list_packs() if item.pack_id == target), None)

    def upsert_pack(self, pack: PromptPack) -> PromptPack:
        normalized_pack = prompt_pack_from_dict(migrate_prompt_pack_payload(pack.to_dict()))
        packs = [item for item in self._list_stored_packs(normalize=True) if item.pack_id != normalized_pack.pack_id]
        packs.append(normalized_pack)
        packs.sort(key=lambda item: (item.invocation_kind, item.pack_id))
        _write_json(_packs_path(self.base_dir), {"packs": [item.to_dict() for item in packs]})
        return normalized_pack

    def _list_stored_resources(self, *, normalize: bool) -> list[PromptResource]:
        payload = _read_json(_resources_path(self.base_dir), {"resources": []})
        resources_by_id: dict[str, PromptResource] = {}
        for item in list(payload.get("resources") or []):
            if not isinstance(item, dict):
                continue
            resource = prompt_resource_from_dict(migrate_prompt_resource_payload(item))
            resources_by_id[resource.resource_id] = resource
        resources = sorted(
            resources_by_id.values(),
            key=lambda item: (item.resource_type, item.workflow_id, item.task_id, item.resource_id),
        )
        if normalize:
            normalized = [item.to_dict() for item in resources]
            if payload.get("resources") != normalized:
                _write_json(_resources_path(self.base_dir), {"resources": normalized})
        return resources

    def _list_stored_packs(self, *, normalize: bool) -> list[PromptPack]:
        payload = _read_json(_packs_path(self.base_dir), {"packs": []})
        packs_by_id: dict[str, PromptPack] = {}
        for item in list(payload.get("packs") or []):
            if not isinstance(item, dict):
                continue
            pack = prompt_pack_from_dict(migrate_prompt_pack_payload(item))
            packs_by_id[pack.pack_id] = pack
        packs = sorted(packs_by_id.values(), key=lambda item: (item.invocation_kind, item.pack_id))
        if normalize:
            normalized = [item.to_dict() for item in packs]
            if payload.get("packs") != normalized:
                _write_json(_packs_path(self.base_dir), {"packs": normalized})
        return packs

    def upsert_task_graph_node_role_prompt(
        self,
        *,
        graph_id: str,
        graph_title: str,
        domain_id: str,
        node: dict[str, Any],
        prompt: str,
    ) -> PromptResource:
        node_id = str(node.get("node_id") or node.get("id") or "").strip()
        task_id = str(node.get("task_id") or "").strip()
        workflow_id = str(node.get("workflow_id") or "").strip()
        resource = PromptResource(
            resource_id=_stable_resource_id(
                workflow_id=workflow_id,
                task_id=task_id,
                node_id=f"{graph_id}.{node_id}",
                resource_type="graph_node.role",
            ),
            category="graph_node",
            subtype="role",
            resource_type="graph_node.role",
            title=str(node.get("title") or node_id or graph_title or graph_id),
            content=str(prompt or "").strip(),
            workflow_id=workflow_id,
            task_id=task_id,
            graph_id=str(graph_id or "").strip(),
            node_id=node_id,
            stage_id=node_id,
            tags=tuple(item for item in ("task_graph", domain_id, graph_id) if item),
            cache_scope="static",
            model_visible=True,
            source_ref=f"task_graph:{graph_id}#nodes.{node_id}.role_prompt",
            version="2026-06-08",
            enabled=True,
            metadata={
                "managed_by": "prompt_library.task_graph_role_prompt",
                "graph_id": str(graph_id or "").strip(),
                "graph_title": str(graph_title or "").strip(),
                "domain_id": str(domain_id or "").strip(),
            },
        )
        return self.upsert_resource(resource)


def list_builtin_environment_prompt_resources() -> tuple[PromptResource, ...]:
    from task_system.environments.prompt_resources import default_environment_prompt_resource_specs

    resources: list[PromptResource] = []
    for spec in default_environment_prompt_resource_specs():
        environment_id = str(spec.environment_id or "").strip()
        allowed_environment_refs = (environment_id,) if environment_id.startswith("env.") else ()
        resources.append(
            PromptResource(
                prompt_id=spec.prompt_id,
                resource_id=spec.prompt_id,
                category="environment",
                subtype=spec.subtype,
                resource_type="environment_prompt",
                title=spec.title,
                content=spec.content,
                owner_layer="environment",
                cache_scope=spec.cache_scope,
                model_visible=True,
                allowed_environment_refs=allowed_environment_refs,
                source_ref=f"task_system.environments.prompt_resources#{spec.prompt_id}",
                version=spec.version,
                enabled=True,
                status="active",
                metadata={
                    "managed_by": "prompt_library.default_environment_prompt_resources",
                    "source_type": "environment_resource_prompt"
                    if environment_id.startswith("resource.")
                    else "environment_orientation_prompt",
                    "environment_id": environment_id if environment_id.startswith("env.") else "",
                    "resource_ref": environment_id if environment_id.startswith("resource.") else "",
                },
            )
        )
    return tuple(resources)


def list_environment_prompt_resources_from_backend_dir(base_dir: Path) -> tuple[PromptResource, ...]:
    from task_system.environments import task_environment_registry_from_backend_dir

    return _environment_prompt_resources_from_definitions(
        task_environment_registry_from_backend_dir(base_dir).list(),
        source_prefix="task_environment",
    )


def _environment_prompt_resources_from_definitions(definitions: tuple[Any, ...], *, source_prefix: str) -> tuple[PromptResource, ...]:
    resources: list[PromptResource] = []
    for definition in definitions:
        environment_id = str(definition.record.environment_id or "")
        for prompt in definition.spec.environment_prompts:
            prompt_id = str(prompt.prompt_id or "").strip()
            content = str(prompt.content or "").strip()
            if not prompt_id or not content:
                continue
            resources.append(
                PromptResource(
                    prompt_id=prompt_id,
                    resource_id=prompt_id,
                    category="environment",
                    subtype=str(prompt.prompt_kind or "boundary"),
                    resource_type="environment_prompt",
                    title=f"环境提示：{environment_id}",
                    content=content,
                    owner_layer="environment",
                    cache_scope=str(prompt.cache_scope or "static_environment"),
                    model_visible=True,
                    allowed_environment_refs=(environment_id,),
                    source_ref=f"{source_prefix}#{environment_id}.environment_prompts.{prompt_id}",
                    version=str(prompt.version or "2026-06-08"),
                    enabled=True,
                    status="active",
                    metadata={
                        "managed_by": "prompt_library.task_environment_sync",
                        "source_type": "environment_prompt",
                        "environment_id": environment_id,
                    },
                )
            )
    return tuple(resources)


