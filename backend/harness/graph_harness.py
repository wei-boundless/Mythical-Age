from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph.loop import GraphLoop, GraphLoopAdvance, GraphLoopStart
from .graph.models import GraphHarnessConfig, NodeResultEnvelope
from .graph.runtime import GraphRuntime, GraphRuntimeStart


@dataclass(frozen=True, slots=True)
class GraphHarnessStart:
    task_run: Any
    graph_run: Any
    envelope: Any
    loop_state: Any
    checkpoint: dict[str, Any]
    node_work_orders: tuple[Any, ...] = ()
    events: tuple[dict[str, Any], ...] = ()

    @property
    def node_work_order(self) -> dict[str, Any]:
        return self.node_work_orders[0].to_dict() if self.node_work_orders else {}

    @property
    def graph_run_id(self) -> str:
        return str(getattr(self.graph_run, "graph_run_id", "") or "")


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
        dispatch_ready: bool = True,
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
            dispatch_ready=dispatch_ready,
        )
        return GraphHarnessStart(
            task_run=runtime_start.task_run,
            graph_run=runtime_start.graph_run,
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

    def get_graph_run(self, graph_run_id: str) -> Any | None:
        try:
            payload = self._services.runtime_objects.get_object(f"rtobj:graph_run:{_safe_ref_id(graph_run_id)}")
        except ValueError:
            return None
        if not payload:
            return None
        return payload

    def get_task_run(self, task_run_id: str) -> Any | None:
        return self.state_index.get_task_run(task_run_id)

    def get_graph_run_monitor(self, graph_run_id: str, *, graph_config: GraphHarnessConfig | None = None) -> dict[str, Any] | None:
        state = self._loop.get_state(graph_run_id)
        graph_run = self.get_graph_run(graph_run_id)
        if state is None and graph_run is None:
            return None
        config_payload = graph_config.to_dict() if graph_config is not None else {}
        task_run_id = state.task_run_id if state is not None else str(dict(graph_run or {}).get("task_run_id") or "")
        events = self._services.event_log.list_events(task_run_id) if task_run_id else []
        return {
            "authority": "harness.graph_run_monitor",
            "graph_run_id": graph_run_id,
            "graph_run": graph_run or {},
            "task_run": self.get_task_run(task_run_id).to_dict() if task_run_id and self.get_task_run(task_run_id) is not None else None,
            "graph_harness_config": config_payload,
            "graph_loop_state": state.to_dict() if state is not None else {},
            "events": [item.to_dict() for item in events],
            "event_count": len(events),
        }

    def get_trace(self, task_run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self._services.get_trace(task_run_id, **kwargs)

    def event_count(self, task_run_id: str) -> int:
        return self._services.event_count(task_run_id)


def _safe_ref_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]
