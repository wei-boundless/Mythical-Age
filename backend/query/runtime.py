from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import os
import re
from pathlib import PurePosixPath
from typing import Any

from agents import MAIN_AGENT
from observability import build_debug_trace_event, start_turn_trace
from query.answer_assembler import AnswerAssembler
from query.answer_finalizer import RAGEvidencePack
from query.context_models import MainContextState, TaskSummaryRef
from query.evidence_orchestrator import EvidenceOrchestrator
from query.evidence_graph import EvidenceArtifactGraph
from query.evidence_store import BindingCandidateStore, EvidenceGraphStore
from query.followup_resolver import QueryFollowupResolver
from query.models import QueryContext, QueryExecutionPlan, QueryPlan, QueryRequest
from query.pdf_worker import PDFWorker
from query.retrieval_worker import RetrievalWorker
from query.structured_data_worker import StructuredDataWorker
from query.table_materializer import TableMaterializer
from query.binding_models import StructuredDatasetBinding
from query.output_boundary import AssistantOutputBoundary, contains_internal_protocol, sanitize_visible_assistant_content
from query.runtime_context_state import RuntimeContextState
from query.runtime_followup import RuntimeFollowupCoordinator
from query.runtime_persistence import RuntimePersistenceAssembler
from query.runtime_output_policy import RuntimeOutputPolicy
from query.runtime_tools import RuntimeToolBridge
from query.prompt_builder import build_system_prompt
from query.planner import QueryPlanner
from query.worker_models import WorkerExecutionPlan, WorkerRequest
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content
from skill_system import SkillDefinition
from tasks.coordinator import TaskCoordinator
from tools.contracts import ToolContractDecision, ToolContractGate, ToolScope
from understanding import QueryUnderstanding, analyze_memory_intent, evaluate_memory_write

logger = logging.getLogger(__name__)

HIDDEN_SKILL_NOTICE = "[internal skill instructions hidden]"


class QueryRuntime:
    def __init__(
        self,
        *,
        base_dir,
        settings_service,
        session_manager,
        memory_facade,
        retrieval_service,
        tool_runtime,
        skill_registry,
        permission_service,
        model_runtime: ModelRuntime,
        task_coordinator: TaskCoordinator,
    ) -> None:
        self.base_dir = base_dir
        self.settings_service = settings_service
        self.session_manager = session_manager
        self.memory_facade = memory_facade
        self.retrieval_service = retrieval_service
        self.tool_runtime = tool_runtime
        self.skill_registry = skill_registry
        self.permission_service = permission_service
        self.model_runtime = model_runtime
        self.task_coordinator = task_coordinator
        self.followup_resolver = QueryFollowupResolver(
            task_coordinator,
            session_state_loader=self._load_session_binding_snapshot,
        )
        self.answer_assembler = AnswerAssembler()
        self._output_policy = RuntimeOutputPolicy(
            model_runtime=model_runtime,
            stringify_tool_output=self._stringify_tool_output,
        )
        self._persistence = RuntimePersistenceAssembler(hidden_skill_notice=HIDDEN_SKILL_NOTICE)
        self.binding_candidate_store = BindingCandidateStore()
        self.evidence_graph_store = EvidenceGraphStore()
        self.retrieval_worker = RetrievalWorker(retrieval_service=retrieval_service)
        self.pdf_worker = PDFWorker(root_dir=base_dir)
        self.structured_data_worker = StructuredDataWorker(tool_runtime=tool_runtime)
        self.table_materializer = TableMaterializer(root_dir=base_dir)
        self.evidence_orchestrator = EvidenceOrchestrator(
            retrieval_worker=self.retrieval_worker,
            pdf_worker=self.pdf_worker,
            structured_data_worker=self.structured_data_worker,
            candidate_store=self.binding_candidate_store,
            graph_store=self.evidence_graph_store,
            output_policy=self._output_policy,
        )
        self._session_memory_projection: dict[str, dict[str, Any]] = {}
        self._context_state = RuntimeContextState(
            memory_facade=memory_facade,
            session_memory_projection=self._session_memory_projection,
            normalize_pdf_scope=self._normalize_pdf_scope,
        )
        self._followup = RuntimeFollowupCoordinator(task_coordinator=task_coordinator)
        self.max_tool_steps = 8
        self.tool_contract_gate = ToolContractGate(
            mode=str(os.getenv("TOOL_CONTRACT_MODE", "shadow") or "shadow").strip().lower()
        )
        self._tool_bridge = RuntimeToolBridge(
            permission_service=permission_service,
            tool_runtime=tool_runtime,
            task_coordinator=task_coordinator,
            tool_contract_gate=self.tool_contract_gate,
            output_policy=self._output_policy,
            skill_allowed_tool_scope=self._skill_allowed_tool_scope,
            extract_active_constraints=self._extract_active_constraints,
            build_direct_tool_main_context=self._build_direct_tool_main_context,
            task_summary_ref_from_task=self._task_summary_ref_from_task,
        )
        self.planner = QueryPlanner(
            base_dir=base_dir,
            skill_registry=skill_registry,
            tool_runtime=tool_runtime,
        )

    def build_system_prompt_for_session(
        self,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        active_skill: SkillDefinition | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ) -> str:
        context_package = None
        persistent_memory = None
        if session_id:
            context_package = self.memory_facade.build_context_package(
                session_id,
                history=history,
                pending_user_message=pending_user_message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
                retrieval_results=retrieval_results,
                rebuild_reason="prompt_assembly",
            )
        persistent_memory = self.memory_facade.build_persistent_memory_block(
            query=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_memory_notes,
        )
        return build_system_prompt(
            self.base_dir,
            self.settings_service.get_rag_mode(),
            persistent_memory=persistent_memory,
            session_memory=None,
            context_package=context_package,
            active_skill=self._render_active_skill_prompt(active_skill),
        )

    async def abuild_system_prompt_for_session(
        self,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        active_skill: SkillDefinition | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ) -> str:
        context_package = None
        persistent_memory = None
        if session_id:
            context_package = self.memory_facade.build_context_package(
                session_id,
                history=history,
                pending_user_message=pending_user_message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
                retrieval_results=retrieval_results,
                rebuild_reason="prompt_assembly",
            )
        async_builder = getattr(self.memory_facade, "abuild_persistent_memory_block", None)
        if callable(async_builder):
            persistent_memory = await async_builder(
                query=pending_user_message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
            )
        else:
            persistent_memory = self.memory_facade.build_persistent_memory_block(
                query=pending_user_message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
            )
        return build_system_prompt(
            self.base_dir,
            self.settings_service.get_rag_mode(),
            persistent_memory=persistent_memory,
            session_memory=None,
            context_package=context_package,
            active_skill=self._render_active_skill_prompt(active_skill),
        )

    async def _abuild_system_prompt_for_execution(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        retrieval_results: list[dict[str, Any]] | None = None,
        relevant_memory_notes: list[Any] | None = None,
    ) -> str:
        context_package = self.memory_facade.build_context_package(
            session_id,
            history=execution.history,
            pending_user_message=execution.message,
            memory_intent=execution.memory_intent,
            relevant_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
            rebuild_reason="prompt_assembly",
        )
        if self._is_session_summary_execution(execution):
            context_package = self._filter_runtime_sections_from_context_package(context_package)

        async_builder = getattr(self.memory_facade, "abuild_persistent_memory_block", None)
        if callable(async_builder):
            persistent_memory = await async_builder(
                query=execution.message,
                memory_intent=execution.memory_intent,
                relevant_notes=relevant_memory_notes,
            )
        else:
            persistent_memory = self.memory_facade.build_persistent_memory_block(
                query=execution.message,
                memory_intent=execution.memory_intent,
                relevant_notes=relevant_memory_notes,
            )

        return build_system_prompt(
            self.base_dir,
            self.settings_service.get_rag_mode(),
            persistent_memory=persistent_memory,
            session_memory=None,
            context_package=context_package,
            active_skill=self._render_execution_skill_prompt(execution),
        )

    def _render_active_skill_prompt(self, active_skill: SkillDefinition | None) -> str | None:
        if active_skill is None:
            return None
        return active_skill.render_prompt_block()

    def _render_execution_skill_prompt(self, execution: QueryExecutionPlan) -> str | None:
        prompt_exposure = getattr(getattr(execution, "dispatch_plan", None), "prompt_exposure", None)
        prompt_block = str(getattr(prompt_exposure, "skill_prompt_block", "") or "").strip()
        if prompt_block:
            return prompt_block
        return self._render_active_skill_prompt(execution.active_skill)

    def _skill_allowed_tool_scope(self, active_skill: SkillDefinition | None) -> ToolScope:
        if active_skill is None:
            return ToolScope(source="skill", reason="no_active_skill")
        return active_skill.tool_scope()

    async def astream(self, request: QueryRequest):
        history_record = self.session_manager.load_session_record(request.session_id)
        history = request.history or self.session_manager.load_session_for_agent(
            request.session_id,
            include_compressed_context=False,
        )
        is_first_user_message = not any(
            message.get("role") == "user"
            for message in history_record.get("messages", [])
        )

        segments: list[dict[str, Any]] = []
        current_segment = self._new_segment()
        assistant_persisted = False

        self.session_manager.save_message(request.session_id, "user", request.message)

        try:
            with start_turn_trace(
                session_id=request.session_id,
                user_message=request.message,
                history_length=len(history),
                metadata={"request_kind": "chat"},
                tags=["query-runtime"],
            ) as trace:
                debug_event = build_debug_trace_event(trace)
                if debug_event is not None:
                    yield debug_event

                async for event in self._execution_events(
                    request.session_id,
                    request.message,
                    history,
                    ephemeral_system_messages=request.ephemeral_system_messages,
                    explicit_subtasks=request.explicit_subtasks,
                    trace=trace,
                ):
                    event_type = event["type"]

                    if event_type == "token":
                        current_segment["content"] += str(event.get("content", ""))
                    elif event_type == "tool_start":
                        current_segment["tool_calls"].append(
                            {
                                "tool": event.get("tool", "tool"),
                                "input": event.get("input", ""),
                                "output": "",
                            }
                        )
                    elif event_type == "tool_end":
                        if current_segment["tool_calls"]:
                            current_segment["tool_calls"][-1]["output"] = event.get("output", "")
                    elif event_type == "new_response":
                        segments = self._finalize_segments(segments, current_segment)
                        current_segment = self._new_segment()
                    elif event_type == "done":
                        segments = self._finalize_segments(
                            segments,
                            current_segment,
                            fallback_content=str(event.get("content", "") or ""),
                        )
                        self._capture_session_memory_projection(
                            request.session_id,
                            main_context_payload=event.get("main_context"),
                            task_summary_payloads=event.get("task_summary_refs"),
                        )
                        assistant_messages = self._build_assistant_messages(
                            segments,
                            canonical_content=str(event.get("content", "") or ""),
                            answer_metadata=self._assistant_metadata_from_done_event(event),
                        )
                        if assistant_messages:
                            self.session_manager.append_messages(request.session_id, assistant_messages)
                            assistant_persisted = True

                        trace.annotate(
                            {
                                "app.final_segment_count": len(segments),
                                "app.assistant_persisted": assistant_persisted,
                            }
                        )
                        asyncio.create_task(
                            self._run_post_turn_tasks(
                                request.session_id,
                                title_seed=request.message if is_first_user_message else None,
                            )
                        )

                        yield event
                        break

                    yield event
        except Exception as exc:
            failure_text = self._user_visible_error(exc)
            if not assistant_persisted:
                try:
                    partial_segments = self._finalize_segments(segments, current_segment)
                    assistant_messages = self._build_assistant_messages(partial_segments)
                    if assistant_messages:
                        self.session_manager.append_messages(request.session_id, assistant_messages)
                    else:
                        self.session_manager.save_message(
                            request.session_id,
                            "assistant",
                            f"Request failed: {failure_text}",
                        )
                except Exception:
                    logger.exception(
                        "Failed to persist errored assistant response for session %s",
                        request.session_id,
                    )
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
        trace=None,
    ):
        authority_context = self._load_session_authoritative_context(session_id)
        followup_resolution = self.followup_resolver.resolve(session_id=session_id, message=message)
        followup_results = self._followup_results_from_resolution(session_id, followup_resolution)
        if trace is not None:
            trace.annotate(
                {
                    "app.followup_mode": followup_resolution.mode,
                    "app.followup_source": followup_resolution.resolution_source,
                    "app.followup_task_id": (
                        self._resolved_binding_owner_task_id(followup_resolution)
                        or self._resolved_task_id(followup_resolution)
                    ),
                    "app.followup_task_ids": ",".join(self._resolved_task_ids(followup_resolution)),
                }
            )
        if followup_resolution.requires_clarification:
            main_context = MainContextState(
                active_goal=message.strip(),
                active_work_item="clarify_followup_owner",
                active_binding_identity=self._resolved_binding_identity(followup_resolution),
                followup_mode=followup_resolution.mode,
                followup_resolution_source=followup_resolution.resolution_source,
                followup_target_task_ids=self._resolved_task_ids(followup_resolution),
                followup_binding_identity=self._resolved_binding_identity(followup_resolution),
                latest_correction=self._extract_latest_correction(message),
                next_step="clarify_followup_owner",
            )
            yield {
                "type": "done",
                "content": followup_resolution.clarification_prompt or "请明确你要继续的是哪一个对象。",
                "main_context": main_context.to_dict(),
                "task_summary_refs": [],
                "followup_mode": followup_resolution.mode,
                "answer_channel": "fallback_answer",
                "answer_source": "clarification_prompt",
                "answer_fallback_reason": "followup_requires_clarification",
                "answer_leak_flags": [],
            }
            return
        if self._should_answer_from_followup(
            message=message,
            followup_resolution=followup_resolution,
            results=followup_results,
        ):
            main_context = self._build_followup_main_context(
                message,
                followup_results,
                followup_resolution=followup_resolution,
            )
            task_summary_refs = self._task_summary_refs_from_results(followup_results)
            if trace is not None:
                trace.annotate(
                    {
                        "app.route": "followup_direct",
                        "app.subquery_count": len(followup_results),
                    }
                )
            yield {
                "type": "done",
                "content": self._assemble_subtask_results(followup_results, main_context=main_context),
                "main_context": main_context.to_dict(),
                "task_summary_refs": [item.to_dict() for item in task_summary_refs],
                "followup_mode": followup_resolution.mode,
                "answer_channel": "answer_candidate",
                "answer_source": "answer_assembler",
                "answer_fallback_reason": "",
                "answer_leak_flags": [],
            }
            return
        if trace is not None:
            with trace.stage(
                "query.plan",
                inputs={"message": message, "history_length": len(history)},
                metadata={"session_id": session_id},
            ):
                plan = self._planner_build_plan(
                    session_id=session_id,
                    message=message,
                    history=history,
                    ephemeral_system_messages=ephemeral_system_messages,
                    authority_context=authority_context,
                    explicit_subtasks=explicit_subtasks,
                )
        else:
            plan = self._planner_build_plan(
                session_id=session_id,
                message=message,
                history=history,
                ephemeral_system_messages=ephemeral_system_messages,
                authority_context=authority_context,
                explicit_subtasks=explicit_subtasks,
            )
        executions = plan.iter_executions()
        if executions:
            executions[0] = self._maybe_build_candidate_selection_execution(session_id, executions[0])
        if trace is not None:
            trace.annotate(
                {
                    "app.route": plan.query_understanding.route,
                    "app.execution_mode": str(getattr(plan, "execution_mode", "") or ""),
                    "app.execution_posture": str(getattr(plan.query_understanding, "execution_posture", "") or ""),
                    "app.direct_route_reason": str(getattr(plan.query_understanding, "direct_route_reason", "") or ""),
                    "app.tool_name": plan.query_understanding.tool_name or "",
                    "app.skill_name": plan.query_understanding.skill_name or "",
                    "app.bound_candidate_tools": ",".join(list(getattr(plan.query_understanding, "candidate_tools", []) or [])),
                    "app.subquery_count": len(executions),
                    "app.bundle_item_count": len(list(getattr(getattr(plan, "bundle_plan", None), "items", []) or [])),
                }
            )
        if self._should_execute_binding_followup(
            session_id=session_id,
            followup_resolution=followup_resolution,
            plan=plan,
        ):
            async for event in self._stream_binding_followup(
                session_id,
                message,
                history,
                followup_resolution=followup_resolution,
                trace=trace,
            ):
                yield event
            return
        if str(getattr(plan, "execution_mode", "") or "") == "bundle_execution":
            async for event in self._stream_bundle_execution(
                session_id=session_id,
                message=message,
                executions=executions,
                plan=plan,
                trace=trace,
            ):
                yield event
            return
        if str(getattr(plan, "execution_mode", "") or "") == "explicit_fanout":
            subtask_results: list[dict[str, object]] = []
            async for event in self.task_coordinator.run_query_tasks(
                session_id,
                executions,
                lambda execution: self._stream_planned_execution(session_id, execution, trace=trace),
                subtasks=plan.subtasks,
            ):
                if event.get("type") == "subtask_end":
                    subtask_results.append(dict(event))
                yield event
            main_context = self._build_compound_main_context(message, subtask_results)
            task_summary_refs = self._task_summary_refs_from_results(subtask_results)
            yield {
                "type": "done",
                "content": self._assemble_subtask_results(subtask_results, main_context=main_context),
                "main_context": main_context.to_dict(),
                "task_summary_refs": [item.to_dict() for item in task_summary_refs],
                "answer_channel": "answer_candidate",
                "answer_source": "answer_assembler",
                "answer_fallback_reason": "",
                "answer_leak_flags": [],
            }
            return

        async for event in self._stream_planned_execution(session_id, executions[0], trace=trace):
            yield event

    async def _stream_bundle_execution(
        self,
        *,
        session_id: str,
        message: str,
        executions: list[QueryExecutionPlan],
        plan: QueryPlan,
        trace=None,
    ):
        bundle_results: list[dict[str, object]] = []
        async for event in self.task_coordinator.run_query_tasks(
            session_id,
            executions,
            lambda execution: self._stream_planned_execution(session_id, execution, trace=trace),
            subtasks=None,
        ):
            if event.get("type") == "subtask_end":
                bundle_results.append(dict(event))
            yield event
        main_context = self._build_bundle_main_context(
            message,
            bundle_results,
            bundle_plan=plan.bundle_plan,
        )
        task_summary_refs = self._task_summary_refs_from_results(bundle_results)
        yield {
            "type": "done",
            "content": self._assemble_subtask_results(bundle_results, main_context=main_context),
            "main_context": main_context.to_dict(),
            "task_summary_refs": [item.to_dict() for item in task_summary_refs],
            "answer_channel": "answer_candidate",
            "answer_source": "answer_assembler",
            "answer_fallback_reason": "",
            "answer_leak_flags": [],
        }

    async def _stream_single_execution(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        *,
        ephemeral_system_messages: list[str] | None = None,
        trace=None,
    ):
        self._restore_evidence_state_from_session(session_id)
        plan = self._planner_build_plan(
            session_id=session_id,
            message=message,
            history=history,
            ephemeral_system_messages=ephemeral_system_messages,
            authority_context=self._load_session_authoritative_context(session_id),
        )
        executions = plan.iter_executions()
        execution = executions[0]
        execution = self._maybe_build_candidate_selection_execution(session_id, execution)
        async for event in self._stream_planned_execution(session_id, execution, trace=trace):
            yield event

    def _maybe_build_candidate_selection_execution(
        self,
        session_id: str,
        execution: QueryExecutionPlan,
    ) -> QueryExecutionPlan:
        selection = self.binding_candidate_store.resolve_selection(session_id, execution.message)
        if selection is None:
            return execution
        candidate = selection.candidate
        if candidate.kind == "document":
            return self._build_document_candidate_selection_execution(
                session_id=session_id,
                execution=execution,
                selection=selection,
            )
        if candidate.kind == "table":
            return self._build_table_candidate_selection_execution(
                session_id=session_id,
                execution=execution,
                selection=selection,
            )
        if candidate.kind != "dataset":
            return execution
        return self._build_dataset_candidate_selection_execution(
            session_id=session_id,
            execution=execution,
            selection=selection,
        )

    def _build_dataset_candidate_selection_execution(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        selection,
    ) -> QueryExecutionPlan:
        candidate = selection.candidate
        dataset_path = str(candidate.identity or "").strip()
        if not dataset_path:
            return execution
        source_query = str(selection.source_query or execution.message or "").strip()
        binding = StructuredDatasetBinding(
            dataset_path=dataset_path,
            target_object=str(candidate.display_label or ""),
            source="evidence_candidate_selection",
            confidence=float(candidate.confidence or 0.0),
            binding_identity=dataset_path.replace("\\", "/").strip().lower(),
            explicit_switch=True,
        )
        request = WorkerRequest(
            request_id=f"worker:structured_data:{candidate.candidate_id}",
            session_id=session_id,
            query=source_query,
            worker_route="structured_data",
            task_frame={
                "intent": "structured_candidate_followup",
                "source_kind": "dataset",
                "task_kind": "dataset_query",
                "modality": "table",
                "selection_source": selection.selection_source,
            },
            bindings={"active_dataset": dataset_path},
            target_handle_kind="object",
            target_handle_id=str(getattr(candidate, "source_object_id", "") or dataset_path),
            upstream_object_handle_ids=[
                str(item)
                for item in [getattr(candidate, "source_object_id", ""), dataset_path]
                if str(item or "").strip()
            ],
            owner_task_id=str(getattr(selection, "source_task_id", "") or ""),
            arbitration_reason=str(selection.selection_source or "evidence_candidate_selection"),
        )
        self.binding_candidate_store.clear(session_id)
        return QueryExecutionPlan(
            message=source_query,
            history=list(execution.history),
            memory_intent=execution.memory_intent,
            query_understanding=QueryUnderstanding(
                intent="structured_candidate_followup",
                source_kind="dataset",
                task_kind="dataset_query",
                modality="table",
                route="worker",
                execution_posture="worker",
                direct_route_reason="evidence_candidate_selection",
                capability_requests=["dataset_analysis"],
                should_skip_rag=True,
                reasons=["evidence_candidate_selection", selection.selection_source],
            ),
            active_skill=execution.active_skill,
            structured_binding=binding,
            execution_kind="worker",
            execution_posture="worker",
            target_handle_kind="object",
            target_handle_id=str(getattr(candidate, "source_object_id", "") or dataset_path),
            upstream_object_handle_ids=[
                str(item)
                for item in [getattr(candidate, "source_object_id", ""), dataset_path]
                if str(item or "").strip()
            ],
            arbitration_reason=str(selection.selection_source or "evidence_candidate_selection"),
            worker_plan=WorkerExecutionPlan(
                worker_route="structured_data",
                request=request,
                expected_result="canonical",
                candidate_refs=[candidate.candidate_id],
                fallback_execution_kind="none",
                cutover_mode="primary",
            ),
            ephemeral_system_messages=list(execution.ephemeral_system_messages),
        )

    def _build_table_candidate_selection_execution(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        selection,
    ) -> QueryExecutionPlan:
        candidate = selection.candidate
        table_identity = str(candidate.identity or candidate.artifact_id or "").strip()
        if not table_identity:
            return execution
        source_query = str(selection.source_query or execution.message or "").strip()
        dataset_path = self._dataset_path_from_table_candidate(session_id, table_identity)
        bindings = {"active_table": table_identity}
        if dataset_path:
            bindings["active_dataset"] = dataset_path
        request = WorkerRequest(
            request_id=f"worker:structured_data:{candidate.candidate_id}",
            session_id=session_id,
            query=source_query,
            worker_route="structured_data",
            task_frame={
                "intent": "table_candidate_followup",
                "source_kind": "table",
                "task_kind": "table_query",
                "modality": "table",
                "selection_source": selection.selection_source,
            },
            bindings=bindings,
            target_handle_kind="artifact",
            target_handle_id=table_identity,
            upstream_object_handle_ids=[
                str(item)
                for item in [table_identity, dataset_path]
                if str(item or "").strip()
            ],
            owner_task_id=str(getattr(selection, "source_task_id", "") or ""),
            arbitration_reason=str(selection.selection_source or "evidence_candidate_selection"),
        )
        self.binding_candidate_store.clear(session_id)
        return QueryExecutionPlan(
            message=source_query,
            history=list(execution.history),
            memory_intent=execution.memory_intent,
            query_understanding=QueryUnderstanding(
                intent="table_candidate_followup",
                source_kind="table",
                task_kind="table_query",
                modality="table",
                route="worker",
                execution_posture="worker",
                direct_route_reason="evidence_candidate_selection",
                capability_requests=["dataset_analysis"],
                should_skip_rag=True,
                reasons=["evidence_candidate_selection", selection.selection_source],
            ),
            active_skill=execution.active_skill,
            execution_kind="worker",
            execution_posture="worker",
            target_handle_kind="artifact",
            target_handle_id=table_identity,
            upstream_object_handle_ids=[
                str(item)
                for item in [table_identity, dataset_path]
                if str(item or "").strip()
            ],
            arbitration_reason=str(selection.selection_source or "evidence_candidate_selection"),
            worker_plan=WorkerExecutionPlan(
                worker_route="structured_data",
                request=request,
                expected_result="canonical",
                candidate_refs=[candidate.candidate_id],
                fallback_execution_kind="none",
                cutover_mode="primary",
            ),
            ephemeral_system_messages=list(execution.ephemeral_system_messages),
        )

    def _dataset_path_from_table_candidate(self, session_id: str, table_identity: str) -> str:
        artifact = self.evidence_graph_store.get_artifact(session_id, table_identity)
        if artifact is None:
            return ""
        content_ref = str(getattr(artifact, "content_ref", "") or "").strip()
        if _structured_dataset_path(content_ref):
            return content_ref.split("#", 1)[0]
        materialized = self.table_materializer.materialize(artifact, session_id=session_id)
        if materialized is not None:
            graph = EvidenceArtifactGraph(session_id=session_id)
            graph.add_artifact(
                materialized.artifact,
                worker="table_materializer",
                relation="materialized_as",
            )
            self.evidence_graph_store.merge(session_id, graph)
            return materialized.dataset_path
        source = self.evidence_graph_store.get_source_object(session_id, artifact.source_object_id)
        if source is None:
            return ""
        uri = str(getattr(source, "uri", "") or "").strip()
        return uri if _structured_dataset_path(uri) else ""

    def _restore_evidence_state_from_session(self, session_id: str) -> None:
        loader = getattr(self.session_manager, "get_runtime_state", None)
        if not callable(loader):
            return
        try:
            state = loader(session_id, "evidence_state")
        except Exception:
            return
        if not isinstance(state, dict) or not state:
            return
        candidates = state.get("binding_candidates")
        if isinstance(candidates, dict):
            self.binding_candidate_store.restore(session_id, candidates)
        graph = state.get("evidence_graph")
        if isinstance(graph, dict):
            self.evidence_graph_store.restore(session_id, graph)

    def _persist_evidence_state_to_session(self, session_id: str) -> None:
        saver = getattr(self.session_manager, "set_runtime_state", None)
        if not callable(saver):
            return
        state = {
            "binding_candidates": self.binding_candidate_store.snapshot(session_id),
            "evidence_graph": self.evidence_graph_store.snapshot(session_id),
        }
        try:
            saver(session_id, "evidence_state", state)
        except Exception:
            return

    def _build_document_candidate_selection_execution(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        selection,
    ) -> QueryExecutionPlan:
        candidate = selection.candidate
        document_path = str(candidate.identity or "").strip()
        if not document_path:
            return execution
        source_query = str(selection.source_query or execution.message or "").strip()
        request = WorkerRequest(
            request_id=f"worker:pdf:{candidate.candidate_id}",
            session_id=session_id,
            query=source_query,
            worker_route="pdf",
            task_frame={
                "intent": "document_candidate_followup",
                "source_kind": "document",
                "task_kind": "pdf_query",
                "modality": "pdf",
                "selection_source": selection.selection_source,
            },
            bindings={"active_pdf": document_path},
            constraints={"mode": "document"},
            target_handle_kind="object",
            target_handle_id=str(getattr(candidate, "source_object_id", "") or document_path),
            upstream_object_handle_ids=[
                str(item)
                for item in [getattr(candidate, "source_object_id", ""), document_path]
                if str(item or "").strip()
            ],
            owner_task_id=str(getattr(selection, "source_task_id", "") or ""),
            arbitration_reason=str(selection.selection_source or "evidence_candidate_selection"),
        )
        self.binding_candidate_store.clear(session_id)
        return QueryExecutionPlan(
            message=source_query,
            history=list(execution.history),
            memory_intent=execution.memory_intent,
            query_understanding=QueryUnderstanding(
                intent="document_candidate_followup",
                source_kind="document",
                task_kind="pdf_query",
                modality="pdf",
                route="worker",
                execution_posture="worker",
                direct_route_reason="evidence_candidate_selection",
                capability_requests=["pdf_read"],
                should_skip_rag=True,
                reasons=["evidence_candidate_selection", selection.selection_source],
            ),
            active_skill=execution.active_skill,
            execution_kind="worker",
            execution_posture="worker",
            target_handle_kind="object",
            target_handle_id=str(getattr(candidate, "source_object_id", "") or document_path),
            upstream_object_handle_ids=[
                str(item)
                for item in [getattr(candidate, "source_object_id", ""), document_path]
                if str(item or "").strip()
            ],
            arbitration_reason=str(selection.selection_source or "evidence_candidate_selection"),
            worker_plan=WorkerExecutionPlan(
                worker_route="pdf",
                request=request,
                expected_result="canonical",
                candidate_refs=[candidate.candidate_id],
                fallback_execution_kind="none",
                cutover_mode="primary",
            ),
            ephemeral_system_messages=list(execution.ephemeral_system_messages),
        )

    async def _stream_planned_execution(
        self,
        session_id: str,
        execution: QueryExecutionPlan,
        *,
        trace=None,
    ):
        execution_stage = (
            trace.stage(
                "query.single_execution",
                inputs={"message": execution.message},
                metadata={"session_id": session_id},
            )
            if trace is not None
            else None
        )
        if execution_stage is not None:
            execution_stage.__enter__()
        try:
            context = QueryContext(
                session_id=session_id,
                history=list(execution.history),
                augmented_history=list(execution.history),
                main_context=self._build_main_working_context(execution),
                ephemeral_system_messages=list(execution.ephemeral_system_messages),
            )

            if trace is not None:
                with trace.stage(
                    "query.context_compaction",
                    metadata={"history_length": len(context.augmented_history)},
                ):
                    context.augmented_history, context.context_compaction = self.memory_facade.compact_history_for_query(
                        session_id,
                        context.augmented_history,
                    )
            else:
                context.augmented_history, context.context_compaction = self.memory_facade.compact_history_for_query(
                    session_id,
                    context.augmented_history,
                )
            yield {"type": "context_management", "context": context.context_compaction}

            if execution.execution_kind == "worker" and execution.worker_plan is not None:
                async for event in self.evidence_orchestrator.stream_execution(
                    session_id=session_id,
                    execution=execution,
                    worker_plan=execution.worker_plan,
                    main_context=context.main_context,
                    trace=trace,
                ):
                    if event.get("type") == "done":
                        event = self._materialize_worker_done_event(
                            session_id=session_id,
                            execution=execution,
                            event=dict(event),
                        )
                    yield event
                self._persist_evidence_state_to_session(session_id)
                return

            if execution.execution_kind == "direct_tool" and execution.query_understanding.tool_name:
                async for event in self._stream_direct_tool_execution(session_id, execution, trace=trace):
                    if event.get("type") == "done":
                        event = dict(event)
                        event.setdefault("main_context", context.main_context.to_dict())
                        if "task_summary_refs" not in event:
                            final_content = str(event.get("content", "") or "")
                            event["task_summary_refs"] = [
                                item.to_dict()
                                for item in self._build_single_execution_task_summaries(
                                    execution,
                                    final_content,
                                )
                            ]
                    yield event
                return

            if (
                self.settings_service.get_rag_mode()
                and execution.query_understanding.route == "rag"
                and not execution.memory_intent.should_skip_rag
                and not execution.query_understanding.should_skip_rag
            ):
                if trace is not None:
                    with trace.stage(
                        "query.retrieval",
                        inputs={"query": execution.message},
                        metadata={"top_k": 5},
                    ):
                        context.retrieval_results = self.retrieval_service.retrieve(execution.message, top_k=5)
                else:
                    context.retrieval_results = self.retrieval_service.retrieve(execution.message, top_k=5)
                yield {"type": "retrieval", "query": execution.message, "results": context.retrieval_results}

            if self._should_prefetch_durable_context(execution):
                try:
                    context.relevant_memory_notes = await asyncio.to_thread(
                        self.memory_facade.prefetch_relevant_notes,
                        execution.message,
                        execution.memory_intent,
                        limit=3,
                    )
                except Exception:
                    context.relevant_memory_notes = None

            memory_trace = self.memory_facade.inspect_query_context(
                session_id,
                history=execution.history,
                pending_user_message=execution.message,
                memory_intent=execution.memory_intent,
                relevant_notes=context.relevant_memory_notes,
                context_compaction=context.context_compaction,
                retrieval_results=context.retrieval_results,
            )
            yield {"type": "memory_context", "memory": memory_trace}

            if self._should_isolate_augmented_history(execution):
                context.augmented_history = []

            if self._is_session_summary_execution(execution):
                session_summary_guide = self._build_session_summary_instruction_block(
                    session_id=session_id,
                    history=execution.history,
                )
                if session_summary_guide:
                    context.ephemeral_system_messages.append(session_summary_guide)

            if self._should_handle_memory_write_directly(execution):
                final_content = self._build_memory_write_acknowledgement(execution.message)
                if trace is not None:
                    trace.annotate(
                        {
                            "app.answer_chars": len(final_content),
                            "app.answer_channel": "answer_candidate",
                            "app.answer_source": "memory_write_ack",
                            "app.answer_fallback_reason": "",
                            "app.output_leak_flags": "",
                            "app.tool_receipt_count": 0,
                        }
                    )
                yield {
                    "type": "done",
                    "content": final_content,
                    "main_context": context.main_context.to_dict(),
                    "task_summary_refs": [],
                    "answer_channel": "answer_candidate",
                    "answer_source": "memory_write_ack",
                    "answer_fallback_reason": "",
                    "answer_leak_flags": [],
                }
                return

            allowed_names = self._allowed_tool_names_for_execution(execution)
            tools = [
                tool
                for tool in self.tool_runtime.instances
                if getattr(tool, "name", "") in allowed_names
            ]
            system_prompt = await self._abuild_system_prompt_for_execution(
                session_id=session_id,
                execution=execution,
                retrieval_results=context.retrieval_results,
                relevant_memory_notes=context.relevant_memory_notes,
            )
            agent = self.model_runtime.create_conversation_agent(
                system_prompt=system_prompt,
                tools=tools,
                agent_definition=MAIN_AGENT,
            )
            messages = self._build_agent_messages(context)
            messages.append({"role": "user", "content": execution.message})

            last_ai_message = ""
            pending_tools: dict[str, dict[str, str]] = {}
            tool_step_count = 0
            output_boundary = AssistantOutputBoundary()

            if trace is not None:
                trace.annotate(
                    {
                        "app.route": execution.query_understanding.route,
                        "app.execution_posture": str(
                            execution.execution_posture or getattr(execution.query_understanding, "execution_posture", "") or ""
                        ),
                        "app.direct_route_reason": str(
                            getattr(execution.query_understanding, "direct_route_reason", "") or ""
                        ),
                        "app.tool_count": len(tools),
                        "app.bound_candidate_tools": ",".join(list(getattr(execution.query_understanding, "candidate_tools", []) or [])),
                    }
                )
            stream_context = (
                trace.stage(
                    "query.model_stream",
                    metadata={
                        "route": execution.query_understanding.route,
                        "tool_count": len(tools),
                    },
                )
                if trace is not None
                else None
            )
            if stream_context is not None:
                stream_context.__enter__()
            try:
                async for mode, payload in agent.astream(
                    {"messages": messages},
                    stream_mode=["messages", "updates"],
                ):
                    if mode == "messages":
                        chunk, _metadata = payload
                        text = stringify_content(getattr(chunk, "content", ""))
                        if text:
                            visible_delta = output_boundary.ingest_stream_text(text)
                            if visible_delta:
                                yield {"type": "token", "content": visible_delta}
                        continue

                    if mode != "updates":
                        continue

                    for update in payload.values():
                        for agent_message in update.get("messages", []):
                            message_type = getattr(agent_message, "type", "")
                            tool_calls = getattr(agent_message, "tool_calls", []) or []

                            if message_type == "ai" and not tool_calls:
                                candidate = stringify_content(getattr(agent_message, "content", ""))
                                if candidate:
                                    output_boundary.ingest_ai_update(candidate, has_tool_calls=False)
                                    last_ai_message = sanitize_visible_assistant_content(candidate)

                            if tool_calls:
                                for tool_call in tool_calls:
                                    tool_step_count += 1
                                    if tool_step_count > self.max_tool_steps:
                                        yield {"type": "done", "content": "调用工具失败"}
                                        return
                                    call_id = str(tool_call.get("id") or tool_call.get("name"))
                                    tool_name = str(tool_call.get("name", "tool"))
                                    tool_args = tool_call.get("args", "")
                                    if not isinstance(tool_args, str):
                                        tool_args = json.dumps(tool_args, ensure_ascii=False)
                                    pending_tools[call_id] = {
                                        "tool": tool_name,
                                        "input": str(tool_args),
                                    }
                                    output_boundary.ingest_tool_call(tool_name, str(tool_args))
                                    yield {
                                        "type": "tool_start",
                                        "tool": tool_name,
                                        "input": str(tool_args),
                                    }

                            if message_type == "tool":
                                tool_call_id = str(getattr(agent_message, "tool_call_id", ""))
                                pending = pending_tools.pop(
                                    tool_call_id,
                                    {"tool": getattr(agent_message, "name", "tool"), "input": ""},
                                )
                                output = stringify_content(getattr(agent_message, "content", ""))
                                output_boundary.ingest_tool_result(str(pending["tool"]), output)
                                yield {
                                    "type": "tool_end",
                                    "tool": pending["tool"],
                                    "output": output,
                                }
                                yield {"type": "new_response"}
            finally:
                if stream_context is not None:
                    stream_context.__exit__(None, None, None)

            output_boundary.finalize_segment(fallback_content=last_ai_message)
            output_response = output_boundary.build_response(
                route=str(execution.query_understanding.route or ""),
                execution_posture=str(execution.execution_posture or execution.query_understanding.execution_posture or ""),
                user_message=execution.message,
                tool_name=str(execution.query_understanding.tool_name or ""),
                retrieval_results=context.retrieval_results,
            )
            output_response = self._maybe_gate_memory_output(
                execution=execution,
                output_response=output_response,
            )
            output_response = await self._maybe_finalize_rag_output(
                execution=execution,
                retrieval_results=context.retrieval_results,
                output_response=output_response,
            )
            final_content = output_response.canonical_answer.strip()
            if trace is not None:
                trace.annotate(
                    {
                        "app.answer_chars": len(final_content),
                        "app.answer_channel": output_response.selected_channel,
                        "app.answer_source": output_response.selected_source,
                        "app.answer_canonical_state": str(getattr(output_response, "canonical_state", "") or ""),
                        "app.answer_persist_policy": str(getattr(output_response, "persist_policy", "") or ""),
                        "app.answer_finalization_policy": str(getattr(output_response, "finalization_policy", "") or ""),
                        "app.answer_fallback_reason": output_response.fallback_reason,
                        "app.output_leak_flags": ",".join(output_response.leak_flags),
                        "app.tool_receipt_count": len(list(getattr(output_response, "tool_receipts", []) or [])),
                    }
                )
            task_summary_refs = self._build_single_execution_task_summaries(
                execution,
                final_content,
            )
            yield {
                "type": "done",
                "content": final_content,
                "main_context": context.main_context.to_dict(),
                "task_summary_refs": [item.to_dict() for item in task_summary_refs],
                "answer_channel": output_response.selected_channel,
                "answer_source": output_response.selected_source,
                "answer_canonical_state": str(getattr(output_response, "canonical_state", "") or ""),
                "answer_persist_policy": str(getattr(output_response, "persist_policy", "") or ""),
                "answer_finalization_policy": str(getattr(output_response, "finalization_policy", "") or ""),
                "answer_fallback_reason": output_response.fallback_reason,
                "answer_leak_flags": list(output_response.leak_flags),
            }
        finally:
            if execution_stage is not None:
                execution_stage.__exit__(None, None, None)

    async def _run_post_turn_tasks(self, session_id: str, *, title_seed: str | None = None) -> None:
        try:
            await asyncio.to_thread(self.refresh_session_memory, session_id)
        except Exception:
            logger.exception("Failed to refresh session memory for %s", session_id)

        try:
            await asyncio.to_thread(self.schedule_durable_memory_extraction, session_id)
        except Exception:
            logger.exception("Failed to extract durable memories for %s", session_id)

        if title_seed:
            try:
                title = await self.generate_title(title_seed)
                self.session_manager.set_title(session_id, title)
            except Exception:
                logger.exception("Failed to generate title for session %s", session_id)

    def refresh_session_memory(self, session_id: str) -> str:
        projection = self._session_memory_projection.get(session_id)
        if projection is not None:
            try:
                summary = self.memory_facade.refresh_session_memory_from_context_state(
                    session_id,
                    projection.get("main_context"),
                    task_summaries=list(projection.get("task_summary_refs", []) or []),
                    corrections=list(projection.get("corrections", []) or []),
                )
                return summary
            except Exception:
                logger.exception(
                    "Failed to refresh session memory from context-state projection for %s; falling back to committed messages",
                    session_id,
                )
        summary = self.memory_facade.refresh_session_memory(
            session_id,
            self.session_manager.load_session_for_agent(session_id, include_compressed_context=False),
        )
        return summary

    def commit_durable_memory_extraction(self, session_id: str) -> int:
        projection = self._session_memory_projection.pop(session_id, None)
        if projection is not None:
            return self.memory_facade.commit_durable_memory_extraction_from_context_state(
                session_id,
                projection.get("main_context"),
                task_summaries=list(projection.get("task_summary_refs", []) or []),
                corrections=list(projection.get("corrections", []) or []),
            )
        return self.memory_facade.commit_durable_memory_extraction(
            session_id,
            self.session_manager.load_session_for_agent(session_id, include_compressed_context=False),
        )

    def schedule_durable_memory_extraction(self, session_id: str) -> int:
        projection = self._session_memory_projection.pop(session_id, None)
        if projection is not None:
            return self.memory_facade.submit_durable_memory_extraction_from_context_state(
                session_id,
                projection.get("main_context"),
                task_summaries=list(projection.get("task_summary_refs", []) or []),
                corrections=list(projection.get("corrections", []) or []),
            )
        return self.memory_facade.submit_durable_memory_extraction(
            session_id,
            self.session_manager.load_session_for_agent(session_id, include_compressed_context=False),
        )

    async def generate_title(self, first_user_message: str) -> str:
        return await self.model_runtime.generate_title(first_user_message)

    async def summarize_history(self, messages: list[dict[str, Any]]) -> str:
        return await self.model_runtime.summarize_history(messages)

    def _planner_build_plan(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        ephemeral_system_messages: list[str] | None = None,
        authority_context: dict[str, Any] | None,
        explicit_subtasks: list[dict[str, Any]] | None = None,
    ) -> QueryPlan:
        try:
            parameters = inspect.signature(self.planner.build_plan).parameters
        except (TypeError, ValueError):
            parameters = {}
        kwargs: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
            "history": history,
        }
        if "ephemeral_system_messages" in parameters:
            kwargs["ephemeral_system_messages"] = ephemeral_system_messages
        if "authority_context" in parameters:
            kwargs["authority_context"] = authority_context
        if "explicit_subtasks" in parameters:
            kwargs["explicit_subtasks"] = explicit_subtasks
        return self.planner.build_plan(**kwargs)

    def _build_agent_messages(self, context: QueryContext) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        working_block = context.main_context.to_prompt_block().strip()
        if working_block:
            messages.append({"role": "system", "content": working_block})
        for content in context.ephemeral_system_messages:
            normalized = str(content or "").strip()
            if normalized:
                messages.append({"role": "system", "content": normalized})
        for item in context.augmented_history:
            role = item.get("role")
            if role not in {"system", "user", "assistant"}:
                continue
            if role == "system":
                continue
            messages.append({"role": role, "content": str(item.get("content", ""))})
        return messages

    def _build_main_working_context(self, execution: QueryExecutionPlan) -> MainContextState:
        constraints = self._apply_execution_binding_to_constraints(
            self._extract_active_constraints(execution.message),
            execution,
        )
        intent = str(getattr(execution.query_understanding, "intent", "") or "")
        task_kind = str(getattr(execution.query_understanding, "task_kind", "") or "")
        route = str(getattr(execution.query_understanding, "route", "") or "")
        return MainContextState(
            active_goal=execution.message.strip(),
            active_work_item=intent or task_kind or route or "query",
            active_binding_identity=self._binding_identity_from_constraints(constraints),
            active_constraints=constraints,
            latest_correction=self._extract_latest_correction(execution.message),
            next_step="answer_current_request",
        )

    def _build_compound_main_context(
        self,
        message: str,
        results: list[dict[str, object]],
    ) -> MainContextState:
        followup_target_task_id = ""
        task_refs: list[TaskSummaryRef] = []
        for item in results:
            task_id = str(item.get("task_id", "") or "")
            query = str(item.get("query", "") or "")
            summary_payload = item.get("summary")
            context_ref_payload = item.get("context_ref")
            if isinstance(summary_payload, dict):
                task_refs.append(
                    TaskSummaryRef(
                        task_id=task_id,
                        query=query,
                        summary=str(summary_payload.get("response", "") or ""),
                        task_kind=str(
                            context_ref_payload.get("task_kind", "") if isinstance(context_ref_payload, dict) else ""
                        ),
                        response_style=str(summary_payload.get("response_style", "") or ""),
                        key_points=list(summary_payload.get("key_points", []) or []),
                    )
                )
            if task_id:
                followup_target_task_id = task_id
        constraints = self._extract_active_constraints(message)
        return MainContextState(
            active_goal=message.strip(),
            active_work_item="explicit_fanout",
            active_binding_identity=self._binding_identity_from_constraints(
                self._merge_constraints_from_results(constraints, results)
            ),
            followup_target_task_id=followup_target_task_id or None,
            followup_target_task_ids=[task_ref.task_id for task_ref in task_refs if task_ref.task_id],
            active_constraints=self._merge_constraints_from_results(constraints, results),
            latest_correction=self._extract_latest_correction(message),
            next_step="follow_up_or_refine_subtask_results",
        )

    def _build_bundle_main_context(
        self,
        message: str,
        results: list[dict[str, object]],
        *,
        bundle_plan=None,
    ) -> MainContextState:
        main_context = self._build_compound_main_context(message, results)
        main_context.active_work_item = "bundle_execution"
        main_context.next_step = "follow_up_or_refine_bundle_results"
        if bundle_plan is not None:
            main_context.followup_mode = "bundle_ref"
        return main_context

    def _build_direct_tool_main_context(
        self,
        message: str,
        *,
        task,
    ) -> MainContextState:
        constraints = self._extract_active_constraints(message)
        result_payload = {
            "task_id": task.task_id,
            "query": task.query,
            "summary": task.summary.to_dict() if task.summary is not None else None,
            "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
        }
        return MainContextState(
            active_goal=message.strip(),
            active_work_item="direct_tool_execution",
            active_binding_identity=self._binding_identity_from_constraints(
                self._merge_constraints_from_results(constraints, [result_payload])
            ),
            followup_mode="task_ref",
            followup_resolution_source="task_record",
            followup_target_task_id=task.task_id,
            followup_target_task_ids=[task.task_id],
            active_constraints=self._merge_constraints_from_results(constraints, [result_payload]),
            latest_correction=self._extract_latest_correction(message),
            next_step="follow_up_or_refine_direct_tool_result",
        )

    def _build_followup_main_context(
        self,
        message: str,
        results: list[dict[str, object]],
        *,
        followup_resolution,
    ) -> MainContextState:
        return self._followup.build_followup_main_context(
            message,
            results,
            followup_resolution=followup_resolution,
            extract_active_constraints=self._extract_active_constraints,
            merge_constraints_from_results=self._merge_constraints_from_results,
            binding_identity_from_constraints=self._binding_identity_from_constraints,
            extract_latest_correction=self._extract_latest_correction,
        )

    def _task_summary_refs_from_results(self, results: list[dict[str, object]]) -> list[TaskSummaryRef]:
        task_refs: list[TaskSummaryRef] = []
        for item in results:
            task_id = str(item.get("task_id", "") or "")
            query = str(item.get("query", "") or "")
            summary_payload = item.get("summary")
            context_ref_payload = item.get("context_ref")
            if not isinstance(summary_payload, dict):
                continue
            task_refs.append(
                TaskSummaryRef(
                    task_id=task_id,
                    query=query,
                    summary=str(summary_payload.get("response", "") or ""),
                    task_kind=self._normalize_task_kind(
                        str(context_ref_payload.get("task_kind", "") if isinstance(context_ref_payload, dict) else "")
                    ),
                    response_style=str(summary_payload.get("response_style", "") or ""),
                    key_points=list(summary_payload.get("key_points", []) or []),
                )
            )
        return task_refs

    def _task_summary_ref_from_task(self, task) -> TaskSummaryRef | None:
        if task is None or task.summary is None:
            return None
        task_kind = ""
        if task.context_ref is not None:
            task_kind = self._normalize_task_kind(str(task.context_ref.task_kind or ""))
        return TaskSummaryRef(
            task_id=str(task.task_id or ""),
            query=str(task.query or ""),
            summary=str(task.summary.response or ""),
            task_kind=task_kind,
            response_style=str(task.summary.response_style or ""),
            key_points=list(task.summary.key_points or []),
        )

    def _materialize_worker_done_event(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        if str(event.get("task_id", "") or "").strip():
            return event
        content = str(event.get("content", "") or "")
        main_context_payload = dict(event.get("main_context") or {})
        active_constraints = dict(main_context_payload.get("active_constraints") or {})
        committed_bindings = dict(event.get("committed_bindings") or {})
        bindings = {
            key: value
            for key, value in {
                "active_pdf": committed_bindings.get("active_pdf") or active_constraints.get("active_pdf"),
                "active_dataset": committed_bindings.get("active_dataset") or active_constraints.get("active_dataset"),
                "active_binding_identity": active_constraints.get("active_binding_identity", ""),
                "active_entity": active_constraints.get("active_entity", ""),
                "active_location": active_constraints.get("active_location", ""),
                "source_kind": active_constraints.get("source_kind", "") or getattr(execution.query_understanding, "source_kind", ""),
            }.items()
            if value not in ("", None)
        }
        object_handle_ids = [str(item).strip() for item in list(event.get("object_handle_ids", []) or []) if str(item).strip()]
        result_handle_ids = [str(item).strip() for item in list(event.get("result_handle_ids", []) or []) if str(item).strip()]
        degraded_reason_typed = str(event.get("degraded_reason_typed", "") or "").strip()
        presentation_hints = dict(event.get("presentation_hints") or {})
        task = self.task_coordinator.create_completed_execution_task(
            session_id=session_id,
            query=execution.message,
            content=content,
            execution_kind="worker",
            task_kind=str(getattr(execution.query_understanding, "task_kind", "") or ""),
            source_kind=str(getattr(execution.query_understanding, "source_kind", "") or ""),
            worker_name=str(getattr(getattr(execution, "worker_plan", None), "worker_route", "") or ""),
            bindings=bindings,
            constraints=active_constraints,
            object_handle_ids=object_handle_ids,
            result_handle_ids=result_handle_ids,
            primary_result_handle_id=(
                result_handle_ids[0] if result_handle_ids else str(main_context_payload.get("active_result_handle_id", "") or "")
            ),
            subset_handle_id=str(
                main_context_payload.get("active_subset_handle_id", "")
                or presentation_hints.get("subset_handle_id", "")
                or ""
            ),
            subset_labels=list(presentation_hints.get("subset_labels", []) or []),
            subset_hint_query=str(presentation_hints.get("subset_hint_query", "") or ""),
            binding_owner_task_id=str(event.get("binding_owner_task_id", "") or ""),
            degraded_reason_typed=degraded_reason_typed,
            metadata={
                "answer_channel": str(event.get("answer_channel", "") or ""),
                "answer_source": str(event.get("answer_source", "") or ""),
                "answer_fallback_reason": str(event.get("answer_fallback_reason", "") or ""),
                "execution_protocol": str(event.get("execution_protocol", "") or "worker"),
            },
        )
        context_ref_payload = task.context_ref.to_dict() if task.context_ref is not None else None
        result_ref_payload = task.result_ref.to_dict() if task.result_ref is not None else None
        summary_payload = task.summary.to_dict() if task.summary is not None else None
        task_summary_ref = self._task_summary_ref_from_task(task)
        main_context_payload.setdefault("followup_mode", "task_ref")
        main_context_payload["followup_target_task_id"] = task.task_id
        main_context_payload["followup_target_task_ids"] = [task.task_id]
        main_context_payload["followup_binding_owner_task_id"] = task.task_id
        if task.context_ref is not None:
            if task.context_ref.primary_object_handle_id:
                main_context_payload["active_object_handle_id"] = task.context_ref.primary_object_handle_id
            if task.context_ref.primary_result_handle_id:
                main_context_payload["active_result_handle_id"] = task.context_ref.primary_result_handle_id
            if task.context_ref.active_subset_handle_id:
                main_context_payload["active_subset_handle_id"] = task.context_ref.active_subset_handle_id
        event.update(
            {
                "task_id": task.task_id,
                "summary": summary_payload,
                "context_ref": context_ref_payload,
                "result_ref": result_ref_payload,
                "main_context": main_context_payload,
                "task_summary_refs": [task_summary_ref.to_dict()] if task_summary_ref is not None else list(event.get("task_summary_refs", []) or []),
                "object_handle_ids": list(task.metadata.get("object_handle_ids", []) or object_handle_ids),
                "result_handle_ids": list(task.metadata.get("result_handle_ids", []) or result_handle_ids),
                "binding_owner_task_id": str(
                    task.metadata.get("binding_owner_task_id", "")
                    or event.get("binding_owner_task_id", "")
                    or task.task_id
                ),
            }
        )
        return event

    def _build_single_execution_task_summaries(
        self,
        execution: QueryExecutionPlan,
        content: str,
    ) -> list[TaskSummaryRef]:
        summary = " ".join(sanitize_visible_assistant_content(str(content or "")).split()).strip()
        route = str(getattr(execution.query_understanding, "route", "") or "")
        if (
            not summary
            or route == "memory"
            or contains_internal_protocol(summary)
        ):
            return []
        constraints = self._apply_execution_binding_to_constraints(
            self._extract_active_constraints(execution.message),
            execution,
        )
        key_points: list[str] = []
        if constraints.get("top_n") is not None:
            key_points.append(f"top_n={constraints['top_n']}")
        if constraints.get("page") is not None:
            key_points.append(f"page={constraints['page']}")
        if constraints.get("group_by"):
            key_points.append(f"group_by={constraints['group_by']}")
        if constraints.get("pdf_mode"):
            key_points.append(f"pdf_mode={constraints['pdf_mode']}")
        if constraints.get("pdf_section"):
            key_points.append(f"pdf_section={constraints['pdf_section']}")
        pdf_focus_pages = list(constraints.get("pdf_focus_pages") or [])
        if pdf_focus_pages:
            key_points.append("pdf_pages=" + ",".join(str(item) for item in pdf_focus_pages if int(item) > 0))
        if constraints.get("active_dataset"):
            key_points.append(f"dataset={constraints['active_dataset']}")
        if constraints.get("active_pdf"):
            key_points.append(f"pdf={constraints['active_pdf']}")
        source_kind = str(constraints.get("source_kind", "") or "")
        task_slug = re.sub(r"[^a-z0-9]+", "-", execution.message.lower()).strip("-")[:48] or "main"
        return [
            TaskSummaryRef(
                task_id=f"{execution.query_understanding.route or 'main'}:{task_slug}",
                query=execution.message,
                summary=summary[:280],
                task_kind=self._normalize_task_kind(
                    source_kind or str(getattr(execution.query_understanding, "task_kind", "") or "")
                ),
                response_style=str(constraints.get("response_style", "") or ""),
                key_points=key_points,
            )
        ]

    def _normalize_task_kind(self, raw: str) -> str:
        lowered = str(raw or "").strip().lower()
        if not lowered:
            return ""
        if any(marker in lowered for marker in ("structured", "dataset", "table")):
            return "structured_data"
        if "pdf" in lowered or lowered.startswith("document_"):
            return "pdf"
        if "weather" in lowered:
            return "weather"
        if "finance" in lowered or "gold" in lowered:
            return "finance"
        return str(raw or "")

    def _merge_constraints_from_results(
        self,
        constraints: dict[str, Any],
        results: list[dict[str, object]],
    ) -> dict[str, Any]:
        return self._context_state.merge_constraints_from_results(constraints, results)

    def _capture_session_memory_projection(
        self,
        session_id: str,
        *,
        main_context_payload: Any,
        task_summary_payloads: Any,
    ) -> None:
        self._context_state.capture_session_memory_projection(
            session_id,
            main_context_payload=main_context_payload,
            task_summary_payloads=task_summary_payloads,
        )

    def _load_session_binding_snapshot(self, session_id: str) -> dict[str, Any]:
        return self._context_state.load_session_binding_snapshot(session_id)

    def _load_session_authoritative_context(self, session_id: str) -> dict[str, Any]:
        return self._context_state.load_session_authoritative_context(session_id)

    def _apply_execution_binding_to_constraints(
        self,
        constraints: dict[str, Any],
        execution: QueryExecutionPlan,
    ) -> dict[str, Any]:
        return self._context_state.apply_execution_binding_to_constraints(constraints, execution)

    def _binding_identity_from_constraints(self, constraints: dict[str, Any]) -> str:
        return self._context_state.binding_identity_from_constraints(constraints)

    def _extract_active_constraints(self, message: str) -> dict[str, Any]:
        return self._context_state.extract_active_constraints(message)

    def _should_answer_from_followup(
        self,
        *,
        message: str,
        followup_resolution,
        results: list[dict[str, object]],
    ) -> bool:
        return self._followup.should_answer_from_followup(
            message=message,
            followup_resolution=followup_resolution,
            results=results,
        )

    def _followup_results_from_resolution(
        self,
        session_id: str,
        followup_resolution,
    ) -> list[dict[str, object]]:
        return self._followup.followup_results_from_resolution(session_id, followup_resolution)

    def _followup_results_from_task_ids(
        self,
        session_id: str,
        task_ids: list[str],
    ) -> list[dict[str, object]]:
        return self._followup.followup_results_from_task_ids(session_id, task_ids)

    def _followup_result_from_done_event(
        self,
        event: dict[str, object],
        *,
        fallback_query: str,
    ) -> dict[str, object] | None:
        return self._followup.followup_result_from_done_event(event, fallback_query=fallback_query)

    def _synthesize_followup_task_summary_ref(
        self,
        *,
        task_id: str,
        query: str,
        content: str,
        task_kind: str = "",
    ) -> TaskSummaryRef | None:
        return self._followup.synthesize_followup_task_summary_ref(
            task_id=task_id,
            query=query,
            content=content,
            task_kind=task_kind,
        )

    def _binding_owner_task(self, session_id: str, followup_resolution) -> Any | None:
        return self._followup.binding_owner_task(session_id, followup_resolution)

    def _should_execute_binding_followup(
        self,
        *,
        session_id: str,
        followup_resolution,
        plan: QueryPlan,
    ) -> bool:
        return self._followup.should_execute_binding_followup(
            session_id=session_id,
            followup_resolution=followup_resolution,
            plan=plan,
        )

    def _normalize_binding_identity(self, value: str) -> str:
        return self._followup.normalize_binding_identity(value)

    def _binding_execution_from_owner(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        owner_task,
    ) -> QueryExecutionPlan | None:
        return self._followup.binding_execution_from_owner(
            session_id=session_id,
            message=message,
            history=history,
            owner_task=owner_task,
        )

    async def _stream_binding_followup(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        *,
        followup_resolution,
        trace=None,
    ):
        async for event in self._followup.stream_binding_followup(
            session_id,
            message,
            history,
            followup_resolution=followup_resolution,
            trace=trace,
            stream_planned_execution=self._stream_planned_execution,
            build_followup_main_context=self._build_followup_main_context,
            assemble_subtask_results=self._assemble_subtask_results,
            task_summary_refs_from_results=self._task_summary_refs_from_results,
        ):
            yield event

    def _resolved_task_id(self, followup_resolution) -> str:
        return self._followup.resolved_task_id(followup_resolution)

    def _resolved_task_ids(self, followup_resolution) -> list[str]:
        return self._followup.resolved_task_ids(followup_resolution)

    def _resolved_binding_kind(self, followup_resolution) -> str:
        return self._followup.resolved_binding_kind(followup_resolution)

    def _resolved_binding_identity(self, followup_resolution) -> str:
        return self._followup.resolved_binding_identity(followup_resolution)

    def _resolved_binding_owner_task_id(self, followup_resolution) -> str:
        return self._followup.resolved_binding_owner_task_id(followup_resolution)

    def _is_session_summary_execution(self, execution: QueryExecutionPlan) -> bool:
        route = str(getattr(execution.query_understanding, "route", "") or "").strip()
        task_kind = str(getattr(execution.query_understanding, "task_kind", "") or "").strip()
        intent = str(getattr(execution.query_understanding, "intent", "") or "").strip()
        return route == "memory" and (task_kind == "session_summary" or intent == "session_summary_query")

    def _should_isolate_augmented_history(self, execution: QueryExecutionPlan) -> bool:
        return self._should_isolate_explicit_durable_turn(execution) or self._is_session_summary_execution(execution)

    def _filter_runtime_sections_from_context_package(self, context_package: Any) -> Any:
        if context_package is None:
            return None
        filtered = copy.deepcopy(context_package)
        runtime_sections = {
            "active_process_context",
            "hot_truth_window",
            "warm_snapshots",
            "retrieval_evidence",
        }
        for attr_name in ("sections", "model_visible_sections", "debug_sections"):
            sections = getattr(filtered, attr_name, None)
            if not isinstance(sections, dict):
                continue
            copied = {
                str(name): ([] if str(name) in runtime_sections else list(items or []))
                for name, items in sections.items()
            }
            setattr(filtered, attr_name, copied)
        if hasattr(filtered, "selected_sections") and isinstance(filtered.model_visible_sections, dict):
            filtered.selected_sections = [
                name for name, items in filtered.model_visible_sections.items() if list(items or [])
            ]
        if hasattr(filtered, "debug_selected_sections") and isinstance(filtered.debug_sections, dict):
            filtered.debug_selected_sections = [
                name for name, items in filtered.debug_sections.items() if list(items or [])
            ]
        return filtered

    def _build_session_summary_instruction_block(
        self,
        *,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> str:
        tasks = [
            task
            for task in self.task_coordinator.list_tasks(session_id=session_id)
            if str(getattr(task, "status", "") or "") == "completed" and getattr(task, "summary", None) is not None
        ]
        grouped: dict[str, list[str]] = {"PDF": [], "数据": [], "实时": []}
        for task in tasks:
            category = self._session_summary_category_for_task(task)
            if category not in grouped:
                continue
            query = self._compact_session_summary_text(str(getattr(task, "query", "") or ""), limit=72)
            summary = self._compact_session_summary_text(
                str(getattr(getattr(task, "summary", None), "response", "") or ""),
                limit=150,
            )
            if not query and not summary:
                continue
            if query and summary:
                grouped[category].append(f"{query} -> {summary}")
            else:
                grouped[category].append(query or summary)

        memory_events = self._session_summary_memory_events(history)
        if not any(grouped.values()) and not memory_events:
            return ""

        lines = [
            "## Session Recap Ledger",
            "This turn is a session-wide recap request.",
            "Summarize from the structured ledger below, not from the latest active goal, recent hot window, or stale flow state.",
            "If a section has entries, it counts as involved. If a section has no stable entry, say 本轮未形成稳定结果 or 本轮未涉及. Do not invent execution, and do not say 正在查询 without a real result.",
        ]
        for title in ("PDF", "数据", "实时"):
            lines.append("")
            lines.append(f"### {title}")
            entries = grouped[title][:4]
            if entries:
                lines.extend(f"- {entry}" for entry in entries)
            else:
                lines.append("- 本轮没有稳定记录。")

        lines.append("")
        lines.append("### 长期记忆")
        if memory_events:
            lines.extend(f"- {entry}" for entry in memory_events[:4])
        else:
            lines.append("- 本轮没有明确的长期记忆写入或回看记录。")
        return "\n".join(lines).strip()

    def _session_summary_category_for_task(self, task: Any) -> str:
        context_ref = getattr(task, "context_ref", None)
        bindings = getattr(context_ref, "bindings", None)
        task_kind = str(getattr(context_ref, "task_kind", "") or "").strip().lower()
        source_kind = str(getattr(bindings, "source_kind", "") or "").strip().lower()
        if str(getattr(bindings, "active_pdf", "") or "").strip():
            return "PDF"
        if str(getattr(bindings, "active_dataset", "") or "").strip():
            return "数据"
        if str(getattr(bindings, "active_location", "") or "").strip():
            return "实时"
        if str(getattr(bindings, "active_entity", "") or "").strip() in {"黄金", "gold"}:
            return "实时"
        if source_kind == "pdf" or "pdf" in task_kind:
            return "PDF"
        if source_kind in {"dataset", "structured_data"} or task_kind in {"structured_data", "table"}:
            return "数据"
        if source_kind in {"weather", "finance", "realtime", "web"} or task_kind in {"weather", "finance", "realtime"}:
            return "实时"
        return "other"

    def _session_summary_memory_events(self, history: list[dict[str, Any]]) -> list[str]:
        events: list[str] = []
        for index, item in enumerate(history):
            if str(item.get("role", "") or "") != "user":
                continue
            content = str(item.get("content", "") or "").strip()
            if not content:
                continue
            intent = analyze_memory_intent(content)
            intent_name = str(getattr(intent, "intent", "") or "")
            if intent_name not in {"durable_memory_statement", "durable_memory_query"}:
                continue
            label = "记忆写入" if intent_name == "durable_memory_statement" else "记忆回看"
            user_line = self._compact_session_summary_text(content, limit=72)
            assistant_line = ""
            for candidate in history[index + 1 :]:
                role = str(candidate.get("role", "") or "")
                if role == "assistant":
                    assistant_line = self._compact_session_summary_text(str(candidate.get("content", "") or ""), limit=110)
                    break
                if role == "user":
                    break
            if assistant_line:
                events.append(f"{label}: {user_line} -> {assistant_line}")
            else:
                events.append(f"{label}: {user_line}")
        return events

    def _compact_session_summary_text(self, text: str, *, limit: int) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 3)].rstrip() + "..."

    def _extract_latest_correction(self, message: str) -> str:
        correction_markers = ("不对", "改成", "纠正", "不是", "更正")
        if any(marker in message for marker in correction_markers):
            return message.strip()
        return ""

    def _should_prefetch_durable_context(self, execution: QueryExecutionPlan) -> bool:
        if getattr(execution.memory_intent, "ignore_memory", False):
            return False
        if not str(getattr(execution, "message", "") or "").strip():
            return False
        if getattr(execution.memory_intent, "intent", "") == "session_continuity_query":
            return False
        route = str(getattr(execution.query_understanding, "route", "") or "")
        modality = str(getattr(execution.query_understanding, "modality", "") or "")
        if route == "tool" and modality in {"realtime", "web"}:
            return False
        return True

    def _new_segment(self) -> dict[str, Any]:
        return {"content": "", "tool_calls": []}

    def _allowed_tool_names_for_plan(self, plan: QueryPlan) -> set[str]:
        return self._tool_bridge.allowed_tool_names_for_plan(plan)

    def _allowed_tool_names_for_execution(self, execution: QueryExecutionPlan) -> set[str]:
        return self._tool_bridge.allowed_tool_names_for_execution(execution)

    async def _stream_direct_tool_execution(
        self,
        session_id: str,
        execution: QueryExecutionPlan,
        *,
        trace=None,
    ):
        async for event in self._tool_bridge.stream_direct_tool_execution(session_id, execution, trace=trace):
            yield event

    def _evaluate_tool_contract(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        execution: QueryExecutionPlan,
    ) -> ToolContractDecision:
        return self._tool_bridge.evaluate_tool_contract(
            tool_name=tool_name,
            tool_input=tool_input,
            execution=execution,
        )

    def _effective_tool_contract_mode(self, tool_name: str) -> str:
        return self._tool_bridge.effective_tool_contract_mode(tool_name)

    def _tool_contract_failure_message(
        self,
        *,
        tool_name: str,
        contract_decision: ToolContractDecision,
    ) -> str:
        return self._tool_bridge.tool_contract_failure_message(
            tool_name=tool_name,
            contract_decision=contract_decision,
        )

    def _normalize_direct_tool_output(
        self,
        output: Any,
        *,
        tool_name: str = "",
        query: str = "",
        route: str = "tool",
    ) -> str:
        return self._tool_bridge.normalize_direct_tool_output(
            output,
            tool_name=tool_name,
            query=query,
            route=route,
        )

    def _build_direct_tool_output_decision(
        self,
        output: Any,
        *,
        tool_name: str = "",
        query: str = "",
        route: str = "tool",
        force_allow_unlabeled: bool = False,
    ):
        return self._tool_bridge.build_direct_tool_output_decision(
            output,
            tool_name=tool_name,
            query=query,
            route=route,
            force_allow_unlabeled=force_allow_unlabeled,
        )

    def _prepare_direct_tool_output_candidate(self, output: Any) -> tuple[str, bool]:
        return self._tool_bridge.prepare_direct_tool_output_candidate(output)

    def _stringify_tool_output(self, output: Any) -> str:
        return self._tool_bridge.stringify_tool_output(output)

    async def _maybe_finalize_rag_output(
        self,
        *,
        execution: QueryExecutionPlan,
        retrieval_results: list[dict[str, Any]] | None,
        output_response,
    ):
        return await self._output_policy.maybe_finalize_rag_output(
            execution=execution,
            retrieval_results=retrieval_results,
            output_response=output_response,
        )

    async def _rewrite_rag_answer_with_model(
        self,
        *,
        evidence_pack: RAGEvidencePack,
    ) -> str:
        return await self._output_policy.rewrite_rag_answer_with_model(evidence_pack=evidence_pack)

    def _rag_evidence_pack_can_finalize(self, evidence_pack: RAGEvidencePack | None) -> bool:
        return self._output_policy.rag_evidence_pack_can_finalize(evidence_pack)

    def _fallback_rag_output_response(self, output_response):
        return self._output_policy.fallback_rag_output_response(output_response)

    def _maybe_gate_memory_output(
        self,
        *,
        execution: QueryExecutionPlan,
        output_response,
    ):
        return self._output_policy.maybe_gate_memory_output(
            execution=execution,
            output_response=output_response,
        )

    def _memory_output_needs_gate(self, output_response) -> bool:
        return self._output_policy.memory_output_needs_gate(output_response)

    def _fallback_memory_output_response(self, output_response):
        return self._output_policy.fallback_memory_output_response(output_response)

    def _looks_like_rag_procedural_answer(self, answer: str) -> bool:
        return self._output_policy.looks_like_rag_procedural_answer(answer)

    def _should_isolate_explicit_durable_turn(
        self,
        execution: QueryExecutionPlan,
    ) -> bool:
        intent_name = str(getattr(execution.memory_intent, "intent", "") or "").strip()
        return intent_name in {"durable_memory_statement", "durable_memory_query"}

    def _should_handle_memory_write_directly(
        self,
        execution: QueryExecutionPlan,
    ) -> bool:
        intent_name = str(getattr(execution.memory_intent, "intent", "") or "").strip()
        write_mode = str(getattr(execution.memory_intent, "memory_write_mode", "") or "").strip()
        return intent_name == "durable_memory_statement" and write_mode == "durable_fact"

    def _build_memory_write_acknowledgement(self, message: str) -> str:
        normalized = self._normalize_memory_write_statement(message)
        decision = evaluate_memory_write(message)
        if decision.action == "durable_fact":
            if normalized:
                return f"好，我会把这条作为长期记忆保留：{normalized}"
            return "好，我会把这条作为长期记忆保留。"
        if decision.action == "session_only":
            if normalized:
                return f"这条我会按当前会话记住，但不写入长期记忆：{normalized}"
            return "这条我会按当前会话记住，但不写入长期记忆。"
        if normalized:
            return f"这条我不会写入长期记忆；它更适合作为当前会话约定或静态设定处理：{normalized}"
        return "这条我不会写入长期记忆；它更适合作为当前会话约定或静态设定处理。"

    def _normalize_memory_write_statement(self, message: str) -> str:
        normalized = sanitize_visible_assistant_content(str(message or "")).strip()
        if not normalized:
            return ""
        normalized = re.sub(
            r"^(?:记住|记一下|别忘了|记到长期记忆|remember that|remember|don't forget)\s*[:：,，-]*\s*",
            "",
            normalized,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        return normalized

    def _merge_summary_key_points(
        self,
        existing: list[str],
        *,
        pdf_path: str = "",
        page: int | None = None,
        pdf_mode: str = "",
        pdf_section: str = "",
        pdf_pages: list[int] | None = None,
        readable_pages: int | None = None,
        usable_pages: int | None = None,
    ) -> list[str]:
        return self._output_policy.merge_summary_key_points(
            existing,
            pdf_path=pdf_path,
            page=page,
            pdf_mode=pdf_mode,
            pdf_section=pdf_section,
            pdf_pages=pdf_pages,
            readable_pages=readable_pages,
            usable_pages=usable_pages,
        )

    def _pdf_task_kind_from_mode(self, mode: str) -> str:
        return self._output_policy.pdf_task_kind_from_mode(mode)

    def _normalize_pdf_scope(self, mode: str) -> str:
        return self._output_policy.normalize_pdf_scope(mode)

    def _assemble_subtask_results(
        self,
        results: list[dict[str, object]],
        *,
        main_context: MainContextState,
    ) -> str:
        plan = self.answer_assembler.build_plan(results=results, main_context=main_context)
        return self.answer_assembler.render(plan)

    def _user_visible_error(self, exc: Exception) -> str:
        if isinstance(exc, ModelRuntimeError):
            return exc.user_message
        return str(exc)

    def _is_internal_skill_read_tool_call(self, tool_call: dict[str, Any]) -> bool:
        return self._persistence.is_internal_skill_read_tool_call(tool_call)

    def _looks_like_skill_document(self, content: str) -> bool:
        return self._persistence.looks_like_skill_document(content)

    def _sanitize_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any] | None:
        return self._persistence.sanitize_tool_call(tool_call)

    def _finalize_segments(
        self,
        segments: list[dict[str, Any]],
        current_segment: dict[str, Any],
        *,
        fallback_content: str = "",
    ) -> list[dict[str, Any]]:
        return self._persistence.finalize_segments(
            segments,
            current_segment,
            fallback_content=fallback_content,
        )

    def _build_assistant_messages(
        self,
        segments: list[dict[str, Any]],
        *,
        canonical_content: str | None = None,
        answer_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._persistence.build_assistant_messages(
            segments,
            canonical_content=canonical_content,
            answer_metadata=answer_metadata,
        )

    def _assistant_metadata_from_done_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return self._persistence.assistant_metadata_from_done_event(event)

    def _apply_assistant_persistence_gate(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> str:
        return self._persistence.apply_assistant_persistence_gate(content, tool_calls)

    def _has_completed_tool_receipt(self, tool_calls: list[dict[str, Any]]) -> bool:
        return self._persistence.has_completed_tool_receipt(tool_calls)


def _structured_dataset_path(value: str) -> bool:
    suffix = PurePosixPath(str(value or "").replace("\\", "/").split("#", 1)[0]).suffix.lower()
    return suffix in {".xlsx", ".xls", ".csv", ".json", ".parquet"}
