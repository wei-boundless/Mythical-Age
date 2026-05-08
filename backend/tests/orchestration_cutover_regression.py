from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.agent_registry import AgentRegistry
from orchestration import AgentRuntimeChainAssembler, StageProjectionCycle
from query import QueryRuntime
from tasks import TaskFlowRegistry


class _MemoryFacadeStub:
    session_memory = SimpleNamespace(manager=lambda _session_id: SimpleNamespace(load_state=lambda: None))

    def build_memory_context_package(self, *_args, **_kwargs):
        return None

    def build_memory_runtime_view(self, *_args, **_kwargs):
        return {"view_id": "memview:test", "state_snapshot": {}}

    def refresh_session_memory(self, *_args, **_kwargs):
        return ""

    def commit_durable_memory_extraction(self, *_args, **_kwargs):
        return 0


class _ToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_definition(self, _name):
        return None


class _SkillRegistryStub:
    skills = []


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return False

    def get_orchestration_plan_mode(self) -> str:
        return "primary"


class _PermissionStub:
    def current_mode(self) -> str:
        return "default"

    def supported_modes(self) -> list[str]:
        return ["default"]


class _ModelRuntimeStub:
    async def invoke_messages(self, _messages):
        return SimpleNamespace(content="单轮收口回答")


class _SessionManagerStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages)}

    def load_session_for_agent(self, _session_id, *, include_compressed_context: bool = False):
        return list(self.messages)

    def load_session(self, _session_id):
        return list(self.messages)

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)
        return list(messages)


def _isolated_backend_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="orchestration-cutover-")) / "backend"
    root.mkdir(parents=True, exist_ok=True)
    return root


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
        task_selection={"turn_id": "turn:session-chain-cutover:1"},
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
    registry.upsert_task_agent_adoption_plan(
        task_id="task.dev.light_web_game",
        adoption_mode="adopt_with_projection",
        default_agent_id="agent:0",
        allowed_agent_categories=("main_agent", "worker_sub_agent"),
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
        worker_agent_naming_rule="game-worker-{n}",
        notes="runtime formalization test",
    )
    registry.upsert_coordination_task(
        coordination_task_id="coord.dev.parallel_game_delivery",
        title="小游戏并行交付",
        coordination_mode="review_merge",
        coordinator_agent_id="agent:0",
        participant_agent_ids=("agent:6",),
        topology_template_id="topology.dev.parallel_game_delivery",
        handoff_policy="structured_handoff",
        output_merge_policy="coordinator_final_merge",
        enabled=True,
    )
    registry.upsert_topology_template(
        template_id="topology.dev.parallel_game_delivery",
        title="小游戏并行交付拓扑",
        nodes=(
            {"node_id": "design_worker", "agent_id": "agent:6", "lane": "game_delivery", "role": "worker_participant"},
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
                    "coordination_task_id": "coord.dev.parallel_game_delivery",
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
    assert spawned_agent is not None
    assert "main_agent" not in spawned_agent.task_scope
    assert "worker_sub_agent" not in spawned_agent.task_scope
    assert "light_web_game" in spawned_agent.task_scope
    assert len(trace["agent_runs"]) >= 2
    assert trace["coordination_runs"]
    assert trace["coordination_runs"][0]["diagnostics"]["coordination_engine"] == "langgraph"
    assert trace["coordination_runs"][0]["diagnostics"]["coordination_graph_spec"]["valid"] is True
    assert trace["coordination_runs"][0]["node_runs"]
    assert all(node["diagnostics"]["coordination_engine"] == "langgraph" for node in trace["coordination_runs"][0]["node_runs"])
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


def test_agent_registry_upsert_preserves_explicit_task_scope_for_new_agent() -> None:
    base_dir = _isolated_backend_root()
    registry = AgentRegistry(base_dir)

    created = registry.upsert_agent(
        agent_id="agent:6",
        agent_name="测试工作Agent",
        agent_category="worker_sub_agent",
        task_scope=("light_web_game", "bounded_patch"),
        metadata={"created_by": "regression"},
    )

    assert created.task_scope == ("light_web_game", "bounded_patch")
    loaded = registry.get_agent("agent:6")
    assert loaded is not None
    assert loaded.task_scope == ("light_web_game", "bounded_patch")
