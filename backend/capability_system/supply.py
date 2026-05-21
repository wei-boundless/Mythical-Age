from __future__ import annotations

from pathlib import Path
from typing import Any

from .operation_registry import build_default_operation_registry
from .skill_registry import SkillRegistry
from .tool_registry import ToolRegistry
from .mcp_registry import build_mcp_catalog
from .catalog import MAIN_AGENT_ID, build_capability_catalog
from .models import (
    CapabilitySupplyMCPRef,
    CapabilitySupplyPackage,
    CapabilitySupplySkillRef,
    CapabilitySupplyToolRef,
)
from .endpoints import build_capability_endpoints


def build_capability_supply_package(
    runtime,
    tool_overrides: dict[str, dict[str, Any]] | None = None,
    *,
    task_id: str = "capability-system",
    agent_id: str = MAIN_AGENT_ID,
    operation_scope: list[str] | tuple[str, ...] | None = None,
) -> CapabilitySupplyPackage:
    catalog = build_capability_catalog(runtime, tool_overrides)
    return build_capability_supply_package_from_catalog(
        catalog,
        task_id=task_id,
        agent_id=agent_id,
        operation_scope=operation_scope,
    )


def build_capability_supply_package_from_base_dir(
    base_dir: str | Path,
    *,
    task_id: str = "capability-system",
    agent_id: str = MAIN_AGENT_ID,
    operation_scope: list[str] | tuple[str, ...] | None = None,
) -> CapabilitySupplyPackage:
    resolved_base_dir = Path(base_dir).resolve()
    skill_registry = SkillRegistry(resolved_base_dir)
    tool_registry = ToolRegistry(resolved_base_dir)
    operation_registry = build_default_operation_registry()
    mcps = build_mcp_catalog(operation_registry)
    catalog = {
        "skills": [
            {
                "runtime": {
                    "name": skill.runtime.name,
                    "title": skill.prompt_view.title,
                    "activation_policy": skill.runtime.activation_policy,
                    "context_mode": skill.runtime.context_mode,
                    "preferred_route": skill.runtime.preferred_route,
                    "capability_tags": list(skill.runtime.capability_tags),
                    "requires_operations": list(skill.runtime.requires_operations),
                    "requires_capabilities": list(skill.runtime.requires_capabilities),
                },
            }
            for skill in skill_registry.skills
        ],
        "tools": [tool.to_registry_record() for tool in tool_registry.tools],
        "mcps": mcps,
        "capability_endpoints": build_capability_endpoints(mcps=mcps),
    }
    return build_capability_supply_package_from_catalog(
        catalog,
        task_id=task_id,
        agent_id=agent_id,
        operation_scope=operation_scope,
    )


def build_capability_supply_package_from_catalog(
    catalog: dict[str, Any],
    *,
    task_id: str = "capability-system",
    agent_id: str = MAIN_AGENT_ID,
    operation_scope: list[str] | tuple[str, ...] | None = None,
) -> CapabilitySupplyPackage:
    normalized_scope = _normalize_operation_scope(operation_scope)
    tools = list(catalog.get("tools") or [])
    skills = list(catalog.get("skills") or [])
    mcps = list(catalog.get("mcps") or [])

    filtered_tools = [
        tool for tool in tools
        if not normalized_scope or str(tool.get("operation_id") or "").strip() in normalized_scope
    ]
    filtered_mcps = [
        mcp for mcp in mcps
        if not normalized_scope or str(mcp.get("operation_id") or "").strip() in normalized_scope
    ]
    filtered_skills = [
        skill for skill in skills
        if not normalized_scope
        or not _skill_operation_ids(skill)
        or bool(set(_skill_operation_ids(skill)) & normalized_scope)
    ]

    tool_refs = [
        CapabilitySupplyToolRef(
            tool_name=str(tool.get("name") or ""),
            operation_id=str(tool.get("operation_id") or ""),
            tool_type=str(((tool.get("operation_metadata") or {}) if isinstance(tool.get("operation_metadata"), dict) else {}).get("tool_type") or ""),
            runtime_visibility=str(tool.get("runtime_visibility") or ""),
            prompt_exposure_policy=str(tool.get("prompt_exposure_policy") or ""),
            risk_level=str(((tool.get("operation_metadata") or {}) if isinstance(tool.get("operation_metadata"), dict) else {}).get("risk_level") or ""),
            source_class=str(((tool.get("operation_metadata") or {}) if isinstance(tool.get("operation_metadata"), dict) else {}).get("source_class") or ""),
        )
        for tool in filtered_tools
    ]
    skill_refs = [
        CapabilitySupplySkillRef(
            skill_name=str(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("name") or ""),
            title=str(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("title") or ""),
            activation_policy=str(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("activation_policy") or ""),
            context_mode=str(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("context_mode") or ""),
            preferred_route=str(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("preferred_route") or ""),
            capability_tags=tuple(
                str(item)
                for item in list(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("capability_tags") or [])
                if str(item)
            ),
            operation_ids=tuple(_skill_operation_ids(skill)),
            capability_ids=tuple(
                str(item)
                for item in list(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("requires_capabilities") or [])
                if str(item)
            ),
        )
        for skill in filtered_skills
    ]
    mcp_refs = [
        CapabilitySupplyMCPRef(
            mcp_id=str(mcp.get("mcp_id") or ""),
            operation_id=str(mcp.get("operation_id") or ""),
            route=str(mcp.get("route") or ""),
            unit_id=str(mcp.get("unit_id") or ""),
            transport=str(mcp.get("transport") or ""),
            model_visibility=str(mcp.get("model_visibility") or ""),
        )
        for mcp in filtered_mcps
    ]

    available_operation_ids = sorted({
        *[ref.operation_id for ref in tool_refs if ref.operation_id],
        *[ref.operation_id for ref in mcp_refs if ref.operation_id],
    })

    main_runtime_tools = sorted(
        ref.tool_name for ref in tool_refs if ref.runtime_visibility == "main_runtime"
    )
    agent_internal_tools = sorted(
        ref.tool_name for ref in tool_refs if ref.runtime_visibility == "agent_internal"
    )
    model_visible_skills = sorted(
        ref.skill_name for ref in skill_refs if ref.activation_policy == "model_visible"
    )
    hidden_mcp_refs = sorted(
        ref.mcp_id for ref in mcp_refs if ref.model_visibility == "not_direct_model_tool"
    )

    return CapabilitySupplyPackage(
        package_id=f"capsupply:{task_id}:{agent_id}",
        task_id=task_id,
        agent_id=agent_id,
        tool_refs=tool_refs,
        skill_refs=skill_refs,
        mcp_refs=mcp_refs,
        capability_constraints={
            "operation_scope": sorted(normalized_scope),
            "available_operation_ids": available_operation_ids,
        },
        visibility_rules={
            "main_runtime_tools": main_runtime_tools,
            "agent_internal_tools": agent_internal_tools,
            "model_visible_skills": model_visible_skills,
            "hidden_mcp_refs": hidden_mcp_refs,
        },
        diagnostics={
            "tool_count": len(tool_refs),
            "skill_count": len(skill_refs),
            "mcp_count": len(mcp_refs),
            "filtered": bool(normalized_scope),
        },
    )


def _normalize_operation_scope(
    operation_scope: list[str] | tuple[str, ...] | None,
) -> set[str]:
    normalized: set[str] = set()
    for item in list(operation_scope or ()):
        value = str(item or "").strip()
        if value:
            normalized.add(value)
    return normalized


def _skill_operation_ids(skill: dict[str, Any]) -> list[str]:
    runtime = (skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}
    explicit = [
        str(item).strip()
        for item in list(runtime.get("requires_operations") or [])
        if str(item).strip()
    ]
    if explicit:
        return explicit
    route = str(runtime.get("preferred_route") or "").strip()
    if route.startswith("op."):
        return [route]
    return {
        "rag": ["op.mcp_retrieval"],
        "retrieval": ["op.mcp_retrieval"],
        "pdf": ["op.mcp_pdf"],
        "structured_data": ["op.mcp_structured_data"],
        "data": ["op.mcp_structured_data"],
    }.get(route, [])
