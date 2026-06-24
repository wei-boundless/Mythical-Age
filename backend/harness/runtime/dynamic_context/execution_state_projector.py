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
            "current_facts": _bounded_dicts(system_projection.get("current_facts"), limit=12),
            "artifact_evidence": _bounded_dicts(system_projection.get("artifact_evidence"), limit=20),
            "active_failures": _bounded_dicts(system_projection.get("active_failures"), limit=8),
            "historical_failures": _bounded_dicts(system_projection.get("historical_failures"), limit=8),
            "repair_focus": _bounded_dicts(system_projection.get("repair_focus"), limit=8),
            "file_state": _bounded_dicts(system_projection.get("file_state"), limit=20),
            "file_state_source": compact_text(system_projection.get("file_state_source") or "", limit=160),
            "last_action_receipts": _bounded_dicts(system_projection.get("last_action_receipts"), limit=12),
            "pending_user_steers": _bounded_dicts(system_projection.get("pending_user_steers"), limit=8),
            "active_contract_revisions": _bounded_dicts(system_projection.get("active_contract_revisions"), limit=8),
            "turn_to_task_context_handoff": _compact_handoff(system_projection.get("turn_to_task_context_handoff")),
            "exploration_advisory": _exploration_advisory(system_projection.get("exploration_advisory")),
            "recoverable_error": _recoverable_error(system_projection, state, diagnostics),
            "validation_status": _validation_status(system_projection, state, diagnostics),
            "authority": "harness.runtime.dynamic_context.execution_state_projection",
        }
        unknown_keys = sorted(
            key for key in state.keys()
            if key not in {"system_projection", "runtime_status", "status", "step", "current_step", "recoverable_error", "validation_status", "memory_summary", "context_summary", "file_state", "turn_to_task_context_handoff", "authority"}
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
                "status": str(payload.get("status") or ""),
                "terminal_reason": str(payload.get("terminal_reason") or ""),
                "started_at": payload.get("started_at"),
                "updated_at": payload.get("updated_at"),
                "completed_at": payload.get("completed_at"),
                "current_step_index": payload.get("current_step_index"),
                "primary_work_mode_instance_id": str(diagnostics.get("primary_work_mode_instance_id") or ""),
                "active_work_mode_refs": [
                    str(item)
                    for item in list(diagnostics.get("active_work_mode_refs") or [])
                    if str(item).strip()
                ],
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


def _exploration_advisory(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    recent_tools = []
    for item in list(value.get("recent_tools") or [])[-8:]:
        if not isinstance(item, dict):
            continue
        recent_tools.append(
            drop_empty(
                {
                    "observation_ref": str(item.get("observation_ref") or ""),
                    "tool_name": str(item.get("tool_name") or ""),
                    "status": str(item.get("status") or ""),
                    "path": compact_text(item.get("path") or "", limit=300),
                    "summary": compact_text(item.get("summary") or "", limit=180),
                }
            )
        )
    return drop_empty(
        {
            "triggered": value.get("triggered") if isinstance(value.get("triggered"), bool) else None,
            "kind": compact_text(value.get("kind") or "", limit=120),
            "authority_boundary": compact_text(value.get("authority_boundary") or "", limit=120),
            "consecutive_exploration_tool_calls": value.get("consecutive_exploration_tool_calls"),
            "threshold": value.get("threshold"),
            "recent_tools": recent_tools,
            "decision_questions": [compact_text(item, limit=180) for item in list(value.get("decision_questions") or [])[:4] if str(item).strip()],
            "non_blocking": value.get("non_blocking") if isinstance(value.get("non_blocking"), bool) else None,
            "authority": compact_text(value.get("authority") or "", limit=160),
        }
    )


def _compact_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    return drop_empty(
        {
            "handoff_id": compact_text(value.get("handoff_id") or "", limit=160),
            "turn_id": compact_text(value.get("turn_id") or "", limit=160),
            "task_run_id": compact_text(value.get("task_run_id") or "", limit=180),
            "source_packet_ref": compact_text(value.get("source_packet_ref") or "", limit=260),
            "inherited_observation_refs": [compact_text(item, limit=220) for item in list(value.get("inherited_observation_refs") or [])[:12]],
            "inherited_observation_count": value.get("inherited_observation_count"),
            "inherited_file_state_count": value.get("inherited_file_state_count"),
            "inherited_memory_context_refs": {
                str(key): compact_text(item, limit=220)
                for key, item in dict(value.get("inherited_memory_context_refs") or {}).items()
                if str(item).strip()
            },
            "selected_memory_sections": [compact_text(item, limit=120) for item in list(value.get("selected_memory_sections") or [])[:8]],
            "authority": compact_text(value.get("authority") or "harness.loop.turn_to_task_context_handoff", limit=160),
        }
    )


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
