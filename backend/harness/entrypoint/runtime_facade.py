from __future__ import annotations

from dataclasses import replace
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from observability import build_debug_trace_event, start_turn_trace
from capability_system.tools.authorization import build_tool_authorization_index
from graph_system.facade import GraphSystem
from harness.receipt_payload import receipt_payload
from harness.continuation import (
    select_session_continuation,
)
from harness.runtime import AgentRuntimeServices, RuntimeCompiler, SingleAgentRuntimeHost, assemble_runtime
from harness.runtime.request_facts import build_turn_input_facts
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.output_commit_authority import OutputCommitAuthority, OutputCommitRequest, OutputCommitResult
from harness.entrypoint.current_work_boundary import (
    CurrentWorkBoundaryDecision,
    CurrentWorkBoundaryReceipt,
    build_current_work_boundary_input,
    current_work_boundary_receipt_from_decision,
    decide_current_work_boundary,
)
from runtime import ModelResponseRuntimeExecutor, ModelRuntimeError, ToolRuntimeExecutor
from runtime.context_management.session_compaction import auto_compact_session_if_needed, compact_session_history
from runtime.shared.history_assembler import assemble_runtime_history
from runtime.turn_memory import build_prior_work_memory_context, build_turn_memory_recovery_context
from permissions.policy import normalize_permission_mode
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from capability_system.catalog_projection import build_base_unit_catalog
from harness.task_run_contract_normalization import contract_dict_tuple, contract_string_tuple
from harness.runtime.commit_gate import build_user_message_commit_decision
from core.project_layout import ProjectLayout
from harness.entrypoint.models import HarnessRuntimeRequest
from api.chat_direct_routes import run_direct_system_route
from harness.loop.active_work import (
    ActiveWorkContext,
    active_work_control_denial_observation,
    active_work_turn_decision_from_payload,
    default_reply_for_action,
)
from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.model_action_runtime import call_model_invoker
from harness.loop.execution_kernel import (
    append_action_lifecycle_event,
    build_action_lifecycle_event_record,
    decide_model_action_lifecycle,
)
from harness.loop.presentation import error_event, final_answer_event, turn_completed_event
from harness.loop.single_agent_turn import run_single_agent_turn
from harness.entrypoint.task_mode_slash_command import TaskModeSlashSignal, task_mode_slash_signal_from_message
from harness.entrypoint.graph_node_work_order_bridge import GraphNodeWorkOrderBridge
from harness.entrypoint.task_environment_episode_bridge import TaskEnvironmentEpisodeBridge
from harness.loop.task_lifecycle import (
    TaskRunContract,
    contract_from_action_request,
)
from task_system.work_environments.models import SessionTaskBinding, stable_task_environment_id
from task_system.work_environments.repository import TaskEnvironmentRepository
from task_system.work_environments.scheduler import TaskScheduler
from task_system.work_environments.service import TaskWorkEnvironmentService
from task_system.work_environments.view_service import TaskEnvironmentViewService
from graph_system.runtime_effect_registry import handle_runtime_algorithm_effects
from memory_system.runtime_context_provider import RuntimeMemoryContextProvider, should_inject_session_emphasis
from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response

logger = logging.getLogger(__name__)

DEFAULT_INTERACTIVE_AGENT_PROFILE_ID = "main_interactive_agent"

class HarnessRuntimeFacade:
    """Thin API adapter for the agent runtime chain.

    The old query layer used to own planning, tool routing, worker coordination,
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
            recent_messages_loader=self._load_recent_provider_protocol_messages_for_memory,
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
        self._retrieval_service = retrieval_service
        self._evidence_orchestrator_enabled = retrieval_enabled
        self._evidence_orchestrator = None
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
        attach_turn_memory = getattr(self.model_runtime, "attach_turn_memory_store", None)
        if callable(attach_turn_memory):
            attach_turn_memory(self.single_agent_runtime_host.turn_memory_store)
        self.agent_runtime_services = AgentRuntimeServices.from_runtime_host(
            self.single_agent_runtime_host,
            execute_graph_agent_work_order_callback=self._execute_graph_agent_work_order,
            model_runtime=self.model_runtime,
            tool_runtime_executor=self.tool_runtime_executor,
            tool_instances=tuple(self._all_tool_instances()),
            agent_runtime_profile_resolver=self.agent_runtime_registry.get_profile,
            runtime_algorithm_effect_sink=self._handle_runtime_algorithm_effects,
        )
        self.graph_system = GraphSystem(
            services=self.agent_runtime_services,
        )
        self.single_agent_runtime_host.run_monitor_service.attach_graph_system(self.graph_system)
        self.runtime_components = {
            "harness.entrypoint": "application_runtime_facade",
            "graph_system": "active",
            "evidence_orchestrator": "active" if retrieval_enabled else "disabled_missing_retrieval_service",
            "task_environment_episode_bridge": "active",
            "graph_node_work_order_bridge": "active",
        }

    def _handle_runtime_algorithm_effects(
        self,
        *,
        effect_requests: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        graph_config: Any,
        graph_state: Any,
        node_result: Any,
    ) -> dict[str, Any]:
        return handle_runtime_algorithm_effects(
            effect_requests=effect_requests,
            graph_config=graph_config,
            graph_state=graph_state,
            node_result=node_result,
            backend_dir=self.base_dir,
        )

    async def execute_task_environment_episode(
        self,
        *,
        task_environment_id: str,
        episode_id: str = "",
        max_steps: int = 12,
    ) -> dict[str, Any]:
        return await TaskEnvironmentEpisodeBridge(self).execute(
            task_environment_id=task_environment_id,
            episode_id=episode_id,
            max_steps=max_steps,
        )

    async def _execute_graph_agent_work_order(
        self,
        *,
        graph_config: Any,
        work_order: Any,
        max_steps: int = 12,
    ) -> dict[str, Any]:
        return await GraphNodeWorkOrderBridge(self).execute(
            graph_config=graph_config,
            work_order=work_order,
            max_steps=max_steps,
        )

    @property
    def evidence_orchestrator(self):
        if not self._evidence_orchestrator_enabled:
            return None
        if self._evidence_orchestrator is None:
            self._evidence_orchestrator = self._build_evidence_orchestrator()
        return self._evidence_orchestrator

    def _build_evidence_orchestrator(self):
        from evidence.orchestrator import EvidenceOrchestrator
        from evidence.office_document_worker import OfficeDocumentWorker
        from evidence.output_policy import RAGEvidenceOutputPolicy
        from evidence.pdf_worker import PDFWorker
        from evidence.retrieval_worker import RetrievalWorker
        from evidence.structured_data_worker import StructuredDataWorker

        return EvidenceOrchestrator(
            retrieval_worker=RetrievalWorker(retrieval_service=self._retrieval_service),
            pdf_worker=PDFWorker(root_dir=self.base_dir),
            structured_data_worker=StructuredDataWorker(root_dir=self.base_dir),
            office_document_worker=OfficeDocumentWorker(root_dir=self.base_dir),
            output_policy=RAGEvidenceOutputPolicy(model_runtime=self.model_runtime),
        )

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

    def _context_recovery_package_for_session(
        self,
        session_id: str,
        *,
        raw_messages: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    ) -> dict[str, Any]:
        conversation_continuity = getattr(getattr(self, "memory_facade", None), "conversation_continuity", None)
        manager_factory = getattr(conversation_continuity, "manager", None)
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
        if not isinstance(payload, dict) or not payload:
            return {}
        validator = getattr(manager, "validate_compaction_state", None)
        if callable(validator):
            try:
                validation = validator(list(raw_messages or []))
            except Exception:
                logger.debug("failed to validate context recovery package freshness", exc_info=True)
                return {}
            if not bool(dict(validation or {}).get("ok")):
                return {}
        return dict(payload)

    def _context_recovery_package_allowed_for_record(self, history_record: dict[str, Any]) -> bool:
        record = dict(history_record or {})
        return bool(str(record.get("compressed_context") or "").strip()) or (
            _safe_compaction_boundary_timestamp(record.get("provider_protocol_compaction_created_at")) > 0
        )

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
        provider_protocol_timeline_loader = getattr(self.session_manager, "load_provider_protocol_timeline", None)
        provider_protocol_timeline = (
            provider_protocol_timeline_loader(session_id)
            if callable(provider_protocol_timeline_loader)
            else list(raw_history or [])
        )
        if exclude_current_user_turn_id:
            provider_protocol_timeline = _history_without_current_user_request(
                list(provider_protocol_timeline or []),
                turn_id=exclude_current_user_turn_id,
                user_message=exclude_current_user_message,
            )
        history_assembly = assemble_runtime_history(
            history=raw_history,
            compressed_context=str(history_record.get("compressed_context") or ""),
        )
        session_context = dict(base_session_context or {})
        session_context["compressed_context"] = history_assembly.compressed_context
        session_context["provider_protocol_timeline"] = [
            dict(item)
            for item in list(provider_protocol_timeline or [])
            if isinstance(item, dict)
        ]
        session_context = _attach_fork_snapshot_to_session_context(session_context, history_record)
        context_recovery_package = (
            self._context_recovery_package_for_session(
                session_id,
                raw_messages=list(history_record.get("messages") or []),
            )
            if self._context_recovery_package_allowed_for_record(history_record)
            else {}
        )
        if context_recovery_package:
            session_context["context_recovery_package"] = context_recovery_package
        else:
            session_context.pop("context_recovery_package", None)
        provider_protocol_compaction_created_at = _safe_compaction_boundary_timestamp(
            history_record.get("provider_protocol_compaction_created_at")
        )
        if provider_protocol_compaction_created_at > 0:
            session_context["provider_protocol_compaction_created_at"] = provider_protocol_compaction_created_at
        else:
            session_context.pop("provider_protocol_compaction_created_at", None)
        compaction_generation = str(history_record.get("compaction_generation") or "0").strip() or "0"
        session_context["compaction_generation"] = compaction_generation
        compaction_generation_updated_at = _safe_compaction_boundary_timestamp(
            history_record.get("compaction_generation_updated_at")
        )
        if compaction_generation_updated_at > 0:
            session_context["compaction_generation_updated_at"] = compaction_generation_updated_at
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

    def prepare_chat_run_request_for_schedule(self, request: HarnessRuntimeRequest, *, stream_run_id: str) -> HarnessRuntimeRequest:
        runtime_profile = request.runtime_profile_payload()
        if str(runtime_profile.get("precommitted_user_message_turn_id") or "").strip():
            return request
        history_record = self.session_manager.load_session_record(request.session_id)
        turn_id = _next_session_turn_id(
            request.session_id,
            history_record=history_record,
            turn_memory_store=self.single_agent_runtime_host.turn_memory_store,
        )
        message_id = str(getattr(request, "client_message_id", "") or "").strip() or f"user:{stream_run_id}"
        attachments = _normalized_turn_attachments(getattr(request, "attachments", []) or [])
        self._commit_user_message(
            session_id=request.session_id,
            content=request.message,
            provider_protocol_content=str(request.message or ""),
            attachments=attachments,
            turn_id=turn_id,
            message_id=message_id,
            client_message_id=str(getattr(request, "client_message_id", "") or "").strip(),
            source="harness.entrypoint.chat_run_schedule",
        )
        return replace(
            request,
            runtime_profile={
                **runtime_profile,
                "precommitted_user_message": True,
                "precommitted_user_message_turn_id": turn_id,
                "precommitted_user_message_id": message_id,
                "precommitted_user_message_source": "harness.entrypoint.chat_run_schedule",
                "precommitted_user_message_defer_auto_compaction": not bool(request.history),
                "precommitted_user_message_auto_compaction": {
                    "applied": False,
                    "strategy": "deferred_to_agent_worker" if not request.history else "none",
                    "skipped_reason": "deferred_to_agent_worker" if not request.history else "explicit_history",
                },
            },
        )

    async def astream(self, request: HarnessRuntimeRequest):
        request_runtime_profile = request.runtime_profile_payload()
        model_user_message = str(request.message or "")
        precommitted_turn_id = str(request_runtime_profile.get("precommitted_user_message_turn_id") or "").strip()
        history_record = self.session_manager.load_session_record(request.session_id)
        auto_compaction: dict[str, Any] = {}
        if precommitted_turn_id:
            defer_auto_compaction = bool(request_runtime_profile.get("precommitted_user_message_defer_auto_compaction"))
            if defer_auto_compaction and not request.history:
                auto_compaction = auto_compact_session_if_needed(
                    self,
                    session_id=request.session_id,
                    reason="auto_context_replacement_before_model_turn",
                )
                if bool(auto_compaction.get("applied")):
                    history_record = self.session_manager.load_session_record(request.session_id)
            else:
                auto_compaction = dict(request_runtime_profile.get("precommitted_user_message_auto_compaction") or {})
            if not auto_compaction:
                auto_compaction = {
                    "applied": False,
                    "strategy": "none",
                    "skipped_reason": "precommitted_user_message",
                }
        elif not request.history:
            auto_compaction = auto_compact_session_if_needed(
                self,
                session_id=request.session_id,
                reason="auto_context_replacement_before_model_turn",
            )
            if bool(auto_compaction.get("applied")):
                history_record = self.session_manager.load_session_record(request.session_id)
        raw_history = request.history or self.session_manager.load_session_for_agent(request.session_id)
        if precommitted_turn_id:
            raw_history = _history_without_current_user_request(
                list(raw_history or []),
                turn_id=precommitted_turn_id,
                user_message=model_user_message,
            )
        provider_protocol_timeline_loader = getattr(self.session_manager, "load_provider_protocol_timeline", None)
        provider_protocol_timeline = (
            provider_protocol_timeline_loader(request.session_id)
            if callable(provider_protocol_timeline_loader) and not request.history
            else list(raw_history or [])
        )
        if precommitted_turn_id:
            provider_protocol_timeline = _history_without_current_user_request(
                list(provider_protocol_timeline or []),
                turn_id=precommitted_turn_id,
                user_message=model_user_message,
            )
        history_assembly = assemble_runtime_history(
            history=raw_history,
            compressed_context=str(history_record.get("compressed_context") or ""),
        )
        history = [dict(item) for item in history_assembly.model_history]
        session_context = {
            "compressed_context": history_assembly.compressed_context,
            "provider_protocol_timeline": [dict(item) for item in list(provider_protocol_timeline or []) if isinstance(item, dict)],
        }
        session_context = _attach_fork_snapshot_to_session_context(session_context, history_record)
        context_recovery_package = (
            self._context_recovery_package_for_session(
                request.session_id,
                raw_messages=list(history_record.get("messages") or []),
            )
            if self._context_recovery_package_allowed_for_record(history_record)
            else {}
        )
        if context_recovery_package:
            session_context["context_recovery_package"] = context_recovery_package
        provider_protocol_compaction_created_at = _safe_compaction_boundary_timestamp(
            history_record.get("provider_protocol_compaction_created_at")
        )
        if provider_protocol_compaction_created_at > 0:
            session_context["provider_protocol_compaction_created_at"] = provider_protocol_compaction_created_at
        compaction_generation = str(history_record.get("compaction_generation") or "0").strip() or "0"
        session_context["compaction_generation"] = compaction_generation
        compaction_generation_updated_at = _safe_compaction_boundary_timestamp(
            history_record.get("compaction_generation_updated_at")
        )
        if compaction_generation_updated_at > 0:
            session_context["compaction_generation_updated_at"] = compaction_generation_updated_at
        conversation_state = dict(history_record.get("conversation_state") or {})
        project_binding = dict(conversation_state.get("project_binding") or {})
        if project_binding:
            session_context["project_binding"] = project_binding
        editor_context = request.editor_context_payload()
        if editor_context:
            session_context["editor_context"] = editor_context
        attachments = _normalized_turn_attachments(getattr(request, "attachments", []) or [])
        if attachments:
            session_context["turn_input_attachments"] = attachments
        semantic_request = replace(request, message=model_user_message)
        turn_id = precommitted_turn_id or _next_session_turn_id(
            request.session_id,
            history_record=history_record,
            turn_memory_store=self.single_agent_runtime_host.turn_memory_store,
        )
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
                provider_protocol_content=model_user_message,
                attachments=attachments,
                turn_id=turn_id,
                message_id=str(
                    request_runtime_profile.get("precommitted_user_message_id")
                    or getattr(request, "client_message_id", "")
                    or ""
                ).strip(),
                client_message_id=str(getattr(request, "client_message_id", "") or "").strip(),
            )
            if active_turn is None:
                self.single_agent_runtime_host.active_turn_registry.start(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    stream_run_id=str(request_runtime_profile.get("stream_run_id") or ""),
                    state="starting",
                )
                started_active_turn_id = turn_id
            with start_turn_trace(
                session_id=request.session_id,
                user_message=model_user_message,
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
                active_work_context_payload = active_work_context.to_dict() if active_work_context is not None else {}
                agent_runtime_profile = self._resolve_request_agent_runtime_profile(request)
                request_environment_binding = request.environment_binding_payload()
                request_runtime_contract = request.runtime_contract_payload()
                request_model_selection = request.model_selection_payload()
                runtime_contract = _runtime_contract_for_turn(
                    request_runtime_contract=request_runtime_contract,
                    turn_id=turn_id,
                    runtime_profile=request_runtime_profile,
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
                    model_selection=request_model_selection,
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

                slash_task_signal = task_mode_slash_signal_from_message(request.message, turn_id=turn_id)
                runtime_branch = _runtime_branch_projection(runtime_assembly=runtime_assembly)
                if slash_task_signal is not None:
                    runtime_branch = _slash_task_action_runtime_branch(slash_task_signal)
                continuation_selection = select_session_continuation(
                    self.single_agent_runtime_host,
                    session_id=request.session_id,
                    active_work_present=active_work_context is not None,
                )
                turn_memory_recovery_context = build_turn_memory_recovery_context(
                    self.single_agent_runtime_host.turn_memory_store,
                    session_id=request.session_id,
                )
                prior_work_memory_context = (
                    build_prior_work_memory_context(
                        self.single_agent_runtime_host.turn_memory_store,
                        session_id=request.session_id,
                    )
                    if active_work_context is None
                    else {}
                )
                if turn_memory_recovery_context:
                    selection_payload = continuation_selection.to_dict()
                    selection_payload["turn_memory_recovery"] = {
                        "selected_turn_id": str(turn_memory_recovery_context.get("previous_turn_id") or ""),
                        "decision": dict(turn_memory_recovery_context.get("recovery_decision") or {}),
                        "authority": str(turn_memory_recovery_context.get("authority") or ""),
                    }
                    session_context["continuation_selection"] = selection_payload
                if turn_memory_recovery_context:
                    session_context["turn_memory_recovery"] = turn_memory_recovery_context
                if prior_work_memory_context:
                    session_context["prior_work_memory_context"] = prior_work_memory_context
                recent_work_outcome: dict[str, Any] = {}
                if active_work_context is None:
                    recent_work_outcome = self._recent_work_outcome_from_latest_task_environment(request.session_id)
                    if recent_work_outcome:
                        session_context["recent_work_outcome"] = recent_work_outcome
                turn_input_facts = build_turn_input_facts(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    user_message=model_user_message,
                    expected_active_turn_id=str(getattr(request, "expected_active_turn_id", "") or "").strip(),
                    active_turn_input_policy=str(getattr(request, "active_turn_input_policy", "") or "auto").strip() or "auto",
                    expected_continuation_id=str(getattr(request, "expected_continuation_id", "") or "").strip(),
                    recovery_input_policy=str(getattr(request, "recovery_input_policy", "") or "auto").strip() or "auto",
                    active_turn=active_turn,
                    active_work_candidate=active_work_context,
                    recent_work_outcome_candidate=recent_work_outcome,
                    environment_binding=request_environment_binding,
                    runtime_profile=request_runtime_profile,
                    editor_context=editor_context,
                )
                session_context["turn_id"] = turn_id
                session_context["turn_input_facts"] = turn_input_facts.to_dict()
                current_work_decision, current_work_receipt = await self._decide_current_work_boundary_for_turn(
                    request=semantic_request,
                    turn_id=turn_id,
                    turn_input_facts=turn_input_facts,
                    active_work_context=active_work_context,
                    runtime_branch=runtime_branch,
                    runtime_assembly=runtime_assembly,
                    model_selection=request_model_selection,
                )
                session_context["current_work_boundary_receipt"] = current_work_receipt.to_dict()
                yield {
                    "type": "current_work_boundary_decided",
                    "decision": current_work_decision.to_dict(),
                    "receipt": current_work_receipt.to_dict(),
                }
                session_emphasis = self._session_emphasis_for_turn(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    user_message=model_user_message,
                    environment_binding=request_environment_binding,
                    active_work_context=active_work_context_payload,
                    recent_work_outcome=recent_work_outcome,
                    runtime_assembly=runtime_assembly,
                )
                if session_emphasis:
                    session_context["session_emphasis"] = session_emphasis
                memory_context = await self._runtime_memory_context_for_turn(
                    session_id=request.session_id,
                    turn_id=turn_id,
                    user_message=model_user_message,
                    session_context=session_context,
                    agent_runtime_profile=agent_runtime_profile,
                    runtime_assembly=runtime_assembly,
                    environment_binding=request_environment_binding,
                    active_work_context=active_work_context_payload,
                    recent_work_outcome=recent_work_outcome,
                )
                if memory_context:
                    session_context["memory_context"] = memory_context
                yield {
                    "type": "runtime_branch_decided",
                    "runtime_branch": runtime_branch,
                }
                if runtime_branch.get("branch_kind") == "slash_task_action_signal":
                    async for event in self._run_slash_task_action_signal(
                        request=semantic_request,
                        turn_id=turn_id,
                        runtime_assembly=runtime_assembly,
                        runtime_branch=runtime_branch,
                        agent_runtime_profile=agent_runtime_profile,
                        slash_task_signal=slash_task_signal,
                        current_work_boundary_receipt=current_work_receipt.to_dict(),
                    ):
                        yield event
                    return
                if runtime_branch.get("branch_kind") == "single_agent_turn":
                    async for event in self._run_single_agent_turn(
                        request=semantic_request,
                        turn_id=turn_id,
                        history=history,
                        session_context=session_context,
                        agent_invocation_id=agent_invocation_id,
                        agent_runtime_profile=agent_runtime_profile,
                        runtime_assembly=runtime_assembly,
                        runtime_branch=runtime_branch,
                        active_work_context=active_work_context,
                        current_work_boundary_receipt=current_work_receipt.to_dict(),
                    ):
                        yield event
                    return
                if runtime_branch.get("branch_kind") == "explicit_contract_task":
                    async for event in self._run_explicit_contract_task_turn(
                        request=semantic_request,
                        turn_id=turn_id,
                        history=history,
                        session_context=session_context,
                        agent_invocation_id=agent_invocation_id,
                        agent_runtime_profile=agent_runtime_profile,
                        runtime_assembly=runtime_assembly,
                        runtime_branch=runtime_branch,
                        active_work_context=active_work_context,
                        current_work_boundary_receipt=current_work_receipt.to_dict(),
                    ):
                        yield event
                    return
                if runtime_branch.get("branch_kind") == "blocked_runtime":
                    blocked_content = "当前运行环境未能完成装配，无法继续执行本轮请求。"
                    commit_result = await self._commit_facade_assistant_output(
                        request=semantic_request,
                        turn_id=turn_id,
                        content=blocked_content,
                        answer_source="harness.entrypoint.blocked_runtime",
                        execution_posture="runtime_blocked",
                        terminal_reason=str(runtime_branch.get("reason") or "runtime_assembly_blocked"),
                    )
                    output_content = commit_result.decision.content
                    yield error_event(
                        content=output_content,
                        code="blocked_runtime",
                        reason=str(runtime_branch.get("reason") or "runtime_assembly_blocked"),
                        extra={
                            "runtime_branch": dict(runtime_branch or {}),
                            "answer_source": "harness.entrypoint.blocked_runtime",
                            "answer_persist_policy": (
                                "assistant_message_committed"
                                if commit_result.receipt.get("state") == "committed"
                                else "assistant_message_not_committed"
                            ),
                            "answer_finalization_policy": "fail_closed_visible_message",
                            "diagnostics": {
                                "runtime_unavailable": True,
                                "runtime_branch": dict(runtime_branch or {}),
                            },
                        },
                    )
                    return

                yield error_event(
                    content="运行中断",
                    code="runtime_branch_unhandled",
                    reason=str(runtime_branch.get("branch_kind") or ""),
                    extra={
                        "runtime_branch": dict(runtime_branch or {}),
                        "answer_persist_policy": "runtime_status_only",
                        "answer_finalization_policy": "no_agent_answer_runtime_unavailable",
                    },
                )
                return
        except Exception as exc:
            logger.exception("HarnessRuntimeFacade failed while streaming request.")
            self._release_transient_active_turn(
                session_id=request.session_id,
                turn_id=turn_id,
                terminal_reason="harness.entrypoint_error",
            )
            yield error_event(
                content="运行中断",
                code=exc.code if isinstance(exc, ModelRuntimeError) else "harness_entrypoint_error",
                reason=str(exc) or type(exc).__name__,
                extra={
                    "answer_persist_policy": "runtime_status_only",
                    "answer_finalization_policy": "no_agent_answer_runtime_unavailable",
                    "diagnostics": {
                        "exception_type": type(exc).__name__,
                        "runtime_unavailable": True,
                    },
                },
            )
        finally:
            if started_active_turn_id:
                self._release_transient_active_turn(
                    session_id=request.session_id,
                    turn_id=started_active_turn_id,
                    terminal_reason="turn_stream_closed",
                )

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
        current_work_boundary_receipt: dict[str, Any],
        max_steps: int | None = None,
    ):
        async def start_task(action_request: ModelActionRequest, start_context_handoff: dict[str, Any]):
            for event in _task_environment_receipt_events(
                base_dir=self.base_dir,
                session_id=request.session_id,
                turn_id=turn_id,
                action_request=action_request,
                runtime_branch=runtime_branch,
                source="harness.single_agent_turn.request_task_run",
            ):
                yield event

        async def apply_active_work_control(action_request: ModelActionRequest):
            async for event in self._apply_task_environment_active_work_control(
                request=request,
                turn_id=turn_id,
                action_request=action_request,
                active_work_context=active_work_context,
                runtime_branch=runtime_branch,
            ):
                yield event

        async for event in run_single_agent_turn(
            session_id=request.session_id,
            turn_id=turn_id,
            user_message=request.message,
            history=history,
            session_context=session_context,
            agent_invocation_id=agent_invocation_id,
            agent_runtime_profile=agent_runtime_profile,
            model_selection=request.model_selection_payload(),
            runtime_assembly=runtime_assembly,
            runtime_host=self.single_agent_runtime_host,
            runtime_branch=runtime_branch,
            active_work_context=active_work_context,
            current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
            model_runtime=getattr(self.model_response_executor, "model_runtime", None),
            commit_assistant_message=self._apply_assistant_message_commit_async,
            stream_run_id=request.stream_run_id(),
            start_task_from_action_request=start_task,
            apply_active_work_control=apply_active_work_control if active_work_context is not None else None,
            compact_session_context=self._compact_session_context_for_single_agent_followup,
            max_tool_iterations=max_steps,
        ):
            yield event

    async def _commit_facade_assistant_output(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        content: str,
        answer_source: str,
        execution_posture: str,
        terminal_reason: str,
        answer_channel: str = "conversation",
        run_id: str = "",
        task_run_id: str = "",
        task_id: str = "",
        completion_state: str = "",
        refs: dict[str, Any] | None = None,
    ) -> OutputCommitResult:
        commit_request = OutputCommitRequest(
            run_id=str(run_id or turn_id or request.session_id or "runtime-facade-output"),
            session_id=request.session_id,
            turn_id=turn_id,
            task_run_id=str(task_run_id or ""),
            task_id=str(task_id or ""),
            content=str(content or ""),
            answer_channel=answer_channel,
            answer_source=answer_source,
            execution_posture=execution_posture,
            completion_state=completion_state,
            terminal_reason=terminal_reason,
            commit_source="harness.entrypoint.runtime_facade",
            refs={
                "session_ref": request.session_id,
                "turn_ref": turn_id,
                **dict(refs or {}),
            },
        )
        return await OutputCommitAuthority(self.single_agent_runtime_host).commit_async(
            commit_request,
            committer=self._apply_assistant_message_commit_async,
        )

    async def _decide_current_work_boundary_for_turn(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        turn_input_facts: Any,
        active_work_context: ActiveWorkContext | None,
        runtime_branch: dict[str, Any],
        runtime_assembly: Any,
        model_selection: dict[str, Any],
    ) -> tuple[CurrentWorkBoundaryDecision, CurrentWorkBoundaryReceipt]:
        assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
        profile_payload = dict(assembly_payload.get("profile") or {})
        expected_turn_id = str(getattr(request, "expected_active_turn_id", "") or "").strip()
        request_policy = str(getattr(request, "active_turn_input_policy", "") or "auto").strip().lower() or "auto"
        active_turn_check = self.single_agent_runtime_host.active_turn_registry.compare_and_update_current_turn(
            session_id=request.session_id,
            expected_turn_id=expected_turn_id,
        )
        boundary_input = build_current_work_boundary_input(
            turn_input_facts=turn_input_facts,
            active_turn_record=dict(active_turn_check.get("record") or {}),
            active_turn_check=active_turn_check,
            active_work_context=active_work_context,
            request_active_turn_policy=request_policy,
            active_turn_input_policy=request_policy,
            expected_active_turn_id=expected_turn_id,
            runtime_branch=runtime_branch,
            control_capabilities=dict(assembly_payload.get("control_capabilities") or {}),
            context_policy=dict(profile_payload.get("context_policy") or {}),
            editor_context_summary=request.editor_context_payload(),
        )
        decision = decide_current_work_boundary(boundary_input)
        receipt = current_work_boundary_receipt_from_decision(decision)
        return decision, receipt

    async def _run_slash_task_action_signal(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        runtime_assembly: Any,
        runtime_branch: dict[str, Any],
        agent_runtime_profile: Any,
        slash_task_signal: TaskModeSlashSignal | None,
        current_work_boundary_receipt: dict[str, Any],
    ):
        signal = slash_task_signal
        if signal is None or signal.action_request is None:
            diagnostics = dict(signal.diagnostics if signal is not None else {})
            errors = list(diagnostics.get("validation_errors") or [])
            content = "任务命令没有形成合格的 request_task_run 动作信号，任务未启动。"
            yield {
                "type": "runtime_status",
                "title": "任务命令未执行",
                "detail": content,
                "state": "blocked",
                "phase": "slash_task_action_signal",
                "terminal_reason": "slash_task_action_invalid",
                "contract_errors": errors,
                "runtime_branch": dict(runtime_branch or {}),
                "diagnostics": diagnostics,
            }
            yield error_event(
                content=content,
                code="slash_task_action_invalid",
                reason=";".join(str(item) for item in errors if str(item)) or "slash_task_action_invalid",
                extra={
                    "runtime_branch": dict(runtime_branch or {}),
                    "diagnostics": diagnostics,
                    "answer_source": "harness.entrypoint.slash_task_action_signal",
                    "answer_persist_policy": "runtime_status_only",
                    "answer_finalization_policy": "fail_closed_visible_message",
                },
            )
            return

        action_request = signal.action_request
        packet_ref = f"slash-task-command:{turn_id}"
        launch_runtime_assembly = _runtime_assembly_with_task_launch_supervision(runtime_assembly)
        lifecycle = decide_model_action_lifecycle(
            action_request,
            packet_allowed_action_types=("request_task_run",),
            invocation_kind="slash_task_command",
            permit_invocation_kind="agent_turn",
            packet_ref=packet_ref,
            definitions_by_name=getattr(getattr(self.single_agent_runtime_host, "tool_authorization_index", None), "definitions_by_name", {}),
            allowed_tool_names=set(),
            runtime_profile=_runtime_profile_payload_from_assembly(launch_runtime_assembly),
            permission_mode=_runtime_permission_mode_from_assembly(launch_runtime_assembly),
            current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
            session_id=request.session_id,
            turn_id=turn_id,
            grant_scope="turn",
        )
        event = _append_model_action_admission_event(
            self.single_agent_runtime_host,
            action_request=action_request,
            lifecycle=lifecycle,
            run_id=turn_id,
            packet_ref=packet_ref,
            session_id=request.session_id,
            turn_id=turn_id,
            extra_payload={
                "slash_task_signal": signal.to_dict(),
                "runtime_branch": dict(runtime_branch or {}),
            },
        )
        yield {"type": "model_action_request", "model_action_request": action_request.to_dict()}
        yield {"type": "model_action_admission", "event": event}

        admission = lifecycle.admission
        if admission.decision != "allow":
            content = str(admission.user_visible_reason or admission.system_reason or "任务动作信号未通过准入，任务未启动。").strip()
            yield {
                "type": "runtime_status",
                "title": "任务动作未通过准入",
                "detail": content,
                "state": "blocked",
                "phase": "slash_task_action_signal",
                "terminal_reason": str(admission.system_reason or admission.decision),
                "admission": admission.to_dict(),
                "runtime_branch": dict(runtime_branch or {}),
            }
            yield error_event(
                content=content,
                code=str(admission.system_reason or "slash_task_admission_denied"),
                reason=str(admission.system_reason or admission.decision),
                extra={
                    "admission": admission.to_dict(),
                    "model_action_request": action_request.to_dict(),
                    "runtime_branch": dict(runtime_branch or {}),
                    "answer_source": "harness.entrypoint.slash_task_action_signal",
                    "answer_persist_policy": "runtime_status_only",
                    "answer_finalization_policy": "fail_closed_visible_message",
                },
            )
            return

        for event in _task_environment_receipt_events(
            base_dir=self.base_dir,
            session_id=request.session_id,
            turn_id=turn_id,
            action_request=action_request,
            runtime_branch=runtime_branch,
            source="harness.slash_task_command.request_task_run",
        ):
            yield event

    async def _run_explicit_contract_task_turn(
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
        current_work_boundary_receipt: dict[str, Any],
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
            errors = [str(item or "").strip() for item in list(contract_errors or []) if str(item or "").strip()]
            yield {
                "type": "runtime_status",
                "title": "显式任务合同无效",
                "detail": "显式任务合同缺少必要目标或验收边界，未启动任务生命周期。",
                "state": "blocked",
                "phase": "explicit_contract_task",
                "terminal_reason": "explicit_contract_invalid",
                "contract_errors": errors,
                "runtime_branch": dict(runtime_branch or {}),
            }
            yield error_event(
                content="显式任务合同无效，任务未启动。",
                code="explicit_contract_invalid",
                reason="explicit_contract_invalid",
                extra={
                    "terminal_reason": "explicit_contract_invalid",
                    "contract_errors": errors,
                    "runtime_branch": dict(runtime_branch or {}),
                    "answer_source": "harness.entrypoint.explicit_contract_task",
                    "answer_persist_policy": "runtime_status_only",
                    "answer_finalization_policy": "fail_closed_visible_message",
                    "diagnostics": {
                        "runtime_unavailable": True,
                        "explicit_contract_invalid": True,
                        "contract_errors": errors,
                    },
                },
            )
            return
        for event in _task_environment_receipt_events(
            base_dir=self.base_dir,
            session_id=request.session_id,
            turn_id=turn_id,
            action_request=action_request,
            runtime_branch=runtime_branch,
            source="harness.explicit_contract_task",
            contract=contract,
        ):
            yield event

    def _active_work_context_from_active_turn(self, session_id: str) -> ActiveWorkContext | None:
        repository = TaskEnvironmentRepository(self.base_dir)
        binding = repository.get_foreground_session_binding(session_id)
        if binding is None:
            return None
        environment = repository.get_task_environment(binding.task_environment_id)
        if environment is None or _task_environment_status_is_terminal(environment.status):
            return None
        task_instance = repository.get_task_instance(environment.task_instance_id)
        now = time.time()
        leases = repository.list_leases(environment.task_environment_id, limit=10)
        active_leases = [
            lease
            for lease in leases
            if str(lease.status or "") == "active" and float(lease.expires_at or 0.0) > now
        ]
        pending_signals = repository.list_control_signals(
            environment.task_environment_id,
            status="pending",
            limit=20,
        )
        pending_signal_kinds = {
            str(signal.signal_kind or "").strip()
            for signal in pending_signals
            if str(signal.signal_kind or "").strip()
        }
        running = bool(active_leases) or environment.status == "leased"
        paused = environment.status == "paused"
        resumable = environment.status in {"ready", "paused", "blocked"} and not running
        control_state = _active_task_environment_control_state(pending_signal_kinds)
        return ActiveWorkContext(
            session_id=str(session_id or "").strip(),
            active_work_id=environment.task_environment_id,
            task_environment_id=environment.task_environment_id,
            task_instance_id=environment.task_instance_id,
            session_binding_id=binding.binding_id,
            status=environment.status,
            control_state=control_state,
            environment_kind=environment.environment_kind,
            user_visible_goal=_task_environment_user_visible_goal(task_instance, environment.to_dict()),
            latest_progress=_task_environment_latest_progress(environment.to_dict()),
            latest_step_name=environment.current_step,
            resumable=resumable,
            running=running,
            paused=paused,
            queued_user_instruction_count=len(pending_signals),
            execution_runtime_kind="task_work_environment",
            continuation_kind="task_environment",
            control_capabilities=_task_environment_active_work_capabilities(
                environment=environment.to_dict(),
                running=running,
                pending_signal_kinds=pending_signal_kinds,
            ),
        )

    async def _apply_task_environment_active_work_control(
        self,
        *,
        request: HarnessRuntimeRequest,
        turn_id: str,
        action_request: ModelActionRequest,
        active_work_context: ActiveWorkContext | None,
        runtime_branch: dict[str, Any],
    ):
        decision = active_work_turn_decision_from_payload(
            dict(action_request.active_work_control or {}),
            user_message=request.message,
        )
        if not decision.accepted:
            yield {
                "type": "active_work_control_observation",
                "terminal_reason": decision.denied_reason or decision.reason or "active_work_control_denied",
                "content": active_work_control_denial_observation(decision),
                "decision": decision.to_dict(),
                "authority": "harness.entrypoint.task_environment_active_work_control",
            }
            return
        if active_work_context is None or not str(active_work_context.task_environment_id or "").strip():
            yield {
                "type": "active_work_control_observation",
                "terminal_reason": "task_environment_active_work_unavailable",
                "content": "当前没有可控制的任务环境。",
                "decision": decision.to_dict(),
                "authority": "harness.entrypoint.task_environment_active_work_control",
            }
            return

        content = decision.response or default_reply_for_action(decision.action, active_work_context)
        if decision.action == "answer_about_active_work":
            commit_result = await self._commit_facade_assistant_output(
                request=request,
                turn_id=turn_id,
                content=content,
                answer_source="harness.entrypoint.task_environment_active_work_control.answer",
                execution_posture="active_work_status_answer",
                terminal_reason="active_work_status_answered",
                refs={
                    "task_environment_ref": active_work_context.task_environment_id,
                    "active_work_ref": active_work_context.active_work_id,
                },
            )
            yield final_answer_event(
                content=commit_result.decision.content,
                answer_source="harness.entrypoint.task_environment_active_work_control.answer",
                answer_channel="conversation",
                terminal_reason="active_work_status_answered",
                execution_posture="active_work_status_answer",
                extra={
                    "task_environment_id": active_work_context.task_environment_id,
                    "active_work_control_decision": decision.to_dict(),
                    "runtime_branch": dict(runtime_branch or {}),
                },
            )
            return

        signal_kind = _task_environment_control_signal_kind(decision.action)
        if not signal_kind:
            yield {
                "type": "active_work_control_observation",
                "terminal_reason": "active_work_control_action_not_mapped",
                "content": "当前控制动作没有可写入的任务环境信号。",
                "decision": decision.to_dict(),
                "authority": "harness.entrypoint.task_environment_active_work_control",
            }
            return
        try:
            scheduler = TaskScheduler(
                self.base_dir,
                harness_runtime=self,
                graph_system=self.graph_system,
            )
            submitted = scheduler.submit_command(
                command_kind="request_control_signal",
                task_environment_id=active_work_context.task_environment_id,
                requested_by="user",
                payload={
                    "signal_kind": signal_kind,
                    "requested_by": "user",
                    "reason": decision.reason or decision.action,
                    "active_work_action": decision.action,
                    "payload": {
                        "active_work_action": decision.action,
                        "appended_instruction": decision.appended_instruction,
                        "relation_to_current_work": decision.relation_to_current_work,
                        "evidence": decision.evidence,
                        "turn_id": turn_id,
                        "request_id": action_request.request_id,
                        "session_id": request.session_id,
                    },
                    "bridge_graph_control": True,
                    "signal_idempotency_key": stable_task_environment_id(
                        "controlkey",
                        active_work_context.task_environment_id,
                        turn_id,
                        action_request.request_id,
                        signal_kind,
                    ),
                },
                idempotency_key=stable_task_environment_id(
                    "taskcmdkey",
                    active_work_context.task_environment_id,
                    turn_id,
                    action_request.request_id,
                    signal_kind,
                ),
            )
            dispatched = await scheduler.dispatch_command(str(dict(submitted.get("command") or {}).get("command_id") or ""))
            command_result = dict(dispatched.get("result") or {})
            request_result = dict(command_result.get("request") or {})
            signal = dict(request_result.get("control_signal") or {})
            bridge = dict(command_result.get("bridge") or {})
            handling = dict(command_result.get("handling") or {})
        except Exception as exc:
            yield {
                "type": "active_work_control_observation",
                "terminal_reason": "task_environment_control_signal_failed",
                "content": "当前工作控制信号写入失败。",
                "error": {"reason": str(exc) or type(exc).__name__, "exception_type": type(exc).__name__},
                "decision": decision.to_dict(),
                "task_environment_id": active_work_context.task_environment_id,
                "authority": "harness.entrypoint.task_environment_active_work_control",
            }
            return

        commit_result = await self._commit_facade_assistant_output(
            request=request,
            turn_id=turn_id,
            content=content,
            answer_source="harness.entrypoint.task_environment_active_work_control",
            execution_posture="task_environment_control_signal_requested",
            terminal_reason="active_work_control_signal_requested",
            refs={
                "task_environment_ref": active_work_context.task_environment_id,
                "active_work_ref": active_work_context.active_work_id,
                "control_signal_ref": str(signal.get("signal_id") or ""),
                "task_command_ref": str(dict(submitted.get("command") or {}).get("command_id") or ""),
                "task_dispatch_ref": str(dict(dispatched.get("dispatch") or {}).get("dispatch_id") or ""),
            },
        )
        yield {
            "type": "active_work_control_requested",
            "task_environment_id": active_work_context.task_environment_id,
            "control_signal": signal,
            "request": dict(request_result or {}),
            "bridge": dict(bridge or {}),
            "handling": dict(handling or {}),
            "task_command": dict(submitted.get("command") or {}),
            "task_dispatch": dict(dispatched.get("dispatch") or {}),
            "decision": decision.to_dict(),
            "authority": "harness.entrypoint.task_environment_active_work_control",
        }
        yield final_answer_event(
            content=commit_result.decision.content,
            answer_source="harness.entrypoint.task_environment_active_work_control",
            answer_channel="conversation",
            terminal_reason="active_work_control_signal_requested",
            execution_posture="task_environment_control_signal_requested",
            extra={
                "task_environment_id": active_work_context.task_environment_id,
                "control_signal_id": str(signal.get("signal_id") or ""),
                "task_command_id": str(dict(submitted.get("command") or {}).get("command_id") or ""),
                "runtime_branch": dict(runtime_branch or {}),
            },
        )

    def _release_transient_active_turn(self, *, session_id: str, turn_id: str, terminal_reason: str) -> None:
        record = self.single_agent_runtime_host.active_turn_registry.snapshot(session_id)
        if record is None or record.turn_id != turn_id:
            return
        try:
            self.single_agent_runtime_host.active_turn_registry.complete(
                session_id=session_id,
                expected_turn_id=turn_id,
                terminal_reason=terminal_reason,
            )
        except Exception:
            logger.debug("failed to release transient active turn", exc_info=True)

    def _recent_work_outcome_from_latest_task_environment(self, session_id: str) -> dict[str, Any]:
        """Return a read-only status fact for the latest terminal TaskWorkEnvironment."""
        repository = TaskEnvironmentRepository(self.base_dir)
        bindings = repository.list_session_bindings(
            session_id,
            visibility="foreground",
            control_role="controller",
            limit=20,
        )
        if not bindings:
            bindings = repository.list_session_bindings(
                session_id,
                control_role="controller",
                limit=20,
            )
        candidates: list[tuple[float, Any, Any, Any | None]] = []
        for binding in bindings:
            environment = repository.get_task_environment(binding.task_environment_id)
            if environment is None:
                continue
            candidate_status = str(environment.status or "").strip()
            candidate_reason = str(environment.blocked_reason or environment.continuation_hint or "").strip()
            if not _recent_work_outcome_status(status=candidate_status, terminal_reason=candidate_reason):
                continue
            instance = repository.get_task_instance(environment.task_instance_id)
            recency = max(
                float(environment.updated_at or 0.0),
                float(getattr(binding, "updated_at", 0.0) or 0.0),
                float(getattr(binding, "last_focused_at", 0.0) or 0.0),
            )
            candidates.append((recency, binding, environment, instance))
        if not candidates:
            return {}
        _, binding, latest, task_instance = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        status = str(latest.status or "").strip()
        terminal_reason = str(latest.blocked_reason or latest.continuation_hint or status).strip()
        if not _recent_work_outcome_status(status=status, terminal_reason=terminal_reason):
            return {}
        metadata = dict(latest.metadata or {})
        contract = dict(metadata.get("contract") or {})
        latest_events = list(repository.list_events(latest.task_environment_id, limit=80))
        latest_event = latest_events[-1] if latest_events else None
        latest_event_payload = dict(getattr(latest_event, "payload", {}) or {}) if latest_event is not None else {}
        goal = _public_status_text(
            contract.get("goal")
            or contract.get("user_visible_goal")
            or contract.get("task_run_goal")
            or getattr(task_instance, "goal", "")
            or getattr(task_instance, "title", "")
            or latest.task_environment_id
        )
        latest_progress = _public_status_text(
            latest.progress_label
            or latest_event_payload.get("public_progress_note")
            or latest_event_payload.get("latest_step_summary")
            or latest_event_payload.get("summary")
            or latest.blocked_reason
            or latest.continuation_hint
            or terminal_reason
            or status
        )
        agent_brief = _public_status_text(
            latest_event_payload.get("agent_brief_output")
            or metadata.get("agent_brief_output")
        )
        return _drop_empty_entrypoint_payload(
            {
                "task_environment_id": latest.task_environment_id,
                "task_instance_id": latest.task_instance_id,
                "session_task_binding_id": str(getattr(binding, "binding_id", "") or ""),
                "task_kind": str(getattr(task_instance, "task_kind", "") or ""),
                "status": status,
                "terminal_reason": terminal_reason,
                "lifecycle": "task_work_environment",
                "bucket": "task_environment",
                "user_visible_goal": goal,
                "latest_progress": latest_progress,
                "latest_step_name": str(latest.current_step or latest.current_phase or ""),
                "latest_step_status": status,
                "latest_event_type": str(getattr(latest_event, "event_type", "") or ""),
                "agent_brief_output": agent_brief,
                "work_product_refs": (
                    [{"work_product_id": latest.latest_work_product_id}]
                    if latest.latest_work_product_id
                    else []
                ),
                "updated_at": float(latest.updated_at or 0.0),
                "continuation_state": "terminal_or_interrupted_task_environment",
                "decision_boundary": (
                    "只读事实：这是最近一个已结束、受阻或中断 TaskWorkEnvironment 的结果记录。"
                    "你可以用它回答状态或失败原因问题，但不能把它当成 active work，"
                    "也不能基于这条记录直接续跑任务；恢复或控制必须走 TaskWorkEnvironment 控制面。"
                ),
                "authority": "task_system.task_environment.recent_work_outcome",
            }
        )

    async def generate_title(self, first_user_message: str) -> str:
        return await self.model_runtime.generate_title(first_user_message)

    def _resolve_request_agent_runtime_profile(self, request: Any) -> Any:
        request_profile = _request_payload(request, "runtime_profile")
        runtime_contract = _request_payload(request, "runtime_contract")
        contract_profile = dict(runtime_contract.get("runtime_profile") or {})
        profile_id = _first_non_empty_string(
            request_profile.get("agent_profile_id"),
            request_profile.get("profile_ref"),
            request_profile.get("agent_profile_ref"),
            contract_profile.get("agent_profile_id"),
            contract_profile.get("profile_ref"),
            contract_profile.get("agent_profile_ref"),
        )
        if profile_id:
            profile = self.agent_runtime_registry.get_profile_by_profile_id(profile_id)
            if profile is None:
                raise ValueError(f"request_agent_profile_not_registered:{profile_id}")
            explicit_agent_id = _first_non_empty_string(
                request_profile.get("agent_id"),
                contract_profile.get("agent_id"),
            )
            if explicit_agent_id and str(getattr(profile, "agent_id", "") or "").strip() != explicit_agent_id:
                raise ValueError(
                    "request_agent_profile_agent_mismatch:"
                    f"{profile_id}:{explicit_agent_id}:{str(getattr(profile, 'agent_id', '') or '').strip()}"
                )
            return profile
        agent_id = _first_non_empty_string(
            request_profile.get("agent_id"),
            contract_profile.get("agent_id"),
        )
        if agent_id:
            profile = self.agent_runtime_registry.get_profile(agent_id)
            if profile is None:
                raise ValueError(f"request_agent_id_not_registered:{agent_id}")
            return profile
        profile = self.agent_runtime_registry.get_profile_by_profile_id(DEFAULT_INTERACTIVE_AGENT_PROFILE_ID)
        if profile is None:
            raise ValueError(f"default_interactive_agent_profile_missing:{DEFAULT_INTERACTIVE_AGENT_PROFILE_ID}")
        return profile

    def _commit_user_message(
        self,
        *,
        session_id: str,
        content: str,
        turn_id: str,
        provider_protocol_content: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        message_id: str = "",
        client_message_id: str = "",
        source: str = "harness.entrypoint.adapter_input",
    ):
        normalized_message_id = str(message_id or client_message_id or "").strip()
        normalized_client_message_id = str(client_message_id or "").strip()
        decision = build_user_message_commit_decision(
            session_id=session_id,
            content=content,
            task_id=turn_id,
            source=source,
        )
        if decision.commit_allowed:
            payload = dict(decision.commit_candidate.payload)
            public_payload = {
                "role": payload.get("role"),
                "content": payload.get("content"),
                "turn_id": turn_id,
                "attachments": [dict(item) for item in list(attachments or []) if isinstance(item, dict)],
                "source": source,
            }
            if normalized_message_id:
                public_payload["id"] = normalized_message_id
                public_payload["message_id"] = normalized_message_id
            if normalized_client_message_id:
                public_payload["client_message_id"] = normalized_client_message_id
            if not self._session_contains_user_message(
                session_id,
                message_id=normalized_message_id,
                client_message_id=normalized_client_message_id,
                turn_id=turn_id,
                content=str(payload.get("content") or ""),
                use_provider_protocol_timeline=False,
            ):
                self.session_manager.append_messages(session_id, [public_payload])
            append_provider_protocol = getattr(self.session_manager, "append_provider_protocol_messages", None)
            if callable(append_provider_protocol):
                provider_protocol_payload = {
                    "role": payload.get("role"),
                    "content": str(provider_protocol_content if provider_protocol_content is not None else payload.get("content") or ""),
                    "turn_id": turn_id,
                    "source": source,
                }
                if not self._session_contains_user_message(
                    session_id,
                    message_id=normalized_message_id,
                    client_message_id=normalized_client_message_id,
                    turn_id=turn_id,
                    content=str(provider_protocol_payload.get("content") or ""),
                    use_provider_protocol_timeline=True,
                ):
                    append_provider_protocol(session_id, [provider_protocol_payload])
        return decision

    def _session_contains_user_message(
        self,
        session_id: str,
        *,
        message_id: str,
        client_message_id: str,
        turn_id: str,
        content: str,
        use_provider_protocol_timeline: bool,
    ) -> bool:
        loader = (
            getattr(self.session_manager, "load_provider_protocol_timeline", None)
            if use_provider_protocol_timeline
            else getattr(self.session_manager, "load_session", None)
        )
        if not callable(loader):
            return False
        try:
            messages = list(loader(session_id) or [])
        except Exception:
            logger.debug("failed to inspect session user message for idempotent commit", exc_info=True)
            return False
        target_message_id = str(message_id or "").strip()
        target_client_message_id = str(client_message_id or "").strip()
        target_turn_id = str(turn_id or "").strip()
        target_content = str(content or "")
        for item in messages:
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "").strip() != "user":
                continue
            item_id = str(item.get("id") or item.get("message_id") or "").strip()
            item_client_message_id = str(item.get("client_message_id") or "").strip()
            if target_message_id and item_id == target_message_id:
                return True
            if target_client_message_id and item_client_message_id == target_client_message_id:
                return True
            item_turn_id = str(item.get("turn_id") or "").strip()
            item_content = str(item.get("content") or "")
            content_matches = item_content == target_content or item_content.strip() == target_content.strip()
            if target_turn_id and item_turn_id == target_turn_id and content_matches:
                return True
        return False

    def _record_turn_environment_snapshot(
        self,
        *,
        session_id: str,
        turn_id: str,
        runtime_assembly: Any,
        execution_scope: dict[str, Any] | None = None,
    ) -> None:
        update_snapshot = getattr(self.session_manager, "update_turn_environment_snapshot", None)
        if not callable(update_snapshot):
            return
        try:
            assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
            environment = dict(assembly_payload.get("task_environment") or {})
            boundary = dict(environment.get("environment_boundary") or {})
            prompt_refs = assembly_payload.get("environment_prompt_refs") or boundary.get("prompt_refs") or []
            scope = dict(execution_scope or {})
            execution_scope_kind = str(scope.get("execution_scope_kind") or scope.get("scope_kind") or "single_agent_turn").strip()
            task_environment_id = str(
                scope.get("task_environment_id")
                or environment.get("environment_id")
                or environment.get("task_environment_id")
                or environment.get("requested_environment_id")
                or ""
            ).strip()
            update_snapshot(
                session_id,
                turn_id=turn_id,
                snapshot={
                    "turn_id": turn_id,
                    "execution_scope_kind": execution_scope_kind,
                    "task_environment_id": task_environment_id,
                    "task_instance_id": str(scope.get("task_instance_id") or "").strip(),
                    "episode_id": str(scope.get("episode_id") or "").strip(),
                    "graph_run_id": str(scope.get("graph_run_id") or "").strip(),
                    "node_id": str(scope.get("node_id") or "").strip(),
                    "work_order_id": str(scope.get("work_order_id") or "").strip(),
                    "context_package_id": str(scope.get("context_package_id") or "").strip(),
                    "environment_kind": str(environment.get("environment_kind") or "").strip(),
                    "environment_prompt_refs": list(prompt_refs or []),
                    "runtime_assembly_id": str(assembly_payload.get("assembly_id") or "").strip(),
                    "task_run_id": str(scope.get("task_run_id") or "").strip(),
                },
            )
        except Exception:
            logger.debug("failed to record turn environment snapshot", exc_info=True)

    def _apply_assistant_message_commit(self, session_id: str, payload: dict[str, Any]):
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
        append_provider_protocol = getattr(self.session_manager, "append_provider_protocol_messages", None)
        if callable(append_provider_protocol):
            protocol_messages = [
                dict(item)
                for item in list(payload.get("provider_protocol_messages_to_append") or [])
                if isinstance(item, dict)
            ]
            if protocol_messages:
                append_provider_protocol(session_id, protocol_messages)
            else:
                append_provider_protocol(
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
        updater = getattr(getattr(self.memory_facade, "conversation_continuity", None), "update_runtime_state_from_context_state", None)
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

    def _load_recent_provider_protocol_messages_for_memory(self, session_id: str) -> list[dict[str, Any]]:
        loader = getattr(self.session_manager, "load_provider_protocol_timeline", None)
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
        payload = receipt_payload(receipt)
        continuity_succeeded = bool(payload.get("conversation_continuity_succeeded") is True)
        durable_succeeded = bool(payload.get("durable_memory_succeeded") is True)
        durable_write_count = int(payload.get("durable_write_count") or 0)
        attempted = bool(payload.get("attempted") is True)
        failed = str(payload.get("status") or "") == "failed"
        conversation_continuity_chars = 0
        try:
            conversation_continuity_chars = len(self.memory_facade.conversation_continuity.manager(str(payload.get("session_id") or "")).load() or "") if continuity_succeeded else 0
        except Exception:
            conversation_continuity_chars = 0
        return {
            "memory_maintenance_attempted": attempted,
            "memory_maintenance_status": str(payload.get("status") or ""),
            "memory_maintenance_receipt": payload,
            "memory_maintenance_error": str(payload.get("error") or ""),
            "conversation_continuity_succeeded": continuity_succeeded,
            "durable_memory_succeeded": durable_succeeded,
            "durable_write_count": durable_write_count,
            "conversation_continuity_chars": conversation_continuity_chars,
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


def _request_payload(request: Any, field_name: str) -> dict[str, Any]:
    payload_reader = getattr(request, f"{field_name}_payload", None)
    if callable(payload_reader):
        return payload_reader()
    value = getattr(request, field_name, {})
    return dict(value) if isinstance(value, dict) else {}


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
        content_matches = not target_content or content == target_content or content.strip() == target_content.strip()
        compacted_current_request_match = not item_turn_id and bool(target_content) and content_matches
        is_current_user_request = (
            role == "user"
            and (current_turn_match or compacted_current_request_match)
            and content_matches
        )
        if is_current_user_request:
            continue
        result.append(dict(item))
    return result


def _attach_fork_snapshot_to_session_context(
    session_context: dict[str, Any],
    history_record: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(session_context or {})
    record = dict(history_record or {})
    parent_session_id = str(record.get("parent_session_id") or "").strip()
    forked_from = dict(record.get("forked_from") or {}) if isinstance(record.get("forked_from"), dict) else {}
    if parent_session_id:
        payload["parent_session_id"] = parent_session_id
    else:
        payload.pop("parent_session_id", None)
    if forked_from:
        payload["forked_from"] = forked_from
    else:
        payload.pop("forked_from", None)
    return payload


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


def _runtime_profile_payload_from_assembly(runtime_assembly: Any) -> dict[str, Any]:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    return dict(payload.get("profile") or {})


def _runtime_permission_mode_from_assembly(runtime_assembly: Any) -> str:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    runtime_contract = dict(payload.get("runtime_contract") or {})
    profile = dict(payload.get("profile") or {})
    return str(
        payload.get("permission_mode")
        or runtime_contract.get("permission_mode")
        or profile.get("permission_mode")
        or "default"
    ).strip() or "default"


class _RuntimeAssemblyPayloadView:
    def __init__(self, base: Any, payload: dict[str, Any]) -> None:
        self._base = base
        self._payload = dict(payload or {})

    def to_dict(self) -> dict[str, Any]:
        return dict(self._payload or {})

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def _runtime_assembly_with_task_launch_supervision(runtime_assembly: Any) -> Any:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    profile = dict(payload.get("profile") or {})
    lifecycle_policy = dict(profile.get("task_lifecycle_policy") or {})
    supervision = dict(lifecycle_policy.get("task_launch_supervision") or lifecycle_policy.get("launch_supervision") or {})
    lifecycle_policy["task_launch_supervision"] = {
        **supervision,
        "enabled": True,
        "allow_direct_pass": True,
        "gate_type": str(supervision.get("gate_type") or "slash_task_command_launch"),
        "user_prompt": str(supervision.get("user_prompt") or "长任务资源已建立。你可以补充约束，或直接继续执行。"),
    }
    profile["task_lifecycle_policy"] = lifecycle_policy
    payload["profile"] = profile
    return _RuntimeAssemblyPayloadView(runtime_assembly, payload)


def _append_model_action_admission_event(
    runtime_host: Any,
    *,
    action_request: ModelActionRequest,
    lifecycle: Any,
    run_id: str,
    packet_ref: str,
    session_id: str,
    turn_id: str,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_record = build_action_lifecycle_event_record(
        lifecycle,
        action_request,
        run_id=run_id,
        packet_ref=packet_ref,
        session_id=session_id,
        turn_id=turn_id,
        extra_payload=dict(extra_payload or {}),
    )
    event = append_action_lifecycle_event(runtime_host, event_record)
    return event.to_dict() if hasattr(event, "to_dict") else dict(event or {})


def _slash_task_action_runtime_branch(signal: TaskModeSlashSignal) -> dict[str, Any]:
    mode_kind = str(signal.mode_kind or "").strip()
    return {
        "branch_kind": "slash_task_action_signal",
        "invocation_kind": "task_action_signal",
        "dispatch_target": "harness.entrypoint.slash_task_action_signal",
        "reason": "user_slash_task_command",
        "control_capabilities": {},
        "monitor_policy": {"record_task_monitor": True, "record_turn_monitor": False},
        "diagnostics": {
            "slash_command": str(signal.command or ""),
            "mode_kind": mode_kind,
            "action_request_present": signal.action_request is not None,
            "signal_authority": "harness.entrypoint.task_mode_slash_command",
        },
        "authority": "harness.entrypoint.runtime_branch",
    }


def _explicit_contract_action_request(
    *,
    request: HarnessRuntimeRequest,
    turn_id: str,
    runtime_assembly: Any,
) -> ModelActionRequest:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    source = _explicit_contract_source_payload(assembly_payload)
    runtime_contract = dict(assembly_payload.get("runtime_contract") or {})
    return ModelActionRequest(
        request_id=f"system-explicit-contract:{turn_id}:{uuid.uuid4().hex[:8]}",
        turn_id=turn_id,
        action_type="request_task_run",
        public_progress_note="已接收明确任务目标，正在启动任务。",
        public_action_state={
            "current_judgment": "任务目标、范围和验收标准已经成型。",
            "next_action": "直接建立任务生命周期。",
            "completion_status": "working",
        },
        task_run_contract_seed=_explicit_contract_task_seed(
            request=request,
            source=source,
            runtime_contract=runtime_contract,
        ),
        diagnostics={
            "origin_kind": "user_direct_request",
            "origin_authority": "harness.explicit_contract_task",
            "source_contract_ref": str(source.get("contract_id") or source.get("source_ref") or ""),
        },
    )


def _explicit_contract_task_seed(
    *,
    request: HarnessRuntimeRequest,
    source: dict[str, Any],
    runtime_contract: dict[str, Any],
) -> dict[str, Any]:
    for candidate in (
        source.get("task_run_contract_seed"),
        source.get("task_run_contract"),
        runtime_contract.get("task_run_contract_seed"),
        runtime_contract.get("task_run_contract"),
    ):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    output_contract = dict(source.get("output_contract") or {})
    acceptance_policy = dict(source.get("acceptance_policy") or {})
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
    working_scope = dict(source.get("working_scope") or {}) if isinstance(source.get("working_scope"), dict) else {}
    completion_criteria = contract_string_tuple(
        source.get("completion_criteria")
        or output_contract.get("completion_criteria")
        or acceptance_policy.get("completion_criteria")
    )
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
    plan_contract = dict(source.get("plan_contract") or {}) if isinstance(source.get("plan_contract"), dict) else {}
    major_steps = contract_string_tuple(
        plan_contract.get("major_steps")
        or plan_contract.get("steps")
        or source.get("major_steps")
        or completion_criteria
        or (task_run_goal,)
    )
    primary_ref = "work-mode:plan:primary"
    return {
        "contract_id": "task_run_contract",
        "container_contract": {
            "entry_reason": _first_contract_text(
                source.get("entry_reason"),
                f"显式任务合同已提供，当前工作需要绑定长任务资源：{user_visible_goal}",
            ),
            "continuity_required": True,
            "control_required": True,
            "projection_required": True,
            "checkpoint_required": True,
            "minimum_viable_next_step": _first_contract_text(
                source.get("minimum_viable_next_step"),
                "按显式合同推进 primary Plan Work Mode 的第一步。",
            ),
            "primary_work_mode_ref": primary_ref,
            "supporting_mode_refs": [],
            "mode_transition_policy": {
                "agent_may_propose_transition": True,
                "system_may_infer_transition": False,
                "requires_accepted_event": True,
            },
        },
        "work_modes": [
            {
                "mode_instance_id": primary_ref,
                "mode_kind": "plan",
                "mode_role": "primary",
                "status": "draft",
                "depends_on_mode_refs": [],
                "contract": {
                    "strategy_summary": _first_contract_text(
                        plan_contract.get("strategy_summary"),
                        task_run_goal,
                        user_visible_goal,
                    ),
                    "major_steps": list(major_steps),
                    "plan_status": _first_contract_text(plan_contract.get("plan_status"), "agent_managed"),
                    "replan_policy": dict(plan_contract.get("replan_policy") or {}) if isinstance(plan_contract.get("replan_policy"), dict) else {},
                    "external_plan_ref": str(source.get("plan_id") or source.get("external_plan_ref") or "").strip(),
                    "working_scope": working_scope,
                },
            }
        ],
        "lifecycle_contract": {
            "pause_policy": {"allowed": True, "state_to_preserve": ["container_contract", "active_work_mode_refs", "completed_steps", "open_risks", "next_resume_step"]},
            "resume_policy": {"resume_from": "latest_preserved_state_and_user_steer"},
            "stop_policy": {"on_stop": "停止后说明已完成内容、未完成内容和可恢复状态。"},
            "replan_policy": {"when": "显式合同、观察证据或验收状态发生实质偏离时先反馈。"},
            "failure_recovery_policy": dict(source.get("recovery_policy") or {"on_failure": "公开说明失败原因、已完成范围和可恢复状态。"}),
            "terminal_policy": {"final_report_required": True, "include_unfinished_work": True},
        },
        "feedback_contract": {
            "feedback_sources": ["tool_observation", "runtime_observation", "lifecycle_signal", "verification_signal"],
            "verification_feedback_policy": {"report_failed_verification": True},
        },
        "memory_contract": {
            "preserve_on_pause": ["container_contract", "active_work_mode_refs", "completed_steps", "open_risks", "next_resume_step"],
            "preserve_on_stop": ["final_status", "unfinished_work", "resume_hint"],
        },
        "acceptance_contract": {
            "acceptance_mode": "strict" if (completion_criteria or required_artifacts or required_verifications) else "checkpoint",
            "completion_criteria": list(completion_criteria),
            "required_artifacts": list(required_artifacts),
            "required_verifications": list(required_verifications),
            "acceptance_policy": acceptance_policy,
            "final_answer_requirements": ["说明完成项", "说明验证结果", "说明未完成项和风险"],
            "evidence_refs_required": bool(completion_criteria or required_artifacts or required_verifications),
        },
        "runtime_requirements": {
            "permission_requirements": dict(source.get("permission_requirements") or source.get("tool_scope") or {}),
            "resource_requirements": {},
            "safety_boundaries": [],
        },
    }


def _task_run_contract_from_explicit_contract(
    *,
    request: HarnessRuntimeRequest,
    turn_id: str,
    runtime_assembly: Any,
    action_request: ModelActionRequest,
) -> tuple[TaskRunContract | None, list[str]]:
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    source = _explicit_contract_source_payload(assembly_payload)
    runtime_contract = dict(assembly_payload.get("runtime_contract") or {})
    environment = dict(assembly_payload.get("task_environment") or {})
    task_environment_id = str(
        runtime_contract.get("task_environment_id")
        or source.get("task_environment_id")
        or source.get("environment_id")
        or environment.get("environment_id")
        or ""
    ).strip()
    contract, errors = contract_from_action_request(
        action_request,
        packet_ref=action_request.request_id,
        task_environment_id=task_environment_id,
    )
    if contract is None:
        return None, errors
    contract = replace(
        contract,
        contract_source="user_direct_request",
        source_contract_ref=str(source.get("contract_id") or source.get("source_ref") or "").strip(),
        external_plan_ref=str(source.get("plan_id") or source.get("external_plan_ref") or "").strip(),
        origin={
            "origin_kind": "user_direct_request",
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


def _task_environment_status_is_terminal(status: str) -> bool:
    return str(status or "").strip() in {"completed", "failed", "aborted", "archived"}


def _active_task_environment_control_state(pending_signal_kinds: set[str]) -> str:
    for signal_kind in (
        "stop_requested",
        "abort_requested",
        "pause_requested",
        "resume_requested",
        "replan_requested",
        "instruction_appended",
    ):
        if signal_kind in pending_signal_kinds:
            return signal_kind
    return ""


def _task_environment_user_visible_goal(task_instance: Any | None, environment: dict[str, Any]) -> str:
    title = str(getattr(task_instance, "title", "") or "").strip() if task_instance is not None else ""
    goal = str(getattr(task_instance, "goal", "") or "").strip() if task_instance is not None else ""
    return _first_non_empty_string(
        title,
        goal,
        dict(environment.get("metadata") or {}).get("title"),
        dict(environment.get("metadata") or {}).get("goal"),
        environment.get("task_environment_id"),
    )


def _task_environment_latest_progress(environment: dict[str, Any]) -> str:
    return _first_non_empty_string(
        environment.get("progress_label"),
        environment.get("blocked_reason"),
        environment.get("continuation_hint"),
        environment.get("current_step"),
        environment.get("status"),
    )


def _task_environment_active_work_capabilities(
    *,
    environment: dict[str, Any],
    running: bool,
    pending_signal_kinds: set[str],
) -> dict[str, Any]:
    status = str(environment.get("status") or "").strip()
    terminal = _task_environment_status_is_terminal(status)
    return {
        "pause_active_work": bool(running and not terminal and "pause_requested" not in pending_signal_kinds),
        "stop_active_work": bool(
            not terminal
            and "stop_requested" not in pending_signal_kinds
            and "abort_requested" not in pending_signal_kinds
        ),
        "append_instruction_to_active_work": bool(not terminal),
        "answer_about_active_work": True,
        "pending_control_signal_kinds": sorted(item for item in pending_signal_kinds if item),
        "authority": "harness.entrypoint.task_environment_active_work_capabilities",
    }


def _task_environment_control_signal_kind(action: str) -> str:
    if action == "pause_active_work":
        return "pause_requested"
    if action == "stop_active_work":
        return "stop_requested"
    if action == "append_instruction_to_active_work":
        return "instruction_appended"
    return ""


def _task_run_id_from_lifecycle_event(event: dict[str, Any]) -> str:
    payload = dict(event or {})
    task_run = dict(payload.get("task_run") or {})
    if task_run:
        return str(task_run.get("task_run_id") or "").strip()
    runtime_event = dict(payload.get("event") or {})
    runtime_payload = dict(runtime_event.get("payload") or {})
    task_run = dict(runtime_payload.get("task_run") or {})
    return str(task_run.get("task_run_id") or "").strip()


def _task_environment_receipt_events(
    *,
    base_dir: Path,
    session_id: str,
    turn_id: str,
    action_request: ModelActionRequest,
    runtime_branch: dict[str, Any],
    source: str,
    contract: TaskRunContract | None = None,
) -> list[dict[str, Any]]:
    request_id = str(getattr(action_request, "request_id", "") or f"request-task-run:{turn_id}").strip()
    resolved_contract = contract
    contract_errors: list[str] = []
    if resolved_contract is None:
        resolved_contract, contract_errors = contract_from_action_request(
            action_request,
            packet_ref=request_id,
            task_environment_id="",
        )
    if resolved_contract is None:
        reason = ";".join(str(item) for item in contract_errors if str(item)) or "task_environment_contract_invalid"
        return [
            {
                "type": "runtime_status",
                "title": "任务环境未创建",
                "detail": "request_task_run 缺少可持久化的目标、范围或验收边界，未创建任务环境。",
                "state": "blocked",
                "status_kind": "task_environment_contract_invalid",
                "phase": "request_task_run",
                "terminal_reason": "task_environment_contract_invalid",
                "contract_errors": list(contract_errors),
                "runtime_branch": dict(runtime_branch or {}),
                "model_action_request": action_request.to_dict() if hasattr(action_request, "to_dict") else {},
                "request_id": request_id,
                "session_id": str(session_id or ""),
                "turn_id": str(turn_id or ""),
                "authority": "harness.entrypoint.task_environment_allocation",
            },
            error_event(
                content="任务环境未创建：任务目标、范围或验收边界不完整。",
                code="task_environment_contract_invalid",
                reason=reason,
                extra={
                    "answer_source": "harness.entrypoint.task_environment_allocation",
                    "answer_persist_policy": "runtime_status_only",
                    "answer_finalization_policy": "fail_closed_visible_message",
                    "contract_errors": list(contract_errors),
                },
            ),
        ]
    try:
        service = TaskWorkEnvironmentService(base_dir)
        contract_payload = resolved_contract.to_dict()
        task_environment = service.create_task_environment(
            task_kind=_task_environment_task_kind(resolved_contract),
            title=_task_environment_title(resolved_contract),
            goal=_task_environment_goal(resolved_contract),
            environment_kind=_task_environment_kind(source=source, contract=resolved_contract),
            caller_kind=_task_environment_caller_kind(source),
            idempotency_key=f"{source}:{session_id}:{turn_id}:{request_id}",
            project_id=_task_environment_project_id(resolved_contract),
            workspace_view=_task_environment_workspace_view(resolved_contract),
            acceptance_contract_ref=str(resolved_contract.source_contract_ref or ""),
            metadata={
                "source": str(source or ""),
                "turn_id": str(turn_id or ""),
                "request_id": request_id,
                "contract_id": str(resolved_contract.contract_id or ""),
                "contract": contract_payload,
                "public_progress_note": str(getattr(action_request, "public_progress_note", "") or ""),
                "public_action_state": dict(getattr(action_request, "public_action_state", {}) or {}),
                "runtime_branch": dict(runtime_branch or {}),
                "authority": "harness.entrypoint.task_environment_allocation",
            },
        )
        repository = TaskEnvironmentRepository(base_dir)
        session_binding = repository.upsert_session_binding(
            SessionTaskBinding(
                binding_id=stable_task_environment_id("sessiontask", session_id, task_environment.task_environment_id),
                session_id=str(session_id or ""),
                task_environment_id=task_environment.task_environment_id,
                task_instance_id=task_environment.task_instance_id,
                binding_kind="origin",
                control_role="controller",
                visibility="foreground",
                created_from_turn_id=str(turn_id or ""),
                last_focused_at=time.time(),
                status="active",
                metadata={
                    "source": str(source or ""),
                    "request_id": request_id,
                    "authority": "harness.entrypoint.task_environment_session_binding",
                },
            )
        )
    except Exception as exc:
        return [
            {
                "type": "runtime_status",
                "title": "任务环境创建失败",
                "detail": "request_task_run 已通过动作准入，但任务环境持久化失败。",
                "state": "blocked",
                "status_kind": "task_environment_allocation_failed",
                "phase": "request_task_run",
                "terminal_reason": "task_environment_allocation_failed",
                "request_id": request_id,
                "session_id": str(session_id or ""),
                "turn_id": str(turn_id or ""),
                "error": {"reason": str(exc) or type(exc).__name__, "exception_type": type(exc).__name__},
                "authority": "harness.entrypoint.task_environment_allocation",
            },
            error_event(
                content="任务环境创建失败，本轮没有创建可恢复的 TaskWorkEnvironment。",
                code="task_environment_allocation_failed",
                reason=str(exc) or type(exc).__name__,
                extra={
                    "answer_source": "harness.entrypoint.task_environment_allocation",
                    "answer_persist_policy": "runtime_status_only",
                    "answer_finalization_policy": "fail_closed_visible_message",
                },
            ),
        ]
    return [
        {
            "type": "runtime_status",
            "title": "任务环境已创建",
            "detail": "已接收 request_task_run 控制信号，并创建可恢复的 TaskWorkEnvironment；当前动作只完成任务环境分配，不在同一动作内执行 episode。",
            "state": "completed",
            "status_kind": "task_environment_allocated",
            "phase": "request_task_run",
            "runtime_branch": dict(runtime_branch or {}),
            "model_action_request": action_request.to_dict() if hasattr(action_request, "to_dict") else {},
            "request_id": request_id,
            "session_id": str(session_id or ""),
            "turn_id": str(turn_id or ""),
            "task_environment_id": task_environment.task_environment_id,
            "task_instance_id": task_environment.task_instance_id,
            "session_task_binding_id": session_binding.binding_id,
            "task_environment": task_environment.to_dict(),
            "session_task_binding": session_binding.to_dict(),
            "contract_summary": {
                "contract_id": str(resolved_contract.contract_id or ""),
                "user_visible_goal": str(resolved_contract.user_visible_goal or ""),
                "task_run_goal": str(resolved_contract.task_run_goal or ""),
                "working_scope": dict(resolved_contract.working_scope or {}),
                "acceptance_contract": dict(resolved_contract.acceptance_contract or {}),
            },
            "authority": "harness.entrypoint.task_environment_allocation",
        },
        turn_completed_event(
            status="completed",
            terminal_reason="task_environment_allocated",
            completion_state="task_environment_allocated",
        ),
    ]


def _task_environment_task_kind(contract: TaskRunContract) -> str:
    task_shape = str(dict(contract.container_contract or {}).get("task_shape") or "standard").strip() or "standard"
    return f"agent_task.{task_shape}"


def _task_environment_title(contract: TaskRunContract) -> str:
    return _first_contract_text(
        contract.user_visible_goal,
        contract.task_run_goal,
        dict(contract.container_contract or {}).get("entry_reason"),
        "持续任务环境",
    )


def _task_environment_goal(contract: TaskRunContract) -> str:
    return _first_contract_text(
        contract.task_run_goal,
        contract.user_visible_goal,
        dict(contract.container_contract or {}).get("minimum_viable_next_step"),
        "持续推进当前任务。",
    )


def _task_environment_kind(*, source: str, contract: TaskRunContract) -> str:
    source_text = str(source or "")
    if "slash_task_command" in source_text:
        return "session_slash_task"
    if "explicit_contract" in source_text:
        return "explicit_contract_task"
    primary_kind = ""
    for mode in tuple(contract.work_modes or ()):
        if str(dict(mode).get("mode_role") or "") == "primary":
            primary_kind = str(dict(mode).get("mode_kind") or "").strip()
            break
    return f"agent_requested_{primary_kind or 'task'}"


def _task_environment_caller_kind(source: str) -> str:
    source_text = str(source or "")
    if "graph" in source_text:
        return "graph_node"
    if "slash_task_command" in source_text:
        return "session_command"
    if "explicit_contract" in source_text:
        return "system_contract"
    return "session_turn"



def _task_environment_project_id(contract: TaskRunContract) -> str:
    scope = dict(contract.working_scope or {})
    for item in list(scope.get("workspace_refs") or []):
        text = str(item or "").strip()
        if text.startswith("project:"):
            return text
    return str(dict(contract.origin or {}).get("project_id") or "").strip()


def _task_environment_workspace_view(contract: TaskRunContract) -> str:
    scope = dict(contract.working_scope or {})
    workspace_refs = [str(item or "").strip() for item in list(scope.get("workspace_refs") or []) if str(item or "").strip()]
    return workspace_refs[0] if workspace_refs else "chat"


def _normalized_turn_attachments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        path = _attachment_text(raw.get("path"), limit=500)
        attachment_id = _attachment_text(raw.get("attachment_id"), limit=80)
        if not path or not attachment_id:
            continue
        result.append(
            {
                "attachment_id": attachment_id,
                "session_id": _attachment_text(raw.get("session_id"), limit=120),
                "filename": _attachment_text(raw.get("filename"), limit=180),
                "mime_type": _attachment_text(raw.get("mime_type"), limit=120),
                "size_bytes": _attachment_int(raw.get("size_bytes")),
                "content_sha256": _attachment_text(raw.get("content_sha256"), limit=120),
                "path": path.replace("\\", "/"),
                "created_at": _attachment_float(raw.get("created_at")),
                "width": _attachment_int(raw.get("width")),
                "height": _attachment_int(raw.get("height")),
                "authority": _attachment_text(raw.get("authority"), limit=120),
                "storage_authority": _attachment_text(raw.get("storage_authority"), limit=120),
            }
        )
    return result


def _attachment_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    return text[: max(0, int(limit))]


def _attachment_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _attachment_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _recent_work_outcome_status(*, status: str, terminal_reason: str) -> bool:
    normalized_status = str(status or "").strip()
    normalized_reason = str(terminal_reason or "").strip()
    if normalized_status in {
        "completed",
        "failed",
        "aborted",
        "blocked",
    }:
        return True
    return normalized_reason in {
        "user_aborted",
        "model_call_recovery_required",
        "model_action_protocol_repair_required",
        "task_execution_step_budget_exhausted",
        "task_execution_step_budget_exceeded",
        "executor_failed",
        "runtime_cell_missing_after_restart",
    }


def _public_status_text(value: Any, *, limit: int = 900) -> str:
    text = public_runtime_progress_summary(value)
    if not text:
        text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _drop_empty_entrypoint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _next_session_turn_id(session_id: str, *, history_record: dict[str, Any], turn_memory_store: Any | None) -> str:
    normalized_session = str(session_id or "").strip()
    prefix = f"turn:{normalized_session}:"
    max_index = len(list(dict(history_record or {}).get("messages") or []))
    for message in list(dict(history_record or {}).get("messages") or []):
        if not isinstance(message, dict):
            continue
        for key in ("turn_id", "sourceTurnId", "source_turn_id", "active_turn_id"):
            max_index = max(max_index, _turn_id_index(message.get(key), prefix=prefix))
    lister = getattr(turn_memory_store, "list_session_turns", None)
    if callable(lister):
        try:
            records = list(lister(normalized_session, include_released=True) or [])
        except Exception:
            records = []
        for record in records:
            max_index = max(max_index, _turn_id_index(getattr(record, "turn_id", ""), prefix=prefix))
    return f"{prefix}{max_index + 1}"


def _turn_id_index(value: Any, *, prefix: str) -> int:
    text = str(value or "").strip()
    if not text.startswith(prefix):
        return 0
    suffix = text[len(prefix):]
    if not suffix.isdigit():
        return 0
    try:
        return max(0, int(suffix))
    except ValueError:
        return 0


def _safe_compaction_boundary_timestamp(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _runtime_is_blocked(assembly_payload: dict[str, Any]) -> bool:
    status = str(assembly_payload.get("status") or "").strip().lower()
    if status in {"blocked", "failed", "invalid"}:
        return True
    diagnostics = dict(assembly_payload.get("diagnostics") or {})
    return bool(diagnostics.get("blocked_runtime") is True or diagnostics.get("runtime_blocked") is True)


def _system_issued_explicit_contract_payload(assembly_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_contract = dict(assembly_payload.get("runtime_contract") or {})
    candidates: list[dict[str, Any]] = []
    for key in ("task_run_contract", "task_run_contract_seed", "engagement_contract"):
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


def _first_non_empty_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_contract_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
