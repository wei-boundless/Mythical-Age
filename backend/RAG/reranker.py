from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import httpx

from config import Settings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RerankScore:
    score: float
    reasons: list[str]


class DictReranker(Protocol):
    def rerank_dict_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        text_key: str = "text",
        metadata_key: str = "metadata",
    ) -> list[dict[str, Any]]: ...


class NoopReranker:
    """Explicit no-op reranker used when rerank is disabled."""

    def rerank_dict_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        text_key: str = "text",
        metadata_key: str = "metadata",
    ) -> list[dict[str, Any]]:
        _ = query, text_key, metadata_key
        return [dict(item) for item in results]


class HeuristicReranker:
    """Low-cost lexical reranker for short factual queries.

    This is intentionally lightweight so it can improve top-1 ranking without
    adding another model dependency or extra API cost.
    """

    def rerank_dict_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        text_key: str = "text",
        metadata_key: str = "metadata",
    ) -> list[dict[str, Any]]:
        rescored: list[dict[str, Any]] = []
        for rank, item in enumerate(results, start=1):
            base_score = float(item.get("score", 0.0) or 0.0)
            score = self.score(
                query=query,
                text=str(item.get(text_key, "") or ""),
                metadata=item.get(metadata_key, {}) or {},
                source=str(item.get("source", "") or ""),
                base_score=base_score,
                rank=rank,
            )
            updated = dict(item)
            updated["retrieval_score"] = float(item.get("retrieval_score", base_score) or 0.0)
            updated["score"] = base_score + score.score
            updated["rerank_backend"] = "heuristic"
            updated["rerank_score"] = score.score
            updated["rerank_reasons"] = score.reasons
            updated["rerank_applied"] = True
            rescored.append(updated)
        return sorted(rescored, key=lambda row: float(row.get("score", 0.0)), reverse=True)

    def score(
        self,
        *,
        query: str,
        text: str,
        metadata: dict[str, Any],
        source: str = "",
        base_score: float = 0.0,
        rank: int = 1,
    ) -> RerankScore:
        normalized_query = self._normalize(query)
        normalized_text = self._normalize(text)
        normalized_source = self._normalize(source)
        reasons: list[str] = []
        boost = 0.0

        if not normalized_query or not normalized_text:
            return RerankScore(score=0.0, reasons=reasons)

        if normalized_query in normalized_text:
            boost += 0.35
            reasons.append("exact_query_match")

        query_terms = self._terms(normalized_query)
        text_terms = set(self._terms(normalized_text))

        if query_terms:
            overlap = sum(1 for term in query_terms if term in text_terms)
            ratio = overlap / max(len(query_terms), 1)
            if ratio > 0:
                boost += 0.25 * ratio
                reasons.append(f"term_overlap:{overlap}/{len(query_terms)}")

        preview = normalized_text[:240]
        if normalized_query in preview:
            boost += 0.12
            reasons.append("early_match")

        if any(term and term in normalized_source for term in query_terms[:3]):
            boost += 0.08
            reasons.append("source_match")

        title = self._normalize(str(metadata.get("title", "") or metadata.get("section", "") or ""))
        if title and any(term in title for term in query_terms[:3]):
            boost += 0.08
            reasons.append("title_or_section_match")

        if len(query_terms) <= 2 and len(normalized_query) <= 12 and normalized_query in normalized_text:
            boost += 0.10
            reasons.append("short_query_exact_bonus")

        boost += min(max(base_score, 0.0), 1.0) * 0.05
        boost += max(0.0, 0.03 - (rank - 1) * 0.005)

        return RerankScore(score=boost, reasons=reasons)

    def _normalize(self, text: str) -> str:
        lowered = text.lower().strip()
        lowered = re.sub(r"\s+", " ", lowered)
        return lowered

    def _terms(self, text: str) -> list[str]:
        latin = re.findall(r"[a-z0-9_]+", text)
        cjk = [token for token in re.findall(r"[\u4e00-\u9fff]{1,6}", text) if token]
        terms = [token for token in latin + cjk if token]
        deduped: list[str] = []
        for term in terms:
            if term not in deduped:
                deduped.append(term)
        return deduped


class CrossEncoderReranker:
    """Standard model reranker backed by a sentence-transformers CrossEncoder."""

    def __init__(
        self,
        *,
        model_name: str,
        top_n: int = 8,
        batch_size: int = 8,
        max_length: int = 512,
        device: str | None = None,
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for cross-encoder reranking"
            ) from exc

        kwargs: dict[str, Any] = {}
        if device:
            kwargs["device"] = device
        if max_length > 0:
            kwargs["max_length"] = max_length
        self._model = CrossEncoder(model_name, **kwargs)
        self.model_name = model_name
        self.top_n = max(top_n, 1)
        self.batch_size = max(batch_size, 1)
        self.max_length = max(max_length, 1)

    def rerank_dict_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        text_key: str = "text",
        metadata_key: str = "metadata",
    ) -> list[dict[str, Any]]:
        if not query.strip() or not results:
            return results

        head = [dict(item) for item in results[: self.top_n]]
        tail = [dict(item) for item in results[self.top_n :]]
        pairs = [(query, str(item.get(text_key, "") or "")) for item in head]
        if not pairs:
            return results

        scores = self._model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        rerank_scores = [float(score) for score in scores]
        min_rerank = min(rerank_scores) if rerank_scores else 0.0
        max_rerank = max(rerank_scores) if rerank_scores else 0.0
        rerank_range = max_rerank - min_rerank

        retrieval_scores = [float(item.get("retrieval_score", item.get("score", 0.0)) or 0.0) for item in head]
        min_retrieval = min(retrieval_scores) if retrieval_scores else 0.0
        max_retrieval = max(retrieval_scores) if retrieval_scores else 0.0
        retrieval_range = max_retrieval - min_retrieval

        rescored: list[dict[str, Any]] = []
        for item, score in zip(head, scores, strict=False):
            base_score = float(item.get("score", 0.0) or 0.0)
            item["retrieval_score"] = float(item.get("retrieval_score", base_score) or 0.0)
            rerank_score = float(score)
            rerank_normalized = (
                (rerank_score - min_rerank) / rerank_range
                if rerank_range > 0
                else 0.0
            )
            retrieval_normalized = (
                (item["retrieval_score"] - min_retrieval) / retrieval_range
                if retrieval_range > 0
                else 0.0
            )
            item["rerank_backend"] = "cross_encoder"
            item["rerank_model"] = self.model_name
            item["rerank_score"] = rerank_score
            item["rerank_score_normalized"] = rerank_normalized
            item["rerank_retrieval_score_normalized"] = retrieval_normalized
            item["rerank_score_blend"] = {
                "cross_encoder": rerank_score,
                "cross_encoder_normalized": rerank_normalized,
                "retrieval_normalized": retrieval_normalized,
                "retrieval_weight": 0.05,
            }
            item["rerank_reasons"] = ["cross_encoder_score", "retrieval_prior_blend"]
            item["score"] = rerank_normalized + 0.05 * retrieval_normalized
            item["rerank_applied"] = True
            rescored.append(item)

        rescored.sort(
            key=lambda row: (
                float(row.get("score", 0.0)),
                float(row.get("rerank_score", 0.0)),
                float(row.get("retrieval_score", 0.0)),
            ),
            reverse=True,
        )

        for item in tail:
            base_score = float(item.get("score", 0.0) or 0.0)
            item["retrieval_score"] = float(item.get("retrieval_score", base_score) or 0.0)
            item["rerank_backend"] = item.get("rerank_backend", "tail_passthrough")
            item["rerank_reasons"] = item.get("rerank_reasons", ["outside_rerank_top_n"])
            item["rerank_applied"] = False

        return rescored + tail


class RemoteApiReranker:
    """Remote reranker for provider-hosted text rerank APIs."""

    def __init__(
        self,
        *,
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str,
        top_n: int = 8,
        timeout_seconds: int = 30,
    ) -> None:
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.top_n = max(top_n, 1)
        self.timeout_seconds = max(timeout_seconds, 5)
        self.rerank_url = self._resolve_rerank_url(base_url)
        self._fallback = HeuristicReranker()

    def rerank_dict_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        text_key: str = "text",
        metadata_key: str = "metadata",
    ) -> list[dict[str, Any]]:
        if not query.strip() or not results:
            return results

        head = [dict(item) for item in results[: self.top_n]]
        tail = [dict(item) for item in results[self.top_n :]]
        try:
            ranked = self._remote_rerank(query=query, results=head, text_key=text_key)
        except Exception:
            return self._fallback.rerank_dict_results(
                query=query,
                results=results,
                text_key=text_key,
                metadata_key=metadata_key,
            )

        rescored: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in ranked:
            index = int(item.get("index", -1))
            if index < 0 or index >= len(head) or index in seen:
                continue
            seen.add(index)
            updated = dict(head[index])
            base_score = float(updated.get("score", 0.0) or 0.0)
            updated["retrieval_score"] = float(updated.get("retrieval_score", base_score) or 0.0)
            updated["rerank_backend"] = f"{self.provider}_api"
            updated["rerank_model"] = self.model_name
            updated["rerank_score"] = float(item.get("relevance_score", 0.0) or 0.0)
            updated["rerank_reasons"] = ["remote_api_score"]
            updated["score"] = float(item.get("relevance_score", 0.0) or 0.0)
            updated["rerank_applied"] = True
            rescored.append(updated)

        for index, original in enumerate(head):
            if index in seen:
                continue
            updated = dict(original)
            base_score = float(updated.get("score", 0.0) or 0.0)
            updated["retrieval_score"] = float(updated.get("retrieval_score", base_score) or 0.0)
            updated["rerank_backend"] = updated.get("rerank_backend", "remote_api_tail_passthrough")
            updated["rerank_reasons"] = updated.get("rerank_reasons", ["missing_remote_rerank_score"])
            updated["rerank_applied"] = False
            rescored.append(updated)

        for item in tail:
            base_score = float(item.get("score", 0.0) or 0.0)
            item["retrieval_score"] = float(item.get("retrieval_score", base_score) or 0.0)
            item["rerank_backend"] = item.get("rerank_backend", "tail_passthrough")
            item["rerank_reasons"] = item.get("rerank_reasons", ["outside_rerank_top_n"])
            item["rerank_applied"] = False

        return rescored + tail

    def _remote_rerank(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        text_key: str,
    ) -> list[dict[str, Any]]:
        payload = {
            "model": self.model_name,
            "query": query,
            "documents": [str(item.get(text_key, "") or "") for item in results],
            "top_n": len(results),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = client.post(self.rerank_url, headers=headers, json=payload)
            response.raise_for_status()

        data = response.json()
        error_code = str(data.get("code", "") or "").strip()
        if error_code:
            message = str(data.get("message", "") or "remote rerank request failed")
            raise RuntimeError(f"{error_code}: {message}")

        output = data.get("output", {}) or {}
        rows = output.get("results", data.get("results", [])) or []
        ranked: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ranked.append(
                {
                    "index": int(row.get("index", -1)),
                    "relevance_score": float(row.get("relevance_score", 0.0) or 0.0),
                }
            )
        return ranked

    def _resolve_rerank_url(self, base_url: str) -> str:
        normalized = (base_url or "").strip()
        if not normalized:
            raise RuntimeError("Remote rerank base URL is required.")
        if normalized.endswith("/reranks"):
            return normalized.rstrip("/")

        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError(f"Unsupported remote rerank base URL: {base_url}")

        service_root = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")
        lowered = path.lower()
        if "compatible-api" in lowered:
            if lowered.endswith("/v1"):
                return urljoin(service_root.rstrip("/") + "/", path.lstrip("/") + "/reranks")
            return urljoin(service_root.rstrip("/") + "/", path.lstrip("/") + "/v1/reranks")
        if "compatible-mode" in lowered:
            return urljoin(service_root.rstrip("/") + "/", "compatible-api/v1/reranks")
        if lowered.endswith("/v1"):
            return urljoin(service_root.rstrip("/") + "/", path.lstrip("/") + "/reranks")
        return urljoin(service_root.rstrip("/") + "/", "compatible-api/v1/reranks")


def build_reranker(settings: Settings) -> DictReranker:
    if not settings.rerank_enabled:
        return NoopReranker()

    provider = (settings.rerank_provider or "heuristic").strip().lower()
    if provider == "heuristic":
        return HeuristicReranker()

    if provider in {"cross_encoder", "sentence_transformers", "huggingface"}:
        model_name = settings.rerank_model
        if not model_name:
            logger.warning("Cross-encoder rerank requested but RERANK_MODEL is empty; falling back to heuristic reranker.")
            return HeuristicReranker()
        try:
            return CrossEncoderReranker(
                model_name=model_name,
                top_n=settings.rerank_top_n,
                batch_size=settings.rerank_batch_size,
                max_length=settings.rerank_max_length,
                device=settings.rerank_device,
            )
        except Exception:
            logger.exception(
                "Failed to initialize cross-encoder reranker model=%s; falling back to heuristic reranker.",
                model_name,
            )
            return HeuristicReranker()

    if provider in {"bailian", "dashscope", "qwen", "remote_api", "remote"}:
        model_name = settings.rerank_model
        api_key = settings.rerank_api_key
        base_url = settings.rerank_base_url
        if not model_name or not api_key or not base_url:
            logger.warning(
                "Remote rerank requested but model/api_key/base_url is incomplete; falling back to heuristic reranker."
            )
            return HeuristicReranker()
        try:
            return RemoteApiReranker(
                provider=provider,
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                top_n=settings.rerank_top_n,
            )
        except Exception:
            logger.exception(
                "Failed to initialize remote reranker provider=%s model=%s; falling back to heuristic reranker.",
                provider,
                model_name,
            )
            return HeuristicReranker()

    logger.warning("Unknown rerank provider=%s; falling back to heuristic reranker.", provider)
    return HeuristicReranker()
