from __future__ import annotations

import hashlib
from typing import Any

from .lifecycle import GLOBAL_MONITOR_BUCKETS


MONITOR_AUTHORITY = "runtime_monitor.v1"


def monitor_revision(items: list[dict[str, Any]], *, now: float) -> str:
    latest = max((float(item.get("last_activity_at") or 0.0) for item in items), default=0.0)
    identity = "|".join(
        f"{item.get('task_instance_id') or item.get('task_run_id')}:{item.get('status')}:{item.get('bucket')}:{item.get('last_activity_at')}"
        for item in items
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"rtmon:{int(latest or now)}:{digest}"


def build_envelope(
    *,
    scope: str,
    items: list[dict[str, Any]],
    now: float,
    limit: int = 20,
    selected: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested_limit = max(1, min(int(limit or 20), 100))
    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in GLOBAL_MONITOR_BUCKETS}
    for item in items:
        bucket = str(item.get("bucket") or "diagnostics")
        if bucket not in buckets:
            bucket = "diagnostics"
        if len(buckets[bucket]) < requested_limit:
            buckets[bucket].append(item)
    for name in GLOBAL_MONITOR_BUCKETS:
        buckets[name].sort(key=_bucket_sort_key(name), reverse=True)
    visible_items = [item for name in GLOBAL_MONITOR_BUCKETS for item in buckets[name]]
    payload = {
        "authority": MONITOR_AUTHORITY,
        "scope": scope,
        "revision": monitor_revision(visible_items, now=now),
        "updated_at": float(now),
        "bucket_limit": requested_limit,
        "summary": {
            "total": len(visible_items),
            "running": len(buckets["running"]),
            "completed": len(buckets["completed"]),
            "failed": len(buckets["failed"]),
            "diagnostics": len(buckets["diagnostics"]),
            "action_required": sum(1 for item in visible_items if item.get("action_required") is True),
        },
        "buckets": buckets,
        "items": visible_items,
        "task_runs": visible_items,
        "selected": selected,
        "events": [],
    }
    if extra:
        payload.update(dict(extra))
    return payload


def build_task_detail_envelope(*, item: dict[str, Any], now: float) -> dict[str, Any]:
    return {
        **item,
        "authority": MONITOR_AUTHORITY,
        "scope": "task_run",
        "revision": monitor_revision([item], now=now),
        "updated_at": float(now),
    }


def build_navigation_target(
    *,
    kind: str,
    task_instance_id: str,
    task_run_id: str,
    session_id: str = "",
    graph_run_id: str = "",
    graph_id: str = "",
    focus_node_id: str = "",
) -> dict[str, Any]:
    if kind == "task_graph":
        return {
            "target_kind": "graph_task",
            "workspace_view": "chat",
            "session_id": session_id,
            "task_instance_id": task_instance_id,
            "task_run_id": task_run_id,
            "graph_run_id": graph_run_id,
            "graph_id": graph_id,
            "mode": "graph_monitor",
            "focus_node_id": focus_node_id,
        }
    if kind == "agent_run":
        return {
            "target_kind": "task_instance",
            "workspace_view": "orchestration",
            "session_id": session_id,
            "task_instance_id": task_instance_id,
            "task_run_id": task_run_id,
            "graph_run_id": "",
            "graph_id": "",
            "mode": "runtime_detail",
            "focus_node_id": "",
        }
    return {
        "target_kind": "session",
        "workspace_view": "chat",
        "session_id": session_id,
        "task_instance_id": task_instance_id,
        "task_run_id": task_run_id,
        "graph_run_id": "",
        "graph_id": "",
        "mode": "conversation",
        "focus_node_id": "",
    }


def _bucket_sort_key(bucket: str):
    if bucket in {"completed", "failed"}:
        return lambda item: float(item.get("ended_at") or item.get("last_activity_at") or 0.0)
    return lambda item: float(item.get("last_activity_at") or 0.0)
