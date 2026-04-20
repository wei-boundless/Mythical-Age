from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
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
    assert events[-1]["content"] == "normalized tool answer"
    assert events[-2]["output"] == "normalized tool answer"


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


def main() -> None:
    test_memory_route_disables_tools()
    test_rag_route_prefetches_retrieval_without_tools()
    test_direct_tool_route_normalizes_final_content()
    test_semantic_memory_signal_keeps_rag_and_prefetches_durable()
    test_execution_events_reuses_built_plan_for_subtasks()
    test_memory_route_does_not_promote_fake_tool_call_into_task_summary()
    print("ALL PASSED (query runtime route guard regression)")


if __name__ == "__main__":
    main()
