from __future__ import annotations

from pathlib import Path

from api import task_system as tasks_api
from task_system import TaskFlowRegistry, build_static_split_plan
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from tests.support.runtime_stubs import RuntimeBaseDirStub


_RuntimeStub = RuntimeBaseDirStub


def test_static_split_plan_compiles_unit_batch_contract_into_ranges() -> None:
    plan = build_static_split_plan(
        graph_id="graph.test.split",
        node_id="produce",
        contract_bindings={
            "unit_batch": {
                "unit_kind": "chapter",
                "requested_count": 53,
                "range_start": 1,
                "input_contract_id": "contract.chapter.request",
                "output_contract_id": "contract.chapter.batch",
            },
            "runtime": {
                "split_policy": {
                    "mode": "static_batch",
                    "batch_size": 10,
                    "range_label_template": "chapter_{start}_{end}",
                },
                "batch_acceptance_policy": {
                    "mode": "review_then_commit",
                    "review_node_id": "review",
                    "max_repair_rounds": 2,
                },
                "merge_policy": {
                    "mode": "wait_all_committed",
                    "result_order": "batch_sequence",
                },
            },
        },
    )

    assert plan is not None
    assert plan.valid is True
    assert plan.unit_kind == "chapter"
    assert [(item.range.start, item.range.end) for item in plan.batches] == [
        (1, 10),
        (11, 20),
        (21, 30),
        (31, 40),
        (41, 50),
        (51, 53),
    ]
    assert plan.batches[0].batch_id == "chapter_1_10"
    assert plan.batches[0].input_contract_id == "contract.chapter.request"
    assert plan.batches[0].output_contract_id == "contract.chapter.batch"
    assert plan.acceptance_policy.review_node_id == "review"
    assert plan.acceptance_policy.max_repair_rounds == 2
    assert plan.merge_policy.mode == "wait_all_committed"
    assert len(plan.batch_lifecycle_plans) == 6
    assert [step.step_type for step in plan.batch_lifecycle_plans[0].steps] == [
        "execute",
        "review",
        "repair_loop",
        "commit",
    ]
    assert plan.batch_lifecycle_plans[1].steps[0].depends_on == (
        f"{plan.plan_id}:chapter_1_10:commit",
    )
    assert plan.merge_readiness_plan is not None
    assert plan.merge_readiness_plan.depends_on_batch_ids == tuple(item.batch_id for item in plan.batches)
    assert plan.merge_readiness_plan.depends_on_commit_step_ids[-1] == f"{plan.plan_id}:chapter_51_53:commit"


def test_static_split_plan_reports_contract_errors_without_generating_fake_batches() -> None:
    plan = build_static_split_plan(
        graph_id="graph.test.split",
        node_id="produce",
        contract_bindings={
            "unit_batch": {"unit_kind": "chapter", "requested_count": 50},
            "runtime": {"split_policy": {"mode": "dynamic_agent_decides"}},
        },
    )

    assert plan is not None
    assert plan.valid is False
    assert plan.batches == ()
    assert {issue.code for issue in plan.issues} == {
        "split_mode_unsupported",
        "split_policy_batch_size_missing",
    }


def test_static_split_plan_rejects_non_positive_batch_values() -> None:
    plan = build_static_split_plan(
        graph_id="graph.test.split",
        node_id="produce",
        contract_bindings={
            "unit_batch": {"unit_kind": "item", "requested_count": -1},
            "runtime": {
                "split_policy": {"mode": "static_batch", "batch_size": 0},
                "batch_acceptance_policy": {"max_repair_rounds": 0},
            },
        },
    )

    assert plan is not None
    assert plan.valid is False
    assert plan.batches == ()
    assert {issue.code for issue in plan.issues} == {
        "unit_batch_requested_count_missing",
        "split_policy_batch_size_missing",
        "batch_acceptance_repair_rounds_invalid",
    }


def test_runtime_spec_and_execution_package_expose_split_plan(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.execution_package_split",
        title="批次执行包图",
        graph_kind="multi_agent",
        nodes=(
            {
                "node_id": "produce",
                "node_type": "agent",
                "title": "生产节点",
                "agent_id": "agent:worker",
                "contract_bindings": {
                    "unit_batch": {
                        "unit_kind": "item",
                        "requested_count": 25,
                        "range_start": 1,
                    },
                    "runtime": {
                        "split_policy": {
                            "mode": "static_batch",
                            "batch_size": 10,
                        },
                        "batch_acceptance_policy": {"mode": "review_then_commit"},
                        "merge_policy": {"mode": "wait_all_committed"},
                    },
                },
            },
        ),
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    split_plans = spec.diagnostics["split_plans"]

    assert len(split_plans) == 1
    assert split_plans[0]["node_id"] == "produce"
    assert len(split_plans[0]["batches"]) == 3
    assert not any(issue.code.startswith("split_") for issue in spec.issues)

    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        import asyncio

        package = asyncio.run(tasks_api.build_task_system_task_graph_execution_package(graph.graph_id))
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert package["summary"]["split_plan_count"] == 1
    assert package["summary"]["split_batch_count"] == 3
    assert package["summary"]["split_batch_lifecycle_plan_count"] == 3
    assert package["summary"]["split_batch_lifecycle_step_count"] == 12
    assert package["summary"]["split_merge_readiness_plan_count"] == 1
    assert package["split_plans"][0]["plan_id"] == split_plans[0]["plan_id"]
    assert any(item["object_type"] == "split_plan" for item in package["object_trace_index"])
    assert any(item["object_type"] == "batch_lifecycle_plan" for item in package["object_trace_index"])
    assert any(item["object_type"] == "batch_merge_readiness_plan" for item in package["object_trace_index"])


def test_auto_commit_lifecycle_omits_review_and_repair_steps() -> None:
    plan = build_static_split_plan(
        graph_id="graph.test.split",
        node_id="produce",
        contract_bindings={
            "unit_batch": {"unit_kind": "file", "requested_count": 4, "range_start": 1},
            "runtime": {
                "split_policy": {"mode": "static_batch", "batch_size": 2, "child_execution_mode": "parallel"},
                "batch_acceptance_policy": {"mode": "auto_commit_without_review"},
                "merge_policy": {"mode": "manual_merge", "allow_partial": True, "final_review_required": False},
            },
        },
    )

    assert plan is not None
    assert len(plan.batch_lifecycle_plans) == 2
    assert [step.step_type for step in plan.batch_lifecycle_plans[0].steps] == ["execute", "commit"]
    assert plan.batch_lifecycle_plans[1].steps[0].depends_on == ()
    assert plan.merge_readiness_plan is not None
    assert plan.merge_readiness_plan.ready_condition == "committed_batches_available"
    assert {issue.code for issue in plan.issues} == {"batch_acceptance_auto_commit_without_review"}


def test_parallel_split_plan_carries_concurrency_limit_in_metadata() -> None:
    plan = build_static_split_plan(
        graph_id="graph.test.split",
        node_id="produce",
        contract_bindings={
            "unit_batch": {"unit_kind": "record", "requested_count": 8, "range_start": 1},
            "runtime": {
                "split_policy": {
                    "mode": "static_batch",
                    "batch_size": 2,
                    "child_execution_mode": "parallel",
                    "max_parallel_batches": 3,
                },
                "batch_acceptance_policy": {"mode": "review_then_commit"},
                "merge_policy": {"mode": "wait_all_committed"},
            },
        },
    )

    assert plan is not None
    assert plan.valid is True
    assert plan.metadata["child_execution_mode"] == "parallel"
    assert plan.metadata["max_parallel_batches"] == 3
    assert all(item.steps[0].depends_on == () for item in plan.batch_lifecycle_plans)


