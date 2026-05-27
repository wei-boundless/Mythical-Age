from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness import AgentHarness, AgentRunRequest, GraphHarness
from harness.runtime import CoordinationStageAgentRunRequest
from query import QueryRuntime
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


def test_query_runtime_exposes_graph_harness_facade() -> None:
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

    assert isinstance(runtime.agent_harness, AgentHarness)
    assert isinstance(runtime.graph_harness, GraphHarness)
    assert not hasattr(runtime, "agent_runtime")
    assert not hasattr(runtime, "graph_task_runtime")
    assert runtime.runtime_components["agent_harness"] == "active"
    assert runtime.runtime_components["graph_harness"] == "active"
    assert "agent_runtime" not in runtime.runtime_components
    assert "graph_task_runtime" not in runtime.runtime_components
    assert not hasattr(runtime.graph_harness, "coordination_runtime")
    assert runtime.graph_harness.graph_loop.checkpoints is runtime.harness_service_host.graph_coordination_engine.checkpoints


def test_graph_harness_can_be_instantiated_with_agent_harness() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("graph-task-runtime-legacy-alias-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )

    graph_harness = GraphHarness(service_host=runtime.harness_service_host, agent_harness=runtime.agent_harness)

    assert isinstance(graph_harness, GraphHarness)
    assert not hasattr(graph_harness, "coordination_runtime")
    assert graph_harness.graph_loop.checkpoints is runtime.harness_service_host.graph_coordination_engine.checkpoints


def test_graph_harness_chains_coordination_continuation_through_agent_runtime() -> None:
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

    runtime.agent_harness.run_stream = _agent_stream  # type: ignore[method-assign]

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.graph_harness.run_coordination_stage_stream(
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
