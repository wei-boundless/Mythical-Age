from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_TIMELINE_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    event_id: str
    clock_seq: int
    coordination_run_id: str
    root_task_run_id: str
    graph_id: str
    event_type: str
    status: str = "recorded"
    scope_type: str = "run"
    scope_path: tuple[str, ...] = ("run",)
    parent_event_id: str = ""
    causal_event_ids: tuple[str, ...] = ()
    node_id: str = ""
    edge_id: str = ""
    phase_id: str = ""
    loop_frame_id: str = ""
    iteration_index: int = 0
    revision_cycle_id: str = ""
    parallel_group_id: str = ""
    dispatch_id: str = ""
    request_id: str = ""
    result_record_id: str = ""
    payload_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    checkpoint_ref: str = ""
    idempotency_key: str = ""
    created_at: float = 0.0
    authority: str = "task_graph.timeline_event"

    def __post_init__(self) -> None:
        if self.authority != "task_graph.timeline_event":
            raise ValueError("TimelineEvent authority must be task_graph.timeline_event")
        if not self.coordination_run_id:
            raise ValueError("TimelineEvent requires coordination_run_id")
        if not self.event_type:
            raise ValueError("TimelineEvent requires event_type")
        if self.clock_seq <= 0:
            raise ValueError("TimelineEvent requires positive clock_seq")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_path"] = list(self.scope_path)
        payload["causal_event_ids"] = list(self.causal_event_ids)
        payload["payload"] = dict(self.payload)
        return payload


@dataclass(frozen=True, slots=True)
class TimelineLedger:
    ledger_id: str
    coordination_run_id: str
    root_task_run_id: str = ""
    graph_id: str = ""
    current_clock_seq: int = 0
    events: tuple[TimelineEvent, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0
    authority: str = "task_graph.timeline_ledger"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_id": self.ledger_id,
            "coordination_run_id": self.coordination_run_id,
            "root_task_run_id": self.root_task_run_id,
            "graph_id": self.graph_id,
            "current_clock_seq": self.current_clock_seq,
            "events": [item.to_dict() for item in self.events],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "authority": self.authority,
        }


class TimelineLedgerStore:
    """Append-only semantic event ledger for TaskGraph runs."""

    authority = "task_graph.timeline_ledger_store"

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir)
        self.ledger_dir = self.root_dir / "timeline_ledgers"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)

    def append_event(
        self,
        *,
        coordination_run_id: str,
        event_type: str,
        root_task_run_id: str = "",
        graph_id: str = "",
        status: str = "recorded",
        scope_type: str = "run",
        scope_path: list[str] | tuple[str, ...] | None = None,
        parent_event_id: str = "",
        causal_event_ids: list[str] | tuple[str, ...] = (),
        node_id: str = "",
        edge_id: str = "",
        phase_id: str = "",
        loop_frame_id: str = "",
        iteration_index: int = 0,
        revision_cycle_id: str = "",
        parallel_group_id: str = "",
        dispatch_id: str = "",
        request_id: str = "",
        result_record_id: str = "",
        payload_ref: str = "",
        payload: dict[str, Any] | None = None,
        checkpoint_ref: str = "",
        idempotency_key: str = "",
    ) -> TimelineEvent:
        clean_run_id = str(coordination_run_id or "").strip()
        if not clean_run_id:
            raise ValueError("TimelineLedgerStore.append_event requires coordination_run_id")
        with _TIMELINE_LOCK:
            ledger = self.load(clean_run_id)
            if idempotency_key:
                for item in ledger.events:
                    if item.idempotency_key == idempotency_key:
                        return item
            next_clock = int(ledger.current_clock_seq or 0) + 1
            parent = str(parent_event_id or (ledger.events[-1].event_id if ledger.events else "")).strip()
            event = TimelineEvent(
                event_id=f"tlevent:{_safe_id(clean_run_id)}:{next_clock:06d}:{_safe_id(event_type)}:{uuid.uuid4().hex[:8]}",
                clock_seq=next_clock,
                coordination_run_id=clean_run_id,
                root_task_run_id=str(root_task_run_id or ledger.root_task_run_id or ""),
                graph_id=str(graph_id or ledger.graph_id or ""),
                event_type=str(event_type or "").strip(),
                status=str(status or "recorded"),
                scope_type=str(scope_type or "run"),
                scope_path=tuple(str(item).strip() for item in list(scope_path or ("run",)) if str(item).strip()) or ("run",),
                parent_event_id=parent,
                causal_event_ids=tuple(str(item).strip() for item in causal_event_ids if str(item).strip()),
                node_id=str(node_id or ""),
                edge_id=str(edge_id or ""),
                phase_id=str(phase_id or ""),
                loop_frame_id=str(loop_frame_id or ""),
                iteration_index=int(iteration_index or 0),
                revision_cycle_id=str(revision_cycle_id or ""),
                parallel_group_id=str(parallel_group_id or ""),
                dispatch_id=str(dispatch_id or ""),
                request_id=str(request_id or ""),
                result_record_id=str(result_record_id or ""),
                payload_ref=str(payload_ref or ""),
                payload=dict(payload or {}),
                checkpoint_ref=str(checkpoint_ref or ""),
                idempotency_key=str(idempotency_key or ""),
                created_at=time.time(),
            )
            events = (*ledger.events, event)
            now = time.time()
            updated = TimelineLedger(
                ledger_id=ledger.ledger_id or f"tlledger:{_safe_id(clean_run_id)}",
                coordination_run_id=clean_run_id,
                root_task_run_id=str(root_task_run_id or ledger.root_task_run_id or ""),
                graph_id=str(graph_id or ledger.graph_id or ""),
                current_clock_seq=next_clock,
                events=events,
                created_at=float(ledger.created_at or now),
                updated_at=now,
            )
            self._atomic_write(self._path(clean_run_id), updated.to_dict())
            return event

    def load(self, coordination_run_id: str) -> TimelineLedger:
        clean_run_id = str(coordination_run_id or "").strip()
        if not clean_run_id:
            return TimelineLedger(ledger_id="", coordination_run_id="")
        path = self._path(clean_run_id)
        if not path.exists():
            now = time.time()
            return TimelineLedger(
                ledger_id=f"tlledger:{_safe_id(clean_run_id)}",
                coordination_run_id=clean_run_id,
                created_at=now,
                updated_at=now,
            )
        payload = self._read_json_with_retry(path)
        events: list[TimelineEvent] = []
        for item in list(payload.get("events") or []):
            if not isinstance(item, dict):
                continue
            try:
                events.append(_event_from_payload(item))
            except (TypeError, ValueError):
                continue
        return TimelineLedger(
            ledger_id=str(payload.get("ledger_id") or f"tlledger:{_safe_id(clean_run_id)}"),
            coordination_run_id=str(payload.get("coordination_run_id") or clean_run_id),
            root_task_run_id=str(payload.get("root_task_run_id") or ""),
            graph_id=str(payload.get("graph_id") or ""),
            current_clock_seq=int(payload.get("current_clock_seq") or len(events)),
            events=tuple(events),
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
        )

    def snapshot(self, coordination_run_id: str, *, limit: int = 80) -> dict[str, Any]:
        ledger = self.load(coordination_run_id)
        events = list(ledger.events)
        selected = events[-max(int(limit or 0), 0) :] if limit else events
        return {
            "ledger_id": ledger.ledger_id,
            "coordination_run_id": ledger.coordination_run_id,
            "root_task_run_id": ledger.root_task_run_id,
            "graph_id": ledger.graph_id,
            "current_clock_seq": ledger.current_clock_seq,
            "event_count": len(events),
            "recent_events": [item.to_dict() for item in selected],
            "updated_at": ledger.updated_at,
            "authority": ledger.authority,
        }

    def recent_events(self, coordination_run_id: str, *, limit: int = 80) -> list[dict[str, Any]]:
        return list(self.snapshot(coordination_run_id, limit=limit).get("recent_events") or [])

    def _path(self, coordination_run_id: str) -> Path:
        return self.ledger_dir / f"{_safe_id(coordination_run_id)}.json"

    @staticmethod
    def _read_json_with_retry(path: Path) -> dict[str, Any]:
        last_error: OSError | json.JSONDecodeError | None = None
        for attempt in range(8):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(0.03 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return {}

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with _TIMELINE_LOCK:
            tmp.write_text(text, encoding="utf-8")
            last_error: OSError | None = None
            for attempt in range(8):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            try:
                path.write_text(text, encoding="utf-8")
                tmp.unlink(missing_ok=True)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                if last_error is not None:
                    raise last_error from exc
                raise


def _event_from_payload(payload: dict[str, Any]) -> TimelineEvent:
    return TimelineEvent(
        event_id=str(payload.get("event_id") or ""),
        clock_seq=int(payload.get("clock_seq") or 0),
        coordination_run_id=str(payload.get("coordination_run_id") or ""),
        root_task_run_id=str(payload.get("root_task_run_id") or ""),
        graph_id=str(payload.get("graph_id") or ""),
        event_type=str(payload.get("event_type") or ""),
        status=str(payload.get("status") or "recorded"),
        scope_type=str(payload.get("scope_type") or "run"),
        scope_path=tuple(str(item) for item in list(payload.get("scope_path") or ["run"]) if str(item)),
        parent_event_id=str(payload.get("parent_event_id") or ""),
        causal_event_ids=tuple(str(item) for item in list(payload.get("causal_event_ids") or []) if str(item)),
        node_id=str(payload.get("node_id") or ""),
        edge_id=str(payload.get("edge_id") or ""),
        phase_id=str(payload.get("phase_id") or ""),
        loop_frame_id=str(payload.get("loop_frame_id") or ""),
        iteration_index=int(payload.get("iteration_index") or 0),
        revision_cycle_id=str(payload.get("revision_cycle_id") or ""),
        parallel_group_id=str(payload.get("parallel_group_id") or ""),
        dispatch_id=str(payload.get("dispatch_id") or ""),
        request_id=str(payload.get("request_id") or ""),
        result_record_id=str(payload.get("result_record_id") or ""),
        payload_ref=str(payload.get("payload_ref") or ""),
        payload=dict(payload.get("payload") or {}),
        checkpoint_ref=str(payload.get("checkpoint_ref") or ""),
        idempotency_key=str(payload.get("idempotency_key") or ""),
        created_at=float(payload.get("created_at") or 0.0),
    )


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:120]


