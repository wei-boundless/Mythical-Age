from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact_system.artifact_authority import (
    artifact_materialization_ref,
    artifact_ref_value,
    dedupe_artifact_refs,
    normalize_artifact_ref,
)
from task_system.runtime_semantics.quality_gates import stage_business_acceptance
from task_system.runtime_semantics.chapter_progress import (
    ChapterProgressReceiptError,
    normalize_chapter_progress_receipt,
)

from .models import GraphHarnessConfig, GraphNodeWorkOrder, NodeResultEnvelope, safe_id, stable_safe_id
from .model_overrides import sanitize_runtime_overrides, work_order_with_model_overrides
from .output_policy import resolve_output_policy
from .runtime_objects import node_result_summary, work_order_summary


@dataclass(frozen=True, slots=True)
class GraphWorkOrderExecution:
    work_order: GraphNodeWorkOrder
    node_result: NodeResultEnvelope
    task_run: Any | None = None
    executor_result: dict[str, Any] | None = None
    events: tuple[dict[str, Any], ...] = ()


class GraphNodeWorkOrderExecutor:
    """Executes graph work orders through the new graph harness contract."""

    def __init__(self, *, services: Any) -> None:
        self._services = services

    async def execute(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder | dict[str, Any],
        max_steps: int = 12,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> GraphWorkOrderExecution:
        order = work_order if isinstance(work_order, GraphNodeWorkOrder) else GraphNodeWorkOrder.from_dict(dict(work_order or {}))
        order, model_override_diagnostics = work_order_with_model_overrides(
            graph_config=graph_config,
            work_order=order,
            runtime_overrides=sanitize_runtime_overrides(runtime_overrides or {}),
        )
        if order.structure_hash and order.structure_hash != graph_config.expected_structural_hash():
            raise ValueError("GraphNodeWorkOrder structure_hash does not match GraphHarnessConfig")
        if not _graph_node_by_id(graph_config, order.node_id):
            raise ValueError("GraphNodeWorkOrder node_id not found in GraphHarnessConfig")
        if order.work_kind == "agent":
            return await self._execute_agent_node(
                graph_config=graph_config,
                work_order=order,
                max_steps=max_steps,
                model_override_diagnostics=model_override_diagnostics,
            )
        if order.work_kind == "human_gate":
            return self._unsupported_executor_result(
                graph_config=graph_config,
                work_order=order,
                reason="human_gate_requires_external_decision",
            )
        if order.work_kind == "tool":
            return self._unsupported_executor_result(
                graph_config=graph_config,
                work_order=order,
                reason="graph_tool_node_executor_not_connected",
            )
        return self._unsupported_executor_result(
            graph_config=graph_config,
            work_order=order,
            reason=f"unsupported_graph_work_kind:{order.work_kind}",
        )

    async def _execute_agent_node(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
        max_steps: int,
        model_override_diagnostics: dict[str, Any] | None = None,
    ) -> GraphWorkOrderExecution:
        executor = self._services.execute_graph_agent_work_order_callback
        if not callable(executor):
            return self._unsupported_executor_result(
                graph_config=graph_config,
                work_order=work_order,
                reason="graph_agent_work_order_executor_unavailable",
            )
        executor_result = await executor(
            graph_config=graph_config,
            work_order=work_order,
            max_steps=max(1, int(max_steps or 12)),
        )
        task_run_payload = dict(dict(executor_result or {}).get("task_run") or {})
        result = self._node_result_from_agent_execution(
            graph_config=graph_config,
            work_order=work_order,
            task_run_id=str(task_run_payload.get("task_run_id") or ""),
            executor_result=dict(executor_result or {}),
            model_override_diagnostics=dict(model_override_diagnostics or {}),
        )
        event = self._services.event_log.append(
            work_order.task_run_id,
            "graph_node_work_order_executed",
            payload={
                "graph_run_id": work_order.graph_run_id,
                "node_id": work_order.node_id,
                "work_order": work_order_summary(work_order),
                "node_executor_task_run_id": str(task_run_payload.get("task_run_id") or ""),
                "node_result": node_result_summary(result),
                "executor_result": _public_executor_result(executor_result),
            },
            refs={
                "graph_run_ref": work_order.graph_run_id,
                "graph_harness_config_ref": graph_config.config_id,
                "node_ref": work_order.node_id,
                "work_order_ref": work_order.work_order_id,
                "node_executor_task_run_ref": str(task_run_payload.get("task_run_id") or ""),
            },
        )
        return GraphWorkOrderExecution(
            work_order=work_order,
            node_result=result,
            task_run=task_run_payload,
            executor_result=dict(executor_result or {}),
            events=(event.to_dict(),),
        )

    def _node_result_from_agent_execution(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
        task_run_id: str,
        executor_result: dict[str, Any],
        model_override_diagnostics: dict[str, Any] | None = None,
    ) -> NodeResultEnvelope:
        ok = bool(executor_result.get("ok") is True)
        task_run_payload = dict(executor_result.get("task_run") or {})
        if not ok:
            return _agent_execution_not_ok_result(
                graph_config=graph_config,
                work_order=work_order,
                task_run_id=task_run_id,
                executor_result=executor_result,
                task_run_payload=task_run_payload,
            )
        final_answer = str(executor_result.get("final_answer") or task_run_payload.get("diagnostics", {}).get("final_answer") or "")
        artifact_refs = _artifact_refs_from_executor_result(executor_result, task_run_payload=task_run_payload)
        model_output_payload = _model_output_payload(final_answer=final_answer, task_run_payload=task_run_payload)
        contract_artifact_refs, contract_artifact_errors = _contract_artifact_refs_from_final_content(
            final_answer=final_answer,
            model_output_payload=model_output_payload,
            services=self._services,
            graph_config=graph_config,
            work_order=work_order,
        )
        artifact_refs = dedupe_artifact_refs([*artifact_refs, *contract_artifact_refs])
        artifact_receipts, artifact_errors = _artifact_materialization_receipts(
            artifact_refs,
            services=self._services,
            graph_config=graph_config,
            work_order=work_order,
            task_run_id=task_run_id,
        )
        memory_candidates, memory_receipts, memory_errors = _formal_memory_receipts(
            services=self._services,
            graph_config=graph_config,
            work_order=work_order,
            task_run_id=task_run_id,
            task_run_payload=task_run_payload,
            artifact_refs=artifact_refs,
        )
        structured_outputs = _structured_agent_outputs(task_run_payload)
        progress_receipts, progress_errors = _progress_receipts_from_structured_outputs(
            structured_outputs,
            graph_config=graph_config,
            work_order=work_order,
        )
        postprocess_errors = [*contract_artifact_errors, *artifact_errors, *memory_errors, *progress_errors]
        result_status = "completed" if ok and not postprocess_errors else "failed"
        quality_acceptance = _node_quality_acceptance(
            graph_config=graph_config,
            work_order=work_order,
            final_answer=final_answer,
            artifact_refs=artifact_refs,
            result_status=result_status,
        )
        quality_gate_failed = bool(result_status == "completed" and quality_acceptance and not bool(quality_acceptance.get("accepted")))
        quality_soft_pass = _quality_failure_soft_passes(
            graph_config=graph_config,
            work_order=work_order,
            quality_acceptance=quality_acceptance,
        )
        if quality_soft_pass:
            quality_acceptance = {
                **quality_acceptance,
                "accepted": True,
                "business_accepted": True,
                "quality_gate_soft_pass": True,
                "quality_gate_soft_pass_reason": "quality_retry_limit_exhausted_for_metric_only_failure",
                "authority": "harness.graph.work_order_executor.quality_gate_soft_pass",
            }
            quality_gate_failed = False
        has_quality_repair_route = bool(
            result_status == "completed" and quality_gate_failed and _has_quality_repair_route(graph_config, work_order.node_id)
        )
        recoverable_quality_failure = bool(
            result_status == "completed"
            and quality_gate_failed
            and not has_quality_repair_route
            and _quality_failure_requeues_same_node(graph_config=graph_config, work_order=work_order)
        )
        effective_result_status = (
            "completed"
            if has_quality_repair_route
            else ("blocked" if recoverable_quality_failure else ("failed" if quality_gate_failed else result_status))
        )
        result_error = (
            _node_result_error(
                executor_result=executor_result,
                task_run_payload=task_run_payload,
                postprocess_errors=postprocess_errors,
                quality_acceptance=quality_acceptance,
                recoverable=bool(recoverable_quality_failure),
            )
            if result_status != "completed" or quality_gate_failed
            else {}
        )
        return NodeResultEnvelope(
            result_id=f"nresult:{stable_safe_id(work_order.graph_run_id)}:{stable_safe_id(work_order.node_id)}:{stable_safe_id(work_order.work_order_id)}",
            graph_run_id=work_order.graph_run_id,
            task_run_id=work_order.task_run_id,
            node_id=work_order.node_id,
            work_order_id=work_order.work_order_id,
            executor_type=work_order.executor_type,
            status=effective_result_status,
            outputs={
                "node_executor_task_run_id": task_run_id,
                "executor_status": str(task_run_payload.get("status") or ("completed" if ok else "failed")),
                "artifact_refs": artifact_refs,
                **structured_outputs,
            },
            artifact_refs=tuple(artifact_ref_value(item) for item in artifact_refs if artifact_ref_value(item)),
            memory_candidates=tuple(memory_candidates),
            progress_receipts=tuple(progress_receipts),
            artifact_materialization_receipts=tuple(artifact_receipts),
            memory_commit_receipts=tuple(memory_receipts),
            handoff_summary=final_answer[:1200],
            error=result_error,
            diagnostics={
                "authority": "harness.graph.work_order_executor.agent_result",
                "graph_harness_config_id": graph_config.config_id,
                "node_executor_task_run_id": task_run_id,
                "executor_result": _public_executor_result(executor_result),
                "formal_postprocess_errors": postprocess_errors,
                **({"quality_acceptance": quality_acceptance} if quality_acceptance else {}),
                **({"quality_gate_soft_pass": True} if quality_soft_pass else {}),
                **({"graph_model_override": dict(model_override_diagnostics or {})} if model_override_diagnostics else {}),
            },
            created_at=time.time(),
        )

    def _unsupported_executor_result(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
        reason: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> GraphWorkOrderExecution:
        result = NodeResultEnvelope(
            result_id=f"nresult:{stable_safe_id(work_order.graph_run_id)}:{stable_safe_id(work_order.node_id)}:{stable_safe_id(work_order.work_order_id)}:unsupported",
            graph_run_id=work_order.graph_run_id,
            task_run_id=work_order.task_run_id,
            node_id=work_order.node_id,
            work_order_id=work_order.work_order_id,
            executor_type=work_order.executor_type,
            status="waiting_human_gate" if work_order.work_kind == "human_gate" else "blocked",
            outputs={},
            error={"reason": reason},
            diagnostics={
                "authority": "harness.graph.work_order_executor.unsupported",
                "graph_harness_config_id": graph_config.config_id,
                **dict(diagnostics or {}),
            },
            created_at=time.time(),
        )
        return GraphWorkOrderExecution(work_order=work_order, node_result=result)


def _agent_execution_not_ok_result(
    *,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    task_run_id: str,
    executor_result: dict[str, Any],
    task_run_payload: dict[str, Any],
) -> NodeResultEnvelope:
    status = _agent_node_result_status_for_not_ok_execution(
        executor_result=executor_result,
        task_run_payload=task_run_payload,
    )
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    recoverable_error = dict(diagnostics.get("recoverable_error") or {})
    reason = str(
        executor_result.get("error")
        or task_run_payload.get("terminal_reason")
        or recoverable_error.get("error_code")
        or ("node_executor_blocked" if status == "blocked" else "node_executor_failed")
    )
    return NodeResultEnvelope(
        result_id=f"nresult:{stable_safe_id(work_order.graph_run_id)}:{stable_safe_id(work_order.node_id)}:{stable_safe_id(work_order.work_order_id)}",
        graph_run_id=work_order.graph_run_id,
        task_run_id=work_order.task_run_id,
        node_id=work_order.node_id,
        work_order_id=work_order.work_order_id,
        executor_type=work_order.executor_type,
        status=status,
        outputs={
            "node_executor_task_run_id": task_run_id,
            "executor_status": str(task_run_payload.get("status") or status),
            "artifact_refs": [],
        },
        error={
            "reason": reason,
            **({"recoverable_error": recoverable_error} if recoverable_error else {}),
        },
        diagnostics={
            "authority": "harness.graph.work_order_executor.agent_result",
            "graph_harness_config_id": graph_config.config_id,
            "node_executor_task_run_id": task_run_id,
            "executor_result": _public_executor_result(executor_result),
            "formal_postprocess_errors": [],
        },
        created_at=time.time(),
    )


def _agent_node_result_status_for_not_ok_execution(
    *,
    executor_result: dict[str, Any],
    task_run_payload: dict[str, Any],
) -> str:
    task_status = str(task_run_payload.get("status") or "").strip()
    terminal_reason = str(task_run_payload.get("terminal_reason") or executor_result.get("error") or "").strip()
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    recoverable_error = dict(diagnostics.get("recoverable_error") or {})
    if task_status in {"blocked", "waiting_executor", "waiting_approval"}:
        return "blocked"
    if terminal_reason in {
        "model_call_recovery_required",
        "task_execution_step_budget_exhausted",
        "task_execution_step_budget_exceeded",
        "waiting_executor",
        "user_input_required",
        "agent_blocked",
    }:
        return "blocked"
    if recoverable_error and bool(recoverable_error.get("retryable", True)):
        return "blocked"
    return "failed"


def _artifact_refs_from_executor_result(executor_result: dict[str, Any], *, task_run_payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in list(executor_result.get("artifact_refs") or []):
        refs.append(normalize_artifact_ref(item))
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    for item in list(diagnostics.get("artifact_refs") or []):
        refs.append(normalize_artifact_ref(item))
    return dedupe_artifact_refs(refs)


def _contract_artifact_refs_from_final_content(
    *,
    final_answer: str,
    model_output_payload: dict[str, Any],
    services: Any,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved_output_policy = resolve_output_policy(graph_config=graph_config, work_order=work_order)
    if bool(resolved_output_policy.get("no_artifact_output") is True):
        return [], []
    artifacts = [dict(item) for item in list(resolved_output_policy.get("artifact_targets") or []) if isinstance(item, dict)]
    if not artifacts:
        return [], []
    values = _artifact_template_values(graph_config=graph_config, work_order=work_order)
    root = _contract_artifact_root(policy=resolved_output_policy, services=services, graph_config=graph_config, work_order=work_order, values=values)
    if root is None:
        required = any(bool(item.get("required")) for item in artifacts)
        if required:
            return [], [{"reason": "contract_artifact_root_unresolved", "authority": "harness.graph.contract_artifact_materializer"}]
        return [], []

    refs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for artifact in artifacts:
        raw_path = str(artifact.get("path") or artifact.get("artifact_path") or artifact.get("naming_rule") or "").strip()
        if not raw_path:
            if artifact.get("required"):
                errors.append(
                    {
                        "reason": "contract_artifact_path_missing",
                        "authority": "harness.graph.contract_artifact_materializer",
                    }
                )
            continue
        rendered_path = _render_artifact_template(raw_path, values).replace("\\", "/").lstrip("/")
        content_source = str(artifact.get("content_source") or resolved_output_policy.get("primary_content_key") or "final_answer").strip()
        content = _artifact_content_for_source(
            content_source=content_source,
            final_answer=final_answer,
            model_output_payload=model_output_payload,
        )
        if not content and bool(artifact.get("fallback_to_full_content")):
            content = str(final_answer or "").strip()
        if not content:
            if artifact.get("required"):
                errors.append(
                    {
                        "reason": "contract_artifact_content_missing",
                        "path": raw_path,
                        "content_source": content_source,
                        "authority": "harness.graph.contract_artifact_materializer",
                    }
                )
            continue
        target = _resolve_artifact_target(root=root, relative_path=rendered_path)
        if target is None:
            errors.append(
                {
                    "reason": "contract_artifact_path_outside_root",
                    "path": rendered_path,
                    "authority": "harness.graph.contract_artifact_materializer",
                }
            )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_normalize_artifact_text(content), encoding="utf-8")
        workspace_root = _workspace_root_from_services(services)
        artifact_ref = _relative_to_workspace(target, workspace_root=workspace_root)
        refs.append(
            {
                "artifact_ref": artifact_ref,
                "path": artifact_ref,
                "created_file": artifact_ref,
                "absolute_path": str(target),
                "content_source": content_source,
                "source": "graph_contract_artifact_policy",
                "authority": "harness.graph.contract_artifact_materializer",
            }
        )
    return dedupe_artifact_refs(refs), errors


def _public_executor_result(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(result or {})
    return {
        "ok": bool(payload.get("ok") is True),
        "error": str(payload.get("error") or ""),
        "artifact_refs": dedupe_artifact_refs([normalize_artifact_ref(item) for item in list(payload.get("artifact_refs") or [])]),
        "task_run": _task_run_summary(payload.get("task_run")),
        "event": _event_summary(payload.get("event")),
        "lifecycle": _lifecycle_summary(payload.get("lifecycle")),
    }


def _structured_agent_outputs(task_run_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    final_action_diagnostics = dict(diagnostics.get("final_action_diagnostics") or {})
    allowed_keys = (
        "semantic_evidence",
        "monitor_verdict",
        "structured_output",
        "node_output",
    )
    outputs: dict[str, Any] = {}
    for key in allowed_keys:
        value = final_action_diagnostics.get(key)
        if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
            if value is not None:
                outputs[key] = value
    return outputs


def _progress_receipts_from_structured_outputs(
    structured_outputs: dict[str, Any],
    *,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    policy = _progress_receipt_policy(graph_config=graph_config, work_order=work_order)
    if not policy:
        return [], []
    key = str(policy.get("progress_receipt_key") or "chapter_progress_receipt").strip()
    source = _structured_output_source(structured_outputs)
    candidate = source.get(key)
    if not isinstance(candidate, dict):
        return [], [
            {
                "reason": "chapter_progress_receipt_missing",
                "node_id": work_order.node_id,
                "progress_receipt_key": key,
                "authority": "harness.graph.progress_receipt_postprocess",
            }
        ]
    try:
        receipt = normalize_chapter_progress_receipt(
            candidate,
            initial_inputs=dict(dict(work_order.input_package or {}).get("initial_inputs") or work_order.explicit_inputs or {}),
        )
    except ChapterProgressReceiptError as exc:
        return [], [
            {
                "reason": "chapter_progress_receipt_invalid",
                "detail": str(exc),
                "node_id": work_order.node_id,
                "progress_receipt_key": key,
                "authority": "harness.graph.progress_receipt_postprocess",
            }
        ]
    return [receipt], []


def _structured_output_source(structured_outputs: dict[str, Any]) -> dict[str, Any]:
    payload = dict(structured_outputs or {})
    for key in ("structured_output", "node_output"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return {**payload, **dict(nested)}
    return payload


def _progress_receipt_policy(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    node = next((dict(item) for item in graph_config.nodes if str(item.get("node_id") or "") == work_order.node_id), {})
    metadata = dict(node.get("metadata") or {})
    policy = dict(node.get("progress_receipt_policy") or metadata.get("progress_receipt_policy") or {})
    if policy:
        return policy
    bindings = dict(dict(node.get("contracts") or {}).get("contract_bindings") or {})
    progress = dict(bindings.get("progress") or {})
    if progress:
        return progress
    return {}


def _task_run_summary(task_run: Any | None) -> dict[str, Any]:
    payload = task_run.to_dict() if hasattr(task_run, "to_dict") else (dict(task_run) if isinstance(task_run, dict) else {})
    diagnostics = dict(payload.get("diagnostics") or {})
    origin = dict(diagnostics.get("origin") or {})
    return {
        "task_run_id": str(payload.get("task_run_id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "task_id": str(payload.get("task_id") or ""),
        "status": str(payload.get("status") or ""),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "origin_kind": str(origin.get("origin_kind") or diagnostics.get("origin_kind") or ""),
        "graph_run_id": str(diagnostics.get("graph_run_id") or ""),
        "graph_work_order_id": str(diagnostics.get("graph_work_order_id") or ""),
        "graph_node_id": str(diagnostics.get("graph_node_id") or ""),
        "project_id": str(diagnostics.get("project_id") or ""),
        "runtime_scope": dict(diagnostics.get("runtime_scope") or {}),
    }


def _lifecycle_summary(lifecycle: Any | None) -> dict[str, Any]:
    payload = lifecycle.to_dict() if hasattr(lifecycle, "to_dict") else (dict(lifecycle) if isinstance(lifecycle, dict) else {})
    return {
        "task_run_id": str(payload.get("task_run_id") or ""),
        "contract_ref": str(payload.get("contract_ref") or ""),
        "status": str(payload.get("status") or ""),
        "created_at": payload.get("created_at", 0.0),
        "updated_at": payload.get("updated_at", 0.0),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "acceptance_ref_count": len(list(payload.get("acceptance_refs") or [])),
        "observation_ref_count": len(list(payload.get("observation_refs") or [])),
        "authority": str(payload.get("authority") or "harness.loop.task_lifecycle"),
    }


def _event_summary(event: Any | None) -> dict[str, Any]:
    payload = event.to_dict() if hasattr(event, "to_dict") else (dict(event) if isinstance(event, dict) else {})
    return {
        "event_id": str(payload.get("event_id") or ""),
        "event_type": str(payload.get("event_type") or payload.get("type") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "created_at": payload.get("created_at", 0.0),
        "refs": dict(payload.get("refs") or {}),
        "authority": str(payload.get("authority") or ""),
    }


def _artifact_materialization_receipts(
    artifact_refs: list[dict[str, Any]],
    *,
    services: Any,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    task_run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not artifact_refs:
        return [], []
    service = getattr(services, "artifact_repository_service", None)
    if service is None:
        return [], [{"reason": "artifact_repository_service_unavailable", "authority": "harness.graph.artifact_postprocess"}]
    receipts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    artifact_policy = _artifact_repository_policy(graph_config=graph_config, work_order=work_order)
    refs = [artifact_materialization_ref(ref) for ref in artifact_refs]
    refs = [item for item in refs if item]
    if not refs:
        return [], []
    try:
        receipt = service.record_materialization(
            task_run_id=work_order.task_run_id,
            graph_id=graph_config.graph_id,
            graph_run_id=work_order.graph_run_id,
            stage_id=work_order.node_id,
            node_run_id=task_run_id or work_order.work_order_id,
            task_ref=work_order.task_ref,
            output_contract_id=str(dict(work_order.expected_result_contract or {}).get("output_contract_id") or ""),
            producer_node_id=work_order.node_id,
            artifact_refs=refs,
            created_files=[_created_file(ref) for ref in artifact_refs],
            artifact_root=_artifact_materialization_root(graph_config=graph_config, work_order=work_order),
            repository_id=str(artifact_policy.get("repository_id") or "artifact.repository.default"),
            collection_id=str(artifact_policy.get("collection_id") or "default"),
            lifecycle_policy=dict(artifact_policy.get("lifecycle_policy") or {}),
            status="accepted",
            metadata={
                "graph_harness_config_id": graph_config.config_id,
                "work_order_id": work_order.work_order_id,
                "node_executor_task_run_id": task_run_id,
                "task_environment_id": str(graph_config.task_environment_id or ""),
                "source_authority": "harness.graph.work_order_executor",
            },
        )
        receipts.append(
            {
                **dict(receipt or {}),
                "receipt_id": f"artifact-receipt:{stable_safe_id(work_order.work_order_id)}:{stable_safe_id(str(dict(receipt or {}).get('materialization_id') or task_run_id))}",
                "status": "materialized",
                "task_environment_id": str(graph_config.task_environment_id or ""),
                "node_executor_task_run_id": task_run_id,
            }
        )
    except Exception as exc:
        errors.append(
            {
                "reason": "artifact_materialization_failed",
                "error": str(exc),
                "authority": "harness.graph.artifact_postprocess",
            }
        )
    return receipts, errors


def _formal_memory_receipts(
    *,
    services: Any,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    task_run_id: str,
    task_run_payload: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    service = getattr(services, "formal_memory_service", None)
    candidate_pool = _memory_candidates_from_task_run(task_run_payload)
    memory_edges = _memory_write_edges_for_work_order(graph_config=graph_config, work_order=work_order)
    if not candidate_pool and not memory_edges:
        return [], [], []
    if service is None:
        return candidate_pool, [], [{"reason": "formal_memory_service_unavailable", "authority": "harness.graph.memory_postprocess"}]
    receipts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    candidate_receipts: list[dict[str, Any]] = []
    for edge in memory_edges:
        declaration_error = _formal_memory_declaration_error(service=service, edge=edge, graph_config=graph_config, work_order=work_order, task_run_payload=task_run_payload)
        if declaration_error:
            errors.append(declaration_error)
            continue
        edge_candidates = _candidates_for_memory_edge(edge=edge, candidates=candidate_pool, task_run_payload=task_run_payload)
        if not edge_candidates:
            continue
        for candidate in edge_candidates:
            try:
                version, write_transaction = service.write_candidate_from_edge(
                    edge=_formal_memory_service_edge(edge),
                    candidate=candidate,
                    task_run_id=work_order.task_run_id,
                    graph_id=graph_config.graph_id,
                    node_run_id=task_run_id or work_order.work_order_id,
                    source_node_id=str(edge.get("source_node_id") or work_order.node_id),
                    source_clock=f"graph:{work_order.graph_run_id}",
                    source_clock_seq=_source_clock_seq(task_run_payload),
                    artifact_refs=list(_candidate_artifact_refs(candidate) or [artifact_materialization_ref(ref) for ref in artifact_refs]),
                    runtime_scope=_runtime_scope(graph_config=graph_config, work_order=work_order, task_run_payload=task_run_payload),
                )
                version_payload = version.to_dict() if hasattr(version, "to_dict") else dict(version or {})
                write_payload = write_transaction.to_dict() if hasattr(write_transaction, "to_dict") else dict(write_transaction or {})
                candidate_receipts.append(
                    {
                        "receipt_id": f"memory-candidate:{stable_safe_id(work_order.work_order_id)}:{stable_safe_id(str(version_payload.get('version_id') or 'candidate'))}",
                        "status": "candidate_recorded",
                        "operation": "memory_write_candidate",
                        "edge_id": str(edge.get("edge_id") or ""),
                        "candidate_version": version_payload,
                        "transaction": write_payload,
                        "memory_space_ref": str(work_order.memory_space_ref or ""),
                        "task_environment_id": str(graph_config.task_environment_id or ""),
                        "node_executor_task_run_id": task_run_id,
                        "authority": "formal_memory.service",
                    }
                )
                if _edge_commits_memory(edge=edge, graph_config=graph_config, work_order=work_order):
                    committed, commit_transaction = service.commit_from_edge(
                        edge=_formal_memory_service_edge(edge),
                        candidate_version_id=str(version_payload.get("version_id") or ""),
                        node_run_id=task_run_id or work_order.work_order_id,
                        source_clock=f"graph:{work_order.graph_run_id}",
                        source_clock_seq=_source_clock_seq(task_run_payload),
                        verdict=str(candidate.get("verdict") or ""),
                        required_verdict=str(edge.get("required_verdict") or ""),
                    )
                    receipts.append(
                        {
                            "receipt_id": f"memory-commit:{stable_safe_id(work_order.work_order_id)}:{stable_safe_id(str(version_payload.get('version_id') or 'commit'))}",
                            "status": "committed",
                            "operation": "memory_commit",
                            "edge_id": str(edge.get("edge_id") or ""),
                            "candidate_version": version_payload,
                            "committed_version": committed.to_dict() if hasattr(committed, "to_dict") else dict(committed or {}),
                            "transaction": commit_transaction.to_dict() if hasattr(commit_transaction, "to_dict") else dict(commit_transaction or {}),
                            "memory_space_ref": str(work_order.memory_space_ref or ""),
                            "task_environment_id": str(graph_config.task_environment_id or ""),
                            "node_executor_task_run_id": task_run_id,
                            "authority": "formal_memory.service",
                        }
                    )
            except Exception as exc:
                errors.append(
                    {
                        "reason": "formal_memory_write_failed",
                        "edge_id": str(edge.get("edge_id") or ""),
                        "error": str(exc),
                        "authority": "harness.graph.memory_postprocess",
                    }
                )
    return [*candidate_pool, *[dict(item.get("candidate_version") or {}) for item in candidate_receipts]], [*candidate_receipts, *receipts], errors


def _created_file(ref: dict[str, Any]) -> str:
    payload = dict(ref or {})
    return str(payload.get("created_file") or payload.get("filename") or payload.get("path") or payload.get("src") or "").replace("\\", "/").strip()


def _node_artifact_policy(work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    view = dict(work_order.artifact_view_request or {})
    node_policy = dict(view.get("node_artifact_policy") or {})
    if node_policy:
        return node_policy
    bindings = dict(dict(work_order.expected_result_contract or {}).get("contract_bindings") or {})
    artifact_binding = dict(bindings.get("artifact") or {})
    return dict(artifact_binding.get("artifact_policy") or artifact_binding)


def _contract_artifact_root(
    *,
    policy: dict[str, Any],
    services: Any,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    values: dict[str, Any],
) -> Path | None:
    workspace_root = _workspace_root_from_services(services)
    environment = dict(graph_config.environment or {})
    storage_space = dict(environment.get("storage_space") or {})
    environment_projection = dict(policy.get("environment_projection") or {})
    output_policy = dict(policy.get("output_policy") or {})
    artifact_materialization = dict(policy.get("artifact_materialization_policy") or {})
    raw_policy_root = str(
        artifact_materialization.get("artifact_root")
        or output_policy.get("artifact_root")
        or policy.get("artifact_root")
        or ""
    ).strip()
    environment_root = str(environment_projection.get("environment_artifact_root") or storage_space.get("artifact_root") or work_order.artifact_space_ref or "").strip()
    policy_root = "" if raw_policy_root.startswith("repo.") else raw_policy_root
    root_value = str(
        environment_root
        or policy_root
        or artifact_materialization.get("default_artifact_root")
        or output_policy.get("default_artifact_root")
        or policy.get("default_artifact_root")
        or policy.get("root")
        or ""
    ).strip()
    root = _resolve_inside_workspace(workspace_root=workspace_root, value=_render_artifact_template(root_value, values))
    if root is None:
        return None
    explicit_subdir = _artifact_subdir_from_explicit_root(work_order)
    subdir_template = explicit_subdir or str(
        artifact_materialization.get("subdir_template")
        or artifact_materialization.get("scope_template")
        or output_policy.get("subdir_template")
        or policy.get("subdir_template")
        or policy.get("scope_template")
        or ""
    ).strip()
    if subdir_template:
        subdir = _sanitize_relative_path(_render_artifact_template(subdir_template, values))
        if subdir:
            root = _resolve_artifact_target(root=root, relative_path=subdir) or root
    return root


def _explicit_artifact_root(work_order: GraphNodeWorkOrder) -> str:
    input_package = dict(work_order.input_package or {})
    initial_inputs = dict(input_package.get("initial_inputs") or {})
    values = [
        dict(work_order.explicit_inputs or {}).get("artifact_root"),
        initial_inputs.get("artifact_root"),
        dict(input_package.get("runtime_scope") or {}).get("artifact_root"),
    ]
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _artifact_subdir_from_explicit_root(work_order: GraphNodeWorkOrder) -> str:
    explicit_root = _explicit_artifact_root(work_order)
    if not explicit_root:
        return ""
    clean = _sanitize_relative_path(explicit_root)
    parts = [part for part in clean.split("/") if part]
    if len(parts) >= 3 and parts[:3] == ["frontend", "public", "games"]:
        return "/".join(parts[3:])
    if len(parts) >= 1 and parts[0] in {"storage", "frontend", "backend", "docs"}:
        return parts[-1]
    return clean


def _artifact_materialization_root(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> str:
    resolved = resolve_output_policy(graph_config=graph_config, work_order=work_order)
    environment_projection = dict(resolved.get("environment_projection") or {})
    artifact_materialization = dict(resolved.get("artifact_materialization_policy") or {})
    output_policy = dict(resolved.get("output_policy") or {})
    values = _artifact_template_values(graph_config=graph_config, work_order=work_order)
    raw_policy_root = str(artifact_materialization.get("artifact_root") or output_policy.get("artifact_root") or "").strip()
    policy_root = "" if raw_policy_root.startswith("repo.") else raw_policy_root
    return str(
        environment_projection.get("environment_artifact_root")
        or work_order.artifact_space_ref
        or _environment_artifact_root(graph_config)
        or _render_artifact_template(policy_root, values)
        or _render_artifact_template(str(artifact_materialization.get("default_artifact_root") or output_policy.get("default_artifact_root") or "").strip(), values)
    ).strip()


def _artifact_template_values(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    input_package = dict(work_order.input_package or {})
    loop_context = dict(input_package.get("loop_context") or {})
    active_frame = dict(loop_context.get("active_frame") or {})
    frame_values = dict(active_frame.get("values") or active_frame.get("state") or active_frame)
    runtime_scope = {
        **dict(input_package.get("runtime_scope") or {}),
        **dict(dict(work_order.graph_state or {}).get("runtime_scope") or {}),
        **dict(dict(work_order.dispatch_context or {}).get("runtime_scope") or {}),
    }
    initial_inputs = dict(input_package.get("initial_inputs") or {})
    values: dict[str, Any] = {
        **runtime_scope,
        **initial_inputs,
        **dict(work_order.explicit_inputs or {}),
        **frame_values,
        "graph_id": graph_config.graph_id,
        "graph_run_id": work_order.graph_run_id,
        "task_run_id": work_order.task_run_id,
        "node_id": work_order.node_id,
        "safe_graph_run_id": safe_id(work_order.graph_run_id),
        "safe_node_id": safe_id(work_order.node_id),
    }
    for key in ("round_index", "volume_index", "chapter_index", "unit_index", "group_index", "batch_index"):
        values[key] = _int_template_value(values.get(key), 1)
    project_id = str(values.get("project_id") or values.get("scope_id") or "").strip()
    if project_id:
        values.setdefault("project_slug", _safe_path_component(project_id))
    return values


def _model_output_payload(*, final_answer: str, task_run_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    final_action_diagnostics = dict(diagnostics.get("final_action_diagnostics") or {})
    return {
        "final_answer": str(final_answer or ""),
        "final_content": str(final_answer or ""),
        "full_content": str(final_answer or ""),
        "model_response": str(final_answer or ""),
        "diagnostics": diagnostics,
        "final_action_diagnostics": final_action_diagnostics,
        **final_action_diagnostics,
    }


def _artifact_content_for_source(*, content_source: str, final_answer: str, model_output_payload: dict[str, Any]) -> str:
    source = str(content_source or "").strip()
    if source in {"", "final_content", "final_answer", "full_content", "model_response"}:
        return str(final_answer or "").strip()
    value = _nested_lookup(dict(model_output_payload or {}), source)
    if isinstance(value, str):
        return value.strip()
    if value is not None:
        return str(value).strip()
    return ""


def _render_artifact_template(template: str, values: dict[str, Any]) -> str:
    text = str(template or "").strip()
    if not text:
        return ""
    try:
        return text.format_map(_ArtifactFormatValues(values))
    except Exception:
        return text


class _ArtifactFormatValues(dict):
    def __missing__(self, key: str) -> Any:
        return _MissingArtifactFormatValue(key)


class _MissingArtifactFormatValue:
    def __init__(self, key: str) -> None:
        self.key = key

    def __format__(self, _spec: str) -> str:
        return _safe_path_component(self.key)

    def __str__(self) -> str:
        return _safe_path_component(self.key)


def _resolve_artifact_target(*, root: Path, relative_path: str) -> Path | None:
    clean = _sanitize_relative_path(relative_path)
    if not clean:
        return None
    relative = Path(clean)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        return None
    resolved_root = root.resolve()
    target = (resolved_root / relative).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError:
        return None
    return target


def _resolve_inside_workspace(*, workspace_root: Path, value: str) -> Path | None:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        return None
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / raw.lstrip("/")).resolve()
    try:
        resolved.relative_to(workspace_root.resolve())
    except ValueError:
        return None
    return resolved


def _relative_to_workspace(path: Path, *, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _workspace_root_from_services(services: Any) -> Path:
    backend_dir = Path(getattr(services, "backend_dir", "") or ".").resolve()
    return backend_dir.parent if backend_dir.name == "backend" else backend_dir


def _sanitize_relative_path(value: str) -> str:
    parts = [
        _safe_path_component(part)
        for part in str(value or "").replace("\\", "/").split("/")
        if part not in {"", "."}
    ]
    return "/".join(part for part in parts if part)


def _safe_path_component(value: Any) -> str:
    text = str(value or "").strip()
    result = []
    for ch in text:
        if ch.isalnum() or ch in {"-", "_", "."} or "\u4e00" <= ch <= "\u9fff":
            result.append(ch)
        else:
            result.append("-")
    return "".join(result).strip("-") or "value"


def _normalize_artifact_text(content: str) -> str:
    text = str(content or "").strip()
    return text + "\n" if text else ""


def _int_template_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _artifact_repository_policy(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    resolved = resolve_output_policy(graph_config=graph_config, work_order=work_order)
    repository_policy = dict(resolved.get("artifact_repository_policy") or {})
    repository_id = str(repository_policy.get("repository_id") or "artifact.repository.default").strip()
    return {
        "repository_id": repository_id or "artifact.repository.default",
        "collection_id": str(repository_policy.get("collection_id") or "default").strip() or "default",
        "lifecycle_policy": dict(repository_policy.get("lifecycle_policy") or {}),
    }


def _environment_artifact_root(graph_config: GraphHarnessConfig) -> str:
    return str(dict(dict(graph_config.environment or {}).get("storage_space") or {}).get("artifact_root") or "").strip()


def _memory_candidates_from_task_run(task_run_payload: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    final_action_diagnostics = dict(diagnostics.get("final_action_diagnostics") or {})
    candidates: list[dict[str, Any]] = []
    for source in (diagnostics, final_action_diagnostics):
        for key in ("memory_candidates", "memory_commit_candidates"):
            for item in list(source.get(key) or []):
                if isinstance(item, dict):
                    candidates.append(dict(item))
    return _dedupe_candidates(candidates)


def _memory_write_edges_for_work_order(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    node_id = work_order.node_id
    executable_memory_commit_targets = {
        str(node.get("node_id") or "")
        for node in graph_config.nodes
        if str(node.get("node_type") or "") in {"memory_commit", "memory_finalize"}
    }
    for raw in graph_config.edges:
        edge = _normalize_memory_edge(raw)
        edge_type = str(edge.get("edge_type") or "")
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if edge_type not in {"memory_write", "memory_write_candidate", "memory_commit"}:
            continue
        if edge_type == "memory_commit" and target == node_id:
            edges.append({**edge, "commit_trigger": "target_commit_node_completed"})
            continue
        if source != node_id:
            continue
        if edge_type == "memory_commit" and target in executable_memory_commit_targets:
            continue
        edges.append({**edge, "commit_trigger": "source_node_completed"})
    return edges


def _normalize_memory_edge(raw_edge: dict[str, Any]) -> dict[str, Any]:
    edge = dict(raw_edge or {})
    metadata = dict(edge.get("metadata") or {})
    selector = dict(edge.get("selector") or metadata.get("selector") or {})
    edge_type = str(edge.get("edge_type") or metadata.get("memory_edge_type") or "").strip()
    record_kinds = _string_list(
        edge.get("record_kinds")
        or metadata.get("record_kinds")
        or selector.get("record_kinds")
        or selector.get("record_kind")
    )
    record_kind = str(
        edge.get("record_kind")
        or metadata.get("record_kind")
        or selector.get("record_kind")
        or (record_kinds[0] if record_kinds else "")
    ).strip()
    return {
        **edge,
        "edge_type": edge_type,
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "repository": str(edge.get("repository") or edge.get("repository_id") or metadata.get("repository") or metadata.get("repository_id") or metadata.get("repository_node_id") or "").strip(),
        "collection": str(edge.get("collection") or edge.get("collection_id") or metadata.get("collection") or selector.get("collection") or "").strip(),
        "selector": selector,
        "record_key": str(edge.get("record_key") or metadata.get("record_key") or selector.get("record_key") or "").strip(),
        "record_kind": record_kind,
        "record_kinds": record_kinds,
        "source_output_key": str(edge.get("source_output_key") or metadata.get("source_output_key") or selector.get("source_output_key") or "").strip(),
        "candidate_ref_key": str(edge.get("candidate_ref_key") or metadata.get("candidate_ref_key") or "").strip(),
        "verdict_key": str(edge.get("verdict_key") or metadata.get("verdict_key") or "").strip(),
        "required_verdict": str(edge.get("required_verdict") or metadata.get("required_verdict") or "").strip(),
        "lifecycle_policy": dict(edge.get("lifecycle_policy") or edge.get("resource_lifecycle_policy") or metadata.get("lifecycle_policy") or metadata.get("resource_lifecycle_policy") or {}),
        "commit_visibility_policy": dict(edge.get("commit_visibility_policy") or metadata.get("commit_visibility_policy") or metadata.get("visibility_policy") or {}),
        "content_requirement": dict(edge.get("content_requirement") or metadata.get("content_requirement") or metadata.get("memory_content_requirement") or {}),
        "metadata": metadata,
    }


def _candidates_for_memory_edge(*, edge: dict[str, Any], candidates: list[dict[str, Any]], task_run_payload: dict[str, Any]) -> list[dict[str, Any]]:
    source_output_key = str(edge.get("source_output_key") or "").strip()
    if source_output_key:
        value = _nested_lookup(_candidate_source_payload(task_run_payload), source_output_key)
        if value is not None:
            return _candidates_from_value(value, edge=edge)
        if bool(edge.get("require_source_output_key")):
            return []
    if candidates:
        return [_candidate_for_edge(candidate, edge=edge) for candidate in candidates]
    final_answer = str(dict(task_run_payload.get("diagnostics") or {}).get("final_answer") or "").strip()
    if final_answer and str(edge.get("edge_type") or "") == "memory_commit":
        return [_candidate_for_edge({"canonical_text": final_answer, "summary": final_answer[:240]}, edge=edge)]
    return []


def _candidate_source_payload(task_run_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    final_answer = str(diagnostics.get("final_answer") or "")
    return {
        **diagnostics,
        **dict(diagnostics.get("final_action_diagnostics") or {}),
        "final_answer": final_answer,
        "review_advisories": _review_advisory_candidates(final_answer),
        "review_blocking_issues": _review_blocking_issue_candidates(final_answer),
    }


def _candidates_from_value(value: Any, *, edge: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [_candidate_from_value(item, edge=edge) for item in value if item is not None]
    if isinstance(value, tuple):
        return [_candidate_from_value(item, edge=edge) for item in value if item is not None]
    return [_candidate_from_value(value, edge=edge)]


def _candidate_from_value(value: Any, *, edge: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return _candidate_for_edge(dict(value), edge=edge)
    text = str(value or "").strip()
    return _candidate_for_edge({"canonical_text": text, "summary": text[:240], "payload": {"value": value}}, edge=edge)


def _review_advisory_candidates(final_answer: str) -> list[dict[str, Any]]:
    text = str(final_answer or "").strip()
    if not text:
        return []
    if _review_verdict(text) not in {"通过", "带备注通过"}:
        return []
    section = _review_advisory_section(text)
    if not section:
        return []
    items = _numbered_review_items(section)
    if not items:
        items = [section] if _looks_like_non_blocking_advisory(section) else []
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        canonical = item.strip()
        if not canonical or not _looks_like_non_blocking_advisory(canonical):
            continue
        key = f"planning_advisory_{index:03d}_{safe_id(canonical[:48])}"
        candidates.append(
            {
                "record_key": key,
                "record_kind": "planning_advisory",
                "canonical_text": canonical,
                "summary": canonical[:240],
                "payload": {
                    "advisory_index": index,
                    "severity": "non_blocking",
                    "source": "review_report",
                    "content": canonical,
                    "authority": "harness.graph.review_advisory_extractor",
                },
                "metadata": {
                    "advisory_kind": "planning_advisory",
                    "blocking": False,
                    "authority": "harness.graph.review_advisory_extractor",
                },
            }
        )
    return candidates


def _review_blocking_issue_candidates(final_answer: str) -> list[dict[str, Any]]:
    text = str(final_answer or "").strip()
    if not text:
        return []
    verdict = _review_verdict(text)
    if verdict not in {"返修", "拒绝"} and not _contains_blocking_review_marker(text):
        return []
    return [
        {
            "record_key": "blocking_review_issue",
            "record_kind": "review_issue",
            "canonical_text": text,
            "summary": text[:240],
            "payload": {
                "severity": "blocking",
                "source": "review_report",
                "content": text,
                "authority": "harness.graph.review_issue_extractor",
            },
            "metadata": {
                "issue_kind": "review_issue",
                "blocking": True,
                "authority": "harness.graph.review_issue_extractor",
            },
        }
    ]


def _review_verdict(text: str) -> str:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("审核裁决："):
            return line.split("：", 1)[1].strip()
        break
    return ""


def _review_advisory_section(text: str) -> str:
    lines = str(text or "").splitlines()
    start = -1
    for index, raw_line in enumerate(lines):
        line = raw_line.strip().lstrip("#").strip()
        if any(marker in line for marker in ("潜在风险与建议", "非阻塞性", "审核备注", "可选轻微建议")):
            start = index + 1
            break
    if start < 0:
        return ""
    collected: list[str] = []
    for raw_line in lines[start:]:
        line = raw_line.strip()
        heading = line.lstrip("#").strip()
        if heading.startswith("是否允许进入下一阶段"):
            break
        if line.startswith("##") and collected:
            break
        collected.append(raw_line)
    return "\n".join(collected).strip()


def _numbered_review_items(section: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for raw_line in str(section or "").splitlines():
        line = raw_line.strip()
        if _starts_numbered_item(line) or line.startswith("- "):
            if current:
                items.append("\n".join(current).strip())
            current = [line]
            continue
        if current and line:
            current.append(line)
    if current:
        items.append("\n".join(current).strip())
    return items


def _starts_numbered_item(line: str) -> bool:
    head = line.split(" ", 1)[0].strip()
    if not head.endswith((".", "、")):
        return False
    return head[:-1].isdigit()


def _looks_like_non_blocking_advisory(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    blocking_markers = ("阻塞", "必须修改", "返修", "拒绝", "不允许进入下一阶段", "冻结前必须处理")
    if any(marker in value for marker in blocking_markers):
        return False
    advisory_markers = ("建议", "可在", "可进一步", "增加", "明确", "细化", "铺垫", "避免")
    return any(marker in value for marker in advisory_markers)


def _contains_blocking_review_marker(text: str) -> bool:
    markers = ("必须修改", "不允许进入下一阶段", "冻结前必须处理", "阻塞问题", "硬设定冲突")
    return any(marker in str(text or "") for marker in markers)


def _candidate_for_edge(candidate: dict[str, Any], *, edge: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate or {})
    record_key = str(payload.get("record_key") or edge.get("record_key") or "").strip()
    record_kind = str(payload.get("record_kind") or payload.get("kind") or edge.get("record_kind") or "").strip()
    canonical_text = str(
        payload.get("canonical_text")
        or dict(payload.get("payload") or {}).get("canonical_text")
        or dict(payload.get("payload") or {}).get("content")
        or dict(payload.get("payload") or {}).get("text")
        or payload.get("summary")
        or ""
    ).strip()
    summary = str(payload.get("summary") or canonical_text[:240]).strip()
    return {
        **payload,
        **({"record_key": record_key} if record_key else {}),
        **({"record_kind": record_kind, "kind": record_kind} if record_kind else {}),
        **({"canonical_text": canonical_text} if canonical_text else {}),
        **({"summary": summary} if summary else {}),
    }


def _formal_memory_service_edge(edge: dict[str, Any]) -> dict[str, Any]:
    selector = dict(edge.get("selector") or {})
    record_kinds = _string_list(edge.get("record_kinds") or selector.get("record_kinds"))
    return {
        **dict(edge or {}),
        "repository": str(edge.get("repository") or edge.get("repository_id") or "").strip(),
        "repository_id": str(edge.get("repository") or edge.get("repository_id") or "").strip(),
        "collection": str(edge.get("collection") or edge.get("collection_id") or "").strip(),
        "collection_id": str(edge.get("collection") or edge.get("collection_id") or "").strip(),
        "record_kinds": record_kinds,
        "selector": {
            **selector,
            **({"record_key": str(edge.get("record_key") or "")} if str(edge.get("record_key") or "") else {}),
            **({"record_kind": str(edge.get("record_kind") or "")} if str(edge.get("record_kind") or "") else {}),
            **({"record_kinds": record_kinds} if record_kinds else {}),
        },
        "lifecycle_policy": dict(edge.get("lifecycle_policy") or {}),
        "commit_visibility_policy": dict(edge.get("commit_visibility_policy") or {}),
        "content_requirement": dict(edge.get("content_requirement") or {}),
    }


def _formal_memory_declaration_error(
    *,
    service: Any,
    edge: dict[str, Any],
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    task_run_payload: dict[str, Any],
) -> dict[str, Any]:
    repository_id = str(edge.get("repository") or edge.get("repository_id") or "").strip()
    collection_id = str(edge.get("collection") or edge.get("collection_id") or "").strip()
    if not repository_id or not collection_id:
        return {
            "reason": "formal_memory_edge_missing_repository_or_collection",
            "edge_id": str(edge.get("edge_id") or ""),
            "authority": "harness.graph.memory_postprocess",
        }
    try:
        scope = service.resolve_repository_scope(
            logical_repository_id=repository_id,
            task_run_id=work_order.task_run_id,
            lifecycle_policy=dict(edge.get("lifecycle_policy") or {}),
            runtime_scope=_runtime_scope(graph_config=graph_config, work_order=work_order, task_run_payload=task_run_payload),
        )
    except Exception as exc:
        return {
            "reason": "formal_memory_scope_resolution_failed",
            "edge_id": str(edge.get("edge_id") or ""),
            "error": str(exc),
            "authority": "harness.graph.memory_postprocess",
        }
    effective_repository_id = str(dict(scope or {}).get("effective_repository_id") or "")
    store = getattr(service, "store", None)
    repository = store.get_repository(effective_repository_id) if store is not None and hasattr(store, "get_repository") else None
    collection = store.get_collection(effective_repository_id, collection_id) if store is not None and hasattr(store, "get_collection") else None
    if repository is None or collection is None:
        return {
            "reason": "formal_memory_repository_or_collection_not_declared",
            "edge_id": str(edge.get("edge_id") or ""),
            "repository_id": repository_id,
            "effective_repository_id": effective_repository_id,
            "collection_id": collection_id,
            "authority": "harness.graph.memory_postprocess",
        }
    return {}


def _edge_commits_memory(*, edge: dict[str, Any], graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> bool:
    del graph_config, work_order
    return str(edge.get("edge_type") or "") == "memory_commit"


def _candidate_artifact_refs(candidate: dict[str, Any]) -> list[str]:
    refs = candidate.get("artifact_refs") or dict(candidate.get("payload") or {}).get("artifact_refs") or []
    result: list[str] = []
    seen: set[str] = set()
    for item in list(refs or []):
        value = artifact_materialization_ref(item) if isinstance(item, dict) else str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


def _runtime_scope(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder, task_run_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    environment = dict(graph_config.environment or {})
    graph_state = dict(work_order.graph_state or {})
    input_package = dict(work_order.input_package or {})
    dispatch_context = dict(work_order.dispatch_context or {})
    return {
        **dict(environment.get("runtime_scope") or {}),
        **dict(graph_state.get("runtime_scope") or {}),
        **dict(input_package.get("runtime_scope") or {}),
        **dict(dispatch_context.get("runtime_scope") or {}),
        **dict(diagnostics.get("runtime_scope") or {}),
        **({"project_id": str(diagnostics.get("project_id") or "")} if str(diagnostics.get("project_id") or "") else {}),
        **({"scope_id": str(diagnostics.get("scope_id") or "")} if str(diagnostics.get("scope_id") or "") else {}),
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "graph_run_id": work_order.graph_run_id,
        "task_run_id": work_order.task_run_id,
        "authority": "harness.graph.work_order_runtime_scope",
    }


def _source_clock_seq(task_run_payload: dict[str, Any]) -> int:
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    try:
        return int(diagnostics.get("graph_clock_seq") or diagnostics.get("step_index") or 0)
    except (TypeError, ValueError):
        return 0


def _nested_lookup(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in [item for item in str(dotted_key or "").split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        key = str(candidate.get("idempotency_key") or candidate.get("record_key") or candidate.get("canonical_text") or candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(candidate))
    return result


def _node_quality_acceptance(
    *,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    final_answer: str,
    artifact_refs: list[dict[str, Any]],
    result_status: str,
) -> dict[str, Any]:
    node = _graph_node_by_id(graph_config, work_order.node_id)
    if not node:
        return {}
    if str(node.get("node_type") or "").strip() == "review_gate":
        return {}
    retry_policy = dict(node.get("retry") or work_order.retry_policy or {})
    accepted_policies = [
        str(item).strip()
        for item in list(retry_policy.get("acceptance_policies") or [])
        if str(item).strip()
    ]
    runtime_contract = dict(dict(node.get("contracts") or {}).get("contract_bindings") or {}).get("runtime") or {}
    length_budget = dict(runtime_contract.get("length_budget") or {})
    has_length_budget = bool(length_budget.get("enabled") is True or length_budget.get("configured") is True)
    if not has_length_budget and not accepted_policies:
        return {}
    if not str(final_answer or "").strip():
        return {}
    if has_length_budget:
        length_budget = {**length_budget, "configured": True}
    explicit_inputs = {
        **dict(dict(work_order.input_package or {}).get("initial_inputs") or {}),
        **dict(work_order.explicit_inputs or {}),
    }
    return stage_business_acceptance(
        stage_id=work_order.node_id,
        contract={
            "node_type": str(node.get("node_type") or ""),
            "length_budget": length_budget,
            "quality_retry_policy": retry_policy,
        },
        explicit_inputs=explicit_inputs,
        final_content=final_answer,
        output_refs=[
            str(item.get("path") or item.get("src") or item.get("absolute_path") or "")
            for item in list(artifact_refs or [])
            if isinstance(item, dict)
        ],
        terminal_status=result_status,
        requires_file_artifact_refs=False,
    )


def _node_result_error(
    *,
    executor_result: dict[str, Any],
    task_run_payload: dict[str, Any],
    postprocess_errors: list[dict[str, Any]],
    quality_acceptance: dict[str, Any],
    recoverable: bool = False,
) -> dict[str, Any]:
    if quality_acceptance and not bool(quality_acceptance.get("accepted")):
        return {
            "reason": "quality_gate_failed",
            "quality_issue_summary": str(quality_acceptance.get("quality_issue_summary") or ""),
            "issues": [str(item) for item in list(quality_acceptance.get("issues") or []) if str(item)],
            "policy": str(quality_acceptance.get("policy") or ""),
            "authority": "harness.graph.work_order_executor.quality_gate",
            **(
                {
                    "recoverable_error": {
                        "error_code": "quality_gate_failed",
                        "retryable": True,
                        "recovery_action": "requeue_same_graph_node_with_quality_feedback",
                        "user_message": "质量门未通过，系统会把字数统计和原文回灌给同一节点重修。",
                    }
                }
                if recoverable
                else {}
            ),
            **({"postprocess_errors": postprocess_errors} if postprocess_errors else {}),
        }
    return {
        "reason": str(
            executor_result.get("error")
            or task_run_payload.get("terminal_reason")
            or (postprocess_errors[0].get("reason") if postprocess_errors else "")
            or "node_executor_failed"
        ),
        **({"postprocess_errors": postprocess_errors} if postprocess_errors else {}),
    }


def _has_quality_repair_route(graph_config: GraphHarnessConfig, node_id: str) -> bool:
    source = str(node_id or "").strip()
    if not source:
        return False
    for edge in graph_config.edges:
        payload = dict(edge or {})
        if str(payload.get("source_node_id") or "").strip() != source:
            continue
        edge_type = str(payload.get("edge_type") or "").strip().lower()
        semantic_role = str(payload.get("semantic_role") or "").strip().lower()
        metadata = dict(payload.get("metadata") or {})
        dependency_role = str(metadata.get("dependency_role") or payload.get("dependency_role") or "").strip().lower()
        if (
            edge_type in {"revision_request", "repair_feedback", "repair_route"}
            or semantic_role in {"revision", "repair"}
            or dependency_role in {"repair_feedback", "repair_route"}
        ):
            return True
    return False


def _quality_failure_requeues_same_node(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> bool:
    node = _graph_node_by_id(graph_config, work_order.node_id)
    retry_policy = dict(node.get("retry") or work_order.retry_policy or {})
    mode = str(retry_policy.get("quality_failure_mode") or retry_policy.get("failure_mode") or "").strip().lower()
    return mode in {"retry_same_node", "requeue_same_node"}


def _quality_failure_soft_passes(
    *,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    quality_acceptance: dict[str, Any],
) -> bool:
    if not quality_acceptance or bool(quality_acceptance.get("accepted")):
        return False
    node = _graph_node_by_id(graph_config, work_order.node_id)
    retry_policy = dict(node.get("retry") or work_order.retry_policy or {})
    if str(retry_policy.get("quality_failure_mode") or "").strip().lower() != "retry_same_node":
        return False
    max_retries = int(retry_policy.get("max_quality_retries") or retry_policy.get("max_metric_retries") or 0)
    if max_retries < 1:
        return False
    revision_feedback = dict(dict(work_order.input_package or {}).get("initial_inputs") or {}).get("quality_gate_feedback")
    if not isinstance(revision_feedback, dict):
        return False
    issues = [str(item) for item in list(quality_acceptance.get("issues") or []) if str(item)]
    if not issues:
        return False
    allowed_prefixes = ("insufficient_metric:", "insufficient_unit_metric:", "below_target:")
    return all(any(issue.startswith(prefix) for prefix in allowed_prefixes) for issue in issues)


def _graph_node_by_id(graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
    target = str(node_id or "").strip()
    if not target:
        return {}
    for node in graph_config.nodes:
        current = str(dict(node).get("node_id") or "").strip()
        if current == target:
            return dict(node)
    return {}
