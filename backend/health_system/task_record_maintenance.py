from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .models import HealthManagementReceipt


ACTIVE_TASK_STATUSES = {"created", "queued", "running", "waiting_executor", "waiting_approval", "paused"}
FAILED_TASK_STATUSES = {"failed", "aborted", "cancelled", "error"}
MAINTENANCE_BUCKETS = {"static", "completed", "failed", "diagnostics"}
DEFAULT_MIN_RECORD_AGE_SECONDS = 24 * 60 * 60
DEFAULT_STALE_RUNTIME_SECONDS = 30 * 60
DEFAULT_MAINTENANCE_SCAN_LIMIT = 80


class HealthTaskRecordMaintenanceService:
    """Controlled task-record maintenance owned by HealthSystem.

    The service may request deletion through runtime stores, but it does not
    decide runtime facts. It only applies health-system protection policy,
    emits impact previews, and records receipts for actual maintenance.
    """

    def __init__(
        self,
        *,
        runtime_host: Any,
        prompt_accounting_ledger: Any | None = None,
        store: Any | None = None,
        now: float | None = None,
    ) -> None:
        self.runtime_host = runtime_host
        self.state_index = runtime_host.state_index
        self.event_log = runtime_host.event_log
        self.prompt_accounting_ledger = prompt_accounting_ledger
        self.store = store
        self.now = time.time() if now is None else float(now)
        self.layout = ProjectLayout.from_runtime_root(getattr(runtime_host, "root_dir", getattr(runtime_host, "backend_dir", Path.cwd())))

    def build_view(
        self,
        *,
        bucket: str = "static",
        task_run_ids: list[str] | None = None,
        min_age_seconds: int = DEFAULT_MIN_RECORD_AGE_SECONDS,
    ) -> dict[str, Any]:
        normalized_bucket = self._normalize_bucket(bucket)
        records = self._candidate_records(
            bucket=normalized_bucket,
            task_run_ids=task_run_ids,
            min_age_seconds=min_age_seconds,
        )
        return {
            "authority": "health_system.task_record_maintenance",
            "mode": "preflight",
            "bucket": normalized_bucket,
            "requested_task_run_ids": self._requested_ids(task_run_ids),
            "policy": self._policy(min_age_seconds=min_age_seconds),
            "summary": self._summary(records),
            "candidates": records,
            "recent_receipts": self._recent_maintenance_receipts(),
            "updated_at": self.now,
        }

    def prune_task_records(
        self,
        *,
        bucket: str = "static",
        task_run_ids: list[str] | None = None,
        dry_run: bool = False,
        min_age_seconds: int = DEFAULT_MIN_RECORD_AGE_SECONDS,
        operation: str = "delete_expired",
    ) -> dict[str, Any]:
        normalized_bucket = self._normalize_bucket(bucket)
        operation = str(operation or "delete_expired").strip() or "delete_expired"
        view = self.build_view(
            bucket=normalized_bucket,
            task_run_ids=task_run_ids,
            min_age_seconds=min_age_seconds,
        )
        candidates = [dict(item) for item in list(view.get("candidates") or [])]
        eligible_ids = [str(item.get("task_run_id") or "") for item in candidates if item.get("eligible")]
        protected = [item for item in candidates if not item.get("eligible")]
        state_result: dict[str, Any] = {}
        deleted_event_logs: list[str] = []
        prompt_accounting_prune: dict[str, Any] = {}
        deleted_task_run_ids: list[str] = []

        if not dry_run and eligible_ids:
            state_result = dict(self.state_index.prune_task_runs(set(eligible_ids)) or {})
            deleted_task_run_ids = [str(item) for item in list(state_result.get("deleted_task_run_ids") or [])]
            deleted_event_logs = [
                task_run_id
                for task_run_id in deleted_task_run_ids
                if self.event_log.delete_events(task_run_id)
            ]
            ledger_prune = getattr(self.prompt_accounting_ledger, "prune_task_runs", None)
            if callable(ledger_prune):
                prompt_accounting_prune = dict(ledger_prune(set(deleted_task_run_ids)) or {})

        deleted_counts = {
            **dict(state_result.get("deleted_counts") or {}),
            **{
                f"prompt_accounting.{key}": value
                for key, value in dict(prompt_accounting_prune.get("deleted_counts") or {}).items()
            },
        }
        result = {
            "authority": "health_system.task_record_maintenance",
            "mode": "dry_run" if dry_run else "execute",
            "operation": operation,
            "bucket": normalized_bucket,
            "requested_task_run_ids": self._requested_ids(task_run_ids),
            "candidate_count": len(candidates),
            "eligible_task_run_ids": eligible_ids,
            "protected_task_run_ids": [str(item.get("task_run_id") or "") for item in protected],
            "deleted_task_run_ids": deleted_task_run_ids,
            "deleted_event_log_task_run_ids": deleted_event_logs,
            "deleted_counts": deleted_counts,
            "skipped": [
                {
                    "task_run_id": str(item.get("task_run_id") or ""),
                    "reason": ",".join(str(reason) for reason in list(item.get("protection_reasons") or [])),
                    "status": str(item.get("status") or ""),
                    "bucket": str(item.get("bucket") or ""),
                    "protection_reasons": list(item.get("protection_reasons") or []),
                }
                for item in protected
            ],
            "preflight": view,
            "policy": dict(view.get("policy") or {}),
            "updated_at": time.time(),
        }
        receipt = self._build_receipt(result=result, dry_run=dry_run)
        result["maintenance_receipt"] = receipt.to_dict()
        if not dry_run and self.store is not None:
            self.store.append_receipt(receipt)
            result["maintenance_receipt"]["persisted"] = True
        else:
            result["maintenance_receipt"]["persisted"] = False
        return result

    def _candidate_records(
        self,
        *,
        bucket: str,
        task_run_ids: list[str] | None,
        min_age_seconds: int,
    ) -> list[dict[str, Any]]:
        requested = set(self._requested_ids(task_run_ids))
        monitor_by_id = self._monitor_by_task_run_id()
        reported_task_run_ids = self._reported_task_run_ids()
        lineage_index = self._lineage_index()
        records: list[dict[str, Any]] = []
        deep_diagnostics = bool(requested) or bucket == "diagnostics"
        task_runs = (
            [item for item in (self.state_index.get_task_run(task_run_id) for task_run_id in requested) if item is not None]
            if requested
            else self.state_index.list_recent_task_runs(limit=DEFAULT_MAINTENANCE_SCAN_LIMIT)
        )
        token_summary_index = self._token_summary_index(task_runs)
        for task_run in task_runs:
            task_run_id = str(getattr(task_run, "task_run_id", "") or "")
            if not task_run_id:
                continue
            monitor = dict(monitor_by_id.get(task_run_id) or {})
            record = self._maintenance_record(
                task_run,
                monitor=monitor,
                reported_task_run_ids=reported_task_run_ids,
                min_age_seconds=min_age_seconds,
                lineage_index=lineage_index,
                token_summary_index=token_summary_index,
                deep_diagnostics=deep_diagnostics,
            )
            if requested:
                if task_run_id in requested:
                    records.append(record)
                continue
            if self._matches_bucket(record, bucket=bucket):
                records.append(record)
        return sorted(
            records,
            key=lambda item: (bool(item.get("eligible")), float(item.get("updated_at") or 0.0)),
            reverse=True,
        )

    def _maintenance_record(
        self,
        task_run: Any,
        *,
        monitor: dict[str, Any],
        reported_task_run_ids: set[str],
        min_age_seconds: int,
        lineage_index: dict[str, Any],
        token_summary_index: dict[str, dict[str, Any]],
        deep_diagnostics: bool = False,
    ) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        status = str(getattr(task_run, "status", "") or "unknown")
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        created_at = float(getattr(task_run, "created_at", 0.0) or 0.0)
        updated_at = float(getattr(task_run, "updated_at", 0.0) or created_at or 0.0)
        age_seconds = max(0.0, self.now - max(created_at, updated_at))
        bucket = str(monitor.get("bucket") or self._bucket_from_status(status))
        resource_class = str(monitor.get("resource_class") or ("dynamic" if status in ACTIVE_TASK_STATUSES else "static"))
        activity = _project_runtime_activity({**dict(monitor or {}), "status": str(monitor.get("status") or status)})
        activity_state = str(activity.get("activity_state") or "")
        event_count = self._event_count(task_run_id)
        graph_run_id = str(diagnostics.get("graph_run_id") or monitor.get("graph_run_id") or dict(monitor.get("graph_ref") or {}).get("graph_run_id") or "").strip()
        needs_runtime_diagnostics = (
            status in ACTIVE_TASK_STATUSES
            or activity.get("is_running") is True
            or activity.get("is_waiting") is True
            or activity_state == "stale"
            or resource_class == "dynamic"
            or bucket == "diagnostics"
            or bool(graph_run_id)
        )
        recent_event = self._recent_event_snapshot(task_run_id) if needs_runtime_diagnostics else _empty_recent_event_snapshot(task_run_id)
        token_summary = dict(token_summary_index.get(task_run_id) or {})
        runtime_diagnostics = self._runtime_diagnostics(
            task_run=task_run,
            monitor=monitor,
            activity=activity,
            recent_event=recent_event,
            include_graph_checkpoint=deep_diagnostics,
        )
        protection_reasons: list[str] = []
        if activity.get("is_running") is True or activity.get("is_waiting") is True or activity_state == "stale" or resource_class == "dynamic":
            protection_reasons.append("active_or_dynamic_runtime")
        if age_seconds < max(0, int(min_age_seconds or 0)):
            protection_reasons.append("recent_task_record")
        if status in FAILED_TASK_STATUSES and task_run_id not in reported_task_run_ids:
            protection_reasons.append("failed_without_health_report")
        if self._has_lineage(task_run, diagnostics=diagnostics):
            protection_reasons.append("task_lineage_record")
        if task_run_id in set(lineage_index.get("parent_task_run_ids") or set()):
            protection_reasons.append("task_lineage_parent")
        for reason in list(runtime_diagnostics.get("protection_reasons") or []):
            if reason not in protection_reasons:
                protection_reasons.append(str(reason))
        return {
            "task_run_id": task_run_id,
            "title": str(
                dict(getattr(task_run, "diagnostics", {}) or {}).get("title")
                or dict(getattr(task_run, "diagnostics", {}) or {}).get("task_graph_title")
                or getattr(task_run, "task_id", "")
                or task_run_id
            ),
            "status": status,
            "bucket": bucket,
            "resource_class": resource_class,
            "created_at": created_at,
            "updated_at": updated_at,
            "age_seconds": age_seconds,
            "event_count": event_count,
            "latest_event": recent_event,
            "prompt_accounting_record_count": int(token_summary.get("record_count") or 0),
            "monitor": self._monitor_summary(monitor=monitor, activity=activity),
            "runtime_diagnostics": runtime_diagnostics,
            "storage_refs": self._storage_refs(task_run=task_run, graph_run_id=str(runtime_diagnostics.get("graph_run_id") or "")),
            "estimated_delete_counts": {
                "task_runs": 1,
                "event_log_events": event_count,
                "prompt_accounting_records": int(token_summary.get("record_count") or 0),
            },
            "eligible": not protection_reasons,
            "protection_reasons": protection_reasons,
        }

    def _event_count(self, task_run_id: str) -> int:
        estimator = getattr(self.event_log, "estimated_event_count", None)
        if callable(estimator):
            try:
                return int(estimator(task_run_id))
            except Exception:
                return 0
        counter = getattr(self.event_log, "event_count", None)
        if callable(counter):
            try:
                return int(counter(task_run_id))
            except Exception:
                return 0
        return 0

    def _recent_event_snapshot(self, task_run_id: str) -> dict[str, Any]:
        reader = getattr(self.event_log, "list_recent_events", None)
        events: list[Any] = []
        if callable(reader):
            try:
                events = list(reader(task_run_id, limit=1))
            except TypeError:
                try:
                    events = list(reader(task_run_id))[-1:]
                except Exception:
                    events = []
            except Exception:
                events = []
        elif hasattr(self.event_log, "list_events"):
            try:
                events = list(self.event_log.list_events(task_run_id))[-1:]
            except Exception:
                events = []
        if not events:
            return {
                "available": False,
                "task_run_id": task_run_id,
                "event_type": "",
                "event_id": "",
                "created_at": 0.0,
                "age_seconds": 0.0,
            }
        event = events[-1]
        payload = event.to_dict() if hasattr(event, "to_dict") else dict(event or {})
        created_at = float(payload.get("created_at") or getattr(event, "created_at", 0.0) or 0.0)
        return {
            "available": True,
            "task_run_id": task_run_id,
            "event_type": str(payload.get("event_type") or getattr(event, "event_type", "") or ""),
            "event_id": str(payload.get("event_id") or getattr(event, "event_id", "") or ""),
            "created_at": created_at,
            "age_seconds": max(0.0, self.now - created_at) if created_at else 0.0,
        }

    def _runtime_diagnostics(
        self,
        *,
        task_run: Any,
        monitor: dict[str, Any],
        activity: dict[str, Any],
        recent_event: dict[str, Any],
        include_graph_checkpoint: bool = False,
    ) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        status = str(getattr(task_run, "status", "") or "")
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        graph_run_id = str(diagnostics.get("graph_run_id") or monitor.get("graph_run_id") or dict(monitor.get("graph_ref") or {}).get("graph_run_id") or "").strip()
        graph_run = self._graph_run_object(graph_run_id)
        graph_state = self._graph_checkpoint_state(graph_run_id) if include_graph_checkpoint else {}
        flags: list[str] = []
        protection_reasons: list[str] = []
        recommended_actions: list[str] = []
        activity_state = str(activity.get("activity_state") or "")
        active_status = status in ACTIVE_TASK_STATUSES or activity.get("is_running") is True or activity.get("is_waiting") is True
        latest_event_age = float(recent_event.get("age_seconds") or 0.0)
        runner_terminal_reason = str(diagnostics.get("runner_terminal_reason") or dict(graph_run.get("diagnostics") or {}).get("runner_terminal_reason") or "")
        runner_budget_exhausted = bool(diagnostics.get("runner_budget_exhausted") is True or dict(graph_run.get("diagnostics") or {}).get("runner_budget_exhausted") is True)
        active_graph_work = self._active_graph_work(graph_state)

        if active_status and latest_event_age > DEFAULT_STALE_RUNTIME_SECONDS:
            flags.append("active_runtime_without_recent_event")
            recommended_actions.append("inspect_recent_events")
        if activity_state == "stale":
            flags.append("monitor_projected_stale_runtime")
            recommended_actions.append("inspect_runtime_monitor_signal")
        if graph_run_id and active_graph_work["active_work_order_count"] > 0 and active_status:
            flags.append("graph_has_active_work_orders")
            protection_reasons.append("graph_runtime_active_work_orders")
            recommended_actions.append("inspect_graph_checkpoint")
        if graph_run_id and runner_budget_exhausted and status in ACTIVE_TASK_STATUSES:
            flags.append("graph_runner_budget_exhausted_but_task_active")
            recommended_actions.append("close_runtime")
        if graph_run_id and runner_terminal_reason and status in ACTIVE_TASK_STATUSES and runner_terminal_reason != status:
            flags.append("graph_runner_terminal_reason_mismatch")
            recommended_actions.append("close_runtime")
        graph_status = str(graph_run.get("status") or "")
        if graph_run_id and graph_status in {"completed", "failed", "aborted", "cancelled", "canceled", "error"} and status in ACTIVE_TASK_STATUSES:
            flags.append("graph_run_terminal_but_root_task_active")
            recommended_actions.append("close_runtime")
        if not flags and active_status:
            recommended_actions.append("continue_monitoring")

        return {
            "authority": "health_system.task_record_runtime_diagnostics",
            "task_run_id": task_run_id,
            "graph_run_id": graph_run_id,
            "activity_state": activity_state,
            "is_running": bool(activity.get("is_running") is True),
            "is_waiting": bool(activity.get("is_waiting") is True),
            "latest_event_age_seconds": latest_event_age,
            "stale_threshold_seconds": DEFAULT_STALE_RUNTIME_SECONDS,
            "graph_run": self._graph_run_summary(graph_run),
            "graph_checkpoint": active_graph_work,
            "graph_checkpoint_deep_scan": bool(include_graph_checkpoint),
            "flags": list(dict.fromkeys(flags)),
            "protection_reasons": list(dict.fromkeys(protection_reasons)),
            "recommended_actions": list(dict.fromkeys(recommended_actions)),
            "diagnostic_state": "needs_attention" if flags else "observed",
        }

    def _graph_run_object(self, graph_run_id: str) -> dict[str, Any]:
        target = str(graph_run_id or "").strip()
        if not target:
            return {}
        store = getattr(self.runtime_host, "runtime_objects", None)
        getter = getattr(store, "get_object", None)
        if not callable(getter):
            return {}
        for ref in (f"rtobj:graph_run:{_safe_runtime_object_id(target)}", f"rtobj:graph_run:{target}"):
            try:
                payload = dict(getter(ref) or {})
            except Exception:
                payload = {}
            if payload:
                return payload
        return {}

    def _graph_checkpoint_state(self, graph_run_id: str) -> dict[str, Any]:
        target = str(graph_run_id or "").strip()
        if not target:
            return {}
        store = getattr(self.runtime_host, "graph_checkpoint_store", None)
        getter = getattr(store, "get_latest_state", None)
        if callable(getter):
            try:
                return dict(getter(target) or {})
            except Exception:
                return {}
        return {}

    def _active_graph_work(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        if not graph_state:
            return {
                "available": False,
                "status": "",
                "ready_node_ids": [],
                "running_node_ids": [],
                "active_work_orders": {},
                "active_work_order_count": 0,
                "event_cursor": -1,
                "terminal_reason": "",
            }
        active_work_orders = {
            str(key): str(value)
            for key, value in dict(graph_state.get("active_work_orders") or {}).items()
            if str(key) and str(value)
        }
        ready_node_ids = [str(item) for item in list(graph_state.get("ready_node_ids") or []) if str(item)]
        running_node_ids = [str(item) for item in list(graph_state.get("running_node_ids") or []) if str(item)]
        return {
            "available": True,
            "status": str(graph_state.get("status") or ""),
            "ready_node_ids": ready_node_ids,
            "running_node_ids": running_node_ids,
            "active_work_orders": active_work_orders,
            "active_work_order_count": len(active_work_orders),
            "event_cursor": int(graph_state.get("event_cursor") or -1),
            "terminal_reason": str(graph_state.get("terminal_reason") or ""),
        }

    @staticmethod
    def _graph_run_summary(graph_run: dict[str, Any]) -> dict[str, Any]:
        if not graph_run:
            return {"available": False}
        diagnostics = dict(graph_run.get("diagnostics") or {})
        return {
            "available": True,
            "graph_run_id": str(graph_run.get("graph_run_id") or ""),
            "task_run_id": str(graph_run.get("task_run_id") or ""),
            "status": str(graph_run.get("status") or ""),
            "terminal_reason": str(graph_run.get("terminal_reason") or ""),
            "runner_status": str(diagnostics.get("runner_status") or ""),
            "runner_terminal_reason": str(diagnostics.get("runner_terminal_reason") or ""),
            "runner_budget_exhausted": bool(diagnostics.get("runner_budget_exhausted") is True),
            "updated_at": float(graph_run.get("updated_at") or 0.0),
        }

    @staticmethod
    def _monitor_summary(*, monitor: dict[str, Any], activity: dict[str, Any]) -> dict[str, Any]:
        return {
            "available": bool(monitor),
            "bucket": str(monitor.get("bucket") or ""),
            "lifecycle": str(monitor.get("lifecycle") or ""),
            "activity_state": str(activity.get("activity_state") or ""),
            "is_running": bool(activity.get("is_running") is True),
            "is_waiting": bool(activity.get("is_waiting") is True),
            "is_interruptible": bool(activity.get("is_interruptible") is True),
            "is_resumable": bool(activity.get("is_resumable") is True),
            "control_reason": str(activity.get("control_reason") or ""),
        }

    def _storage_refs(self, *, task_run: Any, graph_run_id: str) -> dict[str, str]:
        runtime_root = self.layout.runtime_state_dir
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        refs = {
            "runtime_root": str(runtime_root),
            "state_index_task_runs": str(runtime_root / "state_index" / "task_runs"),
            "event_log": str(runtime_root / "events" / _safe_runtime_object_id(task_run_id)),
            "runtime_objects": str(runtime_root / "runtime_objects"),
            "prompt_accounting": str(runtime_root / "prompt_accounting"),
            "facts": str(runtime_root / "facts"),
            "health_system": str(self.layout.health_system_dir),
            "graph_checkpoints": str(runtime_root / "graph_checkpoints.sqlite"),
        }
        if graph_run_id:
            refs["graph_run_object"] = f"rtobj:graph_run:{_safe_runtime_object_id(graph_run_id)}"
        return refs

    def _monitor_by_task_run_id(self) -> dict[str, dict[str, Any]]:
        try:
            monitor = dict(self.runtime_host.list_global_live_monitor(limit=DEFAULT_MAINTENANCE_SCAN_LIMIT) or {})
        except Exception:
            return {}
        return {
            str(item.get("task_run_id") or ""): dict(item)
            for item in list(monitor.get("task_runs") or [])
            if isinstance(item, dict) and str(item.get("task_run_id") or "")
        }

    def _reported_task_run_ids(self) -> set[str]:
        if self.store is None:
            return set()
        reported: set[str] = set()
        try:
            for run in self.store.load_agent_runs():
                if run.task_run_id:
                    reported.add(run.task_run_id)
            for report in self.store.load_reports():
                for ref in report.evidence_refs:
                    if ref:
                        reported.add(str(ref))
        except Exception:
            return reported
        return reported

    def _token_summary(self, task_run_id: str) -> dict[str, Any]:
        summarizer = getattr(self.prompt_accounting_ledger, "summarize_task", None)
        if not callable(summarizer):
            return {}
        try:
            return dict(summarizer(task_run_id) or {})
        except Exception:
            return {}

    def _token_summary_index(self, task_runs: list[Any]) -> dict[str, dict[str, Any]]:
        summarizer = getattr(self.prompt_accounting_ledger, "summarize_tasks", None)
        task_run_ids = [
            str(getattr(task_run, "task_run_id", "") or "")
            for task_run in list(task_runs or [])
            if str(getattr(task_run, "task_run_id", "") or "")
        ]
        if not callable(summarizer) or not task_run_ids:
            return {}
        try:
            return {
                str(task_run_id): dict(summary or {})
                for task_run_id, summary in dict(summarizer(task_run_ids) or {}).items()
            }
        except Exception:
            return {}

    def _has_lineage(self, task_run: Any, *, diagnostics: dict[str, Any]) -> bool:
        lineage = dict(diagnostics.get("lineage") or {})
        origin = dict(diagnostics.get("origin") or {})
        parent_id = str(diagnostics.get("parent_task_run_id") or lineage.get("parent_task_run_id") or origin.get("parent_task_run_id") or "")
        root_id = str(diagnostics.get("root_task_run_id") or lineage.get("root_task_run_id") or "")
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        return bool(parent_id or (root_id and root_id != task_run_id))

    def _lineage_index(self) -> dict[str, Any]:
        parent_task_run_ids: set[str] = set()
        for other in self.state_index.list_recent_task_runs(limit=DEFAULT_MAINTENANCE_SCAN_LIMIT):
            diagnostics = dict(getattr(other, "diagnostics", {}) or {})
            lineage = dict(diagnostics.get("lineage") or {})
            origin = dict(diagnostics.get("origin") or {})
            parent_id = str(diagnostics.get("parent_task_run_id") or lineage.get("parent_task_run_id") or origin.get("parent_task_run_id") or "")
            root_id = str(diagnostics.get("root_task_run_id") or lineage.get("root_task_run_id") or "")
            if parent_id:
                parent_task_run_ids.add(parent_id)
            if root_id:
                parent_task_run_ids.add(root_id)
        return {"parent_task_run_ids": parent_task_run_ids}

    def _recent_maintenance_receipts(self) -> list[dict[str, Any]]:
        if self.store is None:
            return []
        try:
            receipts = self.store.load_receipts()
        except Exception:
            return []
        rows = [
            item.to_dict()
            for item in receipts
            if str(item.command_ref or "") == "health-system/task-records/prune"
        ]
        return sorted(rows, key=lambda item: float(item.get("created_at") or 0.0), reverse=True)[:10]

    def _build_receipt(self, *, result: dict[str, Any], dry_run: bool) -> HealthManagementReceipt:
        deleted = list(result.get("deleted_task_run_ids") or [])
        eligible = list(result.get("eligible_task_run_ids") or [])
        status = "preflight" if dry_run else "completed"
        accepted = not dry_run
        if not dry_run and eligible and not deleted:
            status = "failed"
            accepted = False
        elif not dry_run and not eligible:
            status = "blocked"
            accepted = False
        return HealthManagementReceipt(
            receipt_id=f"health-maintenance:{int(time.time() * 1000)}",
            command_ref="health-system/task-records/prune",
            accepted=accepted,
            status=status,
            admission_status="accepted",
            run_status=status,
            blocked_reasons=tuple(
                sorted(
                    {
                        str(reason)
                        for item in list(result.get("skipped") or [])
                        for reason in list(dict(item).get("protection_reasons") or [])
                    }
                )
            ),
            diagnostics={
                "maintenance": {
                    "operation": result.get("operation"),
                    "bucket": result.get("bucket"),
                    "candidate_count": result.get("candidate_count"),
                    "eligible_task_run_ids": list(eligible),
                    "deleted_task_run_ids": list(deleted),
                    "protected_task_run_ids": list(result.get("protected_task_run_ids") or []),
                    "deleted_counts": dict(result.get("deleted_counts") or {}),
                    "dry_run": dry_run,
                }
            },
            created_at=time.time(),
        )

    def _summary(self, records: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "candidate_count": len(records),
            "eligible_count": sum(1 for item in records if item.get("eligible")),
            "protected_count": sum(1 for item in records if not item.get("eligible")),
            "completed_count": sum(1 for item in records if str(item.get("bucket") or "") == "completed"),
            "failed_count": sum(1 for item in records if str(item.get("bucket") or "") == "failed"),
            "diagnostics_count": sum(1 for item in records if str(item.get("bucket") or "") == "diagnostics"),
        }

    @staticmethod
    def _policy(*, min_age_seconds: int) -> dict[str, Any]:
        return {
            "authority": "health_system.task_record_maintenance_policy",
            "min_age_seconds": max(0, int(min_age_seconds or 0)),
            "protected_statuses": sorted(ACTIVE_TASK_STATUSES),
            "failed_records_require_health_report": True,
            "requires_preflight": True,
            "requires_receipt": True,
        }

    @staticmethod
    def _requested_ids(task_run_ids: list[str] | None) -> list[str]:
        return sorted({str(item).strip() for item in list(task_run_ids or []) if str(item).strip()})

    @staticmethod
    def _normalize_bucket(bucket: str) -> str:
        normalized = str(bucket or "static").strip() or "static"
        if normalized not in MAINTENANCE_BUCKETS:
            raise ValueError(f"Unsupported task record maintenance bucket: {normalized}")
        return normalized

    @staticmethod
    def _bucket_from_status(status: str) -> str:
        if status in {"completed", "success"}:
            return "completed"
        if status in FAILED_TASK_STATUSES:
            return "failed"
        if status in ACTIVE_TASK_STATUSES:
            return "running"
        return "diagnostics"

    @staticmethod
    def _matches_bucket(record: dict[str, Any], *, bucket: str) -> bool:
        record_bucket = str(record.get("bucket") or "")
        resource_class = str(record.get("resource_class") or "")
        if bucket == "static":
            return resource_class == "static" and record_bucket in {"completed", "failed", "diagnostics"}
        if bucket == "diagnostics":
            diagnostics = dict(record.get("runtime_diagnostics") or {})
            return record_bucket == "diagnostics" or bool(diagnostics.get("flags"))
        return resource_class == "static" and record_bucket == bucket


def _project_runtime_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from harness.runtime.run_monitor.activity import project_runtime_activity

    return dict(project_runtime_activity(payload))


def _empty_recent_event_snapshot(task_run_id: str) -> dict[str, Any]:
    return {
        "available": False,
        "task_run_id": task_run_id,
        "event_type": "",
        "event_id": "",
        "created_at": 0.0,
        "age_seconds": 0.0,
    }


def _safe_runtime_object_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:180]
