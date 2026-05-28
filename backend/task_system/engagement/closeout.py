from __future__ import annotations

from pathlib import Path
from typing import Any

from .run_repository import EngagementRunRepository


TERMINAL_TASK_STATUSES = {"completed", "failed", "blocked", "canceled"}


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
    if not run.task_run_id:
        return {"changed": False, "reason": "engagement_run_has_no_task_run", "engagement_run": run.to_dict()}
    task_run = runtime_host.state_index.get_task_run(run.task_run_id)
    if task_run is None:
        return {"changed": False, "reason": "task_run_not_found", "engagement_run": run.to_dict()}
    task_status = str(getattr(task_run, "status", "") or "")
    if task_status not in TERMINAL_TASK_STATUSES:
        return {
            "changed": False,
            "reason": "task_run_not_terminal",
            "task_run_status": task_status,
            "engagement_run": run.to_dict(),
        }
    artifacts = _task_run_artifacts(runtime_host, run.task_run_id)
    verification_refs = _verification_refs(task_run)
    closeout = {
        **dict(run.closeout or {}),
        "task_run_status": task_status,
        "task_run_terminal_reason": str(getattr(task_run, "terminal_reason", "") or ""),
        "verified_artifact_count": len(artifacts),
        "verification_ref_count": len(verification_refs),
        "authority": "task_system.engagement_closeout",
    }
    status = _engagement_status_from_task_status(task_status)
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
            f"承接计划运行已随 TaskRun 收口：{status}。",
        )
    )
    return {
        "changed": True,
        "task_run_status": task_status,
        "engagement_run": updated.to_dict(),
        "closeout": closeout,
        "authority": "task_system.engagement_closeout",
    }


def sync_engagement_runs_for_terminal_task(
    *,
    backend_dir: Path | str,
    runtime_host: Any,
    task_run_id: str,
) -> list[dict[str, Any]]:
    repository = EngagementRunRepository(backend_dir)
    results: list[dict[str, Any]] = []
    for item in repository.list_runs():
        if str(item.get("task_run_id") or "") != str(task_run_id or ""):
            continue
        results.append(
            sync_engagement_run_closeout(
                backend_dir=backend_dir,
                runtime_host=runtime_host,
                engagement_run_id=str(item.get("engagement_run_id") or ""),
            )
        )
    return results


def _task_run_artifacts(runtime_host: Any, task_run_id: str) -> list[dict[str, Any]]:
    if hasattr(runtime_host, "get_task_run_artifacts"):
        try:
            payload = runtime_host.get_task_run_artifacts(task_run_id)
            return [dict(item) for item in list(payload.get("artifact_refs") or []) if isinstance(item, dict)]
        except Exception:
            return []
    return []


def _verification_refs(task_run: Any) -> list[dict[str, Any]]:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    refs: list[dict[str, Any]] = []
    for key in ("verification_refs", "verified_artifacts", "completion_verdicts"):
        for item in list(diagnostics.get(key) or []):
            if isinstance(item, dict):
                refs.append(dict(item))
    return _dedupe_dicts(refs)


def _engagement_status_from_task_status(task_status: str) -> str:
    if task_status == "completed":
        return "completed"
    if task_status == "blocked":
        return "blocked"
    if task_status == "canceled":
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
