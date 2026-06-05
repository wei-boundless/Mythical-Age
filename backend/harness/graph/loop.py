from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from runtime.shared.models import TaskRun
from task_system.runtime_semantics.chapter_progress import (
    ChapterProgressReceiptError,
    first_chapter_progress_receipt,
)
from task_system.runtime_semantics.review_gate_verdict import (
    extract_review_verdict,
    review_verdict_is_rejected,
)

from .checkpoint_store import checkpoint_store_from_services
from .context_materializer import GraphContextMaterializer
from .flow_edges import build_outbound_flow_edges
from .flow_packet import build_flow_packet, edge_delivers_flow_packet
from .language import REVISION_EDGE_TYPES
from .model_overrides import merge_runtime_settings
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
from .scheduler_view import build_scheduler_view
from .state_machine import GraphStateMachine


_STATE_MACHINE = GraphStateMachine()


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
        self._state_machine = _STATE_MACHINE

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
            structure_hash=envelope.structure_hash,
            structure_version=envelope.structure_version,
            config_snapshot_id=envelope.config_snapshot_id or envelope.config_id,
            config_snapshot_hash=envelope.config_snapshot_hash or envelope.config_hash,
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
                "graph_structure_hash": envelope.structure_hash,
                "graph_structure_version": envelope.structure_version,
                "config_snapshot_id": envelope.config_snapshot_id or envelope.config_id,
                "config_snapshot_hash": envelope.config_snapshot_hash or envelope.config_hash,
                "runtime_scope": dict(envelope.memory_scope.get("runtime_scope") or {}),
                "static_topology_view": dict(envelope.static_topology_view or {}),
                "contract_index": dict(envelope.contract_index or {}),
                "state_machine_spec": dict(envelope.state_machine_spec or {}),
                "loop_control_spec": dict(envelope.loop_control_spec or {}),
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
        assert_graph_config_compatible_with_state(graph_config=graph_config, state=state)
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
        assert_graph_config_compatible_with_state(graph_config=graph_config, state=state)
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
        post_node_gate = _post_node_gate_wait_decision(
            graph_config=graph_config,
            result=envelope,
            result_ref=result_ref,
        )
        if post_node_gate:
            current_node["status"] = "waiting_human_gate"
            current_node["human_gate"] = post_node_gate
        node_states[envelope.node_id] = current_node
        edge_states = (
            {key: dict(value) for key, value in state.edge_states.items()}
            if post_node_gate
            else _edge_states_after_node_result(
                graph_config=graph_config,
                state=state,
                result=envelope,
                result_ref=result_ref,
                services=self._services,
            )
        )
        result_index = {key: dict(value) for key, value in state.result_index.items()}
        result_summary = _node_result_summary(envelope, result_ref=result_ref)
        result_index[envelope.node_id] = result_summary
        result_history = _result_history_with_result(state=state, result=envelope, result_ref=result_ref)
        loop_state = _loop_state_with_iteration_result(
            graph_config=graph_config,
            state=state,
            node_id=envelope.node_id,
            result_summary=result_summary,
        )
        active_work_orders = dict(state.active_work_orders)
        active_work_orders.pop(envelope.node_id, None)
        next_state = _replace_state(
            state,
            node_states=node_states,
            edge_states=edge_states,
            result_index=result_index,
            result_history=result_history,
            loop_state=loop_state,
            active_work_orders=active_work_orders,
        )
        route_decision = _evaluate_loop_route(graph_config=graph_config, state=next_state, result=envelope, services=self._services)
        if route_decision:
            next_state = _state_after_loop_route(graph_config=graph_config, state=next_state, decision=route_decision)
            node_states = {key: dict(value) for key, value in next_state.node_states.items()}
            edge_states = {key: dict(value) for key, value in next_state.edge_states.items()}
            result_index = {key: dict(value) for key, value in next_state.result_index.items()}
            active_work_orders = dict(next_state.active_work_orders)
        revision_route_decision: dict[str, Any] = {}
        revision_targets = _ready_rejected_revision_targets(graph_config=graph_config, state=next_state)
        if revision_targets:
            reset_node_ids = _revision_reset_node_ids(graph_config=graph_config, start_node_ids=revision_targets)
            next_state = _state_after_revision_requeue(
                graph_config=graph_config,
                state=next_state,
                targets=revision_targets,
                reset_node_ids=reset_node_ids,
            )
            node_states = {key: dict(value) for key, value in next_state.node_states.items()}
            edge_states = {key: dict(value) for key, value in next_state.edge_states.items()}
            result_index = {key: dict(value) for key, value in next_state.result_index.items()}
            active_work_orders = dict(next_state.active_work_orders)
            revision_route_decision = {
                "authority": "harness.graph.revision_route_decision",
                "action": "request_revision",
                "source_node_id": envelope.node_id,
                "revision_target_node_ids": list(revision_targets),
                "reset_node_ids": list(reset_node_ids),
            }
        status_snapshot = self._state_machine.status_snapshot(
            graph_config=graph_config,
            node_states=node_states,
            active_work_orders=active_work_orders,
            loop_state=next_state.loop_state,
        )
        graph_result: GraphResultEnvelope | None = None
        if status_snapshot.terminal_result_status:
            graph_result = _graph_result(
                graph_config=graph_config,
                state=next_state,
                status=status_snapshot.terminal_result_status,
                terminal_reason=status_snapshot.terminal_reason,
                services=self._services,
            )
        next_state = _replace_state(
            next_state,
            status=status_snapshot.status,
            ready_node_ids=tuple([] if graph_result else status_snapshot.ready_node_ids),
            running_node_ids=status_snapshot.running_node_ids,
            completed_node_ids=status_snapshot.completed_node_ids,
            failed_node_ids=status_snapshot.failed_node_ids,
            blocked_node_ids=status_snapshot.blocked_node_ids,
            terminal_reason=status_snapshot.terminal_reason,
        )
        work_orders = () if graph_result is not None or status_snapshot.status in {"blocked", "waiting_human_gate"} else self.dispatch_ready(graph_config=graph_config, state=next_state)
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
                    "revision_route_decision": revision_route_decision,
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

    def patch_runtime_settings_and_checkpoint(
        self,
        *,
        graph_run_id: str,
        runtime_settings_patch: dict[str, Any] | None,
    ) -> GraphLoopStart:
        state = self.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        patch = merge_runtime_settings(current={}, patch=runtime_settings_patch or {})
        if not patch:
            checkpoint = self.get_latest_checkpoint(state.graph_run_id)
            return GraphLoopStart(
                loop_state=state,
                checkpoint=checkpoint.to_dict() if checkpoint is not None else {},
            )
        diagnostics = dict(state.diagnostics or {})
        diagnostics["runtime_settings"] = merge_runtime_settings(
            current=diagnostics.get("runtime_settings") or {},
            patch=patch,
        )
        history = list(diagnostics.get("runtime_settings_patch_history") or [])
        history.append(
            {
                "authority": "harness.graph.runtime_settings_patch",
                "source": "graph_runtime_settings_patch",
                "patch": patch,
                "created_at": time.time(),
            }
        )
        diagnostics["runtime_settings_patch_history"] = history[-20:]
        diagnostics["runtime_settings_revision"] = int(diagnostics.get("runtime_settings_revision") or 0) + 1
        next_state = _advance_event_cursor(_replace_state(state, diagnostics=diagnostics))
        checkpoint = self._write_state(next_state)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_runtime_settings_patched",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "runtime_settings": diagnostics["runtime_settings"],
                },
                refs={"graph_run_ref": next_state.graph_run_id, "graph_harness_config_ref": next_state.config_id},
            )
        ]
        return GraphLoopStart(loop_state=next_state, checkpoint=checkpoint, events=tuple(events))

    def requeue_nodes_and_checkpoint(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        start_node_ids: tuple[str, ...],
        runtime_settings_patch: dict[str, Any] | None = None,
        reset_downstream: bool = True,
    ) -> GraphLoopStart:
        state = self.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        assert_graph_config_compatible_with_state(graph_config=graph_config, state=state)
        targets = tuple(dict.fromkeys(str(item).strip() for item in start_node_ids if str(item).strip()))
        if not targets:
            raise ValueError("Graph node requeue requires start_node_ids")
        missing = [item for item in targets if _node_by_id(graph_config, item) is None]
        if missing:
            raise ValueError(f"Graph node requeue target not found: {', '.join(missing)}")
        reset_node_ids = _revision_reset_node_ids(graph_config=graph_config, start_node_ids=targets) if reset_downstream else targets
        next_state = _state_after_revision_requeue(
            graph_config=graph_config,
            state=state,
            targets=targets,
            reset_node_ids=reset_node_ids,
        )
        diagnostics = dict(next_state.diagnostics or {})
        diagnostics.update(
            {
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
                "config_snapshot_id": graph_config.config_id,
                "config_snapshot_hash": graph_config.content_hash,
                "graph_structure_hash": _effective_structure_hash(graph_config=graph_config, state=state),
                "graph_structure_version": state.structure_version or "graph_structure.v1",
            }
        )
        if runtime_settings_patch:
            diagnostics["runtime_settings"] = merge_runtime_settings(
                current=diagnostics.get("runtime_settings") or {},
                patch=dict(runtime_settings_patch or {}),
            )
            history = list(diagnostics.get("runtime_settings_patch_history") or [])
            history.append(
                {
                    "authority": "harness.graph.runtime_settings_patch",
                    "source": "graph_requeue_nodes",
                    "patch": dict(runtime_settings_patch or {}),
                    "created_at": time.time(),
                }
            )
            diagnostics["runtime_settings_patch_history"] = history[-20:]
            diagnostics["runtime_settings_revision"] = int(diagnostics.get("runtime_settings_revision") or 0) + 1
        next_state = _replace_state(
            next_state,
            config_id=graph_config.config_id,
            config_hash=graph_config.content_hash,
            config_snapshot_id=graph_config.config_id,
            config_snapshot_hash=graph_config.content_hash,
            structure_hash=_effective_structure_hash(graph_config=graph_config, state=state),
            structure_version=state.structure_version or "graph_structure.v1",
            diagnostics=diagnostics,
        )
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_nodes_requeued",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "start_node_ids": list(targets),
                    "reset_node_ids": list(reset_node_ids),
                    "runtime_settings_patched": bool(runtime_settings_patch),
                    "graph_loop_state": _loop_state_summary(next_state),
                },
                refs={"graph_run_ref": next_state.graph_run_id, "graph_harness_config_ref": next_state.config_snapshot_id or next_state.config_id},
            )
        ]
        self._update_formal_runs(next_state, graph_result=None)
        return GraphLoopStart(loop_state=next_state, checkpoint=checkpoint, events=tuple(events))

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
        edge_states = {key: dict(value) for key, value in state.edge_states.items()}
        active_work_orders = dict(state.active_work_orders)
        now = time.time()
        for node_id in targets:
            node = dict(node_states.get(node_id) or {})
            if not node:
                continue
            node["status"] = "ready"
            node["updated_at"] = now
            for key in ("blocked_reason", "result_ref", "work_order_id"):
                node.pop(key, None)
            node_states[node_id] = node
            active_work_orders.pop(node_id, None)
            edge_states = _reset_outgoing_failed_edges(
                edge_states=edge_states,
                source_node_id=node_id,
                updated_at=now,
            )
        next_state = _replace_state(
            state,
            status="running",
            node_states=node_states,
            edge_states=edge_states,
            active_work_orders=active_work_orders,
            ready_node_ids=tuple(dict.fromkeys([*state.ready_node_ids, *targets])),
            running_node_ids=(),
            blocked_node_ids=tuple(
                node_id
                for node_id, payload in node_states.items()
                if str(payload.get("status") or "") in {"blocked", "waiting_human_gate"}
            ),
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

    def requeue_recoverable_failed_nodes_and_checkpoint(
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
        edge_states = {key: dict(value) for key, value in state.edge_states.items()}
        result_index = {key: dict(value) for key, value in state.result_index.items()}
        active_work_orders = dict(state.active_work_orders)
        now = time.time()
        for node_id in targets:
            node = dict(node_states.get(node_id) or {})
            if not node:
                continue
            node["status"] = "ready"
            node["updated_at"] = now
            for key in ("blocked_reason", "result_ref", "work_order_id"):
                node.pop(key, None)
            node_states[node_id] = node
            result_index.pop(node_id, None)
            active_work_orders.pop(node_id, None)
            edge_states = _reset_outgoing_failed_edges(
                edge_states=edge_states,
                source_node_id=node_id,
                updated_at=now,
            )
        target_set = set(targets)
        next_state = _replace_state(
            state,
            status="running",
            node_states=node_states,
            edge_states=edge_states,
            result_index=result_index,
            active_work_orders=active_work_orders,
            ready_node_ids=tuple(dict.fromkeys([*state.ready_node_ids, *targets])),
            running_node_ids=(),
            failed_node_ids=tuple(item for item in state.failed_node_ids if item not in target_set),
            blocked_node_ids=tuple(
                node_id
                for node_id, payload in node_states.items()
                if str(payload.get("status") or "") in {"blocked", "waiting_human_gate"}
            ),
            terminal_reason="",
        )
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_recoverable_failed_nodes_requeued",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "node_ids": list(targets),
                    "graph_loop_state": _loop_state_summary(next_state),
                },
                refs={"graph_run_ref": next_state.graph_run_id, "graph_harness_config_ref": next_state.config_id},
            )
        ]
        return GraphLoopStart(loop_state=next_state, checkpoint=checkpoint, events=tuple(events))

    def requeue_ready_revision_targets_and_checkpoint(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
    ) -> GraphLoopStart:
        targets = _ready_rejected_revision_targets(graph_config=graph_config, state=state)
        if not targets:
            checkpoint = self.get_latest_checkpoint(state.graph_run_id)
            return GraphLoopStart(
                loop_state=state,
                checkpoint=checkpoint.to_dict() if checkpoint is not None else {},
            )
        reset_node_ids = _revision_reset_node_ids(graph_config=graph_config, start_node_ids=targets)
        next_state = _state_after_revision_requeue(
            graph_config=graph_config,
            state=state,
            targets=targets,
            reset_node_ids=reset_node_ids,
        )
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_revision_targets_requeued",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "revision_target_node_ids": list(targets),
                    "reset_node_ids": list(reset_node_ids),
                    "graph_loop_state": _loop_state_summary(next_state),
                },
                refs={"graph_run_ref": next_state.graph_run_id, "graph_harness_config_ref": next_state.config_id},
            )
        ]
        return GraphLoopStart(loop_state=next_state, checkpoint=checkpoint, events=tuple(events))

    def apply_human_gate_decision_and_checkpoint(
        self,
        *,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        decision: dict[str, Any],
        max_requests: int | None = None,
    ) -> GraphLoopAdvance:
        state = self.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        node_id = str(decision.get("node_id") or "").strip()
        if not node_id:
            waiting = [item for item, payload in state.node_states.items() if str(dict(payload).get("status") or "") == "waiting_human_gate"]
            node_id = waiting[0] if waiting else ""
        if not node_id:
            raise ValueError("HumanGateDecision requires node_id or an active waiting human gate")
        node_states = {key: dict(value) for key, value in state.node_states.items()}
        node_state = dict(node_states.get(node_id) or {})
        if str(node_state.get("status") or "") != "waiting_human_gate":
            raise ValueError("HumanGateDecision target node is not waiting_human_gate")
        result_ref = str(dict(node_state.get("human_gate") or {}).get("source_result_ref") or node_state.get("result_ref") or "")
        result = load_node_result(self._services, {"result_ref": result_ref}) if result_ref else None
        if result is None:
            raise ValueError("HumanGateDecision target result not found")
        action = str(decision.get("human_action") or decision.get("action") or "").strip()
        if action not in {"approve_continue", "request_revision", "reroute_to_node", "abort_graph", "stop_and_checkpoint"}:
            raise ValueError(f"unsupported HumanGateDecision action: {action}")
        human_gate = {
            **dict(node_state.get("human_gate") or {}),
            "decision": {
                **dict(decision),
                "node_id": node_id,
                "source_result_id": result.result_id,
                "authority": "harness.graph.human_gate_decision",
            },
        }
        node_state["human_gate"] = human_gate
        edge_states = {key: dict(value) for key, value in state.edge_states.items()}
        graph_result = None
        terminal_reason = ""
        if action == "approve_continue":
            node_state["status"] = "completed"
            node_state["updated_at"] = time.time()
            node_states[node_id] = node_state
            edge_states = _edge_states_after_node_result(
                graph_config=graph_config,
                state=state,
                result=result,
                result_ref=result_ref,
                services=self._services,
            )
            status = "running"
        elif action in {"request_revision", "reroute_to_node"}:
            target = str(decision.get("route_target_node_id") or decision.get("target_node_id") or "").strip()
            if not target:
                raise ValueError("HumanGateDecision revision/reroute requires route_target_node_id")
            node_state["status"] = "completed"
            node_state["updated_at"] = time.time()
            node_states[node_id] = node_state
            target_state = dict(node_states.get(target) or {})
            if not target_state:
                raise ValueError(f"HumanGateDecision route target not found: {target}")
            target_state["status"] = "ready"
            target_state["updated_at"] = time.time()
            target_state["human_gate_route_from"] = node_id
            node_states[target] = target_state
            status = "running"
        elif action == "abort_graph":
            node_state["updated_at"] = time.time()
            node_states[node_id] = node_state
            status = "failed"
            terminal_reason = "human_gate_aborted"
        else:
            node_state["updated_at"] = time.time()
            node_states[node_id] = node_state
            status = "waiting_human_gate"
            terminal_reason = f"waiting_human_gate:{node_id}"
        next_state = _replace_state(
            state,
            status=status,
            node_states=node_states,
            edge_states=edge_states,
            active_work_orders={},
            terminal_reason=terminal_reason,
        )
        if status == "failed":
            graph_result = _graph_result(graph_config=graph_config, state=next_state, status="failed", terminal_reason=terminal_reason, services=self._services)
        ready = _ready_nodes(graph_config=graph_config, node_states=node_states, loop_state=state.loop_state)
        if action in {"request_revision", "reroute_to_node"}:
            target = str(decision.get("route_target_node_id") or decision.get("target_node_id") or "").strip()
            ready = tuple(dict.fromkeys([target, *ready]))
        next_state = _replace_state(
            next_state,
            ready_node_ids=tuple([] if graph_result else ready),
            running_node_ids=(),
            completed_node_ids=tuple(node for node, payload in node_states.items() if str(payload.get("status") or "") == "completed"),
            failed_node_ids=tuple(node for node, payload in node_states.items() if str(payload.get("status") or "") == "failed"),
            blocked_node_ids=tuple(node for node, payload in node_states.items() if str(payload.get("status") or "") in {"blocked", "waiting_human_gate"}),
        )
        work_orders = () if graph_result is not None or status == "waiting_human_gate" else self.dispatch_ready(graph_config=graph_config, state=next_state, max_requests=max_requests)
        if work_orders:
            next_state = _state_with_work_orders(next_state, work_orders, services=self._services)
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state, pending_work_orders=work_orders)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_human_gate_decision_applied",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "human_gate_decision": dict(decision),
                    "graph_loop_state": _loop_state_summary(next_state),
                    "node_work_orders": [_work_order_summary(item) for item in work_orders],
                    "graph_result": _graph_result_summary(graph_result),
                },
                refs={"graph_run_ref": next_state.graph_run_id, "node_ref": node_id},
            )
        ]
        self._update_formal_runs(next_state, graph_result=graph_result)
        return GraphLoopAdvance(
            loop_state=next_state,
            checkpoint=checkpoint,
            accepted_result=result,
            graph_result=graph_result,
            node_work_orders=work_orders,
            events=tuple(events),
        )

    def reset_source_failed_edges_for_nodes_and_checkpoint(
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
        edge_states = {key: dict(value) for key, value in state.edge_states.items()}
        now = time.time()
        for node_id in targets:
            edge_states = _reset_outgoing_failed_edges(
                edge_states=edge_states,
                source_node_id=node_id,
                updated_at=now,
            )
        state_patch: dict[str, Any] = {}
        if state.status == "blocked" and any(node_id in dict(state.active_work_orders or {}) for node_id in targets):
            state_patch["status"] = "running"
            state_patch["terminal_reason"] = ""
        if edge_states == state.edge_states and not state_patch:
            checkpoint = self.get_latest_checkpoint(state.graph_run_id)
            return GraphLoopStart(
                loop_state=state,
                checkpoint=checkpoint.to_dict() if checkpoint is not None else {},
            )
        next_state = _replace_state(state, edge_states=edge_states, **state_patch)
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state)
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_source_failed_edges_reset_for_active_nodes",
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
        self._state_machine.validate(state)
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
        now = time.time()
        if graph_result is not None:
            self._services.runtime_objects.put_object(
                "graph_result",
                safe_id(graph_result.result_id),
                graph_result.to_dict(),
            )
        status = "completed" if graph_result is not None and graph_result.status == "completed" else ("failed" if graph_result is not None else state.status)
        terminal_reason = (graph_result.terminal_reason or graph_result.status) if graph_result is not None else state.terminal_reason
        audit = _state_identity_audit(state)
        current_task = self._services.state_index.get_task_run(state.task_run_id)
        if current_task is not None:
            diagnostics = {
                **dict(current_task.diagnostics or {}),
                **audit,
            }
            if graph_result is not None:
                diagnostics["graph_result"] = graph_result.to_dict()
            self._services.state_index.upsert_task_run(
                TaskRun(
                    **{
                        **current_task.to_dict(),
                        "status": status,
                        "updated_at": now,
                        "terminal_reason": terminal_reason,
                        "diagnostics": diagnostics,
                    }
                )
            )
        graph_run = self._services.runtime_objects.get_object(f"rtobj:graph_run:{safe_id(state.graph_run_id)}")
        if graph_run:
            diagnostics = {
                **dict(dict(graph_run).get("diagnostics") or {}),
                **audit,
            }
            if graph_result is not None:
                diagnostics["graph_result"] = graph_result.to_dict()
            self._services.runtime_objects.put_object(
                "graph_run",
                safe_id(state.graph_run_id),
                {
                    **dict(graph_run),
                    "status": status,
                    "updated_at": now,
                    "terminal_reason": terminal_reason,
                    "config_id": state.config_snapshot_id or state.config_id,
                    "config_hash": state.config_snapshot_hash or state.config_hash,
                    "structure_hash": state.structure_hash,
                    "structure_version": state.structure_version,
                    "config_snapshot_id": state.config_snapshot_id or state.config_id,
                    "config_snapshot_hash": state.config_snapshot_hash or state.config_hash,
                    "diagnostics": diagnostics,
                },
            )


def _initial_node_states(graph_config: GraphHarnessConfig) -> dict[str, dict[str, Any]]:
    return _STATE_MACHINE.initial_node_states(graph_config)


def _initial_edge_states(graph_config: GraphHarnessConfig) -> dict[str, dict[str, Any]]:
    return _STATE_MACHINE.initial_edge_states(graph_config)


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
    inputs = _initial_loop_inputs(graph_config=graph_config, envelope=envelope)
    for raw in graph_config.loop_frames:
        frame = _normalize_loop_frame(dict(raw))
        frame_id = str(frame.get("frame_id") or "")
        if not frame_id:
            continue
        cursor_key = str(frame.get("cursor_key") or "").strip()
        start_key = str(frame.get("start_key") or "").strip()
        end_key = str(frame.get("end_key") or "").strip()
        start_value = _numeric_value(inputs.get(start_key), None) if start_key else None
        cursor_value = _numeric_value(inputs.get(cursor_key), start_value) if cursor_key else None
        end_value = _numeric_value(inputs.get(end_key), None) if end_key else None
        step = int(_numeric_value(frame.get("step"), 1) or 1)
        identity_values = {**inputs, **frame, "cursor": cursor_value, "iteration_index": 0, "scope_id": str(frame.get("scope_id") or frame_id)}
        frames[frame_id] = {
            **frame,
            "status": "active",
            "iteration_index": 0,
            "cursor": cursor_value,
            "start": start_value,
            "end": end_value,
            "step": step,
            "active_iteration_id": _loop_iteration_id(frame=frame, values=identity_values),
            "scope_node_ids": list(_loop_scope_node_ids(graph_config=graph_config, frame=frame)),
        }
    return {
        "authority": "harness.graph.loop_contract_state",
        "graph_run_id": envelope.graph_run_id,
        "frames": frames,
        "route_history": [],
        "iteration_results": {},
    }


def _normalize_loop_frame(frame: dict[str, Any]) -> dict[str, Any]:
    frame_id = str(frame.get("frame_id") or frame.get("scope_id") or "").strip()
    return _drop_empty(
        {
            **frame,
            "frame_id": frame_id,
            "scope_id": str(frame.get("scope_id") or frame_id).strip(),
            "parent_scope_id": str(frame.get("parent_scope_id") or "").strip(),
            "entry_node_id": str(frame.get("entry_node_id") or "").strip(),
            "router_node_id": str(frame.get("router_node_id") or "").strip(),
            "continue_node_id": str(frame.get("continue_node_id") or "").strip(),
            "exit_node_id": str(frame.get("exit_node_id") or "").strip(),
            "scope_node_ids": [str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)],
            "cursor_key": str(frame.get("cursor_key") or "").strip(),
            "start_key": str(frame.get("start_key") or "").strip(),
            "end_key": str(frame.get("end_key") or "").strip(),
            "step": int(_numeric_value(frame.get("step"), 1) or 1),
            "iteration_index_key": str(frame.get("iteration_index_key") or "").strip(),
            "iteration_identity_template": str(frame.get("iteration_identity_template") or "").strip(),
            "progress_receipt_key": str(frame.get("progress_receipt_key") or "").strip(),
            "reset_scope_on_continue": frame.get("reset_scope_on_continue"),
            "preserve_iteration_results": frame.get("preserve_iteration_results"),
            "aggregate_policy": dict(frame.get("aggregate_policy") or {}),
        }
    )


def _evaluate_loop_route(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    services: Any | None = None,
) -> dict[str, Any]:
    if result.status != "completed":
        return {}
    node = _node_by_id(graph_config, result.node_id) or {}
    node_loop = dict(node.get("loop") or {})
    route_policy = dict(node_loop.get("route_policy") or {})
    if not route_policy:
        return {}
    mode = str(route_policy.get("mode") or "metric_target").strip() or "metric_target"
    if mode == "progress_receipt":
        return _evaluate_progress_receipt_route(
            graph_config=graph_config,
            state=state,
            result=result,
            node=node,
            node_loop=node_loop,
            route_policy=route_policy,
            services=services,
        )
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
    current_value = _numeric_value(patched_inputs.get(current_key), 0) if current_key else 0
    target_value = _numeric_value(patched_inputs.get(target_key), 0) if target_key else 0
    action = "exit" if target_key and current_value >= target_value else "continue"
    cursor_key = str(frame.get("cursor_key") or "").strip()
    cursor_set_by_route = bool(
        cursor_key
        and (
            cursor_key == current_key
            or _patch_rules_target_key(list(route_policy.get("patch_rules") or []), cursor_key)
        )
    )
    if not cursor_set_by_route:
        patched_inputs = _apply_frame_cursor_patch(inputs=patched_inputs, frame=frame, action=action)
    if action == "continue":
        patched_inputs = _apply_child_loop_input_resets(
            graph_config=graph_config,
            inputs=patched_inputs,
            parent_frame=frame,
        )
    patched_inputs = _apply_derived_fields(patched_inputs, list(route_policy.get("derived_fields") or []))
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
        "reset_scope_on_continue": frame.get("reset_scope_on_continue"),
        "preserve_iteration_results": frame.get("preserve_iteration_results"),
    }


def _evaluate_progress_receipt_route(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    node: dict[str, Any],
    node_loop: dict[str, Any],
    route_policy: dict[str, Any],
    services: Any | None,
) -> dict[str, Any]:
    scope_id = str(route_policy.get("scope_id") or node_loop.get("scope_id") or "").strip()
    frame = _loop_frame_for_route(graph_config=graph_config, scope_id=scope_id, node_id=result.node_id, route_policy=route_policy)
    receipt_key = str(route_policy.get("progress_receipt_key") or "chapter_progress_receipt").strip()
    try:
        receipt = first_chapter_progress_receipt(
            _progress_receipt_sources(
                graph_config=graph_config,
                state=state,
                result=result,
                route_policy=route_policy,
                services=services,
            ),
            key=receipt_key,
            initial_inputs=dict(state.initial_inputs or {}),
        )
    except ChapterProgressReceiptError as exc:
        return {
            "authority": "harness.graph.loop_route_decision",
            "action": "blocked",
            "reason": "loop_route_progress_receipt_missing",
            "detail": str(exc),
            "node_id": result.node_id,
            "scope_id": scope_id,
            "route_policy": route_policy,
        }
    if route_policy.get("receipt_to_input_mappings") or route_policy.get("receipt_complete_key") or route_policy.get("receipt_metric_key"):
        return _evaluate_generic_progress_receipt_route(
            graph_config=graph_config,
            state=state,
            result=result,
            route_policy=route_policy,
            frame=frame,
            receipt=receipt,
            scope_id=scope_id,
        )

    patched_inputs = dict(state.initial_inputs or {})
    committed_words = _numeric_value(receipt.get("committed_words"), 0)
    current_key = str(route_policy.get("current_key") or "group_current_measure").strip()
    if current_key:
        patched_inputs[current_key] = _numeric_value(patched_inputs.get(current_key), 0) + committed_words
    last_metric_key = str(route_policy.get("last_metric_key") or "last_batch_words").strip()
    if last_metric_key:
        patched_inputs[last_metric_key] = committed_words
    for counter in list(route_policy.get("secondary_counters") or []):
        if not isinstance(counter, dict):
            continue
        secondary_key = str(counter.get("current_key") or "").strip()
        if secondary_key:
            patched_inputs[secondary_key] = _numeric_value(patched_inputs.get(secondary_key), 0) + committed_words

    next_chapter_index = int(_numeric_value(receipt.get("next_chapter_index"), _numeric_value(patched_inputs.get("chapter_index"), 1)))
    batch_complete = bool(receipt.get("batch_complete"))
    patched_inputs["chapter_index"] = next_chapter_index
    patched_inputs["active_chapter_start_index"] = next_chapter_index
    patched_inputs["active_chapter_end_index"] = int(_numeric_value(receipt.get("batch_end_index"), _numeric_value(patched_inputs.get("batch_end_index"), next_chapter_index)))
    if batch_complete:
        patched_inputs["batch_start_index"] = next_chapter_index
        patched_inputs["batch_end_index"] = next_chapter_index + max(1, int(_numeric_value(patched_inputs.get("units_per_batch"), 1))) - 1
        patched_inputs["active_chapter_end_index"] = patched_inputs["batch_end_index"]
    else:
        patched_inputs["batch_start_index"] = int(_numeric_value(receipt.get("batch_start_index"), _numeric_value(patched_inputs.get("batch_start_index"), next_chapter_index)))
        patched_inputs["batch_end_index"] = int(_numeric_value(receipt.get("batch_end_index"), _numeric_value(patched_inputs.get("batch_end_index"), patched_inputs["active_chapter_end_index"])))
    patched_inputs["active_chapter_range"] = f"{int(patched_inputs['active_chapter_start_index']):03d}-{int(patched_inputs['active_chapter_end_index']):03d}"
    patched_inputs = _apply_patch_rules(patched_inputs, list(route_policy.get("patch_rules") or []))
    patched_inputs.setdefault("active_chapter_range", f"{int(_numeric_value(patched_inputs.get('active_chapter_start_index'), next_chapter_index)):03d}-{int(_numeric_value(patched_inputs.get('active_chapter_end_index'), next_chapter_index)):03d}")

    target_key = str(route_policy.get("target_key") or "group_target_measure").strip()
    current_value = _numeric_value(patched_inputs.get(current_key), 0) if current_key else 0
    target_value = _numeric_value(patched_inputs.get(target_key), 0) if target_key else 0
    receipt_complete = bool(receipt.get("volume_complete"))
    action = "exit" if receipt_complete or (target_key and current_value >= target_value) else "continue"
    patched_inputs = _apply_frame_cursor_patch(inputs=patched_inputs, frame=frame, action=action)
    patched_inputs = _apply_derived_fields(patched_inputs, list(route_policy.get("derived_fields") or []))
    continue_node_id = str(route_policy.get("continue_node_id") or frame.get("continue_node_id") or frame.get("entry_node_id") or "").strip()
    exit_node_id = str(route_policy.get("exit_node_id") or frame.get("exit_node_id") or "").strip()
    return {
        "authority": "harness.graph.loop_route_decision",
        "action": action,
        "reason": "volume_complete" if receipt_complete else ("target_reached" if action == "exit" else "target_not_reached"),
        "node_id": result.node_id,
        "result_id": result.result_id,
        "scope_id": scope_id,
        "frame_id": str(frame.get("frame_id") or scope_id),
        "continue_node_id": continue_node_id,
        "exit_node_id": exit_node_id,
        "metric": committed_words,
        "current_key": current_key,
        "current_value": current_value,
        "target_key": target_key,
        "target_value": target_value,
        "progress_receipt": receipt,
        "initial_inputs_patch": patched_inputs,
        "scope_node_ids": list(_loop_scope_node_ids(graph_config=graph_config, frame=frame)),
        "reset_scope_on_continue": frame.get("reset_scope_on_continue"),
        "preserve_iteration_results": frame.get("preserve_iteration_results"),
    }


def _evaluate_generic_progress_receipt_route(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    route_policy: dict[str, Any],
    frame: dict[str, Any],
    receipt: dict[str, Any],
    scope_id: str,
) -> dict[str, Any]:
    patched_inputs = dict(state.initial_inputs or {})
    metric_key = str(route_policy.get("receipt_metric_key") or "").strip()
    metric = _numeric_value(receipt.get(metric_key), 0) if metric_key else 0
    current_key = str(route_policy.get("current_key") or "").strip()
    if current_key and metric_key:
        patched_inputs[current_key] = _numeric_value(patched_inputs.get(current_key), 0) + metric
    last_metric_key = str(route_policy.get("last_metric_key") or "").strip()
    if last_metric_key and metric_key:
        patched_inputs[last_metric_key] = metric
    complete_key = str(route_policy.get("receipt_complete_key") or route_policy.get("complete_key") or "").strip()
    receipt_complete = bool(receipt.get(complete_key)) if complete_key else False
    cursor_key = str(frame.get("cursor_key") or "").strip()
    cursor_set_by_receipt = False
    for mapping in list(route_policy.get("receipt_to_input_mappings") or []):
        if not isinstance(mapping, dict):
            continue
        apply_on = [
            str(item).strip()
            for item in list(mapping.get("apply_on") or mapping.get("actions") or [])
            if str(item).strip()
        ]
        receipt_action = "exit" if receipt_complete else "continue"
        if apply_on and receipt_action not in set(apply_on):
            continue
        source_key = str(mapping.get("source_key") or mapping.get("from_key") or "").strip()
        target_key = str(mapping.get("target_key") or mapping.get("key") or "").strip()
        if not source_key or not target_key:
            continue
        if source_key in receipt:
            patched_inputs[target_key] = receipt.get(source_key)
            if cursor_key and target_key == cursor_key:
                cursor_set_by_receipt = True
    patched_inputs = _apply_patch_rules(patched_inputs, list(route_policy.get("patch_rules") or []))
    target_key = str(route_policy.get("target_key") or "").strip()
    current_value = _numeric_value(patched_inputs.get(current_key), 0) if current_key else 0
    target_value = _numeric_value(patched_inputs.get(target_key), 0) if target_key else 0
    action = "exit" if receipt_complete or (not complete_key and target_key and current_value >= target_value) else "continue"
    if not cursor_set_by_receipt:
        patched_inputs = _apply_frame_cursor_patch(inputs=patched_inputs, frame=frame, action=action)
    if action == "continue":
        patched_inputs = _apply_child_loop_input_resets(
            graph_config=graph_config,
            inputs=patched_inputs,
            parent_frame=frame,
        )
    patched_inputs = _patch_chapter_active_range_for_cursor(
        patched_inputs,
        cursor_key=cursor_key,
        start_value=_numeric_value(patched_inputs.get(cursor_key), None) if cursor_key else None,
        end_value=_numeric_value(patched_inputs.get("batch_end_index"), None),
    )
    patched_inputs = _apply_derived_fields(patched_inputs, list(route_policy.get("derived_fields") or []))
    continue_node_id = str(route_policy.get("continue_node_id") or frame.get("continue_node_id") or frame.get("entry_node_id") or "").strip()
    exit_node_id = str(route_policy.get("exit_node_id") or frame.get("exit_node_id") or "").strip()
    return {
        "authority": "harness.graph.loop_route_decision",
        "action": action,
        "reason": "receipt_complete" if receipt_complete else ("target_reached" if action == "exit" else "target_not_reached"),
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
        "progress_receipt": receipt,
        "initial_inputs_patch": patched_inputs,
        "scope_node_ids": list(_loop_scope_node_ids(graph_config=graph_config, frame=frame)),
        "reset_scope_on_continue": frame.get("reset_scope_on_continue"),
        "preserve_iteration_results": frame.get("preserve_iteration_results"),
    }


def _state_after_loop_route(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    decision: dict[str, Any],
) -> GraphLoopState:
    action = str(decision.get("action") or "").strip()
    loop_state = _loop_state_after_decision(state=state, decision=decision)
    if action == "continue" and decision.get("preserve_iteration_results") is False:
        loop_state = _loop_state_without_frame_iteration_results(loop_state=loop_state, frame_id=str(decision.get("frame_id") or decision.get("scope_id") or ""))
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
        if action == "exit":
            node_states, edge_states, result_index, active_work_orders = _cancel_descendant_loop_nodes_after_parent_exit(
                graph_config=graph_config,
                loop_state=loop_state,
                parent_frame_id=str(decision.get("frame_id") or decision.get("scope_id") or ""),
                node_states=node_states,
                edge_states=edge_states,
                result_index=result_index,
                active_work_orders=active_work_orders,
            )
        return _replace_state(
            state,
            node_states=node_states,
            edge_states=edge_states,
            result_index=result_index,
            active_work_orders=active_work_orders,
            initial_inputs=dict(decision.get("initial_inputs_patch") or state.initial_inputs),
            loop_state=loop_state,
        )
    if decision.get("reset_scope_on_continue") is False:
        return _replace_state(
            state,
            initial_inputs=dict(decision.get("initial_inputs_patch") or state.initial_inputs),
            loop_state=loop_state,
        )
    scope_node_ids = [str(item) for item in list(decision.get("scope_node_ids") or []) if str(item)]
    continue_node_id = str(decision.get("continue_node_id") or "").strip()
    exit_node_id = str(decision.get("exit_node_id") or "").strip()
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
    if exit_node_id and exit_node_id != continue_node_id:
        payload = dict(node_states.get(exit_node_id) or {})
        if payload:
            payload["status"] = "pending"
            payload.pop("result_ref", None)
            payload.pop("work_order_id", None)
            payload.pop("blocked_reason", None)
            payload["updated_at"] = time.time()
            node_states[exit_node_id] = payload
            result_index.pop(exit_node_id, None)
            active_work_orders.pop(exit_node_id, None)
    reset_edge_node_ids = set(scope_node_ids)
    if exit_node_id:
        reset_edge_node_ids.add(exit_node_id)
    for edge in graph_config.edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source in reset_edge_node_ids or target in reset_edge_node_ids:
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
    explicit_scope = [str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)]
    if explicit_scope:
        return tuple(dict.fromkeys(explicit_scope))
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


def _progress_receipt_sources(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    route_policy: dict[str, Any],
    services: Any | None,
) -> list[dict[str, Any]]:
    sources = _route_metric_sources(result)
    source_node_ids = [
        str(item).strip()
        for item in list(route_policy.get("receipt_source_node_ids") or route_policy.get("progress_receipt_source_node_ids") or [])
        if str(item).strip()
    ]
    if source_node_ids:
        sources: list[dict[str, Any]] = []
        for node_id in source_node_ids:
            if node_id == result.node_id:
                sources.extend(_route_metric_sources(result))
                continue
            summary = dict(dict(state.result_index or {}).get(node_id) or {})
            loaded = _load_result_from_summary(summary, services=services)
            if loaded:
                sources.extend(_route_metric_sources(loaded))
        return sources
    sources = _route_metric_sources(result)
    source_node_ids = [
        str(edge.get("source_node_id") or "")
        for edge in graph_config.edges
        if str(edge.get("target_node_id") or "") == result.node_id
        and str(edge.get("source_node_id") or "")
    ]
    for node_id in source_node_ids:
        summary = dict(dict(state.result_index or {}).get(node_id) or {})
        loaded = _load_result_from_summary(summary, services=services)
        if loaded:
            sources.extend(_route_metric_sources(loaded))
    return sources


def _load_result_from_summary(summary: dict[str, Any], *, services: Any | None) -> NodeResultEnvelope | None:
    if services is None:
        return None
    try:
        payload = load_node_result(services, summary)
    except Exception:
        return None
    return payload


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


def _patch_rules_target_key(rules: list[Any], target_key: str) -> bool:
    if not target_key:
        return False
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        if str(raw_rule.get("key") or "").strip() == target_key:
            return True
    return False


def _apply_frame_cursor_patch(*, inputs: dict[str, Any], frame: dict[str, Any], action: str) -> dict[str, Any]:
    patched = dict(inputs or {})
    if str(action or "") != "continue":
        return patched
    cursor_key = str(frame.get("cursor_key") or "").strip()
    if not cursor_key:
        return patched
    step = int(_numeric_value(frame.get("step"), 1) or 1)
    current = _numeric_value(patched.get(cursor_key), None)
    if current is None:
        start_key = str(frame.get("start_key") or "").strip()
        current = _numeric_value(patched.get(start_key), None) if start_key else None
    if current is None:
        return patched
    patched[cursor_key] = current + step
    iteration_index_key = str(frame.get("iteration_index_key") or "").strip()
    if iteration_index_key:
        patched[iteration_index_key] = int(_numeric_value(patched.get(iteration_index_key), 0)) + 1
    return patched


def _apply_child_loop_input_resets(
    *,
    graph_config: GraphHarnessConfig,
    inputs: dict[str, Any],
    parent_frame: dict[str, Any],
) -> dict[str, Any]:
    parent_frame_id = str(parent_frame.get("frame_id") or parent_frame.get("scope_id") or "").strip()
    if not parent_frame_id:
        return dict(inputs or {})
    patched = dict(inputs or {})
    for raw_child in graph_config.loop_frames:
        child = _normalize_loop_frame(dict(raw_child))
        if not _loop_parent_matches(child, parent_frame_id):
            continue
        cursor_key = str(child.get("cursor_key") or "").strip()
        start_key = str(child.get("start_key") or "").strip()
        if not cursor_key or not start_key:
            continue
        start_value = _numeric_value(patched.get(start_key), None)
        if start_value is None:
            continue
        patched[cursor_key] = start_value
        end_key = str(child.get("end_key") or "").strip()
        patched = _patch_chapter_active_range_for_cursor(
            patched,
            cursor_key=cursor_key,
            start_value=start_value,
            end_value=_numeric_value(patched.get(end_key), None) if end_key else None,
        )
        patched = _apply_child_loop_input_resets(graph_config=graph_config, inputs=patched, parent_frame=child)
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
            elif op == "range_count":
                start = int(_numeric_value(patched.get(str(field.get("start_key") or "")), 0))
                end = int(_numeric_value(patched.get(str(field.get("end_key") or "")), start))
                patched[key] = max(0, end - start + 1)
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
    action = str(decision.get("action") or "").strip()
    patched_inputs = dict(decision.get("initial_inputs_patch") or {})
    if frame_id:
        frame = dict(frames.get(frame_id) or {"frame_id": frame_id, "scope_id": str(decision.get("scope_id") or frame_id)})
        current_iteration_index = int(_numeric_value(frame.get("iteration_index"), 0))
        next_iteration_index = current_iteration_index + (1 if action == "continue" else 0)
        cursor_key = str(frame.get("cursor_key") or "").strip()
        step = int(_numeric_value(frame.get("step"), 1) or 1)
        current_cursor = _numeric_value(frame.get("cursor"), None)
        next_cursor = _numeric_value(patched_inputs.get(cursor_key), None) if cursor_key and cursor_key in patched_inputs else None
        if next_cursor is None and action == "continue" and current_cursor is not None:
            next_cursor = _numeric_value(current_cursor, 0) + step
        if next_cursor is None:
            next_cursor = current_cursor
        frame["last_decision"] = dict(decision)
        frame["iteration_index"] = next_iteration_index
        frame["cursor"] = next_cursor
        frame["active_iteration_id"] = _loop_iteration_id(
            frame=frame,
            values={**patched_inputs, **frame, "cursor": next_cursor, "iteration_index": next_iteration_index},
        )
        frame["status"] = "exited" if action == "exit" else ("blocked" if action == "blocked" else "active")
        frame["scope_node_ids"] = list(decision.get("scope_node_ids") or frame.get("scope_node_ids") or [])
        frames[frame_id] = frame
        if action == "continue":
            frames = _reset_child_loop_frames_for_parent_continue(frames=frames, parent_frame_id=frame_id, inputs=patched_inputs)
            decision["initial_inputs_patch"] = patched_inputs
            loop_state = _loop_state_without_descendant_iteration_results(
                loop_state=loop_state,
                frames=frames,
                parent_frame_id=frame_id,
            )
        elif action == "exit":
            frames = _exit_child_loop_frames_for_parent_exit(frames=frames, parent_frame_id=frame_id)
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


def _exit_child_loop_frames_for_parent_exit(
    *,
    frames: dict[str, dict[str, Any]],
    parent_frame_id: str,
) -> dict[str, dict[str, Any]]:
    if not parent_frame_id:
        return frames
    patched_frames = {key: dict(value) for key, value in frames.items()}
    for child_frame_id in _descendant_loop_frame_ids(frames=patched_frames, parent_frame_id=parent_frame_id):
        child = dict(patched_frames.get(child_frame_id) or {})
        child["status"] = "exited"
        child["updated_at"] = time.time()
        patched_frames[child_frame_id] = child
    return patched_frames


def _reset_child_loop_frames_for_parent_continue(
    *,
    frames: dict[str, dict[str, Any]],
    parent_frame_id: str,
    inputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if not parent_frame_id:
        return frames
    patched_frames = {key: dict(value) for key, value in frames.items()}
    for child_frame_id, raw_child in list(patched_frames.items()):
        child = dict(raw_child or {})
        if not _loop_parent_matches(child, parent_frame_id):
            continue
        cursor_key = str(child.get("cursor_key") or "").strip()
        start_key = str(child.get("start_key") or "").strip()
        end_key = str(child.get("end_key") or "").strip()
        start_value = _numeric_value(inputs.get(start_key), None) if start_key else None
        cursor_value = start_value
        end_value = _numeric_value(inputs.get(end_key), None) if end_key else None
        child["status"] = "active"
        child["iteration_index"] = 0
        child["cursor"] = cursor_value
        child["start"] = start_value
        child["end"] = end_value
        if cursor_key and cursor_value is not None:
            inputs[cursor_key] = cursor_value
        inputs.update(
            _patch_chapter_active_range_for_cursor(
                inputs,
                cursor_key=cursor_key,
                start_value=cursor_value,
                end_value=end_value,
            )
        )
        child["active_iteration_id"] = _loop_iteration_id(
            frame=child,
            values={**inputs, **child, "cursor": cursor_value, "iteration_index": 0},
        )
        patched_frames[child_frame_id] = child
        patched_frames = _reset_child_loop_frames_for_parent_continue(
            frames=patched_frames,
            parent_frame_id=child_frame_id,
            inputs=inputs,
        )
    return patched_frames


def _patch_chapter_active_range_for_cursor(
    inputs: dict[str, Any],
    *,
    cursor_key: str,
    start_value: Any,
    end_value: Any,
) -> dict[str, Any]:
    if str(cursor_key or "").strip() != "chapter_index" or start_value is None:
        return inputs
    patched = dict(inputs)
    start = int(_numeric_value(start_value, 0))
    end = int(_numeric_value(end_value, start))
    if end < start:
        end = start
    patched["active_chapter_start_index"] = start
    patched["active_chapter_end_index"] = end
    patched["active_chapter_count"] = max(0, end - start + 1)
    patched["active_chapter_range"] = f"{start:03d}-{end:03d}"
    return patched


def _loop_state_with_iteration_result(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    node_id: str,
    result_summary: dict[str, Any],
) -> dict[str, Any]:
    loop_state = dict(state.loop_state or {})
    frame = _active_loop_frame_for_node(graph_config=graph_config, state=state, node_id=node_id)
    if not frame:
        return loop_state
    frame_id = str(frame.get("frame_id") or frame.get("scope_id") or "").strip()
    iteration_id = str(frame.get("active_iteration_id") or "").strip()
    if not frame_id or not iteration_id:
        return loop_state
    iteration_results = {
        str(raw_frame_id): {
            str(raw_iteration_id): dict(raw_results)
            for raw_iteration_id, raw_results in dict(raw_frame_results or {}).items()
            if isinstance(raw_results, dict)
        }
        for raw_frame_id, raw_frame_results in dict(loop_state.get("iteration_results") or {}).items()
        if isinstance(raw_frame_results, dict)
    }
    frame_results = dict(iteration_results.get(frame_id) or {})
    current_results = dict(frame_results.get(iteration_id) or {})
    current_results[node_id] = dict(result_summary)
    frame_results[iteration_id] = current_results
    iteration_results[frame_id] = frame_results
    return {**loop_state, "iteration_results": iteration_results}


def _loop_state_without_frame_iteration_results(*, loop_state: dict[str, Any], frame_id: str) -> dict[str, Any]:
    if not frame_id:
        return loop_state
    iteration_results = {
        str(raw_frame_id): dict(raw_frame_results)
        for raw_frame_id, raw_frame_results in dict(loop_state.get("iteration_results") or {}).items()
        if isinstance(raw_frame_results, dict)
    }
    iteration_results.pop(frame_id, None)
    return {**loop_state, "iteration_results": iteration_results}


def _descendant_loop_frame_ids(*, frames: dict[str, dict[str, Any]], parent_frame_id: str) -> set[str]:
    descendants: set[str] = set()
    pending = [parent_frame_id]
    while pending:
        current = pending.pop(0)
        for frame_id, frame in frames.items():
            if frame_id in descendants:
                continue
            if _loop_parent_matches(dict(frame or {}), current):
                descendants.add(frame_id)
                pending.append(frame_id)
    return descendants


def _loop_parent_matches(frame: dict[str, Any], parent_frame_id: str) -> bool:
    parent_ref = str(dict(frame or {}).get("parent_scope_id") or "").strip()
    parent_id = str(parent_frame_id or "").strip()
    if not parent_ref or not parent_id:
        return False
    if parent_ref == parent_id:
        return True
    return _loop_scope_tail(parent_ref) == _loop_scope_tail(parent_id)


def _loop_scope_tail(value: str) -> str:
    text = str(value or "").strip()
    return text.rsplit("::", 1)[-1]


def _loop_state_without_descendant_iteration_results(
    *,
    loop_state: dict[str, Any],
    frames: dict[str, dict[str, Any]],
    parent_frame_id: str,
) -> dict[str, Any]:
    if not parent_frame_id:
        return loop_state
    descendants = _descendant_loop_frame_ids(frames=frames, parent_frame_id=parent_frame_id)
    if not descendants:
        return loop_state
    iteration_results = {
        str(raw_frame_id): dict(raw_frame_results)
        for raw_frame_id, raw_frame_results in dict(loop_state.get("iteration_results") or {}).items()
        if isinstance(raw_frame_results, dict) and str(raw_frame_id) not in descendants
    }
    return {**loop_state, "iteration_results": iteration_results}


def _cancel_descendant_loop_nodes_after_parent_exit(
    *,
    graph_config: GraphHarnessConfig,
    loop_state: dict[str, Any],
    parent_frame_id: str,
    node_states: dict[str, dict[str, Any]],
    edge_states: dict[str, dict[str, Any]],
    result_index: dict[str, dict[str, Any]],
    active_work_orders: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    frames = {key: dict(value) for key, value in dict(loop_state.get("frames") or {}).items() if isinstance(value, dict)}
    descendant_frame_ids = _descendant_loop_frame_ids(frames=frames, parent_frame_id=parent_frame_id)
    if not descendant_frame_ids:
        return node_states, edge_states, result_index, active_work_orders
    descendant_node_ids: set[str] = set()
    for frame_id in descendant_frame_ids:
        frame = dict(frames.get(frame_id) or {})
        descendant_node_ids.update(_loop_scope_node_ids(graph_config=graph_config, frame=frame))
    if not descendant_node_ids:
        return node_states, edge_states, result_index, active_work_orders
    now = time.time()
    patched_nodes = {key: dict(value) for key, value in node_states.items()}
    patched_edges = {key: dict(value) for key, value in edge_states.items()}
    patched_results = {key: dict(value) for key, value in result_index.items()}
    patched_active = dict(active_work_orders)
    for node_id in descendant_node_ids:
        payload = dict(patched_nodes.get(node_id) or {})
        if not payload:
            continue
        if str(payload.get("status") or "") in {"ready", "running", "blocked", "waiting_human_gate"}:
            payload["status"] = "pending"
        payload.pop("work_order_id", None)
        payload.pop("blocked_reason", None)
        payload["updated_at"] = now
        patched_nodes[node_id] = payload
        patched_active.pop(node_id, None)
        patched_results.pop(node_id, None)
    for edge in graph_config.edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source not in descendant_node_ids and target not in descendant_node_ids:
            continue
        edge_payload = dict(patched_edges.get(edge_id) or {})
        edge_payload.update(
            {
                "edge_id": edge_id,
                "source_node_id": source,
                "target_node_id": target,
                "status": "pending",
                "updated_at": now,
            }
        )
        for key in ("source_result_ref", "handoff_packet_id", "packet_refs", "latest_packet_id", "latest_packet_ref", "latest_packet"):
            edge_payload.pop(key, None)
        patched_edges[edge_id] = edge_payload
    return patched_nodes, patched_edges, patched_results, patched_active


def _active_loop_frame_for_node(*, graph_config: GraphHarnessConfig, state: GraphLoopState, node_id: str) -> dict[str, Any]:
    frames = [dict(item) for item in dict(dict(state.loop_state or {}).get("frames") or {}).values() if isinstance(item, dict)]
    for frame in frames:
        if str(frame.get("status") or "active") != "active":
            continue
        if node_id in _loop_scope_node_ids(graph_config=graph_config, frame=frame):
            return frame
    return {}


def _loop_iteration_id(*, frame: dict[str, Any], values: dict[str, Any]) -> str:
    template = str(frame.get("iteration_identity_template") or "").strip()
    if template:
        try:
            return template.format_map(_SafeFormatDict(values))
        except Exception:
            pass
    frame_id = str(frame.get("frame_id") or frame.get("scope_id") or "loop").strip()
    cursor = values.get("cursor")
    iteration_index = values.get("iteration_index")
    if cursor is not None and cursor != "":
        return f"{frame_id}:{cursor}"
    return f"{frame_id}:{iteration_index}"


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


def _ready_nodes(
    *,
    graph_config: GraphHarnessConfig,
    node_states: dict[str, dict[str, Any]],
    loop_state: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    return _STATE_MACHINE.ready_nodes(graph_config=graph_config, node_states=node_states, loop_state=loop_state)


def _blocked_nodes(
    *,
    graph_config: GraphHarnessConfig,
    node_states: dict[str, dict[str, Any]],
    loop_state: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    return _STATE_MACHINE.blocked_nodes(graph_config=graph_config, node_states=node_states, loop_state=loop_state)


def _node_is_resource(node: dict[str, Any]) -> bool:
    return str(node.get("node_class") or node.get("node_type") or "").strip() == "resource"


def _ready_rejected_revision_targets(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
) -> tuple[str, ...]:
    targets: list[str] = []
    for edge in graph_config.edges:
        edge_type = str(edge.get("edge_type") or "").strip()
        semantic_role = str(edge.get("semantic_role") or "").strip()
        if edge_type not in REVISION_EDGE_TYPES and semantic_role != "revision":
            continue
        edge_id = str(edge.get("edge_id") or "").strip()
        edge_state = dict(state.edge_states.get(edge_id) or {})
        if str(edge_state.get("status") or "") != "ready":
            continue
        source = str(edge.get("source_node_id") or "").strip()
        target = str(edge.get("target_node_id") or "").strip()
        if not source or not target:
            continue
        source_result = dict(state.result_index.get(source) or {})
        verdict = extract_review_verdict(str(source_result.get("handoff_summary") or ""))
        if review_verdict_is_rejected(verdict) and target not in targets:
            targets.append(target)
    return tuple(targets)


def _revision_reset_node_ids(
    *,
    graph_config: GraphHarnessConfig,
    start_node_ids: tuple[str, ...],
) -> tuple[str, ...]:
    reset: set[str] = set(str(item) for item in start_node_ids if str(item))
    queue = list(reset)
    while queue:
        source = queue.pop(0)
        for edge in graph_config.edges:
            if str(edge.get("source_node_id") or "") != source:
                continue
            target = str(edge.get("target_node_id") or "").strip()
            if not target or target in reset:
                continue
            node = _node_by_id(graph_config, target) or {}
            if _node_is_resource(node):
                continue
            reset.add(target)
            queue.append(target)
    ordered = [str(item) for item in start_node_ids if str(item)]
    seen = set(ordered)
    for node_id in reset:
        if node_id not in seen:
            ordered.append(node_id)
    return tuple(ordered)


def _state_after_revision_requeue(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    targets: tuple[str, ...],
    reset_node_ids: tuple[str, ...],
) -> GraphLoopState:
    node_states = {key: dict(value) for key, value in state.node_states.items()}
    edge_states = {key: dict(value) for key, value in state.edge_states.items()}
    result_index = {key: dict(value) for key, value in state.result_index.items()}
    active_work_orders = dict(state.active_work_orders)
    target_set = set(targets)
    reset_set = set(reset_node_ids)
    now = time.time()
    for node_id in reset_node_ids:
        node = dict(node_states.get(node_id) or {})
        if not node:
            continue
        node["status"] = "ready" if node_id in target_set else "pending"
        node["updated_at"] = now
        for key in ("blocked_reason", "result_ref", "work_order_id", "human_gate"):
            node.pop(key, None)
        node_states[node_id] = node
        result_index.pop(node_id, None)
        active_work_orders.pop(node_id, None)
    for edge in graph_config.edges:
        edge_id = str(edge.get("edge_id") or "")
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if not edge_id or (source not in reset_set and target not in reset_set):
            continue
        edge_state = dict(edge_states.get(edge_id) or {})
        edge_state.update(
            {
                "edge_id": edge_id,
                "source_node_id": source,
                "target_node_id": target,
                "status": "pending",
                "updated_at": now,
            }
        )
        for key in (
            "source_result_ref",
            "handoff_packet_id",
            "packet_refs",
            "latest_packet_id",
            "latest_packet_ref",
            "latest_packet",
        ):
            edge_state.pop(key, None)
        edge_states[edge_id] = edge_state
    return _replace_state(
        state,
        status="running",
        node_states=node_states,
        edge_states=edge_states,
        result_index=result_index,
        active_work_orders=active_work_orders,
        ready_node_ids=targets,
        running_node_ids=(),
        blocked_node_ids=(),
        terminal_reason="",
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
        status="running" if work_orders else state.status,
        node_states=node_states,
        active_work_orders=active,
        work_order_index=work_order_index,
        ready_node_ids=tuple(item for item in state.ready_node_ids if item not in active),
        running_node_ids=tuple(dict.fromkeys([*state.running_node_ids, *(item.node_id for item in work_orders)])),
    )


def _reset_outgoing_failed_edges(
    *,
    edge_states: dict[str, dict[str, Any]],
    source_node_id: str,
    updated_at: float,
) -> dict[str, dict[str, Any]]:
    next_edges = {key: dict(value) for key, value in edge_states.items()}
    for edge_id, edge_state in list(next_edges.items()):
        if str(edge_state.get("source_node_id") or "") != source_node_id:
            continue
        if str(edge_state.get("status") or "") != "source_failed":
            continue
        edge_state["status"] = "pending"
        edge_state["updated_at"] = updated_at
        edge_state.pop("packet_refs", None)
        edge_state.pop("latest_packet_id", None)
        edge_state.pop("latest_packet_ref", None)
        edge_state.pop("latest_packet", None)
        next_edges[edge_id] = edge_state
    return next_edges


def _node_status_from_result(result: NodeResultEnvelope) -> str:
    if result.status == "completed":
        return "completed"
    if result.status == "waiting_human_gate":
        return "waiting_human_gate"
    if result.status == "blocked":
        return "blocked"
    return "failed"


def _post_node_gate_wait_decision(
    *,
    graph_config: GraphHarnessConfig,
    result: NodeResultEnvelope,
    result_ref: str,
) -> dict[str, Any]:
    if result.status != "completed":
        return {}
    node = _node_by_id(graph_config, result.node_id) or {}
    policy = _post_node_gate_policy(node)
    if not policy:
        return {}
    mode = str(policy.get("mode") or "auto_continue").strip()
    if mode in {"", "auto_continue"}:
        return {}
    review_policy = str(policy.get("review_result_policy") or "").strip()
    verdict = _review_verdict(result)
    wait = mode in {"wait_human_after_node", "wait_human_after_review", "wait_human_after_review_any_result"}
    if review_policy == "wait_always":
        wait = True
    if review_policy == "wait_on_reject" and verdict in {"reject", "rejected", "revise", "failed", "not_passed"}:
        wait = True
    if not wait:
        return {}
    return {
        "gate_id": str(policy.get("gate_id") or f"gate:{result.node_id}:post_node"),
        "node_id": result.node_id,
        "source_result_id": result.result_id,
        "source_result_ref": result_ref,
        "mode": mode,
        "review_result_policy": review_policy,
        "reviewer_result": verdict,
        "allowed_human_actions": _string_values(policy.get("allowed_human_actions"))
        or ["approve_continue", "request_revision", "reroute_to_node", "abort_graph", "stop_and_checkpoint"],
        "checkpoint_policy": dict(policy.get("checkpoint_policy") or {}),
        "status": "waiting_human_gate",
        "authority": "harness.graph.post_node_gate_wait",
    }


def _post_node_gate_policy(node: dict[str, Any]) -> dict[str, Any]:
    gates = dict(node.get("gates") or {})
    metadata = dict(node.get("metadata") or {})
    return dict(gates.get("post_node_gate_policy") or metadata.get("post_node_gate_policy") or {})


def _review_verdict(result: NodeResultEnvelope) -> str:
    for source in (dict(result.decisions or {}), dict(result.outputs or {}), dict(result.diagnostics or {})):
        value = _verdict_from_payload(source)
        if value:
            return value
    return ""


def _verdict_from_payload(payload: dict[str, Any]) -> str:
    for key in ("review_verdict", "verdict", "decision", "status"):
        value = str(payload.get(key) or "").strip().lower()
        if value:
            return value
    for key in ("structured_output", "node_output", "review_result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            value = _verdict_from_payload(dict(nested))
            if value:
                return value
    return ""


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


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


def _state_identity_audit(state: GraphLoopState) -> dict[str, Any]:
    diagnostics = dict(state.diagnostics or {})
    return {
        "graph_harness_config_id": state.config_snapshot_id or state.config_id,
        "graph_harness_config_hash": state.config_snapshot_hash or state.config_hash,
        "graph_structure_hash": state.structure_hash or str(diagnostics.get("graph_structure_hash") or ""),
        "graph_structure_version": state.structure_version or str(diagnostics.get("graph_structure_version") or "graph_structure.v1"),
        "config_snapshot_id": state.config_snapshot_id or state.config_id,
        "config_snapshot_hash": state.config_snapshot_hash or state.config_hash,
        "runtime_settings_revision": int(diagnostics.get("runtime_settings_revision") or 0),
    }


def _replace_state(state: GraphLoopState, **patch: Any) -> GraphLoopState:
    payload = state.to_dict()
    payload.update(patch)
    return GraphLoopState.from_dict(payload)


def assert_graph_config_compatible_with_state(*, graph_config: GraphHarnessConfig, state: GraphLoopState) -> None:
    if graph_config.status != "published":
        raise ValueError("Graph operation requires a published GraphHarnessConfig")
    expected_hash = graph_config.expected_content_hash()
    if graph_config.content_hash and graph_config.content_hash != expected_hash:
        raise ValueError("GraphHarnessConfig config_hash mismatch (content_hash mismatch)")
    if state.graph_id != graph_config.graph_id:
        raise ValueError("GraphRun graph_id does not match GraphHarnessConfig")
    expected_structure_hash = graph_config.expected_structural_hash()
    state_structure_hash = _effective_structure_hash(graph_config=graph_config, state=state)
    if state_structure_hash != expected_structure_hash:
        raise ValueError("GraphRun structure_hash does not match GraphHarnessConfig")


def _effective_structure_hash(*, graph_config: GraphHarnessConfig, state: GraphLoopState) -> str:
    current = str(state.structure_hash or "").strip()
    if current:
        return current
    diagnostics = dict(state.diagnostics or {})
    projected = str(diagnostics.get("graph_structure_hash") or "").strip()
    if projected:
        return projected
    if state.config_hash == graph_config.content_hash:
        return graph_config.expected_structural_hash()
    return ""


def _advance_event_cursor(state: GraphLoopState) -> GraphLoopState:
    return _replace_state(state, event_cursor=state.event_cursor + 1)


def _node_by_id(graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any] | None:
    target = str(node_id or "")
    return next((dict(item) for item in graph_config.nodes if str(item.get("node_id") or "") == target), None)


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
