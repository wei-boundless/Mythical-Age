from __future__ import annotations

from pathlib import Path
from typing import Callable

from task_system.registry.flow_models import SpecificTaskRecord, TaskFlowDefinition
from task_system.repositories.common import merge_default_overlay_by_key
from task_system.storage import TaskSystemStorage


class SpecificTaskRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        list_flows: Callable[[], list[TaskFlowDefinition]],
        record_from_flow: Callable[[TaskFlowDefinition], SpecificTaskRecord],
        synthetic_record_for_runtime: Callable[[str], SpecificTaskRecord | None],
        removed_config_predicate: Callable[[dict[str, object]], bool],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.list_flows = list_flows
        self.record_from_flow = record_from_flow
        self.synthetic_record_for_runtime = synthetic_record_for_runtime
        self.removed_config_predicate = removed_config_predicate

    def list(self) -> list[SpecificTaskRecord]:
        default_records = [self.record_from_flow(flow).to_dict() for flow in self.list_flows()]
        payload = self.storage.read_object(
            "specific_task_records.json",
            {"specific_task_records": default_records},
        )
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip()
        }
        records: list[SpecificTaskRecord] = []
        merged_payload = merge_default_overlay_by_key(
            [item for item in default_records if str(item.get("task_id") or "").strip() not in deleted_task_ids],
            [
                item
                for item in list(payload.get("specific_task_records") or [])
                if isinstance(item, dict)
                and str(item.get("task_id") or "").strip() not in deleted_task_ids
                and not self.removed_config_predicate(item)
            ],
            key="task_id",
        )
        for item in merged_payload:
            records.append(_specific_task_record_from_payload(item))
        if not records:
            records = [self.record_from_flow(flow) for flow in self.list_flows()]
        if records:
            normalized = [item.to_dict() for item in records]
            if payload.get("specific_task_records") != normalized:
                self.storage.write_object(
                    "specific_task_records.json",
                    {
                        "specific_task_records": normalized,
                        "deleted_task_ids": sorted(deleted_task_ids),
                    },
                )
        return records

    def get(self, task_id: str) -> SpecificTaskRecord | None:
        target = str(task_id or "").strip()
        stored_record = next((item for item in self.list() if item.task_id == target), None)
        if stored_record is not None:
            return stored_record
        return self.synthetic_record_for_runtime(target)

    def upsert(
        self,
        *,
        task_id: str,
        task_title: str,
        domain_id: str = "",
        description: str = "",
        enabled: bool = True,
        input_contract_id: str = "",
        output_contract_id: str = "",
        acceptance_profile_id: str = "",
        default_flow_contract_id: str = "",
        default_workflow_id: str = "",
        task_policy: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SpecificTaskRecord:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        record = SpecificTaskRecord(
            task_id=target,
            task_title=str(task_title or target).strip(),
            domain_id=str(domain_id or "").strip(),
            description=str(description or task_title or target).strip(),
            enabled=bool(enabled),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            acceptance_profile_id=str(acceptance_profile_id or "").strip(),
            default_flow_contract_id=str(default_flow_contract_id or "").strip(),
            default_workflow_id=str(default_workflow_id or "").strip(),
            task_policy=dict(task_policy or {}),
            metadata=dict(metadata or {}),
        )
        records = [item for item in self.list() if item.task_id != target]
        records.append(record)
        payload = self.storage.read_object("specific_task_records.json", {"specific_task_records": []})
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip() and str(item).strip() != target
        }
        self.storage.write_object(
            "specific_task_records.json",
            {
                "specific_task_records": [item.to_dict() for item in records],
                "deleted_task_ids": sorted(deleted_task_ids),
            },
        )
        return record

    def delete_many(self, task_ids: set[str]) -> set[str]:
        targets = {str(item or "").strip() for item in task_ids if str(item or "").strip()}
        if not targets:
            return set()
        payload = self.storage.read_object("specific_task_records.json", {"specific_task_records": []})
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip()
        }
        deleted_task_ids.update(targets)
        records = [item for item in self.list() if item.task_id not in targets]
        self.storage.write_object(
            "specific_task_records.json",
            {
                "specific_task_records": [item.to_dict() for item in records],
                "deleted_task_ids": sorted(deleted_task_ids),
            },
        )
        return targets


def _specific_task_record_from_payload(item: dict[str, object]) -> SpecificTaskRecord:
    return SpecificTaskRecord(
        task_id=str(item.get("task_id") or ""),
        task_title=str(item.get("task_title") or ""),
        domain_id=str(item.get("domain_id") or dict(item.get("metadata") or {}).get("domain_id") or ""),
        description=str(item.get("description") or ""),
        enabled=bool(item.get("enabled", True)),
        input_contract_id=str(item.get("input_contract_id") or ""),
        output_contract_id=str(item.get("output_contract_id") or ""),
        acceptance_profile_id=str(item.get("acceptance_profile_id") or ""),
        default_flow_contract_id=str(item.get("default_flow_contract_id") or ""),
        default_workflow_id=str(item.get("default_workflow_id") or ""),
        task_policy=dict(item.get("task_policy") or {}),
        metadata=dict(item.get("metadata") or {}),
    )


