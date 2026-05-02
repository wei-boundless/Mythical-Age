from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from execution import ModelResponseRuntimeExecutor, ToolRuntimeExecutor
from observability import build_debug_trace_event, start_turn_trace
from operations import AgentRegistry
from orchestration import (
    RuntimeContextManager,
    TaskRunLoop,
    build_base_unit_catalog,
    build_user_message_commit_decision,
)
from prompting import build_static_prompt, build_system_prompt
from query.models import QueryRequest
from runtime.agent_chain import AgentRuntimeChainAssembler
from runtime.model_runtime import ModelRuntimeError
from understanding import analyze_memory_intent

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
        task_coordinator=None,
    ) -> None:
        self.base_dir = base_dir
        self.settings_service = settings_service
        self.session_manager = session_manager
        self.memory_facade = memory_facade
        self.model_runtime = model_runtime
        self.tool_runtime = tool_runtime
        self.skill_registry = skill_registry
        self.unit_catalog = build_base_unit_catalog()
        self.tool_contract_gate = SimpleNamespace(
            mode=str(os.getenv("TOOL_CONTRACT_MODE", "shadow") or "shadow").strip().lower()
        )
        self.model_response_executor = ModelResponseRuntimeExecutor(
            model_runtime=model_runtime,
            tool_definition_resolver=self._get_tool_definition,
        )
        self.tool_runtime_executor = ToolRuntimeExecutor(tool_runtime=tool_runtime) if tool_runtime is not None else None
        self.agent_registry = AgentRegistry(base_dir)
        self.agent_runtime_chain = AgentRuntimeChainAssembler(
            memory_facade=memory_facade,
            skill_registry=skill_registry,
            tool_registry=getattr(tool_runtime, "registry", None),
        )
        self.runtime_context_manager = RuntimeContextManager(self.build_static_system_prompt_for_session)
        self.task_run_loop = TaskRunLoop(base_dir / "runtime-loop")

        self.legacy_query_chain_removed = True
        self.legacy_runtime_components = {
            "query_planner": "removed",
            "runtime_tool_bridge": "removed",
            "runtime_followup": "removed",
            "evidence_orchestrator": "removed",
            "worker_direct_execution": "removed",
        }

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
            active_skill=self._render_active_skill_prompt(active_skill),
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
        history = request.history or self.session_manager.load_session_for_agent(
            request.session_id,
            include_compressed_context=False,
        )
        task_id = f"turn:{request.session_id}:{len(history_record.get('messages', [])) + 1}"
        input_commit_gate = self._commit_user_message(
            session_id=request.session_id,
            content=request.message,
            task_id=task_id,
        )

        try:
            with start_turn_trace(
                session_id=request.session_id,
                user_message=request.message,
                history_length=len(history),
                metadata={"request_kind": "chat", "query_runtime_role": "adapter_only"},
                tags=["query-runtime", "agent-runtime-chain"],
            ) as trace:
                debug_event = build_debug_trace_event(trace)
                if debug_event is not None:
                    yield debug_event
                yield {
                    "type": "input_commit_gate",
                    "commit_gate": input_commit_gate.to_dict(),
                }

                memory_intent = analyze_memory_intent(request.message)
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
                    assistant_message_committer=lambda payload: self._apply_assistant_message_commit_async(
                        request.session_id,
                        payload,
                    ),
                    tool_runtime_executor=self.tool_runtime_executor,
                    tool_instances=self._all_tool_instances(),
                    agent_capability_profile=self.agent_registry.get_capability_profile("agent:main"),
                ):
                    yield event
        except Exception as exc:
            failure_text = self._user_visible_error(exc)
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
        search_policy: list[str] | None = None,
        trace=None,
    ):
        if trace is not None:
            trace.annotate(
                {
                    "app.query_runtime_role": "adapter_only",
                    "app.legacy_query_chain_removed": "true",
                    "app.runtime_channel": "single_agent_runtime",
                }
            )
        async for event in self.astream(
            QueryRequest(session_id=session_id, message=message, history=history)
        ):
            yield event

    def refresh_session_memory(self, session_id: str) -> str:
        history = self.session_manager.load_session(session_id)
        return self.memory_facade.refresh_session_memory(session_id, history)

    def inspect_session_memory_refresh(self, session_id: str):
        builder = getattr(self.memory_facade, "build_memory_compaction_result", None)
        if callable(builder):
            result = builder(session_id=session_id)
            return result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        return {"status": "blocked", "reason": "legacy_session_memory_refresh_removed"}

    def commit_durable_memory_extraction(self, session_id: str) -> int:
        history = self.session_manager.load_session(session_id)
        return self.memory_facade.commit_durable_memory_extraction(session_id, history)

    def schedule_durable_memory_extraction(self, session_id: str) -> int:
        history = self.session_manager.load_session(session_id)
        return self.memory_facade.submit_durable_memory_extraction(session_id, history)

    def inspect_durable_memory_extraction(self, session_id: str):
        history = self.session_manager.load_session_for_agent(session_id, include_compressed_context=False)
        builder = getattr(self.memory_facade, "build_durable_memory_write_candidates", None)
        if callable(builder):
            candidates = builder(session_id, history)
            return {
                "status": "candidate_only",
                "commit_allowed": False,
                "candidates": [
                    candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
                    for candidate in candidates
                ],
            }
        return {"status": "blocked", "reason": "legacy_durable_memory_extraction_removed"}

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
        session_memory_chars = 0
        durable_saved_count = 0
        try:
            if main_context or task_summary_refs or bundle_summary_refs:
                session_memory_chars = len(
                    self.memory_facade.refresh_session_memory_from_context_state(
                        session_id,
                        main_context,
                        task_summaries=task_summary_refs,
                        bundle_summaries=bundle_summary_refs,
                    )
                    or ""
                )
            else:
                session_memory_chars = len(self.memory_facade.refresh_session_memory(session_id, history) or "")
        except Exception:
            logger.warning("session memory refresh failed after assistant commit", exc_info=True)
        try:
            durable_saved_count = int(self.memory_facade.commit_durable_memory_extraction(session_id, history) or 0)
        except Exception:
            logger.warning("durable memory extraction failed after assistant commit", exc_info=True)
        return {
            "appended_messages": appended,
            "session_memory_chars": session_memory_chars,
            "durable_saved_count": durable_saved_count,
            "file_work_context_writeback": bool(main_context or task_summary_refs or bundle_summary_refs),
        }

    async def _apply_assistant_message_commit_async(self, session_id: str, payload: dict[str, Any]):
        appended = self.session_manager.append_messages(
            session_id,
            [
                {
                    "role": payload.get("role"),
                    "content": payload.get("content"),
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
        session_memory_chars = 0
        durable_saved_count = 0
        try:
            if main_context or task_summary_refs or bundle_summary_refs:
                session_memory_chars = len(
                    self.memory_facade.refresh_session_memory_from_context_state(
                        session_id,
                        main_context,
                        task_summaries=task_summary_refs,
                        bundle_summaries=bundle_summary_refs,
                    )
                    or ""
                )
            else:
                session_memory_chars = len(self.memory_facade.refresh_session_memory(session_id, history) or "")
        except Exception:
            logger.warning("session memory refresh failed after assistant commit", exc_info=True)
        try:
            async_committer = getattr(self.memory_facade, "acommit_durable_memory_extraction", None)
            if callable(async_committer):
                durable_saved_count = int(await async_committer(session_id, history) or 0)
            else:
                durable_saved_count = int(self.memory_facade.commit_durable_memory_extraction(session_id, history) or 0)
        except Exception:
            logger.warning("durable memory extraction failed after assistant commit", exc_info=True)
        return {
            "appended_messages": appended,
            "session_memory_chars": session_memory_chars,
            "durable_saved_count": durable_saved_count,
            "file_work_context_writeback": bool(main_context or task_summary_refs or bundle_summary_refs),
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

    def _render_active_skill_prompt(self, active_skill: Any | None) -> str | None:
        if active_skill is None:
            return None
        prompt_view = getattr(active_skill, "prompt_view", None)
        if prompt_view is not None:
            if hasattr(prompt_view, "render_block"):
                return str(prompt_view.render_block())
            if hasattr(prompt_view, "to_prompt"):
                return str(prompt_view.to_prompt())
        return str(active_skill)

    @staticmethod
    def _user_visible_error(exc: Exception) -> str:
        if isinstance(exc, ModelRuntimeError):
            return str(exc)
        return "请求处理失败，运行时已按 fail-closed 策略停止。"
