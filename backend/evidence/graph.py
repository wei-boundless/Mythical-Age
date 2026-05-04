from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from evidence.models import EvidenceArtifact, EvidenceEnvelope, ResultHandle, SourceObjectRef, SubsetHandle


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    from_id: str
    to_id: str
    relation: str
    confidence: float = 0.0
    mcp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidenceArtifactGraph:
    session_id: str
    turn_id: str = ""
    source_objects: dict[str, SourceObjectRef] = field(default_factory=dict)
    artifacts: dict[str, EvidenceArtifact] = field(default_factory=dict)
    result_handles: dict[str, ResultHandle] = field(default_factory=dict)
    subset_handles: dict[str, SubsetHandle] = field(default_factory=dict)
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
                mcp=envelope.source_mcp,
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
        for raw in list(payload.get("result_handles", []) or []):
            if not isinstance(raw, dict):
                continue
            result = _result_handle_from_payload(raw)
            if result is not None:
                graph.add_result_handle(result)
        for raw in list(payload.get("subset_handles", []) or []):
            if not isinstance(raw, dict):
                continue
            subset = _subset_handle_from_payload(raw)
            if subset is not None:
                graph.add_subset_handle(subset)
        for raw in list(payload.get("edges", []) or []):
            if not isinstance(raw, dict):
                continue
            graph.edges.append(
                EvidenceEdge(
                    from_id=str(raw.get("from_id", "") or ""),
                    to_id=str(raw.get("to_id", "") or ""),
                    relation=str(raw.get("relation", "") or ""),
                    confidence=float(raw.get("confidence", 0.0) or 0.0),
                    mcp=str(raw.get("mcp", raw.get("worker", "")) or ""),
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
        mcp: str = "",
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
                    mcp=mcp,
                )
            )

    def add_result_handle(
        self,
        result: ResultHandle,
        *,
        mcp: str = "",
        relation: str = "produced_result",
    ) -> None:
        if not result.result_id:
            return
        self.result_handles[result.result_id] = result
        source_id = str(result.artifact_id or result.source_object_id or "").strip()
        if source_id:
            self.edges.append(
                EvidenceEdge(
                    from_id=source_id,
                    to_id=result.result_id,
                    relation=relation,
                    confidence=float(result.metadata.get("confidence", 0.0) or 0.0),
                    mcp=mcp,
                )
            )

    def add_subset_handle(
        self,
        subset: SubsetHandle,
        *,
        mcp: str = "",
        relation: str = "selected_subset",
    ) -> None:
        if not subset.subset_id:
            return
        self.subset_handles[subset.subset_id] = subset
        source_id = str(subset.result_id or subset.artifact_id or subset.source_object_id or "").strip()
        if source_id:
            self.edges.append(
                EvidenceEdge(
                    from_id=source_id,
                    to_id=subset.subset_id,
                    relation=relation,
                    confidence=float(subset.metadata.get("confidence", 0.0) or 0.0),
                    mcp=mcp,
                )
            )

    def merge(self, other: "EvidenceArtifactGraph") -> None:
        for source in other.source_objects.values():
            self.add_source_object(source)
        for artifact in other.artifacts.values():
            self.artifacts[artifact.artifact_id] = artifact
        for result in other.result_handles.values():
            self.result_handles[result.result_id] = result
        for subset in other.subset_handles.values():
            self.subset_handles[subset.subset_id] = subset
        self.edges.extend(other.edges)

    def get_artifact(self, artifact_id: str) -> EvidenceArtifact | None:
        return self.artifacts.get(str(artifact_id or "").strip())

    def get_source_object(self, object_id: str) -> SourceObjectRef | None:
        return self.source_objects.get(str(object_id or "").strip())

    def get_result_handle(self, result_id: str) -> ResultHandle | None:
        return self.result_handles.get(str(result_id or "").strip())

    def get_subset_handle(self, subset_id: str) -> SubsetHandle | None:
        return self.subset_handles.get(str(subset_id or "").strip())

    def to_delta(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "source_objects": [item.to_dict() for item in self.source_objects.values()],
            "artifacts": [item.to_dict() for item in self.artifacts.values()],
            "result_handles": [item.to_dict() for item in self.result_handles.values()],
            "subset_handles": [item.to_dict() for item in self.subset_handles.values()],
            "edges": [item.to_dict() for item in self.edges],
        }


def result_handle_from_payload(payload: dict[str, Any]) -> ResultHandle | None:
    return _result_handle_from_payload(payload)


def subset_handle_from_payload(payload: dict[str, Any]) -> SubsetHandle | None:
    return _subset_handle_from_payload(payload)


def _result_handle_from_payload(payload: dict[str, Any]) -> ResultHandle | None:
    result_id = str(payload.get("result_id") or payload.get("handle_id") or "").strip()
    if not result_id:
        return None
    source_object_id = str(
        payload.get("source_object_id")
        or payload.get("object_handle_id")
        or payload.get("source_id")
        or ""
    ).strip()
    metadata = dict(payload.get("metadata", {}) or {})
    for key in ("handle_kind", "mode", "labels", "filter_column"):
        value = payload.get(key)
        if value not in ("", None) and key not in metadata:
            metadata[key] = value
    return ResultHandle(
        result_id=result_id,
        result_kind=str(payload.get("result_kind", "") or "").strip(),
        owner_task_id=str(payload.get("owner_task_id", "") or "").strip(),
        source_object_id=source_object_id,
        artifact_id=str(payload.get("artifact_id", "") or "").strip(),
        identity=str(payload.get("identity", "") or result_id).strip(),
        locator=dict(payload.get("locator", {}) or {}),
        metadata=metadata,
    )


def _subset_handle_from_payload(payload: dict[str, Any]) -> SubsetHandle | None:
    subset_id = str(payload.get("subset_id") or payload.get("handle_id") or "").strip()
    if not subset_id:
        return None
    source_object_id = str(
        payload.get("source_object_id")
        or payload.get("object_handle_id")
        or payload.get("source_id")
        or ""
    ).strip()
    result_id = str(payload.get("result_id") or payload.get("result_handle_id") or "").strip()
    metadata = dict(payload.get("metadata", {}) or {})
    for key in ("handle_kind", "labels", "filter_column"):
        value = payload.get(key)
        if value not in ("", None) and key not in metadata:
            metadata[key] = value
    return SubsetHandle(
        subset_id=subset_id,
        subset_kind=str(payload.get("subset_kind", "") or "").strip(),
        owner_task_id=str(payload.get("owner_task_id", "") or "").strip(),
        result_id=result_id,
        source_object_id=source_object_id,
        artifact_id=str(payload.get("artifact_id", "") or "").strip(),
        identity=str(payload.get("identity", "") or subset_id).strip(),
        locator=dict(payload.get("locator", {}) or {}),
        metadata=metadata,
    )
