from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


PlanMode = Literal["legacy", "shadow", "primary"]
ExecutionMode = Literal["single_execution", "bundle_execution", "explicit_fanout"]
ExecutionKind = Literal["agent", "direct_tool", "worker"]
DecisionStatus = Literal["selected", "candidate", "blocked", "skipped", "warning"]


@dataclass(slots=True)
class ExecutionTopology:
    mode: str = "single_execution"
    route: str = "unknown"
    execution_kind: str = "agent"
    reason: str = ""
    branch_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OrchestrationDecision:
    node_id: str
    node_type: str
    owner_module: str
    status: DecisionStatus = "selected"
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OrchestrationExecution:
    execution_id: str
    message: str
    route: str
    execution_kind: str
    skill_name: str = ""
    tool_name: str = ""
    worker_route: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    worker_request: dict[str, Any] | None = None
    structured_binding: dict[str, Any] | None = None
    arbitration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextPolicyDecision:
    mode: str = "runtime"
    summary: str = ""
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PromptAssemblyDecision:
    mode: str = "runtime"
    active_skill_name: str = ""
    tool_schema_names: list[str] = field(default_factory=list)
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OutputPolicyDecision:
    mode: str = "runtime"
    answer_channel: str = ""
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SafetyDecision:
    mode: str = "shadow"
    warnings: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OrchestrationPlan:
    plan_id: str
    session_id: str
    input_text: str
    source: str
    mode: PlanMode
    behavior_policy_id: str
    topology: ExecutionTopology
    decisions: list[OrchestrationDecision] = field(default_factory=list)
    executions: list[OrchestrationExecution] = field(default_factory=list)
    context_policy: ContextPolicyDecision = field(default_factory=ContextPolicyDecision)
    prompt_policy: PromptAssemblyDecision = field(default_factory=PromptAssemblyDecision)
    output_policy: OutputPolicyDecision = field(default_factory=OutputPolicyDecision)
    safety: SafetyDecision = field(default_factory=SafetyDecision)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "input_text": self.input_text,
            "source": self.source,
            "mode": self.mode,
            "behavior_policy_id": self.behavior_policy_id,
            "topology": self.topology.to_dict(),
            "decisions": [item.to_dict() for item in self.decisions],
            "executions": [item.to_dict() for item in self.executions],
            "context_policy": self.context_policy.to_dict(),
            "prompt_policy": self.prompt_policy.to_dict(),
            "output_policy": self.output_policy.to_dict(),
            "safety": self.safety.to_dict(),
            "diagnostics": dict(self.diagnostics),
        }
