from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from harness.loop.task_run_execution_control import ExecutorControlSignal, request_executor_control_signal
from harness.loop.work_rollout import append_work_rollout_item
from harness.task_run_status import runtime_control_state_from_task_run
from harness.runtime.dynamic_context.manager import dynamic_context_storage_root
from harness.runtime.dynamic_context.replacement_store import ReplacementStore
from core.project_layout import ProjectLayout
from runtime.cache_manager import SANDBOX_CACHE_NAMESPACE, runtime_cache_manager_for_host
from runtime_objects.tool_result_storage import ToolResultStore


TERMINAL_STATUSES = {"completed", "success", "failed", "error", "aborted", "cancelled", "canceled", "stopped"}
RETENTION_STOP_REASONS = {"blocked_expired", "runtime_retention_expired", "approval_expired"}
WAITING_STATUSES = {"blocked", "waiting_executor", "waiting_approval"}
PAUSED_CONTROL_STATES = {"pause_requested", "paused"}
STOP_CONTROL_STATES = {"stop_requested", "stopped"}
RECOVERY_ACTIONS = {"resume_task_run", "rerun_task_executor"}
DEFAULT_BLOCKED_TTL_SECONDS = 2 * 60 * 60
DEFAULT_WAITING_EXECUTOR_TTL_SECONDS = 2 * 60 * 60
DEFAULT_WAITING_APPROVAL_TTL_SECONDS = 24 * 60 * 60
DEFAULT_STOP_GRACE_SECONDS = 60


@dataclass(frozen=True, slots=True)
class TaskRunRetentionPolicy:
    blocked_ttl_seconds: float = DEFAULT_BLOCKED_TTL_SECONDS
    waiting_executor_ttl_seconds: float = DEFAULT_WAITING_EXECUTOR_TTL_SECONDS
    waiting_approval_ttl_seconds: float = DEFAULT_WAITING_APPROVAL_TTL_SECONDS
    stop_grace_seconds: float = DEFAULT_STOP_GRACE_SECONDS

    @classmethod
    def from_runtime_host(cls, runtime_host: Any) -> "TaskRunRetentionPolicy":
        raw = getattr(runtime_host, "task_run_retention_policy", None)
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            blocked_ttl_seconds=_positive_float(raw.get("blocked_ttl_seconds"), DEFAULT_BLOCKED_TTL_SECONDS),
            waiting_executor_ttl_seconds=_positive_float(raw.get("waiting_executor_ttl_seconds"), DEFAULT_WAITING_EXECUTOR_TTL_SECONDS),
            waiting_approval_ttl_seconds=_positive_float(raw.get("waiting_approval_ttl_seconds"), DEFAULT_WAITING_APPROVAL_TTL_SECONDS),
            stop_grace_seconds=_positive_float(raw.get("stop_grace_seconds"), DEFAULT_STOP_GRACE_SECONDS),
        )


class TaskRunLifecycleRetention:
    authority = "harness.runtime.task_run_lifecycle_retention"

    def __init__(self, *, runtime_host: Any, policy: TaskRunRetentionPolicy | None = None) -> None:
        self.runtime_host = runtime_host
        self.policy = policy or TaskRunRetentionPolicy.from_runtime_host(runtime_host)

    def sweep_expired_task_runs(self, *, now: float | None = None, limit: int = 240) -> dict[str, Any]:
        state_index = getattr(self.runtime_host, "state_index", None)
        if state_index is None or not callable(getattr(state_index, "update_task_run", None)):
            return self._empty_result(reason="state_index_update_unavailable")
        current_time = time.time() if now is None else float(now)
        task_runs = self._recent_task_runs_for_sweep(state_index, limit=max(1, int(limit or 240)))
        results: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for task_run in task_runs:
            decision = self._decision(task_run, now=current_time)
            task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
            if not task_run_id:
                continue
            if not decision.get("expired"):
                reason = str(decision.get("reason") or "")
                if reason:
                    skipped.append({"task_run_id": task_run_id, "reason": reason})
                continue
            if decision.get("active_claim"):
                results.append(self._request_retention_stop(task_run, now=current_time, decision=decision))
                continue
            results.append(self._finalize_expired_task_run(task_run, now=current_time, decision=decision))
        terminal_updates = [item for item in results if item.get("terminal_update")]
        stop_requests = [item for item in results if item.get("stop_requested")]
        stop_request_failures = [
            item
            for item in results
            if str(item.get("authority") or "") == f"{self.authority}.stop_request"
            and item.get("stop_requested") is False
        ]
        return {
            "authority": self.authority,
            "scanned_count": len(task_runs),
            "expired_count": len(results),
            "terminal_update_count": len(terminal_updates),
            "stop_request_count": len(stop_requests),
            "stop_request_failure_count": len(stop_request_failures),
            "expired_task_run_ids": [str(item.get("task_run_id") or "") for item in results if str(item.get("task_run_id") or "")],
            "terminal_updates": terminal_updates,
            "stop_requests": stop_requests,
            "stop_request_failures": stop_request_failures,
            "skipped_reasons": skipped[:80],
            "updated_at": current_time,
        }

    def _decision(self, task_run: Any, *, now: float) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
        status = str(getattr(task_run, "status", "") or "").strip()
        terminal_reason = str(getattr(task_run, "terminal_reason", "") or "").strip()
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        if not task_run_id:
            return {"expired": False, "reason": "missing_task_run_id"}
        if status in TERMINAL_STATUSES or terminal_reason in RETENTION_STOP_REASONS:
            return {"expired": False, "reason": "terminal"}
        if status not in WAITING_STATUSES:
            return {"expired": False, "reason": "status_not_retention_waiting"}
        if _graph_controlled(diagnostics):
            return {"expired": False, "reason": "graph_controlled"}
        control = _runtime_control(diagnostics)
        control_state = runtime_control_state_from_task_run(
            task_run,
            runtime_host=self.runtime_host,
            runtime_control=control,
        )
        if control_state in PAUSED_CONTROL_STATES:
            return {"expired": False, "reason": "paused_control_state"}
        timestamp = _last_activity_time(task_run)
        if timestamp <= 0:
            return {"expired": False, "reason": "missing_runtime_time"}
        ttl = self._ttl_for_status(status)
        age_seconds = max(0.0, now - timestamp)
        if age_seconds < ttl:
            return {"expired": False, "reason": "within_retention_ttl"}
        active_claim = self._has_active_executor_claim(task_run)
        if active_claim:
            requested_at = float(control.get("requested_at") or 0.0)
            if (
                control_state in STOP_CONTROL_STATES
                and requested_at
                and now - requested_at >= self.policy.stop_grace_seconds
            ):
                active_claim = False
            else:
                return {
                    "expired": True,
                    "active_claim": True,
                    "reason": self._terminal_reason_for_status(status),
                    "age_seconds": age_seconds,
                    "ttl_seconds": ttl,
                }
        return {
            "expired": True,
            "active_claim": False,
            "reason": self._terminal_reason_for_status(status),
            "age_seconds": age_seconds,
            "ttl_seconds": ttl,
        }

    def _ttl_for_status(self, status: str) -> float:
        if status == "waiting_approval":
            return self.policy.waiting_approval_ttl_seconds
        if status == "waiting_executor":
            return self.policy.waiting_executor_ttl_seconds
        return self.policy.blocked_ttl_seconds

    def _terminal_reason_for_status(self, status: str) -> str:
        if status == "waiting_approval":
            return "approval_expired"
        if status == "waiting_executor":
            return "runtime_retention_expired"
        return "blocked_expired"

    def _has_active_executor_claim(self, task_run: Any) -> bool:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
        session_id = str(getattr(task_run, "session_id", "") or "").strip()
        active_cell = _active_agent_cell(self.runtime_host, task_run_id, session_id=session_id)
        return active_cell is not None

    def _request_retention_stop(self, task_run: Any, *, now: float, decision: dict[str, Any]) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
        reason = str(decision.get("reason") or "runtime_retention_expired")
        control_signal = request_executor_control_signal(
            self.runtime_host,
            task_run_id=task_run_id,
            kind="stop",
            reason=reason,
            requested_by="runtime_retention",
        )
        if control_signal is None:
            return {
                "authority": f"{self.authority}.stop_request",
                "task_run_id": task_run_id,
                "reason": reason,
                "stop_requested": False,
                "executor_signal_requested": False,
                "error": "runtime_gateway_control_signal_unavailable",
                "retryable": True,
                "task_run": _to_dict(task_run),
            }
        updated = self._update_task_run_control(
            task_run_id=task_run_id,
            now=now,
            reason=reason,
            terminal=False,
            control_signal=control_signal,
        )
        return {
            "authority": f"{self.authority}.stop_request",
            "task_run_id": task_run_id,
            "reason": reason,
            "stop_requested": True,
            "executor_signal_requested": True,
            "runtime_control_signal_ref": str(getattr(control_signal, "signal_id", "") or ""),
            "runtime_control_event_ref": str(getattr(control_signal, "control_event_ref", "") or ""),
            "task_run": _to_dict(updated),
        }

    def _finalize_expired_task_run(self, task_run: Any, *, now: float, decision: dict[str, Any]) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
        terminal_reason = str(decision.get("reason") or "runtime_retention_expired")
        updated = self._update_task_run_control(
            task_run_id=task_run_id,
            now=now,
            reason=terminal_reason,
            terminal=True,
        )
        event = self._append_retention_event(updated, terminal_reason=terminal_reason, decision=decision)
        event_offset = _event_offset(event)
        if event_offset >= 0:
            updated = self._record_latest_event_offset(task_run_id=task_run_id, event_offset=event_offset) or updated
        lifecycle_ref = self._sync_lifecycle_object(updated, terminal_reason=terminal_reason, now=now)
        rollout = self._append_rollout(updated, terminal_reason=terminal_reason, event_offset=event_offset)
        active_turn = self._complete_active_turn(updated, terminal_reason=terminal_reason)
        cell_cancel = self._cancel_active_cell(task_run=updated, reason=terminal_reason)
        release = EphemeralRuntimeCacheReleaser(runtime_host=self.runtime_host).release_task_run(
            task_run_id=task_run_id,
            reason=terminal_reason,
        )
        return {
            "authority": f"{self.authority}.terminal_update",
            "task_run_id": task_run_id,
            "terminal_reason": terminal_reason,
            "terminal_update": True,
            "task_run": _to_dict(updated),
            "event": _to_dict(event),
            "lifecycle_ref": lifecycle_ref,
            "work_rollout": _to_dict(rollout),
            "active_turn": _to_dict(active_turn),
            "cell_cancel": cell_cancel,
            "released_cache_effects": release,
        }

    def _update_task_run_control(
        self,
        *,
        task_run_id: str,
        now: float,
        reason: str,
        terminal: bool,
        control_signal: ExecutorControlSignal | None = None,
    ) -> Any | None:
        state_index = self.runtime_host.state_index

        def updater(current: Any) -> Any:
            diagnostics = _retention_diagnostics(
                current,
                now=now,
                reason=reason,
                terminal=terminal,
                control_signal=control_signal,
            )
            patch = {
                "updated_at": now,
                "diagnostics": diagnostics,
            }
            if terminal:
                patch.update({"status": "aborted", "terminal_reason": reason})
            return _replace_task_run(current, **patch)

        return state_index.update_task_run(task_run_id, updater)

    def _record_latest_event_offset(self, *, task_run_id: str, event_offset: int) -> Any | None:
        def updater(current: Any) -> Any:
            return _replace_task_run(current, latest_event_offset=int(event_offset))

        return self.runtime_host.state_index.update_task_run(task_run_id, updater)

    def _append_retention_event(self, task_run: Any, *, terminal_reason: str, decision: dict[str, Any]) -> Any:
        event_log = getattr(self.runtime_host, "event_log", None)
        append = getattr(event_log, "append", None)
        if not callable(append):
            return {}
        return append(
            str(getattr(task_run, "task_run_id", "") or ""),
            "task_run_lifecycle_retention_stopped",
            payload={
                "task_run": _to_dict(task_run),
                "terminal_reason": terminal_reason,
                "retention_decision": dict(decision),
                "authority": f"{self.authority}.event",
            },
            refs={"task_run_ref": str(getattr(task_run, "task_run_id", "") or "")},
        )

    def _sync_lifecycle_object(self, task_run: Any, *, terminal_reason: str, now: float) -> str:
        runtime_objects = getattr(self.runtime_host, "runtime_objects", None)
        if runtime_objects is None:
            return ""
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        ref = f"rtobj:task_lifecycle:{task_run_id}"
        try:
            payload = dict(runtime_objects.get_object(ref) or {})
        except Exception:
            payload = {}
        payload = {
            **payload,
            "task_run_id": task_run_id,
            "contract_ref": str(payload.get("contract_ref") or getattr(task_run, "task_contract_ref", "") or ""),
            "status": "aborted",
            "created_at": float(payload.get("created_at") or getattr(task_run, "created_at", 0.0) or now),
            "updated_at": now,
            "terminal_reason": terminal_reason,
            "authority": "harness.loop.task_lifecycle",
        }
        try:
            return str(runtime_objects.put_object("task_lifecycle", task_run_id, payload))
        except Exception:
            return ""

    def _append_rollout(self, task_run: Any, *, terminal_reason: str, event_offset: int) -> Any:
        try:
            return append_work_rollout_item(
                self.runtime_host,
                task_run=task_run,
                item_type="interrupted_boundary",
                title="已停止",
                status="aborted",
                summary="运行状态长时间停留在阻塞/等待，已停止该旧任务并释放临时运行缓存。",
                event_offset=event_offset,
                refs={"task_run_ref": str(getattr(task_run, "task_run_id", "") or "")},
                payload={"terminal_reason": terminal_reason, "model_visible": False},
            )
        except Exception:
            return {}

    def _complete_active_turn(self, task_run: Any, *, terminal_reason: str) -> Any:
        active_turn_registry = getattr(self.runtime_host, "active_turn_registry", None)
        complete = getattr(active_turn_registry, "complete_bound_task", None)
        if not callable(complete):
            return {}
        try:
            return complete(
                session_id=str(getattr(task_run, "session_id", "") or ""),
                task_run_id=str(getattr(task_run, "task_run_id", "") or ""),
                terminal_reason=terminal_reason,
            )
        except Exception:
            return {}

    def _cancel_active_cell(self, *, task_run: Any, reason: str) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
        session_id = str(getattr(task_run, "session_id", "") or "").strip()
        supervisor = getattr(self.runtime_host, "agent_run_supervisor", None)
        if supervisor is None or not task_run_id or not session_id:
            return {
                "authority": f"{self.authority}.cell_cancel",
                "cancelled": False,
                "reason": "cell_cancel_scope_unavailable",
                "task_run_id": task_run_id,
                "session_id": session_id,
            }
        cancelled = bool(supervisor.cancel_task_run(task_run_id, session_id=session_id, reason=reason))
        return {
            "authority": f"{self.authority}.cell_cancel",
            "cancelled": cancelled,
            "task_run_id": task_run_id,
            "session_id": session_id,
        }

    def _empty_result(self, *, reason: str) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "scanned_count": 0,
            "expired_count": 0,
            "terminal_update_count": 0,
            "stop_request_count": 0,
            "stop_request_failure_count": 0,
            "expired_task_run_ids": [],
            "terminal_updates": [],
            "stop_requests": [],
            "stop_request_failures": [],
            "skipped_reasons": [{"reason": reason}],
            "updated_at": time.time(),
        }

    def _recent_task_runs_for_sweep(self, state_index: Any, *, limit: int) -> list[Any]:
        return list(state_index.list_recent_task_run_summaries(limit=limit) or [])


class EphemeralRuntimeCacheReleaser:
    authority = "harness.runtime.ephemeral_runtime_cache_releaser"

    def __init__(self, *, runtime_host: Any) -> None:
        self.runtime_host = runtime_host

    def release_task_run(self, *, task_run_id: str, reason: str) -> dict[str, Any]:
        normalized = str(task_run_id or "").strip()
        if not normalized:
            return {"authority": self.authority, "released": False, "reason": "missing_task_run_id"}
        effects: dict[str, Any] = {
            "authority": self.authority,
            "task_run_id": normalized,
            "reason": str(reason or ""),
        }
        effects["tool_invocation_control"] = self._cancel_tool_invocations(normalized, reason=reason)
        effects["file_state"] = self._prune_file_state(normalized)
        effects["runtime_cache"] = self._delete_runtime_cache(normalized, reason=reason)
        effects["dynamic_context"] = self._prune_dynamic_context(normalized)
        return effects

    def _cancel_tool_invocations(self, task_run_id: str, *, reason: str) -> dict[str, Any]:
        try:
            from runtime.tool_runtime.tool_invocation_control import registry_for

            registry = registry_for(self.runtime_host)
            scope = _task_run_agent_scope(self.runtime_host, task_run_id)
            count = registry.cancel_by_caller(
                task_run_id=task_run_id,
                agent_run_id=str(scope.get("agent_run_id") or ""),
                run_cell_id=str(scope.get("run_cell_id") or ""),
                kind="cancel",
                reason=reason or "runtime_retention_expired",
                requested_by="runtime_retention",
            ) if registry is not None else 0
            return {
                "authority": "runtime.tool_invocation_control.cancel_by_caller",
                "cancelled_count": count,
                "agent_run_id": str(scope.get("agent_run_id") or ""),
                "run_cell_id": str(scope.get("run_cell_id") or ""),
            }
        except Exception as exc:
            return {"authority": "runtime.tool_invocation_control.cancel_by_caller", "error": str(exc)}

    def _prune_file_state(self, task_run_id: str) -> dict[str, Any]:
        store = getattr(self.runtime_host, "file_state_store", None)
        pruner = getattr(store, "prune_task_runs", None)
        if not callable(pruner):
            return {"authority": "runtime.memory.file_state_store.prune_task_runs", "deleted_count": 0, "reason": "store_unavailable"}
        try:
            return dict(pruner({task_run_id}) or {})
        except Exception as exc:
            return {"authority": "runtime.memory.file_state_store.prune_task_runs", "error": str(exc)}

    def _delete_runtime_cache(self, task_run_id: str, *, reason: str) -> dict[str, Any]:
        try:
            manager = runtime_cache_manager_for_host(self.runtime_host)
            return manager.delete_cache_entry(
                namespace=SANDBOX_CACHE_NAMESPACE,
                cache_key=task_run_id,
                reason=reason or "runtime_retention_expired",
                dry_run=False,
                measure_size=False,
                defer_delete=True,
            )
        except Exception as exc:
            return {"authority": "runtime.cache_manager.delete_cache_entry", "error": str(exc)}

    def _prune_dynamic_context(self, task_run_id: str) -> dict[str, Any]:
        effects: list[dict[str, Any]] = []
        seen_roots: set[str] = set()
        for root in self._candidate_dynamic_context_roots(task_run_id):
            resolved = str(root.resolve())
            if resolved in seen_roots:
                continue
            seen_roots.add(resolved)
            effects.append(self._prune_dynamic_context_root(root, task_run_id))
        return {
            "authority": "harness.runtime.dynamic_context.prune_task_runs",
            "root_count": len(effects),
            "effects": effects,
            "deleted_count": sum(int(item.get("replacement_store", {}).get("deleted_count") or 0) for item in effects),
        }

    def _candidate_dynamic_context_roots(self, task_run_id: str) -> list[Path]:
        roots: list[Path] = []
        root_dir = getattr(self.runtime_host, "root_dir", None)
        if root_dir is not None:
            roots.append(Path(root_dir))
        task_run = getattr(getattr(self.runtime_host, "state_index", None), "get_task_run", lambda _: None)(task_run_id)
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {}) if task_run is not None else {}
        runtime_assembly = dict(diagnostics.get("runtime_assembly") or {})
        if runtime_assembly:
            try:
                resolved = dynamic_context_storage_root(Path(getattr(self.runtime_host, "backend_dir", ".") or "."), runtime_assembly)
                if resolved is not None:
                    roots.append(Path(resolved))
            except Exception:
                pass
        backend_dir = getattr(self.runtime_host, "backend_dir", None)
        if backend_dir is not None:
            roots.append(ProjectLayout.from_backend_dir(Path(backend_dir)).runtime_state_dir)
        return roots

    def _prune_dynamic_context_root(self, root: Path, task_run_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "authority": "harness.runtime.dynamic_context.prune_task_run_root",
            "root": str(root),
        }
        try:
            result["replacement_store"] = ReplacementStore(root).prune_task_runs({task_run_id})
        except Exception as exc:
            result["replacement_store"] = {"error": str(exc)}
        try:
            result["tool_results"] = ToolResultStore.prune_task_runs(root, {task_run_id})
        except Exception as exc:
            result["tool_results"] = {"error": str(exc)}
        return result


def _control_signal_trace_payload(signal: ExecutorControlSignal | None) -> dict[str, str]:
    if signal is None:
        return {}
    signal_ref = str(getattr(signal, "signal_id", "") or "").strip()
    if not signal_ref:
        return {}
    event_ref = str(getattr(signal, "control_event_ref", "") or "").strip()
    return {
        "runtime_control_signal_ref": signal_ref,
        **({"runtime_control_event_ref": event_ref} if event_ref else {}),
    }


def _retention_diagnostics(
    task_run: Any,
    *,
    now: float,
    reason: str,
    terminal: bool,
    control_signal: ExecutorControlSignal | None = None,
) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = {
        "state": "stopped" if terminal else "stop_requested",
        "requested_by": "runtime_retention",
        "requested_at": now,
        "reason": reason,
        "authority": "harness.runtime.task_run_lifecycle_retention",
        **_control_signal_trace_payload(control_signal),
    }
    for key in (
        "recoverable_error",
        "recovery_action",
        "pending_user_steer_count",
        "latest_user_steer_ref",
        "active_contract_revision_count",
        "latest_contract_revision_ref",
    ):
        diagnostics.pop(key, None)
    if terminal:
        pending_approval = diagnostics.get("pending_approval")
        if isinstance(pending_approval, dict):
            diagnostics["pending_approval"] = {
                **dict(pending_approval),
                "status": "expired",
                "expired_at": now,
                "expired_reason": reason,
            }
    return {
        **diagnostics,
        "runtime_control": control,
        "executor_status": "stopped" if terminal else str(diagnostics.get("executor_status") or "stop_requested"),
        "task_retention": {
            "authority": "harness.runtime.task_run_lifecycle_retention",
            "terminal": bool(terminal),
            "reason": reason,
            "applied_at": now,
        },
        "latest_step": "task_run_retention_stopped" if terminal else "task_run_retention_stop_requested",
        "latest_step_status": "aborted" if terminal else "running",
        "latest_step_summary": (
            "运行状态长时间停留在阻塞/等待，已停止该旧任务并释放临时运行缓存。"
            if terminal
            else "运行状态长时间停留在阻塞/等待，已请求当前执行器停止。"
        ),
    }


def _runtime_control(diagnostics: dict[str, Any]) -> dict[str, Any]:
    control = diagnostics.get("runtime_control")
    return dict(control) if isinstance(control, dict) else {}


def _last_activity_time(task_run: Any) -> float:
    values = [
        getattr(task_run, "updated_at", 0.0),
        getattr(task_run, "created_at", 0.0),
    ]
    parsed = []
    for value in values:
        try:
            parsed.append(float(value or 0.0))
        except (TypeError, ValueError):
            parsed.append(0.0)
    return max(parsed)


def _graph_controlled(diagnostics: dict[str, Any]) -> bool:
    origin = diagnostics.get("origin")
    origin_kind = str(diagnostics.get("origin_kind") or dict(origin or {}).get("origin_kind") or "").strip() if isinstance(origin, dict) else str(diagnostics.get("origin_kind") or "").strip()
    return bool(
        origin_kind == "graph_node_assigned"
        or diagnostics.get("graph_run_id")
        or diagnostics.get("graph_harness_config_id")
        or diagnostics.get("graph_node_id")
    )


def _active_agent_cell(runtime_host: Any, task_run_id: str, *, session_id: str = "") -> Any | None:
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    if supervisor is None:
        return None
    active_cell = getattr(supervisor, "active_cell_for_task_run", None)
    if not callable(active_cell):
        return None
    return active_cell(str(task_run_id or "").strip(), session_id=str(session_id or "").strip())


def _task_run_agent_scope(runtime_host: Any, task_run_id: str) -> dict[str, str]:
    task_run = getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _: None)(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {}) if task_run is not None else {}
    scope = diagnostics.get("agent_run_scope")
    scope_payload = dict(scope or {}) if isinstance(scope, dict) else {}
    return {
        "agent_run_id": str(scope_payload.get("agent_run_id") or diagnostics.get("agent_run_id") or "").strip(),
        "run_cell_id": str(scope_payload.get("run_cell_id") or diagnostics.get("run_cell_id") or "").strip(),
    }


def _replace_task_run(task_run: Any, **patch: Any) -> Any:
    try:
        return replace(task_run, **patch)
    except TypeError:
        payload = dict(vars(task_run))
        payload.update(patch)
        return SimpleNamespace(**payload)


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            return dict(value.to_dict())
        except Exception:
            return {}
    try:
        return dict(vars(value))
    except Exception:
        return {}


def _event_offset(event: Any) -> int:
    try:
        if isinstance(event, dict):
            return int(event.get("offset", -1))
        return int(getattr(event, "offset", -1))
    except (TypeError, ValueError):
        return -1


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(1.0, parsed)

