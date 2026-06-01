from __future__ import annotations

from capability_system.tools.tool_units.fetch_url_tool import FetchURLToolError
from harness.loop.observations import build_observation_record, structured_error_from_exception
from harness.loop.task_executor import _structured_error_from_observation


def test_fetch_url_structured_error_survives_observation_pipeline() -> None:
    exc = FetchURLToolError(
        "Fetch failed for https://example.invalid/rss.xml: HTTP 404",
        code="http_status_error",
        retryable=False,
        status_code=404,
    )
    structured_error = structured_error_from_exception(exc)
    observation = build_observation_record(
        source="tool:fetch_url",
        packet_ref="packet:test",
        payload={
            "tool_name": "fetch_url",
            "tool_args": {"url": "https://example.invalid/rss.xml"},
            "structured_error": structured_error,
        },
        error=str(exc),
    ).to_dict()

    assert structured_error == {
        "code": "http_status_error",
        "message": "Fetch failed for https://example.invalid/rss.xml: HTTP 404",
        "retryable": False,
        "origin": "tool_provider",
        "status_code": 404,
    }
    assert _structured_error_from_observation(observation) == {
        "code": "http_status_error",
        "message": "Fetch failed for https://example.invalid/rss.xml: HTTP 404",
        "retryable": False,
        "origin": "tool_provider",
    }
