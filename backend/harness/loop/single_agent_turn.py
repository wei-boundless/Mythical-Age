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
from harness.loop.admission import AdmissionDecision, admit_model_action
from harness.loop.action_permit import action_permit_from_admission
from harness.loop.model_action_protocol import ModelActionRequest, model_action_request_from_payload
from harness.loop.model_action_runtime import call_model_invoker
from harness.loop.presentation import error_event, final_answer_event
from harness.runtime import RuntimeCompiler, ToolBatchGroup, build_runtime_tool_plan, build_tool_batch_plan
from harness.runtime.environment_storage import ensure_environment_storage_dirs
from harness.runtime.file_management_policy import compile_tool_file_management_policy
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.sandbox_artifacts import (
    logical_path_publish_allowed,
    publish_sandbox_artifact_refs,
    sandbox_publish_scopes,
)
from harness.runtime.sandbox_execution_scope import compile_sandbox_execution_scope
from runtime.cache_manager import DEFAULT_SANDBOX_CACHE_TTL_SECONDS, runtime_cache_manager_for_host
from runtime.prompt_accounting.serializer import normalize_messages
from runtime.prompt_accounting import ContextUsageMeter
from runtime.model_gateway.assistant_stream_frame import (
    assistant_final_stream_events,
    assistant_message_ref,
)
from runtime.model_gateway.assistant_stream_normalizer import AssistantStreamNormalizer
from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response
from runtime.model_gateway.protocol_sanitizer import sanitize_messages_for_prompt
from runtime.model_gateway.model_runtime import stringify_content
from runtime.output_boundary import (
    CanonicalFinalTextDecision,
    canonical_output_decision_for_final_text,
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from runtime.output_stream.public_contract import ASSISTANT_PUBLIC_FEEDBACK_EVENT
from runtime.shared.models import TurnRun
from runtime.shared.tool_identity import canonical_action_tool_call_id, permission_decision_id
from runtime.tool_runtime import ToolInvocationRequest, ToolObservation, build_round_tool_call_options, build_tool_invocation_id
from runtime.memory.file_evidence_scope import session_file_evidence_scope
from runtime.tool_runtime.provider_tool_call_adapter import tool_calls_for_langchain_messages
from orchestration.commit_gate import build_assistant_session_message_commit_decision
from permissions.policy import normalize_permission_mode
from prompt_library import SINGLE_AGENT_ADMISSION_REPAIR_PROMPT

from .turn_to_task_context_handoff import build_turn_to_task_context_handoff_seed


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest, dict[str, Any]], AsyncIterator[dict[str, Any]]]
ApplyActiveWorkControl = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
ApplyRecoverableWorkResume = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
CompactSessionContext = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]

_DEFAULT_SINGLE_TURN_TOOL_ITERATIONS = 16
_MAX_CONFIGURED_SINGLE_TURN_TOOL_ITERATIONS = 32
_DEFAULT_INTERACTIVE_TOOL_BATCH_TIMEOUT_SECONDS = 45.0
_TOOL_BATCH_CANCEL_DRAIN_SECONDS = 1.0


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
_TOOL_LIMIT_CLOSEOUT_SOURCE = "harness.single_agent_turn.tool_limit_closeout"
_AGENT_CLOSEOUT_SOURCE = "harness.single_agent_turn.agent_closeout"
_AGENT_CONTRACT_FEEDBACK_SOURCE = "harness.single_agent_turn.agent_contract_feedback"
_ASSISTANT_CONTENT_PREAMBLE_PROGRESS_SOURCE = "model_action.assistant_content_preamble"
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
_CONTROL_ACTION_ALIASES = {
    "task_run_request": "request_task_run",
}
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


def _looks_like_structured_closeout_payload(content: str) -> bool:
    parsed = _structured_closeout_payload(content)
    if isinstance(parsed, dict):
        keys = {str(key) for key in parsed.keys()}
        return bool(keys & {"authority", "action_type", "tool_call", "tool_calls", "active_work_control", "recovery_resume"})
    return isinstance(parsed, list) and any(isinstance(item, dict) for item in parsed)


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


def _tool_limit_closeout_messages(
    model_messages: list[dict[str, Any]],
    *,
    turn_id: str,
    control_signal: dict[str, Any],
) -> list[dict[str, Any]]:
    closeout_payload = {
        "runtime_control_signal": dict(control_signal or {}),
        "required_action_protocol": {
            "authority": "harness.loop.model_action_request",
            "allowed_action_types": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
            "tool_call_allowed": False,
            "json_only": True,
        },
    }
    instruction = (
        "系统运行控制观察如下。它不是最终回复，而是交给你的收口信号。\n"
        f"{json.dumps(closeout_payload, ensure_ascii=False, sort_keys=True)}\n\n"
        "你现在是本轮收口负责人。你不能再调用工具，不能输出 provider-native tool_calls，"
        "也不能在 JSON 外输出正文。\n"
        "你只能输出一个 JSON action，authority 必须是 harness.loop.model_action_request，"
        "action_type 只能是 respond、ask_user 或 block。\n"
        "如果当前事实足以告知用户进展或结果，选择 respond 并填写 final_answer。\n"
        "如果任务还没完成但需要用户决定是否继续，选择 ask_user 并填写 user_question。\n"
        "如果当前事实不足以可靠继续或可靠总结，选择 block 并填写 blocking_reason。"
    )
    return _sanitize_model_messages(
        [
            *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
            {"role": "system", "content": instruction, "turn_id": turn_id},
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.tool_limit_closeout",
    )


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
    code = str(protocol_error.get("code") or "single_agent_turn_model_protocol_error")
    reason = str(protocol_error.get("reason") or code)
    specific_repair = _protocol_error_specific_repair_instruction(protocol_error)
    instruction = (
        "上一轮模型动作没有通过运行时动作合同校验。系统没有执行该动作。"
        "你必须先吸收这条运行控制观察，再重新选择一个合法动作。"
        "只能输出一个 JSON action；不要使用 Markdown 代码块；不要在 JSON 前后附加解释文字。"
    )
    if specific_repair:
        instruction += f"具体修复：{specific_repair}"
    if public_response_required:
        instruction += (
            "本次仍处在公开反馈义务内；如果继续请求工具，必须写入 public_progress_note "
            "或 public_action_state.current_judgment，说明已确认事实、影响和下一步。"
        )
    if not tool_calls_allowed:
        instruction += "当前阶段不允许继续调用工具；只能选择 respond、ask_user 或 block 收口。"
    return {
        "observation_type": "runtime_control_signal",
        "source": "system:runtime_control_signal",
        "signal_kind": "model_protocol_violation",
        "runtime_control_state": "model_action_recovery_required",
        "turn_id": turn_id,
        "packet_ref": packet_ref,
        "phase": phase,
        "recovery_attempt": int(recovery_attempt or 0),
        "max_recovery_attempts": int(max_recovery_attempts or 0),
        "agent_closeout_required": not tool_calls_allowed,
        "allowed_agent_actions": allowed,
        "tool_calls_allowed_after_signal": bool(tool_calls_allowed),
        "public_response_required": bool(public_response_required),
        "protocol_error": dict(protocol_error or {}),
        "previous_response_preview": _compact_text(response_preview, limit=1200),
        "repair_instruction": instruction,
        "structured_signal": {
            "code": code,
            "message": instruction,
            "reason": reason,
            "origin": "single_agent_turn_model_protocol_boundary",
            "retryable": int(recovery_attempt or 0) < int(max_recovery_attempts or 0),
        },
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
        "不要泄露内部协议、动作 JSON、tool_calls 或提交门禁字段。"
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
) -> list[dict[str, Any]]:
    payload = {
        "runtime_control_signal": dict(control_signal or {}),
        "required_action_protocol": {
            "authority": "harness.loop.model_action_request",
            "allowed_action_types": [str(item) for item in list(allowed_action_types or ()) if str(item)],
            "tool_call_allowed": "tool_call" in set(allowed_action_types or ()),
            "json_only": True,
        },
    }
    instruction = (
        "系统运行控制观察如下。它是模型可见的 observation/control signal，不是最终回复。\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"
        "你必须基于这条观察重新输出一个合法 JSON action。"
        "不要重复上一轮违规输出；不要使用 Markdown 代码块；不要输出 provider-native tool_calls；"
        "不要在 JSON 前后附加解释文字。"
    )
    return _sanitize_model_messages(
        [
            *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
            {"role": "system", "content": instruction, "turn_id": turn_id},
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.runtime_control_signal_recovery",
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
) -> list[dict[str, Any]]:
    closeout_payload = {
        key: value
        for key, value in {
            "reason": str(reason or "").strip(),
            "phase": str(phase or "").strip(),
            "runtime_control_signal": dict(control_signal or {}),
            "protocol_error": dict(protocol_error or {}),
            "previous_invalid_response": str(previous_invalid_response or "").strip()[:1200],
        }.items()
        if value not in ("", None, [], {}, ())
    }
    instruction = (
        "你是一名正在收口的 coding agent。\n"
        "系统已经停止继续执行工具；现在必须由你亲自向用户收口。\n"
        "你只能输出给用户看的自然语言正文，不要输出 JSON、action_request、tool_calls、内部协议、工具调用片段或开发者说明。\n"
        "如果当前信息足够，请说明你已经确认的事实、完成了什么、还缺什么、下一步应该怎么继续。\n"
        "如果遇到搜索参数、路径、权限、读取窗口、上下文预算或大文件边界，请把它当作可恢复的运行事实："
        "说明应缩小范围、把目录放在 roots、把具体文件放在 paths、按 read_file 窗口继续读取、提高上下文预算，"
        "或把工作升级为项目级任务继续处理。\n"
        "如果你还没有完成用户目标，要明确说未完成和可继续的具体方向；不要把工具记录当作最终成果。\n\n"
        "运行边界观察如下，只用于你理解收口原因，不要逐字泄露内部字段：\n"
        f"{json.dumps(closeout_payload, ensure_ascii=False, sort_keys=True)}"
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
        "source": "system:execution_contract_feedback",
        "signal_kind": "agent_contract_feedback_required",
        "lifecycle": "agent_contract_feedback_required",
        "runtime_control_state": "execution_contract_feedback_required",
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
            "runtime_control_signal": signal,
        },
        "observed_facts": _contract_feedback_observed_facts(list(observations or [])),
        "required_action_protocol": {
            "authority": "harness.loop.model_action_request",
            "allowed_action_types": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
            "tool_call_allowed": False,
            "json_only": True,
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
        "这是一条执行契约反馈，不是用户消息。",
        "上一条输出没有进入会话，也不会被运行时代写成用户正文；你仍然负责判断、调度和最终表达。",
        f"当前阶段：{phase_text}",
    ]
    if signal_kind:
        pieces.append(f"触发信号：{signal_kind}。")
    if items:
        pieces.append("未通过的契约：")
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
        pieces.append(f"未通过的契约：{fallback_reason}。请按本轮 required_action_protocol 重新提交一个合法动作。")
    if previous_invalid_response:
        pieces.append("上一条不可发布输出已保存在 previous_invalid_response_preview，只能用于你定位错误，不能复述给用户。")
    pieces.append(
        "恢复要求：下一次只输出一个 authority 为 harness.loop.model_action_request 的 JSON action；"
        "action_type 只能是 respond、ask_user 或 block；不能调用工具，不能输出 provider-native tool_calls，也不能在 JSON 外写正文。"
    )
    pieces.append(
        "选择动作时按真实情况来：事实足够就用 respond.final_answer 写自然、可发布的收口；"
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
        "protocol_recovery": "协议恢复阶段，上一轮输出未满足动作合同，需要重新提交合法动作。",
        "tool_loop": "工具执行循环阶段，模型输出必须能被运行时唯一解释为一个合法动作。",
        "final_output_commit": "最终回复提交阶段，候选正文必须是 agent 自己写出的自然用户回复，且不能泄露内部协议。",
    }
    return labels.get(normalized, normalized or "unknown")


def _uses_standard_contract_feedback_template(code: str) -> bool:
    return str(code or "").strip() in {
        "json_action_required",
        "single_agent_turn_json_action_required",
        "native_tool_call_transport_not_available",
        "native_tool_call_not_allowed_for_context",
        "native_control_action_requires_json_action",
        "control_action_requires_json_action",
        "single_agent_turn_multiple_action_sources",
        "final_answer_required_for_respond",
        "native_respond_final_answer_required",
        "blocking_reason_required_for_block",
        "user_question_required_for_ask_user",
    }


def _situation_feedback_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "你没有提交本阶段要求的 JSON action，运行时无法把上一条输出可靠归类为回答、询问或阻塞。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        tool_hint = f"（{requested_tool}）" if requested_tool else ""
        return f"你尝试继续调用工具{tool_hint}，但当前阶段的工具通道已经关闭；这次工具意图不会被执行。"
    if normalized in {"native_control_action_requires_json_action", "control_action_requires_json_action"}:
        action_hint = f"（{requested_action}）" if requested_action else ""
        return f"你把控制类动作{action_hint}作为 provider-native tool_call 发出；这类动作会改变会话/任务状态，必须走 JSON action 合同。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "同一轮同时出现 JSON action 和 provider-native tool_call，运行时无法判断哪一个才是你的真实决定。"
    if normalized in {"final_answer_required_for_respond", "native_respond_final_answer_required"}:
        return "你选择了 respond，但没有提供 final_answer；这样会让用户只看到状态或记录，而不是 agent 的自然回复。"
    if normalized in {"blocking_reason_required_for_block"}:
        return "你选择了 block，但没有说明具体阻塞事实；用户和后续 agent 都无法判断卡点是权限、证据、环境还是目标不清。"
    if normalized in {"user_question_required_for_ask_user"}:
        return "你选择了 ask_user，但没有给出用户可以直接回答的问题。"
    return "上一条输出没有满足当前动作合同，运行时不能安全地执行或发布它。"


def _repair_instruction_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "只输出一个 authority 为 harness.loop.model_action_request 的 JSON 对象，不要写 Markdown、解释文字或自然语言正文。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        tool_hint = f"（刚才请求的是 {requested_tool}）" if requested_tool else ""
        return f"不要重复 provider-native tool_calls{tool_hint}；把当前意图改写为 respond、ask_user 或 block。"
    if normalized in {"native_control_action_requires_json_action", "control_action_requires_json_action"}:
        action_label = f" {requested_action} " if requested_action else "该动作"
        return f"保留控制意图，但把{action_label}重发为 harness.loop.model_action_request JSON action。"
    if normalized in {"single_agent_turn_multiple_action_sources"}:
        return "只保留一个动作来源；如果是收口/恢复阶段，优先提交 JSON action，并清除 native tool_call。"
    if normalized in {"final_answer_required_for_respond", "native_respond_final_answer_required"}:
        return "如果选择 respond，必须填写 final_answer；如果事实不足，不要空答，改用 ask_user 或 block。"
    if normalized in {"blocking_reason_required_for_block"}:
        return "如果选择 block，必须填写 blocking_reason，并说明具体阻塞事实、缺少的权限或缺失信息。"
    if normalized in {"user_question_required_for_ask_user"}:
        return "如果选择 ask_user，必须填写 user_question，并提出用户能直接回答的具体问题。"
    return "根据本轮 required_action_protocol 重新提交一个允许动作，保留已确认事实，避免泄露内部协议或重复无效动作。"


def _expected_next_action_for_contract_code(code: str, *, requested_action: str = "", requested_tool: str = "") -> str:
    normalized = str(code or "").strip()
    if normalized in {"json_action_required", "single_agent_turn_json_action_required"}:
        return "重新选择 respond、ask_user 或 block，并把对应正文放入 final_answer、user_question 或 blocking_reason。"
    if normalized in {"native_tool_call_transport_not_available", "native_tool_call_not_allowed_for_context"}:
        return "承认当前不能继续执行该工具；基于已有观察收口，或说明需要用户/环境提供什么条件。"
    if normalized in {"native_control_action_requires_json_action", "control_action_requires_json_action"}:
        if requested_action == "ask_user":
            return "提交 action_type=ask_user，并把问题写入 user_question。"
        if requested_action == "block":
            return "提交 action_type=block，并把真实阻塞写入 blocking_reason。"
        if requested_action == "request_task_run":
            return "当前收口阶段不能新开控制工具；若仍需任务化，先用 ask_user 或 block 说明需要用户确认的任务边界。"
        return "提交同等语义的 JSON action，不要通过工具通道表达控制决定。"
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
        return "你的候选 final_answer 混入了内部协议、运行时拦截或系统处理细节；这会变成系统越过 agent 对用户说话。"
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
        return "不要解释内部协议或运行时拦截，不要说“系统替你处理”；把事实、结果、风险和下一步改写成你自己的自然回复。"
    if commit_reason in {"empty_final_text", "missing_answer"}:
        return "给出真实 final_answer；如果无法可靠回答，改用 ask_user 或 block。"
    return "不要复述被拒绝内容，按 respond、ask_user 或 block 合同生成新的 agent 输出。"


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
        current_packet_ref = str(compilation.packet.packet_id)
        current_allowed_action_types = tuple(compilation.packet.allowed_action_types)
        current_available_tools = tuple(compilation.packet.available_tools or ())
        current_requires_json_action = single_agent_requires_json_action
        protocol_recovery_attempts = 0
        tool_observation_payloads: list[dict[str, Any]] = []
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
                    payload=terminal_payload,
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
            nonlocal terminal_recorded
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
                )
                closeout_segment_plan = _single_agent_turn_followup_segment_plan(
                    base_segment_plan=dict(compilation.packet.segment_plan or {}),
                    model_messages=closeout_messages,
                    packet_id=current_packet_ref,
                    tool_iteration=tool_iteration + attempt,
                )
                closeout_response = await _invoke_single_turn_model(
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
                    native_tools=[],
                )
                if isinstance(closeout_response, dict) and closeout_response.get("type") == "error":
                    break
                content = stringify_content(getattr(closeout_response, "content", closeout_response)).strip()
                closeout_content = _agent_authored_closeout_content_from_structured_payload(content, turn_id=turn_id)
                answer_channel = "conversation"
                terminal_status = "completed"
                if closeout_content is not None:
                    content = closeout_content.content
                    answer_channel = closeout_content.answer_channel
                    terminal_status = closeout_content.terminal_status
                elif _looks_like_structured_closeout_payload(content):
                    previous_invalid_response = content[:1200]
                    continue
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
            nonlocal assistant_stream_normalizer, protocol_recovery_attempts
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
            closeout_messages = _tool_limit_closeout_messages(
                model_messages,
                turn_id=turn_id,
                control_signal=control_signal,
            )
            closeout_segment_plan = _single_agent_turn_followup_segment_plan(
                base_segment_plan=dict(compilation.packet.segment_plan or {}),
                model_messages=closeout_messages,
                packet_id=current_packet_ref,
                tool_iteration=tool_iteration + 1,
            )
            closeout_response = None
            async for model_event in _invoke_single_turn_model_with_stream_events(
                model_runtime=model_runtime,
                model_messages=closeout_messages,
                model_selection=dict(model_selection or {}),
                accounting_context={
                    "request_id": f"modelreq:{current_packet_ref}:tool-limit-closeout",
                    "session_id": session_id,
                    "run_id": turn_run.turn_run_id if turn_run is not None else "",
                    "turn_id": turn_id,
                    "packet_ref": current_packet_ref,
                    "source": _TOOL_LIMIT_CLOSEOUT_SOURCE,
                    "segment_plan": closeout_segment_plan,
                    "prompt_manifest": {
                        **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                        "invocation_kind": "single_agent_turn_tool_limit_closeout",
                        "closeout_required": True,
                        "allowed_action_types": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
                        "segment_plan_ref": str(closeout_segment_plan.get("segment_plan_id") or ""),
                    },
                },
                native_tools=[],
                allow_assistant_text_delta=False,
                require_json_action=True,
            ):
                if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                    closeout_response = model_event.get("response")
                    assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                    continue
                yield model_event

            answer_source = _TOOL_LIMIT_CLOSEOUT_SOURCE
            if isinstance(closeout_response, dict) and closeout_response.get("type") == "error":
                yield closeout_response
                content = ""
                terminal_status = "blocked"
                answer_channel = "blocked"
                completion_state = "tool_limit_closeout_failed"
            else:
                closeout_parse = _single_agent_action_request_from_response(
                    closeout_response,
                    request_id=f"model-response:{current_packet_ref}:tool-limit-closeout",
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    iteration=tool_iteration + 1,
                    allowed_action_types=_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES,
                    phase="tool_limit_closeout",
                    require_json_action=True,
                    public_response_required=False,
                )
                if closeout_parse.error:
                    protocol_recovery_attempts += 1
                    protocol_control_signal = _model_protocol_violation_control_signal(
                        turn_id=turn_id,
                        packet_ref=current_packet_ref,
                        phase="tool_limit_closeout",
                        protocol_error=dict(closeout_parse.error or {}),
                        allowed_action_types=_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES,
                        recovery_attempt=protocol_recovery_attempts,
                        max_recovery_attempts=_MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS,
                        public_response_required=False,
                        response_preview=stringify_content(getattr(closeout_response, "content", closeout_response)),
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
                    recovery_messages = _runtime_control_signal_recovery_messages(
                        closeout_messages,
                        turn_id=turn_id,
                        control_signal=protocol_control_signal,
                        allowed_action_types=_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES,
                    )
                    recovery_segment_plan = _single_agent_turn_followup_segment_plan(
                        base_segment_plan=dict(compilation.packet.segment_plan or {}),
                        model_messages=recovery_messages,
                        packet_id=current_packet_ref,
                        tool_iteration=tool_iteration + 1,
                    )
                    recovery_response = None
                    async for model_event in _invoke_single_turn_model_with_stream_events(
                        model_runtime=model_runtime,
                        model_messages=recovery_messages,
                        model_selection=dict(model_selection or {}),
                        accounting_context={
                            "request_id": f"modelreq:{current_packet_ref}:tool-limit-closeout-runtime-control-recovery",
                            "session_id": session_id,
                            "run_id": turn_run.turn_run_id if turn_run is not None else "",
                            "turn_id": turn_id,
                            "packet_ref": current_packet_ref,
                            "source": "harness.single_agent_turn.runtime_control_signal_recovery",
                            "segment_plan": recovery_segment_plan,
                            "prompt_manifest": {
                                **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                                "invocation_kind": "single_agent_turn_runtime_control_signal_recovery",
                                "recovery_phase": "tool_limit_closeout",
                                "signal_kind": "model_protocol_violation",
                                "recovery_attempt": protocol_recovery_attempts,
                                "closeout_required": True,
                                "allowed_action_types": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
                            },
                        },
                        native_tools=[],
                        allow_assistant_text_delta=False,
                        require_json_action=True,
                    ):
                        if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                            recovery_response = model_event.get("response")
                            assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                            continue
                        yield model_event
                    closeout_parse = _single_agent_action_request_from_response(
                        recovery_response,
                        request_id=f"model-response:{current_packet_ref}:tool-limit-closeout:runtime-control-recovery",
                        turn_id=turn_id,
                        packet_ref=current_packet_ref,
                        iteration=tool_iteration + 1,
                        allowed_action_types=_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES,
                        phase="tool_limit_closeout_recovery",
                        require_json_action=True,
                        public_response_required=False,
                    )
                action_request = closeout_parse.action_request
                if (
                    closeout_parse.error
                    or closeout_parse.tool_actions
                    or action_request is None
                    or action_request.action_type not in set(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES)
                ):
                    content = ""
                    terminal_status = "blocked"
                    answer_channel = "blocked"
                    completion_state = "tool_limit_closeout_protocol_failed"
                elif action_request.action_type == "respond":
                    content = str(action_request.final_answer or "").strip()
                    if contains_internal_protocol(content) or contains_inline_pseudo_tool_call(content):
                        content = ""
                        terminal_status = "blocked"
                        answer_channel = "blocked"
                        completion_state = "tool_limit_closeout_unsafe_content"
                    else:
                        terminal_status = "completed" if _meaningful_visible_answer(content) else "blocked"
                        answer_channel = "conversation" if terminal_status == "completed" else "blocked"
                        completion_state = "tool_limit_agent_responded" if terminal_status == "completed" else "tool_limit_missing_answer"
                elif action_request.action_type == "ask_user":
                    content = str(action_request.user_question or "").strip()
                    if contains_internal_protocol(content) or contains_inline_pseudo_tool_call(content):
                        content = ""
                        terminal_status = "blocked"
                        answer_channel = "blocked"
                        completion_state = "tool_limit_closeout_unsafe_content"
                    else:
                        terminal_status = "completed" if _meaningful_visible_answer(content) else "blocked"
                        answer_channel = "ask_user" if terminal_status == "completed" else "blocked"
                        completion_state = "tool_limit_agent_asked_user" if terminal_status == "completed" else "tool_limit_missing_answer"
                else:
                    content = str(action_request.blocking_reason or "").strip()
                    if contains_internal_protocol(content) or contains_inline_pseudo_tool_call(content):
                        content = ""
                        completion_state = "tool_limit_closeout_unsafe_content"
                    else:
                        completion_state = "tool_limit_agent_blocked"
                    terminal_status = "blocked"
                    answer_channel = "blocked"
            if not str(content or "").strip():
                async for event in emit_agent_authored_closeout(
                    reason="tool_budget_exhausted",
                    phase=f"tool_limit_{phase}",
                    terminal_reason="single_turn_tool_iteration_limit",
                    control_signal=control_signal,
                    completion_state=completion_state,
                ):
                    yield event
                return
            protocol_final = _assistant_protocol_message_from_content(content, turn_id=turn_id)
            commit_decision = await _commit_final_message(
                commit_assistant_message,
                runtime_host=runtime_host,
                turn_run=turn_run,
                session_id=session_id,
                turn_id=turn_id,
                content=content,
                answer_channel=answer_channel,
                answer_source=answer_source,
                api_protocol_messages=[
                    *api_protocol_messages,
                    protocol_final,
                ],
            )
            async for event in emit_terminal_then_final(
                content=content,
                answer_channel=answer_channel,
                answer_source=answer_source,
                terminal_status=terminal_status,
                terminal_reason="single_turn_tool_iteration_limit",
                final_extra={
                    "runtime_branch": dict(runtime_branch or {}),
                    "completion_state": completion_state,
                    "runtime_control_signal": control_signal,
                },
                terminal_payload={"runtime_control_signal": control_signal, "completion_state": completion_state},
                commit_decision=commit_decision,
            ):
                yield event

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
            yield model_event
        tool_iteration = 0
        tool_observation_payloads = []
        last_tool_observation_payloads: list[dict[str, Any]] = []
        consecutive_failure_rounds = 0
        repaired_or_parsed_final_action: SingleAgentActionParse | None = None
        while True:
            if isinstance(response, dict) and response.get("type") == "error":
                break
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
                if protocol_recovery_attempts > _MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS:
                    async for event in emit_agent_authored_closeout(
                        reason="protocol_recovery_exhausted",
                        phase="tool_loop_protocol_recovery_exhausted",
                        terminal_reason=str(dict(action_parse.error or {}).get("code") or "single_agent_turn_protocol_error"),
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
                )
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
                        "request_id": f"modelreq:{current_packet_ref}:runtime-control-recovery:{tool_iteration + 1}:{protocol_recovery_attempts}",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.runtime_control_signal_recovery",
                        "segment_plan": recovery_segment_plan,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_runtime_control_signal_recovery",
                            "recovery_phase": "tool_loop",
                            "signal_kind": "model_protocol_violation",
                            "recovery_attempt": protocol_recovery_attempts,
                            "segment_plan_ref": str(recovery_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=_native_tools_for_packet(current_allowed_action_types, available_tools=current_available_tools),
                    allow_assistant_text_delta=not current_requires_json_action,
                    require_json_action=current_requires_json_action,
                ):
                    if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                        response = model_event.get("response")
                        assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                        continue
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
                admission = admit_model_action(
                    tool_action,
                    packet_allowed_action_types=current_allowed_action_types,
                    invocation_kind="single_agent_turn",
                    definitions_by_name=tool_definitions_by_name,
                    allowed_tool_names=set(runtime_tool_plan.dispatchable_tool_names),
                    runtime_profile=_runtime_profile_payload(runtime_assembly),
                    permission_mode=runtime_permission_mode,
                    side_effect_policy="runtime_authorized",
                    current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
                )
                action_permit = action_permit_from_admission(
                    tool_action,
                    admission,
                    invocation_kind="agent_turn",
                    packet_allowed_action_types=current_allowed_action_types,
                    allowed_tool_names=set(runtime_tool_plan.dispatchable_tool_names),
                    permission_mode=runtime_permission_mode,
                    side_effect_policy="runtime_authorized",
                    session_id=session_id,
                    grant_scope="turn",
                )
                if runtime_host is not None and turn_run is not None:
                    event = _record_model_action_admission(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        action_request=tool_action,
                        admission=admission,
                        packet_ref=current_packet_ref,
                    )
                    yield {"type": "model_action_admission", "event": event}
                row = {
                    "action_request": tool_action,
                    "tool_call": _tool_call_from_action_request(tool_action),
                    "admission": admission,
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
            if assistant_tool_calls:
                assistant_protocol_message = _with_turn_id(_assistant_tool_call_message(response, assistant_tool_calls), turn_id)
                api_protocol_messages.extend([assistant_protocol_message, *tool_protocol_messages])
            else:
                assistant_protocol_message = {}
            model_messages = _sanitize_model_messages(
                [
                    *model_messages,
                    assistant_protocol_message,
                    *tool_protocol_messages,
                ],
                turn_id=turn_id,
                source="harness.loop.single_agent_turn.tool_followup",
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
                followup_segment_plan = dict(followup_compilation.packet.segment_plan or {})
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
            response = None
            async for model_event in _invoke_single_turn_model_with_stream_events(
                model_runtime=model_runtime,
                model_messages=model_messages,
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
                allow_assistant_text_delta=not current_requires_json_action,
                require_json_action=current_requires_json_action,
            ):
                if model_event.get("type") == _INTERNAL_MODEL_RESPONSE_EVENT:
                    response = model_event.get("response")
                    assistant_stream_normalizer = model_event.get("assistant_stream_normalizer")
                    continue
                yield model_event
        if isinstance(response, dict) and response.get("type") == "error":
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status="failed",
                    terminal_reason=str(response.get("code") or "single_agent_turn_failed"),
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
                if protocol_recovery_attempts > _MAX_SINGLE_TURN_PROTOCOL_RECOVERY_ATTEMPTS:
                    async for event in emit_agent_authored_closeout(
                        reason="protocol_recovery_exhausted",
                        phase="final_protocol_recovery_exhausted",
                        terminal_reason=str(dict(action_parse.error or {}).get("code") or "single_agent_turn_protocol_error"),
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
                        "request_id": f"modelreq:{current_packet_ref}:final-runtime-control-recovery:{protocol_recovery_attempts}",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.runtime_control_signal_recovery",
                        "segment_plan": recovery_segment_plan,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_runtime_control_signal_recovery",
                            "recovery_phase": "final",
                            "signal_kind": "model_protocol_violation",
                            "recovery_attempt": protocol_recovery_attempts,
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
            admission = admit_model_action(
                action_request,
                packet_allowed_action_types=current_allowed_action_types,
                invocation_kind="single_agent_turn",
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
            )
            if runtime_host is not None and turn_run is not None:
                event = _record_model_action_admission(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    action_request=action_request,
                    admission=admission,
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
                    admission = admit_model_action(
                        action_request,
                        packet_allowed_action_types=current_allowed_action_types,
                        invocation_kind="single_agent_turn",
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
                    )
                    if runtime_host is not None and turn_run is not None:
                        event = _record_model_action_admission(
                            runtime_host,
                            turn_run=turn_run,
                            turn_id=turn_id,
                            action_request=action_request,
                            admission=admission,
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
                        payload={"action_request_ref": action_request.request_id},
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
                        payload={"action_request_ref": action_request.request_id},
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
                        payload={"action_request_ref": action_request.request_id},
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
            return error_event(
                content="运行中断",
                code="single_agent_turn_model_failed",
                reason=str(exc),
            )
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
            return error_event(
                content="运行中断",
                code="single_agent_turn_model_failed",
                reason=str(exc),
            )
    return error_event(
        content="运行中断",
        code="model_runtime_unavailable",
        reason="model_runtime_unavailable",
    )


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
    assistant_normalizer = AssistantStreamNormalizer(
        stream_ref=stream_ref,
        message_ref=assistant_message_ref(turn_id=str(accounting_context.get("turn_id") or ""), stream_ref=stream_ref),
        turn_run_id=str(accounting_context.get("run_id") or accounting_context.get("turn_run_id") or ""),
        task_run_id=str(accounting_context.get("task_run_id") or ""),
        answer_source=str(accounting_context.get("source") or "harness.single_agent_turn"),
    ) if emit_assistant_text_delta else None
    raw_content = ""
    aggregated_response: Any = None
    try:
        if native_tools and callable(tool_streamer):
            tool_call_options = build_round_tool_call_options(max_tool_calls=len(native_tools))
            async for chunk in tool_streamer(
                model_messages,
                native_tools,
                model_spec=model_selection,
                tool_call_options=tool_call_options,
                accounting_context=accounting_context,
            ):
                aggregated_response = _merge_model_stream_chunk(aggregated_response, chunk)
                delta_text = _model_stream_chunk_text(chunk)
                if not delta_text:
                    continue
                raw_content += delta_text
                if assistant_normalizer is not None:
                    for frame_event in assistant_normalizer.observe_delta(delta_text):
                        yield frame_event
        elif callable(plain_streamer):
            async for chunk in plain_streamer(
                model_messages,
                model_spec=model_selection,
                accounting_context=accounting_context,
            ):
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
        yield {
            "type": _INTERNAL_MODEL_RESPONSE_EVENT,
            "assistant_stream_normalizer": assistant_normalizer,
            "response": error_event(
                content="运行中断",
                code="single_agent_turn_model_failed",
                reason=str(exc),
            ),
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
                        code=str(protocol.protocol_errors[0] if protocol.protocol_errors else "model_protocol_error"),
                        repair_instruction="请只输出符合本轮模型决策合同的 JSON action，不要使用 Markdown 包裹或混入额外文本。",
                    ),
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
                        repair_instruction="请在 JSON action 和 provider-native tool call 之间二选一；控制裁决必须使用 JSON action。",
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
                        repair_instruction="这看起来像控制/工具动作，但缺少 harness.loop.model_action_request 契约；请提交顶层 action_type 和对应动作字段，或改用普通助手正文回答用户。",
                    ),
                    "phase": phase,
                },
            ),
        )
    if not native_tool_calls:
        if assistant_text and not require_json_action:
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
    allowed_set = set(allowed_action_types or ())
    if "tool_call" not in allowed_set:
        native_respond_actions: list[ModelActionRequest] = []
        native_errors: list[dict[str, Any]] = []
        for call in native_tool_calls:
            tool_name = str(dict(call or {}).get("name") or "").strip()
            if tool_name == "respond":
                action, error = _respond_action_request_from_native_tool_call(
                    dict(call or {}),
                    turn_id=turn_id,
                    packet_ref=packet_ref,
                    iteration=iteration,
                    allowed_action_types=allowed_action_types,
                )
                if action is not None:
                    native_respond_actions.append(action)
                elif error is not None:
                    native_errors.append(error)
            elif control_error := _native_control_action_error(dict(call or {})):
                native_errors.append(control_error)
            else:
                action_issue = _protocol_action_issue(
                    category="service_unavailable",
                    code="native_tool_call_transport_not_available",
                    requested_tool_name=tool_name,
                    repair_instruction="当前阶段没有开放普通 native 工具调用；请按本轮允许动作选择 JSON action 或等待进入正确服务面。",
                )
                native_errors.append(
                    {
                        "authority": "harness.loop.single_agent_turn.native_action_parser",
                        "code": "native_tool_call_transport_not_available",
                        "reason": "native_tool_call_transport_not_available",
                        "native_tool_call": _native_tool_call_diagnostics(dict(call or {})),
                        "action_issue": action_issue,
                        "repairable": True,
                        "repair_contract": {
                            "allowed_action_types": list(allowed_action_types or ()),
                        },
                    }
                )
        if native_respond_actions and not native_errors:
            return SingleAgentActionParse(
                action_request=native_respond_actions[0] if len(native_respond_actions) == 1 else None,
                native_tool_calls=native_tool_calls,
                control_action=native_respond_actions[0] if len(native_respond_actions) == 1 else None,
            )
        reasons = [
            str(error.get("reason") or error.get("code") or "").strip()
            for error in native_errors
            if str(error.get("reason") or error.get("code") or "").strip()
        ]
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_invalid_native_action",
                reason=";".join(reasons) or "native_tool_call_transport_not_available",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "native_action_errors": native_errors,
                    "action_issue": dict(native_errors[0].get("action_issue") or {}) if native_errors else {},
                    "phase": phase,
                },
            ),
        )
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
    if tool_actions:
        if "tool_call" not in set(allowed_action_types or ()):
            action_issue = _protocol_action_issue(
                category="service_unavailable",
                code="tool_call_transport_not_available",
                requested_action_type="tool_call",
                requested_tool_name=str(dict(tool_actions[0].tool_call or {}).get("tool_name") or dict(tool_actions[0].tool_call or {}).get("name") or ""),
                repair_instruction="当前阶段没有开放普通工具调用服务面；请按本轮允许动作选择控制裁决、回答、询问或阻塞。",
            )
            return SingleAgentActionParse(
                action_request=None,
                native_tool_calls=native_tool_calls,
                error=_single_agent_protocol_error(
                    code="single_agent_turn_invalid_native_action",
                    reason="native_tool_call_not_allowed_for_context",
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


def _looks_like_malformed_single_agent_action_payload(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    action_contract_keys = {
        "active_work_control",
        "blocking_reason",
        "capability_intent",
        "completion_contract",
        "final_answer",
        "observation_contract",
        "permission_request",
        "public_action_state",
        "public_progress_note",
        "recovery_resume",
        "selected_skill_ids",
        "skill_intent",
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
    call_id = str(call.get("id") or f"call:respond:{iteration}")
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
    action_type = _control_action_from_native_tool_call(call)
    if not action_type:
        return None
    tool_name = str(dict(call or {}).get("name") or "").strip()
    return {
        "authority": "harness.loop.single_agent_turn.native_action_parser",
        "code": "native_control_action_requires_json_action",
        "reason": "native_control_action_requires_json_action",
        "native_tool_call": _native_tool_call_diagnostics(call),
        "action_issue": _protocol_action_issue(
            category="protocol_violation",
            code="control_action_requires_json_action",
            requested_action_type=action_type,
            requested_tool_name=tool_name,
            repair_instruction="控制裁决必须输出 JSON action；请保留原控制意图并改用 JSON action 重新提交。",
        ),
        "repairable": True,
        "repair_contract": {
            "required_transport": "json_action",
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
    return _CONTROL_ACTION_ALIASES.get(normalized, "")


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
    "capability_intent",
    "skill_intent",
    "observation_contract",
)
_RECOVERY_RESUME_NESTED_FIELDS = ("task_run_id", "continuation_id")


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
                "全部放入 recovery_resume 对象内。只使用系统提供的可恢复句柄，不要从旧消息文本猜测。"
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
                f"{missing_text}；task_run_id 和 continuation_id 必须来自系统提供的可恢复上下文。"
            )
        return default
    if action_type != "request_task_run":
        return default
    errors = {str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or [])}
    task_seed = payload.get("task_contract_seed")
    task_seed_obj = dict(task_seed or {}) if isinstance(task_seed, dict) else {}
    misplaced_top_level = [field for field in _REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS if field in payload]
    payload_wrapper = payload.get("payload") if isinstance(payload.get("payload"), dict) else None
    if misplaced_top_level or payload_wrapper is not None:
        misplaced = "、".join(misplaced_top_level) if misplaced_top_level else "payload"
        return (
            "request_task_run 的任务合同字段放错层级。不要把 "
            f"{misplaced} 放在 JSON 顶层，也不要使用 payload 包裹。"
            "请保留 action_type=request_task_run，把 working_scope、capability_intent、"
            "skill_intent、observation_contract 全部放入 task_contract_seed 内；"
            "capability_intent 使用 needed_capability_groups，不使用 selected_groups；"
            "observation_contract 必须包含 evidence_policy。"
        )
    required_errors = {
        f"{field}_required_for_request_task_run" for field in _REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS
    }
    if errors.intersection(required_errors) or "observation_contract.evidence_policy_required" in errors:
        missing = [
            field
            for field in _REQUEST_TASK_RUN_NESTED_CONTRACT_FIELDS
            if field not in task_seed_obj or not isinstance(task_seed_obj.get(field), dict)
        ]
        missing_text = "、".join(missing) if missing else "必需字段"
        return (
            "request_task_run 必须提交完整 task_contract_seed。请在 task_contract_seed 内补齐 "
            f"{missing_text}；capability_intent 至少包含 needed_capability_groups 或 reason，"
            "skill_intent 即使不选择 skill 也要给 selected_skill_ids: [] 和 reason，"
            "observation_contract 必须包含 evidence_policy。"
        )
    if "task_contract_seed_required_for_request_task_run" in errors:
        return (
            "request_task_run 必须包含 task_contract_seed，且任务目标、范围、能力意图、"
            "skill 意图、观察证据要求和完成标准都必须放在 task_contract_seed 内。"
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
    tools: list[dict[str, Any]] = []
    if "tool_call" in allowed:
        tools.extend(_runtime_native_tools(available_tools))
    return tools


def _runtime_native_tools(available_tools: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for item in available_tools:
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name:
            continue
        schema = dict(tool.get("input_schema") or {}) if isinstance(tool.get("input_schema"), dict) else {}
        if not schema:
            properties = {str(value): {"type": "string"} for value in list(tool.get("required_inputs") or []) if str(value)}
            schema = {
                "type": "object",
                "properties": properties,
                "required": list(properties),
            }
        tools.append(
            {
                "name": name,
                "description": str(tool.get("description") or tool.get("display_name") or name),
                "input_schema": schema,
            }
        )
    return tools


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
        call_id = str(call.get("id") or f"call:{tool_name}:{iteration}")
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
    for key in ("path", "file_path", "target_path", "query", "pattern", "url"):
        value = str(args.get(key) or "").strip()
        if value:
            return value[:120]
    return ""


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
    tool_call = _tool_call_from_action_request(action_request)
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    tool_call_id = _canonical_action_tool_call_id(action_request)
    operation_id = _tool_operation_id(runtime_host, tool_name=tool_name)
    invocation_id = build_tool_invocation_id(
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        action_request_ref=action_request.request_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
    )
    status = _tool_observation_status_from_admission(admission)
    system_reason = str(admission.system_reason or admission.decision or status)
    user_reason = str(admission.user_visible_reason or system_reason)
    action_issue = dict(getattr(admission, "action_issue", {}) or {})
    issue_category = str(action_issue.get("category") or getattr(admission, "issue_category", "") or "runtime_boundary")
    if status == "needs_approval":
        text = (
            f"工具调用等待运行时人工确认。问题分类：{issue_category}；准入裁决：{admission.decision}；原因：{system_reason}。"
            f"边界说明：{user_reason}。这属于 control-plane 审批状态，不应作为模型恢复观察进入下一轮。"
        )
    else:
        text = (
            f"工具调用未执行。问题分类：{issue_category}；准入裁决：{admission.decision}；原因：{system_reason}。"
            f"边界说明：{user_reason}。请基于这条观察继续：改用本轮已开放工具、请求必要信息、请求持续任务，或直接说明无法执行的边界。"
        )
    return ToolObservation(
        observation_id=f"toolobs:{invocation_id}:{uuid.uuid4().hex[:8]}",
        invocation_id=invocation_id,
        caller_kind="agent_turn",
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        tool_name=tool_name,
        operation_id=operation_id,
        status=status,
        text=text,
        result_envelope={
            "tool_call_id": tool_call_id,
            "error": system_reason,
            "error_code": system_reason,
            "admission_decision": admission.decision,
            "action_issue": action_issue,
            "retryable": True,
        },
        operation_gate={
            "admission": admission.to_dict(),
            "action_permit": dict(action_permit or {}),
            "tool_plan_ref": str(getattr(tool_plan, "plan_id", "") or ""),
        },
        diagnostics={
            "stage": "model_action_admission",
            "packet_ref": packet_ref,
            "action_request": action_request.to_dict(),
            "action_issue": action_issue,
            "model_visible_recovery_observation": status != "needs_approval",
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
    tool_call = _tool_call_from_action_request(action_request)
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    tool_call_id = _canonical_action_tool_call_id(action_request)
    operation_id = _tool_operation_id(runtime_host, tool_name=tool_name)
    invocation_id = build_tool_invocation_id(
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        action_request_ref=action_request.request_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
    )
    error_text = _compact_text(str(error), limit=1000) or type(error).__name__
    return ToolObservation(
        observation_id=f"toolobs:{invocation_id}:{uuid.uuid4().hex[:8]}",
        invocation_id=invocation_id,
        caller_kind="agent_turn",
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        tool_name=tool_name,
        operation_id=operation_id,
        status="error",
        text=f"工具调用返回运行时错误：{error_text}。请基于该错误调整下一步，不要重复同一失败动作。",
        result_envelope={
            "tool_call_id": tool_call_id,
            "error": error_text,
            "error_code": type(error).__name__,
            "retryable": True,
        },
        operation_gate={
            "admission": admission.to_dict(),
            "action_permit": dict(action_permit or {}),
            "tool_plan_ref": str(getattr(tool_plan, "plan_id", "") or ""),
        },
        diagnostics={
            "stage": "tool_runtime_exception",
            "packet_ref": packet_ref,
            "exception_type": type(error).__name__,
            "action_request": action_request.to_dict(),
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


def _tool_observation_status_from_admission(admission: AdmissionDecision) -> str:
    decision = str(admission.decision or "").strip()
    if decision == "deny":
        return "denied"
    if decision == "ask_approval":
        return "needs_approval"
    if decision in {"needs_contract", "needs_task_run"}:
        return "needs_contract"
    return "error"


def _tool_operation_id(runtime_host: Any, *, tool_name: str) -> str:
    definitions = getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {})
    definition = dict(definitions or {}).get(tool_name)
    return str(getattr(definition, "operation_id", "") or tool_name)


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
    tool_call_id = _canonical_action_tool_call_id(action_request)
    tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    definitions = getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {})
    definition = dict(definitions or {}).get(tool_name)
    operation_id = str(getattr(definition, "operation_id", "") or tool_name)
    invocation_id = build_tool_invocation_id(
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        action_request_ref=action_request.request_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
    )
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    sandbox_scope = _single_turn_sandbox_scope(assembly_payload, runtime_host=runtime_host, turn_id=turn_id)
    request = ToolInvocationRequest(
        invocation_id=invocation_id,
        caller_kind="agent_turn",
        caller_ref=turn_run.turn_run_id if turn_run is not None else f"turnrun:{turn_id}",
        session_id=session_id,
        turn_id=turn_id,
        action_request_ref=action_request.request_id,
        packet_ref=packet_ref,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args,
        operation_id=operation_id,
        tool_plan_ref=str(getattr(tool_plan, "plan_id", "") or ""),
        admission_ref=admission.admission_id,
        action_permit=dict(action_permit or {}),
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
    base_segments: dict[int, dict[str, Any]] = {}
    for segment in list(base_segment_plan.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        index = _segment_model_message_index(segment)
        if index >= 0:
            base_segments[index] = dict(segment)
    normalized_messages = normalize_messages(
        _sanitize_model_messages(
            model_messages,
            turn_id="",
            source="harness.loop.single_agent_turn.followup_segment_plan",
        )
    )
    specs: list[dict[str, Any]] = []
    for index, message in enumerate(normalized_messages):
        base = dict(base_segments.get(index) or {})
        if base:
            specs.append(
                {
                    "role": str(message.get("role") or "user"),
                    "content": str(message.get("content") or ""),
                    "kind": str(base.get("kind") or "single_agent_turn_base"),
                    "source_ref": str(base.get("source_ref") or "single_agent_turn_base"),
                    "cache_scope": str(base.get("cache_scope") or "none"),
                    "cache_role": str(base.get("cache_role") or "volatile"),
                    "prefix_tier": str(base.get("prefix_tier") or "volatile"),
                    "compression_role": str(base.get("compression_role") or "summarize"),
                    "metadata": dict(base.get("metadata") or {}),
                    "model_message": dict(message),
                }
            )
            continue
        specs.append(_single_agent_turn_followup_message_spec(message, tool_iteration=tool_iteration))
    return build_prompt_segment_plan(
        packet_id=f"{packet_id}:tool-followup:{max(1, int(tool_iteration or 1))}",
        invocation_kind="single_agent_turn_tool_followup",
        message_specs=specs,
    ).to_dict()


def _single_agent_turn_followup_message_spec(message: dict[str, Any], *, tool_iteration: int) -> dict[str, Any]:
    role = str(message.get("role") or "user")
    if role == "assistant" and message.get("tool_calls"):
        kind = "single_agent_turn_tool_call"
        source_ref = f"single_agent_turn.tool_call:{tool_iteration}"
        compression_role = "preserve"
    elif role == "tool":
        kind = "single_agent_turn_tool_observation"
        source_ref = f"single_agent_turn.tool_observation:{tool_iteration}"
        compression_role = "summarize"
    else:
        kind = "single_agent_turn_followup_message"
        source_ref = f"single_agent_turn.followup:{tool_iteration}"
        compression_role = "summarize"
    return {
        "role": role,
        "content": str(message.get("content") or ""),
        "kind": kind,
        "source_ref": source_ref,
        "cache_scope": "none",
        "cache_role": "volatile",
        "prefix_tier": "volatile",
        "compression_role": compression_role,
        "metadata": {
            "followup_iteration": max(1, int(tool_iteration or 1)),
            "volatility_reason": "single agent turn tool follow-up messages change after each tool observation",
        },
        "model_message": dict(message),
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
) -> FinalMessageCommit:
    sanitized_protocol_messages = _sanitize_model_messages(
        [dict(item) for item in list(api_protocol_messages or []) if isinstance(item, dict)],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.commit_api_protocol_messages",
    )
    decision = canonical_output_decision_for_final_text(
        content,
        answer_channel=answer_channel,
        answer_source=answer_source,
        execution_posture="single_agent_turn",
        has_tool_receipt=any(str(item.get("role") or "") == "tool" for item in sanitized_protocol_messages),
    )
    commit_gate = build_assistant_session_message_commit_decision(
        session_id=session_id,
        task_run_id="",
        task_id="",
        turn_id=turn_id,
        content=decision.content,
        answer_channel=decision.answer_channel,
        answer_source=decision.answer_source,
        answer_canonical_state=decision.canonical_state,
        answer_persist_policy=decision.persist_policy,
        answer_finalization_policy=decision.finalization_policy,
        answer_fallback_reason=decision.fallback_reason,
        answer_selected_channel=decision.selected_channel,
        answer_selected_source=decision.selected_source,
        answer_leak_flags=decision.leak_flags,
        source="harness.loop.single_agent_turn",
    )
    commit_gate_payload = commit_gate.to_dict()
    checked_event: dict[str, Any] = {}
    checked_offset = -1
    if runtime_host is not None and turn_run is not None:
        checked = runtime_host.event_log.append(
            turn_run.turn_run_id,
            "session_output_commit_checked",
            payload={
                "session_id": session_id,
                "turn_id": turn_id,
                "turn_run_id": turn_run.turn_run_id,
                "commit_allowed": bool(commit_gate.commit_allowed),
                "reason": str(commit_gate.reason or ""),
                "answer_channel": decision.answer_channel,
                "answer_source": decision.answer_source,
                "answer_canonical_state": decision.canonical_state,
                "answer_persist_policy": decision.persist_policy,
                "answer_finalization_policy": decision.finalization_policy,
                "content_sha256": _text_sha256(decision.content),
                "commit_gate": commit_gate_payload,
                "authority": "harness.session_output_commit",
            },
            refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id},
        )
        checked_event = _stream_event_from_runtime_event("session_output_commit_checked", checked)
        checked_offset = _event_offset(checked)
        _update_turn_run_event_offset(runtime_host, turn_run=turn_run, event=checked)

    if not commit_gate.commit_allowed:
        receipt = _record_single_turn_session_output_commit_terminal(
            runtime_host,
            turn_run=turn_run,
            event_type="session_output_commit_skipped",
            status="skipped",
            session_id=session_id,
            turn_id=turn_id,
            content=decision.content,
            commit_allowed=False,
            reason=str(commit_gate.reason or "commit_gate_blocked"),
            commit_gate=commit_gate_payload,
            checked_event_offset=checked_offset,
        )
        return FinalMessageCommit(
            decision=decision,
            events=tuple(item for item in (checked_event, _commit_receipt_stream_event(receipt)) if item),
            receipt=receipt,
        )

    commit_payload = dict(commit_gate.commit_candidate.payload)
    commit_payload["api_protocol_messages"] = sanitized_protocol_messages
    try:
        maybe_result = commit_assistant_message(session_id, commit_payload)
        committer_result = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
    except Exception as exc:
        logger.exception("single agent final message commit failed")
        receipt = _record_single_turn_session_output_commit_terminal(
            runtime_host,
            turn_run=turn_run,
            event_type="session_output_commit_failed",
            status="failed",
            session_id=session_id,
            turn_id=turn_id,
            content=decision.content,
            commit_allowed=True,
            reason=str(exc) or "assistant_message_commit_failed",
            commit_gate=commit_gate_payload,
            checked_event_offset=checked_offset,
        )
        return FinalMessageCommit(
            decision=decision,
            events=tuple(item for item in (checked_event, _commit_receipt_stream_event(receipt)) if item),
            receipt=receipt,
        )

    receipt = _record_single_turn_session_output_commit_terminal(
        runtime_host,
        turn_run=turn_run,
        event_type="session_output_commit_ack",
        status="committed",
        session_id=session_id,
        turn_id=turn_id,
        content=decision.content,
        commit_allowed=True,
        reason="committed",
        commit_gate=commit_gate_payload,
        checked_event_offset=checked_offset,
        committer_result=committer_result,
    )
    return FinalMessageCommit(
        decision=decision,
        events=tuple(item for item in (checked_event, _commit_receipt_stream_event(receipt)) if item),
        receipt=receipt,
    )


def _record_single_turn_session_output_commit_terminal(
    runtime_host: Any | None,
    *,
    turn_run: TurnRun | None,
    event_type: str,
    status: str,
    session_id: str,
    turn_id: str,
    content: str,
    commit_allowed: bool,
    reason: str,
    commit_gate: dict[str, Any],
    checked_event_offset: int = -1,
    committer_result: Any = None,
) -> dict[str, Any]:
    normalized_status = str(status or "").strip() or "failed"
    normalized_reason = str(reason or normalized_status).strip()
    turn_run_id = str(getattr(turn_run, "turn_run_id", "") or "")
    payload = {
        "session_id": str(session_id or ""),
        "turn_id": str(turn_id or ""),
        "turn_run_id": turn_run_id,
        "state": normalized_status,
        "status": normalized_status,
        "commit_allowed": bool(commit_allowed),
        "reason": normalized_reason,
        "content_sha256": _text_sha256(content),
        "anchor_message_id": _assistant_anchor_message_id(turn_id=turn_id, committer_result=committer_result),
        "checked_event_offset": checked_event_offset,
        "committer_result": _public_committer_result(committer_result),
        "commit_gate": dict(commit_gate or {}),
        "authority": "harness.session_output_commit",
    }
    event_payload = {
        **payload,
        "event_type": event_type,
    }
    if runtime_host is None or turn_run is None:
        return event_payload
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        event_type,
        payload=payload,
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id},
    )
    _update_turn_run_event_offset(runtime_host, turn_run=turn_run, event=event)
    return {
        **event_payload,
        "event_id": str(getattr(event, "event_id", "") or ""),
        "event_offset": _event_offset(event),
        "created_at": float(getattr(event, "created_at", 0.0) or 0.0),
        "event": event.to_dict() if hasattr(event, "to_dict") else {},
    }


def _commit_receipt_stream_event(receipt: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(receipt or {})
    event_type = str(data.get("event_type") or "").strip()
    if not event_type:
        return {}
    event = data.get("event")
    if isinstance(event, dict) and event:
        return {"type": event_type, "event": dict(event)}
    payload = {key: value for key, value in data.items() if key not in {"event_type", "event"}}
    return {"type": event_type, **payload}


def _stream_event_from_runtime_event(event_type: str, event: Any) -> dict[str, Any]:
    payload = event.to_dict() if hasattr(event, "to_dict") else {}
    return {"type": event_type, "event": payload} if payload else {}


def _update_turn_run_event_offset(runtime_host: Any, *, turn_run: TurnRun, event: Any) -> None:
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
    runtime_host.state_index.upsert_turn_run(
        replace(
            current,
            updated_at=float(getattr(event, "created_at", 0.0) or getattr(current, "updated_at", 0.0) or 0.0),
            latest_event_offset=_event_offset(event),
        )
    )


def _assistant_anchor_message_id(*, turn_id: str, committer_result: Any = None) -> str:
    result = dict(committer_result or {}) if isinstance(committer_result, dict) else {}
    appended = list(result.get("appended_messages") or [])
    for item in reversed(appended):
        if not isinstance(item, dict):
            continue
        explicit = str(item.get("id") or item.get("message_id") or "").strip()
        if explicit:
            return explicit
    return f"history-message:{turn_id}:assistant" if str(turn_id or "").strip() else ""


def _public_committer_result(value: Any) -> dict[str, Any]:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    return {
        key: payload.get(key)
        for key in ("file_work_context_writeback", "memory_maintenance_enqueued", "memory_commit_state")
        if key in payload
    }


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
        },
    )
    runtime_host.state_index.upsert_turn_run(turn_run)
    event = runtime_host.event_log.append(
        turn_run_id,
        "agent_turn_received",
        payload={"turn_id": turn_id, "turn_run": turn_run.to_dict()},
        refs={"turn_ref": turn_id, "turn_run_ref": turn_run.turn_run_id},
    )
    updated = replace(turn_run, updated_at=event.created_at, latest_event_offset=event.offset)
    runtime_host.state_index.upsert_turn_run(updated)
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is not None:
        active_registry.bind_turn_run(session_id=session_id, turn_id=turn_id, turn_run_id=turn_run_id)
    return updated, event.to_dict()


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


def _record_model_action_admission(
    runtime_host: Any,
    *,
    turn_run: TurnRun,
    turn_id: str,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
    packet_ref: str,
) -> dict[str, Any]:
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        "model_action_admission_checked",
        payload={
            "turn_id": turn_id,
            "model_action_request": action_request.to_dict(),
            "admission": admission.to_dict(),
        },
        refs={
            "turn_ref": turn_id,
            "turn_run_ref": turn_run.turn_run_id,
            "action_request_ref": action_request.request_id,
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
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        "turn_runtime_control_signal_observed",
        payload={
            "turn_id": turn_id,
            "model_visible": True,
            "runtime_control_signal": dict(control_signal or {}),
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
                "latest_runtime_control_signal": dict(control_signal or {}),
                "latest_step": "runtime_control_signal_observed",
            },
        )
    )
    return event.to_dict()


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
        tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        tool_call_id = _canonical_action_tool_call_id(action_request)
        if not tool_name or not tool_call_id:
            continue
        permission_decision_id_value = permission_decision_id(admission, tool_call_id=tool_call_id)
        tool_lifecycle_id = build_tool_invocation_id(
            caller_ref=turn_run.turn_run_id,
            action_request_ref=str(getattr(action_request, "request_id", "") or tool_call_id),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
        event = runtime_host.event_log.append(
            turn_run.turn_run_id,
            "tool_item_started",
            payload={
                "turn_id": turn_id,
                "turn_run_id": turn_run.turn_run_id,
                "tool_lifecycle_id": tool_lifecycle_id,
                "tool_call_id": tool_call_id,
                "permission_decision_id": permission_decision_id_value,
                "tool_name": tool_name,
                "state": "running",
                "action_request_ref": str(getattr(action_request, "request_id", "") or ""),
            },
            refs={
                "turn_ref": turn_id,
                "turn_run_ref": turn_run.turn_run_id,
                "action_request_ref": str(getattr(action_request, "request_id", "") or ""),
                "tool_invocation_ref": tool_lifecycle_id,
            },
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
    event = runtime_host.event_log.append(
        turn_run.turn_run_id,
        "agent_turn_terminal",
        payload={
            "turn_id": turn_id,
            "status": status,
            "terminal_reason": terminal_reason,
            **dict(payload or {}),
        },
        refs={"turn_ref": turn_id},
    )
    current = runtime_host.state_index.get_turn_run(turn_run.turn_run_id) or turn_run
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
