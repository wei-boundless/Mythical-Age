from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from graph.agent import AgentManager
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


async def _collect_events() -> list[dict[str, object]]:
    manager = AgentManager()
    manager.base_dir = Path(".")
    manager.memory_bridge = None
    manager.rag_router = None
    manager._build_agent = lambda *args, **kwargs: _FakeAgent()  # type: ignore[method-assign]
    manager._resolve_active_skill = lambda *args, **kwargs: None  # type: ignore[method-assign]

    fake_intent = MemoryIntent()
    fake_query = QueryUnderstanding(
        intent="general_query",
        route="agent",
        should_skip_rag=True,
    )

    events: list[dict[str, object]] = []
    with patch("graph.agent.analyze_memory_intent", return_value=fake_intent), patch(
        "graph.agent.analyze_query_understanding", return_value=fake_query
    ):
        async for event in manager._astream_single("session-1", "Test tool loop guard", []):
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
