from __future__ import annotations

import asyncio
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
from harness.loop.active_work import active_work_action_from_payload
from harness.loop.action_permit import action_permit_from_admission
from harness.loop.model_action_protocol import ModelActionRequest, model_action_request_from_payload
from harness.loop.model_action_runtime import call_model_invoker
from harness.loop.presentation import assistant_body_final_event, error_event, final_answer_event
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
from runtime.cache_manager import runtime_cache_manager_for_host
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
from runtime.shared.models import TurnRun
from runtime.tool_runtime import ToolInvocationRequest, ToolObservation, build_round_tool_call_options, build_tool_invocation_id
from runtime.tool_runtime.provider_tool_call_adapter import tool_calls_for_langchain_messages
from permissions.policy import normalize_permission_mode
from prompt_library import SINGLE_AGENT_ADMISSION_REPAIR_PROMPT, SINGLE_AGENT_PROTOCOL_REPAIR_PROMPT


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
ApplyActiveWorkControl = Callable[[dict[str, Any]], Awaitable[str | dict[str, Any]]]
CompactSessionContext = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]

_STEER_ACTIVE_WORK_ACTIONS = {
    "continue_active_work",
    "append_instruction_to_active_work",
    "answer_then_continue_active_work",
}
_DEFAULT_SINGLE_TURN_TOOL_ITERATIONS = 8
_MAX_CONFIGURED_SINGLE_TURN_TOOL_ITERATIONS = 32


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
_CONTROL_ACTION_NAMES = {"request_task_run", "active_work_control", "ask_user", "block"}
_REPAIRABLE_SINGLE_AGENT_PROTOCOL_ERRORS = {
    "single_agent_turn_model_protocol_error",
    "single_agent_turn_multiple_action_sources",
    "single_agent_turn_invalid_native_action",
    "single_agent_turn_invalid_json_action",
    "single_agent_turn_json_action_required",
}
_INTERNAL_MODEL_RESPONSE_EVENT = "__single_agent_model_response"


@dataclass(frozen=True, slots=True)
class NativeActionRequestParse:
    actions: tuple[ModelActionRequest, ...] = ()
    errors: tuple[dict[str, Any], ...] = ()


def _meaningful_visible_answer(content: str) -> bool:
    visible = sanitize_visible_assistant_content(str(content or "")).strip()
    if not visible:
        return False
    if visible in {">", "<", "...", "…", "---", "----"}:
        return False
    if contains_internal_protocol(visible) or contains_inline_pseudo_tool_call(visible):
        return False
    return any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in visible)


def _looks_like_structured_closeout_payload(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    candidate = text
    if candidate.startswith("```"):
        candidate = candidate.replace("\r\n", "\n")
        candidate = candidate[7:] if candidate.lower().startswith("```json") else candidate[3:]
        if candidate.endswith("```"):
            candidate = candidate[:-3]
        candidate = candidate.strip()
    if not ((candidate.startswith("{") and candidate.endswith("}")) or (candidate.startswith("[") and candidate.endswith("]"))):
        return False
    try:
        parsed = json.loads(candidate)
    except Exception:
        return False
    if isinstance(parsed, dict):
        keys = {str(key) for key in parsed.keys()}
        return bool(keys & {"authority", "action_type", "tool_call", "tool_calls", "active_work_control"})
    return isinstance(parsed, list) and any(isinstance(item, dict) for item in parsed)


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
        "本轮工具预算已经耗尽。这不是最终回复。你必须停止发起新的工具调用，"
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
    stream_run_id: str = "",
    commit_assistant_message: CommitAssistantMessage,
    start_task_from_action_request: StartTaskFromActionRequest,
    apply_active_work_control: ApplyActiveWorkControl,
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
            commit_decision: CanonicalFinalTextDecision | None = None,
        ) -> AsyncIterator[dict[str, Any]]:
            nonlocal terminal_recorded, assistant_stream_normalizer
            decision = commit_decision or canonical_output_decision_for_final_text(
                content,
                answer_channel=answer_channel,
                answer_source=answer_source,
                execution_posture="single_agent_turn",
                has_tool_receipt=has_tool_receipt,
                terminal_reason=terminal_reason,
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
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status=terminal_status,
                    terminal_reason=terminal_reason,
                    payload=terminal_payload,
                )
                terminal_recorded = True
                yield {"type": "agent_turn_terminal", "event": terminal}
            yield {
                "type": "done",
                **decision.to_payload(),
                "terminal_reason": terminal_reason,
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
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_agent_authored_closeout",
                            "closeout_phase": phase,
                            "closeout_reason": reason,
                            "attempt": attempt,
                        },
                    },
                    native_tools=[],
                )
                if isinstance(closeout_response, dict) and closeout_response.get("type") == "error":
                    break
                content = stringify_content(getattr(closeout_response, "content", closeout_response)).strip()
                if _looks_like_structured_closeout_payload(content):
                    previous_invalid_response = content[:1200]
                    continue
                decision = canonical_output_decision_for_final_text(
                    content,
                    answer_channel="conversation",
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
                        session_id=session_id,
                        turn_id=turn_id,
                        content=content,
                        answer_channel="conversation",
                        answer_source=_AGENT_CLOSEOUT_SOURCE,
                        api_protocol_messages=[
                            *api_protocol_messages,
                            _assistant_protocol_message_from_content(content, turn_id=turn_id),
                        ],
                    )
                    async for event in emit_terminal_then_final(
                        content=content,
                        answer_channel="conversation",
                        answer_source=_AGENT_CLOSEOUT_SOURCE,
                        terminal_status="completed",
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
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status="failed",
                    terminal_reason=f"{terminal_reason}:agent_closeout_not_returned",
                    payload={
                        "completion_state": "agent_closeout_not_returned",
                        **({"runtime_control_signal": dict(control_signal or {})} if control_signal else {}),
                        **({"protocol_error": dict(protocol_error or {})} if protocol_error else {}),
                    },
                )
                terminal_recorded = True
                yield {"type": "agent_turn_terminal", "event": terminal}
            yield error_event(
                content="agent 没有回传收口正文，运行连接已中断。",
                code="single_agent_turn_agent_closeout_not_returned",
                reason=f"{terminal_reason}:agent_closeout_not_returned",
                extra={
                    "terminal_reason": f"{terminal_reason}:agent_closeout_not_returned",
                    "completion_state": "agent_closeout_not_returned",
                    "runtime_branch": dict(runtime_branch or {}),
                    "turn_run_id": turn_run.turn_run_id if turn_run is not None else "",
                },
            )

        async def emit_tool_limit_closeout(
            *,
            attempted_actions: list[ModelActionRequest],
            phase: str,
        ) -> AsyncIterator[dict[str, Any]]:
            nonlocal assistant_stream_normalizer
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
                )
                if closeout_parse.error:
                    closeout_parse = await _repair_single_agent_action_parse(
                        closeout_parse,
                        response=closeout_response,
                        model_runtime=model_runtime,
                        model_messages=closeout_messages,
                        model_selection=dict(model_selection or {}),
                        accounting_context={
                            "request_id": f"modelreq:{current_packet_ref}:tool-limit-closeout-protocol-repair",
                            "session_id": session_id,
                            "run_id": turn_run.turn_run_id if turn_run is not None else "",
                            "turn_id": turn_id,
                            "packet_ref": current_packet_ref,
                            "source": "harness.single_agent_turn.tool_limit_closeout.protocol_repair",
                            "segment_plan": closeout_segment_plan,
                            "prompt_manifest": {
                                **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                                "invocation_kind": "single_agent_turn_tool_limit_closeout_protocol_repair",
                                "closeout_required": True,
                                "allowed_action_types": list(_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES),
                            },
                        },
                        request_id=f"model-response:{current_packet_ref}:tool-limit-closeout:repair",
                        turn_id=turn_id,
                        packet_ref=current_packet_ref,
                        iteration=tool_iteration + 1,
                        allowed_action_types=_TOOL_LIMIT_CLOSEOUT_ACTION_TYPES,
                        phase="tool_limit_closeout",
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
        tool_observation_payloads: list[dict[str, Any]] = []
        emitted_feedback_segments: set[str] = set()
        repaired_or_parsed_final_action: SingleAgentActionParse | None = None
        while True:
            if isinstance(response, dict) and response.get("type") == "error":
                break
            action_parse = _single_agent_action_request_from_response(
                response,
                request_id=f"model-response:{current_packet_ref}:tool:{tool_iteration + 1}",
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                iteration=tool_iteration + 1,
                allowed_action_types=current_allowed_action_types,
                phase="tool_loop",
                require_json_action=current_requires_json_action,
            )
            if action_parse.error:
                action_parse = await _repair_single_agent_action_parse(
                    action_parse,
                    response=response,
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": f"modelreq:{current_packet_ref}:tool-protocol-repair:{tool_iteration + 1}",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.protocol_repair",
                        "segment_plan": dict(compilation.packet.segment_plan or {}),
                        "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                    },
                    request_id=f"model-response:{current_packet_ref}:tool:{tool_iteration + 1}:repair",
                    turn_id=turn_id,
                    packet_ref=current_packet_ref,
                    iteration=tool_iteration + 1,
                    allowed_action_types=current_allowed_action_types,
                    phase="tool_loop",
                )
            if action_parse.error:
                async for event in emit_agent_authored_closeout(
                    reason=str(dict(action_parse.error or {}).get("code") or "single_agent_turn_protocol_error"),
                    phase="tool_loop_protocol_error",
                    terminal_reason=str(dict(action_parse.error or {}).get("code") or "single_agent_turn_protocol_error"),
                    protocol_error=dict(action_parse.error or {}),
                ):
                    yield event
                terminal_recorded = True
                return
            if (
                action_parse.action_request is not None
                and action_parse.action_request.action_type == "active_work_control"
            ):
                if tool_iteration >= _MAX_SINGLE_TURN_TOOL_ITERATIONS:
                    async for event in emit_tool_limit_closeout(
                        attempted_actions=[action_parse.action_request],
                        phase="active_work_control",
                    ):
                        yield event
                    return
                tool_iteration += 1
                control_action = action_parse.action_request
                async for event in _action_feedback_segment_events(
                    action_request=control_action,
                    response=response,
                    assistant_stream_normalizer=assistant_stream_normalizer,
                    turn_id=turn_id,
                    turn_run_id=turn_run.turn_run_id if turn_run is not None else "",
                    phase="active_work_control",
                    iteration=tool_iteration,
                    emitted_feedback_segments=emitted_feedback_segments,
                ):
                    yield event
                admission = admit_model_action(
                    control_action,
                    packet_allowed_action_types=current_allowed_action_types,
                    invocation_kind="single_agent_turn",
                    definitions_by_name=tool_definitions_by_name,
                    allowed_tool_names=set(runtime_tool_plan.dispatchable_tool_names),
                    runtime_profile=_runtime_profile_payload(runtime_assembly),
                    permission_mode=runtime_permission_mode,
                    side_effect_policy="runtime_authorized",
                )
                if runtime_host is not None and turn_run is not None:
                    event = _record_model_action_admission(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        action_request=control_action,
                        admission=admission,
                        packet_ref=current_packet_ref,
                    )
                    yield {"type": "model_action_admission", "event": event}
                active_control = dict(control_action.active_work_control or {})
                if admission.decision != "allow":
                    active_status = "blocked"
                    active_terminal_reason = admission.system_reason or admission.decision
                    active_content = admission.user_visible_reason or active_terminal_reason or "active_work_control_denied"
                else:
                    active_result = await apply_active_work_control(active_control)
                    if isinstance(active_result, dict):
                        active_content = str(active_result.get("content") or active_result.get("message") or "").strip()
                        active_status = str(active_result.get("status") or "completed").strip()
                        active_terminal_reason = str(active_result.get("terminal_reason") or active_result.get("reason") or "").strip()
                    else:
                        active_content = str(active_result or "").strip()
                        active_status = "completed"
                        active_terminal_reason = ""
                resolved_action = str(active_control.get("resolved_action") or active_control.get("action") or "active_work_control")
                active_terminal_reason = active_terminal_reason or resolved_action
                is_task_steer = resolved_action in _STEER_ACTIVE_WORK_ACTIONS
                if is_task_steer and active_status != "blocked":
                    yield {
                        "type": "active_task_steer_accepted",
                        "summary": active_content,
                        "status": "accepted",
                        "terminal_reason": resolved_action,
                        **active_work_event_refs(),
                        "runtime_branch": dict(runtime_branch or {}),
                        "active_work": dict(active_control),
                    }
                observation_payload = _active_work_control_observation_payload(
                    action_request=control_action,
                    admission=admission,
                    active_work_control=active_control,
                    status=active_status,
                    terminal_reason=active_terminal_reason,
                    content=active_content,
                    runtime_branch=runtime_branch,
                    active_work_refs=active_work_event_refs(),
                )
                tool_observation_payloads.append(observation_payload)
                status_title, status_detail, status_state = _active_work_control_status_projection(
                    active_work_control=active_control,
                    status=active_status,
                    terminal_reason=active_terminal_reason,
                    content=active_content,
                )
                observed_event: dict[str, Any] = {}
                if runtime_host is not None and turn_run is not None:
                    event = runtime_host.event_log.append(
                        turn_run.turn_run_id,
                        "active_work_control_observed",
                        payload={
                            "turn_id": turn_id,
                            "model_action_request": control_action.to_dict(),
                            "observation": observation_payload,
                            "title": status_title,
                            "detail": status_detail,
                            "state": status_state,
                            "phase": "work_control",
                        },
                        refs={
                            "turn_ref": turn_id,
                            "turn_run_ref": turn_run.turn_run_id,
                            "runtime_invocation_packet_ref": current_packet_ref,
                            **active_work_event_refs(),
                        },
                    )
                    observed_event = event.to_dict()
                yield {
                    "type": "runtime_status",
                    "title": status_title,
                    "detail": status_detail,
                    "state": status_state,
                    "phase": "work_control",
                    "terminal_reason": active_terminal_reason,
                    "runtime_event_id": str(observed_event.get("event_id") or "") if observed_event else "",
                    "runtime_run_id": str(observed_event.get("run_id") or "") if observed_event else "",
                    "created_at": observed_event.get("created_at") if observed_event else None,
                    **active_work_event_refs(),
                }
                if not _active_work_control_requires_followup(active_control, status=active_status):
                    if runtime_host is not None and turn_run is not None:
                        terminal = _record_turn_terminal(
                            runtime_host,
                            turn_run=turn_run,
                            turn_id=turn_id,
                            status="completed",
                            terminal_reason=active_terminal_reason,
                            payload={
                                "active_work_control": dict(active_control),
                                "observation": observation_payload,
                            },
                        )
                        terminal_recorded = True
                        yield {"type": "agent_turn_terminal", "event": terminal}
                    yield final_answer_event(
                        content="",
                        answer_channel="runtime_control",
                        answer_source="harness.single_agent_turn.active_work_control",
                        terminal_reason=active_terminal_reason,
                        execution_posture="active_work_control",
                        extra={
                            "runtime_branch": dict(runtime_branch or {}),
                            "active_work": dict(active_control),
                            **active_work_event_refs(),
                        },
                    )
                    return
                api_protocol_messages.extend(
                    _active_work_control_protocol_messages(
                        response,
                        action_parse.native_tool_calls,
                        observation=observation_payload,
                        turn_id=turn_id,
                    )
                )
                followup_compilation = compiler.compile_observation_followup_packet(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_invocation_id=agent_invocation_id,
                    user_message=user_message,
                    history=history,
                    session_context=session_context,
                    observations=tool_observation_payloads,
                    agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id") or "main_interactive_agent"),
                    model_selection=dict(model_selection or {}),
                    available_tools=list(current_available_tools or []),
                    runtime_assembly=runtime_assembly,
                )
                model_messages = _sanitize_model_messages(
                    list(followup_compilation.packet.model_messages),
                    turn_id=turn_id,
                    source="harness.loop.single_agent_turn.active_work_control_followup",
                )
                current_packet_ref = str(followup_compilation.packet.packet_id)
                current_allowed_action_types = tuple(followup_compilation.packet.allowed_action_types)
                current_available_tools = tuple(followup_compilation.packet.available_tools or ())
                current_requires_json_action = True
                response = None
                async for model_event in _invoke_single_turn_model_with_stream_events(
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": f"modelreq:{current_packet_ref}:active-work-control-followup:{tool_iteration}",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": current_packet_ref,
                        "source": "harness.single_agent_turn.active_work_control_followup",
                        "segment_plan": dict(followup_compilation.packet.segment_plan or {}),
                        "prompt_manifest": {
                            **dict(followup_compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_active_work_control_followup",
                            "followup_iteration": tool_iteration,
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
                if action_parse.action_request is not None:
                    repaired_or_parsed_final_action = action_parse
                break
            if tool_iteration >= _MAX_SINGLE_TURN_TOOL_ITERATIONS:
                async for event in emit_tool_limit_closeout(
                    attempted_actions=list(tool_actions),
                    phase="tool_loop",
                ):
                    yield event
                return
            tool_iteration += 1
            feedback_action = tool_actions[0] if tool_actions else action_parse.action_request
            if feedback_action is not None:
                async for event in _action_feedback_segment_events(
                    action_request=feedback_action,
                    response=response,
                    assistant_stream_normalizer=assistant_stream_normalizer,
                    turn_id=turn_id,
                    turn_run_id=turn_run.turn_run_id if turn_run is not None else "",
                    phase="tool_call",
                    iteration=tool_iteration,
                    emitted_feedback_segments=emitted_feedback_segments,
                ):
                    yield event
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
                )
                action_permit = action_permit_from_admission(
                    tool_action,
                    admission,
                    invocation_kind="agent_turn",
                    packet_allowed_action_types=current_allowed_action_types,
                    allowed_tool_names=set(runtime_tool_plan.dispatchable_tool_names),
                    permission_mode=runtime_permission_mode,
                    side_effect_policy="runtime_authorized",
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
                current_requires_json_action = True
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
            action_parse = _single_agent_action_request_from_response(
                response,
                request_id=f"model-response:{current_packet_ref}:final",
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                iteration=tool_iteration + 1,
                allowed_action_types=current_allowed_action_types,
                phase="final",
                require_json_action=current_requires_json_action,
            )
        if action_parse.error:
            action_parse = await _repair_single_agent_action_parse(
                action_parse,
                response=response,
                model_runtime=model_runtime,
                model_messages=model_messages,
                model_selection=dict(model_selection or {}),
                accounting_context={
                    "request_id": f"modelreq:{current_packet_ref}:final-protocol-repair",
                    "session_id": session_id,
                    "run_id": turn_run.turn_run_id if turn_run is not None else "",
                    "turn_id": turn_id,
                    "packet_ref": current_packet_ref,
                    "source": "harness.single_agent_turn.protocol_repair",
                    "segment_plan": dict(compilation.packet.segment_plan or {}),
                    "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                },
                request_id=f"model-response:{current_packet_ref}:final:repair",
                turn_id=turn_id,
                packet_ref=current_packet_ref,
                iteration=tool_iteration + 1,
                allowed_action_types=tuple(item for item in current_allowed_action_types if item != "tool_call"),
                phase="final",
            )
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
                content = admission.user_visible_reason or "本轮动作没有通过运行时准入，运行时未执行该动作。"
                commit_decision = await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.admission",
                    api_protocol_messages=_final_api_protocol_messages(
                        api_protocol_messages,
                        response,
                        tool_calls,
                        turn_id=turn_id,
                        tool_result_content=content,
                        final_content=content,
                    ),
                )
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.admission",
                    terminal_status="blocked",
                    terminal_reason=admission.system_reason or admission.decision,
                    final_extra={"runtime_branch": dict(runtime_branch or {}), "admission": admission.to_dict()},
                    commit_decision=commit_decision,
                ):
                    yield event
                return
            if action_request.action_type == "respond":
                content = action_request.final_answer or stringify_content(getattr(response, "content", response)).strip()
                if not content:
                    content = "模型选择直接回答，但没有提供可用回答内容。"
                commit_decision = await _commit_final_message(
                    commit_assistant_message,
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
                async for event in start_task_from_action_request(action_request):
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
                content = action_request.blocking_reason or "当前请求无法继续处理。"
                commit_decision = await _commit_final_message(
                    commit_assistant_message,
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
                content = action_request.user_question or "我需要你补充一点信息。"
                commit_decision = await _commit_final_message(
                    commit_assistant_message,
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
            if action_request.action_type == "active_work_control":
                protocol_error = _single_agent_protocol_error(
                    code="single_agent_turn_active_work_control_not_observed",
                    reason="active_work_control_final_dispatch_unreachable",
                    diagnostics={
                        "phase": "final",
                        "action_request": action_request.to_dict(),
                    },
                )
                async for event in emit_agent_authored_closeout(
                    reason="single_agent_turn_active_work_control_not_observed",
                    phase="final_active_work_control_protocol_error",
                    terminal_reason="single_agent_turn_active_work_control_not_observed",
                    protocol_error=protocol_error,
                ):
                    yield event
                terminal_recorded = True
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

        content = stringify_content(getattr(response, "content", response)).strip()
        if not content:
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status="failed",
                    terminal_reason="single_agent_turn_empty_response",
                )
                terminal_recorded = True
                yield {"type": "agent_turn_terminal", "event": terminal}
            yield error_event(
                content="模型没有返回可用的回复内容。",
                code="single_agent_turn_empty_response",
                reason="single_agent_turn_empty_response",
            )
            return
        commit_decision = await _commit_final_message(
            commit_assistant_message,
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
        yield {
            "type": "assistant_message_committed",
            "answer_channel": commit_decision.answer_channel,
            "answer_source": commit_decision.answer_source,
            "answer_canonical_state": commit_decision.canonical_state,
            "answer_persist_policy": commit_decision.persist_policy,
            "answer_finalization_policy": commit_decision.finalization_policy,
            "answer_fallback_reason": commit_decision.fallback_reason,
        }
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
                content="模型生成本轮回复时失败。",
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
                content="模型生成本轮回复时失败。",
                code="single_agent_turn_model_failed",
                reason=str(exc),
            )
    return error_event(
        content="当前模型运行时不可用，无法完成本轮处理。",
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
    emit_legacy_content_delta = bool(stream_policy.get("legacy_content_delta_public_stream") is True) and bool(allow_assistant_text_delta)
    stream_ref = str(accounting_context.get("request_id") or "")
    assistant_normalizer = AssistantStreamNormalizer(
        stream_ref=stream_ref,
        message_ref=assistant_message_ref(turn_id=str(accounting_context.get("turn_id") or ""), stream_ref=stream_ref),
        turn_run_id=str(accounting_context.get("run_id") or accounting_context.get("turn_run_id") or ""),
        task_run_id=str(accounting_context.get("task_run_id") or ""),
        answer_source=str(accounting_context.get("source") or "harness.single_agent_turn"),
    ) if emit_assistant_text_delta else None
    legacy_delta_index = 0
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
                if emit_legacy_content_delta and _public_stream_delta_allowed(raw_content):
                    legacy_delta_index += 1
                    yield _single_agent_content_delta_event(
                        delta_text,
                        delta_index=legacy_delta_index,
                        raw_content=raw_content,
                        accounting_context=accounting_context,
                    )
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
                if emit_legacy_content_delta and _public_stream_delta_allowed(raw_content):
                    legacy_delta_index += 1
                    yield _single_agent_content_delta_event(
                        delta_text,
                        delta_index=legacy_delta_index,
                        raw_content=raw_content,
                        accounting_context=accounting_context,
                    )
        else:
            response = await _invoke_single_turn_model(
                model_runtime=model_runtime,
                model_messages=model_messages,
                model_selection=model_selection,
                accounting_context=accounting_context,
                native_tools=native_tools,
            )
            yield {"type": _INTERNAL_MODEL_RESPONSE_EVENT, "response": response, "assistant_stream_normalizer": assistant_normalizer}
            return
    except Exception as exc:
        logger.exception("single agent turn streaming model invocation failed")
        yield {
            "type": _INTERNAL_MODEL_RESPONSE_EVENT,
            "assistant_stream_normalizer": assistant_normalizer,
            "response": error_event(
                content="模型生成本轮回复时失败。",
                code="single_agent_turn_model_failed",
                reason=str(exc),
            ),
        }
        return
    response = aggregated_response if aggregated_response is not None else raw_content
    yield {"type": _INTERNAL_MODEL_RESPONSE_EVENT, "response": response, "assistant_stream_normalizer": assistant_normalizer}


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


def _public_stream_delta_allowed(raw_content: str) -> bool:
    text = str(raw_content or "").lstrip()
    if not text:
        return False
    lowered = text[:80].lower()
    if lowered.startswith(("{", "[", "```json")):
        return False
    if any(marker in lowered for marker in ('"action_type"', '"tool_call"', '"authority"', "model_action_request")):
        return False
    return not contains_internal_protocol(text) and not contains_inline_pseudo_tool_call(text)


def _single_agent_content_delta_event(
    content: str,
    *,
    delta_index: int,
    raw_content: str,
    accounting_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "content_delta",
        "content": content,
        "delta_index": delta_index,
        "delta_chars": len(content),
        "accumulated_chars": len(raw_content),
        "request_id": str(accounting_context.get("request_id") or ""),
        "packet_ref": str(accounting_context.get("packet_ref") or ""),
        "source": str(accounting_context.get("source") or "harness.single_agent_turn"),
    }


async def _repair_single_agent_action_parse(
    action_parse: SingleAgentActionParse,
    *,
    response: Any,
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
    error = dict(action_parse.error or {})
    code = str(error.get("code") or "")
    if code not in _REPAIRABLE_SINGLE_AGENT_PROTOCOL_ERRORS:
        return action_parse
    repair_messages = _single_agent_protocol_repair_messages(
        model_messages,
        error=error,
        response=response,
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
            "source": "harness.single_agent_turn.protocol_repair",
            "prompt_manifest": {
                **dict(dict(accounting_context or {}).get("prompt_manifest") or {}),
                "invocation_kind": "single_agent_turn_protocol_repair",
                "repair_phase": phase,
                "original_protocol_error": code,
            },
        },
        native_tools=[],
    )
    if isinstance(repair_response, dict) and repair_response.get("type") == "error":
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=[],
            error=_single_agent_protocol_error(
                code="single_agent_turn_protocol_repair_failed",
                reason=str(repair_response.get("code") or "protocol_repair_model_failed"),
                diagnostics={
                    "original_error": error,
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
        phase=f"{phase}_protocol_repair",
        require_json_action=True,
    )
    if repaired.error:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=list(repaired.native_tool_calls or []),
            error=_single_agent_protocol_error(
                code="single_agent_turn_protocol_repair_failed",
                reason=str(dict(repaired.error or {}).get("code") or "protocol_repair_invalid"),
                diagnostics={
                    "original_error": error,
                    "repair_error": dict(repaired.error or {}),
                    "phase": phase,
                },
            ),
        )
    if repaired.action_request is None:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=[],
            error=_single_agent_protocol_error(
                code="single_agent_turn_protocol_repair_failed",
                reason="protocol_repair_returned_no_action",
                diagnostics={"original_error": error, "phase": phase},
            ),
        )
    repaired_action = replace(
        repaired.action_request,
        diagnostics={
            **dict(repaired.action_request.diagnostics or {}),
            "protocol_repair": {
                "authority": "harness.loop.single_agent_turn.protocol_repair",
                "original_error_code": code,
                "original_error_reason": str(error.get("reason") or ""),
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


def _single_agent_protocol_repair_messages(
    model_messages: list[dict[str, Any]],
    *,
    error: dict[str, Any],
    response: Any,
    turn_id: str,
    allowed_action_types: tuple[str, ...],
    phase: str,
) -> list[dict[str, Any]]:
    diagnostics = dict(error.get("diagnostics") or {})
    repair_payload = {
        "allowed_action_types": list(allowed_action_types),
        "phase": phase,
        "protocol_error": {
            "code": str(error.get("code") or ""),
            "reason": str(error.get("reason") or ""),
            "diagnostics": diagnostics,
        },
        "previous_response": {
            "content_preview": _compact_text(stringify_content(getattr(response, "content", response)), limit=1200),
            "native_tool_call_count": diagnostics.get("native_tool_call_count"),
            "tool_names": list(diagnostics.get("tool_names") or []),
            "action_types": list(diagnostics.get("action_types") or []),
        },
        "required_protocol": _single_agent_protocol_repair_contract(allowed_action_types),
    }
    tool_repair_allowed = "tool_call" in set(allowed_action_types or ())
    repair_target_text = "一个合法的控制裁决或一个合法工具调用" if tool_repair_allowed else "一个合法的最终控制裁决"
    non_tool_alternatives = ["询问用户", "阻止或直接回答"]
    if "request_task_run" in set(allowed_action_types or ()):
        non_tool_alternatives.insert(1, "请求持续任务")
    tool_repair_instruction = (
        "如果需要普通工具，只能输出一个 action_type=tool_call 的动作；不要混入 ask_user、block、request_task_run 或 active_work_control。\n"
        if tool_repair_allowed
        else f"当前是协议修复或收口阶段，普通工具服务面未开放；这不是执行安全结论。如需更多执行能力，只能在允许动作内选择{'、'.join(non_tool_alternatives)}。\n"
    )
    repair_instruction = (
        f"{SINGLE_AGENT_PROTOCOL_REPAIR_PROMPT}\n\n"
        f"你只负责把上一轮模型输出修复为{repair_target_text}。\n"
        "系统没有执行上一轮违规输出；这是一条发给你的协议修复信号，不是给用户的正文。\n"
        "如果需要控制裁决，只能选择一个 action_type。\n"
        f"{tool_repair_instruction}"
        "必须只输出一个 JSON 对象；不要使用 Markdown 代码块；不要输出 provider-native tool_calls；"
        "不要在 JSON 前后附加解释文字。\n"
        "修复输入：\n"
        f"{json.dumps(repair_payload, ensure_ascii=False, sort_keys=True)}"
    )
    return _sanitize_model_messages(
        [
            *[dict(item) for item in list(model_messages or []) if isinstance(item, dict)],
            {"role": "user", "content": repair_instruction, "turn_id": turn_id},
        ],
        turn_id=turn_id,
        source="harness.loop.single_agent_turn.protocol_repair",
    )


def _single_agent_protocol_repair_contract(allowed_action_types: tuple[str, ...]) -> dict[str, Any]:
    allowed = [str(item) for item in list(allowed_action_types or ()) if str(item)]
    shapes: list[dict[str, Any]] = []
    if "tool_call" in allowed:
        shapes.append(
            {
                "action_type": "tool_call",
                "shape": {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "tool_call",
                    "tool_call": {
                        "tool_name": "read_file",
                        "args": {"path": "README.md"},
                    },
                    "public_progress_note": "我会先核对可见事实，再给出判断。",
                    "public_action_state": {
                        "current_judgment": "当前需要补充文件事实才能判断。",
                        "next_action": "核对文件内容。",
                    },
                },
            }
        )
    if "respond" in allowed:
        shapes.append(
            {
                "action_type": "respond",
                "shape": {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "respond",
                    "final_answer": "在这里写给用户的最终回复。",
                    "public_progress_note": "已有事实足以直接回复。",
                    "public_action_state": {
                        "current_judgment": "当前事实足以回复用户。",
                        "next_action": "整理回复。",
                    },
                },
            }
        )
    if "ask_user" in allowed:
        shapes.append(
            {
                "action_type": "ask_user",
                "shape": {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "ask_user",
                    "user_question": "请补充一个继续执行所必需的信息。",
                    "public_progress_note": "需要用户补充关键信息。",
                    "public_action_state": {
                        "current_judgment": "缺少继续执行所必需的信息。",
                        "next_action": "向用户询问。",
                    },
                },
            }
        )
    if "block" in allowed:
        shapes.append(
            {
                "action_type": "block",
                "shape": {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "block",
                    "blocking_reason": "说明当前无法可靠继续的具体原因。",
                    "public_progress_note": "当前请求无法可靠继续。",
                    "public_action_state": {
                        "current_judgment": "继续执行会越过事实或权限边界。",
                        "next_action": "说明阻塞原因。",
                    },
                },
            }
        )
    if "request_task_run" in allowed:
        shapes.append(
            {
                "action_type": "request_task_run",
                "shape": {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "request_task_run",
                    "task_contract_seed": {
                        "user_visible_goal": "把用户目标写成可见任务目标。",
                        "task_run_goal": "把任务执行目标写清楚。",
                        "working_scope": {
                            "target_objects": ["列出任务对象、文件、材料或目标。"],
                            "workspace_refs": [],
                            "source_refs": [],
                            "excluded_scope": [],
                            "known_constraints": ["列出用户明确约束。"],
                        },
                        "completion_criteria": ["列出可验证的完成条件。"],
                        "capability_intent": {
                            "needed_capability_groups": ["file_work"],
                            "preferred_tool_namespaces": [],
                            "requires_deferred_tool_loading": True,
                            "reason": "说明需要这些系统服务的原因。",
                        },
                        "skill_intent": {
                            "selected_skill_ids": [],
                            "candidate_skill_ids": [],
                            "required_capability_tags": [],
                            "reason": "",
                        },
                        "observation_contract": {
                            "evidence_policy": "observation_required",
                            "progress_granularity": "step",
                            "finalization_requires_evidence": True,
                        },
                    },
                    "public_progress_note": "我会按可验收目标推进，并用结果和验证收口。",
                    "public_action_state": {
                        "current_judgment": "目标需要进入可验收执行流程。",
                        "next_action": "进入执行流程。",
                    },
                },
            }
        )
    if "active_work_control" in allowed:
        shapes.append(
            {
                "action_type": "active_work_control",
                "shape": {
                    "authority": "harness.loop.model_action_request",
                    "action_type": "active_work_control",
                    "active_work_control": {
                        "action": "continue_active_work",
                        "relation_to_current_work": "current_work",
                        "turn_response_policy": "active_work_only",
                        "answer_obligation": "none",
                    },
                    "public_progress_note": "我会按当前目标继续推进。",
                    "public_action_state": {
                        "current_judgment": "用户要求继续当前工作。",
                        "next_action": "继续当前工作。",
                    },
                },
            }
        )
    return {
        "authority": "harness.loop.model_action_request",
        "json_only": True,
        "single_action_only": True,
        "allowed_action_types": allowed,
        "forbidden_output": [
            "provider_native_tool_calls",
            "markdown_fence",
            "text_before_or_after_json",
            "multiple_json_objects",
            "multiple_control_actions",
        ],
        "allowed_action_shapes": shapes,
    }


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
) -> SingleAgentActionParse:
    protocol = model_response_protocol_from_response(
        response,
        request_id=request_id,
        turn_id=turn_id,
        require_json_action=require_json_action,
        allow_native_tool_calls=True,
    )
    native_tool_calls = [dict(item) for item in protocol.native_tool_calls]
    json_payload = _normalize_single_agent_json_payload(
        dict(protocol.json_payload or {}),
        request_id=request_id,
        turn_id=turn_id,
        packet_ref=packet_ref,
    )
    json_action_like = _is_model_action_json_payload(json_payload)
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
            allowed_action_types=allowed_action_types,
        )
        if action_request is None:
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
                            repair_instruction="请按本轮 model_decision_contract 和 action schema 重新提交一个合法 JSON action。",
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
    if not native_tool_calls:
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
        native_errors: list[dict[str, Any]] = []
        for call in native_tool_calls:
            tool_name = str(dict(call or {}).get("name") or "").strip()
            if tool_name in _CONTROL_ACTION_NAMES:
                action_issue = _protocol_action_issue(
                    category="protocol_violation",
                    code="control_action_requires_json_action",
                    requested_action_type=tool_name,
                    requested_tool_name=tool_name,
                    repair_instruction="控制裁决必须输出 JSON action；请保留原控制意图并改用 JSON action 重新提交。",
                )
                native_errors.append(
                    {
                        "authority": "harness.loop.single_agent_turn.native_action_parser",
                        "code": "native_control_action_requires_json_action",
                        "reason": "native_control_action_requires_json_action",
                        "native_tool_call": _native_tool_call_diagnostics(dict(call or {})),
                        "action_issue": action_issue,
                        "repairable": True,
                        "repair_contract": {
                            "required_transport": "json_action",
                            "action_type": tool_name,
                        },
                    }
                )
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
    native_parse = _action_requests_from_native_tool_calls_with_diagnostics(
        native_tool_calls,
        turn_id=turn_id,
        packet_ref=packet_ref,
        iteration=iteration,
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


def _normalize_single_agent_json_payload(
    payload: dict[str, Any],
    *,
    request_id: str,
    turn_id: str,
    packet_ref: str,
) -> dict[str, Any]:
    del request_id, turn_id, packet_ref
    return dict(payload or {})


def _action_requests_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
) -> list[ModelActionRequest]:
    return list(
        _action_requests_from_native_tool_calls_with_diagnostics(
            tool_calls,
            turn_id=turn_id,
            packet_ref=packet_ref,
            iteration=iteration,
        ).actions
    )


def _action_requests_from_native_tool_calls_with_diagnostics(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
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
        if tool_name in _CONTROL_ACTION_NAMES:
            errors.append(
                {
                    "authority": "harness.loop.single_agent_turn.native_action_parser",
                    "code": "native_control_action_requires_json_action",
                    "reason": "native_control_action_requires_json_action",
                    "native_tool_call": _native_tool_call_diagnostics(call),
                    "action_issue": _protocol_action_issue(
                        category="protocol_violation",
                        code="control_action_requires_json_action",
                        requested_action_type=tool_name,
                        requested_tool_name=tool_name,
                        repair_instruction="控制裁决必须输出 JSON action；请保留原控制意图并改用 JSON action 重新提交。",
                    ),
                    "repairable": True,
                    "repair_contract": {
                        "required_transport": "json_action",
                        "action_type": tool_name,
                    },
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


def _single_agent_protocol_error(*, code: str, reason: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "reason": reason,
        "diagnostics": {
            "authority": "harness.loop.single_agent_turn.protocol_error",
            **dict(diagnostics or {}),
        },
    }


async def _action_feedback_segment_events(
    *,
    action_request: ModelActionRequest,
    response: Any,
    assistant_stream_normalizer: AssistantStreamNormalizer | None,
    turn_id: str,
    turn_run_id: str,
    phase: str,
    iteration: int,
    emitted_feedback_segments: set[str],
) -> AsyncIterator[dict[str, Any]]:
    content = _action_feedback_segment_text(action_request, response=response)
    if not content:
        return
    segment_key = f"{phase}:{iteration}:{content}"
    if segment_key in emitted_feedback_segments:
        return
    emitted_feedback_segments.add(segment_key)
    body_sequence = max(1, int(iteration) * 2 - 1)
    stream_ref = str(
        getattr(assistant_stream_normalizer, "stream_ref", "")
        or f"assistant-body:{turn_id}:{phase}:{iteration}"
    )
    extra = {
        "body_segment_id": stream_ref,
        "body_sequence": body_sequence,
        "segment_role": "stage_feedback",
    }
    if assistant_stream_normalizer is not None:
        for event in assistant_final_stream_events(
            assistant_stream_normalizer,
            content=content,
            answer_channel="stage_feedback",
            answer_source=f"harness.single_agent_turn.{phase}.feedback",
            terminal_reason="stage_feedback",
            answer_canonical_state="stable_feedback",
            answer_persist_policy="persist_canonical",
            turn_run_id=turn_run_id,
            extra=extra,
        ):
            yield event
        return
    event = assistant_body_final_event(
        content=content,
        answer_channel="stage_feedback",
        answer_source=f"harness.single_agent_turn.{phase}.feedback",
        turn_id=turn_id,
        turn_run_id=turn_run_id,
        stream_ref=stream_ref,
        body_sequence=body_sequence,
        terminal_reason="stage_feedback",
        execution_posture="single_agent_turn",
        extra=extra,
    )
    if event:
        yield event


def _action_feedback_segment_text(action_request: ModelActionRequest, *, response: Any) -> str:
    state = dict(action_request.public_action_state or {})
    candidates: list[Any] = [
        state.get("current_judgment"),
        action_request.public_progress_note,
    ]
    if action_request.action_type == "tool_call":
        candidates.append(_response_content_public_feedback(response))
    for candidate in candidates:
        text = public_runtime_progress_summary(candidate or "").strip()
        if _is_public_feedback_segment(text):
            return text[:220].rstrip()
    return ""


def _response_content_public_feedback(response: Any) -> str:
    text = stringify_content(getattr(response, "content", response)).strip()
    if not text:
        return ""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[", "```json")):
        return ""
    if not _meaningful_visible_answer(text):
        return ""
    return text


def _is_public_feedback_segment(text: str) -> bool:
    value = sanitize_visible_assistant_content(str(text or "")).strip()
    if not value or not _meaningful_visible_answer(value):
        return False
    normalized = " ".join(value.split()).strip()
    generic_values = {
        "开始处理",
        "开始处理。",
        "正在处理",
        "正在处理。",
        "处理完成",
        "处理完成。",
        "正在思考",
        "正在思考。",
        "正在调用工具",
        "正在调用工具。",
        "已发起工具调用",
        "已发起工具调用。",
        "需要用户补充信息后才能继续。",
        "当前请求无法继续执行。",
    }
    if normalized in generic_values:
        return False
    generic_prefixes = (
        "我会开始处理",
        "我将调用工具",
        "我正在调用",
        "正在运行工具",
        "运行工具 ",
        "已发起工具调用，正在等待工具返回",
    )
    return not any(normalized.startswith(prefix) for prefix in generic_prefixes)


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
        if not tool_name or tool_name in _CONTROL_ACTION_NAMES:
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
    tool_call_id = str(tool_call.get("id") or action_request.request_id).strip()
    tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    return {
        "id": tool_call_id,
        "name": tool_name,
        "tool_name": tool_name,
        "args": tool_args,
        "type": "tool_call",
    }


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
    tool_call_id = str(tool_call.get("id") or action_request.request_id)
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
    tool_call_id = str(tool_call.get("id") or action_request.request_id)
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
            await asyncio.gather(*pending, return_exceptions=True)
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
        try:
            invocation = _invoke_turn_tool_for_batch_row(
                row,
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly,
                turn_run=turn_run,
                session_id=session_id,
                turn_id=turn_id,
                packet_ref=packet_ref,
                tool_plan=tool_plan,
            )
            if timeout_seconds > 0:
                result = await asyncio.wait_for(invocation, timeout=timeout_seconds)
            else:
                result = await invocation
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            result = TimeoutError(f"tool_batch_group_timeout_after_{timeout_seconds:g}s")
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
    return 300.0


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
    tool_call = dict(action_request.tool_call or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    tool_call_id = str(tool_call.get("id") or action_request.request_id)
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
        sandbox_root = str(runtime_cache_manager_for_host(runtime_host).sandbox_root(namespace))
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


def _active_work_control_protocol_messages(
    response: Any,
    tool_calls: list[dict[str, Any]],
    *,
    observation: dict[str, Any],
    turn_id: str,
) -> list[dict[str, Any]]:
    observation_text = _active_work_control_observation_text(observation)
    native_messages = _native_action_protocol_messages(
        response,
        tool_calls,
        turn_id=turn_id,
        tool_result_content=observation_text,
    )
    if native_messages:
        return native_messages
    return [
        _assistant_final_protocol_message(response, turn_id=turn_id, include_reasoning=True),
        {
            "role": "user",
            "content": observation_text,
            "turn_id": turn_id,
        },
    ]


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


def _active_work_control_observation_text(observation: dict[str, Any]) -> str:
    return (
        "当前工作控制观察：系统已经尝试执行你提交的当前工作控制。"
        "以下是执行事实，不是给用户的最终回复。请基于这些事实继续判断本轮请求；"
        "如果已经可以答复，就用本轮允许的动作格式向用户给出自然回复。\n"
        f"{json.dumps(observation, ensure_ascii=False, sort_keys=True)}"
    )


def _active_work_control_observation_payload(
    *,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
    active_work_control: dict[str, Any],
    status: str,
    terminal_reason: str,
    content: str,
    runtime_branch: dict[str, Any],
    active_work_refs: dict[str, Any],
) -> dict[str, Any]:
    normalized_status = str(status or "").strip() or "completed"
    applied = normalized_status != "blocked" and str(admission.decision or "").strip() == "allow"
    return {
        "authority": "harness.loop.active_work_control_observation",
        "observation_kind": "active_work_control",
        "applied": applied,
        "status": normalized_status,
        "terminal_reason": str(terminal_reason or "").strip(),
        "runtime_result": str(content or "").strip(),
        "active_work_control": dict(active_work_control or {}),
        "model_action_request": action_request.to_dict(),
        "admission": admission.to_dict(),
        "runtime_branch": dict(runtime_branch or {}),
        "active_work_refs": dict(active_work_refs or {}),
        "followup_instruction": "基于该观察继续判断；不要向用户暴露协议字段；不要仅因控制未执行就要求用户重复已经明确的请求。",
    }


def _active_work_control_status_projection(
    *,
    active_work_control: dict[str, Any],
    status: str,
    terminal_reason: str,
    content: str,
) -> tuple[str, str, str]:
    normalized_status = str(status or "").strip()
    action = str(active_work_control.get("resolved_action") or active_work_control.get("action") or terminal_reason or "").strip()
    if normalized_status == "blocked":
        return "当前工作控制未执行", "边界校验未通过，模型会继续处理当前请求。", "warning"
    if action == "continue_active_work":
        return "继续当前工作", "当前工作已进入继续处理流程。", "running"
    if action == "pause_active_work":
        return "暂停当前工作", "暂停请求已记录。", "done"
    if action == "stop_active_work":
        return "停止当前工作", "停止请求已记录。", "stopped"
    if action == "append_instruction_to_active_work":
        return "已收到补充要求", "补充要求已进入当前工作队列。", "running"
    if action in {"answer_about_active_work", "answer_then_continue_active_work"}:
        return "查看当前进展", str(content or "").strip() or "当前工作进展已同步。", "done"
    return "当前工作控制", "当前工作控制状态已更新。", "done"


def _active_work_control_requires_followup(active_work_control: dict[str, Any], *, status: str) -> bool:
    if str(status or "").strip().lower() == "blocked":
        return True
    control = dict(active_work_control or {})
    action = str(control.get("resolved_action") or control.get("action") or "").strip()
    obligation = str(control.get("answer_obligation") or "").strip().lower()
    response_policy = str(control.get("turn_response_policy") or "").strip().lower()
    user_turn_kind = str(control.get("user_turn_kind") or "").strip().lower()
    if obligation in {"direct_answer_required", "answer_required", "must_answer", "answer_user_first"}:
        return True
    if response_policy in {"answer_only", "answer_then_active_work"}:
        return True
    if action in {"answer_about_active_work", "answer_then_continue_active_work"}:
        return True
    if obligation in {"none", "no_answer_required", "acknowledgement_only", "ack_only", "ack"}:
        return False
    if response_policy in {"active_work_only", "no_user_reply", "control_only", "status_only"}:
        return False
    if user_turn_kind in {"question", "complaint", "mixed"}:
        return True
    if action in _STEER_ACTIVE_WORK_ACTIONS:
        return True
    return action not in _STEER_ACTIVE_WORK_ACTIONS


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
    session_id: str,
    turn_id: str,
    content: str,
    answer_channel: str,
    answer_source: str,
    api_protocol_messages: list[dict[str, Any]] | None = None,
) -> CanonicalFinalTextDecision:
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
    await commit_assistant_message(
        session_id,
        {
            "role": "assistant",
            "content": decision.content,
            "turn_id": turn_id,
            **decision.to_payload(),
            "api_protocol_messages": sanitized_protocol_messages,
        },
    )
    return decision


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
) -> dict[str, Any]:
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
    event = runtime_host.event_log.append(
        run_id,
        "step_summary_recorded",
        payload=payload,
        refs={"turn_ref": turn_id},
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
    return {"type": "runtime_step_summary", **payload, "event": event.to_dict()}


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
