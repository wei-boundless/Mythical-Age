from __future__ import annotations

from typing import Iterable


CANONICAL_AGENT_ID_BY_ALIAS = {
    "agent:main": "agent:0",
    "agent:6": "agent:rag_analyst",
    "agent.rag_retriever": "agent:rag_analyst",
    "agent.rag_analyst": "agent:rag_analyst",
    "builtin-rag-reader": "agent:rag_analyst",
    "builtin-rag-agent": "agent:rag_analyst",
    "builtin-rag-analyst": "agent:rag_analyst",
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
    "agent:chapter_planner": "agent:writing_team_worker",
    "agent:character_designer_a": "agent:writing_team_worker",
    "agent:character_designer_b": "agent:writing_team_worker",
    "agent:character_judge": "agent:writing_team_worker",
    "agent:novel_quality_judge": "agent:writing_team_worker",
    "agent:novel_writer_a": "agent:writing_team_worker",
    "agent:novel_writer_b": "agent:writing_team_worker",
    "agent:outline_designer_a": "agent:writing_team_worker",
    "agent:outline_designer_b": "agent:writing_team_worker",
    "agent:outline_judge": "agent:writing_team_worker",
    "agent:world_designer_a": "agent:writing_team_worker",
    "agent:world_designer_b": "agent:writing_team_worker",
    "agent:world_judge": "agent:writing_team_worker",
    "agent:writing_simple_creator": "agent:writing_simple_worker",
    "agent:writing_simple_reviewer": "agent:writing_simple_worker",
    "agent:writing_final_assembler": "agent:writing_simple_worker",
    "agent:memory_steward": "agent:writing_memory_steward",
}

WORKER_AGENT_ALIASES = {
    "agent:rag_analyst": ("agent:6", "agent.rag_retriever", "agent.rag_analyst", "builtin-rag-reader", "builtin-rag-agent", "builtin-rag-analyst"),
    "agent:pdf_reader": ("agent:7", "agent.pdf_analyst", "agent.pdf_reader", "builtin-pdf-reader", "builtin-pdf-agent", "builtin-pdf-analyst"),
    "agent:table_analyst": ("agent:8", "agent.table_analyst", "builtin-table-analyzer", "builtin-structured-data-agent", "builtin-table-analyst"),
    "agent:web_researcher": ("agent.web_researcher", "agent.web_research", "builtin-web-researcher", "builtin-web-agent", "builtin-web-search-agent"),
    "agent:writing_team_worker": (
        "agent:chapter_planner",
        "agent:character_designer_a",
        "agent:character_designer_b",
        "agent:character_judge",
        "agent:novel_quality_judge",
        "agent:novel_writer_a",
        "agent:novel_writer_b",
        "agent:outline_designer_a",
        "agent:outline_designer_b",
        "agent:outline_judge",
        "agent:world_designer_a",
        "agent:world_designer_b",
        "agent:world_judge",
    ),
    "agent:writing_simple_worker": (
        "agent:writing_simple_creator",
        "agent:writing_simple_reviewer",
        "agent:writing_final_assembler",
    ),
    "agent:writing_memory_steward": ("agent:memory_steward",),
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
