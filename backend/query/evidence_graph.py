from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from query.evidence_models import EvidenceArtifact, EvidenceEnvelope, SourceObjectRef


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    from_id: str
    to_id: str
    relation: str
    confidence: float = 0.0
    worker: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidenceArtifactGraph:
    session_id: str
    turn_id: str = ""
    source_objects: dict[str, SourceObjectRef] = field(default_factory=dict)
    artifacts: dict[str, EvidenceArtifact] = field(default_factory=dict)
    edges: list[EvidenceEdge] = field(default_factory=list)

    @classmethod
    def from_envelope(
        cls,
        *,
        session_id: str,
        envelope: EvidenceEnvelope,
        turn_id: str = "",
    ) -> "EvidenceArtifactGraph":
        graph = cls(session_id=session_id, turn_id=turn_id)
        for source in envelope.source_objects:
            graph.add_source_object(source)
        for artifact in envelope.derived_artifacts:
            graph.add_artifact(
                artifact,
                worker=envelope.source_worker,
                relation="derived_from",
            )
        return graph

    @classmethod
    def from_delta(cls, payload: dict[str, Any]) -> "EvidenceArtifactGraph":
        graph = cls(
            session_id=str(payload.get("session_id", "") or ""),
            turn_id=str(payload.get("turn_id", "") or ""),
        )
        for raw in list(payload.get("source_objects", []) or []):
            if not isinstance(raw, dict):
                continue
            source = SourceObjectRef(
                object_id=str(raw.get("object_id", "") or ""),
                object_type=str(raw.get("object_type", "") or ""),
                uri=str(raw.get("uri", "") or ""),
                parent_id=str(raw.get("parent_id", "") or ""),
                locator=dict(raw.get("locator", {}) or {}),
                index_refs=[str(item) for item in list(raw.get("index_refs", []) or [])],
                metadata=dict(raw.get("metadata", {}) or {}),
            )
            graph.add_source_object(source)
        for raw in list(payload.get("artifacts", []) or []):
            if not isinstance(raw, dict):
                continue
            artifact = EvidenceArtifact(
                artifact_id=str(raw.get("artifact_id", "") or ""),
                artifact_type=str(raw.get("artifact_type", "") or ""),
                source_object_id=str(raw.get("source_object_id", "") or ""),
                parent_artifact_id=str(raw.get("parent_artifact_id", "") or ""),
                content_ref=str(raw.get("content_ref", "") or ""),
                canonical_preview=str(raw.get("canonical_preview", "") or ""),
                visibility=raw.get("visibility") if raw.get("visibility") in {"model_visible", "debug_only"} else "debug_only",
                consumable_by=[str(item) for item in list(raw.get("consumable_by", []) or [])],
                metadata=dict(raw.get("metadata", {}) or {}),
            )
            graph.artifacts[artifact.artifact_id] = artifact
        for raw in list(payload.get("edges", []) or []):
            if not isinstance(raw, dict):
                continue
            graph.edges.append(
                EvidenceEdge(
                    from_id=str(raw.get("from_id", "") or ""),
                    to_id=str(raw.get("to_id", "") or ""),
                    relation=str(raw.get("relation", "") or ""),
                    confidence=float(raw.get("confidence", 0.0) or 0.0),
                    worker=str(raw.get("worker", "") or ""),
                    metadata=dict(raw.get("metadata", {}) or {}),
                )
            )
        return graph

    def add_source_object(self, source: SourceObjectRef) -> None:
        if not source.object_id:
            return
        self.source_objects[source.object_id] = source

    def add_artifact(
        self,
        artifact: EvidenceArtifact,
        *,
        worker: str = "",
        relation: str = "derived_from",
    ) -> None:
        if not artifact.artifact_id:
            return
        self.artifacts[artifact.artifact_id] = artifact
        source_id = str(artifact.parent_artifact_id or artifact.source_object_id or "").strip()
        if source_id:
            self.edges.append(
                EvidenceEdge(
                    from_id=source_id,
                    to_id=artifact.artifact_id,
                    relation=relation,
                    confidence=float(artifact.metadata.get("confidence", 0.0) or 0.0),
                    worker=worker,
                )
            )

    def merge(self, other: "EvidenceArtifactGraph") -> None:
        for source in other.source_objects.values():
            self.add_source_object(source)
        for artifact in other.artifacts.values():
            self.artifacts[artifact.artifact_id] = artifact
        self.edges.extend(other.edges)

    def get_artifact(self, artifact_id: str) -> EvidenceArtifact | None:
        return self.artifacts.get(str(artifact_id or "").strip())

    def get_source_object(self, object_id: str) -> SourceObjectRef | None:
        return self.source_objects.get(str(object_id or "").strip())

    def to_delta(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "source_objects": [item.to_dict() for item in self.source_objects.values()],
            "artifacts": [item.to_dict() for item in self.artifacts.values()],
            "edges": [item.to_dict() for item in self.edges],
        }
