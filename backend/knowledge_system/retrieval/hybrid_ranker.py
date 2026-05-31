from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from capability_system.units.mcp.local.retrieval.models import RetrievalHit


HitKeyFn = Callable[[RetrievalHit], tuple[Any, ...]]
ResultGranularityFn = Callable[[RetrievalHit], str]


@dataclass(slots=True)
class _RankEntry:
    key: tuple[Any, ...]
    primary: RetrievalHit
    score: float = 0.0
    hit_count: int = 0
    channels: list[str] = field(default_factory=list)
    breakdown: dict[str, float] = field(default_factory=dict)


class HybridRanker:
    """Single authority for dense/lexical fusion before candidate coalescing."""

    def __init__(
        self,
        *,
        rank_constant: float = 60.0,
        normalized_score_weight: float = 0.35,
        corroboration_weight: float = 0.04,
        multi_channel_weight: float = 0.03,
    ) -> None:
        self.rank_constant = max(float(rank_constant or 60.0), 1.0)
        self.normalized_score_weight = max(float(normalized_score_weight or 0.0), 0.0)
        self.corroboration_weight = max(float(corroboration_weight or 0.0), 0.0)
        self.multi_channel_weight = max(float(multi_channel_weight or 0.0), 0.0)

    def rank(
        self,
        channels: dict[str, list[RetrievalHit]],
        *,
        top_k: int,
        query_mode: str,
        weights: dict[str, float] | None = None,
        key_fn: HitKeyFn | None = None,
        result_granularity_fn: ResultGranularityFn | None = None,
        chain_version: str = "",
    ) -> list[RetrievalHit]:
        key_for = key_fn or default_hit_key
        granularity_for = result_granularity_fn or default_result_granularity
        channel_weights = dict(weights or {})
        merged: dict[tuple[Any, ...], _RankEntry] = {}
        for channel, hits in channels.items():
            normalized_scores = _normalized_scores(hits)
            weight = float(channel_weights.get(channel, 1.0) or 1.0)
            for rank, hit in enumerate(hits, start=1):
                key = key_for(hit)
                entry = merged.get(key)
                if entry is None:
                    entry = _RankEntry(key=key, primary=hit)
                    merged[key] = entry
                if channel == "dense":
                    entry.primary = hit
                raw_score = max(float(hit.score or 0.0), 0.0)
                normalized = normalized_scores[rank - 1]
                rrf = weight / (self.rank_constant + float(rank))
                normalized_component = weight * normalized * self.normalized_score_weight
                entry.score += rrf + normalized_component
                entry.hit_count += 1
                if channel not in entry.channels:
                    entry.channels.append(channel)
                _max_breakdown(entry.breakdown, f"{channel}_raw", raw_score)
                _max_breakdown(entry.breakdown, f"{channel}_normalized", normalized)
                _min_positive_breakdown(entry.breakdown, f"{channel}_rank", float(rank))
                entry.breakdown[f"{channel}_rrf"] = float(entry.breakdown.get(f"{channel}_rrf", 0.0) + rrf)
                entry.breakdown[f"{channel}_component"] = float(
                    entry.breakdown.get(f"{channel}_component", 0.0) + normalized_component
                )

        ranked = [
            self._to_hit(
                entry,
                query_mode=query_mode,
                result_granularity_fn=granularity_for,
                chain_version=chain_version,
            )
            for entry in merged.values()
        ]
        ranked.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return self._diversify(ranked, top_k=max(int(top_k or 1), 1))

    def _to_hit(
        self,
        entry: _RankEntry,
        *,
        query_mode: str,
        result_granularity_fn: ResultGranularityFn,
        chain_version: str,
    ) -> RetrievalHit:
        base = entry.primary
        channel_count = len(entry.channels)
        corroboration_boost = self.corroboration_weight * (1.0 - (1.0 / max(entry.hit_count, 1)))
        multi_channel_boost = self.multi_channel_weight * max(channel_count - 1, 0)
        policy_boost = _policy_boost(base, query_mode=query_mode)
        metadata_bias = _metadata_bias(base)
        final_score = max(entry.score + corroboration_boost + multi_channel_boost + policy_boost + metadata_bias, 0.0)
        breakdown = dict(entry.breakdown)
        breakdown["fusion"] = float(entry.score)
        breakdown["corroboration_boost"] = float(corroboration_boost)
        breakdown["multi_channel_boost"] = float(multi_channel_boost)
        breakdown["policy_boost"] = float(policy_boost)
        breakdown["metadata_bias"] = float(metadata_bias)
        breakdown["hit_count"] = float(entry.hit_count)
        breakdown["final"] = float(final_score)
        modes = _merge_modes(base, entry.channels)
        metadata = dict(base.metadata)
        metadata["retrieval_stage"] = "hybrid_ranker"
        metadata["hybrid_ranker_channels"] = list(entry.channels)
        metadata["hybrid_ranker_hit_count"] = entry.hit_count
        metadata["result_granularity"] = result_granularity_fn(base)
        if chain_version:
            metadata["chain_version"] = chain_version
        return RetrievalHit(
            text=base.text,
            source=base.source,
            modality=base.modality,
            score=final_score,
            page=base.page,
            metadata=metadata,
            hit_id=base.hit_id,
            doc_id=base.doc_id,
            block_id=base.block_id,
            object_ref_id=base.object_ref_id,
            block_type=base.block_type,
            section_path=base.section_path,
            score_breakdown=breakdown,
            retrieval_modes=modes,
            parser_backend=base.parser_backend,
            quality_flags=base.quality_flags,
        )

    def _diversify(self, hits: list[RetrievalHit], *, top_k: int) -> list[RetrievalHit]:
        selected: list[RetrievalHit] = []
        remaining = list(hits)
        while remaining and len(selected) < top_k:
            best = max(
                remaining,
                key=lambda item: (
                    float(item.score or 0.0) - _diversity_penalty(item, selected),
                    float(item.score or 0.0),
                ),
            )
            remaining.remove(best)
            penalty = _diversity_penalty(best, selected)
            selected.append(_with_diversity_penalty(best, penalty) if penalty else best)
        return selected


def default_hit_key(hit: RetrievalHit) -> tuple[Any, ...]:
    if hit.hit_id:
        return ("hit_id", hit.hit_id)
    return (
        str(hit.doc_id or ""),
        str(hit.block_id or ""),
        str(hit.object_ref_id or ""),
        str(hit.source or ""),
        int(hit.page or 0),
    )


def default_result_granularity(hit: RetrievalHit) -> str:
    if str(hit.object_ref_id or "").strip():
        return "object"
    if hit.page not in (None, "", 0):
        return "page"
    return "block"


def _normalized_scores(hits: list[RetrievalHit]) -> list[float]:
    raw_scores = [max(float(hit.score or 0.0), 0.0) for hit in hits]
    if not raw_scores:
        return []
    low = min(raw_scores)
    high = max(raw_scores)
    if high <= 0:
        return [0.0 for _ in raw_scores]
    if high == low:
        return [1.0 for _ in raw_scores]
    return [(score - low) / (high - low) for score in raw_scores]


def _policy_boost(hit: RetrievalHit, *, query_mode: str) -> float:
    mode = str(query_mode or "")
    if mode == "page_grounded_lookup" and hit.page not in (None, "", 0):
        return 0.05
    if mode == "table_lookup" and str(hit.modality or "").lower() == "table":
        return 0.06
    if mode == "document_overview" and str(hit.block_type or "") in {"document_summary", "parent_section"}:
        return 0.04
    return 0.0


def _metadata_bias(hit: RetrievalHit) -> float:
    metadata = dict(hit.metadata)
    modality = str(hit.modality or "").lower()
    score = 0.0
    if modality == "table":
        score += 0.08
    elif modality == "image":
        score += 0.03
    if metadata.get("ocr") is True:
        score -= 0.01
    if metadata.get("collection") == "durable_memory":
        score += 0.05
    return score


def _merge_modes(hit: RetrievalHit, channels: list[str]) -> tuple[str, ...]:
    modes: list[str] = []
    for mode in [*list(hit.retrieval_modes or ()), *channels]:
        if mode and mode not in modes:
            modes.append(str(mode))
    if len(modes) > 1 and "fusion" not in modes:
        modes.append("fusion")
    return tuple(modes)


def _diversity_penalty(hit: RetrievalHit, selected: list[RetrievalHit]) -> float:
    if not selected:
        return 0.0
    doc = str(hit.doc_id or hit.source or "")
    page = int(hit.page or 0)
    penalty = 0.0
    for prior in selected:
        prior_doc = str(prior.doc_id or prior.source or "")
        prior_page = int(prior.page or 0)
        if doc and doc == prior_doc and page and page == prior_page:
            penalty += 0.05
        elif doc and doc == prior_doc:
            penalty += 0.02
    return min(penalty, 0.2)


def _with_diversity_penalty(hit: RetrievalHit, penalty: float) -> RetrievalHit:
    score = max(float(hit.score or 0.0) - penalty, 0.0)
    metadata = dict(hit.metadata)
    metadata["diversity_penalty"] = float(penalty)
    breakdown = dict(hit.score_breakdown)
    breakdown["diversity_penalty"] = float(penalty)
    breakdown["final_before_diversity"] = float(hit.score or 0.0)
    breakdown["final"] = score
    return RetrievalHit(
        text=hit.text,
        source=hit.source,
        modality=hit.modality,
        score=score,
        page=hit.page,
        metadata=metadata,
        hit_id=hit.hit_id,
        doc_id=hit.doc_id,
        block_id=hit.block_id,
        object_ref_id=hit.object_ref_id,
        block_type=hit.block_type,
        section_path=hit.section_path,
        score_breakdown=breakdown,
        retrieval_modes=hit.retrieval_modes,
        parser_backend=hit.parser_backend,
        quality_flags=hit.quality_flags,
    )


def _max_breakdown(payload: dict[str, float], key: str, value: float) -> None:
    payload[key] = max(float(payload.get(key, 0.0)), float(value or 0.0))


def _min_positive_breakdown(payload: dict[str, float], key: str, value: float) -> None:
    current = float(payload.get(key, 0.0) or 0.0)
    payload[key] = float(value) if current <= 0 else min(current, float(value))
