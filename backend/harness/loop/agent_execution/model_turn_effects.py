from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeEventEffect:
    event_type: str
    result_ref: str = ""
    observation_ref: str = ""
    observation: dict[str, Any] | None = None
    observation_payload: dict[str, Any] | None = None
    approval_state: dict[str, Any] | None = None
    operation_id: str = ""
    runtime_error: str = ""
    runtime_error_observation: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RawModelEventEffect:
    event_type: str
    final_content: str = ""
    final_answer_metadata: dict[str, Any] | None = None
    terminal_reason: str = ""
    should_yield: bool = True


def classify_runtime_event(runtime_event: Any) -> RuntimeEventEffect:
    event_type = str(getattr(runtime_event, "event_type", "") or "")
    refs = dict(getattr(runtime_event, "refs", {}) or {})
    payload = dict(getattr(runtime_event, "payload", {}) or {})
    if event_type == "executor_observation_received":
        observation_ref = str(refs.get("observation_ref") or getattr(runtime_event, "event_id", "") or "")
        observation = dict(payload.get("observation") or {})
        return RuntimeEventEffect(
            event_type=event_type,
            result_ref=observation_ref,
            observation_ref=observation_ref,
            observation=observation,
            observation_payload=dict(observation.get("payload") or {}),
        )
    if event_type == "approval_waiting":
        return RuntimeEventEffect(
            event_type=event_type,
            approval_state=dict(payload.get("approval") or {}),
        )
    if event_type == "output_boundary_applied":
        return RuntimeEventEffect(
            event_type=event_type,
            result_ref=f"output_boundary:{getattr(runtime_event, 'event_id', '')}",
        )
    if event_type == "commit_gate_checked":
        commit_ref = str(
            refs.get("commit_gate_ref")
            or dict(payload.get("commit_gate") or {}).get("gate_id")
            or getattr(runtime_event, "event_id", "")
        )
        return RuntimeEventEffect(
            event_type=event_type,
            result_ref=f"commit_gate:{commit_ref}" if commit_ref else "",
        )
    if event_type == "tool_call_requested":
        return RuntimeEventEffect(
            event_type=event_type,
            operation_id=str(refs.get("operation_id") or ""),
        )
    if event_type == "loop_error":
        observation = dict(payload.get("observation") or {})
        return RuntimeEventEffect(
            event_type=event_type,
            runtime_error=str(payload.get("error") or "executor_failed"),
            runtime_error_observation=observation,
        )
    return RuntimeEventEffect(event_type=event_type)


def classify_raw_model_event(
    event: dict[str, Any],
    *,
    current_final_content: str = "",
    current_answer_metadata: dict[str, Any] | None = None,
    preserve_answer_metadata: bool = False,
    merge_existing_metadata: bool = False,
) -> RawModelEventEffect:
    event_type = str(event.get("type") or "")
    if event_type == "done":
        metadata = dict(current_answer_metadata or {})
        if not preserve_answer_metadata:
            metadata = answer_metadata_from_done_event(
                event,
                existing_metadata=metadata,
                merge_existing=merge_existing_metadata,
            )
        return RawModelEventEffect(
            event_type=event_type,
            final_content=str(event.get("content") or (current_final_content if merge_existing_metadata else "")),
            final_answer_metadata=metadata,
            should_yield=False,
        )
    if event_type == "error":
        return RawModelEventEffect(
            event_type=event_type,
            terminal_reason="executor_failed",
            should_yield=True,
        )
    return RawModelEventEffect(event_type=event_type, should_yield=True)


def answer_metadata_from_done_event(
    event: dict[str, Any],
    *,
    existing_metadata: dict[str, Any] | None = None,
    merge_existing: bool = False,
) -> dict[str, Any]:
    existing = dict(existing_metadata or {})

    def value(key: str) -> str:
        raw = event.get(key)
        if merge_existing and (raw is None or str(raw) == ""):
            raw = existing.get(key)
        return str(raw or "")

    metadata = {
        "answer_channel": value("answer_channel"),
        "answer_source": value("answer_source"),
        "answer_canonical_state": value("answer_canonical_state"),
        "answer_persist_policy": value("answer_persist_policy"),
        "answer_finalization_policy": value("answer_finalization_policy"),
        "answer_fallback_reason": value("answer_fallback_reason"),
        "completion_state": value("completion_state"),
        "terminal_reason": value("terminal_reason"),
        "timeout_seconds": value("timeout_seconds"),
        "partial_delta_count": value("partial_delta_count"),
    }
    for key in ("completion", "run_outcome"):
        payload = event.get(key)
        if not isinstance(payload, dict) and merge_existing:
            payload = existing.get(key)
        if isinstance(payload, dict):
            metadata[key] = dict(payload)
    return metadata
