from __future__ import annotations

from typing import Any


DEFAULT_REFS = {
    "nodes": ["tests", "query-core"],
    "edges": ["tests-query"],
    "reason": "默认映射到测试与主执行链。",
}


def graph_refs_for_issue(issue: dict[str, Any]) -> dict[str, object]:
    category = str(issue.get("category", "") or "").lower()
    title = str(issue.get("title", "") or "").lower()
    summary = str(issue.get("summary", "") or "").lower()
    haystack = " ".join([category, title, summary])

    if "long_scenario" in haystack or "followup" in haystack or "漂移" in haystack:
        return {
            "nodes": ["tests", "query-core", "planner", "memory", "session-store"],
            "edges": ["tests-query", "query-planner", "query-memory", "query-session"],
            "reason": "长场景/follow-up 问题通常同时经过执行核心、规划、记忆和会话状态链。",
        }
    if "memory" in haystack or "记忆" in haystack:
        return {
            "nodes": ["tests", "memory", "storage", "retrieval"],
            "edges": ["tests-query", "memory-storage", "retrieval-storage"],
            "reason": "记忆类问题主要定位到记忆门面、持久层和记忆索引召回链。",
        }
    if "retrieval" in haystack or "rag" in haystack or "检索" in haystack:
        return {
            "nodes": ["tests", "retrieval", "evidence", "storage"],
            "edges": ["evidence-retrieval", "retrieval-storage", "tests-storage"],
            "reason": "检索类问题主要定位到证据编排、检索服务和索引读写链。",
        }
    if "tool" in haystack or "skill" in haystack or "工具" in haystack:
        return {
            "nodes": ["tests", "query-core", "tooling"],
            "edges": ["tests-query", "query-tools"],
            "reason": "工具/技能问题主要定位到执行核心到工具与技能运行链。",
        }
    if "pdf" in haystack or "structured" in haystack or "table" in haystack:
        return {
            "nodes": ["tests", "evidence", "retrieval", "storage"],
            "edges": ["tests-query", "query-evidence", "evidence-retrieval"],
            "reason": "文档、PDF 或结构化数据问题主要定位到证据编排和材料检索链。",
        }
    if "frontend" in haystack or "sse" in haystack:
        return {
            "nodes": ["tests", "api-router", "query-core", "model"],
            "edges": ["app-api", "api-model", "query-model"],
            "reason": "前端或 SSE 问题主要定位到接口路由、执行核心和模型流式回传链。",
        }
    if "model" in haystack or "deepseek" in haystack or "reasoning" in haystack:
        return {
            "nodes": ["tests", "model", "query-core"],
            "edges": ["tests-query", "query-model", "api-model"],
            "reason": "模型或 reasoning 续写问题主要定位到模型边界和执行核心。",
        }
    return dict(DEFAULT_REFS)


def attach_graph_refs(issues: list[Any]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for raw in issues:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["graph_refs"] = graph_refs_for_issue(item)
        enriched.append(item)
    return enriched
