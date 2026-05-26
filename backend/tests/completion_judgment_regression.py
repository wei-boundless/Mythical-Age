from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.assembler import assemble_runtime_prompt_contract
from runtime.agent_runtime.phases import build_verification_review, judge_completion


SEMANTIC_CONTRACT = {
    "contract_id": "semantic-task:completion:test",
    "task_goal_type": "frontend_app_delivery",
    "deliverables": ["runnable_artifact_refs", "workflow_acceptance", "verification_evidence", "limitations"],
    "required_actions": ["inspect_code", "apply_real_change", "run_browser_verification", "validate_deliverables"]}


def test_completion_judgment_verified_requires_passed_validation() -> None:
    evidence = {
        "packet_id": "evidence:completion:verified",
        "facts": [{"fact_type": "observation", "preview": "write succeeded frontend/src/App.tsx browser opened workflow click"}],
        "limitations": []}
    deliverable = {"passed": True, "missing_deliverables": [], "unsupported_claims": []}
    obligation = {"passed": True, "unsatisfied_obligations": []}

    review = build_verification_review(
        task_run_id="completion-verified",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        deliverable_validation=deliverable,
        obligation_validation=obligation,
    )
    judgment = judge_completion(
        task_run_id="completion-verified",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        verification_review=review,
        terminal_reason="completed",
    ).to_dict()

    assert review.passed is True
    verifier_request = review.diagnostics["readonly_verifier_request"]
    assert verifier_request["authority"] == "runtime.readonly_verifier_request"
    assert verifier_request["diagnostics"]["request_contract_only"] is True
    assert verifier_request["diagnostics"]["model_call_performed"] is False
    assert verifier_request["diagnostics"]["readonly"] is True
    assert "你是一名只读交付验证员" in verifier_request["role_prompt"]
    assert "不修改文件" in verifier_request["role_prompt"]
    assert judgment["status"] == "verified"
    assert judgment["completion_allowed"] is True


def test_readonly_verifier_request_does_not_receive_task_domain_binding() -> None:
    contract = {
        **SEMANTIC_CONTRACT,
        "domain": "development",
        "diagnostics": {
            "task_domain_binding": {
                "binding_id": "taskdomainbind:verify:domain.development",
                "bound_domain_id": "domain.development",
                "default_practices": ["不得声称未发生的浏览器验证"],
            }
        },
    }
    review = build_verification_review(
        task_run_id="completion-domain-binding-hidden",
        semantic_contract=contract,
        evidence_packet={"packet_id": "evidence:domain-hidden", "facts": []},
        deliverable_validation={"passed": False, "missing_deliverables": ["verification_evidence"]},
        obligation_validation={"passed": False, "unsatisfied_obligations": ["run_browser_verification"]},
    )
    verifier_request = review.diagnostics["readonly_verifier_request"]
    serialized = str(verifier_request)

    assert "task_domain_binding" not in serialized
    assert "taskdomainbind:verify:domain.development" not in serialized
    assert "不得声称未发生的浏览器验证" not in serialized
    assert "domain" not in verifier_request["semantic_contract"]


def test_completion_judgment_blocks_missing_deliverables_without_evidence() -> None:
    evidence = {"packet_id": "evidence:completion:blocked", "facts": [], "limitations": ["未收到工具观察。"]}
    deliverable = {"passed": False, "missing_deliverables": ["verification_evidence"], "unsupported_claims": []}
    obligation = {"passed": False, "unsatisfied_obligations": ["run_browser_verification"]}

    review = build_verification_review(
        task_run_id="completion-blocked",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        deliverable_validation=deliverable,
        obligation_validation=obligation,
    )
    judgment = judge_completion(
        task_run_id="completion-blocked",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        verification_review=review,
        terminal_reason="partial_contract_failed",
    ).to_dict()

    assert review.passed is False
    assert judgment["status"] == "blocked"
    assert judgment["completion_allowed"] is False
    assert "verification_evidence" in judgment["missing_deliverables"]
    assert "run_browser_verification" in judgment["unsatisfied_obligations"]


def test_completion_judgment_marks_unsupported_claims_as_contradicted() -> None:
    evidence = {"packet_id": "evidence:completion:contradicted", "facts": []}
    deliverable = {
        "passed": False,
        "missing_deliverables": ["verification_evidence"],
        "unsupported_claims": ["claims_runtime_or_browser_verification_without_evidence"]}
    obligation = {"passed": False, "unsatisfied_obligations": ["run_browser_verification"]}

    review = build_verification_review(
        task_run_id="completion-contradicted",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        deliverable_validation=deliverable,
        obligation_validation=obligation,
    )
    judgment = judge_completion(
        task_run_id="completion-contradicted",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        verification_review=review,
        terminal_reason="completed",
    ).to_dict()

    assert judgment["status"] == "contradicted"
    assert judgment["completion_allowed"] is False
    assert "claims_runtime_or_browser_verification_without_evidence" in judgment["unsupported_claims"]
    assert "unsupported_claim:claims_runtime_or_browser_verification_without_evidence" in review.contradictions


def test_completion_judgment_can_be_partially_verified_with_real_evidence_and_missing_items() -> None:
    evidence = {
        "packet_id": "evidence:completion:partial",
        "facts": [{"fact_type": "observation", "preview": "write succeeded frontend/src/App.tsx"}],
        "limitations": ["未运行浏览器验证。"]}
    deliverable = {"passed": False, "missing_deliverables": ["verification_evidence"], "unsupported_claims": []}
    obligation = {"passed": False, "unsatisfied_obligations": ["run_browser_verification"]}

    review = build_verification_review(
        task_run_id="completion-partial",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        deliverable_validation=deliverable,
        obligation_validation=obligation,
    )
    judgment = judge_completion(
        task_run_id="completion-partial",
        semantic_contract=SEMANTIC_CONTRACT,
        evidence_packet=evidence,
        verification_review=review,
        terminal_reason="completed",
    ).to_dict()

    assert judgment["status"] == "partially_verified"
    assert judgment["completion_allowed"] is False
    assert "未运行浏览器验证。" in judgment["limitations"]


def test_prompt_contract_renders_completion_judgment_section() -> None:
    judgment = {
        "judgment_id": "completion-judgment:prompt",
        "status": "blocked",
        "completion_allowed": False,
        "missing_deliverables": ["verification_evidence"],
        "unsatisfied_obligations": ["run_browser_verification"],
        "unsupported_claims": [],
        "limitations": ["浏览器未运行。"]}
    review = {
        "review_id": "verification-review:prompt",
        "verifier_mode": "readonly_structured_review",
        "passed": False}
    prompt = assemble_runtime_prompt_contract(
        base_dir=ROOT.parent,
        task_id="completion-prompt",
        user_goal="验证前端交付",
        task_contract={
            "user_goal": "验证前端交付",
            "task_requirement_contract": SEMANTIC_CONTRACT,
            "mode_policy": {"interaction_mode": "professional_mode"}},
        task_execution_assembly={"task_mode": "professional_mode", "metadata": {}},
        task_spec={"inputs": {}},
        selected_recipe={
            "recipe_id": "runtime.recipe.professional_task",
            "metadata": {
                "completion_judgment": judgment,
                "verification_review": review}},
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[],
        projection_requirement={},
        operation_requirement={},
        agent_id="agent:0",
        current_turn_context={},
    )

    assert "完成裁决" in prompt["completion_judgment_section"]
    assert "状态=blocked" in prompt["completion_judgment_section"]
    assert "最终回答不能用语气替代证据状态" in prompt["completion_judgment_section"]
    assert prompt["metadata"]["completion_judgment"]["judgment_id"] == "completion-judgment:prompt"
