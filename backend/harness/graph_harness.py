from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph.loop import GraphLoop, GraphLoopAdvance, GraphLoopStart
from .graph.models import GraphHarnessConfig, NodeResultEnvelope
from .graph.runtime import GraphRuntime, GraphRuntimeStart


@dataclass(frozen=True, slots=True)
class GraphHarnessStart:
    task_run: Any
    coordination_run: Any
    envelope: Any
    loop_state: Any
    checkpoint: dict[str, Any]
    node_work_orders: tuple[Any, ...] = ()
    events: tuple[dict[str, Any], ...] = ()

    @property
    def node_work_order(self) -> dict[str, Any]:
        return self.node_work_orders[0].to_dict() if self.node_work_orders else {}


class GraphHarness:
    """Production facade for graph task control.

    It owns GraphRuntime and GraphLoop composition. Agent node execution remains
    delegated to AgentHarness outside the graph loop.
    """

    def __init__(self, *, services: Any, agent_harness: Any | None = None) -> None:
        self._services = services
        self._agent_harness = agent_harness
        self._runtime = GraphRuntime(services=services)
        self._loop = GraphLoop(services=services)

    @property
    def graph_loop(self) -> GraphLoop:
        return self._loop

    @property
    def state_index(self) -> Any:
        return self._services.state_index

    def start_run(
        self,
        *,
        session_id: str,
        task_id: str,
        graph_config: GraphHarnessConfig,
        initial_inputs: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> GraphHarnessStart:
        runtime_start: GraphRuntimeStart = self._runtime.start(
            session_id=session_id,
            task_id=task_id,
            graph_config=graph_config,
            initial_inputs=dict(initial_inputs or {}),
            diagnostics=dict(diagnostics or {}),
        )
        loop_start: GraphLoopStart = self._loop.initialize(
            graph_config=graph_config,
            envelope=runtime_start.envelope,
        )
        return GraphHarnessStart(
            task_run=runtime_start.task_run,
            coordination_run=runtime_start.coordination_run,
            envelope=runtime_start.envelope,
            loop_state=loop_start.loop_state,
            checkpoint=loop_start.checkpoint,
            node_work_orders=loop_start.node_work_orders,
            events=tuple([*runtime_start.events, *loop_start.events]),
        )

    def accept_node_result(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        result: NodeResultEnvelope | dict[str, Any],
    ) -> GraphLoopAdvance:
        return self._loop.accept_node_result(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            result=result,
        )

    def get_checkpoint_state(self, graph_run_id: str) -> dict[str, Any]:
        state = self._loop.get_state(graph_run_id)
        return state.to_dict() if state is not None else {}

    def get_coordination_run(self, graph_run_id: str) -> Any | None:
        return self.state_index.get_coordination_run(graph_run_id)

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self._services.get_trace(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return self._services.event_count(task_run_id)

