from __future__ import annotations

from copy import deepcopy
import threading
import time
from typing import Any

from .contract import build_envelope
from .management import RuntimeMonitorManagementProjector
from .projector import RuntimeMonitorProjector
from .retention_store import RuntimeMonitorRetentionStore
from .resource_resolver import MonitorResourceResolver
from .signals import build_runtime_monitor_envelope
from .lifecycle import TERMINAL_TASK_RUN_STATUSES
from ..task_run_retention import TaskRunLifecycleRetention

SESSION_MONITOR_TASK_RUN_CANDIDATE_LIMIT = 240


class RuntimeMonitorService:
    def __init__(
        self,
        *,
        runtime_host: Any,
        graph_harness: Any | None = None,
        freshness_seconds: float = 5 * 60.0,
        global_monitor_cache_seconds: float = 1.0,
        retention_sweep_interval_seconds: float = 30.0,
    ) -> None:
        self.runtime_host = runtime_host
        self.global_monitor_cache_seconds = max(0.0, float(global_monitor_cache_seconds or 0.0))
        self.retention_sweep_interval_seconds = max(0.0, float(retention_sweep_interval_seconds or 0.0))
        self._global_monitor_cache_lock = threading.RLock()
        self._global_monitor_cache: dict[tuple[int, tuple[Any, ...]], tuple[float, dict[str, Any]]] = {}
        self._retention_sweep_lock = threading.RLock()
        self._last_retention_sweep_at = 0.0
        self._last_retention_sweep_result: dict[str, Any] | None = None
        self.resource_resolver = MonitorResourceResolver(
            runtime_host=runtime_host,
            graph_harness=graph_harness,
            base_dir=getattr(runtime_host, "backend_dir", None),
        )
        self.projector = RuntimeMonitorProjector(
            runtime_host.event_log,
            runtime_host=runtime_host,
            freshness_seconds=freshness_seconds,
            resource_resolver=self.resource_resolver,
            session_scope_resolver=getattr(runtime_host, "session_scope_resolver", None),
            observability_query=getattr(getattr(runtime_host, "observability", None), "query", None),
            fact_ledger=getattr(runtime_host, "fact_ledger", None),
            trace_service=getattr(runtime_host, "trace_service", None),
        )
        self.retention_store = RuntimeMonitorRetentionStore(
            backend_dir=getattr(runtime_host, "backend_dir", None),
        )
        self.management_projector = RuntimeMonitorManagementProjector(
            retention_store=self.retention_store,
        )
        self.lifecycle_retention = TaskRunLifecycleRetention(runtime_host=runtime_host)

    def attach_graph_harness(self, graph_harness: Any | None) -> None:
        self.resource_resolver.graph_harness = graph_harness

    def list_global_live_monitor(self, limit: int = 20) -> dict[str, Any]:
        requested_limit = max(1, min(int(limit or 20), 100))
        now = time.time()
        self._sweep_expired_task_runs(now=now, limit=max(requested_limit * 4, 80))
        items = self._global_live_items(requested_limit=requested_limit, now=now)
        return build_envelope(scope="global", items=items, now=now, limit=requested_limit)

    def collect_global_runtime_monitor(self, limit: int = 30) -> dict[str, Any]:
        requested_limit = max(1, min(int(limit or 30), 100))
        now = time.time()
        self._sweep_expired_task_runs(now=now, limit=max(requested_limit * 4, 80))
        revision = self._global_monitor_revision()
        cached = self._read_global_monitor_cache(limit=requested_limit, revision=revision, now=now)
        if cached is not None:
            return cached
        items = self._global_live_items(
            requested_limit=requested_limit,
            now=now,
            include_recent_terminal=True,
        )
        envelope = build_runtime_monitor_envelope(items=items, now=now, limit=requested_limit)
        monitor = self.management_projector.apply_management(envelope, now=now, source_items=items)
        self._write_global_monitor_cache(limit=requested_limit, revision=revision, now=time.time(), monitor=monitor)
        return monitor

    def _global_monitor_revision(self) -> tuple[Any, ...]:
        state_index = getattr(self.runtime_host, "state_index", None)
        meta_path = getattr(state_index, "meta_path", None)
        if meta_path is not None:
            try:
                stat = meta_path.stat()
                return ("state_index_meta", int(stat.st_mtime_ns), int(stat.st_size))
            except Exception:
                pass
        return ("ttl_only",)

    def _read_global_monitor_cache(self, *, limit: int, revision: tuple[Any, ...], now: float) -> dict[str, Any] | None:
        if self.global_monitor_cache_seconds <= 0:
            return None
        key = (int(limit), revision)
        with self._global_monitor_cache_lock:
            cached = self._global_monitor_cache.get(key)
            if cached is None:
                return None
            cached_at, monitor = cached
            if now - cached_at > self.global_monitor_cache_seconds:
                self._global_monitor_cache.pop(key, None)
                return None
            return deepcopy(monitor)

    def _write_global_monitor_cache(self, *, limit: int, revision: tuple[Any, ...], now: float, monitor: dict[str, Any]) -> None:
        if self.global_monitor_cache_seconds <= 0:
            return
        key = (int(limit), revision)
        with self._global_monitor_cache_lock:
            self._global_monitor_cache = {
                cache_key: value
                for cache_key, value in self._global_monitor_cache.items()
                if now - value[0] <= self.global_monitor_cache_seconds
            }
            self._global_monitor_cache[key] = (now, deepcopy(monitor))

    def invalidate_global_monitor_cache(self) -> None:
        with self._global_monitor_cache_lock:
            self._global_monitor_cache.clear()

    def _sweep_expired_task_runs(self, *, now: float, limit: int) -> dict[str, Any]:
        with self._retention_sweep_lock:
            elapsed = now - self._last_retention_sweep_at if self._last_retention_sweep_at else 0.0
            if (
                self._last_retention_sweep_result is not None
                and self.retention_sweep_interval_seconds > 0
                and elapsed < self.retention_sweep_interval_seconds
            ):
                return {
                    "authority": "harness.runtime.task_run_lifecycle_retention",
                    "skipped": True,
                    "reason": "retention_sweep_interval",
                    "last_sweep_at": self._last_retention_sweep_at,
                    "next_sweep_at": self._last_retention_sweep_at + self.retention_sweep_interval_seconds,
                    "updated_at": now,
                }
            sweep = self.lifecycle_retention.sweep_expired_task_runs(now=now, limit=limit)
            self._last_retention_sweep_at = now
            self._last_retention_sweep_result = dict(sweep)
        if int(sweep.get("terminal_update_count") or 0) or int(sweep.get("stop_request_count") or 0):
            self.invalidate_global_monitor_cache()
        return sweep

    def _global_live_items(self, *, requested_limit: int, now: float, include_recent_terminal: bool = False) -> list[dict[str, Any]]:
        task_runs = self._recent_task_run_summaries(limit=max(requested_limit * 4, 80))
        base_monitor = self.projector.build_global_monitor(
            task_runs,
            now=now,
            limit=requested_limit,
        )
        base_items = [item for item in list(base_monitor.get("items") or []) if isinstance(item, dict)]
        if include_recent_terminal:
            base_items = [
                *base_items,
                *self._recent_terminal_items(
                    task_runs=task_runs,
                    visible_items=base_items,
                    now=now,
                    limit=max(requested_limit, 20),
                ),
            ]
        active_turn_items = self._global_active_turn_items(now=now, visible_items=base_items)
        if not active_turn_items:
            return base_items
        return self.projector.select_current_items_by_session([
            *base_items,
            *active_turn_items,
        ])

    def _recent_terminal_items(
        self,
        *,
        task_runs: list[Any],
        visible_items: list[dict[str, Any]],
        now: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        visible_ids = {
            str(item.get("task_run_id") or "").strip()
            for item in visible_items
            if str(item.get("task_run_id") or "").strip()
        }
        recent: list[dict[str, Any]] = []
        for task_run in sorted(
            task_runs,
            key=lambda item: float(getattr(item, "updated_at", 0.0) or getattr(item, "created_at", 0.0) or 0.0),
            reverse=True,
        ):
            task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
            if not task_run_id or task_run_id in visible_ids:
                continue
            if not self.projector.is_top_level_task_run(task_run):
                continue
            status = str(getattr(task_run, "status", "") or "").strip()
            if status not in TERMINAL_TASK_RUN_STATUSES:
                continue
            projected = self.projector.project_task_run(
                task_run,
                now=now,
                include_runtime_details=False,
                include_graph_runtime=False,
            )
            if str(projected.get("kind") or "").strip() == "task_graph":
                continue
            recent.append(projected)
            if len(recent) >= max(1, int(limit or 20)):
                break
        return recent

    def get_session_live_monitor(self, session_id: str, *, limit: int = 20) -> dict[str, Any]:
        requested_limit = max(1, min(int(limit or 20), 100))
        candidate_limit = min(SESSION_MONITOR_TASK_RUN_CANDIDATE_LIMIT, max(requested_limit * 4, 40))
        self._sweep_expired_task_runs(now=time.time(), limit=240)
        task_runs = sorted(
            self._session_task_run_summaries(session_id, limit=candidate_limit),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        now = time.time()
        monitor = self.projector.build_session_monitor(session_id, task_runs, now=now, limit=requested_limit)
        active_turn_snapshot = None
        active_turn_registry = getattr(self.runtime_host, "active_turn_registry", None)
        if active_turn_registry is not None:
            try:
                active_turn = active_turn_registry.resolve_current(session_id)
                active_turn_snapshot = active_turn.to_dict() if active_turn is not None else None
            except Exception:
                active_turn_snapshot = None
        if not list(monitor.get("items") or []):
            active_item = self._session_active_turn_item(session_id, now=now)
            if active_item is not None:
                monitor = build_envelope(
                    scope="session",
                    items=[active_item],
                    now=now,
                    limit=limit,
                    selected=active_item,
                    extra={
                        "session_id": session_id,
                        "active_task_run_id": str(active_item.get("task_run_id") or ""),
                        "latest_task_run_id": "",
                        "task_run_count": len(task_runs),
                        "monitor": active_item,
                    },
                )
        return {
            **monitor,
            "active_turn_snapshot": active_turn_snapshot,
        }

    def get_session_task_summary(self, session_id: str) -> dict[str, Any]:
        self._sweep_expired_task_runs(now=time.time(), limit=240)
        task_runs = sorted(
            [
                item
                for item in self._session_task_run_summaries(session_id)
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
            self.projector.project_task_run(
                item,
                now=now,
                include_runtime_details=False,
                include_graph_runtime=False,
            )
            for item in task_runs
        ]
        active = next(
            (
                item for item in items
                if item.get("activity_state") in {"running", "waiting", "paused", "stale"}
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
            "activity_state": str(selected.get("activity_state") or ""),
            "activity_label": str(selected.get("activity_label") or ""),
            "is_running": bool(selected.get("is_running")),
            "is_waiting": bool(selected.get("is_waiting")),
            "is_resumable": bool(selected.get("is_resumable")),
            "is_interruptible": bool(selected.get("is_interruptible")),
            "control_reason": str(selected.get("control_reason") or ""),
            "tone": str(selected.get("tone") or ""),
            "activity": dict(selected.get("activity") or {}),
            "control_capability": dict(selected.get("control_capability") or {}),
            "graph_run_id": str(selected.get("graph_run_id") or ""),
            "graph_id": str(selected.get("graph_id") or ""),
            "graph_harness_config_id": str(selected.get("graph_harness_config_id") or ""),
            "created_at": float(selected.get("created_at") or 0.0),
            "updated_at": float(selected.get("updated_at") or 0.0),
        }

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        self._sweep_expired_task_runs(now=time.time(), limit=240)
        task_run = self.runtime_host.state_index.get_task_run(task_run_id)
        now = time.time()
        if task_run is not None:
            return self.projector.build_task_monitor(task_run, now=now)
        turn_run = self.runtime_host.state_index.get_turn_run(task_run_id)
        if turn_run is None:
            return None
        active_turn = None
        active_turn_registry = getattr(self.runtime_host, "active_turn_registry", None)
        if active_turn_registry is not None:
            try:
                candidate = active_turn_registry.resolve_current(str(getattr(turn_run, "session_id", "") or ""))
                if candidate is not None and str(getattr(candidate, "turn_run_id", "") or "") == str(getattr(turn_run, "turn_run_id", "") or ""):
                    active_turn = candidate
            except Exception:
                active_turn = None
        if active_turn is None:
            return None
        runtime_run = self._latest_session_runtime_run(str(getattr(turn_run, "session_id", "") or ""))
        return self.projector.build_turn_monitor(
            active_turn=active_turn,
            turn_run=turn_run,
            runtime_run=runtime_run,
            now=now,
        )

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

    def _global_active_turn_items(self, *, now: float, visible_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        run_registry = getattr(self.runtime_host, "run_registry", None)
        active_turn_registry = getattr(self.runtime_host, "active_turn_registry", None)
        if run_registry is None or active_turn_registry is None:
            return []
        session_ids: list[str] = []
        seen: set[str] = set()
        for run in list(getattr(run_registry, "list_runs", lambda: [])() or []):
            session_id = str(getattr(run, "session_id", "") or "").strip()
            status = str(getattr(run, "status", "") or "").strip()
            if not session_id or session_id in seen or status in {"completed", "failed", "stopped", "orphaned"}:
                continue
            seen.add(session_id)
            session_ids.append(session_id)
        items: list[dict[str, Any]] = []
        for session_id in session_ids:
            item = self._session_active_turn_item(session_id, now=now)
            if item is not None:
                if self._visible_item_already_represents_active_turn(item, visible_items):
                    continue
                items.append(item)
        return items

    def _session_active_turn_item(self, session_id: str, *, now: float) -> dict[str, Any] | None:
        active_turn_registry = getattr(self.runtime_host, "active_turn_registry", None)
        if active_turn_registry is None:
            return None
        try:
            active_turn = active_turn_registry.resolve_current(session_id)
        except Exception:
            active_turn = None
        if active_turn is None:
            return None
        turn_run_id = str(getattr(active_turn, "turn_run_id", "") or "").strip()
        if not turn_run_id:
            return None
        turn_run = self.runtime_host.state_index.get_turn_run(turn_run_id)
        runtime_run = self._latest_session_runtime_run(session_id)
        return self.projector.project_active_turn(
            active_turn=active_turn,
            turn_run=turn_run,
            runtime_run=runtime_run,
            now=now,
        )

    def _visible_item_already_represents_active_turn(self, active_item: dict[str, Any], visible_items: list[dict[str, Any]]) -> bool:
        active_session_id = str(active_item.get("session_id") or "").strip()
        active_task_run_id = str(active_item.get("task_run_id") or "").strip()
        active_instance_id = str(active_item.get("task_instance_id") or "").strip()
        for item in visible_items:
            if str(item.get("session_id") or "").strip() != active_session_id:
                continue
            item_task_run_id = str(item.get("task_run_id") or "").strip()
            item_instance_id = str(item.get("task_instance_id") or "").strip()
            same_work = active_task_run_id and item_task_run_id == active_task_run_id
            same_instance = active_instance_id and item_instance_id == active_instance_id
            if not same_work and not same_instance:
                continue
            if item.get("is_running") is True or str(item.get("activity_state") or "") in {"waiting", "paused", "stale"}:
                return True
        return False

    def _latest_session_runtime_run(self, session_id: str) -> Any | None:
        run_registry = getattr(self.runtime_host, "run_registry", None)
        if run_registry is None:
            return None
        latest = getattr(run_registry, "latest_session_run", None)
        if callable(latest):
            try:
                return latest(session_id)
            except Exception:
                return None
        return None

    def _recent_task_run_summaries(self, *, limit: int) -> list[Any]:
        return list(self.runtime_host.state_index.list_recent_task_run_summaries(limit=limit) or [])

    def _session_task_run_summaries(self, session_id: str, *, limit: int | None = None) -> list[Any]:
        return list(self.runtime_host.state_index.list_session_task_run_summaries(session_id, limit=limit) or [])
