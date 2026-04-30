from __future__ import annotations

from typing import Any

from operations import ResourceDecision, ResourcePolicy
from ..runtime_directive import RuntimeDirective


def build_model_response_runtime_adoption(
    task_operation_preview: dict[str, Any],
) -> tuple[RuntimeDirective, ResourcePolicy]:
    """Adopt the current model-only lane into an executable directive.

    This is the first executable adoption path. It is intentionally narrow:
    model response only, no tools, no workers, no memory writes.
    """

    task_contract = dict(task_operation_preview.get("task_contract") or {})
    task_id = str(task_contract.get("task_id") or "task-runtime")
    plan_preview = dict(task_operation_preview.get("orchestration_plan_preview") or {})
    stages = list(plan_preview.get("stages") or [])
    stage_preview = dict(stages[0] if stages else {})
    policy_ref = f"respol:{task_id}:model-response:runtime"
    decision = ResourceDecision(
        operation_id="op.model_response",
        decision="allow",
        reason="model-only response is the phase-1 executable lane",
        risk_tags=("model_only", "read_only"),
    )
    resource_policy = ResourcePolicy(
        policy_id=policy_ref,
        task_id=task_id,
        allowed_operations=("op.model_response",),
        denied_operations=(),
        requires_approval_operations=(),
        preview_only_operations=(),
        allowed_tools=(),
        denied_tools=(),
        allowed_workers=(),
        denied_workers=(),
        allowed_agents=(),
        denied_agents=(),
        memory_read_scope="context_package_preview",
        memory_write_scope="none",
        approval_policy="model_only",
        preview_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=(decision,),
        diagnostics={
            "runtime_executable": True,
            "adopted": True,
            "model_only": True,
            "tools_allowed": False,
            "workers_allowed": False,
            "memory_write_allowed": False,
            "filesystem_write_allowed": False,
            "legacy_query_chain_removed": True,
            "adoption_owner": "TaskRunLoop",
        },
    )
    directive = RuntimeDirective(
        directive_id=f"runtime-directive:{task_id}:model-response",
        task_id=task_id,
        plan_ref=str(plan_preview.get("plan_id") or f"orchplan:{task_id}").replace(":preview", ":runtime"),
        stage_ref=str(stage_preview.get("stage_id") or f"orchstage:{task_id}:model").replace(":preview", ":runtime"),
        executor_type="model",
        adopted_resource_policy_ref=policy_ref,
        operation_refs=("op.model_response",),
        input_contract_ref=str(task_operation_preview.get("task_prompt_contract", {}).get("contract_id") or ""),
        output_contract_ref=str(task_operation_preview.get("task_prompt_contract", {}).get("contract_id") or ""),
        execution_graph_ref=str(
            task_operation_preview.get("execution_graph_preview", {}).get("graph_preview_id") or ""
        ).replace(":preview", ":runtime"),
        runtime_executable=True,
        diagnostics={
            "source_preview_plan_ref": str(plan_preview.get("plan_id") or ""),
            "source_preview_stage_ref": str(stage_preview.get("stage_id") or ""),
            "directive_only_executor": True,
            "model_only": True,
            "legacy_query_chain_removed": True,
            "adoption_owner": "TaskRunLoop",
        },
    )
    return directive, resource_policy
