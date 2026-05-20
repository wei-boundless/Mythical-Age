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
    if expression.startswith("plan.route="):
        expected = expression.split("=", 1)[1]
        actual = str(result.get("plan_route") or dict(payload.get("plan") or {}).get("route") or "")
        return _pass(expression, actual == expected, actual=actual)
    if expression.startswith("plan.tool="):
        expected = expression.split("=", 1)[1]
        actual = str(result.get("plan_tool") or dict(payload.get("plan") or {}).get("tool") or "")
        return _pass(expression, actual == expected, actual=actual)
    if expression.startswith("plan.mcp="):
        expected = expression.split("=", 1)[1]
        actual = str(result.get("plan_mcp") or dict(payload.get("plan") or {}).get("mcp") or "")
        return _pass(expression, actual == expected, actual=actual)
    if expression.startswith("plan.skill="):
        expected = expression.split("=", 1)[1]
        actual = str(result.get("plan_skill") or dict(payload.get("plan") or {}).get("skill") or "")
        return _pass(expression, actual == expected, actual=actual)
    if expression.startswith("plan.execution_mode="):
        expected = expression.split("=", 1)[1]
        actual = str(result.get("execution_mode") or dict(payload.get("plan") or {}).get("execution_mode") or "")
        return _pass(expression, actual == expected, actual=actual)
    if expression.startswith("plan.bundle_items="):
        expected = _safe_int(expression.split("=", 1)[1])
        actual = int(result.get("bundle_item_count") or dict(payload.get("plan") or {}).get("bundle_item_count") or 0)
        return _pass(expression, actual == expected, actual=actual)
    if expression.startswith("event.tool="):
        expected = expression.split("=", 1)[1]
        tool_names = _tool_names_from_payload(payload)
        return _pass(expression, expected in tool_names, actual=tool_names)
    if expression.startswith("event="):
        expected = expression.split("=", 1)[1]
        event_names = _event_names_from_payload(payload)
        runtime_event_names = [str(item.get("event_type") or "") for item in events]
        return _pass(expression, expected in event_names or expected in runtime_event_names, actual={"events": event_names, "runtime_events": runtime_event_names})
    if expression.startswith("negative.absent_event="):
        expected = expression.split("=", 1)[1]
        event_names = _event_names_from_payload(payload)
        runtime_event_names = [str(item.get("event_type") or "") for item in events]
        return _pass(expression, expected not in event_names and expected not in runtime_event_names, actual={"events": event_names, "runtime_events": runtime_event_names})
    if expression == "evidence.selected.nonempty":
        packet = dict(payload.get("evidence_packet") or {})
        actual = list(packet.get("selected_evidence") or [])
        return _pass(expression, bool(actual), actual=actual[:3])
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


def _event_names_from_payload(payload: dict[str, Any]) -> list[str]:
    names = [
        str(item.get("event") or "")
        for item in list(payload.get("events") or [])
        if isinstance(item, dict) and str(item.get("event") or "")
    ]
    return names


def _tool_names_from_payload(payload: dict[str, Any]) -> list[str]:
    result = dict(payload.get("result") or {})
    names = [str(item) for item in list(result.get("tool_names") or []) if str(item).strip()]
    for event in list(payload.get("events") or []):
        if not isinstance(event, dict):
            continue
        data = dict(event.get("data") or {})
        tool = str(data.get("tool") or "")
        if tool and tool not in names:
            names.append(tool)
    for event in runtime_events_from_turn_payload(payload):
        if str(event.get("event_type") or "") != "tool_call_requested":
            continue
        action_request = dict(dict(event.get("payload") or {}).get("action_request") or {})
        tool = str(dict(action_request.get("payload") or {}).get("tool_name") or "")
        if tool and tool not in names:
            names.append(tool)
    return names


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
