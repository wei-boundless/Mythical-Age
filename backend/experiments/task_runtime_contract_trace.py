from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tasks import build_task_runtime_contract


@dataclass(frozen=True, slots=True)
class TaskRuntimeContractCase:
    scenario_id: str
    snapshot_name: str
    session_id: str
    task_id: str
    user_goal: str


ACCEPTANCE_RUNTIME_CASES: tuple[TaskRuntimeContractCase, ...] = (
    TaskRuntimeContractCase(
        scenario_id="search_official_material",
        snapshot_name="search_official_material.runtime.json",
        session_id="runtime-search-official",
        task_id="task-runtime-search-official",
        user_goal="帮我联网搜索 Claude Code subagent 官方资料。",
    ),
    TaskRuntimeContractCase(
        scenario_id="local_read_and_summarize",
        snapshot_name="local_read_and_summarize.runtime.json",
        session_id="runtime-local-read",
        task_id="task-runtime-local-read",
        user_goal="读取 docs/系统规划/操作系统与任务系统/03-任务系统与操作系统接线方案-20260429.md 并总结。",
    ),
    TaskRuntimeContractCase(
        scenario_id="modify_then_review",
        snapshot_name="modify_then_review.runtime.json",
        session_id="runtime-modify-review",
        task_id="task-runtime-modify-review",
        user_goal="修改任务系统文档，然后检查有没有前后矛盾。",
    ),
)


def build_task_runtime_contract_snapshots() -> dict[str, Any]:
    snapshots = [build_task_runtime_contract_snapshot(item) for item in ACCEPTANCE_RUNTIME_CASES]
    return {
        "status": "runtime",
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
        "invariants": {
            "runtime_executable": True,
            "resource_sections_hidden": True,
            "prompt_uses_authorized_visible_surface_only": True,
        },
    }


def build_task_runtime_contract_snapshot(case: TaskRuntimeContractCase) -> dict[str, Any]:
    runtime = build_task_runtime_contract(
        session_id=case.session_id,
        task_id=case.task_id,
        user_goal=case.user_goal,
        source="acceptance_runtime",
    )
    snapshot = {
        "snapshot_name": case.snapshot_name,
        "scenario_id": case.scenario_id,
        "status": runtime["status"],
        "task_contract": runtime["task_contract"],
        "operation_requirement": runtime["operation_requirement"],
        "task_prompt_contract": runtime["task_prompt_contract"],
        "soul_runtime_view": runtime["soul_runtime_view"],
        "prompt_manifest": runtime["prompt_manifest"],
        "understanding_candidates": runtime["understanding_candidates"],
        "runtime_executable": runtime["runtime_executable"],
    }
    snapshot["validation"] = _validate_snapshot(snapshot)
    return snapshot


def _validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    prompt_contract = _dict(snapshot.get("task_prompt_contract"))
    prompt_metadata = _dict(prompt_contract.get("metadata"))
    manifest = _dict(snapshot.get("prompt_manifest"))
    manifest_sections = {
        str(item.get("section_id") or ""): item
        for item in list(manifest.get("sections") or [])
        if isinstance(item, dict)
    }
    runtime_view = _dict(snapshot.get("soul_runtime_view"))
    runtime_sections = {
        str(item.get("section_id") or ""): item
        for item in list(runtime_view.get("sections") or [])
        if isinstance(item, dict)
    }
    understanding_candidates = list(snapshot.get("understanding_candidates") or [])
    failures: list[str] = []

    _require(snapshot.get("status") == "runtime", "snapshot must be runtime", failures)
    _require(snapshot.get("runtime_executable") is True, "runtime contract must be executable", failures)
    _require(prompt_metadata.get("runtime_directive_enabled") is True, "runtime directive must be enabled", failures)
    _require(prompt_metadata.get("runtime_executable") is True, "prompt contract must be runtime executable", failures)
    _require("resource_section" not in manifest_sections, "resource section must not enter prompt manifest", failures)
    _require("guardrail_section" not in manifest_sections, "guardrail section must not enter prompt manifest", failures)
    _require("resource_section" not in runtime_sections, "resource section must not enter runtime view", failures)
    _require("guardrail_section" not in runtime_sections, "guardrail section must not enter runtime view", failures)
    _require(
        all(_dict(item).get("authority") == "candidate_only" for item in understanding_candidates),
        "understanding candidates must remain candidates",
        failures,
    )

    return {
        "passed": not failures,
        "failed_checks": failures,
        "checked_invariants": [
            "runtime_status",
            "runtime_executable",
            "resource_sections_hidden",
            "understanding_candidates_candidate_only",
        ],
    }


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
