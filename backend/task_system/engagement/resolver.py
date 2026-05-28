from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from task_system.environments import build_task_environment_catalog, task_environment_registry_from_backend_dir

from .models import EngagementRequest, ResolvedEngagementPlan
from .repository import EngagementPlanRepository


def resolve_engagement_plan(
    *,
    backend_dir: Path | str,
    request: EngagementRequest,
) -> ResolvedEngagementPlan:
    plan = EngagementPlanRepository(backend_dir).get(request.plan_id)
    if plan is None:
        raise KeyError(f"engagement plan not found: {request.plan_id}")
    environment_registry = task_environment_registry_from_backend_dir(backend_dir)
    task_environment = build_task_environment_catalog(registry=environment_registry).runtime_environment_payload(
        plan.task_environment_id
    )
    assignee_profile: dict[str, Any] = {}
    if plan.assignee.kind == "agent":
        profile_ref = plan.assignee.agent_id or "agent:0"
        profile = AgentRuntimeRegistry(Path(backend_dir)).get_profile(profile_ref)
        if profile is not None:
            assignee_profile = profile.to_dict()
    return ResolvedEngagementPlan(
        request=request,
        plan=plan,
        task_environment=task_environment,
        assignee_profile=assignee_profile,
        execution_strategy=plan.execution_strategy,
        runtime_profile=plan.runtime_profile,
        missing_refs=_missing_refs(plan=plan, assignee_profile=assignee_profile),
    )


def _missing_refs(*, plan: Any, assignee_profile: dict[str, Any]) -> tuple[str, ...]:
    missing: list[str] = []
    if plan.assignee.kind == "agent" and not assignee_profile:
        missing.append(f"agent_profile:{plan.assignee.agent_id or 'agent:0'}")
    if plan.assignee.kind == "workflow" and not plan.assignee.workflow_id:
        missing.append("workflow_id")
    return tuple(missing)

