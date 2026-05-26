from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
from runtime import AgentRunRequest, GraphTaskRuntime
from runtime.graph_task_runtime import CoordinationStageAgentRunRequest
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


def test_query_runtime_exposes_graph_task_runtime_facade() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("graph-task-runtime-facade-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )

    assert isinstance(runtime.graph_task_runtime, GraphTaskRuntime)
    assert runtime.runtime_components["graph_task_runtime"] == "active"
    assert runtime.graph_task_runtime.coordination_runtime is runtime.task_run_loop.langgraph_coordination_runtime


def test_graph_task_runtime_chains_coordination_continuation_through_agent_runtime() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("graph-task-runtime-continuation-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )
    captured_task_ids: list[str] = []

    async def _agent_stream(request: AgentRunRequest):
        captured_task_ids.append(request.task_id)
        if len(captured_task_ids) == 1:
            yield {
                "type": "done",
                "content": "first stage",
                "coordination_continuation": {
                    "next_task_ref": "task.dev.second",
                    "message": "继续第二节点。",
                    "suppress_done": True,
                },
            }
        else:
            yield {
                "type": "done",
                "content": "second stage",
            }

    runtime.agent_runtime.run_stream = _agent_stream  # type: ignore[method-assign]

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.graph_task_runtime.run_coordination_stage_stream(
            CoordinationStageAgentRunRequest(
                session_id="session-graph-continuation",
                history=[],
                source="regression",
                agent_runtime_chain=runtime.agent_runtime_chain,
                model_response_executor=runtime.model_response_executor,
                runtime_context_manager=runtime.runtime_context_manager,
                continuation_payload={
                    "next_task_ref": "task.dev.first",
                    "message": "执行第一节点。",
                    "suppress_done": True,
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert len(captured_task_ids) == 2
    assert captured_task_ids[0].endswith(":first")
    assert captured_task_ids[1].endswith(":second")
    assert events == []
