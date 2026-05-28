from __future__ import annotations

import uuid

from .models import EngagementContract, ResolvedEngagementPlan


class EngagementContractIssuer:
    authority = "task_system.engagement_contract_issuer"

    def issue(self, resolved: ResolvedEngagementPlan) -> EngagementContract:
        plan = resolved.plan
        return EngagementContract(
            contract_id=f"engagement-contract:{uuid.uuid4().hex[:12]}",
            request_id=resolved.request.request_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            task_environment_id=plan.task_environment_id,
            assignee=plan.assignee,
            runtime_profile=plan.runtime_profile,
            execution_strategy=plan.execution_strategy,
            startup_parameters=dict(resolved.request.startup_parameters or {}),
            input_contract=dict(plan.input_contract or {}),
            output_contract=dict(plan.output_contract or {}),
            prompt_contract=dict(plan.prompt_contract or {}),
            resource_requirements=dict(plan.resource_requirements or {}),
            capability_requirements=dict(plan.capability_requirements or {}),
            memory_requirements=dict(plan.memory_requirements or {}),
            acceptance_policy=dict(plan.acceptance_policy or {}),
            recovery_policy=dict(plan.recovery_policy or {}),
        )

