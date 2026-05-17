from __future__ import annotations

from typing import Any

from .contracts import AssertionResult
from .runtime_loop_probe import runtime_events_from_turn_payload, runtime_loop_summary_from_turn_payload


def evaluate_turn_assertions(payload: dict[str, Any], assertions: list[str] | tuple[str, ...]) -> list[AssertionResult]:
    return [evaluate_turn_assertion(payload, assertion) for assertion in assertions]


def evaluate_turn_assertion(payload: dict[str, Any], assertion: str) -> AssertionResult:
    expression = str(assertion or "").strip()
    if not expression:
        return AssertionResult(expression=expression, status="unsupported", reason="empty assertion")
    turn = dict(payload.get("turn") or {})
    result = dict(payload.get("result") or {})
    loop_summary = runtime_loop_summary_from_turn_payload(payload)
    events = runtime_events_from_turn_payload(payload)
    response_text = str(result.get("response_text") or result.get("answer") or _done_content(payload) or "")

    if expression == "response.nonempty":
        return _pass(expression, bool(response_text.strip()), actual=response_text[:160])
    if expression.startswith("response.contains="):
        expected = expression.split("=", 1)[1]
        return _pass(expression, expected in response_text, actual=response_text[:160])
    if expression.startswith("response.contains_any="):
        variants = [item for item in expression.split("=", 1)[1].split("|") if item]
        return _pass(expression, any(item in response_text for item in variants), actual=response_text[:160])
    if expression.startswith("response.contains_all="):
        variants = [item for item in expression.split("=", 1)[1].split("|") if item]
        return _pass(expression, all(item in response_text for item in variants), actual=response_text[:160])
    if expression.startswith("response.not_contains_any="):
        variants = [item for item in expression.split("=", 1)[1].split("|") if item]
        return _pass(expression, not any(item in response_text for item in variants), actual=response_text[:160])
    if expression.startswith("loop.event="):
        expected = expression.split("=", 1)[1]
        actual = [str(item.get("event_type") or "") for item in events]
        return _pass(expression, expected in actual, actual=actual)
    if expression.startswith("loop.tool="):
        expected = expression.split("=", 1)[1]
        actual = list(dict(loop_summary.get("tools") or {}).get("requested") or [])
        return _pass(expression, expected in actual, actual=actual)
    if expression == "loop.completed":
        return _pass(expression, str(loop_summary.get("status") or "") == "completed", actual=loop_summary.get("status"))
    if expression.startswith("loop.terminal_reason="):
        expected = expression.split("=", 1)[1]
        return _pass(expression, str(loop_summary.get("terminal_reason") or "") == expected, actual=loop_summary.get("terminal_reason"))
    if expression == "tool.pairing_ok":
        actual = bool(dict(loop_summary.get("tools") or {}).get("pairing_ok") is True)
        return _pass(expression, actual, actual=dict(loop_summary.get("tools") or {}))
    if expression == "commit.assistant_session=true":
        actual = bool(dict(loop_summary.get("commits") or {}).get("assistant_session_write_applied") is True)
        return _pass(expression, actual, actual=dict(loop_summary.get("commits") or {}))
    if expression == "memory.session_refresh=true":
        actual = bool(dict(loop_summary.get("memory") or {}).get("session_memory_refresh_applied") is True)
        return _pass(expression, actual, actual=dict(loop_summary.get("memory") or {}))
    if expression == "memory.durable_commit=true":
        actual = bool(dict(loop_summary.get("memory") or {}).get("durable_memory_commit_applied") is True)
        return _pass(expression, actual, actual=dict(loop_summary.get("memory") or {}))
    if expression == "task_run.nonempty":
        actual = str(dict(payload.get("result") or {}).get("task_run_id") or "")
        return _pass(expression, bool(actual.strip()), actual=actual)
    if expression == "trace.agent_run_results.nonempty":
        actual = list(dict(payload.get("runtime_trace") or {}).get("artifact_refs") or [])
        result_count = int(dict(payload.get("runtime_trace") or {}).get("agent_run_result_count") or 0)
        return _pass(expression, result_count > 0, actual={"agent_run_result_count": result_count, "artifact_refs": actual})
    if expression == "trace.worker_spawned":
        actual = int(dict(payload.get("runtime_trace") or {}).get("worker_spawn_result_count") or 0)
        return _pass(expression, actual > 0, actual=actual)
    if expression == "trace.coordination.flow_registered":
        actual = int(dict(payload.get("runtime_trace") or {}).get("coordination_run_count") or 0)
        return _pass(expression, actual > 0, actual=actual)
    if expression == "trace.coordination.accepted":
        actual = bool(dict(payload.get("runtime_trace") or {}).get("accepted") is True)
        return _pass(expression, actual, actual=dict(payload.get("runtime_trace") or {}))
    if expression.startswith("trace.coordination.completed_nodes>="):
        expected = int(expression.split(">=", 1)[1])
        actual = int(dict(payload.get("runtime_trace") or {}).get("completed_node_count") or 0)
        return _pass(expression, actual >= expected, actual=actual)
    if expression.startswith("trace.artifact.contains="):
        expected = expression.split("=", 1)[1]
        actual = [str(item) for item in list(dict(payload.get("runtime_trace") or {}).get("artifact_refs") or [])]
        return _pass(expression, any(expected in item for item in actual), actual=actual)

    return AssertionResult(expression=expression, status="unsupported", reason="assertion is not recognized")


def _pass(expression: str, passed: bool, *, actual: Any) -> AssertionResult:
    return AssertionResult(
        expression=expression,
        status="passed" if passed else "failed",
        reason="" if passed else "assertion failed",
        actual=actual,
    )


def _done_content(payload: dict[str, Any]) -> str:
    for item in reversed(list(payload.get("events") or [])):
        if not isinstance(item, dict) or str(item.get("event") or "") != "done":
            continue
        return str(dict(item.get("data") or {}).get("content") or "")
    return ""
