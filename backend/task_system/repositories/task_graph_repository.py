from __future__ import annotations

from pathlib import Path
from typing import Any

from task_system.graphs.task_graph_models import TaskGraphDefinition, task_graph_from_dict
from task_system.repositories.common import next_prefixed_id
from task_system.storage import TaskSystemStorage


class TaskGraphRepository:
    def __init__(self, base_dir: Path) -> None:
        self.storage = TaskSystemStorage(base_dir)

    def list(self) -> list[TaskGraphDefinition]:
        payload = self.storage.read_object("task_graphs.json", {"task_graphs": []})
        graphs = [
            task_graph_from_dict(item)
            for item in list(payload.get("task_graphs") or [])
            if isinstance(item, dict)
        ]
        graphs = sorted(
            [item for item in graphs if item.graph_id],
            key=lambda item: (item.domain_id, item.title, item.graph_id),
        )
        normalized = [item.to_dict() for item in graphs]
        if payload.get("task_graphs") != normalized:
            self.storage.write_object("task_graphs.json", {"task_graphs": normalized})
        return graphs

    def get(self, graph_id: str) -> TaskGraphDefinition | None:
        target = str(graph_id or "").strip()
        return next((item for item in self.list() if item.graph_id == target), None)

    def next_id(self) -> str:
        return next_prefixed_id([item.graph_id for item in self.list()], prefix="graph.")

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
                "publish_state": publish_state,
                "enabled": enabled,
                "metadata": dict(metadata or {}),
            }
        )
        graphs = [item for item in self.list() if item.graph_id != target]
        graphs.append(graph)
        self.storage.write_object("task_graphs.json", {"task_graphs": [item.to_dict() for item in graphs]})
        return graph
