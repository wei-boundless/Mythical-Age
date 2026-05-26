from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PlanCoverageReview:
    review_id: str
    plan_id: str
    semantic_contract_ref: str
    passed: bool
    gate_status: str = "passed"
    covered_actions: tuple[str, ...] = ()
    missing_actions: tuple[str, ...] = ()
    covered_deliverables: tuple[str, ...] = ()
    missing_deliverables: tuple[str, ...] = ()
    unsupported_skips: tuple[str, ...] = ()
    required_replan_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.plan_coverage_review"

    def __post_init__(self) -> None:
        if self.authority != "runtime.plan_coverage_review":
            raise ValueError("PlanCoverageReview authority must be runtime.plan_coverage_review")
        if not self.review_id:
            raise ValueError("PlanCoverageReview requires review_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["covered_actions"] = list(self.covered_actions)
        payload["missing_actions"] = list(self.missing_actions)
        payload["covered_deliverables"] = list(self.covered_deliverables)
        payload["missing_deliverables"] = list(self.missing_deliverables)
        payload["unsupported_skips"] = list(self.unsupported_skips)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def review_plan_coverage(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    agent_plan_draft: dict[str, Any] | None,
) -> PlanCoverageReview:
    contract = dict(semantic_contract or {})
    plan = dict(agent_plan_draft or {})
    plan_source = str(plan.get("source") or dict(plan.get("diagnostics") or {}).get("source") or "").strip()
    plan_status = str(plan.get("plan_status") or "").strip()
    required_actions = _required_actions_for_review(contract)
    required_deliverables = _required_deliverables_for_review(contract)
    steps = [dict(item) for item in list(plan.get("steps") or []) if isinstance(item, dict)]
    covered_actions = _covered_items(steps, required_actions)
    covered_deliverables = _covered_items(steps, required_deliverables)
    missing_actions = [item for item in required_actions if item not in covered_actions]
    missing_deliverables = [item for item in required_deliverables if item not in covered_deliverables]
    unsupported_skips = [
        str(step.get("step_id") or "")
        for step in steps
        if str(step.get("may_skip_if") or "").strip() and not _skip_is_supported(step)
    ]
    plan_present = bool(steps)
    missing_plan = not plan_present
    passed = bool(plan_present and not missing_actions and not missing_deliverables and not unsupported_skips)
    gate_status = "passed" if passed else "blocked_replan_required"
    replan_reasons = []
    if missing_plan:
        replan_reasons.append("agent_plan_draft_missing_or_empty")
    if missing_actions:
        replan_reasons.append("missing_required_actions")
    if missing_deliverables:
        replan_reasons.append("missing_required_deliverables")
    if unsupported_skips:
        replan_reasons.append("unsupported_skip_conditions")
    return PlanCoverageReview(
        review_id=f"plan-coverage:{task_id or 'runtime'}",
        plan_id=str(plan.get("plan_id") or ""),
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        passed=passed,
        gate_status=gate_status,
        covered_actions=tuple(covered_actions),
        missing_actions=tuple(missing_actions),
        covered_deliverables=tuple(covered_deliverables),
        missing_deliverables=tuple(missing_deliverables),
        unsupported_skips=tuple(item for item in unsupported_skips if item),
        required_replan_reason="" if passed else ",".join(replan_reasons or ["agent_plan_draft_does_not_cover_semantic_contract"]),
        diagnostics={
            "hard_gate": True,
            "execution_must_not_start_when_failed": not passed,
            "plan_present": plan_present,
            "plan_source": plan_source,
            "plan_status": plan_status,
            "required_actions": required_actions,
            "required_deliverables": required_deliverables,
        },
    )


def _required_actions_for_review(contract: dict[str, Any]) -> list[str]:
    actions = [
        str(item).strip()
        for item in list(contract.get("required_actions") or [])
        if str(item).strip()
    ]
    return [
        item
        for item in actions
        if item
        in {
            "read_material",
            "inspect_code",
            "apply_real_change",
            "integrate_asset",
            "run_browser_verification",
            "run_verification",
            "validate_deliverables",
        }
    ]


def _required_deliverables_for_review(contract: dict[str, Any]) -> list[str]:
    deliverables = [
        str(item).strip()
        for item in list(contract.get("deliverables") or [])
        if str(item).strip()
    ]
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    if task_goal_type == "game_vertical_slice_delivery":
        return [
            item
            for item in deliverables
            if item in {"runnable_artifact_refs", "gameplay_acceptance", "visual_asset_refs", "verification_evidence", "final_report"}
        ]
    if task_goal_type == "frontend_app_delivery":
        return [
            item
            for item in deliverables
            if item in {"runnable_artifact_refs", "workflow_acceptance", "verification_evidence", "limitations"}
        ]
    return deliverables


def _covered_items(steps: list[dict[str, Any]], required: list[str]) -> list[str]:
    covered: list[str] = []
    for item in required:
        if any(_step_covers(step, item) for step in steps):
            covered.append(item)
    return covered


def _step_covers(step: dict[str, Any], item: str) -> bool:
    refs = {
        str(value).strip()
        for key in ("contract_refs", "expected_outputs", "evidence_expectations")
        for value in list(step.get(key) or [])
        if str(value).strip()
    }
    step_id = str(step.get("step_id") or "").strip()
    if item in refs or item == step_id:
        return True
    aliases = {
        "runnable_artifact_refs": {"source_changes", "file_write", "apply_real_change"},
        "visual_asset_refs": {"asset_refs", "asset_file", "asset_visible", "integrate_asset"},
        "verification_evidence": {"verification_evidence", "browser_open", "command_run", "test_result"},
        "gameplay_acceptance": {"gameplay_acceptance", "gameplay_check", "implement_core_gameplay"},
        "workflow_acceptance": {"workflow_acceptance", "workflow_check", "implement_frontend_changes"},
        "validate_deliverables": {"completion_judgment", "final_answer"},
        "run_verification": {"run_browser_verification", "verification_evidence", "browser_open", "command_run", "test_result"},
        "final_report": {"final_report", "write_final_report"},
        "limitations": {"limitations", "final_answer"},
    }
    return bool(refs.intersection(aliases.get(item, set())))


def _skip_is_supported(step: dict[str, Any]) -> bool:
    text = str(step.get("may_skip_if") or "").lower()
    return any(token in text for token in ("blocked", "not applicable", "user forbids", "无法", "阻断", "不适用"))
