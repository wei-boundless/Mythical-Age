from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from agents import MAIN_AGENT
from observability import build_debug_trace_event, start_turn_trace
from pdf_agent import PDFCanonicalResult
from query.answer_assembler import AnswerAssembler
from query.binding_models import StructuredDatasetBinding
from query.context_models import MainContextState, TaskSummaryRef
from query.followup_resolver import QueryFollowupResolver
from query.models import QueryContext, QueryExecutionPlan, QueryPlan, QueryRequest
from query.output_classifier import build_output_decision, classify_output_candidate
from query.output_boundary import AssistantOutputBoundary, contains_internal_protocol, sanitize_visible_assistant_content
from query.prompt_builder import build_system_prompt
from query.planner import QueryPlanner
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content
from tasks.context_models import TaskConstraints
from tasks.coordinator import TaskCoordinator
from tools.contracts import ToolContractDecision, ToolContractGate
from tools.definitions import get_tool_definition_map
from understanding import MemoryIntent, QueryUnderstanding

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
        self.followup_resolver = QueryFollowupResolver(task_coordinator)
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
        active_skill: Any | None = None,
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
            active_skill=self.skill_registry.format_active_skill_block(active_skill)
            if self.skill_registry is not None and active_skill is not None
            else None,
        )

    async def abuild_system_prompt_for_session(
        self,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        active_skill: Any | None = None,
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
            active_skill=self.skill_registry.format_active_skill_block(active_skill)
            if self.skill_registry is not None and active_skill is not None
            else None,
        )

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
        trace=None,
    ):
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
                plan = self.planner.build_plan(session_id=session_id, message=message, history=history)
        else:
            plan = self.planner.build_plan(session_id=session_id, message=message, history=history)
        executions = plan.iter_executions()
        if trace is not None:
            trace.annotate(
                {
                    "app.route": plan.query_understanding.route,
                    "app.tool_name": plan.query_understanding.tool_name or "",
                    "app.skill_name": plan.query_understanding.skill_name or "",
                    "app.subquery_count": len(executions),
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
        if len(executions) > 1:
            subtask_results: list[dict[str, object]] = []
            async for event in self.task_coordinator.run_query_tasks(
                session_id,
                executions,
                lambda execution: self._stream_planned_execution(session_id, execution, trace=trace),
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

    async def _stream_single_execution(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        *,
        trace=None,
    ):
        plan = self.planner.build_plan(session_id=session_id, message=message, history=history)
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

            allowed_names = self._allowed_tool_names_for_execution(execution)
            tools = [
                tool
                for tool in self.tool_runtime.instances
                if getattr(tool, "name", "") in allowed_names
            ]
            system_prompt = await self.abuild_system_prompt_for_session(
                session_id,
                history=execution.history,
                pending_user_message=execution.message,
                memory_intent=execution.memory_intent,
                relevant_memory_notes=context.relevant_memory_notes,
                active_skill=execution.active_skill,
                retrieval_results=context.retrieval_results,
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
                        "app.tool_count": len(tools),
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
                user_message=execution.message,
                tool_name=str(execution.query_understanding.tool_name or ""),
                retrieval_results=context.retrieval_results,
            )
            final_content = output_response.canonical_answer.strip()
            if trace is not None:
                trace.annotate(
                    {
                        "app.answer_chars": len(final_content),
                        "app.answer_channel": output_response.selected_channel,
                        "app.answer_source": output_response.selected_source,
                        "app.answer_fallback_reason": output_response.fallback_reason,
                        "app.output_leak_flags": ",".join(output_response.leak_flags),
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
        messages = self.session_manager.load_session(session_id)
        summary = self.memory_facade.refresh_session_memory(session_id, messages)
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
        messages = self.session_manager.load_session(session_id)
        return self.memory_facade.commit_durable_memory_extraction(session_id, messages)

    def schedule_durable_memory_extraction(self, session_id: str) -> int:
        projection = self._session_memory_projection.pop(session_id, None)
        if projection is not None:
            return self.memory_facade.submit_durable_memory_extraction_from_context_state(
                session_id,
                projection.get("main_context"),
                task_summaries=list(projection.get("task_summary_refs", []) or []),
                corrections=list(projection.get("corrections", []) or []),
            )
        messages = self.session_manager.load_session(session_id)
        return self.memory_facade.submit_durable_memory_extraction(session_id, messages)

    async def generate_title(self, first_user_message: str) -> str:
        return await self.model_runtime.generate_title(first_user_message)

    async def summarize_history(self, messages: list[dict[str, Any]]) -> str:
        return await self.model_runtime.summarize_history(messages)

    def _build_agent_messages(self, context: QueryContext) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        working_block = context.main_context.to_prompt_block().strip()
        if working_block:
            messages.append({"role": "system", "content": working_block})
        for item in context.augmented_history:
            role = item.get("role")
            if role not in {"system", "user", "assistant"}:
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
            active_work_item="compound_query",
            active_binding_identity=self._binding_identity_from_constraints(
                self._merge_constraints_from_results(constraints, results)
            ),
            followup_target_task_id=followup_target_task_id or None,
            followup_target_task_ids=[task_ref.task_id for task_ref in task_refs if task_ref.task_id],
            active_constraints=self._merge_constraints_from_results(constraints, results),
            latest_correction=self._extract_latest_correction(message),
            next_step="follow_up_or_refine_subtask_results",
        )

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
        if followup_resolution.mode == "compound_subset":
            work_item = "followup_task_subset_assembly"
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
        if followup_resolution.mode not in {"task_ref", "compound_subset"}:
            return False
        return bool(message.strip())

    def _followup_results_from_resolution(
        self,
        session_id: str,
        followup_resolution,
    ) -> list[dict[str, object]]:
        if followup_resolution.mode not in {"task_ref", "compound_subset"}:
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
                    "index": int(task.metadata.get("subtask_index", 0) or len(records) + 1),
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
        skill_scope = list(getattr(execution.active_skill, "allowed_tools", None) or [])

        if route in {"memory", "rag"}:
            return set()

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
                "content": f"无法调用工具 {tool_name}：{contract_decision.reason}",
                "answer_channel": "fallback_answer",
                "answer_source": "tool_contract_gate",
                "answer_fallback_reason": "tool_contract_blocked",
                "answer_leak_flags": [],
                "contract": contract_decision.to_dict(),
            }
            return
        decision = self.permission_service.can_invoke_tool(
            tool_name,
            allowed_tools=getattr(execution.active_skill, "allowed_tools", None),
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
                mode=self.tool_contract_gate.mode,
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
        return self.tool_contract_gate.evaluate(
            tool_name=tool_name,
            contract=contract,
            tool_input=tool_input,
            skill_allowed_tools=getattr(execution.active_skill, "allowed_tools", None),
            binding_context=binding_context,
        )

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
        )
        return build_output_decision(
            candidates=[candidate] if candidate is not None else [],
            route=route,
            user_message=query,
            tool_name=tool_name,
            retrieval_results=None,
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
            or (canonical.summary.strip() and content == canonical.summary.strip())
        ):
            return ""
        return content

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
            if self._looks_like_skill_document(content) and not filtered_tool_calls:
                return []
            if not content.strip() and not filtered_tool_calls:
                return []
            return [
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": filtered_tool_calls or None,
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
            if self._looks_like_skill_document(content) and not filtered_tool_calls:
                continue
            if not content.strip() and not filtered_tool_calls:
                continue
            persisted.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": filtered_tool_calls or None,
                }
            )
        return persisted
