from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from evidence import EvidenceOrchestrator, PDFWorker, RetrievalWorker, StructuredDataWorker
from evidence.output_policy import RAGEvidenceOutputPolicy
from observability import build_debug_trace_event, start_turn_trace
from capability_system.tool_authorization import build_tool_authorization_index
from harness import AgentHarness, GraphHarness
from harness.runtime import AgentRuntimeServices, SingleAgentRuntimeHost, TaskExecutorServices, assemble_runtime
from runtime import ModelResponseRuntimeExecutor, ModelRuntimeError, ToolRuntimeExecutor
from runtime.shared.history_assembler import assemble_runtime_history
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.identity import normalize_agent_id
from orchestration import (
    build_base_unit_catalog,
    build_user_message_commit_decision,
)
from project_layout import ProjectLayout
from query.models import QueryRequest
from query.system_routes import run_direct_system_route
from harness.runtime import AgentRunRequest
from harness.loop.active_work import (
    ActiveWorkContext,
    ActiveWorkTurnDecision,
    active_work_status_reply,
    build_active_work_context,
    decide_active_work_turn,
    default_reply_for_action,
    public_active_work_text,
)
from harness.loop.presentation import final_answer_event
from harness.loop.task_executor import (
    append_user_work_instruction,
    execute_task_run,
    is_task_run_executable,
    is_task_run_executor_claimed,
    recover_interrupted_task_executors,
    request_task_run_pause,
    resume_paused_task_run,
    stop_task_run,
)
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from harness.graph.models import safe_id
from runtime.shared.models import AgentRun, TaskRun

logger = logging.getLogger(__name__)


class QueryRuntime:
    """Thin API adapter for the agent runtime chain.

    The old query layer used to own planning, tool routing, worker orchestration,
    follow-up execution, context restore, and writeback. Those responsibilities
    are intentionally gone from this class. QueryRuntime now only accepts API
    input, emits stream events, and calls the admitted agent harness.
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
    ) -> None:
        self.base_dir = base_dir
        self.settings_service = settings_service
        self.session_manager = session_manager
        self.memory_facade = memory_facade
        self.model_runtime = model_runtime
        self.tool_runtime = tool_runtime
        self.skill_registry = skill_registry
        self.unit_catalog = build_base_unit_catalog()
        self.tool_invocation_validation_mode = "enforce"
        self.model_response_executor = ModelResponseRuntimeExecutor(
            model_runtime=model_runtime,
            tool_definition_resolver=self._get_tool_definition,
        )
        self.tool_runtime_executor = ToolRuntimeExecutor(tool_runtime=tool_runtime) if tool_runtime is not None else None
        self.agent_runtime_registry = AgentRuntimeRegistry(base_dir)
        retrieval_enabled = callable(getattr(retrieval_service, "retrieve", None))
        self.evidence_orchestrator = (
            EvidenceOrchestrator(
                retrieval_worker=RetrievalWorker(retrieval_service=retrieval_service),
                pdf_worker=PDFWorker(root_dir=base_dir),
                structured_data_worker=StructuredDataWorker(root_dir=base_dir),
                output_policy=RAGEvidenceOutputPolicy(model_runtime=model_runtime),
            )
            if retrieval_enabled
            else None
        )
        self.single_agent_runtime_host = SingleAgentRuntimeHost(
            ProjectLayout.from_backend_dir(base_dir).runtime_state_dir,
            backend_dir=base_dir,
            permission_mode_provider=_permission_mode_provider(
                permission_service=permission_service,
                settings_service=settings_service,
            ),
            tool_authorization_index=build_tool_authorization_index(
                list(getattr(tool_runtime, "definitions", []) or [])
            ),
        )
        attach_prompt_accounting = getattr(self.model_runtime, "attach_prompt_accounting_ledger", None)
        if callable(attach_prompt_accounting):
            attach_prompt_accounting(self.single_agent_runtime_host.prompt_accounting_ledger)
        self.agent_harness = AgentHarness(
            services=AgentRuntimeServices.from_runtime_host(
                self.single_agent_runtime_host,
                execute_task_run_callback=self.execute_task_run,
                execute_graph_agent_work_order_callback=self.execute_graph_agent_work_order,
                model_runtime=self.model_runtime,
                tool_runtime_executor=self.tool_runtime_executor,
                tool_instances=tuple(self._all_tool_instances()),
                agent_runtime_profile_resolver=self.agent_runtime_registry.get_profile,
            )
        )
        self.graph_harness = GraphHarness(
            services=AgentRuntimeServices.from_runtime_host(
                self.single_agent_runtime_host,
                execute_task_run_callback=self.execute_task_run,
                execute_graph_agent_work_order_callback=self.execute_graph_agent_work_order,
                model_runtime=self.model_runtime,
                tool_runtime_executor=self.tool_runtime_executor,
                tool_instances=tuple(self._all_tool_instances()),
                agent_runtime_profile_resolver=self.agent_runtime_registry.get_profile,
            ),
            agent_harness=self.agent_harness,
        )
        self.task_executor_recovery = recover_interrupted_task_executors(self.single_agent_runtime_host)
        self.runtime_components = {
            "query_runtime": "adapter_only",
            "agent_harness": "active",
            "graph_harness": "active",
            "evidence_orchestrator": "active" if retrieval_enabled else "disabled_missing_retrieval_service",
            "task_executor_recovery": self.task_executor_recovery,
        }

    def build_system_prompt_for_session(
        self,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ) -> str:
        _ = (session_id, history, pending_user_message, memory_intent, relevant_memory_notes, retrieval_results)
        return self.build_static_system_prompt_for_session()

    async def abuild_system_prompt_for_session(self, *args, **kwargs) -> str:
        return self.build_system_prompt_for_session(*args, **kwargs)

    def build_static_system_prompt_for_session(self, *args, **kwargs) -> str:
        _ = (args, kwargs)
        return "当前单 agent harness prompt 由每次 RuntimeInvocationPacket 装配；请查看 latest_prompt_manifest_summary。"

    async def astream(self, request: QueryRequest):
        history_record = self.session_manager.load_session_record(request.session_id)
        raw_history = request.history or self.session_manager.load_session_for_agent(
            request.session_id,
            include_compressed_context=False,
        )
        history_assembly = assemble_runtime_history(
            history=raw_history,
            compressed_context=str(history_record.get("compressed_context") or ""),
        )
        history = [dict(item) for item in history_assembly.model_history]
        turn_index = len(history_record.get("messages", [])) + 1
        turn_id = f"turn:{request.session_id}:{turn_index}"
        try:
            input_commit_gate = self._commit_user_message(
                session_id=request.session_id,
                content=request.message,
                turn_id=turn_id,
            )
            with start_turn_trace(
                session_id=request.session_id,
                user_message=request.message,
                history_length=len(history),
                metadata={
                    "request_kind": "chat",
                    "query_runtime_role": "adapter_only",
                    "history_assembly": dict(history_assembly.diagnostics),
                },
                tags=["query-runtime", "agent-runtime-chain"],
            ) as trace:
                debug_event = build_debug_trace_event(trace)
                if debug_event is not None:
                    yield debug_event
                yield {
                    "type": "input_commit_gate",
                    "commit_gate": input_commit_gate.to_dict(),
                }
                direct_system_route_event = await run_direct_system_route(
                    base_dir=self.base_dir,
                    request=request,
                    turn_id=turn_id,
                    assistant_message_committer=lambda payload: self._apply_assistant_message_commit_async(
                        request.session_id,
                        payload,
                    ),
                )
                if direct_system_route_event is not None:
                    yield direct_system_route_event
                    return

                active_work_event = await self._handle_active_work_turn(
                    request=request,
                    turn_id=turn_id,
                )
                if active_work_event is not None:
                    yield active_work_event
                    return

                agent_runtime_profile = self.agent_runtime_registry.get_profile("agent:0")
                runtime_task_selection = _task_selection_for_runtime(
                    request_task_selection=dict(request.task_selection or {}),
                    turn_id=turn_id,
                    runtime_mode=request.runtime_mode,
                    soul_id=request.soul_id,
                    runtime_profile=dict(request.runtime_profile or {}),
                )
                agent_invocation_id = f"aginvoke:{turn_id}:main"
                tool_instances = self._all_tool_instances()
                runtime_assembly = assemble_runtime(
                    backend_dir=self.base_dir,
                    session_id=request.session_id,
                    turn_id=turn_id,
                    agent_invocation_id=agent_invocation_id,
                    request_task_selection=runtime_task_selection,
                    model_selection=dict(request.model_selection or {}),
                    agent_runtime_profile=agent_runtime_profile,
                    tool_instances=tool_instances,
                    definitions_by_name=dict(self.single_agent_runtime_host.tool_authorization_index.definitions_by_name or {}),
                )
                yield {
                    "type": "runtime_assembly_compiled",
                    "runtime_assembly": runtime_assembly.to_dict(),
                }
                async for event in self.agent_harness.run_stream(
                    AgentRunRequest(
                        session_id=request.session_id,
                        turn_id=turn_id,
                        user_message=request.message,
                        history=history,
                        source="query_runtime.adapter",
                        model_response_executor=self.model_response_executor,
                        task_selection=runtime_task_selection,
                        assistant_message_committer=lambda payload: self._apply_assistant_message_commit_async(
                            request.session_id,
                            {**dict(payload or {}), "turn_id": turn_id},
                        ),
                        tool_runtime_executor=self.tool_runtime_executor,
                        tool_instances=tool_instances,
                        agent_runtime_profile=agent_runtime_profile,
                        search_policy=list(request.search_policy) if request.search_policy is not None else None,
                        model_selection=dict(request.model_selection or {}),
                        agent_invocation={"agent_invocation_id": agent_invocation_id},
                        runtime_assembly=runtime_assembly,
                    )
                ):
                    if event.get("type") == "agent_turn_terminal":
                        terminal_payload = dict(dict(event.get("event") or {}).get("payload") or {})
                        marker = getattr(trace, "mark_terminal", None)
                        if callable(marker):
                            marker(
                                status=str(terminal_payload.get("status") or ""),
                                reason=str(terminal_payload.get("terminal_reason") or ""),
                            )
                    yield event
        except Exception as exc:
            logger.exception("QueryRuntime failed while streaming request.")
            failure_text = self._user_visible_error(exc)
            error_payload = {"type": "error", "error": failure_text}
            if isinstance(exc, ModelRuntimeError):
                error_payload["code"] = exc.code
            yield error_payload

    async def _handle_active_work_turn(self, *, request: QueryRequest, turn_id: str) -> dict[str, Any] | None:
        context = build_active_work_context(
            self.single_agent_runtime_host,
            session_id=request.session_id,
        )
        if context is None:
            return None
        decision = await decide_active_work_turn(
            model_runtime=self.model_runtime,
            user_message=request.message,
            active_work_context=context,
            model_selection=dict(request.model_selection or {}),
        )
        if decision.action in {"start_new_work", "normal_response"}:
            return None
        content = await self._apply_active_work_turn_decision(
            decision=decision,
            context=context,
            turn_id=turn_id,
            user_message=request.message,
        )
        await self._apply_assistant_message_commit_async(
            request.session_id,
            {
                "role": "assistant",
                "content": content,
                "turn_id": turn_id,
                "answer_channel": "active_work_control",
                "answer_source": "harness.loop.active_work_turn",
                "answer_canonical_state": "final",
                "answer_persist_policy": "persist_canonical",
                "answer_finalization_policy": "assistant_final",
            },
        )
        return final_answer_event(
            content=content,
            answer_source="harness.loop.active_work_turn",
            terminal_reason=decision.action,
            extra={
                "active_work": {
                    "action": decision.action,
                    "status": context.status,
                    "control_state": context.control_state,
                }
            },
        )

    async def _apply_active_work_turn_decision(
        self,
        *,
        decision: ActiveWorkTurnDecision,
        context: ActiveWorkContext,
        turn_id: str,
        user_message: str,
    ) -> str:
        host = self.single_agent_runtime_host
        action = decision.action
        response = public_active_work_text(decision.response) or default_reply_for_action(action, context)
        if action == "continue_active_work":
            if context.resumable:
                result = resume_paused_task_run(host, context.task_run_id, reason="conversation_continue", requested_by="user")
                if result.get("ok"):
                    self._schedule_active_task_run_executor(context.task_run_id, scheduler="conversation_continue")
                else:
                    response = active_work_status_reply(build_active_work_context(host, session_id=context.session_id) or context)
            elif context.running:
                response = response or "我正在接着处理，新的进展会继续更新在这里。"
            else:
                response = active_work_status_reply(build_active_work_context(host, session_id=context.session_id) or context)
        elif action == "pause_active_work":
            result = request_task_run_pause(host, context.task_run_id, reason="conversation_pause", requested_by="user")
            if not result.get("ok"):
                response = active_work_status_reply(build_active_work_context(host, session_id=context.session_id) or context)
        elif action == "stop_active_work":
            result = stop_task_run(host, context.task_run_id, reason="conversation_stop", requested_by="user")
            if not result.get("ok"):
                response = active_work_status_reply(build_active_work_context(host, session_id=context.session_id) or context)
        elif action == "append_instruction_to_active_work":
            instruction = decision.appended_instruction or str(user_message or "").strip()
            result = append_user_work_instruction(
                host,
                context.task_run_id,
                content=instruction,
                turn_id=turn_id,
                intent="append_instruction_to_active_work",
            )
            if result.get("ok") and context.resumable:
                resume_result = resume_paused_task_run(host, context.task_run_id, reason="conversation_instruction", requested_by="user")
                if resume_result.get("ok"):
                    self._schedule_active_task_run_executor(context.task_run_id, scheduler="conversation_instruction")
            if not result.get("ok"):
                response = active_work_status_reply(build_active_work_context(host, session_id=context.session_id) or context)
        elif action == "answer_about_active_work":
            response = decision.response or active_work_status_reply(build_active_work_context(host, session_id=context.session_id) or context)
        elif action == "ask_user":
            response = decision.response or default_reply_for_action(action, context)
        return public_active_work_text(response)

    def _schedule_active_task_run_executor(self, task_run_id: str, *, scheduler: str, max_steps: int = 12) -> dict[str, Any]:
        runtime_host = self.single_agent_runtime_host
        task_run = runtime_host.state_index.get_task_run(task_run_id)
        if task_run is None:
            return {"ok": False, "scheduled": False, "reason": "task_run_not_found"}
        if is_task_run_executor_claimed(task_run):
            return {"ok": True, "scheduled": False, "reason": "already_running"}
        if not is_task_run_executable(task_run):
            return {"ok": False, "scheduled": False, "reason": f"not_executable:{getattr(task_run, 'status', '')}"}
        scheduled_event = runtime_host.event_log.append(
            task_run_id,
            "task_run_executor_scheduled",
            payload={"task_run_id": task_run_id, "max_steps": max_steps, "scheduler": scheduler},
            refs={"task_run_ref": task_run_id},
        )
        runtime_host.state_index.upsert_task_run(
            replace(
                task_run,
                status="running",
                updated_at=scheduled_event.created_at or time.time(),
                latest_event_offset=scheduled_event.offset,
                terminal_reason="",
                diagnostics={
                    **dict(task_run.diagnostics or {}),
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
                    result = await self.execute_task_run(task_run_id, max_steps=max_steps)
                    payload = dict(result or {}) if isinstance(result, dict) else {}
                    if not _task_executor_should_auto_continue(runtime_host, task_run_id=task_run_id, result=payload):
                        return
                    runtime_host.event_log.append(
                        task_run_id,
                        "task_run_executor_rescheduled",
                        payload={"task_run_id": task_run_id, "reason": str(payload.get("error") or "waiting_executor"), "scheduler": scheduler},
                        refs={"task_run_ref": task_run_id},
                    )
                    await asyncio.sleep(0)
            except Exception as exc:
                _mark_query_scheduled_task_failed(runtime_host, task_run_id=task_run_id, error=str(exc) or exc.__class__.__name__)

        asyncio.create_task(_runner())
        return {"ok": True, "scheduled": True, "task_run_id": task_run_id}

    async def generate_title(self, first_user_message: str) -> str:
        return await self.model_runtime.generate_title(first_user_message)

    async def execute_task_run(self, task_run_id: str, *, max_steps: int = 12) -> dict[str, Any]:
        return await execute_task_run(self._task_executor_services(), task_run_id, max_steps=max_steps)

    async def execute_graph_agent_work_order(self, *, graph_config: Any, work_order: Any, max_steps: int = 12) -> dict[str, Any]:
        task_run = self._create_graph_node_task_run(graph_config=graph_config, work_order=work_order)
        return await execute_task_run(
            self._task_executor_services_for_task_run(task_run),
            task_run.task_run_id,
            max_steps=max(1, int(max_steps or 12)),
        )

    def _task_executor_services(self, *, agent_id: str = "agent:0") -> TaskExecutorServices:
        profile = self.agent_runtime_registry.get_profile(agent_id) or self.agent_runtime_registry.get_profile("agent:0")
        if profile is None:
            raise ValueError("AgentRuntimeProfile not found: agent:0")
        return self._task_executor_services_with_profile(profile)

    def _task_executor_services_for_task_run(self, task_run: TaskRun) -> TaskExecutorServices:
        return self._task_executor_services_with_profile(self._resolve_task_run_runtime_profile(task_run))

    def _resolve_task_run_runtime_profile(self, task_run: TaskRun) -> Any:
        explicit_profile_id = str(getattr(task_run, "agent_profile_id", "") or "").strip()
        profile = None
        if explicit_profile_id:
            profile = self.agent_runtime_registry.get_profile_by_profile_id(explicit_profile_id)
            if profile is None:
                raise ValueError(f"AgentRuntimeProfile not found: {explicit_profile_id}")
        if profile is None:
            profile = self.agent_runtime_registry.get_profile(getattr(task_run, "agent_id", "") or "agent:0")
        if profile is None:
            profile = self.agent_runtime_registry.get_profile("agent:0")
        if profile is None:
            raise ValueError("AgentRuntimeProfile not found: agent:0")
        return profile

    def _task_executor_services_with_profile(self, profile: Any) -> TaskExecutorServices:
        return TaskExecutorServices(
            runtime_host=self.single_agent_runtime_host,
            backend_dir=self.base_dir,
            model_runtime=self.model_runtime,
            tool_runtime_executor=self.tool_runtime_executor,
            tool_instances=tuple(self._all_tool_instances()),
            agent_runtime_profile=profile,
            backend_config=dict(getattr(self, "config", {}) or {}),
            assistant_message_committer=lambda payload: self._apply_assistant_message_commit(
                str(dict(payload or {}).get("session_id") or ""),
                payload,
            ),
        )

    def _create_graph_node_task_run(self, *, graph_config: Any, work_order: Any) -> TaskRun:
        runtime_host = self.single_agent_runtime_host
        now = time.time()
        node_task_run_id = f"gtask:{safe_id(work_order.graph_run_id)}:{safe_id(work_order.node_id)}:{safe_id(work_order.work_order_id)}"
        existing = runtime_host.state_index.get_task_run(node_task_run_id)
        if existing is not None:
            _validate_existing_graph_node_task_run(existing, graph_run_id=work_order.graph_run_id, work_order_id=work_order.work_order_id)
            return existing
        origin = _graph_node_origin(work_order)
        contract = _graph_node_contract_from_work_order(work_order)
        runtime_selection = _graph_node_task_selection(graph_config, work_order)
        node_agent_id = _graph_node_agent_id(graph_config, work_order)
        node_profile = self._resolve_graph_node_profile(node_agent_id=node_agent_id, work_order=work_order, graph_config=graph_config)
        node_profile_id = str(getattr(node_profile, "agent_profile_id", "") or "")
        contract_ref = runtime_host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
        lifecycle = TaskLifecycleRecord(
            task_run_id=node_task_run_id,
            contract_ref=contract_ref,
            status="waiting_executor",
            created_at=now,
            updated_at=now,
        )
        runtime_host.runtime_objects.put_object("task_lifecycle", node_task_run_id, lifecycle.to_dict())
        graph_run = runtime_host.runtime_objects.get_object(f"rtobj:graph_run:{safe_id(work_order.graph_run_id)}")
        task_run = TaskRun(
            task_run_id=node_task_run_id,
            session_id=str(dict(graph_run or {}).get("session_id") or work_order.graph_run_id),
            task_id=work_order.task_ref,
            task_contract_ref=contract_ref,
            owner_agent_seat_id=work_order.node_id,
            agent_id=node_agent_id,
            agent_profile_id=node_profile_id,
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=now,
            updated_at=now,
            diagnostics={
                "source": "query_runtime.graph_agent_work_order_adapter",
                "origin": origin,
                **origin,
                "graph_run_id": work_order.graph_run_id,
                "graph_harness_config_id": graph_config.config_id,
                "graph_node_id": work_order.node_id,
                "graph_work_order_id": work_order.work_order_id,
                "runtime_scope": _graph_node_runtime_scope(work_order),
                **_graph_node_public_scope_fields(work_order),
                "runtime_task_selection": runtime_selection,
                "contract": contract.to_dict(),
            },
        )
        agent_run = AgentRun(
            agent_run_id=f"agrun:{node_task_run_id}:main",
            task_run_id=node_task_run_id,
            agent_id=task_run.agent_id,
            agent_profile_id=task_run.agent_profile_id,
            role="graph_node_executor",
            spawn_mode="graph_node",
            context_scope="graph_node_work_order",
            execution_runtime_kind="single_agent_task",
            parent_agent_run_ref=work_order.graph_run_id,
            status="waiting_executor",
            created_at=now,
            updated_at=now,
            diagnostics={
                "origin": origin,
                **origin,
                "graph_run_id": work_order.graph_run_id,
                "graph_node_id": work_order.node_id,
                "graph_work_order_id": work_order.work_order_id,
            },
        )
        runtime_host.state_index.upsert_task_run(task_run)
        runtime_host.state_index.upsert_agent_run(agent_run)
        event = runtime_host.event_log.append(
            work_order.task_run_id,
            "graph_node_agent_task_run_created",
            payload={
                "graph_run_id": work_order.graph_run_id,
                "node_id": work_order.node_id,
                "work_order_id": work_order.work_order_id,
                "node_executor_task_run": task_run.to_dict(),
                "node_executor_agent_run": agent_run.to_dict(),
            },
            refs={
                "graph_run_ref": work_order.graph_run_id,
                "work_order_ref": work_order.work_order_id,
                "node_executor_task_run_ref": task_run.task_run_id,
            },
        )
        runtime_host.state_index.upsert_task_run(
            TaskRun(
                **{
                    **task_run.to_dict(),
                    "updated_at": event.created_at,
                    "latest_event_offset": event.offset,
                }
            )
        )
        return runtime_host.state_index.get_task_run(node_task_run_id) or task_run

    def _resolve_graph_node_profile(self, *, node_agent_id: str, work_order: Any, graph_config: Any) -> Any:
        explicit_profile_id = str(getattr(work_order, "agent_profile_id", "") or "").strip()
        if explicit_profile_id:
            profile = self.agent_runtime_registry.get_profile_by_profile_id(explicit_profile_id)
            if profile is None:
                raise ValueError(f"AgentRuntimeProfile not found: {explicit_profile_id}")
            if normalize_agent_id(str(getattr(profile, "agent_id", "") or "")) != normalize_agent_id(node_agent_id):
                raise ValueError("Graph node agent_profile_id does not belong to node agent_id")
            return profile
        coordinator_profile_id = _graph_coordinator_profile_ref(graph_config)
        if coordinator_profile_id:
            profile = self.agent_runtime_registry.get_profile_by_profile_id(coordinator_profile_id)
            if profile is not None and normalize_agent_id(str(getattr(profile, "agent_id", "") or "")) == normalize_agent_id(node_agent_id):
                return profile
        profile = self.agent_runtime_registry.get_profile(node_agent_id)
        if profile is None:
            profile = self.agent_runtime_registry.get_profile("agent:0")
        if profile is None:
            raise ValueError(f"AgentRuntimeProfile not found for agent_id: {node_agent_id}")
        return profile

    def _commit_user_message(self, *, session_id: str, content: str, turn_id: str):
        decision = build_user_message_commit_decision(
            session_id=session_id,
            content=content,
            task_id=turn_id,
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
                    "image": payload.get("image"),
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
        main_context = dict(payload.get("main_context") or {})
        task_summary_refs = [
            dict(item)
            for item in list(payload.get("task_summary_refs") or [])
            if isinstance(item, dict)
        ]
        bundle_summary_refs = [
            dict(item)
            for item in list(payload.get("bundle_summary_refs") or [])
            if isinstance(item, dict)
        ]
        self._write_runtime_state_projection(
            session_id=session_id,
            main_context=main_context,
            task_summary_refs=task_summary_refs,
            bundle_summary_refs=bundle_summary_refs,
        )
        receipt = self.memory_facade.enqueue_memory_maintenance_after_commit(
            session_id=session_id,
            messages=history,
            turn_id=str(payload.get("turn_id") or ""),
            main_context=main_context,
            task_summary_refs=task_summary_refs,
            bundle_summary_refs=bundle_summary_refs,
        )
        return {
            "appended_messages": appended,
            **self._memory_receipt_commit_payload(receipt),
            "file_work_context_writeback": bool(main_context or task_summary_refs or bundle_summary_refs),
        }

    async def _apply_assistant_message_commit_async(self, session_id: str, payload: dict[str, Any]):
        return self._apply_assistant_message_commit(session_id, payload)

    def _write_runtime_state_projection(
        self,
        *,
        session_id: str,
        main_context: dict[str, Any],
        task_summary_refs: list[dict[str, Any]],
        bundle_summary_refs: list[dict[str, Any]],
    ) -> None:
        if not (main_context or task_summary_refs or bundle_summary_refs):
            return
        updater = getattr(getattr(self.memory_facade, "session_memory", None), "update_runtime_state_from_context_state", None)
        if not callable(updater):
            return
        updater(
            session_id,
            main_context,
            task_summaries=task_summary_refs,
            bundle_summaries=bundle_summary_refs,
            corrections=[],
        )

    def _memory_receipt_commit_payload(self, receipt: Any) -> dict[str, Any]:
        payload = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt or {})
        session_succeeded = bool(payload.get("session_memory_succeeded") is True)
        durable_succeeded = bool(payload.get("durable_memory_succeeded") is True)
        durable_write_count = int(payload.get("durable_write_count") or 0)
        attempted = bool(payload.get("attempted") is True)
        failed = str(payload.get("status") or "") == "failed"
        session_memory_chars = 0
        try:
            session_memory_chars = len(self.memory_facade.session_memory.manager(str(payload.get("session_id") or "")).load() or "") if session_succeeded else 0
        except Exception:
            session_memory_chars = 0
        return {
            "memory_maintenance_attempted": attempted,
            "memory_maintenance_status": str(payload.get("status") or ""),
            "memory_maintenance_receipt": payload,
            "memory_maintenance_error": str(payload.get("error") or ""),
            "session_memory_succeeded": session_succeeded,
            "durable_memory_succeeded": durable_succeeded,
            "durable_write_count": durable_write_count,
            "session_memory_chars": session_memory_chars,
            "durable_saved_count": durable_write_count,
            "durable_memory_commit_attempted": attempted,
            "durable_memory_commit_failed": failed,
        }

    def _all_tool_instances(self) -> list[Any]:
        if self.tool_runtime is None:
            return []
        return list(self.tool_runtime.instances)

    def _get_tool_definition(self, name: str | None):
        if self.tool_runtime is None:
            return None
        getter = getattr(self.tool_runtime, "get_definition", None)
        if not callable(getter):
            return None
        return getter(name)

    @staticmethod
    def _user_visible_error(exc: Exception) -> str:
        if isinstance(exc, ModelRuntimeError):
            return str(exc)
        return "请求处理失败，运行时已按 fail-closed 策略停止。"


def _task_executor_should_auto_continue(runtime_host: Any, *, task_run_id: str, result: dict[str, Any]) -> bool:
    if str(result.get("error") or "") != "task_execution_step_budget_exhausted":
        return False
    if not bool(result.get("retryable")):
        return False
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = diagnostics.get("runtime_control")
    control_state = str(dict(control or {}).get("state") or "") if isinstance(control, dict) else ""
    return str(getattr(task_run, "status", "") or "") == "waiting_executor" and control_state not in {"pause_requested", "paused", "stop_requested", "stopped"}


def _mark_query_scheduled_task_failed(runtime_host: Any, *, task_run_id: str, error: str) -> None:
    event = runtime_host.event_log.append(
        task_run_id,
        "task_run_executor_schedule_failed",
        payload={"task_run_id": task_run_id, "error": error, "scheduler": "conversation"},
        refs={"task_run_ref": task_run_id},
    )
    current = runtime_host.state_index.get_task_run(task_run_id)
    if current is None:
        return
    runtime_host.state_index.upsert_task_run(
        replace(
            current,
            status="blocked",
            updated_at=event.created_at,
            latest_event_offset=event.offset,
            terminal_reason="task_executor_schedule_failed",
            diagnostics={
                **dict(current.diagnostics or {}),
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


def _permission_mode_provider(*, permission_service: Any | None, settings_service: Any | None):
    def _current_mode() -> str:
        service_mode = getattr(permission_service, "current_mode", None)
        if callable(service_mode):
            mode = str(service_mode() or "").strip()
            if mode:
                return mode
        settings_mode = getattr(settings_service, "get_permission_mode", None)
        if callable(settings_mode):
            mode = str(settings_mode() or "").strip()
            if mode:
                return mode
        return "default"

    return _current_mode


def _graph_node_contract_from_work_order(work_order: Any) -> TaskRunContract:
    contracts = dict(getattr(work_order, "expected_result_contract", {}) or {})
    input_package = dict(getattr(work_order, "input_package", {}) or {})
    prompt_contract = dict(input_package.get("prompt_contract") or input_package.get("prompt") or {})
    runtime_profile = dict(input_package.get("runtime_profile") or {})
    task_environment_id = str(
        input_package.get("task_environment_id")
        or dict(input_package.get("task_environment") or {}).get("task_environment_id")
        or dict(input_package.get("task_environment") or {}).get("environment_id")
        or ""
    ).strip()
    criteria = [
        "完成当前图节点职责，并输出可被下游节点消费的结果。",
        "如产生文件或记忆候选，需要在输出中列出真实引用。",
    ]
    output_contract_id = str(contracts.get("output_contract_id") or contracts.get("node_contract_id") or "")
    if output_contract_id:
        criteria.append(f"满足输出合同：{output_contract_id}。")
    return TaskRunContract(
        contract_id=f"gcontract:{safe_id(work_order.graph_run_id)}:{safe_id(work_order.node_id)}:{safe_id(work_order.work_order_id)}",
        contract_source="graph_node_work_order",
        user_visible_goal=work_order.message or f"完成图节点 {work_order.node_id}。",
        task_run_goal=work_order.message or f"完成图节点 {work_order.node_id}。",
        completion_criteria=tuple(criteria),
        resource_requirements=_graph_node_resource_requirements(work_order),
        permission_requirements=dict(getattr(work_order, "permission_scope", {}) or {}),
        acceptance_policy=contracts,
        recovery_policy=dict(getattr(work_order, "retry_policy", {}) or {}),
        created_from_packet_ref=work_order.work_order_id,
        task_environment_id=task_environment_id,
        runtime_profile=runtime_profile,
        prompt_contract=prompt_contract,
        origin=_graph_node_origin(work_order),
    )


def _graph_node_resource_requirements(work_order: Any) -> dict[str, Any]:
    return {
        "graph_state": dict(getattr(work_order, "graph_state", {}) or {}),
        "input_package": _model_visible_input_package(dict(getattr(work_order, "input_package", {}) or {})),
        "context_refs": dict(getattr(work_order, "context_refs", {}) or {}),
        "artifact_space_ref": str(getattr(work_order, "artifact_space_ref", "") or ""),
        "memory_space_ref": str(getattr(work_order, "memory_space_ref", "") or ""),
        "file_access_table_refs": list(getattr(work_order, "file_access_table_refs", ()) or ()),
        "artifact_repository_targets": [
            dict(item)
            for item in list(getattr(work_order, "artifact_repository_targets", ()) or ())
            if isinstance(item, dict)
        ],
        "memory_repository_targets": [
            dict(item)
            for item in list(getattr(work_order, "memory_repository_targets", ()) or ())
            if isinstance(item, dict)
        ],
    }


def _model_visible_input_package(input_package: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_id": str(input_package.get("package_id") or ""),
        "authority": str(input_package.get("authority") or "harness.graph_node_input_package"),
        "node_identity": dict(input_package.get("node_identity") or {}),
        "prompt_contract": dict(input_package.get("prompt_contract") or input_package.get("prompt") or {}),
        "task_environment_id": str(input_package.get("task_environment_id") or ""),
        "runtime_scope": dict(input_package.get("runtime_scope") or {}),
        "runtime_profile": _compact_runtime_profile(dict(input_package.get("runtime_profile") or {})),
        "agent_instruction": str(input_package.get("agent_instruction") or ""),
        "input_contract": dict(input_package.get("input_contract") or {}),
        "output_contract": dict(input_package.get("output_contract") or {}),
        "initial_inputs": dict(input_package.get("initial_inputs") or {}),
        "loop_context": dict(input_package.get("loop_context") or {}),
        "inbound_context": [dict(item) for item in list(input_package.get("inbound_context") or []) if isinstance(item, dict)],
        "memory_view": dict(input_package.get("memory_view") or {}),
        "artifact_view": dict(input_package.get("artifact_view") or {}),
        "file_view": dict(input_package.get("file_view") or {}),
        "issue_view": dict(input_package.get("issue_view") or {}),
        "environment_refs": dict(input_package.get("environment_refs") or {}),
        "artifact_space_ref": str(input_package.get("artifact_space_ref") or ""),
        "memory_space_ref": str(input_package.get("memory_space_ref") or ""),
        "file_access_table_refs": [str(item) for item in list(input_package.get("file_access_table_refs") or []) if str(item)],
        "artifact_repository_targets": [
            dict(item) for item in list(input_package.get("artifact_repository_targets") or []) if isinstance(item, dict)
        ],
        "memory_repository_targets": [
            dict(item) for item in list(input_package.get("memory_repository_targets") or []) if isinstance(item, dict)
        ],
        "permission_summary": dict(input_package.get("permission_summary") or {}),
        "tool_capability_table": dict(input_package.get("tool_capability_table") or {}),
        "expected_result_contract": dict(input_package.get("expected_result_contract") or {}),
    }


def _compact_runtime_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": str(profile.get("mode") or ""),
        "runtime_mode": str(profile.get("runtime_mode") or profile.get("mode") or ""),
        "task_environment_id": str(profile.get("task_environment_id") or ""),
        "runtime_mode_policy": dict(profile.get("runtime_mode_policy") or profile.get("mode_policy") or {}),
    }


def _graph_node_task_selection(graph_config: Any, work_order: Any) -> dict[str, Any]:
    mode = _graph_node_runtime_mode(graph_config, work_order)
    input_package = dict(getattr(work_order, "input_package", {}) or {})
    package_profile = dict(input_package.get("runtime_profile") or {})
    task_environment_id = str(
        getattr(graph_config, "task_environment_id", "")
        or input_package.get("task_environment_id")
        or dict(input_package.get("task_environment") or {}).get("environment_id")
        or ""
    )
    runtime_profile = {
        **package_profile,
        "mode": mode,
        "runtime_mode": mode,
        "task_environment_id": task_environment_id,
        "tool_policy": dict(getattr(work_order, "tool_scope", {}) or getattr(graph_config, "tools", {}) or {}),
        "permission_policy": dict(getattr(work_order, "permission_scope", {}) or getattr(graph_config, "permissions", {}) or {}),
        "runtime_mode_policy": {
            **dict(package_profile.get("runtime_mode_policy") or package_profile.get("mode_policy") or {}),
            "source": "graph_node_work_order",
            "graph_run_id": work_order.graph_run_id,
            "node_id": work_order.node_id,
        },
    }
    return {
        "selected_task_id": work_order.task_ref,
        "task_environment_id": task_environment_id,
        "runtime_mode": mode,
        "runtime_profile": runtime_profile,
        "prompt_contract": dict(input_package.get("prompt_contract") or input_package.get("prompt") or {}),
        "allowed_operations": list(dict(getattr(work_order, "tool_scope", {}) or {}).get("allowed_operations") or []),
    }


def _graph_node_runtime_mode(graph_config: Any, work_order: Any) -> str:
    input_package = dict(getattr(work_order, "input_package", {}) or {})
    prompt = dict(input_package.get("prompt") or {})
    candidates = [
        dict(getattr(work_order, "dispatch_context", {}) or {}).get("runtime_mode"),
        dict(input_package.get("runtime_profile") or {}).get("mode"),
        dict(input_package.get("metadata") or {}).get("runtime_mode"),
        prompt.get("runtime_mode"),
        dict(getattr(graph_config, "agents", {}) or {}).get("runtime_mode"),
    ]
    for value in candidates:
        mode = str(value or "").strip().lower()
        if mode in {"role", "standard", "professional", "custom"}:
            return mode
    return "professional"


def _graph_coordinator_profile_ref(graph_config: Any) -> str:
    return str(dict(getattr(graph_config, "agents", {}) or {}).get("coordinator_agent_profile_id") or "task_graph_node_executor")


def _graph_node_agent_id(graph_config: Any, work_order: Any) -> str:
    raw = str(
        getattr(work_order, "agent_id", "")
        or dict(getattr(graph_config, "agents", {}) or {}).get("coordinator_agent_id")
        or "agent:0"
    ).strip()
    normalized = normalize_agent_id(raw)
    return normalized if normalized.startswith("agent:") else "agent:0"


def _graph_node_origin(work_order: Any) -> dict[str, str]:
    return {
        "origin_kind": "graph_node_assigned",
        "origin_authority": "harness.graph_loop",
        "origin_ref": str(getattr(work_order, "work_order_id", "") or ""),
        "parent_run_ref": str(getattr(work_order, "graph_run_id", "") or ""),
        "graph_run_id": str(getattr(work_order, "graph_run_id", "") or ""),
        "node_id": str(getattr(work_order, "node_id", "") or ""),
    }


def _graph_node_runtime_scope(work_order: Any) -> dict[str, Any]:
    graph_state = dict(getattr(work_order, "graph_state", {}) or {})
    input_package = dict(getattr(work_order, "input_package", {}) or {})
    dispatch_context = dict(getattr(work_order, "dispatch_context", {}) or {})
    return {
        **dict(graph_state.get("runtime_scope") or {}),
        **dict(input_package.get("runtime_scope") or {}),
        **dict(dispatch_context.get("runtime_scope") or {}),
        "graph_run_id": str(getattr(work_order, "graph_run_id", "") or ""),
        "task_run_id": str(getattr(work_order, "task_run_id", "") or ""),
        "authority": "query_runtime.graph_node_runtime_scope",
    }


def _graph_node_public_scope_fields(work_order: Any) -> dict[str, str]:
    runtime_scope = _graph_node_runtime_scope(work_order)
    result: dict[str, str] = {}
    for key in ("project_id", "scope_id"):
        value = str(runtime_scope.get(key) or "").strip()
        if value:
            result[key] = value
    return result


def _validate_existing_graph_node_task_run(task_run: TaskRun, *, graph_run_id: str, work_order_id: str) -> None:
    diagnostics = dict(task_run.diagnostics or {})
    if str(diagnostics.get("origin_kind") or "") != "graph_node_assigned":
        raise ValueError("Existing graph node TaskRun origin_kind mismatch")
    if str(diagnostics.get("graph_run_id") or "") != str(graph_run_id or ""):
        raise ValueError("Existing graph node TaskRun graph_run_id mismatch")
    if str(diagnostics.get("graph_work_order_id") or "") != str(work_order_id or ""):
        raise ValueError("Existing graph node TaskRun work_order_id mismatch")


def _task_selection_for_runtime(
    *,
    request_task_selection: dict[str, Any],
    turn_id: str,
    runtime_mode: str = "",
    soul_id: str = "",
    runtime_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_payload = {
        **dict(request_task_selection.get("runtime_profile") or {}),
        **dict(runtime_profile or {}),
    }
    mode = str(runtime_mode or request_task_selection.get("runtime_mode") or request_task_selection.get("mode") or "").strip()
    if mode:
        profile_payload["mode"] = mode
    requested_soul_id = str(soul_id or request_task_selection.get("soul_id") or profile_payload.get("soul_id") or "").strip()
    if requested_soul_id:
        profile_payload["soul_id"] = requested_soul_id
    return {
        **dict(request_task_selection or {}),
        "turn_id": turn_id,
        **({"runtime_mode": mode} if mode else {}),
        **({"soul_id": requested_soul_id} if requested_soul_id else {}),
        **({"runtime_profile": profile_payload} if profile_payload else {}),
    }



