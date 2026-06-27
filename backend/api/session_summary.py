from __future__ import annotations

from typing import Any


def enrich_session_summary(session: dict[str, Any], runtime: Any) -> dict[str, Any]:
    summary = dict(session or {})
    task_summary = _session_task_summary(summary.get("id"), runtime)
    if task_summary and task_summary.get("available"):
        summary["active_task"] = task_summary
    return summary


def enrich_session_summaries(sessions: list[dict[str, Any]], runtime: Any) -> list[dict[str, Any]]:
    return [enrich_session_summary(session, runtime) for session in sessions]


def _session_task_summary(session_id: Any, runtime: Any) -> dict[str, Any]:
    target_session_id = str(session_id or "").strip()
    if not target_session_id:
        return {}
    host = getattr(getattr(runtime, "harness_runtime", None), "single_agent_runtime_host", None)
    service = getattr(host, "run_monitor_service", None)
    summary = getattr(service, "get_session_task_summary", None)
    if not callable(summary):
        return {}
    payload = summary(target_session_id)
    return dict(payload or {}) if isinstance(payload, dict) else {}
