from __future__ import annotations

import asyncio
import time
from typing import Any

from graph_system.lifecycle_manager import GraphTaskLifecycleManager
from harness.runtime.task_record_lifecycle import (
    TaskRecordLifecycleConflict,
    TaskRecordLifecycleManager,
    TaskRecordLifecycleNotFound,
)


class RunMonitorActionService:
    authority = "harness.run_monitor.actions"

    def __init__(self, *, runtime: Any, monitor_service: Any) -> None:
        self.runtime = runtime
        self.monitor_service = monitor_service
        self.host = runtime.harness_runtime.single_agent_runtime_host

    async def preflight(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = _action_name(payload)
        monitor = self.monitor_service.collect_global_run_monitor(limit=80)
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
        signal = _find_signal(dict(preflight.get("monitor") or {}), payload)
        execution_check = self._execution_check(action=action, payload=payload, signal=signal)
        if not execution_check.get("enabled"):
            return {
                **preflight,
                "mode": "execute",
                "accepted": False,
                "receipt": _receipt(
                    action=action,
                    accepted=False,
                    mode="execute",
                    reason=str(execution_check.get("disabled_reason") or "action_not_available"),
                ),
                "disabled_reason": str(execution_check.get("disabled_reason") or "action_not_available"),
            }
        effects: dict[str, Any]
        if action == "clear_from_monitor":
            effects = self._clear_from_monitor(payload=payload, signal=signal)
        elif action == "restore_to_monitor":
            effects = self._restore_to_monitor(payload=payload, signal=signal)
        elif action == "delete_record":
            effects = await self._delete_record(payload=payload, signal=signal)
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
            "monitor": self.monitor_service.collect_global_run_monitor(limit=80),
            "updated_at": time.time(),
        }

    def _action_check(self, *, action: str, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        if action in {"clear_from_monitor", "restore_to_monitor"} and not _signal_id(payload=payload, signal=signal):
            return {"enabled": False, "disabled_reason": "signal_id_required"}
        if action == "preview_delete_graph_run":
            return {"enabled": bool(_graph_run_id(payload=payload, signal=signal)), "disabled_reason": "" if _graph_run_id(payload=payload, signal=signal) else "graph_run_id_required"}
        task_run_required_actions = {
            "delete_record",
            "preview_delete_record",
        }
        if action in task_run_required_actions and not self._legacy_task_run_id(payload=payload, signal=signal):
            return {"enabled": False, "disabled_reason": "runtime_anchor_or_task_run_id_required"}
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

    def _execution_check(self, *, action: str, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        if action in {"clear_from_monitor", "restore_to_monitor"}:
            if not _signal_id(payload=payload, signal=signal):
                return {"enabled": False, "disabled_reason": "signal_id_required"}
            return {"enabled": True, "disabled_reason": ""}
        if action == "preview_delete_graph_run":
            if not _graph_run_id(payload=payload, signal=signal):
                return {"enabled": False, "disabled_reason": "graph_run_id_required"}
            return {"enabled": True, "disabled_reason": ""}
        task_run_required_actions = {
            "delete_record",
            "preview_delete_record",
        }
        if action in task_run_required_actions:
            if not self._legacy_task_run_id(payload=payload, signal=signal):
                return {"enabled": False, "disabled_reason": "runtime_anchor_or_task_run_id_required"}
            return {"enabled": True, "disabled_reason": ""}
        return {"enabled": False, "disabled_reason": "unsupported_action"}

    def _preview_effects(self, *, action: str, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        if action == "preview_delete_graph_run":
            graph_run_id = _graph_run_id(payload=payload, signal=signal)
            graph_system = getattr(self.runtime.harness_runtime, "graph_system", None)
            if graph_system is None:
                return {"error": "graph_system_unavailable", "graph_run_id": graph_run_id}
            try:
                return GraphTaskLifecycleManager(base_dir=self.runtime.base_dir, graph_system=graph_system).preview_delete_graph_run(graph_run_id)
            except Exception as exc:
                return {"error": str(exc), "graph_run_id": graph_run_id}
        if action in {"preview_delete_record", "delete_record"}:
            task_run_id = self._legacy_task_run_id(payload=payload, signal=signal)
            runtime_anchor_id = _runtime_anchor_id(payload=payload, signal=signal)
            task_run = self.host.state_index.get_task_run(task_run_id)
            if task_run is None:
                return {"error": "runtime_anchor_event_scope_not_found", "runtime_anchor_id": runtime_anchor_id, "task_run_id": task_run_id}
            status = str(getattr(task_run, "status", "") or "")
            return {
                "authority": "harness.run_monitor.actions.delete_record_preview",
                "runtime_anchor_id": runtime_anchor_id,
                "task_run_id": task_run_id,
                "status": status,
                "terminal": status in {"completed", "failed", "aborted"},
                "estimated_effects": {
                    "task_runs": 1,
                    "event_log": "task_run_scope",
                    "prompt_accounting": "task_run_scope",
                    "execution_store": "task_run_scope",
                },
            }
        return {"authority": "harness.run_monitor.actions.preflight", "action": action}

    def _clear_from_monitor(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        signal_id = _signal_id(payload=payload, signal=signal)
        row = self.monitor_service.retention_store.hide_signal(
            signal_id=signal_id,
            task_run_id=self._legacy_task_run_id(payload=payload, signal=signal),
            graph_run_id=_graph_run_id(payload=payload, signal=signal),
            reason=str(payload.get("reason") or "user_cleared"),
            hidden_by="user",
            source_revision=str(payload.get("source_revision") or ""),
        )
        return {"authority": "harness.run_monitor.actions.clear_from_monitor", "hidden": row}

    def _restore_to_monitor(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        row = self.monitor_service.retention_store.unhide_signal(
            signal_id=_signal_id(payload=payload, signal=signal),
            reason=str(payload.get("reason") or "user_restored"),
        )
        return {"authority": "harness.run_monitor.actions.restore_to_monitor", "restored": row}

    async def _delete_record(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, Any]:
        task_run_id = self._legacy_task_run_id(payload=payload, signal=signal)
        runtime_anchor_id = _runtime_anchor_id(payload=payload, signal=signal)
        manager = TaskRecordLifecycleManager(self.runtime)
        try:
            task_run, deletion_mark = await manager.prepare_single_task_record_deletion(
                task_run_id,
                cancel_timeout_seconds=1.0,
            )
        except TaskRecordLifecycleNotFound:
            return {"error": "runtime_anchor_event_scope_not_found", "runtime_anchor_id": runtime_anchor_id, "task_run_id": task_run_id}
        except TaskRecordLifecycleConflict as exc:
            return {
                "error": exc.reason,
                "runtime_anchor_id": runtime_anchor_id,
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
            "authority": "harness.run_monitor.actions.delete_record",
            "mode": "queued_cleanup",
            "runtime_anchor_id": runtime_anchor_id,
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
                "authority": "harness.run_monitor.actions.delete_record.cleanup",
                "task_run_id": str(getattr(task_run, "task_run_id", "") or ""),
                "error": str(exc),
            }

    def _spawn_background_cleanup(self, coro: Any, *, name: str) -> None:
        spawner = getattr(self.host, "spawn_background_task", None)
        if not callable(spawner):
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            raise RuntimeError("runtime monitor cleanup requires host.spawn_background_task")
        spawner(coro, name=name)

    def _legacy_task_run_id(self, *, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
        direct = _task_run_id(payload=payload, signal=signal)
        if direct:
            return direct
        runtime_anchor_id = _runtime_anchor_id(payload=payload, signal=signal)
        if not runtime_anchor_id:
            return ""
        getter = getattr(getattr(self.host, "state_index", None), "get_runtime_anchor", None)
        if not callable(getter):
            return ""
        try:
            anchor = getter(runtime_anchor_id)
        except Exception:
            anchor = None
        if anchor is None:
            return ""
        payload = anchor.to_dict() if hasattr(anchor, "to_dict") else dict(anchor)
        return _event_scope_task_run_id(payload)


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
        str(payload.get("runtime_anchor_id") or "").strip(),
        str(payload.get("task_run_id") or "").strip(),
        str(payload.get("graph_run_id") or "").strip(),
    } - {""}
    for signal in _all_signals(monitor):
        if {
            str(signal.get("signal_id") or "").strip(),
            str(signal.get("runtime_anchor_id") or "").strip(),
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
        key = str(row.get("signal_id") or row.get("runtime_anchor_id") or row.get("task_run_id") or row.get("graph_run_id") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(row)
    return result


def _target(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> dict[str, str]:
    return {
        "signal_id": _signal_id(payload=payload, signal=signal),
        "runtime_anchor_id": _runtime_anchor_id(payload=payload, signal=signal),
        "task_run_id": _task_run_id(payload=payload, signal=signal),
        "graph_run_id": _graph_run_id(payload=payload, signal=signal),
    }


def _signal_id(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
    return str(payload.get("signal_id") or (signal or {}).get("signal_id") or (signal or {}).get("runtime_anchor_id") or (signal or {}).get("task_instance_id") or "").strip()


def _runtime_anchor_id(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
    runtime_anchor = dict((signal or {}).get("runtime_anchor") or {})
    return str(payload.get("runtime_anchor_id") or (signal or {}).get("runtime_anchor_id") or runtime_anchor.get("runtime_anchor_id") or "").strip()


def _task_run_id(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
    runtime_anchor = dict((signal or {}).get("runtime_anchor") or {})
    return str(payload.get("task_run_id") or (signal or {}).get("task_run_id") or runtime_anchor.get("legacy_task_run_id") or "").strip()


def _graph_run_id(*, payload: dict[str, Any], signal: dict[str, Any] | None) -> str:
    graph_ref = dict((signal or {}).get("graph_ref") or {})
    return str(payload.get("graph_run_id") or (signal or {}).get("graph_run_id") or graph_ref.get("graph_run_id") or "").strip()


def _receipt(*, action: str, accepted: bool, mode: str, reason: str = "") -> dict[str, Any]:
    return {
        "authority": "harness.run_monitor.action_receipt",
        "action": action,
        "accepted": bool(accepted),
        "mode": mode,
        "reason": reason,
        "created_at": time.time(),
    }


def _background_task_running(host: Any, name: str) -> bool:
    checker = getattr(host, "background_task_running", None)
    if not callable(checker):
        raise RuntimeError("runtime monitor cleanup requires host.background_task_running")
    return bool(checker(name))


def _event_scope_task_run_id(anchor: dict[str, Any]) -> str:
    direct = str(anchor.get("legacy_task_run_id") or "").strip()
    if direct:
        return direct
    event_scope = str(anchor.get("event_scope_ref") or "").strip()
    if event_scope.startswith("task_run:"):
        return event_scope.removeprefix("task_run:").strip()
    return event_scope
