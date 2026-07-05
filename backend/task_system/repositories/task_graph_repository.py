from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from task_system.graphs.task_graph_models import TaskGraphDefinition, task_graph_from_dict
from task_system.repositories.common import next_prefixed_id
from task_system.storage import TaskSystemStorage


TASK_GRAPHS_DIR = "task_graphs"


class TaskGraphRepository:
    def __init__(self, base_dir: Path) -> None:
        self.storage = TaskSystemStorage(base_dir)

    def list(self) -> list[TaskGraphDefinition]:
        graphs_by_id: dict[str, TaskGraphDefinition] = {}
        for graph in self._folder_graphs():
            if graph.graph_id:
                graphs_by_id[graph.graph_id] = graph
        graphs = list(graphs_by_id.values())
        graphs = sorted(
            [item for item in graphs if item.graph_id],
            key=lambda item: (item.domain_id, item.title, item.graph_id),
        )
        self._write_graph_files(graphs)
        return graphs

    def get(self, graph_id: str) -> TaskGraphDefinition | None:
        target = str(graph_id or "").strip()
        if not target:
            return None
        folder_payload = self.storage.read_object(_graph_object_path(target), {})
        if folder_payload:
            return task_graph_from_dict(folder_payload)
        return next((item for item in self.list() if item.graph_id == target), None)

    def next_id(self) -> str:
        return next_prefixed_id([item.graph_id for item in self.list()], prefix="graph.")

    def delete(self, graph_id: str) -> bool:
        target = str(graph_id or "").strip()
        if not target:
            return False
        path = self.storage.path(_graph_object_path(target))
        if not path.exists():
            return False
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return True

    def upsert(
        self,
        *,
        graph_id: str,
        title: str,
        domain_id: str = "",
        graph_kind: str = "single_agent",
        entry_node_id: str = "",
        output_node_id: str = "",
        nodes: tuple[dict[str, Any], ...] = (),
        edges: tuple[dict[str, Any], ...] = (),
        graph_contract_id: str = "",
        contract_bindings: dict[str, Any] | None = None,
        default_protocol_id: str = "",
        working_memory_policy_profile_id: str = "",
        working_memory_policy: dict[str, Any] | None = None,
        runtime_policy: dict[str, Any] | None = None,
        context_policy: dict[str, Any] | None = None,
        loop_frames: tuple[dict[str, Any], ...] = (),
        publish_state: str = "draft",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TaskGraphDefinition:
        target = str(graph_id or "").strip()
        if not target.startswith("graph."):
            raise ValueError("graph_id must start with graph.")
        graph = task_graph_from_dict(
            {
                "graph_id": target,
                "title": title,
                "domain_id": domain_id,
                "graph_kind": graph_kind,
                "entry_node_id": entry_node_id,
                "output_node_id": output_node_id,
                "nodes": [dict(item) for item in nodes],
                "edges": [dict(item) for item in edges],
                "graph_contract_id": graph_contract_id,
                "contract_bindings": dict(contract_bindings or {}),
                "default_protocol_id": default_protocol_id,
                "working_memory_policy_profile_id": working_memory_policy_profile_id,
                "working_memory_policy": dict(working_memory_policy or {}),
                "runtime_policy": dict(runtime_policy or {}),
                "context_policy": dict(context_policy or {}),
                "loop_frames": [dict(item) for item in loop_frames if isinstance(item, dict)],
                "publish_state": publish_state,
                "enabled": enabled,
                "metadata": dict(metadata or {}),
            }
        )
        self.storage.write_object(_graph_object_path(target), graph.to_dict())
        return graph

    def _folder_graphs(self) -> list[TaskGraphDefinition]:
        root = self.storage.path(TASK_GRAPHS_DIR)
        if not root.exists():
            return []
        graphs: list[TaskGraphDefinition] = []
        for graph_file in sorted(root.glob("*/graph.json")):
            relative = graph_file.relative_to(self.storage.root).as_posix()
            payload = self.storage.read_object(relative, {})
            if payload:
                graphs.append(task_graph_from_dict(payload))
        return graphs

    def _write_graph_files(self, graphs: list[TaskGraphDefinition]) -> None:
        for graph in graphs:
            self.storage.write_object(_graph_object_path(graph.graph_id), graph.to_dict())


def _graph_object_path(graph_id: str) -> str:
    return f"{TASK_GRAPHS_DIR}/{_safe_graph_dir(graph_id)}/graph.json"


def _safe_graph_dir(graph_id: str) -> str:
    raw = str(graph_id or "").strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    if len(safe) > 120:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        safe = f"{safe[:103].rstrip('._-')}_{digest}"
    return safe or "graph"
