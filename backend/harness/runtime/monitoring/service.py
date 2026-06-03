from __future__ import annotations

import time
from typing import Any

from .projector import RuntimeMonitorProjector
from .resource_resolver import MonitorResourceResolver


class RuntimeMonitorService:
    def __init__(self, *, runtime_host: Any, graph_harness: Any | None = None, freshness_seconds: float = 5 * 60.0) -> None:
        self.runtime_host = runtime_host
        self.resource_resolver = MonitorResourceResolver(
            runtime_host=runtime_host,
            graph_harness=graph_harness,
            base_dir=getattr(runtime_host, "backend_dir", None),
        )
        self.projector = RuntimeMonitorProjector(
            runtime_host.event_log,
            freshness_seconds=freshness_seconds,
            resource_resolver=self.resource_resolver,
            session_scope_resolver=getattr(runtime_host, "session_scope_resolver", None),
        )

    def attach_graph_harness(self, graph_harness: Any | None) -> None:
        self.resource_resolver.graph_harness = graph_harness

    def list_global_live_monitor(self, limit: int = 20) -> dict[str, Any]:
        requested_limit = max(1, min(int(limit or 20), 100))
        task_runs = self.runtime_host.state_index.list_recent_task_runs(limit=max(requested_limit * 4, 80))
        return self.projector.build_global_monitor(
            task_runs,
            now=time.time(),
            limit=requested_limit,
        )

    def get_session_live_monitor(self, session_id: str, *, limit: int = 20) -> dict[str, Any]:
        task_runs = sorted(
            self.runtime_host.state_index.list_session_task_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        monitor = self.projector.build_session_monitor(session_id, task_runs, now=time.time(), limit=limit)
        active_turn_snapshot = None
        active_turn_registry = getattr(self.runtime_host, "active_turn_registry", None)
        if active_turn_registry is not None:
            try:
                active_turn = active_turn_registry.resolve_current(session_id)
                active_turn_snapshot = active_turn.to_dict() if active_turn is not None else None
            except Exception:
                active_turn_snapshot = None
        return {
            **monitor,
            "active_turn_snapshot": active_turn_snapshot,
        }

    def get_session_task_summary(self, session_id: str) -> dict[str, Any]:
        task_runs = sorted(
            [
                item
                for item in self.runtime_host.state_index.list_session_task_runs(session_id)
                if self.projector.is_top_level_task_run(item)
            ],
            key=lambda item: float(getattr(item, "updated_at", 0.0) or getattr(item, "created_at", 0.0) or 0.0),
            reverse=True,
        )
        if not task_runs:
            return {
                "authority": "runtime_monitor.v1.session_task_summary",
                "available": False,
                "task_run_count": 0,
                "latest_task_run_id": "",
            }

        now = time.time()
        items = [
            self.projector.project_task_run(item, now=now, include_runtime_details=False)
            for item in task_runs
        ]
        active = next(
            (
                item for item in items
                if item.get("bucket") in {"running", "diagnostics"} or item.get("action_required") is True
            ),
            None,
        )
        selected = active or items[0]
        return {
            "authority": "runtime_monitor.v1.session_task_summary",
            "available": True,
            "selection": "active" if active else "latest",
            "task_run_count": len(items),
            "latest_task_run_id": str(items[0].get("task_run_id") or ""),
            "task_run_id": str(selected.get("task_run_id") or ""),
            "task_instance_id": str(selected.get("task_instance_id") or ""),
            "task_id": str(selected.get("task_id") or ""),
            "kind": str(selected.get("kind") or ""),
            "title": str(selected.get("title") or ""),
            "summary": str(selected.get("summary") or ""),
            "status": str(selected.get("status") or ""),
            "lifecycle": str(selected.get("lifecycle") or ""),
            "bucket": str(selected.get("bucket") or ""),
            "terminal": bool(selected.get("terminal")),
            "action_required": bool(selected.get("action_required")),
            "graph_run_id": str(selected.get("graph_run_id") or ""),
            "graph_id": str(selected.get("graph_id") or ""),
            "graph_harness_config_id": str(selected.get("graph_harness_config_id") or ""),
            "created_at": float(selected.get("created_at") or 0.0),
            "updated_at": float(selected.get("updated_at") or 0.0),
        }

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        task_run = self.runtime_host.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        return self.projector.build_task_monitor(task_run, now=time.time())

    def get_resource(self, resource_ref: str) -> dict[str, Any]:
        kind, _, resource_id = str(resource_ref or "").partition(":")
        if kind == "task_run":
            return self.resource_resolver.task_run_ref(resource_id)
        if kind == "session":
            return self.resource_resolver.session_ref(resource_id)
        if kind == "graph_run":
            return self.resource_resolver.graph_run_ref(resource_id)
        if kind == "graph_harness_config":
            return self.resource_resolver.graph_config_ref(resource_id)
        if kind == "artifact":
            return self.resource_resolver.artifact_refs([{"path": resource_id}])[0]
        return {
            "ref": resource_ref,
            "kind": kind or "unknown",
            "id": resource_id,
            "label": resource_ref,
            "availability": {
                "state": "unsupported",
                "reason": "unsupported_resource_kind",
                "checked_at": time.time(),
            },
            "detail_endpoint": "",
        }
