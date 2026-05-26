from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent_system.identity import normalize_agent_id
from task_system.registry.flow_models import TaskFlowDefinition
from task_system.repositories.common import merge_default_overlay_by_key, next_prefixed_id
from task_system.storage import TaskSystemStorage


class FlowRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        default_flows: Callable[[], tuple[TaskFlowDefinition, ...]],
        removed_config_predicate: Callable[[dict[str, object]], bool],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.default_flows = default_flows
        self.removed_config_predicate = removed_config_predicate

    def list(self) -> list[TaskFlowDefinition]:
        default_payload = [item.to_dict() for item in self.default_flows()]
        payload = self.storage.read_object("task_flows.json", {"flows": default_payload})
        merged_payload = merge_default_overlay_by_key(
            default_payload,
            [
                item
                for item in list(payload.get("flows") or [])
                if isinstance(item, dict) and not self.removed_config_predicate(item)
            ],
            key="flow_id",
        )
        flows: list[TaskFlowDefinition] = []
        for item in merged_payload:
            flows.append(
                TaskFlowDefinition(
                    flow_id=str(item.get("flow_id") or ""),
                    title=str(item.get("title") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "")),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_runtime_lane=str(item.get("default_runtime_lane") or ""),
                    default_memory_scope=str(item.get("default_memory_scope") or ""),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in flows]
        if payload.get("flows") != normalized:
            self.storage.write_object("task_flows.json", {"flows": normalized})
        return flows

    def get(self, flow_id: str) -> TaskFlowDefinition | None:
        target = str(flow_id or "").strip()
        return next((item for item in self.list() if item.flow_id == target), None)

    def next_id(self) -> str:
        return next_prefixed_id([item.flow_id for item in self.list()], prefix="flow.")

    def upsert(
        self,
        *,
        flow_id: str,
        title: str,
        input_contract_id: str,
        output_contract_id: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_runtime_lane: str,
        default_memory_scope: str,
        enabled: bool = True,
        metadata: dict[str, object] | None = None,
    ) -> TaskFlowDefinition:
        normalized_flow_id = str(flow_id or "").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        flow = TaskFlowDefinition(
            flow_id=normalized_flow_id,
            title=str(title or normalized_flow_id).strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            default_agent_id=normalize_agent_id(str(default_agent_id or "").strip()),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_runtime_lane=str(default_runtime_lane or "").strip(),
            default_memory_scope=str(default_memory_scope or "").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        flows = [item for item in self.list() if item.flow_id != normalized_flow_id]
        flows.append(flow)
        self.storage.write_object("task_flows.json", {"flows": [item.to_dict() for item in flows]})
        return flow
