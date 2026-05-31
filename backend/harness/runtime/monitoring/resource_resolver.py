from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from project_layout import ProjectLayout


class MonitorResourceResolver:
    def __init__(self, *, runtime_host: Any, graph_harness: Any | None = None, base_dir: Path | None = None) -> None:
        self.runtime_host = runtime_host
        self.graph_harness = graph_harness
        self.base_dir = Path(base_dir or getattr(runtime_host, "backend_dir", Path.cwd()))
        self.project_root = ProjectLayout.from_backend_dir(self.base_dir).project_root

    def task_run_ref(self, task_run_id: str, *, label: str = "任务运行") -> dict[str, Any]:
        return self._resource_ref(
            kind="task_run",
            resource_id=task_run_id,
            label=label,
            available=self._task_run_exists(task_run_id),
        )

    def session_ref(self, session_id: str, *, label: str = "会话") -> dict[str, Any]:
        return self._resource_ref(kind="session", resource_id=session_id, label=label, available=bool(session_id))

    def graph_run_ref(self, graph_run_id: str, *, label: str = "任务图运行") -> dict[str, Any]:
        available = False
        if graph_run_id and self.graph_harness is not None:
            get_graph_run = getattr(self.graph_harness, "get_graph_run", None)
            if callable(get_graph_run):
                try:
                    available = bool(get_graph_run(graph_run_id))
                except Exception:
                    available = False
        return self._resource_ref(kind="graph_run", resource_id=graph_run_id, label=label, available=available)

    def graph_config_ref(self, graph_harness_config_id: str, *, label: str = "任务图配置") -> dict[str, Any]:
        available = False
        if graph_harness_config_id:
            try:
                from task_system import TaskFlowRegistry

                available = TaskFlowRegistry(self.base_dir).get_graph_harness_config(graph_harness_config_id) is not None
            except Exception:
                available = False
        return self._resource_ref(
            kind="graph_harness_config",
            resource_id=graph_harness_config_id,
            label=label,
            available=available,
        )

    def artifact_refs(self, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            self._artifact_ref(ref)
            for ref in refs
            if isinstance(ref, dict)
        ]

    def graph_monitor(self, graph_run_id: str, graph_harness_config_id: str = "", *, event_limit: int = 80) -> dict[str, Any] | None:
        if not graph_run_id or self.graph_harness is None:
            return None
        graph_config = None
        if graph_harness_config_id:
            try:
                from task_system import TaskFlowRegistry

                graph_config = TaskFlowRegistry(self.base_dir).get_graph_harness_config(graph_harness_config_id)
            except Exception:
                graph_config = None
            if graph_config is None:
                return None
        getter = getattr(self.graph_harness, "get_graph_run_monitor", None)
        if not callable(getter):
            return None
        try:
            return getter(graph_run_id, graph_config=graph_config, event_limit=event_limit)
        except Exception:
            return None

    def _task_run_exists(self, task_run_id: str) -> bool:
        if not task_run_id:
            return False
        getter = getattr(getattr(self.runtime_host, "state_index", None), "get_task_run", None)
        if not callable(getter):
            return False
        try:
            return getter(task_run_id) is not None
        except Exception:
            return False

    def _artifact_ref(self, ref: dict[str, Any]) -> dict[str, Any]:
        path_text = str(ref.get("absolute_path") or ref.get("path") or ref.get("src") or "").strip()
        exists = False
        if path_text:
            candidate = Path(path_text)
            resolved = candidate.resolve() if candidate.is_absolute() else (self.project_root / path_text).resolve()
            exists = _inside(resolved, self.project_root) and resolved.exists() and resolved.is_file()
        resource_id = path_text or str(ref)
        return {
            **dict(ref),
            **self._resource_ref(kind="artifact", resource_id=resource_id, label=str(ref.get("label") or "交付物"), available=exists),
        }

    def _resource_ref(self, *, kind: str, resource_id: str, label: str, available: bool) -> dict[str, Any]:
        normalized_id = str(resource_id or "").strip()
        state = "available" if normalized_id and available else "missing"
        return {
            "ref": f"{kind}:{normalized_id}",
            "kind": kind,
            "id": normalized_id,
            "label": str(label or kind),
            "availability": {
                "state": state,
                "reason": "" if state == "available" else f"{kind}_missing",
                "checked_at": time.time(),
            },
            "detail_endpoint": f"/api/orchestration/runtime-monitor/resources/{kind}:{normalized_id}" if normalized_id else "",
        }


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
