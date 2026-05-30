from __future__ import annotations

import time
from typing import Any

from .models import HealthManagementReceipt


ACTIVE_TASK_STATUSES = {"created", "queued", "running", "waiting_executor", "waiting_approval", "paused"}
FAILED_TASK_STATUSES = {"failed", "aborted", "cancelled", "error"}
MAINTENANCE_BUCKETS = {"static", "completed", "failed", "diagnostics"}
DEFAULT_MIN_RECORD_AGE_SECONDS = 24 * 60 * 60


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
        records: list[dict[str, Any]] = []
        for task_run in self.state_index.list_task_runs():
            task_run_id = str(getattr(task_run, "task_run_id", "") or "")
            if not task_run_id:
                continue
            monitor = dict(monitor_by_id.get(task_run_id) or {})
            record = self._maintenance_record(
                task_run,
                monitor=monitor,
                reported_task_run_ids=reported_task_run_ids,
                min_age_seconds=min_age_seconds,
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
    ) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        status = str(getattr(task_run, "status", "") or "unknown")
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        created_at = float(getattr(task_run, "created_at", 0.0) or 0.0)
        updated_at = float(getattr(task_run, "updated_at", 0.0) or created_at or 0.0)
        age_seconds = max(0.0, self.now - max(created_at, updated_at))
        bucket = str(monitor.get("bucket") or self._bucket_from_status(status))
        resource_class = str(monitor.get("resource_class") or ("dynamic" if status in ACTIVE_TASK_STATUSES else "static"))
        event_count = self._event_count(task_run_id)
        token_summary = self._token_summary(task_run_id)
        protection_reasons: list[str] = []
        if status in ACTIVE_TASK_STATUSES or resource_class == "dynamic" or bucket == "running":
            protection_reasons.append("active_or_dynamic_runtime")
        if age_seconds < max(0, int(min_age_seconds or 0)):
            protection_reasons.append("recent_task_record")
        if status in FAILED_TASK_STATUSES and task_run_id not in reported_task_run_ids:
            protection_reasons.append("failed_without_health_report")
        if self._has_lineage(task_run, diagnostics=diagnostics):
            protection_reasons.append("task_lineage_record")
        if self._has_lineage_dependents(task_run_id):
            protection_reasons.append("task_lineage_parent")
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
            "prompt_accounting_record_count": int(token_summary.get("record_count") or 0),
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

    def _monitor_by_task_run_id(self) -> dict[str, dict[str, Any]]:
        try:
            monitor = dict(self.runtime_host.list_global_live_monitor(limit=500) or {})
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

    def _has_lineage(self, task_run: Any, *, diagnostics: dict[str, Any]) -> bool:
        lineage = dict(diagnostics.get("lineage") or {})
        origin = dict(diagnostics.get("origin") or {})
        parent_id = str(diagnostics.get("parent_task_run_id") or lineage.get("parent_task_run_id") or origin.get("parent_task_run_id") or "")
        root_id = str(diagnostics.get("root_task_run_id") or lineage.get("root_task_run_id") or "")
        origin_kind = str(diagnostics.get("origin_kind") or origin.get("origin_kind") or "")
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        return bool(parent_id or (root_id and root_id != task_run_id) or origin_kind == "checkout_resume")

    def _has_lineage_dependents(self, task_run_id: str) -> bool:
        if not task_run_id:
            return False
        for other in self.state_index.list_task_runs():
            diagnostics = dict(getattr(other, "diagnostics", {}) or {})
            lineage = dict(diagnostics.get("lineage") or {})
            origin = dict(diagnostics.get("origin") or {})
            parent_id = str(diagnostics.get("parent_task_run_id") or lineage.get("parent_task_run_id") or origin.get("parent_task_run_id") or "")
            root_id = str(diagnostics.get("root_task_run_id") or lineage.get("root_task_run_id") or "")
            if parent_id == task_run_id or root_id == task_run_id:
                return True
        return False

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
        return resource_class == "static" and record_bucket == bucket
