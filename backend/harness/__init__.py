from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_harness import AgentHarness
    from .graph_harness import GraphHarness
    from .runtime import AgentRunRequest, AgentRuntimeServices, SingleAgentRuntimeHost

__all__ = [
    "AgentHarness",
    "GraphHarness",
    "AgentRunRequest",
    "AgentRuntimeServices",
    "SingleAgentRuntimeHost",
]


def __getattr__(name: str):
    if name == "AgentHarness":
        from .agent_harness import AgentHarness

        return AgentHarness
    if name == "GraphHarness":
        from .graph_harness import GraphHarness

        return GraphHarness
    if name in {"AgentRunRequest", "AgentRuntimeServices", "SingleAgentRuntimeHost"}:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(name)


