from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from runtime.shared.models import TaskRun

from .checkpoint_store import checkpoint_store_from_services
from .context_materializer import GraphContextMaterializer
from .flow_edges import build_outbound_flow_edges
from .flow_packet import build_flow_packet, edge_delivers_flow_packet
from .models import (
    GraphHarnessConfig,
    GraphLoopState,
    GraphNodeWorkOrder,
    GraphResultEnvelope,
    GraphRuntimeEnvelope,
    NodeResultEnvelope,
    safe_id,
)
from .runtime_objects import (
    flow_packet_summary,
    load_node_result,
    node_result_summary,
    store_flow_packet,
    store_node_result,
    store_work_order,
    work_order_summary,
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
        self._context_materializer = GraphContextMaterializer(services=services)

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
            initial_inputs=_initial_loop_inputs(graph_config=graph_config, envelope=envelope),
            loop_state=_initial_loop_state(graph_config=graph_config, envelope=envelope),
            terminal_reason=terminal_reason,
            diagnostics={
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
                "runtime_scope": dict(envelope.memory_scope.get("runtime_scope") or {}),
                "source": "harness.graph_loop.initialize",
                "scheduler": scheduler_view.diagnostics,
            },
        )
        work_orders = self.dispatch_ready(graph_config=graph_config, state=state) if dispatch_ready and not terminal_status else ()
        if work_orders:
            state = _state_with_work_orders(state, work_orders, services=self._services)
        graph_result = None
        if terminal_status:
            graph_result = _graph_result(
                graph_config=graph_config,
                state=state,
                status=terminal_status,
                terminal_reason=terminal_reason,
                services=self._services,
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
                    "graph_loop_state": _loop_state_summary(state),
                    "node_work_orders": [_work_order_summary(item) for item in work_orders],
                    "graph_result": _graph_result_summary(graph_result),
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
        next_state = _state_with_work_orders(state, work_orders, services=self._services) if work_orders else state
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
                        "node_work_orders": [_work_order_summary(item) for item in work_orders],
                        "graph_loop_state": _loop_state_summary(next_state),
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
        current_node["status"] = _node_status_from_result(envelope)
        result_ref = store_node_result(self._services, envelope)
        current_node["result_ref"] = result_ref
        current_node["updated_at"] = envelope.created_at or time.time()
        node_states[envelope.node_id] = current_node
        edge_states = _edge_states_after_node_result(
            graph_config=graph_config,
            state=state,
            result=envelope,
            result_ref=result_ref,
            services=self._services,
        )
        result_index = {key: dict(value) for key, value in state.result_index.items()}
        result_index[envelope.node_id] = _node_result_summary(envelope, result_ref=result_ref)
        result_history = _result_history_with_result(state=state, result=envelope, result_ref=result_ref)
        active_work_orders = dict(state.active_work_orders)
        active_work_orders.pop(envelope.node_id, None)
        next_state = _replace_state(
            state,
            node_states=node_states,
            edge_states=edge_states,
            result_index=result_index,
            result_history=result_history,
            active_work_orders=active_work_orders,
        )
        route_decision = _evaluate_loop_route(graph_config=graph_config, state=next_state, result=envelope)
        if route_decision:
            next_state = _state_after_loop_route(graph_config=graph_config, state=next_state, decision=route_decision)
            node_states = {key: dict(value) for key, value in next_state.node_states.items()}
            edge_states = {key: dict(value) for key, value in next_state.edge_states.items()}
            result_index = {key: dict(value) for key, value in next_state.result_index.items()}
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
        blocked = [
            node_id
            for node_id, payload in node_states.items()
            if str(payload.get("status") or "") in {"blocked", "waiting_human_gate"}
        ]
        waiting_human = [
            node_id
            for node_id, payload in node_states.items()
            if str(payload.get("status") or "") == "waiting_human_gate"
        ]
        if waiting_human:
            status = "waiting_human_gate"
            terminal_reason = f"waiting_human_gate:{waiting_human[0]}"
        elif blocked:
            status = "blocked"
            terminal_reason = f"node_blocked:{blocked[0]}"
        elif failed:
            status = "failed"
            terminal_reason = f"node_failed:{failed[0]}"
            graph_result = _graph_result(graph_config=graph_config, state=next_state, status="failed", terminal_reason=terminal_reason, services=self._services)
        elif terminal_ids and terminal_ids.issubset(set(completed)):
            status = "completed"
            terminal_reason = "terminal_nodes_completed"
            graph_result = _graph_result(graph_config=graph_config, state=next_state, status="completed", terminal_reason=terminal_reason, services=self._services)
        elif len(completed) == len(build_scheduler_view(graph_config).executable_node_ids):
            status = "completed"
            terminal_reason = "all_executable_nodes_completed"
            graph_result = _graph_result(graph_config=graph_config, state=next_state, status="completed", terminal_reason=terminal_reason, services=self._services)
        next_state = _replace_state(
            next_state,
            status=status,
            ready_node_ids=tuple([] if graph_result else next_ready),
            running_node_ids=tuple(running),
            completed_node_ids=tuple(completed),
            failed_node_ids=tuple(failed),
            blocked_node_ids=tuple(dict.fromkeys([*blocked, *_blocked_nodes(graph_config=graph_config, node_states=node_states)])),
            terminal_reason=terminal_reason,
        )
        work_orders = () if graph_result is not None or status in {"blocked", "waiting_human_gate"} else self.dispatch_ready(graph_config=graph_config, state=next_state)
        if work_orders:
            next_state = _state_with_work_orders(next_state, work_orders, services=self._services)
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state, pending_work_orders=work_orders)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_node_result_accepted",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "node_result": _node_result_summary(envelope, result_ref=result_ref),
                    "loop_route_decision": route_decision,
                    "graph_loop_state": _loop_state_summary(next_state),
                    "node_work_orders": [_work_order_summary(item) for item in work_orders],
                    "graph_result": _graph_result_summary(graph_result),
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

    def requeue_blocked_nodes_and_checkpoint(
        self,
        *,
        state: GraphLoopState,
        node_ids: tuple[str, ...],
    ) -> GraphLoopStart:
        targets = tuple(dict.fromkeys(str(item) for item in node_ids if str(item)))
        if not targets:
            checkpoint = self.get_latest_checkpoint(state.graph_run_id)
            return GraphLoopStart(
                loop_state=state,
                checkpoint=checkpoint.to_dict() if checkpoint is not None else {},
            )
        node_states = {key: dict(value) for key, value in state.node_states.items()}
        now = time.time()
        for node_id in targets:
            node = dict(node_states.get(node_id) or {})
            if not node:
                continue
            node["status"] = "ready"
            node["updated_at"] = now
            node.pop("blocked_reason", None)
            node_states[node_id] = node
        next_state = _replace_state(
            state,
            status="running",
            node_states=node_states,
            ready_node_ids=tuple(dict.fromkeys([*state.ready_node_ids, *targets])),
            running_node_ids=(),
            blocked_node_ids=tuple(item for item in state.blocked_node_ids if item not in set(targets)),
            terminal_reason="",
        )
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_blocked_nodes_requeued",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "node_ids": list(targets),
                    "graph_loop_state": _loop_state_summary(next_state),
                },
                refs={"graph_run_ref": next_state.graph_run_id, "graph_harness_config_ref": next_state.config_id},
            )
        ]
        return GraphLoopStart(loop_state=next_state, checkpoint=checkpoint, events=tuple(events))

    def _write_state(self, state: GraphLoopState, *, pending_work_orders: tuple[GraphNodeWorkOrder, ...] = ()) -> dict[str, Any]:
        checkpoint = self._checkpoint_store.put_checkpoint(
            state=state,
            metadata={"created_at": time.time(), "authority": "harness.graph_loop_checkpoint"},
        )
        if pending_work_orders:
            self._checkpoint_store.put_pending_writes(
                graph_run_id=state.graph_run_id,
                task_id=f"dispatch:{state.graph_run_id}:{int(time.time() * 1000)}",
                writes=tuple(
                    (
                        "active_work_order",
                        dict(state.work_order_index.get(item.work_order_id) or _work_order_summary(item)),
                    )
                    for item in pending_work_orders
                ),
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


def _initial_loop_inputs(*, graph_config: GraphHarnessConfig, envelope: GraphRuntimeEnvelope) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    derived_fields: list[Any] = []
    for frame in graph_config.loop_frames:
        inputs.update(dict(dict(frame).get("initial_inputs") or {}))
        derived_fields.extend(list(dict(frame).get("derived_fields") or []))
    inputs.update(dict(envelope.initial_inputs or {}))
    return _apply_derived_fields(inputs, derived_fields)


def _initial_loop_state(*, graph_config: GraphHarnessConfig, envelope: GraphRuntimeEnvelope) -> dict[str, Any]:
    frames: dict[str, dict[str, Any]] = {}
    for raw in graph_config.loop_frames:
        frame = _normalize_loop_frame(dict(raw))
        frame_id = str(frame.get("frame_id") or "")
        if not frame_id:
            continue
        frames[frame_id] = {
            **frame,
            "status": "active",
            "iteration_index": 0,
            "scope_node_ids": list(_loop_scope_node_ids(graph_config=graph_config, frame=frame)),
        }
    return {
        "authority": "harness.graph.loop_contract_state",
        "graph_run_id": envelope.graph_run_id,
        "frames": frames,
        "route_history": [],
    }


def _normalize_loop_frame(frame: dict[str, Any]) -> dict[str, Any]:
    frame_id = str(frame.get("frame_id") or frame.get("scope_id") or "").strip()
    return _drop_empty(
        {
            **frame,
            "frame_id": frame_id,
            "scope_id": str(frame.get("scope_id") or frame_id).strip(),
            "entry_node_id": str(frame.get("entry_node_id") or "").strip(),
            "router_node_id": str(frame.get("router_node_id") or "").strip(),
            "continue_node_id": str(frame.get("continue_node_id") or "").strip(),
            "exit_node_id": str(frame.get("exit_node_id") or "").strip(),
        }
    )


def _evaluate_loop_route(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
) -> dict[str, Any]:
    if result.status != "completed":
        return {}
    node = _node_by_id(graph_config, result.node_id) or {}
    node_loop = dict(node.get("loop") or {})
    route_policy = dict(node_loop.get("route_policy") or {})
    if not route_policy:
        return {}
    mode = str(route_policy.get("mode") or "metric_target").strip() or "metric_target"
    if mode != "metric_target":
        raise ValueError(f"unsupported graph loop route mode: {mode}")
    scope_id = str(route_policy.get("scope_id") or node_loop.get("scope_id") or "").strip()
    frame = _loop_frame_for_route(graph_config=graph_config, scope_id=scope_id, node_id=result.node_id, route_policy=route_policy)
    metric = _route_metric(route_policy=route_policy, state=state, result=result)
    if metric is None:
        return {
            "authority": "harness.graph.loop_route_decision",
            "action": "blocked",
            "reason": "loop_route_metric_missing",
            "node_id": result.node_id,
            "scope_id": scope_id,
            "route_policy": route_policy,
        }
    patched_inputs = dict(state.initial_inputs or {})
    current_key = str(route_policy.get("current_key") or "").strip()
    target_key = str(route_policy.get("target_key") or "").strip()
    if current_key:
        patched_inputs[current_key] = _numeric_value(patched_inputs.get(current_key), 0) + metric
    last_metric_key = str(route_policy.get("last_metric_key") or "").strip()
    if last_metric_key:
        patched_inputs[last_metric_key] = metric
    for counter in list(route_policy.get("secondary_counters") or []):
        if not isinstance(counter, dict):
            continue
        secondary_key = str(counter.get("current_key") or "").strip()
        if secondary_key:
            patched_inputs[secondary_key] = _numeric_value(patched_inputs.get(secondary_key), 0) + metric
    patched_inputs = _apply_patch_rules(patched_inputs, list(route_policy.get("patch_rules") or []))
    patched_inputs = _apply_derived_fields(patched_inputs, list(route_policy.get("derived_fields") or []))
    current_value = _numeric_value(patched_inputs.get(current_key), 0) if current_key else 0
    target_value = _numeric_value(patched_inputs.get(target_key), 0) if target_key else 0
    action = "exit" if target_key and current_value >= target_value else "continue"
    continue_node_id = str(route_policy.get("continue_node_id") or frame.get("continue_node_id") or frame.get("entry_node_id") or "").strip()
    exit_node_id = str(route_policy.get("exit_node_id") or frame.get("exit_node_id") or "").strip()
    return {
        "authority": "harness.graph.loop_route_decision",
        "action": action,
        "reason": "target_reached" if action == "exit" else "target_not_reached",
        "node_id": result.node_id,
        "result_id": result.result_id,
        "scope_id": scope_id,
        "frame_id": str(frame.get("frame_id") or scope_id),
        "continue_node_id": continue_node_id,
        "exit_node_id": exit_node_id,
        "metric": metric,
        "current_key": current_key,
        "current_value": current_value,
        "target_key": target_key,
        "target_value": target_value,
        "initial_inputs_patch": patched_inputs,
        "scope_node_ids": list(_loop_scope_node_ids(graph_config=graph_config, frame=frame)),
    }


def _state_after_loop_route(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    decision: dict[str, Any],
) -> GraphLoopState:
    action = str(decision.get("action") or "").strip()
    loop_state = _loop_state_after_decision(state=state, decision=decision)
    node_states = {key: dict(value) for key, value in state.node_states.items()}
    edge_states = {key: dict(value) for key, value in state.edge_states.items()}
    result_index = {key: dict(value) for key, value in state.result_index.items()}
    active_work_orders = dict(state.active_work_orders)
    if action == "blocked":
        node_id = str(decision.get("node_id") or "")
        node_payload = dict(node_states.get(node_id) or {})
        node_payload["status"] = "blocked"
        node_payload["blocked_reason"] = str(decision.get("reason") or "loop_route_blocked")
        node_payload["updated_at"] = time.time()
        node_states[node_id] = node_payload
        return _replace_state(state, node_states=node_states, loop_state=loop_state)
    if action != "continue":
        return _replace_state(
            state,
            initial_inputs=dict(decision.get("initial_inputs_patch") or state.initial_inputs),
            loop_state=loop_state,
        )
    scope_node_ids = [str(item) for item in list(decision.get("scope_node_ids") or []) if str(item)]
    continue_node_id = str(decision.get("continue_node_id") or "").strip()
    if not continue_node_id:
        node_id = str(decision.get("node_id") or "")
        node_payload = dict(node_states.get(node_id) or {})
        node_payload["status"] = "blocked"
        node_payload["blocked_reason"] = "loop_continue_node_missing"
        node_payload["updated_at"] = time.time()
        node_states[node_id] = node_payload
        return _replace_state(state, node_states=node_states, loop_state=loop_state)
    for node_id in scope_node_ids:
        payload = dict(node_states.get(node_id) or {})
        if not payload:
            continue
        payload["status"] = "ready" if node_id == continue_node_id else "pending"
        payload.pop("result_ref", None)
        payload.pop("work_order_id", None)
        payload["updated_at"] = time.time()
        node_states[node_id] = payload
        result_index.pop(node_id, None)
        active_work_orders.pop(node_id, None)
    for edge in graph_config.edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source in scope_node_ids or target in scope_node_ids:
            edge_payload = dict(edge_states.get(edge_id) or {})
            edge_payload.update(
                {
                    "edge_id": edge_id,
                    "source_node_id": source,
                    "target_node_id": target,
                    "status": "pending",
                    "updated_at": time.time(),
                }
            )
            edge_payload.pop("source_result_ref", None)
            edge_payload.pop("handoff_packet_id", None)
            edge_payload.pop("packet_refs", None)
            edge_payload.pop("latest_packet_id", None)
            edge_payload.pop("latest_packet_ref", None)
            edge_payload.pop("latest_packet", None)
            edge_states[edge_id] = edge_payload
    return _replace_state(
        state,
        node_states=node_states,
        edge_states=edge_states,
        result_index=result_index,
        active_work_orders=active_work_orders,
        initial_inputs=dict(decision.get("initial_inputs_patch") or state.initial_inputs),
        loop_state=loop_state,
    )


def _loop_frame_for_route(
    *,
    graph_config: GraphHarnessConfig,
    scope_id: str,
    node_id: str,
    route_policy: dict[str, Any],
) -> dict[str, Any]:
    normalized_frames = [_normalize_loop_frame(dict(item)) for item in graph_config.loop_frames]
    for frame in normalized_frames:
        if scope_id and str(frame.get("scope_id") or frame.get("frame_id") or "") == scope_id:
            return frame
    for frame in normalized_frames:
        if str(frame.get("router_node_id") or "") == node_id:
            return frame
    return _drop_empty(
        {
            "frame_id": scope_id,
            "scope_id": scope_id,
            "entry_node_id": str(route_policy.get("continue_node_id") or "").strip(),
            "router_node_id": node_id,
            "continue_node_id": str(route_policy.get("continue_node_id") or "").strip(),
            "exit_node_id": str(route_policy.get("exit_node_id") or "").strip(),
        }
    )


def _loop_scope_node_ids(*, graph_config: GraphHarnessConfig, frame: dict[str, Any]) -> tuple[str, ...]:
    entry = str(frame.get("entry_node_id") or frame.get("continue_node_id") or "").strip()
    router = str(frame.get("router_node_id") or "").strip()
    if entry and router:
        dependency_edges = build_scheduler_view(graph_config).dependency_edges
        reachable = _reachable_nodes(entry, dependency_edges)
        ancestors = _ancestor_nodes(router, dependency_edges)
        scoped = [node_id for node_id in _graph_node_order(graph_config) if node_id in reachable and node_id in ancestors]
        if scoped:
            return tuple(dict.fromkeys([*scoped, router]))
    scope_id = str(frame.get("scope_id") or frame.get("frame_id") or "").strip()
    if scope_id:
        explicit = [
            str(node.get("node_id") or "")
            for node in graph_config.nodes
            if str(dict(node.get("loop") or {}).get("scope_id") or "") == scope_id
        ]
        if explicit:
            return tuple(dict.fromkeys(explicit))
    return tuple(item for item in (entry, router) if item)


def _reachable_nodes(start: str, edges: tuple[dict[str, Any], ...]) -> set[str]:
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for edge in edges:
            if str(edge.get("source_node_id") or "") != current:
                continue
            target = str(edge.get("target_node_id") or "")
            if target and target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _ancestor_nodes(target: str, edges: tuple[dict[str, Any], ...]) -> set[str]:
    seen = {target}
    queue = [target]
    while queue:
        current = queue.pop(0)
        for edge in edges:
            if str(edge.get("target_node_id") or "") != current:
                continue
            source = str(edge.get("source_node_id") or "")
            if source and source not in seen:
                seen.add(source)
                queue.append(source)
    return seen


def _graph_node_order(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    return tuple(str(node.get("node_id") or "") for node in graph_config.nodes if str(node.get("node_id") or ""))


def _route_metric(*, route_policy: dict[str, Any], state: GraphLoopState, result: NodeResultEnvelope) -> float | int | None:
    metric_key = str(route_policy.get("metric_key") or "").strip()
    for source in _route_metric_sources(result):
        if metric_key:
            value = _nested_lookup(source, metric_key)
            if value is not None:
                return _numeric_value(value, 0)
        value = source.get("metric") if isinstance(source, dict) else None
        if value is not None:
            return _numeric_value(value, 0)
    fallback_key = str(route_policy.get("fallback_increment_key") or "").strip()
    if fallback_key and fallback_key in state.initial_inputs:
        return _numeric_value(state.initial_inputs.get(fallback_key), 0)
    if route_policy.get("default_increment") is not None:
        return _numeric_value(route_policy.get("default_increment"), 0)
    return None


def _route_metric_sources(result: NodeResultEnvelope) -> list[dict[str, Any]]:
    payload = result.to_dict()
    sources: list[dict[str, Any]] = [
        dict(result.outputs or {}),
        dict(result.decisions or {}),
        dict(result.diagnostics or {}),
    ]
    for key in ("progress_receipts", "memory_commit_receipts", "artifact_materialization_receipts", "memory_candidates"):
        for item in list(payload.get(key) or []):
            if isinstance(item, dict):
                sources.append(dict(item))
    return sources


def _apply_patch_rules(inputs: dict[str, Any], rules: list[Any]) -> dict[str, Any]:
    patched = dict(inputs)
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        rule = dict(raw_rule)
        key = str(rule.get("key") or "").strip()
        if not key:
            continue
        op = str(rule.get("op") or rule.get("mode") or "").strip()
        if op == "increment":
            step_key = str(rule.get("step_key") or rule.get("by_key") or "").strip()
            step = _numeric_value(patched.get(step_key), None) if step_key else None
            if step is None:
                step = _numeric_value(rule.get("step") if rule.get("step") is not None else rule.get("value"), 1)
            patched[key] = _numeric_value(patched.get(key), 0) + _numeric_value(step, 0)
        elif op == "reset":
            patched[key] = rule.get("value", 0)
        elif op == "set":
            patched[key] = rule.get("value")
        elif op == "copy":
            patched[key] = patched.get(str(rule.get("from_key") or ""))
    return patched


def _apply_derived_fields(inputs: dict[str, Any], fields: list[Any]) -> dict[str, Any]:
    patched = dict(inputs)
    for raw_field in fields:
        if not isinstance(raw_field, dict):
            continue
        field = dict(raw_field)
        key = str(field.get("key") or "").strip()
        op = str(field.get("op") or "").strip()
        if not key or not op:
            continue
        try:
            if op == "copy":
                patched[key] = patched.get(str(field.get("from_key") or ""))
            elif op == "add":
                base = _numeric_value(patched.get(str(field.get("from_key") or "")), 0)
                value_key = str(field.get("value_key") or "").strip()
                value = _numeric_value(patched.get(value_key), None) if value_key else None
                if value is None:
                    value = _numeric_value(field.get("value"), 0)
                patched[key] = base + _numeric_value(value, 0) + _numeric_value(field.get("offset"), 0)
            elif op == "multiply":
                base = _numeric_value(patched.get(str(field.get("from_key") or "")), 0)
                value_key = str(field.get("value_key") or "").strip()
                value = _numeric_value(patched.get(value_key), None) if value_key else None
                if value is None:
                    value = _numeric_value(field.get("value"), 1)
                patched[key] = base * _numeric_value(value, 1)
            elif op == "ordinal_group":
                base = _numeric_value(patched.get(str(field.get("from_key") or "")), 1)
                size_key = str(field.get("size_key") or "").strip()
                size = _numeric_value(patched.get(size_key), None) if size_key else None
                if size is None:
                    size = _numeric_value(field.get("size"), 1)
                size = max(1, int(size or 1))
                patched[key] = int((int(base) - 1) / size) + 1
            elif op == "format":
                patched[key] = str(field.get("template") or "").format_map(_SafeFormatDict(patched))
            elif op == "range":
                start = int(_numeric_value(patched.get(str(field.get("start_key") or "")), 0))
                end = int(_numeric_value(patched.get(str(field.get("end_key") or "")), start))
                patched[key] = list(range(start, end + 1))
            elif op == "join":
                values = list(patched.get(str(field.get("from_key") or "")) or [])
                prefix = str(field.get("prefix") or "")
                suffix = str(field.get("suffix") or "")
                separator = str(field.get("separator") or ",")
                patched[key] = separator.join(f"{prefix}{item}{suffix}" for item in values)
        except Exception:
            patched.setdefault("_derived_field_errors", []).append({"key": key, "op": op})
    return patched


def _loop_state_after_decision(*, state: GraphLoopState, decision: dict[str, Any]) -> dict[str, Any]:
    loop_state = dict(state.loop_state or {})
    frames = {key: dict(value) for key, value in dict(loop_state.get("frames") or {}).items()}
    frame_id = str(decision.get("frame_id") or decision.get("scope_id") or "").strip()
    if frame_id:
        frame = dict(frames.get(frame_id) or {"frame_id": frame_id, "scope_id": str(decision.get("scope_id") or frame_id)})
        frame["last_decision"] = dict(decision)
        frame["iteration_index"] = int(_numeric_value(frame.get("iteration_index"), 0)) + (1 if str(decision.get("action") or "") == "continue" else 0)
        frame["status"] = "exited" if str(decision.get("action") or "") == "exit" else ("blocked" if str(decision.get("action") or "") == "blocked" else "active")
        frame["scope_node_ids"] = list(decision.get("scope_node_ids") or frame.get("scope_node_ids") or [])
        frames[frame_id] = frame
    history = [dict(item) for item in list(loop_state.get("route_history") or []) if isinstance(item, dict)]
    history.append(
        {
            key: value
            for key, value in dict(decision).items()
            if key not in {"initial_inputs_patch", "route_policy"}
        }
    )
    return {
        **loop_state,
        "authority": "harness.graph.loop_contract_state",
        "frames": frames,
        "route_history": history,
    }


def _result_history_with_result(
    *,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    result_ref: str = "",
) -> dict[str, tuple[dict[str, Any], ...]]:
    history = {key: tuple(dict(item) for item in value) for key, value in state.result_history.items()}
    node_history = list(history.get(result.node_id) or ())
    node_history.append(_node_result_summary(result, result_ref=result_ref))
    history[result.node_id] = tuple(node_history)
    return history


def _numeric_value(value: Any, default: Any = 0) -> Any:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number.is_integer():
        return int(number)
    return number


def _nested_lookup(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in [item for item in str(dotted_key or "").split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


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


def _state_with_work_orders(
    state: GraphLoopState,
    work_orders: tuple[GraphNodeWorkOrder, ...],
    *,
    services: Any | None = None,
) -> GraphLoopState:
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
        work_order_ref = store_work_order(services, order) if services is not None else ""
        work_order_index[order.work_order_id] = _work_order_summary(order, work_order_ref=work_order_ref)
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


def _node_status_from_result(result: NodeResultEnvelope) -> str:
    if result.status == "completed":
        return "completed"
    if result.status == "waiting_human_gate":
        return "waiting_human_gate"
    if result.status == "blocked":
        return "blocked"
    return "failed"


def _loop_state_summary(state: GraphLoopState) -> dict[str, Any]:
    return {
        "authority": "harness.graph_loop_state_summary",
        "state_id": state.state_id,
        "graph_run_id": state.graph_run_id,
        "task_run_id": state.task_run_id,
        "session_id": state.session_id,
        "config_id": state.config_id,
        "config_hash": state.config_hash,
        "graph_id": state.graph_id,
        "status": state.status,
        "ready_node_ids": list(state.ready_node_ids),
        "running_node_ids": list(state.running_node_ids),
        "completed_node_ids": list(state.completed_node_ids),
        "failed_node_ids": list(state.failed_node_ids),
        "blocked_node_ids": list(state.blocked_node_ids),
        "active_work_orders": dict(state.active_work_orders),
        "node_state_count": len(state.node_states),
        "edge_state_count": len(state.edge_states),
        "result_count": len(state.result_index),
        "event_cursor": state.event_cursor,
        "terminal_reason": state.terminal_reason,
    }


def _work_order_summary(order: GraphNodeWorkOrder, *, work_order_ref: str = "") -> dict[str, Any]:
    return work_order_summary(order, work_order_ref=work_order_ref)


def _node_result_summary(result: NodeResultEnvelope, *, result_ref: str = "") -> dict[str, Any]:
    return node_result_summary(result, result_ref=result_ref)


def _graph_result_summary(result: GraphResultEnvelope | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "authority": "harness.graph_result_summary",
        "result_id": result.result_id,
        "graph_run_id": result.graph_run_id,
        "task_run_id": result.task_run_id,
        "graph_id": result.graph_id,
        "config_id": result.config_id,
        "status": result.status,
        "artifact_refs": list(result.artifact_refs),
        "node_result_refs": list(result.node_result_refs),
        "terminal_reason": result.terminal_reason,
        "created_at": result.created_at,
    }


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


def _outgoing_state_edges(graph_config: GraphHarnessConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    source = str(node_id or "")
    scheduler_edge_ids = {str(edge.get("edge_id") or "") for edge in _outgoing_dependency_edges(graph_config, source)}
    flow_edge_ids = {str(edge.get("edge_id") or "") for edge in build_outbound_flow_edges(graph_config, source)}
    edges: list[dict[str, Any]] = []
    for edge in graph_config.edges:
        payload = dict(edge)
        if str(payload.get("source_node_id") or "") != source:
            continue
        edge_id = str(payload.get("edge_id") or "")
        if edge_id in scheduler_edge_ids or edge_id in flow_edge_ids:
            edges.append(payload)
    return tuple(edges)


def _edge_states_after_node_result(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    result_ref: str,
    services: Any | None = None,
) -> dict[str, dict[str, Any]]:
    edge_states = {key: dict(value) for key, value in state.edge_states.items()}
    now = time.time()
    for edge in _outgoing_state_edges(graph_config, result.node_id):
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        edge_state = dict(edge_states.get(edge_id) or {})
        packet_summary: dict[str, Any] = {}
        if result.status == "completed" and edge_delivers_flow_packet(edge):
            packet = build_flow_packet(
                graph_config=graph_config,
                state=state,
                edge=edge,
                result=result,
                result_ref=result_ref,
                created_at=now,
            )
            packet_ref = store_flow_packet(services, packet) if services is not None else ""
            packet_summary = flow_packet_summary(packet, packet_ref=packet_ref)
            existing_packets = [
                dict(item)
                for item in list(edge_state.get("packet_refs") or [])
                if isinstance(item, dict) and str(item.get("packet_ref") or "")
            ]
            existing_packets.append(packet_summary)
            edge_state["packet_refs"] = existing_packets
            edge_state["latest_packet_id"] = packet.packet_id
            edge_state["latest_packet_ref"] = packet_ref
            edge_state["latest_packet"] = packet_summary
        else:
            edge_state.pop("packet_refs", None)
            edge_state.pop("latest_packet_id", None)
            edge_state.pop("latest_packet_ref", None)
            edge_state.pop("latest_packet", None)
        edge_state.update(
            {
                "edge_id": edge_id,
                "source_node_id": result.node_id,
                "target_node_id": str(edge.get("target_node_id") or ""),
                "status": "ready" if result.status == "completed" else "source_failed",
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
    services: Any | None = None,
) -> GraphResultEnvelope:
    result_refs = [
        str(dict(item).get("result_ref") or dict(item).get("result_id") or "")
        for item in state.result_index.values()
        if str(dict(item).get("result_ref") or dict(item).get("result_id") or "")
    ]
    artifact_refs = _graph_artifact_refs(state)
    return GraphResultEnvelope(
        result_id=f"gresult:{safe_id(state.graph_run_id)}",
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        graph_id=graph_config.graph_id,
        config_id=graph_config.config_id,
        status=status,
        outputs={},
        artifact_refs=tuple(artifact_refs),
        node_result_refs=tuple(result_refs),
        diagnostics={
            "artifact_materialization_receipts": _graph_receipts(state, "artifact_materialization_receipts", services=services),
            "memory_commit_receipts": _graph_receipts(state, "memory_commit_receipts", services=services),
            "authority": "harness.graph_result_envelope.diagnostics",
        },
        terminal_reason=terminal_reason or status,
        created_at=time.time(),
    )


def _graph_artifact_refs(state: GraphLoopState) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for result in state.result_index.values():
        for raw in list(dict(result).get("artifact_refs") or []):
            ref = str(raw or "").strip()
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def _graph_receipts(state: GraphLoopState, key: str, *, services: Any | None = None) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for result in state.result_index.values():
        if services is None:
            continue
        stored = load_node_result(services, dict(result))
        if stored is not None:
            receipts.extend(dict(item) for item in list(stored.to_dict().get(key) or []) if isinstance(item, dict))
    return receipts
