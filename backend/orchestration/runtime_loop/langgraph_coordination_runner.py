from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from tasks.coordination_graph_models import TaskGraphRuntimeSpec


class CoordinationGraphRuntimeState(TypedDict, total=False):
    task_run_id: str
    coordination_run_id: str
    visited_node_ids: Annotated[list[str], operator.add]
    traversal_nodes: Annotated[list[dict[str, Any]], operator.add]
    handoff_edges: Annotated[list[dict[str, Any]], operator.add]


@dataclass(frozen=True, slots=True)
class LangGraphCoordinationResult:
    coordination_engine: str = "langgraph"
    graph_spec: dict[str, Any] = field(default_factory=dict)
    traversal_nodes: tuple[dict[str, Any], ...] = ()
    handoff_edges: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


class LangGraphCoordinationRunner:
    """Compile and traverse a coordination graph without claiming runtime execution."""

    def run(
        self,
        *,
        task_run_id: str,
        coordination_run_id: str,
        graph_spec: TaskGraphRuntimeSpec,
    ) -> LangGraphCoordinationResult:
        if not graph_spec.valid:
            return LangGraphCoordinationResult(
                graph_spec=graph_spec.to_dict(),
                diagnostics={
                    "compiled": False,
                    "reason": "invalid_graph_spec",
                    "execution_mode": "planning_only",
                    "runtime_execution_bound": False,
                    "issues": [item.to_dict() for item in graph_spec.issues],
                },
            )
        graph = StateGraph(CoordinationGraphRuntimeState)
        for node in graph_spec.nodes:
            graph.add_node(node.node_id, self._node_executor(node.to_dict()))
        start_node_ids = tuple(graph_spec.start_node_ids or (graph_spec.nodes[0].node_id,))
        execution_edges = self._acyclic_execution_edges(
            start_node_ids=start_node_ids,
            edges=[edge.to_dict() for edge in graph_spec.edges],
        )
        for node_id in start_node_ids:
            graph.add_edge(START, node_id)
        for edge in execution_edges:
            graph.add_edge(str(edge["source_node_id"]), str(edge["target_node_id"]))
        terminal_node_ids = self._terminal_node_ids(
            node_ids=[node.node_id for node in graph_spec.nodes],
            execution_edges=execution_edges,
        )
        for node_id in terminal_node_ids:
            graph.add_edge(node_id, END)
        app = graph.compile()
        result = app.invoke(
            {
                "task_run_id": task_run_id,
                "coordination_run_id": coordination_run_id,
                "visited_node_ids": [],
                "traversal_nodes": [],
                "handoff_edges": [edge.to_dict() for edge in graph_spec.edges],
            }
        )
        return LangGraphCoordinationResult(
            graph_spec=graph_spec.to_dict(),
            traversal_nodes=tuple(dict(item) for item in list(result.get("traversal_nodes") or [])),
            handoff_edges=tuple(dict(item) for item in list(result.get("handoff_edges") or [])),
            diagnostics={
                "compiled": True,
                "execution_mode": "planning_only",
                "runtime_execution_bound": False,
                "start_node_ids": list(start_node_ids),
                "terminal_node_ids": list(terminal_node_ids),
                "visited_node_ids": list(result.get("visited_node_ids") or []),
                "node_count": len(graph_spec.nodes),
                "edge_count": len(graph_spec.edges),
                "execution_edge_count": len(execution_edges),
                "skipped_cycle_edge_count": max(0, len(graph_spec.edges) - len(execution_edges)),
            },
        )

    @staticmethod
    def _node_executor(node: dict[str, Any]):
        def _execute(state: CoordinationGraphRuntimeState) -> dict[str, Any]:
            node_id = str(node.get("node_id") or "")
            return {
                "visited_node_ids": [node_id],
                "traversal_nodes": [
                    {
                        "node_id": node_id,
                        "title": str(node.get("title") or node_id),
                        "node_type": str(node.get("node_type") or ""),
                        "role": str(node.get("role") or ""),
                        "agent_id": str(node.get("agent_id") or ""),
                        "task_id": str(node.get("task_id") or ""),
                        "task_run_id": str(state.get("task_run_id") or ""),
                        "coordination_run_id": str(state.get("coordination_run_id") or ""),
                    }
                ],
            }

        return _execute

    @staticmethod
    def _acyclic_execution_edges(
        *,
        start_node_ids: tuple[str, ...],
        edges: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            outgoing.setdefault(str(edge.get("source_node_id") or ""), []).append(edge)
        selected: list[dict[str, Any]] = []
        selected_pairs: set[tuple[str, str]] = set()
        visited: set[str] = set()

        def visit(node_id: str, stack: set[str]) -> None:
            visited.add(node_id)
            for edge in outgoing.get(node_id, []):
                source = str(edge.get("source_node_id") or "")
                target = str(edge.get("target_node_id") or "")
                if not source or not target or target in stack:
                    continue
                pair = (source, target)
                if pair not in selected_pairs:
                    selected.append(edge)
                    selected_pairs.add(pair)
                if target not in visited:
                    visit(target, {*stack, target})

        for node_id in start_node_ids:
            visit(str(node_id), {str(node_id)})
        return selected

    @staticmethod
    def _terminal_node_ids(
        *,
        node_ids: list[str],
        execution_edges: list[dict[str, Any]],
    ) -> tuple[str, ...]:
        sources = {str(edge.get("source_node_id") or "") for edge in execution_edges}
        terminals = tuple(node_id for node_id in node_ids if node_id not in sources)
        return terminals or ((node_ids[-1],) if node_ids else ())
