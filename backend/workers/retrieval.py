from __future__ import annotations

from typing import Any

from evidence.adapter import build_evidence_envelope_from_retrieval
from evidence.models import BindingCandidate, EvidenceEnvelope
from workers.models import WorkerRequest, WorkerResult


class RetrievalWorker:
    def __init__(self, *, retrieval_service) -> None:
        self.retrieval_service = retrieval_service

    def run(self, request: WorkerRequest, *, top_k: int = 5) -> WorkerResult:
        query = str(request.query or "").strip()
        raw_results = self.retrieval_service.retrieve(query, top_k=max(int(top_k or 1), 1))
        envelope = build_evidence_envelope_from_retrieval(
            query=query,
            retrieval_results=list(raw_results or []),
            source_worker="retrieval",
        )
        return WorkerResult(
            worker_name="retrieval",
            status="ok",
            evidence_envelope=envelope,
            artifact_updates=list(envelope.derived_artifacts),
            binding_candidates=_binding_candidates_from_envelope(envelope),
            diagnostics={"raw_result_count": len(list(raw_results or []))},
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
                source_worker=envelope.source_worker,
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
                source_worker=envelope.source_worker,
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
                source_worker=envelope.source_worker,
                artifact_id=candidate.artifact_id,
                confidence=candidate.confidence,
                evidence_refs=[candidate.artifact_id],
            )
        )
    return candidates
