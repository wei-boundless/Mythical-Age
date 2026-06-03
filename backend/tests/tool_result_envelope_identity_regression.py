from __future__ import annotations

import runtime.output_boundary as output_boundary
from runtime.output_boundary.output_models import ToolVisibleOutputEnvelope
from runtime.tool_runtime.tool_result_envelope import ToolResultEnvelope, build_tool_result_envelope


def test_tool_result_envelope_name_is_reserved_for_tool_runtime_protocol() -> None:
    assert ToolResultEnvelope.__module__ == "runtime.tool_runtime.tool_result_envelope"
    assert not hasattr(output_boundary, "ToolResultEnvelope")
    assert ToolVisibleOutputEnvelope.__name__ == "ToolVisibleOutputEnvelope"


def test_tool_result_envelope_identity_is_stable_for_same_tool_call() -> None:
    first = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "README.md"},
        result={"text": "first", "structured_payload": {}},
        tool_call_id="call:read",
        action_request_id="action:read",
        caller_kind="task_run",
        caller_ref="taskrun:one",
    )
    second = build_tool_result_envelope(
        tool_name="read_file",
        tool_args={"path": "README.md", "line_count": 20},
        result={"text": "second", "structured_payload": {}},
        tool_call_id="call:read",
        action_request_id="action:read",
        caller_kind="task_run",
        caller_ref="taskrun:one",
    )

    assert first.idempotency_key == second.idempotency_key
    assert first.envelope_id == second.envelope_id
    assert first.envelope_id.startswith("tool-result:")
