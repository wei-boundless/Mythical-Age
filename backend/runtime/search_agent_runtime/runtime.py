from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.execution.delegation_models import AgentDelegationRequest

from .evidence_builder import build_deepsearch_evidence_packet
from .models import SearchRuntimeConfig, required_operations_for_search_config
from .providers import FetchUrlProvider, TavilySearchProvider
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
    ) -> None:
        self.root_dir = Path(root_dir)
        self.search_provider = search_provider or TavilySearchProvider(self.root_dir)
        self.fetch_provider = fetch_provider or FetchUrlProvider()
        self.strategy = strategy or DefaultDeepSearchStrategy()

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
        per_query_results = max(1, min(config.max_sources, max(1, config.max_sources // max(1, min(config.max_queries, len(state.query_queue))))))
        total_tool_calls = 0
        search_payloads: list[dict[str, Any]] = []

        for _iteration in range(config.max_iterations):
            if not state.query_queue:
                state.stop_reason = "query_queue_empty"
                break
            if len(state.executed_queries) >= config.max_queries:
                state.stop_reason = "max_queries_reached"
                break
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
            if not bool(payload_result.get("ok", True)):
                state.unknowns.append(str(payload_result.get("error") or "web_search_failed"))
                continue
            state.candidate_sources.extend(_unique_result_items(payload_result.get("results")))
            review = self.strategy.review(state=state, config=config)
            state.reviews.append(review)
            if review.next_queries:
                enqueue_queries(state, review.next_queries, max_queries=config.max_queries)
            if review.should_stop:
                state.stop_reason = review.stop_reason
                break
        if not state.stop_reason:
            state.stop_reason = "budget_exhausted"

        if config.allow_fetch_url and config.max_fetches > 0:
            fetch_budget = min(config.max_fetches, max(0, config.max_tool_calls if hasattr(config, "max_tool_calls") else config.max_fetches))
            for item in state.candidate_sources[:fetch_budget]:
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                total_tool_calls += 1
                fetched = await self.fetch_provider.fetch(url=url)
                state.fetched_sources.append(dict(fetched))
                if bool(fetched.get("ok")):
                    item.update(normalize_web_result_item(item, fetched_payload=dict(fetched)))
            review = self.strategy.review(state=state, config=config)
            state.reviews.append(review)
            if review.should_stop and state.stop_reason in {"evidence_gap", "budget_exhausted", "query_budget_exhausted"}:
                state.stop_reason = review.stop_reason
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
            "artifact_refs": [],
            "confidence": packet.confidence,
            "limitations": limitations,
            "diagnostics": {
                "child_execution_mode": "runtime_configured_search_agent",
                "operation_id": "op.web_search",
                "specialist_route": "web_research",
                "runtime_template_id": "runtime.template.deepsearch",
                "runtime_config": config.to_dict(),
                "web_payload": combined_payload,
                "research_state": state.to_dict(),
                "agent_evidence_packet": packet.to_dict(),
                "visible_packet_summary": packet.visible_summary(),
            },
        }


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
