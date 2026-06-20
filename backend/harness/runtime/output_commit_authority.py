from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
from typing import Any, Callable

from orchestration.commit_gate import RuntimeCommitGateDecision, build_assistant_session_message_commit_decision
from runtime.output_boundary import CanonicalFinalTextDecision, canonical_output_decision_for_final_text


@dataclass(frozen=True, slots=True)
class OutputCommitRequest:
    run_id: str
    session_id: str
    content: str
    turn_id: str = ""
    turn_run_id: str = ""
    task_run_id: str = ""
    task_id: str = ""
    agent_run_id: str = ""
    run_cell_id: str = ""
    answer_channel: str = "final_answer"
    answer_source: str = "harness.runtime.output_commit_authority"
    execution_posture: str = "runtime_output_commit"
    has_tool_receipt: bool = False
    completion_state: str = ""
    terminal_reason: str = ""
    commit_source: str = "harness.runtime.output_commit_authority"
    refs: dict[str, Any] | None = None
    commit_payload_overrides: dict[str, Any] | None = None
    authority: str = "harness.runtime.output_commit_request"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.output_commit_request":
            raise ValueError("OutputCommitRequest authority must be harness.runtime.output_commit_request")
        if not self.run_id:
            raise ValueError("OutputCommitRequest requires run_id")
        if not self.session_id:
            raise ValueError("OutputCommitRequest requires session_id")


@dataclass(frozen=True, slots=True)
class PreparedOutputCommit:
    request: OutputCommitRequest
    decision: CanonicalFinalTextDecision
    commit_gate: RuntimeCommitGateDecision
    commit_gate_payload: dict[str, Any]
    commit_content: str
    authority: str = "harness.runtime.output_commit_authority.prepared"


@dataclass(frozen=True, slots=True)
class OutputCommitResult:
    decision: CanonicalFinalTextDecision
    commit_gate: RuntimeCommitGateDecision | None
    receipt: dict[str, Any]
    events: tuple[dict[str, Any], ...] = ()
    checked_event: Any | None = None
    terminal_event: Any | None = None
    authority: str = "harness.runtime.output_commit_authority.result"


class OutputCommitAuthority:
    """Single authority for assistant final text clean, commit gate, and commit events."""

    def __init__(self, runtime_host: Any | None = None) -> None:
        self.runtime_host = runtime_host

    def prepare(self, request: OutputCommitRequest) -> PreparedOutputCommit:
        decision = canonical_output_decision_for_final_text(
            request.content,
            answer_channel=request.answer_channel,
            answer_source=request.answer_source,
            execution_posture=request.execution_posture,
            has_tool_receipt=bool(request.has_tool_receipt),
            terminal_reason=request.terminal_reason,
            completion_state=request.completion_state,
        )
        commit_gate = build_assistant_session_message_commit_decision(
            session_id=request.session_id,
            task_run_id=request.task_run_id,
            task_id=request.task_id,
            turn_id=request.turn_id,
            content=decision.content,
            answer_channel=decision.answer_channel,
            answer_source=decision.answer_source,
            answer_canonical_state=decision.canonical_state,
            answer_persist_policy=decision.persist_policy,
            answer_finalization_policy=decision.finalization_policy,
            answer_fallback_reason=decision.fallback_reason,
            answer_selected_channel=decision.selected_channel,
            answer_selected_source=decision.selected_source,
            answer_leak_flags=decision.leak_flags,
            completion_state=request.completion_state,
            terminal_reason=request.terminal_reason,
            source=request.commit_source,
        )
        return PreparedOutputCommit(
            request=request,
            decision=decision,
            commit_gate=commit_gate,
            commit_gate_payload=commit_gate.to_dict(),
            commit_content=decision.content,
        )

    def record_skipped(
        self,
        request: OutputCommitRequest,
        *,
        reason: str,
        content: str = "",
        commit_gate: dict[str, Any] | None = None,
        _scope_checked: bool = False,
    ) -> OutputCommitResult:
        if not _scope_checked:
            stale_result = self._stale_scope_result(request, event_kind="output_commit")
            if stale_result is not None:
                return stale_result
        receipt, terminal_event = self._record_terminal(
            request,
            event_type="session_output_commit_skipped",
            status="skipped",
            content=content,
            commit_allowed=False,
            reason=reason,
            commit_gate=dict(commit_gate or {}),
            checked_event_offset=-1,
        )
        return OutputCommitResult(
            decision=canonical_output_decision_for_final_text(
                content,
                answer_channel=request.answer_channel,
                answer_source=request.answer_source,
                execution_posture=request.execution_posture,
                has_tool_receipt=bool(request.has_tool_receipt),
                terminal_reason=request.terminal_reason,
                completion_state=request.completion_state,
            ),
            commit_gate=None,
            receipt=receipt,
            events=tuple(item for item in (_commit_receipt_stream_event(receipt),) if item),
            terminal_event=terminal_event,
        )

    def commit_sync(
        self,
        request: OutputCommitRequest,
        *,
        committer: Callable[[dict[str, Any]], Any] | None,
        before_checked: Callable[[PreparedOutputCommit], Any] | None = None,
    ) -> OutputCommitResult:
        stale_result = self._stale_scope_result(request, event_kind="output_commit")
        if stale_result is not None:
            return stale_result
        if not callable(committer):
            return self.record_skipped(
                request,
                reason="assistant_message_committer_missing",
                content="",
                commit_gate={},
            )
        prepared = self.prepare(request)
        if callable(before_checked):
            before_checked(prepared)
        checked_event = self._record_checked(prepared)
        checked_offset = _event_offset(checked_event)
        checked_stream_event = _stream_event_from_runtime_event("session_output_commit_checked", checked_event)
        if not prepared.commit_gate.commit_allowed:
            return self._terminal_result(
                prepared,
                checked_event=checked_event,
                checked_stream_event=checked_stream_event,
                event_type="session_output_commit_skipped",
                status="skipped",
                reason=str(prepared.commit_gate.reason or "commit_gate_blocked"),
                checked_event_offset=checked_offset,
            )
        try:
            commit_payload = self._commit_payload(prepared)
            committer_result = committer(commit_payload)
            if inspect.isawaitable(committer_result):
                close = getattr(committer_result, "close", None)
                if callable(close):
                    close()
                return self._terminal_result(
                    prepared,
                    checked_event=checked_event,
                    checked_stream_event=checked_stream_event,
                    event_type="session_output_commit_failed",
                    status="failed",
                    reason="async_committer_not_supported",
                    checked_event_offset=checked_offset,
                )
        except Exception as exc:
            return self._terminal_result(
                prepared,
                checked_event=checked_event,
                checked_stream_event=checked_stream_event,
                event_type="session_output_commit_failed",
                status="failed",
                reason=str(exc) or "assistant_message_commit_failed",
                checked_event_offset=checked_offset,
            )
        return self._terminal_result(
            prepared,
            checked_event=checked_event,
            checked_stream_event=checked_stream_event,
            event_type="session_output_commit_ack",
            status="committed",
            reason="committed",
            checked_event_offset=checked_offset,
            committer_result=committer_result,
        )

    async def commit_async(
        self,
        request: OutputCommitRequest,
        *,
        committer: Callable[[str, dict[str, Any]], Any] | None,
        before_checked: Callable[[PreparedOutputCommit], Any] | None = None,
    ) -> OutputCommitResult:
        stale_result = self._stale_scope_result(request, event_kind="output_commit")
        if stale_result is not None:
            return stale_result
        if not callable(committer):
            return self.record_skipped(
                request,
                reason="assistant_message_committer_missing",
                content="",
                commit_gate={},
            )
        prepared = self.prepare(request)
        if callable(before_checked):
            before_checked(prepared)
        checked_event = self._record_checked(prepared)
        checked_offset = _event_offset(checked_event)
        checked_stream_event = _stream_event_from_runtime_event("session_output_commit_checked", checked_event)
        if not prepared.commit_gate.commit_allowed:
            return self._terminal_result(
                prepared,
                checked_event=checked_event,
                checked_stream_event=checked_stream_event,
                event_type="session_output_commit_skipped",
                status="skipped",
                reason=str(prepared.commit_gate.reason or "commit_gate_blocked"),
                checked_event_offset=checked_offset,
            )
        try:
            commit_payload = self._commit_payload(prepared)
            maybe_result = committer(request.session_id, commit_payload)
            committer_result = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        except Exception as exc:
            return self._terminal_result(
                prepared,
                checked_event=checked_event,
                checked_stream_event=checked_stream_event,
                event_type="session_output_commit_failed",
                status="failed",
                reason=str(exc) or "assistant_message_commit_failed",
                checked_event_offset=checked_offset,
            )
        return self._terminal_result(
            prepared,
            checked_event=checked_event,
            checked_stream_event=checked_stream_event,
            event_type="session_output_commit_ack",
            status="committed",
            reason="committed",
            checked_event_offset=checked_offset,
            committer_result=committer_result,
        )

    def _commit_payload(self, prepared: PreparedOutputCommit) -> dict[str, Any]:
        payload = dict(prepared.commit_gate.commit_candidate.payload)
        payload.update(dict(prepared.request.commit_payload_overrides or {}))
        if prepared.request.agent_run_id:
            payload["agent_run_id"] = prepared.request.agent_run_id
        if prepared.request.run_cell_id:
            payload["run_cell_id"] = prepared.request.run_cell_id
        return payload

    def _stale_scope_result(self, request: OutputCommitRequest, *, event_kind: str) -> OutputCommitResult | None:
        runtime_host = self.runtime_host
        supervisor = getattr(runtime_host, "agent_run_supervisor", None) if runtime_host is not None else None
        checker = getattr(supervisor, "current_scope_status_for_task_run", None)
        task_run_id = str(request.task_run_id or "").strip()
        agent_run_id = str(request.agent_run_id or "").strip()
        run_cell_id = str(request.run_cell_id or "").strip()
        if not task_run_id or not run_cell_id or not callable(checker):
            return None
        scope_status = dict(checker(task_run_id, agent_run_id=agent_run_id, run_cell_id=run_cell_id) or {})
        if scope_status.get("accepted") is True:
            return None
        recorder = getattr(supervisor, "record_late_event_rejected", None)
        reason = str(scope_status.get("reason") or "stale_agent_cell").strip()
        if callable(recorder):
            recorder(
                task_run_id=task_run_id,
                agent_run_id=agent_run_id,
                run_cell_id=run_cell_id,
                event_kind=event_kind,
                reason=reason,
                payload={
                    "turn_id": request.turn_id,
                    "turn_run_id": request.turn_run_id,
                    "task_id": request.task_id,
                    "content_sha256": _text_sha256(request.content),
                    "completion_state": request.completion_state,
                    "terminal_reason": request.terminal_reason,
                    "answer_source": request.answer_source,
                },
                refs=dict(request.refs or {}),
                scope_status=scope_status,
            )
        return self.record_skipped(
            request,
            reason=f"agent_cell_{reason}",
            content="",
            commit_gate={"scope_status": scope_status},
            _scope_checked=True,
        )

    def _record_checked(self, prepared: PreparedOutputCommit) -> Any | None:
        runtime_host = self.runtime_host
        if runtime_host is None:
            return None
        request = prepared.request
        return runtime_host.event_log.append(
            request.run_id,
            "session_output_commit_checked",
            payload={
                "session_id": request.session_id,
                "turn_id": request.turn_id,
                "turn_run_id": request.turn_run_id,
                "task_run_id": request.task_run_id,
                "task_id": request.task_id,
                "agent_run_id": request.agent_run_id,
                "run_cell_id": request.run_cell_id,
                "commit_allowed": bool(prepared.commit_gate.commit_allowed),
                "reason": str(prepared.commit_gate.reason or ""),
                "answer_channel": prepared.decision.answer_channel,
                "answer_source": prepared.decision.answer_source,
                "answer_canonical_state": prepared.decision.canonical_state,
                "answer_persist_policy": prepared.decision.persist_policy,
                "answer_finalization_policy": prepared.decision.finalization_policy,
                "content_sha256": _text_sha256(prepared.commit_content),
                "commit_gate": prepared.commit_gate_payload,
                "authority": "harness.session_output_commit",
            },
            refs=dict(request.refs or {}),
        )

    def _terminal_result(
        self,
        prepared: PreparedOutputCommit,
        *,
        checked_event: Any | None,
        checked_stream_event: dict[str, Any],
        event_type: str,
        status: str,
        reason: str,
        checked_event_offset: int,
        committer_result: Any = None,
    ) -> OutputCommitResult:
        receipt, terminal_event = self._record_terminal(
            prepared.request,
            event_type=event_type,
            status=status,
            content=prepared.commit_content,
            commit_allowed=bool(prepared.commit_gate.commit_allowed),
            reason=reason,
            commit_gate=prepared.commit_gate_payload,
            checked_event_offset=checked_event_offset,
            committer_result=committer_result,
        )
        return OutputCommitResult(
            decision=prepared.decision,
            commit_gate=prepared.commit_gate,
            receipt=receipt,
            events=tuple(item for item in (checked_stream_event, _commit_receipt_stream_event(receipt)) if item),
            checked_event=checked_event,
            terminal_event=terminal_event,
        )

    def _record_terminal(
        self,
        request: OutputCommitRequest,
        *,
        event_type: str,
        status: str,
        content: str,
        commit_allowed: bool,
        reason: str,
        commit_gate: dict[str, Any],
        checked_event_offset: int = -1,
        committer_result: Any = None,
    ) -> tuple[dict[str, Any], Any | None]:
        normalized_status = str(status or "").strip() or "failed"
        normalized_reason = str(reason or normalized_status).strip()
        payload = {
            "session_id": str(request.session_id or ""),
            "turn_id": str(request.turn_id or ""),
            "turn_run_id": str(request.turn_run_id or ""),
            "task_run_id": str(request.task_run_id or ""),
            "task_id": str(request.task_id or ""),
            "agent_run_id": str(request.agent_run_id or ""),
            "run_cell_id": str(request.run_cell_id or ""),
            "state": normalized_status,
            "status": normalized_status,
            "commit_allowed": bool(commit_allowed),
            "reason": normalized_reason,
            "content_sha256": _text_sha256(content),
            "anchor_message_id": _assistant_anchor_message_id(
                turn_id=request.turn_id,
                committer_result=committer_result,
            ),
            "checked_event_offset": checked_event_offset,
            "committer_result": _public_committer_result(committer_result),
            "commit_gate": dict(commit_gate or {}),
            "authority": "harness.session_output_commit",
        }
        runtime_host = self.runtime_host
        if runtime_host is None:
            return {**payload, "event_type": event_type}, None
        event = runtime_host.event_log.append(
            request.run_id,
            event_type,  # type: ignore[arg-type]
            payload=payload,
            refs=dict(request.refs or {}),
        )
        return (
            {
                **payload,
                "event_type": event_type,
                "event_id": str(getattr(event, "event_id", "") or ""),
                "event_offset": _event_offset(event),
                "created_at": float(getattr(event, "created_at", 0.0) or 0.0),
                "event": event.to_dict() if hasattr(event, "to_dict") else {},
            },
            event,
        )


def _commit_receipt_stream_event(receipt: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(receipt or {})
    event_type = str(data.get("event_type") or "").strip()
    if not event_type:
        return {}
    event = data.get("event")
    if isinstance(event, dict) and event:
        return {"type": event_type, "event": dict(event)}
    payload = {key: value for key, value in data.items() if key not in {"event_type", "event"}}
    return {"type": event_type, **payload}


def _stream_event_from_runtime_event(event_type: str, event: Any) -> dict[str, Any]:
    payload = event.to_dict() if hasattr(event, "to_dict") else {}
    return {"type": event_type, "event": payload} if payload else {}


def _assistant_anchor_message_id(*, turn_id: str, committer_result: Any = None) -> str:
    result = dict(committer_result or {}) if isinstance(committer_result, dict) else {}
    appended = list(result.get("appended_messages") or [])
    for item in reversed(appended):
        if not isinstance(item, dict):
            continue
        explicit = str(item.get("id") or item.get("message_id") or "").strip()
        if explicit:
            return explicit
    normalized_turn_id = str(turn_id or "").strip()
    return f"history-message:{normalized_turn_id}:assistant" if normalized_turn_id else ""


def _public_committer_result(committer_result: Any) -> dict[str, Any]:
    if not isinstance(committer_result, dict):
        return {}
    appended = list(committer_result.get("appended_messages") or [])
    payload: dict[str, Any] = {
        "appended_message_count": len(appended),
    }
    for key in (
        "file_work_context_writeback",
        "memory_maintenance_enqueued",
        "memory_commit_state",
    ):
        if key in committer_result:
            payload[key] = committer_result.get(key)
    return payload


def _text_sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _event_offset(event: Any) -> int:
    if event is None:
        return -1
    if isinstance(event, dict):
        try:
            return int(event.get("offset", -1))
        except (TypeError, ValueError):
            return -1
    try:
        return int(getattr(event, "offset", -1))
    except (TypeError, ValueError):
        return -1
