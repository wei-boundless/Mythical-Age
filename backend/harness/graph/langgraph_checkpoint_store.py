from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint

from .checkpoint_store import GRAPH_CHECKPOINT_NAMESPACE, GraphCheckpointRecord


class LangGraphCheckpointStore:
    """GraphLoop checkpoint store backed by LangGraph checkpointers.

    This adapter intentionally uses only the checkpoint saver contract. It does
    not import or compile LangGraph's graph runner, so GraphLoop remains the only
    graph state progression authority.
    """

    authority = "harness.graph_checkpoint_store.langgraph"

    def __init__(self, saver: BaseCheckpointSaver[Any]) -> None:
        self._saver = saver

    def put_checkpoint(self, *, state: Any, metadata: dict[str, Any] | None = None) -> GraphCheckpointRecord:
        payload = state.to_dict() if hasattr(state, "to_dict") else dict(state or {})
        graph_run_id = str(payload.get("graph_run_id") or "")
        if not graph_run_id:
            raise ValueError("Graph checkpoint requires graph_run_id")
        checkpoint = empty_checkpoint()
        checkpoint_id = _checkpoint_id(payload)
        checkpoint["id"] = checkpoint_id
        checkpoint["channel_values"] = {
            "graph_loop_state": payload,
            "active_work_orders": dict(payload.get("active_work_orders") or {}),
            "work_order_index": dict(payload.get("work_order_index") or {}),
            "event_cursor": int(payload.get("event_cursor") or -1),
        }
        channel_version = _event_cursor(payload) + 1
        checkpoint["channel_versions"] = {
            "graph_loop_state": channel_version,
            "active_work_orders": channel_version,
            "work_order_index": channel_version,
            "event_cursor": channel_version,
        }
        checkpoint_metadata = {
            "source": "harness.graph_loop",
            "step": _event_cursor(payload),
            "graph_run_id": graph_run_id,
            "task_run_id": str(payload.get("task_run_id") or ""),
            "config_id": str(payload.get("config_id") or ""),
            "config_hash": str(payload.get("config_hash") or ""),
            "schema": "harness.graph_checkpoint.v1",
            "backend": self.authority,
            **dict(metadata or {}),
        }
        new_config = self._saver.put(
            _config(graph_run_id),
            checkpoint,
            checkpoint_metadata,
            checkpoint["channel_versions"],
        )
        stored_checkpoint_id = str(dict(new_config.get("configurable") or {}).get("checkpoint_id") or checkpoint_id)
        return _record_from_checkpoint_tuple(
            self._saver.get_tuple(new_config),
            fallback_graph_run_id=graph_run_id,
            fallback_checkpoint_id=stored_checkpoint_id,
        )

    def get_latest_state(self, graph_run_id: str) -> dict[str, Any] | None:
        record = self.get_latest_checkpoint(graph_run_id)
        return dict(record.state) if record is not None else None

    def get_latest_checkpoint(self, graph_run_id: str) -> GraphCheckpointRecord | None:
        checkpoint_tuple = self._saver.get_tuple(_config(graph_run_id))
        if checkpoint_tuple is None:
            return None
        return _record_from_checkpoint_tuple(
            checkpoint_tuple,
            fallback_graph_run_id=graph_run_id,
            fallback_checkpoint_id="",
        )

    def list_checkpoints(self, graph_run_id: str, *, limit: int | None = None) -> tuple[GraphCheckpointRecord, ...]:
        records: list[GraphCheckpointRecord] = []
        for item in self._saver.list(_config(graph_run_id), limit=limit):
            records.append(
                _record_from_checkpoint_tuple(
                    item,
                    fallback_graph_run_id=graph_run_id,
                    fallback_checkpoint_id="",
                )
            )
        return tuple(records)

    def put_pending_writes(self, *, graph_run_id: str, task_id: str, writes: tuple[tuple[str, Any], ...]) -> None:
        if not writes:
            return
        latest = self._saver.get_tuple(_config(graph_run_id))
        if latest is None:
            raise ValueError(f"Graph checkpoint not found: {graph_run_id}")
        self._saver.put_writes(latest.config, list(writes), task_id=task_id, task_path=GRAPH_CHECKPOINT_NAMESPACE)


def _config(graph_run_id: str) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": str(graph_run_id or ""),
            "checkpoint_ns": GRAPH_CHECKPOINT_NAMESPACE,
        }
    }


def _checkpoint_id(payload: dict[str, Any]) -> str:
    graph_run_id = str(payload.get("graph_run_id") or "graph")
    cursor = _event_cursor(payload)
    return f"gchk:{_safe_id(graph_run_id)}:{cursor}"


def _record_from_checkpoint_tuple(
    checkpoint_tuple: Any,
    *,
    fallback_graph_run_id: str,
    fallback_checkpoint_id: str,
) -> GraphCheckpointRecord:
    if checkpoint_tuple is None:
        return GraphCheckpointRecord(
            checkpoint_id=fallback_checkpoint_id,
            graph_run_id=fallback_graph_run_id,
            task_run_id="",
            config_id="",
            config_hash="",
            event_cursor=-1,
            state={},
            metadata={"backend": LangGraphCheckpointStore.authority, "missing": True},
        )
    checkpoint = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channels = dict(checkpoint.get("channel_values") or {})
    state = dict(channels.get("graph_loop_state") or {})
    return GraphCheckpointRecord(
        checkpoint_id=str(checkpoint.get("id") or fallback_checkpoint_id),
        graph_run_id=str(state.get("graph_run_id") or metadata.get("graph_run_id") or fallback_graph_run_id),
        task_run_id=str(state.get("task_run_id") or metadata.get("task_run_id") or ""),
        config_id=str(state.get("config_id") or metadata.get("config_id") or ""),
        config_hash=str(state.get("config_hash") or metadata.get("config_hash") or ""),
        event_cursor=_int_or_default(state.get("event_cursor"), _int_or_default(metadata.get("step"), -1)),
        state=state,
        metadata=metadata,
        pending_writes=tuple(getattr(checkpoint_tuple, "pending_writes", None) or ()),
    )


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]


def _event_cursor(payload: dict[str, Any]) -> int:
    return _int_or_default(payload.get("event_cursor"), -1)


def _int_or_default(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
