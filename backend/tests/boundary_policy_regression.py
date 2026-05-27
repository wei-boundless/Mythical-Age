from __future__ import annotations

from agent_runtime.understanding.action_permit import build_action_permit
from agent_runtime.understanding.boundary_policy import build_boundary_policy


def test_boundary_policy_scopes_source_readonly_without_blocking_sandbox_report_write() -> None:
    message = (
        "请在 sandbox 中读取 .materials/source_projects/source_01/README.md，"
        "不要修改源项目，然后写入 output/vibe-code-smoke/report.md。"
    )
    boundary = build_boundary_policy(
        user_message=message,
        current_turn_context={
            "resource_contract": {
                "required_write_files": ["output/vibe-code-smoke/report.md"],
            }
        },
    ).to_dict()
    permit = build_action_permit(
        model_turn_decision={
            "decision_id": "model-turn-decision:test",
            "action_intent": "edit_workspace",
        },
        boundary_policy=boundary,
    ).to_dict()

    assert boundary["write_allowed"] is True
    assert not {"edit_workspace", "write_file", "modify_code"}.intersection(boundary["forbidden_actions"])
    assert boundary["diagnostics"]["natural_language_marker_policy"] == "disabled_for_hard_permissions"
    assert boundary["diagnostics"]["hard_boundary"] is False
    assert boundary["diagnostics"]["authority_boundary"] == "operation_gate_and_sandbox_policy"
    assert permit["allowed"] is True
    assert permit["denied_reasons"] == []


def test_boundary_policy_natural_language_no_file_write_does_not_create_hard_permission_block() -> None:
    boundary = build_boundary_policy(
        user_message="只分析 backend/app.py，不要写任何文件。",
    ).to_dict()
    permit = build_action_permit(
        model_turn_decision={
            "decision_id": "model-turn-decision:test",
            "action_intent": "edit_workspace",
        },
        boundary_policy=boundary,
    ).to_dict()

    assert boundary["write_allowed"] is True
    assert boundary["forbidden_actions"] == []
    assert boundary["diagnostics"]["natural_language_markers_are_intent_signals"] is False
    assert boundary["diagnostics"]["natural_language_marker_policy"] == "disabled_for_hard_permissions"
    assert permit["allowed"] is True
    assert permit["denied_reasons"] == []


def test_action_permit_honors_model_turn_structured_write_forbid() -> None:
    boundary = build_boundary_policy(
        user_message="只分析 backend/app.py，不要写任何文件。",
        current_turn_context={
            "model_turn_decision": {
                "forbidden_actions": ["modify_code", "write_file", "edit_file"],
            }
        },
    ).to_dict()
    permit = build_action_permit(
        model_turn_decision={
            "decision_id": "model-turn-decision:test",
            "action_intent": "edit_workspace",
            "forbidden_actions": ["modify_code", "write_file", "edit_file"],
        },
        boundary_policy=boundary,
    ).to_dict()

    assert boundary["write_allowed"] is False
    assert "write_file" in boundary["forbidden_actions"]
    assert permit["allowed"] is False
    assert permit["denied_reasons"] == ["write_forbidden_by_model_turn_decision"]


