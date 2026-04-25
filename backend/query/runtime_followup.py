from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from query.binding_models import StructuredDatasetBinding
from query.context_models import MainContextState, TaskSummaryRef
from query.models import QueryExecutionPlan, QueryPlan
from query.output_boundary import contains_internal_protocol, sanitize_visible_assistant_content
from query.worker_models import WorkerExecutionPlan, WorkerRequest
from understanding import MemoryIntent, QueryUnderstanding


class RuntimeFollowupCoordinator:
    def __init__(self, *, task_coordinator) -> None:
        self.task_coordinator = task_coordinator

    def should_answer_from_followup(
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

    def followup_results_from_resolution(
        self,
        session_id: str,
        followup_resolution,
    ) -> list[dict[str, object]]:
        if followup_resolution.mode not in {"task_ref", "explicit_fanout_subset", "bundle_item_ref", "bundle_subset"}:
            return []
        task_ids = self.resolved_task_ids(followup_resolution)
        if not task_ids and self.resolved_task_id(followup_resolution):
            task_ids = [self.resolved_task_id(followup_resolution)]
        return self.followup_results_from_task_ids(session_id, task_ids)

    def followup_results_from_task_ids(
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

    def followup_result_from_done_event(
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

    def synthesize_followup_task_summary_ref(
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

    def binding_owner_task(self, session_id: str, followup_resolution) -> Any | None:
        owner_task_id = str(
            self.resolved_binding_owner_task_id(followup_resolution)
            or self.resolved_task_id(followup_resolution)
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

    def should_execute_binding_followup(
        self,
        *,
        session_id: str,
        followup_resolution,
        plan: QueryPlan,
    ) -> bool:
        if str(getattr(followup_resolution, "mode", "") or "") != "binding_ref":
            return False
        executions = plan.iter_executions()
        if len(executions) != 1:
            return False
        execution = executions[0]
        route = str(getattr(execution.query_understanding, "route", "") or "").strip()
        if route in {"memory", "compound", "bundle"}:
            return False
        binding_kind = self.resolved_binding_kind(followup_resolution)
        tool_name = str(getattr(execution.query_understanding, "tool_name", "") or "").strip()
        tool_input = dict(getattr(execution, "tool_input", {}) or getattr(execution.query_understanding, "tool_input", {}) or {})
        normalized_path = self.normalize_binding_identity(str(tool_input.get("path", "") or ""))
        normalized_location = str(tool_input.get("location", "") or "").strip()
        binding_identity = self.normalize_binding_identity(self.resolved_binding_identity(followup_resolution))
        owner_task = self.binding_owner_task(session_id, followup_resolution)
        owner_context = getattr(owner_task, "context_ref", None)
        owner_bindings = getattr(owner_context, "bindings", None)
        if binding_kind == "active_pdf":
            owner_path = self.normalize_binding_identity(str(getattr(owner_bindings, "active_pdf", "") or ""))
            expected_path = binding_identity or owner_path
            if not expected_path:
                return False
            if normalized_path and normalized_path != expected_path:
                return False
            return route != "memory"
        if binding_kind == "active_dataset":
            owner_path = self.normalize_binding_identity(str(getattr(owner_bindings, "active_dataset", "") or ""))
            expected_path = binding_identity or owner_path
            if not expected_path:
                return False
            if normalized_path and normalized_path != expected_path:
                return False
            return route != "memory"
        if owner_task is None:
            return False
        owner_context = getattr(owner_task, "context_ref", None)
        owner_bindings = getattr(owner_context, "bindings", None)
        if binding_kind == "active_location":
            owner_location = str(getattr(owner_bindings, "active_location", "") or "").strip()
            return tool_name == "get_weather" and (not normalized_location or normalized_location == owner_location)
        if binding_kind == "active_entity":
            owner_entity = str(getattr(owner_bindings, "active_entity", "") or "").strip()
            return tool_name == "get_gold_price" and owner_entity == "黄金"
        return False

    def normalize_binding_identity(self, value: str) -> str:
        return str(value or "").replace("\\", "/").strip().lower()

    def _scalar_binding_execution_from_task_ref(
        self,
        *,
        session_id: str,
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
        tool_input: dict[str, Any] = {"query": message}
        target_handle_kind = self._target_handle_kind(owner_task)
        target_handle_id = self._target_handle_id(owner_task)
        upstream_object_handle_ids = self._owner_object_handle_ids(owner_task)
        upstream_result_handle_ids = self._owner_result_handle_ids(owner_task)
        arbitration_reason = "scalar_binding_task_ref_followup"

        if bindings.active_location:
            tool_name = tool_name or "get_weather"
            tool_input["location"] = bindings.active_location
            query_understanding = QueryUnderstanding(
                intent="weather_followup_query",
                source_kind="weather",
                task_kind=context_ref.task_kind or "weather",
                modality="realtime",
                route="tool",
                execution_posture="direct_tool",
                direct_route_reason="scalar_binding_weather",
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
                direct_route_reason="scalar_binding_finance",
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
            execution_kind="direct_tool",
            target_handle_kind=target_handle_kind,
            target_handle_id=target_handle_id,
            upstream_object_handle_ids=upstream_object_handle_ids,
            upstream_result_handle_ids=upstream_result_handle_ids,
            arbitration_reason=arbitration_reason,
        )

    def binding_execution_from_resolution(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        followup_resolution,
    ) -> QueryExecutionPlan | None:
        binding_kind = self.resolved_binding_kind(followup_resolution)
        binding_identity = self.resolved_binding_identity(followup_resolution)
        owner_task = self.binding_owner_task(session_id, followup_resolution)
        if owner_task is not None and binding_kind not in {"active_pdf", "active_dataset"}:
            return self._scalar_binding_execution_from_task_ref(
                session_id=session_id,
                message=message,
                history=history,
                owner_task=owner_task,
            )
        if binding_kind == "active_pdf":
            return self._pdf_binding_execution_from_resolution(
                session_id=session_id,
                message=message,
                history=history,
                followup_resolution=followup_resolution,
                owner_task=owner_task,
                active_pdf=binding_identity,
            )
        if binding_kind == "active_dataset":
            return self._dataset_binding_execution_from_resolution(
                session_id=session_id,
                message=message,
                history=history,
                followup_resolution=followup_resolution,
                owner_task=owner_task,
                active_dataset=binding_identity,
            )
        return None

    def _pdf_binding_execution_from_resolution(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        followup_resolution,
        owner_task,
        active_pdf: str,
    ) -> QueryExecutionPlan | None:
        active_pdf = str(active_pdf or "").strip()
        if not active_pdf:
            return None
        target_handle_kind, target_handle_id, upstream_object_handle_ids, upstream_result_handle_ids = (
            self._handle_context_from_resolution(followup_resolution, owner_task=owner_task)
        )
        owner_task_id = str(getattr(owner_task, "task_id", "") or self.resolved_binding_owner_task_id(followup_resolution) or "").strip()
        pdf_constraints = self._pdf_constraints_from_message(message, active_pdf=active_pdf)
        request = WorkerRequest(
            request_id=f"worker:pdf:followup:{owner_task_id or target_handle_id or 'session'}",
            session_id=session_id,
            query=message,
            worker_route="pdf",
            task_frame={
                "intent": "pdf_followup_query",
                "source_kind": "document",
                "task_kind": "pdf",
                "modality": "pdf",
            },
            bindings={"active_pdf": active_pdf},
            constraints=pdf_constraints,
            target_handle_kind=target_handle_kind,
            target_handle_id=target_handle_id,
            upstream_object_handle_ids=upstream_object_handle_ids,
            upstream_result_handle_ids=upstream_result_handle_ids,
            owner_task_id=owner_task_id,
            arbitration_reason="handle_binding_followup",
        )
        query_understanding = QueryUnderstanding(
            intent="pdf_followup_query",
            source_kind="document",
            task_kind="pdf",
            modality="pdf",
            route="worker",
            execution_posture="worker",
            direct_route_reason="handle_binding_pdf_worker",
            capability_requests=["pdf_read"],
            should_skip_rag=True,
            reasons=["handle_binding_followup", "handle_binding_pdf_worker"],
        )
        return QueryExecutionPlan(
            message=message,
            history=list(history),
            memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
            query_understanding=query_understanding,
            execution_kind="worker",
            execution_posture="worker",
            worker_plan=WorkerExecutionPlan(
                worker_route="pdf",
                request=request,
                expected_result="canonical",
                fallback_execution_kind="none",
                cutover_mode="primary",
            ),
            target_handle_kind=target_handle_kind,
            target_handle_id=target_handle_id,
            upstream_object_handle_ids=upstream_object_handle_ids,
            upstream_result_handle_ids=upstream_result_handle_ids,
            arbitration_reason="handle_binding_followup",
        )

    def _dataset_binding_execution_from_resolution(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        followup_resolution,
        owner_task,
        active_dataset: str,
    ) -> QueryExecutionPlan | None:
        active_dataset = str(active_dataset or "").strip()
        if not active_dataset:
            return None
        target_handle_kind, target_handle_id, upstream_object_handle_ids, upstream_result_handle_ids = (
            self._handle_context_from_resolution(followup_resolution, owner_task=owner_task)
        )
        owner_task_id = str(getattr(owner_task, "task_id", "") or self.resolved_binding_owner_task_id(followup_resolution) or "").strip()
        subset_constraints = self._dataset_subset_constraints(owner_task) if owner_task is not None else {}
        followup_query = message if subset_constraints or owner_task is None else self._dataset_followup_query(message, owner_task)
        owner_context = getattr(owner_task, "context_ref", None)
        owner_bindings = getattr(owner_context, "bindings", None)
        owner_constraints = getattr(owner_context, "constraints", None)
        active_table = str(getattr(owner_constraints, "active_table", "") or "").strip()
        structured_binding = StructuredDatasetBinding(
            dataset_path=active_dataset,
            target_object=str(getattr(owner_bindings, "active_entity", "") or ""),
            source="handle_binding",
            confidence=1.0,
            binding_identity=str(self.resolved_binding_identity(followup_resolution) or active_dataset.replace("\\", "/").strip().lower()),
            derived_from_task_id=owner_task_id,
        )
        request = WorkerRequest(
            request_id=f"worker:structured_data:followup:{owner_task_id or target_handle_id or 'session'}",
            session_id=session_id,
            query=followup_query,
            worker_route="structured_data",
            task_frame={
                "intent": "structured_followup_query",
                "source_kind": "dataset",
                "task_kind": "structured_data",
                "modality": "table",
            },
            bindings={
                key: value
                for key, value in {
                    "active_dataset": active_dataset,
                    "active_table": active_table,
                }.items()
                if value not in ("", None)
            },
            constraints={
                key: value
                for key, value in {
                    "group_by": getattr(owner_constraints, "group_by", ""),
                    "top_n": getattr(owner_constraints, "top_n", None),
                    "active_table": active_table,
                    **subset_constraints,
                }.items()
                if value not in ("", None)
            },
            target_handle_kind=target_handle_kind,
            target_handle_id=target_handle_id,
            upstream_object_handle_ids=upstream_object_handle_ids,
            upstream_result_handle_ids=upstream_result_handle_ids,
            owner_task_id=owner_task_id,
            arbitration_reason="handle_binding_followup",
        )
        query_understanding = QueryUnderstanding(
            intent="structured_followup_query",
            source_kind="dataset",
            task_kind="structured_data",
            modality="table",
            route="worker",
            execution_posture="worker",
            direct_route_reason="handle_binding_dataset_worker",
            capability_requests=["dataset_analysis"],
            should_skip_rag=True,
            reasons=["handle_binding_followup", "handle_binding_dataset_worker"],
        )
        return QueryExecutionPlan(
            message=followup_query,
            history=list(history),
            memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
            query_understanding=query_understanding,
            structured_binding=structured_binding,
            execution_kind="worker",
            execution_posture="worker",
            worker_plan=WorkerExecutionPlan(
                worker_route="structured_data",
                request=request,
                expected_result="canonical",
                fallback_execution_kind="none",
                cutover_mode="primary",
            ),
            target_handle_kind=target_handle_kind,
            target_handle_id=target_handle_id,
            upstream_object_handle_ids=upstream_object_handle_ids,
            upstream_result_handle_ids=upstream_result_handle_ids,
            arbitration_reason="handle_binding_followup",
        )

    def resolved_task_id(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_task_id", "")
            or getattr(followup_resolution, "task_id", "")
            or ""
        ).strip()

    def resolved_task_ids(self, followup_resolution) -> list[str]:
        task_ids = list(getattr(followup_resolution, "resolved_task_ids", []) or [])
        if not task_ids:
            task_ids = list(getattr(followup_resolution, "task_ids", []) or [])
        return [str(task_id or "").strip() for task_id in task_ids if str(task_id or "").strip()]

    def resolved_binding_kind(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_binding_kind", "")
            or getattr(followup_resolution, "binding_kind", "")
            or getattr(followup_resolution, "binding_key", "")
            or ""
        ).strip()

    def resolved_binding_identity(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_binding_identity", "")
            or getattr(followup_resolution, "binding_identity", "")
            or getattr(followup_resolution, "resolved_binding_ref", "")
            or ""
        ).strip()

    def resolved_binding_owner_task_id(self, followup_resolution) -> str:
        return str(
            getattr(followup_resolution, "resolved_binding_owner_task_id", "")
            or getattr(followup_resolution, "binding_owner_task_id", "")
            or ""
        ).strip()

    async def stream_binding_followup(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        *,
        followup_resolution,
        trace=None,
        stream_planned_execution: Callable[..., AsyncIterator[dict[str, Any]]],
        build_followup_main_context: Callable[..., Any],
        assemble_subtask_results: Callable[..., str],
        task_summary_refs_from_results: Callable[[list[dict[str, object]]], list[TaskSummaryRef]],
    ) -> AsyncIterator[dict[str, Any]]:
        owner_task = self.binding_owner_task(session_id, followup_resolution)
        if trace is not None:
            trace.annotate(
                {
                    "app.route": "followup_binding",
                    "app.binding_owner_task_id": str(getattr(owner_task, "task_id", "") or ""),
                    "app.followup_resolution_scope": str(getattr(followup_resolution, "resolution_scope", "") or ""),
                }
            )
        execution = self.binding_execution_from_resolution(
            session_id=session_id,
            message=message,
            history=history,
            followup_resolution=followup_resolution,
        )
        if execution is None:
            return
        async for event in stream_planned_execution(session_id, execution, trace=trace):
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
            followup_results = self.followup_results_from_task_ids(session_id, task_ids)
            if not followup_results:
                synthetic_result = self.followup_result_from_done_event(event, fallback_query=message)
                if synthetic_result is not None:
                    followup_results = [synthetic_result]
            if followup_results:
                resolved_followup_task_id = (
                    task_ids[-1]
                    if task_ids
                    else str(event.get("task_id", "") or self.resolved_task_id(followup_resolution)).strip()
                )
                resolved_followup_task_ids = (
                    list(task_ids)
                    if task_ids
                    else [resolved_followup_task_id] if resolved_followup_task_id else self.resolved_task_ids(followup_resolution)
                )
                synthetic_resolution = followup_resolution.model_copy(
                    update={
                        "task_id": resolved_followup_task_id,
                        "resolved_task_id": resolved_followup_task_id,
                        "task_ids": resolved_followup_task_ids,
                        "resolved_task_ids": resolved_followup_task_ids,
                        "owner_task_id": resolved_followup_task_id,
                        "object_handle_id": str(event.get("object_handle_ids", [None])[0] or ""),
                        "object_handle_ids": list(event.get("object_handle_ids", []) or []),
                        "result_handle_id": str(event.get("result_handle_ids", [None])[0] or ""),
                        "result_handle_ids": list(event.get("result_handle_ids", []) or []),
                        "subset_handle_id": str(dict(event.get("main_context") or {}).get("active_subset_handle_id", "") or ""),
                    }
                )
                main_context = build_followup_main_context(
                    message,
                    followup_results,
                    followup_resolution=synthetic_resolution,
                )
                event["main_context"] = main_context.to_dict()
                event["content"] = assemble_subtask_results(
                    followup_results,
                    main_context=main_context,
                )
                if not task_summary_payloads:
                    followup_task_refs = task_summary_refs_from_results(followup_results)
                    if not followup_task_refs:
                        followup_task_refs = [
                            synthetic_ref
                            for synthetic_ref in [
                                self.synthesize_followup_task_summary_ref(
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

    def build_followup_main_context(
        self,
        message: str,
        results: list[dict[str, object]],
        *,
        followup_resolution,
        extract_active_constraints: Callable[[str], dict[str, Any]],
        merge_constraints_from_results: Callable[[dict[str, Any], list[dict[str, object]]], dict[str, Any]],
        binding_identity_from_constraints: Callable[[dict[str, Any]], str],
        extract_latest_correction: Callable[[str], str],
    ) -> MainContextState:
        constraints = extract_active_constraints(message)
        target_task_ids = self.resolved_task_ids(followup_resolution)
        target_task_id = self.resolved_task_id(followup_resolution) or (target_task_ids[0] if target_task_ids else "")
        work_item = "followup_task_result_assembly"
        if followup_resolution.mode == "explicit_fanout_subset":
            work_item = "followup_explicit_fanout_subset_assembly"
        elif followup_resolution.mode == "bundle_subset":
            work_item = "followup_bundle_subset_assembly"
        elif followup_resolution.mode == "bundle_item_ref":
            work_item = "followup_bundle_item_result"
        elif followup_resolution.mode == "binding_ref":
            work_item = "followup_task_binding_execution"
        merged_constraints = merge_constraints_from_results(constraints, results)
        active_binding_identity = self.resolved_binding_identity(followup_resolution)
        if not active_binding_identity:
            active_binding_identity = binding_identity_from_constraints(merged_constraints)
        return MainContextState(
            active_goal=message.strip(),
            active_work_item=work_item,
            active_binding_identity=active_binding_identity,
            active_object_handle_id=str(getattr(followup_resolution, "object_handle_id", "") or ""),
            active_result_handle_id=str(getattr(followup_resolution, "result_handle_id", "") or ""),
            active_subset_handle_id=str(getattr(followup_resolution, "subset_handle_id", "") or ""),
            followup_mode=str(followup_resolution.mode or ""),
            followup_resolution_source=str(getattr(followup_resolution, "resolution_source", "") or ""),
            followup_target_task_id=target_task_id or None,
            followup_target_task_ids=target_task_ids,
            followup_binding_key=self.resolved_binding_kind(followup_resolution),
            followup_binding_identity=self.resolved_binding_identity(followup_resolution),
            followup_binding_owner_task_id=(self.resolved_binding_owner_task_id(followup_resolution) or None),
            active_constraints=merged_constraints,
            latest_correction=extract_latest_correction(message),
            next_step="answer_selected_task_results",
        )

    def _owner_object_handle_ids(self, owner_task) -> list[str]:
        metadata = dict(getattr(owner_task, "metadata", {}) or {})
        context_ref = getattr(owner_task, "context_ref", None)
        primary = str(getattr(context_ref, "primary_object_handle_id", "") or "").strip()
        handle_ids = [str(item).strip() for item in list(metadata.get("object_handle_ids", []) or []) if str(item).strip()]
        if primary and primary not in handle_ids:
            handle_ids.insert(0, primary)
        return handle_ids

    def _handle_context_from_resolution(self, followup_resolution, *, owner_task) -> tuple[str, str, list[str], list[str]]:
        object_handle_ids = [
            str(item).strip()
            for item in list(getattr(followup_resolution, "object_handle_ids", []) or [])
            if str(item).strip()
        ]
        object_handle_id = str(getattr(followup_resolution, "object_handle_id", "") or "").strip()
        if object_handle_id and object_handle_id not in object_handle_ids:
            object_handle_ids.insert(0, object_handle_id)
        if not object_handle_ids and owner_task is not None:
            object_handle_ids = self._owner_object_handle_ids(owner_task)

        result_handle_ids = [
            str(item).strip()
            for item in list(getattr(followup_resolution, "result_handle_ids", []) or [])
            if str(item).strip()
        ]
        result_handle_id = str(getattr(followup_resolution, "result_handle_id", "") or "").strip()
        if result_handle_id and result_handle_id not in result_handle_ids:
            result_handle_ids.insert(0, result_handle_id)
        if not result_handle_ids and owner_task is not None:
            result_handle_ids = self._owner_result_handle_ids(owner_task)

        subset_handle_id = str(getattr(followup_resolution, "subset_handle_id", "") or "").strip()
        if subset_handle_id:
            return "subset", subset_handle_id, object_handle_ids, result_handle_ids
        if result_handle_ids:
            return "result", result_handle_ids[0], object_handle_ids, result_handle_ids
        if object_handle_ids:
            return "object", object_handle_ids[0], object_handle_ids, result_handle_ids
        if owner_task is not None:
            return self._target_handle_kind(owner_task), self._target_handle_id(owner_task), object_handle_ids, result_handle_ids
        return "binding", self.resolved_binding_identity(followup_resolution), object_handle_ids, result_handle_ids

    def _owner_result_handle_ids(self, owner_task) -> list[str]:
        context_ref = getattr(owner_task, "context_ref", None)
        result_ref = getattr(owner_task, "result_ref", None)
        primary = str(
            getattr(result_ref, "primary_result_handle_id", "")
            or getattr(context_ref, "primary_result_handle_id", "")
            or ""
        ).strip()
        handle_ids = [
            str(item).strip()
            for item in list(getattr(result_ref, "result_handle_ids", []) or getattr(context_ref, "result_handle_ids", []) or [])
            if str(item).strip()
        ]
        if primary and primary not in handle_ids:
            handle_ids.insert(0, primary)
        return handle_ids

    def _target_handle_kind(self, owner_task) -> str:
        result_ref = getattr(owner_task, "result_ref", None)
        context_ref = getattr(owner_task, "context_ref", None)
        if str(getattr(result_ref, "subset_handle_id", "") or getattr(context_ref, "active_subset_handle_id", "") or "").strip():
            return "subset"
        if str(getattr(result_ref, "primary_result_handle_id", "") or getattr(context_ref, "primary_result_handle_id", "") or "").strip():
            return "result"
        if str(getattr(context_ref, "primary_object_handle_id", "") or "").strip():
            return "object"
        return "task"

    def _target_handle_id(self, owner_task) -> str:
        result_ref = getattr(owner_task, "result_ref", None)
        context_ref = getattr(owner_task, "context_ref", None)
        for value in (
            getattr(result_ref, "subset_handle_id", ""),
            getattr(context_ref, "active_subset_handle_id", ""),
            getattr(result_ref, "primary_result_handle_id", ""),
            getattr(context_ref, "primary_result_handle_id", ""),
            getattr(context_ref, "primary_object_handle_id", ""),
            getattr(owner_task, "task_id", ""),
        ):
            normalized = str(value or "").strip()
            if normalized:
                return normalized
        return ""

    def _pdf_constraints_from_message(self, message: str, *, active_pdf: str) -> dict[str, object]:
        page = self._page_number_from_message(message)
        constraints: dict[str, object] = {"active_pdf": active_pdf}
        if page is not None:
            constraints["mode"] = "page"
            constraints["page"] = page
            return constraints
        constraints["mode"] = "document"
        return constraints

    def _page_number_from_message(self, message: str) -> int | None:
        text = str(message or "")
        match = re.search(r"第\s*(\d+)\s*页", text, flags=re.IGNORECASE)
        if match:
            return _positive_int(match.group(1))
        match = re.search(r"page\s*(\d+)", text, flags=re.IGNORECASE)
        if match:
            return _positive_int(match.group(1))
        chinese_match = re.search(r"第\s*([零一二三四五六七八九十两]+)\s*页", text)
        if chinese_match:
            return _chinese_page_number(chinese_match.group(1))
        return None

    def _dataset_followup_query(self, message: str, owner_task) -> str:
        result_ref = getattr(owner_task, "result_ref", None)
        subset_hint_query = str(getattr(result_ref, "subset_hint_query", "") or "").strip()
        if not subset_hint_query:
            return message
        return f"{subset_hint_query} {message}".strip()

    def _dataset_subset_constraints(self, owner_task) -> dict[str, object]:
        result_ref = getattr(owner_task, "result_ref", None)
        subset_filter_column = str(getattr(result_ref, "subset_filter_column", "") or "").strip()
        subset_labels = [
            str(item or "").strip()
            for item in list(getattr(result_ref, "subset_labels", []) or [])
            if str(item or "").strip()
        ]
        if not subset_filter_column or not subset_labels:
            return {}
        return {
            "subset_filter_column": subset_filter_column,
            "subset_labels": subset_labels,
        }


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _chinese_page_number(value: str) -> int | None:
    normalized = str(value or "").strip().replace("两", "二")
    if not normalized:
        return None
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if normalized in digits:
        return digits[normalized]
    if normalized == "十":
        return 10
    if normalized.startswith("十") and len(normalized) == 2:
        ones = digits.get(normalized[1])
        return 10 + ones if ones is not None else None
    if "十" in normalized:
        tens_raw, ones_raw = normalized.split("十", 1)
        tens = digits.get(tens_raw)
        if tens is None:
            return None
        ones = digits.get(ones_raw, 0) if ones_raw else 0
        return tens * 10 + ones
    return None
