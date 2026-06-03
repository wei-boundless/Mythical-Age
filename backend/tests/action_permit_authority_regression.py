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
