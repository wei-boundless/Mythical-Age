from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.model_gateway.model_response import ModelResponseRuntimeExecutor
from orchestration.runtime_directive import RuntimeDirective


def test_model_executor_does_not_fabricate_subagent_tool_call_when_model_answers() -> None:
    class _Runtime:
        async def invoke_messages(self, _messages):
            return SimpleNamespace(content="第二部分的约束是旧摘要里的两句话。")

    directive = RuntimeDirective(
        directive_id="runtime-directive:test:model",
        task_id="task:auto-subagent",
        plan_ref="plan:test",
        stage_ref="stage:test",
        executor_type="model",
        adopted_resource_policy_ref="respol:test",
        operation_refs=("op.model_response",),
    )
    executor = ModelResponseRuntimeExecutor(model_runtime=_Runtime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in executor.stream(
            user_message="再回到 PDF，第二部分的约束能不能只用两句话说清楚？",
            model_messages=[],
            directive=directive,
            tool_instances=[],
        ):
            events.append(event)
        return events

    events = __import__("asyncio").run(_collect())

    assert all(event["type"] != "tool_call_requested" for event in events)
    assert events[-1]["type"] == "done"
    assert "第二部分的约束是旧摘要里的两句话。" in str(events[-1]["content"])



def test_model_executor_does_not_auto_subagent_for_direct_web_search_lane() -> None:
    class _Runtime:
        async def invoke_messages(self, _messages):
            return SimpleNamespace(content="需要联网查询后回答。")

    directive = RuntimeDirective(
        directive_id="runtime-directive:test:web",
        task_id="task:web-search",
        plan_ref="plan:test",
        stage_ref="stage:test",
        executor_type="model",
        adopted_resource_policy_ref="respol:test",
        operation_refs=("op.model_response", "op.web_search"),
    )
    executor = ModelResponseRuntimeExecutor(model_runtime=_Runtime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in executor.stream(
            user_message="北京今天天气怎么样，直接给温度范围和时间口径。",
            model_messages=[],
            directive=directive,
            tool_instances=[],
        ):
            events.append(event)
        return events

    events = __import__("asyncio").run(_collect())

    assert all(event["type"] != "tool_call_requested" for event in events)
    assert events[-1]["type"] == "done"


