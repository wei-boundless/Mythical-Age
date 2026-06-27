from __future__ import annotations

import argparse
import json
import sys
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.project_layout import ProjectLayout
from runtime.cache_manager import (
    SANDBOX_CACHE_NAMESPACE,
    RuntimeCacheManager,
    safe_cache_namespace,
)
from runtime.storage_policy import DEFAULT_RUNTIME_STORAGE_POLICY, RuntimeStoragePolicy
from runtime.storage_policy import SECONDS_PER_DAY
from runtime.retention_archiver import RuntimeFactArchiver


DEBUG_TASK_PREFIXES = ("writing_graph_", "backend_8003_retest_")
DEBUG_TASK_SUFFIXES = ("_latest.json", "_stdout.txt", "_stderr.txt", ".ps1", ".log")
FORMAL_TASK_FILES = {
    "contract_specs.json",
    "graph_configs.json",
    "specific_task_records.json",
    "task_assignments.json",
    "task_communication_protocols.json",
    "task_domains.json",
    "task_execution_policies.json",
    "task_flow_contract_bindings.json",
    "task_flows.json",
    "task_graphs.json",
    "task_memory_request_profiles.json",
    "task_workflows.json",
}


@dataclass(slots=True)
class MaintenanceAction:
    action: str
    source: str
    target: str = ""
    size_bytes: int = 0
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "action": self.action,
            "source": self.source,
            "target": self.target,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / 1024 / 1024, 2),
            "reason": self.reason,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


class RuntimeArtifactMaintenance:
    def __init__(
        self,
        project_root: Path,
        *,
        stamp: str = "20260530",
        runtime_cache_ttl_seconds: int | None = None,
        storage_policy: RuntimeStoragePolicy = DEFAULT_RUNTIME_STORAGE_POLICY,
        pressure_mode: bool = False,
        prompt_hot_budget_mb: int | None = None,
        event_payload_hot_budget_mb: int | None = None,
        session_id: str = "",
        task_run_id: str = "",
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.stamp = stamp
        self.storage_policy = storage_policy
        self.pressure_mode = bool(pressure_mode)
        self.prompt_hot_budget_mb = prompt_hot_budget_mb
        self.event_payload_hot_budget_mb = event_payload_hot_budget_mb
        self.session_id = str(session_id or "").strip()
        self.task_run_id = str(task_run_id or "").strip()
        resolved_ttl = storage_policy.sandbox_cache_ttl_seconds if runtime_cache_ttl_seconds is None else runtime_cache_ttl_seconds
        self.runtime_cache_ttl_seconds = max(0, int(resolved_ttl or 0))

    @classmethod
    def from_backend_dir(
        cls,
        backend_dir: str | Path,
        *,
        stamp: str = "20260530",
        runtime_cache_ttl_seconds: int | None = None,
        storage_policy: RuntimeStoragePolicy = DEFAULT_RUNTIME_STORAGE_POLICY,
        pressure_mode: bool = False,
        prompt_hot_budget_mb: int | None = None,
        event_payload_hot_budget_mb: int | None = None,
        session_id: str = "",
        task_run_id: str = "",
    ) -> "RuntimeArtifactMaintenance":
        layout = ProjectLayout.from_backend_dir(backend_dir)
        return cls(
            layout.project_root,
            stamp=stamp,
            runtime_cache_ttl_seconds=runtime_cache_ttl_seconds,
            storage_policy=storage_policy,
            pressure_mode=pressure_mode,
            prompt_hot_budget_mb=prompt_hot_budget_mb,
            event_payload_hot_budget_mb=event_payload_hot_budget_mb,
            session_id=session_id,
            task_run_id=task_run_id,
        )

    def plan(self) -> dict[str, Any]:
        return self._result(self._planned_actions(), mode="dry_run")

    def _planned_actions(self) -> list[MaintenanceAction]:
        actions: list[MaintenanceAction] = []
        actions.extend(self._task_debug_snapshot_actions())
        actions.extend(self._existing_task_debug_snapshot_delete_actions())
        actions.extend(self._diagnostic_delete_actions())
        actions.extend(self._frontend_cache_actions())
        actions.extend(self._runtime_cache_actions())
        actions.extend(self._prompt_accounting_retention_actions())
        actions.extend(self._runtime_fact_archive_actions())
        return actions

    def execute(self) -> dict[str, Any]:
        actions = self._planned_actions()
        executed: list[MaintenanceAction] = []
        for action in actions:
            source = (self.project_root / action.source).resolve()
            if action.action == "move":
                target = (self.project_root / action.target).resolve()
                _assert_inside(self.project_root, source)
                _assert_inside(self.project_root, target)
                if not source.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                executed.append(action)
            elif action.action == "delete_file":
                _assert_inside(self.project_root, source)
                if source.exists() and source.is_file():
                    source.unlink()
                    executed.append(action)
            elif action.action == "delete_tree":
                _assert_inside(self.project_root, source)
                if source.exists() and source.is_dir():
                    shutil.rmtree(source)
                    executed.append(action)
            elif action.action == "compact_prompt_accounting":
                _assert_inside(self.project_root, source)
                result = self._execute_prompt_accounting_retention()
                if int(dict(result.get("summary") or {}).get("compactable_detail_rows") or 0) > 0:
                    executed.append(
                        MaintenanceAction(
                            action=action.action,
                            source=action.source,
                            size_bytes=action.size_bytes,
                            reason=action.reason,
                            metadata={
                                "mode": result.get("mode"),
                                "summary": dict(result.get("summary") or {}),
                                "retention_receipt": dict(result.get("retention_receipt") or {}),
                            },
                        )
                    )
            elif action.action == "archive_runtime_facts":
                _assert_inside(self.project_root, source)
                result = self._runtime_fact_archiver().execute()
                if int(dict(result.get("summary") or {}).get("action_count") or 0) > 0:
                    executed.append(
                        MaintenanceAction(
                            action=action.action,
                            source=action.source,
                            size_bytes=action.size_bytes,
                            reason=action.reason,
                            metadata={
                                "mode": result.get("mode"),
                                "summary": dict(result.get("summary") or {}),
                                "receipt_path": str(result.get("receipt_path") or ""),
                                "actions": list(result.get("actions") or []),
                            },
                        )
                    )
        result = self._result(executed, mode="execute")
        receipt_path = self.project_root / "storage" / "health_system" / "maintenance" / "artifact_maintenance_receipts" / f"artifact-maintenance-{int(time.time() * 1000)}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["receipt_path"] = _relative(self.project_root, receipt_path)
        return result

    def _task_debug_snapshot_actions(self) -> list[MaintenanceAction]:
        tasks_dir = self.project_root / "storage" / "tasks"
        if not tasks_dir.exists():
            return []
        actions: list[MaintenanceAction] = []
        target_root = Path("storage") / "tasks" / "debug_snapshots" / self.stamp
        for path in tasks_dir.iterdir():
            if not path.is_file() or path.name in FORMAL_TASK_FILES:
                continue
            if path.name.startswith(DEBUG_TASK_PREFIXES) or path.name.endswith(DEBUG_TASK_SUFFIXES):
                target = target_root / path.name
                actions.append(
                    MaintenanceAction(
                        action="move",
                        source=_relative(self.project_root, path),
                        target=target.as_posix(),
                        size_bytes=path.stat().st_size,
                        reason="partition_task_debug_snapshot",
                    )
                )
        return actions

    def _diagnostic_delete_actions(self) -> list[MaintenanceAction]:
        actions: list[MaintenanceAction] = []
        runtime_dir = self.project_root / "output" / "runtime"
        keep_runtime = {
            "backend-fixed-8003.pid",
            "frontend-fixed-3000.pid",
            "backend-fixed-8003.out.log",
            "backend-fixed-8003.err.log",
            "frontend-fixed-3000.out.log",
            "frontend-fixed-3000.err.log",
        }
        if runtime_dir.exists():
            for path in runtime_dir.iterdir():
                if path.is_file() and path.name not in keep_runtime:
                    actions.append(MaintenanceAction("delete_file", _relative(self.project_root, path), size_bytes=path.stat().st_size, reason="delete_unlinked_runtime_diagnostic"))
        playwright_dir = self.project_root / "output" / "playwright"
        if playwright_dir.exists():
            files = sorted((item for item in playwright_dir.iterdir() if item.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)
            for path in files[20:]:
                actions.append(MaintenanceAction("delete_file", _relative(self.project_root, path), size_bytes=path.stat().st_size, reason="keep_latest_20_playwright_artifacts"))
        return actions

    def _existing_task_debug_snapshot_delete_actions(self) -> list[MaintenanceAction]:
        target = self.project_root / "storage" / "tasks" / "debug_snapshots" / self.stamp
        if not target.exists() or not target.is_dir():
            return []
        return [
            MaintenanceAction(
                action="delete_tree",
                source=_relative(self.project_root, target),
                size_bytes=_tree_size(target),
                reason="delete_task_debug_snapshots_after_receipt",
            )
        ]

    def _frontend_cache_actions(self) -> list[MaintenanceAction]:
        next_dir = self.project_root / "frontend" / ".next"
        if not next_dir.exists():
            return []
        return [
            MaintenanceAction(
                action="delete_tree",
                source=_relative(self.project_root, next_dir),
                size_bytes=_tree_size(next_dir),
                reason="rebuildable_frontend_cache",
            )
        ]

    def _runtime_cache_actions(self) -> list[MaintenanceAction]:
        if self.runtime_cache_ttl_seconds <= 0:
            return []
        cache_root = self.project_root / "storage" / "runtime_cache"
        if not cache_root.exists():
            return []
        manager = RuntimeCacheManager(cache_root)
        cleanup = manager.cleanup(
            namespace=SANDBOX_CACHE_NAMESPACE,
            default_ttl_seconds=self.runtime_cache_ttl_seconds,
            protected_paths=_active_runtime_cache_paths(self.project_root),
            dry_run=True,
        )
        actions: list[MaintenanceAction] = []
        for item in list(cleanup.get("actions") or []):
            path = Path(str(dict(item).get("path") or "")).resolve()
            try:
                source = _relative(self.project_root, path)
            except ValueError:
                continue
            actions.append(
                MaintenanceAction(
                    action="delete_tree",
                    source=source,
                    size_bytes=int(dict(item).get("size_bytes") or 0),
                    reason=str(dict(item).get("reason") or "runtime_cache_ttl_expired"),
                )
            )
        return actions

    def _prompt_accounting_retention_actions(self) -> list[MaintenanceAction]:
        ledger = self._prompt_accounting_ledger()
        if ledger is None:
            return []
        preview = self._prompt_accounting_retention_preview()
        if int(dict(preview.get("summary") or {}).get("compactable_detail_rows") or 0) <= 0:
            return []
        source = Path("storage") / "runtime_state" / "prompt_accounting"
        return [
            MaintenanceAction(
                action="compact_prompt_accounting",
                source=source.as_posix(),
                size_bytes=_tree_size(self.project_root / source),
                reason="compact_prompt_accounting_details_to_l1_summary",
                metadata={
                    "mode": preview.get("mode"),
                    "policy": dict(preview.get("policy") or {}),
                    "summary": dict(preview.get("summary") or {}),
                    "retained_token_stats_path": str(preview.get("retained_token_stats_path") or ""),
                    "retention_receipts_path": str(preview.get("retention_receipts_path") or ""),
                },
            )
        ]

    def _prompt_accounting_retention_preview(self) -> dict[str, Any]:
        ledger = self._prompt_accounting_ledger()
        if ledger is None:
            return {}
        protection = _active_runtime_identity_protection(self.project_root)
        return ledger.build_retention_preview(
            cutoff_days=self._prompt_accounting_cutoff_days(),
            protected_task_run_ids=protection["task_run_ids"],
            protected_session_ids=protection["session_ids"],
        )

    def _execute_prompt_accounting_retention(self) -> dict[str, Any]:
        ledger = self._prompt_accounting_ledger()
        if ledger is None:
            return {}
        protection = _active_runtime_identity_protection(self.project_root)
        return ledger.compact_before(
            cutoff_days=self._prompt_accounting_cutoff_days(),
            dry_run=False,
            protected_task_run_ids=protection["task_run_ids"],
            protected_session_ids=protection["session_ids"],
        )

    def _prompt_accounting_ledger(self) -> Any | None:
        runtime_root = self.project_root / "storage" / "runtime_state"
        ledger_root = runtime_root / "prompt_accounting"
        if not ledger_root.exists():
            return None
        try:
            from runtime.prompt_accounting import PromptAccountingLedger
        except Exception:
            return None
        return PromptAccountingLedger(runtime_root)

    def _prompt_accounting_cutoff_days(self) -> int:
        return max(1, int(self.storage_policy.terminal_hot_seconds // SECONDS_PER_DAY))

    def _runtime_fact_archive_actions(self) -> list[MaintenanceAction]:
        plan = self._runtime_fact_archiver().plan()
        summary = dict(plan.get("summary") or {})
        if int(summary.get("action_count") or 0) <= 0:
            return []
        source = Path("storage") / "runtime_state"
        return [
            MaintenanceAction(
                action="archive_runtime_facts",
                source=source.as_posix(),
                size_bytes=int(summary.get("size_bytes") or 0),
                reason="archive_runtime_facts_to_l2_cold_storage",
                metadata={
                    "mode": plan.get("mode"),
                    "summary": summary,
                    "actions": list(plan.get("actions") or []),
                },
            )
        ]

    def _runtime_fact_archiver(self) -> RuntimeFactArchiver:
        return RuntimeFactArchiver(self.project_root, storage_policy=self.storage_policy)

    def _hot_cache_pressure_report(self) -> dict[str, Any]:
        prompt_report: dict[str, Any] = {}
        ledger = self._prompt_accounting_ledger()
        if ledger is not None and hasattr(ledger, "build_hot_cache_pressure_report"):
            try:
                prompt_report = dict(ledger.build_hot_cache_pressure_report() or {})
            except Exception:
                prompt_report = {"authority": "runtime.prompt_accounting.hot_cache_pressure", "error": "unavailable"}
        event_report = _event_payload_pressure_report(self.project_root)
        prompt_budget = self.prompt_hot_budget_mb
        event_budget = self.event_payload_hot_budget_mb
        return {
            "authority": "artifact_system.maintenance.hot_cache_pressure",
            "enabled": self.pressure_mode,
            "filters": {
                "session_id": self.session_id,
                "task_run_id": self.task_run_id,
            },
            "budgets": {
                "prompt_hot_budget_mb": prompt_budget,
                "event_payload_hot_budget_mb": event_budget,
            },
            "prompt_accounting": prompt_report,
            "event_payloads": event_report,
            "pressure": {
                "prompt_over_budget": (
                    prompt_budget is not None
                    and float(dict(dict(prompt_report.get("summary") or {})).get("size_mb") or 0.0) > float(prompt_budget)
                ),
                "event_payload_over_budget": (
                    event_budget is not None
                    and float(dict(dict(event_report.get("summary") or {})).get("size_mb") or 0.0) > float(event_budget)
                ),
            },
        }

    def _result(self, actions: list[MaintenanceAction], *, mode: str) -> dict[str, Any]:
        result = {
            "authority": "artifact_system.maintenance",
            "mode": mode,
            "storage_policy": self.storage_policy.to_dict(),
            "summary": {
                "action_count": len(actions),
                "size_bytes": sum(item.size_bytes for item in actions),
                "size_mb": round(sum(item.size_bytes for item in actions) / 1024 / 1024, 2),
                "runtime_fact_delete_count": 0,
            },
            "protected_rules": [
                "runtime_state/events not deleted",
                "runtime_state/events archive to L2 before leaving hot path",
                "graph_checkpoints keep latest checkpoint and archive sqlite before pruning old history",
                "prompt_accounting not deleted",
                "prompt_accounting old details compact to L1 retained token stats before rewrite",
                "task records stay under storage/tasks",
                "runtime_cache/sandboxes deletes only rebuildable cache dirs older than ttl",
                "active task_run sandbox cache dirs are protected",
                "user_asset and project_artifact durability classes are never automatic cache deletes",
            ],
            "actions": [item.to_dict() for item in actions],
            "updated_at": time.time(),
        }
        if self.pressure_mode:
            result["hot_cache_pressure"] = self._hot_cache_pressure_report()
        return result


def _tree_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            total += int(item.stat().st_size)
        except OSError:
            continue
    return total


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _assert_inside(root: Path, path: Path) -> None:
    path.resolve().relative_to(root.resolve())


def _event_payload_pressure_report(project_root: Path) -> dict[str, Any]:
    payload_root = project_root / "storage" / "runtime_state" / "event_payloads"
    rows: list[dict[str, Any]] = []
    if payload_root.exists():
        paths = [
            path
            for path in payload_root.glob("*/*.json")
            if path.is_file()
        ]
        paths.extend(
            path
            for path in payload_root.glob("hot/by_day/*/*/*.json")
            if path.is_file()
        )
        paths.extend(
            path
            for path in payload_root.glob("hot/by_time/*/*/*/*.json")
            if path.is_file()
        )
        for path in sorted(paths):
            size = path.stat().st_size
            rows.append(
                {
                    "path": _relative(project_root, path),
                    "bucket": _event_payload_bucket(payload_root, path),
                    "size_bytes": size,
                    "size_mb": round(size / 1024 / 1024, 2),
                }
            )
    buckets = {
        str(item.get("bucket") or "")
        for item in rows
        if str(item.get("bucket") or "") and str(item.get("bucket") or "") != "legacy_root"
    }
    total = sum(int(item.get("size_bytes") or 0) for item in rows)
    return {
        "authority": "runtime.event_payload.hot_cache_pressure",
        "layout": "event_payloads/hot/by_time/YYYYMMDD/HH/{digest_prefix}/{digest}.json",
        "summary": {
            "file_count": len(rows),
            "size_bytes": total,
            "size_mb": round(total / 1024 / 1024, 2),
            "bucket_count": len(buckets),
            "oldest_bucket": min(buckets) if buckets else "",
            "newest_bucket": max(buckets) if buckets else "",
        },
        "files": rows,
    }


def _event_payload_bucket(payload_root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to((payload_root / "hot" / "by_time").resolve())
    except ValueError:
        try:
            day_relative = path.resolve().relative_to((payload_root / "hot" / "by_day").resolve())
        except ValueError:
            return "legacy_root"
        day_parts = day_relative.parts
        return str(day_parts[0]) if day_parts else "legacy_root"
    parts = relative.parts
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return str(parts[0]) if parts else "legacy_root"


def _active_runtime_cache_paths(project_root: Path) -> list[Path]:
    protection = _active_runtime_identity_protection(project_root)
    sandbox_root = project_root / "storage" / "runtime_cache" / SANDBOX_CACHE_NAMESPACE
    return [
        (sandbox_root / safe_cache_namespace(task_run_id)).resolve()
        for task_run_id in sorted(protection["task_run_ids"])
    ]


def _active_runtime_identity_protection(project_root: Path) -> dict[str, set[str]]:
    runtime_root = project_root / "storage" / "runtime_state"
    if not runtime_root.exists():
        return {"task_run_ids": set(), "session_ids": set()}
    try:
        from runtime.memory.state_index import RuntimeStateIndex
    except Exception:
        return {"task_run_ids": set(), "session_ids": set()}
    try:
        task_runs = RuntimeStateIndex(runtime_root).list_recent_task_run_summaries(limit=800)
    except Exception:
        return {"task_run_ids": set(), "session_ids": set()}
    terminal = {"completed", "failed", "aborted"}
    task_run_ids: set[str] = set()
    session_ids: set[str] = set()
    for task_run in task_runs:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
        session_id = str(getattr(task_run, "session_id", "") or "").strip()
        status = str(getattr(task_run, "status", "") or "").strip()
        if not task_run_id or status in terminal:
            continue
        task_run_ids.add(task_run_id)
        if session_id:
            session_ids.add(session_id)
    return {"task_run_ids": task_run_ids, "session_ids": session_ids}


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe runtime artifact maintenance.")
    parser.add_argument("--backend-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stamp", default="20260530")
    parser.add_argument("--runtime-cache-ttl-seconds", type=int, default=None)
    parser.add_argument("--pressure-mode", action="store_true")
    parser.add_argument("--prompt-hot-budget-mb", type=int, default=None)
    parser.add_argument("--event-payload-hot-budget-mb", type=int, default=None)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--task-run-id", default="")
    args = parser.parse_args()
    maintenance = RuntimeArtifactMaintenance.from_backend_dir(
        args.backend_dir,
        stamp=args.stamp,
        runtime_cache_ttl_seconds=args.runtime_cache_ttl_seconds,
        pressure_mode=args.pressure_mode,
        prompt_hot_budget_mb=args.prompt_hot_budget_mb,
        event_payload_hot_budget_mb=args.event_payload_hot_budget_mb,
        session_id=args.session_id,
        task_run_id=args.task_run_id,
    )
    result = maintenance.execute() if args.execute else maintenance.plan()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

