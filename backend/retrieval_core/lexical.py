from __future__ import annotations

import heapq
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

try:
    import jieba  # type: ignore
except Exception:  # pragma: no cover - fallback is intentional
    jieba = None


def normalize_text(text: str) -> str:
    lowered = str(text or "").lower().strip()
    return re.sub(r"\s+", " ", lowered)


def tokenizer_name() -> str:
    if jieba is not None:
        return "jieba_search_with_bigram_fallback_v1"
    return "mixed_word_cjk_bigram_v1"


@lru_cache(maxsize=1)
def _jieba_available() -> bool:
    return jieba is not None


def _legacy_bigram_tokens(normalized: str) -> list[str]:
    tokens: list[str] = []
    for chunk in re.findall(r"[a-z0-9][a-z0-9_./:-]*|[\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            if len(chunk) == 1:
                tokens.append(chunk)
            else:
                tokens.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
        else:
            token = chunk.strip(".,;:!?()[]{}\"'")
            if token:
                tokens.append(token)
    return tokens


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _dedupe_preserve_order(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        normalized = str(token or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _jieba_tokens(normalized: str) -> list[str]:
    if not _jieba_available():
        return []
    pieces = [
        str(token or "").strip()
        for token in jieba.cut_for_search(normalized)
        if str(token or "").strip()
    ]
    cleaned: list[str] = []
    for piece in pieces:
        if re.fullmatch(r"[\u4e00-\u9fff]+", piece):
            cleaned.append(piece)
            continue
        token = piece.strip(".,;:!?()[]{}\"'")
        if token:
            cleaned.append(token)
    return cleaned


def lexical_tokens(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    fallback_tokens = _legacy_bigram_tokens(normalized)
    if not _contains_cjk(normalized):
        return fallback_tokens
    jieba_tokens = _jieba_tokens(normalized)
    if not jieba_tokens:
        return fallback_tokens
    return _dedupe_preserve_order(jieba_tokens + fallback_tokens)


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


def build_lexical_index_payload(texts: Sequence[str]) -> dict[str, Any]:
    postings: dict[str, dict[str, list[int]]] = {}
    doc_lengths: list[int] = []
    for doc_idx, text in enumerate(texts):
        tokens = lexical_tokens(text)
        term_freqs: dict[str, int] = {}
        for token in tokens:
            term_freqs[token] = term_freqs.get(token, 0) + 1
        doc_lengths.append(sum(term_freqs.values()))
        for term, tf in term_freqs.items():
            entry = postings.setdefault(term, {"doc_indexes": [], "term_freqs": []})
            entry["doc_indexes"].append(doc_idx)
            entry["term_freqs"].append(tf)
    avg_doc_length = (sum(doc_lengths) / len(doc_lengths)) if doc_lengths else 0.0
    doc_count = len(texts)
    term_ids = {term: index for index, term in enumerate(sorted(postings))}
    idf = {
        term: math.log(1.0 + ((max(doc_count, 1) - len(entry["doc_indexes"]) + 0.5) / (len(entry["doc_indexes"]) + 0.5)))
        for term, entry in postings.items()
    }
    return {
        "doc_lengths": doc_lengths,
        "avg_doc_length": avg_doc_length,
        "doc_count": doc_count,
        "k1": 1.5,
        "b": 0.75,
        "postings": postings,
        "term_ids": term_ids,
        "idf": idf,
    }


def build_sparse_vector_payload(
    text: str,
    *,
    term_ids: dict[str, int],
    idf: dict[str, float] | None = None,
) -> tuple[list[int], list[float]]:
    token_freqs = Counter(lexical_tokens(text))
    if not token_freqs:
        return ([], [])
    indices: list[int] = []
    values: list[float] = []
    for term, tf in sorted(token_freqs.items(), key=lambda item: term_ids.get(item[0], 10**18)):
        term_id = term_ids.get(term)
        if term_id is None:
            continue
        local_idf = float((idf or {}).get(term, 1.0) or 1.0)
        weight = (1.0 + math.log(float(tf))) * local_idf
        indices.append(int(term_id))
        values.append(float(weight))
    return (indices, values)


def score_lexical_query(
    lexical_index: dict[str, Any],
    query_tokens: list[str],
    *,
    top_k: int,
) -> list[tuple[int, float]]:
    if not query_tokens:
        return []
    postings = dict(lexical_index.get("postings", {}) or {})
    doc_lengths = list(lexical_index.get("doc_lengths", []) or [])
    doc_count = max(1, int(lexical_index.get("doc_count", 0) or 0))
    avg_doc_length = float(lexical_index.get("avg_doc_length", 0.0) or 0.0) or 1.0
    k1 = float(lexical_index.get("k1", 1.5) or 1.5)
    b = float(lexical_index.get("b", 0.75) or 0.75)
    scores: dict[int, float] = {}
    for term in query_tokens:
        posting = dict(postings.get(term, {}) or {})
        doc_indexes = list(posting.get("doc_indexes", []) or [])
        term_freqs = list(posting.get("term_freqs", []) or [])
        if not doc_indexes:
            continue
        df = len(doc_indexes)
        idf = math.log(1.0 + ((doc_count - df + 0.5) / (df + 0.5)))
        for doc_idx, tf in zip(doc_indexes, term_freqs, strict=False):
            doc_len = float(doc_lengths[doc_idx]) if doc_idx < len(doc_lengths) else 0.0
            denom = float(tf) + k1 * (1.0 - b + b * (doc_len / avg_doc_length))
            contribution = idf * ((float(tf) * (k1 + 1.0)) / denom) if denom > 0 else 0.0
            scores[doc_idx] = scores.get(doc_idx, 0.0) + contribution
    if not scores:
        return []
    return heapq.nlargest(top_k, scores.items(), key=lambda item: item[1])


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
        self.avg_doc_len = sum(self.doc_lengths) / self.doc_count if self.doc_count > 0 else 0.0

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
        return cls([lexical_tokens(text) for text in texts], k1=k1, b=b)

    def search(self, query: str, *, top_k: int) -> list[BM25Match]:
        if top_k <= 0 or self.doc_count <= 0:
            return []

        query_tokens = lexical_tokens(query)
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
    unique_terms = len(set(lexical_tokens(query)))
    if unique_terms <= 2:
        return 1
    if unique_terms <= 5:
        return 2
    return max(2, math.ceil(unique_terms * 0.35))
