from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .invocation_loop import run_agent_invocation_stream
from .request import AgentRunRequest
from .services import AgentRuntimeServices


class AgentRuntime:
    """Formal runtime entry for one agent invocation.

    AgentRuntime owns the single-agent control loop. The injected host provides
    durable runtime services such as event logs, checkpoints, state indexes,
    operation gates, model/tool execution, and artifact stores.
    """

    def __init__(self, *, services: AgentRuntimeServices) -> None:
        self._services = services

    @property
    def state_index(self) -> Any:
        return self._services.state_index

    async def run_stream(self, request: AgentRunRequest) -> AsyncIterator[dict[str, Any]]:
        async for event in run_agent_invocation_stream(self._services, request):
            yield event

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self._services.get_task_run(task_run_id)

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self._services.get_trace(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return self._services.event_count(task_run_id)
