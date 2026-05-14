from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from evidence.mcp_models import MCPRequest


AgentEvidenceDomain = Literal["pdf", "rag", "table", "web", "code", "memory", "other"]
AgentEvidenceConfidence = Literal["high", "medium", "low", "unknown"]


@dataclass(frozen=True, slots=True)
class AgentEvidenceFact:
    fact_id: str
    claim: str
    source_refs: tuple[str, ...] = ()
    confidence: AgentEvidenceConfidence = "medium"
    scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_refs"] = list(self.source_refs)
        return payload


@dataclass(frozen=True, slots=True)
class AgentEvidenceItem:
    evidence_id: str
    kind: str
    source: str
    locator: dict[str, Any] = field(default_factory=dict)
    text_or_value: str = ""
    confidence: AgentEvidenceConfidence = "medium"
    visibility: str = "debug_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentEvidenceHint:
    hint_id: str
    suggestion: str
    basis_fact_ids: tuple[str, ...] = ()
    confidence: AgentEvidenceConfidence = "medium"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["basis_fact_ids"] = list(self.basis_fact_ids)
        return payload


@dataclass(frozen=True, slots=True)
class AgentEvidenceUnknown:
    unknown_id: str
    description: str
    impact: str = ""
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentEvidenceLimit:
    limit_id: str
    description: str
    kind: str = "data_boundary"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentEvidencePacket:
    packet_id: str
    source_agent_id: str
    target_task_id: str
    task_goal: str
    domain: AgentEvidenceDomain
    facts: tuple[AgentEvidenceFact, ...] = ()
    evidence: tuple[AgentEvidenceItem, ...] = ()
    method: dict[str, Any] = field(default_factory=dict)
    hints: tuple[AgentEvidenceHint, ...] = ()
    unknowns: tuple[AgentEvidenceUnknown, ...] = ()
    limits: tuple[AgentEvidenceLimit, ...] = ()
    confidence: AgentEvidenceConfidence = "unknown"
    relevance: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    domain_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "source_agent_id": self.source_agent_id,
            "target_task_id": self.target_task_id,
            "task_goal": self.task_goal,
            "domain": self.domain,
            "facts": [item.to_dict() for item in self.facts],
            "evidence": [item.to_dict() for item in self.evidence],
            "method": dict(self.method),
            "hints": [item.to_dict() for item in self.hints],
            "unknowns": [item.to_dict() for item in self.unknowns],
            "limits": [item.to_dict() for item in self.limits],
            "confidence": self.confidence,
            "relevance": dict(self.relevance),
            "freshness": dict(self.freshness),
            "domain_payload": dict(self.domain_payload),
        }

    def visible_summary(self, *, max_facts: int = 4, max_unknowns: int = 2) -> str:
        lines: list[str] = [
            f"Evidence packet {self.packet_id} from {self.source_agent_id} for {self.domain}.",
            f"Confidence: {self.confidence}.",
        ]
        if self.facts:
            lines.append("Facts:")
            for fact in self.facts[: max(1, int(max_facts or 1))]:
                lines.append(f"- {fact.claim}")
        if self.hints:
            lines.append("Hints:")
            for hint in self.hints[:2]:
                lines.append(f"- {hint.suggestion}")
        if self.unknowns:
            lines.append("Unknowns:")
            for unknown in self.unknowns[: max(1, int(max_unknowns or 1))]:
                lines.append(f"- {unknown.description}")
        if self.limits:
            lines.append("Limits:")
            for limit in self.limits[:2]:
                lines.append(f"- {limit.description}")
        return "\n".join(lines).strip()


def build_agent_evidence_packet_from_mcp_payload(
    *,
    mcp_result_payload: dict[str, Any],
    mcp_request: MCPRequest | None = None,
    source_agent_id: str = "",
    target_task_id: str = "",
    task_goal: str = "",
    domain: str = "",
) -> AgentEvidencePacket:
    canonical = dict(mcp_result_payload.get("canonical_result") or {})
    envelope = dict(mcp_result_payload.get("evidence_envelope") or {})
    diagnostics = dict(mcp_result_payload.get("diagnostics") or {})
    route = str(domain or mcp_result_payload.get("mcp_name") or (mcp_request.mcp_route if mcp_request else "") or "").strip()
    normalized_domain = _normalize_domain(route)
    request_goal = str(task_goal or (mcp_request.query if mcp_request else "") or "").strip()
    packet_source_agent = str(source_agent_id or mcp_result_payload.get("agent_id") or (mcp_request.agent_id if mcp_request else "") or "").strip()
    packet_task_id = str(target_task_id or (mcp_request.owner_task_id if mcp_request else "") or "").strip()

    evidence_items = _evidence_items_from_envelope(envelope)
    facts = _facts_from_evidence(evidence_items)
    unknowns = _unknowns_from_payload(canonical=canonical, envelope=envelope, diagnostics=diagnostics)
    limits = _limits_from_payload(canonical=canonical, diagnostics=diagnostics)
    hints = _hints_from_payload(canonical=canonical, facts=facts, envelope=envelope)
    confidence = _packet_confidence(canonical=canonical, evidence_items=evidence_items, unknowns=unknowns)
    method = {
        "mcp_route": route or normalized_domain,
        "mcp_status": str(mcp_result_payload.get("status") or ""),
        "request_id": str(mcp_request.request_id if mcp_request else ""),
        "query": str((mcp_request.query if mcp_request else envelope.get("query")) or ""),
        "diagnostics": diagnostics,
    }
    relevance = _relevance(goal=request_goal, facts=facts, hints=hints, ok=bool(canonical.get("ok", False)))
    freshness = {
        "source": "mcp_payload",
        "cache_state": str(diagnostics.get("cache_state") or diagnostics.get("conversion_cache_state") or "unknown"),
    }
    domain_payload = {
        "canonical_result_kind": str(canonical.get("result_kind") or ""),
        "canonical_bindings": dict(canonical.get("bindings") or {}),
        "canonical_presentation_hints": dict(canonical.get("presentation_hints") or {}),
        "envelope_ambiguity": dict(envelope.get("ambiguity") or {}),
        "envelope_diagnostics": dict(envelope.get("diagnostics") or {}),
        "source_objects": list(envelope.get("source_objects") or []),
        "document_candidates": list(envelope.get("document_candidates") or []),
        "dataset_candidates": list(envelope.get("dataset_candidates") or []),
        "table_candidates": list(envelope.get("table_candidates") or []),
    }
    return AgentEvidencePacket(
        packet_id=_stable_packet_id(
            normalized_domain,
            packet_source_agent,
            packet_task_id,
            request_goal,
            evidence_items,
            canonical,
        ),
        source_agent_id=packet_source_agent or "agent:unknown",
        target_task_id=packet_task_id,
        task_goal=request_goal,
        domain=normalized_domain,
        facts=facts,
        evidence=evidence_items,
        method=method,
        hints=hints,
        unknowns=unknowns,
        limits=limits,
        confidence=confidence,
        relevance=relevance,
        freshness=freshness,
        domain_payload=domain_payload,
    )


def build_agent_evidence_packet_from_web_payload(
    *,
    web_payload: dict[str, Any],
    source_agent_id: str = "",
    target_task_id: str = "",
    task_goal: str = "",
) -> AgentEvidencePacket:
    query = str(web_payload.get("query") or task_goal or "").strip()
    results = [dict(item) for item in list(web_payload.get("results") or []) if isinstance(item, dict)]
    evidence_items: list[AgentEvidenceItem] = []
    for index, item in enumerate(results, start=1):
        url = str(item.get("url") or "").strip()
        title = _compact_text(item.get("title") or url or "web source", limit=160)
        content = _compact_text(item.get("raw_content") or item.get("content") or "", limit=700)
        evidence_items.append(
            AgentEvidenceItem(
                evidence_id=f"web:evidence:{index}",
                kind="web_source_excerpt" if content else "web_search_result",
                source=url or title,
                locator={
                    "url": url,
                    "title": title,
                    "host": _host_from_url(url),
                    "published_date": str(item.get("published_date") or "").strip(),
                    "rank": index,
                },
                text_or_value=content or title,
                confidence=_confidence_from_score(item.get("score")),
                visibility="model_visible",
            )
        )
    canonical = {
        "ok": bool(web_payload.get("ok", True)) and bool(evidence_items),
        "answer": str(web_payload.get("answer") or "").strip(),
        "degraded_reason_typed": str(web_payload.get("error") or web_payload.get("degraded_reason_typed") or "").strip(),
    }
    facts = _facts_from_evidence(tuple(evidence_items))
    hints: list[AgentEvidenceHint] = []
    answer = _compact_text(web_payload.get("answer") or "", limit=700)
    if answer:
        hints.append(
            AgentEvidenceHint(
                hint_id="hint:web_answer",
                suggestion=answer,
                basis_fact_ids=tuple(fact.fact_id for fact in facts[:3]),
                confidence="medium" if facts else "low",
            )
        )
    if not evidence_items and query:
        hints.append(
            AgentEvidenceHint(
                hint_id="hint:web_query",
                suggestion=f"网页检索查询为：{query}",
                confidence="low",
            )
        )
    unknowns: list[AgentEvidenceUnknown] = []
    if not evidence_items:
        unknowns.append(
            AgentEvidenceUnknown(
                unknown_id="unknown:web_no_sources",
                description="网页研究没有返回可见来源。",
                impact="主 Agent 不应把该结果当作已核验事实。",
                next_step="更换查询词、放宽时效条件或告知用户外部检索不可用。",
            )
        )
    if canonical["degraded_reason_typed"]:
        unknowns.append(
            AgentEvidenceUnknown(
                unknown_id="unknown:web_degraded_reason",
                description=str(canonical["degraded_reason_typed"]),
                impact="网页检索能力可能不可用或返回不完整。",
                next_step="优先使用已有证据，必要时说明外部检索失败。",
            )
        )
    limits = _limits_from_payload(canonical=canonical, diagnostics={})
    confidence = _packet_confidence(
        canonical=canonical,
        evidence_items=tuple(evidence_items),
        unknowns=tuple(unknowns),
    )
    freshness = {
        "source": "web_search",
        "topic": str(web_payload.get("topic") or "general"),
        "time_range": str(web_payload.get("time_range") or ""),
        "response_time": str(web_payload.get("response_time") or ""),
    }
    domain_payload = {
        "query": query,
        "topic": str(web_payload.get("topic") or "general"),
        "request_id": str(web_payload.get("request_id") or ""),
        "result_count": len(results),
        "usage": dict(web_payload.get("usage") or {}),
        "auto_parameters": dict(web_payload.get("auto_parameters") or {}),
    }
    return AgentEvidencePacket(
        packet_id=_stable_packet_id("web", source_agent_id, target_task_id, task_goal, tuple(evidence_items), canonical),
        source_agent_id=source_agent_id or "agent:web_researcher",
        target_task_id=target_task_id,
        task_goal=task_goal or query,
        domain="web",
        facts=facts,
        evidence=tuple(evidence_items),
        method={
            "tool": "web_search",
            "query": query,
            "topic": str(web_payload.get("topic") or "general"),
            "max_results": len(results),
        },
        hints=tuple(hints),
        unknowns=tuple(unknowns),
        limits=limits,
        confidence=confidence,
        relevance=_relevance(goal=task_goal or query, facts=facts, hints=tuple(hints), ok=bool(canonical["ok"])),
        freshness=freshness,
        domain_payload=domain_payload,
    )


def visible_packet_summary(packet: AgentEvidencePacket | dict[str, Any]) -> str:
    if isinstance(packet, AgentEvidencePacket):
        return packet.visible_summary()
    facts = list(dict(packet).get("facts") or [])
    hints = list(dict(packet).get("hints") or [])
    unknowns = list(dict(packet).get("unknowns") or [])
    lines = [
        f"Evidence packet {dict(packet).get('packet_id') or ''} for {dict(packet).get('domain') or 'other'}.",
        f"Confidence: {dict(packet).get('confidence') or 'unknown'}.",
    ]
    if facts:
        lines.append("Facts:")
        for fact in facts[:4]:
            lines.append(f"- {dict(fact).get('claim') or ''}".rstrip())
    if hints:
        lines.append("Hints:")
        for hint in hints[:2]:
            lines.append(f"- {dict(hint).get('suggestion') or ''}".rstrip())
    if unknowns:
        lines.append("Unknowns:")
        for unknown in unknowns[:2]:
            lines.append(f"- {dict(unknown).get('description') or ''}".rstrip())
    return "\n".join(line for line in lines if line.strip()).strip()


def _evidence_items_from_envelope(envelope: dict[str, Any]) -> tuple[AgentEvidenceItem, ...]:
    items: list[AgentEvidenceItem] = []
    for index, raw_item in enumerate(list(envelope.get("evidence_items") or []), start=1):
        item = dict(raw_item or {})
        metadata = dict(item.get("metadata") or {})
        locator = dict(metadata.get("locator") or {})
        for key in ("page", "page_number", "row", "column", "sheet", "path", "uri"):
            if key in metadata and key not in locator:
                locator[key] = metadata.get(key)
        evidence_id = str(metadata.get("evidence_id") or metadata.get("artifact_id") or f"evidence:{index}")
        text = _compact_text(item.get("text") or item.get("value") or "", limit=600)
        items.append(
            AgentEvidenceItem(
                evidence_id=evidence_id,
                kind=str(item.get("kind") or "evidence"),
                source=str(item.get("source") or ""),
                locator=locator,
                text_or_value=text,
                confidence=_confidence_from_score(item.get("score")),
                visibility=str(item.get("visibility") or "debug_only"),
            )
        )
    return tuple(items)


def _facts_from_evidence(evidence_items: tuple[AgentEvidenceItem, ...]) -> tuple[AgentEvidenceFact, ...]:
    facts: list[AgentEvidenceFact] = []
    for index, item in enumerate(evidence_items, start=1):
        if not item.text_or_value:
            continue
        source = item.source.strip()
        locator = _format_locator(item.locator)
        claim_parts = [part for part in (source, locator, item.text_or_value) if part]
        facts.append(
            AgentEvidenceFact(
                fact_id=f"fact:{index}",
                claim=" | ".join(claim_parts),
                source_refs=(item.evidence_id,),
                confidence=item.confidence,
                scope=item.kind,
            )
        )
    return tuple(facts)


def _hints_from_payload(
    *,
    canonical: dict[str, Any],
    facts: tuple[AgentEvidenceFact, ...],
    envelope: dict[str, Any],
) -> tuple[AgentEvidenceHint, ...]:
    hints: list[AgentEvidenceHint] = []
    basis = tuple(fact.fact_id for fact in facts[:3])
    answer = _compact_text(canonical.get("answer") or "", limit=600)
    if answer:
        hints.append(
            AgentEvidenceHint(
                hint_id="hint:canonical_answer",
                suggestion=answer,
                basis_fact_ids=basis,
                confidence="medium" if basis else "low",
            )
        )
    for index, answer_candidate in enumerate(list(envelope.get("answer_candidates") or [])[:2], start=1):
        text = _compact_text(answer_candidate, limit=400)
        if not text:
            continue
        hints.append(
            AgentEvidenceHint(
                hint_id=f"hint:answer_candidate:{index}",
                suggestion=text,
                basis_fact_ids=basis,
                confidence="medium" if basis else "low",
            )
        )
    return tuple(hints)


def _unknowns_from_payload(
    *,
    canonical: dict[str, Any],
    envelope: dict[str, Any],
    diagnostics: dict[str, Any],
) -> tuple[AgentEvidenceUnknown, ...]:
    unknowns: list[AgentEvidenceUnknown] = []
    degraded = str(
        canonical.get("degraded_reason_typed")
        or canonical.get("degraded_reason")
        or diagnostics.get("degraded_reason_typed")
        or ""
    ).strip()
    if degraded:
        unknowns.append(
            AgentEvidenceUnknown(
                unknown_id="unknown:degraded_reason",
                description=degraded,
                impact="May affect whether the evidence is sufficient for the current task.",
                next_step="Use available facts first, then ask for or retrieve missing evidence if needed.",
            )
        )
    ambiguity = dict(envelope.get("ambiguity") or {})
    if ambiguity:
        unknowns.append(
            AgentEvidenceUnknown(
                unknown_id="unknown:ambiguity",
                description=_compact_text(json.dumps(ambiguity, ensure_ascii=True, sort_keys=True), limit=400),
                impact="Multiple interpretations or candidates may exist.",
                next_step="Compare candidate evidence against the current user goal.",
            )
        )
    if not list(envelope.get("evidence_items") or []) and not bool(canonical.get("ok", False)):
        unknowns.append(
            AgentEvidenceUnknown(
                unknown_id="unknown:no_visible_evidence",
                description="No model-visible evidence item was returned.",
                impact="The main agent should not treat the child result as a verified answer.",
                next_step="Recover source evidence or report the evidence gap.",
            )
        )
    return tuple(unknowns)


def _limits_from_payload(*, canonical: dict[str, Any], diagnostics: dict[str, Any]) -> tuple[AgentEvidenceLimit, ...]:
    values: list[str] = []
    for value in (
        canonical.get("degraded_reason_typed"),
        canonical.get("degraded_reason"),
        diagnostics.get("degraded_reason_typed"),
    ):
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return tuple(
        AgentEvidenceLimit(limit_id=f"limit:{index}", description=value, kind=_limit_kind(value))
        for index, value in enumerate(values, start=1)
    )


def _packet_confidence(
    *,
    canonical: dict[str, Any],
    evidence_items: tuple[AgentEvidenceItem, ...],
    unknowns: tuple[AgentEvidenceUnknown, ...],
) -> AgentEvidenceConfidence:
    if not bool(canonical.get("ok", False)):
        return "low"
    if not evidence_items:
        return "low"
    if unknowns:
        return "medium"
    if all(item.confidence == "high" for item in evidence_items):
        return "high"
    return "medium"


def _relevance(
    *,
    goal: str,
    facts: tuple[AgentEvidenceFact, ...],
    hints: tuple[AgentEvidenceHint, ...],
    ok: bool,
) -> dict[str, Any]:
    goal_terms = _terms(goal)
    text_terms = _terms(" ".join([fact.claim for fact in facts] + [hint.suggestion for hint in hints]))
    matched = sorted(goal_terms & text_terms)
    missing = sorted(goal_terms - text_terms)
    if not goal_terms:
        score = 0.0
    else:
        score = round(len(matched) / max(len(goal_terms), 1), 3)
    return {
        "score": score if ok else min(score, 0.5),
        "reason": "lexical_overlap_shadow_signal",
        "matched_goal_terms": matched[:20],
        "missing_goal_terms": missing[:20],
    }


def _normalize_domain(route: str) -> AgentEvidenceDomain:
    value = str(route or "").strip().lower()
    if value == "retrieval":
        return "rag"
    if value in {"structured_data", "table_analysis", "spreadsheet"}:
        return "table"
    if value in {"pdf", "rag", "table", "web", "code", "memory"}:
        return value  # type: ignore[return-value]
    return "other"


def _confidence_from_score(value: Any) -> AgentEvidenceConfidence:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "medium"
    if score >= 0.75:
        return "high"
    if score <= 0.25:
        return "low"
    return "medium"


def _limit_kind(value: str) -> str:
    normalized = value.lower()
    if "auth" in normalized or "permission" in normalized:
        return "authorization_boundary"
    if "missing" in normalized or "not_found" in normalized or "unavailable" in normalized:
        return "data_boundary"
    if "budget" in normalized or "timeout" in normalized:
        return "runtime_boundary"
    return "capability_boundary"


def _format_locator(locator: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("page", "page_number", "sheet", "row", "column", "path", "uri"):
        value = locator.get(key)
        if value not in ("", None, [], {}):
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def _host_from_url(value: str) -> str:
    text = str(value or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    return text.split("/", 1)[0].strip()


def _terms(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in str(value or "").replace("/", " ").replace("\\", " ").replace("_", " ").split():
        token = raw.strip(".,:;!?()[]{}<>\"'`").lower()
        if len(token) >= 2:
            tokens.add(token)
    return tokens


def _stable_packet_id(
    domain: str,
    source_agent_id: str,
    target_task_id: str,
    task_goal: str,
    evidence_items: tuple[AgentEvidenceItem, ...],
    canonical: dict[str, Any],
) -> str:
    payload = {
        "domain": domain,
        "source_agent_id": source_agent_id,
        "target_task_id": target_task_id,
        "task_goal": task_goal,
        "evidence_ids": [item.evidence_id for item in evidence_items],
        "answer": str(canonical.get("answer") or "")[:160],
        "ok": bool(canonical.get("ok", False)),
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"agent_evidence_packet:{digest}"
