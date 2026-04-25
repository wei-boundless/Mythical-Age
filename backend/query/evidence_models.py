from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EvidenceVisibility = Literal["model_visible", "debug_only"]


@dataclass(frozen=True, slots=True)
class SourceObjectRef:
    object_id: str
    object_type: str
    uri: str
    parent_id: str = ""
    locator: dict[str, Any] = field(default_factory=dict)
    index_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    artifact_id: str
    artifact_type: str
    source_object_id: str
    parent_artifact_id: str = ""
    content_ref: str = ""
    canonical_preview: str = ""
    visibility: EvidenceVisibility = "debug_only"
    consumable_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    kind: str
    source: str
    text: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    visibility: EvidenceVisibility = "debug_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DatasetCandidate:
    path: str
    target_object: str = ""
    evidence_source: str = ""
    confidence: float = 0.0
    reason: str = ""
    artifact_id: str = ""
    source_object_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DocumentCandidate:
    path: str
    document_type: str = ""
    page: int | None = None
    confidence: float = 0.0
    reason: str = ""
    artifact_id: str = ""
    source_object_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TableCandidate:
    artifact_id: str
    source_object_id: str
    source_kind: str
    locator: dict[str, Any] = field(default_factory=dict)
    schema_preview: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BindingCandidate:
    candidate_id: str
    kind: str
    identity: str
    display_label: str = ""
    source_worker: str = ""
    artifact_id: str = ""
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    expires_after_turns: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    query: str
    source_worker: str
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    source_objects: list[SourceObjectRef] = field(default_factory=list)
    derived_artifacts: list[EvidenceArtifact] = field(default_factory=list)
    document_candidates: list[DocumentCandidate] = field(default_factory=list)
    dataset_candidates: list[DatasetCandidate] = field(default_factory=list)
    table_candidates: list[TableCandidate] = field(default_factory=list)
    answer_candidates: list[str] = field(default_factory=list)
    ambiguity: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "source_worker": self.source_worker,
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "source_objects": [item.to_dict() for item in self.source_objects],
            "derived_artifacts": [item.to_dict() for item in self.derived_artifacts],
            "document_candidates": [item.to_dict() for item in self.document_candidates],
            "dataset_candidates": [item.to_dict() for item in self.dataset_candidates],
            "table_candidates": [item.to_dict() for item in self.table_candidates],
            "answer_candidates": list(self.answer_candidates),
            "ambiguity": dict(self.ambiguity or {}) if self.ambiguity is not None else None,
            "diagnostics": dict(self.diagnostics),
        }

    def compact_summary(self, *, max_items: int = 3) -> str:
        lines: list[str] = []
        for item in self.evidence_items[: max(int(max_items or 1), 1)]:
            text = " ".join(str(item.text or "").split())
            if not text:
                continue
            source = str(item.source or "").strip()
            lines.append(f"{source}: {text[:220]}" if source else text[:220])
        return "\n".join(lines).strip()
