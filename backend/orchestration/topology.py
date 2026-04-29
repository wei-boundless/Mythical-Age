from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TopologyMode = Literal["single_agent", "multi_agent", "hybrid"]


@dataclass(slots=True, frozen=True)
class ExecutionTopologyPreview:
    """Preview-only topology decision for the current turn.

    The default topology is single_agent. Multi-agent topology must later be
    explicitly adopted by the control plane before any AgentSeat can execute.
    """

    topology_id: str
    task_id: str
    mode: TopologyMode = "single_agent"
    reason: str = "single_agent_default"
    candidate_refs: tuple[str, ...] = ()
    coordination_policy_ref: str = ""
    preview_only: bool = True
    adopted: bool = False
    runtime_executable: bool = False
    authority: str = "topology_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("ExecutionTopologyPreview must remain preview_only")
        if self.adopted:
            raise ValueError("ExecutionTopologyPreview cannot be adopted")
        if self.runtime_executable:
            raise ValueError("ExecutionTopologyPreview cannot be runtime executable")
        if self.authority != "topology_preview":
            raise ValueError("ExecutionTopologyPreview cannot carry execution authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidate_refs"] = list(self.candidate_refs)
        return payload


@dataclass(slots=True, frozen=True)
class CoordinationPolicyPreview:
    """Preview-only coordination policy for optional future multi-agent work."""

    policy_id: str
    task_id: str
    max_agents: int = 1
    max_parallelism: int = 1
    allowed_agent_profiles: tuple[str, ...] = ()
    allowed_shared_channels: tuple[str, ...] = ()
    allow_recursive_delegation: bool = False
    default_isolation_mode: str = "isolated"
    approval_mode: str = "fail_closed"
    preview_only: bool = True
    adopted: bool = False
    runtime_executable: bool = False
    authority: str = "coordination_policy_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_agents < 1:
            raise ValueError("CoordinationPolicyPreview.max_agents must be at least 1")
        if self.max_parallelism < 1:
            raise ValueError("CoordinationPolicyPreview.max_parallelism must be at least 1")
        if not self.preview_only:
            raise ValueError("CoordinationPolicyPreview must remain preview_only")
        if self.adopted:
            raise ValueError("CoordinationPolicyPreview cannot be adopted")
        if self.runtime_executable:
            raise ValueError("CoordinationPolicyPreview cannot be runtime executable")
        if self.authority != "coordination_policy_preview":
            raise ValueError("CoordinationPolicyPreview cannot carry execution authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_agent_profiles"] = list(self.allowed_agent_profiles)
        payload["allowed_shared_channels"] = list(self.allowed_shared_channels)
        return payload


@dataclass(slots=True, frozen=True)
class AgentSeatPlanPreview:
    """A future bounded agent seat. It is never executable in preview."""

    seat_id: str
    role: str
    stage_ref: str
    task_contract_ref: str
    candidate_profile_refs: tuple[str, ...] = ()
    resource_policy_ref: str = ""
    memory_scope: str = "none"
    memory_policy_ref: str = ""
    shared_channels: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    output_contract_ref: str = ""
    preview_only: bool = True
    runtime_executable: bool = False
    authority: str = "agent_seat_preview"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("AgentSeatPlanPreview must remain preview_only")
        if self.runtime_executable:
            raise ValueError("AgentSeatPlanPreview cannot be runtime executable")
        if self.authority != "agent_seat_preview":
            raise ValueError("AgentSeatPlanPreview cannot carry execution authority")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidate_profile_refs"] = list(self.candidate_profile_refs)
        payload["shared_channels"] = list(self.shared_channels)
        payload["depends_on"] = list(self.depends_on)
        return payload


@dataclass(slots=True, frozen=True)
class AgentAssignmentCandidate:
    """Candidate-only assignment of an agent profile to a future AgentSeat."""

    assignment_id: str
    seat_ref: str
    agent_profile_ref: str
    reason: str
    confidence: float = 0.0
    authority: str = "candidate_only"
    preview_only: bool = True

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("AgentAssignmentCandidate must remain candidate_only")
        if not self.preview_only:
            raise ValueError("AgentAssignmentCandidate must remain preview_only")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("AgentAssignmentCandidate.confidence must be between 0.0 and 1.0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class AgentResultCandidate:
    """Bounded agent output candidate. It cannot become the final answer by itself."""

    result_id: str
    seat_ref: str
    agent_instance_ref: str
    summary: str = ""
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "candidate_only"
    final_answer: bool = False

    def __post_init__(self) -> None:
        if self.authority != "candidate_only":
            raise ValueError("AgentResultCandidate must remain candidate_only")
        if self.final_answer:
            raise ValueError("AgentResultCandidate cannot be a final answer")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


def build_single_agent_topology_preview(
    *,
    task_id: str,
    reason: str = "single_agent_default",
) -> tuple[ExecutionTopologyPreview, CoordinationPolicyPreview]:
    policy = CoordinationPolicyPreview(
        policy_id=f"coordpol:{task_id}:single-agent:preview",
        task_id=task_id,
        max_agents=1,
        max_parallelism=1,
        diagnostics={
            "single_agent_default": True,
            "multi_agent_enabled": False,
            "agent_seat_count": 0,
            "fail_closed": True,
        },
    )
    topology = ExecutionTopologyPreview(
        topology_id=f"topology:{task_id}:single-agent:preview",
        task_id=task_id,
        mode="single_agent",
        reason=reason,
        coordination_policy_ref=policy.policy_id,
        diagnostics={
            "single_agent_default": True,
            "multi_agent_enabled": False,
            "agent_seat_count": 0,
            "fail_closed": True,
        },
    )
    return topology, policy
