from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .invocation_loop import run_agent_invocation_stream
from .request import AgentRunRequest


class AgentRuntime:
    """Formal runtime entry for one agent invocation.

    AgentRuntime owns the single-agent control loop. The injected host provides
    durable runtime services such as event logs, checkpoints, state indexes,
    operation gates, model/tool execution, and artifact stores.
    """

    def __init__(self, *, task_run_loop: Any) -> None:
        self._task_run_loop = task_run_loop

    @property
    def state_index(self) -> Any:
        return self._task_run_loop.state_index

    async def run_stream(self, request: AgentRunRequest) -> AsyncIterator[dict[str, Any]]:
        async for event in run_agent_invocation_stream(self._task_run_loop, request):
            yield event

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self._task_run_loop.state_index.get_task_run(task_run_id)

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self._task_run_loop.get_trace(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return len(self._task_run_loop.event_log.list_events(task_run_id))
