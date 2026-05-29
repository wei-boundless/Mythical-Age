from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import GraphHarnessConfig, GraphNodeWorkOrder, NodeResultEnvelope, safe_id


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
    ) -> GraphWorkOrderExecution:
        order = work_order if isinstance(work_order, GraphNodeWorkOrder) else GraphNodeWorkOrder.from_dict(dict(work_order or {}))
        if order.config_id != graph_config.config_id:
            raise ValueError("GraphNodeWorkOrder config_id does not match GraphHarnessConfig")
        if order.work_kind == "agent":
            return await self._execute_agent_node(graph_config=graph_config, work_order=order, max_steps=max_steps)
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
        )
        event = self._services.event_log.append(
            work_order.task_run_id,
            "graph_node_work_order_executed",
            payload={
                "graph_run_id": work_order.graph_run_id,
                "node_id": work_order.node_id,
                "work_order": work_order.to_dict(),
                "node_executor_task_run_id": str(task_run_payload.get("task_run_id") or ""),
                "node_result": result.to_dict(),
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
    ) -> NodeResultEnvelope:
        ok = bool(executor_result.get("ok") is True)
        task_run_payload = dict(executor_result.get("task_run") or {})
        final_answer = str(executor_result.get("final_answer") or task_run_payload.get("diagnostics", {}).get("final_answer") or "")
        artifact_refs = _artifact_refs_from_executor_result(executor_result, task_run_payload=task_run_payload)
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
        postprocess_errors = [*artifact_errors, *memory_errors]
        result_status = "completed" if ok and not postprocess_errors else "failed"
        return NodeResultEnvelope(
            result_id=f"nresult:{safe_id(work_order.graph_run_id)}:{safe_id(work_order.node_id)}:{safe_id(work_order.work_order_id)}",
            graph_run_id=work_order.graph_run_id,
            task_run_id=work_order.task_run_id,
            node_id=work_order.node_id,
            work_order_id=work_order.work_order_id,
            executor_type=work_order.executor_type,
            status=result_status,
            outputs={
                "final_answer": final_answer,
                "node_executor_task_run_id": task_run_id,
                "executor_status": str(task_run_payload.get("status") or ("completed" if ok else "failed")),
                "artifact_refs": artifact_refs,
            },
            artifact_refs=tuple(str(item.get("path") or item.get("src") or item.get("absolute_path") or "") for item in artifact_refs if isinstance(item, dict)),
            memory_candidates=tuple(memory_candidates),
            artifact_materialization_receipts=tuple(artifact_receipts),
            memory_commit_receipts=tuple(memory_receipts),
            handoff_summary=final_answer[:1200],
            error={} if result_status == "completed" else {
                "reason": str(
                    executor_result.get("error")
                    or task_run_payload.get("terminal_reason")
                    or (postprocess_errors[0].get("reason") if postprocess_errors else "")
                    or "node_executor_failed"
                ),
                **({"postprocess_errors": postprocess_errors} if postprocess_errors else {}),
            },
            diagnostics={
                "authority": "harness.graph.work_order_executor.agent_result",
                "graph_harness_config_id": graph_config.config_id,
                "node_executor_task_run_id": task_run_id,
                "executor_result": _public_executor_result(executor_result),
                "formal_postprocess_errors": postprocess_errors,
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
            result_id=f"nresult:{safe_id(work_order.graph_run_id)}:{safe_id(work_order.node_id)}:{safe_id(work_order.work_order_id)}:unsupported",
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


def _artifact_refs_from_executor_result(executor_result: dict[str, Any], *, task_run_payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in list(executor_result.get("artifact_refs") or []):
        if isinstance(item, dict):
            refs.append(dict(item))
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    for item in list(diagnostics.get("artifact_refs") or []):
        if isinstance(item, dict):
            refs.append(dict(item))
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        key = str(ref.get("path") or ref.get("absolute_path") or ref.get("src") or ref)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _public_executor_result(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(result or {})
    return {
        key: value
        for key, value in payload.items()
        if key in {"ok", "error", "final_answer", "artifact_refs", "task_run", "event", "lifecycle"}
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
    refs = [_artifact_ref_value(ref) for ref in artifact_refs]
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
            artifact_root=str(work_order.artifact_space_ref or _environment_artifact_root(graph_config)),
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
                "receipt_id": f"artifact-receipt:{safe_id(work_order.work_order_id)}:{safe_id(str(dict(receipt or {}).get('materialization_id') or task_run_id))}",
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
                    artifact_refs=list(_candidate_artifact_refs(candidate) or [_artifact_ref_value(ref) for ref in artifact_refs]),
                    runtime_scope=_runtime_scope(graph_config=graph_config, work_order=work_order, task_run_payload=task_run_payload),
                )
                version_payload = version.to_dict() if hasattr(version, "to_dict") else dict(version or {})
                write_payload = write_transaction.to_dict() if hasattr(write_transaction, "to_dict") else dict(write_transaction or {})
                candidate_receipts.append(
                    {
                        "receipt_id": f"memory-candidate:{safe_id(work_order.work_order_id)}:{safe_id(str(version_payload.get('version_id') or 'candidate'))}",
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
                            "receipt_id": f"memory-commit:{safe_id(work_order.work_order_id)}:{safe_id(str(version_payload.get('version_id') or 'commit'))}",
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


def _artifact_ref_value(ref: dict[str, Any]) -> str:
    payload = dict(ref or {})
    value = str(payload.get("artifact_ref") or payload.get("path") or payload.get("src") or payload.get("absolute_path") or "").strip()
    if not value:
        return ""
    return value if value.startswith("artifact:") else value.replace("\\", "/")


def _created_file(ref: dict[str, Any]) -> str:
    payload = dict(ref or {})
    return str(payload.get("created_file") or payload.get("filename") or payload.get("path") or payload.get("src") or "").replace("\\", "/").strip()


def _artifact_repository_policy(*, graph_config: GraphHarnessConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    node_policy = dict(work_order.artifact_view_request.get("node_artifact_policy") or {})
    graph_policy = dict(work_order.artifact_view_request.get("graph_artifact_policy") or graph_config.artifacts or {})
    environment_policy = dict(work_order.artifact_view_request.get("environment_artifact_policy") or dict(graph_config.environment or {}).get("artifact_policy") or {})
    repository_id = str(
        node_policy.get("repository_id")
        or graph_policy.get("repository_id")
        or environment_policy.get("repository_id")
        or environment_policy.get("artifact_repository_id")
        or environment_policy.get("artifact_root")
        or "artifact.repository.default"
    ).strip()
    return {
        "repository_id": repository_id or "artifact.repository.default",
        "collection_id": str(node_policy.get("collection_id") or graph_policy.get("collection_id") or "default").strip() or "default",
        "lifecycle_policy": dict(node_policy.get("lifecycle_policy") or graph_policy.get("lifecycle_policy") or {}),
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
    return {
        **edge,
        "edge_type": edge_type,
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "repository": str(edge.get("repository") or edge.get("repository_id") or metadata.get("repository") or metadata.get("repository_id") or metadata.get("repository_node_id") or "").strip(),
        "collection": str(edge.get("collection") or edge.get("collection_id") or metadata.get("collection") or selector.get("collection") or "").strip(),
        "selector": selector,
        "record_key": str(edge.get("record_key") or metadata.get("record_key") or selector.get("record_key") or "").strip(),
        "record_kind": str(edge.get("record_kind") or metadata.get("record_kind") or selector.get("record_kind") or "").strip(),
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
            return [_candidate_from_value(value, edge=edge)]
    if candidates:
        return [_candidate_for_edge(candidate, edge=edge) for candidate in candidates]
    final_answer = str(dict(task_run_payload.get("diagnostics") or {}).get("final_answer") or "").strip()
    if final_answer and str(edge.get("edge_type") or "") == "memory_commit":
        return [_candidate_for_edge({"canonical_text": final_answer, "summary": final_answer[:240]}, edge=edge)]
    return []


def _candidate_source_payload(task_run_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    return {
        **diagnostics,
        **dict(diagnostics.get("final_action_diagnostics") or {}),
        "final_answer": str(diagnostics.get("final_answer") or ""),
    }


def _candidate_from_value(value: Any, *, edge: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return _candidate_for_edge(dict(value), edge=edge)
    text = str(value or "").strip()
    return _candidate_for_edge({"canonical_text": text, "summary": text[:240], "payload": {"value": value}}, edge=edge)


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
    return {
        **dict(edge or {}),
        "repository": str(edge.get("repository") or edge.get("repository_id") or "").strip(),
        "repository_id": str(edge.get("repository") or edge.get("repository_id") or "").strip(),
        "collection": str(edge.get("collection") or edge.get("collection_id") or "").strip(),
        "collection_id": str(edge.get("collection") or edge.get("collection_id") or "").strip(),
        "selector": {
            **selector,
            **({"record_key": str(edge.get("record_key") or "")} if str(edge.get("record_key") or "") else {}),
            **({"record_kind": str(edge.get("record_kind") or "")} if str(edge.get("record_kind") or "") else {}),
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
    return [str(item or "").strip() for item in list(refs or []) if str(item or "").strip()]


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
