from __future__ import annotations

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
        normalized_run_id = str(run_id or "").strip() or _run_id_from_scope(scope)
        normalized_signal_id = str(signal_id or "").strip()
        if normalized_signal_id:
            for event in self.event_log.list_events(normalized_run_id):
                if event.event_type != CONTROL_SIGNAL_PUBLISHED_EVENT:
                    continue
                signal = runtime_signal_from_event_payload(dict(event.payload or {}))
                if signal is not None and signal.signal_id == normalized_signal_id:
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
        consumed = build_runtime_signal_envelope(
            signal_id=signal.signal_id,
            signal_type=signal.signal_type,
            scope=signal.scope,
            source_authority=signal.source_authority,
            payload={**dict(signal.payload or {}), **dict(payload or {})},
            visibility=signal.visibility,
            consumption_state="consumed",
            consumed_by=consumed_by,
            causation_id=signal.causation_id,
            correlation_id=signal.correlation_id,
            created_at=signal.created_at,
        )
        return self.event_log.append(
            str(run_id or "").strip() or _run_id_from_scope(signal.scope),
            CONTROL_SIGNAL_CONSUMED_EVENT,  # type: ignore[arg-type]
            payload={"signal": consumed.to_dict()},
            refs={**dict(refs or {}), "signal_ref": signal.signal_id},
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
        observed = build_runtime_signal_envelope(
            signal_id=signal.signal_id,
            signal_type=signal.signal_type,
            scope=signal.scope,
            source_authority=signal.source_authority,
            payload={**dict(signal.payload or {}), **dict(payload or {})},
            visibility=signal.visibility,
            consumption_state="observed",
            consumed_by=observed_by,
            causation_id=signal.causation_id,
            correlation_id=signal.correlation_id,
            created_at=signal.created_at,
        )
        return self.event_log.append(
            str(run_id or "").strip() or _run_id_from_scope(signal.scope),
            CONTROL_SIGNAL_OBSERVED_EVENT,  # type: ignore[arg-type]
            payload={"signal": observed.to_dict()},
            refs={**dict(refs or {}), "signal_ref": signal.signal_id},
        )

    def signal_by_id(self, run_id: str, *, signal_id: str) -> RuntimeSignalEnvelope | None:
        wanted = str(signal_id or "").strip()
        if not wanted:
            return None
        for event in self.event_log.list_events(run_id):
            signal = runtime_signal_from_event_payload(dict(event.payload or {}))
            if signal is not None and signal.signal_id == wanted:
                return signal
        return None

    def can_consume_by_id(self, run_id: str, *, signal_id: str) -> bool:
        normalized_run_id = str(run_id or "").strip()
        normalized_signal_id = str(signal_id or "").strip()
        if not normalized_run_id or not normalized_signal_id:
            return False
        events = self.event_log.list_events(normalized_run_id)
        if normalized_signal_id in _consumed_signal_ids(events):
            return False
        for event in events:
            if event.event_type != CONTROL_SIGNAL_PUBLISHED_EVENT:
                continue
            signal = runtime_signal_from_event_payload(dict(event.payload or {}))
            if signal is not None and signal.signal_id == normalized_signal_id:
                return True
        return False

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
        signal = None
        for event in events:
            candidate = runtime_signal_from_event_payload(dict(event.payload or {}))
            if candidate is not None and candidate.signal_id == normalized_signal_id:
                signal = candidate
                break
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
        signal = None
        for event in events:
            candidate = runtime_signal_from_event_payload(dict(event.payload or {}))
            if candidate is not None and candidate.signal_id == normalized_signal_id:
                signal = candidate
                break
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
    closed: set[str] = set()
    for event in events:
        if event.event_type not in {CONTROL_SIGNAL_OBSERVED_EVENT, CONTROL_SIGNAL_CONSUMED_EVENT}:
            continue
        signal = runtime_signal_from_event_payload(dict(event.payload or {}))
        if signal is not None:
            closed.add(signal.signal_id)
    return closed


def _consumed_signal_ids(events: list[RuntimeEvent]) -> set[str]:
    consumed: set[str] = set()
    for event in events:
        if event.event_type != CONTROL_SIGNAL_CONSUMED_EVENT:
            continue
        signal = runtime_signal_from_event_payload(dict(event.payload or {}))
        if signal is not None:
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
