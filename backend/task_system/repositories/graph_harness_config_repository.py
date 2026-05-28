from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.graph.models import GraphHarnessConfig, graph_harness_config_from_dict
from task_system.storage import TaskSystemStorage


class GraphHarnessConfigRepository:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = TaskSystemStorage(base_dir)

    def list(self) -> list[GraphHarnessConfig]:
        payload = self.storage.read_object("graph_harness_configs.json", {"configs": [], "published_bindings": {}})
        configs = [
            graph_harness_config_from_dict(item)
            for item in list(payload.get("configs") or [])
            if isinstance(item, dict)
        ]
        return sorted(configs, key=lambda item: (item.graph_id, item.publish_version, item.config_id))

    def get(self, config_id: str) -> GraphHarnessConfig | None:
        target = str(config_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list() if item.config_id == target), None)

    def get_published_for_graph(self, graph_id: str) -> GraphHarnessConfig | None:
        target = str(graph_id or "").strip()
        if not target:
            return None
        config_id = self.published_bindings().get(target, "")
        if config_id:
            config = self.get(config_id)
            if config is not None and config.status == "published":
                return config
        return None

    def upsert(self, config: Any, *, publish: bool = True) -> GraphHarnessConfig:
        item = config if isinstance(config, GraphHarnessConfig) else graph_harness_config_from_dict(dict(config or {}))
        if item.status not in {"published", "archived"}:
            raise ValueError("GraphHarnessConfigRepository only stores published or archived immutable configs")
        if item.content_hash and item.content_hash != item.expected_content_hash():
            raise ValueError("GraphHarnessConfig content_hash mismatch")
        if not item.content_hash:
            item = item.with_content_identity()
        payload = self.storage.read_object("graph_harness_configs.json", {"configs": [], "published_bindings": {}})
        configs = [
            graph_harness_config_from_dict(raw)
            for raw in list(payload.get("configs") or [])
            if isinstance(raw, dict)
        ]
        configs = [existing for existing in configs if existing.config_id != item.config_id]
        configs.append(item)
        bindings = {
            str(key): str(value)
            for key, value in dict(payload.get("published_bindings") or {}).items()
            if str(key) and str(value)
        }
        if publish:
            bindings[item.graph_id] = item.config_id
        self.storage.write_object(
            "graph_harness_configs.json",
            {
                "configs": [stored.to_dict() for stored in sorted(configs, key=lambda value: (value.graph_id, value.config_id))],
                "published_bindings": bindings,
            },
        )
        return item

    def published_bindings(self) -> dict[str, str]:
        payload = self.storage.read_object("graph_harness_configs.json", {"configs": [], "published_bindings": {}})
        return {
            str(key): str(value)
            for key, value in dict(payload.get("published_bindings") or {}).items()
            if str(key) and str(value)
        }
