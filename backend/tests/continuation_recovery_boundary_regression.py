from __future__ import annotations

import json

from runtime.shared.models import TaskRun, TurnRun
from runtime.shared.event_log import RuntimeEventLog

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
from harness.runtime import RuntimeCompiler, RuntimeGateway, RuntimeSignalScope
from harness.runtime.control_events import build_runtime_signal_envelope
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
    def __init__(self, task_runs, turn_runs=None, event_log=None):
        self.state_index = _StateIndex(task_runs, turn_runs=turn_runs)
        self.runtime_objects = _RuntimeObjects()
        self.event_log = event_log
        self.runtime_gateway = RuntimeGateway(event_log) if event_log is not None else None


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


def _interrupted_turn() -> TurnRun:
    return TurnRun(
        turn_run_id="turnrun:session-continuation:4:def",
        session_id="session-continuation",
        turn_id="turn:session-continuation:4",
        execution_runtime_kind="single_agent_turn",
        status="blocked",
        latest_event_offset=21,
        updated_at=120.0,
        terminal_reason="single_turn_tool_iteration_limit",
        diagnostics={
            "turn_id": "turn:session-continuation:4",
            "stream_run_id": "strun:session-continuation:4",
            "latest_step": "tool_budget_closeout",
            "latest_step_summary": "已读取 fps_game.html 的敌人生成和移动逻辑，尚未完成最终修复判断。",
            "assistant_visible_stream_continuity": {
                "content": "我已经定位到敌人生成逻辑，接下来",
                "content_sha256": "sha256:test-visible-prefix",
                "content_utf8_bytes": 54,
                "truncated_from_start": False,
                "authority": "harness.loop.single_agent_turn.assistant_stream_continuity",
            },
        },
    )


def _completed_turn() -> TurnRun:
    return TurnRun(
        turn_run_id="turnrun:session-continuation:5:ghi",
        session_id="session-continuation",
        turn_id="turn:session-continuation:5",
        execution_runtime_kind="single_agent_turn",
        status="completed",
        latest_event_offset=24,
        updated_at=140.0,
        terminal_reason="respond",
        diagnostics={
            "turn_id": "turn:session-continuation:5",
            "latest_step": "respond",
            "latest_step_summary": "已完成上一轮答复。",
        },
    )


def _generic_interrupted_turn_with_diagnostic_signal() -> TurnRun:
    return TurnRun(
        turn_run_id="turnrun:session-continuation:6:jkl",
        session_id="session-continuation",
        turn_id="turn:session-continuation:6",
        execution_runtime_kind="single_agent_turn",
        status="failed",
        latest_event_offset=31,
        updated_at=150.0,
        terminal_reason="model_output_boundary_failed",
        diagnostics={
            "turn_id": "turn:session-continuation:6",
            "latest_step": "protocol_repair_failed",
            "latest_step_summary": "模型输出没有满足动作合同。",
            "latest_runtime_control_signal": {
                "signal_kind": "model_protocol_violation",
                "message": "diagnostic-only signal must not decide continuation",
            },
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


def test_selector_builds_continuation_context_from_interrupted_turn_tool_limit() -> None:
    selection = select_session_continuation(
        _Host([], turn_runs=[_interrupted_turn()]),
        session_id="session-continuation",
    )

    assert selection.record is None
    assert selection.interrupted_turn is not None
    assert selection.interrupted_turn.state == "interrupted_continuation_context"
    assert selection.interrupted_turn.resume_allowed is False
    assert selection.interrupted_turn.turn_run_id == "turnrun:session-continuation:4:def"
    assert selection.interrupted_turn.interruption_kind == "tool_budget_exhausted"
    assert selection.interrupted_turn.visible_assistant_prefix == "我已经定位到敌人生成逻辑，接下来"
    assert selection.interrupted_turn.visible_assistant_prefix_sha256 == "sha256:test-visible-prefix"
    assert "exact read evidence" in selection.interrupted_turn.model_visible_summary
    assert "已公开" in selection.interrupted_turn.model_visible_summary


def test_selector_uses_gateway_signal_for_generic_interrupted_turn(tmp_path) -> None:
    turn = _generic_interrupted_turn_with_diagnostic_signal()
    event_log = RuntimeEventLog(tmp_path)
    host = _Host([], turn_runs=[turn], event_log=event_log)
    signal_event = host.runtime_gateway.publish(
        turn.turn_run_id,
        signal_type="control.signal.requested",
        signal_id="turnsig:model-protocol-violation:test",
        scope=RuntimeSignalScope(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            turn_run_id=turn.turn_run_id,
        ),
        source_authority="test.continuation.gateway_signal",
        payload={
            "signal_kind": "model_protocol_violation",
            "message": "Gateway signal decides continuation.",
        },
        visibility="runtime_private",
    )
    host.runtime_gateway.mark_observed_by_id(
        turn.turn_run_id,
        signal_id=dict(dict(signal_event.payload or {}).get("signal") or {})["signal_id"],
        observed_by="test.continuation.gateway_signal",
    )

    selection = select_session_continuation(host, session_id="session-continuation")

    assert selection.interrupted_turn is not None
    assert selection.interrupted_turn.interruption_kind == "model_protocol_violation"
    assert selection.interrupted_turn.diagnostics["latest_runtime_control_signal_kind"] == "model_protocol_violation"


def test_selector_ignores_diagnostics_only_signal_for_generic_interrupted_turn() -> None:
    selection = select_session_continuation(
        _Host([], turn_runs=[_generic_interrupted_turn_with_diagnostic_signal()]),
        session_id="session-continuation",
    )

    assert selection.interrupted_turn is None
    assert selection.reason == "session_task_run_missing_or_interrupted_turn_missing"


def test_selector_ignores_derived_gateway_signal_without_published_source(tmp_path) -> None:
    turn = _generic_interrupted_turn_with_diagnostic_signal()
    event_log = RuntimeEventLog(tmp_path)
    host = _Host([], turn_runs=[turn], event_log=event_log)
    scope = RuntimeSignalScope(
        session_id=turn.session_id,
        turn_id=turn.turn_id,
        turn_run_id=turn.turn_run_id,
    )
    for event_type, state, actor in (
        ("runtime_control_signal_observed", "observed", "test.observer"),
        ("runtime_control_signal_consumed", "consumed", "test.consumer"),
    ):
        signal = build_runtime_signal_envelope(
            signal_type="control.signal.requested",
            signal_id="rtsig:derived-only",
            scope=scope,
            source_authority="test.derived",
            payload={
                "signal_kind": "model_protocol_violation",
                "message": "derived signal must not decide continuation",
            },
            consumption_state=state,
            consumed_by=actor,
        )
        event_log.append(
            turn.turn_run_id,
            event_type,  # type: ignore[arg-type]
            payload={"signal": signal.to_dict()},
            refs={"signal_ref": signal.signal_id},
        )

    selection = select_session_continuation(host, session_id="session-continuation")

    assert selection.interrupted_turn is None
    assert selection.reason == "session_task_run_missing_or_interrupted_turn_missing"


def test_selector_does_not_reuse_old_interrupted_turn_after_newer_completed_turn() -> None:
    selection = select_session_continuation(
        _Host([], turn_runs=[_interrupted_turn(), _completed_turn()]),
        session_id="session-continuation",
    )

    assert selection.record is None
    assert selection.interrupted_turn is None
    assert selection.reason == "session_task_run_missing_or_interrupted_turn_missing"


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
    assert "allowed_next_actions" not in decision.to_dict()
    assert "forbidden_next_actions" not in decision.to_dict()
    assert "available_action_types_for_next_packet" not in receipt.to_dict()


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
    assert receipt.operation_availability == {"resume_recoverable_work": True}
    assert receipt.task_run_ref == record.task_run_id
    assert "available_action_types_for_next_packet" not in receipt.to_dict()


def test_recovery_boundary_ignores_shadow_current_work_receipt_true() -> None:
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
            current_work_boundary_receipt={
                "receipt_id": "cwreceipt:shadow",
                "decision_id": "cwbd:shadow",
                "boundary_decision": "current_work_control_required",
                "active_work_ref": {"task_run_id": "taskrun:active", "actual_active_turn_id": "turn:active"},
                "operation_availability": {"active_work_control": True},
            },
        )
    )

    assert decision.action == "resume_recoverable_work"
    assert decision.reason == "recovery_boundary_ready"


def test_recovery_boundary_prioritizes_trusted_live_current_work_receipt() -> None:
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

    assert decision.action == "no_recoverable_work"
    assert decision.reason == "live_active_work_has_priority"


def test_recovery_boundary_receipt_projection_requires_authority() -> None:
    record = select_session_continuation(
        _Host([_recoverable_task()]),
        session_id="session-continuation",
    ).record
    assert record is not None

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-continuation",
        turn_id="turn:session-continuation:4",
        agent_invocation_id="aginvoke:session-continuation:4",
        user_message="继续。",
        history=[],
        session_context={
            "recoverable_work": record.to_dict(),
            "recovery_boundary_receipt": {
                "receipt_id": "rbreceipt:shadow",
                "decision_id": "rbd:shadow",
                "boundary_decision": "resume_recoverable_work",
                "continuation_ref": record.continuation_id,
                "task_run_ref": record.task_run_id,
                "operation_availability": {"resume_recoverable_work": True},
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

    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected = dict(dynamic_payload["recovery_boundary_receipt"])

    assert "resume_recoverable_work" in result.packet.allowed_action_types
    assert projected["operation_availability"]["resume_recoverable_work"] is False
    assert projected["read_only_context"] is True


def test_recovery_boundary_receipt_projection_accepts_trusted_resume_receipt() -> None:
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

    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session-continuation",
        turn_id="turn:session-continuation:4",
        agent_invocation_id="aginvoke:session-continuation:4",
        user_message="继续。",
        history=[],
        session_context={
            "recoverable_work": record.to_dict(),
            "recovery_boundary_receipt": receipt.to_dict(),
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
        },
    )

    dynamic_payload = _message_payload_with_title(result.packet, "Single agent turn dynamic runtime")
    projected = dict(dynamic_payload["recovery_boundary_receipt"])

    assert projected["operation_availability"]["resume_recoverable_work"] is True
    assert projected["read_only_context"] is False


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

    dynamic_payload = _message_payload_with_title(result.packet, "Task execution runtime boundary")
    projected = dict(dynamic_payload["recovery_packet"])
    assert projected["continuation_id"] == record.continuation_id
    assert projected["task_run_id"] == record.task_run_id
    assert projected["resume_intent"] == "user_requested_resume"
    assert projected["user_resume_instruction"] == "继续，并优先处理刚才新增的 steer。"
    assert "recovery_packet" in result.packet.diagnostics["prompt_manifest"]["dynamic_projection_refs"]
