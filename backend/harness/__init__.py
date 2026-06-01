from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_harness import GraphHarness
    from .runtime import AgentRuntimeServices, SingleAgentRuntimeHost

__all__ = [
    "GraphHarness",
    "AgentRuntimeServices",
    "SingleAgentRuntimeHost",
]


def __getattr__(name: str):
    if name == "GraphHarness":
        from .graph_harness import GraphHarness

        return GraphHarness
    if name in {"AgentRuntimeServices", "SingleAgentRuntimeHost"}:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(name)


