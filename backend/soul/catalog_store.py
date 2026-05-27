from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .registry import read_text, write_text


RESOURCE_BUCKETS = {
    "worlds": "soul/worlds/catalog.json",
    "stories": "soul/stories/catalog.json",
    "cards": "soul/cards/catalog.json",
    "work_prompts": "soul/work_prompts/catalog.json",
    "common_contracts": "soul/common_contracts/catalog.json",
    "manifestations": "soul/manifestations/catalog.json",
}


class SoulCatalogStore:
    """Small JSON-file store for formal soul resources."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def load_bucket(self, bucket: str) -> list[dict[str, Any]]:
        path = self._bucket_path(bucket)
        if not path.exists():
            return []
        try:
            payload = json.loads(read_text(path) or "[]")
        except json.JSONDecodeError:
            return []
        if isinstance(payload, dict):
            items = payload.get("items", [])
        else:
            items = payload
        return [dict(item) for item in list(items or []) if isinstance(item, dict)]

    def save_bucket(self, bucket: str, items: list[dict[str, Any]]) -> None:
        path = self._bucket_path(bucket)
        payload = {
            "items": items,
            "authority": f"soul.{bucket}.catalog",
        }
        write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

    def ensure_bucket(self, bucket: str, defaults: list[dict[str, Any]]) -> list[dict[str, Any]]:
        current = self.load_bucket(bucket)
        if current:
            return current
        self.save_bucket(bucket, defaults)
        return defaults

    def _bucket_path(self, bucket: str) -> Path:
        if bucket not in RESOURCE_BUCKETS:
            raise KeyError(bucket)
        candidate = (self.base_dir / RESOURCE_BUCKETS[bucket]).resolve()
        root = self.base_dir.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("Invalid soul catalog path")
        return candidate


