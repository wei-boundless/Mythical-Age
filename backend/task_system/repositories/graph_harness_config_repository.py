from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.runtime.graph_config import GraphHarnessConfig, graph_harness_config_from_dict
from task_system.storage import TaskSystemStorage


class GraphHarnessConfigRepository:
    def __init__(self, base_dir: Path) -> None:
        self.storage = TaskSystemStorage(base_dir)

    def list(self) -> list[GraphHarnessConfig]:
        payload = self.storage.read_object("graph_harness_configs.json", {"configs": [], "published": {}})
        configs = [
            graph_harness_config_from_dict(item)
            for item in list(payload.get("configs") or [])
            if isinstance(item, dict)
        ]
        return sorted([item for item in configs if item.config_id], key=lambda item: (item.graph_id, item.publish_version, item.config_id))

    def get(self, config_id: str) -> GraphHarnessConfig | None:
        target = str(config_id or "").strip()
        return next((item for item in self.list() if item.config_id == target), None)

    def get_published_for_graph(self, graph_id: str) -> GraphHarnessConfig | None:
        target = str(graph_id or "").strip()
        if not target:
            return None
        payload = self.storage.read_object("graph_harness_configs.json", {"configs": [], "published": {}})
        config_id = str(dict(payload.get("published") or {}).get(target) or "").strip()
        if config_id:
            return self.get(config_id)
        return None

    def upsert(self, config: GraphHarnessConfig, *, publish: bool = True) -> GraphHarnessConfig:
        payload = self.storage.read_object("graph_harness_configs.json", {"configs": [], "published": {}})
        configs = [
            graph_harness_config_from_dict(item)
            for item in list(payload.get("configs") or [])
            if isinstance(item, dict)
        ]
        configs = [item for item in configs if item.config_id != config.config_id]
        configs.append(config)
        published = {
            str(key): str(value)
            for key, value in dict(payload.get("published") or {}).items()
            if str(key) and str(value)
        }
        if publish and config.status == "published":
            published[config.graph_id] = config.config_id
        self.storage.write_object(
            "graph_harness_configs.json",
            {
                "authority": "task_system.graph_harness_config_repository",
                "published": published,
                "configs": [item.to_dict() for item in sorted(configs, key=lambda item: (item.graph_id, item.publish_version, item.config_id))],
            },
        )
        return config

    def published_bindings(self) -> dict[str, str]:
        payload = self.storage.read_object("graph_harness_configs.json", {"configs": [], "published": {}})
        return {
            str(key): str(value)
            for key, value in dict(payload.get("published") or {}).items()
            if str(key) and str(value)
        }
