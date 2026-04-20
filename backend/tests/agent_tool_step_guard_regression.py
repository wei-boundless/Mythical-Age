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
        tool_calls = [
            {"id": f"call-{index}", "name": "mock_tool", "args": {"step": index}}
            for index in range(1, 10)
        ]
        yield (
            "updates",
            {
                "model": {
                    "messages": [
                        SimpleNamespace(
                            type="ai",
                            tool_calls=tool_calls,
                            content="",
                        )
                    ]
                }
            },
        )


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return False


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


class _ToolRuntimeStub:
    registry = None
    instances: list[object] = []

    def get_instance(self, _name: str | None):
        return None


class _SkillRegistryStub:
    def format_active_skill_block(self, _active_skill):
        return None


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or [])


class _ModelRuntimeStub:
    def create_conversation_agent(self, **_kwargs):
        return _FakeAgent()


def _build_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=Path("."),
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
        task_coordinator=SimpleNamespace(),
    )


async def _collect_events() -> list[dict[str, object]]:
    runtime = _build_runtime()
    fake_intent = MemoryIntent()
    fake_query = QueryUnderstanding(
        intent="general_query",
        route="agent",
        should_skip_rag=True,
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: QueryPlan(  # type: ignore[method-assign]
        session_id=session_id,
        message=message,
        history=history,
        subqueries=[message],
        memory_intent=fake_intent,
        query_understanding=fake_query,
        active_skill=None,
    )

    events: list[dict[str, object]] = []
    async for event in runtime._stream_single_execution("session-1", "Test tool loop guard", []):
        events.append(event)
    return events


def test_agent_stops_when_tool_steps_exceed_limit() -> None:
    events = asyncio.run(_collect_events())
    tool_starts = [event for event in events if event.get("type") == "tool_start"]
    done_events = [event for event in events if event.get("type") == "done"]

    assert len(tool_starts) == 8
    assert done_events
    assert done_events[-1].get("content") == "调用工具失败"


def main() -> None:
    test_agent_stops_when_tool_steps_exceed_limit()
    print("ALL PASSED (agent tool step guard)")


if __name__ == "__main__":
    main()
