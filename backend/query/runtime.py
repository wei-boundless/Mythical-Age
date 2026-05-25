from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from evidence import EvidenceOrchestrator, PDFWorker, RetrievalWorker, StructuredDataWorker
from evidence.output_policy import RAGEvidenceOutputPolicy
from observability import build_debug_trace_event, start_turn_trace
from context_system import RuntimeContextManager
from runtime import ModelResponseRuntimeExecutor, ModelRuntimeError, TaskRunLoop, ToolRuntimeExecutor
from runtime.shared.history_assembler import assemble_runtime_history
from agent_system.assembly.runtime_chain import AgentRuntimeChainAssembler
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from orchestration import (
    build_base_unit_catalog,
    build_user_message_commit_decision,
)
from project_layout import ProjectLayout
from prompting import build_static_prompt, build_system_prompt
from query.models import QueryRequest
from request_intent import analyze_memory_intent
from task_system.orders.intent_decision import TaskIntentDecisionService
from task_system.orders.models import ConversationTurn
from task_system.orders.continuation_recovery import (
    TaskContinuationRecoveryDecision,
    recover_task_order_continuation,
)
from task_system.orders.order_factory import TaskOrderCreation, TaskOrderFactory
from task_system.orders.order_registry import TaskOrderRegistry

logger = logging.getLogger(__name__)


class QueryRuntime:
    """Thin API adapter for the new single-agent runtime chain.

    The old query layer used to own planning, tool routing, worker orchestration,
    follow-up execution, context restore, and writeback. Those responsibilities
    are intentionally gone from this class. QueryRuntime now only accepts API
    input, emits stream events, and calls the adopted single-agent runtime lane.
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
        self.agent_runtime_chain = AgentRuntimeChainAssembler(
            base_dir=base_dir,
            memory_facade=memory_facade,
            skill_registry=skill_registry,
            tool_registry=getattr(tool_runtime, "registry", None),
        )
        self.runtime_context_manager = RuntimeContextManager(self.build_static_system_prompt_for_session)
        self.task_run_loop = TaskRunLoop(
            ProjectLayout.from_backend_dir(base_dir).runtime_state_dir,
            backend_dir=base_dir,
            evidence_orchestrator=self.evidence_orchestrator,
            permission_mode_provider=_permission_mode_provider(
                permission_service=permission_service,
                settings_service=settings_service,
            ),
        )
        self.task_order_registry = TaskOrderRegistry(self.task_run_loop.state_index)
        self.task_intent_decision_service = TaskIntentDecisionService()
        self.task_order_factory = TaskOrderFactory()

        self.runtime_components = {
            "query_runtime": "adapter_only",
            "single_agent_runtime": "active",
            "evidence_orchestrator": "active" if retrieval_enabled else "disabled_missing_retrieval_service",
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
        context_package = self.agent_runtime_chain.build_context_package(
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
            task_order_creation = self._resolve_or_create_task_order(
                session_id=request.session_id,
                turn_id=turn_id,
                message=request.message,
                task_selection=dict(request.task_selection or {}),
                task_order_intent=dict(request.task_order_intent or {}),
            )
            task_id = f"taskinst:{turn_id}:{_task_instance_suffix(dict(request.task_selection or {}))}"
            input_commit_gate = self._commit_user_message(
                session_id=request.session_id,
                content=request.message,
                task_id=task_id,
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
                yield {
                    "type": "task_intent_decision",
                    "conversation_turn": task_order_creation.conversation_turn.to_dict(),
                    "decision": task_order_creation.intent_decision.to_dict(),
                }
                if task_order_creation.draft is not None:
                    yield {
                        "type": "task_order_draft",
                        "draft": task_order_creation.draft.to_dict(),
                        "conversation_turn": task_order_creation.conversation_turn.to_dict(),
                        "decision": task_order_creation.intent_decision.to_dict(),
                    }
                if task_order_creation.order is not None:
                    yield {
                        "type": "task_order_projection",
                        **task_order_creation.projection(),
                    }
                recovery_decision = dict(task_order_creation.conversation_turn.metadata or {}).get(
                    "task_continuation_recovery"
                )
                if isinstance(recovery_decision, dict) and recovery_decision:
                    yield {
                        "type": "task_continuation_recovery",
                        "decision": recovery_decision,
                    }

                image_generation = dict(request.image_generation or {})
                image_model = str(image_generation.get("model") or "").strip().lower()
                if image_model in {"gpt-image-2", "image-2"} or str(image_generation.get("mode") or "").strip().lower() == "generate":
                    from soul.image_asset_service import SoulImageAssetError, SoulImageAssetService

                    asset_kind = str(image_generation.get("asset_kind") or "chat").strip() or "chat"
                    size = str(image_generation.get("size") or "1024x1024").strip() or "1024x1024"
                    target_id = str(image_generation.get("target_id") or turn_id).strip() or turn_id
                    try:
                        generated = await SoulImageAssetService(self.base_dir).generate(
                            prompt=request.message,
                            target_id=target_id,
                            asset_kind=asset_kind,
                            size=size,
                            overwrite=bool(image_generation.get("overwrite") or False),
                        )
                    except SoulImageAssetError as exc:
                        yield {"type": "error", "error": str(exc), "code": "provider_unavailable"}
                        return
                    asset_path = str(generated.get("asset_path") or "").strip()
                    revised_prompt = str(generated.get("revised_prompt") or "").strip()
                    content = "已生成图像。"
                    await self._apply_assistant_message_commit_async(
                        request.session_id,
                        {
                            "role": "assistant",
                            "content": content,
                            "image": {
                                "src": asset_path,
                                "alt": request.message,
                                "caption": revised_prompt or "",
                            } if asset_path else None,
                            "turn_id": turn_id,
                            "answer_channel": "image",
                            "answer_source": "soul_image_asset_service",
                            "answer_canonical_state": "complete",
                            "answer_persist_policy": "store",
                            "answer_finalization_policy": "final",
                        },
                    )
                    yield {
                        "type": "done",
                        "content": content,
                        "image": {
                            "src": asset_path,
                            "alt": request.message,
                            "caption": revised_prompt or "",
                        } if asset_path else None,
                    }
                    return

                memory_intent = analyze_memory_intent(request.message)
                agent_runtime_profile = self.agent_runtime_registry.get_profile("agent:0")
                runtime_task_selection = _task_selection_for_runtime(
                    request_task_selection=dict(request.task_selection or {}),
                    task_order_creation=task_order_creation,
                    turn_id=turn_id,
                )
                async for event in self.task_run_loop.run_single_agent_stream(
                    session_id=request.session_id,
                    task_id=task_id,
                    user_message=request.message,
                    history=history,
                    source="query_runtime.adapter",
                    agent_runtime_chain=self.agent_runtime_chain,
                    model_response_executor=self.model_response_executor,
                    runtime_context_manager=self.runtime_context_manager,
                    memory_intent=memory_intent,
                    task_selection=runtime_task_selection,
                    task_order_ref=(
                        task_order_creation.order.to_dict()
                        if task_order_creation.order is not None
                        else None
                    ),
                    task_order_run_ref=(
                        task_order_creation.order_run.to_dict()
                        if task_order_creation.order_run is not None
                        else None
                    ),
                    execution_channel_ref=(
                        task_order_creation.execution_channel.to_dict()
                        if task_order_creation.execution_channel is not None
                        else None
                    ),
                    task_execution_envelope_ref=(
                        task_order_creation.envelope.to_dict()
                        if task_order_creation.envelope is not None
                        else None
                    ),
                    assistant_message_committer=lambda payload: self._apply_assistant_message_commit_async(
                        request.session_id,
                        {**dict(payload or {}), "turn_id": turn_id},
                    ),
                    tool_runtime_executor=self.tool_runtime_executor,
                    tool_instances=self._all_tool_instances(),
                    agent_runtime_profile=agent_runtime_profile,
                    search_policy=list(request.search_policy) if request.search_policy is not None else None,
                    model_selection=dict(request.model_selection or {}),
                ):
                    if (
                        event.get("type") == "runtime_loop_started"
                        and task_order_creation.order_run is not None
                    ):
                        task_run = dict(event.get("task_run") or {})
                        agent_run = dict(event.get("agent_run") or {})
                        coordination_run = dict(event.get("coordination_run") or {})
                        self.task_order_registry.bind_runtime(
                            order_run_id=task_order_creation.order_run.run_id,
                            task_run_id=str(task_run.get("task_run_id") or ""),
                            execution_channel_id=(
                                task_order_creation.execution_channel.channel_id
                                if task_order_creation.execution_channel is not None
                                else ""
                            ),
                            coordination_run_id=str(coordination_run.get("coordination_run_id") or ""),
                            agent_run_id=str(agent_run.get("agent_run_id") or ""),
                            status="running",
                            diagnostics={"bound_by": "query_runtime.task_order_binding"},
                        )
                    self._maybe_update_task_order_run_from_event(
                        creation=task_order_creation,
                        event=event,
                    )
                    yield event
        except Exception as exc:
            logger.exception("QueryRuntime failed while streaming request.")
            failure_text = self._user_visible_error(exc)
            error_payload = {"type": "error", "error": failure_text}
            if isinstance(exc, ModelRuntimeError):
                error_payload["code"] = exc.code
            yield error_payload

    def _maybe_update_task_order_run_from_event(
        self,
        *,
        creation: TaskOrderCreation,
        event: dict[str, Any],
    ) -> None:
        if creation.order_run is None:
            return
        event_type = str(event.get("type") or "")
        runtime_event = dict(event.get("event") or {}) if event_type == "runtime_loop_event" else {}
        runtime_event_type = str(runtime_event.get("event_type") or "")
        payload = dict(runtime_event.get("payload") or {}) if runtime_event else dict(event)
        if (
            event_type not in {"done", "error", "stopped"}
            and runtime_event_type not in {
                "loop_terminal",
                "loop_error",
                "runtime_blocked_before_assembly",
            }
        ):
            return
        raw_status = str(payload.get("status") or "")
        terminal_reason = str(payload.get("terminal_reason") or payload.get("reason") or "")
        runtime_event_task_run_id = str(runtime_event.get("task_run_id") or "")
        bound_task_run_id = str(creation.order_run.task_run_id or "")
        task_run_id = bound_task_run_id or runtime_event_task_run_id
        if event_type == "done":
            raw_status = raw_status or "completed"
            terminal_reason = terminal_reason or "completed"
        elif event_type == "error" or runtime_event_type == "loop_error":
            raw_status = raw_status or "failed"
            terminal_reason = terminal_reason or str(payload.get("error") or "error")
        elif event_type == "stopped":
            raw_status = raw_status or "cancelled"
            terminal_reason = terminal_reason or "stopped"
        elif runtime_event_type == "runtime_blocked_before_assembly":
            raw_status = raw_status or "failed"
            terminal_reason = terminal_reason or str(payload.get("reason") or "runtime_blocked_before_assembly")
        if raw_status in {"completed", "failed", "cancelled"}:
            order_run_status = raw_status
        elif raw_status == "aborted":
            order_run_status = "cancelled"
        else:
            order_run_status = "failed" if terminal_reason and terminal_reason != "completed" else "completed"
        diagnostics = {
            "finished_by": "query_runtime.runtime_terminal",
            "terminal_event_type": event_type,
            "runtime_event_type": runtime_event_type,
        }
        if bound_task_run_id:
            self.task_order_registry.sync_runtime_terminal(
                task_run_id=bound_task_run_id,
                status=order_run_status,
                terminal_reason=terminal_reason,
                diagnostics=diagnostics,
            )
            return
        self.task_order_registry.finish_order_run(
            order_run_id=creation.order_run.run_id,
            status=order_run_status,
            terminal_reason=terminal_reason,
            diagnostics=diagnostics,
        )

    def _create_task_order_for_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        message: str,
        task_selection: dict[str, Any],
        task_order_intent: dict[str, Any],
    ) -> TaskOrderCreation:
        now = time.time()
        turn = ConversationTurn(
            turn_id=turn_id,
            session_id=session_id,
            user_message_ref=f"session:{session_id}:message:{turn_id}",
            created_at=now,
            status="created",
            metadata={"source": "query_runtime.adapter"},
        )
        decision = self.task_intent_decision_service.decide(
            turn_id=turn_id,
            message=message,
            task_selection=task_selection,
            task_order_intent=task_order_intent,
            created_at=now,
        )
        creation = self.task_order_factory.create_from_conversation_turn(
            conversation_turn=turn,
            intent_decision=decision,
            message=message,
            task_selection=task_selection,
            task_order_intent=task_order_intent,
        )
        self.task_order_registry.upsert_creation(creation)
        return creation

    def _resolve_or_create_task_order(
        self,
        *,
        session_id: str,
        turn_id: str,
        message: str,
        task_selection: dict[str, Any],
        task_order_intent: dict[str, Any],
    ) -> TaskOrderCreation:
        existing = self._existing_task_order_creation(
            session_id=session_id,
            task_selection=task_selection,
            task_order_intent=task_order_intent,
        )
        if existing is not None:
            self._claim_existing_task_order_run(existing)
            return existing
        if _has_task_order_reference(task_selection, task_order_intent):
            raise ValueError("Task order reference was not found or does not belong to this session.")
        recovery = self._recover_implicit_task_order_continuation(
            session_id=session_id,
            message=message,
        )
        if recovery.decision_kind == "selected":
            recovered = self._existing_task_order_creation(
                session_id=session_id,
                task_selection={
                    "task_order_id": recovery.selected_order_id,
                    "task_order_run_id": recovery.selected_order_run_id,
                },
                task_order_intent={},
            )
            if recovered is None:
                raise ValueError("Recovered task order reference was not found or does not belong to this session.")
            self._claim_existing_task_order_run(recovered)
            return self._with_continuation_recovery_metadata(recovered, recovery)
        if recovery.decision_kind == "clarify":
            return self._create_task_order_for_turn(
                session_id=session_id,
                turn_id=turn_id,
                message=message,
                task_selection={
                    **dict(task_selection or {}),
                    "task_continuation_recovery": recovery.to_dict(),
                },
                task_order_intent={
                    **dict(task_order_intent or {}),
                    "continuation_recovery": recovery.to_dict(),
                    "action": "clarify_task_continuation",
                },
            )
        return self._create_task_order_for_turn(
            session_id=session_id,
            turn_id=turn_id,
            message=message,
            task_selection=task_selection,
            task_order_intent=task_order_intent,
        )

    def _recover_implicit_task_order_continuation(
        self,
        *,
        session_id: str,
        message: str,
    ) -> TaskContinuationRecoveryDecision:
        return recover_task_order_continuation(
            message=message,
            session_orders=self.task_run_loop.state_index.list_session_task_orders(session_id),
            session_runs=self.task_run_loop.state_index.list_session_task_order_runs(session_id),
        )

    @staticmethod
    def _with_continuation_recovery_metadata(
        creation: TaskOrderCreation,
        recovery: TaskContinuationRecoveryDecision,
    ) -> TaskOrderCreation:
        return TaskOrderCreation(
            conversation_turn=ConversationTurn(
                **{
                    **creation.conversation_turn.to_dict(),
                    "metadata": {
                        **dict(creation.conversation_turn.metadata or {}),
                        "task_continuation_recovery": recovery.to_dict(),
                    },
                }
            ),
            intent_decision=creation.intent_decision,
            order=creation.order,
            order_run=creation.order_run,
            execution_channel=creation.execution_channel,
            envelope=creation.envelope,
            draft=creation.draft,
        )

    def _claim_existing_task_order_run(self, creation: TaskOrderCreation) -> None:
        if creation.order_run is None:
            raise ValueError("Task order reference is missing its executable run.")
        ok, current_status = self.task_order_registry.claim_order_run_for_execution(
            order_run_id=creation.order_run.run_id,
            diagnostics={"claimed_by": "query_runtime.resolve_existing_order"},
        )
        if not ok:
            raise ValueError(
                f"Task order run is not executable from status {current_status}; create a new run instead."
            )

    def _existing_task_order_creation(
        self,
        *,
        session_id: str,
        task_selection: dict[str, Any],
        task_order_intent: dict[str, Any],
    ) -> TaskOrderCreation | None:
        refs = {
            **dict(task_selection or {}),
            **dict(task_order_intent or {}),
        }
        order_run_id = str(
            refs.get("task_order_run_id")
            or refs.get("order_run_id")
            or refs.get("run_id")
            or ""
        ).strip()
        if order_run_id:
            creation = self.task_order_registry.creation_for_order_run(order_run_id)
            if creation is not None and creation.conversation_turn.session_id == session_id:
                return creation
            return None
        order_id = str(
            refs.get("task_order_id")
            or refs.get("order_id")
            or refs.get("task_order_ref")
            or ""
        ).strip()
        if order_id:
            creation = self.task_order_registry.creation_for_order(order_id)
            if creation is not None and creation.conversation_turn.session_id == session_id:
                return creation
            return None
        return None

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
        if trace is not None:
            trace.annotate(
                {
                    "app.query_runtime_role": "adapter_only",
                    "app.runtime_channel": "single_agent_runtime",
                }
            )
        async for event in self.astream(
            QueryRequest(
                session_id=session_id,
                message=message,
                history=history,
                search_policy=list(search_policy) if search_policy is not None else None,
            )
        ):
            yield event

    def run_memory_maintenance(self, session_id: str, *, durable: bool = True) -> dict[str, Any]:
        history = self.session_manager.load_session(session_id)
        receipt = self.memory_facade.run_memory_maintenance_after_commit(
            session_id=session_id,
            messages=history,
            durable_lane_enabled=durable,
        )
        return receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt or {})

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


def _task_instance_suffix(task_selection: dict[str, Any]) -> str:
    selected_task_id = str(task_selection.get("selected_task_id") or "").strip()
    if selected_task_id:
        tail = selected_task_id.split(".")[-1].split(":")[-1].strip()
        if tail:
            return tail
    return "general_response"


def _has_task_order_reference(
    task_selection: dict[str, Any],
    task_order_intent: dict[str, Any],
) -> bool:
    refs = {
        **dict(task_selection or {}),
        **dict(task_order_intent or {}),
    }
    return any(
        str(refs.get(key) or "").strip()
        for key in (
            "task_order_id",
            "order_id",
            "task_order_ref",
            "task_order_run_id",
            "order_run_id",
            "run_id",
            "execution_channel_id",
            "task_execution_envelope_id",
        )
    )


def _task_selection_for_runtime(
    *,
    request_task_selection: dict[str, Any],
    task_order_creation: TaskOrderCreation,
    turn_id: str,
) -> dict[str, Any]:
    order_projection = {}
    if task_order_creation.order is not None:
        order_projection = dict(
            dict(task_order_creation.order.input_contract or {}).get("task_selection_projection")
            or {}
        )
    envelope_projection = {}
    if task_order_creation.envelope is not None:
        envelope_projection = dict(
            dict(task_order_creation.envelope.context_package or {}).get("task_selection_projection")
            or {}
        )
    return {
        **order_projection,
        **envelope_projection,
        **dict(request_task_selection or {}),
        "turn_id": turn_id,
    }

