from __future__ import annotations

from pathlib import Path
from typing import Any

from task_system.storage import TaskSystemStorage

from .models import TaskNodeConfigurationSpec


class TaskNodeConfigurationRepository:
    def __init__(self, base_dir: Path) -> None:
        self.storage = TaskSystemStorage(base_dir)

    def list(self) -> list[TaskNodeConfigurationSpec]:
        payload = self.storage.read_object("node_configurations.json", {"node_configurations": []})
        specs = [
            TaskNodeConfigurationSpec.from_dict(item)
            for item in list(payload.get("node_configurations") or [])
            if isinstance(item, dict)
        ]
        normalized = [item.to_dict() for item in specs]
        if payload.get("node_configurations") != normalized:
            self.storage.write_object("node_configurations.json", {"node_configurations": normalized})
        return sorted(specs, key=lambda item: item.node_config_id)

    def get(self, node_config_id: str) -> TaskNodeConfigurationSpec | None:
        target = str(node_config_id or "").strip()
        return next((item for item in self.list() if item.node_config_id == target), None)

    def upsert(self, payload: dict[str, Any]) -> TaskNodeConfigurationSpec:
        spec = TaskNodeConfigurationSpec.from_dict(payload)
        _validate(spec)
        specs = [item for item in self.list() if item.node_config_id != spec.node_config_id]
        specs.append(spec)
        self.storage.write_object("node_configurations.json", {"node_configurations": [item.to_dict() for item in sorted(specs, key=lambda item: item.node_config_id)]})
        return spec

    def delete(self, node_config_id: str) -> str:
        target = str(node_config_id or "").strip()
        specs = [item for item in self.list() if item.node_config_id != target]
        if len(specs) == len(self.list()):
            raise KeyError(f"unknown node configuration: {node_config_id}")
        self.storage.write_object("node_configurations.json", {"node_configurations": [item.to_dict() for item in specs]})
        return target


def _validate(spec: TaskNodeConfigurationSpec) -> None:
    if not spec.node_config_id.startswith("nodecfg."):
        raise ValueError("node_config_id must start with nodecfg.")
    if not spec.title:
        raise ValueError("node configuration requires title")
