from __future__ import annotations

from dataclasses import replace
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from evidence import EvidenceOrchestrator, PDFWorker, RetrievalWorker, StructuredDataWorker
from evidence.output_policy import RAGEvidenceOutputPolicy
from observability import build_debug_trace_event, start_turn_trace
from capability_system.tools.authorization import build_tool_authorization_index
from harness import GraphHarness
from harness.runtime import AgentRuntimeServices, SingleAgentRuntimeHost, TaskExecutorServices, assemble_runtime
from harness.runtime.request_facts import build_turn_input_facts
from harness.runtime.public_progress import public_runtime_progress_summary
from runtime import ModelResponseRuntimeExecutor, ModelRuntimeError, ToolRuntimeExecutor
from runtime.context_management.session_compaction import auto_compact_session_if_needed, compact_session_history
from runtime.output_boundary import canonical_output_decision_for_final_text
from runtime.shared.history_assembler import assemble_runtime_history
from permissions.policy import normalize_permission_mode
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.identity import normalize_agent_id
from harness.task_contract_normalization import contract_dict_tuple, contract_string_tuple
from orchestration import (
    build_base_unit_catalog,
    build_user_message_commit_decision,
)
from project_layout import ProjectLayout
from harness.entrypoint.models import HarnessRuntimeRequest
from api.chat_direct_routes import run_direct_system_route
from harness.loop.active_work import (
    ActiveWorkContext,
    ActiveWorkTurnDecision,
    active_work_control_denial_observation,
    active_work_turn_decision_from_payload,
    active_work_status_reply,
    default_reply_for_action,
    public_active_work_text,
)
from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.presentation import error_event, final_answer_event
from harness.loop.single_agent_turn import run_single_agent_turn
from harness.loop.task_executor import (
    append_user_work_instruction,
    execute_task_run,
    request_task_run_pause,
    resume_paused_task_run,
    stop_task_run,
)
from harness.loop.task_executor_controller import TaskExecutorController
from harness.loop.task_lifecycle import (
    TaskLifecycleRecord,
    TaskRunContract,
    current_session_task_run,
    start_task_lifecycle_from_action_request,
    start_task_lifecycle_from_contract,
)
from harness.graph.models import safe_id
from harness.graph.work_order_contract import (
    _graph_coordinator_profile_ref,
    _graph_node_agent_id,
    _graph_node_clock_seq,
    _graph_node_contract_from_work_order,
    _graph_node_origin,
    _graph_node_public_scope_fields,
    _graph_node_runtime_contract,
    _graph_node_runtime_scope,
    _graph_node_task_run_id,
    _validate_existing_graph_node_task_run,
)
from runtime.shared.models import AgentRun, TaskRun
from memory_system.runtime_context_provider import RuntimeMemoryContextProvider, should_inject_session_emphasis

logger = logging.getLogger(__name__)

_CONVERSATION_TASK_EXECUTION_STEPS = 50


class HarnessRuntimeFacade:
    """Thin API adapter for the agent runtime chain.

    The old query layer used to own planning, tool routing, worker orchestration,
    follow-up execution, context restore, and writeback. Those responsibilities
    are intentionally gone from this class. HarnessRuntimeFacade now only accepts API
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
        self.runtime_memory_context_provider = RuntimeMemoryContextProvider(
            bundle_service_getter=lambda: getattr(getattr(self, "memory_facade", None), "bundle_service", None),
            session_record_loader=lambda session_id: self.session_manager.load_session_record(session_id),
            recent_messages_loader=self._load_recent_api_messages_for_memory,
            logger=logger,
        )
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
            session_scope_resolver=self._session_scope_for_monitor,
            session_manager=session_manager,
            tool_authorization_index=build_tool_authorization_index(
                list(getattr(tool_runtime, "definitions", []) or [])
            ),
            tool_runtime_executor=self.tool_runtime_executor,
        )
        if self.tool_runtime is not None:
            setattr(self.tool_runtime, "runtime_host", self.single_agent_runtime_host)
        attach_prompt_accounting = getattr(self.model_runtime, "attach_prompt_accounting_ledger", None)
        if callable(attach_prompt_accounting):
            attach_prompt_accounting(self.single_agent_runtime_host.prompt_accounting_ledger)
        attach_observability = getattr(self.model_runtime, "attach_runtime_observability", None)
        if callable(attach_observability):
            attach_observability(self.single_agent_runtime_host.observability)
        self.agent_runtime_services = AgentRuntimeServices.from_runtime_host(
            self.single_agent_runtime_host,
            execute_task_run_callback=self.execute_task_run,
            execute_graph_agent_work_order_callback=self.execute_graph_agent_work_order,
            model_runtime=self.model_runtime,
            tool_runtime_executor=self.tool_runtime_executor,
            tool_instances=tuple(self._all_tool_instances()),
            agent_runtime_profile_resolver=self.agent_runtime_registry.get_profile,
        )
        self.task_executor_controller = TaskExecutorController(
            runtime_host=self.single_agent_runtime_host,
            execute_task_run_callback=lambda task_run_id, **kwargs: self.execute_task_run(task_run_id, **kwargs),
        )
        self.graph_harness = GraphHarness(
            services=self.agent_runtime_services,
        )
        self.single_agent_runtime_host.runtime_monitor_service.attach_graph_harness(self.graph_harness)
        self.task_executor_recovery = self.task_executor_controller.recover_interrupted_executor_leases()
        self.runtime_components = {
            "harness.entrypoint": "application_runtime_facade",
            "graph_harness": "active",
            "evidence_orchestrator": "active" if retrieval_enabled else "disabled_missing_retrieval_service",
            "task_executor_recovery": self.task_executor_recovery,
        }

    def _session_scope_for_monitor(self, session_id: str) -> dict[str, Any] | None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return None
        try:
            history = self.session_manager.load_session_record(normalized)
        except Exception:
            return None
        scope = dict(history.get("scope") or {})
        if not scope:
            return None
        return {
            "workspace_view": str(scope.get("workspace_view") or "chat").strip() or "chat",
            "task_environment_id": str(scope.get("task_environment_id") or "").strip(),
            "project_id": str(scope.get("project_id") or "").strip(),
        }

    def _context_recovery_package_for_session(self, session_id: str) -> dict[str, Any]:
        session_memory = getattr(getattr(self, "memory_facade", None), "session_memory", None)
        manager_factory = getattr(session_memory, "manager", None)
        if not callable(manager_factory):
            return {}
        try:
            manager = manager_factory(session_id)
            loader = getattr(manager, "load_context_recovery_package", None)
            if not callable(loader):
                return {}
            payload = loader()
        except Exception:
            logger.debug("failed to load context recovery package for session", exc_info=True)
            return {}
        return dict(payload) if isinstance(payload, dict) and payload else {}

    def _runtime_history_and_session_context_for_record(
        self,
        *,
        session_id: str,
        history_record: dict[str, Any],
        base_session_context: dict[str, Any] | None = None,
        exclude_current_user_turn_id: str = "",
        exclude_current_user_message: str = "",
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        raw_history = _history_without_current_user_request(
            list(history_record.get("messages") or []),
            turn_id=exclude_current_user_turn_id,
            user_message=exclude_current_user_message,
        )
        api_transcript_loader = getattr(self.session_manager, "load_session_for_api", None)
        api_transcript = (
            api_transcript_loader(session_id)
            if callable(api_transcript_loader)
            else list(raw_history or [])
        )
        history_assembly = assemble_runtime_history(
            history=raw_history,
            compressed_context=str(history_record.get("compressed_context") or ""),
        )
        session_context = dict(base_session_context or {})
        session_context["compressed_context"] = history_assembly.compressed_context
        session_context["api_transcript"] = [
            dict(item)
            for item in list(api_transcript or [])
            if isinstance(item, dict)
        ]
        context_recovery_package = self._context_recovery_package_for_session(session_id)
        if context_recovery_package:
            session_context["context_recovery_package"] = context_recovery_package
        else:
            session_context.pop("context_recovery_package", None)
        provider_protocol_compaction_created_at = float(history_record.get("provider_protocol_compaction_created_at") or 0.0)
        if provider_protocol_compaction_created_at > 0:
            session_context["provider_protocol_compaction_created_at"] = provider_protocol_compaction_created_at
        else:
            session_context.pop("provider_protocol_compaction_created_at", None)
        conversation_state = dict(history_record.get("conversation_state") or {})
        project_binding = dict(conversation_state.get("project_binding") or {})
        if project_binding:
            session_context["project_binding"] = project_binding
        return [dict(item) for item in history_assembly.model_history], session_context

    async def _compact_session_context_for_single_agent_followup(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload_map = dict(payload or {})
        session_id = str(payload_map.get("session_id") or "").strip()
        if not session_id:
            return {
                "compaction": {
                    "applied": False,
                    "strategy": "none",
                    "skipped_reason": "missing_session_id",
                }
            }
        compaction = compact_session_history(
            self,
            session_id=session_id,
            mode="auto",
            pressure_level="auto",
            reason=str(payload_map.get("reason") or "mid_turn_tool_observation_followup"),
            pressure_source="context",
            context_snapshot=payload_map.get("context_snapshot"),
        )
        history_record = self.session_manager.load_session_record(session_id)
        history, session_context = self._runtime_history_and_session_context_for_record(
            session_id=session_id,
            history_record=history_record,
            exclude_current_user_turn_id=str(payload_map.get("turn_id") or ""),
            exclude_current_user_message=str(payload_map.get("user_message") or ""),
            base_session_context=(
                dict(payload_map.get("session_context") or {})
                if isinstance(payload_map.get("session_context"), dict)
                else {}
            ),
        )
        return {
            "compaction": dict(compaction or {}),
            "history": history,
            "session_context": session_context,
        }

    def _event_coverage_for_active_turn(self, *, session_id: str, turn_id: str) -> dict[str, Any]:
        active_registry = getattr(self.single_agent_runtime_host, "active_turn_registry", None)
        if active_registry is None:
            return {}
        try:
            active_turn = active_registry.snapshot(session_id)
        except Exception:
            logger.debug("failed to snapshot active turn for context recovery coverage", exc_info=True)
            return {}
        if active_turn is None:
            return {}
        if str(getattr(active_turn, "turn_id", "") or "") != str(turn_id or ""):
            return {}
        turn_run_id = str(getattr(active_turn, "turn_run_id", "") or "").strip()
        if not turn_run_id:
            return {}
        latest_offset = -1
        try:
            turn_run = self.single_agent_runtime_host.state_index.get_turn_run(turn_run_id)
            latest_offset = int(getattr(turn_run, "latest_event_offset", -1) if turn_run is not None else -1)
        except Exception:
            latest_offset = -1
        if latest_offset < 0:
            try:
                latest_offset = max(0, int(self.single_agent_runtime_host.event_log.event_count(turn_run_id)) - 1)
            except Exception:
                latest_offset = -1
        if latest_offset < 0:
            return {}
        return {
            "covered_event_run_id": turn_run_id,
            "covered_event_offset_start": 0,
            "covered_event_offset_end": latest_offset,
        }

    async def astream(self, request: HarnessRuntimeRequest):
        history_record = self.session_manager.load_session_record(request.session_id)
        auto_compaction: dict[str, Any] = {}
        if not request.history:
            auto_compaction = auto_compact_session_if_needed(
                self,
                session_id=request.session_id,
                reason="auto_context_replacement_before_model_turn",
            )
            if bool(auto_compaction.get("applied")):
                history_record = self.session_manager.load_session_record(request.session_id)
        raw_history = request.history or self.session_manager.load_session_for_agent(request.session_id)
        api_transcript_loader = getattr(self.session_manager, "load_session_for_api", None)
        api_transcript = (
            api_transcript_loader(request.session_id)
            if callable(api_transcript_loader) and not request.history
            else list(raw_history or [])
        )
        history_assembly = assemble_runtime_history(
            history=raw_history,
            compressed_context=str(history_record.get("compressed_context") or ""),
        )
        history = [dict(item) for item in history_assembly.model_history]
        session_context = {
            "compressed_context": history_assembly.compressed_context,
            "api_transcript": [dict(item) for item in list(api_transcript or []) if isinstance(item, dict)],
        }
        context_recovery_package = self._context_recovery_package_for_session(request.session_id)
        if context_recovery_package:
            session_context["context_recovery_package"] = context_recovery_package
        provider_protocol_compaction_created_at = float(history_record.get("provider_protocol_compaction_created_at") or 0.0)
        if provider_protocol_compaction_created_at > 0:
            session_context["provider_protocol_compaction_created_at"] = provider_protocol_compaction_created_at
        conversation_state = dict(history_record.get("conversation_state") or {})
        project_binding = dict(conversation_state.get("project_binding") or {})
        if project_binding:
            session_context["project_binding"] = project_binding
        editor_context = dict(getattr(request, "editor_context", {}) or {})
        if editor_context:
            session_context["editor_context"] = editor_context
        turn_index = len(history_record.get("messages", [])) + 1
        turn_id = f"turn:{request.session_id}:{turn_index}"
        started_active_turn_id = ""
        request_permission_mode = _request_permission_mode(
            request,
            session_record=history_record,
            permission_mode_provider=self.single_agent_runtime_host._current_permission_mode,
        )
        try:
            active_turn = self.single_agent_runtime_host.active_turn_registry.resolve_current(request.session_id)
            input_commit_gate = self._commit_user_message(
                session_id=request.session_id,
                content=request.message,
                turn_id=turn_id,
            )
            if active_turn is None:
                self.single_agent_runtime_host.active_turn_registry.start(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    stream_run_id=str(dict(getattr(request, "runtime_profile", {}) or {}).get("stream_run_id") or ""),
                    state="starting",
                )
                started_active_turn_id = turn_id
            with start_turn_trace(
                session_id=request.session_id,
                user_message=request.message,
                history_length=len(history),
                metadata={
                    "request_kind": "chat",
                    "harness.entrypoint_role": "application_runtime_facade",
                    "history_assembly": dict(history_assembly.diagnostics),
                    "auto_context_compaction": {
                        "applied": bool(auto_compaction.get("applied")),
                        "strategy": str(auto_compaction.get("strategy") or "none"),
                        "skipped_reason": str(auto_compaction.get("skipped_reason") or ""),
                    },
                    "permission_mode": request_permission_mode,
                },
                tags=["harness-entrypoint", "agent-runtime-chain"],
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

                active_work_context = self._active_work_context_from_active_turn(request.session_id)
                fast_steer_events = await self._active_turn_steer_fast_path(
                    request=request,
                    turn_id=turn_id,
                    active_work_context=active_work_context,
                )
                if fast_steer_events is not None:
                    for event in fast_steer_events:
                        yield event
                    return

                agent_runtime_profile = self.agent_runtime_registry.get_profile("agent:0")
                request_environment_binding = dict(getattr(request, "environment_binding", {}) or {})
                runtime_contract = _runtime_contract_for_turn(
                    request_runtime_contract=dict(request.runtime_contract or {}),
                    turn_id=turn_id,
                    runtime_profile=dict(request.runtime_profile or {}),
                    active_turn_present=active_turn is not None,
                )
                agent_invocation_id = f"aginvoke:{turn_id}:main"
                tool_instances = self._all_tool_instances()
                runtime_assembly = assemble_runtime(
                    backend_dir=self.base_dir,
                    session_id=request.session_id,
                    turn_id=turn_id,
                    agent_invocation_id=agent_invocation_id,
                    runtime_contract=runtime_contract,
                    model_selection=dict(request.model_selection or {}),
                    environment_binding=request_environment_binding,
                    agent_runtime_profile=agent_runtime_profile,
                    tool_instances=tool_instances,
                    definitions_by_name=dict(self.single_agent_runtime_host.tool_authorization_index.definitions_by_name or {}),
                    permission_mode=request_permission_mode,
                    workspace_root=str(project_binding.get("workspace_root") or ""),
                )
                self._record_turn_environment_snapshot(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    runtime_assembly=runtime_assembly,
                )
                yield {
                    "type": "runtime_assembly_compiled",
                    "runtime_assembly": runtime_assembly.to_dict(),
                }

                runtime_branch = _runtime_branch_projection(runtime_assembly=runtime_assembly)
                if active_work_context is None:
                    active_work_context = self._current_work_context_from_latest_task(request.session_id)
                recent_work_outcome: dict[str, Any] = {}
                if active_work_context is None:
                    recent_work_outcome = self._recent_work_outcome_from_latest_task(request.session_id)
                    if recent_work_outcome:
                        session_context["recent_work_outcome"] = recent_work_outcome
                turn_input_facts = build_turn_input_facts(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    user_message=request.message,
                    expected_active_turn_id=str(getattr(request, "expected_active_turn_id", "") or "").strip(),
                    active_turn_input_policy=str(getattr(request, "active_turn_input_policy", "") or "auto").strip() or "auto",
                    active_turn=active_turn,
                    active_work_candidate=active_work_context,
                    recent_work_outcome_candidate=recent_work_outcome,
                    environment_binding=request_environment_binding,
                    runtime_profile=dict(request.runtime_profile or {}),
                    editor_context=editor_context,
                )
                session_context["turn_id"] = turn_id
                session_context["turn_input_facts"] = turn_input_facts.to_dict()
                session_emphasis = self._session_emphasis_for_turn(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    user_message=request.message,
                    environment_binding=request_environment_binding,
                    active_work_context=active_work_context,
                    recent_work_outcome=recent_work_outcome,
                    runtime_assembly=runtime_assembly,
                )
                if session_emphasis:
                    session_context["session_emphasis"] = session_emphasis
                memory_context = await self._runtime_memory_context_for_turn(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    user_message=request.message,
                    session_context=session_context,
                    agent_runtime_profile=agent_runtime_profile,
                    runtime_assembly=runtime_assembly,
                    environment_binding=request_environment_binding,
                    active_work_context=active_work_context,
                    recent_work_outcome=recent_work_outcome,
                )
                if memory_context:
                    session_context["memory_context"] = memory_context
                yield {
                    "type": "runtime_branch_decided",
                    "runtime_branch": runtime_branch,
                }
                if runtime_branch.get("branch_kind") == "single_agent_turn":
                    async for event in self._run_single_agent_turn(
                        request=request,
                        turn_id=turn_id,
                        history=history,
                        session_context=session_context,
                        agent_invocation_id=agent_invocation_id,
                        agent_runtime_profile=agent_runtime_profile,
                        runtime_assembly=runtime_assembly,
                        runtime_branch=runtime_branch,
                        active_work_context=active_work_context,
                    ):
                        yield event
                    return
                if runtime_branch.get("branch_kind") == "explicit_contract_task":
                    async for event in self._run_explicit_contract_task_turn(
                        request=request,
                        turn_id=turn_id,
                        agent_runtime_profile=agent_runtime_profile,
                        runtime_assembly=runtime_assembly,
                        runtime_branch=runtime_branch,
                    ):
                        yield event
                    return
                if runtime_branch.get("branch_kind") == "blocked_runtime":
                    blocked_content = "当前运行环境未能完成装配，本轮无法继续。"
                    await self._commit_entrypoint_fail_closed_message(
                        session_id=request.session_id,
                        turn_id=turn_id,
                        content=blocked_content,
                        answer_source="harness.entrypoint.blocked_runtime",
                        terminal_reason="blocked_runtime",
                    )
                    yield error_event(
                        content=blocked_content,
                        code="blocked_runtime",
                        reason=str(runtime_branch.get("reason") or "runtime_assembly_blocked"),
                    )
                    return

                unhandled_content = "当前请求没有匹配到可执行的单 agent 入口。"
                await self._commit_entrypoint_fail_closed_message(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    content=unhandled_content,
                    answer_source="harness.entrypoint.runtime_branch_unhandled",
                    terminal_reason="runtime_branch_unhandled",
                )
                yield error_event(
                    content=unhandled_content,
                    code="runtime_branch_unhandled",
                    reason=str(runtime_branch.get("branch_kind") or ""),
                )
                return
        except Exception as exc:
            logger.exception("HarnessRuntimeFacade failed while streaming request.")
            self._release_transient_active_turn(
                session_id=request.session_id,
                turn_id=turn_id,
                terminal_reason="harness.entrypoint_error",
            )
            failure_text = self._user_visible_error(exc)
            await self._commit_entrypoint_fail_closed_message(
                session_id=request.session_id,
                turn_id=turn_id,
                content=failure_text,
                answer_source="harness.entrypoint.exception",
                terminal_reason="harness.entrypoint_error",
            )
            error_payload = {"type": "error", "error": failure_text}
            if isinstance(exc, ModelRuntimeError):
                error_payload["code"] = exc.code
            yield error_payload
        finally:
            if started_active_turn_id:
                self._release_transient_active_turn(
                    session_id=request.session_id,
                    turn_id=started_active_turn_id,
                    terminal_reason="turn_stream_closed",
                )

    async def _commit_entrypoint_fail_closed_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        content: str,
        answer_source: str,
        terminal_reason: str,
    ) -> bool:
        if self._session_has_assistant_message_for_turn(session_id=session_id, turn_id=turn_id):
            return False
        decision = canonical_output_decision_for_final_text(
            content,
            answer_channel="orchestration_fail_closed",
            answer_source=answer_source,
            execution_posture="runtime_entrypoint",
            terminal_reason=terminal_reason,
        )
        try:
            await self._apply_assistant_message_commit_async(
                session_id,
                {
                    "role": "assistant",
                    "content": decision.content,
                    "turn_id": turn_id,
                    **decision.to_payload(),
                },
            )
            return True
        except Exception:
            logger.debug("failed to commit entrypoint fail-closed assistant message", exc_info=True)
            return False

    def _session_has_assistant_message_for_turn(self, *, session_id: str, turn_id: str) -> bool:
        try:
            loaded = self.session_manager.load_session(session_id)
        except Exception:
            return False
        messages = list(loaded.get("messages") or []) if isinstance(loaded, dict) else list(loaded or [])
        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "") != "assistant":
                continue
            if str(message.get("turn_id") or "") == str(turn_id or ""):
                return True
        return False

    async def _run_single_agent_turn(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        history: list[dict[str, Any]],
        session_context: dict[str, Any],
        agent_invocation_id: str,
        agent_runtime_profile: Any,
        runtime_assembly: Any,
        runtime_branch: dict[str, Any],
        active_work_context: ActiveWorkContext | None,
    ):
        async def start_task(action_request: ModelActionRequest):
            replacement_block = await self._prepare_current_task_for_new_task_request(
                session_id=request.session_id,
                turn_id=turn_id,
                action_request=action_request,
                answer_source="harness.single_agent_turn.request_task_run",
                runtime_branch=runtime_branch,
            )
            if replacement_block is not None:
                for event in replacement_block:
                    yield event
                return
            async for event in start_task_lifecycle_from_action_request(
                runtime_host=self.single_agent_runtime_host,
                session_id=request.session_id,
                turn_id=turn_id,
                runtime_contract=dict(request.runtime_contract or {}),
                model_selection=dict(request.model_selection or {}),
                action_request=action_request,
                agent_runtime_profile=agent_runtime_profile,
                runtime_assembly=runtime_assembly,
                runtime_branch=runtime_branch,
                editor_context=dict(getattr(request, "editor_context", {}) or {}),
                answer_source="harness.single_agent_turn.request_task_run",
                scheduler="single_agent_turn",
                max_steps=_CONVERSATION_TASK_EXECUTION_STEPS,
                commit_assistant_message=self._apply_assistant_message_commit_async,
                initialize_task_todo=self._initialize_task_todo_for_contract,
                schedule_task_run_executor=self.schedule_task_run_executor,
            ):
                task_run_id = _task_run_id_from_lifecycle_event(event)
                if task_run_id:
                    self._record_turn_environment_snapshot(
                        session_id=request.session_id,
                        turn_id=turn_id,
                        runtime_assembly=runtime_assembly,
                        task_run_id=task_run_id,
                    )
                yield event

        async def apply_active_work_control(control_payload: dict[str, Any]) -> str | dict[str, Any]:
            if active_work_context is None:
                return "当前没有可控制的进行中工作。"
            active_turn_guard = self._active_turn_control_guard(
                request=request,
                active_work_context=active_work_context,
            )
            if active_turn_guard is not None:
                return active_turn_guard
            decision = active_work_turn_decision_from_payload(
                {
                    **dict(control_payload or {}),
                    "authority": "harness.loop.active_work_turn_decision",
                    "action": str(control_payload.get("action") or ""),
                    "response": str(control_payload.get("response") or ""),
                    "appended_instruction": str(control_payload.get("appended_instruction") or ""),
                    "continuation_strategy": str(control_payload.get("continuation_strategy") or ""),
                    "turn_response_policy": str(control_payload.get("turn_response_policy") or ""),
                    "user_turn_kind": str(control_payload.get("user_turn_kind") or ""),
                    "answer_obligation": str(control_payload.get("answer_obligation") or ""),
                    "relation_to_current_work": str(control_payload.get("relation_to_current_work") or ""),
                    "evidence": str(control_payload.get("evidence") or ""),
                },
                user_message=request.message,
            )
            control_payload["resolved_action"] = decision.action
            if not decision.accepted:
                control_payload["decision_error"] = decision.denied_reason or decision.reason
                return {
                    "status": "blocked",
                    "terminal_reason": decision.denied_reason or decision.reason or "active_work_control_denied",
                    "content": active_work_control_denial_observation(decision),
                }
            return await self._apply_active_work_turn_decision(
                decision=decision,
                context=active_work_context,
                turn_id=turn_id,
                user_message=request.message,
                editor_context=dict(getattr(request, "editor_context", {}) or {}),
            )

        async for event in run_single_agent_turn(
            session_id=request.session_id,
            turn_id=turn_id,
            user_message=request.message,
            history=history,
            session_context=session_context,
            agent_invocation_id=agent_invocation_id,
            agent_runtime_profile=agent_runtime_profile,
            model_selection=dict(request.model_selection or {}),
            runtime_assembly=runtime_assembly,
            runtime_host=self.single_agent_runtime_host,
            runtime_branch=runtime_branch,
            active_work_context=active_work_context,
            model_runtime=getattr(self.model_response_executor, "model_runtime", None),
            commit_assistant_message=self._apply_assistant_message_commit_async,
            stream_run_id=str(dict(getattr(request, "runtime_profile", {}) or {}).get("stream_run_id") or ""),
            start_task_from_action_request=start_task,
            apply_active_work_control=apply_active_work_control,
            compact_session_context=self._compact_session_context_for_single_agent_followup,
        ):
                yield event

    async def _active_turn_steer_fast_path(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        active_work_context: ActiveWorkContext | None,
    ) -> list[dict[str, Any]] | None:
        policy = str(getattr(request, "active_turn_input_policy", "") or "auto").strip().lower() or "auto"
        if policy != "steer":
            return None
        expected_active_turn_id = str(getattr(request, "expected_active_turn_id", "") or "").strip()
        if not expected_active_turn_id:
            return await self._active_turn_steer_blocked_events(
                request=request,
                turn_id=turn_id,
                context=None,
                terminal_reason="expected_active_turn_unavailable",
                content="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
            )
        if active_work_context is None:
            if self._current_work_context_from_latest_task(request.session_id) is not None:
                return None
            return await self._active_turn_steer_blocked_events(
                request=request,
                turn_id=turn_id,
                context=None,
                terminal_reason="active_turn_steer_not_running",
                content="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
            )
        if str(active_work_context.authority or "") != "harness.runtime.active_turn_context":
            return await self._active_turn_steer_blocked_events(
                request=request,
                turn_id=turn_id,
                context=active_work_context,
                terminal_reason="expected_active_turn_mismatch",
                content="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
            )
        steer_action = _active_turn_steer_action_from_user_message(str(getattr(request, "message", "") or ""))
        control_state = str(active_work_context.control_state or "")
        if control_state in {"paused", "pause_requested", "stopped", "stop_requested"} and not (
            steer_action == "continue_active_work"
            and active_work_context.resumable
            and control_state in {"paused", "pause_requested"}
        ):
            return await self._active_turn_steer_blocked_events(
                request=request,
                turn_id=turn_id,
                context=active_work_context,
                terminal_reason=f"active_turn_steer_control_state_{control_state}",
                content="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
            )
        if not active_work_context.running and not (
            steer_action in {"continue_active_work", "stop_active_work"}
            and (active_work_context.resumable or steer_action == "stop_active_work")
        ):
            return await self._active_turn_steer_blocked_events(
                request=request,
                turn_id=turn_id,
                context=active_work_context,
                terminal_reason="active_turn_steer_not_running",
                content="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
            )
        guard = self._active_turn_control_guard(request=request, active_work_context=active_work_context)
        if guard is not None:
            terminal_reason = str(guard.get("terminal_reason") or "expected_active_turn_mismatch")
            terminal_events = await self._active_turn_steer_terminal_events(
                request=request,
                turn_id=turn_id,
                context=active_work_context,
                content=str(guard.get("content") or "当前任务状态已变化，请刷新后重试。"),
                status="blocked",
                terminal_reason=terminal_reason,
                completion_state="blocked",
            )
            return [self._active_turn_steer_branch_event(reason=terminal_reason), *terminal_events]
        branch_event = self._active_turn_steer_branch_event(reason="expected_active_turn_matched")
        if steer_action in {"pause_active_work", "stop_active_work", "continue_active_work"}:
            control_events = await self._active_turn_steer_control_events(
                request=request,
                turn_id=turn_id,
                context=active_work_context,
                action=steer_action,
            )
            return [branch_event, *control_events]
        return None

    async def _active_turn_steer_control_events(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        context: ActiveWorkContext,
        action: str,
    ) -> list[dict[str, Any]]:
        expected_active_turn_id = str(getattr(request, "expected_active_turn_id", "") or "").strip()
        decision = active_work_turn_decision_from_payload(
            {
                "authority": "harness.loop.active_work_turn_decision",
                "action": action,
                "relation_to_current_work": "current_work",
                "response": default_reply_for_action(action, context),
                "turn_response_policy": "active_work_only",
                "answer_obligation": "none",
            },
            user_message=str(getattr(request, "message", "") or ""),
        )
        if not decision.accepted:
            content = active_work_control_denial_observation(decision)
            return await self._active_turn_steer_terminal_events(
                request=request,
                turn_id=turn_id,
                context=context,
                content=content,
                status="blocked",
                terminal_reason=decision.denied_reason or decision.reason or "active_work_control_denied",
                completion_state="blocked",
            )
        result = await self._apply_active_work_turn_decision(
            decision=decision,
            context=context,
            turn_id=expected_active_turn_id or turn_id,
            user_message=str(getattr(request, "message", "") or ""),
            editor_context=dict(getattr(request, "editor_context", {}) or {}),
        )
        payload = dict(result) if isinstance(result, dict) else {}
        content = str(payload.get("content") if payload else result or "").strip()
        blocked = str(payload.get("status") or "").strip().lower() == "blocked"
        active_turn_payload = self._active_turn_payload_for_context(
            context=self._active_work_context_from_active_turn(context.session_id) or context,
            turn_id=expected_active_turn_id,
        )
        active_event = {
            "type": "active_task_steer_accepted",
            "summary": content,
            "status": "blocked" if blocked else "accepted",
            "terminal_reason": action,
            "runtime_task_run_id": context.task_run_id,
            "active_turn_id": expected_active_turn_id,
            "active_turn": active_turn_payload,
            "runtime_branch": {
                "branch_kind": "active_turn_steer",
                "invocation_kind": "active_turn_input",
                "reason": "expected_active_turn_matched",
                "authority": "harness.entrypoint.active_turn_steer_fast_path",
            },
            "active_work": {
                "action": action,
                "relation_to_current_work": "current_work",
                "continuation_strategy": "immediate_control",
                "turn_response_policy": "answer_then_active_work",
            },
            "task_run_id": context.task_run_id,
        }
        terminal_events = await self._active_turn_steer_terminal_events(
            request=request,
            turn_id=turn_id,
            context=self._active_work_context_from_active_turn(context.session_id) or context,
            content=content,
            status="blocked" if blocked else "completed",
            terminal_reason=action,
            completion_state="blocked" if blocked else "task_steer_accepted",
        )
        return [active_event, *terminal_events]

    async def _active_turn_steer_blocked_events(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        context: ActiveWorkContext | None,
        terminal_reason: str,
        content: str,
    ) -> list[dict[str, Any]]:
        terminal_events = await self._active_turn_steer_terminal_events(
            request=request,
            turn_id=turn_id,
            context=context,
            content=content,
            status="blocked",
            terminal_reason=terminal_reason,
            completion_state="blocked",
        )
        return [self._active_turn_steer_branch_event(reason=terminal_reason), *terminal_events]

    def _active_turn_steer_branch_event(self, *, reason: str) -> dict[str, Any]:
        return {
            "type": "runtime_branch_decided",
            "runtime_branch": {
                "branch_kind": "active_turn_steer",
                "invocation_kind": "active_turn_input",
                "reason": str(reason or "active_turn_steer"),
                "authority": "harness.entrypoint.active_turn_steer_fast_path",
            },
        }

    async def _active_turn_steer_terminal_events(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        context: ActiveWorkContext | None,
        content: str,
        status: str,
        terminal_reason: str,
        completion_state: str,
    ) -> list[dict[str, Any]]:
        expected_active_turn_id = str(getattr(request, "expected_active_turn_id", "") or "").strip()
        active_turn_payload = self._active_turn_payload_for_context(
            context=context,
            session_id=request.session_id,
            turn_id=expected_active_turn_id,
        )
        extra = {
            "completion_state": completion_state,
            "summary": str(content or "") if completion_state == "task_steer_accepted" else "",
            "active_turn_id": expected_active_turn_id,
            "active_turn": active_turn_payload,
            "runtime_branch": {
                "branch_kind": "active_turn_steer",
                "invocation_kind": "active_turn_input",
                "authority": "harness.entrypoint.active_turn_steer_fast_path",
            },
        }
        if context is not None and context.task_run_id:
            extra["runtime_task_run_id"] = context.task_run_id
            extra["task_run_id"] = context.task_run_id
        status_title, status_detail, status_state, status_phase = _active_turn_steer_status_projection(
            status=status,
            terminal_reason=terminal_reason,
            content=content,
        )
        runtime_status_event = {
            "type": "runtime_status",
            "title": status_title,
            "detail": status_detail,
            "state": status_state,
            "phase": status_phase,
            "terminal_reason": terminal_reason,
            **extra,
        }
        done_event = {
            "type": "done",
            "content": "",
            "answer_channel": "runtime_control",
            "answer_source": "harness.entrypoint.active_turn_steer",
            "terminal_reason": terminal_reason,
            "execution_posture": "active_work_control",
            **extra,
        }
        return [
            runtime_status_event,
            done_event,
        ]

    def _active_turn_payload_for_context(
        self,
        *,
        context: ActiveWorkContext | None,
        session_id: str = "",
        turn_id: str,
    ) -> dict[str, Any]:
        active_turn = self.single_agent_runtime_host.active_turn_registry.snapshot(
            context.session_id if context is not None else session_id
        )
        if active_turn is not None:
            if context is None and str(getattr(active_turn, "turn_id", "") or "").strip() != str(turn_id or "").strip():
                return {
                    "session_id": str(session_id or ""),
                    "turn_id": str(turn_id or ""),
                    "state": "unavailable",
                }
            return active_turn.to_dict()
        if context is None:
            return {
                "session_id": str(session_id or ""),
                "turn_id": str(turn_id or ""),
                "state": "unavailable",
            }
        return {
            "session_id": context.session_id,
            "turn_id": str(turn_id or context.active_work_id or "").strip(),
            "bound_task_run_id": context.task_run_id,
            "state": "running_task" if context.running else "waiting_executor",
        }

    def _active_turn_control_guard(
        self,
        *,
        request: HarnessRuntimeRequest,
        active_work_context: ActiveWorkContext,
    ) -> dict[str, Any] | None:
        if str(getattr(active_work_context, "authority", "") or "") != "harness.runtime.active_turn_context":
            return None
        expected_active_turn_id = str(getattr(request, "expected_active_turn_id", "") or "").strip()
        active_turn = self.single_agent_runtime_host.active_turn_registry.snapshot(request.session_id)
        actual_turn_id = str(getattr(active_turn, "turn_id", "") or "").strip()
        actual_task_run_id = str(getattr(active_turn, "bound_task_run_id", "") or "").strip()
        expected_task_run_id = str(getattr(active_work_context, "task_run_id", "") or "").strip()
        if not active_turn or (expected_task_run_id and actual_task_run_id != expected_task_run_id):
            return {
                "status": "blocked",
                "terminal_reason": "expected_active_turn_mismatch",
                "content": "当前任务状态已变化，请刷新后重试。",
            }
        if expected_active_turn_id and actual_turn_id != expected_active_turn_id:
            return {
                "status": "blocked",
                "terminal_reason": "expected_active_turn_mismatch",
                "content": "当前任务状态已变化，请刷新后重试。",
            }
        return None

    async def _run_explicit_contract_task_turn(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        agent_runtime_profile: Any,
        runtime_assembly: Any,
        runtime_branch: dict[str, Any],
    ):
        action_request = _explicit_contract_action_request(
            request=request,
            turn_id=turn_id,
            runtime_assembly=runtime_assembly,
        )
        contract, contract_errors = _task_run_contract_from_explicit_contract(
            request=request,
            turn_id=turn_id,
            runtime_assembly=runtime_assembly,
            action_request=action_request,
        )
        if contract is None:
            content = "显式任务合同缺少必要目标或验收边界，系统已停止启动任务。"
            decision = canonical_output_decision_for_final_text(
                content,
                answer_channel="task_control",
                answer_source="harness.explicit_contract_task.invalid_contract",
                execution_posture="explicit_contract_task",
                terminal_reason="explicit_contract_invalid",
            )
            await self._apply_assistant_message_commit_async(
                request.session_id,
                {
                    "role": "assistant",
                    "content": decision.content,
                    "turn_id": turn_id,
                    **decision.to_payload(),
                },
            )
            yield error_event(
                content=content,
                code="explicit_contract_invalid",
                reason=";".join(contract_errors) or "explicit_contract_invalid",
            )
            return
        replacement_block = await self._prepare_current_task_for_new_task_request(
            session_id=request.session_id,
            turn_id=turn_id,
            action_request=action_request,
            answer_source="harness.explicit_contract_task",
            runtime_branch=runtime_branch,
        )
        if replacement_block is not None:
            for event in replacement_block:
                yield event
            return
        async for event in start_task_lifecycle_from_contract(
            runtime_host=self.single_agent_runtime_host,
            session_id=request.session_id,
            turn_id=turn_id,
            model_selection=dict(request.model_selection or {}),
            action_request=action_request,
            contract=contract,
            agent_runtime_profile=agent_runtime_profile,
            runtime_assembly=runtime_assembly,
            runtime_branch=runtime_branch,
            editor_context=dict(getattr(request, "editor_context", {}) or {}),
            answer_source="harness.explicit_contract_task",
            scheduler="explicit_contract_task",
            task_id=str(contract.source_contract_ref or contract.contract_id or f"task:{turn_id}"),
            max_steps=_CONVERSATION_TASK_EXECUTION_STEPS,
            commit_assistant_message=self._apply_assistant_message_commit_async,
            initialize_task_todo=self._initialize_task_todo_for_contract,
            schedule_task_run_executor=self.schedule_task_run_executor,
        ):
            task_run_id = _task_run_id_from_lifecycle_event(event)
            if task_run_id:
                self._record_turn_environment_snapshot(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    runtime_assembly=runtime_assembly,
                    task_run_id=task_run_id,
                )
            yield event

    async def _prepare_current_task_for_new_task_request(
        self,
        *,
        session_id: str,
        turn_id: str,
        action_request: ModelActionRequest,
        answer_source: str,
        runtime_branch: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        current_task = current_session_task_run(self.single_agent_runtime_host, session_id=session_id)
        if current_task is None:
            return None
        current_task_id = str(getattr(current_task, "task_run_id", "") or "").strip()
        if not current_task_id:
            return None
        stop_result = stop_task_run(
            self.single_agent_runtime_host,
            current_task_id,
            reason="replaced_by_new_task_request",
            requested_by="agent",
        )
        if not stop_result.get("ok"):
            content = "当前会话已有未完成任务，但运行时未能完成旧任务的接管收口，因此没有启动新的持续任务。"
            decision = canonical_output_decision_for_final_text(
                content,
                answer_channel="blocked",
                answer_source=f"{answer_source}.current_task_replacement_failed",
                execution_posture="task_control",
                terminal_reason=str(stop_result.get("error") or "current_task_replacement_failed"),
            )
            await self._apply_assistant_message_commit_async(
                session_id,
                {
                    "role": "assistant",
                    "content": decision.content,
                    "turn_id": turn_id,
                    **decision.to_payload(),
                },
            )
            return [
                error_event(
                    content=content,
                    code="current_task_replacement_failed",
                    reason=str(stop_result.get("error") or "current_task_replacement_failed"),
                    extra={"runtime_branch": dict(runtime_branch or {}), "task_run": _task_run_identity(current_task)},
                )
            ]
        self._record_current_task_replaced_by_new_request(
            session_id=session_id,
            task_run_id=current_task_id,
            replacement_turn_id=turn_id,
            replacement_request_id=str(getattr(action_request, "request_id", "") or ""),
            relationship=_task_request_active_work_relationship(action_request),
        )
        return None

    def _record_current_task_replaced_by_new_request(
        self,
        *,
        session_id: str,
        task_run_id: str,
        replacement_turn_id: str,
        replacement_request_id: str,
        relationship: str,
    ) -> None:
        host = self.single_agent_runtime_host
        try:
            host.active_turn_registry.complete_bound_task(
                session_id=session_id,
                task_run_id=task_run_id,
                terminal_reason="replaced_by_new_task_request",
            )
        except Exception:
            logger.debug("failed to release replaced active turn", exc_info=True)
        task_run = host.state_index.get_task_run(task_run_id)
        if task_run is None:
            return
        replacement = {
            "replacement_turn_id": str(replacement_turn_id or ""),
            "replacement_request_id": str(replacement_request_id or ""),
            "relationship": str(relationship or "new_task_request"),
            "reason": "request_task_run_while_current_work_exists",
            "authority": "harness.entrypoint.current_work_replacement",
        }
        event = host.event_log.append(
            task_run_id,
            "task_run_replaced_by_new_task_request",
            payload={"task_run_id": task_run_id, "replacement": replacement},
            refs={
                "task_run_ref": task_run_id,
                "turn_ref": str(replacement_turn_id or ""),
                "action_request_ref": str(replacement_request_id or ""),
            },
        )
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        host.state_index.upsert_task_run(
            replace(
                task_run,
                updated_at=event.created_at or time.time(),
                latest_event_offset=event.offset,
                diagnostics={
                    **diagnostics,
                    "replacement": replacement,
                    "latest_step": "task_run_replaced_by_new_task_request",
                    "latest_step_status": str(getattr(task_run, "status", "") or ""),
                    "latest_step_summary": "当前任务已被新的任务请求接管，旧任务保留为审计记录。",
                    "latest_public_progress_note": "当前任务已被新的任务请求接管。",
                },
            )
        )

    def _active_work_context_from_active_turn(self, session_id: str) -> ActiveWorkContext | None:
        active_turn = self.single_agent_runtime_host.active_turn_registry.resolve_current(session_id)
        if active_turn is None or not active_turn.bound_task_run_id:
            return None
        task_run = self.single_agent_runtime_host.state_index.get_task_run(active_turn.bound_task_run_id)
        if task_run is None:
            return None
        status = str(getattr(task_run, "status", "") or "")
        if status in {"completed", "success", "failed", "aborted", "cancelled", "error"}:
            return None
        if str(getattr(task_run, "execution_runtime_kind", "") or "") != "single_agent_task":
            return None
        return self._active_work_context_from_task_run(
            session_id=session_id,
            task_run=task_run,
            active_work_id=active_turn.turn_id,
            authority="harness.runtime.active_turn_context",
        )

    def _current_work_context_from_latest_task(self, session_id: str) -> ActiveWorkContext | None:
        latest = current_session_task_run(self.single_agent_runtime_host, session_id=session_id)
        if latest is None:
            return None
        return self._active_work_context_from_task_run(
            session_id=session_id,
            task_run=latest,
            active_work_id=f"current-task:{getattr(latest, 'task_run_id', '')}",
            authority="harness.runtime.current_session_task_context",
        )

    def _active_work_context_from_task_run(
        self,
        *,
        session_id: str,
        task_run: Any,
        active_work_id: str,
        authority: str,
    ) -> ActiveWorkContext | None:
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        status = str(getattr(task_run, "status", "") or "")
        if status in {"completed", "success", "failed", "aborted", "cancelled", "error"}:
            return None
        if str(getattr(task_run, "execution_runtime_kind", "") or "") != "single_agent_task":
            return None
        control = diagnostics.get("runtime_control") if isinstance(diagnostics.get("runtime_control"), dict) else {}
        control_state = str(dict(control or {}).get("state") or "")
        same_run_allowed = status in {"waiting_executor", "blocked"} and control_state not in {
            "stop_requested",
            "stopped",
        }
        running = status in {"created", "running"}
        continuation_kind = "paused" if control_state == "paused" else ("active" if running else "waiting")
        contract = {}
        try:
            contract = dict(self.single_agent_runtime_host.runtime_objects.get_object(str(getattr(task_run, "task_contract_ref", "") or "")) or {})
        except Exception:
            contract = {}
        goal = str(
            diagnostics.get("goal")
            or contract.get("user_visible_goal")
            or contract.get("task_run_goal")
            or ""
        ).strip()
        return ActiveWorkContext(
            session_id=session_id,
            active_work_id=active_work_id,
            task_run_id=str(getattr(task_run, "task_run_id", "") or ""),
            status=status,
            control_state=control_state,
            user_visible_goal=goal,
            latest_progress=str(
                diagnostics.get("latest_public_progress_note")
                or diagnostics.get("latest_step_summary")
                or ""
            ).strip(),
            latest_step_name=str(diagnostics.get("latest_step") or ""),
            resumable=same_run_allowed,
            running=running,
            paused=control_state == "paused",
            queued_user_instruction_count=int(diagnostics.get("pending_user_steer_count") or 0),
            execution_runtime_kind=str(getattr(task_run, "execution_runtime_kind", "") or ""),
            continuation_kind=continuation_kind,
            same_run_allowed=same_run_allowed,
            authority=authority,
        )

    def _release_transient_active_turn(self, *, session_id: str, turn_id: str, terminal_reason: str) -> None:
        record = self.single_agent_runtime_host.active_turn_registry.snapshot(session_id)
        if record is None or record.turn_id != turn_id:
            return
        if record.bound_task_run_id:
            task_run = self.single_agent_runtime_host.state_index.get_task_run(record.bound_task_run_id)
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
            self.single_agent_runtime_host.active_turn_registry.complete(
                session_id=session_id,
                expected_turn_id=turn_id,
                terminal_reason=terminal_reason,
            )
        except Exception:
            logger.debug("failed to release transient active turn", exc_info=True)

    def _recent_work_outcome_from_latest_task(self, session_id: str) -> dict[str, Any]:
        """Return a read-only status fact for the latest non-active formal task.

        This is context, not routing. The model still decides how to answer the
        current user turn, but it no longer has to rediscover why the last task
        stopped.
        """
        task_runs = [
            item
            for item in list(self.single_agent_runtime_host.state_index.list_session_task_runs(session_id) or [])
            if str(getattr(item, "execution_runtime_kind", "") or "") == "single_agent_task"
        ]
        if not task_runs:
            return {}
        formal = [item for item in task_runs if _looks_like_chat_task_run(item)]
        candidates = formal or task_runs
        latest = sorted(candidates, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True)[0]
        status = str(getattr(latest, "status", "") or "").strip()
        terminal_reason = str(getattr(latest, "terminal_reason", "") or "").strip()
        if not _recent_work_outcome_status(status=status, terminal_reason=terminal_reason):
            return {}
        diagnostics = dict(getattr(latest, "diagnostics", {}) or {})
        monitor = {}
        try:
            monitor = dict(self.single_agent_runtime_host.monitor_projector.project_task_run(latest, now=time.time()))
        except Exception:
            monitor = {}
        contract = {}
        contract_ref = str(getattr(latest, "task_contract_ref", "") or "").strip()
        if contract_ref:
            try:
                contract = dict(self.single_agent_runtime_host.runtime_objects.get_object(contract_ref) or {})
            except Exception:
                contract = {}
        goal = _public_status_text(
            diagnostics.get("goal")
            or contract.get("user_visible_goal")
            or contract.get("task_run_goal")
            or monitor.get("title")
            or getattr(latest, "task_id", "")
        )
        latest_step = dict(monitor.get("latest_step") or {})
        latest_progress = _public_status_text(
            monitor.get("latest_public_progress_note")
            or monitor.get("latest_step_summary")
            or monitor.get("summary")
            or latest_step.get("public_progress_note")
            or diagnostics.get("latest_public_progress_note")
            or diagnostics.get("latest_step_summary")
            or diagnostics.get("summary")
            or terminal_reason
            or status
        )
        agent_brief = _public_status_text(
            monitor.get("agent_brief_output")
            or latest_step.get("agent_brief_output")
            or diagnostics.get("agent_brief_output")
        )
        return _drop_empty_entrypoint_payload(
            {
                "task_run_id": str(getattr(latest, "task_run_id", "") or ""),
                "task_id": str(getattr(latest, "task_id", "") or ""),
                "status": status,
                "terminal_reason": terminal_reason,
                "lifecycle": str(monitor.get("lifecycle") or ""),
                "bucket": str(monitor.get("bucket") or ""),
                "user_visible_goal": goal,
                "latest_progress": latest_progress,
                "latest_step_name": str(monitor.get("latest_step_name") or latest_step.get("step") or diagnostics.get("latest_step") or ""),
                "latest_step_status": str(monitor.get("latest_step_status") or latest_step.get("status") or diagnostics.get("latest_step_status") or ""),
                "latest_event_type": str(monitor.get("latest_event_type") or ""),
                "agent_brief_output": agent_brief,
                "artifact_refs": list(monitor.get("artifact_refs") or diagnostics.get("artifact_refs") or [])[:6],
                "updated_at": float(getattr(latest, "updated_at", 0.0) or 0.0),
                "continuation_state": "terminal_or_interrupted_task_record",
                "decision_boundary": (
                    "This is a read-only result from the most recent terminal, blocked, or interrupted task. "
                    "Use it to answer status or failure questions before using tools. "
                    "Do not treat it as active work and do not resume that task unless the user starts a new task or the runtime exposes a current active-work context."
                ),
                "authority": "harness.runtime.recent_work_outcome",
            }
        )

    def _initialize_task_todo_for_contract(
        self,
        *,
        session_id: str,
        task_run_id: str,
        contract: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            from capability_system.tools.tool_units.agent_todo_tool import AgentTodoTool

            tool = AgentTodoTool(Path(self.single_agent_runtime_host.root_dir))
            result = tool._run(
                operation="replace",
                session_id=session_id,
                task_id=task_run_id,
                items=[
                    {
                        "content": str(contract.get("user_visible_goal") or contract.get("task_run_goal") or "继续处理当前工作"),
                        "status": "in_progress",
                        "evidence_expectations": [
                            *contract_string_tuple(contract.get("completion_criteria")),
                            *[
                                str(item.get("user_visible_name") or item.get("artifact_kind") or item)
                                for item in list(contract.get("required_artifacts") or [])
                                if isinstance(item, dict)
                            ],
                        ],
                        "contract_refs": [str(contract.get("contract_id") or "")],
                    }
                ],
            )
            event = self.single_agent_runtime_host.event_log.append(
                task_run_id,
                "agent_todo_initialized",
                payload={
                    "observation": {
                        "observation_id": f"todoobs:{task_run_id}:initial",
                        "observation_type": "tool_result",
                        "source": "system:agent_todo",
                        "tool_name": "agent_todo",
                        "summary": str(result or "")[:300],
                        "payload": {
                            "tool_name": "agent_todo",
                            "tool_args": {
                                "operation": "replace",
                                "session_id": session_id,
                                "task_id": task_run_id,
                            },
                            "result": str(result or ""),
                        },
                    },
                },
                refs={"task_run_ref": task_run_id},
            )
            return event.to_dict()
        except Exception as exc:
            event = self.single_agent_runtime_host.event_log.append(
                task_run_id,
                "agent_todo_initialization_failed",
                payload={
                    "observation": {
                        "source": "system:agent_todo",
                        "summary": "任务待办初始化失败。",
                        "payload": {"error": str(exc)},
                        "error": str(exc),
                    },
                },
                refs={"task_run_ref": task_run_id},
            )
            return event.to_dict()

    def _apply_append_instruction_to_active_work(
        self,
        *,
        decision: ActiveWorkTurnDecision,
        context: ActiveWorkContext,
        turn_id: str,
        user_message: str,
        default_response: str,
        editor_context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        host = self.single_agent_runtime_host
        instruction = decision.appended_instruction or str(user_message or "").strip()
        result = append_user_work_instruction(
            host,
            context.task_run_id,
            content=instruction,
            turn_id=turn_id,
            intent="append_instruction_to_active_work",
            editor_context=dict(editor_context or {}),
        )
        if result.get("ok"):
            self._bind_current_turn_to_task_run(
                session_id=context.session_id,
                turn_id=turn_id,
                task_run_id=context.task_run_id,
                state="running_task" if context.running else "waiting_executor",
            )
        if result.get("ok") and context.resumable:
            resume_result = resume_paused_task_run(
                host,
                context.task_run_id,
                reason="conversation_instruction",
                requested_by="user",
                turn_id=turn_id,
            )
            if resume_result.get("ok"):
                self._bind_current_turn_to_task_run(
                    session_id=context.session_id,
                    turn_id=turn_id,
                    task_run_id=context.task_run_id,
                    state="waiting_executor",
                )
                schedule_result = self._schedule_active_task_run_executor(
                    context.task_run_id,
                    scheduler="conversation_instruction",
                    turn_id=turn_id,
                )
                if not _schedule_result_allows_progress(schedule_result):
                    return _active_work_schedule_failure_payload(schedule_result)
                self._bind_current_turn_to_task_run(
                    session_id=context.session_id,
                    turn_id=turn_id,
                    task_run_id=context.task_run_id,
                    state="running_task",
                )
            else:
                return _active_work_resume_failure_payload(resume_result)
        if not result.get("ok"):
            return active_work_status_reply(self._active_work_context_from_active_turn(context.session_id) or context)
        if result.get("ok") and not context.running and not context.resumable:
            latest_context = self._active_work_context_from_active_turn(context.session_id) or context
            return "补充要求已记录。\n" + active_work_status_reply(latest_context)
        return default_response

    async def _apply_active_work_turn_decision(
        self,
        *,
        decision: ActiveWorkTurnDecision,
        context: ActiveWorkContext,
        turn_id: str,
        user_message: str,
        editor_context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        host = self.single_agent_runtime_host
        action = decision.action
        response = public_active_work_text(decision.response) or default_reply_for_action(action, context)
        if action == "continue_active_work":
            response = self._apply_continue_active_work(
                context=context,
                turn_id=turn_id,
                user_message=user_message,
                appended_instruction=decision.appended_instruction,
                continuation_strategy=decision.continuation_strategy,
                default_response=response,
                editor_context=dict(editor_context or {}),
            )
        elif action == "pause_active_work":
            result = request_task_run_pause(host, context.task_run_id, reason="conversation_pause", requested_by="user")
            if not result.get("ok"):
                response = active_work_status_reply(self._active_work_context_from_active_turn(context.session_id) or context)
            else:
                control_state = str(dict(result.get("control") or {}).get("state") or "").strip()
                self._bind_current_turn_to_task_run(
                    session_id=context.session_id,
                    turn_id=turn_id,
                    task_run_id=context.task_run_id,
                    state="waiting_executor" if control_state == "paused" else "waiting_safe_boundary",
                )
        elif action == "stop_active_work":
            result = stop_task_run(host, context.task_run_id, reason="conversation_stop", requested_by="user")
            if not result.get("ok"):
                response = active_work_status_reply(self._active_work_context_from_active_turn(context.session_id) or context)
            else:
                self._complete_active_turn_for_task_run(
                    session_id=context.session_id,
                    task_run_id=context.task_run_id,
                    terminal_reason="conversation_stop",
                )
        elif action == "append_instruction_to_active_work":
            response = self._apply_append_instruction_to_active_work(
                decision=decision,
                context=context,
                turn_id=turn_id,
                user_message=user_message,
                default_response=response,
                editor_context=dict(editor_context or {}),
            )
        elif action == "answer_then_continue_active_work":
            response = self._apply_continue_active_work(
                context=context,
                turn_id=turn_id,
                user_message=user_message,
                appended_instruction=decision.appended_instruction,
                continuation_strategy=decision.continuation_strategy,
                default_response=response,
                editor_context=dict(editor_context or {}),
            )
        elif action == "answer_about_active_work":
            response = decision.response or active_work_status_reply(self._active_work_context_from_active_turn(context.session_id) or context)
        elif action == "ask_user":
            response = decision.response or default_reply_for_action(action, context)
        if isinstance(response, dict):
            return {
                **response,
                "content": public_active_work_text(str(response.get("content") or "")),
            }
        return public_active_work_text(response)

    def _apply_continue_active_work(
        self,
        *,
        context: ActiveWorkContext,
        turn_id: str,
        user_message: str,
        appended_instruction: str = "",
        continuation_strategy: str = "",
        default_response: str,
        editor_context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        host = self.single_agent_runtime_host
        strategy = _continuation_strategy_for_execution(
            decision_strategy=continuation_strategy,
            context=context,
        )
        if strategy == "same_run_resume":
            if not (context.same_run_allowed or context.resumable):
                return active_work_status_reply(self._active_work_context_from_active_turn(context.session_id) or context)
            instruction = str(appended_instruction or "").strip()
            if instruction:
                append_user_work_instruction(
                    host,
                    context.task_run_id,
                    content=instruction,
                    turn_id=turn_id,
                    intent="conversation_continue",
                    editor_context=dict(editor_context or {}),
                )
            result = resume_paused_task_run(
                host,
                context.task_run_id,
                reason="conversation_continue",
                requested_by="user",
                turn_id=turn_id,
            )
            if result.get("ok"):
                self._bind_current_turn_to_task_run(
                    session_id=context.session_id,
                    turn_id=turn_id,
                    task_run_id=context.task_run_id,
                    state="waiting_executor",
                )
                schedule_result = self._schedule_active_task_run_executor(
                    context.task_run_id,
                    scheduler="conversation_continue",
                    turn_id=turn_id,
                )
                if not _schedule_result_allows_progress(schedule_result):
                    return _active_work_schedule_failure_payload(schedule_result)
                self._bind_current_turn_to_task_run(
                    session_id=context.session_id,
                    turn_id=turn_id,
                    task_run_id=context.task_run_id,
                    state="running_task",
                )
                return default_response or "好，我接着处理。"
            return _active_work_resume_failure_payload(result)
        if strategy == "already_running":
            if not context.running:
                return active_work_status_reply(self._active_work_context_from_active_turn(context.session_id) or context)
            self._bind_current_turn_to_task_run(
                session_id=context.session_id,
                turn_id=turn_id,
                task_run_id=context.task_run_id,
                state="running_task",
            )
            instruction = str(appended_instruction or "").strip()
            if instruction:
                append_user_work_instruction(
                    host,
                    context.task_run_id,
                    content=instruction,
                    turn_id=turn_id,
                    intent="conversation_steer_while_running",
                    editor_context=dict(editor_context or {}),
                )
            return default_response or "我正在接着处理，新的进展会继续更新在这里。"
        return active_work_status_reply(self._active_work_context_from_active_turn(context.session_id) or context)

    def _bind_current_turn_to_task_run(
        self,
        *,
        session_id: str,
        turn_id: str,
        task_run_id: str,
        state: str,
    ) -> None:
        active_registry = self.single_agent_runtime_host.active_turn_registry
        try:
            record = active_registry.resolve_current(session_id)
            if record is None:
                record = active_registry.start(session_id=session_id, turn_id=turn_id, state="starting")
            if str(getattr(record, "turn_id", "") or "") != str(turn_id or ""):
                return
            existing_task_run_id = str(getattr(record, "bound_task_run_id", "") or "").strip()
            if existing_task_run_id and existing_task_run_id != str(task_run_id or "").strip():
                return
            active_registry.bind_task_run(
                session_id=session_id,
                turn_id=turn_id,
                task_run_id=task_run_id,
                state=state if state in {"running_task", "waiting_executor", "waiting_approval", "waiting_safe_boundary"} else "waiting_executor",
            )
        except Exception:
            logger.debug("failed to bind current active turn to task run", exc_info=True)

    def _complete_active_turn_for_task_run(self, *, session_id: str, task_run_id: str, terminal_reason: str) -> None:
        try:
            self.single_agent_runtime_host.active_turn_registry.complete_bound_task(
                session_id=session_id,
                task_run_id=task_run_id,
                terminal_reason=terminal_reason,
            )
        except Exception:
            logger.debug("failed to complete active turn for task run", exc_info=True)

    def _schedule_active_task_run_executor(
        self,
        task_run_id: str,
        *,
        scheduler: str,
        turn_id: str = "",
        max_steps: int = _CONVERSATION_TASK_EXECUTION_STEPS,
    ) -> dict[str, Any]:
        return self.schedule_task_run_executor(task_run_id, scheduler=scheduler, turn_id=turn_id, max_steps=max_steps)

    def schedule_task_run_executor(
        self,
        task_run_id: str,
        *,
        scheduler: str,
        turn_id: str = "",
        max_steps: int = _CONVERSATION_TASK_EXECUTION_STEPS,
    ) -> dict[str, Any]:
        return self.task_executor_controller.schedule(
            task_run_id,
            scheduler=scheduler,
            turn_id=turn_id,
            max_steps=max_steps,
        )

    def recover_scheduled_task_run_executor(
        self,
        task_run_id: str,
        *,
        scheduler: str,
        max_steps: int = _CONVERSATION_TASK_EXECUTION_STEPS,
        recovered_from: str = "scheduled_executor_claim",
    ) -> dict[str, Any]:
        return self.task_executor_controller.recover_scheduled(
            task_run_id,
            scheduler=scheduler,
            max_steps=max_steps,
            recovered_from=recovered_from,
        )

    def schedule_or_recover_task_run_executor(
        self,
        task_run_id: str,
        *,
        scheduler: str,
        max_steps: int = _CONVERSATION_TASK_EXECUTION_STEPS,
        recovered_from: str = "scheduled_executor_claim",
    ) -> dict[str, Any]:
        return self.task_executor_controller.recover_scheduled(
            task_run_id,
            scheduler=scheduler,
            max_steps=max_steps,
            recovered_from=recovered_from,
        )

    def start_runtime_recovered_task_run_executors(
        self,
        *,
        max_steps: int = _CONVERSATION_TASK_EXECUTION_STEPS,
    ) -> dict[str, Any]:
        recovery = dict(getattr(self, "task_executor_recovery", {}) or {})
        task_run_ids = [
            str(item or "").strip()
            for item in list(recovery.get("task_run_ids") or [])
            if str(item or "").strip()
        ]
        schedule_result = self.task_executor_controller.schedule_runtime_start_recovered_executors(
            task_run_ids,
            scheduler="runtime_start_recovery",
            max_steps=max_steps,
        )
        self.task_executor_recovery = {
            **recovery,
            "executor_restart_schedule": schedule_result,
        }
        runtime_components = dict(getattr(self, "runtime_components", {}) or {})
        runtime_components["task_executor_recovery"] = self.task_executor_recovery
        self.runtime_components = runtime_components
        return schedule_result

    async def generate_title(self, first_user_message: str) -> str:
        return await self.model_runtime.generate_title(first_user_message)

    async def execute_task_run(self, task_run_id: str, *, max_steps: int = 12) -> dict[str, Any]:
        task_run = self.single_agent_runtime_host.state_index.get_task_run(task_run_id)
        services = self._task_executor_services_for_task_run(task_run) if task_run is not None else self._task_executor_services()
        return await execute_task_run(services, task_run_id, max_steps=max_steps)

    async def execute_graph_agent_work_order(self, *, graph_config: Any, work_order: Any, max_steps: int = 12) -> dict[str, Any]:
        task_run = self._create_graph_node_task_run(graph_config=graph_config, work_order=work_order)
        return await execute_task_run(
            self._task_executor_services_for_task_run(task_run),
            task_run.task_run_id,
            max_steps=max(1, int(max_steps or 12)),
            graph_node_authorization={
                "graph_run_id": work_order.graph_run_id,
                "graph_work_order_id": work_order.work_order_id,
                "graph_node_id": work_order.node_id,
            },
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

    def _task_executor_backend_config(self) -> dict[str, Any]:
        provider = getattr(self.settings_service, "task_executor_backend_config", None)
        if callable(provider):
            payload = provider()
            if isinstance(payload, dict):
                return dict(payload)
        return dict(getattr(self, "config", {}) or {})

    def _task_executor_services_with_profile(self, profile: Any) -> TaskExecutorServices:
        return TaskExecutorServices(
            runtime_host=self.single_agent_runtime_host,
            backend_dir=self.base_dir,
            model_runtime=self.model_runtime,
            tool_control_plane=getattr(self.single_agent_runtime_host, "tool_control_plane", None),
            tool_runtime_executor=self.tool_runtime_executor,
            tool_instances=tuple(self._all_tool_instances()),
            agent_runtime_profile=profile,
            backend_config=self._task_executor_backend_config(),
            assistant_message_committer=lambda payload: self._apply_assistant_message_commit(
                str(dict(payload or {}).get("session_id") or ""),
                payload,
            ),
            execute_task_run_callback=self.execute_task_run,
            memory_context_provider=lambda payload: self._runtime_memory_context_for_task_execution(dict(payload or {})),
        )

    def _create_graph_node_task_run(self, *, graph_config: Any, work_order: Any) -> TaskRun:
        runtime_host = self.single_agent_runtime_host
        now = time.time()
        node_task_run_id = _graph_node_task_run_id(work_order)
        existing = runtime_host.state_index.get_task_run(node_task_run_id)
        if existing is not None:
            _validate_existing_graph_node_task_run(existing, graph_run_id=work_order.graph_run_id, work_order_id=work_order.work_order_id)
            return _refresh_existing_graph_node_task_run(
                runtime_host=runtime_host,
                graph_config=graph_config,
                work_order=work_order,
                task_run=existing,
                now=now,
            )
        origin = _graph_node_origin(work_order)
        contract = _graph_node_contract_from_work_order(work_order)
        runtime_contract = _graph_node_runtime_contract(graph_config, work_order)
        model_override_diagnostics = _graph_model_override_diagnostics(work_order)
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
        node_session_id = str(getattr(work_order, "node_session_id", "") or "")
        if node_session_id:
            self._ensure_graph_node_session(
                node_session_id=node_session_id,
                graph_config=graph_config,
                work_order=work_order,
                graph_run=dict(graph_run or {}),
            )
        task_run = TaskRun(
            task_run_id=node_task_run_id,
            session_id=node_session_id or str(dict(graph_run or {}).get("session_id") or work_order.graph_run_id),
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
                "source": "harness.entrypoint.graph_agent_work_order_adapter",
                "origin": origin,
                **origin,
                "graph_run_id": work_order.graph_run_id,
                "graph_harness_config_id": graph_config.config_id,
                "graph_node_id": work_order.node_id,
                "graph_work_order_id": work_order.work_order_id,
                "graph_root_session_id": str(dict(graph_run or {}).get("session_id") or ""),
                "node_session_id": node_session_id,
                "node_session_policy": dict(getattr(work_order, "node_session_policy", {}) or {}),
                "graph_clock_seq": _graph_node_clock_seq(work_order),
                "runtime_scope": _graph_node_runtime_scope(work_order),
                **_graph_node_public_scope_fields(work_order),
                "runtime_contract": runtime_contract,
                "contract": contract.to_dict(),
                **({"graph_model_override": model_override_diagnostics} if model_override_diagnostics else {}),
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

    def _ensure_graph_node_session(
        self,
        *,
        node_session_id: str,
        graph_config: Any,
        work_order: Any,
        graph_run: dict[str, Any],
    ) -> None:
        session_id = str(node_session_id or "").strip()
        if not session_id:
            return
        try:
            self.session_manager.load_session_record(session_id)
            return
        except Exception:
            pass
        runtime_scope = _graph_node_runtime_scope(work_order)
        project_id = str(
            dict(runtime_scope or {}).get("project_id")
            or dict(graph_run or {}).get("project_id")
            or ""
        )
        create = getattr(self.session_manager, "create_session", None)
        if not callable(create):
            return
        create(
            session_id=session_id,
            title=f"Graph node {getattr(work_order, 'node_id', '')}",
            scope={
                "workspace_view": "graph_task",
                "task_environment_id": "",
                "project_id": project_id,
            },
        )

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
            source="harness.entrypoint.adapter_input",
        )
        if decision.commit_allowed:
            payload = dict(decision.commit_candidate.payload)
            self.session_manager.append_messages(
                session_id,
                [
                    {
                        "role": payload.get("role"),
                        "content": payload.get("content"),
                        "turn_id": turn_id,
                    }
                ],
            )
            append_api = getattr(self.session_manager, "append_api_messages", None)
            if callable(append_api):
                append_api(
                    session_id,
                    [
                        {
                            "role": payload.get("role"),
                            "content": payload.get("content"),
                            "turn_id": turn_id,
                        }
                    ],
                )
        return decision

    def _record_turn_environment_snapshot(self, *, session_id: str, turn_id: str, runtime_assembly: Any, task_run_id: str = "") -> None:
        update_snapshot = getattr(self.session_manager, "update_turn_environment_snapshot", None)
        if not callable(update_snapshot):
            return
        try:
            assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
            environment = dict(assembly_payload.get("task_environment") or {})
            boundary = dict(environment.get("environment_boundary") or {})
            prompt_refs = assembly_payload.get("environment_prompt_refs") or boundary.get("prompt_refs") or []
            update_snapshot(
                session_id,
                turn_id=turn_id,
                snapshot={
                    "turn_id": turn_id,
                    "task_environment_id": str(
                        environment.get("environment_id")
                        or environment.get("task_environment_id")
                        or environment.get("requested_environment_id")
                        or ""
                    ).strip(),
                    "environment_kind": str(environment.get("environment_kind") or "").strip(),
                    "environment_prompt_refs": list(prompt_refs or []),
                    "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "").strip(),
                    "task_run_id": str(task_run_id or "").strip(),
                },
            )
        except Exception:
            logger.debug("failed to record turn environment snapshot", exc_info=True)

    def _apply_assistant_message_commit(self, session_id: str, payload: dict[str, Any]):
        self._remove_superseded_stream_failure_boundary(
            session_id=session_id,
            turn_id=str(payload.get("turn_id") or ""),
            answer_source=str(payload.get("answer_source") or ""),
        )
        appended = self.session_manager.append_messages(
            session_id,
            [
                {
                    "role": payload.get("role"),
                    "content": payload.get("content"),
                    "turn_id": payload.get("turn_id"),
                    "task_run_id": payload.get("task_run_id"),
                    "task_id": payload.get("task_id"),
                    "completion_state": payload.get("completion_state"),
                    "terminal_reason": payload.get("terminal_reason"),
                    "image": payload.get("image"),
                    "answer_channel": payload.get("answer_channel"),
                    "answer_source": payload.get("answer_source"),
                    "answer_canonical_state": payload.get("answer_canonical_state"),
                    "answer_persist_policy": payload.get("answer_persist_policy"),
                    "answer_finalization_policy": payload.get("answer_finalization_policy"),
                    "answer_fallback_reason": payload.get("answer_fallback_reason"),
                    "answer_selected_channel": payload.get("answer_selected_channel"),
                    "answer_selected_source": payload.get("answer_selected_source"),
                    "answer_leak_flags": payload.get("answer_leak_flags"),
                }
            ],
        )
        append_api = getattr(self.session_manager, "append_api_messages", None)
        if callable(append_api):
            protocol_messages = [
                dict(item)
                for item in list(payload.get("api_protocol_messages") or [])
                if isinstance(item, dict)
            ]
            if protocol_messages:
                append_api(session_id, protocol_messages)
            else:
                append_api(
                    session_id,
                    [
                        {
                            "role": payload.get("role"),
                            "content": payload.get("content"),
                            "turn_id": payload.get("turn_id"),
                            "reasoning_content": payload.get("reasoning_content"),
                            "tool_calls": payload.get("tool_calls"),
                            "tool_call_id": payload.get("tool_call_id"),
                            "name": payload.get("name"),
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
            memory_environment_context=self._memory_environment_context_for_turn(
                session_id=session_id,
                turn_id=str(payload.get("turn_id") or ""),
                task_run_id=str(payload.get("task_run_id") or ""),
                main_context=main_context,
            ),
            event_coverage=self._event_coverage_for_active_turn(
                session_id=session_id,
                turn_id=str(payload.get("turn_id") or ""),
            ),
        )
        return {
            "appended_messages": appended,
            **self._memory_receipt_commit_payload(receipt),
            "file_work_context_writeback": bool(main_context or task_summary_refs or bundle_summary_refs),
        }

    def _remove_superseded_stream_failure_boundary(self, *, session_id: str, turn_id: str, answer_source: str) -> None:
        if not str(turn_id or "").strip():
            return
        if str(answer_source or "").strip() == "harness.runtime.stream_failure_reconciliation":
            return
        remover = getattr(self.session_manager, "remove_stream_failure_boundary_messages", None)
        if not callable(remover):
            return
        try:
            remover(session_id, turn_id=turn_id)
        except Exception:
            logger.debug("failed to remove superseded stream failure boundary", exc_info=True)

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

    def _session_emphasis_for_turn(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        user_message: str,
        environment_binding: dict[str, Any] | None,
        active_work_context: dict[str, Any] | None,
        recent_work_outcome: dict[str, Any] | None,
        runtime_assembly: Any | None = None,
    ) -> list[dict[str, Any]]:
        store = getattr(self.memory_facade, "session_emphasis", None)
        if store is None:
            return []
        if not should_inject_session_emphasis(
            user_message=user_message,
            active_work_context=active_work_context,
            recent_work_outcome=recent_work_outcome,
        ):
            return []
        environment_context = self._memory_environment_context_for_turn(
            session_id=session_id,
            turn_id=turn_id,
            environment_binding=environment_binding,
            active_work_context=active_work_context,
            recent_work_outcome=recent_work_outcome,
            runtime_assembly=runtime_assembly,
        )
        return list(
            store.render_pinned_facts(
                session_id,
                limit=8,
                task_environment_id=str(environment_context.get("task_environment_id") or ""),
            )
        )

    def _memory_environment_context_for_turn(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        task_run_id: str = "",
        main_context: dict[str, Any] | None = None,
        environment_binding: dict[str, Any] | None = None,
        active_work_context: dict[str, Any] | None = None,
        recent_work_outcome: dict[str, Any] | None = None,
        runtime_assembly: Any | None = None,
    ) -> dict[str, Any]:
        return self.runtime_memory_context_provider.environment_context(
            session_id=session_id,
            turn_id=turn_id,
            task_run_id=task_run_id,
            main_context=main_context,
            environment_binding=environment_binding,
            active_work_context=active_work_context,
            recent_work_outcome=recent_work_outcome,
            runtime_assembly=runtime_assembly,
        )

    async def _runtime_memory_context_for_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
        session_context: dict[str, Any],
        agent_runtime_profile: Any,
        runtime_assembly: Any,
        environment_binding: dict[str, Any] | None,
        active_work_context: dict[str, Any] | None,
        recent_work_outcome: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return await self.runtime_memory_context_provider.for_turn(
            session_id=session_id,
            turn_id=turn_id,
            user_message=user_message,
            session_context=session_context,
            agent_runtime_profile=agent_runtime_profile,
            runtime_assembly=runtime_assembly,
            environment_binding=environment_binding,
            active_work_context=active_work_context,
            recent_work_outcome=recent_work_outcome,
        )

    def _load_recent_api_messages_for_memory(self, session_id: str) -> list[dict[str, Any]]:
        loader = getattr(self.session_manager, "load_session_for_api", None)
        if not callable(loader):
            return []
        try:
            return [
                dict(item)
                for item in list(loader(session_id) or [])
                if isinstance(item, dict)
            ]
        except Exception:
            return []

    async def _runtime_memory_context_for_task_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.runtime_memory_context_provider.for_task_execution(dict(payload or {}))

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


def _active_work_schedule_failure_reply(result: dict[str, Any]) -> str:
    reason = str(result.get("reason") or result.get("error") or "unknown").strip()
    if not reason:
        reason = "unknown"
    return f"当前工作恢复调度没有成功：{reason}。断点已保留；需要先修复这个运行问题，再由 agent 在新的模型轮次中继续处理。"


def _active_work_schedule_failure_payload(result: dict[str, Any]) -> dict[str, Any]:
    reason = str(result.get("reason") or result.get("error") or "unknown").strip() or "unknown"
    return {
        "status": "blocked",
        "terminal_reason": "active_work_schedule_failed",
        "reason": reason,
        "content": _active_work_schedule_failure_reply(result),
    }


def _active_work_resume_failure_reply(result: dict[str, Any]) -> str:
    reason = str(result.get("reason") or result.get("error") or "unknown").strip()
    if not reason:
        reason = "unknown"
    return f"当前工作没有成功恢复：{reason}。断点已保留；如本轮包含补充要求，也已保留。需要先修复这个运行问题，再由 agent 在新的模型轮次中继续处理。"


def _active_work_resume_failure_payload(result: dict[str, Any]) -> dict[str, Any]:
    reason = str(result.get("reason") or result.get("error") or "unknown").strip() or "unknown"
    return {
        "status": "blocked",
        "terminal_reason": "active_work_resume_failed",
        "reason": reason,
        "content": _active_work_resume_failure_reply(result),
    }


def _schedule_result_allows_progress(result: dict[str, Any]) -> bool:
    payload = dict(result or {})
    if not payload.get("ok"):
        return False
    if payload.get("scheduled"):
        return True
    return str(payload.get("reason") or "").strip() == "already_running"


def _task_request_active_work_relationship(action_request: ModelActionRequest) -> str:
    diagnostics = dict(getattr(action_request, "diagnostics", {}) or {})
    seed = dict(getattr(action_request, "task_contract_seed", {}) or {})
    raw = str(
        diagnostics.get("active_work_relationship")
        or seed.get("active_work_relationship")
        or seed.get("lifecycle_intent")
        or diagnostics.get("lifecycle_intent")
        or ""
    ).strip().lower()
    aliases = {
        "replace": "replace_current_work",
        "restart": "replace_current_work",
        "restart_current_work": "replace_current_work",
        "replace_active_work": "replace_current_work",
        "replace_current_task": "replace_current_work",
        "new_task": "new_work",
        "new_current_work": "new_work",
        "independent": "new_work",
        "independent_work": "new_work",
    }
    return aliases.get(raw, raw or "new_task_request")


def _task_run_identity(task_run: Any) -> dict[str, str]:
    return {
        "task_run_id": str(getattr(task_run, "task_run_id", "") or ""),
        "status": str(getattr(task_run, "status", "") or ""),
    }


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


def _request_permission_mode(
    request: HarnessRuntimeRequest,
    *,
    session_record: dict[str, Any] | None = None,
    permission_mode_provider: Any | None = None,
) -> str:
    explicit = str(getattr(request, "permission_mode", "") or "").strip()
    if explicit:
        return normalize_permission_mode(explicit)
    session_state = dict(dict(session_record or {}).get("conversation_state") or {})
    session_mode = str(session_state.get("permission_mode") or "").strip()
    if session_mode:
        return normalize_permission_mode(session_mode)
    if callable(permission_mode_provider):
        provider_mode = str(permission_mode_provider() or "").strip()
        if provider_mode:
            return normalize_permission_mode(provider_mode)
    return "full_access"


def _history_without_current_user_request(
    history: list[dict[str, Any]],
    *,
    turn_id: str,
    user_message: str,
) -> list[dict[str, Any]]:
    target_turn_id = str(turn_id or "").strip()
    target_content = str(user_message or "")
    if not target_turn_id:
        return [dict(item) for item in list(history or []) if isinstance(item, dict)]
    result: list[dict[str, Any]] = []
    for item in list(history or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        item_turn_id = str(item.get("turn_id") or "").strip()
        content = str(item.get("content") or "")
        current_turn_match = item_turn_id == target_turn_id
        compacted_current_request_match = not item_turn_id and bool(target_content) and content == target_content
        is_current_user_request = (
            role == "user"
            and (current_turn_match or compacted_current_request_match)
            and (not target_content or content == target_content)
        )
        if is_current_user_request:
            continue
        result.append(dict(item))
    return result


def _graph_model_override_diagnostics(work_order: Any) -> dict[str, Any]:
    dispatch_context = dict(getattr(work_order, "dispatch_context", {}) or {})
    diagnostics = dispatch_context.get("model_override_diagnostics")
    return dict(diagnostics or {}) if isinstance(diagnostics, dict) else {}


def _refresh_existing_graph_node_task_run(
    *,
    runtime_host: Any,
    graph_config: Any,
    work_order: Any,
    task_run: TaskRun,
    now: float,
) -> TaskRun:
    model_override_diagnostics = _graph_model_override_diagnostics(work_order)
    if not model_override_diagnostics:
        return task_run
    if str(getattr(task_run, "status", "") or "") not in {"created", "waiting_executor"}:
        return task_run

    contract = _graph_node_contract_from_work_order(work_order)
    runtime_contract = _graph_node_runtime_contract(graph_config, work_order)
    contract_ref = runtime_host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    diagnostics.pop("model_selection", None)
    diagnostics["runtime_contract"] = runtime_contract
    diagnostics["contract"] = contract.to_dict()
    diagnostics["graph_model_override"] = model_override_diagnostics
    updated = TaskRun(
        **{
            **task_run.to_dict(),
            "task_contract_ref": contract_ref,
            "updated_at": now,
            "diagnostics": diagnostics,
        }
    )
    runtime_host.state_index.upsert_task_run(updated)
    return runtime_host.state_index.get_task_run(updated.task_run_id) or updated


def _runtime_contract_for_turn(
    *,
    request_runtime_contract: dict[str, Any],
    turn_id: str,
    runtime_profile: dict[str, Any] | None = None,
    active_turn_present: bool = False,
) -> dict[str, Any]:
    profile_payload = {
        **dict(request_runtime_contract.get("runtime_profile") or {}),
        **dict(runtime_profile or {}),
    }
    contract_payload = dict(request_runtime_contract or {})
    if active_turn_present:
        runtime_facts = dict(contract_payload.get("runtime_facts") or {})
        runtime_facts["active_turn_present"] = True
        runtime_facts["active_turn_capability_policy"] = "preserve_user_granted_capabilities"
        contract_payload["runtime_facts"] = runtime_facts
    return {
        **contract_payload,
        "turn_id": turn_id,
        **({"runtime_profile": profile_payload} if profile_payload else {}),
    }


def _continuation_strategy_for_execution(*, decision_strategy: str, context: ActiveWorkContext) -> str:
    strategy = str(decision_strategy or "").strip()
    if strategy in {"same_run_resume", "already_running", "defer", "none"}:
        return strategy
    if context.running:
        return "already_running"
    if context.same_run_allowed or context.resumable:
        return "same_run_resume"
    return "defer"


def _explicit_contract_action_request(
    *,
    request: HarnessRuntimeRequest,
    turn_id: str,
    runtime_assembly: Any,
) -> ModelActionRequest:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    source = _explicit_contract_source_payload(assembly_payload)
    return ModelActionRequest(
        request_id=f"system-explicit-contract:{turn_id}:{uuid.uuid4().hex[:8]}",
        turn_id=turn_id,
        action_type="request_task_run",
        public_progress_note="已接收明确任务合同，正在启动任务。",
        public_action_state={
            "current_judgment": "系统已收到成型任务合同。",
            "next_action": "直接建立任务生命周期。",
            "completion_status": "working",
        },
        task_contract_seed={
            "user_visible_goal": _first_contract_text(
                source.get("user_visible_goal"),
                source.get("user_goal"),
                source.get("objective"),
                source.get("title"),
                request.message,
            ),
            "task_run_goal": _first_contract_text(
                source.get("task_run_goal"),
                source.get("objective"),
                source.get("user_visible_goal"),
                source.get("user_goal"),
                request.message,
            ),
            "completion_criteria": contract_string_tuple(
                source.get("completion_criteria")
                or dict(source.get("output_contract") or {}).get("completion_criteria")
                or dict(source.get("acceptance_policy") or {}).get("completion_criteria")
            ),
        },
        diagnostics={
            "origin_kind": "explicit_contract",
            "origin_authority": "harness.explicit_contract_task",
            "source_contract_ref": str(source.get("contract_id") or source.get("source_ref") or ""),
        },
    )


def _task_run_contract_from_explicit_contract(
    *,
    request: HarnessRuntimeRequest,
    turn_id: str,
    runtime_assembly: Any,
    action_request: ModelActionRequest,
) -> tuple[TaskRunContract | None, list[str]]:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    source = _explicit_contract_source_payload(assembly_payload)
    errors: list[str] = []
    user_visible_goal = _first_contract_text(
        source.get("user_visible_goal"),
        source.get("user_goal"),
        source.get("objective"),
        source.get("title"),
        request.message,
    )
    task_run_goal = _first_contract_text(
        source.get("task_run_goal"),
        source.get("objective"),
        source.get("user_visible_goal"),
        source.get("user_goal"),
        request.message,
    )
    if not user_visible_goal:
        errors.append("task_goal_required")
    if not task_run_goal:
        errors.append("task_run_goal_required")
    output_contract = dict(source.get("output_contract") or {})
    acceptance_policy = dict(source.get("acceptance_policy") or {})
    required_artifacts = contract_dict_tuple(
        source.get("required_artifacts")
        or output_contract.get("required_artifacts")
        or output_contract.get("artifact_requirements")
        or acceptance_policy.get("required_artifacts")
    )
    required_verifications = contract_dict_tuple(
        source.get("required_verifications")
        or output_contract.get("required_verifications")
        or output_contract.get("verification_requirements")
        or acceptance_policy.get("required_verifications")
    )
    completion_criteria = contract_string_tuple(
        source.get("completion_criteria")
        or output_contract.get("completion_criteria")
        or acceptance_policy.get("completion_criteria")
    )
    if not completion_criteria and not required_artifacts and not required_verifications:
        errors.append("completion_evidence_required")
    if errors:
        return None, errors
    runtime_contract = dict(assembly_payload.get("runtime_contract") or {})
    environment = dict(assembly_payload.get("task_environment") or {})
    task_environment_id = str(
        runtime_contract.get("task_environment_id")
        or source.get("task_environment_id")
        or source.get("environment_id")
        or environment.get("environment_id")
        or ""
    ).strip()
    runtime_profile = dict(source.get("runtime_profile") or {})
    if not runtime_profile:
        runtime_profile = dict(dict(source.get("runtime_assembly_plan") or {}).get("runtime_profile") or {})
    runtime_profile = _runtime_profile_with_execution_permit_allowed_operations(
        runtime_profile,
        allowed_operations=_explicit_allowed_operations_for_contract(runtime_contract=runtime_contract, source=source),
    )
    contract = TaskRunContract(
        contract_id=f"task-contract:{uuid.uuid4().hex[:12]}",
        contract_source="explicit_contract",
        user_visible_goal=user_visible_goal,
        task_run_goal=task_run_goal,
        required_artifacts=required_artifacts,
        required_verifications=required_verifications,
        completion_criteria=completion_criteria,
        resource_requirements=dict(
            source.get("resource_requirements")
            or source.get("runtime_requirements")
            or source.get("resource_scope")
            or {}
        ),
        permission_requirements=dict(source.get("permission_requirements") or source.get("tool_scope") or {}),
        acceptance_policy=acceptance_policy,
        recovery_policy=dict(source.get("recovery_policy") or {}),
        created_from_packet_ref=action_request.request_id,
        source_contract_ref=str(source.get("contract_id") or source.get("source_ref") or "").strip(),
        external_plan_ref=str(source.get("plan_id") or source.get("external_plan_ref") or "").strip(),
        task_environment_id=task_environment_id,
        runtime_profile=runtime_profile,
        prompt_contract=dict(source.get("prompt_contract") or {}),
        graph_slot=dict(source.get("graph_slot") or source.get("graph_contract") or {}),
        origin={
            "origin_kind": "explicit_contract",
            "origin_authority": "harness.explicit_contract_task",
            "turn_id": turn_id,
        },
    )
    return contract, []


def _runtime_branch_projection(*, runtime_assembly: Any) -> dict[str, Any]:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    capabilities = dict(assembly_payload.get("control_capabilities") or {})
    if _runtime_is_blocked(assembly_payload):
        return {
            "branch_kind": "blocked_runtime",
            "invocation_kind": "blocked_runtime",
            "dispatch_target": "harness.entrypoint.blocked_runtime",
            "reason": "runtime_assembly_blocked",
            "control_capabilities": capabilities,
            "monitor_policy": {"record_task_monitor": False, "record_turn_monitor": False},
            "diagnostics": {"runtime_status": str(assembly_payload.get("status") or "")},
            "authority": "harness.entrypoint.runtime_branch",
        }
    explicit_contract = _system_issued_explicit_contract_payload(assembly_payload)
    if explicit_contract:
        return {
            "branch_kind": "explicit_contract_task",
            "invocation_kind": "task_execution_start",
            "dispatch_target": "harness.entrypoint.explicit_contract_task",
            "reason": "system_issued_explicit_contract_present",
            "control_capabilities": capabilities,
            "monitor_policy": {"record_task_monitor": True, "record_turn_monitor": False},
            "diagnostics": {
                "explicit_contract_present": True,
                "contract_id": str(explicit_contract.get("contract_id") or explicit_contract.get("source_ref") or ""),
            },
            "authority": "harness.entrypoint.runtime_branch",
        }
    return {
        "branch_kind": "single_agent_turn",
        "invocation_kind": "single_agent_turn",
        "dispatch_target": "harness.entrypoint.single_agent_turn",
        "reason": "default_agent_runtime_turn",
        "control_capabilities": capabilities,
        "monitor_policy": {"record_task_monitor": False, "record_turn_monitor": False},
        "diagnostics": {"explicit_contract_present": False},
        "authority": "harness.entrypoint.runtime_branch",
    }


def _looks_like_chat_task_run(task_run: Any) -> bool:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    return task_run_id.startswith("taskrun:turn:") or task_id.startswith("task:turn:")


def _task_run_id_from_lifecycle_event(event: dict[str, Any]) -> str:
    payload = dict(event or {})
    task_run = dict(payload.get("task_run") or {})
    if task_run:
        return str(task_run.get("task_run_id") or "").strip()
    runtime_event = dict(payload.get("event") or {})
    runtime_payload = dict(runtime_event.get("payload") or {})
    task_run = dict(runtime_payload.get("task_run") or {})
    return str(task_run.get("task_run_id") or "").strip()


def _recent_work_outcome_status(*, status: str, terminal_reason: str) -> bool:
    normalized_status = str(status or "").strip()
    normalized_reason = str(terminal_reason or "").strip()
    if normalized_status in {
        "completed",
        "success",
        "failed",
        "error",
        "aborted",
        "cancelled",
        "canceled",
        "blocked",
        "stopped",
        "user_aborted",
    }:
        return True
    return normalized_reason in {
        "user_aborted",
        "model_call_recovery_required",
        "model_action_protocol_repair_required",
        "task_execution_step_budget_exhausted",
        "task_execution_step_budget_exceeded",
        "task_executor_schedule_failed",
        "background_executor_missing_after_restart",
    }


def _public_status_text(value: Any, *, limit: int = 900) -> str:
    text = public_runtime_progress_summary(value)
    if not text:
        text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _active_turn_steer_action_from_user_message(message: str) -> str:
    text = " ".join(str(message or "").strip().lower().split())
    if not text:
        return ""
    negative_pause = any(marker in text for marker in ("不要暂停", "别暂停", "不用暂停", "不要先停", "别先停"))
    negative_stop = any(marker in text for marker in ("不要停止", "别停止", "不用停止", "不要取消", "别取消", "不用取消", "不要停掉", "别停掉"))
    if not negative_stop and any(marker in text for marker in ("停止", "终止", "取消当前", "取消任务", "停掉", "别做了", "不用做了", "stop", "cancel", "abort")):
        return "stop_active_work"
    if not negative_pause and any(marker in text for marker in ("暂停", "先停", "停一下", "等一下", "缓一缓", "pause")):
        return "pause_active_work"
    if len(text) <= 40 and any(marker in text for marker in ("继续", "接着", "恢复", "继续做", "接着做", "continue", "resume")):
        return "continue_active_work"
    return ""


def _active_turn_steer_status_projection(
    *,
    status: str,
    terminal_reason: str,
    content: str,
) -> tuple[str, str, str, str]:
    normalized_status = str(status or "").strip().lower()
    reason = str(terminal_reason or "").strip()
    detail = str(content or "").strip()
    if normalized_status == "blocked":
        return "当前补充未接入", detail or "当前工作控制未执行。", "warning", "active_turn_steer"
    if reason == "pause_active_work":
        return "已暂停当前工作", detail or "暂停请求已记录。", "done", "work_control"
    if reason == "stop_active_work":
        return "已停止当前工作", detail or "停止请求已记录。", "stopped", "work_control"
    if reason == "continue_active_work":
        return "继续当前工作", detail or "当前工作已进入继续处理流程。", "running", "work_control"
    return "已收到补充要求", detail or "补充要求已进入当前工作队列。", "running", "active_turn_steer"


def _drop_empty_entrypoint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _runtime_is_blocked(assembly_payload: dict[str, Any]) -> bool:
    status = str(assembly_payload.get("status") or "").strip().lower()
    if status in {"blocked", "failed", "invalid"}:
        return True
    diagnostics = dict(assembly_payload.get("diagnostics") or {})
    return bool(diagnostics.get("blocked_runtime") is True or diagnostics.get("runtime_blocked") is True)


def _system_issued_explicit_contract_payload(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_contract = dict(assembly_payload.get("runtime_contract") or {})
    candidates: list[dict[str, Any]] = []
    for key in ("task_contract", "task_contract_seed", "engagement_contract"):
        value = runtime_contract.get(key)
        if isinstance(value, dict) and value:
            candidates.append(dict(value))
    engagement_contract = dict(assembly_payload.get("engagement_contract") or {})
    if engagement_contract:
        candidates.append(engagement_contract)
    if not candidates:
        return {}
    system_issued = bool(runtime_contract.get("system_issued_contract") is True)
    for candidate in candidates:
        if system_issued or candidate.get("system_issued") is True:
            return candidate
    return {}


def _explicit_contract_source_payload(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    return _system_issued_explicit_contract_payload(assembly_payload)


def _explicit_allowed_operations_for_contract(
    *,
    runtime_contract: dict[str, Any],
    source: dict[str, Any],
) -> tuple[str, ...] | None:
    runtime_profile = dict(source.get("runtime_profile") or {})
    if not runtime_profile:
        runtime_profile = dict(dict(source.get("runtime_assembly_plan") or {}).get("runtime_profile") or {})
    source_execution_permit = dict(runtime_profile.get("execution_permit") or {})
    contract_runtime_profile = dict(runtime_contract.get("runtime_profile") or {})
    contract_execution_permit = dict(runtime_contract.get("execution_permit") or {})
    contract_runtime_execution_permit = dict(contract_runtime_profile.get("execution_permit") or {})
    permission_requirements = dict(source.get("permission_requirements") or source.get("tool_scope") or {})
    operation_requirement = dict(source.get("operation_requirement") or {})
    operations: list[str] = []
    seen: set[str] = set()
    for value in (
        runtime_contract.get("allowed_operations"),
        contract_execution_permit.get("allowed_operations"),
        contract_runtime_profile.get("allowed_operations"),
        contract_runtime_execution_permit.get("allowed_operations"),
        source.get("allowed_operations"),
        source_execution_permit.get("allowed_operations"),
        permission_requirements.get("allowed_operations"),
        operation_requirement.get("allowed_operations"),
        operation_requirement.get("required_operations"),
        operation_requirement.get("optional_operations"),
    ):
        for operation in contract_string_tuple(value):
            if operation in seen:
                continue
            seen.add(operation)
            operations.append(operation)
    return tuple(operations) if operations else None


def _runtime_profile_with_execution_permit_allowed_operations(
    runtime_profile: dict[str, Any],
    *,
    allowed_operations: tuple[str, ...] | None,
) -> dict[str, Any]:
    if allowed_operations is None:
        return dict(runtime_profile or {})
    profile = dict(runtime_profile or {})
    execution_permit = dict(profile.get("execution_permit") or {})
    execution_permit["allowed_operations"] = list(allowed_operations)
    profile["execution_permit"] = execution_permit
    return profile


def _first_contract_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
