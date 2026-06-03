from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import replace
from typing import Any, AsyncIterator, Awaitable, Callable

from harness.loop.admission import AdmissionDecision, admit_model_action
from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.model_action_runtime import call_model_invoker
from harness.loop.presentation import error_event, final_answer_event
from harness.runtime import RuntimeCompiler, build_runtime_tool_plan
from harness.runtime.file_management_policy import compile_tool_file_management_policy
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from harness.runtime.public_progress import public_runtime_progress_summary
from runtime.prompt_accounting.serializer import normalize_messages
from runtime.model_gateway.model_runtime import stringify_content
from runtime.shared.models import TurnRun
from runtime.tool_runtime import ToolInvocationRequest, build_tool_invocation_id
from runtime.tool_runtime.provider_tool_call_adapter import normalize_tool_call_dicts, tool_calls_for_langchain_messages


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
ApplyActiveWorkControl = Callable[[dict[str, Any]], Awaitable[str]]

_STEER_ACTIVE_WORK_ACTIONS = {
    "continue_active_work",
    "append_instruction_to_active_work",
    "answer_then_continue_active_work",
}
_MAX_SINGLE_TURN_TOOL_ITERATIONS = 3


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
            )
            yield {"type": "harness_run_started", "turn_run": turn_run.to_dict(), "event": start_event}
        compiler = RuntimeCompiler()
        active_work_payload = _active_work_payload(active_work_context)
        active_work_for_turn = (
            active_work_payload
            if _user_message_targets_active_work(user_message) or _task_selection_allows_active_work_control(session_context)
            else {}
        )
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
        yield {
            "type": "single_agent_turn_started",
            "runtime_branch": dict(runtime_branch or {}),
            "packet_ref": compilation.packet.packet_id,
            "allowed_action_types": list(compilation.packet.allowed_action_types),
        }
        runtime_tool_plan = build_runtime_tool_plan(
            runtime_assembly=runtime_assembly,
            invocation_kind="single_agent_turn",
            tool_definitions_by_name=getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {}),
        )
        model_messages = list(compilation.packet.model_messages)
        api_protocol_messages: list[dict[str, Any]] = []
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
        while True:
            if isinstance(response, dict) and response.get("type") == "error":
                break
            tool_calls = normalize_tool_call_dicts(response)
            tool_action = _tool_action_request_from_native_tool_calls(
                tool_calls,
                turn_id=turn_id,
                packet_ref=compilation.packet.packet_id,
                iteration=tool_iteration + 1,
            )
            if tool_action is None:
                break
            if tool_iteration >= _MAX_SINGLE_TURN_TOOL_ITERATIONS:
                synthesis_messages = [
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
                ]
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
                else:
                    content = stringify_content(getattr(synthesis_response, "content", synthesis_response)).strip()
                    terminal_status = "completed" if content else "failed"
                    if not content:
                        content = "我连续检查了几次仍没有形成可靠结论，先停在这里，避免继续无效操作。你可以补充要我重点核查的位置，或让我根据当前已知状态直接说明。"
                answer_source = "harness.single_agent_turn.tool_limit_synthesis"
                answer_channel = "conversation" if terminal_status == "completed" else "blocked"
                protocol_final = (
                    _assistant_final_protocol_message(synthesis_response, turn_id=turn_id, include_reasoning=True)
                    if terminal_status == "completed"
                    else _assistant_protocol_message_from_content(content, turn_id=turn_id)
                )
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
                yield final_answer_event(
                    content=content,
                    answer_source=answer_source,
                    terminal_reason="single_turn_tool_iteration_limit",
                    extra={"runtime_branch": dict(runtime_branch or {}), "completion_state": "tool_limit_synthesized"},
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status=terminal_status,
                        terminal_reason="single_turn_tool_iteration_limit",
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            tool_iteration += 1
            admission = admit_model_action(
                tool_action,
                packet_allowed_action_types=tuple(compilation.packet.allowed_action_types),
                invocation_kind="single_agent_turn",
                definitions_by_name=getattr(getattr(runtime_host, "tool_authorization_index", None), "definitions_by_name", {}),
                allowed_tool_names=set(runtime_tool_plan.dispatchable_tool_names),
                runtime_profile=_runtime_profile_payload(runtime_assembly),
                permission_mode=runtime_host._current_permission_mode() if runtime_host is not None and hasattr(runtime_host, "_current_permission_mode") else "default",
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
            if admission.decision == "needs_contract":
                content = admission.user_visible_reason or "这个动作需要先建立持续处理任务。"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.tool_admission",
                )
                yield final_answer_event(
                    content=content,
                    answer_source="harness.single_agent_turn.tool_admission",
                    terminal_reason=admission.system_reason or admission.decision,
                    extra={"runtime_branch": dict(runtime_branch or {}), "admission": admission.to_dict()},
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="blocked",
                        terminal_reason=admission.system_reason or admission.decision,
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            if admission.decision != "allow":
                content = admission.user_visible_reason or "本轮工具调用没有通过运行时准入，已停止执行。"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.tool_admission",
                )
                yield final_answer_event(
                    content=content,
                    answer_source="harness.single_agent_turn.tool_admission",
                    terminal_reason=admission.system_reason or admission.decision,
                    extra={"runtime_branch": dict(runtime_branch or {}), "admission": admission.to_dict()},
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="blocked",
                        terminal_reason=admission.system_reason or admission.decision,
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            tool_call = dict(tool_action.tool_call or {})
            observation = await _invoke_turn_tool(
                runtime_host=runtime_host,
                runtime_assembly=runtime_assembly,
                turn_run=turn_run,
                session_id=session_id,
                turn_id=turn_id,
                action_request=tool_action,
                admission=admission,
                packet_ref=compilation.packet.packet_id,
                tool_plan=runtime_tool_plan,
            )
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
            if observation.status != "ok":
                content = observation.text or "本轮工具调用失败，已停止执行。"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="blocked",
                    answer_source="harness.single_agent_turn.tool_observation",
                    api_protocol_messages=[
                        *api_protocol_messages,
                        _with_turn_id(_assistant_tool_call_message(response, [tool_call]), turn_id),
                        _with_turn_id(_tool_observation_message(observation, tool_call_id=str(tool_call.get("id") or "")), turn_id),
                        _assistant_protocol_message_from_content(content, turn_id=turn_id),
                    ],
                )
                yield final_answer_event(
                    content=content,
                    answer_source="harness.single_agent_turn.tool_observation",
                    terminal_reason=observation.status,
                    extra={"runtime_branch": dict(runtime_branch or {}), "tool_observation": observation.to_dict()},
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="blocked",
                        terminal_reason=f"tool_{observation.status}",
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            assistant_protocol_message = _with_turn_id(_assistant_tool_call_message(response, [tool_call]), turn_id)
            tool_protocol_message = _with_turn_id(
                _tool_observation_message(observation, tool_call_id=str(tool_call.get("id") or "")),
                turn_id,
            )
            api_protocol_messages.extend([assistant_protocol_message, tool_protocol_message])
            model_messages = [
                *model_messages,
                assistant_protocol_message,
                tool_protocol_message,
            ]
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
            yield response
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
            return
        tool_calls = normalize_tool_call_dicts(response)
        action_request = _action_request_from_native_tool_calls(
            tool_calls,
            turn_id=turn_id,
            packet_ref=compilation.packet.packet_id,
        )
        if action_request is None:
            action_request = _active_work_action_request_from_native_tool_calls(
                tool_calls,
                turn_id=turn_id,
                packet_ref=compilation.packet.packet_id,
            )
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
                permission_mode=runtime_host._current_permission_mode() if runtime_host is not None and hasattr(runtime_host, "_current_permission_mode") else "default",
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
                content = admission.user_visible_reason or "本轮动作没有通过运行时准入，已停止执行。"
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
                yield final_answer_event(
                    content=content,
                    answer_source="harness.single_agent_turn.admission",
                    terminal_reason=admission.system_reason or admission.decision,
                    extra={"runtime_branch": dict(runtime_branch or {}), "admission": admission.to_dict()},
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="blocked",
                        terminal_reason=admission.system_reason or admission.decision,
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
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
                async for event in start_task_from_action_request(action_request):
                    yield event
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="completed",
                        terminal_reason="task_executor_scheduled",
                        payload={"action_request_ref": action_request.request_id},
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
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
                yield final_answer_event(
                    content=content,
                    answer_source="harness.single_agent_turn.block",
                    terminal_reason="blocked",
                    extra={"runtime_branch": dict(runtime_branch or {})},
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="blocked",
                        terminal_reason="blocked",
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            if action_request.action_type == "ask_user":
                content = action_request.user_question or "我需要你补充一点信息。"
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="conversation",
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
                yield final_answer_event(
                    content=content,
                    answer_source="harness.single_agent_turn.ask_user",
                    terminal_reason="ask_user",
                    extra={"runtime_branch": dict(runtime_branch or {})},
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="completed",
                        terminal_reason="ask_user",
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return
            if action_request.action_type == "active_work_control":
                active_control = dict(action_request.active_work_control or {})
                content = await apply_active_work_control(active_control)
                resolved_action = str(active_control.get("resolved_action") or active_control.get("action") or "active_work_control")
                is_task_steer = resolved_action in _STEER_ACTIVE_WORK_ACTIONS
                if is_task_steer:
                    yield {
                        "type": "active_task_steer_accepted",
                        "summary": content,
                        "status": "accepted",
                        "terminal_reason": resolved_action,
                        "runtime_branch": dict(runtime_branch or {}),
                        "active_work": dict(active_control),
                    }
                await _commit_final_message(
                    commit_assistant_message,
                    session_id=session_id,
                    turn_id=turn_id,
                    content=content,
                    answer_channel="active_work_control",
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
                yield final_answer_event(
                    content=content,
                    answer_source="harness.single_agent_turn.active_work_control",
                    terminal_reason=resolved_action,
                    extra={
                        "runtime_branch": dict(runtime_branch or {}),
                        "active_work": dict(active_control),
                        "completion_state": "task_steer_accepted" if is_task_steer else "completed",
                        "summary": content if is_task_steer else "",
                    },
                )
                if runtime_host is not None and turn_run is not None:
                    terminal = _record_turn_terminal(
                        runtime_host,
                        turn_run=turn_run,
                        turn_id=turn_id,
                        status="completed",
                        terminal_reason=resolved_action,
                    )
                    terminal_recorded = True
                    yield {"type": "agent_turn_terminal", "event": terminal}
                return

        content = stringify_content(getattr(response, "content", response)).strip()
        if not content:
            yield error_event(
                content="模型没有返回可用的回复内容。",
                code="single_agent_turn_empty_response",
                reason="single_agent_turn_empty_response",
            )
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
            return
        await _commit_final_message(
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
            "answer_channel": "conversation",
            "answer_source": "harness.single_agent_turn",
            "answer_canonical_state": "final",
        }
        yield final_answer_event(
            content=content,
            answer_source="harness.single_agent_turn",
            terminal_reason="assistant_message",
            extra={"runtime_branch": dict(runtime_branch or {})},
        )
        if runtime_host is not None and turn_run is not None:
            terminal = _record_turn_terminal(
                runtime_host,
                turn_run=turn_run,
                turn_id=turn_id,
                status="completed",
                terminal_reason="assistant_message",
            )
            terminal_recorded = True
            yield {"type": "agent_turn_terminal", "event": terminal}
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
    tool_invoker = getattr(model_runtime, "invoke_messages_with_tools", None)
    plain_invoker = getattr(model_runtime, "invoke_messages", None)
    if native_tools and callable(tool_invoker):
        try:
            return await tool_invoker(
                model_messages,
                native_tools,
                model_spec=model_selection,
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


def _native_tools_for_packet(allowed_action_types: tuple[str, ...], *, available_tools: tuple[dict[str, Any], ...] = ()) -> list[dict[str, Any]]:
    allowed = set(allowed_action_types or ())
    tools: list[dict[str, Any]] = []
    if "tool_call" in allowed:
        tools.extend(_runtime_native_tools(available_tools))
    if "request_task_run" in allowed:
        tools.append(request_task_run_native_tool())
    if "active_work_control" in allowed:
        tools.append(active_work_control_native_tool())
    if "ask_user" in allowed:
        tools.append(ask_user_native_tool())
    if "block" in allowed:
        tools.append(block_native_tool())
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


def request_task_run_native_tool() -> dict[str, Any]:
    return {
        "name": "request_task_run",
        "description": (
            "当用户目标需要持续执行、真实产物、文件写入、命令验证、浏览器验证、失败恢复或多步骤交付时调用。"
            "如果当前请求可以直接回答，不要调用此工具，直接回复用户。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_visible_goal": {"type": "string"},
                "task_run_goal": {"type": "string"},
                "required_artifacts": {"type": "array", "items": {"type": "object"}},
                "required_verifications": {"type": "array", "items": {"type": "object"}},
                "completion_criteria": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["user_visible_goal", "task_run_goal", "completion_criteria"],
        },
    }


def active_work_control_native_tool() -> dict[str, Any]:
    return {
        "name": "active_work_control",
        "description": (
            "当用户明确要继续、暂停、停止、补充或询问当前正在进行的工作时调用。"
            "如果用户只是普通聊天或新请求，不要调用此工具。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "continue_active_work",
                        "pause_active_work",
                        "stop_active_work",
                        "append_instruction_to_active_work",
                        "answer_about_active_work",
                        "answer_then_continue_active_work",
                    ],
                },
                "response": {"type": "string"},
                "appended_instruction": {"type": "string"},
                "continuation_strategy": {"type": "string"},
                "turn_response_policy": {"type": "string"},
                "user_turn_kind": {"type": "string"},
                "answer_obligation": {"type": "string"},
                "relation_to_current_work": {"type": "string"},
                "evidence": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action"],
        },
    }


def ask_user_native_tool() -> dict[str, Any]:
    return {
        "name": "ask_user",
        "description": (
            "当缺少用户才能提供的关键信息、选择或授权，且不能可靠继续时调用。"
            "问题必须具体、简短，并说明需要用户补充什么。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
        },
    }


def block_native_tool() -> dict[str, Any]:
    return {
        "name": "block",
        "description": (
            "当当前请求越过权限边界、运行环境无法支持、缺少必要能力，或继续执行会产生不可靠结果时调用。"
            "阻止理由必须面向用户说明事实边界和可恢复方向。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
            },
            "required": ["reason"],
        },
    }


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
        return ModelActionRequest(
            request_id=f"model-action:{turn_id}:single-agent-request-task-run",
            turn_id=turn_id,
            action_type="request_task_run",
            public_progress_note="正在建立任务运行。",
            public_action_state={
                "visible_status": "thinking",
                "completion_status": "working",
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
    reserved = {"request_task_run", "active_work_control", "ask_user", "block"}
    for call in tool_calls:
        tool_name = str(call.get("name") or "").strip()
        if not tool_name or tool_name in reserved:
            continue
        args = dict(call.get("args") or {})
        call_id = str(call.get("id") or f"call:{tool_name}:{iteration}")
        return ModelActionRequest(
            request_id=f"model-action:{turn_id}:single-agent-tool:{iteration}:{uuid.uuid4().hex[:8]}",
            turn_id=turn_id,
            action_type="tool_call",
            public_progress_note=f"已发起工具调用，正在等待工具返回：{tool_name}。",
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
            "confidence": args.get("confidence"),
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


async def _invoke_turn_tool(
    *,
    runtime_host: Any,
    runtime_assembly: Any,
    turn_run: TurnRun | None,
    session_id: str,
    turn_id: str,
    action_request: ModelActionRequest,
    admission: AdmissionDecision,
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
        permission_mode=runtime_host._current_permission_mode() if runtime_host is not None and hasattr(runtime_host, "_current_permission_mode") else "default",
        sandbox_scope=_single_turn_sandbox_scope(assembly_payload),
        file_scope=compile_tool_file_management_policy(dict(assembly_payload.get("task_environment") or {})),
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
    return await control_plane.invoke(request, tool_plan=tool_plan)


def _single_turn_sandbox_scope(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    environment = dict(assembly_payload.get("task_environment") or {})
    sandbox = dict(environment.get("sandbox_policy") or {})
    storage = dict(environment.get("storage_space") or {})
    if storage.get("workspace_root") and "workspace_root" not in sandbox:
        sandbox["workspace_root"] = str(storage.get("workspace_root") or "")
    return sandbox


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
    normalized_messages = normalize_messages(model_messages)
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
) -> None:
    await commit_assistant_message(
        session_id,
        {
            "role": "assistant",
            "content": content,
            "turn_id": turn_id,
            "answer_channel": answer_channel,
            "answer_source": answer_source,
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
            "api_protocol_messages": [dict(item) for item in list(api_protocol_messages or []) if isinstance(item, dict)],
        },
    )


def _active_work_payload(active_work_context: Any | None) -> dict[str, Any]:
    if active_work_context is None:
        return {}
    if hasattr(active_work_context, "to_dict"):
        return dict(active_work_context.to_dict())
    return dict(active_work_context or {})


def _task_selection_allows_active_work_control(session_context: dict[str, Any] | None) -> bool:
    payload = dict(session_context or {})
    task_selection = dict(payload.get("task_selection") or {})
    capabilities = dict(task_selection.get("control_capabilities") or {})
    return bool(capabilities.get("may_control_active_work") is True)


def _user_message_targets_active_work(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    keywords = (
        "继续",
        "接着",
        "恢复",
        "续上",
        "暂停",
        "停止",
        "终止",
        "取消",
        "先停",
        "进展",
        "状态",
        "做到哪",
        "做到哪里",
        "卡住",
        "为什么停",
        "补充",
        "改成",
        "按这个方向",
        "当前工作",
        "上个任务",
        "继续当前",
        "resume",
        "continue",
        "pause",
        "stop",
        "cancel",
        "status",
        "progress",
        "current work",
    )
    return any(keyword in text for keyword in keywords)


def _start_turn_runtime(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    agent_profile_ref: str,
) -> tuple[TurnRun, dict[str, Any]]:
    now = time.time()
    turn_run_id = f"turnrun:{turn_id}"
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
            "source": "harness.loop.single_agent_turn",
            "execution_runtime_kind": "single_agent_turn",
        },
    )
    runtime_host.state_index.upsert_turn_run(turn_run)
    event = runtime_host.event_log.append(
        turn_run_id,
        "agent_turn_received",
        payload={"turn_id": turn_id, "turn_run": turn_run.to_dict()},
        refs={"turn_ref": turn_id},
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
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is not None and terminal_reason != "task_executor_scheduled":
        try:
            active_registry.complete(session_id=turn_run.session_id, expected_turn_id=turn_id, terminal_reason=terminal_reason)
        except Exception:
            logger.debug("failed to complete active turn", exc_info=True)
    return event.to_dict()


def _terminal_status_for_turn_run(status: str) -> str:
    if status in {"completed", "blocked", "failed", "aborted"}:
        return status
    return "failed"
