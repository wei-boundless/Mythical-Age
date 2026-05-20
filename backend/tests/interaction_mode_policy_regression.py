from __future__ import annotations

from orchestration.interaction_mode_policy import build_runtime_interaction_mode_policy
from tasks.assembly_support import build_runtime_task_intent_contract


def test_test_report_triage_promotes_to_professional_mode() -> None:
    contract = build_runtime_task_intent_contract(
        session_id="session-mode-policy",
        task_id="task-test-report",
        user_goal=(
            "分析 backend/tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
            "里的失败，列出失败归类、结构性根因和应该补的回归测试。"
        ),
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={},
    )

    semantic = contract.semantic_task_contract
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
        semantic_task_contract={"task_goal_type": "role_conversation"},
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
    policy = build_runtime_interaction_mode_policy(
        semantic_task_contract={"task_goal_type": "bounded_tool_task"},
        query_understanding={"route": "workspace_read"},
        current_turn_context={},
    )

    payload = policy.to_dict()
    assert payload["interaction_mode"] == "standard_mode"
    assert payload["runtime_lane"] == "standard_task"
    assert payload["projection_strength"] == "companion"
    assert payload["delegation_policy"]["enabled"] is False
    assert payload["verification_policy"]["required"] is True


def test_troubleshooting_with_repair_advice_is_not_code_fix_execution() -> None:
    contract = build_runtime_task_intent_contract(
        session_id="session-troubleshoot-policy",
        task_id="task-troubleshoot",
        user_goal=(
            "请用专业模式排查 backend/tests/fixtures/professional_task_suite/ops_incident_snapshot.json "
            "里的本地服务超时问题。你需要运行一个只读命令确认当前工作目录，再给出原因、修复建议和验证步骤。"
        ),
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={"interaction_mode": "professional_mode"},
    )

    semantic = contract.semantic_task_contract

    assert semantic["task_goal_type"] == "bounded_tool_task"
    assert "apply_real_change" not in semantic["required_actions"]


def test_draft_artifact_delivery_is_not_code_fix_execution() -> None:
    contract = build_runtime_task_intent_contract(
        session_id="session-artifact-policy",
        task_id="task-artifact",
        user_goal=(
            "请用专业模式根据 backend/tests/fixtures/professional_task_suite/node_status_filter_contract.json，"
            "在 sandbox overlay 中完成一个最小端到端功能草案，需要写入一份实施草案文件并说明验证结果。"
        ),
        query_understanding={"route": "workspace_read", "source_kind": "workspace"},
        current_turn_context={"interaction_mode": "professional_mode"},
    )

    semantic = contract.semantic_task_contract

    assert semantic["task_goal_type"] == "artifact_delivery"
    assert "apply_real_change" not in semantic["required_actions"]
