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


class _StateIndex:
    def __init__(self, task_runs):
        self._task_runs = list(task_runs)

    def list_session_task_runs(self, session_id: str):
        return [item for item in self._task_runs if item.session_id == session_id]


class _RuntimeObjects:
    def get_object(self, _ref: str):
        return {}


class _Host:
    def __init__(self, task_runs):
        self.state_index = _StateIndex(task_runs)
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
            "latest_public_progress_note": "后端运行时已重启，当前工作已恢复为可继续状态。",
            "goal": "修复页面交互问题",
        },
    )


def test_selector_builds_recoverable_continuation_record_from_waiting_executor() -> None:
    selection = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
    )

    assert selection.record is not None
    assert selection.record.state == "recoverable"
    assert selection.record.resume_allowed is True
    assert selection.record.task_run_id == "taskrun:session-continuation:3:abc"
    assert selection.record.recovery_cause == "runtime_restart"
    assert selection.record.latest_progress


def test_recovery_boundary_requires_explicit_handle_for_resume() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
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

    assert decision.action == "confirm_recoverable_work"
    assert decision.reason == "expected_recovery_handle_missing"
    assert receipt.operation_availability["resume_recoverable_work"] is False


def test_recovery_boundary_allows_resume_only_when_expected_handles_match() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
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

    assert decision.action == "resume_recoverable_work"
    assert decision.reason == "recovery_boundary_ready"
    assert receipt.operation_availability["resume_recoverable_work"] is True
    assert receipt.task_run_ref == record.task_run_id


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


def test_model_action_protocol_requires_explicit_recovery_resume_handles() -> None:
    valid_action, valid_diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:resume-recoverable",
            "turn_id": "turn:session-continuation:4",
            "action_type": "resume_recoverable_work",
            "public_progress_note": "我会从已恢复的任务断点继续，并先核对当前文件状态。",
            "recovery_resume": {
                "task_run_id": "taskrun:session-continuation:3:abc",
                "continuation_id": "cont:session-continuation:17:0",
                "reason": "用户要求继续上一轮可恢复任务",
            },
        },
        turn_id="turn:session-continuation:4",
        allowed_action_types=("respond", "ask_user", "block", "resume_recoverable_work"),
    )

    assert valid_diagnostics["status"] == "accepted"
    assert valid_action is not None
    assert valid_action.action_type == "resume_recoverable_work"
    assert valid_action.recovery_resume["task_run_id"] == "taskrun:session-continuation:3:abc"

    missing_handle_action, missing_handle_diagnostics = model_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "turn_id": "turn:session-continuation:4",
            "action_type": "resume_recoverable_work",
            "public_progress_note": "我会继续。",
            "recovery_resume": {"task_run_id": "taskrun:session-continuation:3:abc"},
        },
        turn_id="turn:session-continuation:4",
        allowed_action_types=("respond", "ask_user", "block", "resume_recoverable_work"),
    )

    assert missing_handle_action is None
    assert missing_handle_diagnostics["status"] == "invalid"
    assert "recovery_resume.continuation_id_required" in missing_handle_diagnostics["validation_errors"]


def test_task_execution_protocol_rejects_resume_recoverable_work_cross_context_action() -> None:
    action, diagnostics = task_execution_action_request_from_payload(
        {
            "authority": "harness.loop.model_action_request",
            "request_id": "model-action:task-cross-resume",
            "turn_id": "taskrun:session-continuation:3:abc",
            "action_type": "resume_recoverable_work",
            "public_progress_note": "不应在 task execution 内请求恢复。",
            "public_action_state": {
                "current_judgment": "恢复动作属于主线程模型决策。",
                "next_action": "拒绝跨上下文动作。",
            },
            "recovery_resume": {
                "task_run_id": "taskrun:session-continuation:3:abc",
                "continuation_id": "cont:session-continuation:17:0",
            },
        },
        turn_id="taskrun:session-continuation:3:abc",
    )

    assert action is None
    assert diagnostics["status"] == "invalid"
    assert "field_not_allowed_for_task_execution:recovery_resume" in diagnostics["validation_errors"]


def test_task_execution_packet_injects_authorized_recovery_packet_from_task_run_diagnostics() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
    ).record
    assert record is not None
    recovery_packet = build_recovery_packet(record, resume_intent="user_requested_resume")

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

    dynamic_payload = _message_payload_with_title(result.packet, "Task execution runtime boundary")
    projected = dict(dynamic_payload["recovery_packet"])
    assert projected["continuation_id"] == record.continuation_id
    assert projected["task_run_id"] == record.task_run_id
    assert projected["resume_intent"] == "user_requested_resume"
    assert "recovery_packet" in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]
