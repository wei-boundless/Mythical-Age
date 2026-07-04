from __future__ import annotations

from pathlib import Path
from typing import Any

from .view_service import TaskEnvironmentViewService


def apply_task_environment_control_signal_bridge(
    *,
    base_dir: str | Path,
    graph_system: Any | None,
    environment_id: str,
    signal: dict[str, Any],
    bridge_graph_control: bool = True,
) -> dict[str, Any]:
    signal_kind = str(signal.get("signal_kind") or "").strip()
    if not bridge_graph_control:
        return {
            "authority": "task_system.task_environment_control_signal_bridge",
            "applied": False,
            "signal_status": "pending",
            "reason": "bridge_disabled",
        }
    detail = TaskEnvironmentViewService(base_dir).task_environment_detail(
        environment_id,
        event_limit=1,
        episode_limit=1,
        context_package_limit=1,
        work_product_limit=1,
    )
    binding = dict(detail.get("graph_node_binding") or {})
    graph_run_id = str(binding.get("graph_run_id") or "").strip()
    if not graph_run_id:
        return {
            "authority": "task_system.task_environment_control_signal_bridge",
            "applied": False,
            "signal_status": "pending",
            "reason": "no_graph_node_binding",
        }
    if graph_system is None:
        return {
            "authority": "task_system.task_environment_control_signal_bridge",
            "applied": False,
            "signal_status": "failed",
            "reason": "graph_system_unavailable",
            "graph_run_id": graph_run_id,
        }
    try:
        if signal_kind == "pause_requested":
            result = graph_system.request_graph_run_pause(
                graph_run_id,
                reason=str(signal.get("reason") or ""),
                requested_by=str(signal.get("requested_by") or "user"),
            )
            action = "graph_run_pause"
        elif signal_kind == "resume_requested":
            result = graph_system.request_graph_run_resume(
                graph_run_id,
                reason=str(signal.get("reason") or ""),
                requested_by=str(signal.get("requested_by") or "user"),
            )
            action = "graph_run_resume"
        else:
            return {
                "authority": "task_system.task_environment_control_signal_bridge",
                "applied": False,
                "signal_status": "pending",
                "reason": "unsupported_graph_control_signal",
                "signal_kind": signal_kind,
                "graph_run_id": graph_run_id,
            }
    except ValueError as exc:
        return {
            "authority": "task_system.task_environment_control_signal_bridge",
            "applied": False,
            "signal_status": "failed",
            "reason": str(exc),
            "signal_kind": signal_kind,
            "graph_run_id": graph_run_id,
        }
    accepted = bool(dict(result or {}).get("accepted", False))
    return {
        "authority": "task_system.task_environment_control_signal_bridge",
        "applied": accepted,
        "signal_status": "handled" if accepted else "failed",
        "action": action,
        "signal_kind": signal_kind,
        "graph_run_id": graph_run_id,
        "graph_control": dict(result or {}),
    }
