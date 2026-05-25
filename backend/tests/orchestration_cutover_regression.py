from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.assembly.runtime_chain import AgentRuntimeChainAssembler
from query import QueryRuntime
from runtime.shared.stage_projection import StageProjectionCycle
from task_system import TaskFlowRegistry
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
    SingleMessageModelRuntimeStub,
    isolated_backend_root,
    model_turn_context,
)


_MemoryFacadeStub = QueryRuntimeMemoryFacadeStub
_ToolRuntimeStub = EmptyToolRuntimeStub
_SkillRegistryStub = EmptySkillRegistryStub
_SettingsStub = PrimarySettingsStub
_PermissionStub = DefaultPermissionStub
_SessionManagerStub = InMemorySessionManagerStub
_ModelRuntimeStub = SingleMessageModelRuntimeStub


def _isolated_backend_root() -> Path:
    return isolated_backend_root("orchestration-cutover-")


def test_agent_runtime_chain_cutsover_to_formal_orchestration_objects() -> None:
    chain = AgentRuntimeChainAssembler(
        base_dir=BACKEND_DIR,
        memory_facade=_MemoryFacadeStub(),
        skill_registry=_SkillRegistryStub(),
        tool_registry=None,
    )

    payload = chain.build_runtime(
        session_id="session-chain-cutover",
        task_id="taskinst:turn:session-chain-cutover:1:general_response",
        turn_id="turn:session-chain-cutover:1",
        message="读取 docs/系统规划/03-编排系统详细设计书-20260504.md 并总结。",
        source="test",
        task_selection={
            "turn_id": "turn:session-chain-cutover:1",
            **model_turn_context(
                action_intent="read_context",
                work_mode="read_only_analysis",
                interaction_intent="inspect",
                target_objects=["docs/系统规划/03-编排系统详细设计书-20260504.md"],
                desired_outcome="读取文档并总结",
                deliverables=["summary"],
            ),
        },
    )

    task_operation = payload["task_operation"]
    stage_projection = StageProjectionCycle().build_from_orchestration(
        task_id="taskinst:turn:session-chain-cutover:1:general_response",
        task_body_orchestration=dict(payload["task_body_orchestration"]),
        agent_runtime_spec=dict(payload["agent_runtime_spec"]),
    )

    assert "task_body_orchestration" in task_operation
    assert "agent_runtime_spec" in task_operation
    assert "task_prompt_contract" not in task_operation
    assert "prompt_manifest" not in task_operation
    assert "soul_runtime_view" not in task_operation
    assert payload["task_execution_assembly"]["authority"] == "task_system.task_execution_assembly"
    assert payload["task_body_orchestration"]["authority"] == "orchestration.task_body_orchestration"
    assert payload["agent_runtime_spec"]["authority"] == "orchestration.agent_runtime_spec"
    assert stage_projection.task_body_orchestration_ref == payload["task_body_orchestration"]["orchestration_id"]
    assert stage_projection.runtime_spec_ref == payload["agent_runtime_spec"]["runtime_spec_id"]


def test_query_runtime_uses_turn_id_and_task_instance_id_instead_of_turn_task_id() -> None:
    runtime = QueryRuntime(
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

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-runtime-turn-split",
                message="给我一个简短结论",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = next(event for event in events if event["type"] == "runtime_loop_started")
    task_built = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )

    task_run = dict(started["task_run"])
    refs = dict(task_built.get("refs") or {})
    payload = dict(task_built.get("payload") or {})
    orchestration = dict(payload.get("task_body_orchestration") or {})

    assert str(task_run["task_id"]).startswith("taskinst:")
    assert not str(task_run["task_id"]).startswith("turn:")
    assert refs["task_body_orchestration_ref"] == orchestration["orchestration_id"]
    assert refs["agent_runtime_spec_ref"]


def test_runtime_formalizes_worker_spawn_and_coordination_runtime_objects() -> None:
    base_dir = _isolated_backend_root()
    registry = TaskFlowRegistry(base_dir)
    registry.upsert_task_execution_policy(
        task_id="task.dev.light_web_game",
        execution_mode="coordinated_agents",
        default_agent_id="agent:0",
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
        worker_agent_naming_rule="game-worker-{n}",
        notes="runtime formalization test",
    )
    registry.upsert_graph_task(
        graph_id="graph.dev.parallel_game_delivery",
        title="小游戏并行交付",
        coordination_mode="review_merge",
        coordinator_agent_id="agent:0",
        participant_agent_ids=("agent:9",),
        topology_template_id="topology.dev.parallel_game_delivery",
        handoff_policy="structured_handoff",
        output_merge_policy="coordinator_final_merge",
        enabled=True,
    )
    registry.upsert_topology_template(
        template_id="topology.dev.parallel_game_delivery",
        title="小游戏并行交付拓扑",
        nodes=(
            {"node_id": "design_worker", "agent_id": "agent:9", "lane": "game_delivery", "role": "worker_participant"},
            {"node_id": "final_merge", "agent_id": "agent:0", "lane": "final_integration", "role": "coordinator"},
        ),
        edges=(
            {"from": "design_worker", "to": "final_merge", "policy": "structured_handoff"},
        ),
        enabled=True,
    )
    registry.upsert_task_communication_protocol(
        protocol_id="protocol.dev.parallel_game_delivery",
        title="小游戏并行交付协议",
        message_types=("draft_result", "merge_request"),
        payload_contracts=("LightWebGameResult",),
        signal_rules=("worker_to_coordinator",),
        handoff_rules=("structured_handoff",),
        enabled=True,
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
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-worker-coordination",
                message="请开发一个轻量网页小游戏原型。",
                history=[],
                task_selection={
                    "task_id": "task.dev.light_web_game",
                    "task_mode": "light_web_game",
                    "graph_id": "graph.dev.parallel_game_delivery",
                    **model_turn_context(
                        action_intent="delegate",
                        work_mode="delegated",
                        interaction_intent="create",
                        target_objects=["task.dev.light_web_game", "graph.dev.parallel_game_delivery"],
                        desired_outcome="开发轻量网页小游戏原型，并通过已选任务图协调交付。",
                        deliverables=["playable_web_game_prototype", "coordination_trace"],
                        planning_required=True,
                        todo_required=True,
                        task_goal_type="game_vertical_slice_delivery",
                        task_domain="development",
                    ),
                },
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)

    runtime_event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]

    assert trace is not None
    assert "worker_agent_spawn_requested" in runtime_event_types
    assert "worker_agent_spawn_completed" in runtime_event_types
    assert "coordination_node_run_created" in runtime_event_types
    assert "handoff_envelope_created" in runtime_event_types
    assert trace["worker_spawn_requests"]
    assert trace["worker_spawn_results"]
    assert any(item["status"] == "spawned" for item in trace["worker_spawn_results"])
    spawned_agent_id = str(trace["worker_spawn_results"][0]["spawned_agent_id"] or "")
    spawned_agent = AgentRegistry(base_dir).get_agent(spawned_agent_id)
    spawned_profile = AgentRuntimeRegistry(base_dir).get_profile(spawned_agent_id)
    assert spawned_agent is not None
    assert spawned_profile is not None
    assert spawned_profile.runtime_template_id == "worker.dev.prototype"
    assert "game_delivery" in spawned_profile.allowed_runtime_lanes
    assert "op.write_file" in spawned_profile.allowed_operations
    assert "op.edit_file" in spawned_profile.allowed_operations
    assert "op.shell" in spawned_profile.blocked_operations
    assert len(trace["agent_runs"]) >= 2
    assert trace["coordination_runs"]
    assert trace["coordination_runs"][0]["diagnostics"]["coordination_engine"] == "langgraph_runtime"
    assert trace["coordination_runs"][0]["diagnostics"]["coordination_graph_spec"]["valid"] is True
    assert trace["coordination_runs"][0]["node_runs"]
    assert all(node["diagnostics"]["coordination_engine"] == "langgraph_runtime" for node in trace["coordination_runs"][0]["node_runs"])
    assert trace["coordination_runs"][0]["handoff_envelopes"]
    assert all(
        handoff["diagnostics"]["coordination_engine"] == "langgraph"
        for handoff in trace["coordination_runs"][0]["handoff_envelopes"]
    )
    assert trace["coordination_runs"][0]["latest_merge_result"] is not None


def test_runtime_does_not_register_removed_story_pipeline() -> None:
    base_dir = _isolated_backend_root()
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
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-story-coordination",
                message="请用多 Agent 协调模式创作一篇短篇小说。",
                history=[],
                task_selection={
                    "selected_task_id": "task.writing.short_story",
                    "task_id": "task.writing.short_story",
                    "task_mode": "short_story",
                },
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)
    runtime_event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    trace_event_types = [str(item.get("event_type") or "") for item in list(trace.get("events") or [])] if trace is not None else []

    assert trace is not None
    assert "coordination_flow_registered" not in runtime_event_types
    assert "coordination_stage_updated" not in runtime_event_types
    assert "coordination_flow_finalized" not in trace_event_types
    assert trace["agent_run_results"]
    assert trace["coordination_runs"] == []


def test_agent_registry_upsert_preserves_agent_metadata_without_task_scope() -> None:
    base_dir = _isolated_backend_root()
    registry = AgentRegistry(base_dir)

    created = registry.upsert_agent(
        agent_id="agent:knowledge_searcher",
        agent_name="测试工作Agent",
        agent_category="builtin_agent",
        metadata={"created_by": "regression"},
    )

    assert created.metadata["created_by"] == "regression"
    loaded = registry.get_agent("agent:knowledge_searcher")
    assert loaded is not None
    assert loaded.metadata["created_by"] == "regression"

