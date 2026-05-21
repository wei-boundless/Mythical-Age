from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


MONITOR_ACTIONS = {
    "no_action",
    "notify",
    "request_user_decision",
    "request_human_review",
    "resume",
    "restart",
    "pause",
    "escalate",
}


@dataclass(frozen=True, slots=True)
class TaskGraphMonitorDecision:
    decision_id: str
    task_run_id: str
    coordination_run_id: str = ""
    monitor_node_id: str = ""
    severity: str = "info"
    action: str = "no_action"
    reason: str = "healthy"
    summary: str = ""
    observed: dict[str, Any] = field(default_factory=dict)
    recommended_control: dict[str, Any] = field(default_factory=dict)
    run_interaction_request: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "task_graph.monitor_decision"

    def __post_init__(self) -> None:
        if self.authority != "task_graph.monitor_decision":
            raise ValueError("TaskGraphMonitorDecision authority must be task_graph.monitor_decision")
        if not self.decision_id:
            raise ValueError("TaskGraphMonitorDecision requires decision_id")
        if not self.task_run_id:
            raise ValueError("TaskGraphMonitorDecision requires task_run_id")
        if self.action not in MONITOR_ACTIONS:
            raise ValueError(f"Unsupported monitor action: {self.action}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_task_graph_monitor_snapshot(
    monitor_snapshot: dict[str, Any],
    *,
    monitor_node_id: str = "",
    monitor_policy: dict[str, Any] | None = None,
    now: float | None = None,
) -> TaskGraphMonitorDecision:
    snapshot = dict(monitor_snapshot or {})
    policy = _normalize_monitor_policy(monitor_policy)
    current_time = float(now or time.time())
    task_run_id = str(snapshot.get("task_run_id") or "")
    coordination_run_id = str(snapshot.get("coordination_run_id") or "")
    runtime = dict(snapshot.get("runtime") or {})
    project = dict(snapshot.get("project") or {})
    progress = dict(snapshot.get("progress") or {})
    supervision = dict(snapshot.get("supervision") or {})
    blocker = dict(snapshot.get("blocker") or {})
    streaming = dict(snapshot.get("streaming") or {})
    state = dict(snapshot.get("state") or {})
    temporal = dict(snapshot.get("temporal") or {})
    stage_request = dict(snapshot.get("current_node_execution_request") or snapshot.get("current_stage_execution_request") or {})
    human_work_packet = dict(snapshot.get("current_human_work_packet") or stage_request.get("human_work_packet") or {})

    status = str(runtime.get("status") or "").strip()
    terminal_status = str(runtime.get("terminal_status") or "").strip()
    active_node_id = str(runtime.get("active_node_id") or "").strip()
    latest_runtime_at = max(
        _float(runtime.get("updated_at")),
        _float(runtime.get("checkpoint_updated_at")),
        _float(supervision.get("latest_event_at")),
        _float(supervision.get("last_effective_output_at")),
        _float(streaming.get("latest_chunk_at")),
    )
    stale_after = int(policy.get("stale_after_seconds") or 600)
    allowed_actions = set(policy.get("allowed_actions") or MONITOR_ACTIONS)
    running_nodes = [str(item) for item in list(state.get("running_node_ids") or []) if str(item)]
    if active_node_id and active_node_id not in running_nodes and (status in {"running", "waiting"} or stage_request):
        running_nodes.append(active_node_id)
    waiting_nodes = [str(item) for item in list(state.get("waiting_node_ids") or []) if str(item)]
    failed_nodes = [str(item) for item in list(state.get("failed_node_ids") or []) if str(item)]
    temporal_violations = [
        dict(item)
        for item in list(temporal.get("violations") or [])
        if isinstance(item, dict)
    ]

    reason = "healthy"
    severity = "info"
    action = "no_action"
    summary = "TaskGraph run is healthy."
    recommended_control: dict[str, Any] = {}
    run_interaction_request: dict[str, Any] = {}

    if temporal_violations:
        reason = str(temporal_violations[0].get("code") or "temporal_violation")
        severity = "critical"
        action = _first_allowed(("pause", "request_user_decision", "notify", "escalate"), allowed_actions)
        summary = str(temporal_violations[0].get("message") or "TaskGraph run has an out-of-timeline execution.")
        recommended_control = _control_packet(
            action=action,
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            safe_to_auto_apply=False,
            requires_human=True,
        )
    elif status in {"completed"} or terminal_status == "completed":
        reason = "completed"
        summary = "TaskGraph run has completed."
    elif status in {"failed", "aborted", "killed"} or terminal_status in {"failed", "aborted", "killed"} or failed_nodes:
        reason = "runtime_failed"
        severity = "critical"
        action = _first_allowed(("restart", "escalate", "notify"), allowed_actions)
        summary = "TaskGraph run has failed or contains failed nodes."
        recommended_control = _control_packet(
            action=action,
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            safe_to_auto_apply=False,
            requires_human=True,
        )
    elif blocker and policy.get("watch_blockers") is not False:
        reason = "blocker_present"
        severity = "error"
        action = _first_allowed(("request_user_decision", "request_human_review", "notify", "escalate"), allowed_actions)
        summary = str(blocker.get("summary") or blocker.get("reason") or "TaskGraph run has an active blocker.")
        recommended_control = _control_packet(
            action=action,
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            safe_to_auto_apply=False,
            requires_human=True,
        )
    elif human_work_packet and policy.get("watch_human_executor") is not False:
        reason = "human_executor_waiting"
        severity = "warning"
        action = _first_allowed(("request_user_decision", "notify"), allowed_actions)
        summary = str(human_work_packet.get("title") or "TaskGraph run is waiting for a human executor.")
        recommended_control = _control_packet(
            action=action,
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            safe_to_auto_apply=False,
            requires_human=True,
        )
    elif waiting_nodes and policy.get("watch_manual_gate") is not False:
        reason = "manual_gate_waiting"
        severity = "warning"
        action = _first_allowed(("request_user_decision", "request_human_review", "notify"), allowed_actions)
        summary = "TaskGraph run is waiting for manual gate review."
        recommended_control = _control_packet(
            action=action,
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            safe_to_auto_apply=False,
            requires_human=True,
        )
    elif latest_runtime_at > 0 and current_time - latest_runtime_at > stale_after and running_nodes:
        reason = "stale_runtime"
        severity = "error"
        action = _first_allowed(("resume", "notify", "escalate"), allowed_actions)
        summary = f"TaskGraph run has no effective runtime update for more than {stale_after} seconds."
        recommended_control = _control_packet(
            action=action,
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            safe_to_auto_apply=action == "resume",
            requires_human=action != "resume",
        )
    elif stage_request and policy.get("watch_runtime_status") is not False and status in {"running", "waiting"}:
        reason = "active_stage_observed"
        summary = "TaskGraph run has an active stage execution request."

    observed = {
        "runtime_status": status,
        "terminal_status": terminal_status,
        "active_node_id": active_node_id,
        "running_node_ids": running_nodes,
        "waiting_node_ids": waiting_nodes,
        "failed_node_ids": failed_nodes,
        "latest_runtime_at": latest_runtime_at,
        "stale_after_seconds": stale_after,
        "project_id": str(project.get("project_id") or ""),
        "progress": {
            "metric_label": str(progress.get("metric_label") or "units"),
            "completed_metric_total": int(progress.get("completed_metric_total") or 0),
            "target_metric_total": int(progress.get("target_metric_total") or 0),
            "committed_unit_count": int(progress.get("committed_unit_count") or 0),
        },
        "blocker": blocker,
        "streaming": {
            "enabled": bool(streaming.get("enabled") is True),
            "latest_chunk_at": _float(streaming.get("latest_chunk_at")),
        },
        "human_work_packet": human_work_packet,
        "temporal": temporal,
        "temporal_violations": temporal_violations,
    }
    if action != "no_action" and reason != "completed":
        run_interaction_request = _run_interaction_request(
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            monitor_node_id=monitor_node_id,
            action=action,
            reason=reason,
            severity=severity,
            summary=summary,
            observed=observed,
            policy=policy,
        )
    return TaskGraphMonitorDecision(
        decision_id=f"monitor-decision:{task_run_id or 'unknown'}:{uuid.uuid4().hex}",
        task_run_id=task_run_id,
        coordination_run_id=coordination_run_id,
        monitor_node_id=monitor_node_id,
        severity=severity,
        action=action,
        reason=reason,
        summary=summary,
        observed=observed,
        recommended_control=recommended_control,
        run_interaction_request=run_interaction_request,
        created_at=current_time,
    )


def compact_monitor_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = dict(snapshot or {})
    return {
        "authority": str(payload.get("authority") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "coordination_run_id": str(payload.get("coordination_run_id") or ""),
        "graph": dict(payload.get("graph") or {}),
        "runtime": dict(payload.get("runtime") or {}),
        "project": dict(payload.get("project") or {}),
        "progress": dict(payload.get("progress") or {}),
        "supervision": dict(payload.get("supervision") or {}),
        "blocker": dict(payload.get("blocker") or {}),
        "state": dict(payload.get("state") or {}),
        "temporal": dict(payload.get("temporal") or {}),
        "streaming": dict(payload.get("streaming") or {}),
    }


def _normalize_monitor_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(policy or {})
    allowed = [str(item) for item in list(payload.get("allowed_actions") or []) if str(item) in MONITOR_ACTIONS]
    if not allowed:
        allowed = ["no_action", "notify", "request_user_decision", "resume", "restart", "pause", "escalate"]
    stale_after = int(payload.get("stale_after_seconds") or payload.get("stale_after") or 600)
    return {
        **payload,
        "allowed_actions": allowed,
        "stale_after_seconds": max(stale_after, 30),
    }


def _control_packet(
    *,
    action: str,
    task_run_id: str,
    coordination_run_id: str,
    safe_to_auto_apply: bool,
    requires_human: bool,
) -> dict[str, Any]:
    api = ""
    if action == "resume" and coordination_run_id:
        api = f"/orchestration/coordination-runs/{coordination_run_id}/continue-current-stage"
    elif action == "pause" and task_run_id:
        api = f"/orchestration/runtime-loop/task-runs/{task_run_id}/stop"
    return {
        "action": action,
        "task_run_id": task_run_id,
        "coordination_run_id": coordination_run_id,
        "api": api,
        "safe_to_auto_apply": safe_to_auto_apply,
        "requires_human": requires_human,
    }


def _run_interaction_request(
    *,
    task_run_id: str,
    coordination_run_id: str,
    monitor_node_id: str,
    action: str,
    reason: str,
    severity: str,
    summary: str,
    observed: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    interaction_surface = dict(policy.get("interaction_surface") or {})
    window = str(interaction_surface.get("window") or "task_graph_run_interaction_panel").strip() or "task_graph_run_interaction_panel"
    return {
        "authority": "task_graph.run_interaction_request",
        "request_id": f"run-interaction:{task_run_id or 'unknown'}:{uuid.uuid4().hex}",
        "task_run_id": task_run_id,
        "coordination_run_id": coordination_run_id,
        "monitor_node_id": monitor_node_id,
        "action": action,
        "reason": reason,
        "severity": severity,
        "summary": summary,
        "window": window,
        "interaction_kind": _interaction_kind(action=action, reason=reason),
        "presentation": {
            "open_mode": str(interaction_surface.get("open_mode") or "inline_panel"),
            "focus": dict(interaction_surface.get("focus") or {"layer": "publish", "facet": "run_interaction"}),
            "title": str(interaction_surface.get("title") or "TaskGraph 运行交互"),
        },
        "decision_options": _interaction_decision_options(action=action, interaction_surface=interaction_surface),
        "human_work_packet": dict(observed.get("human_work_packet") or {}),
        "safe_state_refs": {
            "active_node_id": str(observed.get("active_node_id") or ""),
            "running_node_ids": list(observed.get("running_node_ids") or []),
            "waiting_node_ids": list(observed.get("waiting_node_ids") or []),
            "failed_node_ids": list(observed.get("failed_node_ids") or []),
        },
    }


def _interaction_kind(*, action: str, reason: str) -> str:
    if reason == "human_executor_waiting":
        return "human_executor"
    if action in {"request_user_decision", "request_human_review"}:
        return "manual_review"
    if action in {"resume", "restart", "pause"}:
        return "run_control"
    if reason == "manual_gate_waiting":
        return "manual_review"
    return "notification"


def _interaction_decision_options(*, action: str, interaction_surface: dict[str, Any]) -> list[dict[str, Any]]:
    configured = [dict(item) for item in list(interaction_surface.get("decision_options") or []) if isinstance(item, dict)]
    if configured:
        existing_actions = {
            str(item.get("control_action") or item.get("action") or item.get("decision") or "")
            for item in configured
        }
        if action == "restart" and "start_new_run" not in existing_actions:
            return [
                {"decision": "start_new_run", "label": "重新创建运行", "control_action": "start_new_run", "resume_payload": {"decision": "restart"}},
                *configured,
            ]
        if action == "notify" and "acknowledge" not in existing_actions:
            return [
                {"decision": "acknowledge", "label": "知道了", "control_action": "acknowledge", "resume_payload": {}},
                *configured,
            ]
        if action == "resume" and "continue_current_stage" not in existing_actions:
            return [
                {"decision": "continue_current_stage", "label": "续跑当前节点", "control_action": "continue_current_stage", "resume_payload": {"decision": "approve"}},
                *configured,
            ]
        return configured
    if action == "restart":
        return [
            {"decision": "start_new_run", "label": "重新创建运行", "control_action": "start_new_run", "resume_payload": {"decision": "restart"}},
            {"decision": "pause", "label": "暂停等待处理", "control_action": "stop_task_run", "resume_payload": {"reason": "monitor_restart_paused"}},
        ]
    if action == "notify":
        return [
            {"decision": "acknowledge", "label": "知道了", "control_action": "acknowledge", "resume_payload": {}},
            {"decision": "continue_current_stage", "label": "续跑当前节点", "control_action": "continue_current_stage", "resume_payload": {"decision": "approve"}},
            {"decision": "pause", "label": "暂停等待处理", "control_action": "stop_task_run", "resume_payload": {"reason": "monitor_notify_paused"}},
        ]
    return [
        {"decision": "continue_current_stage", "label": "续跑当前节点", "control_action": "continue_current_stage", "resume_payload": {"decision": "approve"}},
        {"decision": "retry_current_stage", "label": "重试当前节点", "control_action": "continue_current_stage", "resume_payload": {"decision": "retry"}},
        {"decision": "pause", "label": "暂停等待处理", "control_action": "stop_task_run", "resume_payload": {"decision": "reject", "reason": "monitor_pause_requested"}},
    ]


def _first_allowed(candidates: tuple[str, ...], allowed_actions: set[str]) -> str:
    for item in candidates:
        if item in allowed_actions:
            return item
    return "notify" if "notify" in allowed_actions else "no_action"


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
