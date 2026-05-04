from __future__ import annotations

from typing import Any

from agents.a2a_runtime import task_envelope_from_request, task_envelope_from_result
from evidence.graph import EvidenceArtifactGraph, result_handle_from_payload, subset_handle_from_payload
from output_boundary import build_rag_evidence_pack
from .pdf_worker import PDFWorker
from .projection import WorkerProjectionAdapter
from .retrieval_worker import RetrievalWorker
from .structured_data_worker import StructuredDataWorker
from .worker_models import (
    A2A_COMPATIBLE_PROTOCOL_VERSION,
    CanonicalResult,
    WorkerExecutionPlan,
    WorkerResult,
    request_agent_id,
    result_agent_id,
    stream_event_type_from_worker_status,
    task_status_from_worker_status,
)


class EvidenceOrchestrator:
    def __init__(
        self,
        *,
        retrieval_worker: RetrievalWorker,
        pdf_worker: PDFWorker | None = None,
        structured_data_worker: StructuredDataWorker | None = None,
        candidate_store=None,
        graph_store=None,
        output_policy,
    ) -> None:
        self.retrieval_worker = retrieval_worker
        self.pdf_worker = pdf_worker
        self.structured_data_worker = structured_data_worker
        self.candidate_store = candidate_store
        self.graph_store = graph_store
        self.output_policy = output_policy
        self.projection_adapter = WorkerProjectionAdapter()

    async def stream_execution(
        self,
        *,
        session_id: str,
        execution,
        worker_plan: WorkerExecutionPlan,
        main_context: Any,
        trace=None,
    ):
        request = worker_plan.request
        worker_route = str(worker_plan.worker_route or "none")
        agent_id = request_agent_id(request, fallback_worker_route=worker_route)
        protocol_version = (
            str(getattr(request, "protocol_version", "") or "").strip()
            or A2A_COMPATIBLE_PROTOCOL_VERSION
        )
        message_id = str(getattr(request, "message_id", "") or getattr(request, "request_id", "") or "").strip()
        extensions = dict(getattr(request, "extensions", {}) or {})
        if request is None or worker_route in {"", "none"}:
            yield self._done_event(
                canonical=CanonicalResult(
                    result_kind="worker_answer",
                    ok=False,
                    answer="当前请求没有形成可执行的证据任务。",
                    degraded_reason="missing_worker_request",
                ),
                main_context=main_context,
                worker_result=None,
                query=str(getattr(request, "query", "") or "") if request is not None else "",
                agent_id=agent_id,
                protocol_version=protocol_version,
                message_id=message_id,
                extensions=extensions,
            )
            return

        yield {
            "type": "worker_start",
            "worker": worker_route,
            "agent_id": agent_id,
            "protocol_version": protocol_version,
            "message_id": message_id,
            "task_status": "submitted",
            "stream_event_type": "task.started",
            "extensions": extensions,
            "request": request.to_dict(),
            "a2a_task": task_envelope_from_request(request).to_dict(),
        }
        if worker_route in {"retrieval", "evidence_orchestrator"}:
            worker_result = self.retrieval_worker.run(request)
        elif worker_route == "pdf" and self.pdf_worker is not None:
            worker_result = await self.pdf_worker.run(request)
        elif worker_route == "structured_data" and self.structured_data_worker is not None:
            worker_result = await self.structured_data_worker.run(request)
        else:
            worker_result = WorkerResult(
                worker_name=worker_route,
                status="error",
                diagnostics={"reason": "unsupported_worker_route"},
            )

        if trace is not None:
            trace.annotate(
                {
                    "app.worker_route": worker_route,
                    "app.agent_id": result_agent_id(worker_result, fallback_worker_route=worker_route),
                    "app.protocol_version": protocol_version,
                    "app.worker_status": worker_result.status,
                    "app.evidence_candidate_count": len(worker_result.binding_candidates),
                }
            )

        envelope = worker_result.evidence_envelope
        raw_results = _retrieval_results_from_envelope(envelope)
        if envelope is not None:
            if self.candidate_store is not None:
                self.candidate_store.save(
                    session_id,
                    source_query=request.query,
                    candidates=list(worker_result.binding_candidates),
                )
            if worker_route in {"retrieval", "evidence_orchestrator"}:
                yield {
                    "type": "retrieval",
                    "query": request.query,
                    "results": raw_results,
                    "agent_id": agent_id,
                    "protocol_version": protocol_version,
                    "message_id": message_id,
                }
            yield {
                "type": "worker_evidence",
                "worker": worker_route,
                "agent_id": agent_id,
                "protocol_version": protocol_version,
                "message_id": message_id,
                "task_status": "working",
                "stream_event_type": "task.updated",
                "extensions": extensions,
                "evidence": envelope.to_dict(),
            }
            graph = EvidenceArtifactGraph.from_envelope(session_id=session_id, envelope=envelope)
            _add_emitted_handles_to_graph(graph, worker_result=worker_result, worker=worker_route)
            if self.graph_store is not None:
                self.graph_store.merge(session_id, graph)
            yield {
                "type": "worker_artifacts",
                "worker": worker_route,
                "agent_id": agent_id,
                "protocol_version": protocol_version,
                "message_id": message_id,
                "task_status": "working",
                "stream_event_type": "task.artifact_delta",
                "extensions": extensions,
                "graph_delta": graph.to_delta(),
            }

        if worker_result.canonical_result is not None:
            canonical = worker_result.canonical_result
        else:
            canonical = await self._canonicalize_retrieval_answer(
                query=request.query,
                worker_result=worker_result,
                raw_results=raw_results,
            )
        yield {
            "type": "worker_end",
            "worker": worker_route,
            "agent_id": result_agent_id(worker_result, fallback_worker_route=worker_route),
            "protocol_version": protocol_version,
            "message_id": message_id,
            "task_status": task_status_from_worker_status(worker_result.status),
            "stream_event_type": stream_event_type_from_worker_status(worker_result.status),
            "extensions": {
                **extensions,
                **dict(getattr(worker_result, "extensions", {}) or {}),
            },
            "result": canonical.to_dict(),
            "binding_candidates": [item.to_dict() for item in worker_result.binding_candidates],
            "object_handle_ids": list(canonical.object_handle_ids or []),
            "result_handle_ids": list(canonical.result_handle_ids or []),
            "binding_owner_task_id": str(getattr(worker_result, "binding_owner_task_id", "") or ""),
            "degraded_reason_typed": str(canonical.degraded_reason_typed or canonical.degraded_reason or ""),
            "presentation_hints": dict(canonical.presentation_hints or {}),
            "a2a_task": task_envelope_from_result(
                request=request,
                result=worker_result,
                canonical=canonical,
            ).to_dict(),
        }
        yield self._done_event(
            canonical=canonical,
            main_context=main_context,
            worker_result=worker_result,
            query=request.query,
            agent_id=result_agent_id(worker_result, fallback_worker_route=worker_route),
            protocol_version=protocol_version,
            message_id=message_id,
            extensions={
                **extensions,
                **dict(getattr(worker_result, "extensions", {}) or {}),
            },
        )

    async def _canonicalize_retrieval_answer(
        self,
        *,
        query: str,
        worker_result: WorkerResult,
        raw_results: list[dict[str, Any]],
    ) -> CanonicalResult:
        evidence_pack = build_rag_evidence_pack(
            user_query=query,
            retrieval_results=raw_results,
            max_items=3,
        )
        if self.output_policy.rag_evidence_pack_can_finalize(evidence_pack):
            finalized = await self.output_policy.rewrite_rag_answer_with_model(evidence_pack=evidence_pack)
            if finalized:
                return CanonicalResult(
                    result_kind="rag_answer",
                    ok=True,
                    answer=finalized,
                    evidence_refs=_evidence_refs(worker_result),
                    artifact_refs=_artifact_refs(worker_result),
                    projection_policy="persist_canonical",
                    diagnostics={"answer_source": "rag_answer_finalization"},
                    object_handle_ids=_source_object_ids(worker_result),
                    result_handle_ids=[f"result:rag_answer:{_slug(query)}:primary"],
                    primary_result_handle_id=f"result:rag_answer:{_slug(query)}:primary",
                )

        candidate_answer = _candidate_clarification_answer(worker_result)
        if candidate_answer:
            return CanonicalResult(
                result_kind="rag_candidate_clarification",
                ok=False,
                answer=candidate_answer,
                evidence_refs=_evidence_refs(worker_result),
                artifact_refs=_artifact_refs(worker_result),
                projection_policy="do_not_persist",
                degraded_reason="candidate_needs_binding",
                diagnostics={"answer_source": "evidence_candidate_clarification"},
                object_handle_ids=_source_object_ids(worker_result),
                degraded_reason_typed="missing_object_handle",
            )

        return CanonicalResult(
            result_kind="rag_answer",
            ok=False,
            answer="已检索到相关资料，但当前模型尚未产出可直接展示的结论。",
            evidence_refs=_evidence_refs(worker_result),
            artifact_refs=_artifact_refs(worker_result),
            projection_policy="do_not_persist",
            degraded_reason="rag_missing_answer",
            diagnostics={"answer_source": "fallback_policy"},
            object_handle_ids=_source_object_ids(worker_result),
            degraded_reason_typed="evidence_insufficient_for_synthesis",
        )

    def _done_event(
        self,
        *,
        canonical: CanonicalResult,
        main_context: Any,
        worker_result: WorkerResult | None,
        query: str = "",
        agent_id: str = "",
        protocol_version: str = A2A_COMPATIBLE_PROTOCOL_VERSION,
        message_id: str = "",
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diagnostics = dict(canonical.diagnostics or {})
        answer_source = str(diagnostics.get("answer_source", "") or "evidence_worker")
        binding_candidates = list(getattr(worker_result, "binding_candidates", []) or []) if worker_result is not None else []
        resolved_agent_id = agent_id or result_agent_id(worker_result)
        task_status = (
            str(getattr(worker_result, "task_status", "") or "").strip()
            if worker_result is not None
            else ""
        ) or ("completed" if canonical.ok else "failed")
        stream_event_type = (
            str(getattr(worker_result, "stream_event_type", "") or "").strip()
            if worker_result is not None
            else ""
        ) or ("task.completed" if canonical.ok else "task.failed")
        projection = self.projection_adapter.project_done_event(
            query=query,
            canonical_result=canonical,
            worker_result=worker_result,
            previous_main_context=main_context,
        )
        return {
            "type": "done",
            "content": canonical.answer,
            "agent_id": resolved_agent_id,
            "protocol_version": protocol_version or A2A_COMPATIBLE_PROTOCOL_VERSION,
            "message_id": message_id,
            "task_status": task_status,
            "stream_event_type": stream_event_type,
            "extensions": {
                **dict(extensions or {}),
                **dict(canonical.extensions or {}),
            },
            "main_context": projection.main_context.to_dict(),
            "task_summary_refs": [item.to_dict() for item in projection.task_summary_refs],
            "object_handle_ids": list(projection.object_handle_ids),
            "result_handle_ids": list(projection.result_handle_ids),
            "binding_owner_task_id": projection.binding_owner_task_id,
            "degraded_reason_typed": projection.degraded_reason_typed,
            "presentation_hints": dict(canonical.presentation_hints or {}),
            "execution_protocol": "worker",
            "answer_channel": "answer_candidate" if canonical.ok else "fallback_answer",
            "answer_source": answer_source,
            "answer_canonical_state": "stable_answer" if canonical.ok else "missing_answer",
            "answer_persist_policy": canonical.projection_policy,
            "answer_finalization_policy": "none",
            "answer_fallback_reason": canonical.degraded_reason,
            "answer_leak_flags": [],
            "evidence_refs": list(canonical.evidence_refs),
            "artifact_refs": list(canonical.artifact_refs),
            "binding_candidate_refs": projection.candidate_refs or [candidate.candidate_id for candidate in binding_candidates],
            "binding_candidates": [candidate.to_dict() for candidate in binding_candidates],
            "committed_bindings": dict(canonical.bindings),
            "memory_policy": projection.memory_policy,
        }


def _retrieval_results_from_envelope(envelope) -> list[dict[str, Any]]:
    if envelope is None:
        return []
    results: list[dict[str, Any]] = []
    for item in envelope.evidence_items:
        metadata = dict(item.metadata)
        results.append(
            {
                "text": item.text,
                "source": item.source,
                "score": item.score,
                "metadata": metadata,
                "page": metadata.get("page"),
                "rewritten_query": metadata.get("rewritten_query", ""),
            }
        )
    return results


def _candidate_clarification_answer(worker_result: WorkerResult) -> str:
    candidates = list(worker_result.binding_candidates or [])
    if not candidates:
        return ""
    labels = [candidate.display_label or candidate.identity for candidate in candidates[:3]]
    joined = "、".join(label for label in labels if label)
    if not joined:
        return ""
    return f"我在本地资料中找到了可继续处理的对象：{joined}。请确认是否基于这些对象继续分析。"


def _evidence_refs(worker_result: WorkerResult) -> list[str]:
    envelope = worker_result.evidence_envelope
    if envelope is None:
        return []
    return [item.artifact_id for item in envelope.derived_artifacts if item.artifact_id]


def _artifact_refs(worker_result: WorkerResult) -> list[str]:
    return _evidence_refs(worker_result)


def _source_object_ids(worker_result: WorkerResult) -> list[str]:
    envelope = worker_result.evidence_envelope
    if envelope is None:
        return []
    return [item.object_id for item in envelope.source_objects if item.object_id]


def _add_emitted_handles_to_graph(
    graph: EvidenceArtifactGraph,
    *,
    worker_result: WorkerResult,
    worker: str,
) -> None:
    for raw in list(getattr(worker_result, "emitted_result_handles", []) or []):
        if not isinstance(raw, dict):
            continue
        handle_kind = str(raw.get("handle_kind", "") or "").strip()
        if handle_kind == "subset":
            subset = subset_handle_from_payload(raw)
            if subset is not None:
                graph.add_subset_handle(subset, worker=worker)
            continue
        result = result_handle_from_payload(raw)
        if result is not None:
            graph.add_result_handle(result, worker=worker)


def _slug(value: str) -> str:
    compact = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).strip("-")
    compact = "-".join(item for item in compact.split("-") if item)
    return compact[:48] or "main"
