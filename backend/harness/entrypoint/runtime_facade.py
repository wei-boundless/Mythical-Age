from __future__ import annotations

import json
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
from harness.loop.task_lifecycle import (
    TaskRunContract,
    contract_from_action_request,
)
from task_system.episodes import AgentExecutionEpisode, EpisodeRepository, EpisodeResult
from task_system.reducer import TaskReducer
from task_system.work_environments.models import SessionTaskBinding, TaskContextPackage, TaskEvent, stable_task_environment_id
from task_system.work_environments.repository import TaskEnvironmentRepository
from task_system.work_environments.control_signal_bridge import apply_task_environment_control_signal_bridge
from task_system.work_environments.service import TaskWorkEnvironmentService
from task_system.work_environments.view_service import TaskEnvironmentViewService
from task_system.work_products import WorkProduct
from graph_system.runtime_effect_registry import handle_runtime_algorithm_effects
from memory_system.runtime_context_provider import RuntimeMemoryContextProvider, should_inject_session_emphasis
from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response

logger = logging.getLogger(__name__)

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
        """Execute one prepared TaskWorkEnvironment episode through the harness.

        TaskSystem owns the task environment, episode ledger, lease, and result
        reduction. This method only bridges an already prepared context package
        into the single-agent runtime and projects the terminal output back into
        TaskReducer.
        """

        service = TaskWorkEnvironmentService(self.base_dir)
        episode_repository = EpisodeRepository(self.base_dir)
        environment = service.repository.get_task_environment(task_environment_id)
        if environment is None:
            raise KeyError(f"TaskWorkEnvironment not found: {task_environment_id}")
        episode = _task_episode_for_execution(
            episode_repository=episode_repository,
            task_environment_id=environment.task_environment_id,
            episode_id=episode_id,
        )
        if episode.task_environment_id != environment.task_environment_id:
            raise ValueError("episode does not belong to task environment")
        context_package = _task_episode_context_package(
            repository=service.repository,
            environment=environment,
            episode=episode,
        )
        agent_profile_resolution = self._resolve_task_episode_agent_profile(episode)
        if not agent_profile_resolution.get("ok"):
            executor_result = _task_episode_executor_blocked_result(
                reason=str(agent_profile_resolution.get("reason") or "task_episode_agent_profile_unresolved"),
                environment=environment.to_dict(),
                episode=episode,
                context_package=context_package,
                diagnostics=dict(agent_profile_resolution.get("diagnostics") or {}),
            )
            reduction = _record_task_episode_execution_result(
                base_dir=self.base_dir,
                environment=environment.to_dict(),
                episode=episode,
                context_package=context_package,
                executor_result=executor_result,
            )
            return {
                "ok": False,
                "status": "blocked",
                "executor_result": executor_result,
                "reduction": reduction.to_dict(),
                "task_environment_view": TaskEnvironmentViewService(self.base_dir).task_environment_detail(environment.task_environment_id),
                "lease": {},
                "lease_release": {},
                "authority": "harness.task_environment_episode_bridge",
            }

        agent_runtime_profile = agent_profile_resolution["profile"]
        agent_profile_id = str(agent_profile_resolution.get("agent_profile_id") or "").strip()
        agent_id = str(agent_profile_resolution.get("agent_id") or "").strip()
        session_id = _task_episode_session_id(environment.to_dict(), episode=episode, context_package=context_package)
        self._ensure_task_episode_execution_session(
            session_id=session_id,
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
        )
        turn_id = stable_task_environment_id(
            "turn",
            "task-environment-episode",
            environment.task_environment_id,
            episode.episode_id,
            context_package.package_hash,
        )
        message = _task_episode_user_message(
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
        )
        self._commit_user_message(
            session_id=session_id,
            content=message,
            provider_protocol_content=message,
            turn_id=turn_id,
            message_id=stable_task_environment_id("user", "task-episode", episode.episode_id),
            source="harness.task_environment_episode_bridge",
        )
        lease_projection = service.acquire_episode_lease(
            task_environment_id=environment.task_environment_id,
            episode_id=episode.episode_id,
            lease_kind="task_episode_execution",
            holder_kind="harness_runtime",
            holder_id=f"task_episode:{episode.episode_id}",
            ttl_seconds=_task_episode_lease_ttl_seconds(context_package),
            idempotency_key=stable_task_environment_id("leasekey", "task-episode", episode.episode_id, context_package.package_hash),
            event_type="task_episode_execution_started",
            current_phase="task_episode",
            current_step="running",
            progress_label="task episode executing through harness",
        )
        runtime_contract = _task_episode_runtime_contract(
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            turn_id=turn_id,
        )
        environment_binding = _task_episode_environment_binding(environment.to_dict(), context_package=context_package)
        model_selection = _task_episode_model_selection(context_package)
        workspace_root = _task_episode_workspace_root(environment.to_dict(), context_package=context_package)
        permission_mode = _graph_node_permission_mode(self.single_agent_runtime_host)
        runtime_assembly = assemble_runtime(
            backend_dir=self.base_dir,
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=f"aginvoke:{turn_id}:task_episode",
            runtime_contract=runtime_contract,
            model_selection=model_selection,
            environment_binding=environment_binding,
            agent_runtime_profile=agent_runtime_profile,
            tool_instances=self._all_tool_instances(),
            definitions_by_name=dict(self.single_agent_runtime_host.tool_authorization_index.definitions_by_name or {}),
            permission_mode=permission_mode,
            workspace_root=workspace_root,
        )
        self._record_turn_environment_snapshot(
            session_id=session_id,
            turn_id=turn_id,
            runtime_assembly=runtime_assembly,
            execution_scope={
                "execution_scope_kind": "task_environment_episode",
                "task_environment_id": environment.task_environment_id,
                "task_instance_id": episode.task_instance_id,
                "episode_id": episode.episode_id,
                "context_package_id": context_package.package_id,
                "authority": "harness.task_environment_episode_bridge.execution_scope",
            },
        )
        session_context = _task_episode_session_context(
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
            runtime_contract=runtime_contract,
            workspace_root=workspace_root,
        )
        events: list[dict[str, Any]] = []
        done_event: dict[str, Any] = {}
        terminal_event: dict[str, Any] = {}
        error_payload: dict[str, Any] = {}
        executor_result: dict[str, Any] = {}
        reduction_payload: dict[str, Any] = {}
        release_payload: dict[str, Any] = {}
        try:
            try:
                async for event in self._run_single_agent_turn(
                    request=HarnessRuntimeRequest(
                        session_id=session_id,
                        message=message,
                        runtime_profile={
                            "agent_id": agent_id,
                            "agent_profile_id": agent_profile_id,
                            "task_environment_episode": True,
                        },
                        environment_binding=environment_binding,
                        runtime_contract=runtime_contract,
                        model_selection=model_selection,
                        permission_mode=permission_mode,
                    ),
                    turn_id=turn_id,
                    history=[],
                    session_context=session_context,
                    agent_invocation_id=f"aginvoke:{turn_id}:task_episode",
                    agent_runtime_profile=agent_runtime_profile,
                    runtime_assembly=runtime_assembly,
                    runtime_branch={
                        "branch_kind": "single_agent_turn",
                        "invocation_kind": "task_environment_episode",
                        "branch_id": stable_task_environment_id("branch", episode.episode_id, turn_id),
                        "task_environment_id": environment.task_environment_id,
                        "episode_id": episode.episode_id,
                        "authority": "harness.task_environment_episode_bridge",
                    },
                    active_work_context=None,
                    current_work_boundary_receipt=_task_episode_current_work_boundary_receipt(
                        environment.to_dict(),
                        episode=episode,
                        turn_id=turn_id,
                    ),
                    max_steps=max_steps,
                ):
                    compact_event = _compact_graph_node_harness_event(event)
                    if compact_event:
                        events.append(compact_event)
                    event_type = str(dict(event or {}).get("type") or "").strip()
                    if event_type == "done":
                        done_event = dict(event or {})
                    elif event_type == "agent_turn_terminal":
                        terminal_event = dict(event or {})
                    elif event_type == "error":
                        error_payload = dict(event or {})
                executor_result = _task_episode_executor_result_from_events(
                    environment=environment.to_dict(),
                    episode=episode,
                    context_package=context_package,
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_id=agent_id,
                    agent_profile_id=agent_profile_id,
                    done_event=done_event,
                    terminal_event=terminal_event,
                    error_payload=error_payload,
                    events=tuple(events),
                    runtime_contract=runtime_contract,
                    model_selection=model_selection,
                )
            except Exception as exc:
                executor_result = _task_episode_exception_executor_result(
                    environment=environment.to_dict(),
                    episode=episode,
                    context_package=context_package,
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_id=agent_id,
                    agent_profile_id=agent_profile_id,
                    exc=exc,
                    events=tuple(events),
                )
            reduction = _record_task_episode_execution_result(
                base_dir=self.base_dir,
                environment=environment.to_dict(),
                episode=episode,
                context_package=context_package,
                executor_result=executor_result,
            )
            reduction_payload = reduction.to_dict()
        finally:
            try:
                release_projection = service.release_episode_lease(
                    task_environment_id=environment.task_environment_id,
                    lease_id=lease_projection.lease.lease_id,
                    release_reason="task_episode_execution_finished",
                    event_type="task_episode_execution_finished",
                    current_phase="task_episode",
                    current_step="lease_released",
                    progress_label="task episode execution lease released",
                )
                release_payload = release_projection.to_dict()
            except Exception as exc:
                release_payload = {
                    "authority": "harness.task_environment_episode_bridge.lease_release_error",
                    "error": str(exc) or exc.__class__.__name__,
                    "error_type": exc.__class__.__name__,
                    "lease_id": lease_projection.lease.lease_id,
                }
        task_environment_view = TaskEnvironmentViewService(self.base_dir).task_environment_detail(environment.task_environment_id)
        return {
            "ok": bool(executor_result.get("ok") is True),
            "status": str(executor_result.get("status") or ""),
            "executor_result": executor_result,
            "reduction": reduction_payload,
            "task_environment_view": task_environment_view,
            "lease": lease_projection.to_dict(),
            "lease_release": release_payload,
            "authority": "harness.task_environment_episode_bridge",
        }

    def _resolve_task_episode_agent_profile(self, episode: AgentExecutionEpisode) -> dict[str, Any]:
        profile_ref = str(episode.agent_profile_id or "").strip()
        if not profile_ref:
            return {
                "ok": False,
                "reason": "task_episode_agent_profile_missing",
                "diagnostics": {
                    "required_source": "AgentExecutionEpisode.agent_profile_id",
                    "authority": "harness.task_environment_episode_bridge.agent_profile_resolution",
                },
            }
        profile = self.agent_runtime_registry.get_profile_by_profile_id(profile_ref)
        if profile is None:
            return {
                "ok": False,
                "reason": "task_episode_agent_profile_not_registered",
                "agent_profile_id": profile_ref,
                "diagnostics": {
                    "authority": "harness.task_environment_episode_bridge.agent_profile_resolution",
                },
            }
        return {
            "ok": True,
            "profile": profile,
            "agent_profile_id": profile_ref,
            "agent_id": str(episode.agent_id or getattr(profile, "agent_id", "") or "").strip(),
            "authority": "harness.task_environment_episode_bridge.agent_profile_resolution",
        }

    def _ensure_task_episode_execution_session(
        self,
        *,
        session_id: str,
        environment: dict[str, Any],
        episode: AgentExecutionEpisode,
        context_package: TaskContextPackage,
    ) -> None:
        try:
            self.session_manager.load_session_record(session_id)
            return
        except Exception:
            pass
        self.session_manager.create_session(
            session_id=session_id,
            title=_task_episode_session_title(environment, episode=episode, context_package=context_package),
            scope={
                "task_environment_id": str(environment.get("task_environment_id") or ""),
                "task_instance_id": str(environment.get("task_instance_id") or ""),
                "episode_id": episode.episode_id,
                "scope_kind": "task_environment_episode",
            },
        )

    async def _execute_graph_agent_work_order(
        self,
        *,
        graph_config: Any,
        work_order: Any,
        max_steps: int = 12,
    ) -> dict[str, Any]:
        """Execute one graph node through the single-agent harness authority.

        GraphSystem owns scheduling and result acceptance. TaskSystem owns the
        task environment/episode ledger. This bridge only turns the already
        materialized graph node work order into a harness invocation and returns
        an executor projection for GraphSystem to reduce.
        """

        work_order_payload = _object_payload(work_order)
        preparation_payload = self._graph_node_task_preparation_payload(work_order)
        context_package = dict(preparation_payload.get("context_package") or {})
        task_environment = dict(preparation_payload.get("task_environment") or {})
        episode = dict(preparation_payload.get("episode") or {})
        agent_profile_resolution = self._resolve_graph_node_agent_profile(work_order_payload)
        if not agent_profile_resolution.get("ok"):
            return _graph_node_executor_blocked_result(
                reason=str(agent_profile_resolution.get("reason") or "graph_node_agent_profile_unresolved"),
                graph_config=graph_config,
                work_order_payload=work_order_payload,
                preparation_payload=preparation_payload,
                diagnostics=dict(agent_profile_resolution.get("diagnostics") or {}),
            )
        agent_runtime_profile = agent_profile_resolution["profile"]
        agent_profile_id = str(agent_profile_resolution.get("agent_profile_id") or "").strip()
        agent_id = str(agent_profile_resolution.get("agent_id") or "").strip()
        session_id = _graph_node_session_id(work_order_payload)
        if not session_id:
            return _graph_node_executor_blocked_result(
                reason="graph_node_session_id_missing",
                graph_config=graph_config,
                work_order_payload=work_order_payload,
                preparation_payload=preparation_payload,
                diagnostics={
                    "expected_source": "GraphNodeWorkOrder.node_session_id",
                    "node_session_policy": dict(work_order_payload.get("node_session_policy") or {}),
                },
            )
        turn_id = stable_task_environment_id(
            "turn",
            "graph-node-work-order",
            work_order_payload.get("graph_run_id"),
            work_order_payload.get("node_id"),
            work_order_payload.get("work_order_id"),
            context_package.get("package_hash"),
        )
        self._ensure_graph_node_execution_session(
            session_id=session_id,
            graph_config=graph_config,
            work_order_payload=work_order_payload,
            task_environment=task_environment,
        )
        message = _graph_node_work_order_user_message(
            work_order_payload=work_order_payload,
            context_package=context_package,
            episode=episode,
            task_environment=task_environment,
        )
        self._commit_user_message(
            session_id=session_id,
            content=message,
            provider_protocol_content=message,
            turn_id=turn_id,
            message_id=stable_task_environment_id("user", "graph-node-work-order", work_order_payload.get("work_order_id")),
            source="harness.graph_node_work_order_bridge",
        )
        runtime_contract = _graph_node_runtime_contract(
            work_order_payload=work_order_payload,
            context_package=context_package,
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            turn_id=turn_id,
        )
        environment_binding = _graph_node_environment_binding(work_order_payload, context_package=context_package)
        model_selection = _graph_node_model_selection(work_order_payload)
        workspace_root = _graph_node_workspace_root(work_order_payload, context_package=context_package)
        permission_mode = _graph_node_permission_mode(self.single_agent_runtime_host)
        runtime_assembly = assemble_runtime(
            backend_dir=self.base_dir,
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=f"aginvoke:{turn_id}:graph_node",
            runtime_contract=runtime_contract,
            model_selection=model_selection,
            environment_binding=environment_binding,
            agent_runtime_profile=agent_runtime_profile,
            tool_instances=self._all_tool_instances(),
            definitions_by_name=dict(self.single_agent_runtime_host.tool_authorization_index.definitions_by_name or {}),
            permission_mode=permission_mode,
            workspace_root=workspace_root,
        )
        self._record_turn_environment_snapshot(
            session_id=session_id,
            turn_id=turn_id,
            runtime_assembly=runtime_assembly,
            execution_scope={
                "execution_scope_kind": "graph_node_work_order",
                "task_environment_id": str(task_environment.get("task_environment_id") or context_package.get("task_environment_id") or ""),
                "task_instance_id": str(task_environment.get("task_instance_id") or ""),
                "episode_id": str(episode.get("episode_id") or ""),
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "task_run_id": str(work_order_payload.get("task_run_id") or ""),
                "node_id": str(work_order_payload.get("node_id") or ""),
                "work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "context_package_id": str(context_package.get("package_id") or ""),
                "authority": "harness.graph_node_work_order_bridge.execution_scope",
            },
        )
        session_context = _graph_node_session_context(
            work_order_payload=work_order_payload,
            context_package=context_package,
            episode=episode,
            task_environment=task_environment,
            runtime_contract=runtime_contract,
            workspace_root=workspace_root,
        )
        events: list[dict[str, Any]] = []
        done_event: dict[str, Any] = {}
        terminal_event: dict[str, Any] = {}
        error_payload: dict[str, Any] = {}
        async for event in self._run_single_agent_turn(
            request=HarnessRuntimeRequest(
                session_id=session_id,
                message=message,
                runtime_profile={
                    "agent_id": agent_id,
                    "agent_profile_id": agent_profile_id,
                    "graph_node_work_order": True,
                },
                environment_binding=environment_binding,
                runtime_contract=runtime_contract,
                model_selection=model_selection,
                permission_mode=permission_mode,
            ),
            turn_id=turn_id,
            history=[],
            session_context=session_context,
            agent_invocation_id=f"aginvoke:{turn_id}:graph_node",
            agent_runtime_profile=agent_runtime_profile,
            runtime_assembly=runtime_assembly,
            runtime_branch={
                "branch_kind": "single_agent_turn",
                "invocation_kind": "graph_node_work_order",
                "branch_id": stable_task_environment_id("branch", work_order_payload.get("work_order_id"), turn_id),
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "node_id": str(work_order_payload.get("node_id") or ""),
                "work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "authority": "harness.graph_node_work_order_bridge",
            },
            active_work_context=None,
            current_work_boundary_receipt=_graph_node_current_work_boundary_receipt(work_order_payload, turn_id=turn_id),
            max_steps=max_steps,
        ):
            compact_event = _compact_graph_node_harness_event(event)
            if compact_event:
                events.append(compact_event)
            event_type = str(dict(event or {}).get("type") or "").strip()
            if event_type == "done":
                done_event = dict(event or {})
            elif event_type == "agent_turn_terminal":
                terminal_event = dict(event or {})
            elif event_type == "error":
                error_payload = dict(event or {})
        return _graph_node_executor_result_from_events(
            graph_config=graph_config,
            work_order_payload=work_order_payload,
            preparation_payload=preparation_payload,
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            done_event=done_event,
            terminal_event=terminal_event,
            error_payload=error_payload,
            events=tuple(events),
            runtime_contract=runtime_contract,
            model_selection=model_selection,
        )

    def _graph_node_task_preparation_payload(self, work_order: Any) -> dict[str, Any]:
        sink = getattr(self.agent_runtime_services, "graph_node_task_preparation_sink", None)
        prepare = getattr(sink, "prepare_work_order", None)
        if not callable(prepare):
            return {}
        projection = prepare(work_order)
        return _object_payload(projection)

    def _resolve_graph_node_agent_profile(self, work_order_payload: dict[str, Any]) -> dict[str, Any]:
        profile_ref = _explicit_graph_node_agent_profile_id(work_order_payload)
        if not profile_ref:
            return {
                "ok": False,
                "reason": "graph_node_agent_profile_missing",
                "diagnostics": {
                    "required_sources": [
                        "GraphNodeWorkOrder.agent_profile_id",
                        "input_package.node_identity.agent_profile_id",
                        "graph_slot.node_contract.agent_assembly.agent_profile_id",
                    ],
                    "authority": "harness.graph_node_work_order_bridge.agent_profile_resolution",
                },
            }
        profile = self.agent_runtime_registry.get_profile_by_profile_id(profile_ref)
        if profile is None:
            return {
                "ok": False,
                "reason": "graph_node_agent_profile_not_registered",
                "agent_profile_id": profile_ref,
                "diagnostics": {
                    "authority": "harness.graph_node_work_order_bridge.agent_profile_resolution",
                },
            }
        return {
            "ok": True,
            "profile": profile,
            "agent_profile_id": profile_ref,
            "agent_id": _explicit_graph_node_agent_id(work_order_payload, profile=profile),
            "authority": "harness.graph_node_work_order_bridge.agent_profile_resolution",
        }

    def _ensure_graph_node_execution_session(
        self,
        *,
        session_id: str,
        graph_config: Any,
        work_order_payload: dict[str, Any],
        task_environment: dict[str, Any],
    ) -> None:
        try:
            self.session_manager.load_session_record(session_id)
            return
        except Exception:
            pass
        runtime_scope = dict(dict(work_order_payload.get("input_package") or {}).get("runtime_scope") or {})
        project_id = str(runtime_scope.get("project_id") or getattr(graph_config, "graph_id", "") or "").strip()
        self.session_manager.create_session(
            session_id=session_id,
            title=_graph_node_session_title(work_order_payload),
            scope={
                "workspace_view": "graph_node",
                "task_environment_id": str(task_environment.get("task_environment_id") or ""),
                "project_id": project_id,
            },
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
                continuation_record = continuation_selection.record
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
                if (
                    continuation_record is not None
                    or turn_memory_recovery_context
                ):
                    selection_payload = continuation_selection.to_dict()
                    if turn_memory_recovery_context:
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
                if continuation_record is not None and continuation_record.state == "terminal_read_only":
                    recent_work_outcome = self._recent_work_outcome_from_continuation_record(continuation_record.to_dict())
                    if recent_work_outcome:
                        session_context["recent_work_outcome"] = recent_work_outcome
                elif active_work_context is None:
                    recent_work_outcome = self._recent_work_outcome_from_latest_task(request.session_id)
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
            same_run_allowed=False,
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
            service = TaskWorkEnvironmentService(self.base_dir)
            request_result = service.request_control_signal(
                task_environment_id=active_work_context.task_environment_id,
                signal_kind=signal_kind,
                requested_by="user",
                reason=decision.reason or decision.action,
                payload={
                    "active_work_action": decision.action,
                    "appended_instruction": decision.appended_instruction,
                    "relation_to_current_work": decision.relation_to_current_work,
                    "evidence": decision.evidence,
                    "turn_id": turn_id,
                    "request_id": action_request.request_id,
                    "session_id": request.session_id,
                },
                idempotency_key=stable_task_environment_id(
                    "controlkey",
                    active_work_context.task_environment_id,
                    turn_id,
                    action_request.request_id,
                    signal_kind,
                ),
            )
            signal = dict(request_result.get("control_signal") or {})
            bridge = apply_task_environment_control_signal_bridge(
                base_dir=self.base_dir,
                graph_system=self.graph_system,
                environment_id=active_work_context.task_environment_id,
                signal=signal,
                bridge_graph_control=True,
            )
            handling: dict[str, Any] = {}
            bridge_status = str(bridge.get("signal_status") or "")
            if bridge_status in {"handled", "failed"}:
                handling = service.record_control_signal_handling(
                    signal_id=str(signal.get("signal_id") or ""),
                    status=bridge_status,
                    handling_result=bridge,
                )
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
            },
        )
        yield {
            "type": "active_work_control_requested",
            "task_environment_id": active_work_context.task_environment_id,
            "control_signal": signal,
            "request": dict(request_result or {}),
            "bridge": dict(bridge or {}),
            "handling": dict(handling or {}),
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
        contract_ref = str(getattr(latest, "task_run_contract_ref", "") or "").strip()
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
            diagnostics.get("latest_public_progress_note")
            or latest_step.get("public_progress_note")
            or monitor.get("latest_public_progress_note")
            or diagnostics.get("latest_step_summary")
            or monitor.get("latest_step_summary")
            or diagnostics.get("summary")
            or monitor.get("summary")
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
                    "只读事实：这是最近一个已结束、受阻或中断任务的结果记录。"
                    "你可以用它回答状态或失败原因问题，但不能把它当成 active work，"
                    "也不能基于这条记录直接续跑任务。"
                ),
                "authority": "harness.runtime.recent_work_outcome",
            }
        )

    def _recent_work_outcome_from_continuation_record(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record or {})
        if str(payload.get("state") or "") != "terminal_read_only":
            return {}
        return _drop_empty_entrypoint_payload(
            {
                "task_run_id": str(payload.get("task_run_id") or ""),
                "status": str(payload.get("task_status") or ""),
                "terminal_reason": str(dict(payload.get("diagnostics") or {}).get("terminal_reason") or ""),
                "user_visible_goal": _public_status_text(payload.get("user_visible_goal")),
                "latest_progress": _public_status_text(payload.get("latest_progress") or payload.get("model_visible_summary")),
                "latest_step_name": str(payload.get("last_completed_step") or ""),
                "artifact_refs": list(payload.get("artifact_refs") or [])[:6],
                "updated_at": float(payload.get("updated_at") or 0.0),
                "continuation_state": "terminal_read_only",
                "decision_boundary": (
                    "只读事实：这是最近一个已结束任务的结果记录。"
                    "你可以用它回答状态或失败原因问题，但不能把它当成 active work，"
                    "也不能基于这条记录直接续跑任务。"
                ),
                "authority": "harness.continuation.recent_work_outcome",
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
            if profile is not None:
                return profile
        agent_id = _first_non_empty_string(
            request_profile.get("agent_id"),
            contract_profile.get("agent_id"),
        )
        profile = self.agent_runtime_registry.get_profile(agent_id or "agent:0")
        return profile or self.agent_runtime_registry.get_profile("agent:0")

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


def _looks_like_chat_task_run(task_run: Any) -> bool:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    return task_run_id.startswith("taskrun:turn:") or task_id.startswith("task:turn:")


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


def _object_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(value or {}) if isinstance(value, dict) else {}


def _task_episode_for_execution(
    *,
    episode_repository: EpisodeRepository,
    task_environment_id: str,
    episode_id: str = "",
) -> AgentExecutionEpisode:
    target = str(episode_id or "").strip()
    if target:
        episode = episode_repository.get_episode(target)
        if episode is None:
            raise KeyError(f"AgentExecutionEpisode not found: {target}")
        return episode
    candidates = episode_repository.list_episodes(task_environment_id, limit=20)
    for episode in candidates:
        if episode.status in {"scheduled", "interrupted", "waiting_user", "waiting_tool"}:
            return episode
    if candidates:
        return candidates[0]
    raise KeyError(f"No AgentExecutionEpisode found for task environment: {task_environment_id}")


def _task_episode_context_package(
    *,
    repository: TaskEnvironmentRepository,
    environment: Any,
    episode: AgentExecutionEpisode,
) -> TaskContextPackage:
    environment_payload = environment.to_dict() if hasattr(environment, "to_dict") else dict(environment or {})
    package_id = _first_non_empty_string(
        episode.input_context_package_id,
        environment_payload.get("latest_context_package_id"),
    )
    if not package_id:
        raise KeyError(f"TaskContextPackage missing for episode: {episode.episode_id}")
    package = repository.get_context_package(package_id)
    if package is None:
        raise KeyError(f"TaskContextPackage not found: {package_id}")
    if package.task_environment_id != episode.task_environment_id:
        raise ValueError("TaskContextPackage task_environment_id does not match episode")
    if package.episode_id != episode.episode_id:
        raise ValueError("TaskContextPackage episode_id does not match episode")
    return package


def _task_episode_session_id(
    environment: dict[str, Any],
    *,
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
) -> str:
    packet_policy = dict(context_package.packet_policy or {})
    scope = dict(context_package.scope or {})
    return _first_non_empty_string(
        packet_policy.get("session_id"),
        scope.get("session_id"),
        dict(environment.get("metadata") or {}).get("session_id"),
        stable_task_environment_id("tsess", environment.get("task_environment_id"), episode.episode_id),
    )


def _task_episode_session_title(
    environment: dict[str, Any],
    *,
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
) -> str:
    scope = dict(context_package.scope or {})
    task_title = str(scope.get("task_title") or scope.get("title") or "").strip()
    return f"Task episode: {task_title or environment.get('task_environment_id') or episode.episode_id}"


def _task_episode_environment_binding(
    environment: dict[str, Any],
    *,
    context_package: TaskContextPackage,
) -> dict[str, Any]:
    task_environment_id = _first_non_empty_string(
        context_package.task_environment_id,
        environment.get("task_environment_id"),
    )
    return _drop_empty_entrypoint_payload(
        {
            "task_environment_id": task_environment_id,
            "environment_id": task_environment_id,
            "source": "task_environment_episode",
            "authority": "harness.task_environment_episode_bridge.environment_binding",
        }
    )


def _task_episode_runtime_contract(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    agent_profile_id: str,
    agent_id: str,
    turn_id: str,
) -> dict[str, Any]:
    runtime_policy = dict(dict(context_package.packet_policy or {}).get("runtime_policy") or {})
    runtime_policy["task_lifecycle_policy"] = {
        **dict(runtime_policy.get("task_lifecycle_policy") or {}),
        "request_task_run": False,
    }
    runtime_policy["context_policy"] = {
        **dict(runtime_policy.get("context_policy") or {}),
        "active_work_context": "disabled",
        "history_scope": "task_context_package",
    }
    return _drop_empty_entrypoint_payload(
        {
            "turn_id": turn_id,
            "task_environment_id": context_package.task_environment_id,
            "runtime_profile": {
                "agent_id": agent_id,
                "agent_profile_id": agent_profile_id,
                "runtime_policy": runtime_policy,
                "control_capabilities": {
                    "may_request_task_run": False,
                    "may_control_active_work": False,
                    "requires_json_action_protocol": False,
                },
            },
            "control_capabilities": {
                "may_request_task_run": False,
                "may_control_active_work": False,
                "requires_json_action_protocol": False,
            },
            "task_environment_episode_execution": {
                "task_environment_id": context_package.task_environment_id,
                "task_instance_id": episode.task_instance_id,
                "episode_id": episode.episode_id,
                "context_package_id": context_package.package_id,
                "task_environment_owner": "task_system",
                "authority": "harness.task_environment_episode_bridge.runtime_contract",
            },
            "authority": "harness.task_environment_episode_bridge.runtime_contract",
        }
    )


def _task_episode_model_selection(context_package: TaskContextPackage) -> dict[str, Any]:
    packet_policy = dict(context_package.packet_policy or {})
    model_requirement = dict(packet_policy.get("model_selection") or packet_policy.get("model_requirement") or {})
    allowed = {
        "provider",
        "provider_family",
        "model",
        "model_family",
        "credential_ref",
        "max_output_tokens",
        "preferred_output_tokens",
        "min_output_tokens",
        "action_max_output_tokens",
        "action_timeout_seconds",
        "action_long_output_timeout_seconds",
        "action_thinking_mode",
        "action_reasoning_effort",
        "timeout_seconds",
        "long_output_timeout_seconds",
        "max_retries",
        "temperature",
        "thinking_mode",
        "reasoning_effort",
        "stream_policy",
        "response_format",
        "structured_output",
        "streaming_required",
        "fallback_allowed",
    }
    return {
        key: value
        for key, value in model_requirement.items()
        if str(key or "").strip() in allowed and value not in ("", None, [], {})
    }


def _task_episode_workspace_root(
    environment: dict[str, Any],
    *,
    context_package: TaskContextPackage,
) -> str:
    scope = dict(context_package.scope or {})
    resources = dict(context_package.resource_handles or {})
    metadata = dict(environment.get("metadata") or {})
    project_binding = dict(metadata.get("project_binding") or {})
    return _first_non_empty_string(
        resources.get("workspace_root"),
        scope.get("workspace_root"),
        scope.get("project_root"),
        project_binding.get("workspace_root"),
    )


def _task_episode_session_context(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    runtime_contract: dict[str, Any],
    workspace_root: str,
) -> dict[str, Any]:
    return _drop_empty_entrypoint_payload(
        {
            "compressed_context": "",
            "provider_protocol_timeline": [],
            "compaction_generation": "0",
            "task_context_package": context_package.to_dict(),
            "task_execution_episode": episode.to_dict(),
            "task_work_environment": dict(environment or {}),
            "task_episode_execution_boundary": {
                "task_environment_owner": "task_system",
                "forbidden_actions": [
                    "rewrite_task_goal",
                    "bypass_acceptance_contract",
                    "control_parent_active_work",
                    "create_unrequested_task_run",
                ],
                "authority": "harness.task_environment_episode_bridge.execution_boundary",
            },
            "runtime_contract": runtime_contract,
            "project_binding": (
                {
                    "workspace_root": workspace_root,
                    "authority": "harness.task_environment_episode_bridge.project_binding",
                }
                if workspace_root
                else {}
            ),
        }
    )


def _task_episode_current_work_boundary_receipt(
    environment: dict[str, Any],
    *,
    episode: AgentExecutionEpisode,
    turn_id: str,
) -> dict[str, Any]:
    return {
        "receipt_id": stable_task_environment_id("cwreceipt", "task-episode", environment.get("task_environment_id"), episode.episode_id, turn_id),
        "decision": "isolated_task_environment_episode_execution",
        "active_work_control_available": False,
        "reason": "task episode workers cannot control parent active work; TaskSystem owns task environment state",
        "authority": "harness.task_environment_episode_bridge.current_work_boundary",
    }


def _task_episode_user_message(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
) -> str:
    role_contract = str(context_package.role_contract or "").strip()
    goal = str(context_package.goal or "").strip()
    payload = {
        "task_identity": {
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
        },
        "scope": dict(context_package.scope or {}),
        "acceptance": dict(context_package.acceptance or {}),
        "resource_handles": dict(context_package.resource_handles or {}),
        "project_network_handles": dict(context_package.project_network_handles or {}),
        "graph_context": dict(context_package.graph_context or {}),
        "output_contract": dict(context_package.output_contract or {}),
        "continuation_hint": str(context_package.continuation_hint or episode.continuation_hint or ""),
        "tool_authority": {
            "source": "agent_runtime_profile",
            "agent_profile_id": episode.agent_profile_id,
            "rule": "任务环境不授予工具；只能使用运行时已经展示给当前 agent profile 的工具。",
        },
    }
    return (
        "你是一名任务环境执行员。\n"
        "你只负责完成本次分派给你的工作：推进目标、整理证据、产出可归并结果，或在信息不足时给出清楚的阻塞说明。\n"
        "你不能改写任务目标，不能绕过验收边界，不能控制父级当前工作，也不能自行启动新任务。\n"
        "你只能使用运行时已经展示给你的工具；如果没有相关工具，就只基于输入上下文完成判断和交付。\n"
        "如果输入足够，请直接交付结果；如果输入不足，请说明缺少什么、为什么阻塞、下一步应由谁补充。\n\n"
        f"你的职责契约：\n{role_contract or '依据任务环境上下文推进本次 episode，并输出清晰、可归并的结果。'}\n\n"
        f"当前目标：\n{goal or '推进当前任务环境。'}\n\n"
        "你收到的任务输入、资源和输出契约如下：\n"
        f"```json\n{_json_for_prompt(payload, limit=30000)}\n```"
    )


def _task_episode_lease_ttl_seconds(context_package: TaskContextPackage) -> float:
    policy = dict(context_package.packet_policy or {})
    for key in ("lease_ttl_seconds", "ttl_seconds", "timeout_seconds", "max_runtime_seconds"):
        try:
            value = float(policy.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return max(1.0, value)
    return 2 * 60 * 60


def _task_episode_executor_result_from_events(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    session_id: str,
    turn_id: str,
    agent_id: str,
    agent_profile_id: str,
    done_event: dict[str, Any],
    terminal_event: dict[str, Any],
    error_payload: dict[str, Any],
    events: tuple[dict[str, Any], ...],
    runtime_contract: dict[str, Any],
    model_selection: dict[str, Any],
) -> dict[str, Any]:
    terminal_reason = _first_non_empty_string(
        done_event.get("terminal_reason"),
        dict(dict(terminal_event.get("event") or {}).get("payload") or {}).get("terminal_reason"),
        error_payload.get("code"),
        "completed" if done_event else "task_episode_harness_no_terminal_event",
    )
    final_answer = str(done_event.get("content") or error_payload.get("content") or error_payload.get("error") or "").strip()
    answer_channel = str(done_event.get("answer_channel") or "").strip()
    done_status = str(done_event.get("status") or "").strip()
    blocked = bool(answer_channel in {"blocked", "ask_user"} or terminal_reason in {"blocked", "ask_user"})
    failed = bool(error_payload or (done_event and done_status == "failed") or not done_event)
    status = "completed" if done_event and not blocked and not failed else ("blocked" if blocked or done_event else "failed")
    final_action_diagnostics = _final_action_diagnostics_from_done_event(done_event)
    structured_output = _structured_output_from_final_action_diagnostics(final_action_diagnostics)
    turn_run_id = _first_event_value(events, "turn_run_id")
    return {
        "ok": status == "completed",
        "status": status,
        "error": "" if status == "completed" else terminal_reason,
        "final_answer": final_answer,
        "structured_output": structured_output,
        "artifact_refs": list(structured_output.get("artifact_refs") or []) if isinstance(structured_output, dict) else [],
        "task_environment_id": context_package.task_environment_id,
        "episode_id": episode.episode_id,
        "session_id": session_id,
        "event": {"turn_id": turn_id, "turn_run_id": turn_run_id, "terminal_reason": terminal_reason},
        "diagnostics": {
            "origin_kind": "task_environment_episode",
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "context_package_id": context_package.package_id,
            "turn_id": turn_id,
            "turn_run_id": turn_run_id,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
            "final_action_diagnostics": final_action_diagnostics,
            "event_count": len(events),
            "harness_events": [dict(item) for item in events[:40]],
            "runtime_contract": {
                "control_capabilities": dict(runtime_contract.get("control_capabilities") or {}),
                "task_environment_episode_execution": dict(runtime_contract.get("task_environment_episode_execution") or {}),
                "tool_authority": "agent_runtime_profile_runtime_assembly",
            },
            "model_selection": dict(model_selection or {}),
            "authority": "harness.task_environment_episode_bridge.executor_result",
        },
        "authority": "harness.task_environment_episode_bridge",
    }


def _task_episode_exception_executor_result(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    session_id: str,
    turn_id: str,
    agent_id: str,
    agent_profile_id: str,
    exc: Exception,
    events: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    reason = str(exc) or exc.__class__.__name__
    return {
        "ok": False,
        "status": "failed",
        "error": reason,
        "final_answer": "",
        "structured_output": {},
        "artifact_refs": [],
        "task_environment_id": context_package.task_environment_id,
        "episode_id": episode.episode_id,
        "session_id": session_id,
        "event": {"turn_id": turn_id, "terminal_reason": "task_episode_harness_exception"},
        "diagnostics": {
            "origin_kind": "task_environment_episode",
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "context_package_id": context_package.package_id,
            "turn_id": turn_id,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
            "event_count": len(events),
            "harness_events": [dict(item) for item in events[:40]],
            "exception": {"type": exc.__class__.__name__, "message": reason},
            "authority": "harness.task_environment_episode_bridge.executor_exception",
        },
        "authority": "harness.task_environment_episode_bridge",
    }


def _task_episode_executor_blocked_result(
    *,
    reason: str,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "error": str(reason or "task_episode_executor_blocked"),
        "final_answer": "",
        "structured_output": {},
        "artifact_refs": [],
        "task_environment_id": context_package.task_environment_id,
        "episode_id": episode.episode_id,
        "session_id": "",
        "event": {"terminal_reason": str(reason or "task_episode_executor_blocked")},
        "diagnostics": {
            "origin_kind": "task_environment_episode",
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "context_package_id": context_package.package_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
            "recoverable_error": {
                "retryable": True,
                "error_code": str(reason or "task_episode_executor_blocked"),
            },
            **dict(diagnostics or {}),
            "authority": "harness.task_environment_episode_bridge.blocked_result",
        },
        "authority": "harness.task_environment_episode_bridge",
    }


def _record_task_episode_execution_result(
    *,
    base_dir: Path,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    executor_result: dict[str, Any],
) -> Any:
    status = str(executor_result.get("status") or "failed")
    final_answer = str(executor_result.get("final_answer") or "").strip()
    terminal_reason = str(dict(executor_result.get("event") or {}).get("terminal_reason") or executor_result.get("error") or status)
    structured_output = dict(executor_result.get("structured_output") or {})
    summary = _first_non_empty_string(
        structured_output.get("summary"),
        structured_output.get("handoff_summary"),
        final_answer[:4000],
        terminal_reason,
    )
    episode_result_status = "completed" if status == "completed" else ("blocked" if status == "blocked" else "failed")
    work_products = _task_episode_work_products(
        environment=environment,
        episode=episode,
        context_package=context_package,
        executor_result=executor_result,
        summary=summary,
    )
    result = EpisodeResult(
        result_id=stable_task_environment_id("epresult", episode.task_environment_id, episode.episode_id, status, context_package.package_hash),
        episode_id=episode.episode_id,
        task_environment_id=episode.task_environment_id,
        status=episode_result_status,  # type: ignore[arg-type]
        summary=summary if episode_result_status == "completed" else "",
        state_update_proposals=tuple(dict(item) for item in list(structured_output.get("state_update_proposals") or []) if isinstance(item, dict)),
        plan_patch=dict(structured_output.get("plan_patch") or {}),
        todo_patch=dict(structured_output.get("todo_patch") or {}),
        memory_candidates=tuple(dict(item) for item in list(structured_output.get("memory_candidates") or []) if isinstance(item, dict)),
        artifact_refs=tuple(str(item) for item in list(executor_result.get("artifact_refs") or structured_output.get("artifact_refs") or []) if str(item)),
        evidence_refs=tuple(str(item) for item in list(structured_output.get("evidence_refs") or []) if str(item)),
        blocker=terminal_reason if episode_result_status == "blocked" else "",
        continuation_hint=str(structured_output.get("continuation_hint") or ""),
        output_contract_version=str(dict(context_package.output_contract or {}).get("version") or ""),
        diagnostics={
            "executor_result": _public_task_episode_executor_projection(executor_result),
            "structured_output": structured_output,
            "context_package_id": context_package.package_id,
            "authority": "harness.task_environment_episode_bridge.episode_result",
        },
    )
    event = TaskEvent(
        event_id=stable_task_environment_id("taskevent", episode.task_environment_id, "task_episode_result_recorded", result.result_id),
        task_environment_id=episode.task_environment_id,
        task_instance_id=episode.task_instance_id,
        event_seq=0,
        event_type="task_episode_result_recorded",
        actor_kind="system",
        source_episode_id=episode.episode_id,
        idempotency_key=f"task-episode-result:{result.result_id}",
        payload={
            "episode_result_id": result.result_id,
            "episode_result_status": result.status,
            "executor_status": status,
            "work_product_ids": [item.work_product_id for item in work_products],
        },
        refs={
            "task_environment_ref": episode.task_environment_id,
            "episode_ref": episode.episode_id,
            "context_package_ref": context_package.package_id,
        },
    )
    snapshot_patch = _task_episode_result_snapshot_patch(
        status=status,
        summary=summary,
        terminal_reason=terminal_reason,
        work_products=work_products,
    )
    return TaskReducer(base_dir).reduce_episode_result(
        episode=episode,
        episode_status="completed" if status == "completed" else ("interrupted" if status == "blocked" else "failed"),
        terminal_reason=terminal_reason,
        episode_result=result,
        work_product_candidates=tuple(work_products),
        event=event,
        snapshot_patch=snapshot_patch,
        episode_diagnostics_patch={
            "executor_status": status,
            "executor_authority": str(executor_result.get("authority") or ""),
        },
    )


def _task_episode_work_products(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    executor_result: dict[str, Any],
    summary: str,
) -> tuple[WorkProduct, ...]:
    if str(executor_result.get("status") or "") != "completed":
        return ()
    final_answer = str(executor_result.get("final_answer") or "").strip()
    structured_output = dict(executor_result.get("structured_output") or {})
    if not final_answer and not structured_output:
        return ()
    output_contract = dict(context_package.output_contract or {})
    product_kind = str(output_contract.get("product_kind") or output_contract.get("kind") or "episode_output").strip()
    return (
        WorkProduct(
            work_product_id=stable_task_environment_id("workproduct", episode.task_environment_id, episode.episode_id, context_package.package_hash),
            task_environment_id=episode.task_environment_id,
            task_instance_id=episode.task_instance_id,
            source_episode_id=episode.episode_id,
            product_domain=str(output_contract.get("product_domain") or "task_episode"),
            product_kind=product_kind,
            confidence="derived",
            status="candidate",
            stable_ref=f"{episode.task_environment_id}:{episode.episode_id}:{product_kind}",
            payload={
                "summary": summary,
                "final_answer": final_answer,
                "structured_output": structured_output,
                "context_package_id": context_package.package_id,
            },
            artifact_refs=tuple(str(item) for item in list(executor_result.get("artifact_refs") or []) if str(item)),
            evidence_refs=tuple(str(item) for item in list(structured_output.get("evidence_refs") or []) if str(item)),
            downstream_refs={
                "task_environment_id": episode.task_environment_id,
                "episode_id": episode.episode_id,
            },
            metadata={
                "source_authority": "harness.task_environment_episode_bridge",
                "environment_kind": str(environment.get("environment_kind") or ""),
            },
        ),
    )


def _task_episode_result_snapshot_patch(
    *,
    status: str,
    summary: str,
    terminal_reason: str,
    work_products: tuple[WorkProduct, ...],
) -> dict[str, Any]:
    if status == "completed":
        return _drop_empty_entrypoint_payload(
            {
                "status": "ready",
                "current_phase": "task_episode",
                "current_step": "episode_completed",
                "progress_label": summary[:240],
                "blocked_reason": "",
                "continuation_hint": "Episode completed; prepare another episode if the task still needs work.",
                "latest_work_product_id": work_products[0].work_product_id if work_products else "",
            }
        )
    if status == "blocked":
        return {
            "status": "blocked",
            "current_phase": "task_episode",
            "current_step": "episode_blocked",
            "progress_label": summary[:240] or terminal_reason[:240],
            "blocked_reason": terminal_reason[:1200],
            "recovery_action": "prepare_task_episode",
        }
    return {
        "status": "failed",
        "current_phase": "task_episode",
        "current_step": "episode_failed",
        "progress_label": summary[:240] or terminal_reason[:240],
        "blocked_reason": terminal_reason[:1200],
        "recovery_action": "inspect_task_episode_failure",
    }


def _public_task_episode_executor_projection(executor_result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(executor_result.get("diagnostics") or {})
    return {
        "ok": bool(executor_result.get("ok") is True),
        "status": str(executor_result.get("status") or ""),
        "authority": str(executor_result.get("authority") or ""),
        "event": dict(executor_result.get("event") or {}),
        "diagnostics": {
            "origin_kind": str(diagnostics.get("origin_kind") or ""),
            "turn_id": str(diagnostics.get("turn_id") or ""),
            "turn_run_id": str(diagnostics.get("turn_run_id") or ""),
            "agent_profile_id": str(diagnostics.get("agent_profile_id") or ""),
            "context_package_id": str(diagnostics.get("context_package_id") or ""),
        },
    }


def _explicit_graph_node_agent_profile_id(work_order_payload: dict[str, Any]) -> str:
    input_package = dict(work_order_payload.get("input_package") or {})
    node_identity = dict(input_package.get("node_identity") or {})
    graph_slot = dict(work_order_payload.get("graph_slot") or {})
    node_contract = dict(graph_slot.get("node_contract") or {})
    agent_assembly = dict(node_contract.get("agent_assembly") or {})
    return _first_non_empty_string(
        work_order_payload.get("agent_profile_id"),
        node_identity.get("agent_profile_id"),
        agent_assembly.get("agent_profile_id"),
    )


def _explicit_graph_node_agent_id(work_order_payload: dict[str, Any], *, profile: Any) -> str:
    input_package = dict(work_order_payload.get("input_package") or {})
    node_identity = dict(input_package.get("node_identity") or {})
    graph_slot = dict(work_order_payload.get("graph_slot") or {})
    node_contract = dict(graph_slot.get("node_contract") or {})
    agent_assembly = dict(node_contract.get("agent_assembly") or {})
    return _first_non_empty_string(
        work_order_payload.get("agent_id"),
        node_identity.get("agent_id"),
        agent_assembly.get("agent_id"),
        getattr(profile, "agent_id", ""),
    )


def _graph_node_session_id(work_order_payload: dict[str, Any]) -> str:
    return str(work_order_payload.get("node_session_id") or "").strip()


def _graph_node_session_title(work_order_payload: dict[str, Any]) -> str:
    input_package = dict(work_order_payload.get("input_package") or {})
    node_identity = dict(input_package.get("node_identity") or {})
    title = str(node_identity.get("title") or "").strip()
    node_id = str(work_order_payload.get("node_id") or node_identity.get("node_id") or "").strip()
    return f"Graph node: {title or node_id or 'work order'}"


def _graph_node_environment_binding(
    work_order_payload: dict[str, Any],
    *,
    context_package: dict[str, Any],
) -> dict[str, Any]:
    input_package = dict(work_order_payload.get("input_package") or {})
    graph_context = dict(context_package.get("graph_context") or {})
    node_contract = dict(dict(work_order_payload.get("graph_slot") or {}).get("node_contract") or {})
    environment_lock = dict(node_contract.get("environment_lock") or {})
    environment_id = _first_non_empty_string(
        input_package.get("task_environment_id"),
        environment_lock.get("environment_id"),
        environment_lock.get("task_environment_id"),
        context_package.get("task_environment_ref"),
        graph_context.get("task_environment_id"),
    )
    return _drop_empty_entrypoint_payload(
        {
            "task_environment_id": environment_id,
            "environment_id": environment_id,
            "source": "graph_node_work_order",
            "authority": "harness.graph_node_work_order_bridge.environment_binding",
        }
    )


def _graph_node_model_selection(work_order_payload: dict[str, Any]) -> dict[str, Any]:
    node_contract = dict(dict(work_order_payload.get("graph_slot") or {}).get("node_contract") or {})
    model_requirement = dict(node_contract.get("model_requirement") or {})
    allowed = {
        "provider",
        "provider_family",
        "model",
        "model_family",
        "credential_ref",
        "max_output_tokens",
        "preferred_output_tokens",
        "min_output_tokens",
        "action_max_output_tokens",
        "action_timeout_seconds",
        "action_long_output_timeout_seconds",
        "action_thinking_mode",
        "action_reasoning_effort",
        "timeout_seconds",
        "long_output_timeout_seconds",
        "max_retries",
        "temperature",
        "thinking_mode",
        "reasoning_effort",
        "stream_policy",
        "response_format",
        "structured_output",
        "streaming_required",
        "fallback_allowed",
    }
    return {
        key: value
        for key, value in model_requirement.items()
        if str(key or "").strip() in allowed and value not in ("", None, [], {})
    }


def _graph_node_runtime_contract(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
    agent_profile_id: str,
    agent_id: str,
    turn_id: str,
) -> dict[str, Any]:
    node_contract = dict(dict(work_order_payload.get("graph_slot") or {}).get("node_contract") or {})
    runtime_policy = dict(node_contract.get("runtime_policy") or {})
    tool_policy = dict(node_contract.get("tool_policy") or {})
    runtime_policy["task_lifecycle_policy"] = {
        **dict(runtime_policy.get("task_lifecycle_policy") or {}),
        "request_task_run": False,
    }
    runtime_policy["context_policy"] = {
        **dict(runtime_policy.get("context_policy") or {}),
        "active_work_context": "disabled",
        "history_scope": "graph_node_context_package",
    }
    return _drop_empty_entrypoint_payload(
        {
            "turn_id": turn_id,
            "task_environment_id": str(dict(work_order_payload.get("input_package") or {}).get("task_environment_id") or ""),
            "runtime_profile": {
                "agent_id": agent_id,
                "agent_profile_id": agent_profile_id,
                "runtime_policy": runtime_policy,
                "tool_policy": tool_policy,
                "tool_exposure_policy": tool_policy,
                "control_capabilities": {
                    "may_request_task_run": False,
                    "may_control_active_work": False,
                    "requires_json_action_protocol": False,
                },
            },
            "tool_policy": tool_policy,
            "tool_exposure_policy": tool_policy,
            "control_capabilities": {
                "may_request_task_run": False,
                "may_control_active_work": False,
                "requires_json_action_protocol": False,
            },
            "graph_node_execution": {
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "node_id": str(work_order_payload.get("node_id") or ""),
                "work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "context_package_id": str(context_package.get("package_id") or ""),
                "node_worker_only": True,
                "graph_state_owner": "graph_system_loop",
                "authority": "harness.graph_node_work_order_bridge.runtime_contract",
            },
            "authority": "harness.graph_node_work_order_bridge.runtime_contract",
        }
    )


def _graph_node_permission_mode(runtime_host: Any | None) -> str:
    provider = getattr(runtime_host, "_current_permission_mode", None)
    if callable(provider):
        return normalize_permission_mode(str(provider() or "full_access"))
    return "full_access"


def _graph_node_workspace_root(
    work_order_payload: dict[str, Any],
    *,
    context_package: dict[str, Any],
) -> str:
    node_contract = dict(dict(work_order_payload.get("graph_slot") or {}).get("node_contract") or {})
    project_binding = dict(node_contract.get("project_binding") or {})
    scope = dict(context_package.get("scope") or {})
    runtime_scope = dict(scope.get("runtime_scope") or dict(work_order_payload.get("graph_state") or {}).get("runtime_scope") or {})
    return _first_non_empty_string(
        project_binding.get("workspace_root"),
        runtime_scope.get("workspace_root"),
        runtime_scope.get("project_root"),
    )


def _graph_node_session_context(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
    episode: dict[str, Any],
    task_environment: dict[str, Any],
    runtime_contract: dict[str, Any],
    workspace_root: str,
) -> dict[str, Any]:
    return _drop_empty_entrypoint_payload(
        {
            "compressed_context": "",
            "provider_protocol_timeline": [],
            "compaction_generation": "0",
            "task_context_package": context_package,
            "task_execution_episode": episode,
            "task_work_environment": task_environment,
            "graph_node_work_order": _public_graph_node_work_order_payload(work_order_payload),
            "graph_node_execution_boundary": {
                "node_worker_only": True,
                "graph_state_owner": "graph_system_loop",
                "forbidden_actions": [
                    "advance_graph_state",
                    "dispatch_downstream_node",
                    "write_graph_checkpoint",
                    "request_new_task_run",
                    "control_parent_active_work",
                ],
                "authority": "harness.graph_node_work_order_bridge.execution_boundary",
            },
            "runtime_contract": runtime_contract,
            "project_binding": (
                {
                    "workspace_root": workspace_root,
                    "authority": "harness.graph_node_work_order_bridge.project_binding",
                }
                if workspace_root
                else {}
            ),
        }
    )


def _graph_node_current_work_boundary_receipt(work_order_payload: dict[str, Any], *, turn_id: str) -> dict[str, Any]:
    return {
        "receipt_id": stable_task_environment_id("cwreceipt", "graph-node", work_order_payload.get("work_order_id"), turn_id),
        "decision": "isolated_graph_node_execution",
        "active_work_control_available": False,
        "reason": "graph node workers cannot control parent active work or graph loop state",
        "authority": "harness.graph_node_work_order_bridge.current_work_boundary",
    }


def _graph_node_work_order_user_message(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
    episode: dict[str, Any],
    task_environment: dict[str, Any],
) -> str:
    role_contract = str(context_package.get("role_contract") or work_order_payload.get("message") or "").strip()
    goal = str(context_package.get("goal") or role_contract or "完成当前图任务节点。").strip()
    payload = {
        "graph_identity": {
            "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
            "node_id": str(work_order_payload.get("node_id") or ""),
            "work_order_id": str(work_order_payload.get("work_order_id") or ""),
            "task_ref": str(work_order_payload.get("task_ref") or ""),
        },
        "task_environment": {
            "task_environment_id": str(task_environment.get("task_environment_id") or ""),
            "episode_id": str(episode.get("episode_id") or ""),
            "context_package_id": str(context_package.get("package_id") or ""),
        },
        "scope": dict(context_package.get("scope") or {}),
        "acceptance": dict(context_package.get("acceptance") or {}),
        "resource_handles": _graph_node_agent_visible_resource_handles(context_package),
        "graph_context": _graph_node_agent_visible_graph_context(context_package),
        "output_contract": dict(context_package.get("output_contract") or {}),
        "tool_authority": {
            "source": "agent_runtime_profile",
            "agent_profile_id": str(work_order_payload.get("agent_profile_id") or ""),
            "rule": "节点契约不授予工具；只能使用运行时已经展示给当前 agent profile 的工具。",
        },
    }
    return (
        "你是一名图任务节点执行员。\n"
        "你只负责当前节点的职责、判断和产物，不负责推进整张图、调度下游节点、写入图检查点或启动新任务。\n"
        "你需要严格依据节点契约、上游上下文、验收要求和输出契约完成工作。\n"
        "你只能使用运行时已经展示给你的工具；如果没有相关工具，就只基于当前输入完成判断和交付。\n"
        "如果节点信息足够，请直接完成节点产物；如果缺少必要输入，请说明阻塞原因、缺失项和建议的回传信息。\n\n"
        f"你的节点职责：\n{role_contract or goal}\n\n"
        f"当前目标：\n{goal}\n\n"
        "你收到的节点输入、上游上下文和输出契约如下：\n"
        f"```json\n{_json_for_prompt(payload, limit=28000)}\n```"
    )


def _graph_node_agent_visible_resource_handles(context_package: dict[str, Any]) -> dict[str, Any]:
    handles = dict(context_package.get("resource_handles") or {})
    return _drop_empty_entrypoint_payload(
        {
            "artifact_space_ref": str(handles.get("artifact_space_ref") or ""),
            "memory_space_ref": str(handles.get("memory_space_ref") or ""),
            "file_access_table_refs": list(handles.get("file_access_table_refs") or []),
            "artifact_repository_targets": [dict(item) for item in list(handles.get("artifact_repository_targets") or []) if isinstance(item, dict)],
            "memory_repository_targets": [dict(item) for item in list(handles.get("memory_repository_targets") or []) if isinstance(item, dict)],
        }
    )


def _graph_node_agent_visible_graph_context(context_package: dict[str, Any]) -> dict[str, Any]:
    graph_context = dict(context_package.get("graph_context") or {})
    return _drop_empty_entrypoint_payload(
        {
            "graph_identity": dict(graph_context.get("graph_identity") or {}),
            "node_contract": _graph_node_agent_visible_node_contract(graph_context.get("node_contract")),
            "edge_contracts": dict(graph_context.get("edge_contracts") or {}),
            "memory_contract": dict(graph_context.get("memory_contract") or {}),
            "loop_contract": dict(graph_context.get("loop_contract") or {}),
            "output_contract": dict(graph_context.get("output_contract") or {}),
            "node_identity": dict(graph_context.get("node_identity") or {}),
            "initial_inputs": dict(graph_context.get("initial_inputs") or {}),
            "loop_context": dict(graph_context.get("loop_context") or {}),
            "inbound_context": [dict(item) for item in list(graph_context.get("inbound_context") or []) if isinstance(item, dict)],
        }
    )


def _graph_node_agent_visible_node_contract(value: Any) -> dict[str, Any]:
    contract = dict(value or {})
    return _drop_empty_entrypoint_payload(
        {
            "contract_id": str(contract.get("contract_id") or ""),
            "compiled_contract_id": str(contract.get("compiled_contract_id") or ""),
            "node_id": str(contract.get("node_id") or ""),
            "node_kind": str(contract.get("node_kind") or ""),
            "node_class": str(contract.get("node_class") or ""),
            "node_identity": dict(contract.get("node_identity") or {}),
            "agent_assembly": dict(contract.get("agent_assembly") or {}),
            "prompt_contract": dict(contract.get("prompt_contract") or {}),
            "input_contract": dict(contract.get("input_contract") or {}),
            "acceptance_policy": dict(contract.get("acceptance_policy") or {}),
            "environment_lock": dict(contract.get("environment_lock") or {}),
            "project_binding": dict(contract.get("project_binding") or {}),
            "authority": "harness.graph_node_work_order_bridge.agent_visible_node_contract",
        }
    )


def _public_graph_node_work_order_payload(work_order_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
        "node_id": str(work_order_payload.get("node_id") or ""),
        "work_order_id": str(work_order_payload.get("work_order_id") or ""),
        "task_run_id": str(work_order_payload.get("task_run_id") or ""),
        "node_session_id": str(work_order_payload.get("node_session_id") or ""),
        "node_session_policy": dict(work_order_payload.get("node_session_policy") or {}),
        "agent_id": str(work_order_payload.get("agent_id") or ""),
        "agent_profile_id": str(work_order_payload.get("agent_profile_id") or ""),
        "expected_result_contract": dict(work_order_payload.get("expected_result_contract") or {}),
    }


def _compact_graph_node_harness_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event or {})
    event_type = str(payload.get("type") or "").strip()
    if not event_type:
        return {}
    if event_type == "done":
        final_action_diagnostics = dict(payload.get("final_action_diagnostics") or {}) if isinstance(payload.get("final_action_diagnostics"), dict) else {}
        return {
            "type": "done",
            "status": str(payload.get("status") or ""),
            "terminal_reason": str(payload.get("terminal_reason") or ""),
            "answer_channel": str(payload.get("answer_channel") or ""),
            "answer_source": str(payload.get("answer_source") or ""),
            "content_chars": len(str(payload.get("content") or "")),
            "final_action_diagnostic_keys": sorted(str(key) for key in final_action_diagnostics.keys()),
        }
    if event_type == "error":
        return {
            "type": "error",
            "code": str(payload.get("code") or ""),
            "content": str(payload.get("content") or payload.get("error") or "")[:500],
        }
    if event_type == "agent_turn_terminal":
        raw_event = dict(payload.get("event") or {})
        terminal_payload = dict(raw_event.get("payload") or {})
        return {
            "type": "agent_turn_terminal",
            "event_id": str(raw_event.get("event_id") or ""),
            "turn_run_id": str(raw_event.get("run_id") or raw_event.get("stream_id") or ""),
            "status": str(terminal_payload.get("status") or ""),
            "terminal_reason": str(terminal_payload.get("terminal_reason") or ""),
        }
    if event_type == "harness_run_started":
        turn_run = dict(payload.get("turn_run") or {})
        return {
            "type": "harness_run_started",
            "turn_run_id": str(turn_run.get("turn_run_id") or ""),
            "status": str(turn_run.get("status") or ""),
        }
    if event_type == "turn_runtime_control_signal_observed":
        raw_event = dict(payload.get("event") or {})
        signal = dict(dict(raw_event.get("payload") or {}).get("runtime_control_signal") or {})
        return {
            "type": "turn_runtime_control_signal_observed",
            "signal_kind": str(signal.get("signal_kind") or ""),
            "runtime_control_state": str(signal.get("runtime_control_state") or ""),
            "used_tool_iterations": signal.get("used_tool_iterations"),
            "max_tool_iterations": signal.get("max_tool_iterations"),
            "runtime_control_signal_ref": str(signal.get("runtime_control_signal_ref") or ""),
        }
    if event_type in {
        "single_agent_turn_started",
        "runtime_branch_decided",
        "tool_batch_planned",
        "tool_batch_group_completed",
        "tool_observation",
        "model_action_admission",
    }:
        return {"type": event_type}
    return {}


def _graph_node_executor_result_from_events(
    *,
    graph_config: Any,
    work_order_payload: dict[str, Any],
    preparation_payload: dict[str, Any],
    session_id: str,
    turn_id: str,
    agent_profile_id: str,
    agent_id: str,
    done_event: dict[str, Any],
    terminal_event: dict[str, Any],
    error_payload: dict[str, Any],
    events: tuple[dict[str, Any], ...],
    runtime_contract: dict[str, Any],
    model_selection: dict[str, Any],
) -> dict[str, Any]:
    terminal_reason = _first_non_empty_string(
        done_event.get("terminal_reason"),
        dict(dict(terminal_event.get("event") or {}).get("payload") or {}).get("terminal_reason"),
        error_payload.get("code"),
        "completed" if done_event else "graph_node_harness_no_terminal_event",
    )
    final_answer = str(done_event.get("content") or error_payload.get("content") or error_payload.get("error") or "").strip()
    answer_channel = str(done_event.get("answer_channel") or "").strip()
    done_status = str(done_event.get("status") or "").strip()
    blocked = bool(answer_channel in {"blocked", "ask_user"} or terminal_reason in {"blocked", "ask_user"})
    failed = bool(error_payload or (done_event and done_status == "failed") or not done_event)
    status = "completed" if done_event and not blocked and not failed else ("blocked" if blocked or done_event else "failed")
    final_action_diagnostics = _final_action_diagnostics_from_done_event(done_event)
    episode = dict(preparation_payload.get("episode") or {})
    task_environment = dict(preparation_payload.get("task_environment") or {})
    node_execution_id = str(episode.get("episode_id") or "") or stable_task_environment_id(
        "nodeexec",
        work_order_payload.get("graph_run_id"),
        work_order_payload.get("node_id"),
        work_order_payload.get("work_order_id"),
    )
    turn_run_id = _first_event_value(events, "turn_run_id")
    task_execution_payload = {
        "execution_id": node_execution_id,
        "episode_id": str(episode.get("episode_id") or ""),
        "task_environment_id": str(task_environment.get("task_environment_id") or ""),
        "session_id": session_id,
        "task_ref": str(work_order_payload.get("task_ref") or work_order_payload.get("node_id") or ""),
        "status": status,
        "terminal_reason": terminal_reason,
        "diagnostics": {
            "origin": {"origin_kind": "graph_node_assigned"},
            "origin_kind": "graph_node_assigned",
            "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
            "graph_config_id": str(getattr(graph_config, "config_id", "") or work_order_payload.get("config_id") or ""),
            "graph_work_order_id": str(work_order_payload.get("work_order_id") or ""),
            "graph_node_id": str(work_order_payload.get("node_id") or ""),
            "runtime_scope": dict(dict(work_order_payload.get("input_package") or {}).get("runtime_scope") or {}),
            "task_environment_id": str(task_environment.get("task_environment_id") or ""),
            "episode_id": str(episode.get("episode_id") or ""),
            "turn_id": turn_id,
            "turn_run_id": turn_run_id,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "final_answer": final_answer,
            "final_action_diagnostics": final_action_diagnostics,
            "event_count": len(events),
            "harness_events": [dict(item) for item in events[:40]],
            "runtime_contract": {
                "control_capabilities": dict(runtime_contract.get("control_capabilities") or {}),
                "graph_node_execution": dict(runtime_contract.get("graph_node_execution") or {}),
                "tool_authority": "agent_runtime_profile_runtime_assembly",
            },
            "model_selection": dict(model_selection or {}),
            "authority": "harness.graph_node_work_order_bridge.executor_result",
        },
    }
    return {
        "ok": status == "completed",
        "status": status,
        "error": "" if status == "completed" else terminal_reason,
        "final_answer": final_answer,
        "artifact_refs": [],
        "task_execution": task_execution_payload,
        "event": {"turn_id": turn_id, "turn_run_id": turn_run_id, "terminal_reason": terminal_reason},
        "lifecycle": {
            "executor": "harness.graph_node_work_order_bridge",
            "status": status,
            "event_count": len(events),
        },
        "authority": "harness.graph_node_work_order_bridge",
    }


def _graph_node_executor_blocked_result(
    *,
    reason: str,
    graph_config: Any,
    work_order_payload: dict[str, Any],
    preparation_payload: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    episode = dict(preparation_payload.get("episode") or {})
    node_execution_id = str(episode.get("episode_id") or "") or stable_task_environment_id(
        "nodeexec",
        work_order_payload.get("graph_run_id"),
        work_order_payload.get("node_id"),
        work_order_payload.get("work_order_id"),
    )
    task_environment = dict(preparation_payload.get("task_environment") or {})
    return {
        "ok": False,
        "status": "blocked",
        "error": str(reason or "graph_node_executor_blocked"),
        "final_answer": "",
        "artifact_refs": [],
        "task_execution": {
            "execution_id": node_execution_id,
            "episode_id": str(episode.get("episode_id") or ""),
            "task_environment_id": str(task_environment.get("task_environment_id") or ""),
            "session_id": str(work_order_payload.get("node_session_id") or ""),
            "task_ref": str(work_order_payload.get("task_ref") or work_order_payload.get("node_id") or ""),
            "status": "blocked",
            "terminal_reason": str(reason or "graph_node_executor_blocked"),
            "diagnostics": {
                "origin": {"origin_kind": "graph_node_assigned"},
                "origin_kind": "graph_node_assigned",
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "graph_config_id": str(getattr(graph_config, "config_id", "") or work_order_payload.get("config_id") or ""),
                "graph_work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "graph_node_id": str(work_order_payload.get("node_id") or ""),
                "recoverable_error": {
                    "retryable": True,
                    "error_code": str(reason or "graph_node_executor_blocked"),
                },
                **dict(diagnostics or {}),
                "authority": "harness.graph_node_work_order_bridge.blocked_result",
            },
        },
        "event": {"terminal_reason": str(reason or "graph_node_executor_blocked")},
        "lifecycle": {"executor": "harness.graph_node_work_order_bridge", "status": "blocked"},
        "authority": "harness.graph_node_work_order_bridge",
    }


def _final_action_diagnostics_from_done_event(done_event: dict[str, Any]) -> dict[str, Any]:
    value = dict(done_event or {}).get("final_action_diagnostics")
    if not isinstance(value, dict):
        return {}
    payload = {
        str(key): item
        for key, item in dict(value or {}).items()
        if str(key).strip() and item not in ("", [], {}, None)
    }
    structured_output = payload.get("structured_output")
    node_output = payload.get("node_output")
    if isinstance(structured_output, dict) and not isinstance(node_output, dict):
        payload["node_output"] = dict(structured_output)
    if isinstance(node_output, dict) and not isinstance(structured_output, dict):
        payload["structured_output"] = dict(node_output)
    return payload


def _structured_output_from_final_action_diagnostics(final_action_diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(final_action_diagnostics or {})
    for key in ("structured_output", "node_output"):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_event_value(events: tuple[dict[str, Any], ...], key: str) -> str:
    target = str(key or "").strip()
    for event in events:
        value = str(dict(event or {}).get(target) or "").strip()
        if value:
            return value
    return ""


def _json_for_prompt(payload: Any, *, limit: int) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    max_chars = max(1000, int(limit or 1000))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>"


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
