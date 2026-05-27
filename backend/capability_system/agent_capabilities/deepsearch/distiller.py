from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from runtime.model_gateway.model_runtime import stringify_content

from .web_text import best_web_excerpt, clean_web_text


EVIDENCE_DISTILLER_PROMPT = """你是一名检索证据提炼员。

你只负责把搜索和网页抓取结果提炼成可追溯的证据。
你不能替主 Agent 写最终回答，也不能把没有来源支持的判断写成事实。
你需要保留来源 URL、标题、关键摘录、来源类型、置信度、未知项和冲突点。
如果内容不足、来源不可访问、发布时间不明或只有二手来源，你必须明确标记限制。
输出必须是结构化 JSON，包含 claims、unknowns、conflicts 和 source_refs。"""


@dataclass(frozen=True, slots=True)
class DistilledClaim:
    claim_id: str
    claim: str
    source_url: str
    source_title: str
    source_type: str
    confidence: str
    excerpt: str
    artifact_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim": self.claim,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "source_type": self.source_type,
            "confidence": self.confidence,
            "excerpt": self.excerpt,
            "artifact_ref": self.artifact_ref,
        }


@dataclass(frozen=True, slots=True)
class DistillationResult:
    claims: tuple[DistilledClaim, ...]
    unknowns: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    prompt: str = EVIDENCE_DISTILLER_PROMPT
    method: str = "deterministic_distiller"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [item.to_dict() for item in self.claims],
            "unknowns": list(self.unknowns),
            "conflicts": list(self.conflicts),
            "prompt": self.prompt,
            "method": self.method,
        }


class SearchEvidenceDistiller:
    def distill(self, *, query: str, sources: list[dict[str, Any]]) -> DistillationResult:
        claims: list[DistilledClaim] = []
        unknowns: list[str] = []
        seen_claims: set[str] = set()
        for index, source in enumerate(sources, start=1):
            url = str(source.get("url") or "").strip()
            title = clean_web_text(source.get("title") or url or "web source", limit=180)
            excerpt = best_web_excerpt(source, limit=1000)
            if not excerpt:
                unknowns.append(f"source_without_readable_excerpt:{url or title}")
                continue
            claim = _extract_claim(title=title, excerpt=excerpt)
            if not claim:
                unknowns.append(f"source_without_distilled_claim:{url or title}")
                continue
            key = claim.lower()
            if key in seen_claims:
                continue
            seen_claims.add(key)
            source_type = str(source.get("_source_type") or source.get("source_type") or _source_type(url=url, text=f"{title} {excerpt}"))
            confidence = str(source.get("confidence") or _confidence_from_source(source_type=source_type, score=source.get("score")))
            claims.append(
                DistilledClaim(
                    claim_id=f"claim:{index}",
                    claim=claim,
                    source_url=url,
                    source_title=title,
                    source_type=source_type,
                    confidence=confidence,
                    excerpt=clean_web_text(excerpt, limit=700),
                    artifact_ref=str(source.get("artifact_ref") or _artifact_ref(url=url, title=title)),
                )
            )
        if not claims and query:
            unknowns.append("distiller_no_claims")
        return DistillationResult(claims=tuple(claims), unknowns=tuple(_dedupe(unknowns)))


class ModelBackedSearchEvidenceDistiller(SearchEvidenceDistiller):
    def __init__(self, model_runtime: Any, *, fallback: SearchEvidenceDistiller | None = None, max_sources: int = 8) -> None:
        self.model_runtime = model_runtime
        self.fallback = fallback or SearchEvidenceDistiller()
        self.max_sources = max(1, int(max_sources or 8))

    async def adistill(self, *, query: str, sources: list[dict[str, Any]]) -> DistillationResult:
        fallback_result = self.fallback.distill(query=query, sources=sources)
        invoker = getattr(self.model_runtime, "invoke_messages", None)
        if not callable(invoker):
            return DistillationResult(
                claims=fallback_result.claims,
                unknowns=(*fallback_result.unknowns, "model_distiller_unavailable"),
                conflicts=fallback_result.conflicts,
                method="deterministic_distiller_fallback",
            )
        messages = [
            {"role": "system", "content": EVIDENCE_DISTILLER_PROMPT},
            {"role": "user", "content": _distiller_user_payload(query=query, sources=sources[: self.max_sources])},
        ]
        try:
            response = await invoker(messages)
        except Exception as exc:
            return DistillationResult(
                claims=fallback_result.claims,
                unknowns=(*fallback_result.unknowns, f"model_distiller_failed:{exc.__class__.__name__}"),
                conflicts=fallback_result.conflicts,
                method="deterministic_distiller_fallback",
            )
        parsed = _parse_model_distillation(stringify_content(getattr(response, "content", response)), sources=sources)
        if not parsed.claims:
            return DistillationResult(
                claims=fallback_result.claims,
                unknowns=(*fallback_result.unknowns, "model_distiller_returned_no_claims"),
                conflicts=fallback_result.conflicts,
                method="deterministic_distiller_fallback",
            )
        return parsed

    def distill(self, *, query: str, sources: list[dict[str, Any]]) -> DistillationResult:
        return self.fallback.distill(query=query, sources=sources)


def _extract_claim(*, title: str, excerpt: str) -> str:
    sentences = _sentences(excerpt)
    preferred = _preferred_sentence(sentences) or (sentences[0] if sentences else clean_web_text(excerpt, limit=320))
    if not preferred:
        return ""
    title_text = clean_web_text(title, limit=160)
    if title_text and title_text.lower() not in preferred.lower():
        return _compact(f"{title_text}. {preferred}", 420)
    return _compact(preferred, 420)


def _distiller_user_payload(*, query: str, sources: list[dict[str, Any]]) -> str:
    payload = {
        "query": query,
        "instructions": {
            "output": "Return JSON only. Do not include markdown fences.",
            "schema": {
                "claims": [
                    {
                        "claim": "short evidence-backed statement",
                        "source_url": "URL",
                        "source_title": "title",
                        "source_type": "official|primary|secondary",
                        "confidence": "high|medium|low|unknown",
                        "excerpt": "supporting quote or paraphrase from source",
                    }
                ],
                "unknowns": ["missing or uncertain items"],
                "conflicts": ["conflicting evidence"],
            },
        },
        "sources": [
            {
                "url": str(source.get("url") or ""),
                "title": clean_web_text(source.get("title") or "", limit=180),
                "source_type": str(source.get("_source_type") or source.get("source_type") or ""),
                "score": source.get("score"),
                "content": best_web_excerpt(source, limit=1600),
            }
            for source in sources
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_model_distillation(content: str, *, sources: list[dict[str, Any]]) -> DistillationResult:
    payload = _extract_json_object(content)
    if not payload:
        return DistillationResult(claims=(), unknowns=("model_distiller_invalid_json",), method="model_distiller")
    claims: list[DistilledClaim] = []
    source_by_url = {str(source.get("url") or "").strip(): source for source in sources if str(source.get("url") or "").strip()}
    for index, raw in enumerate(list(payload.get("claims") or []), start=1):
        if not isinstance(raw, dict):
            continue
        claim = clean_web_text(raw.get("claim") or "", limit=420)
        url = str(raw.get("source_url") or "").strip()
        if not claim or not url:
            continue
        source = dict(source_by_url.get(url) or {})
        title = clean_web_text(raw.get("source_title") or source.get("title") or url, limit=180)
        source_type = _verified_source_type(
            model_value=raw.get("source_type"),
            source=source,
            url=url,
            text=f"{title} {claim}",
        )
        claims.append(
            DistilledClaim(
                claim_id=f"claim:{index}",
                claim=claim,
                source_url=url,
                source_title=title,
                source_type=source_type,
                confidence=_normalize_confidence(raw.get("confidence")),
                excerpt=clean_web_text(raw.get("excerpt") or claim, limit=700),
                artifact_ref=str(source.get("artifact_ref") or _artifact_ref(url=url, title=title)),
            )
        )
    return DistillationResult(
        claims=tuple(claims),
        unknowns=tuple(str(item) for item in list(payload.get("unknowns") or []) if str(item).strip()),
        conflicts=tuple(str(item) for item in list(payload.get("conflicts") or []) if str(item).strip()),
        method="model_distiller",
    )


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    candidates = [text]
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _preferred_sentence(sentences: list[str]) -> str:
    keywords = (
        "official",
        "documentation",
        "announced",
        "release",
        "available",
        "supports",
        "requires",
        "confirms",
        "published",
        "updated",
        "api",
        "tool",
    )
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            return sentence
    return ""


def _sentences(text: str) -> list[str]:
    cleaned = clean_web_text(text, limit=1400)
    parts = re.split(r"(?<=[.!?。！？])\s+", cleaned)
    return [_compact(part, 500) for part in parts if len(part.strip()) >= 30 and not _looks_like_code_or_json(part)]


def _source_type(*, url: str, text: str) -> str:
    lowered = f"{url} {text}".lower()
    if any(token in lowered for token in ("community.openai.com", "forum.", "discuss.")):
        return "secondary"
    if any(token in lowered for token in ("openai.com", "microsoft.com", ".gov", ".edu", "github.com", "docs.", "developers.")):
        return "official"
    if any(token in lowered for token in ("official announcement", "press release", "documentation")):
        return "primary"
    return "secondary"


def _verified_source_type(*, model_value: Any, source: dict[str, Any], url: str, text: str) -> str:
    deterministic = str(source.get("_source_type") or source.get("source_type") or _source_type(url=url, text=text))
    model_type = str(model_value or "").strip().lower()
    if deterministic == "secondary":
        return "secondary"
    if model_type in {"official", "primary", "secondary"}:
        return model_type
    return deterministic if deterministic in {"official", "primary", "secondary"} else "secondary"


def _confidence_from_source(*, source_type: str, score: Any) -> str:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        numeric = 0.5
    if source_type in {"official", "primary"} and numeric >= 0.7:
        return "high"
    if numeric <= 0.25:
        return "low"
    return "medium"


def _normalize_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low", "unknown"}:
        return text
    return "medium"


def _artifact_ref(*, url: str, title: str) -> str:
    seed = url or title
    digest = hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"artifact:web_source:{digest}"


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _looks_like_code_or_json(value: str) -> bool:
    text = " ".join(str(value or "").split())
    lowered = text.lower()
    if any(token in lowered for token in ("client.responses.create", "from openai import", "\"role\":", "\"content\":", "```")):
        return True
    symbol_count = sum(1 for char in text if char in "{}[]=:;,`")
    word_count = len(re.findall(r"[A-Za-z][A-Za-z'-]+", text))
    return symbol_count > max(12, len(text) // 12) and word_count < 35


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result
