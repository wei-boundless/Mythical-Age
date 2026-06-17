from __future__ import annotations

from typing import Any

from .queued_user_input_store import QueuedUserInput


def queued_input_admission_target(runtime_host: Any, *, session_id: str) -> dict[str, str]:
    active_turn = _resolve_active_turn(runtime_host, session_id)
    turn_id = str(getattr(active_turn, "turn_id", "") or "").strip() if active_turn is not None else ""
    task_run_id = str(getattr(active_turn, "bound_task_run_id", "") or "").strip() if active_turn is not None else ""
    steerable = bool(getattr(active_turn, "steerable", False)) if active_turn is not None else False
    if turn_id and task_run_id and steerable:
        return {
            "input_policy": "steer",
            "expected_active_turn_id": turn_id,
            "task_run_id": task_run_id,
            "authority": "runtime.queued_user_input_dispatcher.admission_target",
        }
    return {
        "input_policy": "auto",
        "expected_active_turn_id": "",
        "task_run_id": "",
        "authority": "runtime.queued_user_input_dispatcher.admission_target",
    }


def has_active_primary_chat_run(runtime_host: Any, *, session_id: str, terminal_statuses: set[str]) -> bool:
    for run in _active_session_runs(runtime_host, session_id=session_id, terminal_statuses=terminal_statuses):
        if not _is_steer_run(run):
            return True
    return False


def has_active_steer_chat_run(
    runtime_host: Any,
    *,
    session_id: str,
    terminal_statuses: set[str],
    expected_active_turn_id: str = "",
) -> bool:
    expected = str(expected_active_turn_id or "").strip()
    for run in _active_session_runs(runtime_host, session_id=session_id, terminal_statuses=terminal_statuses):
        if not _is_steer_run(run):
            continue
        if not expected:
            return True
        diagnostics = dict(getattr(run, "diagnostics", {}) or {})
        if str(diagnostics.get("expected_active_turn_id") or "").strip() == expected:
            return True
    return False


def validate_queued_steer(runtime_host: Any, item: QueuedUserInput) -> tuple[bool, str]:
    active_turn = _resolve_active_turn(runtime_host, item.session_id)
    if active_turn is None:
        return False, "active_turn_unavailable"
    actual_turn_id = str(getattr(active_turn, "turn_id", "") or "").strip()
    actual_task_run_id = str(getattr(active_turn, "bound_task_run_id", "") or "").strip()
    expected_turn_id = str(item.expected_active_turn_id or "").strip()
    expected_task_run_id = str(item.task_run_id or "").strip()
    if expected_turn_id and actual_turn_id != expected_turn_id:
        return False, "expected_active_turn_mismatch"
    if expected_task_run_id and actual_task_run_id != expected_task_run_id:
        return False, "expected_task_run_mismatch"
    if not actual_task_run_id:
        return False, "active_turn_not_bound_to_task"
    if not bool(getattr(active_turn, "steerable", False)):
        return False, "active_turn_not_steerable"
    return True, ""


def _active_session_runs(runtime_host: Any, *, session_id: str, terminal_statuses: set[str]) -> list[Any]:
    registry = getattr(runtime_host, "run_registry", None)
    if registry is None or not callable(getattr(registry, "list_session_runs", None)):
        return []
    normalized = str(session_id or "").strip()
    runs: list[Any] = []
    for run in list(registry.list_session_runs(normalized) or []):
        status = str(getattr(run, "status", "") or "").strip()
        if status and status not in set(terminal_statuses or set()):
            runs.append(run)
    return runs


def _is_steer_run(run: Any) -> bool:
    diagnostics = dict(getattr(run, "diagnostics", {}) or {})
    expected_active_turn_id = str(diagnostics.get("expected_active_turn_id") or "").strip()
    policy = str(diagnostics.get("active_turn_input_policy") or "").strip().lower()
    return bool(expected_active_turn_id and policy == "steer")


def _resolve_active_turn(runtime_host: Any, session_id: str) -> Any | None:
    active_turn_registry = getattr(runtime_host, "active_turn_registry", None)
    resolver = getattr(active_turn_registry, "resolve_current", None)
    if not callable(resolver):
        return None
    try:
        return resolver(str(session_id or "").strip())
    except Exception:
        return None
