from __future__ import annotations

import hashlib
from typing import Any

from .activity import project_runtime_activity, signal_state_from_activity


MONITOR_AUTHORITY = "runtime_monitor"
SIGNAL_AUTHORITY = "runtime_monitor.signal"


def build_runtime_monitor_envelope(*, items: list[dict[str, Any]], now: float, limit: int = 30) -> dict[str, Any]:
    requested_limit = max(1, min(int(limit or 30), 100))
    signals = sorted(
        [project_monitor_signal(item, now=now) for item in items if isinstance(item, dict)],
        key=lambda item: (int(item.get("priority") or 0), _signal_last_activity(item)),
        reverse=True,
    )[:requested_limit]
    primary = [item for item in signals if item.get("is_running") is True]
    attention = [item for item in signals if item.get("state") in {"waiting", "attention", "stale", "failed"}]
    recent = [item for item in signals if item.get("state") == "completed"]
    projects = [item for item in signals if item.get("work_kind") == "graph_task"]
    return {
        "authority": MONITOR_AUTHORITY,
        "revision": _monitor_revision(signals, now=now),
        "updated_at": float(now),
        "summary": {
            "active": len(primary),
            "attention": len(attention),
            "waiting": sum(1 for item in signals if item.get("activity_state") in {"waiting", "paused"}),
            "failed": sum(1 for item in signals if item.get("state") == "failed"),
            "recent": len(recent),
            "projects": len(projects),
            "total": len(signals),
        },
        "primary": primary,
        "attention": attention,
        "recent": recent,
        "projects": projects,
        "signals": signals,
    }


def project_monitor_signal(item: dict[str, Any], *, now: float) -> dict[str, Any]:
    activity = _activity(item)
    view_item = {**item, **activity, "activity": activity}
    state = signal_state_from_activity(activity)
    source_kind = _source_kind(item)
    work_kind = _work_kind(item)
    signal_id = str(item.get("task_instance_id") or item.get("task_run_id") or "").strip()
    started_at = float(item.get("started_at") or item.get("created_at") or 0.0)
    updated_at = float(item.get("updated_at") or 0.0)
    last_activity_at = float(item.get("last_activity_at") or item.get("latest_event_at") or updated_at or started_at or 0.0)
    elapsed_seconds = max(0.0, float(now) - started_at) if state == "active" and started_at else float(item.get("duration_seconds") or 0.0)
    return {
        "signal_id": signal_id,
        "source_kind": source_kind,
        "work_kind": work_kind,
        "state": state,
        "priority": _signal_priority(item, state=state, source_kind=source_kind),
        "title": _public_title(view_item, work_kind=work_kind, state=state),
        "line": _public_line(view_item, state=state),
        "detail": _signal_detail(view_item, elapsed_seconds=elapsed_seconds, last_activity_at=last_activity_at),
        "status": str(item.get("status") or ""),
        "lifecycle": str(item.get("lifecycle") or ""),
        "bucket": str(item.get("bucket") or ""),
        "activity_state": str(activity.get("activity_state") or ""),
        "activity_label": str(activity.get("activity_label") or ""),
        "is_running": bool(activity.get("is_running")),
        "is_waiting": bool(activity.get("is_waiting")),
        "is_resumable": bool(activity.get("is_resumable")),
        "is_interruptible": bool(activity.get("is_interruptible")),
        "control_reason": str(activity.get("control_reason") or ""),
        "tone": str(activity.get("tone") or ""),
        "activity": activity,
        "control_capability": dict(item.get("control_capability") or {
            "is_resumable": bool(activity.get("is_resumable")),
            "is_interruptible": bool(activity.get("is_interruptible")),
            "control_reason": str(activity.get("control_reason") or ""),
        }),
        "session_id": str(item.get("session_id") or ""),
        "task_run_id": str(item.get("task_run_id") or ""),
        "task_instance_id": signal_id,
        "graph_run_id": str(item.get("graph_run_id") or ""),
        "graph_id": str(item.get("graph_id") or ""),
        "navigation_target": dict(item.get("navigation_target") or {}),
        "detail_ref": _detail_ref(item),
        "graph_ref": _graph_ref(item),
        "fact_summary": dict(item.get("fact_summary") or {}),
        "trace_summary": dict(item.get("trace_summary") or {}),
        "diagnostic_signal_refs": list(item.get("diagnostic_signal_refs") or []),
        "timestamps": {
            "started_at": started_at,
            "updated_at": updated_at,
            "last_activity_at": last_activity_at,
            "elapsed_seconds": elapsed_seconds,
        },
        "raw_refs": {
            "task_id": str(item.get("task_id") or ""),
            "route": dict(item.get("route") or {}),
        },
        "authority": SIGNAL_AUTHORITY,
    }


def _signal_lane_state(item: dict[str, Any]) -> str:
    return signal_state_from_activity(_activity(item))


def _activity(item: dict[str, Any]) -> dict[str, Any]:
    activity = item.get("activity")
    if isinstance(activity, dict) and activity.get("activity_state"):
        payload = dict(activity)
    else:
        payload = dict(project_runtime_activity(item))
    if str(item.get("lifecycle") or "") == "stale" or bool(item.get("stale") is True):
        return {
            **payload,
            "activity_state": "stale",
            "activity_label": "等待检查",
            "is_running": False,
            "is_waiting": True,
            "tone": "neutral",
        }
    return payload


def _source_kind(item: dict[str, Any]) -> str:
    execution_kind = str(item.get("execution_runtime_kind") or "")
    task_run_id = str(item.get("task_run_id") or "")
    if execution_kind == "single_agent_turn" or task_run_id.startswith("turnrun:"):
        return "turn_run"
    if str(item.get("graph_run_id") or ""):
        return "graph_run"
    return "task_run"


def _work_kind(item: dict[str, Any]) -> str:
    if str(item.get("kind") or "") == "task_graph" or str(item.get("graph_run_id") or ""):
        return "graph_task"
    if _source_kind(item) == "turn_run":
        return "chat_turn"
    return "agent_task"


def _signal_priority(item: dict[str, Any], *, state: str, source_kind: str) -> int:
    if state == "active":
        return 100 if source_kind == "turn_run" else 95
    if state == "waiting":
        return 80
    if state == "stale":
        return 70
    if state == "failed":
        return 60
    if state == "completed":
        return 20
    return 50


def _signal_last_activity(signal: dict[str, Any]) -> float:
    timestamps = dict(signal.get("timestamps") or {})
    return float(timestamps.get("last_activity_at") or 0.0)


def _detail_ref(item: dict[str, Any]) -> dict[str, str]:
    task_run_id = str(item.get("task_run_id") or "").strip()
    graph_run_id = str(item.get("graph_run_id") or "").strip()
    graph_harness_config_id = str(item.get("graph_harness_config_id") or "").strip()
    if graph_run_id:
        return {
            "kind": "graph_run",
            "task_run_id": task_run_id,
            "turn_run_id": "",
            "graph_run_id": graph_run_id,
            "graph_harness_config_id": graph_harness_config_id,
            "resource_ref": "",
        }
    if task_run_id:
        kind = "turn_run" if task_run_id.startswith("turnrun:") else "task_run"
        return {
            "kind": kind,
            "task_run_id": task_run_id,
            "turn_run_id": task_run_id if kind == "turn_run" else "",
            "graph_run_id": "",
            "graph_harness_config_id": "",
            "resource_ref": "",
        }
    return {"kind": "none", "task_run_id": "", "turn_run_id": "", "graph_run_id": "", "graph_harness_config_id": "", "resource_ref": ""}


def _graph_ref(item: dict[str, Any]) -> dict[str, str]:
    return {
        "graph_id": str(item.get("graph_id") or ""),
        "graph_run_id": str(item.get("graph_run_id") or ""),
        "graph_harness_config_id": str(item.get("graph_harness_config_id") or ""),
    }


def _public_title(item: dict[str, Any], *, work_kind: str, state: str) -> str:
    for key in ("project_title", "title"):
        value = _public_text(item.get(key))
        if value:
            return value
    task_id = _public_text(item.get("task_id"))
    if task_id:
        return task_id
    if work_kind == "graph_task":
        return "任务图运行"
    if work_kind == "chat_turn":
        return "当前对话"
    activity_state = str(item.get("activity_state") or dict(item.get("activity") or {}).get("activity_state") or "")
    if activity_state == "stopped":
        return "已停止"
    if state == "failed":
        return "运行中断"
    if state == "stale":
        return "运行状态需诊断"
    return "持续处理"


def _public_line(item: dict[str, Any], *, state: str) -> str:
    latest_progress = dict(item.get("latest_progress") or {})
    graph_status = dict(item.get("graph_status") or {})
    candidates = [
        latest_progress.get("tool_status"),
        latest_progress.get("observation"),
        latest_progress.get("summary"),
        item.get("latest_public_progress_note"),
        item.get("latest_step_summary"),
        item.get("summary"),
        latest_progress.get("current_judgment"),
        latest_progress.get("next_action"),
        graph_status.get("current_stage_summary"),
    ]
    for candidate in candidates:
        text = _public_text(candidate)
        if text:
            return text
    if state == "active":
        return "当前运行中。"
    if state == "waiting":
        return "等待继续。"
    if state == "stale":
        return "运行已停滞，需要诊断。"
    if state == "failed":
        return "运行失败，需要检查原因。"
    if state == "completed":
        activity_state = str(item.get("activity_state") or dict(item.get("activity") or {}).get("activity_state") or "")
        if activity_state == "stopped":
            return "运行已停止。"
        return "运行已完成。"
    return "运行状态已同步。"


def _signal_detail(item: dict[str, Any], *, elapsed_seconds: float, last_activity_at: float) -> str:
    state = _signal_lane_state(item)
    if state == "active":
        return f"运行 {_human_duration(elapsed_seconds)}"
    if state == "stale":
        age = float(item.get("last_activity_age_seconds") or 0.0)
        return f"停滞 {_human_duration(age)}"
    if state in {"waiting", "failed", "completed"}:
        duration = float(item.get("duration_seconds") or elapsed_seconds or 0.0)
        return f"耗时 {_human_duration(duration)}"
    if last_activity_at:
        return "已同步"
    return ""


def _public_text(value: Any) -> str:
    candidate = str(value or "").replace("\n", " ").strip()
    if not candidate:
        return ""
    lowered = candidate.lower()
    if any(lowered.startswith(prefix) for prefix in ("task:", "taskrun:", "turn:", "turnrun:", "session:", "taskinst:", "grun:")):
        return ""
    return " ".join(candidate.split())


def _human_duration(seconds: float) -> str:
    safe = max(0, int(seconds or 0))
    hours = safe // 3600
    minutes = (safe % 3600) // 60
    secs = safe % 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _monitor_revision(signals: list[dict[str, Any]], *, now: float) -> str:
    latest = max((float(dict(item.get("timestamps") or {}).get("last_activity_at") or 0.0) for item in signals), default=0.0)
    identity = "|".join(
        (
            f"{item.get('signal_id')}:{item.get('state')}:"
            f"{dict(item.get('timestamps') or {}).get('last_activity_at')}:"
            f"{_diagnostic_revision_part(item)}"
        )
        for item in signals
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"rtmon:{int(latest or now)}:{digest}"


def _diagnostic_revision_part(item: dict[str, Any]) -> str:
    trace_summary = dict(item.get("trace_summary") or {})
    fact_summary = dict(item.get("fact_summary") or {})
    return ":".join(
        [
            str(trace_summary.get("trace_id") or ""),
            str(trace_summary.get("span_count") or ""),
            str(trace_summary.get("event_count") or ""),
            str(trace_summary.get("error_span_count") or ""),
            str(fact_summary.get("fact_count") or ""),
        ]
    )
