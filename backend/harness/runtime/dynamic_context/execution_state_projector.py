from __future__ import annotations

from typing import Any

from .models import compact_text, drop_empty


class ExecutionStateProjector:
    def project(self, execution_state: dict[str, Any] | None, *, task_run: dict[str, Any] | None = None) -> dict[str, Any]:
        state = dict(execution_state or {})
        system_projection = dict(state.get("system_projection") or {})
        task_payload = dict(task_run or {})
        diagnostics = dict(task_payload.get("diagnostics") or {})
        projected = {
            "runtime_status": _first_value(system_projection, state, diagnostics, keys=("runtime_status", "status", "executor_status")),
            "current_step": _current_step(system_projection, state, task_payload),
            "pending_user_steers": _bounded_dicts(system_projection.get("pending_user_steers"), limit=8),
            "active_contract_revisions": _bounded_dicts(system_projection.get("active_contract_revisions"), limit=8),
            "recoverable_error": _recoverable_error(system_projection, state, diagnostics),
            "validation_status": _validation_status(system_projection, state, diagnostics),
            "authority": "harness.runtime.dynamic_context.execution_state_projection",
        }
        unknown_keys = sorted(
            key for key in state.keys()
            if key not in {"system_projection", "runtime_status", "status", "step", "current_step", "recoverable_error", "validation_status", "memory_summary", "context_summary", "authority"}
        )
        if unknown_keys:
            projected["omitted_unknown_key_count"] = len(unknown_keys)
        return drop_empty(projected)

    def task_run_state(self, task_run: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(task_run or {})
        if not payload:
            return {}
        diagnostics = dict(payload.get("diagnostics") or {})
        return drop_empty(
            {
                "task_run_id": str(payload.get("task_run_id") or ""),
                "status": str(payload.get("status") or ""),
                "terminal_reason": str(payload.get("terminal_reason") or ""),
                "started_at": payload.get("started_at"),
                "updated_at": payload.get("updated_at"),
                "completed_at": payload.get("completed_at"),
                "current_step_index": payload.get("current_step_index"),
                "diagnostics": {
                    key: diagnostics.get(key)
                    for key in (
                        "executor_status",
                        "recoverable_error",
                        "recovery_action",
                        "last_error",
                        "last_observation_id",
                        "last_model_action",
                    )
                    if key in diagnostics
                },
                "authority": "orchestration.task_run.volatile_state",
            }
        )


def _first_value(*payloads: dict[str, Any], keys: tuple[str, ...]) -> str:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if str(value or "").strip():
                return compact_text(value, limit=160)
    return ""


def _current_step(system_projection: dict[str, Any], state: dict[str, Any], task_run: dict[str, Any]) -> dict[str, Any]:
    value = system_projection.get("current_step") or state.get("current_step")
    if isinstance(value, dict):
        return {
            "step_id": str(value.get("step_id") or ""),
            "title": compact_text(value.get("title") or value.get("name") or "", limit=160),
            "status": str(value.get("status") or ""),
        }
    if state.get("step") is not None:
        return {"index": state.get("step")}
    if task_run.get("current_step_index") is not None:
        return {"index": task_run.get("current_step_index")}
    return {}


def _recoverable_error(*payloads: dict[str, Any]) -> dict[str, Any]:
    for payload in payloads:
        value = payload.get("recoverable_error") or payload.get("last_error")
        if isinstance(value, dict):
            return {
                "code": compact_text(value.get("code") or value.get("error_code") or "", limit=120),
                "message": compact_text(value.get("message") or value.get("detail") or value.get("error") or "", limit=500),
                "retryable": value.get("retryable") if isinstance(value.get("retryable"), bool) else None,
            }
        if str(value or "").strip():
            return {"message": compact_text(value, limit=500)}
    return {}


def _validation_status(*payloads: dict[str, Any]) -> dict[str, Any]:
    for payload in payloads:
        value = payload.get("validation_status") or payload.get("completion_validation")
        if isinstance(value, dict):
            return {
                "status": str(value.get("status") or ""),
                "summary": compact_text(value.get("summary") or value.get("message") or "", limit=500),
            }
    return {}


def _bounded_dicts(value: Any, *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(value or [])[:limit]:
        if not isinstance(item, dict):
            continue
        result.append({str(key): item[key] for key in sorted(item) if key in _ALLOWED_STEER_KEYS or not str(key).startswith("_")})
    return result


_ALLOWED_STEER_KEYS = {
    "steer_id",
    "summary",
    "content",
    "message",
    "scope",
    "impact",
    "revision_id",
    "contract_revision_id",
    "created_at",
    "requested_by",
}
