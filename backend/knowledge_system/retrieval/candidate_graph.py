from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from capability_system.units.mcp.local.retrieval.models import RetrievalHit


@dataclass(slots=True)
class CandidateNode:
    key: tuple[Any, ...]
    bucket_kind: str
    hits: list[RetrievalHit] = field(default_factory=list)

    def add(self, hit: RetrievalHit) -> None:
        self.hits.append(hit)

    def to_hit(self, *, query_mode: str, chain_version: str) -> RetrievalHit:
        bucket = sorted(self.hits, key=lambda item: float(item.score or 0.0), reverse=True)
        primary = bucket[0]
        metadata = dict(primary.metadata)
        metadata["retrieval_stage"] = "candidate_graph"
        metadata["candidate_graph_node_key"] = list(self.key)
        metadata["candidate_graph_bucket_kind"] = self.bucket_kind
        metadata["candidate_graph_hit_count"] = len(bucket)
        metadata["merged_hit_count"] = len(bucket)
        metadata["merged_block_ids"] = [
            str(item.block_id)
            for item in bucket
            if str(item.block_id or "").strip()
        ]
        metadata["result_granularity"] = result_granularity(primary, query_mode=query_mode)
        metadata["chain_version"] = chain_version
        return RetrievalHit(
            text=merge_hit_texts(bucket),
            source=primary.source,
            modality=primary.modality,
            score=max(float(item.score or 0.0) for item in bucket),
            page=primary.page,
            metadata=metadata,
            hit_id=primary.hit_id,
            doc_id=primary.doc_id,
            block_id=primary.block_id,
            object_ref_id=primary.object_ref_id,
            block_type=primary.block_type,
            section_path=primary.section_path,
            score_breakdown=merge_score_breakdown(bucket),
            retrieval_modes=merge_hit_modes(bucket),
            parser_backend=primary.parser_backend,
            quality_flags=primary.quality_flags,
        )


class CandidateGraph:
    def __init__(self, *, query_mode: str, chain_version: str) -> None:
        self.query_mode = query_mode
        self.chain_version = chain_version
        self._nodes: dict[tuple[Any, ...], CandidateNode] = {}

    def add_hit(self, hit: RetrievalHit) -> None:
        key = candidate_key(hit, self.query_mode)
        node = self._nodes.get(key)
        if node is None:
            node = CandidateNode(key=key, bucket_kind=str(key[0]))
            self._nodes[key] = node
        node.add(hit)

    def merged_hits(self, *, top_k: int) -> list[RetrievalHit]:
        hits = [
            node.to_hit(query_mode=self.query_mode, chain_version=self.chain_version)
            for node in self._nodes.values()
            if node.hits
        ]
        hits.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return hits[:top_k]


def coalesce_with_candidate_graph(
    hits: list[object],
    *,
    query_mode: str,
    chain_version: str,
    top_k: int,
) -> list[RetrievalHit]:
    graph = CandidateGraph(query_mode=query_mode, chain_version=chain_version)
    for raw_hit in hits:
        graph.add_hit(as_retrieval_hit(raw_hit))
    return graph.merged_hits(top_k=top_k)


def as_retrieval_hit(raw_hit: object) -> RetrievalHit:
    if isinstance(raw_hit, RetrievalHit):
        return raw_hit
    return RetrievalHit(
        text=str(getattr(raw_hit, "text", "")),
        source=str(getattr(raw_hit, "source", "")),
        modality=str(getattr(raw_hit, "modality", "text")),
        score=float(getattr(raw_hit, "score", 0.0) or 0.0),
        page=getattr(raw_hit, "page", None),
        metadata=dict(getattr(raw_hit, "metadata", {}) or {}),
        hit_id=getattr(raw_hit, "hit_id", None),
        doc_id=getattr(raw_hit, "doc_id", None),
        block_id=getattr(raw_hit, "block_id", None),
        object_ref_id=getattr(raw_hit, "object_ref_id", None),
        block_type=getattr(raw_hit, "block_type", None),
        section_path=tuple(getattr(raw_hit, "section_path", ()) or ()),
        score_breakdown=dict(getattr(raw_hit, "score_breakdown", {}) or {}),
        retrieval_modes=tuple(getattr(raw_hit, "retrieval_modes", ()) or ()),
        parser_backend=str(getattr(raw_hit, "parser_backend", "") or ""),
        quality_flags=tuple(getattr(raw_hit, "quality_flags", ()) or ()),
    )


def candidate_key(hit: RetrievalHit, query_mode: str) -> tuple[Any, ...]:
    doc_id = str(hit.doc_id or "").strip()
    source = str(hit.source or "").strip()
    object_ref_id = str(hit.object_ref_id or "").strip()
    page = int(hit.page or 0)
    mode = str(query_mode or "semantic_lookup")
    unit_view = str(dict(hit.metadata).get("unit_view", "") or "").strip()
    if object_ref_id:
        return ("object", doc_id or source, object_ref_id)
    if unit_view == "table_row_window":
        return ("table_window", doc_id or source, page, hit.block_id or hit.hit_id or hit.source)
    if mode == "document_overview":
        return ("doc", doc_id or source)
    if page > 0:
        return ("page", doc_id or source, page)
    return ("doc", doc_id or source)


def result_granularity(hit: RetrievalHit, *, query_mode: str) -> str:
    metadata = dict(hit.metadata)
    if metadata.get("unit_view") == "table_row_window":
        return "object"
    if str(hit.object_ref_id or "").strip():
        return "object"
    if str(query_mode or "") == "document_overview":
        return "document"
    if hit.page not in (None, "", 0):
        return "page"
    return "block"


def merge_hit_texts(hits: list[RetrievalHit]) -> str:
    snippets: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for hit in hits:
        text = re.sub(r"\s+", " ", str(hit.text or "")).strip()
        if not text or text in seen:
            continue
        if any(text in existing for existing in seen):
            continue
        seen.add(text)
        snippets.append(text)
        total_chars += len(text)
        if len(snippets) >= 3 or total_chars >= 1800:
            break
    return "\n\n".join(snippets).strip()


def merge_hit_modes(hits: list[RetrievalHit]) -> tuple[str, ...]:
    modes: list[str] = []
    for hit in hits:
        for mode in hit.retrieval_modes:
            if mode not in modes:
                modes.append(str(mode))
    return tuple(modes)


def merge_score_breakdown(hits: list[RetrievalHit]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for hit in hits:
        for key, value in dict(hit.score_breakdown).items():
            merged[key] = max(float(merged.get(key, 0.0)), float(value or 0.0))
    merged["merged_hit_count"] = float(len(hits))
    merged["final"] = max(float(hit.score or 0.0) for hit in hits) if hits else 0.0
    return merged


