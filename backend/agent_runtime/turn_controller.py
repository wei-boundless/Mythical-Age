from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Callable

from response_system.boundary.boundary import sanitize_visible_assistant_content

from agent_runtime.understanding import (
    build_action_permit,
    build_boundary_policy,
    build_context_candidates,
    build_request_facts,
    main_model_owned_turn_decision,
)
from harness.runtime import AgentRunRequest
from .execution_decision import (
    execution_decision_from_model_turn,
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

        request_facts = build_request_facts(
            user_message=item.user_message,
            session_id=item.session_id,
            task_id="",
            turn_id=item.turn_id,
            source=item.source,
            explicit_selection=item.task_selection,
        ).to_dict()
        record = self.turn_store.transition(
            record,
            "facts_built",
            event_type="request_facts_built",
            request_facts=request_facts,
            phase="request_facts",
            status_code="facts.built",
        )
        yield self._turn_event("request_facts_built", record, {"request_facts": request_facts})

        boundary_policy = build_boundary_policy(
            user_message=item.user_message,
            request_facts=request_facts,
            current_turn_context=dict(item.task_selection or {}),
        ).to_dict()
        record = self.turn_store.transition(
            record,
            "boundary_checked",
            event_type="boundary_policy_checked",
            boundary_policy=boundary_policy,
            phase="boundary_policy",
            status_code="boundary.checked",
        )
        yield self._turn_event("boundary_policy_checked", record, {"boundary_policy": boundary_policy})

        context_candidates = build_context_candidates(
            request_facts=request_facts,
            continuation_candidates=[],
            memory_runtime_view={},
            current_turn_context=dict(item.task_selection or {}),
        ).to_dict()
        record = self.turn_store.transition(
            record,
            "context_candidates_built",
            event_type="context_candidates_built",
            context_candidates=context_candidates,
            phase="context_candidates",
            status_code="context.candidates_built",
        )
        yield self._turn_event("context_candidates_built", record, {"context_candidates": context_candidates})

        record = self.turn_store.transition(
            record,
            "understanding",
            event_type="understanding_started",
            phase="understanding",
            status_code="understanding.started",
        )
        yield self._turn_event("understanding_started", record)
        model_turn_decision, model_turn_diagnostics = await main_model_owned_turn_decision(
            user_message=item.user_message,
            request_facts=request_facts,
            task_selection=item.task_selection,
            model_runtime=getattr(self.model_response_executor, "model_runtime", None),
        )
        decision_status = str(model_turn_diagnostics.get("decision_status") or "")
        if decision_status in {"unresolved", "runtime_error", "blocked"}:
            status = "blocked" if decision_status == "blocked" else "failed"
            record = self.turn_store.transition(
                record,
                status,  # type: ignore[arg-type]
                event_type="understanding_failed",
                payload={"diagnostics": model_turn_diagnostics},
                understanding_decision=model_turn_decision,
                phase="understanding",
                status_code=f"understanding.{decision_status or 'failed'}",
                blocking_reason=str(
                    model_turn_diagnostics.get("unresolved_reason")
                    or model_turn_diagnostics.get("block_reason")
                    or "understanding_failed"
                ),
                terminal_reason="understanding_failed",
            )
            yield self._turn_event("understanding_failed", record, {"diagnostics": model_turn_diagnostics})
            yield {
                "type": "error",
                "error": "Model turn decision unresolved.",
                "code": "model_turn_decision_unresolved",
                "content": str(
                    model_turn_decision.get("clarification_question")
                    or "本轮任务理解未稳定建立，需要补充信息或重试理解决策。"
                ),
                "model_turn_decision": model_turn_decision,
                "diagnostics": model_turn_diagnostics,
            }
            return
        record = self.turn_store.transition(
            record,
            "deciding",
            event_type="understanding_completed",
            payload={"diagnostics": model_turn_diagnostics},
            understanding_decision=model_turn_decision,
            phase="understanding",
            status_code="understanding.completed",
        )
        yield self._turn_event("understanding_completed", record, {"diagnostics": model_turn_diagnostics})
        execution_decision = execution_decision_from_model_turn(
            turn_id=item.turn_id,
            model_turn_decision=model_turn_decision,
        )
        record = self.turn_store.transition(
            record,
            "permit_checking",
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

        action_permit = build_action_permit(
            model_turn_decision=model_turn_decision,
            boundary_policy=boundary_policy,
        ).to_dict()
        if action_permit.get("allowed") is not True:
            record = self.turn_store.transition(
                record,
                "blocked",
                event_type="action_permit_blocked",
                action_permit=action_permit,
                phase="action_permit",
                status_code="action_permit.blocked",
                blocking_reason="action_permit_denied",
                terminal_reason="action_permit_denied",
            )
            yield self._turn_event("action_permit_blocked", record, {"action_permit": action_permit})
            yield {
                "type": "error",
                "error": "Action permit denied before runtime execution.",
                "code": "action_permit_denied",
                "content": "本轮请求被运行许可策略阻止，未进入执行阶段。",
                "action_permit": action_permit,
            }
            return
        record = self.turn_store.transition(
            record,
            "permit_checking",
            event_type="action_permit_checked",
            action_permit=action_permit,
            phase="action_permit",
            status_code="action_permit.allowed",
        )
        yield self._turn_event("action_permit_checked", record, {"action_permit": action_permit})

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
            content = await self._invoke_direct_answer(item=item, model_turn_decision=model_turn_decision)
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
            "model_turn_decision": model_turn_decision,
            "model_turn_decision_diagnostics": model_turn_diagnostics,
            "execution_decision": execution_decision.to_dict(),
            "request_facts": request_facts,
            "boundary_policy": boundary_policy,
            "context_candidates": context_candidates,
            "action_permit": action_permit,
            "task_contract_seed": execution_decision.task_contract_seed,
            "agent_turn_handoff": {
                "authority": "agent_runtime.task_run_handoff",
                "turn_id": item.turn_id,
                "agent_invocation_id": item.agent_invocation_id,
                "session_id": item.session_id,
                "source": "execution_decision",
                "execution_decision": execution_decision.to_dict(),
                "action_permit": action_permit,
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
        model_turn_decision: dict[str, Any],
    ) -> str:
        invoker = getattr(getattr(self.model_response_executor, "model_runtime", None), "invoke_messages", None)
        if not callable(invoker):
            return "模型运行时不可用，本轮停止执行。"
        messages = [
            {
                "role": "system",
                "content": (
                    "你是当前对话轮次的回答 agent。你只回答用户当前问题。"
                    "不要声称已经运行工具、修改文件或创建任务。"
                    "不要输出内部运行 ID、控制协议或隐藏推理。"
                ),
            },
            *[dict(message) for message in list(item.history or [])],
            {
                "role": "user",
                "content": item.user_message,
            },
        ]
        response = await invoker(
            messages,
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
