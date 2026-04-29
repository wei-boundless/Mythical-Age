from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
from pathlib import PurePosixPath
from typing import Any

from agents import MAIN_AGENT
from observability import build_debug_trace_event, start_turn_trace
from operations import OperationGate, ResourceDecision, ResourcePolicy, build_default_operation_registry
from orchestration import (
    ControlKernel,
    RuntimeDirective,
    TaskContract,
    build_agent_runtime_chain_preview,
    build_blocked_runtime_commit_gate,
    build_base_unit_catalog,
    build_user_message_commit_decision,
)
from query.answer_assembler import AnswerAssembler
from query.context_models import MainContextState, TaskSummaryRef
from query.evidence_orchestrator import EvidenceOrchestrator
from query.evidence_graph import EvidenceArtifactGraph
from query.evidence_store import BindingCandidateStore, EvidenceGraphStore
from query.followup_models import FollowupResolution
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
from query.prompt_builder import build_system_prompt, build_system_prompt_with_manifest
from query.prompt_manifest import PromptManifest, compact_prompt_manifest
from query.planner import QueryPlanner
from query.worker_models import WorkerExecutionPlan, WorkerRequest
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content
from memory_system import MemoryWritebackPreviewService
from skill_system import SkillDefinition
from tasks.contract_builder import build_task_runtime_contract_preview
from tasks.coordinator import TaskCoordinator
from tools.contracts import ToolContractDecision, ToolContractGate, ToolScope
from understanding import QueryUnderstanding, analyze_memory_intent

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
        self.control_kernel = ControlKernel()
        self.unit_catalog = build_base_unit_catalog()
        self.operation_registry = build_default_operation_registry()
        self.operation_gate = OperationGate(self.operation_registry)
        self.restore_context_gate = None
        self.execution_candidate_gate = None
        self.output_commit_gate = None
        self.memory_gate_preview = None
        self.answer_assembler = AnswerAssembler()
        self._output_policy = RuntimeOutputPolicy(
            model_runtime=model_runtime,
            stringify_tool_output=self._stringify_tool_output,
        )
        self._persistence = RuntimePersistenceAssembler(hidden_skill_notice=HIDDEN_SKILL_NOTICE)
        self._memory_writeback = MemoryWritebackPreviewService(
            memory_facade,
            session_history_loader=lambda session_id: self.session_manager.load_session_for_agent(
                session_id,
                include_compressed_context=False,
            ),
        )
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
        context_package = self._build_context_package_preview_for_session(
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
        context_package = self._build_context_package_preview_for_session(
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

    async def _abuild_system_prompt_for_execution(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        retrieval_results: list[dict[str, Any]] | None = None,
        relevant_memory_notes: list[Any] | None = None,
    ) -> str:
        context_package = self._build_context_package_preview_for_session(
            session_id=session_id,
            pending_user_message=execution.message,
            memory_intent=execution.memory_intent,
            relevant_memory_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
        )
        if self._is_session_summary_execution(execution):
            context_package = self._filter_runtime_sections_from_context_package(context_package)

        return build_system_prompt(
            self.base_dir,
            self.settings_service.get_rag_mode(),
            persistent_memory=None,
            session_memory=None,
            context_package=context_package,
            active_skill=self._render_execution_skill_prompt(execution),
        )

    async def _abuild_system_prompt_with_manifest_for_execution(
        self,
        *,
        session_id: str,
        execution: QueryExecutionPlan,
        retrieval_results: list[dict[str, Any]] | None = None,
        relevant_memory_notes: list[Any] | None = None,
    ) -> tuple[str, PromptManifest]:
        context_package = self._build_context_package_preview_for_session(
            session_id=session_id,
            pending_user_message=execution.message,
            memory_intent=execution.memory_intent,
            relevant_memory_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
        )
        if self._is_session_summary_execution(execution):
            context_package = self._filter_runtime_sections_from_context_package(context_package)

        return build_system_prompt_with_manifest(
            self.base_dir,
            self.settings_service.get_rag_mode(),
            persistent_memory=None,
            session_memory=None,
            context_package=context_package,
            active_skill=self._render_execution_skill_prompt(execution),
            session_id=session_id,
            turn_id=str(getattr(execution, "execution_id", "") or getattr(execution, "message", "") or "")[:64],
        )

    def _build_context_package_preview_for_session(
        self,
        *,
        session_id: str,
        pending_user_message: str | None,
        memory_intent: Any | None,
        relevant_memory_notes: list[Any] | None,
        retrieval_results: list[dict[str, Any]] | None,
    ):
        if not session_id:
            return None
        preview_builder = getattr(self.memory_facade, "build_memory_context_package_preview", None)
        if callable(preview_builder):
            result = preview_builder(
                session_id=session_id,
                query=pending_user_message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
                retrieval_results=retrieval_results,
            )
            return getattr(result, "package", result)
        return None

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

    def _execution_branch_fields(self, execution: QueryExecutionPlan) -> dict[str, Any]:
        execution_id = str(
            getattr(execution, "subtask_id", "")
            or getattr(execution, "bundle_item_id", "")
            or "main"
        ).strip()
        fields: dict[str, Any] = {
            "execution_id": execution_id,
            "execution_kind": str(getattr(execution, "execution_kind", "") or "agent"),
        }
        bundle_id = str(getattr(execution, "bundle_id", "") or "").strip()
        bundle_item_id = str(getattr(execution, "bundle_item_id", "") or "").strip()
        bundle_item_index = int(getattr(execution, "bundle_item_index", 0) or 0)
        if bundle_id or bundle_item_id:
            fields["bundle_item"] = {
                "bundle_id": bundle_id,
                "bundle_item_id": bundle_item_id,
                "bundle_item_index": bundle_item_index,
                "bundle_origin": str(getattr(execution, "bundle_origin", "") or ""),
            }
        subtask_id = str(getattr(execution, "subtask_id", "") or "").strip()
        if subtask_id:
            fields["subtask_plan"] = {
                "subtask_plan_id": subtask_id,
                "subtask_goal": str(getattr(execution, "subtask_goal", "") or ""),
                "subtask_title": str(getattr(execution, "subtask_title", "") or ""),
                "subtask_origin": str(getattr(execution, "subtask_origin", "") or ""),
            }
        if bundle_item_index > 0:
            fields["subtask_index"] = bundle_item_index
        worker_plan = getattr(execution, "worker_plan", None)
        worker_route = str(getattr(worker_plan, "worker_route", "") or "").strip()
        if worker_route:
            fields["worker_route"] = worker_route
        tool_name = str(getattr(getattr(execution, "query_understanding", None), "tool_name", "") or "").strip()
        if tool_name:
            fields["tool"] = tool_name
            fields["tool_name"] = tool_name
        return fields

    def _attach_execution_branch_fields(self, event: dict[str, Any], execution: QueryExecutionPlan) -> dict[str, Any]:
        enriched = dict(event)
        for key, value in self._execution_branch_fields(execution).items():
            if key not in enriched or enriched.get(key) in (None, "", {}, []):
                enriched[key] = value
        return enriched

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

        input_commit_gate = self._commit_user_message(
            session_id=request.session_id,
            content=request.message,
            task_id=f"turn:{request.session_id}:{len(history_record.get('messages', [])) + 1}",
        )

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
                yield {
                    "type": "input_commit_gate",
                    "commit_gate": input_commit_gate.to_dict(),
                }

                chain_preview = self._build_live_agent_runtime_chain_preview(
                    session_id=request.session_id,
                    task_id=f"turn:{request.session_id}:{len(history_record.get('messages', [])) + 1}",
                    message=request.message,
                    source="query_runtime.astream",
                )
                for event in self._agent_runtime_chain_preview_events(
                    chain_preview,
                    fail_closed_message="旧编排连线已清空；新的 ControlKernel/ExecutionGraph 接线完成前，本轮按 fail-closed 策略停止执行。",
                    include_fail_closed=False,
                ):
                    yield event
                async for event in self._stream_model_response_directive(
                    request=request,
                    chain_preview=chain_preview,
                    history=history,
                ):
                    yield event
                return
        except Exception as exc:
            failure_text = self._user_visible_error(exc)
            error_payload = {"type": "error", "error": failure_text}
            if isinstance(exc, ModelRuntimeError):
                error_payload["code"] = exc.code
            yield error_payload

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
        chain_preview = self._build_live_agent_runtime_chain_preview(
            session_id=session_id,
            task_id=f"turn:{session_id}:execution_events",
            message=message,
            source="query_runtime.execution_events",
        )
        if trace is not None:
            trace.annotate(
                {
                    "app.orchestration_state": "agent_runtime_chain_preview",
                    "app.fail_closed": "true",
                    "app.resource_policy_ref": str(
                        chain_preview.get("task_operation_preview", {}).get("resource_policy", {}).get("policy_id", "")
                    ),
                }
            )
        for event in self._agent_runtime_chain_preview_events(
            chain_preview,
            fail_closed_message="旧编排执行链已清空；新的 ExecutionGraph/RuntimeDirective 接线完成前，本轮停止执行。",
        ):
            yield event

    def _build_live_agent_runtime_chain_preview(
        self,
        *,
        session_id: str,
        task_id: str,
        message: str,
        source: str,
    ) -> dict[str, Any]:
        memory_intent = analyze_memory_intent(message)
        memory_payload: dict[str, Any] = {}
        context_payload: dict[str, Any] = {}
        memory_view_builder = getattr(self.memory_facade, "build_memory_runtime_view", None)
        if callable(memory_view_builder):
            memory_view = memory_view_builder(
                session_id=session_id,
                query=message,
                memory_intent=memory_intent,
            )
            memory_payload = memory_view.to_dict() if hasattr(memory_view, "to_dict") else dict(memory_view or {})
        context_builder = getattr(self.memory_facade, "build_memory_context_package_preview", None)
        if callable(context_builder):
            context_policy_result = context_builder(
                session_id=session_id,
                query=message,
                memory_intent=memory_intent,
            )
            context_payload = (
                context_policy_result.to_dict()
                if hasattr(context_policy_result, "to_dict")
                else dict(context_policy_result or {})
            )
        task_operation_preview = build_task_runtime_contract_preview(
            session_id=session_id,
            task_id=task_id,
            user_goal=message,
            source=source,
            memory_runtime_view=memory_payload,
            context_policy_preview=context_payload,
        )
        chain = build_agent_runtime_chain_preview(
            session_id=session_id,
            task_operation_preview=task_operation_preview,
            memory_runtime_view=memory_payload,
            context_policy_preview=context_payload,
        )
        return {
            "agent_runtime_chain_preview": chain.to_dict(),
            "memory_runtime_view": memory_payload,
            "context_policy_preview": context_payload,
            "task_operation_preview": task_operation_preview,
            "status": chain.status,
        }

    def _build_live_task_operation_preview(
        self,
        *,
        session_id: str,
        task_id: str,
        message: str,
        source: str,
    ) -> dict[str, Any]:
        return self._build_live_agent_runtime_chain_preview(
            session_id=session_id,
            task_id=task_id,
            message=message,
            source=source,
        )["task_operation_preview"]

    def _agent_runtime_chain_preview_events(
        self,
        chain_preview: dict[str, Any],
        *,
        fail_closed_message: str,
        include_fail_closed: bool = True,
    ) -> list[dict[str, Any]]:
        task_operation_preview = dict(chain_preview.get("task_operation_preview") or {})
        events = [
            {
                "type": "agent_runtime_chain_preview",
                "preview": dict(chain_preview.get("agent_runtime_chain_preview") or {}),
                "memory_runtime_view": dict(chain_preview.get("memory_runtime_view") or {}),
                "context_policy_preview": dict(chain_preview.get("context_policy_preview") or {}),
            }
        ]
        events.extend(
            self._task_operation_preview_events(
                task_operation_preview,
                fail_closed_message=fail_closed_message,
            )
        )
        if not include_fail_closed:
            events = [
                event
                for event in events
                if not (
                    event.get("type") == "error"
                    and str(event.get("answer_source") or "") == "control_kernel"
                )
            ]
        return events

    async def _stream_model_response_directive(
        self,
        *,
        request: QueryRequest,
        chain_preview: dict[str, Any],
        history: list[dict[str, Any]],
    ):
        task_operation_preview = dict(chain_preview.get("task_operation_preview") or {})
        directive, resource_policy = self._build_model_response_runtime_directive(task_operation_preview)
        gate_result = self.operation_gate.check(
            "op.model_response",
            resource_policy=resource_policy,
            directive_ref=directive.directive_id,
        )
        yield {
            "type": "runtime_directive",
            "directive": directive.to_dict(),
            "resource_policy": resource_policy.to_dict(),
        }
        yield {
            "type": "operation_gate",
            "gate": gate_result.to_dict(),
        }
        if not gate_result.allowed:
            yield {
                "type": "error",
                "error": gate_result.reason,
                "content": "OperationGate 未放行模型回答，本轮停止执行。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "operation_gate",
            }
            return
        invoker = getattr(self.model_runtime, "invoke_messages", None)
        if not callable(invoker):
            yield {
                "type": "error",
                "error": "model_runtime_unavailable",
                "content": "模型运行时不可用，本轮停止执行。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "runtime_directive_executor",
            }
            return
        context_package = self._build_context_package_preview_for_session(
            session_id=request.session_id,
            pending_user_message=request.message,
            memory_intent=analyze_memory_intent(request.message),
            relevant_memory_notes=None,
            retrieval_results=None,
        )
        system_prompt = build_system_prompt(
            self.base_dir,
            self.settings_service.get_rag_mode(),
            persistent_memory=None,
            session_memory=None,
            context_package=context_package,
            active_skill=None,
        )
        model_messages = [
            {"role": "system", "content": system_prompt},
            *[
                {
                    "role": str(item.get("role") or "user"),
                    "content": str(item.get("content") or ""),
                }
                for item in list(history or [])
                if str(item.get("content") or "").strip()
            ],
            {"role": "user", "content": request.message},
        ]
        response = await invoker(model_messages)
        raw_content = stringify_content(getattr(response, "content", response))
        output_boundary = AssistantOutputBoundary()
        output_boundary.ingest_ai_update(raw_content, has_tool_calls=False)
        output_boundary.finalize_segment(fallback_content=raw_content)
        output_response = output_boundary.build_response(
            route="",
            execution_posture="model",
            user_message=request.message,
            tool_name="",
            retrieval_results=None,
        )
        content = sanitize_visible_assistant_content(output_response.canonical_answer).strip()
        if not content:
            content = "我已接入新的单 agent 主链，但这轮模型没有返回可展示内容。"
        runtime_commit_gate = build_blocked_runtime_commit_gate(
            task_id=directive.task_id,
            plan_ref=directive.plan_ref,
            execution_graph_ref=directive.execution_graph_ref,
            directive_ref=directive.directive_id,
            output_response=output_response,
        )
        yield {
            "type": "answer_candidate",
            "content": content,
            "source": "runtime_directive:model_response",
            "directive_ref": directive.directive_id,
        }
        yield {
            "type": "output_boundary",
            "output": {
                "visible_text": output_response.visible_text,
                "canonical_answer": content,
                "selected_channel": output_response.selected_channel,
                "selected_source": output_response.selected_source,
                "canonical_state": output_response.canonical_state,
                "persist_policy": output_response.persist_policy,
                "finalization_policy": output_response.finalization_policy,
                "leak_flags": list(output_response.leak_flags),
                "fallback_reason": output_response.fallback_reason,
            },
        }
        yield {
            "type": "runtime_commit_gate",
            "commit_gate": runtime_commit_gate.to_dict(),
        }
        yield {
            "type": "done",
            "content": content,
            "main_context": {},
            "task_summary_refs": [],
            "answer_channel": output_response.selected_channel,
            "answer_source": "runtime_directive:model_response",
            "answer_canonical_state": output_response.canonical_state,
            "answer_persist_policy": output_response.persist_policy,
            "answer_finalization_policy": output_response.finalization_policy,
            "answer_fallback_reason": output_response.fallback_reason,
            "answer_leak_flags": list(output_response.leak_flags),
            "persist_policy": "commit_gate_blocked",
            "commit_gate": runtime_commit_gate.to_dict(),
        }

    def _build_model_response_runtime_directive(
        self,
        task_operation_preview: dict[str, Any],
    ) -> tuple[RuntimeDirective, ResourcePolicy]:
        task_contract = dict(task_operation_preview.get("task_contract") or {})
        task_id = str(task_contract.get("task_id") or "task-runtime")
        plan_preview = dict(task_operation_preview.get("orchestration_plan_preview") or {})
        stages = list(plan_preview.get("stages") or [])
        stage_preview = dict(stages[0] if stages else {})
        policy_ref = f"respol:{task_id}:model-response:runtime"
        decision = ResourceDecision(
            operation_id="op.model_response",
            decision="allow",
            reason="model-only response is the phase-1 executable lane",
            risk_tags=("model_only", "read_only"),
        )
        resource_policy = ResourcePolicy(
            policy_id=policy_ref,
            task_id=task_id,
            allowed_operations=("op.model_response",),
            denied_operations=(),
            requires_approval_operations=(),
            preview_only_operations=(),
            allowed_tools=(),
            denied_tools=(),
            allowed_workers=(),
            denied_workers=(),
            allowed_agents=(),
            denied_agents=(),
            memory_read_scope="context_package_preview",
            memory_write_scope="none",
            approval_policy="model_only",
            preview_only=False,
            adopted=True,
            runtime_executable=True,
            decisions=(decision,),
            diagnostics={
                "runtime_executable": True,
                "adopted": True,
                "model_only": True,
                "tools_allowed": False,
                "workers_allowed": False,
                "memory_write_allowed": False,
                "filesystem_write_allowed": False,
            },
        )
        directive = RuntimeDirective(
            directive_id=f"runtime-directive:{task_id}:model-response",
            task_id=task_id,
            plan_ref=str(plan_preview.get("plan_id") or f"orchplan:{task_id}").replace(":preview", ":runtime"),
            stage_ref=str(stage_preview.get("stage_id") or f"orchstage:{task_id}:model").replace(":preview", ":runtime"),
            executor_type="model",
            adopted_resource_policy_ref=policy_ref,
            operation_refs=("op.model_response",),
            input_contract_ref=str(task_operation_preview.get("task_prompt_contract", {}).get("contract_id") or ""),
            output_contract_ref=str(task_operation_preview.get("task_prompt_contract", {}).get("contract_id") or ""),
            execution_graph_ref=str(task_operation_preview.get("execution_graph_preview", {}).get("graph_preview_id") or "").replace(":preview", ":runtime"),
            runtime_executable=True,
            diagnostics={
                "source_preview_plan_ref": str(plan_preview.get("plan_id") or ""),
                "source_preview_stage_ref": str(stage_preview.get("stage_id") or ""),
                "directive_only_executor": True,
                "model_only": True,
            },
        )
        return directive, resource_policy

    def _task_operation_preview_events(
        self,
        task_operation_preview: dict[str, Any],
        *,
        fail_closed_message: str,
    ) -> list[dict[str, Any]]:
        control_result = dict(task_operation_preview.get("control_kernel_result") or {})
        ref_payload = _preview_ref_payload(task_operation_preview)
        return [
            {
                "type": "task_operation_preview",
                "preview": task_operation_preview,
            },
            {
                "type": "candidate_set_preview",
                "candidates": list(task_operation_preview.get("candidate_set_preview") or []),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "orchestration_plan_preview",
                "plan": dict(task_operation_preview.get("orchestration_plan_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "plan_validation",
                "validation": dict(task_operation_preview.get("plan_validation") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "execution_graph_preview",
                "graph_preview": dict(task_operation_preview.get("execution_graph_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "adoption_candidate_preview",
                "adoption": dict(task_operation_preview.get("adoption_candidate_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "runtime_directive_candidate_preview",
                "candidates": list(task_operation_preview.get("runtime_directive_candidates") or []),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "commit_gate_preview",
                "commit_gate": dict(task_operation_preview.get("commit_gate_preview") or {}),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "orchestration_control",
                "control": control_result,
                "unit_catalog": self.unit_catalog.to_list(),
                "task_operation_preview_ref": ref_payload,
            },
            {
                "type": "error",
                "error": str(control_result.get("reason") or "preview_only"),
                "content": fail_closed_message,
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "control_kernel",
            },
        ]

    async def _stream_bundle_execution(
        self,
        *,
        session_id: str,
        message: str,
        executions: list[QueryExecutionPlan],
        plan: QueryPlan,
        trace=None,
    ):
        chain_preview = self._build_live_agent_runtime_chain_preview(
            session_id=session_id,
            task_id=f"turn:{session_id}:legacy_bundle_removed",
            message=message,
            source="query_runtime.stream_bundle_execution.removed",
        )
        for event in self._agent_runtime_chain_preview_events(
            chain_preview,
            fail_closed_message="旧 bundle 执行链已清理；等待 RuntimeDirective 主链接管。",
        ):
            yield event
        return

    async def _stream_single_execution(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        *,
        ephemeral_system_messages: list[str] | None = None,
        trace=None,
    ):
        chain_preview = self._build_live_agent_runtime_chain_preview(
            session_id=session_id,
            task_id=f"turn:{session_id}:legacy_single_removed",
            message=message,
            source="query_runtime.stream_single_execution.removed",
        )
        for event in self._agent_runtime_chain_preview_events(
            chain_preview,
            fail_closed_message="旧 single execution 链已清理；等待 RuntimeDirective 主链接管。",
        ):
            yield event
        return

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
            **self._carry_execution_branch_fields(execution),
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
            **self._carry_execution_branch_fields(execution),
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

    def _load_evidence_restore_candidates(self, session_id: str) -> dict[str, Any]:
        loader = getattr(self.session_manager, "get_runtime_state", None)
        if not callable(loader):
            return {}
        try:
            state = loader(session_id, "evidence_state")
        except Exception:
            return {}
        if not isinstance(state, dict) or not state:
            return {}
        candidates: dict[str, Any] = {}
        binding_candidates = state.get("binding_candidates")
        if isinstance(binding_candidates, dict):
            candidates["binding_candidates"] = binding_candidates
        evidence_graph = state.get("evidence_graph")
        if isinstance(evidence_graph, dict):
            candidates["evidence_graph"] = evidence_graph
        return candidates

    def _apply_evidence_restore_candidates(self, session_id: str, candidates_payload: dict[str, Any]) -> None:
        if not isinstance(candidates_payload, dict) or not candidates_payload:
            return
        candidates = candidates_payload.get("binding_candidates")
        if isinstance(candidates, dict):
            self.binding_candidate_store.restore(session_id, candidates)
        graph = candidates_payload.get("evidence_graph")
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
            **self._carry_execution_branch_fields(execution),
        )

    def _carry_execution_branch_fields(self, execution: QueryExecutionPlan) -> dict[str, Any]:
        """Preserve the canonical branch identity when a candidate selection rewrites execution."""
        return {
            "subtask_id": str(getattr(execution, "subtask_id", "") or ""),
            "subtask_goal": str(getattr(execution, "subtask_goal", "") or ""),
            "subtask_title": str(getattr(execution, "subtask_title", "") or ""),
            "subtask_refs": dict(getattr(execution, "subtask_refs", {}) or {}),
            "subtask_depends_on": list(getattr(execution, "subtask_depends_on", []) or []),
            "subtask_origin": str(getattr(execution, "subtask_origin", "") or ""),
            "bundle_id": str(getattr(execution, "bundle_id", "") or ""),
            "bundle_item_id": str(getattr(execution, "bundle_item_id", "") or ""),
            "bundle_item_index": int(getattr(execution, "bundle_item_index", 0) or 0),
            "bundle_origin": str(getattr(execution, "bundle_origin", "") or ""),
        }

    async def _stream_planned_execution(
        self,
        session_id: str,
        execution: QueryExecutionPlan,
        *,
        trace=None,
    ):
        chain_preview = self._build_live_agent_runtime_chain_preview(
            session_id=session_id,
            task_id=f"turn:{session_id}:legacy_planned_removed",
            message=str(getattr(execution, "message", "") or ""),
            source="query_runtime.stream_planned_execution.removed",
        )
        for event in self._agent_runtime_chain_preview_events(
            chain_preview,
            fail_closed_message="旧 planned execution 链已清理；等待 RuntimeDirective 主链接管。",
        ):
            yield event
        return
    async def _run_post_turn_tasks(self, session_id: str, *, title_seed: str | None = None) -> None:
        try:
            await asyncio.to_thread(self.preview_session_memory_refresh, session_id)
        except Exception:
            logger.exception("Failed to preview session memory refresh for %s", session_id)

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
        self.preview_session_memory_refresh(session_id)
        return ""

    def preview_session_memory_refresh(self, session_id: str):
        projection = self._context_state.peek_session_memory_projection(session_id)
        gate = self._memory_writeback.preview_session_projection(session_id, projection)
        return self._merge_memory_gate_preview(session_id, gate)

    def commit_durable_memory_extraction(self, session_id: str) -> int:
        projections = self._context_state.drain_durable_memory_projections(session_id)
        if projections:
            self._merge_memory_gate_preview(session_id, self._preview_durable_projection_batch(session_id, projections))
            return 0
        self._merge_memory_gate_preview(session_id, self._memory_writeback.preview_durable_history(session_id))
        return 0

    def schedule_durable_memory_extraction(self, session_id: str) -> int:
        pending_projection_count = self._context_state.pending_durable_projection_count(session_id)
        if pending_projection_count:
            min_projection_batch = self._durable_projection_batch_threshold()
            if (
                pending_projection_count < min_projection_batch
                and not self._has_explicit_durable_projection(session_id)
            ):
                return 0
            projections = self._context_state.drain_durable_memory_projections(session_id)
            if projections:
                gate = self._preview_durable_projection_batch(session_id, projections)
                self._merge_memory_gate_preview(session_id, gate)
                return 0
        self._merge_memory_gate_preview(session_id, self._memory_writeback.preview_durable_history(session_id))
        return 0

    def preview_durable_memory_extraction(self, session_id: str):
        projections = self._context_state.peek_durable_memory_projections(session_id)
        if projections:
            gate = self._preview_durable_projection_batch(session_id, projections)
        else:
            gate = self._memory_writeback.preview_durable_history(session_id)
        return self._merge_memory_gate_preview(session_id, gate)

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
        search_policy: list[str] | None = None,
    ) -> QueryPlan:
        raise RuntimeError(
            "legacy QueryPlanner execution path is retired; use AgentRuntimeChainPreview and RuntimeDirective"
        )

    async def _build_orchestration_plan(
        self,
        *,
        session_id: str,
        message: str,
        plan: QueryPlan,
        source: str = "live-session",
        contract_previews: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        task = TaskContract(
            task_id=f"legacy-plan:{session_id}",
            user_goal=message,
            session_id=session_id,
            refs={"legacy_query_plan": type(plan).__name__, "source": source},
        )
        return self.control_kernel.collect(task=task).to_dict()

    def _build_orchestration_diff_event(
        self,
        orchestration_plan: dict[str, Any],
        event: dict[str, Any],
        *,
        actual_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "orchestration_diff",
            "diff": {
                "status": "skipped",
                "summary": "旧 orchestration diff 接线已清空。",
                "plan_id": str(orchestration_plan.get("plan_id") or ""),
                "actual_trace": dict(actual_trace or {}),
                "event_type": str(event.get("type") or ""),
            },
        }

    def _apply_runtime_control_to_orchestration_plan(self, orchestration_plan: dict[str, Any], runtime_control) -> None:
        diagnostics = orchestration_plan.setdefault("diagnostics", {})
        if isinstance(diagnostics, dict):
            diagnostics["runtime_control"] = {
                "source": runtime_control.source,
                "primary_active": bool(runtime_control.primary_active),
                "execution_mode": runtime_control.execution_mode,
                "execution_count": len(runtime_control.execution_specs),
                "warnings": list(runtime_control.warnings),
                **dict(runtime_control.diagnostics),
            }
        safety = orchestration_plan.setdefault("safety", {})
        if isinstance(safety, dict):
            warnings = [
                str(item)
                for item in list(safety.get("warnings") or [])
                if str(item or "").strip()
            ]
            for warning in runtime_control.warnings:
                if warning not in warnings:
                    warnings.append(warning)
            safety["warnings"] = warnings
            if warnings:
                safety["mode"] = str(safety.get("mode") or orchestration_plan.get("mode") or "primary")

    def _executions_from_runtime_control(
        self,
        runtime_control,
        candidate_executions: list[QueryExecutionPlan],
    ) -> list[QueryExecutionPlan]:
        if not runtime_control.primary_active:
            return []
        candidates: dict[str, list[QueryExecutionPlan]] = {}
        for index, execution in enumerate(candidate_executions, start=1):
            execution_id = str(getattr(execution, "subtask_id", "") or getattr(execution, "bundle_item_id", "") or "main")
            candidates.setdefault(execution_id, []).append(execution)
        selected: list[QueryExecutionPlan] = []
        missing: list[str] = []
        for index, spec in enumerate(list(getattr(runtime_control, "execution_specs", []) or []), start=1):
            execution_id = str(spec.get("execution_id") or f"main-{index}")
            matching = candidates.get(execution_id) or []
            if not matching:
                missing.append(execution_id)
                continue
            selected.append(matching.pop(0))
        if missing:
            runtime_control.primary_active = False
            runtime_control.source = "orchestration_blocked"
            runtime_control.execution_mode = "blocked"
            runtime_control.warnings.append("execution_candidate_missing")
            runtime_control.diagnostics["blocked_reason"] = "execution_candidate_missing"
            runtime_control.diagnostics["missing_execution_ids"] = missing
            return []
        return selected

    def _fail_closed_runtime_control_event(self, runtime_control, *, reason: str | None = None) -> dict[str, Any]:
        blocked_reason = str(reason or runtime_control.diagnostics.get("blocked_reason") or "orchestration_blocked")
        details = ", ".join(str(item) for item in list(runtime_control.warnings or []) if str(item).strip())
        content = "编排计划未通过运行时校验，本轮已按 fail-closed 策略停止执行。"
        if details:
            content = f"{content} 阻断原因：{details}。"
        return {
            "type": "error",
            "content": content,
            "error": blocked_reason,
            "answer_channel": "orchestration_fail_closed",
            "answer_source": "orchestration_runtime_control",
        }

    def _build_live_behavior_snapshot(
        self,
        *,
        session_id: str,
        message: str,
        plan: QueryPlan,
        execution: QueryExecutionPlan,
        orchestration_plan: dict[str, Any] | None = None,
        contract_previews: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "source": "live-session",
            "session_id": session_id,
            "message": message,
            "state": "wiring_cleared",
            "orchestration_plan": dict(orchestration_plan or {}),
            "unit_catalog": self.unit_catalog.to_list(),
            "warnings": ["legacy_behavior_trace_removed"],
        }

    def _build_contract_previews_for_execution(self, execution: QueryExecutionPlan) -> list[dict[str, Any]]:
        return []

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
            active_object_handle_id=(
                str(getattr(task.context_ref, "primary_object_handle_id", "") or "")
                if getattr(task, "context_ref", None) is not None
                else ""
            ),
            active_result_handle_id=(
                str(getattr(task.context_ref, "primary_result_handle_id", "") or "")
                if getattr(task, "context_ref", None) is not None
                else ""
            ),
            active_subset_handle_id=(
                str(getattr(task.context_ref, "active_subset_handle_id", "") or "")
                if getattr(task, "context_ref", None) is not None
                else ""
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
            subset_filter_column=str(presentation_hints.get("subset_filter_column", "") or ""),
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

    def _build_output_commit_plan(
        self,
        *,
        done_event: dict[str, Any],
        assistant_messages: list[dict[str, Any]],
        segment_count: int,
        title_seed: str | None,
    ) -> dict[str, Any]:
        return {
            "projection": {},
            "assistant_messages": [],
            "post_turn": {},
            "diagnostics": {
                "state": "commit_gate_removed",
                "allowed": False,
                "segment_count": segment_count,
                "assistant_message_count": len(assistant_messages),
                "title_seed_present": bool(title_seed),
                "done_event_type": str(done_event.get("type") or ""),
            },
        }

    def _apply_output_commit_plan(
        self,
        session_id: str,
        commit_plan: dict[str, Any],
        *,
        trace=None,
    ) -> bool:
        if trace is not None:
            trace.annotate(
                {
                    "app.final_segment_count": int(dict(commit_plan.get("diagnostics") or {}).get("segment_count") or 0),
                    "app.assistant_persisted": False,
                    "app.output_commit_state": "commit_gate_blocked",
                }
            )
        return False

    def _load_session_binding_snapshot(self, session_id: str) -> dict[str, Any]:
        return self._context_state.load_session_binding_snapshot(session_id)

    def _load_session_restore_candidates(self, session_id: str) -> dict[str, Any]:
        return self._context_state.load_session_restore_candidates(session_id)

    def _planner_authority_context(self, session_id: str) -> dict[str, Any]:
        return self._planner_authority_context_result(session_id).context

    def _planner_authority_context_result(self, session_id: str):
        return type(
            "PlannerAuthorityContextResult",
            (),
            {
                "context": {},
                "diagnostics": {
                    "state": "restore_context_gate_removed",
                    "session_id": session_id,
                    "takeover_allowed": False,
                },
            },
        )()

    def _attach_restore_context_gate_diagnostics(
        self,
        orchestration_plan: dict[str, Any] | None,
        diagnostics: dict[str, Any],
    ) -> None:
        if not isinstance(orchestration_plan, dict) or not diagnostics:
            return
        plan_diagnostics = orchestration_plan.setdefault("diagnostics", {})
        if not isinstance(plan_diagnostics, dict):
            return
        restore_authority = plan_diagnostics.setdefault("restore_authority", {})
        if isinstance(restore_authority, dict):
            restore_authority["restore_authority_context_gate"] = dict(diagnostics)

    def _preview_followup_runtime_risk(
        self,
        *,
        session_id: str,
        history: list[dict[str, Any]],
        message: str,
    ) -> dict[str, Any]:
        session_memory = getattr(self.memory_facade, "session_memory", None)
        manager_factory = getattr(session_memory, "manager", None)
        if session_memory is None or not callable(manager_factory):
            return {}
        try:
            manager = manager_factory(session_id)
            preview_history = [*list(history or []), {"role": "user", "content": message}]
            preview_messages = self.memory_facade.adapter.to_messages(preview_history, session_id=session_id)
            state = manager.preview_state(preview_messages)
        except Exception:
            logger.exception("Failed to preview follow-up runtime risk for %s", session_id)
            return {}
        return {
            "risk_flags": [
                str(item or "").strip()
                for item in list(getattr(state, "risk_flags", []) or [])
                if str(item or "").strip()
            ],
            "flow_type": str(getattr(getattr(state, "flow_state", None), "flow_type", "") or "").strip(),
            "active_pdf": str(getattr(getattr(state, "context_slots", None), "active_pdf", "") or "").strip(),
            "active_dataset": str(getattr(getattr(state, "context_slots", None), "active_dataset", "") or "").strip(),
        }

    def _durable_projection_batch_threshold(self) -> int:
        durable_layer = getattr(self.memory_facade, "durable_memory", None)
        scheduler = getattr(durable_layer, "scheduler", None)
        config = getattr(scheduler, "config", None)
        threshold = int(getattr(config, "min_messages_between_runs", 1) or 1)
        return max(1, threshold)

    def _has_explicit_durable_projection(self, session_id: str) -> bool:
        return self._memory_writeback.has_explicit_durable_projection(
            self._context_state.peek_durable_memory_projections(session_id)
        )

    def _commit_durable_projection_batch(
        self,
        session_id: str,
        projections: list[dict[str, Any]],
    ) -> int:
        self._merge_memory_gate_preview(session_id, self._preview_durable_projection_batch(session_id, projections))
        return 0

    def _preview_durable_projection_batch(
        self,
        session_id: str,
        projections: list[dict[str, Any]],
    ):
        return self._memory_writeback.preview_durable_projections(session_id, projections)

    def _merge_memory_gate_preview(self, session_id: str, gate):
        candidates = tuple(getattr(gate, "write_candidates", ()) or ())
        return self._build_blocked_memory_gate_preview(session_id, candidates)

    def _build_blocked_memory_gate_preview(self, session_id: str, candidates):
        builder = getattr(self.memory_facade, "build_memory_gate_preview", None)
        if not callable(builder):
            self.memory_gate_preview = None
            return None
        existing_candidates = tuple(getattr(self.memory_gate_preview, "write_candidates", ()) or ())
        incoming_candidates = tuple(candidates or ())
        by_id = {str(getattr(candidate, "candidate_id", "") or index): candidate for index, candidate in enumerate(existing_candidates)}
        for index, candidate in enumerate(incoming_candidates):
            by_id[str(getattr(candidate, "candidate_id", "") or f"incoming-{index}")] = candidate
        self.memory_gate_preview = builder(
            tuple(by_id.values()),
            gate_id=f"memory-gate:{session_id or 'session'}:writeback-preview",
            reason="query_runtime_writeback_preview_only",
        )
        return self.memory_gate_preview

    def _guard_followup_resolution_by_runtime_risk(
        self,
        *,
        message: str,
        followup_resolution,
        risk_snapshot: dict[str, Any] | None,
    ):
        if str(getattr(followup_resolution, "mode", "") or "").strip() != "binding_ref":
            return followup_resolution
        flags = {
            str(item or "").strip()
            for item in list((risk_snapshot or {}).get("risk_flags", []) or [])
            if str(item or "").strip()
        }
        if not flags:
            return followup_resolution
        binding_kind = str(getattr(followup_resolution, "resolved_binding_kind", "") or getattr(followup_resolution, "binding_kind", "") or "").strip()
        if self._message_has_strong_binding_anchor(message, binding_kind=binding_kind):
            return followup_resolution
        if "clarification_required" in flags:
            return FollowupResolution(
                mode="clarify",
                target_kind=str(getattr(followup_resolution, "target_kind", "") or "binding"),
                resolved_target_kind=str(getattr(followup_resolution, "resolved_target_kind", "") or "binding"),
                task_id=str(getattr(followup_resolution, "task_id", "") or ""),
                task_ids=list(getattr(followup_resolution, "task_ids", []) or []),
                resolved_task_id=str(getattr(followup_resolution, "resolved_task_id", "") or ""),
                resolved_task_ids=list(getattr(followup_resolution, "resolved_task_ids", []) or []),
                binding_key=str(getattr(followup_resolution, "binding_key", "") or ""),
                binding_kind=binding_kind,
                binding_identity=str(getattr(followup_resolution, "binding_identity", "") or ""),
                binding_owner_task_id=str(getattr(followup_resolution, "binding_owner_task_id", "") or ""),
                resolved_binding_kind=binding_kind,
                resolved_binding_identity=str(getattr(followup_resolution, "resolved_binding_identity", "") or ""),
                resolved_binding_owner_task_id=str(getattr(followup_resolution, "resolved_binding_owner_task_id", "") or ""),
                resolution_source="runtime_risk_gate",
                confidence=0.0,
                reason="runtime_risk_clarification_required",
                requires_clarification=True,
                clarification_prompt="当前会话上下文存在任务漂移风险。请直接说明你要继续的是哪一个对象、文件或结果。",
            )
        suppressing_flags = {"cross_flow_slot_contamination", "implicit_goal_jump"}
        if suppressing_flags & flags:
            return FollowupResolution(
                resolution_source="runtime_risk_gate",
                reason="runtime_risk_binding_suppressed",
            )
        if "low_flow_confidence" in flags and str(getattr(followup_resolution, "resolution_source", "") or "").strip() == "session_committed_binding":
            return FollowupResolution(
                resolution_source="runtime_risk_gate",
                reason="runtime_low_confidence_binding_suppressed",
            )
        return followup_resolution

    def _message_has_strong_binding_anchor(self, message: str, *, binding_kind: str) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        if binding_kind == "active_pdf":
            if ".pdf" in normalized:
                return True
            if re.search(r"第\s*\d+\s*页", message):
                return True
            if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
                return True
            if re.search(r"page\s*\d+", normalized):
                return True
            if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)", message):
                return True
            return any(
                marker in message or marker in normalized
                for marker in (
                    "这份 pdf",
                    "那个 pdf",
                    "这份PDF",
                    "那个PDF",
                    "回到刚才 pdf",
                    "回到刚才 PDF",
                    "刚才那份 pdf",
                    "刚才那份 PDF",
                    "这份文档",
                    "那个文档",
                )
            )
        if binding_kind == "active_dataset":
            return any(ext in normalized for ext in (".xlsx", ".csv", ".xls", ".json", ".parquet"))
        return False

    def _is_stale_non_worker_rag_plan(self, execution: QueryExecutionPlan) -> bool:
        if not self.settings_service.get_rag_mode():
            return False
        if str(getattr(execution.query_understanding, "route", "") or "") != "rag":
            return False
        if str(getattr(execution, "execution_kind", "") or "") == "worker":
            return False
        if getattr(execution, "worker_plan", None) is not None:
            return False
        if bool(getattr(execution.memory_intent, "should_skip_rag", False)):
            return False
        if bool(getattr(execution.query_understanding, "should_skip_rag", False)):
            return False
        return True

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
        chain_preview = self._build_live_agent_runtime_chain_preview(
            session_id=session_id,
            task_id=f"turn:{session_id}:legacy_direct_tool_removed",
            message=str(getattr(execution, "message", "") or ""),
            source="query_runtime.stream_direct_tool_execution.removed",
        )
        for event in self._agent_runtime_chain_preview_events(
            chain_preview,
            fail_closed_message="旧 direct tool 执行链已清理；工具只能通过 RuntimeDirective + OperationGate 进入。",
        ):
            yield event
        return

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

    def _tool_step_guard_done_event(
        self,
        *,
        execution: QueryExecutionPlan,
        recent_tool_receipts: list[dict[str, str]],
    ) -> dict[str, Any]:
        content = self._build_tool_step_guard_message(
            message=execution.message,
            recent_tool_receipts=recent_tool_receipts,
        )
        return {
            "type": "done",
            "content": content,
            "main_context": self._build_main_working_context(execution).to_dict(),
            "task_summary_refs": [],
            "answer_channel": "fallback_answer",
            "answer_source": "tool_step_guard",
            "answer_fallback_reason": "agent_tool_steps_exceeded",
            "answer_leak_flags": [],
        }

    def _model_runtime_failure_done_event(
        self,
        *,
        execution: QueryExecutionPlan,
        main_context: MainContextState,
        error: ModelRuntimeError,
        recent_tool_receipts: list[dict[str, str]],
    ) -> dict[str, Any]:
        fallback_reason = f"model_runtime_{str(getattr(error, 'code', '') or 'error').strip() or 'error'}"
        return {
            "type": "done",
            "content": self._build_model_runtime_failure_message(
                error=error,
                recent_tool_receipts=recent_tool_receipts,
            ),
            "main_context": main_context.to_dict(),
            "task_summary_refs": [],
            "answer_channel": "fallback_answer",
            "answer_source": "runtime_error_fallback",
            "answer_fallback_reason": fallback_reason,
            "answer_leak_flags": [],
        }

    def _build_model_runtime_failure_message(
        self,
        *,
        error: ModelRuntimeError,
        recent_tool_receipts: list[dict[str, str]],
    ) -> str:
        code = str(getattr(error, "code", "") or "").strip()
        if code == "timeout":
            lines = ["这轮在整理最终答案时超时了，我先把当前进展停在这里。"]
        else:
            lines = ["这轮在生成最终答案时中断了，我先把当前进展停在这里。"]
        recent_attempts = [
            item
            for item in (self._summarize_tool_step_attempt(receipt) for receipt in recent_tool_receipts[-3:])
            if item
        ]
        if recent_attempts:
            lines.append("我刚才已经做到这些：")
            for item in recent_attempts:
                lines.append(f"- {item}")
        lines.append("你可以直接告诉我继续沿哪条线程、哪个文件，或让我只基于当前已拿到的结果先给结论。")
        return "\n".join(lines)

    def _build_tool_step_guard_message(
        self,
        *,
        message: str,
        recent_tool_receipts: list[dict[str, str]],
    ) -> str:
        lines = [
            "这轮我连续尝试了过多工具调用，但还是没有形成稳定答案，所以先停下来，避免继续空转。"
        ]
        recent_attempts = [
            item
            for item in (self._summarize_tool_step_attempt(receipt) for receipt in recent_tool_receipts[-3:])
            if item
        ]
        if recent_attempts:
            lines.append("最近几次尝试是：")
            for item in recent_attempts:
                lines.append(f"- {item}")
        if str(message or "").strip():
            lines.append("如果要继续，最好直接告诉我要延续哪条线程、哪个文件，或你想保留哪份结果。")
        return "\n".join(lines)

    def _summarize_tool_step_attempt(self, receipt: dict[str, str]) -> str:
        tool_name = str(receipt.get("tool", "") or "").strip() or "tool"
        raw_input = str(receipt.get("input", "") or "").strip()
        raw_output = str(receipt.get("output", "") or "").strip()
        parsed_input = self._parse_tool_step_input(raw_input)
        path = str(parsed_input.get("path", "") or "").strip()
        query = str(parsed_input.get("query", "") or "").strip()

        if tool_name == "read_file" and "path is a directory" in raw_output.lower():
            target = f"`{path}`" if path else "目标路径"
            return f"`read_file` 试图读取 {target}，但那里是目录，不是文件。"
        if tool_name == "pdf_analysis" and "explicit path is required" in raw_output.lower():
            return "`pdf_analysis` 被用于查找 PDF，但这个工具必须提供明确文件路径。"
        if tool_name == "structured_data_analysis" and raw_output:
            dataset = path.rsplit("/", 1)[-1] if path else "当前数据表"
            return f"`structured_data_analysis` 已拿到 `{dataset}` 的一份结构化结果，但还没有收束成最终回答。"
        if raw_output:
            compact_output = " ".join(raw_output.split())
            compact_output = compact_output[:80] + ("..." if len(compact_output) > 80 else "")
            return f"`{tool_name}` 返回了：{compact_output}"
        if query:
            compact_query = " ".join(query.split())
            compact_query = compact_query[:60] + ("..." if len(compact_query) > 60 else "")
            return f"`{tool_name}` 仍在围绕“{compact_query}”反复尝试。"
        return f"`{tool_name}` 被重复调用，但还没有形成可用结果。"

    def _parse_tool_step_input(self, raw_input: str) -> dict[str, Any]:
        normalized = str(raw_input or "").strip()
        if not normalized:
            return {}
        try:
            payload = json.loads(normalized)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

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
        return self._memory_writeback.build_acknowledgement(message)

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

    def _answer_assembly_payload(self, plan, *, content: str) -> dict[str, Any]:
        segments = [self._pydantic_to_dict(item) for item in list(getattr(plan, "segments", []) or [])]
        dropped = [self._pydantic_to_dict(item) for item in list(getattr(plan, "dropped_segments", []) or [])]
        style_constraints = self._pydantic_to_dict(getattr(plan, "style_constraints", None))
        return {
            "selected_task_ids": [
                str(item.get("task_id") or "").strip()
                for item in segments
                if str(item.get("task_id") or "").strip()
            ],
            "selected_count": len(segments),
            "dropped_count": len(dropped),
            "segments": segments,
            "dropped_segments": dropped,
            "dedupe_targets": list(getattr(plan, "dedupe_targets", []) or []),
            "source_refs": list(getattr(plan, "source_refs", []) or []),
            "style_constraints": style_constraints,
            "content_preview": " ".join(str(content or "").split())[:240],
            "content_chars": len(str(content or "")),
        }

    def _pydantic_to_dict(self, value) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return dict(model_dump())
        as_dict = getattr(value, "dict", None)
        if callable(as_dict):
            return dict(as_dict())
        return {}

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


def _preview_ref_payload(preview: dict[str, Any]) -> dict[str, Any]:
    task_contract = dict(preview.get("task_contract") or {})
    operation_requirement = dict(preview.get("operation_requirement") or {})
    resource_policy = dict(preview.get("resource_policy") or {})
    task_prompt_contract = dict(preview.get("task_prompt_contract") or {})
    prompt_manifest = dict(preview.get("prompt_manifest_preview") or {})
    topology = dict(preview.get("execution_topology_preview") or {})
    coordination_policy = dict(preview.get("coordination_policy_preview") or {})
    orchestration_plan = dict(preview.get("orchestration_plan_preview") or {})
    plan_validation = dict(preview.get("plan_validation") or {})
    graph_preview = dict(preview.get("execution_graph_preview") or {})
    adoption = dict(preview.get("adoption_candidate_preview") or {})
    adoption_block = dict(preview.get("adoption_block") or {})
    runtime_directive_block = dict(preview.get("runtime_directive_block") or {})
    operation_gate_preflight = dict(preview.get("operation_gate_preflight") or {})
    directive_only_executor = dict(preview.get("directive_only_executor_preview") or {})
    commit_gate = dict(preview.get("commit_gate_preview") or {})
    control_kernel_result = dict(preview.get("control_kernel_result") or {})
    execution_graph = dict(control_kernel_result.get("execution_graph") or {})
    return {
        "status": str(preview.get("status") or "preview_only"),
        "task_id": str(task_contract.get("task_id") or ""),
        "operation_requirement_ref": str(operation_requirement.get("requirement_id") or ""),
        "resource_policy_ref": str(resource_policy.get("policy_id") or ""),
        "task_prompt_contract_ref": str(task_prompt_contract.get("contract_id") or ""),
        "prompt_manifest_ref": str(prompt_manifest.get("manifest_id") or ""),
        "execution_topology_ref": str(topology.get("topology_id") or ""),
        "execution_topology_mode": str(topology.get("mode") or "single_agent"),
        "coordination_policy_ref": str(coordination_policy.get("policy_id") or ""),
        "orchestration_plan_ref": str(orchestration_plan.get("plan_id") or ""),
        "plan_validation_ref": str(plan_validation.get("validation_id") or ""),
        "plan_validation_status": str(plan_validation.get("status") or ""),
        "execution_graph_preview_ref": str(graph_preview.get("graph_preview_id") or ""),
        "execution_graph_preview_node_count": len(list(graph_preview.get("node_previews") or [])),
        "adoption_candidate_ref": str(adoption.get("candidate_id") or ""),
        "adoption_candidate_status": str(adoption.get("status") or ""),
        "adoption_block_ref": str(adoption_block.get("block_id") or ""),
        "adopted_resource_policy_available": False,
        "runtime_directive_candidate_count": len(list(preview.get("runtime_directive_candidates") or [])),
        "runtime_directive_block_ref": str(runtime_directive_block.get("block_id") or ""),
        "runtime_directive_available": False,
        "operation_gate_preflight_ref": str(operation_gate_preflight.get("preflight_id") or ""),
        "operation_gate_passed": bool(operation_gate_preflight.get("operation_gate_passed") is True),
        "operation_gate_check_count": len(list(operation_gate_preflight.get("checks") or [])),
        "directive_only_executor_ref": str(directive_only_executor.get("preview_id") or ""),
        "executor_dispatch_enabled": bool(directive_only_executor.get("will_dispatch") is True),
        "executor_accepts_only": str(directive_only_executor.get("accepted_input_type") or ""),
        "commit_gate_ref": str(commit_gate.get("gate_id") or ""),
        "commit_gate_status": str(commit_gate.get("status") or ""),
        "commit_allowed": bool(commit_gate.get("commit_allowed") is True),
        "commit_candidate_count": len(list(commit_gate.get("commit_candidates") or [])),
        "understanding_candidate_count": len(list(preview.get("understanding_candidate_preview") or [])),
        "candidate_count": len(list(preview.get("candidate_set_preview") or [])),
        "multi_agent_enabled": False,
        "agent_seat_count": len(list(preview.get("agent_seat_plan_previews") or [])),
        "agent_assignment_count": len(list(preview.get("agent_assignment_candidates") or [])),
        "control_status": str(control_kernel_result.get("status") or ""),
        "control_reason": str(control_kernel_result.get("reason") or ""),
        "execution_node_count": len(list(execution_graph.get("nodes") or [])),
        "directive_count": len(list(control_kernel_result.get("directives") or [])),
        "preview_only": bool(preview.get("status") == "preview_only"),
        "runtime_directive_enabled": False,
        "runtime_executable": False,
    }

