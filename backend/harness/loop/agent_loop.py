from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

from capability_system.units.tools.agent_todo_tool import AgentTodoTool
from harness.runtime import AgentRunRequest, RuntimeCompiler, build_execution_context
from harness.runtime.public_progress import public_action_progress_summary, public_runtime_progress_summary
from runtime.shared.models import AgentRun, TaskRun

from .admission import admit_model_action
from .model_action_protocol import ModelActionRequest, model_action_request_from_payload
from .model_action_runtime import call_model_invoker, compact_text, model_action_timeout_seconds, parse_json_object
from .observations import build_observation_record
from .presentation import error_event, final_answer_event
from .task_lifecycle import (
    contract_from_action_request,
    requires_task_launch_supervision,
    start_task_lifecycle,
    task_launch_supervision_policy,
    wait_task_launch_supervision,
)
from .task_run_recovery_state import recovery_state_for_task_run, should_auto_continue_task_run


_MAX_TURN_ACTIONS = 6
_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS = 15.0
_MAX_TURN_PROTOCOL_REPAIR_ATTEMPTS = 3


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
    runtime_available_tools = _runtime_available_tools(runtime_assembly_payload)
    available_tools = _turn_direct_tools(runtime_available_tools)
    allowed_tool_names = _runtime_allowed_tool_names(available_tools)
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
        summary="已收到请求，正在整理上下文。",
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
            summary="正在整理上下文，准备判断下一步。",
            refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
        )

        yield _record_step_summary(
            runtime_host,
            task_run_id=turn_task_run.task_run_id,
            turn_id=turn_id,
            step=f"model_action_invocation_started:{action_index}",
            status="running",
            summary="正在处理这一步。",
            refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
        )
        model_action_task: asyncio.Task | None = None
        try:
            model_action_task = asyncio.create_task(
                _invoke_model_action(
                    model_response_executor=request.model_response_executor,
                    packet=compilation.packet,
                    session_id=request.session_id,
                    task_run_id=turn_task_run.task_run_id,
                    turn_id=turn_id,
                    invocation_index=action_index,
                    model_selection=dict(request.model_selection or {}),
                )
            )
            wait_round = 0
            while not model_action_task.done():
                done, _pending = await asyncio.wait(
                    {model_action_task},
                    timeout=_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS,
                )
                if done:
                    break
                wait_round += 1
                yield _record_step_summary(
                    runtime_host,
                    task_run_id=turn_task_run.task_run_id,
                    turn_id=turn_id,
                    step=f"model_action_waiting:{action_index}",
                    status="running",
                    summary="正在等待模型根据当前上下文返回下一步判断。",
                    refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
                )
            action_request, diagnostics = await model_action_task
        except (asyncio.CancelledError, GeneratorExit):
            if model_action_task is not None and not model_action_task.done():
                model_action_task.cancel()
            _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step=f"model_action_invocation_cancelled:{action_index}",
                status="aborted",
                summary="客户端或上游流已断开，系统已终止本轮模型等待并关闭 turn 运行记录。",
                refs={"runtime_invocation_packet_ref": compilation.packet.packet_id},
            )
            _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_aborted",
                status="aborted",
                terminal_reason="stream_cancelled",
                payload={"runtime_invocation_packet_ref": compilation.packet.packet_id},
            )
            raise
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
            observation = _build_model_protocol_error_observation(
                packet_ref=compilation.packet.packet_id,
                turn_id=turn_id,
                invocation_index=action_index,
                diagnostics=diagnostics,
            )
            observations.append(observation)
            runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
            observation_event = runtime_host.event_log.append(
                turn_task_run.task_run_id,
                "model_action_protocol_observation_recorded",
                payload={"observation": observation, "diagnostics": diagnostics},
                refs={
                    "turn_ref": turn_id,
                    "observation_ref": observation["observation_id"],
                    "runtime_invocation_packet_ref": compilation.packet.packet_id,
                },
            )
            yield {"type": "bounded_observation", "event": observation_event.to_dict()}
            yield _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step=f"model_action_protocol_repair_required:{action_index}",
                status="running",
                summary="当前步骤输出格式不完整，正在自动修正后继续。",
                refs={
                    "observation_ref": observation["observation_id"],
                    "runtime_invocation_packet_ref": compilation.packet.packet_id,
                },
            )
            if _turn_protocol_repair_count(observations) >= _MAX_TURN_PROTOCOL_REPAIR_ATTEMPTS:
                content = "本轮动作请求多次未通过协议校验，运行时已按 fail-closed 停止。"
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
            summary=_action_progress_note(action_request),
            public_progress_note=action_request.public_progress_note,
            agent_brief_output=compact_text(action_request.final_answer, limit=300) if action_request.action_type == "respond" else "",
            presentation_source="model_action.public_progress_note" if action_request.public_progress_note else "model_action.action_type_fallback",
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
            summary="安全边界已确认。" if admission.decision == "allow" else "当前步骤未通过安全边界检查。",
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
            yield _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step="bounded_observation_started",
                status="running",
                summary=_turn_tool_call_progress_summary(action_request),
                presentation_source="system.tool_call_status",
                refs={"action_request_ref": action_request.request_id},
            )
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
                summary="已完成一次必要观察，正在根据结果继续。",
                agent_brief_output=_turn_observation_brief(observation),
                presentation_source="tool_observation.summary",
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

        if action_request.action_type == "request_registered_engagement":
            from task_system.engagement import EngagementService

            engagement_payload = dict(action_request.engagement_request or {})
            plan_id = str(engagement_payload.get("plan_id") or "").strip()
            startup_parameters = dict(engagement_payload.get("startup_parameters") or {})
            result = EngagementService(runtime_host.backend_dir).start(
                runtime_host=runtime_host,
                plan_id=plan_id,
                session_id=request.session_id,
                startup_parameters=startup_parameters,
                requested_by="agent",
                source_ref=action_request.request_id,
                turn_id=turn_id,
            )
            engagement_event = runtime_host.event_log.append(
                turn_task_run.task_run_id,
                "registered_engagement_requested",
                payload={"result": result, "action_request": action_request.to_dict()},
                refs={"turn_ref": turn_id, "action_request_ref": action_request.request_id},
            )
            yield {"type": "registered_engagement", "event": engagement_event.to_dict()}
            if result.get("decision") == "started":
                task_run = dict(result.get("task_run") or {})
                yield _record_step_summary(
                    runtime_host,
                    task_run_id=turn_task_run.task_run_id,
                    turn_id=turn_id,
                    step="registered_engagement_started",
                    status="completed",
                    summary="已按当前计划开始处理。",
                    refs={
                        "action_request_ref": action_request.request_id,
                        "task_run_ref": str(task_run.get("task_run_id") or ""),
                        "engagement_run_ref": str(dict(result.get("engagement_run") or {}).get("engagement_run_id") or ""),
                    },
                )
                task_run_id = str(task_run.get("task_run_id") or "")
                if task_run_id:
                    _schedule_task_executor(runtime_host, task_run_id)
                content = "我已按当前计划开始处理，后续进展会继续汇总在这里。"
                await _commit_assistant_message(
                    request.assistant_message_committer,
                    content=content,
                    turn_id=turn_id,
                    answer_source="harness.loop.single_agent.registered_engagement",
                )
                terminal_event = _record_turn_terminal(
                    runtime_host,
                    turn_task_run=turn_task_run,
                    turn_agent_run=turn_agent_run,
                    turn_id=turn_id,
                    event_type="agent_turn_completed",
                    status="task_executor_scheduled",
                    terminal_reason="registered_engagement_started",
                    payload={"action_request": action_request.to_dict(), "engagement": result},
                )
                yield {"type": "agent_turn_terminal", "event": terminal_event}
                yield final_answer_event(
                    content=content,
                    answer_source="harness.loop.single_agent.registered_engagement",
                    terminal_reason="registered_engagement_started",
                    extra={"agent_turn": {"turn_id": turn_id, "status": "task_executor_scheduled"}},
                )
                return
            observation = {
                "observation_id": f"observation:{turn_id}:engagement:{len(observations) + 1}",
                "observation_kind": "registered_engagement_admission",
                "status": "failed",
                "content": result,
                "authority": "harness.loop.registered_engagement_observation",
            }
            observations.append(observation)
            runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
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
                task_environment_id=_runtime_task_environment_id(runtime_assembly_payload),
            )
            if contract is None:
                observation = _build_task_contract_error_observation(
                    packet_ref=compilation.packet.packet_id,
                    action_request=action_request,
                    contract_errors=contract_errors,
                )
                observations.append(observation)
                runtime_host.runtime_objects.put_object("observation", observation["observation_id"], observation)
                observation_event = runtime_host.event_log.append(
                    turn_task_run.task_run_id,
                    "task_contract_observation_recorded",
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
                    step="task_contract_repair_required",
                    status="running",
                    summary="处理目标还不完整，正在补全必要边界。",
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
            task_run, _agent_run, lifecycle, events = start_task_lifecycle(
                runtime_host,
                session_id=request.session_id,
                turn_id=turn_id,
                task_id=request.task_id,
                action_request=action_request,
                contract=contract,
                agent_profile_ref=agent_profile_ref,
                model_selection=dict(request.model_selection or {}),
            )
            for event in events:
                yield event
            yield _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step="task_lifecycle_started",
                status="running",
                summary="已确认当前处理目标。",
                refs={
                    "action_request_ref": action_request.request_id,
                    "task_run_ref": task_run.task_run_id,
                },
            )
            todo_observation = await _initialize_agent_todo(
                runtime_host=runtime_host,
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
            launch_gate_policy = task_launch_supervision_policy(runtime_assembly)
            if requires_task_launch_supervision(launch_gate_policy):
                gated_task, _gated_lifecycle, gate_event = wait_task_launch_supervision(
                    runtime_host,
                    task_run=task_run,
                    lifecycle=lifecycle,
                    gate_policy=launch_gate_policy,
                )
                yield {"type": "task_run_lifecycle_event", "event": gate_event}
                yield _record_step_summary(
                    runtime_host,
                    task_run_id=turn_task_run.task_run_id,
                    turn_id=turn_id,
                    step="task_launch_supervision_waiting",
                    status="completed",
                    summary="已准备好继续处理，正在等待确认。",
                    refs={"task_run_ref": gated_task.task_run_id},
                )
                content = _task_run_handoff_content(
                    contract=contract.to_dict(),
                    status_text=str(launch_gate_policy.get("user_prompt") or "我已经准备好继续处理。你可以补充建议，或直接确认继续。"),
                    control_text="确认前，我会先停在这里。",
                )
                await _commit_assistant_message(
                    request.assistant_message_committer,
                    content=content,
                    turn_id=turn_id,
                    answer_source="harness.loop.single_agent.task_launch_supervision",
                )
                terminal_event = _record_turn_terminal(
                    runtime_host,
                    turn_task_run=turn_task_run,
                    turn_agent_run=turn_agent_run,
                    turn_id=turn_id,
                    event_type="agent_turn_completed",
                    status="waiting_approval",
                    terminal_reason="task_launch_supervision",
                    payload={
                        "action_request": action_request.to_dict(),
                        "task_run": gated_task.to_dict(),
                        "launch_supervision": launch_gate_policy,
                    },
                )
                yield {"type": "agent_turn_terminal", "event": terminal_event}
                yield final_answer_event(
                    content=content,
                    answer_source="harness.loop.single_agent.task_launch_supervision",
                    terminal_reason="task_launch_supervision",
                    extra={
                        "agent_turn": {"turn_id": turn_id, "status": "waiting_approval"},
                        "task_run": {"task_run_id": gated_task.task_run_id, "status": gated_task.status},
                    },
                )
                return

            _schedule_task_executor(runtime_host, task_run.task_run_id)
            yield _record_step_summary(
                runtime_host,
                task_run_id=turn_task_run.task_run_id,
                turn_id=turn_id,
                step="task_executor_scheduled",
                status="completed",
                summary="已开始处理，后续进展会继续汇总在当前会话里。",
                refs={"task_run_ref": task_run.task_run_id},
            )
            content = _task_run_handoff_content(
                contract=contract.to_dict(),
                status_text="我会按这个目标继续推进。",
                control_text="你可以直接说暂停、继续或停止；进展会汇总在当前会话里。",
            )
            await _commit_assistant_message(
                request.assistant_message_committer,
                content=content,
                turn_id=turn_id,
                answer_source="harness.loop.single_agent.task_executor_schedule",
            )
            terminal_event = _record_turn_terminal(
                runtime_host,
                turn_task_run=turn_task_run,
                turn_agent_run=turn_agent_run,
                turn_id=turn_id,
                event_type="agent_turn_completed",
                status="task_executor_scheduled",
                terminal_reason="task_executor_scheduled",
                payload={
                    "action_request": action_request.to_dict(),
                    "task_run": task_run.to_dict(),
                },
            )
            yield {"type": "agent_turn_terminal", "event": terminal_event}
            yield final_answer_event(
                content=content,
                answer_source="harness.loop.single_agent.task_executor_schedule",
                terminal_reason="task_executor_scheduled",
                extra={
                    "agent_turn": {"turn_id": turn_id, "status": "task_executor_scheduled"},
                    "task_run": {"task_run_id": task_run.task_run_id, "status": task_run.status},
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
    session_id: str,
    task_run_id: str,
    turn_id: str,
    invocation_index: int,
    model_selection: dict[str, Any],
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    model_runtime = getattr(model_response_executor, "model_runtime", None)
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return None, {"status": "invalid", "validation_errors": ["model_runtime_unavailable"]}
    timeout_seconds = model_action_timeout_seconds(
        model_runtime,
        model_selection=model_selection,
    )
    response = await asyncio.wait_for(
        call_model_invoker(
            invoker,
            list(packet.model_messages),
            model_selection=model_selection,
            accounting_context={
                "request_id": f"modelreq:{packet.packet_id}:{invocation_index}",
                "session_id": session_id,
                "task_run_id": task_run_id,
                "turn_id": turn_id,
                "packet_ref": str(packet.packet_id or ""),
                "invocation_index": invocation_index,
                "source": "harness.loop.agent_turn.model_action",
                "segment_plan": dict(getattr(packet, "segment_plan", {}) or {}),
            },
        ),
        timeout=timeout_seconds,
    )
    payload = parse_json_object(getattr(response, "content", response))
    payload.setdefault("request_id", f"model-action:{turn_id}:{invocation_index}")
    return model_action_request_from_payload(payload, turn_id=turn_id, require_public_progress_note=True)


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
                summary=compact_text(result),
                payload={
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "result": str(result or ""),
                    "execution_context": execution_context.to_dict(),
                },
            )
        except Exception as exc:
            structured_error = _structured_error_from_exception(exc)
            observation = build_observation_record(
                source=f"tool:{tool_name}",
                packet_ref=packet_ref,
                action_request_ref=action_request.request_id,
                execution_context_ref=execution_context.execution_context_id,
                summary="工具执行失败。",
                payload={
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "execution_context": execution_context.to_dict(),
                    **({"structured_error": structured_error} if structured_error else {}),
                },
                error=str(exc),
            )
    runtime_host.runtime_objects.put_object("observation", observation.observation_id, observation.to_dict())
    return observation.to_dict()


def _structured_error_from_exception(exc: Exception) -> dict[str, Any]:
    payload = getattr(exc, "structured_error", None)
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in {
            "code": str(payload.get("code") or payload.get("error_code") or "tool_error"),
            "message": str(payload.get("message") or str(exc) or ""),
            "retryable": payload.get("retryable") if isinstance(payload.get("retryable"), bool) else True,
            "origin": str(payload.get("origin") or "tool_provider"),
            "status_code": payload.get("status_code") if isinstance(payload.get("status_code"), int) else None,
        }.items()
        if value not in ("", None)
    }


async def _initialize_agent_todo(
    *,
    runtime_host: Any,
    request: AgentRunRequest,
    session_id: str,
    task_run_id: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    tool = _find_tool_instance(request.tool_instances, "agent_todo")
    source = "tool:agent_todo"
    if tool is None:
        tool = AgentTodoTool(Path(runtime_host.root_dir))
        source = "system:agent_todo"
    args = {
        "operation": "replace",
        "session_id": session_id,
        "task_id": task_run_id,
        "items": [
            {
                "content": str(contract.get("user_visible_goal") or contract.get("task_run_goal") or "继续处理当前工作"),
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
        return {"source": source, "summary": compact_text(result), "payload": {"result": str(result or "")}}
    except Exception as exc:
        return {
            "source": source,
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


def _schedule_task_executor(runtime_host: Any, task_run_id: str) -> None:
    execute_task_run = getattr(runtime_host, "execute_task_run_callback", None)
    if not callable(execute_task_run):
        _mark_task_executor_schedule_failed(
            runtime_host,
            task_run_id=task_run_id,
            error="task_executor_callback_unavailable",
        )
        return
    current_task_run = runtime_host.state_index.get_task_run(task_run_id)
    if current_task_run is None:
        _mark_task_executor_schedule_failed(
            runtime_host,
            task_run_id=task_run_id,
            error="task_run_not_found",
        )
        return
    recovery_state = recovery_state_for_task_run(current_task_run)
    if not recovery_state.executable:
        runtime_host.event_log.append(
            task_run_id,
            "task_run_executor_schedule_rejected",
            payload={
                "task_run_id": task_run_id,
                "reason": f"task_run_not_executable:{recovery_state.reason}",
                "status": str(current_task_run.status or ""),
            },
            refs={"task_run_ref": task_run_id},
        )
        return
    scheduled_event = runtime_host.event_log.append(
        task_run_id,
        "task_run_executor_scheduled",
        payload={"task_run_id": task_run_id, "scheduler": "agent_loop"},
        refs={"task_run_ref": task_run_id},
    )
    runtime_host.state_index.upsert_task_run(
        replace(
            current_task_run,
            status="running",
            updated_at=scheduled_event.created_at,
            latest_event_offset=scheduled_event.offset,
            terminal_reason="",
            diagnostics={
                **dict(current_task_run.diagnostics or {}),
                "executor_status": "scheduled",
                "latest_step": "task_executor_scheduled",
                "latest_step_status": "running",
                "latest_step_summary": "正在准备继续处理。",
            },
        )
    )

    async def _runner() -> None:
        try:
            while True:
                result = execute_task_run(task_run_id)
                if hasattr(result, "__await__"):
                    result = await result
                payload = dict(result or {}) if isinstance(result, dict) else {}
                if not _task_executor_should_continue(runtime_host, task_run_id=task_run_id, result=payload):
                    return
                runtime_host.event_log.append(
                    task_run_id,
                    "task_run_executor_rescheduled",
                    payload={
                        "task_run_id": task_run_id,
                        "reason": str(payload.get("error") or "waiting_executor"),
                    },
                    refs={"task_run_ref": task_run_id},
                )
                _record_step_summary(
                    runtime_host,
                    task_run_id=task_run_id,
                    turn_id=task_run_id,
                    step="task_executor_auto_continue_scheduled",
                    status="running",
                    summary="本轮步骤预算已用尽，正在自动接着处理下一段。",
                    refs={"task_run_ref": task_run_id},
                )
                await asyncio.sleep(0)
        except Exception as exc:
            _mark_task_executor_schedule_failed(
                runtime_host,
                task_run_id=task_run_id,
                error=str(exc) or exc.__class__.__name__,
            )

    _spawn_background_task(runtime_host, _runner(), name=f"task-run-executor:{task_run_id}")


def _task_run_handoff_content(*, contract: dict[str, Any], status_text: str, control_text: str) -> str:
    goal = _first_public_text(
        contract.get("user_visible_goal"),
        contract.get("task_run_goal"),
        "我会把这件事继续推进。",
    )
    criteria = _first_list_items(contract.get("completion_criteria"), limit=2)
    artifacts = _artifact_names(contract.get("required_artifacts"), limit=2)
    verifications = _verification_names(contract.get("required_verifications"), limit=2)
    lines = [f"我会按这个目标推进：{goal}"]
    scope_parts: list[str] = []
    if criteria:
        scope_parts.append("完成标准：" + "；".join(criteria))
    if artifacts:
        scope_parts.append("产物：" + "、".join(artifacts))
    if verifications:
        scope_parts.append("验证：" + "、".join(verifications))
    if scope_parts:
        lines.append("；".join(scope_parts) + "。")
    lines.append(status_text.strip())
    if control_text.strip():
        lines.append(control_text.strip())
    return "\n".join(line for line in lines if line.strip())


def _spawn_background_task(runtime_host: Any, coro: Any, *, name: str = "") -> asyncio.Task[Any]:
    spawner = getattr(runtime_host, "spawn_background_task", None)
    if callable(spawner):
        return spawner(coro, name=name)
    kwargs = {"name": name} if name else {}
    return asyncio.create_task(coro, **kwargs)


def _first_public_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_list_items(value: Any, *, limit: int) -> list[str]:
    result: list[str] = []
    for item in list(value or []):
        text = str(item or "").strip()
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _artifact_names(value: Any, *, limit: int) -> list[str]:
    names: list[str] = []
    for item in list(value or []):
        payload = dict(item or {}) if isinstance(item, dict) else {}
        text = str(payload.get("user_visible_name") or payload.get("artifact_kind") or item or "").strip()
        if text:
            names.append(text)
        if len(names) >= limit:
            break
    return names


def _verification_names(value: Any, *, limit: int) -> list[str]:
    names: list[str] = []
    for item in list(value or []):
        payload = dict(item or {}) if isinstance(item, dict) else {}
        text = str(payload.get("user_visible_name") or payload.get("verification_kind") or item or "").strip()
        if text:
            names.append(text)
        if len(names) >= limit:
            break
    return names


def _task_executor_should_continue(runtime_host: Any, *, task_run_id: str, result: dict[str, Any]) -> bool:
    if str(result.get("error") or "") != "task_execution_step_budget_exhausted":
        return False
    if not bool(result.get("retryable")):
        return False
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return False
    return should_auto_continue_task_run(task_run)


def _mark_task_executor_schedule_failed(runtime_host: Any, *, task_run_id: str, error: str) -> None:
    event = runtime_host.event_log.append(
        task_run_id,
        "task_run_executor_schedule_failed",
        payload={"task_run_id": task_run_id, "error": error},
        refs={"task_run_ref": task_run_id},
    )
    current_task_run = runtime_host.state_index.get_task_run(task_run_id)
    if current_task_run is not None:
        runtime_host.state_index.upsert_task_run(
            replace(
                current_task_run,
                status="blocked",
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                terminal_reason="task_executor_schedule_failed",
                diagnostics={
                    **dict(current_task_run.diagnostics or {}),
                    "executor_status": "blocked",
                    "latest_step": "task_executor_schedule_failed",
                    "latest_step_status": "blocked",
                    "latest_step_summary": f"继续处理时遇到调度失败：{error}",
                    "recoverable_error": {
                        "error_code": "task_executor_schedule_failed",
                        "retryable": True,
                        "detail": error,
                    },
                    "recovery_action": "rerun_task_executor",
                },
            )
        )


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
        execution_runtime_kind="single_agent_turn",
        status="running",
        created_at=now,
        updated_at=now,
        diagnostics={
            "turn_id": turn_id,
            "source": source,
            "execution_runtime_kind": "single_agent_turn",
        },
    )
    agent_run = AgentRun(
        agent_run_id=f"agrun:{task_run_id}:main",
        task_run_id=task_run_id,
        agent_id="agent:0",
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        status="running",
        execution_runtime_kind="single_agent_turn",
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
    public_progress_note: str = "",
    agent_brief_output: str = "",
    presentation_source: str = "",
) -> dict[str, Any]:
    visible_summary = public_runtime_progress_summary(summary)
    visible_note = public_runtime_progress_summary(public_progress_note)
    visible_brief = public_runtime_progress_summary(agent_brief_output)
    payload = {
        "turn_id": turn_id,
        "step": step,
        "status": status,
        "summary": visible_summary,
    }
    if visible_note:
        payload["public_progress_note"] = visible_note
    if visible_brief:
        payload["agent_brief_output"] = visible_brief
    if presentation_source:
        payload["presentation_source"] = presentation_source
    event = runtime_host.event_log.append(
        task_run_id,
        "step_summary_recorded",
        payload=payload,
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
                    "latest_step_summary": visible_summary,
                },
            )
        )
    return {
        "type": "runtime_step_summary",
        "step": step,
        "status": status,
        "summary": visible_summary,
        "event": event.to_dict(),
    }


def _action_progress_note(action_request: ModelActionRequest) -> str:
    return public_runtime_progress_summary(action_request.public_progress_note) or public_action_progress_summary(action_request.action_type)


def _build_task_contract_error_observation(
    *,
    packet_ref: str,
    action_request: ModelActionRequest,
    contract_errors: list[str],
) -> dict[str, Any]:
    errors = [str(item) for item in list(contract_errors or []) if str(item)]
    return build_observation_record(
        source="system:task_contract_validator",
        packet_ref=packet_ref,
        action_request_ref=action_request.request_id,
        execution_context_ref="",
        summary="当前处理目标未通过校验，需要修正后重新提交。",
        payload={
            "error_code": "task_contract_invalid",
            "contract_errors": errors,
            "required_shape": {
                "task_contract_seed": {
                    "user_visible_goal": "必填",
                    "task_run_goal": "必填",
                    "completion_criteria": "至少一条，除非 required_artifacts 或 required_verifications 已提供",
                    "required_artifacts": "真实交付物要求列表",
                    "required_verifications": "验收或验证要求列表",
                }
            },
            "rejected_action_request": action_request.to_dict(),
        },
        error="task_contract_invalid:" + ";".join(errors),
    ).to_dict()


def _build_model_protocol_error_observation(
    *,
    packet_ref: str,
    turn_id: str,
    invocation_index: int,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    errors = [str(item) for item in list(dict(diagnostics or {}).get("validation_errors") or []) if str(item)]
    return build_observation_record(
        source="system:model_action_protocol_validator",
        packet_ref=packet_ref,
        action_request_ref=f"model-action-invalid:{turn_id}:{invocation_index}",
        execution_context_ref="",
        summary="当前步骤输出格式不完整，需要修正后继续。",
        payload={
            "error_code": "model_action_invalid",
            "validation_errors": errors,
            "required_shape": {
                "authority": "harness.loop.model_action_request",
                "action_type": "respond|ask_user|tool_call|request_task_run|request_registered_engagement|block",
                "tool_call": {"tool_name": "工具名", "args": {}},
                "task_contract_seed": {
                    "user_visible_goal": "开始持续处理时必填",
                    "task_run_goal": "开始持续处理时必填",
                    "completion_criteria": "真实验收标准",
                },
            },
            "repair_instruction": "不要输出 Markdown 或解释文字；只输出一个 JSON 对象，并选择一个合法 action_type。",
            "turn_id": turn_id,
        },
        error="model_action_invalid:" + ";".join(errors),
    ).to_dict()


def _turn_protocol_repair_count(observations: list[dict[str, Any]]) -> int:
    count = 0
    for observation in observations:
        payload = dict(observation.get("payload") or {})
        if str(payload.get("error_code") or "") == "model_action_invalid":
            count += 1
    return count


def _turn_task_terminal_state(*, status: str, event_type: str) -> tuple[str, str]:
    if status in {"completed", "task_executor_scheduled"}:
        return "completed", "completed"
    if status in {"aborted", "cancelled"} or event_type == "agent_turn_aborted":
        return "aborted", "stream_cancelled"
    if status == "waiting_approval":
        return "waiting_approval", "waiting_approval"
    if status in {"blocked", "clarification_required"} or event_type == "agent_turn_blocked":
        return "blocked", "blocked_by_gate"
    return "failed", "internal_error"


def _runtime_assembly_payload(runtime_assembly: Any) -> dict[str, Any]:
    if hasattr(runtime_assembly, "to_dict"):
        payload = runtime_assembly.to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    return dict(runtime_assembly or {}) if isinstance(runtime_assembly, dict) else {}


def _runtime_available_tools(runtime_assembly_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(runtime_assembly_payload.get("available_tools") or [])
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    ]


def _runtime_task_environment_id(runtime_assembly_payload: dict[str, Any]) -> str:
    environment = dict(runtime_assembly_payload.get("task_environment") or {})
    return str(
        environment.get("environment_id")
        or environment.get("task_environment_id")
        or ""
    ).strip()


def _turn_direct_tools(available_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in available_tools
        if _tool_can_run_directly_in_turn(item)
    ]


def _tool_can_run_directly_in_turn(tool: dict[str, Any]) -> bool:
    if bool(tool.get("read_only") is True):
        return True
    return False


def _runtime_allowed_tool_names(available_tools: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("tool_name") or "").strip()
        for item in available_tools
        if str(item.get("tool_name") or "").strip()
    }


def _turn_tool_call_progress_summary(action_request: ModelActionRequest) -> str:
    tool_call = dict(action_request.tool_call or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    target = _turn_tool_target_preview(args)
    display = tool_name.replace("_", " ") if tool_name else "工具"
    if target:
        return f"正在调用{display}处理 {target}。"
    return f"正在调用{display}处理当前步骤。"


def _turn_tool_target_preview(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "target_path", "prompt", "query", "command"):
        value = str(args.get(key) or "").strip()
        if value:
            return " ".join(value.split())[:120].rstrip()
    return ""


def _turn_observation_brief(observation: dict[str, Any]) -> str:
    payload = dict(observation.get("payload") or {})
    for value in (
        observation.get("summary"),
        payload.get("summary"),
        payload.get("result"),
        payload.get("error"),
        observation.get("error"),
    ):
        text = compact_text(value, limit=180)
        if text:
            return text
    return ""


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
