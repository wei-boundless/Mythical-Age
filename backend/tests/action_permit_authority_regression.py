from __future__ import annotations

from types import SimpleNamespace

from harness.loop.action_permit import action_permit_from_admission, validate_tool_invocation_permit
from harness.loop.admission import admit_model_action
from harness.loop.model_action_protocol import ModelActionRequest


def test_action_admission_emits_permit_for_allowed_tool_call() -> None:
    action = ModelActionRequest(
        request_id="model-action:test:read",
        turn_id="turn:test:1",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "README.md"}},
    )
    admission = admit_model_action(
        action,
        packet_allowed_action_types=("respond", "tool_call", "block"),
        invocation_kind="agent_turn",
        definitions_by_name={"read_file": SimpleNamespace(operation_id="op.read_file", is_read_only=True)},
        allowed_tool_names={"read_file"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
    )
    permit = action_permit_from_admission(
        action,
        admission,
        invocation_kind="agent_turn",
        packet_allowed_action_types=("respond", "tool_call", "block"),
        allowed_tool_names={"read_file"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
    )

    payload = permit.to_dict()

    assert admission.decision == "allow"
    assert payload["authority"] == "harness.loop.action_permit"
    assert payload["permit_id"] == f"action-permit:{action.request_id}"
    assert payload["action_request_ref"] == action.request_id
    assert payload["action_type"] == "tool_call"
    assert payload["tool_name"] == "read_file"
    assert payload["operation_id"] == "op.read_file"
    assert payload["read_only"] is True
    assert payload["allowed_tool_names"] == ["read_file"]


def test_action_admission_routes_task_memory_tool_to_task_run() -> None:
    action = ModelActionRequest(
        request_id="model-action:test:memory",
        turn_id="turn:test:memory",
        action_type="tool_call",
        tool_call={"tool_name": "memory_search", "args": {"query": "升级计划"}},
    )

    admission = admit_model_action(
        action,
        packet_allowed_action_types=("respond", "tool_call", "request_task_run", "block"),
        invocation_kind="single_agent_turn",
        definitions_by_name={
            "memory_search": SimpleNamespace(
                operation_id="op.memory_read",
                is_read_only=True,
                contract=SimpleNamespace(owner_scope="task_memory"),
            )
        },
        allowed_tool_names={"memory_search"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
    )

    assert admission.decision == "needs_task_run"
    assert admission.system_reason == "task_scoped_tool_requires_task_run"
    assert admission.permission_delta["required_action"] == "request_task_run"


def test_action_admission_routes_agent_todo_to_task_run() -> None:
    action = ModelActionRequest(
        request_id="model-action:test:agent-todo",
        turn_id="turn:test:agent-todo",
        action_type="tool_call",
        tool_call={"tool_name": "agent_todo", "args": {"action": "start", "items": []}},
    )

    admission = admit_model_action(
        action,
        packet_allowed_action_types=("respond", "tool_call", "request_task_run", "block"),
        invocation_kind="single_agent_turn",
        definitions_by_name={
            "agent_todo": SimpleNamespace(
                operation_id="op.agent_todo",
                is_read_only=False,
                contract=SimpleNamespace(owner_scope="state"),
            )
        },
        allowed_tool_names={"agent_todo"},
        permission_mode="default",
        side_effect_policy="runtime_authorized",
    )

    assert admission.decision == "needs_task_run"
    assert admission.system_reason == "task_scoped_tool_requires_task_run"
    assert admission.permission_delta["operation_id"] == "op.agent_todo"
    assert admission.permission_delta["required_action"] == "request_task_run"


def test_tool_invocation_permit_validation_rejects_mismatched_tool() -> None:
    permit = {
        "permit_id": "action-permit:model-action:test:read",
        "action_request_ref": "model-action:test:read",
        "action_type": "tool_call",
        "decision": "allow",
        "invocation_kind": "agent_turn",
        "tool_name": "read_file",
        "operation_id": "op.read_file",
        "authority": "harness.loop.action_permit",
    }

    reason = validate_tool_invocation_permit(
        action_permit=permit,
        action_request_ref="model-action:test:read",
        invocation_kind="agent_turn",
        tool_name="write_file",
        operation_id="op.write_file",
    )

    assert reason == "action_permit_tool_name_mismatch"
