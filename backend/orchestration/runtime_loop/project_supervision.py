from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .models import ProjectProgressLedger, ProjectRuntimeStatus, SupervisionRecord


def ensure_project_runtime_inputs(
    *,
    initial_inputs: dict[str, Any],
    graph_id: str,
    session_id: str,
) -> dict[str, Any]:
    inputs = dict(initial_inputs or {})
    title = str(
        inputs.get("project_title")
        or inputs.get("title")
        or inputs.get("project_name")
        or ""
    ).strip()
    project_brief = str(inputs.get("project_brief") or "").strip()
    project_id = str(inputs.get("project_id") or "").strip()
    if not project_id:
        project_id = _safe_slug(title or project_brief[:48] or graph_id or session_id or "project")
        project_id = f"project:{project_id}"
    target_metric_total = _target_metric_from_inputs(inputs)
    metric_label = str(inputs.get("metric_label") or inputs.get("progress_metric_label") or "units").strip() or "units"
    normalized = {
        **inputs,
        "project_id": project_id,
        "project_title": title or project_id,
        "metric_label": metric_label,
        "target_metric_total": target_metric_total,
    }
    if "target_length" not in normalized or not str(normalized.get("target_length") or "").strip():
        normalized["target_length"] = str(target_metric_total)
    return normalized


def make_initial_project_ledger(
    *,
    project_id: str,
    session_id: str,
    graph_id: str,
    task_family: str,
    project_title: str,
    target_metric_total: int,
    metric_label: str = "units",
    task_run_id: str,
    now: float | None = None,
) -> ProjectProgressLedger:
    ts = float(now or time.time())
    return ProjectProgressLedger(
        ledger_id=project_id,
        project_id=project_id,
        session_id=session_id,
        graph_id=graph_id,
        task_family=task_family,
        project_title=project_title,
        metric_label=str(metric_label or "units"),
        target_metric_total=target_metric_total,
        run_chain=(task_run_id,) if task_run_id else (),
        updated_at=ts,
        created_at=ts,
    )


def record_progress_unit_commit(
    ledger: ProjectProgressLedger,
    *,
    task_run_id: str,
    unit_index: int,
    unit_ref: str,
    metric_value: int,
    receipt_ref: str,
    now: float | None = None,
) -> ProjectProgressLedger:
    receipt_key = str(receipt_ref or unit_ref or f"unit:{unit_index}")
    existing_receipts = [dict(item) for item in ledger.metric_receipts]
    if any(str(item.get("receipt_ref") or "") == receipt_key for item in existing_receipts):
        return ledger
    committed_refs = list(ledger.committed_unit_refs)
    if unit_ref and unit_ref not in committed_refs:
        committed_refs.append(unit_ref)
    existing_receipts.append(
        {
            "receipt_ref": receipt_key,
            "task_run_id": task_run_id,
            "unit_index": int(unit_index or 0),
            "unit_ref": unit_ref,
            "metric_value": int(max(metric_value, 0)),
            "recorded_at": float(now or time.time()),
        }
    )
    run_chain = _append_unique(list(ledger.run_chain), task_run_id)
    return ProjectProgressLedger(
        ledger_id=ledger.ledger_id,
        project_id=ledger.project_id,
        session_id=ledger.session_id,
        graph_id=ledger.graph_id,
        task_family=ledger.task_family,
        project_title=ledger.project_title,
        metric_label=ledger.metric_label,
        target_metric_total=ledger.target_metric_total,
        committed_metric_total=int(ledger.committed_metric_total or 0) + int(max(metric_value, 0)),
        committed_unit_count=int(ledger.committed_unit_count or 0) + 1,
        last_committed_unit_index=max(int(ledger.last_committed_unit_index or 0), int(unit_index or 0)),
        committed_unit_refs=tuple(committed_refs),
        metric_receipts=tuple(existing_receipts),
        run_chain=tuple(run_chain),
        latest_delivery_state=ledger.latest_delivery_state,
        last_failure=dict(ledger.last_failure),
        last_repair_action=dict(ledger.last_repair_action),
        updated_at=float(now or time.time()),
        created_at=ledger.created_at,
    )


def record_delivery_state(
    ledger: ProjectProgressLedger,
    *,
    task_run_id: str,
    delivery_state: str,
    now: float | None = None,
) -> ProjectProgressLedger:
    return ProjectProgressLedger(
        **{
            **ledger.to_dict(),
            "run_chain": _append_unique(list(ledger.run_chain), task_run_id),
            "latest_delivery_state": str(delivery_state or ""),
            "updated_at": float(now or time.time()),
        }
    )


def record_failure(
    ledger: ProjectProgressLedger,
    *,
    task_run_id: str,
    failure: dict[str, Any],
    repair_action: dict[str, Any] | None = None,
    now: float | None = None,
) -> ProjectProgressLedger:
    return ProjectProgressLedger(
        **{
            **ledger.to_dict(),
            "run_chain": _append_unique(list(ledger.run_chain), task_run_id),
            "last_failure": dict(failure or {}),
            "last_repair_action": dict(repair_action or ledger.last_repair_action),
            "updated_at": float(now or time.time()),
        }
    )


def clear_recovered_failure(
    ledger: ProjectProgressLedger,
    *,
    task_run_id: str,
    stage_id: str,
    now: float | None = None,
) -> ProjectProgressLedger:
    failure = dict(ledger.last_failure or {})
    if not failure:
        return ledger
    failed_stage_id = str(failure.get("stage_id") or "").strip()
    failed_task_run_id = str(failure.get("task_run_id") or "").strip()
    current_stage_id = str(stage_id or "").strip()
    current_task_run_id = str(task_run_id or "").strip()
    if failed_stage_id and current_stage_id:
        if failed_stage_id != current_stage_id:
            return ledger
    elif failed_task_run_id and current_task_run_id and failed_task_run_id != current_task_run_id:
        return ledger
    return ProjectProgressLedger(
        **{
            **ledger.to_dict(),
            "run_chain": _append_unique(list(ledger.run_chain), current_task_run_id),
            "last_failure": {},
            "last_repair_action": {},
            "updated_at": float(now or time.time()),
        }
    )


def build_runtime_status(
    *,
    ledger: ProjectProgressLedger,
    task_run_id: str,
    coordination_run_id: str,
    active_run_status: str,
    latest_artifact_root: str,
    latest_event_offset: int,
    latest_event_at: float,
    last_effective_output_at: float,
    blocker: dict[str, Any],
    recovery_state: dict[str, Any],
    updated_at: float | None = None,
) -> ProjectRuntimeStatus:
    runtime_status = "watching"
    if ledger.committed_metric_total >= ledger.target_metric_total > 0 and str(ledger.latest_delivery_state or "") in {"delivery_ready", "completed", "delivered"}:
        runtime_status = "completed"
    elif active_run_status in {"failed", "aborted"}:
        runtime_status = "failed"
    elif blocker:
        runtime_status = "blocked"
    elif recovery_state:
        runtime_status = "repairing"
    elif active_run_status in {"running", "waiting", "blocked"}:
        runtime_status = "watching"
    return ProjectRuntimeStatus(
        project_id=ledger.project_id,
        session_id=ledger.session_id,
        graph_id=ledger.graph_id,
        task_family=ledger.task_family,
        project_title=ledger.project_title,
        active_task_run_id=task_run_id,
        active_coordination_run_id=coordination_run_id,
        active_run_status=active_run_status,
        project_runtime_status=runtime_status,
        metric_label=ledger.metric_label,
        completed_metric_total=ledger.committed_metric_total,
        target_metric_total=ledger.target_metric_total,
        committed_unit_count=ledger.committed_unit_count,
        last_committed_unit_index=ledger.last_committed_unit_index,
        active_blocker=dict(blocker or {}),
        recovery_state=dict(recovery_state or {}),
        delivery_state=ledger.latest_delivery_state,
        latest_artifact_root=str(latest_artifact_root or ""),
        latest_event_offset=int(latest_event_offset or 0),
        latest_event_at=float(latest_event_at or 0.0),
        last_effective_output_at=float(last_effective_output_at or 0.0),
        updated_at=float(updated_at or time.time()),
    )


def classify_blocker(
    *,
    run_status: str,
    terminal_reason: str,
    active_node_id: str,
    stage_execution_request: dict[str, Any] | None,
    last_event_at: float,
    now: float | None = None,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_time = float(now or time.time())
    stage_request = dict(stage_execution_request or {})
    error = dict(failure or {})
    if run_status in {"failed", "aborted"}:
        return {
            "kind": "run_failed",
            "severity": "error",
            "summary": str(error.get("message") or terminal_reason or "Task run failed"),
            "active_node_id": active_node_id,
            "terminal_reason": terminal_reason,
        }
    if active_node_id and not stage_request and run_status == "running":
        return {
            "kind": "missing_stage_execution_request",
            "severity": "error",
            "summary": "Active run has no current stage execution request.",
            "active_node_id": active_node_id,
        }
    if last_event_at > 0 and current_time - last_event_at >= 180 and run_status == "running":
        return {
            "kind": "stalled_run",
            "severity": "warning",
            "summary": f"Run has no new events for {int(current_time - last_event_at)}s.",
            "active_node_id": active_node_id,
            "stalled_for_seconds": int(current_time - last_event_at),
        }
    return {}


def make_supervision_record(
    *,
    project_id: str,
    session_id: str,
    task_run_id: str = "",
    coordination_run_id: str = "",
    issue_type: str,
    issue_summary: str,
    root_cause: str = "",
    repair_action: str = "",
    repair_result: str = "",
    followup_status: str = "recorded",
    diagnostics: dict[str, Any] | None = None,
    created_at: float | None = None,
) -> SupervisionRecord:
    ts = float(created_at or time.time())
    return SupervisionRecord(
        supervision_record_id=f"supervision:{project_id}:{int(ts * 1000)}:{_safe_slug(issue_type or 'issue')}",
        supervision_session_id=session_id,
        project_id=project_id,
        observed_task_run_id=task_run_id,
        observed_coordination_run_id=coordination_run_id,
        issue_type=issue_type,
        issue_summary=issue_summary,
        root_cause=root_cause,
        repair_action=repair_action,
        repair_result=repair_result,
        followup_status=followup_status,
        created_at=ts,
        diagnostics=dict(diagnostics or {}),
    )


def _target_metric_from_inputs(inputs: dict[str, Any]) -> int:
    for candidate in (
        inputs.get("target_metric_total"),
        inputs.get("target_words"),
        inputs.get("target_length"),
        dict(inputs.get("project_meta") or {}).get("target_metric_total"),
        dict(inputs.get("project_meta") or {}).get("target_words"),
    ):
        value = _coerce_target_metric(candidate)
        if value > 0:
            return value
    return 1_000_000


def _coerce_target_metric(value: Any) -> int:
    if isinstance(value, int):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    text = text.replace(",", "")
    direct = re.findall(r"\d+", text)
    if direct:
        return int("".join(direct))
    if "百万" in text:
        return 1_000_000
    return 0


def _append_unique(items: list[str], value: str) -> list[str]:
    candidate = str(value or "").strip()
    if candidate and candidate not in items:
        items.append(candidate)
    return items


def _safe_slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", str(value or "").strip()).strip("-").lower()
    return normalized[:80] or "value"


def latest_artifact_files_from_root(workspace_root: Path, artifact_root: str) -> list[str]:
    root = str(artifact_root or "").strip()
    if not root:
        return []
    target = (Path(workspace_root) / root).resolve()
    if not target.exists() or not target.is_dir():
        return []
    files = [item.resolve().relative_to(Path(workspace_root).resolve()).as_posix() for item in target.rglob("*") if item.is_file()]
    return sorted(files)[-200:]
