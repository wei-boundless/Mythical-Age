from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Awaitable, Callable

from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.model_action_runtime import call_model_invoker
from harness.loop.presentation import error_event, final_answer_event
from harness.runtime import RuntimeCompiler
from runtime.tool_runtime.provider_tool_call_adapter import normalize_tool_call_dicts


logger = logging.getLogger(__name__)

CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
StartTaskFromActionRequest = Callable[[ModelActionRequest], AsyncIterator[dict[str, Any]]]


async def run_agent_native_turn(
    *,
    session_id: str,
    turn_id: str,
    user_message: str,
    history: list[dict[str, Any]],
    session_context: dict[str, Any],
    agent_invocation_id: str,
    agent_runtime_profile: Any,
    runtime_assembly: Any,
    turn_route: Any,
    model_runtime: Any,
    model_selection: dict[str, Any],
    commit_assistant_message: CommitAssistantMessage,
    start_task_from_action_request: StartTaskFromActionRequest,
) -> AsyncIterator[dict[str, Any]]:
    compiler = RuntimeCompiler()
    compilation = compiler.compile_plain_conversation_packet(
        session_id=session_id,
        turn_id=turn_id,
        agent_invocation_id=agent_invocation_id,
        user_message=user_message,
        history=history,
        session_context=session_context,
        agent_profile_ref=str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
        model_selection=dict(model_selection or {}),
        runtime_assembly=runtime_assembly,
    )
    yield {
        "type": "agent_native_turn_started",
        "turn_route": turn_route.to_dict(),
        "packet_ref": compilation.packet.packet_id,
    }

    tool_invoker = getattr(model_runtime, "invoke_messages_with_tools", None)
    plain_invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(tool_invoker) and not callable(plain_invoker):
        yield error_event(
            content="当前模型运行时不可用，无法完成本轮处理。",
            code="model_runtime_unavailable",
            reason="model_runtime_unavailable",
        )
        return

    accounting_context = {
        "request_id": f"modelreq:{compilation.packet.packet_id}:1",
        "session_id": session_id,
        "turn_id": turn_id,
        "packet_ref": compilation.packet.packet_id,
        "source": "harness.route.agent_native_turn",
        "segment_plan": dict(compilation.packet.segment_plan or {}),
        "prompt_manifest": dict(compilation.packet.diagnostics.get("prompt_manifest") or {}),
    }
    try:
        if callable(tool_invoker):
            response = await tool_invoker(
                list(compilation.packet.model_messages),
                [request_task_run_native_tool()],
                model_spec=dict(model_selection or {}),
                accounting_context=accounting_context,
            )
        else:
            response = await call_model_invoker(
                plain_invoker,
                list(compilation.packet.model_messages),
                model_selection=dict(model_selection or {}),
                accounting_context=accounting_context,
            )
    except Exception as exc:
        logger.exception("agent native turn model invocation failed")
        yield error_event(
            content="模型生成本轮回复时失败。",
            code="agent_native_turn_model_failed",
            reason=str(exc),
        )
        return

    request_task_run_calls = [
        item
        for item in normalize_tool_call_dicts(response)
        if str(item.get("name") or "").strip() == "request_task_run"
    ]
    if request_task_run_calls:
        action_request = native_request_task_run_action_request(
            turn_id=turn_id,
            tool_call=dict(request_task_run_calls[0]),
        )
        async for event in start_task_from_action_request(action_request):
            yield event
        return

    content = str(getattr(response, "content", response) or "").strip()
    if not content:
        yield error_event(
            content="模型没有返回可用的回复内容。",
            code="agent_native_turn_empty_response",
            reason="agent_native_turn_empty_response",
        )
        return

    await commit_assistant_message(
        session_id,
        {
            "role": "assistant",
            "content": content,
            "turn_id": turn_id,
            "answer_channel": "conversation",
            "answer_source": "harness.route.agent_native_turn",
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
        },
    )
    yield {
        "type": "assistant_message_committed",
        "answer_channel": "conversation",
        "answer_source": "harness.route.agent_native_turn",
        "answer_canonical_state": "final",
    }
    yield final_answer_event(
        content=content,
        answer_source="harness.route.agent_native_turn",
        terminal_reason="agent_native_turn_completed",
        extra={"turn_route": turn_route.to_dict()},
    )


def native_request_task_run_action_request(
    *,
    turn_id: str,
    tool_call: dict[str, Any],
) -> ModelActionRequest:
    args = dict(tool_call.get("args") or {})
    contract_seed = {
        "user_visible_goal": str(args.get("user_visible_goal") or "").strip(),
        "task_run_goal": str(args.get("task_run_goal") or "").strip(),
        "required_artifacts": list(args.get("required_artifacts") or []),
        "required_verifications": list(args.get("required_verifications") or []),
        "completion_criteria": list(args.get("completion_criteria") or []),
    }
    return ModelActionRequest(
        request_id=f"model-action:{turn_id}:native-request-task-run",
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
            "origin_kind": "agent_native_tool_call",
            "origin_authority": "harness.routing.agent_native_turn",
            "native_tool_call": {
                "id": str(tool_call.get("id") or ""),
                "name": str(tool_call.get("name") or ""),
                "source": str(tool_call.get("source") or ""),
            },
        },
    )


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
                "user_visible_goal": {"type": "string", "description": "用户能理解的目标说明。"},
                "task_run_goal": {"type": "string", "description": "执行 agent 应按此推进的具体目标。"},
                "required_artifacts": {"type": "array", "items": {"type": "object"}},
                "required_verifications": {"type": "array", "items": {"type": "object"}},
                "completion_criteria": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["user_visible_goal", "task_run_goal", "completion_criteria"],
        },
    }
