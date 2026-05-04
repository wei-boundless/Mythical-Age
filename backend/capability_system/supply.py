from __future__ import annotations

from pathlib import Path
from typing import Any

from .operation_registry import build_default_operation_registry
from .skill_registry import SkillRegistry
from .tool_registry import ToolRegistry
from .worker_registry import build_worker_catalog
from .catalog import MAIN_AGENT_ID, build_capability_catalog
from .models import (
    CapabilitySupplyPackage,
    CapabilitySupplySkillRef,
    CapabilitySupplyToolRef,
    CapabilitySupplyWorkerRef,
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
    workers = build_worker_catalog(operation_registry)
    catalog = {
        "skills": [
            {
                "runtime": {
                    "name": skill.runtime.name,
                    "title": skill.prompt_view.title,
                    "activation_policy": skill.runtime.activation_policy,
                    "context_mode": skill.runtime.context_mode,
                    "allowed_tools": list(skill.runtime.allowed_tools),
                },
                "allowed_operations": [
                    tool.operation_id
                    for tool in tool_registry.filter_names(list(skill.runtime.allowed_tools))
                    if tool.operation_id
                ],
            }
            for skill in skill_registry.skills
        ],
        "tools": [tool.to_registry_record() for tool in tool_registry.tools],
        "workers": workers,
        "capability_endpoints": build_capability_endpoints(workers=workers),
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
    workers = list(catalog.get("workers") or [])

    filtered_tools = [
        tool for tool in tools
        if not normalized_scope or str(tool.get("operation_id") or "").strip() in normalized_scope
    ]
    filtered_workers = [
        worker for worker in workers
        if not normalized_scope or str(worker.get("operation_id") or "").strip() in normalized_scope
    ]
    filtered_skills = [
        skill for skill in skills
        if not normalized_scope or set(str(item) for item in list(skill.get("allowed_operations") or [])).intersection(normalized_scope)
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
            allowed_tools=tuple(str(item) for item in list(((skill.get("runtime") or {}) if isinstance(skill.get("runtime"), dict) else {}).get("allowed_tools") or [])),
            allowed_operations=tuple(str(item) for item in list(skill.get("allowed_operations") or [])),
        )
        for skill in filtered_skills
    ]
    worker_refs = [
        CapabilitySupplyWorkerRef(
            worker_id=str(worker.get("worker_id") or ""),
            operation_id=str(worker.get("operation_id") or ""),
            route=str(worker.get("route") or ""),
            agent_id=str(worker.get("agent_id") or ""),
            transport=str(worker.get("transport") or ""),
            model_visibility=str(worker.get("model_visibility") or ""),
        )
        for worker in filtered_workers
    ]

    available_operation_ids = sorted({
        *[ref.operation_id for ref in tool_refs if ref.operation_id],
        *[ref.operation_id for ref in worker_refs if ref.operation_id],
        *[
            operation_id
            for ref in skill_refs
            for operation_id in ref.allowed_operations
            if operation_id
        ],
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
    hidden_worker_refs = sorted(
        ref.worker_id for ref in worker_refs if ref.model_visibility == "not_direct_model_tool"
    )

    return CapabilitySupplyPackage(
        package_id=f"capsupply:{task_id}:{agent_id}",
        task_id=task_id,
        agent_id=agent_id,
        tool_refs=tool_refs,
        skill_refs=skill_refs,
        worker_refs=worker_refs,
        capability_constraints={
            "operation_scope": sorted(normalized_scope),
            "available_operation_ids": available_operation_ids,
        },
        visibility_rules={
            "main_runtime_tools": main_runtime_tools,
            "agent_internal_tools": agent_internal_tools,
            "model_visible_skills": model_visible_skills,
            "hidden_worker_refs": hidden_worker_refs,
        },
        diagnostics={
            "tool_count": len(tool_refs),
            "skill_count": len(skill_refs),
            "worker_count": len(worker_refs),
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
