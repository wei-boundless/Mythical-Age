from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EngagementPlanStatus = Literal["draft", "active", "deprecated", "disabled", "archived"]
EngagementAssigneeKind = Literal["agent", "workflow", "human", "system"]
EngagementExecutionKind = Literal[
    "graph_task_run",
]
EngagementAdmissionDecision = Literal["allow", "deny", "ask_user", "requires_approval", "invalid"]
EngagementRunStatus = Literal[
    "requested",
    "admitted",
    "assembled",
    "running",
    "waiting_user",
    "waiting_approval",
    "completed",
    "blocked",
    "failed",
    "canceled",
]


@dataclass(frozen=True, slots=True)
class EngagementAssignee:
    kind: EngagementAssigneeKind
    agent_id: str = ""
    agent_profile_id: str = ""
    workflow_id: str = ""
    participant_agent_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participant_agent_ids"] = list(self.participant_agent_ids)
        return payload


@dataclass(frozen=True, slots=True)
class EngagementRuntimeProfile:
    runtime_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EngagementExecutionStrategy:
    kind: EngagementExecutionKind
    startup_policy: dict[str, Any] = field(default_factory=dict)
    lifecycle_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RegisteredEngagementPlan:
    plan_id: str
    title: str
    task_environment_id: str
    assignee: EngagementAssignee
    runtime_profile: EngagementRuntimeProfile
    execution_strategy: EngagementExecutionStrategy
    description: str = ""
    version: str = "1.0.0"
    status: EngagementPlanStatus = "draft"
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    prompt_contract: dict[str, Any] = field(default_factory=dict)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    capability_requirements: dict[str, Any] = field(default_factory=dict)
    memory_requirements: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    supersedes_plan_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.registered_engagement_plan"

    def __post_init__(self) -> None:
        if self.authority != "task_system.registered_engagement_plan":
            raise ValueError("RegisteredEngagementPlan authority must be task_system.registered_engagement_plan")
        if not self.plan_id:
            raise ValueError("RegisteredEngagementPlan requires plan_id")
        if not self.title:
            raise ValueError("RegisteredEngagementPlan requires title")
        if not self.task_environment_id:
            raise ValueError("RegisteredEngagementPlan requires task_environment_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assignee"] = self.assignee.to_dict()
        payload["runtime_profile"] = self.runtime_profile.to_dict()
        payload["execution_strategy"] = self.execution_strategy.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class EngagementRequest:
    request_id: str
    plan_id: str
    startup_parameters: dict[str, Any] = field(default_factory=dict)
    requested_by: Literal["user", "agent", "workflow", "system"] = "user"
    source_ref: str = ""
    session_id: str = ""
    user_visible_request: str = ""
    authority: str = "task_system.engagement_request"

    def __post_init__(self) -> None:
        if self.authority != "task_system.engagement_request":
            raise ValueError("EngagementRequest authority must be task_system.engagement_request")
        if not self.request_id:
            raise ValueError("EngagementRequest requires request_id")
        if not self.plan_id:
            raise ValueError("EngagementRequest requires plan_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResolvedEngagementPlan:
    request: EngagementRequest
    plan: RegisteredEngagementPlan
    task_environment: dict[str, Any]
    assignee_profile: dict[str, Any]
    execution_strategy: EngagementExecutionStrategy
    runtime_profile: EngagementRuntimeProfile
    backend_dir: str = ""
    missing_refs: tuple[str, ...] = ()
    authority: str = "task_system.resolved_engagement_plan"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["request"] = self.request.to_dict()
        payload["plan"] = self.plan.to_dict()
        payload["execution_strategy"] = self.execution_strategy.to_dict()
        payload["runtime_profile"] = self.runtime_profile.to_dict()
        payload["missing_refs"] = list(self.missing_refs)
        return payload


@dataclass(frozen=True, slots=True)
class EngagementContract:
    contract_id: str
    request_id: str
    plan_id: str
    plan_version: str
    task_environment_id: str
    assignee: EngagementAssignee
    runtime_profile: EngagementRuntimeProfile
    execution_strategy: EngagementExecutionStrategy
    startup_parameters: dict[str, Any] = field(default_factory=dict)
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    prompt_contract: dict[str, Any] = field(default_factory=dict)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    capability_requirements: dict[str, Any] = field(default_factory=dict)
    memory_requirements: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.engagement_contract"

    def __post_init__(self) -> None:
        if self.authority != "task_system.engagement_contract":
            raise ValueError("EngagementContract authority must be task_system.engagement_contract")
        if not self.contract_id:
            raise ValueError("EngagementContract requires contract_id")
        if not self.plan_id:
            raise ValueError("EngagementContract requires plan_id")
        if not self.task_environment_id:
            raise ValueError("EngagementContract requires task_environment_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assignee"] = self.assignee.to_dict()
        payload["runtime_profile"] = self.runtime_profile.to_dict()
        payload["execution_strategy"] = self.execution_strategy.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class EngagementAdmissionResult:
    decision: EngagementAdmissionDecision
    plan_ref: str
    resolved_task_environment_id: str
    resolved_agent_profile_id: str
    execution_strategy: dict[str, Any]
    input_errors: tuple[str, ...] = ()
    capability_errors: tuple[str, ...] = ()
    environment_errors: tuple[str, ...] = ()
    user_visible_reason: str = ""
    authority: str = "task_system.engagement_admission"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_errors"] = list(self.input_errors)
        payload["capability_errors"] = list(self.capability_errors)
        payload["environment_errors"] = list(self.environment_errors)
        return payload


@dataclass(frozen=True, slots=True)
class EngagementRunRecord:
    engagement_run_id: str
    request_id: str
    contract_id: str
    plan_id: str
    plan_version: str
    strategy_kind: str
    status: EngagementRunStatus
    task_run_id: str = ""
    turn_result_ref: str = ""
    workflow_run_id: str = ""
    human_gate_id: str = ""
    artifact_refs: tuple[dict[str, Any], ...] = ()
    verification_refs: tuple[dict[str, Any], ...] = ()
    closeout: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.engagement_run"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["verification_refs"] = [dict(item) for item in self.verification_refs]
        return payload


@dataclass(frozen=True, slots=True)
class EngagementEvent:
    engagement_run_id: str
    event_type: str
    summary: str
    payload_ref: str = ""
    user_visible: bool = True
    created_at: str = ""
    authority: str = "task_system.engagement_event"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
