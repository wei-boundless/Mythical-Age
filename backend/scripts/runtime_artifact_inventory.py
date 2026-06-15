from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from artifact_system import ArtifactInventoryService
from project_layout import ProjectLayout


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only inventory for runtime and artifact ports.")
    parser.add_argument("--backend-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    layout = ProjectLayout.from_backend_dir(args.backend_dir)
    inventory = ArtifactInventoryService(layout.project_root).build_inventory()
    if args.json:
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return 0
    summary = dict(inventory.get("summary") or {})
    print(f"artifact ports: {summary.get('port_count', 0)}")
    print(f"files: {summary.get('file_count', 0)}")
    print(f"size_mb: {summary.get('size_mb', 0)}")
    for port in sorted(inventory.get("ports") or [], key=lambda item: int(item.get("size_bytes") or 0), reverse=True):
        print(f"{port['port_id']}\t{port['size_mb']} MB\t{port['file_count']} files\t{port['artifact_class']}\t{port['retention_policy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
