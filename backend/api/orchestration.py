from __future__ import annotations

from typing import Any
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from operations import build_default_operation_registry
from orchestration import AgentRuntimeRegistry, ControlKernel, TaskContract, build_base_unit_catalog
from tasks import TaskFlowRegistry, TaskWorkflowRegistry

router = APIRouter()


class BehaviorDryRunRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1)
    ephemeral_system_messages: list[str] = Field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)


class OrchestrationModeRequest(BaseModel):
    mode: str = Field(default="primary")


class AgentRuntimeProfileRequest(BaseModel):
    agent_profile_id: str = Field(default="", max_length=160)
    allowed_task_modes: list[str] = Field(default_factory=list)
    allowed_runtime_lanes: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    blocked_operations: list[str] = Field(default_factory=list)
    allowed_memory_scopes: list[str] = Field(default_factory=list)
    allowed_context_sections: list[str] = Field(default_factory=list)
    output_contracts: list[str] = Field(default_factory=list)
    approval_policy: str = Field(default="default", max_length=80)
    trace_policy: str = Field(default="runtime_event_log", max_length=120)
    lifecycle_policy: str = Field(default="orchestration_managed", max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/orchestration/dry-run")
async def orchestration_dry_run(payload: BehaviorDryRunRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        task = TaskContract(
            task_id=f"dry-run:{payload.session_id}",
            session_id=payload.session_id,
            user_goal=payload.message,
            inputs={
                "ephemeral_system_message_count": len(payload.ephemeral_system_messages),
                "explicit_subtask_count": len(payload.explicit_subtasks),
            },
        )
        control = ControlKernel().collect(task=task)
        return {
            "state": "wiring_cleared",
            "control": control.to_dict(),
            "unit_catalog": build_base_unit_catalog().to_list(),
            "runtime_available": runtime is not None,
        }
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
        "orchestration_state": "wiring_cleared",
        "supported_orchestration_plan_modes": ["primary"],
        "unit_catalog": build_base_unit_catalog().to_list(),
        "skills": skills,
        "tools": tools,
    }


@router.get("/orchestration/agents")
async def orchestration_agents() -> dict[str, Any]:
    runtime = require_runtime()
    registry = AgentRuntimeRegistry(runtime.base_dir)
    catalog = registry.build_catalog()
    task_registry = TaskFlowRegistry(runtime.base_dir)
    operations = build_default_operation_registry().list_operations()
    workflows = TaskWorkflowRegistry(runtime.base_dir).list_workflows()
    return {
        **catalog,
        "options": {
            "operations": [item.to_dict() for item in operations],
            "task_modes": sorted({item.task_mode for item in task_registry.list_flows() if item.task_mode}),
            "runtime_lanes": sorted({item.default_runtime_lane for item in task_registry.list_flows() if item.default_runtime_lane}),
            "memory_scopes": sorted({item.default_memory_scope for item in task_registry.list_flows() if item.default_memory_scope}),
            "context_sections": [
                "conversation",
                "state",
                "task",
                "projection",
                "tool",
                "health_issue",
                "runtime_trace",
                "prompt_manifest",
                "memory_runtime_view",
                "assertions",
            ],
            "output_contracts": sorted(
                {
                    *[item.output_contract_id for item in task_registry.list_flows() if item.output_contract_id],
                    *[item.output_contract_id for item in workflows if item.output_contract_id],
                    "AssistantFinalAnswer",
                }
            ),
            "approval_policies": ["default", "read_only_first", "manual_approval_required", "deny_destructive"],
            "trace_policies": ["runtime_event_log", "full_trace", "minimal_trace"],
        },
    }


@router.put("/orchestration/agents/{agent_id}/runtime-profile")
async def upsert_orchestration_agent_runtime_profile(
    agent_id: str,
    payload: AgentRuntimeProfileRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        AgentRuntimeRegistry(runtime.base_dir).upsert_profile(
            agent_id=agent_id,
            agent_profile_id=payload.agent_profile_id,
            allowed_task_modes=tuple(payload.allowed_task_modes),
            allowed_runtime_lanes=tuple(payload.allowed_runtime_lanes),
            allowed_operations=tuple(payload.allowed_operations),
            blocked_operations=tuple(payload.blocked_operations),
            allowed_memory_scopes=tuple(payload.allowed_memory_scopes),
            allowed_context_sections=tuple(payload.allowed_context_sections),
            output_contracts=tuple(payload.output_contracts),
            approval_policy=payload.approval_policy,
            trace_policy=payload.trace_policy,
            lifecycle_policy=payload.lifecycle_policy,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await orchestration_agents()


@router.post("/orchestration/catalog/refresh")
async def refresh_orchestration_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    runtime.refresh_catalogs()
    return await orchestration_catalog()


@router.get("/orchestration/runtime-loop/sessions/{session_id}/task-runs")
async def list_runtime_loop_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_session_traces(session_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}")
async def get_runtime_loop_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.query_runtime.task_run_loop.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.put("/orchestration/plan-mode")
async def set_orchestration_plan_mode(payload: OrchestrationModeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    config = runtime.settings.set_orchestration_plan_mode(payload.mode)
    return {
        "mode": str(config.get("orchestration_plan_mode", "primary") or "primary"),
        "supported_modes": ["primary"],
    }
