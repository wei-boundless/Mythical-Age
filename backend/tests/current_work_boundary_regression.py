from __future__ import annotations

import json

from harness.entrypoint.current_work_boundary import (
    boundary_receipt_allows_active_work_control,
    build_current_work_boundary_input,
    current_work_boundary_decision_from_payload,
    current_work_boundary_receipt_from_decision,
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
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "no_current_work"
    assert receipt.execution_route == "ordinary_turn"
    assert "active_work_control" not in receipt.allowed_action_types_for_next_packet
    assert "request_task_run" in receipt.allowed_action_types_for_next_packet
    assert boundary_receipt_allows_active_work_control(receipt) is False


def test_steer_without_expected_active_turn_fails_closed_before_model() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer"),
        active_turn_input_policy="steer",
    )

    decision = decide_current_work_boundary(boundary_input)

    assert decision.action == "block"
    assert decision.reason == "expected_active_turn_unavailable"
    assert decision.requires_model_boundary_decision is False


def test_steer_without_active_work_does_not_promote_latest_task() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_turn_check={"accepted": False, "denied_reason": "active_turn_unavailable"},
        current_task_collision_candidate={"task_run_id": "taskrun:latest-waiting", "status": "waiting_executor"},
    )

    decision = decide_current_work_boundary(boundary_input)

    assert decision.action == "block"
    assert decision.reason == "active_turn_steer_not_running"
    assert decision.task_run_id == ""


def test_active_turn_bound_current_work_requires_narrow_boundary_model() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_work_context=_active_work(),
        active_turn_check=_accepted_check(),
    )

    decision = decide_current_work_boundary(boundary_input)

    assert decision.action == "current_work_control_required"
    assert decision.requires_model_boundary_decision is True
    assert decision.task_run_id == "taskrun:active"


def test_steer_boundary_model_cannot_turn_valid_steer_into_independent_turn() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_work_context=_active_work(),
        active_turn_check=_accepted_check(),
    )

    decision = current_work_boundary_decision_from_payload(
        {
            "action": "new_independent_turn_allowed",
            "relation_to_current_work": "independent_turn",
            "reason": "model attempted to leave steer channel",
        },
        boundary_input=boundary_input,
    )
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "block"
    assert decision.reason == "steer_boundary_action_not_allowed:new_independent_turn_allowed"
    assert receipt.execution_route == "terminal"
    assert "active_work_control" not in receipt.allowed_action_types_for_next_packet


def test_boundary_control_receipt_is_the_only_active_work_control_permit() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_work_context=_active_work(),
        active_turn_check=_accepted_check(),
    )

    decision = current_work_boundary_decision_from_payload(
        {
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "appended_instruction": "先检查 CurrentWorkBoundary 的冲突。",
            "reason": "user is adding scope to the current work",
        },
        boundary_input=boundary_input,
    )
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "append_instruction_to_active_work"
    assert receipt.execution_route == "control_only"
    assert receipt.allowed_action_types_for_next_packet == ("active_work_control",)
    assert receipt.active_work_control_payload["resolved_action"] == "append_instruction_to_active_work"
    assert boundary_receipt_allows_active_work_control(receipt) is True


def test_terminal_active_work_is_read_only_for_ordinary_input() -> None:
    active_work = {**_active_work(), "status": "completed"}
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(),
        active_work_context=active_work,
        active_turn_check={**_accepted_check(), "accepted": False, "denied_reason": "bound_task_run_terminal:completed"},
    )

    decision = decide_current_work_boundary(boundary_input)
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "new_independent_turn_allowed"
    assert decision.reason == "active_work_terminal"
    assert "active_work_control" not in receipt.allowed_action_types_for_next_packet


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


def test_compiler_honors_independent_boundary_receipt_as_read_only_context() -> None:
    receipt = {
        "receipt_id": "cwbr:independent",
        "boundary_action": "new_independent_turn_allowed",
        "execution_route": "ordinary_turn",
        "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
        "allowed_action_types_for_next_packet": ["respond", "ask_user", "block", "tool_call"],
        "diagnostics": {"decision": {"reason": "independent user request", "relation_to_current_work": "independent_turn"}},
    }
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compiler-boundary",
        turn_id="turn:compiler-boundary",
        agent_invocation_id="aginvoke:compiler-boundary",
        user_message="解释一下 CurrentWorkBoundary 的设计。",
        history=[],
        active_work_context=_active_work(),
        current_work_boundary_receipt=receipt,
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )
    model_input = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert "active_work_control" not in result.packet.allowed_action_types
    assert "request_task_run" not in result.packet.allowed_action_types
    assert "current_work_boundary_receipt" in model_input
    assert '"read_only_context":true' in model_input


def test_boundary_packet_is_narrow_and_toolless() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_work_context=_active_work(),
        active_turn_check=_accepted_check(),
    )

    result = RuntimeCompiler().compile_current_work_boundary_packet(
        session_id="session:boundary-packet",
        turn_id="turn:boundary-packet",
        boundary_input=boundary_input.to_dict(),
    )
    prompt_text = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert result.packet.available_tools == ()
    assert result.packet.allowed_action_types == ("current_work_boundary_decision",)
    assert "你是当前工作边界裁决员" in prompt_text
    assert "这是 runtime 节点" not in prompt_text
    assert json.loads(result.packet.model_messages[1]["content"])["boundary_input"]["active_work_context"]["task_run_id"] == "taskrun:active"
