from __future__ import annotations

from typing import Any, Callable

from runtime.shared.execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)


def prepare_tool_execution(
    *,
    task_run_id: str,
    step_id: str,
    action_request: Any,
    directive_ref: str,
    operation_id: str,
    descriptor: Any,
    tool_name: str,
    execution_store: RuntimeExecutionStore,
    record_execution_event: Callable[..., Any],
) -> tuple[OperationExecutionRecord, list[Any], str]:
    request_fingerprint = build_request_fingerprint(
        step_id=step_id,
        operation_id=operation_id,
        payload=dict(action_request.payload or {}),
    )
    idempotency_token = build_idempotency_token(
        task_run_id=task_run_id,
        step_id=step_id,
        operation_id=operation_id,
        request_fingerprint=request_fingerprint,
    )
    replay_policy = derive_replay_policy(descriptor)
    existing = execution_store.find_by_fingerprint(
        task_run_id=task_run_id,
        step_id=step_id,
        operation_id=operation_id,
        request_fingerprint=request_fingerprint,
    )
    record = execution_store.create_record(
        task_run_id=task_run_id,
        step_id=step_id,
        action_request=action_request,
        directive_ref=directive_ref,
        operation_id=operation_id,
        executor_type="tool",
        replay_policy=replay_policy,
        request_fingerprint=request_fingerprint,
        idempotency_token=idempotency_token,
        diagnostics={"tool_name": tool_name},
    )
    events = [
        record_execution_event(
            task_run_id,
            event_type="execution_record_created",
            record=record,
            reason="tool_call_requested",
        )
    ]
    if existing is None or existing.execution_id == record.execution_id:
        return record, events, "dispatch"
    if replay_policy == "reuse_completed_result" and existing.status in {"completed", "reused_completed_result"}:
        record = execution_store.mark_reused(
            record,
            result_ref=existing.result_ref,
            result_payload=dict(existing.result_payload or {}),
            diagnostics={"source_execution_id": existing.execution_id},
        )
        events.append(
            record_execution_event(
                task_run_id,
                event_type="recovery_replay_decided",
                record=record,
                reason="reuse_completed_result",
                diagnostics={"source_execution_id": existing.execution_id},
            )
        )
        events.append(
            record_execution_event(
                task_run_id,
                event_type="execution_result_reused",
                record=record,
                reason="reuse_completed_result",
                diagnostics={"source_execution_id": existing.execution_id},
            )
        )
        return record, events, "reuse_completed_result"
    if replay_policy in {"deny_auto_replay", "manual_recovery_required"} and existing.status in {
        "completed",
        "dispatched",
        "reused_completed_result",
    }:
        record = execution_store.mark_replay_suppressed(
            record,
            error="replay_denied",
            diagnostics={"source_execution_id": existing.execution_id},
        )
        events.append(
            record_execution_event(
                task_run_id,
                event_type="recovery_replay_decided",
                record=record,
                reason="deny_auto_replay",
                diagnostics={"source_execution_id": existing.execution_id},
            )
        )
        events.append(
            record_execution_event(
                task_run_id,
                event_type="replay_guard_triggered",
                record=record,
                reason="deny_auto_replay",
                diagnostics={"source_execution_id": existing.execution_id},
            )
        )
        return record, events, "deny_auto_replay"
    return record, events, "dispatch"
