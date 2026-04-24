from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
from query.models import QueryPlan
from understanding import MemoryIntent, QueryUnderstanding


class _FakeAgent:
    async def astream(self, *_args, **_kwargs):
        yield ("messages", (SimpleNamespace(content="当前还没有形成真实查询结果。"), {}))


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return True


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
        return []


class _ToolRuntimeStub:
    registry = None

    def __init__(self) -> None:
        self.instances = [
            SimpleNamespace(name="search_knowledge"),
            SimpleNamespace(name="web_search"),
            SimpleNamespace(name="structured_data_analysis"),
        ]

    def get_instance(self, _name: str | None):
        return None


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or [])

    def can_invoke_tool(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=True, reason="")


class _ModelRuntimeStub:
    def __init__(self) -> None:
        self.last_tools: list[str] = []

    def create_conversation_agent(self, **kwargs):
        self.last_tools = [getattr(tool, "name", "") for tool in kwargs.get("tools", [])]
        return _FakeAgent()


def _build_runtime() -> tuple[QueryRuntime, _RetrievalStub, _ModelRuntimeStub]:
    retrieval = _RetrievalStub()
    model_runtime = _ModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=Path("."),
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=SimpleNamespace(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=SimpleNamespace(),
    )
    return runtime, retrieval, model_runtime


async def _collect_events(plan: QueryPlan) -> tuple[list[dict[str, object]], _RetrievalStub, _ModelRuntimeStub]:
    runtime, retrieval, model_runtime = _build_runtime()
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    events: list[dict[str, object]] = []
    async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
        events.append(event)
    return events, retrieval, model_runtime


def test_bounded_agent_exposes_bounded_tools_without_rag_retrieval() -> None:
    plan = QueryPlan(
        session_id="bounded-agent-session",
        message="他今年还在打比赛吗",
        history=[],
        subqueries=["他今年还在打比赛吗"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="general_query",
            route="agent",
            execution_posture="bounded_agent",
            direct_route_reason="freshness_aware_lookup",
            candidate_tools=["search_knowledge", "web_search"],
            tool_input={"query": "他今年还在打比赛吗"},
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime = asyncio.run(_collect_events(plan))

    assert retrieval.queries == []
    assert model_runtime.last_tools == ["search_knowledge", "web_search"]
    done = events[-1]
    assert done["content"] == "当前还没有形成真实查询结果。"
    assert done["answer_source"] == "segment.visible_text"


def main() -> None:
    test_bounded_agent_exposes_bounded_tools_without_rag_retrieval()
    print("ALL PASSED (unresolved lookup regression)")


if __name__ == "__main__":
    main()
