from __future__ import annotations

from pathlib import Path
from typing import Any

from .run_repository import EngagementRunRepository


TERMINAL_GRAPH_STATUSES = {"completed", "failed", "blocked", "cancelled", "canceled", "stopped"}


def sync_engagement_run_closeout(
    *,
    backend_dir: Path | str,
    runtime_host: Any,
    engagement_run_id: str,
) -> dict[str, Any]:
    repository = EngagementRunRepository(backend_dir)
    run = repository.get_run(engagement_run_id)
    if run is None:
        raise KeyError(f"engagement run not found: {engagement_run_id}")
    if run.strategy_kind != "graph_task_run":
        return {
            "changed": False,
            "reason": f"unsupported_strategy:{run.strategy_kind}",
            "engagement_run": run.to_dict(),
            "authority": "task_system.engagement_closeout",
        }
    monitor_result = _graph_run_monitor(runtime_host, run.workflow_run_id)
    if not monitor_result.get("available"):
        return {
            "changed": False,
            "reason": str(monitor_result.get("reason") or "graph_run_monitor_unavailable"),
            "engagement_run": run.to_dict(),
            "graph_run_id": run.workflow_run_id,
            "authority": "task_system.engagement_closeout",
        }
    monitor = dict(monitor_result.get("monitor") or {})
    graph_status = _graph_status(monitor)
    if graph_status not in TERMINAL_GRAPH_STATUSES:
        return {
            "changed": False,
            "reason": "graph_run_not_terminal",
            "graph_run_status": graph_status,
            "graph_run_id": run.workflow_run_id,
            "engagement_run": run.to_dict(),
            "authority": "task_system.engagement_closeout",
        }
    graph_result = _graph_result(monitor)
    artifacts = _artifact_refs_from_graph_result(graph_result)
    verification_refs = _verification_refs_from_graph_result(graph_result)
    closeout = {
        **dict(run.closeout or {}),
        "graph_run_id": run.workflow_run_id,
        "graph_run_status": graph_status,
        "graph_run_terminal_reason": _graph_terminal_reason(monitor, graph_result=graph_result),
        "verified_artifact_count": len(artifacts),
        "verification_ref_count": len(verification_refs),
        "node_result_ref_count": len(list(graph_result.get("node_result_refs") or [])),
        "authority": "task_system.engagement_closeout",
    }
    status = _engagement_status_from_graph_status(graph_status)
    updated = repository.update_run(
        engagement_run_id,
        status=status,
        artifact_refs=tuple(artifacts),
        verification_refs=tuple(verification_refs),
        closeout=closeout,
    )
    if hasattr(runtime_host, "runtime_objects"):
        runtime_host.runtime_objects.put_object("engagement_run", updated.engagement_run_id, updated.to_dict())
    repository.append_event(
        _event_model(
            updated.engagement_run_id,
            "closeout_synced",
            f"承接计划运行已随 GraphRun 收口：{status}。",
        )
    )
    return {
        "changed": True,
        "graph_run_status": graph_status,
        "graph_run_id": run.workflow_run_id,
        "engagement_run": updated.to_dict(),
        "closeout": closeout,
        "authority": "task_system.engagement_closeout",
    }


def _graph_run_monitor(runtime_host: Any, graph_run_id: str) -> dict[str, Any]:
    target = str(graph_run_id or "").strip()
    if not target:
        return {"available": False, "reason": "engagement_run_has_no_graph_run"}
    graph_system = getattr(runtime_host, "graph_system", None)
    if graph_system is None:
        return {"available": False, "reason": "graph_system_unavailable"}
    monitor_loader = getattr(graph_system, "get_graph_run_monitor", None)
    if not callable(monitor_loader):
        return {"available": False, "reason": "graph_run_monitor_unavailable"}
    try:
        monitor = monitor_loader(target, graph_config=None, event_limit=1, include_config=False)
    except ValueError as exc:
        return {"available": False, "reason": str(exc) or "graph_run_monitor_failed"}
    if not monitor:
        return {"available": False, "reason": "graph_run_monitor_not_found"}
    return {"available": True, "monitor": dict(monitor)}


def _graph_status(monitor: dict[str, Any]) -> str:
    loop_state = dict(monitor.get("graph_loop_state") or {})
    graph_run = dict(monitor.get("graph_run") or {})
    return str(loop_state.get("status") or graph_run.get("status") or "").strip()


def _graph_result(monitor: dict[str, Any]) -> dict[str, Any]:
    graph_run = dict(monitor.get("graph_run") or {})
    diagnostics = dict(graph_run.get("diagnostics") or {})
    result = diagnostics.get("graph_result")
    return dict(result) if isinstance(result, dict) else {}


def _graph_terminal_reason(monitor: dict[str, Any], *, graph_result: dict[str, Any]) -> str:
    loop_state = dict(monitor.get("graph_loop_state") or {})
    graph_run = dict(monitor.get("graph_run") or {})
    return str(
        graph_result.get("terminal_reason")
        or loop_state.get("terminal_reason")
        or graph_run.get("terminal_reason")
        or _graph_status(monitor)
    )


def _artifact_refs_from_graph_result(graph_result: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in list(graph_result.get("artifact_refs") or []):
        if isinstance(item, dict):
            refs.append(dict(item))
        elif str(item or "").strip():
            refs.append({"ref": str(item).strip(), "source": "graph_result.artifact_refs"})
    return _dedupe_dicts(refs)


def _verification_refs_from_graph_result(graph_result: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = dict(graph_result.get("diagnostics") or {})
    refs: list[dict[str, Any]] = []
    for key in ("verification_refs", "verified_artifacts", "completion_verdicts", "artifact_materialization_receipts", "memory_commit_receipts"):
        for item in list(diagnostics.get(key) or []):
            if isinstance(item, dict):
                refs.append({**dict(item), "source": f"graph_result.diagnostics.{key}"})
    return _dedupe_dicts(refs)


def _engagement_status_from_graph_status(graph_status: str) -> str:
    if graph_status == "completed":
        return "completed"
    if graph_status == "blocked":
        return "blocked"
    if graph_status in {"cancelled", "canceled", "stopped"}:
        return "canceled"
    return "failed"


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        key = str(item.get("path") or item.get("id") or item.get("ref") or item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _event_model(engagement_run_id: str, event_type: str, summary: str) -> Any:
    from time import time

    from .models import EngagementEvent

    return EngagementEvent(
        engagement_run_id=engagement_run_id,
        event_type=event_type,
        summary=summary,
        created_at=str(time()),
    )
