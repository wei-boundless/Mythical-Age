from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .models import PromptPack, PromptResource, prompt_pack_from_dict, prompt_resource_from_dict
from .packs import list_builtin_prompt_packs, list_builtin_runtime_prompt_resources


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
                *list_builtin_runtime_prompt_resources(),
                *list_builtin_agent_prompt_resources(),
                *list_agent_prompt_resources_from_backend_dir(self.base_dir),
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

    def upsert_resource(self, resource: PromptResource) -> PromptResource:
        target = str(resource.resource_id or "").strip()
        if not target:
            raise ValueError("PromptResource requires resource_id")
        resources = [item for item in self._list_stored_resources(normalize=True) if item.resource_id != target]
        resources.append(resource)
        resources.sort(key=lambda item: (item.resource_type, item.workflow_id, item.task_id, item.resource_id))
        _write_json(_resources_path(self.base_dir), {"resources": [item.to_dict() for item in resources]})
        return resource

    def upsert_resources(self, resources: list[PromptResource] | tuple[PromptResource, ...]) -> tuple[PromptResource, ...]:
        existing = {item.resource_id: item for item in self._list_stored_resources(normalize=True)}
        for resource in resources:
            if not str(resource.resource_id or "").strip():
                continue
            existing[resource.resource_id] = resource
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
        packs = [item for item in self._list_stored_packs(normalize=True) if item.pack_id != pack.pack_id]
        packs.append(pack)
        packs.sort(key=lambda item: (item.invocation_kind, item.pack_id))
        _write_json(_packs_path(self.base_dir), {"packs": [item.to_dict() for item in packs]})
        return pack

    def _list_stored_resources(self, *, normalize: bool) -> list[PromptResource]:
        payload = _read_json(_resources_path(self.base_dir), {"resources": []})
        resources = [
            prompt_resource_from_dict(item)
            for item in list(payload.get("resources") or [])
            if isinstance(item, dict)
        ]
        if normalize:
            normalized = [item.to_dict() for item in resources]
            if payload.get("resources") != normalized:
                _write_json(_resources_path(self.base_dir), {"resources": normalized})
        return resources

    def _list_stored_packs(self, *, normalize: bool) -> list[PromptPack]:
        payload = _read_json(_packs_path(self.base_dir), {"packs": []})
        packs = [
            prompt_pack_from_dict(item)
            for item in list(payload.get("packs") or [])
            if isinstance(item, dict)
        ]
        if normalize:
            normalized = [item.to_dict() for item in packs]
            if payload.get("packs") != normalized:
                _write_json(_packs_path(self.base_dir), {"packs": normalized})
        return packs

    def migrate_task_graph_node_prompt(
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
            source_ref=f"task_graph:{graph_id}#nodes.{node_id}.metadata.role_prompt",
            version="v1",
            enabled=True,
            metadata={
                "managed_by": "prompt_library.task_graph_api_migration",
                "graph_id": str(graph_id or "").strip(),
                "graph_title": str(graph_title or "").strip(),
                "domain_id": str(domain_id or "").strip(),
            },
        )
        return self.upsert_resource(resource)


def list_builtin_agent_prompt_resources() -> tuple[PromptResource, ...]:
    from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles

    return _agent_prompt_resources_from_profiles(default_agent_runtime_profiles(), source_prefix="agent_runtime_profiles.default")


def list_agent_prompt_resources_from_backend_dir(base_dir: Path) -> tuple[PromptResource, ...]:
    from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry

    return _agent_prompt_resources_from_profiles(
        tuple(AgentRuntimeRegistry(base_dir).list_profiles()),
        source_prefix="agent_runtime_profiles",
    )


def _agent_prompt_resources_from_profiles(profiles: tuple[Any, ...], *, source_prefix: str) -> tuple[PromptResource, ...]:
    resources: list[PromptResource] = []
    for profile in profiles:
        metadata = dict(profile.metadata or {})
        for invocation_kind, content in _work_role_prompt_by_invocation(metadata).items():
            prompt_id = _agent_work_role_prompt_id(str(profile.agent_profile_id or ""), invocation_kind=invocation_kind)
            resources.append(
                PromptResource(
                    prompt_id=prompt_id,
                    resource_id=prompt_id,
                    category="agent",
                    subtype=f"{invocation_kind}.work_role",
                    resource_type="work_role",
                    title=f"{profile.agent_profile_id} {invocation_kind} work role",
                    content=content,
                    owner_layer="agent",
                    cache_scope="static",
                    model_visible=True,
                    allowed_invocation_kinds=(invocation_kind,),
                    allowed_agent_refs=(str(profile.agent_profile_id or ""),),
                    source_ref=f"{source_prefix}#{profile.agent_profile_id}.metadata.work_role_prompt_by_invocation.{invocation_kind}",
                    version="v1",
                    enabled=True,
                    status="active",
                    metadata={
                        "managed_by": "prompt_library.agent_profile_sync",
                        "source_type": "agent_work_role_prompt_by_invocation",
                        "invocation_kind": invocation_kind,
                    },
                )
            )
        content = str(
            metadata.get("work_role_prompt")
            or metadata.get("agent_work_role_prompt")
            or ""
        ).strip()
        if not content:
            continue
        prompt_id = _agent_work_role_prompt_id(str(profile.agent_profile_id or ""))
        resources.append(
            PromptResource(
                prompt_id=prompt_id,
                resource_id=prompt_id,
                category="agent",
                subtype="main.work_role",
                resource_type="work_role",
                title=f"{profile.agent_profile_id} work role",
                content=content,
                owner_layer="agent",
                cache_scope="static",
                model_visible=True,
                allowed_agent_refs=(str(profile.agent_profile_id or ""),),
                source_ref=f"{source_prefix}#{profile.agent_profile_id}.metadata.work_role_prompt",
                version="v1",
                enabled=True,
                status="active",
                metadata={"managed_by": "prompt_library.agent_profile_sync", "source_type": "agent_work_role_prompt"},
            )
        )
    return tuple(resources)


def list_builtin_environment_prompt_resources() -> tuple[PromptResource, ...]:
    from task_system.environments.default_environments import default_task_environments

    return _environment_prompt_resources_from_definitions(default_task_environments(), source_prefix="task_environment.default")


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
                    title=f"{environment_id} environment boundary",
                    content=content,
                    owner_layer="environment",
                    cache_scope=str(prompt.cache_scope or "static_environment"),
                    model_visible=True,
                    allowed_environment_refs=(environment_id,),
                    source_ref=f"{source_prefix}#{environment_id}.environment_prompts.{prompt_id}",
                    version=str(prompt.version or "v1"),
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


def _agent_work_role_prompt_id(agent_profile_id: str, *, invocation_kind: str = "") -> str:
    normalized = ".".join(part for part in str(agent_profile_id or "agent").replace(":", ".").split(".") if part)
    invocation = ".".join(part for part in str(invocation_kind or "").replace(":", ".").split(".") if part)
    return f"agent.{normalized}.{invocation}.work_role.v1" if invocation else f"agent.{normalized}.work_role.v1"


def _work_role_prompt_by_invocation(metadata: dict[str, Any]) -> dict[str, str]:
    raw = (
        metadata.get("work_role_prompt_by_invocation")
        or metadata.get("agent_work_role_prompt_by_invocation")
        or {}
    )
    return {
        str(key).strip(): str(value or "").strip()
        for key, value in dict(raw or {}).items()
        if str(key).strip() and str(value or "").strip()
    }


