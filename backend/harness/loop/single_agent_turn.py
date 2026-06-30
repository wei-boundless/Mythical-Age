from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Awaitable, Callable

from core.project_layout import ProjectLayout
from file_management import external_scope_payloads_for_base_dir
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
    incremental_context_frame_segment_spec,
    is_incremental_context_frame_message,
    prefix_lock_violation_for_index,
)
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan, stable_model_message_hash, stable_text_hash
from harness.runtime.provider_tool_schema import provider_tool_bindings_for_available_tools
from harness.runtime.control_action_schema import (
    CONTROL_ACTION_TOOL_NAMES,
    control_action_arg_errors_from_native_tool_call,
    control_action_request_payload_from_native_tool_call,
    is_control_action_tool_name,
    provider_control_action_bindings,
)
from harness.runtime.tool_call_contract import (
    provider_control_tools_enabled_from_contract,
    provider_tools_enabled_from_contract,
)
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
    CONTEXT_MEMORY_PREFIX,
    NEVER_REPLAY_TAIL,
    PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
    STATIC_PREFIX,
    assemble_physical_context_spine,
    annotate_specs_with_physical_context_plan,
    context_segment_is_provider_visible_sealable_spec,
    context_segment_policy_for_spec,
    context_segment_policy_metadata,
    context_segment_routes_to_dynamic_tail,
    DYNAMIC_TAIL,
    provider_visible_append_candidate_spec,
)
from runtime.context_management.followup_context_rebase import (
    current_followup_append_context_policy,
    provider_protocol_prefix_replay_policy,
)
from runtime.context_management.provider_message_replay_contract import (
    PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY,
    PHYSICAL_PREFIX_FRAME_REPLAY_POLICY,
    PHYSICAL_PREFIX_FRAME_REPLAY_STATUS,
    PROVIDER_PROTOCOL_REPLAY_POLICY,
    PROVIDER_PROTOCOL_REPLAY_STATUS,
    provider_message_byte_preservation_required,
    provider_protocol_append_candidate_metadata,
)
from runtime.context_management.provider_tool_protocol import annotate_provider_tool_round_specs
from runtime.output_stream.public_contract import ASSISTANT_PUBLIC_FEEDBACK_EVENT, TURN_COMPLETED_EVENT
from runtime.context_management.tool_transcript import (
    TOOL_TRANSCRIPT_DELTA_KIND,
    is_current_tool_transcript_kind,
    is_tool_transcript_kind,
)
from runtime.prompt_accounting import ContextUsageMeter
from runtime.prompt_accounting.provider_lane import (
    PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
    PROVIDER_LANE_AGENT_TOOL_LOOP,
)
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
from runtime.model_gateway.lightweight_chat_model import provider_message_payloads
from runtime.model_gateway.stream_iteration import iterate_stream_with_due_ticks
from harness.runtime.output_boundary import (
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
from runtime.shared.models import TurnRun
from runtime.shared.tool_identity import canonical_action_tool_call_id, ensure_tool_call_id
from runtime.tool_runtime import ToolInvocationRequest, ToolObservation, build_round_tool_call_options
from runtime.memory.evidence_delta_summary import build_tool_followup_evidence_delta_summary
from runtime.memory.file_evidence_scope import session_file_evidence_scope
from permissions.policy import normalize_permission_mode
from prompt_library import SINGLE_AGENT_ADMISSION_REPAIR_PROMPT

from .active_turn_steering import ActiveTurnQueuedUserSteers, claim_active_turn_queued_user_steers
from .turn_to_task_context_handoff import build_turn_to_task_context_handoff_seed


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest, dict[str, Any]], AsyncIterator[dict[str, Any]]]
ApplyActiveWorkControl = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
ApplyTaskRecoveryResume = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
CompactSessionContext = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]

_DEFAULT_INTERACTIVE_TOOL_BATCH_TIMEOUT_SECONDS = 45.0
_TOOL_BATCH_CANCEL_DRAIN_SECONDS = 1.0
_ASSISTANT_VISIBLE_STREAM_CONTEXT_MAX_CHARS = 12000
_REASONING_STATUS_MIN_INTERVAL_SECONDS = 0.4
_REASONING_STATUS_MIN_CHAR_DELTA = 160

_AGENT_CLOSEOUT_ACTION_TYPES = ("respond", "ask_user", "block")
_AGENT_CLOSEOUT_SOURCE = "harness.single_agent_turn.agent_closeout"
_ASSISTANT_CONTENT_PREAMBLE_PROGRESS_SOURCE = "model_action.assistant_content_preamble"
_PARTIAL_STREAM_RECOVERY_SOURCE = "harness.single_agent_turn.partial_stream_recovery"
_CONSECUTIVE_TOOL_FAILURE_CLOSEOUT_THRESHOLD = 3
_MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS = 3
_RUNTIME_CONTEXT_SEGMENT_KIND_KEY = "_runtime_context_segment_kind"
_RUNTIME_CONTEXT_SEGMENT_SOURCE_REF_KEY = "_runtime_context_segment_source_ref"
_RUNTIME_CONTEXT_SEGMENT_METADATA_KEY = "_runtime_context_segment_metadata"
_RUNTIME_CONTEXT_SEGMENT_SOURCES: dict[str, tuple[str, str, str]] = {
    "harness.loop.single_agent_turn.runtime_control_signal_recovery": (
        "runtime_control_signal_tail",
        "single_agent_turn.runtime_control_recovery",
        "runtime_control_recovery",
    ),
    "harness.loop.single_agent_turn.agent_authored_closeout": (
        "runtime_control_signal_tail",
        "single_agent_turn.agent_authored_closeout",
        "agent_authored_closeout",
    ),
    "harness.loop.single_agent_turn.admission_repair": (
        "runtime_control_signal_tail",
        "single_agent_turn.admission_repair",
        "admission_repair",
    ),
    "harness.loop.single_agent_turn.tool_followup_action_contract": (
        "single_agent_turn_followup_action_contract",
        "single_agent_turn_tool_followup_action_contract",
        "tool_followup_action_contract",
    ),
}
_CONTROL_ACTION_NAMES = set(CONTROL_ACTION_TOOL_NAMES)
_ACTIVE_WORK_CONTROL_ACTIONS = {
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_then_continue_active_work",
}
_LEGACY_CONTROL_ACTION_NAMES = {"task_run_request"}
_ACTION_OBJECT_ONLY_ACTION_HINTS = {
    "task_run_request": "request_task_run",
}
_ACTION_OBJECT_ONLY_ACTION_NAMES = _LEGACY_CONTROL_ACTION_NAMES
_INTERNAL_MODEL_RESPONSE_EVENT = "__single_agent_model_response"


def _is_model_action_native_tool_name(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return bool(normalized and (normalized in _ACTION_OBJECT_ONLY_ACTION_NAMES or is_control_action_tool_name(normalized)))


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


def _feedback_contract_payload(
    *,
    source: str,
    public_feedback_recommended: bool = False,
    tool_calls_allowed: bool | None = None,
    allowed_action_types: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    return _drop_empty_dict(
        {
            "source": str(source or ""),
            "situation": "上一轮动作或观察改变了你当前可采取的下一步。",
            "your_task": (
                "重新判断用户目标、已确认状态和可行动作。"
                "当语义阶段、风险、失败、验证或用户关切发生变化时，"
                "你需要用自然语言给出用户能理解的结论、问题、阻塞或下一步。"
            ),
            "public_feedback_obligation": (
                "respond_with_public_judgment_now"
                if public_feedback_recommended
                else "maintain_public_feedback_rhythm"
            ),
            "system_handling_of_missing_feedback": "record_contract_gap_only",
            "tool_action_available": tool_calls_allowed if tool_calls_allowed is not None else None,
            "available_actions": [
                str(item)
                for item in list(allowed_action_types or [])
                if str(item or "").strip()
            ],
            "response_slots": [
                "public_progress_note",
                "public_action_state.current_judgment",
                "final_answer",
                "user_question",
                "blocking_reason",
            ],
            "tool_result_feedback": (
                "按用户问题和语义变化反馈。一批低层工具观察服务同一个短证据链时，"
                "可以合并到下一次公开判断；跨阶段、失败恢复、写入验证或最终收口时必须说明影响和下一步。"
            ),
        }
    )


def _agent_visible_action_facts(signal: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(signal or {})
    protocol_error = dict(payload.get("protocol_error") or {})
    diagnostics = dict(protocol_error.get("diagnostics") or {})
    detected_action = dict(payload.get("detected_unexecuted_action") or diagnostics.get("detected_json_action") or {})
    previous_payload = payload.get("rejected_json_action_payload") or diagnostics.get("rejected_json_action_payload")
    model_error = dict(payload.get("model_error") or {})
    return _drop_empty_dict(
        {
            "kind": _agent_visible_signal_kind(payload),
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
            "attempted_actions_not_executed": list(payload.get("attempted_actions_not_executed") or []),
            "recent_observations": list(payload.get("recent_observations") or [])[:3],
            "public_feedback_recommended": bool(payload.get("public_feedback_recommended")),
            "feedback_contract": dict(payload.get("feedback_contract") or {}),
            "previous_action": _drop_empty_dict(
                {
                    "execution_state": str(detected_action.get("execution_state") or "not_executed") if detected_action else "",
                    "action_type": str(detected_action.get("action_type") or ""),
                    "top_level_keys": list(detected_action.get("top_level_keys") or []),
                    "task_run_contract_seed_summary": dict(detected_action.get("task_run_contract_seed_summary") or {}),
                    "tool_call_summary": dict(detected_action.get("tool_call_summary") or {}),
                    "tool_calls_summary": list(detected_action.get("tool_calls_summary") or []),
                    "payload": previous_payload if isinstance(previous_payload, dict) else {},
                }
            ),
            "previous_tool_intents_not_executed": list(payload.get("previous_tool_intents_not_executed") or []),
            "previous_response_preview": _compact_text(payload.get("previous_response_preview"), limit=900),
            "model_error": _drop_empty_dict(
                {
                    "code": str(model_error.get("code") or model_error.get("failure_code") or ""),
                    "reason": str(model_error.get("reason") or ""),
                    "provider": str(model_error.get("provider") or ""),
                    "model": str(model_error.get("model") or ""),
                    "retryable": model_error.get("retryable") if isinstance(model_error.get("retryable"), bool) else None,
                }
            ),
            "observed_facts": dict(payload.get("observed_facts") or {}),
        }
    )


def _agent_visible_action_state(signal: dict[str, Any]) -> str:
    kind = str(signal.get("signal_kind") or "").strip()
    if kind == "model_protocol_violation":
        return "previous_action_not_executed"
    if kind == "final_output_not_committable":
        return "previous_answer_not_saved"
    if kind == "consecutive_tool_failures":
        return "tool_failures"
    return str(signal.get("runtime_control_state") or signal.get("reason") or "")


def _agent_visible_signal_kind(signal: dict[str, Any]) -> str:
    kind = str(signal.get("signal_kind") or signal.get("observation_type") or "").strip()
    if kind == "model_protocol_violation":
        return "previous_action_not_executed"
    if kind == "final_output_not_committable":
        return "previous_answer_not_finalized"
    return kind


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
        fields["request_task_run"] = "compact TaskStartIntent in task_run_contract_seed"
    if "tool_call" in allowed:
        fields["tool_call"] = "tool_call or tool_calls"
    if "active_work_control" in allowed:
        fields["active_work_control"] = "active_work_control"
    if "resume_task_recovery" in allowed:
        fields["resume_task_recovery"] = "task_recovery_resume"
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
            "observation_type": "agent_final_feedback_lifecycle",
            "lifecycle": "agent_authored_final_feedback",
            "cause": str(reason or "").strip(),
            "phase": str(phase or "").strip(),
            "attempt": _drop_empty_dict(
                {
                    "current": int(closeout_attempt or 0),
                    "max": int(max_closeout_attempts or 0),
                }
            ),
            "tool_action_available": False,
            "allowed_actions": list(_AGENT_CLOSEOUT_ACTION_TYPES),
            "required_user_visible_decision": {
                "respond": "final_answer when facts are enough to answer or summarize",
                "ask_user": "user_question when user choice or missing input is required",
                "block": "blocking_reason when facts, permissions, or environment are insufficient",
            },
            "facts": _agent_visible_action_facts(signal),
            "protocol_error": dict(protocol_error or {}),
            "previous_invalid_response_preview": _compact_text(previous_invalid_response, limit=1200),
            "agent_obligations": [
                "base the final feedback only on observed facts and user-visible implications",
                "state what is confirmed, what is incomplete, and how work can continue",
                "write the final user-facing judgment in your own words",
            ],
            "forbidden": [
                "do not call tools",
                "do not submit tool_call or tool_calls",
                "do not present action fields, runtime refs, diagnostics, or debug payloads as the answer",
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
        allowed_action_types=_AGENT_CLOSEOUT_ACTION_TYPES,
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


def _agent_authored_closeout_content_from_response(
    response: Any,
    *,
    turn_id: str,
    packet_ref: str,
    closeout_attempt: int,
    phase: str,
) -> tuple[AgentAuthoredCloseoutContent | None, dict[str, Any]]:
    action_parse = _single_agent_action_request_from_response(
        response,
        request_id=f"model-response:{packet_ref}:agent-closeout:{phase}:{closeout_attempt}",
        turn_id=turn_id,
        packet_ref=packet_ref,
        iteration=closeout_attempt,
        allowed_action_types=_AGENT_CLOSEOUT_ACTION_TYPES,
        phase=f"agent_closeout:{phase}",
        output_contract=_assistant_message_or_action_output_channel_contract(phase=f"closeout_decision:{phase}"),
        allow_model_tool_calls=False,
    )
    if action_parse.error:
        return None, {
            "status": "closeout_action_not_consumed",
            "reason": str(dict(action_parse.error or {}).get("reason") or dict(action_parse.error or {}).get("code") or "closeout_action_not_consumed"),
            "protocol_error": dict(action_parse.error or {}),
            "native_tool_call_count": len(action_parse.native_tool_calls or []),
            "authority": "harness.loop.single_agent_turn.agent_closeout_response_boundary",
        }
    action_request = action_parse.control_action or action_parse.action_request
    if action_request is not None:
        if action_request.action_type == "respond":
            return AgentAuthoredCloseoutContent(content=str(action_request.final_answer or "").strip()), {}
        if action_request.action_type == "ask_user":
            return AgentAuthoredCloseoutContent(
                content=str(action_request.user_question or "").strip(),
                answer_channel="ask_user",
            ), {}
        if action_request.action_type == "block":
            return AgentAuthoredCloseoutContent(
                content=str(action_request.blocking_reason or "").strip(),
                answer_channel="blocked",
                terminal_status="blocked",
            ), {}
        return None, {
            "status": "closeout_action_not_consumed",
            "reason": f"closeout_action_not_consumed:{action_request.action_type}",
            "action_type": str(action_request.action_type or ""),
            "authority": "harness.loop.single_agent_turn.agent_closeout_response_boundary",
        }
    content = str(action_parse.assistant_final_text or stringify_content(getattr(response, "content", response))).strip()
    structured_content = _agent_authored_closeout_content_from_structured_payload(content, turn_id=turn_id)
    if structured_content is not None:
        return structured_content, {}
    if content:
        return AgentAuthoredCloseoutContent(content=content), {}
    return None, {
        "status": "closeout_empty_response",
        "reason": "closeout_empty_response",
        "authority": "harness.loop.single_agent_turn.agent_closeout_response_boundary",
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
        "allowed_agent_actions": list(_AGENT_CLOSEOUT_ACTION_TYPES),
        "tool_calls_allowed_after_signal": False,
        "feedback_contract": _feedback_contract_payload(
            source="consecutive_tool_failures",
            public_feedback_recommended=True,
            tool_calls_allowed=False,
            allowed_action_types=list(_AGENT_CLOSEOUT_ACTION_TYPES),
        ),
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


def _model_invocation_failure_closeout_control_signal(
    *,
    turn_id: str,
    packet_ref: str,
    phase: str,
    response: dict[str, Any],
    recent_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(response or {})
    model_error = _drop_empty_dict(
        {
            "code": str(payload.get("code") or payload.get("failure_code") or "single_agent_turn_model_failed"),
            "reason": str(payload.get("reason") or payload.get("code") or "single_agent_turn_model_failed"),
            "failure_code": str(payload.get("failure_code") or payload.get("code") or ""),
            "error_summary": str(payload.get("error_summary") or payload.get("content") or ""),
            "provider": str(payload.get("provider") or ""),
            "model": str(payload.get("model") or ""),
            "retryable": payload.get("retryable") if isinstance(payload.get("retryable"), bool) else None,
        }
    )
    instruction = (
        "本轮后续模型调用失败，当前不能继续工具循环。"
        "你必须基于已经观察到的事实和这次失败事实收口，选择 respond、ask_user 或 block；"
        "不要继续发起工具调用，不要把内部错误对象、事件编号或运行诊断当作用户回复。"
    )
    return {
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "signal_kind": "model_invocation_failed",
        "runtime_control_state": "agent_closeout_required",
        "turn_id": turn_id,
        "packet_ref": packet_ref,
        "phase": phase,
        "agent_closeout_required": True,
        "allowed_agent_actions": list(_AGENT_CLOSEOUT_ACTION_TYPES),
        "tool_calls_allowed_after_signal": False,
        "feedback_contract": _feedback_contract_payload(
            source="model_invocation_failed",
            public_feedback_recommended=True,
            tool_calls_allowed=False,
            allowed_action_types=list(_AGENT_CLOSEOUT_ACTION_TYPES),
        ),
        "model_error": model_error,
        "observed_facts": _drop_empty_dict(
            {
                "recent_observations": [dict(item) for item in list(recent_observations or [])[-3:]],
                "recent_observation_count": len(list(recent_observations or [])),
            }
        ),
        "repair_instruction": instruction,
        "structured_signal": {
            "code": "single_agent_turn_model_invocation_failed",
            "message": instruction,
            "origin": "single_agent_turn_model_invocation_boundary",
            "retryable": model_error.get("retryable"),
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
    public_feedback_recommended: bool = False,
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
    previous_tool_intents = [
        dict(item)
        for item in list(
            diagnostics.get("previous_tool_intents_not_executed")
            or dict(diagnostics.get("explicit_tool_transport") or {}).get("tool_intents")
            or []
        )
        if isinstance(item, dict)
    ]
    specific_repair = _protocol_error_specific_repair_instruction(protocol_error)
    instruction = (
        "上一轮行动意图没有进入执行队列。"
        "请根据用户目标、已观察事实、可用动作和执行反馈，重新提交一个当前可执行的动作。"
        "把你的公开判断和本次行动放在同一个结构化动作对象里。"
    )
    if recovery_exhausted:
        instruction += (
            "同一行动校正已经达到上限；不要重复同一未执行的动作形状。"
            "请重新评估当前事实，选择一个新的合法动作。"
        )
    if detected_action:
        detected_action_type = str(detected_action.get("action_type") or "").strip()
        action_hint = f"（action_type={detected_action_type}）" if detected_action_type else ""
        instruction += (
            f"上一轮输出中已有一个结构化动作{action_hint}，但没有进入执行队列。"
            "如果该动作仍是你的判断，请保留语义意图，修正字段，并作为唯一动作重新提交。"
        )
    if specific_repair:
        instruction += f"具体修复：{specific_repair}"
    if public_feedback_recommended:
        instruction += (
            "本次已经触发公开反馈义务：需要让用户知道你对当前问题、失败、风险或下一步的判断。"
            "如果继续查证，可以在结构化动作的 public_progress_note 或 public_action_state.current_judgment "
            "中说明已确认事实、影响和下一步。"
            "如果你直接调用普通工具，不要在工具调用前后夹带普通正文；等观察返回后在下一次结构化动作、"
            "respond、ask_user 或 block 中补上同一判断目标的公开交代。"
        )
    if not tool_calls_allowed:
        instruction += "当前阶段没有可继续执行的工具动作；请在 allowed_agent_actions 内选择回答、询问、阻塞或其他已开放动作。"
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
        "public_feedback_recommended": bool(public_feedback_recommended),
        "feedback_contract": _feedback_contract_payload(
            source="previous_action_not_executed",
            public_feedback_recommended=public_feedback_recommended,
            tool_calls_allowed=bool(tool_calls_allowed),
            allowed_action_types=allowed,
        ),
        "protocol_error": dict(protocol_error or {}),
        "detected_unexecuted_action": detected_action,
        "previous_tool_intents_not_executed": previous_tool_intents,
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
    allowed_action_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    receipt = dict(commit.receipt or {})
    decision = commit.decision
    reason = str(receipt.get("reason") or "session_output_commit_not_committed")
    allowed = [str(item) for item in list(allowed_action_types or ()) if str(item)]
    tool_calls_allowed = "tool_call" in set(allowed)
    instruction = (
        "上一轮没有形成可保存的自然回应。"
        "请保留你已经形成的判断，重新给出本次行动：如果需要继续查证，可以请求工具；如果已经足够回答，给出自然回应；如果缺少条件，询问用户或说明阻塞。"
        "不要把动作字段或运行记录当作给用户看的正文。"
    )
    return {
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "signal_kind": "final_output_not_committable",
        "runtime_control_state": "model_action_recovery_required",
        "turn_id": turn_id,
        "packet_ref": packet_ref,
        "phase": phase,
        "agent_closeout_required": False,
        "allowed_agent_actions": allowed or list(_AGENT_CLOSEOUT_ACTION_TYPES),
        "tool_calls_allowed_after_signal": bool(tool_calls_allowed),
        "feedback_contract": _feedback_contract_payload(
            source="final_output_not_committable",
            public_feedback_recommended=True,
            tool_calls_allowed=bool(tool_calls_allowed),
            allowed_action_types=allowed or list(_AGENT_CLOSEOUT_ACTION_TYPES),
        ),
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
        "feedback_contract": dict(signal.get("feedback_contract") or _feedback_contract_payload(
            source="runtime_control_signal_recovery",
            public_feedback_recommended=bool(signal.get("public_feedback_recommended")),
            tool_calls_allowed="tool_call" in set(allowed),
            allowed_action_types=allowed,
        )),
        "allowed_action_types": allowed,
        "tool_call_allowed": "tool_call" in set(allowed_action_types or ()),
        "required_fields": _agent_visible_action_fields(allowed),
        "output": {
            "shape": "直接回答或一个结构化动作对象",
            "tool_contract": "需要使用工具时，只按本轮工具行动合同提交当前允许的工具行动，不要额外写第二种工具请求。",
            "respond_contract": "如果只需要回答用户，可以直接自然回应；也可以使用 action_type=respond，并把自然回应写入 final_answer。",
        },
    }
    if recovery_exhausted:
        payload["facts"]["same_repair_channel_exhausted"] = True
    if detected_action:
        payload["previous_action"] = detected_action
    instruction = (
        "请根据以下事实选择下一步动作。\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"
        "保留用户目标和已确认事实。"
        "如果只是回答用户且不需要其它生命周期动作，可以直接自然回应。"
        "如果上一轮工具、控制、询问或阻塞动作仍然正确，修正字段后重新提交结构化动作；"
        "也可以使用 action_type=respond，并把自然回应写入 final_answer。"
    )
    return _append_model_messages_without_rewriting_context(
        model_messages,
        [{"role": "system", "content": instruction, "turn_id": turn_id}],
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
            "resume_task_recovery",
            "tool_call",
        }.intersection(str(item) for item in tuple(allowed_action_types or ()))
    )


def _tool_followup_action_contract_messages(
    model_messages: list[dict[str, Any]],
    *,
    turn_id: str,
    allowed_action_types: tuple[str, ...],
    tool_iteration: int,
    output_contract: SingleAgentOutputChannelContract,
    evidence_delta_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    allowed = tuple(str(item) for item in tuple(allowed_action_types or ()) if str(item))
    evidence_summary = _drop_empty_dict(dict(evidence_delta_summary or {}))
    payload = {
        "context_kind": "tool_observation_followup",
        "tool_followup_iteration": int(tool_iteration or 0),
        "allowed_action_types": list(allowed),
        "required_fields": _agent_visible_action_fields(allowed),
        "tool_call_allowed": "tool_call" in set(allowed),
        "output_channel": _tool_followup_output_channel_cursor(output_contract, allowed_action_types=allowed),
        "contract_refs": _tool_followup_contract_refs(allowed),
    }
    if evidence_summary:
        payload["evidence_delta"] = _tool_followup_evidence_cursor(evidence_summary)
    evidence_instruction = (
        "先按 evidence_delta 的当前观察和边界游标校准结论；证据规则见 answer_evidence_alignment_contract。\n"
        if evidence_summary
        else ""
    )
    instruction = (
        "你是正在根据刚才工具观察决定下一步的 coding agent。\n"
        "先判断刚才观察改变了什么，再为当前 turn 选择一个允许动作；保持用户目标和已确认事实不变。\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"
        f"{evidence_instruction}"
        "事实足够时直接给用户完整自然语言回复，或提交 respond.final_answer。"
        "需要继续观察时提交一个 tool_call；需要用户补充时提交 ask_user；事实或权限不足时提交 block。"
        "需要长期保存目标、计划、todo、恢复点或验收边界时提交 request_task_run，并只填写紧凑 TaskStartIntent。"
        "不要同时给出自然正文和另一个动作对象。"
    )
    return _append_model_messages_without_rewriting_context(
        model_messages,
        [
            {
                "role": "user",
                "content": instruction,
                "turn_id": turn_id,
                "source_ref": "single_agent_turn_tool_followup_action_contract",
            }
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.tool_followup_action_contract",
    )


def _tool_followup_output_channel_cursor(
    output_contract: SingleAgentOutputChannelContract,
    *,
    allowed_action_types: tuple[str, ...],
) -> dict[str, Any]:
    payload = output_contract.to_dict()
    respond_allowed = "respond" in {str(item) for item in tuple(allowed_action_types or ()) if str(item)}
    return _drop_empty_dict(
        {
            "shape_ref": "action_schema_static.action_shape_rules",
            "public_response_ref": "action_schema_static.public_response_obligation",
            "phase": str(payload.get("phase") or ""),
            "action_required": payload.get("action_required") if isinstance(payload.get("action_required"), bool) else None,
            "provider_json_object_required": (
                payload.get("provider_json_object_required")
                if isinstance(payload.get("provider_json_object_required"), bool)
                else None
            ),
            "direct_visible_text_allowed": (
                payload.get("direct_visible_text_stream_allowed")
                if isinstance(payload.get("direct_visible_text_stream_allowed"), bool)
                else None
            ),
            "raw_assistant_text_allowed": (
                payload.get("raw_assistant_text_allowed")
                if isinstance(payload.get("raw_assistant_text_allowed"), bool)
                else None
            ),
            "natural_response_carrier": (
                "assistant_message_or_respond.final_answer"
                if respond_allowed
                else str(payload.get("natural_response_carrier") or "")
            ),
        }
    )


def _tool_followup_contract_refs(allowed_action_types: tuple[str, ...]) -> dict[str, Any]:
    allowed = {str(item) for item in tuple(allowed_action_types or ()) if str(item)}
    return _drop_empty_dict(
        {
            "action_schema": "action_schema_static",
            "action_type": "action_schema_static.action_type",
            "action_shape": "action_schema_static.action_shape_rules",
            "public_response": "action_schema_static.public_response_obligation",
            "tool_call_shape": "action_schema_static.action_shape_rules.tool_call" if "tool_call" in allowed else "",
            "task_lifecycle": (
                "model_turn_action.task_lifecycle_action_contract"
                if "request_task_run" in allowed
                else ""
            ),
            "evidence_alignment": "answer_evidence_alignment_contract",
        }
    )


def _tool_followup_evidence_cursor(evidence_summary: dict[str, Any]) -> dict[str, Any]:
    payload = dict(evidence_summary or {})
    return _drop_empty_dict(
        {
            "summary_ref": str(payload.get("summary_ref") or ""),
            "tool_iteration": payload.get("tool_iteration"),
            "current_observation_count": payload.get("current_observation_count"),
            "cumulative_observation_count": payload.get("cumulative_observation_count"),
            "new_observations": list(payload.get("new_observations") or [])[:4],
            "ledger_cursor": dict(payload.get("ledger_cursor") or {}),
            "evidence_boundary_cursor": dict(payload.get("evidence_boundary_cursor") or {}),
            "contract_ref": str(payload.get("contract_ref") or "answer_evidence_alignment_contract"),
        }
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
    stop_context = _agent_visible_stop_context(closeout_lifecycle)
    instruction = (
        "你是正在为当前 turn 收口的 coding agent。\n"
        "你收到的是本轮不能继续执行后的事实摘要。现在由你亲自判断如何向用户交代；这一步的可见解释由你负责。\n"
        "这一阶段不能再调用工具。你可以直接给用户一段完整的自然语言收口；如果需要让运行时记录等待用户或阻塞状态，则提交一个结构化 ask_user 或 block 动作。\n"
        "本阶段不是工具调用阶段；不要使用 tool_calls、function_call、工具名或参数包装。\n"
        "先判断事实是否足够：足够说明当前结果时，直接写出自然、完整的用户回复，Markdown 可以用于清晰排版；也可以用 action_type=respond 且 final_answer 承载同一段回复。\n"
        "如果需要用户做选择或补充信息，提交 action_type=ask_user，并把用户能直接回答的问题写入 user_question。\n"
        "如果事实、权限、环境或模型调用状态不足以可靠继续，提交 action_type=block，并把阻塞边界写入 blocking_reason。\n"
        "你的可见回复要按时间顺序交代：已经确认了什么、哪里停住了、哪些目标还没有完成、用户或下一轮可以怎样继续。"
        "不要把工具记录、内部字段名、事件编号、运行诊断或生命周期对象当成给用户的正文。\n"
        "如果停止事实来自搜索参数、路径、权限、读取窗口、上下文预算、大文件边界或模型调用失败，把它当作执行事实来解释影响和可继续方向。\n"
        "如果你还没有完成用户目标，要明确说未完成；不要把未验证的工作说成已经完成。\n\n"
        "当前阶段事实如下，只用于你理解原因和边界，不要逐字泄露内部字段：\n"
        f"{json.dumps({'current_stop_context': stop_context}, ensure_ascii=False, sort_keys=True)}"
    )
    return _append_model_messages_without_rewriting_context(
        model_messages,
        [{"role": "system", "content": instruction, "turn_id": turn_id}],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.agent_authored_closeout",
    )


def _agent_visible_stop_context(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload or {})
    keep = {
        "reason",
        "phase",
        "turn_id",
        "packet_ref",
        "contract_failure",
        "observed_facts",
        "next_action_requirements",
        "agent_feedback",
        "structured_signal",
    }
    visible = {key: raw.get(key) for key in keep if key in raw}
    if "structured_signal" in visible and isinstance(visible["structured_signal"], dict):
        signal = dict(visible["structured_signal"])
        visible["structured_signal"] = {
            key: value
            for key, value in signal.items()
            if key in {"message", "reason", "retryable"}
        }
    return {key: value for key, value in visible.items() if value not in ("", None, [], {})}


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
        "feedback_contract": _feedback_contract_payload(
            source="agent_contract_feedback_required",
            public_feedback_recommended=True,
            tool_calls_allowed=False,
            allowed_action_types=list(_AGENT_CLOSEOUT_ACTION_TYPES),
        ),
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
        "next_action_requirements": {
            "allowed_action_types": list(_AGENT_CLOSEOUT_ACTION_TYPES),
            "tool_call_allowed": False,
            "one_action_only": True,
            "visible_response_fields": ["final_answer", "user_question", "blocking_reason"],
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
        "上一条输出没有形成可执行的动作合同。",
        "请保留用户目标和已确认事实，重新判断下一步动作。",
        f"当前阶段：{phase_text}",
    ]
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
        "下一步要求：不能调用工具，也不能混入第二个动作。"
        "如果只是向用户收口，可以直接自然回复；如果需要记录等待用户或阻塞状态，提交 ask_user 或 block 结构化动作。"
    )
    pieces.append(
        "按真实情况选择动作：事实足够就直接写自然、可发布的收口，或用 respond.final_answer 承载同一段回复；"
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
    if not items and not str(control_signal.get("commit_reason") or "").strip():
        signal_reason = str(control_signal.get("signal_kind") or control_signal.get("reason") or control_signal.get("code") or "").strip()
        if signal_reason:
            attempted_tool_names = [
                str(dict(dict(item or {}).get("tool_call") or {}).get("tool_name") or "").strip()
                for item in list(control_signal.get("attempted_actions_not_executed") or [])
                if isinstance(item, dict)
            ]
            items.append(
                _contract_feedback_item_for_reason(
                    signal_reason,
                    diagnostics={
                        **diagnostics,
                        "tool_names": [name for name in attempted_tool_names if name],
                        "used_tool_iterations": control_signal.get("used_tool_iterations"),
                        "max_tool_iterations": control_signal.get("max_tool_iterations"),
                        "attempted_actions_not_executed": list(control_signal.get("attempted_actions_not_executed") or []),
                    },
                )
            )
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
    normalized = str(reason or "action_contract_failed").strip()
    if normalized in {"tool_budget_exhausted", "consecutive_tool_failures"}:
        used = diagnostics.get("used_tool_iterations")
        maximum = diagnostics.get("max_tool_iterations")
        budget_text = f"{used}/{maximum}" if used not in (None, "") and maximum not in (None, "") else "已耗尽"
        attempted = _attempted_tool_summaries(diagnostics.get("attempted_actions_not_executed"))
        tool_text = "；未执行工具：" + "、".join(attempted) if attempted else ""
        if normalized == "consecutive_tool_failures":
            return {
                "category": "runtime_control",
                "code": "consecutive_tool_failures",
                "reason": "consecutive_tool_failures",
                "situation_feedback": f"已经连续工具失败{tool_text}；上一条工具请求没有执行，不能继续重复同类工具动作。",
                "repair_instruction": "基于已经观察到的失败事实收口；如果证据不足，说明缺口并询问用户或阻塞，不要再次调用同类工具。",
                "expected_next_action": "不要再调用工具；用 respond.final_answer、ask_user.user_question 或 block.blocking_reason 收口。",
            }
        return {
            "category": "runtime_control",
            "code": "tool_budget_exhausted",
            "reason": "tool_budget_exhausted",
            "situation_feedback": f"本轮工具预算已经耗尽（{budget_text}）{tool_text}；上一条工具请求没有执行，不能继续申请工具。",
            "repair_instruction": "用你自己的判断收口；如果证据不足，说明缺口并询问用户或阻塞，不要再次调用工具。",
            "expected_next_action": "不要再调用工具；用 respond.final_answer、ask_user.user_question 或 block.blocking_reason 收口。",
        }
    return {
        "category": "protocol_violation",
        "code": normalized,
        "reason": normalized,
        "situation_feedback": _situation_feedback_for_contract_code(normalized, requested_tool="、".join(tool_names)),
        "repair_instruction": _repair_instruction_for_contract_code(normalized, requested_tool="、".join(tool_names)),
        "expected_next_action": _expected_next_action_for_contract_code(normalized, requested_tool="、".join(tool_names)),
    }


def _attempted_tool_summaries(value: Any) -> list[str]:
    summaries: list[str] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        tool_call = dict(item.get("tool_call") or {}) if isinstance(item.get("tool_call"), dict) else {}
        name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        if not name:
            continue
        args = dict(tool_call.get("args") or {}) if isinstance(tool_call.get("args"), dict) else {}
        path = str(args.get("path") or "").strip()
        summaries.append(f"{name}({path})" if path else name)
    return summaries


def _contract_feedback_phase_text(phase: str) -> str:
    normalized = str(phase or "").strip()
    labels = {
        "consecutive_tool_failure_closeout": "连续工具失败后的阶段反馈，不能重复同类失败动作，只能解释失败、询问用户或阻塞。",
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
        "tool_action_intent_not_in_current_connection",
        "action_object_required_for_control_action",
        "multiple_native_action_sources",
        "single_agent_turn_multiple_action_sources",
        "final_answer_required_for_respond",
        "blocking_reason_required_for_block",
        "user_question_required_for_ask_user",
        "tool_budget_exhausted",
    }


def _situation_feedback_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "你没有提交本阶段要求的结构化动作，上一条输出不能进入执行。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        tool_hint = f"（{requested_tool}）" if requested_tool else ""
        return f"上一轮提出了工具动作{tool_hint}，但当前阶段没有可执行的工具动作；这次工具请求尚未执行。"
    if normalized == "tool_action_intent_not_in_current_connection":
        tool_hint = f"（{requested_tool}）" if requested_tool else ""
        return f"上一轮表达了工具行动意图{tool_hint}，但没有进入当前可执行工具队列；这次工具请求尚未执行。"
    if normalized == "action_object_required_for_control_action":
        action_hint = f"（{requested_action}）" if requested_action else ""
        return f"你把动作选择{action_hint}放在了错误的工具请求位置；它需要作为本轮控制动作提交。"
    if normalized == "tool_budget_exhausted":
        return "本轮工具预算已经耗尽；上一条工具请求没有执行，不能继续申请工具。"
    if normalized in {"multiple_native_action_sources"}:
        return "同一轮出现了多个动作决定，无法判断哪一个才是你的唯一真实决策。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "同一轮出现多个动作来源，无法判断哪一个才是你的真实决定。"
    if normalized in {"final_answer_required_for_respond"}:
        return "你选择了 respond，但没有提供 final_answer；这样会让用户只看到状态或记录，而不是 agent 的自然回复。"
    if normalized in {"blocking_reason_required_for_block"}:
        return "你选择了 block，但没有说明具体阻塞事实；用户和后续 agent 都无法判断卡点是权限、证据、环境还是目标不清。"
    if normalized in {"user_question_required_for_ask_user"}:
        return "你选择了 ask_user，但没有给出用户可以直接回答的问题。"
    return "上一条输出不能进入执行或发布。"


def _repair_instruction_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "如果只是回答用户，可以直接自然回复；如果需要工具、询问、阻塞或控制，提交一个可唯一识别的结构化动作。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        tool_hint = f"（刚才请求的是 {requested_tool}）" if requested_tool else ""
        return f"当前阶段不能继续执行该工具动作{tool_hint}；保留判断，改用回答、询问或阻塞说明表达下一步。"
    if normalized == "tool_action_intent_not_in_current_connection":
        tool_hint = f"（刚才请求的是 {requested_tool}）" if requested_tool else ""
        return f"保留同一个观察目标{tool_hint}，按本轮工具行动合同重新提交工具行动；如果事实已经足够，可以直接自然回复或使用 respond.final_answer。"
    if normalized == "action_object_required_for_control_action":
        return "保留原动作意图，选择对应控制动作并填写参数；申请长任务资源时只填写紧凑 TaskStartIntent。"
    if normalized == "tool_budget_exhausted":
        return "基于已经观察到的事实收口；如果证据不足，说明缺口并询问用户或阻塞，不要再次调用工具。"
    if normalized in {"multiple_native_action_sources"}:
        return "只保留一个普通工具动作集合；不要在同一轮混合多个决策。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "只保留一个动作决定；如果要调用工具，按本轮工具行动合同表达，不要同时提交两种工具行动。"
    if normalized in {"final_answer_required_for_respond"}:
        return "如果选择 respond，必须填写 final_answer；如果事实不足，不要空答，改用 ask_user 或 block。"
    if normalized in {"blocking_reason_required_for_block"}:
        return "如果选择 block，必须填写 blocking_reason，并说明具体阻塞事实、缺少的权限或缺失信息。"
    if normalized in {"user_question_required_for_ask_user"}:
        return "如果选择 ask_user，必须填写 user_question，并提出用户能直接回答的具体问题。"
    return "根据 allowed_action_types 重新提交一个允许动作，保留已确认事实，不要把动作字段当作自然回应，也不要重复同一无效形状。"


def _expected_next_action_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "重新选择 respond、ask_user 或 block，并把对应正文放入 final_answer、user_question 或 blocking_reason。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        return "承认当前不能继续执行该工具；基于已有观察收口，或说明需要用户/环境提供什么条件。"
    if normalized == "tool_action_intent_not_in_current_connection":
        return "按当前工具行动合同重新提交同一个观察目标，或基于已有事实收口。"
    if normalized == "action_object_required_for_control_action":
        return "提交同等语义的控制动作。"
    if normalized == "tool_budget_exhausted":
        return "不要再调用工具；用 respond.final_answer、ask_user.user_question 或 block.blocking_reason 收口。"
    if normalized in {"multiple_native_action_sources"}:
        return "删掉冲突动作，只提交一个可执行的结构化决定。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "删掉冲突动作，只提交一个可执行的决定。"
    if normalized in {"final_answer_required_for_respond"}:
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
    return "不要复述不可提交文本，重新生成一个自然、完整、可发布的 agent 输出。"


def _commit_feedback_instruction(*, commit_reason: str, leak_flags: list[str]) -> str:
    if any("runtime_protocol" in flag or "internal_protocol" in flag for flag in leak_flags):
        return "不要解释内部字段；把事实、结果、风险和下一步改写成你自己的自然回复。"
    if commit_reason in {"empty_final_text", "missing_answer"}:
        return "给出真实 final_answer；如果无法可靠回答，改用 ask_user 或 block。"
    return "用 respond、ask_user 或 block 重新给出自然回应、问题或阻塞说明。"


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
    return str(dict(event or {}).get("type") or "").strip() in {"done", "error", "stopped", TURN_COMPLETED_EVENT}


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
    payload = dict(event or {})
    event_type = str(payload.get("type") or "").strip()
    if event_type == TURN_COMPLETED_EVENT:
        status = str(payload.get("status") or "").strip().lower()
        if status in {"completed", "blocked", "failed", "aborted", "interrupted", "stopped"}:
            return "aborted" if status == "stopped" else status
        return "failed"
    if event_type == "done":
        return "completed"
    if event_type == "stopped":
        return "aborted"
    return "failed"


@dataclass(frozen=True, slots=True)
class SingleAgentOutputChannelContract:
    phase: str
    action_transport_required: bool
    provider_json_object_required: bool
    visible_body_source: str
    direct_visible_text_stream_allowed: bool
    raw_assistant_text_allowed: bool
    action_required: bool
    natural_response_carrier: str
    preferred_action_transport: str = ""
    fallback_action_transport: str = ""
    action_authority: str = "harness.loop.model_action_request"
    authority: str = "harness.loop.single_agent_turn.output_channel_contract"

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": str(self.phase or ""),
            "action_transport_required": bool(self.action_transport_required),
            "action_required": bool(self.action_required),
            "provider_json_object_required": bool(self.provider_json_object_required),
            "visible_body_source": str(self.visible_body_source or ""),
            "direct_visible_text_stream_allowed": bool(self.direct_visible_text_stream_allowed),
            "raw_assistant_text_allowed": bool(self.raw_assistant_text_allowed),
            "natural_response_carrier": str(self.natural_response_carrier or ""),
            "preferred_action_transport": str(self.preferred_action_transport or ""),
            "fallback_action_transport": str(self.fallback_action_transport or ""),
            "action_identity_bound_by_runtime": True,
        }


def _single_agent_output_channel_contract(
    *,
    action_transport_required: bool,
    phase: str = "initial_decision",
    provider_json_object_required: bool | None = None,
    direct_visible_text_stream_allowed: bool | None = None,
    raw_assistant_text_allowed: bool | None = None,
    preferred_action_transport: str = "",
    fallback_action_transport: str = "",
) -> SingleAgentOutputChannelContract:
    action_required = bool(action_transport_required)
    json_required = action_required if provider_json_object_required is None else bool(provider_json_object_required)
    direct_stream_allowed = False if action_required else (
        True
        if direct_visible_text_stream_allowed is None
        else bool(direct_visible_text_stream_allowed)
    )
    raw_text_allowed = (
        bool(direct_stream_allowed and not action_required)
        if raw_assistant_text_allowed is None
        else bool(raw_assistant_text_allowed)
    )
    return SingleAgentOutputChannelContract(
        phase=str(phase or ("action_decision" if action_required else "initial_decision")),
        action_transport_required=action_required,
        provider_json_object_required=json_required,
        visible_body_source=(
            "assistant_text_or_model_action_user_field"
            if action_required and raw_text_allowed
            else ("model_action_user_field" if action_required else "assistant_text")
        ),
        direct_visible_text_stream_allowed=direct_stream_allowed,
        raw_assistant_text_allowed=raw_text_allowed,
        action_required=action_required,
        natural_response_carrier=(
            "assistant_message_or_respond.final_answer"
            if action_required and raw_text_allowed
            else ("respond.final_answer" if action_required else "assistant_message")
        ),
        preferred_action_transport=str(
            preferred_action_transport
            or (
                "assistant_message_or_provider_control_tool_or_json_action_object"
                if action_required and raw_text_allowed
                else ("provider_control_tool_or_json_action_object" if action_required else "assistant_message_or_action")
            )
        ),
        fallback_action_transport=str(
            fallback_action_transport
            or (
                "assistant_message_or_json_action_object"
                if action_required and raw_text_allowed
                else ("json_action_object" if action_required else "json_action_object_when_action_selected")
            )
        ),
    )


def _output_channel_contract_from_capabilities(
    capabilities: dict[str, Any] | None,
    *,
    phase: str = "initial_decision",
    allowed_action_types: tuple[str, ...] = (),
) -> SingleAgentOutputChannelContract:
    payload = dict(capabilities or {})
    action_required = bool(payload.get("requires_json_action_protocol") is True)
    assistant_response_allowed = "respond" in {str(item) for item in tuple(allowed_action_types or ()) if str(item)}
    return _single_agent_output_channel_contract(
        phase=phase,
        action_transport_required=action_required,
        provider_json_object_required=bool(action_required and not assistant_response_allowed),
        raw_assistant_text_allowed=bool(action_required and assistant_response_allowed) if action_required else None,
    )


def _action_output_channel_contract(
    phase: str = "action_decision",
    *,
    assistant_response_allowed: bool = True,
) -> SingleAgentOutputChannelContract:
    return _single_agent_output_channel_contract(
        action_transport_required=True,
        phase=phase,
        provider_json_object_required=not bool(assistant_response_allowed),
        raw_assistant_text_allowed=bool(assistant_response_allowed),
    )


def _assistant_message_or_action_output_channel_contract(phase: str = "assistant_message_or_action_decision") -> SingleAgentOutputChannelContract:
    return _single_agent_output_channel_contract(
        action_transport_required=False,
        phase=phase,
        direct_visible_text_stream_allowed=True,
        preferred_action_transport="assistant_message_or_json_action_object",
        fallback_action_transport="assistant_message",
    )


def _output_channel_allows_direct_visible_text(contract: SingleAgentOutputChannelContract | None) -> bool:
    payload = contract or _single_agent_output_channel_contract(action_transport_required=False)
    return (
        str(payload.visible_body_source or "") == "assistant_text"
        and not payload.action_transport_required
        and bool(payload.direct_visible_text_stream_allowed)
    )


def _output_channel_requires_action(contract: SingleAgentOutputChannelContract | None) -> bool:
    payload = contract or _single_agent_output_channel_contract(action_transport_required=False)
    return bool(payload.action_transport_required)


@dataclass(frozen=True, slots=True)
class SingleAgentActionParse:
    action_request: ModelActionRequest | None
    native_tool_calls: list[dict[str, Any]]
    error: dict[str, Any] | None = None
    tool_actions: tuple[ModelActionRequest, ...] = ()
    control_action: ModelActionRequest | None = None
    assistant_final_text: str = ""
    agent_public_feedback_note: str = ""


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
    apply_task_recovery_resume: ApplyTaskRecoveryResume | None = None,
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
            _ensure_turn_memory_started(
                runtime_host,
                session_id=session_id,
                turn_id=turn_id,
                turn_run_id=turn_run.turn_run_id if turn_run is not None else "",
                branch_id=str(runtime_branch.get("branch_id") or runtime_branch.get("branch") or session_id),
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
        _patch_turn_memory(
            runtime_host,
            session_id=session_id,
            turn_id=turn_id,
            current_user_message_ref=str(compilation.packet.packet_id),
            current_append_hash=stable_text_hash(user_message),
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
        initial_output_contract = _output_channel_contract_from_capabilities(
            dict(compilation.packet.diagnostics.get("control_capabilities") or {}),
            phase="initial_decision",
            allowed_action_types=tuple(compilation.packet.allowed_action_types),
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
        model_messages = _copy_model_messages_without_rewriting(list(compilation.packet.model_messages))
        provider_protocol_messages_to_append: list[dict[str, Any]] = []
        assistant_stream_normalizer: AssistantStreamNormalizer | None = None
        assistant_visible_stream_continuity = {}
        current_packet_ref = str(compilation.packet.packet_id)
        current_allowed_action_types = tuple(compilation.packet.allowed_action_types)
        current_available_tools = tuple(compilation.packet.available_tools or ())
        current_tool_call_contract = _tool_call_contract_from_packet(compilation.packet)
        current_output_contract = initial_output_contract
        protocol_recovery_attempts = 0
        latest_protocol_error: dict[str, Any] = {}
        latest_protocol_control_signal: dict[str, Any] = {}
        tool_observation_payloads: list[dict[str, Any]] = []
        tool_context_ledger_entries: list[dict[str, Any]] = []
        model_messages_segment_plan = dict(compilation.packet.segment_plan or {})
        provider_visible_followup_ledger = _provider_visible_followup_ledger_kwargs(
            compiler=compiler,
            session_id=session_id,
            model_selection=dict(model_selection or {}),
        )
        provider_cache_scope_id = _provider_cache_scope_id_for_turn(
            session_id=session_id,
            session_context=session_context,
        )
        reasoning_projection_public_visible = _turn_reasoning_projection_public_enabled(runtime_assembly)

        def current_native_tools_transport() -> list[dict[str, Any]]:
            return _native_tools_for_packet(
                current_allowed_action_types,
                available_tools=current_available_tools,
                tool_call_contract=current_tool_call_contract,
            )

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
            sanitized_steer_messages = _sanitize_model_messages(
                [dict(batch.model_message)],
                turn_id=turn_id,
                source=f"{source}.new_append",
            )
            model_messages = _append_messages_to_accumulated_context(
                model_messages,
                sanitized_steer_messages,
                segment_plan=model_messages_segment_plan,
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
            reasoning_content: str = "",
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
            reasoning_projection = (
                _reasoning_projection_status_event(
                    reasoning_content,
                    turn_id=turn_id,
                    turn_run_id=turn_run.turn_run_id if turn_run is not None else "",
                    task_run_id=str(dict(active_work_payload or {}).get("task_run_id") or ""),
                    answer_channel=decision.answer_channel,
                    answer_source=decision.answer_source,
                )
                if _turn_reasoning_projection_public_enabled(runtime_assembly)
                else {}
            )
            if reasoning_projection:
                yield reasoning_projection
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
            closeout_model_error: dict[str, Any] = {}
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
                closeout_messages, closeout_segment_plan = _single_agent_turn_followup_prompt_payload(
                    base_segment_plan=dict(model_messages_segment_plan or {}),
                    model_messages=closeout_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + attempt,
                    **provider_visible_followup_ledger,
                )
                closeout_response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=closeout_messages,
                    model_selection=_model_selection_for_native_tool_protocol(dict(model_selection or {})),
                    accounting_context={
                        "request_id": f"providerreq:{current_packet_ref}:agent-closeout:{phase}:{attempt}",
                        "session_id": session_id,
                        "provider_cache_scope_id": provider_cache_scope_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": _AGENT_CLOSEOUT_SOURCE,
                        "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
                        "segment_plan": closeout_segment_plan,
                        "provider_visible_physical_context": True,
                        "reasoning_projection_public_visible": reasoning_projection_public_visible,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_agent_authored_closeout",
                            "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
                            "closeout_phase": phase,
                            "closeout_reason": reason,
                            "attempt": attempt,
                            "segment_plan_ref": str(closeout_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=[],
                    allow_assistant_text_delta=False,
                    output_contract=_assistant_message_or_action_output_channel_contract(phase=f"closeout_decision:{phase}"),
                ):
                    if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                        closeout_response = model_event.get("response")
                        assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                        continue
                    capture_assistant_stream_event(model_event)
                    yield model_event
                if isinstance(closeout_response, dict) and closeout_response.get("type") == "error":
                    closeout_model_error = dict(closeout_response)
                    previous_invalid_response = json.dumps(
                        {"closeout_model_error": _runtime_error_payload(closeout_response)},
                        ensure_ascii=False,
                        sort_keys=True,
                    )[:1200]
                    break
                closeout_content, closeout_parse_issue = _agent_authored_closeout_content_from_response(
                    closeout_response,
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    closeout_attempt=attempt,
                    phase=phase,
                )
                if closeout_content is None:
                    previous_invalid_response = json.dumps(
                        closeout_parse_issue,
                        ensure_ascii=False,
                        sort_keys=True,
                    )[:1200]
                    continue
                answer_channel = "conversation"
                terminal_status = "completed"
                content = closeout_content.content
                answer_channel = closeout_content.answer_channel
                terminal_status = closeout_content.terminal_status
                decision = canonical_output_decision_for_final_text(
                    content,
                    answer_channel=answer_channel,
                    answer_source=_AGENT_CLOSEOUT_SOURCE,
                    execution_posture="single_agent_turn",
                    terminal_reason=terminal_reason,
                    has_tool_receipt=bool(provider_protocol_messages_to_append),
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
                        provider_protocol_messages_to_append=[
                            *provider_protocol_messages_to_append,
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
                        reasoning_content=_reasoning_content_from_response(closeout_response),
                    ):
                        yield event
                    return
                previous_invalid_response = content[:1200]
            feedback_protocol_error = dict(protocol_error or latest_protocol_error or {})
            feedback_control_signal = dict(control_signal or latest_protocol_control_signal or {})
            contract_feedback = _agent_contract_feedback_required_lifecycle(
                reason=reason,
                phase=phase,
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                control_signal=feedback_control_signal,
                protocol_error=feedback_protocol_error,
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
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status="failed",
                    terminal_reason="agent_contract_feedback_required",
                    payload=terminal_payload_with_stream_continuity(
                        {
                            "completion_state": "agent_contract_feedback_required",
                            "agent_closeout_attempts": 2,
                            "agent_contract_feedback": contract_feedback,
                            "agent_authored_closeout_missing": True,
                            **({"closeout_model_error": closeout_model_error} if closeout_model_error else {}),
                            **({"runtime_control_signal": feedback_control_signal} if feedback_control_signal else {}),
                            **({"protocol_error": feedback_protocol_error} if feedback_protocol_error else {}),
                        }
                    ),
                )
                terminal_recorded = True
                yield {"type": "agent_turn_terminal", "event": terminal}

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
                allowed_action_types=current_allowed_action_types,
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

        response = None
        async for model_event in _invoke_single_turn_model_with_stream_events(
            model_runtime=model_runtime,
            model_messages=model_messages,
            model_selection=dict(model_selection or {}),
            accounting_context={
                "request_id": f"providerreq:{compilation.packet.packet_id}:1",
                "session_id": session_id,
                "provider_cache_scope_id": provider_cache_scope_id,
                "run_id": turn_run.turn_run_id if turn_run is not None else "",
                "turn_id": turn_id,
                "packet_ref": compilation.packet.packet_id,
                "source": "harness.single_agent_turn",
                "provider_lane": PROVIDER_LANE_AGENT_TOOL_LOOP,
                "segment_plan": dict(compilation.packet.segment_plan or {}),
                "provider_visible_physical_context": True,
                "reasoning_projection_public_visible": reasoning_projection_public_visible,
                "prompt_manifest": {
                    **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                    "provider_lane": PROVIDER_LANE_AGENT_TOOL_LOOP,
                },
            },
            native_tools=current_native_tools_transport(),
            allow_assistant_text_delta=_output_channel_allows_direct_visible_text(initial_output_contract),
            output_contract=initial_output_contract,
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
                current_output_contract = _action_output_channel_contract(
                    phase="active_turn_steer_decision",
                    assistant_response_allowed="respond" in set(current_allowed_action_types or ()),
                )
                model_messages, steer_segment_plan = _single_agent_turn_followup_prompt_payload(
                    base_segment_plan=dict(model_messages_segment_plan or {}),
                    model_messages=model_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + 1,
                    **provider_visible_followup_ledger,
                )
                model_messages_segment_plan = dict(steer_segment_plan or {})
                response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": f"providerreq:{current_packet_ref}:active-turn-steer:{tool_iteration + 1}",
                        "session_id": session_id,
                        "provider_cache_scope_id": provider_cache_scope_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.active_turn_steer",
                        "provider_lane": PROVIDER_LANE_AGENT_TOOL_LOOP,
                        "segment_plan": steer_segment_plan,
                        "provider_visible_physical_context": True,
                        "reasoning_projection_public_visible": reasoning_projection_public_visible,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_active_turn_steer",
                            "provider_lane": PROVIDER_LANE_AGENT_TOOL_LOOP,
                            "steer_phase": "before_model_action",
                            "queued_user_steer_count": len(active_turn_steer_batch.items),
                            "segment_plan_ref": str(steer_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=current_native_tools_transport(),
                    allow_assistant_text_delta=False,
                    output_contract=current_output_contract,
                ):
                    if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                        response = model_event.get("response")
                        assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                        continue
                    capture_assistant_stream_event(model_event)
                    yield model_event
                continue
            public_feedback_recommended = _tool_followup_public_feedback_recommended(
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
                output_contract=current_output_contract,
                allow_model_tool_calls=_model_tool_calls_allowed_for_packet(
                    current_allowed_action_types,
                    available_tools=current_available_tools,
                    tool_call_contract=current_tool_call_contract,
                ),
                public_feedback_expected=public_feedback_recommended,
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
                    public_feedback_recommended=public_feedback_recommended,
                    response_preview=stringify_content(getattr(response, "content", response)),
                )
                latest_protocol_error = dict(action_parse.error or {})
                latest_protocol_control_signal = dict(protocol_control_signal or {})
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
                current_output_contract = _action_output_channel_contract(
                    phase="runtime_recovery_decision",
                    assistant_response_allowed="respond" in set(current_allowed_action_types or ()),
                )
                model_messages, recovery_segment_plan = _single_agent_turn_followup_prompt_payload(
                    base_segment_plan=dict(model_messages_segment_plan or {}),
                    model_messages=model_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + 1,
                    **provider_visible_followup_ledger,
                )
                model_messages_segment_plan = dict(recovery_segment_plan or {})
                response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": (
                            f"providerreq:{current_packet_ref}:contract-observation:{tool_iteration + 1}:{protocol_recovery_attempts}"
                            if recovery_exhausted
                            else f"providerreq:{current_packet_ref}:runtime-control-recovery:{tool_iteration + 1}:{protocol_recovery_attempts}"
                        ),
                        "session_id": session_id,
                        "provider_cache_scope_id": provider_cache_scope_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": (
                            "harness.single_agent_turn.contract_observation"
                            if recovery_exhausted
                            else "harness.single_agent_turn.runtime_control_signal_recovery"
                        ),
                        "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
                        "segment_plan": recovery_segment_plan,
                        "provider_visible_physical_context": True,
                        "reasoning_projection_public_visible": reasoning_projection_public_visible,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": (
                                "single_agent_turn_contract_observation_decision"
                                if recovery_exhausted
                                else "single_agent_turn_runtime_control_signal_recovery"
                            ),
                            "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
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
                    output_contract=current_output_contract,
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
            tool_iteration += 1
            for feedback_event in _record_model_action_public_feedback_events(
                runtime_host,
                turn_run=turn_run,
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                phase="tool_loop",
                tool_iteration=tool_iteration,
                action_parse=action_parse,
                tool_actions=tool_actions,
            ):
                yield feedback_event
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
                provider_protocol_messages_to_append.extend([assistant_protocol_message, *tool_protocol_messages])
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
            model_messages = _append_tool_transcript_to_accumulated_context(
                model_messages,
                _copy_model_messages_without_rewriting(new_tool_transcript_messages),
                segment_plan=model_messages_segment_plan,
            )
            if assistant_tool_calls:
                round_tool_context_entries = _append_tool_context_ledger_entries(
                    tool_context_ledger_entries,
                    tool_iteration=tool_iteration,
                    assistant_model_message_index=tool_context_assistant_message_index,
                    tool_calls=assistant_tool_calls,
                    observations=round_observation_payloads,
                )
            if assistant_tool_calls or round_observation_payloads:
                _record_turn_memory_tool_round(
                    runtime_host,
                    session_id=session_id,
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    tool_batch_ref=batch_plan.batch_id,
                    tool_iteration=tool_iteration,
                    tool_calls=assistant_tool_calls,
                    observations=round_observation_payloads,
                    tool_context_entries=round_tool_context_entries,
                )
            evidence_alignment_enabled = _runtime_system_group_enabled(
                runtime_assembly,
                "evidence_alignment",
                default=True,
            )
            evidence_delta_summary = (
                build_tool_followup_evidence_delta_summary(
                    current_observations=round_observation_payloads,
                    accumulated_observations=tool_observation_payloads,
                    tool_iteration=tool_iteration,
                )
                if evidence_alignment_enabled
                else {}
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
            model_messages, followup_segment_plan, followup_prompt_manifest, followup_packet_ref = _single_agent_turn_followup_prompt_context(
                compilation=compilation,
                model_messages=model_messages,
                base_segment_plan=model_messages_segment_plan,
                packet_id=current_packet_ref,
                tool_iteration=tool_iteration,
                **provider_visible_followup_ledger,
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
                followup_compilation = compiler.compile_single_agent_turn_packet(
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
                model_messages = _copy_model_messages_without_rewriting(list(followup_compilation.packet.model_messages))
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
                current_tool_call_contract = _tool_call_contract_from_packet(followup_compilation.packet)
                current_output_contract = _output_channel_contract_from_capabilities(
                    dict(followup_compilation.packet.diagnostics.get("control_capabilities") or {}),
                    phase="tool_followup_decision",
                    allowed_action_types=tuple(followup_compilation.packet.allowed_action_types),
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
                            "strategy": str(compaction_payload.get("strategy") or "single_agent_turn_context_recompile"),
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
                model_messages, followup_segment_plan, followup_prompt_manifest, followup_packet_ref = _single_agent_turn_followup_prompt_context(
                    compilation=compilation,
                    model_messages=model_messages,
                    base_segment_plan=model_messages_segment_plan,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration,
                    **provider_visible_followup_ledger,
                )
                model_messages_segment_plan = dict(followup_segment_plan or {})
                followup_prompt_manifest = {
                    **dict(followup_prompt_manifest or {}),
                    "active_turn_user_steer_included": True,
                    "queued_user_steer_count": len(active_turn_steer_batch.items),
                }
            followup_accumulated_messages, _previous_dynamic_tail_messages = _tool_followup_context_layers(
                [dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
                segment_plan=model_messages_segment_plan,
            )
            followup_context_messages = [dict(item) for item in list(followup_accumulated_messages or []) if isinstance(item, dict)]
            followup_invocation_messages = [dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)]
            if _tool_followup_requires_action_transport(current_allowed_action_types):
                followup_context_messages = [
                    dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)
                ]
                followup_context_messages = _append_tool_followup_context_boundary(
                    followup_context_messages,
                    tool_iteration=tool_iteration,
                    turn_id=turn_id,
                )
                current_output_contract = _action_output_channel_contract(
                    phase="tool_followup_decision",
                    assistant_response_allowed="respond" in set(current_allowed_action_types or ()),
                )
                followup_invocation_messages = _tool_followup_action_contract_messages(
                    [dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)],
                    turn_id=turn_id,
                    allowed_action_types=current_allowed_action_types,
                    tool_iteration=tool_iteration,
                    output_contract=current_output_contract,
                    evidence_delta_summary=evidence_delta_summary,
                )
                followup_prompt_manifest = {
                    **dict(followup_prompt_manifest or {}),
                    "tool_followup_action_guidance": True,
                    "evidence_alignment_system_group_enabled": evidence_alignment_enabled,
                    "evidence_delta_summary_included": bool(evidence_delta_summary),
                    "assistant_body_form": "action_object_with_final_answer_for_respond",
                    "control_action_submission": "provider_tool_selection_when_available",
                    "output_channel_contract": current_output_contract.to_dict(),
                    "natural_response_terminal_when_no_action": False,
                    "synthetic_incremental_context_frame": "omitted_from_provider_visible_messages",
                    "synthetic_incremental_context_frame_reason": (
                        "deepseek_prefix_cache_does_not_reliably_extend_after_mid_transcript_system_frames"
                    ),
                }
            else:
                followup_context_messages = _append_tool_followup_context_boundary(
                    followup_context_messages,
                    tool_iteration=tool_iteration,
                    turn_id=turn_id,
                )
                followup_invocation_messages = [
                    *[dict(item) for item in list(followup_context_messages or []) if isinstance(item, dict)],
                ]
            followup_invocation_messages, followup_segment_plan = _single_agent_turn_followup_prompt_payload(
                base_segment_plan=dict(followup_segment_plan or {}),
                model_messages=followup_invocation_messages,
                packet_id=str(followup_packet_ref or current_packet_ref),
                tool_iteration=tool_iteration,
                **provider_visible_followup_ledger,
            )
            model_messages_segment_plan = dict(followup_segment_plan or {})
            followup_prompt_manifest = {
                **dict(followup_prompt_manifest or {}),
                "segment_plan_ref": str(followup_segment_plan.get("segment_plan_id") or ""),
                "provider_lane": PROVIDER_LANE_AGENT_TOOL_LOOP,
                "physical_context_assembly": "physical_prefix_frame_then_current_append_then_dynamic_tail",
                "physical_message_order": "physical_context_assembler",
            }
            response = None
            async for model_event in _invoke_single_turn_model_with_stream_events(
                model_runtime=model_runtime,
                model_messages=followup_invocation_messages,
                model_selection=dict(model_selection or {}),
                accounting_context={
                    "request_id": f"providerreq:{followup_packet_ref}:tool-followup:{tool_iteration}",
                    "session_id": session_id,
                    "provider_cache_scope_id": provider_cache_scope_id,
                    "run_id": turn_run.turn_run_id if turn_run is not None else "",
                    "turn_id": turn_id,
                    "packet_ref": followup_packet_ref,
                    "source": "harness.single_agent_turn.tool_followup",
                    "provider_lane": PROVIDER_LANE_AGENT_TOOL_LOOP,
                    "segment_plan": followup_segment_plan,
                    "provider_visible_physical_context": True,
                    "provider_visible_append_ledger_storage_root": str(provider_visible_followup_ledger.get("storage_root") or ""),
                    "provider_visible_append_scope": str(provider_visible_followup_ledger.get("provider_visible_append_scope") or ""),
                    "reasoning_projection_public_visible": reasoning_projection_public_visible,
                    "prompt_manifest": followup_prompt_manifest,
                },
                native_tools=current_native_tools_transport(),
                allow_assistant_text_delta=False,
                output_contract=current_output_contract,
            ):
                if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                    response = model_event.get("response")
                    assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                    continue
                capture_assistant_stream_event(model_event)
                yield model_event
            model_messages = _copy_model_messages_without_rewriting(followup_invocation_messages)
        if isinstance(response, dict) and response.get("type") == "error":
            terminal_reason = str(response.get("code") or "single_agent_turn_failed")
            control_signal = _model_invocation_failure_closeout_control_signal(
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                phase="model_invocation",
                response=dict(response),
                recent_observations=tool_observation_payloads,
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
                reason=terminal_reason,
                phase="model_invocation_failed",
                terminal_reason=terminal_reason,
                control_signal=control_signal,
                completion_state="model_invocation_failed",
            ):
                yield event
            terminal_recorded = True
            return
        if response is None:
            terminal_reason = "single_agent_turn_model_response_missing"
            control_signal = _model_invocation_failure_closeout_control_signal(
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                phase="model_invocation",
                response={
                    "type": "error",
                    "code": terminal_reason,
                    "reason": "model invocation completed without a response payload",
                    "retryable": True,
                },
                recent_observations=tool_observation_payloads,
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
                reason=terminal_reason,
                phase="model_invocation_missing_response",
                terminal_reason=terminal_reason,
                control_signal=control_signal,
                completion_state="model_invocation_missing_response",
            ):
                yield event
            terminal_recorded = True
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
                    output_contract=current_output_contract,
                    allow_model_tool_calls=_model_tool_calls_allowed_for_packet(
                        current_allowed_action_types,
                        available_tools=current_available_tools,
                        tool_call_contract=current_tool_call_contract,
                    ),
                    public_feedback_recommended=False,
                )
                if not action_parse.error:
                    break
                protocol_recovery_attempts += 1
                protocol_control_signal = _model_protocol_violation_control_signal(
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    phase="final",
                    protocol_error=dict(action_parse.error or {}),
                    allowed_action_types=current_allowed_action_types,
                    recovery_attempt=protocol_recovery_attempts,
                    max_recovery_attempts=_MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS,
                    public_feedback_recommended=False,
                    response_preview=stringify_content(getattr(response, "content", response)),
                )
                latest_protocol_error = dict(action_parse.error or {})
                latest_protocol_control_signal = dict(protocol_control_signal or {})
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
                    allowed_action_types=current_allowed_action_types,
                    recovery_exhausted=recovery_exhausted,
                )
                current_output_contract = _action_output_channel_contract(
                    phase="runtime_recovery_decision",
                    assistant_response_allowed="respond" in set(current_allowed_action_types or ()),
                )
                model_messages, recovery_segment_plan = _single_agent_turn_followup_prompt_payload(
                    base_segment_plan=dict(model_messages_segment_plan or {}),
                    model_messages=model_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + 1,
                    **provider_visible_followup_ledger,
                )
                model_messages_segment_plan = dict(recovery_segment_plan or {})
                response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": (
                            f"providerreq:{current_packet_ref}:final-contract-observation:{protocol_recovery_attempts}"
                            if recovery_exhausted
                            else f"providerreq:{current_packet_ref}:final-runtime-control-recovery:{protocol_recovery_attempts}"
                        ),
                        "session_id": session_id,
                        "provider_cache_scope_id": provider_cache_scope_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": (
                            "harness.single_agent_turn.contract_observation"
                            if recovery_exhausted
                            else "harness.single_agent_turn.runtime_control_signal_recovery"
                        ),
                        "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
                        "segment_plan": recovery_segment_plan,
                        "provider_visible_physical_context": True,
                        "reasoning_projection_public_visible": reasoning_projection_public_visible,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": (
                                "single_agent_turn_contract_observation_decision"
                                if recovery_exhausted
                                else "single_agent_turn_runtime_control_signal_recovery"
                            ),
                            "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
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
                    output_contract=current_output_contract,
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
            for feedback_event in _record_model_action_public_feedback_events(
                runtime_host,
                turn_run=turn_run,
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                phase="final",
                tool_iteration=tool_iteration + 1,
                action_parse=action_parse,
                tool_actions=(action_request,),
            ):
                yield feedback_event
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
                        "request_id": f"providerreq:{current_packet_ref}:final-admission-repair",
                        "session_id": session_id,
                        "provider_cache_scope_id": provider_cache_scope_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.admission_repair",
                        "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
                        "segment_plan": dict(model_messages_segment_plan or {}),
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
                        },
                        "provider_visible_append_ledger_storage_root": str(provider_visible_followup_ledger.get("storage_root") or ""),
                        "provider_visible_append_scope": str(provider_visible_followup_ledger.get("provider_visible_append_scope") or ""),
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
                    for feedback_event in _record_model_action_public_feedback_events(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        packet_ref=current_packet_ref,
                        phase="final_admission_repair",
                        tool_iteration=tool_iteration + 1,
                        action_parse=action_parse,
                        tool_actions=(action_request,),
                    ):
                        yield feedback_event
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
                    provider_protocol_messages_to_append=_final_provider_protocol_messages_to_append(
                        provider_protocol_messages_to_append,
                        turn_id=turn_id,
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
                    reasoning_content=_reasoning_content_from_response(response),
                ):
                    yield event
                return
            if action_request.action_type == "request_task_run":
                request_task_terminal_reason = "task_resource_allocated"
                request_task_terminal_status = "completed"
                lifecycle_public_terminal_events: list[dict[str, Any]] = []
                start_context_handoff = build_turn_to_task_context_handoff_seed(
                    runtime_host=runtime_host,
                    session_id=session_id,
                    turn_id=turn_id,
                    source_packet_ref=current_packet_ref,
                    tool_observation_payloads=tool_observation_payloads,
                    turn_run_id=turn_run.turn_run_id if turn_run is not None else "",
                    stream_run_id=stream_run_id,
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
                    provider_protocol_messages_to_append=_final_provider_protocol_messages_to_append(
                        provider_protocol_messages_to_append,
                        turn_id=turn_id,
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
                    reasoning_content=_reasoning_content_from_response(response),
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
                    provider_protocol_messages_to_append=_final_provider_protocol_messages_to_append(
                        provider_protocol_messages_to_append,
                        turn_id=turn_id,
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
                    reasoning_content=_reasoning_content_from_response(response),
                ):
                    yield event
                return
            if action_request.action_type == "resume_task_recovery":
                if apply_task_recovery_resume is None:
                    async for event in emit_agent_authored_closeout(
                        reason="task_recovery_resume_executor_missing",
                        phase="task_recovery_resume_executor_missing",
                        terminal_reason="task_recovery_resume_executor_missing",
                        protocol_error=_single_agent_protocol_error(
                            code="task_recovery_resume_executor_missing",
                            reason="single_agent_turn_missing_task_recovery_resume_callback",
                            diagnostics={"action_request": action_request.to_dict()},
                        ),
                    ):
                        yield event
                    terminal_recorded = True
                    return
                terminal_reason = "task_recovery_resume"
                terminal_status = "completed"
                buffered_resume_events: list[dict[str, Any]] = []
                async for event in apply_task_recovery_resume(action_request):
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
            provider_protocol_messages_to_append=[
                *provider_protocol_messages_to_append,
                _assistant_final_protocol_message(response, turn_id=turn_id, include_reasoning=True),
            ]
            if provider_protocol_messages_to_append
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
            has_tool_receipt=bool(provider_protocol_messages_to_append),
            terminal_status="completed",
            terminal_reason="assistant_message",
            final_extra={"runtime_branch": dict(runtime_branch or {})},
            commit_decision=commit_decision,
            reasoning_content=_reasoning_content_from_response(response),
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


def _uses_provider_visible_physical_context(accounting_context: dict[str, Any] | None) -> bool:
    return bool(dict(accounting_context or {}).get("provider_visible_physical_context") is True)


async def _invoke_single_turn_model(
    *,
    model_runtime: Any,
    model_messages: list[dict[str, Any]],
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any],
    native_tools: list[dict[str, Any]],
    output_contract: SingleAgentOutputChannelContract | None = None,
) -> Any:
    channel_contract = output_contract or _single_agent_output_channel_contract(action_transport_required=False)
    if channel_contract.provider_json_object_required:
        if native_tools:
            model_selection = _model_selection_for_native_tool_protocol(model_selection, native_tools=native_tools)
        else:
            model_selection = _model_selection_with_json_object_contract(model_selection)
    elif native_tools:
        model_selection = _model_selection_for_native_tool_protocol(model_selection, native_tools=native_tools)
    if _uses_provider_visible_physical_context(accounting_context):
        model_messages = _copy_model_messages_without_rewriting(model_messages)
    else:
        model_messages = _sanitize_model_messages(
            model_messages,
            turn_id=str(accounting_context.get("turn_id") or ""),
            source=str(accounting_context.get("source") or "harness.loop.single_agent_turn.invoke"),
        )
    _assert_model_messages_match_segment_plan(
        model_messages,
        accounting_context=accounting_context,
        source="harness.loop.single_agent_turn.invoke",
    )
    tool_invoker = getattr(model_runtime, "invoke_messages_with_tools", None)
    plain_invoker = getattr(model_runtime, "invoke_messages", None)
    if native_tools and callable(tool_invoker):
        try:
            tool_call_options = _round_tool_call_options_for_native_tools(
                native_tools,
                output_contract=channel_contract,
            )
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


def _model_selection_for_native_tool_protocol(
    model_selection: dict[str, Any],
    *,
    native_tools: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    selection = dict(model_selection or {})
    selection.pop("structured_output", None)
    selection.pop("response_format", None)
    if _native_tools_include_strict(native_tools):
        provider_extensions = dict(selection.get("provider_extensions") or {})
        provider_extensions["strict_tool_schema"] = True
        selection["provider_extensions"] = provider_extensions
    return selection


def _native_tools_include_strict(native_tools: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> bool:
    return any(bool(dict(item or {}).get("strict") is True) for item in tuple(native_tools or ()))


def _round_tool_call_options_for_native_tools(
    native_tools: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    output_contract: SingleAgentOutputChannelContract | None = None,
):
    max_tool_calls = 1 if _native_tools_include_strict(native_tools) else len(list(native_tools or []))
    tool_choice = (
        "required"
        if _output_channel_requires_action(output_contract)
        and not bool(getattr(output_contract, "raw_assistant_text_allowed", False))
        else None
    )
    return build_round_tool_call_options(max_tool_calls=max_tool_calls, tool_choice=tool_choice)


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
    output_contract: SingleAgentOutputChannelContract | None = None,
) -> AsyncIterator[dict[str, Any]]:
    channel_contract = output_contract or _single_agent_output_channel_contract(action_transport_required=False)
    if channel_contract.provider_json_object_required:
        if native_tools:
            model_selection = _model_selection_for_native_tool_protocol(model_selection, native_tools=native_tools)
        else:
            model_selection = _model_selection_with_json_object_contract(model_selection)
    elif native_tools:
        model_selection = _model_selection_for_native_tool_protocol(model_selection, native_tools=native_tools)
    stream_policy = dict(dict(model_selection or {}).get("stream_policy") or {})
    stream_enabled = bool(stream_policy.get("enabled") is True)
    if not stream_enabled:
        response = await _invoke_single_turn_model(
            model_runtime=model_runtime,
            model_messages=model_messages,
            model_selection=model_selection,
            accounting_context=accounting_context,
            native_tools=native_tools,
            output_contract=channel_contract,
        )
        yield {"type": _INTERNAL_MODEL_RESPONSE_EVENT, "response": response, "assistant_stream_normalizer": None}
        return

    if _uses_provider_visible_physical_context(accounting_context):
        model_messages = _copy_model_messages_without_rewriting(model_messages)
    else:
        model_messages = _sanitize_model_messages(
            model_messages,
            turn_id=str(accounting_context.get("turn_id") or ""),
            source=str(accounting_context.get("source") or "harness.loop.single_agent_turn.invoke_stream"),
        )
    _assert_model_messages_match_segment_plan(
        model_messages,
        accounting_context=accounting_context,
        source="harness.loop.single_agent_turn.invoke_stream",
    )
    tool_streamer = getattr(model_runtime, "astream_messages_with_tools", None)
    plain_streamer = getattr(model_runtime, "astream_messages", None)
    emit_assistant_text_delta = (
        bool(stream_policy.get("emit_assistant_text_delta", True) is not False)
        and bool(allow_assistant_text_delta)
        and _output_channel_allows_direct_visible_text(channel_contract)
        and not native_tools
    )
    stream_ref = str(accounting_context.get("request_id") or "")
    reasoning_projection_public_visible = bool(accounting_context.get("reasoning_projection_public_visible") is True)
    reasoning_projection_last_content = ""
    reasoning_projection_last_emit_at = 0.0

    def live_reasoning_projection_event(response: Any, *, phase: str, state: str) -> dict[str, Any]:
        nonlocal reasoning_projection_last_content, reasoning_projection_last_emit_at
        if not reasoning_projection_public_visible:
            return {}
        reasoning_content = _reasoning_content_from_response(response)
        if not reasoning_content or reasoning_content == reasoning_projection_last_content:
            return {}
        now = time.monotonic()
        if reasoning_projection_last_content:
            char_delta = abs(len(reasoning_content) - len(reasoning_projection_last_content))
            if (
                now - reasoning_projection_last_emit_at < _REASONING_STATUS_MIN_INTERVAL_SECONDS
                and char_delta < _REASONING_STATUS_MIN_CHAR_DELTA
            ):
                return {}
        reasoning_projection_last_content = reasoning_content
        reasoning_projection_last_emit_at = now
        return _reasoning_projection_status_event(
            reasoning_content,
            turn_id=str(accounting_context.get("turn_id") or ""),
            turn_run_id=str(accounting_context.get("run_id") or accounting_context.get("turn_run_id") or ""),
            task_run_id=str(accounting_context.get("task_run_id") or ""),
            answer_channel="runtime",
            answer_source=str(accounting_context.get("source") or "harness.single_agent_turn"),
            phase=phase,
            state=state,
            provider_request_id=stream_ref,
        )

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
            tool_call_options = _round_tool_call_options_for_native_tools(
                native_tools,
                output_contract=channel_contract,
            )
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
                reasoning_event = live_reasoning_projection_event(aggregated_response, phase="model_stream", state="running")
                if reasoning_event:
                    yield reasoning_event
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
                reasoning_event = live_reasoning_projection_event(aggregated_response, phase="model_stream", state="running")
                if reasoning_event:
                    yield reasoning_event
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
                output_contract=channel_contract,
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
            require_json_action=channel_contract.action_transport_required,
            error=exc,
        ):
            if assistant_normalizer is not None:
                for frame_event in assistant_normalizer.flush():
                    yield frame_event
            recovery_context = {
                **dict(accounting_context or {}),
                "request_id": f"{stream_ref}:partial-stream-recovery",
                "source": _PARTIAL_STREAM_RECOVERY_SOURCE,
                "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
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
                            "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
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
                            "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
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
    if raw_content.strip():
        response_content = stringify_content(getattr(response, "content", response)).strip()
        if not response_content:
            response = SimpleNamespace(content=raw_content)
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
        reasoning_content = _reasoning_content_from_response(current) + _reasoning_content_from_response(chunk)
        additional_kwargs = {}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content
        raw_tool_call_chunks = [
            *list(getattr(current, "raw_tool_call_chunks", []) or []),
            *list(getattr(chunk, "raw_tool_call_chunks", []) or []),
        ]
        return SimpleNamespace(
            content=current_text + chunk_text,
            additional_kwargs=additional_kwargs,
            raw_tool_call_chunks=raw_tool_call_chunks,
            tool_calls=[
                *list(getattr(current, "tool_calls", []) or []),
                *list(getattr(chunk, "tool_calls", []) or []),
            ],
            raw_response=dict(getattr(chunk, "raw_response", None) or getattr(current, "raw_response", None) or {}),
        )


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
    repair_messages, repair_segment_plan = _single_agent_turn_followup_prompt_payload(
        base_segment_plan=dict(dict(accounting_context or {}).get("segment_plan") or {}),
        model_messages=repair_messages,
        packet_id=packet_ref,
        tool_iteration=iteration + 1,
        **_provider_visible_followup_ledger_kwargs_from_accounting(
            accounting_context,
            model_selection=dict(model_selection or {}),
        ),
    )
    repair_output_contract = _action_output_channel_contract(
        phase="admission_repair_decision",
        assistant_response_allowed="respond" in set(allowed_action_types or ()),
    )
    repair_response = await _invoke_single_turn_model(
        model_runtime=model_runtime,
        model_messages=repair_messages,
        model_selection=dict(model_selection or {}),
        accounting_context={
            **dict(accounting_context or {}),
            "request_id": request_id,
            "source": "harness.single_agent_turn.admission_repair",
            "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
            "segment_plan": repair_segment_plan,
            "provider_visible_physical_context": True,
            "prompt_manifest": {
                **dict(dict(accounting_context or {}).get("prompt_manifest") or {}),
                "invocation_kind": "single_agent_turn_admission_repair",
                "provider_lane": PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
                "repair_phase": phase,
                "original_admission_decision": admission.decision,
                "original_admission_reason": admission.system_reason,
                "segment_plan_ref": str(repair_segment_plan.get("segment_plan_id") or ""),
            },
        },
        native_tools=[],
        output_contract=repair_output_contract,
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
        output_contract=repair_output_contract,
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
        "上一轮未被接受的动作与当前可用动作：\n"
        f"{json.dumps(repair_payload, ensure_ascii=False, sort_keys=True)}"
    )
    return _append_model_messages_without_rewriting_context(
        model_messages,
        [{"role": "user", "content": repair_instruction, "turn_id": turn_id}],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.admission_repair",
    )


def _plain_assistant_text_is_allowed_response(
    assistant_text: str,
    *,
    allowed_action_types: tuple[str, ...],
    output_contract: SingleAgentOutputChannelContract | None = None,
) -> bool:
    if not str(assistant_text or "").strip():
        return False
    if "respond" not in {str(item) for item in tuple(allowed_action_types or ()) if str(item)}:
        return False
    contract = output_contract or _single_agent_output_channel_contract(action_transport_required=False)
    return bool(getattr(contract, "raw_assistant_text_allowed", False)) or _output_channel_allows_direct_visible_text(contract)


def _direct_visible_text_not_allowed_error(
    *,
    phase: str,
    assistant_text: str,
    output_contract: SingleAgentOutputChannelContract | None,
    allowed_action_types: tuple[str, ...],
    parse_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _single_agent_protocol_error(
        code="single_agent_turn_direct_visible_text_not_allowed",
        reason="direct_visible_text_not_allowed",
        diagnostics={
            "phase": phase,
            "allowed_action_types": list(allowed_action_types),
            "output_channel_contract": (
                output_contract.to_dict()
                if output_contract is not None
                else _single_agent_output_channel_contract(action_transport_required=False).to_dict()
            ),
            "parse_diagnostics": dict(parse_diagnostics or {}),
            "previous_response_preview": _compact_text(assistant_text, limit=600),
            "action_issue": _protocol_action_issue(
                category="protocol_violation",
                code="direct_visible_text_not_allowed",
                requested_action_type="respond",
                repair_instruction=(
                    "当前阶段没有开放直接回答通道。"
                    "如果需要工具、询问、阻塞或控制动作，请提交本轮允许的结构化动作；"
                    "如果要回答用户，需要在允许 respond 的阶段直接自然回复或提交 respond.final_answer。"
                ),
            ),
        },
    )


def _single_agent_action_request_from_response(
    response: Any,
    *,
    request_id: str,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...],
    phase: str,
    output_contract: SingleAgentOutputChannelContract | None = None,
    require_json_action: bool = False,
    allow_model_tool_calls: bool = False,
    public_feedback_expected: bool = False,
) -> SingleAgentActionParse:
    channel_contract = output_contract or _single_agent_output_channel_contract(
        action_transport_required=bool(require_json_action)
    )
    require_json_action = _output_channel_requires_action(channel_contract)
    protocol = model_response_protocol_from_response(
        response,
        request_id=request_id,
        turn_id=turn_id,
        require_json_action=require_json_action,
        allow_native_tool_calls=bool(allow_model_tool_calls),
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
    if json_action_like and _parse_diagnostics_contains_mixed_public_text_and_action_intent(protocol.parse_diagnostics):
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_mixed_public_text_and_action_intent_error(
                phase=phase,
                assistant_text=assistant_text,
                parse_diagnostics=dict(protocol.parse_diagnostics or {}),
                requested_action_type=str(json_payload.get("action_type") or ""),
            ),
        )
    if protocol.protocol_errors:
        protocol_error_code = str(protocol.protocol_errors[0] if protocol.protocol_errors else "model_protocol_error")
        detected_transport = _detected_json_action_transport_rejection(
            json_payload=json_payload,
            protocol_errors=protocol.protocol_errors,
        )
        detected_action = dict(detected_transport.get("detected_json_action") or {})
        requested_action_type = str(detected_action.get("action_type") or "").strip()
        if protocol_error_code == "native_tool_call_transport_not_available":
            requested_tool_name = next(
                (
                    str(call.get("name") or call.get("tool_name") or "").strip()
                    for call in native_tool_calls
                    if str(call.get("name") or call.get("tool_name") or "").strip()
                ),
                "",
            )
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=native_tool_calls,
                error=_single_agent_protocol_error(
                    code="single_agent_turn_unexecuted_tool_intent",
                    reason="tool_action_intent_not_executed",
                    diagnostics={
                        "protocol_errors": list(protocol.protocol_errors),
                        "parse_diagnostics": dict(protocol.parse_diagnostics or {}),
                        "previous_tool_intents_not_executed": [
                            {
                                "tool_name": str(call.get("name") or call.get("tool_name") or ""),
                                "args": dict(call.get("args") or {}) if isinstance(call.get("args"), dict) else {},
                                "source": str(call.get("source") or ""),
                            }
                            for call in native_tool_calls
                        ],
                        "action_issue": _protocol_action_issue(
                            category="action_not_executed",
                            code="tool_action_intent_not_in_current_connection",
                            requested_action_type="tool_call",
                            requested_tool_name=requested_tool_name,
                            repair_instruction=(
                                "上一轮表达了工具行动意图，但没有进入当前可执行工具队列。"
                                "请保留同一个观察目标，按本轮工具行动合同重新提交工具行动；"
                                "如果事实已经足够，可以直接自然回应或使用 respond.final_answer。"
                            ),
                        ),
                        "phase": phase,
                    },
                ),
            )
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
                        repair_instruction="同一轮只能提交一个动作决定；如果要调用工具，按本轮工具行动合同表达，不要同时提交两种工具行动。",
                    ),
                    "phase": phase,
                },
            ),
        )
    if json_action_like:
        action_request, diagnostics = model_action_request_from_payload(
            json_payload,
            turn_id=turn_id,
            public_feedback_expected=public_feedback_expected,
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
        tool_action_requests = (
            _tool_action_requests_from_json_action(parsed_action)
            if parsed_action.action_type == "tool_call"
            else ()
        )
        return SingleAgentActionParse(
            action_request=tool_action_requests[0] if len(tool_action_requests) == 1 else parsed_action,
            native_tool_calls=[],
            control_action=parsed_action if parsed_action.action_type != "tool_call" else None,
            tool_actions=tool_action_requests,
        )
    if malformed_action_like:
        action_request, diagnostics = model_action_request_from_payload(
            json_payload,
            turn_id=turn_id,
            public_feedback_expected=public_feedback_expected,
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
                        repair_instruction=(
                            "这看起来像一次动作选择，但行动对象缺少可执行字段。"
                            "请提交顶层 action_type 和对应动作字段，并保持本轮只有一个动作对象。"
                        )
                        if require_json_action
                        else (
                            "这看起来像一次动作选择，但行动对象缺少可执行字段。"
                            "请提交顶层 action_type 和对应动作字段，或直接自然回答用户。"
                        ),
                    ),
                    "phase": phase,
                },
            ),
        )
    if not native_tool_calls:
        if (
            assistant_text
            and _plain_assistant_text_is_allowed_response(
                assistant_text,
                allowed_action_types=allowed_action_types,
                output_contract=channel_contract,
            )
        ):
            if contains_internal_protocol(assistant_text) or contains_inline_pseudo_tool_call(assistant_text):
                return SingleAgentActionParse(
                    action_request=None,
                    native_tool_calls=[],
                    error=_mixed_public_text_and_action_intent_error(
                        phase=phase,
                        assistant_text=assistant_text,
                        parse_diagnostics=dict(protocol.parse_diagnostics or {}),
                    ),
                )
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=[],
                assistant_final_text=assistant_text,
            )
        if assistant_text and not _output_channel_allows_direct_visible_text(channel_contract):
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=[],
                error=_direct_visible_text_not_allowed_error(
                    phase=phase,
                    assistant_text=assistant_text,
                    output_contract=channel_contract,
                    allowed_action_types=allowed_action_types,
                    parse_diagnostics=dict(protocol.parse_diagnostics or {}),
                ),
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
                            repair_instruction=(
                                "本轮没有形成可执行动作或可发布回答；如果只是回答用户，可以直接自然回复；如果需要工具、询问、阻塞或控制，提交结构化动作对象。"
                            ),
                        ),
                        "phase": phase,
                    },
                ),
            )
        return SingleAgentActionParse(action_request=None, native_tool_calls=[])
    agent_public_feedback_note = public_runtime_progress_summary(protocol.content).strip()
    native_parse = _action_requests_from_native_tool_calls_with_diagnostics(
        native_tool_calls,
        turn_id=turn_id,
        packet_ref=packet_ref,
        iteration=iteration,
        allowed_action_types=allowed_action_types,
        public_feedback_expected=public_feedback_expected,
        agent_public_feedback_note=agent_public_feedback_note,
    )
    sidecar_actions = list(native_parse.actions)
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
    tool_actions = tuple(item for item in sidecar_actions if item.action_type == "tool_call")
    control_actions = tuple(item for item in sidecar_actions if item.action_type != "tool_call")
    if tool_actions and control_actions:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_mixed_native_action_planes",
                reason="mixed_native_tool_and_control_actions",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "tool_action_count": len(tool_actions),
                    "control_action_count": len(control_actions),
                    "action_issue": _protocol_action_issue(
                        category="protocol_violation",
                        code="mixed_native_tool_and_control_actions",
                        repair_instruction=(
                            "本轮只能选择一个语义动作平面：要么选择普通工具观察，要么选择一个控制动作。"
                            "如果要申请长任务资源，请只提交 request_task_run。"
                        ),
                    ),
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
                repair_instruction="当前阶段不能继续请求工具；请在本轮可用动作中选择回答、询问、阻塞或已开放的控制动作。",
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
            agent_public_feedback_note=agent_public_feedback_note,
        )
    if control_actions:
        if len(control_actions) != 1:
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=native_tool_calls,
                error=_single_agent_protocol_error(
                    code="single_agent_turn_multiple_control_actions",
                    reason="multiple_control_actions",
                    diagnostics={
                        "native_tool_call_count": len(native_tool_calls),
                        "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                        "control_action_count": len(control_actions),
                        "action_issue": _protocol_action_issue(
                            category="protocol_violation",
                            code="multiple_control_actions",
                            repair_instruction="本轮只能选择一个控制动作；请保留最能表达下一步的那个动作并重新提交。",
                        ),
                        "phase": phase,
                    },
                ),
            )
        return SingleAgentActionParse(
            action_request=control_actions[0],
            native_tool_calls=native_tool_calls,
            control_action=control_actions[0],
            agent_public_feedback_note=agent_public_feedback_note,
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
        "text_transport": str(diagnostics.get("transport") or "structured_action"),
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
        "task_recovery_resume",
        "selected_skill_ids",
        "task_run_contract_seed",
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


def _parse_diagnostics_contains_mixed_public_text_and_action_intent(parse_diagnostics: dict[str, Any] | None) -> bool:
    diagnostics = dict(parse_diagnostics or {})
    ignored_parts = (
        diagnostics.get("ignored_leading_text"),
        diagnostics.get("ignored_trailing_text"),
    )
    return any(
        contains_internal_protocol(str(part or "")) or contains_inline_pseudo_tool_call(str(part or ""))
        for part in ignored_parts
        if str(part or "").strip()
    )


def _mixed_public_text_and_action_intent_error(
    *,
    phase: str,
    assistant_text: str,
    parse_diagnostics: dict[str, Any] | None = None,
    requested_action_type: str = "",
) -> dict[str, Any]:
    repair_instruction = (
        "上一轮输出里同时出现了公开表达和行动表达，行动没有进入执行队列。"
        "请继续根据用户目标和已确认事实选择当前可执行动作。"
        "如果只是回答用户，可以直接自然回应；"
        "如果还需要查证，按本轮工具行动合同提交工具动作。"
        "需要保留的公开判断放入 public_progress_note 或 public_action_state.current_judgment。"
    )
    return _single_agent_protocol_error(
        code="single_agent_turn_mixed_public_text_and_action_intent",
        reason="action_intent_not_executed",
        diagnostics={
            "phase": phase,
            "parse_diagnostics": dict(parse_diagnostics or {}),
            "previous_response_preview": _compact_text(assistant_text, limit=600),
            "action_issue": _protocol_action_issue(
                category="action_not_executed",
                code="mixed_public_text_and_action_intent",
                requested_action_type=str(requested_action_type or ""),
                repair_instruction=repair_instruction,
            ),
        },
    )


def _action_requests_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...] = ("respond", "tool_call"),
    public_feedback_expected: bool = False,
    agent_public_feedback_note: str = "",
) -> list[ModelActionRequest]:
    return list(
        _action_requests_from_native_tool_calls_with_diagnostics(
            tool_calls,
            turn_id=turn_id,
            packet_ref=packet_ref,
            iteration=iteration,
            allowed_action_types=allowed_action_types,
            public_feedback_expected=public_feedback_expected,
            agent_public_feedback_note=agent_public_feedback_note,
        ).actions
    )


def _action_requests_from_native_tool_calls_with_diagnostics(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
    allowed_action_types: tuple[str, ...] = ("respond", "tool_call"),
    public_feedback_expected: bool = False,
    agent_public_feedback_note: str = "",
) -> NativeActionRequestParse:
    actions: list[ModelActionRequest] = []
    errors: list[dict[str, Any]] = []
    visible_feedback_note = public_runtime_progress_summary(agent_public_feedback_note).strip()
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
                        repair_instruction="如果要调用工具，按本轮工具行动合同表达，并填写工具名和参数。",
                    ),
                    "repairable": True,
                }
            )
            continue
        action_object_only_error = _native_action_object_only_error(call)
        if action_object_only_error is not None:
            errors.append(action_object_only_error)
            continue
        if is_control_action_tool_name(tool_name):
            arg_errors = control_action_arg_errors_from_native_tool_call(call)
            payload = control_action_request_payload_from_native_tool_call(
                call,
                turn_id=turn_id,
                packet_ref=packet_ref,
                iteration=iteration,
            )
            action, parse_diagnostics = model_action_request_from_payload(
                payload,
                turn_id=turn_id,
                allowed_action_types=allowed_action_types,
                public_feedback_expected=public_feedback_expected,
            )
            validation_errors = [
                str(item)
                for item in [
                    *arg_errors,
                    *list(dict(parse_diagnostics or {}).get("validation_errors") or []),
                ]
                if str(item)
            ]
            if action is None or validation_errors:
                errors.append(
                    {
                        "authority": "harness.loop.single_agent_turn.native_action_parser",
                        "code": "native_control_action_invalid",
                        "reason": "native_control_action_invalid",
                        "native_tool_call": _native_tool_call_diagnostics(call),
                        "validation_errors": validation_errors,
                        "action_issue": _protocol_action_issue(
                            category="protocol_violation",
                            code="native_control_action_invalid",
                            requested_action_type=tool_name,
                            requested_tool_name=tool_name,
                            repair_instruction=(
                                "请重新选择本轮允许的控制动作并按 provider 参数 schema 填写；"
                                "request_task_run 只填写紧凑 TaskStartIntent，不要手写内部 TaskRunContract。"
                            ),
                        ),
                        "repairable": True,
                    }
                )
                continue
        else:
            action = _tool_action_request_from_native_tool_calls(
                [call],
                turn_id=turn_id,
                packet_ref=packet_ref,
                iteration=iteration,
            )
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
                        repair_instruction="请重新提交当前动作合同允许的动作；工具调用按本轮工具行动合同表达。",
                    ),
                    "repairable": True,
                }
            )
            continue
        if visible_feedback_note and not _model_action_request_has_public_response(action):
            public_action_state = dict(action.public_action_state or {})
            if not str(public_action_state.get("current_judgment") or "").strip():
                public_action_state["current_judgment"] = visible_feedback_note
            diagnostics = dict(action.diagnostics or {})
            contract_gaps = [
                str(item)
                for item in list(diagnostics.get("contract_gaps") or [])
                if str(item) not in {
                    "public_feedback_omitted_for_native_tool_call",
                    "public_feedback_omitted_for_tool_call",
                    "public_progress_note_missing_for_tool_call",
                }
            ]
            if contract_gaps:
                diagnostics["contract_gaps"] = contract_gaps
            else:
                diagnostics.pop("contract_gaps", None)
            action = replace(
                action,
                public_progress_note=visible_feedback_note,
                public_action_state=public_action_state,
                diagnostics={
                    **diagnostics,
                    "public_feedback_sidecar": "assistant_content_preamble",
                    "public_progress_note_source": "assistant_content_preamble",
                },
            )
        if public_feedback_expected and not _model_action_request_has_public_response(action):
            diagnostics = dict(action.diagnostics or {})
            contract_gaps = [
                str(item)
                for item in list(diagnostics.get("contract_gaps") or [])
                if str(item)
            ]
            if "public_feedback_omitted_for_native_tool_call" not in contract_gaps:
                contract_gaps.append("public_feedback_omitted_for_native_tool_call")
            action = replace(
                action,
                diagnostics={
                    **diagnostics,
                    "contract_gaps": contract_gaps,
                    "public_feedback_recommended": True,
                    "public_feedback_recommendation_source": "tool_observation_feedback",
                },
            )
        actions.append(action)
    return NativeActionRequestParse(actions=tuple(actions), errors=tuple(errors))


def _native_tool_call_diagnostics(call: dict[str, Any]) -> dict[str, Any]:
    payload = dict(call or {})
    args = payload.get("args")
    return {
        "id": str(payload.get("id") or ""),
        "name": str(payload.get("name") or ""),
        "source": str(payload.get("source") or ""),
        "args": dict(args or {}) if isinstance(args, dict) else {},
    }


def _native_action_object_only_error(call: dict[str, Any]) -> dict[str, Any] | None:
    tool_name = str(dict(call or {}).get("name") or "").strip()
    normalized = tool_name.lower()
    if normalized not in _ACTION_OBJECT_ONLY_ACTION_NAMES:
        return None
    action_type = _ACTION_OBJECT_ONLY_ACTION_HINTS.get(normalized, normalized)
    return {
        "authority": "harness.loop.single_agent_turn.native_action_parser",
        "code": "action_object_required_for_control_action",
        "reason": "action_object_required_for_control_action",
        "native_tool_call": _native_tool_call_diagnostics(call),
        "action_issue": _protocol_action_issue(
            category="protocol_violation",
            code="action_object_required_for_control_action",
            requested_action_type=action_type,
            requested_tool_name=tool_name,
            repair_instruction="这个意图属于本轮动作选择，不是外部工具请求；请保留你的判断，用结构化动作对象提交对应 action_type。",
        ),
        "repairable": True,
        "repair_contract": {
            "required_signal": "model_action_request",
            "action_type": action_type,
        },
    }


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
    task_run_contract_seed = (
        dict(payload.get("task_run_contract_seed") or {})
        if isinstance(payload.get("task_run_contract_seed"), dict)
        else {}
    )
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
    if task_run_contract_seed:
        container = dict(task_run_contract_seed.get("container_contract") or {})
        work_modes = [dict(item) for item in list(task_run_contract_seed.get("work_modes") or []) if isinstance(item, dict)]
        primary_ref = str(container.get("primary_work_mode_ref") or "").strip()
        primary = next((item for item in work_modes if str(item.get("mode_instance_id") or "") == primary_ref), {})
        detected_action["task_run_contract_seed_summary"] = {
            "resource_request_summary": _compact_text(container.get("entry_reason"), limit=240),
            "primary_work_mode_ref": primary_ref,
            "primary_work_mode_kind": str(dict(primary or {}).get("mode_kind") or "").strip(),
            "work_mode_count": len(work_modes),
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
            "required_shape": "one_action_like_object",
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
        f"上一轮包含{action_label}结构化动作，但该动作没有进入执行队列，"
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
    "container_contract",
    "work_modes",
    "user_visible_goal",
    "task_run_goal",
    "completion_criteria",
    "required_artifacts",
    "artifact_requirements",
    "required_verifications",
    "verification_requirements",
    *_REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS,
)
_TASK_RECOVERY_RESUME_NESTED_FIELDS = ("work_ref", "resume_ref", "task_run_id", "continuation_id")


def _request_task_run_minimal_repair_action() -> dict[str, Any]:
    return {
        "action_type": "request_task_run",
        "public_progress_note": "说明你要申请长任务资源来保存哪些目标、游标、恢复点或验收边界。",
        "public_action_state": {
            "current_judgment": "说明当前工作需要系统资源来保持执行状态。",
            "next_action": "申请长任务资源并绑定当前 turn。",
        },
        "task_run_contract_seed": {
            "contract_shape": "compact_task_start_intent",
            "primary_mode": "plan",
            "task_shape": "standard",
            "minimum_viable_next_step": "资源接受后的第一个可执行动作。",
            "working_scope": {
                "target_objects": ["要处理的文件、模块、目录、对象或问题域"],
                "workspace_refs": [],
                "source_refs": ["用户消息或已观察证据"],
                "excluded_scope": [],
                "known_constraints": ["用户明确约束、质量要求或排除项"],
            },
            "acceptance": {
                "mode": "checkpoint",
                "criteria": ["完成这项任务所需满足的可观察标准"],
                "final_answer_requirements": ["说明完成内容、验证结果、未完成项和风险"],
            },
            "mode_payload": {
                "summary": "当前可执行路线。",
                "steps": ["第一步"],
                "success_definition": "",
                "question": "",
                "recovery_handle": "",
                "monitor_target": "",
                "notes": [],
            },
            "todo_tool_contract": {
                "todo_is_tool": True,
                "cursor_updates": [],
            },
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
        "request_task_run 是申请长任务资源的控制动作，用于保存目标、计划游标、todo 游标、恢复点、控制边界和验收边界。"
        "它不是普通工具调用，也不是第二套模型生命周期。"
        "request_task_run 只提交紧凑 TaskStartIntent；运行时会生成内部 TaskRunContract。"
        "最小合法意图如下；用当前任务目标、范围、完成证据和验收边界替换占位文本，但保留这些键和层级：\n"
        f"{_request_task_run_repair_template_text()}"
    ).strip()


def _protocol_error_specific_repair_instruction(protocol_error: dict[str, Any]) -> str:
    diagnostics = dict(protocol_error.get("diagnostics") or {})
    action_issue = dict(diagnostics.get("action_issue") or {})
    return str(action_issue.get("repair_instruction") or "").strip()


def _invalid_json_action_repair_instruction(*, json_payload: dict[str, Any], diagnostics: dict[str, Any]) -> str:
    default = (
        "请按本轮动作契约重新提交一个合法结构化动作。"
        "需要工具时，只按本轮工具行动合同提交当前允许的工具行动，不要额外写第二种工具请求。"
    )
    payload = dict(json_payload or {})
    action_type = str(payload.get("action_type") or "").strip()
    errors = {str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or [])}
    if "public_task_lifecycle_claim_requires_request_task_run" in errors:
        return (
            "你的公开反馈宣称要申请或绑定长任务资源，但结构化动作不是 request_task_run。"
            "请重新选择一个一致动作：如果确实需要资源，提交 action_type=request_task_run 并填写紧凑 TaskStartIntent；"
            "如果只是要在当前 turn 内继续工具处理，请使用 action_type=tool_call，并改写公开反馈。"
        )
    if "public_feedback_required_for_tool_call" in errors:
        return (
            "本轮工具动作需要给用户一条简短阶段反馈。请保留同一个工具意图，"
            "并在顶层 public_progress_note 或 public_action_state.current_judgment 中写明要核对的公开事实；"
            "不要把反馈写成普通正文，也不要把尚未完成的工具动作说成已经完成。"
        )
    if action_type == "resume_task_recovery":
        task_recovery_resume = payload.get("task_recovery_resume")
        task_recovery_resume_obj = dict(task_recovery_resume or {}) if isinstance(task_recovery_resume, dict) else {}
        misplaced_top_level = [field for field in _TASK_RECOVERY_RESUME_NESTED_FIELDS if field in payload]
        payload_wrapper = payload.get("payload") if isinstance(payload.get("payload"), dict) else None
        if misplaced_top_level or payload_wrapper is not None:
            misplaced = "、".join(misplaced_top_level) if misplaced_top_level else "payload"
            return (
                "resume_task_recovery 的恢复句柄字段放错层级。不要把 "
                f"{misplaced} 放在动作对象顶层，也不要使用 payload 包裹。"
                "请保留 action_type=resume_task_recovery，并把 work_ref、resume_ref "
                "全部放入 task_recovery_resume 对象内。只使用当前任务恢复上下文提供的句柄，不要从旧消息文本猜测。"
            )
        if (
            "task_recovery_resume.task_run_id_required" in errors
            or "task_recovery_resume.continuation_id_required" in errors
            or not isinstance(task_recovery_resume, dict)
        ):
            missing = []
            if not str(task_recovery_resume_obj.get("work_ref") or task_recovery_resume_obj.get("task_run_id") or "").strip():
                missing.append("work_ref")
            if not str(task_recovery_resume_obj.get("resume_ref") or task_recovery_resume_obj.get("continuation_id") or "").strip():
                missing.append("resume_ref")
            missing_text = "、".join(missing) if missing else "必需字段"
            return (
                "resume_task_recovery 必须包含 task_recovery_resume 对象。请在 task_recovery_resume 内补齐 "
                f"{missing_text}；这些句柄必须来自当前可恢复上下文。"
            )
        return default
    if action_type != "request_task_run":
        return default
    task_seed = payload.get("task_run_contract_seed")
    task_seed_obj = dict(task_seed or {}) if isinstance(task_seed, dict) else {}
    misplaced_top_level = [field for field in _REQUEST_TASK_RUN_TASK_CONTRACT_FIELDS if field in payload]
    payload_wrapper = payload.get("payload") if isinstance(payload.get("payload"), dict) else None
    if misplaced_top_level or payload_wrapper is not None:
        misplaced = "、".join(misplaced_top_level) if misplaced_top_level else "payload"
        return _with_request_task_run_repair_template(
            "request_task_run 的任务运行合同字段放错层级。不要把 "
            f"{misplaced} 放在动作对象顶层，也不要使用 payload 包裹。"
            "请保留 action_type=request_task_run，把紧凑 TaskStartIntent 放入 task_run_contract_seed 内。"
        )
    if any(str(item).startswith("system_execution_field_not_allowed_in_task_run_contract") for item in errors):
        return _with_request_task_run_repair_template(
            "request_task_run 的 TaskStartIntent 只描述 primary_mode、task_shape、最小下一步、范围和验收；请删除工具、模型、环境或执行授权字段。"
        )
    if (
        "compact_task_start_intent.minimum_viable_next_step_required" in errors
        or "compact_task_start_intent.working_scope_required" in errors
        or "compact_task_start_intent.acceptance_mode_required" in errors
        or any(item.startswith("compact_task_start_intent.contract_shape_unsupported") for item in errors)
        or any(item.startswith("compact_task_start_intent.primary_mode_unsupported") for item in errors)
        or any(item.startswith("compact_task_start_intent.task_shape_unsupported") for item in errors)
    ):
        return _with_request_task_run_repair_template(
            "request_task_run 的紧凑 TaskStartIntent 不完整。请补齐 primary_mode、task_shape、minimum_viable_next_step、working_scope 和 acceptance.mode。"
        )
    if (
        "container_contract.minimum_viable_next_step_required_for_request_task_run" in errors
        or "work_modes.exactly_one_primary_required_for_request_task_run" in errors
        or "work_modes_required_for_request_task_run" in errors
        or "container_contract.primary_work_mode_ref_must_point_to_primary_work_mode" in errors
    ):
        return _with_request_task_run_repair_template(
            "request_task_run 必须提交紧凑 TaskStartIntent。请补齐 primary_mode、task_shape、"
            "minimum_viable_next_step、working_scope、acceptance 和 mode_payload。"
        )
    if "task_run_contract_seed_required_for_request_task_run" in errors:
        return _with_request_task_run_repair_template(
            "request_task_run 必须包含 task_run_contract_seed，且紧凑 TaskStartIntent 必须放在 task_run_contract_seed 内。"
        )
    if any(item.startswith("primary_") and item.endswith("_required_for_request_task_run") for item in errors):
        return (
            "TaskStartIntent 的 mode_payload 最低可执行内容不完整。"
            "如果 primary_mode=goal，请给出 summary 或 success_definition；如果 primary_mode=plan，请给出 summary 或 steps。"
            "todo 是资源中的游标或工具，不是 primary_mode。"
        )
    if "acceptance_contract.acceptance_mode_required_for_request_task_run" in errors:
        return _with_request_task_run_repair_template("request_task_run 必须声明 acceptance.mode，例如 checkpoint、user_review、best_effort 或 strict。")
    if "tool_call_not_allowed_for_request_task_run" in errors:
        return _with_request_task_run_repair_template(
            "request_task_run 是长任务资源申请动作，不能和普通 tool_call 放在同一个动作里。"
            "请先提交资源申请；资源接受后再在后续 turn 中继续执行工具。"
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


def _native_tools_for_packet(
    allowed_action_types: tuple[str, ...],
    *,
    available_tools: tuple[dict[str, Any], ...] = (),
    tool_call_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    allowed = set(allowed_action_types or ())
    bindings: list[dict[str, Any]] = []
    if "tool_call" in allowed and provider_tools_enabled_from_contract(tool_call_contract):
        executable_tools = tuple(
            dict(item)
            for item in tuple(available_tools or ())
            if isinstance(item, dict)
            and not _is_model_action_native_tool_name(item.get("tool_name") or item.get("name"))
        )
        bindings.extend(provider_tool_bindings_for_available_tools(executable_tools))
    if provider_control_tools_enabled_from_contract(tool_call_contract):
        bindings.extend(provider_control_action_bindings(tuple(allowed)))
    deduped: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        name = str(dict(binding or {}).get("name") or "").strip()
        if name:
            deduped[name] = dict(binding or {})
    return [deduped[name] for name in sorted(deduped)]


def _model_tool_calls_allowed_for_packet(
    allowed_action_types: tuple[str, ...],
    *,
    available_tools: tuple[dict[str, Any], ...] = (),
    tool_call_contract: dict[str, Any] | None = None,
) -> bool:
    return bool(
        _native_tools_for_packet(
            allowed_action_types,
            available_tools=available_tools,
            tool_call_contract=tool_call_contract,
        )
    )


def _tool_call_contract_from_packet(packet: Any) -> dict[str, Any]:
    hidden = dict(getattr(packet, "hidden_control_refs", {}) or {})
    contract = hidden.get("tool_call_contract")
    if isinstance(contract, dict) and contract:
        return dict(contract)
    diagnostics = dict(getattr(packet, "diagnostics", {}) or {})
    diagnostic_contract = diagnostics.get("tool_call_contract")
    return dict(diagnostic_contract or {}) if isinstance(diagnostic_contract, dict) else {}


def _tool_action_requests_from_json_action(action_request: ModelActionRequest) -> tuple[ModelActionRequest, ...]:
    raw_calls = tuple(dict(item) for item in tuple(getattr(action_request, "tool_calls", ()) or ()) if isinstance(item, dict))
    if not raw_calls and action_request.tool_call:
        raw_calls = (dict(action_request.tool_call or {}),)
    if not raw_calls:
        return ()
    if len(raw_calls) == 1:
        tool_call = dict(raw_calls[0])
        return (
            replace(
                action_request,
                tool_call=tool_call,
                tool_calls=(tool_call,),
                diagnostics={
                    **dict(action_request.diagnostics or {}),
                    "tool_call_submission": "action_object",
                },
            ),
        )
    result: list[ModelActionRequest] = []
    for index, raw_call in enumerate(raw_calls, start=1):
        tool_call = dict(raw_call or {})
        tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        call_id = str(tool_call.get("id") or tool_call.get("tool_call_id") or tool_name or index).strip()
        child_request_id = f"{action_request.request_id}:tool:{index}:{_stable_action_suffix(call_id)}"
        result.append(
            replace(
                action_request,
                request_id=child_request_id,
                tool_call=tool_call,
                tool_calls=(tool_call,),
                diagnostics={
                    **dict(action_request.diagnostics or {}),
                    "origin_kind": "single_agent_turn_json_tool_calls",
                    "tool_call_submission": "action_object",
                    "batch_action_request_ref": action_request.request_id,
                    "tool_call_index": index - 1,
                    "tool_call_count": len(raw_calls),
                },
            )
        )
    return tuple(result)


def _tool_action_request_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
) -> ModelActionRequest | None:
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name or tool_name.lower() in _ACTION_OBJECT_ONLY_ACTION_NAMES or is_control_action_tool_name(tool_name):
            continue
        args, public_note, public_action_state = _native_tool_action_args_and_public_feedback(dict(call.get("args") or {}))
        call_id = str(call.get("id") or "").strip()
        if not call_id:
            continue
        request_id = f"model-action:{turn_id}:single-agent-tool:{iteration}:{_stable_action_suffix(call_id or tool_name)}"
        tool_call = _normalized_transport_tool_call(
            call,
            request_id=request_id,
            tool_name=tool_name,
            args=args,
        )
        call_id = str(tool_call.get("id") or call_id)
        diagnostics: dict[str, Any] = {
            "origin_kind": "single_agent_turn_native_tool_call",
            "origin_authority": "harness.loop.single_agent_turn",
            "packet_ref": packet_ref,
            "tool_call_submission": "direct_tool_selection",
            "native_tool_call": {
                "id": call_id,
                "name": tool_name,
                "source": str(call.get("source") or ""),
            },
        }
        if public_note and not str(public_action_state.get("current_judgment") or "").strip():
            public_action_state["current_judgment"] = public_note
        if public_note:
            diagnostics["public_feedback_sidecar"] = "native_tool_args"
        else:
            diagnostics["contract_gaps"] = ["public_feedback_omitted_for_native_tool_call"]
        return ModelActionRequest(
            request_id=request_id,
            turn_id=turn_id,
            action_type="tool_call",
            public_progress_note=public_note,
            public_action_state=public_action_state,
            tool_call=tool_call,
            tool_calls=(tool_call,),
            diagnostics=diagnostics,
        )
    return None


def _normalized_transport_tool_call(
    call: dict[str, Any],
    *,
    request_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        **dict(call or {}),
        "tool_name": str(tool_name or ""),
        "name": str(tool_name or ""),
        "args": dict(args or {}),
    }
    source = str(payload.get("source") or "").strip()
    if source in {"native_tool_call", "provider_function_call"}:
        return ensure_tool_call_id(payload, request_id=request_id, ordinal=0)
    payload.pop("id", None)
    payload.pop("tool_call_id", None)
    return ensure_tool_call_id(payload, request_id=request_id, ordinal=0)


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


def _model_action_request_should_emit_public_feedback(action_request: ModelActionRequest) -> bool:
    if not _model_action_request_has_public_response(action_request):
        return False
    return str(action_request.action_type or "") in {
        "tool_call",
        "request_task_run",
        "active_work_control",
        "resume_task_recovery",
        "pause_for_user_steer",
    }


def _model_action_public_feedback_presentation_source(action_request: ModelActionRequest, values: dict[str, str]) -> str:
    diagnostics = dict(action_request.diagnostics or {})
    if str(diagnostics.get("public_feedback_sidecar") or "") == "assistant_content_preamble":
        return _ASSISTANT_CONTENT_PREAMBLE_PROGRESS_SOURCE
    public_progress_note = values.get("public_progress_note", "")
    current_judgment = values.get("current_judgment", "")
    return (
        "model_action.public_progress_note"
        if public_progress_note
        else "model_action.current_judgment"
        if current_judgment
        else "model_action.next_action"
    )


def _model_action_public_feedback_values(action_request: ModelActionRequest) -> dict[str, str]:
    public_state = dict(action_request.public_action_state or {})
    return _drop_empty_dict(
        {
            "public_progress_note": public_runtime_progress_summary(action_request.public_progress_note).strip(),
            "current_judgment": public_runtime_progress_summary(public_state.get("current_judgment") or "").strip(),
            "next_action": public_runtime_progress_summary(public_state.get("next_action") or "").strip(),
            "completion_status": public_runtime_progress_summary(public_state.get("completion_status") or "").strip(),
        }
    )


def _model_action_public_feedback_key(action_request: ModelActionRequest) -> str:
    values = _model_action_public_feedback_values(action_request)
    identity_payload = {
        "public_progress_note": values.get("public_progress_note", ""),
        "current_judgment": values.get("current_judgment", ""),
        "next_action": values.get("next_action", ""),
        "completion_status": values.get("completion_status", ""),
    }
    return hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_action_public_feedback_source_actions(
    action_parse: SingleAgentActionParse,
    tool_actions: list[ModelActionRequest] | tuple[ModelActionRequest, ...],
) -> tuple[ModelActionRequest, ...]:
    primary = action_parse.action_request
    candidates: list[ModelActionRequest] = []
    if primary is not None and _model_action_request_should_emit_public_feedback(primary):
        candidates.append(primary)
    else:
        candidates.extend(
            action
            for action in tuple(tool_actions or ())
            if _model_action_request_should_emit_public_feedback(action)
        )
    selected: list[ModelActionRequest] = []
    seen_feedback: set[str] = set()
    for action in candidates:
        feedback_key = _model_action_public_feedback_key(action)
        if feedback_key in seen_feedback:
            continue
        seen_feedback.add(feedback_key)
        selected.append(action)
    return tuple(selected)


def _model_public_feedback_identity(
    *,
    packet_ref: str,
    tool_iteration: int,
    tool_actions: list[ModelActionRequest] | tuple[ModelActionRequest, ...],
) -> str:
    action_refs = [
        str(getattr(action, "request_id", "") or "").strip()
        for action in tuple(tool_actions or ())
        if str(getattr(action, "request_id", "") or "").strip()
    ]
    if len(action_refs) == 1:
        return f"model-action-feedback:{action_refs[0]}"
    payload = {
        "packet_ref": str(packet_ref or ""),
        "tool_iteration": int(tool_iteration or 0),
        "action_refs": action_refs,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"model-action-feedback:{digest}"


_NATIVE_TOOL_PUBLIC_FEEDBACK_ARG_KEYS = {
    "public_progress_note",
    "public_note",
    "current_judgment",
    "user_visible_reason",
    "public_action_state",
}


def _native_tool_action_args_and_public_feedback(args: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
    raw_args = dict(args or {})
    clean_args = {
        key: value
        for key, value in raw_args.items()
        if str(key) not in _NATIVE_TOOL_PUBLIC_FEEDBACK_ARG_KEYS
    }
    public_note = _native_tool_public_note(raw_args)
    public_action_state = _native_tool_public_action_state(raw_args, public_note=public_note)
    return clean_args, public_note, public_action_state


def _native_tool_public_action_state(args: dict[str, Any], *, public_note: str) -> dict[str, Any]:
    raw_state = args.get("public_action_state")
    state_payload = dict(raw_state or {}) if isinstance(raw_state, dict) else {}
    state: dict[str, Any] = {"completion_status": "waiting_for_tool"}
    current_judgment = public_runtime_progress_summary(
        state_payload.get("current_judgment")
        or args.get("current_judgment")
        or public_note
        or ""
    ).strip()
    next_action = public_runtime_progress_summary(state_payload.get("next_action") or "").strip()
    visible_status = public_runtime_progress_summary(state_payload.get("visible_status") or "").strip()
    completion_status = public_runtime_progress_summary(state_payload.get("completion_status") or "").strip()
    if current_judgment:
        state["current_judgment"] = current_judgment[:220].rstrip()
    if next_action:
        state["next_action"] = next_action[:220].rstrip()
    if visible_status:
        state["visible_status"] = visible_status[:80].rstrip()
    if completion_status:
        state["completion_status"] = completion_status[:80].rstrip()
    open_risks = _native_tool_public_string_list(state_payload.get("open_risks"))
    if open_risks:
        state["open_risks"] = open_risks[:6]
    evidence_refs = _native_tool_public_string_list(state_payload.get("evidence_refs"))
    if evidence_refs:
        state["evidence_refs"] = evidence_refs[:8]
    return state


def _native_tool_public_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = public_runtime_progress_summary(item or "").strip()
        if text:
            result.append(text[:180].rstrip())
    return result


_TOOL_OBSERVATION_FAILURE_STATUSES = {
    "error",
    "failed",
    "denied",
    "needs_contract",
    "aborted",
    "canceled",
    "cancelled",
}


def _tool_followup_public_feedback_recommended(
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
        return True
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
    state = dict(args.get("public_action_state") or {}) if isinstance(args.get("public_action_state"), dict) else {}
    for key in (
        "public_progress_note",
        "public_note",
        "current_judgment",
        "user_visible_reason",
    ):
        text = public_runtime_progress_summary(args.get(key) or "").strip()
        if text:
            return text[:160].rstrip()
    text = public_runtime_progress_summary(state.get("current_judgment") or "").strip()
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


def _runtime_system_group_enabled(runtime_assembly: Any, group_id: str, *, default: bool) -> bool:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    manifest = dict(payload.get("system_wiring_manifest") or {})
    group = dict(dict(manifest.get("system_groups") or {}).get(str(group_id or "").strip()) or {})
    if not group:
        return default
    return bool(group.get("enabled") is True)


def _turn_reasoning_projection_public_enabled(runtime_assembly: Any) -> bool:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    runtime_contract = dict(payload.get("runtime_contract") or {})
    reasoning_projection = dict(runtime_contract.get("reasoning_projection") or {})
    for candidate in (
        reasoning_projection.get("public_visible"),
        reasoning_projection.get("public_enabled"),
        runtime_contract.get("reasoning_projection_enabled"),
    ):
        parsed = _optional_bool(candidate)
        if parsed is not None:
            return parsed
    return _runtime_system_group_enabled(runtime_assembly, "reasoning_projection", default=True)


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in ("", None):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return None


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
    repair_instruction = (
        "该工具调用没有执行，因为它需要可恢复的人工确认，而当前单轮对话没有持久审批恢复入口。"
        "请向用户说明这个边界，改为申请长任务资源，或在无法继续时给出阻塞说明；不要重复同一个未获准动作。"
    )
    structured_payload = dict(dict(observation.result_envelope or {}).get("structured_payload") or {})
    structured_payload["structured_error"] = {
        **dict(structured_payload.get("structured_error") or {}),
        "code": reason,
        "message": repair_instruction,
        "origin": "single_agent_turn_tool_approval_boundary",
        "retryable": True,
        "tool_executed": False,
        "repair_instruction": repair_instruction,
    }
    structured_payload["error"] = reason
    return replace(
        observation,
        status="denied",
        text=repair_instruction,
        result_envelope={
            **dict(observation.result_envelope or {}),
            "status": "denied",
            "error": reason,
            "error_code": reason,
            "retryable": True,
            "task_run_required": True,
            "repair_instruction": repair_instruction,
            "structured_payload": structured_payload,
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
            external_read_scopes=external_scope_payloads_for_base_dir(
                str(getattr(runtime_host, "backend_dir", "") or assembly_payload.get("backend_dir") or ".")
            ),
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
        "tool_calls": _provider_visible_tool_calls_from_response(response, fallback_tool_calls=tool_calls),
    }
    reasoning_content = _reasoning_content_from_response(response)
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return message


def _provider_visible_tool_calls_from_response(
    response: Any,
    *,
    fallback_tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for raw_calls in _response_provider_tool_call_candidates(response):
        provider_calls = _provider_shaped_tool_calls(raw_calls)
        if provider_calls:
            return provider_calls
        provider_calls = _provider_calls_from_stream_chunks(raw_calls)
        if provider_calls:
            return provider_calls
    return _provider_visible_tool_calls_from_normalized(fallback_tool_calls)


def _response_provider_tool_call_candidates(response: Any) -> list[Any]:
    candidates: list[Any] = []
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        candidates.append(additional_kwargs.get("tool_calls"))
    raw_tool_call_chunks = getattr(response, "raw_tool_call_chunks", None)
    if raw_tool_call_chunks:
        candidates.append(raw_tool_call_chunks)
    raw_response = getattr(response, "raw_response", None)
    if not isinstance(raw_response, dict):
        raw_response = getattr(response, "raw", None)
    if isinstance(raw_response, dict):
        choices = list(raw_response.get("choices") or [])
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            candidates.append(dict(message).get("tool_calls"))
            candidates.append(dict(delta).get("tool_calls"))
    if isinstance(response, dict):
        candidates.append(response.get("tool_calls"))
        nested_kwargs = response.get("additional_kwargs")
        if isinstance(nested_kwargs, dict):
            candidates.append(nested_kwargs.get("tool_calls"))
    return [item for item in candidates if item not in (None, [], {})]


def _provider_shaped_tool_calls(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in list(value or []) if isinstance(value, (list, tuple)) else []:
        if not isinstance(raw, dict):
            return []
        item = dict(raw)
        function = item.get("function")
        if str(item.get("type") or "") != "function" or not isinstance(function, dict):
            return []
        if not str(item.get("id") or "").strip():
            return []
        if not str(function.get("name") or "").strip():
            return []
        if not isinstance(function.get("arguments"), str):
            return []
        result.append(copy.deepcopy(item))
    return result


def _provider_calls_from_stream_chunks(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in list(value or []) if isinstance(value, (list, tuple)) else []:
        if not isinstance(raw, dict):
            return []
        item = dict(raw)
        call_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        arguments = item.get("arguments")
        if not call_id or not name or not isinstance(arguments, str):
            return []
        result.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        )
    return result


def _provider_visible_tool_calls_from_normalized(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    provider_message = provider_message_payloads(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [dict(item) for item in list(tool_calls or []) if isinstance(item, dict)],
            }
        ]
    )
    if not provider_message:
        return []
    calls = dict(provider_message[0]).get("tool_calls")
    return [dict(item) for item in list(calls or []) if isinstance(item, dict)]


def _reasoning_content_from_response(response: Any) -> str:
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        reasoning_content = _explicit_provider_text(additional_kwargs.get("reasoning_content"))
        if reasoning_content:
            return reasoning_content
    raw_response = getattr(response, "raw_response", None)
    if not isinstance(raw_response, dict):
        raw_response = getattr(response, "raw", None)
    if isinstance(raw_response, dict):
        for choice in list(raw_response.get("choices") or []):
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            reasoning_content = _first_explicit_provider_text(
                dict(message).get("reasoning_content"),
                dict(message).get("reasoning"),
                dict(delta).get("reasoning_content"),
                dict(delta).get("reasoning"),
            )
            if reasoning_content:
                return reasoning_content
    if isinstance(response, dict):
        reasoning_content = _explicit_provider_text(response.get("reasoning_content"))
        if reasoning_content:
            return reasoning_content
        response_additional_kwargs = response.get("additional_kwargs")
        if isinstance(response_additional_kwargs, dict):
            return _explicit_provider_text(response_additional_kwargs.get("reasoning_content"))
    return ""


def _first_explicit_provider_text(*values: Any) -> str:
    for value in values:
        text = _explicit_provider_text(value)
        if text:
            return text
    return ""


def _explicit_provider_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text != "" else ""


def _reasoning_projection_status_event(
    reasoning_content: str,
    *,
    turn_id: str,
    turn_run_id: str,
    task_run_id: str,
    answer_channel: str,
    answer_source: str,
    phase: str = "model_finalization",
    state: str = "done",
    provider_request_id: str = "",
) -> dict[str, Any]:
    content = str(reasoning_content or "").strip()
    if not content:
        return {}
    char_count = len(content)
    estimated_tokens = max(1, (char_count + 3) // 4)
    digest = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
    normalized_state = str(state or "done").strip() or "done"
    detail = "正在整理当前思路，可折叠查看。" if normalized_state == "running" else "当前思路已记录，可折叠查看。"
    return {
        "type": "runtime_status",
        "title": "模型思考",
        "detail": detail,
        "state": normalized_state,
        "status_kind": "reasoning_projection_state",
        "phase": str(phase or "model_finalization"),
        "turn_id": str(turn_id or ""),
        "active_turn_id": str(turn_id or ""),
        "turn_run_id": str(turn_run_id or ""),
        "task_run_id": str(task_run_id or ""),
        "provider_request_id": str(provider_request_id or ""),
        "reasoning_content_present": True,
        "reasoning_content": content,
        "reasoning_content_chars": char_count,
        "reasoning_content_estimated_tokens": estimated_tokens,
        "reasoning_content_sha256": "sha256:" + digest,
        "reasoning_projection_policy": "public_collapsible_trace",
        "answer_channel": str(answer_channel or ""),
        "answer_source": str(answer_source or ""),
    }


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


def _final_provider_protocol_messages_to_append(
    provider_protocol_messages_to_append: list[dict[str, Any]],
    *,
    turn_id: str,
    final_content: str,
) -> list[dict[str, Any]] | None:
    messages = [dict(item) for item in list(provider_protocol_messages_to_append or []) if isinstance(item, dict)]
    if not messages:
        return None
    messages.append(_assistant_protocol_message_from_content(final_content, turn_id=turn_id))
    return messages


def _with_turn_id(message: dict[str, Any], turn_id: str) -> dict[str, Any]:
    return {**dict(message or {}), "turn_id": turn_id}


def _copy_model_messages_without_rewriting(messages: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(messages or []) if isinstance(item, dict) and item]


def _append_model_messages_without_rewriting_context(
    model_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    new_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    turn_id: str = "",
    source: str = "harness.loop.single_agent_turn.append_only_context",
    segment_kind: str = "",
    segment_source_ref: str = "",
    segment_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    sealed_prefix = _copy_model_messages_without_rewriting(model_messages)
    clean_new = [dict(item) for item in list(new_messages or []) if isinstance(item, dict) and item]
    if not clean_new:
        return sealed_prefix
    sanitized_new = _sanitize_model_messages(clean_new, turn_id=turn_id, source=source)
    tagged_new = _with_runtime_context_segment_tags(
        sanitized_new,
        source=source,
        segment_kind=segment_kind,
        segment_source_ref=segment_source_ref,
        segment_metadata=segment_metadata,
    )
    return [*sealed_prefix, *tagged_new]


def _with_runtime_context_segment_tags(
    messages: list[dict[str, Any]],
    *,
    source: str,
    segment_kind: str = "",
    segment_source_ref: str = "",
    segment_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    kind = str(segment_kind or "").strip()
    source_ref = str(segment_source_ref or "").strip()
    runtime_control_role = ""
    if not kind:
        kind, source_ref, runtime_control_role = _RUNTIME_CONTEXT_SEGMENT_SOURCES.get(str(source or ""), ("", "", ""))
    if not kind:
        return [dict(item) for item in list(messages or []) if isinstance(item, dict)]
    metadata = {
        **dict(segment_metadata or {}),
        "runtime_control_source": str(source or ""),
    }
    if runtime_control_role:
        metadata.setdefault("runtime_control_role", runtime_control_role)
    tagged: list[dict[str, Any]] = []
    for message in [dict(item) for item in list(messages or []) if isinstance(item, dict)]:
        message[_RUNTIME_CONTEXT_SEGMENT_KIND_KEY] = kind
        if source_ref:
            message[_RUNTIME_CONTEXT_SEGMENT_SOURCE_REF_KEY] = source_ref
        if metadata:
            message[_RUNTIME_CONTEXT_SEGMENT_METADATA_KEY] = dict(metadata)
        tagged.append(message)
    return tagged


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


def _assert_model_messages_match_segment_plan(
    model_messages: list[dict[str, Any]],
    *,
    accounting_context: dict[str, Any],
    source: str,
) -> None:
    segment_plan = dict(dict(accounting_context or {}).get("segment_plan") or {})
    segments = [
        dict(item)
        for item in list(segment_plan.get("segments") or [])
        if isinstance(item, dict) and _safe_int_value(item.get("model_message_index")) >= 0
    ]
    if not segments:
        return
    provider_messages = provider_message_payloads(
        [dict(item) for item in list(model_messages or []) if isinstance(item, dict)]
    )
    violations: list[dict[str, Any]] = []
    if len(provider_messages) != len(segments):
        violations.append(
            {
                "reason": "message_count_mismatch",
                "provider_message_count": len(provider_messages),
                "segment_count": len(segments),
            }
        )
    for segment in sorted(segments, key=lambda item: _safe_int_value(item.get("model_message_index"))):
        index = _safe_int_value(segment.get("model_message_index"))
        if index >= len(provider_messages):
            violations.append(
                {
                    "reason": "segment_index_out_of_range",
                    "model_message_index": index,
                    "kind": str(segment.get("kind") or ""),
                }
            )
            continue
        message = dict(provider_messages[index])
        metadata = dict(segment.get("metadata") or {})
        provider_hash = _stable_payload_hash(message)
        expected_provider_hash = str(metadata.get("provider_payload_hash") or metadata.get("provider_visible_hash") or "").strip()
        if expected_provider_hash and expected_provider_hash != provider_hash:
            violations.append(
                {
                    "reason": "provider_payload_hash_mismatch",
                    "model_message_index": index,
                    "kind": str(segment.get("kind") or ""),
                    "expected_provider_payload_hash": expected_provider_hash,
                    "actual_provider_payload_hash": provider_hash,
                }
            )
            continue
        expected_model_hash = str(segment.get("model_message_hash") or "").strip()
        actual_model_hash = stable_model_message_hash(message)
        if expected_model_hash and expected_model_hash != actual_model_hash:
            violations.append(
                {
                    "reason": "model_message_hash_mismatch",
                    "model_message_index": index,
                    "kind": str(segment.get("kind") or ""),
                    "expected_model_message_hash": expected_model_hash,
                    "actual_model_message_hash": actual_model_hash,
                }
            )
    if violations:
        raise RuntimeError(
            "single_agent_provider_payload_segment_plan_mismatch:"
            + json.dumps(
                {
                    "source": str(source or ""),
                    "request_id": str(dict(accounting_context or {}).get("request_id") or ""),
                    "packet_ref": str(dict(accounting_context or {}).get("packet_ref") or ""),
                    "violations": violations[:20],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def _compact_text(value: Any, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _single_agent_turn_followup_prompt_context(
    *,
    compilation: Any,
    model_messages: list[dict[str, Any]],
    base_segment_plan: dict[str, Any] | None = None,
    packet_id: str = "",
    tool_iteration: int,
    storage_root: Path | None = None,
    provider_visible_append_scope: str = "",
    model_selection: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    resolved_packet_id = str(packet_id or compilation.packet.packet_id)
    followup_messages, followup_segment_plan = _single_agent_turn_followup_prompt_payload(
        base_segment_plan=dict(base_segment_plan or compilation.packet.segment_plan or {}),
        model_messages=model_messages,
        packet_id=resolved_packet_id,
        tool_iteration=tool_iteration,
        storage_root=storage_root,
        provider_visible_append_scope=provider_visible_append_scope,
        model_selection=model_selection,
    )
    followup_prompt_manifest = {
        **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
        "invocation_kind": "single_agent_turn_tool_followup",
        "segment_plan_ref": str(followup_segment_plan.get("segment_plan_id") or ""),
        "followup_iteration": tool_iteration,
    }
    return followup_messages, followup_segment_plan, followup_prompt_manifest, resolved_packet_id


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

    def list_cache_plans(self, **_kwargs: Any) -> list[Any]:
        return []

    def summarize_session(self, _session_id: str) -> dict[str, Any]:
        return {}


def _single_agent_turn_followup_prompt_payload(
    *,
    base_segment_plan: dict[str, Any],
    model_messages: list[dict[str, Any]],
    packet_id: str,
    tool_iteration: int,
    storage_root: Path | None = None,
    provider_visible_append_scope: str = "",
    model_selection: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    append_only_messages = _copy_model_messages_without_rewriting(model_messages)
    specs, prefix_lock_report = _single_agent_turn_append_only_followup_message_specs(
        base_segment_plan=base_segment_plan,
        model_messages=append_only_messages,
        tool_iteration=tool_iteration,
        packet_id=packet_id,
    )
    specs, tool_protocol_diagnostics = _standardize_followup_provider_tool_protocol_specs(
        specs,
        source="single_agent_turn_tool_followup",
    )
    specs, tool_round_diagnostics = annotate_provider_tool_round_specs(
        specs,
        source="single_agent_turn_tool_followup",
    )
    specs = _with_provider_visible_followup_commit_candidates(
        specs,
        storage_root=storage_root,
        scope=provider_visible_append_scope,
        model_selection=model_selection,
    )
    specs, physical_assembly_diagnostics = _single_agent_turn_followup_physical_context_assembly(
        specs,
        storage_root=storage_root,
        provider_visible_append_scope=provider_visible_append_scope,
        model_selection=model_selection,
    )
    specs = _with_provider_payload_hashes(specs)
    specs, physical_plan = annotate_specs_with_physical_context_plan(specs)
    append_only_messages = [
        dict(spec.get("model_message") or {"role": spec.get("role") or "user", "content": spec.get("content") or ""})
        for spec in specs
        if isinstance(spec, dict)
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id=f"{packet_id}:tool-followup:{max(1, int(tool_iteration or 1))}",
        invocation_kind="single_agent_turn_tool_followup",
        message_specs=specs,
    ).to_dict()
    segment_plan = _with_followup_context_physical_diagnostics(
        segment_plan,
        base_segment_plan=base_segment_plan,
        physical_plan=physical_plan.to_dict(),
    )
    segment_plan.setdefault("diagnostics", {})
    segment_plan["diagnostics"] = {
        **dict(segment_plan.get("diagnostics") or {}),
        "physical_context_assembly": physical_assembly_diagnostics,
    }
    segment_plan = _annotate_single_agent_followup_segment_plan(
        segment_plan,
        packet_id=str(packet_id or ""),
        message_specs=specs,
    )
    segment_plan["prefix_lock"] = prefix_lock_report
    segment_plan["provider_tool_protocol_standardization"] = tool_protocol_diagnostics
    segment_plan["provider_tool_round_grouping"] = tool_round_diagnostics
    if str(prefix_lock_report.get("status") or "") != "preserved":
        raise RuntimeError(
            "single_agent_followup_provider_prefix_mutated:"
            + json.dumps(
                {
                    "packet_id": str(packet_id or ""),
                    "tool_iteration": int(tool_iteration or 0),
                    "prefix_lock": dict(prefix_lock_report or {}),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return append_only_messages, segment_plan


def _single_agent_turn_followup_physical_context_assembly(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    storage_root: Path | None,
    provider_visible_append_scope: str,
    model_selection: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if storage_root is None or not str(provider_visible_append_scope or "").strip():
        return [dict(item) for item in list(specs or []) if isinstance(item, dict)], {
            "status": "skipped",
            "reason": "missing_scope_or_storage_root",
            "authority": "harness.loop.single_agent_turn.followup_physical_context_assembly",
        }
    provider, model = _provider_model_from_selection(model_selection)
    static_prefix: list[dict[str, Any]] = []
    provider_protocol_replay_prefix: list[dict[str, Any]] = []
    provider_visible_append_specs: list[dict[str, Any]] = []
    dynamic_tail: list[dict[str, Any]] = []
    for raw_spec in list(specs or []):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        policy = context_segment_policy_for_spec(spec)
        metadata = dict(spec.get("metadata") or {})
        if provider_message_byte_preservation_required(spec) and not provider_protocol_append_candidate_metadata(metadata):
            provider_protocol_replay_prefix.append(_provider_protocol_prefix_replay_spec(spec))
            continue
        if policy.section == STATIC_PREFIX:
            static_prefix.append(spec)
            continue
        if _followup_spec_routes_to_physical_provider_visible_memory(spec, policy=policy, metadata=metadata):
            provider_visible_append_specs.append(spec)
            continue
        dynamic_tail.append(spec)
    assembly = assemble_physical_context_spine(
        static_prefix_specs=static_prefix,
        provider_visible_append_specs=provider_visible_append_specs,
        current_tail_specs=dynamic_tail,
        storage_root=storage_root,
        scope=str(provider_visible_append_scope or "").strip(),
        provider=provider,
        model=model,
        provider_lane=PROVIDER_LANE_AGENT_TOOL_LOOP,
    )
    if provider_protocol_replay_prefix:
        message_specs = [
            *static_prefix,
            *provider_protocol_replay_prefix,
            *list(assembly.current_append_specs or ()),
            *dynamic_tail,
        ]
        replay_status = "provider_protocol_prefix_preserved"
    else:
        message_specs = [dict(item) for item in assembly.message_specs]
        replay_status = "confirmed_physical_frame_replayed"
    return message_specs, {
        **dict(assembly.diagnostics or {}),
        "input_static_prefix_spec_count": len(static_prefix),
        "input_provider_visible_spec_count": len(provider_visible_append_specs),
        "input_dynamic_tail_spec_count": len(dynamic_tail),
        "provider_protocol_replay_prefix_spec_count": len(provider_protocol_replay_prefix),
        "provider_message_replay_status": replay_status,
        "authority": "harness.loop.single_agent_turn.followup_physical_context_assembly",
    }


def _provider_protocol_prefix_replay_spec(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    message = _spec_model_message(payload)
    metadata = {
        **dict(payload.get("metadata") or {}),
        "context_cache_section": CONTEXT_MEMORY_PREFIX,
        "fixed_context_package": "context_memory_prefix",
        "context_replay_policy": PROVIDER_PROTOCOL_REPLAY_POLICY,
        "provider_protocol_replay": True,
        "provider_protocol_prefix_replay": True,
        "provider_visible_history_status": PROVIDER_PROTOCOL_REPLAY_STATUS,
        "provider_visible_history_authority": "harness.loop.single_agent_turn.followup_physical_context_assembly",
        "provider_visible_history_model_message_hash": stable_model_message_hash(dict(message or {})),
        "cache_policy_rebased": "provider_protocol_prefix_preserved",
    }
    exact = {
        **payload,
        "role": str(message.get("role") or payload.get("role") or "user"),
        "content": str(message.get("content") if message.get("content") is not None else payload.get("content") or ""),
        "cache_scope": str(payload.get("cache_scope") or "session"),
        "cache_role": str(payload.get("cache_role") or "session_stable"),
        "prefix_tier": str(payload.get("prefix_tier") or "session"),
        "metadata": metadata,
        "model_message": dict(message or {}),
    }
    policy = context_segment_policy_for_spec(exact, default_section=CONTEXT_MEMORY_PREFIX)
    exact["metadata"] = {
        **metadata,
        **context_segment_policy_metadata(policy),
        "context_cache_section": CONTEXT_MEMORY_PREFIX,
        "fixed_context_package": "context_memory_prefix",
        "context_replay_policy": PROVIDER_PROTOCOL_REPLAY_POLICY,
        "provider_protocol_replay": True,
        "provider_protocol_prefix_replay": True,
    }
    exact["cache_scope"] = policy.prefix_cache_scope
    exact["cache_role"] = policy.prefix_cache_role
    exact["prefix_tier"] = policy.prefix_tier
    return exact


def _followup_spec_routes_to_physical_provider_visible_memory(
    spec: dict[str, Any],
    *,
    policy: Any,
    metadata: dict[str, Any],
) -> bool:
    if str(policy.section or "") == CONTEXT_MEMORY_PREFIX:
        return True
    if str(policy.section or "") != CONTEXT_APPEND:
        return False
    if str(metadata.get("provider_visible_append_commit_stage") or "").strip() == "provider_success_required":
        return True
    if str(metadata.get("context_commit_policy") or getattr(policy, "commit_policy", "") or "").strip() != "append_then_seal":
        return False
    if str(metadata.get("context_replay_policy") or getattr(policy, "replay_policy", "") or "").strip() == "current_dynamic_tail_only":
        return False
    return context_segment_is_provider_visible_sealable_spec(spec)


def _standardize_followup_provider_tool_protocol_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    source: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clean_specs = [dict(item) for item in list(specs or []) if isinstance(item, dict)]
    clean_specs, repair_diagnostics = _repair_adjacent_orphan_tool_protocol_specs(clean_specs)
    result: list[dict[str, Any]] = []
    pending_tool_call_ids: set[str] = set()
    pending_round_start_index: int | None = None
    diagnostics = {
        "source": str(source or ""),
        "input_spec_count": len(clean_specs),
        "output_spec_count": 0,
        "assistant_tool_call_count": 0,
        "tool_output_count": 0,
        "closed_tool_round_count": 0,
        "dropped_orphan_tool_output_count": 0,
        "dropped_invalid_assistant_tool_call_count": 0,
        "dropped_incomplete_tool_round_count": 0,
        "dropped_incomplete_tool_round_spec_count": 0,
        "reordered_adjacent_orphan_tool_round_count": repair_diagnostics["round_count"],
        "reordered_adjacent_orphan_tool_spec_count": repair_diagnostics["spec_count"],
        "authority": "harness.loop.single_agent_turn.provider_tool_protocol_standardization",
    }

    for raw_spec in clean_specs:
        spec = dict(raw_spec)
        message = _spec_model_message(spec)
        role = str(message.get("role") or spec.get("role") or "").strip()
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            if not tool_call_id or tool_call_id not in pending_tool_call_ids:
                if pending_tool_call_ids:
                    dropped = _drop_pending_tool_protocol_specs(
                        result,
                        pending_round_start_index=pending_round_start_index,
                    )
                    diagnostics["dropped_incomplete_tool_round_count"] += 1
                    diagnostics["dropped_incomplete_tool_round_spec_count"] += dropped
                    pending_tool_call_ids.clear()
                    pending_round_start_index = None
                diagnostics["dropped_orphan_tool_output_count"] += 1
                continue
            result.append(spec)
            pending_tool_call_ids.remove(tool_call_id)
            diagnostics["tool_output_count"] += 1
            if not pending_tool_call_ids:
                pending_round_start_index = None
                diagnostics["closed_tool_round_count"] += 1
            continue

        if pending_tool_call_ids:
            dropped = _drop_pending_tool_protocol_specs(
                result,
                pending_round_start_index=pending_round_start_index,
            )
            diagnostics["dropped_incomplete_tool_round_count"] += 1
            diagnostics["dropped_incomplete_tool_round_spec_count"] += dropped
            pending_tool_call_ids.clear()
            pending_round_start_index = None

        if role == "assistant" and message.get("tool_calls"):
            tool_call_ids = _assistant_tool_call_ids_from_provider_message(message)
            if not tool_call_ids:
                diagnostics["dropped_invalid_assistant_tool_call_count"] += 1
                continue
            pending_tool_call_ids = set(tool_call_ids)
            pending_round_start_index = len(result)
            diagnostics["assistant_tool_call_count"] += len(tool_call_ids)
            result.append(spec)
            continue

        result.append(spec)

    if pending_tool_call_ids:
        dropped = _drop_pending_tool_protocol_specs(
            result,
            pending_round_start_index=pending_round_start_index,
        )
        diagnostics["dropped_incomplete_tool_round_count"] += 1
        diagnostics["dropped_incomplete_tool_round_spec_count"] += dropped

    diagnostics["output_spec_count"] = len(result)
    diagnostics["changed"] = diagnostics["input_spec_count"] != diagnostics["output_spec_count"]
    return result, diagnostics


def _repair_adjacent_orphan_tool_protocol_specs(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    result: list[dict[str, Any]] = []
    round_count = 0
    spec_count = 0
    index = 0
    clean_specs = [dict(item) for item in list(specs or []) if isinstance(item, dict)]
    while index < len(clean_specs):
        spec = dict(clean_specs[index])
        message = _spec_model_message(spec)
        role = str(message.get("role") or spec.get("role") or "").strip()
        if role != "tool":
            result.append(spec)
            index += 1
            continue
        block_start = index
        tool_block: list[dict[str, Any]] = []
        tool_call_ids: list[str] = []
        while index < len(clean_specs):
            tool_spec = dict(clean_specs[index])
            tool_message = _spec_model_message(tool_spec)
            if str(tool_message.get("role") or tool_spec.get("role") or "").strip() != "tool":
                break
            tool_block.append(tool_spec)
            tool_call_id = str(tool_message.get("tool_call_id") or "").strip()
            if tool_call_id and tool_call_id not in tool_call_ids:
                tool_call_ids.append(tool_call_id)
            index += 1
        if tool_call_ids and index < len(clean_specs):
            assistant_spec = dict(clean_specs[index])
            assistant_message = _spec_model_message(assistant_spec)
            if str(assistant_message.get("role") or assistant_spec.get("role") or "").strip() == "assistant":
                assistant_tool_call_ids = _assistant_tool_call_ids_from_provider_message(assistant_message)
                if set(tool_call_ids).issubset(set(assistant_tool_call_ids)):
                    result.append(assistant_spec)
                    result.extend(tool_block)
                    round_count += 1
                    spec_count += len(tool_block) + 1
                    index += 1
                    continue
        result.extend(tool_block)
        if index == block_start:
            index += 1
    return result, {"round_count": round_count, "spec_count": spec_count}


def _spec_model_message(spec: dict[str, Any]) -> dict[str, Any]:
    message = dict(dict(spec or {}).get("model_message") or {})
    if message:
        return message
    return {
        "role": str(dict(spec or {}).get("role") or "user"),
        "content": str(dict(spec or {}).get("content") or ""),
    }


def _assistant_tool_call_ids_from_provider_message(message: dict[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for raw_call in list(dict(message or {}).get("tool_calls") or []):
        if not isinstance(raw_call, dict):
            continue
        call_id = str(dict(raw_call).get("id") or "").strip()
        if call_id and call_id not in ids:
            ids.append(call_id)
    return tuple(ids)


def _drop_pending_tool_protocol_specs(
    specs: list[dict[str, Any]],
    *,
    pending_round_start_index: int | None,
) -> int:
    if pending_round_start_index is None:
        return 0
    start = int(pending_round_start_index)
    if start < 0 or start >= len(specs):
        return 0
    dropped = len(specs) - start
    del specs[start:]
    return dropped


def _single_agent_turn_append_only_followup_message_specs(
    *,
    base_segment_plan: dict[str, Any],
    model_messages: list[dict[str, Any]],
    tool_iteration: int,
    packet_id: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prefix_locked_base_plan = dict(base_segment_plan or {})
    ordered_input_messages = _copy_model_messages_without_rewriting(model_messages)
    base_segments = _segment_plan_segments_by_message_index(prefix_locked_base_plan)
    provider_messages = provider_message_payloads(ordered_input_messages)
    prefix_lock_report = _single_agent_followup_prefix_lock_report(
        base_segment_plan=prefix_locked_base_plan,
        model_messages=list(provider_messages or []),
    )
    has_dynamic_tail = _has_physical_dynamic_tail_segments(prefix_locked_base_plan)
    dynamic_tail_segments_by_hash = (
        _dynamic_tail_segments_by_hash(prefix_locked_base_plan)
        if has_dynamic_tail
        else {}
    )
    current_tool_round_indexes = _current_tool_round_message_indexes(ordered_input_messages)
    specs: list[dict[str, Any]] = []
    for index, message in enumerate(ordered_input_messages):
        provider_message = dict(provider_messages[index]) if index < len(provider_messages) else dict(message)
        base = dict(base_segments.get(index) or {})
        base_from_hash = False
        if base and _followup_base_segment_conflicts_with_message_shape(base, provider_message):
            base = {}
        if not base and has_dynamic_tail:
            base = _pop_matching_dynamic_tail_segment(dynamic_tail_segments_by_hash, message=provider_message)
            base_from_hash = bool(base)
        if base:
            prefix_lock_violation = (
                {}
                if base_from_hash and _is_tool_followup_current_dynamic_tail_segment(base)
                else prefix_lock_violation_for_index(prefix_lock_report, index)
            )
            spec = _single_agent_turn_followup_base_message_spec(
                base,
                message=provider_message,
                prefix_lock_violation=prefix_lock_violation,
                is_current_tool_round=index in current_tool_round_indexes,
                seal_provider_visible_history=not (
                    has_dynamic_tail and _is_tool_followup_current_dynamic_tail_segment(base)
                ),
                packet_id=packet_id,
            )
        else:
            spec = _single_agent_turn_followup_message_spec(
                provider_message,
                tool_iteration=tool_iteration,
                is_current_tool_round=index in current_tool_round_indexes,
            )
        specs.append(spec)
    return specs, prefix_lock_report


def _provider_visible_followup_ledger_kwargs(
    *,
    compiler: Any,
    session_id: str,
    model_selection: dict[str, Any] | None,
) -> dict[str, Any]:
    storage_root = _path_value(getattr(compiler, "base_dir", None))
    return {
        "storage_root": storage_root,
        "provider_visible_append_scope": str(session_id or "").strip(),
        "model_selection": dict(model_selection or {}),
    }


def _provider_cache_scope_id_for_turn(*, session_id: str, session_context: dict[str, Any] | None) -> str:
    payload = dict(session_context or {})
    forked_from = (
        dict(payload.get("forked_from") or {})
        if isinstance(payload.get("forked_from"), dict)
        else {}
    )
    inherited = str(forked_from.get("provider_cache_scope_id") or "").strip()
    if inherited:
        return inherited
    return str(session_id or "").strip()


def _provider_visible_followup_ledger_kwargs_from_accounting(
    accounting_context: dict[str, Any] | None,
    *,
    model_selection: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(accounting_context or {})
    storage_root = _path_value(
        payload.get("provider_visible_append_ledger_storage_root")
        or payload.get("storage_root")
    )
    return {
        "storage_root": storage_root,
        "provider_visible_append_scope": str(
            payload.get("provider_visible_append_scope")
            or payload.get("session_id")
            or ""
        ).strip(),
        "model_selection": dict(model_selection or {}),
    }


def _path_value(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text)


def _with_provider_visible_followup_commit_candidates(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    storage_root: Path | None,
    scope: str,
    model_selection: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if storage_root is None or not str(scope or "").strip():
        return [dict(item) for item in list(specs or []) if isinstance(item, dict)]
    provider, model = _provider_model_from_selection(model_selection)
    result: list[dict[str, Any]] = []
    for raw_spec in list(specs or []):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        candidate = _followup_provider_visible_candidate_source_spec(spec)
        if not candidate:
            result.append(spec)
            continue
        result.append(
            provider_visible_append_candidate_spec(
                candidate,
                storage_root=storage_root,
                scope=scope,
                provider=provider,
                model=model,
                adapter_contract=PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
            )
        )
    return result


def _followup_provider_visible_candidate_source_spec(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    kind = str(payload.get("kind") or "").strip()
    metadata = dict(payload.get("metadata") or {})
    if kind in {"accumulated_context_boundary"}:
        return {}
    if not _followup_provider_visible_message_from_spec(payload):
        return {}
    policy = context_segment_policy_for_spec(payload)
    replay_policy = str(metadata.get("context_replay_policy") or getattr(policy, "replay_policy", "") or "").strip()
    if policy.section == DYNAMIC_TAIL or replay_policy == "current_dynamic_tail_only":
        return {}
    if policy.section == STATIC_PREFIX:
        return {}
    if _is_followup_provider_visible_replayed_prefix(policy=policy, metadata=metadata):
        return {}
    if _is_followup_provider_visible_current_append(policy=policy, metadata=metadata):
        return payload
    if not _is_followup_provider_visible_append_only_kind(kind, payload):
        return {}
    metadata = {
        **metadata,
        "context_cache_section": CONTEXT_APPEND,
        "fixed_context_package": "context_memory_append",
        "context_commit_policy": "append_then_seal",
        "context_replay_policy": "current_append_commit_on_provider_success_then_next_physical_prefix_frame",
        "context_identity_policy": "origin_ref_stable",
        "context_origin_authority": "harness.loop.single_agent_turn.followup_provider_visible_commit_candidate",
        "context_origin_ref": str(
            metadata.get("context_origin_ref")
            or metadata.get("prefix_origin_ref")
            or metadata.get("origin_ref")
            or metadata.get("stable_origin_ref")
            or payload.get("source_ref")
            or kind
            or ""
        ).strip(),
        "semantic_commit_class": _followup_provider_visible_replay_only_class(kind),
        "provider_visible_replay_only": True,
        "context_memory_visible": False,
        "context_memory_commit_policy": "never_commit",
        "provider_visible_history_authority": "harness.loop.single_agent_turn.followup_provider_visible_commit_candidate",
    }
    candidate = {
        **payload,
        "cache_scope": "session",
        "cache_role": "session_stable",
        "prefix_tier": "session",
        "compression_role": str(payload.get("compression_role") or "preserve"),
        "metadata": metadata,
    }
    policy = context_segment_policy_for_spec(candidate, default_section=CONTEXT_APPEND)
    candidate["metadata"] = {
        **metadata,
        **context_segment_policy_metadata(policy),
        "semantic_commit_class": metadata["semantic_commit_class"],
        "provider_visible_replay_only": True,
        "context_memory_visible": False,
        "context_memory_commit_policy": "never_commit",
    }
    return candidate


def _is_followup_provider_visible_replayed_prefix(
    *,
    policy: Any,
    metadata: dict[str, Any],
) -> bool:
    if str(getattr(policy, "section", "") or "") == CONTEXT_MEMORY_PREFIX:
        return True
    commit_policy = str(metadata.get("context_commit_policy") or getattr(policy, "commit_policy", "") or "").strip()
    replay_policy = str(metadata.get("context_replay_policy") or getattr(policy, "replay_policy", "") or "").strip()
    payload_authority = str(metadata.get("provider_visible_payload_authority") or "").strip()
    history_status = str(metadata.get("provider_visible_history_status") or "").strip()
    if commit_policy.startswith("replay_only"):
        return True
    if replay_policy == PHYSICAL_PREFIX_FRAME_REPLAY_POLICY:
        return True
    if payload_authority == PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY:
        return True
    return history_status in {PHYSICAL_PREFIX_FRAME_REPLAY_STATUS, "static_context"}


def _is_followup_provider_visible_current_append(
    *,
    policy: Any,
    metadata: dict[str, Any],
) -> bool:
    if str(getattr(policy, "section", "") or "") != CONTEXT_APPEND:
        return False
    commit_policy = str(metadata.get("context_commit_policy") or getattr(policy, "commit_policy", "") or "").strip()
    history_status = str(metadata.get("provider_visible_history_status") or "").strip()
    commit_stage = str(metadata.get("provider_visible_append_commit_stage") or "").strip()
    if commit_stage == "provider_success_required":
        return True
    if history_status == "current_tool_round_pending_provider_success":
        return True
    return commit_policy == "append_then_seal"


def _is_followup_provider_visible_append_only_kind(kind: str, spec: dict[str, Any]) -> bool:
    if kind in {
        "single_agent_turn_tool_call",
        TOOL_TRANSCRIPT_DELTA_KIND,
        "single_agent_turn_user_steer_context",
    }:
        return True
    role = str(dict(spec or {}).get("role") or "")
    if role == "tool":
        return True
    if role == "assistant" and dict(spec or {}).get("tool_calls"):
        return True
    return False


def _followup_provider_visible_replay_only_class(kind: str) -> str:
    if kind == "single_agent_turn_followup_action_contract":
        return "provider_visible_replay_only_followup_action_contract"
    if is_current_tool_transcript_kind(kind):
        return "provider_visible_replay_only_tool_transcript"
    if kind == "single_agent_turn_user_steer_context":
        return "provider_visible_replay_only_user_steer"
    return "provider_visible_replay_only_followup_context"


def _provider_model_from_selection(model_selection: dict[str, Any] | None) -> tuple[str, str]:
    selection = dict(model_selection or {})
    return (
        str(selection.get("provider") or selection.get("llm_provider") or "").strip(),
        str(selection.get("model") or selection.get("llm_model") or "").strip(),
    )


def _with_provider_payload_hashes(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_spec in list(specs or []):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        message = dict(spec.get("model_message") or {})
        if not message:
            message = {
                "role": str(spec.get("role") or "user"),
                "content": str(spec.get("content") or ""),
            }
        provider_messages = provider_message_payloads([message])
        provider_message = dict(provider_messages[0]) if provider_messages else message
        metadata = {
            **dict(spec.get("metadata") or {}),
            "provider_payload_hash": _stable_payload_hash(provider_message),
            "provider_payload_hash_authority": "harness.loop.single_agent_turn.followup_prompt_payload",
        }
        spec["role"] = str(provider_message.get("role") or spec.get("role") or "user")
        spec["content"] = str(provider_message.get("content") if provider_message.get("content") is not None else "")
        spec["model_message"] = provider_message
        spec["metadata"] = metadata
        result.append(spec)
    return result


def _single_agent_followup_prefix_lock_report(
    *,
    base_segment_plan: dict[str, Any],
    model_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    report = build_prefix_lock_report(
        base_segment_plan=base_segment_plan,
        model_messages=model_messages,
    )
    violations = [dict(item) for item in list(dict(report or {}).get("violations") or []) if isinstance(item, dict)]
    if not violations:
        return dict(report or {})
    base_segments = _segment_plan_segments_by_message_index(dict(base_segment_plan or {}))
    hard_violations: list[dict[str, Any]] = []
    suppressed_violations: list[dict[str, Any]] = []
    for violation in violations:
        index = _safe_int_value(violation.get("model_message_index"))
        base = dict(base_segments.get(index) or {})
        if _is_tool_followup_current_dynamic_tail_segment(base):
            metadata = dict(base.get("metadata") or {})
            suppressed_violations.append(
                {
                    **violation,
                    "suppressed_reason": "dynamic_tail_index_shift_after_current_append",
                    "base_context_cache_section": str(metadata.get("context_cache_section") or ""),
                    "base_physical_prefix_lane": str(metadata.get("physical_prefix_lane") or ""),
                    "base_replay_policy": str(metadata.get("context_replay_policy") or ""),
                }
            )
            continue
        hard_violations.append(violation)
    if not hard_violations:
        return {
            **dict(report or {}),
            "status": "preserved",
            "violation_count": 0,
            "violations": [],
            "suppressed_violation_count": len(suppressed_violations),
            "suppressed_violations": suppressed_violations[:20],
            "authority": "harness.loop.single_agent_turn.followup_prefix_lock",
            "authority_scope": "sealed_prefix_only_dynamic_tail_shift_is_diagnostic",
        }
    return {
        **dict(report or {}),
        "status": "violated",
        "violation_count": len(hard_violations),
        "violations": hard_violations[:20],
        "suppressed_violation_count": len(suppressed_violations),
        "suppressed_violations": suppressed_violations[:20],
        "authority": "harness.loop.single_agent_turn.followup_prefix_lock",
        "authority_scope": "sealed_prefix_only_dynamic_tail_shift_is_diagnostic",
    }


def _annotate_single_agent_followup_segment_plan(
    segment_plan: dict[str, Any],
    *,
    packet_id: str,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    payload = dict(segment_plan or {})
    segments = [dict(item) for item in list(payload.get("segments") or []) if isinstance(item, dict)]
    if not segments:
        return payload
    ledger_metadata_by_ordinal = _provider_visible_metadata_by_followup_ordinal(message_specs)
    provider_messages_by_ordinal = _followup_provider_visible_messages_by_ordinal(message_specs)
    annotated_segments: list[dict[str, Any]] = []
    for segment in segments:
        metadata = dict(segment.get("metadata") or {})
        policy = context_segment_policy_for_spec(segment)
        metadata = {
            **metadata,
            **context_segment_policy_metadata(policy),
            "context_contract_mapping_authority": "runtime.context_management.context_segment_policy",
        }
        if not _is_followup_sealable_segment(segment):
            segment["metadata"] = metadata
            annotated_segments.append(segment)
            continue
        provider_visible_message = provider_messages_by_ordinal.get(_safe_int_value(segment.get("ordinal")), {})
        provider_visible_hash = (
            _stable_payload_hash(provider_visible_message)
            if provider_visible_message
            else str(segment.get("model_message_hash") or segment.get("content_hash") or "")
        )
        ordinal = _safe_int_value(segment.get("ordinal"))
        ledger_metadata = dict(ledger_metadata_by_ordinal.get(ordinal) or {})
        segment["metadata"] = {
            **metadata,
            **ledger_metadata,
            "provider_visible_context_authority": _provider_visible_manifest_segment_authority(ledger_metadata),
            "provider_visible_context_stage": _provider_visible_manifest_segment_stage(ledger_metadata),
            "provider_visible_context_packet_ref": str(packet_id or ""),
            "provider_visible_hash": provider_visible_hash,
        }
        annotated_segments.append(segment)
    payload["segments"] = annotated_segments
    return payload


def _provider_visible_metadata_by_followup_ordinal(
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for ordinal, raw_spec in enumerate(list(message_specs or []), start=1):
        if not isinstance(raw_spec, dict):
            continue
        metadata = dict(raw_spec.get("metadata") or {})
        provider_keys = {
            key: value
            for key, value in metadata.items()
            if str(key).startswith("provider_visible_append_ledger_")
            or str(key) in {"provider_visible_hash", "provider_visible_payload_form", "provider_visible_payload_authority"}
        }
        if provider_keys:
            result[int(ordinal or 0)] = provider_keys
    return result


def _provider_visible_manifest_segment_authority(metadata: dict[str, Any]) -> str:
    payload_authority = str(dict(metadata or {}).get("provider_visible_payload_authority") or "").strip()
    if payload_authority == PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY:
        return "runtime.context_management.physical_context_assembler"
    return "runtime.context_management.provider_visible_append_ledger"


def _provider_visible_manifest_segment_stage(metadata: dict[str, Any]) -> str:
    payload_authority = str(dict(metadata or {}).get("provider_visible_payload_authority") or "").strip()
    if payload_authority == PHYSICAL_PREFIX_FRAME_REPLAY_AUTHORITY:
        return PHYSICAL_PREFIX_FRAME_REPLAY_POLICY
    commit_stage = str(dict(metadata or {}).get("provider_visible_append_commit_stage") or "").strip()
    if commit_stage == "provider_success_required":
        return "current_append_pending_provider_success"
    return "provider_visible_append_candidate"


def _followup_provider_visible_messages_by_ordinal(
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for ordinal, raw_spec in enumerate(list(message_specs or []), start=1):
        spec = dict(raw_spec or {})
        message = _followup_provider_visible_message_from_spec(spec)
        if message:
            result[ordinal] = message
    return result


def _followup_provider_visible_message_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    raw_message = spec.get("model_message") if isinstance(spec.get("model_message"), dict) else {}
    message = dict(raw_message or {})
    if not message:
        message = {
            "role": str(spec.get("role") or "user"),
            "content": str(spec.get("content") or ""),
        }
    provider_messages = provider_message_payloads([message])
    return dict(provider_messages[0]) if provider_messages else {}


def _is_followup_sealable_segment(segment: dict[str, Any]) -> bool:
    return context_segment_is_provider_visible_sealable_spec(dict(segment or {}))


def _safe_int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _runtime_context_segment_tag(message: dict[str, Any]) -> dict[str, Any]:
    payload = dict(message or {})
    metadata = (
        dict(payload.get(_RUNTIME_CONTEXT_SEGMENT_METADATA_KEY) or {})
        if isinstance(payload.get(_RUNTIME_CONTEXT_SEGMENT_METADATA_KEY), dict)
        else {}
    )
    kind = str(payload.get(_RUNTIME_CONTEXT_SEGMENT_KIND_KEY) or "").strip()
    source_ref = str(payload.get(_RUNTIME_CONTEXT_SEGMENT_SOURCE_REF_KEY) or payload.get("source_ref") or "").strip()
    if not kind and str(metadata.get("context_segment_kind") or "").strip():
        kind = str(metadata.get("context_segment_kind") or "").strip()
    if not source_ref and str(metadata.get("context_segment_source_ref") or "").strip():
        source_ref = str(metadata.get("context_segment_source_ref") or "").strip()
    return {"kind": kind, "source_ref": source_ref, "metadata": metadata}


def _runtime_context_tag_is_control_tail(message: dict[str, Any]) -> bool:
    tag = _runtime_context_segment_tag(message)
    return str(tag.get("kind") or "").strip() in {
        "runtime_control_signal_tail",
        "single_agent_turn_followup_action_contract",
        "single_agent_turn_followup_message",
    }


def _is_tool_followup_action_contract_message(message: dict[str, Any]) -> bool:
    payload = dict(message or {})
    tag = _runtime_context_segment_tag(payload)
    if str(tag.get("kind") or "") == "single_agent_turn_followup_action_contract":
        return True
    if str(tag.get("source_ref") or "") == "single_agent_turn_tool_followup_action_contract":
        return True
    if str(payload.get("source_ref") or "") == "single_agent_turn_tool_followup_action_contract":
        return True
    content = str(payload.get("content") or "")
    return "你是正在根据刚才工具观察决定下一步的 coding agent。" in content


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
    return _split_append_only_context_and_dynamic_tail(
        [dict(item) for item in list(messages or []) if isinstance(item, dict) and item],
        segment_plan=segment_plan,
    )


def _ordered_tool_followup_prompt_messages(
    messages: list[dict[str, Any]],
    *,
    segment_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    accumulated, dynamic_tail = _split_append_only_context_and_dynamic_tail(
        [dict(item) for item in list(messages or []) if isinstance(item, dict) and item],
        segment_plan=segment_plan,
    )
    return [*accumulated, *dynamic_tail]


def _append_tool_transcript_to_accumulated_context(
    messages: list[dict[str, Any]],
    new_tool_transcript_messages: list[dict[str, Any]],
    *,
    segment_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return _append_messages_to_accumulated_context(
        messages,
        new_tool_transcript_messages,
        segment_plan=segment_plan,
    )


def _append_messages_to_accumulated_context(
    messages: list[dict[str, Any]],
    new_messages: list[dict[str, Any]],
    *,
    segment_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    accumulated, dynamic_tail = _split_append_only_context_and_dynamic_tail(messages, segment_plan=segment_plan)
    clean_new_messages = [
        dict(item)
        for item in list(new_messages or [])
        if isinstance(item, dict) and item
    ]
    return [*accumulated, *clean_new_messages, *dynamic_tail]


def _split_append_only_context_and_dynamic_tail(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    segment_plan: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clean_messages = _copy_model_messages_without_rewriting(messages)
    if not clean_messages or not _has_physical_dynamic_tail_segments(segment_plan):
        return clean_messages, []
    segments_by_index = _segment_plan_segments_by_message_index(dict(segment_plan or {}))
    dynamic_tail_segments_by_hash = _dynamic_tail_segments_by_hash(dict(segment_plan or {}))
    accumulated: list[dict[str, Any]] = []
    dynamic_tail: list[dict[str, Any]] = []
    for index, message in enumerate(clean_messages):
        segment = dict(segments_by_index.get(index) or {})
        if segment and _followup_base_segment_conflicts_with_message_shape(segment, message):
            segment = {}
        if not segment:
            segment = _pop_matching_dynamic_tail_segment(dynamic_tail_segments_by_hash, message=message)
        if (segment and _is_tool_followup_current_dynamic_tail_segment(segment)) or (
            not segment and _is_current_control_tail_message(message)
        ):
            dynamic_tail.append(message)
            continue
        accumulated.append(message)
    return accumulated, dynamic_tail


def _has_physical_dynamic_tail_segments(segment_plan: dict[str, Any] | None) -> bool:
    for segment in list(dict(segment_plan or {}).get("segments") or []):
        if not isinstance(segment, dict):
            continue
        if _is_tool_followup_current_dynamic_tail_segment(segment):
            return True
    return False


def _with_followup_context_physical_diagnostics(
    segment_plan: dict[str, Any],
    *,
    base_segment_plan: dict[str, Any],
    physical_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(segment_plan or {})
    inherited = _context_physical_diagnostics_from_segment_plan(base_segment_plan)
    current_plan = dict(physical_plan or {})
    if not inherited and not current_plan:
        return payload
    diagnostics = {
        **dict(payload.get("diagnostics") or {}),
        **inherited,
        **(
            {
                "physical_context_plan": current_plan,
                "physical_context_plan_ref": str(current_plan.get("plan_id") or ""),
                "cache_spine_hash": str(current_plan.get("cache_spine_hash") or ""),
                "cache_spine_generation": str(current_plan.get("cache_spine_generation") or ""),
                "physical_prefix_lane_order": list(current_plan.get("lane_order") or []),
                "physical_prefix_lane_counts": dict(current_plan.get("lane_counts") or {}),
            }
            if current_plan
            else {}
        ),
        "context_physical_inherited_from_base_segment_plan": True,
    }
    payload["diagnostics"] = diagnostics
    return payload


def _context_physical_diagnostics_from_segment_plan(segment_plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = dict(segment_plan or {})
    result: dict[str, Any] = {}
    lane_counts: dict[str, int] = {}
    lane_order: list[str] = []
    physical_plan_ref = ""
    cache_spine_hash = ""
    cache_spine_generation = ""
    for segment in list(plan.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        metadata = dict(segment.get("metadata") or {})
        lane = str(metadata.get("physical_prefix_lane") or "").strip()
        if lane:
            lane_counts[lane] = lane_counts.get(lane, 0) + 1
            if lane not in lane_order:
                lane_order.append(lane)
        if not physical_plan_ref:
            physical_plan_ref = str(metadata.get("physical_context_plan_ref") or "")
        if not cache_spine_hash:
            cache_spine_hash = str(metadata.get("cache_spine_hash") or "")
        if not cache_spine_generation:
            cache_spine_generation = str(metadata.get("cache_spine_generation") or "")
    if lane_counts:
        result["base_physical_prefix_lane_counts"] = lane_counts
        result["base_physical_prefix_lane_order"] = lane_order
    if physical_plan_ref:
        result["base_physical_context_plan_ref"] = physical_plan_ref
    if cache_spine_hash:
        result["base_cache_spine_hash"] = cache_spine_hash
    if cache_spine_generation:
        result["base_cache_spine_generation"] = cache_spine_generation
    return result


def _is_current_control_tail_message(message: dict[str, Any]) -> bool:
    return (
        _runtime_context_tag_is_control_tail(message)
        or _is_tool_followup_action_contract_message(message)
        or _is_tool_followup_context_boundary_message(message)
        or _is_runtime_control_signal_recovery_message(message)
        or _is_agent_authored_closeout_message(message)
        or _is_admission_repair_message(message)
    )


def _is_runtime_control_signal_recovery_message(message: dict[str, Any]) -> bool:
    tag = _runtime_context_segment_tag(message)
    if str(tag.get("kind") or "") == "runtime_control_signal_tail" and "runtime_control_recovery" in str(tag.get("source_ref") or ""):
        return True
    content = str(dict(message or {}).get("content") or "")
    return "请根据以下事实选择下一步动作。" in content and "allowed_action_types" in content


def _is_agent_authored_closeout_message(message: dict[str, Any]) -> bool:
    tag = _runtime_context_segment_tag(message)
    if str(tag.get("kind") or "") == "runtime_control_signal_tail" and "agent_authored_closeout" in str(tag.get("source_ref") or ""):
        return True
    content = str(dict(message or {}).get("content") or "")
    return (
        "你是一名正在收口的 coding agent。" in content
        or "你是一名需要向用户说明当前阶段结果的 coding agent。" in content
    )


def _is_admission_repair_message(message: dict[str, Any]) -> bool:
    tag = _runtime_context_segment_tag(message)
    if str(tag.get("kind") or "") == "runtime_control_signal_tail" and "admission_repair" in str(tag.get("source_ref") or ""):
        return True
    content = str(dict(message or {}).get("content") or "")
    return "修复输入：" in content and "rejected_action_request" in content and "admission" in content


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
    metadata = dict(dict(segment or {}).get("metadata") or {})
    if str(metadata.get("physical_prefix_lane") or "").strip() == NEVER_REPLAY_TAIL:
        return True
    return context_segment_routes_to_dynamic_tail(dict(segment or {}))


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
    return accumulated


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
    seal_provider_visible_history: bool = True,
    packet_id: str = "",
) -> dict[str, Any]:
    metadata = dict(base.get("metadata") or {})
    kind = str(base.get("kind") or "single_agent_turn_base")
    cache_scope = str(base.get("cache_scope") or "none")
    cache_role = str(base.get("cache_role") or "volatile")
    prefix_tier = str(base.get("prefix_tier") or "volatile")
    if seal_provider_visible_history:
        sealed = (
            current_followup_append_context_policy(
                base,
                message=message,
                metadata=metadata,
            )
            if is_current_tool_round
            else provider_protocol_prefix_replay_policy(
                base,
                message=message,
                metadata=metadata,
            )
        )
        cache_scope = str(sealed.get("cache_scope") or cache_scope)
        cache_role = str(sealed.get("cache_role") or cache_role)
        prefix_tier = str(sealed.get("prefix_tier") or prefix_tier)
        kind = str(sealed.get("kind") or kind)
        metadata = dict(sealed.get("metadata") or metadata)
    if prefix_lock_violation:
        metadata = {
            **metadata,
            "prefix_lock_status": "violated",
            "prefix_lock_violation": dict(prefix_lock_violation),
            "prefix_lock_authority": "diagnostic_only",
            "prefix_lock_cache_policy": "preserve_context_segment_policy_classification",
        }
    if _is_tool_followup_current_dynamic_tail_segment(base):
        metadata = {
            **metadata,
            "context_cache_section": DYNAMIC_TAIL,
            "context_prefix_cache_scope": "none",
            "context_prefix_cache_role": "volatile",
            "context_prefix_tier": "volatile",
            "context_commit_policy": "never_commit",
            "context_replay_policy": "current_dynamic_tail_only",
            "semantic_commit_class": "current_runtime_control",
            "cache_impact": "current_dynamic_tail_only",
            "stability_rule": "previous runtime-control tail text is current-control context only and must not be sealed into provider-visible history",
            "cache_policy_rebased": "physical_context_assembler_current_dynamic_tail",
        }
    else:
        metadata = {
            **metadata,
            "cache_policy_rebased": "physical_context_assembler_current_message_annotation",
        }
    result = {
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
    return result


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
    runtime_tag = _runtime_context_segment_tag(message)
    runtime_tag_kind = str(runtime_tag.get("kind") or "").strip()
    runtime_tag_source_ref = str(runtime_tag.get("source_ref") or "").strip()
    runtime_tag_metadata = (
        dict(runtime_tag.get("metadata") or {})
        if isinstance(runtime_tag.get("metadata"), dict)
        else {}
    )
    is_action_contract = _is_tool_followup_action_contract_message(message)
    is_runtime_control_tail = _is_current_control_tail_message(message)
    if is_action_contract:
        kind = "single_agent_turn_followup_action_contract"
        source_ref = f"single_agent_turn.followup_action_contract:{tool_iteration}"
        compression_role = "preserve"
    elif runtime_tag_kind == "runtime_control_signal_tail":
        kind = "runtime_control_signal_tail"
        tag_role = str(runtime_tag_metadata.get("runtime_control_role") or "").strip()
        if runtime_tag_source_ref:
            source_prefix = runtime_tag_source_ref
        elif tag_role:
            source_prefix = f"single_agent_turn.{tag_role}"
        else:
            source_prefix = "single_agent_turn.runtime_control_tail"
        source_ref = f"{source_prefix}:{tool_iteration}"
        compression_role = "preserve"
    elif _is_runtime_control_signal_recovery_message(message):
        kind = "runtime_control_signal_tail"
        source_ref = f"single_agent_turn.runtime_control_recovery:{tool_iteration}"
        compression_role = "preserve"
    elif _is_agent_authored_closeout_message(message):
        kind = "runtime_control_signal_tail"
        source_ref = f"single_agent_turn.agent_authored_closeout:{tool_iteration}"
        compression_role = "preserve"
    elif _is_admission_repair_message(message):
        kind = "runtime_control_signal_tail"
        source_ref = f"single_agent_turn.admission_repair:{tool_iteration}"
        compression_role = "preserve"
    elif role == "assistant" and message.get("tool_calls"):
        kind = "single_agent_turn_tool_call"
        source_ref = _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_call")
        compression_role = "preserve"
    elif role == "tool":
        kind = TOOL_TRANSCRIPT_DELTA_KIND
        source_ref = _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_transcript")
        compression_role = "summarize"
    elif _is_active_turn_user_steer_message(message):
        kind = "single_agent_turn_user_steer_context"
        source_ref = _active_turn_user_steer_source_ref(message, tool_iteration=tool_iteration)
        compression_role = "preserve"
    else:
        kind = "single_agent_turn_followup_message"
        source_ref = f"single_agent_turn.followup:{tool_iteration}"
        compression_role = "summarize"
    cache_scope = "none"
    cache_role = "volatile"
    prefix_tier = "volatile"
    metadata = {
        **runtime_tag_metadata,
        "followup_iteration": max(1, int(tool_iteration or 1)),
    }
    if runtime_tag_source_ref:
        metadata["runtime_context_segment_source_ref"] = runtime_tag_source_ref
    if is_runtime_control_tail:
        metadata.update(
            {
                "context_cache_section": DYNAMIC_TAIL,
                "context_prefix_cache_scope": "none",
                "context_prefix_cache_role": "volatile",
                "context_prefix_tier": "volatile",
                "context_commit_policy": "never_commit",
                "context_replay_policy": "current_dynamic_tail_only",
                "semantic_commit_class": "current_runtime_control",
                "cache_impact": "current_dynamic_tail_only",
                "stability_rule": (
                    "current invocation control is appended only for this provider request; "
                    "it must not be sealed into provider-visible history"
                ),
                "volatility_reason": "runtime control tail can change before it is sent in the current model call",
            }
        )
    elif is_current_tool_transcript_kind(kind):
        metadata.update(
            {
                "context_cache_section": CONTEXT_APPEND,
                "fixed_context_package": "context_memory_append",
                "context_semantic_slot": "tool_transcript",
                "context_prefix_cache_scope": "none",
                "context_prefix_cache_role": "volatile",
                "context_prefix_tier": "volatile",
                "context_commit_policy": "append_then_seal",
                "context_replay_policy": "current_append_commit_on_provider_success_then_next_physical_prefix_frame",
                "context_identity_policy": "origin_ref_stable",
                "context_origin_authority": "harness.loop.single_agent_turn.followup_tool_transcript",
                "context_origin_ref": source_ref,
                "semantic_commit_class": "tool_transcript",
                "provider_visible_history_status": "current_tool_round_pending_provider_success",
                "provider_visible_history_authority": "harness.loop.single_agent_turn.followup_tool_transcript",
                "provider_visible_history_model_message_hash": stable_model_message_hash(dict(message or {})),
                "cache_impact": "current_tool_transcript_append_promotes_to_next_prefix",
                "stability_rule": (
                    "current tool transcript is provider-visible in this follow-up request; "
                    "after provider success it is sealed into the next physical prefix frame"
                ),
                "volatility_reason": "current tool round transcript is new append content before provider success",
            }
        )
    elif kind == "single_agent_turn_user_steer_context":
        metadata.update(
            {
                "context_cache_section": CONTEXT_APPEND,
                "fixed_context_package": "context_memory_append",
                "context_semantic_slot": "active_user_steer_content",
                "context_prefix_cache_scope": "none",
                "context_prefix_cache_role": "volatile",
                "context_prefix_tier": "volatile",
                "context_commit_policy": "append_then_seal",
                "context_replay_policy": "current_append_commit_on_provider_success_then_next_physical_prefix_frame",
                "context_identity_policy": "origin_ref_stable",
                "context_origin_authority": "harness.loop.single_agent_turn.followup_user_steer",
                "context_origin_ref": source_ref,
                "semantic_commit_class": "current_user_context",
                "provider_visible_history_status": "current_user_context_pending_provider_success",
                "provider_visible_history_authority": "harness.loop.single_agent_turn.followup_user_steer",
                "provider_visible_history_model_message_hash": stable_model_message_hash(dict(message or {})),
                "cache_impact": "current_user_steer_append_promotes_to_next_prefix",
                "stability_rule": (
                    "active user steering is provider-visible current-turn content; "
                    "after provider success it is sealed for exact ledger replay"
                ),
                "volatility_reason": "active user steering is new append content before provider success",
            }
        )
    else:
        metadata.update(
            {
                "context_cache_section": DYNAMIC_TAIL,
                "context_prefix_cache_scope": "none",
                "context_prefix_cache_role": "volatile",
                "context_prefix_tier": "volatile",
                "context_commit_policy": "never_commit",
                "context_replay_policy": "current_dynamic_tail_only",
                "semantic_commit_class": "current_runtime_control",
                "cache_impact": "current_dynamic_tail_only",
                "stability_rule": "unclassified follow-up prompt text is current invocation control and must not be sealed into provider-visible history",
                "volatility_reason": "unclassified follow-up prompt text is invocation-local",
            }
        )
    if is_current_tool_transcript_kind(kind):
        metadata.update(
            {
                "canonical_kind": kind,
                "source_route": "single_agent_turn_followup",
            }
        )
    metadata["cache_policy_rebased"] = "physical_context_assembler_current_message_annotation"
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
        return not (
            is_tool_transcript_kind(kind, include_historical=True)
            or kind == "physical_prefix_frame_tool_transcript_replay"
        )
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


def _rebased_followup_source_ref(*, kind: str, message: dict[str, Any], fallback: str) -> str:
    if kind == "single_agent_turn_tool_call" or (
        str(message.get("role") or "") == "assistant" and message.get("tool_calls")
    ):
        return _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_call")
    if (
        is_tool_transcript_kind(kind, include_historical=True)
        or kind == "physical_prefix_frame_tool_transcript_replay"
        or str(message.get("role") or "") == "tool"
    ):
        return _followup_tool_message_source_ref(message, prefix="single_agent_turn.tool_transcript")
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
        "cache_scope": str(segment.get("cache_scope") or "session"),
        "cache_role": str(segment.get("cache_role") or "session_stable"),
        "prefix_tier": str(segment.get("prefix_tier") or "session"),
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
    provider_protocol_messages_to_append: list[dict[str, Any]] | None = None,
    main_context: dict[str, Any] | None = None,
) -> FinalMessageCommit:
    sanitized_protocol_messages = _sanitize_model_messages(
        [dict(item) for item in list(provider_protocol_messages_to_append or []) if isinstance(item, dict)],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.commit_provider_protocol_messages",
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
            "provider_protocol_messages_to_append": sanitized_protocol_messages,
            **({"main_context": dict(main_context or {})} if main_context else {}),
        },
    )
    _record_turn_memory_assistant_final(
        runtime_host,
        session_id=session_id,
        turn_id=turn_id,
        content=content,
        final_ref=f"assistant-final:{request.run_id}:{turn_id}",
    )
    result = await OutputCommitAuthority(runtime_host).commit_async(
        request,
        committer=commit_assistant_message,
    )
    _record_turn_memory_commit_result(
        runtime_host,
        session_id=session_id,
        turn_id=turn_id,
        receipt=dict(result.receipt or {}),
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


def _ensure_turn_memory_started(
    runtime_host: Any | None,
    *,
    session_id: str,
    turn_id: str,
    turn_run_id: str = "",
    branch_id: str = "",
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    create_or_get = getattr(store, "create_or_get_turn", None)
    if not callable(create_or_get):
        return
    try:
        create_or_get(
            session_id=session_id,
            turn_id=turn_id,
            turn_run_id=turn_run_id,
            branch_id=branch_id or session_id,
        )
    except Exception:
        logger.debug("failed to start turn memory", exc_info=True)


def _patch_turn_memory(
    runtime_host: Any | None,
    *,
    session_id: str,
    turn_id: str,
    **changes: Any,
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    patch = getattr(store, "patch_turn", None)
    if not callable(patch):
        return
    try:
        patch(session_id, turn_id, **changes)
    except Exception:
        logger.debug("failed to patch turn memory", exc_info=True)


def _record_turn_memory_assistant_final(
    runtime_host: Any | None,
    *,
    session_id: str,
    turn_id: str,
    content: str,
    final_ref: str,
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    create_or_get = getattr(store, "create_or_get_turn", None)
    recorder = getattr(store, "record_assistant_final", None)
    checkpoint = getattr(store, "record_checkpoint", None)
    if not callable(recorder):
        return
    try:
        if callable(create_or_get):
            create_or_get(session_id=session_id, turn_id=turn_id)
        recorder(
            session_id=session_id,
            turn_id=turn_id,
            text=content,
            final_ref=final_ref,
        )
        if callable(checkpoint):
            checkpoint(
                session_id=session_id,
                turn_id=turn_id,
                checkpoint_kind="assistant_final_ready",
                payload={
                    "assistant_final_ref": final_ref,
                    "assistant_final_sha256": _text_sha256(content),
                    "authority": "harness.loop.single_agent_turn.turn_memory_final",
                },
            )
    except Exception:
        logger.debug("failed to record assistant final in turn memory", exc_info=True)


def _record_turn_memory_commit_result(
    runtime_host: Any | None,
    *,
    session_id: str,
    turn_id: str,
    receipt: dict[str, Any],
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    recorder = getattr(store, "record_commit_result", None)
    checkpoint = getattr(store, "record_checkpoint", None)
    if not callable(recorder):
        return
    try:
        recorder(session_id=session_id, turn_id=turn_id, receipt=dict(receipt or {}))
        if callable(checkpoint):
            state = str(dict(receipt or {}).get("state") or dict(receipt or {}).get("status") or "unknown")
            checkpoint(
                session_id=session_id,
                turn_id=turn_id,
                checkpoint_kind=f"assistant_commit_{state}",
                payload={
                    "commit_state": state,
                    "session_commit_ref": str(dict(receipt or {}).get("anchor_message_id") or dict(receipt or {}).get("event_id") or ""),
                    "event_type": str(dict(receipt or {}).get("event_type") or ""),
                    "authority": "harness.loop.single_agent_turn.turn_memory_commit",
                },
            )
    except Exception:
        logger.debug("failed to record commit result in turn memory", exc_info=True)


def _record_turn_memory_tool_round(
    runtime_host: Any | None,
    *,
    session_id: str,
    turn_id: str,
    packet_ref: str,
    tool_batch_ref: str,
    tool_iteration: int,
    tool_calls: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    tool_context_entries: list[dict[str, Any]],
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    recorder = getattr(store, "record_tool_round", None)
    checkpoint = getattr(store, "record_checkpoint", None)
    if not callable(recorder):
        return
    observation_refs = tuple(
        str(item.get("observation_id") or item.get("observation_ref") or "")
        for item in list(observations or [])
        if isinstance(item, dict) and str(item.get("observation_id") or item.get("observation_ref") or "").strip()
    )
    tool_round = {
        "tool_round_ref": f"toolround:{tool_batch_ref}:{tool_iteration}",
        "tool_batch_ref": tool_batch_ref,
        "tool_iteration": tool_iteration,
        "packet_ref": packet_ref,
        "tool_calls": [dict(item) for item in list(tool_calls or []) if isinstance(item, dict)],
        "observations": [dict(item) for item in list(observations or []) if isinstance(item, dict)],
        "tool_context_entries": [dict(item) for item in list(tool_context_entries or []) if isinstance(item, dict)],
        "authority": "harness.loop.single_agent_turn.turn_memory_tool_round",
    }
    try:
        recorder(
            session_id=session_id,
            turn_id=turn_id,
            tool_round=tool_round,
            closed_tool_round_refs=observation_refs,
        )
        if callable(checkpoint):
            checkpoint(
                session_id=session_id,
                turn_id=turn_id,
                checkpoint_kind="tool_round_closed",
                payload={
                    "tool_round_ref": tool_round["tool_round_ref"],
                    "packet_ref": packet_ref,
                    "tool_iteration": tool_iteration,
                    "observation_refs": list(observation_refs),
                    "authority": "harness.loop.single_agent_turn.turn_memory_tool_round",
                },
            )
    except Exception:
        logger.debug("failed to record tool round in turn memory", exc_info=True)


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


def _record_model_action_public_feedback(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    packet_ref: str,
    action_request: ModelActionRequest,
    phase: str,
    tool_iteration: int,
) -> dict[str, Any]:
    values = _model_action_public_feedback_values(action_request)
    if not values:
        return {}
    public_progress_note = values.get("public_progress_note", "")
    current_judgment = values.get("current_judgment", "")
    next_action = values.get("next_action", "")
    presentation_source = _model_action_public_feedback_presentation_source(action_request, values)
    feedback_identity = _model_public_feedback_identity(
        packet_ref=packet_ref,
        tool_iteration=tool_iteration,
        tool_actions=[action_request],
    )
    payload = _drop_empty_dict(
        {
            "turn_id": turn_id,
            "active_turn_id": turn_id,
            "turn_run_id": turn_run.turn_run_id,
            "session_id": str(getattr(turn_run, "session_id", "") or ""),
            "message_id": assistant_message_ref(turn_id=turn_id),
            "message_ref": assistant_message_ref(turn_id=turn_id),
            "step": "model_action_public_feedback",
            "status": "running",
            "phase": str(phase or ""),
            "presentation_source": presentation_source,
            "feedback_identity": feedback_identity,
            "public_progress_note": public_progress_note,
            "current_judgment": current_judgment,
            "next_action": next_action,
            "completion_status": values.get("completion_status", ""),
        }
    )
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        payload=payload,
        refs={
            "turn_ref": turn_id,
            "turn_run_ref": turn_run.turn_run_id,
            "message_ref": assistant_message_ref(turn_id=turn_id),
            "runtime_invocation_packet_ref": packet_ref,
            "action_request_ref": action_request.request_id,
        },
    )
    visible_feedback = public_progress_note or current_judgment or next_action
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            diagnostics={
                **dict(current.diagnostics or {}),
                "latest_public_progress_note": visible_feedback,
                "latest_model_action_public_feedback_ref": feedback_identity,
            },
        )
    )
    return {
        "type": ASSISTANT_PUBLIC_FEEDBACK_EVENT,
        **payload,
        "runtime_event_id": str(event.event_id or ""),
        "event": event.to_dict(),
    }


def _record_model_action_public_feedback_events(
    runtime_host: Any | None,
    *,
    turn_run: TurnRun | None,
    turn_id: str,
    packet_ref: str,
    phase: str,
    tool_iteration: int,
    action_parse: SingleAgentActionParse,
    tool_actions: list[ModelActionRequest] | tuple[ModelActionRequest, ...] = (),
) -> list[dict[str, Any]]:
    if runtime_host is None or turn_run is None:
        return []
    events: list[dict[str, Any]] = []
    for action in _model_action_public_feedback_source_actions(action_parse, tool_actions):
        event = _record_model_action_public_feedback(
            runtime_host,
            turn_run=turn_run,
            turn_id=turn_id,
            packet_ref=packet_ref,
            action_request=action,
            phase=phase,
            tool_iteration=tool_iteration,
        )
        if event:
            events.append(event)
    return events


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
    _record_turn_memory_terminal(
        runtime_host,
        session_id=turn_run.session_id,
        turn_id=turn_id,
        status=status,
        terminal_reason=terminal_reason,
        terminal_event_ref=str(getattr(event, "event_id", "") or ""),
    )
    if status == "completed":
        _release_consumed_interrupted_turn_memory_packages(
            runtime_host,
            session_id=turn_run.session_id,
            consuming_turn_id=turn_id,
            terminal_event_ref=str(getattr(event, "event_id", "") or ""),
        )
    return event.to_dict()


def _record_turn_memory_terminal(
    runtime_host: Any | None,
    *,
    session_id: str,
    turn_id: str,
    status: str,
    terminal_reason: str,
    terminal_event_ref: str,
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    recorder = getattr(store, "record_terminal", None)
    checkpoint = getattr(store, "record_checkpoint", None)
    if not callable(recorder):
        return
    try:
        recorder(
            session_id=session_id,
            turn_id=turn_id,
            status=status,
            terminal_reason=terminal_reason,
            terminal_event_ref=terminal_event_ref,
        )
        if callable(checkpoint):
            checkpoint(
                session_id=session_id,
                turn_id=turn_id,
                checkpoint_kind="turn_terminal",
                payload={
                    "terminal_status": status,
                    "terminal_reason": terminal_reason,
                    "terminal_event_ref": terminal_event_ref,
                    "authority": "harness.loop.single_agent_turn.turn_memory_terminal",
                },
            )
    except Exception:
        logger.debug("failed to record terminal in turn memory", exc_info=True)


def _release_consumed_interrupted_turn_memory_packages(
    runtime_host: Any | None,
    *,
    session_id: str,
    consuming_turn_id: str,
    terminal_event_ref: str,
) -> None:
    store = getattr(runtime_host, "turn_memory_store", None)
    lister = getattr(store, "list_session_turns", None)
    releaser = getattr(store, "release_turn", None)
    checkpoint = getattr(store, "record_checkpoint", None)
    if not callable(lister) or not callable(releaser):
        return
    interruption_states = {
        "runtime_process_restarted",
        "runtime_cell_missing_after_restart",
        "runtime_cell_cancelled",
        "runtime_stream_interrupted",
        "stream_cancelled",
        "stream_exception",
        "missing_terminal_event",
        "projection_stream_exception",
        "projection_stream_missing_terminal",
        "task_bridge_context_missing",
    }
    try:
        records = list(lister(session_id, include_released=False) or [])
        for record in records:
            turn_id = str(getattr(record, "turn_id", "") or "").strip()
            if not turn_id or turn_id == str(consuming_turn_id or "").strip():
                continue
            if str(getattr(record, "status", "") or "") != "terminal":
                continue
            if str(getattr(record, "handoff_state", "") or "") != "interrupted_turn_memory_package":
                continue
            recovery_state = str(getattr(record, "recovery_state", "") or "").strip()
            if recovery_state not in interruption_states:
                continue
            if callable(checkpoint):
                checkpoint(
                    session_id=session_id,
                    turn_id=turn_id,
                    checkpoint_kind="interrupted_memory_package_consumed",
                    payload={
                        "consuming_turn_id": str(consuming_turn_id or ""),
                        "terminal_event_ref": str(terminal_event_ref or ""),
                        "authority": "harness.loop.single_agent_turn.turn_memory_interruption_package_release",
                    },
                )
            releaser(
                session_id=session_id,
                turn_id=turn_id,
                reason=f"interrupted_memory_package_consumed_by:{consuming_turn_id}",
            )
    except Exception:
        logger.debug("failed to release consumed interrupted turn memory packages", exc_info=True)


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
    if status in {"completed", "blocked", "failed", "aborted", "interrupted"}:
        return status
    return "failed"
