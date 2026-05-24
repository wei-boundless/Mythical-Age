from __future__ import annotations

from typing import Any

from .models import SearchSourceClass


DEFAULT_SEARCH_POLICY_SOURCES = frozenset({"rag", "local_files", "web"})

AGENT_SOURCE_CLASS = {
    "agent:rag_analyst": "rag",
    "agent:pdf_reader": "document",
    "agent:table_analyst": "data",
    "agent:web_researcher": "general",
    "agent:verifier": "general",
}

OPERATION_SOURCE_CLASS = {
    "op.mcp_retrieval": "rag",
    "op.mcp_pdf": "document",
    "op.mcp_structured_data": "data",
    "op.web_search": "web",
    "op.fetch_url": "web",
    "op.read_file": "local_files",
    "op.search_files": "local_files",
    "op.search_text": "local_files",
    "op.read_structured_file": "data",
}


def normalize_search_policy(search_policy: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    if search_policy is None:
        return set(DEFAULT_SEARCH_POLICY_SOURCES)
    return {
        str(item or "").strip()
        for item in search_policy
        if str(item or "").strip()
    }


def _field_value(tool: Any, field_name: str) -> Any:
    if isinstance(tool, dict):
        return tool.get(field_name)
    return getattr(tool, field_name, None)


def tool_text_set(tool: Any, *fields: str) -> set[str]:
    values: set[str] = set()
    for field_name in fields:
        raw = _field_value(tool, field_name)
        if isinstance(raw, list):
            values.update(str(item).lower() for item in raw if str(item).strip())
        elif isinstance(raw, tuple):
            values.update(str(item).lower() for item in raw if str(item).strip())
        elif isinstance(raw, set):
            values.update(str(item).lower() for item in raw if str(item).strip())
        elif raw:
            values.add(str(raw).lower())
    return values


def classify_tool_source(tool: Any) -> SearchSourceClass:
    tags = tool_text_set(tool, "capability_tags", "supported_modalities", "safety_tags", "route_hints")
    name = str(_field_value(tool, "name") or "").lower()
    if name in {"terminal", "python_repl"} or "shell" in tags:
        return "system_execution"
    if tags & {"delegation", "agent", "orchestration"}:
        return "general"
    if tags & {"web", "network", "realtime", "finance", "weather"}:
        return "web"
    if tags & {"rag", "retrieval", "knowledge", "local-knowledge"}:
        return "rag"
    if tags & {"pdf", "document", "page", "section", "multimodal"}:
        return "document"
    if tags & {"table", "spreadsheet", "csv", "json", "dataset", "analytics"}:
        return "data"
    if tags & {"file", "workspace", "local", "code"} or str(_field_value(tool, "resource_exposure_policy") or "") == "explicit_resource":
        return "local_files"
    return "general"


def search_policy_labels(source_class: str) -> list[str]:
    if source_class == "rag":
        return ["rag"]
    if source_class == "local_files":
        return ["local_files"]
    if source_class == "web":
        return ["web"]
    if source_class == "document":
        return ["local_files", "document"]
    if source_class == "data":
        return ["local_files", "data"]
    if source_class == "system_execution":
        return ["system_execution"]
    return ["general"]


def source_allowed_by_search_policy(source_class: str, allowed: set[str]) -> bool:
    if source_class == "rag":
        return "rag" in allowed
    if source_class in {"local_files", "document", "data"}:
        return "local_files" in allowed
    if source_class == "web":
        return "web" in allowed
    return True


def operation_allowed_by_search_policy(operation_id: str | None, allowed: set[str]) -> bool:
    source_class = OPERATION_SOURCE_CLASS.get(str(operation_id or "").strip())
    if not source_class:
        return True
    return source_allowed_by_search_policy(source_class, allowed)


def agent_allowed_by_search_policy(agent_id: str | None, allowed: set[str]) -> bool:
    source_class = AGENT_SOURCE_CLASS.get(str(agent_id or "").strip())
    if not source_class:
        return True
    return source_allowed_by_search_policy(source_class, allowed)


def tool_allowed_by_search_policy(tool: Any, allowed: set[str]) -> bool:
    return source_allowed_by_search_policy(classify_tool_source(tool), allowed)
