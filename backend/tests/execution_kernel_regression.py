from __future__ import annotations

from types import SimpleNamespace

from harness.loop.admission import AdmissionDecision
from harness.loop.action_permit import validate_tool_invocation_permit
from harness.loop.execution_kernel import (
    action_admission_denial_fingerprint,
    append_action_lifecycle_event,
    build_action_admission_recovery_payload,
    build_action_lifecycle_event_record,
    build_action_lifecycle_from_admission,
    build_action_tool_invocation_identity,
    build_tool_lifecycle_started_event_record,
    decide_model_action_lifecycle,
)
from harness.loop.model_action_protocol import ModelActionRequest
from runtime.shared.file_observation_policy import read_window_fingerprint_defaults


def test_execution_kernel_emits_lifecycle_for_allowed_tool_call() -> None:
    action = ModelActionRequest(
        request_id="model-action:kernel:read",
        turn_id="turn:kernel:read",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "README.md"}},
    )

    lifecycle = decide_model_action_lifecycle(
        action,
        invocation_kind="agent_turn",
        packet_ref="packet:kernel:read",
        packet_allowed_action_types=("respond", "tool_call", "block"),
        definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
        allowed_tool_names={"read_file"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
        session_id="session:kernel",
        turn_id="turn:kernel:read",
    )

    payload = lifecycle.to_dict()

    assert lifecycle.allowed is True
    assert payload["authority"] == "harness.loop.execution_kernel"
    assert payload["lifecycle_id"] == f"action-lifecycle:{action.request_id}"
    assert payload["action_request_ref"] == action.request_id
    assert payload["packet_ref"] == "packet:kernel:read"
    assert payload["admission"]["authority"] == "harness.loop.admission"
    assert payload["admission"]["decision"] == "allow"
    assert payload["action_permit"]["authority"] == "harness.loop.action_permit"
    assert payload["action_permit"]["decision"] == "allow"
    assert payload["action_permit"]["tool_name"] == "read_file"
    assert payload["allowed_action_types"] == ["respond", "tool_call", "block"]
    assert payload["allowed_tool_names"] == ["read_file"]
    assert payload["diagnostics"]["single_authority_chain"] == "admission->action_permit"


def test_execution_kernel_preserves_operation_unavailable_as_lifecycle_denial() -> None:
    action = ModelActionRequest(
        request_id="model-action:kernel:active-work",
        turn_id="turn:kernel:active-work",
        action_type="active_work_control",
        active_work_control={"action": "continue_active_work"},
    )

    lifecycle = decide_model_action_lifecycle(
        action,
        invocation_kind="single_agent_turn",
        packet_allowed_action_types=("respond", "ask_user", "block", "active_work_control"),
        current_work_boundary_receipt={
            "receipt_id": "cwreceipt:kernel:missing",
            "boundary_decision": "current_work_unavailable",
            "operation_availability": {"active_work_control": False},
        },
    )

    payload = lifecycle.to_dict()

    assert lifecycle.allowed is False
    assert payload["admission"]["decision"] == "operation_unavailable"
    assert payload["admission"]["issue_category"] == "operation_unavailable"
    assert payload["admission"]["issue_code"] == "active_work_control_unavailable"
    assert payload["action_permit"]["decision"] == "operation_unavailable"
    assert payload["action_permit"]["issue_category"] == "operation_unavailable"
    assert payload["action_permit"]["action_issue"]["model_intent_preserved"] is True
    assert payload["diagnostics"]["admission_decision"] == "operation_unavailable"
    assert payload["diagnostics"]["permit_decision"] == "operation_unavailable"


def test_execution_kernel_rebuilds_permit_from_existing_admission_with_resource_scope() -> None:
    action = ModelActionRequest(
        request_id="model-action:kernel:write",
        turn_id="turn:kernel:write",
        action_type="tool_call",
        tool_call={"tool_name": "write_file", "args": {"path": "out.md", "content": "done"}},
    )
    admission = AdmissionDecision(
        admission_id=f"admission:{action.request_id}",
        action_request_ref=action.request_id,
        decision="allow",
        permission_delta={
            "tool_name": "write_file",
            "operation_id": "op.write_file",
            "read_only": False,
            "permission_mode": "default",
        },
    )

    lifecycle = build_action_lifecycle_from_admission(
        action,
        admission,
        invocation_kind="task_execution",
        packet_ref="packet:kernel:write",
        packet_allowed_action_types=("respond", "tool_call", "block"),
        allowed_tool_names={"write_file"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
        session_id="session:kernel",
        turn_id="turn:kernel:write",
        task_run_id="taskrun:kernel",
        grant_scope="task_run",
        resource_scope={"approval_risk_fingerprint": "approval-risk:kernel"},
    )

    permit = lifecycle.to_dict()["action_permit"]

    assert lifecycle.allowed is True
    assert lifecycle.admission is admission
    assert permit["grant_scope"] == "task_run"
    assert permit["session_id"] == "session:kernel"
    assert permit["turn_id"] == "turn:kernel:write"
    assert permit["task_run_id"] == "taskrun:kernel"
    assert permit["resource_scope"]["approval_risk_fingerprint"] == "approval-risk:kernel"
    assert validate_tool_invocation_permit(
        action_permit=permit,
        action_request_ref=action.request_id,
        invocation_kind="task_execution",
        tool_name="write_file",
        operation_id="op.write_file",
        session_id="session:kernel",
        turn_id="turn:kernel:write",
        task_run_id="taskrun:kernel",
        approval_risk_fingerprint="approval-risk:kernel",
    ) == ""


def test_execution_kernel_builds_canonical_lifecycle_event_record() -> None:
    action = ModelActionRequest(
        request_id="model-action:kernel:event",
        turn_id="turn:kernel:event",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "README.md"}},
    )
    lifecycle = decide_model_action_lifecycle(
        action,
        invocation_kind="agent_turn",
        packet_ref="packet:kernel:event",
        packet_allowed_action_types=("respond", "tool_call", "block"),
        definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
        allowed_tool_names={"read_file"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
        session_id="session:kernel",
        turn_id="turn:kernel:event",
    )

    record = build_action_lifecycle_event_record(
        lifecycle,
        action,
        run_id="turnrun:kernel:event",
        packet_ref="packet:kernel:event",
        session_id="session:kernel",
        turn_id="turn:kernel:event",
        turn_run_id="turnrun:kernel:event",
        batch_action_request_ref="model-action:kernel:batch",
    )

    payload = record.payload
    refs = record.refs

    assert record.event_type == "model_action_admission_checked"
    assert record.authority == "harness.loop.execution_kernel"
    assert payload["action_lifecycle_event"]["authority"] == "harness.loop.execution_kernel"
    assert payload["model_action_request"]["request_id"] == action.request_id
    assert payload["admission"]["admission_id"] == f"admission:{action.request_id}"
    assert payload["action_lifecycle"]["lifecycle_id"] == f"action-lifecycle:{action.request_id}"
    assert payload["batch_action_request_ref"] == "model-action:kernel:batch"
    assert refs["action_request_ref"] == action.request_id
    assert refs["action_lifecycle_ref"] == f"action-lifecycle:{action.request_id}"
    assert refs["runtime_invocation_packet_ref"] == "packet:kernel:event"
    assert refs["turn_run_ref"] == "turnrun:kernel:event"
    assert refs["batch_action_request_ref"] == "model-action:kernel:batch"


def test_execution_kernel_appends_lifecycle_event_from_canonical_record() -> None:
    class EventLog:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def append(self, run_id, event_type, *, payload, refs):
            self.calls.append(
                {
                    "run_id": run_id,
                    "event_type": event_type,
                    "payload": dict(payload or {}),
                    "refs": dict(refs or {}),
                }
            )
            return SimpleNamespace(offset=3, created_at=4.0, to_dict=lambda: dict(self.calls[-1]))

    action = ModelActionRequest(
        request_id="model-action:kernel:append",
        turn_id="turn:kernel:append",
        action_type="respond",
        final_answer="done",
    )
    lifecycle = decide_model_action_lifecycle(
        action,
        invocation_kind="agent_turn",
        packet_ref="packet:kernel:append",
        packet_allowed_action_types=("respond", "tool_call", "block"),
        session_id="session:kernel",
        turn_id="turn:kernel:append",
    )
    record = build_action_lifecycle_event_record(
        lifecycle,
        action,
        run_id="turnrun:kernel:append",
        packet_ref="packet:kernel:append",
        session_id="session:kernel",
        turn_id="turn:kernel:append",
        turn_run_id="turnrun:kernel:append",
    )
    event_log = EventLog()

    event = append_action_lifecycle_event(SimpleNamespace(event_log=event_log), record)

    assert event.offset == 3
    assert event_log.calls == [
        {
            "run_id": "turnrun:kernel:append",
            "event_type": "model_action_admission_checked",
            "payload": record.payload,
            "refs": record.refs,
        }
    ]


def test_execution_kernel_builds_admission_recovery_payload_with_stable_fingerprint() -> None:
    action = ModelActionRequest(
        request_id="model-action:kernel:denied-tool",
        turn_id="turn:kernel:denied-tool",
        action_type="tool_call",
        tool_call={"tool_name": "write_file", "args": {"path": "out.md", "content": "done"}},
    )
    admission = AdmissionDecision(
        admission_id=f"admission:{action.request_id}",
        action_request_ref=action.request_id,
        decision="needs_contract",
        system_reason="side_effect_tool_requires_task_run",
        user_visible_reason="这个动作会改变环境，需要先确认处理目标和安全边界。",
        issue_category="requires_task_run",
        issue_code="side_effect_tool_requires_task_run",
        action_issue={
            "authority": "harness.loop.action_issue",
            "category": "requires_task_run",
            "code": "side_effect_tool_requires_task_run",
            "model_intent_preserved": True,
        },
    )
    runtime_fingerprint = {
        "runtime_assembly_id": "assembly:kernel",
        "tool_registry_hash": "tools:kernel",
        "permission_mode": "default",
    }

    recovery = build_action_admission_recovery_payload(
        action,
        admission,
        runtime_fingerprint=runtime_fingerprint,
    )

    expected_fingerprint = action_admission_denial_fingerprint(
        action,
        admission_payload=admission.to_dict(),
        runtime_fingerprint=runtime_fingerprint,
    )

    assert recovery.status == "needs_contract"
    assert recovery.source == "system:model_action_admission"
    assert recovery.observation_type == "executor_error"
    assert recovery.model_visible_recovery_observation is True
    assert recovery.admission_denial_fingerprint == expected_fingerprint
    assert recovery.payload["admission_denial_fingerprint"] == expected_fingerprint
    assert recovery.payload["action_lifecycle_ref"] == f"action-lifecycle:{action.request_id}"
    assert recovery.payload["action_request_ref"] == action.request_id
    assert recovery.payload["structured_error"]["origin"] == "model_action_admission"
    assert recovery.payload["rejected_action_request"]["request_id"] == action.request_id
    assert "不要重复同一个未获准动作" in recovery.repair_instruction


def test_execution_kernel_builds_repeated_admission_guard_payload() -> None:
    read_defaults = read_window_fingerprint_defaults()
    action = ModelActionRequest(
        request_id="model-action:kernel:repeat",
        turn_id="turn:kernel:repeat",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "src\\main.py"}},
    )
    admission = AdmissionDecision(
        admission_id=f"admission:{action.request_id}",
        action_request_ref=action.request_id,
        decision="deny",
        system_reason="tool_not_in_runtime_assembly",
    )

    recovery = build_action_admission_recovery_payload(
        action,
        admission,
        runtime_fingerprint={"permission_mode": "default"},
        repeat_count=3,
        previous_observation_refs=("rtobs:first", "rtobs:second"),
        pause_after_observation=True,
    )

    assert recovery.source == "system:repeated_admission_guard"
    assert recovery.observation_type == "runtime_guard"
    assert recovery.error_code == "repeated_admission_denial"
    assert recovery.payload["admission_denial_repeat_count"] == 3
    assert recovery.payload["action_lifecycle_ref"] == f"action-lifecycle:{action.request_id}"
    assert recovery.payload["previous_observation_refs"] == ["rtobs:first", "rtobs:second"]
    assert recovery.payload["pause_after_observation"] is True
    assert recovery.payload["tool_args"]["rejected_tool_args"]["path"] == "src/main.py"
    assert recovery.payload["tool_args"]["rejected_tool_args"]["start_line"] == read_defaults["start_line"]
    assert recovery.payload["tool_args"]["rejected_tool_args"]["line_count"] == read_defaults["line_count"]


def test_execution_kernel_builds_tool_invocation_identity_with_cell_scope() -> None:
    action = ModelActionRequest(
        request_id="model-action:kernel:invoke",
        turn_id="turn:kernel:invoke",
        action_type="tool_call",
        tool_call={
            "id": "toolcall:kernel:invoke",
            "tool_name": "read_file",
            "args": {"path": "src\\main.py"},
        },
    )
    lifecycle = decide_model_action_lifecycle(
        action,
        invocation_kind="task_execution",
        packet_ref="packet:kernel:invoke",
        packet_allowed_action_types=("respond", "tool_call", "block"),
        definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
        allowed_tool_names={"read_file"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
        session_id="session:kernel",
        turn_id="turn:kernel:invoke",
        task_run_id="taskrun:kernel",
        grant_scope="task_run",
    )

    identity = build_action_tool_invocation_identity(
        action,
        caller_ref="taskrun:kernel",
        definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
        admission=lifecycle.admission,
        action_permit=lifecycle.action_permit,
        action_lifecycle_ref=lifecycle.lifecycle_id,
        tool_args_override={"path": "src/main.py", "start_line": 5},
        agent_run_id="agrun:kernel",
        run_cell_id="cell:kernel",
    )

    payload = identity.to_dict()

    assert payload["authority"] == "harness.loop.execution_kernel"
    assert payload["caller_ref"] == "taskrun:kernel"
    assert payload["action_request_ref"] == action.request_id
    assert payload["action_lifecycle_ref"] == lifecycle.lifecycle_id
    assert payload["admission_ref"] == lifecycle.admission.admission_id
    assert payload["tool_name"] == "read_file"
    assert payload["tool_call_id"] == "toolcall:kernel:invoke"
    assert payload["tool_args"] == {"path": "src/main.py", "start_line": 5}
    assert payload["operation_id"] == "op.read_file"
    assert payload["action_permit"]["permit_id"] == f"action-permit:{action.request_id}"
    assert payload["agent_run_id"] == "agrun:kernel"
    assert payload["run_cell_id"] == "cell:kernel"
    assert payload["invocation_id"].startswith("toolinv:")


def test_execution_kernel_builds_tool_lifecycle_started_record_with_cell_scope() -> None:
    action = ModelActionRequest(
        request_id="model-action:kernel:started",
        turn_id="turn:kernel:started",
        action_type="tool_call",
        tool_call={
            "id": "toolcall:kernel:started",
            "tool_name": "read_file",
            "args": {"path": "src/main.py"},
        },
    )
    lifecycle = decide_model_action_lifecycle(
        action,
        invocation_kind="task_execution",
        packet_ref="packet:kernel:started",
        packet_allowed_action_types=("respond", "tool_call", "block"),
        definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
        allowed_tool_names={"read_file"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
        session_id="session:kernel",
        turn_id="turn:kernel:started",
        task_run_id="taskrun:kernel",
        grant_scope="task_run",
    )
    identity = build_action_tool_invocation_identity(
        action,
        caller_ref="taskrun:kernel",
        definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
        admission=lifecycle.admission,
        action_permit=lifecycle.action_permit,
        action_lifecycle_ref=lifecycle.lifecycle_id,
        agent_run_id="agrun:kernel",
        run_cell_id="cell:kernel",
    )

    record = build_tool_lifecycle_started_event_record(
        identity,
        run_id="taskrun:kernel",
        caller_kind="task_run",
        session_id="session:kernel",
        turn_id="turn:kernel:started",
        task_run_id="taskrun:kernel",
        packet_ref="packet:kernel:started",
        target="src/main.py",
        arguments_preview="path=src/main.py",
    )

    payload = record.payload
    refs = record.refs

    assert record.event_type == "tool_item_started"
    assert record.authority == "harness.loop.execution_kernel"
    assert payload["action_lifecycle_event"]["authority"] == "harness.loop.execution_kernel"
    assert payload["caller_kind"] == "task_run"
    assert payload["caller_ref"] == "taskrun:kernel"
    assert payload["tool_lifecycle_id"] == identity.invocation_id
    assert payload["tool_invocation_id"] == identity.invocation_id
    assert payload["permission_decision_id"] == lifecycle.admission.admission_id
    assert payload["action_request_ref"] == action.request_id
    assert payload["action_lifecycle_ref"] == lifecycle.lifecycle_id
    assert payload["arguments_preview"] == "path=src/main.py"
    assert payload["packet_ref"] == "packet:kernel:started"
    assert payload["agent_run_id"] == "agrun:kernel"
    assert payload["run_cell_id"] == "cell:kernel"
    assert refs["task_run_ref"] == "taskrun:kernel"
    assert refs["runtime_invocation_packet_ref"] == "packet:kernel:started"
    assert refs["tool_invocation_ref"] == identity.invocation_id
    assert refs["agent_run_ref"] == "agrun:kernel"
    assert refs["run_cell_ref"] == "cell:kernel"
