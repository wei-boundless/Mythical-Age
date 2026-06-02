from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import orchestration_harness as harness_api
from harness.graph.models import safe_id
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from harness.runtime.task_record_lifecycle import (
    TaskRecordLifecycleConflict,
    TaskRecordLifecycleManager,
)
from runtime.shared.models import AgentRun, TaskRun
from tests.graph_harness_api_regression import GRAPH_TEST_SCOPE, _graph, _harness_runtime_with_graph_executor
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph


def test_task_record_lifecycle_deletes_single_task_runtime_records_and_blocks_late_writes(tmp_path: Path) -> None:
    runtime = _harness_runtime_with_graph_executor(base_dir=tmp_path / "backend")
    host = runtime.harness_runtime.single_agent_runtime_host
    session = runtime.session_manager.create_session(title="Task delete", scope=GRAPH_TEST_SCOPE)
    session_id = str(session["id"])
    task_run_id = "taskrun:test-delete-single"
    contract = TaskRunContract(
        contract_id="task-contract:test-delete-single",
        contract_source="test",
        user_visible_goal="删除单条任务记录。",
        task_run_goal="验证单条 TaskRun 清理会删除运行时痕迹。",
        completion_criteria=("记录被清理",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status="running",
        created_at=1.0,
        updated_at=2.0,
    )
    host.runtime_objects.put_object("task_lifecycle", task_run_id, lifecycle.to_dict())
    task_run = TaskRun(
        task_run_id=task_run_id,
        session_id=session_id,
        task_id="task.test.delete.single",
        task_contract_ref=contract_ref,
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1.0,
        updated_at=2.0,
        diagnostics={"executor_status": "running"},
    )
    host.state_index.upsert_task_run(task_run)
    host.state_index.upsert_agent_run(
        AgentRun(
            agent_run_id=f"agrun:{task_run_id}:main",
            task_run_id=task_run_id,
            agent_id="agent:0",
            agent_profile_id="main_interactive_agent",
            status="running",
        )
    )
    host.event_log.append(task_run_id, "test_event", payload={"task_run_id": task_run_id})
    host.active_turn_registry.start(session_id=session_id, turn_id="turn:test-delete", state="running_task")
    host.active_turn_registry.bind_task_run(
        session_id=session_id,
        turn_id="turn:test-delete",
        task_run_id=task_run_id,
        state="running_task",
    )

    result = asyncio.run(TaskRecordLifecycleManager(runtime).delete_task_record(task_run_id))

    assert result["mode"] == "single_task_record"
    assert result["deleted"] is True
    assert host.state_index.get_task_run(task_run_id) is None
    assert host.state_index.list_session_task_runs(session_id) == []
    assert host.state_index.list_recent_task_runs(limit=20) == []
    assert host.state_index.list_task_agent_runs(task_run_id) == []
    assert host.event_log.list_events(task_run_id) == []
    assert host.runtime_objects.get_object(f"rtobj:task_lifecycle:{safe_id(task_run_id)}") == {}
    assert host.active_turn_registry.snapshot(session_id) is None
    host.state_index.upsert_task_run(task_run)
    host.state_index.upsert_agent_run(
        AgentRun(
            agent_run_id=f"agrun:{task_run_id}:late",
            task_run_id=task_run_id,
            agent_id="agent:0",
            agent_profile_id="main_interactive_agent",
        )
    )
    assert host.state_index.get_task_run(task_run_id) is None
    assert host.state_index.list_task_agent_runs(task_run_id) == []


def test_task_record_lifecycle_rejects_graph_node_task_record_delete(tmp_path: Path) -> None:
    runtime = _harness_runtime_with_graph_executor(base_dir=tmp_path / "backend")
    host = runtime.harness_runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="gtask:test-node",
        session_id="session:graph-node",
        task_id="task.graph.node",
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={
            "origin_kind": "graph_node_assigned",
            "graph_run_id": "grun:test",
            "graph_work_order_id": "work:test",
        },
    )
    host.state_index.upsert_task_run(task_run)

    with pytest.raises(TaskRecordLifecycleConflict) as conflict:
        asyncio.run(TaskRecordLifecycleManager(runtime).delete_task_record(task_run.task_run_id))

    assert conflict.value.reason == "graph_node_task_run_controlled_by_graph_runtime"
    assert host.state_index.get_task_run(task_run.task_run_id) is not None


def test_task_record_lifecycle_deletes_graph_root_through_graph_lifecycle(tmp_path: Path) -> None:
    runtime = _harness_runtime_with_graph_executor(base_dir=tmp_path / "backend")
    session = runtime.session_manager.create_session(title="Delete graph root", scope=GRAPH_TEST_SCOPE)
    session_id = str(session["id"])
    graph_config = build_graph_harness_config_from_graph(graph=_graph())
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id=session_id,
        task_id="task.test.graph-root-delete",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=False,
    )
    graph_run_id = started.graph_run.graph_run_id
    task_run_id = started.task_run.task_run_id
    host = runtime.harness_runtime.single_agent_runtime_host
    host.event_log.append(task_run_id, "test_event", payload={"graph_run_id": graph_run_id})

    result = asyncio.run(TaskRecordLifecycleManager(runtime).delete_task_record(task_run_id))

    assert result["mode"] == "graph_root_delegated"
    assert result["graph_run_id"] == graph_run_id
    assert runtime.harness_runtime.graph_harness.get_graph_run(graph_run_id) is None
    assert host.state_index.get_task_run(task_run_id) is None
    assert host.event_log.list_events(task_run_id) == []
    host.state_index.upsert_task_run(started.task_run)
    assert host.state_index.get_task_run(task_run_id) is None


def test_delete_harness_task_run_api_uses_task_record_lifecycle(tmp_path: Path) -> None:
    runtime = _harness_runtime_with_graph_executor(base_dir=tmp_path / "backend")
    host = runtime.harness_runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:api-delete",
        session_id="session:api-delete",
        task_id="task.api.delete",
        execution_runtime_kind="single_agent_task",
        status="completed",
    )
    host.state_index.upsert_task_run(task_run)

    original = harness_api.require_runtime
    harness_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        result = asyncio.run(harness_api.delete_harness_task_run(task_run.task_run_id))
        with pytest.raises(HTTPException) as not_found:
            asyncio.run(harness_api.delete_harness_task_run(task_run.task_run_id))
    finally:
        harness_api.require_runtime = original  # type: ignore[assignment]

    assert result["deleted"] is True
    assert result["task_run_id"] == task_run.task_run_id
    assert not_found.value.status_code == 404
