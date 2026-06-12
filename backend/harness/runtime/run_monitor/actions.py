from __future__ import annotations

import asyncio
import time
from typing import Any

from harness.graph.lifecycle_manager import GraphTaskLifecycleManager
from harness.runtime.task_record_lifecycle import (
    TaskRecordLifecycleConflict,
    TaskRecordLifecycleManager,
    TaskRecordLifecycleNotFound,
)


class RuntimeMonitorActionService:
    authority = "runtime_monitor.actions"

    def __init__(self, *, runtime: Any, monitor_service: Any) -> None:
        self.runtime = runtime
        self.monitor_service = monitor_service
        self.host = runtime.harness_runtime.single_agent_runtime_host

    async def preflight(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = _action_name(payload)
        monitor = self.monitor_service.collect_global_runtime_monitor(limit=80)
        signal = _find_signal(monitor, payload)
        revision_check = _source_revision_check(payload=payload, monitor=monitor)
        check = self._action_check(action=action, payload=payload, signal=signal)
        effects = self._preview_effects(action=action, payload=payload, signal=signal)
        if not revision_check.get("fresh"):
            effects = {
                **effects,
                "source_revision_check": revision_check,
            }
        return {
            "authority": self.authority,
            "mode": "preflight",
            "accepted": bool(check.get("enabled")),
            "action": action,
            "target": _target(payload=payload, signal=signal),
            "effects": effects,
            "disabled_reason": str(check.get("disabled_reason") or ""),
            "receipt": _receipt(action=action, accepted=bool(check.get("enabled")), mode="preflight"),
            "monitor": monitor,
            "updated_at": time.time(),
        }

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = _action_name(payload)
        preflight = await self.preflight(payload)
        if not preflight.get("accepted"):
            return {
                **preflight,
                "mode": "execute",
                "accepted": False,
                "receipt": _receipt(
                    action=action,
                    accepted=False,
                    mode="execute",
                    reason=str(preflight.get("disabled_reason") or "action_not_available"),
                ),
            }
        signal = _find_signal(dict(preflight.get("monitor") or {}), payload)
        effects: dict[str, Any]
        if action == "clear_from_monitor":
            effects = self._clear_from_monitor(payload=payload, signal=signal)
        elif action == "restore_to_monitor":
            effects = self._restore_to_monitor(payload=payload, signal=signal)
        elif action == "close_runtime":
            effects = self._close_runtime(payload=payload, signal=signal)
        elif action == "delete_record":
            effects = await self._delete_record(payload=payload, signal=signal)
        elif action == "pause_task":
            effects = self._pause_task(payload=payload, signal=signal)
        elif action == "stop_task":
            effects = self._stop_task(payload=payload, signal=signal)
        elif action in {"preview_delete_record", "preview_delete_graph_run"}:
            effects = self._preview_effects(action=action, payload=payload, signal=signal)
        else:
            return {
                **preflight,
                "mode": "execute",
                "accepted": False,
                "disabled_reason": "unsupported_action",
                "receipt": _receipt(action=action, accepted=False, mode="execute", reason="unsupported_action"),
            }
        accepted = not bool(effects.get("error"))
        if accepted:
            invalidator = getattr(self.monitor_service, "invalidate_global_monitor_cache", None)
            if callable(invalidator):
                invalidator()
        return {
            "authority": self.authority,
            "mode": "execute",
            "accepted": accepted,
            "action": action,
            "target": _target(payload=payload, signal=signal),
            "effects": effects,
            "disabled_reason": "" if accepted else str(effects.get("error") or "action_failed"),
            "receipt": _receipt(action=action, accepted=accepted, mode="execute", reason=str(effects.get("error") or "")),
            "monitor": self.monitor_service.collect_global_runtime_monitor(limit=80),
            "updated_at": time.time(),
        }

    def _action_check(self, *, action: str, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        if action in {"clear_from_monitor", "restore_to_monitor"} and not _signal_id(payload=payload, signal=signal):
            return {"enabled": False, "disabled_reason": "signal_id_required"}
        if action == "preview_delete_graph_run":
            return {"enabled": bool(_graph_run_id(payload=payload, signal=signal)), "disabled_reason": "" if _graph_run_id(payload=payload, signal=signal) else "graph_run_id_required"}
        task_run_required_actions = {
            "close_runtime",
            "pause_task",
            "stop_task",
            "delete_record",
            "preview_delete_record",
        }
        if action in task_run_required_actions and not _task_run_id(payload=payload, signal=signal):
            return {"enabled": False, "disabled_reason": "task_run_id_required"}
        if signal is None:
            return {"enabled": action in {"preview_delete_record", "delete_record"}, "disabled_reason": "" if action in {"preview_delete_record", "delete_record"} else "signal_not_found"}
        for item in list(signal.get("actions") or []):
            candidate = dict(item or {})
            if str(candidate.get("action") or "") == action:
                return {
                    "enabled": bool(candidate.get("enabled")),
                    "disabled_reason": str(candidate.get("disabled_reason") or ""),
                }
        return {"enabled": False, "disabled_reason": "action_not_available"}

    def _preview_effects(self, *, action: str, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        if action == "preview_delete_graph_run":
            graph_run_id = _graph_run_id(payload=payload, signal=signal)
            graph_harness = getattr(self.runtime.harness_runtime, "graph_harness", None)
            if graph_harness is None:
                return {"error": "graph_harness_unavailable", "graph_run_id": graph_run_id}
            try:
                return GraphTaskLifecycleManager(base_dir=self.runtime.base_dir, graph_harness=graph_harness).preview_delete_graph_run(graph_run_id)
            except Exception as exc:
                return {"error": str(exc), "graph_run_id": graph_run_id}
        if action in {"preview_delete_record", "delete_record"}:
            task_run_id = _task_run_id(payload=payload, signal=signal)
            task_run = self.host.state_index.get_task_run(task_run_id)
            if task_run is None:
                return {"error": "task_run_not_found", "task_run_id": task_run_id}
            status = str(getattr(task_run, "status", "") or "")
            return {
                "authority": "runtime_monitor.actions.delete_record_preview",
                "task_run_id": task_run_id,
                "status": status,
                "terminal": status in {"completed", "success", "failed", "aborted", "cancelled", "error"},
                "estimated_effects": {
                    "task_runs": 1,
                    "event_log": "task_run_scope",
                    "prompt_accounting": "task_run_scope",
                    "execution_store": "task_run_scope",
                },
            }
        return {"authority": "runtime_monitor.actions.preflight", "action": action}

    def _clear_from_monitor(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        signal_id = _signal_id(payload=payload, signal=signal)
        row = self.monitor_service.retention_store.hide_signal(
            signal_id=signal_id,
            task_run_id=_task_run_id(payload=payload, signal=signal),
            graph_run_id=_graph_run_id(payload=payload, signal=signal),
            reason=str(payload.get("reason") or "user_cleared"),
            hidden_by="user",
            source_revision=str(payload.get("source_revision") or ""),
        )
        return {"authority": "runtime_monitor.actions.clear_from_monitor", "hidden": row}

    def _restore_to_monitor(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        row = self.monitor_service.retention_store.unhide_signal(
            signal_id=_signal_id(payload=payload, signal=signal),
            reason=str(payload.get("reason") or "user_restored"),
        )
        return {"authority": "runtime_monitor.actions.restore_to_monitor", "restored": row}

    def _close_runtime(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        task_run_id = _task_run_id(payload=payload, signal=signal)
        reason = str(payload.get("reason") or "runtime_monitor_close_runtime")
        stop_result = self._stop_task(
            payload={**payload, "reason": reason},
            signal=signal,
        )
        if stop_result.get("error") or stop_result.get("ok") is False:
            return {
                "authority": "runtime_monitor.actions.close_runtime",
                "task_run_id": task_run_id,
                "stop": stop_result,
                "error": str(stop_result.get("error") or "runtime_close_rejected"),
            }
        signal_id = _signal_id(payload=payload, signal=signal) or task_run_id
        hidden = self.monitor_service.retention_store.hide_signal(
            signal_id=signal_id,
            task_run_id=task_run_id,
            graph_run_id=_graph_run_id(payload=payload, signal=signal),
            reason=reason,
            hidden_by="user",
            source_revision=str(payload.get("source_revision") or ""),
        )
        return {
            "authority": "runtime_monitor.actions.close_runtime",
            "task_run_id": task_run_id,
            "stop": stop_result,
            "hidden": hidden,
        }

    async def _delete_record(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        task_run_id = _task_run_id(payload=payload, signal=signal)
        manager = TaskRecordLifecycleManager(self.runtime)
        try:
            task_run, deletion_mark = await manager.prepare_single_task_record_deletion(
                task_run_id,
                cancel_timeout_seconds=1.0,
            )
        except TaskRecordLifecycleNotFound:
            return {"error": "task_run_not_found", "task_run_id": task_run_id}
        except TaskRecordLifecycleConflict as exc:
            return {
                "error": exc.reason,
                "task_run_id": exc.task_run_id,
                "graph_run_id": exc.graph_run_id,
            }
        signal_id = _signal_id(payload=payload, signal=signal) or task_run_id
        hidden = self.monitor_service.retention_store.hide_signal(
            signal_id=signal_id,
            task_run_id=task_run_id,
            graph_run_id=_graph_run_id(payload=payload, signal=signal),
            reason="delete_record_queued",
            hidden_by="user",
            source_revision=str(payload.get("source_revision") or ""),
        )
        cleanup_name = f"runtime-monitor-delete-record:{task_run_id}"
        cleanup_queued = False
        if not _background_task_running(self.host, cleanup_name):
            self._spawn_background_cleanup(
                self._cleanup_task_record(manager=manager, task_run=task_run),
                name=cleanup_name,
            )
            cleanup_queued = True
        return {
            "authority": "runtime_monitor.actions.delete_record",
            "mode": "queued_cleanup",
            "task_run_id": task_run_id,
            "deleted": False,
            "cleanup_queued": cleanup_queued,
            "cleanup_task_name": cleanup_name,
            "hidden": hidden,
            "deletion_mark": deletion_mark,
        }

    async def _cleanup_task_record(self, *, manager: TaskRecordLifecycleManager, task_run: Any) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager.cleanup_single_task_record, task_run)
        except Exception as exc:
            return {
                "authority": "runtime_monitor.actions.delete_record.cleanup",
                "task_run_id": str(getattr(task_run, "task_run_id", "") or ""),
                "error": str(exc),
            }

    def _spawn_background_cleanup(self, coro: Any, *, name: str) -> None:
        spawner = getattr(self.host, "spawn_background_task", None)
        if callable(spawner):
            spawner(coro, name=name)
            return
        asyncio.create_task(coro, name=name)

    def _pause_task(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        from harness.loop.task_executor import request_task_run_pause

        task_run_id = _task_run_id(payload=payload, signal=signal)
        return dict(request_task_run_pause(self.host, task_run_id, reason=str(payload.get("reason") or ""), requested_by="user") or {})

    def _stop_task(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        from harness.loop.task_executor import stop_task_run

        task_run_id = _task_run_id(payload=payload, signal=signal)
        return dict(stop_task_run(self.host, task_run_id, reason=str(payload.get("reason") or ""), requested_by="user") or {})


def _action_name(payload: dict[str, Any]) -> str:
    return str(payload.get("action") or "").strip()


def _source_revision_check(*, payload: dict[str, Any], monitor: dict[str, Any]) -> dict[str, Any]:
    source_revision = str(payload.get("source_revision") or "").strip()
    current_revision = str(monitor.get("revision") or "").strip()
    if not source_revision or not current_revision:
        return {
            "fresh": True,
            "source_revision": source_revision,
            "current_revision": current_revision,
        }
    return {
        "fresh": source_revision == current_revision,
        "source_revision": source_revision,
        "current_revision": current_revision,
    }


def _find_signal(monitor: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates = {
        str(payload.get("signal_id") or "").strip(),
        str(payload.get("task_run_id") or "").strip(),
        str(payload.get("graph_run_id") or "").strip(),
    } - {""}
    for signal in _all_signals(monitor):
        if {
            str(signal.get("signal_id") or "").strip(),
            str(signal.get("task_instance_id") or "").strip(),
            str(signal.get("task_run_id") or "").strip(),
            str(signal.get("graph_run_id") or "").strip(),
        } & candidates:
            return signal
    return None


def _all_signals(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend([dict(item) for item in list(monitor.get("signals") or []) if isinstance(item, dict)])
    management = dict(monitor.get("management") or {})
    lanes = dict(management.get("lanes") or {})
    for lane in ("current", "attention", "projects", "recent", "hidden"):
        rows.extend([dict(item) for item in list(lanes.get(lane) or []) if isinstance(item, dict)])
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("signal_id") or row.get("task_run_id") or row.get("graph_run_id") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(row)
    return result


def _target(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, str]:
    return {
        "signal_id": _signal_id(payload=payload, signal=signal),
        "task_run_id": _task_run_id(payload=payload, signal=signal),
        "graph_run_id": _graph_run_id(payload=payload, signal=signal),
    }


def _signal_id(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
    return str(payload.get("signal_id") or (signal or {}).get("signal_id") or (signal or {}).get("task_instance_id") or "").strip()


def _task_run_id(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
    return str(payload.get("task_run_id") or (signal or {}).get("task_run_id") or "").strip()


def _graph_run_id(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
    graph_ref = dict((signal or {}).get("graph_ref") or {})
    return str(payload.get("graph_run_id") or (signal or {}).get("graph_run_id") or graph_ref.get("graph_run_id") or "").strip()


def _receipt(*, action: str, accepted: bool, mode: str, reason: str = "") -> dict[str, Any]:
    return {
        "authority": "runtime_monitor.action_receipt",
        "action": action,
        "accepted": bool(accepted),
        "mode": mode,
        "reason": reason,
        "created_at": time.time(),
    }


def _background_task_running(host: Any, name: str) -> bool:
    tasks_by_name = getattr(host, "_background_tasks_by_name", {})
    if not isinstance(tasks_by_name, dict):
        return False
    tasks = tasks_by_name.get(name, set())
    return any(not getattr(task, "done", lambda: True)() for task in list(tasks or []))
