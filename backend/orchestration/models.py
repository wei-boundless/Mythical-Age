from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


PlanMode = Literal["legacy", "plan_only", "primary"]
ExecutionMode = Literal["single_execution", "bundle_execution", "explicit_fanout"]
ExecutionKind = Literal["agent", "direct_tool", "worker"]
DecisionStatus = Literal["selected", "candidate", "blocked", "skipped", "warning"]
ValidationStatus = Literal["passed", "blocked", "warning", "skipped"]


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
class IntentFrame:
    user_goal: str = ""
    intent: str = "general_query"
    task_kind: str = "knowledge_lookup"
    source_kind: str = "knowledge_base"
    modality: str = "general"
    route: str = "unknown"
    source_needs: list[str] = field(default_factory=list)
    freshness_required: bool = False
    needs_tool: bool = False
    needs_agent: bool = True
    risk_signals: list[str] = field(default_factory=list)
    confidence: float = 0.0
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryPolicy:
    read_mode: str = "none"
    write_mode: str = "none"
    use_session_state: bool = False
    use_durable_memory: bool = False
    ignore_memory: bool = False
    restored_candidates: list[str] = field(default_factory=list)
    writeback_scope: list[str] = field(default_factory=list)
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextPolicyDecision:
    mode: str = "runtime"
    summary: str = ""
    required_handles: list[str] = field(default_factory=list)
    evidence_budget: str = "normal"
    prompt_sections: list[str] = field(default_factory=list)
    restore_indexes: list[str] = field(default_factory=list)
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResourcePolicy:
    allowed_sources: list[str] = field(default_factory=list)
    allowed_skills: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    allowed_agents: list[str] = field(default_factory=list)
    allowed_workers: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    source_policy: list[str] | None = None
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionDirective:
    step_id: str
    action: str
    execution_id: str = ""
    skill: str = ""
    tool: str = ""
    agent_id: str = ""
    worker_route: str = ""
    input_summary: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    risk_tags: list[str] = field(default_factory=list)
    shared_channels: list[str] = field(default_factory=list)
    fallback: str = "legacy_runtime"
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnswerPolicy:
    require_citations: bool = False
    hide_internal_protocol: bool = True
    allow_fallback: bool = True
    answer_channel: str = "runtime_output_boundary"
    memory_writeback_allowed: bool = False
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidationDecision:
    status: ValidationStatus = "skipped"
    issues: list[dict[str, Any]] = field(default_factory=list)
    checked_rules: list[str] = field(default_factory=list)
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
    mode: str = "plan_only"
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
    intent_frame: IntentFrame = field(default_factory=IntentFrame)
    memory_policy: MemoryPolicy = field(default_factory=MemoryPolicy)
    resource_policy: ResourcePolicy = field(default_factory=ResourcePolicy)
    execution_directives: list[ExecutionDirective] = field(default_factory=list)
    answer_policy: AnswerPolicy = field(default_factory=AnswerPolicy)
    validation: ValidationDecision = field(default_factory=ValidationDecision)
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
            "intent_frame": self.intent_frame.to_dict(),
            "memory_policy": self.memory_policy.to_dict(),
            "resource_policy": self.resource_policy.to_dict(),
            "execution_directives": [item.to_dict() for item in self.execution_directives],
            "answer_policy": self.answer_policy.to_dict(),
            "validation": self.validation.to_dict(),
            "decisions": [item.to_dict() for item in self.decisions],
            "executions": [item.to_dict() for item in self.executions],
            "context_policy": self.context_policy.to_dict(),
            "prompt_policy": self.prompt_policy.to_dict(),
            "output_policy": self.output_policy.to_dict(),
            "safety": self.safety.to_dict(),
            "diagnostics": dict(self.diagnostics),
        }
