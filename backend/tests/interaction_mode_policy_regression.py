from __future__ import annotations

from orchestration.interaction_mode_policy import build_runtime_interaction_mode_policy
from request_intent.request_signals import build_request_signals
from task_system.services.assembly_support import build_runtime_task_intent_contract
from tests.support.runtime_stubs import model_turn_context


def _runtime_contract(
    *,
    session_id: str,
    task_id: str,
    user_goal: str,
    action_intent: str,
    work_mode: str,
    interaction_intent: str,
    task_goal_type: str,
    task_domain: str = "workspace",
    current_turn_context: dict[str, object] | None = None,
):
    turn_context = model_turn_context(
        action_intent=action_intent,
        work_mode=work_mode,
        interaction_intent=interaction_intent,
        desired_outcome=user_goal,
        task_goal_type=task_goal_type,
        task_domain=task_domain,
    )
    query_understanding = {
        **build_request_signals(user_goal).to_dict(),
        "model_turn_decision": dict(turn_context["model_turn_decision"]),
        "request_facts": dict(turn_context["request_facts"]),
        "boundary_policy": dict(turn_context["boundary_policy"]),
        "action_permit": dict(turn_context["action_permit"]),
    }
    return build_runtime_task_intent_contract(
        session_id=session_id,
        task_id=task_id,
        user_goal=user_goal,
        query_understanding=query_understanding,
        current_turn_context={
            **turn_context,
            **dict(current_turn_context or {}),
        },
    )


def test_test_report_triage_promotes_to_professional_mode() -> None:
    goal = (
        "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
        "里的失败，列出失败归类、结构性根因和应该补的回归测试。"
    )
    contract = _runtime_contract(
        session_id="session-mode-policy",
        task_id="task-test-report",
        user_goal=goal,
        action_intent="read_context",
        work_mode="read_only_analysis",
        interaction_intent="review",
        task_goal_type="test_report_triage",
        task_domain="testing",
    )

    semantic = contract.task_requirement_contract
    policy = contract.mode_policy

    assert semantic["task_goal_type"] == "test_report_triage"
    assert semantic["professional_profile_id"] == "professional.test_report_triage"
    assert "failure_classification" in semantic["deliverables"]
    assert "structural_root_causes" in semantic["deliverables"]
    assert "regression_test_plan" in semantic["deliverables"]
    assert policy["interaction_mode"] == "professional_mode"
    assert policy["runtime_lane"] == "professional_task"
    assert policy["projection_strength"] == "style_only"


def test_role_mode_is_primary_projection_and_read_only() -> None:
    policy = build_runtime_interaction_mode_policy(
        task_requirement_contract={"task_goal_type": "role_conversation"},
        query_understanding={},
        current_turn_context={"interaction_mode": "role_mode"},
    )

    payload = policy.to_dict()
    assert payload["interaction_mode"] == "role_mode"
    assert payload["runtime_lane"] == "role_interaction"
    assert payload["projection_strength"] == "primary"
    assert payload["tool_policy"]["read_only"] is True
    assert payload["delegation_policy"]["enabled"] is False


def test_standard_mode_is_bounded_tool_task_without_delegation() -> None:
    turn_context = model_turn_context(
        action_intent="read_context",
        work_mode="read_only_analysis",
        interaction_intent="inspect",
        desired_outcome="检查 backend/app.py",
        task_goal_type="bounded_tool_task",
        task_domain="workspace",
    )
    query_understanding = {
        **build_request_signals("检查 backend/app.py").to_dict(),
        "model_turn_decision": dict(turn_context["model_turn_decision"]),
    }
    policy = build_runtime_interaction_mode_policy(
        task_requirement_contract={"task_goal_type": "bounded_tool_task"},
        query_understanding=query_understanding,
        current_turn_context=turn_context,
    )

    payload = policy.to_dict()
    assert payload["interaction_mode"] == "standard_mode"
    assert payload["runtime_lane"] == "standard_task"
    assert payload["projection_strength"] == "companion"
    assert payload["delegation_policy"]["enabled"] is False
    assert payload["verification_policy"]["required"] is True


def test_vibe_coding_alias_is_accepted_for_explicit_mode() -> None:
    policy = build_runtime_interaction_mode_policy(
        task_requirement_contract={"task_goal_type": "code_fix_execution"},
        query_understanding={},
        current_turn_context={"interaction_mode": "vibe_code"},
    ).to_dict()

    assert policy["interaction_mode"] == "vibe_coding"
    assert policy["runtime_lane"] == "vibe_coding_task"
    assert policy["recipe_id"] == "runtime.recipe.vibe_coding"
    assert policy["output_policy"]["answer_boundary"] == "coding_change_evidence"
    assert policy["diagnostics"]["vibe_coding"] is True


def test_regression_test_design_selects_vibe_coding_mode() -> None:
    turn_context = model_turn_context(
        action_intent="read_context",
        work_mode="planning",
        interaction_intent="plan",
        desired_outcome="为这个代码风险补回归测试设计。",
        task_goal_type="regression_test_design",
        task_domain="development",
    )
    policy = build_runtime_interaction_mode_policy(
        task_requirement_contract={"task_goal_type": "regression_test_design"},
        query_understanding={"model_turn_decision": dict(turn_context["model_turn_decision"])},
        current_turn_context=turn_context,
    ).to_dict()

    assert policy["interaction_mode"] == "vibe_coding"
    assert policy["runtime_lane"] == "vibe_coding_task"


def test_frontend_delivery_selects_vibe_coding_mode() -> None:
    turn_context = model_turn_context(
        action_intent="edit_workspace",
        work_mode="implementation",
        interaction_intent="create",
        desired_outcome="重构前端页面并用浏览器验证。",
        task_goal_type="frontend_app_delivery",
        task_domain="development",
    )
    policy = build_runtime_interaction_mode_policy(
        task_requirement_contract={"task_goal_type": "frontend_app_delivery"},
        query_understanding={"model_turn_decision": dict(turn_context["model_turn_decision"])},
        current_turn_context=turn_context,
    ).to_dict()

    assert policy["interaction_mode"] == "vibe_coding"
    assert policy["runtime_lane"] == "vibe_coding_task"
    assert policy["recipe_id"] == "runtime.recipe.vibe_coding"
    assert policy["verification_policy"]["strict"] is True


def test_troubleshooting_with_repair_advice_is_not_code_fix_execution() -> None:
    goal = (
        "请用专业模式排查 backend/tests/fixtures/professional_task_suite/ops_incident_snapshot.json "
        "里的本地服务超时问题。你需要运行一个只读命令确认当前工作目录，再给出原因、修复建议和验证步骤。"
    )
    contract = _runtime_contract(
        session_id="session-troubleshoot-policy",
        task_id="task-troubleshoot",
        user_goal=goal,
        action_intent="run_command",
        work_mode="verification",
        interaction_intent="review",
        task_goal_type="bounded_tool_task",
        current_turn_context={"interaction_mode": "professional_mode"},
    )

    semantic = contract.task_requirement_contract

    assert semantic["task_goal_type"] == "bounded_tool_task"
    assert "apply_real_change" not in semantic["required_actions"]


def test_draft_artifact_delivery_is_not_code_fix_execution() -> None:
    goal = (
        "请用专业模式根据 backend/tests/fixtures/professional_task_suite/node_status_filter_contract.json，"
        "在 sandbox overlay 中完成一个最小端到端功能草案，需要写入一份实施草案文件并说明验证结果。"
    )
    contract = _runtime_contract(
        session_id="session-artifact-policy",
        task_id="task-artifact",
        user_goal=goal,
        action_intent="edit_workspace",
        work_mode="implementation",
        interaction_intent="create",
        task_goal_type="artifact_delivery",
        current_turn_context={"interaction_mode": "professional_mode"},
    )

    semantic = contract.task_requirement_contract

    assert semantic["task_goal_type"] == "artifact_delivery"
    assert "apply_real_change" in semantic["required_actions"]
    assert contract.execution_obligation["required_writes"]


def test_failure_repair_with_pytest_is_obligation_driven_vibe_coding_mode() -> None:
    goal = (
        "追踪 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
        "修复代码，然后运行 pytest 验证。"
    )
    contract = _runtime_contract(
        session_id="session-obligation-policy",
        task_id="task-repair-pytest",
        user_goal=goal,
        action_intent="edit_workspace",
        work_mode="implementation",
        interaction_intent="modify",
        task_goal_type="code_fix_execution",
    )

    semantic = contract.task_requirement_contract
    policy = contract.mode_policy
    obligation = contract.execution_obligation

    assert obligation["required_writes"]
    assert obligation["required_commands"]
    assert obligation["required_verifications"]
    assert "apply_real_change" in semantic["required_actions"]
    assert "run_verification" in semantic["required_actions"]
    assert "modify_code_without_request" not in semantic["forbidden_actions"]
    assert policy["interaction_mode"] == "vibe_coding"
    assert policy["mode_reason"] == "execution_obligation:write_or_verify"
    assert policy["projection_strength"] == "style_only"
    assert policy["runtime_lane"] == "vibe_coding_task"
    assert policy["recipe_id"] == "runtime.recipe.vibe_coding"
    assert policy["verification_policy"]["strict"] is True
    assert "edit_file" in policy["tool_policy"]["allowed_tool_names"]
    assert "terminal" in policy["tool_policy"]["allowed_tool_names"]


def test_analysis_only_goal_does_not_escalate_from_forbidden_write() -> None:
    goal = (
        "先分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
        "不要改代码。"
    )
    contract = _runtime_contract(
        session_id="session-readonly-policy",
        task_id="task-analysis-only",
        user_goal=goal,
        action_intent="read_context",
        work_mode="read_only_analysis",
        interaction_intent="inspect",
        task_goal_type="inspection",
    )

    semantic = contract.task_requirement_contract
    policy = contract.mode_policy

    assert contract.execution_obligation["forbidden_actions"]
    assert not contract.execution_obligation["required_writes"]
    assert "apply_real_change" not in semantic["required_actions"]
    assert policy["interaction_mode"] == "standard_mode"
