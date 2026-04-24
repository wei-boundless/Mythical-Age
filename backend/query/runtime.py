from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import os
import re
from dataclasses import replace
from typing import Any

from agents import MAIN_AGENT
from observability import build_debug_trace_event, start_turn_trace
from pdf_agent import PDFCanonicalResult
from query.answer_assembler import AnswerAssembler
from query.answer_finalizer import (
    RAGEvidencePack,
    answer_looks_like_snippet_dump,
    build_rag_answer_finalization_messages,
    build_rag_evidence_pack,
    normalize_finalized_answer,
    total_compact_chars,
)
from query.binding_models import StructuredDatasetBinding
from query.context_models import MainContextState, TaskSummaryRef
from query.followup_resolver import QueryFollowupResolver
from query.models import QueryContext, QueryExecutionPlan, QueryPlan, QueryRequest
from query.output_classifier import (
    build_output_decision,
    classify_output_candidate,
    looks_like_progress_text,
    looks_like_procedural_promise_text,
    looks_like_tool_claim_without_receipt,
)
from query.output_boundary import AssistantOutputBoundary, contains_internal_protocol, sanitize_visible_assistant_content
from query.prompt_builder import build_system_prompt
from query.planner import QueryPlanner
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content
from skill_system import SkillDefinition
from tasks.context_models import TaskConstraints
from tasks.coordinator import TaskCoordinator
from tools.contracts import ToolContractDecision, ToolContractGate
from tools.definitions import get_tool_definition_map
from understanding import MemoryIntent, QueryUnderstanding, analyze_memory_intent, evaluate_memory_write

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
        self._session_memory_projection: dict[str, dict[str, Any]] = {}
        self.max_tool_steps = 8
        self.tool_contract_gate = ToolContractGate(
            mode=str(os.getenv("TOOL_CONTRACT_MODE", "shadow") or "shadow").strip().lower()
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
            active_skill=self._render_active_skill_prompt(execution.active_skill),
        )

    def _render_active_skill_prompt(self, active_skill: SkillDefinition | None) -> str | None:
        if active_skill is None:
            return None
        return active_skill.render_prompt_block()

    def _skill_allowed_tool_scope(self, active_skill: SkillDefinition | None) -> list[str]:
        if active_skill is None:
            return []
        return active_skill.allowed_tool_scope()

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
        plan = self._planner_build_plan(
            session_id=session_id,
            message=message,
            history=history,
            ephemeral_system_messages=ephemeral_system_messages,
            authority_context=self._load_session_authoritative_context(session_id),
        )
        executions = plan.iter_executions()
        execution = executions[0]
        async for event in self._stream_planned_execution(session_id, execution, trace=trace):
            yield event

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
            output_response = await self._maybe_finalize_pdf_output(
                execution=execution,
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
        constraints = self._extract_active_constraints(message)
        target_task_ids = self._resolved_task_ids(followup_resolution)
        target_task_id = self._resolved_task_id(followup_resolution) or (target_task_ids[0] if target_task_ids else "")
        work_item = "followup_task_result_assembly"
        if followup_resolution.mode == "explicit_fanout_subset":
            work_item = "followup_explicit_fanout_subset_assembly"
        elif followup_resolution.mode == "bundle_subset":
            work_item = "followup_bundle_subset_assembly"
        elif followup_resolution.mode == "bundle_item_ref":
            work_item = "followup_bundle_item_result"
        elif followup_resolution.mode == "binding_ref":
            work_item = "followup_task_binding_execution"
        merged_constraints = self._merge_constraints_from_results(constraints, results)
        active_binding_identity = self._resolved_binding_identity(followup_resolution)
        if not active_binding_identity:
            active_binding_identity = self._binding_identity_from_constraints(merged_constraints)
        return MainContextState(
            active_goal=message.strip(),
            active_work_item=work_item,
            active_binding_identity=active_binding_identity,
            followup_mode=str(followup_resolution.mode or ""),
            followup_resolution_source=str(getattr(followup_resolution, "resolution_source", "") or ""),
            followup_target_task_id=target_task_id or None,
            followup_target_task_ids=target_task_ids,
            followup_binding_key=self._resolved_binding_kind(followup_resolution),
            followup_binding_identity=self._resolved_binding_identity(followup_resolution),
            followup_binding_owner_task_id=(
                self._resolved_binding_owner_task_id(followup_resolution) or None
            ),
            active_constraints=merged_constraints,
            latest_correction=self._extract_latest_correction(message),
            next_step="answer_selected_task_results",
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
                    task_kind=str(
                        context_ref_payload.get("task_kind", "") if isinstance(context_ref_payload, dict) else ""
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
            task_kind = str(task.context_ref.task_kind or "")
        return TaskSummaryRef(
            task_id=str(task.task_id or ""),
            query=str(task.query or ""),
            summary=str(task.summary.response or ""),
            task_kind=task_kind,
            response_style=str(task.summary.response_style or ""),
            key_points=list(task.summary.key_points or []),
        )

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
                task_kind=source_kind or str(getattr(execution.query_understanding, "task_kind", "") or ""),
                response_style=str(constraints.get("response_style", "") or ""),
                key_points=key_points,
            )
        ]

    def _merge_constraints_from_results(
        self,
        constraints: dict[str, Any],
        results: list[dict[str, object]],
    ) -> dict[str, Any]:
        merged = dict(constraints)
        for item in reversed(results):
            context_ref_payload = item.get("context_ref")
            if not isinstance(context_ref_payload, dict):
                continue
            bindings = dict(context_ref_payload.get("bindings") or {})
            binding_identity = str(bindings.get("active_binding_identity", "") or "").strip()
            if bindings.get("active_pdf") and not merged.get("active_pdf"):
                merged["active_pdf"] = str(bindings["active_pdf"])
                merged.setdefault(
                    "active_binding_identity",
                    binding_identity or str(bindings["active_pdf"]).replace("\\", "/").strip().lower(),
                )
            if bindings.get("active_dataset") and not merged.get("active_dataset"):
                merged["active_dataset"] = str(bindings["active_dataset"])
                merged.setdefault(
                    "active_binding_identity",
                    binding_identity or str(bindings["active_dataset"]).replace("\\", "/").strip().lower(),
                )
            if bindings.get("active_location") and not merged.get("active_location"):
                merged["active_location"] = str(bindings["active_location"])
            if bindings.get("source_kind") and not merged.get("source_kind"):
                merged["source_kind"] = str(bindings["source_kind"])
            constraints_payload = item.get("context_ref")
            if isinstance(constraints_payload, dict):
                task_constraints = dict(constraints_payload.get("constraints") or {})
                if task_constraints.get("page") is not None and merged.get("page") is None:
                    merged["page"] = int(task_constraints["page"])
                if task_constraints.get("group_by") and not merged.get("group_by"):
                    merged["group_by"] = str(task_constraints["group_by"])
                if task_constraints.get("pdf_mode") and not merged.get("pdf_mode"):
                    merged["pdf_mode"] = str(task_constraints["pdf_mode"])
                if task_constraints.get("pdf_section") and not merged.get("pdf_section"):
                    merged["pdf_section"] = str(task_constraints["pdf_section"])
                if task_constraints.get("pdf_focus_pages") and not merged.get("pdf_focus_pages"):
                    merged["pdf_focus_pages"] = list(task_constraints["pdf_focus_pages"])
                if task_constraints.get("readable_pages") is not None and merged.get("readable_pages") is None:
                    merged["readable_pages"] = int(task_constraints["readable_pages"])
                if task_constraints.get("usable_pages") is not None and merged.get("usable_pages") is None:
                    merged["usable_pages"] = int(task_constraints["usable_pages"])
                if task_constraints.get("total_pages") is not None and merged.get("total_pages") is None:
                    merged["total_pages"] = int(task_constraints["total_pages"])
        return merged

    def _capture_session_memory_projection(
        self,
        session_id: str,
        *,
        main_context_payload: Any,
        task_summary_payloads: Any,
    ) -> None:
        corrections: list[str] = []
        if isinstance(main_context_payload, dict):
            latest_correction = str(main_context_payload.get("latest_correction", "") or "").strip()
            if latest_correction:
                corrections.append(latest_correction)
        task_summaries = task_summary_payloads if isinstance(task_summary_payloads, list) else []
        self._session_memory_projection[session_id] = {
            "main_context": main_context_payload,
            "task_summary_refs": task_summaries,
            "corrections": corrections,
        }

    def _load_session_binding_snapshot(self, session_id: str) -> dict[str, Any]:
        session_memory = getattr(self.memory_facade, "session_memory", None)
        if session_memory is None or not hasattr(session_memory, "manager"):
            return {}
        try:
            manager = session_memory.manager(session_id)
            state = manager.load_state()
        except Exception:
            logger.exception("Failed to load session binding snapshot for %s", session_id)
            return {}
        slots = getattr(state, "context_slots", None)
        if slots is None:
            return {}
        committed_pdf = str(getattr(slots, "committed_pdf", "") or getattr(slots, "active_pdf", "") or "").strip()
        committed_dataset = str(
            getattr(slots, "committed_dataset", "") or getattr(slots, "active_dataset", "") or ""
        ).strip()
        return {
            "committed_pdf": committed_pdf,
            "committed_pdf_owner_task_id": str(
                getattr(slots, "committed_pdf_owner_task_id", "")
                or (getattr(slots, "active_binding_owner_task_id", "") if committed_pdf else "")
                or ""
            ).strip(),
            "committed_dataset": committed_dataset,
            "committed_dataset_owner_task_id": str(
                getattr(slots, "committed_dataset_owner_task_id", "")
                or (getattr(slots, "active_binding_owner_task_id", "") if committed_dataset else "")
                or ""
            ).strip(),
        }

    def _load_session_authoritative_context(self, session_id: str) -> dict[str, Any]:
        snapshot = self._load_session_binding_snapshot(session_id)
        context: dict[str, Any] = {}
        committed_pdf = str(snapshot.get("committed_pdf", "") or "").strip()
        if committed_pdf:
            context["active_pdf"] = committed_pdf
        committed_dataset = str(snapshot.get("committed_dataset", "") or "").strip()
        if committed_dataset:
            context["active_dataset"] = committed_dataset
        return context

    def _apply_execution_binding_to_constraints(
        self,
        constraints: dict[str, Any],
        execution: QueryExecutionPlan,
    ) -> dict[str, Any]:
        merged = dict(constraints)
        tool_input = dict(getattr(execution, "tool_input", {}) or {})
        pdf_path = str(tool_input.get("path", "") or "").strip()
        if pdf_path and str(getattr(execution.query_understanding, "tool_name", "") or "") == "pdf_analysis":
            merged["active_pdf"] = pdf_path
            merged["active_binding_identity"] = pdf_path.replace("\\", "/").strip().lower()
            merged.setdefault("source_kind", "pdf")
            if str(tool_input.get("mode", "") or "").strip():
                merged["pdf_mode"] = self._normalize_pdf_scope(str(tool_input.get("mode", "") or "").strip())
        binding = getattr(execution, "structured_binding", None)
        if binding is None:
            return merged
        dataset_path = str(getattr(binding, "dataset_path", "") or "").strip()
        if dataset_path:
            merged["active_dataset"] = dataset_path
            merged["active_binding_identity"] = str(
                getattr(binding, "binding_identity", "") or dataset_path.replace("\\", "/").strip().lower()
            )
            merged.setdefault("source_kind", "dataset")
        return merged

    def _binding_identity_from_constraints(self, constraints: dict[str, Any]) -> str:
        explicit = str(constraints.get("active_binding_identity", "") or "").strip()
        if explicit:
            return explicit
        active_pdf = str(constraints.get("active_pdf", "") or "").strip()
        if active_pdf:
            return active_pdf.replace("\\", "/").lower()
        active_dataset = str(constraints.get("active_dataset", "") or "").strip()
        if active_dataset:
            return active_dataset.replace("\\", "/").lower()
        return ""

    def _extract_active_constraints(self, message: str) -> dict[str, Any]:
        lowered = message.lower()
        constraints: dict[str, Any] = {}
        top_match = None
        for pattern in (r"(?:前|top\s*)(\d+)",):
            top_match = re.search(pattern, message, flags=re.IGNORECASE)
            if top_match:
                break
        if top_match:
            constraints["top_n"] = int(top_match.group(1))
        if "一句话" in message or "一句" in message:
            constraints["response_style"] = "one_sentence"
        elif "简要" in message or "简短" in message:
            constraints["response_style"] = "brief"
        page_match = re.search(r"第\s*(\d+)\s*页", message)
        if page_match:
            constraints["page"] = int(page_match.group(1))
            constraints["pdf_mode"] = "page"
        elif re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
            constraints["pdf_mode"] = "page"
        elif re.search(r"page\s*\d+", lowered):
            constraints["pdf_mode"] = "page"
        section_match = re.search(r"(第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节))", message)
        if section_match:
            constraints["pdf_mode"] = "section"
            constraints["pdf_section"] = str(section_match.group(1) or "").strip()
        else:
            for marker in ("这一部分", "那一部分", "这一章", "那一章", "这一节", "那一节"):
                if marker in message:
                    constraints["pdf_mode"] = "section"
                    constraints["pdf_section"] = marker
                    break
        if "按仓库" in message:
            constraints["group_by"] = "仓库"
        elif "按地区" in message:
            constraints["group_by"] = "地区"
        if "不要重复" in message:
            constraints["dedupe"] = True
        if "补一句" in message:
            constraints["append_mode"] = "single_sentence_append"
        has_pdf_overview_hint = any(
            marker in message for marker in ("全文总览", "总览", "概览", "核心结论", "行动建议", "完整总结", "详细解读")
        )
        if has_pdf_overview_hint and constraints.get("pdf_mode") not in {"page", "section"}:
            constraints["pdf_mode"] = "document"
        if "pdf" in lowered:
            constraints["source_kind"] = "pdf"
            constraints.setdefault("pdf_mode", "document")
        elif any(ext in lowered for ext in (".xlsx", ".csv", ".xls")):
            constraints["source_kind"] = "dataset"
        return constraints

    def _should_answer_from_followup(
        self,
        *,
        message: str,
        followup_resolution,
        results: list[dict[str, object]],
    ) -> bool:
        if not results:
            return False
        if followup_resolution.mode not in {"task_ref", "explicit_fanout_subset", "bundle_item_ref", "bundle_subset"}:
            return False
        return bool(message.strip())

    def _followup_results_from_resolution(
        self,
        session_id: str,
        followup_resolution,
    ) -> list[dict[str, object]]:
        if followup_resolution.mode not in {"task_ref", "explicit_fanout_subset", "bundle_item_ref", "bundle_subset"}:
            return []
        task_ids = self._resolved_task_ids(followup_resolution)
        if not task_ids and self._resolved_task_id(followup_resolution):
            task_ids = [self._resolved_task_id(followup_resolution)]
        return self._followup_results_from_task_ids(session_id, task_ids)

    def _followup_results_from_task_ids(
        self,
        session_id: str,
        task_ids: list[str],
    ) -> list[dict[str, object]]:
        if not task_ids:
            return []
        records: list[dict[str, object]] = []
        for task_id in task_ids:
            task = self.task_coordinator.get_task(task_id)
            if task is None:
                continue
            if str(task.metadata.get("session_id", "")) != session_id:
                continue
            records.append(
                {
                    "index": int(
                        getattr(getattr(task, "context_ref", None), "bundle_item_index", 0)
                        or task.metadata.get("bundle_item_index", 0)
                        or task.metadata.get("subtask_index", 0)
                        or len(records) + 1
                    ),
                    "query": task.query,
                    "content": task.result,
                    "task_id": task.task_id,
                    "summary": task.summary.to_dict() if task.summary is not None else None,
                    "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
                    "result_ref": task.result_ref.to_dict() if task.result_ref is not None else None,
                }
            )
        return sorted(records, key=lambda item: int(item.get("index", 0) or 0))

    def _followup_result_from_done_event(
        self,
        event: dict[str, object],
        *,
        fallback_query: str,
    ) -> dict[str, object] | None:
        task_id = str(event.get("task_id", "") or "").strip()
        summary_payload = event.get("summary")
        context_ref_payload = event.get("context_ref")
        result_ref_payload = event.get("result_ref")
        content = event.get("content")
        if not task_id and not isinstance(summary_payload, dict):
            return None
        return {
            "index": 1,
            "query": str(event.get("query", "") or fallback_query),
            "content": content if content is not None else "",
            "task_id": task_id,
            "summary": summary_payload if isinstance(summary_payload, dict) else None,
            "context_ref": context_ref_payload if isinstance(context_ref_payload, dict) else None,
            "result_ref": result_ref_payload if isinstance(result_ref_payload, dict) else None,
        }

    def _synthesize_followup_task_summary_ref(
        self,
        *,
        task_id: str,
        query: str,
        content: str,
        task_kind: str = "",
    ) -> TaskSummaryRef | None:
        summary = " ".join(sanitize_visible_assistant_content(str(content or "")).split()).strip()
        if not task_id or not summary or contains_internal_protocol(summary):
            return None
        return TaskSummaryRef(
            task_id=task_id,
            query=query,
            summary=summary[:280],
            task_kind=task_kind,
        )

    def _binding_owner_task(self, session_id: str, followup_resolution) -> Any | None:
        owner_task_id = str(
            self._resolved_binding_owner_task_id(followup_resolution)
            or self._resolved_task_id(followup_resolution)
            or ""
        ).strip()
        if not owner_task_id:
            return None
        task = self.task_coordinator.get_task(owner_task_id)
        if task is None:
            return None
        if str(task.metadata.get("session_id", "")) != session_id:
            return None
        return task

    def _should_execute_binding_followup(
        self,
        *,
        session_id: str,
        followup_resolution,
        plan: QueryPlan,
    ) -> bool:
        if str(getattr(followup_resolution, "mode", "") or "") != "binding_ref":
            return False
        owner_task = self._binding_owner_task(session_id, followup_resolution)
        if owner_task is None:
            return False
        executions = plan.iter_executions()
        if len(executions) != 1:
            return False
        execution = executions[0]
        if str(getattr(execution.query_understanding, "route", "") or "") != "tool":
            return False
        binding_kind = self._resolved_binding_kind(followup_resolution)
        tool_name = str(getattr(execution.query_understanding, "tool_name", "") or "").strip()
        tool_input = dict(getattr(execution, "tool_input", {}) or getattr(execution.query_understanding, "tool_input", {}) or {})
        normalized_path = self._normalize_binding_identity(str(tool_input.get("path", "") or ""))
        normalized_location = str(tool_input.get("location", "") or "").strip()
        owner_context = getattr(owner_task, "context_ref", None)
        owner_bindings = getattr(owner_context, "bindings", None)
        if binding_kind == "active_pdf":
            owner_path = self._normalize_binding_identity(str(getattr(owner_bindings, "active_pdf", "") or ""))
            return tool_name == "pdf_analysis" and (not normalized_path or normalized_path == owner_path)
        if binding_kind == "active_dataset":
            owner_path = self._normalize_binding_identity(str(getattr(owner_bindings, "active_dataset", "") or ""))
            return tool_name == "structured_data_analysis" and (not normalized_path or normalized_path == owner_path)
        if binding_kind == "active_location":
            owner_location = str(getattr(owner_bindings, "active_location", "") or "").strip()
            return tool_name == "get_weather" and (not normalized_location or normalized_location == owner_location)
        if binding_kind == "active_entity":
            owner_entity = str(getattr(owner_bindings, "active_entity", "") or "").strip()
            return tool_name == "get_gold_price" and owner_entity == "黄金"
        return False

    def _normalize_binding_identity(self, value: str) -> str:
        return str(value or "").replace("\\", "/").strip().lower()

    def _binding_execution_from_owner(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
        owner_task,
    ) -> QueryExecutionPlan | None:
        context_ref = getattr(owner_task, "context_ref", None)
        if context_ref is None:
            return None
        bindings = context_ref.bindings
        tool_name = str(owner_task.metadata.get("tool_name", "") or "").strip()
        query_understanding: QueryUnderstanding | None = None
        structured_binding: StructuredDatasetBinding | None = None
        tool_input: dict[str, Any] = {"query": message}

        if bindings.active_pdf:
            tool_name = tool_name or "pdf_analysis"
            tool_input["path"] = bindings.active_pdf
            query_understanding = QueryUnderstanding(
                intent="pdf_followup_query",
                source_kind="pdf",
                task_kind=context_ref.task_kind or "pdf",
                modality="pdf",
                route="tool",
                execution_posture="direct_tool",
                direct_route_reason="binding_owner_pdf",
                tool_name=tool_name,
                tool_input=dict(tool_input),
                should_skip_rag=True,
            )
        elif bindings.active_dataset:
            tool_name = tool_name or "structured_data_analysis"
            tool_input["path"] = bindings.active_dataset
            structured_binding = StructuredDatasetBinding(
                dataset_path=bindings.active_dataset,
                target_object=bindings.active_entity,
                source="binding_owner",
                confidence=1.0,
                binding_identity=str(
                    bindings.active_binding_identity or str(bindings.active_dataset or "").replace("\\", "/").strip().lower()
                ),
                derived_from_task_id=owner_task.task_id,
            )
            query_understanding = QueryUnderstanding(
                intent="structured_followup_query",
                source_kind="dataset",
                task_kind=context_ref.task_kind or "structured_data",
                modality="table",
                route="tool",
                execution_posture="direct_tool",
                direct_route_reason="binding_owner_dataset",
                tool_name=tool_name,
                tool_input=dict(tool_input),
                should_skip_rag=True,
            )
        elif bindings.active_location:
            tool_name = tool_name or "get_weather"
            tool_input["location"] = bindings.active_location
            query_understanding = QueryUnderstanding(
                intent="weather_followup_query",
                source_kind="weather",
                task_kind=context_ref.task_kind or "weather",
                modality="realtime",
                route="tool",
                execution_posture="direct_tool",
                direct_route_reason="binding_owner_weather",
                tool_name=tool_name,
                tool_input=dict(tool_input),
                should_skip_rag=True,
            )
        elif bindings.active_entity == "黄金":
            tool_name = tool_name or "get_gold_price"
            query_understanding = QueryUnderstanding(
                intent="finance_followup_query",
                source_kind="finance",
                task_kind=context_ref.task_kind or "finance",
                modality="realtime",
                route="tool",
                execution_posture="direct_tool",
                direct_route_reason="binding_owner_finance",
                tool_name=tool_name,
                tool_input=dict(tool_input),
                should_skip_rag=True,
            )
        if query_understanding is None:
            return None
        return QueryExecutionPlan(
            message=message,
            history=list(history),
            memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
            query_understanding=query_understanding,
            tool_input=tool_input,
            structured_binding=structured_binding,
            execution_kind="direct_tool",
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
        owner_task = self._binding_owner_task(session_id, followup_resolution)
        if owner_task is None:
            return
        if trace is not None:
            trace.annotate(
                {
                    "app.route": "followup_binding",
                    "app.binding_owner_task_id": owner_task.task_id,
                }
            )
        execution = self._binding_execution_from_owner(
            message=message,
            history=history,
            owner_task=owner_task,
        )
        if execution is None:
            return
        async for event in self._stream_planned_execution(session_id, execution, trace=trace):
            if event.get("type") != "done":
                yield event
                continue
            event = dict(event)
            task_summary_payloads = list(event.get("task_summary_refs") or [])
            task_ids = [
                str(dict(item or {}).get("task_id", "") or "").strip()
                for item in task_summary_payloads
                if str(dict(item or {}).get("task_id", "") or "").strip()
            ]
            followup_results = self._followup_results_from_task_ids(session_id, task_ids)
            if not followup_results:
                synthetic_result = self._followup_result_from_done_event(event, fallback_query=message)
                if synthetic_result is not None:
                    followup_results = [synthetic_result]
            if followup_results:
                resolved_followup_task_id = (
                    task_ids[-1]
                    if task_ids
                    else str(event.get("task_id", "") or self._resolved_task_id(followup_resolution)).strip()
                )
                resolved_followup_task_ids = (
                    list(task_ids)
                    if task_ids
                    else [resolved_followup_task_id] if resolved_followup_task_id else self._resolved_task_ids(followup_resolution)
                )
                synthetic_resolution = followup_resolution.model_copy(
                    update={
                        "task_id": resolved_followup_task_id,
                        "resolved_task_id": resolved_followup_task_id,
                        "task_ids": resolved_followup_task_ids,
                        "resolved_task_ids": resolved_followup_task_ids,
                    }
                )
                main_context = self._build_followup_main_context(
                    message,
                    followup_results,
                    followup_resolution=synthetic_resolution,
                )
                event["main_context"] = main_context.to_dict()
                event["content"] = self._assemble_subtask_results(
                    followup_results,
                    main_context=main_context,
                )
                if not task_summary_payloads:
                    followup_task_refs = self._task_summary_refs_from_results(followup_results)
                    if not followup_task_refs:
                        followup_task_refs = [
                            synthetic_ref
                            for synthetic_ref in [
                                self._synthesize_followup_task_summary_ref(
                                    task_id=synthetic_resolution.resolved_task_id
                                    or synthetic_resolution.task_id,
                                    query=message,
                                    content=str(event.get("content", "") or ""),
                                    task_kind=str(synthetic_resolution.resolved_task_kind or ""),
                                )
                            ]
                            if synthetic_ref is not None
                        ]
                    event["task_summary_refs"] = [
                        item.to_dict() if isinstance(item, TaskSummaryRef) else dict(item or {})
                        for item in followup_task_refs
                    ]
            event["followup_mode"] = followup_resolution.mode
            yield event

    def _resolved_task_id(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_task_id", "")
            or getattr(followup_resolution, "task_id", "")
            or ""
        ).strip()

    def _resolved_task_ids(self, followup_resolution) -> list[str]:
        task_ids = list(getattr(followup_resolution, "resolved_task_ids", []) or [])
        if not task_ids:
            task_ids = list(getattr(followup_resolution, "task_ids", []) or [])
        return [str(task_id or "").strip() for task_id in task_ids if str(task_id or "").strip()]

    def _resolved_binding_kind(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_binding_kind", "")
            or getattr(followup_resolution, "binding_kind", "")
            or getattr(followup_resolution, "binding_key", "")
            or ""
        ).strip()

    def _resolved_binding_identity(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_binding_identity", "")
            or getattr(followup_resolution, "binding_identity", "")
            or getattr(followup_resolution, "resolved_binding_ref", "")
            or ""
        ).strip()

    def _resolved_binding_owner_task_id(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_binding_owner_task_id", "")
            or getattr(followup_resolution, "binding_owner_task_id", "")
            or ""
        ).strip()

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
        return self._allowed_tool_names_for_execution(plan.iter_executions()[0])

    def _allowed_tool_names_for_execution(self, execution: QueryExecutionPlan) -> set[str]:
        route = str(execution.query_understanding.route or "").strip()
        execution_posture = str(
            execution.execution_posture or getattr(execution.query_understanding, "execution_posture", "") or ""
        ).strip()
        skill_scope = self._skill_allowed_tool_scope(execution.active_skill)

        if route == "memory":
            return set()
        if route == "rag" and execution_posture != "bounded_agent":
            return set()

        if execution_posture == "bounded_agent":
            requested = list(getattr(execution.query_understanding, "candidate_tools", []) or [])
            if not requested and skill_scope:
                requested.extend(skill_scope)
            return set(self.permission_service.allowed_tool_names(allowed_tools=requested or None))

        if route == "tool":
            requested: list[str] = []
            if execution.query_understanding.tool_name:
                requested.append(execution.query_understanding.tool_name)
            elif getattr(execution.query_understanding, "candidate_tools", None):
                requested.extend(list(execution.query_understanding.candidate_tools))
            elif skill_scope:
                requested.extend(skill_scope)
            return set(self.permission_service.allowed_tool_names(allowed_tools=requested))

        return set(self.permission_service.allowed_tool_names(allowed_tools=skill_scope or None))

    async def _stream_direct_tool_execution(
        self,
        session_id: str,
        execution: QueryExecutionPlan,
        *,
        trace=None,
    ):
        tool_name = str(execution.query_understanding.tool_name or "").strip()
        tool_input = dict(execution.tool_input or execution.query_understanding.tool_input or {"query": execution.message})
        contract_decision = self._evaluate_tool_contract(
            tool_name=tool_name,
            tool_input=tool_input,
            execution=execution,
        )
        if trace is not None:
            trace.annotate(
                {
                    "app.tool_contract_mode": contract_decision.mode,
                    "app.tool_contract_action": contract_decision.action,
                    "app.tool_contract_reason": contract_decision.reason,
                }
            )
        if contract_decision.should_block:
            yield {
                "type": "done",
                "content": self._tool_contract_failure_message(
                    tool_name=tool_name,
                    contract_decision=contract_decision,
                ),
                "answer_channel": "fallback_answer",
                "answer_source": "tool_contract_gate",
                "answer_fallback_reason": "tool_contract_blocked",
                "answer_leak_flags": [],
                "contract": contract_decision.to_dict(),
            }
            return
        decision = self.permission_service.can_invoke_tool(
            tool_name,
            allowed_tools=self._skill_allowed_tool_scope(execution.active_skill),
            direct_route=True,
            tool_input=tool_input,
        )
        if not decision.allowed:
            yield {
                "type": "done",
                "content": f"无法调用工具 {tool_name}：{decision.reason}",
                "answer_channel": "fallback_answer",
                "answer_source": "permission_guard",
                "answer_fallback_reason": "tool_permission_denied",
                "answer_leak_flags": [],
            }
            return

        tool = self.tool_runtime.get_instance(tool_name)
        if tool is None:
            yield {
                "type": "done",
                "content": f"工具 {tool_name} 当前不可用。",
                "answer_channel": "fallback_answer",
                "answer_source": "tool_runtime",
                "answer_fallback_reason": "tool_unavailable",
                "answer_leak_flags": [],
            }
            return

        if trace is not None:
            trace.annotate(
                {
                    "app.route": "tool",
                    "app.tool_name": tool_name,
                    "app.structured_binding_path": (
                        execution.structured_binding.dataset_path
                        if getattr(execution, "structured_binding", None) is not None
                        else ""
                    ),
                    "app.structured_binding_source": (
                        execution.structured_binding.source
                        if getattr(execution, "structured_binding", None) is not None
                        else ""
                    ),
                }
            )

        yield {
            "type": "tool_start",
            "tool": tool_name,
            "input": tool_input,
            "contract": contract_decision.to_dict(),
            "structured_binding": (
                execution.structured_binding.to_dict()
                if getattr(execution, "structured_binding", None) is not None
                else None
            ),
        }

        active_constraints = self._extract_active_constraints(execution.message)
        raw_tool_output: Any = None
        rendered_tool_decision = None

        async def invoke_tool() -> Any:
            nonlocal raw_tool_output
            if trace is not None:
                with trace.stage(
                    "query.direct_tool",
                    run_type="tool",
                    inputs={"tool": tool_name, "input": tool_input},
                ):
                    raw_tool_output = await asyncio.to_thread(tool.invoke, tool_input)
                    return raw_tool_output
            raw_tool_output = await asyncio.to_thread(tool.invoke, tool_input)
            return raw_tool_output

        def _render_content(output: Any) -> str:
            nonlocal rendered_tool_decision
            rendered_tool_decision = self._build_direct_tool_output_decision(
                output,
                tool_name=tool_name,
                query=execution.message,
                route=str(execution.query_understanding.route or "tool"),
            )
            return rendered_tool_decision.canonical_answer.strip()

        task = await self.task_coordinator.run_tool_task(
            session_id,
            tool_name,
            invoke_tool,
            query=execution.message,
            tool_input=tool_input,
            structured_binding=getattr(execution, "structured_binding", None),
            task_kind=str(getattr(execution.query_understanding, "task_kind", "") or ""),
            constraints=TaskConstraints(
                top_n=active_constraints.get("top_n"),
                group_by=str(active_constraints.get("group_by", "") or ""),
                page=active_constraints.get("page"),
                response_style=str(active_constraints.get("response_style", "") or ""),
                pdf_mode=str(active_constraints.get("pdf_mode", "") or ""),
                pdf_section=str(active_constraints.get("pdf_section", "") or ""),
            ),
            render_content=_render_content,
        )
        self._enrich_direct_tool_task(
            task,
            raw_output=raw_tool_output,
            tool_name=tool_name,
        )
        tool_decision = rendered_tool_decision or self._build_direct_tool_output_decision(
            raw_tool_output,
            tool_name=tool_name,
            query=execution.message,
            route=str(execution.query_understanding.route or "tool"),
        )
        self._apply_pdf_persistence_gate(
            task=task,
            raw_output=raw_tool_output,
            tool_name=tool_name,
            tool_decision=tool_decision,
        )
        visible_content = await self._finalize_pdf_direct_tool_answer(
            session_id=session_id,
            execution=execution,
            task=task,
            raw_output=raw_tool_output,
            tool_name=tool_name,
            tool_decision=tool_decision,
        )
        tool_content = task.result
        pdf_model_finalized = bool(task.metadata.get("pdf_model_finalized")) if task is not None else False
        binding_payload = (
            execution.structured_binding.to_dict()
            if getattr(execution, "structured_binding", None) is not None
            else None
        )
        task_summary_ref = self._task_summary_ref_from_task(task)
        yield {"type": "tool_end", "tool": tool_name, "output": tool_content, "structured_binding": binding_payload}
        if tool_name == "pdf_analysis" and not (
            self._pdf_tool_decision_is_persistable(raw_tool_output, tool_decision) or pdf_model_finalized
        ):
            task_summary_ref = None
        yield {
            "type": "done",
            "content": visible_content,
            "task_id": task.task_id,
            "summary": task.summary.to_dict() if task.summary is not None else None,
            "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
            "result_ref": task.result_ref.to_dict() if task.result_ref is not None else None,
            "main_context": self._build_direct_tool_main_context(execution.message, task=task).to_dict(),
            "structured_binding": binding_payload,
            "answer_channel": "answer_candidate" if pdf_model_finalized else tool_decision.selected_channel,
            "answer_source": "pdf_model_finalization" if pdf_model_finalized else tool_decision.selected_source,
            "answer_fallback_reason": "" if pdf_model_finalized else tool_decision.fallback_reason,
            "answer_leak_flags": list(tool_decision.leak_flags),
            "contract": contract_decision.to_dict(),
            "task_summary_refs": (
                [task_summary_ref.to_dict()]
                if task_summary_ref is not None
                else []
            ),
        }

    def _evaluate_tool_contract(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        execution: QueryExecutionPlan,
    ) -> ToolContractDecision:
        effective_mode = self._effective_tool_contract_mode(tool_name)
        contract = None
        runtime_get_contract = getattr(self.tool_runtime, "get_contract", None)
        if callable(runtime_get_contract):
            contract = runtime_get_contract(tool_name)
        if contract is None:
            definition = get_tool_definition_map().get(tool_name)
            if definition is not None:
                contract = definition.contract
        if contract is None:
            return ToolContractDecision(
                tool_name=tool_name,
                mode=effective_mode,
                action="deny",
                reason="missing_tool_contract",
            )

        binding_context = {
            "active_dataset": (
                execution.structured_binding.dataset_path
                if getattr(execution, "structured_binding", None) is not None
                else ""
            ),
            "active_pdf": str(tool_input.get("path", "") or "").strip(),
        }
        local_gate = ToolContractGate(mode=effective_mode)
        return local_gate.evaluate(
            tool_name=tool_name,
            contract=contract,
            tool_input=tool_input,
            skill_allowed_tools=self._skill_allowed_tool_scope(execution.active_skill),
            binding_context=binding_context,
        )

    def _effective_tool_contract_mode(self, tool_name: str) -> str:
        base_mode = str(self.tool_contract_gate.mode or "shadow").strip().lower() or "shadow"
        if base_mode == "off":
            return "off"
        if tool_name in {
            "pdf_analysis",
            "structured_data_analysis",
            "analyze_multimodal_file",
            "index_multimodal_file",
        }:
            return "enforce"
        return base_mode

    def _tool_contract_failure_message(
        self,
        *,
        tool_name: str,
        contract_decision: ToolContractDecision,
    ) -> str:
        if contract_decision.reason == "missing_required_binding":
            if tool_name == "pdf_analysis":
                return "无法调用 PDF 工具：需要先明确 PDF 文件 path，或已有已确认的 PDF 绑定。"
            if tool_name == "structured_data_analysis":
                return "无法调用表格工具：需要先明确数据文件 path，或已有已确认的数据集绑定。"
            if contract_decision.missing_bindings:
                return f"无法调用工具 {tool_name}：缺少绑定 {', '.join(contract_decision.missing_bindings)}。"
        if contract_decision.reason == "missing_required_input":
            if contract_decision.missing_inputs:
                return f"无法调用工具 {tool_name}：缺少输入 {', '.join(contract_decision.missing_inputs)}。"
        return f"无法调用工具 {tool_name}：{contract_decision.reason}"

    def _normalize_direct_tool_output(
        self,
        output: Any,
        *,
        tool_name: str = "",
        query: str = "",
        route: str = "tool",
    ) -> str:
        decision = self._build_direct_tool_output_decision(
            output,
            tool_name=tool_name,
            query=query,
            route=route,
        )
        return decision.canonical_answer.strip()

    def _build_direct_tool_output_decision(
        self,
        output: Any,
        *,
        tool_name: str = "",
        query: str = "",
        route: str = "tool",
        force_allow_unlabeled: bool = False,
    ):
        normalized_text, allow_unlabeled_answer = self._prepare_direct_tool_output_candidate(output)
        candidate = classify_output_candidate(
            text=normalized_text,
            route=route,
            source=f"direct_tool.{tool_name or 'tool'}",
            tool_name=tool_name,
            allow_unlabeled_answer=allow_unlabeled_answer or force_allow_unlabeled,
            has_tool_receipt=True,
        )
        return build_output_decision(
            candidates=[candidate] if candidate is not None else [],
            route=route,
            execution_posture="direct_tool",
            user_message=query,
            tool_name=tool_name,
            retrieval_results=None,
            has_tool_receipt=True,
        )

    def _prepare_direct_tool_output_candidate(self, output: Any) -> tuple[str, bool]:
        if isinstance(output, dict):
            for key in ("answer", "summary", "result", "output", "text", "content"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return sanitize_visible_assistant_content(value).strip(), True
        return self._stringify_tool_output(output), False

    def _stringify_tool_output(self, output: Any) -> str:
        if isinstance(output, str):
            return sanitize_visible_assistant_content(output).strip()
        if isinstance(output, dict):
            for key in ("answer", "content", "summary", "result", "output", "text"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return sanitize_visible_assistant_content(value).strip()
            return json.dumps(output, ensure_ascii=False, indent=2)
        if isinstance(output, (list, tuple)):
            if all(isinstance(item, str) for item in output):
                parts = [
                    sanitize_visible_assistant_content(str(item)).strip()
                    for item in output
                ]
                return "\n".join(item for item in parts if item).strip()
            return json.dumps(list(output), ensure_ascii=False, indent=2)
        normalized = stringify_content(output)
        return sanitize_visible_assistant_content(normalized).strip() if isinstance(normalized, str) else str(output)

    def _enrich_direct_tool_task(
        self,
        task,
        *,
        raw_output: Any,
        tool_name: str,
    ) -> None:
        if tool_name != "pdf_analysis" or task is None:
            return
        canonical = PDFCanonicalResult.from_tool_output(self._stringify_tool_output(raw_output))
        if canonical is None:
            return
        context_ref = getattr(task, "context_ref", None)
        summary = getattr(task, "summary", None)
        if context_ref is None or summary is None:
            return
        metadata = dict(canonical.metadata or {})
        normalized_mode = self._normalize_pdf_scope(str(canonical.effective_mode or ""))
        if canonical.ok:
            context_ref.constraints.pdf_mode = normalized_mode
        context_ref.constraints.pdf_section = str(metadata.get("target_section", "") or "")
        target_page = metadata.get("target_page")
        if isinstance(target_page, int) and target_page > 0:
            context_ref.constraints.page = target_page
        context_ref.constraints.pdf_focus_pages = [int(page) for page in list(canonical.pages or []) if int(page) > 0][:5]
        total_pages = metadata.get("document_total_pages", metadata.get("total_pages"))
        readable_pages = metadata.get("readable_pages")
        usable_pages = metadata.get("usable_pages")
        if isinstance(total_pages, int) and total_pages > 0:
            context_ref.constraints.total_pages = total_pages
        if isinstance(readable_pages, int) and readable_pages >= 0:
            context_ref.constraints.readable_pages = readable_pages
            task.metadata["pdf_readable_pages"] = readable_pages
        if isinstance(usable_pages, int) and usable_pages >= 0:
            context_ref.constraints.usable_pages = usable_pages
        if canonical.ok:
            context_ref.task_kind = self._pdf_task_kind_from_mode(canonical.effective_mode)
        task.metadata["pdf_canonical_result"] = canonical.to_payload()
        if canonical.ok:
            summary.key_points = self._merge_summary_key_points(
                list(summary.key_points or []),
                pdf_path=str(context_ref.bindings.active_pdf or ""),
                page=context_ref.constraints.page,
                pdf_mode=context_ref.constraints.pdf_mode,
                pdf_section=context_ref.constraints.pdf_section,
                pdf_pages=context_ref.constraints.pdf_focus_pages,
                readable_pages=context_ref.constraints.readable_pages,
                usable_pages=context_ref.constraints.usable_pages,
            )
            context_ref.summary = str(summary.response or "")

    def _apply_pdf_persistence_gate(
        self,
        *,
        task,
        raw_output: Any,
        tool_name: str,
        tool_decision,
    ) -> None:
        if tool_name != "pdf_analysis" or task is None:
            return
        canonical = PDFCanonicalResult.from_tool_output(self._stringify_tool_output(raw_output))
        if canonical is None or self._pdf_tool_decision_is_persistable(raw_output, tool_decision):
            return
        summary = getattr(task, "summary", None)
        context_ref = getattr(task, "context_ref", None)
        if summary is not None:
            summary.response = ""
            summary.key_points = []
        if context_ref is not None:
            context_ref.summary = ""
        task.metadata["skip_session_memory_projection"] = True
        task.metadata["pdf_persistable"] = False

    async def _finalize_pdf_direct_tool_answer(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        task,
        raw_output: Any,
        tool_name: str,
        tool_decision,
    ) -> str:
        fallback = tool_decision.canonical_answer.strip() or f"{tool_name} 已执行，但未返回可展示结果。"
        if tool_name != "pdf_analysis" or task is None:
            return fallback
        if not self._pdf_tool_result_can_use_model_finalization(raw_output, tool_decision):
            return fallback
        canonical = PDFCanonicalResult.from_tool_output(self._stringify_tool_output(raw_output))
        if canonical is None:
            return fallback
        finalized = await self._rewrite_pdf_answer_with_model(
            user_query=execution.message,
            canonical=canonical,
        )
        if not finalized or finalized == fallback:
            return fallback
        self.task_coordinator.refresh_completed_tool_task(
            session_id=session_id,
            task=task,
            content=finalized,
            event_name="tool_task_llm_finalize",
        )
        task.metadata["pdf_model_finalized"] = True
        task.metadata["pdf_model_finalized_answer"] = finalized
        return finalized

    async def _rewrite_pdf_answer_with_model(
        self,
        *,
        user_query: str,
        canonical: PDFCanonicalResult,
    ) -> str:
        messages = self._build_pdf_answer_finalization_messages(
            user_query=user_query,
            canonical=canonical,
        )
        try:
            response = await self.model_runtime.invoke_messages(messages)
        except ModelRuntimeError:
            return ""
        except Exception:
            logger.exception("PDF answer finalization failed")
            return ""
        content = sanitize_visible_assistant_content(
            stringify_content(getattr(response, "content", response))
        ).strip()
        if (
            not content
            or contains_internal_protocol(content)
            or self._looks_like_pdf_procedural_answer(content)
            or (canonical.summary.strip() and content == canonical.summary.strip())
        ):
            return ""
        return content

    async def _maybe_finalize_rag_output(
        self,
        *,
        execution: QueryExecutionPlan,
        retrieval_results: list[dict[str, Any]] | None,
        output_response,
    ):
        if str(execution.query_understanding.route or "") != "rag":
            return output_response
        if str(getattr(output_response, "finalization_policy", "none") or "none") != "route_required":
            return output_response
        fallback_reason = str(getattr(output_response, "fallback_reason", "") or "")
        preserve_no_receipt_fallback = fallback_reason in {"no_receipt_tool_claim", "no_receipt_query_promise"}
        evidence_pack = build_rag_evidence_pack(
            user_query=execution.message,
            retrieval_results=retrieval_results,
            max_items=3,
        )
        if not self._rag_evidence_pack_can_finalize(evidence_pack):
            return output_response if preserve_no_receipt_fallback else self._fallback_rag_output_response(output_response)
        finalized = await self._rewrite_rag_answer_with_model(evidence_pack=evidence_pack)
        if not finalized:
            return self._fallback_rag_output_response(output_response)
        return replace(
            output_response,
            canonical_answer=finalized,
            selected_channel="answer_candidate",
            selected_source="rag_answer_finalization",
            canonical_state="stable_answer",
            persist_policy="persist_canonical",
            finalization_policy="none",
            fallback_reason="",
        )

    async def _rewrite_rag_answer_with_model(
        self,
        *,
        evidence_pack: RAGEvidencePack,
    ) -> str:
        messages = build_rag_answer_finalization_messages(evidence_pack=evidence_pack)
        try:
            response = await self.model_runtime.invoke_messages(messages)
        except ModelRuntimeError:
            return ""
        except Exception:
            logger.exception("RAG answer finalization failed")
            return ""
        content = normalize_finalized_answer(stringify_content(getattr(response, "content", response)))
        if (
            not content
            or contains_internal_protocol(content)
            or self._looks_like_rag_procedural_answer(content)
            or answer_looks_like_snippet_dump(content, evidence_pack)
        ):
            return ""
        return content

    def _rag_evidence_pack_can_finalize(self, evidence_pack: RAGEvidencePack | None) -> bool:
        if evidence_pack is None:
            return False
        if len(list(evidence_pack.items or [])) < 2:
            return False
        return total_compact_chars(evidence_pack) >= 60

    def _fallback_rag_output_response(self, output_response):
        return replace(
            output_response,
            canonical_answer="已检索到相关资料，但当前模型尚未产出可直接展示的结论。",
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="route_required",
            fallback_reason="rag_missing_answer",
        )

    def _maybe_gate_memory_output(
        self,
        *,
        execution: QueryExecutionPlan,
        output_response,
    ):
        if str(execution.query_understanding.route or "") != "memory":
            return output_response
        if str(getattr(output_response, "selected_channel", "") or "") == "fallback_answer":
            return output_response
        if str(getattr(output_response, "canonical_state", "") or "") == "progress_only":
            return self._fallback_memory_output_response(output_response)
        if not self._memory_output_needs_gate(output_response):
            return output_response
        return self._fallback_memory_output_response(output_response)

    def _memory_output_needs_gate(self, output_response) -> bool:
        selected_source = str(getattr(output_response, "selected_source", "") or "")
        if not selected_source.startswith("segment."):
            return False
        answer = sanitize_visible_assistant_content(
            str(getattr(output_response, "canonical_answer", "") or "")
        ).strip()
        if not answer:
            return False
        if looks_like_progress_text(answer):
            return True
        leak_flags = {str(flag or "").strip() for flag in list(getattr(output_response, "leak_flags", []) or [])}
        if not leak_flags:
            return False
        compact = re.sub(r"\s+", "", answer)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in answer
            for token in (
                "检查",
                "查看",
                "读取",
                "分析",
                "确认",
                "整理",
                "梳理",
                "回顾",
                "回忆",
                "目录结构",
                "知识库",
            )
        )

    def _fallback_memory_output_response(self, output_response):
        return replace(
            output_response,
            canonical_answer="当前没有足够稳定的会话内容可直接回答这个问题。",
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="none",
            fallback_reason="memory_visible_pollution",
        )

    async def _maybe_finalize_pdf_output(
        self,
        *,
        execution: QueryExecutionPlan,
        output_response,
    ):
        canonical = self._extract_pdf_canonical_from_output_response(output_response)
        if canonical is None:
            return output_response
        if str(getattr(output_response, "finalization_policy", "none") or "none") != "route_required":
            return output_response
        if not self._pdf_canonical_can_finalize(canonical):
            return self._fallback_pdf_output_response(output_response, canonical)
        finalized = await self._rewrite_pdf_answer_with_model(
            user_query=execution.message,
            canonical=canonical,
        )
        if not finalized:
            return self._fallback_pdf_output_response(output_response, canonical)
        return replace(
            output_response,
            canonical_answer=finalized,
            selected_channel="answer_candidate",
            selected_source="pdf_answer_finalization",
            canonical_state="stable_answer",
            persist_policy="persist_canonical",
            finalization_policy="none",
            fallback_reason="",
        )

    def _extract_pdf_canonical_from_output_response(self, output_response) -> PDFCanonicalResult | None:
        for item in reversed(list(getattr(output_response, "tool_calls", []) or [])):
            if str(item.get("tool", "") or "") != "pdf_analysis":
                continue
            output = str(item.get("output", "") or "").strip()
            if not output:
                continue
            canonical = PDFCanonicalResult.from_tool_output(output)
            if canonical is not None:
                return canonical
        return None

    def _pdf_canonical_can_finalize(self, canonical: PDFCanonicalResult) -> bool:
        if canonical.ok and canonical.summary.strip():
            return True
        return self._pdf_canonical_has_finalizable_evidence(canonical)

    def _fallback_pdf_output_response(self, output_response, canonical: PDFCanonicalResult):
        pages = [int(page) for page in list(canonical.pages or []) if int(page) > 0][:3]
        if pages:
            selected = "、".join(f"P{page}" for page in pages)
            message = f"已读取与当前问题最相关的 PDF 页面：{selected}，但当前还没有形成稳定摘要。"
            reason = "pdf_canonical_missing_summary"
        else:
            message = "已读取这份 PDF，但当前工具尚未形成可直接展示的摘要。"
            reason = "pdf_missing_summary"
        return replace(
            output_response,
            canonical_answer=message,
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="route_required",
            fallback_reason=reason,
        )

    def _looks_like_rag_procedural_answer(self, answer: str) -> bool:
        normalized = sanitize_visible_assistant_content(str(answer or "")).strip()
        if not normalized:
            return False
        normalized = re.sub(r"^(?:岩[，,\s]*)+", "", normalized).strip()
        if not normalized:
            return False
        if looks_like_progress_text(normalized):
            return True
        compact = re.sub(r"\s+", "", normalized)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in normalized
            for token in (
                "检索",
                "搜索",
                "查看",
                "检查",
                "读取",
                "分析",
                "确认",
                "整理",
                "改写",
                "根据这些证据",
                "整理答案",
            )
        )

    def _looks_like_pdf_procedural_answer(self, answer: str) -> bool:
        normalized = sanitize_visible_assistant_content(str(answer or "")).strip()
        if not normalized:
            return False
        normalized = re.sub(r"^(?:岩[，,\s]*)+", "", normalized).strip()
        if not normalized:
            return False
        if looks_like_progress_text(normalized):
            return True
        compact = re.sub(r"\s+", "", normalized)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in normalized
            for token in (
                "PDF",
                "页面",
                "页",
                "文档",
                "章节",
                "读取",
                "查看",
                "分析",
                "整理",
                "提炼",
                "总结",
            )
        )

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

    def _build_pdf_answer_finalization_messages(
        self,
        *,
        user_query: str,
        canonical: PDFCanonicalResult,
    ) -> list[dict[str, str]]:
        source = str(canonical.source or "当前PDF").strip()
        page_marks = [f"P{int(page)}" for page in list(canonical.pages or []) if int(page) > 0][:6]
        evidence_lines: list[str] = []
        for item in list(canonical.evidence or [])[:4]:
            snippet = " ".join(str(item.snippet or "").split()).strip()
            if not snippet:
                continue
            evidence_lines.append(f"- P{int(item.page_number)}: {snippet[:220]}")
        evidence_block = "\n".join(evidence_lines) if evidence_lines else "- 无额外证据片段"
        page_block = "、".join(page_marks) if page_marks else "未标注"
        summary = canonical.summary.strip()
        degraded_reason = str(canonical.degraded_reason or "").strip()
        system_prompt = (
            "你负责把已经清洗过的 PDF 阅读结果改写成对用户可直接展示的最终回答。"
            "只能依据提供的摘要和证据回答，不要编造，不要输出内部协议、工具名、canonical、evidence 等词。"
            "不要大段摘抄原文；优先直接回应用户任务。"
            "如果用户要求总结、行动建议、解释或对比，请按该任务形态组织答案。"
            "如果提供的页面看起来主要是封面、题名页、目录、版权页或其他非正文，请直接说明这一点，不要硬编正文结论。"
        )
        user_prompt = (
            f"用户问题：{user_query.strip()}\n"
            f"PDF：{source}\n"
            f"相关页面：{page_block}\n"
            f"稳定摘要：{summary or '无'}\n"
            f"当前状态：{canonical.status}\n"
            f"降级原因：{degraded_reason or '无'}\n"
            f"证据片段：\n{evidence_block}\n\n"
            "请直接回答用户，不要解释你的处理过程。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _pdf_tool_result_can_use_model_finalization(self, raw_output: Any, tool_decision) -> bool:
        canonical = PDFCanonicalResult.from_tool_output(self._stringify_tool_output(raw_output))
        if canonical is None:
            return False
        if canonical.ok:
            return True
        return self._pdf_canonical_has_finalizable_evidence(canonical)

    def _pdf_canonical_has_finalizable_evidence(self, canonical: PDFCanonicalResult) -> bool:
        if str(canonical.effective_mode or "") == "page" and str(canonical.degraded_reason or "") == "target_page_has_no_stable_text":
            return False
        for item in list(canonical.evidence or [])[:4]:
            snippet = sanitize_visible_assistant_content(str(item.snippet or "")).strip()
            compact = re.sub(r"\s+", "", snippet)
            if len(compact) >= 8:
                return True
        return False

    def _pdf_tool_decision_is_persistable(self, raw_output: Any, tool_decision) -> bool:
        if tool_decision is None or str(getattr(tool_decision, "selected_channel", "") or "") == "fallback_answer":
            return False
        canonical = PDFCanonicalResult.from_tool_output(self._stringify_tool_output(raw_output))
        return canonical is not None and canonical.ok

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
        merged: list[str] = []
        seen: set[str] = set()

        def add(item: str) -> None:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            merged.append(normalized)

        for item in existing:
            add(str(item or ""))
        if page is not None:
            add(f"page={page}")
        if pdf_mode:
            add(f"pdf_mode={pdf_mode}")
        if pdf_section:
            add(f"pdf_section={pdf_section}")
        normalized_pages = [int(page_item) for page_item in list(pdf_pages or []) if int(page_item) > 0]
        if normalized_pages:
            add("pdf_pages=" + ",".join(str(page_item) for page_item in normalized_pages))
        if readable_pages is not None:
            add(f"readable_pages={readable_pages}")
        if usable_pages is not None:
            add(f"usable_pages={usable_pages}")
        if pdf_path:
            add(f"pdf={pdf_path}")
        return merged

    def _pdf_task_kind_from_mode(self, mode: str) -> str:
        normalized = self._normalize_pdf_scope(str(mode or ""))
        if normalized == "page":
            return "document_page"
        if normalized == "section":
            return "document_section"
        return "document_read"

    def _normalize_pdf_scope(self, mode: str) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized in {"page", "page-read", "page_read"}:
            return "page"
        if normalized in {"section", "section-read", "section_read"}:
            return "section"
        return "document"

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
        tool_name = str(tool_call.get("tool", "") or "").strip().lower()
        raw = f"{tool_call.get('input', '')}\n{tool_call.get('output', '')}".lower()
        return tool_name == "read_file" and "skills/" in raw and "/skill.md" in raw

    def _looks_like_skill_document(self, content: str) -> bool:
        normalized = content.strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        has_skill_frontmatter = (
            (normalized.startswith("---") or lowered.startswith("name:"))
            and "metadata:" in lowered
            and "description:" in lowered
        )
        has_skill_sections = "display_name:" in lowered and (
            "## execution steps" in lowered
            or "## output format" in lowered
            or "目标" in normalized
            or "执行步骤" in normalized
            or "输出格式" in normalized
            or "故障排查" in normalized
            or "查询策略" in normalized
        )
        return has_skill_frontmatter or has_skill_sections

    def _sanitize_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any] | None:
        if self._is_internal_skill_read_tool_call(tool_call):
            return None

        sanitized = {
            "tool": tool_call.get("tool", "tool"),
            "input": str(tool_call.get("input", "") or ""),
            "output": str(tool_call.get("output", "") or ""),
        }
        input_is_skill = self._looks_like_skill_document(sanitized["input"])
        output_is_skill = self._looks_like_skill_document(sanitized["output"])

        if (input_is_skill and not sanitized["output"].strip()) or (input_is_skill and output_is_skill):
            return None

        if input_is_skill:
            sanitized["input"] = HIDDEN_SKILL_NOTICE
        if output_is_skill:
            sanitized["output"] = HIDDEN_SKILL_NOTICE
        return sanitized

    def _finalize_segments(
        self,
        segments: list[dict[str, Any]],
        current_segment: dict[str, Any],
        *,
        fallback_content: str = "",
    ) -> list[dict[str, Any]]:
        finalized = list(segments)
        candidate = {
            "content": current_segment.get("content", ""),
            "tool_calls": list(current_segment.get("tool_calls", [])),
        }
        if not str(candidate["content"]).strip() and fallback_content:
            candidate["content"] = fallback_content
        if str(candidate["content"]).strip() or candidate["tool_calls"]:
            finalized.append(candidate)
        return finalized

    def _build_assistant_messages(
        self,
        segments: list[dict[str, Any]],
        *,
        canonical_content: str | None = None,
        answer_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if canonical_content is not None:
            filtered_tool_calls = [
                sanitized
                for segment in segments
                for tool_call in (segment.get("tool_calls") or [])
                for sanitized in [self._sanitize_tool_call(tool_call)]
                if sanitized is not None
            ]
            content = sanitize_visible_assistant_content(canonical_content)
            content = self._apply_assistant_persistence_gate(content, filtered_tool_calls)
            if self._looks_like_skill_document(content) and not filtered_tool_calls:
                return []
            if not content.strip() and not filtered_tool_calls:
                return []
            return [
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": filtered_tool_calls or None,
                    **dict(answer_metadata or {}),
                }
            ]

        persisted: list[dict[str, Any]] = []
        for segment in segments:
            filtered_tool_calls = [
                sanitized
                for tool_call in (segment.get("tool_calls") or [])
                for sanitized in [self._sanitize_tool_call(tool_call)]
                if sanitized is not None
            ]
            content = sanitize_visible_assistant_content(str(segment.get("content", "") or ""))
            content = self._apply_assistant_persistence_gate(content, filtered_tool_calls)
            if self._looks_like_skill_document(content) and not filtered_tool_calls:
                continue
            if not content.strip() and not filtered_tool_calls:
                continue
            persisted.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": filtered_tool_calls or None,
                    **dict(answer_metadata or {}),
                }
            )
        return persisted

    def _assistant_metadata_from_done_event(self, event: dict[str, Any]) -> dict[str, Any]:
        answer_channel = str(event.get("answer_channel", "") or "").strip()
        answer_source = str(event.get("answer_source", "") or "").strip()
        fallback_reason = str(event.get("answer_fallback_reason", "") or "").strip()
        canonical_state = str(event.get("answer_canonical_state", "") or "").strip()
        persist_policy = str(event.get("answer_persist_policy", "") or "").strip()
        finalization_policy = str(event.get("answer_finalization_policy", "") or "").strip()

        if not canonical_state:
            if fallback_reason in {"no_receipt_query_promise", "no_receipt_tool_claim"}:
                canonical_state = "progress_only"
            elif answer_channel == "answer_candidate" or answer_source in {"memory_write_ack"}:
                canonical_state = "stable_answer"
            elif answer_channel == "fallback_answer":
                canonical_state = "missing_answer"

        if not persist_policy:
            if canonical_state in {"stable_answer", "tool_summary"}:
                persist_policy = "persist_canonical"
            elif canonical_state == "progress_only":
                persist_policy = "persist_debug_only"
            else:
                persist_policy = "do_not_persist"

        if not finalization_policy:
            if fallback_reason in {"rag_missing_answer", "pdf_missing_summary", "pdf_canonical_missing_summary"}:
                finalization_policy = "route_required"
            else:
                finalization_policy = "none"

        metadata: dict[str, Any] = {}
        if answer_channel:
            metadata["answer_channel"] = answer_channel
        if answer_source:
            metadata["answer_source"] = answer_source
        if canonical_state:
            metadata["answer_canonical_state"] = canonical_state
        if persist_policy:
            metadata["answer_persist_policy"] = persist_policy
        if finalization_policy:
            metadata["answer_finalization_policy"] = finalization_policy
        if fallback_reason:
            metadata["answer_fallback_reason"] = fallback_reason
        return metadata

    def _apply_assistant_persistence_gate(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> str:
        normalized = sanitize_visible_assistant_content(str(content or "")).strip()
        if not normalized:
            return ""
        if self._has_completed_tool_receipt(tool_calls):
            return normalized
        if looks_like_procedural_promise_text(normalized) or looks_like_tool_claim_without_receipt(normalized):
            return "当前还没有形成真实查询结果。"
        return normalized

    def _has_completed_tool_receipt(self, tool_calls: list[dict[str, Any]]) -> bool:
        return any(str(tool_call.get("output", "") or "").strip() for tool_call in list(tool_calls or []))
