from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


class ModalityArtifactStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.base_dir = ProjectLayout.from_backend_dir(self.root_dir).modality_artifacts_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def load_json(self, modality: str, relative_source: str, kind: str) -> dict[str, Any] | None:
        path = self._artifact_path(modality, relative_source, kind)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_json(self, modality: str, relative_source: str, kind: str, payload: dict[str, Any]) -> Path:
        path = self._artifact_path(modality, relative_source, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _artifact_path(self, modality: str, relative_source: str, kind: str) -> Path:
        digest = hashlib.md5(relative_source.encode("utf-8")).hexdigest()
        safe_modality = modality.strip().lower().replace("\\", "-").replace("/", "-")
        safe_kind = kind.strip().lower().replace("\\", "-").replace("/", "-")
        return self.base_dir / safe_modality / f"{digest}.{safe_kind}.json"
