from __future__ import annotations

from typing import Any

from agent_system.a2a.official_adapter import (
    OFFICIAL_A2A_PROTOCOL_VERSION,
    build_official_task_from_request,
    build_official_task_from_result,
)
from capability_system.local_mcp_registry import get_local_mcp_unit
from evidence.graph import EvidenceArtifactGraph, result_handle_from_payload, subset_handle_from_payload
from runtime.output_boundary import build_rag_evidence_pack
from .pdf_worker import PDFWorker
from .projection import MCPProjectionAdapter
from .retrieval_worker import RetrievalWorker
from .structured_data_worker import StructuredDataWorker
from .mcp_models import (
    CanonicalResult,
    MCPExecutionPlan,
    MCPResult,
    request_agent_id,
    result_agent_id,
    stream_event_type_from_mcp_status,
    task_status_from_mcp_status,
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
        self.worker_by_slot = {
            "retrieval_worker": retrieval_worker,
            "pdf_worker": pdf_worker,
            "structured_data_worker": structured_data_worker,
        }
        self.candidate_store = candidate_store
        self.graph_store = graph_store
        self.output_policy = output_policy
        self.projection_adapter = MCPProjectionAdapter()

    async def stream_execution(
        self,
        *,
        session_id: str,
        execution,
        mcp_plan: MCPExecutionPlan,
        main_context: Any,
        trace=None,
    ):
        request = mcp_plan.request
        mcp_route = str(mcp_plan.mcp_route or "none")
        agent_id = request_agent_id(request, fallback_mcp_route=mcp_route)
        protocol_version = (
            str(getattr(request, "protocol_version", "") or "").strip()
            or OFFICIAL_A2A_PROTOCOL_VERSION
        )
        message_id = str(getattr(request, "message_id", "") or getattr(request, "request_id", "") or "").strip()
        extensions = dict(getattr(request, "extensions", {}) or {})
        if request is None or mcp_route in {"", "none"}:
            yield self._done_event(
                canonical=CanonicalResult(
                    result_kind="mcp_answer",
                    ok=False,
                    answer="当前请求没有形成可执行的证据任务。",
                    degraded_reason="missing_mcp_request",
                ),
                main_context=main_context,
                mcp_result=None,
                query=str(getattr(request, "query", "") or "") if request is not None else "",
                agent_id=agent_id,
                protocol_version=protocol_version,
                message_id=message_id,
                extensions=extensions,
            )
            return

        yield {
            "type": "mcp_start",
            "mcp": mcp_route,
            "agent_id": agent_id,
            "protocol_version": protocol_version,
            "message_id": message_id,
            "task_status": "submitted",
            "stream_event_type": "task.started",
            "extensions": extensions,
            "request": request.to_dict(),
            "a2a_task": build_official_task_from_request(request),
        }
        mcp_result = await self._run_registered_mcp_worker(mcp_route, request)

        if trace is not None:
            trace.annotate(
                {
                    "app.mcp_route": mcp_route,
                    "app.agent_id": result_agent_id(mcp_result, fallback_mcp_route=mcp_route),
                    "app.protocol_version": protocol_version,
                    "app.mcp_status": mcp_result.status,
                    "app.evidence_candidate_count": len(mcp_result.binding_candidates),
                }
            )

        envelope = mcp_result.evidence_envelope
        raw_results = _retrieval_results_from_envelope(envelope)
        if envelope is not None:
            if self.candidate_store is not None:
                self.candidate_store.save(
                    session_id,
                    source_query=request.query,
                    candidates=list(mcp_result.binding_candidates),
                )
            if self._is_retrieval_route(mcp_route):
                yield {
                    "type": "retrieval",
                    "query": request.query,
                    "results": raw_results,
                    "agent_id": agent_id,
                    "protocol_version": protocol_version,
                    "message_id": message_id,
                }
            yield {
                "type": "mcp_evidence",
                "mcp": mcp_route,
                "agent_id": agent_id,
                "protocol_version": protocol_version,
                "message_id": message_id,
                "task_status": "working",
                "stream_event_type": "task.updated",
                "extensions": extensions,
                "evidence": envelope.to_dict(),
            }
            graph = EvidenceArtifactGraph.from_envelope(session_id=session_id, envelope=envelope)
            _add_emitted_handles_to_graph(graph, mcp_result=mcp_result, mcp=mcp_route)
            if self.graph_store is not None:
                self.graph_store.merge(session_id, graph)
            yield {
                "type": "mcp_artifacts",
                "mcp": mcp_route,
                "agent_id": agent_id,
                "protocol_version": protocol_version,
                "message_id": message_id,
                "task_status": "working",
                "stream_event_type": "task.artifact_delta",
                "extensions": extensions,
                "graph_delta": graph.to_delta(),
            }

        if mcp_result.canonical_result is not None:
            canonical = mcp_result.canonical_result
        else:
            canonical = await self._canonicalize_retrieval_answer(
                query=request.query,
                mcp_result=mcp_result,
                raw_results=raw_results,
            )
        yield {
            "type": "mcp_end",
            "mcp": mcp_route,
            "agent_id": result_agent_id(mcp_result, fallback_mcp_route=mcp_route),
            "protocol_version": protocol_version,
            "message_id": message_id,
            "task_status": task_status_from_mcp_status(mcp_result.status),
            "stream_event_type": stream_event_type_from_mcp_status(mcp_result.status),
            "extensions": {
                **extensions,
                **dict(getattr(mcp_result, "extensions", {}) or {}),
            },
            "result": canonical.to_dict(),
            "binding_candidates": [item.to_dict() for item in mcp_result.binding_candidates],
            "object_handle_ids": list(canonical.object_handle_ids or []),
            "result_handle_ids": list(canonical.result_handle_ids or []),
            "binding_owner_task_id": str(getattr(mcp_result, "binding_owner_task_id", "") or ""),
            "degraded_reason_typed": str(canonical.degraded_reason_typed or canonical.degraded_reason or ""),
            "presentation_hints": dict(canonical.presentation_hints or {}),
            "a2a_task": build_official_task_from_result(
                request=request,
                result=mcp_result,
                canonical=canonical,
            ),
        }
        yield self._done_event(
            canonical=canonical,
            main_context=main_context,
            mcp_result=mcp_result,
            query=request.query,
            agent_id=result_agent_id(mcp_result, fallback_mcp_route=mcp_route),
            protocol_version=protocol_version,
            message_id=message_id,
            extensions={
                **extensions,
                **dict(getattr(mcp_result, "extensions", {}) or {}),
            },
        )

    async def _run_registered_mcp_worker(self, mcp_route: str, request) -> MCPResult:
        unit = get_local_mcp_unit(mcp_route)
        if unit is None:
            return MCPResult(
                mcp_name=mcp_route,
                status="error",
                diagnostics={"reason": "unsupported_mcp_route"},
            )
        worker = self.worker_by_slot.get(unit.worker_slot)
        if worker is None:
            return MCPResult(
                mcp_name=unit.route,
                status="error",
                diagnostics={
                    "reason": "mcp_worker_unavailable",
                    "worker_slot": unit.worker_slot,
                    "local_mcp_unit_id": unit.unit_id,
                },
            )
        runner = getattr(worker, "run", None)
        if not callable(runner):
            return MCPResult(
                mcp_name=unit.route,
                status="error",
                diagnostics={
                    "reason": "mcp_worker_missing_run",
                    "worker_slot": unit.worker_slot,
                    "local_mcp_unit_id": unit.unit_id,
                },
            )
        if unit.worker_execution_kind == "sync":
            return runner(request)
        return await runner(request)

    @staticmethod
    def _is_retrieval_route(mcp_route: str) -> bool:
        unit = get_local_mcp_unit(mcp_route)
        return bool(unit is not None and unit.route == "retrieval")

    async def _canonicalize_retrieval_answer(
        self,
        *,
        query: str,
        mcp_result: MCPResult,
        raw_results: list[dict[str, Any]],
    ) -> CanonicalResult:
        evidence_pack = build_rag_evidence_pack(
            user_query=query,
            retrieval_results=raw_results,
            max_items=3,
        )
        if self.output_policy.rag_evidence_pack_can_finalize(evidence_pack):
            finalization = await self.output_policy.rewrite_rag_answer_with_model(evidence_pack=evidence_pack)
            if finalization.status == "finalized" and finalization.answer:
                return CanonicalResult(
                    result_kind="rag_answer",
                    ok=True,
                    answer=finalization.answer,
                    evidence_refs=_evidence_refs(mcp_result),
                    artifact_refs=_artifact_refs(mcp_result),
                    projection_policy="persist_canonical",
                    diagnostics={
                        "answer_source": "rag_answer_finalization",
                        "finalization": dict(finalization.diagnostics),
                    },
                    object_handle_ids=_source_object_ids(mcp_result),
                    result_handle_ids=[f"result:rag_answer:{_slug(query)}:primary"],
                    primary_result_handle_id=f"result:rag_answer:{_slug(query)}:primary",
                )
            if finalization.status == "error":
                return CanonicalResult(
                    result_kind="rag_answer",
                    ok=False,
                    answer="已检索到相关资料，但当前答案整合阶段失败，请稍后重试。",
                    evidence_refs=_evidence_refs(mcp_result),
                    artifact_refs=_artifact_refs(mcp_result),
                    projection_policy="do_not_persist",
                    degraded_reason="rag_answer_finalization_failed",
                    diagnostics={
                        "answer_source": "rag_answer_finalization_failed",
                        "finalization": dict(finalization.diagnostics),
                    },
                    object_handle_ids=_source_object_ids(mcp_result),
                    degraded_reason_typed=finalization.degraded_reason_typed,
                )

        retrieval_diagnostics = dict(mcp_result.diagnostics.get("retrieval", {}) or {})
        retrieval_failure = dict(retrieval_diagnostics.get("retrieval_failure", {}) or {})
        if not raw_results and retrieval_failure:
            return CanonicalResult(
                result_kind="rag_answer",
                ok=False,
                answer="检索链路当前未能返回证据结果，请稍后重试。",
                evidence_refs=_evidence_refs(mcp_result),
                artifact_refs=_artifact_refs(mcp_result),
                projection_policy="do_not_persist",
                degraded_reason="retrieval_execution_failed",
                diagnostics={
                    "answer_source": "retrieval_failure",
                    "retrieval_failure": retrieval_failure,
                },
                object_handle_ids=_source_object_ids(mcp_result),
                degraded_reason_typed=str(
                    mcp_result.diagnostics.get("degraded_reason_typed") or "retrieval_execution_failed"
                ),
            )

        candidate_answer = _candidate_clarification_answer(mcp_result)
        if candidate_answer:
            return CanonicalResult(
                result_kind="rag_candidate_clarification",
                ok=False,
                answer=candidate_answer,
                evidence_refs=_evidence_refs(mcp_result),
                artifact_refs=_artifact_refs(mcp_result),
                projection_policy="do_not_persist",
                degraded_reason="candidate_needs_binding",
                diagnostics={"answer_source": "evidence_candidate_clarification"},
                object_handle_ids=_source_object_ids(mcp_result),
                degraded_reason_typed="missing_object_handle",
            )

        return CanonicalResult(
            result_kind="rag_answer",
            ok=False,
            answer="已检索到相关资料，但当前模型尚未产出可直接展示的结论。",
            evidence_refs=_evidence_refs(mcp_result),
            artifact_refs=_artifact_refs(mcp_result),
            projection_policy="do_not_persist",
            degraded_reason="rag_missing_answer",
            diagnostics={"answer_source": "fallback_policy"},
            object_handle_ids=_source_object_ids(mcp_result),
            degraded_reason_typed="evidence_insufficient_for_synthesis",
        )

    def _done_event(
        self,
        *,
        canonical: CanonicalResult,
        main_context: Any,
        mcp_result: MCPResult | None,
        query: str = "",
        agent_id: str = "",
        protocol_version: str = OFFICIAL_A2A_PROTOCOL_VERSION,
        message_id: str = "",
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diagnostics = dict(canonical.diagnostics or {})
        answer_source = str(diagnostics.get("answer_source", "") or "evidence_mcp")
        binding_candidates = list(getattr(mcp_result, "binding_candidates", []) or []) if mcp_result is not None else []
        resolved_agent_id = agent_id or result_agent_id(mcp_result)
        task_status = (
            str(getattr(mcp_result, "task_status", "") or "").strip()
            if mcp_result is not None
            else ""
        ) or ("completed" if canonical.ok else "failed")
        stream_event_type = (
            str(getattr(mcp_result, "stream_event_type", "") or "").strip()
            if mcp_result is not None
            else ""
        ) or ("task.completed" if canonical.ok else "task.failed")
        projection = self.projection_adapter.project_done_event(
            query=query,
            canonical_result=canonical,
            mcp_result=mcp_result,
            previous_main_context=main_context,
        )
        return {
            "type": "done",
            "content": canonical.answer,
            "agent_id": resolved_agent_id,
            "protocol_version": protocol_version or OFFICIAL_A2A_PROTOCOL_VERSION,
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
            "execution_protocol": "mcp",
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


def _candidate_clarification_answer(mcp_result: MCPResult) -> str:
    candidates = list(mcp_result.binding_candidates or [])
    if not candidates:
        return ""
    labels = [candidate.display_label or candidate.identity for candidate in candidates[:3]]
    joined = "、".join(label for label in labels if label)
    if not joined:
        return ""
    return f"我在本地资料中找到了可继续处理的对象：{joined}。请确认是否基于这些对象继续分析。"


def _evidence_refs(mcp_result: MCPResult) -> list[str]:
    envelope = mcp_result.evidence_envelope
    if envelope is None:
        return []
    return [item.artifact_id for item in envelope.derived_artifacts if item.artifact_id]


def _artifact_refs(mcp_result: MCPResult) -> list[str]:
    return _evidence_refs(mcp_result)


def _source_object_ids(mcp_result: MCPResult) -> list[str]:
    envelope = mcp_result.evidence_envelope
    if envelope is None:
        return []
    return [item.object_id for item in envelope.source_objects if item.object_id]


def _add_emitted_handles_to_graph(
    graph: EvidenceArtifactGraph,
    *,
    mcp_result: MCPResult,
    mcp: str,
) -> None:
    for raw in list(getattr(mcp_result, "emitted_result_handles", []) or []):
        if not isinstance(raw, dict):
            continue
        handle_kind = str(raw.get("handle_kind", "") or "").strip()
        if handle_kind == "subset":
            subset = subset_handle_from_payload(raw)
            if subset is not None:
                graph.add_subset_handle(subset, mcp=mcp)
            continue
        result = result_handle_from_payload(raw)
        if result is not None:
            graph.add_result_handle(result, mcp=mcp)


def _slug(value: str) -> str:
    compact = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).strip("-")
    compact = "-".join(item for item in compact.split("-") if item)
    return compact[:48] or "main"


