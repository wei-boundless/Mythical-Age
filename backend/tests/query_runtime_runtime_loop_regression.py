from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.models import QueryRequest
from tests.support.runtime_stubs import (
    SingleMessageModelRuntimeStub,
    build_query_runtime,
)


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    task_contract_seed: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "authority": "agent_runtime.agent_turn_action_request",
        "request_id": f"agent-turn-action:test:{action_type}",
        "turn_id": "",
        "action_type": action_type,
        "final_answer": final_answer,
        "task_contract_seed": dict(task_contract_seed or {}),
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {"test_action_request": True},
    }


def test_direct_agent_response_does_not_start_task_run() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="直接回答，不进入任务生命周期。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-direct", message="介绍一下 harness。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "done" for event in events)
    assert not any(event.get("type") == "harness_run_started" for event in events)
    assert runtime.harness_service_host.list_session_traces("session-direct")["task_run_count"] == 0


def test_agent_action_request_launches_task_run_and_initializes_todo() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={
                    "goal": "交付一个真实可验证产物。",
                    "task_goal_type": "artifact_delivery",
                    "deliverables": ["artifact_refs", "verification_evidence"],
                    "required_actions": ["apply_real_change", "run_verification"],
                },
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-taskrun", message="请交付产物。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    started = next(event for event in events if event.get("type") == "harness_run_started")
    task_run_id = str(dict(started.get("task_run") or {}).get("task_run_id") or "")
    trace = runtime.harness_service_host.get_trace(task_run_id, include_payloads=True)
    event_types = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(trace or {}).get("events") or [])
    ]
    agent_turn_events = [
        str(dict(event.get("event") or {}).get("event_type") or "")
        for event in events
        if event.get("type") == "agent_turn_event"
    ]

    assert "agent_turn_action_request_started" in agent_turn_events
    assert "agent_turn_action_request_completed" in agent_turn_events
    assert "task_run_launch_requested" in agent_turn_events
    assert "agent_todo_initialized" in event_types


def test_invalid_agent_action_request_reports_error_without_task_run() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request={
                "authority": "agent_runtime.agent_turn_action_request",
                "request_id": "agent-turn-action:test:invalid",
                "turn_id": "",
                "action_type": "request_task_run",
                "task_contract_seed": {},
            }
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-invalid", message="请执行。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "error" for event in events)
    assert not any(event.get("type") == "harness_run_started" for event in events)


class _MalformedModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(content=json.dumps({"authority": "bad"}))


def test_malformed_agent_action_request_fails_closed() -> None:
    runtime = build_query_runtime(model_runtime=_MalformedModelRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-malformed", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "error" for event in events)
    assert not any(event.get("type") == "harness_run_started" for event in events)
