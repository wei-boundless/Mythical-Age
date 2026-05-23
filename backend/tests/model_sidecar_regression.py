from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intent.model_understanding_invoker import invoke_model_understanding_draft
from intent.task_understanding_frame import build_task_understanding_frame
from runtime.professional_runtime.model_sidecars import (
    invoke_readonly_planner_draft,
    invoke_readonly_verifier_review,
)
from runtime.professional_runtime.plan_coverage import review_plan_coverage


FRONTEND_CONTRACT = {
    "contract_id": "semantic-task:sidecar:frontend",
    "task_goal_type": "frontend_app_delivery",
    "required_actions": [
        "inspect_code",
        "apply_real_change",
        "run_browser_verification",
        "validate_deliverables",
    ],
    "deliverables": [
        "runnable_artifact_refs",
        "workflow_acceptance",
        "verification_evidence",
        "limitations",
    ],
}


def test_model_understanding_sidecar_accepts_valid_json_and_arbitration_preserves_user_forbidden_actions() -> None:
    async def invoker(messages, **_kwargs):
        assert "JSON object" in messages[0]["content"]
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "intent.model_understanding_draft",
                    "draft_id": "modeldraft:sidecar-valid",
                    "user_message": "请只分析，不要改代码",
                    "action_intent": "modify",
                    "execution_mode_hint": "implementation",
                    "forbidden_actions": ["modify_workspace"],
                    "desired_outcomes": ["analysis_report"],
                    "confidence": 0.91,
                },
                ensure_ascii=False,
            )
        )

    draft, diagnostics = asyncio.run(
        invoke_model_understanding_draft(
            invoker=invoker,
            user_message="请只分析，不要改代码",
            deterministic_signals={"forbidden_actions": ["modify_workspace"]},
        )
    )
    frame = build_task_understanding_frame(
        "请只分析，不要改代码",
        model_understanding_draft=draft,
    ).to_dict()

    assert diagnostics["model_call_performed"] is True
    assert diagnostics["model_authority_used"] is True
    assert draft["draft_id"] == "modeldraft:sidecar-valid"
    assert "modify_workspace" in frame["forbidden_actions"]
    assert frame["execution_mode_hint"] == "analysis_only"
    assert frame["understanding_arbitration"]["conflict_set"]


def test_model_understanding_sidecar_rejects_invalid_json_without_model_authority() -> None:
    async def invoker(_messages, **_kwargs):
        return SimpleNamespace(content="不是 JSON")

    draft, diagnostics = asyncio.run(
        invoke_model_understanding_draft(
            invoker=invoker,
            user_message="继续推进",
            deterministic_signals={},
        )
    )

    assert draft == {}
    assert diagnostics["model_call_performed"] is True
    assert diagnostics["model_authority_used"] is False
    assert diagnostics["model_draft_status"] == "absent"
    assert diagnostics["sidecar_status"] == "rejected_invalid_json"


def test_readonly_planner_sidecar_accepts_valid_plan_and_coverage_gate() -> None:
    async def invoker(messages, **_kwargs):
        payload = json.loads(messages[1]["content"])
        request = payload["request"]
        assert request["authority"] == "runtime.readonly_planner_request"
        assert request["diagnostics"]["readonly"] is True
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "runtime.agent_plan_draft",
                    "plan_id": "agent-plan:sidecar-valid",
                    "semantic_contract_ref": FRONTEND_CONTRACT["contract_id"],
                    "task_goal_type": "frontend_app_delivery",
                    "steps": [
                        {
                            "step_id": "inspect",
                            "title": "Inspect",
                            "purpose": "Read project structure",
                            "required_operations": ["op.read_file"],
                            "contract_refs": ["inspect_code"],
                            "evidence_expectations": ["source_tree_observation"],
                        },
                        {
                            "step_id": "change",
                            "title": "Change",
                            "purpose": "Apply real frontend change",
                            "required_operations": ["op.edit_file"],
                            "contract_refs": ["apply_real_change", "runnable_artifact_refs", "workflow_acceptance"],
                            "evidence_expectations": ["file_write", "workflow_check"],
                        },
                        {
                            "step_id": "verify",
                            "title": "Verify",
                            "purpose": "Run browser verification",
                            "required_operations": ["op.shell", "op.browser"],
                            "contract_refs": ["run_browser_verification", "verification_evidence"],
                            "evidence_expectations": ["browser_open", "workflow_check"],
                        },
                        {
                            "step_id": "final",
                            "title": "Final",
                            "purpose": "Report limitations and completion judgment",
                            "required_operations": ["op.model_response"],
                            "contract_refs": ["validate_deliverables", "limitations"],
                            "evidence_expectations": ["completion_judgment"],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        )

    plan, diagnostics = asyncio.run(
        invoke_readonly_planner_draft(
            invoker=invoker,
            task_id="sidecar-plan",
            semantic_contract=FRONTEND_CONTRACT,
        )
    )
    review = review_plan_coverage(
        task_id="sidecar-plan",
        semantic_contract=FRONTEND_CONTRACT,
        agent_plan_draft=plan.to_dict() if plan is not None else {},
    ).to_dict()

    assert plan is not None
    assert plan.source == "model_agent_plan_draft"
    assert diagnostics["model_call_performed"] is True
    assert diagnostics["readonly_planner_request"]["diagnostics"]["model_call_performed"] is True
    assert review["passed"] is True


def test_readonly_planner_sidecar_rejects_schema_mismatch() -> None:
    async def invoker(_messages, **_kwargs):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "runtime.agent_plan_draft",
                    "plan_id": "agent-plan:bad",
                    "semantic_contract_ref": "semantic-task:other",
                    "steps": [{"step_id": "only", "title": "Only", "purpose": "Mismatch"}],
                }
            )
        )

    plan, diagnostics = asyncio.run(
        invoke_readonly_planner_draft(
            invoker=invoker,
            task_id="sidecar-plan-bad",
            semantic_contract=FRONTEND_CONTRACT,
        )
    )

    assert plan is None
    assert diagnostics["model_plan_authority_used"] is False
    assert diagnostics["model_plan_status"] == "rejected_invalid"
    assert "semantic_contract_ref_mismatch" in diagnostics["validation_errors"]


def test_readonly_verifier_sidecar_cannot_override_hard_validation_failures() -> None:
    async def invoker(_messages, **_kwargs):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "runtime.verification_review",
                    "review_id": "verification-review:sidecar",
                    "semantic_contract_ref": FRONTEND_CONTRACT["contract_id"],
                    "passed": True,
                    "blocking_issues": [],
                    "contradictions": [],
                    "limitations": [],
                },
                ensure_ascii=False,
            )
        )

    review, diagnostics = asyncio.run(
        invoke_readonly_verifier_review(
            invoker=invoker,
            task_run_id="sidecar-verifier",
            semantic_contract=FRONTEND_CONTRACT,
            evidence_packet={"packet_id": "evidence:sidecar", "facts": []},
            deliverable_validation={
                "passed": False,
                "missing_deliverables": ["verification_evidence"],
                "unsupported_claims": [],
            },
            obligation_validation={
                "passed": False,
                "unsatisfied_obligations": ["run_browser_verification"],
            },
        )
    )

    assert review is not None
    assert diagnostics["model_verifier_authority_used"] is True
    assert review.passed is False
    assert "missing_deliverable:verification_evidence" in review.blocking_issues
    assert "unsatisfied_obligation:run_browser_verification" in review.blocking_issues
