from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Any, AsyncIterator, Awaitable, Callable

from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.model_action_runtime import call_model_invoker
from harness.loop.presentation import error_event, final_answer_event
from harness.runtime import RuntimeCompiler
from harness.runtime.public_progress import public_runtime_progress_summary
from runtime.model_gateway.model_runtime import stringify_content
from runtime.shared.models import TurnRun
from runtime.tool_runtime.provider_tool_call_adapter import normalize_tool_call_dicts


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]
ApplyActiveWorkControl = Callable[[dict[str, Any]], Awaitable[str]]


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
    turn_route: Any,
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
        compilation = compiler.compile_single_agent_turn_packet(
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=agent_invocation_id,
            user_message=user_message,
            history=history,
            session_context=session_context,
            active_work_context=active_work_payload,
            agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
            model_selection=dict(model_selection or {}),
            runtime_assembly=runtime_assembly,
        )
        yield {
            "type": "single_agent_turn_started",
            "turn_route": turn_route.to_dict(),
            "packet_ref": compilation.packet.packet_id,
            "allowed_action_types": list(compilation.packet.allowed_action_types),
        }
        if runtime_host is not None and turn_run is not None:
            yield _record_step_summary(
                runtime_host,
                run_id=turn_run.turn_run_id,
                turn_id=turn_id,
                step="model_turn_invocation_started",
                status="running",
                summary="正在思考。",
                presentation_source="single_agent_turn.model_start",
            )

        response = await _invoke_single_turn_model(
            model_runtime=model_runtime,
            model_messages=list(compilation.packet.model_messages),
            model_selection=dict(model_selection or {}),
            accounting_context={
                "request_id": f"modelreq:{compilation.packet.packet_id}:1",
                "session_id": session_id,
                "run_id": turn_run.turn_run_id if turn_run is not None else "",
                "turn_id": turn_id,
                "packet_ref": compilation.packet.packet_id,
                "source": "harness.route.single_agent_turn",
                "segment_plan": dict(compilation.packet.segment_plan or {}),
                "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
            },
            native_tools=_native_tools_for_packet(compilation.packet.allowed_action_types),
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
        if runtime_host is not None and turn_run is not None:
            yield _record_step_summary(
                runtime_host,
                run_id=turn_run.turn_run_id,
                turn_id=turn_id,
                step="model_turn_output_received",
                status="running",
                summary="已收到模型判断，正在执行下一步。",
                presentation_source="single_agent_turn.model_result",
            )

        tool_calls = normalize_tool_call_dicts(response)
        action_request = _action_request_from_native_tool_calls(
            tool_calls,
            turn_id=turn_id,
            packet_ref=compilation.packet.packet_id,
        )
        if action_request is not None:
            if action_request.action_type == "request_task_run":
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
                    answer_source="harness.route.single_agent_turn.block",
                )
                yield final_answer_event(
                    content=content,
                    answer_source="harness.route.single_agent_turn.block",
                    terminal_reason="blocked",
                    extra={"turn_route": turn_route.to_dict()},
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
                    answer_source="harness.route.single_agent_turn.ask_user",
                )
                yield final_answer_event(
                    content=content,
                    answer_source="harness.route.single_agent_turn.ask_user",
                    terminal_reason="ask_user",
                    extra={"turn_route": turn_route.to_dict()},
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

        active_control = _active_work_control_from_native_tool_calls(
            tool_calls,
            turn_id=turn_id,
            packet_ref=compilation.packet.packet_id,
        )
        if active_control is not None:
            content = await apply_active_work_control(active_control)
            await _commit_final_message(
                commit_assistant_message,
                session_id=session_id,
                turn_id=turn_id,
                content=content,
                answer_channel="active_work_control",
                answer_source="harness.route.single_agent_turn.active_work_control",
            )
            yield final_answer_event(
                content=content,
                answer_source="harness.route.single_agent_turn.active_work_control",
                terminal_reason=str(active_control.get("action") or "active_work_control"),
                extra={"turn_route": turn_route.to_dict(), "active_work": dict(active_control)},
            )
            if runtime_host is not None and turn_run is not None:
                terminal = _record_turn_terminal(
                    runtime_host,
                    turn_run=turn_run,
                    turn_id=turn_id,
                    status="completed",
                    terminal_reason=str(active_control.get("action") or "active_work_control"),
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
            answer_source="harness.route.single_agent_turn",
        )
        yield {
            "type": "assistant_message_committed",
            "answer_channel": "conversation",
            "answer_source": "harness.route.single_agent_turn",
            "answer_canonical_state": "final",
        }
        yield final_answer_event(
            content=content,
            answer_source="harness.route.single_agent_turn",
            terminal_reason="assistant_message",
            extra={"turn_route": turn_route.to_dict()},
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


def _native_tools_for_packet(allowed_action_types: tuple[str, ...]) -> list[dict[str, Any]]:
    allowed = set(allowed_action_types or ())
    tools: list[dict[str, Any]] = []
    if "request_task_run" in allowed:
        tools.append(request_task_run_native_tool())
    if "active_work_control" in allowed:
        tools.append(active_work_control_native_tool())
    if "ask_user" in allowed:
        tools.append(ask_user_native_tool())
    if "block" in allowed:
        tools.append(block_native_tool())
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
            public_progress_note="已判断需要进入持续处理流程，正在建立任务边界。",
            public_action_state={
                "current_judgment": "当前目标需要持续处理。",
                "next_action": "建立任务合同并启动执行生命周期。",
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


def _active_work_control_from_native_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    turn_id: str,
    packet_ref: str,
) -> dict[str, Any] | None:
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
            return {"action": "answer_about_active_work", "response": "我需要确认当前工作状态后再继续。"}
        return {
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
    return None


async def _commit_final_message(
    commit_assistant_message: CommitAssistantMessage,
    *,
    session_id: str,
    turn_id: str,
    content: str,
    answer_channel: str,
    answer_source: str,
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
        },
    )


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
    return event.to_dict()


def _terminal_status_for_turn_run(status: str) -> str:
    if status in {"completed", "blocked", "failed", "aborted"}:
        return status
    return "failed"
