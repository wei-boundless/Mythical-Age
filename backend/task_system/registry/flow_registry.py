from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.identity import normalize_agent_id, normalize_agent_id_sequence
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry

from task_system.registry.flow_models import (
    AgentTaskCarryingProfile,
    AgentTaskConnectionProfile,
    GeneralTaskProfile,
    SpecificTaskRecord,
    TaskDomainRecord,
    TaskExecutionPolicy,
    TaskAgentBinding,
    TaskAssignment,
    TaskCommunicationProtocol,
    TaskFlowDefinition,
    TaskFlowContractBinding,
    TaskMemoryRequestProfile,
)
from task_system.contracts.contract_models import TaskContractDescriptor
from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    task_graph_from_dict,
)
from task_system.repositories import (
    AssignmentRepository,
    ExecutableGraphConfigRepository,
    TaskAssemblyConfigRepository,
    FlowRepository,
    SpecificTaskRepository,
    TaskDomainRepository,
    TaskCommunicationProtocolRepository,
    TaskGraphRepository,
)
from task_system.services.graph_task_registry import TaskGraphRegistryService
from task_system.services.registry_overview import TaskRegistryOverviewBuilder
from task_system.registry.workflow_registry import TaskWorkflowRegistry


CONTRACT_TITLE_MAP: dict[str, str] = {
    "UserMessage": "用户消息",
    "WorkspaceTaskInput": "工作区任务输入",
    "WorkspacePatchTaskInput": "工作区补丁任务输入",
    "AssistantFinalAnswer": "最终回答",
    "LightWebGameTaskInput": "网页小游戏任务输入",
    "LightWebGameResult": "网页游戏产物",
    "ArcadeGameBundleTaskInput": "复合网页游戏任务输入",
    "ShortStoryTaskInput": "短篇小说任务输入",
    "ShortStoryResult": "短篇小说成稿",
    "HealthIssue": "健康问题",
}


CONTRACT_KIND_LABELS: dict[str, str] = {
    "input": "输入契约",
    "output": "输出契约",
    "flow": "流程契约",
    "payload": "通信载荷契约",
}

def normalize_task_execution_mode(value: str) -> str:
    normalized = str(value or "").strip()
    return normalized or "single_agent"


def default_health_task_flows() -> tuple[TaskFlowDefinition, ...]:
    return ()


def default_task_flows() -> tuple[TaskFlowDefinition, ...]:
    return default_health_task_flows()


def _system_task_specs() -> dict[str, dict[str, Any]]:
    return {}


def _is_removed_health_task_config(payload: dict[str, Any]) -> bool:
    metadata = dict(payload.get("metadata") or {})
    values = (
        payload.get("task_id"),
        payload.get("flow_id"),
        payload.get("workflow_id"),
        payload.get("default_workflow_id"),
        payload.get("default_flow_contract_id"),
        payload.get("flow_contract_id"),
        payload.get("binding_id"),
        payload.get("policy_id"),
        payload.get("profile_id"),
        metadata.get("task_resource"),
        metadata.get("source_flow_id"),
    )
    return any(
        str(value or "").strip().startswith(("task.health.", "flow.health.", "workflow.health."))
        for value in values
    )


def _synthetic_specific_task_record_for_runtime(task_id: str) -> SpecificTaskRecord | None:
    target = str(task_id or "").strip()
    spec = _system_task_specs().get(target)
    if spec is None:
        return None
    workflow_id = str(spec.get("workflow_id") or "").strip()
    return SpecificTaskRecord(
        task_id=target,
        task_title=str(spec.get("title") or target),
        domain_id=str(spec.get("domain_id") or "").strip(),
        description=str(spec.get("description") or spec.get("title") or target),
        enabled=True,
        input_contract_id=str(spec.get("input_contract_id") or "UserMessage"),
        output_contract_id=str(spec.get("output_contract_id") or "AssistantFinalAnswer"),
        acceptance_profile_id="",
        default_flow_contract_id=workflow_id.replace("workflow.", "flow.", 1) if workflow_id else f"flow.{target.removeprefix('task.')}",
        default_workflow_id=workflow_id,
        task_policy={
            "safety_policy": dict(spec.get("safety_policy") or {}),
            "task_structure": {
                "memory_scope_hint": "conversation",
            },
        },
        metadata={
            "managed_by": "task_system",
            "source": "task_system_runtime_projection",
        },
    )
def _next_prefixed_id(existing_ids: list[str], *, prefix: str, width: int = 6) -> str:
    max_value = 0
    for raw in existing_ids:
        value = str(raw or "").strip()
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):]
        if suffix.isdigit():
            max_value = max(max_value, int(suffix))
    return f"{prefix}{max_value + 1:0{width}d}"


def default_task_domains() -> tuple[TaskDomainRecord, ...]:
    return ()

def default_general_task_profiles() -> tuple[GeneralTaskProfile, ...]:
    return ()

def default_task_communication_protocols() -> tuple[TaskCommunicationProtocol, ...]:
    return ()

def _default_flow_contract_binding(task: TaskAssignment) -> TaskFlowContractBinding:
    flow_contract_id = str(task.flow_id or "").strip()
    return TaskFlowContractBinding(
        binding_id=f"taskflowbind:{task.task_id}",
        task_id=task.task_id,
        flow_contract_id=flow_contract_id,
        override_policy="task_default",
        verification_gate_profile=str(dict(task.safety_policy or {}).get("verification_mode") or ""),
        fallback_policy="fail_closed",
        metadata={"derived_from": "task_assignment"},
    )


def _default_execution_policy(task: TaskAssignment) -> TaskExecutionPolicy:
    participant_ids = tuple(str(item).strip() for item in task.participant_agent_ids if str(item).strip())
    task_structure = dict(task.task_structure or {})
    task_metadata = dict(task.metadata or {})
    runtime_limits = dict(task_structure.get("runtime_limits") or {})
    task_graph_id = str(
        task_structure.get("task_graph_id") or task_structure.get("graph_id") or task_metadata.get("task_graph_id") or ""
    ).strip()
    communication_protocol_id = str(
        task_structure.get("communication_protocol_id") or task_metadata.get("communication_protocol_id") or ""
    ).strip()
    agent_group_id = str(task_structure.get("agent_group_id") or task_metadata.get("agent_group_id") or "").strip()
    execution_chain_type = str(task.to_dict().get("execution_chain_type") or "").strip() or (
        "task_graph_chain" if task_graph_id else "agent_harness_chain"
    )
    return TaskExecutionPolicy(
        policy_id=f"taskexecpol:{task.task_id}",
        task_id=task.task_id,
        execution_mode="agent_harness" if not participant_ids else "task_graph",
        default_agent_id=normalize_agent_id(str(task.default_agent_id or "agent:0").strip() or "agent:0"),
        allow_worker_agent_spawn=False,
        worker_agent_blueprint_id="",
        worker_agent_naming_rule="",
        notes="Derived from task assignment defaults.",
        metadata={
            "derived_from": "task_assignment",
            "participant_agent_ids": list(participant_ids),
            "runtime_limits": runtime_limits,
            "execution_chain_type": execution_chain_type,
            "task_graph_id": task_graph_id,
            "graph_id": task_graph_id,
            "communication_protocol_id": communication_protocol_id,
            "agent_group_id": agent_group_id,
        },
    )


def _default_memory_request_profile(task: TaskAssignment) -> TaskMemoryRequestProfile:
    memory_scope_hint = str(dict(task.task_structure or {}).get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [task.task_id or "general_task"]
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{task.task_id}",
        task_id=task.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="normal",
        writeback_policy="task_default",
        allow_long_term_memory=False,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "task_assignment"},
    )


def _specific_task_record_from_assignment(task: TaskAssignment) -> SpecificTaskRecord:
    return SpecificTaskRecord(
        task_id=task.task_id,
        task_title=task.task_title,
        domain_id=task.domain_id,
        description=str(dict(task.metadata or {}).get("description") or task.task_title),
        enabled=task.enabled,
        input_contract_id=task.input_contract_id,
        output_contract_id=task.output_contract_id,
        acceptance_profile_id=str(dict(task.metadata or {}).get("acceptance_profile_id") or ""),
        default_flow_contract_id=str(task.flow_id or ""),
        default_workflow_id=str(task.workflow_id or ""),
        task_policy={
            "safety_policy": dict(task.safety_policy or {}),
            "task_structure": dict(task.task_structure or {}),
            "runtime_limits": dict(dict(task.task_structure or {}).get("runtime_limits") or {}),
        },
        metadata=dict(task.metadata or {}),
    )


def _default_flow_contract_binding_from_specific_record(record: SpecificTaskRecord) -> TaskFlowContractBinding:
    return TaskFlowContractBinding(
        binding_id=f"taskflowbind:{record.task_id}",
        task_id=record.task_id,
        flow_contract_id=str(record.default_flow_contract_id or "").strip(),
        override_policy="task_default",
        verification_gate_profile=str(dict(record.task_policy or {}).get("verification_gate_profile") or ""),
        fallback_policy="fail_closed",
        metadata={"derived_from": "specific_task_record"},
    )


def _default_memory_request_profile_from_specific_record(record: SpecificTaskRecord) -> TaskMemoryRequestProfile:
    task_policy = dict(record.task_policy or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    memory_scope_hint = str(task_structure.get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [record.task_id or "specific_task"]
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{record.task_id}",
        task_id=record.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="normal",
        writeback_policy="task_default",
        allow_long_term_memory=False,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "specific_task_record"},
    )


def _synthetic_task_from_general_profile(profile: GeneralTaskProfile) -> TaskAssignment:
    return TaskAssignment(
        task_id=profile.profile_id,
        task_title=profile.title,
        task_kind="general_task",
        flow_id="flow.general.main_conversation",
        domain_id="domain.general",
        default_agent_id=normalize_agent_id(str(profile.default_agent_id or "agent:0").strip() or "agent:0"),
        participant_agent_ids=(),
        workflow_id=str(profile.default_workflow_id or ""),
        workflow_file_ref=f"workflow:{profile.default_workflow_id}" if profile.default_workflow_id else "",
        input_contract_id=str(profile.input_contract_id or ""),
        output_contract_id=str(profile.output_contract_id or ""),
        safety_policy={},
        task_structure={
            "entry_channel": str(profile.entry_channel or "main_conversation"),
            "memory_scope_hint": "conversation_readonly",
        },
        enabled=profile.enabled,
        metadata=dict(profile.metadata or {}),
    )


class TaskFlowRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.agent_group_registry = None
        self.agent_runtime_registry = AgentRuntimeRegistry(self.base_dir)
        self.workflow_registry = TaskWorkflowRegistry(self.base_dir)
        self.flow_repository = FlowRepository(
            self.base_dir,
            default_flows=default_task_flows,
            default_general_profiles=default_general_task_profiles,
            removed_config_predicate=_is_removed_health_task_config,
        )
        self.specific_task_repository = SpecificTaskRepository(
            self.base_dir,
            list_flows=self.flow_repository.list,
            record_from_flow=self._specific_task_record_from_flow,
            synthetic_record_for_runtime=_synthetic_specific_task_record_for_runtime,
            removed_config_predicate=_is_removed_health_task_config,
        )
        self.domain_repository = TaskDomainRepository(
            self.base_dir,
            default_domains=default_task_domains,
        )
        self.assignment_repository = AssignmentRepository(
            self.base_dir,
            list_flows=self.list_flows,
            list_specific_task_records=self.list_specific_task_records,
            get_flow=self.get_flow,
            synthetic_record_for_runtime=_synthetic_specific_task_record_for_runtime,
            removed_config_predicate=_is_removed_health_task_config,
        )
        self.assembly_config_repository = TaskAssemblyConfigRepository(
            self.base_dir,
            list_general_task_profiles=self.list_general_task_profiles,
            list_specific_task_records=self.list_specific_task_records,
            list_task_assignments=self.list_task_assignments,
            synthetic_task_from_general_profile=_synthetic_task_from_general_profile,
            default_flow_contract_binding=_default_flow_contract_binding,
            default_flow_contract_binding_from_specific_record=_default_flow_contract_binding_from_specific_record,
            default_execution_policy=_default_execution_policy,
            default_memory_request_profile=_default_memory_request_profile,
            default_memory_request_profile_from_specific_record=_default_memory_request_profile_from_specific_record,
            removed_config_predicate=_is_removed_health_task_config,
            normalize_execution_mode=normalize_task_execution_mode,
        )
        self.task_graph_repository = TaskGraphRepository(self.base_dir)
        self.executable_graph_config_repository = ExecutableGraphConfigRepository(self.base_dir)
        self.protocol_repository = TaskCommunicationProtocolRepository(
            self.base_dir,
            default_protocols=default_task_communication_protocols,
        )
        self.graph_service = TaskGraphRegistryService(self, self.base_dir)
        self.overview_builder = TaskRegistryOverviewBuilder(self)
        self._cache: dict[str, Any] = {}

    def _get_cached(self, key: str, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def _invalidate_cache(self, *keys: str) -> None:
        if not keys:
            self._cache.clear()
            return
        for key in keys:
            self._cache.pop(key, None)

    def list_general_task_profiles(self) -> list[GeneralTaskProfile]:
        return self.flow_repository.list_general_profiles()

    def upsert_general_task_profile(
        self,
        *,
        profile_id: str,
        title: str,
        default_agent_id: str,
        default_workflow_id: str,
        input_contract_id: str = "",
        output_contract_id: str = "",
        conversation_entry_policy: str = "user_dialogue_to_main_agent",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> GeneralTaskProfile:
        profile = self.flow_repository.upsert_general_profile(
            profile_id=profile_id,
            title=title,
            default_agent_id=default_agent_id,
            default_workflow_id=default_workflow_id,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            conversation_entry_policy=conversation_entry_policy,
            enabled=enabled,
            metadata=metadata,
        )
        self._invalidate_cache()
        return profile

    def list_flows(self) -> list[TaskFlowDefinition]:
        return self._get_cached("flows", self.flow_repository.list)

    def get_flow(self, flow_id: str) -> TaskFlowDefinition | None:
        return self.flow_repository.get(flow_id)

    def next_flow_id(self) -> str:
        return self.flow_repository.next_id()

    def upsert_flow(
        self,
        *,
        flow_id: str,
        title: str,
        input_contract_id: str,
        output_contract_id: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_memory_scope: str,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowDefinition:
        flow = self.flow_repository.upsert(
            flow_id=flow_id,
            title=title,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            default_agent_id=default_agent_id,
            default_workflow_id=default_workflow_id,
            default_memory_scope=default_memory_scope,
            enabled=enabled,
            metadata=metadata,
        )
        self._invalidate_cache()
        return flow

    def list_task_assignments(self) -> list[TaskAssignment]:
        return self._get_cached("task_assignments", self.assignment_repository.list)

    def get_general_task_profile(self, profile_id: str) -> GeneralTaskProfile | None:
        return self.flow_repository.get_general_profile(profile_id)

    def get_task_assignment(self, task_id: str) -> TaskAssignment | None:
        return self.assignment_repository.get(task_id)

    def next_specific_task_id(self) -> str:
        ids = [item.task_id for item in self.list_task_assignments()]
        ids.extend(item.task_id for item in self.list_specific_task_records())
        return _next_prefixed_id(ids, prefix="task.")

    def list_task_domains(self) -> list[TaskDomainRecord]:
        return self.domain_repository.list()

    def get_task_domain(self, domain_id: str) -> TaskDomainRecord | None:
        return self.domain_repository.get(domain_id)

    def upsert_task_domain(
        self,
        *,
        domain_id: str,
        title: str,
        description: str = "",
        enabled: bool = True,
        sort_order: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TaskDomainRecord:
        record = self.domain_repository.upsert(
            domain_id=domain_id,
            title=title,
            description=description,
            enabled=enabled,
            sort_order=sort_order,
            metadata=metadata,
        )
        self._invalidate_cache()
        return record

    def delete_task_domain(self, domain_id: str) -> dict[str, Any]:
        target = str(domain_id or "").strip()
        domain = self.get_task_domain(target)
        if domain is None:
            raise ValueError("task domain not found")
        task_ids = {
            item.task_id
            for item in self.list_specific_task_records()
            if str(item.domain_id or item.metadata.get("domain_id") or "").strip() == target
        }
        flow_ids = {
            item.flow_id
            for item in self.list_flows()
            if str(item.metadata.get("domain_id") or "").strip() == target
            or str(item.metadata.get("task_id") or "") in task_ids
        }
        coordination_ids = {
            str(item.graph_id or "")
            for item in self.list_task_graphs()
            if str(item.metadata.get("domain_id") or item.domain_id or "") == target
            or any(ref in task_ids for ref in item.to_dict().get("subtask_refs") or [])
        }
        protocol_ids = {
            item.protocol_id
            for item in self.list_task_communication_protocols()
            if str(item.metadata.get("domain_id") or "") == target
            or str(item.metadata.get("task_id") or "") in task_ids
        }
        workflow_ids = self._collect_deletable_workflow_ids(
            task_ids=task_ids,
            flow_ids=flow_ids,
        )

        self.domain_repository.mark_deleted(target)
        self.specific_task_repository.delete_many(task_ids)
        self.assignment_repository.delete_for_task_ids(task_ids)
        self.flow_repository.delete_many(flow_ids)
        self.assembly_config_repository.delete_for_task_ids(task_ids)
        self.protocol_repository.delete_many(protocol_ids)
        deleted_workflow_ids = self.workflow_registry.delete_workflows(workflow_ids)
        return {
            "domain_id": target,
            "deleted_task_ids": sorted(task_ids),
            "deleted_flow_ids": sorted(flow_ids),
            "deleted_workflow_ids": list(deleted_workflow_ids),
            "deleted_task_graph_ids": sorted(coordination_ids),
            "deleted_protocol_ids": sorted(protocol_ids),
        }

    def list_specific_task_records(self) -> list[SpecificTaskRecord]:
        return self.specific_task_repository.list()

    def get_specific_task_record(self, task_id: str) -> SpecificTaskRecord | None:
        return self.specific_task_repository.get(task_id)

    def upsert_task_assignment(
        self,
        *,
        task_id: str,
        task_title: str,
        task_kind: str,
        flow_id: str,
        domain_id: str = "",
        task_environment_id: str = "",
        default_agent_id: str,
        participant_agent_ids: tuple[str, ...] = (),
        workflow_id: str = "",
        workflow_file_ref: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        safety_policy: dict[str, Any] | None = None,
        task_structure: dict[str, Any] | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskAssignment:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        normalized_flow_id = str(flow_id or f"flow.{target.removeprefix('task.')}").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        normalized_metadata = dict(metadata or {})
        normalized_task_structure = dict(task_structure or {})
        normalized_task_environment_id = str(
            task_environment_id
            or normalized_metadata.get("task_environment_id")
            or normalized_metadata.get("environment_id")
            or normalized_task_structure.get("task_environment_id")
            or normalized_task_structure.get("environment_id")
            or ""
        ).strip()
        record = self.upsert_specific_task_record(
            task_id=target,
            task_title=task_title,
            domain_id=str(domain_id or normalized_metadata.get("domain_id") or "").strip(),
            description=str(normalized_metadata.get("description") or task_title or target).strip(),
            enabled=enabled,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            acceptance_profile_id=str(normalized_metadata.get("acceptance_profile_id") or ""),
            default_flow_contract_id=normalized_flow_id,
            default_workflow_id=workflow_id,
            task_policy={
                "safety_policy": dict(safety_policy or {}),
                "task_structure": {
                    **normalized_task_structure,
                    "trigger_signals": list(normalized_task_structure.get("trigger_signals") or []),
                    "notes": str(normalized_task_structure.get("notes") or ""),
                },
            },
            metadata=normalized_metadata,
        )
        self.upsert_flow(
            flow_id=normalized_flow_id,
            title=record.task_title,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            default_workflow_id=record.default_workflow_id,
            default_memory_scope=str(dict(record.task_policy or {}).get("task_structure", {}).get("memory_scope_hint") or ""),
            enabled=record.enabled,
            metadata={**dict(record.metadata or {}), "task_assignment_id": record.task_id},
        )
        assignment = TaskAssignment(
            task_id=target,
            task_title=record.task_title,
            task_kind=str(task_kind or "specific_task").strip(),
            flow_id=normalized_flow_id,
            domain_id=record.domain_id,
            task_environment_id=normalized_task_environment_id,
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            participant_agent_ids=normalize_agent_id_sequence(str(item).strip() for item in participant_agent_ids if str(item).strip()),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=str(workflow_file_ref or "").strip(),
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=dict(safety_policy or {}),
            task_structure=normalized_task_structure,
            enabled=record.enabled,
            metadata=normalized_metadata,
        )
        self.assignment_repository.upsert(assignment)
        self._invalidate_cache()
        return assignment

    def upsert_specific_task_record(
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
        task_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpecificTaskRecord:
        record = self.specific_task_repository.upsert(
            task_id=task_id,
            task_title=task_title,
            domain_id=domain_id,
            description=description,
            enabled=enabled,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            acceptance_profile_id=acceptance_profile_id,
            default_flow_contract_id=default_flow_contract_id,
            default_workflow_id=default_workflow_id,
            task_policy=task_policy,
            metadata=metadata,
        )
        self._invalidate_cache()
        return record

    def delete_specific_task_record(self, task_id: str) -> dict[str, Any]:
        target = str(task_id or "").strip()
        record = self.get_specific_task_record(target)
        if record is None:
            raise ValueError("specific task not found")
        flow_ids = {
            item.flow_id
            for item in self.list_flows()
            if str(item.metadata.get("task_id") or "") == target
            or item.flow_id == record.default_flow_contract_id
            or item.flow_id == f"flow.{target.removeprefix('task.')}"
        }
        workflow_ids = self._collect_deletable_workflow_ids(
            task_ids={target},
            flow_ids=flow_ids,
        )
        self.specific_task_repository.delete_many({target})
        self._invalidate_cache()
        self.assignment_repository.delete_for_task_ids({target})
        self.flow_repository.delete_many(flow_ids)
        self.assembly_config_repository.delete_for_task_ids({target})
        deleted_workflow_ids = self.workflow_registry.delete_workflows(workflow_ids)
        self._invalidate_cache()
        return {
            "task_id": target,
            "deleted_flow_ids": sorted(flow_ids),
            "deleted_workflow_ids": list(deleted_workflow_ids),
        }

    def _assignment_from_flow(self, flow: TaskFlowDefinition) -> TaskAssignment:
        workflow = self.workflow_registry.get_workflow(flow.default_workflow_id)
        task_id = str(flow.metadata.get("task_id") or flow.metadata.get("task_assignment_id") or f"task.{flow.flow_id.removeprefix('flow.')}").strip()
        spec = _system_task_specs().get(task_id)
        return TaskAssignment(
            task_id=task_id,
            task_title=flow.title,
            task_kind="specific_task",
            flow_id=flow.flow_id,
            domain_id=str(flow.metadata.get("domain_id") or ""),
            default_agent_id=flow.default_agent_id or "agent:0",
            participant_agent_ids=(),
            workflow_id=flow.default_workflow_id,
            workflow_file_ref=f"workflow:{flow.default_workflow_id}" if flow.default_workflow_id else "",
            input_contract_id=flow.input_contract_id,
            output_contract_id=flow.output_contract_id,
            safety_policy=dict(spec.get("safety_policy") or {}) if spec is not None else {},
            task_structure={
                "memory_scope_hint": flow.default_memory_scope,
                "workflow_steps": [dict(item) for item in workflow.steps] if workflow is not None else [],
                "task_resource_kind": str(flow.metadata.get("task_resource") or ""),
            },
            enabled=flow.enabled,
            metadata={**flow.metadata, "source_flow_id": flow.flow_id},
        )

    def _specific_task_record_from_flow(self, flow: TaskFlowDefinition) -> SpecificTaskRecord:
        assignment = self._assignment_from_flow(flow)
        return _specific_task_record_from_assignment(assignment)

    def list_bindings(self) -> list[TaskAgentBinding]:
        return [self.build_binding_for_flow(flow) for flow in self.list_flows()]

    def list_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        return self.assembly_config_repository.list_flow_contract_bindings()

    def list_explicit_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        return self.assembly_config_repository.list_explicit_flow_contract_bindings()

    def get_flow_contract_binding(self, task_id: str) -> TaskFlowContractBinding | None:
        return self.assembly_config_repository.get_flow_contract_binding(task_id)

    def upsert_flow_contract_binding(
        self,
        *,
        task_id: str,
        flow_contract_id: str,
        override_policy: str = "task_default",
        verification_gate_profile: str = "",
        fallback_policy: str = "fail_closed",
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowContractBinding:
        binding = self.assembly_config_repository.upsert_flow_contract_binding(
            task_id=task_id,
            flow_contract_id=flow_contract_id,
            override_policy=override_policy,
            verification_gate_profile=verification_gate_profile,
            fallback_policy=fallback_policy,
            metadata=metadata,
        )
        self._invalidate_cache()
        return binding

    def list_task_execution_policies(self) -> list[TaskExecutionPolicy]:
        return self._get_cached("task_execution_policies", self.assembly_config_repository.list_execution_policies)

    def list_explicit_task_execution_policies(self) -> list[TaskExecutionPolicy]:
        return self.assembly_config_repository.list_explicit_execution_policies()

    def get_task_execution_policy(self, task_id: str) -> TaskExecutionPolicy | None:
        return self.assembly_config_repository.get_execution_policy(task_id)

    def upsert_task_execution_policy(
        self,
        *,
        task_id: str,
        execution_mode: str,
        default_agent_id: str = "agent:0",
        allow_worker_agent_spawn: bool = False,
        worker_agent_blueprint_id: str = "",
        worker_agent_naming_rule: str = "",
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskExecutionPolicy:
        plan = self.assembly_config_repository.upsert_execution_policy(
            task_id=task_id,
            execution_mode=execution_mode,
            default_agent_id=default_agent_id,
            allow_worker_agent_spawn=allow_worker_agent_spawn,
            worker_agent_blueprint_id=worker_agent_blueprint_id,
            worker_agent_naming_rule=worker_agent_naming_rule,
            notes=notes,
            metadata=metadata,
        )
        self._invalidate_cache()
        return plan

    def _collect_deletable_workflow_ids(
        self,
        *,
        task_ids: set[str],
        flow_ids: set[str],
    ) -> set[str]:
        candidates = {
            str(item.default_workflow_id or "").strip()
            for item in self.list_specific_task_records()
            if item.task_id in task_ids
        }
        candidates.update(
            str(item.workflow_id or "").strip()
            for item in self.list_task_assignments()
            if item.task_id in task_ids
        )
        candidates.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_flows()
            if item.flow_id in flow_ids or str(item.metadata.get("task_id") or "") in task_ids
        )
        candidates = {item for item in candidates if item}
        if not candidates:
            return set()

        remaining_task_ids = {
            item.task_id
            for item in self.list_specific_task_records()
            if item.task_id not in task_ids
        }
        referenced_after_delete: set[str] = set()
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_general_task_profiles()
            if str(item.default_workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_specific_task_records()
            if item.task_id in remaining_task_ids and str(item.default_workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.workflow_id or "").strip()
            for item in self.list_task_assignments()
            if item.task_id in remaining_task_ids and str(item.workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_flows()
            if item.flow_id not in flow_ids
            and str(item.metadata.get("task_id") or "") not in task_ids
            and str(item.default_workflow_id or "").strip()
        )
        return {
            item
            for item in candidates
            if item not in referenced_after_delete
        }

    def list_task_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        return self.assembly_config_repository.list_memory_request_profiles()

    def list_explicit_task_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        return self.assembly_config_repository.list_explicit_memory_request_profiles()

    def get_task_memory_request_profile(self, task_id: str) -> TaskMemoryRequestProfile | None:
        return self.assembly_config_repository.get_memory_request_profile(task_id)

    def upsert_task_memory_request_profile(
        self,
        *,
        task_id: str,
        requested_memory_layers: tuple[str, ...] = (),
        requested_topics: tuple[str, ...] = (),
        memory_priority: str = "normal",
        writeback_policy: str = "task_default",
        allow_long_term_memory: bool = False,
        memory_scope_hint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskMemoryRequestProfile:
        profile = self.assembly_config_repository.upsert_memory_request_profile(
            task_id=task_id,
            requested_memory_layers=requested_memory_layers,
            requested_topics=requested_topics,
            memory_priority=memory_priority,
            writeback_policy=writeback_policy,
            allow_long_term_memory=allow_long_term_memory,
            memory_scope_hint=memory_scope_hint,
            metadata=metadata,
        )
        self._invalidate_cache()
        return profile

    def list_task_graphs(self) -> list[TaskGraphDefinition]:
        return self.task_graph_repository.list()

    def get_task_graph(self, graph_id: str) -> TaskGraphDefinition | None:
        return self.task_graph_repository.get(graph_id)

    def next_task_graph_id(self) -> str:
        return self.task_graph_repository.next_id()

    def upsert_task_graph(
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
        graph = self.task_graph_repository.upsert(
            graph_id=graph_id,
            title=title,
            domain_id=domain_id,
            graph_kind=graph_kind,
            entry_node_id=entry_node_id,
            output_node_id=output_node_id,
            nodes=nodes,
            edges=edges,
            graph_contract_id=graph_contract_id,
            contract_bindings=contract_bindings,
            default_protocol_id=default_protocol_id,
            working_memory_policy_profile_id=working_memory_policy_profile_id,
            working_memory_policy=working_memory_policy,
            runtime_policy=runtime_policy,
            context_policy=context_policy,
            loop_frames=loop_frames,
            publish_state=publish_state,
            enabled=enabled,
            metadata=metadata,
        )
        self._invalidate_cache()
        return graph

    def list_graph_configs(self) -> list[Any]:
        return self.executable_graph_config_repository.list()

    def get_graph_config(self, config_id: str) -> Any | None:
        return self.executable_graph_config_repository.get(config_id)

    def get_published_graph_config(self, graph_id: str) -> Any | None:
        return self.executable_graph_config_repository.get_published_for_graph(graph_id)

    def upsert_graph_config(self, config: Any, *, publish: bool = True) -> Any:
        stored = self.executable_graph_config_repository.upsert(config, publish=publish)
        self._invalidate_cache()
        return stored

    def list_task_communication_protocols(self) -> list[TaskCommunicationProtocol]:
        return self.protocol_repository.list()

    def list_contract_descriptors(self) -> list[TaskContractDescriptor]:
        collected: dict[tuple[str, str], dict[str, Any]] = {}

        def append_contract(
            contract_id: str,
            kind: str,
            *,
            source_ref: str = "",
            usage_ref: str = "",
            title: str = "",
            summary: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> None:
            normalized_id = str(contract_id or "").strip()
            if not normalized_id:
                return
            normalized_kind = str(kind or "").strip() or "unknown"
            key = (normalized_id, normalized_kind)
            current = collected.setdefault(
                key,
                {
                    "contract_id": normalized_id,
                    "title": str(title or CONTRACT_TITLE_MAP.get(normalized_id) or normalized_id).strip(),
                    "contract_kind": normalized_kind,
                    "summary": str(summary or CONTRACT_KIND_LABELS.get(normalized_kind) or "").strip(),
                    "source_refs": [],
                    "usage_refs": [],
                    "metadata": {},
                },
            )
            if source_ref:
                current["source_refs"].append(source_ref)
            if usage_ref:
                current["usage_refs"].append(usage_ref)
            current["metadata"] = {**dict(current.get("metadata") or {}), **dict(metadata or {})}

        for profile in self.list_general_task_profiles():
            append_contract(profile.input_contract_id, "input", source_ref=profile.profile_id, usage_ref=profile.title)
            append_contract(profile.output_contract_id, "output", source_ref=profile.profile_id, usage_ref=profile.title)

        for flow in self.list_flows():
            append_contract(flow.input_contract_id, "input", source_ref=flow.flow_id, usage_ref=flow.title)
            append_contract(flow.output_contract_id, "output", source_ref=flow.flow_id, usage_ref=flow.title)
            append_contract(
                flow.flow_id,
                "flow",
                source_ref=flow.flow_id,
                usage_ref=flow.title,
                title=flow.title,
                summary=f"{CONTRACT_TITLE_MAP.get(flow.input_contract_id, flow.input_contract_id)} -> {CONTRACT_TITLE_MAP.get(flow.output_contract_id, flow.output_contract_id)}",
                metadata={
                    "default_workflow_id": flow.default_workflow_id,
                },
            )

        for record in self.list_specific_task_records():
            append_contract(record.input_contract_id, "input", source_ref=record.task_id, usage_ref=record.task_title)
            append_contract(record.output_contract_id, "output", source_ref=record.task_id, usage_ref=record.task_title)
            append_contract(record.default_flow_contract_id, "flow", source_ref=record.task_id, usage_ref=record.task_title)

        for protocol in self.list_task_communication_protocols():
            for contract_id in protocol.payload_contracts:
                append_contract(contract_id, "payload", source_ref=protocol.protocol_id, usage_ref=protocol.title)

        descriptors = []
        for item in collected.values():
            descriptors.append(
                TaskContractDescriptor(
                    contract_id=str(item["contract_id"]),
                    title=str(item["title"]),
                    contract_kind=str(item["contract_kind"]),
                    summary=str(item.get("summary") or ""),
                    source_refs=tuple(dict.fromkeys(str(ref) for ref in list(item.get("source_refs") or []) if str(ref))),
                    usage_refs=tuple(dict.fromkeys(str(ref) for ref in list(item.get("usage_refs") or []) if str(ref))),
                    editable=False,
                    status="derived",
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return sorted(descriptors, key=lambda item: (item.contract_kind, item.title, item.contract_id))

    def get_task_communication_protocol(self, protocol_id: str) -> TaskCommunicationProtocol | None:
        return self.protocol_repository.get(protocol_id)

    def upsert_task_communication_protocol(
        self,
        *,
        protocol_id: str,
        title: str,
        message_types: tuple[str, ...] = (),
        payload_contracts: tuple[str, ...] = (),
        signal_rules: tuple[str, ...] = (),
        handoff_rules: tuple[str, ...] = (),
        ack_policy: str = "explicit_ack",
        timeout_policy: str = "fail_closed",
        error_signal_policy: str = "raise_to_coordinator",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TaskCommunicationProtocol:
        return self.protocol_repository.upsert(
            protocol_id=protocol_id,
            title=title,
            message_types=message_types,
            payload_contracts=payload_contracts,
            signal_rules=signal_rules,
            handoff_rules=handoff_rules,
            ack_policy=ack_policy,
            timeout_policy=timeout_policy,
            error_signal_policy=error_signal_policy,
            enabled=enabled,
            metadata=metadata,
        )

    def upsert_graph_task(
        self,
        *,
        graph_id: str,
        title: str,
        coordination_mode: str,
        coordinator_agent_id: str,
        domain_id: str = "",
        agent_group_id: str = "",
        participant_agent_ids: tuple[str, ...] = (),
        shared_context_policy: str = "explicit_refs_only",
        memory_sharing_policy: str = "isolated_by_default",
        handoff_policy: str = "filtered_handoff",
        conflict_resolution_policy: str = "coordinator_review",
        output_merge_policy: str = "coordinator_final_merge",
        stop_conditions: tuple[str, ...] = (),
        subtask_refs: tuple[str, ...] = (),
        graph_nodes: tuple[dict[str, Any], ...] = (),
        graph_edges: tuple[dict[str, Any], ...] = (),
        communication_modes: tuple[str, ...] = (),
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TaskGraphDefinition:
        return self.graph_service.upsert_graph_task(
            graph_id=graph_id,
            title=title,
            coordination_mode=coordination_mode,
            coordinator_agent_id=coordinator_agent_id,
            domain_id=domain_id,
            agent_group_id=agent_group_id,
            participant_agent_ids=participant_agent_ids,
            shared_context_policy=shared_context_policy,
            memory_sharing_policy=memory_sharing_policy,
            handoff_policy=handoff_policy,
            conflict_resolution_policy=conflict_resolution_policy,
            output_merge_policy=output_merge_policy,
            stop_conditions=stop_conditions,
            subtask_refs=subtask_refs,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            communication_modes=communication_modes,
            enabled=enabled,
            metadata=metadata,
        )

    def _resolve_coordination_participants(
        self,
        *,
        coordinator_agent_id: str,
        agent_group_id: str,
        participant_agent_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        return self.graph_service.resolve_coordination_participants(
            coordinator_agent_id=coordinator_agent_id,
            agent_group_id=agent_group_id,
            participant_agent_ids=participant_agent_ids,
        )

    def build_binding_for_flow(self, flow: TaskFlowDefinition) -> TaskAgentBinding:
        return self.overview_builder.build_binding_for_flow(flow)

    def build_link_permission_matrix(self) -> dict[str, Any]:
        return self.overview_builder.build_link_permission_matrix()

    def list_agent_task_connection_profiles(
        self,
        *,
        owner_system: str = "",
    ) -> list[AgentTaskConnectionProfile]:
        return self.overview_builder.list_agent_task_connection_profiles(owner_system=owner_system)

    def build_agent_task_connection_overview(
        self,
        *,
        owner_system: str = "",
    ) -> dict[str, Any]:
        return self.overview_builder.build_agent_task_connection_overview(owner_system=owner_system)

    def list_agent_task_carrying_profiles(self) -> list[AgentTaskCarryingProfile]:
        return self.overview_builder.list_agent_task_carrying_profiles()

    def build_agent_carrying_overview(self) -> dict[str, Any]:
        return self.overview_builder.build_agent_carrying_overview()

    def build_connection_diagnostics(self) -> dict[str, Any]:
        return self.overview_builder.build_connection_diagnostics()

    def build_overview(self) -> dict[str, Any]:
        return self.overview_builder.build_overview()



