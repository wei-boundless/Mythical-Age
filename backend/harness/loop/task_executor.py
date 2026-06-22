from __future__ import annotations

import json
import asyncio
import hashlib
import inspect
import time
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from artifact_system.artifact_authority import (
    artifact_ref_value,
    artifact_refs_from_event_payload,
    dedupe_artifact_refs,
    normalize_artifact_ref,
)
from file_management import RepositoryRootResolver, normalize_logical_path, resolve_file_environment
from runtime.shared.models import AgentRun, AgentRunResult
from runtime.memory.file_evidence_scope import task_run_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore
from runtime.memory.tool_observation_ledger import build_tool_observation_record
from runtime.output_stream.public_contract import ASSISTANT_PUBLIC_FEEDBACK_EVENT
from runtime.model_gateway.assistant_stream_frame import (
    allows_assistant_body_projection,
    assistant_message_ref,
    assistant_text_final_event,
)
from runtime.cache_manager import DEFAULT_SANDBOX_CACHE_TTL_SECONDS, runtime_cache_manager_for_host
from runtime.shared.approval_fingerprint import build_approval_risk_fingerprint
from runtime.shared.file_observation_policy import read_window_fingerprint_defaults
from runtime.tool_runtime import ToolInvocationRequest
from runtime.shared.tool_identity import (
    canonical_action_tool_call_id,
    permission_decision_id,
)

from permissions.policy import normalize_permission_mode
from prompt_library import TASK_ACTION_JSON_REPAIR_PROMPT
from project_layout import ProjectLayout
from harness.task_run_status import is_stopped_or_terminal_task_run, runtime_control_state_from_task_run
from harness.runtime.assembly import assemble_runtime
from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.output_commit_authority import OutputCommitAuthority, OutputCommitRequest
from harness.runtime.control_events import RuntimeSignalScope
from harness.runtime.packet_context import (
    runtime_packet_evidence_projection_event_payload,
    runtime_packet_evidence_projection_ref,
    runtime_packet_evidence_signal_scope,
)
from harness.runtime.dynamic_context.semantic_payload_classifier import (
    merge_pending_subagent_result_actions,
    pending_subagent_result_actions_from_observation,
)
from harness.runtime.services import TaskExecutorServices
from harness.runtime.tool_batch_planner import ToolBatchGroup, build_tool_batch_plan
from harness.runtime.tool_plan import build_runtime_tool_plan
from harness.runtime.environment_storage import ensure_environment_storage_dirs
from harness.runtime.artifact_scope import (
    canonicalize_task_contract_artifacts,
    runtime_artifact_scope_from_environment,
)
from harness.runtime.sandbox_execution_scope import compile_sandbox_execution_scope, task_safety_envelope_from_assembly
from harness.runtime.file_management_policy import compile_tool_file_management_policy
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.sandbox_artifacts import (
    discover_sandbox_artifact_refs,
    publish_sandbox_artifact_refs,
)

from .execution_kernel import (
    append_action_lifecycle_event,
    action_admission_denial_fingerprint,
    build_action_admission_recovery_payload,
    build_action_lifecycle_event_record,
    build_action_lifecycle_from_admission,
    build_action_tool_invocation_identity,
    build_tool_lifecycle_started_event_record,
    decide_model_action_lifecycle,
)
from .active_turn_steering import ActiveTurnQueuedUserSteers, claim_active_turn_queued_user_steers
from .executor_sequence import claim_executor_sequence, next_model_action_request_id
from .model_action_runtime import (
    call_model_invoker,
    call_model_streamer,
    compact_text,
    model_action_timeout_seconds,
    normalize_model_selection_for_invocation,
)
from .model_action_protocol import AnyModelActionRequest, TaskExecutionModelActionRequest, task_execution_action_request_from_payload
from .specialist_runtime_router import SpecialistRuntimeExecution, SpecialistRuntimeRouter
from .task_run_execution_control import (
    ExecutorControlSignal,
    attach_model_task,
    clear_executor_epoch,
    clear_model_task,
    clear_executor_signal,
    executor_epoch_is_live,
    peek_executor_signal,
    register_executor_epoch,
    request_executor_control_signal,
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
from .turn_to_task_context_handoff import (
    handoff_summary,
    inherited_observations_for_packet,
    inherited_start_context_for_model,
    load_turn_to_task_context_handoff,
)
from .task_tool_approval import (
    APPROVAL_GRANT_KIND,
    append_task_tool_approval_grant,
    approval_state_for_task_run,
    build_task_tool_approval_grant,
    matching_approval_grant_for_pending,
    pending_approval_from_task_run,
    publish_task_tool_approval_granted,
    publish_task_tool_approval_requested,
    tool_args_hash,
)
from .task_run_recovery_state import recovery_state_for_task_run, should_auto_continue_task_run
from .work_rollout import append_work_rollout_item, ensure_work_rollout, work_rollout_summary


_MAX_TASK_EXECUTION_STEPS = 12
_MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS = 3
_PROTOCOL_REPAIR_PRESENTATION_SOURCE = "runtime.protocol_repair"
_REPEATED_ADMISSION_GUARD_COUNT = 2
_REPEATED_ADMISSION_PAUSE_COUNT = 3
_REPEATED_TOOL_FAILURE_OBSERVATION_COUNT = 3
_REPEATED_TOOL_FAILURE_BLOCK_COUNT = 4
_DEFAULT_TASK_TOOL_BATCH_TIMEOUT_SECONDS = 45.0
_TASK_TOOL_BATCH_CANCEL_DRAIN_SECONDS = 1.0
_TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS = 15.0
_TASK_MODEL_THINKING_FEEDBACK_FIRST_DELAY_SECONDS = 0.8
_TASK_MODEL_THINKING_FEEDBACK_INTERVAL_SECONDS = 1.5
_TASK_MODEL_WAIT_PRESENTATION_SOURCE = "runtime.model_wait"
_TASK_MODEL_THINKING_PRESENTATION_SOURCE = "runtime.no_public_event"
_TASK_RUN_CONTROL_KEY = "runtime_control"
_TASK_RUN_PAUSE_REQUESTED = "pause_requested"
_TASK_RUN_PAUSED = "paused"
_TASK_RUN_RESUME_REQUESTED = "resume_requested"
_TASK_RUN_STOP_REQUESTED = "stop_requested"
_TASK_RUN_STOPPED = "stopped"
_TASK_RUN_REPLAN_REQUESTED = "replan_requested"
_TASK_RUN_INTERRUPTED_FOR_REPLAN = "interrupted_for_replan"


class TaskRunExecutorInterrupted(Exception):
    def __init__(self, signal: ExecutorControlSignal) -> None:
        super().__init__(f"task_run_executor_interrupted:{signal.kind}")
        self.signal = signal


class TaskModelActionStreamProtocolError(RuntimeError):
    def __init__(
        self,
        *,
        stream_error: Exception,
        model_selection: dict[str, Any],
    ) -> None:
        detail = f"task model action stream failed; non-stream fallback is disabled for JSON action protocol: {stream_error}"
        super().__init__(detail)
        self.code = "non_stream_fallback_disabled_for_task_action_protocol"
        self.provider = str(dict(model_selection or {}).get("provider") or "")
        self.model = str(dict(model_selection or {}).get("model") or "")
        self.detail = detail
        self.retryable = bool(getattr(stream_error, "retryable", True))
        self.user_message = "任务模型动作流式调用失败。为避免重采样控制动作，已保留任务在可恢复状态。"


class TaskToolChildActionProtocolError(RuntimeError):
    def __init__(self, code: str) -> None:
        normalized = str(code or "task_tool_child_action_invalid").strip()
        super().__init__(normalized)
        self.code = normalized


def is_task_run_executable(task_run: Any, *, runtime_host: Any | None = None) -> bool:
    return recovery_state_for_task_run(task_run, runtime_host=runtime_host).executable


def is_task_run_executor_claimed(task_run: Any, *, runtime_host: Any | None = None) -> bool:
    return _active_task_run_executor_cell(runtime_host, task_run) is not None


def _active_task_run_executor_cell(runtime_host: Any | None, task_run: Any) -> Any | None:
    supervisor = getattr(runtime_host, "agent_run_supervisor", None) if runtime_host is not None else None
    getter = getattr(supervisor, "active_cell_for_task_run", None)
    if not callable(getter):
        return None
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    if not task_run_id:
        return None
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    try:
        return getter(task_run_id, session_id=session_id)
    except Exception:
        return None


def _visible_task_run_control_state(task_run: Any, control: dict[str, Any], *, runtime_host: Any | None = None) -> str:
    state = runtime_control_state_from_task_run(task_run, runtime_host=runtime_host, runtime_control=control)
    if state in {_TASK_RUN_PAUSE_REQUESTED, _TASK_RUN_REPLAN_REQUESTED, _TASK_RUN_STOP_REQUESTED}:
        signal_ref = str(control.get("runtime_control_signal_ref") or "").strip()
        return state if signal_ref else ""
    if state == _TASK_RUN_PAUSED and str(getattr(task_run, "status", "") or "") != "waiting_executor":
        return ""
    if state == _TASK_RUN_INTERRUPTED_FOR_REPLAN and str(getattr(task_run, "status", "") or "") != "waiting_executor":
        return ""
    return state


def _bind_active_turn_for_task_state(runtime_host: Any, task_run: Any, *, state: str) -> None:
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is None:
        return
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    if not session_id or not task_run_id:
        return
    try:
        active_turn = active_registry.snapshot(session_id)
        if active_turn is None:
            return
        if str(getattr(active_turn, "bound_task_run_id", "") or "").strip() != task_run_id:
            return
        active_registry.bind_task_run(
            session_id=session_id,
            turn_id=str(getattr(active_turn, "turn_id", "") or "").strip(),
            task_run_id=task_run_id,
            state=state,
        )
    except Exception:
        return


def _active_turn_bound_to_task(runtime_host: Any, task_run: Any) -> Any | None:
    if _origin_kind(task_run) == "graph_node_assigned":
        return None
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    resolver = getattr(active_registry, "resolve_current", None)
    if not callable(resolver):
        return None
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    if not session_id or not task_run_id:
        return None
    try:
        active_turn = resolver(session_id)
    except Exception:
        return None
    if active_turn is None:
        return None
    if str(getattr(active_turn, "bound_task_run_id", "") or "").strip() != task_run_id:
        return None
    if not bool(getattr(active_turn, "steerable", False)):
        return None
    return active_turn


async def _claim_active_turn_queued_steers_for_task_step(
    runtime_host: Any,
    *,
    task_run: Any,
    step_index: int,
) -> ActiveTurnQueuedUserSteers:
    active_turn = _active_turn_bound_to_task(runtime_host, task_run)
    if active_turn is None:
        return ActiveTurnQueuedUserSteers()
    turn_id = str(getattr(active_turn, "turn_id", "") or "").strip()
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    turn_run = _turn_run_for_active_turn(runtime_host, active_turn)
    return await claim_active_turn_queued_user_steers(
        runtime_host,
        session_id=str(getattr(task_run, "session_id", "") or ""),
        turn_id=turn_id,
        turn_run=turn_run,
        stream_run_id=str(getattr(active_turn, "stream_run_id", "") or ""),
        packet_ref=f"task-executor-before-packet:{task_run_id}:{int(step_index or 0)}",
        phase=f"task_executor_before_packet:{int(step_index or 0)}",
        bound_task_run_id=task_run_id,
        include_model_message=False,
        mirror_bound_task=True,
        source_authority="harness.loop.task_executor.active_turn_steer",
    )


def _turn_run_for_active_turn(runtime_host: Any, active_turn: Any) -> Any | None:
    turn_run_id = str(getattr(active_turn, "turn_run_id", "") or "").strip()
    if not turn_run_id:
        return None
    state_index = getattr(runtime_host, "state_index", None)
    getter = getattr(state_index, "get_turn_run", None)
    if not callable(getter):
        return None
    try:
        return getter(turn_run_id)
    except Exception:
        return None


def _is_task_run_resumable_for_user_control(task_run: Any, *, runtime_host: Any | None = None) -> bool:
    return recovery_state_for_task_run(task_run, runtime_host=runtime_host).same_run_resumable


def _task_run_terminal_conflict_reason(task_run: Any, *, runtime_host: Any | None = None) -> str:
    status = str(getattr(task_run, "status", "") or "").strip()
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or "").strip()
    control_state = runtime_control_state_from_task_run(task_run, runtime_host=runtime_host)
    reason = terminal_reason or control_state or status or "unknown"
    return f"task_run_terminal:{reason}"


def approve_task_run_tool_call(
    runtime_host: Any,
    task_run_id: str,
    *,
    reason: str = "",
    requested_by: str = "user",
    turn_id: str = "",
    ttl_seconds: float = 3600.0,
) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    status = str(getattr(task_run, "status", "") or "")
    if status != "waiting_approval":
        return _conflict(task_run_id, f"task_run_not_waiting_approval:{status}")
    pending_approval = pending_approval_from_task_run(task_run)
    if str(pending_approval.get("status") or "") != "pending":
        return _conflict(task_run_id, "pending_approval_missing")
    grant = build_task_tool_approval_grant(
        task_run=task_run,
        pending_approval=pending_approval,
        requested_by=requested_by,
        ttl_seconds=ttl_seconds,
        reason=reason,
    )
    if grant is None:
        return _conflict(task_run_id, "pending_approval_incomplete")
    now = time.time()
    approval_signal = publish_task_tool_approval_granted(
        runtime_host,
        task_run=task_run,
        grant=grant,
        pending_approval=pending_approval,
    )
    if approval_signal is None:
        return _conflict(task_run_id, "runtime_gateway_approval_signal_unavailable")
    runtime_host.runtime_objects.put_object(APPROVAL_GRANT_KIND, grant.grant_id, grant.to_dict())
    event = runtime_host.event_log.append(
        task_run_id,
        "task_tool_approval_granted",
        payload={
            "task_run_id": task_run_id,
            "grant": grant.to_dict(),
            "pending_approval": pending_approval,
            "reason": reason,
            "requested_by": requested_by,
            **({"turn_id": turn_id} if turn_id else {}),
        },
        refs={
            "task_run_ref": task_run_id,
            "approval_grant_ref": grant.grant_id,
            "action_request_ref": grant.action_request_ref,
            **({"turn_ref": turn_id} if turn_id else {}),
        },
    )
    approved_pending = {
        **pending_approval,
        "status": "approved",
        "approved_at": event.created_at or now,
        "approval_grant_id": grant.grant_id,
    }
    updated = replace(
        task_run,
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        diagnostics={
            **append_task_tool_approval_grant(task_run, grant),
            "pending_approval": approved_pending,
            "executor_status": "waiting_approval",
            "latest_step": "task_tool_approval_granted",
            "latest_step_status": "waiting_approval",
            "latest_step_summary": "工具调用已获确认，等待继续执行。",
            **({"latest_interaction_turn_id": turn_id} if turn_id else {}),
        },
    )
    runtime_host.state_index.upsert_task_run(updated)
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run_id,
        step="task_tool_approval_granted",
        status="waiting_approval",
        summary="工具调用已获确认，等待继续执行。",
        refs={"approval_grant_ref": grant.grant_id, "action_request_ref": grant.action_request_ref},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=updated,
        item_type="progress",
        title="已确认",
        status="waiting_approval",
        summary="工具调用已获确认，等待继续执行。",
        event_offset=event.offset,
        refs={"task_run_ref": task_run_id, "approval_grant_ref": grant.grant_id, "action_request_ref": grant.action_request_ref},
        payload={"pending_approval": approved_pending},
    )
    return {
        "ok": True,
        "accepted": True,
        "task_run": updated.to_dict(),
        "approval_grant": grant.to_dict(),
        "pending_approval": approved_pending,
    }


def _is_single_agent_task_run(task_run: Any) -> bool:
    return str(getattr(task_run, "execution_runtime_kind", "") or "") in {"single_agent_task", "subagent_task"}


def _task_run_session_deleted(runtime_host: Any, task_run: Any) -> bool:
    checker = getattr(getattr(runtime_host, "state_index", None), "is_session_deleted", None)
    if not callable(checker):
        return False
    try:
        return bool(checker(str(getattr(task_run, "session_id", "") or "")))
    except Exception:
        return False


def _executor_control_signal_trace_payload(signal: ExecutorControlSignal | None) -> dict[str, str]:
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


def _executor_control_signal_trace_refs(signal: ExecutorControlSignal | None) -> dict[str, str]:
    return _executor_control_signal_trace_payload(signal)


def request_task_run_pause(runtime_host: Any, task_run_id: str, *, reason: str = "", requested_by: str = "user") -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    status = str(getattr(task_run, "status", "") or "")
    if is_stopped_or_terminal_task_run(task_run, runtime_host=runtime_host):
        return _conflict(task_run_id, _task_run_terminal_conflict_reason(task_run, runtime_host=runtime_host))
    current_state = runtime_control_state_from_task_run(task_run, runtime_host=runtime_host)
    if status == "waiting_executor" and current_state == _TASK_RUN_PAUSED:
        return {"ok": True, "accepted": True, "task_run": task_run.to_dict(), "control": _runtime_control_payload(task_run, runtime_host=runtime_host)}
    now = time.time()
    executor_claimed = is_task_run_executor_claimed(task_run, runtime_host=runtime_host)
    if not executor_claimed:
        updated_status = "waiting_executor" if status in {"created", "running", "queued", "in_progress", "waiting_executor", "blocked"} else status
        control_state = _TASK_RUN_PAUSED
        latest_step_status = "waiting_executor" if updated_status == "waiting_executor" else str(updated_status or status)
    elif status in {"created", "waiting_executor", "waiting_approval", "blocked"}:
        updated_status = "waiting_executor" if status in {"created", "waiting_executor", "blocked"} else status
        control_state = _TASK_RUN_PAUSED if updated_status == "waiting_executor" else _TASK_RUN_PAUSE_REQUESTED
        latest_step_status = "waiting_executor" if updated_status == "waiting_executor" else "waiting_approval"
    else:
        updated_status = status
        control_state = _TASK_RUN_PAUSE_REQUESTED
        latest_step_status = "running"
    control_signal: ExecutorControlSignal | None = None
    if control_state == _TASK_RUN_PAUSE_REQUESTED:
        control_signal = request_executor_control_signal(
            runtime_host,
            task_run_id=task_run_id,
            kind="pause",
            reason=reason,
            requested_by=requested_by,
        )
        if control_signal is None:
            return _conflict(task_run_id, "runtime_gateway_control_signal_unavailable")
    event = runtime_host.event_log.append(
        task_run_id,
        "task_run_pause_requested",
        payload={
            "task_run_id": task_run_id,
            "reason": reason,
            "requested_by": requested_by,
            **_executor_control_signal_trace_payload(control_signal),
        },
        refs={"task_run_ref": task_run_id, **_executor_control_signal_trace_refs(control_signal)},
    )
    updated_diagnostics = _diagnostics_with_runtime_control(
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
        control_signal=control_signal,
    )
    if control_state == _TASK_RUN_PAUSED and updated_status == "waiting_executor":
        updated_diagnostics = {
            **_strip_runtime_lease_diagnostics(updated_diagnostics),
            "executor_status": "waiting_executor",
            "wait_reason": "user_paused",
            "recovery_action": "resume_task_run",
        }
    updated = replace(
        task_run,
        status=updated_status,  # type: ignore[arg-type]
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        terminal_reason="" if updated_status == "waiting_executor" else getattr(task_run, "terminal_reason", ""),
        diagnostics=updated_diagnostics,
    )
    runtime_host.state_index.upsert_task_run(updated)
    _bind_active_turn_for_task_state(
        runtime_host,
        updated,
        state="waiting_executor" if control_state == _TASK_RUN_PAUSED else "waiting_safe_boundary",
    )
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
    return {"ok": True, "accepted": True, "task_run": updated.to_dict(), "control": _runtime_control_payload(updated, runtime_host=runtime_host)}


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
    if is_stopped_or_terminal_task_run(task_run, runtime_host=runtime_host):
        return _conflict(task_run_id, _task_run_terminal_conflict_reason(task_run, runtime_host=runtime_host))
    if status == "waiting_approval" and matching_approval_grant_for_pending(task_run) is None:
        return _conflict(task_run_id, "task_run_waiting_approval_requires_grant")
    if not _is_task_run_resumable_for_user_control(task_run, runtime_host=runtime_host):
        return _conflict(task_run_id, f"task_run_not_resumable:{status}")
    now = time.time()
    recovery_state = recovery_state_for_task_run(task_run, runtime_host=runtime_host)
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
        terminal_reason="",
        diagnostics=_diagnostics_with_runtime_control(
            {
                **_strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
                "executor_status": "waiting_executor",
                "wait_reason": "resume_requested",
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
    return {"ok": True, "accepted": True, "task_run": updated.to_dict(), "control": _runtime_control_payload(updated, runtime_host=runtime_host)}


def stop_task_run(runtime_host: Any, task_run_id: str, *, reason: str = "", requested_by: str = "user") -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    status = str(getattr(task_run, "status", "") or "")
    if is_stopped_or_terminal_task_run(task_run, runtime_host=runtime_host):
        return {"ok": True, "accepted": False, "task_run": task_run.to_dict(), "control": _runtime_control_payload(task_run, runtime_host=runtime_host)}
    now = time.time()
    executor_claimed = is_task_run_executor_claimed(task_run, runtime_host=runtime_host)
    control_signal: ExecutorControlSignal | None = None
    if executor_claimed:
        control_signal = request_executor_control_signal(
            runtime_host,
            task_run_id=task_run_id,
            kind="stop",
            reason=reason,
            requested_by=requested_by,
        )
        if control_signal is None:
            return _conflict(task_run_id, "runtime_gateway_control_signal_unavailable")
    event = runtime_host.event_log.append(
        task_run_id,
        "task_run_stop_requested",
        payload={
            "task_run_id": task_run_id,
            "reason": reason,
            "requested_by": requested_by,
            **_executor_control_signal_trace_payload(control_signal),
        },
        refs={"task_run_ref": task_run_id, **_executor_control_signal_trace_refs(control_signal)},
    )
    if executor_claimed:
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
                control_signal=control_signal,
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
        return {"ok": True, "accepted": True, "task_run": updated.to_dict(), "control": _runtime_control_payload(updated, runtime_host=runtime_host)}
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
        "control": _runtime_control_payload(updated, runtime_host=runtime_host),
    }


def append_user_work_instruction(
    runtime_host: Any,
    task_run_id: str,
    *,
    content: str,
    turn_id: str = "",
    intent: str = "append_instruction_to_active_work",
    editor_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return _not_found(task_run_id)
    if not _is_single_agent_task_run(task_run):
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned":
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    if is_stopped_or_terminal_task_run(task_run, runtime_host=runtime_host):
        return _conflict(task_run_id, _task_run_terminal_conflict_reason(task_run, runtime_host=runtime_host))
    instruction = str(content or "").strip()
    if not instruction:
        return _conflict(task_run_id, "user_work_instruction_empty")
    if is_task_run_executor_claimed(task_run, runtime_host=runtime_host) and not callable(getattr(getattr(runtime_host, "runtime_gateway", None), "publish", None)):
        return _conflict(task_run_id, "runtime_gateway_control_signal_unavailable")
    result = create_active_task_steer(
        runtime_host,
        task_run_id,
        content=instruction,
        turn_id=turn_id,
        intent=intent,
        steer_kind="instruction",
        priority="high",
        editor_context=dict(editor_context or {}),
    )
    if not bool(result.get("ok")):
        return result
    updated = runtime_host.state_index.get_task_run(task_run_id) or task_run
    steer_ref = str(dict(result.get("steer") or {}).get("steer_id") or "")
    if is_task_run_executor_claimed(updated, runtime_host=runtime_host):
        control_signal = request_executor_control_signal(
            runtime_host,
            task_run_id=task_run_id,
            kind="replan",
            reason=intent,
            requested_by="user",
            steer_ref=steer_ref,
        )
        if control_signal is None:
            return {
                **result,
                "ok": False,
                "accepted": False,
                "error": "runtime_gateway_control_signal_unavailable",
                "task_run": updated.to_dict(),
            }
        event = runtime_host.event_log.append(
            task_run_id,
            "task_run_replan_requested",
            payload={
                "task_run_id": task_run_id,
                "reason": intent,
                "steer_ref": steer_ref,
                "signalled": True,
                **_executor_control_signal_trace_payload(control_signal),
            },
            refs={
                "task_run_ref": task_run_id,
                "steer_ref": steer_ref,
                **_executor_control_signal_trace_refs(control_signal),
            },
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
                latest_step_summary="",
                control_signal=control_signal,
            ),
        )
        runtime_host.state_index.upsert_task_run(updated)
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run_id,
        step="active_task_steer_recorded",
        status=str(getattr(updated, "status", "") or "running"),
        summary="",
        presentation_source="system.user_steer_status",
        refs={"steer_ref": steer_ref},
    )
    return {**result, "task_run": updated.to_dict()}


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
    if _task_run_session_deleted(runtime_host, task_run):
        return _conflict(task_run_id, "session_deleted")
    runtime_kind = str(getattr(task_run, "execution_runtime_kind", "") or "")
    if runtime_kind not in {"single_agent_task", "subagent_task"}:
        return _conflict(task_run_id, "not_single_agent_task_run")
    if _origin_kind(task_run) == "graph_node_assigned" and not _graph_node_authorization_matches_identity(
        task_run,
        authorization=graph_node_authorization,
    ):
        return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime")
    control_result = _apply_runtime_control_boundary(runtime_host, task_run=task_run, agent_run=None, boundary="executor_start")
    if control_result is not None:
        return control_result
    active_executor_cell = _active_task_run_executor_cell(runtime_host, task_run)
    live_executor_claimed = active_executor_cell is not None
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    executor_status = str(diagnostics.get("executor_status") or "")
    if active_executor_cell is not None:
        if executor_status == "running":
            recovered = _recover_stale_graph_node_executor_claim(
                runtime_host,
                task_run=task_run,
                graph_node_authorization=graph_node_authorization,
            )
            if recovered is None:
                return _conflict(task_run_id, "task_run_executor_already_running")
            task_run = recovered
    elif executor_status == "running":
        recovered = _recover_stale_graph_node_executor_claim(
            runtime_host,
            task_run=task_run,
            graph_node_authorization=graph_node_authorization,
        )
        if recovered is not None:
            task_run = recovered
    if not is_task_run_executable(task_run, runtime_host=runtime_host) and not live_executor_claimed:
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
    runtime_permission_mode = _task_runtime_permission_mode(task_run, runtime_host=runtime_host)
    runtime_assembly = assemble_runtime(
        backend_dir=services.backend_dir,
        session_id=task_run.session_id,
        turn_id=turn_id,
        agent_invocation_id=f"aginvoke:{task_run.task_run_id}:executor",
        runtime_contract=_runtime_contract_from_task_run(task_run),
        model_selection=model_selection,
        agent_runtime_profile=agent_profile,
        tool_instances=services.all_tool_instances(),
        definitions_by_name=dict(runtime_host.tool_authorization_index.definitions_by_name or {}),
        permission_mode=runtime_permission_mode,
    )
    runtime_tool_plan = build_runtime_tool_plan(
        runtime_assembly=runtime_assembly,
        invocation_kind="task_execution",
        tool_definitions_by_name=dict(runtime_host.tool_authorization_index.definitions_by_name or {}),
    )
    runtime_available_tools = list(runtime_tool_plan.model_visible_tools)
    allowed_tool_names = set(runtime_tool_plan.dispatchable_tool_names)
    runtime_fingerprint = _current_runtime_fingerprint(
        runtime_assembly.to_dict(),
        permission_mode=runtime_permission_mode,
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
        summary="",
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
    control_result = _apply_runtime_control_boundary(runtime_host, task_run=projected_task, agent_run=None, boundary="before_executor_claim")
    if control_result is not None:
        return control_result
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
        specialist_execution = await SpecialistRuntimeRouter(
            services.backend_dir,
            model_runtime=services.model_runtime,
        ).try_run(
            task_run=current_task,
            agent_run=agent_run,
            profile=agent_profile,
            contract=contract,
        )
        if specialist_execution.handled:
            return _finish_specialist_runtime_execution(
                services,
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                execution=specialist_execution,
            )
        return await _execute_claimed_task_run(
            services,
            runtime_host=runtime_host,
            task_run=task_run,
            current_task=current_task,
            agent_run=agent_run,
            contract=contract,
            runtime_assembly=runtime_assembly,
            runtime_tool_plan=runtime_tool_plan,
            runtime_available_tools=runtime_available_tools,
            allowed_tool_names=allowed_tool_names,
            runtime_permission_mode=runtime_permission_mode,
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


async def _replay_approved_pending_tool_call(
    runtime_host: Any,
    *,
    services: TaskExecutorServices,
    current_task: Any,
    agent_run: Any,
    runtime_assembly: Any,
    runtime_tool_plan: Any,
    allowed_tool_names: set[str],
    runtime_permission_mode: str,
    runtime_fingerprint: dict[str, Any],
    raw_observations: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    execution_state: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    pending = pending_approval_from_task_run(current_task)
    if str(pending.get("status") or "") != "approved":
        return None
    if matching_approval_grant_for_pending(current_task) is None:
        return None
    payload = dict(pending.get("action_request") or {})
    action_request, protocol = task_execution_action_request_from_payload(
        payload,
        turn_id=current_task.task_run_id,
        require_public_progress_note=False,
        require_public_action_state=False,
        public_response_required=False,
        allowed_action_types=("tool_call",),
    )
    if action_request is None:
        observation = _model_protocol_repair_observation(
            task_run_id=current_task.task_run_id,
            packet_ref=str(pending.get("directive_ref") or ""),
            step_index=int(dict(getattr(current_task, "diagnostics", {}) or {}).get("next_invocation_index") or 0),
            diagnostics=protocol,
            runtime_fingerprint=runtime_fingerprint,
        )
        raw_observations.append(observation)
        runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
        return {
            "current_task": runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task,
            "raw_observations": raw_observations,
            "observations": observations,
            "execution_state": execution_state,
            "artifact_refs": artifact_refs,
        }
    replay_turn_id = str(dict(getattr(current_task, "diagnostics", {}) or {}).get("turn_id") or current_task.task_id or "")
    lifecycle = decide_model_action_lifecycle(
        action_request,
        packet_allowed_action_types=("tool_call",),
        definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
        allowed_tool_names=allowed_tool_names,
        runtime_profile=dict(runtime_assembly.profile.to_dict() if hasattr(runtime_assembly, "profile") else dict(runtime_assembly or {}).get("profile") or {}),
        invocation_kind="task_execution",
        permit_invocation_kind="task_execution",
        packet_ref=str(pending.get("directive_ref") or ""),
        permission_mode=runtime_permission_mode,
        side_effect_policy="runtime_authorized",
        session_id=current_task.session_id,
        turn_id=replay_turn_id,
        task_run_id=current_task.task_run_id,
        grant_scope="task_run",
    )
    admission = lifecycle.admission
    if admission.decision != "allow":
        admission_observation = _model_action_admission_recovery_observation(
            task_run_id=current_task.task_run_id,
            packet_ref=str(pending.get("directive_ref") or ""),
            action_request=action_request,
            admission=admission,
            runtime_fingerprint=runtime_fingerprint,
            step_index=int(dict(getattr(current_task, "diagnostics", {}) or {}).get("next_invocation_index") or 0),
        )
        raw_observations.append(admission_observation)
        runtime_host.runtime_objects.put_object("observation", admission_observation["observation_id"], admission_observation)
        observation_context = _observations_for_packet(
            runtime_host,
            current_task.task_run_id,
            current_fingerprint=runtime_fingerprint,
            pending_observations=raw_observations,
        )
        return {
            "current_task": runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task,
            "raw_observations": list(observation_context["raw_observations"]),
            "observations": list(observation_context["packet_observations"]),
            "execution_state": dict(observation_context["execution_state"]),
            "artifact_refs": dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs]),
        }
    _record_task_step_summary(
        runtime_host,
        task_run_id=current_task.task_run_id,
        step="approved_tool_call_replay_started",
        status="running",
        summary="正在执行已确认的工具调用。",
        refs={
            "approval_grant_ref": str(
                dict(dict(getattr(current_task, "diagnostics", {}) or {}).get("approval_state") or {}).get("latest_grant_id") or ""
            )
        },
    )
    observation = await _execute_task_tool_call(
        runtime_host,
        services=services,
        task_run=current_task,
        packet_ref=str(pending.get("directive_ref") or ""),
        action_request=action_request,
        admission=admission,
        runtime_assembly=runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {}),
        runtime_tool_plan=runtime_tool_plan,
    )
    raw_observations.append(observation)
    runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
    observation_event = runtime_host.event_log.append(
        current_task.task_run_id,
        "approved_task_tool_observation_recorded",
        payload={"observation": observation, "pending_approval": pending},
        refs={
            "task_run_ref": current_task.task_run_id,
            "action_request_ref": action_request.request_id,
            "observation_ref": observation["observation_id"],
        },
    )
    if _is_approval_request_observation(observation):
        return {
            "return_result": _pause_executor_for_tool_approval(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                action_request=action_request,
                observation=observation,
                observation_event=observation_event,
                step_index=int(dict(getattr(current_task, "diagnostics", {}) or {}).get("next_invocation_index") or 0),
            )
        }
    _record_task_step_summary(
        runtime_host,
        task_run_id=current_task.task_run_id,
        step="approved_tool_call_replayed",
        status=_observation_status(observation),
        summary="已执行确认后的工具调用。",
        refs={"observation_ref": observation["observation_id"], "action_request_ref": action_request.request_id},
    )
    observation_context = _observations_for_packet(
        runtime_host,
        current_task.task_run_id,
        current_fingerprint=runtime_fingerprint,
        pending_observations=raw_observations,
    )
    latest_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
    return {
        "current_task": latest_task,
        "raw_observations": list(observation_context["raw_observations"]),
        "observations": list(observation_context["packet_observations"]),
        "execution_state": dict(observation_context["execution_state"]),
        "artifact_refs": dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs, *_artifact_refs_from_observation(observation)]),
    }


async def _runtime_memory_context_for_task_step(
    services: TaskExecutorServices,
    *,
    session_id: str,
    task_run: Any,
    contract: dict[str, Any],
    observations: list[dict[str, Any]],
    execution_state: dict[str, Any],
    runtime_assembly: Any,
    agent_runtime_profile: Any,
    invocation_index: int,
    inherited_start_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = getattr(services, "memory_context_provider", None)
    if not callable(provider):
        return {}
    try:
        result = provider(
            {
                "session_id": session_id,
                "task_run_id": str(getattr(task_run, "task_run_id", "") or ""),
                "task_run": task_run.to_dict() if hasattr(task_run, "to_dict") else dict(task_run or {}),
                "contract": dict(contract or {}),
                "observations": [dict(item) for item in list(observations or []) if isinstance(item, dict)],
                "execution_state": dict(execution_state or {}),
                "inherited_start_context": dict(inherited_start_context or {}),
                "runtime_assembly": runtime_assembly,
                "agent_runtime_profile": agent_runtime_profile,
                "invocation_index": int(invocation_index or 1),
            }
        )
        if asyncio.iscoroutine(result):
            result = await result
    except Exception:
        return {}
    return dict(result or {}) if isinstance(result, dict) else {}


async def _execute_claimed_task_run(
    services: TaskExecutorServices,
    *,
    runtime_host: Any,
    task_run: Any,
    current_task: Any,
    agent_run: Any,
    contract: Any,
    runtime_assembly: Any,
    runtime_tool_plan: Any,
    runtime_available_tools: list[dict[str, Any]],
    allowed_tool_names: set[str],
    runtime_permission_mode: str,
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
    replay = await _replay_approved_pending_tool_call(
        runtime_host,
        services=services,
        current_task=current_task,
        agent_run=agent_run,
        runtime_assembly=runtime_assembly,
        runtime_tool_plan=runtime_tool_plan,
        allowed_tool_names=allowed_tool_names,
        runtime_permission_mode=runtime_permission_mode,
        runtime_fingerprint=runtime_fingerprint,
        raw_observations=raw_observations,
        observations=observations,
        execution_state=execution_state,
        artifact_refs=artifact_refs,
    )
    if replay is not None:
        if replay.get("return_result") is not None:
            return dict(replay["return_result"])
        current_task = replay["current_task"]
        raw_observations = list(replay["raw_observations"])
        observations = list(replay["observations"])
        execution_state = dict(replay["execution_state"])
        artifact_refs = list(replay["artifact_refs"])
    for local_step_index in range(1, max(1, int(max_steps or _MAX_TASK_EXECUTION_STEPS)) + 1):
        step_index = sequence.next_invocation_index + local_step_index - 1
        if _task_run_session_deleted(runtime_host, current_task):
            return _conflict(current_task.task_run_id, "session_deleted")
        control_result = _apply_runtime_control_boundary(runtime_host, task_run=current_task, agent_run=agent_run, boundary=f"step_start:{step_index}")
        if control_result is not None:
            return control_result
        control_followup = _record_pending_runtime_control_signal_for_agent(
            runtime_host,
            current_task=current_task,
            signal=None,
            packet_ref=f"runtime-control-boundary:{current_task.task_run_id}:step:{step_index}",
            boundary=f"step_start:{step_index}",
            raw_observations=raw_observations,
            observations=observations,
            execution_state=execution_state,
            artifact_refs=artifact_refs,
            runtime_fingerprint=runtime_fingerprint,
            step_index=step_index,
        )
        if control_followup is not None:
            current_task = control_followup["current_task"]
            raw_observations = list(control_followup["raw_observations"])
            observations = list(control_followup["observations"])
            execution_state = dict(control_followup["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(control_followup["artifact_refs"]))
        current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
        if _task_run_session_deleted(runtime_host, current_task):
            return _conflict(current_task.task_run_id, "session_deleted")
        active_turn_steer_batch = await _claim_active_turn_queued_steers_for_task_step(
            runtime_host,
            task_run=current_task,
            step_index=step_index,
        )
        if active_turn_steer_batch.items:
            current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
            observation_context = _observations_for_packet(
                runtime_host,
                current_task.task_run_id,
                current_fingerprint=runtime_fingerprint,
                pending_observations=raw_observations,
            )
            raw_observations = list(observation_context["raw_observations"])
            observations = list(observation_context["packet_observations"])
            execution_state = dict(observation_context["execution_state"])
            artifact_refs = dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs])
        start_context_handoff = load_turn_to_task_context_handoff(runtime_host, current_task)
        inherited_start_context = inherited_start_context_for_model(start_context_handoff)
        memory_context = await _runtime_memory_context_for_task_step(
            services,
            session_id=current_task.session_id,
            task_run=current_task,
            contract=contract,
            observations=observations,
            execution_state=execution_state,
            runtime_assembly=runtime_assembly,
            agent_runtime_profile=services.agent_runtime_profile,
            invocation_index=step_index,
            inherited_start_context=inherited_start_context,
        )
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
            memory_context=memory_context,
            inherited_start_context=inherited_start_context,
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
        evidence_event = _publish_packet_evidence_projection_event(
            runtime_host,
            run_id=current_task.task_run_id,
            packet_context=dict(compilation.packet.diagnostics.get("runtime_packet_context") or {}),
            refs={
                "task_run_ref": current_task.task_run_id,
                "runtime_envelope_ref": compilation.envelope.envelope_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
                "packet_compiled_event_ref": packet_event.event_id,
                "executor_epoch": sequence.executor_epoch,
                "invocation_index": step_index,
            },
        )
        latest_packet_event_offset = max(
            packet_event.offset,
            int(getattr(evidence_event, "offset", packet_event.offset) or packet_event.offset),
        )
        runtime_host.state_index.upsert_task_run(
            replace(
                current_task,
                latest_event_offset=latest_packet_event_offset,
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
        control_followup = _record_pending_runtime_control_signal_for_agent(
            runtime_host,
            current_task=current_task,
            signal=None,
            packet_ref=compilation.packet.packet_id,
            boundary=f"before_model_action:{step_index}",
            raw_observations=raw_observations,
            observations=observations,
            execution_state=execution_state,
            artifact_refs=artifact_refs,
            runtime_fingerprint=runtime_fingerprint,
            step_index=step_index,
            event_offset=packet_event.offset,
        )
        if control_followup is not None:
            current_task = control_followup["current_task"]
            raw_observations = list(control_followup["raw_observations"])
            observations = list(control_followup["observations"])
            execution_state = dict(control_followup["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(control_followup["artifact_refs"]))
            continue
        _record_task_model_wait_heartbeat(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"task_model_action_invocation_started:{step_index}",
            wait_round=0,
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
            control_followup = _record_pending_runtime_control_signal_for_agent(
                runtime_host,
                current_task=interrupted_task,
                signal=exc.signal,
                packet_ref=compilation.packet.packet_id,
                boundary=f"model_action_wait:{step_index}",
                raw_observations=raw_observations,
                observations=observations,
                execution_state=execution_state,
                artifact_refs=artifact_refs,
                runtime_fingerprint=runtime_fingerprint,
                step_index=step_index,
                event_offset=packet_event.offset,
            )
            if control_followup is not None:
                current_task = control_followup["current_task"]
                raw_observations = list(control_followup["raw_observations"])
                observations = list(control_followup["observations"])
                execution_state = dict(control_followup["execution_state"])
                artifact_refs = dedupe_artifact_refs(list(control_followup["artifact_refs"]))
                continue
            return _pause_executor_for_model_recovery(
                runtime_host,
                task_run=interrupted_task,
                agent_run=agent_run,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                error=exc,
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
                presentation_source=_PROTOCOL_REPAIR_PRESENTATION_SOURCE,
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
            artifact_refs = dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs])
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
        public_action_state = _action_public_state(action_request)
        action_progress = _action_progress_note(action_request)
        visible_public_note = public_runtime_progress_summary(action_request.public_progress_note)
        presentation_source = (
            "model_action.public_progress_note"
            if visible_public_note
            else ("model_action.public_action_state" if action_progress else "model_action.no_public_feedback")
        )
        action_tool_call = dict(action_request.tool_call or {})
        action_tool_args = dict(action_tool_call.get("args") or action_tool_call.get("tool_args") or {})
        action_tool_name = str(action_tool_call.get("tool_name") or action_tool_call.get("name") or "").strip()
        action_tool_target = _tool_target_preview(action_tool_args)
        action_brief = compact_text(action_request.final_answer, limit=300) if action_request.action_type == "respond" else ""
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"model_action_received:{step_index}",
            status="running",
            summary=action_progress,
            public_progress_note=action_request.public_progress_note,
            agent_brief_output=action_brief,
            action_type=action_request.action_type,
            current_judgment=public_action_state.get("current_judgment", ""),
            next_action=public_action_state.get("next_action", ""),
            completion_status=public_action_state.get("completion_status", ""),
            open_risks=list(public_action_state.get("open_risks") or []),
            evidence_refs=list(public_action_state.get("evidence_refs") or []),
            presentation_source=presentation_source,
            tool_name=action_tool_name,
            tool_target=action_tool_target,
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
            replan_control_consumption = _mark_replan_control_signals_consumed_by_model_action(
                runtime_host,
                task_run=current_task,
                action_request=action_request,
                observations=raw_observations,
                consumed_steer_ids=consumed_steer_ids,
            )
            if replan_control_consumption["missing_steer_refs"]:
                return _finish_executor_blocked(
                    runtime_host,
                    task_run=current_task,
                    agent_run=agent_run,
                    terminal_reason="runtime_gateway_control_signal_consumption_unavailable",
                    payload={
                        "recoverable_error": {
                            "error_code": "runtime_gateway_control_signal_consumption_unavailable",
                            "retryable": True,
                            "missing_steer_refs": list(replan_control_consumption["missing_steer_refs"]),
                        },
                        "recovery_action": "rerun_task_executor",
                    },
                )
            mark_task_steers_consumed(
                runtime_host,
                current_task.task_run_id,
                steer_ids=consumed_steer_ids,
                action_ref=action_request.request_id,
            )
        if action_progress or action_brief:
            append_work_rollout_item(
                runtime_host,
                task_run=current_task,
                item_type="progress",
                title="模型反馈",
                status="running",
                summary=action_progress,
                agent_brief_output=action_brief,
                event_offset=action_event.offset,
                refs={"action_request_ref": action_request.request_id, "runtime_invocation_packet_ref": compilation.packet.packet_id},
                payload={
                    "action_type": action_request.action_type,
                    "public_progress_note": visible_public_note,
                    "public_action_state": public_action_state,
                    "presentation_source": presentation_source,
                    "model_visible": False,
                },
            )
        current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
        control_result = _apply_runtime_control_boundary(runtime_host, task_run=current_task, agent_run=agent_run, boundary=f"after_model_action:{step_index}")
        if control_result is not None:
            return control_result
        control_followup = _record_pending_runtime_control_signal_for_agent(
            runtime_host,
            current_task=current_task,
            signal=None,
            packet_ref=compilation.packet.packet_id,
            boundary=f"after_model_action:{step_index}",
            raw_observations=raw_observations,
            observations=observations,
            execution_state=execution_state,
            artifact_refs=artifact_refs,
            runtime_fingerprint=runtime_fingerprint,
            step_index=step_index,
            event_offset=action_event.offset,
        )
        if control_followup is not None:
            current_task = control_followup["current_task"]
            raw_observations = list(control_followup["raw_observations"])
            observations = list(control_followup["observations"])
            execution_state = dict(control_followup["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(control_followup["artifact_refs"]))
            continue

        if action_request.action_type == "tool_call":
            batch_result = await _process_task_tool_call_batch(
                runtime_host,
                services=services,
                current_task=current_task,
                agent_run=agent_run,
                action_request=action_request,
                runtime_assembly=runtime_assembly,
                runtime_tool_plan=runtime_tool_plan,
                allowed_tool_names=allowed_tool_names,
                runtime_permission_mode=runtime_permission_mode,
                runtime_fingerprint=runtime_fingerprint,
                raw_observations=raw_observations,
                observations=observations,
                execution_state=execution_state,
                artifact_refs=artifact_refs,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                action_event_offset=action_event.offset,
            )
            if batch_result.get("return_result") is not None:
                return batch_result["return_result"]
            current_task = batch_result["current_task"]
            raw_observations = list(batch_result["raw_observations"])
            observations = list(batch_result["observations"])
            execution_state = dict(batch_result["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(batch_result["artifact_refs"]))
            continue

        action_turn_id = str(dict(getattr(current_task, "diagnostics", {}) or {}).get("turn_id") or current_task.task_id or "")
        lifecycle = decide_model_action_lifecycle(
            action_request,
            packet_allowed_action_types=tuple(compilation.packet.allowed_action_types or ()),
            invocation_kind="task_execution",
            permit_invocation_kind="task_execution",
            packet_ref=compilation.packet.packet_id,
            definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
            allowed_tool_names=allowed_tool_names,
            runtime_profile=dict(runtime_assembly.profile.to_dict()),
            permission_mode=runtime_permission_mode,
            side_effect_policy="runtime_authorized",
            session_id=current_task.session_id,
            turn_id=action_turn_id,
            task_run_id=current_task.task_run_id,
            grant_scope="task_run",
        )
        admission = lifecycle.admission
        event_record = build_action_lifecycle_event_record(
            lifecycle,
            action_request,
            run_id=current_task.task_run_id,
            packet_ref=compilation.packet.packet_id,
            session_id=current_task.session_id,
            turn_id=action_turn_id,
            task_run_id=current_task.task_run_id,
        )
        append_action_lifecycle_event(runtime_host, event_record)
        current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
        control_result = _apply_runtime_control_boundary(runtime_host, task_run=current_task, agent_run=agent_run, boundary=f"after_action_admission:{step_index}")
        if control_result is not None:
            return control_result
        control_followup = _record_pending_runtime_control_signal_for_agent(
            runtime_host,
            current_task=current_task,
            signal=None,
            packet_ref=compilation.packet.packet_id,
            boundary=f"after_action_admission:{step_index}",
            raw_observations=raw_observations,
            observations=observations,
            execution_state=execution_state,
            artifact_refs=artifact_refs,
            runtime_fingerprint=runtime_fingerprint,
            step_index=step_index,
            event_offset=action_event.offset,
        )
        if control_followup is not None:
            current_task = control_followup["current_task"]
            raw_observations = list(control_followup["raw_observations"])
            observations = list(control_followup["observations"])
            execution_state = dict(control_followup["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(control_followup["artifact_refs"]))
            continue
        if admission.decision != "allow":
            admission_result = _record_task_admission_observation(
                runtime_host,
                current_task=current_task,
                agent_run=agent_run,
                action_request=action_request,
                admission=admission,
                runtime_fingerprint=runtime_fingerprint,
                raw_observations=raw_observations,
                observations=observations,
                execution_state=execution_state,
                artifact_refs=artifact_refs,
                packet_ref=compilation.packet.packet_id,
                step_index=step_index,
                event_offset=action_event.offset,
            )
            if admission_result.get("return_result") is not None:
                return admission_result["return_result"]
            current_task = admission_result["current_task"]
            raw_observations = list(admission_result["raw_observations"])
            observations = list(admission_result["observations"])
            execution_state = dict(admission_result["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(admission_result["artifact_refs"]))
            continue

        if action_request.action_type == "respond":
            control_closeout_observation = _latest_agent_closeout_runtime_control_observation(raw_observations)
            if control_closeout_observation is not None:
                return _finish_executor_agent_controlled_runtime_boundary(
                    services,
                    runtime_host,
                    task_run=current_task,
                    agent_run=agent_run,
                    action_request=action_request,
                    control_observation=control_closeout_observation,
                    artifact_refs=dedupe_artifact_refs([*artifact_refs, *_artifacts_from_action(action_request)]),
                    observations=raw_observations,
                )
            if not str(action_request.final_answer or "").strip():
                repair_observation = _model_protocol_repair_observation(
                    task_run_id=current_task.task_run_id,
                    packet_ref=compilation.packet.packet_id,
                    step_index=step_index,
                    diagnostics={"validation_errors": ["final_answer_required_for_respond"], "action_request": action_request.to_dict()},
                    runtime_fingerprint=runtime_fingerprint,
                )
                raw_observations.append(repair_observation)
                runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
                runtime_host.event_log.append(
                    current_task.task_run_id,
                    "task_model_action_protocol_repair_required",
                    payload={"observation": repair_observation, "diagnostics": {"validation_errors": ["final_answer_required_for_respond"]}},
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
                    summary="模型 respond 动作缺少 final_answer，已反馈模型修正。",
                    presentation_source=_PROTOCOL_REPAIR_PRESENTATION_SOURCE,
                    refs={"observation_ref": repair_observation["observation_id"]},
                )
                if _model_protocol_repair_count(raw_observations) >= _MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS:
                    return _finish_executor_blocked(
                        runtime_host,
                        task_run=current_task,
                        agent_run=agent_run,
                        terminal_reason="model_action_protocol_repair_required",
                        payload={
                            "recoverable_error": {
                                "error_code": "model_action_invalid",
                                "retryable": True,
                                "reason": "final_answer_required_for_respond",
                            },
                            "recovery_action": "rerun_task_executor",
                            "action_request": action_request.to_dict(),
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
                artifact_refs = dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs])
                continue
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
                artifact_refs = dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs])
                continue
            active_subagents = _active_child_subagent_summaries(
                runtime_host,
                task_run=current_task,
                parent_agent_run=agent_run,
            )
            if active_subagents:
                repair_observation = _active_subagent_completion_repair_observation(
                    task_run_id=current_task.task_run_id,
                    packet_ref=compilation.packet.packet_id,
                    action_request=action_request,
                    active_subagents=active_subagents,
                )
                raw_observations.append(repair_observation)
                runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
                runtime_host.event_log.append(
                    current_task.task_run_id,
                    "task_completion_repair_required",
                    payload={"observation": repair_observation, "active_subagents": active_subagents},
                    refs={"task_run_ref": current_task.task_run_id, "observation_ref": repair_observation["observation_id"]},
                )
                _record_task_step_summary(
                    runtime_host,
                    task_run_id=current_task.task_run_id,
                    step=f"task_completion_active_subagent_required:{step_index}",
                    status="running",
                    summary="仍有子 Agent 未完成，正在等待或收口子任务后再完成父任务。",
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
                artifact_refs = dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs])
                continue
            candidate_artifacts = dedupe_artifact_refs([*artifact_refs, *_artifacts_from_action(action_request)])
            verdict = _verify_completion(
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly.to_dict(),
                task_run_id=current_task.task_run_id,
                contract=contract,
                artifact_refs=candidate_artifacts,
                observations=raw_observations,
                enforce_verification_gate=_should_enforce_completion_verification_gate(current_task, contract=contract),
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
                artifact_refs = dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs])
                continue
            return _finish_executor_success(
                services,
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                final_answer=action_request.final_answer,
                final_action_diagnostics={
                    **dict(action_request.diagnostics or {}),
                    "completion_verdict": verdict,
                },
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


async def _process_task_tool_call_batch(
    runtime_host: Any,
    *,
    services: TaskExecutorServices,
    current_task: Any,
    agent_run: Any,
    action_request: AnyModelActionRequest,
    runtime_assembly: Any,
    runtime_tool_plan: Any,
    allowed_tool_names: set[str],
    runtime_permission_mode: str,
    runtime_fingerprint: dict[str, Any],
    raw_observations: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    execution_state: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    packet_ref: str,
    step_index: int,
    action_event_offset: int | float = 0,
) -> dict[str, Any]:
    try:
        child_requests = _task_tool_child_action_requests(action_request)
    except TaskToolChildActionProtocolError as exc:
        repair_observation = _model_protocol_repair_observation(
            task_run_id=current_task.task_run_id,
            packet_ref=packet_ref,
            step_index=step_index,
            diagnostics={
                "status": "rejected",
                "validation_errors": [exc.code],
                "authority": "harness.loop.task_executor.task_tool_child_action_protocol",
            },
            runtime_fingerprint=runtime_fingerprint,
        )
        raw_observations.append(repair_observation)
        runtime_host.runtime_objects.put_object("observation", repair_observation["observation_id"], repair_observation)
        runtime_host.event_log.append(
            current_task.task_run_id,
            "task_model_action_protocol_repair_required",
            payload={"observation": repair_observation, "diagnostics": {"validation_errors": [exc.code]}},
            refs={
                "task_run_ref": current_task.task_run_id,
                "runtime_invocation_packet_ref": packet_ref,
                "observation_ref": repair_observation["observation_id"],
                "action_request_ref": action_request.request_id,
            },
        )
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"model_action_protocol_repair_required:{step_index}",
            status="running",
            summary=repair_observation["summary"],
            presentation_source=_PROTOCOL_REPAIR_PRESENTATION_SOURCE,
            refs={"observation_ref": repair_observation["observation_id"], "action_request_ref": action_request.request_id},
        )
        return {
            "current_task": current_task,
            "raw_observations": raw_observations,
            "observations": observations,
            "execution_state": execution_state,
            "artifact_refs": artifact_refs,
        }
    if not child_requests:
        return {
            "current_task": current_task,
            "raw_observations": raw_observations,
            "observations": observations,
            "execution_state": execution_state,
            "artifact_refs": artifact_refs,
        }
    tool_progress = _tool_calls_progress_summary(action_request)
    _record_task_step_summary(
        runtime_host,
        task_run_id=current_task.task_run_id,
        step=f"task_tool_batch_started:{step_index}",
        status="running",
        summary=tool_progress,
        tool_status=tool_progress,
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
        event_offset=action_event_offset,
        refs={"action_request_ref": action_request.request_id, "runtime_invocation_packet_ref": packet_ref},
        payload={
            "action_type": "tool_call",
            "tool_calls": [dict(item.tool_call or {}) for item in child_requests],
            "model_visible": False,
        },
    )
    invocation_rows: list[dict[str, Any]] = []
    tool_turn_id = str(dict(getattr(current_task, "diagnostics", {}) or {}).get("turn_id") or current_task.task_id or "")
    for child_request in child_requests:
        lifecycle = decide_model_action_lifecycle(
            child_request,
            packet_allowed_action_types=("respond", "ask_user", "tool_call", "block"),
            invocation_kind="task_execution",
            permit_invocation_kind="task_execution",
            packet_ref=packet_ref,
            definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
            allowed_tool_names=allowed_tool_names,
            runtime_profile=dict(runtime_assembly.profile.to_dict()),
            permission_mode=runtime_permission_mode,
            side_effect_policy="runtime_authorized",
            session_id=current_task.session_id,
            turn_id=tool_turn_id,
            task_run_id=current_task.task_run_id,
            grant_scope="task_run",
        )
        admission = lifecycle.admission
        action_permit = lifecycle.action_permit
        event_record = build_action_lifecycle_event_record(
            lifecycle,
            child_request,
            run_id=current_task.task_run_id,
            packet_ref=packet_ref,
            session_id=current_task.session_id,
            turn_id=tool_turn_id,
            task_run_id=current_task.task_run_id,
            batch_action_request_ref=action_request.request_id,
        )
        append_action_lifecycle_event(runtime_host, event_record)
        row = {
            "action_request": child_request,
            "tool_call": dict(child_request.tool_call or {}),
            "admission": admission,
            "action_lifecycle": lifecycle.to_dict(),
            "action_permit": action_permit.to_dict(),
            "observation": None,
        }
        if admission.decision != "allow":
            invocation_rows.append(row)
            admission_result = _record_task_admission_observation(
                runtime_host,
                current_task=current_task,
                agent_run=agent_run,
                action_request=child_request,
                admission=admission,
                runtime_fingerprint=runtime_fingerprint,
                raw_observations=raw_observations,
                observations=observations,
                execution_state=execution_state,
                artifact_refs=artifact_refs,
                packet_ref=packet_ref,
                step_index=step_index,
                event_offset=action_event_offset,
            )
            if admission_result.get("return_result") is not None:
                return admission_result
            current_task = admission_result["current_task"]
            raw_observations = list(admission_result["raw_observations"])
            observations = list(admission_result["observations"])
            execution_state = dict(admission_result["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(admission_result["artifact_refs"]))
            continue
        duplicate_observation = _duplicate_read_only_tool_call_observation(
            task_run_id=current_task.task_run_id,
            packet_ref=packet_ref,
            action_request=child_request,
            previous_observations=raw_observations,
            runtime_fingerprint={"runtime_fingerprint": runtime_fingerprint},
        )
        if duplicate_observation:
            duplicate_result = _record_duplicate_tool_call_guard_observation_for_tool_child(
                runtime_host,
                current_task=current_task,
                action_request=child_request,
                observation=duplicate_observation,
                runtime_fingerprint=runtime_fingerprint,
                raw_observations=raw_observations,
                observations=observations,
                execution_state=execution_state,
                artifact_refs=artifact_refs,
                packet_ref=packet_ref,
                step_index=step_index,
                event_offset=action_event_offset,
            )
            current_task = duplicate_result["current_task"]
            raw_observations = list(duplicate_result["raw_observations"])
            observations = list(duplicate_result["observations"])
            execution_state = dict(duplicate_result["execution_state"])
            artifact_refs = dedupe_artifact_refs(list(duplicate_result["artifact_refs"]))
            continue
        invocation_rows.append(row)
    batch_plan = build_tool_batch_plan(
        turn_id=current_task.task_run_id,
        packet_ref=packet_ref,
        invocation_rows=invocation_rows,
        tool_plan=runtime_tool_plan,
        definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
        workspace_root=_task_batch_workspace_root(runtime_assembly, runtime_host=runtime_host),
    )
    runtime_host.event_log.append(
        current_task.task_run_id,
        "task_tool_batch_planned",
        payload={
            "task_run_id": current_task.task_run_id,
            "packet_ref": packet_ref,
            "tool_batch_plan": batch_plan.to_dict(),
        },
        refs={
            "task_run_ref": current_task.task_run_id,
            "runtime_invocation_packet_ref": packet_ref,
            "tool_batch_ref": batch_plan.batch_id,
            "action_request_ref": action_request.request_id,
        },
    )
    for group in batch_plan.groups:
        group_event = runtime_host.event_log.append(
            current_task.task_run_id,
            "task_tool_batch_group_started",
            payload={
                "task_run_id": current_task.task_run_id,
                "packet_ref": packet_ref,
                "tool_batch_ref": batch_plan.batch_id,
                "tool_batch_group": group.to_dict(),
            },
            refs={
                "task_run_ref": current_task.task_run_id,
                "runtime_invocation_packet_ref": packet_ref,
                "tool_batch_ref": batch_plan.batch_id,
            },
        )
        try:
            group_execution = await _execute_task_tool_batch_group(
                group,
                invocation_rows=invocation_rows,
                runtime_host=runtime_host,
                services=services,
                task_run=current_task,
                packet_ref=packet_ref,
                runtime_assembly=runtime_assembly,
                runtime_tool_plan=runtime_tool_plan,
            )
            group_results = list(group_execution.get("results") or [])
            group_interrupt = group_execution.get("interrupt")
        except TaskRunExecutorInterrupted as exc:
            interrupted_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
            control_followup = _record_pending_runtime_control_signal_for_agent(
                runtime_host,
                current_task=interrupted_task,
                signal=exc.signal,
                packet_ref=packet_ref,
                boundary=f"tool_batch_execution:{step_index}",
                raw_observations=raw_observations,
                observations=observations,
                execution_state=execution_state,
                artifact_refs=artifact_refs,
                runtime_fingerprint=runtime_fingerprint,
                step_index=step_index,
                event_offset=group_event.offset,
            )
            if control_followup is not None:
                return control_followup
            return {
                "return_result": _pause_executor_for_model_recovery(
                    runtime_host,
                    task_run=interrupted_task,
                    agent_run=agent_run,
                    packet_ref=packet_ref,
                    step_index=step_index,
                    error=exc,
                )
            }
        completed_refs: list[str] = []
        completed_statuses: list[str] = []
        for row, observation in group_results:
            scope_status = _task_tool_observation_scope_status(
                runtime_host,
                task_run=current_task,
                observation=observation,
            )
            if scope_status.get("accepted") is not True:
                _record_late_task_tool_observation_rejected(
                    runtime_host,
                    task_run=current_task,
                    row=row,
                    observation=observation,
                    packet_ref=packet_ref,
                    tool_batch_ref=batch_plan.batch_id,
                    group=group,
                    scope_status=scope_status,
                )
                continue
            raw_observations.append(observation)
            runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
            observation_event = runtime_host.event_log.append(
                current_task.task_run_id,
                "task_tool_observation_recorded",
                payload={
                    "observation": observation,
                    "tool_batch_ref": batch_plan.batch_id,
                    "tool_batch_group": group.to_dict(),
                },
                refs={
                    "task_run_ref": current_task.task_run_id,
                    "action_request_ref": row["action_request"].request_id,
                    "observation_ref": observation["observation_id"],
                    "tool_batch_ref": batch_plan.batch_id,
                },
            )
            completed_refs.append(str(observation.get("observation_id") or ""))
            completed_statuses.append(_observation_status(observation))
            artifact_refs = dedupe_artifact_refs([*artifact_refs, *_artifact_refs_from_observation(observation)])
            if _is_approval_request_observation(observation):
                return {
                    "return_result": _pause_executor_for_tool_approval(
                        runtime_host,
                        task_run=current_task,
                        agent_run=agent_run,
                        action_request=row["action_request"],
                        observation=observation,
                        observation_event=observation_event,
                        step_index=step_index,
                    )
                }
            repeated_failure = _record_repeated_tool_failure_if_needed(
                runtime_host,
                current_task=current_task,
                agent_run=agent_run,
                action_request=row["action_request"],
                observation=observation,
                packet_ref=packet_ref,
                raw_observations=raw_observations,
                step_index=step_index,
            )
            if repeated_failure.get("return_result") is not None:
                return repeated_failure
            observation_summary = _observation_public_step_summary(observation)
            observation_error = str(observation.get("error") or "")
            _record_task_step_summary(
                runtime_host,
                task_run_id=current_task.task_run_id,
                step=f"task_tool_observation_recorded:{step_index}",
                status="running",
                summary=observation_summary,
                agent_brief_output=_observation_brief(observation),
                presentation_source="tool_observation.summary",
                refs={
                    "observation_ref": observation["observation_id"],
                    "tool_name": _observation_tool_name(observation),
                    "action_request_ref": row["action_request"].request_id,
                },
            )
            rollout_summary = "工具调用失败，正在根据失败原因调整处理路径。" if observation_error else observation_summary
            if rollout_summary:
                append_work_rollout_item(
                    runtime_host,
                    task_run=current_task,
                    item_type="progress",
                    title="执行操作",
                    status="running",
                    summary=rollout_summary,
                    agent_brief_output=_observation_brief(observation),
                    event_offset=observation_event.offset,
                    refs={"observation_ref": observation["observation_id"], "action_request_ref": row["action_request"].request_id},
                    payload={"artifact_refs": _artifact_refs_from_observation(observation), "error": observation_error},
                )
            if observation_error:
                _record_task_step_summary(
                    runtime_host,
                    task_run_id=current_task.task_run_id,
                    step=f"task_tool_repair_required:{step_index}",
                    status="running",
                    summary="工具调用失败，正在根据失败原因调整处理路径。",
                    refs={"observation_ref": observation["observation_id"]},
                )
        runtime_host.event_log.append(
            current_task.task_run_id,
            "task_tool_batch_group_completed",
            payload={
                "task_run_id": current_task.task_run_id,
                "packet_ref": packet_ref,
                "tool_batch_ref": batch_plan.batch_id,
                "tool_batch_group": group.to_dict(),
                "observation_refs": completed_refs,
                "statuses": completed_statuses,
                "interrupted": isinstance(group_interrupt, TaskRunExecutorInterrupted),
            },
            refs={
                "task_run_ref": current_task.task_run_id,
                "runtime_invocation_packet_ref": packet_ref,
                "tool_batch_ref": batch_plan.batch_id,
                "tool_observation_refs": completed_refs,
                "group_event_ref": getattr(group_event, "event_id", ""),
            },
        )
        if isinstance(group_interrupt, TaskRunExecutorInterrupted):
            interrupted_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
            control_followup = _record_pending_runtime_control_signal_for_agent(
                runtime_host,
                current_task=interrupted_task,
                signal=group_interrupt.signal,
                packet_ref=packet_ref,
                boundary=f"tool_batch_execution:{step_index}",
                raw_observations=raw_observations,
                observations=observations,
                execution_state=execution_state,
                artifact_refs=artifact_refs,
                runtime_fingerprint=runtime_fingerprint,
                step_index=step_index,
                event_offset=group_event.offset,
            )
            if control_followup is not None:
                return control_followup
            return {
                "return_result": _pause_executor_for_model_recovery(
                    runtime_host,
                    task_run=interrupted_task,
                    agent_run=agent_run,
                    packet_ref=packet_ref,
                    step_index=step_index,
                    error=group_interrupt,
                )
            }
        current_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
        control_result = _apply_runtime_control_boundary(runtime_host, task_run=current_task, agent_run=agent_run, boundary=f"after_tool_batch_group:{step_index}")
        if control_result is not None:
            return {"return_result": control_result}
        control_followup = _record_pending_runtime_control_signal_for_agent(
            runtime_host,
            current_task=current_task,
            signal=None,
            packet_ref=packet_ref,
            boundary=f"after_tool_batch_group:{step_index}",
            raw_observations=raw_observations,
            observations=observations,
            execution_state=execution_state,
            artifact_refs=artifact_refs,
            runtime_fingerprint=runtime_fingerprint,
            step_index=step_index,
            event_offset=group_event.offset,
        )
        if control_followup is not None:
            return control_followup
        observation_context = _observations_for_packet(
            runtime_host,
            current_task.task_run_id,
            current_fingerprint=runtime_fingerprint,
            pending_observations=raw_observations,
        )
        raw_observations = list(observation_context["raw_observations"])
        observations = list(observation_context["packet_observations"])
        execution_state = dict(observation_context["execution_state"])
        artifact_refs = dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs])
    return {
        "current_task": current_task,
        "raw_observations": raw_observations,
        "observations": observations,
        "execution_state": execution_state,
        "artifact_refs": artifact_refs,
    }


def _record_duplicate_tool_call_guard_observation_for_tool_child(
    runtime_host: Any,
    *,
    current_task: Any,
    action_request: AnyModelActionRequest,
    observation: dict[str, Any],
    runtime_fingerprint: dict[str, Any],
    raw_observations: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    execution_state: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    packet_ref: str,
    step_index: int,
    event_offset: int | float = 0,
) -> dict[str, Any]:
    raw_observations.append(observation)
    runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
    duplicate_event = runtime_host.event_log.append(
        current_task.task_run_id,
        "task_duplicate_tool_call_guarded",
        payload={"observation": observation},
        refs={
            "task_run_ref": current_task.task_run_id,
            "action_request_ref": action_request.request_id,
            "observation_ref": observation["observation_id"],
            "runtime_invocation_packet_ref": packet_ref,
        },
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=current_task.task_run_id,
        step=f"task_duplicate_tool_call_guarded:{step_index}",
        status="running",
        summary="重复只读工具调用被拦截，已有观察将继续参与上下文。",
        refs={"observation_ref": observation["observation_id"], "action_request_ref": action_request.request_id},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=current_task,
        item_type="progress",
        title="重复工具调用已拦截",
        status="running",
        summary="重复只读工具调用被拦截，已有观察将继续参与上下文。",
        event_offset=event_offset or duplicate_event.offset,
        refs={"observation_ref": observation["observation_id"], "action_request_ref": action_request.request_id},
        payload={"model_visible": False},
    )
    observation_context = _observations_for_packet(
        runtime_host,
        current_task.task_run_id,
        current_fingerprint=runtime_fingerprint,
        pending_observations=raw_observations,
    )
    return {
        "current_task": runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task,
        "raw_observations": list(observation_context["raw_observations"]),
        "observations": list(observation_context["packet_observations"]),
        "execution_state": dict(observation_context["execution_state"]),
        "artifact_refs": dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs]),
    }


def _record_task_admission_observation(
    runtime_host: Any,
    *,
    current_task: Any,
    agent_run: Any,
    action_request: AnyModelActionRequest,
    admission: Any,
    runtime_fingerprint: dict[str, Any],
    raw_observations: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    execution_state: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    packet_ref: str,
    step_index: int,
    event_offset: int | float = 0,
) -> dict[str, Any]:
    previous_admission_denials = _matching_model_action_admission_denial_observations(
        raw_observations,
        action_request=action_request,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
    )
    admission_denial_count = len(previous_admission_denials) + 1
    pause_after_repeated_admission = admission_denial_count >= _REPEATED_ADMISSION_PAUSE_COUNT
    if admission_denial_count >= _REPEATED_ADMISSION_GUARD_COUNT:
        admission_observation = _model_action_admission_recovery_observation(
            task_run_id=current_task.task_run_id,
            packet_ref=packet_ref,
            action_request=action_request,
            admission=admission,
            runtime_fingerprint=runtime_fingerprint,
            step_index=step_index,
            repeat_count=admission_denial_count,
            previous_observations=previous_admission_denials,
            pause_after_observation=pause_after_repeated_admission,
        )
        admission_event_type = "task_repeated_model_action_admission_guarded"
        admission_step = f"repeated_model_action_admission_guarded:{step_index}"
        admission_summary = "模型重复请求同一个未获准动作，已返回恢复观察。"
        admission_title = "重复运行边界"
    else:
        admission_observation = _model_action_admission_recovery_observation(
            task_run_id=current_task.task_run_id,
            packet_ref=packet_ref,
            action_request=action_request,
            admission=admission,
            runtime_fingerprint=runtime_fingerprint,
            step_index=step_index,
        )
        admission_event_type = "task_model_action_admission_observation_recorded"
        admission_step = f"model_action_admission_observation:{step_index}"
        admission_summary = "运行边界拒绝了当前动作，正在根据边界观察继续推进。"
        admission_title = "运行边界"
    raw_observations.append(admission_observation)
    runtime_host.runtime_objects.put_object("observation", admission_observation["observation_id"], admission_observation)
    admission_refs = _admission_observation_refs(
        current_task=current_task,
        action_request=action_request,
        admission_observation=admission_observation,
        packet_ref=packet_ref,
    )
    runtime_host.event_log.append(
        current_task.task_run_id,
        admission_event_type,
        payload={
            "observation": admission_observation,
            "admission": admission.to_dict(),
            "repeat_count": admission_denial_count,
        },
        refs=admission_refs,
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=current_task.task_run_id,
        step=admission_step,
        status="running",
        summary=admission_summary,
        refs=_public_admission_observation_refs(admission_refs),
    )
    append_work_rollout_item(
        runtime_host,
        task_run=current_task,
        item_type="progress",
        title=admission_title,
        status="running",
        summary=admission_summary,
        event_offset=event_offset,
        refs=_public_admission_observation_refs(admission_refs),
        payload={"model_visible": False, "admission": admission.to_dict(), "repeat_count": admission_denial_count},
    )
    observation_context = _observations_for_packet(
        runtime_host,
        current_task.task_run_id,
        current_fingerprint=runtime_fingerprint,
        pending_observations=raw_observations,
    )
    result = {
        "current_task": runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task,
        "raw_observations": list(observation_context["raw_observations"]),
        "observations": list(observation_context["packet_observations"]),
        "execution_state": dict(observation_context["execution_state"]),
        "artifact_refs": dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs]),
    }
    if pause_after_repeated_admission:
        result["return_result"] = _pause_executor_for_repeated_admission_denial(
            runtime_host,
            task_run=current_task,
            agent_run=agent_run,
            action_request=action_request,
            admission=admission,
            observation=admission_observation,
            repeat_count=admission_denial_count,
        )
    return result


def _admission_observation_refs(
    *,
    current_task: Any,
    action_request: AnyModelActionRequest,
    admission_observation: dict[str, Any],
    packet_ref: str,
) -> dict[str, Any]:
    payload = dict(admission_observation.get("payload") or {})
    refs = {
        "task_run_ref": current_task.task_run_id,
        "action_request_ref": action_request.request_id,
        "observation_ref": admission_observation["observation_id"],
        "runtime_invocation_packet_ref": packet_ref,
    }
    action_lifecycle_ref = str(payload.get("action_lifecycle_ref") or "")
    if action_lifecycle_ref:
        refs["action_lifecycle_ref"] = action_lifecycle_ref
    return refs


def _public_admission_observation_refs(refs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(refs or {}).items()
        if key in {"observation_ref", "action_request_ref", "action_lifecycle_ref"}
    }


def _record_repeated_tool_failure_if_needed(
    runtime_host: Any,
    *,
    current_task: Any,
    agent_run: Any,
    action_request: AnyModelActionRequest,
    observation: dict[str, Any],
    packet_ref: str,
    raw_observations: list[dict[str, Any]],
    step_index: int,
) -> dict[str, Any]:
    fingerprint = _tool_failure_fingerprint(observation)
    if not fingerprint:
        return {}
    matching = [
        item
        for item in raw_observations
        if _tool_failure_fingerprint(item) == fingerprint
    ]
    repeat_count = len(matching)
    if repeat_count < _REPEATED_TOOL_FAILURE_OBSERVATION_COUNT:
        return {}
    guard_already_recorded = any(
        str(item.get("source") or "") == "system:repeated_tool_failure_guard"
        and str(dict(item.get("payload") or {}).get("failure_fingerprint") or "") == fingerprint
        for item in raw_observations
    )
    if not guard_already_recorded:
        guard_observation = _repeated_tool_failure_observation(
            task_run_id=current_task.task_run_id,
            packet_ref=packet_ref,
            action_request=action_request,
            observation=observation,
            failure_fingerprint=fingerprint,
            repeat_count=repeat_count,
            step_index=step_index,
            block_after_observation=repeat_count >= _REPEATED_TOOL_FAILURE_BLOCK_COUNT,
        )
        raw_observations.append(guard_observation)
        runtime_host.runtime_objects.put_object("observation", guard_observation["observation_id"], guard_observation)
        runtime_host.event_log.append(
            current_task.task_run_id,
            "task_repeated_tool_failure_guarded",
            payload={"observation": guard_observation, "repeat_count": repeat_count},
            refs={
                "task_run_ref": current_task.task_run_id,
                "action_request_ref": action_request.request_id,
                "observation_ref": guard_observation["observation_id"],
                "runtime_invocation_packet_ref": packet_ref,
            },
        )
        _record_task_step_summary(
            runtime_host,
            task_run_id=current_task.task_run_id,
            step=f"task_repeated_tool_failure_guarded:{step_index}",
            status="running",
            summary="同一工具失败已多次重复，正在要求改变策略。",
            refs={"observation_ref": guard_observation["observation_id"], "action_request_ref": action_request.request_id},
        )
    if repeat_count >= _REPEATED_TOOL_FAILURE_BLOCK_COUNT:
        return {
            "return_result": _finish_executor_blocked(
                runtime_host,
                task_run=current_task,
                agent_run=agent_run,
                terminal_reason="repeated_failure_limit_exceeded",
                payload={
                    "recoverable_error": {
                        "error_code": "repeated_failure_limit_exceeded",
                        "retryable": True,
                        "failure_fingerprint": fingerprint,
                        "repeat_count": repeat_count,
                        "user_message": "同一失败动作已经多次重复，需要改变工具、参数、策略或等待用户补充信息后继续。",
                    },
                    "recovery_action": "rerun_task_executor_after_strategy_change",
                    "action_request": action_request.to_dict(),
                },
            )
        }
    return {}


def _pending_runtime_control_signal_from_gateway(
    runtime_host: Any,
    *,
    task_run: Any,
    executor_epoch: int,
) -> ExecutorControlSignal | None:
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    drain = getattr(runtime_gateway, "drain", None)
    if not callable(drain):
        return None
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    if not task_run_id:
        return None
    try:
        snapshot = drain(
            task_run_id,
            scope=_runtime_signal_scope_for_task_run(task_run),
            signal_types={"control.signal.requested"},
        )
    except Exception:
        return None
    for envelope in tuple(getattr(snapshot, "pending_signals", ()) or ()):
        payload = dict(getattr(envelope, "payload", {}) or {})
        kind = str(payload.get("signal_kind") or "").strip()
        if kind not in {"pause", "stop", "replan"}:
            continue
        try:
            signal_epoch = int(payload.get("executor_epoch") or executor_epoch or 0)
        except (TypeError, ValueError):
            signal_epoch = int(executor_epoch or 0)
        return ExecutorControlSignal(
            kind=kind,  # type: ignore[arg-type]
            task_run_id=task_run_id,
            executor_epoch=signal_epoch,
            reason=str(payload.get("reason") or kind),
            requested_by=str(payload.get("requested_by") or "system"),
            requested_at=float(payload.get("requested_at") or getattr(envelope, "created_at", 0.0) or time.time()),
            steer_ref=str(payload.get("steer_ref") or ""),
            signal_id=str(getattr(envelope, "signal_id", "") or ""),
            control_event_ref=_runtime_signal_event_ref(runtime_host, task_run_id=task_run_id, signal_id=str(getattr(envelope, "signal_id", "") or "")),
        )
    return None


def _pending_runtime_control_signal_from_gateway_for_task_id(
    runtime_host: Any,
    *,
    task_run_id: str,
    executor_epoch: int,
) -> ExecutorControlSignal | None:
    task_run = getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(task_run_id)
    if task_run is None:
        return None
    return _pending_runtime_control_signal_from_gateway(
        runtime_host,
        task_run=task_run,
        executor_epoch=executor_epoch,
    )


def _runtime_signal_scope_for_task_run(task_run: Any) -> RuntimeSignalScope:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    scope_payload = dict(diagnostics.get("agent_run_scope") or {})
    return RuntimeSignalScope(
        session_id=str(getattr(task_run, "session_id", "") or scope_payload.get("session_id") or ""),
        task_run_id=str(getattr(task_run, "task_run_id", "") or scope_payload.get("task_run_id") or ""),
        agent_run_id=str(scope_payload.get("agent_run_id") or diagnostics.get("agent_run_id") or ""),
        run_cell_id=str(scope_payload.get("run_cell_id") or diagnostics.get("run_cell_id") or ""),
        turn_id=str(scope_payload.get("turn_id") or diagnostics.get("turn_id") or diagnostics.get("latest_interaction_turn_id") or ""),
        turn_run_id=str(scope_payload.get("turn_run_id") or diagnostics.get("turn_run_id") or ""),
    )


def _runtime_signal_event_ref(runtime_host: Any, *, task_run_id: str, signal_id: str) -> str:
    normalized_signal_id = str(signal_id or "").strip()
    if not normalized_signal_id:
        return ""
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    event_log = getattr(runtime_host, "event_log", None) or getattr(runtime_gateway, "event_log", None)
    list_events = getattr(event_log, "list_events", None)
    if not callable(list_events):
        return ""
    try:
        events = list_events(task_run_id)
    except Exception:
        return ""
    for event in events:
        signal = dict(dict(getattr(event, "payload", {}) or {}).get("signal") or {})
        if str(signal.get("signal_id") or "") == normalized_signal_id:
            return str(getattr(event, "event_id", "") or "")
    return ""


def _record_pending_runtime_control_signal_for_agent(
    runtime_host: Any,
    *,
    current_task: Any,
    signal: ExecutorControlSignal | None,
    packet_ref: str,
    boundary: str,
    raw_observations: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    execution_state: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    runtime_fingerprint: dict[str, Any],
    step_index: int,
    event_offset: int | float = 0,
) -> dict[str, Any] | None:
    latest_task = runtime_host.state_index.get_task_run(current_task.task_run_id) or current_task
    diagnostics = dict(getattr(latest_task, "diagnostics", {}) or {})
    executor_epoch = int(
        getattr(signal, "executor_epoch", 0)
        or diagnostics.get("executor_epoch")
        or 0
    )
    if signal is None:
        signal = peek_executor_signal(
            runtime_host,
            task_run_id=latest_task.task_run_id,
            executor_epoch=executor_epoch,
        )
    if signal is None:
        signal = _pending_runtime_control_signal_from_gateway(
            runtime_host,
            task_run=latest_task,
            executor_epoch=executor_epoch,
        )
    if signal is None:
        return None
    fingerprint = _runtime_control_signal_fingerprint(latest_task, signal=signal, runtime_host=runtime_host)
    if _runtime_control_signal_already_delivered(latest_task, signal=signal, fingerprint=fingerprint):
        clear_executor_signal(
            runtime_host,
            task_run_id=latest_task.task_run_id,
            executor_epoch=executor_epoch,
            signal=signal,
        )
        return None
    existing_observation = _matching_runtime_control_signal_observation(
        raw_observations,
        signal=signal,
        fingerprint=fingerprint,
    )
    if existing_observation is not None:
        observed_event = _mark_runtime_control_signal_gateway_observed(
            runtime_host,
            task_run=latest_task,
            signal=signal,
            observation=existing_observation,
            packet_ref=packet_ref,
            boundary=boundary,
            fingerprint=fingerprint,
        )
        if observed_event is None:
            return None
        updated_task = _mark_runtime_control_signal_delivered(
            runtime_host,
            latest_task,
            signal=signal,
            observation=existing_observation,
            fingerprint=fingerprint,
            boundary=boundary,
        )
        clear_executor_signal(
            runtime_host,
            task_run_id=latest_task.task_run_id,
            executor_epoch=executor_epoch,
            signal=signal,
        )
        observation_context = _observations_for_packet(
            runtime_host,
            updated_task.task_run_id,
            current_fingerprint=runtime_fingerprint,
            pending_observations=raw_observations,
        )
        return {
            "current_task": updated_task,
            "raw_observations": list(observation_context["raw_observations"]),
            "observations": list(observation_context["packet_observations"]),
            "execution_state": dict(observation_context["execution_state"]),
            "artifact_refs": dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs]),
            "recorded": False,
        }
    observation = _runtime_control_signal_observation(
        runtime_host=runtime_host,
        task_run=latest_task,
        signal=signal,
        packet_ref=packet_ref,
        boundary=boundary,
        step_index=step_index,
        fingerprint=fingerprint,
    )
    observed_event = _mark_runtime_control_signal_gateway_observed(
        runtime_host,
        task_run=latest_task,
        signal=signal,
        observation=observation,
        packet_ref=packet_ref,
        boundary=boundary,
        fingerprint=fingerprint,
    )
    if observed_event is None:
        return None
    raw_observations.append(observation)
    runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
    event = runtime_host.event_log.append(
        latest_task.task_run_id,
        "task_runtime_control_signal_observed",
        payload={"observation": observation, "control": _runtime_control_payload(latest_task, runtime_host=runtime_host)},
        refs={
            "task_run_ref": latest_task.task_run_id,
            "observation_ref": observation["observation_id"],
            "runtime_invocation_packet_ref": packet_ref,
        },
    )
    updated_task = _mark_runtime_control_signal_delivered(
        runtime_host,
        latest_task,
        signal=signal,
        observation=observation,
        fingerprint=fingerprint,
        boundary=boundary,
        event_offset=event.offset,
    )
    clear_executor_signal(
        runtime_host,
        task_run_id=latest_task.task_run_id,
        executor_epoch=executor_epoch,
        signal=signal,
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=latest_task.task_run_id,
        step=f"runtime_control_signal_observed:{step_index}",
        status="running",
        summary="已收到运行控制信号，并作为观察交给 agent 选择下一步。",
        refs={"observation_ref": observation["observation_id"]},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=updated_task,
        item_type="progress",
        title="控制信号",
        status="running",
        summary="已收到运行控制信号，并作为观察交给 agent 选择下一步。",
        event_offset=event_offset or event.offset,
        refs={"task_run_ref": latest_task.task_run_id, "observation_ref": observation["observation_id"]},
        payload={"model_visible": True, "runtime_control_signal": dict(observation.get("payload") or {})},
    )
    observation_context = _observations_for_packet(
        runtime_host,
        updated_task.task_run_id,
        current_fingerprint=runtime_fingerprint,
        pending_observations=raw_observations,
    )
    return {
        "current_task": updated_task,
        "raw_observations": list(observation_context["raw_observations"]),
        "observations": list(observation_context["packet_observations"]),
        "execution_state": dict(observation_context["execution_state"]),
        "artifact_refs": dedupe_artifact_refs([*list(observation_context["artifact_refs"]), *artifact_refs]),
        "recorded": True,
    }


def _runtime_control_signal_observation(
    *,
    runtime_host: Any | None = None,
    task_run: Any,
    signal: ExecutorControlSignal,
    packet_ref: str,
    boundary: str,
    step_index: int,
    fingerprint: str,
) -> dict[str, Any]:
    control = _runtime_control_payload(task_run, runtime_host=runtime_host)
    state = str(control.get("state") or "").strip()
    kind = str(signal.kind or "").strip()
    if kind == "stop":
        instruction = (
            "收到停止请求。这不是最终回复。你需要停止发起新的工具调用，基于已经观察到的事实选择 respond 或 block 收口；"
            "respond 时写清已完成事项、未完成事项、验证状态和停止原因。"
        )
        closeout_required = True
    elif kind == "pause":
        instruction = (
            "收到暂停请求。这不是最终回复。你需要停止发起新的工具调用，基于当前事实选择 respond 或 block 说明暂停断点、"
            "已完成事项、未完成事项和可恢复条件。"
        )
        closeout_required = True
    elif kind == "replan":
        instruction = (
            "收到重规划信号。这不是最终回复。你需要先吸收新的用户补充要求，判断是否修订计划、询问用户、阻塞，"
            "或在已有事实足够时收口；不要继续执行旧计划里的下一步。"
        )
        closeout_required = False
    else:
        instruction = (
            "收到运行控制信号。这不是最终回复。你需要先判断它对当前任务目标、工具使用和收口方式的影响，再选择下一步动作。"
        )
        closeout_required = False
    payload = {
        "signal_kind": kind,
        "runtime_control_state": state,
        "requested_by": str(control.get("requested_by") or signal.requested_by or "system"),
        "requested_at": float(control.get("requested_at") or signal.requested_at or time.time()),
        "reason": str(control.get("reason") or signal.reason or ""),
        "steer_ref": str(signal.steer_ref or ""),
        "runtime_control_signal_ref": str(getattr(signal, "signal_id", "") or ""),
        "runtime_control_event_ref": str(getattr(signal, "control_event_ref", "") or ""),
        "boundary": str(boundary or ""),
        "runtime_control_signal_fingerprint": fingerprint,
        "agent_closeout_required": bool(closeout_required),
        "allowed_agent_actions": ["respond", "ask_user", "block", "tool_call"],
        "tool_calls_allowed_after_signal": bool(kind == "replan"),
        "repair_instruction": instruction,
        "structured_signal": {
            "code": f"runtime_control_{kind or 'signal'}",
            "message": instruction,
            "origin": "runtime_control_boundary",
            "retryable": True,
        },
    }
    ref_raw = json.dumps(
        {
            "task_run_id": str(getattr(task_run, "task_run_id", "") or ""),
            "step_index": int(step_index or 0),
            "fingerprint": fingerprint,
            "boundary": str(boundary or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    ref_digest = hashlib.sha256(ref_raw.encode("utf-8")).hexdigest()[:12]
    return {
        "observation_id": f"rtobs:{task_run.task_run_id}:runtime-control:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run.task_run_id,
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "request_ref": f"runtime-control-signal:{task_run.task_run_id}:invocation:{step_index}:{ref_digest}",
        "directive_ref": packet_ref,
        "content_chars": len(instruction),
        "summary": instruction,
        "payload": payload,
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
    }


def _mark_runtime_control_signal_gateway_observed(
    runtime_host: Any,
    *,
    task_run: Any,
    signal: ExecutorControlSignal,
    observation: dict[str, Any],
    packet_ref: str,
    boundary: str,
    fingerprint: str,
) -> Any | None:
    signal_id = str(getattr(signal, "signal_id", "") or "").strip()
    if not signal_id:
        return None
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    marker = getattr(runtime_gateway, "mark_observed_by_id", None)
    if not callable(marker):
        return None
    try:
        return marker(
            str(getattr(task_run, "task_run_id", "") or signal.task_run_id or ""),
            signal_id=signal_id,
            observed_by="harness.loop.task_executor.runtime_control_boundary",
            payload={
                "observation_ref": str(observation.get("observation_id") or ""),
                "runtime_invocation_packet_ref": str(packet_ref or ""),
                "boundary": str(boundary or ""),
                "runtime_control_signal_fingerprint": fingerprint,
            },
            refs={
                "task_run_ref": str(getattr(task_run, "task_run_id", "") or signal.task_run_id or ""),
                "observation_ref": str(observation.get("observation_id") or ""),
                "runtime_invocation_packet_ref": str(packet_ref or ""),
            },
        )
    except Exception:
        return None


def _mark_runtime_control_signal_gateway_consumed(
    runtime_host: Any,
    *,
    task_run: Any,
    control_observation: dict[str, Any],
    lifecycle_status: str,
    terminal_reason: str,
    output_commit: dict[str, Any],
    lifecycle_event: Any,
) -> Any | None:
    observation_payload = dict(control_observation.get("payload") or {})
    signal_id = str(observation_payload.get("runtime_control_signal_ref") or "").strip()
    if not signal_id:
        return None
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    marker = getattr(runtime_gateway, "mark_consumed_by_id", None)
    if not callable(marker):
        return None
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    commit_payload = dict(output_commit or {})
    lifecycle_event_payload = dict(lifecycle_event or {}) if isinstance(lifecycle_event, dict) else {}
    lifecycle_event_ref = str(lifecycle_event_payload.get("event_id") or getattr(lifecycle_event, "event_id", "") or "")
    try:
        return marker(
            task_run_id,
            signal_id=signal_id,
            consumed_by="harness.loop.task_executor.agent_controlled_runtime_boundary",
            payload={
                "observation_ref": str(control_observation.get("observation_id") or ""),
                "lifecycle_status": str(lifecycle_status or ""),
                "terminal_reason": str(terminal_reason or ""),
                "output_commit_status": str(commit_payload.get("state") or commit_payload.get("status") or ""),
                "task_lifecycle_event_ref": lifecycle_event_ref,
                "task_lifecycle_event_offset": _event_offset(lifecycle_event),
            },
            refs={
                "task_run_ref": task_run_id,
                "observation_ref": str(control_observation.get("observation_id") or ""),
                "task_lifecycle_event_ref": lifecycle_event_ref,
                **(
                    {"session_output_commit_event_ref": str(commit_payload.get("event_id") or "")}
                    if commit_payload.get("event_id")
                    else {}
                ),
            },
        )
    except Exception:
        return None


def _runtime_control_signal_gateway_can_consume(
    runtime_host: Any,
    *,
    task_run: Any,
    control_observation: dict[str, Any],
) -> bool:
    payload = dict(control_observation.get("payload") or {})
    signal_id = str(payload.get("runtime_control_signal_ref") or "").strip()
    if not signal_id:
        return False
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    if not callable(getattr(runtime_gateway, "mark_consumed_by_id", None)):
        return False
    can_consume = getattr(runtime_gateway, "can_consume_by_id", None)
    if not callable(can_consume):
        return False
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    try:
        return bool(can_consume(task_run_id, signal_id=signal_id))
    except Exception:
        return False


def _mark_replan_control_signals_consumed_by_model_action(
    runtime_host: Any,
    *,
    task_run: Any,
    action_request: AnyModelActionRequest,
    observations: list[dict[str, Any]],
    consumed_steer_ids: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {"consumed_events": [], "required_steer_refs": [], "missing_steer_refs": []}
    consumed_steer_refs = {str(item or "").strip() for item in consumed_steer_ids if str(item or "").strip()}
    if not consumed_steer_refs:
        return result
    candidates: list[tuple[dict[str, Any], str, str]] = []
    required_refs: set[str] = set()
    for observation in list(observations or []):
        if str(observation.get("source") or "") != "system:runtime_control_signal":
            continue
        payload = dict(observation.get("payload") or {})
        if str(payload.get("signal_kind") or "") != "replan":
            continue
        steer_ref = str(payload.get("steer_ref") or "").strip()
        signal_id = str(payload.get("runtime_control_signal_ref") or "").strip()
        if not steer_ref or steer_ref not in consumed_steer_refs or not signal_id:
            continue
        required_refs.add(steer_ref)
        candidates.append((observation, steer_ref, signal_id))
    result["required_steer_refs"] = sorted(required_refs)
    if not candidates:
        return result
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    marker = getattr(runtime_gateway, "mark_consumed_by_id", None)
    can_consume = getattr(runtime_gateway, "can_consume_by_id", None)
    if not callable(marker) or not callable(can_consume):
        result["missing_steer_refs"] = sorted(required_refs)
        return result
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    consumed_events: list[Any] = []
    missing_refs: set[str] = set()
    for observation, steer_ref, signal_id in candidates:
        try:
            if not can_consume(task_run_id, signal_id=signal_id):
                missing_refs.add(steer_ref)
                continue
            event = marker(
                task_run_id,
                signal_id=signal_id,
                consumed_by="harness.loop.task_executor.model_action_replan_consumption",
                payload={
                    "observation_ref": str(observation.get("observation_id") or ""),
                    "action_request_ref": str(action_request.request_id or ""),
                    "signal_kind": "replan",
                    "steer_ref": steer_ref,
                    "lifecycle_status": str(getattr(task_run, "status", "") or "running"),
                    "terminal_reason": str(getattr(task_run, "terminal_reason", "") or ""),
                    "model_action_consumption": "consumed_steer_refs",
                },
                refs={
                    "task_run_ref": task_run_id,
                    "observation_ref": str(observation.get("observation_id") or ""),
                    "action_request_ref": str(action_request.request_id or ""),
                    "steer_ref": steer_ref,
                },
            )
        except Exception:
            event = None
        if event is not None:
            consumed_events.append(event)
        else:
            missing_refs.add(steer_ref)
    result["consumed_events"] = consumed_events
    result["missing_steer_refs"] = sorted(missing_refs)
    return result


def _runtime_control_signal_fingerprint(task_run: Any, *, signal: ExecutorControlSignal, runtime_host: Any | None = None) -> str:
    control = _runtime_control_payload(task_run, runtime_host=runtime_host)
    return "sha256:" + _stable_hash(
        {
            "task_run_id": str(getattr(task_run, "task_run_id", "") or signal.task_run_id or ""),
            "executor_epoch": int(signal.executor_epoch or 0),
            "kind": str(signal.kind or ""),
            "state": str(control.get("state") or ""),
            "requested_by": str(control.get("requested_by") or signal.requested_by or ""),
            "requested_at": float(control.get("requested_at") or signal.requested_at or 0.0),
            "reason": str(control.get("reason") or signal.reason or ""),
            "steer_ref": str(signal.steer_ref or ""),
        }
    )


def _runtime_control_signal_already_delivered(
    task_run: Any,
    *,
    signal: ExecutorControlSignal,
    fingerprint: str,
) -> bool:
    signal_ref = str(getattr(signal, "signal_id", "") or "").strip()
    if not signal_ref:
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = diagnostics.get(_TASK_RUN_CONTROL_KEY)
    if not isinstance(control, dict):
        return False
    return (
        str(control.get("runtime_control_signal_ref") or "").strip() == signal_ref
        and str(control.get("runtime_control_signal_fingerprint") or "") == fingerprint
        and str(control.get("runtime_control_signal_kind") or "") == str(signal.kind or "")
        and bool(str(control.get("runtime_control_signal_observation_ref") or "").strip())
    )


def _matching_runtime_control_signal_observation(
    observations: list[dict[str, Any]],
    *,
    signal: ExecutorControlSignal,
    fingerprint: str,
) -> dict[str, Any] | None:
    signal_id = str(getattr(signal, "signal_id", "") or "").strip()
    if not signal_id:
        return None
    for observation in list(observations or []):
        if str(observation.get("source") or "") != "system:runtime_control_signal":
            continue
        payload = dict(observation.get("payload") or {})
        if str(payload.get("runtime_control_signal_ref") or "").strip() != signal_id:
            continue
        if str(payload.get("runtime_control_signal_fingerprint") or "") == fingerprint:
            return dict(observation)
    return None


def _latest_agent_closeout_runtime_control_observation(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    for observation in reversed(list(observations or [])):
        if str(observation.get("source") or "") != "system:runtime_control_signal":
            continue
        payload = dict(observation.get("payload") or {})
        if bool(payload.get("agent_closeout_required") is True):
            return dict(observation)
    return None


def _mark_runtime_control_signal_delivered(
    runtime_host: Any,
    task_run: Any,
    *,
    signal: ExecutorControlSignal,
    observation: dict[str, Any],
    fingerprint: str,
    boundary: str,
    event_offset: int | float = 0,
) -> Any:
    now = float(observation.get("created_at") or time.time())
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = dict(diagnostics.get(_TASK_RUN_CONTROL_KEY) or {})
    signal_ref = str(getattr(signal, "signal_id", "") or "").strip()
    event_ref = str(getattr(signal, "control_event_ref", "") or "").strip()
    signal_state = {
        "pause": _TASK_RUN_PAUSE_REQUESTED,
        "replan": _TASK_RUN_REPLAN_REQUESTED,
        "stop": _TASK_RUN_STOP_REQUESTED,
    }.get(str(signal.kind or "").strip(), "")
    signal_control = {
        **control,
        "state": signal_state or str(control.get("state") or ""),
        **({"runtime_control_signal_ref": signal_ref} if signal_ref else {}),
        **({"runtime_control_event_ref": event_ref} if event_ref else {}),
    }
    visible_state = _visible_task_run_control_state(task_run, signal_control, runtime_host=runtime_host)
    if signal_ref or control or visible_state:
        control = {
            **signal_control,
            "state": visible_state,
            "requested_by": str(control.get("requested_by") or signal.requested_by or "system"),
            "requested_at": float(control.get("requested_at") or signal.requested_at or now),
            "reason": str(control.get("reason") or signal.reason or ""),
            "authority": "orchestration.task_run_control",
            "runtime_control_signal_kind": str(signal.kind or ""),
            "runtime_control_signal_fingerprint": fingerprint,
            "runtime_control_signal_observation_ref": str(observation.get("observation_id") or ""),
            "runtime_control_signal_requested_at": float(control.get("requested_at") or signal.requested_at or now),
            "runtime_control_signal_delivered_at": now,
            "runtime_control_signal_boundary": str(boundary or ""),
        }
        diagnostics[_TASK_RUN_CONTROL_KEY] = control
    diagnostics.update(
        {
            "latest_step": "runtime_control_signal_observed",
            "latest_step_status": "running",
            "latest_step_summary": "已收到运行控制信号，并作为观察交给 agent 选择下一步。",
            "latest_observation_ref": str(observation.get("observation_id") or ""),
        }
    )
    updated = replace(
        task_run,
        updated_at=now,
        latest_event_offset=int(event_offset or getattr(task_run, "latest_event_offset", 0) or 0),
        diagnostics=diagnostics,
    )
    runtime_host.state_index.upsert_task_run(updated)
    return updated


def _tool_failure_fingerprint(observation: dict[str, Any]) -> str:
    if not isinstance(observation, dict):
        return ""
    if _is_approval_request_observation(observation):
        return ""
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    status = _observation_status(observation)
    if (
        status not in {"failed", "denied", "canceled", "error"}
        and not observation.get("error")
        and not payload.get("error")
        and str(envelope.get("status") or "").strip() not in {"error", "failed", "denied", "canceled"}
    ):
        return ""
    tool_name = _observation_tool_name(observation)
    if not tool_name or tool_name in {"repeated_tool_failure_guard", "duplicate_tool_call_guard"}:
        return ""
    tool_args = _normalize_tool_call_args_for_fingerprint(tool_name, _observation_tool_args(observation))
    structured_error = _structured_error_from_observation(observation)
    error_code = str(
        structured_error.get("code")
        or payload.get("error_code")
        or envelope.get("error_code")
        or observation.get("error")
        or payload.get("error")
        or envelope.get("error")
        or envelope.get("status")
        or status
        or "tool_failure"
    ).strip()
    raw = json.dumps(
        {"tool_name": tool_name, "tool_args": tool_args, "error_code": error_code},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _repeated_tool_failure_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    action_request: AnyModelActionRequest,
    observation: dict[str, Any],
    failure_fingerprint: str,
    repeat_count: int,
    step_index: int,
    block_after_observation: bool,
) -> dict[str, Any]:
    tool_name = _observation_tool_name(observation)
    tool_args = _observation_tool_args(observation)
    summary = (
        "同一工具失败已经重复出现。你必须改变工具、参数、范围或策略；"
        "不要再次提交相同失败指纹。"
    )
    if block_after_observation:
        summary = f"{summary} 如果继续重复，任务将保持可恢复阻塞。"
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:repeated_tool_failure_guard",
        "request_ref": f"repeated-tool-failure:{task_run_id}:invocation:{step_index}:{failure_fingerprint}",
        "directive_ref": packet_ref,
        "content_chars": len(summary),
        "summary": summary,
        "payload": {
            "tool_name": "repeated_tool_failure_guard",
            "tool_args": {
                "rejected_tool_name": tool_name,
                "rejected_tool_args": _normalize_tool_call_args_for_fingerprint(tool_name, tool_args),
            },
            "error": "repeated_failure_limit_exceeded",
            "error_code": "repeated_failure_limit_exceeded",
            "failure_fingerprint": failure_fingerprint,
            "repeat_count": repeat_count,
            "action_request_ref": action_request.request_id,
            "structured_error": {
                "code": "repeated_failure_limit_exceeded",
                "message": summary,
                "retryable": True,
                "origin": "repeated_tool_failure_guard",
            },
        },
        "needs_model_followup": not block_after_observation,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "repeated_failure_limit_exceeded",
    }


async def _execute_task_tool_batch_group(
    group: ToolBatchGroup,
    *,
    invocation_rows: list[dict[str, Any]],
    runtime_host: Any,
    services: TaskExecutorServices,
    task_run: Any,
    packet_ref: str,
    runtime_assembly: Any,
    runtime_tool_plan: Any,
) -> dict[str, Any]:
    row_indexes: list[int] = []
    for raw_index in list(group.item_indexes or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(invocation_rows):
            row_indexes.append(index)
    if not row_indexes:
        return {"results": [], "interrupt": None}
    timeout_seconds = _task_tool_batch_group_timeout_seconds(runtime_assembly)
    if group.parallel and len(row_indexes) > 1:
        tasks = {
            asyncio.create_task(
                _execute_task_tool_call(
                    runtime_host,
                    services=services,
                    task_run=task_run,
                    packet_ref=packet_ref,
                    action_request=invocation_rows[index]["action_request"],
                    admission=invocation_rows[index]["admission"],
                    runtime_assembly=runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {}),
                    runtime_tool_plan=runtime_tool_plan,
                )
            ): index
            for index in row_indexes
        }
        done, pending = await asyncio.wait(tasks, timeout=timeout_seconds if timeout_seconds > 0 else None)
        if pending:
            for task in pending:
                task.cancel()
            await _drain_cancelled_task_tool_tasks(pending)
        results_by_index: dict[int, Any] = {}
        interrupt: TaskRunExecutorInterrupted | None = None
        for task in done:
            row_index = tasks[task]
            try:
                results_by_index[row_index] = task.result()
            except TaskRunExecutorInterrupted as exc:
                interrupt = interrupt or exc
            except BaseException as exc:
                results_by_index[row_index] = exc
        for task in pending:
            results_by_index[tasks[task]] = TimeoutError(f"task_tool_batch_group_timeout_after_{timeout_seconds:g}s")
        return {
            "results": [
                (
                    invocation_rows[row_index],
                    _task_observation_from_batch_result(
                        results_by_index.get(row_index),
                        runtime_host=runtime_host,
                        task_run=task_run,
                        packet_ref=packet_ref,
                        row=invocation_rows[row_index],
                    ),
                )
                for row_index in row_indexes
                if row_index in results_by_index
            ],
            "interrupt": interrupt,
        }
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    interrupt: TaskRunExecutorInterrupted | None = None
    for row_index in row_indexes:
        row = invocation_rows[row_index]
        try:
            invocation = _execute_task_tool_call(
                runtime_host,
                services=services,
                task_run=task_run,
                packet_ref=packet_ref,
                action_request=row["action_request"],
                admission=row["admission"],
                runtime_assembly=runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {}),
                runtime_tool_plan=runtime_tool_plan,
            )
            if timeout_seconds > 0:
                result = await asyncio.wait_for(invocation, timeout=timeout_seconds)
            else:
                result = await invocation
        except TaskRunExecutorInterrupted as exc:
            interrupt = exc
            break
        except asyncio.TimeoutError:
            result = TimeoutError(f"task_tool_batch_group_timeout_after_{timeout_seconds:g}s")
        except BaseException as exc:
            result = exc
        results.append((row, _task_observation_from_batch_result(result, runtime_host=runtime_host, task_run=task_run, packet_ref=packet_ref, row=row)))
    return {"results": results, "interrupt": interrupt}


def _task_observation_from_batch_result(result: Any, *, runtime_host: Any, task_run: Any, packet_ref: str, row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    error = result if isinstance(result, BaseException) else RuntimeError("task_tool_batch_invalid_observation")
    action_request = row["action_request"]
    tool_call = dict(getattr(action_request, "tool_call", {}) or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    tool_args = _runtime_bound_tool_args(tool_name, tool_args, task_run=task_run)
    tool_call_id = _canonical_tool_call_id(action_request)
    action_lifecycle_ref = str(dict(row.get("action_lifecycle") or {}).get("lifecycle_id") or f"action-lifecycle:{action_request.request_id}")
    identity = None
    try:
        identity = _task_action_tool_invocation_identity(
            runtime_host,
            task_run=task_run,
            action_request=action_request,
            admission=row.get("admission"),
            action_permit=dict(row.get("action_permit") or {}),
            action_lifecycle_ref=action_lifecycle_ref,
            tool_args_override=tool_args,
        )
    except ValueError:
        identity = None
    return _executor_error_observation(
        task_run_id=task_run.task_run_id,
        request_ref=action_request.request_id,
        directive_ref=packet_ref,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_call_id=tool_call_id,
        admission_ref=str(getattr(identity, "admission_ref", "") or permission_decision_id(row.get("admission"), tool_call_id=tool_call_id)),
        action_lifecycle_ref=action_lifecycle_ref,
        identity=identity,
        action_request=action_request,
        error=str(error),
    )


def _task_tool_batch_group_timeout_seconds(runtime_assembly: Any) -> float:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    environment = dict(assembly_payload.get("task_environment") or {})
    execution_policy = dict(environment.get("execution_policy") or {})
    for candidate in (
        execution_policy.get("tool_batch_timeout_seconds"),
        environment.get("tool_batch_timeout_seconds"),
        dict(assembly_payload.get("diagnostics") or {}).get("tool_batch_timeout_seconds"),
    ):
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return max(1.0, value)
    return _DEFAULT_TASK_TOOL_BATCH_TIMEOUT_SECONDS


async def _drain_cancelled_task_tool_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    if not tasks:
        return
    done, still_pending = await asyncio.wait(tasks, timeout=_TASK_TOOL_BATCH_CANCEL_DRAIN_SECONDS)
    for task in done:
        _consume_task_tool_task_result(task)
    for task in still_pending:
        task.add_done_callback(_consume_task_tool_task_result)


def _consume_task_tool_task_result(task: asyncio.Task[Any]) -> None:
    try:
        task.exception()
    except BaseException:
        return


def _task_tool_child_action_requests(action_request: AnyModelActionRequest) -> list[TaskExecutionModelActionRequest]:
    raw_calls = list(getattr(action_request, "tool_calls", ()) or ())
    if not raw_calls and getattr(action_request, "tool_call", None):
        raw_calls = [dict(getattr(action_request, "tool_call", {}) or {})]
    result: list[TaskExecutionModelActionRequest] = []
    for index, raw_call in enumerate(raw_calls):
        tool_call = dict(raw_call or {})
        tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
        child_request_id = action_request.request_id if len(raw_calls) == 1 else f"{action_request.request_id}:tool:{index + 1}"
        tool_call_id = str(tool_call.get("id") or tool_call.get("tool_call_id") or "").strip()
        if not tool_call_id:
            raise TaskToolChildActionProtocolError("task_tool_call_id_required")
        tool_call = {
            **tool_call,
            "id": tool_call_id,
            "tool_name": tool_name,
            "name": tool_name,
            "args": tool_args,
        }
        result.append(
            TaskExecutionModelActionRequest(
                request_id=child_request_id,
                turn_id=action_request.turn_id,
                action_type="tool_call",
                public_progress_note=action_request.public_progress_note,
                public_action_state=dict(action_request.public_action_state or {}),
                tool_call=tool_call,
                tool_calls=(tool_call,),
                diagnostics={
                    **dict(action_request.diagnostics or {}),
                    "batch_action_request_ref": action_request.request_id,
                    "batch_tool_index": index,
                },
            )
        )
    return result


def _canonical_tool_call_id(action_request: AnyModelActionRequest) -> str:
    return canonical_action_tool_call_id(action_request)


def _task_action_tool_invocation_identity(
    runtime_host: Any,
    *,
    task_run: Any,
    action_request: AnyModelActionRequest,
    admission: Any,
    action_permit: Any,
    action_lifecycle_ref: str = "",
    tool_args_override: dict[str, Any] | None = None,
    agent_run: Any | None = None,
):
    agent_scope = _agent_run_scope_payload(task_run)
    scoped_agent_run_id = str(agent_scope.get("agent_run_id") or getattr(agent_run, "agent_run_id", "") or "")
    scoped_run_cell_id = str(agent_scope.get("run_cell_id") or "")
    return build_action_tool_invocation_identity(
        action_request,
        caller_ref=task_run.task_run_id,
        definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
        admission=admission,
        action_permit=action_permit,
        action_lifecycle_ref=action_lifecycle_ref,
        tool_args_override=tool_args_override,
        agent_run_id=scoped_agent_run_id,
        run_cell_id=scoped_run_cell_id,
    )


def _task_batch_workspace_root(runtime_assembly: Any, *, runtime_host: Any | None = None) -> str:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    for candidate in (
        dict(payload.get("sandbox_policy") or {}).get("workspace_root"),
        dict(payload.get("execution_context") or {}).get("workspace_root"),
        dict(payload.get("task_environment") or {}).get("workspace_root"),
        getattr(runtime_host, "workspace_root", "") if runtime_host is not None else "",
        getattr(runtime_host, "base_dir", "") if runtime_host is not None else "",
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


async def _invoke_task_model_action(
    *,
    model_runtime: Any,
    packet: Any,
    task_run_id: str,
    session_id: str,
    invocation_index: int,
    model_selection: dict[str, Any],
    executor_epoch: int = 0,
) -> tuple[AnyModelActionRequest | None, dict[str, Any]]:
    from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response

    invoker = getattr(model_runtime, "invoke_messages", None)
    stream_policy = dict(dict(model_selection or {}).get("stream_policy") or {})
    streamer = getattr(model_runtime, "astream_messages", None)
    stream_enabled = bool(stream_policy.get("enabled") is True)
    if not callable(invoker) and not (stream_enabled and callable(streamer)):
        return None, {"status": "invalid", "validation_errors": ["model_runtime_unavailable"]}
    effective_model_selection = _model_selection_with_json_object_contract(model_selection)
    timeout_seconds = model_action_timeout_seconds(model_runtime, model_selection=effective_model_selection)
    accounting_context = {
        "request_id": f"modelreq:{packet.packet_id}:{invocation_index}",
        "session_id": session_id,
        "task_run_id": task_run_id,
        "turn_id": task_run_id,
        "packet_ref": str(packet.packet_id or ""),
        "invocation_index": invocation_index,
        "source": "harness.loop.task_executor.model_action",
        "segment_plan": dict(getattr(packet, "segment_plan", {}) or {}),
        "prompt_manifest": dict(dict(getattr(packet, "diagnostics", {}) or {}).get("prompt_manifest") or {}),
    }
    response = await asyncio.wait_for(
        _invoke_task_model_action_response(
            invoker=invoker,
            streamer=streamer,
            messages=list(packet.model_messages),
            model_selection=effective_model_selection,
            accounting_context=accounting_context,
        ),
        timeout=timeout_seconds,
    )
    protocol_result = model_response_protocol_from_response(
        response,
        request_id=f"modelreq:{packet.packet_id}:{invocation_index}",
        turn_id=task_run_id,
        require_json_action=True,
        allow_native_tool_calls=False,
    )
    payload = dict(protocol_result.json_payload or {})
    payload.setdefault(
        "request_id",
        next_model_action_request_id(
            task_run_id=task_run_id,
            executor_epoch=executor_epoch,
            invocation_index=invocation_index,
            suffix=protocol_result.response_digest[:12],
        ),
    )
    action_request, protocol = task_execution_action_request_from_payload(
        payload,
        turn_id=task_run_id,
        require_public_progress_note=True,
        require_public_action_state=True,
        public_response_required=False,
        allowed_action_types=tuple(getattr(packet, "allowed_action_types", ()) or ()),
    )
    if action_request is None:
        protocol = {
            **dict(protocol or {}),
            "parse_diagnostics": dict(protocol_result.parse_diagnostics),
            "response_diagnostics": {
                **dict(protocol_result.response_diagnostics),
                **_model_action_response_diagnostics(response, model_selection=effective_model_selection),
            },
            "model_response_protocol": protocol_result.to_dict(),
        }
    else:
        protocol = {
            **dict(protocol or {}),
            "model_response_protocol": protocol_result.to_dict(),
        }
    return action_request, protocol


async def _invoke_task_model_action_response(
    *,
    invoker: Any,
    streamer: Any,
    messages: list[Any],
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any],
) -> Any:
    stream_policy = dict(dict(model_selection or {}).get("stream_policy") or {})
    stream_enabled = bool(stream_policy.get("enabled") is True)
    if stream_enabled and callable(streamer):
        try:
            return await _collect_task_model_stream_response(
                streamer,
                messages,
                model_selection=model_selection,
                accounting_context=accounting_context,
            )
        except Exception as exc:
            raise TaskModelActionStreamProtocolError(
                stream_error=exc,
                model_selection=model_selection,
            ) from exc
    if not callable(invoker):
        raise RuntimeError("model_runtime.invoke_messages is unavailable")
    return await call_model_invoker(
        invoker,
        messages,
        model_selection=model_selection,
        accounting_context=accounting_context,
    )


async def _collect_task_model_stream_response(
    streamer: Any,
    messages: list[Any],
    *,
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any],
) -> Any:
    stream = call_model_streamer(
        streamer,
        messages,
        model_selection=model_selection,
        accounting_context=accounting_context,
    )
    if inspect.isawaitable(stream):
        stream = await stream
    aggregated_response: Any = None
    raw_content = ""
    async for chunk in stream:
        aggregated_response = _merge_task_model_stream_chunk(aggregated_response, chunk)
        raw_content += _task_model_stream_chunk_text(chunk)
    return aggregated_response if aggregated_response is not None else raw_content


def _merge_task_model_stream_chunk(current: Any, chunk: Any) -> Any:
    if current is None:
        return chunk
    try:
        return current + chunk
    except Exception:
        current_text = _task_model_stream_chunk_text(current)
        chunk_text = _task_model_stream_chunk_text(chunk)
        return SimpleNamespace(content=current_text + chunk_text)


def _task_model_stream_chunk_text(chunk: Any) -> str:
    from runtime.model_gateway.model_runtime import stringify_content

    return stringify_content(getattr(chunk, "content", chunk))


def _model_selection_with_json_object_contract(model_selection: dict[str, Any]) -> dict[str, Any]:
    selection = dict(model_selection or {})
    selection = _model_selection_with_action_budget(selection)
    selection.setdefault("structured_output", "json_object")
    selection.setdefault("response_format", {"type": "json_object"})
    return normalize_model_selection_for_invocation(selection)


def _model_selection_with_action_budget(model_selection: dict[str, Any]) -> dict[str, Any]:
    selection = dict(model_selection or {})
    mappings = {
        "action_max_output_tokens": "max_output_tokens",
        "action_timeout_seconds": "timeout_seconds",
        "action_long_output_timeout_seconds": "long_output_timeout_seconds",
        "action_thinking_mode": "thinking_mode",
        "action_reasoning_effort": "reasoning_effort",
    }
    for action_key, provider_key in mappings.items():
        value = selection.pop(action_key, None)
        if value not in (None, "", {}, []):
            selection[provider_key] = value
    return selection


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
) -> tuple[AnyModelActionRequest | None, dict[str, Any]]:
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
    public_feedback_count = 0
    started_at = time.monotonic()
    last_progress_at = time.monotonic()
    last_public_feedback_at = 0.0
    try:
        while not task.done():
            signal = peek_executor_signal(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
            if signal is None:
                signal = _pending_runtime_control_signal_from_gateway_for_task_id(
                    runtime_host,
                    task_run_id=task_run_id,
                    executor_epoch=executor_epoch,
                )
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
            public_feedback_due = (
                public_feedback_count == 0
                and now - started_at >= _TASK_MODEL_THINKING_FEEDBACK_FIRST_DELAY_SECONDS
            ) or (
                public_feedback_count > 0
                and now - last_public_feedback_at >= _TASK_MODEL_THINKING_FEEDBACK_INTERVAL_SECONDS
            )
            if public_feedback_due and public_feedback_count < 3:
                public_feedback_count += 1
                last_public_feedback_at = now
                _record_task_model_thinking_public_feedback(
                    runtime_host,
                    task_run_id=task_run_id,
                    step_index=step_index,
                    wait_round=public_feedback_count,
                    refs={"runtime_invocation_packet_ref": packet_ref},
                )
            if now - last_progress_at >= _TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS:
                wait_round += 1
                last_progress_at = now
                _record_task_model_wait_heartbeat(
                    runtime_host,
                    task_run_id=task_run_id,
                    step=f"task_model_action_waiting:{step_index}",
                    wait_round=wait_round,
                    refs={"runtime_invocation_packet_ref": packet_ref},
                )
        signal = peek_executor_signal(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
        if signal is None:
            signal = _pending_runtime_control_signal_from_gateway_for_task_id(
                runtime_host,
                task_run_id=task_run_id,
                executor_epoch=executor_epoch,
            )
        if signal is not None:
            raise TaskRunExecutorInterrupted(signal)
        return await task
    except asyncio.CancelledError:
        signal = peek_executor_signal(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
        if signal is None:
            signal = _pending_runtime_control_signal_from_gateway_for_task_id(
                runtime_host,
                task_run_id=task_run_id,
                executor_epoch=executor_epoch,
            )
        if signal is not None:
            raise TaskRunExecutorInterrupted(signal) from None
        raise
    finally:
        clear_model_task(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch, model_task=task)


def _record_task_tool_item_started(
    runtime_host: Any,
    *,
    task_run: Any,
    identity: Any,
    packet_ref: str,
) -> Any:
    tool_args = dict(getattr(identity, "tool_args", {}) or {})
    turn_id = str(dict(getattr(task_run, "diagnostics", {}) or {}).get("turn_id") or getattr(task_run, "task_id", "") or "")
    record = build_tool_lifecycle_started_event_record(
        identity,
        run_id=task_run.task_run_id,
        caller_kind="task_run",
        session_id=str(getattr(task_run, "session_id", "") or ""),
        turn_id=turn_id,
        task_run_id=task_run.task_run_id,
        packet_ref=packet_ref,
        target=_tool_target_preview(tool_args),
        arguments_preview=_tool_arguments_preview(tool_args),
    )
    event = runtime_host.event_log.append(
        record.run_id,
        record.event_type,
        payload=record.payload,
        refs=record.refs,
    )
    current = runtime_host.state_index.get_task_run(task_run.task_run_id) or task_run
    runtime_host.state_index.upsert_task_run(
        replace(
            current,
            updated_at=event.created_at or time.time(),
            latest_event_offset=event.offset,
        )
    )
    return event


async def _execute_task_tool_call(
    runtime_host: Any,
    *,
    services: TaskExecutorServices,
    task_run: Any,
    packet_ref: str,
    action_request: AnyModelActionRequest,
    admission: Any,
    runtime_assembly: dict[str, Any],
    runtime_tool_plan: Any,
) -> dict[str, Any]:
    executor_epoch = int(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_epoch") or 0)
    signal = peek_executor_signal(runtime_host, task_run_id=task_run.task_run_id, executor_epoch=executor_epoch)
    if signal is not None:
        raise TaskRunExecutorInterrupted(signal)
    latest_task_run = runtime_host.state_index.get_task_run(task_run.task_run_id) or task_run
    signal = _pending_runtime_control_signal_from_gateway(
        runtime_host,
        task_run=latest_task_run,
        executor_epoch=executor_epoch,
    )
    if signal is not None:
        raise TaskRunExecutorInterrupted(signal)
    control_result = _apply_runtime_control_boundary(runtime_host, task_run=latest_task_run, agent_run=None, boundary="before_tool_execution")
    if control_result is not None:
        task_after_boundary = runtime_host.state_index.get_task_run(task_run.task_run_id) or latest_task_run
        signal = _executor_control_signal_from_boundary_result(
            control_result,
            task_run=task_after_boundary,
            executor_epoch=executor_epoch,
        )
        raise TaskRunExecutorInterrupted(signal)
    task_run = runtime_host.state_index.get_task_run(task_run.task_run_id) or latest_task_run
    tool_name = str(action_request.tool_call.get("tool_name") or action_request.tool_call.get("name") or "").strip()
    tool_call_id = _canonical_tool_call_id(action_request)
    tool_args = dict(action_request.tool_call.get("args") or action_request.tool_call.get("tool_args") or {})
    tool_args = _runtime_bound_tool_args(tool_name, tool_args, task_run=task_run)
    definition = getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}).get(tool_name)
    operation_id = str(getattr(definition, "operation_id", "") or tool_name)
    tool_turn_id = str(dict(getattr(task_run, "diagnostics", {}) or {}).get("turn_id") or task_run.task_id or "")
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run.task_run_id)
    file_policy = _task_file_policy(runtime_assembly, sandbox_policy=sandbox_policy)
    runtime_permission_mode = _task_runtime_permission_mode(
        task_run,
        runtime_host=runtime_host,
        runtime_assembly=runtime_assembly,
    )
    sandbox_policy = {
        **sandbox_policy,
        "session_id": task_run.session_id,
        "executor_epoch": int(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_epoch") or 0),
        **_task_runtime_scope_policy(task_run),
    }
    approval_risk_fingerprint = build_approval_risk_fingerprint(
        operation_id=operation_id,
        tool_name=tool_name,
        tool_args=tool_args,
        sandbox_policy=sandbox_policy,
        file_management_policy=file_policy,
    )
    agent_run = _ensure_executor_agent_run(runtime_host, task_run=task_run)
    lifecycle = build_action_lifecycle_from_admission(
        action_request,
        admission,
        invocation_kind="task_execution",
        permit_invocation_kind="task_execution",
        packet_ref=packet_ref,
        packet_allowed_action_types=("respond", "ask_user", "tool_call", "block"),
        allowed_tool_names=set(getattr(runtime_tool_plan, "dispatchable_tool_names", ()) or ()),
        permission_mode=runtime_permission_mode,
        side_effect_policy="runtime_authorized",
        session_id=task_run.session_id,
        turn_id=tool_turn_id,
        task_run_id=task_run.task_run_id,
        grant_scope="task_run",
        resource_scope={"approval_risk_fingerprint": approval_risk_fingerprint},
    )
    action_permit = lifecycle.action_permit
    identity = _task_action_tool_invocation_identity(
        runtime_host,
        task_run=task_run,
        action_request=action_request,
        admission=admission,
        action_permit=action_permit,
        action_lifecycle_ref=lifecycle.lifecycle_id,
        tool_args_override=tool_args,
        agent_run=agent_run,
    )
    scoped_agent_run_id = identity.agent_run_id
    scoped_run_cell_id = identity.run_cell_id
    tool_name = identity.tool_name
    tool_call_id = identity.tool_call_id
    tool_args = identity.tool_args
    operation_id = identity.operation_id
    invocation_id = identity.invocation_id
    request = ToolInvocationRequest(
        invocation_id=invocation_id,
        caller_kind="task_run",
        caller_ref=task_run.task_run_id,
        session_id=task_run.session_id,
        turn_id=tool_turn_id,
        task_run_id=task_run.task_run_id,
        agent_run_id=scoped_agent_run_id,
        run_cell_id=scoped_run_cell_id,
        action_request_ref=action_request.request_id,
        packet_ref=packet_ref,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args,
        operation_id=operation_id,
        tool_plan_ref=str(getattr(runtime_tool_plan, "plan_id", "") or ""),
        admission_ref=identity.admission_ref,
        action_permit=identity.action_permit,
        permission_mode=runtime_permission_mode,
        caller_resource_scope={
            "task_id": task_run.task_id,
            "step_id": f"task-step:{action_request.request_id}",
            "plan_ref": f"orchplan:{task_run.task_run_id}:single-agent-task",
            "stage_ref": f"orchstage:{task_run.task_run_id}:step",
            "execution_graph_ref": f"execgraph:{task_run.task_run_id}:single-agent-task",
            "resource_policy_ref": f"respol:{task_run.task_run_id}:tool:{action_request.request_id}",
        },
        sandbox_scope=sandbox_policy,
        file_scope=file_policy,
        file_evidence_scope=task_run_file_evidence_scope(task_run.task_run_id, session_id=task_run.session_id),
        approval_state=approval_state_for_task_run(task_run).to_dict(),
        approval_risk_fingerprint=approval_risk_fingerprint,
        requested_constraints={
            "runtime_host": runtime_host,
            "services": services,
            "runtime_assembly": runtime_assembly,
            "backend_dir": str(runtime_host.backend_dir),
        },
    )
    _record_task_tool_item_started(
        runtime_host,
        task_run=task_run,
        identity=identity,
        packet_ref=packet_ref,
    )
    tool_control_plane = getattr(services, "tool_control_plane", None) or getattr(runtime_host, "tool_control_plane", None)
    if tool_control_plane is None:
        return _executor_error_observation(
            task_run_id=task_run.task_run_id,
            request_ref=action_request.request_id,
            directive_ref=f"runtime-directive:{task_run.task_run_id}:tool:{action_request.request_id}",
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            admission_ref=identity.admission_ref,
            action_lifecycle_ref=identity.action_lifecycle_ref,
            identity=identity,
            action_request=action_request,
            error="runtime_tool_control_plane_unavailable",
        )
    observation_result = await tool_control_plane.invoke(request, tool_plan=runtime_tool_plan)
    observation = observation_result.to_task_observation(
        task_run_id=task_run.task_run_id,
        request_ref=action_request.request_id,
        directive_ref=f"runtime-directive:{task_run.task_run_id}:tool:{action_request.request_id}",
    )
    observation["tool_call_id"] = tool_call_id
    observation.setdefault("payload", {})
    if isinstance(observation.get("payload"), dict):
        payload = observation["payload"]
        payload.setdefault("tool_call_id", tool_call_id)
        payload["runtime_fingerprint"] = _current_runtime_fingerprint(
            runtime_assembly,
            permission_mode=_task_runtime_permission_mode(
                task_run,
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly,
            ),
            backend_config=services.backend_config,
        )
        payload.setdefault("tool_name", tool_name)
        payload.setdefault("tool_args", tool_args)
        if observation_result.status != "ok":
            error = observation_result.text or observation_result.status
            payload.setdefault("error", error)
            observation["error"] = error
    return observation


def _load_contract(runtime_host: Any, task_run: Any) -> dict[str, Any]:
    try:
        contract = runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    except Exception:
        contract = {}
    if contract:
        return dict(contract)
    return dict(dict(task_run.diagnostics or {}).get("contract") or {})


def _publish_packet_evidence_projection_event(
    runtime_host: Any,
    *,
    run_id: str,
    packet_context: dict[str, Any],
    refs: dict[str, Any] | None = None,
) -> Any | None:
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    publisher = getattr(runtime_gateway, "publish_evidence_projection", None)
    if not callable(publisher) or not packet_context:
        return None
    projection_ref = runtime_packet_evidence_projection_ref(packet_context)
    payload = runtime_packet_evidence_projection_event_payload(packet_context)
    scope = runtime_packet_evidence_signal_scope(packet_context)
    try:
        return publisher(
            run_id,
            projection_ref=projection_ref,
            scope=scope,
            payload=payload,
            refs={
                **dict(refs or {}),
                "session_ref": str(packet_context.get("session_id") or ""),
                "task_run_ref": str(packet_context.get("task_run_id") or ""),
                "runtime_invocation_packet_ref": str(packet_context.get("packet_id") or ""),
            },
        )
    except Exception:
        return None


def _task_runtime_permission_mode(
    task_run: Any,
    *,
    runtime_host: Any | None = None,
    runtime_assembly: dict[str, Any] | None = None,
) -> str:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    candidates = [
        diagnostics.get("runtime_permission_mode"),
        diagnostics.get("permission_mode"),
    ]
    assembly = dict(runtime_assembly or diagnostics.get("runtime_assembly") or {})
    if assembly:
        candidates.append(assembly.get("permission_mode"))
    contract = dict(diagnostics.get("contract") or {})
    if contract:
        permission_requirements = dict(contract.get("permission_requirements") or {})
        candidates.extend([
            contract.get("runtime_permission_mode"),
            permission_requirements.get("permission_mode"),
        ])
    if runtime_host is not None and hasattr(runtime_host, "_current_permission_mode"):
        candidates.append(runtime_host._current_permission_mode())
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return normalize_permission_mode(text)
    return "full_access"


def _runtime_contract_from_task_run(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(task_run.diagnostics or {})
    original = dict(diagnostics.get("runtime_contract") or {})
    runtime_profile = dict(original.get("runtime_profile") or {})
    return {
        **original,
        "runtime_profile": runtime_profile,
    }


def _task_model_selection(task_run: Any, *, agent_profile: Any | None = None) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    selection = diagnostics.get("model_selection")
    if isinstance(selection, dict) and selection:
        return normalize_model_selection_for_invocation(
            _model_selection_with_runtime_requirement(dict(selection), diagnostics=diagnostics)
        )
    runtime_contract = dict(diagnostics.get("runtime_contract") or {})
    runtime_profile = dict(runtime_contract.get("runtime_profile") or {})
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
        "credential_ref": str(requirement.get("credential_ref") or profile_payload.get("credential_ref") or "").strip(),
        "max_output_tokens": requirement.get("max_output_tokens") or requirement.get("preferred_output_tokens") or profile_payload.get("max_output_tokens"),
        "timeout_seconds": profile_payload.get("timeout_seconds"),
        "long_output_timeout_seconds": profile_payload.get("long_output_timeout_seconds"),
        "max_retries": profile_payload.get("max_retries"),
        "temperature": profile_payload.get("temperature"),
        "thinking_mode": str(requirement.get("thinking_mode") or profile_payload.get("thinking_mode") or "").strip(),
        "reasoning_effort": str(requirement.get("reasoning_effort") or profile_payload.get("reasoning_effort") or "").strip(),
        "action_max_output_tokens": requirement.get("action_max_output_tokens") or profile_payload.get("action_max_output_tokens"),
        "action_timeout_seconds": requirement.get("action_timeout_seconds") or profile_payload.get("action_timeout_seconds"),
        "action_long_output_timeout_seconds": requirement.get("action_long_output_timeout_seconds") or profile_payload.get("action_long_output_timeout_seconds"),
        "action_thinking_mode": str(requirement.get("action_thinking_mode") or profile_payload.get("action_thinking_mode") or "").strip(),
        "action_reasoning_effort": str(requirement.get("action_reasoning_effort") or profile_payload.get("action_reasoning_effort") or "").strip(),
        "response_format": dict(requirement.get("response_format") or profile_payload.get("response_format") or {}),
        "structured_output": str(requirement.get("structured_output") or "").strip().lower(),
        "stream_policy": _stream_policy_for_task_model_requirement(
            profile_payload.get("stream_policy"),
            requirement=requirement,
        ),
        "completion_profile": dict(runtime_profile.get("completion_profile") or {}),
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


def _runtime_bound_tool_args(tool_name: str, tool_args: dict[str, Any], *, task_run: Any) -> dict[str, Any]:
    args = dict(tool_args or {})
    if str(tool_name or "").strip() != "agent_todo":
        return args
    session_id = str(args.get("session_id") or "").strip()
    task_id = str(args.get("task_id") or "").strip()
    if not session_id or session_id == "default":
        args["session_id"] = str(getattr(task_run, "session_id", "") or "default")
    if not task_id or task_id in {"runtime", "default"}:
        args["task_id"] = str(getattr(task_run, "task_run_id", "") or getattr(task_run, "task_id", "") or "runtime")
    return args


def _model_selection_with_runtime_requirement(
    model_selection: dict[str, Any],
    *,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    runtime_contract = dict(diagnostics.get("runtime_contract") or {})
    runtime_profile = dict(runtime_contract.get("runtime_profile") or {})
    requirement = dict(runtime_profile.get("model_requirement") or {})
    if not requirement:
        return dict(model_selection or {})
    selection = dict(model_selection or {})
    stream_policy = _stream_policy_for_task_model_requirement(
        selection.get("stream_policy"),
        requirement=requirement,
    )
    if stream_policy:
        selection["stream_policy"] = stream_policy
    response_format = dict(requirement.get("response_format") or {})
    if response_format:
        selection["response_format"] = response_format
    structured_output = str(requirement.get("structured_output") or "").strip().lower()
    if structured_output:
        selection["structured_output"] = structured_output
    for key in (
        "action_max_output_tokens",
        "action_timeout_seconds",
        "action_long_output_timeout_seconds",
        "action_thinking_mode",
        "action_reasoning_effort",
    ):
        value = requirement.get(key)
        if value not in (None, "", {}, []):
            selection[key] = value
    return selection


def _stream_policy_for_task_model_requirement(
    base_policy: Any,
    *,
    requirement: dict[str, Any],
) -> dict[str, Any]:
    policy = dict(base_policy or {})
    requirement_policy = dict(dict(requirement or {}).get("stream_policy") or {})
    if requirement_policy:
        policy = {**policy, **requirement_policy}
    if _truthy_config_bool(dict(requirement or {}).get("streaming_required")):
        policy = {
            **policy,
            "enabled": True,
            "mode": str(policy.get("mode") or "model_text_stream"),
            "fallback_to_non_stream_on_error": False,
            "chunk_strategy": str(policy.get("chunk_strategy") or "adaptive_buffer"),
            "first_flush_delay_ms": _stream_policy_int(policy.get("first_flush_delay_ms"), default=70),
            "target_buffer_delay_ms": _stream_policy_int(policy.get("target_buffer_delay_ms"), default=150),
            "adaptive_min_buffer_delay_ms": _stream_policy_int(policy.get("adaptive_min_buffer_delay_ms"), default=80),
            "adaptive_max_buffer_delay_ms": _stream_policy_int(policy.get("adaptive_max_buffer_delay_ms"), default=240),
            "release_tick_ms": _stream_policy_int(policy.get("release_tick_ms"), default=16),
            "max_buffer_delay_ms": _stream_policy_int(policy.get("max_buffer_delay_ms"), default=320),
            "max_flush_interval_ms": _stream_policy_int(policy.get("max_flush_interval_ms"), default=80),
            "max_pending_utf8_bytes": _stream_policy_int(policy.get("max_pending_utf8_bytes"), default=1536),
            "max_release_utf8_bytes": _stream_policy_int(policy.get("max_release_utf8_bytes"), default=192),
            "max_pending_line_count": _stream_policy_int(policy.get("max_pending_line_count"), default=1),
            "min_event_interval_ms": _stream_policy_int(policy.get("min_event_interval_ms"), default=16),
            "event_budget_per_second": _stream_policy_int(policy.get("event_budget_per_second"), default=45),
            "source": str(policy.get("source") or "node.contract_bindings.runtime.model_requirement.streaming_required"),
        }
    return policy


def _stream_policy_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed > 0 else int(default)


def _truthy_config_bool(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "required"}
    return False


def _origin_kind(task_run: Any) -> str:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    origin = dict(diagnostics.get("origin") or {})
    return str(origin.get("origin_kind") or diagnostics.get("origin_kind") or "").strip()


def _authorized_graph_node_executor_resume(task_run: Any, *, authorization: dict[str, Any] | None) -> bool:
    if not _graph_node_authorization_matches_identity(task_run, authorization=authorization):
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    if str(getattr(task_run, "status", "") or "") != "waiting_executor":
        return False
    executor_status = str(diagnostics.get("executor_status") or "").strip()
    if executor_status not in {"", "waiting_executor"}:
        return False
    return True


def _graph_node_authorization_matches_identity(task_run: Any, *, authorization: dict[str, Any] | None) -> bool:
    if not authorization:
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    if _origin_kind(task_run) != "graph_node_assigned":
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
    if not _graph_node_authorization_matches_identity(task_run, authorization=graph_node_authorization):
        return None
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
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
    sandbox = dict(environment.get("sandbox_policy") or {})
    storage = dict(environment.get("storage_space") or {})
    scope = compile_sandbox_execution_scope(
        environment_payload=environment,
        contract=_load_contract_for_policy(runtime_host, task_run_id),
        safety_envelope=task_safety_envelope_from_assembly(runtime_assembly),
    )
    project_root = _task_workspace_root(runtime_assembly, runtime_host=runtime_host)
    ensure_environment_storage_dirs(project_root=project_root, storage_space=storage)
    sandbox_root = str(sandbox.get("sandbox_root") or "").strip()
    if not sandbox_root:
        namespace = task_run_id.replace(":", "_")
        sandbox_root = str(
            runtime_cache_manager_for_host(runtime_host).sandbox_root(
                namespace,
                owner="task_run_sandbox",
                source_refs=(task_run_id,),
                ttl_seconds=DEFAULT_SANDBOX_CACHE_TTL_SECONDS,
            )
        )
    return {
        **sandbox,
        "enabled": bool(sandbox.get("enabled") is True),
        "sandbox_root": sandbox_root,
        "workspace_root": str(project_root),
        **scope.to_policy_payload(),
        "read_scopes": ["."],
        "approval_policy": str(sandbox.get("approval_policy") or "sandboxed_side_effects"),
        "side_effect_operations": list(
            sandbox.get("side_effect_operations")
            or ("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.browser_control", "op.image_generate")
        ),
    }


def _task_workspace_root(runtime_assembly: dict[str, Any], *, runtime_host: Any) -> Path:
    environment = dict(runtime_assembly.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    sandbox = dict(environment.get("sandbox_policy") or {})
    for candidate in (storage.get("workspace_root"), sandbox.get("workspace_root")):
        text = str(candidate or "").strip()
        if text:
            return Path(text).resolve()
    return ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root.resolve()


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
    artifact_root = str(sandbox_policy.get("artifact_root") or runtime_artifact_scope_from_environment(environment).artifact_root or "")
    return compile_tool_file_management_policy(
        environment,
        storage_space=storage,
        artifact_root=artifact_root,
        sandbox_policy=sandbox_policy,
    )


def _load_contract_for_policy(runtime_host: Any, task_run_id: str) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return {}
    return _load_contract(runtime_host, task_run)

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


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _verify_completion(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    contract: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    enforce_verification_gate: bool = False,
) -> dict[str, Any]:
    environment = dict(runtime_assembly.get("task_environment") or {})
    artifact_scope = runtime_artifact_scope_from_environment(environment)
    contract = canonicalize_task_contract_artifacts(
        contract,
        environment_payload=environment,
        artifact_root=artifact_scope.artifact_root,
    ).contract
    acceptance_contract = _acceptance_contract_projection(contract)
    required_artifacts = _contract_dict_items(acceptance_contract.get("required_artifacts"))
    artifact_refs = dedupe_artifact_refs(
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
    verification_gate: dict[str, Any] = {}
    if enforce_verification_gate:
        gate_observations = list(observations or _existing_observations(runtime_host, task_run_id))
        verification_gate = _verify_completion_worker_gate(
            runtime_host=runtime_host,
            task_run_id=task_run_id,
            contract=contract,
            artifact_refs=artifact_refs,
            verified_artifacts=verified_artifacts,
            observations=gate_observations,
        )
        if not verification_gate.get("ok", False):
            return {
                "ok": False,
                "missing": list(verification_gate.get("missing") or ["verification_worker_verdict"]),
                "required_artifacts": required_artifacts,
                "artifact_refs": artifact_refs,
                "verified_artifacts": verified_artifacts,
                "verification_gate": verification_gate,
                "repair_instruction": str(verification_gate.get("repair_instruction") or ""),
                "reason": str(verification_gate.get("reason") or "verification worker PASS verdict required"),
            }
    return {
        "ok": True,
        "missing": [],
        "verified_artifacts": verified_artifacts,
        **({"verification_gate": verification_gate} if verification_gate else {}),
    }


def _verify_completion_worker_gate(
    *,
    runtime_host: Any,
    task_run_id: str,
    contract: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    verified_artifacts: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    required_reasons = _verification_gate_required_reasons(
        contract=contract,
        artifact_refs=artifact_refs,
        verified_artifacts=verified_artifacts,
        observations=observations,
    )
    if not required_reasons:
        return {
            "ok": True,
            "required": False,
            "authority": "harness.loop.task_completion_verification_gate",
        }
    verdicts = _completion_verifier_verdicts_from_observations(
        runtime_host=runtime_host,
        observations=observations,
    )
    if not verdicts:
        return {
            "ok": False,
            "required": True,
            "required_reasons": required_reasons,
            "missing": ["verification_worker_verdict"],
            "reason": "completion verifier PASS verdict is required before finishing this TaskRun",
            "repair_instruction": _verification_gate_repair_instruction(contract=contract),
            "recommended_tool_call": {
                "tool_name": "spawn_subagent",
                "args": {
                    "target_agent_id": "agent:verifier",
                    "goal": "独立验证当前 TaskRun 是否已经满足用户目标和验收标准。",
                    "expected_outputs": ["verdict", "checks", "evidence_refs", "risks"],
                },
            },
            "authority": "harness.loop.task_completion_verification_gate",
        }
    latest = verdicts[-1]
    verdict_value = str(latest.get("verdict") or "").strip().upper()
    if verdict_value != "PASS":
        return {
            "ok": False,
            "required": True,
            "required_reasons": required_reasons,
            "missing": ["verification_worker_pass"],
            "latest_verdict": latest,
            "reason": f"completion verifier returned {verdict_value or 'UNKNOWN'}",
            "repair_instruction": (
                "验证员没有给出 PASS。你需要根据 verification worker 的检查结果修复问题；"
                "修复后再次验证，不能直接宣称完成。"
            ),
            "authority": "harness.loop.task_completion_verification_gate",
        }
    if not _verification_verdict_has_evidence(latest):
        return {
            "ok": False,
            "required": True,
            "required_reasons": required_reasons,
            "missing": ["verification_worker_evidence"],
            "latest_verdict": latest,
            "reason": "completion verifier PASS verdict lacks evidence",
            "repair_instruction": (
                "验证员给出了 PASS，但缺少命令、请求、浏览器检查或 observation refs 等证据。"
                "请等待或重新要求 verification worker 返回 evidence_refs/checks 后再完成。"
            ),
            "authority": "harness.loop.task_completion_verification_gate",
        }
    return {
        "ok": True,
        "required": True,
        "required_reasons": required_reasons,
        "latest_verdict": latest,
        "authority": "harness.loop.task_completion_verification_gate",
    }


def _verification_gate_required_reasons(
    *,
    contract: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    verified_artifacts: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    acceptance_contract = _acceptance_contract_projection(contract)
    if _contract_dict_items(acceptance_contract.get("required_verifications")):
        reasons.append("required_verifications")
    if _contract_dict_items(acceptance_contract.get("required_artifacts")):
        reasons.append("required_artifacts")
    if artifact_refs or verified_artifacts:
        reasons.append("artifact_evidence")
    if any(_observation_is_successful_write(item) for item in observations):
        reasons.append("write_observation")
    return _dedupe_strings(reasons)


def _should_enforce_completion_verification_gate(task_run: Any, *, contract: dict[str, Any]) -> bool:
    acceptance_contract = _acceptance_contract_projection(contract)
    required = _contract_dict_items(acceptance_contract.get("required_verifications"))
    acceptance = dict(acceptance_contract.get("acceptance_policy") or contract.get("acceptance_policy") or {})
    required.extend(
        dict(item)
        for item in list(acceptance.get("required_verifications") or [])
        if isinstance(item, dict)
    )
    return bool(required)


def _acceptance_contract_projection(contract: dict[str, Any]) -> dict[str, Any]:
    payload = dict(contract or {})
    acceptance = dict(payload.get("acceptance_contract") or {})
    if not acceptance:
        acceptance = {}
    if "completion_criteria" not in acceptance:
        acceptance["completion_criteria"] = list(payload.get("completion_criteria") or [])
    if "required_artifacts" not in acceptance:
        acceptance["required_artifacts"] = _contract_dict_items(payload.get("required_artifacts"))
    if "required_verifications" not in acceptance:
        acceptance["required_verifications"] = _contract_dict_items(payload.get("required_verifications"))
    if "acceptance_policy" not in acceptance and isinstance(payload.get("acceptance_policy"), dict):
        acceptance["acceptance_policy"] = dict(payload.get("acceptance_policy") or {})
    acceptance.setdefault("authority", "harness.loop.task_completion.acceptance_contract_projection")
    return acceptance


def _contract_dict_items(value: Any) -> list[dict[str, Any]]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if isinstance(value, dict) else [])
    return [dict(item) for item in raw_values if isinstance(item, dict)]


def _observation_is_successful_write(observation: dict[str, Any]) -> bool:
    return _observation_tool_name(observation) in {"write_file", "edit_file", "batch_edit_file"} and _observation_status(observation) == "ok"


def _completion_verifier_verdicts_from_observations(*, runtime_host: Any, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verdicts: list[dict[str, Any]] = []
    for observation in observations:
        if _observation_tool_name(observation) != "wait_subagent" or _observation_status(observation) != "ok":
            continue
        control = _subagent_control_payload_from_observation(observation)
        subagent_run_ref = str(control.get("subagent_run_ref") or "").strip()
        agent_run_payload = _agent_run_payload_for_ref(runtime_host, subagent_run_ref)
        if not _is_completion_verifier_agent_run(agent_run_payload):
            continue
        payloads = _verification_payload_candidates(
            runtime_host=runtime_host,
            control=control,
            agent_run_payload=agent_run_payload,
        )
        verdict = _extract_verification_verdict(payloads)
        if not verdict:
            continue
        evidence_refs, evidence_text_present = _verification_evidence(payloads)
        verdicts.append(
            {
                "verdict": verdict,
                "source": "wait_subagent",
                "subagent_run_ref": subagent_run_ref,
                "agent_id": str(agent_run_payload.get("agent_id") or ""),
                "agent_profile_id": str(agent_run_payload.get("agent_profile_id") or ""),
                "result_ref": _first_text(*(payload.get("result_ref") for payload in payloads if isinstance(payload, dict))),
                "evidence_refs": evidence_refs,
                "evidence_text_present": evidence_text_present,
                "observation_ref": str(observation.get("observation_id") or observation.get("observation_ref") or ""),
                "authority": "harness.loop.task_completion_verifier_verdict",
            }
        )
    return verdicts


def _subagent_control_payload_from_observation(observation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(envelope.get("structured_payload") or {})
    control = structured.get("subagent_control")
    if isinstance(control, dict):
        return dict(control)
    for raw in (payload.get("text"), envelope.get("text"), payload.get("result")):
        parsed = _json_payload(raw)
        if parsed.get("subagent_run_ref") or parsed.get("result_available"):
            return parsed
    return {}


def _agent_run_payload_for_ref(runtime_host: Any, agent_run_ref: str) -> dict[str, Any]:
    ref = str(agent_run_ref or "").strip()
    if not ref:
        return {}
    state_index = getattr(runtime_host, "state_index", None)
    snapshot_reader = getattr(state_index, "read_snapshot", None)
    if callable(snapshot_reader):
        try:
            snapshot = dict(snapshot_reader() or {})
        except Exception:
            snapshot = {}
        agent_runs = dict(snapshot.get("agent_runs") or {})
        if isinstance(agent_runs.get(ref), dict):
            return dict(agent_runs[ref])
    return {}


def _is_completion_verifier_agent_run(agent_run_payload: dict[str, Any]) -> bool:
    agent_id = str(agent_run_payload.get("agent_id") or "").strip()
    profile_id = str(agent_run_payload.get("agent_profile_id") or "").strip()
    return agent_id == "agent:verifier" or profile_id == "completion_verifier_agent"


def _verification_payload_candidates(
    *,
    runtime_host: Any,
    control: dict[str, Any],
    agent_run_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = [dict(control or {})]
    result = control.get("result")
    if isinstance(result, dict):
        payloads.append(dict(result))
    result_ref = _first_text(
        dict(result or {}).get("result_ref") if isinstance(result, dict) else "",
        control.get("result_ref"),
    )
    runtime_objects = getattr(runtime_host, "runtime_objects", None)
    get_object = getattr(runtime_objects, "get_object", None)
    if callable(get_object) and result_ref:
        try:
            stored_result = get_object(result_ref)
        except Exception:
            stored_result = {}
        if isinstance(stored_result, dict):
            payloads.append(dict(stored_result))
            raw_result = stored_result.get("raw_result")
            if isinstance(raw_result, dict):
                payloads.append(dict(raw_result))
            diagnostics = stored_result.get("diagnostics")
            if isinstance(diagnostics, dict):
                payloads.append(dict(diagnostics))
    task_run_id = str(agent_run_payload.get("task_run_id") or "").strip()
    state_index = getattr(runtime_host, "state_index", None)
    get_task_run = getattr(state_index, "get_task_run", None)
    if callable(get_task_run) and task_run_id:
        try:
            child_task = get_task_run(task_run_id)
        except Exception:
            child_task = None
        diagnostics = dict(getattr(child_task, "diagnostics", {}) or {}) if child_task is not None else {}
        if diagnostics:
            payloads.append(diagnostics)
            final_diagnostics = diagnostics.get("final_action_diagnostics")
            if isinstance(final_diagnostics, dict):
                payloads.append(dict(final_diagnostics))
    return [payload for payload in payloads if isinstance(payload, dict) and payload]


def _extract_verification_verdict(payloads: list[dict[str, Any]]) -> str:
    for payload in payloads:
        verdict = _normalize_verification_verdict(payload.get("verdict"))
        if verdict:
            return verdict
        for key in ("verification_gate", "verification", "completion_verification", "verifier_result", "raw_result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                verdict = _normalize_verification_verdict(nested.get("verdict"))
                if verdict:
                    return verdict
        for key in ("final_answer", "summary", "answer_candidate", "text", "result", "content"):
            verdict = _normalize_verification_verdict(payload.get(key))
            if verdict:
                return verdict
    return ""


def _normalize_verification_verdict(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper().replace("：", ":")
    if upper in {"PASS", "FAIL", "PARTIAL"}:
        return upper
    for marker in ("VERDICT", "裁决", "结论"):
        index = upper.find(marker)
        if index < 0:
            continue
        tail = upper[index : index + 96]
        positions = {
            verdict: tail.find(verdict)
            for verdict in ("PASS", "FAIL", "PARTIAL")
            if tail.find(verdict) >= 0
        }
        if positions:
            return sorted(positions.items(), key=lambda item: item[1])[0][0]
    stripped = upper.lstrip()
    for verdict in ("PASS", "FAIL", "PARTIAL"):
        if stripped.startswith(verdict):
            return verdict
    parsed = _json_payload(text)
    if parsed:
        return _normalize_verification_verdict(parsed.get("verdict"))
    return ""


def _verification_evidence(payloads: list[dict[str, Any]]) -> tuple[list[str], bool]:
    refs: list[str] = []
    text_parts: list[str] = []
    for payload in payloads:
        for key in ("evidence_refs", "observation_refs", "source_observation_refs"):
            refs.extend(str(item).strip() for item in list(payload.get(key) or []) if str(item).strip())
        for item in list(payload.get("artifact_refs") or []):
            if isinstance(item, dict):
                refs.append(str(item.get("path") or item.get("ref") or item.get("artifact_ref") or "").strip())
            elif str(item).strip():
                refs.append(str(item).strip())
        checks = payload.get("checks")
        if isinstance(checks, (list, tuple)) and checks:
            refs.append("checks")
        for key in ("final_answer", "summary", "answer_candidate", "text", "result", "content"):
            if str(payload.get(key) or "").strip():
                text_parts.append(str(payload.get(key) or ""))
    evidence_text = "\n".join(text_parts).lower()
    evidence_text_present = any(
        marker in evidence_text
        for marker in ("evidence", "command", "pytest", "browser", "request", "probe", "证据", "命令", "检查", "对抗")
    )
    return _dedupe_strings([ref for ref in refs if ref]), evidence_text_present


def _verification_verdict_has_evidence(verdict: dict[str, Any]) -> bool:
    return bool(list(verdict.get("evidence_refs") or []) or verdict.get("evidence_text_present") is True)


def _verification_gate_repair_instruction(*, contract: dict[str, Any]) -> str:
    goal = _first_text(contract.get("task_run_goal"), contract.get("user_visible_goal"), "当前 TaskRun")
    return (
        "完成前需要独立 verification worker 的 PASS 裁决。"
        "下一步不要直接 respond 完成；如果还没有验证员，请调用 spawn_subagent，target_agent_id 使用 agent:verifier，"
        f"goal 写成：独立验证“{goal}”是否已经满足用户目标、required_artifacts、required_verifications 和 completion_criteria。"
        "instructions 需要包含原始任务、已改动/产物、验证命令或证据、开放风险，并要求输出 verdict=PASS/FAIL/PARTIAL、checks、evidence_refs、risks。"
        "如果验证员已经启动，请调用 wait_subagent 等待结果。只有 verification worker 返回 PASS 且有证据时才允许完成。"
    )


def _finish_specialist_runtime_execution(
    services: TaskExecutorServices,
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    execution: SpecialistRuntimeExecution,
) -> dict[str, Any]:
    result = dict(execution.result or {})
    status = str(result.get("status") or "").strip().lower()
    completed = status == "completed"
    closeout_status = "completed" if completed else "failed"
    limitations = [str(item) for item in list(result.get("limitations") or []) if str(item)]
    summary = str(result.get("answer_candidate") or result.get("summary") or "").strip()
    missing_completed_answer = completed and not summary
    if missing_completed_answer:
        completed = False
        closeout_status = "failed"
        if "specialist_runtime_missing_answer" not in limitations:
            limitations.append("specialist_runtime_missing_answer")
    status_summary = summary or "能力运行结束，但没有返回可提交的 agent 正文。"
    artifact_refs = _normal_artifact_refs(result.get("artifact_refs"))
    evidence_refs = [str(item) for item in list(result.get("evidence_refs") or []) if str(item).strip()]
    task_runtime_diagnostics = {
        "authority": "harness.loop.task_executor.specialist_runtime_execution",
        "runtime_kind": execution.runtime_kind,
        "specialist_route": execution.route,
        "capability_result_status": status or closeout_status,
        "limitations": limitations,
        **dict(execution.diagnostics or {}),
    }
    result_diagnostics = {
        **task_runtime_diagnostics,
        "capability_diagnostics": dict(result.get("diagnostics") or {}),
    }
    result_payload = {
        "status": closeout_status,
        "final_answer": summary,
        "summary": str(result.get("summary") or ""),
        "answer_candidate": str(result.get("answer_candidate") or ""),
        "artifact_refs": artifact_refs,
        "evidence_refs": evidence_refs,
        "observation_refs": [],
        "limitations": limitations,
        "diagnostics": result_diagnostics,
        "raw_result": result,
    }
    result_ref = runtime_host.runtime_objects.put_object(
        "agent_run_result",
        f"{agent_run.agent_run_id}:result",
        result_payload,
    )
    now = time.time()
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status=closeout_status,
            updated_at=now,
            result_ref=result_ref,
            diagnostics={**dict(agent_run.diagnostics or {}), "specialist_runtime": result_diagnostics},
        )
    )
    runtime_host.state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id=f"agresult:{agent_run.agent_run_id}",
            agent_run_id=agent_run.agent_run_id,
            task_run_id=task_run.task_run_id,
            agent_id=agent_run.agent_id,
            status=closeout_status,  # type: ignore[arg-type]
            output_ref=result_ref,
            summary=compact_text(status_summary, limit=500),
            artifact_refs=tuple(_artifact_ref_to_string(item) for item in artifact_refs),
            created_at=now,
            diagnostics=result_diagnostics,
        )
    )
    terminal_reason = (
        "completed"
        if completed
        else ("specialist_runtime_missing_answer" if missing_completed_answer else _specialist_terminal_reason(execution=execution, limitations=limitations))
    )
    task_candidate = replace(
        task_run,
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "artifact_refs": artifact_refs,
            "specialist_runtime": task_runtime_diagnostics,
            "specialist_result_ref": result_ref,
            "execution_result_status": closeout_status,
        },
    )
    output_commit: dict[str, Any] = {}
    if completed:
        if str(getattr(task_candidate, "execution_runtime_kind", "") or "") == "subagent_task":
            output_commit = _record_session_output_commit_skipped(
                runtime_host,
                task_run=task_candidate,
                final_answer=summary,
                reason="not_main_session_visible",
            )
        else:
            output_commit = _commit_task_run_final_message(services, task_run=task_candidate, final_answer=summary)
            if not _commit_receipt_committed(output_commit):
                return _finish_executor_output_commit_failure(
                    runtime_host,
                    task_run=task_candidate,
                    observations=[],
                    final_answer=summary,
                    artifact_refs=artifact_refs,
                    commit_receipt=output_commit,
                )
        task_candidate = replace(
            task_candidate,
            diagnostics={
                **dict(task_candidate.diagnostics or {}),
                "output_commit_status": _commit_receipt_status(output_commit),
            },
        )
    lifecycle = _load_lifecycle(runtime_host, task_run)
    finished_task, finished_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=task_candidate,
        lifecycle=lifecycle,
        status=closeout_status,  # type: ignore[arg-type]
        terminal_reason=terminal_reason,
        observation_refs=(),
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=finished_task.task_run_id,
        step=f"specialist_runtime_{closeout_status}",
        status=closeout_status,
        summary=status_summary,
        evidence_refs=evidence_refs,
        refs={"agent_run_result_ref": result_ref},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=finished_task,
        item_type="final_response" if completed else "interrupted_boundary",
        title="已完成" if completed else "执行失败",
        status=closeout_status,
        summary=status_summary,
        agent_brief_output=summary,
        event_offset=_event_offset(event),
        refs={"task_run_ref": finished_task.task_run_id, "agent_run_result_ref": result_ref},
        payload={"artifact_refs": artifact_refs, "evidence_refs": evidence_refs, "limitations": limitations, "output_commit": dict(output_commit)},
    )
    _sync_engagement_closeout(runtime_host, finished_task.task_run_id)
    return {
        "ok": completed,
        "task_run": finished_task.to_dict(),
        "lifecycle": finished_lifecycle.to_dict(),
        "event": event,
        "final_answer": summary,
        "artifact_refs": artifact_refs,
        "result_ref": result_ref,
        "output_commit": output_commit,
        **({"error": terminal_reason} if not completed else {}),
    }


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
    success_task = replace(
        task_run,
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "artifact_refs": artifact_refs,
            "final_action_diagnostics": dict(final_action_diagnostics or {}),
            "execution_result_status": "completed",
        },
    )
    commit_receipt = _commit_task_run_final_message(
        services,
        task_run=success_task,
        final_answer=final_answer,
    )
    if not _commit_receipt_committed(commit_receipt):
        return _finish_executor_output_commit_failure(
            runtime_host,
            task_run=success_task,
            observations=observations,
            final_answer=final_answer,
            artifact_refs=artifact_refs,
            commit_receipt=commit_receipt,
        )
    lifecycle = _load_lifecycle(runtime_host, task_run)
    finished_task, finished_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=replace(
            success_task,
            diagnostics={
                **dict(success_task.diagnostics or {}),
                "output_commit_status": "committed",
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
        payload={"artifact_refs": artifact_refs, "final_answer": final_answer, "output_commit": dict(commit_receipt)},
    )
    _sync_engagement_closeout(runtime_host, finished_task.task_run_id)
    return {
        "ok": True,
        "task_run": finished_task.to_dict(),
        "lifecycle": finished_lifecycle.to_dict(),
        "event": event,
        "final_answer": final_answer,
        "artifact_refs": artifact_refs,
        "output_commit": commit_receipt,
    }


def _finish_executor_agent_controlled_runtime_boundary(
    services: TaskExecutorServices,
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    action_request: AnyModelActionRequest,
    control_observation: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(control_observation.get("payload") or {})
    signal_kind = str(payload.get("signal_kind") or "").strip()
    final_answer = str(getattr(action_request, "final_answer", "") or "").strip()
    now = time.time()
    if signal_kind == "stop":
        lifecycle_status = "aborted"
        terminal_reason = "user_aborted"
        agent_status = "killed"
        result_status = "killed"
        control_state = _TASK_RUN_STOPPED
        executor_status = "stopped"
        recovery_action = ""
        rollout_title = "已停止"
        rollout_item_type = "interrupted_boundary"
        latest_step = "task_run_agent_controlled_stop"
        latest_summary = "agent 已根据停止信号完成收口。"
    elif signal_kind == "pause":
        lifecycle_status = "waiting_executor"
        terminal_reason = "waiting_executor"
        agent_status = "failed"
        result_status = "failed"
        control_state = _TASK_RUN_PAUSED
        executor_status = "waiting_executor"
        recovery_action = "resume_task_run"
        rollout_title = "已暂停"
        rollout_item_type = "pause_boundary"
        latest_step = "task_run_agent_controlled_pause"
        latest_summary = "agent 已根据暂停信号完成断点收口。"
    else:
        lifecycle_status = "waiting_executor"
        terminal_reason = f"runtime_control_{signal_kind or 'signal'}"
        agent_status = "failed"
        result_status = "failed"
        control_state = str(payload.get("runtime_control_state") or "")
        executor_status = "waiting_executor"
        recovery_action = "rerun_task_executor"
        rollout_title = "等待调整"
        rollout_item_type = "interrupted_boundary"
        latest_step = "task_run_agent_controlled_runtime_boundary"
        latest_summary = "agent 已根据运行控制信号完成当前边界收口。"

    control = _runtime_control_payload(task_run, runtime_host=runtime_host)
    diagnostics = _diagnostics_with_runtime_control(
        _strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
        state=control_state,
        requested_by=str(control.get("requested_by") or payload.get("requested_by") or "system"),
        requested_at=float(control.get("requested_at") or payload.get("requested_at") or now),
        reason=str(control.get("reason") or payload.get("reason") or ""),
        latest_step=latest_step,
        latest_step_status=lifecycle_status,
        latest_step_summary=latest_summary,
    )
    diagnostics.update(
        {
            "executor_status": executor_status,
            "artifact_refs": artifact_refs,
            "final_action_diagnostics": dict(getattr(action_request, "diagnostics", {}) or {}),
            "agent_controlled_runtime_boundary": {
                "signal_kind": signal_kind,
                "observation_ref": str(control_observation.get("observation_id") or ""),
                "terminal_reason": terminal_reason,
                "authority": "harness.loop.task_executor",
            },
        }
    )
    if not _runtime_control_signal_gateway_can_consume(
        runtime_host,
        task_run=task_run,
        control_observation=control_observation,
    ):
        return {
            "ok": False,
            "task_run": task_run.to_dict(),
            "error": "runtime_gateway_control_signal_consumption_unavailable",
            "retryable": True,
        }
    if recovery_action:
        diagnostics["recovery_action"] = recovery_action
    else:
        diagnostics.pop("recoverable_error", None)
        diagnostics.pop("recovery_action", None)
    result_ref = runtime_host.runtime_objects.put_object(
        "agent_run_result",
        f"{agent_run.agent_run_id}:result",
        {
            "final_answer": final_answer,
            "artifact_refs": artifact_refs,
            "observation_refs": [str(item.get("observation_id") or "") for item in observations if item.get("observation_id")],
            "agent_controlled_runtime_boundary": dict(diagnostics["agent_controlled_runtime_boundary"]),
        },
    )
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status=agent_status,
            updated_at=now,
            result_ref=result_ref,
            diagnostics={
                **dict(agent_run.diagnostics or {}),
                "terminal_reason": terminal_reason,
                "agent_controlled_runtime_boundary": dict(diagnostics["agent_controlled_runtime_boundary"]),
            },
        )
    )
    runtime_host.state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id=f"agresult:{agent_run.agent_run_id}",
            agent_run_id=agent_run.agent_run_id,
            task_run_id=task_run.task_run_id,
            agent_id=agent_run.agent_id,
            status=result_status,  # type: ignore[arg-type]
            output_ref=result_ref,
            summary=compact_text(final_answer, limit=500),
            artifact_refs=tuple(str(item.get("path") or item.get("src") or item) for item in artifact_refs),
            created_at=now,
            diagnostics={"artifact_refs": artifact_refs, "agent_controlled_runtime_boundary": dict(diagnostics["agent_controlled_runtime_boundary"])},
        )
    )
    task_candidate = replace(task_run, diagnostics=diagnostics)
    output_commit: dict[str, Any] = {}
    if str(getattr(task_candidate, "execution_runtime_kind", "") or "") != "subagent_task":
        output_commit = _commit_task_run_final_message(
            services,
            task_run=task_candidate,
            final_answer=final_answer,
            completion_state=lifecycle_status,
            terminal_reason=terminal_reason,
            answer_source="harness.loop.task_executor.agent_controlled_runtime_boundary",
            execution_posture="task_run_agent_controlled_runtime_boundary",
        )
        diagnostics = {
            **dict(diagnostics),
            "output_commit_status": _commit_receipt_status(output_commit),
        }
        task_candidate = replace(task_candidate, diagnostics=diagnostics)

    consumed_event: Any | None = None

    def _consume_control_signal_before_terminal_state(
        updated_task: Any,
        _updated_lifecycle: Any,
        lifecycle_event: dict[str, Any],
    ) -> None:
        nonlocal consumed_event
        consumed_event = _mark_runtime_control_signal_gateway_consumed(
            runtime_host,
            task_run=updated_task,
            control_observation=control_observation,
            lifecycle_status=lifecycle_status,
            terminal_reason=terminal_reason,
            output_commit=output_commit,
            lifecycle_event=lifecycle_event,
        )
        if consumed_event is None:
            raise RuntimeError("runtime_gateway_control_signal_consumption_unavailable")

    lifecycle = _load_lifecycle(runtime_host, task_run)
    finished_task, finished_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=task_candidate,
        lifecycle=lifecycle,
        status=lifecycle_status,  # type: ignore[arg-type]
        terminal_reason=terminal_reason,
        observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
        before_state_commit=_consume_control_signal_before_terminal_state,
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step=latest_step,
        status=lifecycle_status,
        summary=latest_summary,
        agent_brief_output=final_answer,
        refs={"observation_ref": str(control_observation.get("observation_id") or "")},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=finished_task,
        item_type=rollout_item_type,
        title=rollout_title,
        status=lifecycle_status,
        summary=latest_summary,
        agent_brief_output=final_answer,
        event_offset=_event_offset(event),
        refs={"task_run_ref": finished_task.task_run_id, "observation_ref": str(control_observation.get("observation_id") or "")},
        payload={
            "terminal_reason": terminal_reason,
            "final_answer": final_answer,
            "agent_controlled_runtime_boundary": dict(diagnostics["agent_controlled_runtime_boundary"]),
        },
    )
    if lifecycle_status == "waiting_executor":
        _bind_active_turn_for_task_state(runtime_host, finished_task, state="waiting_executor")
    else:
        _sync_engagement_closeout(runtime_host, finished_task.task_run_id)
    return {
        "ok": False,
        "task_run": finished_task.to_dict(),
        "lifecycle": finished_lifecycle.to_dict(),
        "event": event,
        "final_answer": final_answer,
        "artifact_refs": artifact_refs,
        "error": terminal_reason,
        "retryable": lifecycle_status == "waiting_executor",
        "runtime_control_signal_consumed_event": consumed_event,
    }


def _commit_task_run_final_message(
    services: TaskExecutorServices,
    *,
    task_run: Any,
    final_answer: str,
    completion_state: str = "completed",
    terminal_reason: str = "completed",
    answer_source: str = "harness.loop.task_executor.completed",
    execution_posture: str = "task_run_completed",
) -> dict[str, Any]:
    committer = getattr(services, "assistant_message_committer", None)
    runtime_host = services.runtime_host
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    session_id = str(getattr(task_run, "session_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    agent_scope = _agent_run_scope_payload(task_run)
    agent_run_id = str(agent_scope.get("agent_run_id") or "").strip()
    run_cell_id = str(agent_scope.get("run_cell_id") or "").strip()
    refs = {
        "task_run_ref": task_run_id,
        **({"agent_run_ref": agent_run_id} if agent_run_id else {}),
        **({"run_cell_ref": run_cell_id} if run_cell_id else {}),
    }
    if not callable(committer):
        result = OutputCommitAuthority(runtime_host).record_skipped(
            OutputCommitRequest(
                run_id=task_run_id or "session-output-commit",
                session_id=session_id,
                task_run_id=task_run_id,
                task_id=task_id,
                agent_run_id=agent_run_id,
                run_cell_id=run_cell_id,
                turn_id="",
                content="",
                answer_channel="final_answer",
                answer_source=answer_source,
                execution_posture=execution_posture,
                has_tool_receipt=True,
                completion_state=completion_state,
                terminal_reason=terminal_reason,
                refs=refs,
            ),
            reason="assistant_message_committer_missing",
            content="",
            commit_gate={},
        )
        return dict(result.receipt)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    turn_id = str(diagnostics.get("turn_id") or "").strip() or _task_run_output_turn_id(task_run_id)
    runtime_control = dict(diagnostics.get(_TASK_RUN_CONTROL_KEY) or {})
    control_reason = str(runtime_control.get("reason") or "").strip()
    commit_source = "harness.loop.task_executor"
    if control_reason == "replaced_by_new_task_request" and terminal_reason == "user_aborted":
        commit_source = "harness.loop.task_executor.replacement_stop"
    request = OutputCommitRequest(
        run_id=task_run_id or "session-output-commit",
        session_id=session_id,
        task_run_id=task_run_id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        run_cell_id=run_cell_id,
        turn_id=turn_id,
        content=final_answer,
        answer_channel="final_answer",
        answer_source=answer_source,
        execution_posture=execution_posture,
        has_tool_receipt=True,
        completion_state=completion_state,
        terminal_reason=terminal_reason,
        commit_source=commit_source,
        refs=refs,
    )
    authority = OutputCommitAuthority(runtime_host)
    result = authority.commit_sync(
        request,
        committer=committer,
    )
    if str(result.receipt.get("state") or result.receipt.get("status") or "") == "committed":
        _record_task_assistant_text_final(
            runtime_host,
            task_run=task_run,
            content=result.decision.content,
            decision=result.decision,
            completion_state=completion_state,
            terminal_reason=terminal_reason,
        )
    return dict(result.receipt)


def _task_run_output_turn_id(task_run_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(task_run_id or "")).strip("_")
    return f"taskrun-final:{safe or uuid.uuid4().hex[:12]}"


def _record_session_output_commit_skipped(
    runtime_host: Any,
    *,
    task_run: Any,
    final_answer: str,
    reason: str,
) -> dict[str, Any]:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    session_id = str(getattr(task_run, "session_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    turn_id = str(diagnostics.get("turn_id") or "").strip()
    agent_scope = _agent_run_scope_payload(task_run)
    agent_run_id = str(agent_scope.get("agent_run_id") or "").strip()
    run_cell_id = str(agent_scope.get("run_cell_id") or "").strip()
    refs = {
        "task_run_ref": task_run_id,
        **({"agent_run_ref": agent_run_id} if agent_run_id else {}),
        **({"run_cell_ref": run_cell_id} if run_cell_id else {}),
    }
    result = OutputCommitAuthority(runtime_host).record_skipped(
        OutputCommitRequest(
            run_id=task_run_id or "session-output-commit",
            session_id=session_id,
            task_run_id=task_run_id,
            task_id=task_id,
            agent_run_id=agent_run_id,
            run_cell_id=run_cell_id,
            turn_id=turn_id,
            content=final_answer,
            answer_channel="final_answer",
            answer_source="harness.loop.task_executor.skipped",
            execution_posture="task_run_output_commit_skipped",
            has_tool_receipt=True,
            refs=refs,
        ),
        reason=reason,
        content=final_answer,
        commit_gate={},
    )
    return dict(result.receipt)


def _record_task_assistant_text_final(
    runtime_host: Any,
    *,
    task_run: Any,
    content: str,
    decision: Any,
    completion_state: str,
    terminal_reason: str,
) -> Any | None:
    final_content = str(content or "")
    if not final_content.strip():
        return None
    if not allows_assistant_body_projection(
        answer_channel=str(getattr(decision, "answer_channel", "") or ""),
        answer_canonical_state=str(getattr(decision, "canonical_state", "") or ""),
        answer_persist_policy=str(getattr(decision, "persist_policy", "") or ""),
    ):
        return None
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    if not task_run_id:
        return None
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    session_id = str(getattr(task_run, "session_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    turn_id = str(diagnostics.get("turn_id") or "").strip()
    turn_run_id = str(diagnostics.get("turn_run_id") or "").strip()
    stream_ref = f"task-run:{task_run_id}:final-answer"
    message_ref = assistant_message_ref(turn_id=turn_id, stream_ref=stream_ref)
    payload = assistant_text_final_event(
        content=final_content,
        stream_ref=stream_ref,
        message_ref=message_ref,
        turn_run_id=turn_run_id,
        task_run_id=task_run_id,
        sequence=1,
        answer_channel=str(getattr(decision, "answer_channel", "") or "final_answer"),
        answer_source=str(getattr(decision, "answer_source", "") or "harness.loop.task_executor.completed"),
        answer_canonical_state=str(getattr(decision, "canonical_state", "") or "stable_answer"),
        answer_persist_policy=str(getattr(decision, "persist_policy", "") or "persist_canonical"),
        terminal_reason=terminal_reason,
        extra={
            "session_id": session_id,
            "turn_id": turn_id,
            "task_id": task_id,
            "completion_state": str(completion_state or ""),
            "answer_finalization_policy": str(getattr(decision, "finalization_policy", "") or ""),
            "answer_fallback_reason": str(getattr(decision, "fallback_reason", "") or ""),
            "answer_selected_channel": str(getattr(decision, "selected_channel", "") or ""),
            "answer_selected_source": str(getattr(decision, "selected_source", "") or ""),
            "answer_leak_flags": list(getattr(decision, "leak_flags", ()) or ()),
            "authority": "harness.loop.task_executor.assistant_body_projection",
        },
    )
    event = runtime_host.event_log.append(
        task_run_id,
        "assistant_text_final",
        payload=payload,
        refs={
            "session_id": session_id,
            "session_ref": session_id,
            "turn_id": turn_id,
            "turn_ref": turn_id,
            "turn_run_ref": turn_run_id,
            "task_id": task_id,
            "task_run_ref": task_run_id,
            "message_ref": message_ref,
        },
    )
    state_index = getattr(runtime_host, "state_index", None)
    get_task_run = getattr(state_index, "get_task_run", None)
    upsert_task_run = getattr(state_index, "upsert_task_run", None)
    current = get_task_run(task_run_id) if callable(get_task_run) else None
    if current is not None and callable(upsert_task_run):
        upsert_task_run(
            replace(
                current,
                updated_at=event.created_at or time.time(),
                latest_event_offset=event.offset,
            )
        )
    return event


def _commit_receipt_status(receipt: dict[str, Any]) -> str:
    return str((receipt or {}).get("state") or (receipt or {}).get("status") or "").strip().lower()


def _commit_receipt_committed(receipt: dict[str, Any]) -> bool:
    return _commit_receipt_status(receipt) == "committed"


def _finish_executor_output_commit_failure(
    runtime_host: Any,
    *,
    task_run: Any,
    observations: list[dict[str, Any]],
    final_answer: str,
    artifact_refs: list[dict[str, Any]],
    commit_receipt: dict[str, Any],
) -> dict[str, Any]:
    reason = str(commit_receipt.get("reason") or "session_output_commit_failed").strip()
    status = _commit_receipt_status(commit_receipt) or "failed"
    terminal_reason = "session_output_commit_failed" if status == "failed" else "session_output_commit_not_committed"
    lifecycle = _load_lifecycle(runtime_host, task_run)
    failed_task, failed_lifecycle, event = finish_task_lifecycle(
        runtime_host,
        task_run=replace(
            task_run,
            diagnostics={
                **dict(getattr(task_run, "diagnostics", {}) or {}),
                "artifact_refs": artifact_refs,
                "execution_result_status": "completed",
                "output_commit_status": status,
                "output_commit_failure_reason": reason,
            },
        ),
        lifecycle=lifecycle,
        status="failed",
        terminal_reason=terminal_reason,
        observation_refs=tuple(str(item.get("observation_id") or "") for item in observations if item.get("observation_id")),
    )
    summary = "任务执行已完成，但最终回答写入会话失败。"
    _record_task_step_summary(
        runtime_host,
        task_run_id=failed_task.task_run_id,
        step="session_output_commit_failed",
        status="failed",
        summary=summary,
        agent_brief_output=final_answer,
        refs={"task_run_ref": failed_task.task_run_id},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=failed_task,
        item_type="interrupted_boundary",
        title="输出写入失败",
        status="failed",
        summary=summary,
        agent_brief_output=final_answer,
        event_offset=_event_offset(event),
        refs={"task_run_ref": failed_task.task_run_id},
        payload={"terminal_reason": terminal_reason, "output_commit": dict(commit_receipt)},
    )
    _sync_engagement_closeout(runtime_host, failed_task.task_run_id)
    return {
        "ok": False,
        "task_run": failed_task.to_dict(),
        "lifecycle": failed_lifecycle.to_dict(),
        "event": event,
        "error": terminal_reason,
        "final_answer": final_answer,
        "artifact_refs": artifact_refs,
        "output_commit": commit_receipt,
    }


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
    closeout_summary = _executor_closeout_summary(status=closeout_status, terminal_reason=closeout_reason)
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step=f"task_run_{closeout_status}",
        status=closeout_status,
        summary=closeout_summary,
    )
    append_work_rollout_item(
        runtime_host,
        task_run=finished_task,
        item_type="pause_boundary" if closeout_status == "waiting_executor" else ("interrupted_boundary" if closeout_status in {"aborted", "failed", "blocked"} else "progress"),
        title="等待继续" if closeout_status == "waiting_executor" else ("处理遇到阻塞" if closeout_status in {"aborted", "failed", "blocked"} else "处理结束"),
        status=closeout_status,
        summary=closeout_summary,
        event_offset=_event_offset(event),
        refs={"task_run_ref": finished_task.task_run_id},
        payload={"terminal_reason": closeout_reason},
    )
    _sync_engagement_closeout(runtime_host, finished_task.task_run_id)
    return {"ok": False, "task_run": finished_task.to_dict(), "lifecycle": finished_lifecycle.to_dict(), "event": event, "error": closeout_reason}


def _executor_closeout_summary(*, status: str, terminal_reason: str) -> str:
    reason = _executor_public_terminal_reason(terminal_reason) or "未知原因"
    if status == "waiting_executor":
        if reason == "等待你的确认":
            return "当前步骤正在等待你的确认。"
        return f"当前步骤在等待继续：{reason}。"
    if status in {"aborted", "failed", "blocked"}:
        return f"当前步骤遇到阻塞：{reason}。"
    if status == "completed":
        return "当前步骤已完成。"
    return f"当前步骤已结束：{reason}。"


def _executor_public_terminal_reason(reason: str) -> str:
    normalized = str(reason or "").strip()
    label = {
        "user_input_required": "等待你的确认",
        "waiting_executor": "等待继续",
        "waiting_user": "等待你的确认",
        "waiting_approval": "等待权限确认",
        "runtime_cell_missing_after_restart": "连接恢复后需要重新接续运行",
        "runtime_cell_cancelled": "运行已停止",
        "completed": "已完成",
        "failed": "运行中断",
        "blocked": "处理遇到阻塞",
        "aborted": "运行已停止",
        "cancelled": "运行已停止",
        "canceled": "运行已停止",
        "stopped": "运行已停止",
    }.get(normalized)
    if label:
        return label
    public = public_runtime_progress_summary(normalized)
    if public and not _looks_like_executor_reason_code(public):
        return public
    return "需要检查运行状态" if normalized else ""


def _looks_like_executor_reason_code(reason: str) -> bool:
    normalized = str(reason or "").strip()
    if not normalized or any(ord(ch) > 127 for ch in normalized):
        return False
    return "_" in normalized or normalized.startswith(("task-", "task:", "stream-", "stream:", "runtime-", "runtime:", "background-"))


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
    lifecycle = _load_lifecycle(runtime_host, task_run)
    paused_task, _paused_lifecycle, _lifecycle_event = finish_task_lifecycle(
        runtime_host,
        task_run=paused_task,
        lifecycle=lifecycle,
        status="blocked",
        terminal_reason="model_call_recovery_required",
        observation_refs=(observation["observation_id"],),
    )
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status="failed",
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
    recovery_state = recovery_state_for_task_run(current, runtime_host=runtime_host)
    if recovery_state.stopped:
        if recovery_state.control_state == _TASK_RUN_STOP_REQUESTED:
            return None
        return _stop_executor_for_terminal_control(runtime_host, task_run=current, agent_run=agent_run, boundary=boundary)
    return None


def _executor_control_signal_from_boundary_result(
    result: dict[str, Any],
    *,
    task_run: Any,
    executor_epoch: int,
) -> ExecutorControlSignal:
    error = str(result.get("error") or result.get("reason") or "").strip()
    kind = "stop"
    if error == "task_run_paused":
        kind = "pause"
    elif error == "user_interrupt_replan_required":
        kind = "replan"
    return ExecutorControlSignal(
        kind=kind,  # type: ignore[arg-type]
        task_run_id=str(getattr(task_run, "task_run_id", "") or dict(result.get("task_run") or {}).get("task_run_id") or ""),
        executor_epoch=int(executor_epoch or 0),
        reason=error or str(dict(result.get("task_run") or {}).get("terminal_reason") or "runtime_control_boundary"),
        requested_by="system",
        requested_at=time.time(),
    )


def _stop_executor_for_terminal_control(runtime_host: Any, *, task_run: Any, agent_run: Any | None, boundary: str) -> dict[str, Any]:
    if str(getattr(task_run, "status", "") or "") == "aborted" and str(getattr(task_run, "terminal_reason", "") or "") == "user_aborted":
        if agent_run is not None:
            runtime_host.state_index.upsert_agent_run(
                replace(
                    agent_run,
                    status="killed",
                    updated_at=time.time(),
                    diagnostics={
                        **dict(agent_run.diagnostics or {}),
                        "terminal_reason": "user_aborted",
                        "runtime_control": _runtime_control_payload(task_run, runtime_host=runtime_host),
                    },
                )
            )
        return {"ok": False, "task_run": task_run.to_dict(), "error": "user_aborted", "boundary": boundary}
    return _stop_executor_for_user_control(runtime_host, task_run=task_run, agent_run=agent_run, boundary=boundary)


def _pause_executor_for_user_control(runtime_host: Any, *, task_run: Any, agent_run: Any | None, boundary: str) -> dict[str, Any]:
    now = time.time()
    control = _runtime_control_payload(task_run, runtime_host=runtime_host)
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_run_paused",
        payload={"task_run_id": task_run.task_run_id, "boundary": boundary, "control": control},
        refs={"task_run_ref": task_run.task_run_id},
    )
    diagnostics = _diagnostics_with_runtime_control(
        _strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
        state=_TASK_RUN_PAUSED,
        requested_by=str(control.get("requested_by") or "user"),
        requested_at=float(control.get("requested_at") or now),
        reason=str(control.get("reason") or ""),
        latest_step="task_run_paused",
        latest_step_status="waiting_executor",
        latest_step_summary="已在安全边界暂停，后续可以从这里继续。",
    )
    paused_task = replace(
        task_run,
        status="waiting_executor",
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        terminal_reason="",
        diagnostics={
            **diagnostics,
            "executor_status": "waiting_executor",
            "wait_reason": "user_paused",
            "recovery_action": "resume_task_run",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    _bind_active_turn_for_task_state(runtime_host, paused_task, state="waiting_executor")
    if agent_run is not None:
        runtime_host.state_index.upsert_agent_run(
            replace(
                agent_run,
                status="failed",
                updated_at=event.created_at or now,
                diagnostics={
                    **dict(agent_run.diagnostics or {}),
                    "terminal_reason": "user_paused",
                    "runtime_control": _runtime_control_payload(paused_task, runtime_host=runtime_host),
                },
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
    control = _runtime_control_payload(task_run, runtime_host=runtime_host)
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
                diagnostics={
                    **dict(agent_run.diagnostics or {}),
                    "terminal_reason": "user_aborted",
                    "runtime_control": _runtime_control_payload(stopped_task, runtime_host=runtime_host),
                },
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
    control = _runtime_control_payload(task_run, runtime_host=runtime_host)
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
        terminal_reason="",
        diagnostics={
            **diagnostics,
            "executor_status": "waiting_executor",
            "wait_reason": "user_interrupt_replan_required",
            "recoverable_error": recoverable_error,
            "recovery_action": "resume_task_run",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    if agent_run is not None:
        runtime_host.state_index.upsert_agent_run(
            replace(
                agent_run,
                status="failed",
                updated_at=event.created_at or now,
                diagnostics={
                    **dict(agent_run.diagnostics or {}),
                    "terminal_reason": "user_interrupt_replan_required",
                    "runtime_control": _runtime_control_payload(paused_task, runtime_host=runtime_host),
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
    control = _runtime_control_payload(task_run, runtime_host=runtime_host)
    stopped_diagnostics = _diagnostics_with_runtime_control(
        _strip_runtime_lease_diagnostics(dict(task_run.diagnostics or {})),
        state=_TASK_RUN_STOPPED,
        requested_by=str(control.get("requested_by") or "user"),
        requested_at=float(control.get("requested_at") or time.time()),
        reason=reason or str(control.get("reason") or ""),
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


def _pause_executor_for_tool_approval(
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    action_request: AnyModelActionRequest,
    observation: dict[str, Any],
    observation_event: Any,
    step_index: int,
) -> dict[str, Any]:
    now = time.time()
    observation_ref = str(observation.get("observation_id") or "")
    payload = dict(observation.get("payload") or {})
    identity_source, execution_receipt = _trusted_tool_observation_identity_source(payload)
    tool_name = _observation_tool_name(observation)
    operation_id = str(identity_source.get("operation_id") or payload.get("operation_id") or "").strip()
    tool_call = dict(getattr(action_request, "tool_call", {}) or {})
    tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    tool_call_id = _canonical_tool_call_id(action_request)
    directive_ref = str(observation.get("directive_ref") or f"runtime-directive:{task_run.task_run_id}:tool:{action_request.request_id}")
    approval_fingerprint = _approval_fingerprint_from_observation(observation)
    pending_approval = {
        "approval_request_id": f"approval-request:{task_run.task_run_id}:{action_request.request_id}:{uuid.uuid4().hex[:8]}",
        "status": "pending",
        "mode": "runtime_approval",
        "task_run_id": task_run.task_run_id,
        "action_request_ref": action_request.request_id,
        "tool_call_id": tool_call_id,
        "observation_ref": observation_ref,
        "tool_name": tool_name,
        "operation_id": operation_id,
        "directive_ref": directive_ref,
        "approval_risk_fingerprint": approval_fingerprint,
        "tool_args_hash": tool_args_hash(tool_args),
        "action_request": action_request.to_dict(),
        "created_at": now,
        "authority": "runtime.tool_approval_control",
        "operation_gate": dict(payload.get("operation_gate") or {}),
        "execution_receipt": execution_receipt,
    }
    approval_signal = publish_task_tool_approval_requested(
        runtime_host,
        task_run=task_run,
        pending_approval=pending_approval,
        observation_ref=observation_ref,
    )
    if approval_signal is None:
        return {
            "ok": False,
            "task_run": task_run.to_dict(),
            "error": "runtime_gateway_approval_signal_unavailable",
            "retryable": True,
            "pending_approval": pending_approval,
        }
    lifecycle = _load_lifecycle(runtime_host, task_run)
    updated_lifecycle = replace(
        lifecycle,
        status="waiting_approval",
        updated_at=now,
        terminal_reason="",
        observation_refs=tuple(_dedupe_strings([*list(lifecycle.observation_refs), observation_ref])),
    )
    waiting_task = replace(
        task_run,
        status="waiting_approval",
        updated_at=now,
        terminal_reason="",
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "executor_status": "waiting_approval",
            "wait_reason": "tool_approval_required",
            "pending_approval": pending_approval,
            "latest_step": f"task_tool_approval_waiting:{step_index}",
            "latest_step_status": "waiting_approval",
            "latest_step_summary": "工具调用需要前端确认，任务已暂停等待确认。",
        },
    )
    runtime_host.state_index.upsert_task_run(waiting_task)
    _bind_active_turn_for_task_state(runtime_host, waiting_task, state="waiting_approval")
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            updated_at=now,
            diagnostics={**dict(agent_run.diagnostics or {}), "executor_status": "waiting_approval", "pending_approval": pending_approval},
        )
    )
    lifecycle_ref = runtime_host.runtime_objects.put_object(
        "task_lifecycle",
        task_run.task_run_id,
        updated_lifecycle.to_dict(),
    )
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "approval_waiting",
        payload={
            "task_run": waiting_task.to_dict(),
            "lifecycle": updated_lifecycle.to_dict(),
            "pending_approval": pending_approval,
            "observation": observation,
        },
        refs={
            "task_run_ref": task_run.task_run_id,
            "task_lifecycle_ref": lifecycle_ref,
            "action_request_ref": action_request.request_id,
            "observation_ref": observation_ref,
        },
    )
    waiting_task = replace(waiting_task, updated_at=event.created_at or now, latest_event_offset=event.offset)
    runtime_host.state_index.upsert_task_run(waiting_task)
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step=f"task_tool_approval_waiting:{step_index}",
        status="waiting_approval",
        summary="工具调用需要前端确认，任务已暂停等待确认。",
        refs={"observation_ref": observation_ref, "action_request_ref": action_request.request_id},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=waiting_task,
        item_type="interrupted_boundary",
        title="等待确认",
        status="waiting_approval",
        summary="工具调用需要前端确认，任务已暂停等待确认。",
        agent_brief_output=_observation_brief(observation),
        event_offset=_event_offset(event),
        refs={"task_run_ref": task_run.task_run_id, "observation_ref": observation_ref, "action_request_ref": action_request.request_id},
        payload={"pending_approval": pending_approval, "observation_event_offset": _event_offset(observation_event)},
    )
    return {
        "ok": False,
        "task_run": waiting_task.to_dict(),
        "lifecycle": updated_lifecycle.to_dict(),
        "event": event.to_dict() if hasattr(event, "to_dict") else dict(event or {}),
        "error": "waiting_approval",
        "retryable": True,
        "pending_approval": pending_approval,
    }


def _pause_executor_for_repeated_admission_denial(
    runtime_host: Any,
    *,
    task_run: Any,
    agent_run: Any,
    action_request: AnyModelActionRequest,
    admission: Any,
    observation: dict[str, Any],
    repeat_count: int,
) -> dict[str, Any]:
    now = time.time()
    observation_payload = dict(observation.get("payload") or {})
    admission_payload = admission.to_dict() if hasattr(admission, "to_dict") else dict(admission or {})
    observation_ref = str(observation.get("observation_id") or observation.get("observation_ref") or "")
    previous_refs = [
        str(item)
        for item in list(observation_payload.get("previous_observation_refs") or [])
        if str(item)
    ]
    recoverable_error = {
        "error_code": "repeated_admission_denial",
        "retryable": True,
        "repeat_count": int(repeat_count or 0),
        "observation_ref": observation_ref,
        "previous_observation_refs": previous_refs,
        "admission": admission_payload,
        "rejected_action_request": action_request.to_dict(),
        "user_message": "模型连续重复同一个未获准动作，任务保持可恢复状态，等待新的边界、权限或用户补充要求后继续。",
    }
    paused_task = replace(
        task_run,
        status="waiting_executor",
        updated_at=now,
        terminal_reason="",
        diagnostics={
            **_strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
            "executor_status": "waiting_executor",
            "wait_reason": "repeated_admission_denial",
            "recoverable_error": recoverable_error,
            "recovery_action": "resume_task_run",
            "latest_step": "task_executor_repeated_admission_denial",
            "latest_step_status": "waiting_executor",
            "latest_step_summary": "模型连续重复同一个未获准动作，当前工作等待新的边界或补充要求后继续。",
            "latest_observation_ref": observation_ref,
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status="failed",
            updated_at=now,
            diagnostics={**dict(agent_run.diagnostics or {}), "terminal_reason": "repeated_admission_denial", "recoverable_error": recoverable_error},
        )
    )
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_executor_repeated_admission_denial_paused",
        payload={"task_run": paused_task.to_dict(), "observation": observation, "repeat_count": int(repeat_count or 0)},
        refs={"task_run_ref": task_run.task_run_id, "action_request_ref": action_request.request_id, "observation_ref": observation_ref},
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_executor_repeated_admission_denial",
        status="waiting_executor",
        summary="模型连续重复同一个未获准动作，当前工作等待新的边界或补充要求后继续。",
        refs={"observation_ref": observation_ref, "action_request_ref": action_request.request_id},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=replace(paused_task, latest_event_offset=event.offset, updated_at=event.created_at or now),
        item_type="pause_boundary",
        title="等待调整",
        status="waiting_executor",
        summary="模型连续重复同一个未获准动作，当前工作等待新的边界或补充要求后继续。",
        event_offset=event.offset,
        refs={"task_run_ref": task_run.task_run_id, "observation_ref": observation_ref},
        payload={"terminal_reason": "repeated_admission_denial", "recoverable_error": recoverable_error},
    )
    return {"ok": False, "task_run": paused_task.to_dict(), "error": "repeated_admission_denial", "retryable": True}


def _pause_executor_for_step_budget(runtime_host: Any, *, task_run: Any, agent_run: Any, max_steps: int) -> dict[str, Any]:
    now = time.time()
    public_status = "本轮步骤预算已用尽，任务已停在可续跑边界；继续后会从当前任务状态恢复。"
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
        terminal_reason="",
        diagnostics={
            **_strip_terminal_diagnostics(dict(task_run.diagnostics or {})),
            "executor_status": "waiting_executor",
            "wait_reason": "task_execution_step_budget_exhausted",
            "recoverable_error": payload,
            "recovery_action": "rerun_task_executor",
            "latest_step": "task_executor_waiting_next_run",
            "latest_step_status": "waiting_executor",
            "latest_step_summary": public_status,
            "latest_public_status": public_status,
            "latest_public_progress_note": public_status,
            "latest_public_action_state": {
                "current_judgment": public_status,
                "next_action": "等待用户继续或调度器续跑当前任务。",
                "completion_status": "blocked",
            },
            "latest_current_judgment": public_status,
            "latest_next_action": "等待用户继续或调度器续跑当前任务。",
            "latest_completion_status": "blocked",
        },
    )
    runtime_host.state_index.upsert_task_run(paused_task)
    runtime_host.state_index.upsert_agent_run(
        replace(
            agent_run,
            status="failed",
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
    observation = _budget_exhausted_runtime_control_observation(
        task_run=replace(paused_task, latest_event_offset=budget_event.offset, updated_at=budget_event.created_at or now),
        max_steps=int(max_steps or _MAX_TASK_EXECUTION_STEPS),
        event_offset=budget_event.offset,
    )
    control_signal_id, control_event_ref = _publish_step_budget_control_signal(
        runtime_host,
        task_run=replace(paused_task, latest_event_offset=budget_event.offset, updated_at=budget_event.created_at or now),
        observation=observation,
        budget_event=budget_event,
        max_steps=int(max_steps or _MAX_TASK_EXECUTION_STEPS),
    )
    if not control_signal_id:
        latest_task = runtime_host.state_index.get_task_run(task_run.task_run_id) or paused_task
        return {"ok": False, "task_run": latest_task.to_dict(), "error": "runtime_gateway_control_signal_unavailable", "retryable": True}
    if control_signal_id:
        observation = {
            **observation,
            "payload": {
                **dict(observation.get("payload") or {}),
                "runtime_control_signal_ref": control_signal_id,
                "runtime_control_event_ref": control_event_ref,
            },
        }
    observed_event = _mark_step_budget_control_signal_observed(
        runtime_host,
        task_run=paused_task,
        observation=observation,
        observation_event=None,
        budget_event=budget_event,
        signal_id=control_signal_id,
    )
    if observed_event is None:
        latest_task = runtime_host.state_index.get_task_run(task_run.task_run_id) or paused_task
        return {
            "ok": False,
            "task_run": latest_task.to_dict(),
            "error": "runtime_gateway_control_signal_observation_unavailable",
            "retryable": True,
        }
    runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
    signal_event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_runtime_control_signal_observed",
        payload={"observation": observation, "control": _runtime_control_payload(paused_task, runtime_host=runtime_host)},
        refs={
            "task_run_ref": task_run.task_run_id,
            "observation_ref": observation["observation_id"],
            "runtime_invocation_packet_ref": str(dict(getattr(task_run, "diagnostics", {}) or {}).get("active_packet_ref") or ""),
        },
    )
    _record_task_step_summary(
        runtime_host,
        task_run_id=task_run.task_run_id,
        step="task_executor_waiting_next_run",
        status="waiting_executor",
        summary=public_status,
        public_progress_note=public_status,
        current_judgment=public_status,
        next_action="等待用户继续或调度器续跑当前任务。",
        completion_status="blocked",
        presentation_source="runtime.step_budget_exhausted",
        refs={"observation_ref": observation["observation_id"]},
    )
    append_work_rollout_item(
        runtime_host,
        task_run=replace(paused_task, latest_event_offset=signal_event.offset, updated_at=signal_event.created_at or budget_event.created_at or now),
        item_type="pause_boundary",
        title="等待继续",
        status="waiting_executor",
        summary=public_status,
        event_offset=signal_event.offset,
        refs={"task_run_ref": task_run.task_run_id, "observation_ref": observation["observation_id"]},
        payload={
            "terminal_reason": "task_execution_step_budget_exhausted",
            "model_visible": True,
            "runtime_control_signal": dict(observation.get("payload") or {}),
        },
    )
    latest_task = runtime_host.state_index.get_task_run(task_run.task_run_id) or paused_task
    return {"ok": False, "task_run": latest_task.to_dict(), "error": "task_execution_step_budget_exhausted", "retryable": True}


def _publish_step_budget_control_signal(
    runtime_host: Any,
    *,
    task_run: Any,
    observation: dict[str, Any],
    budget_event: Any,
    max_steps: int,
) -> tuple[str, str]:
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    publish = getattr(runtime_gateway, "publish", None)
    if not callable(publish):
        return "", ""
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    if not task_run_id:
        return "", ""
    payload = dict(observation.get("payload") or {})
    fingerprint = str(payload.get("runtime_control_signal_fingerprint") or "")
    signal_id = _step_budget_control_signal_id(task_run_id=task_run_id, fingerprint=fingerprint, max_steps=max_steps)
    scope_payload = _agent_run_scope_payload(task_run)
    scope = RuntimeSignalScope(
        session_id=str(getattr(task_run, "session_id", "") or scope_payload.get("session_id") or ""),
        task_run_id=task_run_id,
        agent_run_id=str(scope_payload.get("agent_run_id") or ""),
        run_cell_id=str(scope_payload.get("run_cell_id") or ""),
        turn_id=str(scope_payload.get("turn_id") or ""),
        turn_run_id=str(scope_payload.get("turn_run_id") or ""),
    )
    try:
        event = publish(
            task_run_id,
            signal_type="control.signal.requested",
            signal_id=signal_id,
            scope=scope,
            source_authority="harness.loop.task_executor.step_budget_boundary",
            payload={
                "signal_kind": "budget_exhausted",
                "task_run_id": task_run_id,
                "executor_epoch": int(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_epoch") or 0),
                "reason": "task_execution_step_budget_exhausted",
                "requested_by": "system",
                "requested_at": float(payload.get("requested_at") or time.time()),
                "boundary": "task_execution_step_budget",
                "runtime_control_signal_fingerprint": fingerprint,
                "observation_ref": str(observation.get("observation_id") or ""),
                "max_steps": int(max_steps or _MAX_TASK_EXECUTION_STEPS),
                "adapter": "task_executor_step_budget",
            },
            visibility="runtime_private",
            refs={
                "task_run_ref": task_run_id,
                "observation_ref": str(observation.get("observation_id") or ""),
                "budget_event_ref": str(getattr(budget_event, "event_id", "") or ""),
                "runtime_invocation_packet_ref": str(dict(getattr(task_run, "diagnostics", {}) or {}).get("active_packet_ref") or ""),
            },
        )
    except Exception:
        return "", ""
    signal = dict(dict(getattr(event, "payload", {}) or {}).get("signal") or {})
    return str(signal.get("signal_id") or signal_id), str(getattr(event, "event_id", "") or "")


def _mark_step_budget_control_signal_observed(
    runtime_host: Any,
    *,
    task_run: Any,
    observation: dict[str, Any],
    observation_event: Any,
    budget_event: Any,
    signal_id: str,
) -> Any | None:
    normalized_signal_id = str(signal_id or "").strip()
    if not normalized_signal_id:
        return None
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    marker = getattr(runtime_gateway, "mark_observed_by_id", None)
    if not callable(marker):
        return None
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    try:
        return marker(
            task_run_id,
            signal_id=normalized_signal_id,
            observed_by="harness.loop.task_executor.step_budget_boundary",
            payload={
                "observation_ref": str(observation.get("observation_id") or ""),
                "task_runtime_control_event_ref": str(getattr(observation_event, "event_id", "") or ""),
                "budget_event_ref": str(getattr(budget_event, "event_id", "") or ""),
                "boundary": "task_execution_step_budget",
                "runtime_control_signal_fingerprint": str(
                    dict(observation.get("payload") or {}).get("runtime_control_signal_fingerprint") or ""
                ),
            },
            refs={
                "task_run_ref": task_run_id,
                "observation_ref": str(observation.get("observation_id") or ""),
                "task_runtime_control_event_ref": str(getattr(observation_event, "event_id", "") or ""),
                "budget_event_ref": str(getattr(budget_event, "event_id", "") or ""),
            },
        )
    except Exception:
        return None


def _step_budget_control_signal_id(*, task_run_id: str, fingerprint: str, max_steps: int) -> str:
    digest = _stable_hash(
        {
            "task_run_id": str(task_run_id or ""),
            "fingerprint": str(fingerprint or ""),
            "max_steps": int(max_steps or _MAX_TASK_EXECUTION_STEPS),
            "signal_kind": "budget_exhausted",
        }
    )[:24]
    return f"control-signal:budget-exhausted:{digest}"


def _budget_exhausted_runtime_control_observation(*, task_run: Any, max_steps: int, event_offset: int | float) -> dict[str, Any]:
    now = time.time()
    instruction = (
        "本轮任务执行步骤预算已用尽。当前 task_run 已停在 waiting_executor 可续跑边界。"
        "你需要在下一次恢复时先吸收这条预算边界观察，说明已完成进度和下一步；不要把它误判为动作格式修复失败或最终阻塞。"
    )
    fingerprint = "sha256:" + _stable_hash(
        {
            "task_run_id": str(getattr(task_run, "task_run_id", "") or ""),
            "event_offset": int(event_offset or 0),
            "signal_kind": "budget_exhausted",
            "max_steps": int(max_steps or _MAX_TASK_EXECUTION_STEPS),
        }
    )
    return {
        "observation_id": f"rtobs:{task_run.task_run_id}:budget-exhausted:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run.task_run_id,
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "request_ref": f"runtime-control-signal:{task_run.task_run_id}:budget-exhausted:{int(event_offset or 0)}",
        "directive_ref": str(dict(getattr(task_run, "diagnostics", {}) or {}).get("active_packet_ref") or ""),
        "content_chars": len(instruction),
        "summary": instruction,
        "payload": {
            "signal_kind": "budget_exhausted",
            "runtime_control_state": "waiting_executor",
            "requested_by": "system",
            "requested_at": now,
            "reason": "task_execution_step_budget_exhausted",
            "boundary": "task_execution_step_budget",
            "runtime_control_signal_fingerprint": fingerprint,
            "agent_closeout_required": False,
            "allowed_agent_actions": ["respond", "ask_user", "block", "tool_call"],
            "tool_calls_allowed_after_signal": True,
            "repair_instruction": instruction,
            "structured_signal": {
                "code": "runtime_control_budget_exhausted",
                "message": instruction,
                "origin": "task_execution_step_budget_boundary",
                "retryable": True,
            },
            "max_steps": int(max_steps or _MAX_TASK_EXECUTION_STEPS),
        },
        "needs_model_followup": True,
        "created_at": now,
        "authority": "orchestration.runtime_observation",
    }


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


def _agent_run_scope_payload(task_run: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    scope = diagnostics.get("agent_run_scope")
    if isinstance(scope, dict):
        return dict(scope)
    return {
        "agent_run_id": str(diagnostics.get("agent_run_id") or ""),
        "run_cell_id": str(diagnostics.get("run_cell_id") or ""),
    }


def _task_tool_observation_scope_status(
    runtime_host: Any,
    *,
    task_run: Any,
    observation: dict[str, Any],
) -> dict[str, Any]:
    scope = _task_tool_observation_scope_payload(task_run=task_run, observation=observation)
    return _agent_cell_scope_status(
        runtime_host,
        task_run_id=str(scope.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
        agent_run_id=str(scope.get("agent_run_id") or ""),
        run_cell_id=str(scope.get("run_cell_id") or ""),
    )


def _trusted_tool_observation_identity_source(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result_envelope = dict(payload.get("result_envelope") or {})
    if result_envelope:
        return result_envelope, dict(result_envelope.get("execution_receipt") or {})
    return payload, dict(payload.get("execution_receipt") or {})


def _task_tool_observation_scope_payload(*, task_run: Any, observation: dict[str, Any]) -> dict[str, str]:
    payload = dict((observation or {}).get("payload") or {})
    identity_source, execution_receipt = _trusted_tool_observation_identity_source(payload)
    return {
        "task_run_id": str(
            execution_receipt.get("task_run_id")
            or identity_source.get("task_run_id")
            or (observation or {}).get("task_run_id")
            or getattr(task_run, "task_run_id", "")
            or ""
        ).strip(),
        "agent_run_id": str(
            execution_receipt.get("agent_run_id")
            or identity_source.get("agent_run_id")
            or ""
        ).strip(),
        "run_cell_id": str(
            execution_receipt.get("run_cell_id")
            or ""
        ).strip(),
    }


def _agent_cell_scope_status(
    runtime_host: Any,
    *,
    task_run_id: str,
    agent_run_id: str = "",
    run_cell_id: str = "",
) -> dict[str, Any]:
    normalized_task_run_id = str(task_run_id or "").strip()
    normalized_agent_run_id = str(agent_run_id or "").strip()
    normalized_run_cell_id = str(run_cell_id or "").strip()
    if not normalized_run_cell_id:
        return {
            "accepted": True,
            "reason": "run_cell_scope_unscoped",
            "active_scope": {},
            "rejected_scope": {},
            "authority": "harness.runtime.agent_run_supervisor.current_cell_gate",
        }
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    checker = getattr(supervisor, "current_scope_status_for_task_run", None)
    if not callable(checker):
        return {
            "accepted": False,
            "reason": "agent_scope_gate_unavailable",
            "active_scope": {},
            "rejected_scope": {
                "task_run_id": normalized_task_run_id,
                "agent_run_id": normalized_agent_run_id,
                "run_cell_id": normalized_run_cell_id,
            },
            "authority": "harness.runtime.agent_run_supervisor.current_cell_gate",
        }
    return dict(
        checker(
            normalized_task_run_id,
            agent_run_id=normalized_agent_run_id,
            run_cell_id=normalized_run_cell_id,
        )
        or {}
    )


def _record_late_task_tool_observation_rejected(
    runtime_host: Any,
    *,
    task_run: Any,
    row: dict[str, Any],
    observation: dict[str, Any],
    packet_ref: str,
    tool_batch_ref: str,
    group: ToolBatchGroup,
    scope_status: dict[str, Any],
) -> Any | None:
    scope = _task_tool_observation_scope_payload(task_run=task_run, observation=observation)
    action_request = row.get("action_request")
    tool_call = dict(getattr(action_request, "tool_call", {}) or row.get("tool_call") or {})
    payload = dict((observation or {}).get("payload") or {})
    identity_source, execution_receipt = _trusted_tool_observation_identity_source(payload)
    result_envelope = dict(payload.get("result_envelope") or {})
    tool_call_id = str(_canonical_tool_call_id(action_request) if action_request is not None else "").strip()
    if not tool_call_id:
        tool_call_id = str(identity_source.get("tool_call_id") or execution_receipt.get("tool_call_id") or "").strip()
    late_payload = {
        "observation_id": str((observation or {}).get("observation_id") or ""),
        "request_ref": str(
            getattr(action_request, "request_id", "")
            or identity_source.get("action_request_id")
            or identity_source.get("request_ref")
            or execution_receipt.get("request_ref")
            or ""
        ),
        "tool_name": str(tool_call.get("tool_name") or tool_call.get("name") or identity_source.get("tool_name") or ""),
        "tool_call_id": tool_call_id,
        "status": _observation_status(observation),
        "result_ref": str(identity_source.get("result_ref") or execution_receipt.get("result_ref") or ""),
        "content_chars": int((observation or {}).get("content_chars") or len(str(payload.get("text") or ""))),
        "packet_ref": str(packet_ref or ""),
        "tool_batch_ref": str(tool_batch_ref or ""),
        "tool_batch_group": group.to_dict() if hasattr(group, "to_dict") else {},
    }
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    recorder = getattr(supervisor, "record_late_event_rejected", None)
    refs = {
        "task_run_ref": str(scope.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
        "runtime_invocation_packet_ref": str(packet_ref or ""),
        "tool_batch_ref": str(tool_batch_ref or ""),
        "action_request_ref": str(getattr(action_request, "request_id", "") or ""),
        "observation_ref": late_payload["observation_id"],
        "agent_run_ref": str(scope.get("agent_run_id") or ""),
        "run_cell_ref": str(scope.get("run_cell_id") or ""),
    }
    if callable(recorder):
        return recorder(
            task_run_id=str(scope.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
            session_id=str(scope.get("session_id") or getattr(task_run, "session_id", "") or ""),
            agent_run_id=str(scope.get("agent_run_id") or ""),
            run_cell_id=str(scope.get("run_cell_id") or ""),
            event_kind="tool_observation",
            reason=str(scope_status.get("reason") or "stale_agent_cell"),
            payload=late_payload,
            refs=refs,
            scope_status=scope_status,
        )
    return runtime_host.event_log.append(
        str(scope.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
        "agent_runtime_cell_late_event_rejected",  # type: ignore[arg-type]
        payload={
            "task_run_id": str(scope.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
            "event_kind": "tool_observation",
            "reason": str(scope_status.get("reason") or "stale_agent_cell"),
            "scope_status": dict(scope_status or {}),
            "payload": late_payload,
            "authority": "harness.runtime.agent_run_supervisor.current_cell_gate",
        },
        refs=refs,
    )


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


def _file_state_projection_from_store(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    task_id = str(task_run_id or "").strip()
    if not task_id:
        return []
    store = getattr(runtime_host, "file_state_store", None)
    if store is None:
        root_dir = getattr(runtime_host, "root_dir", None)
        if root_dir is None:
            return []
        store = FileStateAuthorityStore(Path(root_dir))
    snapshot = getattr(store, "snapshot_scope", None)
    if not callable(snapshot):
        return []
    return list(snapshot(task_run_file_evidence_scope(task_id), limit=20) or [])


def _observations_for_packet(
    runtime_host: Any,
    task_run_id: str,
    *,
    current_fingerprint: dict[str, Any],
    pending_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    existing_observations = _existing_observations(runtime_host, task_run_id)
    pending = list(pending_observations or [])
    task_run = getattr(runtime_host, "state_index", None).get_task_run(task_run_id) if getattr(runtime_host, "state_index", None) is not None else None
    start_context_handoff = load_turn_to_task_context_handoff(runtime_host, task_run) if task_run is not None else {}
    inherited_observations = (
        inherited_observations_for_packet(start_context_handoff)
        if not existing_observations and not pending
        else []
    )
    raw_observations = [*inherited_observations, *existing_observations, *pending]
    deduped = _dedupe_observations(raw_observations)
    records = [
        _tool_record_from_observation(observation, current_fingerprint=current_fingerprint)
        for observation in deduped
    ]
    projection = _build_execution_state_projection(records)
    pending_subagent_result_actions = merge_pending_subagent_result_actions(
        *[pending_subagent_result_actions_from_observation(observation) for observation in deduped],
        limit=12,
    )
    pending_subagent_result_actions = _filter_consumed_subagent_pending_actions(
        runtime_host,
        task_run_id,
        pending_subagent_result_actions,
    )
    if pending_subagent_result_actions:
        projection = {
            **projection,
            "pending_subagent_result_actions": pending_subagent_result_actions,
        }
    runtime_control_signals = _runtime_control_signal_projection_from_observations(
        deduped,
        runtime_host=runtime_host,
        task_run_id=task_run_id,
    )
    if runtime_control_signals:
        projection = {
            **projection,
            "runtime_control_signals": runtime_control_signals,
            "latest_runtime_control_signal": runtime_control_signals[-1],
        }
    handoff_projection = handoff_summary(start_context_handoff)
    if handoff_projection:
        projection = {
            **projection,
            "turn_to_task_context_handoff": handoff_projection,
        }
    file_state = _file_state_projection_from_store(runtime_host, task_run_id)
    if file_state:
        projection = {
            **projection,
            "file_state": file_state,
            "file_state_source": "runtime.memory.file_state_store",
        }
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
        "artifact_refs": dedupe_artifact_refs(
            [
                dict(ref)
                for record in records
                if str(record.get("status") or "") == "ok" and _record_visibility(record) == "active"
                for ref in list(record.get("artifact_refs") or [])
                if isinstance(ref, dict)
            ]
        ),
    }


def _filter_consumed_subagent_pending_actions(
    runtime_host: Any,
    task_run_id: str,
    pending_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not pending_actions:
        return []
    state_index = getattr(runtime_host, "state_index", None)
    if state_index is None:
        return list(pending_actions)
    result: list[dict[str, Any]] = []
    for action in list(pending_actions or []):
        if str(action.get("action") or "") != "collect_subagent_result":
            result.append(action)
            continue
        args = dict(action.get("args") or {})
        subagent_run_ref = str(args.get("subagent_run_ref") or "").strip()
        result_ref = str(action.get("result_ref") or "").strip()
        if not subagent_run_ref:
            result.append(action)
            continue
        if _subagent_result_already_read(
            state_index,
            parent_task_run_id=task_run_id,
            subagent_run_ref=subagent_run_ref,
            result_ref=result_ref,
        ):
            continue
        result.append(action)
    return result


def _subagent_result_already_read(
    state_index: Any,
    *,
    parent_task_run_id: str,
    subagent_run_ref: str,
    result_ref: str,
) -> bool:
    if result_ref:
        state_reader = getattr(state_index, "subagent_result_read_state", None)
        if callable(state_reader):
            try:
                return (
                    str(
                        state_reader(
                            parent_task_run_id=parent_task_run_id,
                            subagent_run_ref=subagent_run_ref,
                            result_ref=result_ref,
                        )
                        or ""
                    )
                    == "read"
                )
            except Exception:
                return False
    list_reads = getattr(state_index, "list_subagent_result_reads", None)
    if not callable(list_reads):
        return False
    try:
        reads = list_reads(parent_task_run_id)
    except Exception:
        return False
    for item in list(reads or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("subagent_run_ref") or "") != subagent_run_ref:
            continue
        if str(item.get("read_state") or "") != "read":
            continue
        if not result_ref or str(item.get("result_ref") or "") == result_ref:
            return True
    return False


def _runtime_control_signal_projection_from_observations(
    observations: list[dict[str, Any]],
    *,
    runtime_host: Any | None = None,
    task_run_id: str = "",
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in list(observations or []):
        if str(observation.get("source") or "") != "system:runtime_control_signal":
            continue
        payload = dict(observation.get("payload") or {})
        signal_ref = str(payload.get("runtime_control_signal_ref") or "").strip()
        if not signal_ref:
            continue
        if not _runtime_control_signal_ref_is_gateway_published(
            runtime_host,
            task_run_id=task_run_id,
            signal_ref=signal_ref,
        ):
            continue
        fingerprint = str(payload.get("runtime_control_signal_fingerprint") or observation.get("observation_id") or "")
        if fingerprint and fingerprint in seen:
            continue
        if fingerprint:
            seen.add(fingerprint)
        signals.append(
            {
                "observation_ref": str(observation.get("observation_id") or ""),
                "runtime_control_signal_ref": signal_ref,
                "signal_kind": str(payload.get("signal_kind") or ""),
                "runtime_control_state": str(payload.get("runtime_control_state") or ""),
                "requested_by": str(payload.get("requested_by") or ""),
                "requested_at": float(payload.get("requested_at") or 0.0),
                "reason": str(payload.get("reason") or ""),
                "steer_ref": str(payload.get("steer_ref") or ""),
                "boundary": str(payload.get("boundary") or ""),
                "agent_closeout_required": bool(payload.get("agent_closeout_required") is True),
                "tool_calls_allowed_after_signal": bool(payload.get("tool_calls_allowed_after_signal") is True),
                "repair_instruction": compact_text(payload.get("repair_instruction") or observation.get("summary") or "", limit=1200),
                "authority": "harness.loop.runtime_control_signal_projection",
            }
        )
    return signals


def _runtime_control_signal_ref_is_gateway_published(
    runtime_host: Any | None,
    *,
    task_run_id: str,
    signal_ref: str,
) -> bool:
    normalized_task_run_id = str(task_run_id or "").strip()
    normalized_signal_ref = str(signal_ref or "").strip()
    if not normalized_task_run_id or not normalized_signal_ref:
        return False
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    signal_by_id = getattr(runtime_gateway, "signal_by_id", None)
    if not callable(signal_by_id):
        return _runtime_control_signal_ref_exists_in_event_log(
            runtime_host,
            task_run_id=normalized_task_run_id,
            signal_ref=normalized_signal_ref,
        )
    try:
        if signal_by_id(normalized_task_run_id, signal_id=normalized_signal_ref) is not None:
            return True
    except Exception:
        pass
    return _runtime_control_signal_ref_exists_in_event_log(
        runtime_host,
        task_run_id=normalized_task_run_id,
        signal_ref=normalized_signal_ref,
    )


def _runtime_control_signal_ref_exists_in_event_log(
    runtime_host: Any | None,
    *,
    task_run_id: str,
    signal_ref: str,
) -> bool:
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    event_log = getattr(runtime_host, "event_log", None) or getattr(runtime_gateway, "event_log", None)
    list_events = getattr(event_log, "list_events", None)
    if not callable(list_events):
        return False
    try:
        events = list_events(task_run_id)
    except Exception:
        return False
    for event in list(events or []):
        if str(getattr(event, "event_type", "") or "") != "runtime_control_signal_published":
            continue
        signal = dict(dict(getattr(event, "payload", {}) or {}).get("signal") or {})
        if str(signal.get("signal_id") or "") == signal_ref:
            return True
    return False


def _steer_for_projection(steer: dict[str, Any]) -> dict[str, Any]:
    payload = {
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
    editor_context = _steer_editor_context_projection(steer.get("editor_context"))
    if editor_context:
        payload["editor_context"] = editor_context
    return payload


def _steer_editor_context_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    active_file = _steer_active_file_projection(value.get("active_file"))
    visible_files = []
    for item in list(value.get("visible_files") or [])[:12]:
        if not isinstance(item, dict):
            continue
        path = compact_text(item.get("path") or item.get("uri") or "", limit=500)
        if not path:
            continue
        visible_files.append({
            "path": path,
            "label": compact_text(item.get("label") or "", limit=240),
            "language_id": compact_text(item.get("language_id") or item.get("languageId") or "", limit=80),
            "dirty": bool(item.get("dirty") is True),
        })
    open_tabs = []
    seen_open_tabs: set[str] = set()
    for item in list(value.get("open_tabs") or [])[:24]:
        if not isinstance(item, dict):
            continue
        path = compact_text(item.get("path") or item.get("uri") or "", limit=500)
        key = path.replace("\\", "/").rstrip("/").lower()
        if not path or key in seen_open_tabs:
            continue
        seen_open_tabs.add(key)
        open_tabs.append({
            "path": path,
            "label": compact_text(item.get("label") or "", limit=240),
            "language_id": compact_text(item.get("language_id") or item.get("languageId") or "", limit=80),
            "dirty": bool(item.get("dirty") is True),
            "active": bool(item.get("active") is True),
            "visible": bool(item.get("visible") is True),
        })
    workspace_roots = [
        compact_text(item, limit=500)
        for item in list(value.get("workspace_roots") or [])[:4]
        if compact_text(item, limit=500)
    ]
    payload = {
        "source": compact_text(value.get("source") or "editor", limit=80),
        "captured_at": compact_text(value.get("captured_at") or "", limit=80),
        "workspace_roots": workspace_roots,
        "active_file": active_file,
        "visible_files": visible_files,
        "open_tabs": open_tabs,
        "notes": [
            "This editor context belongs only to this pending user steer.",
            "It is contextual evidence, not a file permission grant.",
            "Dirty or preview content must be verified before editing or making file-content claims.",
        ],
        "authority": "harness.loop.active_task_steer.editor_context_projection",
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _steer_active_file_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    selection = value.get("selection") if isinstance(value.get("selection"), dict) else {}
    content_preview = value.get("content_preview") if isinstance(value.get("content_preview"), dict) else {}
    payload = {
        "path": compact_text(value.get("path") or value.get("uri") or "", limit=500),
        "label": compact_text(value.get("label") or "", limit=240),
        "language_id": compact_text(value.get("language_id") or value.get("languageId") or "", limit=80),
        "dirty": bool(value.get("dirty") is True),
        "selection": _steer_text_range_projection(selection, text_limit=12000),
        "content_preview": _steer_text_range_projection(content_preview, text_limit=12000),
    }
    return {key: item for key, item in payload.items() if item not in ("", {}, None)}


def _steer_text_range_projection(value: Any, *, text_limit: int) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    text = str(value.get("text") or "")
    payload = {
        "start": value.get("start") if isinstance(value.get("start"), dict) else {},
        "end": value.get("end") if isinstance(value.get("end"), dict) else {},
        "text": text[: max(1, int(text_limit or 12000))],
        "truncated": bool(value.get("truncated") is True or len(text) > int(text_limit or 12000)),
        "source": compact_text(value.get("source") or "", limit=80),
    }
    return {key: item for key, item in payload.items() if item not in ("", {}, None)}


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


def _consumed_steer_ids(action_request: AnyModelActionRequest, included_steer_ids: list[str]) -> list[str]:
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


def _contract_revision_decisions(action_request: AnyModelActionRequest) -> list[dict[str, Any]]:
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
    elif status == "ok" and str(observation.get("observation_type") or "") == "tool_result":
        record["status"] = "ok"
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


_EXPLORATION_ADVISORY_TOOLS = frozenset(
    {
        "glob_paths",
        "list_dir",
        "path_exists",
        "read_file",
        "read_structured_file",
        "search_files",
        "search_text",
        "stat_path",
    }
)
_EXPLORATION_ADVISORY_THRESHOLD = 6


def _build_execution_state_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    current_facts: list[dict[str, Any]] = []
    artifact_evidence: list[dict[str, Any]] = []
    active_failures: list[dict[str, Any]] = []
    historical_failures: list[dict[str, Any]] = []
    repair_focus: list[dict[str, Any]] = []
    last_action_receipts: list[dict[str, Any]] = []
    authoritative_subagent_results: list[dict[str, Any]] = []
    for record in records:
        visibility = _record_visibility(record)
        status = str(record.get("status") or "ok")
        summary = _record_summary(record)
        result_metadata = dict(record.get("result_metadata") or {})
        subagent_result = dict(result_metadata.get("subagent_result") or {})
        receipt = {
            "observation_ref": str(record.get("observation_ref") or ""),
            "tool_name": str(record.get("tool_name") or ""),
            "status": status,
            "visibility": visibility,
            "path": _record_target_path(record),
            "summary": summary,
            "content_range": dict(result_metadata.get("content_range") or {}),
            "subagent_result": subagent_result,
            "tool_guidance": str(result_metadata.get("tool_guidance") or ""),
            "event_offset": record.get("event_offset"),
            "created_at": record.get("created_at"),
        }
        receipt = {key: value for key, value in receipt.items() if value not in ("", None, [], {})}
        last_action_receipts.append(receipt)
        if status == "ok":
            if subagent_result and str(record.get("tool_name") or "") == "collect_subagent_result":
                authoritative_subagent_results.append(receipt)
            if visibility == "active":
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
    projection = {
        "current_facts": current_facts[-12:],
        "artifact_evidence": dedupe_artifact_refs(artifact_evidence)[-20:],
        "active_failures": active_failures[-8:],
        "historical_failures": historical_failures[-8:],
        "repair_focus": repair_focus[-8:],
        "open_questions": [],
        "last_action_receipts": last_action_receipts[-12:],
        "authoritative_subagent_results": authoritative_subagent_results[-4:],
        "authority": "harness.task_observation_projection",
    }
    exploration_advisory = _exploration_advisory_from_records(records)
    if exploration_advisory:
        projection["exploration_advisory"] = exploration_advisory
    return projection


def _exploration_advisory_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    streak: list[dict[str, Any]] = []
    for record in reversed(list(records or [])):
        if _record_visibility(record) != "active":
            continue
        tool_name = str(record.get("tool_name") or "").strip()
        if tool_name not in _EXPLORATION_ADVISORY_TOOLS:
            break
        streak.append(record)
    if len(streak) < _EXPLORATION_ADVISORY_THRESHOLD:
        return {}
    ordered = list(reversed(streak))
    return {
        "triggered": True,
        "kind": "large_scope_exploration_streak",
        "authority_boundary": "observation_pattern_only",
        "consecutive_exploration_tool_calls": len(ordered),
        "threshold": _EXPLORATION_ADVISORY_THRESHOLD,
        "recent_tools": [_exploration_record_projection(item) for item in ordered[-8:]],
        "decision_questions": [
            "还剩多少未探索的独立代码区域？",
            "哪些已有 observation 可以作为当前任务证据复用？",
            "是否需要更多读取、搜索、委派、实现、验证或收口，由模型根据任务合同自行裁决。",
        ],
        "non_blocking": True,
        "authority": "harness.task_observation_projection.exploration_advisory",
    }


def _exploration_record_projection(record: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "observation_ref": str(record.get("observation_ref") or ""),
        "tool_name": str(record.get("tool_name") or ""),
        "status": str(record.get("status") or "ok"),
        "path": _record_target_path(record),
        "summary": compact_text(_record_summary(record), limit=160),
    }
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


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


def _current_runtime_fingerprint(runtime_assembly: dict[str, Any], *, permission_mode: str, backend_config: dict[str, Any]) -> dict[str, Any]:
    profile = dict(runtime_assembly.get("profile") or {})
    environment = dict(runtime_assembly.get("task_environment") or {})
    config = _safe_backend_config(backend_config)
    return {
        "runtime_assembly_id": str(runtime_assembly.get("assembly_id") or ""),
        "agent_profile_id": str(runtime_assembly.get("agent_profile_ref") or ""),
        "runtime_profile_ref": str(profile.get("profile_ref") or ""),
        "task_environment_id": str(environment.get("environment_id") or ""),
        "tool_registry_hash": _stable_hash(_runtime_available_tools(runtime_assembly)),
        "tool_config_hash": _stable_hash(_tool_config_fingerprint(config)),
        "sandbox_policy_hash": _stable_hash(environment.get("sandbox_policy") or {}),
        "permission_policy_hash": _stable_hash(profile.get("permission_policy") or {}),
        "backend_config_hash": _stable_hash(config),
        "permission_mode": str(permission_mode or "").strip(),
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
    elif source == "system:agent_todo":
        source_name = "agent_todo"
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
                "artifact_refs": artifact_refs_from_event_payload({"observation": observation}),
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


def _is_approval_request_observation(observation: dict[str, Any]) -> bool:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    return (
        str(observation.get("observation_type") or "") == "approval_request"
        or str(payload.get("status") or "") == "needs_approval"
        or str(envelope.get("status") or "") == "needs_approval"
    )


def _approval_fingerprint_from_observation(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    diagnostics = dict(payload.get("diagnostics") or {})
    supervision = dict(diagnostics.get("supervision") or {})
    decision = dict(supervision.get("decision") or {})
    receipt = dict(supervision.get("receipt") or {})
    for value in (
        decision.get("approval_fingerprint"),
        receipt.get("approval_fingerprint"),
        diagnostics.get("approval_fingerprint"),
        payload.get("approval_risk_fingerprint"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _observation_status(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    tool_result = dict(structured.get("tool_result") or {}) if isinstance(structured.get("tool_result"), dict) else {}
    operation_gate = dict(payload.get("operation_gate") or {})
    if _is_approval_request_observation(observation):
        return "waiting_approval"
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
        structured_error = source.get("structured_error") if isinstance(source, dict) else None
        if isinstance(structured_error, dict) and structured_error:
            return _project_structured_error(
                structured_error,
                code=str(structured_error.get("code") or structured_error.get("error_code") or source.get("code") or "tool_error"),
                message=str(structured_error.get("message") or structured_error.get("detail") or structured_error),
                retryable=bool(structured_error.get("retryable", source.get("retryable", True))),
                origin=str(structured_error.get("origin") or source.get("origin") or "tool_provider"),
            )
        error = source.get("error") if isinstance(source, dict) else None
        if isinstance(error, dict):
            return _project_structured_error(
                error,
                code=str(error.get("code") or error.get("error_code") or source.get("code") or "tool_error"),
                message=str(error.get("message") or error.get("detail") or error),
                retryable=bool(error.get("retryable", source.get("retryable", True))),
                origin=str(error.get("origin") or source.get("origin") or "tool_provider"),
            )
    parsed_result = _json_payload(payload.get("result"))
    parsed_error = parsed_result.get("structured_error")
    if isinstance(parsed_error, dict) and parsed_error:
        return _project_structured_error(
            parsed_error,
            code=str(parsed_error.get("code") or parsed_result.get("error_code") or parsed_result.get("code") or "tool_error"),
            message=str(parsed_error.get("message") or parsed_result.get("error") or parsed_error),
            retryable=bool(parsed_error.get("retryable", parsed_result.get("retryable", True))),
            origin=str(parsed_error.get("origin") or _error_origin(observation)),
        )
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
            return _project_structured_error(
                structured_error,
                code=str(structured_error.get("code") or payload.get("error_code") or payload.get("code") or "tool_error"),
                message=str(structured_error.get("message") or message),
                retryable=bool(structured_error.get("retryable", payload.get("retryable", True))),
                origin=str(structured_error.get("origin") or _error_origin(observation)),
            )
        return {
            "code": str(payload.get("error_code") or payload.get("code") or "tool_error"),
            "message": message,
            "retryable": bool(payload.get("retryable", True)),
            "origin": _error_origin(observation),
        }
    status = _observation_status(observation)
    if status in {"failed", "denied", "canceled", "error"}:
        status_code = str(envelope.get("status") or tool_result.get("status") or payload.get("status") or status or "tool_error").strip()
        return {
            "code": status_code or "tool_error",
            "message": str(envelope.get("text") or payload.get("result") or tool_result.get("error") or status_code or "tool execution failed"),
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


def _project_structured_error(source: dict[str, Any], **defaults: Any) -> dict[str, Any]:
    payload = dict(defaults)
    for key in (
        "repair_instruction",
        "expected_ref_type",
        "expected_prefix",
        "received_ref_type",
    ):
        if str(source.get(key) or "").strip():
            payload[key] = str(source.get(key) or "").strip()
    if isinstance(source.get("provider_retryable"), bool):
        payload["provider_retryable"] = source.get("provider_retryable")
    if isinstance(source.get("agent_auto_retry_allowed"), bool):
        payload["agent_auto_retry_allowed"] = source.get("agent_auto_retry_allowed")
    if str(source.get("agent_retry_policy") or "").strip():
        payload["agent_retry_policy"] = str(source.get("agent_retry_policy") or "")
    if isinstance(source.get("max_agent_retry_attempts"), int):
        payload["max_agent_retry_attempts"] = source.get("max_agent_retry_attempts")
    if isinstance(source.get("suggested_retry_delay_seconds"), (int, float)):
        payload["suggested_retry_delay_seconds"] = source.get("suggested_retry_delay_seconds")
    attempts = [dict(item) for item in list(source.get("attempts") or []) if isinstance(item, dict)]
    if attempts:
        payload["attempts"] = attempts
    return payload


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


def _record_target_path(record: dict[str, Any]) -> str:
    args = dict(record.get("tool_args") or {})
    for key in ("path", "target_path", "artifact_path", "output_path"):
        value = str(args.get(key) or "").replace("\\", "/").strip().strip("/")
        if value:
            return value
    for key in ("observed_paths", "matched_paths"):
        values = [str(item or "").replace("\\", "/").strip().strip("/") for item in list(record.get(key) or [])]
        for value in values:
            if value:
                return value
    refs = [dict(item) for item in list(record.get("artifact_refs") or []) if isinstance(item, dict)]
    for ref in refs:
        value = str(ref.get("path") or ref.get("artifact_ref") or ref.get("src") or "").replace("\\", "/").strip().strip("/")
        if value:
            return value
    return ""


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


def _observation_public_step_summary(observation: dict[str, Any]) -> str:
    brief = _observation_brief(observation)
    if not brief:
        artifact_refs = _artifact_refs_from_observation(observation)
        return f"产生 {len(artifact_refs)} 个产物引用。" if artifact_refs else ""
    parsed = _json_payload(brief)
    if parsed:
        if parsed.get("ok") is False or parsed.get("error"):
            return ""
        for key in ("result", "summary", "output"):
            value = compact_text(str(parsed.get(key) or ""), limit=300)
            if value:
                return value
        artifact_refs = parsed.get("artifact_refs")
        if isinstance(artifact_refs, list) and artifact_refs:
            return f"产生 {len(artifact_refs)} 个产物引用。"
        return ""
    return brief


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
    image = dict(config.get("image_generation") or config.get("images") or config.get("image_assets") or {})
    return {
        "image_generation": {
            "base_url": str(image.get("base_url") or image.get("api_base") or ""),
            "model": str(image.get("model") or ""),
            "api_key_present": bool(image.get("api_key_present") or image.get("api_key") or image.get("key")),
        }
    }


def _tool_config_fingerprint(config: dict[str, Any]) -> dict[str, Any]:
    return dict(config.get("image_generation") or config.get("images") or config.get("image_assets") or {})


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


def _runtime_control_payload(task_run: Any, *, runtime_host: Any | None = None) -> dict[str, Any]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = diagnostics.get(_TASK_RUN_CONTROL_KEY)
    if not isinstance(control, dict):
        return {}
    signal_ref = str(control.get("runtime_control_signal_ref") or "").strip()
    event_ref = str(control.get("runtime_control_event_ref") or "").strip()
    state = _visible_task_run_control_state(task_run, control, runtime_host=runtime_host)
    return {
        "state": state,
        "requested_by": str(control.get("requested_by") or ""),
        "requested_at": float(control.get("requested_at") or 0.0),
        "reason": str(control.get("reason") or ""),
        "authority": "orchestration.task_run_control",
        **({"runtime_control_signal_ref": signal_ref} if signal_ref else {}),
        **({"runtime_control_event_ref": event_ref} if event_ref else {}),
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
    control_signal: ExecutorControlSignal | None = None,
) -> dict[str, Any]:
    control_payload = {
        "state": state,
        "requested_by": requested_by or "user",
        "requested_at": float(requested_at or time.time()),
        "reason": reason,
        "authority": "orchestration.task_run_control",
        **_executor_control_signal_trace_payload(control_signal),
    }
    return {
        **dict(diagnostics or {}),
        _TASK_RUN_CONTROL_KEY: control_payload,
        "latest_step": latest_step,
        "latest_step_status": latest_step_status,
        "latest_step_summary": latest_step_summary,
    }


def _completion_repair_observation(*, task_run_id: str, packet_ref: str, action_request: AnyModelActionRequest, verdict: dict[str, Any]) -> dict[str, Any]:
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


def _active_child_subagent_summaries(
    runtime_host: Any,
    *,
    task_run: Any,
    parent_agent_run: Any,
) -> list[dict[str, Any]]:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    parent_agent_run_ref = str(getattr(parent_agent_run, "agent_run_id", "") or "").strip()
    if not task_run_id or not parent_agent_run_ref:
        return []
    state_index = getattr(runtime_host, "state_index", None)
    snapshot_reader = getattr(state_index, "read_snapshot", None)
    if not callable(snapshot_reader):
        return []
    try:
        snapshot = dict(snapshot_reader() or {})
    except Exception:
        return []
    result: list[dict[str, Any]] = []
    for value in dict(snapshot.get("agent_runs") or {}).values():
        if not isinstance(value, dict):
            continue
        diagnostics = dict(value.get("diagnostics") or {})
        control = dict(diagnostics.get("subagent_control") or {})
        if str(control.get("parent_task_run_id") or "") != task_run_id:
            continue
        if str(value.get("parent_agent_run_ref") or "") != parent_agent_run_ref:
            continue
        if str(value.get("spawn_mode") or "") != "subagent":
            continue
        status = str(value.get("status") or "").strip()
        if status not in {"pending", "running"}:
            continue
        result.append(
            _drop_empty(
                {
                    "subagent_run_ref": str(value.get("agent_run_id") or ""),
                    "task_run_id": str(value.get("task_run_id") or ""),
                    "agent_id": str(value.get("agent_id") or ""),
                    "agent_profile_id": str(value.get("agent_profile_id") or ""),
                    "status": status,
                    "goal": str(control.get("goal") or ""),
                    "scheduler_status": str(control.get("scheduler_status") or ""),
                }
            )
        )
    result.sort(key=lambda item: (str(item.get("status") or ""), str(item.get("subagent_run_ref") or "")))
    return result


def _active_subagent_completion_repair_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    action_request: AnyModelActionRequest,
    active_subagents: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "observation_id": f"rtobs:{task_run_id}:active-subagent:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:task_completion_validator",
        "request_ref": action_request.request_id,
        "directive_ref": packet_ref,
        "content_chars": 0,
        "payload": {
            "error_code": "active_subagents_pending",
            "active_subagents": [dict(item) for item in active_subagents],
            "repair_instruction": (
                "父任务仍有未完成的子 Agent，不能直接完成。你需要调用 wait_subagent 或 list_subagents 观察进度；"
                "子 Agent 已完成时综合其 result/evidence 后再收口；确实不再需要时先 close_subagent 并说明原因。"
            ),
            "rejected_action_request": action_request.to_dict(),
        },
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "active_subagents_pending",
    }


def _active_steer_completion_repair_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    action_request: AnyModelActionRequest,
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


def _model_action_admission_recovery_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    action_request: AnyModelActionRequest,
    admission: Any,
    runtime_fingerprint: dict[str, Any],
    step_index: int,
    repeat_count: int = 1,
    previous_observations: list[dict[str, Any]] | None = None,
    pause_after_observation: bool = False,
) -> dict[str, Any]:
    previous_refs = [
        str(item.get("observation_id") or item.get("observation_ref") or "")
        for item in list(previous_observations or [])
        if str(item.get("observation_id") or item.get("observation_ref") or "")
    ]
    recovery = build_action_admission_recovery_payload(
        action_request=action_request,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
        repeat_count=repeat_count,
        previous_observation_refs=previous_refs,
        pause_after_observation=pause_after_observation,
    )
    is_repeated = int(repeat_count or 1) > 1
    ref_raw = json.dumps(
        {
            "task_run_id": task_run_id,
            "step_index": step_index,
            "request_ref": action_request.request_id,
            "fingerprint": recovery.admission_denial_fingerprint,
            **({"repeat_count": int(repeat_count or 0)} if is_repeated else {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    ref_digest = hashlib.sha256(ref_raw.encode("utf-8")).hexdigest()[:12]
    observation_kind = "admission-guard" if is_repeated else "admission"
    request_prefix = "repeated-model-action-admission" if is_repeated else "model-action-admission"
    return {
        "observation_id": f"rtobs:{task_run_id}:{observation_kind}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": recovery.observation_type,
        "source": recovery.source,
        "request_ref": f"{request_prefix}:{task_run_id}:invocation:{step_index}:{ref_digest}",
        "directive_ref": packet_ref,
        "content_chars": recovery.content_chars,
        "summary": recovery.summary,
        "payload": recovery.payload,
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": recovery.error_code,
    }


def _matching_model_action_admission_denial_observations(
    observations: list[dict[str, Any]],
    *,
    action_request: AnyModelActionRequest,
    admission: Any,
    runtime_fingerprint: dict[str, Any],
) -> list[dict[str, Any]]:
    admission_payload = admission.to_dict() if hasattr(admission, "to_dict") else dict(admission or {})
    current_fingerprint = action_admission_denial_fingerprint(
        action_request=action_request,
        admission_payload=admission_payload,
        runtime_fingerprint=runtime_fingerprint,
    )
    matches: list[dict[str, Any]] = []
    for observation in list(observations or []):
        if not isinstance(observation, dict):
            continue
        source = str(observation.get("source") or "")
        if source not in {"system:model_action_admission", "system:repeated_admission_guard"}:
            continue
        payload = dict(observation.get("payload") or {})
        stored_fingerprint = str(payload.get("admission_denial_fingerprint") or "")
        if stored_fingerprint:
            if stored_fingerprint == current_fingerprint:
                matches.append(dict(observation))
        continue
    return matches


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
    parse_diagnostics = _model_protocol_parse_diagnostics(diagnostics)
    response_diagnostics = _model_protocol_response_diagnostics(diagnostics)
    repair_instruction = _model_protocol_repair_instruction(
        validation_errors=errors,
        parse_diagnostics=parse_diagnostics,
        response_diagnostics=response_diagnostics,
    )
    repair_ref = _stable_model_protocol_repair_ref(
        task_run_id=task_run_id,
        step_index=step_index,
        validation_errors=errors,
        parse_diagnostics=parse_diagnostics,
        response_diagnostics=response_diagnostics,
        repair_instruction=repair_instruction,
    )
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": "system:model_action_protocol",
        "request_ref": repair_ref,
        "directive_ref": packet_ref,
        "content_chars": len(repair_instruction),
        "summary": repair_instruction,
        "payload": {
            "tool_name": "model_action_protocol",
            "tool_args": {},
            "error": message,
            "error_code": "model_action_invalid",
            "validation_errors": errors,
            "repair_instruction": repair_instruction,
            "parse_diagnostics": parse_diagnostics,
            "response_diagnostics": response_diagnostics,
            "structured_error": {
                "code": "model_action_invalid",
                "message": message,
                "retryable": True,
                "origin": "model_protocol",
                "repair_instruction": repair_instruction,
                "validation_errors": errors,
                "parse_diagnostics": parse_diagnostics,
                "response_diagnostics": response_diagnostics,
            },
            "runtime_fingerprint": dict(runtime_fingerprint or {}),
        },
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": "model_action_invalid",
    }


def _stable_model_protocol_repair_ref(
    *,
    task_run_id: str,
    step_index: int,
    validation_errors: list[str],
    parse_diagnostics: dict[str, Any],
    response_diagnostics: dict[str, Any],
    repair_instruction: str,
) -> str:
    raw = json.dumps(
        {
            "task_run_id": str(task_run_id or ""),
            "step_index": int(step_index or 0),
            "validation_errors": list(validation_errors or []),
            "parse_diagnostics": dict(parse_diagnostics or {}),
            "response_diagnostics": dict(response_diagnostics or {}),
            "repair_instruction": str(repair_instruction or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"model-action-protocol:{task_run_id}:invocation:{step_index}:{digest}"


def _model_protocol_repair_count(observations: list[dict[str, Any]]) -> int:
    return sum(1 for item in observations if str(item.get("source") or "") == "system:model_action_protocol")


def _executor_error_observation(
    *,
    task_run_id: str,
    request_ref: str,
    directive_ref: str,
    tool_name: str,
    tool_args: dict[str, Any],
    error: str,
    tool_call_id: str = "",
    admission_ref: str = "",
    action_lifecycle_ref: str = "",
    identity: Any | None = None,
    action_request: AnyModelActionRequest | None = None,
) -> dict[str, Any]:
    identity_payload = identity.to_dict() if hasattr(identity, "to_dict") else dict(identity or {})
    normalized_tool_call_id = str(identity_payload.get("tool_call_id") or tool_call_id or "").strip()
    normalized_admission_ref = str(identity_payload.get("admission_ref") or admission_ref or permission_decision_id(tool_call_id=normalized_tool_call_id)).strip()
    normalized_tool_name = str(identity_payload.get("tool_name") or tool_name or "").strip()
    normalized_tool_args = dict(identity_payload.get("tool_args") or tool_args or {})
    normalized_action_lifecycle_ref = str(
        identity_payload.get("action_lifecycle_ref")
        or action_lifecycle_ref
        or (f"action-lifecycle:{request_ref}" if request_ref else "")
    ).strip()
    normalized_tool_invocation_ref = str(identity_payload.get("invocation_id") or "").strip()
    normalized_agent_run_id = str(identity_payload.get("agent_run_id") or "").strip()
    normalized_run_cell_id = str(identity_payload.get("run_cell_id") or "").strip()
    diagnostics: dict[str, Any] = {}
    if action_request is not None:
        diagnostics["action_request"] = action_request.to_dict()
    if identity_payload:
        diagnostics["action_tool_invocation_identity"] = identity_payload
    if normalized_action_lifecycle_ref:
        diagnostics["action_lifecycle_ref"] = normalized_action_lifecycle_ref
    execution_receipt = {
        "task_run_id": task_run_id,
        "tool_call_id": normalized_tool_call_id,
        "admission_ref": normalized_admission_ref,
    }
    if normalized_tool_invocation_ref:
        execution_receipt["tool_invocation_ref"] = normalized_tool_invocation_ref
    if normalized_action_lifecycle_ref:
        execution_receipt["action_lifecycle_ref"] = normalized_action_lifecycle_ref
    if normalized_agent_run_id:
        execution_receipt["agent_run_id"] = normalized_agent_run_id
    if normalized_run_cell_id:
        execution_receipt["run_cell_id"] = normalized_run_cell_id
    payload = {
        "tool_name": normalized_tool_name,
        "tool_args": normalized_tool_args,
        "error": error,
        "tool_call_id": normalized_tool_call_id,
        "action_request_ref": request_ref,
    }
    if normalized_tool_invocation_ref:
        payload["tool_invocation_ref"] = normalized_tool_invocation_ref
    if normalized_action_lifecycle_ref:
        payload["action_lifecycle_ref"] = normalized_action_lifecycle_ref
    if normalized_agent_run_id:
        payload["agent_run_id"] = normalized_agent_run_id
    if normalized_run_cell_id:
        payload["run_cell_id"] = normalized_run_cell_id
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "executor_error",
        "source": f"tool:{normalized_tool_name}",
        "request_ref": request_ref,
        "directive_ref": directive_ref,
        "tool_name": normalized_tool_name,
        "tool_call_id": normalized_tool_call_id,
        "execution_receipt": execution_receipt,
        "content_chars": len(error),
        "payload": payload,
        "diagnostics": diagnostics,
        "needs_model_followup": False,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": error,
    }


_DUPLICATE_GUARDED_READ_ONLY_TOOLS = frozenset(
    {
        "glob_paths",
        "list_dir",
        "path_exists",
        "read_file",
        "read_structured_file",
        "search_files",
        "search_text",
        "stat_path",
    }
)
_DUPLICATE_READ_ONLY_TOOL_CALL_LIMIT = 5


def _duplicate_read_only_tool_call_observation(
    *,
    task_run_id: str,
    packet_ref: str,
    action_request: AnyModelActionRequest,
    previous_observations: list[dict[str, Any]],
    runtime_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    tool_call = dict(action_request.tool_call or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    if tool_name not in _DUPLICATE_GUARDED_READ_ONLY_TOOLS:
        return None
    tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    fingerprint = _tool_call_fingerprint(tool_name, tool_args)
    previous_ok_refs: list[str] = []
    previous_failed_refs: list[str] = []
    for observation in list(previous_observations or []):
        if _tool_call_fingerprint(_observation_tool_name(observation), _observation_tool_args(observation)) != fingerprint:
            continue
        status = _observation_status(observation)
        if status == "ok":
            previous_ok_refs.append(str(observation.get("observation_id") or observation.get("observation_ref") or ""))
        elif status in {"failed", "denied", "canceled", "error"}:
            previous_failed_refs.append(str(observation.get("observation_id") or observation.get("observation_ref") or ""))
    if len(previous_ok_refs) < _DUPLICATE_READ_ONLY_TOOL_CALL_LIMIT and len(previous_failed_refs) < _DUPLICATE_READ_ONLY_TOOL_CALL_LIMIT:
        return None
    if not previous_ok_refs:
        if not previous_failed_refs:
            return None
        error_code = "duplicate_failed_read_only_tool_call"
        message = (
            f"相同参数的只读工具调用已连续失败 {len(previous_failed_refs)} 次：{tool_name}。"
            "请根据失败原因修改参数、换工具、缩小范围，或明确说明阻塞；不要继续原样重试。"
        )
        previous_refs = previous_failed_refs
        repair_instruction = (
            "The identical failed read-only tool call has reached the retry limit. "
            "Use the previous failure as evidence, change arguments or tool, or report the blocker."
        )
    else:
        error_code = "duplicate_read_only_tool_call"
        message = (
            f"相同参数的只读工具调用已达到 {len(previous_ok_refs)} 次：{tool_name}。"
            "请使用已有 observation 作为证据，或改用更有针对性的验证工具/参数；如果合同已满足，应直接 respond。"
        )
        previous_refs = previous_ok_refs
        repair_instruction = (
            "The identical read-only tool call has reached the repeat limit. "
            "Use the existing observation, change the verification method or arguments, or finish if completion evidence is sufficient."
        )
    return {
        "observation_id": f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}",
        "task_run_id": task_run_id,
        "observation_type": "runtime_guard",
        "source": "system:duplicate_tool_call_guard",
        "request_ref": action_request.request_id,
        "directive_ref": packet_ref,
        "content_chars": len(message),
        "summary": message,
        "payload": {
            "tool_name": "duplicate_tool_call_guard",
            "tool_args": {"tool_name": tool_name, "args": tool_args},
            "error": message,
            "error_code": error_code,
            "previous_observation_refs": [ref for ref in previous_refs if ref],
            "structured_error": {
                "code": error_code,
                "message": message,
                "retryable": True,
                "origin": "runtime_guard",
                "tool_name": tool_name,
                "tool_args": tool_args,
                "previous_observation_refs": [ref for ref in previous_refs if ref],
                "repair_instruction": repair_instruction,
            },
            "runtime_fingerprint": dict(runtime_fingerprint or {}),
        },
        "needs_model_followup": True,
        "created_at": time.time(),
        "authority": "orchestration.runtime_observation",
        "error": error_code,
    }


def _tool_call_fingerprint(tool_name: str, tool_args: dict[str, Any]) -> str:
    payload = json.dumps(
        {"tool_name": str(tool_name or ""), "args": _normalize_tool_call_args_for_fingerprint(tool_name, tool_args)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_tool_call_args_for_fingerprint(tool_name: str, tool_args: dict[str, Any]) -> Any:
    normalized = _normalize_tool_call_args(tool_args)
    if str(tool_name or "").strip() != "read_file" or not isinstance(normalized, dict):
        return normalized
    # The runtime supplies these defaults during validation. Include them in the
    # duplicate fingerprint so read_file(path) and read_file(path, start_line=1)
    # are treated as the same line window, while unsupported args remain visible
    # to the validator instead of being accepted as compatibility shims.
    defaults = read_window_fingerprint_defaults()
    if "start_line" not in normalized and not any(key in normalized for key in ("offset", "limit")):
        normalized["start_line"] = defaults["start_line"]
    if "line_count" not in normalized and not any(key in normalized for key in ("offset", "limit")):
        normalized["line_count"] = defaults["line_count"]
    return normalized


def _normalize_tool_call_args(tool_args: dict[str, Any]) -> Any:
    if isinstance(tool_args, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(tool_args):
            value = tool_args[key]
            if isinstance(value, str) and key in {"path", "target_path", "artifact_path", "output_path", "root", "roots", "paths"}:
                normalized[str(key)] = value.replace("\\", "/").strip().strip("/")
            else:
                normalized[str(key)] = _normalize_tool_call_args(value) if isinstance(value, dict) else value
        return normalized
    if isinstance(tool_args, list):
        return [_normalize_tool_call_args(item) if isinstance(item, (dict, list)) else str(item).replace("\\", "/").strip().strip("/") if isinstance(item, str) else item for item in tool_args]
    return tool_args


def _artifact_refs_from_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for observation in observations:
        refs.extend(_artifact_refs_from_observation(observation))
    return dedupe_artifact_refs(refs)


def _artifact_refs_from_observation(observation: dict[str, Any]) -> list[dict[str, Any]]:
    return artifact_refs_from_event_payload({"observation": observation})


def _artifacts_from_action(action_request: AnyModelActionRequest) -> list[dict[str, Any]]:
    diagnostics = dict(action_request.diagnostics or {})
    return [dict(item) for item in list(diagnostics.get("artifacts") or []) if isinstance(item, dict)]


def _normal_artifact_refs(value: Any) -> list[dict[str, Any]]:
    return dedupe_artifact_refs([normalize_artifact_ref(item) for item in list(value or [])])


def _artifact_ref_to_string(ref: Any) -> str:
    if isinstance(ref, dict):
        return artifact_ref_value(ref) or str(ref.get("url") or json.dumps(ref, ensure_ascii=False, sort_keys=True))
    return str(ref or "")


def _specialist_terminal_reason(*, execution: SpecialistRuntimeExecution, limitations: list[str]) -> str:
    if limitations:
        return limitations[0]
    route = str(execution.route or execution.runtime_kind or "specialist").strip()
    return f"{route}_failed" if route else "specialist_runtime_failed"


def _verified_artifacts(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    artifact_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run_id)
    project_root = _task_workspace_root(runtime_assembly, runtime_host=runtime_host)
    repository_verified, sandbox_candidates = _verified_repository_artifacts(
        runtime_assembly=runtime_assembly,
        sandbox_policy=sandbox_policy,
        project_root=project_root,
        artifact_refs=artifact_refs,
    )
    sandbox_verified = publish_sandbox_artifact_refs(
        project_root=project_root,
        sandbox_policy=sandbox_policy,
        artifact_refs=sandbox_candidates,
    )
    return dedupe_artifact_refs([*repository_verified, *sandbox_verified])


def _verified_repository_artifacts(
    *,
    runtime_assembly: dict[str, Any],
    sandbox_policy: dict[str, Any],
    project_root: Path,
    artifact_refs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    verified: list[dict[str, Any]] = []
    sandbox_candidates: list[dict[str, Any]] = []
    resolver: RepositoryRootResolver | None = None
    environment: Any | None = None
    file_policy: dict[str, Any] = {}
    for ref in dedupe_artifact_refs(artifact_refs):
        repository_id = str(ref.get("repository_id") or "").strip()
        if not repository_id:
            sandbox_candidates.append(ref)
            continue
        if environment is None:
            file_policy = _task_file_policy(runtime_assembly, sandbox_policy=sandbox_policy)
            environment = _resolve_file_policy_environment(file_policy)
            resolver = _file_repository_root_resolver(
                project_root=project_root,
                sandbox_policy=sandbox_policy,
                file_policy=file_policy,
            )
        resolved_ref = _resolve_repository_artifact_ref(
            ref,
            repository_id=repository_id,
            environment=environment,
            resolver=resolver,
        )
        if resolved_ref is not None:
            verified.append(resolved_ref)
            continue
        repository_kind = str(ref.get("repository_kind") or "").strip()
        if repository_kind == "sandbox_workspace":
            sandbox_candidates.append(ref)
    return dedupe_artifact_refs(verified), dedupe_artifact_refs(sandbox_candidates)


def _resolve_file_policy_environment(file_policy: dict[str, Any]) -> Any | None:
    profile_id = str(file_policy.get("profile_id") or "").strip()
    if not profile_id:
        return None
    try:
        return resolve_file_environment(
            profile_id,
            repository_requirements=dict(file_policy.get("repository_requirements") or {}),
        )
    except Exception:
        return None


def _file_repository_root_resolver(
    *,
    project_root: Path,
    sandbox_policy: dict[str, Any],
    file_policy: dict[str, Any],
) -> RepositoryRootResolver:
    managed_storage_root = _configured_root(
        file_policy.get("managed_storage_root"),
        project_root=project_root,
        default=project_root / ".managed-files",
    )
    runtime_output_root = _configured_root(
        file_policy.get("runtime_output_root"),
        project_root=project_root,
        default=managed_storage_root / "runtime",
    )
    sandbox_root = str(sandbox_policy.get("sandbox_root") or "").strip() or None
    return RepositoryRootResolver(
        project_root=project_root,
        sandbox_root=sandbox_root,
        managed_storage_root=managed_storage_root,
        runtime_output_root=runtime_output_root,
    )


def _configured_root(value: Any, *, project_root: Path, default: Path) -> Path:
    text = str(value or "").strip()
    if not text:
        return default.resolve()
    root = Path(text)
    return root.resolve() if root.is_absolute() else (project_root / root).resolve()


def _resolve_repository_artifact_ref(
    ref: dict[str, Any],
    *,
    repository_id: str,
    environment: Any | None,
    resolver: RepositoryRootResolver | None,
) -> dict[str, Any] | None:
    if environment is None or resolver is None:
        return None
    repository = environment.repository(repository_id)
    if repository is None:
        return None
    if repository.repository_kind == "sandbox_workspace":
        return None
    try:
        binding = resolver.resolve(repository)
    except Exception:
        return None
    logical_path = _repository_artifact_logical_path(ref, root=binding.root)
    if not logical_path:
        return None
    target = (binding.root / logical_path).resolve()
    if not _path_within(target, binding.root):
        return None
    if not target.exists() or not target.is_file():
        return None
    return {
        **dict(ref),
        "path": logical_path,
        "absolute_path": str(target),
        "exists": True,
        "size_bytes": target.stat().st_size,
        "published": True,
        "repository_id": repository.repository_id,
        "repository_kind": repository.repository_kind,
        "authority": "harness.loop.task_completion_artifact_verifier",
    }


def _repository_artifact_logical_path(ref: dict[str, Any], *, root: Path) -> str:
    for key in ("path", "published_path", "artifact_ref"):
        value = str(ref.get(key) or "").strip()
        if key == "artifact_ref":
            value = value.removeprefix("artifact:").strip()
        if not value:
            continue
        try:
            return normalize_logical_path(value)
        except Exception:
            continue
    absolute_path = str(ref.get("absolute_path") or "").strip()
    if not absolute_path:
        return ""
    try:
        target = Path(absolute_path).resolve()
        if _path_within(target, root):
            return target.relative_to(root).as_posix()
    except Exception:
        return ""
    return ""


def _path_within(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _discover_sandbox_artifact_refs(
    *,
    runtime_host: Any,
    runtime_assembly: dict[str, Any],
    task_run_id: str,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    sandbox_policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run_id)
    return discover_sandbox_artifact_refs(sandbox_policy=sandbox_policy, contract=contract)


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
    action_type: str = "",
    current_judgment: str = "",
    next_action: str = "",
    completion_status: str = "",
    open_risks: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    presentation_source: str = "",
    tool_status: str = "",
    tool_name: str = "",
    tool_target: str = "",
) -> dict[str, Any]:
    visible_summary = public_runtime_progress_summary(summary)
    visible_note = public_runtime_progress_summary(public_progress_note)
    visible_brief = public_runtime_progress_summary(agent_brief_output)
    visible_judgment = public_runtime_progress_summary(current_judgment)
    visible_next_action = public_runtime_progress_summary(next_action)
    visible_completion_status = public_runtime_progress_summary(completion_status)
    refs_record = dict(refs or {})
    payload = {"task_run_id": task_run_id, "step": step, "status": status, "summary": visible_summary}
    if str(action_type or "").strip():
        payload["action_type"] = str(action_type or "").strip()
    if visible_note:
        payload["public_progress_note"] = visible_note
    if visible_brief:
        payload["agent_brief_output"] = visible_brief
    public_action_state: dict[str, Any] = {
        key: value
        for key, value in {
            "current_judgment": visible_judgment,
            "next_action": visible_next_action,
            "completion_status": visible_completion_status,
        }.items()
        if value
    }
    risk_values = [public_runtime_progress_summary(item) for item in list(open_risks or []) if public_runtime_progress_summary(item)]
    ref_values = [str(item or "").strip() for item in list(evidence_refs or []) if str(item or "").strip()]
    if risk_values:
        public_action_state["open_risks"] = risk_values[:6]
    if ref_values:
        public_action_state["evidence_refs"] = ref_values[:8]
    if public_action_state:
        payload["public_action_state"] = public_action_state
        payload.update(
            {
                key: value
                for key, value in {
                    "current_judgment": visible_judgment,
                    "next_action": visible_next_action,
                    "completion_status": visible_completion_status,
                }.items()
                if value
            }
        )
    if presentation_source:
        payload["presentation_source"] = presentation_source
    feedback_identity = _step_summary_feedback_identity(
        presentation_source=presentation_source,
        refs=refs_record,
    )
    if feedback_identity:
        payload["feedback_identity"] = feedback_identity
    visible_tool_status = public_runtime_progress_summary(tool_status)
    if visible_tool_status:
        payload["tool_status"] = visible_tool_status
    if tool_name:
        payload["tool_name"] = str(tool_name or "").strip()
    if tool_target:
        payload["tool_target"] = public_runtime_progress_summary(tool_target)
    event = runtime_host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload=payload,
        refs={"task_run_ref": task_run_id, **refs_record},
    )
    current = runtime_host.state_index.get_task_run(task_run_id)
    if current is not None:
        diagnostics_update = _step_summary_diagnostics_update(
            step=step,
            status=status,
            summary=visible_summary,
            public_progress_note=visible_note,
            agent_brief_output=visible_brief,
            public_action_state=public_action_state,
            current_judgment=visible_judgment,
            next_action=visible_next_action,
            completion_status=visible_completion_status,
            presentation_source=presentation_source,
            tool_name=tool_name,
        )
        runtime_host.state_index.upsert_task_run(
            replace(
                current,
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                diagnostics={
                    **dict(current.diagnostics or {}),
                    **diagnostics_update,
                },
            )
        )
    return event.to_dict()


def _step_summary_feedback_identity(*, presentation_source: str, refs: dict[str, Any]) -> str:
    if not str(presentation_source or "").strip().startswith("model_action."):
        return ""
    for key in ("action_request_ref", "batch_action_request_ref", "runtime_invocation_packet_ref"):
        value = str(refs.get(key) or "").strip()
        if value:
            return value
    return ""


def _step_summary_diagnostics_update(
    *,
    step: str,
    status: str,
    summary: str,
    public_progress_note: str,
    agent_brief_output: str,
    public_action_state: dict[str, Any],
    current_judgment: str,
    next_action: str,
    completion_status: str,
    presentation_source: str,
    tool_name: str,
) -> dict[str, Any]:
    source = str(presentation_source or "").strip()
    update: dict[str, Any] = {
        "latest_step": step,
        "latest_step_status": status,
        "latest_step_summary": summary,
    }
    if source == "system.user_steer_status":
        update["latest_step_summary"] = ""
        return update
    if source == _PROTOCOL_REPAIR_PRESENTATION_SOURCE:
        update["latest_step_summary"] = ""
        return update
    if source in {"tool_observation.summary", "system.tool_call_status"}:
        trace = public_progress_note or agent_brief_output or summary
        if trace:
            update["latest_tool_observation_trace"] = trace
        return update
    if str(status or "").strip().lower() in {"error", "failed", "blocked", "denied", "canceled", "cancelled", "aborted"}:
        diagnostic = public_progress_note or agent_brief_output or summary
        if diagnostic:
            update["latest_failure_diagnostic"] = diagnostic
    public_status = public_progress_note or current_judgment or summary
    if public_status:
        update["latest_public_status"] = public_status
        update["latest_public_progress_note"] = public_status
    if agent_brief_output and tool_name != "agent_todo":
        update["agent_brief_output"] = agent_brief_output
    if public_action_state:
        update["latest_public_action_state"] = public_action_state
    if current_judgment:
        update["latest_model_judgment"] = current_judgment
        update["latest_current_judgment"] = current_judgment
    if next_action:
        update["latest_next_action"] = next_action
    if completion_status:
        update["latest_completion_status"] = completion_status
    if tool_name and tool_name not in {"read_file", "search_text", "search_files", "agent_todo", "read_persisted_tool_result"}:
        material = public_progress_note or agent_brief_output or summary
        if material:
            update["latest_material_progress"] = material
    return update


def _model_action_response_diagnostics(response: Any, *, model_selection: dict[str, Any]) -> dict[str, Any]:
    metadata = _safe_dict(getattr(response, "response_metadata", None))
    usage = _safe_dict(getattr(response, "usage_metadata", None))
    output_tokens = _first_int(
        usage.get("output_tokens"),
        usage.get("completion_tokens"),
        _safe_dict(metadata.get("token_usage")).get("completion_tokens"),
        _safe_dict(metadata.get("token_usage")).get("output_tokens"),
    )
    max_output_tokens = _first_int(dict(model_selection or {}).get("max_output_tokens"))
    return _drop_empty(
        {
            "finish_reason": str(metadata.get("finish_reason") or metadata.get("stop_reason") or ""),
            "output_tokens": output_tokens,
            "max_output_tokens": max_output_tokens,
            "output_limit_hit_suspected": bool(output_tokens and max_output_tokens and output_tokens >= max_output_tokens),
        }
    )


def _model_protocol_parse_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    raw = _safe_dict(dict(diagnostics or {}).get("parse_diagnostics"))
    return _drop_empty(
        {
            "parse_error": str(raw.get("parse_error") or ""),
            "parsed_type": str(raw.get("parsed_type") or ""),
            "content_chars": _first_int(raw.get("content_chars")),
            "raw_content_preview": compact_text(str(raw.get("raw_content_preview") or ""), limit=300),
            "starts_with": str(raw.get("starts_with") or ""),
            "ends_with": str(raw.get("ends_with") or ""),
        }
    )


def _model_protocol_response_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    raw = _safe_dict(dict(diagnostics or {}).get("response_diagnostics"))
    return _drop_empty(
        {
            "finish_reason": str(raw.get("finish_reason") or ""),
            "output_tokens": _first_int(raw.get("output_tokens")),
            "max_output_tokens": _first_int(raw.get("max_output_tokens")),
            "output_limit_hit_suspected": bool(raw.get("output_limit_hit_suspected") is True),
        }
    )


def _model_protocol_repair_instruction(
    *,
    validation_errors: list[str],
    parse_diagnostics: dict[str, Any],
    response_diagnostics: dict[str, Any],
) -> str:
    error_text = ", ".join(validation_errors) if validation_errors else "输出不是合法 action JSON"
    limit_hit = bool(response_diagnostics.get("output_limit_hit_suspected") is True)
    parse_error = str(parse_diagnostics.get("parse_error") or "")
    reason = "上一轮输出没有通过 action JSON 校验"
    if limit_hit:
        reason = "上一轮输出疑似达到模型输出上限并被截断"
    elif parse_error:
        reason = "上一轮输出不是可解析的 JSON 对象"
    return (
        f"{reason}；上一轮动作没有进入执行队列。错误：{error_text}。"
        f"{TASK_ACTION_JSON_REPAIR_PROMPT}"
        "此时在 tool_calls 数组中调用 write_file 或 terminal；"
        "把交付物内容放入 tool_calls[0].args，或先写入完整可运行的紧凑版本再用后续工具增量完善。"
    )


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_int(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if value not in ("", None, [], {})
    }


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
            "summary": "",
            "title": "",
            "presentation_source": _TASK_MODEL_WAIT_PRESENTATION_SOURCE,
            "status_kind": "model_wait_placeholder",
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
                diagnostics={
                    **dict(current.diagnostics or {}),
                    "latest_step": step,
                    "latest_step_status": "running",
                },
            )
        )
    return event.to_dict()


def _record_task_model_thinking_public_feedback(
    runtime_host: Any,
    *,
    task_run_id: str,
    step_index: int,
    wait_round: int,
    refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = runtime_host.event_log.append(
        task_run_id,
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        payload={
            "task_run_id": task_run_id,
            "step": f"no_public_event_thinking:{int(step_index)}",
            "status": "running",
            "summary": "正在思考。",
            "public_progress_note": "正在思考。",
            "presentation_source": _TASK_MODEL_THINKING_PRESENTATION_SOURCE,
            "feedback_identity": f"no-public-event-thinking:{task_run_id}:{int(step_index)}",
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
                diagnostics={
                    **dict(current.diagnostics or {}),
                    "latest_public_step_summary": "正在思考。",
                },
            )
        )
    return event.to_dict()


def _action_progress_note(action_request: AnyModelActionRequest) -> str:
    state = _action_public_state(action_request)
    return (
        public_runtime_progress_summary(action_request.public_progress_note)
        or _action_state_feedback_note(action_request, state)
    )


def _action_state_feedback_note(action_request: AnyModelActionRequest, state: dict[str, Any]) -> str:
    next_action = public_runtime_progress_summary(state.get("next_action") or "")
    if next_action and _action_state_next_action_matches(action_request, next_action):
        return next_action
    return public_runtime_progress_summary(state.get("current_judgment") or "")


def _action_state_next_action_matches(action_request: AnyModelActionRequest, next_action: str) -> bool:
    action_type = str(action_request.action_type or "").strip().lower()
    if action_type == "tool_call":
        fragments: list[str] = []
        raw_calls = list(getattr(action_request, "tool_calls", ()) or ())
        if not raw_calls and getattr(action_request, "tool_call", None):
            raw_calls = [dict(getattr(action_request, "tool_call", {}) or {})]
        for raw_call in raw_calls:
            tool_call = dict(raw_call or {})
            tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
            tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
            target = _tool_target_preview(tool_args)
            fragments.extend([
                tool_name,
                tool_name.replace("_", " "),
                _public_tool_display_name(tool_name),
                target,
                _target_basename(target),
                *_tool_action_match_keywords(tool_name),
            ])
        return _contains_public_fragment(next_action, fragments)
    if action_type == "respond":
        return _contains_public_fragment(next_action, ("回复", "回答", "整理", "总结", "收口", "说明", "respond"))
    if action_type == "ask_user":
        return _contains_public_fragment(next_action, ("询问", "提问", "确认", "补充", "请你", "需要你", "ask"))
    if action_type == "request_task_run":
        return _contains_public_fragment(next_action, ("任务", "运行", "持续", "后台", "建立", "启动", "处理流程"))
    if action_type == "block":
        return _contains_public_fragment(next_action, ("阻塞", "受阻", "说明", "无法", "等待", "确认"))
    return False


def _target_basename(target: str) -> str:
    text = str(target or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1] if text else ""


def _tool_action_match_keywords(tool_name: str) -> tuple[str, ...]:
    normalized = str(tool_name or "").strip().lower()
    if normalized in {"image_generate", "image_generation", "generate_image"}:
        return ("图像", "图片", "生图", "美术", "资源", "生成", "image")
    if normalized == "path_exists":
        return ("路径", "存在", "检查", "确认", "artifact", "path")
    if normalized in {"read_file", "read_path"}:
        return ("读取", "查看", "文件", "内容", "read")
    if normalized in {"write_file", "edit_file", "batch_edit_file", "apply_patch"}:
        return ("写入", "创建", "修改", "编辑", "补丁", "文件", "write", "edit", "patch")
    if normalized in {"search_text", "search_files", "glob_paths"}:
        return ("搜索", "查找", "检索", "匹配", "search", "grep")
    if normalized in {"terminal", "shell", "run_command", "powershell"}:
        return ("命令", "终端", "运行", "执行", "shell", "powershell")
    return tuple(part for part in normalized.replace("-", "_").split("_") if part)


def _contains_public_fragment(value: str, fragments: Iterable[str]) -> bool:
    haystack = _match_public_text(value)
    for fragment in fragments:
        needle = _match_public_text(fragment)
        if len(needle) >= 2 and needle in haystack:
            return True
    return False


def _match_public_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _action_public_state(action_request: AnyModelActionRequest) -> dict[str, Any]:
    state = dict(action_request.public_action_state or {})
    result: dict[str, Any] = {}
    for key in ("current_judgment", "next_action", "completion_status"):
        value = public_runtime_progress_summary(state.get(key) or "")
        if value:
            result[key] = value
    evidence_refs = [str(item or "").strip() for item in list(state.get("evidence_refs") or []) if str(item or "").strip()]
    open_risks = [public_runtime_progress_summary(item) for item in list(state.get("open_risks") or []) if public_runtime_progress_summary(item)]
    if evidence_refs:
        result["evidence_refs"] = evidence_refs[:8]
    if open_risks:
        result["open_risks"] = open_risks[:6]
    return result


def _tool_call_progress_summary(action_request: AnyModelActionRequest) -> str:
    tool_call = dict(action_request.tool_call or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    target = _tool_target_preview(args)
    action_label = _public_tool_action_label(tool_name)
    if target:
        return f"{action_label}：{target}。"
    return f"{action_label}。"


def _tool_calls_progress_summary(action_request: AnyModelActionRequest) -> str:
    raw_calls = list(getattr(action_request, "tool_calls", ()) or ())
    if not raw_calls and getattr(action_request, "tool_call", None):
        raw_calls = [dict(getattr(action_request, "tool_call", {}) or {})]
    if len(raw_calls) <= 1:
        return _tool_call_progress_summary(action_request)
    previews: list[str] = []
    for raw_call in raw_calls[:3]:
        call = dict(raw_call or {})
        tool_name = str(call.get("tool_name") or call.get("name") or "").strip()
        args = dict(call.get("args") or call.get("tool_args") or {})
        label = _public_tool_action_label(tool_name)
        target = _tool_target_preview(args)
        previews.append(f"{label} {target}".strip())
    suffix = "、".join(previews)
    if len(raw_calls) > 3:
        suffix = f"{suffix} 等"
    return f"执行 {len(raw_calls)} 个工具调用：{suffix}。"


def _public_tool_action_label(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower()
    mapping = {
        "image_generate": "生成图像资源",
        "image_generation": "生成图像资源",
        "generate_image": "生成图像资源",
        "spawn_subagent": "启动子 Agent",
        "send_subagent_message": "发送子 Agent 消息",
        "wait_subagent": "等待子 Agent 返回",
        "list_subagents": "读取子 Agent 状态",
        "close_subagent": "关闭子 Agent",
        "write_file": "写入文件",
        "edit_file": "编辑文件",
        "batch_edit_file": "批量编辑文件",
        "apply_patch": "应用补丁",
        "read_file": "读取文件",
        "read_persisted_tool_result": "读取工具输出缓存",
        "read_path": "读取文件",
        "stat_path": "检查路径信息",
        "list_dir": "读取目录",
        "path_exists": "检查路径是否存在",
        "search_text": "搜索文本",
        "search_files": "搜索文件",
        "glob_paths": "匹配路径",
        "terminal": "运行命令",
        "shell": "运行命令",
        "run_command": "运行命令",
        "powershell": "运行命令",
    }
    return mapping.get(normalized, f"执行 {str(tool_name or '').strip().replace('_', ' ') or '工具'}")


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
        "batch_edit_file": "批量文件编辑工具",
        "read_file": "文件读取工具",
        "read_persisted_tool_result": "工具输出缓存读取工具",
        "terminal": "命令工具",
        "shell": "命令工具",
    }
    if lowered in mapping:
        return mapping[lowered]
    return normalized.replace("_", " ") or "工具"


def _tool_target_preview(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "target_path", "prompt", "query", "command"):
        value = str(args.get(key) or "").strip()
        if value:
            return " ".join(value.split())[:120].rstrip()
    return ""


def _tool_arguments_preview(args: dict[str, Any]) -> str:
    if not args:
        return ""
    priority = ("path", "file_path", "target_path", "prompt", "query", "command", "start_line", "line_count")
    skipped = {"content", "replacement", "new_content", "old_content", "patch", "diff"}
    ordered_keys = [key for key in priority if key in args]
    ordered_keys.extend(key for key in sorted(args) if key not in ordered_keys and key not in skipped)
    parts: list[str] = []
    for key in ordered_keys:
        value = args.get(key)
        if isinstance(value, (dict, list, tuple)):
            continue
        text = public_runtime_progress_summary(f"{key}={value}").strip()
        if text:
            parts.append(text[:120] if key == "command" else text[:80])
        if len(parts) >= 6:
            break
    return ", ".join(parts)[:240]


def _not_found(task_run_id: str) -> dict[str, Any]:
    return {"ok": False, "task_run_id": task_run_id, "error": "task_run_not_found"}


def _conflict(task_run_id: str, error: str) -> dict[str, Any]:
    return {"ok": False, "task_run_id": task_run_id, "error": error}
