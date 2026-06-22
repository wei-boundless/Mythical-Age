from __future__ import annotations

from typing import Any

from .models import compact_text, drop_empty


COMPRESSED_CONTEXT_PREFIX = "[Compressed session context]"


class HistoryProjector:
    def project(
        self,
        history: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        current_user_message: str = "",
        session_context: dict[str, Any] | None = None,
        projection_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = dict(projection_policy or {})
        session_payload = _session_context_projection(
            session_context,
            context_recovery_package_chars=int(policy.get("context_recovery_package_chars") or 4000),
        )
        pinned_facts = _session_emphasis_projection(session_context)
        normalized = [
            _normalize_message(item)
            for item in list(history or [])
            if isinstance(item, dict) and not _is_compressed_context_message(item)
        ]
        normalized = [item for item in normalized if item]
        payload = {
            "session_context": session_payload,
            "pinned_facts": pinned_facts,
            "active_history": normalized,
            "active_tool_trajectory": _tool_trajectory(
                normalized,
                limit=int(policy.get("tool_trajectory_limit") or 8),
                result_preview_chars=int(policy.get("tool_trajectory_result_chars") or 300),
            ),
            "current_user_message_ref": "volatile_current_request" if str(current_user_message or "").strip() else "",
            "authority": "harness.runtime.dynamic_context.history_projection",
        }
        return drop_empty(payload)


def _normalize_message(item: dict[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or item.get("type") or "user")
    content = str(item.get("content") or item.get("text") or "")
    payload = {
        "role": role,
        "content": content,
    }
    for key in ("id", "message_id", "turn_id"):
        value = str(item.get(key) or "").strip()
        if value:
            payload[key] = value
    for key in ("created_at", "updated_at", "timestamp"):
        value = _positive_float(item.get(key))
        if value > 0:
            payload[key] = value
    if item.get("tool_call_id"):
        payload["tool_call_id"] = str(item.get("tool_call_id") or "")
    if item.get("tool_calls"):
        payload["tool_calls"] = item.get("tool_calls")
    return drop_empty(payload)


def _positive_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _session_context_projection(session_context: dict[str, Any] | None, *, context_recovery_package_chars: int) -> dict[str, Any]:
    payload = dict(session_context or {})
    context_recovery_package = _context_recovery_package_projection(
        payload,
        limit=max(1000, int(context_recovery_package_chars or 4000)),
    )
    recent_work_outcome = _recent_work_outcome_projection(payload.get("recent_work_outcome"))
    return drop_empty(
        {
            "context_recovery_package": context_recovery_package,
            "recent_work_outcome": recent_work_outcome,
            "authority": "harness.runtime.dynamic_context.session_context_projection" if context_recovery_package or recent_work_outcome else "",
        }
    )


def _context_recovery_package_projection(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
    package = payload.get("context_recovery_package")
    if isinstance(package, dict) and package:
        projected = dict(package)
        coverage = projected.get("coverage")
        freshness = projected.get("freshness")
        return drop_empty(
            {
                **projected,
                "coverage": dict(coverage) if isinstance(coverage, dict) else {},
                "freshness": dict(freshness) if isinstance(freshness, dict) else {},
                "authority": str(projected.get("authority") or "runtime.context_management.context_recovery_package"),
            }
        )
    compressed_context = compact_text(payload.get("compressed_context") or "", limit=limit)
    if not compressed_context:
        return {}
    return {
        "content": compressed_context,
        "format": "markdown",
        "source": "session_record.compressed_context",
        "authority": "runtime.context_management.context_recovery_package",
    }


def _session_emphasis_projection(session_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = dict(session_context or {})
    items = payload.get("session_emphasis")
    if not isinstance(items, list):
        return []
    projected: list[dict[str, Any]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        content = compact_text(item.get("content") or "", limit=600)
        if not content:
            continue
        projected.append(
            drop_empty(
                {
                    "fact_id": compact_text(item.get("fact_id") or item.get("emphasis_id") or "", limit=120),
                    "kind": "session_emphasis",
                    "content": content,
                    "scope": compact_text(item.get("scope") or "", limit=80),
                    "priority": compact_text(item.get("priority") or "", limit=40),
                    "source_message_ref": compact_text(item.get("source_message_ref") or "", limit=120),
                    "task_environment_id": compact_text(item.get("task_environment_id") or "", limit=120),
                    "authority": "memory_system.session_emphasis",
                }
            )
        )
    return projected


def _recent_work_outcome_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    artifact_refs = [
        {
            "path": compact_text(item.get("path") or item.get("artifact_path") or item.get("ref") or "", limit=240),
            "kind": compact_text(item.get("kind") or item.get("artifact_kind") or "", limit=80),
        }
        for item in list(value.get("artifact_refs") or [])
        if isinstance(item, dict)
    ][:6]
    return drop_empty(
        {
            "task_run_id": compact_text(value.get("task_run_id") or "", limit=240),
            "status": compact_text(value.get("status") or "", limit=80),
            "terminal_reason": compact_text(value.get("terminal_reason") or "", limit=160),
            "lifecycle": compact_text(value.get("lifecycle") or "", limit=80),
            "user_visible_goal": compact_text(value.get("user_visible_goal") or "", limit=900),
            "latest_progress": compact_text(value.get("latest_progress") or "", limit=900),
            "latest_step_name": compact_text(value.get("latest_step_name") or "", limit=120),
            "latest_step_status": compact_text(value.get("latest_step_status") or "", limit=80),
            "latest_event_type": compact_text(value.get("latest_event_type") or "", limit=120),
            "agent_brief_output": compact_text(value.get("agent_brief_output") or "", limit=900),
            "artifact_refs": artifact_refs,
            "continuation_state": compact_text(value.get("continuation_state") or "", limit=120),
            "decision_boundary": compact_text(value.get("decision_boundary") or "", limit=500),
            "boundary_code": "recent_work_outcome_read_only_fact",
            "authority": "harness.runtime.dynamic_context.recent_work_outcome_projection",
        }
    )


def _is_compressed_context_message(item: dict[str, Any]) -> bool:
    content = str(item.get("content") or item.get("text") or "")
    return content.startswith(COMPRESSED_CONTEXT_PREFIX)


def _tool_trajectory(messages: list[dict[str, Any]], *, limit: int, result_preview_chars: int) -> list[dict[str, Any]]:
    trajectory: list[dict[str, Any]] = []
    for item in messages:
        if item.get("tool_calls"):
            trajectory.append(
                {
                    "role": str(item.get("role") or "assistant"),
                    "tool_calls": item.get("tool_calls"),
                }
            )
        elif str(item.get("role") or "") == "tool" or item.get("tool_call_id"):
            trajectory.append(
                {
                    "role": "tool",
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                    "result_preview": compact_text(
                        item.get("content") or "",
                        limit=max(120, int(result_preview_chars or 300)),
                    ),
                }
            )
    return trajectory[-max(1, int(limit or 8)):]
