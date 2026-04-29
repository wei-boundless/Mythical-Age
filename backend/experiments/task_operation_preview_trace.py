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
            "execution_graph_empty",
            "resource_section_dynamic",
        ],
    }


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
