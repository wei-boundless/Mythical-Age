from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from runtime.shared.models import TaskRun

from .checkpoint_store import checkpoint_store_from_services
from .context_materializer import GraphContextMaterializer
from .models import (
    GraphHarnessConfig,
    GraphLoopState,
    GraphNodeWorkOrder,
    GraphResultEnvelope,
    GraphRuntimeEnvelope,
    NodeResultEnvelope,
    safe_id,
)
from .scheduler_view import build_scheduler_view, is_executable_node


@dataclass(frozen=True, slots=True)
class GraphLoopStart:
    loop_state: GraphLoopState
    checkpoint: dict[str, Any]
    node_work_orders: tuple[GraphNodeWorkOrder, ...] = ()
    events: tuple[dict[str, Any], ...] = ()

    @property
    def node_work_order(self) -> dict[str, Any]:
        return self.node_work_orders[0].to_dict() if self.node_work_orders else {}


@dataclass(frozen=True, slots=True)
class GraphLoopAdvance:
    loop_state: GraphLoopState
    checkpoint: dict[str, Any]
    accepted_result: NodeResultEnvelope | None = None
    graph_result: GraphResultEnvelope | None = None
    node_work_orders: tuple[GraphNodeWorkOrder, ...] = ()
    events: tuple[dict[str, Any], ...] = ()


class GraphLoop:
    """Dynamic controller for graph state progression."""

    def __init__(self, *, services: Any) -> None:
        self._services = services
        self._checkpoint_store = checkpoint_store_from_services(services)
        self._context_materializer = GraphContextMaterializer()

    def initialize(
        self,
        *,
        graph_config: GraphHarnessConfig,
        envelope: GraphRuntimeEnvelope,
        dispatch_ready: bool = True,
    ) -> GraphLoopStart:
        node_states = _initial_node_states(graph_config)
        edge_states = _initial_edge_states(graph_config)
        ready_node_ids = _ready_nodes(graph_config=graph_config, node_states=node_states)
        scheduler_view = build_scheduler_view(graph_config)
        executable_node_ids = tuple(scheduler_view.executable_node_ids)
        terminal_status = ""
        terminal_reason = ""
        if not graph_config.nodes:
            terminal_status = "failed"
            terminal_reason = "no_nodes"
        elif not executable_node_ids:
            terminal_status = "failed"
            terminal_reason = "no_executable_nodes"
        elif not ready_node_ids:
            terminal_status = "failed"
            terminal_reason = "no_schedulable_start_nodes"
        state = GraphLoopState(
            state_id=f"gstate:{safe_id(envelope.graph_run_id)}",
            graph_run_id=envelope.graph_run_id,
            task_run_id=envelope.task_run_id,
            session_id=envelope.session_id,
            config_id=envelope.config_id,
            config_hash=envelope.config_hash,
            graph_id=envelope.graph_id,
            status=terminal_status or "running",
            node_states=node_states,
            edge_states=edge_states,
            ready_node_ids=tuple(ready_node_ids),
            blocked_node_ids=tuple(_blocked_nodes(graph_config=graph_config, node_states=node_states)) if terminal_status else (),
            initial_inputs=dict(envelope.initial_inputs or {}),
            terminal_reason=terminal_reason,
            diagnostics={
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
                "source": "harness.graph_loop.initialize",
                "scheduler": scheduler_view.diagnostics,
            },
        )
        work_orders = self.dispatch_ready(graph_config=graph_config, state=state) if dispatch_ready and not terminal_status else ()
        if work_orders:
            state = _state_with_work_orders(state, work_orders)
        graph_result = None
        if terminal_status:
            graph_result = _graph_result(
                graph_config=graph_config,
                state=state,
                status=terminal_status,
                terminal_reason=terminal_reason,
            )
        state = _advance_event_cursor(state)
        checkpoint = self._write_state(state, pending_work_orders=work_orders)
        self._update_formal_runs(state, graph_result=graph_result)
        events = [
            self._append_event(
                state.task_run_id,
                "graph_loop_started",
                payload={
                    "graph_run_id": state.graph_run_id,
                    "graph_loop_state": state.to_dict(),
                    "node_work_orders": [item.to_dict() for item in work_orders],
                    "graph_result": graph_result.to_dict() if graph_result is not None else None,
                },
                refs={"graph_run_ref": state.graph_run_id, "graph_harness_config_ref": state.config_id},
            )
        ]
        return GraphLoopStart(
            loop_state=state,
            checkpoint=checkpoint,
            node_work_orders=work_orders,
            events=tuple(events),
        )

    def dispatch_ready(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        max_requests: int | None = None,
    ) -> tuple[GraphNodeWorkOrder, ...]:
        limit = int(max_requests or dict(graph_config.control or {}).get("max_active_nodes") or 1)
        selected = [
            node_id
            for node_id in state.ready_node_ids
            if node_id not in state.active_work_orders
        ][: max(1, limit)]
        orders: list[GraphNodeWorkOrder] = []
        for node_id in selected:
            node = _node_by_id(graph_config, node_id)
            if node is None:
                continue
            orders.append(self._context_materializer.build_work_order(graph_config=graph_config, state=state, node=node))
        return tuple(orders)

    def dispatch_ready_and_checkpoint(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        max_requests: int | None = None,
    ) -> GraphLoopStart:
        state = self.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        work_orders = self.dispatch_ready(
            graph_config=graph_config,
            state=state,
            max_requests=max_requests,
        )
        next_state = _state_with_work_orders(state, work_orders) if work_orders else state
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state, pending_work_orders=work_orders)
        events = []
        if work_orders:
            events.append(
                self._append_event(
                    next_state.task_run_id,
                    "graph_ready_nodes_dispatched",
                    payload={
                        "graph_run_id": next_state.graph_run_id,
                        "node_work_orders": [item.to_dict() for item in work_orders],
                        "graph_loop_state": next_state.to_dict(),
                    },
                    refs={"graph_run_ref": next_state.graph_run_id, "graph_harness_config_ref": next_state.config_id},
                )
            )
        return GraphLoopStart(
            loop_state=next_state,
            checkpoint=checkpoint,
            node_work_orders=work_orders,
            events=tuple(events),
        )

    def accept_node_result(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        result: NodeResultEnvelope | dict[str, Any],
    ) -> GraphLoopAdvance:
        state = self.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        envelope = result if isinstance(result, NodeResultEnvelope) else NodeResultEnvelope.from_dict(dict(result or {}))
        if envelope.graph_run_id != state.graph_run_id:
            raise ValueError("NodeResultEnvelope graph_run_id does not match GraphLoopState")
        active_work_order_id = str(dict(state.active_work_orders or {}).get(envelope.node_id) or "")
        if not active_work_order_id:
            raise ValueError("NodeResultEnvelope node is not active in GraphLoopState")
        if envelope.work_order_id != active_work_order_id:
            raise ValueError("NodeResultEnvelope work_order_id does not match active GraphNodeWorkOrder")
        node_states = {key: dict(value) for key, value in state.node_states.items()}
        current_node = dict(node_states.get(envelope.node_id) or {})
        current_node["status"] = "completed" if envelope.status == "completed" else "failed"
        current_node["result_ref"] = envelope.result_id
        current_node["updated_at"] = envelope.created_at or time.time()
        node_states[envelope.node_id] = current_node
        edge_states = _edge_states_after_node_result(graph_config=graph_config, state=state, result=envelope)
        result_index = {key: dict(value) for key, value in state.result_index.items()}
        result_index[envelope.node_id] = envelope.to_dict()
        active_work_orders = dict(state.active_work_orders)
        active_work_orders.pop(envelope.node_id, None)
        next_state = _replace_state(
            state,
            node_states=node_states,
            edge_states=edge_states,
            result_index=result_index,
            active_work_orders=active_work_orders,
        )
        next_ready = _ready_nodes(graph_config=graph_config, node_states=node_states)
        running = [
            node_id
            for node_id, payload in node_states.items()
            if str(payload.get("status") or "") == "running"
        ]
        completed = [
            node_id
            for node_id, payload in node_states.items()
            if str(payload.get("status") or "") == "completed"
        ]
        failed = [
            node_id
            for node_id, payload in node_states.items()
            if str(payload.get("status") or "") == "failed"
        ]
        terminal_ids = set(_terminal_node_ids(graph_config))
        graph_result: GraphResultEnvelope | None = None
        status = "running"
        terminal_reason = ""
        if failed:
            status = "failed"
            terminal_reason = f"node_failed:{failed[0]}"
            graph_result = _graph_result(graph_config=graph_config, state=next_state, status="failed", terminal_reason=terminal_reason)
        elif terminal_ids and terminal_ids.issubset(set(completed)):
            status = "completed"
            terminal_reason = "terminal_nodes_completed"
            graph_result = _graph_result(graph_config=graph_config, state=next_state, status="completed", terminal_reason=terminal_reason)
        elif len(completed) == len(build_scheduler_view(graph_config).executable_node_ids):
            status = "completed"
            terminal_reason = "all_executable_nodes_completed"
            graph_result = _graph_result(graph_config=graph_config, state=next_state, status="completed", terminal_reason=terminal_reason)
        next_state = _replace_state(
            next_state,
            status=status,
            ready_node_ids=tuple([] if graph_result else next_ready),
            running_node_ids=tuple(running),
            completed_node_ids=tuple(completed),
            failed_node_ids=tuple(failed),
            blocked_node_ids=tuple(_blocked_nodes(graph_config=graph_config, node_states=node_states)),
            terminal_reason=terminal_reason,
        )
        work_orders = () if graph_result is not None else self.dispatch_ready(graph_config=graph_config, state=next_state)
        if work_orders:
            next_state = _state_with_work_orders(next_state, work_orders)
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state, pending_work_orders=work_orders)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_node_result_accepted",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "node_result": envelope.to_dict(),
                    "graph_loop_state": next_state.to_dict(),
                    "node_work_orders": [item.to_dict() for item in work_orders],
                    "graph_result": graph_result.to_dict() if graph_result is not None else None,
                },
                refs={"graph_run_ref": next_state.graph_run_id, "node_ref": envelope.node_id},
            )
        ]
        self._update_formal_runs(next_state, graph_result=graph_result)
        return GraphLoopAdvance(
            loop_state=next_state,
            checkpoint=checkpoint,
            accepted_result=envelope,
            graph_result=graph_result,
            node_work_orders=work_orders,
            events=tuple(events),
        )

    def get_state(self, graph_run_id: str) -> GraphLoopState | None:
        payload = self._checkpoint_store.get_latest_state(graph_run_id)
        if not payload:
            return None
        return GraphLoopState.from_dict(payload)

    def get_latest_checkpoint(self, graph_run_id: str) -> Any | None:
        return self._checkpoint_store.get_latest_checkpoint(graph_run_id)

    def list_checkpoints(self, graph_run_id: str, *, limit: int | None = None) -> tuple[Any, ...]:
        return self._checkpoint_store.list_checkpoints(graph_run_id, limit=limit)

    def _write_state(self, state: GraphLoopState, *, pending_work_orders: tuple[GraphNodeWorkOrder, ...] = ()) -> dict[str, Any]:
        checkpoint = self._checkpoint_store.put_checkpoint(
            state=state,
            metadata={"created_at": time.time(), "authority": "harness.graph_loop_checkpoint"},
        )
        if pending_work_orders:
            self._checkpoint_store.put_pending_writes(
                graph_run_id=state.graph_run_id,
                task_id=f"dispatch:{state.graph_run_id}:{int(time.time() * 1000)}",
                writes=tuple(("active_work_order", item.to_dict()) for item in pending_work_orders),
            )
            latest = self._checkpoint_store.get_latest_checkpoint(state.graph_run_id)
            return latest.to_dict() if latest is not None else checkpoint.to_dict()
        return checkpoint.to_dict()

    def _append_event(
        self,
        task_run_id: str,
        event_type: str,
        *,
        payload: dict[str, Any],
        refs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._services.event_log.append(
            task_run_id,
            event_type,
            payload=payload,
            refs=dict(refs or {}),
        ).to_dict()

    def _update_formal_runs(self, state: GraphLoopState, *, graph_result: GraphResultEnvelope | None) -> None:
        if graph_result is None:
            return
        now = time.time()
        self._services.runtime_objects.put_object(
            "graph_result",
            safe_id(graph_result.result_id),
            graph_result.to_dict(),
        )
        current_task = self._services.state_index.get_task_run(state.task_run_id)
        if current_task is not None:
            self._services.state_index.upsert_task_run(
                TaskRun(
                    **{
                        **current_task.to_dict(),
                        "status": "completed" if graph_result.status == "completed" else "failed",
                        "updated_at": now,
                        "terminal_reason": graph_result.terminal_reason or graph_result.status,
                        "diagnostics": {
                            **dict(current_task.diagnostics or {}),
                            "graph_result": graph_result.to_dict(),
                        },
                    }
                )
            )
        graph_run = self._services.runtime_objects.get_object(f"rtobj:graph_run:{safe_id(state.graph_run_id)}")
        if graph_run:
            self._services.runtime_objects.put_object(
                "graph_run",
                safe_id(state.graph_run_id),
                {
                    **dict(graph_run),
                    "status": "completed" if graph_result.status == "completed" else "failed",
                    "updated_at": now,
                    "terminal_reason": graph_result.terminal_reason or graph_result.status,
                    "diagnostics": {
                        **dict(dict(graph_run).get("diagnostics") or {}),
                        "graph_result": graph_result.to_dict(),
                    },
                },
            )


def _initial_node_states(graph_config: GraphHarnessConfig) -> dict[str, dict[str, Any]]:
    start_ids = set(_start_node_ids(graph_config))
    now = time.time()
    return {
        str(node.get("node_id") or ""): {
            "node_id": str(node.get("node_id") or ""),
            "status": _initial_node_status(node, start_ids=start_ids),
            "executor_type": str(dict(node.get("executor") or {}).get("executor_type") or "agent"),
            "created_at": now,
            "updated_at": now,
        }
        for node in graph_config.nodes
        if str(node.get("node_id") or "")
    }


def _initial_edge_states(graph_config: GraphHarnessConfig) -> dict[str, dict[str, Any]]:
    return {
        str(edge.get("edge_id") or ""): {
            "edge_id": str(edge.get("edge_id") or ""),
            "source_node_id": str(edge.get("source_node_id") or ""),
            "target_node_id": str(edge.get("target_node_id") or ""),
            "status": "pending",
        }
        for edge in graph_config.edges
        if str(edge.get("edge_id") or "")
    }


def _ready_nodes(*, graph_config: GraphHarnessConfig, node_states: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    ready: list[str] = []
    scheduler_view = build_scheduler_view(graph_config)
    executable_ids = set(scheduler_view.executable_node_ids)
    for node in graph_config.nodes:
        node_id = str(node.get("node_id") or "")
        if node_id not in executable_ids:
            continue
        status = str(dict(node_states.get(node_id) or {}).get("status") or "")
        if status == "ready":
            ready.append(node_id)
            continue
        if status not in {"pending", "blocked"}:
            continue
        upstream = _upstream_node_ids(graph_config, node_id)
        if upstream and all(str(dict(node_states.get(item) or {}).get("status") or "") == "completed" for item in upstream):
            ready.append(node_id)
    return tuple(dict.fromkeys(item for item in ready if item))


def _blocked_nodes(*, graph_config: GraphHarnessConfig, node_states: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    ready = set(_ready_nodes(graph_config=graph_config, node_states=node_states))
    return tuple(
        node_id
        for node_id, payload in node_states.items()
        if str(payload.get("status") or "") in {"pending", "blocked"} and node_id not in ready
    )


def _state_with_work_orders(state: GraphLoopState, work_orders: tuple[GraphNodeWorkOrder, ...]) -> GraphLoopState:
    node_states = {key: dict(value) for key, value in state.node_states.items()}
    active = dict(state.active_work_orders)
    work_order_index = {key: dict(value) for key, value in state.work_order_index.items()}
    for order in work_orders:
        node_id = order.node_id
        payload = dict(node_states.get(node_id) or {})
        payload["status"] = "running"
        payload["work_order_id"] = order.work_order_id
        payload["updated_at"] = time.time()
        node_states[node_id] = payload
        active[node_id] = order.work_order_id
        work_order_index[order.work_order_id] = order.to_dict()
    return _replace_state(
        state,
        node_states=node_states,
        active_work_orders=active,
        work_order_index=work_order_index,
        ready_node_ids=tuple(item for item in state.ready_node_ids if item not in active),
        running_node_ids=tuple(dict.fromkeys([*state.running_node_ids, *(item.node_id for item in work_orders)])),
    )


def _initial_node_status(node: dict[str, Any], *, start_ids: set[str]) -> str:
    node_id = str(node.get("node_id") or "")
    if not is_executable_node(node):
        return "resource"
    return "ready" if node_id in start_ids else "pending"


def _replace_state(state: GraphLoopState, **patch: Any) -> GraphLoopState:
    payload = state.to_dict()
    payload.update(patch)
    return GraphLoopState.from_dict(payload)


def _advance_event_cursor(state: GraphLoopState) -> GraphLoopState:
    return _replace_state(state, event_cursor=state.event_cursor + 1)


def _node_by_id(graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any] | None:
    target = str(node_id or "")
    return next((dict(item) for item in graph_config.nodes if str(item.get("node_id") or "") == target), None)


def _start_node_ids(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    return build_scheduler_view(graph_config).start_node_ids


def _terminal_node_ids(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    return build_scheduler_view(graph_config).terminal_node_ids


def _upstream_node_ids(graph_config: GraphHarnessConfig, node_id: str) -> tuple[str, ...]:
    return tuple(
        str(edge.get("source_node_id") or "")
        for edge in build_scheduler_view(graph_config).dependency_edges
        if str(edge.get("target_node_id") or "") == node_id and str(edge.get("source_node_id") or "")
    )


def _outgoing_dependency_edges(graph_config: GraphHarnessConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    source = str(node_id or "")
    return tuple(
        dict(edge)
        for edge in build_scheduler_view(graph_config).dependency_edges
        if str(edge.get("source_node_id") or "") == source
    )


def _edge_states_after_node_result(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
) -> dict[str, dict[str, Any]]:
    edge_states = {key: dict(value) for key, value in state.edge_states.items()}
    now = time.time()
    for edge in _outgoing_dependency_edges(graph_config, result.node_id):
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        edge_state = dict(edge_states.get(edge_id) or {})
        edge_state.update(
            {
                "edge_id": edge_id,
                "source_node_id": result.node_id,
                "target_node_id": str(edge.get("target_node_id") or ""),
                "status": "ready" if result.status == "completed" else "source_failed",
                "source_result_ref": result.result_id,
                "handoff_packet_id": f"ghandoff:{safe_id(state.graph_run_id)}:{safe_id(edge_id)}",
                "updated_at": now,
            }
        )
        edge_states[edge_id] = edge_state
    return edge_states


def _graph_result(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    status: str,
    terminal_reason: str = "",
) -> GraphResultEnvelope:
    result_refs = [
        str(dict(item).get("result_id") or "")
        for item in state.result_index.values()
        if str(dict(item).get("result_id") or "")
    ]
    return GraphResultEnvelope(
        result_id=f"gresult:{safe_id(state.graph_run_id)}",
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        graph_id=graph_config.graph_id,
        config_id=graph_config.config_id,
        status=status,
        outputs={
            node_id: dict(result).get("outputs")
            for node_id, result in state.result_index.items()
        },
        node_result_refs=tuple(result_refs),
        terminal_reason=terminal_reason or status,
        created_at=time.time(),
    )
