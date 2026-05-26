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
from query.runtime import _task_selection_for_runtime
from runtime.agent_assembly import NodeWorkOrder, build_agent_invocation
from runtime.unit_runtime.finalizer import FinishedTaskRunResult
from task_system import TaskFlowRegistry
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
    SingleMessageModelRuntimeStub,
    StreamingMessageModelRuntimeStub,
    isolated_backend_root,
)
from task_system.orders.models import ConversationTurn, TaskIntentDecision, TaskOrder, TaskExecutionEnvelope
from task_system.orders.order_factory import TaskOrderCreation


class _FailingDecisionModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        raise RuntimeError("simulated provider unavailable")


def _build_stream_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-loop-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )


def _build_game_generation_runtime() -> QueryRuntime:
    return _build_stream_runtime()


def _build_arcade_bundle_runtime(_tmp_path: Path) -> QueryRuntime:
    return _build_stream_runtime()


def _main_agent_mode_task_selection(
    *,
    interaction_mode: str,
    runtime_lane: str,
    recipe_id: str,
    professional: bool = False,
) -> dict[str, object]:
    mode_policy: dict[str, object] = {
        "interaction_mode": interaction_mode,
        "runtime_lane": runtime_lane,
        "recipe_id": recipe_id,
    }
    if professional:
        mode_policy["execution_strategy"] = "professional_task_run"
    return {
        "agent_id": "agent:0",
        "agent_profile_id": "main_interactive_agent",
        "interaction_mode": interaction_mode,
        "runtime_interaction_mode": interaction_mode,
        "runtime_lane": runtime_lane,
        "mode_policy": mode_policy,
    }


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


def test_run_single_agent_stream_emits_stream_delta_once() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-stream-dedup-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=StreamingMessageModelRuntimeStub(chunks=["final answer：流式片段"]),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.task_run_loop.run_single_agent_stream(
            session_id="session-stream-dedup",
            task_id="taskinst:session-stream-dedup:general",
            user_message="请流式回答。",
            history=[],
            source="regression",
            agent_runtime_chain=runtime.agent_runtime_chain,
            model_response_executor=runtime.model_response_executor,
            runtime_context_manager=runtime.runtime_context_manager,
            task_selection={
                "turn_id": "turn:session-stream-dedup:1",
                "stream_policy": {"enabled": True, "mode": "model_text_stream"},
            },
            tool_runtime_executor=runtime.tool_runtime_executor,
            tool_instances=runtime._all_tool_instances(),
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    deltas = [
        event
        for event in events
        if event.get("type") == "content_delta" and event.get("content") == "final answer：流式片段"
    ]

    assert len(deltas) == 1
    assert any(event.get("type") == "done" for event in events)


def test_query_runtime_assembles_compressed_context_before_model_history() -> None:
    session_manager = InMemorySessionManagerStub()
    session_manager.compressed_context = "旧历史已经压缩为项目审查摘要。"
    session_manager.messages = [
        {"role": "user", "content": f"old-{index}"}
        for index in range(14)
    ]
    model_runtime = SingleMessageModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-history-assembly-"),
        settings_service=PrimarySettingsStub(),
        session_manager=session_manager,
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=model_runtime,
    )

    captured_history: list[dict[str, object]] = []
    original_run = runtime.task_run_loop.run_single_agent_stream

    async def _capture(**kwargs):
        captured_history.extend(list(kwargs.get("history") or []))
        if False:
            yield {}
        return

    runtime.task_run_loop.run_single_agent_stream = _capture  # type: ignore[method-assign]

    async def _collect() -> None:
        async for _event in runtime.astream(
            QueryRequest(
                session_id="session-history-assembly",
                message="继续",
                history=[],
            )
        ):
            pass

    try:
        asyncio.run(_collect())
    finally:
        runtime.task_run_loop.run_single_agent_stream = original_run  # type: ignore[method-assign]

    assert captured_history[0]["role"] == "assistant"
    assert "旧历史已经压缩为项目审查摘要" in str(captured_history[0]["content"])
    assert [item["content"] for item in captured_history[1:]] == [f"old-{index}" for index in range(2, 14)]


def test_runtime_task_selection_preserves_order_projection_resource_contract() -> None:
    projected_selection = {
        "interaction_mode": "professional_mode",
        "resource_contract": {
            "source_projects": [
                {"path": "D:/AI应用/agent-vibe-sandboxes/langchain-mini-clean", "role": "source"}
            ]
        },
        "sandbox_policy": {"enabled": True, "workspace_key": "langchain-mini-clean-agent-smoke"},
    }
    creation = TaskOrderCreation(
        conversation_turn=ConversationTurn(turn_id="turn:session:1", session_id="session"),
        intent_decision=TaskIntentDecision(
            decision_id="intent:turn:1",
            turn_id="turn:session:1",
            decision="executable_task",
        ),
        order=TaskOrder(
            order_id="order:test",
            session_id="session",
            order_kind="ad_hoc_task",
            source="conversation_turn",
            source_ref="conversation.turn:1",
            objective="审查代码",
            input_contract={"task_selection_projection": projected_selection},
        ),
        envelope=TaskExecutionEnvelope(
            envelope_id="taskenv:test",
            order_id="order:test",
            order_run_id="orderrun:test",
            execution_channel_id="channel:test",
            session_id="session",
            context_package={"task_selection_projection": projected_selection},
        ),
    )

    task_selection = _task_selection_for_runtime(
        request_task_selection={"interaction_mode": "professional_mode"},
        task_order_creation=creation,
        turn_id="turn:session:1",
    )

    assert task_selection["turn_id"] == "turn:session:1"
    assert task_selection["sandbox_policy"]["workspace_key"] == "langchain-mini-clean-agent-smoke"
    assert task_selection["resource_contract"]["source_projects"][0]["path"].endswith("langchain-mini-clean")


def test_astream_marks_task_order_failed_when_runtime_blocks_before_start() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-prestart-failure-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=_FailingDecisionModelRuntime(),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-prestart-failure",
                message="请检查 backend/api/chat.py 并写一份代码审查报告。",
                history=[],
                task_selection={
                    "interaction_mode": "professional_mode",
                    "runtime_lane": "professional_task",
                    "sandbox_policy": {"enabled": True, "workspace_key": "prestart-failure"},
                },
                task_order_intent={"action": "run_task"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    projection = next(event for event in events if event.get("type") == "task_order_projection")
    order_run_id = str(dict(projection.get("task_order_run") or {}).get("run_id") or "")
    run = runtime.task_run_loop.state_index.get_task_order_run(order_run_id)

    assert any(
        dict(event.get("event") or {}).get("event_type") == "runtime_blocked_before_assembly"
        for event in events
        if event.get("type") == "runtime_loop_event"
    )
    assert run is not None
    assert run.status == "failed"
    assert run.task_run_id == ""
    assert "model_turn_decision_unavailable_or_blocked" in run.terminal_reason
    error = next(event for event in events if event.get("type") == "error")
    assert error["code"] == "model_turn_decision_blocked"


def test_astream_blocks_before_assembly_when_action_permit_denies_write() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-action-permit-denied",
                message="请修改 backend/api/chat.py，但不要写任何文件。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    blocked_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "runtime_blocked_before_assembly"
    )
    payload = dict(blocked_event.get("payload") or {})

    assert payload["reason"] == "action_permit_denied"
    assert payload["denied_reasons"] == ["write_forbidden_by_boundary"]
    assert not any(event.get("type") == "runtime_loop_started" for event in events)
    error = next(event for event in events if event.get("type") == "error")
    assert error["code"] == "action_permit_denied"


def test_removed_health_task_selection_falls_back_to_general_runtime() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.task_run_loop.run_single_agent_stream(
            session_id="session-health-task-config",
            task_id="taskinst:session-health-task-config:health",
            user_message="请分诊这个健康问题。",
            history=[],
            source="regression",
            agent_runtime_chain=runtime.agent_runtime_chain,
            model_response_executor=runtime.model_response_executor,
            runtime_context_manager=runtime.runtime_context_manager,
            task_selection={"selected_task_id": "task.health.issue_triage"},
            tool_runtime_executor=runtime.tool_runtime_executor,
            tool_instances=runtime._all_tool_instances(),
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = next(event for event in events if event.get("type") == "runtime_loop_started")
    task_run = dict(started["task_run"])
    task_contract_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )

    payload = dict(task_contract_event["payload"])
    assembly = dict(payload.get("task_execution_assembly") or {})

    assert task_run["agent_id"] == "agent:0"
    assert task_run["agent_profile_id"] == "main_interactive_agent"
    assert "task_family" not in assembly
    assert assembly["flow_contract_id"] == ""


def test_graph_node_assembly_contract_overrides_stale_task_selection_agent() -> None:
    runtime = _build_stream_runtime()
    work_order = NodeWorkOrder(
        work_order_id="workorder:assembly-authority",
        task_ref="task.dev.light_web_game",
        coordination_run_id="coordrun:assembly-authority",
        root_task_run_id="taskrun:root",
        stage_id="prototype",
        node_id="prototype",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        runtime_lane="game_delivery",
        executor_type="agent",
        explicit_inputs={"goal": "做一个小游戏"},
        input_package={"package_id": "nodeinput:assembly-authority"},
        dispatch_context={"dispatch_event_id": "tlevent:assembly-authority"},
    )
    invocation = build_agent_invocation(work_order, base_dir=runtime.base_dir).to_dict()
    assembly = dict(invocation["assembly_contract"])

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.task_run_loop.run_single_agent_stream(
            session_id="session-assembly-authority",
            task_id="taskinst:session-assembly-authority:triage",
            user_message="请分诊这个健康问题。",
            history=[],
            source="regression",
            agent_runtime_chain=runtime.agent_runtime_chain,
            model_response_executor=runtime.model_response_executor,
            runtime_context_manager=runtime.runtime_context_manager,
            task_selection={
                "selected_task_id": "task.dev.light_web_game",
                "agent_id": "agent:pdf_reader",
                "agent_profile_id": "pdf_analysis_agent",
                "runtime_lane": "pdf_delegate",
                "agent_invocation": invocation,
            },
            tool_runtime_executor=runtime.tool_runtime_executor,
            tool_instances=runtime._all_tool_instances(),
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = next(event for event in events if event.get("type") == "runtime_loop_started")
    task_run = dict(started["task_run"])
    task_contract_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )
    payload = dict(task_contract_event["payload"])
    refs = dict(task_contract_event["refs"])

    assert task_run["agent_id"] == "agent:0"
    assert task_run["agent_profile_id"] == "main_interactive_agent"
    assert task_run["runtime_lane"] == "game_delivery"
    assert payload["agent_runtime_spec"]["agent_id"] == "agent:0"
    assert payload["agent_invocation"]["invocation_id"] == invocation["invocation_id"]
    assert payload["agent_assembly_contract"]["assembly_id"] == assembly["assembly_id"]
    assert "prompt_assembly" not in payload["agent_assembly_contract"]
    assert "runtime_control" not in payload["agent_invocation"]
    assert refs["agent_invocation_ref"] == invocation["invocation_id"]
    assert refs["agent_assembly_contract_ref"] == assembly["assembly_id"]
    assert refs["work_order_ref"] == work_order.work_order_id
    assert refs["agent_invocation_object_ref"].startswith("rtobj:agent_invocation:")
    assert refs["agent_assembly_object_ref"].startswith("rtobj:agent_assembly_contract:")
    assert refs["execution_permit_object_ref"].startswith("rtobj:execution_permit:")


def test_main_agent_assembly_modes_select_expected_runtime_lanes() -> None:
    cases = {
        "role": ("role_mode", "role_interaction", "runtime.recipe.role_interaction"),
        "standard": ("standard_mode", "standard_task", "runtime.recipe.standard_task"),
        "professional": ("professional_mode", "professional_task", "runtime.recipe.professional_task"),
    }

    for mode, (interaction_mode, runtime_lane, recipe_id) in cases.items():
        runtime = _build_stream_runtime()
        task_selection = _main_agent_mode_task_selection(
            interaction_mode=interaction_mode,
            runtime_lane=runtime_lane,
            recipe_id=recipe_id,
            professional=mode == "professional",
        )

        async def _collect() -> list[dict[str, object]]:
            events: list[dict[str, object]] = []
            async for event in runtime.astream(
                QueryRequest(
                    session_id=f"session-main-agent-{mode}",
                    message="请确认当前主 Agent 装配模式。",
                    history=[],
                    task_selection=task_selection,
                )
            ):
                events.append(event)
            return events

        events = asyncio.run(_collect())
        started = next(event for event in events if event.get("type") == "runtime_loop_started")
        task_run = dict(started["task_run"])
        task_contract_event = next(
            dict(event.get("event") or {})
            for event in events
            if event.get("type") == "runtime_loop_event"
            and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
        )
        payload = dict(task_contract_event.get("payload") or {})
        agent_runtime_spec = dict(payload.get("agent_runtime_spec") or {})
        agent_assembly_contract = dict(payload.get("agent_assembly_contract") or {})
        agent_invocation = dict(payload.get("agent_invocation") or {})
        selected_recipe = dict(payload.get("selected_recipe") or {})
        selected_metadata = dict(selected_recipe.get("metadata") or {})
        mode_policy = dict(selected_metadata.get("mode_policy") or {})

        assert task_run["agent_id"] == "agent:0"
        assert task_run["agent_profile_id"] == "main_interactive_agent"
        assert task_run["runtime_lane"] == runtime_lane
        assert agent_runtime_spec["agent_id"] == "agent:0"
        assert agent_runtime_spec["runtime_lane"] == runtime_lane
        assert agent_assembly_contract["agent_id"] == "agent:0"
        assert agent_assembly_contract["agent_profile_id"] == "main_interactive_agent"
        assert agent_assembly_contract["runtime_lane"] == runtime_lane
        assert agent_invocation["agent_profile_id"] == "main_interactive_agent"
        assert selected_recipe["recipe_id"] == recipe_id
        assert mode_policy["interaction_mode"] == interaction_mode
        assert mode_policy["runtime_lane"] == runtime_lane
        if mode == "professional":
            assert selected_recipe["execution_kind"] == interaction_mode


def test_runtime_trace_exposes_worker_spawn_trace_for_light_web_game(tmp_path: Path) -> None:
    base_dir = isolated_backend_root("query-runtime-loop-")
    registry = TaskFlowRegistry(base_dir)
    registry.upsert_task_execution_policy(
        task_id="task.dev.light_web_game",
        execution_mode="coordinated_agents",
        default_agent_id="agent:0",
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
        worker_agent_naming_rule="game-worker-{n}",
        notes="trace regression",
    )
    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
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


def test_delegate_mode_does_not_start_system_retrieval_phase() -> None:
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
    recipe = dict(payload.get("selected_recipe") or {})
    assert str(recipe.get("recipe_id") or "")
    assert str(recipe.get("execution_kind") or "") in {
        "conversation",
        "professional",
        "standard_mode",
        "capability",
        "role_mode",
    }

    executor_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "executor_started"
    ]
    assert not any(
        str(dict(event.get("payload") or {}).get("runtime_channel") or "") == "system_retrieval"
        for event in executor_events
    )


def test_terminal_state_index_failure_still_yields_done() -> None:
    runtime = _build_stream_runtime()

    def _raise_state_index_failure(*_args, **_kwargs):
        raise PermissionError("simulated state_index replace failure")

    runtime.task_run_loop.task_run_finalizer.upsert_finished_task_run = _raise_state_index_failure  # type: ignore[method-assign]

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


def test_coordination_continuation_is_consumed_before_terminal_done() -> None:
    runtime = _build_stream_runtime()
    original_upsert = runtime.task_run_loop.task_run_finalizer.upsert_finished_task_run
    continuation_called = False

    def _upsert_with_continuation(*args, **kwargs):
        finished = original_upsert(*args, **kwargs)
        return FinishedTaskRunResult(
            events=finished.events,
            continuation_payload={
                "next_task_ref": "task.dev.followup",
                "message": "继续执行后续节点。",
            },
        )

    async def _continuation_stream(**_kwargs):
        nonlocal continuation_called
        continuation_called = True
        yield {"type": "content_delta", "content": "后续节点已调度"}

    runtime.task_run_loop.task_run_finalizer.upsert_finished_task_run = _upsert_with_continuation  # type: ignore[method-assign]
    runtime.task_run_loop._continue_coordination_delivery_stream = _continuation_stream  # type: ignore[method-assign]

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-done-ends-stream",
                message="你好",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert continuation_called is True
    assert events[-1].get("type") == "content_delta"
    assert events[-1].get("content") == "后续节点已调度"
    assert not any(event.get("type") == "done" and event.get("content") == "单轮收口回答" for event in events)


def test_assistant_commit_enqueues_memory_maintenance_without_waiting(tmp_path: Path) -> None:
    runtime = QueryRuntime(
        base_dir=tmp_path,
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )

    result = runtime._apply_assistant_message_commit(
        "session-queued-commit",
        {
            "role": "assistant",
            "content": "已提交。",
            "turn_id": "turn:queued:1",
        },
    )

    assert result["memory_maintenance_status"] == "queued"
    assert result["memory_maintenance_attempted"] is False
    assert result["durable_memory_commit_attempted"] is False
