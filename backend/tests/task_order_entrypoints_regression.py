from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import api.task_orders as task_orders_api
from app import app
from query import QueryRuntime
from query.models import QueryRequest
from task_system.registry.flow_registry import TaskFlowRegistry
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
    SingleMessageModelRuntimeStub,
    isolated_backend_root,
)


def _runtime(prefix: str) -> QueryRuntime:
    return QueryRuntime(
        base_dir=isolated_backend_root(prefix),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )


def test_chat_discussion_creates_turn_and_decision_without_order() -> None:
    runtime = _runtime("task-order-chat-boundary-")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-chat-boundary",
                message="我们先讨论一下任务系统设计方案。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    decision_event = next(event for event in events if event.get("type") == "task_intent_decision")
    assert dict(decision_event["decision"])["decision"] == "chat_turn"
    assert runtime.task_run_loop.state_index.list_session_task_orders("session-chat-boundary") == []
    started = next(event for event in events if event.get("type") == "runtime_loop_started")
    task_run_id = str(dict(started["task_run"]).get("task_run_id") or "")
    projection = runtime.task_run_loop.state_index.task_order_projection_for_task_run(task_run_id)
    assert projection is None


def test_chat_specific_task_creates_order_run_channel_and_binds_task_run() -> None:
    runtime = _runtime("task-order-specific-binding-")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-specific-task",
                message="请执行这个前端任务并给出结果。",
                history=[],
                task_selection={"selected_task_id": "task.dev.frontend_ui", "mode": "single_task"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    projection_event = next(event for event in events if event.get("type") == "task_order_projection")
    task_order = dict(projection_event["task_order"])
    assert task_order["order_kind"] == "specific_task"
    assert task_order["task_id"] == "task.dev.frontend_ui"

    started = next(event for event in events if event.get("type") == "runtime_loop_started")
    task_run = dict(started["task_run"])
    diagnostics = dict(task_run.get("diagnostics") or {})
    assert diagnostics["task_order_id"] == task_order["order_id"]
    assert diagnostics["task_order_binding"]["projection_kind"] == "task_order"

    projection = runtime.task_run_loop.state_index.task_order_projection_for_task_run(
        str(task_run.get("task_run_id") or "")
    )
    assert projection["projection_kind"] == "task_order"
    assert projection["task_order"]["order_id"] == task_order["order_id"]
    assert projection["task_order_run"]["task_run_id"] == task_run["task_run_id"]
    assert projection["execution_channel"]["task_run_id"] == task_run["task_run_id"]


def test_task_orders_api_creates_specific_task_order_from_task_library() -> None:
    runtime = _runtime("task-order-api-create-")
    TaskFlowRegistry(runtime.base_dir).upsert_specific_task_record(
        task_id="task.dev.frontend_ui",
        task_title="前端 UI 优化",
        domain_id="domain.development",
        description="优化前端工作台 UI。",
        input_contract_id="WorkspaceTaskInput",
        output_contract_id="AssistantFinalAnswer",
        enabled=True,
    )
    original = task_orders_api.require_runtime
    task_orders_api.require_runtime = lambda: SimpleNamespace(query_runtime=runtime)  # type: ignore[assignment]
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/tasks/orders",
                json={
                    "session_id": "session-task-library",
                    "task_id": "task.dev.frontend_ui",
                    "domain_id": "domain.development",
                    "objective": "优化前端工作台 UI",
                    "source": "task_library",
                },
            )
    finally:
        task_orders_api.require_runtime = original  # type: ignore[assignment]

    assert response.status_code == 200
    payload = response.json()
    assert payload["authority"] == "task_system.task_orders_api"
    assert payload["task_order"]["order_kind"] == "specific_task"
    assert payload["task_order"]["task_id"] == "task.dev.frontend_ui"
    assert payload["task_order_run"]["order_id"] == payload["task_order"]["order_id"]
    assert payload["execution_channel"]["order_run_id"] == payload["task_order_run"]["run_id"]
    assert payload["task_execution_envelope"]["execution_channel_id"] == payload["execution_channel"]["channel_id"]


def test_chat_reuses_precreated_task_order_run_instead_of_duplicate_order() -> None:
    runtime = _runtime("task-order-precreated-reuse-")
    creation = runtime.task_order_factory.create_specific_task_order(
        session_id="session-precreated",
        task_record={
            "task_id": "task.dev.frontend_ui",
            "task_title": "前端 UI 优化",
            "domain_id": "domain.development",
            "description": "优化前端 UI。",
            "enabled": True,
        },
        objective="优化前端 UI",
        source="task_library",
    )
    runtime.task_order_registry.upsert_creation(creation)
    assert creation.order is not None
    assert creation.order_run is not None

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-precreated",
                message="开始执行这个任务。",
                history=[],
                task_selection={
                    "selected_task_id": "task.dev.frontend_ui",
                    "mode": "single_task",
                    "task_order_id": creation.order.order_id,
                    "task_order_run_id": creation.order_run.run_id,
                },
                task_order_intent={
                    "action": "execute_task_order_run",
                    "task_order_id": creation.order.order_id,
                    "task_order_run_id": creation.order_run.run_id,
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    orders = runtime.task_run_loop.state_index.list_session_task_orders("session-precreated")
    assert [item.order_id for item in orders] == [creation.order.order_id]
    projection_event = next(event for event in events if event.get("type") == "task_order_projection")
    assert dict(projection_event["task_order"])["order_id"] == creation.order.order_id
    started = next(event for event in events if event.get("type") == "runtime_loop_started")
    diagnostics = dict(dict(started["task_run"]).get("diagnostics") or {})
    assert diagnostics["task_order_id"] == creation.order.order_id
    assert diagnostics["task_order_run_id"] == creation.order_run.run_id
    assert runtime.task_run_loop.state_index.get_task_order_run(creation.order_run.run_id).status == "completed"


def test_chat_rejects_reusing_consumed_task_order_run() -> None:
    runtime = _runtime("task-order-consumed-reject-")
    creation = runtime.task_order_factory.create_specific_task_order(
        session_id="session-consumed",
        task_record={
            "task_id": "task.dev.frontend_ui",
            "task_title": "前端 UI 优化",
            "domain_id": "domain.development",
            "description": "优化前端 UI。",
            "enabled": True,
        },
        objective="优化前端 UI",
        source="task_library",
    )
    runtime.task_order_registry.upsert_creation(creation)
    assert creation.order is not None
    assert creation.order_run is not None

    async def _collect(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-consumed",
                message=message,
                history=[],
                task_selection={
                    "selected_task_id": "task.dev.frontend_ui",
                    "mode": "single_task",
                    "task_order_id": creation.order.order_id,
                    "task_order_run_id": creation.order_run.run_id,
                },
                task_order_intent={
                    "action": "execute_task_order_run",
                    "task_order_id": creation.order.order_id,
                    "task_order_run_id": creation.order_run.run_id,
                },
            )
        ):
            events.append(event)
        return events

    first_events = asyncio.run(_collect("开始执行这个任务。"))
    assert any(event.get("type") == "runtime_loop_started" for event in first_events)
    assert runtime.task_run_loop.state_index.get_task_order_run(creation.order_run.run_id).status == "completed"

    second_events = asyncio.run(_collect("继续使用同一个运行。"))

    assert not any(event.get("type") == "runtime_loop_started" for event in second_events)
    error = next(event for event in second_events if event.get("type") == "error")
    assert "fail-closed" in str(error.get("error") or "")


def test_chat_rejects_missing_task_order_ref_without_creating_legacy_order() -> None:
    runtime = _runtime("task-order-missing-ref-")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-missing-ref",
                message="开始执行这个任务。",
                history=[],
                task_selection={
                    "selected_task_id": "task.dev.frontend_ui",
                    "mode": "single_task",
                    "task_order_id": "order:specific_task:missing",
                    "task_order_run_id": "orderrun:missing",
                },
                task_order_intent={
                    "action": "execute_task_order_run",
                    "task_order_id": "order:specific_task:missing",
                    "task_order_run_id": "orderrun:missing",
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert runtime.task_run_loop.state_index.list_session_task_orders("session-missing-ref") == []
    error = next(event for event in events if event.get("type") == "error")
    assert "fail-closed" in str(error.get("error") or "")
