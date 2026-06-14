from __future__ import annotations

from harness.entrypoint.current_work_boundary import (
    build_current_work_boundary_input,
    current_work_permit_allows_active_work_control,
    current_work_permit_from_decision,
    decide_current_work_boundary,
)
from harness.runtime import RuntimeCompiler


def _facts(*, policy: str = "auto", expected_turn_id: str = "") -> dict[str, str]:
    return {
        "session_id": "session:current-work-boundary",
        "turn_id": "turn:current-work-boundary",
        "user_message": "继续处理当前任务。",
        "active_turn_input_policy": policy,
        "expected_active_turn_id": expected_turn_id,
    }


def _active_work() -> dict[str, object]:
    return {
        "session_id": "session:current-work-boundary",
        "active_work_id": "turn:active",
        "task_run_id": "taskrun:active",
        "status": "running",
        "control_state": "running",
        "running": True,
        "resumable": True,
        "authority": "harness.runtime.active_turn_context",
    }


def _accepted_check() -> dict[str, object]:
    return {
        "accepted": True,
        "expected_turn_id": "turn:active",
        "actual_turn_id": "turn:active",
        "expected_task_run_id": "taskrun:active",
        "actual_task_run_id": "taskrun:active",
        "authority": "harness.runtime.active_turn.compare_and_update_current_turn",
    }


def test_no_current_work_allows_ordinary_turn_without_active_work_control() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(),
        control_capabilities={"may_request_task_run": True},
    )

    decision = decide_current_work_boundary(boundary_input)
    permit = current_work_permit_from_decision(decision)

    assert decision.action == "no_current_work"
    assert decision.requires_model_boundary_decision is False
    assert permit.execution_route == "ordinary_turn"
    assert "active_work_control" not in permit.allowed_action_types_for_next_packet
    assert "request_task_run" in permit.allowed_action_types_for_next_packet
    assert current_work_permit_allows_active_work_control(permit) is False


def test_steer_without_expected_active_turn_fails_closed_before_model() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer"),
        active_turn_input_policy="steer",
    )

    decision = decide_current_work_boundary(boundary_input)
    permit = current_work_permit_from_decision(decision)

    assert decision.action == "block"
    assert decision.reason == "expected_active_turn_unavailable"
    assert decision.requires_model_boundary_decision is False
    assert permit.execution_route == "terminal"
    assert permit.decision == "deny"


def test_steer_without_active_work_does_not_promote_latest_task() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_turn_check={"accepted": False, "denied_reason": "active_turn_unavailable"},
        current_task_collision_candidate={"task_run_id": "taskrun:latest-waiting", "status": "waiting_executor"},
    )

    decision = decide_current_work_boundary(boundary_input)
    permit = current_work_permit_from_decision(decision)

    assert decision.action == "block"
    assert decision.reason == "active_turn_steer_not_running"
    assert decision.task_run_id == ""
    assert permit.allows["active_work_control"] is False


def test_active_turn_bound_current_work_issues_control_permit_without_boundary_model() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_work_context=_active_work(),
        active_turn_check=_accepted_check(),
    )

    decision = decide_current_work_boundary(boundary_input)
    permit = current_work_permit_from_decision(decision)

    assert decision.action == "current_work_control_required"
    assert decision.reason == "current_work_permit_ready"
    assert decision.requires_model_boundary_decision is False
    assert permit.boundary_decision == "current_work_control_required"
    assert permit.execution_route == "ordinary_turn"
    assert permit.allowed_action_types_for_next_packet == ("active_work_control", "ask_user", "block")
    assert current_work_permit_allows_active_work_control(permit) is True


def test_terminal_active_work_is_read_only_for_ordinary_input() -> None:
    active_work = {**_active_work(), "status": "completed"}
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(),
        active_work_context=active_work,
        active_turn_check={**_accepted_check(), "accepted": False, "denied_reason": "bound_task_run_terminal:completed"},
    )

    decision = decide_current_work_boundary(boundary_input)
    permit = current_work_permit_from_decision(decision)

    assert decision.action == "new_independent_turn_allowed"
    assert decision.reason == "active_work_terminal"
    assert "active_work_control" not in permit.allowed_action_types_for_next_packet


def test_compiler_does_not_open_active_work_control_from_context_alone() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compiler-boundary",
        turn_id="turn:compiler-boundary",
        agent_invocation_id="aginvoke:compiler-boundary",
        user_message="继续。",
        history=[],
        active_work_context=_active_work(),
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    assert "active_work_control" not in result.packet.allowed_action_types


def test_compiler_honors_current_work_permit_as_the_only_control_authority() -> None:
    permit = {
        "permit_id": "cwpermit:active",
        "boundary_decision": "current_work_control_required",
        "execution_route": "ordinary_turn",
        "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
        "allowed_action_types_for_next_packet": ["active_work_control", "ask_user", "block"],
        "allows": {"active_work_control": True, "request_task_run": False, "tool_call": False},
        "diagnostics": {"decision": {"reason": "current_work_permit_ready", "relation_to_current_work": "active_turn_bound_current_work"}},
    }
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compiler-boundary",
        turn_id="turn:compiler-boundary",
        agent_invocation_id="aginvoke:compiler-boundary",
        user_message="继续当前任务。",
        history=[],
        active_work_context=_active_work(),
        current_work_permit=permit,
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )
    model_input = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert result.packet.allowed_action_types == ("active_work_control", "ask_user", "block")
    assert "current_work_permit" in model_input
    assert "current_work_boundary_receipt" not in model_input
    assert '"read_only_context":false' in model_input
