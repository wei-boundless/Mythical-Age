from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_system import GraphSystem
    from .runtime import AgentRuntimeServices, SingleAgentRuntimeHost

__all__ = [
    "GraphSystem",
    "AgentRuntimeServices",
    "SingleAgentRuntimeHost",
]


def __getattr__(name: str):
    if name == "GraphSystem":
        from .graph_system import GraphSystem

        return GraphSystem
    if name in {"AgentRuntimeServices", "SingleAgentRuntimeHost"}:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(name)


