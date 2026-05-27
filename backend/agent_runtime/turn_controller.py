from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Callable

from response_system.boundary.boundary import sanitize_visible_assistant_content

from harness.runtime import AgentRunRequest, RuntimeCompiler
from .execution_decision import (
    execution_decision_from_payload,
)
from .turn_action_request import (
    execution_decision_from_agent_action,
    main_agent_turn_action_request,
)
from .turn_store import AgentTurnStore


@dataclass(slots=True)
class AgentTurnControllerInput:
    session_id: str
    turn_id: str
    agent_invocation_id: str
    user_message: str
    history: list[dict[str, Any]]
    source: str
    task_id: str
    task_selection: dict[str, Any]
    memory_intent: Any | None
    agent_runtime_profile: Any | None
    search_policy: list[str] | None
    model_selection: dict[str, Any]
    assistant_message_committer: Callable[[dict[str, Any]], Any] | None


class AgentTurnController:
    """Owns ordinary chat-turn control before a formal TaskRun exists."""

    def __init__(
        self,
        *,
        runtime_host: Any,
        agent_harness: Any,
        agent_runtime_chain: Any,
        model_response_executor: Any,
        runtime_context_manager: Any,
        tool_runtime_executor: Any | None,
        tool_instances_provider: Callable[[], list[Any]],
    ) -> None:
        self.runtime_host = runtime_host
        self.agent_harness = agent_harness
        self.agent_runtime_chain = agent_runtime_chain
        self.model_response_executor = model_response_executor
        self.runtime_context_manager = runtime_context_manager
        self.tool_runtime_executor = tool_runtime_executor
        self.tool_instances_provider = tool_instances_provider
        self.runtime_compiler = RuntimeCompiler()
        self.turn_store = AgentTurnStore(
            runtime_objects=runtime_host.runtime_objects,
            event_log=runtime_host.event_log,
        )

    async def run_stream(self, item: AgentTurnControllerInput) -> AsyncIterator[dict[str, Any]]:
        record = self.turn_store.create(
            turn_id=item.turn_id,
            session_id=item.session_id,
            agent_invocation_id=item.agent_invocation_id,
            user_message=item.user_message,
            source=item.source,
            diagnostics={"task_id_seed": item.task_id},
        )
        yield self._turn_event("agent_turn_received", record)

        record = self.turn_store.transition(
            record,
            "agent_invoking",
            event_type="agent_turn_action_request_started",
            phase="agent_action_request",
            status_code="agent_action_request.started",
        )
        yield self._turn_event("agent_turn_action_request_started", record)
        action_request, action_diagnostics = await main_agent_turn_action_request(
            user_message=item.user_message,
            history=item.history,
            turn_id=item.turn_id,
            task_selection=item.task_selection,
            model_runtime=getattr(self.model_response_executor, "model_runtime", None),
            model_selection=item.model_selection,
            runtime_compiler=self.runtime_compiler,
            session_id=item.session_id,
            agent_invocation_id=item.agent_invocation_id,
            agent_profile_ref=str(getattr(item.agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
        )
        action_runtime_context = _runtime_context_from_diagnostics(action_diagnostics)
        if action_runtime_context:
            self.runtime_host.event_log.append(
                f"agent-turn:{item.turn_id}",
                "runtime_invocation_packet_compiled",
                payload=action_runtime_context,
                refs={
                    "turn_ref": item.turn_id,
                    "runtime_envelope_ref": action_runtime_context.get("runtime_envelope_ref", ""),
                    "runtime_invocation_packet_ref": action_runtime_context.get("runtime_invocation_packet_ref", ""),
                },
            )
        decision_status = str(action_diagnostics.get("decision_status") or "")
        if decision_status in {"unresolved", "runtime_error", "blocked", "rejected_invalid"}:
            status = "blocked" if decision_status == "blocked" else "failed"
            record = self.turn_store.transition(
                record,
                status,  # type: ignore[arg-type]
                event_type="agent_turn_action_request_failed",
                payload={"diagnostics": action_diagnostics},
                agent_turn_action_request=action_request,
                runtime_context=action_runtime_context,
                phase="agent_action_request",
                status_code=f"agent_action_request.{decision_status or 'failed'}",
                blocking_reason=str(
                    action_diagnostics.get("unresolved_reason")
                    or action_diagnostics.get("block_reason")
                    or "agent_turn_action_request_failed"
                ),
                terminal_reason="agent_turn_action_request_failed",
            )
            yield self._turn_event("agent_turn_action_request_failed", record, {"diagnostics": action_diagnostics})
            yield {
                "type": "error",
                "error": "Agent turn action request unresolved.",
                "code": "agent_turn_action_request_unresolved",
                "content": str(action_request.get("user_question") or "本轮请求还需要补充信息或重试。"),
            }
            return
        record = self.turn_store.transition(
            record,
            "action_requesting",
            event_type="agent_turn_action_request_completed",
            payload={"diagnostics": action_diagnostics},
            agent_turn_action_request=action_request,
            runtime_context=action_runtime_context,
            phase="agent_action_request",
            status_code="agent_action_request.completed",
        )
        yield self._turn_event("agent_turn_action_request_completed", record, {"diagnostics": action_diagnostics})
        execution_payload = execution_decision_from_agent_action(
            turn_id=item.turn_id,
            action_request=action_request,
        )
        execution_decision, execution_validation = execution_decision_from_payload(
            execution_payload,
            turn_id=item.turn_id,
        )
        if execution_decision is None:
            record = self.turn_store.transition(
                record,
                "failed",
                event_type="execution_decision_failed",
                payload={"diagnostics": execution_validation},
                phase="execution_decision",
                status_code="execution_decision.invalid",
                terminal_reason="execution_decision_invalid",
            )
            yield self._turn_event("execution_decision_failed", record, {"diagnostics": execution_validation})
            yield {
                "type": "error",
                "error": "Agent action request could not be admitted.",
                "code": "execution_decision_invalid",
                "content": "本轮动作请求未通过系统准入。",
            }
            return
        record = self.turn_store.transition(
            record,
            "admission_checking",
            event_type="execution_decision_completed",
            execution_decision=execution_decision.to_dict(),
            phase="execution_decision",
            status_code=execution_decision.status_code,
        )
        yield self._turn_event(
            "execution_decision_completed",
            record,
            {"execution_decision": execution_decision.to_dict()},
        )

        if execution_decision.execution_mode == "ask_clarification":
            async for event in self._complete_direct_turn(
                record=record,
                content=execution_decision.clarification_question,
                assistant_message_committer=item.assistant_message_committer,
                answer_source="agent_turn.clarification",
                terminal_status="clarification_required",
            ):
                yield event
            return

        if execution_decision.execution_mode == "block":
            record = self.turn_store.transition(
                record,
                "blocked",
                event_type="agent_turn_blocked",
                phase="blocked",
                status_code="turn.blocked",
                blocking_reason=execution_decision.blocking_reason,
                terminal_reason="blocked",
            )
            yield self._turn_event("agent_turn_blocked", record)
            yield {
                "type": "error",
                "error": execution_decision.blocking_reason or "blocked",
                "code": "agent_turn_blocked",
                "content": execution_decision.blocking_reason or "本轮请求被阻止。",
            }
            return

        if execution_decision.execution_mode == "direct_answer":
            record = self.turn_store.transition(
                record,
                "direct_responding",
                event_type="direct_response_started",
                phase="direct_response",
                status_code="direct_response.started",
            )
            yield self._turn_event("direct_response_started", record)
            content = str(action_request.get("final_answer") or "")
            if not content:
                content = await self._invoke_direct_answer(item=item, action_request=action_request)
            async for event in self._complete_direct_turn(
                record=record,
                content=content,
                assistant_message_committer=item.assistant_message_committer,
                answer_source="agent_turn.direct_response",
                terminal_status="completed",
            ):
                yield event
            return

        record = self.turn_store.transition(
            record,
            "launching_task_run",
            event_type="task_run_launch_requested",
            phase="launching_task_run",
            status_code="task_run.launch_requested",
            execution_decision=execution_decision.to_dict(),
        )
        yield self._turn_event("task_run_launch_requested", record, {"execution_decision": execution_decision.to_dict()})
        runtime_task_selection = {
            **dict(item.task_selection or {}),
            "turn_id": item.turn_id,
            "agent_invocation_id": item.agent_invocation_id,
            "agent_turn_action_request": action_request,
            "agent_turn_action_diagnostics": action_diagnostics,
            "execution_decision": execution_decision.to_dict(),
            "task_contract_seed": execution_decision.task_contract_seed,
            "agent_turn_handoff": {
                "authority": "agent_runtime.task_run_handoff",
                "turn_id": item.turn_id,
                "agent_invocation_id": item.agent_invocation_id,
                "session_id": item.session_id,
                "source": "agent_turn_action_request",
                "execution_decision": execution_decision.to_dict(),
                "agent_turn_action_request": action_request,
                "task_contract_seed": execution_decision.task_contract_seed,
                "resource_contract": dict(execution_decision.task_contract_seed.get("resource_contract") or {}),
                "completion_contract": execution_decision.completion_contract,
                "status_code": "task_run.launch_requested",
                "phase": "launching_task_run",
            },
        }
        task_started = False
        async for event in self.agent_harness.run_stream(
            AgentRunRequest(
                session_id=item.session_id,
                task_id=item.task_id,
                user_message=item.user_message,
                history=item.history,
                source=item.source,
                agent_runtime_chain=self.agent_runtime_chain,
                model_response_executor=self.model_response_executor,
                runtime_context_manager=self.runtime_context_manager,
                memory_intent=item.memory_intent,
                task_selection=runtime_task_selection,
                assistant_message_committer=item.assistant_message_committer,
                tool_runtime_executor=self.tool_runtime_executor,
                tool_instances=self.tool_instances_provider(),
                agent_runtime_profile=item.agent_runtime_profile,
                search_policy=item.search_policy,
                model_selection=item.model_selection,
            )
        ):
            if event.get("type") == "harness_run_started":
                task_run = dict(event.get("task_run") or {})
                active_task_run_id = str(task_run.get("task_run_id") or "")
                record = self.turn_store.transition(
                    record,
                    "waiting_task_run",
                    event_type="task_run_launched",
                    active_task_run_id=active_task_run_id,
                    phase="waiting_task_run",
                    status_code="task_run.launched",
                    payload={"task_run_status": str(task_run.get("status") or "")},
                )
                task_started = True
                yield self._turn_event("task_run_launched", record, {"task_run_status": str(task_run.get("status") or "")})
            if event.get("type") in {"done", "error", "stopped"}:
                terminal_status = "completed" if event.get("type") == "done" else "failed"
                record = self.turn_store.transition(
                    record,
                    terminal_status,  # type: ignore[arg-type]
                    event_type="task_run_terminal_observed",
                    phase="closing",
                    status_code=f"task_run.{event.get('type')}",
                    terminal_reason=str(event.get("terminal_reason") or event.get("type") or ""),
                    payload={"event_type": event.get("type")},
                )
                yield self._turn_event("task_run_terminal_observed", record, {"event_type": event.get("type")})
            yield event
        if not task_started:
            record = self.turn_store.transition(
                record,
                "failed",
                event_type="agent_turn_failed",
                phase="launching_task_run",
                status_code="task_run.not_started",
                terminal_reason="task_run_not_started",
            )
            yield self._turn_event("agent_turn_failed", record)

    async def _invoke_direct_answer(
        self,
        *,
        item: AgentTurnControllerInput,
        action_request: dict[str, Any],
    ) -> str:
        invoker = getattr(getattr(self.model_response_executor, "model_runtime", None), "invoke_messages", None)
        if not callable(invoker):
            return "模型运行时不可用，本轮停止执行。"
        compilation = self.runtime_compiler.compile_direct_answer_packet(
            session_id=item.session_id,
            turn_id=item.turn_id,
            agent_invocation_id=item.agent_invocation_id,
            user_message=item.user_message,
            history=item.history,
            agent_profile_ref=str(getattr(item.agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"),
            model_selection=item.model_selection,
        )
        self.runtime_host.event_log.append(
            f"agent-turn:{item.turn_id}",
            "runtime_invocation_packet_compiled",
            payload={
                "runtime_envelope": compilation.envelope.to_dict(),
                "runtime_invocation_packet": compilation.packet.to_dict(),
            },
            refs={
                "turn_ref": item.turn_id,
                "runtime_envelope_ref": compilation.envelope.envelope_id,
                "runtime_invocation_packet_ref": compilation.packet.packet_id,
            },
        )
        response = await invoker(
            list(compilation.packet.model_messages),
            **({"model_spec": item.model_selection} if item.model_selection else {}),
        )
        return sanitize_visible_assistant_content(_stringify_content(getattr(response, "content", response)))

    async def _complete_direct_turn(
        self,
        *,
        record: Any,
        content: str,
        assistant_message_committer: Callable[[dict[str, Any]], Any] | None,
        answer_source: str,
        terminal_status: str,
    ) -> AsyncIterator[dict[str, Any]]:
        final_content = sanitize_visible_assistant_content(str(content or ""))
        commit_payload = {
            "role": "assistant",
            "content": final_content,
            "answer_channel": "final_answer",
            "answer_source": answer_source,
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
        }
        commit_result = None
        if assistant_message_committer is not None:
            commit_result = assistant_message_committer(commit_payload)
            if hasattr(commit_result, "__await__"):
                commit_result = await commit_result
        status = "completed" if terminal_status == "completed" else "clarification_required"
        record = self.turn_store.transition(
            record,
            "closing",
            event_type="agent_turn_closing",
            payload={"commit_attempted": assistant_message_committer is not None},
            phase="closing",
            status_code="turn.closing",
        )
        yield self._turn_event("agent_turn_closing", record)
        record = self.turn_store.transition(
            record,
            status,  # type: ignore[arg-type]
            event_type="agent_turn_completed" if status == "completed" else "agent_turn_clarification_required",
            payload={"commit_result": _safe_commit_result(commit_result)},
            phase="completed",
            status_code=f"turn.{status}",
            terminal_reason=status,
        )
        yield self._turn_event("agent_turn_completed" if status == "completed" else "agent_turn_clarification_required", record)
        yield {
            "type": "done",
            "content": final_content,
            "answer_channel": "final_answer",
            "answer_source": answer_source,
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
            "agent_turn": {
                "turn_id": record.turn_id,
                "status": status,
                "status_code": record.status_code,
            },
        }

    @staticmethod
    def _turn_event(event_type: str, record: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "type": "agent_turn_event",
            "event": {
                "event_type": event_type,
                "turn_id": record.turn_id,
                "session_id": record.session_id,
                "status": record.status,
                "phase": record.phase,
                "status_code": record.status_code,
                "blocking_reason": record.blocking_reason,
                **dict(payload or {}),
            },
        }


def _safe_commit_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            key: value.get(key)
            for key in (
                "appended_messages",
                "memory_maintenance_status",
                "file_work_context_writeback",
            )
            if key in value
        }
    return {}


def _runtime_context_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    envelope = dict(dict(diagnostics or {}).get("runtime_envelope") or {})
    packet = dict(dict(diagnostics or {}).get("runtime_invocation_packet") or {})
    if not envelope and not packet:
        return {}
    return {
        "runtime_envelope": envelope,
        "runtime_invocation_packet": packet,
        "runtime_envelope_ref": str(envelope.get("envelope_id") or ""),
        "runtime_invocation_packet_ref": str(packet.get("packet_id") or ""),
        "authority": "agent_runtime.turn_runtime_context",
    }


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content or "")
