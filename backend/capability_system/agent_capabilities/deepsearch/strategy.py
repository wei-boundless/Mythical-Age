from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import SearchRuntimeConfig


@dataclass(frozen=True, slots=True)
class ResearchQuestion:
    question_id: str
    question: str
    priority: str = "normal"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SearchPlanningStep:
    research_questions: tuple[ResearchQuestion, ...]
    initial_queries: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_questions": [item.to_dict() for item in self.research_questions],
            "initial_queries": list(self.initial_queries),
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class EvidenceReviewStep:
    should_stop: bool
    stop_reason: str
    gaps: tuple[str, ...] = ()
    next_queries: tuple[str, ...] = ()
    accepted_source_count: int = 0
    primary_source_count: int = 0
    distilled_claim_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_stop": self.should_stop,
            "stop_reason": self.stop_reason,
            "gaps": list(self.gaps),
            "next_queries": list(self.next_queries),
            "accepted_source_count": self.accepted_source_count,
            "primary_source_count": self.primary_source_count,
            "distilled_claim_count": self.distilled_claim_count,
        }


@dataclass(frozen=True, slots=True)
class FinalSynthesisStep:
    summary: str
    stop_reason: str
    covered_questions: tuple[str, ...]
    unresolved_gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "stop_reason": self.stop_reason,
            "covered_questions": list(self.covered_questions),
            "unresolved_gaps": list(self.unresolved_gaps),
        }


@dataclass(slots=True)
class ResearchState:
    goal: str
    research_questions: list[ResearchQuestion] = field(default_factory=list)
    query_queue: list[str] = field(default_factory=list)
    executed_queries: list[str] = field(default_factory=list)
    candidate_sources: list[dict[str, Any]] = field(default_factory=list)
    fetched_sources: list[dict[str, Any]] = field(default_factory=list)
    distilled_claims: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[EvidenceReviewStep] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    stop_reason: str = ""
    final_synthesis: FinalSynthesisStep | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "research_questions": [item.to_dict() for item in self.research_questions],
            "query_queue": list(self.query_queue),
            "executed_queries": list(self.executed_queries),
            "candidate_sources": list(self.candidate_sources),
            "fetched_sources": list(self.fetched_sources),
            "distilled_claims": list(self.distilled_claims),
            "reviews": [item.to_dict() for item in self.reviews],
            "unknowns": list(self.unknowns),
            "limits": list(self.limits),
            "stop_reason": self.stop_reason,
            "final_synthesis": self.final_synthesis.to_dict() if self.final_synthesis else None,
        }


class DefaultDeepSearchStrategy:
    """State-driven DeepSearch planning and evidence-gap review."""

    def plan(self, *, payload: dict[str, Any], goal: str, config: SearchRuntimeConfig) -> SearchPlanningStep:
        raw_queries = payload.get("queries")
        provided_queries = [
            str(item or "").strip()
            for item in list(raw_queries or [])
            if str(item or "").strip()
        ] if isinstance(raw_queries, (list, tuple)) else []
        questions = [
            ResearchQuestion(
                question_id="rq:core",
                question=goal,
                priority="high",
                reason="Verify the subagent research goal.",
            )
        ]
        queries = [*provided_queries, goal]
        if config.search_strategy == "deepsearch" and config.prefer_primary_sources:
            questions.append(
                ResearchQuestion(
                    question_id="rq:primary-source",
                    question=f"What primary or official source supports: {goal}",
                    priority="high",
                    reason="DeepSearch requires source quality checks.",
                )
            )
            queries.append(f"{goal} official source")
            queries.append(f"{goal} official announcement")
        if config.search_strategy == "deepsearch" and config.freshness_required_by_default:
            questions.append(
                ResearchQuestion(
                    question_id="rq:freshness",
                    question=f"What is the latest dated source for: {goal}",
                    priority="normal",
                    reason="Freshness is required by runtime_config.search.",
                )
            )
            queries.append(f"{goal} latest update")
            queries.append(f"{goal} release notes date")
        return SearchPlanningStep(
            research_questions=tuple(questions),
            initial_queries=_dedupe(queries)[: config.max_queries],
            rationale="Initial plan derived from subagent query, runtime budget, source quality policy, and freshness policy.",
        )

    def review(self, *, state: ResearchState, config: SearchRuntimeConfig, phase: str = "search") -> EvidenceReviewStep:
        accepted_sources = _unique_sources(state.candidate_sources)
        accepted_count = len(accepted_sources)
        primary_count = sum(1 for item in accepted_sources if _looks_primary_source(item))
        distilled_claim_count = len(state.distilled_claims)
        gaps: list[str] = []
        next_queries: list[str] = []
        if accepted_count <= 0:
            gaps.append("no_sources")
            next_queries.append(f"{state.goal} source")
        if config.prefer_primary_sources and primary_count <= 0:
            gaps.append("primary_source_missing")
            next_queries.append(f"{state.goal} official announcement")
        if config.freshness_required_by_default and not _has_dated_source(accepted_sources):
            gaps.append("dated_source_missing")
            next_queries.append(f"{state.goal} date")
        if phase == "distilled":
            if distilled_claim_count <= 0:
                gaps.append("distilled_claim_missing")
                next_queries.append(f"{state.goal} official documentation details")
            for unknown in state.unknowns:
                unknown_queries = _queries_for_unknown(state.goal, unknown)
                if unknown_queries:
                    gaps.append("distilled_unknown_followup_required")
                    next_queries.extend(unknown_queries)
        if config.search_strategy == "single_search":
            return EvidenceReviewStep(
                should_stop=True,
                stop_reason="single_search_complete",
                gaps=tuple(gaps),
                next_queries=(),
                accepted_source_count=accepted_count,
                primary_source_count=primary_count,
                distilled_claim_count=distilled_claim_count,
            )
        remaining_query_budget = config.max_queries - len(state.executed_queries) - len(state.query_queue)
        if phase != "distilled" and state.query_queue:
            return EvidenceReviewStep(
                should_stop=False,
                stop_reason="query_queue_has_planned_work",
                gaps=tuple(gaps),
                next_queries=(),
                accepted_source_count=accepted_count,
                primary_source_count=primary_count,
                distilled_claim_count=distilled_claim_count,
            )
        if phase == "distilled" and gaps and remaining_query_budget > 0:
            return EvidenceReviewStep(
                should_stop=False,
                stop_reason="distilled_evidence_gap",
                gaps=tuple(_dedupe(gaps)),
                next_queries=tuple(_dedupe(next_queries)[:remaining_query_budget]),
                accepted_source_count=accepted_count,
                primary_source_count=primary_count,
                distilled_claim_count=distilled_claim_count,
            )
        if accepted_count >= config.max_sources:
            return EvidenceReviewStep(
                should_stop=True,
                stop_reason="enough_sources",
                gaps=tuple(gaps),
                next_queries=(),
                accepted_source_count=accepted_count,
                primary_source_count=primary_count,
                distilled_claim_count=distilled_claim_count,
            )
        if not gaps and accepted_count >= 2 and (phase != "distilled" or distilled_claim_count >= 1):
            return EvidenceReviewStep(
                should_stop=True,
                stop_reason="enough_evidence",
                accepted_source_count=accepted_count,
                primary_source_count=primary_count,
                distilled_claim_count=distilled_claim_count,
            )
        if state.query_queue:
            return EvidenceReviewStep(
                should_stop=False,
                stop_reason="evidence_gap",
                gaps=tuple(gaps),
                next_queries=tuple(_dedupe(next_queries)[: max(0, remaining_query_budget)]),
                accepted_source_count=accepted_count,
                primary_source_count=primary_count,
                distilled_claim_count=distilled_claim_count,
            )
        return EvidenceReviewStep(
            should_stop=remaining_query_budget <= 0,
            stop_reason="query_budget_exhausted" if remaining_query_budget <= 0 else "evidence_gap",
            gaps=tuple(gaps),
            next_queries=tuple(_dedupe(next_queries)[: max(0, remaining_query_budget)]),
            accepted_source_count=accepted_count,
            primary_source_count=primary_count,
            distilled_claim_count=distilled_claim_count,
        )

    def synthesize(self, *, state: ResearchState) -> FinalSynthesisStep:
        covered = [
            question.question_id
            for question in state.research_questions
            if question.question_id == "rq:core" or any(_query_matches_question(query, question.question) for query in state.executed_queries)
        ]
        unresolved: list[str] = []
        if state.reviews:
            unresolved.extend(state.reviews[-1].gaps)
        if not state.candidate_sources:
            unresolved.append("no_accepted_sources")
        if not state.distilled_claims:
            unresolved.append("no_distilled_claims")
        return FinalSynthesisStep(
            summary=f"Executed {len(state.executed_queries)} search queries and accepted {len(_unique_sources(state.candidate_sources))} candidate sources.",
            stop_reason=state.stop_reason or "unknown",
            covered_questions=tuple(_dedupe(covered)),
            unresolved_gaps=tuple(_dedupe(unresolved)),
        )


def enqueue_queries(state: ResearchState, queries: tuple[str, ...], *, max_queries: int, front: bool = False) -> None:
    seen = set(state.executed_queries) | set(state.query_queue)
    accepted: list[str] = []
    for query in queries:
        item = str(query or "").strip()
        if not item or item in seen:
            continue
        if not front and len(state.executed_queries) + len(state.query_queue) >= max_queries:
            break
        accepted.append(item)
        seen.add(item)
    if not accepted:
        return
    if front:
        state.query_queue = [*accepted, *state.query_queue]
        remaining_slots = max(0, max_queries - len(state.executed_queries))
        state.query_queue = state.query_queue[:remaining_slots]
    else:
        state.query_queue.extend(accepted)


def _unique_sources(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        url = str(item.get("url") or "").strip()
        key = url or str(item.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _looks_primary_source(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(item.get(key) or "").lower()
        for key in ("title", "url", "content", "raw_content")
    )
    return any(token in haystack for token in ("official", ".gov", ".edu", "docs.", "developer.", "developers.", "learn.microsoft.com", "press release", "announcement"))


def _has_dated_source(items: list[dict[str, Any]]) -> bool:
    return any(str(item.get("published_date") or "").strip() for item in items)


def _queries_for_unknown(goal: str, unknown: str) -> list[str]:
    text = str(unknown or "").lower()
    queries: list[str] = []
    if any(token in text for token in ("model", "models", "support", "supported")):
        queries.append(f"{goal} supported models")
    if any(token in text for token in ("pricing", "rate limit", "rate limits", "access restriction")):
        queries.append(f"{goal} pricing rate limits")
    if any(token in text for token in ("date", "released", "release", "latest", "current")):
        queries.append(f"{goal} release notes latest date")
    if any(token in text for token in ("parameter", "options", "response structure", "filters")):
        queries.append(f"{goal} parameters response structure")
    if any(token in text for token in ("citation", "citations", "source", "formatted")):
        queries.append(f"{goal} citations source links")
    return queries


def _query_matches_question(query: str, question: str) -> bool:
    query_tokens = {item for item in query.lower().split() if len(item) > 3}
    question_tokens = {item.strip(":,?.") for item in question.lower().split() if len(item.strip(":,?.")) > 3}
    return bool(query_tokens & question_tokens)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


