from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from execution import ModelResponseRuntimeExecutor, ToolRuntimeExecutor
from observability import build_debug_trace_event, start_turn_trace
from orchestration import (
    RuntimeContextManager,
    TaskRunLoop,
    build_base_unit_catalog,
    build_user_message_commit_decision,
)
from prompting import build_static_prompt, build_system_prompt
from query.models import QueryRequest
from runtime.agent_chain import AgentRuntimeChainAssembler
from runtime.model_runtime import ModelRuntimeError
from understanding import analyze_memory_intent

logger = logging.getLogger(__name__)


class QueryRuntime:
    """Thin API adapter for the new single-agent runtime chain.

    The old query layer used to own planning, tool routing, worker orchestration,
    follow-up execution, context restore, and writeback. Those responsibilities
    are intentionally gone from this class. QueryRuntime now only accepts API
    input, emits stream events, and calls the adopted model-only runtime lane.
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        settings_service,
        session_manager,
        memory_facade,
        retrieval_service=None,
        tool_runtime=None,
        skill_registry=None,
        permission_service=None,
        model_runtime,
        task_coordinator=None,
    ) -> None:
        self.base_dir = base_dir
        self.settings_service = settings_service
        self.session_manager = session_manager
        self.memory_facade = memory_facade
        self.model_runtime = model_runtime
        self.tool_runtime = tool_runtime
        self.unit_catalog = build_base_unit_catalog()
        self.tool_contract_gate = SimpleNamespace(
            mode=str(os.getenv("TOOL_CONTRACT_MODE", "shadow") or "shadow").strip().lower()
        )
        self.model_response_executor = ModelResponseRuntimeExecutor(
            model_runtime=model_runtime,
        )
        self.tool_runtime_executor = ToolRuntimeExecutor(tool_runtime=tool_runtime) if tool_runtime is not None else None
        self.agent_runtime_chain = AgentRuntimeChainAssembler(memory_facade=memory_facade)
        self.runtime_context_manager = RuntimeContextManager(self.build_static_system_prompt_for_session)
        self.task_run_loop = TaskRunLoop(base_dir / "runtime-loop")

        self.legacy_query_chain_removed = True
        self.legacy_runtime_components = {
            "query_planner": "removed",
            "runtime_tool_bridge": "removed",
            "runtime_followup": "removed",
            "evidence_orchestrator": "removed",
            "worker_direct_execution": "removed",
        }

    def build_system_prompt_for_session(
        self,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        active_skill: Any | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ) -> str:
        context_package = self.agent_runtime_chain.build_context_package_preview(
            session_id=session_id or "",
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_memory_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
        )
        return build_system_prompt(
            self.base_dir,
            self.settings_service.get_rag_mode(),
            persistent_memory=None,
            session_memory=None,
            context_package=context_package,
            active_skill=self._render_active_skill_prompt(active_skill),
        )

    async def abuild_system_prompt_for_session(self, *args, **kwargs) -> str:
        return self.build_system_prompt_for_session(*args, **kwargs)

    def build_static_system_prompt_for_session(self, *args, **kwargs) -> str:
        return build_static_prompt(
            self.base_dir,
            self.settings_service.get_rag_mode(),
        )

    async def astream(self, request: QueryRequest):
        history_record = self.session_manager.load_session_record(request.session_id)
        history = request.history or self.session_manager.load_session_for_agent(
            request.session_id,
            include_compressed_context=False,
        )
        task_id = f"turn:{request.session_id}:{len(history_record.get('messages', [])) + 1}"
        input_commit_gate = self._commit_user_message(
            session_id=request.session_id,
            content=request.message,
            task_id=task_id,
        )

        try:
            with start_turn_trace(
                session_id=request.session_id,
                user_message=request.message,
                history_length=len(history),
                metadata={"request_kind": "chat", "query_runtime_role": "adapter_only"},
                tags=["query-runtime", "agent-runtime-chain"],
            ) as trace:
                debug_event = build_debug_trace_event(trace)
                if debug_event is not None:
                    yield debug_event
                yield {
                    "type": "input_commit_gate",
                    "commit_gate": input_commit_gate.to_dict(),
                }

                memory_intent = analyze_memory_intent(request.message)
                async for event in self.task_run_loop.run_model_only_stream(
                    session_id=request.session_id,
                    task_id=task_id,
                    user_message=request.message,
                    history=history,
                    source="query_runtime.adapter",
                    agent_runtime_chain=self.agent_runtime_chain,
                    model_response_executor=self.model_response_executor,
                    runtime_context_manager=self.runtime_context_manager,
                    memory_intent=memory_intent,
                    preview_event_builder=lambda chain_preview: self._agent_runtime_chain_preview_events(
                        chain_preview,
                        fail_closed_message="旧 query 编排链已移除；当前只允许 RuntimeDirective + OperationGate 的模型回答通道。",
                        include_fail_closed=False,
                    ),
                    assistant_message_committer=lambda payload: self._apply_assistant_message_commit(
                        request.session_id,
                        payload,
                    ),
                    tool_runtime_executor=self.tool_runtime_executor,
                    tool_instances=self._all_tool_instances(),
                ):
                    yield event
        except Exception as exc:
            failure_text = self._user_visible_error(exc)
            error_payload = {"type": "error", "error": failure_text}
            if isinstance(exc, ModelRuntimeError):
                error_payload["code"] = exc.code
            yield error_payload

    async def _execution_events(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        *,
        ephemeral_system_messages: list[str] | None = None,
        explicit_subtasks: list[dict[str, Any]] | None = None,
        search_policy: list[str] | None = None,
        trace=None,
    ):
        chain_preview = self.agent_runtime_chain.build_live_preview(
            session_id=session_id,
            task_id=f"turn:{session_id}:execution-events",
            message=message,
            source="query_runtime.execution_events_adapter",
        )
        if trace is not None:
            trace.annotate(
                {
                    "app.query_runtime_role": "adapter_only",
                    "app.legacy_query_chain_removed": "true",
                    "app.runtime_channel": "model_response_only",
                }
            )
        for event in self._agent_runtime_chain_preview_events(
            chain_preview,
            fail_closed_message="旧 execution_events 执行链已移除；请走 QueryRuntime.astream 的 RuntimeDirective 主链。",
        ):
            yield event

    def refresh_session_memory(self, session_id: str) -> str:
        history = self.session_manager.load_session(session_id)
        return self.memory_facade.refresh_session_memory(session_id, history)

    def preview_session_memory_refresh(self, session_id: str):
        builder = getattr(self.memory_facade, "build_memory_compaction_preview", None)
        if callable(builder):
            preview = builder(session_id=session_id)
            return preview.to_dict() if hasattr(preview, "to_dict") else dict(preview or {})
        return {"status": "blocked", "reason": "legacy_session_memory_refresh_removed"}

    def commit_durable_memory_extraction(self, session_id: str) -> int:
        history = self.session_manager.load_session(session_id)
        return self.memory_facade.commit_durable_memory_extraction(session_id, history)

    def schedule_durable_memory_extraction(self, session_id: str) -> int:
        history = self.session_manager.load_session(session_id)
        return self.memory_facade.submit_durable_memory_extraction(session_id, history)

    def preview_durable_memory_extraction(self, session_id: str):
        history = self.session_manager.load_session_for_agent(session_id, include_compressed_context=False)
        builder = getattr(self.memory_facade, "build_durable_memory_write_candidates", None)
        if callable(builder):
            candidates = builder(session_id, history)
            return {
                "status": "candidate_only",
                "commit_allowed": False,
                "candidates": [
                    candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
                    for candidate in candidates
                ],
            }
        return {"status": "blocked", "reason": "legacy_durable_memory_extraction_removed"}

    async def generate_title(self, first_user_message: str) -> str:
        return await self.model_runtime.generate_title(first_user_message)

    async def summarize_history(self, messages: list[dict[str, Any]]) -> str:
        return await self.model_runtime.summarize_history(messages)

    async def _run_post_turn_tasks(self, session_id: str, *, title_seed: str | None = None) -> None:
        return None

    def _commit_user_message(self, *, session_id: str, content: str, task_id: str):
        decision = build_user_message_commit_decision(
            session_id=session_id,
            content=content,
            task_id=task_id,
            source="query_runtime.adapter_input",
        )
        if decision.commit_allowed:
            payload = dict(decision.commit_candidate.payload)
            self.session_manager.append_messages(
                session_id,
                [
                    {
                        "role": payload.get("role"),
                        "content": payload.get("content"),
                    }
                ],
            )
        return decision

    def _apply_assistant_message_commit(self, session_id: str, payload: dict[str, Any]):
        appended = self.session_manager.append_messages(
            session_id,
            [
                {
                    "role": payload.get("role"),
                    "content": payload.get("content"),
                    "answer_channel": payload.get("answer_channel"),
                    "answer_source": payload.get("answer_source"),
                    "answer_canonical_state": payload.get("answer_canonical_state"),
                    "answer_persist_policy": payload.get("answer_persist_policy"),
                    "answer_finalization_policy": payload.get("answer_finalization_policy"),
                    "answer_fallback_reason": payload.get("answer_fallback_reason"),
                }
            ],
        )
        history = self.session_manager.load_session(session_id)
        session_memory_chars = 0
        durable_saved_count = 0
        try:
            session_memory_chars = len(self.memory_facade.refresh_session_memory(session_id, history) or "")
        except Exception:
            logger.warning("session memory refresh failed after assistant commit", exc_info=True)
        try:
            durable_saved_count = int(self.memory_facade.commit_durable_memory_extraction(session_id, history) or 0)
        except Exception:
            logger.warning("durable memory extraction failed after assistant commit", exc_info=True)
        return {
            "appended_messages": appended,
            "session_memory_chars": session_memory_chars,
            "durable_saved_count": durable_saved_count,
        }

    def _all_tool_instances(self) -> list[Any]:
        if self.tool_runtime is None:
            return []
        return list(self.tool_runtime.instances)

    def _agent_runtime_chain_preview_events(
        self,
        chain_preview: dict[str, Any],
        *,
        fail_closed_message: str,
        include_fail_closed: bool = True,
    ) -> list[dict[str, Any]]:
        task_operation_preview = dict(chain_preview.get("task_operation_preview") or {})
        events = [
            {
                "type": "agent_runtime_chain_preview",
                "preview": dict(chain_preview.get("agent_runtime_chain_preview") or {}),
                "memory_runtime_view": dict(chain_preview.get("memory_runtime_view") or {}),
                "context_policy_preview": dict(chain_preview.get("context_policy_preview") or {}),
                "legacy_query_chain_removed": True,
            }
        ]
        events.extend(
            self._task_operation_preview_events(
                task_operation_preview,
                fail_closed_message=fail_closed_message,
            )
        )
        if include_fail_closed:
            return events
        return [
            event
            for event in events
            if not (
                event.get("type") == "error"
                and str(event.get("answer_source") or "") == "control_kernel"
            )
        ]

    def _task_operation_preview_events(
        self,
        task_operation_preview: dict[str, Any],
        *,
        fail_closed_message: str,
    ) -> list[dict[str, Any]]:
        control_result = dict(task_operation_preview.get("control_kernel_result") or {})
        ref_payload = _preview_ref_payload(task_operation_preview)
        return [
            {
                "type": "task_operation_preview",
                "preview": task_operation_preview,
            },
            {
                "type": "candidate_set_preview",
                "candidates": list(task_operation_preview.get("candidate_set_preview") or []),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "orchestration_plan_preview",
                "plan": dict(task_operation_preview.get("orchestration_plan_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "plan_validation",
                "validation": dict(task_operation_preview.get("plan_validation") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "execution_graph_preview",
                "graph_preview": dict(task_operation_preview.get("execution_graph_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "adoption_candidate_preview",
                "adoption": dict(task_operation_preview.get("adoption_candidate_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "runtime_directive_candidate_preview",
                "candidates": list(task_operation_preview.get("runtime_directive_candidates") or []),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "commit_gate_preview",
                "commit_gate": dict(task_operation_preview.get("commit_gate_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "orchestration_control",
                "control": control_result,
                "unit_catalog": self.unit_catalog.to_list(),
                "task_operation_preview_ref": ref_payload,
                "legacy_query_chain_removed": True,
            },
            {
                "type": "error",
                "error": str(control_result.get("reason") or "preview_only"),
                "content": fail_closed_message,
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "control_kernel",
            },
        ]

    def _render_active_skill_prompt(self, active_skill: Any | None) -> str | None:
        if active_skill is None:
            return None
        prompt_view = getattr(active_skill, "prompt_view", None)
        if prompt_view is not None and hasattr(prompt_view, "to_prompt"):
            return str(prompt_view.to_prompt())
        return str(active_skill)

    @staticmethod
    def _user_visible_error(exc: Exception) -> str:
        if isinstance(exc, ModelRuntimeError):
            return str(exc)
        return "请求处理失败，运行时已按 fail-closed 策略停止。"


def _preview_ref_payload(preview: dict[str, Any]) -> dict[str, Any]:
    task_contract = dict(preview.get("task_contract") or {})
    resource_policy = dict(preview.get("resource_policy") or {})
    prompt_contract = dict(preview.get("task_prompt_contract") or {})
    topology = dict(preview.get("execution_topology_preview") or {})
    orchestration_plan = dict(preview.get("orchestration_plan_preview") or {})
    plan_validation = dict(preview.get("plan_validation") or {})
    graph_preview = dict(preview.get("execution_graph_preview") or {})
    adoption_candidate = dict(preview.get("adoption_candidate_preview") or {})
    operation_gate = dict(preview.get("operation_gate_preflight") or {})
    executor_preview = dict(preview.get("directive_only_executor_preview") or {})
    commit_gate = dict(preview.get("commit_gate_preview") or {})
    directive_candidates = list(preview.get("runtime_directive_candidates") or [])
    operation_checks = list(operation_gate.get("checks") or [])
    commit_candidates = list(commit_gate.get("commit_candidates") or [])
    understanding_candidates = list(preview.get("understanding_candidate_preview") or [])
    candidate_set = list(preview.get("candidate_set_preview") or [])
    agent_seats = list(preview.get("agent_seat_plan_previews") or [])
    return {
        "task_id": str(task_contract.get("task_id") or ""),
        "resource_policy_ref": str(resource_policy.get("policy_id") or ""),
        "resource_policy_id": str(resource_policy.get("policy_id") or ""),
        "prompt_contract_ref": str(prompt_contract.get("contract_id") or ""),
        "prompt_contract_id": str(prompt_contract.get("contract_id") or ""),
        "execution_topology_mode": str(topology.get("mode") or "single_agent"),
        "orchestration_plan_ref": str(orchestration_plan.get("plan_id") or ""),
        "plan_validation_status": str(plan_validation.get("status") or ""),
        "execution_graph_preview_node_count": len(list(graph_preview.get("node_previews") or [])),
        "adoption_candidate_status": str(adoption_candidate.get("status") or ""),
        "adopted_resource_policy_available": bool(adoption_candidate.get("adopted_resource_policy_available")),
        "runtime_directive_candidate_count": len(directive_candidates),
        "runtime_directive_available": False,
        "operation_gate_passed": bool(operation_gate.get("operation_gate_passed") is True),
        "operation_gate_check_count": len(operation_checks),
        "executor_dispatch_enabled": bool(executor_preview.get("will_dispatch") is True),
        "executor_accepts_only": str(executor_preview.get("accepted_input_type") or ""),
        "commit_gate_status": str(commit_gate.get("status") or ""),
        "commit_allowed": bool(commit_gate.get("commit_allowed") is True),
        "commit_candidate_count": len(commit_candidates),
        "understanding_candidate_count": len(understanding_candidates),
        "candidate_count": len(candidate_set),
        "multi_agent_enabled": False,
        "agent_seat_count": len(agent_seats),
        "runtime_directive_enabled": False,
        "runtime_executable": False,
        "authority": "task_operation_preview",
    }
