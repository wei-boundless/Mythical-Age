from __future__ import annotations

import json
import asyncio
import hashlib
import shutil
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from capability_system import build_default_operation_registry
from permissions import OperationGatePipelineContext, ResourcePolicy
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import (
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)
from runtime.shared.models import AgentRun, AgentRunResult
from runtime.shared.safety import build_task_safety_validators
from runtime.memory.tool_observation_ledger import build_tool_observation_record

from orchestration.runtime_directive import RuntimeDirective
from orchestration.commit_gate import build_assistant_session_message_commit_decision
from project_layout import ProjectLayout
from harness.runtime import RuntimeCompiler, TaskExecutorServices, assemble_runtime, build_execution_context
from harness.runtime.public_progress import public_action_progress_summary, public_runtime_progress_summary
from harness.agent_control.controller import SUBAGENT_TOOL_NAMES, SubagentControl

from .admission import admit_model_action
from .executor_sequence import claim_executor_sequence, next_model_action_request_id
from .model_action_runtime import (
    call_model_invoker,
    compact_text,
    model_action_timeout_seconds,
    normalize_model_selection_for_invocation,
    parse_json_object,
)
from .model_action_protocol import ModelActionRequest, model_action_request_from_payload
from .task_run_execution_control import (
    ExecutorControlSignal,
    attach_model_task,
    clear_executor_epoch,
    clear_model_task,
    executor_epoch_is_live,
    peek_executor_signal,
    register_executor_epoch,
    request_executor_pause,
    request_executor_replan,
    request_executor_stop,
)
from .task_contract_revision import (
    apply_contract_revision_decisions,
    ensure_revision_for_steer,
    list_active_task_contract_revisions,
)
from .task_steering import (
    create_active_task_steer,
    list_pending_task_steers,
    mark_task_steers_consumed,
    mark_task_steers_included,
)
from .task_lifecycle import TaskLifecycleRecord, finish_task_lifecycle
from .task_run_recovery_state import recovery_state_for_task_run, should_auto_continue_task_run
from .work_rollout import append_work_rollout_item, ensure_work_rollout, work_rollout_summary


_MAX_TASK_EXECUTION_STEPS = 12
_MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS = 3
_TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS = 15.0
_TASK_RUN_CONTROL_KEY = "runtime_control"
_TASK_RUN_PAUSE_REQUESTED = "pause_requested"
_TASK_RUN_PAUSED = "paused"
_TASK_RUN_RESUME_REQUESTED = "resume_requested"
_TASK_RUN_STOP_REQUESTED = "stop_requested"
_TASK_RUN_STOPPED = "stopped"
_TASK_RUN_REPLAN_REQUESTED = "replan_requested"
_TASK_RUN_INTERRUPTED_FOR_REPLAN = "interrupted_for_replan"
_TASK_RUN_CONTROL_STATES = {
    _TASK_RUN_PAUSE_REQUESTED,
    _TASK_RUN_PAUSED,
    _TASK_RUN_RESUME_REQUESTED,
    _TASK_RUN_STOP_REQUESTED,
    _TASK_RUN_STOPPED,
    _TASK_RUN_REPLAN_REQUESTED,
    _TASK_RUN_INTERRUPTED_FOR_REPLAN,
}


class TaskRunExecutorInterrupted(Exception):
    def __init__(self, signal: ExecutorControlSignal) -> None:
        super().__init__(f"task_run_executor_interrupted:{signal.kind}")
        self.signal = signal


def is_task_run_executable(task_run: Any) -> bool:
    return recovery_state_for_task_run(task_run).executable


def is_task_run_executor_claimed(task_run: Any) -> bool:
    return recovery_state_for_task_run(task_run).running_claimed


def task_run_control_state(task_run: Any) -> str:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = diagnostics.get(_TASK_RUN_CONTROL_KEY)
    if not isinstance(control, dict):
        return ""
    state = str(control.get("state") or "").strip()
    return state if state in _TASK_RUN_CONTROL_STATES else ""


def _is_task_run_resumable_for_user_control(task_run: Any) -> bool:
    return recovery_state_for_task_run(task_run).same_run_resumable


def _is_single_agent_task_run(task_run: Any) -> bool:
    return str(getattr(task_run, "execution_runtime_kind", "") or "") in {"single_agent_task", "subagent_task"}


def request_task_run_pause(runtime_host: Any, task_run_id: str, *, reason: str = "", requested_by: str = "user") -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    status = str(getattr(task_run, "status", "") or "")
    if status in {"completed", "failed", "aborted"}:
        return _conflict(task_run_id, f"task_run_terminal:{status}")
    current_state = task_run_control_state(task_run)
    if status == "waiting_executor" and current_state == _TASK_RUN_PAUSED:
        return {"ok": True, "accepted": True, "task_run": task_run.to_dict(), "control": _runtime_control_payload(task_run)}
    now = time.time()
    event = runtime_host.event_log.append(
        task_run_id,
        "task_run_pause_requested",
        payload={"task_run_id": task_run_id, "reason": reason, "requested_by": requested_by},
        refs={"task_run_ref": task_run_id},
    )
    if status in {"created", "waiting_executor", "waiting_approval", "blocked"}:
        updated_status = "waiting_executor" if status in {"created", "waiting_executor", "blocked"} else status
        control_state = _TASK_RUN_PAUSED if updated_status == "waiting_executor" else _TASK_RUN_PAUSE_REQUESTED
        latest_step_status = "waiting_executor" if updated_status == "waiting_executor" else "waiting_approval"
    else:
        updated_status = status
        control_state = _TASK_RUN_PAUSE_REQUESTED
        latest_step_status = "running"
    updated = replace(
        task_run,
        status=updated_status,  # type: ignore[arg-type]
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        terminal_reason="waiting_executor" if updated_status == "waiting_executor" else getattr(task_run, "terminal_reason", ""),
        diagnostics=_diagnostics_with_runtime_control(
            dict(task_run.diagnostics or {}),
            state=control_state,
            requested_by=requested_by,
            requested_at=event.created_at or now,
            reason=reason,
            latest_step="task_run_pause_requested",
            latest_step_status=latest_step_status,
            latest_step_summary=(
                "暂停请求已记录；当前步骤收口后任务会停在可继续状态。"
                if control_state == _TASK_RUN_PAUSE_REQUESTED
                else "任务已暂停，后续可以继续执行。"
            ),
        ),
    )
    runtime_host.state_index.upsert_task_run(updated)
    if control_state == _TASK_RUN_PAUSE_REQUESTED:
        request_executor_pause(runtime_host, task_run_id=task_run_id, reason=reason, requested_by=requested_by)
    if control_state == _TASK_RUN_PAUSED:
        _record_task_step_summary(
            runtime_host,
            task_run_id=task_run_id,
            step="task_run_paused",
            status="waiting_executor",
            summary="任务已暂停，后续可以继续执行。",
        )
        append_work_rollout_item(
            runtime_host,
            task_run=updated,
            item_type="pause_boundary",
            title="已暂停",
            status="waiting_executor",
            summary="任务已暂停，后续可以继续执行。",
            event_offset=event.offset,
            refs={"task_run_ref": task_run_id},
        )
    else:
        _record_task_step_summary(
            runtime_host,
            task_run_id=task_run_id,
            step="task_run_pause_requested",
            status="running",
            summary="暂停请求已记录；当前步骤收口后任务会停在可继续状态。",
        )
        append_work_rollout_item(
            runtime_host,
            task_run=updated,
            item_type="progress",
            title="正在暂停",
            status="running",
            summary="暂停请求已记录；当前步骤收口后任务会停在可继续状态。",
            event_offset=event.offset,
            refs={"task_run_ref": task_run_id},
        )
    return {"ok": True, "accepted": True, "task_run": updated.to_dict(), "control": _runtime_control_payload(updated)}


def resume_paused_task_run(
    runtime_host: Any,
    task_run_id: str,
    *,
    reason: str = "",
    requested_by: str = "user",
    turn_id: str = "",
) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    status = str(getattr(task_run, "status", "") or "")
    if status in {"completed", "failed", "aborted"}:
        return _conflict(task_run_id, f"task_run_terminal:{status}")
    if not _is_task_run_resumable_for_user_control(task_run):
        return _conflict(task_run_id, f"task_run_not_resumable:{status}")
    now = time.time()
    recovery_state = recovery_state_for_task_run(task_run)
    resume_status = "waiting_executor" if recovery_state.same_run_resumable else status
    resume_recovery_action = recovery_state.recovery_action or "resume_task_run"
    resume_recoverable = dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {})
    if not resume_recoverable and status in {"blocked", "failed"}:
        resume_recoverable = {
            "error_code": str(getattr(task_run, "terminal_reason", "") or "resume_requested"),
            "retryable": True,
            "user_message": "继续请求已记录，任务可以从当前恢复点续跑。",
        }
    event = runtime_host.event_log.append(
        task_run_id,
        "task_run_resume_requested",
        payload={
            "task_run_id": task_run_id,
            "reason": reason,
            "requested_by": requested_by,
            **({"turn_id": turn_id} if turn_id else {}),
        },
        refs={"task_run_ref": task_run_id, **({"turn_ref": turn_id} if turn_id else {})},
    )
    updated = replace(
        task_run,
        status=resume_status,  # type: ignore[arg-type]
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        terminal_reason="waiting_executor",
        diagnostics=_diagnostics_with_runtime_control(
            {
                **_strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
                "executor_status": "waiting_executor",
                "recovery_action": resume_recovery_action,
                **({"recoverable_error": resume_recoverable} if resume_recoverable else {}),
                **({"latest_interaction_turn_id": turn_id} if turn_id else {}),
            },
            state=_TASK_RUN_RESUME_REQUESTED,
            requested_by=requested_by,
            requested_at=event.created_at or now,
            reason=reason,
            latest_step="task_run_resume_requested",
            latest_step_status="waiting_executor",
            latest_step_summary="继续请求已记录，我会从原进度接着处理。",
        ),
    )
    runtime_host.state_index.upsert_task_run(updated)
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run_id,
        step="task_run_resume_requested",
        status="waiting_executor",
        summary="继续请求已记录，我会从原进度接着处理。",
        refs={"turn_ref": turn_id} if turn_id else None,
    )
    append_work_rollout_item(
        runtime_host,
        task_run=updated,
        item_type="progress",
        title="继续处理",
        status="waiting_executor",
        summary="继续请求已记录，我会从原进度接着处理。",
        event_offset=event.offset,
        refs={"task_run_ref": task_run_id, **({"turn_ref": turn_id} if turn_id else {})},
    )
    return {"ok": True, "accepted": True, "task_run": updated.to_dict(), "control": _runtime_control_payload(updated)}


def stop_task_run(runtime_host: Any, task_run_id: str, *, reason: str = "", requested_by: str = "user") -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    status = str(getattr(task_run, "status", "") or "")
    if status in {"completed", "failed", "aborted"}:
        return {"ok": True, "accepted": False, "task_run": task_run.to_dict(), "control": _runtime_control_payload(task_run)}
    now = time.time()
    event = runtime_host.event_log.append(
        task_run_id,
        "task_run_stop_requested",
        payload={"task_run_id": task_run_id, "reason": reason, "requested_by": requested_by},
        refs={"task_run_ref": task_run_id},
    )
    if is_task_run_executor_claimed(task_run):
        request_executor_stop(runtime_host, task_run_id=task_run_id, reason=reason, requested_by=requested_by)
        updated = replace(
            task_run,
            updated_at=event.created_at or now,
            latest_event_offset=event.offset,
            diagnostics=_diagnostics_with_runtime_control(
                dict(task_run.diagnostics or {}),
                state=_TASK_RUN_STOP_REQUESTED,
                requested_by=requested_by,
                requested_at=event.created_at or now,
                reason=reason,
                latest_step="task_run_stop_requested",
                latest_step_status="running",
                latest_step_summary="停止请求已记录；当前步骤收口后任务会结束。",
            ),
        )
        runtime_host.state_index.upsert_task_run(updated)
        _record_task_step_summary(
            runtime_host,
            task_run_id=task_run_id,
            step="task_run_stop_requested",
            status="running",
            summary="停止请求已记录；当前步骤收口后任务会结束。",
        )
        return {"ok": True, "accepted": True, "task_run": updated.to_dict(), "control": _runtime_control_payload(updated)}
    updated, lifecycle, finished_event = _finish_user_stopped_task(
        runtime_host,
        task_run=replace(
            task_run,
            updated_at=event.created_at or now,
            latest_event_offset=event.offset,
            diagnostics=_diagnostics_with_runtime_control(
                dict(task_run.diagnostics or {}),
                state=_TASK_RUN_STOPPED,
                requested_by=requested_by,
                requested_at=event.created_at or now,
                reason=reason,
                latest_step="task_run_stopped",
                latest_step_status="aborted",
                latest_step_summary="任务已按用户要求停止。",
            ),
        ),
        reason=reason,
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run_id,
        step="task_run_stopped",
        status="aborted",
        summary="任务已按用户要求停止。",
    )
    return {
        "ok": True,
        "accepted": True,
        "task_run": updated.to_dict(),
        "lifecycle": lifecycle.to_dict(),
        "event": finished_event,
        "control": _runtime_control_payload(updated),
    }


def append_user_work_instruction(
    runtime_host: Any,
    task_run_id: str,
    *,
    content: str,
    turn_id: str = "",
    intent: str = "append_instruction_to_active_work",
) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    instruction = str(content or "").strip()
    if not instruction:
        return _conflict(task_run_id, "user_work_instruction_empty")
    result = create_active_task_steer(
        runtime_host,
        task_run_id,
        content=instruction,
        turn_id=turn_id,
        intent=intent,
        steer_kind="instruction",
        priority="high",
    )
    updated = runtime_host.state_index.get_task_run(task_run_id) or task_run
    steer_ref = str(dict(result.get("steer") or {}).get("steer_id") or "")
    if is_task_run_executor_claimed(updated):
        signalled = request_executor_replan(
            runtime_host,
            task_run_id=task_run_id,
            reason=intent,
            requested_by="user",
            steer_ref=steer_ref,
        )
        event = runtime_host.event_log.append(
            task_run_id,
            "task_run_replan_requested",
            payload={"task_run_id": task_run_id, "reason": intent, "steer_ref": steer_ref, "signalled": signalled},
            refs={"task_run_ref": task_run_id, "steer_ref": steer_ref},
        )
        updated = replace(
            updated,
            updated_at=event.created_at or time.time(),
            latest_event_offset=event.offset,
            diagnostics=_diagnostics_with_runtime_control(
                dict(updated.diagnostics or {}),
                state=_TASK_RUN_REPLAN_REQUESTED,
                requested_by="user",
                requested_at=event.created_at or time.time(),
                reason=intent,
                latest_step="task_run_replan_requested",
                latest_step_status="running",
                latest_step_summary="已收到新的补充要求，正在中断当前步骤并重新规划。",
            ),
        )
        runtime_host.state_index.upsert_task_run(updated)
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run_id,
        step="active_task_steer_recorded",
        status=str(getattr(updated, "status", "") or "running"),
        summary="已收到你的补充说明，会在后续处理里优先纳入。",
        refs={"steer_ref": steer_ref},
    )
    return {**result, "task_run": updated.to_dict()}


def recover_interrupted_task_executors(runtime_host: Any) -> dict[str, Any]:
    recovered: list[str] = []
    skipped_graph_node_task_run_ids: list[str] = []
    for task_run in runtime_host.state_index.list_task_runs():
        if not _is_single_agent_task_run(task_run):
            continue
        if _origin_kind(task_run) == "graph_node_assigned":
            skipped_graph_node_task_run_ids.append(task_run.task_run_id)
            continue
        if not is_task_run_executor_claimed(task_run):
            continue
        event = runtime_host.event_log.append(
            task_run.task_run_id,
            "task_run_executor_recovered_after_runtime_start",
            payload={
                "task_run_id": task_run.task_run_id,
                "previous_status": str(task_run.status or ""),
                "previous_executor_status": str(dict(task_run.diagnostics or {}).get("executor_status") or ""),
            },
            refs={"task_run_ref": task_run.task_run_id},
        )
        recovered_task = replace(
            task_run,
            status="waiting_executor",
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            terminal_reason="waiting_executor",
            diagnostics={
                **_strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
                "executor_status": "waiting_executor",
                "latest_step": "task_executor_recovered_after_runtime_start",
                "latest_step_status": "waiting_executor",
                "latest_step_summary": "后端运行时已重启，当前工作已恢复为可继续状态。",
                "recoverable_error": {
                    "error_code": "task_executor_interrupted_by_runtime_restart",
                    "retryable": True,
                    "user_message": "后端运行时已重启，任务可以继续续跑。",
                },
                "recovery_action": "rerun_task_executor",
            },
        )
        runtime_host.state_index.upsert_task_run(recovered_task)
        append_work_rollout_item(
            runtime_host,
            task_run=recovered_task,
            item_type="interrupted_boundary",
            title="恢复断点",
            status="waiting_executor",
            summary="后端运行时已重启，当前工作已恢复为可继续状态。",
            event_offset=event.offset,
            refs={"task_run_ref": task_run.task_run_id},
            payload={"terminal_reason": "task_executor_interrupted_by_runtime_restart"},
        )
        recovered.append(task_run.task_run_id)
    return {
        "recovered_count": len(recovered),
        "task_run_ids": recovered,
        "skipped_graph_node_task_run_ids": skipped_graph_node_task_run_ids,
        "authority": "harness.task_executor.runtime_start_recovery",
    }


async def execute_task_run(
    services: TaskExecutorServices,
    task_run_id: str,
    *,
    max_steps: int = _MAX_TASK_EXECUTION_STEPS,
    graph_node_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_host = services.runtime_host
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    runtime_kind = str(getattr(task_run, "execution_runtime_kind", "") or "")
    if runtime_kind not in {"single_agent_task", "subagent_task"}:
        return _conflict(task_run_id, "not_single_agent_task_run")
    control_result = _apply_runtime_control_boundary(runtime_host, task_run=task_run, agent_run=None, boundary="executor_start")
    if control_result is not None:
        return control_result
    if is_task_run_executor_claimed(task_run):
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        executor_status = str(diagnostics.get("executor_status") or "")
        if executor_status == "running":
            recovered = _recover_stale_graph_node_executor_claim(
                runtime_host,
                task_run=task_run,
                graph_node_authorization=graph_node_authorization,
            )
            if recovered is None:
                return _conflict(task_run_id, "task_run_executor_already_running")
            task_run = recovered
        elif executor_status == "scheduled":
            pass
        else:
            return _conflict(task_run_id, "task_run_executor_already_running")
    if not is_task_run_executable(task_run) and not is_task_run_executor_claimed(task_run):
        if not _authorized_graph_node_executor_resume(task_run, authorization=graph_node_authorization):
            return _conflict(task_run_id, f"task_run_not_executable:{task_run.status}")
    elif graph_node_authorization is not None and not _authorized_graph_node_executor_resume(task_run, authorization=graph_node_authorization):
        return _conflict(task_run_id, f"task_run_not_executable:{task_run.status}")

    contract = _load_contract(runtime_host, task_run)
    if not contract:
        failed_task, _lifecycle, event = _finish_without_executor(
            runtime_host,
            task_run=task_run,
            status="failed",
            terminal_reason="task_contract_missing",
        )
        return {"ok": False, "task_run": failed_task.to_dict(), "event": event, "error": "task_contract_missing"}

    agent_profile = services.agent_runtime_profile
    diagnostics = dict(task_run.diagnostics or {})
    turn_id = str(diagnostics.get("turn_id") or task_run.task_id or task_run.task_run_id)
    model_selection = _task_model_selection(task_run, agent_profile=agent_profile)
    runtime_assembly = assemble_runtime(
        backend_dir=services.backend_dir,
        session_id=task_run.session_id,
        turn_id=turn_id,
        agent_invocation_id=f"aginvoke:{task_run.task_run_id}:executor",
        request_task_selection=_task_selection_from_task_run(task_run),
        model_selection=model_selection,
        agent_runtime_profile=agent_profile,
        tool_instances=services.all_tool_instances(),
        definitions_by_name=dict(runtime_host.tool_authorization_index.definitions_by_name or {}),
    )
    runtime_available_tools = _runtime_available_tools(runtime_assembly.to_dict())
    allowed_tool_names = _runtime_allowed_tool_names(runtime_available_tools)
    runtime_fingerprint = _current_runtime_fingerprint(
        runtime_assembly.to_dict(),
        runtime_host=runtime_host,
        backend_config=services.backend_config,
    )
    runtime_host.event_log.append(
        task_run.task_run_id,
        "task_run_executor_started",
        payload={"task_run": task_run.to_dict(), "runtime_assembly": runtime_assembly.to_dict()},
        refs={"task_run_ref": task_run.task_run_id},
    )
    sequence = claim_executor_sequence(runtime_host, task_run)
    runtime_host.event_log.append(
        task_run.task_run_id,
        "task_run_executor_claimed",
        payload={"sequence": sequence.to_dict()},
        refs={"task_run_ref": task_run.task_run_id, "executor_epoch": sequence.executor_epoch},
    )
    register_executor_epoch(runtime_host, task_run_id=task_run.task_run_id, executor_epoch=sequence.executor_epoch)
    ensure_work_rollout(runtime_host, task_run, status="running")
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_executor_started",
        status="running",
        summary="已接上当前工作，正在整理上下文。",
    )

    observation_context = _observations_for_packet(
        runtime_host,
        task_run.task_run_id,
        current_fingerprint=runtime_fingerprint,
    )
    raw_observations: list[dict[str, Any]] = list(observation_context["raw_observations"])
    observations: list[dict[str, Any]] = list(observation_context["packet_observations"])
    execution_state: dict[str, Any] = dict(observation_context["execution_state"])
    artifact_refs: list[dict[str, Any]] = list(observation_context["artifact_refs"])
    compiler = RuntimeCompiler()
    projected_task = runtime_host.state_index.get_task_run(task_run.task_run_id) or task_run
    current_task = replace(
        projected_task,
        status="running",
        updated_at=time.time(),
        terminal_reason="",
        diagnostics={
            **_diagnostics_for_executor_start(dict(getattr(projected_task, "diagnostics", {}) or diagnostics)),
            "executor_status": "running",
            "executor_epoch": sequence.executor_epoch,
            "next_invocation_index": sequence.next_invocation_index,
        },
    )
    runtime_host.state_index.upsert_task_run(current_task)
    agent_run = _ensure_executor_agent_run(runtime_host, task_run=current_task)

    try:
        return await _execute_claimed_task_run(
            services,
            runtime_host=runtime_host,
            task_run=task_run,
            current_task=current_task,
            agent_run=agent_run,
            contract=contract,
            runtime_assembly=runtime_assembly,
            runtime_available_tools=runtime_available_tools,
            allowed_tool_names=allowed_tool_names,
            runtime_fingerprint=runtime_fingerprint,
            raw_observations=raw_observations,
            observations=observations,
            execution_state=execution_state,
            artifact_refs=artifact_refs,
            model_selection=model_selection,
            compiler=compiler,
            sequence=sequence,
            max_steps=max_steps,
        )
    finally:
        clear_executor_epoch(runtime_host, task_run_id=task_run.task_run_id, executor_epoch=sequence.executor_epoch)


async def _execute_claimed_task_run(
    services: TaskExecutorServices,
    *,
    runtime_host: Any,
    task_run: Any,
    current_task: Any,
    agent_run: Any,
    contract: Any,
    runtime_assembly: Any,
    runtime_available_tools: list[dict[str, Any]],
    allowed_tool_names: set[str],
    runtime_fingerprint: str,
    raw_observations: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    execution_state: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    model_selection: dict[str, Any],
    compiler: RuntimeCompiler,
    sequence: Any,
    max_steps: int,
) -> dict[str, Any]:
    for local_step_index in range(1, max(1, int(max_steps or _MAX_TASK_EXECUTION_STEPS)) + 1):
        step_index = sequence.next_invocation_index + local_step_index - 1
        control_result = _apply_runtime_control_boundary(runtime_host, task_run=current_task, agent_run=agent_run, boundary=f"step_start:{step_index}")
        if control_result is not None:
            return control_result
        current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
        compilation = compiler.compile_task_execution_packet(
            session_id=current_task.session_id,
            task_run=current_task.to_dict(),
            contract=contract,
            observations=observations,
            execution_state=execution_state,
            work_rollout=work_rollout_summary(runtime_host, current_task),
            agent_profile_ref=current_task.agent_profile_id,
            model_selection=model_selection,
            available_tools=runtime_available_tools,
            runtime_assembly=runtime_assembly,
            invocation_index=step_index,
        )
        packet_event = runtime_host.event_log.append(
            current_task.task_run_id,
            "runtime_invocation_packet_compiled",
            payload=compilation.to_dict(),
            refs={
                "task_run_ref": current_task.task_run_id,
                "runtime_envelope_ref": compilation.envelope.envelope_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
                "executor_epoch": sequence.executor_epoch,
                "invocation_index": step_index,
            },
        )
        runtime_host.state_index.upsert_task_run(
            replace(
                current_task,
                latest_event_offset=packet_event.offset,
                diagnostics={
                    **dict(getattr(current_task, "diagnostics", {}) or {}),
                    "executor_epoch": sequence.executor_epoch,
                    "next_invocation_index": step_index + 1,
                    "active_packet_ref": compilation.packet.packet_id,
                },
            )
        )
        current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
        included_steer_ids = [
            str(item.get("steer_id") or "")
            for item in list(dict(execution_state.get("system_projection") or {}).get("pending_user_steers") or [])
            if isinstance(item, dict) and str(item.get("steer_id") or "")
        ]
        if included_steer_ids:
            mark_task_steers_included(
                runtime_host,
                current_task.task_run_id,
                steer_ids=included_steer_ids,
                packet_ref=compilation.packet.packet_id,
            )
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"task_execution_packet_compiled:{step_index}",
            status="running",
            summary="正在整理上下文，准备继续处理。",
            refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
        )
        append_work_rollout_item(
            runtime_host,
            task_run=current_task,
            item_type="progress",
            title="整理上下文",
            status="running",
            summary="正在整理上下文，准备继续处理。",
            event_offset=packet_event.offset,
            refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
        )
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"task_model_action_invocation_started:{step_index}",
            status="running",
            summary="正在分析当前目标、已有进展和最新要求，准备决定下一步。",
            refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
        )
        try:
            action_request, protocol = await _await_task_model_action_with_status(
                runtime_host,
                task_run_id=current_task.task_run_id,
                session_id=current_task.session_id,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                executor_epoch=sequence.executor_epoch,
                model_runtime=services.model_runtime,
                packet=compilation.packet,
                model_selection=model_selection,
            )
        except TaskRunExecutorInterrupted as exc:
            interrupted_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
            if exc.signal.kind == "pause":
                return _pause_executor_for_user_control(runtime_host, task_run=interrupted_task, agent_run=agent_run, boundary=f"model_action_wait:{step_index}")
            if exc.signal.kind == "stop":
                return _stop_executor_for_user_control(runtime_host, task_run=interrupted_task, agent_run=agent_run, boundary=f"model_action_wait:{step_index}")
            return _replan_executor_for_user_control(
                runtime_host,
                task_run=interrupted_task,
                agent_run=agent_run,
                boundary=f"model_action_wait:{step_index}",
                signal=exc.signal,
            )
        except Exception as exc:
            return _pause_executor_for_model_recovery(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                error=exc,
            )
        if action_request is None:
            repair_observation = _model_protocol_repair_observation(
                task_run_id=current_task.task_run_id,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                diagnostics=protocol,
                runtime_fingerprint=runtime_fingerprint,
            )
            raw_observations.append(repair_observation)
            runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
            runtime_host.event_log.append(
                current_task.task_run_id,
                "task_model_action_protocol_repair_required",
                payload={"observation": repair_observation, "diagnostics": protocol},
                refs={
                    "task_run_ref": current_task.task_run_id,
                    "observation_ref": repair_observation["observation_id"],
                    "runtime_invocation_packet_ref": compilation.packet.packet_id,
                },
            )
            _record_task_step_summary(
                runtime_host,
                task_run_id=current_task.task_run_id,
                step=f"model_action_protocol_repair_required:{step_index}",
                status="running",
                summary="当前步骤输出格式不完整，正在自动修正后继续。",
                refs={"observation_ref": repair_observation["observation_id"]},
            )
            if _model_protocol_repair_count(raw_observations) >= _MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS:
                return _finish_executor_blocked(
                    runtime_host,
                    task_run=current_task,
                    agent_run=agent_run,
                    terminal_reason="model_action_protocol_repair_required",
                    payload={
                        "diagnostics": protocol,
                        "recoverable_error": {
                            "error_code": "model_action_invalid",
                            "retryable": True,
                            "validation_errors": list(protocol.get("validation_errors") or []),
                        },
                        "recovery_action": "rerun_task_executor",
                    },
                )
            observation_context = _observations_for_packet(
                runtime_host,
                current_task.task_run_id,
                current_fingerprint=runtime_fingerprint,
                pending_observations=raw_observations,
            )
            raw_observations = list(observation_context["raw_observations"])
            observations = list(observation_context["packet_observations"])
            execution_state = dict(observation_context["execution_state"])
            artifact_refs = _dedupe_artifacts([*list(observation_context["artifact_refs"]), *artifact_refs])
            continue
        action_event = runtime_host.event_log.append(
            current_task.task_run_id,
            "model_action_request_received",
            payload={"model_action_request": action_request.to_dict(), "diagnostics": protocol},
            refs={
                "task_run_ref": current_task.task_run_id,
                "action_request_ref": action_request.request_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
            },
        )
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"model_action_received:{step_index}",
            status="running",
            summary=_action_progress_note(action_request),
            public_progress_note=action_request.public_progress_note,
            agent_brief_output=compact_text(action_request.final_answer, limit=300) if action_request.action_type == "respond" else "",
            presentation_source="model_action.public_progress_note" if action_request.public_progress_note else "model_action.action_type_fallback",
            refs={"action_request_ref": action_request.request_id},
        )
        consumed_steer_ids = _consumed_steer_ids(action_request, included_steer_ids)
        apply_contract_revision_decisions(
            runtime_host,
            current_task.task_run_id,
            decisions=_contract_revision_decisions(action_request),
            action_ref=action_request.request_id,
        )
        if consumed_steer_ids:
            mark_task_steers_consumed(
                runtime_host,
                current_task.task_run_id,
                steer_ids=consumed_steer_ids,
                action_ref=action_request.request_id,
            )
        append_work_rollout_item(
            runtime_host,
            task_run=current_task,
            item_type="progress",
            title="思考下一步",
            status="running",
            summary=_action_progress_note(action_request),
            agent_brief_output=compact_text(action_request.final_answer, limit=300) if action_request.action_type == "respond" else "",
            event_offset=action_event.offset,
            refs={"action_request_ref": action_request.request_id, "runtime_invocation_packet_ref": compilation.packet.packet_id},
            payload={
                "action_type": action_request.action_type,
                "public_progress_note": action_request.public_progress_note,
                "presentation_source": "model_action.public_progress_note" if action_request.public_progress_note else "model_action.action_type_fallback",
            },
        )
        current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
        control_result = _apply_runtime_control_boundary(runtime_host, task_run=current_task, agent_run=agent_run, boundary=f"after_model_action:{step_index}")
        if control_result is not None:
            return control_result

        project_root = ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve()
        admission = admit_model_action(
            action_request,
            definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
            allowed_tool_names=allowed_tool_names,
            runtime_profile=dict(runtime_assembly.profile.to_dict()),
            operation_gate=None,
            permission_mode=runtime_host._current_permission_mode(),
            directive_ref=f"task-execution:{action_request.request_id}",
            workspace_root=project_root,
            side_effect_tools_allowed=True,
        )
        runtime_host.event_log.append(
            current_task.task_run_id,
            "model_action_admission_checked",
            payload={"admission": admission.to_dict()},
            refs={"task_run_ref": current_task.task_run_id, "action_request_ref": action_request.request_id},
        )
        if admission.decision != "allow":
            return _finish_executor_blocked(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                terminal_reason=admission.system_reason or admission.decision,
                payload={"admission": admission.to_dict(), "action_request": action_request.to_dict()},
            )

        if action_request.action_type == "tool_call":
            tool_progress = _tool_call_progress_summary(action_request)
            _record_task_step_summary(
                runtime_host,
                task_run_id=current_task.task_run_id,
                step=f"task_tool_call_started:{step_index}",
                status="running",
                summary=tool_progress,
                presentation_source="system.tool_call_status",
                refs={"action_request_ref": action_request.request_id},
            )
            append_work_rollout_item(
                runtime_host,
                task_run=current_task,
                item_type="progress",
                title="执行操作",
                status="running",
                summary=tool_progress,
                event_offset=action_event.offset,
                refs={"action_request_ref": action_request.request_id, "runtime_invocation_packet_ref": compilation.packet.packet_id},
                payload={"tool_name": str(action_request.tool_call.get("tool_name") or action_request.tool_call.get("name") or "")},
            )
            observation = await _execute_task_tool_call(
                runtime_host,
                services=services,
                task_run=current_task,
                packet_ref=compilation.packet.packet_id,
                action_request=action_request,
                runtime_assembly=runtime_assembly.to_dict(),
            )
            raw_observations.append(observation)
            runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
            observation_event = runtime_host.event_log.append(
                current_task.task_run_id,
                "task_tool_observation_recorded",
                payload={"observation": observation},
                refs={
                    "task_run_ref": current_task.task_run_id,
                    "action_request_ref": action_request.request_id,
                    "observation_ref": observation["observation_id"],
                },
            )
            artifact_refs = _dedupe_artifacts([*artifact_refs, *_artifact_refs_from_observation(observation)])
            _record_task_step_summary(
                runtime_host,
                task_run_id=current_task.task_run_id,
                step=f"task_tool_observation_recorded:{step_index}",
                status="running",
                summary="工具调用已完成，正在根据结果继续。",
                agent_brief_output=_observation_brief(observation),
                presentation_source="tool_observation.summary",
                refs={"observation_ref": observation["observation_id"]},
            )
            append_work_rollout_item(
                runtime_host,
                task_run=current_task,
                item_type="progress",
                title="执行操作",
                status="running",
                summary="工具调用已完成，正在根据结果继续。" if not observation.get("error") else "工具调用失败，正在根据失败原因调整处理路径。",
                agent_brief_output=_observation_brief(observation),
                event_offset=observation_event.offset,
                refs={"observation_ref": observation["observation_id"], "action_request_ref": action_request.request_id},
                payload={"artifact_refs": _artifact_refs_from_observation(observation), "error": str(observation.get("error") or "")},
            )
            if observation.get("error"):
                _record_task_step_summary(
                    runtime_host,
                    task_run_id=current_task.task_run_id,
                    step=f"task_tool_repair_required:{step_index}",
                    status="running",
                    summary="工具调用失败，正在根据失败原因调整处理路径。",
                    refs={"observation_ref": observation["observation_id"]},
                )
            current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
            control_result = _apply_runtime_control_boundary(runtime_host, task_run=current_task, agent_run=agent_run, boundary=f"after_tool_observation:{step_index}")
            if control_result is not None:
                return control_result
            observation_context = _observations_for_packet(
                runtime_host,
                current_task.task_run_id,
                current_fingerprint=runtime_fingerprint,
                pending_observations=raw_observations,
            )
            raw_observations = list(observation_context["raw_observations"])
            observations = list(observation_context["packet_observations"])
            execution_state = dict(observation_context["execution_state"])
            artifact_refs = _dedupe_artifacts([*list(observation_context["artifact_refs"]), *artifact_refs])
            continue

        if action_request.action_type == "respond":
            current_pending_steer_ids = [
                str(item.get("steer_id") or "")
                for item in list_pending_task_steers(runtime_host, current_task.task_run_id)
                if str(item.get("steer_id") or "")
            ]
            consumed_set = set(consumed_steer_ids)
            unconsumed_steer_ids = _dedupe_strings(
                [
                    *[item for item in included_steer_ids if item not in consumed_set],
                    *[item for item in current_pending_steer_ids if item not in consumed_set],
                ]
            )
            for steer in list_pending_task_steers(runtime_host, current_task.task_run_id):
                ensure_revision_for_steer(runtime_host, current_task.task_run_id, steer)
            active_revisions = list_active_task_contract_revisions(runtime_host, current_task.task_run_id)
            if unconsumed_steer_ids or active_revisions:
                repair_observation = _active_steer_completion_repair_observation(
                    task_run_id=current_task.task_run_id,
                    packet_ref=compilation.packet.packet_id,
                    action_request=action_request,
                    pending_steer_ids=unconsumed_steer_ids,
                    active_revisions=active_revisions,
                )
                raw_observations.append(repair_observation)
                runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
                runtime_host.event_log.append(
                    current_task.task_run_id,
                    "task_completion_repair_required",
                    payload={
                        "observation": repair_observation,
                        "pending_steer_ids": unconsumed_steer_ids,
                        "active_contract_revision_ids": [str(item.get("revision_id") or "") for item in active_revisions],
                    },
                    refs={"task_run_ref": current_task.task_run_id, "observation_ref": repair_observation["observation_id"]},
                )
                _record_task_step_summary(
                    runtime_host,
                    task_run_id=current_task.task_run_id,
                    step=f"task_completion_pending_steer_required:{step_index}",
                    status="running",
                    summary="用户补充要求或目标修订尚未被明确处理，正在继续推进。",
                )
                observation_context = _observations_for_packet(
                    runtime_host,
                    current_task.task_run_id,
                    current_fingerprint=runtime_fingerprint,
                    pending_observations=raw_observations,
                )
                raw_observations = list(observation_context["raw_observations"])
                observations = list(observation_context["packet_observations"])
                execution_state = dict(observation_context["execution_state"])
                artifact_refs = _dedupe_artifacts([*list(observation_context["artifact_refs"]), *artifact_refs])
                continue
            candidate_artifacts = _dedupe_artifacts([*artifact_refs, *_artifacts_from_action(action_request)])
            verdict = _verify_completion(
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly.to_dict(),
                task_run_id=current_task.task_run_id,
                contract=contract,
                artifact_refs=candidate_artifacts,
            )
            if not verdict["ok"]:
                repair_observation = _completion_repair_observation(
                    task_run_id=current_task.task_run_id,
                    packet_ref=compilation.packet.packet_id,
                    action_request=action_request,
                    verdict=verdict,
                )
                raw_observations.append(repair_observation)
                runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
                runtime_host.event_log.append(
                    current_task.task_run_id,
                    "task_completion_repair_required",
                    payload={"observation": repair_observation, "verdict": verdict},
                    refs={"task_run_ref": current_task.task_run_id, "observation_ref": repair_observation["observation_id"]},
                )
                _record_task_step_summary(
                    runtime_host,
                    task_run_id=current_task.task_run_id,
                    step=f"task_completion_repair_required:{step_index}",
                    status="running",
                    summary="当前结果还缺少验收证据，正在补齐。",
                )
                observation_context = _observations_for_packet(
                    runtime_host,
                    current_task.task_run_id,
                    current_fingerprint=runtime_fingerprint,
                    pending_observations=raw_observations,
                )
                raw_observations = list(observation_context["raw_observations"])
                observations = list(observation_context["packet_observations"])
                execution_state = dict(observation_context["execution_state"])
                artifact_refs = _dedupe_artifacts([*list(observation_context["artifact_refs"]), *artifact_refs])
                continue
            return _finish_executor_success(
                services,
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                final_answer=action_request.final_answer,
                final_action_diagnostics=dict(action_request.diagnostics or {}),
                artifact_refs=list(verdict.get("verified_artifacts") or []),
                observations=raw_observations,
            )

        if action_request.action_type == "ask_user":
            return _finish_executor_blocked(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                terminal_reason="user_input_required",
                payload={"user_question": action_request.user_question, "action_request": action_request.to_dict()},
            )

        if action_request.action_type == "block":
            return _finish_executor_blocked(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                terminal_reason=action_request.blocking_reason or "agent_blocked",
                payload={"action_request": action_request.to_dict()},
            )

    return _pause_executor_for_step_budget(
        runtime_host,
        task_run=current_task,
        agent_run=agent_run,
        max_steps=max_steps,
    )


async def _invoke_task_model_action(
    *,
    model_runtime: Any,
    packet: Any,
    task_run_id: str,
    session_id: str,
    invocation_index: int,
    model_selection: dict[str, Any],
    executor_epoch: int = 0,
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return None, {"status": "invalid", "validation_errors": ["model_runtime_unavailable"]}
    timeout_seconds = model_action_timeout_seconds(model_runtime, model_selection=model_selection)
    response = await asyncio.wait_for(
        call_model_invoker(
            invoker,
            list(packet.model_messages),
            model_selection=model_selection,
            accounting_context={
                "request_id": f"modelreq:{packet.packet_id}:{invocation_index}",
                "session_id": session_id,
                "task_run_id": task_run_id,
                "turn_id": task_run_id,
                "packet_ref": str(packet.packet_id or ""),
                "invocation_index": invocation_index,
                "source": "harness.loop.task_executor.model_action",
                "segment_plan": dict(getattr(packet, "segment_plan", {}) or {}),
            },
        ),
        timeout=timeout_seconds,
    )
    payload = parse_json_object(getattr(response, "content", response))
    payload.setdefault(
        "request_id",
        next_model_action_request_id(
            task_run_id=task_run_id,
            executor_epoch=executor_epoch,
            invocation_index=invocation_index,
            suffix=uuid.uuid4().hex[:8],
        ),
    )
    return model_action_request_from_payload(
        payload,
        turn_id=task_run_id,
        require_public_progress_note=True,
    )


async def _await_task_model_action_with_status(
    runtime_host: Any,
    *,
    task_run_id: str,
    session_id: str,
    packet_ref: str,
    step_index: int,
    executor_epoch: int = 0,
    model_runtime: Any,
    packet: Any,
    model_selection: dict[str, Any],
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    task = asyncio.create_task(
        _invoke_task_model_action(
            model_runtime=model_runtime,
            packet=packet,
            task_run_id=task_run_id,
            session_id=session_id,
            invocation_index=step_index,
            model_selection=model_selection,
            executor_epoch=executor_epoch,
        )
    )
    attach_model_task(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch, model_task=task)
    wait_round = 0
    last_progress_at = time.monotonic()
    try:
        while not task.done():
            signal = peek_executor_signal(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
            if signal is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise TaskRunExecutorInterrupted(signal)
            wait_timeout = max(0.001, min(1.0, _TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS))
            done, _pending = await asyncio.wait({task}, timeout=wait_timeout)
            if done:
                break
            now = time.monotonic()
            if now - last_progress_at >= _TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS:
                wait_round += 1
                last_progress_at = now
                if wait_round == 1:
                    _record_task_step_summary(
                        runtime_host,
                        task_run_id=task_run_id,
                        step=f"task_model_action_waiting:{step_index}",
                        status="running",
                        summary="正在思考。",
                        refs={"runtime_invocation_packet_ref": packet_ref},
                    )
                else:
                    _record_task_model_wait_heartbeat(
                        runtime_host,
                        task_run_id=task_run_id,
                        step=f"task_model_action_waiting:{step_index}",
                        wait_round=wait_round,
                        refs={"runtime_invocation_packet_ref": packet_ref},
                    )
        signal = peek_executor_signal(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
        if signal is not None:
            raise TaskRunExecutorInterrupted(signal)
        return await task
    except asyncio.CancelledError:
        signal = peek_executor_signal(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
        if signal is not None:
            raise TaskRunExecutorInterrupted(signal) from None
        raise
    finally:
        clear_model_task(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch, model_task=task)


async def _execute_task_tool_call(
    runtime_host: Any,
    *,
    services: TaskExecutorServices,
    task_run: Any,
    packet_ref: str,
    action_request: ModelActionRequest,
    runtime_assembly: dict[str, Any],
) -> dict[str, Any]:
    tool_name = str(action_request.tool_call.get("tool_name") or action_request.tool_call.get("name") or "").strip()
    tool_args = dict(action_request.tool_call.get("args") or action_request.tool_call.get("tool_args") or {})
    definition = getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}).get(tool_name)
    operation_id = str(getattr(definition, "operation_id", "") or tool_name)
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{task_run.task_run_id}:tool:{action_request.request_id}",
        task_id=task_run.task_id,
        plan_ref=f"orchplan:{task_run.task_run_id}:single-agent-task",
        stage_ref=f"orchstage:{task_run.task_run_id}:step",
        executor_type="tool",
        adopted_resource_policy_ref=f"respol:{task_run.task_run_id}:tool:{action_request.request_id}",
        operation_refs=(operation_id,),
        input_contract_ref=str(getattr(definition, "input_contract_ref", "") or ""),
        output_contract_ref=str(getattr(definition, "output_contract_ref", "") or ""),
        execution_graph_ref=f"execgraph:{task_run.task_run_id}:single-agent-task",
        diagnostics={"packet_ref": packet_ref, "source": "single_agent_task_executor"},
    )
    runtime_action = RuntimeActionRequest(
        request_id=action_request.request_id,
        task_run_id=task_run.task_run_id,
        request_type="tool_call",
        step_id=f"task-step:{action_request.request_id}",
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        payload={
            "tool_name": tool_name,
            "tool_call": {
                "id": action_request.request_id,
                "name": tool_name,
                "args": tool_args,
            },
        },
        created_at=time.time(),
    )
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run.task_run_id)
    file_policy = _task_file_policy(runtime_assembly, sandbox_policy=sandbox_policy)
    resource_policy = ResourcePolicy(
        policy_id=directive.adopted_resource_policy_ref,
        task_id=task_run.task_id,
        allowed_operations=(operation_id,),
        allowed_tools=(tool_name,),
        approval_policy="task_environment_sandbox",
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        diagnostics={"source": "single_agent_task_executor", "sandbox_policy": _public_policy(sandbox_policy)},
    )
    sandbox_policy = {
        **sandbox_policy,
        "session_id": task_run.session_id,
        **_task_runtime_scope_policy(task_run),
    }
    gate_result = runtime_host.operation_gate.check(
        operation_id,
        resource_policy=resource_policy,
        directive_ref=directive.directive_id,
        context=OperationGatePipelineContext(
            permission_mode="default",
            operation_input={"operation_id": operation_id, "tool_name": tool_name, "name": tool_name, "args": tool_args},
            validators=build_task_safety_validators(
                root_dir=runtime_host.backend_dir,
                safety_envelope={"write_mode": "bounded_create", "write_roots": _sandbox_relative_write_roots(sandbox_policy)},
                sandbox_policy=sandbox_policy,
            ),
            strip_dangerous_allow_rules=False,
        ),
    )
    if not getattr(gate_result, "allowed", False):
        observation = _executor_error_observation(
            task_run_id=task_run.task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=tool_name,
            tool_args=tool_args,
            error=str(getattr(gate_result, "reason", "") or "operation_gate_denied"),
        )
        observation["payload"]["operation_gate"] = gate_result.to_dict() if hasattr(gate_result, "to_dict") else {}
        observation["payload"]["runtime_fingerprint"] = _current_runtime_fingerprint(
            runtime_assembly,
            runtime_host=runtime_host,
            backend_config=services.backend_config,
        )
        return observation
    if tool_name in SUBAGENT_TOOL_NAMES:
        parent_agent_run = _ensure_executor_agent_run(runtime_host, task_run=task_run)
        payload = await SubagentControl(runtime_host, services=services).execute_tool(
            tool_name=tool_name,
            tool_args=tool_args,
            task_run=task_run,
            parent_agent_run=parent_agent_run,
            runtime_assembly=runtime_assembly,
        )
        observation = _subagent_control_observation(
            task_run_id=task_run.task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=tool_name,
            tool_args=tool_args,
            payload=payload,
        )
        observation["payload"]["operation_gate"] = gate_result.to_dict() if hasattr(gate_result, "to_dict") else {}
        observation["payload"]["runtime_fingerprint"] = _current_runtime_fingerprint(
            runtime_assembly,
            runtime_host=runtime_host,
            backend_config=services.backend_config,
        )
        return observation
    execution_context = build_execution_context(
        packet_ref=packet_ref,
        action_request_ref=action_request.request_id,
        admission_ref="task_executor_admission",
        tool_name=tool_name,
        operation_id=operation_id,
        workspace_root=ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve(),
        permission_snapshot={"permission_mode": runtime_host._current_permission_mode(), "task_run": True},
    )
    fingerprint = build_request_fingerprint(
        step_id=runtime_action.step_id,
        operation_id=operation_id,
        payload=runtime_action.payload,
    )
    registry = build_default_operation_registry()
    descriptor = registry.get_operation(operation_id)
    record = runtime_host.execution_store.create_record(
        task_run_id=task_run.task_run_id,
        step_id=runtime_action.step_id,
        action_request=runtime_action,
        directive_ref=directive.directive_id,
        operation_id=operation_id,
        executor_type="tool",
        replay_policy=derive_replay_policy(descriptor),
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=task_run.task_run_id,
            step_id=runtime_action.step_id,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
        ),
        diagnostics={"execution_context": execution_context.to_dict(), "operation_gate": gate_result.to_dict()},
    )
    if services.tool_runtime_executor is None:
        return _executor_error_observation(
            task_run_id=task_run.task_run_id,
            request_ref=action_request.request_id,
            directive_ref=directive.directive_id,
            tool_name=tool_name,
            tool_args=tool_args,
            error="tool_runtime_executor_unavailable",
        )
    result = await services.tool_runtime_executor.run(
        task_run_id=task_run.task_run_id,
        action_request=runtime_action,
        directive=directive,
        execution_record=record,
        execution_store=runtime_host.execution_store,
        sandbox_policy=sandbox_policy,
        file_management_policy=file_policy,
    )
    observation = dict(result.get("observation").to_dict() if hasattr(result.get("observation"), "to_dict") else result.get("observation") or {})
    if result.get("error") or result.get("recoverable_error"):
        observation["error"] = str(result.get("error") or result.get("recoverable_error") or "tool_execution_failed")
    observation.setdefault("payload", {})
    if isinstance(observation.get("payload"), dict):
        observation["payload"]["runtime_fingerprint"] = _current_runtime_fingerprint(
            runtime_assembly,
            runtime_host=runtime_host,
            backend_config=services.backend_config,
        )
    return observation


def _load_contract(runtime_host: Any, task_run: Any) -> dict[str, Any]:
    try:
        contract = runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    except Exception:
        contract = {}
    if contract:
        return dict(contract)
    return dict(dict(task_run.diagnostics or {}).get("contract") or {})


def _task_selection_from_task_run(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(task_run.diagnostics or {})
    original = dict(diagnostics.get("runtime_task_selection") or diagnostics.get("task_selection") or {})
    runtime_profile = dict(original.get("runtime_profile") or {})
    runtime_profile.setdefault("mode", "professional")
    return {
        **original,
        "runtime_mode": str(original.get("runtime_mode") or runtime_profile.get("mode") or "professional"),
        "runtime_profile": runtime_profile,
    }


def _task_model_selection(task_run: Any, *, agent_profile: Any | None = None) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    selection = diagnostics.get("model_selection")
    if isinstance(selection, dict) and selection:
        return dict(selection)
    task_selection = dict(diagnostics.get("runtime_task_selection") or diagnostics.get("task_selection") or {})
    runtime_profile = dict(task_selection.get("runtime_profile") or {})
    requirement = dict(runtime_profile.get("model_requirement") or {})
    model_profile = getattr(agent_profile, "model_profile", None)
    profile_payload = model_profile.to_dict() if hasattr(model_profile, "to_dict") else (dict(model_profile) if isinstance(model_profile, dict) else {})
    provider = str(requirement.get("provider") or requirement.get("provider_family") or profile_payload.get("provider") or "").strip()
    if provider in {"openai-compatible", "openai_compatible"}:
        provider = ""
    model = str(requirement.get("model") or requirement.get("model_family") or profile_payload.get("model") or "").strip()
    resolved: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "credential_ref": str(profile_payload.get("credential_ref") or "").strip(),
        "max_output_tokens": requirement.get("max_output_tokens") or requirement.get("preferred_output_tokens") or profile_payload.get("max_output_tokens"),
        "timeout_seconds": profile_payload.get("timeout_seconds"),
        "long_output_timeout_seconds": profile_payload.get("long_output_timeout_seconds"),
        "max_retries": profile_payload.get("max_retries"),
        "temperature": profile_payload.get("temperature"),
        "thinking_mode": str(requirement.get("thinking_mode") or profile_payload.get("thinking_mode") or "").strip(),
        "reasoning_effort": str(requirement.get("reasoning_effort") or profile_payload.get("reasoning_effort") or "").strip(),
        "stream_policy": dict(profile_payload.get("stream_policy") or {}),
        "diagnostics": {
            "authority": "harness.loop.task_executor.model_selection",
            "source": "agent_runtime_profile.model_profile+node.model_requirement",
            "agent_profile_id": str(getattr(agent_profile, "agent_profile_id", "") or ""),
            "model_profile_id": str(profile_payload.get("profile_id") or ""),
            "requirement_profile_ref": str(requirement.get("profile_ref") or ""),
            "requirement_model_family": str(requirement.get("model_family") or ""),
        },
    }
    return normalize_model_selection_for_invocation(resolved)


def _origin_kind(task_run: Any) -> str:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    origin = dict(diagnostics.get("origin") or {})
    return str(origin.get("origin_kind") or diagnostics.get("origin_kind") or "").strip()


def _authorized_graph_node_executor_resume(task_run: Any, *, authorization: dict[str, Any] | None) -> bool:
    if not authorization:
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    if _origin_kind(task_run) != "graph_node_assigned":
        return False
    if str(getattr(task_run, "status", "") or "") != "waiting_executor":
        return False
    executor_status = str(diagnostics.get("executor_status") or "").strip()
    if executor_status not in {"", "waiting_executor"}:
        return False
    return (
        str(diagnostics.get("graph_run_id") or "") == str(authorization.get("graph_run_id") or "")
        and str(diagnostics.get("graph_work_order_id") or "") == str(authorization.get("graph_work_order_id") or "")
        and str(diagnostics.get("graph_node_id") or "") == str(authorization.get("graph_node_id") or "")
    )


def _recover_stale_graph_node_executor_claim(
    runtime_host: Any,
    *,
    task_run: Any,
    graph_node_authorization: dict[str, Any] | None,
) -> Any | None:
    if not graph_node_authorization:
        return None
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    if _origin_kind(task_run) != "graph_node_assigned":
        return None
    if (
        str(diagnostics.get("graph_run_id") or "") != str(graph_node_authorization.get("graph_run_id") or "")
        or str(diagnostics.get("graph_work_order_id") or "") != str(graph_node_authorization.get("graph_work_order_id") or "")
        or str(diagnostics.get("graph_node_id") or "") != str(graph_node_authorization.get("graph_node_id") or "")
    ):
        return None
    executor_epoch = int(diagnostics.get("executor_epoch") or 0)
    if executor_epoch_is_live(runtime_host, task_run_id=task_run.task_run_id, executor_epoch=executor_epoch):
        return None
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "graph_node_executor_claim_recovered",
        payload={
            "task_run_id": task_run.task_run_id,
            "previous_status": str(getattr(task_run, "status", "") or ""),
            "previous_executor_status": str(diagnostics.get("executor_status") or ""),
            "executor_epoch": executor_epoch,
        },
        refs={"task_run_ref": task_run.task_run_id},
    )
    recovered = replace(
        task_run,
        status="waiting_executor",
        updated_at=event.created_at or time.time(),
        latest_event_offset=event.offset,
        terminal_reason="",
        diagnostics={
            **_strip_runtime_lease_diagnostics(diagnostics),
            "executor_status": "waiting_executor",
            "latest_step": "graph_node_executor_claim_recovered",
            "latest_step_status": "waiting_executor",
            "latest_step_summary": "图节点执行器已从中断的运行占用恢复，可以重新接管。",
            "recoverable_error": {
                "error_code": "graph_node_executor_claim_lost",
                "retryable": True,
            },
            "recovery_action": "rerun_task_executor",
        },
    )
    runtime_host.state_index.upsert_task_run(recovered)
    return recovered


def _task_sandbox_policy(runtime_assembly: dict[str, Any], *, runtime_host: Any, task_run_id: str) -> dict[str, Any]:
    environment = dict(runtime_assembly.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    sandbox = dict(environment.get("sandbox_policy") or {})
    contract = _load_contract_for_policy(runtime_host, task_run_id)
    project_root = ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve()
    sandbox_root = str(sandbox.get("sandbox_root") or "").strip()
    if not sandbox_root:
        namespace = task_run_id.replace(":", "_")
        sandbox_root = str((Path(runtime_host.root_dir) / "sandboxes" / namespace).resolve())
    artifact_root = str(storage.get("artifact_root") or "").strip()
    publish_scopes = _dedupe_strings([*([artifact_root] if artifact_root else []), *_explicit_contract_write_roots(contract)])
    scratch_scopes = _task_scratch_write_scopes(storage)
    write_scopes = _dedupe_strings([*list(sandbox.get("write_scopes") or []), *publish_scopes, *scratch_scopes])
    materialized_roots = _dedupe_strings([*_explicit_contract_materialized_roots(contract), *publish_scopes])
    return {
        **sandbox,
        "enabled": True,
        "sandbox_root": sandbox_root,
        "workspace_root": str(project_root),
        "artifact_root": artifact_root,
        "write_scopes": write_scopes,
        "publish_scopes": publish_scopes,
        "scratch_scopes": scratch_scopes,
        "materialized_roots": materialized_roots,
        "read_scopes": ["."],
        "approval_policy": "sandboxed_side_effects",
        "side_effect_operations": list(sandbox.get("side_effect_operations") or ("op.write_file", "op.edit_file", "op.shell", "op.browser_control", "op.image_generate")),
    }


def _task_runtime_scope_policy(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    runtime_scope = {
        **dict(diagnostics.get("runtime_scope") or {}),
    }
    for key in ("project_id", "scope_id", "graph_run_id", "graph_node_id", "graph_work_order_id"):
        value = str(diagnostics.get(key) or "").strip()
        if value:
            runtime_scope.setdefault(key, value)
    if not runtime_scope:
        return {}
    return {
        "runtime_scope": runtime_scope,
        **({"project_id": str(runtime_scope.get("project_id") or "")} if runtime_scope.get("project_id") else {}),
    }


def _task_file_policy(runtime_assembly: dict[str, Any], *, sandbox_policy: dict[str, Any]) -> dict[str, Any]:
    environment = dict(runtime_assembly.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    return {
        "file_management": dict(environment.get("file_management") or {}),
        "storage_space": storage,
        "artifact_root": str(storage.get("artifact_root") or sandbox_policy.get("artifact_root") or ""),
    }


def _sandbox_relative_write_roots(sandbox_policy: dict[str, Any]) -> list[str]:
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or ".")).resolve()
    roots: list[str] = []
    for raw in list(sandbox_policy.get("write_scopes") or []):
        text = str(raw or "").replace("\\", "/").strip().strip("/")
        if not text:
            continue
        try:
            roots.append((sandbox_root / text).resolve().relative_to(sandbox_root).as_posix())
        except Exception:
            roots.append(text)
    return roots


def _task_scratch_write_scopes(storage: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    for key in ("environment_storage_root", "runtime_state_root", "cache_root"):
        root = _normalize_contract_path(str(storage.get(key) or ""))
        if not root:
            continue
        if key == "environment_storage_root":
            roots.append(f"{root}/tmp")
        else:
            roots.append(root)
    return _dedupe_strings(roots)


def _load_contract_for_policy(runtime_host: Any, task_run_id: str) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return {}
    return _load_contract(runtime_host, task_run)


def _explicit_contract_write_roots(contract: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    for path in _explicit_contract_paths(contract):
        normalized = _normalize_contract_path(path)
        if not normalized:
            continue
        if normalized.endswith("/"):
            roots.append(normalized.strip("/"))
        else:
            parent = str(Path(normalized).parent).replace("\\", "/").strip(".")
            roots.append(parent if parent else normalized)
    return _dedupe_strings(roots)


def _explicit_contract_materialized_roots(contract: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    for path in _explicit_contract_paths(contract):
        normalized = _normalize_contract_path(path)
        if not normalized:
            continue
        candidate = normalized.strip("/") if normalized.endswith("/") else str(Path(normalized).parent).replace("\\", "/").strip(".")
        if candidate:
            roots.append(candidate)
    return _dedupe_strings(roots)


def _explicit_contract_paths(contract: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in list(contract.get("required_artifacts") or []):
        if not isinstance(item, dict):
            continue
        for key in ("path", "output_path", "artifact_path", "target_path"):
            value = str(item.get(key) or "").strip()
            if value:
                paths.append(value)
    for item in list(contract.get("required_verifications") or []):
        if not isinstance(item, dict):
            continue
        for key in ("path", "output_path", "artifact_path", "target_path", "verification_path"):
            value = str(item.get(key) or "").strip()
            if value:
                paths.append(value)
    return _dedupe_strings(paths)


def _normalize_contract_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").strip().strip("'\"`")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.strip("/")
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        return ""
    if "://" in normalized or normalized.startswith(("/", "\\")):
        return ""
    return normalized


def _dedupe_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").replace("\\", "/").strip().strip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _verify_completion(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    contract: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    required_artifacts = [dict(item) for item in list(contract.get("required_artifacts") or []) if isinstance(item, dict)]
    artifact_refs = _dedupe_artifacts(
        [
            *artifact_refs,
            *_discover_sandbox_artifact_refs(
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly,
                task_run_id=task_run_id,
                contract=contract,
            ),
        ]
    )
    verified_artifacts = _verified_artifacts(
        runtime_host=runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        artifact_refs=artifact_refs,
    )
    if required_artifacts and not verified_artifacts:
        return {
            "ok": False,
            "missing": ["required_artifacts"],
            "required_artifacts": required_artifacts,
            "artifact_refs": artifact_refs,
            "verified_artifacts": [],
            "reason": "required artifacts must resolve to existing files",
        }
    return {"ok": True, "missing": [], "verified_artifacts": verified_artifacts}


def _finish_executor_success(
    services: TaskExecutorServices,
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    final_answer: str,
    final_action_diagnostics: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    result_ref = runtime_host.runtime_objects.put_object(
        "agent_run_result",
        f"{agent_run.agent_run_id}:result",
        {
            "final_answer": final_answer,
            "artifact_refs": artifact_refs,
            "observation_refs": [str(item.get("observation_id") or "") for item in observations if item.get("observation_id")],
        },
    )
    now = time.time()
    updated_agent = replace(agent_run, status="completed", updated_at=now, result_ref=result_ref)
    runtime_host.state_index.upsert_agent_run(updated_agent)
    runtime_host.state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id=f"agresult:{agent_run.agent_run_id}",
            agent_run_id=agent_run.agent_run_id,
            task_run_id=task_run.task_run_id,
            agent_id=agent_run.agent_id,
            status="completed",
            output_ref=result_ref,
            summary=compact_text(final_answer, limit=500),
            artifact_refs=tuple(str(item.get("path") or item.get("src") or item) for item in artifact_refs),
            created_at=now,
            diagnostics={"artifact_refs": artifact_refs},
        )
    )
    lifecycle = _load_lifecycle(runtime_host, task_run)
    finished_task, finished_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=replace(
            task_run,
            diagnostics={
                **dict(task_run.diagnostics or {}),
                "artifact_refs": artifact_refs,
                "final_answer": final_answer,
                "final_action_diagnostics": dict(final_action_diagnostics or {}),
            },
        ),
        lifecycle=lifecycle,
        status="completed",
        terminal_reason="completed",
        observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_run_completed",
        status="completed",
        summary="已完成收口并记录交付证据。",
    )
    append_work_rollout_item(
        runtime_host,
        task_run=finished_task,
        item_type="final_response",
        title="已完成",
        status="completed",
        summary="已完成收口并记录交付证据。",
        agent_brief_output=final_answer,
        event_offset=_event_offset(event),
        refs={"task_run_ref": finished_task.task_run_id},
        payload={"artifact_refs": artifact_refs, "final_answer": final_answer},
    )
    _commit_task_run_final_message(
        services,
        task_run=finished_task,
        final_answer=final_answer,
    )
    _sync_engagement_closeout(runtime_host, finished_task.task_run_id)
    return {
        "ok": True,
        "task_run": finished_task.to_dict(),
        "lifecycle": finished_lifecycle.to_dict(),
        "event": event,
        "final_answer": final_answer,
        "artifact_refs": artifact_refs,
    }


def _commit_task_run_final_message(
    services: TaskExecutorServices,
    *,
    task_run: Any,
    final_answer: str,
) -> None:
    committer = getattr(services, "assistant_message_committer", None)
    if not callable(committer):
        return
    decision = build_assistant_session_message_commit_decision(
        session_id=str(getattr(task_run, "session_id", "") or ""),
        task_run_id=str(getattr(task_run, "task_run_id", "") or ""),
        task_id=str(getattr(task_run, "task_id", "") or ""),
        content=final_answer,
        answer_channel="final_answer",
        answer_source="harness.loop.task_executor.completed",
        answer_canonical_state="final",
        answer_persist_policy="persist_canonical",
        answer_finalization_policy="assistant_final",
        completion_state="completed",
        terminal_reason="completed",
        source="harness.loop.task_executor",
    )
    runtime_host = services.runtime_host
    runtime_host.event_log.append(
        str(getattr(task_run, "task_run_id", "") or ""),
        "task_run_final_message_commit_checked",
        payload={"commit_gate": decision.to_dict()},
        refs={"task_run_ref": str(getattr(task_run, "task_run_id", "") or "")},
    )
    if not decision.commit_allowed:
        return
    try:
        result = committer(dict(decision.commit_candidate.payload))
        if hasattr(result, "__await__"):
            runtime_host.event_log.append(
                str(getattr(task_run, "task_run_id", "") or ""),
                "task_run_final_message_commit_failed",
                payload={"error": "async_committer_not_supported", "authority": "harness.loop.task_executor"},
                refs={"task_run_ref": str(getattr(task_run, "task_run_id", "") or "")},
            )
            return
    except Exception as exc:
        runtime_host.event_log.append(
            str(getattr(task_run, "task_run_id", "") or ""),
            "task_run_final_message_commit_failed",
            payload={"error": str(exc), "authority": "harness.loop.task_executor"},
            refs={"task_run_ref": str(getattr(task_run, "task_run_id", "") or "")},
        )


def _finish_executor_failure(runtime_host: Any, *, task_run: Any, agent_run: Any, terminal_reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _finish_executor_terminal(
        runtime_host,
        task_run=task_run,
        agent_run=agent_run,
        status="failed",
        terminal_reason=terminal_reason,
        payload=payload,
    )


def _finish_executor_blocked(runtime_host: Any, *, task_run: Any, agent_run: Any, terminal_reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _finish_executor_terminal(
        runtime_host,
        task_run=task_run,
        agent_run=agent_run,
        status="blocked",
        terminal_reason=terminal_reason,
        payload=payload,
    )


def _finish_executor_terminal(runtime_host: Any, *, task_run: Any, agent_run: Any, status: str, terminal_reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    lifecycle = _load_lifecycle(runtime_host, task_run)
    terminal_payload = dict(payload or {})
    action_request_payload = dict(terminal_payload.get("action_request") or {})
    action_diagnostics = dict(action_request_payload.get("diagnostics") or {})
    promoted_terminal_diagnostics = {
        key: action_diagnostics[key]
        for key in ("recoverable_error", "recovery_action")
        if key in action_diagnostics
    }
    merged_diagnostics = {
        **dict(task_run.diagnostics or {}),
        **terminal_payload,
        **promoted_terminal_diagnostics,
    }
    closeout_status, closeout_reason, closeout_diagnostics, agent_status = _normalize_executor_terminal_closeout(
        status=status,
        terminal_reason=terminal_reason,
        diagnostics=merged_diagnostics,
    )
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status=agent_status,
            updated_at=now,
            diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": closeout_reason},
        )
    )
    finished_task, finished_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=replace(
            task_run,
            diagnostics=closeout_diagnostics,
        ),
        lifecycle=lifecycle,
        status=closeout_status,  # type: ignore[arg-type]
        terminal_reason=closeout_reason,
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step=f"task_run_{closeout_status}",
        status=closeout_status,
        summary=f"当前处理已停止：{closeout_reason}。",
    )
    append_work_rollout_item(
        runtime_host,
        task_run=finished_task,
        item_type="pause_boundary" if closeout_status == "waiting_executor" else ("interrupted_boundary" if closeout_status in {"aborted", "failed", "blocked"} else "progress"),
        title="等待继续" if closeout_status == "waiting_executor" else ("已中断" if closeout_status in {"aborted", "failed", "blocked"} else "处理停止"),
        status=closeout_status,
        summary=f"当前处理已停止：{closeout_reason}。",
        event_offset=_event_offset(event),
        refs={"task_run_ref": finished_task.task_run_id},
        payload={"terminal_reason": closeout_reason},
    )
    _sync_engagement_closeout(runtime_host, finished_task.task_run_id)
    return {"ok": False, "task_run": finished_task.to_dict(), "lifecycle": finished_lifecycle.to_dict(), "event": event, "error": closeout_reason}


def _normalize_executor_terminal_closeout(*, status: str, terminal_reason: str, diagnostics: dict[str, Any]) -> tuple[str, str, dict[str, Any], str]:
    payload = dict(diagnostics or {})
    recoverable = payload.get("recoverable_error")
    recovery_action = str(payload.get("recovery_action") or "")
    if terminal_reason == "user_input_required" and recovery_action not in {"resume_task_run", "rerun_task_executor"}:
        recovery_action = "resume_task_run"
        recoverable = {
            "error_code": "user_input_required",
            "retryable": True,
            "user_message": "任务正在等待用户补充输入，收到后可以继续。",
        }
    retryable = isinstance(recoverable, dict) and recoverable.get("retryable") is not False
    can_same_run_recover = retryable and recovery_action in {"resume_task_run", "rerun_task_executor"}
    payload = _strip_runtime_lease_diagnostics(payload)
    if status == "completed":
        return "completed", terminal_reason or "completed", {**payload, "executor_status": "completed"}, "completed"
    if status == "aborted":
        return "aborted", terminal_reason or "user_aborted", {**payload, "executor_status": "stopped"}, "failed"
    if status in {"blocked", "failed"} and can_same_run_recover:
        return (
            "waiting_executor",
            terminal_reason or "waiting_executor",
            {
                **payload,
                "executor_status": "waiting_executor",
                "recoverable_error": recoverable,
                "recovery_action": recovery_action,
                "latest_step_status": "waiting_executor",
            },
            "failed",
        )
    executor_status = "failed" if status == "failed" else "blocked"
    return status, terminal_reason, {**payload, "executor_status": executor_status}, "failed"


def _finish_without_executor(runtime_host: Any, *, task_run: Any, status: str, terminal_reason: str) -> tuple[Any, TaskLifecycleRecord, dict[str, Any]]:
    lifecycle = _load_lifecycle(runtime_host, task_run)
    finished = finish_task_lifecycle(
        runtime_host,
        task_run=task_run,
        lifecycle=lifecycle,
        status=status,  # type: ignore[arg-type]
        terminal_reason=terminal_reason,
    )
    _sync_engagement_closeout(runtime_host, finished[0].task_run_id)
    return finished


def _sync_engagement_closeout(runtime_host: Any, task_run_id: str) -> None:
    backend_dir = getattr(runtime_host, "backend_dir", None)
    if backend_dir is None:
        return
    try:
        from task_system.engagement import sync_engagement_runs_for_terminal_task

        sync_engagement_runs_for_terminal_task(
            backend_dir=backend_dir,
            runtime_host=runtime_host,
            task_run_id=task_run_id,
        )
    except Exception as exc:
        if hasattr(runtime_host, "event_log"):
            runtime_host.event_log.append(
                task_run_id,
                "engagement_closeout_sync_failed",
                payload={"error": str(exc), "authority": "task_system.engagement_closeout"},
            )


def _is_recoverable_protocol_terminal(task_run: Any) -> bool:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    recoverable = dict(diagnostics.get("recoverable_error") or {})
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or "")
    return (
        str(getattr(task_run, "status", "") or "") in {"failed", "blocked"}
        and terminal_reason in {"model_action_invalid", "model_action_protocol_repair_required", "task_execution_step_budget_exceeded"}
        and bool(recoverable.get("retryable", True))
    )


def _pause_executor_for_model_recovery(
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    packet_ref: str,
    step_index: int,
    error: Exception,
) -> dict[str, Any]:
    now = time.time()
    error_payload = _model_error_payload(error)
    executor_epoch = int(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_epoch") or 0)
    observation = {
        "observation_id": f"rtobs:{task_run.task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run.task_run_id,
        "observation_type": "executor_error",
        "source": "system:model_runtime",
        "request_ref": next_model_action_request_id(
            task_run_id=task_run.task_run_id,
            executor_epoch=executor_epoch,
            invocation_index=step_index,
            suffix="model-call-failed",
        ),
        "directive_ref": packet_ref,
        "content_chars": len(str(error_payload.get("detail") or "")),
        "payload": error_payload,
        "needs_model_followup": False,
        "created_at": now,
        "authority": "orchestration.runtime_observation",
        "error": str(error_payload.get("code") or "model_call_failed"),
    }
    runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
    failed_event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_executor_model_call_failed",
        payload={"observation": observation},
        refs={"task_run_ref": task_run.task_run_id, "observation_ref": observation["observation_id"], "runtime_invocation_packet_ref": packet_ref},
    )
    paused_task = replace(
        task_run,
        status="blocked",
        updated_at=failed_event.created_at or now,
        latest_event_offset=failed_event.offset,
        terminal_reason="model_call_recovery_required",
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "executor_status": "blocked",
            "recoverable_error": error_payload,
            "recovery_action": "rerun_task_executor",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status="blocked",
            updated_at=now,
            diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": "model_call_recovery_required", "recoverable_error": error_payload},
        )
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_executor_model_recovery_required",
        status="blocked",
        summary=f"模型调用失败，任务已保留在可续跑状态：{error_payload['user_message']}",
        refs={"observation_ref": observation["observation_id"]},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=paused_task,
        item_type="interrupted_boundary",
        title="等待恢复",
        status="blocked",
        summary=f"模型调用失败，任务已保留在可续跑状态：{error_payload['user_message']}",
        event_offset=failed_event.offset,
        refs={"observation_ref": observation["observation_id"], "runtime_invocation_packet_ref": packet_ref},
        payload={"terminal_reason": "model_call_recovery_required", "recoverable_error": error_payload},
    )
    return {"ok": False, "task_run": paused_task.to_dict(), "observation": observation, "error": "model_call_recovery_required"}


def _apply_runtime_control_boundary(runtime_host: Any, *, task_run: Any, agent_run: Any | None, boundary: str) -> dict[str, Any] | None:
    current = runtime_host.state_index.get_task_run(task_run.task_run_id) or task_run
    state = task_run_control_state(current)
    if state == _TASK_RUN_PAUSE_REQUESTED:
        return _pause_executor_for_user_control(runtime_host, task_run=current, agent_run=agent_run, boundary=boundary)
    if state == _TASK_RUN_STOP_REQUESTED:
        return _stop_executor_for_user_control(runtime_host, task_run=current, agent_run=agent_run, boundary=boundary)
    if state == _TASK_RUN_REPLAN_REQUESTED:
        return _replan_executor_for_user_control(runtime_host, task_run=current, agent_run=agent_run, boundary=boundary, signal=None)
    return None


def _pause_executor_for_user_control(runtime_host: Any, *, task_run: Any, agent_run: Any | None, boundary: str) -> dict[str, Any]:
    now = time.time()
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_run_paused",
        payload={"task_run_id": task_run.task_run_id, "boundary": boundary, "control": _runtime_control_payload(task_run)},
        refs={"task_run_ref": task_run.task_run_id},
    )
    diagnostics = _diagnostics_with_runtime_control(
        _strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
        state=_TASK_RUN_PAUSED,
        requested_by=str(_runtime_control_payload(task_run).get("requested_by") or "user"),
        requested_at=float(_runtime_control_payload(task_run).get("requested_at") or now),
        reason=str(_runtime_control_payload(task_run).get("reason") or ""),
        latest_step="task_run_paused",
        latest_step_status="waiting_executor",
        latest_step_summary="已在安全边界暂停，后续可以从这里继续。",
    )
    paused_task = replace(
        task_run,
        status="waiting_executor",
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        terminal_reason="waiting_executor",
        diagnostics={
            **diagnostics,
            "executor_status": "waiting_executor",
            "recovery_action": "resume_task_run",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    if agent_run is not None:
        runtime_host.state_index.upsert_agent_run(
            replace(
                agent_run,
                status="blocked",
                updated_at=event.created_at or now,
                diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": "user_paused", "runtime_control": _runtime_control_payload(paused_task)},
            )
        )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_run_paused",
        status="waiting_executor",
        summary="已在安全边界暂停，后续可以从这里继续。",
    )
    append_work_rollout_item(
        runtime_host,
        task_run=paused_task,
        item_type="pause_boundary",
        title="已暂停",
        status="waiting_executor",
        summary="已在安全边界暂停，后续可以从这里继续。",
        event_offset=event.offset,
        refs={"task_run_ref": task_run.task_run_id},
    )
    return {"ok": False, "task_run": paused_task.to_dict(), "error": "task_run_paused", "retryable": True}


def _stop_executor_for_user_control(runtime_host: Any, *, task_run: Any, agent_run: Any | None, boundary: str) -> dict[str, Any]:
    now = time.time()
    control = _runtime_control_payload(task_run)
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_run_stopped",
        payload={"task_run_id": task_run.task_run_id, "boundary": boundary, "control": control},
        refs={"task_run_ref": task_run.task_run_id},
    )
    stopped_task = replace(
        task_run,
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        diagnostics={
            **_diagnostics_with_runtime_control(
                _strip_runtime_lease_diagnostics(dict(task_run.diagnostics or {})),
                state=_TASK_RUN_STOPPED,
                requested_by=str(control.get("requested_by") or "user"),
                requested_at=float(control.get("requested_at") or now),
                reason=str(control.get("reason") or ""),
                latest_step="task_run_stopped",
                latest_step_status="aborted",
                latest_step_summary="任务已按用户要求停止。",
            ),
            "executor_status": "stopped",
        },
    )
    if agent_run is not None:
        runtime_host.state_index.upsert_agent_run(
            replace(
                agent_run,
                status="killed",
                updated_at=event.created_at or now,
                diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": "user_aborted", "runtime_control": _runtime_control_payload(stopped_task)},
            )
        )
    finished_task, finished_lifecycle, finished_event = _finish_user_stopped_task(
        runtime_host,
        task_run=stopped_task,
        reason=str(control.get("reason") or ""),
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_run_stopped",
        status="aborted",
        summary="任务已按用户要求停止。",
    )
    return {
        "ok": False,
        "task_run": finished_task.to_dict(),
        "lifecycle": finished_lifecycle.to_dict(),
        "event": finished_event,
        "error": "user_aborted",
    }


def _replan_executor_for_user_control(
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any | None,
    boundary: str,
    signal: ExecutorControlSignal | None,
) -> dict[str, Any]:
    now = time.time()
    control = _runtime_control_payload(task_run)
    requested_by = str(control.get("requested_by") or getattr(signal, "requested_by", "") or "user")
    requested_at = float(control.get("requested_at") or getattr(signal, "requested_at", 0.0) or now)
    reason = str(control.get("reason") or getattr(signal, "reason", "") or "conversation_steer_while_running")
    steer_ref = str(getattr(signal, "steer_ref", "") or "")
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_run_interrupted_for_replan",
        payload={"task_run_id": task_run.task_run_id, "boundary": boundary, "reason": reason, "steer_ref": steer_ref},
        refs={"task_run_ref": task_run.task_run_id, "steer_ref": steer_ref},
    )
    recoverable_error = {
        "error_code": "user_interrupt_replan_required",
        "retryable": True,
        "user_message": "收到新的补充要求，已中断当前步骤并准备重新规划。",
    }
    diagnostics = _diagnostics_with_runtime_control(
        _strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
        state=_TASK_RUN_INTERRUPTED_FOR_REPLAN,
        requested_by=requested_by,
        requested_at=requested_at,
        reason=reason,
        latest_step="task_run_interrupted_for_replan",
        latest_step_status="waiting_executor",
        latest_step_summary="收到新的补充要求，已中断当前步骤并准备重新规划。",
    )
    paused_task = replace(
        task_run,
        status="waiting_executor",
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        terminal_reason="waiting_executor",
        diagnostics={
            **diagnostics,
            "executor_status": "waiting_executor",
            "recoverable_error": recoverable_error,
            "recovery_action": "resume_task_run",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    if agent_run is not None:
        runtime_host.state_index.upsert_agent_run(
            replace(
                agent_run,
                status="blocked",
                updated_at=event.created_at or now,
                diagnostics={
                    **dict(agent_run.diagnostics or {}),
                    "terminal_reason": "user_interrupt_replan_required",
                    "runtime_control": _runtime_control_payload(paused_task),
                    "recoverable_error": recoverable_error,
                },
            )
        )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_run_interrupted_for_replan",
        status="waiting_executor",
        summary="收到新的补充要求，已中断当前步骤并准备重新规划。",
        refs={"steer_ref": steer_ref},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=paused_task,
        item_type="interrupted_boundary",
        title="重新规划",
        status="waiting_executor",
        summary="收到新的补充要求，已中断当前步骤并准备重新规划。",
        event_offset=event.offset,
        refs={"task_run_ref": task_run.task_run_id, "steer_ref": steer_ref},
        payload={"terminal_reason": "user_interrupt_replan_required", "recoverable_error": recoverable_error},
    )
    return {"ok": False, "task_run": paused_task.to_dict(), "error": "user_interrupt_replan_required", "retryable": True}


def _finish_user_stopped_task(runtime_host: Any, *, task_run: Any, reason: str = "") -> tuple[Any, TaskLifecycleRecord, dict[str, Any]]:
    lifecycle = _load_lifecycle(runtime_host, task_run)
    stopped_diagnostics = _diagnostics_with_runtime_control(
        _strip_runtime_lease_diagnostics(dict(task_run.diagnostics or {})),
        state=_TASK_RUN_STOPPED,
        requested_by=str(_runtime_control_payload(task_run).get("requested_by") or "user"),
        requested_at=float(_runtime_control_payload(task_run).get("requested_at") or time.time()),
        reason=reason or str(_runtime_control_payload(task_run).get("reason") or ""),
        latest_step="task_run_stopped",
        latest_step_status="aborted",
        latest_step_summary="任务已按用户要求停止。",
    )
    for key in ("recoverable_error", "recovery_action", "pending_user_steer_count", "latest_user_steer_ref", "active_contract_revision_count", "latest_contract_revision_ref"):
        stopped_diagnostics.pop(key, None)
    stopped_task, stopped_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=replace(
            task_run,
            diagnostics={
                **stopped_diagnostics,
                "executor_status": "stopped",
            },
        ),
        lifecycle=lifecycle,
        status="aborted",
        terminal_reason="user_aborted",
    )
    append_work_rollout_item(
        runtime_host,
        task_run=stopped_task,
        item_type="interrupted_boundary",
        title="已停止",
        status="aborted",
        summary="任务已按用户要求停止。",
        event_offset=_event_offset(event),
        refs={"task_run_ref": stopped_task.task_run_id},
        payload={"terminal_reason": "user_aborted"},
    )
    _sync_engagement_closeout(runtime_host, stopped_task.task_run_id)
    return stopped_task, stopped_lifecycle, event


def _pause_executor_for_step_budget(runtime_host: Any, *, task_run: Any, agent_run: Any, max_steps: int) -> dict[str, Any]:
    now = time.time()
    payload = {
        "error_code": "task_execution_step_budget_exhausted",
        "retryable": True,
        "max_steps": int(max_steps or _MAX_TASK_EXECUTION_STEPS),
        "user_message": "本轮执行步数预算已用尽，任务保持可续跑状态。",
    }
    paused_task = replace(
        task_run,
        status="waiting_executor",
        updated_at=now,
        terminal_reason="waiting_executor",
        diagnostics={
            **_strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
            "executor_status": "waiting_executor",
            "recoverable_error": payload,
            "recovery_action": "rerun_task_executor",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status="blocked",
            updated_at=now,
            diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": "task_execution_step_budget_exhausted", "recoverable_error": payload},
        )
    )
    budget_event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_executor_step_budget_exhausted",
        payload={"task_run": paused_task.to_dict(), "max_steps": int(max_steps or _MAX_TASK_EXECUTION_STEPS)},
        refs={"task_run_ref": task_run.task_run_id},
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_executor_waiting_next_run",
        status="waiting_executor",
        summary="本轮步骤预算已用尽，当前工作会等待后续继续。",
    )
    append_work_rollout_item(
        runtime_host,
        task_run=replace(paused_task, latest_event_offset=budget_event.offset, updated_at=budget_event.created_at or now),
        item_type="pause_boundary",
        title="等待继续",
        status="waiting_executor",
        summary="本轮步骤预算已用尽，当前工作会等待后续继续。",
        event_offset=budget_event.offset,
        refs={"task_run_ref": task_run.task_run_id},
        payload={"terminal_reason": "task_execution_step_budget_exhausted"},
    )
    return {"ok": False, "task_run": paused_task.to_dict(), "error": "task_execution_step_budget_exhausted", "retryable": True}


def _model_error_payload(error: Exception) -> dict[str, Any]:
    return {
        "error_code": "model_call_failed",
        "code": str(getattr(error, "code", "") or error.__class__.__name__),
        "retryable": bool(getattr(error, "retryable", True)),
        "user_message": str(getattr(error, "user_message", "") or "模型调用失败，任务可以稍后续跑。"),
        "provider": str(getattr(error, "provider", "") or ""),
        "model": str(getattr(error, "model", "") or ""),
        "detail": str(getattr(error, "detail", "") or error),
    }


def _event_offset(event: Any) -> int:
    if isinstance(event, dict):
        try:
            return int(event.get("offset", -1))
        except (TypeError, ValueError):
            return -1
    try:
        return int(getattr(event, "offset", -1))
    except (TypeError, ValueError):
        return -1


def _load_lifecycle(runtime_host: Any, task_run: Any) -> TaskLifecycleRecord:
    try:
        payload = runtime_host.runtime_objects.get_object(f"rtobj:task_lifecycle:{task_run.task_run_id}")
    except Exception:
        payload = {}
    if payload:
        return TaskLifecycleRecord(
            task_run_id=str(payload.get("task_run_id") or task_run.task_run_id),
            contract_ref=str(payload.get("contract_ref") or task_run.task_contract_ref),
            status=str(payload.get("status") or "running"),  # type: ignore[arg-type]
            created_at=float(payload.get("created_at") or task_run.created_at or time.time()),
            updated_at=float(payload.get("updated_at") or task_run.updated_at or time.time()),
            terminal_reason=str(payload.get("terminal_reason") or ""),
            acceptance_refs=tuple(str(item) for item in list(payload.get("acceptance_refs") or [])),
            observation_refs=tuple(str(item) for item in list(payload.get("observation_refs") or [])),
        )
    return TaskLifecycleRecord(
        task_run_id=task_run.task_run_id,
        contract_ref=task_run.task_contract_ref,
        status="running",
        created_at=float(task_run.created_at or time.time()),
        updated_at=float(task_run.updated_at or time.time()),
    )


def _ensure_executor_agent_run(runtime_host: Any, *, task_run: Any) -> Any:
    expected_id = f"agrun:{task_run.task_run_id}:main"
    runs = runtime_host.state_index.list_task_agent_runs(task_run.task_run_id)
    for item in runs:
        if str(getattr(item, "agent_run_id", "") or "") == expected_id:
            updated = replace(item, status="running", updated_at=time.time())
            runtime_host.state_index.upsert_agent_run(updated)
            return updated
    runs = [
        item
        for item in runs
        if not str(getattr(item, "parent_agent_run_ref", "") or "").strip()
        and str(getattr(item, "spawn_mode", "") or "single_agent") == "single_agent"
    ]
    if runs:
        current = runs[-1]
        updated = replace(current, status="running", updated_at=time.time())
        runtime_host.state_index.upsert_agent_run(updated)
        return updated
    now = time.time()
    agent_run = AgentRun(
        agent_run_id=f"agrun:{task_run.task_run_id}:main",
        task_run_id=task_run.task_run_id,
        agent_id=str(getattr(task_run, "agent_id", "") or "agent:0"),
        agent_profile_id=task_run.agent_profile_id,
        status="running",
        execution_runtime_kind="single_agent_task",
        created_at=now,
        updated_at=now,
    )
    runtime_host.state_index.upsert_agent_run(agent_run)
    return agent_run


def _existing_observations(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for event in runtime_host.event_log.list_events(task_run_id):
        payload = dict(getattr(event, "payload", {}) or {})
        observation = payload.get("observation")
        if isinstance(observation, dict):
            observations.append(dict(observation))
    return observations


def _reusable_observations(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    context = _observations_for_packet(runtime_host, task_run_id, current_fingerprint={})
    return list(context["packet_observations"])


def _observations_for_packet(
    runtime_host: Any,
    task_run_id: str,
    *,
    current_fingerprint: dict[str, Any],
    pending_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_observations = [*_existing_observations(runtime_host, task_run_id), *list(pending_observations or [])]
    deduped = _dedupe_observations(raw_observations)
    records = [
        _tool_record_from_observation(observation, current_fingerprint=current_fingerprint)
        for observation in deduped
    ]
    projection = _build_execution_state_projection(records)
    pending_steers = list_pending_task_steers(runtime_host, task_run_id)
    for steer in pending_steers:
        ensure_revision_for_steer(runtime_host, task_run_id, steer)
    active_revisions = list_active_task_contract_revisions(runtime_host, task_run_id)
    if pending_steers:
        projection = {
            **projection,
            "pending_user_steers": [_steer_for_projection(item) for item in pending_steers],
            "pending_user_steer_count": len(pending_steers),
        }
    if active_revisions:
        projection = {
            **projection,
            "active_contract_revisions": [_contract_revision_for_projection(item) for item in active_revisions],
            "active_contract_revision_count": len(active_revisions),
        }
    return {
        "raw_observations": deduped,
        "tool_observation_records": records,
        "packet_observations": _packet_observations_from_records(records),
        "execution_state": {
            "system_projection": projection,
            "memory_summary": {},
            "context_summary": {},
            "authority": "harness.task_observation_projection",
        },
        "artifact_refs": _dedupe_artifacts(
            [
                dict(ref)
                for record in records
                if str(record.get("status") or "") == "ok" and _record_visibility(record) == "active"
                for ref in list(record.get("artifact_refs") or [])
                if isinstance(ref, dict)
            ]
        ),
    }


def _steer_for_projection(steer: dict[str, Any]) -> dict[str, Any]:
    return {
        "steer_id": str(steer.get("steer_id") or ""),
        "submission_ref": str(steer.get("submission_ref") or ""),
        "task_run_id": str(steer.get("task_run_id") or ""),
        "steer_kind": str(steer.get("steer_kind") or "instruction"),
        "priority": str(steer.get("priority") or "normal"),
        "consumption_state": str(steer.get("consumption_state") or "pending"),
        "content": compact_text(str(steer.get("content") or ""), limit=1200),
        "created_at": float(steer.get("created_at") or 0.0),
        "authority": "harness.loop.active_task_steer.model_projection",
    }


def _contract_revision_for_projection(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision_id": str(revision.get("revision_id") or ""),
        "task_run_id": str(revision.get("task_run_id") or ""),
        "submission_ref": str(revision.get("submission_ref") or ""),
        "steer_ref": str(revision.get("steer_ref") or ""),
        "revision_kind": str(revision.get("revision_kind") or "continuation_instruction"),
        "status": str(revision.get("status") or "pending_agent_triage"),
        "instruction": compact_text(str(revision.get("instruction") or ""), limit=1200),
        "proposed_goal": compact_text(str(revision.get("proposed_goal") or ""), limit=600),
        "proposed_acceptance_criteria": [
            compact_text(str(item), limit=300)
            for item in list(revision.get("proposed_acceptance_criteria") or [])
            if str(item)
        ],
        "impact": dict(revision.get("impact") or {}),
        "authority": "harness.loop.task_contract_revision.model_projection",
    }


def _consumed_steer_ids(action_request: ModelActionRequest, included_steer_ids: list[str]) -> list[str]:
    wanted = {str(item or "").strip() for item in included_steer_ids if str(item or "").strip()}
    diagnostics = dict(action_request.diagnostics or {})
    raw = diagnostics.get("consumed_steer_refs")
    if raw is None:
        raw = diagnostics.get("consumed_user_steer_refs")
    result: list[str] = []
    for item in list(raw or []):
        steer_id = str(item or "").strip()
        if steer_id in wanted and steer_id not in result:
            result.append(steer_id)
    return result


def _contract_revision_decisions(action_request: ModelActionRequest) -> list[dict[str, Any]]:
    diagnostics = dict(action_request.diagnostics or {})
    raw = diagnostics.get("contract_revision_decisions")
    if raw is None:
        raw = diagnostics.get("task_contract_revision_decisions")
    return [dict(item) for item in list(raw or []) if isinstance(item, dict)]


def _tool_record_from_observation(observation: dict[str, Any], *, current_fingerprint: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    tool_name = _observation_tool_name(observation)
    tool_args = _observation_tool_args(observation)
    result_payload = _observation_result_payload(observation)
    structured_error = _structured_error_from_observation(observation)
    previous_fingerprint = _observation_runtime_fingerprint(observation)
    freshness = _classify_record_freshness(
        observation=observation,
        status=_observation_status(observation),
        structured_error=structured_error,
        previous_fingerprint=previous_fingerprint,
        current_fingerprint=current_fingerprint,
    )
    record = build_tool_observation_record(
        observation_ref=str(observation.get("observation_id") or observation.get("observation_ref") or ""),
        tool_name=tool_name,
        tool_args=tool_args,
        result=result_payload,
        runtime_fingerprint=previous_fingerprint or current_fingerprint,
        structured_error=structured_error,
        freshness=freshness,
    ).to_dict()
    status = _observation_status(observation) or str(record.get("status") or "ok")
    if status in {"failed", "denied", "canceled", "error"}:
        record["status"] = "error"
    record["source_observation"] = _compact_observation_for_record(observation)
    if payload.get("operation_gate"):
        record["side_effect_kind"] = "gate"
    return record


def _classify_record_freshness(
    *,
    observation: dict[str, Any],
    status: str,
    structured_error: dict[str, Any],
    previous_fingerprint: dict[str, Any],
    current_fingerprint: dict[str, Any],
) -> dict[str, Any]:
    if str(observation.get("observation_type") or "") == "user_work_instruction":
        return {
            "visibility": "active",
            "reuse_as_fact": True,
            "reuse_as_repair_context": False,
            "reason": "user_work_instruction",
        }
    if _is_completion_repair_observation(observation):
        return {
            "visibility": "active",
            "reuse_as_fact": False,
            "reuse_as_repair_context": True,
            "reason": "completion_evidence_missing",
        }
    if status not in {"failed", "denied", "canceled", "error"}:
        if not previous_fingerprint and current_fingerprint:
            return {
                "visibility": "historical",
                "reuse_as_fact": False,
                "reuse_as_repair_context": False,
                "reason": "missing_runtime_fingerprint",
            }
        if previous_fingerprint and current_fingerprint and not _fingerprints_compatible(previous_fingerprint, current_fingerprint):
            return {
                "visibility": "historical",
                "reuse_as_fact": False,
                "reuse_as_repair_context": False,
                "reason": "superseded_by_runtime_change",
            }
        return {
            "visibility": "active",
            "reuse_as_fact": True,
            "reuse_as_repair_context": False,
            "reason": "current_success",
        }
    if not previous_fingerprint and current_fingerprint:
        return {
            "visibility": "historical",
            "reuse_as_fact": False,
            "reuse_as_repair_context": False,
            "reason": "missing_runtime_fingerprint",
        }
    if _fingerprints_compatible(previous_fingerprint, current_fingerprint):
        return {
            "visibility": "active",
            "reuse_as_fact": False,
            "reuse_as_repair_context": True,
            "reason": str(structured_error.get("code") or "current_failure"),
        }
    return {
        "visibility": "historical",
        "reuse_as_fact": False,
        "reuse_as_repair_context": False,
        "reason": "superseded_by_runtime_change",
    }


def _build_execution_state_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    current_facts: list[dict[str, Any]] = []
    artifact_evidence: list[dict[str, Any]] = []
    active_failures: list[dict[str, Any]] = []
    historical_failures: list[dict[str, Any]] = []
    repair_focus: list[dict[str, Any]] = []
    last_action_receipts: list[dict[str, Any]] = []
    for record in records:
        visibility = _record_visibility(record)
        status = str(record.get("status") or "ok")
        summary = _record_summary(record)
        receipt = {
            "observation_ref": str(record.get("observation_ref") or ""),
            "tool_name": str(record.get("tool_name") or ""),
            "status": status,
            "visibility": visibility,
            "summary": summary,
        }
        last_action_receipts.append(receipt)
        if status == "ok" and visibility == "active":
            current_facts.append(receipt)
            for ref in list(record.get("artifact_refs") or []):
                if isinstance(ref, dict):
                    artifact_evidence.append({**dict(ref), "observation_ref": receipt["observation_ref"]})
            continue
        failure = {
            **receipt,
            "error": dict(record.get("structured_error") or {}),
            "reason": str(dict(record.get("runtime_freshness") or {}).get("reason") or ""),
        }
        if visibility == "historical":
            historical_failures.append({**failure, "current_runtime_fact": False})
        else:
            active_failures.append(failure)
            if str(dict(record.get("structured_error") or {}).get("origin") or "") == "validator" or str(record.get("side_effect_kind") or "") == "repair":
                repair_focus.append(failure)
    return {
        "current_facts": current_facts[-12:],
        "artifact_evidence": _dedupe_artifacts(artifact_evidence)[-20:],
        "active_failures": active_failures[-8:],
        "historical_failures": historical_failures[-8:],
        "repair_focus": repair_focus[-8:],
        "open_questions": [],
        "last_action_receipts": last_action_receipts[-12:],
        "authority": "harness.task_observation_projection",
    }


def _packet_observations_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    packet: list[dict[str, Any]] = []
    for record in records:
        visibility = _record_visibility(record)
        status = str(record.get("status") or "ok")
        if visibility == "active" or status == "ok" or _is_record_completion_repair(record):
            packet.append(record)
        elif visibility == "historical":
            packet.append(
                {
                    "observation_ref": str(record.get("observation_ref") or ""),
                    "tool_name": str(record.get("tool_name") or ""),
                    "status": status,
                    "runtime_freshness": dict(record.get("runtime_freshness") or {}),
                    "structured_error": dict(record.get("structured_error") or {}),
                    "result_preview": _record_summary(record),
                    "authority": "orchestration.tool_observation_record.historical_summary",
                }
            )
    return packet[-24:]


def _current_runtime_fingerprint(runtime_assembly: dict[str, Any], *, runtime_host: Any, backend_config: dict[str, Any]) -> dict[str, Any]:
    profile = dict(runtime_assembly.get("profile") or {})
    environment = dict(runtime_assembly.get("task_environment") or {})
    config = _safe_backend_config(backend_config)
    return {
        "runtime_assembly_id": str(runtime_assembly.get("assembly_id") or ""),
        "agent_profile_id": str(runtime_assembly.get("agent_profile_ref") or ""),
        "runtime_mode": str(profile.get("mode") or ""),
        "task_environment_id": str(environment.get("environment_id") or ""),
        "tool_registry_hash": _stable_hash(_runtime_available_tools(runtime_assembly)),
        "tool_config_hash": _stable_hash(_tool_config_fingerprint(config)),
        "sandbox_policy_hash": _stable_hash(environment.get("sandbox_policy") or {}),
        "permission_policy_hash": _stable_hash(profile.get("permission_policy") or {}),
        "backend_config_hash": _stable_hash(config),
        "permission_mode": str(runtime_host._current_permission_mode()) if hasattr(runtime_host, "_current_permission_mode") else "",
    }


def _dedupe_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in observations:
        if not isinstance(item, dict):
            continue
        if str(item.get("authority") or "") == "orchestration.tool_observation_record":
            continue
        key = str(item.get("observation_id") or item.get("observation_ref") or item.get("request_ref") or json.dumps(item, ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _observation_tool_name(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    source = str(observation.get("source") or "")
    if source.startswith("tool:"):
        source_name = source.split(":", 1)[1].strip()
    else:
        source_name = ""
    return str(
        payload.get("tool_name")
        or envelope.get("tool_name")
        or dict(payload.get("tool_call") or {}).get("name")
        or source_name
        or "system"
    ).strip()


def _observation_tool_args(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    return dict(
        payload.get("tool_args")
        or envelope.get("tool_args")
        or dict(payload.get("tool_call") or {}).get("args")
        or {}
    )


def _observation_result_payload(observation: dict[str, Any]) -> Any:
    payload = dict(observation.get("payload") or {})
    if payload.get("result_envelope"):
        return {"result_envelope": dict(payload.get("result_envelope") or {})}
    if payload.get("structured_payload"):
        return {
            "result_envelope": {
                "tool_name": _observation_tool_name(observation),
                "tool_args": _observation_tool_args(observation),
                "status": "error" if _observation_status(observation) in {"failed", "denied", "canceled", "error"} else "ok",
                "text": str(payload.get("result") or payload.get("error") or ""),
                "structured_payload": dict(payload.get("structured_payload") or {}),
                "artifact_refs": list(payload.get("artifact_refs") or []),
                "error": str(payload.get("error") or observation.get("error") or ""),
            }
        }
    if payload.get("result") is not None:
        return str(payload.get("result") or "")
    if payload.get("error") or observation.get("error"):
        return {
            "result_envelope": {
                "tool_name": _observation_tool_name(observation),
                "tool_args": _observation_tool_args(observation),
                "status": "error",
                "text": str(payload.get("error") or observation.get("error") or ""),
                "structured_payload": {},
                "error": str(payload.get("error") or observation.get("error") or ""),
            }
        }
    return payload


def _observation_status(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    tool_result = dict(structured.get("tool_result") or {}) if isinstance(structured.get("tool_result"), dict) else {}
    operation_gate = dict(payload.get("operation_gate") or {})
    if operation_gate and operation_gate.get("allowed") is False:
        return "denied"
    if str(observation.get("observation_type") or "") == "executor_error":
        return "failed"
    if observation.get("error") or payload.get("error"):
        return "failed"
    if str(envelope.get("status") or "").strip() in {"error", "failed", "denied", "canceled"}:
        return "failed"
    if str(tool_result.get("status") or "").strip() in {"error", "failed", "denied", "canceled"}:
        return "failed"
    parsed = _json_payload(payload.get("result"))
    if parsed.get("ok") is False:
        return "failed"
    if parsed.get("ok") is True:
        return "ok"
    return "ok"


def _structured_error_from_observation(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    tool_result = dict(structured.get("tool_result") or {}) if isinstance(structured.get("tool_result"), dict) else {}
    operation_gate = dict(payload.get("operation_gate") or {})
    if operation_gate and operation_gate.get("allowed") is False:
        return {
            "code": str(operation_gate.get("reason") or payload.get("error") or "operation_gate_denied"),
            "message": str(operation_gate.get("reason") or payload.get("error") or "operation gate denied"),
            "retryable": False,
            "origin": "operation_gate",
        }
    for source in (tool_result, structured, envelope, payload):
        error = source.get("error") if isinstance(source, dict) else None
        if isinstance(error, dict):
            return {
                "code": str(error.get("code") or error.get("error_code") or source.get("code") or "tool_error"),
                "message": str(error.get("message") or error.get("detail") or error),
                "retryable": bool(error.get("retryable", source.get("retryable", True))),
                "origin": str(error.get("origin") or source.get("origin") or "tool_provider"),
            }
    parsed_result = _json_payload(payload.get("result"))
    parsed_error = parsed_result.get("structured_error")
    if isinstance(parsed_error, dict) and parsed_error:
        return {
            "code": str(parsed_error.get("code") or parsed_result.get("error_code") or parsed_result.get("code") or "tool_error"),
            "message": str(parsed_error.get("message") or parsed_result.get("error") or parsed_error),
            "retryable": bool(parsed_error.get("retryable", parsed_result.get("retryable", True))),
            "origin": str(parsed_error.get("origin") or _error_origin(observation)),
        }
    if parsed_result.get("ok") is False and parsed_result.get("error"):
        return {
            "code": str(parsed_result.get("error_code") or parsed_result.get("code") or "tool_error"),
            "message": str(parsed_result.get("error") or ""),
            "retryable": bool(parsed_result.get("retryable", True)),
            "origin": _error_origin(observation),
        }
    message = str(payload.get("error") or envelope.get("error") or observation.get("error") or tool_result.get("error") or "")
    if message:
        structured_error = payload.get("structured_error")
        if isinstance(structured_error, dict) and structured_error:
            return {
                "code": str(structured_error.get("code") or payload.get("error_code") or payload.get("code") or "tool_error"),
                "message": str(structured_error.get("message") or message),
                "retryable": bool(structured_error.get("retryable", payload.get("retryable", True))),
                "origin": str(structured_error.get("origin") or _error_origin(observation)),
            }
        return {
            "code": str(payload.get("error_code") or payload.get("code") or "tool_error"),
            "message": message,
            "retryable": bool(payload.get("retryable", True)),
            "origin": _error_origin(observation),
        }
    if _is_completion_repair_observation(observation):
        return {
            "code": "completion_evidence_missing",
            "message": "completion evidence missing",
            "retryable": True,
            "origin": "validator",
        }
    return {}


def _error_origin(observation: dict[str, Any]) -> str:
    source = str(observation.get("source") or "")
    if source == "system:model_runtime":
        return "model_runtime"
    if source == "system:model_action_protocol":
        return "model_protocol"
    if source == "system:task_completion_validator":
        return "validator"
    if source.startswith("tool:"):
        return "tool_provider"
    return "runtime"


def _observation_runtime_fingerprint(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    for source in (
        payload.get("runtime_fingerprint"),
        dict(payload.get("runtime_freshness") or {}).get("fingerprint") if isinstance(payload.get("runtime_freshness"), dict) else {},
        dict(observation.get("runtime_freshness") or {}).get("fingerprint") if isinstance(observation.get("runtime_freshness"), dict) else {},
    ):
        if isinstance(source, dict) and source:
            return dict(source)
    packet_ref = str(observation.get("directive_ref") or "")
    assembly_id = ""
    if ":task_execution:" in packet_ref:
        assembly_id = packet_ref.split(":task_execution:", 1)[0].replace("rtpacket:", "rtasm:")
    return {"runtime_assembly_id": assembly_id} if assembly_id else {}


def _fingerprints_compatible(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if not previous or not current:
        return True
    keys = ("tool_registry_hash", "tool_config_hash", "sandbox_policy_hash", "permission_policy_hash", "backend_config_hash")
    compared = [key for key in keys if previous.get(key) and current.get(key)]
    if not compared:
        return str(previous.get("runtime_assembly_id") or "") == str(current.get("runtime_assembly_id") or "") or not previous.get("runtime_assembly_id")
    return all(str(previous.get(key)) == str(current.get(key)) for key in compared)


def _is_completion_repair_observation(observation: dict[str, Any]) -> bool:
    payload = dict(observation.get("payload") or {})
    return str(payload.get("error_code") or "") == "completion_evidence_missing" or str(observation.get("source") or "") == "system:task_completion_validator"


def _is_record_completion_repair(record: dict[str, Any]) -> bool:
    error = dict(record.get("structured_error") or {})
    return str(error.get("origin") or "") == "validator" or str(error.get("code") or "") == "completion_evidence_missing"


def _record_visibility(record: dict[str, Any]) -> str:
    return str(dict(record.get("runtime_freshness") or {}).get("visibility") or "active")


def _record_summary(record: dict[str, Any]) -> str:
    error = dict(record.get("structured_error") or {})
    if error.get("message"):
        return compact_text(str(error.get("message") or ""), limit=400)
    return compact_text(str(record.get("result_preview") or ""), limit=400)


def _observation_brief(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    if observation.get("error") or payload.get("error"):
        return compact_text(str(payload.get("error") or observation.get("error") or ""), limit=300)
    envelope = dict(payload.get("result_envelope") or {})
    if envelope.get("text"):
        return compact_text(str(envelope.get("text") or ""), limit=300)
    if payload.get("result") is not None:
        return compact_text(str(payload.get("result") or ""), limit=300)
    return ""


def _compact_observation_for_record(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": str(observation.get("observation_id") or ""),
        "observation_type": str(observation.get("observation_type") or ""),
        "source": str(observation.get("source") or ""),
        "request_ref": str(observation.get("request_ref") or ""),
        "created_at": observation.get("created_at"),
    }


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_backend_config(backend_config: dict[str, Any]) -> dict[str, Any]:
    config = dict(backend_config or {})
    image = dict(config.get("image_generation") or config.get("images") or config.get("soul_image_assets") or {})
    return {
        "image_generation": {
            "base_url": str(image.get("base_url") or image.get("api_base") or ""),
            "model": str(image.get("model") or ""),
            "api_key_present": bool(image.get("api_key_present") or image.get("api_key") or image.get("key")),
        }
    }


def _tool_config_fingerprint(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get("image_generation") or config.get("images") or config.get("soul_image_assets") or {})


def _strip_terminal_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    for key in (
        "observation",
        "latest_step",
        "latest_step_status",
        "latest_step_summary",
        "terminal_reason",
        "action_request",
        "admission",
        "diagnostics",
        "recoverable_error",
        "recovery_action",
        "user_question",
    ):
        payload.pop(key, None)
    return payload


def _strip_runtime_lease_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    for key in ("executor_status", "active_packet_ref"):
        payload.pop(key, None)
    control = payload.get(_TASK_RUN_CONTROL_KEY)
    if isinstance(control, dict) and str(control.get("state") or "") in {_TASK_RUN_RESUME_REQUESTED, _TASK_RUN_INTERRUPTED_FOR_REPLAN, "running"}:
        payload.pop(_TASK_RUN_CONTROL_KEY, None)
    return payload


def _runtime_control_payload(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = diagnostics.get(_TASK_RUN_CONTROL_KEY)
    if not isinstance(control, dict):
        return {}
    return {
        "state": task_run_control_state(task_run),
        "requested_by": str(control.get("requested_by") or ""),
        "requested_at": float(control.get("requested_at") or 0.0),
        "reason": str(control.get("reason") or ""),
        "authority": "orchestration.task_run_control",
    }


def _diagnostics_for_executor_start(diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_terminal_diagnostics(dict(diagnostics or {}))
    control = payload.get(_TASK_RUN_CONTROL_KEY)
    if isinstance(control, dict) and str(control.get("state") or "") in {_TASK_RUN_RESUME_REQUESTED, _TASK_RUN_INTERRUPTED_FOR_REPLAN}:
        payload[_TASK_RUN_CONTROL_KEY] = {
            **dict(control),
            "state": "running",
            "authority": "orchestration.task_run_control",
        }
    return payload


def _diagnostics_with_runtime_control(
    diagnostics: dict[str, Any],
    *,
    state: str,
    requested_by: str,
    requested_at: float,
    reason: str,
    latest_step: str,
    latest_step_status: str,
    latest_step_summary: str,
) -> dict[str, Any]:
    return {
        **dict(diagnostics or {}),
        _TASK_RUN_CONTROL_KEY: {
            "state": state,
            "requested_by": requested_by or "user",
            "requested_at": float(requested_at or time.time()),
            "reason": reason,
            "authority": "orchestration.task_run_control",
        },
        "latest_step": latest_step,
        "latest_step_status": latest_step_status,
        "latest_step_summary": latest_step_summary,
    }


def _completion_repair_observation(*, task_run_id: str, packet_ref: str, action_request: ModelActionRequest, verdict: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:task_completion_validator",
        "request_ref": action_request.request_id,
        "directive_ref": packet_ref,
        "content_chars": 0,
        "payload": {"error_code": "completion_evidence_missing", "verdict": verdict, "rejected_action_request": action_request.to_dict()},
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "completion_evidence_missing",
    }


def _active_steer_completion_repair_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    action_request: ModelActionRequest,
    pending_steer_ids: list[str],
    active_revisions: list[dict[str, Any]],
) -> dict[str, Any]:
    active_revision_ids = [str(item.get("revision_id") or "") for item in active_revisions if str(item.get("revision_id") or "")]
    return {
        "observation_id": f"rtobs:{task_run_id}:pending-steer:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:task_completion_validator",
        "request_ref": action_request.request_id,
        "directive_ref": packet_ref,
        "content_chars": 0,
        "payload": {
            "error_code": "pending_user_steer_unconsumed",
            "pending_steer_ids": list(pending_steer_ids),
            "active_contract_revision_ids": active_revision_ids,
            "repair_instruction": (
                "处理 pending_user_steers 前不能直接完成。你需要真正纳入用户补充要求，并在 diagnostics.consumed_steer_refs "
                "列出已处理的 steer_id；如果补充要求改变目标、验收或范围，还需要在 diagnostics.contract_revision_decisions "
                "中裁决对应 revision_id。"
            ),
            "rejected_action_request": action_request.to_dict(),
        },
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "pending_user_steer_unconsumed",
    }


def _model_protocol_repair_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    step_index: int,
    diagnostics: dict[str, Any],
    runtime_fingerprint: dict[str, Any],
) -> dict[str, Any]:
    errors = [str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or [])]
    message = "model action request failed protocol validation"
    if errors:
        message = f"{message}: {', '.join(errors)}"
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:model_action_protocol",
        "request_ref": f"model-action-protocol:{task_run_id}:invocation:{step_index}:{uuid.uuid4().hex[:8]}",
        "directive_ref": packet_ref,
        "content_chars": len(message),
        "payload": {
            "tool_name": "model_action_protocol",
            "tool_args": {},
            "error": message,
            "error_code": "model_action_invalid",
            "validation_errors": errors,
            "structured_error": {
                "code": "model_action_invalid",
                "message": message,
                "retryable": True,
                "origin": "model_protocol",
            },
            "runtime_fingerprint": dict(runtime_fingerprint or {}),
        },
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "model_action_invalid",
    }


def _model_protocol_repair_count(observations: list[dict[str, Any]]) -> int:
    return sum(1 for item in observations if str(item.get("source") or "") == "system:model_action_protocol")


def _executor_error_observation(*, task_run_id: str, request_ref: str, directive_ref: str, tool_name: str, tool_args: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": f"tool:{tool_name}",
        "request_ref": request_ref,
        "directive_ref": directive_ref,
        "content_chars": len(error),
        "payload": {"tool_name": tool_name, "tool_args": tool_args, "error": error},
        "needs_model_followup": False,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": error,
    }


def _artifact_refs_from_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for observation in observations:
        refs.extend(_artifact_refs_from_observation(observation))
    return _dedupe_artifacts(refs)


def _artifact_refs_from_observation(observation: dict[str, Any]) -> list[dict[str, Any]]:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    refs = [
        dict(item)
        for item in list(payload.get("artifact_refs") or envelope.get("artifact_refs") or structured.get("artifact_refs") or [])
        if isinstance(item, dict)
    ]
    if refs:
        return refs
    image = dict(_json_payload(payload.get("result")).get("image") or {})
    path = str(image.get("file_path") or image.get("src") or "").strip()
    if path:
        return [{"path": path, "kind": "image", "source": "image_generate"}]
    return []


def _artifacts_from_action(action_request: ModelActionRequest) -> list[dict[str, Any]]:
    diagnostics = dict(action_request.diagnostics or {})
    return [dict(item) for item in list(diagnostics.get("artifacts") or []) if isinstance(item, dict)]


def _dedupe_artifacts(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = str(ref.get("path") or ref.get("src") or json.dumps(ref, ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(ref))
    return result


def _verified_artifacts(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    artifact_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project_root = ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve()
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run_id)
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or "")).resolve()
    artifact_root = str(sandbox_policy.get("artifact_root") or "").replace("\\", "/").strip().strip("/")
    publish_roots = tuple(_sandbox_publish_scopes(sandbox_policy))
    verified: list[dict[str, Any]] = []
    for ref in _dedupe_artifacts(artifact_refs):
        resolved = _publish_or_resolve_artifact_ref(
            ref,
            project_root=project_root,
            sandbox_root=sandbox_root,
            artifact_root=artifact_root,
            publish_roots=publish_roots,
        )
        if resolved is None or not resolved.exists() or not resolved.is_file():
            continue
        try:
            logical_path = resolved.relative_to(project_root).as_posix()
        except ValueError:
            logical_path = str(resolved)
        verified.append(
            {
                **dict(ref),
                "path": logical_path,
                "absolute_path": str(resolved),
                "exists": True,
                "size_bytes": resolved.stat().st_size,
                "published": True,
            }
        )
    return _dedupe_artifacts(verified)


def _discover_sandbox_artifact_refs(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run_id)
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or "")).resolve()
    if not sandbox_root.exists() or not sandbox_root.is_dir():
        return []
    roots = _publish_scan_roots(sandbox_policy)
    refs: list[dict[str, Any]] = []
    for root in roots:
        scan_root = (sandbox_root / root).resolve()
        if not _is_inside(scan_root, sandbox_root) or not scan_root.exists():
            continue
        candidates = [scan_root] if scan_root.is_file() else [path for path in scan_root.rglob("*") if path.is_file()]
        for path in candidates:
            try:
                logical_path = path.resolve().relative_to(sandbox_root).as_posix()
            except ValueError:
                continue
            if not _discovered_artifact_matches_contract(logical_path, contract):
                continue
            refs.append(
                {
                    "path": logical_path,
                    "kind": _artifact_kind_for_path(path),
                    "source": "sandbox_closeout_discovery",
                    "absolute_path": str(path.resolve()),
                    "sandbox_path": logical_path,
                }
            )
    return _dedupe_artifacts(refs)


def _discovered_artifact_matches_contract(logical_path: str, contract: dict[str, Any]) -> bool:
    normalized = _normalize_contract_path(logical_path)
    if not normalized:
        return False
    if _is_graph_node_contract(contract):
        return True
    explicit_paths = {_normalize_contract_path(item) for item in _explicit_contract_paths(contract)}
    return normalized in explicit_paths


def _is_graph_node_contract(contract: dict[str, Any]) -> bool:
    if str(dict(contract or {}).get("contract_source") or "") == "graph_node_work_order":
        return True
    origin = dict(dict(contract or {}).get("origin") or {})
    return str(origin.get("origin_kind") or "") == "graph_node_assigned"


def _publish_scan_roots(sandbox_policy: dict[str, Any]) -> tuple[str, ...]:
    roots = [
        str(sandbox_policy.get("artifact_root") or ""),
        *[str(item or "") for item in _sandbox_publish_scopes(sandbox_policy)],
    ]
    return tuple(_dedupe_strings([_normalize_contract_path(root) for root in roots]))


def _sandbox_publish_scopes(sandbox_policy: dict[str, Any]) -> list[str]:
    explicit = _dedupe_strings([str(item or "") for item in list(sandbox_policy.get("publish_scopes") or [])])
    if explicit:
        return explicit
    return _dedupe_strings([str(sandbox_policy.get("artifact_root") or "")])


def _artifact_kind_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".html", ".htm"}:
        return "html_document"
    if suffix in {".md", ".markdown"}:
        return "markdown_document"
    return "file"


def _publish_or_resolve_artifact_ref(
    ref: dict[str, Any],
    *,
    project_root: Path,
    sandbox_root: Path,
    artifact_root: str,
    publish_roots: tuple[str, ...] = (),
) -> Path | None:
    logical_path = str(ref.get("path") or ref.get("published_path") or ref.get("src") or "").replace("\\", "/").strip().strip("/")
    sandbox_source = _sandbox_artifact_source(ref, sandbox_root=sandbox_root)
    if sandbox_source is not None and sandbox_source.exists() and sandbox_source.is_file():
        if not logical_path or not _logical_path_publish_allowed(logical_path, artifact_root, publish_roots):
            return None
        publish_target = (project_root / logical_path).resolve()
        if not _is_inside(publish_target, project_root):
            return None
        publish_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sandbox_source, publish_target)
        return publish_target
    if logical_path:
        project_candidate = (project_root / logical_path).resolve()
        if _is_inside(project_candidate, project_root) and project_candidate.exists() and project_candidate.is_file():
            return project_candidate
    return None


def _sandbox_artifact_source(ref: dict[str, Any], *, sandbox_root: Path) -> Path | None:
    for key in ("absolute_path", "sandbox_path"):
        raw = str(ref.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (sandbox_root / raw).resolve()
        if _is_inside(resolved, sandbox_root):
            return resolved
    return None


def _logical_path_within_artifact_root(logical_path: str, artifact_root: str) -> bool:
    if not artifact_root:
        return False
    return logical_path == artifact_root or logical_path.startswith(f"{artifact_root}/")


def _logical_path_publish_allowed(logical_path: str, artifact_root: str, publish_roots: tuple[str, ...]) -> bool:
    normalized = str(logical_path or "").replace("\\", "/").strip().strip("/")
    if not normalized:
        return False
    if _logical_path_within_artifact_root(normalized, artifact_root):
        return True
    for root in publish_roots:
        clean_root = str(root or "").replace("\\", "/").strip().strip("/")
        if clean_root and (normalized == clean_root or normalized.startswith(f"{clean_root}/")):
            return True
    return False


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _json_payload(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _runtime_available_tools(runtime_assembly_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(runtime_assembly_payload.get("available_tools") or [])
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    ]


def _runtime_allowed_tool_names(available_tools: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("tool_name") or "").strip() for item in available_tools if str(item.get("tool_name") or "").strip()}


def _record_task_step_summary(
    runtime_host: Any,
    *,
    task_run_id: str,
    step: str,
    status: str,
    summary: str,
    refs: dict[str, Any] | None = None,
    public_progress_note: str = "",
    agent_brief_output: str = "",
    presentation_source: str = "",
) -> dict[str, Any]:
    visible_summary = public_runtime_progress_summary(summary)
    visible_note = public_runtime_progress_summary(public_progress_note)
    visible_brief = public_runtime_progress_summary(agent_brief_output)
    payload = {"task_run_id": task_run_id, "step": step, "status": status, "summary": visible_summary}
    if visible_note:
        payload["public_progress_note"] = visible_note
    if visible_brief:
        payload["agent_brief_output"] = visible_brief
    if presentation_source:
        payload["presentation_source"] = presentation_source
    event = runtime_host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload=payload,
        refs={"task_run_ref": task_run_id, **dict(refs or {})},
    )
    current = runtime_host.state_index.get_task_run(task_run_id)
    if current is not None:
        runtime_host.state_index.upsert_task_run(
            replace(
                current,
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                diagnostics={
                    **dict(current.diagnostics or {}),
                    "latest_step": step,
                    "latest_step_status": status,
                    "latest_step_summary": visible_summary,
                    **({"latest_public_progress_note": visible_note or visible_summary} if (visible_note or visible_summary) else {}),
                    **({"agent_brief_output": visible_brief} if visible_brief else {}),
                },
            )
        )
    return event.to_dict()


def _record_task_model_wait_heartbeat(
    runtime_host: Any,
    *,
    task_run_id: str,
    step: str,
    wait_round: int,
    refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = runtime_host.event_log.append(
        task_run_id,
        "task_model_action_wait_heartbeat",
        payload={
            "task_run_id": task_run_id,
            "step": step,
            "status": "running",
            "wait_round": int(wait_round),
        },
        refs={"task_run_ref": task_run_id, **dict(refs or {})},
    )
    current = runtime_host.state_index.get_task_run(task_run_id)
    if current is not None:
        runtime_host.state_index.upsert_task_run(
            replace(
                current,
                updated_at=event.created_at,
                latest_event_offset=event.offset,
            )
        )
    return event.to_dict()


def _action_progress_note(action_request: ModelActionRequest) -> str:
    return public_runtime_progress_summary(action_request.public_progress_note) or public_action_progress_summary(action_request.action_type)


def _tool_call_progress_summary(action_request: ModelActionRequest) -> str:
    tool_call = dict(action_request.tool_call or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    target = _tool_target_preview(args)
    display = _public_tool_display_name(tool_name)
    if target:
        return f"正在使用{display}处理 {target}。"
    return f"正在使用{display}处理当前步骤。"


def _public_tool_display_name(tool_name: str) -> str:
    normalized = str(tool_name or "").strip()
    lowered = normalized.lower()
    mapping = {
        "image_generate": "生图工具",
        "image_generation": "生图工具",
        "generate_image": "生图工具",
        "spawn_subagent": "子 Agent 启动工具",
        "send_subagent_message": "子 Agent 消息工具",
        "wait_subagent": "子 Agent 等待工具",
        "list_subagents": "子 Agent 列表工具",
        "close_subagent": "子 Agent 关闭工具",
        "write_file": "文件写入工具",
        "edit_file": "文件编辑工具",
        "read_file": "文件读取工具",
        "terminal": "命令工具",
        "shell": "命令工具",
    }
    if lowered in mapping:
        return mapping[lowered]
    return normalized.replace("_", " ") or "工具"


def _subagent_control_observation(
    *,
    task_run_id: str,
    request_ref: str,
    directive_ref: str,
    tool_name: str,
    tool_args: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    ok = bool(dict(payload or {}).get("ok") is True)
    return {
        "observation_id": f"rtobs:{task_run_id}:subagent:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "tool_result" if ok else "executor_error",
        "source": f"tool:{tool_name}",
        "request_ref": request_ref,
        "directive_ref": directive_ref,
        "content_chars": len(json.dumps(payload, ensure_ascii=False)),
        "payload": {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "result": payload,
            **({"error": str(dict(payload).get("error") or "subagent_control_failed")} if not ok else {}),
        },
        "needs_model_followup": not ok,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        **({"error": str(dict(payload).get("error") or "subagent_control_failed")} if not ok else {}),
    }


def _tool_target_preview(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "target_path", "prompt", "query", "command"):
        value = str(args.get(key) or "").strip()
        if value:
            return " ".join(value.split())[:120].rstrip()
    return ""


def _public_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(policy or {}).items()
        if key in {"enabled", "sandbox_root", "workspace_root", "artifact_root", "write_scopes", "approval_policy", "side_effect_operations"}
    }


def _not_found(task_run_id: str) -> dict[str, Any]:
    return {"ok": False, "task_run_id": task_run_id, "error": "task_run_not_found"}


def _conflict(task_run_id: str, error: str) -> dict[str, Any]:
    return {"ok": False, "task_run_id": task_run_id, "error": error}
