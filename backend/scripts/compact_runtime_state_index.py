from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.runtime_loop.state_index import RuntimeStateIndex


def compact_runtime_state_index(root_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        with tempfile.TemporaryDirectory(prefix="runtime-state-index-compact-") as tmp:
            tmp_root = Path(tmp)
            tmp_root.mkdir(parents=True, exist_ok=True)
            source = root_dir / "state_index.json"
            if source.exists():
                shutil.copy2(source, tmp_root / "state_index.json")
            state_index_dir = root_dir / "state_index"
            if state_index_dir.exists():
                shutil.copytree(state_index_dir, tmp_root / "state_index", dirs_exist_ok=True)
            runtime_objects_dir = root_dir / "runtime_objects"
            if runtime_objects_dir.exists():
                shutil.copytree(runtime_objects_dir, tmp_root / "runtime_objects", dirs_exist_ok=True)
            report = compact_runtime_state_index(tmp_root, dry_run=False)
            report["root_dir"] = str(root_dir)
            report["dry_run"] = True
            report.pop("backup_path", None)
            report.pop("report_path", None)
            return report

    state_index = RuntimeStateIndex(root_dir)
    before = state_index.read_snapshot()
    after = dict(before)

    task_runs = dict(before.get("task_runs") or {})
    coordination_runs = dict(before.get("coordination_runs") or {})
    after["task_runs"] = {
        key: state_index._compact_task_run_payload(dict(value))
        for key, value in task_runs.items()
        if isinstance(value, dict)
    }
    after["coordination_runs"] = {
        key: state_index._compact_coordination_run_payload(dict(value))
        for key, value in coordination_runs.items()
        if isinstance(value, dict)
    }
    after["updated_at"] = time.time()

    before_text = json.dumps(before, ensure_ascii=False, indent=2)
    after_text = json.dumps(after, ensure_ascii=False, indent=2)
    report = {
        "root_dir": str(root_dir),
        "dry_run": dry_run,
        "before_bytes": len(before_text.encode("utf-8")),
        "after_bytes": len(after_text.encode("utf-8")),
        "saved_bytes": len(before_text.encode("utf-8")) - len(after_text.encode("utf-8")),
        "task_run_count": len(task_runs),
        "coordination_run_count": len(coordination_runs),
        "forbidden_field_counts_after": _forbidden_field_counts(after),
        "authority": "orchestration.runtime_state_index_compaction_report",
    }
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup = root_dir / f"state_index.json.bak.{timestamp}"
    legacy_source = state_index.index_path
    shard_source = state_index.index_dir
    if legacy_source.exists():
        shutil.copy2(legacy_source, backup)
        report["backup_path"] = str(backup)
    elif shard_source.exists():
        shard_backup = root_dir / f"state_index.pre_compaction.{timestamp}"
        shutil.copytree(shard_source, shard_backup, dirs_exist_ok=True)
        report["backup_path"] = str(shard_backup)
    state_index.replace_snapshot(after)
    report_path = root_dir / f"state_index_compaction_report_{time.strftime('%Y%m%d-%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def _forbidden_field_counts(payload: dict[str, Any]) -> dict[str, int]:
    counts = {
        "task_graph_definition": 0,
        "task_graph_runtime_spec": 0,
        "agent_dispatch_plan": 0,
        "langgraph_runtime_state": 0,
        "coordination_graph_spec": 0,
        "task_graph_scheduler_state": 0,
    }
    for bucket in ("task_runs", "coordination_runs"):
        for item in dict(payload.get(bucket) or {}).values():
            diagnostics = dict(dict(item or {}).get("diagnostics") or {}) if isinstance(item, dict) else {}
            for key in counts:
                if key in diagnostics:
                    counts[key] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact runtime state_index.json into a lightweight index.")
    parser.add_argument("--root-dir", default="storage/runtime_state")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = compact_runtime_state_index(Path(args.root_dir), dry_run=bool(args.dry_run))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
