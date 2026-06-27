from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


GRAPH_CHECKPOINT_NAMESPACE = "graph_loop"


@dataclass(frozen=True, slots=True)
class GraphCheckpointRecord:
    checkpoint_id: str
    graph_run_id: str
    task_run_id: str
    config_id: str
    config_hash: str
    event_cursor: int
    state: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    pending_writes: tuple[Any, ...] = ()
    authority: str = "graph_system_checkpoint"

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "thread_id": self.graph_run_id,
            "graph_run_id": self.graph_run_id,
            "task_run_id": self.task_run_id,
            "config_id": self.config_id,
            "config_hash": self.config_hash,
            "event_cursor": self.event_cursor,
            "state": dict(self.state),
            "metadata": dict(self.metadata),
            "pending_writes": list(self.pending_writes),
            "authority": self.authority,
        }


class GraphCheckpointStore(Protocol):
    def put_checkpoint(self, *, state: Any, metadata: dict[str, Any] | None = None) -> GraphCheckpointRecord:
        ...

    def get_latest_state(self, graph_run_id: str) -> dict[str, Any] | None:
        ...

    def get_latest_checkpoint(self, graph_run_id: str) -> GraphCheckpointRecord | None:
        ...

    def list_checkpoints(self, graph_run_id: str, *, limit: int | None = None) -> tuple[GraphCheckpointRecord, ...]:
        ...

    def put_pending_writes(self, *, graph_run_id: str, task_id: str, writes: tuple[tuple[str, Any], ...]) -> None:
        ...


def checkpoint_store_from_services(services: Any) -> GraphCheckpointStore:
    store = getattr(services, "graph_checkpoint_store", None)
    if store is not None:
        return store
    raise RuntimeError("GraphLoop requires an explicit GraphCheckpointStore")


def _record_from_state_payload(
    payload: dict[str, Any],
    *,
    checkpoint_id: str,
    metadata: dict[str, Any] | None = None,
    pending_writes: tuple[Any, ...] = (),
) -> GraphCheckpointRecord:
    return GraphCheckpointRecord(
        checkpoint_id=str(checkpoint_id or ""),
        graph_run_id=str(payload.get("graph_run_id") or ""),
        task_run_id=str(payload.get("task_run_id") or ""),
        config_id=str(payload.get("config_id") or ""),
        config_hash=str(payload.get("config_hash") or ""),
        event_cursor=int(payload.get("event_cursor") or -1),
        state=dict(payload),
        metadata=dict(metadata or {}),
        pending_writes=tuple(pending_writes or ()),
    )


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]
