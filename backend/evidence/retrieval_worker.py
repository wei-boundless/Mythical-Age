from __future__ import annotations

from typing import Any

from evidence.adapter import build_evidence_envelope_from_retrieval
from evidence.models import BindingCandidate, EvidenceEnvelope
from knowledge_system.retrieval.service import RetrievalExecutionResult
from .mcp_models import MCPRequest, MCPResult


class RetrievalWorker:
    def __init__(self, *, retrieval_service) -> None:
        self.retrieval_service = retrieval_service

    def run(self, request: MCPRequest, *, top_k: int = 5) -> MCPResult:
        query = str(request.query or "").strip()
        execution = self._retrieve_execution(query, top_k=max(int(top_k or 1), 1))
        raw_results = list(execution.results or [])
        envelope = build_evidence_envelope_from_retrieval(
            query=query,
            retrieval_results=raw_results,
            source_mcp="retrieval",
        )
        status = "ok"
        if execution.status == "error":
            status = "degraded"
        return MCPResult(
            mcp_name="retrieval",
            status=status,
            evidence_envelope=envelope,
            artifact_updates=list(envelope.derived_artifacts),
            binding_candidates=_binding_candidates_from_envelope(envelope),
            diagnostics={
                "raw_result_count": len(raw_results),
                "retrieval": dict(execution.diagnostics),
                "degraded_reason_typed": execution.degraded_reason_typed,
            },
        )

    def _retrieve_execution(self, query: str, *, top_k: int) -> RetrievalExecutionResult:
        retrieve_execution = getattr(self.retrieval_service, "retrieve_execution", None)
        if callable(retrieve_execution):
            return retrieve_execution(query, top_k=top_k)
        retrieve = getattr(self.retrieval_service, "retrieve", None)
        if callable(retrieve):
            results = list(retrieve(query, top_k=top_k) or [])
            return RetrievalExecutionResult(
                status="ok" if results else "empty",
                results=tuple(dict(item) for item in results),
                diagnostics={"result_count": len(results), "service_contract": "retrieve_only"},
            )
        return RetrievalExecutionResult(
            status="error",
            diagnostics={
                "result_count": 0,
                "retrieval_failure": {
                    "failure_stage": "service_contract",
                    "error_type": "MissingMethod",
                    "error_message": "retrieval service must implement retrieve_execution() or retrieve()",
                },
            },
            degraded_reason_typed="retrieval_service_contract_error",
        )


def _binding_candidates_from_envelope(envelope: EvidenceEnvelope) -> list[BindingCandidate]:
    candidates: list[BindingCandidate] = []
    for index, candidate in enumerate(envelope.dataset_candidates, start=1):
        candidates.append(
            BindingCandidate(
                candidate_id=f"cand:dataset:{index}",
                kind="dataset",
                identity=candidate.path,
                display_label=candidate.target_object or candidate.path,
                source_mcp=envelope.source_mcp,
                artifact_id=candidate.artifact_id,
                confidence=candidate.confidence,
                evidence_refs=[candidate.artifact_id] if candidate.artifact_id else [],
            )
        )
    for index, candidate in enumerate(envelope.document_candidates, start=1):
        candidates.append(
            BindingCandidate(
                candidate_id=f"cand:document:{index}",
                kind="document",
                identity=candidate.path,
                display_label=candidate.path,
                source_mcp=envelope.source_mcp,
                artifact_id=candidate.artifact_id,
                confidence=candidate.confidence,
                evidence_refs=[candidate.artifact_id] if candidate.artifact_id else [],
            )
        )
    for index, candidate in enumerate(envelope.table_candidates, start=1):
        candidates.append(
            BindingCandidate(
                candidate_id=f"cand:table:{index}",
                kind="table",
                identity=candidate.artifact_id,
                display_label=candidate.artifact_id,
                source_mcp=envelope.source_mcp,
                artifact_id=candidate.artifact_id,
                confidence=candidate.confidence,
                evidence_refs=[candidate.artifact_id],
            )
        )
    return candidates
