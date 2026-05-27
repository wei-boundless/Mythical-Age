from __future__ import annotations

import asyncio
import json
import inspect
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from harness.runtime import AgentRunRequest, RuntimeCompiler, build_execution_context
from runtime.shared.models import AgentRun, TaskRun

from .admission import admit_model_action
from .model_action_protocol import ModelActionRequest, model_action_request_from_payload
from .observations import build_observation_record
from .presentation import error_event, final_answer_event
from .task_lifecycle import (
    contract_from_action_request,
    start_task_lifecycle,
    wait_task_lifecycle_executor,
)


_MAX_TURN_ACTIONS = 6


async def run_agent_invocation_stream(
    runtime_host: Any,
    request: AgentRunRequest,
) -> AsyncIterator[dict[str, Any]]:
    """Run one generic agent turn through action, admission, observation, and closeout."""

    compiler = RuntimeCompiler()
    turn_id = str(request.turn_id or dict(request.task_selection or {}).get("turn_id") or request.task_id)
    agent_invocation_id = str(
        dict(request.agent_invocation or {}).get("agent_invocation_id")
        or dict(request.task_selection or {}).get("agent_invocation_id")
        or f"aginvoke:{turn_id}:main"
    )
    runtime_assembly = request.runtime_assembly
    runtime_assembly_payload = _runtime_assembly_payload(runtime_assembly)
    runtime_profile = dict(runtime_assembly_payload.get("profile") or {})
    agent_profile_ref = str(
        runtime_assembly_payload.get("agent_profile_ref")
        or getattr(request.agent_runtime_profile, "agent_profile_id", "")
        or "main_interactive_agent"
    )
    available_tools = _runtime_available_tools(runtime_assembly_payload)
    allowed_tool_names = _runtime_allowed_tool_names(runtime_assembly_payload, available_tools)
    observations: list[dict[str, Any]] = []
    seen_action_request_ids: set[str] = set()
    turn_task_run, turn_agent_run, start_event = _start_turn_runtime(
        runtime_host,
        session_id=request.session_id,
        turn_id=turn_id,
        task_id=request.task_id,
        agent_profile_ref=agent_profile_ref,
        source=request.source,
    )
    yield {
        "type": "harness_run_started",
        "task_run": turn_task_run.to_dict(),
        "event": start_event,
    }
    yield _record_step_summary(
        runtime_host,
        task_run_id=turn_task_run.task_run_id,
        turn_id=turn_id,
        step="turn_started",
        status="running",
        summary="系统已创建本轮单 agent 运行记录，并开始装配运行时。",
    )
    if not runtime_assembly_payload:
        content = "本轮缺少 runtime assembly，系统已按 fail-closed 停止。"
        await _commit_assistant_message(
            request.assistant_message_committer,
            content=content,
            turn_id=turn_id,
            answer_source="harness.loop.single_agent.runtime_assembly_missing",
        )
        terminal_event = _record_turn_terminal(
            runtime_host,
            turn_task_run=turn_task_run,
            turn_agent_run=turn_agent_run,
            turn_id=turn_id,
            event_type="agent_turn_failed",
            status="failed",
            terminal_reason="runtime_assembly_missing",
            payload={},
        )
        yield {"type": "agent_turn_terminal", "event": terminal_event}
        yield error_event(
            content=content,
            code="runtime_assembly_missing",
            reason="runtime_assembly_missing",
        )
        return
    assembly_event = runtime_host.event_log.append(
        turn_task_run.task_run_id,
        "runtime_assembly_bound",
        payload={"runtime_assembly": runtime_assembly_payload},
        refs={
            "turn_ref": turn_id,
            "runtime_assembly_ref": str(runtime_assembly_payload.get("assembly_id") or ""),
        },
    )
    yield {"type": "runtime_assembly_bound", "event": assembly_event.to_dict()}
    compilation = compiler.compile_turn_action_packet(
        session_id=request.session_id,
        turn_id=turn_id,
        agent_invocation_id=agent_invocation_id,
        user_message=request.user_message,
        history=request.history,
        task_selection=request.task_selection,
        agent_profile_ref=agent_profile_ref,
        model_selection=request.model_selection,
        available_tools=available_tools,
        runtime_assembly=runtime_assembly,
    )
    for action_index in range(1, _MAX_TURN_ACTIONS + 1):
        packet_event = runtime_host.event_log.append(
            turn_task_run.task_run_id,
            "runtime_invocation_packet_compiled",
            payload=compilation.to_dict(),
            refs={
                "turn_ref": turn_id,
                "runtime_envelope_ref": compilation.envelope.envelope_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
            },
        )
        yield {
            "type": "runtime_invocation_packet",
            "packet_ref": compilation.packet.packet_id,
            "event": packet_event.to_dict(),
        }
        yield _record_step_summary(
            runtime_host,
            task_run_id=turn_task_run.task_run_id,
            turn_id=turn_id,
            step="runtime_packet_compiled",
            status="running",
            summary="系统已装配本次调用的 runtime packet，并交给 agent 决定下一步动作。",
            refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
        )

        try:
            action_request, diagnostics = await _invoke_model_action(
                model_response_executor=request.model_response_executor,
                packet=compilation.packet,
                turn_id=turn_id,
                invocation_index=action_index,
                model_selection=dict(request.model_selection or {}),
            )
        except Exception as exc:
            content = "模型调用失败，运行时已按 fail-closed 停止。"
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=content,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.model_call_failed",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_failed",
                status="failed",
                terminal_reason="model_call_failed",
                payload={"error": str(exc)},
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield error_event(
                content=content,
                code="model_call_failed",
                reason=str(exc) or "model_call_failed",
            )
            return
        if action_request is None:
            content = "本轮动作请求未通过协议校验，运行时已按 fail-closed 停止。"
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=content,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.protocol_error",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_failed",
                status="failed",
                terminal_reason="model_action_invalid",
                payload={"diagnostics": diagnostics},
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield error_event(
                content=content,
                code="model_action_invalid",
                reason="model_action_invalid",
            )
            return
        if action_request.request_id in seen_action_request_ids:
            content = "模型重复提交了同一个动作请求，运行时已停止以避免重复执行。"
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=content,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.duplicate_action",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_failed",
                status="failed",
                terminal_reason="duplicate_action_request",
                payload={"action_request": action_request.to_dict()},
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield error_event(
                content=content,
                code="duplicate_action_request",
                reason="duplicate_action_request",
            )
            return
        seen_action_request_ids.add(action_request.request_id)
        action_event = runtime_host.event_log.append(
            turn_task_run.task_run_id,
            "model_action_request_received",
            payload={"model_action_request": action_request.to_dict(), "diagnostics": diagnostics},
            refs={
                "turn_ref": turn_id,
                "action_request_ref": action_request.request_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
            },
        )
        yield {"type": "model_action_request", "event": action_event.to_dict()}
        yield _record_step_summary(
            runtime_host,
            task_run_id=turn_task_run.task_run_id,
            turn_id=turn_id,
            step="model_action_received",
            status="running",
            summary=f"agent 已返回动作请求：{action_request.action_type}。",
            refs={"action_request_ref": action_request.request_id},
        )

        admission = admit_model_action(
            action_request,
            definitions_by_name=getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}),
            allowed_tool_names=allowed_tool_names,
            runtime_profile=runtime_profile,
            operation_gate=getattr(runtime_host, "operation_gate", None),
            permission_mode=runtime_host._current_permission_mode(),
            directive_ref=f"bounded-observation:{action_request.request_id}",
            workspace_root=runtime_host.backend_dir,
        )
        admission_event = runtime_host.event_log.append(
            turn_task_run.task_run_id,
            "model_action_admission_checked",
            payload={"admission": admission.to_dict()},
            refs={
                "turn_ref": turn_id,
                "action_request_ref": action_request.request_id,
                "admission_ref": admission.admission_id,
            },
        )
        yield {"type": "model_action_admission", "event": admission_event.to_dict()}
        yield _record_step_summary(
            runtime_host,
            task_run_id=turn_task_run.task_run_id,
            turn_id=turn_id,
            step="action_admission_checked",
            status="running",
            summary=f"系统已完成动作准入检查：{admission.decision}。",
            refs={
                "action_request_ref": action_request.request_id,
                "admission_ref": admission.admission_id,
            },
        )
        if admission.decision != "allow":
            content = admission.user_visible_reason or "本轮动作请求未通过系统准入。"
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=content,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.admission",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_blocked" if admission.decision in {"deny", "ask_approval"} else "agent_turn_failed",
                status="waiting_approval" if admission.decision == "ask_approval" else ("blocked" if admission.decision in {"deny", "needs_contract"} else "failed"),
                terminal_reason=admission.system_reason or admission.decision,
                payload={"admission": admission.to_dict(), "action_request": action_request.to_dict()},
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield error_event(
                content=content,
                code=f"admission_{admission.decision}",
                reason=admission.system_reason or admission.decision,
            )
            return

        if action_request.action_type == "respond":
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=action_request.final_answer,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.respond",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_completed",
                status="completed",
                terminal_reason="completed",
                payload={"action_request": action_request.to_dict()},
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield final_answer_event(
                content=action_request.final_answer,
                answer_source="harness.loop.single_agent.respond",
                extra={"agent_turn": {"turn_id": turn_id, "status": "completed"}},
            )
            return

        if action_request.action_type == "ask_user":
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=action_request.user_question,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.ask_user",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_clarification_required",
                status="clarification_required",
                terminal_reason="clarification_required",
                payload={"action_request": action_request.to_dict()},
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield final_answer_event(
                content=action_request.user_question,
                answer_source="harness.loop.single_agent.ask_user",
                terminal_reason="clarification_required",
                extra={"agent_turn": {"turn_id": turn_id, "status": "clarification_required"}},
            )
            return

        if action_request.action_type == "block":
            content = action_request.blocking_reason or "本轮请求被阻止。"
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=content,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.block",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_blocked",
                status="blocked",
                terminal_reason=action_request.blocking_reason or "agent_blocked",
                payload={"action_request": action_request.to_dict()},
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield error_event(
                content=content,
                code="agent_blocked",
                reason=action_request.blocking_reason or "agent_blocked",
            )
            return

        if action_request.action_type == "tool_call":
            observation = await _run_bounded_tool_observation(
                runtime_host,
                request=request,
                turn_id=turn_id,
                packet_ref=compilation.packet.packet_id,
                action_request=action_request,
                admission_ref=admission.admission_id,
            )
            observations.append(observation)
            observation_event = runtime_host.event_log.append(
                turn_task_run.task_run_id,
                "bounded_observation_recorded",
                payload={"observation": observation},
                refs={
                    "turn_ref": turn_id,
                    "action_request_ref": action_request.request_id,
                    "observation_ref": observation["observation_id"],
                },
            )
            yield {"type": "bounded_observation", "event": observation_event.to_dict()}
            yield _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step="bounded_observation_recorded",
                status="running",
                summary="系统已执行一次有边界的只读观察，并把结果回灌给 agent。",
                refs={
                    "action_request_ref": action_request.request_id,
                    "observation_ref": observation["observation_id"],
                },
            )
            compilation = compiler.compile_observation_followup_packet(
                session_id=request.session_id,
                turn_id=turn_id,
                agent_invocation_id=agent_invocation_id,
                user_message=request.user_message,
                history=request.history,
                observations=observations,
                agent_profile_ref=agent_profile_ref,
                model_selection=request.model_selection,
                available_tools=available_tools,
                runtime_assembly=runtime_assembly,
            )
            continue

        if action_request.action_type == "request_task_run":
            contract, contract_errors = contract_from_action_request(
                action_request,
                packet_ref=compilation.packet.packet_id,
            )
            if contract is None:
                content = "正式任务合同不完整，无法开启长任务生命周期。"
                await _commit_assistant_message(
                    request.assistant_message_committer,
                    content=content,
                    turn_id=turn_id,
                    answer_source="harness.loop.single_agent.task_contract_invalid",
                )
                terminal_event = _record_turn_terminal(
                    runtime_host,
                    turn_task_run=turn_task_run,
                    turn_agent_run=turn_agent_run,
                    turn_id=turn_id,
                    event_type="agent_turn_failed",
                    status="failed",
                    terminal_reason="task_contract_invalid",
                    payload={"contract_errors": list(contract_errors), "action_request": action_request.to_dict()},
                )
                yield {"type": "agent_turn_terminal", "event": terminal_event}
                yield error_event(
                    content=content,
                    code="task_contract_invalid",
                    reason=";".join(contract_errors) or "task_contract_invalid",
                )
                return
            task_run, _agent_run, lifecycle, events = start_task_lifecycle(
                runtime_host,
                session_id=request.session_id,
                turn_id=turn_id,
                task_id=request.task_id,
                action_request=action_request,
                contract=contract,
                agent_profile_ref=agent_profile_ref,
            )
            for event in events:
                yield event
            yield _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step="task_lifecycle_started",
                status="running",
                summary="系统已按 agent 的任务合同开启正式任务生命周期。",
                refs={
                    "action_request_ref": action_request.request_id,
                    "task_run_ref": task_run.task_run_id,
                },
            )
            todo_observation = await _initialize_agent_todo(
                request=request,
                session_id=request.session_id,
                task_run_id=task_run.task_run_id,
                contract=contract.to_dict(),
            )
            if todo_observation:
                todo_event = runtime_host.event_log.append(
                    task_run.task_run_id,
                    "agent_todo_initialized",
                    payload={"observation": todo_observation},
                    refs={"task_run_ref": task_run.task_run_id},
                )
                yield {"type": "task_run_lifecycle_event", "event": todo_event.to_dict()}
            waiting_task, _waiting_lifecycle, wait_event = wait_task_lifecycle_executor(
                runtime_host,
                task_run=task_run,
                lifecycle=lifecycle,
                reason="task_executor_rebuild_pending",
            )
            yield {"type": "task_run_lifecycle_event", "event": wait_event}
            yield _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step="task_lifecycle_waiting_executor",
                status="completed",
                summary="正式任务已建立并进入等待执行器接管状态；本轮不会伪报完成。",
                refs={"task_run_ref": waiting_task.task_run_id},
            )
            content = (
                "我已经把这件事转入正式任务并建立了待办。当前任务执行器尚未接管步骤推进，"
                "所以现在停在等待执行状态，不会把未完成的工作报告为完成。"
            )
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=content,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.task_lifecycle",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_completed",
                status="task_lifecycle_waiting_executor",
                terminal_reason="waiting_executor",
                payload={
                    "action_request": action_request.to_dict(),
                    "task_run": waiting_task.to_dict(),
                },
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield final_answer_event(
                content=content,
                answer_source="harness.loop.single_agent.task_lifecycle",
                terminal_reason="waiting_executor",
                extra={
                    "agent_turn": {"turn_id": turn_id, "status": "task_lifecycle_waiting_executor"},
                    "task_run": {"task_run_id": waiting_task.task_run_id, "status": waiting_task.status},
                },
            )
            return

    content = "本轮行动次数超过上限，运行时已停止以避免阻塞。"
    await _commit_assistant_message(
        request.assistant_message_committer,
        content=content,
        turn_id=turn_id,
        answer_source="harness.loop.single_agent.action_budget",
    )
    terminal_event = _record_turn_terminal(
        runtime_host,
        turn_task_run=turn_task_run,
        turn_agent_run=turn_agent_run,
        turn_id=turn_id,
        event_type="agent_turn_failed",
        status="failed",
        terminal_reason="turn_action_budget_exceeded",
        payload={"action_count": _MAX_TURN_ACTIONS},
    )
    yield {"type": "agent_turn_terminal", "event": terminal_event}
    yield error_event(
        content=content,
        code="turn_action_budget_exceeded",
        reason="turn_action_budget_exceeded",
    )


async def _invoke_model_action(
    *,
    model_response_executor: Any,
    packet: Any,
    turn_id: str,
    invocation_index: int,
    model_selection: dict[str, Any],
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    model_runtime = getattr(model_response_executor, "model_runtime", None)
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return None, {"status": "invalid", "validation_errors": ["model_runtime_unavailable"]}
    timeout_seconds = _model_action_timeout_seconds(
        model_runtime,
        model_selection=model_selection,
    )
    response = await asyncio.wait_for(
        _call_model_invoker(
            invoker,
            list(packet.model_messages),
            model_selection=model_selection,
        ),
        timeout=timeout_seconds,
    )
    payload = _parse_json_object(getattr(response, "content", response))
    payload.setdefault("request_id", f"model-action:{turn_id}:{invocation_index}")
    return model_action_request_from_payload(payload, turn_id=turn_id)


async def _call_model_invoker(
    invoker: Any,
    messages: list[Any],
    *,
    model_selection: dict[str, Any],
) -> Any:
    if model_selection:
        try:
            return await _await_if_needed(invoker(messages, model_spec=model_selection))
        except TypeError as exc:
            if "model_spec" not in str(exc):
                raise
    return await _await_if_needed(invoker(messages))


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _model_action_timeout_seconds(
    model_runtime: Any,
    *,
    model_selection: dict[str, Any],
) -> float:
    for key in ("model_response_timeout_seconds", "model_timeout_seconds", "request_timeout_seconds", "timeout_seconds"):
        if key not in model_selection:
            continue
        try:
            value = float(model_selection.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    for attr_name in ("model_call_timeout_seconds", "request_timeout_seconds", "long_output_timeout_seconds"):
        try:
            value = float(getattr(model_runtime, attr_name) or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 180.0


async def _commit_assistant_message(
    committer: Any,
    *,
    content: str,
    turn_id: str,
    answer_source: str,
) -> None:
    if committer is None:
        return
    result = committer(
        {
            "role": "assistant",
            "content": content,
            "turn_id": turn_id,
            "answer_channel": "final_answer",
            "answer_source": answer_source,
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
        }
    )
    if hasattr(result, "__await__"):
        await result


def _parse_json_object(content: Any) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


async def _run_bounded_tool_observation(
    runtime_host: Any,
    *,
    request: AgentRunRequest,
    turn_id: str,
    packet_ref: str,
    action_request: ModelActionRequest,
    admission_ref: str,
) -> dict[str, Any]:
    tool_name = str(action_request.tool_call.get("tool_name") or action_request.tool_call.get("name") or "").strip()
    tool_args = dict(action_request.tool_call.get("args") or action_request.tool_call.get("tool_args") or {})
    definition = getattr(runtime_host.tool_authorization_index, "definitions_by_name", {}).get(tool_name)
    operation_id = str(getattr(definition, "operation_id", "") or tool_name)
    execution_context = build_execution_context(
        packet_ref=packet_ref,
        action_request_ref=action_request.request_id,
        admission_ref=admission_ref,
        tool_name=tool_name,
        operation_id=operation_id,
        workspace_root=runtime_host.backend_dir,
        permission_snapshot={"permission_mode": runtime_host._current_permission_mode(), "bounded_turn": True},
    )
    tool = _find_tool_instance(request.tool_instances, tool_name)
    if tool is None:
        observation = build_observation_record(
            source=f"tool:{tool_name}",
            packet_ref=packet_ref,
            action_request_ref=action_request.request_id,
            execution_context_ref=execution_context.execution_context_id,
            summary="工具实例不可用。",
            payload={"tool_name": tool_name, "tool_args": tool_args, "execution_context": execution_context.to_dict()},
            error="tool_instance_unavailable",
        )
    else:
        try:
            result = await _call_tool(tool, tool_args)
            observation = build_observation_record(
                source=f"tool:{tool_name}",
                packet_ref=packet_ref,
                action_request_ref=action_request.request_id,
                execution_context_ref=execution_context.execution_context_id,
                summary=_compact_text(result),
                payload={
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "result": str(result or ""),
                    "execution_context": execution_context.to_dict(),
                },
            )
        except Exception as exc:
            observation = build_observation_record(
                source=f"tool:{tool_name}",
                packet_ref=packet_ref,
                action_request_ref=action_request.request_id,
                execution_context_ref=execution_context.execution_context_id,
                summary="工具执行失败。",
                payload={"tool_name": tool_name, "tool_args": tool_args, "execution_context": execution_context.to_dict()},
                error=str(exc),
            )
    runtime_host.runtime_objects.put_object("observation", observation.observation_id, observation.to_dict())
    return observation.to_dict()


async def _initialize_agent_todo(
    *,
    request: AgentRunRequest,
    session_id: str,
    task_run_id: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    tool = _find_tool_instance(request.tool_instances, "agent_todo")
    if tool is None:
        return {}
    args = {
        "operation": "replace",
        "session_id": session_id,
        "task_id": task_run_id,
        "items": [
            {
                "content": str(contract.get("user_visible_goal") or contract.get("task_run_goal") or "执行正式任务"),
                "status": "in_progress",
                "evidence_expectations": [
                    *[str(item) for item in list(contract.get("completion_criteria") or [])],
                    *[
                        str(item.get("user_visible_name") or item.get("artifact_kind") or item)
                        for item in list(contract.get("required_artifacts") or [])
                        if isinstance(item, dict)
                    ],
                ],
                "contract_refs": [str(contract.get("contract_id") or "")],
            }
        ],
    }
    try:
        result = await _call_tool(tool, args)
        return {"source": "tool:agent_todo", "summary": _compact_text(result), "payload": {"result": str(result or "")}}
    except Exception as exc:
        return {
            "source": "tool:agent_todo",
            "summary": "任务待办初始化失败。",
            "payload": {"error": str(exc)},
            "error": str(exc),
        }


def _find_tool_instance(tool_instances: list[Any] | None, tool_name: str) -> Any | None:
    for tool in list(tool_instances or []):
        if str(getattr(tool, "name", "") or "").strip() == tool_name:
            return tool
    return None


def _record_turn_terminal(
    runtime_host: Any,
    *,
    turn_task_run: TaskRun,
    turn_agent_run: AgentRun,
    turn_id: str,
    event_type: str,
    status: str,
    terminal_reason: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = runtime_host.event_log.append(
        turn_task_run.task_run_id,
        event_type,
        payload={
            "turn_id": turn_id,
            "status": status,
            "terminal_reason": terminal_reason,
            **dict(payload or {}),
        },
        refs={"turn_ref": turn_id},
    )
    task_status, task_terminal_reason = _turn_task_terminal_state(status=status, event_type=event_type)
    current_task_run = runtime_host.state_index.get_task_run(turn_task_run.task_run_id) or turn_task_run
    runtime_host.state_index.upsert_task_run(
        replace(
            current_task_run,
            status=task_status,  # type: ignore[arg-type]
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            terminal_reason=task_terminal_reason,  # type: ignore[arg-type]
            diagnostics={
                **dict(current_task_run.diagnostics or {}),
                "terminal_event_type": event_type,
                "terminal_status": status,
                "terminal_reason_detail": terminal_reason,
            },
        )
    )
    current_agent_run = (runtime_host.state_index.list_task_agent_runs(turn_task_run.task_run_id) or [turn_agent_run])[-1]
    runtime_host.state_index.upsert_agent_run(
        replace(
            current_agent_run,
            status="failed" if event_type == "agent_turn_failed" else "completed",
            updated_at=event.created_at,
            diagnostics={
                **dict(current_agent_run.diagnostics or {}),
                "terminal_event_type": event_type,
                "terminal_status": status,
                "terminal_reason_detail": terminal_reason,
            },
        )
    )
    return event.to_dict()


def _start_turn_runtime(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    task_id: str,
    agent_profile_ref: str,
    source: str,
) -> tuple[TaskRun, AgentRun, dict[str, Any]]:
    now = time.time()
    task_run_id = f"turnrun:{turn_id}"
    task_run = TaskRun(
        task_run_id=task_run_id,
        session_id=session_id,
        task_id=task_id or turn_id,
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        runtime_lane="single_agent_turn",
        status="running",
        created_at=now,
        updated_at=now,
        diagnostics={
            "turn_id": turn_id,
            "source": source,
            "runtime_kind": "single_agent_turn",
        },
    )
    agent_run = AgentRun(
        agent_run_id=f"agrun:{task_run_id}:main",
        task_run_id=task_run_id,
        agent_id="agent:0",
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        status="running",
        runtime_lane="single_agent_turn",
        created_at=now,
        updated_at=now,
        diagnostics={"turn_id": turn_id, "source": source},
    )
    runtime_host.state_index.upsert_task_run(task_run)
    runtime_host.state_index.upsert_agent_run(agent_run)
    event = runtime_host.event_log.append(
        task_run_id,
        "agent_turn_received",
        payload={
            "turn_id": turn_id,
            "task_run": task_run.to_dict(),
            "agent_run": agent_run.to_dict(),
        },
        refs={"turn_ref": turn_id, "agent_run_ref": agent_run.agent_run_id},
    )
    updated_task_run = replace(
        task_run,
        updated_at=event.created_at,
        latest_event_offset=event.offset,
    )
    runtime_host.state_index.upsert_task_run(updated_task_run)
    return updated_task_run, agent_run, event.to_dict()


def _record_step_summary(
    runtime_host: Any,
    *,
    task_run_id: str,
    turn_id: str,
    step: str,
    status: str,
    summary: str,
    refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = runtime_host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload={
            "turn_id": turn_id,
            "step": step,
            "status": status,
            "summary": summary,
        },
        refs={"turn_ref": turn_id, **dict(refs or {})},
    )
    current_task_run = runtime_host.state_index.get_task_run(task_run_id)
    if current_task_run is not None:
        runtime_host.state_index.upsert_task_run(
            replace(
                current_task_run,
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                diagnostics={
                    **dict(current_task_run.diagnostics or {}),
                    "latest_step": step,
                    "latest_step_status": status,
                    "latest_step_summary": summary,
                },
            )
        )
    return {
        "type": "runtime_step_summary",
        "step": step,
        "status": status,
        "summary": summary,
        "event": event.to_dict(),
    }


def _turn_task_terminal_state(*, status: str, event_type: str) -> tuple[str, str]:
    if status in {"completed", "task_lifecycle_waiting_executor"}:
        return "completed", "completed"
    if status == "waiting_approval":
        return "waiting_approval", "waiting_approval"
    if status in {"blocked", "clarification_required"} or event_type == "agent_turn_blocked":
        return "blocked", "blocked_by_gate"
    return "failed", "internal_error"


def _model_visible_readonly_tools(runtime_host: Any, tool_instances: list[Any] | None) -> list[dict[str, Any]]:
    instance_names = {
        str(getattr(tool, "name", "") or "").strip()
        for tool in list(tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip()
    }
    definitions_by_name = getattr(runtime_host.tool_authorization_index, "definitions_by_name", {})
    visible: list[dict[str, Any]] = []
    for tool_name in sorted(instance_names):
        definition = dict(definitions_by_name or {}).get(tool_name)
        if definition is None:
            continue
        if str(getattr(definition, "runtime_visibility", "") or "main_runtime") != "main_runtime":
            continue
        if str(getattr(definition, "prompt_exposure_policy", "") or "") != "schema_only":
            continue
        if not bool(getattr(definition, "is_read_only", False)):
            continue
        contract = getattr(definition, "contract", None)
        visible.append(
            {
                "tool_name": tool_name,
                "operation_id": str(getattr(definition, "operation_id", "") or ""),
                "display_name": str(getattr(definition, "display_name", "") or tool_name),
                "required_inputs": list(getattr(contract, "required_inputs", []) or []),
                "optional_inputs": list(getattr(contract, "optional_inputs", []) or []),
                "owner_scope": str(getattr(contract, "owner_scope", "") or "none"),
                "read_only": True,
            }
        )
    return visible


async def _call_tool(tool: Any, args: dict[str, Any]) -> Any:
    if callable(getattr(tool, "ainvoke", None)):
        return await tool.ainvoke(dict(args))
    if callable(getattr(tool, "_arun", None)):
        return await tool._arun(**dict(args))
    if callable(getattr(tool, "invoke", None)):
        return tool.invoke(dict(args))
    if callable(getattr(tool, "_run", None)):
        result = tool._run(**dict(args))
        if inspect.isawaitable(result):
            return await result
        return result
    raise RuntimeError(f"Tool is not callable: {getattr(tool, 'name', type(tool).__name__)}")


def _compact_text(value: Any, *, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"
