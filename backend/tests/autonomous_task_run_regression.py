from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tool_definitions import get_tool_definition_map
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.runtime_lane_registry import RuntimeLaneRegistry
from query import QueryRuntime
from tasks.assembly_support import build_runtime_task_intent_contract
from tasks.execution_recipe_builder import build_execution_recipe
from tasks.execution_shape_resolver import resolve_execution_shape


class _MemoryFacadeStub:
    session_memory = SimpleNamespace(
        manager=lambda _session_id: SimpleNamespace(load_state=lambda: None),
        update_runtime_state_from_context_state=lambda *_args, **_kwargs: None,
    )

    def build_memory_context_package(self, *_args, **_kwargs):
        return None

    def build_memory_runtime_view(self, *_args, **_kwargs):
        return {"view_id": "memview:test", "state_snapshot": {}}

    def enqueue_memory_maintenance_after_commit(self, *_args, **_kwargs):
        return SimpleNamespace(
            to_dict=lambda: {
                "attempted": False,
                "queued": True,
                "status": "queued",
                "session_memory_succeeded": False,
                "durable_memory_succeeded": False,
                "durable_write_count": 0,
            }
        )


class _ToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_definition(self, _name):
        return None

    def get_instance(self, _name):
        return None


class _SearchTextToolStub:
    name = "search_text"

    def invoke(self, args):
        query = str(dict(args or {}).get("query") or "")
        return f"真实工具结果：query={query}; 命中 backend/orchestration/runtime_loop/autonomous_task_run_driver.py"


class _ToolRuntimeWithSearchTextStub:
    registry = None

    def __init__(self) -> None:
        self._definition_map = get_tool_definition_map()
        self._instances = [_SearchTextToolStub()]

    @property
    def definitions(self):
        return [self._definition_map["search_text"]]

    @property
    def instances(self):
        return list(self._instances)

    def get_definition(self, name):
        return self._definition_map.get(str(name or ""))

    def get_instance(self, name):
        target = str(name or "")
        return next((tool for tool in self._instances if getattr(tool, "name", "") == target), None)


class _DelegateToAgentToolStub:
    name = "delegate_to_agent"

    def invoke(self, _args):
        return "delegate_to_agent should be handled by runtime loop dispatcher."


class _ToolRuntimeWithDelegateStub:
    registry = None

    def __init__(self) -> None:
        self._definition_map = get_tool_definition_map()
        self._instances = [_DelegateToAgentToolStub()]

    @property
    def definitions(self):
        return [self._definition_map["delegate_to_agent"]]

    @property
    def instances(self):
        return list(self._instances)

    def get_definition(self, name):
        return self._definition_map.get(str(name or ""))

    def get_instance(self, name):
        target = str(name or "")
        return next((tool for tool in self._instances if getattr(tool, "name", "") == target), None)


class _ToolRuntimeWithSideEffectsStub:
    registry = None

    def __init__(self, root_dir: Path) -> None:
        self._definition_map = get_tool_definition_map()
        self._instances = [
            self._definition_map["write_file"].build(root_dir),
            self._definition_map["terminal"].build(root_dir),
        ]

    @property
    def definitions(self):
        return [self._definition_map["write_file"], self._definition_map["terminal"]]

    @property
    def instances(self):
        return list(self._instances)

    def get_definition(self, name):
        return self._definition_map.get(str(name or ""))

    def get_instance(self, name):
        target = str(name or "")
        return next((tool for tool in self._instances if getattr(tool, "name", "") == target), None)


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
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(content="已锁定目标、按轻量计划完成分析，并给出当前结论。")


class _ToolCallingModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0
        self.seen_tool_result = False

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        self.seen_tool_result = self.seen_tool_result or any(
            item.__class__.__name__ == "ToolMessage" for item in list(messages or [])
        )
        content = (
            "已基于真实 search_text 工具结果完成收口：定位到 autonomous_task_run_driver.py，"
            "标准自主任务可以在一轮受控观察后回答。"
        )
        return SimpleNamespace(content=content)

    async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "search_text" for tool in list(tools or []))
        return AIMessage(
            content="我需要先搜索运行时驱动实现。",
            tool_calls=[
                {
                    "id": "call-search-autonomous-driver",
                    "name": "search_text",
                    "args": {
                        "query": "AutonomousTaskRunDriver",
                        "roots": ["backend"],
                        "glob": "**/*.py",
                        "max_results": 5,
                    },
                    "type": "tool_call",
                }
            ],
        )


class _DelegatingModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0
        self.seen_delegation_result = False

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        self.seen_delegation_result = "agent_delegation_result" in tool_text and "agent:rag_analyst" in tool_text
        return SimpleNamespace(
            content=(
                "已基于真实子 Agent 回传完成收口：rag_analyst 提供了证据摘要，"
                "主 Agent 已综合其限制并给出结论。"
            )
        )

    async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "delegate_to_agent" for tool in list(tools or []))
        return AIMessage(
            content="这部分需要交给知识库分析子 Agent 收集证据。",
            tool_calls=[
                {
                    "id": "call-delegate-rag",
                    "name": "delegate_to_agent",
                    "args": {
                        "target_agent_id": "agent:rag_analyst",
                        "delegation_kind": "evidence_lookup",
                        "instruction": (
                            "你是一名知识库检索分析员。请只围绕 AutonomousTaskRunDriver 的标准模式，"
                            "检索是否已有受控工具观察与委派边界的证据，返回 summary、answer_candidate、evidence_refs、limitations。"
                        ),
                        "input_payload": {
                            "query": "AutonomousTaskRunDriver standard controlled delegation",
                            "source_kind": "knowledge",
                        },
                    },
                    "type": "tool_call",
                }
            ],
        )


class _SandboxWriteModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0
        self.seen_tool_result = False

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        self.seen_tool_result = "Write succeeded" in tool_text
        return SimpleNamespace(content="已在隔离沙箱中完成写入实验，真实工程未直接修改。")

    async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "write_file" for tool in list(tools or []))
        return AIMessage(
            content="我先在沙箱里写一个探针文件验证隔离边界。",
            tool_calls=[
                {
                    "id": "call-write-sandbox-probe",
                    "name": "write_file",
                    "args": {
                        "path": "backend/sandbox_probe.txt",
                        "content": "sandbox-only",
                    },
                    "type": "tool_call",
                }
            ],
        )


class _SandboxTerminalModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0
        self.seen_sandbox_cwd = False

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        normalized = tool_text.replace("\\", "/")
        self.seen_sandbox_cwd = "/output/sandbox_runs/" in normalized and normalized.endswith("/workspace")
        return SimpleNamespace(content="已验证 terminal 在 sandbox workspace 内运行。")

    async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "terminal" for tool in list(tools or []))
        return AIMessage(
            content="我需要确认命令运行目录是否被隔离。",
            tool_calls=[
                {
                    "id": "call-terminal-pwd",
                    "name": "terminal",
                    "args": {"command": "Get-Location | Select-Object -ExpandProperty Path"},
                    "type": "tool_call",
                }
            ],
        )


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
    root = Path(tempfile.mkdtemp(prefix="autonomous-task-run-")) / "backend"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _step_by_id(ledger: dict[str, object], step_id: str) -> dict[str, object]:
    return next(
        dict(step)
        for step in list(ledger.get("step_runs") or [])
        if dict(step).get("step_id") == step_id
    )


def _assert_final_check_bound_to_verification(
    ledger: dict[str, object],
    verify_event: dict[str, object],
    *,
    expected_mode: str = "standard",
) -> None:
    verification_ref = f"runtime_event:{verify_event.get('event_id')}"
    final_check_step = _step_by_id(ledger, "autonomous.final_check")
    diagnostics = dict(final_check_step.get("diagnostics") or {})

    assert dict(verify_event.get("refs") or {})["task_step_ref"] == "autonomous.final_check"
    assert final_check_step.get("status") == "completed"
    assert final_check_step.get("step_result_ref") == verification_ref
    assert verification_ref in list(final_check_step.get("observation_refs") or [])
    assert verification_ref in list(final_check_step.get("output_refs") or [])
    assert diagnostics["transition_reason"] == "autonomous_task_verification_completed"
    assert diagnostics["verification_ref"] == verification_ref
    assert diagnostics["verification_passed"] is True
    assert diagnostics["autonomy_mode"] == expected_mode


def test_autonomous_task_run_recipe_is_selected_without_specialist_route() -> None:
    current_turn_context = {
        "intent_decision": {"execution_strategy": "autonomous_task_run"},
        "runtime_assembly_hint": {"execution_strategy": "autonomous_task_run"},
    }
    contract = build_runtime_task_intent_contract(
        session_id="session-autonomous-shape",
        task_id="taskinst:autonomous-shape",
        user_goal="追踪这个问题并修复，最好一次性执行完计划。",
        query_understanding={},
        current_turn_context=current_turn_context,
    )

    shape = resolve_execution_shape(
        task_intent_contract=contract,
        query_understanding={},
        current_turn_context=current_turn_context,
    )

    assert shape.recipe_id == "runtime.recipe.autonomous_task_run"
    assert shape.execution_kind == "autonomous_task_run"
    assert shape.resolution_source == "intent_runtime_assembly"


def test_autonomous_task_run_managed_mode_is_preserved_in_recipe_policy() -> None:
    current_turn_context = {
        "autonomy_mode": "managed",
        "intent_decision": {"execution_strategy": "autonomous_task_run", "autonomy_mode": "managed"},
        "runtime_assembly_hint": {"execution_strategy": "autonomous_task_run", "autonomy_mode": "managed"},
    }
    contract = build_runtime_task_intent_contract(
        session_id="session-autonomous-managed-shape",
        task_id="taskinst:autonomous-managed-shape",
        user_goal="后台追踪这个长任务问题，完整实施到结束并持续保留恢复证据。",
        query_understanding={},
        current_turn_context=current_turn_context,
    )

    shape = resolve_execution_shape(
        task_intent_contract=contract,
        query_understanding={},
        current_turn_context=current_turn_context,
    )
    recipe = build_execution_recipe(base_dir=_isolated_backend_root(), execution_shape=shape)
    metadata = dict(recipe.metadata)

    assert shape.recipe_id == "runtime.recipe.autonomous_task_run"
    assert shape.diagnostics["autonomy_mode"] == "managed"
    assert metadata["autonomy_mode"] == "managed"
    assert metadata["background_policy"]["enabled"] is True
    assert metadata["recovery_policy"]["allow_resume"] is True
    assert metadata["verification_policy"]["strict"] is True
    assert metadata["delegation_policy"]["max_delegate_calls_per_task_run"] == 4


def test_specialist_routes_still_outrank_autonomous_task_run() -> None:
    current_turn_context = {
        "intent_decision": {"execution_strategy": "autonomous_task_run"},
        "runtime_assembly_hint": {"execution_strategy": "autonomous_task_run"},
    }
    contract = build_runtime_task_intent_contract(
        session_id="session-autonomous-specialist",
        task_id="taskinst:autonomous-specialist",
        user_goal="基于本地知识库总结 AI 治理风险。",
        query_understanding={
            "route_hint": "rag",
            "execution_posture": "direct_rag",
            "preferred_skill": "rag-skill",
            "source_kind": "knowledge",
        },
        current_turn_context=current_turn_context,
    )

    shape = resolve_execution_shape(
        task_intent_contract=contract,
        query_understanding={
            "route_hint": "rag",
            "execution_posture": "direct_rag",
            "preferred_skill": "rag-skill",
            "source_kind": "knowledge",
        },
        current_turn_context=current_turn_context,
    )

    assert shape.recipe_id == "runtime.recipe.knowledge_retrieval"
    assert shape.execution_kind == "retrieval"


def test_autonomous_task_lane_is_registered_for_main_agent() -> None:
    base_dir = _isolated_backend_root()

    lane = RuntimeLaneRegistry().get("autonomous_task")
    profile = AgentRuntimeRegistry(base_dir).get_profile("agent:0")

    assert lane is not None
    assert lane.metadata["runtime_driver"] == "autonomous_task_run"
    assert profile is not None
    assert "autonomous_task" in profile.allowed_runtime_lanes


def test_query_runtime_runs_autonomous_task_driver_without_coordination_run() -> None:
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

    async def _collect() -> tuple[list[dict[str, object]], str]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-autonomous-driver",
                message="帮我追踪这个问题并修复，最好一次性执行完计划。",
                history=[],
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
    done = next(event for event in events if event.get("type") == "done")

    assert "autonomous_task_started" in runtime_event_types
    assert "autonomous_task_plan_drafted" in runtime_event_types
    assert "autonomous_task_verification_checked" in runtime_event_types
    assert done["terminal_reason"] == "completed"
    assert trace is not None
    assert trace["coordination_runs"] == []


def test_query_runtime_standard_autonomy_adds_dynamic_plan_steps() -> None:
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
                session_id="session-autonomous-standard",
                message="帮我追踪这个问题并修复，最好一次性执行完计划。",
                history=[],
                task_selection={"autonomy_mode": "standard"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    event_types = [str(event.get("event_type") or "") for event in runtime_events]
    plan_event = next(
        event for event in runtime_events if event.get("event_type") == "autonomous_task_plan_drafted"
    )
    verify_event = next(
        event for event in runtime_events if event.get("event_type") == "autonomous_task_verification_checked"
    )
    step_added_events = [
        event for event in runtime_events if event.get("event_type") == "step_added"
    ]
    done = next(event for event in events if event.get("type") == "done")
    ledger = dict(done.get("task_run_ledger") or {})
    step_ids = [
        str(step.get("step_id") or "")
        for step in list(ledger.get("step_runs") or [])
    ]

    assert "autonomous_task_started" in event_types
    assert dict(plan_event.get("payload") or {})["mode"] == "standard"
    assert len(step_added_events) >= 3
    assert "autonomous.goal_lock" in step_ids
    assert "autonomous.context_review" in step_ids
    assert "autonomous.final_check" in step_ids
    _assert_final_check_bound_to_verification(ledger, verify_event)
    assert done["terminal_reason"] == "completed"


def test_query_runtime_standard_autonomy_runs_one_controlled_tool_observation() -> None:
    model_runtime = _ToolCallingModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=_isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeWithSearchTextStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-autonomous-standard-tool",
                message="追踪一下 AutonomousTaskRunDriver 的标准模式工具闭环。",
                history=[],
                task_selection={"autonomy_mode": "standard"},
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    event_types = [str(event.get("event_type") or "") for event in runtime_events]
    plan_event = next(
        event for event in runtime_events if event.get("event_type") == "autonomous_task_plan_drafted"
    )
    executor_event = next(
        event
        for event in runtime_events
        if event.get("event_type") == "executor_started"
        and dict(event.get("payload") or {}).get("runtime_channel") == "autonomous_task_run"
    )
    observation_events = [
        event
        for event in runtime_events
        if event.get("event_type") == "executor_observation_received"
    ]
    tool_request_event = next(
        event for event in runtime_events if event.get("event_type") == "tool_call_requested"
    )
    verify_event = next(
        event for event in runtime_events if event.get("event_type") == "autonomous_task_verification_checked"
    )
    done = next(event for event in events if event.get("type") == "done")
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)
    monitor = runtime.task_run_loop.get_task_run_live_monitor(task_run_id)

    assert dict(plan_event.get("payload") or {})["tool_execution_enabled"] is True
    assert dict(executor_event.get("payload") or {})["allowed_tool_names"] == ["search_text"]
    assert "tool_call_requested" in event_types
    assert "tool_result_received" in event_types
    assert "executor_observation_received" in event_types
    assert any(
        dict(dict(event.get("payload") or {}).get("observation") or {}).get("observation_type") == "tool_result"
        for event in observation_events
    )
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    checks = dict(verification.get("checks") or {})
    assert checks["tool_call_count"] == 1
    assert checks["tool_observation_count"] == 1
    assert done["terminal_reason"] == "completed"
    assert "真实 search_text 工具结果" in str(done.get("content") or "")
    assert model_runtime.tool_enabled_calls == 1
    assert model_runtime.plain_calls == 1
    assert model_runtime.seen_tool_result is True
    assert trace is not None
    assert trace["coordination_runs"] == []
    assert dict(tool_request_event.get("refs") or {})["task_step_ref"] == "autonomous.context_review"
    ledger = dict(done.get("task_run_ledger") or {})
    context_review_step = _step_by_id(ledger, "autonomous.context_review")
    assert dict(context_review_step).get("status") == "completed"
    assert list(dict(context_review_step).get("observation_refs") or [])
    assert list(dict(context_review_step).get("output_refs") or [])
    _assert_final_check_bound_to_verification(ledger, verify_event)
    assert monitor is not None
    assert monitor["has_coordination"] is False
    autonomous_summary = dict(monitor["autonomous_task_summary"] or {})
    assert autonomous_summary["runtime_driver"] == "autonomous_task_run"
    assert autonomous_summary["mode"] == "standard"
    assert autonomous_summary["goal"] == "追踪一下 AutonomousTaskRunDriver 的标准模式工具闭环。"
    assert autonomous_summary["plan"]["tool_execution_enabled"] is True
    assert autonomous_summary["observation"]["tool_call_count"] == 1
    assert autonomous_summary["observation"]["tool_observation_count"] == 1
    assert autonomous_summary["verification"]["status"] == "passed"
    assert autonomous_summary["latest_checkpoint"] is not None


def test_query_runtime_standard_autonomy_runs_one_controlled_agent_delegation() -> None:
    model_runtime = _DelegatingModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=_isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeWithDelegateStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-autonomous-standard-delegate",
                message="帮我追踪这个问题并修复，最好一次性执行完计划；必要时可以委派一个受限子 Agent 做只读核对。",
                history=[],
                task_selection={"autonomy_mode": "standard"},
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    event_types = [str(event.get("event_type") or "") for event in runtime_events]
    plan_event = next(
        event for event in runtime_events if event.get("event_type") == "autonomous_task_plan_drafted"
    )
    tool_request_event = next(
        event for event in runtime_events if event.get("event_type") == "tool_call_requested"
    )
    verify_event = next(
        event for event in runtime_events if event.get("event_type") == "autonomous_task_verification_checked"
    )
    done = next(event for event in events if event.get("type") == "done")
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)

    assert dict(plan_event.get("payload") or {})["delegation_enabled"] is True
    assert "delegate_to_agent" in dict(plan_event.get("payload") or {})["allowed_tool_names"]
    assert "tool_call_requested" in event_types
    assert "agent_delegation_requested" in event_types
    assert "agent_run_created" in event_types
    assert "agent_delegation_result_created" in event_types
    assert "agent_delegation_parent_observation_created" in event_types
    assert "tool_result_received" in event_types
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    checks = dict(verification.get("checks") or {})
    assert checks["tool_call_count"] == 1
    assert checks["tool_observation_count"] == 1
    assert checks["delegation_observation_count"] == 1
    assert done["terminal_reason"] == "completed"
    assert "真实子 Agent 回传" in str(done.get("content") or "")
    assert model_runtime.tool_enabled_calls == 1
    assert model_runtime.plain_calls == 1
    assert model_runtime.seen_delegation_result is True
    assert trace is not None
    assert trace["coordination_runs"] == []
    assert dict(tool_request_event.get("refs") or {})["task_step_ref"] == "autonomous.context_review"
    ledger = dict(done.get("task_run_ledger") or {})
    context_review_step = _step_by_id(ledger, "autonomous.context_review")
    assert dict(context_review_step).get("status") == "completed"
    assert list(dict(context_review_step).get("observation_refs") or [])
    _assert_final_check_bound_to_verification(ledger, verify_event)


def test_autonomous_task_run_sandbox_redirects_write_file_side_effects() -> None:
    backend_root = _isolated_backend_root()
    project_root = backend_root.parent
    model_runtime = _SandboxWriteModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=backend_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-autonomous-sandbox-write",
                message="请在隔离环境里写一个探针文件，验证不会误伤真实工程。",
                history=[],
                task_selection={
                    "autonomy_mode": "standard",
                    "intent_decision": {"execution_strategy": "autonomous_task_run", "autonomy_mode": "standard"},
                    "runtime_assembly_hint": {
                        "execution_strategy": "autonomous_task_run",
                        "autonomy_mode": "standard",
                    },
                },
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    sandbox_event = next(event for event in runtime_events if event.get("event_type") == "runtime_sandbox_prepared")
    sandbox_policy = dict(dict(sandbox_event.get("payload") or {}).get("sandbox_policy") or {})
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or ""))
    real_probe = project_root / "backend" / "sandbox_probe.txt"
    sandbox_probe = sandbox_root / "backend" / "sandbox_probe.txt"
    execution_result_event = next(
        event for event in runtime_events if event.get("event_type") == "execution_result_recorded"
    )
    execution_record = dict(dict(execution_result_event.get("payload") or {}).get("execution_record") or {})
    result_payload = dict(execution_record.get("result_payload") or {})
    done = next(event for event in events if event.get("type") == "done")

    assert sandbox_policy["enabled"] is True
    assert sandbox_policy["real_workspace_access"] == "read_only"
    assert real_probe.exists() is False
    assert sandbox_probe.read_text(encoding="utf-8") == "sandbox-only"
    assert dict(result_payload.get("sandbox") or {})["sandbox_root"] == str(sandbox_root)
    assert model_runtime.tool_enabled_calls == 1
    assert model_runtime.plain_calls == 1
    assert model_runtime.seen_tool_result is True
    assert done["terminal_reason"] == "completed"
    assert runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)["coordination_runs"] == []


def test_autonomous_task_run_sandbox_runs_terminal_inside_overlay_workspace() -> None:
    backend_root = _isolated_backend_root()
    model_runtime = _SandboxTerminalModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=backend_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
    )

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-autonomous-sandbox-terminal",
                message="请在隔离环境里运行一个命令，确认 terminal 的工作目录。",
                history=[],
                task_selection={
                    "autonomy_mode": "standard",
                    "intent_decision": {"execution_strategy": "autonomous_task_run", "autonomy_mode": "standard"},
                    "runtime_assembly_hint": {
                        "execution_strategy": "autonomous_task_run",
                        "autonomy_mode": "standard",
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    sandbox_event = next(event for event in runtime_events if event.get("event_type") == "runtime_sandbox_prepared")
    sandbox_root = str(dict(dict(sandbox_event.get("payload") or {}).get("sandbox_policy") or {}).get("sandbox_root") or "")
    tool_result_event = next(event for event in runtime_events if event.get("event_type") == "tool_result_received")
    observation = dict(dict(tool_result_event.get("payload") or {}).get("observation") or {})
    observation_payload = dict(observation.get("payload") or {})

    assert sandbox_root
    assert str(observation_payload.get("tool_name") or "") == "terminal"
    assert str(observation_payload.get("result") or "").strip() == sandbox_root
    assert model_runtime.tool_enabled_calls == 1
    assert model_runtime.plain_calls == 1
    assert model_runtime.seen_sandbox_cwd is True


def test_query_runtime_managed_autonomy_preserves_mode_without_coordination_run() -> None:
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

    async def _collect() -> tuple[list[dict[str, object]], str]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-autonomous-managed",
                message="后台追踪这个长任务问题，完整实施到结束并保留恢复证据。",
                history=[],
                task_selection={
                    "autonomy_mode": "managed",
                    "intent_decision": {"execution_strategy": "autonomous_task_run", "autonomy_mode": "managed"},
                    "runtime_assembly_hint": {"execution_strategy": "autonomous_task_run", "autonomy_mode": "managed"},
                },
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    start_event = next(event for event in runtime_events if event.get("event_type") == "autonomous_task_started")
    plan_event = next(event for event in runtime_events if event.get("event_type") == "autonomous_task_plan_drafted")
    executor_event = next(
        event
        for event in runtime_events
        if event.get("event_type") == "executor_started"
        and dict(event.get("payload") or {}).get("runtime_channel") == "autonomous_task_run"
    )
    verify_event = next(
        event for event in runtime_events if event.get("event_type") == "autonomous_task_verification_checked"
    )
    done = next(event for event in events if event.get("type") == "done")
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)
    monitor = runtime.task_run_loop.get_task_run_live_monitor(task_run_id)
    ledger = dict(done.get("task_run_ledger") or {})
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})

    assert dict(start_event.get("payload") or {})["mode"] == "managed"
    assert dict(plan_event.get("payload") or {})["mode"] == "managed"
    assert dict(executor_event.get("payload") or {})["autonomy_mode"] == "managed"
    assert verification["mode"] == "managed"
    _assert_final_check_bound_to_verification(ledger, verify_event, expected_mode="managed")
    assert done["terminal_reason"] == "completed"
    assert trace is not None
    assert trace["coordination_runs"] == []
    assert monitor is not None
    assert monitor["has_coordination"] is False
    autonomous_summary = dict(monitor["autonomous_task_summary"] or {})
    assert autonomous_summary["mode"] == "managed"
