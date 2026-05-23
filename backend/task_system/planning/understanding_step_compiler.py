from __future__ import annotations

from typing import Any

from task_system.tasks.step_models import TaskStepBlueprint


SYSTEM_STEP_KINDS = {
    "turn_intake",
    "context_resolution",
    "task_goal_understanding",
    "domain_flow_matching",
    "contract_compilation",
    "prompt_assembly",
    "execution_planning",
    "plan_coverage_review",
    "step_execution",
    "verification",
    "finalization",
}


def compile_understanding_runtime_steps(
    *,
    interaction_mode: str,
    semantic_contract: dict[str, Any] | None = None,
    mode_policy: dict[str, Any] | None = None,
    execution_obligation: dict[str, Any] | None = None,
    plan_coverage_review: dict[str, Any] | None = None,
) -> tuple[TaskStepBlueprint, ...]:
    mode = str(interaction_mode or "").strip() or "standard_mode"
    contract = dict(semantic_contract or {})
    policy = dict(mode_policy or {})
    obligation = dict(execution_obligation or contract.get("execution_obligation") or {})
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    plan_coverage = dict(plan_coverage_review or {})

    if mode == "role_mode":
        return (
            _step(
                "turn_intake",
                "Turn intake",
                "turn_intake",
                output_contract_id="current_turn_context",
            ),
            _step(
                "context_resolution",
                "Resolve role context",
                "context_resolution",
                input_refs=("current_turn_context",),
                output_contract_id="role_context",
            ),
            _step(
                "prompt_assembly",
                "Assemble role prompt",
                "prompt_assembly",
                input_refs=("role_context",),
                output_contract_id="prompt_assembly",
            ),
            _step(
                "finalization",
                "Finalize response",
                "finalization",
                input_refs=("prompt_assembly",),
                output_contract_id="final_answer",
            ),
        )

    if mode == "professional_mode":
        core = (
            *_core_understanding_steps(contract=contract, policy=policy, obligation=obligation),
            _step(
                "execution_planning",
                "Plan executable stages",
                "execution_planning",
                input_refs=("semantic_task_contract", "execution_obligation", "runtime_interaction_mode_policy"),
                output_contract_id="execution_plan_draft",
            ),
            _step(
                "plan_coverage_review",
                "Review plan coverage",
                "plan_coverage_review",
                input_refs=("execution_plan_draft", "semantic_task_contract", "execution_obligation"),
                output_contract_id="plan_coverage_review",
            ),
        )
        if plan_coverage and plan_coverage.get("passed") is not True:
            return (
                *core,
                _step(
                    "finalization",
                    "Finalize blocked plan review",
                    "finalization",
                    input_refs=("plan_coverage_review", "semantic_task_contract"),
                    output_contract_id="blocked_replan_required",
                ),
            )
        return (
            *core,
            *_domain_execution_steps(task_goal_type=task_goal_type, contract=contract, obligation=obligation),
            _step(
                "verification",
                "Verify deliverables against evidence",
                "verification",
                input_refs=("semantic_task_contract", "execution_evidence"),
                output_contract_id="verification_evidence",
                required_operations=("op.model_response",),
                optional_operations=_verification_operations(policy=policy, contract=contract, obligation=obligation),
            ),
            _step(
                "finalization",
                "Finalize user-facing result",
                "finalization",
                input_refs=("verification_evidence", "semantic_task_contract"),
                output_contract_id="final_answer",
            ),
        )

    return (
        *_core_understanding_steps(contract=contract, policy=policy, obligation=obligation),
        _step(
            "step_execution",
            "Execute current task",
            "step_execution",
            input_refs=("semantic_task_contract", "execution_obligation", "prompt_assembly"),
            output_contract_id="execution_evidence",
            optional_operations=_execution_operations(policy=policy, contract=contract, obligation=obligation),
        ),
        _step(
            "verification",
            "Verify result",
            "verification",
            input_refs=("execution_evidence",),
            output_contract_id="verification_evidence",
            optional_operations=_verification_operations(policy=policy, contract=contract, obligation=obligation),
        ),
        _step(
            "finalization",
            "Finalize response",
            "finalization",
            input_refs=("verification_evidence",),
            output_contract_id="final_answer",
        ),
    )


def _core_understanding_steps(
    *,
    contract: dict[str, Any],
    policy: dict[str, Any],
    obligation: dict[str, Any],
) -> tuple[TaskStepBlueprint, ...]:
    _ = policy, obligation
    return (
        _step(
            "turn_intake",
            "Turn intake",
            "turn_intake",
            output_contract_id="current_turn_context",
        ),
        _step(
            "context_resolution",
            "Resolve context",
            "context_resolution",
            input_refs=("current_turn_context",),
            output_contract_id="resolved_context",
        ),
        _step(
            "task_goal_understanding",
            "Understand task goal",
            "task_goal_understanding",
            input_refs=("resolved_context",),
            output_contract_id="task_goal_frame",
        ),
        _step(
            "domain_flow_matching",
            "Match task domain flow",
                "domain_flow_matching",
                input_refs=("task_goal_frame",),
                output_contract_id="task_goal_profile_binding",
            ),
            _step(
                "contract_compilation",
                "Compile semantic contract",
                "contract_compilation",
                input_refs=("task_goal_frame", "task_goal_profile_binding"),
                output_contract_id=str(contract.get("contract_id") or "semantic_task_contract"),
            ),
        _step(
            "prompt_assembly",
            "Assemble task prompt",
            "prompt_assembly",
            input_refs=("semantic_task_contract",),
            output_contract_id="prompt_assembly",
        ),
    )


def _domain_execution_steps(
    *,
    task_goal_type: str,
    contract: dict[str, Any],
    obligation: dict[str, Any],
) -> tuple[TaskStepBlueprint, ...]:
    reasoning_steps = [
        str(item).strip()
        for item in list(contract.get("required_reasoning_steps") or [])
        if str(item).strip()
    ]
    filtered = [
        item
        for item in reasoning_steps
        if item
        not in {
            "understand_request",
            "understand_product_goal",
            "answer_with_boundaries",
            "synthesize_final_answer",
            "synthesize_delivery",
            "write_final_report",
        }
    ]
    if not filtered:
        filtered = ["execute_task_contract"]
    operations = _execution_operations(policy={}, contract=contract, obligation=obligation)
    return tuple(
        _step(
            f"step_execution.{_slug(item)}",
            _title_from_token(item),
            "step_execution",
            input_refs=("execution_plan_draft", "semantic_task_contract"),
            output_contract_id=f"{task_goal_type or 'task'}.{_slug(item)}.evidence",
            optional_operations=operations,
        )
        for item in filtered
    )


def _execution_operations(
    *,
    policy: dict[str, Any],
    contract: dict[str, Any],
    obligation: dict[str, Any],
) -> tuple[str, ...]:
    tool_policy = dict(policy.get("tool_policy") or {})
    allowed = [
        str(item).strip()
        for item in list(tool_policy.get("allowed_operation_refs") or [])
        if str(item).strip() and str(item).strip() != "op.model_response"
    ]
    actions = {str(item).strip() for item in list(contract.get("required_actions") or []) if str(item).strip()}
    if list(obligation.get("required_reads") or []) or "read_material" in actions or "inspect_code" in actions:
        allowed.extend(["op.read_file", "op.search_text"])
    if list(obligation.get("required_writes") or []) or "apply_real_change" in actions:
        allowed.extend(["op.write_file", "op.edit_file"])
    if "integrate_asset" in actions:
        allowed.extend(["op.write_file", "op.edit_file"])
    if "run_browser_verification" in actions:
        allowed.extend(["op.shell", "op.browser"])
    if list(obligation.get("required_commands") or []):
        allowed.append("op.shell")
    return _dedupe_tuple(allowed)


def _verification_operations(
    *,
    policy: dict[str, Any],
    contract: dict[str, Any],
    obligation: dict[str, Any],
) -> tuple[str, ...]:
    operations = list(_execution_operations(policy=policy, contract=contract, obligation=obligation))
    actions = {str(item).strip() for item in list(contract.get("required_actions") or []) if str(item).strip()}
    if "run_browser_verification" in actions:
        operations.extend(["op.shell", "op.browser"])
    if list(obligation.get("required_verifications") or []):
        operations.append("op.shell")
    return _dedupe_tuple(operations)


def _step(
    step_id: str,
    title: str,
    step_kind: str,
    *,
    executor_type: str = "model",
    required_operations: tuple[str, ...] = ("op.model_response",),
    optional_operations: tuple[str, ...] = (),
    input_refs: tuple[str, ...] = (),
    output_contract_id: str = "",
) -> TaskStepBlueprint:
    if step_kind not in SYSTEM_STEP_KINDS:
        raise ValueError(f"Unsupported understanding runtime step kind: {step_kind}")
    return TaskStepBlueprint(
        step_id=step_id,
        title=title,
        step_kind=step_kind,
        executor_type=executor_type,
        required_operations=required_operations,
        optional_operations=optional_operations,
        input_refs=input_refs,
        output_contract_id=output_contract_id,
    )


def _title_from_token(token: str) -> str:
    return str(token or "").replace("_", " ").strip().capitalize() or "Execute task step"


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "task_step"


def _dedupe_tuple(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
