from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.events import RuntimeEvent

from .control_events import (
    RuntimeSignalEnvelope,
    RuntimeSignalScope,
    build_runtime_signal_envelope,
    runtime_signal_from_event_payload,
)
from .control_snapshot import RuntimeControlSnapshot


CONTROL_SIGNAL_PUBLISHED_EVENT = "runtime_control_signal_published"
CONTROL_SIGNAL_OBSERVED_EVENT = "runtime_control_signal_observed"
CONTROL_SIGNAL_CONSUMED_EVENT = "runtime_control_signal_consumed"
RUNTIME_EVIDENCE_PROJECTION_PUBLISHED_EVENT = "runtime_evidence_projection_published"


class RuntimeGateway:
    """Typed runtime signal gateway over RuntimeEventLog.

    The gateway records and drains control facts. It does not decide intent,
    grant permissions, execute tools, assemble prompts, or commit output.
    """

    def __init__(self, event_log: RuntimeEventLog) -> None:
        self.event_log = event_log

    def publish(
        self,
        run_id: str,
        *,
        signal_type: str,
        scope: RuntimeSignalScope,
        source_authority: str,
        signal_id: str = "",
        payload: dict[str, Any] | None = None,
        visibility: str = "runtime_private",
        causation_id: str = "",
        correlation_id: str = "",
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        with _event_log_write_guard(self.event_log):
            normalized_run_id = str(run_id or "").strip() or _run_id_from_scope(scope)
            normalized_signal_id = str(signal_id or "").strip()
            if normalized_signal_id:
                for event in self.event_log.list_events(normalized_run_id):
                    if event.event_type != CONTROL_SIGNAL_PUBLISHED_EVENT:
                        continue
                    signal = runtime_signal_from_event_payload(dict(event.payload or {}))
                    if signal is not None and signal.signal_id == normalized_signal_id:
                        if signal.signal_type != str(signal_type or "").strip():
                            raise ValueError("RuntimeGateway signal_id conflict across signal types")
                        return event
            envelope = build_runtime_signal_envelope(
                signal_type=signal_type,
                scope=scope,
                source_authority=source_authority,
                signal_id=normalized_signal_id,
                payload=payload,
                visibility=visibility,  # type: ignore[arg-type]
                causation_id=causation_id,
                correlation_id=correlation_id,
            )
            return self.event_log.append(
                normalized_run_id,
                CONTROL_SIGNAL_PUBLISHED_EVENT,  # type: ignore[arg-type]
                payload={"signal": envelope.to_dict()},
                refs={**dict(refs or {}), "signal_ref": envelope.signal_id},
            )

    def publish_evidence_projection(
        self,
        run_id: str,
        *,
        projection_ref: str,
        scope: RuntimeSignalScope,
        payload: dict[str, Any],
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        with _event_log_write_guard(self.event_log):
            normalized_run_id = str(run_id or "").strip() or _run_id_from_scope(scope)
            normalized_ref = str(projection_ref or "").strip()
            if not normalized_ref:
                raise ValueError("publish_evidence_projection requires projection_ref")
            for event in self.event_log.list_events(normalized_run_id):
                if event.event_type != RUNTIME_EVIDENCE_PROJECTION_PUBLISHED_EVENT:
                    continue
                if str(dict(event.refs or {}).get("evidence_projection_ref") or "") == normalized_ref:
                    return event
            event_payload = {
                "evidence_projection": {
                    **dict(payload or {}),
                    "projection_ref": normalized_ref,
                    "scope": scope.to_dict(),
                    "event_family": "runtime_evidence_projection",
                }
            }
            return self.event_log.append(
                normalized_run_id,
                RUNTIME_EVIDENCE_PROJECTION_PUBLISHED_EVENT,  # type: ignore[arg-type]
                payload=event_payload,
                refs={
                    **dict(refs or {}),
                    "evidence_projection_ref": normalized_ref,
                    "runtime_invocation_packet_ref": str(dict(payload or {}).get("packet_id") or ""),
                },
            )

    def mark_consumed(
        self,
        run_id: str,
        *,
        signal: RuntimeSignalEnvelope,
        consumed_by: str,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        with _event_log_write_guard(self.event_log):
            normalized_run_id = str(run_id or "").strip() or _run_id_from_scope(signal.scope)
            events = self.event_log.list_events(normalized_run_id)
            canonical_signal = _published_signal_for_closure(events, signal)
            if canonical_signal is None:
                raise ValueError("RuntimeGateway cannot consume a signal without a canonical published source")
            existing_consumed = _consumed_signal_event_by_id(events, canonical_signal.signal_id)
            if existing_consumed is not None:
                return existing_consumed
            consumed = build_runtime_signal_envelope(
                signal_id=canonical_signal.signal_id,
                signal_type=canonical_signal.signal_type,
                scope=canonical_signal.scope,
                source_authority=canonical_signal.source_authority,
                payload={**dict(canonical_signal.payload or {}), **dict(payload or {})},
                visibility=canonical_signal.visibility,
                consumption_state="consumed",
                consumed_by=consumed_by,
                causation_id=canonical_signal.causation_id,
                correlation_id=canonical_signal.correlation_id,
                created_at=canonical_signal.created_at,
            )
            return self.event_log.append(
                normalized_run_id,
                CONTROL_SIGNAL_CONSUMED_EVENT,  # type: ignore[arg-type]
                payload={"signal": consumed.to_dict()},
                refs={**dict(refs or {}), "signal_ref": canonical_signal.signal_id},
            )

    def mark_observed(
        self,
        run_id: str,
        *,
        signal: RuntimeSignalEnvelope,
        observed_by: str,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        with _event_log_write_guard(self.event_log):
            normalized_run_id = str(run_id or "").strip() or _run_id_from_scope(signal.scope)
            events = self.event_log.list_events(normalized_run_id)
            canonical_signal = _published_signal_for_closure(events, signal)
            if canonical_signal is None:
                raise ValueError("RuntimeGateway cannot observe a signal without a canonical published source")
            existing_closed = _closed_signal_event_by_id(events, canonical_signal.signal_id)
            if existing_closed is not None:
                return existing_closed
            observed = build_runtime_signal_envelope(
                signal_id=canonical_signal.signal_id,
                signal_type=canonical_signal.signal_type,
                scope=canonical_signal.scope,
                source_authority=canonical_signal.source_authority,
                payload={**dict(canonical_signal.payload or {}), **dict(payload or {})},
                visibility=canonical_signal.visibility,
                consumption_state="observed",
                consumed_by=observed_by,
                causation_id=canonical_signal.causation_id,
                correlation_id=canonical_signal.correlation_id,
                created_at=canonical_signal.created_at,
            )
            return self.event_log.append(
                normalized_run_id,
                CONTROL_SIGNAL_OBSERVED_EVENT,  # type: ignore[arg-type]
                payload={"signal": observed.to_dict()},
                refs={**dict(refs or {}), "signal_ref": canonical_signal.signal_id},
            )

    def signal_by_id(self, run_id: str, *, signal_id: str) -> RuntimeSignalEnvelope | None:
        wanted = str(signal_id or "").strip()
        if not wanted:
            return None
        return _published_signal_by_id(self.event_log.list_events(run_id), wanted)

    def can_consume_by_id(self, run_id: str, *, signal_id: str) -> bool:
        normalized_run_id = str(run_id or "").strip()
        normalized_signal_id = str(signal_id or "").strip()
        if not normalized_run_id or not normalized_signal_id:
            return False
        events = self.event_log.list_events(normalized_run_id)
        if normalized_signal_id in _consumed_signal_ids(events):
            return False
        return _published_signal_by_id(events, normalized_signal_id) is not None

    def mark_observed_by_id(
        self,
        run_id: str,
        *,
        signal_id: str,
        observed_by: str,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent | None:
        normalized_run_id = str(run_id or "").strip()
        normalized_signal_id = str(signal_id or "").strip()
        if not normalized_run_id or not normalized_signal_id:
            return None
        events = self.event_log.list_events(normalized_run_id)
        if normalized_signal_id in _closed_signal_ids(events):
            return None
        signal = _published_signal_by_id(events, normalized_signal_id)
        if signal is None:
            return None
        return self.mark_observed(
            normalized_run_id,
            signal=signal,
            observed_by=observed_by,
            payload=payload,
            refs=refs,
        )

    def mark_consumed_by_id(
        self,
        run_id: str,
        *,
        signal_id: str,
        consumed_by: str,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> RuntimeEvent | None:
        normalized_run_id = str(run_id or "").strip()
        normalized_signal_id = str(signal_id or "").strip()
        if not normalized_run_id or not normalized_signal_id:
            return None
        events = self.event_log.list_events(normalized_run_id)
        if normalized_signal_id in _consumed_signal_ids(events):
            return None
        signal = _published_signal_by_id(events, normalized_signal_id)
        if signal is None:
            return None
        return self.mark_consumed(
            normalized_run_id,
            signal=signal,
            consumed_by=consumed_by,
            payload=payload,
            refs=refs,
        )

    def drain(
        self,
        run_id: str,
        *,
        scope: RuntimeSignalScope | None = None,
        after_offset: int = -1,
        signal_types: set[str] | tuple[str, ...] | list[str] | None = None,
    ) -> RuntimeControlSnapshot:
        events = self.event_log.list_events(run_id)
        wanted_types = {str(item) for item in list(signal_types or []) if str(item).strip()}
        closed_ids = _closed_signal_ids(events)
        pending: list[RuntimeSignalEnvelope] = []
        source_events: list[RuntimeEvent] = []
        cursor_offset = int(after_offset or -1)
        for event in events:
            cursor_offset = max(cursor_offset, int(event.offset))
            if int(event.offset) <= int(after_offset or -1):
                continue
            if event.event_type != CONTROL_SIGNAL_PUBLISHED_EVENT:
                continue
            signal = runtime_signal_from_event_payload(dict(event.payload or {}))
            if signal is None:
                continue
            if signal.signal_id in closed_ids:
                continue
            if wanted_types and signal.signal_type not in wanted_types:
                continue
            if scope is not None and not _scope_matches(signal.scope, scope):
                continue
            pending.append(signal)
            source_events.append(event)
        return RuntimeControlSnapshot(
            run_id=run_id,
            scope=scope or RuntimeSignalScope(),
            pending_signals=tuple(pending),
            source_events=tuple(source_events),
            cursor_offset=cursor_offset,
        )


def _closed_signal_ids(events: list[RuntimeEvent]) -> set[str]:
    published_facts = _published_signal_facts_by_id(events)
    closed: set[str] = set()
    for event in events:
        if event.event_type not in {CONTROL_SIGNAL_OBSERVED_EVENT, CONTROL_SIGNAL_CONSUMED_EVENT}:
            continue
        signal = runtime_signal_from_event_payload(dict(event.payload or {}))
        if signal is not None and _is_closure_for_published_signal(event, signal, published_facts):
            closed.add(signal.signal_id)
    return closed


def _published_signal_facts_by_id(events: list[RuntimeEvent]) -> dict[str, tuple[int, str]]:
    facts: dict[str, tuple[int, str]] = {}
    for event in events:
        if event.event_type != CONTROL_SIGNAL_PUBLISHED_EVENT:
            continue
        signal = runtime_signal_from_event_payload(dict(event.payload or {}))
        if signal is None or signal.signal_id in facts:
            continue
        facts[signal.signal_id] = (int(event.offset), signal.signal_type)
    return facts


def _published_signal_for_closure(
    events: list[RuntimeEvent],
    signal: RuntimeSignalEnvelope,
) -> RuntimeSignalEnvelope | None:
    published = _published_signal_by_id(events, signal.signal_id)
    if published is None or published.signal_type != signal.signal_type:
        return None
    return published


def _is_closure_for_published_signal(
    event: RuntimeEvent,
    signal: RuntimeSignalEnvelope,
    published_facts: dict[str, tuple[int, str]],
) -> bool:
    published = published_facts.get(signal.signal_id)
    if published is None:
        return False
    published_offset, published_type = published
    return signal.signal_type == published_type and int(event.offset) > published_offset


def _closed_signal_event_by_id(events: list[RuntimeEvent], signal_id: str) -> RuntimeEvent | None:
    return _closure_signal_event_by_id(
        events,
        signal_id=signal_id,
        event_types={CONTROL_SIGNAL_OBSERVED_EVENT, CONTROL_SIGNAL_CONSUMED_EVENT},
    )


def _consumed_signal_event_by_id(events: list[RuntimeEvent], signal_id: str) -> RuntimeEvent | None:
    return _closure_signal_event_by_id(
        events,
        signal_id=signal_id,
        event_types={CONTROL_SIGNAL_CONSUMED_EVENT},
    )


def _closure_signal_event_by_id(
    events: list[RuntimeEvent],
    *,
    signal_id: str,
    event_types: set[str],
) -> RuntimeEvent | None:
    wanted = str(signal_id or "").strip()
    if not wanted:
        return None
    published_facts = _published_signal_facts_by_id(events)
    for event in events:
        if event.event_type not in event_types:
            continue
        signal = runtime_signal_from_event_payload(dict(event.payload or {}))
        if signal is None or signal.signal_id != wanted:
            continue
        if _is_closure_for_published_signal(event, signal, published_facts):
            return event
    return None


def _published_signal_by_id(events: list[RuntimeEvent], signal_id: str) -> RuntimeSignalEnvelope | None:
    wanted = str(signal_id or "").strip()
    if not wanted:
        return None
    for event in events:
        if event.event_type != CONTROL_SIGNAL_PUBLISHED_EVENT:
            continue
        signal = runtime_signal_from_event_payload(dict(event.payload or {}))
        if signal is not None and signal.signal_id == wanted:
            return signal
    return None


def _consumed_signal_ids(events: list[RuntimeEvent]) -> set[str]:
    published_facts = _published_signal_facts_by_id(events)
    consumed: set[str] = set()
    for event in events:
        if event.event_type != CONTROL_SIGNAL_CONSUMED_EVENT:
            continue
        signal = runtime_signal_from_event_payload(dict(event.payload or {}))
        if signal is not None and _is_closure_for_published_signal(event, signal, published_facts):
            consumed.add(signal.signal_id)
    return consumed


def _scope_matches(candidate: RuntimeSignalScope, expected: RuntimeSignalScope) -> bool:
    candidate_payload = candidate.to_dict()
    expected_payload = expected.to_dict()
    for key, expected_value in expected_payload.items():
        if expected_value and str(candidate_payload.get(key) or "") != str(expected_value):
            return False
    return True


def _run_id_from_scope(scope: RuntimeSignalScope) -> str:
    return scope.task_run_id or scope.turn_run_id or scope.turn_id or scope.session_id or "runtime"


def _event_log_write_guard(event_log: RuntimeEventLog) -> Any:
    lock = getattr(event_log, "_write_lock", None)
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        return lock
    return nullcontext()
