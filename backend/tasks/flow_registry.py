from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import AgentRegistry
from orchestration import AgentRuntimeRegistry

from .flow_models import (
    AgentTaskCarryingProfile,
    AgentTaskConnectionProfile,
    CoordinationTaskDefinition,
    GeneralTaskProfile,
    SpecificTaskRecord,
    TaskAgentAdoptionPlan,
    TaskAgentBinding,
    TaskAssignment,
    TaskCommunicationProtocol,
    TaskFlowDefinition,
    TaskFlowContractBinding,
    TaskMemoryRequestProfile,
    TaskProjectionBinding,
    TopologyTemplate,
)
from .template_registry import TaskTemplateRegistry
from .workflow_registry import TaskWorkflowRegistry


def default_task_flows() -> tuple[TaskFlowDefinition, ...]:
    return (
        TaskFlowDefinition(
            flow_id="flow.dev.bounded_patch",
            task_mode="bounded_patch",
            task_family="development",
            title="受限补丁开发任务",
            input_contract_id="WorkspacePatchTaskInput",
            output_contract_id="AssistantFinalAnswer",
            default_agent_id="agent:0",
            default_workflow_id="workflow.dev.bounded_patch",
            default_runtime_lane="workspace_patch",
            default_memory_scope="conversation_read_write",
            metadata={
                "task_resource": "bounded_patch",
                "template_id": "template.dev.workspace_patch",
                "task_id": "task.dev.bounded_patch",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.dev.light_web_game",
            task_mode="light_web_game",
            task_family="development",
            title="轻量网页小游戏开发",
            input_contract_id="LightWebGameTaskInput",
            output_contract_id="LightWebGameResult",
            default_agent_id="agent:0",
            default_workflow_id="workflow.dev.light_web_game",
            default_runtime_lane="game_delivery",
            default_memory_scope="conversation_read_write",
            metadata={
                "task_resource": "light_web_game",
                "template_id": "template.dev.light_web_game",
                "task_id": "task.dev.light_web_game",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.dev.arcade_game_bundle",
            task_mode="arcade_game_bundle",
            task_family="development",
            title="复合网页小游戏包开发",
            input_contract_id="ArcadeGameBundleTaskInput",
            output_contract_id="LightWebGameResult",
            default_agent_id="agent:0",
            default_workflow_id="workflow.dev.arcade_game_bundle",
            default_runtime_lane="game_delivery",
            default_memory_scope="conversation_read_write",
            metadata={
                "task_resource": "arcade_game_bundle",
                "template_id": "template.dev.arcade_game_bundle",
                "task_id": "task.dev.arcade_game_bundle",
            },
        ),
        TaskFlowDefinition(
            flow_id="flow.health.issue_triage",
            task_mode="issue_triage",
            task_family="health",
            title="健康问题分诊",
            input_contract_id="HealthIssue",
            output_contract_id="HealthTriageResult",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.issue_triage",
            default_runtime_lane="health_issue_read",
            default_memory_scope="issue_local_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.trace_analysis",
            task_mode="trace_analysis",
            task_family="health",
            title="健康链路分析",
            input_contract_id="HealthTrace",
            output_contract_id="HealthTraceAnalysis",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.trace_analysis",
            default_runtime_lane="health_trace_read",
            default_memory_scope="health_trace_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.case_draft",
            task_mode="case_draft",
            task_family="health",
            title="复现用例草案",
            input_contract_id="HealthIssue",
            output_contract_id="HealthCaseDraftProposal",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.case_draft",
            default_runtime_lane="case_draft_candidate",
            default_memory_scope="issue_local_readonly",
        ),
        TaskFlowDefinition(
            flow_id="flow.health.fix_verification",
            task_mode="fix_verification",
            task_family="health",
            title="修复验证",
            input_contract_id="HealthIssueWithBeforeAfterTrace",
            output_contract_id="HealthFixVerificationProposal",
            default_agent_id="agent:3",
            default_workflow_id="workflow.health.fix_verification",
            default_runtime_lane="fix_verification_candidate",
            default_memory_scope="health_trace_readonly",
        ),
    )


def _storage_root(base_dir: Path) -> Path:
    return Path(base_dir) / "storage" / "tasks"


def _flows_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_flows.json"


def _general_profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "general_task_profiles.json"


def _assignments_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_assignments.json"


def _specific_task_records_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "specific_task_records.json"


def _coordination_tasks_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "coordination_tasks.json"


def _topology_templates_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "topology_templates.json"


def _projection_bindings_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_projection_bindings.json"


def _flow_contract_bindings_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_flow_contract_bindings.json"


def _adoption_plans_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_agent_adoption_plans.json"


def _memory_request_profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_memory_request_profiles.json"


def _communication_protocols_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_communication_protocols.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        import json

        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_general_task_profiles() -> tuple[GeneralTaskProfile, ...]:
    return (
        GeneralTaskProfile(
            profile_id="general.conversation.default",
            title="通用对话任务",
            entry_channel="main_conversation",
            default_agent_id="agent:0",
            default_workflow_id="workflow.general.main_conversation",
            default_projection_id="",
            input_contract_id="UserMessage",
            output_contract_id="AssistantFinalAnswer",
            conversation_entry_policy="user_dialogue_to_main_agent",
            enabled=True,
            metadata={
                "managed_by": "task_system",
                "default_specific_task_handoff": "task.dev.light_web_game",
                "notes": "主会话默认保持通用承接，但允许稳定分流到已登记的开发类特定任务。",
            },
        ),
    )


def default_coordination_tasks() -> tuple[CoordinationTaskDefinition, ...]:
    return (
        CoordinationTaskDefinition(
            coordination_task_id="coord.health.repair_review",
            title="健康修复协作草案",
            coordination_mode="review_merge",
            coordinator_agent_id="agent:0",
            participant_agent_ids=("agent:3",),
            topology_template_id="topology.health.repair_review",
            stop_conditions=("all_participants_reported", "coordinator_final_merge"),
            enabled=False,
            metadata={"candidate_only": True},
        ),
    )


def default_task_communication_protocols() -> tuple[TaskCommunicationProtocol, ...]:
    return (
        TaskCommunicationProtocol(
            protocol_id="protocol.health.repair_review",
            title="健康修复协作协议草案",
            message_types=("issue_summary", "trace_findings", "verification_result", "final_merge_request"),
            payload_contracts=("HealthIssue", "HealthTraceAnalysis", "HealthFixVerificationProposal"),
            signal_rules=("participant_report_to_coordinator", "coordinator_final_merge"),
            handoff_rules=("issue_refs_only", "structured_result_only"),
            ack_policy="explicit_ack",
            timeout_policy="fail_closed",
            error_signal_policy="raise_to_coordinator",
            enabled=False,
            metadata={"candidate_only": True},
        ),
    )


def default_topology_templates() -> tuple[TopologyTemplate, ...]:
    return (
        TopologyTemplate(
            template_id="topology.health.repair_review",
            title="健康修复拓扑草案",
            nodes=(
                {"node_id": "health_triage", "agent_id": "agent:3", "lane": "health_issue_read"},
                {"node_id": "fix_verification", "agent_id": "agent:3", "lane": "fix_verification_candidate"},
                {"node_id": "final_merge", "agent_id": "agent:0", "lane": "final_integration"},
            ),
            edges=(
                {"from": "health_triage", "to": "fix_verification", "policy": "issue_refs_only"},
                {"from": "fix_verification", "to": "final_merge", "policy": "structured_result_only"},
            ),
            enabled=False,
        ),
    )


def _default_projection_binding(task: TaskAssignment) -> TaskProjectionBinding:
    selected_projection_ids = tuple(
        item
        for item in [str(task.projection_id or "").strip()]
        if item
    )
    default_projection_id = selected_projection_ids[0] if selected_projection_ids else ""
    return TaskProjectionBinding(
        binding_id=f"taskprojbind:{task.task_id}",
        task_id=task.task_id,
        projection_selection_mode="task_default" if default_projection_id else "workflow_compatible_or_task_default",
        allowed_projection_ids=selected_projection_ids,
        default_projection_id=default_projection_id,
        projection_required=bool(default_projection_id),
        notes="Derived from task assignment defaults.",
        metadata={"derived_from": "task_assignment"},
    )


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


def _default_adoption_plan(task: TaskAssignment) -> TaskAgentAdoptionPlan:
    participant_ids = tuple(str(item).strip() for item in task.participant_agent_ids if str(item).strip())
    return TaskAgentAdoptionPlan(
        plan_id=f"taskadopt:{task.task_id}",
        task_id=task.task_id,
        adoption_mode="adopt_existing" if not participant_ids else "adopt_with_projection",
        default_agent_id=str(task.default_agent_id or "agent:0").strip() or "agent:0",
        allowed_agent_categories=("main_agent", "system_management_agent", "worker_sub_agent"),
        allow_worker_agent_spawn=False,
        worker_agent_blueprint_id="",
        worker_agent_naming_rule="",
        notes="Derived from task assignment defaults.",
        metadata={"derived_from": "task_assignment", "participant_agent_ids": list(participant_ids)},
    )


def _default_memory_request_profile(task: TaskAssignment) -> TaskMemoryRequestProfile:
    task_family = str(task.task_family or "").strip()
    task_mode = str(task.task_mode or "").strip()
    memory_scope_hint = str(dict(task.task_structure or {}).get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [task_family or task_mode or "general_task"]
    allow_long_term_memory = False
    if task_family == "health":
        requested_layers = ["state", "conversation"]
        requested_topics = ["health_issue", task_mode or "health"]
    elif task_family == "development":
        requested_layers = ["conversation", "state", "long_term"]
        requested_topics = ["project_background", "recent_workspace_state", task_mode or "development"]
        allow_long_term_memory = True
    elif task_mode == "general_task":
        requested_layers = ["conversation"]
        requested_topics = ["current_conversation"]
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{task.task_id}",
        task_id=task.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="high" if task_family in {"health", "development"} else "normal",
        writeback_policy="task_default",
        allow_long_term_memory=allow_long_term_memory,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "task_assignment"},
    )


def _specific_task_record_from_assignment(task: TaskAssignment) -> SpecificTaskRecord:
    projection_policy = "fixed_projection" if str(task.projection_id or "").strip() else "workflow_compatible_or_task_default"
    return SpecificTaskRecord(
        task_id=task.task_id,
        task_title=task.task_title,
        task_family=task.task_family,
        task_mode=task.task_mode,
        description=str(dict(task.metadata or {}).get("description") or task.task_title),
        enabled=task.enabled,
        input_contract_id=task.input_contract_id,
        output_contract_id=task.output_contract_id,
        acceptance_profile_id=str(dict(task.metadata or {}).get("acceptance_profile_id") or ""),
        default_flow_contract_id=str(task.flow_id or ""),
        default_workflow_id=str(task.workflow_id or ""),
        default_projection_policy=projection_policy,
        task_policy={
            "safety_policy": dict(task.safety_policy or {}),
            "task_structure": dict(task.task_structure or {}),
        },
        metadata=dict(task.metadata or {}),
    )


def _default_projection_binding_from_specific_record(record: SpecificTaskRecord) -> TaskProjectionBinding:
    projection_policy = str(record.default_projection_policy or "").strip()
    projection_required = projection_policy == "fixed_projection"
    return TaskProjectionBinding(
        binding_id=f"taskprojbind:{record.task_id}",
        task_id=record.task_id,
        projection_selection_mode=projection_policy or "workflow_compatible_or_task_default",
        allowed_projection_ids=(),
        default_projection_id="",
        projection_required=projection_required,
        notes="Derived from specific task record defaults.",
        metadata={"derived_from": "specific_task_record"},
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
    task_family = str(record.task_family or "").strip()
    task_mode = str(record.task_mode or "").strip()
    task_policy = dict(record.task_policy or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    memory_scope_hint = str(task_structure.get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [task_family or task_mode or "specific_task"]
    allow_long_term_memory = False
    if task_family == "health":
        requested_layers = ["state", "conversation"]
        requested_topics = ["health_issue", task_mode or "health"]
    elif task_family == "development":
        requested_layers = ["conversation", "state", "long_term"]
        requested_topics = ["project_background", "recent_workspace_state", task_mode or "development"]
        allow_long_term_memory = True
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{record.task_id}",
        task_id=record.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="high" if task_family in {"health", "development"} else "normal",
        writeback_policy="task_default",
        allow_long_term_memory=allow_long_term_memory,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "specific_task_record"},
    )


def _synthetic_task_from_general_profile(profile: GeneralTaskProfile) -> TaskAssignment:
    return TaskAssignment(
        task_id=profile.profile_id,
        task_title=profile.title,
        task_kind="general_task",
        task_family="general",
        task_mode="general_task",
        flow_id="flow.general.main_conversation",
        default_agent_id=str(profile.default_agent_id or "agent:0").strip() or "agent:0",
        participant_agent_ids=(),
        workflow_id=str(profile.default_workflow_id or ""),
        workflow_file_ref=f"workflow:{profile.default_workflow_id}" if profile.default_workflow_id else "",
        projection_id=str(profile.default_projection_id or ""),
        input_contract_id=str(profile.input_contract_id or ""),
        output_contract_id=str(profile.output_contract_id or ""),
        safety_policy={},
        task_structure={
            "entry_channel": str(profile.entry_channel or "main_conversation"),
            "memory_scope_hint": "conversation_read_write",
        },
        enabled=profile.enabled,
        metadata=dict(profile.metadata or {}),
    )


class TaskFlowRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.agent_runtime_registry = AgentRuntimeRegistry(self.base_dir)
        self.template_registry = TaskTemplateRegistry(self.base_dir)
        self.workflow_registry = TaskWorkflowRegistry(self.base_dir)

    def list_general_task_profiles(self) -> list[GeneralTaskProfile]:
        payload = _read_json(
            _general_profiles_path(self.base_dir),
            {"profiles": [item.to_dict() for item in default_general_task_profiles()]},
        )
        profiles: list[GeneralTaskProfile] = []
        for item in list(payload.get("profiles") or []):
            if not isinstance(item, dict):
                continue
            profiles.append(
                GeneralTaskProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    title=str(item.get("title") or ""),
                    entry_channel=str(item.get("entry_channel") or "main_conversation"),
                    default_agent_id=str(item.get("default_agent_id") or "agent:0"),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_id=str(item.get("default_projection_id") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    conversation_entry_policy=str(item.get("conversation_entry_policy") or "user_dialogue_to_main_agent"),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return profiles

    def upsert_general_task_profile(
        self,
        *,
        profile_id: str,
        title: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_projection_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        conversation_entry_policy: str = "user_dialogue_to_main_agent",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> GeneralTaskProfile:
        target = str(profile_id or "").strip()
        if not target.startswith("general."):
            raise ValueError("profile_id must start with general.")
        profile = GeneralTaskProfile(
            profile_id=target,
            title=str(title or target).strip(),
            entry_channel="main_conversation",
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_id=str(default_projection_id or "").strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            conversation_entry_policy=str(conversation_entry_policy or "user_dialogue_to_main_agent").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_general_task_profiles() if item.profile_id != target]
        profiles.append(profile)
        _write_json(_general_profiles_path(self.base_dir), {"profiles": [item.to_dict() for item in profiles]})
        return profile

    def list_flows(self) -> list[TaskFlowDefinition]:
        payload = _read_json(
            _flows_path(self.base_dir),
            {"flows": [item.to_dict() for item in default_task_flows()]},
        )
        flows = []
        for item in list(payload.get("flows") or []):
            if not isinstance(item, dict):
                continue
            flows.append(
                TaskFlowDefinition(
                    flow_id=str(item.get("flow_id") or ""),
                    task_mode=str(item.get("task_mode") or ""),
                    task_family=str(item.get("task_family") or ""),
                    title=str(item.get("title") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    default_agent_id=str(item.get("default_agent_id") or ""),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_runtime_lane=str(item.get("default_runtime_lane") or ""),
                    default_memory_scope=str(item.get("default_memory_scope") or ""),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return flows

    def get_flow(self, flow_id: str) -> TaskFlowDefinition | None:
        target = str(flow_id or "").strip()
        return next((item for item in self.list_flows() if item.flow_id == target), None)

    def upsert_flow(
        self,
        *,
        flow_id: str,
        task_mode: str,
        task_family: str,
        title: str,
        input_contract_id: str,
        output_contract_id: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_runtime_lane: str,
        default_memory_scope: str,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowDefinition:
        normalized_flow_id = str(flow_id or "").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        flow = TaskFlowDefinition(
            flow_id=normalized_flow_id,
            task_mode=str(task_mode or "").strip(),
            task_family=str(task_family or "").strip(),
            title=str(title or normalized_flow_id).strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            default_agent_id=str(default_agent_id or "").strip(),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_runtime_lane=str(default_runtime_lane or "").strip(),
            default_memory_scope=str(default_memory_scope or "").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        flows = [item for item in self.list_flows() if item.flow_id != normalized_flow_id]
        flows.append(flow)
        _write_json(_flows_path(self.base_dir), {"flows": [item.to_dict() for item in flows]})
        return flow

    def list_task_assignments(self) -> list[TaskAssignment]:
        default_assignments = [self._assignment_from_specific_task_record(item).to_dict() for item in self.list_specific_task_records()]
        payload = _read_json(
            _assignments_path(self.base_dir),
            {"assignments": default_assignments},
        )
        assignments: list[TaskAssignment] = []
        for item in list(payload.get("assignments") or []):
            if not isinstance(item, dict):
                continue
            assignments.append(_assignment_from_dict(item))
        if not assignments:
            assignments = [self._assignment_from_specific_task_record(item) for item in self.list_specific_task_records()]
            _write_json(_assignments_path(self.base_dir), {"assignments": [item.to_dict() for item in assignments]})
        return assignments

    def get_general_task_profile(self, profile_id: str) -> GeneralTaskProfile | None:
        target = str(profile_id or "").strip()
        return next((item for item in self.list_general_task_profiles() if item.profile_id == target), None)

    def get_task_assignment(self, task_id: str) -> TaskAssignment | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_assignments() if item.task_id == target), None)

    def list_specific_task_records(self) -> list[SpecificTaskRecord]:
        default_records = [self._specific_task_record_from_flow(flow).to_dict() for flow in self.list_flows()]
        payload = _read_json(
            _specific_task_records_path(self.base_dir),
            {"specific_task_records": default_records},
        )
        records: list[SpecificTaskRecord] = []
        for item in list(payload.get("specific_task_records") or []):
            if not isinstance(item, dict):
                continue
            records.append(
                SpecificTaskRecord(
                    task_id=str(item.get("task_id") or ""),
                    task_title=str(item.get("task_title") or ""),
                    task_family=str(item.get("task_family") or ""),
                    task_mode=str(item.get("task_mode") or ""),
                    description=str(item.get("description") or ""),
                    enabled=bool(item.get("enabled", True)),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    acceptance_profile_id=str(item.get("acceptance_profile_id") or ""),
                    default_flow_contract_id=str(item.get("default_flow_contract_id") or ""),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_policy=str(item.get("default_projection_policy") or ""),
                    task_policy=dict(item.get("task_policy") or {}),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        if not records:
            legacy_payload = _read_json(_assignments_path(self.base_dir), {"assignments": []})
            for item in list(legacy_payload.get("assignments") or []):
                if not isinstance(item, dict):
                    continue
                records.append(_specific_task_record_from_assignment(_assignment_from_dict(item)))
        if not records:
            records = [self._specific_task_record_from_flow(flow) for flow in self.list_flows()]
        if records:
            _write_json(
                _specific_task_records_path(self.base_dir),
                {"specific_task_records": [item.to_dict() for item in records]},
            )
        return records

    def get_specific_task_record(self, task_id: str) -> SpecificTaskRecord | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_specific_task_records() if item.task_id == target), None)

    def upsert_task_assignment(
        self,
        *,
        task_id: str,
        task_title: str,
        task_kind: str,
        task_family: str,
        task_mode: str,
        flow_id: str,
        default_agent_id: str,
        participant_agent_ids: tuple[str, ...] = (),
        workflow_id: str = "",
        workflow_file_ref: str = "",
        projection_id: str = "",
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
        record = self.upsert_specific_task_record(
            task_id=target,
            task_title=task_title,
            task_family=task_family,
            task_mode=task_mode,
            description=str(normalized_metadata.get("description") or task_title or target).strip(),
            enabled=enabled,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            acceptance_profile_id=str(normalized_metadata.get("acceptance_profile_id") or ""),
            default_flow_contract_id=normalized_flow_id,
            default_workflow_id=workflow_id,
            default_projection_policy="fixed_projection" if str(projection_id or "").strip() else "workflow_compatible_or_task_default",
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
            task_mode=record.task_mode,
            task_family=record.task_family,
            title=record.task_title,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            default_workflow_id=record.default_workflow_id,
            default_runtime_lane=str(dict(record.task_policy or {}).get("task_structure", {}).get("runtime_lane_hint") or ""),
            default_memory_scope=str(dict(record.task_policy or {}).get("task_structure", {}).get("memory_scope_hint") or ""),
            enabled=record.enabled,
            metadata={**dict(record.metadata or {}), "task_assignment_id": record.task_id},
        )
        assignment = TaskAssignment(
            task_id=target,
            task_title=record.task_title,
            task_kind=str(task_kind or "specific_task").strip(),
            task_family=record.task_family,
            task_mode=record.task_mode,
            flow_id=normalized_flow_id,
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            participant_agent_ids=tuple(str(item).strip() for item in participant_agent_ids if str(item).strip()),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=str(workflow_file_ref or "").strip(),
            projection_id=str(projection_id or "").strip(),
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=dict(safety_policy or {}),
            task_structure=normalized_task_structure,
            enabled=record.enabled,
            metadata=normalized_metadata,
        )
        assignments = [item for item in self.list_task_assignments() if item.task_id != target]
        assignments.append(assignment)
        _write_json(_assignments_path(self.base_dir), {"assignments": [item.to_dict() for item in assignments]})
        return assignment

    def upsert_specific_task_record(
        self,
        *,
        task_id: str,
        task_title: str,
        task_family: str,
        task_mode: str,
        description: str = "",
        enabled: bool = True,
        input_contract_id: str = "",
        output_contract_id: str = "",
        acceptance_profile_id: str = "",
        default_flow_contract_id: str = "",
        default_workflow_id: str = "",
        default_projection_policy: str = "",
        task_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpecificTaskRecord:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        record = SpecificTaskRecord(
            task_id=target,
            task_title=str(task_title or target).strip(),
            task_family=str(task_family or "").strip(),
            task_mode=str(task_mode or "").strip(),
            description=str(description or task_title or target).strip(),
            enabled=bool(enabled),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            acceptance_profile_id=str(acceptance_profile_id or "").strip(),
            default_flow_contract_id=str(default_flow_contract_id or "").strip(),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_policy=str(default_projection_policy or "").strip(),
            task_policy=dict(task_policy or {}),
            metadata=dict(metadata or {}),
        )
        records = [item for item in self.list_specific_task_records() if item.task_id != target]
        records.append(record)
        _write_json(
            _specific_task_records_path(self.base_dir),
            {"specific_task_records": [item.to_dict() for item in records]},
        )
        return record

    def _assignment_from_flow(self, flow: TaskFlowDefinition) -> TaskAssignment:
        workflow = self.workflow_registry.get_workflow(flow.default_workflow_id)
        template = self.template_registry.get_template(str(flow.metadata.get("template_id") or ""))
        task_id = str(flow.metadata.get("task_id") or f"task.{flow.task_family}.{flow.task_mode}").strip()
        return TaskAssignment(
            task_id=task_id,
            task_title=flow.title,
            task_kind="specific_task",
            task_family=flow.task_family,
            task_mode=flow.task_mode,
            flow_id=flow.flow_id,
            default_agent_id=flow.default_agent_id or "agent:0",
            participant_agent_ids=(),
            workflow_id=flow.default_workflow_id,
            workflow_file_ref=f"workflow:{flow.default_workflow_id}" if flow.default_workflow_id else "",
            projection_id="",
            input_contract_id=flow.input_contract_id,
            output_contract_id=flow.output_contract_id,
            safety_policy=dict(getattr(template, "safety_policy", {}) or {}),
            task_structure={
                "runtime_lane_hint": flow.default_runtime_lane,
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

    def _assignment_from_specific_task_record(self, record: SpecificTaskRecord) -> TaskAssignment:
        flow_id = str(record.default_flow_contract_id or f"flow.{record.task_id.removeprefix('task.')}").strip()
        task_policy = dict(record.task_policy or {})
        task_structure = dict(task_policy.get("task_structure") or {})
        safety_policy = dict(task_policy.get("safety_policy") or {})
        flow = self.get_flow(flow_id)
        default_agent_id = str(getattr(flow, "default_agent_id", "") or "agent:0").strip() or "agent:0"
        projection_id = ""
        projection_binding = self.get_projection_binding(record.task_id)
        if projection_binding is not None:
            projection_id = str(projection_binding.default_projection_id or "").strip()
        workflow_file_ref = f"workflow:{record.default_workflow_id}" if record.default_workflow_id else ""
        return TaskAssignment(
            task_id=record.task_id,
            task_title=record.task_title,
            task_kind="specific_task",
            task_family=record.task_family,
            task_mode=record.task_mode,
            flow_id=flow_id,
            default_agent_id=default_agent_id,
            participant_agent_ids=(),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=workflow_file_ref,
            projection_id=projection_id,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=safety_policy,
            task_structure=task_structure,
            enabled=record.enabled,
            metadata=dict(record.metadata or {}),
        )

    def list_bindings(self) -> list[TaskAgentBinding]:
        return [self.build_binding_for_flow(flow) for flow in self.list_flows()]

    def list_projection_bindings(self) -> list[TaskProjectionBinding]:
        default_bindings = [
            *[_default_projection_binding(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_projection_binding_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": default_bindings},
        )
        bindings: list[TaskProjectionBinding] = []
        for item in list(payload.get("projection_bindings") or []):
            if not isinstance(item, dict):
                continue
            bindings.append(
                TaskProjectionBinding(
                    binding_id=str(item.get("binding_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    projection_selection_mode=str(item.get("projection_selection_mode") or "task_default"),
                    allowed_projection_ids=tuple(
                        str(value).strip()
                        for value in list(item.get("allowed_projection_ids") or [])
                        if str(value).strip()
                    ),
                    default_projection_id=str(item.get("default_projection_id") or ""),
                    projection_required=bool(item.get("projection_required", False)),
                    notes=str(item.get("notes") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return bindings

    def get_projection_binding(self, task_id: str) -> TaskProjectionBinding | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_projection_bindings() if item.task_id == target), None)

    def upsert_projection_binding(
        self,
        *,
        task_id: str,
        projection_selection_mode: str = "task_default",
        allowed_projection_ids: tuple[str, ...] = (),
        default_projection_id: str = "",
        projection_required: bool = False,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskProjectionBinding:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        binding = TaskProjectionBinding(
            binding_id=f"taskprojbind:{target}",
            task_id=target,
            projection_selection_mode=str(projection_selection_mode or "task_default").strip(),
            allowed_projection_ids=tuple(
                str(value).strip()
                for value in allowed_projection_ids
                if str(value).strip()
            ),
            default_projection_id=str(default_projection_id or "").strip(),
            projection_required=bool(projection_required),
            notes=str(notes or "").strip(),
            metadata=dict(metadata or {}),
        )
        bindings = [item for item in self.list_projection_bindings() if item.task_id != target]
        bindings.append(binding)
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in bindings]},
        )
        return binding

    def list_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        default_bindings = [
            *[_default_flow_contract_binding(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_flow_contract_binding_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": default_bindings},
        )
        bindings: list[TaskFlowContractBinding] = []
        for item in list(payload.get("flow_contract_bindings") or []):
            if not isinstance(item, dict):
                continue
            bindings.append(
                TaskFlowContractBinding(
                    binding_id=str(item.get("binding_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    flow_contract_id=str(item.get("flow_contract_id") or ""),
                    override_policy=str(item.get("override_policy") or "task_default"),
                    verification_gate_profile=str(item.get("verification_gate_profile") or ""),
                    fallback_policy=str(item.get("fallback_policy") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return bindings

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
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowContractBinding:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
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
        _write_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": [item.to_dict() for item in bindings]},
        )
        return binding

    def list_task_agent_adoption_plans(self) -> list[TaskAgentAdoptionPlan]:
        default_tasks = [
            *[_synthetic_task_from_general_profile(item) for item in self.list_general_task_profiles()],
            *[self._assignment_from_specific_task_record(item) for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [_default_adoption_plan(item).to_dict() for item in default_tasks]},
        )
        plans: list[TaskAgentAdoptionPlan] = []
        for item in list(payload.get("adoption_plans") or []):
            if not isinstance(item, dict):
                continue
            plans.append(
                TaskAgentAdoptionPlan(
                    plan_id=str(item.get("plan_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    adoption_mode=str(item.get("adoption_mode") or "adopt_existing"),
                    default_agent_id=str(item.get("default_agent_id") or "agent:0"),
                    allowed_agent_categories=tuple(
                        str(value).strip()
                        for value in list(item.get("allowed_agent_categories") or [])
                        if str(value).strip()
                    ),
                    allow_worker_agent_spawn=bool(item.get("allow_worker_agent_spawn", False)),
                    worker_agent_blueprint_id=str(item.get("worker_agent_blueprint_id") or ""),
                    worker_agent_naming_rule=str(item.get("worker_agent_naming_rule") or ""),
                    notes=str(item.get("notes") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return plans

    def get_task_agent_adoption_plan(self, task_id: str) -> TaskAgentAdoptionPlan | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_agent_adoption_plans() if item.task_id == target), None)

    def upsert_task_agent_adoption_plan(
        self,
        *,
        task_id: str,
        adoption_mode: str,
        default_agent_id: str = "agent:0",
        allowed_agent_categories: tuple[str, ...] = (),
        allow_worker_agent_spawn: bool = False,
        worker_agent_blueprint_id: str = "",
        worker_agent_naming_rule: str = "",
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskAgentAdoptionPlan:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        plan = TaskAgentAdoptionPlan(
            plan_id=f"taskadopt:{target}",
            task_id=target,
            adoption_mode=str(adoption_mode or "adopt_existing").strip(),
            default_agent_id=str(default_agent_id or "agent:0").strip() or "agent:0",
            allowed_agent_categories=tuple(
                str(value).strip()
                for value in allowed_agent_categories
                if str(value).strip()
            ),
            allow_worker_agent_spawn=bool(allow_worker_agent_spawn),
            worker_agent_blueprint_id=str(worker_agent_blueprint_id or "").strip(),
            worker_agent_naming_rule=str(worker_agent_naming_rule or "").strip(),
            notes=str(notes or "").strip(),
            metadata=dict(metadata or {}),
        )
        plans = [item for item in self.list_task_agent_adoption_plans() if item.task_id != target]
        plans.append(plan)
        _write_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [item.to_dict() for item in plans]},
        )
        return plan

    def list_task_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        default_profiles = [
            *[_default_memory_request_profile(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_memory_request_profile_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": default_profiles},
        )
        profiles: list[TaskMemoryRequestProfile] = []
        for item in list(payload.get("memory_request_profiles") or []):
            if not isinstance(item, dict):
                continue
            profiles.append(
                TaskMemoryRequestProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    requested_memory_layers=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_memory_layers") or [])
                        if str(value).strip()
                    ),
                    requested_topics=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_topics") or [])
                        if str(value).strip()
                    ),
                    memory_priority=str(item.get("memory_priority") or "normal"),
                    writeback_policy=str(item.get("writeback_policy") or "task_default"),
                    allow_long_term_memory=bool(item.get("allow_long_term_memory", False)),
                    memory_scope_hint=str(item.get("memory_scope_hint") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return profiles

    def get_task_memory_request_profile(self, task_id: str) -> TaskMemoryRequestProfile | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_memory_request_profiles() if item.task_id == target), None)

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
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        profile = TaskMemoryRequestProfile(
            profile_id=f"taskmem:{target}",
            task_id=target,
            requested_memory_layers=tuple(
                str(value).strip()
                for value in requested_memory_layers
                if str(value).strip()
            ),
            requested_topics=tuple(
                str(value).strip()
                for value in requested_topics
                if str(value).strip()
            ),
            memory_priority=str(memory_priority or "normal").strip(),
            writeback_policy=str(writeback_policy or "task_default").strip(),
            allow_long_term_memory=bool(allow_long_term_memory),
            memory_scope_hint=str(memory_scope_hint or "").strip(),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_task_memory_request_profiles() if item.task_id != target]
        profiles.append(profile)
        _write_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": [item.to_dict() for item in profiles]},
        )
        return profile

    def list_coordination_tasks(self) -> list[CoordinationTaskDefinition]:
        payload = _read_json(
            _coordination_tasks_path(self.base_dir),
            {"coordination_tasks": [item.to_dict() for item in default_coordination_tasks()]},
        )
        tasks: list[CoordinationTaskDefinition] = []
        for item in list(payload.get("coordination_tasks") or []):
            if not isinstance(item, dict):
                continue
            tasks.append(
                CoordinationTaskDefinition(
                    coordination_task_id=str(item.get("coordination_task_id") or ""),
                    title=str(item.get("title") or ""),
                    coordination_mode=str(item.get("coordination_mode") or "review_merge"),
                    coordinator_agent_id=str(item.get("coordinator_agent_id") or "agent:0"),
                    participant_agent_ids=tuple(str(value) for value in list(item.get("participant_agent_ids") or []) if str(value)),
                    topology_template_id=str(item.get("topology_template_id") or ""),
                    shared_context_policy=str(item.get("shared_context_policy") or "explicit_refs_only"),
                    memory_sharing_policy=str(item.get("memory_sharing_policy") or "isolated_by_default"),
                    handoff_policy=str(item.get("handoff_policy") or "filtered_handoff"),
                    conflict_resolution_policy=str(item.get("conflict_resolution_policy") or "coordinator_review"),
                    output_merge_policy=str(item.get("output_merge_policy") or "coordinator_final_merge"),
                    stop_conditions=tuple(str(value) for value in list(item.get("stop_conditions") or []) if str(value)),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return tasks

    def list_topology_templates(self) -> list[TopologyTemplate]:
        payload = _read_json(
            _topology_templates_path(self.base_dir),
            {"topology_templates": [item.to_dict() for item in default_topology_templates()]},
        )
        templates: list[TopologyTemplate] = []
        for item in list(payload.get("topology_templates") or []):
            if not isinstance(item, dict):
                continue
            templates.append(
                TopologyTemplate(
                    template_id=str(item.get("template_id") or ""),
                    title=str(item.get("title") or ""),
                    nodes=tuple(dict(value) for value in list(item.get("nodes") or []) if isinstance(value, dict)),
                    edges=tuple(dict(value) for value in list(item.get("edges") or []) if isinstance(value, dict)),
                    handoff_rules=tuple(dict(value) for value in list(item.get("handoff_rules") or []) if isinstance(value, dict)),
                    join_policy=str(item.get("join_policy") or "explicit_join"),
                    failure_policy=str(item.get("failure_policy") or "fail_closed"),
                    terminal_policy=str(item.get("terminal_policy") or "coordinator_terminal"),
                    enabled=bool(item.get("enabled", False)),
                )
            )
        return templates

    def list_task_communication_protocols(self) -> list[TaskCommunicationProtocol]:
        payload = _read_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": [item.to_dict() for item in default_task_communication_protocols()]},
        )
        protocols: list[TaskCommunicationProtocol] = []
        for item in list(payload.get("communication_protocols") or []):
            if not isinstance(item, dict):
                continue
            protocols.append(
                TaskCommunicationProtocol(
                    protocol_id=str(item.get("protocol_id") or ""),
                    title=str(item.get("title") or ""),
                    message_types=tuple(str(value).strip() for value in list(item.get("message_types") or []) if str(value).strip()),
                    payload_contracts=tuple(str(value).strip() for value in list(item.get("payload_contracts") or []) if str(value).strip()),
                    signal_rules=tuple(str(value).strip() for value in list(item.get("signal_rules") or []) if str(value).strip()),
                    handoff_rules=tuple(str(value).strip() for value in list(item.get("handoff_rules") or []) if str(value).strip()),
                    ack_policy=str(item.get("ack_policy") or "explicit_ack"),
                    timeout_policy=str(item.get("timeout_policy") or "fail_closed"),
                    error_signal_policy=str(item.get("error_signal_policy") or "raise_to_coordinator"),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return protocols

    def get_task_communication_protocol(self, protocol_id: str) -> TaskCommunicationProtocol | None:
        target = str(protocol_id or "").strip()
        return next((item for item in self.list_task_communication_protocols() if item.protocol_id == target), None)

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
        target = str(protocol_id or "").strip()
        if not target.startswith("protocol."):
            raise ValueError("protocol_id must start with protocol.")
        protocol = TaskCommunicationProtocol(
            protocol_id=target,
            title=str(title or target).strip(),
            message_types=tuple(
                str(value).strip()
                for value in message_types
                if str(value).strip()
            ),
            payload_contracts=tuple(
                str(value).strip()
                for value in payload_contracts
                if str(value).strip()
            ),
            signal_rules=tuple(
                str(value).strip()
                for value in signal_rules
                if str(value).strip()
            ),
            handoff_rules=tuple(
                str(value).strip()
                for value in handoff_rules
                if str(value).strip()
            ),
            ack_policy=str(ack_policy or "explicit_ack").strip(),
            timeout_policy=str(timeout_policy or "fail_closed").strip(),
            error_signal_policy=str(error_signal_policy or "raise_to_coordinator").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        protocols = [item for item in self.list_task_communication_protocols() if item.protocol_id != target]
        protocols.append(protocol)
        _write_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": [item.to_dict() for item in protocols]},
        )
        return protocol

    def upsert_coordination_task(
        self,
        *,
        coordination_task_id: str,
        title: str,
        coordination_mode: str,
        coordinator_agent_id: str,
        participant_agent_ids: tuple[str, ...] = (),
        topology_template_id: str = "",
        shared_context_policy: str = "explicit_refs_only",
        memory_sharing_policy: str = "isolated_by_default",
        handoff_policy: str = "filtered_handoff",
        conflict_resolution_policy: str = "coordinator_review",
        output_merge_policy: str = "coordinator_final_merge",
        stop_conditions: tuple[str, ...] = (),
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> CoordinationTaskDefinition:
        target = str(coordination_task_id or "").strip()
        if not target.startswith("coord."):
            raise ValueError("coordination_task_id must start with coord.")
        task = CoordinationTaskDefinition(
            coordination_task_id=target,
            title=str(title or target).strip(),
            coordination_mode=str(coordination_mode or "review_merge").strip(),
            coordinator_agent_id=str(coordinator_agent_id or "agent:0").strip() or "agent:0",
            participant_agent_ids=tuple(str(item).strip() for item in participant_agent_ids if str(item).strip()),
            topology_template_id=str(topology_template_id or "").strip(),
            shared_context_policy=str(shared_context_policy or "explicit_refs_only").strip(),
            memory_sharing_policy=str(memory_sharing_policy or "isolated_by_default").strip(),
            handoff_policy=str(handoff_policy or "filtered_handoff").strip(),
            conflict_resolution_policy=str(conflict_resolution_policy or "coordinator_review").strip(),
            output_merge_policy=str(output_merge_policy or "coordinator_final_merge").strip(),
            stop_conditions=tuple(str(item).strip() for item in stop_conditions if str(item).strip()),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        tasks = [item for item in self.list_coordination_tasks() if item.coordination_task_id != target]
        tasks.append(task)
        _write_json(_coordination_tasks_path(self.base_dir), {"coordination_tasks": [item.to_dict() for item in tasks]})
        return task

    def upsert_topology_template(
        self,
        *,
        template_id: str,
        title: str,
        nodes: tuple[dict[str, Any], ...] = (),
        edges: tuple[dict[str, Any], ...] = (),
        handoff_rules: tuple[dict[str, Any], ...] = (),
        join_policy: str = "explicit_join",
        failure_policy: str = "fail_closed",
        terminal_policy: str = "coordinator_terminal",
        enabled: bool = False,
    ) -> TopologyTemplate:
        target = str(template_id or "").strip()
        if not target.startswith("topology."):
            raise ValueError("template_id must start with topology.")
        template = TopologyTemplate(
            template_id=target,
            title=str(title or target).strip(),
            nodes=tuple(dict(item) for item in nodes if isinstance(item, dict)),
            edges=tuple(dict(item) for item in edges if isinstance(item, dict)),
            handoff_rules=tuple(dict(item) for item in handoff_rules if isinstance(item, dict)),
            join_policy=str(join_policy or "explicit_join").strip(),
            failure_policy=str(failure_policy or "fail_closed").strip(),
            terminal_policy=str(terminal_policy or "coordinator_terminal").strip(),
            enabled=bool(enabled),
        )
        templates = [item for item in self.list_topology_templates() if item.template_id != target]
        templates.append(template)
        _write_json(_topology_templates_path(self.base_dir), {"topology_templates": [item.to_dict() for item in templates]})
        return template

    def build_binding_for_flow(self, flow: TaskFlowDefinition) -> TaskAgentBinding:
        agent = self.agent_registry.get_agent(flow.default_agent_id)
        profile = self.agent_runtime_registry.get_profile(flow.default_agent_id)
        diagnostics: dict[str, Any] = {}
        failures: list[str] = []
        if agent is None:
            failures.append("agent_missing")
        elif agent.lifecycle_state not in {"enabled", "system_builtin"}:
            failures.append("agent_not_enabled")
        if profile is None:
            failures.append("runtime_profile_missing")
        else:
            _validate_contains(failures, diagnostics, "task_mode", flow.task_mode, profile.allowed_task_modes)
            _validate_contains(failures, diagnostics, "runtime_lane", flow.default_runtime_lane, profile.allowed_runtime_lanes)
            _validate_contains(failures, diagnostics, "memory_scope", flow.default_memory_scope, profile.allowed_memory_scopes)
            _validate_contains(failures, diagnostics, "output_contract", flow.output_contract_id, profile.output_contracts)
        self._validate_workflow_ref(failures, diagnostics, flow.default_workflow_id)
        return TaskAgentBinding(
            binding_id=f"binding:{flow.flow_id}:{flow.default_agent_id}",
            task_id=f"task-template:{flow.task_mode}",
            flow_id=flow.flow_id,
            agent_id=flow.default_agent_id,
            agent_profile_id=profile.agent_profile_id if profile is not None else "",
            runtime_lane=flow.default_runtime_lane,
            workflow_id=flow.default_workflow_id,
            memory_scope=flow.default_memory_scope,
            output_contract_id=flow.output_contract_id,
            resource_policy_ref=f"resource-policy:{flow.flow_id}:candidate",
            validation_state="valid" if not failures else "invalid",
            diagnostics={**diagnostics, "failures": failures},
        )

    def build_link_permission_matrix(self) -> dict[str, Any]:
        bindings = self.list_bindings()
        return {
            "authority": "task_system.link_permission_matrix",
            "rows": [
                {
                    "agent_id": item.agent_id,
                    "agent_profile_id": item.agent_profile_id,
                    "task_mode": next((flow.task_mode for flow in self.list_flows() if flow.flow_id == item.flow_id), ""),
                    "runtime_lane": item.runtime_lane,
                    "workflow": item.workflow_id,
                    "memory_scope": item.memory_scope,
                    "output_contract": item.output_contract_id,
                    "validation_state": item.validation_state,
                    "blocked_reasons": list(item.diagnostics.get("failures") or []),
                }
                for item in bindings
            ],
        }

    def list_agent_task_connection_profiles(
        self,
        *,
        owner_system: str = "",
        task_family: str = "",
    ) -> list[AgentTaskConnectionProfile]:
        flows = self.list_flows()
        bindings = self.list_bindings()
        topologies = self.list_topology_templates()
        profiles: list[AgentTaskConnectionProfile] = []
        for agent in self.agent_registry.list_agents():
            agent_bindings = [item for item in bindings if item.agent_id == agent.agent_id]
            agent_flows = [flow for flow in flows if any(binding.flow_id == flow.flow_id for binding in agent_bindings)]
            if owner_system and agent.owner_system != owner_system:
                continue
            if task_family and not any(flow.task_family == task_family for flow in agent_flows):
                continue
            capability = self.agent_runtime_registry.get_profile(agent.agent_id)
            topology_refs = tuple(
                template.template_id
                for template in topologies
                if any(dict(node).get("agent_id") == agent.agent_id for node in template.nodes)
            )
            blocked_reasons = tuple(
                dict.fromkeys(
                    reason
                    for binding in agent_bindings
                    for reason in list(binding.diagnostics.get("failures") or [])
                    if reason
                )
            )
            profile_validation_state = "valid" if agent_bindings and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            default_flow = agent_flows[0] if agent_flows else None
            default_binding = agent_bindings[0] if agent_bindings else None
            profiles.append(
                AgentTaskConnectionProfile(
                    profile_id=f"agent-task-connection:{agent.agent_id}",
                    agent_id=agent.agent_id,
                    agent_profile_id=capability.agent_profile_id if capability is not None else "",
                    owner_system=agent.owner_system,
                    profile_type=agent.profile_type,
                    lifecycle_state=agent.lifecycle_state,
                    task_family_refs=tuple(dict.fromkeys(flow.task_family for flow in agent_flows)),
                    available_task_modes=tuple(dict.fromkeys(flow.task_mode for flow in agent_flows)),
                    flow_refs=tuple(flow.flow_id for flow in agent_flows),
                    binding_refs=tuple(binding.binding_id for binding in agent_bindings),
                    workflow_refs=tuple(
                        dict.fromkeys(binding.workflow_id for binding in agent_bindings if binding.workflow_id)
                    ),
                    topology_refs=topology_refs,
                    default_flow_ref=default_flow.flow_id if default_flow is not None else "",
                    default_workflow_ref=default_binding.workflow_id if default_binding is not None else "",
                    default_runtime_lane_hint=default_binding.runtime_lane if default_binding is not None else "",
                    validation_state=profile_validation_state,
                    blocked_reasons=blocked_reasons,
                    diagnostics={
                        "agent": agent.to_dict(),
                        "runtime_profile_present": capability is not None,
                        "flow_count": len(agent_flows),
                        "binding_count": len(agent_bindings),
                        "topology_count": len(topology_refs),
                    },
                )
            )
        return profiles

    def build_agent_task_connection_overview(
        self,
        *,
        owner_system: str = "",
        task_family: str = "",
    ) -> dict[str, Any]:
        profiles = self.list_agent_task_connection_profiles(owner_system=owner_system, task_family=task_family)
        task_families = {family for profile in profiles for family in profile.task_family_refs}
        topology_refs = {topology for profile in profiles for topology in profile.topology_refs}
        return {
            "authority": "task_system.agent_task_connections",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "task_family_count": len(task_families),
                "topology_count": len(topology_refs),
            },
            "diagnostics": {
                "owner_system_filter": owner_system,
                "task_family_filter": task_family,
            },
        }

    def list_agent_task_carrying_profiles(self) -> list[AgentTaskCarryingProfile]:
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        bindings = self.list_bindings()
        binding_by_flow = {item.flow_id: item for item in bindings}
        profiles: list[AgentTaskCarryingProfile] = []
        for agent in self.agent_registry.list_agents():
            carried_general = [
                item
                for item in general_profiles
                if item.default_agent_id == agent.agent_id
            ]
            carried_specific = [
                item
                for item in assignments
                if item.default_agent_id == agent.agent_id or agent.agent_id in set(item.participant_agent_ids)
            ]
            workflow_refs = tuple(
                dict.fromkeys(
                    [
                        *(item.default_workflow_id for item in carried_general if item.default_workflow_id),
                        *(item.workflow_id for item in carried_specific if item.workflow_id),
                    ]
                )
            )
            blocked_reasons = list(self._agent_assignment_failures(agent.agent_id, carried_general, carried_specific))
            for assignment in carried_specific:
                binding = binding_by_flow.get(assignment.flow_id)
                if binding is not None and binding.validation_state != "valid":
                    blocked_reasons.extend(str(item) for item in list(binding.diagnostics.get("failures") or []) if item)
            validation_state = "valid" if (carried_general or carried_specific) and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            profiles.append(
                AgentTaskCarryingProfile(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    profile_type=agent.profile_type,
                    owner_system=agent.owner_system,
                    lifecycle_state=agent.lifecycle_state,
                    carried_general_task_refs=tuple(item.profile_id for item in carried_general),
                    carried_specific_task_refs=tuple(item.task_id for item in carried_specific),
                    workflow_refs=workflow_refs,
                    validation_state=validation_state,
                    blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
                    diagnostics={
                        "general_task_count": len(carried_general),
                        "specific_task_count": len(carried_specific),
                        "workflow_count": len(workflow_refs),
                    },
                )
            )
        return profiles

    def build_agent_carrying_overview(self) -> dict[str, Any]:
        profiles = self.list_agent_task_carrying_profiles()
        return {
            "authority": "task_system.agent_carrying_profiles",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "unbound_profile_count": sum(1 for item in profiles if item.validation_state == "unbound"),
            },
        }

    def build_connection_diagnostics(self) -> dict[str, Any]:
        agents = {item.agent_id for item in self.agent_registry.list_agents()}
        workflows = {item.workflow_id for item in self.workflow_registry.list_workflows()}
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        issues: list[dict[str, Any]] = []
        for profile in general_profiles:
            self._append_ref_issue(issues, profile.profile_id, "general_task", "default_agent_id", profile.default_agent_id, agents)
            if profile.default_workflow_id:
                self._append_ref_issue(issues, profile.profile_id, "general_task", "workflow_id", profile.default_workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(profile.profile_id, "general_task", "workflow_missing", "default_workflow_id"))
        for assignment in assignments:
            self._append_ref_issue(issues, assignment.task_id, "specific_task", "default_agent_id", assignment.default_agent_id, agents)
            for participant_id in assignment.participant_agent_ids:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "participant_agent_id", participant_id, agents)
            if assignment.workflow_id:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "workflow_id", assignment.workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "workflow_missing", "workflow_id"))
            if not assignment.input_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "input_contract_missing", "input_contract_id"))
            if not assignment.output_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "output_contract_missing", "output_contract_id"))
        for profile in self.list_agent_task_carrying_profiles():
            if profile.validation_state == "unbound":
                issues.append(_diagnostic_issue(profile.agent_id, "agent", "agent_without_task", "carried_tasks"))
            for reason in profile.blocked_reasons:
                issues.append(_diagnostic_issue(profile.agent_id, "agent", reason, "task_connection"))
        return {
            "authority": "task_system.connection_diagnostics",
            "issues": issues,
            "summary": {
                "issue_count": len(issues),
                "blocking_issue_count": sum(1 for item in issues if item.get("severity") == "blocking"),
            },
        }

    def _agent_assignment_failures(
        self,
        agent_id: str,
        general_profiles: list[GeneralTaskProfile],
        assignments: list[TaskAssignment],
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if any(item.default_workflow_id and self.workflow_registry.get_workflow(item.default_workflow_id) is None for item in general_profiles):
            failures.append("general_workflow_missing")
        if any(item.workflow_id and self.workflow_registry.get_workflow(item.workflow_id) is None for item in assignments):
            failures.append("specific_workflow_missing")
        if agent_id == "agent:0" and not general_profiles:
            failures.append("main_agent_without_general_task")
        return tuple(dict.fromkeys(failures))

    def _append_ref_issue(
        self,
        issues: list[dict[str, Any]],
        object_id: str,
        object_type: str,
        field: str,
        value: str,
        allowed: set[str],
    ) -> None:
        if not value or value not in allowed:
            issues.append(_diagnostic_issue(object_id, object_type, f"{field}_missing_ref", field, value=value))

    def _validate_workflow_ref(
        self,
        failures: list[str],
        diagnostics: dict[str, Any],
        workflow_id: str,
    ) -> None:
        value = str(workflow_id or "").strip()
        if not value:
            failures.append("workflow_missing")
            diagnostics["workflow"] = {"value": value, "status": "missing"}
            return
        if self.workflow_registry.get_workflow(value) is not None:
            return
        failures.append("workflow_missing")
        diagnostics["workflow"] = {"value": value, "status": "missing"}

    def build_overview(self) -> dict[str, Any]:
        agent_catalog = self.agent_registry.build_catalog()
        flows = self.list_flows()
        bindings = self.list_bindings()
        general_profiles = self.list_general_task_profiles()
        task_assignments = self.list_task_assignments()
        coordination_tasks = self.list_coordination_tasks()
        templates = self.template_registry.list_templates()
        template_validation_matrix = self.template_registry.build_validation_matrix()
        invalid_bindings = [item for item in bindings if item.validation_state != "valid"]
        return {
            "authority": "task_system.overview",
            "summary": {
                "agent_count": agent_catalog["summary"]["agent_count"],
                "main_agent_count": agent_catalog["summary"]["main_agent_count"],
                "system_management_agent_count": agent_catalog["summary"]["system_management_agent_count"],
                "worker_sub_agent_count": agent_catalog["summary"]["worker_sub_agent_count"],
                "general_task_count": len(general_profiles),
                "specific_task_count": len(task_assignments),
                "task_flow_count": len(flows),
                "enabled_task_flow_count": sum(1 for item in flows if item.enabled),
                "task_template_count": len(templates),
                "enabled_task_template_count": sum(1 for item in templates if item.enabled),
                "coordination_task_count": len(coordination_tasks),
                "projection_binding_count": len(self.list_projection_bindings()),
                "flow_contract_binding_count": len(self.list_flow_contract_bindings()),
                "adoption_plan_count": len(self.list_task_agent_adoption_plans()),
                "memory_request_profile_count": len(self.list_task_memory_request_profiles()),
                "communication_protocol_count": len(self.list_task_communication_protocols()),
                "invalid_binding_count": len(invalid_bindings),
                "invalid_template_count": sum(
                    1
                    for item in list(template_validation_matrix.get("rows") or [])
                    if str(item.get("validation_state") or "") != "valid"
                ),
            },
            "agents": agent_catalog["agents"],
            "general_task_profiles": [item.to_dict() for item in general_profiles],
            "specific_task_records": [item.to_dict() for item in self.list_specific_task_records()],
            "task_assignments": [item.to_dict() for item in task_assignments],
            "flows": [item.to_dict() for item in flows],
            "bindings": [item.to_dict() for item in bindings],
            "projection_bindings": [item.to_dict() for item in self.list_projection_bindings()],
            "flow_contract_bindings": [item.to_dict() for item in self.list_flow_contract_bindings()],
            "agent_adoption_plans": [item.to_dict() for item in self.list_task_agent_adoption_plans()],
            "memory_request_profiles": [item.to_dict() for item in self.list_task_memory_request_profiles()],
            "templates": [item.to_dict() for item in templates],
            "template_validation_matrix": template_validation_matrix,
            "coordination_tasks": [item.to_dict() for item in coordination_tasks],
            "topology_templates": [item.to_dict() for item in self.list_topology_templates()],
            "communication_protocols": [item.to_dict() for item in self.list_task_communication_protocols()],
            "link_permission_matrix": self.build_link_permission_matrix(),
            "agent_task_connections": self.build_agent_task_connection_overview(),
            "agent_carrying_profiles": self.build_agent_carrying_overview(),
            "connection_diagnostics": self.build_connection_diagnostics(),
        }


def _validate_contains(
    failures: list[str],
    diagnostics: dict[str, Any],
    field: str,
    value: str,
    allowed: tuple[str, ...],
) -> None:
    if value not in allowed:
        failures.append(f"{field}_not_allowed")
        diagnostics[field] = {"value": value, "allowed": list(allowed)}


def _assignment_from_dict(payload: dict[str, Any]) -> TaskAssignment:
    return TaskAssignment(
        task_id=str(payload.get("task_id") or ""),
        task_title=str(payload.get("task_title") or ""),
        task_kind=str(payload.get("task_kind") or "specific_task"),
        task_family=str(payload.get("task_family") or ""),
        task_mode=str(payload.get("task_mode") or ""),
        flow_id=str(payload.get("flow_id") or ""),
        default_agent_id=str(payload.get("default_agent_id") or "agent:0"),
        participant_agent_ids=tuple(str(item) for item in list(payload.get("participant_agent_ids") or []) if str(item)),
        workflow_id=str(payload.get("workflow_id") or ""),
        workflow_file_ref=str(payload.get("workflow_file_ref") or ""),
        projection_id=str(payload.get("projection_id") or payload.get("projection_template_id") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        safety_policy=dict(payload.get("safety_policy") or {}),
        task_structure=dict(payload.get("task_structure") or {}),
        enabled=bool(payload.get("enabled", True)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _diagnostic_issue(
    object_id: str,
    object_type: str,
    reason: str,
    field: str,
    *,
    value: str = "",
) -> dict[str, Any]:
    return {
        "object_id": object_id,
        "object_type": object_type,
        "reason": reason,
        "field": field,
        "value": value,
        "severity": "blocking" if reason != "agent_without_task" else "warning",
    }
