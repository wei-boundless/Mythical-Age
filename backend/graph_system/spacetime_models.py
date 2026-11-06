from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GraphTimeRef:
    graph_run_id: str
    structure_hash: str = ""
    run_epoch: int = 0
    graph_clock_seq: int = 0
    event_cursor: int = -1
    superstep_seq: int = 0
    checkpoint_id: str = ""
    authority: str = "graph_system.graph_time_ref"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.graph_time_ref":
            raise ValueError("GraphTimeRef authority must be graph_system.graph_time_ref")
        if not self.graph_run_id:
            raise ValueError("GraphTimeRef requires graph_run_id")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphTimeRef":
        return cls(
            graph_run_id=str(payload.get("graph_run_id") or ""),
            structure_hash=str(payload.get("structure_hash") or ""),
            run_epoch=_int_or_default(payload.get("run_epoch"), 0),
            graph_clock_seq=_int_or_default(payload.get("graph_clock_seq"), 0),
            event_cursor=_int_or_default(payload.get("event_cursor"), -1),
            superstep_seq=_int_or_default(payload.get("superstep_seq"), 0),
            checkpoint_id=str(payload.get("checkpoint_id") or ""),
            authority=str(payload.get("authority") or "graph_system.graph_time_ref"),
        )


@dataclass(frozen=True, slots=True)
class NodeAttemptRef:
    node_id: str
    work_order_id: str
    node_dispatch_seq: int
    attempt_index: int
    graph_run_id: str = ""
    retry_index: int = 0
    previous_attempt_ref: str = ""
    source_frame_id: str = ""
    graph_clock_seq: int = 0
    superstep_seq: int = 0
    authority: str = "graph_system.node_attempt_ref"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.node_attempt_ref":
            raise ValueError("NodeAttemptRef authority must be graph_system.node_attempt_ref")
        if not self.node_id:
            raise ValueError("NodeAttemptRef requires node_id")
        if not self.work_order_id:
            raise ValueError("NodeAttemptRef requires work_order_id")
        if self.node_dispatch_seq <= 0:
            raise ValueError("NodeAttemptRef requires positive node_dispatch_seq")
        if self.attempt_index <= 0:
            raise ValueError("NodeAttemptRef requires positive attempt_index")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NodeAttemptRef":
        return cls(
            node_id=str(payload.get("node_id") or ""),
            work_order_id=str(payload.get("work_order_id") or ""),
            node_dispatch_seq=max(1, _int_or_default(payload.get("node_dispatch_seq"), 1)),
            attempt_index=max(1, _int_or_default(payload.get("attempt_index"), 1)),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            retry_index=max(0, _int_or_default(payload.get("retry_index"), 0)),
            previous_attempt_ref=str(payload.get("previous_attempt_ref") or ""),
            source_frame_id=str(payload.get("source_frame_id") or ""),
            graph_clock_seq=_int_or_default(payload.get("graph_clock_seq"), 0),
            superstep_seq=_int_or_default(payload.get("superstep_seq"), 0),
            authority=str(payload.get("authority") or "graph_system.node_attempt_ref"),
        )


@dataclass(frozen=True, slots=True)
class HarnessTurnTime:
    turn_run_id: str
    turn_id: str = ""
    session_id: str = ""
    agent_profile_id: str = ""
    runtime_anchor_id: str = ""
    task_environment_id: str = ""
    episode_id: str = ""
    graph_run_id: str = ""
    node_id: str = ""
    node_attempt_ref: str = ""
    executor_epoch: int = 0
    invocation_index: int = 0
    runtime_packet_ref: str = ""
    provider_step_seq: int = 0
    action_request_ref: str = ""
    tool_invocation_ref: str = ""
    observation_ref: str = ""
    latest_event_offset: int = -1
    authority: str = "graph_system.harness_turn_time"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.harness_turn_time":
            raise ValueError("HarnessTurnTime authority must be graph_system.harness_turn_time")
        if not self.turn_run_id:
            raise ValueError("HarnessTurnTime requires turn_run_id")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ExecutionTraceBinding:
    binding_id: str
    graph_run_id: str
    node_id: str
    node_attempt_ref: str
    task_environment_id: str = ""
    episode_id: str = ""
    turn_run_ids: tuple[str, ...] = ()
    runtime_anchor_id: str = ""
    first_harness_event_offset: int = -1
    last_harness_event_offset: int = -1
    node_result_ref: str = ""
    action_request_refs: tuple[str, ...] = ()
    tool_invocation_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "graph_system.execution_trace_binding"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.execution_trace_binding":
            raise ValueError("ExecutionTraceBinding authority must be graph_system.execution_trace_binding")
        if not self.binding_id:
            raise ValueError("ExecutionTraceBinding requires binding_id")
        if not self.graph_run_id:
            raise ValueError("ExecutionTraceBinding requires graph_run_id")
        if not self.node_id:
            raise ValueError("ExecutionTraceBinding requires node_id")
        if not self.node_attempt_ref:
            raise ValueError("ExecutionTraceBinding requires node_attempt_ref")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["turn_run_ids"] = list(self.turn_run_ids)
        payload["action_request_refs"] = list(self.action_request_refs)
        payload["tool_invocation_refs"] = list(self.tool_invocation_refs)
        return _drop_empty(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionTraceBinding":
        return cls(
            binding_id=str(payload.get("binding_id") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            node_attempt_ref=str(payload.get("node_attempt_ref") or ""),
            task_environment_id=str(payload.get("task_environment_id") or ""),
            episode_id=str(payload.get("episode_id") or ""),
            turn_run_ids=_string_tuple(payload.get("turn_run_ids")),
            runtime_anchor_id=str(payload.get("runtime_anchor_id") or ""),
            first_harness_event_offset=_int_or_default(payload.get("first_harness_event_offset"), -1),
            last_harness_event_offset=_int_or_default(payload.get("last_harness_event_offset"), -1),
            node_result_ref=str(payload.get("node_result_ref") or ""),
            action_request_refs=_string_tuple(payload.get("action_request_refs")),
            tool_invocation_refs=_string_tuple(payload.get("tool_invocation_refs")),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "graph_system.execution_trace_binding"),
        )


def graph_time_ref_for_dispatch(
    *,
    graph_run_id: str,
    structure_hash: str = "",
    graph_clock_seq: int = 0,
    event_cursor: int = -1,
    superstep_seq: int = 0,
    checkpoint_id: str = "",
    run_epoch: int = 0,
) -> GraphTimeRef:
    return GraphTimeRef(
        graph_run_id=graph_run_id,
        structure_hash=structure_hash,
        run_epoch=run_epoch,
        graph_clock_seq=graph_clock_seq,
        event_cursor=event_cursor,
        superstep_seq=superstep_seq,
        checkpoint_id=checkpoint_id,
    )


def node_attempt_ref_for_dispatch(
    *,
    graph_run_id: str,
    node_id: str,
    work_order_id: str,
    node_dispatch_seq: int,
    attempt_index: int = 1,
    graph_clock_seq: int = 0,
    superstep_seq: int = 0,
    retry_index: int = 0,
    previous_attempt_ref: str = "",
    source_frame_id: str = "",
) -> NodeAttemptRef:
    return NodeAttemptRef(
        graph_run_id=graph_run_id,
        node_id=node_id,
        work_order_id=work_order_id,
        node_dispatch_seq=max(1, int(node_dispatch_seq or 1)),
        attempt_index=max(1, int(attempt_index or (int(retry_index or 0) + 1))),
        retry_index=max(0, int(retry_index or 0)),
        previous_attempt_ref=previous_attempt_ref,
        source_frame_id=source_frame_id,
        graph_clock_seq=graph_clock_seq,
        superstep_seq=superstep_seq,
    )


def execution_trace_binding_id(*, graph_run_id: str, node_id: str, work_order_id: str) -> str:
    return f"etrace:{graph_run_id}:{node_id}:{work_order_id}"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in list(value or []) if str(item))


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ({}, [], (), "", None)}


def _int_or_default(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
