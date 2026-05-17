from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from execution.model_response import ModelResponseRuntimeExecutor
from execution.model_runtime import ModelRuntimeError
from orchestration import RuntimeDirective


def _directive() -> RuntimeDirective:
    return RuntimeDirective(
        directive_id="directive:test",
        task_id="task:test",
        plan_ref="plan:test",
        stage_ref="stage:test",
        executor_type="model",
        adopted_resource_policy_ref="resource:test",
        execution_graph_ref="graph:test",
    )


class _RecoveringRuntime:
    async def astream_messages(self, _messages):
        yield SimpleNamespace(content="partial")
        raise ModelRuntimeError(
            code="provider_unavailable",
            provider="deepseek",
            model="deepseek-v4-pro",
            detail="ReadError",
            retryable=True,
            user_message="模型服务暂时不可用，请稍后重试。",
        )

    async def invoke_messages(self, _messages):
        return SimpleNamespace(content="complete recovered content")


def test_stream_retryable_error_falls_back_to_real_non_stream_invoke() -> None:
    executor = ModelResponseRuntimeExecutor(model_runtime=_RecoveringRuntime())

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={"enabled": True, "fallback_to_non_stream_on_error": True},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "content_delta" and event.get("content") == "partial" for event in events)
    assert any(
        event.get("type") == "stream_recovery" and event.get("status") == "recovered"
        for event in events
    )
    assert not any(event.get("type") == "error" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "complete recovered content"
