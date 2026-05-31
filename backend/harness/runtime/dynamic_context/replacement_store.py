from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import json_clone, stable_json, stable_json_hash


@dataclass(frozen=True, slots=True)
class ReplacementRecord:
    replacement_key: str
    source_kind: str
    source_id: str
    content_hash: str
    projection_policy_hash: str
    projector_version: str
    projection: dict[str, Any]
    authority: str = "harness.runtime.dynamic_context.replacement_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "replacement_key": self.replacement_key,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "projection_policy_hash": self.projection_policy_hash,
            "projector_version": self.projector_version,
            "projection": dict(self.projection),
            "authority": self.authority,
        }


class ReplacementStore:
    def __init__(self, root_dir: Path, *, namespace: str = "dynamic_context") -> None:
        self.root_dir = Path(root_dir)
        self.base_dir = self.root_dir / namespace / "replacements"

    def key(
        self,
        *,
        source_kind: str,
        source_id: str,
        content_hash: str,
        projection_policy_hash: str,
        projector_version: str,
    ) -> str:
        seed = {
            "source_kind": str(source_kind or ""),
            "source_id": str(source_id or ""),
            "content_hash": str(content_hash or ""),
            "projection_policy_hash": str(projection_policy_hash or ""),
            "projector_version": str(projector_version or ""),
        }
        return "replacement:" + stable_json_hash(seed).removeprefix("sha256:")[:24]

    def get(self, replacement_key: str) -> dict[str, Any] | None:
        path = self._path_for_key(replacement_key)
        if not path.exists():
            return None
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        projection = payload.get("projection")
        return dict(projection) if isinstance(projection, dict) else None

    def get_or_put(
        self,
        *,
        source_kind: str,
        source_id: str,
        content: Any,
        projection_policy: dict[str, Any],
        projector_version: str,
        projection: dict[str, Any],
    ) -> tuple[dict[str, Any], ReplacementRecord]:
        content_hash = stable_json_hash(content)
        projection_policy_hash = stable_json_hash(projection_policy)
        replacement_key = self.key(
            source_kind=source_kind,
            source_id=source_id,
            content_hash=content_hash,
            projection_policy_hash=projection_policy_hash,
            projector_version=projector_version,
        )
        existing = self.get(replacement_key)
        record = ReplacementRecord(
            replacement_key=replacement_key,
            source_kind=str(source_kind or ""),
            source_id=str(source_id or ""),
            content_hash=content_hash,
            projection_policy_hash=projection_policy_hash,
            projector_version=str(projector_version or ""),
            projection=dict(existing or projection),
        )
        if existing is not None:
            return dict(existing), record
        self._write(record)
        return dict(projection), record

    def _write(self, record: ReplacementRecord) -> None:
        import json

        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for_key(record.replacement_key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(stable_json(record.to_dict()), encoding="utf-8")
        tmp.replace(path)

    def _path_for_key(self, replacement_key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(replacement_key or ""))
        if not safe:
            safe = "replacement_empty"
        return self.base_dir / f"{safe}.json"


class MemoryReplacementStore(ReplacementStore):
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}

    def get(self, replacement_key: str) -> dict[str, Any] | None:
        value = self._records.get(str(replacement_key or ""))
        return json_clone(value) if isinstance(value, dict) else None

    def _write(self, record: ReplacementRecord) -> None:
        self._records[record.replacement_key] = record.to_dict()["projection"]
