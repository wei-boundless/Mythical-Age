from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .models import safe_id


class GraphTaskLifecycleManager:
    """Deletes one graph task instance and its run-scoped stores."""

    authority = "harness.graph_task_lifecycle"

    def __init__(self, *, base_dir: str | Path, graph_harness: Any) -> None:
        self.base_dir = Path(base_dir)
        self.graph_harness = graph_harness
        self.services = graph_harness._services
        self.storage_root = ProjectLayout.from_backend_dir(self.base_dir).storage_root

    def preview_delete_graph_run(self, graph_run_id: str) -> dict[str, Any]:
        scope = self._resolve_scope(graph_run_id)
        return {
            "authority": self.authority,
            "mode": "preview",
            **scope,
            "artifact_paths": [str(path) for path in self._artifact_paths(scope)],
        }

    def delete_graph_run(self, graph_run_id: str) -> dict[str, Any]:
        scope = self._resolve_scope(graph_run_id)
        if not scope["graph_run_id"]:
            raise ValueError("graph_run_id required")
        if not scope["root_task_run_id"]:
            raise ValueError("graph run root task_run_id not found")
        task_run_ids = set(scope["task_run_ids"])
        scope_ids = {scope["memory_namespace_id"], scope["project_id"]} - {""}
        effects: dict[str, Any] = {}
        formal_memory = getattr(self.services, "formal_memory_service", None)
        if formal_memory is not None and hasattr(formal_memory, "store"):
            effects["formal_memory"] = formal_memory.store.delete_scope(task_run_ids=task_run_ids, scope_ids=scope_ids)
        artifact_repository = getattr(self.services, "artifact_repository_service", None)
        if artifact_repository is not None and hasattr(artifact_repository, "store"):
            effects["artifact_repository"] = artifact_repository.store.delete_scope(
                task_run_ids=task_run_ids,
                graph_run_ids={scope["graph_run_id"]},
                scope_ids=scope_ids,
            )
        effects["artifact_paths"] = self._delete_artifact_paths(scope)
        checkpoint_store = getattr(self.services, "graph_checkpoint_store", None)
        if checkpoint_store is not None and hasattr(checkpoint_store, "delete_graph_run"):
            effects["checkpoints"] = checkpoint_store.delete_graph_run(scope["graph_run_id"])
        effects["runtime_events"] = self._delete_events(task_run_ids)
        effects["runtime_objects"] = self.services.runtime_objects.delete_graph_run_objects(
            graph_run_id=scope["graph_run_id"],
            task_run_ids=task_run_ids,
        )
        effects["state_index"] = self.services.state_index.prune_task_runs(task_run_ids)
        return {
            "authority": self.authority,
            "mode": "delete",
            **scope,
            "effects": effects,
        }

    def _resolve_scope(self, graph_run_id: str) -> dict[str, Any]:
        target = str(graph_run_id or "").strip()
        graph_run = dict(self.graph_harness.get_graph_run(target) or {})
        state = self.graph_harness.get_checkpoint_state(target)
        root_task_run_id = str(
            graph_run.get("task_run_id")
            or state.get("task_run_id")
            or ""
        )
        root_task = self.services.state_index.get_task_run(root_task_run_id) if root_task_run_id else None
        root_payload = root_task.to_dict() if hasattr(root_task, "to_dict") else {}
        diagnostics = dict(root_payload.get("diagnostics") or graph_run.get("diagnostics") or {})
        runtime_scope = dict(diagnostics.get("runtime_scope") or {})
        project_id = str(runtime_scope.get("project_id") or diagnostics.get("project_id") or f"graphrun.{safe_id(target)}").strip()
        memory_namespace = dict(runtime_scope.get("graph_task_memory_namespace") or {})
        memory_namespace_id = str(
            runtime_scope.get("memory_namespace_id")
            or memory_namespace.get("namespace_id")
            or f"graphmem:{safe_id(target)}"
        ).strip()
        task_run_ids = self._collect_task_run_ids(graph_run_id=target, root_task_run_id=root_task_run_id, state=state)
        return {
            "graph_run_id": target,
            "root_task_run_id": root_task_run_id,
            "task_run_ids": sorted(task_run_ids),
            "project_id": project_id,
            "memory_namespace_id": memory_namespace_id,
            "task_environment_id": str(runtime_scope.get("task_environment_id") or diagnostics.get("task_environment_id") or "env.creation.writing"),
            "graph_id": str(graph_run.get("graph_id") or diagnostics.get("graph_id") or ""),
            "config_id": str(graph_run.get("config_id") or diagnostics.get("graph_harness_config_id") or ""),
        }

    def _collect_task_run_ids(self, *, graph_run_id: str, root_task_run_id: str, state: dict[str, Any]) -> set[str]:
        task_ids = {root_task_run_id} if root_task_run_id else set()
        for task_run in self.services.state_index.list_task_runs():
            payload = task_run.to_dict() if hasattr(task_run, "to_dict") else {}
            diagnostics = dict(payload.get("diagnostics") or {})
            if str(diagnostics.get("graph_run_id") or "") == graph_run_id:
                task_ids.add(str(payload.get("task_run_id") or ""))
        for payload in dict(state.get("node_states") or {}).values():
            result_ref = str(dict(payload or {}).get("result_ref") or "")
            if not result_ref:
                continue
            result = self.services.runtime_objects.get_object(result_ref)
            outputs = dict(result.get("outputs") or {})
            task_ids.add(str(outputs.get("node_executor_task_run_id") or ""))
        return {item for item in task_ids if item}

    def _artifact_paths(self, scope: dict[str, Any]) -> list[Path]:
        project_id = str(scope.get("project_id") or "").strip()
        if not project_id:
            return []
        return [self.storage_root / "task_environments" / "creation" / "writing" / "artifacts" / project_id]

    def _delete_artifact_paths(self, scope: dict[str, Any]) -> list[dict[str, Any]]:
        deleted: list[dict[str, Any]] = []
        root = (self.storage_root / "task_environments").resolve()
        for path in self._artifact_paths(scope):
            resolved = path.resolve()
            if not str(resolved).startswith(str(root)):
                deleted.append({"path": str(path), "deleted": False, "reason": "path_outside_task_environment_storage"})
                continue
            existed = resolved.exists()
            if existed:
                shutil.rmtree(resolved)
            deleted.append({"path": str(resolved), "deleted": existed})
        return deleted

    def _delete_events(self, task_run_ids: set[str]) -> dict[str, Any]:
        deleted: list[str] = []
        for task_run_id in sorted(task_run_ids):
            if self.services.event_log.delete_events(task_run_id):
                deleted.append(task_run_id)
        return {
            "authority": "harness.graph_task_lifecycle.runtime_events",
            "deleted_task_run_ids": deleted,
        }
