from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agents import MAIN_AGENT
from observability import build_debug_trace_event, start_turn_trace
from query.models import QueryContext, QueryPlan, QueryRequest
from query.prompt_builder import build_system_prompt
from query.planner import QueryPlanner
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content
from tasks.coordinator import TaskCoordinator

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
        if trace is not None:
            with trace.stage(
                "query.plan",
                inputs={"message": message, "history_length": len(history)},
                metadata={"session_id": session_id},
            ):
                plan = self.planner.build_plan(session_id=session_id, message=message, history=history)
        else:
            plan = self.planner.build_plan(session_id=session_id, message=message, history=history)
        if trace is not None:
            trace.annotate(
                {
                    "app.route": plan.query_understanding.route,
                    "app.tool_name": plan.query_understanding.tool_name or "",
                    "app.skill_name": plan.query_understanding.skill_name or "",
                    "app.subquery_count": len(plan.subqueries),
                }
            )
        if len(plan.subqueries) > 1:
            async for event in self.task_coordinator.run_query_tasks(
                session_id,
                plan.subqueries,
                lambda subquery: self._stream_single_execution(session_id, subquery, history, trace=trace),
            ):
                yield event
            return

        async for event in self._stream_single_execution(session_id, message, history, trace=trace):
            yield event

    async def _stream_single_execution(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        *,
        trace=None,
    ):
        if trace is not None:
            with trace.stage(
                "query.single_execution",
                inputs={"message": message},
                metadata={"session_id": session_id},
            ):
                plan = self.planner.build_plan(session_id=session_id, message=message, history=history)
        else:
            plan = self.planner.build_plan(session_id=session_id, message=message, history=history)
        context = QueryContext(
            session_id=session_id,
            history=list(history),
            augmented_history=list(history),
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

        if plan.query_understanding.route == "tool" and plan.query_understanding.tool_name:
            tool_input = self.planner.resolve_tool_input_from_history(plan, history)
            decision = self.permission_service.can_invoke_tool(
                plan.query_understanding.tool_name,
                allowed_tools=getattr(plan.active_skill, "allowed_tools", None),
                direct_route=True,
                tool_input=tool_input,
            )
            if not decision.allowed:
                yield {
                    "type": "done",
                    "content": f"无法调用工具 {plan.query_understanding.tool_name}：{decision.reason}",
                }
                return

            tool = self.tool_runtime.get_instance(plan.query_understanding.tool_name)
            if tool is not None:
                if trace is not None:
                    trace.annotate(
                        {
                            "app.route": "tool",
                            "app.tool_name": plan.query_understanding.tool_name,
                        }
                    )
                yield {"type": "tool_start", "tool": plan.query_understanding.tool_name, "input": tool_input}
                if trace is not None:
                    with trace.stage(
                        "query.direct_tool",
                        run_type="tool",
                        inputs={"tool": plan.query_understanding.tool_name, "input": tool_input},
                    ):
                        output = await asyncio.to_thread(tool.invoke, tool_input)
                else:
                    output = await asyncio.to_thread(tool.invoke, tool_input)
                tool_content = str(output)
                yield {"type": "tool_end", "tool": plan.query_understanding.tool_name, "output": tool_content}
                yield {"type": "done", "content": tool_content}
                return

        relevant_memory_task = asyncio.create_task(
            asyncio.to_thread(
                self.memory_facade.prefetch_relevant_notes,
                message,
                plan.memory_intent,
                limit=3,
            )
        )

        if (
            self.settings_service.get_rag_mode()
            and plan.query_understanding.route == "rag"
            and not plan.memory_intent.should_skip_rag
            and not plan.query_understanding.should_skip_rag
        ):
            if trace is not None:
                with trace.stage(
                    "query.retrieval",
                    inputs={"query": message},
                    metadata={"top_k": 5},
                ):
                    context.retrieval_results = self.retrieval_service.retrieve(message, top_k=5)
            else:
                context.retrieval_results = self.retrieval_service.retrieve(message, top_k=5)
            yield {"type": "retrieval", "query": message, "results": context.retrieval_results}

        try:
            context.relevant_memory_notes = await relevant_memory_task
        except Exception:
            context.relevant_memory_notes = None

        memory_trace = self.memory_facade.inspect_query_context(
            session_id,
            history=history,
            pending_user_message=message,
            memory_intent=plan.memory_intent,
            relevant_notes=context.relevant_memory_notes,
            context_compaction=context.context_compaction,
            retrieval_results=context.retrieval_results,
        )
        yield {"type": "memory_context", "memory": memory_trace}

        allowed_names = self._allowed_tool_names_for_plan(plan)
        tools = [
            tool
            for tool in self.tool_runtime.instances
            if getattr(tool, "name", "") in allowed_names
        ]
        system_prompt = self.build_system_prompt_for_session(
            session_id,
            history=history,
            pending_user_message=message,
            memory_intent=plan.memory_intent,
            relevant_memory_notes=context.relevant_memory_notes,
            active_skill=plan.active_skill,
            retrieval_results=context.retrieval_results,
        )
        agent = self.model_runtime.create_conversation_agent(
            system_prompt=system_prompt,
            tools=tools,
            agent_definition=MAIN_AGENT,
        )
        messages = self._build_agent_messages(context.augmented_history)
        messages.append({"role": "user", "content": message})

        final_content_parts: list[str] = []
        last_ai_message = ""
        pending_tools: dict[str, dict[str, str]] = {}
        tool_step_count = 0

        if trace is not None:
            trace.annotate(
                {
                    "app.route": plan.query_understanding.route,
                    "app.tool_count": len(tools),
                }
            )
        stream_context = (
            trace.stage(
                "query.model_stream",
                metadata={
                    "route": plan.query_understanding.route,
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
                        final_content_parts.append(text)
                        yield {"type": "token", "content": text}
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
                                last_ai_message = candidate

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
                            yield {
                                "type": "tool_end",
                                "tool": pending["tool"],
                                "output": output,
                            }
                            yield {"type": "new_response"}
        finally:
            if stream_context is not None:
                stream_context.__exit__(None, None, None)

        final_content = "".join(final_content_parts).strip() or last_ai_message.strip()
        if trace is not None:
            trace.annotate({"app.answer_chars": len(final_content)})
        yield {"type": "done", "content": final_content}

    async def _run_post_turn_tasks(self, session_id: str, *, title_seed: str | None = None) -> None:
        try:
            await asyncio.to_thread(self.refresh_session_memory, session_id)
        except Exception:
            logger.exception("Failed to refresh session memory for %s", session_id)

        try:
            await asyncio.to_thread(self.extract_durable_memories, session_id)
        except Exception:
            logger.exception("Failed to extract durable memories for %s", session_id)

        if title_seed:
            try:
                title = await self.generate_title(title_seed)
                self.session_manager.set_title(session_id, title)
            except Exception:
                logger.exception("Failed to generate title for session %s", session_id)

    def refresh_session_memory(self, session_id: str) -> str:
        messages = self.session_manager.load_session(session_id)
        summary = self.memory_facade.refresh_session_memory(session_id, messages)
        self.retrieval_service.rebuild_session_memory()
        return summary

    def extract_durable_memories(self, session_id: str) -> int:
        messages = self.session_manager.load_session(session_id)
        return self.memory_facade.submit_durable_memory_extraction(session_id, messages)

    async def generate_title(self, first_user_message: str) -> str:
        return await self.model_runtime.generate_title(first_user_message)

    async def summarize_history(self, messages: list[dict[str, Any]]) -> str:
        return await self.model_runtime.summarize_history(messages)

    def _build_agent_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for item in history:
            role = item.get("role")
            if role not in {"system", "user", "assistant"}:
                continue
            messages.append({"role": role, "content": str(item.get("content", ""))})
        return messages

    def _new_segment(self) -> dict[str, Any]:
        return {"content": "", "tool_calls": []}

    def _allowed_tool_names_for_plan(self, plan: QueryPlan) -> set[str]:
        route = str(plan.query_understanding.route or "").strip()
        skill_scope = list(getattr(plan.active_skill, "allowed_tools", None) or [])

        if route in {"memory", "rag"}:
            return set()

        if route == "tool":
            requested: list[str] = []
            if plan.query_understanding.tool_name:
                requested.append(plan.query_understanding.tool_name)
            elif getattr(plan.query_understanding, "candidate_tools", None):
                requested.extend(list(plan.query_understanding.candidate_tools))
            elif skill_scope:
                requested.extend(skill_scope)
            return set(self.permission_service.allowed_tool_names(allowed_tools=requested))

        return set(self.permission_service.allowed_tool_names(allowed_tools=skill_scope or None))

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
            content = str(segment.get("content", "") or "")
            if self._looks_like_skill_document(content) and not filtered_tool_calls:
                continue
            persisted.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": filtered_tool_calls or None,
                }
            )
        return persisted
