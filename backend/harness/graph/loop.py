from __future__ import annotations

import time
import re
import json
from dataclasses import dataclass
from pathlib import Path
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
from .edge_contracts import edge_contract_or_projection
from .flow_edges import build_outbound_flow_edges
from .language import REVISION_EDGE_TYPES
from .memory_context import GraphMemoryContextResolutionError
from .model_overrides import merge_runtime_settings
from .models import (
    GraphHarnessConfig,
    GraphLoopState,
    GraphNodeWorkOrder,
    GraphResultEnvelope,
    GraphRuntimeEnvelope,
    GraphTransitionInput,
    NodeResultEnvelope,
    safe_id,
    stable_hash,
)
from .runtime_objects import (
    load_node_result,
    node_result_summary,
    store_node_result,
    store_work_order,
    work_order_summary,
)
from .scheduler_view import build_scheduler_view
from .state_machine import GraphStateMachine
from .transition_processor import (
    GraphTransitionProcessor,
    apply_transition_plan_to_edge_states,
)


_STATE_MACHINE = GraphStateMachine()
_MAX_RESULT_HISTORY_PER_NODE = 24
_MAX_WORK_ORDER_INDEX_ENTRIES = 96
_BULKY_DIAGNOSTIC_KEYS = ("contract_index", "static_topology_view")


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
        ready_node_ids = _ready_nodes(graph_config=graph_config, node_states=node_states, edge_states=edge_states)
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
                "static_topology_view_summary": _payload_summary(envelope.static_topology_view or {}),
                "contract_index_summary": _payload_summary(envelope.contract_index or {}),
                "state_machine_spec": dict(envelope.state_machine_spec or {}),
                "loop_control_spec": dict(envelope.loop_control_spec or {}),
                "source": "harness.graph_loop.initialize",
                "scheduler": scheduler_view.diagnostics,
            },
        )
        work_orders: tuple[GraphNodeWorkOrder, ...] = ()
        if dispatch_ready and not terminal_status:
            state, work_orders = self._dispatch_ready_with_state(graph_config=graph_config, state=state)
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
        allowed_ready = tuple(
            self._state_machine.ready_nodes(
                graph_config=graph_config,
                node_states={key: dict(value) for key, value in state.node_states.items()},
                edge_states={key: dict(value) for key, value in state.edge_states.items()},
                loop_state=state.loop_state,
            )
        )
        selected = [
            node_id
            for node_id in allowed_ready
            if node_id not in state.active_work_orders
        ][: max(1, limit)]
        orders: list[GraphNodeWorkOrder] = []
        for node_id in selected:
            node = _node_by_id(graph_config, node_id)
            if node is None:
                continue
            orders.append(self._context_materializer.build_work_order(graph_config=graph_config, state=state, node=node))
        return tuple(orders)

    def _dispatch_ready_with_state(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        max_requests: int | None = None,
    ) -> tuple[GraphLoopState, tuple[GraphNodeWorkOrder, ...]]:
        try:
            work_orders = self.dispatch_ready(
                graph_config=graph_config,
                state=state,
                max_requests=max_requests,
            )
            next_state = _state_with_work_orders(state, work_orders, services=self._services) if work_orders else state
            return next_state, work_orders
        except GraphMemoryContextResolutionError as exc:
            node_id = exc.node_id
            if not node_id:
                raise
            blocked = _dispatch_block_payload(node_id=node_id, error=exc)
            return (
                _state_after_dispatch_block(
                    graph_config=graph_config,
                    state=state,
                    node_id=node_id,
                    block=blocked,
                    state_machine=self._state_machine,
                ),
                (),
            )

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
        next_state, work_orders = self._dispatch_ready_with_state(
            graph_config=graph_config,
            state=state,
            max_requests=max_requests,
        )
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
            else _edge_states_after_transition(
                graph_config=graph_config,
                state=state,
                trigger_type="node_result",
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
        route_decision: dict[str, Any] = {}
        revision_route_decision: dict[str, Any] = {}
        initial_inputs = dict(next_state.initial_inputs or {})
        revision_targets = (
            ()
            if bool(initial_inputs.get("revision_active")) and initial_inputs.get("revision_queue_chapter_indexes")
            else _ready_rejected_revision_targets(
                graph_config=graph_config,
                state=next_state,
                source_node_id=envelope.node_id,
                source_result_ref=result_ref,
            )
        )
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
        else:
            route_decision = _evaluate_loop_route(graph_config=graph_config, state=next_state, result=envelope, services=self._services)
            if route_decision:
                next_state = _state_after_loop_route(graph_config=graph_config, state=next_state, decision=route_decision)
                node_states = {key: dict(value) for key, value in next_state.node_states.items()}
                edge_states = {key: dict(value) for key, value in next_state.edge_states.items()}
                result_index = {key: dict(value) for key, value in next_state.result_index.items()}
                active_work_orders = dict(next_state.active_work_orders)
        quality_retry_decision = _quality_same_node_retry_decision(graph_config=graph_config, state=next_state, result=envelope)
        if quality_retry_decision:
            next_state = _state_after_quality_same_node_retry(
                graph_config=graph_config,
                state=next_state,
                decision=quality_retry_decision,
            )
            node_states = {key: dict(value) for key, value in next_state.node_states.items()}
            edge_states = {key: dict(value) for key, value in next_state.edge_states.items()}
            result_index = {key: dict(value) for key, value in next_state.result_index.items()}
            active_work_orders = dict(next_state.active_work_orders)
        status_snapshot = self._state_machine.status_snapshot(
            graph_config=graph_config,
            node_states=node_states,
            edge_states=edge_states,
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
        if graph_result is not None or status_snapshot.status in {"blocked", "waiting_human_gate"}:
            work_orders = ()
        else:
            next_state, work_orders = self._dispatch_ready_with_state(graph_config=graph_config, state=next_state)
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
                    "quality_retry_decision": quality_retry_decision,
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
            preserve_ready_revision_edges=False,
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
        assert_graph_config_compatible_with_state(graph_config=graph_config, state=state)
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
            edge_states = _edge_states_after_transition(
                graph_config=graph_config,
                state=state,
                trigger_type="node_result",
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
            route_edge = _human_gate_route_edge(
                graph_config=graph_config,
                source_node_id=node_id,
                target_node_id=target,
                action=action,
            )
            if route_edge is None:
                node_state["status"] = "blocked"
                node_state["blocked_reason"] = "route_edge_not_declared"
                node_states[node_id] = node_state
                status = "blocked"
                terminal_reason = f"route_edge_not_declared:{node_id}->{target}"
            else:
                target_state["status"] = "pending"
                target_state["updated_at"] = time.time()
                target_state["human_gate_route_from"] = node_id
                for key in ("result_ref", "work_order_id", "human_gate", "blocked_reason"):
                    target_state.pop(key, None)
                node_states[target] = target_state
                edge_states = _edge_states_after_transition(
                    graph_config=graph_config,
                    state=state,
                    trigger_type="human_gate_decision",
                    result=result,
                    result_ref=result_ref,
                    services=self._services,
                    edge_id=str(route_edge.get("edge_id") or ""),
                    decision_ref=f"human_gate_decision:{node_id}:{action}:{target}",
                )
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
        ready = _ready_nodes(graph_config=graph_config, node_states=node_states, edge_states=edge_states, loop_state=state.loop_state)
        next_state = _replace_state(
            next_state,
            ready_node_ids=tuple([] if graph_result else ready),
            running_node_ids=(),
            completed_node_ids=tuple(node for node, payload in node_states.items() if str(payload.get("status") or "") == "completed"),
            failed_node_ids=tuple(node for node, payload in node_states.items() if str(payload.get("status") or "") == "failed"),
            blocked_node_ids=tuple(node for node, payload in node_states.items() if str(payload.get("status") or "") in {"blocked", "waiting_human_gate"}),
        )
        if graph_result is not None or status in {"blocked", "waiting_human_gate"}:
            work_orders = ()
        else:
            next_state, work_orders = self._dispatch_ready_with_state(
                graph_config=graph_config,
                state=next_state,
                max_requests=max_requests,
            )
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

    def apply_human_edge_decision_and_checkpoint(
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
        assert_graph_config_compatible_with_state(graph_config=graph_config, state=state)
        payload = dict(decision or {})
        action = str(payload.get("decision") or "").strip()
        if action not in {"pass", "revise", "replace"}:
            raise ValueError(f"unsupported HumanEdgeDecision action: {action}")
        edge = _edge_by_id(graph_config, str(payload.get("edge_id") or ""))
        if edge is None:
            raise ValueError(f"HumanEdgeDecision edge not found: {payload.get('edge_id')}")
        edge_id = str(edge.get("edge_id") or "")
        source_node_id = str(edge.get("source_node_id") or "")
        target_node_id = str(edge.get("target_node_id") or "")
        if str(payload.get("source_node_id") or source_node_id) != source_node_id:
            raise ValueError("HumanEdgeDecision source_node_id does not match edge")
        if str(payload.get("target_node_id") or target_node_id) != target_node_id:
            raise ValueError("HumanEdgeDecision target_node_id does not match edge")
        _assert_human_edge_decision_allowed(graph_config=graph_config, edge=edge, action=action)
        if source_node_id in dict(state.active_work_orders or {}):
            raise ValueError("HumanEdgeDecision source node is currently running")
        if target_node_id in dict(state.active_work_orders or {}):
            raise ValueError("HumanEdgeDecision target node is currently running")

        result_ref = ""
        result: NodeResultEnvelope | None = None
        node_states = {key: dict(value) for key, value in state.node_states.items()}
        edge_states = {key: dict(value) for key, value in state.edge_states.items()}
        result_index = {key: dict(value) for key, value in state.result_index.items()}
        result_history = {key: tuple(dict(item) for item in value) for key, value in state.result_history.items()}
        active_work_orders = dict(state.active_work_orders)
        now = time.time()

        source_state = dict(node_states.get(source_node_id) or {})
        if action == "pass":
            result_ref = _source_result_ref_for_human_decision(source_state)
            result = load_node_result(self._services, {"result_ref": result_ref}) if result_ref else None
            if result is None:
                raise ValueError("HumanEdgeDecision pass requires an existing source result")
            source_state["status"] = "completed"
            source_state["updated_at"] = now
            source_state["human_edge_decision"] = _human_edge_decision_state(payload)
            source_state.pop("human_gate", None)
            node_states[source_node_id] = source_state
            edge_states = _edge_states_after_transition(
                graph_config=graph_config,
                state=state,
                trigger_type="human_edge_decision",
                result=result,
                result_ref=result_ref,
                services=self._services,
                edge_id=edge_id,
            )
            if edge_id in edge_states:
                edge_states[edge_id]["human_edge_decision"] = _human_edge_decision_state(payload)
            next_state = _replace_state(
                state,
                node_states=node_states,
                edge_states=edge_states,
                active_work_orders=active_work_orders,
            )
        else:
            result = _human_edge_decision_result(
                graph_config=graph_config,
                state=state,
                edge=edge,
                decision=payload,
                action=action,
            )
            result_ref = store_node_result(self._services, result)
            result_summary = _node_result_summary(result, result_ref=result_ref)
            source_state["status"] = "completed"
            source_state["result_ref"] = result_ref
            source_state["updated_at"] = now
            source_state["human_edge_decision"] = _human_edge_decision_state(payload)
            source_state.pop("human_gate", None)
            node_states[source_node_id] = source_state
            result_index[source_node_id] = result_summary
            result_history = _result_history_with_result(state=state, result=result, result_ref=result_ref)
            next_state = _replace_state(
                state,
                node_states=node_states,
                result_index=result_index,
                result_history=result_history,
                active_work_orders=active_work_orders,
            )
            if action == "revise":
                reset_node_ids = _revision_reset_node_ids(
                    graph_config=graph_config,
                    start_node_ids=(target_node_id,),
                )
                next_state = _state_after_revision_requeue(
                    graph_config=graph_config,
                    state=next_state,
                    targets=(target_node_id,),
                    reset_node_ids=reset_node_ids,
                )
            edge_states = _edge_states_after_transition(
                graph_config=graph_config,
                state=next_state,
                trigger_type="human_edge_decision",
                result=result,
                result_ref=result_ref,
                services=self._services,
                edge_id=edge_id,
            )
            if edge_id in edge_states:
                edge_states[edge_id]["human_edge_decision"] = _human_edge_decision_state(payload)
            next_state = _replace_state(next_state, edge_states=edge_states)

        status_snapshot = self._state_machine.status_snapshot(
            graph_config=graph_config,
            node_states={key: dict(value) for key, value in next_state.node_states.items()},
            edge_states={key: dict(value) for key, value in next_state.edge_states.items()},
            active_work_orders=dict(next_state.active_work_orders),
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
        if graph_result is not None or status_snapshot.status in {"blocked", "waiting_human_gate"}:
            work_orders = ()
        else:
            next_state, work_orders = self._dispatch_ready_with_state(
                graph_config=graph_config,
                state=next_state,
                max_requests=max_requests,
            )
        next_state = _advance_event_cursor(next_state)
        checkpoint = self._write_state(next_state, pending_work_orders=work_orders)
        packet_ref = str(dict(next_state.edge_states.get(edge_id) or {}).get("latest_packet_ref") or "")
        events = [
            self._append_event(
                next_state.task_run_id,
                "graph_human_edge_decision_applied",
                payload={
                    "graph_run_id": next_state.graph_run_id,
                    "decision_id": str(payload.get("decision_id") or ""),
                    "decision": action,
                    "edge_id": edge_id,
                    "source_node_id": source_node_id,
                    "target_node_id": target_node_id,
                    "packet_ref": packet_ref,
                    "node_result": _node_result_summary(result, result_ref=result_ref) if result is not None else {},
                    "graph_loop_state": _loop_state_summary(next_state),
                    "node_work_orders": [_work_order_summary(item) for item in work_orders],
                    "graph_result": _graph_result_summary(graph_result),
                    "authority": "harness.graph.human_edge_decision_apply_event",
                },
                refs={
                    "graph_run_ref": next_state.graph_run_id,
                    "edge_ref": edge_id,
                    "node_ref": source_node_id,
                    "human_edge_decision_ref": str(payload.get("decision_id") or ""),
                },
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
        checkpoint_state = _compact_state_for_checkpoint(state)
        self._state_machine.validate(checkpoint_state)
        checkpoint = self._checkpoint_store.put_checkpoint(
            state=checkpoint_state,
            metadata={"created_at": time.time(), "authority": "harness.graph_loop_checkpoint"},
        )
        if pending_work_orders:
            self._checkpoint_store.put_pending_writes(
                graph_run_id=checkpoint_state.graph_run_id,
                task_id=f"dispatch:{checkpoint_state.graph_run_id}:{int(time.time() * 1000)}",
                writes=tuple(
                    (
                        "active_work_order",
                        dict(checkpoint_state.work_order_index.get(item.work_order_id) or _work_order_summary(item)),
                    )
                    for item in pending_work_orders
                ),
            )
            latest = self._checkpoint_store.get_latest_checkpoint(checkpoint_state.graph_run_id)
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
        graph_status = "completed" if graph_result is not None and graph_result.status == "completed" else ("failed" if graph_result is not None else state.status)
        task_run_status = _formal_task_run_status(graph_status)
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
                        "status": task_run_status,
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
                    "status": graph_status,
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
    for frame in graph_config.loop_frames:
        inputs.update(dict(dict(frame).get("initial_inputs") or {}))
    inputs.update(dict(envelope.initial_inputs or {}))
    return _apply_derived_fields(inputs, _loop_derived_fields(graph_config))


def _loop_derived_fields(graph_config: GraphHarnessConfig) -> list[Any]:
    derived_fields: list[Any] = []
    for frame in graph_config.loop_frames:
        derived_fields.extend(list(dict(frame).get("derived_fields") or []))
    return derived_fields


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
    hybrid = _evaluate_metric_target_route_from_progress_receipt(
        graph_config=graph_config,
        state=state,
        result=result,
        node=node,
        node_loop=node_loop,
        route_policy=route_policy,
        services=services,
    )
    if hybrid is not None:
        return hybrid
    return _evaluate_metric_target_route(
        graph_config=graph_config,
        state=state,
        result=result,
        node_loop=node_loop,
        route_policy=route_policy,
    )


def _evaluate_metric_target_route(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    node_loop: dict[str, Any],
    route_policy: dict[str, Any],
) -> dict[str, Any]:
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
    patched_inputs = _apply_route_metric_counters(
        initial_inputs=dict(state.initial_inputs or {}),
        route_policy=route_policy,
        metric=metric,
    )
    current_key = str(route_policy.get("current_key") or "").strip()
    target_key = str(route_policy.get("target_key") or "").strip()
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


def _evaluate_metric_target_route_from_progress_receipt(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
    node: dict[str, Any],
    node_loop: dict[str, Any],
    route_policy: dict[str, Any],
    services: Any | None,
) -> dict[str, Any] | None:
    if not _route_uses_chapter_progress_receipt(state=state, route_policy=route_policy):
        return None
    scope_id = str(route_policy.get("scope_id") or node_loop.get("scope_id") or "").strip()
    frame = _loop_frame_for_route(graph_config=graph_config, scope_id=scope_id, node_id=result.node_id, route_policy=route_policy)
    try:
        receipt = first_chapter_progress_receipt(
            _progress_receipt_sources(
                graph_config=graph_config,
                state=state,
                result=result,
                route_policy=route_policy,
                services=services,
            ),
            key="chapter_progress_receipt",
            initial_inputs=dict(state.initial_inputs or {}),
        )
    except ChapterProgressReceiptError:
        return None

    metric = _chapter_progress_receipt_metric(
        receipt=receipt,
        route_policy=route_policy,
        state=state,
        result=result,
    )
    patched_inputs = _apply_route_metric_counters(
        initial_inputs=dict(state.initial_inputs or {}),
        route_policy=route_policy,
        metric=metric,
    )
    patched_inputs = _apply_chapter_progress_receipt_inputs(
        initial_inputs=patched_inputs,
        receipt=receipt,
    )
    patched_inputs = _apply_patch_rules(patched_inputs, list(route_policy.get("patch_rules") or []))

    current_key = str(route_policy.get("current_key") or "group_current_measure").strip()
    target_key = str(route_policy.get("target_key") or "group_target_measure").strip()
    current_value = _numeric_value(patched_inputs.get(current_key), 0) if current_key else 0
    target_value = _numeric_value(patched_inputs.get(target_key), 0) if target_key else 0
    receipt_complete = bool(receipt.get("volume_complete"))
    action = "exit" if receipt_complete or (target_key and current_value >= target_value) else "continue"
    if action == "continue" and _chapter_batch_cursor_advanced(
        previous_inputs=dict(state.initial_inputs or {}),
        next_inputs=patched_inputs,
    ):
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
        "reason": "volume_complete" if receipt_complete else ("target_reached" if action == "exit" else "target_not_reached"),
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

    committed_words = _chapter_progress_receipt_metric(
        receipt=receipt,
        route_policy=route_policy,
        state=state,
        result=result,
    )
    patched_inputs = _apply_route_metric_counters(
        initial_inputs=dict(state.initial_inputs or {}),
        route_policy=route_policy,
        metric=committed_words,
    )
    patched_inputs = _apply_chapter_progress_receipt_inputs(
        initial_inputs=patched_inputs,
        receipt=receipt,
    )
    patched_inputs = _apply_patch_rules(patched_inputs, list(route_policy.get("patch_rules") or []))
    patched_inputs.setdefault(
        "active_chapter_range",
        f"{int(_numeric_value(patched_inputs.get('active_chapter_start_index'), _numeric_value(receipt.get('next_chapter_index'), 1))):03d}-{int(_numeric_value(patched_inputs.get('active_chapter_end_index'), _numeric_value(receipt.get('next_chapter_index'), 1))):03d}",
    )

    current_key = str(route_policy.get("current_key") or "group_current_measure").strip()
    target_key = str(route_policy.get("target_key") or "group_target_measure").strip()
    current_value = _numeric_value(patched_inputs.get(current_key), 0) if current_key else 0
    target_value = _numeric_value(patched_inputs.get(target_key), 0) if target_key else 0
    receipt_complete = bool(receipt.get("volume_complete"))
    action = "exit" if receipt_complete or (target_key and current_value >= target_value) else "continue"
    if action == "continue" and _chapter_batch_cursor_advanced(
        previous_inputs=dict(state.initial_inputs or {}),
        next_inputs=patched_inputs,
    ):
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


def _route_uses_chapter_progress_receipt(*, state: GraphLoopState, route_policy: dict[str, Any]) -> bool:
    return bool(
        any(
            key in dict(state.initial_inputs or {})
            for key in ("batch_start_index", "batch_end_index", "chapter_index", "units_per_batch")
        )
        and str(route_policy.get("current_key") or "").strip() in {"", "group_current_measure"}
    )


def _chapter_progress_receipt_metric(
    *,
    receipt: dict[str, Any],
    route_policy: dict[str, Any],
    state: GraphLoopState,
    result: NodeResultEnvelope,
) -> float | int:
    metric = _numeric_value(receipt.get("committed_words"), None)
    if metric is not None:
        return metric
    fallback = _route_metric(route_policy=route_policy, state=state, result=result)
    return _numeric_value(fallback, 0)


def _apply_route_metric_counters(
    *,
    initial_inputs: dict[str, Any],
    route_policy: dict[str, Any],
    metric: float | int,
) -> dict[str, Any]:
    patched_inputs = dict(initial_inputs or {})
    current_key = str(route_policy.get("current_key") or "").strip()
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
    return patched_inputs


def _apply_chapter_progress_receipt_inputs(
    *,
    initial_inputs: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    patched_inputs = dict(initial_inputs or {})
    next_chapter_index = int(_numeric_value(receipt.get("next_chapter_index"), _numeric_value(patched_inputs.get("chapter_index"), 1)))
    batch_complete = bool(receipt.get("batch_complete"))
    patched_inputs["chapter_index"] = next_chapter_index
    patched_inputs["active_chapter_start_index"] = next_chapter_index
    patched_inputs["active_chapter_end_index"] = int(
        _numeric_value(receipt.get("batch_end_index"), _numeric_value(patched_inputs.get("batch_end_index"), next_chapter_index))
    )
    if batch_complete:
        patched_inputs["batch_start_index"] = next_chapter_index
        patched_inputs["batch_end_index"] = next_chapter_index + max(1, int(_numeric_value(patched_inputs.get("units_per_batch"), 1))) - 1
        patched_inputs["active_chapter_end_index"] = patched_inputs["batch_end_index"]
    else:
        patched_inputs["batch_start_index"] = int(
            _numeric_value(receipt.get("batch_start_index"), _numeric_value(patched_inputs.get("batch_start_index"), next_chapter_index))
        )
        patched_inputs["batch_end_index"] = int(
            _numeric_value(
                receipt.get("batch_end_index"),
                _numeric_value(patched_inputs.get("batch_end_index"), patched_inputs["active_chapter_end_index"]),
            )
        )
    patched_inputs["active_chapter_count"] = max(
        0,
        int(_numeric_value(patched_inputs.get("active_chapter_end_index"), next_chapter_index))
        - int(_numeric_value(patched_inputs.get("active_chapter_start_index"), next_chapter_index))
        + 1,
    )
    patched_inputs["active_chapter_range"] = (
        f"{int(_numeric_value(patched_inputs.get('active_chapter_start_index'), next_chapter_index)):03d}-"
        f"{int(_numeric_value(patched_inputs.get('active_chapter_end_index'), next_chapter_index)):03d}"
    )
    return patched_inputs


def _chapter_batch_cursor_advanced(*, previous_inputs: dict[str, Any], next_inputs: dict[str, Any]) -> bool:
    previous = _numeric_value(previous_inputs.get("batch_start_index"), None)
    current = _numeric_value(next_inputs.get("batch_start_index"), None)
    if previous is None or current is None:
        return False
    return int(current) != int(previous)


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
    revision_route = _revision_queue_route_patch_after_unit_acceptance(
        initial_inputs=dict(state.initial_inputs or {}),
        receipt=receipt,
    )
    if revision_route:
        patched_inputs.update(dict(revision_route.get("initial_inputs_patch") or {}))
    target_key = str(route_policy.get("target_key") or "").strip()
    current_value = _numeric_value(patched_inputs.get(current_key), 0) if current_key else 0
    target_value = _numeric_value(patched_inputs.get(target_key), 0) if target_key else 0
    action = str(revision_route.get("action") or "") if revision_route else ""
    if not action:
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
    if revision_route:
        patched_inputs.update(dict(revision_route.get("initial_inputs_patch") or {}))
    patched_inputs = _apply_derived_fields(patched_inputs, list(route_policy.get("derived_fields") or []))
    continue_node_id = str(route_policy.get("continue_node_id") or frame.get("continue_node_id") or frame.get("entry_node_id") or "").strip()
    exit_node_id = str(route_policy.get("exit_node_id") or frame.get("exit_node_id") or "").strip()
    return {
        "authority": "harness.graph.loop_route_decision",
        "action": action,
        "reason": str(revision_route.get("reason") or "") if revision_route else ("receipt_complete" if receipt_complete else ("target_reached" if action == "exit" else "target_not_reached")),
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
        "revision_route": revision_route,
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
            if target in reset_edge_node_ids and source not in reset_edge_node_ids:
                continue
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


def _revision_queue_route_patch_after_unit_acceptance(
    *,
    initial_inputs: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    queue = _revision_queue_chapter_indexes(initial_inputs.get("revision_queue_chapter_indexes"))
    if not queue:
        return {}
    current = int(_numeric_value(initial_inputs.get("chapter_index"), queue[0]) or queue[0])
    if current not in queue:
        return {}
    committed = [int(item) for item in list(receipt.get("committed_chapter_indexes") or []) if _numeric_value(item, None) is not None]
    if committed and current not in committed:
        return {}
    position = queue.index(current)
    next_position = position + 1
    patch = dict(initial_inputs)
    patch["revision_queue_chapter_indexes"] = queue
    patch["revision_queue_position"] = next_position
    patch["revision_active"] = next_position < len(queue)
    if next_position < len(queue):
        next_chapter = queue[next_position]
        patch.update(_single_chapter_cursor_patch(next_chapter))
        patch["revision_current_chapter_index"] = next_chapter
        patch.pop("quality_gate_feedback", None)
        patch.pop("previous_chapter_draft_ref", None)
        plan_text = str(patch.get("revision_plan_text") or "").strip()
        if plan_text:
            patch["chapter_revision_requirements"] = _revision_requirements_for_chapter(plan_text, next_chapter)
        action = "continue"
        reason = "revision_queue_next_chapter"
    else:
        patch["revision_current_chapter_index"] = current
        patch["revision_active"] = False
        for key in (
            "revision_queue_chapter_indexes",
            "revision_queue_position",
            "revision_current_chapter_index",
            "revision_execution_range",
            "revision_plan_text",
            "chapter_revision_requirements",
            "quality_gate_feedback",
            "previous_chapter_draft_ref",
            "previous_chapter_review_ref",
        ):
            patch.pop(key, None)
        action = "exit"
        reason = "revision_queue_complete"
    return {
        "authority": "harness.graph.revision_queue_route",
        "action": action,
        "reason": reason,
        "current_chapter_index": current,
        "next_chapter_index": patch.get("chapter_index"),
        "revision_queue_chapter_indexes": queue,
        "revision_queue_position": next_position,
        "initial_inputs_patch": patch,
    }


def _revision_queue_chapter_indexes(value: Any) -> list[int]:
    raw_items = value if isinstance(value, list) else []
    indexes: list[int] = []
    for item in raw_items:
        number = _numeric_value(item, None)
        if number is None:
            continue
        chapter = int(number)
        if chapter > 0 and chapter not in indexes:
            indexes.append(chapter)
    return indexes


def _single_chapter_cursor_patch(chapter: int) -> dict[str, Any]:
    return {
        "chapter_index": chapter,
        "chapter_index_padded": f"{chapter:03d}",
        "chapter_file_prefix": f"chapter_{chapter:03d}",
        "active_chapter_start_index": chapter,
        "active_chapter_end_index": chapter,
        "active_chapter_count": 1,
        "active_chapter_range": f"{chapter:03d}-{chapter:03d}",
    }


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


def _loop_state_without_revision_iteration_results(
    *,
    loop_state: dict[str, Any],
    target_node_ids: tuple[str, ...],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    target_set = {str(item) for item in target_node_ids if str(item)}
    if not target_set:
        return loop_state
    frames = {
        str(frame_id): dict(frame)
        for frame_id, frame in dict(loop_state.get("frames") or {}).items()
        if isinstance(frame, dict)
    }
    if not frames:
        return loop_state
    queue_indexes = _revision_queue_chapter_indexes(initial_inputs.get("revision_queue_chapter_indexes"))
    start = min(queue_indexes) if queue_indexes else _numeric_value(initial_inputs.get("active_chapter_start_index"), None)
    if start is None:
        start = _numeric_value(initial_inputs.get("chapter_index"), None)
    end = max(queue_indexes) if queue_indexes else _numeric_value(initial_inputs.get("active_chapter_end_index"), start)
    if start is None:
        return loop_state
    start_int = int(start)
    end_int = int(end if end is not None else start)
    if end_int < start_int:
        start_int, end_int = end_int, start_int
    batch_start = _numeric_value(initial_inputs.get("batch_start_index"), None)
    batch_end = _numeric_value(initial_inputs.get("batch_end_index"), batch_start)
    batch_start_int = int(batch_start) if batch_start is not None else None
    batch_end_int = int(batch_end) if batch_end is not None else batch_start_int
    if batch_start_int is not None and batch_end_int is not None and batch_end_int < batch_start_int:
        batch_start_int, batch_end_int = batch_end_int, batch_start_int
    iteration_results = {
        str(raw_frame_id): {
            str(raw_iteration_id): dict(raw_results)
            for raw_iteration_id, raw_results in dict(raw_frame_results or {}).items()
            if isinstance(raw_results, dict)
        }
        for raw_frame_id, raw_frame_results in dict(loop_state.get("iteration_results") or {}).items()
        if isinstance(raw_frame_results, dict)
    }
    changed = False
    for frame_id, frame in frames.items():
        scope_nodes = {str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)}
        if not scope_nodes.intersection(target_set):
            continue
        frame_results = dict(iteration_results.get(frame_id) or {})
        if not frame_results:
            continue
        template = str(frame.get("iteration_identity_template") or "").strip()
        removal_ids = _revision_iteration_ids_for_range(template=template, start=start_int, end=end_int)
        if _revision_overlaps_frame_range(
            frame=frame,
            initial_inputs=initial_inputs,
            affected_start=start_int,
            affected_end=end_int,
            batch_start=batch_start_int,
            batch_end=batch_end_int,
        ):
            active_iteration_id = str(frame.get("active_iteration_id") or "").strip()
            if active_iteration_id:
                removal_ids.add(active_iteration_id)
            removal_ids.update(_revision_iteration_ids_for_frame_values(template=template, values=initial_inputs))
        next_frame_results = {
            iteration_id: results
            for iteration_id, results in frame_results.items()
            if iteration_id not in removal_ids and not _iteration_id_in_range(iteration_id, start_int, end_int)
        }
        if len(next_frame_results) == len(frame_results):
            continue
        changed = True
        if next_frame_results:
            iteration_results[frame_id] = next_frame_results
        else:
            iteration_results.pop(frame_id, None)
    if not changed:
        return loop_state
    return {**loop_state, "iteration_results": iteration_results}


def _loop_state_with_revision_frames_active(
    *,
    graph_config: GraphHarnessConfig,
    loop_state: dict[str, Any],
    target_node_ids: tuple[str, ...],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    target_set = {str(item) for item in target_node_ids if str(item)}
    if not target_set:
        return loop_state
    frames = {
        str(frame_id): dict(frame)
        for frame_id, frame in dict(loop_state.get("frames") or {}).items()
        if isinstance(frame, dict)
    }
    changed = False
    now = time.time()
    for frame_id, frame in list(frames.items()):
        scope_nodes = {str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)}
        if not scope_nodes.intersection(target_set):
            continue
        cursor_key = str(frame.get("cursor_key") or "").strip()
        start_key = str(frame.get("start_key") or "").strip()
        end_key = str(frame.get("end_key") or "").strip()
        cursor_value = _numeric_value(initial_inputs.get(cursor_key), frame.get("cursor")) if cursor_key else frame.get("cursor")
        start_value = _numeric_value(initial_inputs.get(start_key), frame.get("start")) if start_key else frame.get("start")
        end_value = _numeric_value(initial_inputs.get(end_key), frame.get("end")) if end_key else frame.get("end")
        iteration_index = int(_numeric_value(frame.get("iteration_index"), 0) or 0)
        frame["status"] = "active"
        frame["cursor"] = cursor_value
        frame["start"] = start_value
        frame["end"] = end_value
        frame["active_iteration_id"] = _loop_iteration_id(
            frame=frame,
            values={**initial_inputs, **frame, "cursor": cursor_value, "iteration_index": iteration_index},
        )
        frame["updated_at"] = now
        frames[frame_id] = frame
        changed = True
    if not changed:
        return loop_state
    return {**loop_state, "frames": frames}


def _loop_state_with_requeue_exit_frames(
    *,
    loop_state: dict[str, Any],
    target_node_ids: tuple[str, ...],
) -> dict[str, Any]:
    target_set = {str(item) for item in target_node_ids if str(item)}
    if not target_set:
        return loop_state
    frames = {
        str(frame_id): dict(frame)
        for frame_id, frame in dict(loop_state.get("frames") or {}).items()
        if isinstance(frame, dict)
    }
    changed = False
    now = time.time()
    for frame_id, frame in list(frames.items()):
        exit_node_id = str(frame.get("exit_node_id") or "").strip()
        if not exit_node_id or exit_node_id not in target_set:
            continue
        frame["status"] = "exited"
        frame["updated_at"] = now
        frames[frame_id] = frame
        changed = True
    if not changed:
        return loop_state
    return {**loop_state, "frames": frames}


def _revision_iteration_ids_for_range(*, template: str, start: int, end: int) -> set[str]:
    if not template:
        return set()
    values: set[str] = set()
    for index in range(start, end + 1):
        try:
            values.add(str(template.format_map(_SafeFormatDict({"chapter_index": index, "cursor": index, "iteration_index": index}))))
        except Exception:
            continue
    return values


def _revision_iteration_ids_for_frame_values(*, template: str, values: dict[str, Any]) -> set[str]:
    if not template:
        return set()
    candidates: set[str] = set()
    base_values = dict(values or {})
    for cursor_key in ("chapter_index", "batch_start_index", "volume_index"):
        if cursor_key in base_values:
            base_values.setdefault("cursor", base_values.get(cursor_key))
            break
    try:
        candidates.add(str(template.format_map(_SafeFormatDict(base_values))))
    except Exception:
        pass
    return candidates


def _revision_overlaps_frame_range(
    *,
    frame: dict[str, Any],
    initial_inputs: dict[str, Any],
    affected_start: int,
    affected_end: int,
    batch_start: int | None,
    batch_end: int | None,
) -> bool:
    start_key = str(frame.get("start_key") or "").strip()
    end_key = str(frame.get("end_key") or "").strip()
    if start_key == "batch_start_index" and end_key == "batch_end_index" and batch_start is not None and batch_end is not None:
        return affected_start <= batch_end and affected_end >= batch_start
    frame_start = _numeric_value(initial_inputs.get(start_key), None) if start_key else None
    frame_end = _numeric_value(initial_inputs.get(end_key), frame_start) if end_key else frame_start
    if frame_start is None or frame_end is None:
        return False
    frame_start_int = int(frame_start)
    frame_end_int = int(frame_end)
    if frame_end_int < frame_start_int:
        frame_start_int, frame_end_int = frame_end_int, frame_start_int
    return affected_start <= frame_end_int and affected_end >= frame_start_int


def _iteration_id_in_range(iteration_id: str, start: int, end: int) -> bool:
    numbers = [int(match) for match in re.findall(r"\d+", str(iteration_id or ""))]
    if not numbers:
        return False
    value = numbers[-1]
    return start <= value <= end


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
    frame_index = {
        str(frame.get("frame_id") or frame.get("scope_id") or ""): frame
        for frame in frames
        if str(frame.get("frame_id") or frame.get("scope_id") or "")
    }
    candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    for frame in frames:
        if str(frame.get("status") or "active") != "active":
            continue
        if node_id in _loop_scope_node_ids(graph_config=graph_config, frame=frame):
            frame_id = str(frame.get("frame_id") or frame.get("scope_id") or "").strip()
            scope_size = len(_loop_scope_node_ids(graph_config=graph_config, frame=frame))
            candidates.append((_loop_frame_depth(frame=frame, frames=frame_index), -scope_size, frame_id, frame))
    if not candidates:
        return {}
    return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def _loop_frame_depth(*, frame: dict[str, Any], frames: dict[str, dict[str, Any]]) -> int:
    depth = 0
    current = dict(frame or {})
    visited: set[str] = set()
    while True:
        parent_ref = str(current.get("parent_scope_id") or "").strip()
        if not parent_ref or parent_ref in visited:
            return depth
        visited.add(parent_ref)
        parent = _loop_parent_frame(parent_ref=parent_ref, frames=frames)
        if not parent:
            return depth
        depth += 1
        current = parent


def _loop_parent_frame(*, parent_ref: str, frames: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if parent_ref in frames:
        return dict(frames[parent_ref])
    parent_tail = _loop_scope_tail(parent_ref)
    for frame_id, frame in frames.items():
        if _loop_scope_tail(frame_id) == parent_tail:
            return dict(frame)
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
    history[result.node_id] = tuple(node_history[-_MAX_RESULT_HISTORY_PER_NODE:])
    return history


def _compact_state_for_checkpoint(state: GraphLoopState) -> GraphLoopState:
    return _replace_state(
        state,
        diagnostics=_compact_diagnostics(state.diagnostics),
        result_history=_compact_result_history(state.result_history),
        work_order_index=_compact_work_order_index(
            state.work_order_index,
            active_work_orders=state.active_work_orders,
            node_states=state.node_states,
        ),
    )


def _compact_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    for key in _BULKY_DIAGNOSTIC_KEYS:
        if key not in payload:
            continue
        raw = payload.pop(key)
        payload[f"{key}_summary"] = _payload_summary(raw)
    return payload


def _compact_result_history(history: dict[str, tuple[dict[str, Any], ...]]) -> dict[str, tuple[dict[str, Any], ...]]:
    compacted: dict[str, tuple[dict[str, Any], ...]] = {}
    for key, value in dict(history or {}).items():
        items = [dict(item) for item in tuple(value or ()) if isinstance(item, dict)]
        compacted[str(key)] = tuple(items[-_MAX_RESULT_HISTORY_PER_NODE:])
    return compacted


def _compact_work_order_index(
    index: dict[str, dict[str, Any]],
    *,
    active_work_orders: dict[str, str],
    node_states: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload = {str(key): dict(value) for key, value in dict(index or {}).items() if str(key)}
    keep: set[str] = {str(item) for item in dict(active_work_orders or {}).values() if str(item)}
    for state in dict(node_states or {}).values():
        if not isinstance(state, dict):
            continue
        work_order_id = str(state.get("work_order_id") or "")
        if work_order_id and str(state.get("status") or "") in {"running", "blocked"}:
            keep.add(work_order_id)
    if len(payload) <= _MAX_WORK_ORDER_INDEX_ENTRIES:
        return payload
    recent_keys = list(payload.keys())[-_MAX_WORK_ORDER_INDEX_ENTRIES:]
    keep.update(recent_keys)
    return {key: payload[key] for key in payload.keys() if key in keep}


def _payload_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        count = len(value)
        keys = [str(key) for key in list(value.keys())[:30]]
    elif isinstance(value, (list, tuple)):
        count = len(value)
        keys = []
    else:
        count = 0
        keys = []
    return {
        "content_hash": stable_hash(value),
        "content_chars": len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)),
        "item_count": count,
        **({"keys": keys} if keys else {}),
        "authority": "harness.graph_loop.compacted_payload_summary",
    }


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
    edge_states: dict[str, dict[str, Any]] | None = None,
    loop_state: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    return _STATE_MACHINE.ready_nodes(graph_config=graph_config, node_states=node_states, edge_states=edge_states, loop_state=loop_state)


def _blocked_nodes(
    *,
    graph_config: GraphHarnessConfig,
    node_states: dict[str, dict[str, Any]],
    loop_state: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    return _STATE_MACHINE.blocked_nodes(graph_config=graph_config, node_states=node_states, loop_state=loop_state)


def _node_is_resource(node: dict[str, Any]) -> bool:
    return str(node.get("node_class") or node.get("node_type") or "").strip() == "resource"


def _quality_same_node_retry_decision(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    result: NodeResultEnvelope,
) -> dict[str, Any]:
    if result.status != "blocked" or not _node_result_is_quality_gate_failure(result):
        return {}
    node = _node_by_id(graph_config, result.node_id) or {}
    retry_policy = dict(node.get("retry") or {})
    mode = str(retry_policy.get("quality_failure_mode") or retry_policy.get("failure_mode") or "").strip().lower()
    if mode not in {"retry_same_node", "requeue_same_node"}:
        return {}
    max_retries = int(_numeric_value(retry_policy.get("max_quality_retries") or retry_policy.get("max_metric_retries"), 0) or 0)
    if max_retries < 1:
        return {}
    failure_count = _quality_gate_failure_count(state=state, node_id=result.node_id)
    if failure_count > max_retries:
        return {}
    return {
        "authority": "harness.graph.quality_same_node_retry_decision",
        "action": "requeue_same_node",
        "node_id": result.node_id,
        "result_id": result.result_id,
        "attempt_index": failure_count,
        "max_quality_retries": max_retries,
        "reason": "quality_gate_failed",
    }


def _state_after_quality_same_node_retry(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    decision: dict[str, Any],
) -> GraphLoopState:
    node_id = str(decision.get("node_id") or "").strip()
    if not node_id:
        return state
    node_states = {key: dict(value) for key, value in state.node_states.items()}
    edge_states = {key: dict(value) for key, value in state.edge_states.items()}
    active_work_orders = dict(state.active_work_orders)
    now = time.time()
    node = dict(node_states.get(node_id) or {})
    if not node:
        return state
    node["status"] = "ready"
    node["updated_at"] = now
    for key in ("blocked_reason", "result_ref", "work_order_id", "human_gate"):
        node.pop(key, None)
    node_states[node_id] = node
    active_work_orders.pop(node_id, None)
    edge_states = _reset_outgoing_failed_edges(
        edge_states=edge_states,
        source_node_id=node_id,
        updated_at=now,
    )
    target_set = {node_id}
    return _replace_state(
        state,
        status="running",
        node_states=node_states,
        edge_states=edge_states,
        active_work_orders=active_work_orders,
        ready_node_ids=tuple(dict.fromkeys([*state.ready_node_ids, node_id])),
        running_node_ids=(),
        blocked_node_ids=tuple(
            current_node_id
            for current_node_id, payload in node_states.items()
            if current_node_id not in target_set and str(payload.get("status") or "") in {"blocked", "waiting_human_gate"}
        ),
        terminal_reason="",
    )


def _node_result_is_quality_gate_failure(result: NodeResultEnvelope) -> bool:
    error = dict(result.error or {})
    diagnostics = dict(result.diagnostics or {})
    quality_acceptance = dict(diagnostics.get("quality_acceptance") or {})
    return str(error.get("reason") or "").strip() == "quality_gate_failed" or quality_acceptance.get("accepted") is False


def _quality_gate_failure_count(*, state: GraphLoopState, node_id: str) -> int:
    reset_after = _quality_gate_retry_reset_after(state=state, node_id=node_id)
    count = 0
    for raw_summary in reversed(tuple(dict(state.result_history or {}).get(node_id) or ())):
        if not isinstance(raw_summary, dict):
            continue
        summary = dict(raw_summary)
        created_at = float(_numeric_value(summary.get("created_at"), 0.0) or 0.0)
        if reset_after and (not created_at or created_at <= reset_after):
            break
        error = dict(summary.get("error") or {})
        diagnostics = dict(summary.get("diagnostics") or {})
        quality_acceptance = dict(diagnostics.get("quality_acceptance") or {})
        if str(summary.get("status") or "") == "blocked" and (
            str(error.get("reason") or "").strip() == "quality_gate_failed"
            or quality_acceptance.get("accepted") is False
        ):
            count += 1
            continue
        break
    return count


def _quality_gate_retry_reset_after(*, state: GraphLoopState, node_id: str) -> float:
    resets = dict(dict(state.diagnostics or {}).get("quality_retry_reset_after") or {})
    value = resets.get(node_id)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ready_rejected_revision_targets(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    source_node_id: str = "",
    source_result_ref: str = "",
) -> tuple[str, ...]:
    targets: list[str] = []
    source_filter = str(source_node_id or "").strip()
    result_ref_filter = str(source_result_ref or "").strip()
    for edge in graph_config.edges:
        edge_type = str(edge.get("edge_type") or "").strip()
        semantic_role = str(edge.get("semantic_role") or "").strip()
        if edge_type not in REVISION_EDGE_TYPES and semantic_role != "revision":
            continue
        source = str(edge.get("source_node_id") or "").strip()
        if source_filter and source != source_filter:
            continue
        edge_id = str(edge.get("edge_id") or "").strip()
        edge_state = dict(state.edge_states.get(edge_id) or {})
        if str(edge_state.get("status") or "") != "ready":
            continue
        if result_ref_filter and str(edge_state.get("source_result_ref") or "").strip() != result_ref_filter:
            continue
        target = str(edge.get("target_node_id") or "").strip()
        if not source or not target:
            continue
        source_result = _latest_result_summary(state=state, node_id=source)
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
            if _edge_is_revision(dict(edge)):
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


def _revision_clear_input_keys(
    *,
    graph_config: GraphHarnessConfig,
    target_node_ids: tuple[str, ...],
) -> tuple[str, ...]:
    target_set = {str(item) for item in target_node_ids if str(item)}
    keys: list[str] = [
        "chapter_revision_requirements",
        "quality_gate_feedback",
        "previous_chapter_review_ref",
        "previous_chapter_draft_ref",
        "revision_required",
        "revision_active",
        "revision_queue_chapter_indexes",
        "revision_queue_position",
        "revision_current_chapter_index",
        "revision_execution_range",
    ]
    for node_id in target_set:
        node = _node_by_id(graph_config, node_id) or {}
        retry_policy = dict(node.get("retry") or {})
        requirements_key = str(retry_policy.get("requirements_input_key") or "").strip()
        carry_key = str(retry_policy.get("carry_current_output_as") or "").strip()
        if requirements_key:
            keys.append(requirements_key)
        if carry_key:
            keys.append(carry_key)
    for edge in graph_config.edges:
        if str(edge.get("target_node_id") or "").strip() not in target_set:
            continue
        if not _edge_is_revision(dict(edge)):
            continue
        metadata = dict(edge.get("metadata") or {})
        for key in list(metadata.get("clear_input_keys") or []):
            text = str(key or "").strip()
            if text:
                keys.append(text)
    return tuple(dict.fromkeys(keys))


def _revision_cursor_input_patch(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    target_node_ids: tuple[str, ...],
) -> dict[str, Any]:
    target_set = {str(item) for item in target_node_ids if str(item)}
    if not target_set:
        return {}
    affected_indexes: list[int] = []
    revision_plan_text = ""
    for edge in graph_config.edges:
        target = str(edge.get("target_node_id") or "").strip()
        if target not in target_set or not _edge_is_revision(dict(edge)):
            continue
        source = str(edge.get("source_node_id") or "").strip()
        summary = _latest_result_summary(state=state, node_id=source)
        text = _revision_source_text(summary)
        route = _revision_route_from_result_summary(summary)
        indexes = _revision_route_chapter_indexes(route, state=state) if route else _revision_affected_chapter_indexes(text)
        indexes = _revision_indexes_within_current_batch(indexes, state=state)
        if not indexes:
            continue
        if not revision_plan_text:
            revision_plan_text = _revision_route_plan_text(route=route, review_text=text) if route else _revision_plan_excerpt(text)
        for index in indexes:
            if index not in affected_indexes:
                affected_indexes.append(index)
    queue = sorted(affected_indexes)
    if not queue:
        return {}
    affected_start = int(queue[0])
    affected_end = int(queue[-1])
    patch: dict[str, Any] = {
        **_single_chapter_cursor_patch(affected_start),
        "revision_active": True,
        "revision_queue_chapter_indexes": queue,
        "revision_queue_position": 0,
        "revision_current_chapter_index": affected_start,
        "revision_execution_range": _revision_execution_range_label(queue),
    }
    if revision_plan_text:
        patch["revision_plan_text"] = revision_plan_text
        patch["chapter_revision_requirements"] = _revision_requirements_for_chapter(
            revision_plan_text,
            affected_start,
        )
    return patch


def _revision_indexes_within_current_batch(indexes: list[int], *, state: GraphLoopState) -> list[int]:
    if not indexes:
        return []
    initial_inputs = dict(state.initial_inputs or {})
    start = _numeric_value(
        initial_inputs.get("batch_start_index")
        or initial_inputs.get("active_chapter_start_index"),
        None,
    )
    end = _numeric_value(
        initial_inputs.get("batch_end_index")
        or initial_inputs.get("active_chapter_end_index"),
        None,
    )
    if start is None or end is None:
        return sorted(dict.fromkeys(index for index in indexes if int(index) > 0))
    start_index = int(start)
    end_index = int(end)
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    return sorted(
        dict.fromkeys(
            int(index)
            for index in indexes
            if int(index) >= start_index and int(index) <= end_index
        )
    )


def _revision_route_from_result_summary(summary: dict[str, Any]) -> dict[str, Any]:
    outputs = dict(dict(summary or {}).get("outputs") or {})
    candidates: list[Any] = [
        dict(summary or {}).get("revision_route"),
        outputs.get("revision_route"),
    ]
    for key in ("structured_output", "node_output"):
        payload = outputs.get(key)
        if isinstance(payload, dict):
            candidates.extend(
                [
                    payload.get("revision_route"),
                    payload.get("review_revision_route"),
                    payload.get("revision"),
                ]
            )
    for candidate in candidates:
        route = _normalize_revision_route(candidate)
        if route:
            return route
    return {}


def _normalize_revision_route(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    route = dict(candidate or {})
    action = str(route.get("action") or route.get("decision") or route.get("route") or "").strip().lower()
    if action and action not in {
        "revise",
        "revision",
        "request_revision",
        "rewrite",
        "return_to_writer",
        "reject",
        "rejected",
        "返修",
        "拒绝",
    }:
        return {}
    if not action and not any(
        key in route
        for key in (
            "chapter_indexes",
            "affected_chapter_indexes",
            "revision_chapter_indexes",
            "rewrite_chapter_indexes",
            "scope",
            "full_batch",
        )
    ):
        return {}
    route["action"] = action or "revise"
    route["authority"] = str(route.get("authority") or "chapter_review.revision_route")
    return route


def _revision_route_chapter_indexes(route: dict[str, Any], *, state: GraphLoopState) -> list[int]:
    if not route:
        return []
    scope = str(route.get("scope") or route.get("revision_scope") or "").strip().lower()
    full_batch = bool(route.get("full_batch") is True) or scope in {
        "full_batch",
        "batch",
        "all_batch",
        "entire_batch",
        "all",
        "整批",
        "全批",
    }
    if full_batch:
        initial_inputs = dict(state.initial_inputs or {})
        start = _numeric_value(route.get("batch_start_index"), None)
        end = _numeric_value(route.get("batch_end_index"), None)
        if start is None:
            start = _numeric_value(initial_inputs.get("batch_start_index"), None)
        if end is None:
            end = _numeric_value(initial_inputs.get("batch_end_index"), start)
        return _revision_indexes_from_range_values(start, end)
    indexes: list[int] = []
    for key in (
        "chapter_indexes",
        "affected_chapter_indexes",
        "revision_chapter_indexes",
        "rewrite_chapter_indexes",
        "chapters",
        "affected_chapters",
    ):
        indexes.extend(_revision_route_indexes_from_value(route.get(key)))
    if indexes:
        return sorted(dict.fromkeys(indexes))
    start = _numeric_value(
        route.get("revision_start_index")
        or route.get("start_chapter_index")
        or route.get("chapter_start_index"),
        None,
    )
    end = _numeric_value(
        route.get("revision_end_index")
        or route.get("end_chapter_index")
        or route.get("chapter_end_index"),
        start,
    )
    return _revision_indexes_from_range_values(start, end)


def _revision_route_indexes_from_value(value: Any) -> list[int]:
    raw_items = value if isinstance(value, list) else ([value] if value is not None else [])
    indexes: list[int] = []
    for item in raw_items:
        if isinstance(item, dict):
            number = _numeric_value(item.get("chapter_index") or item.get("index") or item.get("chapter"), None)
        else:
            number = _numeric_value(item, None)
        if number is None:
            continue
        chapter = int(number)
        if chapter > 0 and chapter not in indexes:
            indexes.append(chapter)
    return indexes


def _revision_indexes_from_range_values(start_value: Any, end_value: Any) -> list[int]:
    start = _numeric_value(start_value, None)
    end = _numeric_value(end_value, start)
    if start is None or end is None:
        return []
    start_index = int(start)
    end_index = int(end)
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    if start_index <= 0 or end_index - start_index > 100:
        return []
    return list(range(start_index, end_index + 1))


def _revision_route_plan_text(*, route: dict[str, Any], review_text: str) -> str:
    route_text = json.dumps(route, ensure_ascii=False, indent=2) if route else ""
    requirements = (
        route.get("requirements")
        or route.get("revision_requirements")
        or route.get("instructions")
        or route.get("reason")
        or route.get("issue_summary")
    )
    if isinstance(requirements, (dict, list)):
        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
    else:
        requirements_text = str(requirements or "").strip()
    sections = []
    if route_text:
        sections.append(f"## 返修路由\n\n```json\n{route_text}\n```")
    if requirements_text:
        sections.append(f"## 返修要求\n\n{requirements_text}")
    excerpt = _revision_plan_excerpt(review_text)
    if excerpt:
        sections.append(excerpt)
    return "\n\n".join(sections).strip()[:16000]


def _has_ready_revision_target(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    target_node_ids: tuple[str, ...],
) -> bool:
    target_set = {str(item) for item in target_node_ids if str(item)}
    if not target_set:
        return False
    for edge in graph_config.edges:
        target = str(edge.get("target_node_id") or "").strip()
        if target not in target_set or not _edge_is_revision(dict(edge)):
            continue
        edge_id = str(edge.get("edge_id") or "").strip()
        edge_state = dict(state.edge_states.get(edge_id) or {})
        if str(edge_state.get("status") or "") == "ready":
            return True
    return False


def _latest_result_summary(*, state: GraphLoopState, node_id: str) -> dict[str, Any]:
    history = tuple(dict(state.result_history or {}).get(node_id) or ())
    for raw_summary in reversed(history):
        if isinstance(raw_summary, dict):
            return dict(raw_summary)
    return dict(dict(state.result_index or {}).get(node_id) or {})


def _revision_source_text(summary: dict[str, Any]) -> str:
    for ref in list(dict(summary or {}).get("artifact_refs") or []):
        path = _artifact_ref_path(ref)
        if not path:
            continue
        try:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            if candidate.exists() and candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
                if text.strip():
                    return text
        except Exception:
            continue
    return str(dict(summary or {}).get("handoff_summary") or "")


def _revision_plan_excerpt(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    sections: list[str] = []
    for heading in ("返修要求", "必须修改项", "阻塞问题", "阻塞性问题", "问题清单", "语义连续性与矛盾点检查", "层级一致性检查"):
        match = re.search(rf"(?m)^(#{{1,4}})\s*{heading}\b.*$", normalized)
        if not match:
            continue
        section = _markdown_heading_section(normalized, start=match.start(), level=len(match.group(1)))
        if section.strip():
            sections.append(section.strip())
    return "\n\n".join(dict.fromkeys(sections)).strip()[:16000] or normalized[:16000]


def _markdown_heading_section(text: str, *, start: int, level: int) -> str:
    tail = str(text or "")[start:]
    first_newline = tail.find("\n")
    if first_newline < 0:
        return tail
    search_tail = tail[first_newline + 1 :]
    next_heading = re.search(rf"(?m)^#{{1,{max(1, int(level))}}}\s+", search_tail)
    if not next_heading:
        return tail
    return tail[: first_newline + 1 + next_heading.start()]


def _revision_requirements_for_chapter(plan_text: str, chapter: int) -> str:
    normalized = str(plan_text or "").strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    selected: list[str] = []
    chapter_pattern = re.compile(rf"第\s*0*{chapter}\s*章")
    any_chapter_pattern = re.compile(r"第\s*0*\d{1,4}\s*章")
    capture = False
    for line in lines:
        if chapter_pattern.search(line):
            capture = True
            selected.append(line)
            continue
        if capture and any_chapter_pattern.search(line) and not chapter_pattern.search(line):
            break
        if capture:
            selected.append(line)
    body = "\n".join(selected).strip() if selected else normalized[:6000]
    if len(body) < 200:
        body = normalized[:6000]
    return (
        f"当前返修章：第{chapter}章。以下要求只用于当前章重写；"
        "返修队列中的其他章节由图循环逐章调度。\n\n"
        f"{body}"
    ).strip()[:8000]


def _artifact_ref_path(ref: Any) -> str:
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        for key in ("path", "artifact_path", "ref", "artifact_ref"):
            value = str(ref.get(key) or "").strip()
            if value:
                return value
    return ""


def _revision_affected_chapter_indexes(text: str) -> list[int]:
    normalized = str(text or "")
    if not normalized:
        return []
    explicit_patterns = (
        r"(?:重写|返修|修改|修正)[^。\n]{0,30}?第\s*0*(\d{1,4})\s*[-至到~—－]\s*0*(\d{1,4})\s*章",
        r"(?:重写|返修|修改|修正)[^。\n]{0,30}?第\s*0*(\d{1,4})\s*章",
    )
    requirement_section = _revision_requirement_section(normalized)
    if requirement_section:
        requirement_indexes = _revision_chapter_indexes_from_section(requirement_section, explicit_patterns)
        if requirement_indexes:
            return requirement_indexes
    blocking_section = _revision_blocking_section(normalized)
    if blocking_section:
        blocking_indexes = _revision_chapter_indexes_from_section(blocking_section, explicit_patterns)
        if blocking_indexes:
            return blocking_indexes
    explicit_candidates = _revision_range_candidates(normalized, explicit_patterns)
    if explicit_candidates:
        return _revision_indexes_from_ranges(explicit_candidates)
    return []


def _revision_chapter_indexes_from_section(text: str, patterns: tuple[str, ...]) -> list[int]:
    indexes = _revision_indexes_from_ranges(_revision_range_candidates(text, patterns))
    for line in str(text or "").splitlines():
        if not re.search(r"第\s*0*\d{1,4}\s*章", line):
            continue
        if _revision_line_is_scope_description(line):
            continue
        if not _revision_line_is_issue(line):
            continue
        for match in re.finditer(r"第\s*0*(\d{1,4})\s*章", line):
            chapter = int(match.group(1))
            if chapter > 0 and chapter not in indexes:
                indexes.append(chapter)
    return sorted(indexes)


def _revision_line_is_scope_description(line: str) -> bool:
    text = str(line or "")
    if re.search(r"(?:返修|重写|修改|修正|阻塞|问题|矛盾|缺失|不达标|偏离|必须|需要|不足)", text):
        return False
    return bool(re.search(r"(?:汇总范围|审核范围|当前批次|允许范围|章节引用索引)", text))


def _revision_line_is_issue(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    if re.search(r"(?:返修|重写|修改|修正|阻塞|问题|矛盾|缺失|不达标|偏离|必须|需要|不足|不允许|不能通过)", text):
        return True
    return bool(re.match(r"^(?:[-*+]\s*)?(?:B-\d+|R-\d+|问题\s*\d+|第\s*0*\d{1,4}\s*章)[：:、.\s]", text))


def _revision_range_candidates(text: str, patterns: tuple[str, ...]) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            start = int(match.group(1))
            end = int(match.group(2)) if len(match.groups()) >= 2 and match.group(2) else start
            if start > end:
                start, end = end, start
            candidates.append((start, end))
    return candidates


def _revision_indexes_from_ranges(candidates: list[tuple[int, int]]) -> list[int]:
    indexes: list[int] = []
    for start, end in candidates:
        if start > end:
            start, end = end, start
        if end - start > 100:
            continue
        for chapter in range(start, end + 1):
            if chapter > 0 and chapter not in indexes:
                indexes.append(chapter)
    return sorted(indexes)


def _revision_execution_range_label(indexes: list[int]) -> str:
    ordered = sorted({int(item) for item in indexes if int(item) > 0})
    if not ordered:
        return ""
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{ordered[0]:03d}-{ordered[-1]:03d}"
    return ",".join(f"{item:03d}" for item in ordered)


def _revision_requirement_section(text: str) -> str:
    match = re.search(r"(?m)^#{1,4}\s*返修要求\s*$", text)
    if not match:
        return ""
    tail = text[match.end() :]
    next_heading = re.search(r"(?m)^#{1,4}\s+", tail)
    return tail[: next_heading.start()] if next_heading else tail


def _revision_blocking_section(text: str) -> str:
    match = re.search(r"(?m)^#{1,4}\s*(?:必须修改项|阻塞问题|阻塞性问题|问题清单)\b.*$", text)
    if not match:
        return ""
    tail = text[match.end() :]
    next_nonblocking = re.search(r"(?m)^#{1,4}\s*(?:非阻塞|备注)", tail)
    if next_nonblocking:
        tail = tail[: next_nonblocking.start()]
    next_major = re.search(r"(?m)^##\s+(?:是否允许|下游|输入继承|当前节点|禁止)", tail)
    return tail[: next_major.start()] if next_major else tail


def _state_after_revision_requeue(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    targets: tuple[str, ...],
    reset_node_ids: tuple[str, ...],
    preserve_ready_revision_edges: bool = True,
) -> GraphLoopState:
    node_states = {key: dict(value) for key, value in state.node_states.items()}
    edge_states = {key: dict(value) for key, value in state.edge_states.items()}
    result_index = {key: dict(value) for key, value in state.result_index.items()}
    active_work_orders = dict(state.active_work_orders)
    initial_inputs = dict(state.initial_inputs or {})
    target_set = set(targets)
    reset_set = set(reset_node_ids)
    for key in _revision_clear_input_keys(graph_config=graph_config, target_node_ids=targets):
        initial_inputs.pop(key, None)
    cursor_patch = _revision_cursor_input_patch(
        graph_config=graph_config,
        state=state,
        target_node_ids=targets,
    )
    has_revision_target = bool(preserve_ready_revision_edges) and _has_ready_revision_target(graph_config=graph_config, state=state, target_node_ids=targets)
    requires_execution_range = has_revision_target and _revision_targets_require_execution_range(
        graph_config=graph_config,
        target_node_ids=targets,
    )
    if cursor_patch:
        initial_inputs.update(cursor_patch)
    initial_inputs = _apply_derived_fields(initial_inputs, _loop_derived_fields(graph_config))
    loop_state = _loop_state_without_revision_iteration_results(
        loop_state=dict(state.loop_state or {}),
        target_node_ids=targets,
        initial_inputs=initial_inputs,
    )
    loop_state = _loop_state_with_revision_frames_active(
        graph_config=graph_config,
        loop_state=loop_state,
        target_node_ids=targets,
        initial_inputs=initial_inputs,
    )
    loop_state = _loop_state_with_requeue_exit_frames(
        loop_state=loop_state,
        target_node_ids=targets,
    )
    preserved_revision_edges = {
        edge_id: dict(edge_state)
        for edge_id, edge_state in edge_states.items()
        if preserve_ready_revision_edges
        if str(edge_state.get("status") or "") == "ready"
        and str(edge_state.get("target_node_id") or "") in target_set
        and _edge_is_revision(_edge_by_id(graph_config, edge_id) or {})
    }
    now = time.time()
    for node_id in reset_node_ids:
        node = dict(node_states.get(node_id) or {})
        if not node:
            continue
        missing_required_range = requires_execution_range and not cursor_patch and node_id in target_set
        node["status"] = "blocked" if missing_required_range else ("ready" if node_id in target_set else "pending")
        if missing_required_range:
            node["blocked_reason"] = "revision_execution_range_missing"
        node["updated_at"] = now
        for key in ("result_ref", "work_order_id", "human_gate"):
            node.pop(key, None)
        if not missing_required_range:
            node.pop("blocked_reason", None)
        node_states[node_id] = node
        result_index.pop(node_id, None)
        active_work_orders.pop(node_id, None)
    for edge in graph_config.edges:
        edge_id = str(edge.get("edge_id") or "")
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if not edge_id or (source not in reset_set and target not in reset_set):
            continue
        if target in reset_set and source not in reset_set and not _edge_is_revision(dict(edge)):
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
        if edge_id in preserved_revision_edges:
            edge_state.update(preserved_revision_edges[edge_id])
            edge_state["status"] = "ready"
            edge_state["updated_at"] = now
        edge_states[edge_id] = edge_state
    return _replace_state(
        state,
        status="running",
        node_states=node_states,
        edge_states=edge_states,
        result_index=result_index,
        loop_state=loop_state,
        initial_inputs=initial_inputs,
        active_work_orders=active_work_orders,
        ready_node_ids=() if requires_execution_range and not cursor_patch else targets,
        running_node_ids=(),
        failed_node_ids=tuple(item for item in state.failed_node_ids if item not in reset_set),
        blocked_node_ids=targets if requires_execution_range and not cursor_patch else (),
        terminal_reason="",
    )


def _revision_targets_require_execution_range(
    *,
    graph_config: GraphHarnessConfig,
    target_node_ids: tuple[str, ...],
) -> bool:
    for node_id in target_node_ids:
        node = _node_by_id(graph_config, str(node_id)) or {}
        node_tail = str(node.get("node_id") or "").split("::")[-1]
        if node_tail == "chapter_draft":
            return True
        retry_policy = dict(node.get("retry") or {})
        if str(retry_policy.get("requirements_input_key") or "").strip() == "chapter_revision_requirements":
            return True
    return False


def _dispatch_block_payload(*, node_id: str, error: GraphMemoryContextResolutionError) -> dict[str, Any]:
    reason = str(error.reason or "memory_context_resolution_failed").strip()
    return _drop_empty(
        {
            "reason": reason,
            "node_id": str(node_id or error.node_id or "").strip(),
            "work_order_id": error.work_order_id,
            "message": str(error),
            "details": dict(error.details or {}),
            "blocked_reason": f"memory_context:{reason}",
            "authority": "harness.graph.dispatch_block",
        }
    )


def _state_after_dispatch_block(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    node_id: str,
    block: dict[str, Any],
    state_machine: GraphStateMachine,
) -> GraphLoopState:
    node_states = {key: dict(value) for key, value in state.node_states.items()}
    node_state = dict(node_states.get(node_id) or {"node_id": node_id})
    node_state["status"] = "blocked"
    node_state["blocked_reason"] = str(dict(block).get("blocked_reason") or "dispatch_blocked")
    node_state["dispatch_block"] = dict(block)
    node_state["updated_at"] = time.time()
    node_states[node_id] = node_state
    diagnostics = dict(state.diagnostics or {})
    dispatch_blocks = [dict(item) for item in list(diagnostics.get("dispatch_blocks") or []) if isinstance(item, dict)]
    dispatch_blocks.append(dict(block))
    diagnostics["dispatch_blocks"] = dispatch_blocks[-24:]
    active_work_orders = dict(state.active_work_orders or {})
    active_work_orders.pop(node_id, None)
    status_snapshot = state_machine.status_snapshot(
        graph_config=graph_config,
        node_states=node_states,
        edge_states={key: dict(value) for key, value in state.edge_states.items()},
        active_work_orders=active_work_orders,
        loop_state=state.loop_state,
    )
    return _replace_state(
        state,
        status=status_snapshot.status,
        node_states=node_states,
        active_work_orders=active_work_orders,
        ready_node_ids=status_snapshot.ready_node_ids,
        running_node_ids=status_snapshot.running_node_ids,
        completed_node_ids=status_snapshot.completed_node_ids,
        failed_node_ids=status_snapshot.failed_node_ids,
        blocked_node_ids=status_snapshot.blocked_node_ids,
        terminal_reason=status_snapshot.terminal_reason,
        diagnostics=diagnostics,
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


def _formal_task_run_status(graph_status: str) -> str:
    status = str(graph_status or "").strip()
    if status == "waiting_human_gate":
        return "waiting_approval"
    if status in {"created", "running", "waiting_executor", "waiting_approval", "blocked", "completed", "failed", "aborted"}:
        return status
    return "running"


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


def _edge_by_id(graph_config: GraphHarnessConfig, edge_id: str) -> dict[str, Any] | None:
    target = str(edge_id or "")
    return next((dict(item) for item in graph_config.edges if str(item.get("edge_id") or "") == target), None)


def _edge_is_revision(edge: dict[str, Any]) -> bool:
    edge_type = str(edge.get("edge_type") or "").strip()
    semantic_role = str(edge.get("semantic_role") or "").strip()
    return edge_type in REVISION_EDGE_TYPES or semantic_role == "revision"


def _human_gate_route_edge(
    *,
    graph_config: GraphHarnessConfig,
    source_node_id: str,
    target_node_id: str,
    action: str,
) -> dict[str, Any] | None:
    source = str(source_node_id or "").strip()
    target = str(target_node_id or "").strip()
    route_action = str(action or "").strip()
    for raw_edge in graph_config.edges:
        edge = dict(raw_edge)
        if str(edge.get("source_node_id") or "").strip() != source:
            continue
        if str(edge.get("target_node_id") or "").strip() != target:
            continue
        if route_action == "request_revision":
            if _edge_is_revision(edge):
                return edge
            continue
        metadata = dict(edge.get("metadata") or {})
        edge_type = str(edge.get("edge_type") or "").strip()
        scheduler_role = str(edge.get("scheduler_role") or "").strip()
        if (
            bool(metadata.get("human_gate_reroute"))
            or edge_type in {"control", "gate", "gate_pass", "repair_route"}
            or scheduler_role == "conditional_dependency"
        ):
            return edge
    return None


def _assert_human_edge_decision_allowed(*, graph_config: GraphHarnessConfig, edge: dict[str, Any], action: str) -> None:
    contract = edge_contract_or_projection(graph_config, edge)
    policy = dict(contract.get("human_control") or {})
    if not policy or policy.get("enabled") is False:
        raise ValueError(f"Human edge control is not enabled for edge: {edge.get('edge_id')}")
    allowed = {str(item) for item in list(policy.get("allowed_decisions") or []) if str(item)}
    if action not in allowed:
        raise ValueError(f"HumanEdgeDecision {action} is not allowed for edge: {edge.get('edge_id')}")


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


def _edge_states_after_transition(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    trigger_type: str,
    result: NodeResultEnvelope,
    result_ref: str,
    services: Any | None = None,
    edge_id: str = "",
    decision_ref: str = "",
) -> dict[str, dict[str, Any]]:
    transition_payload = {
        "result": result.to_dict(),
        "result_ref": result_ref,
        "decision_ref": decision_ref or f"{trigger_type}:{result.result_id}",
    }
    if edge_id:
        transition_payload["edge_id"] = edge_id
    trigger = GraphTransitionInput(
        trigger_type=trigger_type,
        graph_run_id=state.graph_run_id,
        config_id=state.config_id,
        config_hash=state.config_hash,
        graph_clock_seq=state.event_cursor + 1,
        payload=transition_payload,
    )
    plan = GraphTransitionProcessor(services=services).plan(
        graph_config=graph_config,
        state=state,
        trigger=trigger,
    )
    return apply_transition_plan_to_edge_states(edge_states=state.edge_states, plan=plan)


def _human_edge_decision_result(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    edge: dict[str, Any],
    decision: dict[str, Any],
    action: str,
) -> NodeResultEnvelope:
    del graph_config
    edge_id = str(edge.get("edge_id") or "")
    source_node_id = str(edge.get("source_node_id") or "")
    decision_id = str(decision.get("decision_id") or f"human:{edge_id}:{int(time.time() * 1000)}")
    instruction = str(decision.get("instruction") or "").strip()
    artifact_refs = tuple(_artifact_ref_values(list(decision.get("artifact_refs") or [])))
    content_submission = dict(decision.get("content_submission") or {})
    summary = instruction
    if action == "replace":
        path = str(content_submission.get("path") or "").strip()
        summary = f"用户提交正式产物并替代节点输出。{path}".strip()
    if not summary:
        summary = f"人工边传播决策：{action}"
    decisions = {
        "human_edge_decision": action,
        "decision_id": decision_id,
        "edge_id": edge_id,
        **({"review_verdict": "revise", "verdict": "revise"} if action == "revise" else {}),
        "authority": "harness.graph.human_edge_decision.result_decisions",
    }
    outputs = {
        "human_edge_decision": {
            "decision_id": decision_id,
            "decision": action,
            "edge_id": edge_id,
            "source_node_id": source_node_id,
            "target_node_id": str(edge.get("target_node_id") or ""),
            "instruction": instruction,
            "artifact_refs": [dict(item) for item in list(decision.get("artifact_refs") or []) if isinstance(item, dict)],
            "content_submission": _content_submission_summary(content_submission),
            "authority": "harness.graph.human_edge_decision.output",
        }
    }
    if action == "revise":
        outputs["human_feedback"] = instruction
    if action == "replace":
        outputs["human_artifact_submission"] = _content_submission_summary(content_submission)
    return NodeResultEnvelope(
        result_id=f"hresult:{safe_id(state.graph_run_id)}:{safe_id(decision_id)}",
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        node_id=source_node_id,
        work_order_id=f"human-edge-decision:{safe_id(decision_id)}",
        executor_type="human",
        status="completed",
        outputs=outputs,
        decisions=decisions,
        artifact_refs=artifact_refs,
        handoff_summary=summary,
        diagnostics={
            "human_edge_decision": dict(decision),
            "source_authority": "task_system.graph_instance.human_edge_decision",
            "authority": "harness.graph.human_edge_decision.result_diagnostics",
        },
        created_at=time.time(),
    )


def _source_result_ref_for_human_decision(node_state: dict[str, Any]) -> str:
    return str(
        node_state.get("result_ref")
        or dict(node_state.get("human_gate") or {}).get("source_result_ref")
        or ""
    ).strip()


def _human_edge_decision_state(decision: dict[str, Any]) -> dict[str, Any]:
    if not decision:
        return {}
    return {
        "decision_id": str(decision.get("decision_id") or ""),
        "decision": str(decision.get("decision") or ""),
        "edge_id": str(decision.get("edge_id") or ""),
        "source_node_id": str(decision.get("source_node_id") or ""),
        "target_node_id": str(decision.get("target_node_id") or ""),
        "authority": "harness.graph.human_edge_decision.state_marker",
    }


def _artifact_ref_values(refs: list[Any]) -> list[str]:
    values: list[str] = []
    for item in refs:
        if isinstance(item, dict):
            value = str(item.get("artifact_ref") or item.get("path") or item.get("ref") or "").strip()
        else:
            value = str(item or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _content_submission_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        key: value
        for key, value in dict(payload).items()
        if key != "content"
    }


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
