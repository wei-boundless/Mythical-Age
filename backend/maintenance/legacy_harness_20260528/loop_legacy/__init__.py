from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_lifecycle import AgentRuntimeStartResult
    from .agent_model_turn import AgentModelTurnInput
    from .agent_turn_loop import AgentTurnLoopInput, AgentTurnLoopResult
    from .graph_loop import GraphLoop

__all__ = [
    "AgentModelTurnInput",
    "AgentRuntimeStartResult",
    "AgentTurnLoopInput",
    "AgentTurnLoopResult",
    "GraphLoop",
    "build_graph_flow_state",
    "run_agent_invocation_stream",
    "run_agent_model_turn",
    "run_agent_turn_loop",
    "run_coordination_delivery_stream",
]


def __getattr__(name: str):
    if name == "AgentRuntimeStartResult":
        from .agent_lifecycle import AgentRuntimeStartResult

        return AgentRuntimeStartResult
    if name in {"run_agent_invocation_stream"}:
        from .agent_loop import run_agent_invocation_stream

        return run_agent_invocation_stream
    if name in {"AgentModelTurnInput", "run_agent_model_turn"}:
        from . import agent_model_turn

        return getattr(agent_model_turn, name)
    if name in {"AgentTurnLoopInput", "AgentTurnLoopResult", "run_agent_turn_loop"}:
        from . import agent_turn_loop

        return getattr(agent_turn_loop, name)
    if name == "run_coordination_delivery_stream":
        from .coordination_delivery import run_coordination_delivery_stream

        return run_coordination_delivery_stream
    if name == "build_graph_flow_state":
        from .graph_flow import build_graph_flow_state

        return build_graph_flow_state
    if name == "GraphLoop":
        from .graph_loop import GraphLoop

        return GraphLoop
    raise AttributeError(name)


