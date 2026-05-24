from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.execution.delegation_models import AgentDelegationRequest

from .distiller import ModelBackedSearchEvidenceDistiller, SearchEvidenceDistiller
from .evidence_builder import build_deepsearch_evidence_packet
from .models import SearchRuntimeConfig, required_operations_for_search_config
from .providers import FetchUrlProvider, TavilySearchProvider
from .result_storage import SearchToolResultStore
from .strategy import DefaultDeepSearchStrategy, ResearchState, enqueue_queries
from .web_text import normalize_web_result_item


class SearchAgentRuntime:
    def __init__(
        self,
        root_dir: Path,
        *,
        search_provider: Any | None = None,
        fetch_provider: Any | None = None,
        strategy: Any | None = None,
        distiller: Any | None = None,
        model_runtime: Any | None = None,
        result_store_factory: Any | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.search_provider = search_provider or TavilySearchProvider(self.root_dir)
        self.fetch_provider = fetch_provider or FetchUrlProvider()
        self.strategy = strategy or DefaultDeepSearchStrategy()
        self.distiller = distiller or (
            ModelBackedSearchEvidenceDistiller(model_runtime)
            if model_runtime is not None
            else SearchEvidenceDistiller()
        )
        self.result_store_factory = result_store_factory

    async def run(
        self,
        *,
        request: AgentDelegationRequest,
        agent: Any,
        profile: Any,
        config: SearchRuntimeConfig,
    ) -> dict[str, Any]:
        available_ops = _available_operations(profile)
        required_ops = set(required_operations_for_search_config(config))
        missing_ops = sorted(required_ops - available_ops)
        if missing_ops:
            return _failed_result(
                summary="Search Agent 缺少 DeepSearch 模板所需权限。",
                limitations=["deepsearch_required_operation_missing", *missing_ops],
                diagnostics={
                    "child_execution_mode": "runtime_configured_search_agent",
                    "runtime_template_id": "runtime.template.deepsearch",
                    "required_operations": sorted(required_ops),
                    "available_operations": sorted(available_ops),
                    "missing_operations": missing_ops,
                },
            )

        payload = dict(request.input_payload or {})
        goal = str(payload.get("query") or payload.get("question") or request.instruction or "").strip()
        if not goal:
            return _failed_result(
                summary="Search Agent 没有收到可检索的问题。",
                limitations=["deepsearch_empty_query"],
                diagnostics={"child_execution_mode": "runtime_configured_search_agent"},
            )
        topic = str(payload.get("topic") or "general").strip() or "general"
        time_range = str(payload.get("time_range") or "").strip()
        planning = self.strategy.plan(payload=payload, goal=goal, config=config)
        state = ResearchState(
            goal=goal,
            research_questions=list(planning.research_questions),
            query_queue=list(planning.initial_queries),
        )
        total_tool_calls = 0
        search_payloads: list[dict[str, Any]] = []

        distillation = None
        combined_payload: dict[str, Any] = {}
        for _iteration in range(config.max_iterations):
            total_tool_calls = await self._run_search_queue(
                state=state,
                topic=topic,
                time_range=time_range,
                config=config,
                search_payloads=search_payloads,
                total_tool_calls=total_tool_calls,
                max_queries_this_cycle=1,
            )
            if config.allow_fetch_url and config.max_fetches > 0:
                total_tool_calls = await self._fetch_sources(state=state, config=config, total_tool_calls=total_tool_calls)
            combined_payload = _combine_search_payloads(
                goal=goal,
                topic=topic,
                time_range=time_range,
                payloads=search_payloads,
                state=state,
                config=config,
                total_tool_calls=total_tool_calls,
            )
            distillation = await _distill(self.distiller, query=goal, sources=list(combined_payload.get("results") or []))
            state.distilled_claims = [item.to_dict() for item in distillation.claims]
            combined_payload.setdefault("deepsearch", {})
            combined_payload["deepsearch"]["distillation"] = distillation.to_dict()
            combined_payload["deepsearch"]["distilled_claims"] = list(state.distilled_claims)
            for unknown in distillation.unknowns:
                if unknown not in state.unknowns:
                    state.unknowns.append(unknown)
            review = self.strategy.review(state=state, config=config, phase="distilled")
            state.reviews.append(review)
            if review.next_queries:
                enqueue_queries(state, review.next_queries, max_queries=config.max_queries, front=True)
            if review.should_stop or not state.query_queue or len(state.executed_queries) >= config.max_queries:
                state.stop_reason = review.stop_reason
                break
        if not state.stop_reason:
            state.stop_reason = "budget_exhausted"
        state.final_synthesis = self.strategy.synthesize(state=state)
        combined_payload = _combine_search_payloads(
            goal=goal,
            topic=topic,
            time_range=time_range,
            payloads=search_payloads,
            state=state,
            config=config,
            total_tool_calls=total_tool_calls,
        )
        if distillation is None:
            distillation = await _distill(self.distiller, query=goal, sources=list(combined_payload.get("results") or []))
            state.distilled_claims = [item.to_dict() for item in distillation.claims]
        combined_payload.setdefault("deepsearch", {})
        combined_payload["deepsearch"]["distillation"] = distillation.to_dict()
        combined_payload["deepsearch"]["distilled_claims"] = list(state.distilled_claims)
        artifact_refs = _artifact_refs_from_distillation(distillation)
        replacements = ()
        diagnostics_state = state.to_dict()
        diagnostics_payload = combined_payload
        if config.persist_large_results:
            store = self._result_store(request=request)
            budgeted_diagnostics, replacements = store.apply_budget(
                {
                    "web_payload": combined_payload,
                    "research_state": diagnostics_state,
                },
                field_limit_bytes=config.tool_result_field_limit_bytes,
                preview_size_bytes=config.tool_result_preview_bytes,
                payload_budget_bytes=config.tool_result_payload_budget_bytes,
            )
            diagnostics_payload = dict(budgeted_diagnostics.get("web_payload") or {})
            diagnostics_state = dict(budgeted_diagnostics.get("research_state") or {})
        packet = build_deepsearch_evidence_packet(
            web_payload=combined_payload,
            source_agent_id=str(getattr(agent, "agent_id", "") or "agent:web_researcher"),
            target_task_id=request.task_run_id,
            task_goal=request.instruction,
        )
        ok = bool(combined_payload.get("ok", True)) and bool(packet.evidence)
        limitations = [*state.unknowns, *state.limits]
        if not ok and not limitations:
            limitations.append("deepsearch_no_sources")
        answer = _deepsearch_summary(web_payload=combined_payload, packet=packet)
        return {
            "status": "completed" if ok else "failed",
            "summary": answer,
            "answer_candidate": answer,
            "evidence_refs": [item.evidence_id for item in packet.evidence],
            "artifact_refs": artifact_refs,
            "confidence": packet.confidence,
            "limitations": limitations,
            "diagnostics": {
                "child_execution_mode": "runtime_configured_search_agent",
                "operation_id": "op.web_search",
                "specialist_route": "web_research",
                "runtime_template_id": "runtime.template.deepsearch",
                "runtime_config": config.to_dict(),
                "web_payload": diagnostics_payload,
                "research_state": diagnostics_state,
                "distillation": distillation.to_dict(),
                "content_replacements": [item.to_dict() for item in replacements],
                "agent_evidence_packet": packet.to_dict(),
                "visible_packet_summary": packet.visible_summary(),
            },
        }

    def _result_store(self, *, request: AgentDelegationRequest) -> SearchToolResultStore:
        if self.result_store_factory is not None:
            return self.result_store_factory(self.root_dir, request)
        run_id = request.request_id or request.task_run_id or "deepsearch"
        return SearchToolResultStore(self.root_dir, run_id=run_id)

    async def _run_search_queue(
        self,
        *,
        state: ResearchState,
        topic: str,
        time_range: str,
        config: SearchRuntimeConfig,
        search_payloads: list[dict[str, Any]],
        total_tool_calls: int,
        max_queries_this_cycle: int,
    ) -> int:
        executed_this_cycle = 0
        while state.query_queue and len(state.executed_queries) < config.max_queries:
            if executed_this_cycle >= max(1, int(max_queries_this_cycle or 1)):
                break
            per_query_results = _per_query_results(config=config, queued_count=max(1, len(state.query_queue)))
            query = state.query_queue.pop(0)
            if query in state.executed_queries:
                continue
            total_tool_calls += 1
            payload_result = await self.search_provider.search(
                query=query,
                topic=topic,
                time_range=time_range,
                max_results=per_query_results,
                config=config,
            )
            search_payloads.append(dict(payload_result))
            state.executed_queries.append(query)
            executed_this_cycle += 1
            if not bool(payload_result.get("ok", True)):
                state.unknowns.append(str(payload_result.get("error") or "web_search_failed"))
                continue
            state.candidate_sources.extend(_unique_result_items(payload_result.get("results")))
            review = self.strategy.review(state=state, config=config, phase="search")
            state.reviews.append(review)
            if review.next_queries:
                enqueue_queries(state, review.next_queries, max_queries=config.max_queries)
            if review.should_stop:
                state.stop_reason = review.stop_reason
                break
        return total_tool_calls

    async def _fetch_sources(self, *, state: ResearchState, config: SearchRuntimeConfig, total_tool_calls: int) -> int:
        fetch_budget = max(0, config.max_fetches - len(state.fetched_sources))
        if fetch_budget <= 0:
            return total_tool_calls
        fetched_urls = {str(item.get("url") or "").strip() for item in state.fetched_sources}
        for item in state.candidate_sources:
            if fetch_budget <= 0:
                break
            url = str(item.get("url") or "").strip()
            if not url or url in fetched_urls:
                continue
            total_tool_calls += 1
            fetched = await self.fetch_provider.fetch(url=url)
            state.fetched_sources.append(dict(fetched))
            fetched_urls.add(url)
            fetch_budget -= 1
            if bool(fetched.get("ok")):
                item.update(normalize_web_result_item(item, fetched_payload=dict(fetched)))
        return total_tool_calls


def _available_operations(profile: Any) -> set[str]:
    allowed = {str(item).strip() for item in tuple(getattr(profile, "allowed_operations", ()) or ()) if str(item).strip()}
    blocked = {str(item).strip() for item in tuple(getattr(profile, "blocked_operations", ()) or ()) if str(item).strip()}
    return allowed - blocked


def _failed_result(*, summary: str, limitations: list[str], diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "failed",
        "summary": summary,
        "answer_candidate": summary,
        "evidence_refs": [],
        "artifact_refs": [],
        "confidence": "low",
        "limitations": limitations,
        "diagnostics": diagnostics,
    }


def _unique_result_items(value: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        key = url or str(item.get("title") or "")
        if key in seen_urls:
            continue
        seen_urls.add(key)
        results.append(normalize_web_result_item(dict(item)))
    return results


def _per_query_results(*, config: SearchRuntimeConfig, queued_count: int) -> int:
    denominator = max(1, min(config.max_queries, queued_count))
    return max(1, min(config.max_sources, max(1, config.max_sources // denominator)))


def _combine_search_payloads(
    *,
    goal: str,
    topic: str,
    time_range: str,
    payloads: list[dict[str, Any]],
    state: ResearchState,
    config: SearchRuntimeConfig,
    total_tool_calls: int,
) -> dict[str, Any]:
    results = _unique_result_items(state.candidate_sources)[: config.max_sources]
    return {
        "ok": bool(results) and not all(not bool(item.get("ok", True)) for item in payloads),
        "query": goal,
        "topic": topic,
        "time_range": time_range,
        "results": results,
        "usage": {
            "runtime_mode": config.runtime_mode,
            "queries_executed": len(state.executed_queries),
            "fetches_executed": len(state.fetched_sources),
            "tool_calls": total_tool_calls,
            "max_queries": config.max_queries,
            "max_fetches": config.max_fetches,
            "max_sources": config.max_sources,
        },
        "deepsearch": {
            "executed_queries": list(state.executed_queries),
            "stop_reason": state.stop_reason,
            "fetched_sources": list(state.fetched_sources),
            "reviews": [item.to_dict() for item in state.reviews],
            "final_synthesis": state.final_synthesis.to_dict() if state.final_synthesis else None,
        },
        "error": "; ".join(state.unknowns),
    }


def _deepsearch_summary(*, web_payload: dict[str, Any], packet: Any) -> str:
    query = str(web_payload.get("query") or "").strip()
    usage = dict(web_payload.get("usage") or {})
    lines = [f"DeepSearch 研究完成：{query}" if query else "DeepSearch 研究完成。"]
    lines.append(
        f"预算使用：{usage.get('queries_executed', 0)} 查询 / {usage.get('fetches_executed', 0)} 抓取 / {usage.get('max_sources', 0)} 来源上限。"
    )
    if getattr(packet, "facts", ()):
        lines.append("可用事实证据：")
        for fact in list(packet.facts)[:3]:
            lines.append(f"- {fact.claim}")
    if getattr(packet, "unknowns", ()):
        lines.append("未知与限制：")
        for unknown in list(packet.unknowns)[:2]:
            lines.append(f"- {unknown.description}")
    return "\n".join(lines).strip()


def _artifact_refs_from_distillation(distillation: Any) -> list[str]:
    refs: list[str] = []
    for claim in tuple(getattr(distillation, "claims", ()) or ()):
        ref = str(getattr(claim, "artifact_ref", "") or "").strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs


async def _distill(distiller: Any, *, query: str, sources: list[dict[str, Any]]) -> Any:
    async_distiller = getattr(distiller, "adistill", None)
    if callable(async_distiller):
        return await async_distiller(query=query, sources=sources)
    return distiller.distill(query=query, sources=sources)
