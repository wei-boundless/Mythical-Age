from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SKILL_ROUTE_OPERATION_MAP = {
    "rag": "op.mcp_retrieval",
    "retrieval": "op.mcp_retrieval",
    "pdf": "op.mcp_pdf",
    "structured_data": "op.mcp_structured_data",
    "data": "op.mcp_structured_data",
}


def operation_id_for_skill_route(route: Any) -> str:
    normalized = str(route or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("op."):
        return normalized
    return SKILL_ROUTE_OPERATION_MAP.get(normalized, "")


def skill_operation_ids_from_runtime(runtime: Any) -> list[str]:
    explicit = [
        str(item).strip()
        for item in list(_read_field(runtime, "requires_operations") or [])
        if str(item).strip()
    ]
    if explicit:
        return explicit
    operation_id = operation_id_for_skill_route(_read_field(runtime, "preferred_route"))
    return [operation_id] if operation_id else []


def skill_operation_ids_from_skill(skill: Any) -> list[str]:
    runtime = _read_field(skill, "runtime")
    if runtime is not None:
        return skill_operation_ids_from_runtime(runtime)
    return skill_operation_ids_from_runtime(skill)


def _read_field(payload: Any, field_name: str) -> Any:
    if isinstance(payload, Mapping):
        return payload.get(field_name)
    return getattr(payload, field_name, None)
