from __future__ import annotations

import re
from typing import Any

from task_system.planning.task_split_merge_models import (
    BatchAcceptancePolicy,
    BatchLifecyclePlan,
    BatchLifecycleStep,
    BatchMergePolicy,
    BatchMergeReadinessPlan,
    BatchRange,
    BatchSpec,
    SplitMergeIssue,
    StaticSplitPlan,
)


SUPPORTED_SPLIT_MODES = {"static_batch"}
SUPPORTED_ACCEPTANCE_MODES = {
    "review_then_commit",
    "manual_review_then_commit",
    "auto_commit_without_review",
}
SUPPORTED_MERGE_MODES = {"wait_all_committed", "manual_merge"}
SUPPORTED_RESULT_ORDERS = {"batch_sequence", "range_start"}
DEFAULT_MAX_BATCHES = 200


def build_static_split_plan(
    *,
    graph_id: str,
    node_id: str,
    contract_bindings: dict[str, Any],
) -> StaticSplitPlan | None:
    bindings = dict(contract_bindings or {})
    unit_batch = _record(bindings.get("unit_batch"))
    runtime = _record(bindings.get("runtime"))
    split_policy = _record(runtime.get("split_policy"))
    if not unit_batch and not split_policy:
        return None

    unit_kind = _string(unit_batch.get("unit_kind"), "unit")
    requested_count = _int_value(unit_batch.get("requested_count"), 0)
    range_start = _positive_int(unit_batch.get("range_start"), 1)
    split_mode = _string(split_policy.get("mode"), "static_batch")
    batch_size = _int_value(split_policy.get("batch_size"), 0)
    max_batches = _positive_int(split_policy.get("max_batches"), DEFAULT_MAX_BATCHES)
    child_execution_mode = _string(split_policy.get("child_execution_mode"), "sequential")
    max_parallel_batches = _int_value(
        split_policy.get("max_parallel_batches")
        or split_policy.get("max_concurrency")
        or split_policy.get("parallelism"),
        0,
    )
    template = _string(split_policy.get("range_label_template"), "{unit_kind}_{start}_{end}")
    plan_id = _plan_id(graph_id=graph_id, node_id=node_id, unit_kind=unit_kind)
    issues: list[SplitMergeIssue] = []

    if split_mode not in SUPPORTED_SPLIT_MODES:
        issues.append(
            _issue(
                "split_mode_unsupported",
                f"拆分模式暂不支持：{split_mode}",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    if requested_count <= 0:
        issues.append(
            _issue(
                "unit_batch_requested_count_missing",
                "unit_batch.requested_count 必须大于 0，编译器才能确定要拆成多少个工作单元。",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    if batch_size <= 0:
        issues.append(
            _issue(
                "split_policy_batch_size_missing",
                "runtime.split_policy.batch_size 必须大于 0，编译器才能生成批次范围。",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    if child_execution_mode not in {"sequential", "parallel"}:
        issues.append(
            _issue(
                "split_policy_child_execution_mode_unsupported",
                f"批次执行模式暂不支持：{child_execution_mode}",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    if child_execution_mode == "parallel" and max_parallel_batches < 0:
        issues.append(
            _issue(
                "split_policy_parallel_limit_invalid",
                "runtime.split_policy.max_parallel_batches 不能小于 0。",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )

    acceptance_policy, acceptance_issues = _acceptance_policy(
        bindings=bindings,
        graph_id=graph_id,
        node_id=node_id,
        plan_id=plan_id,
    )
    merge_policy, merge_issues = _merge_policy(
        bindings=bindings,
        graph_id=graph_id,
        node_id=node_id,
        plan_id=plan_id,
    )
    issues.extend(acceptance_issues)
    issues.extend(merge_issues)

    batches: list[BatchSpec] = []
    batch_lifecycle_plans: list[BatchLifecyclePlan] = []
    merge_readiness_plan: BatchMergeReadinessPlan | None = None
    if split_mode in SUPPORTED_SPLIT_MODES and requested_count > 0 and batch_size > 0:
        batch_count = ((requested_count - 1) // batch_size) + 1
        if batch_count > max_batches:
            issues.append(
                _issue(
                    "split_policy_max_batches_exceeded",
                    f"静态拆分会生成 {batch_count} 个批次，超过 max_batches={max_batches}。",
                    graph_id=graph_id,
                    node_id=node_id,
                    plan_id=plan_id,
                )
            )
        else:
            batches = _build_batches(
                graph_id=graph_id,
                node_id=node_id,
                unit_kind=unit_kind,
                requested_count=requested_count,
                batch_size=batch_size,
                range_start=range_start,
                template=template,
                unit_batch=unit_batch,
            )
            batch_lifecycle_plans = _build_batch_lifecycle_plans(
                graph_id=graph_id,
                node_id=node_id,
                split_plan_id=plan_id,
                batches=batches,
                acceptance_policy=acceptance_policy,
                child_execution_mode=child_execution_mode,
            )
            merge_readiness_plan = _build_merge_readiness_plan(
                graph_id=graph_id,
                node_id=node_id,
                split_plan_id=plan_id,
                lifecycle_plans=batch_lifecycle_plans,
                merge_policy=merge_policy,
            )

    return StaticSplitPlan(
        plan_id=plan_id,
        graph_id=graph_id,
        node_id=node_id,
        unit_kind=unit_kind,
        requested_count=requested_count,
        batch_size=batch_size,
        range_start=range_start,
        batches=tuple(batches),
        batch_lifecycle_plans=tuple(batch_lifecycle_plans),
        merge_readiness_plan=merge_readiness_plan,
        acceptance_policy=acceptance_policy,
        merge_policy=merge_policy,
        issues=tuple(issues),
        metadata={
            "authority": "task_system.static_split_plan",
            "source_path": f"graph.nodes[{node_id}].contract_bindings",
            "split_mode": split_mode,
            "child_execution_mode": child_execution_mode,
            **({"max_parallel_batches": max_parallel_batches} if child_execution_mode == "parallel" and max_parallel_batches > 0 else {}),
            "max_batches": max_batches,
        },
    )


def build_static_split_plans_for_graph(*, graph: Any) -> tuple[StaticSplitPlan, ...]:
    graph_id = _string(getattr(graph, "graph_id", ""), "graph")
    plans: list[StaticSplitPlan] = []
    for node in getattr(graph, "nodes", ()) or ():
        node_id = _string(getattr(node, "node_id", ""), "node")
        plan = build_static_split_plan(
            graph_id=graph_id,
            node_id=node_id,
            contract_bindings=_record(getattr(node, "contract_bindings", {})),
        )
        if plan is not None:
            plans.append(plan)
    return tuple(plans)


def split_merge_runtime_issues(plans: tuple[StaticSplitPlan, ...]) -> tuple[SplitMergeIssue, ...]:
    issues: list[SplitMergeIssue] = []
    for plan in plans:
        issues.extend(plan.issues)
    return tuple(issues)


def _build_batches(
    *,
    graph_id: str,
    node_id: str,
    unit_kind: str,
    requested_count: int,
    batch_size: int,
    range_start: int,
    template: str,
    unit_batch: dict[str, Any],
) -> list[BatchSpec]:
    input_contract_id = _string(unit_batch.get("input_contract_id"))
    output_contract_id = _string(unit_batch.get("output_contract_id"))
    metadata = _record(unit_batch.get("metadata"))
    batches: list[BatchSpec] = []
    current_start = range_start
    final_end = range_start + requested_count - 1
    sequence_index = 1
    while current_start <= final_end:
        current_end = min(current_start + batch_size - 1, final_end)
        label = _range_label(
            template=template,
            unit_kind=unit_kind,
            start=current_start,
            end=current_end,
            sequence_index=sequence_index,
        )
        batch_id = _safe_identifier(label, fallback=f"{unit_kind}_{current_start}_{current_end}")
        batches.append(
            BatchSpec(
                batch_id=batch_id,
                sequence_index=sequence_index,
                unit_kind=unit_kind,
                range=BatchRange(start=current_start, end=current_end, label=label),
                input_contract_id=input_contract_id,
                output_contract_id=output_contract_id,
                idempotency_key=f"{graph_id}:{node_id}:{unit_kind}:{current_start}:{current_end}",
                metadata=dict(metadata),
            )
        )
        current_start = current_end + 1
        sequence_index += 1
    return batches


def _build_batch_lifecycle_plans(
    *,
    graph_id: str,
    node_id: str,
    split_plan_id: str,
    batches: list[BatchSpec],
    acceptance_policy: BatchAcceptancePolicy,
    child_execution_mode: str,
) -> list[BatchLifecyclePlan]:
    lifecycle_plans: list[BatchLifecyclePlan] = []
    previous_commit_step_id = ""
    sequential = child_execution_mode != "parallel"
    for batch in batches:
        step_prefix = f"{split_plan_id}:{batch.batch_id}"
        execute_step_id = f"{step_prefix}:execute"
        execute_depends_on: tuple[str, ...] = (
            (previous_commit_step_id,)
            if sequential and previous_commit_step_id and acceptance_policy.commit_visibility == "next_batch_after_acceptance"
            else ()
        )
        execute_step = BatchLifecycleStep(
            step_id=execute_step_id,
            step_type="execute",
            title="执行批次任务",
            sequence_index=1,
            depends_on=execute_depends_on,
            consumes=("batch_input_packet",),
            produces=("batch_candidate_packet",),
            policy={
                "batch_id": batch.batch_id,
                "unit_kind": batch.unit_kind,
                "range": batch.range.to_dict(),
                "idempotency_key": batch.idempotency_key,
            },
        )
        steps: list[BatchLifecycleStep] = [execute_step]
        commit_depends_on = execute_step_id
        if acceptance_policy.mode != "auto_commit_without_review":
            review_step_id = f"{step_prefix}:review"
            review_step = BatchLifecycleStep(
                step_id=review_step_id,
                step_type="review",
                title="审核批次候选结果",
                sequence_index=2,
                depends_on=(execute_step_id,),
                consumes=("batch_candidate_packet",),
                produces=("batch_review_verdict",),
                policy={
                    "mode": acceptance_policy.mode,
                    "review_graph_id": acceptance_policy.review_graph_id,
                    "review_node_id": acceptance_policy.review_node_id,
                },
            )
            repair_step_id = f"{step_prefix}:repair_loop"
            repair_step = BatchLifecycleStep(
                step_id=repair_step_id,
                step_type="repair_loop",
                title="按审核裁决返修批次",
                sequence_index=3,
                depends_on=(review_step_id,),
                consumes=("batch_candidate_packet", "batch_review_verdict"),
                produces=("batch_repaired_candidate_packet", "batch_review_verdict"),
                policy={
                    "repair_policy": acceptance_policy.repair_policy,
                    "max_repair_rounds": acceptance_policy.max_repair_rounds,
                    "exit_on": ["review_passed", "manual_gate", "repair_rounds_exhausted"],
                },
            )
            steps.extend([review_step, repair_step])
            commit_depends_on = repair_step_id
        commit_step_id = f"{step_prefix}:commit"
        commit_step = BatchLifecycleStep(
            step_id=commit_step_id,
            step_type="commit",
            title="提交批次正式结果",
            sequence_index=len(steps) + 1,
            depends_on=(commit_depends_on,),
            consumes=("batch_candidate_packet", "batch_review_verdict") if acceptance_policy.mode != "auto_commit_without_review" else ("batch_candidate_packet",),
            produces=("batch_committed_packet",),
            policy={
                "mode": acceptance_policy.mode,
                "commit_visibility": acceptance_policy.commit_visibility,
                "committed_visibility_scope": "downstream_and_merge_only",
            },
        )
        steps.append(commit_step)
        lifecycle_plans.append(
            BatchLifecyclePlan(
                plan_id=f"{step_prefix}:lifecycle",
                graph_id=graph_id,
                node_id=node_id,
                split_plan_id=split_plan_id,
                batch_id=batch.batch_id,
                sequence_index=batch.sequence_index,
                unit_kind=batch.unit_kind,
                range=batch.range,
                steps=tuple(steps),
                metadata={
                    "authority": "task_system.batch_lifecycle_plan",
                    "child_execution_mode": child_execution_mode,
                    "source_batch_id": batch.batch_id,
                    "source_idempotency_key": batch.idempotency_key,
                },
            )
        )
        previous_commit_step_id = commit_step_id
    return lifecycle_plans


def _build_merge_readiness_plan(
    *,
    graph_id: str,
    node_id: str,
    split_plan_id: str,
    lifecycle_plans: list[BatchLifecyclePlan],
    merge_policy: BatchMergePolicy,
) -> BatchMergeReadinessPlan | None:
    if not lifecycle_plans:
        return None
    commit_step_ids = tuple(
        step.step_id
        for plan in lifecycle_plans
        for step in plan.steps
        if step.step_type == "commit"
    )
    batch_ids = tuple(plan.batch_id for plan in lifecycle_plans)
    return BatchMergeReadinessPlan(
        plan_id=f"{split_plan_id}:merge_readiness",
        graph_id=graph_id,
        node_id=node_id,
        split_plan_id=split_plan_id,
        merge_id=f"{split_plan_id}:merge",
        mode=merge_policy.mode,
        result_order=merge_policy.result_order,
        allow_partial=merge_policy.allow_partial,
        final_review_required=merge_policy.final_review_required,
        depends_on_batch_ids=batch_ids,
        depends_on_commit_step_ids=commit_step_ids,
        ready_condition="all_batches_committed" if not merge_policy.allow_partial else "committed_batches_available",
        metadata={
            "authority": "task_system.batch_merge_readiness_plan",
            "merge_consumes": "batch_committed_packet",
            "merge_rejects": ["batch_candidate_packet", "batch_review_rejected_packet"],
        },
    )


def _acceptance_policy(
    *,
    bindings: dict[str, Any],
    graph_id: str,
    node_id: str,
    plan_id: str,
) -> tuple[BatchAcceptancePolicy, list[SplitMergeIssue]]:
    runtime = _record(bindings.get("runtime"))
    acceptance = _record(bindings.get("acceptance"))
    policy = {
        **_record(acceptance.get("batch_acceptance_policy")),
        **_record(runtime.get("batch_acceptance_policy")),
    }
    mode = _string(policy.get("mode"), "review_then_commit")
    max_repair_rounds = _int_value(policy.get("max_repair_rounds"), 3)
    issues: list[SplitMergeIssue] = []
    if mode not in SUPPORTED_ACCEPTANCE_MODES:
        issues.append(
            _issue(
                "batch_acceptance_mode_unsupported",
                f"批次验收模式暂不支持：{mode}",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    if mode == "auto_commit_without_review":
        issues.append(
            _issue(
                "batch_acceptance_auto_commit_without_review",
                "批次配置为无审核自动提交；这不会阻塞编译，但运行风险较高。",
                severity="warning",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    if max_repair_rounds <= 0:
        issues.append(
            _issue(
                "batch_acceptance_repair_rounds_invalid",
                "max_repair_rounds 必须大于 0。",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
        max_repair_rounds = 0
    return (
        BatchAcceptancePolicy(
            mode=mode,
            review_graph_id=_string(policy.get("review_graph_id")),
            review_node_id=_string(policy.get("review_node_id")),
            repair_policy=_string(policy.get("repair_policy"), "repair_until_pass_or_manual_gate"),
            max_repair_rounds=max_repair_rounds,
            commit_visibility=_string(policy.get("commit_visibility"), "next_batch_after_acceptance"),
        ),
        issues,
    )


def _merge_policy(
    *,
    bindings: dict[str, Any],
    graph_id: str,
    node_id: str,
    plan_id: str,
) -> tuple[BatchMergePolicy, list[SplitMergeIssue]]:
    runtime = _record(bindings.get("runtime"))
    policy = {
        **_record(bindings.get("merge_policy")),
        **_record(runtime.get("merge_policy")),
    }
    mode = _string(policy.get("mode"), "wait_all_committed")
    result_order = _string(policy.get("result_order"), "batch_sequence")
    issues: list[SplitMergeIssue] = []
    if mode not in SUPPORTED_MERGE_MODES:
        issues.append(
            _issue(
                "batch_merge_mode_unsupported",
                f"批次合并模式暂不支持：{mode}",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    if result_order not in SUPPORTED_RESULT_ORDERS:
        issues.append(
            _issue(
                "batch_merge_result_order_unsupported",
                f"批次合并排序暂不支持：{result_order}",
                graph_id=graph_id,
                node_id=node_id,
                plan_id=plan_id,
            )
        )
    return (
        BatchMergePolicy(
            mode=mode,
            result_order=result_order,
            allow_partial=bool(policy.get("allow_partial", False)),
            final_review_required=bool(policy.get("final_review_required", True)),
        ),
        issues,
    )


def _issue(
    code: str,
    message: str,
    *,
    graph_id: str,
    node_id: str,
    plan_id: str,
    severity: str = "error",
) -> SplitMergeIssue:
    return SplitMergeIssue(
        code=code,
        message=message,
        severity=severity,
        graph_id=graph_id,
        node_id=node_id,
        plan_id=plan_id,
    )


def _range_label(
    *,
    template: str,
    unit_kind: str,
    start: int,
    end: int,
    sequence_index: int,
) -> str:
    try:
        return template.format(
            unit_kind=unit_kind,
            start=start,
            end=end,
            sequence_index=sequence_index,
        )
    except (KeyError, IndexError, ValueError):
        return f"{unit_kind}_{start}_{end}"


def _plan_id(*, graph_id: str, node_id: str, unit_kind: str) -> str:
    return f"split.{_safe_identifier(graph_id)}.{_safe_identifier(node_id)}.{_safe_identifier(unit_kind)}"


def _safe_identifier(value: str, fallback: str = "unit") -> str:
    normalized = re.sub(r"[^0-9A-Za-z_.:-]+", ".", str(value or "").strip())
    normalized = ".".join(part for part in normalized.replace(":", ".").split(".") if part)
    return normalized or fallback


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _positive_int(value: Any, fallback: int) -> int:
    parsed = _int_value(value, fallback)
    return parsed if parsed > 0 else fallback


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


