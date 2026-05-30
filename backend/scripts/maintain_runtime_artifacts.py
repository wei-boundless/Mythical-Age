from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


DEBUG_TASK_PREFIXES = ("writing_graph_", "backend_8003_retest_")
DEBUG_TASK_SUFFIXES = ("_latest.json", "_stdout.txt", "_stderr.txt", ".ps1", ".log")
FORMAL_TASK_FILES = {
    "contract_specs.json",
    "graph_harness_configs.json",
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
    "topology_templates.json",
}


@dataclass(slots=True)
class MaintenanceAction:
    action: str
    source: str
    target: str = ""
    size_bytes: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "source": self.source,
            "target": self.target,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / 1024 / 1024, 2),
            "reason": self.reason,
        }


class RuntimeArtifactMaintenance:
    def __init__(self, project_root: Path, *, stamp: str = "20260530") -> None:
        self.project_root = Path(project_root).resolve()
        self.stamp = stamp

    @classmethod
    def from_backend_dir(cls, backend_dir: str | Path, *, stamp: str = "20260530") -> "RuntimeArtifactMaintenance":
        layout = ProjectLayout.from_backend_dir(backend_dir)
        return cls(layout.project_root, stamp=stamp)

    def plan(self) -> dict[str, Any]:
        return self._result(self._planned_actions(), mode="dry_run")

    def _planned_actions(self) -> list[MaintenanceAction]:
        actions: list[MaintenanceAction] = []
        actions.extend(self._task_debug_snapshot_actions())
        actions.extend(self._existing_task_debug_snapshot_delete_actions())
        actions.extend(self._diagnostic_delete_actions())
        actions.extend(self._frontend_cache_actions())
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

    def _result(self, actions: list[MaintenanceAction], *, mode: str) -> dict[str, Any]:
        return {
            "authority": "artifact_system.maintenance",
            "mode": mode,
            "summary": {
                "action_count": len(actions),
                "size_bytes": sum(item.size_bytes for item in actions),
                "size_mb": round(sum(item.size_bytes for item in actions) / 1024 / 1024, 2),
                "runtime_fact_delete_count": 0,
            },
            "protected_rules": [
                "runtime_state/events not deleted",
                "graph_checkpoints not deleted",
                "prompt_accounting not deleted",
                "task records stay under storage/tasks",
            ],
            "actions": [item.to_dict() for item in actions],
            "updated_at": time.time(),
        }


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe runtime artifact maintenance.")
    parser.add_argument("--backend-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stamp", default="20260530")
    args = parser.parse_args()
    maintenance = RuntimeArtifactMaintenance.from_backend_dir(args.backend_dir, stamp=args.stamp)
    result = maintenance.execute() if args.execute else maintenance.plan()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
