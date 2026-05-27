from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_harness import AgentHarness
    from .graph_harness import GraphHarness
    from .runtime import AgentRunRequest, AgentRuntimeServices, CoordinationStageAgentRunRequest
    from .service_host import HarnessServiceHost

__all__ = [
    "AgentHarness",
    "AgentRunRequest",
    "AgentRuntimeServices",
    "CoordinationStageAgentRunRequest",
    "GraphHarness",
    "HarnessServiceHost",
]


def __getattr__(name: str):
    if name == "AgentHarness":
        from .agent_harness import AgentHarness

        return AgentHarness
    if name == "GraphHarness":
        from .graph_harness import GraphHarness

        return GraphHarness
    if name in {"AgentRunRequest", "AgentRuntimeServices", "CoordinationStageAgentRunRequest"}:
        from . import runtime

        return getattr(runtime, name)
    if name == "HarnessServiceHost":
        from .service_host import HarnessServiceHost

        return HarnessServiceHost
    raise AttributeError(name)


