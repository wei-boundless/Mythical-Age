from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .default_resources import list_default_prompt_resources
from .models import PromptResource, prompt_resource_from_dict


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).storage_root / "prompt_library"


def _resources_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "prompt_resources.json"


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


def _stable_resource_id(*, workflow_id: str = "", task_id: str = "", node_id: str = "", resource_type: str = "stage_role") -> str:
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

    def list_resources(self, *, sync_workflow_prompts: bool = True) -> list[PromptResource]:
        if sync_workflow_prompts:
            self.sync_task_workflow_prompts()
        default_resources = {item.resource_id: item for item in list_default_prompt_resources()}
        stored_resources = {item.resource_id: item for item in self._list_stored_resources(normalize=True)}
        merged = {**default_resources, **stored_resources}
        return sorted(merged.values(), key=lambda item: (item.resource_type, item.workflow_id, item.task_id, item.resource_id))

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

    def resolve_stage_role(
        self,
        *,
        workflow_id: str = "",
        task_id: str = "",
        node_id: str = "",
    ) -> PromptResource | None:
        workflow = str(workflow_id or "").strip()
        task = str(task_id or "").strip()
        node = str(node_id or "").strip()
        candidates = [
            item
            for item in self.list_resources()
            if item.enabled and item.model_visible and item.resource_type == "stage_role"
        ]
        for item in candidates:
            if workflow and item.workflow_id == workflow:
                return item
        for item in candidates:
            if task and item.task_id == task:
                return item
        for item in candidates:
            if node and item.node_id == node:
                return item
        return None

    def sync_task_workflow_prompts(self) -> tuple[PromptResource, ...]:
        from task_system.registry.workflow_registry import TaskWorkflowRegistry

        resources: list[PromptResource] = []
        for workflow in TaskWorkflowRegistry(self.base_dir).list_workflows():
            prompt = str(workflow.prompt or "").strip()
            if not prompt:
                continue
            metadata = dict(workflow.metadata or {})
            workflow_id = str(workflow.workflow_id or "").strip()
            task_id = str(metadata.get("task_id") or _task_id_from_workflow(workflow_id)).strip()
            node_id = str(metadata.get("node_id") or _node_id_from_workflow(workflow_id)).strip()
            domain_id = str(metadata.get("domain_id") or "").strip()
            resources.append(
                PromptResource(
                    resource_id=_stable_resource_id(
                        workflow_id=workflow_id,
                        task_id=task_id,
                        node_id=node_id,
                        resource_type="stage_role",
                    ),
                    resource_type="stage_role",
                    title=str(workflow.title or node_id or workflow_id),
                    content=prompt,
                    workflow_id=workflow_id,
                    task_id=task_id,
                    node_id=node_id,
                    stage_id=node_id,
                    tags=tuple(item for item in ("task_graph", domain_id) if item),
                    applies_to_task_goal_types=("task_graph_node_execution",),
                    applies_to_domains=tuple(item for item in ("task_graph", domain_id) if item),
                    applies_to_modes=("role_mode", "standard_mode", "professional_mode"),
                    cache_scope="static",
                    model_visible=True,
                    source_ref=f"storage/tasks/task_workflows.json#{workflow_id}.prompt",
                    version="v1",
                    enabled=bool(workflow.enabled),
                    metadata={
                        "managed_by": "prompt_library.task_workflow_sync",
                        "source_type": "task_workflow_prompt",
                        "domain_id": domain_id,
                        "output_contract_id": str(workflow.output_contract_id or ""),
                    },
                )
            )
        if resources:
            self.upsert_resources(resources)
        elif not _resources_path(self.base_dir).exists():
            _write_json(_resources_path(self.base_dir), {"resources": []})
        return tuple(resources)

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
                resource_type="stage_role",
            ),
            resource_type="stage_role",
            title=str(node.get("title") or node_id or graph_title or graph_id),
            content=str(prompt or "").strip(),
            workflow_id=workflow_id,
            task_id=task_id,
            graph_id=str(graph_id or "").strip(),
            node_id=node_id,
            stage_id=node_id,
            tags=tuple(item for item in ("task_graph", domain_id, graph_id) if item),
            applies_to_task_goal_types=("task_graph_node_execution",),
            applies_to_domains=tuple(item for item in ("task_graph", domain_id) if item),
            applies_to_modes=("role_mode", "standard_mode", "professional_mode"),
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


