from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


class TaskSystemStorage:
    """Narrow JSON storage adapter for task-system repositories."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.root = ProjectLayout.from_backend_dir(self.base_dir).tasks_dir

    def path(self, filename: str) -> Path:
        return self.root / filename

    def read_object(self, filename: str, fallback: dict[str, Any]) -> dict[str, Any]:
        path = self.path(filename)
        if not path.exists():
            return fallback
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback
        return loaded if isinstance(loaded, dict) else fallback

    def write_object(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
