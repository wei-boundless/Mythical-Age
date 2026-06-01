from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from harness.loop.task_steering import create_active_task_steer


ActiveTurnState = Literal[
    "starting",
    "model_turn",
    "running_task",
    "waiting_executor",
    "waiting_user",
    "interrupting",
    "terminal",
]


@dataclass(frozen=True, slots=True)
class ActiveTurnRecord:
    session_id: str
    turn_id: str
    turn_run_id: str
    state: ActiveTurnState = "starting"
    bound_task_run_id: str = ""
    stream_run_id: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    owner_instance_id: str = ""
    steerable: bool = True
    terminal_reason: str = ""
    pending_input_refs: tuple[str, ...] = ()
    authority: str = "harness.runtime.active_turn"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.active_turn":
            raise ValueError("ActiveTurnRecord authority must be harness.runtime.active_turn")
        if not self.session_id:
            raise ValueError("ActiveTurnRecord requires session_id")
        if not self.turn_id:
            raise ValueError("ActiveTurnRecord requires turn_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pending_input_refs"] = list(self.pending_input_refs)
        return payload


@dataclass(frozen=True, slots=True)
class TurnSteerResult:
    ok: bool
    status: str
    active_turn: ActiveTurnRecord | None = None
    actual_turn_id: str = ""
    task_run_id: str = ""
    steer: dict[str, Any] | None = None
    pending_input_ref: str = ""
    message: str = ""
    authority: str = "harness.runtime.active_turn_steer_result"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "active_turn": self.active_turn.to_dict() if self.active_turn is not None else None,
            "actual_turn_id": self.actual_turn_id,
            "task_run_id": self.task_run_id,
            "steer": dict(self.steer or {}),
            "pending_input_ref": self.pending_input_ref,
            "message": self.message,
            "authority": self.authority,
        }


class ActiveTurnRegistry:
    """Owns the current active turn handle for a session.

    This registry is intentionally separate from TaskRun and RuntimeRun. TaskRun
    records task lifecycle, RuntimeRun records transport/SSE, and this object is
    the only current-turn authority.
    """

    object_kind = "active_turn"

    def __init__(self, runtime_host: Any) -> None:
        self.runtime_host = runtime_host

    def snapshot(self, session_id: str) -> ActiveTurnRecord | None:
        payload = self._read_session_payload(session_id)
        if not payload:
            return None
        record = _record_from_payload(payload)
        if record is None or record.state == "terminal":
            return None
        return record

    def start(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_run_id: str = "",
        stream_run_id: str = "",
        state: ActiveTurnState = "starting",
        steerable: bool = True,
    ) -> ActiveTurnRecord:
        current = self.snapshot(session_id)
        if current is not None and current.turn_id != turn_id:
            raise ActiveTurnConflict(current)
        now = time.time()
        record = ActiveTurnRecord(
            session_id=str(session_id or "").strip(),
            turn_id=str(turn_id or "").strip(),
            turn_run_id=str(turn_run_id or "").strip(),
            state=state,
            stream_run_id=str(stream_run_id or "").strip(),
            started_at=current.started_at if current is not None else now,
            updated_at=now,
            owner_instance_id=str(getattr(self.runtime_host, "instance_id", "") or ""),
            steerable=bool(steerable),
            bound_task_run_id=current.bound_task_run_id if current is not None else "",
            pending_input_refs=current.pending_input_refs if current is not None else (),
        )
        self._write(record)
        return record

    def bind_turn_run(self, *, session_id: str, turn_id: str, turn_run_id: str) -> ActiveTurnRecord | None:
        record = self.snapshot(session_id)
        if record is None or record.turn_id != turn_id:
            return record
        return self._update(record, turn_run_id=str(turn_run_id or "").strip(), state="model_turn")

    def bind_stream_run(self, *, session_id: str, turn_id: str, stream_run_id: str) -> ActiveTurnRecord | None:
        record = self.snapshot(session_id)
        if record is None or record.turn_id != turn_id:
            return record
        return self._update(record, stream_run_id=str(stream_run_id or "").strip())

    def bind_task_run(
        self,
        *,
        session_id: str,
        turn_id: str,
        task_run_id: str,
        state: ActiveTurnState = "waiting_executor",
    ) -> ActiveTurnRecord | None:
        record = self.snapshot(session_id)
        if record is None or record.turn_id != turn_id:
            return record
        return self._update(record, bound_task_run_id=str(task_run_id or "").strip(), state=state)

    def complete(self, *, session_id: str, expected_turn_id: str, terminal_reason: str) -> ActiveTurnRecord | None:
        record = self.snapshot(session_id)
        if record is None:
            return None
        if expected_turn_id and record.turn_id != expected_turn_id:
            raise ActiveTurnMismatch(expected=expected_turn_id, actual=record.turn_id)
        return self._update(record, state="terminal", steerable=False, terminal_reason=str(terminal_reason or "completed"))

    def complete_bound_task(self, *, session_id: str, task_run_id: str, terminal_reason: str) -> ActiveTurnRecord | None:
        record = self.snapshot(session_id)
        if record is None:
            return None
        expected_task_run_id = str(task_run_id or "").strip()
        if not expected_task_run_id or record.bound_task_run_id != expected_task_run_id:
            return record
        return self._update(record, state="terminal", steerable=False, terminal_reason=str(terminal_reason or "completed"))

    def steer(
        self,
        *,
        session_id: str,
        expected_turn_id: str,
        user_message: str,
        stream_run_id: str = "",
    ) -> TurnSteerResult:
        record = self.snapshot(session_id)
        if record is None:
            return TurnSteerResult(ok=False, status="no_active_turn", message="当前没有正在运行的任务。")
        if not expected_turn_id:
            return TurnSteerResult(
                ok=False,
                status="expected_turn_id_required",
                active_turn=record,
                actual_turn_id=record.turn_id,
                message="当前有正在运行的任务，需要携带 expected_active_turn_id。",
            )
        if record.turn_id != expected_turn_id:
            return TurnSteerResult(
                ok=False,
                status="expected_turn_mismatch",
                active_turn=record,
                actual_turn_id=record.turn_id,
                message="当前任务已变化，请刷新后重试。",
            )
        if not record.steerable:
            return TurnSteerResult(
                ok=False,
                status="active_turn_not_steerable",
                active_turn=record,
                actual_turn_id=record.turn_id,
                message="当前任务暂不能接收新的补充输入。",
            )
        if stream_run_id:
            record = self._update(record, stream_run_id=str(stream_run_id or "").strip())
        content = str(user_message or "").strip()
        if not content:
            return TurnSteerResult(ok=False, status="empty_input", active_turn=record, actual_turn_id=record.turn_id)
        if record.bound_task_run_id:
            result = create_active_task_steer(
                self.runtime_host,
                record.bound_task_run_id,
                content=content,
                turn_id=record.turn_id,
                intent="active_turn_steer",
            )
            if not result.get("ok"):
                return TurnSteerResult(
                    ok=False,
                    status=str(result.get("error") or "active_task_steer_failed"),
                    active_turn=record,
                    actual_turn_id=record.turn_id,
                    task_run_id=record.bound_task_run_id,
                    message=str(result.get("error") or ""),
                )
            return TurnSteerResult(
                ok=True,
                status="accepted",
                active_turn=record,
                actual_turn_id=record.turn_id,
                task_run_id=record.bound_task_run_id,
                steer=dict(result.get("steer") or {}),
                message="已收到，会纳入当前任务继续处理。",
            )
        pending_id = f"active-turn-input:{record.turn_id}:{uuid.uuid4().hex[:12]}"
        ref = self.runtime_host.runtime_objects.put_object(
            "active_turn_pending_input",
            pending_id,
            {
                "pending_input_id": pending_id,
                "session_id": record.session_id,
                "turn_id": record.turn_id,
                "stream_run_id": stream_run_id,
                "content": content,
                "created_at": time.time(),
                "authority": "harness.runtime.active_turn_pending_input",
            },
        )
        updated = self._update(record, pending_input_refs=(*record.pending_input_refs, ref))
        return TurnSteerResult(
            ok=True,
            status="queued",
            active_turn=updated,
            actual_turn_id=updated.turn_id,
            pending_input_ref=ref,
            message="已收到，会纳入当前处理。",
        )

    def _update(self, record: ActiveTurnRecord, **changes: Any) -> ActiveTurnRecord:
        updated = replace(record, updated_at=time.time(), **changes)
        self._write(updated)
        return updated

    def _write(self, record: ActiveTurnRecord) -> None:
        self.runtime_host.runtime_objects.put_object(self.object_kind, self._session_object_id(record.session_id), record.to_dict())

    def _read_session_payload(self, session_id: str) -> dict[str, Any]:
        ref = f"rtobj:{self.object_kind}:{self._session_object_id(session_id)}"
        try:
            return dict(self.runtime_host.runtime_objects.get_object(ref) or {})
        except Exception:
            return {}

    @staticmethod
    def _session_object_id(session_id: str) -> str:
        return "session_" + "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(session_id or ""))[:160]


class ActiveTurnConflict(RuntimeError):
    def __init__(self, active_turn: ActiveTurnRecord) -> None:
        super().__init__(f"active turn already exists: {active_turn.turn_id}")
        self.active_turn = active_turn


class ActiveTurnMismatch(RuntimeError):
    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__(f"expected active turn {expected}, actual {actual}")
        self.expected = expected
        self.actual = actual


def _record_from_payload(payload: dict[str, Any]) -> ActiveTurnRecord | None:
    try:
        return ActiveTurnRecord(
            session_id=str(payload.get("session_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            turn_run_id=str(payload.get("turn_run_id") or ""),
            state=_state(payload.get("state")),
            bound_task_run_id=str(payload.get("bound_task_run_id") or ""),
            stream_run_id=str(payload.get("stream_run_id") or ""),
            started_at=float(payload.get("started_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
            owner_instance_id=str(payload.get("owner_instance_id") or ""),
            steerable=bool(payload.get("steerable", True)),
            terminal_reason=str(payload.get("terminal_reason") or ""),
            pending_input_refs=tuple(str(item) for item in list(payload.get("pending_input_refs") or []) if str(item)),
        )
    except Exception:
        return None


def _state(value: Any) -> ActiveTurnState:
    raw = str(value or "").strip()
    if raw in {"starting", "model_turn", "running_task", "waiting_executor", "waiting_user", "interrupting", "terminal"}:
        return raw  # type: ignore[return-value]
    return "starting"
