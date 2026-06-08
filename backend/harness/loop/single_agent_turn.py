from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
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
from runtime.prompt_accounting.serializer import normalize_messages
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


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
ApplyActiveWorkControl = Callable[[dict[str, Any]], Awaitable[str | dict[str, Any]]]

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
_CONTROL_NATIVE_TOOL_NAMES = {"request_task_run", "active_work_control", "ask_user", "block"}
_REPAIRABLE_SINGLE_AGENT_PROTOCOL_ERRORS = {
    "single_agent_turn_multiple_native_actions",
    "single_agent_turn_multiple_action_sources",
    "single_agent_turn_invalid_native_action",
    "single_agent_turn_invalid_json_action",
    "single_agent_turn_json_action_required",
}


def _meaningful_visible_answer(content: str) -> bool:
    visible = sanitize_visible_assistant_content(str(content or "")).strip()
    if not visible:
        return False
    if visible in {">", "<", "...", "…", "---", "----"}:
        return False
    if contains_internal_protocol(visible) or contains_inline_pseudo_tool_call(visible):
        return False
    return any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in visible)


def _tool_limit_protocol_blocked_text() -> str:
    return "本轮已经达到工具预算上限，但模型返回了内部工具协议而不是可展示结论。系统已停止本轮输出，避免把工具调用残片当作回答。"


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
        ) -> AsyncIterator[dict[str, Any]]:
            nonlocal terminal_recorded
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
            yield final_answer_event(
                content=content,
                answer_channel=answer_channel,
                answer_source=answer_source,
                has_tool_receipt=has_tool_receipt,
                terminal_reason=terminal_reason,
                extra=dict(final_extra or {}),
            )
        response = await _invoke_single_turn_model(
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
        )
        tool_iteration = 0
        repaired_or_parsed_final_action: SingleAgentActionParse | None = None
        while True:
            if isinstance(response, dict) and response.get("type") == "error":
                break
            action_parse = _single_agent_action_request_from_response(
                response,
                request_id=f"model-response:{compilation.packet.packet_id}:tool:{tool_iteration + 1}",
                turn_id=turn_id,
                packet_ref=compilation.packet.packet_id,
                iteration=tool_iteration + 1,
                allowed_action_types=tuple(compilation.packet.allowed_action_types),
                phase="tool_loop",
                require_json_action=single_agent_requires_json_action,
            )
            if action_parse.error:
                action_parse = await _repair_single_agent_action_parse(
                    action_parse,
                    response=response,
                    model_runtime=model_runtime,
                    model_messages=model_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": f"modelreq:{compilation.packet.packet_id}:tool-protocol-repair:{tool_iteration + 1}",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": compilation.packet.packet_id,
                        "source": "harness.single_agent_turn.protocol_repair",
                        "segment_plan": dict(compilation.packet.segment_plan or {}),
                        "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                    },
                    request_id=f"model-response:{compilation.packet.packet_id}:tool:{tool_iteration + 1}:repair",
                    turn_id=turn_id,
                    packet_ref=compilation.packet.packet_id,
                    iteration=tool_iteration + 1,
                    allowed_action_types=tuple(compilation.packet.allowed_action_types),
                    phase="tool_loop",
                )
            if action_parse.error:
                async for event in _emit_single_agent_protocol_error(
                    action_parse.error,
                    commit_assistant_message=commit_assistant_message,
                    runtime_host=runtime_host,
                    turn_run=turn_run,
                    session_id=session_id,
                    turn_id=turn_id,
                    runtime_branch=runtime_branch,
                ):
                    yield event
                terminal_recorded = True
                return
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
                synthesis_messages = _sanitize_model_messages(
                    [
                        *model_messages,
                        {
                            "role": "user",
                            "content": (
                                "本轮工具观察已经达到运行边界。现在禁止继续调用工具。"
                                "请只基于当前用户问题、已有上下文和已经返回的工具观察直接回答用户。"
                                "如果事实不足，说明已知事实、缺口和下一步建议；不要再请求工具。"
                            ),
                            "turn_id": turn_id,
                        },
                    ],
                    turn_id=turn_id,
                    source="harness.loop.single_agent_turn.tool_limit_synthesis",
                )
                synthesis_segment_plan = _single_agent_turn_followup_segment_plan(
                    base_segment_plan=dict(compilation.packet.segment_plan or {}),
                    model_messages=synthesis_messages,
                    packet_id=compilation.packet.packet_id,
                    tool_iteration=tool_iteration + 1,
                )
                synthesis_response = await _invoke_single_turn_model(
                    model_runtime=model_runtime,
                    model_messages=synthesis_messages,
                    model_selection=dict(model_selection or {}),
                    accounting_context={
                        "request_id": f"modelreq:{compilation.packet.packet_id}:tool-limit-synthesis",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": compilation.packet.packet_id,
                        "source": "harness.single_agent_turn.tool_limit_synthesis",
                        "segment_plan": synthesis_segment_plan,
                        "prompt_manifest": {
                            **dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                            "invocation_kind": "single_agent_turn_tool_limit_synthesis",
                            "segment_plan_ref": str(synthesis_segment_plan.get("segment_plan_id") or ""),
                        },
                    },
                    native_tools=[],
                )
                if isinstance(synthesis_response, dict) and synthesis_response.get("type") == "error":
                    yield synthesis_response
                    content = "我已经连续检查了几次，但无工具收口也没有成功生成可靠回复。本轮先停止，避免继续无效操作。"
                    terminal_status = "failed"
                    answer_channel = "blocked"
                    completion_state = "tool_limit_synthesis_failed"
                else:
                    synthesis_parse = _single_agent_action_request_from_response(
                        synthesis_response,
                        request_id=f"model-response:{compilation.packet.packet_id}:tool-limit-synthesis",
                        turn_id=turn_id,
                        packet_ref=compilation.packet.packet_id,
                        iteration=tool_iteration + 1,
                        allowed_action_types=("respond", "ask_user", "block"),
                        phase="tool_limit_synthesis",
                        require_json_action=False,
                    )
                    raw_content = stringify_content(getattr(synthesis_response, "content", synthesis_response)).strip()
                    action_request = synthesis_parse.action_request
                    if synthesis_parse.error or synthesis_parse.tool_actions or (
                        action_request is not None and action_request.action_type not in {"respond", "ask_user", "block"}
                    ):
                        content = _tool_limit_protocol_blocked_text()
                        terminal_status = "blocked"
                        answer_channel = "blocked"
                        completion_state = "tool_limit_protocol_blocked"
                    elif action_request is not None and action_request.action_type == "respond":
                        content = (action_request.final_answer or raw_content).strip()
                        if contains_internal_protocol(content) or contains_inline_pseudo_tool_call(content):
                            content = _tool_limit_protocol_blocked_text()
                            terminal_status = "blocked"
                            answer_channel = "blocked"
                            completion_state = "tool_limit_protocol_blocked"
                        else:
                            terminal_status = "completed" if _meaningful_visible_answer(content) else "blocked"
                            answer_channel = "conversation" if terminal_status == "completed" else "blocked"
                            completion_state = "tool_limit_synthesized" if terminal_status == "completed" else "tool_limit_missing_answer"
                    elif action_request is not None and action_request.action_type == "ask_user":
                        content = (action_request.user_question or raw_content).strip()
                        if contains_internal_protocol(content) or contains_inline_pseudo_tool_call(content):
                            content = _tool_limit_protocol_blocked_text()
                            terminal_status = "blocked"
                            answer_channel = "blocked"
                            completion_state = "tool_limit_protocol_blocked"
                        else:
                            terminal_status = "completed" if _meaningful_visible_answer(content) else "blocked"
                            answer_channel = "ask_user" if terminal_status == "completed" else "blocked"
                            completion_state = "tool_limit_ask_user" if terminal_status == "completed" else "tool_limit_missing_answer"
                    elif action_request is not None and action_request.action_type == "block":
                        content = (action_request.blocking_reason or raw_content or _tool_limit_protocol_blocked_text()).strip()
                        terminal_status = "blocked"
                        answer_channel = "blocked"
                        completion_state = "tool_limit_blocked"
                    else:
                        content = raw_content
                        if contains_internal_protocol(content) or contains_inline_pseudo_tool_call(content):
                            content = _tool_limit_protocol_blocked_text()
                            terminal_status = "blocked"
                            answer_channel = "blocked"
                            completion_state = "tool_limit_protocol_blocked"
                        elif _meaningful_visible_answer(content):
                            terminal_status = "completed"
                            answer_channel = "conversation"
                            completion_state = "tool_limit_synthesized"
                        else:
                            content = "我连续检查了几次仍没有形成可靠结论，先停在这里，避免继续无效操作。你可以补充要我重点核查的位置，或让我根据当前已知状态直接说明。"
                            terminal_status = "blocked"
                            answer_channel = "blocked"
                            completion_state = "tool_limit_missing_answer"
                answer_source = "harness.single_agent_turn.tool_limit_synthesis"
                protocol_final = _assistant_protocol_message_from_content(content, turn_id=turn_id)
                await _commit_final_message(
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
                    final_extra={"runtime_branch": dict(runtime_branch or {}), "completion_state": completion_state},
                ):
                    yield event
                return
            tool_iteration += 1
            invocation_rows: list[dict[str, Any]] = []
            for tool_action in tool_actions:
                admission = admit_model_action(
                    tool_action,
                    packet_allowed_action_types=tuple(compilation.packet.allowed_action_types),
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
                    packet_allowed_action_types=tuple(compilation.packet.allowed_action_types),
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
                        packet_ref=compilation.packet.packet_id,
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
                        packet_ref=compilation.packet.packet_id,
                        tool_plan=runtime_tool_plan,
                    )

            batch_plan = build_tool_batch_plan(
                turn_id=turn_id,
                packet_ref=compilation.packet.packet_id,
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
                        "packet_ref": compilation.packet.packet_id,
                        "tool_batch_plan": batch_plan_payload,
                    },
                    refs={
                        "turn_ref": turn_id,
                        "turn_run_ref": turn_run.turn_run_id,
                        "runtime_invocation_packet_ref": compilation.packet.packet_id,
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
                            "packet_ref": compilation.packet.packet_id,
                            "tool_batch_ref": batch_plan.batch_id,
                            "tool_batch_group": group_payload,
                        },
                        refs={
                            "turn_ref": turn_id,
                            "turn_run_ref": turn_run.turn_run_id,
                            "runtime_invocation_packet_ref": compilation.packet.packet_id,
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
                    packet_ref=compilation.packet.packet_id,
                    tool_plan=runtime_tool_plan,
                )
                completed_payload = {
                    "turn_id": turn_id,
                    "packet_ref": compilation.packet.packet_id,
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
                            "runtime_invocation_packet_ref": compilation.packet.packet_id,
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
                        packet_ref=compilation.packet.packet_id,
                        tool_plan=runtime_tool_plan,
                        error=RuntimeError("tool_invocation_missing_observation"),
                    )
                    row["observation"] = observation
                if observation.status == "needs_approval":
                    observation = _agent_turn_approval_requires_task_run_observation(observation)
                    row["observation"] = observation
                yield observation.to_turn_observation_event()
                if runtime_host is not None and turn_run is not None:
                    event = runtime_host.event_log.append(
                        turn_run.turn_run_id,
                        "turn_tool_observation_recorded",
                        payload={
                            "turn_id": turn_id,
                            "tool_observation": observation.to_dict(),
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
            response = await _invoke_single_turn_model(
                model_runtime=model_runtime,
                model_messages=model_messages,
                model_selection=dict(model_selection or {}),
                accounting_context={
                    "request_id": f"modelreq:{compilation.packet.packet_id}:tool-followup:{tool_iteration}",
                    "session_id": session_id,
                    "run_id": turn_run.turn_run_id if turn_run is not None else "",
                    "turn_id": turn_id,
                    "packet_ref": compilation.packet.packet_id,
                    "source": "harness.single_agent_turn.tool_followup",
                    "segment_plan": followup_segment_plan,
                    "prompt_manifest": followup_prompt_manifest,
                },
                native_tools=_native_tools_for_packet(compilation.packet.allowed_action_types, available_tools=compilation.packet.available_tools),
            )
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
                request_id=f"model-response:{compilation.packet.packet_id}:final",
                turn_id=turn_id,
                packet_ref=compilation.packet.packet_id,
                iteration=tool_iteration + 1,
                allowed_action_types=tuple(compilation.packet.allowed_action_types),
                phase="final",
                require_json_action=single_agent_requires_json_action,
            )
        if action_parse.error:
            action_parse = await _repair_single_agent_action_parse(
                action_parse,
                response=response,
                model_runtime=model_runtime,
                model_messages=model_messages,
                model_selection=dict(model_selection or {}),
                accounting_context={
                    "request_id": f"modelreq:{compilation.packet.packet_id}:final-protocol-repair",
                    "session_id": session_id,
                    "run_id": turn_run.turn_run_id if turn_run is not None else "",
                    "turn_id": turn_id,
                    "packet_ref": compilation.packet.packet_id,
                    "source": "harness.single_agent_turn.protocol_repair",
                    "segment_plan": dict(compilation.packet.segment_plan or {}),
                    "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                },
                request_id=f"model-response:{compilation.packet.packet_id}:final:repair",
                turn_id=turn_id,
                packet_ref=compilation.packet.packet_id,
                iteration=tool_iteration + 1,
                allowed_action_types=tuple(item for item in compilation.packet.allowed_action_types if item != "tool_call"),
                phase="final",
            )
        if action_parse.error:
            async for event in _emit_single_agent_protocol_error(
                action_parse.error,
                commit_assistant_message=commit_assistant_message,
                runtime_host=runtime_host,
                turn_run=turn_run,
                session_id=session_id,
                turn_id=turn_id,
                runtime_branch=runtime_branch,
            ):
                yield event
            terminal_recorded = True
            return
        tool_calls = action_parse.native_tool_calls
        action_request = action_parse.action_request
        if action_request is not None:
            admission = admit_model_action(
                action_request,
                packet_allowed_action_types=tuple(compilation.packet.allowed_action_types),
                invocation_kind="single_agent_turn",
                definitions_by_name=getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {}),
                allowed_tool_names=set(
                    str(item.get("tool_name") or item.get("name") or "")
                    for item in list(getattr(compilation.packet, "available_tools", ()) or [])
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
                    packet_ref=compilation.packet.packet_id,
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
                        "request_id": f"modelreq:{compilation.packet.packet_id}:final-admission-repair",
                        "session_id": session_id,
                        "run_id": turn_run.turn_run_id if turn_run is not None else "",
                        "turn_id": turn_id,
                        "packet_ref": compilation.packet.packet_id,
                        "source": "harness.single_agent_turn.admission_repair",
                        "segment_plan": dict(compilation.packet.segment_plan or {}),
                        "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
                    },
                    request_id=f"model-response:{compilation.packet.packet_id}:final:admission-repair",
                    turn_id=turn_id,
                    packet_ref=compilation.packet.packet_id,
                    iteration=tool_iteration + 1,
                    allowed_action_types=tuple(item for item in compilation.packet.allowed_action_types if item != "tool_call"),
                    phase="final_admission_repair",
                )
                if repaired_action_parse.action_request is not None and not repaired_action_parse.error:
                    action_parse = repaired_action_parse
                    tool_calls = action_parse.native_tool_calls
                    action_request = action_parse.action_request
                    admission = admit_model_action(
                        action_request,
                        packet_allowed_action_types=tuple(compilation.packet.allowed_action_types),
                        invocation_kind="single_agent_turn",
                        definitions_by_name=getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {}),
                        allowed_tool_names=set(
                            str(item.get("tool_name") or item.get("name") or "")
                            for item in list(getattr(compilation.packet, "available_tools", ()) or [])
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
                            packet_ref=compilation.packet.packet_id,
                        )
                        yield {"type": "model_action_admission", "event": event}
            if admission.decision != "allow":
                content = admission.user_visible_reason or "本轮动作没有通过运行时准入，运行时未执行该动作。"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.admission",
                    api_protocol_messages=[
                        *_native_action_protocol_messages(
                            response,
                            tool_calls,
                            turn_id=turn_id,
                            tool_result_content=content,
                        ),
                        _assistant_protocol_message_from_content(content, turn_id=turn_id),
                    ]
                    if tool_calls
                    else None,
                )
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.admission",
                    terminal_status="blocked",
                    terminal_reason=admission.system_reason or admission.decision,
                    final_extra={"runtime_branch": dict(runtime_branch or {}), "admission": admission.to_dict()},
                ):
                    yield event
                return
            if action_request.action_type == "respond":
                content = action_request.final_answer or stringify_content(getattr(response, "content", response)).strip()
                if not content:
                    content = "模型选择直接回答，但没有提供可用回答内容。"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="conversation",
                    answer_source="harness.single_agent_turn.respond",
                )
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="conversation",
                    answer_source="harness.single_agent_turn.respond",
                    terminal_status="completed",
                    terminal_reason="respond",
                    final_extra={"runtime_branch": dict(runtime_branch or {})},
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
                    if event.get("type") == "task_run_lifecycle_reused_current":
                        request_task_terminal_reason = "session_active_task_exists"
                    elif _is_public_terminal_event(event):
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
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.block",
                    api_protocol_messages=[
                        *_native_action_protocol_messages(
                            response,
                            tool_calls,
                            turn_id=turn_id,
                            tool_result_content="Runtime accepted block action.",
                        ),
                        _assistant_protocol_message_from_content(content, turn_id=turn_id),
                    ]
                    if tool_calls
                    else None,
                )
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.block",
                    terminal_status="blocked",
                    terminal_reason="blocked",
                    final_extra={"runtime_branch": dict(runtime_branch or {})},
                ):
                    yield event
                return
            if action_request.action_type == "ask_user":
                content = action_request.user_question or "我需要你补充一点信息。"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="ask_user",
                    answer_source="harness.single_agent_turn.ask_user",
                    api_protocol_messages=[
                        *_native_action_protocol_messages(
                            response,
                            tool_calls,
                            turn_id=turn_id,
                            tool_result_content="Runtime accepted ask_user action.",
                        ),
                        _assistant_protocol_message_from_content(content, turn_id=turn_id),
                    ]
                    if tool_calls
                    else None,
                )
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel="ask_user",
                    answer_source="harness.single_agent_turn.ask_user",
                    terminal_status="completed",
                    terminal_reason="ask_user",
                    final_extra={"runtime_branch": dict(runtime_branch or {})},
                ):
                    yield event
                return
            if action_request.action_type == "active_work_control":
                active_control = dict(action_request.active_work_control or {})
                active_result = await apply_active_work_control(active_control)
                if isinstance(active_result, dict):
                    content = str(active_result.get("content") or active_result.get("message") or "").strip()
                    active_status = str(active_result.get("status") or "completed").strip()
                    active_terminal_reason = str(active_result.get("terminal_reason") or active_result.get("reason") or "").strip()
                else:
                    content = str(active_result or "").strip()
                    active_status = "completed"
                    active_terminal_reason = ""
                if not content:
                    content = "当前工作控制请求没有返回可用结果。"
                resolved_action = str(active_control.get("resolved_action") or active_control.get("action") or "active_work_control")
                terminal_reason = active_terminal_reason or resolved_action
                is_task_steer = resolved_action in _STEER_ACTIVE_WORK_ACTIONS
                if is_task_steer and active_status != "blocked":
                    yield {
                        "type": "active_task_steer_accepted",
                        "summary": content,
                        "status": "accepted",
                        "terminal_reason": resolved_action,
                        "runtime_branch": dict(runtime_branch or {}),
                        "active_work": dict(active_control),
                    }
                answer_channel = "blocked" if active_status == "blocked" else "active_work_control"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel=answer_channel,
                    answer_source="harness.single_agent_turn.active_work_control",
                    api_protocol_messages=[
                        *_native_action_protocol_messages(
                            response,
                            tool_calls,
                            turn_id=turn_id,
                            tool_result_content="Runtime accepted active_work_control action.",
                        ),
                        _assistant_protocol_message_from_content(content, turn_id=turn_id),
                    ]
                    if tool_calls
                    else None,
                )
                async for event in emit_terminal_then_final(
                    content=content,
                    answer_channel=answer_channel,
                    answer_source="harness.single_agent_turn.active_work_control",
                    terminal_status="blocked" if active_status == "blocked" else "completed",
                    terminal_reason=terminal_reason,
                    final_extra={
                        "runtime_branch": dict(runtime_branch or {}),
                        "active_work": dict(active_control),
                        "completion_state": "blocked" if active_status == "blocked" else ("task_steer_accepted" if is_task_steer else "completed"),
                        "summary": content if is_task_steer else "",
                    },
                ):
                    yield event
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
        "你是一名单轮动作准入修复员。\n"
        "你只负责在运行边界已经拒绝上一动作后，重新给出一个合法的最终控制裁决。\n"
        "你不能执行动作，不能忽略 admission，不能假设用户已经授权。\n\n"
        "请只输出一个 JSON action。允许的 action_type 见修复输入。"
        "当前阶段禁止普通工具调用；如果需要工具才能继续，应改为询问用户、请求持续任务或说明边界。"
        "如果可以直接回答，使用 respond 并给出 final_answer。"
        "禁止输出解释文字，禁止 Markdown。\n\n"
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
    }
    tool_repair_allowed = "tool_call" in set(allowed_action_types or ())
    repair_target_text = "一个合法的控制裁决或一个合法工具调用" if tool_repair_allowed else "一个合法的最终控制裁决"
    tool_repair_instruction = (
        "如果需要普通工具，只能输出一个 action_type=tool_call 的动作；不要混入 ask_user、block、request_task_run 或 active_work_control。\n"
        if tool_repair_allowed
        else "当前修复阶段不允许普通工具调用；如需更多执行能力，应改为询问用户、请求持续任务、阻止或直接回答。\n"
    )
    repair_instruction = (
        "你是一名动作协议修复员。\n"
        f"你只负责把上一轮模型输出修复为{repair_target_text}。\n"
        "你不能执行动作，不能扩写用户目标，不能引入新需求。\n\n"
        "上一轮输出违反了运行协议。请根据用户当前请求、运行边界和允许动作，只输出一个 JSON 对象。\n"
        "如果需要控制裁决，只能选择一个 action_type。\n"
        f"{tool_repair_instruction}"
        "禁止输出解释文字，禁止 Markdown，禁止多个控制动作。\n\n"
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
        require_json_action=False,
        allow_native_tool_calls=True,
    )
    native_tool_calls = [dict(item) for item in protocol.native_tool_calls]
    json_payload = dict(protocol.json_payload or {})
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
                        "phase": phase,
                    },
                ),
            )
        parsed_action = replace(
            action_request,
            diagnostics={
                **dict(action_request.diagnostics or {}),
                "origin_kind": "single_agent_turn_json_action",
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
                        "phase": phase,
                    },
                ),
            )
        return SingleAgentActionParse(action_request=None, native_tool_calls=[])
    native_actions = _action_requests_from_native_tool_calls(
        native_tool_calls,
        turn_id=turn_id,
        packet_ref=packet_ref,
        iteration=iteration,
    )
    tool_actions = tuple(item for item in native_actions if item.action_type == "tool_call")
    control_actions = tuple(item for item in native_actions if item.action_type != "tool_call")
    if tool_actions and control_actions:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_multiple_action_sources",
                reason="single_agent_turn_mixed_tool_and_control_actions",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "tool_action_count": len(tool_actions),
                    "control_action_count": len(control_actions),
                    "action_types": [item.action_type for item in native_actions],
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "phase": phase,
                },
            ),
        )
    if len(control_actions) > 1:
        return SingleAgentActionParse(
            action_request=None,
            native_tool_calls=native_tool_calls,
            error=_single_agent_protocol_error(
                code="single_agent_turn_multiple_native_actions",
                reason="single_agent_turn_multiple_control_actions",
                diagnostics={
                    "native_tool_call_count": len(native_tool_calls),
                    "action_types": [item.action_type for item in control_actions],
                    "tool_names": [str(call.get("name") or "") for call in native_tool_calls],
                    "phase": phase,
                },
            ),
        )
    if len(control_actions) == 1:
        return SingleAgentActionParse(
            action_request=control_actions[0],
            native_tool_calls=native_tool_calls,
            control_action=control_actions[0],
        )
    if tool_actions:
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


def _action_requests_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
) -> list[ModelActionRequest]:
    actions: list[ModelActionRequest] = []
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name:
            continue
        if tool_name not in _CONTROL_NATIVE_TOOL_NAMES:
            action = _tool_action_request_from_native_tool_calls(
                [call],
                turn_id=turn_id,
                packet_ref=packet_ref,
                iteration=iteration,
            )
        elif tool_name == "active_work_control":
            action = _active_work_action_request_from_native_tool_calls(
                [call],
                turn_id=turn_id,
                packet_ref=packet_ref,
            )
        else:
            action = _action_request_from_native_tool_calls(
                [call],
                turn_id=turn_id,
                packet_ref=packet_ref,
            )
        if action is not None:
            actions.append(action)
    return actions


def _single_agent_protocol_error(*, code: str, reason: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "reason": reason,
        "diagnostics": {
            "authority": "harness.loop.single_agent_turn.protocol_error",
            **dict(diagnostics or {}),
        },
    }


async def _emit_single_agent_protocol_error(
    error: dict[str, Any],
    *,
    commit_assistant_message: CommitAssistantMessage,
    runtime_host: Any,
    turn_run: TurnRun | None,
    session_id: str,
    turn_id: str,
    runtime_branch: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    code = str(error.get("code") or "single_agent_turn_model_protocol_error")
    reason = str(error.get("reason") or code)
    diagnostics = dict(error.get("diagnostics") or {})
    content = _single_agent_protocol_error_user_text(code)
    commit_decision = await _commit_final_message(
        commit_assistant_message,
        session_id=session_id,
        turn_id=turn_id,
        content=content,
        answer_channel="blocked",
        answer_source="harness.single_agent_turn.protocol_error",
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
    if runtime_host is not None and turn_run is not None:
        terminal = _record_turn_terminal(
            runtime_host,
            turn_run=turn_run,
            turn_id=turn_id,
            status="blocked",
            terminal_reason=code,
            payload={"protocol_error": {"code": code, "reason": reason, "diagnostics": diagnostics}},
        )
        yield {"type": "agent_turn_terminal", "event": terminal}
    yield final_answer_event(
        content=content,
        answer_channel="blocked",
        answer_source="harness.single_agent_turn.protocol_error",
        terminal_reason=code,
        extra={
            "runtime_branch": dict(runtime_branch or {}),
            "protocol_error": {
                "code": code,
                "reason": reason,
                "diagnostics": diagnostics,
            },
        },
    )


def _single_agent_protocol_error_user_text(code: str) -> str:
    if code == "single_agent_turn_multiple_native_actions":
        return "我同时拿到了多个可能动作，当前运行已经停住，避免选错方向。请直接说明这一步优先处理哪个目标。"
    if code == "single_agent_turn_multiple_action_sources":
        return "这一步出现了两套互相冲突的执行意图，当前运行已经停住，避免重复执行。请直接补一句最新目标，我会按新的输入重新开始。"
    if code == "single_agent_turn_json_action_required":
        return "这一步没有形成可安全执行的动作，当前运行已经停住，避免误执行。请直接补充新的目标或修改要求。"
    if code == "single_agent_turn_invalid_json_action":
        return "这一步的执行意图不完整，当前运行已经停住，避免误执行。请直接补充新的目标或修改要求。"
    if code in {
        "single_agent_turn_invalid_native_action",
        "single_agent_turn_model_protocol_error",
        "single_agent_turn_protocol_repair_failed",
    }:
        return "这一步没有整理出可安全执行的动作，当前运行已经停住。请直接补一句新的目标或修改要求，我会按最新输入重新开始。"
    return "当前运行没有形成可安全推进的下一步，已经停住。请直接补充新的目标或修改要求，我会按最新输入重新开始。"


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


def _action_request_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
) -> ModelActionRequest | None:
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        args = dict(call.get("args") or {})
        if tool_name == "ask_user":
            return ModelActionRequest(
                request_id=f"model-action:{turn_id}:single-agent-ask-user",
                turn_id=turn_id,
                action_type="ask_user",
                public_progress_note="需要用户补充信息后才能继续。",
                user_question=str(args.get("question") or "").strip() or "我需要你补充一点信息。",
                diagnostics={
                    "origin_kind": "single_agent_turn_native_action",
                    "origin_authority": "harness.loop.single_agent_turn",
                    "packet_ref": packet_ref,
                    "native_tool_call": {
                        "id": str(call.get("id") or ""),
                        "name": tool_name,
                        "source": str(call.get("source") or ""),
                    },
                },
            )
        if tool_name == "block":
            return ModelActionRequest(
                request_id=f"model-action:{turn_id}:single-agent-block",
                turn_id=turn_id,
                action_type="block",
                public_progress_note="当前请求无法继续执行。",
                blocking_reason=str(args.get("reason") or "").strip() or "当前请求无法继续处理。",
                diagnostics={
                    "origin_kind": "single_agent_turn_native_action",
                    "origin_authority": "harness.loop.single_agent_turn",
                    "packet_ref": packet_ref,
                    "native_tool_call": {
                        "id": str(call.get("id") or ""),
                        "name": tool_name,
                        "source": str(call.get("source") or ""),
                    },
                },
            )
        if tool_name != "request_task_run":
            continue
        contract_seed = {
            "user_visible_goal": str(args.get("user_visible_goal") or "").strip(),
            "task_run_goal": str(args.get("task_run_goal") or "").strip(),
            "required_artifacts": list(args.get("required_artifacts") or []),
            "required_verifications": list(args.get("required_verifications") or []),
            "completion_criteria": list(args.get("completion_criteria") or []),
        }
        public_note = str(args.get("public_progress_note") or "").strip() or "正在建立任务运行。"
        return ModelActionRequest(
            request_id=f"model-action:{turn_id}:single-agent-request-task-run",
            turn_id=turn_id,
            action_type="request_task_run",
            public_progress_note=public_note,
            public_action_state={
                "visible_status": "thinking",
                "completion_status": "working",
                "next_action": public_note,
            },
            task_contract_seed=contract_seed,
            completion_contract={"completion_criteria": list(contract_seed.get("completion_criteria") or [])},
            diagnostics={
                "origin_kind": "single_agent_turn_native_action",
                "origin_authority": "harness.loop.single_agent_turn",
                "packet_ref": packet_ref,
                "native_tool_call": {
                    "id": str(call.get("id") or ""),
                    "name": str(call.get("name") or ""),
                    "source": str(call.get("source") or ""),
                },
            },
        )
    return None


def _tool_action_request_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
) -> ModelActionRequest | None:
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name or tool_name in _CONTROL_NATIVE_TOOL_NAMES:
            continue
        args = dict(call.get("args") or {})
        call_id = str(call.get("id") or f"call:{tool_name}:{iteration}")
        public_note = _native_tool_public_progress_note(tool_name, args)
        return ModelActionRequest(
            request_id=f"model-action:{turn_id}:single-agent-tool:{iteration}:{_stable_action_suffix(call_id or tool_name)}",
            turn_id=turn_id,
            action_type="tool_call",
            public_progress_note=public_note,
            public_action_state={"current_judgment": public_note, "completion_status": "waiting_for_tool"},
            tool_call={"tool_name": tool_name, "name": tool_name, "id": call_id, "args": args},
            diagnostics={
                "origin_kind": "single_agent_turn_native_tool_call",
                "origin_authority": "harness.loop.single_agent_turn",
                "packet_ref": packet_ref,
                "native_tool_call": {
                    "id": call_id,
                    "name": tool_name,
                    "source": str(call.get("source") or ""),
                },
            },
        )
    return None


def _native_tool_public_progress_note(tool_name: str, args: dict[str, Any]) -> str:
    normalized = str(tool_name or "").strip().lower()
    target = _native_tool_public_target(args)
    if normalized in {"search_text", "search_files", "glob_paths"} or any(token in normalized for token in ("search", "grep", "glob")):
        return f"我先搜索 {target} 的相关引用，再根据结果判断下一步。" if target else "我先定位相关引用，再根据结果判断下一步。"
    if normalized in {"read_file", "read_path"} or "read" in normalized:
        return f"我先读取 {target}，把判断建立在真实上下文上。" if target else "我先读取相关上下文，再继续判断。"
    if normalized in {"path_exists", "stat_path", "list_dir"}:
        return f"我先确认 {target} 的当前状态。" if target else "我先确认目标状态，再继续推进。"
    if normalized in {"write_file", "edit_file", "apply_patch"} or any(token in normalized for token in ("write", "edit", "patch")):
        return f"我会更新 {target}，随后验证改动是否生效。" if target else "我会先落下改动，再验证结果。"
    if normalized in {"terminal", "shell", "run_command", "powershell"} or any(token in normalized for token in ("terminal", "shell", "command")):
        return "我会运行必要的验证命令，再根据结果判断是否继续修正。"
    if normalized in {"image_generate", "image_generation", "generate_image"}:
        return "我会生成图像资源，拿到结果后确认是否可用。"
    return "我先执行当前必要动作，拿到结果后再继续判断。"


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


def _active_work_action_request_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
) -> ModelActionRequest | None:
    for call in tool_calls:
        if str(call.get("name") or "").strip() != "active_work_control":
            continue
        args = dict(call.get("args") or {})
        action = str(args.get("action") or "").strip()
        if action not in {
            "continue_active_work",
            "pause_active_work",
            "stop_active_work",
            "append_instruction_to_active_work",
            "answer_about_active_work",
            "answer_then_continue_active_work",
        }:
            return None
        active_work_control = {
            "action": action,
            "response": str(args.get("response") or "").strip(),
            "appended_instruction": str(args.get("appended_instruction") or "").strip(),
            "continuation_strategy": str(args.get("continuation_strategy") or "").strip(),
            "turn_response_policy": str(args.get("turn_response_policy") or "").strip(),
            "user_turn_kind": str(args.get("user_turn_kind") or "").strip(),
            "answer_obligation": str(args.get("answer_obligation") or "").strip(),
            "relation_to_current_work": str(args.get("relation_to_current_work") or args.get("relation") or "").strip(),
            "evidence": str(args.get("evidence") or "").strip(),
            "turn_id": turn_id,
            "packet_ref": packet_ref,
        }
        return ModelActionRequest(
            request_id=f"model-action:{turn_id}:single-agent-active-work-control",
            turn_id=turn_id,
            action_type="active_work_control",
            public_progress_note="正在处理当前工作控制请求。",
            active_work_control=active_work_control,
            diagnostics={
                "origin_kind": "single_agent_turn_native_action",
                "origin_authority": "harness.loop.single_agent_turn",
                "packet_ref": packet_ref,
                "native_tool_call": {
                    "id": str(call.get("id") or ""),
                    "name": str(call.get("name") or ""),
                    "source": str(call.get("source") or ""),
                },
            },
        )
    return None


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
    if status == "needs_approval":
        text = (
            f"工具调用等待运行时人工确认。准入裁决：{admission.decision}；原因：{system_reason}。"
            f"边界说明：{user_reason}。这属于 control-plane 审批状态，不应作为模型恢复观察进入下一轮。"
        )
    else:
        text = (
            f"工具调用未执行。准入裁决：{admission.decision}；原因：{system_reason}。"
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
            "error": system_reason,
            "error_code": system_reason,
            "admission_decision": admission.decision,
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
    if decision == "needs_contract":
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
            diagnostics={"stage": "runtime_tool_control_plane_unavailable"},
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
    backend_dir = Path(str(getattr(runtime_host, "backend_dir", "") or assembly_payload.get("backend_dir") or ".")).resolve()
    runtime_root = Path(str(getattr(runtime_host, "root_dir", "") or (backend_dir / "storage" / "runtime"))).resolve()
    sandbox_root = str(sandbox.get("sandbox_root") or "").strip()
    if not sandbox_root:
        namespace = str(turn_id or assembly_payload.get("turn_id") or "single_turn").replace(":", "_")
        sandbox_root = str((runtime_root / "sandboxes" / namespace).resolve())
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
