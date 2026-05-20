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


class _ToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_definition(self, _name):
        return None

    def get_instance(self, _name):
        return None


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


class _SearchTextToolStub:
    name = "search_text"

    def invoke(self, args):
        query = str(dict(args or {}).get("query") or "")
        return f"真实工具结果：query={query}; 命中 backend/orchestration/runtime_loop/professional_task_run_driver.py"


class _ToolRuntimeWithSideEffectsStub:
    registry = None

    def __init__(self, root_dir: Path) -> None:
        self._definition_map = get_tool_definition_map()
        self._instances = [
            self._definition_map["read_file"].build(root_dir),
            self._definition_map["read_structured_file"].build(root_dir),
            self._definition_map["search_text"].build(root_dir),
            self._definition_map["write_file"].build(root_dir),
            self._definition_map["edit_file"].build(root_dir),
            self._definition_map["terminal"].build(root_dir),
        ]

    @property
    def definitions(self):
        return [
            self._definition_map["read_file"],
            self._definition_map["read_structured_file"],
            self._definition_map["search_text"],
            self._definition_map["write_file"],
            self._definition_map["edit_file"],
            self._definition_map["terminal"],
        ]

    @property
    def instances(self):
        return list(self._instances)

    def get_definition(self, name):
        return self._definition_map.get(str(name or ""))

    def get_instance(self, name):
        target = str(name or "")
        return next((tool for tool in self._instances if getattr(tool, "name", "") == target), None)


class _ModelRuntimeStub:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(
            content=(
                "tool grounded answer：已锁定目标、按专业模式计划完成分析，并给出当前结论。"
                "限制：本轮没有执行额外工具。"
            )
        )


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
        return SimpleNamespace(
            content=(
                "tool grounded answer：已基于真实 search_text 工具结果完成收口，定位到 professional_task_run_driver.py，"
                "专业模式可以在预算受控的真实工具观察后回答。限制：本轮只使用 search_text 观察。"
            )
        )

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "search_text" for tool in list(tools or []))
        self.seen_tool_result = self.seen_tool_result or any(
            item.__class__.__name__ == "ToolMessage" for item in list(messages or [])
        )
        if self.seen_tool_result:
            return SimpleNamespace(
                content=(
                    "tool grounded answer：已基于真实 search_text 工具结果完成收口，定位到 professional_task_run_driver.py，"
                    "专业模式可以在预算受控的真实工具观察后回答。限制：本轮只使用 search_text 观察。"
                )
            )
        return AIMessage(
            content="我需要先搜索运行时驱动实现。",
            tool_calls=[
                {
                    "id": "call-search-professional-driver",
                    "name": "search_text",
                    "args": {
                        "query": "ProfessionalTaskRunDriver",
                        "roots": ["backend"],
                        "glob": "**/*.py",
                        "max_results": 5,
                    },
                    "type": "tool_call",
                }
            ],
        )


class _TriageModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_structured_report = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        self.seen_structured_report = self.seen_structured_report or (
            "fixture-professional-triage" in tool_text and "output_boundary" in tool_text
        )
        if not self.seen_structured_report:
            assert any(getattr(tool, "name", "") == "read_structured_file" for tool in list(tools or []))
            return AIMessage(
                content="我先读取测试报告，抽取失败项。",
                tool_calls=[
                    {
                        "id": "call-read-professional-triage-report",
                        "name": "read_structured_file",
                        "args": {"path": "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"},
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(
            content=(
                "失败归类：output boundary 和 tool loop 交界处丢失稳定最终答案。\n"
                "结构性根因：语义交付物没有在工具观察之后进入统一验证，导致长任务收口依赖模型自觉，不是孤立失败。\n"
                "回归测试：补充专业模式长跑测试，断言读取报告、证据包、交付验证和最终回答都出现。\n"
                "证据边界：本轮只读取了指定失败报告，没有执行完整端到端重跑。"
            )
        )


class _BudgetCloseoutModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        assert "fixture-professional-budget" in tool_text
        return SimpleNamespace(
            content=(
                "失败归类：timeout/budget 后的最终答案提交不稳定。\n"
                "结构性根因：专业任务预算耗尽后必须触发强制收口，否则长任务会空转。\n"
                "回归测试：覆盖预算耗尽后基于已有证据形成最终答案。\n"
                "证据边界：只基于已读取报告，没有重跑全量测试。"
            )
        )

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "read_structured_file" for tool in list(tools or []))
        return AIMessage(
            content="继续补充证据。",
            tool_calls=[
                {
                    "id": f"call-read-budget-{self.tool_enabled_calls}",
                    "name": "read_structured_file",
                    "args": {"path": "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"},
                    "type": "tool_call",
                }
            ],
        )


class _SandboxWriteModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_tool_result = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        self.seen_tool_result = self.seen_tool_result or "Write succeeded" in tool_text
        if self.seen_tool_result:
            return SimpleNamespace(
                content=(
                    "completion status：已完成。产物文件：backend/sandbox_probe.txt。"
                    "限制：该文件只写入 sandbox overlay，真实工程未直接修改。"
                )
            )
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
        self.seen_sandbox_cwd = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        normalized = tool_text.replace("\\", "/")
        self.seen_sandbox_cwd = self.seen_sandbox_cwd or (
            "/output/sandbox_runs/" in normalized and normalized.endswith("/workspace")
        )
        if self.seen_sandbox_cwd:
            return SimpleNamespace(
                content=(
                    "tool grounded answer：terminal 已在 sandbox workspace 内运行。"
                    "限制：本轮只验证工作目录，没有修改文件。"
                )
            )
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


class _WriteAfterReadModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_contract = False
        self.seen_write = False
        self.tool_call_options_by_call: list[object] = []

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        self.tool_call_options_by_call.append(_kwargs.get("tool_call_options"))
        tool_names = [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        self.seen_contract = self.seen_contract or "status_filter" in tool_text
        self.seen_write = self.seen_write or "Write succeeded" in tool_text
        if self.seen_write:
            return SimpleNamespace(
                content=(
                    "修改：已写入功能草案。\n"
                    "文件：output/professional_feature_slice/status-filter-plan.md。\n"
                    "验证：本轮写入已由 write_file 返回成功；未运行端到端测试。"
                )
            )
        if self.seen_contract:
            assert "write_file" in tool_names
            assert "read_file" not in tool_names
            return AIMessage(
                content="我已经读到契约，下一步写入草案文件。",
                tool_calls=[
                    {
                        "id": "call-write-feature-slice",
                        "name": "write_file",
                        "args": {
                            "path": "output/professional_feature_slice/status-filter-plan.md",
                            "content": "后端：提供 status 参数筛选节点。\n前端：增加状态筛选控件。\n测试：覆盖全部状态和空结果。",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        assert "read_file" in tool_names
        return AIMessage(
            content="我先读取功能契约。",
            tool_calls=[
                {
                    "id": "call-read-feature-contract",
                    "name": "read_file",
                    "args": {"path": "tests/fixtures/professional_task_suite/node_status_filter_contract.json"},
                    "type": "tool_call",
                }
            ],
        )


class _ToolMarkupLeakModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0

    async def invoke_messages(self, _messages, **_kwargs):
        self.plain_calls += 1
        return SimpleNamespace(
            content=(
                "我需要读取文件。\n"
                "name=\"read_file\">\n"
                "<｜｜DSML｜｜parameter name=\"path\">tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"
            )
        )

    async def invoke_messages_with_tools(self, _messages, _tools, **_kwargs):
        self.tool_enabled_calls += 1
        return SimpleNamespace(
            content=(
                "name=\"read_file\">\n"
                "<｜｜DSML｜｜parameter name=\"path\">tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"
            )
        )


class _EvidenceCloseoutLeakModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_structured_report = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = "\n".join(
            str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if item.__class__.__name__ == "ToolMessage"
        )
        self.seen_structured_report = self.seen_structured_report or (
            "fixture-professional-evidence-closeout" in tool_text and "final_content_chars=0" in tool_text
        )
        if not self.seen_structured_report:
            assert any(getattr(tool, "name", "") == "read_file" for tool in list(tools or []))
            return AIMessage(
                content="我先读取测试报告，抽取失败项。",
                tool_calls=[
                    {
                        "id": "call-read-evidence-closeout-report",
                        "name": "read_file",
                        "args": {"path": "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"},
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(
            content=(
                "name=\"read_file\" string=\"true\">\n"
                "<｜｜DSML｜｜parameter name=\"path\">backend/orchestration/runtime_loop/tool_adoption.py"
            )
        )


def _isolated_backend_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="professional-task-run-")) / "backend"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _professional_task_selection(
    *,
    max_tool_rounds: int | None = None,
    semantic_task_type: str | None = "bounded_tool_task",
) -> dict[str, object]:
    selection: dict[str, object] = {
        "interaction_mode": "professional_mode",
        "intent_decision": {
            "execution_strategy": "professional_task_run",
            "interaction_mode": "professional_mode",
        },
        "runtime_assembly_hint": {
            "execution_strategy": "professional_task_run",
            "runtime_mode": "professional_task",
            "interaction_mode": "professional_mode",
        },
    }
    if max_tool_rounds is not None:
        selection["mode_policy"] = {
            "interaction_mode": "professional_mode",
            "tool_policy": {
                "max_tool_rounds_per_task_run": max_tool_rounds,
                "max_tool_calls_per_task_run": max_tool_rounds,
                "max_tool_calls_per_round": 1,
            },
        }
    if semantic_task_type:
        selection["semantic_task_type"] = semantic_task_type
    return selection


async def _collect_runtime_events(runtime: QueryRuntime, *, session_id: str, message: str, task_selection: dict[str, object] | None = None):
    from query.models import QueryRequest

    events: list[dict[str, object]] = []
    async for event in runtime.astream(
        QueryRequest(
            session_id=session_id,
            message=message,
            history=[],
            task_selection=dict(task_selection or {}),
        )
    ):
        events.append(event)
    started = next(event for event in events if event["type"] == "runtime_loop_started")
    task_run_id = str(dict(started["task_run"]).get("task_run_id") or "")
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    done = next(event for event in events if event.get("type") == "done")
    return events, runtime_events, done, task_run_id


def _runtime(
    *,
    base_dir: Path | None = None,
    model_runtime=None,
    tool_runtime=None,
) -> QueryRuntime:
    return QueryRuntime(
        base_dir=base_dir or _isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=tool_runtime or _ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime or _ModelRuntimeStub(),
    )


def _event_types(runtime_events: list[dict[str, object]]) -> list[str]:
    return [str(event.get("event_type") or "") for event in runtime_events]


def _latest_event(runtime_events: list[dict[str, object]], event_type: str) -> dict[str, object]:
    return next(event for event in reversed(runtime_events) if event.get("event_type") == event_type)


def test_professional_task_run_recipe_is_selected_from_new_intent_strategy() -> None:
    current_turn_context = _professional_task_selection()
    contract = build_runtime_task_intent_contract(
        session_id="session-professional-shape",
        task_id="taskinst:professional-shape",
        user_goal="追踪这个问题并修复，最好一次性执行完计划。",
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

    assert shape.recipe_id == "runtime.recipe.professional_task"
    assert shape.execution_kind == "professional_mode"
    assert "interaction_mode:professional_mode" in shape.resolution_reasons
    assert metadata["runtime_driver"] == "professional_task_run"
    assert metadata["interaction_mode"] == "professional_mode"
    assert metadata["runtime_lane_hint"] == "professional_task"
    assert "autonomy_mode" not in metadata


def test_query_runtime_runs_professional_driver_without_coordination_run() -> None:
    runtime = _runtime()

    events, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-driver",
            message="帮我追踪这个问题并修复，最好一次性执行完计划。",
            task_selection=_professional_task_selection(),
        )
    )
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)
    event_types = _event_types(runtime_events)

    assert "professional_task_started" in event_types
    assert "professional_task_semantic_plan_drafted" in event_types
    assert "professional_task_evidence_packet_built" in event_types
    assert "professional_task_deliverable_validation_checked" in event_types
    assert done["terminal_reason"] == "completed"
    assert trace is not None
    assert trace["coordination_runs"] == []
    assert not any(event.get("type") in {"mcp_start", "mcp_end", "mcp_evidence"} for event in events)


def test_professional_mode_adds_semantic_plan_steps_and_monitor_summary() -> None:
    runtime = _runtime()

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-plan",
            message="帮我追踪这个问题并修复，最好一次性执行完计划。",
            task_selection=_professional_task_selection(),
        )
    )
    plan_event = _latest_event(runtime_events, "professional_task_semantic_plan_drafted")
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    plan_payload = dict(plan_event.get("payload") or {})
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    ledger = dict(done.get("task_run_ledger") or {})
    step_ids = [str(dict(step).get("step_id") or "") for step in list(ledger.get("step_runs") or [])]
    monitor = runtime.task_run_loop.get_task_run_live_monitor(task_run_id)

    assert plan_payload["interaction_mode"] == "professional_mode"
    assert plan_payload["plan_source"] == "semantic_task_contract"
    assert any(dict(item).get("plan_item_id") == "professional.mode_policy" for item in plan_payload["plan_items"])
    assert any(dict(item).get("plan_item_id") == "professional.validate_deliverable" for item in plan_payload["plan_items"])
    assert "professional.mode_policy" in step_ids
    assert "professional.validate_deliverable" in step_ids
    assert verification["interaction_mode"] == "professional_mode"
    assert monitor is not None
    assert monitor["has_coordination"] is False
    summary = dict(monitor["professional_task_summary"] or {})
    assert summary["runtime_driver"] == "professional_task_run"
    assert summary["interaction_mode"] == "professional_mode"
    assert summary["verification"]["status"] == "passed"


def test_professional_mode_runs_budgeted_tool_observation() -> None:
    model_runtime = _ToolCallingModelRuntimeStub()
    runtime = _runtime(model_runtime=model_runtime, tool_runtime=_ToolRuntimeWithSearchTextStub())

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-tool",
            message="追踪一下 ProfessionalTaskRunDriver 的专业模式工具闭环。",
            task_selection=_professional_task_selection(),
        )
    )
    event_types = _event_types(runtime_events)
    executor_event = next(
        event
        for event in runtime_events
        if event.get("event_type") == "executor_started"
        and dict(event.get("payload") or {}).get("runtime_channel") == "professional_task_run"
    )
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    checks = dict(verification.get("checks") or {})
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)

    assert dict(executor_event.get("payload") or {})["allowed_tool_names"] == ["search_text"]
    assert "tool_call_requested" in event_types
    assert "tool_result_received" in event_types
    assert "executor_observation_received" in event_types
    assert checks["tool_call_count"] == 1
    assert checks["tool_observation_count"] == 1
    assert done["terminal_reason"] == "completed"
    assert "真实 search_text 工具结果" in str(done.get("content") or "")
    assert model_runtime.tool_enabled_calls == 2
    assert model_runtime.plain_calls == 0
    assert model_runtime.seen_tool_result is True
    assert trace is not None
    assert trace["coordination_runs"] == []


def test_professional_test_report_triage_builds_evidence_packet_and_strict_validation() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "failing_sixty_turn_summary.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        (
            '{"run_id":"fixture-professional-triage","total_turns":60,"failed_turns":1,'
            '"failures":[{"turn":17,"check":"output_boundary","symptom":"final answer was empty",'
            '"evidence":"tool loop returned observation but stable answer was not committed"}]}'
        ),
        encoding="utf-8",
    )
    model_runtime = _TriageModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-triage",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
                "里的失败，输出失败归类、结构性根因、回归测试和证据边界。"
            ),
            task_selection=_professional_task_selection(semantic_task_type=None),
        )
    )
    evidence_event = _latest_event(runtime_events, "professional_task_evidence_packet_built")
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    evidence = dict(dict(evidence_event.get("payload") or {}).get("evidence_packet") or {})
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    validation = dict(verification.get("deliverable_validation") or {})

    assert evidence["facts"]
    assert evidence["classifications"]
    assert validation["passed"] is True
    assert verification["passed"] is True
    assert done["terminal_reason"] == "completed"
    assert "失败归类" in str(done.get("content") or "")
    assert "结构性根因" in str(done.get("content") or "")
    assert "回归测试" in str(done.get("content") or "")
    assert model_runtime.seen_structured_report is True


def test_professional_task_sandbox_redirects_write_file_side_effects() -> None:
    backend_root = _isolated_backend_root()
    project_root = backend_root.parent
    model_runtime = _SandboxWriteModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-sandbox-write",
            message="请在隔离环境里写一个探针文件，验证不会误伤真实工程。",
            task_selection={
                **_professional_task_selection(semantic_task_type="artifact_delivery"),
            },
        )
    )
    sandbox_event = _latest_event(runtime_events, "runtime_sandbox_prepared")
    sandbox_policy = dict(dict(sandbox_event.get("payload") or {}).get("sandbox_policy") or {})
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or ""))
    real_probe = project_root / "backend" / "sandbox_probe.txt"
    sandbox_probe = sandbox_root / "backend" / "sandbox_probe.txt"

    assert sandbox_policy["enabled"] is True
    assert sandbox_policy["real_workspace_access"] == "read_only"
    assert real_probe.exists() is False
    assert sandbox_probe.read_text(encoding="utf-8") == "sandbox-only"
    assert done["terminal_reason"] == "completed"
    assert model_runtime.tool_enabled_calls == 2
    assert model_runtime.seen_tool_result is True
    assert runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)["coordination_runs"] == []


def test_professional_task_sandbox_runs_terminal_inside_overlay_workspace() -> None:
    backend_root = _isolated_backend_root()
    model_runtime = _SandboxTerminalModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-sandbox-terminal",
            message="请在隔离环境里运行一个命令，确认 terminal 的工作目录。",
            task_selection={
                **_professional_task_selection(semantic_task_type="bounded_tool_task"),
            },
        )
    )
    sandbox_event = _latest_event(runtime_events, "runtime_sandbox_prepared")
    sandbox_root = str(dict(dict(sandbox_event.get("payload") or {}).get("sandbox_policy") or {}).get("sandbox_root") or "")
    tool_result_event = _latest_event(runtime_events, "tool_result_received")
    observation = dict(dict(tool_result_event.get("payload") or {}).get("observation") or {})
    observation_payload = dict(observation.get("payload") or {})

    assert sandbox_root
    assert str(observation_payload.get("tool_name") or "") == "terminal"
    assert str(observation_payload.get("result") or "").strip() == sandbox_root
    assert model_runtime.tool_enabled_calls == 2
    assert model_runtime.seen_sandbox_cwd is True
    assert done["terminal_reason"] == "completed"


def test_professional_task_budget_exhaustion_forces_model_closeout() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "failing_sixty_turn_summary.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        (
            '{"run_id":"fixture-professional-budget","failed_turns":1,'
            '"failures":[{"turn":33,"check":"timeout","symptom":"tool rounds exhausted before final answer"}]}'
        ),
        encoding="utf-8",
    )
    model_runtime = _BudgetCloseoutModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-budget-closeout",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json，"
                "找结构性根因并给回归测试。"
            ),
            task_selection=_professional_task_selection(max_tool_rounds=1, semantic_task_type=None),
        )
    )
    event_types = _event_types(runtime_events)
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    checks = dict(dict(dict(verify_event.get("payload") or {}).get("verification") or {}).get("checks") or {})

    assert "professional_task_budget_closeout_started" in event_types
    assert checks["tool_budget_exhausted"] is True
    assert done["terminal_reason"] == "completed"
    assert "结构性根因" in str(done.get("content") or "")
    assert "回归测试" in str(done.get("content") or "")
    assert model_runtime.plain_calls == 1
    assert runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)["coordination_runs"] == []


def test_professional_task_restricts_next_tools_to_required_write_after_material_review() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "node_status_filter_contract.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text('{"feature":"status_filter","states":["ready","blocked"]}', encoding="utf-8")
    model_runtime = _WriteAfterReadModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-write-after-read",
            message=(
                "请用专业模式根据 tests/fixtures/professional_task_suite/node_status_filter_contract.json，"
                "在 sandbox overlay 中写入一份状态筛选功能草案，并说明验证结果。"
            ),
            task_selection=_professional_task_selection(semantic_task_type=None),
        )
    )
    event_types = _event_types(runtime_events)
    content = str(done.get("content") or "")

    assert "tool_result_received" in event_types
    assert done["terminal_reason"] == "completed"
    assert model_runtime.seen_contract is True
    assert model_runtime.seen_write is True
    write_call_options = model_runtime.tool_call_options_by_call[1]
    assert getattr(write_call_options, "tool_choice", None) == "required"
    assert getattr(write_call_options, "parallel_tool_calls", None) is False
    assert "修改" in content
    assert "文件" in content
    assert "验证" in content


def test_professional_task_tool_markup_leak_cannot_pass_validation() -> None:
    model_runtime = _ToolMarkupLeakModelRuntimeStub()
    runtime = _runtime(model_runtime=model_runtime)

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-tool-markup-leak",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json，"
                "找结构性根因并给出回归测试。"
            ),
            task_selection=_professional_task_selection(semantic_task_type=None),
        )
    )
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    content = str(done.get("content") or "")

    assert verification["passed"] is False
    assert verification["protocol_leak_detected"] is True or "read_material" in verification["missing_required_actions"]
    assert "name=\"read_file\"" not in content
    assert "<｜｜DSML" not in content
    assert done["terminal_reason"] in {"tool_call_markup_leaked", "partial_contract_failed"}


def test_professional_task_uses_evidence_closeout_after_final_markup_leak() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "failing_sixty_turn_summary.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        (
            '{"run_id":"fixture-professional-evidence-closeout","failed_turns":4,'
            '"failures":['
            '{"turn":17,"check":"response.nonempty","symptom":"answer was cut after a tool observation",'
            '"evidence":["tool_result_received","final_content_chars=0"]},'
            '{"turn":18,"check":"runtime.timeout","symptom":"memory maintenance blocked foreground response",'
            '"evidence":["memory_maintenance_attempted=true","duration_ms=1800000"]},'
            '{"turn":31,"check":"main.active_dataset.nonempty","symptom":"delegated table result did not write active_dataset",'
            '"evidence":["context_writeback_hints.source_kind=dataset","final_outputs.main_context={}"]},'
            '{"turn":42,"check":"trace.artifact.contains","symptom":"write_file requested but no artifact ref was committed",'
            '"evidence":["tool_requires_approval=true","artifact_refs=[]"]}'
            ']}'
        ),
        encoding="utf-8",
    )
    model_runtime = _EvidenceCloseoutLeakModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-evidence-closeout",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json，"
                "把失败归类，找出结构性根因，并给出应该补的回归测试。"
            ),
            task_selection=_professional_task_selection(semantic_task_type=None),
        )
    )
    event_types = _event_types(runtime_events)
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    validation = dict(verification.get("deliverable_validation") or {})
    content = str(done.get("content") or "")

    assert "professional_task_evidence_closeout_applied" in event_types
    assert verification["passed"] is True
    assert validation["passed"] is True
    assert done["terminal_reason"] == "completed"
    assert content
    assert "失败归类" in content
    assert "结构性根因" in content
    assert "回归测试" in content
    assert "证据边界" in content
    assert "memory" in content
    assert "context" in content
    assert "artifact/writeback" in content
    assert "tool loop/output boundary" in content
    assert "name=\"read_file\"" not in content
    assert "<｜｜DSML" not in content
