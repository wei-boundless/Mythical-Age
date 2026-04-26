from __future__ import annotations

from typing import Any

from .models import SearchSourceClass


def tool_text_set(tool: dict[str, Any], *fields: str) -> set[str]:
    values: set[str] = set()
    for field_name in fields:
        raw = tool.get(field_name)
        if isinstance(raw, list):
            values.update(str(item).lower() for item in raw if str(item).strip())
        elif raw:
            values.add(str(raw).lower())
    return values


def classify_tool_source(tool: dict[str, Any]) -> SearchSourceClass:
    tags = tool_text_set(tool, "capability_tags", "supported_modalities", "safety_tags", "route_hints")
    name = str(tool.get("name") or "").lower()
    if name in {"terminal", "python_repl"} or "shell" in tags:
        return "system_execution"
    if tags & {"web", "network", "realtime", "finance", "weather"}:
        return "web"
    if tags & {"rag", "retrieval", "knowledge", "local-knowledge"}:
        return "rag"
    if tags & {"pdf", "document", "page", "section", "multimodal"}:
        return "document"
    if tags & {"table", "spreadsheet", "csv", "json", "dataset", "analytics"}:
        return "data"
    if tags & {"file", "workspace", "local", "code"} or str(tool.get("resource_exposure_policy") or "") == "explicit_resource":
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


def tool_allowed_by_search_policy(tool: dict[str, Any], allowed: set[str]) -> bool:
    return source_allowed_by_search_policy(classify_tool_source(tool), allowed)
