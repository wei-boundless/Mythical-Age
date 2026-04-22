from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
from query.binding_models import StructuredDatasetBinding
from query.models import QueryExecutionPlan, QueryPlan
from tasks import TaskCoordinator
from understanding import MemoryIntent, QueryUnderstanding


class _FakeAgent:
    def __init__(self, recorder: dict[str, object]) -> None:
        self.recorder = recorder

    async def astream(self, *_args, **_kwargs):
        if _args:
            self.recorder["last_stream_payload"] = _args[0]
        self.recorder["stream_called"] = True
        yield ("messages", (SimpleNamespace(content="route-safe answer"), {}))


class _ScriptedAgent:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self._events = events

    async def astream(self, *_args, **_kwargs):
        for item in self._events:
            yield item


class _SettingsStub:
    def __init__(self, *, rag_mode: bool) -> None:
        self._rag_mode = rag_mode

    def get_rag_mode(self) -> bool:
        return self._rag_mode


class _MemoryFacadeStub:
    def __init__(self) -> None:
        self.prefetch_queries: list[str] = []
        self.persistent_queries: list[str] = []

    def compact_history_for_query(self, _session_id: str, history: list[dict[str, object]]):
        return history, {"pressure_level": "normal"}

    def inspect_query_context(self, *_args, **_kwargs):
        return {}

    def build_context_package(self, *_args, **_kwargs):
        return None

    def build_persistent_memory_block(self, *, query=None, **_kwargs):
        if isinstance(query, str) and query:
            self.persistent_queries.append(query)
        return ""

    def prefetch_relevant_notes(self, query, *_args, **_kwargs):
        self.prefetch_queries.append(str(query))
        return []


class _RetrievalStub:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str, *, top_k: int = 5):
        self.queries.append(query)
        return [{"text": "retrieved evidence", "top_k": top_k}]


class _ToolRuntimeStub:
    registry = None

    def __init__(self, *, direct_tools: dict[str, object] | None = None) -> None:
        self.instances = [
            SimpleNamespace(name="search_knowledge"),
            SimpleNamespace(name="web_search"),
        ]
        self._direct_tools = dict(direct_tools or {})

    def get_instance(self, name: str | None):
        return self._direct_tools.get(str(name or ""))


class _SkillRegistryStub:
    def format_active_skill_block(self, _active_skill):
        return None


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or ["search_knowledge", "web_search"])

    def can_invoke_tool(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=True, reason="")


class _ModelRuntimeStub:
    def __init__(self) -> None:
        self.last_tools: list[str] = []
        self.last_payload_messages: list[dict[str, str]] = []

    def create_conversation_agent(self, **kwargs):
        self.last_tools = [getattr(tool, "name", "") for tool in kwargs.get("tools", [])]
        recorder = {"tools": self.last_tools}
        agent = _FakeAgent(recorder)
        self._recorder = recorder
        return agent


def _build_runtime(
    *,
    rag_mode: bool,
    direct_tools: dict[str, object] | None = None,
    task_coordinator=None,
) -> tuple[QueryRuntime, _RetrievalStub, _ModelRuntimeStub, _MemoryFacadeStub]:
    retrieval = _RetrievalStub()
    model_runtime = _ModelRuntimeStub()
    memory_facade = _MemoryFacadeStub()
    runtime = QueryRuntime(
        base_dir=Path("."),
        settings_service=_SettingsStub(rag_mode=rag_mode),
        session_manager=SimpleNamespace(),
        memory_facade=memory_facade,
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(direct_tools=direct_tools),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=task_coordinator or TaskCoordinator(),
    )
    return runtime, retrieval, model_runtime, memory_facade


async def _seed_compound_tasks(coordinator: TaskCoordinator) -> None:
    executions = [
        QueryExecutionPlan(
            message="总结 PDF 第三页",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="pdf_analysis", task_kind="pdf_followup_query"),
        ),
        QueryExecutionPlan(
            message="给我 inventory.xlsx 里最缺货的前三个仓库",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
        ),
        QueryExecutionPlan(
            message="补一句北京天气",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="get_weather", task_kind="weather_query"),
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "done", "content": f"answer for {execution.message}"}

    async for _event in coordinator.run_query_tasks("session-1", executions, runner):
        pass


async def _collect_events(
    plan: QueryPlan,
    *,
    rag_mode: bool,
    direct_tools: dict[str, object] | None = None,
    use_execution_events: bool = False,
) -> tuple[list[dict[str, object]], _RetrievalStub, _ModelRuntimeStub, _MemoryFacadeStub]:
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(rag_mode=rag_mode, direct_tools=direct_tools)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    events: list[dict[str, object]] = []
    stream = (
        runtime._execution_events(plan.session_id, plan.message, plan.history)
        if use_execution_events
        else runtime._stream_single_execution(plan.session_id, plan.message, plan.history)
    )
    async for event in stream:
        events.append(event)
    return events, retrieval, model_runtime, memory_facade


def test_memory_route_disables_tools() -> None:
    plan = QueryPlan(
        session_id="memory-session",
        message="把今天这几个任务分成 PDF、数据表、实时查询三段总结。",
        history=[{"role": "assistant", "content": "已有上下文"}],
        subqueries=["把今天这几个任务分成 PDF、数据表、实时查询三段总结。"],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert not any(event.get("type") == "tool_start" for event in events)
    assert any(event.get("type") == "done" for event in events)
    done = [event for event in events if event.get("type") == "done"][-1]
    assert isinstance(done.get("main_context"), dict)
    assert done["main_context"]["active_work_item"] == "session_summary_query"


def test_rag_route_prefetches_retrieval_without_tools() -> None:
    plan = QueryPlan(
        session_id="rag-session",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == ["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"]
    assert memory_facade.prefetch_queries == ["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"]
    assert model_runtime.last_tools == []
    assert any(event.get("type") == "retrieval" for event in events)
    assert not any(event.get("type") == "tool_start" for event in events)
    stream_messages = list(getattr(model_runtime, "_recorder", {}).get("last_stream_payload", {}).get("messages", []))
    assert stream_messages
    assert stream_messages[0]["role"] == "system"
    assert "Main Working Context" in stream_messages[0]["content"]


def test_direct_tool_route_normalizes_final_content() -> None:
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "normalized tool answer", "debug": "ignored"})
    plan = QueryPlan(
        session_id="tool-session",
        message="请直接执行工具。",
        history=[],
        subqueries=["请直接执行工具。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "请直接执行工具。"},
        structured_binding=StructuredDatasetBinding(
            dataset_path="knowledge/E-commerce Data/inventory.xlsx",
            target_object="inventory",
            source="test",
            confidence=1.0,
        ),
        execution_kind="direct_tool",
    )
    events, _retrieval, model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"structured_data_analysis": tool},
        )
    )

    assert model_runtime.last_tools == []
    assert [event["type"] for event in events if event["type"] in {"tool_start", "tool_end", "done"}] == [
        "tool_start",
        "tool_end",
        "done",
    ]
    tool_start = next(event for event in events if event.get("type") == "tool_start")
    assert tool_start["structured_binding"]["dataset_path"].endswith("inventory.xlsx")
    assert events[-1]["content"] == "normalized tool answer"
    assert events[-2]["output"] == "normalized tool answer"
    assert str(events[-1]["task_id"]).startswith("tool-session-tool-structured_data_analysis-")
    assert isinstance(events[-1]["summary"], dict)
    assert isinstance(events[-1]["context_ref"], dict)
    assert isinstance(events[-1]["result_ref"], dict)
    assert events[-1]["main_context"]["followup_mode"] == "task_ref"
    assert events[-1]["main_context"]["followup_resolution_source"] == "task_record"
    assert events[-1]["main_context"]["followup_target_task_id"] == events[-1]["task_id"]
    assert events[-1]["main_context"]["followup_target_task_ids"] == [events[-1]["task_id"]]
    assert events[-1]["main_context"]["active_binding_identity"].endswith("inventory.xlsx")
    assert events[-1]["task_summary_refs"]
    assert str(events[-1]["task_summary_refs"][0]["task_id"]).startswith("tool-session-tool-structured_data_analysis-")


def test_semantic_memory_signal_keeps_rag_and_prefetches_durable() -> None:
    plan = QueryPlan(
        session_id="semantic-memory-signal",
        message="我们项目当前重点是什么？",
        history=[],
        subqueries=["我们项目当前重点是什么？"],
        memory_intent=MemoryIntent(
            intent="memory_read_signal",
            memory_read_mode="durable_exact",
            should_skip_rag=False,
            preferred_types=["project"],
            preferred_memory_classes=["work"],
        ),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == ["我们项目当前重点是什么？"]
    assert memory_facade.prefetch_queries == ["我们项目当前重点是什么？"]
    assert model_runtime.last_tools == []
    retrieval_index = next(i for i, event in enumerate(events) if event.get("type") == "retrieval")
    memory_index = next(i for i, event in enumerate(events) if event.get("type") == "memory_context")
    assert retrieval_index < memory_index


def test_general_memory_adjacent_query_still_prefetches_durable_context() -> None:
    plan = QueryPlan(
        session_id="general-memory-adjacent",
        message="以后我问复杂问题时，你应该先怎么回答？",
        history=[],
        subqueries=["以后我问复杂问题时，你应该先怎么回答？"],
        memory_intent=MemoryIntent(
            intent="general",
            memory_read_mode="none",
            should_skip_rag=False,
        ),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == ["以后我问复杂问题时，你应该先怎么回答？"]
    assert memory_facade.prefetch_queries == ["以后我问复杂问题时，你应该先怎么回答？"]
    assert model_runtime.last_tools == []
    assert any(event.get("type") == "memory_context" for event in events)


def test_execution_events_reuses_built_plan_for_subtasks() -> None:
    execution_a = QueryExecutionPlan(
        message="a",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
    )
    execution_b = QueryExecutionPlan(
        message="b",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
    )
    plan = QueryPlan(
        session_id="compound-session",
        message="a/b",
        history=[],
        subqueries=["a", "b"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="general_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
        executions=[execution_a, execution_b],
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    planner_calls = {"count": 0}

    def _build_plan(*, session_id, message, history):
        planner_calls["count"] += 1
        return plan

    runtime.planner.build_plan = _build_plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert planner_calls["count"] == 1
    subtask_end = [event for event in events if event.get("type") == "subtask_end"]
    assert len(subtask_end) == 2
    assert all(isinstance(event.get("summary"), dict) for event in subtask_end)
    assert all(isinstance(event.get("context_ref"), dict) for event in subtask_end)
    assert all(isinstance(event.get("result_ref"), dict) for event in subtask_end)
    assert events[-1]["type"] == "done"
    assert isinstance(events[-1].get("main_context"), dict)
    assert events[-1]["main_context"]["active_work_item"] == "compound_query"
    assert "1. a" in str(events[-1]["content"])
    assert "2. b" in str(events[-1]["content"])


def test_memory_route_does_not_promote_fake_tool_call_into_task_summary() -> None:
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    execution = QueryExecutionPlan(
        message="回忆一下之前的内容。",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
    )

    summary_refs = runtime._build_single_execution_task_summaries(
        execution,
        "<tool_call>structured_data_analysis(query='inventory.xlsx')</tool_call>",
    )

    assert summary_refs == []


def test_followup_task_ref_is_answered_without_replanning() -> None:
    coordinator = TaskCoordinator()
    asyncio.run(_seed_compound_tasks(coordinator))
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=True,
        task_coordinator=coordinator,
    )

    def _unexpected_plan(**_kwargs):
        raise AssertionError("planner should not run for direct follow-up task assembly")

    runtime.planner.build_plan = _unexpected_plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "session-1",
            "只展开第二个子任务，给我仓库和缺货量。",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert [event["type"] for event in events] == ["done"]
    done = events[0]
    assert done["main_context"]["active_work_item"] == "followup_task_result_assembly"
    assert done["main_context"]["followup_target_task_ids"] == ["session-1-subtask-2"]
    assert "inventory.xlsx" in str(done["content"])


def test_binding_followup_executes_from_owner_task_without_replanning() -> None:
    coordinator = TaskCoordinator()
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "三条行动建议：先立规则，再建审计，最后做责任归口。"})
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"pdf_analysis": tool},
        task_coordinator=coordinator,
    )

    initial_plan = QueryPlan(
        session_id="binding-session",
        message="现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
        history=[],
        subqueries=["现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_overview_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="pdf",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={
            "query": "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
            "path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
        },
        execution_kind="direct_tool",
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: initial_plan  # type: ignore[method-assign]

    async def _seed() -> None:
        async for _event in runtime._execution_events(
            "binding-session",
            initial_plan.message,
            [],
        ):
            pass

    asyncio.run(_seed())

    def _unexpected_plan(**_kwargs):
        raise AssertionError("planner should not run for binding follow-up execution")

    runtime.planner.build_plan = _unexpected_plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "binding-session",
            "把这份 PDF 的核心结论压成三条行动建议。",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert "tool_start" in [event["type"] for event in events]
    done = next(event for event in reversed(events) if event.get("type") == "done")
    assert done["followup_mode"] == "binding_ref"
    assert done["main_context"]["active_work_item"] == "followup_task_binding_execution"
    assert done["main_context"]["followup_mode"] == "binding_ref"
    assert done["main_context"]["followup_resolution_source"] == "task_registry_binding"
    assert done["main_context"]["followup_binding_key"] == "active_pdf"
    assert done["main_context"]["followup_binding_identity"].endswith(".pdf")
    assert done["main_context"]["active_binding_identity"].endswith(".pdf")
    assert done["main_context"]["followup_target_task_id"]
    assert done["main_context"]["active_constraints"]["active_pdf"].endswith(".pdf")
    assert done["task_summary_refs"]
    assert done["task_summary_refs"][0]["task_id"] == done["main_context"]["followup_target_task_id"]


def test_ambiguous_binding_followup_requests_clarification_without_replanning() -> None:
    coordinator = TaskCoordinator()
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "unused"})
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"structured_data_analysis": tool},
        task_coordinator=coordinator,
    )

    async def _seed_tasks() -> None:
        executions = [
            QueryExecutionPlan(
                message="给我 inventory.xlsx 里最缺货的前三个仓库",
                history=[],
                memory_intent=MemoryIntent(),
                query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
            ),
            QueryExecutionPlan(
                message="给我 employees.xlsx 里薪资最高的前三个人",
                history=[],
                memory_intent=MemoryIntent(),
                query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
            ),
        ]

        async def runner(execution: QueryExecutionPlan):
            yield {"type": "done", "content": f"answer for {execution.message}"}

        async for _event in coordinator.run_query_tasks("ambiguous-binding-session", executions, runner):
            pass

    asyncio.run(_seed_tasks())

    def _unexpected_plan(**_kwargs):
        raise AssertionError("planner should not run when follow-up resolution requests clarification")

    runtime.planner.build_plan = _unexpected_plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "ambiguous-binding-session",
            "把那个表按仓库展开一下。",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert [event["type"] for event in events] == ["done"]
    done = events[0]
    assert done["followup_mode"] == "clarify"
    assert "请直接说文件名" in str(done["content"])
    assert done["main_context"]["active_work_item"] == "clarify_followup_owner"
    assert done["main_context"]["followup_mode"] == "clarify"
    assert done["main_context"]["followup_resolution_source"] == "task_registry_binding"
    assert done["task_summary_refs"] == []


def test_runtime_output_boundary_strips_internal_protocol_from_streamed_answer() -> None:
    plan = QueryPlan(
        session_id="protocol-session",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我来检索本地知识库。</think>**工具调用:**\n```json\n"
                            "[{\"name\":\"search_knowledge\"}]\n```\n\n---\n\n"
                            "**工具输出:**\n[搜索结果 失败]\n\n"
                            "**结论：本地知识库当前为空，无法基于知识库回答该问题。**\n\n"
                            "岩，目前 knowledge 目录下没有任何文档。"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    token_text = "".join(str(event.get("content", "")) for event in events if event.get("type") == "token")
    done_text = str(events[-1]["content"])
    assert "</think>" not in token_text
    assert "**工具调用:**" not in token_text
    assert "<tool_call" not in done_text
    assert "**工具输出:**" not in done_text
    assert "本地知识库当前为空" in done_text


def test_runtime_output_boundary_keeps_final_stream_answer_when_ai_update_is_partial() -> None:
    plan = QueryPlan(
        session_id="protocol-stream-wins",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="ai",
                                content="我需要先检索本地知识库中的相关内容，然后再给出结论。",
                                tool_calls=[],
                            )
                        ]
                    }
                },
            ),
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我来检索本地知识库。</think>**工具调用:**\n```json\n"
                            "[{\"name\":\"search_knowledge\"}]\n```\n\n---\n\n"
                            "**工具输出:**\n[搜索结果 失败]\n\n"
                            "**结论：本地知识库当前为空，无法基于知识库回答该问题。**\n\n"
                            "岩，目前 knowledge 目录下没有任何文档。"
                        )
                    ),
                    {},
                ),
            ),
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert done_text
    assert "本地知识库当前为空" in done_text
    assert "我需要先检索本地知识库中的相关内容" not in done_text


def test_runtime_output_boundary_strips_inline_pseudo_tool_calls_from_visible_answer() -> None:
    plan = QueryPlan(
        session_id="pseudo-tool-call",
        message="把这三类风险改写成适合周会汇报的三条。",
        history=[],
        subqueries=["把这三类风险改写成适合周会汇报的三条。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我需要先检索本地知识库中关于 AI 治理风险的内容，然后为您改写成周会汇报格式。"
                            "search_knowledge(query=\"AI 治理 风险 类型\", top_k=5)"
                            "search_knowledge(query=\"人工智能 治理 常见风险\", top_k=5)"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert done_text
    assert "search_knowledge(" not in done_text
    assert "我需要先检索本地知识库中关于 AI 治理风险的内容" not in done_text
    assert "已检索到相关资料，但当前模型尚未产出可直接展示的结论。" == done_text


def test_runtime_output_boundary_salvages_nonempty_answer_when_only_procedural_text_remains() -> None:
    plan = QueryPlan(
        session_id="protocol-salvage",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我来检索本地知识库中关于 AI 治理风险的相关内容。\n\n"
                            "我将使用 search_knowledge 工具查询本地知识库。</think>"
                            "**工具调用:**\n```json\n[{\"name\":\"search_knowledge\"}]\n```"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert done_text
    assert "</think>" not in done_text
    assert "**工具调用:**" not in done_text
    assert "我来检索本地知识库中关于 AI 治理风险的相关内容" not in done_text
    assert "已检索到相关资料，但当前模型尚未产出可直接展示的结论。" == done_text


def test_runtime_output_boundary_does_not_promote_plain_tool_output_to_done_content() -> None:
    plan = QueryPlan(
        session_id="tool-output-leak-guard",
        message="把库存表按缺货量给我看结果。",
        history=[],
        subqueries=["把库存表按缺货量给我看结果。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="ai",
                                content="我先读取库存表，再整理答案。",
                                tool_calls=[
                                    {
                                        "id": "call-1",
                                        "name": "structured_data_analysis",
                                        "args": {"path": "knowledge/E-commerce Data/inventory.xlsx"},
                                    }
                                ],
                            )
                        ]
                    }
                },
            ),
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="tool",
                                tool_call_id="call-1",
                                name="structured_data_analysis",
                                content="warehouse,shortage\nEast,12\nNorth,9",
                            )
                        ]
                    }
                },
            ),
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert "warehouse,shortage" not in done_text
    assert "East,12" not in done_text
    assert "工具 `structured_data_analysis` 已执行，但当前结果尚未形成可直接展示的答案。" == done_text


def test_direct_tool_pdf_raw_browse_dump_does_not_become_done_content() -> None:
    raw_pdf_dump = (
        "Source: knowledge/test.pdf\n"
        "Mode: PDF browse\n"
        "Relevant pages:\n"
        "[P12] score=0.91\n"
        "[P18] score=0.84\n"
        "Page snippet: raw dump should not be exposed directly."
    )
    tool = SimpleNamespace(invoke=lambda _tool_input: raw_pdf_dump)
    plan = QueryPlan(
        session_id="pdf-dump-session",
        message="打开这份 PDF，告诉我结论。",
        history=[],
        subqueries=["打开这份 PDF，告诉我结论。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_overview_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="pdf",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "打开这份 PDF，告诉我结论。", "path": "knowledge/test.pdf"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"pdf_analysis": tool},
        )
    )

    done_text = str(events[-1]["content"])
    assert "Source:" not in done_text
    assert "Mode: PDF browse" not in done_text
    assert "P12" in done_text
    assert "P18" in done_text


def test_direct_tool_plain_table_dump_does_not_become_done_content() -> None:
    raw_table_dump = "warehouse,shortage\nEast,12\nNorth,9"
    tool = SimpleNamespace(invoke=lambda _tool_input: raw_table_dump)
    plan = QueryPlan(
        session_id="table-dump-session",
        message="直接执行库存表工具。",
        history=[],
        subqueries=["直接执行库存表工具。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            task_kind="structured_followup_query",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "直接执行库存表工具。", "path": "knowledge/E-commerce Data/inventory.xlsx"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"structured_data_analysis": tool},
        )
    )

    done_text = str(events[-1]["content"])
    assert "warehouse,shortage" not in done_text
    assert "East,12" not in done_text
    assert "工具 `structured_data_analysis` 已执行，但当前结果尚未形成可直接展示的答案。" == done_text


def test_assistant_message_persistence_uses_canonical_visible_content() -> None:
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)

    messages = runtime._build_assistant_messages(
        [
            {
                "content": (
                    "好的，开始处理。</think><tool_call>terminal::run_command</tool_call>\n"
                    "**结论：先检查 workspace 的安全边界。**"
                ),
                "tool_calls": [],
            }
        ]
    )

    assert len(messages) == 1
    assert "</think>" not in messages[0]["content"]
    assert "<tool_call" not in messages[0]["content"]
    assert "先检查 workspace 的安全边界" in messages[0]["content"]


def test_output_boundary_strips_search_protocol_tail_from_visible_answer() -> None:
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)

    messages = runtime._build_assistant_messages(
        [
            {
                "content": (
                    "岩，上一轮我并没有给出三类风险。\n\n"
                    "现在我再检索一次本地知识库，看是否有 AI 治理相关内容："
                    "search_knowledge 查询本地知识库中关于 AI 治理风险的内容。"
                    "{\n\"query\": \"AI 治理 风险 类型 分类\",\n\"top_k\": 5\n}"
                ),
                "tool_calls": [],
            }
        ]
    )

    assert len(messages) == 1
    assert "search_knowledge" not in messages[0]["content"]
    assert "\"top_k\"" not in messages[0]["content"]
    assert "上一轮我并没有给出三类风险" in messages[0]["content"]


def main() -> None:
    test_memory_route_disables_tools()
    test_rag_route_prefetches_retrieval_without_tools()
    test_direct_tool_route_normalizes_final_content()
    test_semantic_memory_signal_keeps_rag_and_prefetches_durable()
    test_execution_events_reuses_built_plan_for_subtasks()
    test_memory_route_does_not_promote_fake_tool_call_into_task_summary()
    test_followup_task_ref_is_answered_without_replanning()
    test_runtime_output_boundary_strips_internal_protocol_from_streamed_answer()
    test_runtime_output_boundary_keeps_final_stream_answer_when_ai_update_is_partial()
    test_runtime_output_boundary_strips_inline_pseudo_tool_calls_from_visible_answer()
    test_runtime_output_boundary_salvages_nonempty_answer_when_only_procedural_text_remains()
    test_runtime_output_boundary_does_not_promote_plain_tool_output_to_done_content()
    test_direct_tool_pdf_raw_browse_dump_does_not_become_done_content()
    test_direct_tool_plain_table_dump_does_not_become_done_content()
    test_assistant_message_persistence_uses_canonical_visible_content()
    test_output_boundary_strips_search_protocol_tail_from_visible_answer()
    print("ALL PASSED (query runtime route guard regression)")


if __name__ == "__main__":
    main()
