from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from json import JSONDecodeError
from typing import Any

from .event_index import RuntimeEventIndex, read_event_tail_raw
from .event_payload_store import RuntimeEventPayloadStore
from .events import RuntimeEvent, RuntimeEventType


@dataclass(slots=True)
class RuntimeEventSubscription:
    subscription_id: str
    queue: asyncio.Queue[RuntimeEvent]
    loop: asyncio.AbstractEventLoop | None = None
    run_id: str = ""


class RuntimeEventLog:
    """JSONL event log for Harness traces."""

    def __init__(self, root_dir: Path, *, fact_ledger: Any | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.event_dir = self.root_dir / "events"
        self.event_dir.mkdir(parents=True, exist_ok=True)
        self.index = RuntimeEventIndex(self.root_dir)
        self.payload_store = RuntimeEventPayloadStore(self.root_dir)
        self.fact_ledger = fact_ledger
        self._subscriptions: list[RuntimeEventSubscription] = []
        self._subscription_lock = threading.RLock()
        self._write_lock = threading.RLock()

    def append(
        self,
        run_id: str,
        event_type: RuntimeEventType,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        with self._write_lock:
            path = self._event_path(run_id)
            offset = self.index.next_offset(run_id=run_id, event_path=path)
            event = RuntimeEvent(
                event_id=f"rtevt:{run_id}:{offset}:{uuid.uuid4().hex[:8]}",
                run_id=run_id,
                event_type=event_type,
                offset=offset,
                created_at=time.time(),
                payload={},
                refs={},
            )
            compact_payload, compact_refs = self.payload_store.externalize_if_needed(
                run_id=run_id,
                event_id=event.event_id,
                offset=offset,
                event_type=str(event_type),
                payload=dict(payload or {}),
                refs=dict(refs or {}),
            )
            event = RuntimeEvent(
                event_id=event.event_id,
                run_id=event.run_id,
                event_type=event.event_type,
                offset=event.offset,
                created_at=event.created_at,
                payload=compact_payload,
                refs=compact_refs,
            )
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self.index.record_append(event, event_path=path)
            self._record_runtime_event_fact(event)
        self._publish(event)
        return event

    def attach_fact_ledger(self, fact_ledger: Any | None) -> None:
        self.fact_ledger = fact_ledger

    def _record_runtime_event_fact(self, event: RuntimeEvent) -> None:
        ledger = self.fact_ledger
        if ledger is None:
            return
        event_type = str(getattr(event, "event_type", "") or "")
        if event_type not in _RUNTIME_EVENT_FACT_TYPES:
            return
        try:
            ledger.record_fact(
                fact_type="runtime_event",
                scope=_runtime_event_fact_scope(event),
                source={
                    "system": "runtime_event_log",
                    "authority": event.authority,
                    "source_ref": event.event_id,
                },
                refs=_runtime_event_fact_refs(event),
                attributes={
                    "event_type": event_type,
                    "run_id": event.run_id,
                    "offset": int(event.offset),
                    "payload_externalized": bool(dict(event.payload or {}).get("payload_externalized") is True),
                },
                summary=f"{event_type}:{event.run_id}:{event.offset}",
                retention_class="diagnostic_ttl",
                idempotency_key=f"runtime-event:{event.event_id}",
                created_at=event.created_at,
            )
        except Exception:
            return

    def subscribe(self, *, run_id: str = "", max_queue_size: int = 500) -> RuntimeEventSubscription:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        subscription = RuntimeEventSubscription(
            subscription_id=f"rtesub:{uuid.uuid4().hex}",
            queue=asyncio.Queue(maxsize=max(1, int(max_queue_size or 500))),
            loop=loop,
            run_id=run_id.strip(),
        )
        with self._subscription_lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: RuntimeEventSubscription) -> None:
        with self._subscription_lock:
            self._subscriptions = [
                item for item in self._subscriptions if item.subscription_id != subscription.subscription_id
            ]

    def list_events(self, run_id: str) -> list[RuntimeEvent]:
        path = self._event_path(run_id)
        if not path.exists():
            return []
        events: list[RuntimeEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except JSONDecodeError:
                continue
            events.append(
                self._event_from_payload(
                    self.payload_store.hydrate_event_payload(payload if isinstance(payload, dict) else {}),
                    run_id=run_id,
                )
            )
        return events

    def list_event_window(self, run_id: str, *, limit: int = 240, include_payloads: bool = False) -> list[RuntimeEvent]:
        if include_payloads:
            return [
                self._event_from_payload(self.payload_store.hydrate_event_payload(item), run_id=run_id)
                for item in read_event_tail_raw(self._event_path(run_id), tail_limit=max(1, int(limit or 240)))
            ]
        return self.list_recent_events(run_id, limit=limit)

    def list_recent_events(self, run_id: str, *, limit: int = 160) -> list[RuntimeEvent]:
        if max(1, int(limit or 160)) <= 0:
            return []
        path = self._event_path(run_id)
        if not path.exists():
            return []
        events = self.index.list_recent_events(run_id, limit=max(1, int(limit or 160)), event_path=path)
        if events:
            return events
        self.index.next_offset(run_id=run_id, event_path=path)
        return self.index.list_recent_events(run_id, limit=max(1, int(limit or 160)), event_path=path)

    def event_count(self, run_id: str) -> int:
        return self.index.event_count(run_id, event_path=self._event_path(run_id))

    def estimated_event_count(self, run_id: str) -> int:
        return self.index.estimated_event_count(run_id, event_path=self._event_path(run_id))

    def delete_events(self, run_id: str) -> bool:
        path = self._event_path(run_id)
        if not path.exists():
            return False
        with self._write_lock:
            path.unlink(missing_ok=True)
            self.index.delete_index(run_id)
            self.payload_store.delete_payloads_for_run(run_id)
        return True

    def next_offset(self, run_id: str) -> int:
        return self.index.next_offset(run_id=run_id, event_path=self._event_path(run_id))

    def _publish(self, event: RuntimeEvent) -> None:
        with self._subscription_lock:
            subscriptions = list(self._subscriptions)
        if not subscriptions:
            return
        for subscription in subscriptions:
            if subscription.run_id and subscription.run_id != event.run_id:
                continue
            if subscription.loop is not None and subscription.loop.is_running():
                subscription.loop.call_soon_threadsafe(_put_event_drop_oldest, subscription.queue, event)
                continue
            _put_event_drop_oldest(subscription.queue, event)

    def _event_path(self, run_id: str) -> Path:
        return self.event_dir / f"{_safe_id(run_id)}.jsonl"

    def _event_from_payload(self, payload: dict[str, Any], *, run_id: str) -> RuntimeEvent:
        return RuntimeEvent(
            event_id=str(payload.get("event_id") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or run_id),
            event_type=payload.get("event_type", "loop_error"),
            offset=int(payload.get("offset") or 0),
            created_at=float(payload.get("created_at") or 0.0),
            payload=dict(payload.get("payload") or {}),
            refs=dict(payload.get("refs") or {}),
        )


def _put_event_drop_oldest(queue: asyncio.Queue[RuntimeEvent], event: RuntimeEvent) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


def _safe_id(value: str, *, limit: int = 180) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    if not safe:
        return "runtime"
    if len(safe) <= limit:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    head_limit = max(1, limit - len(digest) - 1)
    return f"{safe[:head_limit].rstrip('_')}_{digest}"


_RUNTIME_EVENT_FACT_TYPES = {
    "agent_run_created",
    "agent_run_updated",
    "agent_run_result_created",
    "agent_runtime_cell_backpressure",
    "agent_runtime_cell_cancel_requested",
    "agent_runtime_cell_cancelled",
    "agent_runtime_cell_completed",
    "agent_runtime_cell_created",
    "agent_runtime_cell_failed",
    "agent_runtime_cell_late_event_rejected",
    "agent_runtime_cell_mailbox_overloaded",
    "agent_runtime_cell_start_failed",
    "agent_runtime_cell_started",
    "agent_runtime_cell_supervision_cancel_requested",
    "agent_turn_action_request_started",
    "agent_turn_action_request_completed",
    "agent_turn_action_request_failed",
    "agent_turn_blocked",
    "agent_turn_clarification_required",
    "agent_turn_closing",
    "agent_turn_completed",
    "agent_turn_failed",
    "approval_resumed",
    "approval_waiting",
    "bounded_observation_recorded",
    "checkpoint_written",
    "commit_gate_checked",
    "execution_dispatch_started",
    "execution_record_created",
    "execution_result_recorded",
    "execution_result_reused",
    "file_change_recorded",
    "loop_error",
    "loop_terminal",
    "model_action_admission_checked",
    "model_action_request_received",
    "operation_gate_checked",
    "output_boundary_applied",
    "recovery_attempted",
    "recovery_replay_decided",
    "replay_guard_triggered",
    "runtime_admission_blocked",
    "runtime_admission_checked",
    "runtime_directive_issued",
    "runtime_evidence_projection_published",
    "runtime_invocation_packet_compiled",
    "session_output_commit_ack",
    "session_output_commit_checked",
    "session_output_commit_failed",
    "session_output_commit_skipped",
    "task_run_executor_claimed",
    "task_run_executor_failed",
    "task_run_executor_scheduled",
    "task_run_launched",
    "task_run_lifecycle_finished",
    "task_run_lifecycle_started",
    "task_run_lifecycle_waiting_executor",
    "task_run_started",
    "task_run_terminal_observed",
    "task_tool_observation_recorded",
    "turn_tool_observation_recorded",
}


def _runtime_event_fact_scope(event: RuntimeEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    refs = dict(event.refs or {})
    task_payload = dict(payload.get("task_run") or {})
    lifecycle_payload = dict(payload.get("lifecycle") or {})
    agent_scope = _runtime_scope_payload(payload, "agent_scope")
    signal_scope = _runtime_scope_payload(payload, "signal", "scope")
    evidence_scope = _runtime_scope_payload(payload, "evidence_projection", "scope")
    return {
        "session_id": _first_non_empty(
            refs.get("session_id"),
            refs.get("session_ref"),
            payload.get("session_id"),
            task_payload.get("session_id"),
            agent_scope.get("session_id"),
            signal_scope.get("session_id"),
            evidence_scope.get("session_id"),
        ),
        "turn_id": _first_non_empty(
            refs.get("turn_id"),
            refs.get("turn_ref"),
            payload.get("turn_id"),
            task_payload.get("turn_id"),
            agent_scope.get("turn_id"),
            signal_scope.get("turn_id"),
            evidence_scope.get("turn_id"),
        ),
        "turn_run_id": _first_non_empty(
            refs.get("turn_run_id"),
            refs.get("turn_run_ref"),
            payload.get("turn_run_id"),
            agent_scope.get("turn_run_id"),
            signal_scope.get("turn_run_id"),
            evidence_scope.get("turn_run_id"),
        ),
        "task_run_id": _first_non_empty(
            refs.get("task_run_id"),
            refs.get("task_run_ref"),
            payload.get("task_run_id"),
            task_payload.get("task_run_id"),
            lifecycle_payload.get("task_run_id"),
            agent_scope.get("task_run_id"),
            signal_scope.get("task_run_id"),
            evidence_scope.get("task_run_id"),
            event.run_id if str(event.run_id or "").startswith("taskrun:") else "",
        ),
        "graph_run_id": _first_non_empty(
            refs.get("graph_run_id"),
            refs.get("graph_run_ref"),
            payload.get("graph_run_id"),
        ),
        "node_id": _first_non_empty(refs.get("node_id"), refs.get("node_ref"), payload.get("node_id")),
        "work_order_id": _first_non_empty(
            refs.get("work_order_id"),
            refs.get("work_order_ref"),
            payload.get("work_order_id"),
        ),
    }


def _runtime_event_fact_refs(event: RuntimeEvent) -> dict[str, Any]:
    refs = dict(event.refs or {})
    payload = dict(event.payload or {})
    agent_scope = _runtime_scope_payload(payload, "agent_scope")
    signal_payload = dict(payload.get("signal") or {})
    signal_scope = _runtime_scope_payload(payload, "signal", "scope")
    evidence_projection = dict(payload.get("evidence_projection") or {})
    execution_receipt = dict(payload.get("execution_receipt") or {})
    observation = dict(payload.get("observation") or {})
    observation_payload = dict(observation.get("payload") or {})
    result_envelope = dict(observation_payload.get("result_envelope") or {})
    receipt_from_observation = dict(
        observation_payload.get("execution_receipt")
        or result_envelope.get("execution_receipt")
        or {}
    )
    result = {
        "runtime_event_id": event.event_id,
        "runtime_run_id": event.run_id,
        "runtime_event_offset": int(event.offset),
        "action_request_ref": _first_non_empty(refs.get("action_request_ref"), payload.get("action_request_ref")),
        "observation_ref": _first_non_empty(refs.get("observation_ref"), payload.get("observation_ref"), observation.get("observation_id")),
        "runtime_invocation_packet_ref": _first_non_empty(refs.get("runtime_invocation_packet_ref"), payload.get("runtime_invocation_packet_ref")),
        "trace_id": _first_non_empty(refs.get("trace_id"), payload.get("trace_id")),
        "span_id": _first_non_empty(refs.get("span_id"), payload.get("span_id")),
        "agent_run_ref": _first_non_empty(
            refs.get("agent_run_ref"),
            payload.get("agent_run_ref"),
            payload.get("agent_run_id"),
            agent_scope.get("agent_run_id"),
            signal_scope.get("agent_run_id"),
        ),
        "run_cell_ref": _first_non_empty(
            refs.get("run_cell_ref"),
            payload.get("run_cell_ref"),
            payload.get("run_cell_id"),
            agent_scope.get("run_cell_id"),
            signal_scope.get("run_cell_id"),
        ),
        "parent_agent_run_ref": _first_non_empty(
            refs.get("parent_agent_run_ref"),
            payload.get("parent_agent_run_ref"),
            agent_scope.get("parent_agent_run_id"),
        ),
        "runtime_control_signal_ref": _first_non_empty(
            refs.get("runtime_control_signal_ref"),
            refs.get("signal_ref"),
            payload.get("runtime_control_signal_ref"),
            signal_payload.get("signal_id"),
        ),
        "evidence_projection_ref": _first_non_empty(
            refs.get("evidence_projection_ref"),
            payload.get("evidence_projection_ref"),
            evidence_projection.get("projection_ref"),
        ),
        "execution_id": _first_non_empty(
            refs.get("execution_id"),
            payload.get("execution_id"),
            execution_receipt.get("execution_id"),
            receipt_from_observation.get("execution_id"),
        ),
        "usage_id": _first_non_empty(refs.get("usage_id"), payload.get("usage_id")),
        "artifact_ref": _first_artifact_ref(refs, payload, observation_payload),
    }
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _runtime_scope_payload(payload: dict[str, Any], *path: str) -> dict[str, Any]:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return dict(current or {}) if isinstance(current, dict) else {}


def _first_artifact_ref(*payloads: dict[str, Any]) -> str:
    for payload in payloads:
        for key in ("artifact_ref", "artifact_refs"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (list, tuple)) and value:
                first = value[0]
                if isinstance(first, str) and first.strip():
                    return first.strip()
                if isinstance(first, dict):
                    candidate = _first_non_empty(first.get("artifact_ref"), first.get("ref"), first.get("path"))
                    if candidate:
                        return candidate
    return ""


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


