from __future__ import annotations

import hashlib
import re
from typing import Any

from evidence import AgentEvidenceFact, AgentEvidenceHint, AgentEvidenceItem, AgentEvidencePacket, AgentEvidenceUnknown

from .web_text import best_web_excerpt, clean_web_text


OFFICIAL_HOST_MARKERS = (
    "openai.com",
    "microsoft.com",
    "github.com",
    ".gov",
    ".edu",
)
COMMUNITY_HOST_MARKERS = (
    "community.openai.com",
    "forum.",
    "discuss.",
)
SECONDARY_HOST_MARKERS = (
    "medium.com",
    "datacamp.com",
    "towardsdatascience.com",
    "dev.to",
    "reddit.com",
    "stackoverflow.com",
)


def build_deepsearch_evidence_packet(
    *,
    web_payload: dict[str, Any],
    source_agent_id: str,
    target_task_id: str,
    task_goal: str,
) -> AgentEvidencePacket:
    query = str(web_payload.get("query") or task_goal or "").strip()
    results = _rank_sources([dict(item) for item in list(web_payload.get("results") or []) if isinstance(item, dict)], query=query)
    distilled_claims = _distilled_claims(web_payload)
    evidence = tuple(_evidence_from_distilled_claims(distilled_claims) or _evidence_from_ranked_sources(results))
    facts = tuple(_facts_from_distilled_claims(distilled_claims, evidence) or _facts_from_ranked_sources(results, evidence))
    unknowns = _unknowns(web_payload=web_payload, evidence=evidence)
    hints = _hints(facts=facts, ranked_sources=results)
    confidence = _confidence(ranked_sources=results, unknowns=unknowns)
    source_ranking = [_source_ranking_payload(item) for item in results]
    return AgentEvidencePacket(
        packet_id=_packet_id(source_agent_id, target_task_id, query, results),
        source_agent_id=source_agent_id or "agent:web_researcher",
        target_task_id=target_task_id,
        task_goal=task_goal or query,
        domain="web",
        facts=facts,
        evidence=evidence,
        method={
            "tool": "deepsearch",
            "query": query,
            "topic": str(web_payload.get("topic") or "general"),
            "source_ranking": source_ranking[:8],
            "distillation_method": str(dict(dict(web_payload.get("deepsearch") or {}).get("distillation") or {}).get("method") or ""),
        },
        hints=hints,
        unknowns=unknowns,
        limits=(),
        confidence=confidence,
        relevance=_relevance(goal=task_goal or query, facts=facts),
        freshness={
            "source": "deepsearch",
            "topic": str(web_payload.get("topic") or "general"),
            "time_range": str(web_payload.get("time_range") or ""),
        },
        domain_payload={
            "query": query,
            "topic": str(web_payload.get("topic") or "general"),
            "result_count": len(results),
            "usage": dict(web_payload.get("usage") or {}),
            "deepsearch": dict(web_payload.get("deepsearch") or {}),
            "source_ranking": source_ranking,
            "distilled_claim_count": len(distilled_claims),
        },
    )


def _distilled_claims(web_payload: dict[str, Any]) -> list[dict[str, Any]]:
    deepsearch = dict(web_payload.get("deepsearch") or {})
    return [dict(item) for item in list(deepsearch.get("distilled_claims") or []) if isinstance(item, dict)]


def _evidence_from_distilled_claims(claims: list[dict[str, Any]]) -> list[AgentEvidenceItem]:
    evidence: list[AgentEvidenceItem] = []
    for rank, claim in enumerate(claims, start=1):
        url = str(claim.get("source_url") or "").strip()
        title = clean_web_text(claim.get("source_title") or url or "web source", limit=180)
        excerpt = clean_web_text(claim.get("excerpt") or claim.get("claim") or "", limit=900)
        evidence.append(
            AgentEvidenceItem(
                evidence_id=f"web:evidence:{rank}",
                kind="deepsearch_distilled_claim",
                source=url or title,
                locator={
                    "url": url,
                    "title": title,
                    "host": _host(url),
                    "rank": rank,
                    "source_type": str(claim.get("source_type") or "secondary"),
                    "artifact_ref": str(claim.get("artifact_ref") or ""),
                },
                text_or_value=excerpt or title,
                confidence=_normalize_confidence(claim.get("confidence")),
                visibility="model_visible",
            )
        )
    return evidence


def _facts_from_distilled_claims(claims: list[dict[str, Any]], evidence: tuple[AgentEvidenceItem, ...]) -> list[AgentEvidenceFact]:
    facts: list[AgentEvidenceFact] = []
    for index, claim in enumerate(claims, start=1):
        if index > len(evidence):
            break
        claim_text = clean_web_text(claim.get("claim") or "", limit=430)
        if not claim_text:
            continue
        source_type = str(claim.get("source_type") or "secondary")
        host = _host(str(claim.get("source_url") or ""))
        prefix = "官方/一手来源" if source_type in {"official", "primary"} else "二手来源"
        facts.append(
            AgentEvidenceFact(
                fact_id=f"fact:{index}",
                claim=f"{prefix} {host}: {claim_text}" if host else f"{prefix}: {claim_text}",
                source_refs=(evidence[index - 1].evidence_id,),
                confidence=_normalize_confidence(claim.get("confidence")),
                scope=f"deepsearch.{source_type}",
            )
        )
    return facts


def _rank_sources(results: list[dict[str, Any]], *, query: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        host = _host(str(item.get("url") or ""))
        source_type = _source_type(host=host, item=item)
        quality_score = _quality_score(item=item, host=host, source_type=source_type, original_rank=index, query=query)
        ranked.append(
            {
                **item,
                "_original_rank": index,
                "_host": host,
                "_source_type": source_type,
                "_quality_score": quality_score,
            }
        )
    ranked.sort(key=lambda item: (-float(item["_quality_score"]), int(item["_original_rank"])))
    return ranked


def _evidence_from_ranked_sources(results: list[dict[str, Any]]) -> list[AgentEvidenceItem]:
    evidence: list[AgentEvidenceItem] = []
    for rank, item in enumerate(results, start=1):
        excerpt = best_web_excerpt(item, limit=900)
        url = str(item.get("url") or "").strip()
        title = clean_web_text(item.get("title") or url or "web source", limit=180)
        evidence.append(
            AgentEvidenceItem(
                evidence_id=f"web:evidence:{rank}",
                kind="deepsearch_source_excerpt" if excerpt else "deepsearch_search_result",
                source=url or title,
                locator={
                    "url": url,
                    "title": title,
                    "host": str(item.get("_host") or _host(url)),
                    "rank": rank,
                    "original_rank": int(item.get("_original_rank") or rank),
                    "source_type": str(item.get("_source_type") or "secondary"),
                    "quality_score": round(float(item.get("_quality_score") or 0.0), 3),
                    "published_date": str(item.get("published_date") or "").strip(),
                },
                text_or_value=excerpt or title,
                confidence=_confidence_from_quality(float(item.get("_quality_score") or 0.0)),
                visibility="model_visible",
            )
        )
    return evidence


def _facts_from_ranked_sources(results: list[dict[str, Any]], evidence: tuple[AgentEvidenceItem, ...]) -> list[AgentEvidenceFact]:
    facts: list[AgentEvidenceFact] = []
    for index, item in enumerate(results, start=1):
        if index > len(evidence):
            break
        evidence_item = evidence[index - 1]
        claim_text = _extract_fact_claim(item, evidence_item.text_or_value)
        if not claim_text:
            continue
        source_type = str(item.get("_source_type") or "secondary")
        host = str(item.get("_host") or "")
        prefix = "官方/一手来源" if source_type in {"official", "primary"} else "二手来源"
        facts.append(
            AgentEvidenceFact(
                fact_id=f"fact:{index}",
                claim=f"{prefix} {host}: {claim_text}",
                source_refs=(evidence_item.evidence_id,),
                confidence=evidence_item.confidence,
                scope=f"deepsearch.{source_type}",
            )
        )
    return facts


def _extract_fact_claim(item: dict[str, Any], excerpt: str) -> str:
    title = clean_web_text(item.get("title") or "", limit=160)
    text = clean_web_text(excerpt, limit=1200)
    sentences = _sentences(text)
    preferred = _preferred_sentence(sentences) or (sentences[0] if sentences else "")
    supporting = _supporting_sentence(sentences, preferred)
    if supporting:
        preferred = f"{preferred} {supporting}"
    if title and preferred and title.lower() not in preferred.lower():
        return _compact(f"{title}. {preferred}", 360)
    return _compact(preferred or title, 360)


def _preferred_sentence(sentences: list[str]) -> str:
    keywords = (
        "official",
        "documentation",
        "responses api",
        "web search",
        "tool",
        "supports",
        "available",
        "built-in",
        "search the web",
    )
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            return sentence
    return ""


def _supporting_sentence(sentences: list[str], selected: str) -> str:
    selected_text = str(selected or "")
    selected_terms = _terms(selected_text)
    for sentence in sentences:
        if sentence == selected:
            continue
        lowered = sentence.lower()
        if "responses api" in lowered and "responses" not in selected_terms:
            return sentence
        if "web search tool" in lowered and "tool" not in selected_terms:
            return sentence
    return ""


def _sentences(text: str) -> list[str]:
    cleaned = clean_web_text(text, limit=1600)
    parts = re.split(r"(?<=[.!?。！？])\s+", cleaned)
    return [_compact(part, 500) for part in parts if len(part.strip()) >= 35]


def _source_type(*, host: str, item: dict[str, Any]) -> str:
    haystack = " ".join(str(item.get(key) or "").lower() for key in ("url", "title", "content", "clean_text"))
    lowered_host = host.lower()
    if any(marker in lowered_host for marker in COMMUNITY_HOST_MARKERS):
        return "secondary"
    if any(marker in lowered_host for marker in OFFICIAL_HOST_MARKERS):
        return "official"
    if any(token in haystack for token in ("official documentation", "official announcement", "press release")):
        return "primary"
    if any(marker in lowered_host for marker in SECONDARY_HOST_MARKERS):
        return "secondary"
    return "secondary"


def _quality_score(*, item: dict[str, Any], host: str, source_type: str, original_rank: int, query: str) -> float:
    score = 0.2
    try:
        score += min(max(float(item.get("score") or 0.0), 0.0), 1.0) * 0.35
    except (TypeError, ValueError):
        score += 0.15
    if source_type == "official":
        score += 0.35
    elif source_type == "primary":
        score += 0.28
    if str(item.get("published_date") or "").strip():
        score += 0.04
    if _query_overlap(query, " ".join(str(item.get(key) or "") for key in ("title", "clean_text", "content"))) >= 0.25:
        score += 0.08
    score -= min(max(original_rank - 1, 0), 10) * 0.01
    if any(marker in host.lower() for marker in (*SECONDARY_HOST_MARKERS, *COMMUNITY_HOST_MARKERS)):
        score -= 0.05
    return max(0.0, min(1.0, score))


def _unknowns(*, web_payload: dict[str, Any], evidence: tuple[AgentEvidenceItem, ...]) -> tuple[AgentEvidenceUnknown, ...]:
    values: list[AgentEvidenceUnknown] = []
    error = str(web_payload.get("error") or "").strip()
    if error:
        values.append(
            AgentEvidenceUnknown(
                unknown_id="unknown:deepsearch_error",
                description=error,
                impact="部分搜索或抓取步骤失败，证据可能不完整。",
                next_step="优先使用高质量来源；必要时追加查询。",
            )
        )
    if not evidence:
        values.append(
            AgentEvidenceUnknown(
                unknown_id="unknown:deepsearch_no_sources",
                description="DeepSearch 没有返回可见来源。",
                impact="主 Agent 不应把该结果当作已核验事实。",
                next_step="更换查询词或检查搜索服务。",
            )
        )
    return tuple(values)


def _hints(*, facts: tuple[AgentEvidenceFact, ...], ranked_sources: list[dict[str, Any]]) -> tuple[AgentEvidenceHint, ...]:
    official_count = sum(1 for item in ranked_sources if str(item.get("_source_type")) == "official")
    if official_count <= 0:
        return ()
    return (
        AgentEvidenceHint(
            hint_id="hint:deepsearch_official_sources",
            suggestion=f"DeepSearch 找到 {official_count} 个官方/一手来源；主 Agent 应优先引用这些来源。",
            basis_fact_ids=tuple(fact.fact_id for fact in facts[: min(official_count, 3)]),
            confidence="medium",
        ),
    )


def _confidence(*, ranked_sources: list[dict[str, Any]], unknowns: tuple[AgentEvidenceUnknown, ...]) -> str:
    if not ranked_sources:
        return "low"
    official_count = sum(1 for item in ranked_sources if str(item.get("_source_type")) in {"official", "primary"})
    if unknowns:
        return "medium" if official_count else "low"
    if official_count >= 1 and len(ranked_sources) >= 2:
        return "high"
    return "medium"


def _source_ranking_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": str(item.get("url") or ""),
        "title": clean_web_text(item.get("title") or "", limit=180),
        "host": str(item.get("_host") or ""),
        "source_type": str(item.get("_source_type") or "secondary"),
        "quality_score": round(float(item.get("_quality_score") or 0.0), 3),
        "original_rank": int(item.get("_original_rank") or 0),
        "published_date": str(item.get("published_date") or ""),
    }


def _relevance(*, goal: str, facts: tuple[AgentEvidenceFact, ...]) -> dict[str, Any]:
    goal_terms = _terms(goal)
    fact_terms = _terms(" ".join(fact.claim for fact in facts))
    matched = sorted(goal_terms & fact_terms)
    return {
        "score": round(len(matched) / max(len(goal_terms), 1), 3) if goal_terms else 0.0,
        "reason": "deepsearch_fact_overlap",
        "matched_goal_terms": matched[:20],
    }


def _host(value: str) -> str:
    text = str(value or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    return text.split("/", 1)[0].lower()


def _terms(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-zA-Z0-9]+", str(value or "").lower()) if len(token) >= 3}


def _query_overlap(query: str, text: str) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    return len(query_terms & _terms(text)) / max(len(query_terms), 1)


def _confidence_from_quality(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score <= 0.35:
        return "low"
    return "medium"


def _normalize_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low", "unknown"}:
        return text
    return "medium"


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _packet_id(source_agent_id: str, target_task_id: str, query: str, results: list[dict[str, Any]]) -> str:
    seed = "|".join([source_agent_id, target_task_id, query, *[str(item.get("url") or "") for item in results[:8]]])
    return "packet:web:deepsearch:" + hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:16]
