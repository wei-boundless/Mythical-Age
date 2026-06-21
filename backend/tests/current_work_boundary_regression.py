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
    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected_active_work = dict(dynamic_payload["active_work_context"])
    projected_receipt = dict(dynamic_payload["current_work_boundary_receipt"])
    active_control_contract = dict(dict(result.packet.output_contract["control_actions"])["active_work_control"])
    assert projected_active_work["available_controls"] == []
    assert projected_active_work["read_only_context"] is True
    assert projected_active_work["control_availability"] == "current_work_boundary_receipt_active_work_control_unavailable"
    assert projected_receipt["operation_availability"]["active_work_control"] is False
    assert "operation_availability.active_work_control" in active_control_contract["operation_availability_gate"]


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
    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
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
    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected_active_work = dict(dynamic_payload["active_work_context"])
    projected_receipt = dict(dynamic_payload["current_work_boundary_receipt"])

    assert "active_work_control" in result.packet.allowed_action_types
    assert packet_context["operation_availability"]["active_work_control"] is False
    assert packet_context["operation_availability"]["active_work_control_reason"] == "current_work_receipt_authority_invalid"
    assert projected_receipt["operation_availability"]["active_work_control"] is False
    assert projected_active_work["available_controls"] == []
    assert projected_active_work["read_only_context"] is True


def test_compiler_exposes_recoverable_work_as_model_decision_context_not_active_control() -> None:
    recoverable_work = {
        "continuation_id": "cont:recoverable:17:0",
        "task_run_id": "taskrun:recoverable",
        "state": "recoverable",
        "resume_allowed": True,
        "resume_strategy": "same_run_resume",
        "task_status": "waiting_executor",
        "latest_progress": "连接已恢复，任务停在可恢复边界。",
        "next_recommended_step": "恢复前核对文件状态。",
        "model_visible_summary": "任务目标：修复断线恢复。",
        "authority": "harness.continuation.record",
    }

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:recoverable-work",
        turn_id="turn:recoverable-work",
        agent_invocation_id="aginvoke:recoverable-work",
        user_message="继续。",
        history=[],
        session_context={"recoverable_work": recoverable_work},
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    assert "resume_recoverable_work" in result.packet.allowed_action_types
    assert "active_work_control" in result.packet.allowed_action_types
    resume_contract = dict(dict(result.packet.output_contract["control_actions"])["resume_recoverable_work"])
    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected = dict(dynamic_payload["recoverable_work"])
    assert projected["continuation_id"] == "cont:recoverable:17:0"
    assert projected["task_run_id"] == "taskrun:recoverable"
    assert projected["read_only_context"] is True
    assert resume_contract["enabled"] is True
    assert "recoverable_work.resume_allowed" in resume_contract["operation_availability_gate"]
    assert "recovery_resume.continuation_id" in resume_contract["required_fields"]
    assert "recoverable_work" in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]


def test_compiler_keeps_unresumable_recoverable_work_read_only_without_resume_action() -> None:
    recoverable_work = {
        "continuation_id": "cont:recoverable-read-only:17:0",
        "task_run_id": "taskrun:recoverable-read-only",
        "state": "recoverable",
        "resume_allowed": False,
        "resume_strategy": "ask_user_confirm",
        "task_status": "waiting_executor",
        "latest_progress": "任务有历史断点，但当前不可直接恢复。",
        "next_recommended_step": "解释当前状态，不要直接续跑。",
        "model_visible_summary": "任务目标：修复断线恢复。",
        "authority": "harness.continuation.record",
    }

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:recoverable-work-read-only",
        turn_id="turn:recoverable-work-read-only",
        agent_invocation_id="aginvoke:recoverable-work-read-only",
        user_message="继续。",
        history=[],
        session_context={"recoverable_work": recoverable_work},
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected = dict(dynamic_payload["recoverable_work"])

    assert "resume_recoverable_work" not in result.packet.allowed_action_types
    assert projected["resume_allowed"] is False
    assert projected["read_only_context"] is True


def test_compiler_exposes_interrupted_turn_work_as_volatile_continuation_context() -> None:
    interrupted_turn_work = {
        "continuation_id": "turncont:interrupted:21:0",
        "session_id": "session:interrupted-turn",
        "turn_run_id": "turnrun:interrupted",
        "turn_id": "turn:interrupted",
        "state": "interrupted_continuation_context",
        "resume_allowed": False,
        "resume_strategy": "continue_next_single_agent_turn",
        "interruption_kind": "tool_budget_exhausted",
        "terminal_status": "blocked",
        "terminal_reason": "single_turn_tool_iteration_limit",
        "latest_progress": "已读取目标文件，尚未完成最终判断。",
        "next_recommended_step": "继续上一轮普通对话工作；优先复用 exact read evidence。",
        "visible_assistant_prefix": "我已经检查了目标文件，下一步",
        "visible_assistant_prefix_sha256": "sha256:visible-prefix",
        "visible_assistant_prefix_utf8_bytes": 42,
        "model_visible_summary": "上一轮普通 turn 在工具预算边界中断。",
        "authority": "harness.continuation.interrupted_turn_record",
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
        session_context={"interrupted_turn_work": interrupted_turn_work},
        runtime_assembly=runtime_assembly,
    )

    assert "resume_recoverable_work" not in result.packet.allowed_action_types
    assert "active_work_control" in result.packet.allowed_action_types
    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected = dict(dynamic_payload["interrupted_turn_work"])
    assert projected["turn_run_id"] == "turnrun:interrupted"
    assert projected["state"] == "interrupted_continuation_context"
    assert projected["read_only_context"] is False
    assert projected["allowed_followup_posture"] == "ordinary_turn_continuation"
    assert projected["current_user_instruction"] == "继续。"
    assert projected["visible_assistant_prefix"]["content"] == "我已经检查了目标文件，下一步"
    assert projected["forbidden_action"] == "resume_recoverable_work"
    assert "interrupted_turn_work" in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]

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


def test_compiler_exposes_agent_contract_feedback_inside_interrupted_turn_work() -> None:
    interrupted_turn_work = {
        "continuation_id": "turncont:contract-feedback:33:0",
        "session_id": "session:contract-feedback",
        "turn_run_id": "turnrun:contract-feedback",
        "turn_id": "turn:contract-feedback",
        "state": "interrupted_continuation_context",
        "resume_allowed": False,
        "resume_strategy": "continue_next_single_agent_turn",
        "interruption_kind": "agent_contract_feedback_required",
        "terminal_status": "failed",
        "terminal_reason": "agent_contract_feedback_required",
        "latest_progress": "上一条输出没有进入会话，也不会展示给用户。",
        "latest_step": "agent_contract_feedback_required",
        "next_recommended_step": "根据合同反馈产出合法 action。",
        "model_visible_summary": "上一轮普通 turn 需要合同反馈修复。",
        "agent_contract_feedback": {
            "signal_kind": "agent_contract_feedback_required",
            "lifecycle": "agent_contract_feedback_required",
            "contract_feedback_state": "execution_contract_feedback_required",
            "phase": "tool_limit_tool_loop",
            "reason": "tool_budget_exhausted",
            "visible_assistant_message_allowed": False,
            "tool_calls_allowed_after_signal": False,
            "agent_closeout_required": True,
            "agent_feedback": "上一条输出没有进入会话，也不会展示给用户；请提交合法 JSON action。",
            "required_action_protocol": {
                "authority": "harness.loop.model_action_request",
                "allowed_action_types": ["respond", "ask_user", "block"],
                "tool_call_allowed": False,
                "structured_action_required": True,
                "visible_user_body_allowed_only_from_agent_action": True,
            },
            "contract_failure": {
                "kind": "agent_output_contract_not_satisfied",
                "closeout_attempts": 2,
                "phase": "tool_limit_tool_loop",
                "reason": "tool_budget_exhausted",
                "protocol_error": {"raw_model_output": "private raw model output"},
                "specific_feedback": [
                    {
                        "category": "protocol_violation",
                        "code": "json_action_required",
                        "situation_feedback": "上一条输出无法可靠归类。",
                        "repair_instruction": "只输出一个 JSON action。",
                        "expected_next_action": "选择 respond、ask_user 或 block。",
                    }
                ],
            },
            "observed_facts": {"successful_tool_observation_count": 1},
            "structured_signal": {
                "code": "single_agent_turn_agent_contract_feedback_required",
                "message": "请提交合法 JSON action。",
                "retryable": True,
            },
        },
        "authority": "harness.continuation.interrupted_turn_record",
    }
    runtime_assembly = {
        "profile": {"mode": "conversation"},
        "task_environment": {"environment_id": "env.general.workspace"},
        "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
    }

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:contract-feedback",
        turn_id="turn:contract-feedback-followup",
        agent_invocation_id="aginvoke:contract-feedback-followup",
        user_message="继续。",
        history=[],
        session_context={"interrupted_turn_work": interrupted_turn_work},
        runtime_assembly=runtime_assembly,
    )

    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected = dict(dynamic_payload["interrupted_turn_work"])
    feedback = dict(projected["agent_contract_feedback"])
    protocol = dict(feedback["required_action_protocol"])
    failure = dict(feedback["contract_failure"])

    assert projected["interruption_kind"] == "agent_contract_feedback_required"
    assert feedback["signal_kind"] == "agent_contract_feedback_required"
    assert protocol["authority"] == "harness.loop.model_action_request"
    assert protocol["allowed_action_types"] == ["respond", "ask_user", "block"]
    assert failure["specific_feedback"][0]["repair_instruction"] == "只输出一个 JSON action。"
    assert feedback["observed_facts"]["successful_tool_observation_count"] == 1
    assert "raw_model_output" not in json.dumps(feedback, ensure_ascii=False)
