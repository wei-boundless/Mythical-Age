from __future__ import annotations

import json
from typing import Any, Callable

from capability_system.search_policy import normalize_search_policy, operation_allowed_by_search_policy
from capability_system.tool_authorization import resolve_tool_operation_id
from permissions import build_tool_request_runtime_admission
from permissions.context_models import PermissionContext
from runtime.shared.action_request import build_tool_action_request
from runtime.shared.execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
    build_execution_receipt,
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)
from runtime.shared.action_request import build_tool_result_observation
from runtime.shared.safety import build_task_safety_validators
from runtime.tooling import ToolCapabilityTable, ToolSupervisor

from .event_translation import (
    append_executor_observation_event,
    append_tool_result_received_event,
    build_search_policy_blocked_tool_observation,
)
from .tool_protocol_guard import append_synthetic_tool_result_for_action_request


def begin_tool_call_request(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    event: dict[str, Any],
    current_step_id: str,
    definitions_by_name: dict[str, Any],
    normalize_operation_id: Callable[[str], str],
    allowed_search_sources: set[str] | None,
) -> dict[str, Any]:
    action_request = build_tool_action_request(task_run_id, event, step_id=current_step_id)
    action_step_ref = str(current_step_id or action_request.step_id or "")
    requested_event = event_log.append(
        task_run_id,
        "tool_call_requested",
        payload={"action_request": action_request.to_dict()},
        refs={
            "action_request_ref": action_request.request_id,
            "directive_ref": action_request.directive_ref,
            "operation_id": action_request.operation_id,
            "task_step_ref": action_step_ref,
        },
    )
    operation_id = normalize_operation_id(
        action_request.operation_id
        or resolve_tool_operation_id(
            str(action_request.payload.get("tool_name") or ""),
            definitions_by_name=definitions_by_name,
        )
    )
    allowed_sources = allowed_search_sources if allowed_search_sources is not None else normalize_search_policy(None)
    if operation_allowed_by_search_policy(operation_id, allowed_sources):
        return {
            "action_request": action_request,
            "action_step_ref": action_step_ref,
            "requested_event": requested_event,
            "operation_id": operation_id,
            "blocked_events": [],
            "blocked": False,
        }

    tool_name = str(action_request.payload.get("tool_name") or "")
    blocked_observation = build_search_policy_blocked_tool_observation(
        task_run_id=task_run_id,
        action_request=action_request,
    )
    context_record = runtime_context_manager.record_observation(blocked_observation)
    blocked_events = [
        requested_event,
        event_log.append(
            task_run_id,
            "tool_call_blocked_by_search_policy",
            payload={
                "operation_id": operation_id,
                "tool_name": tool_name,
                "allowed_sources": sorted(allowed_sources),
                "observation": blocked_observation.to_dict(),
                "context_record": context_record.to_dict(),
            },
            refs={
                "action_request_ref": action_request.request_id,
                "operation_id": operation_id,
                "observation_ref": blocked_observation.observation_id,
                "task_step_ref": action_step_ref,
            },
        ),
        append_executor_observation_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=blocked_observation,
            context_record=context_record,
            refs={
                "action_request_ref": action_request.request_id,
                "task_step_ref": action_step_ref,
            },
        ),
        append_tool_result_received_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=blocked_observation,
            context_record=context_record,
            refs={
                "action_request_ref": action_request.request_id,
                "task_step_ref": action_step_ref,
                "tool_protocol_guard": "search_policy_block",
            },
        ),
    ]
    return {
        "action_request": action_request,
        "action_step_ref": action_step_ref,
        "requested_event": requested_event,
        "operation_id": operation_id,
        "blocked_events": blocked_events,
        "blocked": True,
    }


async def handle_tool_call_requested_event(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    event: dict[str, Any],
    current_step_id: str,
    task_id: str,
    task_operation: dict[str, Any],
    adopted_resource_policy: Any,
    user_message: str,
    model_response_executor: Any,
    tool_runtime_executor: Any | None,
    definitions_by_name: dict[str, Any],
    operation_gate: Any,
    permission_mode: str,
    root_dir: Any,
    allowed_search_sources: set[str] | None,
    sandbox_policy: dict[str, Any] | None,
    file_management_policy: dict[str, Any] | None,
    execution_store: RuntimeExecutionStore,
    record_execution_event: Callable[..., Any],
    build_pending_approval_state: Callable[..., dict[str, Any]],
    list_parent_agent_runs: Callable[[str], list[Any]],
    build_delegation_request: Callable[..., Any],
    execute_delegation: Callable[..., Any],
) -> list[Any]:
    begin_result = begin_tool_call_request(
        event_log=event_log,
        runtime_context_manager=runtime_context_manager,
        task_run_id=task_run_id,
        event=event,
        current_step_id=current_step_id,
        definitions_by_name=definitions_by_name,
        normalize_operation_id=operation_gate.registry.normalize_id,
        allowed_search_sources=allowed_search_sources,
    )
    if bool(begin_result.get("blocked")):
        return list(begin_result.get("blocked_events") or [])

    action_request = begin_result["action_request"]
    action_step_ref = str(begin_result.get("action_step_ref") or "")
    requested_event = begin_result["requested_event"]
    operation_id = str(begin_result.get("operation_id") or "")
    tool_name = str(action_request.payload.get("tool_name") or "")
    tool_args = dict(dict(action_request.payload.get("tool_call") or {}).get("args") or {})
    descriptor = operation_gate.registry.get_operation(operation_id)
    tool_directive, tool_policy = build_tool_request_runtime_admission(
        action_request=action_request,
        task_id=task_id,
        task_operation=task_operation,
        operation_id=operation_id,
        operation_descriptor=descriptor,
        adopted_resource_policy=adopted_resource_policy,
    )
    directive_event = event_log.append(
        task_run_id,
        "runtime_directive_issued",
        payload={
            "directive": tool_directive.to_dict(),
            "resource_policy": tool_policy.to_dict(),
            "dispatch_enabled": "pending_operation_gate",
        },
        refs={
            "action_request_ref": action_request.request_id,
            "directive_ref": tool_directive.directive_id,
            "resource_policy_ref": tool_policy.policy_id,
            "task_step_ref": action_step_ref,
        },
    )
    permission_context = _build_permission_context(
        task_run_id=task_run_id,
        action_step_ref=action_step_ref,
        tool_name=tool_name,
        task_operation=task_operation,
        sandbox_policy=sandbox_policy,
        file_management_policy=file_management_policy,
        permission_mode=permission_mode,
    )
    supervision = ToolSupervisor().supervise(
        task_run_id=task_run_id,
        agent_run_id=permission_context.agent_run_id,
        tool_call_id=str(dict(action_request.payload.get("tool_call") or {}).get("id") or action_request.request_id),
        operation_id=operation_id,
        tool_name=tool_name,
        tool_args=tool_args,
        directive=tool_directive,
        resource_policy=tool_policy,
        capability_table=_tool_capability_table_from_task_operation(task_operation),
        permission_context=permission_context,
        operation_gate=operation_gate,
        tool_runtime_executor=tool_runtime_executor,
        action_request=action_request,
        sandbox_policy=dict(sandbox_policy or {}),
        file_management_policy=dict(file_management_policy or {}),
        safety_validators=build_task_safety_validators(
            root_dir=root_dir,
            safety_envelope=dict(
                dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}
            ).get("safety_envelope", {}),
            sandbox_policy=dict(sandbox_policy or {}),
        ),
    )
    gate_result = supervision.gate_result
    approval_risk_fingerprint = supervision.decision.approval_fingerprint
    gate_event = event_log.append(
        task_run_id,
        "operation_gate_checked",
        payload={
            "gate": gate_result.to_dict() if hasattr(gate_result, "to_dict") else {},
            "dispatch_enabled": bool(supervision.allowed and tool_runtime_executor is not None),
            "tool_preflight_only": False,
            "sandbox_policy": dict(sandbox_policy or {}),
            "approval_risk_fingerprint": approval_risk_fingerprint,
            "permission_context": permission_context.to_dict(),
            "permission_decision": supervision.decision.to_dict(),
            "permission_receipt": supervision.receipt.to_dict(),
            "tool_supervision": supervision.to_dict(),
        },
        refs={
            "action_request_ref": action_request.request_id,
            "operation_id": operation_id,
            "directive_ref": tool_directive.directive_id,
            "task_step_ref": action_step_ref,
            "permission_receipt_ref": supervision.receipt.receipt_id,
        },
    )
    events = [requested_event, directive_event, gate_event]
    if supervision.decision.behavior == "repair":
        observation = dict(supervision.preflight or {}).get("observation")
        if observation is not None:
            context_record = runtime_context_manager.record_observation(observation)
            refs = {
                "action_request_ref": action_request.request_id,
                "directive_ref": tool_directive.directive_id,
                "resource_policy_ref": tool_policy.policy_id,
                "task_step_ref": action_step_ref,
                "operation_id": operation_id,
                "permission_receipt_ref": supervision.receipt.receipt_id,
                "tool_preflight": "runtime_tool_validation",
            }
            events.append(
                append_tool_result_received_event(
                    event_log=event_log,
                    task_run_id=task_run_id,
                    observation=observation,
                    context_record=context_record,
                    refs=refs,
                )
            )
            events.append(
                append_executor_observation_event(
                    event_log=event_log,
                    task_run_id=task_run_id,
                    observation=observation,
                    context_record=context_record,
                    refs=refs,
                )
            )
        return events

    if supervision.requires_approval and gate_result is not None:
        approval_state = build_pending_approval_state(
            task_run_id=task_run_id,
            action_request=action_request,
            directive=tool_directive,
            resource_policy=tool_policy,
            gate_result=gate_result,
            descriptor=descriptor,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_management_policy,
            step_ref=action_step_ref,
            approval_risk_fingerprint=approval_risk_fingerprint,
        )
        events.append(
            event_log.append(
                task_run_id,
                "approval_waiting",
                payload={"approval": approval_state},
                refs={
                    "action_request_ref": action_request.request_id,
                    "operation_id": operation_id,
                    "directive_ref": tool_directive.directive_id,
                    "task_step_ref": action_step_ref,
                    "permission_receipt_ref": supervision.receipt.receipt_id,
                },
            )
        )
        return events

    if not supervision.allowed:
        events.extend(
            append_synthetic_tool_result_for_action_request(
                event_log=event_log,
                runtime_context_manager=runtime_context_manager,
                task_run_id=task_run_id,
                action_request=action_request,
                directive_ref=tool_directive.directive_id,
                reason=supervision.decision.reason or "tool_call_denied_by_tool_supervisor",
                step_ref=action_step_ref,
                refs={
                    "operation_id": operation_id,
                    "resource_policy_ref": tool_policy.policy_id,
                    "permission_receipt_ref": supervision.receipt.receipt_id,
                },
                diagnostics={
                    "decision": supervision.decision.behavior,
                    "source": "tool_supervisor",
                    "permission_receipt": supervision.receipt.to_dict(),
                },
            )
        )
        return events

    if tool_runtime_executor is None:
        events.extend(
            append_synthetic_tool_result_for_action_request(
                event_log=event_log,
                runtime_context_manager=runtime_context_manager,
                task_run_id=task_run_id,
                action_request=action_request,
                directive_ref=tool_directive.directive_id,
                reason="Tool runtime executor unavailable.",
                step_ref=action_step_ref,
                refs={
                    "operation_id": operation_id,
                    "resource_policy_ref": tool_policy.policy_id,
                    "permission_receipt_ref": supervision.receipt.receipt_id,
                },
                diagnostics={"decision": "executor_unavailable"},
            )
        )
        return events

    tool_name = str(action_request.payload.get("tool_name") or "")
    if tool_name == "delegate_to_agent":
        parent_agent_runs = list_parent_agent_runs(task_run_id)
        parent_agent_run = next((item for item in parent_agent_runs if item.agent_run_id.endswith(":main")), None)
        if parent_agent_run is None and parent_agent_runs:
            parent_agent_run = parent_agent_runs[0]
        if parent_agent_run is None:
            events.extend(
                append_delegate_tool_failure_observation(
                    event_log=event_log,
                    runtime_context_manager=runtime_context_manager,
                    task_run_id=task_run_id,
                    action_request=action_request,
                    directive=tool_directive,
                    step_ref=action_step_ref,
                    result="委派失败：未找到父 AgentRun。",
                )
            )
            return events
        delegation_request = build_delegation_request(
            task_run_id=task_run_id,
            action_request=action_request,
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            source_agent_id=parent_agent_run.agent_id,
            user_message=user_message,
            task_operation=task_operation,
            allowed_search_sources=allowed_search_sources,
        )
        delegated = await execute_delegation(
            request=delegation_request,
            parent_agent_run=parent_agent_run,
            model_response_executor=model_response_executor,
        )
        events.extend(list(delegated.get("events") or []))
        events.extend(
            append_delegate_tool_result_observation(
                event_log=event_log,
                runtime_context_manager=runtime_context_manager,
                task_run_id=task_run_id,
                action_request=action_request,
                directive=tool_directive,
                delegation_request_ref=delegation_request.request_id,
                step_ref=action_step_ref,
                user_message=user_message,
                delegated_observation=dict(delegated.get("observation") or {}),
            )
        )
        return events

    execution_events, execution_decision = await execute_prepared_tool_call(
        event_log=event_log,
        runtime_context_manager=runtime_context_manager,
        task_run_id=task_run_id,
        action_request=action_request,
        directive=tool_directive,
        operation_id=operation_id,
        descriptor=descriptor,
        tool_name=tool_name,
        step_id=action_step_ref,
        execution_store=execution_store,
        tool_runtime_executor=tool_runtime_executor,
        gate_result=gate_result,
        sandbox_policy=dict(sandbox_policy or {}),
        file_management_policy=dict(file_management_policy or {}),
        record_execution_event=record_execution_event,
        observation_refs={"task_step_ref": action_step_ref},
    )
    events.extend(execution_events)
    if execution_decision in {"reuse_completed_result", "deny_auto_replay"}:
        return events
    return events


def _build_permission_context(
    *,
    task_run_id: str,
    action_step_ref: str,
    tool_name: str,
    task_operation: dict[str, Any],
    sandbox_policy: dict[str, Any] | None,
    file_management_policy: dict[str, Any] | None,
    permission_mode: str,
) -> PermissionContext:
    sandbox_payload = dict(sandbox_policy or {})
    file_payload = dict(file_management_policy or {})
    capability_table = _tool_capability_table_from_task_operation(task_operation)
    file_access_table_ids = tuple(
        str(item)
        for item in list(
            file_payload.get("file_access_table_ids")
            or file_payload.get("file_access_tables")
            or []
        )
        if str(item)
    )
    return PermissionContext(
        context_id=f"permctx:{task_run_id}:{action_step_ref}:{tool_name}",
        task_run_id=task_run_id,
        agent_run_id=str(
            file_payload.get("agent_run_id")
            or sandbox_payload.get("agent_run_id")
            or f"agrun:{task_run_id}:main"
        ),
        environment_id=str(file_payload.get("environment_id") or sandbox_payload.get("environment_id") or ""),
        tool_capability_table_id=str(getattr(capability_table, "table_id", "") or ""),
        file_access_table_ids=file_access_table_ids,
        permission_mode=str(permission_mode or "default"),
        sandbox_policy=sandbox_payload,
        file_management_policy=file_payload,
        metadata={
            "authority": "runtime.execution_engine.tool_loop",
            "task_operation_keys": sorted(str(key) for key in dict(task_operation or {}).keys()),
        },
    )


def _tool_capability_table_from_task_operation(task_operation: dict[str, Any]) -> ToolCapabilityTable | None:
    value = dict(task_operation or {}).get("tool_capability_table")
    return value if isinstance(value, ToolCapabilityTable) else None


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


async def execute_prepared_tool_call(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    action_request: Any,
    directive: Any,
    operation_id: str,
    descriptor: Any,
    tool_name: str,
    step_id: str,
    execution_store: RuntimeExecutionStore,
    tool_runtime_executor: Any,
    gate_result: Any,
    sandbox_policy: dict[str, Any] | None,
    file_management_policy: dict[str, Any] | None = None,
    record_execution_event: Callable[..., Any],
    dispatch_reason: str = "tool_dispatch_started",
    result_record_reason: str = "tool_execution_finished",
    observation_refs: dict[str, Any] | None = None,
) -> tuple[list[Any], str]:
    events: list[Any] = []
    execution_record, execution_events, execution_decision = prepare_tool_execution(
        task_run_id=task_run_id,
        step_id=step_id,
        action_request=action_request,
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        descriptor=descriptor,
        tool_name=tool_name,
        execution_store=execution_store,
        record_execution_event=record_execution_event,
    )
    events.extend(execution_events)
    base_refs = {
        "action_request_ref": action_request.request_id,
        "directive_ref": directive.directive_id,
        **dict(observation_refs or {}),
    }
    if execution_decision == "reuse_completed_result":
        reused_payload = dict(execution_record.result_payload or {})
        reused_observation = build_tool_result_observation(
            task_run_id=task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=str(reused_payload.get("tool_name") or tool_name),
            tool_call_id=str(
                reused_payload.get("tool_call_id")
                or dict(action_request.payload.get("tool_call") or {}).get("id")
                or action_request.request_id
            ),
            tool_args=dict(reused_payload.get("tool_args") or dict(action_request.payload.get("tool_call") or {}).get("args") or {}),
            result=reused_payload.get("result") or "",
            truncated=bool(reused_payload.get("truncated") is True),
            execution_receipt=build_execution_receipt(
                execution_record,
                reused_previous_result=True,
            ).to_dict(),
            result_ref=str(execution_record.result_ref or ""),
            result_envelope=dict(reused_payload.get("result_envelope") or {}),
        )
        context_record = runtime_context_manager.record_observation(reused_observation)
        refs = {
            **base_refs,
            "execution_ref": execution_record.execution_id,
        }
        events.append(
            append_tool_result_received_event(
                event_log=event_log,
                task_run_id=task_run_id,
                observation=reused_observation,
                context_record=context_record,
                refs=refs,
            )
        )
        events.append(
            append_executor_observation_event(
                event_log=event_log,
                task_run_id=task_run_id,
                observation=reused_observation,
                context_record=context_record,
                refs=refs,
            )
        )
        return events, "reuse_completed_result"
    if execution_decision == "deny_auto_replay":
        error_message = "Tool execution replay denied because the operation is not replay-safe."
        events.append(
            event_log.append(
                task_run_id,
                "loop_error",
                payload={
                    "error": error_message,
                    "answer_source": "runtime_execution_replay_guard",
                    "execution_record": execution_record.to_dict(),
                },
                refs={
                    **base_refs,
                    "execution_ref": execution_record.execution_id,
                    "operation_id": operation_id,
                },
            )
        )
        events.extend(
            append_synthetic_tool_result_for_action_request(
                event_log=event_log,
                runtime_context_manager=runtime_context_manager,
                task_run_id=task_run_id,
                action_request=action_request,
                directive_ref=directive.directive_id,
                reason=error_message,
                step_ref=step_id,
                refs={
                    **base_refs,
                    "execution_ref": execution_record.execution_id,
                    "operation_id": operation_id,
                },
                diagnostics={"decision": "deny_auto_replay"},
            )
        )
        return events, "deny_auto_replay"

    events.append(
        record_execution_event(
            task_run_id,
            event_type="execution_dispatch_started",
            record=execution_record,
            reason=dispatch_reason,
        )
    )
    execution_outcome = await tool_runtime_executor.run(
        task_run_id=task_run_id,
        action_request=action_request,
        directive=directive,
        execution_record=execution_record,
        execution_store=execution_store,
        max_result_size_chars=int(dict(gate_result.diagnostics or {}).get("max_result_size_chars") or 0),
        sandbox_policy=dict(sandbox_policy or {}),
        file_management_policy=dict(file_management_policy or {}),
    )
    final_record = execution_outcome.get("execution_record")
    if isinstance(final_record, OperationExecutionRecord):
        events.append(
            record_execution_event(
                task_run_id,
                event_type="execution_result_recorded",
                record=final_record,
                reason=result_record_reason,
            )
        )
    observation = execution_outcome.get("observation")
    if observation is not None:
        context_record = runtime_context_manager.record_observation(observation)
        refs = {
            **base_refs,
            "execution_ref": str(getattr(final_record, "execution_id", "") or ""),
        }
        if observation.observation_type == "tool_result":
            events.append(
                append_tool_result_received_event(
                    event_log=event_log,
                    task_run_id=task_run_id,
                    observation=observation,
                    context_record=context_record,
                    refs=refs,
                )
            )
        events.append(
            append_executor_observation_event(
                event_log=event_log,
                task_run_id=task_run_id,
                observation=observation,
                context_record=context_record,
                refs=refs,
            )
        )
    return events, str(execution_outcome.get("error") or "dispatch")


def append_delegate_tool_failure_observation(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    action_request: Any,
    directive: Any,
    step_ref: str,
    result: str,
) -> list[Any]:
    observation = build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=action_request.request_id,
        directive_ref=directive.directive_id,
        tool_name="delegate_to_agent",
        tool_call_id=str(dict(action_request.payload.get("tool_call") or {}).get("id") or action_request.request_id),
        tool_args=dict(dict(action_request.payload.get("tool_call") or {}).get("args") or {}),
        result=result,
    )
    context_record = runtime_context_manager.record_observation(observation)
    return [
        append_executor_observation_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=observation,
            context_record=context_record,
            refs={
                "action_request_ref": action_request.request_id,
                "directive_ref": directive.directive_id,
                "task_step_ref": step_ref,
            },
        )
    ]


def append_delegate_tool_result_observation(
    *,
    event_log: Any,
    runtime_context_manager: Any,
    task_run_id: str,
    action_request: Any,
    directive: Any,
    delegation_request_ref: str,
    step_ref: str,
    user_message: str,
    delegated_observation: dict[str, Any],
) -> list[Any]:
    observation = build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=action_request.request_id,
        directive_ref=directive.directive_id,
        tool_name="delegate_to_agent",
        tool_call_id=str(dict(action_request.payload.get("tool_call") or {}).get("id") or action_request.request_id),
        tool_args={
            **dict(dict(action_request.payload.get("tool_call") or {}).get("args") or {}),
            "current_user_message": str(user_message or "").strip(),
        },
        result=json.dumps(dict(delegated_observation or {}), ensure_ascii=False),
    )
    context_record = runtime_context_manager.record_observation(observation)
    refs = {
        "action_request_ref": action_request.request_id,
        "directive_ref": directive.directive_id,
        "delegation_request_ref": delegation_request_ref,
        "task_step_ref": step_ref,
    }
    return [
        append_tool_result_received_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=observation,
            context_record=context_record,
            refs=refs,
        ),
        append_executor_observation_event(
            event_log=event_log,
            task_run_id=task_run_id,
            observation=observation,
            context_record=context_record,
            refs=refs,
        ),
    ]
