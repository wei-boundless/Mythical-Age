from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from harness.runtime.control_events import RuntimeSignalScope

from .user_submission import UserSubmission, build_user_submission
from .work_rollout import append_work_rollout_item


SteerKind = Literal["instruction", "correction", "acceptance_change", "priority_change", "status_question"]
SteerPriority = Literal["normal", "high", "blocking"]
SteerState = Literal["pending", "included_in_packet", "consumed", "rejected", "superseded"]


@dataclass(frozen=True, slots=True)
class ActiveTaskSteer:
    steer_id: str
    submission_ref: str
    session_id: str
    task_run_id: str
    expected_task_run_id: str
    expected_executor_epoch: int
    steer_kind: SteerKind
    content: str
    priority: SteerPriority
    consumption_state: SteerState
    created_at: float
    editor_context: dict[str, Any] = field(default_factory=dict)
    included_packet_ref: str = ""
    consumed_action_ref: str = ""
    authority: str = "harness.loop.active_task_steer"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.active_task_steer":
            raise ValueError("ActiveTaskSteer authority must be harness.loop.active_task_steer")
        if not self.steer_id:
            raise ValueError("ActiveTaskSteer requires steer_id")
        if not self.task_run_id:
            raise ValueError("ActiveTaskSteer requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_active_task_steer(
    runtime_host: Any,
    task_run_id: str,
    *,
    content: str,
    turn_id: str = "",
    intent: str = "append_instruction_to_active_work",
    submission: UserSubmission | None = None,
    steer_kind: SteerKind = "instruction",
    priority: SteerPriority = "high",
    editor_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return {"ok": False, "error": "task_run_not_found", "task_run_id": task_run_id}
    instruction = str(content or "").strip()
    if not instruction:
        return {"ok": False, "error": "active_task_steer_empty", "task_run_id": task_run_id}
    now = time.time()
    submission = submission or build_user_submission(
        session_id=str(getattr(task_run, "session_id", "") or ""),
        turn_id=turn_id,
        content=instruction,
        kind="user_input",
    )
    executor_epoch = int(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_epoch") or 0)
    steer = ActiveTaskSteer(
        steer_id=f"steer:{task_run_id}:{uuid.uuid4().hex[:12]}",
        submission_ref=submission.submission_id,
        session_id=str(getattr(task_run, "session_id", "") or ""),
        task_run_id=task_run_id,
        expected_task_run_id=task_run_id,
        expected_executor_epoch=executor_epoch,
        steer_kind=steer_kind,
        content=instruction,
        priority=priority,
        consumption_state="pending",
        created_at=now,
        editor_context=dict(editor_context or {}),
    )
    signal_event = _publish_active_task_steer_signal(
        runtime_host,
        task_run=task_run,
        steer=steer,
        submission=submission,
        turn_id=turn_id,
        intent=intent,
    )
    if signal_event is None:
        return {"ok": False, "accepted": False, "error": "runtime_gateway_control_signal_unavailable", "task_run_id": task_run_id}
    runtime_host.runtime_objects.put_object("user_submission", submission.submission_id, submission.to_dict())
    runtime_host.runtime_objects.put_object("active_task_steer", steer.steer_id, steer.to_dict())
    runtime_host.event_log.append(
        task_run_id,
        "user_submission_recorded",
        payload={"submission": submission.to_dict(), "target": {"task_run_id": task_run_id, "kind": "active_task_steer"}},
        refs={
            "task_run_ref": task_run_id,
            "turn_ref": str(turn_id or ""),
            "submission_ref": submission.submission_id,
        },
    )
    event = runtime_host.event_log.append(
        task_run_id,
        "active_task_steer_recorded",
        payload={"submission": submission.to_dict(), "steer": steer.to_dict(), "intent": intent},
        refs={
            "task_run_ref": task_run_id,
            "turn_ref": str(turn_id or ""),
            "submission_ref": submission.submission_id,
            "steer_ref": steer.steer_id,
        },
    )
    pending_count = len(list_pending_task_steers(runtime_host, task_run_id))
    updated = replace(
        task_run,
        updated_at=event.created_at or now,
        latest_event_offset=event.offset,
        diagnostics={
            **dict(getattr(task_run, "diagnostics", {}) or {}),
            "latest_step": "active_task_steer_recorded",
            "latest_step_status": str(getattr(task_run, "status", "") or "running"),
            "latest_step_summary": "",
            "pending_user_steer_count": pending_count,
            "latest_user_steer_ref": steer.steer_id,
        },
    )
    runtime_host.state_index.upsert_task_run(updated)
    append_work_rollout_item(
        runtime_host,
        task_run=updated,
        item_type="user_instruction",
        title="用户补充要求",
        status=str(getattr(updated, "status", "") or "running"),
        summary="",
        agent_brief_output=instruction,
        event_offset=event.offset,
        refs={"steer_ref": steer.steer_id, "submission_ref": submission.submission_id, "turn_ref": str(turn_id or "")},
        payload={"user_instruction": instruction, "intent": intent, "steer": steer.to_dict()},
    )
    return {
        "ok": True,
        "accepted": True,
        "task_run": updated.to_dict(),
        "submission": submission.to_dict(),
        "steer": steer.to_dict(),
        "event": event.to_dict(),
    }


def _publish_active_task_steer_signal(
    runtime_host: Any,
    *,
    task_run: Any,
    steer: ActiveTaskSteer,
    submission: UserSubmission,
    turn_id: str,
    intent: str,
) -> Any | None:
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    publisher = getattr(runtime_gateway, "publish", None)
    if not callable(publisher):
        return None
    task_run_id = str(steer.task_run_id or getattr(task_run, "task_run_id", "") or "").strip()
    if not task_run_id:
        return None
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    agent_scope = dict(diagnostics.get("agent_run_scope") or {})
    try:
        return publisher(
            task_run_id,
            signal_type="control.steer.recorded",
            signal_id=f"rtsig:active_task_steer:{steer.steer_id}",
            scope=RuntimeSignalScope(
                session_id=str(steer.session_id or getattr(task_run, "session_id", "") or ""),
                agent_run_id=str(agent_scope.get("agent_run_id") or ""),
                run_cell_id=str(agent_scope.get("run_cell_id") or ""),
                turn_id=str(turn_id or ""),
                turn_run_id=str(agent_scope.get("turn_run_id") or ""),
                task_run_id=task_run_id,
            ),
            source_authority="harness.loop.active_task_steer",
            payload={
                "signal_kind": "active_task_steer",
                "task_run_id": task_run_id,
                "turn_id": str(turn_id or ""),
                "steer_ref": steer.steer_id,
                "submission_ref": submission.submission_id,
                "intent": str(intent or ""),
                "steer_kind": steer.steer_kind,
                "priority": steer.priority,
                "expected_executor_epoch": int(steer.expected_executor_epoch or 0),
                "consumption_state": steer.consumption_state,
            },
            visibility="runtime_private",
            refs={
                "task_run_ref": task_run_id,
                "turn_ref": str(turn_id or ""),
                "submission_ref": submission.submission_id,
                "steer_ref": steer.steer_id,
            },
        )
    except Exception:
        return None


def list_task_steers(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    steers: dict[str, dict[str, Any]] = {}
    for event in runtime_host.event_log.list_events(task_run_id):
        payload = dict(getattr(event, "payload", {}) or {})
        for key in ("steer", "active_task_steer"):
            value = payload.get(key)
            if isinstance(value, dict) and str(value.get("steer_id") or ""):
                steers[str(value.get("steer_id"))] = dict(value)
    return sorted(steers.values(), key=lambda item: float(item.get("created_at") or 0.0))


def list_pending_task_steers(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    return [
        steer
        for steer in list_task_steers(runtime_host, task_run_id)
        if str(steer.get("consumption_state") or "") in {"pending", "included_in_packet"}
    ]


def mark_task_steers_included(runtime_host: Any, task_run_id: str, *, steer_ids: list[str], packet_ref: str) -> list[dict[str, Any]]:
    return _transition_task_steers(
        runtime_host,
        task_run_id,
        steer_ids=steer_ids,
        state="included_in_packet",
        packet_ref=packet_ref,
        action_ref="",
        event_type="active_task_steer_included",
    )


def mark_task_steers_consumed(runtime_host: Any, task_run_id: str, *, steer_ids: list[str], action_ref: str) -> list[dict[str, Any]]:
    return _transition_task_steers(
        runtime_host,
        task_run_id,
        steer_ids=steer_ids,
        state="consumed",
        packet_ref="",
        action_ref=action_ref,
        event_type="active_task_steer_consumed",
    )


def mark_task_steers_rejected(runtime_host: Any, task_run_id: str, *, steer_ids: list[str], action_ref: str) -> list[dict[str, Any]]:
    return _transition_task_steers(
        runtime_host,
        task_run_id,
        steer_ids=steer_ids,
        state="rejected",
        packet_ref="",
        action_ref=action_ref,
        event_type="active_task_steer_rejected",
    )


def mark_task_steers_superseded(runtime_host: Any, task_run_id: str, *, steer_ids: list[str], action_ref: str) -> list[dict[str, Any]]:
    return _transition_task_steers(
        runtime_host,
        task_run_id,
        steer_ids=steer_ids,
        state="superseded",
        packet_ref="",
        action_ref=action_ref,
        event_type="active_task_steer_superseded",
    )


def _transition_task_steers(
    runtime_host: Any,
    task_run_id: str,
    *,
    steer_ids: list[str],
    state: SteerState,
    packet_ref: str,
    action_ref: str,
    event_type: str,
) -> list[dict[str, Any]]:
    wanted = {str(item or "").strip() for item in steer_ids if str(item or "").strip()}
    if not wanted:
        return []
    changed: list[dict[str, Any]] = []
    current = {str(item.get("steer_id") or ""): dict(item) for item in list_task_steers(runtime_host, task_run_id)}
    for steer_id in wanted:
        steer = current.get(steer_id)
        if not steer:
            continue
        current_state = str(steer.get("consumption_state") or "pending")
        if current_state in {"consumed", "rejected", "superseded"} and current_state != state:
            continue
        if state == "included_in_packet" and current_state not in {"pending", "included_in_packet"}:
            continue
        updated = {
            **steer,
            "consumption_state": state,
            "included_packet_ref": packet_ref or str(steer.get("included_packet_ref") or ""),
            "consumed_action_ref": action_ref or str(steer.get("consumed_action_ref") or ""),
        }
        runtime_host.runtime_objects.put_object("active_task_steer", steer_id, updated)
        transition = _steer_transition_payload(updated=updated, state=state)
        event = runtime_host.event_log.append(
            task_run_id,
            event_type,
            payload={"steer": updated, "steer_transition": transition, "summary": transition["summary"]},
            refs={"task_run_ref": task_run_id, "steer_ref": steer_id, "runtime_invocation_packet_ref": packet_ref, "action_request_ref": action_ref},
        )
        _append_steer_rollout_item(runtime_host, task_run_id=task_run_id, event_offset=event.offset, transition=transition, steer=updated)
        changed.append(updated)
    _refresh_pending_steer_diagnostics(runtime_host, task_run_id)
    return changed


def _refresh_pending_steer_diagnostics(runtime_host: Any, task_run_id: str) -> None:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return
    pending_count = len(list_pending_task_steers(runtime_host, task_run_id))
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    latest_transition = _latest_steer_transition(runtime_host, task_run_id)
    runtime_host.state_index.upsert_task_run(
        replace(
            task_run,
            diagnostics={
                **diagnostics,
                "pending_user_steer_count": pending_count,
                **(
                    {
                        "latest_step": str(latest_transition.get("step") or diagnostics.get("latest_step") or ""),
                        "latest_step_status": str(latest_transition.get("status") or diagnostics.get("latest_step_status") or ""),
                        "latest_step_summary": str(latest_transition.get("summary") or diagnostics.get("latest_step_summary") or ""),
                    }
                    if latest_transition
                    else {}
                ),
            },
        )
    )


def _steer_transition_payload(*, updated: dict[str, Any], state: SteerState) -> dict[str, Any]:
    state_map = {
        "included_in_packet": {
            "step": "active_task_steer_included",
            "title": "正在按补充要求重规划",
            "summary": "补充要求已进入下一回合处理队列。",
            "status": "running",
            "phase": "handling",
        },
        "consumed": {
            "step": "active_task_steer_consumed",
            "title": "已按补充要求继续处理",
            "summary": "补充要求已在当前处理回合纳入执行。",
            "status": "running",
            "phase": "applied",
        },
        "rejected": {
            "step": "active_task_steer_rejected",
            "title": "补充要求未被采纳",
            "summary": "补充要求已被明确拒绝或无法执行。",
            "status": "blocked",
            "phase": "rejected",
        },
        "superseded": {
            "step": "active_task_steer_superseded",
            "title": "补充要求已被后续要求覆盖",
            "summary": "较新的补充要求已经覆盖这条旧要求。",
            "status": "running",
            "phase": "superseded",
        },
    }
    base = dict(state_map.get(state) or {})
    return {
        **base,
        "steer_id": str(updated.get("steer_id") or ""),
        "content": str(updated.get("content") or ""),
        "consumption_state": state,
    }


def _append_steer_rollout_item(runtime_host: Any, *, task_run_id: str, event_offset: int, transition: dict[str, Any], steer: dict[str, Any]) -> None:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return
    append_work_rollout_item(
        runtime_host,
        task_run=task_run,
        item_type="user_instruction",
        title=str(transition.get("title") or "补充要求状态更新"),
        status=str(transition.get("status") or getattr(task_run, "status", "") or "running"),
        summary=str(transition.get("summary") or ""),
        agent_brief_output=str(steer.get("content") or ""),
        event_offset=event_offset,
        refs={"steer_ref": str(steer.get("steer_id") or "")},
        payload={"steer": steer, "steer_transition": transition},
    )


def _latest_steer_transition(runtime_host: Any, task_run_id: str) -> dict[str, Any]:
    for event in reversed(list(runtime_host.event_log.list_events(task_run_id))):
        payload = dict(getattr(event, "payload", {}) or {})
        transition = dict(payload.get("steer_transition") or {})
        if transition:
            return transition
    return {}
