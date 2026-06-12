from __future__ import annotations

from types import SimpleNamespace

from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response


def test_model_response_protocol_extracts_json_action_candidate() -> None:
    response = SimpleNamespace(
        content='{"action_type":"respond","final_answer":"done"}',
        response_metadata={"finish_reason": "stop"},
        usage_metadata={"output_tokens": 12},
    )

    protocol = model_response_protocol_from_response(
        response,
        request_id="modelreq:one",
        turn_id="turn:one",
        require_json_action=True,
        allow_native_tool_calls=False,
    )

    assert protocol.authority == "runtime.model_gateway.model_response_protocol"
    assert protocol.json_payload["action_type"] == "respond"
    assert protocol.parse_diagnostics["parsed_type"] == "object"
    assert protocol.response_diagnostics["finish_reason"] == "stop"
    assert protocol.response_diagnostics["output_tokens"] == 12
    assert protocol.protocol_errors == ()


def test_model_response_protocol_reports_json_requirement_without_parsing_in_harness() -> None:
    response = SimpleNamespace(content="not json")

    protocol = model_response_protocol_from_response(
        response,
        request_id="modelreq:bad",
        turn_id="turn:bad",
        require_json_action=True,
        allow_native_tool_calls=False,
    )

    assert protocol.json_payload == {}
    assert "json_action_required" in protocol.protocol_errors
    assert protocol.parse_diagnostics["parse_error"]


def test_model_response_protocol_reports_unmounted_native_tool_transport_as_service_boundary() -> None:
    response = SimpleNamespace(
        content="",
        tool_calls=[
            {"id": "call:read", "name": "read_file", "args": {"path": "README.md"}},
        ],
    )

    protocol = model_response_protocol_from_response(
        response,
        request_id="modelreq:native-tool-transport",
        turn_id="turn:native-tool-transport",
        require_json_action=True,
        allow_native_tool_calls=False,
    )

    assert protocol.protocol_errors == ("native_tool_call_transport_not_available",)
