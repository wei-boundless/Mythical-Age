from __future__ import annotations

import json

from runtime.shared.models import TaskRun

from harness.continuation import (
    build_recovery_packet,
    build_recovery_boundary_input,
    decide_recovery_boundary,
    recovery_boundary_receipt_from_decision,
    select_session_continuation,
)
from harness.loop.model_action_protocol import (
    model_action_request_from_payload,
    task_execution_action_request_from_payload,
)
from harness.runtime import RuntimeCompiler
from harness.runtime.request_facts import build_turn_input_facts


class _StateIndex:
    def __init__(self, task_runs, turn_runs=None):
        self._task_runs = list(task_runs)
        self._turn_runs = list(turn_runs or [])

    def list_session_task_runs(self, session_id: str):
        return [item for item in self._task_runs if item.session_id == session_id]

    def list_session_turn_runs(self, session_id: str):
        return [item for item in self._turn_runs if item.session_id == session_id]


class _RuntimeObjects:
    def get_object(self, _ref: str):
        return {}


class _Host:
    def __init__(self, task_runs, turn_runs=None):
        self.state_index = _StateIndex(task_runs, turn_runs=turn_runs)
        self.runtime_objects = _RuntimeObjects()


def _recoverable_task() -> TaskRun:
    return TaskRun(
        task_run_id="taskrun:session-continuation:3:abc",
        session_id="session-continuation",
        task_id="task:continuation",
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        latest_event_offset=17,
        updated_at=100.0,
        diagnostics={
            "executor_status": "waiting_executor",
            "wait_reason": "task_executor_interrupted_by_runtime_restart",
            "recoverable_error": {
                "error_code": "task_executor_interrupted_by_runtime_restart",
                "retryable": True,
            },
            "recovery_action": "rerun_task_executor",
            "latest_step": "task_executor_recovered_after_runtime_start",
            "latest_public_progress_note": "连接已恢复，当前工作已恢复为可继续状态。",
            "goal": "修复页面交互问题",
        },
    )


def _fresh_context_recovery_status() -> dict[str, object]:
    return {
        "available": True,
        "present": True,
        "fresh": True,
        "source": "test.context_recovery_package",
        "authority": "harness.continuation.context_recovery_status",
    }


def _bare_recovery_action_task() -> TaskRun:
    return TaskRun(
        task_run_id="taskrun:session-continuation:bare-recovery",
        session_id="session-continuation",
        task_id="task:continuation:bare-recovery",
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        latest_event_offset=9,
        updated_at=90.0,
        diagnostics={
            "executor_status": "waiting_executor",
            "recovery_action": "resume_task_run",
            "latest_public_progress_note": "旧诊断残留不应授权恢复。",
        },
    )


def test_selector_builds_recoverable_continuation_record_from_waiting_executor() -> None:
    selection = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    )

    assert selection.record is not None
    assert selection.record.state == "recoverable"
    assert selection.record.resume_allowed is True
    assert selection.record.task_run_id == "taskrun:session-continuation:3:abc"
    assert selection.record.recovery_cause == "runtime_restart"
    assert selection.record.latest_progress
    assert "task_run_state_view" not in selection.record.diagnostics


def test_selector_does_not_promote_bare_recovery_action_to_continuation_record() -> None:
    selection = select_session_continuation(
        _Host([_bare_recovery_action_task()]),
        session_id="session-continuation",
    )

    assert selection.record is None
    assert selection.reason == "no_supported_session_task"


def test_recovery_boundary_requires_explicit_handle_for_resume() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    ).record
    assert record is not None

    decision = decide_recovery_boundary(
        build_recovery_boundary_input(
            session_id="session-continuation",
            turn_id="turn:session-continuation:4",
            recovery_input_policy="resume",
            continuation_record=record,
        )
    )
    receipt = recovery_boundary_receipt_from_decision(decision)

    assert decision.action == "confirm_task_recovery"
    assert decision.reason == "expected_recovery_handle_missing"
    assert receipt.operation_availability["resume_task_recovery"] is False
    assert "allowed_next_actions" not in decision.to_dict()
    assert "forbidden_next_actions" not in decision.to_dict()
    assert "available_action_types_for_next_packet" not in receipt.to_dict()


def test_recovery_boundary_allows_resume_only_when_expected_handles_match() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    ).record
    assert record is not None

    decision = decide_recovery_boundary(
        build_recovery_boundary_input(
            session_id="session-continuation",
            turn_id="turn:session-continuation:4",
            recovery_input_policy="resume",
            expected_task_run_id=record.task_run_id,
            expected_continuation_id=record.continuation_id,
            continuation_record=record,
        )
    )
    receipt = recovery_boundary_receipt_from_decision(decision)

    assert decision.action == "resume_task_recovery"
    assert decision.reason == "recovery_boundary_ready"
    assert receipt.operation_availability == {"resume_task_recovery": True}
    assert receipt.task_run_ref == record.task_run_id
    assert "available_action_types_for_next_packet" not in receipt.to_dict()


def test_recovery_boundary_ignores_shadow_current_work_receipt_true() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    ).record
    assert record is not None

    decision = decide_recovery_boundary(
        build_recovery_boundary_input(
            session_id="session-continuation",
            turn_id="turn:session-continuation:4",
            recovery_input_policy="resume",
            expected_task_run_id=record.task_run_id,
            expected_continuation_id=record.continuation_id,
            continuation_record=record,
            current_work_boundary_receipt={
                "receipt_id": "cwreceipt:shadow",
                "decision_id": "cwbd:shadow",
                "boundary_decision": "current_work_control_required",
                "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
                "operation_availability": {"active_work_control": True},
            },
        )
    )

    assert decision.action == "resume_task_recovery"
    assert decision.reason == "recovery_boundary_ready"


def test_recovery_boundary_prioritizes_trusted_live_current_work_receipt() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    ).record
    assert record is not None

    decision = decide_recovery_boundary(
        build_recovery_boundary_input(
            session_id="session-continuation",
            turn_id="turn:session-continuation:4",
            recovery_input_policy="resume",
            expected_task_run_id=record.task_run_id,
            expected_continuation_id=record.continuation_id,
            continuation_record=record,
            current_work_boundary_receipt={
                "receipt_id": "cwreceipt:active",
                "decision_id": "cwbd:active",
                "boundary_decision": "current_work_control_required",
                "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
                "operation_availability": {"active_work_control": True},
                "authority": "harness.entrypoint.current_work_boundary_receipt",
            },
        )
    )

    assert decision.action == "no_task_recovery"
    assert decision.reason == "live_active_work_has_priority"


def test_single_agent_turn_does_not_project_untrusted_recovery_boundary_receipt() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    ).record
    assert record is not None

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-continuation",
        turn_id="turn:session-continuation:4",
        agent_invocation_id="aginvoke:session-continuation:4",
        user_message="继续。",
        history=[],
        session_context={
            "recovery_boundary_receipt": {
                "receipt_id": "rbreceipt:shadow",
                "decision_id": "rbd:shadow",
                "boundary_decision": "resume_task_recovery",
                "continuation_ref": record.continuation_id,
                "task_run_ref": record.task_run_id,
                "operation_availability": {"resume_task_recovery": True},
                "resume_execution_route": "task_executor_controller.schedule",
                "enforced": True,
            },
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    model_payload = json.dumps(result.packet.model_messages, ensure_ascii=False)

    assert "resume_task_recovery" not in result.packet.allowed_action_types
    assert result.packet.diagnostics["current_work_boundary_receipt"] == {}
    assert "recovery_boundary_receipt" not in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]
    assert "recovery_boundary_receipt" not in model_payload
    assert record.continuation_id not in model_payload
    assert record.task_run_id not in model_payload


def test_single_agent_turn_does_not_project_trusted_recovery_boundary_receipt() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    ).record
    assert record is not None
    decision = decide_recovery_boundary(
        build_recovery_boundary_input(
            session_id="session-continuation",
            turn_id="turn:session-continuation:4",
            recovery_input_policy="resume",
            expected_task_run_id=record.task_run_id,
            expected_continuation_id=record.continuation_id,
            continuation_record=record,
        )
    )
    receipt = recovery_boundary_receipt_from_decision(decision)

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-continuation",
        turn_id="turn:session-continuation:4",
        agent_invocation_id="aginvoke:session-continuation:4",
        user_message="继续。",
        history=[],
        session_context={
            "recovery_boundary_receipt": receipt.to_dict(),
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    model_payload = json.dumps(result.packet.model_messages, ensure_ascii=False)

    assert "resume_task_recovery" not in result.packet.allowed_action_types
    assert result.packet.diagnostics["current_work_boundary_receipt"] == {}
    assert "recovery_boundary_receipt" not in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]
    assert "recovery_boundary_receipt" not in model_payload
    assert record.continuation_id not in model_payload
    assert record.task_run_id not in model_payload


def test_public_turn_input_facts_do_not_accept_resume_as_recovery_decision() -> None:
    facts = build_turn_input_facts(
        session_id="session-continuation",
        turn_id="turn:session-continuation:4",
        user_message="继续",
        expected_task_run_id="taskrun:session-continuation:3:abc",
        expected_continuation_id="cont:session-continuation:17:0",
        recovery_input_policy="resume",
    )

    payload = facts.to_dict()
    assert payload["expected_task_run_id"] == "taskrun:session-continuation:3:abc"
    assert payload["expected_continuation_id"] == "cont:session-continuation:17:0"
    assert payload["recovery_input_policy"] == "auto"


def test_model_action_protocol_requires_explicit_task_recovery_resume_handles() -> None:
    valid_action, valid_diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:resume-task-recovery",
            "turn_id": "turn:session-continuation:4",
            "action_type": "resume_task_recovery",
            "public_progress_note": "我会从已恢复的任务断点继续，并先核对当前文件状态。",
            "task_recovery_resume": {
                "task_run_id": "taskrun:session-continuation:3:abc",
                "continuation_id": "cont:session-continuation:17:0",
                "reason": "用户要求继续上一轮可恢复任务",
            },
        },
        turn_id="turn:session-continuation:4",
        allowed_action_types=("respond", "ask_user", "block", "resume_task_recovery"),
    )

    assert valid_diagnostics["status"] == "accepted"
    assert valid_action is not None
    assert valid_action.action_type == "resume_task_recovery"
    assert valid_action.task_recovery_resume["task_run_id"] == "taskrun:session-continuation:3:abc"

    missing_handle_action, missing_handle_diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "turn_id": "turn:session-continuation:4",
            "action_type": "resume_task_recovery",
            "public_progress_note": "我会继续。",
            "task_recovery_resume": {"task_run_id": "taskrun:session-continuation:3:abc"},
        },
        turn_id="turn:session-continuation:4",
        allowed_action_types=("respond", "ask_user", "block", "resume_task_recovery"),
    )

    assert missing_handle_action is None
    assert missing_handle_diagnostics["status"] == "invalid"
    assert "task_recovery_resume.continuation_id_required" in missing_handle_diagnostics["validation_errors"]


def test_task_execution_protocol_rejects_resume_task_recovery_cross_context_action() -> None:
    action, diagnostics = task_execution_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:task-cross-resume",
            "turn_id": "taskrun:session-continuation:3:abc",
            "action_type": "resume_task_recovery",
            "public_progress_note": "不应在 task execution 内请求恢复。",
            "public_action_state": {
                "current_judgment": "恢复动作属于主线程模型决策。",
                "next_action": "拒绝跨上下文动作。",
            },
            "task_recovery_resume": {
                "task_run_id": "taskrun:session-continuation:3:abc",
                "continuation_id": "cont:session-continuation:17:0",
            },
        },
        turn_id="taskrun:session-continuation:3:abc",
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "field_not_allowed_for_task_execution:task_recovery_resume" in diagnostics["validation_errors"]


def test_task_execution_packet_injects_authorized_recovery_packet_from_task_run_diagnostics() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
        context_recovery_status=_fresh_context_recovery_status(),
    ).record
    assert record is not None
    recovery_packet = build_recovery_packet(
        record,
        resume_intent="user_requested_resume",
        user_resume_instruction="继续，并优先处理刚才新增的 steer。",
    )

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-continuation",
        task_run={
            "task_run_id": record.task_run_id,
            "diagnostics": {
                "executor_status": "running",
                "recovery_packet": recovery_packet,
            },
        },
        contract={
            "contract_id": "contract:session-continuation",
            "task_run_goal": "修复页面交互问题",
            "completion_criteria": ["恢复后继续执行"],
        },
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    model_payload = json.dumps(result.packet.model_messages, ensure_ascii=False)
    assert record.continuation_id in model_payload
    assert record.task_run_id in model_payload
    assert "user_requested_resume" in model_payload
    assert "继续，并优先处理刚才新增的 steer。" in model_payload
    assert "recovery_packet" in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]
