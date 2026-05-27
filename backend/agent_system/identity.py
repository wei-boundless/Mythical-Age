from __future__ import annotations

from typing import Iterable


CANONICAL_AGENT_ID_BY_ALIAS = {
    "agent:main": "agent:0",
    "agent:rag_analyst": "agent:knowledge_searcher",
    "agent:6": "agent:knowledge_searcher",
    "agent.rag_retriever": "agent:knowledge_searcher",
    "agent.rag_analyst": "agent:knowledge_searcher",
    "builtin-rag-reader": "agent:knowledge_searcher",
    "builtin-rag-agent": "agent:knowledge_searcher",
    "builtin-rag-analyst": "agent:knowledge_searcher",
    "agent.knowledge_searcher": "agent:knowledge_searcher",
    "agent.knowledge_search": "agent:knowledge_searcher",
    "agent.rag_searcher": "agent:knowledge_searcher",
    "builtin-knowledge-searcher": "agent:knowledge_searcher",
    "builtin-rag-searcher": "agent:knowledge_searcher",
    "agent:7": "agent:pdf_reader",
    "agent.pdf_analyst": "agent:pdf_reader",
    "agent.pdf_reader": "agent:pdf_reader",
    "builtin-pdf-reader": "agent:pdf_reader",
    "builtin-pdf-agent": "agent:pdf_reader",
    "builtin-pdf-analyst": "agent:pdf_reader",
    "agent:8": "agent:table_analyst",
    "agent.table_analyst": "agent:table_analyst",
    "builtin-table-analyzer": "agent:table_analyst",
    "builtin-structured-data-agent": "agent:table_analyst",
    "builtin-table-analyst": "agent:table_analyst",
    "agent.web_researcher": "agent:web_researcher",
    "agent.web_research": "agent:web_researcher",
    "builtin-web-researcher": "agent:web_researcher",
    "builtin-web-agent": "agent:web_researcher",
    "builtin-web-search-agent": "agent:web_researcher",
    "agent.codebase_searcher": "agent:codebase_searcher",
    "agent.codebase_search": "agent:codebase_searcher",
    "agent.local_searcher": "agent:codebase_searcher",
    "builtin-codebase-searcher": "agent:codebase_searcher",
    "builtin-local-file-searcher": "agent:codebase_searcher",
    "agent.memory_searcher": "agent:memory_searcher",
    "agent.memory_search": "agent:memory_searcher",
    "builtin-memory-searcher": "agent:memory_searcher",
    "agent.verifier": "agent:verifier",
    "agent.completion_verifier": "agent:verifier",
    "builtin-verifier": "agent:verifier",
    "builtin-verifier-agent": "agent:verifier",
    "builtin-completion-verifier": "agent:verifier",
}

WORKER_AGENT_ALIASES = {
    "agent:knowledge_searcher": (
        "agent:6",
        "agent.rag_retriever",
        "agent.rag_analyst",
        "builtin-rag-reader",
        "builtin-rag-agent",
        "builtin-rag-analyst",
        "agent.knowledge_searcher",
        "agent.knowledge_search",
        "agent.rag_searcher",
        "builtin-knowledge-searcher",
        "builtin-rag-searcher",
    ),
    "agent:pdf_reader": ("agent:7", "agent.pdf_analyst", "agent.pdf_reader", "builtin-pdf-reader", "builtin-pdf-agent", "builtin-pdf-analyst"),
    "agent:table_analyst": ("agent:8", "agent.table_analyst", "builtin-table-analyzer", "builtin-structured-data-agent", "builtin-table-analyst"),
    "agent:web_researcher": ("agent.web_researcher", "agent.web_research", "builtin-web-researcher", "builtin-web-agent", "builtin-web-search-agent"),
    "agent:codebase_searcher": ("agent.codebase_searcher", "agent.codebase_search", "agent.local_searcher", "builtin-codebase-searcher", "builtin-local-file-searcher"),
    "agent:memory_searcher": ("agent.memory_searcher", "agent.memory_search", "builtin-memory-searcher"),
    "agent:verifier": ("agent.verifier", "agent.completion_verifier", "builtin-verifier", "builtin-verifier-agent", "builtin-completion-verifier"),
}


def normalize_agent_id(agent_id: str) -> str:
    target = str(agent_id or "").strip()
    if not target:
        return ""
    return CANONICAL_AGENT_ID_BY_ALIAS.get(target, target)


def agent_id_aliases(agent_id: str) -> tuple[str, ...]:
    canonical = normalize_agent_id(agent_id)
    values = [canonical] if canonical else []
    if canonical == "agent:0":
        values.append("agent:main")
    values.extend(WORKER_AGENT_ALIASES.get(canonical, ()))
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def normalize_agent_id_sequence(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = normalize_agent_id(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


