from __future__ import annotations

import asyncio

from orchestration import ResourcePolicy, OperationGatePipelineContext
from orchestration.runtime_loop.safety import build_task_safety_validators
from query.models import QueryRequest
from tasks import TaskFlowRegistry

from tests.query_runtime_runtime_loop_regression import (
    _build_arcade_bundle_runtime,
    _build_game_generation_runtime,
    _build_stream_runtime,
    _isolated_backend_root,
)


def _runtime_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]


def _event_payload(events: list[dict[str, object]], event_type: str) -> dict[str, object]:
    event = next(item for item in _runtime_events(events) if item.get("event_type") == event_type)
    return dict(event.get("payload") or {})


def _task_run_id(events: list[dict[str, object]]) -> str:
    started = next(event for event in events if event["type"] == "runtime_loop_started")
    return str(dict(started["task_run"]).get("task_run_id") or "")


def test_acceptance_single_agent_chain_has_formal_frontend_backend_runtime_evidence() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="acceptance-single-agent-chain",
                message="给我一个简短结论：这个项目当前任务系统边界是什么？",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    task_contract = _event_payload(events, "task_contract_built")
    assembly = dict(task_contract.get("task_execution_assembly") or {})
    policy = dict(task_contract.get("task_execution_policy") or {})
    agent_runtime_spec = dict(task_contract.get("agent_runtime_spec") or {})
    done = next(event for event in events if event["type"] == "done")

    assert assembly["authority"] == "task_system.task_execution_assembly"
    assert assembly["execution_chain_type"] == "single_agent_chain"
    assert "selected_agent_id" not in assembly
    assert policy["authority"] == "task_system.task_execution_policy"
    assert agent_runtime_spec["authority"] == "orchestration.agent_runtime_spec"
    assert agent_runtime_spec["agent_id"]
    assert done["answer_source"]


def test_acceptance_specific_development_task_carries_workflow_projection_memory_and_safety(tmp_path) -> None:
    runtime = _build_arcade_bundle_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="acceptance-specific-dev-task",
                message="生成一个包含开始界面、游戏脚本和样式文件的网页小游戏包",
                history=[],
                task_selection={"selected_task_id": "task.dev.arcade_game_bundle"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    task_contract = _event_payload(events, "task_contract_built")
    assembly = dict(task_contract.get("task_execution_assembly") or {})
    policy = dict(task_contract.get("task_execution_policy") or {})
    memory_profile = dict(task_contract.get("task_memory_request_profile") or {})
    projection_binding = dict(task_contract.get("task_projection_binding") or {})
    flow_binding = dict(task_contract.get("task_flow_contract_binding") or {})
    directive = next(event for event in events if event["type"] == "runtime_directive")
    bundle_root = tmp_path / "frontend" / "public" / "games" / "arcade_bundle"

    assert assembly["execution_chain_type"] == "single_agent_chain"
    assert policy["task_id"] == "task.dev.arcade_game_bundle"
    assert policy["authority"] == "task_system.task_execution_policy"
    assert memory_profile["task_id"] == "task.dev.arcade_game_bundle"
    assert projection_binding["task_id"] == "task.dev.arcade_game_bundle"
    assert flow_binding["task_id"] == "task.dev.arcade_game_bundle"
    assert "op.write_file" in directive["resource_policy"]["allowed_operations"]
    assert (bundle_root / "index.html").exists()
    assert (bundle_root / "style.css").exists()
    assert (bundle_root / "game.js").exists()

    gate_result = runtime.task_run_loop.operation_gate.check(
        "op.write_file",
        resource_policy=ResourcePolicy(
            policy_id="respol:acceptance:arcade",
            task_id="task.dev.arcade_game_bundle",
            allowed_operations=("op.write_file",),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        directive_ref="runtime-directive:acceptance",
        context=OperationGatePipelineContext(
            operation_input={"path": "backend/unsafe.py", "content": "print('blocked')"},
            validators=build_task_safety_validators(
                root_dir=tmp_path,
                safety_envelope={
                    "safety_class": "S1_bounded_artifact_write",
                    "write_mode": "bounded_create",
                    "write_roots": ["frontend/public/games/arcade_bundle"],
                    "forbidden_paths": ["backend", "storage", ".env"],
                },
            ),
        ),
    )
    assert gate_result.allowed is False


def test_acceptance_coordination_chain_creates_traceable_formal_objects() -> None:
    from types import SimpleNamespace
    from tests.query_runtime_runtime_loop_regression import _ModelRuntimeStub, _MemoryFacadeStub, _PermissionStub, _SessionManagerStub, _SettingsStub, _SkillRegistryStub, _ToolRuntimeStub
    from query import QueryRuntime

    class _StoryModelRuntimeStub(_ModelRuntimeStub):
        async def invoke_messages(self, messages):
            self.messages = list(messages)
            return SimpleNamespace(
                content=(
                    "《雨后的灯塔》\n\n"
                    "雨停在黄昏前。林岚带着修好的小型信标爬上旧灯塔时，海面像一张刚刚展平的蓝纸。"
                    "镇上的人都说这座灯塔早已无用，因为新的导航系统接管了一切，可她知道，昨夜那艘失联的小船仍在等待一个能被看见的方向。\n\n"
                    "她接上线圈，灯芯却只闪了一下。身后的审核员周澈翻看记录，指出备用电池的接地线仍有风险。"
                    "林岚沉默片刻，拆下自己的手电，把电芯并入临时回路。第二次点火时，白光穿过雨后的雾，像有人在黑暗里慢慢推开一扇门。\n\n"
                    "半小时后，小船回港。船长说他们看到的不是最亮的光，却是唯一按固定节奏闪烁的光。"
                    "林岚在验收表上写下结论：旧系统可以退场，但在新系统沉默时，仍要留一盏能被人理解的灯。\n\n"
                    "验收结果：通过。"
                )
            )

    base_dir = _isolated_backend_root()
    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=object(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_StoryModelRuntimeStub(),
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="acceptance-coordination-chain",
                message="用多 Agent 协调模式创作一篇短篇小说，并经历创意、审核、编写、纠察、验收。",
                history=[],
                task_selection={
                    "selected_task_id": "task.writing.short_story",
                    "task_id": "task.writing.short_story",
                    "task_mode": "short_story",
                    "coordination_task_id": "coord.writing.short_story_pipeline",
                    "communication_protocol_id": "protocol.writing.short_story_pipeline",
                },
            )
        ):
            events.append(event)
        return events, _task_run_id(events)

    events, task_run_id = asyncio.run(_collect())
    task_contract = _event_payload(events, "task_contract_built")
    assembly = dict(task_contract.get("task_execution_assembly") or {})
    done = next(event for event in events if event["type"] == "done")
    trace = runtime.task_run_loop.get_trace(task_run_id)

    assert assembly["execution_chain_type"] == "coordination_chain"
    assert assembly["coordination_task_ref"] == "coord.writing.short_story_pipeline"
    assert assembly["communication_protocol_ref"] == "protocol.writing.short_story_pipeline"
    assert trace is not None
    assert trace["coordination_runs"]
    coordination_run = trace["coordination_runs"][0]
    assert coordination_run["coordination_task_ref"] == "coord.writing.short_story_pipeline"
    assert coordination_run["node_runs"]
    assert coordination_run["handoff_envelopes"]
    assert coordination_run["latest_merge_result"] is not None
    assert trace["agent_run_results"]
    assert "《雨后的灯塔》" in str(done["content"])
    assert "验收结果：通过" in str(done["content"])


def test_acceptance_worker_spawn_allows_and_fail_closes_by_execution_policy() -> None:
    from tests.query_runtime_runtime_loop_regression import _ModelRuntimeStub, _MemoryFacadeStub, _PermissionStub, _SessionManagerStub, _SettingsStub, _SkillRegistryStub, _ToolRuntimeStub
    from query import QueryRuntime

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
        notes="acceptance worker spawn",
    )
    registry.upsert_coordination_task(
        coordination_task_id="coord.dev.acceptance_worker_spawn",
        title="worker spawn 验收协调链",
        coordination_mode="review_merge",
        coordinator_agent_id="agent:0",
        participant_agent_ids=("agent:6",),
        topology_template_id="topology.dev.acceptance_worker_spawn",
        handoff_policy="structured_handoff",
        output_merge_policy="coordinator_final_merge",
        enabled=True,
    )
    registry.upsert_topology_template(
        template_id="topology.dev.acceptance_worker_spawn",
        title="worker spawn 验收拓扑",
        nodes=(
            {"node_id": "worker_lane", "agent_id": "agent:6", "lane": "game_delivery", "role": "worker_participant"},
            {"node_id": "merge_lane", "agent_id": "agent:0", "lane": "final_integration", "role": "coordinator"},
        ),
        edges=({"from": "worker_lane", "to": "merge_lane", "policy": "structured_handoff"},),
        enabled=True,
    )
    registry.upsert_task_communication_protocol(
        protocol_id="protocol.dev.acceptance_worker_spawn",
        title="worker spawn 验收协议",
        message_types=("draft_result", "final_merge_request"),
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
        retrieval_service=object(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )

    async def _collect_allowed() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="acceptance-worker-spawn-allowed",
                message="开发一个轻量网页小游戏。",
                history=[],
                task_selection={
                    "task_id": "task.dev.light_web_game",
                    "task_mode": "light_web_game",
                    "coordination_task_id": "coord.dev.acceptance_worker_spawn",
                    "communication_protocol_id": "protocol.dev.acceptance_worker_spawn",
                },
            )
        ):
            events.append(event)
        return events, _task_run_id(events)

    allowed_events, allowed_task_run_id = asyncio.run(_collect_allowed())
    allowed_trace = runtime.task_run_loop.get_trace(allowed_task_run_id)
    allowed_event_types = [item.get("event_type") for item in _runtime_events(allowed_events)]

    assert "worker_agent_spawn_requested" in allowed_event_types
    assert "worker_agent_spawn_completed" in allowed_event_types
    assert allowed_trace is not None
    assert allowed_trace["worker_spawn_requests"]
    assert allowed_trace["worker_spawn_results"][0]["status"] == "spawned"

    registry.upsert_task_agent_adoption_plan(
        task_id="task.dev.light_web_game",
        adoption_mode="adopt_with_projection",
        default_agent_id="agent:0",
        allowed_agent_categories=("main_agent",),
        allow_worker_agent_spawn=False,
        worker_agent_blueprint_id="",
        worker_agent_naming_rule="",
        notes="acceptance worker spawn disabled",
    )

    async def _collect_denied() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="acceptance-worker-spawn-denied",
                message="开发一个轻量网页小游戏。",
                history=[],
                task_selection={
                    "task_id": "task.dev.light_web_game",
                    "task_mode": "light_web_game",
                    "coordination_task_id": "coord.dev.acceptance_worker_spawn",
                    "communication_protocol_id": "protocol.dev.acceptance_worker_spawn",
                },
            )
        ):
            events.append(event)
        return events, _task_run_id(events)

    denied_events, denied_task_run_id = asyncio.run(_collect_denied())
    denied_trace = runtime.task_run_loop.get_trace(denied_task_run_id)
    denied_event_types = [item.get("event_type") for item in _runtime_events(denied_events)]

    assert "worker_agent_spawn_requested" not in denied_event_types
    assert denied_trace is not None
    assert denied_trace["worker_spawn_requests"] == []
