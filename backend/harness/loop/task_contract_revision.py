from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal


RevisionKind = Literal["goal_change", "acceptance_change", "scope_change", "constraint_change", "continuation_instruction"]
RevisionStatus = Literal["pending_agent_triage", "accepted", "needs_user", "rejected"]


@dataclass(frozen=True, slots=True)
class TaskContractRevision:
    revision_id: str
    task_run_id: str
    submission_ref: str
    steer_ref: str
    revision_kind: RevisionKind
    instruction: str
    status: RevisionStatus
    proposed_goal: str = ""
    proposed_acceptance_criteria: tuple[str, ...] = ()
    impact: dict[str, Any] | None = None
    created_at: float = 0.0
    decided_action_ref: str = ""
    authority: str = "harness.loop.task_contract_revision"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.task_contract_revision":
            raise ValueError("TaskContractRevision authority must be harness.loop.task_contract_revision")
        if not self.revision_id:
            raise ValueError("TaskContractRevision requires revision_id")
        if not self.task_run_id:
            raise ValueError("TaskContractRevision requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["proposed_acceptance_criteria"] = list(self.proposed_acceptance_criteria)
        payload["impact"] = dict(self.impact or {})
        return payload


def ensure_revision_for_steer(runtime_host: Any, task_run_id: str, steer: dict[str, Any]) -> dict[str, Any] | None:
    steer_id = str(steer.get("steer_id") or "").strip()
    if not steer_id:
        return None
    existing = _revision_for_steer(runtime_host, task_run_id, steer_id)
    if existing:
        return existing
    revision = TaskContractRevision(
        revision_id=f"taskrev:{task_run_id}:{uuid.uuid4().hex[:10]}",
        task_run_id=task_run_id,
        submission_ref=str(steer.get("submission_ref") or ""),
        steer_ref=steer_id,
        revision_kind=_revision_kind_for_steer(steer),
        instruction=str(steer.get("content") or ""),
        status="pending_agent_triage",
        created_at=time.time(),
        impact={
            "invalidate_steps": [],
            "requires_user_confirmation": False,
            "source": "active_task_steer",
        },
    )
    payload = revision.to_dict()
    runtime_host.runtime_objects.put_object("task_contract_revision", revision.revision_id, payload)
    runtime_host.event_log.append(
        task_run_id,
        "task_contract_revision_recorded",
        payload={"revision": payload},
        refs={
            "task_run_ref": task_run_id,
            "revision_ref": revision.revision_id,
            "steer_ref": steer_id,
            "submission_ref": revision.submission_ref,
        },
    )
    _refresh_revision_diagnostics(runtime_host, task_run_id)
    return payload


def list_task_contract_revisions(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    revisions: dict[str, dict[str, Any]] = {}
    for event in runtime_host.event_log.list_events(task_run_id):
        payload = dict(getattr(event, "payload", {}) or {})
        revision = payload.get("revision") or payload.get("task_contract_revision")
        if isinstance(revision, dict) and str(revision.get("revision_id") or ""):
            revisions[str(revision.get("revision_id"))] = dict(revision)
    return sorted(revisions.values(), key=lambda item: float(item.get("created_at") or 0.0))


def list_active_task_contract_revisions(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    return [
        revision
        for revision in list_task_contract_revisions(runtime_host, task_run_id)
        if str(revision.get("status") or "") == "pending_agent_triage"
    ]


def apply_contract_revision_decisions(
    runtime_host: Any,
    task_run_id: str,
    *,
    decisions: list[dict[str, Any]],
    action_ref: str,
) -> list[dict[str, Any]]:
    if not decisions:
        return []
    current_by_id = {
        str(item.get("revision_id") or ""): dict(item)
        for item in list_task_contract_revisions(runtime_host, task_run_id)
    }
    current_by_steer = {
        str(item.get("steer_ref") or ""): dict(item)
        for item in current_by_id.values()
        if str(item.get("steer_ref") or "")
    }
    changed: list[dict[str, Any]] = []
    for raw_decision in decisions:
        if not isinstance(raw_decision, dict):
            continue
        status = str(raw_decision.get("status") or "").strip()
        if status not in {"accepted", "needs_user", "rejected"}:
            continue
        revision_id = str(raw_decision.get("revision_id") or "").strip()
        steer_ref = str(raw_decision.get("steer_ref") or raw_decision.get("steer_id") or "").strip()
        revision = current_by_id.get(revision_id) or current_by_steer.get(steer_ref)
        if not revision or str(revision.get("status") or "") != "pending_agent_triage":
            continue
        updated = {
            **revision,
            "status": status,
            "decided_action_ref": action_ref,
            "decision": {
                "status": status,
                "reason": str(raw_decision.get("reason") or ""),
                "requires_user_confirmation": bool(raw_decision.get("requires_user_confirmation") is True),
                "proposed_goal": str(raw_decision.get("proposed_goal") or revision.get("proposed_goal") or ""),
                "proposed_acceptance_criteria": [
                    str(item)
                    for item in list(raw_decision.get("proposed_acceptance_criteria") or revision.get("proposed_acceptance_criteria") or [])
                    if str(item)
                ],
                "authority": "harness.loop.task_contract_revision.decision",
            },
        }
        runtime_host.runtime_objects.put_object("task_contract_revision", str(updated.get("revision_id") or ""), updated)
        runtime_host.event_log.append(
            task_run_id,
            "task_contract_revision_decided",
            payload={"revision": updated},
            refs={
                "task_run_ref": task_run_id,
                "revision_ref": str(updated.get("revision_id") or ""),
                "steer_ref": str(updated.get("steer_ref") or ""),
                "action_request_ref": action_ref,
            },
        )
        changed.append(updated)
    _refresh_revision_diagnostics(runtime_host, task_run_id)
    return changed


def _revision_for_steer(runtime_host: Any, task_run_id: str, steer_id: str) -> dict[str, Any]:
    for revision in list_task_contract_revisions(runtime_host, task_run_id):
        if str(revision.get("steer_ref") or "") == steer_id:
            return dict(revision)
    return {}


def _revision_kind_for_steer(steer: dict[str, Any]) -> RevisionKind:
    steer_kind = str(steer.get("steer_kind") or "").strip()
    if steer_kind in {"acceptance_change", "priority_change"}:
        return "acceptance_change"
    if steer_kind == "correction":
        return "scope_change"
    return "continuation_instruction"


def _refresh_revision_diagnostics(runtime_host: Any, task_run_id: str) -> None:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return
    active = list_active_task_contract_revisions(runtime_host, task_run_id)
    latest_revision_ref = str(active[-1].get("revision_id") or "") if active else ""
    runtime_host.state_index.upsert_task_run(
        replace(
            task_run,
            diagnostics={
                **dict(getattr(task_run, "diagnostics", {}) or {}),
                "active_contract_revision_count": len(active),
                "latest_contract_revision_ref": latest_revision_ref,
            },
        )
    )
