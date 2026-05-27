from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .turn_models import AgentTurnRecord, AgentTurnStatus


class AgentTurnStore:
    def __init__(self, *, runtime_objects: Any, event_log: Any) -> None:
        self.runtime_objects = runtime_objects
        self.event_log = event_log

    def create(
        self,
        *,
        turn_id: str,
        session_id: str,
        agent_invocation_id: str,
        user_message: str,
        source: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> AgentTurnRecord:
        now = time.time()
        record = AgentTurnRecord(
            turn_id=turn_id,
            session_id=session_id,
            agent_invocation_id=agent_invocation_id,
            user_message=user_message,
            status="received",
            source=source,
            created_at=now,
            updated_at=now,
            diagnostics=dict(diagnostics or {}),
        )
        self._put(record)
        self.append_event(record, "agent_turn_received", status_after="received")
        return record

    def transition(
        self,
        record: AgentTurnRecord,
        status: AgentTurnStatus,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        **updates: Any,
    ) -> AgentTurnRecord:
        allowed_fields = set(AgentTurnRecord.__dataclass_fields__.keys())
        clean_updates = {key: value for key, value in updates.items() if key in allowed_fields}
        next_record = replace(
            record,
            status=status,
            updated_at=time.time(),
            **clean_updates,
        )
        self._put(next_record)
        self.append_event(next_record, event_type, status_after=status, payload=payload)
        return next_record

    def append_event(
        self,
        record: AgentTurnRecord,
        event_type: str,
        *,
        status_after: str,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ):
        return self.event_log.append(
            _event_scope(record.turn_id),
            event_type,
            payload={
                "scope": "agent_turn",
                "turn_id": record.turn_id,
                "session_id": record.session_id,
                "agent_invocation_id": record.agent_invocation_id,
                "status_after": status_after,
                "phase": record.phase,
                "status_code": record.status_code,
                "blocking_reason": record.blocking_reason,
                **dict(payload or {}),
            },
            refs={
                "turn_ref": record.turn_id,
                "agent_invocation_ref": record.agent_invocation_id,
                **dict(refs or {}),
            },
        )

    def _put(self, record: AgentTurnRecord) -> str:
        return self.runtime_objects.put_object("agent_turn", record.turn_id, record.to_dict())


def _event_scope(turn_id: str) -> str:
    return f"agent-turn:{turn_id}"
