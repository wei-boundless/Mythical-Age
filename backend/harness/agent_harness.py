from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .loop.agent_loop import run_agent_invocation_stream
from .runtime import AgentRunRequest, AgentRuntimeServices


class AgentHarness:
    """Production control facade for one agent invocation.

    The harness owns the control boundary. Runtime assembly prepares the
    staged context packet; the loop advances model/tool state through the
    permitted service table.
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
