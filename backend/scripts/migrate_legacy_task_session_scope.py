from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from project_layout import ProjectLayout


def migrate_legacy_task_session_scope(*, backend_dir: Path, dry_run: bool = True) -> dict[str, Any]:
    sessions_dir = ProjectLayout.from_backend_dir(backend_dir).sessions_dir
    changed: list[dict[str, str]] = []
    scanned = 0
    for path in sorted(sessions_dir.glob("*.json")):
        scanned += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        scope = dict(payload.get("scope") or {})
        workspace_view = str(scope.get("workspace_view") or scope.get("view") or "").strip()
        task_environment_id = str(scope.get("task_environment_id") or scope.get("environment_id") or "").strip()
        if workspace_view != "task" or not task_environment_id:
            continue
        next_scope = {
            **scope,
            "workspace_view": "task_environment",
            "task_environment_id": task_environment_id,
            "project_id": str(scope.get("project_id") or "").strip(),
        }
        if "view" in next_scope:
            next_scope.pop("view", None)
        changed.append(
            {
                "session_id": str(payload.get("id") or path.stem),
                "from": workspace_view,
                "to": "task_environment",
                "task_environment_id": task_environment_id,
            }
        )
        if dry_run:
            continue
        payload["scope"] = next_scope
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "authority": "backend.scripts.migrate_legacy_task_session_scope",
        "dry_run": dry_run,
        "sessions_dir": str(sessions_dir),
        "scanned": scanned,
        "changed_count": len(changed),
        "changed": changed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize legacy workspace_view=task session scopes.")
    parser.add_argument("--backend-dir", default=str(BACKEND_DIR))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = migrate_legacy_task_session_scope(backend_dir=Path(args.backend_dir), dry_run=not args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
