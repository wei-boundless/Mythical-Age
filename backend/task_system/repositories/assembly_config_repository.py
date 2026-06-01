from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent_system.identity import normalize_agent_id
from task_system.registry.flow_models import (
    GeneralTaskProfile,
    SpecificTaskRecord,
    TaskAssignment,
    TaskExecutionPolicy,
    TaskFlowContractBinding,
    TaskMemoryRequestProfile,
)
from task_system.repositories.common import merge_default_overlay_by_key, merge_items_by_key
from task_system.storage import TaskSystemStorage


class TaskAssemblyConfigRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        list_general_task_profiles: Callable[[], list[GeneralTaskProfile]],
        list_specific_task_records: Callable[[], list[SpecificTaskRecord]],
        list_task_assignments: Callable[[], list[TaskAssignment]],
        synthetic_task_from_general_profile: Callable[[GeneralTaskProfile], TaskAssignment],
        default_flow_contract_binding: Callable[[TaskAssignment], TaskFlowContractBinding],
        default_flow_contract_binding_from_specific_record: Callable[[SpecificTaskRecord], TaskFlowContractBinding],
        default_execution_policy: Callable[[TaskAssignment], TaskExecutionPolicy],
        default_memory_request_profile: Callable[[TaskAssignment], TaskMemoryRequestProfile],
        default_memory_request_profile_from_specific_record: Callable[[SpecificTaskRecord], TaskMemoryRequestProfile],
        removed_config_predicate: Callable[[dict[str, object]], bool],
        normalize_execution_mode: Callable[[str], str],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.list_general_task_profiles = list_general_task_profiles
        self.list_specific_task_records = list_specific_task_records
        self.list_task_assignments = list_task_assignments
        self.synthetic_task_from_general_profile = synthetic_task_from_general_profile
        self.default_flow_contract_binding = default_flow_contract_binding
        self.default_flow_contract_binding_from_specific_record = default_flow_contract_binding_from_specific_record
        self.default_execution_policy = default_execution_policy
        self.default_memory_request_profile = default_memory_request_profile
        self.default_memory_request_profile_from_specific_record = default_memory_request_profile_from_specific_record
        self.removed_config_predicate = removed_config_predicate
        self.normalize_execution_mode = normalize_execution_mode

    def list_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        default_bindings = [
            *[
                self.default_flow_contract_binding(self.synthetic_task_from_general_profile(item)).to_dict()
                for item in self.list_general_task_profiles()
            ],
            *[self.default_flow_contract_binding_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = self.storage.read_object("task_flow_contract_bindings.json", {"flow_contract_bindings": default_bindings})
        deleted_task_ids = self._deleted_specific_task_ids()
        merged_payload = merge_items_by_key(
            [item for item in default_bindings if str(item.get("task_id") or "").strip() not in deleted_task_ids],
            [
                item
                for item in list(payload.get("flow_contract_bindings") or [])
                if isinstance(item, dict)
                and str(item.get("task_id") or "").strip() not in deleted_task_ids
                and not self.removed_config_predicate(item)
            ],
            key="binding_id",
        )
        bindings = [_flow_contract_binding_from_dict(item) for item in merged_payload]
        normalized = [item.to_dict() for item in bindings]
        if payload.get("flow_contract_bindings") != normalized:
            self.storage.write_object("task_flow_contract_bindings.json", {"flow_contract_bindings": normalized})
        return bindings

    def list_explicit_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        payload = self.storage.read_object("task_flow_contract_bindings.json", {"flow_contract_bindings": []})
        return [
            _flow_contract_binding_from_dict(item)
            for item in list(payload.get("flow_contract_bindings") or [])
            if isinstance(item, dict)
        ]

    def get_flow_contract_binding(self, task_id: str) -> TaskFlowContractBinding | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_flow_contract_bindings() if item.task_id == target), None)

    def upsert_flow_contract_binding(
        self,
        *,
        task_id: str,
        flow_contract_id: str,
        override_policy: str = "task_default",
        verification_gate_profile: str = "",
        fallback_policy: str = "fail_closed",
        metadata: dict[str, object] | None = None,
    ) -> TaskFlowContractBinding:
        target = _validate_task_or_general_id(task_id)
        binding = TaskFlowContractBinding(
            binding_id=f"taskflowbind:{target}",
            task_id=target,
            flow_contract_id=str(flow_contract_id or "").strip(),
            override_policy=str(override_policy or "task_default").strip(),
            verification_gate_profile=str(verification_gate_profile or "").strip(),
            fallback_policy=str(fallback_policy or "fail_closed").strip(),
            metadata=dict(metadata or {}),
        )
        bindings = [item for item in self.list_flow_contract_bindings() if item.task_id != target]
        bindings.append(binding)
        self.storage.write_object("task_flow_contract_bindings.json", {"flow_contract_bindings": [item.to_dict() for item in bindings]})
        return binding

    def list_execution_policies(self) -> list[TaskExecutionPolicy]:
        default_tasks = [
            *[self.synthetic_task_from_general_profile(item) for item in self.list_general_task_profiles()],
            *self.list_task_assignments(),
        ]
        default_plans = [self.default_execution_policy(item).to_dict() for item in default_tasks]
        payload = self.storage.read_object("task_execution_policies.json", {"execution_policies": default_plans})
        deleted_task_ids = self._deleted_specific_task_ids()
        merged_payload = merge_default_overlay_by_key(
            [item for item in default_plans if str(item.get("task_id") or "").strip() not in deleted_task_ids],
            [
                item
                for item in list(payload.get("execution_policies") or [])
                if isinstance(item, dict)
                and str(item.get("task_id") or "").strip() not in deleted_task_ids
                and not self.removed_config_predicate(item)
            ],
            key="policy_id",
        )
        plans = [_execution_policy_from_dict(item, normalize_execution_mode=self.normalize_execution_mode) for item in merged_payload]
        normalized = [item.to_dict() for item in plans]
        if payload.get("execution_policies") != normalized:
            self.storage.write_object("task_execution_policies.json", {"execution_policies": normalized})
        return plans

    def list_explicit_execution_policies(self) -> list[TaskExecutionPolicy]:
        payload = self.storage.read_object("task_execution_policies.json", {"execution_policies": []})
        return [
            _execution_policy_from_dict(item, normalize_execution_mode=self.normalize_execution_mode)
            for item in list(payload.get("execution_policies") or [])
            if isinstance(item, dict)
        ]

    def get_execution_policy(self, task_id: str) -> TaskExecutionPolicy | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_execution_policies() if item.task_id == target), None)

    def upsert_execution_policy(
        self,
        *,
        task_id: str,
        execution_mode: str,
        default_agent_id: str = "agent:0",
        allow_worker_agent_spawn: bool = False,
        worker_agent_blueprint_id: str = "",
        worker_agent_naming_rule: str = "",
        notes: str = "",
        metadata: dict[str, object] | None = None,
    ) -> TaskExecutionPolicy:
        target = _validate_task_or_general_id(task_id)
        plan = TaskExecutionPolicy(
            policy_id=f"taskexecpol:{target}",
            task_id=target,
            execution_mode=self.normalize_execution_mode(execution_mode),
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            allow_worker_agent_spawn=bool(allow_worker_agent_spawn),
            worker_agent_blueprint_id=str(worker_agent_blueprint_id or "").strip(),
            worker_agent_naming_rule=str(worker_agent_naming_rule or "").strip(),
            notes=str(notes or "").strip(),
            metadata=dict(metadata or {}),
        )
        plans = [item for item in self.list_execution_policies() if item.task_id != target]
        plans.append(plan)
        self.storage.write_object("task_execution_policies.json", {"execution_policies": [item.to_dict() for item in plans]})
        return plan

    def list_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        default_profiles = [
            *[
                self.default_memory_request_profile(self.synthetic_task_from_general_profile(item)).to_dict()
                for item in self.list_general_task_profiles()
            ],
            *[self.default_memory_request_profile_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = self.storage.read_object("task_memory_request_profiles.json", {"memory_request_profiles": default_profiles})
        deleted_task_ids = self._deleted_specific_task_ids()
        merged_payload = merge_items_by_key(
            [item for item in default_profiles if str(item.get("task_id") or "").strip() not in deleted_task_ids],
            [
                item
                for item in list(payload.get("memory_request_profiles") or [])
                if isinstance(item, dict)
                and str(item.get("task_id") or "").strip() not in deleted_task_ids
                and not self.removed_config_predicate(item)
            ],
            key="profile_id",
        )
        profiles = [_memory_request_profile_from_dict(item) for item in merged_payload]
        normalized = [item.to_dict() for item in profiles]
        if payload.get("memory_request_profiles") != normalized:
            self.storage.write_object("task_memory_request_profiles.json", {"memory_request_profiles": normalized})
        return profiles

    def list_explicit_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        payload = self.storage.read_object("task_memory_request_profiles.json", {"memory_request_profiles": []})
        return [
            _memory_request_profile_from_dict(item)
            for item in list(payload.get("memory_request_profiles") or [])
            if isinstance(item, dict)
        ]

    def get_memory_request_profile(self, task_id: str) -> TaskMemoryRequestProfile | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_memory_request_profiles() if item.task_id == target), None)

    def upsert_memory_request_profile(
        self,
        *,
        task_id: str,
        requested_memory_layers: tuple[str, ...] = (),
        requested_topics: tuple[str, ...] = (),
        memory_priority: str = "normal",
        writeback_policy: str = "task_default",
        allow_long_term_memory: bool = False,
        memory_scope_hint: str = "",
        metadata: dict[str, object] | None = None,
    ) -> TaskMemoryRequestProfile:
        target = _validate_task_or_general_id(task_id)
        profile = TaskMemoryRequestProfile(
            profile_id=f"taskmem:{target}",
            task_id=target,
            requested_memory_layers=tuple(str(value).strip() for value in requested_memory_layers if str(value).strip()),
            requested_topics=tuple(str(value).strip() for value in requested_topics if str(value).strip()),
            memory_priority=str(memory_priority or "normal").strip(),
            writeback_policy=str(writeback_policy or "task_default").strip(),
            allow_long_term_memory=bool(allow_long_term_memory),
            memory_scope_hint=str(memory_scope_hint or "").strip(),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_memory_request_profiles() if item.task_id != target]
        profiles.append(profile)
        self.storage.write_object("task_memory_request_profiles.json", {"memory_request_profiles": [item.to_dict() for item in profiles]})
        return profile

    def delete_for_task_ids(self, task_ids: set[str]) -> None:
        targets = {str(item or "").strip() for item in task_ids if str(item or "").strip()}
        if not targets:
            return
        self.storage.write_object(
            "task_flow_contract_bindings.json",
            {"flow_contract_bindings": [item.to_dict() for item in self.list_flow_contract_bindings() if item.task_id not in targets]},
        )
        self.storage.write_object(
            "task_execution_policies.json",
            {"execution_policies": [item.to_dict() for item in self.list_execution_policies() if item.task_id not in targets]},
        )
        self.storage.write_object(
            "task_memory_request_profiles.json",
            {"memory_request_profiles": [item.to_dict() for item in self.list_memory_request_profiles() if item.task_id not in targets]},
        )

    def _deleted_specific_task_ids(self) -> set[str]:
        payload = self.storage.read_object("specific_task_records.json", {"deleted_task_ids": []})
        return {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip()
        }


def _flow_contract_binding_from_dict(item: dict[str, object]) -> TaskFlowContractBinding:
    return TaskFlowContractBinding(
        binding_id=str(item.get("binding_id") or ""),
        task_id=str(item.get("task_id") or ""),
        flow_contract_id=str(item.get("flow_contract_id") or ""),
        override_policy=str(item.get("override_policy") or "task_default"),
        verification_gate_profile=str(item.get("verification_gate_profile") or ""),
        fallback_policy=str(item.get("fallback_policy") or ""),
        metadata=dict(item.get("metadata") or {}),
    )


def _execution_policy_from_dict(
    item: dict[str, object],
    *,
    normalize_execution_mode: Callable[[str], str],
) -> TaskExecutionPolicy:
    return TaskExecutionPolicy(
        policy_id=str(item.get("policy_id") or "").strip(),
        task_id=str(item.get("task_id") or ""),
        execution_mode=normalize_execution_mode(str(item.get("execution_mode") or "single_agent")),
        default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "agent:0")),
        allow_worker_agent_spawn=bool(item.get("allow_worker_agent_spawn", False)),
        worker_agent_blueprint_id=str(item.get("worker_agent_blueprint_id") or ""),
        worker_agent_naming_rule=str(item.get("worker_agent_naming_rule") or ""),
        notes=str(item.get("notes") or ""),
        metadata=dict(item.get("metadata") or {}),
    )


def _memory_request_profile_from_dict(item: dict[str, object]) -> TaskMemoryRequestProfile:
    return TaskMemoryRequestProfile(
        profile_id=str(item.get("profile_id") or ""),
        task_id=str(item.get("task_id") or ""),
        requested_memory_layers=tuple(str(value).strip() for value in list(item.get("requested_memory_layers") or []) if str(value).strip()),
        requested_topics=tuple(str(value).strip() for value in list(item.get("requested_topics") or []) if str(value).strip()),
        memory_priority=str(item.get("memory_priority") or "normal"),
        writeback_policy=str(item.get("writeback_policy") or "task_default"),
        allow_long_term_memory=bool(item.get("allow_long_term_memory", False)),
        memory_scope_hint=str(item.get("memory_scope_hint") or ""),
        metadata=dict(item.get("metadata") or {}),
    )


def _validate_task_or_general_id(task_id: str) -> str:
    target = str(task_id or "").strip()
    if not target.startswith(("task.", "general.")):
        raise ValueError("task_id must start with task. or general.")
    return target


