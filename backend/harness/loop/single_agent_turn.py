from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Awaitable, Callable

from project_layout import ProjectLayout
from harness.loop.admission import AdmissionDecision
from harness.loop.execution_kernel import (
    ActionLifecycleDecision,
    append_action_lifecycle_event,
    build_action_admission_recovery_payload,
    build_action_lifecycle_event_record,
    build_action_tool_invocation_identity,
    build_tool_lifecycle_started_event_record,
    decide_model_action_lifecycle,
)
from harness.loop.model_action_protocol import ModelActionRequest, model_action_request_from_payload
from harness.loop.model_action_runtime import call_model_invoker
from harness.loop.presentation import error_event, final_answer_event
from harness.runtime import (
    OutputCommitAuthority,
    OutputCommitRequest,
    RuntimeCompiler,
    RuntimeSignalScope,
    ToolBatchGroup,
    build_runtime_tool_plan,
    build_tool_batch_plan,
    runtime_packet_evidence_projection_event_payload,
    runtime_packet_evidence_projection_ref,
    runtime_packet_evidence_signal_scope,
)
from harness.runtime.environment_storage import ensure_environment_storage_dirs
from harness.runtime.file_management_policy import compile_tool_file_management_policy
from harness.runtime.incremental_context_frame import (
    build_prefix_lock_report,
    build_tool_followup_incremental_context_frame_message,
    incremental_context_frame_segment_spec,
    is_incremental_context_frame_message,
    prefix_lock_violation_for_index,
)
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan, stable_model_message_hash, stable_text_hash
from harness.runtime.provider_tool_schema import provider_tool_bindings_for_available_tools
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.sandbox_artifacts import (
    logical_path_publish_allowed,
    publish_sandbox_artifact_refs,
    sandbox_publish_scopes,
)
from harness.runtime.sandbox_execution_scope import compile_sandbox_execution_scope
from runtime.cache_manager import DEFAULT_SANDBOX_CACHE_TTL_SECONDS, runtime_cache_manager_for_host
from runtime.context_management import (
    CONTEXT_APPEND,
    SEALED_CONTEXT_PREFIX,
    STATIC_PREFIX,
    apply_context_assembly_classification,
    assign_sealed_append_order,
    classify_context_spec,
    DYNAMIC_TAIL,
    is_dynamic_tail_spec,
    is_sealable_context_spec,
)
from runtime.prompt_accounting.serializer import normalize_messages
from runtime.prompt_accounting import ContextUsageMeter
from runtime.model_gateway.assistant_stream_frame import (
    ASSISTANT_STREAM_REPAIR_EVENT,
    ASSISTANT_TEXT_DELTA_EVENT,
    assistant_final_stream_events,
    assistant_message_ref,
)
from runtime.model_gateway.assistant_stream_normalizer import AssistantStreamNormalizer
from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response
from runtime.model_gateway.protocol_sanitizer import sanitize_messages_for_prompt
from runtime.model_gateway.model_runtime import ModelRuntimeError, stringify_content
from runtime.model_gateway.stream_iteration import iterate_stream_with_due_ticks
from runtime.output_boundary import (
    CanonicalFinalTextDecision,
    canonical_output_decision_for_final_text,
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from runtime.model_gateway.stream_recovery import (
    VISIBLE_PREFIX_RECOVERY_MODE,
    build_visible_prefix_plain_continuation_messages,
    build_visible_prefix_recovery_messages,
    build_visible_prefix_recovery_segment_plan,
    continuation_after_visible_prefix,
    model_selection_for_visible_prefix_plain_continuation,
    model_selection_for_visible_prefix_recovery,
    recovery_attempts_from_policy,
    should_recover_partial_visible_stream,
    stream_error_code,
    visible_prefix_utf8_bytes,
)
from runtime.output_stream.public_contract import ASSISTANT_PUBLIC_FEEDBACK_EVENT
from runtime.shared.models import TurnRun
from runtime.shared.tool_identity import canonical_action_tool_call_id
from runtime.tool_runtime import ToolInvocationRequest, ToolObservation, build_round_tool_call_options
from runtime.memory.file_evidence_scope import session_file_evidence_scope
from runtime.tool_runtime.provider_tool_call_adapter import tool_calls_for_langchain_messages
from permissions.policy import normalize_permission_mode
from prompt_library import SINGLE_AGENT_ADMISSION_REPAIR_PROMPT

from .active_turn_steering import ActiveTurnQueuedUserSteers, claim_active_turn_queued_user_steers
from .turn_to_task_context_handoff import build_turn_to_task_context_handoff_seed


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest, dict[str, Any]], AsyncIterator[dict[str, Any]]]
ApplyActiveWorkControl = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
ApplyRecoverableWorkResume = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
CompactSessionContext = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]

_DEFAULT_SINGLE_TURN_TOOL_ITERATIONS = 100
_MAX_CONFIGURED_SINGLE_TURN_TOOL_ITERATIONS = 100
_DEFAULT_INTERACTIVE_TOOL_BATCH_TIMEOUT_SECONDS = 45.0
_TOOL_BATCH_CANCEL_DRAIN_SECONDS = 1.0
_ASSISTANT_VISIBLE_STREAM_CONTEXT_MAX_CHARS = 12000


def _configured_single_turn_tool_iterations() -> int:
    raw = str(os.getenv("AGENT_SINGLE_TURN_TOOL_ITERATIONS") or "").strip()
    if not raw:
        return _DEFAULT_SINGLE_TURN_TOOL_ITERATIONS
    try:
        configured = int(raw)
    except ValueError:
        return _DEFAULT_SINGLE_TURN_TOOL_ITERATIONS
    return max(1, min(_MAX_CONFIGURED_SINGLE_TURN_TOOL_ITERATIONS, configured))


_MAX_SINGLE_TURN_TOOL_ITERATIONS = _configured_single_turn_tool_iterations()
_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES = ("respond", "ask_user", "block")
_AGENT_CLOSEOUT_SOURCE = "harness.single_agent_turn.agent_closeout"
_AGENT_CONTRACT_FEEDBACK_SOURCE = "harness.single_agent_turn.agent_contract_feedback"
_ASSISTANT_CONTENT_PREAMBLE_PROGRESS_SOURCE = "model_action.assistant_content_preamble"
_PARTIAL_STREAM_RECOVERY_SOURCE = "harness.single_agent_turn.partial_stream_recovery"
_CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD = 3
_MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS = 3
_CONTROL_ACTION_NAMES = {"request_task_run", "active_work_control", "resume_recoverable_work", "ask_user", "block"}
_ACTIVE_WORK_CONTROL_ACTIONS = {
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_then_continue_active_work",
}
_LEGACY_CONTROL_ACTION_NAMES = {"task_run_request"}
_LEGACY_CONTROL_ACTION_HINTS = {
    "task_run_request": "request_task_run",
}
_MODEL_ACTION_NATIVE_TOOL_NAMES = _CONTROL_ACTION_NAMES | {"respond"} | _LEGACY_CONTROL_ACTION_NAMES
_COMMAND_TRANSPORT_TOOL_NAMES = {
    "bash",
    "cmd",
    "command",
    "execute_command",
    "powershell",
    "run_command",
    "shell",
    "terminal",
}
_CONTROL_TOKEN_COMMAND_PREFIXES = ("echo", "printf", "write-output")
_INTERNAL_MODEL_RESPONSE_EVENT = "__single_agent_model_response"


@dataclass(frozen=True, slots=True)
class NativeActionRequestParse:
    actions: tuple[ModelActionRequest, ...] = ()
    errors: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class FinalMessageCommit:
    decision: CanonicalFinalTextDecision
    events: tuple[dict[str, Any], ...] = ()
    receipt: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AgentAuthoredCloseoutContent:
    content: str
    answer_channel: str = "conversation"
    terminal_status: str = "completed"


def _meaningful_visible_answer(content: str) -> bool:
    visible = sanitize_visible_assistant_content(str(content or "")).strip()
    if not visible:
        return False
    if visible in {">", "<", "...", "…", "---", "----"}:
        return False
    if contains_internal_protocol(visible) or contains_inline_pseudo_tool_call(visible):
        return False
    return any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in visible)


def _runtime_error_payload(error: dict[str, Any] | Any) -> dict[str, Any]:
    payload = dict(error or {}) if isinstance(error, dict) else {"reason": str(error or "")}
    return _drop_empty_dict(
        {
            "type": str(payload.get("type") or "error"),
            "code": str(payload.get("code") or ""),
            "reason": _compact_text(payload.get("reason"), limit=1200),
            "source": "harness.loop.single_agent_turn.model_invocation",
        }
    )


def _drop_empty_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if value not in ("", None, [], {}, ())
    }


def _agent_visible_action_facts(signal: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(signal or {})
    protocol_error = dict(payload.get("protocol_error") or {})
    diagnostics = dict(protocol_error.get("diagnostics") or {})
    detected_action = dict(payload.get("detected_unexecuted_action") or diagnostics.get("detected_json_action") or {})
    previous_payload = payload.get("rejected_json_action_payload") or diagnostics.get("rejected_json_action_payload")
    return _drop_empty_dict(
        {
            "kind": str(payload.get("signal_kind") or payload.get("observation_type") or ""),
            "phase": str(payload.get("phase") or ""),
            "state": _agent_visible_action_state(payload),
            "attempt": _drop_empty_dict(
                {
                    "current": payload.get("recovery_attempt"),
                    "max": payload.get("max_recovery_attempts"),
                    "same_repair_channel_exhausted": bool(payload.get("recovery_exhausted") is True),
                }
            ),
            "allowed_actions": [str(item) for item in list(payload.get("allowed_agent_actions") or ()) if str(item)],
            "tool_call_allowed": bool(payload.get("tool_calls_allowed_after_signal")),
            "tool_budget": _drop_empty_dict(
                {
                    "used_tool_iterations": payload.get("used_tool_iterations"),
                    "max_tool_iterations": payload.get("max_tool_iterations"),
                }
            ),
            "attempted_actions_not_executed": list(payload.get("attempted_actions_not_executed") or []),
            "recent_observations": list(payload.get("recent_observations") or [])[:3],
            "public_response_required": bool(payload.get("public_response_required")),
            "previous_action": _drop_empty_dict(
                {
                    "execution_state": str(detected_action.get("execution_state") or "not_executed") if detected_action else "",
                    "action_type": str(detected_action.get("action_type") or ""),
                    "top_level_keys": list(detected_action.get("top_level_keys") or []),
                    "task_contract_seed_summary": dict(detected_action.get("task_contract_seed_summary") or {}),
                    "payload": previous_payload if isinstance(previous_payload, dict) else {},
                }
            ),
            "previous_response_preview": _compact_text(payload.get("previous_response_preview"), limit=900),
            "observed_facts": dict(payload.get("observed_facts") or {}),
        }
    )


def _agent_visible_action_state(signal: dict[str, Any]) -> str:
    kind = str(signal.get("signal_kind") or "").strip()
    if kind == "model_protocol_violation":
        return "previous_action_not_executed"
    if kind == "tool_budget_exhausted":
        return "tool_budget_exhausted"
    if kind == "final_output_not_committable":
        return "previous_answer_not_saved"
    if kind == "consecutive_tool_failures":
        return "tool_failures"
    return str(signal.get("runtime_control_state") or signal.get("reason") or "")


def _agent_visible_action_fields(allowed_action_types: tuple[str, ...] | list[str]) -> dict[str, str]:
    allowed = {str(item) for item in list(allowed_action_types or ()) if str(item)}
    fields: dict[str, str] = {}
    if "respond" in allowed:
        fields["respond"] = "final_answer"
    if "ask_user" in allowed:
        fields["ask_user"] = "user_question"
    if "block" in allowed:
        fields["block"] = "blocking_reason"
    if "request_task_run" in allowed:
        fields["request_task_run"] = "task_contract_seed"
    if "tool_call" in allowed:
        fields["tool_call"] = "tool_call or tool_calls"
    if "active_work_control" in allowed:
        fields["active_work_control"] = "active_work_control"
    if "resume_recoverable_work" in allowed:
        fields["resume_recoverable_work"] = "recovery_resume"
    return fields


def _agent_closeout_lifecycle_payload(
    *,
    reason: str,
    phase: str,
    control_signal: dict[str, Any] | None = None,
    protocol_error: dict[str, Any] | None = None,
    previous_invalid_response: str = "",
    closeout_attempt: int = 1,
    max_closeout_attempts: int = 2,
) -> dict[str, Any]:
    signal = dict(control_signal or {})
    return _drop_empty_dict(
        {
            "observation_type": "agent_closeout_lifecycle",
            "lifecycle": "agent_authored_closeout",
            "cause": str(reason or "").strip(),
            "phase": str(phase or "").strip(),
            "attempt": _drop_empty_dict(
                {
                    "current": int(closeout_attempt or 0),
                    "max": int(max_closeout_attempts or 0),
                }
            ),
            "tool_channel": "closed",
            "allowed_actions": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
            "required_user_visible_decision": {
                "respond": "final_answer when facts are enough to answer or summarize",
                "ask_user": "user_question when user choice or missing input is required",
                "block": "blocking_reason when facts, permissions, or environment are insufficient",
            },
            "facts": _agent_visible_action_facts(signal),
            "protocol_error": dict(protocol_error or {}),
            "previous_invalid_response_preview": _compact_text(previous_invalid_response, limit=1200),
            "agent_obligations": [
                "base the closeout only on observed facts and user-visible implications",
                "state what is confirmed, what is incomplete, and how work can continue",
                "write the final user-facing judgment in your own words",
            ],
            "forbidden": [
                "do not call tools",
                "do not output provider-native tool_calls",
                "do not expose action fields, internal refs, protocol diagnostics, or debug payloads",
                "do not present unverified work as complete",
            ],
            "authority": "harness.loop.single_agent_turn.agent_closeout_lifecycle",
        }
    )


def _structured_closeout_payload(content: str) -> Any | None:
    text = str(content or "").strip()
    if not text:
        return None
    candidate = text
    if candidate.startswith("```"):
        candidate = candidate.replace("\r\n", "\n")
        candidate = candidate[7:] if candidate.lower().startswith("```json") else candidate[3:]
        if candidate.endswith("```"):
            candidate = candidate[:-3]
        candidate = candidate.strip()
    if not ((candidate.startswith("{") and candidate.endswith("}")) or (candidate.startswith("[") and candidate.endswith("]"))):
        return None
    try:
        return json.loads(candidate)
    except Exception:
        return None

def _agent_authored_closeout_content_from_structured_payload(
    content: str,
    *,
    turn_id: str,
) -> AgentAuthoredCloseoutContent | None:
    parsed = _structured_closeout_payload(content)
    if not isinstance(parsed, dict) or not _is_model_action_json_payload(parsed):
        return None
    action_request, _diagnostics = model_action_request_from_payload(
        parsed,
        turn_id=turn_id,
        allowed_action_types=_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES,
    )
    if action_request is None:
        return None
    if action_request.action_type == "respond":
        return AgentAuthoredCloseoutContent(content=str(action_request.final_answer or "").strip())
    if action_request.action_type == "ask_user":
        return AgentAuthoredCloseoutContent(
            content=str(action_request.user_question or "").strip(),
            answer_channel="ask_user",
        )
    if action_request.action_type == "block":
        return AgentAuthoredCloseoutContent(
            content=str(action_request.blocking_reason or "").strip(),
            answer_channel="blocked",
            terminal_status="blocked",
        )
    return None


def _tool_limit_closeout_control_signal(
    *,
    turn_id: str,
    packet_ref: str,
    tool_iteration: int,
    max_tool_iterations: int,
    attempted_actions: list[ModelActionRequest],
    phase: str,
) -> dict[str, Any]:
    attempted_payloads = [item.to_dict() for item in list(attempted_actions or []) if item is not None]
    instruction = (
        "本轮工具预算已经耗尽。你必须停止发起新的工具调用，"
        "基于已经观察到的事实选择 respond、ask_user 或 block 收口。"
        "respond 时写清已完成事项、未完成事项、验证状态和下一步；"
        "ask_user 只用于确实需要用户决定是否继续；block 只用于事实或权限不足导致无法可靠继续。"
    )
    return {
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "signal_kind": "tool_budget_exhausted",
        "runtime_control_state": "agent_closeout_required",
        "turn_id": turn_id,
        "packet_ref": packet_ref,
        "phase": phase,
        "used_tool_iterations": int(tool_iteration or 0),
        "max_tool_iterations": int(max_tool_iterations or 0),
        "agent_closeout_required": True,
        "allowed_agent_actions": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
        "tool_calls_allowed_after_signal": False,
        "attempted_actions_not_executed": attempted_payloads,
        "repair_instruction": instruction,
        "structured_signal": {
            "code": "single_turn_tool_budget_exhausted",
            "message": instruction,
            "origin": "single_agent_turn_tool_limit_boundary",
            "retryable": False,
        },
        "authority": "harness.loop.single_agent_turn.runtime_control_signal",
    }

def _consecutive_tool_failure_closeout_control_signal(
    *,
    turn_id: str,
    packet_ref: str,
    tool_iteration: int,
    consecutive_failure_rounds: int,
    attempted_actions: list[ModelActionRequest],
    recent_observations: list[dict[str, Any]],
    phase: str,
) -> dict[str, Any]:
    attempted_payloads = [item.to_dict() for item in list(attempted_actions or []) if item is not None]
    instruction = (
        f"最近连续 {_CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD} 轮工具观察均为失败、拒绝、取消、缺合同或运行错误。"
        "你必须停止继续发起工具调用，基于已经观察到的失败事实向用户反馈。"
        "如果可以解释清楚，选择 respond 并说明失败原因、影响和可继续方向；"
        "如果需要用户补充或确认，选择 ask_user；"
        "如果当前无法可靠继续，选择 block 并写清阻塞边界。"
    )
    return {
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "signal_kind": "consecutive_tool_failures",
        "runtime_control_state": "agent_closeout_required",
        "turn_id": turn_id,
        "packet_ref": packet_ref,
        "phase": phase,
        "used_tool_iterations": int(tool_iteration or 0),
        "consecutive_failure_rounds": int(consecutive_failure_rounds or 0),
        "failure_threshold": _CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD,
        "agent_closeout_required": True,
        "allowed_agent_actions": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
        "tool_calls_allowed_after_signal": False,
        "attempted_actions_not_executed": attempted_payloads,
        "recent_observations": [dict(item) for item in list(recent_observations or [])],
        "repair_instruction": instruction,
        "structured_signal": {
            "code": "single_turn_consecutive_tool_failures",
            "message": instruction,
            "origin": "single_agent_turn_tool_failure_boundary",
            "retryable": False,
        },
        "authority": "harness.loop.single_agent_turn.runtime_control_signal",
    }


def _model_protocol_violation_control_signal(
    *,
    turn_id: str,
    packet_ref: str,
    phase: str,
    protocol_error: dict[str, Any],
    allowed_action_types: tuple[str, ...],
    recovery_attempt: int,
    max_recovery_attempts: int,
    public_response_required: bool = False,
    response_preview: str = "",
) -> dict[str, Any]:
    allowed = [str(item) for item in list(allowed_action_types or ()) if str(item)]
    tool_calls_allowed = "tool_call" in set(allowed)
    recovery_exhausted = int(recovery_attempt or 0) >= int(max_recovery_attempts or 0)
    code = str(protocol_error.get("code") or "single_agent_turn_model_protocol_error")
    reason = str(protocol_error.get("reason") or code)
    diagnostics = dict(protocol_error.get("diagnostics") or {})
    detected_action = dict(diagnostics.get("detected_json_action") or {})
    rejected_transport = dict(diagnostics.get("rejected_action_transport") or {})
    rejected_payload = diagnostics.get("rejected_json_action_payload")
    rejected_payload_dict = dict(rejected_payload or {}) if isinstance(rejected_payload, dict) else {}
    specific_repair = _protocol_error_specific_repair_instruction(protocol_error)
    instruction = (
        "上一轮动作没有进入执行队列。"
        "请根据用户目标、已观察事实、allowed_agent_actions 和未执行原因，重新提交一个合法动作。"
        "整段输出只能包含一个 action-like 对象和一个动作来源。"
    )
    if recovery_exhausted:
        instruction += (
            "同一修复通道已经达到上限；不要重复同一无效动作形状。"
            "请重新评估当前事实，选择一个新的合法动作。"
        )
    if detected_action:
        detected_action_type = str(detected_action.get("action_type") or "").strip()
        action_hint = f"（action_type={detected_action_type}）" if detected_action_type else ""
        instruction += (
            f"上一轮输出中已有一个 JSON action{action_hint}，但没有进入执行队列。"
            "如果该动作仍是你的判断，请保留语义意图，修正字段，并作为唯一动作重新提交。"
        )
    if specific_repair:
        instruction += f"具体修复：{specific_repair}"
    if public_response_required:
        instruction += (
            "本次仍处在公开反馈义务内；如果继续请求工具，必须写入 public_progress_note "
            "或 public_action_state.current_judgment，说明已确认事实、影响和下一步。"
        )
    if not tool_calls_allowed:
        instruction += "当前阶段工具通道关闭；请在 allowed_agent_actions 内选择 respond、ask_user、block 或其他已开放控制动作。"
    requested_action_type = _protocol_error_requested_action_type(protocol_error)
    structured_signal = {
        "code": code,
        "message": instruction,
        "reason": reason,
        "origin": "single_agent_turn_model_protocol_boundary",
        "retryable": not recovery_exhausted,
    }
    if requested_action_type == "request_task_run":
        structured_signal["repair_example"] = _request_task_run_minimal_repair_action()
    return {
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "signal_kind": "model_protocol_violation",
        "runtime_control_state": "model_action_contract_feedback_required" if recovery_exhausted else "model_action_recovery_required",
        "turn_id": turn_id,
        "packet_ref": packet_ref,
        "phase": phase,
        "recovery_attempt": int(recovery_attempt or 0),
        "max_recovery_attempts": int(max_recovery_attempts or 0),
        "recovery_exhausted": recovery_exhausted,
        "fresh_agent_decision_required": True,
        "agent_closeout_required": False,
        "allowed_agent_actions": allowed,
        "tool_calls_allowed_after_signal": bool(tool_calls_allowed),
        "public_response_required": bool(public_response_required),
        "protocol_error": dict(protocol_error or {}),
        "detected_unexecuted_action": detected_action,
        "rejected_action_transport": rejected_transport,
        "rejected_json_action_payload": rejected_payload_dict,
        "previous_response_preview": _compact_text(response_preview, limit=1200),
        "repair_instruction": instruction,
        "structured_signal": structured_signal,
        "authority": "harness.loop.single_agent_turn.runtime_control_signal",
    }


def _final_output_not_committable_control_signal(
    *,
    turn_id: str,
    packet_ref: str,
    phase: str,
    answer_channel: str,
    answer_source: str,
    commit: FinalMessageCommit,
) -> dict[str, Any]:
    receipt = dict(commit.receipt or {})
    decision = commit.decision
    reason = str(receipt.get("reason") or "session_output_commit_not_committed")
    instruction = (
        "上一轮最终输出没有通过会话输出提交门禁，因此没有写入用户会话。"
        "你必须停止复述被拒绝内容，改为给用户一个安全、简洁、可见的收口反馈。"
        "不要泄露内部字段、动作 JSON、tool_calls 或提交门禁字段。"
    )
    return {
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "signal_kind": "final_output_not_committable",
        "runtime_control_state": "agent_closeout_required",
        "turn_id": turn_id,
        "packet_ref": packet_ref,
        "phase": phase,
        "agent_closeout_required": True,
        "allowed_agent_actions": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
        "tool_calls_allowed_after_signal": False,
        "answer_channel": str(answer_channel or ""),
        "answer_source": str(answer_source or ""),
        "commit_reason": reason,
        "commit_state": str(receipt.get("state") or receipt.get("status") or ""),
        "answer_canonical_state": str(decision.canonical_state or ""),
        "answer_persist_policy": str(decision.persist_policy or ""),
        "answer_leak_flags": list(decision.leak_flags or ()),
        "repair_instruction": instruction,
        "structured_signal": {
            "code": "single_agent_turn_final_output_not_committable",
            "message": instruction,
            "reason": reason,
            "origin": "single_agent_turn_session_output_boundary",
            "retryable": False,
        },
        "authority": "harness.loop.single_agent_turn.runtime_control_signal",
    }


def _runtime_control_signal_recovery_messages(
    model_messages: list[dict[str, Any]],
    *,
    turn_id: str,
    control_signal: dict[str, Any],
    allowed_action_types: tuple[str, ...],
    recovery_exhausted: bool = False,
) -> list[dict[str, Any]]:
    signal = dict(control_signal or {})
    detected_action = dict(signal.get("detected_unexecuted_action") or {})
    allowed = [str(item) for item in list(allowed_action_types or ()) if str(item)]
    payload = {
        "facts": _agent_visible_action_facts(signal),
        "allowed_action_types": allowed,
        "tool_call_allowed": "tool_call" in set(allowed_action_types or ()),
        "required_fields": _agent_visible_action_fields(allowed),
        "output": {
            "authority": "harness.loop.model_action_request",
            "shape": "one identifiable action-like object",
        },
    }
    if recovery_exhausted:
        payload["facts"]["same_repair_channel_exhausted"] = True
    if detected_action:
        payload["previous_action"] = detected_action
    instruction = (
        "请根据以下事实选择下一步动作。\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"
        "保留用户目标和已确认事实，从 allowed_action_types 中选择一个 action_type。"
        "如果上一轮动作仍然正确，修正字段后重新提交。"
        "整段输出只能包含一个 action-like 对象。"
    )
    return _sanitize_model_messages(
        [
            *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
            {"role": "system", "content": instruction, "turn_id": turn_id},
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.runtime_control_signal_recovery",
    )


def _tool_followup_requires_action_transport(allowed_action_types: tuple[str, ...]) -> bool:
    return bool(
        {
            "respond",
            "ask_user",
            "block",
            "request_task_run",
            "active_work_control",
            "resume_recoverable_work",
            "tool_call",
        }.intersection(str(item) for item in tuple(allowed_action_types or ()))
    )


def _tool_followup_action_contract_messages(
    model_messages: list[dict[str, Any]],
    *,
    turn_id: str,
    allowed_action_types: tuple[str, ...],
    tool_iteration: int,
) -> list[dict[str, Any]]:
    allowed = tuple(str(item) for item in tuple(allowed_action_types or ()) if str(item))
    payload = {
        "allowed_action_types": list(allowed),
        "required_fields": _agent_visible_action_fields(allowed),
        "tool_call_allowed": "tool_call" in set(allowed),
        "output": {
            "assistant_message": "事实已经足够回答用户时，直接输出用户可见的自然语言正文。",
            "control_action": "需要 ask_user、block、request_task_run、active_work_control 或 JSON tool_call 时，输出一个可识别 action-like 对象。",
            "text_transport": "控制动作可以带很短说明，但必须只有一个可识别动作对象；普通最终回答不需要 JSON 包裹。",
        },
        "tool_followup_iteration": int(tool_iteration or 0),
    }
    instruction = (
        "你是正在根据刚才工具观察决定下一步的 coding agent。\n"
        "请选择一个下一步动作。\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"
        "如果已经足够回答用户，直接写用户可见的最终回复；这会作为你的 respond 收口。\n"
        "如果需要用户补充，提交 action_type=ask_user，并填写 user_question。\n"
        "如果当前事实或权限不足，提交 action_type=block，并填写 blocking_reason。\n"
        "如果你决定启动持续任务，提交 action_type=request_task_run；调度只以这个结构化动作生效。\n"
        "task_contract_seed 只需要写清 user_visible_goal、task_run_goal、working_scope.target_objects 和完成证据。"
        "如果仍需普通工具且工具通道可用，可以发起 provider-native tool_call 或 JSON tool_call；"
        "工具前置说明可以作为公开进展，但 task_contract_seed 必须留在动作对象内。\n"
        "只有控制动作和工具动作需要动作对象；不要为了最终回答把自然语言正文塞进 JSON。"
    )
    return _sanitize_model_messages(
        [
            *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
            {
                "role": "system",
                "content": instruction,
                "turn_id": turn_id,
                "source_ref": "single_agent_turn_tool_followup_action_contract",
            },
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.tool_followup_action_contract",
    )


def _agent_authored_closeout_messages(
    model_messages: list[dict[str, Any]],
    *,
    turn_id: str,
    reason: str,
    phase: str,
    control_signal: dict[str, Any] | None = None,
    protocol_error: dict[str, Any] | None = None,
    previous_invalid_response: str = "",
    closeout_attempt: int = 1,
    max_closeout_attempts: int = 2,
) -> list[dict[str, Any]]:
    closeout_lifecycle = _agent_closeout_lifecycle_payload(
        reason=reason,
        phase=phase,
        control_signal=control_signal,
        protocol_error=protocol_error,
        previous_invalid_response=previous_invalid_response,
        closeout_attempt=closeout_attempt,
        max_closeout_attempts=max_closeout_attempts,
    )
    instruction = (
        "你是一名正在收口的 coding agent。\n"
        "你收到的是本轮收口生命周期 observation；当前阶段已经停止继续执行工具，现在必须由你亲自做收口决策。\n"
        "你必须只输出一个 JSON action 对象，不能输出 Markdown 代码块、正文解释、provider-native tool_calls 或第二个动作来源。\n"
        "JSON action 的 authority 必须是 harness.loop.model_action_request，action_type 只能是 respond、ask_user 或 block。\n"
        "如果当前信息足够，请选择 respond，并把给用户看的自然语言收口写入 final_answer。\n"
        "如果还需要用户选择或补充信息，请选择 ask_user，并把问题写入 user_question。\n"
        "如果事实、权限或环境不足以可靠继续，请选择 block，并把阻塞原因写入 blocking_reason。\n"
        "如果收口原因是工具预算耗尽、工具通道关闭、连续工具失败或前一次收口没有形成可发布回复，"
        "必须在用户可见字段里写成你自己的判断：本轮已不能继续执行工具、已确认哪些事实、哪些仍未确认、继续需要什么。"
        "不要把调试字段、动作字段名、内部 ref、协议诊断或生命周期 JSON 写进用户可见字段。\n"
        "如果遇到搜索参数、路径、权限、读取窗口、上下文预算或大文件边界，请把它当作可恢复的执行事实："
        "说明应缩小范围、把目录放在 roots、把具体文件放在 paths、按 read_file 窗口继续读取、提高上下文预算，"
        "或把工作升级为项目级任务继续处理。\n"
        "如果你还没有完成用户目标，要在用户可见字段里明确说未完成和可继续的具体方向；不要把工具记录当作最终成果。\n\n"
        "收口生命周期如下，只用于你理解收口原因和边界，不要逐字泄露内部字段：\n"
        f"{json.dumps({'closeout_lifecycle': closeout_lifecycle}, ensure_ascii=False, sort_keys=True)}"
    )
    return _sanitize_model_messages(
        [
            *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
            {"role": "system", "content": instruction, "turn_id": turn_id},
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.agent_authored_closeout",
    )


def _agent_contract_feedback_required_lifecycle(
    *,
    reason: str,
    phase: str,
    turn_id: str,
    packet_ref: str,
    control_signal: dict[str, Any] | None = None,
    protocol_error: dict[str, Any] | None = None,
    observations: list[dict[str, Any]] | None = None,
    previous_invalid_response: str = "",
    closeout_attempts: int = 0,
) -> dict[str, Any]:
    signal = dict(control_signal or {})
    signal_kind = str(signal.get("signal_kind") or "").strip()
    protocol = dict(protocol_error or {})
    feedback_items = _agent_contract_feedback_items(protocol_error=protocol, control_signal=signal)
    feedback = _agent_contract_feedback_message(
        reason=reason,
        phase=phase,
        signal_kind=signal_kind,
        protocol_error=protocol,
        control_signal=signal,
        previous_invalid_response=previous_invalid_response,
        feedback_items=feedback_items,
    )
    return {
        "observation_type": "agent_contract_feedback_lifecycle",
        "source": "execution_contract_feedback",
        "signal_kind": "agent_contract_feedback_required",
        "lifecycle": "agent_contract_feedback_required",
        "contract_feedback_state": "execution_contract_feedback_required",
        "turn_id": str(turn_id or ""),
        "packet_ref": str(packet_ref or ""),
        "phase": str(phase or ""),
        "reason": str(reason or ""),
        "triggering_signal_kind": signal_kind,
        "visible_assistant_message_allowed": False,
        "tool_calls_allowed_after_signal": False,
        "agent_closeout_required": True,
        "contract_failure": {
            "kind": "agent_output_contract_not_satisfied",
            "closeout_attempts": int(closeout_attempts or 0),
            "phase": str(phase or ""),
            "reason": str(reason or ""),
            "previous_invalid_response_preview": _compact_text(previous_invalid_response, limit=1200),
            "protocol_error": protocol,
            "specific_feedback": feedback_items,
            "facts": _agent_visible_action_facts(signal),
        },
        "observed_facts": _contract_feedback_observed_facts(list(observations or [])),
        "required_action_protocol": {
            "authority": "harness.loop.model_action_request",
            "allowed_action_types": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
            "tool_call_allowed": False,
            "structured_action_required": True,
            "text_transport_accepts_single_unambiguous_json_action": True,
            "visible_user_body_allowed_only_from_agent_action": True,
        },
        "agent_feedback": feedback,
        "structured_signal": {
            "code": "single_agent_turn_agent_contract_feedback_required",
            "message": feedback,
            "origin": "single_agent_turn_output_contract_boundary",
            "retryable": True,
        },
        "authority": "harness.loop.single_agent_turn.agent_contract_feedback_lifecycle",
    }


def _agent_contract_feedback_message(
    *,
    reason: str,
    phase: str,
    signal_kind: str,
    protocol_error: dict[str, Any],
    control_signal: dict[str, Any],
    previous_invalid_response: str,
    feedback_items: list[dict[str, str]],
) -> str:
    del control_signal
    items = list(feedback_items or [])
    phase_text = _contract_feedback_phase_text(phase)
    pieces = [
        "上一条输出没有进入会话，也不会展示给用户。",
        "请保留用户目标和已确认事实，重新选择下一步动作。",
        f"当前阶段：{phase_text}",
    ]
    if signal_kind:
        pieces.append(f"触发信号：{signal_kind}。")
    if items:
        pieces.append("需要修正的地方：")
        for index, item in enumerate(items[:4], start=1):
            situation = str(item.get("situation_feedback") or item.get("reason") or item.get("code") or "").strip()
            repair = str(item.get("repair_instruction") or "").strip()
            expected = str(item.get("expected_next_action") or "").strip()
            line = f"{index}. {situation}"
            if repair:
                line += f" 修正方式：{repair}"
            if expected:
                line += f" 下一步：{expected}"
            pieces.append(line)
    else:
        fallback_reason = str(protocol_error.get("reason") or protocol_error.get("code") or reason or "agent_output_contract_not_satisfied").strip()
        pieces.append(f"上一条输出未满足当前动作要求：{fallback_reason}。请重新提交一个允许动作。")
    if previous_invalid_response:
        pieces.append("上一条不可发布输出已保存在 previous_invalid_response_preview，只能用于你定位错误，不能复述给用户。")
    pieces.append(
        "下一步要求：提交一个可唯一识别的结构化动作，authority 为 harness.loop.model_action_request；"
        "action_type 只能是 respond、ask_user 或 block；不能调用工具，不能输出 provider-native tool_calls，也不能混入第二个动作来源。"
    )
    pieces.append(
        "按真实情况选择动作：事实足够就用 respond.final_answer 写自然、可发布的收口；"
        "需要用户决定就用 ask_user.user_question；事实、权限或证据不足就用 block.blocking_reason。"
    )
    return "\n".join(piece for piece in pieces if str(piece or "").strip()).strip()


def _agent_contract_feedback_items(
    *,
    protocol_error: dict[str, Any],
    control_signal: dict[str, Any],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    diagnostics = dict(protocol_error.get("diagnostics") or {})
    action_issue = dict(diagnostics.get("action_issue") or protocol_error.get("action_issue") or {})
    if action_issue:
        items.append(_contract_feedback_item_from_action_issue(action_issue, fallback_reason=protocol_error.get("reason") or protocol_error.get("code")))
    for native_error in list(diagnostics.get("native_action_errors") or []):
        if not isinstance(native_error, dict):
            continue
        native_issue = dict(native_error.get("action_issue") or {})
        items.append(_contract_feedback_item_from_action_issue(native_issue, fallback_reason=native_error.get("reason") or native_error.get("code")))
    if not items:
        reason = str(protocol_error.get("reason") or protocol_error.get("code") or "").strip()
        if reason:
            items.append(_contract_feedback_item_for_reason(reason, diagnostics=diagnostics))
    runtime_control_item = _contract_feedback_item_for_runtime_control_signal(control_signal)
    if runtime_control_item:
        items.append(runtime_control_item)
    commit_reason = str(control_signal.get("commit_reason") or "").strip()
    if commit_reason:
        leak_flags = [str(item) for item in list(control_signal.get("answer_leak_flags") or []) if str(item)]
        items.append(
            {
                "category": "session_output_contract",
                "code": commit_reason,
                "reason": commit_reason,
                "situation_feedback": _commit_feedback_situation(commit_reason=commit_reason, leak_flags=leak_flags),
                "repair_instruction": _commit_feedback_instruction(commit_reason=commit_reason, leak_flags=leak_flags),
                "expected_next_action": _commit_feedback_expected_next_action(commit_reason=commit_reason, leak_flags=leak_flags),
            }
        )
    return _unique_feedback_items(items)


def _contract_feedback_item_for_runtime_control_signal(control_signal: dict[str, Any]) -> dict[str, str]:
    signal = dict(control_signal or {})
    signal_kind = str(signal.get("signal_kind") or "").strip()
    if signal_kind != "tool_budget_exhausted":
        return {}
    attempted = _attempted_tool_feedback_summary(signal.get("attempted_actions_not_executed"))
    used = _int_feedback_value(signal.get("used_tool_iterations"))
    max_allowed = _int_feedback_value(signal.get("max_tool_iterations"))
    budget = f"{used}/{max_allowed}" if used and max_allowed else ""
    budget_text = f"（{budget}）" if budget else ""
    attempted_text = f"你随后又请求了 {attempted}，该工具意图没有被执行。" if attempted else "你随后又请求了新的工具调用，该工具意图没有被执行。"
    return {
        "category": "runtime_control_boundary",
        "code": "tool_budget_exhausted",
        "reason": "tool_budget_exhausted",
        "situation_feedback": f"本轮已经达到单轮工具预算上限{budget_text}；{attempted_text}",
        "repair_instruction": "停止继续请求工具，用你自己的判断收口：说明已确认事实、未完成项、验证状态和继续条件。",
        "expected_next_action": "事实足够时用 respond.final_answer 收口；需要用户决定是否继续时用 ask_user.user_question；证据不足时用 block.blocking_reason。",
    }


def _attempted_tool_feedback_summary(value: Any) -> str:
    actions = list(value or []) if isinstance(value, list) else []
    for action in actions:
        payload = dict(action or {})
        tool_call = dict(payload.get("tool_call") or {})
        name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
        target = str(
            args.get("path")
            or args.get("file_path")
            or args.get("target_path")
            or args.get("pattern")
            or args.get("query")
            or args.get("url")
            or ""
        ).strip()
        if name and target:
            return f"{name}({target})"
        if name:
            return name
    return ""


def _int_feedback_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _contract_feedback_item_from_action_issue(action_issue: dict[str, Any], *, fallback_reason: Any = "") -> dict[str, str]:
    code = str(action_issue.get("code") or fallback_reason or "action_contract_failed").strip()
    category = str(action_issue.get("category") or "protocol_violation").strip()
    requested_action = str(action_issue.get("requested_action_type") or "").strip()
    requested_tool = str(action_issue.get("requested_tool_name") or "").strip()
    repair = str(action_issue.get("repair_instruction") or "").strip()
    if _uses_standard_contract_feedback_template(code) or not repair:
        repair = _repair_instruction_for_contract_code(code, requested_action=requested_action, requested_tool=requested_tool)
    reason = code
    if requested_action:
        reason = f"{code}（请求动作：{requested_action}）"
    elif requested_tool:
        reason = f"{code}（请求工具：{requested_tool}）"
    return {
        "category": category,
        "code": code,
        "reason": reason,
        "situation_feedback": _situation_feedback_for_contract_code(code, requested_action=requested_action, requested_tool=requested_tool),
        "repair_instruction": repair,
        "expected_next_action": _expected_next_action_for_contract_code(code, requested_action=requested_action, requested_tool=requested_tool),
    }


def _contract_feedback_item_for_reason(reason: str, *, diagnostics: dict[str, Any]) -> dict[str, str]:
    tool_names = [
        str(item).strip()
        for item in list(diagnostics.get("tool_names") or [])
        if str(item).strip()
    ]
    return {
        "category": "protocol_violation",
        "code": str(reason or "action_contract_failed").strip(),
        "reason": str(reason or "action_contract_failed").strip(),
        "situation_feedback": _situation_feedback_for_contract_code(str(reason or ""), requested_tool="、".join(tool_names)),
        "repair_instruction": _repair_instruction_for_contract_code(str(reason or ""), requested_tool="、".join(tool_names)),
        "expected_next_action": _expected_next_action_for_contract_code(str(reason or ""), requested_tool="、".join(tool_names)),
    }


def _contract_feedback_phase_text(phase: str) -> str:
    normalized = str(phase or "").strip()
    labels = {
        "tool_limit_closeout": "工具预算已耗尽后的收口阶段，不能再发起工具，只能基于已观察事实回应、询问或阻塞。",
        "consecutive_tool_failure_closeout": "连续工具失败后的收口阶段，不能重复同类失败动作，只能解释失败、询问用户或阻塞。",
        "protocol_recovery": "上一轮动作未执行，需要重新提交允许动作。",
        "tool_loop": "工具执行循环阶段，模型输出必须是一个可唯一识别的合法动作。",
        "final_output_commit": "最终回复提交阶段，候选正文必须是 agent 自己写出的自然用户回复，且不能泄露内部字段。",
    }
    return labels.get(normalized, normalized or "unknown")


def _uses_standard_contract_feedback_template(code: str) -> bool:
    return str(code or "").strip() in {
        "json_action_required",
        "single_agent_turn_json_action_required",
        "native_tool_call_transport_not_available",
        "native_tool_call_not_allowed_for_context",
        "native_control_action_command_transport_not_allowed",
        "control_action_command_transport_not_allowed",
        "invalid_native_control_action",
        "multiple_native_action_sources",
        "multiple_native_control_actions",
        "single_agent_turn_multiple_action_sources",
        "final_answer_required_for_respond",
        "native_respond_final_answer_required",
        "blocking_reason_required_for_block",
        "user_question_required_for_ask_user",
    }


def _situation_feedback_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "你没有提交本阶段要求的结构化动作，上一条输出无法可靠归类为回答、询问或阻塞。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        tool_hint = f"（{requested_tool}）" if requested_tool else ""
        return f"你尝试继续调用工具{tool_hint}，但当前阶段的工具通道已经关闭；这次工具意图不会被执行。"
    if normalized in {"native_control_action_command_transport_not_allowed", "control_action_command_transport_not_allowed"}:
        action_hint = f"（{requested_action}）" if requested_action else ""
        return f"你把控制类动作{action_hint}写进了命令文本；命令输出不是动作信号，不能当成任务或会话控制。"
    if normalized == "invalid_native_control_action":
        action_hint = f"（{requested_action}）" if requested_action else ""
        return f"你提交了 canonical native 控制动作{action_hint}，但动作参数没有通过 model_action_request 校验。"
    if normalized in {"multiple_native_action_sources", "multiple_native_control_actions"}:
        return "同一轮出现了多个 native 动作决定，无法判断哪一个才是你的唯一真实决策。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "同一轮同时出现 JSON action 和 provider-native tool_call，无法判断哪一个才是你的真实决定。"
    if normalized in {"final_answer_required_for_respond", "native_respond_final_answer_required"}:
        return "你选择了 respond，但没有提供 final_answer；这样会让用户只看到状态或记录，而不是 agent 的自然回复。"
    if normalized in {"blocking_reason_required_for_block"}:
        return "你选择了 block，但没有说明具体阻塞事实；用户和后续 agent 都无法判断卡点是权限、证据、环境还是目标不清。"
    if normalized in {"user_question_required_for_ask_user"}:
        return "你选择了 ask_user，但没有给出用户可以直接回答的问题。"
    return "上一条输出不能进入执行或发布。"


def _repair_instruction_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "提交一个 authority 为 harness.loop.model_action_request 的结构化动作；文本里只能有一个 action-like JSON 对象，包装文字只会被当作传输层噪声。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        tool_hint = f"（刚才请求的是 {requested_tool}）" if requested_tool else ""
        return f"不要重复 provider-native tool_calls{tool_hint}；把当前意图改写为 respond、ask_user 或 block。"
    if normalized in {"native_control_action_command_transport_not_allowed", "control_action_command_transport_not_allowed"}:
        return "不要用 shell、bash、cmd、echo 或 printf 表达控制动作；请提交 JSON action 或 provider-native canonical control action。"
    if normalized == "invalid_native_control_action":
        return "保留原动作类型，补齐缺失或错层的动作参数；request_task_run 必须填写 task_contract_seed，resume_recoverable_work 必须填写 recovery_resume。"
    if normalized in {"multiple_native_action_sources", "multiple_native_control_actions"}:
        return "只保留一个 native 控制动作，或只保留一个普通工具动作集合；不要在同一轮混合多个决策。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "只保留一个动作来源；不要同时提交 JSON action 和 provider-native structured action。"
    if normalized in {"final_answer_required_for_respond", "native_respond_final_answer_required"}:
        return "如果选择 respond，必须填写 final_answer；如果事实不足，不要空答，改用 ask_user 或 block。"
    if normalized in {"blocking_reason_required_for_block"}:
        return "如果选择 block，必须填写 blocking_reason，并说明具体阻塞事实、缺少的权限或缺失信息。"
    if normalized in {"user_question_required_for_ask_user"}:
        return "如果选择 ask_user，必须填写 user_question，并提出用户能直接回答的具体问题。"
    return "根据 allowed_action_types 重新提交一个允许动作，保留已确认事实，不要把动作字段写进用户可见正文，也不要重复同一无效形状。"


def _expected_next_action_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "重新选择 respond、ask_user 或 block，并把对应正文放入 final_answer、user_question 或 blocking_reason。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        return "承认当前不能继续执行该工具；基于已有观察收口，或说明需要用户/环境提供什么条件。"
    if normalized in {"native_control_action_command_transport_not_allowed", "control_action_command_transport_not_allowed"}:
        return "把控制动作从命令文本移出，提交同等语义的 canonical structured action。"
    if normalized == "invalid_native_control_action":
        return "按 model_action_request 补齐当前控制动作的必需字段后重新提交。"
    if normalized in {"multiple_native_action_sources", "multiple_native_control_actions"}:
        return "删掉冲突动作，只提交一个可执行的结构化决定。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "删掉冲突动作，只提交一个可执行的决定。"
    if normalized in {"final_answer_required_for_respond", "native_respond_final_answer_required"}:
        return "写出能直接给用户看的 final_answer，内容应包含结果、依据、未完成项或风险。"
    if normalized in {"blocking_reason_required_for_block"}:
        return "写出具体 blocking_reason，并说明恢复条件。"
    if normalized in {"user_question_required_for_ask_user"}:
        return "写出一个具体、短句、用户能直接回答的 user_question。"
    if requested_tool:
        return f"不要重复提交 {requested_tool}；按当前允许动作给出下一步。"
    return "按当前允许动作重新提交，不要复述内部错误码给用户。"


def _commit_feedback_situation(*, commit_reason: str, leak_flags: list[str]) -> str:
    if any("runtime_protocol" in flag or "internal_protocol" in flag for flag in leak_flags):
        return "你的候选 final_answer 混入了内部字段或动作说明；这些内容不能作为用户回复。"
    if commit_reason in {"empty_final_text", "missing_answer"}:
        return "候选正文为空或没有形成可发布答案；用户会只看到运行记录，而不是你的收口表达。"
    return "候选正文没有通过会话提交门禁；它不能作为最终用户回复保存。"


def _commit_feedback_expected_next_action(*, commit_reason: str, leak_flags: list[str]) -> str:
    if any("runtime_protocol" in flag or "internal_protocol" in flag for flag in leak_flags):
        return "重新写 final_answer，只保留用户需要知道的事实、影响、你自己的判断和下一步。"
    if commit_reason in {"empty_final_text", "missing_answer"}:
        return "补写真实 final_answer；如果不能可靠回答，改用 ask_user 或 block。"
    return "不要复述被拒绝文本，重新生成一个自然、完整、可发布的 agent 输出。"


def _commit_feedback_instruction(*, commit_reason: str, leak_flags: list[str]) -> str:
    if any("runtime_protocol" in flag or "internal_protocol" in flag for flag in leak_flags):
        return "不要解释内部字段；把事实、结果、风险和下一步改写成你自己的自然回复。"
    if commit_reason in {"empty_final_text", "missing_answer"}:
        return "给出真实 final_answer；如果无法可靠回答，改用 ask_user 或 block。"
    return "不要复述被拒绝内容，按 respond、ask_user 或 block 生成新的 agent 输出。"


def _unique_feedback_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in items:
        key = (str(item.get("category") or ""), str(item.get("code") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _contract_feedback_observed_facts(observations: list[dict[str, Any]]) -> dict[str, Any]:
    ok_count = 0
    failed_count = 0
    written_paths: list[str] = []
    observed_paths: list[str] = []
    failed_observations: list[dict[str, str]] = []
    for observation in list(observations or []):
        payload = dict(observation or {})
        status = _normalized_tool_status(payload.get("status"))
        if status == "ok":
            ok_count += 1
        elif status in _TOOL_OBSERVATION_FAILURE_STATUSES:
            failed_count += 1
            failed_observations.append(
                {
                    "tool_name": str(payload.get("tool_name") or "").strip(),
                    "status": str(payload.get("status") or "").strip(),
                    "error": _compact_text(
                        dict(payload.get("result_envelope") or {}).get("error")
                        or payload.get("text")
                        or payload.get("error")
                        or "",
                        limit=240,
                    ),
                }
            )
        envelope = dict(payload.get("result_envelope") or {})
        for path in list(envelope.get("written_paths") or []):
            text = str(path or "").strip()
            if text and text not in written_paths:
                written_paths.append(text)
        structured_payload = dict(envelope.get("structured_payload") or {})
        for path in list(structured_payload.get("observed_paths") or envelope.get("observed_paths") or []):
            text = str(path or "").strip()
            if text and text not in observed_paths:
                observed_paths.append(text)
        tool_result = dict(structured_payload.get("tool_result") or {})
        if str(tool_result.get("kind") or "") == "file_write":
            path = str(tool_result.get("path") or "").strip()
            if path and path not in written_paths:
                written_paths.append(path)
        for event in list(envelope.get("file_state_events") or []):
            if not isinstance(event, dict):
                continue
            path = str(event.get("path") or "").strip()
            if not path:
                continue
            if str(event.get("event_type") or "").strip() == "write":
                if path not in written_paths:
                    written_paths.append(path)
            elif path not in observed_paths:
                observed_paths.append(path)
    return {
        "tool_observation_count": len(list(observations or [])),
        "successful_tool_observation_count": ok_count,
        "failed_tool_observation_count": failed_count,
        "written_paths": written_paths[:20],
        "observed_paths": observed_paths[:20],
        "recent_failed_observations": failed_observations[-5:],
    }


def _is_public_terminal_event(event: dict[str, Any]) -> bool:
    return str(dict(event or {}).get("type") or "").strip() in {"done", "error", "stopped"}


def _terminal_reason_from_public_event(event: dict[str, Any], *, fallback: str) -> str:
    payload = dict(event or {})
    return str(
        payload.get("terminal_reason")
        or payload.get("reason")
        or payload.get("code")
        or fallback
        or str(payload.get("type") or "")
    ).strip()


def _turn_status_from_public_terminal_event(event: dict[str, Any]) -> str:
    event_type = str(dict(event or {}).get("type") or "").strip()
    if event_type == "done":
        return "completed"
    if event_type == "stopped":
        return "aborted"
    return "failed"


@dataclass(frozen=True, slots=True)
class SingleAgentActionParse:
    action_request: ModelActionRequest | None
    native_tool_calls: list[dict[str, Any]]
    error: dict[str, Any] | None = None
    tool_actions: tuple[ModelActionRequest, ...] = ()
    control_action: ModelActionRequest | None = None
    assistant_final_text: str = ""
    packet_public_progress_note: str = ""


async def run_single_agent_turn(
    *,
    session_id: str,
    turn_id: str,
    user_message: str,
    history: list[dict[str, Any]],
    session_context: dict[str, Any],
    agent_invocation_id: str,
    agent_runtime_profile: Any,
    runtime_assembly: Any,
    runtime_host: Any,
    runtime_branch: dict[str, Any],
    active_work_context: Any | None,
    model_runtime: Any,
    model_selection: dict[str, Any],
    current_work_boundary_receipt: dict[str, Any] | None = None,
    stream_run_id: str = "",
    commit_assistant_message: CommitAssistantMessage,
    start_task_from_action_request: StartTaskFromActionRequest,
    apply_active_work_control: ApplyActiveWorkControl | None = None,
    apply_recoverable_work_resume: ApplyRecoverableWorkResume | None = None,
    compact_session_context: CompactSessionContext | None = None,
) -> AsyncIterator[dict[str, Any]]:
    turn_run = None
    terminal_recorded = False
    assistant_visible_stream_continuity: dict[str, Any] = {}

    def terminal_payload_with_stream_continuity(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        continuity = dict(assistant_visible_stream_continuity or {})
        if not continuity:
            return dict(payload or {})
        return {
            **dict(payload or {}),
            "assistant_visible_stream_continuity": continuity,
        }

    try:
        if runtime_host is not None:
            turn_run, start_event = _start_turn_runtime(
                runtime_host,
                session_id=session_id,
                turn_id=turn_id,
                agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
                stream_run_id=stream_run_id,
            )
            yield {"type": "harness_run_started", "turn_run": turn_run.to_dict(), "event": start_event}
        compiler = RuntimeCompiler()
        active_work_payload = _active_work_payload(active_work_context)
        active_work_for_turn = active_work_payload
        def active_work_event_refs() -> dict[str, Any]:
            task_run_id = str(active_work_payload.get("task_run_id") or "").strip()
            if not task_run_id:
                return {}
            active_work_id = str(active_work_payload.get("active_work_id") or "").strip()
            active_turn_id = active_work_id if active_work_id.startswith("turn:") else turn_id
            state = "running_task" if bool(active_work_payload.get("running")) else "waiting_executor"
            return {
                "runtime_task_run_id": task_run_id,
                "task_run_id": task_run_id,
                "active_turn_id": active_turn_id,
                "active_turn": {
                    "session_id": session_id,
                    "turn_id": active_turn_id,
                    "bound_task_run_id": task_run_id,
                    "state": state,
                },
            }

        compilation = compiler.compile_single_agent_turn_packet(
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=agent_invocation_id,
            user_message=user_message,
            history=history,
            session_context=session_context,
            active_work_context=active_work_for_turn,
            current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
            agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
            model_selection=dict(model_selection or {}),
            runtime_assembly=runtime_assembly,
        )
        if runtime_host is not None:
            evidence_event = _publish_packet_evidence_projection_event(
                runtime_host,
                run_id=turn_run.turn_run_id if turn_run is not None else turn_id,
                packet_context=dict(compilation.packet.diagnostics.get("runtime_packet_context") or {}),
                refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id if turn_run is not None else ""},
            )
            if turn_run is not None and evidence_event is not None:
                _update_turn_run_event_offset(runtime_host, turn_run=turn_run, event=evidence_event)
        single_agent_requires_json_action = bool(
            dict(compilation.packet.diagnostics.get("control_capabilities") or {}).get("requires_json_action_protocol") is True
        )
        yield {
            "type": "single_agent_turn_started",
            "runtime_branch": dict(runtime_branch or {}),
            "packet_ref": compilation.packet.packet_id,
            "allowed_action_types": list(compilation.packet.allowed_action_types),
            "current_work_boundary_receipt": dict(current_work_boundary_receipt or {}),
            "turn_id": turn_id,
            "turn_run_id": turn_run.turn_run_id if turn_run is not None else "",
            "active_turn_id": turn_id,
        }
        tool_definitions_by_name = dict(getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {}) or {})
        runtime_tool_plan = build_runtime_tool_plan(
            runtime_assembly=runtime_assembly,
            invocation_kind="single_agent_turn",
            tool_definitions_by_name=tool_definitions_by_name,
        )
        runtime_permission_mode = _turn_runtime_permission_mode(runtime_assembly, runtime_host=runtime_host)
        model_messages = _sanitize_model_messages(
            list(compilation.packet.model_messages),
            turn_id=turn_id,
            source="harness.loop.single_agent_turn.initial",
        )
        api_protocol_messages: list[dict[str, Any]] = []
        assistant_stream_normalizer: AssistantStreamNormalizer | None = None
        assistant_visible_stream_continuity = {}
        current_packet_ref = str(compilation.packet.packet_id)
        current_allowed_action_types = tuple(compilation.packet.allowed_action_types)
        current_available_tools = tuple(compilation.packet.available_tools or ())
        current_requires_json_action = single_agent_requires_json_action
        protocol_recovery_attempts = 0
        tool_observation_payloads: list[dict[str, Any]] = []
        tool_context_ledger_entries: list[dict[str, Any]] = []
        model_messages_segment_plan = dict(compilation.packet.segment_plan or {})

        def memory_maintenance_main_context_for_commit() -> dict[str, Any]:
            return _memory_maintenance_main_context_payload(
                packet_context=dict(compilation.packet.diagnostics.get("runtime_packet_context") or {}),
                model_messages=[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
                segment_plan=dict(model_messages_segment_plan or {}),
                source_packet_ref=current_packet_ref,
                model_selection=dict(model_selection or {}),
            )

        def capture_assistant_stream_event(event: dict[str, Any]) -> None:
            nonlocal assistant_visible_stream_continuity
            assistant_visible_stream_continuity = _assistant_stream_continuity_after_event(
                assistant_visible_stream_continuity,
                event,
                turn_id=turn_id,
            )

        async def claim_active_turn_user_steers(phase: str) -> ActiveTurnQueuedUserSteers:
            return await claim_active_turn_queued_user_steers(
                runtime_host,
                session_id=session_id,
                turn_id=turn_id,
                turn_run=turn_run,
                stream_run_id=stream_run_id,
                packet_ref=current_packet_ref,
                phase=phase,
                source_authority="harness.loop.single_agent_turn.active_turn_steer",
            )

        def append_active_turn_user_steer_message(batch: ActiveTurnQueuedUserSteers, *, source: str) -> None:
            nonlocal model_messages
            if not batch.items or not batch.model_message:
                return
            model_messages = _sanitize_model_messages(
                [
                    *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
                    dict(batch.model_message),
                ],
                turn_id=turn_id,
                source=source,
            )

        async def emit_terminal_then_final(
            *,
            content: str,
            answer_channel: str,
            answer_source: str,
            terminal_reason: str,
            terminal_status: str,
            final_extra: dict[str, Any] | None = None,
            has_tool_receipt: bool = False,
            terminal_payload: dict[str, Any] | None = None,
            commit_decision: FinalMessageCommit | CanonicalFinalTextDecision | None = None,
        ) -> AsyncIterator[dict[str, Any]]:
            nonlocal terminal_recorded, assistant_stream_normalizer
            commit_result = commit_decision if isinstance(commit_decision, FinalMessageCommit) else None
            decision = commit_result.decision if commit_result is not None else (
                commit_decision if isinstance(commit_decision, CanonicalFinalTextDecision) else canonical_output_decision_for_final_text(
                    content,
                    answer_channel=answer_channel,
                    answer_source=answer_source,
                    execution_posture="single_agent_turn",
                    has_tool_receipt=has_tool_receipt,
                    terminal_reason=terminal_reason,
                )
            )
            for frame_event in assistant_final_stream_events(
                assistant_stream_normalizer,
                content=decision.content,
                answer_channel=decision.answer_channel,
                answer_source=decision.answer_source,
                terminal_reason=terminal_reason,
                answer_canonical_state=decision.canonical_state,
                answer_persist_policy=decision.persist_policy,
                extra={
                    "answer_finalization_policy": decision.finalization_policy,
                    "answer_fallback_reason": decision.fallback_reason,
                    "answer_selected_channel": decision.selected_channel,
                    "answer_selected_source": decision.selected_source,
                    "answer_leak_flags": list(decision.leak_flags),
                },
            ):
                yield frame_event
            for commit_event in tuple(commit_result.events if commit_result is not None else ()):
                yield dict(commit_event)
            effective_terminal_status = terminal_status
            effective_terminal_reason = terminal_reason
            commit_receipt = dict(commit_result.receipt or {}) if commit_result is not None else {}
            commit_state = str(commit_receipt.get("state") or commit_receipt.get("status") or "").strip()
            if commit_state and commit_state not in {"committed"}:
                effective_terminal_status = "failed"
                effective_terminal_reason = str(commit_receipt.get("reason") or "session_output_commit_not_committed")
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status=effective_terminal_status,
                    terminal_reason=effective_terminal_reason,
                    payload=terminal_payload_with_stream_continuity(terminal_payload),
                )
                terminal_recorded = True
                yield {"type": "agent_turn_terminal", "event": terminal}
            yield {
                "type": "done",
                **decision.to_payload(),
                "status": effective_terminal_status,
                "terminal_reason": effective_terminal_reason,
                **dict(final_extra or {}),
            }

        async def emit_agent_authored_closeout(
            *,
            reason: str,
            phase: str,
            terminal_reason: str,
            control_signal: dict[str, Any] | None = None,
            protocol_error: dict[str, Any] | None = None,
            completion_state: str = "agent_authored_closeout",
        ) -> AsyncIterator[dict[str, Any]]:
            nonlocal terminal_recorded, assistant_stream_normalizer
            previous_invalid_response = ""
            for attempt in (1, 2):
                closeout_messages = _agent_authored_closeout_messages(
                    model_messages,
                    turn_id=turn_id,
                    reason=reason,
                    phase=phase,
                    control_signal=control_signal,
                    protocol_error=protocol_error,
                    previous_invalid_response=previous_invalid_response,
                    closeout_attempt=attempt,
                    max_closeout_attempts=2,
                )
                closeout_segment_plan = _single_agent_turn_followup_segment_plan(
                    base_segment_plan=dict(compilation.packet.segment_plan or {}),
                    model_messages=closeout_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + attempt,
                )
                closeout_response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=closeout_messages,
                    model_selection=_model_selection_for_native_tool_protocol(dict(model_selection or {})),
                    accounting_context={
                        "request_id": f"modelreq:{current_packet_ref}:agent-closeout:{phase}:{attempt}",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": _AGENT_CLOSEOUT_SOURCE,
                        "segment_plan": closeout_segment_plan,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_agent_authored_closeout",
                            "closeout_phase": phase,
                            "closeout_reason": reason,
                            "attempt": attempt,
                            "segment_plan_ref": str(closeout_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=_native_tools_for_packet(current_allowed_action_types, available_tools=current_available_tools),
                    allow_assistant_text_delta=False,
                    require_json_action=True,
                ):
                    if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                        closeout_response = model_event.get("response")
                        assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                        continue
                    capture_assistant_stream_event(model_event)
                    yield model_event
                if isinstance(closeout_response, dict) and closeout_response.get("type") == "error":
                    break
                content = stringify_content(getattr(closeout_response, "content", closeout_response)).strip()
                closeout_content = _agent_authored_closeout_content_from_structured_payload(content, turn_id=turn_id)
                answer_channel = "conversation"
                terminal_status = "completed"
                if closeout_content is None:
                    previous_invalid_response = content[:1200]
                    continue
                content = closeout_content.content
                answer_channel = closeout_content.answer_channel
                terminal_status = closeout_content.terminal_status
                decision = canonical_output_decision_for_final_text(
                    content,
                    answer_channel=answer_channel,
                    answer_source=_AGENT_CLOSEOUT_SOURCE,
                    execution_posture="single_agent_turn",
                    terminal_reason=terminal_reason,
                    has_tool_receipt=bool(api_protocol_messages),
                )
                if (
                    _meaningful_visible_answer(content)
                    and str(decision.content or "").strip()
                    and decision.persist_policy != "do_not_persist"
                ):
                    commit_decision = await _commit_final_message(
                        commit_assistant_message,
                        runtime_host=runtime_host,
                        turn_run=turn_run,
                        session_id=session_id,
                        turn_id=turn_id,
                        content=content,
                        answer_channel=answer_channel,
                        answer_source=_AGENT_CLOSEOUT_SOURCE,
                        api_protocol_messages=[
                            *api_protocol_messages,
                            _assistant_protocol_message_from_content(content, turn_id=turn_id),
                        ],
                        main_context=memory_maintenance_main_context_for_commit(),
                    )
                    async for event in emit_terminal_then_final(
                        content=content,
                        answer_channel=answer_channel,
                        answer_source=_AGENT_CLOSEOUT_SOURCE,
                        terminal_status=terminal_status,
                        terminal_reason=terminal_reason,
                        final_extra={
                            "runtime_branch": dict(runtime_branch or {}),
                            "completion_state": completion_state,
                            "agent_closeout_attempt": attempt,
                        },
                        terminal_payload={
                            "completion_state": completion_state,
                            "agent_closeout_attempt": attempt,
                            **({"runtime_control_signal": dict(control_signal or {})} if control_signal else {}),
                            **({"protocol_error": dict(protocol_error or {})} if protocol_error else {}),
                        },
                        commit_decision=commit_decision,
                    ):
                        yield event
                    return
                previous_invalid_response = content[:1200]
            contract_feedback = _agent_contract_feedback_required_lifecycle(
                reason=reason,
                phase=phase,
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                control_signal=control_signal,
                protocol_error=protocol_error,
                observations=tool_observation_payloads,
                previous_invalid_response=previous_invalid_response,
                closeout_attempts=2,
            )
            if runtime_host is not None and turn_run is not None:
                lifecycle_event = _record_agent_contract_feedback_required(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    contract_feedback=contract_feedback,
                )
                yield {"type": "agent_contract_feedback_required", "event": lifecycle_event}
            async for event in emit_terminal_then_final(
                content="",
                answer_channel="runtime_control",
                answer_source=_AGENT_CONTRACT_FEEDBACK_SOURCE,
                terminal_status="failed",
                terminal_reason="agent_contract_feedback_required",
                final_extra={
                    "runtime_branch": dict(runtime_branch or {}),
                    "completion_state": "agent_contract_feedback_required",
                    "agent_closeout_attempts": 2,
                    "agent_contract_feedback": contract_feedback,
                },
                terminal_payload={
                    "completion_state": "agent_contract_feedback_required",
                    "agent_closeout_attempts": 2,
                    "agent_contract_feedback": contract_feedback,
                    **({"runtime_control_signal": dict(control_signal or {})} if control_signal else {}),
                    **({"protocol_error": dict(protocol_error or {})} if protocol_error else {}),
                },
            ):
                yield event

        def final_commit_not_committed(commit: FinalMessageCommit) -> bool:
            receipt = dict(commit.receipt or {})
            state = str(receipt.get("state") or receipt.get("status") or "").strip()
            return bool(state and state != "committed")

        async def emit_final_commit_blocked_closeout(
            *,
            commit: FinalMessageCommit,
            phase: str,
            answer_channel: str,
            answer_source: str,
        ) -> AsyncIterator[dict[str, Any]]:
            for commit_event in tuple(commit.events or ()):
                yield dict(commit_event)
            control_signal = _final_output_not_committable_control_signal(
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                phase=phase,
                answer_channel=answer_channel,
                answer_source=answer_source,
                commit=commit,
            )
            if runtime_host is not None and turn_run is not None:
                event = _record_turn_runtime_control_signal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    control_signal=control_signal,
                )
                yield {"type": "turn_runtime_control_signal_observed", "event": event}
            async for event in emit_agent_authored_closeout(
                reason=str(control_signal.get("commit_reason") or "session_output_commit_not_committed"),
                phase=phase,
                terminal_reason=str(control_signal.get("commit_reason") or "session_output_commit_not_committed"),
                control_signal=control_signal,
                completion_state="final_output_not_committable",
            ):
                yield event

        async def emit_tool_limit_closeout(
            *,
            attempted_actions: list[ModelActionRequest],
            phase: str,
        ) -> AsyncIterator[dict[str, Any]]:
            control_signal = _tool_limit_closeout_control_signal(
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                tool_iteration=tool_iteration,
                max_tool_iterations=_MAX_SINGLE_TURN_TOOL_ITERATIONS,
                attempted_actions=list(attempted_actions or []),
                phase=phase,
            )
            if runtime_host is not None and turn_run is not None:
                event = _record_turn_runtime_control_signal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    control_signal=control_signal,
                )
                yield {"type": "turn_runtime_control_signal_observed", "event": event}
            async for event in emit_agent_authored_closeout(
                reason="tool_budget_exhausted",
                phase=f"tool_limit_{phase}",
                terminal_reason="single_turn_tool_iteration_limit",
                control_signal=control_signal,
                completion_state="tool_limit_agent_closeout",
            ):
                yield event
            return

        response = None
        async for model_event in _invoke_single_turn_model_with_stream_events(
            model_runtime=model_runtime,
            model_messages=model_messages,
            model_selection=dict(model_selection or {}),
            accounting_context={
                "request_id": f"modelreq:{compilation.packet.packet_id}:1",
                "session_id": session_id,
                "run_id": turn_run.turn_run_id if turn_run is not None else "",
                "turn_id": turn_id,
                "packet_ref": compilation.packet.packet_id,
                "source": "harness.single_agent_turn",
                "segment_plan": dict(compilation.packet.segment_plan or {}),
                "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
            },
            native_tools=_native_tools_for_packet(compilation.packet.allowed_action_types, available_tools=compilation.packet.available_tools),
            allow_assistant_text_delta=not single_agent_requires_json_action,
            require_json_action=single_agent_requires_json_action,
        ):
            if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                response = model_event.get("response")
                assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                continue
            capture_assistant_stream_event(model_event)
            yield model_event
        tool_iteration = 0
        tool_observation_payloads = []
        last_tool_observation_payloads: list[dict[str, Any]] = []
        consecutive_failure_rounds = 0
        repaired_or_parsed_final_action: SingleAgentActionParse | None = None
        while True:
            if isinstance(response, dict) and response.get("type") == "error":
                break
            active_turn_steer_batch = await claim_active_turn_user_steers("before_model_action")
            if active_turn_steer_batch.items:
                append_active_turn_user_steer_message(
                    active_turn_steer_batch,
                    source="harness.loop.single_agent_turn.active_turn_steer",
                )
                for steer_event in active_turn_steer_batch.events:
                    yield dict(steer_event)
                current_requires_json_action = True
                steer_segment_plan = _single_agent_turn_followup_segment_plan(
                    base_segment_plan=dict(compilation.packet.segment_plan or {}),
                    model_messages=model_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + 1,
                )
                response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": f"modelreq:{current_packet_ref}:active-turn-steer:{tool_iteration + 1}",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.active_turn_steer",
                        "segment_plan": steer_segment_plan,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_active_turn_steer",
                            "steer_phase": "before_model_action",
                            "queued_user_steer_count": len(active_turn_steer_batch.items),
                            "segment_plan_ref": str(steer_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=_native_tools_for_packet(current_allowed_action_types, available_tools=current_available_tools),
                    allow_assistant_text_delta=False,
                    require_json_action=True,
                ):
                    if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                        response = model_event.get("response")
                        assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                        continue
                    capture_assistant_stream_event(model_event)
                    yield model_event
                continue
            require_model_feedback = _tool_followup_public_response_required(
                tool_iteration,
                last_tool_observation_payloads,
            )
            action_parse = _single_agent_action_request_from_response(
                response,
                request_id=f"model-response:{current_packet_ref}:tool:{tool_iteration + 1}",
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                iteration=tool_iteration + 1,
                allowed_action_types=current_allowed_action_types,
                phase="tool_loop",
                require_json_action=current_requires_json_action,
                public_response_required=require_model_feedback,
            )
            if action_parse.error:
                protocol_recovery_attempts += 1
                protocol_control_signal = _model_protocol_violation_control_signal(
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    phase="tool_loop",
                    protocol_error=dict(action_parse.error or {}),
                    allowed_action_types=current_allowed_action_types,
                    recovery_attempt=protocol_recovery_attempts,
                    max_recovery_attempts=_MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS,
                    public_response_required=require_model_feedback,
                    response_preview=stringify_content(getattr(response, "content", response)),
                )
                if runtime_host is not None and turn_run is not None:
                    event = _record_turn_runtime_control_signal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        packet_ref=current_packet_ref,
                        control_signal=protocol_control_signal,
                    )
                    yield {"type": "turn_runtime_control_signal_observed", "event": event}
                recovery_exhausted = protocol_recovery_attempts >= _MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS
                if recovery_exhausted:
                    terminal_reason = str(
                        dict(action_parse.error or {}).get("code")
                        or "single_agent_turn_protocol_error"
                    )
                    async for event in emit_agent_authored_closeout(
                        reason=terminal_reason,
                        phase="tool_loop_protocol_recovery_exhausted",
                        terminal_reason=terminal_reason,
                        control_signal=protocol_control_signal,
                        protocol_error=dict(action_parse.error or {}),
                        completion_state="protocol_recovery_exhausted",
                    ):
                        yield event
                    terminal_recorded = True
                    return
                model_messages = _runtime_control_signal_recovery_messages(
                    model_messages,
                    turn_id=turn_id,
                    control_signal=protocol_control_signal,
                    allowed_action_types=current_allowed_action_types,
                    recovery_exhausted=recovery_exhausted,
                )
                current_requires_json_action = True
                recovery_segment_plan = _single_agent_turn_followup_segment_plan(
                    base_segment_plan=dict(compilation.packet.segment_plan or {}),
                    model_messages=model_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + 1,
                )
                response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": (
                            f"modelreq:{current_packet_ref}:contract-observation:{tool_iteration + 1}:{protocol_recovery_attempts}"
                            if recovery_exhausted
                            else f"modelreq:{current_packet_ref}:runtime-control-recovery:{tool_iteration + 1}:{protocol_recovery_attempts}"
                        ),
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": (
                            "harness.single_agent_turn.contract_observation"
                            if recovery_exhausted
                            else "harness.single_agent_turn.runtime_control_signal_recovery"
                        ),
                        "segment_plan": recovery_segment_plan,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": (
                                "single_agent_turn_contract_observation_decision"
                                if recovery_exhausted
                                else "single_agent_turn_runtime_control_signal_recovery"
                            ),
                            "recovery_phase": "tool_loop",
                            "signal_kind": "model_protocol_violation",
                            "recovery_attempt": protocol_recovery_attempts,
                            "recovery_exhausted": recovery_exhausted,
                            "agent_authored_user_text_required": True,
                            "segment_plan_ref": str(recovery_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=[],
                    allow_assistant_text_delta=False,
                    require_json_action=True,
                ):
                    if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                        response = model_event.get("response")
                        assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                        continue
                    capture_assistant_stream_event(model_event)
                    yield model_event
                continue
            tool_actions = list(action_parse.tool_actions)
            if (
                not tool_actions
                and action_parse.action_request is not None
                and action_parse.action_request.action_type == "tool_call"
            ):
                tool_actions = [action_parse.action_request]
            if not tool_actions:
                if action_parse.action_request is not None or action_parse.assistant_final_text:
                    repaired_or_parsed_final_action = action_parse
                break
            if tool_iteration >= _MAX_SINGLE_TURN_TOOL_ITERATIONS:
                async for event in emit_tool_limit_closeout(
                    attempted_actions=list(tool_actions),
                    phase="tool_loop",
                ):
                    yield event
                return
            if (
                action_parse.packet_public_progress_note
                and runtime_host is not None
                and turn_run is not None
                and not _assistant_stream_has_emitted_public_feedback(
                    assistant_stream_normalizer,
                    action_parse.packet_public_progress_note,
                )
            ):
                yield _record_assistant_public_feedback(
                    runtime_host,
                    run_id=turn_run.turn_run_id,
                    turn_id=turn_id,
                    step="model_action_public_feedback",
                    status="running",
                    summary=action_parse.packet_public_progress_note,
                    presentation_source=_ASSISTANT_CONTENT_PREAMBLE_PROGRESS_SOURCE,
                    feedback_identity=_model_public_feedback_identity(
                        packet_ref=current_packet_ref,
                        tool_iteration=tool_iteration,
                        tool_actions=tool_actions,
                    ),
                )
            tool_iteration += 1
            invocation_rows: list[dict[str, Any]] = []
            for tool_action in tool_actions:
                lifecycle = decide_model_action_lifecycle(
                    tool_action,
                    packet_allowed_action_types=current_allowed_action_types,
                    invocation_kind="single_agent_turn",
                    permit_invocation_kind="agent_turn",
                    packet_ref=current_packet_ref,
                    definitions_by_name=tool_definitions_by_name,
                    allowed_tool_names=set(runtime_tool_plan.dispatchable_tool_names),
                    runtime_profile=_runtime_profile_payload(runtime_assembly),
                    permission_mode=runtime_permission_mode,
                    side_effect_policy="runtime_authorized",
                    current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
                    session_id=session_id,
                    turn_id=turn_id,
                    grant_scope="turn",
                )
                admission = lifecycle.admission
                action_permit = lifecycle.action_permit
                if runtime_host is not None and turn_run is not None:
                    event = _record_model_action_admission(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        action_request=tool_action,
                        lifecycle=lifecycle,
                        packet_ref=current_packet_ref,
                    )
                    yield {"type": "model_action_admission", "event": event}
                row = {
                    "action_request": tool_action,
                    "tool_call": _tool_call_from_action_request(tool_action),
                    "admission": admission,
                    "action_lifecycle": lifecycle.to_dict(),
                    "action_permit": action_permit.to_dict(),
                    "observation": None,
                }
                invocation_rows.append(row)
                if admission.decision != "allow":
                    row["observation"] = _tool_observation_from_admission(
                        runtime_host=runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        action_request=tool_action,
                        admission=admission,
                        action_permit=action_permit.to_dict(),
                        packet_ref=current_packet_ref,
                        tool_plan=runtime_tool_plan,
                    )

            batch_plan = build_tool_batch_plan(
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                invocation_rows=invocation_rows,
                tool_plan=runtime_tool_plan,
                definitions_by_name=tool_definitions_by_name,
                workspace_root=_single_turn_workspace_root(runtime_assembly, runtime_host=runtime_host),
            )
            batch_plan_payload = batch_plan.to_dict()
            planned_event: dict[str, Any] = {}
            if runtime_host is not None and turn_run is not None:
                planned_event = _record_turn_tool_batch_event(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    event_type="tool_batch_planned",
                    payload={
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "tool_batch_plan": batch_plan_payload,
                    },
                    refs={
                        "turn_ref": turn_id,
                        "turn_run_ref": turn_run.turn_run_id,
                        "runtime_invocation_packet_ref": current_packet_ref,
                        "tool_batch_ref": batch_plan.batch_id,
                    },
                )
            yield {
                "type": "tool_batch_planned",
                "tool_batch_plan": batch_plan_payload,
                **({"event": planned_event} if planned_event else {}),
            }
            for group in batch_plan.groups:
                group_payload = group.to_dict()
                started_event: dict[str, Any] = {}
                if runtime_host is not None and turn_run is not None:
                    started_event = _record_turn_tool_batch_event(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        event_type="tool_batch_group_started",
                        payload={
                            "turn_id": turn_id,
                            "packet_ref": current_packet_ref,
                            "tool_batch_ref": batch_plan.batch_id,
                            "tool_batch_group": group_payload,
                        },
                        refs={
                            "turn_ref": turn_id,
                            "turn_run_ref": turn_run.turn_run_id,
                            "runtime_invocation_packet_ref": current_packet_ref,
                            "tool_batch_ref": batch_plan.batch_id,
                        },
                    )
                yield {
                    "type": "tool_batch_group_started",
                    "tool_batch_ref": batch_plan.batch_id,
                    "tool_batch_group": group_payload,
                    **({"event": started_event} if started_event else {}),
                }
                for started_tool_event in _tool_item_started_events_for_group(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    group=group,
                    invocation_rows=invocation_rows,
                ):
                    yield started_tool_event
                group_observations = await _execute_tool_batch_group(
                    group,
                    invocation_rows=invocation_rows,
                    runtime_host=runtime_host,
                    runtime_assembly=runtime_assembly,
                    turn_run=turn_run,
                    session_id=session_id,
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    tool_plan=runtime_tool_plan,
                )
                completed_payload = {
                    "turn_id": turn_id,
                    "packet_ref": current_packet_ref,
                    "tool_batch_ref": batch_plan.batch_id,
                    "tool_batch_group": group_payload,
                    "observation_refs": [item.observation_id for item in group_observations],
                    "statuses": [item.status for item in group_observations],
                    "error_count": sum(1 for item in group_observations if item.status in {"error", "aborted", "canceled"}),
                }
                completed_event: dict[str, Any] = {}
                if runtime_host is not None and turn_run is not None:
                    completed_event = _record_turn_tool_batch_event(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        event_type="tool_batch_group_completed",
                        payload=completed_payload,
                        refs={
                            "turn_ref": turn_id,
                            "turn_run_ref": turn_run.turn_run_id,
                            "runtime_invocation_packet_ref": current_packet_ref,
                            "tool_batch_ref": batch_plan.batch_id,
                            "tool_observation_refs": [item.observation_id for item in group_observations],
                        },
                    )
                yield {
                    "type": "tool_batch_group_completed",
                    "tool_batch_ref": batch_plan.batch_id,
                    "tool_batch_group": group_payload,
                    "observation_refs": completed_payload["observation_refs"],
                    "statuses": completed_payload["statuses"],
                    **({"event": completed_event} if completed_event else {}),
                }

            tool_protocol_messages: list[dict[str, Any]] = []
            assistant_tool_calls: list[dict[str, Any]] = []
            round_observation_payloads: list[dict[str, Any]] = []
            round_tool_context_entries: list[dict[str, Any]] = []
            round_tool_context_indexed_messages: list[tuple[int, dict[str, Any]]] = []
            for row in invocation_rows:
                observation = row["observation"]
                if not isinstance(observation, ToolObservation):
                    observation = _tool_observation_from_runtime_exception(
                        runtime_host=runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        action_request=row["action_request"],
                        admission=row["admission"],
                        action_permit=row["action_permit"],
                        packet_ref=current_packet_ref,
                        tool_plan=runtime_tool_plan,
                        error=RuntimeError("tool_invocation_missing_observation"),
                    )
                    row["observation"] = observation
                if observation.status == "needs_approval":
                    observation = _agent_turn_approval_requires_task_run_observation(observation)
                    row["observation"] = observation
                observation_payload = observation.to_dict()
                tool_observation_payloads.append(observation_payload)
                round_observation_payloads.append(observation_payload)
                yield observation.to_turn_observation_event()
                if runtime_host is not None and turn_run is not None:
                    event = runtime_host.event_log.append(
                        turn_run.turn_run_id,
                        "turn_tool_observation_recorded",
                        payload={
                            "turn_id": turn_id,
                            "tool_observation": observation_payload,
                        },
                        refs={
                            "turn_ref": turn_id,
                            "turn_run_ref": turn_run.turn_run_id,
                            "tool_invocation_ref": observation.invocation_id,
                        },
                    )
                    _update_turn_run_event_offset(runtime_host, turn_run=turn_run, event=event)
                    yield {"type": "turn_tool_observation_recorded", "event": event.to_dict()}
                tool_call = dict(row["tool_call"] or {})
                assistant_tool_calls.append(tool_call)
                tool_protocol_messages.append(
                    _with_turn_id(
                        _tool_observation_message(observation, tool_call_id=str(tool_call.get("id") or "")),
                        turn_id,
                    )
                )
            last_tool_observation_payloads = list(round_observation_payloads)
            if round_observation_payloads and all(_tool_observation_requires_model_feedback(item) for item in round_observation_payloads):
                consecutive_failure_rounds += 1
            else:
                consecutive_failure_rounds = 0
            previous_accumulated_context_count = len(
                _ordered_tool_followup_accumulated_context_messages(
                    model_messages,
                    segment_plan=model_messages_segment_plan,
                )
            )
            if assistant_tool_calls:
                tool_context_assistant_message_index = previous_accumulated_context_count
                assistant_protocol_message = _with_turn_id(_assistant_tool_call_message(response, assistant_tool_calls), turn_id)
                api_protocol_messages.extend([assistant_protocol_message, *tool_protocol_messages])
            else:
                tool_context_assistant_message_index = -1
                assistant_protocol_message = {}
            new_tool_transcript_messages = [
                *([assistant_protocol_message] if assistant_protocol_message else []),
                *tool_protocol_messages,
            ]
            round_tool_context_indexed_messages = _indexed_tool_transcript_messages(
                start_index=previous_accumulated_context_count,
                messages=new_tool_transcript_messages,
            )
            model_messages = _sanitize_model_messages(
                _append_tool_transcript_to_accumulated_context(
                    model_messages,
                    new_tool_transcript_messages,
                    segment_plan=model_messages_segment_plan,
                ),
                turn_id=turn_id,
                source="harness.loop.single_agent_turn.tool_followup",
            )
            if assistant_tool_calls:
                round_tool_context_entries = _append_tool_context_ledger_entries(
                    tool_context_ledger_entries,
                    tool_iteration=tool_iteration,
                    assistant_model_message_index=tool_context_assistant_message_index,
                    tool_calls=assistant_tool_calls,
                    observations=round_observation_payloads,
                )
            if consecutive_failure_rounds >= _CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD:
                control_signal = _consecutive_tool_failure_closeout_control_signal(
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    tool_iteration=tool_iteration,
                    consecutive_failure_rounds=consecutive_failure_rounds,
                    attempted_actions=tool_actions,
                    recent_observations=round_observation_payloads,
                    phase="tool_loop",
                )
                if runtime_host is not None and turn_run is not None:
                    event = _record_turn_runtime_control_signal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        packet_ref=current_packet_ref,
                        control_signal=control_signal,
                    )
                    yield {"type": "turn_runtime_control_signal_observed", "event": event}
                async for event in emit_agent_authored_closeout(
                    reason="consecutive_tool_failures",
                    phase="tool_failure_closeout",
                    terminal_reason="single_turn_consecutive_tool_failures",
                    control_signal=control_signal,
                    completion_state="tool_failure_closeout",
                ):
                    yield event
                return
            followup_segment_plan, followup_prompt_manifest, followup_packet_ref = _single_agent_turn_followup_prompt_context(
                compilation=compilation,
                model_messages=model_messages,
                tool_iteration=tool_iteration,
            )
            model_messages_segment_plan = dict(followup_segment_plan or {})
            mid_turn_snapshot = _mid_turn_context_snapshot(
                session_id=session_id,
                run_id=turn_run.turn_run_id if turn_run is not None else "",
                model_selection=model_selection,
                model_messages=model_messages,
            )
            if mid_turn_snapshot.auto_replacement_allowed:
                mid_turn_compaction: dict[str, Any] = {}
                if runtime_host is not None and turn_run is not None:
                    requested_event = runtime_host.event_log.append(
                        turn_run.turn_run_id,
                        "context_compaction_requested",
                        payload={
                            "turn_id": turn_id,
                            "trigger": "mid_turn_tool_observation_followup",
                            "context_meter": mid_turn_snapshot.to_dict(),
                            "tool_iteration": tool_iteration,
                        },
                        refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id},
                    )
                    yield {"type": "context_compaction_requested", "event": requested_event.to_dict()}
                if compact_session_context is not None:
                    try:
                        maybe_compaction = compact_session_context(
                            {
                                "session_id": session_id,
                                "turn_id": turn_id,
                                "user_message": user_message,
                                "run_id": turn_run.turn_run_id if turn_run is not None else "",
                                "tool_iteration": tool_iteration,
                                "trigger": "mid_turn_tool_observation_followup",
                                "reason": "mid_turn_tool_observation_followup",
                                "context_snapshot": mid_turn_snapshot,
                                "context_meter": mid_turn_snapshot.to_dict(),
                                "model_selection": dict(model_selection or {}),
                                "session_context": dict(session_context or {}),
                            }
                        )
                        resolved_compaction = await maybe_compaction if inspect.isawaitable(maybe_compaction) else maybe_compaction
                        mid_turn_compaction = dict(resolved_compaction or {}) if isinstance(resolved_compaction, dict) else {}
                    except Exception as exc:
                        logger.exception("mid-turn context compaction failed")
                        mid_turn_compaction = {
                            "compaction": {
                                "applied": False,
                                "strategy": "failed",
                                "error": str(exc) or "mid_turn_context_compaction_failed",
                            }
                        }
                        if runtime_host is not None and turn_run is not None:
                            failed_event = runtime_host.event_log.append(
                                turn_run.turn_run_id,
                                "context_compaction_failed",
                                payload={
                                    "turn_id": turn_id,
                                    "trigger": "mid_turn_tool_observation_followup",
                                    "tool_iteration": tool_iteration,
                                    "error": str(exc) or "mid_turn_context_compaction_failed",
                                    "context_meter": mid_turn_snapshot.to_dict(),
                                },
                                refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id},
                            )
                            yield {"type": "context_compaction_failed", "event": failed_event.to_dict()}
                    if bool(dict(mid_turn_compaction.get("compaction") or {}).get("applied")):
                        refreshed_history = [
                            dict(item)
                            for item in list(mid_turn_compaction.get("history") or [])
                            if isinstance(item, dict)
                        ]
                        refreshed_session_context = (
                            dict(mid_turn_compaction.get("session_context") or {})
                            if isinstance(mid_turn_compaction.get("session_context"), dict)
                            else {}
                        )
                        if refreshed_history:
                            history = refreshed_history
                        if refreshed_session_context:
                            session_context = refreshed_session_context
                followup_compilation = compiler.compile_observation_followup_packet(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_invocation_id=agent_invocation_id,
                    user_message=user_message,
                    history=history,
                    session_context=session_context,
                    observations=tool_observation_payloads,
                    agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
                    model_selection=dict(model_selection or {}),
                    available_tools=list(current_available_tools or []),
                    runtime_assembly=runtime_assembly,
                )
                model_messages = _sanitize_model_messages(
                    list(followup_compilation.packet.model_messages),
                    turn_id=turn_id,
                    source="harness.loop.single_agent_turn.mid_turn_context_recovery_followup",
                )
                round_tool_context_indexed_messages = []
                followup_segment_plan = dict(followup_compilation.packet.segment_plan or {})
                model_messages_segment_plan = dict(followup_segment_plan or {})
                followup_prompt_manifest = {
                    **dict(followup_compilation.packet.diagnostics.get("prompt_manifest") or {}),
                    "invocation_kind": "single_agent_turn_tool_followup",
                    "mid_turn_context_recovery": True,
                    "mid_turn_context_meter": mid_turn_snapshot.to_dict(),
                    "followup_iteration": tool_iteration,
                    "segment_plan_ref": str(followup_segment_plan.get("segment_plan_id") or ""),
                }
                followup_packet_ref = followup_compilation.packet.packet_id
                current_packet_ref = str(followup_compilation.packet.packet_id)
                current_allowed_action_types = tuple(followup_compilation.packet.allowed_action_types)
                current_available_tools = tuple(followup_compilation.packet.available_tools or ())
                current_requires_json_action = bool(
                    dict(followup_compilation.packet.diagnostics.get("control_capabilities") or {}).get(
                        "requires_json_action_protocol"
                    )
                    is True
                )
                if runtime_host is not None and turn_run is not None:
                    compaction_payload = dict(mid_turn_compaction.get("compaction") or {})
                    recovery_package = dict(session_context.get("context_recovery_package") or {})
                    package_coverage = dict(recovery_package.get("coverage") or {}) if recovery_package else {}
                    compacted_event = runtime_host.event_log.append(
                        turn_run.turn_run_id,
                        "context_compacted",
                        payload={
                            "turn_id": turn_id,
                            "trigger": "mid_turn_tool_observation_followup",
                            "applied": bool(compaction_payload.get("applied")),
                            "strategy": str(compaction_payload.get("strategy") or "observation_followup_recompile"),
                            "skipped_reason": str(compaction_payload.get("skipped_reason") or ""),
                            "blocked_reason": str(compaction_payload.get("blocked_reason") or ""),
                            "packet_ref": followup_packet_ref,
                            "preserved_observation_count": len(tool_observation_payloads),
                            "context_meter": mid_turn_snapshot.to_dict(),
                            "context_recovery_package_present": bool(recovery_package),
                            "context_recovery_package_source": str(recovery_package.get("source") or "") if recovery_package else "",
                            "context_recovery_package_covered_message_count": int(package_coverage.get("covered_message_count") or 0),
                        },
                        refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id, "runtime_invocation_packet_ref": followup_packet_ref},
                    )
                    yield {"type": "context_compacted", "event": compacted_event.to_dict()}
            active_turn_steer_batch = await claim_active_turn_user_steers("before_tool_followup_model")
            if active_turn_steer_batch.items:
                append_active_turn_user_steer_message(
                    active_turn_steer_batch,
                    source="harness.loop.single_agent_turn.active_turn_steer_tool_followup",
                )
                for steer_event in active_turn_steer_batch.events:
                    yield dict(steer_event)
                followup_segment_plan, followup_prompt_manifest, followup_packet_ref = _single_agent_turn_followup_prompt_context(
                    compilation=compilation,
                    model_messages=model_messages,
                    tool_iteration=tool_iteration,
                )
                model_messages_segment_plan = dict(followup_segment_plan or {})
                followup_prompt_manifest = {
                    **dict(followup_prompt_manifest or {}),
                    "active_turn_user_steer_included": True,
                    "queued_user_steer_count": len(active_turn_steer_batch.items),
                }
            followup_accumulated_messages, followup_dynamic_tail_messages = _tool_followup_context_layers(
                [dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
                segment_plan=model_messages_segment_plan,
            )
            followup_context_messages = [dict(item) for item in list(followup_accumulated_messages or []) if isinstance(item, dict)]
            followup_invocation_messages = [
                *[dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)],
                *[dict(item) for item in list(followup_dynamic_tail_messages or []) if isinstance(item, dict)],
            ]
            if _tool_followup_requires_action_transport(current_allowed_action_types):
                followup_context_messages = [
                    *[dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)],
                    build_tool_followup_incremental_context_frame_message(
                        base_segment_plan=dict(followup_segment_plan or {}),
                        model_messages=[],
                        tool_iteration=tool_iteration,
                        prefix_lock_report=dict(followup_segment_plan.get("prefix_lock") or {}),
                        current_tool_round_indexed_messages=(
                            round_tool_context_indexed_messages
                            or _current_tool_round_indexed_messages(followup_context_messages)
                        ),
                        unchanged_refs=_unchanged_tool_refs_from_tool_context_ledger(
                            tool_context_ledger_entries,
                            current_entries=round_tool_context_entries,
                        ),
                        tool_context_delta=_tool_context_delta_from_ledger(
                            tool_context_ledger_entries,
                            current_entries=round_tool_context_entries,
                            tool_iteration=tool_iteration,
                        ),
                    ),
                ]
                followup_context_messages = _append_tool_followup_context_boundary(
                    followup_context_messages,
                    tool_iteration=tool_iteration,
                    turn_id=turn_id,
                )
                followup_invocation_messages = _tool_followup_action_contract_messages(
                    [
                        *[dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)],
                        *[dict(item) for item in list(followup_dynamic_tail_messages or []) if isinstance(item, dict)],
                    ],
                    turn_id=turn_id,
                    allowed_action_types=current_allowed_action_types,
                    tool_iteration=tool_iteration,
                )
                current_requires_json_action = True
                followup_prompt_manifest = {
                    **dict(followup_prompt_manifest or {}),
                    "tool_followup_action_guidance": True,
                    "assistant_body_transport": "plain_response_allowed",
                    "control_action_transport": "json_action",
                    "non_native_control_action_requires_json_action": True,
                }
            else:
                followup_context_messages = _append_tool_followup_context_boundary(
                    followup_context_messages,
                    tool_iteration=tool_iteration,
                    turn_id=turn_id,
                )
                followup_invocation_messages = [
                    *[dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)],
                    *[dict(item) for item in list(followup_dynamic_tail_messages or []) if isinstance(item, dict)],
                ]
            followup_segment_plan = _single_agent_turn_followup_segment_plan(
                base_segment_plan=dict(followup_segment_plan or {}),
                model_messages=followup_invocation_messages,
                packet_id=str(followup_packet_ref or current_packet_ref),
                tool_iteration=tool_iteration,
            )
            model_messages_segment_plan = dict(followup_segment_plan or {})
            followup_prompt_manifest = {
                **dict(followup_prompt_manifest or {}),
                "segment_plan_ref": str(followup_segment_plan.get("segment_plan_id") or ""),
                "append_only_followup_order": True,
                "physical_message_order": "stable_append_only_context_then_dynamic_tail",
            }
            response = None
            async for model_event in _invoke_single_turn_model_with_stream_events(
                model_runtime=model_runtime,
                model_messages=followup_invocation_messages,
                model_selection=dict(model_selection or {}),
                accounting_context={
                    "request_id": f"modelreq:{followup_packet_ref}:tool-followup:{tool_iteration}",
                    "session_id": session_id,
                    "run_id": turn_run.turn_run_id if turn_run is not None else "",
                    "turn_id": turn_id,
                    "packet_ref": followup_packet_ref,
                    "source": "harness.single_agent_turn.tool_followup",
                    "segment_plan": followup_segment_plan,
                    "prompt_manifest": followup_prompt_manifest,
                },
                native_tools=_native_tools_for_packet(current_allowed_action_types, available_tools=current_available_tools),
                allow_assistant_text_delta=True,
                require_json_action=True,
            ):
                if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                    response = model_event.get("response")
                    assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                    continue
                capture_assistant_stream_event(model_event)
                yield model_event
            model_messages = _sanitize_model_messages(
                followup_invocation_messages,
                turn_id=turn_id,
                source="harness.loop.single_agent_turn.tool_followup_full_invocation_context",
            )
        if isinstance(response, dict) and response.get("type") == "error":
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status="failed",
                    terminal_reason=str(response.get("code") or "single_agent_turn_failed"),
                    payload=terminal_payload_with_stream_continuity(
                        {"model_error": _runtime_error_payload(response)}
                    ),
                )
                terminal_recorded = True
                yield {"type": "agent_turn_terminal", "event": terminal}
            yield response
            return
        if repaired_or_parsed_final_action is not None:
            action_parse = repaired_or_parsed_final_action
        else:
            while True:
                action_parse = _single_agent_action_request_from_response(
                    response,
                    request_id=f"model-response:{current_packet_ref}:final",
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    iteration=tool_iteration + 1,
                    allowed_action_types=current_allowed_action_types,
                    phase="final",
                    require_json_action=current_requires_json_action,
                    public_response_required=False,
                )
                if not action_parse.error:
                    break
                final_allowed_action_types = tuple(item for item in current_allowed_action_types if item != "tool_call")
                protocol_recovery_attempts += 1
                protocol_control_signal = _model_protocol_violation_control_signal(
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    phase="final",
                    protocol_error=dict(action_parse.error or {}),
                    allowed_action_types=final_allowed_action_types,
                    recovery_attempt=protocol_recovery_attempts,
                    max_recovery_attempts=_MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS,
                    public_response_required=False,
                    response_preview=stringify_content(getattr(response, "content", response)),
                )
                if runtime_host is not None and turn_run is not None:
                    event = _record_turn_runtime_control_signal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        packet_ref=current_packet_ref,
                        control_signal=protocol_control_signal,
                    )
                    yield {"type": "turn_runtime_control_signal_observed", "event": event}
                recovery_exhausted = protocol_recovery_attempts >= _MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS
                if recovery_exhausted:
                    terminal_reason = str(
                        dict(action_parse.error or {}).get("code")
                        or "single_agent_turn_protocol_error"
                    )
                    async for event in emit_agent_authored_closeout(
                        reason=terminal_reason,
                        phase="final_protocol_recovery_exhausted",
                        terminal_reason=terminal_reason,
                        control_signal=protocol_control_signal,
                        protocol_error=dict(action_parse.error or {}),
                        completion_state="protocol_recovery_exhausted",
                    ):
                        yield event
                    terminal_recorded = True
                    return
                model_messages = _runtime_control_signal_recovery_messages(
                    model_messages,
                    turn_id=turn_id,
                    control_signal=protocol_control_signal,
                    allowed_action_types=final_allowed_action_types,
                    recovery_exhausted=recovery_exhausted,
                )
                current_allowed_action_types = final_allowed_action_types
                current_available_tools = ()
                current_requires_json_action = True
                recovery_segment_plan = _single_agent_turn_followup_segment_plan(
                    base_segment_plan=dict(compilation.packet.segment_plan or {}),
                    model_messages=model_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + 1,
                )
                response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": (
                            f"modelreq:{current_packet_ref}:final-contract-observation:{protocol_recovery_attempts}"
                            if recovery_exhausted
                            else f"modelreq:{current_packet_ref}:final-runtime-control-recovery:{protocol_recovery_attempts}"
                        ),
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": (
                            "harness.single_agent_turn.contract_observation"
                            if recovery_exhausted
                            else "harness.single_agent_turn.runtime_control_signal_recovery"
                        ),
                        "segment_plan": recovery_segment_plan,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": (
                                "single_agent_turn_contract_observation_decision"
                                if recovery_exhausted
                                else "single_agent_turn_runtime_control_signal_recovery"
                            ),
                            "recovery_phase": "final",
                            "signal_kind": "model_protocol_violation",
                            "recovery_attempt": protocol_recovery_attempts,
                            "recovery_exhausted": recovery_exhausted,
                            "agent_authored_user_text_required": True,
                            "segment_plan_ref": str(recovery_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=[],
                    allow_assistant_text_delta=False,
                    require_json_action=True,
                ):
                    if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                        response = model_event.get("response")
                        assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                        continue
                    capture_assistant_stream_event(model_event)
                    yield model_event
        if action_parse.error:
            async for event in emit_agent_authored_closeout(
                reason=str(dict(action_parse.error or {}).get("code") or "single_agent_turn_protocol_error"),
                phase="final_protocol_error",
                terminal_reason=str(dict(action_parse.error or {}).get("code") or "single_agent_turn_protocol_error"),
                protocol_error=dict(action_parse.error or {}),
            ):
                yield event
            terminal_recorded = True
            return
        tool_calls = action_parse.native_tool_calls
        action_request = action_parse.action_request
        if action_request is not None:
            lifecycle = decide_model_action_lifecycle(
                action_request,
                packet_allowed_action_types=current_allowed_action_types,
                invocation_kind="single_agent_turn",
                permit_invocation_kind="agent_turn",
                packet_ref=current_packet_ref,
                definitions_by_name=getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {}),
                allowed_tool_names=set(
                    str(item.get("tool_name") or item.get("name") or "")
                    for item in list(current_available_tools or [])
                    if isinstance(item, dict)
                ),
                runtime_profile=_runtime_profile_payload(runtime_assembly),
                permission_mode=runtime_permission_mode,
                side_effect_policy="runtime_authorized",
                current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
                session_id=session_id,
                turn_id=turn_id,
                grant_scope="turn",
            )
            admission = lifecycle.admission
            if runtime_host is not None and turn_run is not None:
                event = _record_model_action_admission(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    action_request=action_request,
                    lifecycle=lifecycle,
                    packet_ref=current_packet_ref,
                )
                yield {"type": "model_action_admission", "event": event}
            if admission.decision != "allow":
                repaired_action_parse = await _repair_single_agent_admission_failure(
                    action_request,
                    admission=admission,
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": f"modelreq:{current_packet_ref}:final-admission-repair",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.admission_repair",
                        "segment_plan": dict(compilation.packet.segment_plan or {}),
                        "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                    },
                    request_id=f"model-response:{current_packet_ref}:final:admission-repair",
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    iteration=tool_iteration + 1,
                    allowed_action_types=tuple(item for item in current_allowed_action_types if item != "tool_call"),
                    phase="final_admission_repair",
                )
                if repaired_action_parse.action_request is not None and not repaired_action_parse.error:
                    action_parse = repaired_action_parse
                    tool_calls = action_parse.native_tool_calls
                    action_request = action_parse.action_request
                    lifecycle = decide_model_action_lifecycle(
                        action_request,
                        packet_allowed_action_types=current_allowed_action_types,
                        invocation_kind="single_agent_turn",
                        permit_invocation_kind="agent_turn",
                        packet_ref=current_packet_ref,
                        definitions_by_name=getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {}),
                        allowed_tool_names=set(
                            str(item.get("tool_name") or item.get("name") or "")
                            for item in list(current_available_tools or [])
                            if isinstance(item, dict)
                        ),
                        runtime_profile=_runtime_profile_payload(runtime_assembly),
                        permission_mode=runtime_permission_mode,
                        side_effect_policy="runtime_authorized",
                        current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
                        session_id=session_id,
                        turn_id=turn_id,
                        grant_scope="turn",
                    )
                    admission = lifecycle.admission
                    if runtime_host is not None and turn_run is not None:
                        event = _record_model_action_admission(
                            runtime_host,
                            turn_run=turn_run,
                            turn_id=turn_id,
                            action_request=action_request,
                            lifecycle=lifecycle,
                            packet_ref=current_packet_ref,
                        )
                        yield {"type": "model_action_admission", "event": event}
            if admission.decision != "allow":
                control_signal = {
                    "observation_type": "model_action_admission_observation",
                    "source": "system:admission",
                    "admission": admission.to_dict(),
                    "action_request": action_request.to_dict(),
                    "repair_instruction": (
                        "The requested action was not executed because the current runtime contract or operation "
                        "state does not expose it. Continue by choosing an available action or explaining the "
                        "unavailable operation to the user."
                    ),
                    "authority": "harness.loop.admission",
                }
                async for event in emit_agent_authored_closeout(
                    reason=admission.system_reason or admission.decision,
                    phase="final_admission_observation",
                    terminal_reason=admission.system_reason or admission.decision,
                    control_signal=control_signal,
                    protocol_error=_single_agent_protocol_error(
                        code=str(admission.system_reason or admission.decision or "model_action_admission_not_allowed"),
                        reason=str(admission.user_visible_reason or admission.system_reason or admission.decision),
                        diagnostics={
                            "phase": "final_admission",
                            "admission": admission.to_dict(),
                            "action_request": action_request.to_dict(),
                        },
                    ),
                ):
                    yield event
                terminal_recorded = True
                return
            if action_request.action_type == "respond":
                content = str(action_request.final_answer or "").strip()
                if not content:
                    async for event in emit_agent_authored_closeout(
                        reason="final_answer_required_for_respond",
                        phase="final_respond_missing_answer",
                        terminal_reason="final_answer_required_for_respond",
                        protocol_error=_single_agent_protocol_error(
                            code="final_answer_required_for_respond",
                            reason="respond action did not include final_answer",
                            diagnostics={"phase": "final", "action_request": action_request.to_dict()},
                        ),
                    ):
                        yield event
                    terminal_recorded = True
                    return
                commit_decision = await _commit_final_message(
                    commit_assistant_message,
                    runtime_host=runtime_host,
                    turn_run=turn_run,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="conversation",
                    answer_source="harness.single_agent_turn.respond",
                    api_protocol_messages=_final_api_protocol_messages(
                        api_protocol_messages,
                        response,
                        tool_calls,
                        turn_id=turn_id,
                        tool_result_content="Runtime accepted respond action.",
                        final_content=content,
                    ),
                    main_context=memory_maintenance_main_context_for_commit(),
                )
                if final_commit_not_committed(commit_decision):
                    async for event in emit_final_commit_blocked_closeout(
                        commit=commit_decision,
                        phase="final_respond_output_not_committable",
                        answer_channel="conversation",
                        answer_source="harness.single_agent_turn.respond",
                    ):
                        yield event
                    terminal_recorded = True
                    return
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="conversation",
                    answer_source="harness.single_agent_turn.respond",
                    terminal_status="completed",
                    terminal_reason="respond",
                    final_extra={"runtime_branch": dict(runtime_branch or {})},
                    commit_decision=commit_decision,
                ):
                    yield event
                return
            if action_request.action_type == "request_task_run":
                action_request = _action_request_with_api_protocol_prefix(
                    action_request,
                    _native_action_protocol_messages(
                        response,
                        tool_calls,
                        turn_id=turn_id,
                        tool_result_content="Runtime accepted request_task_run and started task lifecycle scheduling.",
                    ),
                )
                request_task_terminal_reason = "task_executor_scheduled"
                request_task_terminal_status = "completed"
                lifecycle_public_terminal_events: list[dict[str, Any]] = []
                start_context_handoff = build_turn_to_task_context_handoff_seed(
                    runtime_host=runtime_host,
                    session_id=session_id,
                    turn_id=turn_id,
                    source_packet_ref=current_packet_ref,
                    tool_observation_payloads=tool_observation_payloads,
                    session_context=session_context,
                    current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
                )
                async for event in start_task_from_action_request(action_request, start_context_handoff):
                    if _is_public_terminal_event(event):
                        lifecycle_public_terminal_events.append(dict(event))
                        request_task_terminal_reason = _terminal_reason_from_public_event(event, fallback=request_task_terminal_reason)
                        request_task_terminal_status = _turn_status_from_public_terminal_event(event)
                        continue
                    yield event
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status=request_task_terminal_status,
                        terminal_reason=request_task_terminal_reason,
                        payload=terminal_payload_with_stream_continuity({"action_request_ref": action_request.request_id}),
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                for event in lifecycle_public_terminal_events:
                    yield event
                return
            if action_request.action_type == "block":
                content = str(action_request.blocking_reason or "").strip()
                if not content:
                    async for event in emit_agent_authored_closeout(
                        reason="blocking_reason_required_for_block",
                        phase="final_block_missing_reason",
                        terminal_reason="blocking_reason_required_for_block",
                        protocol_error=_single_agent_protocol_error(
                            code="blocking_reason_required_for_block",
                            reason="block action did not include blocking_reason",
                            diagnostics={"phase": "final", "action_request": action_request.to_dict()},
                        ),
                    ):
                        yield event
                    terminal_recorded = True
                    return
                commit_decision = await _commit_final_message(
                    commit_assistant_message,
                    runtime_host=runtime_host,
                    turn_run=turn_run,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.block",
                    api_protocol_messages=_final_api_protocol_messages(
                        api_protocol_messages,
                        response,
                        tool_calls,
                        turn_id=turn_id,
                        tool_result_content="Runtime accepted block action.",
                        final_content=content,
                    ),
                    main_context=memory_maintenance_main_context_for_commit(),
                )
                if final_commit_not_committed(commit_decision):
                    async for event in emit_final_commit_blocked_closeout(
                        commit=commit_decision,
                        phase="final_block_output_not_committable",
                        answer_channel="blocked",
                        answer_source="harness.single_agent_turn.block",
                    ):
                        yield event
                    terminal_recorded = True
                    return
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.block",
                    terminal_status="blocked",
                    terminal_reason="blocked",
                    final_extra={"runtime_branch": dict(runtime_branch or {})},
                    commit_decision=commit_decision,
                ):
                    yield event
                return
            if action_request.action_type == "ask_user":
                content = str(action_request.user_question or "").strip()
                if not content:
                    async for event in emit_agent_authored_closeout(
                        reason="user_question_required_for_ask_user",
                        phase="final_ask_user_missing_question",
                        terminal_reason="user_question_required_for_ask_user",
                        protocol_error=_single_agent_protocol_error(
                            code="user_question_required_for_ask_user",
                            reason="ask_user action did not include user_question",
                            diagnostics={"phase": "final", "action_request": action_request.to_dict()},
                        ),
                    ):
                        yield event
                    terminal_recorded = True
                    return
                commit_decision = await _commit_final_message(
                    commit_assistant_message,
                    runtime_host=runtime_host,
                    turn_run=turn_run,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="ask_user",
                    answer_source="harness.single_agent_turn.ask_user",
                    api_protocol_messages=_final_api_protocol_messages(
                        api_protocol_messages,
                        response,
                        tool_calls,
                        turn_id=turn_id,
                        tool_result_content="Runtime accepted ask_user action.",
                        final_content=content,
                    ),
                    main_context=memory_maintenance_main_context_for_commit(),
                )
                if final_commit_not_committed(commit_decision):
                    async for event in emit_final_commit_blocked_closeout(
                        commit=commit_decision,
                        phase="final_ask_user_output_not_committable",
                        answer_channel="ask_user",
                        answer_source="harness.single_agent_turn.ask_user",
                    ):
                        yield event
                    terminal_recorded = True
                    return
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="ask_user",
                    answer_source="harness.single_agent_turn.ask_user",
                    terminal_status="completed",
                    terminal_reason="ask_user",
                    final_extra={"runtime_branch": dict(runtime_branch or {})},
                    commit_decision=commit_decision,
                ):
                    yield event
                return
            if action_request.action_type == "resume_recoverable_work":
                if apply_recoverable_work_resume is None:
                    async for event in emit_agent_authored_closeout(
                        reason="recoverable_work_resume_executor_missing",
                        phase="recoverable_work_resume_executor_missing",
                        terminal_reason="recoverable_work_resume_executor_missing",
                        protocol_error=_single_agent_protocol_error(
                            code="recoverable_work_resume_executor_missing",
                            reason="single_agent_turn_missing_recoverable_work_resume_callback",
                            diagnostics={"action_request": action_request.to_dict()},
                        ),
                    ):
                        yield event
                    terminal_recorded = True
                    return
                terminal_reason = "recoverable_work_resume"
                terminal_status = "completed"
                buffered_resume_events: list[dict[str, Any]] = []
                async for event in apply_recoverable_work_resume(action_request):
                    event_payload = dict(event or {})
                    event_type = str(event_payload.get("type") or "").strip()
                    if event_type == "error":
                        terminal_status = "failed"
                        terminal_reason = str(event_payload.get("code") or terminal_reason)
                    elif event_type == "done":
                        terminal_reason = str(event_payload.get("terminal_reason") or terminal_reason)
                    buffered_resume_events.append(event_payload)
                for event in buffered_resume_events:
                    yield event
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status=terminal_status,
                        terminal_reason=terminal_reason,
                        payload=terminal_payload_with_stream_continuity({"action_request_ref": action_request.request_id}),
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            if action_request.action_type == "active_work_control":
                if apply_active_work_control is None:
                    async for event in emit_agent_authored_closeout(
                        reason="active_work_control_executor_missing",
                        phase="active_work_control_executor_missing",
                        terminal_reason="active_work_control_executor_missing",
                        protocol_error=_single_agent_protocol_error(
                            code="active_work_control_executor_missing",
                            reason="single_agent_turn_missing_active_work_control_callback",
                            diagnostics={"action_request": action_request.to_dict()},
                        ),
                    ):
                        yield event
                    terminal_recorded = True
                    return
                terminal_reason = "active_work_control"
                terminal_status = "completed"
                control_observation: dict[str, Any] | None = None
                buffered_control_events: list[dict[str, Any]] = []
                async for event in apply_active_work_control(action_request):
                    event_payload = dict(event or {})
                    event_type = str(event_payload.get("type") or "").strip()
                    if event_type == "active_work_control_observation":
                        control_observation = event_payload
                        terminal_status = "failed"
                        terminal_reason = str(event_payload.get("terminal_reason") or "active_work_control_unavailable")
                        continue
                    if event_type == "error":
                        terminal_status = "failed"
                        terminal_reason = str(event_payload.get("code") or terminal_reason)
                    elif event_type == "done":
                        terminal_reason = str(event_payload.get("terminal_reason") or terminal_reason)
                    buffered_control_events.append(event_payload)
                if control_observation is not None:
                    async for event in emit_agent_authored_closeout(
                        reason=terminal_reason,
                        phase="active_work_control_observation",
                        terminal_reason=terminal_reason,
                        control_signal={
                            "observation_type": "active_work_control_observation",
                            "source": "system:active_work_control",
                            **control_observation,
                        },
                    ):
                        yield event
                    terminal_recorded = True
                    return
                for event in buffered_control_events:
                    yield event
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status=terminal_status,
                        terminal_reason=terminal_reason,
                        payload=terminal_payload_with_stream_continuity({"action_request_ref": action_request.request_id}),
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            protocol_error = _single_agent_protocol_error(
                code="single_agent_turn_unhandled_model_action",
                reason=f"unhandled_model_action:{action_request.action_type}",
                diagnostics={
                    "phase": "final",
                    "action_type": action_request.action_type,
                    "action_request": action_request.to_dict(),
                },
            )
            async for event in emit_agent_authored_closeout(
                reason="single_agent_turn_unhandled_model_action",
                phase="final_unhandled_action_protocol_error",
                terminal_reason="single_agent_turn_unhandled_model_action",
                protocol_error=protocol_error,
            ):
                yield event
            terminal_recorded = True
            return

        content = (action_parse.assistant_final_text or stringify_content(getattr(response, "content", response))).strip()
        if not content:
            async for event in emit_agent_authored_closeout(
                reason="single_agent_turn_empty_response",
                phase="single_agent_turn_empty_response",
                terminal_reason="single_agent_turn_empty_response",
                protocol_error=_single_agent_protocol_error(
                    code="single_agent_turn_empty_response",
                    reason="model returned an empty assistant response",
                    diagnostics={"phase": "final", "response_empty": True},
                ),
            ):
                yield event
            terminal_recorded = True
            return
        commit_decision = await _commit_final_message(
            commit_assistant_message,
            runtime_host=runtime_host,
            turn_run=turn_run,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            answer_channel="conversation",
            answer_source="harness.single_agent_turn",
            api_protocol_messages=[
                *api_protocol_messages,
                _assistant_final_protocol_message(response, turn_id=turn_id, include_reasoning=True),
            ]
            if api_protocol_messages
            else None,
            main_context=memory_maintenance_main_context_for_commit(),
        )
        if final_commit_not_committed(commit_decision):
            async for event in emit_final_commit_blocked_closeout(
                commit=commit_decision,
                phase="final_assistant_message_output_not_committable",
                answer_channel="conversation",
                answer_source="harness.single_agent_turn",
            ):
                yield event
            terminal_recorded = True
            return
        async for event in emit_terminal_then_final(
            content=content,
            answer_channel="conversation",
            answer_source="harness.single_agent_turn",
            has_tool_receipt=bool(api_protocol_messages),
            terminal_status="completed",
            terminal_reason="assistant_message",
            final_extra={"runtime_branch": dict(runtime_branch or {})},
            commit_decision=commit_decision,
        ):
            yield event
        return
    except (GeneratorExit, asyncio.CancelledError):
        if runtime_host is not None and turn_run is not None and not terminal_recorded:
            _record_turn_terminal(
                runtime_host,
                turn_run=turn_run,
                turn_id=turn_id,
                status="aborted",
                terminal_reason="stream_cancelled",
                payload=terminal_payload_with_stream_continuity(),
            )
            terminal_recorded = True
        raise


async def _invoke_single_turn_model(
    *,
    model_runtime: Any,
    model_messages: list[dict[str, Any]],
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any],
    native_tools: list[dict[str, Any]],
) -> Any:
    model_messages = _sanitize_model_messages(
        model_messages,
        turn_id=str(accounting_context.get("turn_id") or ""),
        source=str(accounting_context.get("source") or "harness.loop.single_agent_turn.invoke"),
    )
    tool_invoker = getattr(model_runtime, "invoke_messages_with_tools", None)
    plain_invoker = getattr(model_runtime, "invoke_messages", None)
    if native_tools and callable(tool_invoker):
        try:
            tool_call_options = build_round_tool_call_options(max_tool_calls=len(native_tools))
            return await tool_invoker(
                model_messages,
                native_tools,
                model_spec=model_selection,
                tool_call_options=tool_call_options,
                accounting_context=accounting_context,
            )
        except Exception as exc:
            logger.exception("single agent turn model tool invocation failed")
            return _single_agent_model_failure_event(exc)
    if callable(plain_invoker):
        try:
            return await call_model_invoker(
                plain_invoker,
                model_messages,
                model_selection=model_selection,
                accounting_context=accounting_context,
            )
        except Exception as exc:
            logger.exception("single agent turn model invocation failed")
            return _single_agent_model_failure_event(exc)
    return error_event(
        content="运行中断",
        code="model_runtime_unavailable",
        reason="model_runtime_unavailable",
        extra={
            "failure_code": "model_runtime_unavailable",
            "error_summary": "模型运行时不可用。",
            "answer_persist_policy": "do_not_persist",
            "answer_finalization_policy": "no_agent_answer_model_runtime_failed",
        },
    )


def _single_agent_model_failure_event(exc: Exception) -> dict[str, Any]:
    payload = _single_agent_model_failure_payload(exc)
    code = str(payload.pop("code") or "single_agent_turn_model_failed")
    reason = str(payload.get("reason") or payload.get("failure_code") or code)
    return error_event(
        content="运行中断",
        code=code,
        reason=reason,
        extra=payload,
    )


def _single_agent_model_failure_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ModelRuntimeError):
        code = str(exc.code or "single_agent_turn_model_failed").strip() or "single_agent_turn_model_failed"
        summary = sanitize_visible_assistant_content(str(exc.user_message or "")).strip()
        if not summary:
            summary = _public_model_failure_summary(code)
        return {
            "code": code,
            "reason": code,
            "failure_code": code,
            "model_error_code": code,
            "error_summary": summary,
            "provider": str(exc.provider or ""),
            "model": str(exc.model or ""),
            "retryable": bool(exc.retryable),
            "answer_persist_policy": "do_not_persist",
            "answer_finalization_policy": "no_agent_answer_model_runtime_failed",
        }
    return {
        "code": "single_agent_turn_model_failed",
        "reason": "single_agent_turn_model_failed",
        "failure_code": "single_agent_turn_model_failed",
        "error_summary": "模型调用失败，请稍后重试。",
        "retryable": False,
        "answer_persist_policy": "do_not_persist",
        "answer_finalization_policy": "no_agent_answer_model_runtime_failed",
    }


def _public_model_failure_summary(code: str) -> str:
    return {
        "insufficient_balance": "模型服务余额不足，请检查模型提供商账户余额或更换可用模型。",
        "rate_limit": "模型请求触发限流，请稍后重试。",
        "timeout": "模型请求超时，请稍后重试。",
        "provider_unavailable": "模型服务暂时不可用，请稍后重试。",
        "configuration": "模型配置有误，请检查提供商和密钥设置。",
    }.get(str(code or "").strip(), "模型调用失败，请稍后重试。")


def _model_selection_with_json_object_contract(model_selection: dict[str, Any]) -> dict[str, Any]:
    selection = dict(model_selection or {})
    selection = _model_selection_with_action_budget(selection)
    selection.setdefault("structured_output", "json_object")
    selection.setdefault("response_format", {"type": "json_object"})
    return selection


def _model_selection_for_native_tool_protocol(model_selection: dict[str, Any]) -> dict[str, Any]:
    selection = dict(model_selection or {})
    selection.pop("structured_output", None)
    selection.pop("response_format", None)
    return selection


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


async def _invoke_single_turn_model_with_stream_events(
    *,
    model_runtime: Any,
    model_messages: list[dict[str, Any]],
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any],
    native_tools: list[dict[str, Any]],
    allow_assistant_text_delta: bool,
    require_json_action: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    if require_json_action:
        if native_tools:
            model_selection = _model_selection_for_native_tool_protocol(model_selection)
        else:
            model_selection = _model_selection_with_json_object_contract(model_selection)
    elif native_tools:
        model_selection = _model_selection_for_native_tool_protocol(model_selection)
    stream_policy = dict(dict(model_selection or {}).get("stream_policy") or {})
    stream_enabled = bool(stream_policy.get("enabled") is True)
    if not stream_enabled:
        response = await _invoke_single_turn_model(
            model_runtime=model_runtime,
            model_messages=model_messages,
            model_selection=model_selection,
            accounting_context=accounting_context,
            native_tools=native_tools,
        )
        yield {"type": _INTERNAL_MODEL_RESPONSE_EVENT, "response": response, "assistant_stream_normalizer": None}
        return

    model_messages = _sanitize_model_messages(
        model_messages,
        turn_id=str(accounting_context.get("turn_id") or ""),
        source=str(accounting_context.get("source") or "harness.loop.single_agent_turn.invoke_stream"),
    )
    tool_streamer = getattr(model_runtime, "astream_messages_with_tools", None)
    plain_streamer = getattr(model_runtime, "astream_messages", None)
    emit_assistant_text_delta = bool(stream_policy.get("emit_assistant_text_delta", True) is not False) and bool(allow_assistant_text_delta)
    stream_ref = str(accounting_context.get("request_id") or "")
    assistant_normalizer = AssistantStreamNormalizer.from_policy(
        stream_ref=stream_ref,
        message_ref=assistant_message_ref(turn_id=str(accounting_context.get("turn_id") or ""), stream_ref=stream_ref),
        turn_run_id=str(accounting_context.get("run_id") or accounting_context.get("turn_run_id") or ""),
        task_run_id=str(accounting_context.get("task_run_id") or ""),
        answer_source=str(accounting_context.get("source") or "harness.single_agent_turn"),
        stream_policy=stream_policy,
    ) if emit_assistant_text_delta else None
    raw_content = ""
    aggregated_response: Any = None
    try:
        if native_tools and callable(tool_streamer):
            tool_call_options = build_round_tool_call_options(max_tool_calls=len(native_tools))
            async for stream_item_kind, chunk in iterate_stream_with_due_ticks(
                tool_streamer(
                    model_messages,
                    native_tools,
                    model_spec=model_selection,
                    tool_call_options=tool_call_options,
                    accounting_context=accounting_context,
                ),
                timeout_seconds=_single_turn_stream_timeout_seconds(model_selection),
                tick_seconds=assistant_normalizer.release_tick_seconds() if assistant_normalizer is not None else 1.0,
            ):
                if stream_item_kind == "tick":
                    if assistant_normalizer is not None:
                        for frame_event in assistant_normalizer.drain_due():
                            yield frame_event
                    continue
                aggregated_response = _merge_model_stream_chunk(aggregated_response, chunk)
                delta_text = _model_stream_chunk_text(chunk)
                if not delta_text:
                    continue
                raw_content += delta_text
                if assistant_normalizer is not None:
                    for frame_event in assistant_normalizer.observe_delta(delta_text):
                        yield frame_event
        elif callable(plain_streamer):
            async for stream_item_kind, chunk in iterate_stream_with_due_ticks(
                plain_streamer(
                    model_messages,
                    model_spec=model_selection,
                    accounting_context=accounting_context,
                ),
                timeout_seconds=_single_turn_stream_timeout_seconds(model_selection),
                tick_seconds=assistant_normalizer.release_tick_seconds() if assistant_normalizer is not None else 1.0,
            ):
                if stream_item_kind == "tick":
                    if assistant_normalizer is not None:
                        for frame_event in assistant_normalizer.drain_due():
                            yield frame_event
                    continue
                aggregated_response = _merge_model_stream_chunk(aggregated_response, chunk)
                delta_text = _model_stream_chunk_text(chunk)
                if not delta_text:
                    continue
                raw_content += delta_text
                if assistant_normalizer is not None:
                    for frame_event in assistant_normalizer.observe_delta(delta_text):
                        yield frame_event
        else:
            response = await _invoke_single_turn_model(
                model_runtime=model_runtime,
                model_messages=model_messages,
                model_selection=model_selection,
                accounting_context=accounting_context,
                native_tools=native_tools,
            )
            for frame_event in _assistant_stream_end_events(
                assistant_normalizer,
                response,
                response_already_observed=False,
            ):
                yield frame_event
            yield {"type": _INTERNAL_MODEL_RESPONSE_EVENT, "response": response, "assistant_stream_normalizer": assistant_normalizer}
            return
    except Exception as exc:
        logger.exception("single agent turn streaming model invocation failed")
        if should_recover_partial_visible_stream(
            stream_policy,
            raw_content=raw_content,
            emit_assistant_text_delta=emit_assistant_text_delta,
            require_json_action=require_json_action,
            error=exc,
        ):
            if assistant_normalizer is not None:
                for frame_event in assistant_normalizer.flush():
                    yield frame_event
            recovery_context = {
                **dict(accounting_context or {}),
                "request_id": f"{stream_ref}:partial-stream-recovery",
                "source": _PARTIAL_STREAM_RECOVERY_SOURCE,
                "stream_recovery": {
                    "mode": VISIBLE_PREFIX_RECOVERY_MODE,
                    "visible_prefix_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                    "error_code": stream_error_code(exc),
                },
            }
            yield {
                "type": "stream_recovery",
                "status": "started",
                "reason": "partial_stream_error",
                "code": stream_error_code(exc),
                "detail": str(exc),
                "stream_ref": stream_ref,
                "partial_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                "recovery_mode": VISIBLE_PREFIX_RECOVERY_MODE,
            }
            recovery_response: Any = None
            recovery_attempts = recovery_attempts_from_policy(stream_policy)
            recovery_messages = build_visible_prefix_recovery_messages(
                model_messages,
                visible_prefix=raw_content,
                turn_id=str(accounting_context.get("turn_id") or ""),
                source=_PARTIAL_STREAM_RECOVERY_SOURCE,
            )
            for recovery_attempt in range(1, recovery_attempts + 1):
                recovery_segment_plan = build_visible_prefix_recovery_segment_plan(
                    base_segment_plan=dict(accounting_context.get("segment_plan") or {}),
                    recovery_messages=recovery_messages,
                    packet_id=str(accounting_context.get("packet_ref") or stream_ref),
                    recovery_attempt=recovery_attempt,
                    source=_PARTIAL_STREAM_RECOVERY_SOURCE,
                )
                recovery_response = await _invoke_single_turn_model(
                    model_runtime=model_runtime,
                    model_messages=recovery_messages,
                    model_selection=model_selection_for_visible_prefix_recovery(model_selection),
                    accounting_context={
                        **recovery_context,
                        "request_id": f"{stream_ref}:partial-stream-recovery:{recovery_attempt}",
                        "segment_plan": recovery_segment_plan,
                        "prompt_manifest": {
                            **dict(recovery_context.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_partial_stream_recovery",
                            "segment_plan_ref": str(recovery_segment_plan.get("segment_plan_id") or ""),
                        },
                        "stream_recovery": {
                            **dict(recovery_context.get("stream_recovery") or {}),
                            "attempt": recovery_attempt,
                            "max_attempts": recovery_attempts,
                        },
                    },
                    native_tools=[],
                )
                if not (isinstance(recovery_response, dict) and recovery_response.get("type") == "error"):
                    break
            if not (isinstance(recovery_response, dict) and recovery_response.get("type") == "error"):
                recovered_text = stringify_content(getattr(recovery_response, "content", recovery_response))
                continuation = continuation_after_visible_prefix(raw_content, recovered_text)
                if continuation:
                    if assistant_normalizer is not None:
                        for frame_event in assistant_normalizer.observe_delta(continuation):
                            yield frame_event
                        for frame_event in assistant_normalizer.flush():
                            yield frame_event
                    yield {
                        "type": "stream_recovery",
                        "status": "completed",
                        "reason": "continued_from_visible_prefix",
                        "stream_ref": stream_ref,
                        "partial_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                        "continuation_utf8_bytes": visible_prefix_utf8_bytes(continuation),
                        "recovery_mode": VISIBLE_PREFIX_RECOVERY_MODE,
                    }
                    yield {
                        "type": _INTERNAL_MODEL_RESPONSE_EVENT,
                        "assistant_stream_normalizer": assistant_normalizer,
                        "response": SimpleNamespace(content=raw_content + continuation),
                    }
                    return
                yield {
                    "type": "stream_recovery",
                    "status": "completed",
                    "reason": "visible_prefix_committed_without_extra_continuation",
                    "stream_ref": stream_ref,
                    "partial_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                    "continuation_utf8_bytes": 0,
                    "recovery_mode": VISIBLE_PREFIX_RECOVERY_MODE,
                }
                yield {
                    "type": _INTERNAL_MODEL_RESPONSE_EVENT,
                    "assistant_stream_normalizer": assistant_normalizer,
                    "response": SimpleNamespace(content=raw_content),
                }
                return
            recovery_error_reason = str(recovery_response.get("reason") or recovery_response.get("code") or "partial_stream_recovery_failed") if isinstance(recovery_response, dict) else "partial_stream_recovery_failed"
            plain_recovery_messages = build_visible_prefix_plain_continuation_messages(
                model_messages,
                visible_prefix=raw_content,
                turn_id=str(accounting_context.get("turn_id") or ""),
                source=_PARTIAL_STREAM_RECOVERY_SOURCE,
            )
            for recovery_attempt in range(1, recovery_attempts + 1):
                plain_recovery_segment_plan = build_visible_prefix_recovery_segment_plan(
                    base_segment_plan=dict(accounting_context.get("segment_plan") or {}),
                    recovery_messages=plain_recovery_messages,
                    packet_id=str(accounting_context.get("packet_ref") or stream_ref),
                    recovery_attempt=recovery_attempt,
                    source=_PARTIAL_STREAM_RECOVERY_SOURCE,
                )
                recovery_response = await _invoke_single_turn_model(
                    model_runtime=model_runtime,
                    model_messages=plain_recovery_messages,
                    model_selection=model_selection_for_visible_prefix_plain_continuation(model_selection),
                    accounting_context={
                        **recovery_context,
                        "request_id": f"{stream_ref}:partial-stream-plain-continuation:{recovery_attempt}",
                        "segment_plan": plain_recovery_segment_plan,
                        "prompt_manifest": {
                            **dict(recovery_context.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_partial_stream_plain_continuation",
                            "segment_plan_ref": str(plain_recovery_segment_plan.get("segment_plan_id") or ""),
                        },
                        "stream_recovery": {
                            **dict(recovery_context.get("stream_recovery") or {}),
                            "attempt": recovery_attempt,
                            "max_attempts": recovery_attempts,
                            "fallback_mode": "plain_continuation",
                        },
                    },
                    native_tools=[],
                )
                if not (isinstance(recovery_response, dict) and recovery_response.get("type") == "error"):
                    break
                recovery_error_reason = str(
                    recovery_response.get("reason")
                    or recovery_response.get("code")
                    or "partial_stream_recovery_failed"
                )
            if not (isinstance(recovery_response, dict) and recovery_response.get("type") == "error"):
                recovered_text = stringify_content(getattr(recovery_response, "content", recovery_response))
                continuation = continuation_after_visible_prefix(raw_content, recovered_text)
                if continuation:
                    if assistant_normalizer is not None:
                        for frame_event in assistant_normalizer.observe_delta(continuation):
                            yield frame_event
                        for frame_event in assistant_normalizer.flush():
                            yield frame_event
                    yield {
                        "type": "stream_recovery",
                        "status": "completed",
                        "reason": "continued_from_visible_prefix",
                        "stream_ref": stream_ref,
                        "partial_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                        "continuation_utf8_bytes": visible_prefix_utf8_bytes(continuation),
                        "recovery_mode": VISIBLE_PREFIX_RECOVERY_MODE,
                        "fallback_mode": "plain_continuation",
                    }
                    yield {
                        "type": _INTERNAL_MODEL_RESPONSE_EVENT,
                        "assistant_stream_normalizer": assistant_normalizer,
                        "response": SimpleNamespace(content=raw_content + continuation),
                    }
                    return
                yield {
                    "type": "stream_recovery",
                    "status": "completed",
                    "reason": "visible_prefix_committed_without_extra_continuation",
                    "stream_ref": stream_ref,
                    "partial_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                    "continuation_utf8_bytes": 0,
                    "recovery_mode": VISIBLE_PREFIX_RECOVERY_MODE,
                    "fallback_mode": "plain_continuation",
                }
                yield {
                    "type": _INTERNAL_MODEL_RESPONSE_EVENT,
                    "assistant_stream_normalizer": assistant_normalizer,
                    "response": SimpleNamespace(content=raw_content),
                }
                return
            yield {
                "type": "stream_recovery",
                "status": "failed",
                "reason": "partial_stream_recovery_failed",
                "code": stream_error_code(exc),
                "detail": recovery_error_reason,
                "stream_ref": stream_ref,
                "partial_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                "continuation_utf8_bytes": 0,
                "recovery_mode": VISIBLE_PREFIX_RECOVERY_MODE,
                "recovery_call_status": "failed",
            }
            yield {
                "type": _INTERNAL_MODEL_RESPONSE_EVENT,
                "assistant_stream_normalizer": assistant_normalizer,
                "response": error_event(
                    content="运行中断",
                    code="partial_stream_recovery_failed",
                    reason=recovery_error_reason,
                    extra={
                        "original_stream_error_code": stream_error_code(exc),
                        "partial_utf8_bytes": visible_prefix_utf8_bytes(raw_content),
                        "recovery_mode": VISIBLE_PREFIX_RECOVERY_MODE,
                        "recovery_call_status": "failed",
                        "answer_persist_policy": "runtime_status_only",
                    },
                ),
            }
            return
        yield {
            "type": _INTERNAL_MODEL_RESPONSE_EVENT,
            "assistant_stream_normalizer": assistant_normalizer,
            "response": _single_agent_model_failure_event(exc),
        }
        return
    response = aggregated_response if aggregated_response is not None else raw_content
    for frame_event in _assistant_stream_end_events(
        assistant_normalizer,
        response,
        response_already_observed=True,
    ):
        yield frame_event
    yield {"type": _INTERNAL_MODEL_RESPONSE_EVENT, "response": response, "assistant_stream_normalizer": assistant_normalizer}


def _assistant_stream_end_events(
    assistant_normalizer: AssistantStreamNormalizer | None,
    response: Any,
    *,
    response_already_observed: bool,
) -> list[dict[str, Any]]:
    if assistant_normalizer is None:
        return []
    events: list[dict[str, Any]] = []
    if not response_already_observed:
        content = _model_stream_chunk_text(response)
        if content:
            events.extend(assistant_normalizer.observe_delta(content))
    events.extend(assistant_normalizer.flush())
    return events


def _single_turn_stream_timeout_seconds(model_selection: dict[str, Any] | None) -> float:
    selection = dict(model_selection or {})
    stream_policy = dict(selection.get("stream_policy") or {})
    for value in (
        stream_policy.get("model_response_timeout_seconds"),
        stream_policy.get("model_timeout_seconds"),
        stream_policy.get("request_timeout_seconds"),
        selection.get("model_response_timeout_seconds"),
        selection.get("model_timeout_seconds"),
        selection.get("request_timeout_seconds"),
        selection.get("long_output_timeout_seconds"),
    ):
        try:
            parsed = float(value or 0)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return max(0.01, parsed)
    return 300.0


def _merge_model_stream_chunk(current: Any, chunk: Any) -> Any:
    if current is None:
        return chunk
    try:
        return current + chunk
    except Exception:
        current_text = stringify_content(getattr(current, "content", current))
        chunk_text = stringify_content(getattr(chunk, "content", chunk))
        return SimpleNamespace(content=current_text + chunk_text)


def _model_stream_chunk_text(chunk: Any) -> str:
    return stringify_content(getattr(chunk, "content", chunk))


async def _repair_single_agent_admission_failure(
    action_request: ModelActionRequest,
    *,
    admission: AdmissionDecision,
    model_runtime: Any,
    model_messages: list[dict[str, Any]],
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any],
    request_id: str,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...],
    phase: str,
) -> SingleAgentActionParse:
    repair_messages = _single_agent_admission_repair_messages(
        model_messages,
        action_request=action_request,
        admission=admission,
        turn_id=turn_id,
        allowed_action_types=allowed_action_types,
        phase=phase,
    )
    repair_response = await _invoke_single_turn_model(
        model_runtime=model_runtime,
        model_messages=repair_messages,
        model_selection=dict(model_selection or {}),
        accounting_context={
            **dict(accounting_context or {}),
            "request_id": request_id,
            "source": "harness.single_agent_turn.admission_repair",
            "prompt_manifest": {
                **dict(dict(accounting_context or {}).get("prompt_manifest") or {}),
                "invocation_kind": "single_agent_turn_admission_repair",
                "repair_phase": phase,
                "original_admission_decision": admission.decision,
                "original_admission_reason": admission.system_reason,
            },
        },
        native_tools=[],
    )
    if isinstance(repair_response, dict) and repair_response.get("type") == "error":
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=[],
            error=_single_agent_protocol_error(
                code="single_agent_turn_admission_repair_failed",
                reason=str(repair_response.get("code") or "admission_repair_model_failed"),
                diagnostics={
                    "admission": admission.to_dict(),
                    "action_request": action_request.to_dict(),
                    "repair_model_error": dict(repair_response),
                    "phase": phase,
                },
            ),
        )
    repaired = _single_agent_action_request_from_response(
        repair_response,
        request_id=f"{request_id}:response",
        turn_id=turn_id,
        packet_ref=packet_ref,
        iteration=iteration,
        allowed_action_types=allowed_action_types,
        phase=phase,
        require_json_action=True,
    )
    if repaired.error or repaired.action_request is None:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=list(repaired.native_tool_calls or []),
            error=_single_agent_protocol_error(
                code="single_agent_turn_admission_repair_failed",
                reason=str(dict(repaired.error or {}).get("code") or "admission_repair_invalid"),
                diagnostics={
                    "admission": admission.to_dict(),
                    "action_request": action_request.to_dict(),
                    "repair_error": dict(repaired.error or {}),
                    "phase": phase,
                },
            ),
        )
    repaired_action = replace(
        repaired.action_request,
        diagnostics={
            **dict(repaired.action_request.diagnostics or {}),
            "admission_repair": {
                "authority": "harness.loop.single_agent_turn.admission_repair",
                "original_action_type": action_request.action_type,
                "original_admission_decision": admission.decision,
                "original_admission_reason": admission.system_reason,
                "phase": phase,
            },
        },
    )
    return SingleAgentActionParse(
        action_request=repaired_action,
        native_tool_calls=[],
        tool_actions=(repaired_action,) if repaired_action.action_type == "tool_call" else (),
        control_action=repaired_action if repaired_action.action_type != "tool_call" else None,
    )


def _single_agent_admission_repair_messages(
    model_messages: list[dict[str, Any]],
    *,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
    turn_id: str,
    allowed_action_types: tuple[str, ...],
    phase: str,
) -> list[dict[str, Any]]:
    repair_payload = {
        "allowed_action_types": list(allowed_action_types),
        "phase": phase,
        "rejected_action_request": action_request.to_dict(),
        "admission": admission.to_dict(),
    }
    repair_instruction = (
        f"{SINGLE_AGENT_ADMISSION_REPAIR_PROMPT}\n\n"
        "修复输入：\n"
        f"{json.dumps(repair_payload, ensure_ascii=False, sort_keys=True)}"
    )
    return _sanitize_model_messages(
        [
            *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
            {"role": "user", "content": repair_instruction, "turn_id": turn_id},
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.admission_repair",
    )


def _plain_assistant_text_is_allowed_response(
    assistant_text: str,
    *,
    allowed_action_types: tuple[str, ...],
) -> bool:
    if not str(assistant_text or "").strip():
        return False
    return "respond" in {str(item) for item in tuple(allowed_action_types or ()) if str(item)}


def _single_agent_action_request_from_response(
    response: Any,
    *,
    request_id: str,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...],
    phase: str,
    require_json_action: bool = False,
    public_response_required: bool = False,
) -> SingleAgentActionParse:
    protocol = model_response_protocol_from_response(
        response,
        request_id=request_id,
        turn_id=turn_id,
        require_json_action=require_json_action,
        allow_native_tool_calls=True,
    )
    native_tool_calls = [dict(item) for item in protocol.native_tool_calls]
    assistant_text = str(protocol.content or "").strip()
    json_payload = dict(protocol.json_payload or {})
    json_action_like = _is_model_action_json_payload(json_payload)
    malformed_action_like = (
        bool(json_payload)
        and not json_action_like
        and _looks_like_malformed_single_agent_action_payload(json_payload)
    )
    if protocol.protocol_errors:
        protocol_error_code = str(protocol.protocol_errors[0] if protocol.protocol_errors else "model_protocol_error")
        detected_transport = _detected_json_action_transport_rejection(
            json_payload=json_payload,
            protocol_errors=protocol.protocol_errors,
        )
        detected_action = dict(detected_transport.get("detected_json_action") or {})
        requested_action_type = str(detected_action.get("action_type") or "").strip()
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_model_protocol_error",
                reason=";".join(protocol.protocol_errors),
                diagnostics={
                    "protocol_errors": list(protocol.protocol_errors),
                    "parse_diagnostics": dict(protocol.parse_diagnostics or {}),
                    "action_issue": _protocol_action_issue(
                        category="protocol_violation",
                        code=protocol_error_code,
                        requested_action_type=requested_action_type,
                        repair_instruction=_json_action_transport_repair_instruction(
                            protocol_error_code=protocol_error_code,
                            detected_action_type=requested_action_type,
                        ),
                    ),
                    **detected_transport,
                    "phase": phase,
                },
            ),
        )
    if native_tool_calls and json_action_like:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_multiple_action_sources",
                reason="single_agent_turn_multiple_action_sources",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "json_action_type": str(json_payload.get("action_type") or ""),
                    "action_issue": _protocol_action_issue(
                        category="protocol_violation",
                        code="multiple_action_sources",
                        requested_action_type=str(json_payload.get("action_type") or ""),
                        repair_instruction="请在 JSON action 和 provider-native structured action 之间二选一；同一轮只提交一个结构化动作来源。",
                    ),
                    "phase": phase,
                },
            ),
        )
    if json_action_like:
        action_request, diagnostics = model_action_request_from_payload(
            json_payload,
            turn_id=turn_id,
            public_response_required=public_response_required,
            allowed_action_types=allowed_action_types,
        )
        if action_request is None:
            repair_instruction = _invalid_json_action_repair_instruction(
                json_payload=json_payload,
                diagnostics=dict(diagnostics or {}),
            )
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=native_tool_calls,
                error=_single_agent_protocol_error(
                    code="single_agent_turn_invalid_json_action",
                    reason=";".join(str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or []))
                    or "single_agent_turn_invalid_json_action",
                    diagnostics={
                        "model_action_diagnostics": dict(diagnostics or {}),
                        "parse_diagnostics": dict(protocol.parse_diagnostics or {}),
                        "action_issue": _protocol_action_issue(
                            category="protocol_violation",
                            code="invalid_json_action",
                            requested_action_type=str(json_payload.get("action_type") or ""),
                            repair_instruction=repair_instruction,
                        ),
                        "phase": phase,
                    },
                ),
            )
        parsed_action = replace(
            action_request,
            diagnostics={
                **dict(action_request.diagnostics or {}),
                "origin_kind": str(dict(action_request.diagnostics or {}).get("origin_kind") or "single_agent_turn_json_action"),
                "origin_authority": "harness.loop.single_agent_turn",
                "packet_ref": packet_ref,
                "protocol_ref": protocol.protocol_id,
                "parse_transport": _json_action_parse_transport(protocol.parse_diagnostics),
                "phase": phase,
            },
        )
        return SingleAgentActionParse(
            action_request=parsed_action,
            native_tool_calls=[],
            control_action=parsed_action if parsed_action.action_type != "tool_call" else None,
            tool_actions=(parsed_action,) if parsed_action.action_type == "tool_call" else (),
        )
    if malformed_action_like:
        action_request, diagnostics = model_action_request_from_payload(
            json_payload,
            turn_id=turn_id,
            public_response_required=public_response_required,
            allowed_action_types=allowed_action_types,
        )
        del action_request
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_invalid_json_action",
                reason=";".join(str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or []))
                or "single_agent_turn_invalid_json_action",
                diagnostics={
                    "model_action_diagnostics": dict(diagnostics or {}),
                    "parse_diagnostics": dict(protocol.parse_diagnostics or {}),
                    "action_issue": _protocol_action_issue(
                        category="protocol_violation",
                        code="invalid_json_action",
                        repair_instruction="这看起来像控制/工具动作，但缺少 harness.loop.model_action_request 标记；请提交顶层 action_type 和对应动作字段，或改用普通助手正文回答用户。",
                    ),
                    "phase": phase,
                },
            ),
        )
    if not native_tool_calls:
        if assistant_text and _plain_assistant_text_is_allowed_response(
            assistant_text,
            allowed_action_types=allowed_action_types,
        ):
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=[],
                assistant_final_text=assistant_text,
            )
        if require_json_action:
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=native_tool_calls,
                error=_single_agent_protocol_error(
                    code="single_agent_turn_json_action_required",
                    reason="json_action_required",
                    diagnostics={
                        "parse_diagnostics": dict(protocol.parse_diagnostics or {}),
                        "action_issue": _protocol_action_issue(
                            category="protocol_violation",
                            code="json_action_required",
                            repair_instruction="本轮控制动作必须通过 JSON action 提交；不要使用普通正文或 provider-native tool call。",
                        ),
                        "phase": phase,
                    },
                ),
            )
        return SingleAgentActionParse(action_request=None, native_tool_calls=[])
    packet_public_progress_note = public_runtime_progress_summary(protocol.content).strip()
    native_parse = _action_requests_from_native_tool_calls_with_diagnostics(
        native_tool_calls,
        turn_id=turn_id,
        packet_ref=packet_ref,
        iteration=iteration,
        allowed_action_types=allowed_action_types,
        public_response_required=public_response_required,
        packet_public_response_present=bool(packet_public_progress_note),
        packet_public_progress_note=packet_public_progress_note,
    )
    native_actions = list(native_parse.actions)
    if native_parse.errors:
        error_reasons = [
            str(error.get("reason") or error.get("code") or "").strip()
            for error in native_parse.errors
            if str(error.get("reason") or error.get("code") or "").strip()
        ]
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_invalid_native_action",
                reason=";".join(error_reasons) or "single_agent_turn_invalid_native_action",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "native_action_errors": [dict(item) for item in native_parse.errors],
                    "action_issue": dict(native_parse.errors[0].get("action_issue") or {}) if native_parse.errors else {},
                    "phase": phase,
                },
            ),
        )
    tool_actions = tuple(item for item in native_actions if item.action_type == "tool_call")
    control_actions = tuple(item for item in native_actions if item.action_type != "tool_call")
    if control_actions and tool_actions:
        first_control = control_actions[0]
        first_tool = tool_actions[0]
        action_issue = _protocol_action_issue(
            category="protocol_violation",
            code="multiple_native_action_sources",
            requested_action_type=first_control.action_type,
            requested_tool_name=str(dict(first_tool.tool_call or {}).get("tool_name") or dict(first_tool.tool_call or {}).get("name") or ""),
            repair_instruction="同一轮只能提交一个控制动作，或一个普通工具动作集合；请保留真实决策并删除冲突的 native tool_call。",
        )
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_invalid_native_action",
                reason="multiple_native_action_sources",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "action_issue": action_issue,
                    "phase": phase,
                },
            ),
        )
    if len(control_actions) > 1:
        first_control = control_actions[0]
        action_issue = _protocol_action_issue(
            category="protocol_violation",
            code="multiple_native_control_actions",
            requested_action_type=first_control.action_type,
            repair_instruction="同一轮只能提交一个控制动作；请保留真实决策并删除其它 native 控制动作。",
        )
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_invalid_native_action",
                reason="multiple_native_control_actions",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "action_issue": action_issue,
                    "phase": phase,
                },
            ),
        )
    if tool_actions:
        if "tool_call" not in set(allowed_action_types or ()):
            action_issue = _protocol_action_issue(
                category="service_unavailable",
                code="native_tool_call_transport_not_available",
                requested_action_type="tool_call",
                requested_tool_name=str(dict(tool_actions[0].tool_call or {}).get("tool_name") or dict(tool_actions[0].tool_call or {}).get("name") or ""),
                repair_instruction="当前阶段没有开放普通工具调用服务面；请按本轮允许动作选择控制裁决、回答、询问或阻塞。",
            )
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=native_tool_calls,
                error=_single_agent_protocol_error(
                    code="single_agent_turn_invalid_native_action",
                    reason="native_tool_call_transport_not_available",
                    diagnostics={
                        "native_tool_call_count": len(native_tool_calls),
                        "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                        "allowed_action_types": list(allowed_action_types or ()),
                        "action_issue": action_issue,
                        "phase": phase,
                    },
                ),
            )
        return SingleAgentActionParse(
            action_request=tool_actions[0] if len(tool_actions) == 1 else None,
            native_tool_calls=native_tool_calls,
            tool_actions=tool_actions,
            packet_public_progress_note=packet_public_progress_note,
        )
    if control_actions:
        action = control_actions[0]
        return SingleAgentActionParse(
            action_request=action,
            native_tool_calls=native_tool_calls,
            control_action=action,
            packet_public_progress_note=packet_public_progress_note,
        )
    if require_json_action:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_json_action_required",
                reason="json_action_required",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "phase": phase,
                },
            ),
        )
    return SingleAgentActionParse(
        action_request=None,
        native_tool_calls=native_tool_calls,
        error=_single_agent_protocol_error(
            code="single_agent_turn_invalid_native_action",
            reason="single_agent_turn_invalid_native_action",
            diagnostics={
                "native_tool_call_count": len(native_tool_calls),
                "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                "phase": phase,
            },
        ),
    )


def _is_model_action_json_payload(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    authority = str(payload.get("authority") or "").strip()
    if authority == "harness.loop.model_action_request":
        return True
    if "authority" in payload:
        return True
    if "action_type" in payload:
        return True
    return authority.startswith("harness.loop.") and "action" in payload


def _json_action_parse_transport(parse_diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = dict(parse_diagnostics or {})
    return {
        "text_transport": "json_action",
        "markdown_fence": bool(
            diagnostics.get("unwrapped_markdown_fence") is True
            or diagnostics.get("parsed_from_markdown_fence") is True
        ),
        "embedded_action_object": bool(diagnostics.get("parsed_with_embedded_object_repair") is True),
        "trailing_text_repair": bool(diagnostics.get("parsed_with_trailing_repair") is True),
        "ignored_leading_text": str(diagnostics.get("ignored_leading_text") or ""),
        "ignored_trailing_text": str(diagnostics.get("ignored_trailing_text") or ""),
    }


def _looks_like_malformed_single_agent_action_payload(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    action_contract_keys = {
        "active_work_control",
        "blocking_reason",
        "completion_contract",
        "final_answer",
        "permission_request",
        "public_action_state",
        "public_progress_note",
        "recovery_resume",
        "selected_skill_ids",
        "task_contract_seed",
        "tool_call",
        "tool_calls",
        "user_question",
    }
    if action_contract_keys.intersection(payload):
        return True
    raw_action = str(payload.get("action") or "").strip()
    if not raw_action:
        return False
    return raw_action in _ACTIVE_WORK_CONTROL_ACTIONS


def _action_requests_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...] = ("respond", "tool_call"),
    public_response_required: bool = False,
    packet_public_response_present: bool = False,
    packet_public_progress_note: str = "",
) -> list[ModelActionRequest]:
    return list(
        _action_requests_from_native_tool_calls_with_diagnostics(
            tool_calls,
            turn_id=turn_id,
            packet_ref=packet_ref,
            iteration=iteration,
            allowed_action_types=allowed_action_types,
            public_response_required=public_response_required,
            packet_public_response_present=packet_public_response_present,
            packet_public_progress_note=packet_public_progress_note,
        ).actions
    )


def _action_requests_from_native_tool_calls_with_diagnostics(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...] = ("respond", "tool_call"),
    public_response_required: bool = False,
    packet_public_response_present: bool = False,
    packet_public_progress_note: str = "",
) -> NativeActionRequestParse:
    actions: list[ModelActionRequest] = []
    errors: list[dict[str, Any]] = []
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name:
            errors.append(
                {
                    "authority": "harness.loop.single_agent_turn.native_action_parser",
                    "code": "native_tool_name_missing",
                    "reason": "native_tool_name_missing",
                    "native_tool_call": _native_tool_call_diagnostics(call),
                    "action_issue": _protocol_action_issue(
                        category="protocol_violation",
                        code="native_tool_name_missing",
                        repair_instruction="请提交带有工具名的合法 tool_call，或改用符合本轮合同的 JSON action。",
                    ),
                    "repairable": True,
                }
            )
            continue
        if tool_name == "respond":
            action, error = _respond_action_request_from_native_tool_call(
                call,
                turn_id=turn_id,
                packet_ref=packet_ref,
                iteration=iteration,
                allowed_action_types=allowed_action_types,
            )
            if error is not None:
                errors.append(error)
                continue
        else:
            action, error = _control_action_request_from_native_tool_call(
                call,
                turn_id=turn_id,
                packet_ref=packet_ref,
                iteration=iteration,
                allowed_action_types=allowed_action_types,
                public_response_required=public_response_required,
            )
            if action is not None:
                pass
            elif error is not None:
                errors.append(error)
                continue
            elif control_error := _native_control_action_error(call):
                errors.append(control_error)
                continue
            else:
                action = _tool_action_request_from_native_tool_calls(
                    [call],
                    turn_id=turn_id,
                    packet_ref=packet_ref,
                    iteration=iteration,
                )
                error = None
        if error is not None:
            errors.append(error)
            continue
        if action is None:
            errors.append(
                {
                    "authority": "harness.loop.single_agent_turn.native_action_parser",
                    "code": "native_action_request_missing",
                    "reason": "native_action_request_missing",
                    "native_tool_call": _native_tool_call_diagnostics(call),
                    "action_issue": _protocol_action_issue(
                        category="protocol_violation",
                        code="native_action_request_missing",
                        requested_tool_name=tool_name,
                        repair_instruction="请重新提交一个可解析的工具调用或 JSON action。",
                    ),
                    "repairable": True,
                }
            )
            continue
        if packet_public_progress_note and not _model_action_request_has_public_response(action):
            public_action_state = dict(action.public_action_state or {})
            public_action_state.setdefault("current_judgment", packet_public_progress_note)
            public_action_state.setdefault("next_action", packet_public_progress_note)
            action = replace(
                action,
                public_progress_note=packet_public_progress_note,
                public_action_state=public_action_state,
                diagnostics={
                    **dict(action.diagnostics or {}),
                    "public_progress_note_source": "assistant_content_preamble",
                },
            )
        if (
            public_response_required
            and not packet_public_response_present
            and not _model_action_request_has_public_response(action)
        ):
            diagnostics = dict(action.diagnostics or {})
            contract_gaps = [
                str(item)
                for item in list(diagnostics.get("contract_gaps") or [])
                if str(item)
            ]
            if "public_response_missing_for_native_tool_call" not in contract_gaps:
                contract_gaps.append("public_response_missing_for_native_tool_call")
            action = replace(
                action,
                diagnostics={
                    **diagnostics,
                    "contract_gaps": contract_gaps,
                    "public_response_required": True,
                    "public_response_requirement_source": "tool_observation_feedback",
                },
            )
        actions.append(action)
    return NativeActionRequestParse(actions=tuple(actions), errors=tuple(errors))


def _respond_action_request_from_native_tool_call(
    call: dict[str, Any],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...],
) -> tuple[ModelActionRequest | None, dict[str, Any] | None]:
    allowed = {str(item) for item in list(allowed_action_types or ()) if str(item)}
    args = dict(call.get("args") or {})
    call_id = str(call.get("id") or "").strip()
    if not call_id:
        return None, {
            "authority": "harness.loop.single_agent_turn.native_action_parser",
            "code": "native_tool_call_id_missing",
            "reason": "native_tool_call_id_missing",
            "native_tool_call": _native_tool_call_diagnostics(call),
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="native_tool_call_id_missing",
                requested_action_type="respond",
                requested_tool_name="respond",
                repair_instruction="provider-native tool_call 必须带有规范化 id；请重新提交合法 tool_call，或改用 JSON respond action。",
            ),
            "repairable": True,
        }
    final_answer = str(args.get("final_answer") or "").strip()
    if "respond" not in allowed:
        return None, {
            "authority": "harness.loop.single_agent_turn.native_action_parser",
            "code": "native_respond_not_allowed_for_context",
            "reason": "native_respond_not_allowed_for_context",
            "native_tool_call": _native_tool_call_diagnostics(call),
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="respond_not_allowed_for_context",
                requested_action_type="respond",
                requested_tool_name="respond",
                repair_instruction="当前阶段不允许直接回答；请按本轮允许动作重新提交。",
            ),
            "repairable": True,
            "repair_contract": {"allowed_action_types": list(allowed_action_types or ())},
        }
    if not final_answer:
        return None, {
            "authority": "harness.loop.single_agent_turn.native_action_parser",
            "code": "native_respond_final_answer_required",
            "reason": "native_respond_final_answer_required",
            "native_tool_call": _native_tool_call_diagnostics(call),
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="final_answer_required_for_respond",
                requested_action_type="respond",
                requested_tool_name="respond",
                repair_instruction="respond 动作必须提供 final_answer；请保留原回答意图并补齐 final_answer。",
            ),
            "repairable": True,
            "repair_contract": {"required_transport": "native_respond", "required_args": ["final_answer"]},
        }
    return ModelActionRequest(
        request_id=f"model-action:{turn_id}:native-respond:{iteration}:{_stable_action_suffix(call_id or final_answer)}",
        turn_id=turn_id,
        action_type="respond",
        final_answer=final_answer,
        public_progress_note=public_runtime_progress_summary(args.get("public_progress_note") or "").strip(),
        public_action_state={},
        diagnostics={
            "origin_kind": "single_agent_turn_native_respond",
            "origin_authority": "harness.loop.single_agent_turn",
            "packet_ref": packet_ref,
            "native_tool_call": {
                "id": call_id,
                "name": "respond",
                "source": str(call.get("source") or ""),
            },
        },
    ), None


def _control_action_request_from_native_tool_call(
    call: dict[str, Any],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...],
    public_response_required: bool = False,
) -> tuple[ModelActionRequest | None, dict[str, Any] | None]:
    action_type = _direct_control_action_from_native_tool_call(call)
    if not action_type:
        return None, None
    allowed = {str(item) for item in list(allowed_action_types or ()) if str(item)}
    tool_name = str(dict(call or {}).get("name") or "").strip()
    call_id = str(dict(call or {}).get("id") or "").strip()
    if not call_id:
        return None, {
            "authority": "harness.loop.single_agent_turn.native_action_parser",
            "code": "native_tool_call_id_missing",
            "reason": "native_tool_call_id_missing",
            "native_tool_call": _native_tool_call_diagnostics(call),
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="native_tool_call_id_missing",
                requested_action_type=action_type,
                requested_tool_name=tool_name,
                repair_instruction="provider-native structured action 必须带有规范化 id；请重新提交合法结构化动作。",
            ),
            "repairable": True,
        }
    if allowed and action_type not in allowed:
        return None, {
            "authority": "harness.loop.single_agent_turn.native_action_parser",
            "code": "native_control_action_not_allowed_for_context",
            "reason": "native_control_action_not_allowed_for_context",
            "native_tool_call": _native_tool_call_diagnostics(call),
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="action_type_not_allowed_for_context",
                requested_action_type=action_type,
                requested_tool_name=tool_name,
                repair_instruction="该控制动作不在本轮允许动作内；请按 allowed_action_types 保留真实意图并重新选择合法动作。",
            ),
            "repairable": True,
            "repair_contract": {"allowed_action_types": list(allowed_action_types or ())},
        }
    args = dict(call.get("args") or {}) if isinstance(call.get("args"), dict) else {}
    payload = _model_action_payload_from_native_control_args(
        action_type=action_type,
        args=args,
        turn_id=turn_id,
        request_id=f"model-action:{turn_id}:native-control:{action_type}:{iteration}:{_stable_action_suffix(call_id or action_type)}",
        packet_ref=packet_ref,
        call_id=call_id,
        tool_name=tool_name,
        source=str(dict(call or {}).get("source") or ""),
    )
    action_request, diagnostics = model_action_request_from_payload(
        payload,
        turn_id=turn_id,
        public_response_required=public_response_required,
        allowed_action_types=allowed_action_types,
    )
    if action_request is None:
        repair_instruction = _invalid_json_action_repair_instruction(
            json_payload=payload,
            diagnostics=dict(diagnostics or {}),
        )
        return None, {
            "authority": "harness.loop.single_agent_turn.native_action_parser",
            "code": "invalid_native_control_action",
            "reason": ";".join(str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or []))
            or "invalid_native_control_action",
            "native_tool_call": _native_tool_call_diagnostics(call),
            "model_action_diagnostics": dict(diagnostics or {}),
            "normalized_action_payload": payload,
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="invalid_native_control_action",
                requested_action_type=action_type,
                requested_tool_name=tool_name,
                repair_instruction=repair_instruction,
            ),
            "repairable": True,
            "repair_contract": {
                "required_signal": "canonical_structured_control_action",
                "action_type": action_type,
                "allowed_action_types": list(allowed_action_types or ()),
            },
        }
    return replace(
        action_request,
        diagnostics={
            **dict(action_request.diagnostics or {}),
            "origin_kind": f"single_agent_turn_native_{action_type}",
            "origin_authority": "harness.loop.single_agent_turn",
            "packet_ref": packet_ref,
            "native_tool_call": {
                "id": call_id,
                "name": tool_name,
                "source": str(dict(call or {}).get("source") or ""),
            },
        },
    ), None


def _model_action_payload_from_native_control_args(
    *,
    action_type: str,
    args: dict[str, Any],
    turn_id: str,
    request_id: str,
    packet_ref: str,
    call_id: str,
    tool_name: str,
    source: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "authority": "harness.loop.model_action_request",
        "request_id": request_id,
        "turn_id": turn_id,
        "action_type": action_type,
        "diagnostics": {
            "origin_kind": f"single_agent_turn_native_{action_type}",
            "origin_authority": "harness.loop.single_agent_turn",
            "packet_ref": packet_ref,
            "native_tool_call": {"id": call_id, "name": tool_name, "source": source},
        },
    }
    for key in ("public_progress_note", "public_action_state", "completion_contract", "permission_request"):
        if key in args:
            payload[key] = args.get(key)
    if action_type == "ask_user":
        payload["user_question"] = args.get("user_question") or args.get("question") or args.get("prompt") or ""
        return payload
    if action_type == "block":
        payload["blocking_reason"] = args.get("blocking_reason") or args.get("reason") or args.get("message") or ""
        return payload
    if action_type == "active_work_control":
        active_work_control = args.get("active_work_control")
        payload["active_work_control"] = dict(active_work_control) if isinstance(active_work_control, dict) else dict(args)
        return payload
    if action_type == "resume_recoverable_work":
        recovery_resume = args.get("recovery_resume")
        if isinstance(recovery_resume, dict):
            payload["recovery_resume"] = dict(recovery_resume)
        else:
            payload["recovery_resume"] = {
                key: args.get(key)
                for key in _RECOVERY_RESUME_NESTED_FIELDS
                if _has_non_empty_native_arg(args.get(key))
            }
        return payload
    if action_type == "request_task_run":
        seed = args.get("task_contract_seed")
        payload["task_contract_seed"] = (
            _native_request_task_contract_seed(dict(seed))
            if isinstance(seed, dict)
            else _native_request_task_contract_seed(args)
        )
        return payload
    return payload


def _native_request_task_contract_seed(args: dict[str, Any]) -> dict[str, Any]:
    seed: dict[str, Any] = {}
    for field in _REQUEST_TASK_RUN_TASK_CONTRACT_FIELDS:
        if field not in args:
            continue
        value = args.get(field)
        if not _has_non_empty_native_arg(value):
            continue
        if field == "working_scope":
            seed[field] = _native_working_scope(value)
        else:
            seed[field] = value
    for field in _REQUEST_TASK_RUN_SYSTEM_SETTING_FIELDS:
        if _has_non_empty_native_arg(args.get(field)):
            seed[field] = args.get(field)
    return seed


def _native_working_scope(value: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return {"target_objects": list(value)}
    text = str(value or "").strip()
    return {"target_objects": [text]} if text else value


def _has_non_empty_native_arg(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(value)


def _native_tool_call_diagnostics(call: dict[str, Any]) -> dict[str, Any]:
    payload = dict(call or {})
    args = payload.get("args")
    return {
        "id": str(payload.get("id") or ""),
        "name": str(payload.get("name") or ""),
        "source": str(payload.get("source") or ""),
        "args": dict(args or {}) if isinstance(args, dict) else {},
    }


def _native_control_action_error(call: dict[str, Any]) -> dict[str, Any] | None:
    legacy_action_type = _legacy_control_action_from_native_tool_call(call)
    if legacy_action_type:
        tool_name = str(dict(call or {}).get("name") or "").strip()
        canonical_hint = _LEGACY_CONTROL_ACTION_HINTS.get(legacy_action_type, "")
        return {
            "authority": "harness.loop.single_agent_turn.native_action_parser",
            "code": "native_control_action_alias_not_allowed",
            "reason": "native_control_action_alias_not_allowed",
            "native_tool_call": _native_tool_call_diagnostics(call),
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="control_action_alias_not_allowed",
                requested_action_type=legacy_action_type,
                requested_tool_name=tool_name,
                repair_instruction=(
                    "旧控制动作名不再受理；请提交 canonical structured action，"
                    f"并使用 canonical action_type={canonical_hint or 'request_task_run'}。"
                ),
            ),
            "repairable": True,
            "repair_contract": {
                "required_signal": "canonical_structured_control_action",
                "canonical_action_type": canonical_hint,
            },
        }
    action_type = _control_action_from_native_tool_call(call)
    if not action_type:
        return None
    tool_name = str(dict(call or {}).get("name") or "").strip()
    return {
        "authority": "harness.loop.single_agent_turn.native_action_parser",
        "code": "native_control_action_command_transport_not_allowed",
        "reason": "native_control_action_command_transport_not_allowed",
        "native_tool_call": _native_tool_call_diagnostics(call),
        "action_issue": _protocol_action_issue(
            category="protocol_violation",
            code="control_action_command_transport_not_allowed",
            requested_action_type=action_type,
            requested_tool_name=tool_name,
            repair_instruction="命令文本不能伪装成控制动作；请保留原控制意图并改用 canonical structured action 重新提交。",
        ),
        "repairable": True,
        "repair_contract": {
            "required_signal": "canonical_structured_control_action",
            "action_type": action_type,
        },
    }


def _control_action_from_native_tool_call(call: dict[str, Any]) -> str:
    payload = dict(call or {})
    tool_name = str(payload.get("name") or "").strip()
    direct = _canonical_control_action_name(tool_name)
    if direct:
        return direct
    if tool_name.lower() not in _COMMAND_TRANSPORT_TOOL_NAMES:
        return ""
    return _control_action_from_command_transport_args(payload.get("args") or {})


def _canonical_control_action_name(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    if normalized in _CONTROL_ACTION_NAMES:
        return normalized
    return ""


def _legacy_control_action_from_native_tool_call(call: dict[str, Any]) -> str:
    payload = dict(call or {})
    tool_name = str(payload.get("name") or "").strip().lower()
    if tool_name in _LEGACY_CONTROL_ACTION_NAMES:
        return tool_name
    if tool_name not in _COMMAND_TRANSPORT_TOOL_NAMES:
        return ""
    legacy_token = _legacy_control_action_from_command_transport_args(payload.get("args") or {})
    if legacy_token:
        return legacy_token
    return ""


def _is_model_action_native_tool_name(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    if normalized in _MODEL_ACTION_NATIVE_TOOL_NAMES:
        return True
    return bool(_canonical_control_action_name(normalized))


def _control_action_from_command_transport_args(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    command = _command_transport_text(args)
    if not command:
        return ""
    normalized = " ".join(command.replace("\r", " ").replace("\n", " ").split()).strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    for prefix in _CONTROL_TOKEN_COMMAND_PREFIXES:
        if not lowered.startswith(prefix):
            continue
        remainder = normalized[len(prefix):].strip()
        if not remainder:
            continue
        control_token = _strip_command_token_wrappers(remainder)
        canonical = _canonical_control_action_name(control_token)
        if canonical:
            return canonical
    return ""


def _direct_control_action_from_native_tool_call(call: dict[str, Any]) -> str:
    payload = dict(call or {})
    tool_name = str(payload.get("name") or "").strip()
    return _canonical_control_action_name(tool_name)


def _legacy_control_action_from_command_transport_args(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    command = _command_transport_text(args)
    if not command:
        return ""
    normalized = " ".join(command.replace("\r", " ").replace("\n", " ").split()).strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    for prefix in _CONTROL_TOKEN_COMMAND_PREFIXES:
        if not lowered.startswith(prefix):
            continue
        remainder = normalized[len(prefix):].strip()
        if not remainder:
            continue
        control_token = _strip_command_token_wrappers(remainder).lower()
        if control_token in _LEGACY_CONTROL_ACTION_NAMES:
            return control_token
    return ""


def _command_transport_text(args: dict[str, Any]) -> str:
    for key in ("command", "cmd", "script", "input", "code"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _strip_command_token_wrappers(value: str) -> str:
    token = str(value or "").strip()
    for suffix in (";", "&&", "||"):
        if suffix in token:
            token = token.split(suffix, 1)[0].strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"', "`"}:
        token = token[1:-1].strip()
    return token.strip()


def _detected_json_action_transport_rejection(
    *,
    json_payload: dict[str, Any],
    protocol_errors: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    payload = dict(json_payload or {})
    if not _is_model_action_json_payload(payload):
        return {}
    errors = [str(item) for item in list(protocol_errors or ()) if str(item)]
    action_type = str(payload.get("action_type") or "").strip()
    task_contract_seed = dict(payload.get("task_contract_seed") or {}) if isinstance(payload.get("task_contract_seed"), dict) else {}
    tool_call = dict(payload.get("tool_call") or {}) if isinstance(payload.get("tool_call"), dict) else {}
    detected_action: dict[str, Any] = {
        "detected": True,
        "execution_state": "not_executed",
        "action_type": action_type,
        "authority": str(payload.get("authority") or "").strip(),
        "request_id": str(payload.get("request_id") or "").strip(),
        "reason": ";".join(errors),
        "top_level_keys": sorted(str(key) for key in payload.keys()),
    }
    if task_contract_seed:
        detected_action["task_contract_seed_summary"] = {
            "user_visible_goal": _compact_text(task_contract_seed.get("user_visible_goal"), limit=240),
            "task_run_goal": _compact_text(task_contract_seed.get("task_run_goal"), limit=240),
            "completion_criteria_count": len(list(task_contract_seed.get("completion_criteria") or []))
            if isinstance(task_contract_seed.get("completion_criteria"), list)
            else (1 if str(task_contract_seed.get("completion_criteria") or "").strip() else 0),
            "required_artifacts_count": len(list(task_contract_seed.get("required_artifacts") or []))
            if isinstance(task_contract_seed.get("required_artifacts"), list)
            else (1 if task_contract_seed.get("required_artifacts") else 0),
            "required_verifications_count": len(list(task_contract_seed.get("required_verifications") or []))
            if isinstance(task_contract_seed.get("required_verifications"), list)
            else (1 if task_contract_seed.get("required_verifications") else 0),
        }
    if tool_call:
        detected_action["tool_call_summary"] = {
            "tool_name": str(tool_call.get("tool_name") or tool_call.get("name") or "").strip(),
            "call_id": str(tool_call.get("id") or "").strip(),
        }
    return {
        "detected_json_action": detected_action,
        "rejected_json_action_payload": payload,
        "rejected_action_transport": {
            "execution_state": "not_executed",
            "required_transport": "single_unambiguous_structured_action",
            "actual_transport": "invalid_structured_action_protocol",
            "protocol_errors": errors,
            "resubmission_rule": (
                "如果这仍是 agent 的决策，请修正字段并作为唯一结构化动作重新提交；"
                "不要混入其它结构化动作来源。"
            ),
        },
        "repair_contract": {
            "required_transport": "single_unambiguous_structured_action",
            "required_shape": "one_action_like_object_or_one_provider_native_control_signal",
            "detected_action_type": action_type,
            "previous_action_execution_state": "not_executed",
        },
    }


def _json_action_transport_repair_instruction(
    *,
    protocol_error_code: str,
    detected_action_type: str = "",
) -> str:
    del protocol_error_code
    action_label = f" action_type={detected_action_type} 的" if detected_action_type else ""
    return (
        f"上一轮包含{action_label} JSON action，但该动作没有进入执行队列，"
        "所以没有执行，也没有写入任务或会话状态。"
        "如果这仍然是你的真实决策，请修正字段并作为唯一结构化动作重新提交。"
    )


def _protocol_action_issue(
    *,
    category: str,
    code: str,
    repair_instruction: str,
    requested_action_type: str = "",
    requested_tool_name: str = "",
) -> dict[str, Any]:
    return {
        "authority": "harness.loop.action_issue",
        "category": str(category or ""),
        "code": str(code or ""),
        "model_intent_preserved": True,
        "requested_action_type": str(requested_action_type or ""),
        "requested_tool_name": str(requested_tool_name or ""),
        "repair_instruction": str(repair_instruction or ""),
    }


_REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS = (
    "working_scope",
)
_REQUEST_TASK_RUN_SYSTEM_SETTING_FIELDS = (
    "capability_intent",
    "skill_intent",
    "observation_contract",
)
_REQUEST_TASK_RUN_TASK_CONTRACT_FIELDS = (
    "user_visible_goal",
    "task_run_goal",
    "completion_criteria",
    "required_artifacts",
    "artifact_requirements",
    "required_verifications",
    "verification_requirements",
    *_REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS,
)
_RECOVERY_RESUME_NESTED_FIELDS = ("task_run_id", "continuation_id")


def _request_task_run_minimal_repair_action() -> dict[str, Any]:
    return {
        "authority": "harness.loop.model_action_request",
        "action_type": "request_task_run",
        "public_progress_note": "说明为什么当前工作需要进入持续任务生命周期。",
        "public_action_state": {
            "current_judgment": "说明当前 turn 无法稳定承载的边界。",
            "next_action": "进入持续任务执行流程。",
        },
        "task_contract_seed": {
            "user_visible_goal": "用户能看懂的任务目标。",
            "task_run_goal": "执行生命周期要持续推进的具体任务目标。",
            "working_scope": {
                "target_objects": ["要处理的文件、模块、目录、对象或问题域"],
                "source_refs": ["用户消息或已观察证据"],
                "excluded_scope": [],
                "known_constraints": ["用户明确约束、质量要求或排除项"],
            },
            "completion_criteria": ["可验收完成标准"],
        },
    }


def _request_task_run_repair_template_text() -> str:
    return json.dumps(_request_task_run_minimal_repair_action(), ensure_ascii=False, indent=2)


def _protocol_error_requested_action_type(protocol_error: dict[str, Any]) -> str:
    diagnostics = dict(protocol_error.get("diagnostics") or {})
    action_issue = dict(diagnostics.get("action_issue") or {})
    for source in (
        action_issue,
        dict(diagnostics.get("detected_json_action") or {}),
        dict(diagnostics.get("rejected_json_action_payload") or {}),
    ):
        action_type = str(source.get("requested_action_type") or source.get("action_type") or "").strip()
        if action_type:
            return action_type
    native_errors = [dict(item) for item in list(diagnostics.get("native_action_errors") or []) if isinstance(item, dict)]
    for item in native_errors:
        action_issue = dict(item.get("action_issue") or {})
        action_type = str(action_issue.get("requested_action_type") or "").strip()
        if action_type:
            return action_type
    return ""


def _with_request_task_run_repair_template(prefix: str) -> str:
    return (
        f"{str(prefix or '').strip()} "
        "最小合法骨架如下；用你的当前任务目标、范围和证据替换占位文本，但保留这些键和层级：\n"
        f"{_request_task_run_repair_template_text()}"
    ).strip()


def _protocol_error_specific_repair_instruction(protocol_error: dict[str, Any]) -> str:
    diagnostics = dict(protocol_error.get("diagnostics") or {})
    action_issue = dict(diagnostics.get("action_issue") or {})
    return str(action_issue.get("repair_instruction") or "").strip()


def _invalid_json_action_repair_instruction(*, json_payload: dict[str, Any], diagnostics: dict[str, Any]) -> str:
    default = "请按本轮 model_decision_contract 和 action schema 重新提交一个合法 JSON action。"
    payload = dict(json_payload or {})
    action_type = str(payload.get("action_type") or "").strip()
    if action_type == "resume_recoverable_work":
        errors = {str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or [])}
        recovery_resume = payload.get("recovery_resume")
        recovery_resume_obj = dict(recovery_resume or {}) if isinstance(recovery_resume, dict) else {}
        misplaced_top_level = [field for field in _RECOVERY_RESUME_NESTED_FIELDS if field in payload]
        payload_wrapper = payload.get("payload") if isinstance(payload.get("payload"), dict) else None
        if misplaced_top_level or payload_wrapper is not None:
            misplaced = "、".join(misplaced_top_level) if misplaced_top_level else "payload"
            return (
                "resume_recoverable_work 的恢复句柄字段放错层级。不要把 "
                f"{misplaced} 放在 JSON 顶层，也不要使用 payload 包裹。"
                "请保留 action_type=resume_recoverable_work，并把 task_run_id、continuation_id "
                "全部放入 recovery_resume 对象内。只使用 recovery_resume 候选中的可恢复句柄，不要从旧消息文本猜测。"
            )
        if (
            "recovery_resume.task_run_id_required" in errors
            or "recovery_resume.continuation_id_required" in errors
            or not isinstance(recovery_resume, dict)
        ):
            missing = [
                field
                for field in _RECOVERY_RESUME_NESTED_FIELDS
                if not str(recovery_resume_obj.get(field) or "").strip()
            ]
            missing_text = "、".join(missing) if missing else "必需字段"
            return (
                "resume_recoverable_work 必须包含 recovery_resume 对象。请在 recovery_resume 内补齐 "
                f"{missing_text}；task_run_id 和 continuation_id 必须来自当前可恢复上下文。"
            )
        return default
    if action_type != "request_task_run":
        return default
    errors = {str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or [])}
    task_seed = payload.get("task_contract_seed")
    task_seed_obj = dict(task_seed or {}) if isinstance(task_seed, dict) else {}
    misplaced_top_level = [field for field in _REQUEST_TASK_RUN_TASK_CONTRACT_FIELDS if field in payload]
    payload_wrapper = payload.get("payload") if isinstance(payload.get("payload"), dict) else None
    if misplaced_top_level or payload_wrapper is not None:
        misplaced = "、".join(misplaced_top_level) if misplaced_top_level else "payload"
        return _with_request_task_run_repair_template(
            "request_task_run 的任务字段放错层级。不要把 "
            f"{misplaced} 放在 JSON 顶层，也不要使用 payload 包裹。"
            "请保留 action_type=request_task_run，把任务目标、working_scope 和完成证据放入 task_contract_seed 内。"
        )
    if any(str(item).startswith("system_execution_field_not_allowed_in_task_contract") for item in errors):
        return _with_request_task_run_repair_template(
            "request_task_run 的任务合同只接收任务目标、working_scope 和完成证据；请删除不属于任务合同的执行配置字段。"
        )
    required_errors = {
        f"{field}_required_for_request_task_run" for field in _REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS
    }
    if errors.intersection(required_errors) or "working_scope.target_objects_required_for_request_task_run" in errors:
        missing = [
            field
            for field in _REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS
            if field not in task_seed_obj or not isinstance(task_seed_obj.get(field), dict)
        ]
        if not missing and "working_scope.target_objects_required_for_request_task_run" in errors:
            missing.append("working_scope.target_objects")
        missing_text = "、".join(missing) if missing else "必需字段"
        return _with_request_task_run_repair_template(
            "request_task_run 必须提交完整 task_contract_seed。请在 task_contract_seed 内补齐 "
            f"{missing_text}。"
        )
    if "task_contract_seed_required_for_request_task_run" in errors:
        return _with_request_task_run_repair_template(
            "request_task_run 必须包含 task_contract_seed，且任务目标、范围和完成标准都必须放在 task_contract_seed 内。"
        )
    if (
        "user_visible_goal_required_for_request_task_run" in errors
        or "task_run_goal_required_for_request_task_run" in errors
    ):
        return (
            "request_task_run 必须在 task_contract_seed 内写清任务目标。"
            "请补齐 user_visible_goal 和 task_run_goal：前者是用户能看懂的任务目标，"
            "后者是执行器可持续推进的内部任务目标；不要把它们放在 JSON 顶层。"
        )
    if "completion_evidence_required_for_request_task_run" in errors:
        return (
            "request_task_run 必须声明完成证据。请在 task_contract_seed 内提供 "
            "completion_criteria、required_artifacts 或 required_verifications；"
            "只有可验收标准明确时，持续任务才能启动。"
        )
    return default


def _single_agent_protocol_error(*, code: str, reason: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "reason": reason,
        "diagnostics": {
            "authority": "harness.loop.single_agent_turn.protocol_error",
            **dict(diagnostics or {}),
        },
    }


def _native_tools_for_packet(allowed_action_types: tuple[str, ...], *, available_tools: tuple[dict[str, Any], ...] = ()) -> list[dict[str, Any]]:
    allowed = set(allowed_action_types or ())
    if "tool_call" not in allowed:
        return []
    executable_tools = tuple(
        dict(item)
        for item in tuple(available_tools or ())
        if isinstance(item, dict)
        and not _is_model_action_native_tool_name(item.get("tool_name") or item.get("name"))
    )
    return provider_tool_bindings_for_available_tools(executable_tools)


def _tool_action_request_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
) -> ModelActionRequest | None:
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name or _control_action_from_native_tool_call(call):
            continue
        args = dict(call.get("args") or {})
        call_id = str(call.get("id") or "").strip()
        if not call_id:
            continue
        public_note = _native_tool_public_note(args)
        public_action_state = {"completion_status": "waiting_for_tool"}
        diagnostics: dict[str, Any] = {
            "origin_kind": "single_agent_turn_native_tool_call",
            "origin_authority": "harness.loop.single_agent_turn",
            "packet_ref": packet_ref,
            "native_tool_call": {
                "id": call_id,
                "name": tool_name,
                "source": str(call.get("source") or ""),
            },
        }
        if public_note:
            public_action_state["current_judgment"] = public_note
        else:
            diagnostics["contract_gaps"] = ["public_progress_note_missing_for_native_tool_call"]
        return ModelActionRequest(
            request_id=f"model-action:{turn_id}:single-agent-tool:{iteration}:{_stable_action_suffix(call_id or tool_name)}",
            turn_id=turn_id,
            action_type="tool_call",
            public_progress_note=public_note,
            public_action_state=public_action_state,
            tool_call={"tool_name": tool_name, "name": tool_name, "id": call_id, "args": args},
            diagnostics=diagnostics,
        )
    return None


def _model_action_request_has_public_response(action_request: ModelActionRequest) -> bool:
    if str(action_request.public_progress_note or "").strip():
        return True
    if str(dict(action_request.public_action_state or {}).get("current_judgment") or "").strip():
        return True
    if action_request.action_type == "respond":
        return bool(str(action_request.final_answer or "").strip())
    if action_request.action_type == "ask_user":
        return bool(str(action_request.user_question or "").strip())
    if action_request.action_type == "block":
        return bool(str(action_request.blocking_reason or "").strip())
    return False


_TOOL_OBSERVATION_FAILURE_STATUSES = {
    "error",
    "failed",
    "denied",
    "needs_contract",
    "aborted",
    "canceled",
    "cancelled",
}


def _tool_followup_public_response_required(
    tool_iteration: int,
    recent_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> bool:
    if int(tool_iteration or 0) <= 0:
        return True
    return any(_tool_observation_requires_model_feedback(item) for item in list(recent_observations or []))


def _tool_observation_requires_model_feedback(observation: dict[str, Any]) -> bool:
    payload = dict(observation or {})
    status = _normalized_tool_status(payload.get("status"))
    if status in _TOOL_OBSERVATION_FAILURE_STATUSES:
        return True
    if status == "needs_approval":
        return False
    envelope = dict(payload.get("result_envelope") or {})
    envelope_status = _normalized_tool_status(envelope.get("status"))
    if envelope_status in _TOOL_OBSERVATION_FAILURE_STATUSES:
        return True
    if str(envelope.get("error") or envelope.get("error_code") or "").strip():
        return True
    execution_receipt = dict(payload.get("execution_receipt") or envelope.get("execution_receipt") or {})
    receipt_status = _normalized_tool_status(execution_receipt.get("status"))
    if receipt_status in _TOOL_OBSERVATION_FAILURE_STATUSES:
        return True
    return False


def _normalized_tool_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _native_tool_public_note(args: dict[str, Any]) -> str:
    for key in (
        "public_progress_note",
        "public_note",
        "current_judgment",
        "reason",
        "purpose",
        "user_visible_reason",
    ):
        text = public_runtime_progress_summary(args.get(key) or "").strip()
        if text:
            return text[:160].rstrip()
    return ""


def _native_tool_public_target(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "target_path", "query", "pattern", "url", "command", "cmd", "script", "code"):
        value = str(args.get(key) or "").strip()
        if value:
            return value[:120]
    return ""


def _native_tool_arguments_preview(args: dict[str, Any]) -> str:
    if not args:
        return ""
    priority = ("path", "file_path", "target_path", "query", "pattern", "url", "start_line", "line_count", "command")
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


def _stable_action_suffix(value: str) -> str:
    import hashlib

    text = str(value or "").strip() or "tool-call"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _runtime_profile_payload(runtime_assembly: Any) -> dict[str, Any]:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    return dict(payload.get("profile") or {})


def _turn_runtime_permission_mode(runtime_assembly: Any, *, runtime_host: Any | None = None) -> str:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    for candidate in (
        assembly_payload.get("permission_mode"),
        dict(assembly_payload.get("diagnostics") or {}).get("permission_mode"),
    ):
        text = str(candidate or "").strip()
        if text:
            return normalize_permission_mode(text)
    if runtime_host is not None and hasattr(runtime_host, "_current_permission_mode"):
        return normalize_permission_mode(runtime_host._current_permission_mode())
    return "default"


def _tool_call_from_action_request(action_request: ModelActionRequest) -> dict[str, Any]:
    tool_call = dict(action_request.tool_call or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    tool_call_id = _canonical_action_tool_call_id(action_request)
    tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    return {
        "id": tool_call_id,
        "name": tool_name,
        "tool_name": tool_name,
        "args": tool_args,
        "type": "tool_call",
    }


def _canonical_action_tool_call_id(action_request: ModelActionRequest) -> str:
    return canonical_action_tool_call_id(action_request)


def _turn_action_tool_invocation_identity(
    runtime_host: Any,
    *,
    turn_run: TurnRun | None,
    turn_id: str,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
    action_permit: dict[str, Any],
    action_lifecycle_ref: str = "",
):
    definitions = getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {})
    return build_action_tool_invocation_identity(
        action_request,
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        definitions_by_name=dict(definitions or {}),
        admission=admission,
        action_permit=dict(action_permit or {}),
        action_lifecycle_ref=action_lifecycle_ref,
    )


def _tool_observation_from_admission(
    *,
    runtime_host: Any,
    turn_run: TurnRun | None,
    turn_id: str,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
    action_permit: dict[str, Any],
    packet_ref: str,
    tool_plan: Any,
) -> ToolObservation:
    recovery = build_action_admission_recovery_payload(action_request, admission)
    identity = _turn_action_tool_invocation_identity(
        runtime_host,
        turn_run=turn_run,
        turn_id=turn_id,
        action_request=action_request,
        admission=admission,
        action_permit=dict(action_permit or {}),
        action_lifecycle_ref=str(dict(recovery.payload or {}).get("action_lifecycle_ref") or ""),
    )
    status = recovery.status
    system_reason = recovery.error_code
    text = recovery.summary
    action_issue = dict(getattr(admission, "action_issue", {}) or {})
    return ToolObservation(
        observation_id=f"toolobs:{identity.invocation_id}:{uuid.uuid4().hex[:8]}",
        invocation_id=identity.invocation_id,
        caller_kind="agent_turn",
        caller_ref=identity.caller_ref,
        tool_name=identity.tool_name,
        operation_id=identity.operation_id,
        status=status,
        text=text,
        result_envelope={
            "tool_call_id": identity.tool_call_id,
            **dict(recovery.payload or {}),
            "retryable": True,
        },
        operation_gate={
            "admission": admission.to_dict(),
            "action_permit": identity.action_permit,
            "tool_plan_ref": str(getattr(tool_plan, "plan_id", "") or ""),
        },
        diagnostics={
            "stage": "model_action_admission",
            "packet_ref": packet_ref,
            "action_request": action_request.to_dict(),
            "action_issue": action_issue,
            "action_lifecycle_ref": str(dict(recovery.payload or {}).get("action_lifecycle_ref") or ""),
            "model_visible_recovery_observation": recovery.model_visible_recovery_observation,
        },
    )


def _tool_observation_from_runtime_exception(
    *,
    runtime_host: Any,
    turn_run: TurnRun | None,
    turn_id: str,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
    action_permit: dict[str, Any],
    packet_ref: str,
    tool_plan: Any,
    error: BaseException,
) -> ToolObservation:
    identity = _turn_action_tool_invocation_identity(
        runtime_host,
        turn_run=turn_run,
        turn_id=turn_id,
        action_request=action_request,
        admission=admission,
        action_permit=dict(action_permit or {}),
        action_lifecycle_ref=str(dict(action_permit or {}).get("action_lifecycle_ref") or ""),
    )
    error_text = _compact_text(str(error), limit=1000) or type(error).__name__
    return ToolObservation(
        observation_id=f"toolobs:{identity.invocation_id}:{uuid.uuid4().hex[:8]}",
        invocation_id=identity.invocation_id,
        caller_kind="agent_turn",
        caller_ref=identity.caller_ref,
        tool_name=identity.tool_name,
        operation_id=identity.operation_id,
        status="error",
        text=f"工具调用返回执行错误：{error_text}。请基于该错误调整下一步，不要重复同一失败动作。",
        result_envelope={
            "tool_call_id": identity.tool_call_id,
            "action_request_ref": identity.action_request_ref,
            "action_lifecycle_ref": identity.action_lifecycle_ref,
            "error": error_text,
            "error_code": type(error).__name__,
            "retryable": True,
        },
        operation_gate={
            "admission": admission.to_dict(),
            "action_permit": identity.action_permit,
            "tool_plan_ref": str(getattr(tool_plan, "plan_id", "") or ""),
        },
        diagnostics={
            "stage": "tool_runtime_exception",
            "packet_ref": packet_ref,
            "exception_type": type(error).__name__,
            "action_request": action_request.to_dict(),
            "action_lifecycle_ref": identity.action_lifecycle_ref,
            "model_visible_recovery_observation": True,
        },
    )


def _agent_turn_approval_requires_task_run_observation(observation: ToolObservation) -> ToolObservation:
    reason = "single_agent_turn_tool_approval_requires_resumable_task"
    return replace(
        observation,
        status="denied",
        text=(
            "该工具调用需要可恢复的人工确认；当前单轮对话没有持久审批恢复入口。"
            "请改为发起持续任务，或向用户说明需要进入可恢复任务后执行。"
        ),
        result_envelope={
            **dict(observation.result_envelope or {}),
            "status": "denied",
            "error": reason,
            "error_code": reason,
            "retryable": True,
            "task_run_required": True,
        },
        operation_gate={
            **dict(observation.operation_gate or {}),
            "decision": "deny",
            "reason": reason,
            "pipeline_stage": "task_run_required_for_tool_approval",
            "original_decision": dict(observation.operation_gate or {}).get("decision") or "requires_approval",
        },
        diagnostics={
            **dict(observation.diagnostics or {}),
            "stage": "agent_turn_approval_requires_task_run",
            "model_visible_recovery_observation": True,
            "original_status": "needs_approval",
        },
    )


async def _execute_tool_batch_group(
    group: ToolBatchGroup,
    *,
    invocation_rows: list[dict[str, Any]],
    runtime_host: Any,
    runtime_assembly: Any,
    turn_run: TurnRun | None,
    session_id: str,
    turn_id: str,
    packet_ref: str,
    tool_plan: Any,
) -> list[ToolObservation]:
    row_indexes: list[int] = []
    for raw_index in list(group.item_indexes or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(invocation_rows):
            row_indexes.append(index)
    if not row_indexes:
        return []
    timeout_seconds = _tool_batch_group_timeout_seconds(runtime_assembly)
    if group.parallel and len(row_indexes) > 1:
        tasks = {
            asyncio.create_task(
                _invoke_turn_tool_for_batch_row(
                    invocation_rows[index],
                    runtime_host=runtime_host,
                    runtime_assembly=runtime_assembly,
                    turn_run=turn_run,
                    session_id=session_id,
                    turn_id=turn_id,
                    packet_ref=packet_ref,
                    tool_plan=tool_plan,
                )
            ): index
            for index in row_indexes
        }
        done, pending = await asyncio.wait(tasks, timeout=timeout_seconds if timeout_seconds > 0 else None)
        if pending:
            for task in pending:
                task.cancel()
            await _drain_cancelled_tool_tasks(pending)
        results_by_index: dict[int, Any] = {}
        for task in done:
            row_index = tasks[task]
            try:
                results_by_index[row_index] = task.result()
            except asyncio.CancelledError as exc:
                raise exc
            except BaseException as exc:
                results_by_index[row_index] = exc
        for task in pending:
            results_by_index[tasks[task]] = TimeoutError(f"tool_batch_group_timeout_after_{timeout_seconds:g}s")
        observations: list[ToolObservation] = []
        for row_index in row_indexes:
            row = invocation_rows[row_index]
            result = results_by_index.get(row_index, RuntimeError("tool_batch_group_missing_result"))
            if isinstance(result, asyncio.CancelledError):
                raise result
            observation = _observation_from_batch_result(
                result,
                row=row,
                runtime_host=runtime_host,
                turn_run=turn_run,
                turn_id=turn_id,
                packet_ref=packet_ref,
                tool_plan=tool_plan,
            )
            row["observation"] = observation
            observations.append(observation)
        return observations

    observations = []
    for row_index in row_indexes:
        row = invocation_rows[row_index]
        task: asyncio.Task[ToolObservation] | None = None
        try:
            task = asyncio.create_task(_invoke_turn_tool_for_batch_row(
                row,
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly,
                turn_run=turn_run,
                session_id=session_id,
                turn_id=turn_id,
                packet_ref=packet_ref,
                tool_plan=tool_plan,
            ))
            if timeout_seconds > 0:
                done, pending = await asyncio.wait({task}, timeout=timeout_seconds)
                if pending:
                    task.cancel()
                    await _drain_cancelled_tool_tasks({task})
                    result = TimeoutError(f"tool_batch_group_timeout_after_{timeout_seconds:g}s")
                else:
                    result = next(iter(done)).result()
            else:
                result = await task
        except asyncio.CancelledError:
            if task is not None and not task.done():
                task.cancel()
            raise
        except BaseException as exc:
            result = exc
        observation = _observation_from_batch_result(
            result,
            row=row,
            runtime_host=runtime_host,
            turn_run=turn_run,
            turn_id=turn_id,
            packet_ref=packet_ref,
            tool_plan=tool_plan,
        )
        row["observation"] = observation
        observations.append(observation)
    return observations


async def _drain_cancelled_tool_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    if not tasks:
        return
    done, still_pending = await asyncio.wait(tasks, timeout=_TOOL_BATCH_CANCEL_DRAIN_SECONDS)
    for task in done:
        _consume_tool_task_result(task)
    for task in still_pending:
        task.add_done_callback(_consume_tool_task_result)


def _consume_tool_task_result(task: asyncio.Task[Any]) -> None:
    try:
        task.exception()
    except BaseException:
        return


def _tool_batch_group_timeout_seconds(runtime_assembly: Any) -> float:
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
    return _DEFAULT_INTERACTIVE_TOOL_BATCH_TIMEOUT_SECONDS


async def _invoke_turn_tool_for_batch_row(
    row: dict[str, Any],
    *,
    runtime_host: Any,
    runtime_assembly: Any,
    turn_run: TurnRun | None,
    session_id: str,
    turn_id: str,
    packet_ref: str,
    tool_plan: Any,
) -> ToolObservation:
    return await _invoke_turn_tool(
        runtime_host=runtime_host,
        runtime_assembly=runtime_assembly,
        turn_run=turn_run,
        session_id=session_id,
        turn_id=turn_id,
        action_request=row["action_request"],
        admission=row["admission"],
        action_permit=dict(row.get("action_permit") or {}),
        packet_ref=packet_ref,
        tool_plan=tool_plan,
    )


def _observation_from_batch_result(
    result: Any,
    *,
    row: dict[str, Any],
    runtime_host: Any,
    turn_run: TurnRun | None,
    turn_id: str,
    packet_ref: str,
    tool_plan: Any,
) -> ToolObservation:
    if isinstance(result, ToolObservation):
        return result
    error: BaseException
    if isinstance(result, BaseException):
        error = result
    else:
        error = RuntimeError("tool_invocation_invalid_observation")
    return _tool_observation_from_runtime_exception(
        runtime_host=runtime_host,
        turn_run=turn_run,
        turn_id=turn_id,
        action_request=row["action_request"],
        admission=row["admission"],
        action_permit=dict(row.get("action_permit") or {}),
        packet_ref=packet_ref,
        tool_plan=tool_plan,
        error=error,
    )


async def _invoke_turn_tool(
    *,
    runtime_host: Any,
    runtime_assembly: Any,
    turn_run: TurnRun | None,
    session_id: str,
    turn_id: str,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
    action_permit: dict[str, Any],
    packet_ref: str,
    tool_plan: Any,
):
    tool_call = _tool_call_from_action_request(action_request)
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    identity = _turn_action_tool_invocation_identity(
        runtime_host,
        turn_run=turn_run,
        turn_id=turn_id,
        action_request=action_request,
        admission=admission,
        action_permit=dict(action_permit or {}),
        action_lifecycle_ref=str(dict(action_permit or {}).get("action_lifecycle_ref") or ""),
    )
    tool_name = identity.tool_name
    tool_call_id = identity.tool_call_id
    tool_args = identity.tool_args
    operation_id = identity.operation_id
    invocation_id = identity.invocation_id
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    sandbox_scope = _single_turn_sandbox_scope(assembly_payload, runtime_host=runtime_host, turn_id=turn_id)
    agent_scope = _turn_run_agent_scope(
        runtime_host,
        turn_run=turn_run,
        session_id=session_id,
        turn_id=turn_id,
    )
    request = ToolInvocationRequest(
        invocation_id=invocation_id,
        caller_kind="agent_turn",
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        session_id=session_id,
        turn_id=turn_id,
        agent_run_id=str(agent_scope.get("agent_run_id") or ""),
        run_cell_id=str(agent_scope.get("run_cell_id") or ""),
        action_request_ref=action_request.request_id,
        packet_ref=packet_ref,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args,
        operation_id=operation_id,
        tool_plan_ref=str(getattr(tool_plan, "plan_id", "") or ""),
        admission_ref=identity.admission_ref,
        action_permit=identity.action_permit,
        permission_mode=_turn_runtime_permission_mode(runtime_assembly, runtime_host=runtime_host),
        sandbox_scope=sandbox_scope,
        file_scope=compile_tool_file_management_policy(
            dict(assembly_payload.get("task_environment") or {}),
            sandbox_policy=sandbox_scope,
        ),
        file_evidence_scope=session_file_evidence_scope(session_id),
        requested_constraints={
            "runtime_host": runtime_host,
            "runtime_assembly": assembly_payload,
            "agent_scope": agent_scope,
            "backend_dir": str(getattr(runtime_host, "backend_dir", "") or assembly_payload.get("backend_dir") or ""),
        },
    )
    control_plane = getattr(runtime_host, "tool_control_plane", None)
    if control_plane is None:
        from runtime.tool_runtime import ToolObservation

        return ToolObservation(
            observation_id=f"toolobs:{invocation_id}:{uuid.uuid4().hex[:8]}",
            invocation_id=invocation_id,
            caller_kind="agent_turn",
            caller_ref=request.caller_ref,
            tool_name=tool_name,
            operation_id=operation_id,
            status="error",
            text="runtime_tool_control_plane_unavailable",
            result_envelope={
                "tool_call_id": tool_call_id,
                "error": "runtime_tool_control_plane_unavailable",
                "error_code": "runtime_tool_control_plane_unavailable",
                "retryable": True,
            },
            diagnostics={
                "stage": "runtime_tool_control_plane_unavailable",
                "action_request": action_request.to_dict(),
            },
        )
    observation = await control_plane.invoke(request, tool_plan=tool_plan)
    return _publish_turn_tool_artifacts(
        observation,
        runtime_host=runtime_host,
        sandbox_policy=sandbox_scope,
    )


def _publish_turn_tool_artifacts(
    observation: ToolObservation,
    *,
    runtime_host: Any,
    sandbox_policy: dict[str, Any],
) -> ToolObservation:
    if observation.status != "ok" or not observation.artifact_refs:
        return observation
    if dict(sandbox_policy or {}).get("enabled") is not True:
        return observation
    publishable_refs = _publishable_observation_artifact_refs(observation, sandbox_policy=sandbox_policy)
    if not publishable_refs:
        return observation
    try:
        project_root = _turn_tool_artifact_project_root(runtime_host=runtime_host, sandbox_policy=sandbox_policy)
        published_refs = publish_sandbox_artifact_refs(
            project_root=project_root,
            sandbox_policy=sandbox_policy,
            artifact_refs=publishable_refs,
        )
    except Exception as exc:
        return _turn_tool_artifact_publish_error_observation(observation, error=str(exc), artifact_refs=publishable_refs)
    if not published_refs:
        paths = ", ".join(sorted({str(ref.get("path") or "") for ref in publishable_refs if str(ref.get("path") or "").strip()}))
        return _turn_tool_artifact_publish_error_observation(
            observation,
            error=f"sandbox_artifact_publish_failed: {paths or 'artifact path unavailable'}",
            artifact_refs=publishable_refs,
        )
    requested_paths = _artifact_ref_path_set(publishable_refs)
    published_paths = _artifact_ref_path_set(published_refs)
    missing_paths = sorted(requested_paths - published_paths)
    if missing_paths:
        return _turn_tool_artifact_publish_error_observation(
            observation,
            error=f"sandbox_artifact_publish_incomplete: {', '.join(missing_paths)}",
            artifact_refs=publishable_refs,
        )
    return replace(
        observation,
        artifact_refs=tuple(dict(item) for item in published_refs),
        result_envelope=_result_envelope_with_published_artifacts(observation.result_envelope, published_refs=published_refs),
        diagnostics={
            **dict(observation.diagnostics or {}),
            "sandbox_artifact_publish": {
                "status": "published",
                "artifact_refs": [dict(item) for item in published_refs],
                "authority": "harness.loop.single_agent_turn",
            },
        },
    )


def _publishable_observation_artifact_refs(
    observation: ToolObservation,
    *,
    sandbox_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    artifact_root = str(sandbox_policy.get("artifact_root") or "")
    publish_roots = tuple(sandbox_publish_scopes(sandbox_policy))
    result: list[dict[str, Any]] = []
    for ref in observation.artifact_refs:
        payload = dict(ref or {})
        if _artifact_ref_bypasses_sandbox_publish(payload):
            continue
        logical_path = str(payload.get("path") or payload.get("published_path") or payload.get("src") or "")
        if logical_path_publish_allowed(logical_path, artifact_root, publish_roots):
            result.append(payload)
    return result


def _artifact_ref_bypasses_sandbox_publish(ref: dict[str, Any]) -> bool:
    return bool(ref.get("bypass_sandbox_publish") is True) or str(ref.get("storage_authority") or "") == "image_asset_store"


def _artifact_ref_path_set(refs: list[dict[str, Any]]) -> set[str]:
    return {
        str(ref.get("path") or ref.get("published_path") or ref.get("src") or "").replace("\\", "/").strip().strip("/")
        for ref in refs
        if str(ref.get("path") or ref.get("published_path") or ref.get("src") or "").strip()
    }


def _turn_tool_artifact_project_root(*, runtime_host: Any, sandbox_policy: dict[str, Any]) -> Path:
    workspace_root = str(dict(sandbox_policy or {}).get("workspace_root") or "").strip()
    if workspace_root:
        return Path(workspace_root).resolve()
    return ProjectLayout.from_backend_dir(Path(str(getattr(runtime_host, "backend_dir", "") or ".")).resolve()).project_root.resolve()


def _result_envelope_with_published_artifacts(
    envelope: dict[str, Any],
    *,
    published_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(envelope or {})
    structured = dict(updated.get("structured_payload") or {})
    refs = [dict(item) for item in published_refs]
    updated["artifact_refs"] = refs
    structured["artifact_refs"] = refs
    tool_result = dict(structured.get("tool_result") or {})
    if len(refs) == 1:
        ref = refs[0]
        tool_result.update(
            {
                "path": str(ref.get("path") or tool_result.get("path") or ""),
                "absolute_path": str(ref.get("absolute_path") or ""),
                "published": True,
            }
        )
        if ref.get("size_bytes") is not None:
            tool_result["size_bytes"] = ref.get("size_bytes")
    if tool_result:
        structured["tool_result"] = tool_result
    updated["structured_payload"] = structured
    return updated


def _turn_tool_artifact_publish_error_observation(
    observation: ToolObservation,
    *,
    error: str,
    artifact_refs: list[dict[str, Any]],
) -> ToolObservation:
    text = (
        "Tool execution wrote a sandbox artifact, but it was not published to the real workspace. "
        f"Do not treat the write as complete. Error: {error}"
    )
    envelope = dict(observation.result_envelope or {})
    envelope["status"] = "error"
    envelope["error"] = text
    envelope["text"] = text
    envelope["artifact_refs"] = []
    structured = dict(envelope.get("structured_payload") or {})
    structured["artifact_refs"] = []
    envelope["structured_payload"] = structured
    return replace(
        observation,
        status="error",
        text=text,
        artifact_refs=(),
        result_envelope=envelope,
        diagnostics={
            **dict(observation.diagnostics or {}),
            "sandbox_artifact_publish": {
                "status": "error",
                "error": error,
                "artifact_refs": [dict(item) for item in artifact_refs],
                "authority": "harness.loop.single_agent_turn",
            },
        },
    )


def _single_turn_sandbox_scope(
    assembly_payload: dict[str, Any],
    *,
    runtime_host: Any,
    turn_id: str,
) -> dict[str, Any]:
    environment = dict(assembly_payload.get("task_environment") or {})
    sandbox = dict(environment.get("sandbox_policy") or {})
    storage = dict(environment.get("storage_space") or {})
    scope = compile_sandbox_execution_scope(
        environment_payload=environment,
        contract={},
        safety_envelope={},
    )
    project_root = Path(_single_turn_workspace_root(assembly_payload, runtime_host=runtime_host)).resolve()
    ensure_environment_storage_dirs(project_root=project_root, storage_space=storage)
    sandbox_root = str(sandbox.get("sandbox_root") or "").strip()
    if not sandbox_root:
        namespace = str(turn_id or assembly_payload.get("turn_id") or "single_turn").replace(":", "_")
        sandbox_root = str(
            runtime_cache_manager_for_host(runtime_host).sandbox_root(
                namespace,
                owner="single_turn_sandbox",
                source_refs=(str(turn_id or ""),),
                ttl_seconds=DEFAULT_SANDBOX_CACHE_TTL_SECONDS,
            )
        )
    if storage.get("workspace_root") and "workspace_root" not in sandbox:
        sandbox["workspace_root"] = str(storage.get("workspace_root") or "")
    workspace_root = Path(str(sandbox.get("workspace_root") or project_root)).resolve()
    return {
        **sandbox,
        "enabled": bool(sandbox.get("enabled") is True),
        "sandbox_root": sandbox_root,
        "workspace_root": str(workspace_root),
        **scope.to_policy_payload(),
        "read_scopes": ["."],
        "approval_policy": str(sandbox.get("approval_policy") or "sandboxed_side_effects"),
        "side_effect_operations": list(
            sandbox.get("side_effect_operations")
            or ("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.browser_control", "op.image_generate")
        ),
    }


def _single_turn_workspace_root(runtime_assembly: Any, *, runtime_host: Any) -> str:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    environment = dict(assembly_payload.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    sandbox = dict(environment.get("sandbox_policy") or {})
    for candidate in (
        storage.get("workspace_root"),
        sandbox.get("workspace_root"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    backend_dir = Path(str(getattr(runtime_host, "backend_dir", "") or assembly_payload.get("backend_dir") or ".")).resolve()
    tool_runtime_base_dir = getattr(
        getattr(
            getattr(getattr(runtime_host, "tool_control_plane", None), "tool_runtime_executor", None),
            "tool_runtime",
            None,
        ),
        "base_dir",
        "",
    )
    if str(tool_runtime_base_dir or "").strip():
        return str(tool_runtime_base_dir)
    try:
        return str(ProjectLayout.from_backend_dir(backend_dir).project_root.resolve())
    except Exception:
        return str(backend_dir.parent.resolve())


def _assistant_tool_call_message(response: Any, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    message = {
        "role": "assistant",
        "content": stringify_content(getattr(response, "content", response)),
        "tool_calls": tool_calls_for_langchain_messages(tool_calls),
    }
    reasoning_content = _reasoning_content_from_response(response)
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return message


def _reasoning_content_from_response(response: Any) -> str:
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        reasoning_content = str(additional_kwargs.get("reasoning_content") or "").strip()
        if reasoning_content:
            return reasoning_content
    if isinstance(response, dict):
        reasoning_content = str(response.get("reasoning_content") or "").strip()
        if reasoning_content:
            return reasoning_content
        response_additional_kwargs = response.get("additional_kwargs")
        if isinstance(response_additional_kwargs, dict):
            return str(response_additional_kwargs.get("reasoning_content") or "").strip()
    return ""


def _tool_observation_message(observation: Any, *, tool_call_id: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "name": observation.tool_name,
        "tool_call_id": str(tool_call_id or observation.invocation_id),
        "content": observation.text,
    }


def _assistant_final_protocol_message(response: Any, *, turn_id: str, include_reasoning: bool) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": stringify_content(getattr(response, "content", response)),
        "turn_id": turn_id,
    }
    if include_reasoning:
        reasoning_content = _reasoning_content_from_response(response)
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
    return message


def _assistant_protocol_message_from_content(content: str, *, turn_id: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": str(content or ""),
        "turn_id": turn_id,
    }


def _native_action_protocol_messages(
    response: Any,
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    tool_result_content: str,
) -> list[dict[str, Any]]:
    calls = tool_calls_for_langchain_messages(tool_calls)
    if not calls:
        return []
    messages = [_with_turn_id(_assistant_tool_call_message(response, calls), turn_id)]
    for call in calls:
        messages.append(
            {
                "role": "tool",
                "name": str(call.get("name") or ""),
                "tool_call_id": str(call.get("id") or ""),
                "content": str(tool_result_content or ""),
                "turn_id": turn_id,
            }
        )
    return messages


def _final_api_protocol_messages(
    api_protocol_messages: list[dict[str, Any]],
    response: Any,
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    tool_result_content: str,
    final_content: str,
) -> list[dict[str, Any]] | None:
    messages = [dict(item) for item in list(api_protocol_messages or []) if isinstance(item, dict)]
    messages.extend(
        _native_action_protocol_messages(
            response,
            tool_calls,
            turn_id=turn_id,
            tool_result_content=tool_result_content,
        )
    )
    if not messages:
        return None
    messages.append(_assistant_protocol_message_from_content(final_content, turn_id=turn_id))
    return messages


def _action_request_with_api_protocol_prefix(
    action_request: ModelActionRequest,
    messages: list[dict[str, Any]],
) -> ModelActionRequest:
    if not messages:
        return action_request
    return replace(
        action_request,
        diagnostics={
            **dict(action_request.diagnostics or {}),
            "api_protocol_prefix_messages": [dict(item) for item in messages],
        },
    )


def _with_turn_id(message: dict[str, Any], turn_id: str) -> dict[str, Any]:
    return {**dict(message or {}), "turn_id": turn_id}


def _sanitize_model_messages(
    messages: list[dict[str, Any]],
    *,
    turn_id: str,
    source: str,
) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in sanitize_messages_for_prompt(
            messages,
            turn_id=turn_id,
            source=source,
        ).messages
    ]


def _compact_text(value: Any, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _single_agent_turn_followup_prompt_context(
    *,
    compilation: Any,
    model_messages: list[dict[str, Any]],
    tool_iteration: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    followup_segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=dict(compilation.packet.segment_plan or {}),
        model_messages=model_messages,
        packet_id=compilation.packet.packet_id,
        tool_iteration=tool_iteration,
    )
    followup_prompt_manifest = {
        **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
        "invocation_kind": "single_agent_turn_tool_followup",
        "segment_plan_ref": str(followup_segment_plan.get("segment_plan_id") or ""),
        "followup_iteration": tool_iteration,
    }
    return followup_segment_plan, followup_prompt_manifest, str(compilation.packet.packet_id)


def _mid_turn_context_snapshot(
    *,
    session_id: str,
    run_id: str,
    model_selection: dict[str, Any],
    model_messages: list[dict[str, Any]],
) -> Any:
    selection = dict(model_selection or {})
    provider = str(selection.get("provider") or selection.get("llm_provider") or "").strip()
    model = str(selection.get("model") or selection.get("llm_model") or "").strip()
    reserved = _first_int(
        selection,
        "reserved_output_tokens",
        "max_output_tokens",
        "max_tokens",
    )
    context_window = _first_int(
        selection,
        "context_window_tokens",
        "context_window",
    )
    meter = ContextUsageMeter(
        _EmptyPromptAccountingLedger(),
        default_reserved_output_tokens=reserved if reserved is not None else 8192,
    )
    return meter.build_snapshot(
        session_id=session_id,
        run_id=run_id,
        provider=provider,
        model=model,
        context_window_tokens=context_window,
        reserved_output_tokens=reserved,
        fallback_messages=list(model_messages or []),
        session_pressure_source="harness.loop.single_agent_turn.mid_turn_context_meter",
    )


def _first_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return None


class _EmptyPromptAccountingLedger:
    def list_token_usage(self, **_kwargs: Any) -> list[Any]:
        return []

    def list_prompt_cache(self, **_kwargs: Any) -> list[Any]:
        return []

    def summarize_session(self, _session_id: str) -> dict[str, Any]:
        return {}


def _single_agent_turn_followup_segment_plan(
    *,
    base_segment_plan: dict[str, Any],
    model_messages: list[dict[str, Any]],
    packet_id: str,
    tool_iteration: int,
) -> dict[str, Any]:
    _normalized_messages, specs, prefix_lock_report = _single_agent_turn_followup_message_specs(
        base_segment_plan=base_segment_plan,
        model_messages=model_messages,
        tool_iteration=tool_iteration,
    )
    segment_plan = build_prompt_segment_plan(
        packet_id=f"{packet_id}:tool-followup:{max(1, int(tool_iteration or 1))}",
        invocation_kind="single_agent_turn_tool_followup",
        message_specs=specs,
    ).to_dict()
    segment_plan = _seal_single_agent_followup_segment_plan(
        segment_plan,
        packet_id=str(packet_id or ""),
    )
    _validate_single_agent_followup_tail_order(segment_plan)
    segment_plan["prefix_lock"] = prefix_lock_report
    if str(prefix_lock_report.get("status") or "") != "preserved":
        logger.warning(
            "single agent follow-up prefix lock violation: packet_id=%s tool_iteration=%s violation_count=%s",
            packet_id,
            tool_iteration,
            prefix_lock_report.get("violation_count"),
        )
    return segment_plan


def _validate_single_agent_followup_tail_order(segment_plan: dict[str, Any]) -> None:
    dynamic_tail_seen = False
    violations: list[dict[str, Any]] = []
    for segment in sorted(
        [dict(item) for item in list(dict(segment_plan or {}).get("segments") or []) if isinstance(item, dict)],
        key=lambda item: _safe_int_value(item.get("ordinal")),
    ):
        classification = classify_context_spec(segment)
        section = classification.context_cache_section
        if section == DYNAMIC_TAIL:
            dynamic_tail_seen = True
            continue
        if dynamic_tail_seen and section in {STATIC_PREFIX, SEALED_CONTEXT_PREFIX, CONTEXT_APPEND}:
            violations.append(
                {
                    "kind": str(segment.get("kind") or ""),
                    "ordinal": _safe_int_value(segment.get("ordinal")),
                    "context_cache_section": section,
                    "cache_role": str(segment.get("cache_role") or ""),
                    "prefix_tier": str(segment.get("prefix_tier") or ""),
                }
            )
    if violations:
        raise RuntimeError(
            "single_agent_followup_context_after_dynamic_tail:"
            + json.dumps(violations, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )


def _single_agent_turn_followup_message_specs(
    *,
    base_segment_plan: dict[str, Any],
    model_messages: list[dict[str, Any]],
    tool_iteration: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    prefix_locked_base_plan = dict(base_segment_plan or {})
    base_segments = _segment_plan_segments_by_message_index(prefix_locked_base_plan)
    normalized_messages = normalize_messages(
        _sanitize_model_messages(
            model_messages,
            turn_id="",
            source="harness.loop.single_agent_turn.followup_segment_plan",
        )
    )
    prefix_lock_report = build_prefix_lock_report(
        base_segment_plan=prefix_locked_base_plan,
        model_messages=list(normalized_messages or []),
    )
    dynamic_tail_segments_by_hash = _dynamic_tail_segments_by_hash(prefix_locked_base_plan)
    current_tool_round_indexes = _current_tool_round_message_indexes(normalized_messages)
    specs: list[dict[str, Any]] = []
    for index, message in enumerate(normalized_messages):
        base = dict(base_segments.get(index) or {})
        base_from_hash = False
        if base and _followup_base_segment_conflicts_with_message_shape(base, message):
            base = {}
        if not base:
            base = _pop_matching_dynamic_tail_segment(dynamic_tail_segments_by_hash, message=message)
            base_from_hash = bool(base)
        if base:
            prefix_lock_violation = (
                {}
                if base_from_hash and _is_tool_followup_current_dynamic_tail_segment(base)
                else prefix_lock_violation_for_index(prefix_lock_report, index)
            )
            specs.append(
                _single_agent_turn_followup_base_message_spec(
                    base,
                    message=message,
                    prefix_lock_violation=prefix_lock_violation,
                    is_current_tool_round=index in current_tool_round_indexes,
                )
            )
            continue
        specs.append(
            _single_agent_turn_followup_message_spec(
                message,
                tool_iteration=tool_iteration,
                is_current_tool_round=index in current_tool_round_indexes,
            )
    )
    return list(normalized_messages or []), specs, prefix_lock_report


def _seal_single_agent_followup_segment_plan(segment_plan: dict[str, Any], *, packet_id: str) -> dict[str, Any]:
    payload = dict(segment_plan or {})
    segments = [dict(item) for item in list(payload.get("segments") or []) if isinstance(item, dict)]
    if not segments:
        return payload
    scope = _single_agent_sealed_context_scope(packet_id)
    storage_root = Path(__file__).resolve().parents[2]
    sealed_segments: list[dict[str, Any]] = []
    for segment in segments:
        metadata = dict(segment.get("metadata") or {})
        if not _is_followup_sealable_segment(segment):
            sealed_segments.append(segment)
            continue
        if _safe_int_value(metadata.get("sealed_accumulated_context_order")) > 0:
            sealed_segments.append(segment)
            continue
        key = _single_agent_sealed_segment_key(segment)
        assignment = assign_sealed_append_order(
            storage_root=storage_root,
            scope=scope,
            item_key=key,
            receipt_authority="harness.loop.single_agent_turn.sealed_append_only_context",
            provider_visible_hash=str(segment.get("model_message_hash") or segment.get("content_hash") or ""),
            kind=str(segment.get("kind") or ""),
            source_ref=str(segment.get("source_ref") or ""),
        )
        existing_order = _safe_int_value(assignment.get("order"))
        order_source = str(assignment.get("order_source") or "receipt")
        segment["metadata"] = {
            **metadata,
            "sealed_accumulated_context_package": "append_only_context",
            "sealed_accumulated_context_scope": scope,
            "sealed_accumulated_context_item_key": key,
            "sealed_accumulated_context_order": existing_order,
            "sealed_accumulated_context_order_source": order_source,
            "sealed_accumulated_context_authority": str(assignment.get("authority") or ""),
            "sealed_accumulated_context_integrity_status": str(assignment.get("integrity_status") or ""),
            "sealed_accumulated_context_recovery_required": bool(assignment.get("recovery_required") is True),
            "sealed_accumulated_context_structured_failure": dict(assignment.get("structured_failure") or {}),
        }
        sealed_segments.append(segment)
    payload["segments"] = sealed_segments
    return payload


def _is_followup_sealable_segment(segment: dict[str, Any]) -> bool:
    if not is_sealable_context_spec(dict(segment or {})):
        return False
    cache_role = str(dict(segment or {}).get("cache_role") or "").strip()
    prefix_tier = str(dict(segment or {}).get("prefix_tier") or "").strip()
    return cache_role in {"cacheable_prefix", "session_stable"} and prefix_tier not in {"volatile", "none"}


def _single_agent_sealed_context_scope(packet_id: str) -> str:
    text = str(packet_id or "").strip()
    session_id = ""
    marker = "session-"
    if marker in text:
        suffix = text.split(marker, 1)[1]
        session_id = marker + suffix.split(":", 1)[0]
    if not session_id:
        session_id = "default"
    return f"single_agent_turn:{session_id}"


def _single_agent_sealed_segment_key(segment: dict[str, Any]) -> str:
    return _stable_payload_hash(
        {
            "normalization": "provider_visible_message_v1",
            "model_message_hash": str(segment.get("model_message_hash") or segment.get("content_hash") or ""),
        }
    )


def _safe_int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_tool_followup_action_contract_message(message: dict[str, Any]) -> bool:
    payload = dict(message or {})
    if str(payload.get("source_ref") or "") == "single_agent_turn_tool_followup_action_contract":
        return True
    content = str(payload.get("content") or "")
    return "你是正在根据刚才工具观察决定下一步的 coding agent。" in content


_FOLLOWUP_BASE_ACCUMULATED_CONTEXT_KINDS = {
    "accumulated_context_boundary",
    "incremental_context_frame",
    "provider_protocol_history",
    "read_evidence_context",
    "runtime_memory_context",
    "session_history",
    "session_history_context",
    "session_history_entry",
    "session_pinned_facts_context",
    "current_turn_user_context",
    "single_agent_turn_followup_message",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
    "single_agent_turn_user_steer_context",
    "task_plan_context",
    "task_state_replay_entry",
    "tool_observations",
    "user_steering_context_append",
}


def _ordered_tool_followup_accumulated_context_messages(
    messages: list[dict[str, Any]],
    *,
    segment_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    accumulated, _dynamic_tail = _tool_followup_context_layers(messages, segment_plan=segment_plan)
    return accumulated


def _tool_followup_context_layers(
    messages: list[dict[str, Any]],
    *,
    segment_plan: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base_segments = _segment_plan_segments_by_message_index(dict(segment_plan or {}))
    dynamic_tail_segments_by_hash = _dynamic_tail_segments_by_hash(dict(segment_plan or {}))
    accumulated: list[dict[str, Any]] = []
    dynamic_tail: list[dict[str, Any]] = []
    for index, message in enumerate([dict(item) for item in list(messages or []) if isinstance(item, dict)]):
        if _is_tool_followup_action_contract_message(message):
            continue
        if _is_tool_followup_context_boundary_message(message):
            continue
        if _is_tool_followup_accumulated_message_by_shape(message):
            accumulated.append(message)
            continue
        segment = dict(base_segments.get(index) or {})
        if segment and _followup_base_segment_conflicts_with_message_shape(segment, message):
            segment = {}
        if not segment:
            segment = _pop_matching_dynamic_tail_segment(dynamic_tail_segments_by_hash, message=message)
        if _is_tool_followup_current_dynamic_tail_segment(segment):
            dynamic_tail.append(message)
            continue
        accumulated.append(message)
    return accumulated, dynamic_tail


def _append_tool_transcript_to_accumulated_context(
    messages: list[dict[str, Any]],
    new_tool_transcript_messages: list[dict[str, Any]],
    *,
    segment_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    accumulated, dynamic_tail = _tool_followup_context_layers(messages, segment_plan=segment_plan)
    new_messages = [
        dict(item)
        for item in list(new_tool_transcript_messages or [])
        if isinstance(item, dict) and item
    ]
    return [*accumulated, *new_messages, *dynamic_tail]


def _segment_plan_segments_by_message_index(segment_plan: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for segment in list(dict(segment_plan or {}).get("segments") or []):
        if not isinstance(segment, dict):
            continue
        index = _segment_model_message_index(segment)
        if index >= 0:
            result[index] = dict(segment)
    return result


def _dynamic_tail_segments_by_hash(segment_plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for segment in list(dict(segment_plan or {}).get("segments") or []):
        if not isinstance(segment, dict):
            continue
        payload = dict(segment)
        if not _is_tool_followup_current_dynamic_tail_segment(payload):
            continue
        for key in _segment_hash_keys(payload):
            result.setdefault(key, []).append(payload)
    return result


def _pop_matching_dynamic_tail_segment(
    segments_by_hash: dict[str, list[dict[str, Any]]],
    *,
    message: dict[str, Any],
) -> dict[str, Any]:
    for key in _message_hash_keys(message):
        candidates = segments_by_hash.get(key)
        if not candidates:
            continue
        return dict(candidates.pop(0))
    return {}


def _segment_hash_keys(segment: dict[str, Any]) -> tuple[str, ...]:
    keys = [
        str(segment.get("model_message_hash") or "").strip(),
        str(segment.get("content_hash") or "").strip(),
    ]
    return tuple(dict.fromkeys(key for key in keys if key))


def _message_hash_keys(message: dict[str, Any]) -> tuple[str, ...]:
    payload = dict(message or {})
    return (
        stable_model_message_hash(payload),
        stable_text_hash(str(payload.get("content") or "")),
    )


def _is_tool_followup_current_dynamic_tail_segment(segment: dict[str, Any]) -> bool:
    if not segment:
        return False
    return is_dynamic_tail_spec(dict(segment or {}))


def _is_tool_followup_accumulated_message_by_shape(message: dict[str, Any]) -> bool:
    payload = dict(message or {})
    role = str(payload.get("role") or "")
    if is_incremental_context_frame_message(payload):
        return True
    if role == "tool":
        return True
    if role == "assistant" and payload.get("tool_calls"):
        return True
    return False


def _append_tool_followup_context_boundary(
    messages: list[dict[str, Any]],
    *,
    tool_iteration: int,
    turn_id: str,
) -> list[dict[str, Any]]:
    accumulated = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
    if not accumulated:
        return accumulated
    payload = {
        "frame_type": "accumulated_context_boundary",
        "boundary_iteration": max(1, int(tool_iteration or 1)),
        "accumulated_message_count": len(accumulated),
        "accumulated_context_hash": _stable_payload_hash(
            [stable_model_message_hash(message) for message in accumulated]
        ),
        "stability_rule": "messages before this boundary are append-only accumulated context; later follow-up contracts are appended instead of replacing history",
        "authority": "harness.loop.single_agent_turn.accumulated_context_boundary",
    }
    content = (
        "你正在继续同一轮工具执行。\n"
        "以上内容是已经固定的历史上下文、工具调用和工具观察；这条消息只标记累计上下文边界，不是新的用户需求。\n"
        "请继续读取后面的最新执行契约，并基于这些固定事实决定下一步。\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
    )
    return [
        *accumulated,
        {
            "role": "user",
            "content": content,
            "turn_id": turn_id,
        },
    ]


def _is_tool_followup_context_boundary_message(message: dict[str, Any]) -> bool:
    content = str(dict(message or {}).get("content") or "")
    return '"frame_type":"accumulated_context_boundary"' in content or '"frame_type": "accumulated_context_boundary"' in content


def _indexed_tool_transcript_messages(
    *,
    start_index: int,
    messages: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    base = max(0, int(start_index or 0))
    return [
        (base + offset, dict(message))
        for offset, message in enumerate(
            [dict(item) for item in list(messages or []) if isinstance(item, dict) and item]
        )
    ]


def _single_agent_turn_followup_base_message_spec(
    base: dict[str, Any],
    *,
    message: dict[str, Any],
    prefix_lock_violation: dict[str, Any] | None = None,
    is_current_tool_round: bool = False,
) -> dict[str, Any]:
    metadata = dict(base.get("metadata") or {})
    kind = str(base.get("kind") or "single_agent_turn_base")
    cache_scope = str(base.get("cache_scope") or "none")
    cache_role = str(base.get("cache_role") or "volatile")
    prefix_tier = str(base.get("prefix_tier") or "volatile")
    if prefix_lock_violation:
        cache_scope = "none"
        cache_role = "volatile"
        prefix_tier = "volatile"
        metadata = {
            **metadata,
            "prefix_lock_status": "violated",
            "prefix_lock_violation": dict(prefix_lock_violation),
            "volatility_reason": "previously planned message changed at the same model_message_index",
            "cache_impact": "cache_break_diagnostic",
        }
    elif _is_tool_followup_current_dynamic_tail_segment(base):
        metadata = {
            **metadata,
            "cache_impact": "volatile_suffix_only",
            "stability_rule": "current dynamic tail remains after the append-only context prefix and is not promoted into the cached prefix",
        }
    else:
        already_prefix_stable = cache_role in {"cacheable_prefix", "session_stable"} and prefix_tier not in {"volatile", "none"}
        rebased = (
            {}
            if already_prefix_stable
            else _rebased_followup_base_cache_policy(
                kind=kind,
                message=message,
                is_current_tool_round=is_current_tool_round,
            )
        )
        if rebased:
            cache_scope = rebased["cache_scope"]
            cache_role = rebased["cache_role"]
            prefix_tier = rebased["prefix_tier"]
            metadata = {**metadata, **dict(rebased.get("metadata") or {})}
        classified = apply_context_assembly_classification(
            {
                "kind": kind,
                "cache_scope": cache_scope,
                "cache_role": cache_role,
                "prefix_tier": prefix_tier,
                "metadata": metadata,
                "model_message": dict(message),
            }
        )
        cache_scope = str(classified.get("cache_scope") or cache_scope)
        cache_role = str(classified.get("cache_role") or cache_role)
        prefix_tier = str(classified.get("prefix_tier") or prefix_tier)
        metadata = dict(classified.get("metadata") or metadata)
    return {
        "role": str(message.get("role") or "user"),
        "content": str(message.get("content") or ""),
        "kind": kind,
        "source_ref": _rebased_followup_source_ref(
            kind=kind,
            message=message,
            fallback=str(base.get("source_ref") or "single_agent_turn_base"),
        ),
        "cache_scope": cache_scope,
        "cache_role": cache_role,
        "prefix_tier": prefix_tier,
        "compression_role": str(base.get("compression_role") or "summarize"),
        "metadata": metadata,
        "model_message": dict(message),
    }


def _single_agent_turn_followup_message_spec(
    message: dict[str, Any],
    *,
    tool_iteration: int,
    is_current_tool_round: bool = True,
) -> dict[str, Any]:
    boundary_payload = _tool_followup_context_boundary_payload(message)
    if boundary_payload:
        boundary_iteration = _safe_int_value(boundary_payload.get("boundary_iteration")) or max(1, int(tool_iteration or 1))
        boundary_hash = str(boundary_payload.get("accumulated_context_hash") or "").strip()
        return {
            "role": str(message.get("role") or "user"),
            "content": str(message.get("content") or ""),
            "kind": "accumulated_context_boundary",
            "source_ref": f"single_agent_turn.accumulated_context_boundary:{boundary_iteration}:{boundary_hash[:16]}",
            "cache_scope": "none",
            "cache_role": "volatile",
            "prefix_tier": "volatile",
            "compression_role": "preserve",
            "metadata": {
                "authority_class": "accumulated_context_boundary",
                "cache_impact": "volatile_suffix_only",
                "stability_rule": "this boundary is rebuilt for the current invocation and must not become part of the cacheable prefix",
                "followup_iteration": boundary_iteration,
                "accumulated_context_hash": boundary_hash,
                "accumulated_message_count": _safe_int_value(boundary_payload.get("accumulated_message_count")),
                "provider_cache_boundary": "deepseek_user_input_prefix_unit",
            },
            "model_message": dict(message),
        }
    if is_incremental_context_frame_message(message):
        return incremental_context_frame_segment_spec(message, tool_iteration=tool_iteration)
    role = str(message.get("role") or "user")
    is_action_contract = _is_tool_followup_action_contract_message(message)
    if is_action_contract:
        kind = "single_agent_turn_followup_action_contract"
        source_ref = f"single_agent_turn.followup_action_contract:{tool_iteration}"
        compression_role = "preserve"
    elif role == "assistant" and message.get("tool_calls"):
        kind = "single_agent_turn_tool_call"
        source_ref = _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_call")
        compression_role = "preserve"
    elif role == "tool":
        kind = "single_agent_turn_tool_observation"
        source_ref = _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_observation")
        compression_role = "summarize"
    elif _is_active_turn_user_steer_message(message):
        kind = "single_agent_turn_user_steer_context"
        source_ref = _active_turn_user_steer_source_ref(message, tool_iteration=tool_iteration)
        compression_role = "preserve"
    else:
        kind = "single_agent_turn_followup_message"
        source_ref = f"single_agent_turn.followup:{tool_iteration}"
        compression_role = "summarize"
    cache_scope = "none" if is_action_contract else "task"
    cache_role = "volatile" if is_action_contract else "session_stable"
    prefix_tier = "volatile" if is_action_contract else "task"
    metadata = {"followup_iteration": max(1, int(tool_iteration or 1))}
    authority_class = (
        "tool_followup_action_contract"
        if is_action_contract
        else "append_only_tool_transcript"
    )
    if is_action_contract:
        metadata.update(
            {
                "authority_class": authority_class,
                "cache_impact": "volatile_suffix_only",
                "stability_rule": "the latest follow-up action contract is current-invocation control and stays behind the cacheable context prefix",
                "volatility_reason": "tool follow-up control can change every tool round",
            }
        )
    else:
        metadata.update(
            {
                "authority_class": authority_class,
                "cache_impact": "append_only_task_prefix",
                "stability_rule": "follow-up context is appended as immutable context after it has been sent to the model",
            }
        )
    classified = apply_context_assembly_classification(
        {
            "kind": kind,
            "cache_scope": cache_scope,
            "cache_role": cache_role,
            "prefix_tier": prefix_tier,
            "metadata": metadata,
            "model_message": dict(message),
        }
    )
    cache_scope = str(classified.get("cache_scope") or cache_scope)
    cache_role = str(classified.get("cache_role") or cache_role)
    prefix_tier = str(classified.get("prefix_tier") or prefix_tier)
    metadata = dict(classified.get("metadata") or metadata)
    return {
        "role": role,
        "content": str(message.get("content") or ""),
        "kind": kind,
        "source_ref": source_ref,
        "cache_scope": cache_scope,
        "cache_role": cache_role,
        "prefix_tier": prefix_tier,
        "compression_role": compression_role,
        "metadata": metadata,
        "model_message": dict(message),
    }


def _is_active_turn_user_steer_message(message: dict[str, Any]) -> bool:
    content = str(dict(message or {}).get("content") or "")
    return (
        "用户在本轮 agent 运行期间追加了以下补充要求" in content
        and "harness.loop.active_turn_steer" in content
    )


def _active_turn_user_steer_source_ref(message: dict[str, Any], *, tool_iteration: int) -> str:
    content = str(dict(message or {}).get("content") or "")
    digest = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"single_agent_turn.active_turn_user_steer:{max(1, int(tool_iteration or 1))}:{digest}"


def _followup_base_segment_conflicts_with_message_shape(base: dict[str, Any], message: dict[str, Any]) -> bool:
    kind = str(dict(base or {}).get("kind") or "").strip()
    payload = dict(message or {})
    role = str(payload.get("role") or "")
    if is_incremental_context_frame_message(payload):
        return kind != "incremental_context_frame"
    if _is_tool_followup_context_boundary_message(payload):
        return kind != "accumulated_context_boundary"
    if role == "assistant" and payload.get("tool_calls"):
        return kind != "single_agent_turn_tool_call"
    if role == "tool":
        return kind != "single_agent_turn_tool_observation"
    return False


def _tool_followup_context_boundary_payload(message: dict[str, Any]) -> dict[str, Any]:
    content = str(dict(message or {}).get("content") or "")
    if not _is_tool_followup_context_boundary_message({"content": content}):
        return {}
    for candidate in reversed(content.replace("\r\n", "\n").split("\n")):
        text = candidate.strip()
        if not text.startswith("{") or not text.endswith("}"):
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict) and str(payload.get("frame_type") or "") == "accumulated_context_boundary":
            return dict(payload)
    return {}


def _rebased_followup_base_cache_policy(
    *,
    kind: str,
    message: dict[str, Any],
    is_current_tool_round: bool,
) -> dict[str, Any]:
    role = str(message.get("role") or "")
    if kind == "incremental_context_frame" or is_incremental_context_frame_message(message):
        return {
            "cache_scope": "task",
            "cache_role": "session_stable",
            "prefix_tier": "task",
            "metadata": {
                "authority_class": "append_only_incremental_context",
                "cache_impact": "append_only_task_prefix",
                "stability_rule": "historical incremental context frames are immutable append-only context",
                "cache_policy_rebased": "historical_incremental_context_promoted_from_base_plan",
            },
        }
    is_tool_transcript = (
        kind in {"single_agent_turn_tool_call", "single_agent_turn_tool_observation"}
        or role == "tool"
        or (role == "assistant" and bool(message.get("tool_calls")))
    )
    if is_tool_transcript:
        return {
            "cache_scope": "task",
            "cache_role": "session_stable",
            "prefix_tier": "task",
            "metadata": {
                "authority_class": "append_only_tool_transcript",
                "cache_impact": "append_only_task_prefix",
                "stability_rule": "tool transcript is appended to the model-visible context and is immutable after assembly",
                "cache_policy_rebased": "historical_tool_transcript_promoted_from_base_plan",
            },
        }
    if kind in _FOLLOWUP_BASE_ACCUMULATED_CONTEXT_KINDS:
        return {
            "cache_scope": "task",
            "cache_role": "session_stable",
            "prefix_tier": "task",
            "metadata": {
                "cache_impact": "append_only_task_prefix",
                "stability_rule": "preserved accumulated context is append-only; replaceable runtime tail remains volatile",
                "cache_policy_rebased": "preserved_accumulated_context_promoted_from_base_plan",
            },
        }
    return {}


def _rebased_followup_source_ref(*, kind: str, message: dict[str, Any], fallback: str) -> str:
    if kind == "single_agent_turn_tool_call" or (
        str(message.get("role") or "") == "assistant" and message.get("tool_calls")
    ):
        return _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_call")
    if kind == "single_agent_turn_tool_observation" or str(message.get("role") or "") == "tool":
        return _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_observation")
    return str(fallback or "single_agent_turn_base")


def _followup_tool_message_source_ref(message: dict[str, Any], *, prefix: str) -> str:
    payload = dict(message or {})
    role = str(payload.get("role") or "")
    if role == "tool":
        tool_call_id = str(payload.get("tool_call_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if tool_call_id:
            return ":".join(item for item in (prefix, name, tool_call_id) if item)
    if role == "assistant":
        call_refs: list[str] = []
        for call in list(payload.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "").strip()
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(call.get("name") or dict(function).get("name") or "").strip()
            call_refs.append(":".join(item for item in (name, call_id) if item))
        clean_refs = [item for item in call_refs if item]
        if clean_refs:
            return f"{prefix}:{','.join(clean_refs)}"
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}:hash:{digest}"


def _current_tool_round_message_indexes(messages: list[dict[str, Any]]) -> set[int]:
    groups: list[list[int]] = []
    active: list[int] | None = None
    for index, message in enumerate(list(messages or [])):
        if not isinstance(message, dict):
            active = None
            continue
        role = str(message.get("role") or "")
        if role == "assistant" and message.get("tool_calls"):
            active = [index]
            groups.append(active)
            continue
        if role == "tool" and active is not None:
            active.append(index)
            continue
        active = None
    return set(groups[-1]) if groups else set()


def _current_tool_round_indexed_messages(messages: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    indexes = _current_tool_round_message_indexes(messages)
    return [
        (index, dict(messages[index]))
        for index in sorted(indexes)
        if 0 <= index < len(messages) and isinstance(messages[index], dict)
    ]


def _append_tool_context_ledger_entries(
    ledger_entries: list[dict[str, Any]],
    *,
    tool_iteration: int,
    assistant_model_message_index: int,
    tool_calls: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_entries: list[dict[str, Any]] = []
    latest_by_signature = {
        str(entry.get("signature") or ""): dict(entry)
        for entry in list(ledger_entries or [])
        if isinstance(entry, dict) and str(entry.get("signature") or "")
    }
    for offset, (tool_call, observation) in enumerate(
        zip([dict(item) for item in list(tool_calls or []) if isinstance(item, dict)], [dict(item) for item in list(observations or []) if isinstance(item, dict)])
    ):
        entry = _tool_context_ledger_entry(
            tool_call=tool_call,
            observation=observation,
            tool_iteration=tool_iteration,
            ledger_index=len(ledger_entries) + 1,
            assistant_model_message_index=assistant_model_message_index,
            tool_model_message_index=assistant_model_message_index + 1 + offset if assistant_model_message_index >= 0 else -1,
            previous_entry=latest_by_signature.get(_tool_context_signature(tool_call)),
        )
        ledger_entries.append(entry)
        latest_by_signature[str(entry.get("signature") or "")] = entry
        current_entries.append(entry)
    return current_entries


def _tool_context_ledger_entry(
    *,
    tool_call: dict[str, Any],
    observation: dict[str, Any],
    tool_iteration: int,
    ledger_index: int,
    assistant_model_message_index: int,
    tool_model_message_index: int,
    previous_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    name = _tool_context_tool_name(tool_call, observation)
    args_payload = _tool_context_args_payload(tool_call)
    args_hash = _stable_payload_hash(args_payload)
    result_payload = _tool_context_result_payload(observation)
    result_hash = _stable_payload_hash(result_payload)
    signature = _tool_context_signature(tool_call)
    previous = dict(previous_entry or {})
    duplicate_of = ""
    changed_from = ""
    change = "new"
    if previous:
        if str(previous.get("result_hash") or "") == result_hash:
            duplicate_of = str(previous.get("ref") or "")
            change = "duplicate_same_result"
        else:
            changed_from = str(previous.get("ref") or "")
            change = "result_changed"
    return _drop_empty_dict(
        {
            "ledger_index": int(ledger_index),
            "tool_iteration": max(1, int(tool_iteration or 1)),
            "ref": _tool_context_observation_ref(observation, fallback=f"toolctx:{ledger_index}"),
            "tool_call_id": str(tool_call.get("id") or observation.get("tool_call_id") or ""),
            "tool_name": name,
            "signature": signature,
            "args_hash": args_hash,
            "result_hash": result_hash,
            "status": str(observation.get("status") or ""),
            "assistant_model_message_index": assistant_model_message_index,
            "tool_model_message_index": tool_model_message_index,
            "path": _tool_context_path(tool_call, observation),
            "result_ref": str(observation.get("result_ref") or ""),
            "artifact_refs": _bounded_text_list(observation.get("artifact_refs"), limit=4),
            "observed_paths": _bounded_text_list(observation.get("observed_paths"), limit=4),
            "matched_paths": _bounded_text_list(observation.get("matched_paths"), limit=4),
            "written_paths": _bounded_text_list(observation.get("written_paths"), limit=4),
            "exact_content_visible": True,
            "change": change,
            "duplicate_of": duplicate_of,
            "changed_from": changed_from,
        }
    )


def _tool_context_delta_from_ledger(
    ledger_entries: list[dict[str, Any]],
    *,
    current_entries: list[dict[str, Any]],
    tool_iteration: int,
) -> dict[str, Any]:
    current = [dict(item) for item in list(current_entries or []) if isinstance(item, dict)]
    duplicates = [item for item in current if str(item.get("duplicate_of") or "")]
    changed = [item for item in current if str(item.get("changed_from") or "")]
    return _drop_empty_dict(
        {
            "status": "present" if current else "none",
            "tool_followup_iteration": max(1, int(tool_iteration or 1)),
            "ledger_entry_count": len([item for item in list(ledger_entries or []) if isinstance(item, dict)]),
            "new_entries": [_tool_context_frame_ref(item, meaning="本轮新增工具上下文索引") for item in current],
            "duplicate_refs": [
                _tool_context_frame_ref(item, meaning="本轮重新观察到同一工具签名且结果未变")
                for item in duplicates
            ],
            "changed_refs": [
                _tool_context_frame_ref(item, meaning="本轮同一工具签名的结果发生变化，旧 ref 仅作历史参考")
                for item in changed
            ],
            "rule": "exact content is in transcript; this is only an index",
        }
    )


def _unchanged_tool_refs_from_tool_context_ledger(
    ledger_entries: list[dict[str, Any]],
    *,
    current_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_refs = {str(item.get("ref") or "") for item in list(current_entries or []) if isinstance(item, dict)}
    refs = [
        _tool_context_frame_ref(dict(entry), meaning="already visible in preserved append-only transcript")
        for entry in list(ledger_entries or [])
        if isinstance(entry, dict) and str(entry.get("ref") or "") and str(entry.get("ref") or "") not in current_refs
    ]
    return refs[-8:]


def _tool_context_frame_ref(entry: dict[str, Any], *, meaning: str) -> dict[str, Any]:
    return _drop_empty_dict(
        {
            "ledger_index": entry.get("ledger_index"),
            "ref": str(entry.get("ref") or ""),
            "tool_call_id": str(entry.get("tool_call_id") or ""),
            "tool_name": str(entry.get("tool_name") or ""),
            "args_hash": str(entry.get("args_hash") or ""),
            "result_hash": str(entry.get("result_hash") or ""),
            "status": str(entry.get("status") or ""),
            "path": str(entry.get("path") or ""),
            "duplicate_of": str(entry.get("duplicate_of") or ""),
            "changed_from": str(entry.get("changed_from") or ""),
            "change": str(entry.get("change") or ""),
            "assistant_model_message_index": entry.get("assistant_model_message_index"),
            "tool_model_message_index": entry.get("tool_model_message_index"),
            "exact_content_visible": bool(entry.get("exact_content_visible")),
            "relation": meaning,
        }
    )


def _tool_context_signature(tool_call: dict[str, Any]) -> str:
    return _stable_payload_hash(
        {
            "tool_name": _tool_context_tool_name(tool_call, {}),
            "args": _tool_context_args_payload(tool_call),
        }
    )


def _tool_context_tool_name(tool_call: dict[str, Any], observation: dict[str, Any]) -> str:
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    return str(
        tool_call.get("name")
        or tool_call.get("tool_name")
        or dict(function).get("name")
        or observation.get("tool_name")
        or observation.get("name")
        or ""
    ).strip()


def _tool_context_args_payload(tool_call: dict[str, Any]) -> Any:
    if isinstance(tool_call.get("args"), dict):
        return _json_stable_value(tool_call.get("args"))
    if "args" in tool_call:
        return _json_or_text(tool_call.get("args"))
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    if "arguments" in function:
        return _json_or_text(function.get("arguments"))
    return {}


def _tool_context_result_payload(observation: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty_dict(
        {
            "status": observation.get("status"),
            "text": observation.get("text") or observation.get("content") or observation.get("summary"),
            "result_ref": observation.get("result_ref"),
            "artifact_refs": observation.get("artifact_refs"),
            "observed_paths": observation.get("observed_paths"),
            "matched_paths": observation.get("matched_paths"),
            "written_paths": observation.get("written_paths"),
            "error": observation.get("error") or observation.get("structured_error"),
        }
    )


def _tool_context_observation_ref(observation: dict[str, Any], *, fallback: str) -> str:
    return str(observation.get("observation_id") or observation.get("observation_ref") or fallback).strip()


def _tool_context_path(tool_call: dict[str, Any], observation: dict[str, Any]) -> str:
    args = _tool_context_args_payload(tool_call)
    if isinstance(args, dict) and str(args.get("path") or "").strip():
        return str(args.get("path") or "").strip()
    for key in ("path", "target"):
        if str(observation.get(key) or "").strip():
            return str(observation.get(key) or "").strip()
    return ""


def _json_or_text(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return _json_stable_value(value)
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return _json_stable_value(json.loads(text))
    except Exception:
        return text


def _stable_payload_hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(_json_stable_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8", errors="ignore"
        )
    ).hexdigest()


def _json_stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _bounded_text_list(value: Any, *, limit: int) -> list[str]:
    return [str(item) for item in list(value or [])[: max(0, int(limit or 0))] if str(item or "")]


def _drop_empty_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _memory_maintenance_main_context_payload(
    *,
    packet_context: dict[str, Any],
    model_messages: list[dict[str, Any]],
    segment_plan: dict[str, Any],
    source_packet_ref: str,
    model_selection: dict[str, Any],
) -> dict[str, Any]:
    packet = dict(packet_context or {})
    session_context = dict(packet.get("session_context") or {}) if isinstance(packet.get("session_context"), dict) else {}
    environment_payload = dict(packet.get("environment_payload") or {}) if isinstance(packet.get("environment_payload"), dict) else {}
    active_work_context = dict(packet.get("active_work_context") or {}) if isinstance(packet.get("active_work_context"), dict) else {}
    shared_prefix = _memory_maintenance_shared_model_prefix_payload(
        model_messages=model_messages,
        segment_plan=segment_plan,
        source_packet_ref=source_packet_ref,
    )
    return _drop_empty_dict(
        {
            "active_goal": str(session_context.get("active_goal") or session_context.get("current_goal") or ""),
            "task_environment": environment_payload,
            "project_id": str(environment_payload.get("project_id") or packet.get("project_id") or ""),
            "active_work_context": active_work_context,
            "agent_profile_ref": str(packet.get("agent_profile_ref") or ""),
            "task_environment_ref": str(packet.get("task_environment_ref") or ""),
            "model_selection": dict(model_selection or {}),
            "shared_model_prefix": shared_prefix,
            "context_sharing_policy": {
                "authority": "harness.loop.single_agent_turn.memory_maintenance_context_handoff",
                "physical_order": "shared_static_prefix -> maintenance_task_guidance -> append_only_coverage -> current_delta_tail",
                "dynamic_tail_shared": False,
                "tool_authority_shared": False,
            },
        }
    )


def _memory_maintenance_shared_model_prefix_payload(
    *,
    model_messages: list[dict[str, Any]],
    segment_plan: dict[str, Any],
    source_packet_ref: str,
) -> dict[str, Any]:
    segments_by_index = _segment_plan_segments_by_message_index(dict(segment_plan or {}))
    messages: list[dict[str, Any]] = []
    message_cache_plan: list[dict[str, Any]] = []
    message_hashes: list[str] = []
    for index, raw_message in enumerate([dict(item) for item in list(model_messages or []) if isinstance(item, dict)]):
        segment = dict(segments_by_index.get(index) or {})
        if not _memory_maintenance_shared_prefix_segment_cacheable(segment):
            break
        message = _memory_maintenance_shared_prefix_message(raw_message)
        if not message:
            break
        messages.append(message)
        message_cache_plan.append(_memory_maintenance_shared_prefix_cache_plan(segment))
        message_hashes.append(stable_model_message_hash(message))
    if not messages:
        return {}
    return {
        "authority": "harness.loop.single_agent_turn.shared_model_prefix",
        "source_packet_ref": str(source_packet_ref or ""),
        "message_count": len(messages),
        "messages": messages,
        "message_cache_plan": message_cache_plan,
        "message_hashes": message_hashes,
        "stable_prefix_hash": str(dict(segment_plan or {}).get("stable_prefix_hash") or ""),
        "provider_global_prefix_hash": str(dict(segment_plan or {}).get("provider_global_prefix_hash") or ""),
        "session_prefix_hash": str(dict(segment_plan or {}).get("session_prefix_hash") or ""),
        "task_prefix_hash": str(dict(segment_plan or {}).get("task_prefix_hash") or ""),
    }


def _memory_maintenance_shared_prefix_segment_cacheable(segment: dict[str, Any]) -> bool:
    cache_role = str(dict(segment or {}).get("cache_role") or "")
    prefix_tier = str(dict(segment or {}).get("prefix_tier") or "")
    return cache_role in {"cacheable_prefix", "session_stable"} and prefix_tier not in {"volatile", "none"}


def _memory_maintenance_shared_prefix_message(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get("role") or "").strip()
    content = str(message.get("content") or "")
    if not role or not content:
        return {}
    payload: dict[str, Any] = {"role": role, "content": content}
    for key in ("name", "tool_call_id", "tool_calls", "reasoning_content", "prefix", "additional_kwargs"):
        value = message.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload


def _memory_maintenance_shared_prefix_cache_plan(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(segment.get("kind") or "shared_main_agent_prefix"),
        "source_ref": str(segment.get("source_ref") or ""),
        "cache_scope": str(segment.get("cache_scope") or "task"),
        "cache_role": str(segment.get("cache_role") or "session_stable"),
        "prefix_tier": str(segment.get("prefix_tier") or "task"),
        "compression_role": str(segment.get("compression_role") or "preserve"),
        "metadata": {
            **(dict(segment.get("metadata") or {}) if isinstance(segment.get("metadata"), dict) else {}),
            "shared_with": "memory_maintenance_agent",
            "cache_impact": "shared_main_agent_provider_prefix",
        },
    }


def _segment_model_message_index(segment: dict[str, Any]) -> int:
    try:
        return int(segment.get("model_message_index"))
    except (TypeError, ValueError):
        return -1


async def _commit_final_message(
    commit_assistant_message: CommitAssistantMessage,
    *,
    runtime_host: Any | None = None,
    turn_run: TurnRun | None = None,
    session_id: str,
    turn_id: str,
    content: str,
    answer_channel: str,
    answer_source: str,
    api_protocol_messages: list[dict[str, Any]] | None = None,
    main_context: dict[str, Any] | None = None,
) -> FinalMessageCommit:
    sanitized_protocol_messages = _sanitize_model_messages(
        [dict(item) for item in list(api_protocol_messages or []) if isinstance(item, dict)],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.commit_api_protocol_messages",
    )
    agent_scope = _turn_run_agent_scope(
        runtime_host,
        turn_run=turn_run,
        session_id=session_id,
        turn_id=turn_id,
    )
    request = OutputCommitRequest(
        run_id=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        session_id=session_id,
        stream_run_id=str(agent_scope.get("stream_run_id") or ""),
        turn_id=turn_id,
        turn_run_id=turn_run.turn_run_id if turn_run is not None else "",
        agent_run_id=str(agent_scope.get("agent_run_id") or ""),
        run_cell_id=str(agent_scope.get("run_cell_id") or ""),
        content=content,
        answer_channel=answer_channel,
        answer_source=answer_source,
        execution_posture="single_agent_turn",
        has_tool_receipt=any(str(item.get("role") or "") == "tool" for item in sanitized_protocol_messages),
        commit_source="harness.loop.single_agent_turn",
        refs={
            "turn_ref": turn_id,
            "turn_run_ref": turn_run.turn_run_id if turn_run is not None else "",
            **_agent_scope_refs(agent_scope),
        },
        commit_payload_overrides={
            "api_protocol_messages": sanitized_protocol_messages,
            **({"main_context": dict(main_context or {})} if main_context else {}),
        },
    )
    result = await OutputCommitAuthority(runtime_host).commit_async(
        request,
        committer=commit_assistant_message,
    )
    for event in (result.checked_event, result.terminal_event):
        if runtime_host is not None and turn_run is not None and event is not None:
            _update_turn_run_event_offset(runtime_host, turn_run=turn_run, event=event)
    return FinalMessageCommit(
        decision=result.decision,
        events=result.events,
        receipt=result.receipt,
    )


def _update_turn_run_event_offset(runtime_host: Any, *, turn_run: TurnRun, event: Any) -> None:
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            updated_at=float(getattr(event, "created_at", 0.0) or getattr(current, "updated_at", 0.0) or 0.0),
            latest_event_offset=_event_offset(event),
        )
    )


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
                "runtime_invocation_packet_ref": str(packet_context.get("packet_id") or ""),
            },
        )
    except Exception:
        logger.debug("failed to publish packet evidence projection event", exc_info=True)
        return None


def _text_sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


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


def _active_work_payload(active_work_context: Any | None) -> dict[str, Any]:
    if active_work_context is None:
        return {}
    if hasattr(active_work_context, "to_dict"):
        return dict(active_work_context.to_dict())
    return dict(active_work_context or {})


def _start_turn_runtime(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    agent_profile_ref: str,
    stream_run_id: str = "",
) -> tuple[TurnRun, dict[str, Any]]:
    now = time.time()
    stream_ref = str(stream_run_id or "").strip()
    turn_run_id = f"turnrun:{stream_ref}" if stream_ref else f"turnrun:{turn_id}:{uuid.uuid4().hex[:8]}"
    agent_scope = _turn_run_agent_scope(
        runtime_host,
        session_id=session_id,
        turn_id=turn_id,
        turn_run_id=turn_run_id,
        stream_run_id=stream_ref,
    )
    turn_run = TurnRun(
        turn_run_id=turn_run_id,
        session_id=session_id,
        turn_id=turn_id,
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        execution_runtime_kind="single_agent_turn",
        status="running",
        created_at=now,
        updated_at=now,
        diagnostics={
            "turn_id": turn_id,
            "stream_run_id": stream_ref,
            "source": "harness.loop.single_agent_turn",
            "execution_runtime_kind": "single_agent_turn",
            "agent_run_scope": agent_scope,
            "agent_run_id": str(agent_scope.get("agent_run_id") or ""),
            "run_cell_id": str(agent_scope.get("run_cell_id") or ""),
        },
    )
    _record_turn_scope_on_runtime_run(
        runtime_host,
        stream_run_id=stream_ref,
        agent_scope=agent_scope,
        turn_run_id=turn_run_id,
    )
    runtime_host.state_index.upsert_turn_run(turn_run)
    event = runtime_host.event_log.append(
        turn_run_id,
        "agent_turn_received",
        payload={"turn_id": turn_id, "turn_run": turn_run.to_dict()},
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id, **_agent_scope_refs(agent_scope)},
    )
    updated = replace(turn_run, updated_at=event.created_at, latest_event_offset=event.offset)
    runtime_host.state_index.upsert_turn_run(updated)
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is not None:
        active_registry.bind_turn_run(session_id=session_id, turn_id=turn_id, turn_run_id=turn_run_id)
    return updated, event.to_dict()


def _turn_run_agent_scope(
    runtime_host: Any | None,
    *,
    turn_run: TurnRun | None = None,
    session_id: str = "",
    turn_id: str = "",
    turn_run_id: str = "",
    stream_run_id: str = "",
) -> dict[str, Any]:
    diagnostics = dict(getattr(turn_run, "diagnostics", {}) or {}) if turn_run is not None else {}
    scope = dict(diagnostics.get("agent_run_scope") or {}) if isinstance(diagnostics.get("agent_run_scope"), dict) else {}
    normalized_session_id = str(session_id or getattr(turn_run, "session_id", "") or scope.get("session_id") or "").strip()
    normalized_turn_id = str(turn_id or getattr(turn_run, "turn_id", "") or scope.get("turn_id") or "").strip()
    normalized_turn_run_id = str(turn_run_id or getattr(turn_run, "turn_run_id", "") or scope.get("turn_run_id") or "").strip()
    normalized_stream_run_id = str(stream_run_id or diagnostics.get("stream_run_id") or _stream_run_id_from_turn_run_id(normalized_turn_run_id) or "").strip()
    if not scope and runtime_host is not None and normalized_stream_run_id:
        supervisor = getattr(runtime_host, "agent_run_supervisor", None)
        getter = getattr(supervisor, "active_cell_for_stream_run", None)
        if callable(getter):
            try:
                cell = getter(normalized_stream_run_id, session_id=normalized_session_id)
            except Exception:
                cell = None
            if cell is not None:
                scope = dict(cell.scope.to_dict())
    return {
        "session_id": str(scope.get("session_id") or normalized_session_id),
        "agent_run_id": str(scope.get("agent_run_id") or ""),
        "run_cell_id": str(scope.get("run_cell_id") or ""),
        "stream_run_id": normalized_stream_run_id,
        "turn_id": normalized_turn_id,
        "turn_run_id": normalized_turn_run_id,
        "task_run_id": str(scope.get("task_run_id") or ""),
        "invocation_kind": str(scope.get("invocation_kind") or "single_turn"),
        "authority": "harness.loop.single_agent_turn.agent_scope",
    }


def _record_turn_scope_on_runtime_run(
    runtime_host: Any,
    *,
    stream_run_id: str,
    agent_scope: dict[str, Any],
    turn_run_id: str,
) -> None:
    normalized_stream_run_id = str(stream_run_id or "").strip()
    if not normalized_stream_run_id:
        return
    registry = getattr(runtime_host, "run_registry", None)
    updater = getattr(registry, "update_run", None)
    if not callable(updater):
        return
    try:
        updater(
            normalized_stream_run_id,
            diagnostics={
                "agent_run_scope": dict(agent_scope or {}),
                "agent_run_id": str(dict(agent_scope or {}).get("agent_run_id") or ""),
                "run_cell_id": str(dict(agent_scope or {}).get("run_cell_id") or ""),
                "runtime_turn_run_id": str(turn_run_id or ""),
            },
        )
    except Exception:
        return


def _stream_run_id_from_turn_run_id(turn_run_id: str) -> str:
    value = str(turn_run_id or "").strip()
    if value.startswith("turnrun:strun:"):
        return value[len("turnrun:"):]
    return ""


def _agent_scope_refs(agent_scope: dict[str, Any] | None) -> dict[str, str]:
    scope = dict(agent_scope or {})
    refs: dict[str, str] = {}
    agent_run_id = str(scope.get("agent_run_id") or "").strip()
    run_cell_id = str(scope.get("run_cell_id") or "").strip()
    if agent_run_id:
        refs["agent_run_ref"] = agent_run_id
    if run_cell_id:
        refs["run_cell_ref"] = run_cell_id
    return refs


def _record_step_summary(
    runtime_host: Any,
    *,
    run_id: str,
    turn_id: str,
    step: str,
    status: str,
    summary: str,
    presentation_source: str = "",
    feedback_identity: str = "",
) -> dict[str, Any]:
    payload, event = _append_step_summary_record(
        runtime_host,
        run_id=run_id,
        turn_id=turn_id,
        step=step,
        status=status,
        summary=summary,
        presentation_source=presentation_source,
        feedback_identity=feedback_identity,
    )
    return {"type": "runtime_step_summary", **payload, "event": event}


def _record_assistant_public_feedback(
    runtime_host: Any,
    *,
    run_id: str,
    turn_id: str,
    step: str,
    status: str,
    summary: str,
    presentation_source: str = "",
    feedback_identity: str = "",
) -> dict[str, Any]:
    payload, event = _append_step_summary_record(
        runtime_host,
        run_id=run_id,
        turn_id=turn_id,
        step=step,
        status=status,
        summary=summary,
        presentation_source=presentation_source,
        feedback_identity=feedback_identity,
    )
    return {"type": ASSISTANT_PUBLIC_FEEDBACK_EVENT, **payload, "event": event}


def _append_step_summary_record(
    runtime_host: Any,
    *,
    run_id: str,
    turn_id: str,
    step: str,
    status: str,
    summary: str,
    presentation_source: str = "",
    feedback_identity: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    visible_summary = public_runtime_progress_summary(summary)
    payload = {
        "turn_id": turn_id,
        "step": step,
        "status": status,
        "summary": visible_summary,
        "public_progress_note": visible_summary,
    }
    if presentation_source:
        payload["presentation_source"] = presentation_source
    if feedback_identity:
        payload["feedback_identity"] = feedback_identity
    refs = {"turn_ref": turn_id}
    if feedback_identity:
        refs["runtime_invocation_packet_ref"] = feedback_identity
    event = runtime_host.event_log.append(
        run_id,
        "step_summary_recorded",
        payload=payload,
        refs=refs,
    )
    turn_run = runtime_host.state_index.get_turn_run(run_id)
    if turn_run is not None:
        runtime_host.state_index.upsert_turn_run(
            replace(
                turn_run,
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                diagnostics={
                    **dict(turn_run.diagnostics or {}),
                    "latest_step": step,
                    "latest_step_status": status,
                    "latest_step_summary": visible_summary,
                    "latest_public_progress_note": visible_summary,
                },
            )
        )
    return payload, event.to_dict()


def _model_public_feedback_identity(
    *,
    packet_ref: str,
    tool_iteration: int,
    tool_actions: list[ModelActionRequest],
) -> str:
    action_refs = [
        str(getattr(item, "request_id", "") or "").strip()
        for item in list(tool_actions or [])
        if str(getattr(item, "request_id", "") or "").strip()
    ]
    action_ref = "|".join(action_refs) if action_refs else "no-action-ref"
    return f"model-packet-public-feedback:{packet_ref}:tool-iteration:{int(tool_iteration or 0)}:actions:{action_ref}"


def _assistant_stream_has_emitted_public_feedback(
    assistant_stream_normalizer: AssistantStreamNormalizer | None,
    public_progress_note: str,
) -> bool:
    if assistant_stream_normalizer is None:
        return False
    return assistant_stream_normalizer.has_emitted_public_text(
        public_runtime_progress_summary(public_progress_note)
    )


def _assistant_stream_continuity_after_event(
    current: dict[str, Any] | None,
    event: dict[str, Any] | None,
    *,
    turn_id: str,
) -> dict[str, Any]:
    payload = dict(event or {})
    event_type = str(payload.get("type") or payload.get("event_type") or "").strip()
    if event_type == ASSISTANT_TEXT_DELTA_EVENT:
        delta = str(payload.get("content") or "")
        if not delta:
            return dict(current or {})
        previous = dict(current or {})
        content = str(previous.get("content") or "") + delta
    elif event_type == ASSISTANT_STREAM_REPAIR_EVENT:
        content = str(payload.get("replacement_content") or "")
        if not content:
            return dict(current or {})
        previous = dict(current or {})
    else:
        return dict(current or {})

    bounded_content, truncated = _bounded_assistant_visible_stream_content(content)
    stream_refs = _append_unique_ref(
        list(dict(previous or {}).get("stream_refs") or []),
        str(payload.get("stream_ref") or ""),
        limit=8,
    )
    latest_sequence = payload.get("sequence")
    if latest_sequence in (None, ""):
        latest_sequence = payload.get("repair_sequence")
    return {
        "turn_id": str(turn_id or ""),
        "message_ref": str(payload.get("message_ref") or dict(previous or {}).get("message_ref") or ""),
        "stream_refs": stream_refs,
        "content": bounded_content,
        "content_sha256": _text_sha256(bounded_content),
        "content_utf8_bytes": len(bounded_content.encode("utf-8")),
        "truncated_from_start": bool(truncated or dict(previous or {}).get("truncated_from_start") is True),
        "latest_event_type": event_type,
        "latest_sequence": latest_sequence,
        "updated_at": time.time(),
        "authority": "harness.loop.single_agent_turn.assistant_stream_continuity",
    }


def _bounded_assistant_visible_stream_content(content: str) -> tuple[str, bool]:
    text = str(content or "")
    if len(text) <= _ASSISTANT_VISIBLE_STREAM_CONTEXT_MAX_CHARS:
        return text, False
    return text[-_ASSISTANT_VISIBLE_STREAM_CONTEXT_MAX_CHARS:], True


def _append_unique_ref(refs: list[Any], ref: str, *, limit: int) -> list[str]:
    values = [str(item) for item in refs if str(item or "").strip()]
    normalized = str(ref or "").strip()
    if normalized and normalized not in values:
        values.append(normalized)
    return values[-max(1, int(limit or 1)):]


def _record_model_action_admission(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    action_request: ModelActionRequest,
    lifecycle: ActionLifecycleDecision,
    packet_ref: str,
) -> dict[str, Any]:
    event_record = build_action_lifecycle_event_record(
        lifecycle,
        action_request,
        run_id=turn_run.turn_run_id,
        packet_ref=packet_ref,
        session_id=str(getattr(turn_run, "session_id", "") or ""),
        turn_id=turn_id,
        turn_run_id=turn_run.turn_run_id,
    )
    event = append_action_lifecycle_event(runtime_host, event_record)
    admission = lifecycle.admission
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            diagnostics={
                **dict(current.diagnostics or {}),
                "latest_admission_decision": admission.decision,
                "latest_action_type": action_request.action_type,
            },
        )
    )
    return event.to_dict()


def _record_turn_runtime_control_signal(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    packet_ref: str,
    control_signal: dict[str, Any],
) -> dict[str, Any]:
    agent_scope = _turn_run_agent_scope(
        runtime_host,
        turn_run=turn_run,
        session_id=turn_run.session_id,
        turn_id=turn_id,
    )
    signal = _turn_runtime_control_signal_with_identity(
        turn_run=turn_run,
        turn_id=turn_id,
        packet_ref=packet_ref,
        control_signal=control_signal,
        agent_scope=agent_scope,
    )
    if isinstance(control_signal, dict):
        control_signal.clear()
        control_signal.update(signal)
    published_event = _publish_turn_runtime_control_signal_to_gateway(
        runtime_host,
        turn_run=turn_run,
        turn_id=turn_id,
        packet_ref=packet_ref,
        signal=signal,
    )
    observed_event = _mark_turn_runtime_control_signal_gateway_observed(
        runtime_host,
        turn_run=turn_run,
        turn_id=turn_id,
        packet_ref=packet_ref,
        signal_id=str(signal["runtime_control_signal_ref"] or ""),
    )
    if observed_event is None:
        raise RuntimeError("runtime_gateway.mark_observed_by_id did not record turn runtime control signal")
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        "turn_runtime_control_signal_observed",
        payload={
            "turn_id": turn_id,
            "model_visible": True,
            "runtime_control_signal": signal,
        },
        refs={
            "turn_ref": turn_id,
            "turn_run_ref": turn_run.turn_run_id,
            "runtime_invocation_packet_ref": packet_ref,
            "runtime_control_signal_ref": signal["runtime_control_signal_ref"],
            **_agent_scope_refs(agent_scope),
            **(
                {"runtime_gateway_signal_event_ref": str(getattr(published_event, "event_id", "") or "")}
                if published_event is not None
                else {}
            ),
            "runtime_gateway_observed_event_ref": str(getattr(observed_event, "event_id", "") or ""),
        },
    )
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            diagnostics={
                **dict(current.diagnostics or {}),
                "latest_runtime_control_signal_ref": str(signal["runtime_control_signal_ref"] or ""),
                "latest_runtime_control_signal_kind": str(signal.get("signal_kind") or ""),
                "latest_step": "runtime_control_signal_observed",
            },
        )
    )
    return event.to_dict()


def _publish_turn_runtime_control_signal_to_gateway(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    packet_ref: str,
    signal: dict[str, Any],
) -> Any | None:
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    publisher = getattr(runtime_gateway, "publish", None)
    signal_id = str(signal.get("runtime_control_signal_ref") or "").strip()
    if not callable(publisher):
        raise RuntimeError("runtime_gateway.publish is required for turn runtime control signals")
    if not signal_id:
        raise ValueError("turn runtime control signal requires runtime_control_signal_ref")
    agent_scope = _turn_run_agent_scope(
        runtime_host,
        turn_run=turn_run,
        session_id=turn_run.session_id,
        turn_id=turn_id,
    )
    scope = RuntimeSignalScope(
        session_id=str(getattr(turn_run, "session_id", "") or ""),
        agent_run_id=str(agent_scope.get("agent_run_id") or ""),
        run_cell_id=str(agent_scope.get("run_cell_id") or ""),
        turn_id=str(turn_id or ""),
        turn_run_id=str(getattr(turn_run, "turn_run_id", "") or ""),
    )
    payload = {
        **dict(signal or {}),
        "adapter": "single_agent_turn_runtime_control_boundary",
        "boundary": "single_agent_turn_runtime_control",
        "turn_id": str(turn_id or ""),
        "turn_run_id": str(getattr(turn_run, "turn_run_id", "") or ""),
        "agent_run_id": str(agent_scope.get("agent_run_id") or ""),
        "run_cell_id": str(agent_scope.get("run_cell_id") or ""),
        "packet_ref": str(packet_ref or ""),
    }
    return publisher(
        turn_run.turn_run_id,
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=scope,
        source_authority="harness.loop.single_agent_turn.runtime_control_boundary",
        payload=payload,
        visibility="runtime_private",
        causation_id=str(packet_ref or ""),
        correlation_id=str(turn_id or ""),
        refs={
            "turn_ref": str(turn_id or ""),
            "turn_run_ref": str(getattr(turn_run, "turn_run_id", "") or ""),
            "runtime_invocation_packet_ref": str(packet_ref or ""),
            "runtime_control_signal_ref": signal_id,
            **_agent_scope_refs(agent_scope),
        },
    )


def _mark_turn_runtime_control_signal_gateway_observed(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    packet_ref: str,
    signal_id: str,
) -> Any | None:
    normalized_signal_id = str(signal_id or "").strip()
    if not normalized_signal_id:
        return None
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    marker = getattr(runtime_gateway, "mark_observed_by_id", None)
    if not callable(marker):
        raise RuntimeError("runtime_gateway.mark_observed_by_id is required for turn runtime control signals")
    return marker(
        turn_run.turn_run_id,
        signal_id=normalized_signal_id,
        observed_by="harness.loop.single_agent_turn.runtime_control_boundary",
        payload={
            "runtime_invocation_packet_ref": str(packet_ref or ""),
            "boundary": "single_agent_turn_runtime_control",
        },
        refs={
            "turn_ref": str(turn_id or ""),
            "turn_run_ref": str(getattr(turn_run, "turn_run_id", "") or ""),
            "runtime_invocation_packet_ref": str(packet_ref or ""),
        },
    )


def _turn_runtime_control_signal_with_identity(
    *,
    turn_run: TurnRun,
    turn_id: str,
    packet_ref: str,
    control_signal: dict[str, Any],
    agent_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signal = dict(control_signal or {})
    signal_ref = str(signal.get("runtime_control_signal_ref") or "").strip()
    if not signal_ref:
        kind = str(signal.get("signal_kind") or signal.get("observation_type") or "runtime_control_signal").strip()
        structured = dict(signal.get("structured_signal") or {})
        protocol_error = dict(signal.get("protocol_error") or {})
        identity_payload = {
            "turn_run_id": str(turn_run.turn_run_id or ""),
            "turn_id": str(turn_id or signal.get("turn_id") or ""),
            "packet_ref": str(packet_ref or signal.get("packet_ref") or ""),
            "signal_kind": kind,
            "runtime_control_state": str(signal.get("runtime_control_state") or ""),
            "phase": str(signal.get("phase") or ""),
            "recovery_attempt": signal.get("recovery_attempt"),
            "used_tool_iterations": signal.get("used_tool_iterations"),
            "consecutive_failure_rounds": signal.get("consecutive_failure_rounds"),
            "commit_reason": str(signal.get("commit_reason") or ""),
            "answer_channel": str(signal.get("answer_channel") or ""),
            "answer_source": str(signal.get("answer_source") or ""),
            "structured_code": str(structured.get("code") or ""),
            "protocol_error_code": str(protocol_error.get("code") or ""),
            "protocol_error_reason": str(protocol_error.get("reason") or ""),
        }
        digest = hashlib.sha256(
            json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        signal_ref = f"turnsig:{_runtime_control_signal_ref_fragment(kind)}:{digest}"
    scope = {**dict(agent_scope or {}), **dict(signal.get("runtime_control_scope") or {})}
    signal["runtime_control_signal_ref"] = signal_ref
    signal["runtime_control_scope"] = {
        **scope,
        "session_id": str(turn_run.session_id or scope.get("session_id") or ""),
        "agent_run_id": str(scope.get("agent_run_id") or ""),
        "run_cell_id": str(scope.get("run_cell_id") or ""),
        "turn_id": str(turn_id or scope.get("turn_id") or ""),
        "turn_run_id": str(turn_run.turn_run_id or scope.get("turn_run_id") or ""),
        "packet_ref": str(packet_ref or scope.get("packet_ref") or signal.get("packet_ref") or ""),
    }
    return signal


def _runtime_control_signal_ref_fragment(kind: str) -> str:
    fragment = "".join(ch if ch.isalnum() else "-" for ch in str(kind or "").strip().lower())
    fragment = "-".join(part for part in fragment.split("-") if part)
    return fragment[:48] or "runtime-control"


def _record_agent_contract_feedback_required(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    packet_ref: str,
    contract_feedback: dict[str, Any],
) -> dict[str, Any]:
    feedback = dict(contract_feedback or {})
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        "agent_contract_feedback_required",
        payload={
            "turn_id": turn_id,
            "model_visible": True,
            "agent_contract_feedback": feedback,
        },
        refs={
            "turn_ref": turn_id,
            "turn_run_ref": turn_run.turn_run_id,
            "runtime_invocation_packet_ref": packet_ref,
        },
    )
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            diagnostics={
                **dict(current.diagnostics or {}),
                "latest_agent_contract_feedback": feedback,
                "latest_step": "agent_contract_feedback_required",
            },
        )
    )
    return event.to_dict()


def _record_turn_tool_batch_event(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    event_type: str,
    payload: dict[str, Any],
    refs: dict[str, Any],
) -> dict[str, Any]:
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        event_type,
        payload=dict(payload or {}),
        refs=dict(refs or {}),
    )
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            diagnostics={
                **dict(current.diagnostics or {}),
                "latest_tool_batch_event": event_type,
                "latest_tool_batch_ref": str(dict(payload or {}).get("tool_batch_ref") or dict(dict(payload or {}).get("tool_batch_plan") or {}).get("batch_id") or ""),
            },
        )
    )
    return event.to_dict()


def _tool_item_started_events_for_group(
    runtime_host: Any | None,
    *,
    turn_run: TurnRun | None,
    turn_id: str,
    group: ToolBatchGroup,
    invocation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if runtime_host is None or turn_run is None:
        return []
    events: list[dict[str, Any]] = []
    for raw_index in tuple(group.item_indexes or ()):
        try:
            row_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if row_index < 0 or row_index >= len(invocation_rows):
            continue
        row = invocation_rows[row_index]
        admission = row.get("admission")
        if str(getattr(admission, "decision", "") or "").strip() != "allow":
            continue
        action_request = row.get("action_request")
        if action_request is None:
            continue
        tool_call = dict(row.get("tool_call") or _tool_call_from_action_request(action_request))
        if not str(tool_call.get("tool_name") or tool_call.get("name") or "").strip():
            continue
        try:
            identity = _turn_action_tool_invocation_identity(
                runtime_host,
                turn_run=turn_run,
                turn_id=turn_id,
                action_request=action_request,
                admission=admission,
                action_permit=dict(row.get("action_permit") or {}),
                action_lifecycle_ref=str(dict(row.get("action_lifecycle") or {}).get("lifecycle_id") or ""),
            )
        except ValueError:
            continue
        tool_args = dict(identity.tool_args or {})
        record = build_tool_lifecycle_started_event_record(
            identity,
            run_id=turn_run.turn_run_id,
            caller_kind="agent_turn",
            turn_id=turn_id,
            turn_run_id=turn_run.turn_run_id,
            target=_native_tool_public_target(tool_args),
            arguments_preview=_native_tool_arguments_preview(tool_args),
        )
        event = runtime_host.event_log.append(
            record.run_id,
            record.event_type,
            payload=record.payload,
            refs=record.refs,
        )
        _update_turn_run_event_offset(runtime_host, turn_run=turn_run, event=event)
        events.append({"type": "tool_item_started", "event": event.to_dict()})
    return events


def _record_turn_terminal(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    status: str,
    terminal_reason: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    terminal_payload = dict(payload or {})
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        "agent_turn_terminal",
        payload={
            "turn_id": turn_id,
            "status": status,
            "terminal_reason": terminal_reason,
            **terminal_payload,
        },
        refs={"turn_ref": turn_id},
    )
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    continuity = dict(terminal_payload.get("assistant_visible_stream_continuity") or {})
    diagnostic_updates = {"assistant_visible_stream_continuity": continuity} if continuity else {}
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            status=_terminal_status_for_turn_run(status),
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            terminal_reason=terminal_reason,
            diagnostics={
                **dict(current.diagnostics or {}),
                "terminal_event_type": "agent_turn_terminal",
                "terminal_status": status,
                "terminal_reason_detail": terminal_reason,
                **diagnostic_updates,
            },
        )
    )
    _complete_active_turn_after_turn_terminal(
        runtime_host,
        session_id=turn_run.session_id,
        turn_id=turn_id,
        terminal_reason=terminal_reason,
    )
    return event.to_dict()


def _complete_active_turn_after_turn_terminal(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    terminal_reason: str,
) -> None:
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is None:
        return
    try:
        record = active_registry.snapshot(session_id)
    except Exception:
        logger.debug("failed to snapshot active turn before terminal cleanup", exc_info=True)
        return
    if record is None or str(getattr(record, "turn_id", "") or "") != str(turn_id or ""):
        return
    bound_task_run_id = str(getattr(record, "bound_task_run_id", "") or "").strip()
    if bound_task_run_id:
        task_run = getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(bound_task_run_id)
        task_status = str(getattr(task_run, "status", "") or "").strip()
        if task_run is not None and task_status not in {
            "completed",
            "success",
            "failed",
            "aborted",
            "cancelled",
            "canceled",
            "error",
            "stopped",
            "user_aborted",
        }:
            return
    try:
        active_registry.complete(session_id=session_id, expected_turn_id=turn_id, terminal_reason=terminal_reason)
    except Exception:
        logger.debug("failed to complete active turn", exc_info=True)


def _terminal_status_for_turn_run(status: str) -> str:
    if status in {"completed", "blocked", "failed", "aborted"}:
        return status
    return "failed"
