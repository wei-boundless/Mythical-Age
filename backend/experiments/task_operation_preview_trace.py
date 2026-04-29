from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tasks import build_task_runtime_contract_preview


@dataclass(frozen=True, slots=True)
class TaskOperationPreviewCase:
    scenario_id: str
    snapshot_name: str
    session_id: str
    task_id: str
    user_goal: str


ACCEPTANCE_PREVIEW_CASES: tuple[TaskOperationPreviewCase, ...] = (
    TaskOperationPreviewCase(
        scenario_id="search_official_material",
        snapshot_name="search_official_material.preview.json",
        session_id="preview-search-official",
        task_id="task-preview-search-official",
        user_goal="帮我联网搜索 Claude Code subagent 官方资料。",
    ),
    TaskOperationPreviewCase(
        scenario_id="local_read_and_summarize",
        snapshot_name="local_read_and_summarize.preview.json",
        session_id="preview-local-read",
        task_id="task-preview-local-read",
        user_goal="读取 docs/系统规划/操作系统与任务系统/03-任务系统与操作系统接线方案-20260429.md 并总结。",
    ),
    TaskOperationPreviewCase(
        scenario_id="modify_then_review",
        snapshot_name="modify_then_review.preview.json",
        session_id="preview-modify-review",
        task_id="task-preview-modify-review",
        user_goal="修改任务系统文档，然后检查有没有前后矛盾。",
    ),
)


def build_task_operation_preview_snapshots() -> dict[str, Any]:
    snapshots = [build_task_operation_preview_snapshot(item) for item in ACCEPTANCE_PREVIEW_CASES]
    return {
        "status": "preview_only",
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
        "invariants": {
            "preview_only": True,
            "resource_policy_adopted": False,
            "runtime_directive_enabled": False,
            "runtime_executable": False,
            "execution_nodes": 0,
            "commit_allowed": False,
        },
    }


def build_task_operation_preview_snapshot(case: TaskOperationPreviewCase) -> dict[str, Any]:
    preview = build_task_runtime_contract_preview(
        session_id=case.session_id,
        task_id=case.task_id,
        user_goal=case.user_goal,
        source="acceptance_preview",
    )
    snapshot = {
        "snapshot_name": case.snapshot_name,
        "scenario_id": case.scenario_id,
        "status": "preview_only",
        "task_contract": preview["task_contract"],
        "operation_requirement": preview["operation_requirement"],
        "resource_policy_preview": preview["resource_policy"],
        "resource_runtime_views": preview["resource_runtime_views"],
        "task_prompt_contract": preview["task_prompt_contract"],
        "soul_runtime_view": preview["soul_runtime_view"],
        "prompt_manifest_preview": preview["prompt_manifest_preview"],
        "understanding_candidate_preview": preview["understanding_candidate_preview"],
        "candidate_set_preview": preview["candidate_set_preview"],
        "orchestration_plan_preview": preview["orchestration_plan_preview"],
        "plan_validation": preview["plan_validation"],
        "execution_graph_preview": preview["execution_graph_preview"],
        "adoption_candidate_preview": preview["adoption_candidate_preview"],
        "adoption_block": preview["adoption_block"],
        "runtime_directive_candidates": preview["runtime_directive_candidates"],
        "runtime_directive_block": preview["runtime_directive_block"],
        "operation_gate_preflight": preview["operation_gate_preflight"],
        "directive_only_executor_preview": preview["directive_only_executor_preview"],
        "commit_gate_preview": preview["commit_gate_preview"],
        "control_kernel_diagnostics": preview["control_kernel_diagnostics"],
        "control_kernel_result": preview["control_kernel_result"],
    }
    snapshot["validation"] = _validate_snapshot(snapshot)
    return snapshot


def _validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    resource_policy = _dict(snapshot.get("resource_policy_preview"))
    prompt_contract = _dict(snapshot.get("task_prompt_contract"))
    prompt_metadata = _dict(prompt_contract.get("metadata"))
    control_result = _dict(snapshot.get("control_kernel_result"))
    execution_graph = _dict(control_result.get("execution_graph"))
    plan = _dict(snapshot.get("orchestration_plan_preview"))
    plan_validation = _dict(snapshot.get("plan_validation"))
    graph_preview = _dict(snapshot.get("execution_graph_preview"))
    adoption = _dict(snapshot.get("adoption_candidate_preview"))
    adoption_block = _dict(snapshot.get("adoption_block"))
    directive_candidates = list(snapshot.get("runtime_directive_candidates") or [])
    runtime_directive_block = _dict(snapshot.get("runtime_directive_block"))
    operation_gate_preflight = _dict(snapshot.get("operation_gate_preflight"))
    directive_only_executor = _dict(snapshot.get("directive_only_executor_preview"))
    commit_gate = _dict(snapshot.get("commit_gate_preview"))
    commit_candidates = list(commit_gate.get("commit_candidates") or [])
    understanding_candidates = list(snapshot.get("understanding_candidate_preview") or [])
    diagnostics = _dict(snapshot.get("control_kernel_diagnostics"))
    manifest = _dict(snapshot.get("prompt_manifest_preview"))
    manifest_sections = {
        str(item.get("section_id") or ""): item
        for item in list(manifest.get("sections") or [])
        if isinstance(item, dict)
    }
    failures: list[str] = []

    _require(resource_policy.get("preview_only") is True, "resource policy must be preview_only", failures)
    _require(resource_policy.get("adopted") is False, "resource policy must not be adopted", failures)
    _require(resource_policy.get("runtime_executable") is False, "resource policy must not be executable", failures)
    _require(prompt_metadata.get("preview_only") is True, "prompt contract must be preview_only", failures)
    _require(
        prompt_metadata.get("runtime_directive_enabled") is False,
        "prompt contract must not enable runtime directive",
        failures,
    )
    _require(control_result.get("status") == "blocked", "control kernel must stay blocked", failures)
    _require(control_result.get("directives") == [], "control kernel must not emit directives", failures)
    _require(execution_graph.get("nodes") == [], "execution graph must not contain execution nodes", failures)
    _require(plan.get("topology_mode") == "single_agent", "orchestration plan must be single_agent", failures)
    _require(plan.get("runtime_executable") is False, "orchestration plan must not be executable", failures)
    _require(plan_validation.get("status") == "blocked", "plan validation must stay blocked", failures)
    _require(
        plan_validation.get("runtime_executable") is False,
        "plan validation must not be executable",
        failures,
    )
    _require(
        graph_preview.get("runtime_executable") is False,
        "execution graph preview must not be executable",
        failures,
    )
    _require(adoption.get("status") == "blocked", "adoption candidate must stay blocked", failures)
    _require(adoption_block.get("blocked") is True, "adoption block must stay blocked", failures)
    _require(
        adoption.get("can_adopt_plan") is False,
        "adoption candidate must not adopt plan",
        failures,
    )
    _require(
        all(_dict(item).get("authority") == "candidate_only" for item in directive_candidates),
        "runtime directive candidates must remain candidate_only",
        failures,
    )
    _require(
        all(_dict(item).get("runtime_executable") is False for item in directive_candidates),
        "runtime directive candidates must not be executable",
        failures,
    )
    _require(
        runtime_directive_block.get("blocked") is True,
        "runtime directive build must stay blocked",
        failures,
    )
    _require(
        operation_gate_preflight.get("operation_gate_passed") is False,
        "operation gate preflight must not pass",
        failures,
    )
    _require(
        directive_only_executor.get("accepted_input_type") == "RuntimeDirective",
        "executor preflight must accept only RuntimeDirective",
        failures,
    )
    _require(
        directive_only_executor.get("will_dispatch") is False,
        "executor preflight must not dispatch",
        failures,
    )
    _require(commit_gate.get("status") == "blocked", "commit gate must stay blocked", failures)
    _require(commit_gate.get("commit_allowed") is False, "commit gate must not allow writeback", failures)
    _require(
        all(_dict(item).get("allowed") is False for item in commit_candidates),
        "commit candidates must stay denied",
        failures,
    )
    _require(
        all(_dict(item).get("authority") == "candidate_only" for item in understanding_candidates),
        "understanding candidates must remain candidate_only",
        failures,
    )
    _require(diagnostics.get("fail_closed") is True, "control kernel must fail closed", failures)
    _require(diagnostics.get("preview_only") is True, "control kernel diagnostics must be preview_only", failures)
    _require(
        diagnostics.get("runtime_directive_enabled") is False,
        "control kernel must not enable runtime directive",
        failures,
    )
    _require(
        diagnostics.get("runtime_executable") is False,
        "control kernel must not be runtime executable",
        failures,
    )
    resource_section = _dict(manifest_sections.get("resource_section"))
    _require(resource_section.get("cache_scope") == "dynamic", "resource section must be dynamic", failures)
    _require(
        resource_section.get("owner_layer") == "resource_policy",
        "resource section must be owned by resource policy",
        failures,
    )

    return {
        "passed": not failures,
        "failed_checks": failures,
        "checked_invariants": [
            "preview_only",
            "resource_policy_adopted_false",
            "runtime_directive_disabled",
            "runtime_executable_false",
            "orchestration_plan_single_agent",
            "plan_validation_blocked",
            "execution_graph_preview_not_executable",
            "adoption_candidate_blocked",
            "adoption_block_blocked",
            "runtime_directive_candidates_candidate_only",
            "runtime_directive_block_blocked",
            "operation_gate_preflight_blocked",
            "directive_only_executor_blocked",
            "commit_gate_blocked",
            "understanding_candidates_candidate_only",
            "execution_graph_empty",
            "resource_section_dynamic",
        ],
    }


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
