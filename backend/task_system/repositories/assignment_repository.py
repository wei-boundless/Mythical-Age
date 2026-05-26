from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent_system.identity import normalize_agent_id, normalize_agent_id_sequence
from task_system.registry.flow_models import (
    SpecificTaskRecord,
    TaskAssignment,
    TaskFlowDefinition,
)
from task_system.repositories.common import merge_items_by_key
from task_system.storage import TaskSystemStorage


class AssignmentRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        list_flows: Callable[[], list[TaskFlowDefinition]],
        list_specific_task_records: Callable[[], list[SpecificTaskRecord]],
        get_flow: Callable[[str], TaskFlowDefinition | None],
        synthetic_record_for_runtime: Callable[[str], SpecificTaskRecord | None],
        removed_config_predicate: Callable[[dict[str, object]], bool],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.list_flows = list_flows
        self.list_specific_task_records = list_specific_task_records
        self.get_flow = get_flow
        self.synthetic_record_for_runtime = synthetic_record_for_runtime
        self.removed_config_predicate = removed_config_predicate

    def list(self) -> list[TaskAssignment]:
        flow_by_id = {item.flow_id: item for item in self.list_flows()}
        default_assignments = [
            self.assignment_from_specific_task_record(
                item,
                flow=flow_by_id.get(str(item.default_flow_contract_id or f"flow.{item.task_id.removeprefix('task.')}").strip()),
            ).to_dict()
            for item in self.list_specific_task_records()
        ]
        payload = self.storage.read_object(
            "task_assignments.json",
            {"assignments": default_assignments},
        )
        merged_payload = merge_items_by_key(
            default_assignments,
            [
                item
                for item in list(payload.get("assignments") or [])
                if isinstance(item, dict) and not self.removed_config_predicate(item)
            ],
            key="task_id",
        )
        assignments = [_assignment_from_dict(item) for item in merged_payload]
        normalized = [item.to_dict() for item in assignments]
        if payload.get("assignments") != normalized:
            self.storage.write_object("task_assignments.json", {"assignments": normalized})
        return assignments

    def get(self, task_id: str) -> TaskAssignment | None:
        target = str(task_id or "").strip()
        stored_assignment = next((item for item in self.list() if item.task_id == target), None)
        if stored_assignment is not None:
            return stored_assignment
        synthetic_record = self.synthetic_record_for_runtime(target)
        if synthetic_record is None:
            return None
        return self.assignment_from_specific_task_record(synthetic_record)

    def upsert(self, assignment: TaskAssignment) -> TaskAssignment:
        assignments = [item for item in self.list() if item.task_id != assignment.task_id]
        assignments.append(assignment)
        self.storage.write_object("task_assignments.json", {"assignments": [item.to_dict() for item in assignments]})
        return assignment

    def delete_for_task_ids(self, task_ids: set[str]) -> set[str]:
        targets = {str(item or "").strip() for item in task_ids if str(item or "").strip()}
        if not targets:
            return set()
        assignments = [item for item in self.list() if item.task_id not in targets]
        self.storage.write_object("task_assignments.json", {"assignments": [item.to_dict() for item in assignments]})
        return targets

    def assignment_from_specific_task_record(
        self,
        record: SpecificTaskRecord,
        *,
        flow: TaskFlowDefinition | None = None,
    ) -> TaskAssignment:
        flow_id = str(record.default_flow_contract_id or f"flow.{record.task_id.removeprefix('task.')}").strip()
        task_policy = dict(record.task_policy or {})
        task_structure = dict(task_policy.get("task_structure") or {})
        safety_policy = dict(task_policy.get("safety_policy") or {})
        flow = flow if flow is not None else self.get_flow(flow_id)
        default_agent_id = str(getattr(flow, "default_agent_id", "") or "agent:0").strip() or "agent:0"
        flow_metadata = dict(getattr(flow, "metadata", {}) or {})
        task_structure = {
            **task_structure,
            **(
                {
                    "task_graph_id": str(flow_metadata.get("task_graph_id") or flow_metadata.get("graph_id") or "").strip(),
                    "communication_protocol_id": str(flow_metadata.get("communication_protocol_id") or "").strip(),
                    "topology_template_id": str(flow_metadata.get("topology_template_id") or "").strip(),
                    "agent_group_id": str(flow_metadata.get("agent_group_id") or "").strip(),
                }
                if flow is not None
                else {}
            ),
        }
        workflow_file_ref = f"workflow:{record.default_workflow_id}" if record.default_workflow_id else ""
        return TaskAssignment(
            task_id=record.task_id,
            task_title=record.task_title,
            task_kind="specific_task",
            flow_id=flow_id,
            domain_id=record.domain_id,
            runtime_lane=record.runtime_lane or str(task_structure.get("runtime_lane_hint") or getattr(flow, "default_runtime_lane", "") or ""),
            default_agent_id=default_agent_id,
            participant_agent_ids=(),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=workflow_file_ref,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=safety_policy,
            task_structure=task_structure,
            enabled=record.enabled,
            metadata=dict(record.metadata or {}),
        )


def _assignment_from_dict(payload: dict[str, object]) -> TaskAssignment:
    return TaskAssignment(
        task_id=str(payload.get("task_id") or ""),
        task_title=str(payload.get("task_title") or ""),
        task_kind=str(payload.get("task_kind") or "specific_task"),
        flow_id=str(payload.get("flow_id") or ""),
        domain_id=str(payload.get("domain_id") or dict(payload.get("metadata") or {}).get("domain_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or dict(payload.get("task_structure") or {}).get("runtime_lane_hint") or ""),
        default_agent_id=normalize_agent_id(str(payload.get("default_agent_id") or "agent:0")),
        participant_agent_ids=normalize_agent_id_sequence(str(item) for item in list(payload.get("participant_agent_ids") or []) if str(item)),
        workflow_id=str(payload.get("workflow_id") or ""),
        workflow_file_ref=str(payload.get("workflow_file_ref") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        safety_policy=dict(payload.get("safety_policy") or {}),
        task_structure=dict(payload.get("task_structure") or {}),
        enabled=bool(payload.get("enabled", True)),
        metadata=dict(payload.get("metadata") or {}),
    )
