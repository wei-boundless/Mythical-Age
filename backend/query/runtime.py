from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from agents import MAIN_AGENT
from observability import build_debug_trace_event, start_turn_trace
from query.answer_assembler import AnswerAssembler
from query.binding_models import StructuredDatasetBinding
from query.context_models import MainContextState, TaskSummaryRef
from query.followup_resolver import QueryFollowupResolver
from query.models import QueryContext, QueryExecutionPlan, QueryPlan, QueryRequest
from query.output_boundary import AssistantOutputBoundary, contains_internal_protocol, sanitize_visible_assistant_content
from query.prompt_builder import build_system_prompt
from query.planner import QueryPlanner
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content
from tasks.context_models import TaskConstraints
from tasks.coordinator import TaskCoordinator
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
                        assistant_messages = self._build_assistant_messages(segments)
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
                    "app.followup_task_id": (
                        followup_resolution.binding_owner_task_id or followup_resolution.task_id
                    ),
                    "app.followup_task_ids": ",".join(followup_resolution.task_ids),
                }
            )
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
            }
            return
        if followup_resolution.mode == "binding_ref" and self._binding_owner_task(session_id, followup_resolution) is not None:
            async for event in self._stream_binding_followup(
                session_id,
                message,
                history,
                followup_resolution=followup_resolution,
                trace=trace,
            ):
                yield event
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
            output_response = output_boundary.build_response()
            final_content = output_response.visible_text.strip() or last_ai_message.strip()
            if trace is not None:
                trace.annotate(
                    {
                        "app.answer_chars": len(final_content),
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
                self.retrieval_service.rebuild_session_memory()
                return summary
            except Exception:
                logger.exception(
                    "Failed to refresh session memory from context-state projection for %s; falling back to committed messages",
                    session_id,
                )
        messages = self.session_manager.load_session(session_id)
        summary = self.memory_facade.refresh_session_memory(session_id, messages)
        self.retrieval_service.rebuild_session_memory()
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
        if task_refs:
            latest = task_refs[-1]
            constraints = dict(constraints)
            if latest.response_style:
                constraints.setdefault("response_style", latest.response_style)
        return MainContextState(
            active_goal=message.strip(),
            active_work_item="compound_query",
            followup_target_task_id=followup_target_task_id or None,
            followup_target_task_ids=[task_ref.task_id for task_ref in task_refs if task_ref.task_id],
            active_constraints=self._merge_constraints_from_results(constraints, results),
            latest_correction=self._extract_latest_correction(message),
            next_step="follow_up_or_refine_subtask_results",
        )

    def _build_followup_main_context(
        self,
        message: str,
        results: list[dict[str, object]],
        *,
        followup_resolution,
    ) -> MainContextState:
        constraints = self._extract_active_constraints(message)
        task_refs = self._task_summary_refs_from_results(results)
        if task_refs:
            latest = task_refs[-1]
            if latest.response_style:
                constraints = dict(constraints)
                constraints.setdefault("response_style", latest.response_style)
        target_task_ids = [task_id for task_id in followup_resolution.task_ids if task_id]
        target_task_id = followup_resolution.task_id or (target_task_ids[0] if target_task_ids else "")
        work_item = "followup_task_result_assembly"
        if followup_resolution.mode == "compound_subset":
            work_item = "followup_task_subset_assembly"
        elif followup_resolution.mode == "binding_ref":
            work_item = "followup_task_binding_execution"
        return MainContextState(
            active_goal=message.strip(),
            active_work_item=work_item,
            followup_target_task_id=target_task_id or None,
            followup_target_task_ids=target_task_ids,
            active_constraints=self._merge_constraints_from_results(constraints, results),
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
            if bindings.get("active_pdf") and not merged.get("active_pdf"):
                merged["active_pdf"] = str(bindings["active_pdf"])
            if bindings.get("active_dataset") and not merged.get("active_dataset"):
                merged["active_dataset"] = str(bindings["active_dataset"])
            if bindings.get("active_location") and not merged.get("active_location"):
                merged["active_location"] = str(bindings["active_location"])
            if bindings.get("source_kind") and not merged.get("source_kind"):
                merged["source_kind"] = str(bindings["source_kind"])
            summary_payload = item.get("summary")
            if isinstance(summary_payload, dict) and summary_payload.get("response_style") and not merged.get("response_style"):
                merged["response_style"] = str(summary_payload["response_style"])
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
            merged.setdefault("source_kind", "pdf")
        binding = getattr(execution, "structured_binding", None)
        if binding is None:
            return merged
        dataset_path = str(getattr(binding, "dataset_path", "") or "").strip()
        if dataset_path:
            merged["active_dataset"] = dataset_path
            merged.setdefault("source_kind", "dataset")
        return merged

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
        if "按仓库" in message:
            constraints["group_by"] = "仓库"
        elif "按地区" in message:
            constraints["group_by"] = "地区"
        if "不要重复" in message:
            constraints["dedupe"] = True
        if "补一句" in message:
            constraints["append_mode"] = "single_sentence_append"
        if "pdf" in lowered:
            constraints["source_kind"] = "pdf"
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
        task_ids = [task_id for task_id in followup_resolution.task_ids if task_id]
        if not task_ids and followup_resolution.task_id:
            task_ids = [followup_resolution.task_id]
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

    def _binding_owner_task(self, session_id: str, followup_resolution) -> Any | None:
        owner_task_id = str(
            getattr(followup_resolution, "binding_owner_task_id", "")
            or getattr(followup_resolution, "task_id", "")
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
            if followup_results:
                synthetic_resolution = followup_resolution.model_copy(
                    update={
                        "task_id": task_ids[-1] if task_ids else followup_resolution.task_id,
                        "task_ids": task_ids or list(followup_resolution.task_ids),
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
            event["followup_mode"] = followup_resolution.mode
            yield event

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
            }
            return

        tool = self.tool_runtime.get_instance(tool_name)
        if tool is None:
            yield {"type": "done", "content": f"工具 {tool_name} 当前不可用。"}
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
            "structured_binding": (
                execution.structured_binding.to_dict()
                if getattr(execution, "structured_binding", None) is not None
                else None
            ),
        }

        async def invoke_tool() -> Any:
            if trace is not None:
                with trace.stage(
                    "query.direct_tool",
                    run_type="tool",
                    inputs={"tool": tool_name, "input": tool_input},
                ):
                    return await asyncio.to_thread(tool.invoke, tool_input)
            return await asyncio.to_thread(tool.invoke, tool_input)

        active_constraints = self._extract_active_constraints(execution.message)
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
            ),
            render_content=self._normalize_direct_tool_output,
        )
        tool_content = task.result
        binding_payload = (
            execution.structured_binding.to_dict()
            if getattr(execution, "structured_binding", None) is not None
            else None
        )
        yield {"type": "tool_end", "tool": tool_name, "output": tool_content, "structured_binding": binding_payload}
        yield {
            "type": "done",
            "content": tool_content or f"{tool_name} 已执行，但未返回可展示结果。",
            "structured_binding": binding_payload,
            "task_summary_refs": (
                [
                    TaskSummaryRef(
                        task_id=task.task_id,
                        query=task.query,
                        summary=task.summary.response,
                        task_kind=task.context_ref.task_kind if task.context_ref is not None else "",
                        response_style=task.summary.response_style if task.summary is not None else "",
                        key_points=list(task.summary.key_points if task.summary is not None else []),
                    ).to_dict()
                ]
                if task.summary is not None
                else []
            ),
        }

    def _normalize_direct_tool_output(self, output: Any) -> str:
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

    def _build_assistant_messages(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
