from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration import AgentRuntimeChainAssembler, StageProjectionCycle
from query import QueryRuntime
from tasks import TaskCoordinator


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
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
        task_coordinator=TaskCoordinator(),
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
