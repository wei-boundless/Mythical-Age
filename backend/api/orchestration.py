from __future__ import annotations

from typing import Any
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from orchestration import build_behavior_dry_run

router = APIRouter()


class BehaviorDryRunRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1)
    ephemeral_system_messages: list[str] = Field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)


class OrchestrationModeRequest(BaseModel):
    mode: str = Field(default="plan_only")


class PrimaryEntrySelectionRequest(BaseModel):
    enabled: bool = False


@router.post("/orchestration/dry-run")
async def orchestration_dry_run(payload: BehaviorDryRunRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await build_behavior_dry_run(
            runtime,
            session_id=payload.session_id,
            message=payload.message,
            ephemeral_system_messages=payload.ephemeral_system_messages,
            explicit_subtasks=payload.explicit_subtasks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orchestration/catalog")
async def orchestration_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    skills = []
    for skill in runtime.skill_registry.skills:
        skills.append(
            {
                "runtime": asdict(skill.runtime),
                "prompt_view": skill.prompt_view.to_dict() if hasattr(skill.prompt_view, "to_dict") else {
                    "name": skill.prompt_view.name,
                    "title": skill.prompt_view.title,
                    "capability": skill.prompt_view.capability,
                    "use_when": skill.prompt_view.use_when,
                    "output_rule": skill.prompt_view.output_rule,
                },
                "tool_scope": skill.tool_scope().to_dict(),
            }
        )
    tools = [tool.to_registry_record() for tool in runtime.tool_runtime.definitions]
    return {
        "permission_mode": runtime.permission_service.current_mode(),
        "supported_permission_modes": runtime.permission_service.supported_modes(),
        "tool_contract_mode": runtime.query_runtime.tool_contract_gate.mode,
        "orchestration_plan_mode": runtime.settings.get_orchestration_plan_mode(),
        "supported_orchestration_plan_modes": ["legacy", "plan_only", "primary"],
        "primary_entry_selection_enabled": runtime.settings.get_primary_entry_selection_enabled(),
        "skills": skills,
        "tools": tools,
    }


@router.post("/orchestration/catalog/refresh")
async def refresh_orchestration_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    runtime.refresh_catalogs()
    return await orchestration_catalog()


@router.put("/orchestration/plan-mode")
async def set_orchestration_plan_mode(payload: OrchestrationModeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    config = runtime.settings.set_orchestration_plan_mode(payload.mode)
    return {
        "mode": str(config.get("orchestration_plan_mode", "plan_only") or "plan_only"),
        "supported_modes": ["legacy", "plan_only", "primary"],
    }


@router.put("/orchestration/primary-entry-selection")
async def set_primary_entry_selection(payload: PrimaryEntrySelectionRequest) -> dict[str, Any]:
    runtime = require_runtime()
    config = runtime.settings.set_primary_entry_selection_enabled(payload.enabled)
    return {
        "enabled": bool(config.get("primary_entry_selection_enabled", False)),
    }
