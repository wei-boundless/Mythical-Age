from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
from query.models import QueryRequest
from tasks import TaskFlowRegistry

from tests.orchestration_cutover_regression import (
    _MemoryFacadeStub,
    _ModelRuntimeStub,
    _PermissionStub,
    _SessionManagerStub,
    _SettingsStub,
    _SkillRegistryStub,
    _ToolRuntimeStub,
    _isolated_backend_root,
)


def _build_stream_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=_isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )


def _build_game_generation_runtime() -> QueryRuntime:
    return _build_stream_runtime()


def _build_arcade_bundle_runtime(_tmp_path: Path) -> QueryRuntime:
    return _build_stream_runtime()


def test_astream_specific_light_web_game_task_can_write_new_file(tmp_path: Path) -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-light-game",
                message="请生成一个可运行的轻量网页小游戏。",
                history=[],
                task_selection={"selected_task_id": "task.dev.light_web_game"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "done" for event in events)
    assert any(
        dict(event.get("event") or {}).get("event_type") == "task_contract_built"
        for event in events
        if event.get("type") == "runtime_loop_event"
    )


def test_runtime_trace_exposes_worker_spawn_trace_for_light_web_game(tmp_path: Path) -> None:
    base_dir = _isolated_backend_root()
    registry = TaskFlowRegistry(base_dir)
    registry.upsert_task_agent_adoption_plan(
        task_id="task.dev.light_web_game",
        adoption_mode="adopt_with_projection",
        default_agent_id="agent:0",
        allowed_agent_categories=("main_agent", "worker_sub_agent"),
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
        worker_agent_naming_rule="game-worker-{n}",
        notes="trace regression",
    )
    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-trace-light-game",
                message="请开发一个轻量网页小游戏原型。",
                history=[],
                task_selection={"selected_task_id": "task.dev.light_web_game", "task_mode": "light_web_game"},
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    trace = runtime.task_run_loop.get_trace(task_run_id)
    event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]

    assert trace is not None
    assert "worker_agent_spawn_requested" in event_types
    assert "worker_agent_spawn_completed" in event_types
    assert trace["worker_spawn_requests"]
    assert trace["worker_spawn_results"]


def test_delegate_mode_template_skips_legacy_template_mcp_phase() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-delegate-phase",
                message="请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的核心结论。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    built_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )
    payload = dict(built_event.get("payload") or {})
    assert str(dict(payload.get("selected_recipe") or {}).get("template_id") or "") == "template.pdf.document_analysis"

    assert "mcp_start" not in event_types


def test_terminal_state_index_failure_still_yields_done() -> None:
    runtime = _build_stream_runtime()

    def _raise_state_index_failure(*_args, **_kwargs):
        raise PermissionError("simulated state_index replace failure")

    runtime.task_run_loop._upsert_finished_task_run = _raise_state_index_failure  # type: ignore[method-assign]

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-state-index-degraded",
                message="请给我一个值班提示。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done_event = next(event for event in events if event.get("type") == "done")

    assert not any(event.get("type") == "error" for event in events)
    assert done_event.get("content") == "单轮收口回答"
    output_commit = dict(done_event.get("output_commit") or {})
    assert output_commit["state_index_degraded"] is True
    assert dict(done_event.get("runtime_state_index") or {})["phase"] == "finished_task_run_state_write"
