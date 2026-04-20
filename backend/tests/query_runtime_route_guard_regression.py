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
        self.recorder["stream_called"] = True
        yield ("messages", (SimpleNamespace(content="route-safe answer"), {}))


class _SettingsStub:
    def __init__(self, *, rag_mode: bool) -> None:
        self._rag_mode = rag_mode

    def get_rag_mode(self) -> bool:
        return self._rag_mode


class _MemoryFacadeStub:
    def compact_history_for_query(self, _session_id: str, history: list[dict[str, object]]):
        return history, {"pressure_level": "normal"}

    def inspect_query_context(self, *_args, **_kwargs):
        return {}

    def build_context_package(self, *_args, **_kwargs):
        return None

    def build_persistent_memory_block(self, *_args, **_kwargs):
        return ""

    def prefetch_relevant_notes(self, *_args, **_kwargs):
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

    def create_conversation_agent(self, **kwargs):
        self.last_tools = [getattr(tool, "name", "") for tool in kwargs.get("tools", [])]
        return _FakeAgent({"tools": self.last_tools})


def _build_runtime(
    *,
    rag_mode: bool,
    direct_tools: dict[str, object] | None = None,
    task_coordinator=None,
) -> tuple[QueryRuntime, _RetrievalStub, _ModelRuntimeStub]:
    retrieval = _RetrievalStub()
    model_runtime = _ModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=Path("."),
        settings_service=_SettingsStub(rag_mode=rag_mode),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(direct_tools=direct_tools),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=task_coordinator or TaskCoordinator(),
    )
    return runtime, retrieval, model_runtime


async def _collect_events(
    plan: QueryPlan,
    *,
    rag_mode: bool,
    direct_tools: dict[str, object] | None = None,
    use_execution_events: bool = False,
) -> tuple[list[dict[str, object]], _RetrievalStub, _ModelRuntimeStub]:
    runtime, retrieval, model_runtime = _build_runtime(rag_mode=rag_mode, direct_tools=direct_tools)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    events: list[dict[str, object]] = []
    stream = (
        runtime._execution_events(plan.session_id, plan.message, plan.history)
        if use_execution_events
        else runtime._stream_single_execution(plan.session_id, plan.message, plan.history)
    )
    async for event in stream:
        events.append(event)
    return events, retrieval, model_runtime


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
    events, retrieval, model_runtime = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == []
    assert model_runtime.last_tools == []
    assert not any(event.get("type") == "tool_start" for event in events)
    assert any(event.get("type") == "done" for event in events)


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
    events, retrieval, model_runtime = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == ["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"]
    assert model_runtime.last_tools == []
    assert any(event.get("type") == "retrieval" for event in events)
    assert not any(event.get("type") == "tool_start" for event in events)


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
    events, _retrieval, model_runtime = asyncio.run(
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
    runtime, _retrieval, _model_runtime = _build_runtime(rag_mode=False)
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
    assert events[-1]["type"] == "done"
    assert "1. a" in str(events[-1]["content"])
    assert "2. b" in str(events[-1]["content"])


def main() -> None:
    test_memory_route_disables_tools()
    test_rag_route_prefetches_retrieval_without_tools()
    test_direct_tool_route_normalizes_final_content()
    test_execution_events_reuses_built_plan_for_subtasks()
    print("ALL PASSED (query runtime route guard regression)")


if __name__ == "__main__":
    main()
