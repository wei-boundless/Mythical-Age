from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from task_system.graph_instances.models import GraphTaskInstance, graph_task_instance_from_dict
from task_system.storage import TaskSystemStorage


GRAPH_TASK_INSTANCES_STORAGE_FILE = "graph_task_instances.json"


class GraphTaskInstanceRepository:
    authority = "task_system.graph_task_instance_repository"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = TaskSystemStorage(self.base_dir)

    def list(self) -> list[GraphTaskInstance]:
        payload = self.storage.read_object(GRAPH_TASK_INSTANCES_STORAGE_FILE, {"instances": []})
        instances = [
            graph_task_instance_from_dict(item)
            for item in list(payload.get("instances") or [])
            if isinstance(item, dict)
        ]
        instances = sorted(
            [item for item in instances if item.graph_task_instance_id],
            key=lambda item: (item.graph_id, -float(item.updated_at or item.created_at or 0.0), item.title),
        )
        normalized = [item.to_dict() for item in instances]
        if payload.get("instances") != normalized:
            self.storage.write_object(GRAPH_TASK_INSTANCES_STORAGE_FILE, {"instances": normalized})
        return instances

    def list_for_graph(self, graph_id: str) -> list[GraphTaskInstance]:
        target = str(graph_id or "").strip()
        return [item for item in self.list() if item.graph_id == target]

    def get(self, instance_id: str) -> GraphTaskInstance | None:
        target = str(instance_id or "").strip()
        return next((item for item in self.list() if item.graph_task_instance_id == target), None)

    def require(self, instance_id: str) -> GraphTaskInstance:
        instance = self.get(instance_id)
        if instance is None:
            raise KeyError(f"graph task instance not found: {instance_id}")
        return instance

    def create(
        self,
        *,
        graph_id: str,
        title: str,
        description: str = "",
        root_session_id: str = "",
        metadata: dict[str, Any] | None = None,
        instance_id: str = "",
    ) -> GraphTaskInstance:
        now = time.time()
        target = str(instance_id or "").strip() or self.next_id(graph_id)
        instance = GraphTaskInstance(
            graph_task_instance_id=target,
            graph_id=str(graph_id or "").strip(),
            title=str(title or "").strip() or str(graph_id or "图任务实例"),
            description=str(description or "").strip(),
            status="idle",
            root_session_id=str(root_session_id or "").strip(),
            active_graph_run_id="",
            graph_run_ids=(),
            file_space_id=target,
            artifact_index_id=f"artifact_index.{target}",
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        return self.upsert(instance)

    def upsert(self, instance: GraphTaskInstance) -> GraphTaskInstance:
        instances = [item for item in self.list() if item.graph_task_instance_id != instance.graph_task_instance_id]
        instances.append(instance)
        self.storage.write_object(
            GRAPH_TASK_INSTANCES_STORAGE_FILE,
            {"instances": [item.to_dict() for item in sorted(instances, key=lambda item: item.graph_task_instance_id)]},
        )
        return instance

    def patch(self, instance_id: str, patch: dict[str, Any]) -> GraphTaskInstance:
        current = self.require(instance_id)
        payload = current.to_dict()
        for key in ("title", "description", "status", "root_session_id", "active_graph_run_id", "file_space_id", "artifact_index_id"):
            if key in patch:
                payload[key] = patch[key]
        if "metadata" in patch:
            payload["metadata"] = {**dict(payload.get("metadata") or {}), **dict(patch.get("metadata") or {})}
        payload["updated_at"] = time.time()
        return self.upsert(graph_task_instance_from_dict(payload))

    def record_run(
        self,
        instance_id: str,
        *,
        graph_run_id: str,
        status: str = "running",
        metadata: dict[str, Any] | None = None,
    ) -> GraphTaskInstance:
        current = self.require(instance_id)
        target_run = str(graph_run_id or "").strip()
        if not target_run:
            raise ValueError("graph_run_id is required")
        graph_run_ids = list(current.graph_run_ids)
        if target_run not in graph_run_ids:
            graph_run_ids.append(target_run)
        payload = current.to_dict()
        payload.update(
            {
                "active_graph_run_id": target_run,
                "graph_run_ids": graph_run_ids,
                "status": str(status or "running").strip() or "running",
                "updated_at": time.time(),
                "metadata": {**dict(current.metadata or {}), **dict(metadata or {})},
            }
        )
        return self.upsert(graph_task_instance_from_dict(payload))

    def next_id(self, graph_id: str) -> str:
        prefix = f"gti.{_safe_id(graph_id)}."
        return f"{prefix}{uuid.uuid4().hex[:12]}"


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    safe = safe.strip("._-")
    return safe or "graph_task"

