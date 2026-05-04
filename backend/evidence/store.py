from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from evidence.graph import EvidenceArtifactGraph
from evidence.models import BindingCandidate


AFFIRMATIVE_SELECTION_RE = re.compile(
    r"^\s*(?:是|对|对的|嗯|嗯嗯|可以|就是|就这个|选这个|用这个|确认|yes|yep|correct|right)",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class StoredBindingCandidateSet:
    session_id: str
    source_query: str
    candidates: list[BindingCandidate] = field(default_factory=list)
    remaining_turns: int = 3


@dataclass(slots=True)
class CandidateSelection:
    candidate: BindingCandidate
    source_query: str
    selection_source: str


class BindingCandidateStore:
    def __init__(self) -> None:
        self._store: dict[str, StoredBindingCandidateSet] = {}

    def save(
        self,
        session_id: str,
        *,
        source_query: str,
        candidates: list[BindingCandidate],
        ttl_turns: int = 3,
    ) -> None:
        normalized = str(session_id or "").strip()
        filtered = [candidate for candidate in list(candidates or []) if str(candidate.identity or "").strip()]
        if not normalized or not filtered:
            return
        self._store[normalized] = StoredBindingCandidateSet(
            session_id=normalized,
            source_query=str(source_query or "").strip(),
            candidates=filtered,
            remaining_turns=max(int(ttl_turns or 1), 1),
        )

    def resolve_selection(self, session_id: str, message: str) -> CandidateSelection | None:
        normalized = str(session_id or "").strip()
        item = self._store.get(normalized)
        if item is None:
            return None
        text = str(message or "").strip()
        if not text:
            return None
        self._decrement(normalized)
        exact = self._select_by_candidate_surface(item, text)
        if exact is not None:
            return CandidateSelection(candidate=exact, source_query=item.source_query, selection_source="candidate_surface")
        if len(item.candidates) == 1 and self._is_affirmative_selection(text):
            return CandidateSelection(
                candidate=item.candidates[0],
                source_query=item.source_query,
                selection_source="single_candidate_affirmation",
            )
        return None

    def clear(self, session_id: str) -> None:
        self._store.pop(str(session_id or "").strip(), None)

    def snapshot(self, session_id: str) -> dict[str, Any]:
        item = self._store.get(str(session_id or "").strip())
        if item is None:
            return {}
        return {
            "session_id": item.session_id,
            "source_query": item.source_query,
            "remaining_turns": item.remaining_turns,
            "candidates": [candidate.to_dict() for candidate in item.candidates],
        }

    def restore(self, session_id: str, payload: dict[str, Any]) -> None:
        normalized = str(session_id or "").strip()
        if not normalized or not isinstance(payload, dict):
            return
        raw_candidates = list(payload.get("candidates", []) or [])
        candidates: list[BindingCandidate] = []
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue
                candidate = BindingCandidate(
                    candidate_id=str(raw.get("candidate_id", "") or ""),
                    kind=str(raw.get("kind", "") or ""),
                    identity=str(raw.get("identity", "") or ""),
                    display_label=str(raw.get("display_label", "") or ""),
                    source_mcp=str(raw.get("source_mcp", raw.get("source_worker", "")) or ""),
                    artifact_id=str(raw.get("artifact_id", "") or ""),
                confidence=float(raw.get("confidence", 0.0) or 0.0),
                evidence_refs=[str(item) for item in list(raw.get("evidence_refs", []) or [])],
                expires_after_turns=int(raw.get("expires_after_turns", 3) or 3),
            )
            if candidate.identity:
                candidates.append(candidate)
        if not candidates:
            self.clear(normalized)
            return
        self._store[normalized] = StoredBindingCandidateSet(
            session_id=normalized,
            source_query=str(payload.get("source_query", "") or ""),
            candidates=candidates,
            remaining_turns=max(int(payload.get("remaining_turns", 1) or 1), 1),
        )

    def _decrement(self, session_id: str) -> None:
        item = self._store.get(session_id)
        if item is None:
            return
        item.remaining_turns -= 1
        if item.remaining_turns <= 0:
            self._store.pop(session_id, None)

    def _select_by_candidate_surface(
        self,
        item: StoredBindingCandidateSet,
        text: str,
    ) -> BindingCandidate | None:
        compact = _normalize(text)
        if not compact:
            return None
        for candidate in item.candidates:
            surfaces = {
                str(candidate.candidate_id or ""),
                str(candidate.identity or ""),
                str(candidate.display_label or ""),
            }
            for surface in surfaces:
                normalized = _normalize(surface)
                if normalized and normalized in compact:
                    return candidate
        for candidate in item.candidates:
            normalized = _normalize(str(candidate.artifact_id or ""))
            if normalized and normalized in compact:
                return candidate
        return None

    def _is_affirmative_selection(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or "")).strip()
        if len(compact) > 24:
            return False
        return bool(AFFIRMATIVE_SELECTION_RE.search(str(text or "").strip()))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").replace("\\", "/")).strip().lower()


class EvidenceGraphStore:
    def __init__(self) -> None:
        self._store: dict[str, EvidenceArtifactGraph] = {}

    def merge(self, session_id: str, graph: EvidenceArtifactGraph) -> None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return
        existing = self._store.get(normalized)
        if existing is None:
            self._store[normalized] = EvidenceArtifactGraph(
                session_id=normalized,
                turn_id=graph.turn_id,
                source_objects=dict(graph.source_objects),
                artifacts=dict(graph.artifacts),
                result_handles=dict(graph.result_handles),
                subset_handles=dict(graph.subset_handles),
                edges=list(graph.edges),
            )
            return
        existing.merge(graph)

    def snapshot(self, session_id: str) -> dict[str, Any]:
        graph = self._store.get(str(session_id or "").strip())
        if graph is None:
            return {}
        return graph.to_delta()

    def restore(self, session_id: str, payload: dict[str, Any]) -> None:
        normalized = str(session_id or "").strip()
        if not normalized or not isinstance(payload, dict):
            return
        graph = EvidenceArtifactGraph.from_delta({**dict(payload), "session_id": normalized})
        if (
            not graph.source_objects
            and not graph.artifacts
            and not graph.result_handles
            and not graph.subset_handles
            and not graph.edges
        ):
            self.clear(normalized)
            return
        self._store[normalized] = graph

    def get_artifact(self, session_id: str, artifact_id: str):
        graph = self._store.get(str(session_id or "").strip())
        if graph is None:
            return None
        return graph.get_artifact(artifact_id)

    def get_source_object(self, session_id: str, object_id: str):
        graph = self._store.get(str(session_id or "").strip())
        if graph is None:
            return None
        return graph.get_source_object(object_id)

    def get_result_handle(self, session_id: str, result_id: str):
        graph = self._store.get(str(session_id or "").strip())
        if graph is None:
            return None
        return graph.get_result_handle(result_id)

    def get_subset_handle(self, session_id: str, subset_id: str):
        graph = self._store.get(str(session_id or "").strip())
        if graph is None:
            return None
        return graph.get_subset_handle(subset_id)

    def clear(self, session_id: str) -> None:
        self._store.pop(str(session_id or "").strip(), None)
