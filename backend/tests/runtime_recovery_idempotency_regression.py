from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.operation_registry import OperationDescriptor
from orchestration import RuntimeActionRequest
from harness.loop.agent_execution import prepare_tool_execution
from runtime.unit_runtime.loop import TaskRunLoop


def _action_request(request_id: str) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        request_id=request_id,
        task_run_id="taskrun:test-recovery",
        request_type="tool_call",
        step_id="step.write",
        directive_ref="directive:test",
        operation_id="op.test_write",
        payload={
            "tool_name": "edit_file",
            "tool_call": {
                "id": "call-1",
                "name": "edit_file",
                "args": {"path": "docs/test.md", "instruction": "append line"},
                "type": "tool_call",
            },
            "execution_state": "requested_not_dispatched",
        },
    )


def test_idempotent_write_reuses_completed_result(tmp_path: Path) -> None:
    loop = TaskRunLoop(tmp_path / "runtime-idempotent")
    descriptor = OperationDescriptor(
        operation_id="op.test_write",
        operation_type="filesystem",
        title="Test Write",
        capability_summary="",
        idempotent=True,
        read_only=False,
    )

    first_record, first_events, first_decision = prepare_tool_execution(
        task_run_id="taskrun:test-recovery",
        step_id="step.write",
        action_request=_action_request("req-1"),
        directive_ref="directive:test",
        operation_id="op.test_write",
        descriptor=descriptor,
        tool_name="edit_file",
        execution_store=loop.execution_store,
        record_execution_event=loop._record_execution_event,
    )
    assert first_decision == "dispatch"
    assert first_record.replay_policy == "reuse_completed_result"
    assert [event.event_type for event in first_events] == ["execution_record_created"]

    loop.execution_store.mark_completed(
        first_record,
        result_ref="execution-result:first",
        result_payload={
            "tool_name": "edit_file",
            "tool_call_id": "call-1",
            "tool_args": {"path": "docs/test.md", "instruction": "append line"},
            "result": "patched",
            "result_chars": 7,
            "truncated": False,
        },
    )

    second_record, second_events, second_decision = prepare_tool_execution(
        task_run_id="taskrun:test-recovery",
        step_id="step.write",
        action_request=_action_request("req-2"),
        directive_ref="directive:test",
        operation_id="op.test_write",
        descriptor=descriptor,
        tool_name="edit_file",
        execution_store=loop.execution_store,
        record_execution_event=loop._record_execution_event,
    )

    assert second_decision == "reuse_completed_result"
    assert second_record.status == "reused_completed_result"
    assert second_record.result_ref == "execution-result:first"
    assert second_record.diagnostics["source_execution_id"] == first_record.execution_id
    assert [event.event_type for event in second_events] == [
        "execution_record_created",
        "recovery_replay_decided",
        "execution_result_reused",
    ]


def test_non_replay_safe_write_is_suppressed_on_duplicate_request(tmp_path: Path) -> None:
    loop = TaskRunLoop(tmp_path / "runtime-nonreplay")
    descriptor = OperationDescriptor(
        operation_id="op.test_write",
        operation_type="filesystem",
        title="Test Write",
        capability_summary="",
        destructive=True,
        idempotent=False,
        read_only=False,
        requires_user_interaction=True,
    )

    first_record, _, first_decision = prepare_tool_execution(
        task_run_id="taskrun:test-recovery",
        step_id="step.write",
        action_request=_action_request("req-1"),
        directive_ref="directive:test",
        operation_id="op.test_write",
        descriptor=descriptor,
        tool_name="edit_file",
        execution_store=loop.execution_store,
        record_execution_event=loop._record_execution_event,
    )
    assert first_decision == "dispatch"
    loop.execution_store.mark_completed(
        first_record,
        result_ref="execution-result:first",
        result_payload={"result": "patched"},
    )

    second_record, second_events, second_decision = prepare_tool_execution(
        task_run_id="taskrun:test-recovery",
        step_id="step.write",
        action_request=_action_request("req-2"),
        directive_ref="directive:test",
        operation_id="op.test_write",
        descriptor=descriptor,
        tool_name="edit_file",
        execution_store=loop.execution_store,
        record_execution_event=loop._record_execution_event,
    )

    assert second_decision == "deny_auto_replay"
    assert second_record.status == "replay_suppressed"
    assert second_record.diagnostics["source_execution_id"] == first_record.execution_id
    assert [event.event_type for event in second_events] == [
        "execution_record_created",
        "recovery_replay_decided",
        "replay_guard_triggered",
    ]
