from __future__ import annotations

import json

from harness.entrypoint.current_work_boundary import (
    build_current_work_boundary_input,
    current_work_boundary_receipt_allows_active_work_control,
    current_work_boundary_receipt_from_decision,
    decide_current_work_boundary,
)
from harness.loop.admission import admit_model_action
from harness.loop.model_action_protocol import ModelActionRequest
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


def _message_payload_with_title(packet, title: str) -> dict[str, object]:
    marker = title + "\n"
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if content.startswith(marker):
            return json.loads(content.split("\n", 1)[1])
        inner_marker = "\n" + marker
        if inner_marker in content:
            return json.loads(content.split(inner_marker, 1)[1])
        title_marker = f'title="{title}"'
        if title_marker in content and "<context_fragment " in content:
            fragment_body = content.split(">\n", 1)[1].rsplit("\n</context_fragment>", 1)[0]
            payload = json.loads(fragment_body)
            return dict(payload.get("payload") or payload)
    raise AssertionError(f"message title not found: {title}")


def test_no_current_work_allows_ordinary_turn_without_active_work_control() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(),
        control_capabilities={"may_request_task_run": True},
    )

    decision = decide_current_work_boundary(boundary_input)
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "no_current_work"
    assert decision.requires_model_boundary_decision is False
    assert list(receipt.operation_availability.keys()) == ["active_work_control"]
    assert current_work_boundary_receipt_allows_active_work_control(receipt) is False


def test_steer_without_expected_active_turn_becomes_model_visible_state() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer"),
        active_turn_input_policy="steer",
    )

    decision = decide_current_work_boundary(boundary_input)
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "current_work_unavailable"
    assert decision.reason == "expected_active_turn_unavailable"
    assert decision.requires_model_boundary_decision is False
    assert receipt.operation_availability["active_work_control"] is False
    assert receipt.observation_state == "read_only_or_unavailable"


def test_steer_without_active_work_does_not_promote_latest_task() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_turn_check={"accepted": False, "denied_reason": "active_turn_unavailable"},
    )

    decision = decide_current_work_boundary(boundary_input)
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "current_work_unavailable"
    assert decision.reason == "active_turn_steer_not_running"
    assert decision.task_run_id == ""
    assert receipt.operation_availability["active_work_control"] is False


def test_active_turn_bound_current_work_requires_model_decision_after_queue_boundary() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="steer", expected_turn_id="turn:active"),
        active_turn_input_policy="steer",
        expected_active_turn_id="turn:active",
        active_work_context=_active_work(),
        active_turn_check=_accepted_check(),
        control_capabilities={"may_control_active_work": True},
    )

    decision = decide_current_work_boundary(boundary_input)
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "current_work_control_required"
    assert decision.reason == "active_work_boundary_ready"
    assert decision.requires_model_boundary_decision is True
    assert receipt.boundary_decision == "current_work_control_required"
    assert receipt.operation_availability == {"active_work_control": True}
    assert current_work_boundary_receipt_allows_active_work_control(receipt) is True


def test_active_work_control_receipt_requires_current_work_boundary_authority() -> None:
    receipt = {
        "receipt_id": "cwreceipt:shadow",
        "decision_id": "cwbd:shadow",
        "boundary_decision": "current_work_control_required",
        "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
        "operation_availability": {"active_work_control": True},
    }

    assert current_work_boundary_receipt_allows_active_work_control(receipt) is False


def test_running_active_work_keeps_ordinary_input_in_model_decision_path() -> None:
    boundary_input = build_current_work_boundary_input(
        turn_input_facts=_facts(policy="auto", expected_turn_id="turn:active"),
        active_turn_input_policy="auto",
        expected_active_turn_id="turn:active",
        active_work_context=_active_work(),
        active_turn_check=_accepted_check(),
    )

    decision = decide_current_work_boundary(boundary_input)
    receipt = current_work_boundary_receipt_from_decision(decision)

    assert decision.action == "current_work_control_required"
    assert decision.reason == "active_work_boundary_ready"
    assert decision.requires_model_boundary_decision is True
    assert "normalized_active_turn_input_policy" not in decision.diagnostics
    assert receipt.operation_availability["active_work_control"] is True


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


def test_admission_reports_active_work_unavailable_as_operation_observation() -> None:
    action_request = ModelActionRequest(
        request_id="model-action:active-work-unavailable",
        turn_id="turn:active-work-unavailable",
        action_type="active_work_control",
        active_work_control={"action": "continue_active_work"},
    )

    admission = admit_model_action(
        action_request,
        packet_allowed_action_types=("respond", "ask_user", "block", "active_work_control"),
        invocation_kind="single_agent_turn",
        current_work_boundary_receipt={
            "receipt_id": "cwreceipt:unavailable",
            "boundary_decision": "current_work_unavailable",
            "operation_availability": {"active_work_control": False},
        },
    )

    assert admission.decision == "operation_unavailable"
    assert admission.issue_category == "operation_unavailable"
    assert admission.issue_code == "active_work_control_unavailable"
    assert dict(admission.action_issue or {}).get("category") == "operation_unavailable"


def test_compiler_does_not_open_active_work_control_from_context_when_capability_absent() -> None:
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
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": False},
        },
    )

    assert "active_work_control" not in result.packet.allowed_action_types


def test_compiler_does_not_project_active_work_controls_when_receipt_unavailable() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compiler-boundary",
        turn_id="turn:compiler-boundary-unavailable",
        agent_invocation_id="aginvoke:compiler-boundary-unavailable",
        user_message="继续。",
        history=[],
        active_work_context=_active_work(),
        current_work_boundary_receipt={
            "receipt_id": "cwreceipt:unavailable",
            "boundary_decision": "current_work_unavailable",
            "observation_state": "read_only_or_unavailable",
            "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
            "operation_availability": {"active_work_control": False},
            "diagnostics": {
                "decision": {
                    "reason": "expected_active_turn_mismatch",
                    "relation_to_current_work": "stale_or_missing_active_turn",
                }
            },
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    assert "active_work_control" in result.packet.allowed_action_types
    dynamic_payload = _message_payload_with_title(result.packet, "Current Request Context")
    projected_active_work = dict(dynamic_payload["active_work_context"])
    projected_receipt = dict(dynamic_payload["current_work_boundary_receipt"])
    active_control_contract = dict(dict(result.packet.output_contract["control_actions"])["active_work_control"])
    assert projected_active_work["available_controls"] == []
    assert projected_active_work["read_only_context"] is True
    assert projected_active_work["control_availability"] == "current_work_boundary_receipt_active_work_control_unavailable"
    assert projected_receipt["operation_availability"]["active_work_control"] is False
    assert "Current Request Context" in active_control_contract["operation_availability_gate"]


def test_compiler_uses_current_work_boundary_receipt_as_state_observation() -> None:
    receipt = {
        "receipt_id": "cwreceipt:active",
        "decision_id": "cwbd:active",
        "boundary_decision": "current_work_control_required",
        "observation_state": "controllable_current_work",
        "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
        "operation_availability": {"active_work_control": True},
        "authority": "harness.entrypoint.current_work_boundary_receipt",
        "diagnostics": {"decision": {"reason": "active_work_boundary_ready", "relation_to_current_work": "active_turn_bound_current_work"}},
    }
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compiler-boundary",
        turn_id="turn:compiler-boundary",
        agent_invocation_id="aginvoke:compiler-boundary",
        user_message="继续当前任务。",
        history=[],
        active_work_context=_active_work(),
        current_work_boundary_receipt=receipt,
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    assert result.packet.allowed_action_types == ("respond", "ask_user", "block", "request_task_run", "active_work_control")
    assert result.packet.diagnostics["current_work_boundary_receipt"]["receipt_id"] == "cwreceipt:active"
    assert result.packet.diagnostics["current_work_boundary_receipt"]["operation_availability"]["active_work_control"] is True
    dynamic_payload = _message_payload_with_title(result.packet, "Current Request Context")
    projected_active_work = dict(dynamic_payload["active_work_context"])
    assert "continue_active_work" in projected_active_work["available_controls"]
    assert projected_active_work["read_only_context"] is False


def test_compiler_treats_shadow_current_work_receipt_true_as_read_only_state() -> None:
    receipt = {
        "receipt_id": "cwreceipt:shadow",
        "decision_id": "cwbd:shadow",
        "boundary_decision": "current_work_control_required",
        "observation_state": "controllable_current_work",
        "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
        "operation_availability": {"active_work_control": True},
    }

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compiler-boundary",
        turn_id="turn:compiler-boundary-shadow",
        agent_invocation_id="aginvoke:compiler-boundary-shadow",
        user_message="继续当前任务。",
        history=[],
        active_work_context=_active_work(),
        current_work_boundary_receipt=receipt,
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    packet_context = dict(result.packet.diagnostics["runtime_packet_context"])
    dynamic_payload = _message_payload_with_title(result.packet, "Current Request Context")
    projected_active_work = dict(dynamic_payload["active_work_context"])
    projected_receipt = dict(dynamic_payload["current_work_boundary_receipt"])

    assert "active_work_control" in result.packet.allowed_action_types
    assert packet_context["operation_availability"]["active_work_control"] is False
    assert packet_context["operation_availability"]["active_work_control_reason"] == "current_work_receipt_authority_invalid"
    assert projected_receipt["operation_availability"]["active_work_control"] is False
    assert projected_active_work["available_controls"] == []
    assert projected_active_work["read_only_context"] is True


def test_compiler_exposes_prior_work_memory_as_current_request_context() -> None:
    prior_work_memory_context = {
        "authority": "runtime.turn_memory.prior_work_context",
        "source": "previous_interrupted_turn_memory_package",
        "previous_turn_id": "turn:interrupted",
        "turn_run_id": "turnrun:interrupted",
        "status": "terminal",
        "phase": "terminal",
        "interruption": {
            "code": "runtime_process_restarted",
            "reason": "runtime_cell_missing_after_restart",
            "event_id": "rtevt:interrupted:closed",
            "event_offset": 17,
        },
        "current_turn_context": {
            "current_user_message_ref": "msg:user:interrupted",
        },
        "assistant_draft_ref": "draft:interrupted",
        "assistant_draft_sha256": "sha256:visible-prefix",
        "pending_tool_summary": {
            "latest_progress": "已读取目标文件，尚未完成最终判断。",
            "next_recommended_step": "可复用 exact read evidence，但必须重新判断当前用户意图。",
        },
        "pending_commit_summary": {
            "runtime_interruption_code": "runtime_process_restarted",
            "runtime_interruption_reason": "runtime_cell_missing_after_restart",
            "turn_lifecycle_closed_by": "runtime_interruption",
        },
    }
    runtime_assembly = {
        "profile": {"mode": "conversation"},
        "task_environment": {"environment_id": "env.general.workspace"},
        "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
    }

    baseline = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:interrupted-turn",
        turn_id="turn:interrupted-followup",
        agent_invocation_id="aginvoke:interrupted-followup",
        user_message="继续。",
        history=[],
        runtime_assembly=runtime_assembly,
    )
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:interrupted-turn",
        turn_id="turn:interrupted-followup",
        agent_invocation_id="aginvoke:interrupted-followup",
        user_message="继续。",
        history=[],
        session_context={"prior_work_memory_context": prior_work_memory_context},
        runtime_assembly=runtime_assembly,
    )

    assert "resume_task_recovery" not in result.packet.allowed_action_types
    assert "active_work_control" in result.packet.allowed_action_types
    dynamic_payload = _message_payload_with_title(result.packet, "Current Request Context")
    projected = dict(dynamic_payload["prior_work_memory_context"])
    assert "turn_run_id" not in projected
    assert "previous_turn_id" not in projected
    assert projected["state"] == "closed_interrupted_work_memory_package"
    assert projected["read_only_context"] is True
    assert projected["allowed_followup_posture"] == "current_request_with_prior_work_memory"
    assert projected["current_user_request"] == "继续。"
    assert projected["forbidden_action"] == "resume_closed_work"
    assert projected["memory_refs"]["assistant_draft_ref"] == "draft:interrupted"
    assert projected["memory_summaries"]["closure"]["state"] == "interrupted_and_closed"
    assert projected["memory_summaries"]["closure"]["reason"] == "connection_or_process_interruption"
    projected_json = json.dumps(projected, ensure_ascii=False)
    assert "new turn" not in projected_json
    assert "previous turn" not in projected_json
    assert "turn_run" not in projected_json
    assert "turn_lifecycle" not in projected_json
    assert "runtime" not in projected_json.lower()
    assert "prior_work_memory_context" in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]

    def stable_fingerprint(packet) -> list[tuple[str, str, str]]:
        return [
            (str(segment.get("kind") or ""), str(segment.get("cache_role") or ""), str(segment.get("content_hash") or ""))
            for segment in list(packet.segment_plan.get("segments") or [])
            if str(segment.get("cache_role") or "") in {"cacheable_prefix", "session_stable"}
        ]

    assert stable_fingerprint(result.packet) == stable_fingerprint(baseline.packet)
    dynamic_segment = next(
        segment
        for segment in list(result.packet.segment_plan.get("segments") or [])
        if str(segment.get("kind") or "") == "dynamic_projection"
    )
    assert dynamic_segment["cache_role"] == "volatile"
