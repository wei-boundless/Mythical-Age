from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence


def normalize_text(text: str) -> str:
    lowered = (text or "").lower().strip()
    return re.sub(r"\s+", " ", lowered)


def _tokenize_cjk_span(span: str) -> list[str]:
    cleaned = span.strip()
    if not cleaned:
        return []
    if len(cleaned) == 1:
        return [cleaned]

    tokens: list[str] = []
    for size in (2, 3, 4):
        if len(cleaned) < size:
            continue
        tokens.extend(cleaned[idx : idx + size] for idx in range(len(cleaned) - size + 1))

    if len(cleaned) <= 8:
        tokens.append(cleaned)
    return tokens or [cleaned]


def tokenize_for_bm25(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    tokens: list[str] = []
    for part in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[a-z0-9_]+", part):
            tokens.append(part)
        else:
            tokens.extend(_tokenize_cjk_span(part))
    return [token for token in tokens if token]


def tokenize_for_keyword_search(text: str) -> list[str]:
    tokens = tokenize_for_bm25(text)
    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped


def keyword_score(query: str, text: str, source: str = "") -> tuple[float, list[str]]:
    """Compatibility-only lexical scorer retained for older callers.

    Main retrieval paths should use ``BM25Index`` instead.
    """

    query_norm = normalize_text(query)
    text_norm = normalize_text(text)
    source_norm = normalize_text(source)
    reasons: list[str] = []
    score = 0.0

    if not query_norm or not text_norm:
        return score, reasons

    if query_norm in text_norm:
        score += 5.0
        reasons.append("exact_query")

    query_terms = tokenize_for_keyword_search(query_norm)
    if query_terms:
        overlap = sum(1 for term in query_terms if term in text_norm)
        if overlap:
            score += overlap * 1.5
            reasons.append(f"term_overlap:{overlap}")

        if any(term in source_norm for term in query_terms[:3]):
            score += 0.8
            reasons.append("source_overlap")

    preview = text_norm[:200]
    if query_norm in preview:
        score += 1.2
        reasons.append("early_exact")

    return score, reasons


def build_searchable_text(
    text: str,
    *,
    source: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    metadata = metadata or {}
    section = str(metadata.get("section", "") or "").strip()
    title = str(metadata.get("title", "") or "").strip()
    header = metadata.get("header")

    parts: list[str] = []
    if source:
        parts.append(source)
    if title:
        parts.append(title)
    if section and section != title:
        parts.append(section)
    if isinstance(header, list):
        joined_header = " ".join(str(item).strip() for item in header if str(item).strip())
        if joined_header:
            parts.append(joined_header)
    elif header:
        parts.append(str(header).strip())
    if text:
        parts.append(text)
    return "\n".join(part for part in parts if part).strip()


@dataclass(slots=True)
class BM25Match:
    index: int
    score: float
    matched_terms: list[str]
    matched_term_count: int


class BM25Index:
    def __init__(
        self,
        corpus_tokens: Sequence[Sequence[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = max(float(k1), 0.1)
        self.b = min(max(float(b), 0.0), 1.0)
        self.doc_term_freqs = [Counter(tokens) for tokens in corpus_tokens]
        self.doc_lengths = [sum(counter.values()) for counter in self.doc_term_freqs]
        self.doc_count = len(self.doc_term_freqs)
        self.avg_doc_len = (
            sum(self.doc_lengths) / self.doc_count
            if self.doc_count > 0
            else 0.0
        )

        document_frequency: Counter[str] = Counter()
        for counter in self.doc_term_freqs:
            document_frequency.update(counter.keys())

        self.idf: dict[str, float] = {
            term: math.log(1.0 + (self.doc_count - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    @classmethod
    def from_texts(
        cls,
        texts: Sequence[str],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> BM25Index:
        return cls([tokenize_for_bm25(text) for text in texts], k1=k1, b=b)

    def search(self, query: str, *, top_k: int) -> list[BM25Match]:
        if top_k <= 0 or self.doc_count <= 0:
            return []

        query_tokens = tokenize_for_bm25(query)
        if not query_tokens:
            return []

        query_term_freq = Counter(query_tokens)
        results: list[BM25Match] = []
        avg_doc_len = self.avg_doc_len or 1.0

        for index, term_freq in enumerate(self.doc_term_freqs):
            doc_len = self.doc_lengths[index] or 1
            denominator_bias = self.k1 * (1.0 - self.b + self.b * doc_len / avg_doc_len)

            score = 0.0
            term_contributions: dict[str, float] = {}
            for term, query_tf in query_term_freq.items():
                freq = term_freq.get(term, 0)
                if freq <= 0:
                    continue
                idf = self.idf.get(term, 0.0)
                contribution = idf * (freq * (self.k1 + 1.0)) / (freq + denominator_bias)
                contribution *= query_tf
                score += contribution
                term_contributions[term] = contribution

            if score <= 0:
                continue

            matched_terms = [
                term
                for term, _ in sorted(
                    term_contributions.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:6]
            ]
            results.append(
                BM25Match(
                    index=index,
                    score=score,
                    matched_terms=matched_terms,
                    matched_term_count=len(term_contributions),
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]


def required_bm25_term_matches(query: str) -> int:
    unique_terms = len(set(tokenize_for_bm25(query)))
    if unique_terms <= 2:
        return 1
    if unique_terms <= 5:
        return 2
    return max(2, math.ceil(unique_terms * 0.35))


def reciprocal_rank_fusion(rank: int, *, weight: float = 1.0, k: float = 50.0) -> float:
    return weight / (rank + k)


def merge_scores(*parts: float) -> float:
    return sum(parts)


def normalize_dense_score(score: float) -> float:
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


def normalize_keyword_score(score: float, *, ceiling: float | None = None) -> float:
    if score <= 0:
        return 0.0
    if ceiling is not None and ceiling > 0:
        return min(score / ceiling, 1.0)
    return score / (score + 1.0)


def attach_reason_list(item: dict[str, Any], *reasons: list[str]) -> dict[str, Any]:
    merged: list[str] = []
    for group in reasons:
        for reason in group:
            if reason not in merged:
                merged.append(reason)
    item["hybrid_reasons"] = merged
    return item
