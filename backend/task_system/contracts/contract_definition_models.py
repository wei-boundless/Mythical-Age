from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CONTRACT_KIND_OPTIONS: tuple[str, ...] = (
    "global_task",
    "workflow",
    "workflow_step",
    "node_execution",
    "edge_handoff",
    "runtime",
    "acceptance",
    "failure",
    "human_gate",
    "final_output",
)

CONTRACT_FIELD_TYPE_OPTIONS: tuple[str, ...] = (
    "string",
    "number",
    "boolean",
    "object",
    "array",
    "artifact_ref",
    "result_ref",
    "agent_ref",
    "task_ref",
    "contract_ref",
)

CONTRACT_FIELD_SOURCE_HINT_OPTIONS: tuple[str, ...] = (
    "user_input",
    "upstream_output",
    "runtime_context",
    "artifact",
    "system",
    "manual_review",
)

CONTRACT_FIELD_VISIBILITY_OPTIONS: tuple[str, ...] = (
    "model_visible",
    "runtime_only",
    "human_only",
    "monitor_visible",
)

ACCEPTANCE_RULE_TYPE_OPTIONS: tuple[str, ...] = (
    "required_field_present",
    "artifact_exists",
    "schema_match",
    "quality_review",
    "model_judge",
    "human_review",
    "custom_runtime_check",
)

ACCEPTANCE_RULE_SEVERITY_OPTIONS: tuple[str, ...] = ("error", "warning", "info")


def _tuple_of_dicts(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


@dataclass(frozen=True, slots=True)
class ContractField:
    field_id: str
    title_zh: str
    field_type: str = "string"
    required: bool = False
    description: str = ""
    default_value: Any = None
    schema: dict[str, Any] = field(default_factory=dict)
    source_hint: str = "user_input"
    visibility: str = "model_visible"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ContractField":
        return cls(
            field_id=str(payload.get("field_id") or "").strip(),
            title_zh=str(payload.get("title_zh") or "").strip(),
            field_type=str(payload.get("field_type") or "string").strip() or "string",
            required=bool(payload.get("required", False)),
            description=str(payload.get("description") or ""),
            default_value=payload.get("default_value"),
            schema=dict(payload.get("schema") or {}),
            source_hint=str(payload.get("source_hint") or "user_input").strip() or "user_input",
            visibility=str(payload.get("visibility") or "model_visible").strip() or "model_visible",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ArtifactRequirement:
    requirement_id: str
    title_zh: str
    artifact_type: str = ""
    required: bool = False
    description: str = ""
    naming_rule: str = ""
    storage_policy: str = "artifact_ref"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactRequirement":
        return cls(
            requirement_id=str(payload.get("requirement_id") or "").strip(),
            title_zh=str(payload.get("title_zh") or "").strip(),
            artifact_type=str(payload.get("artifact_type") or "").strip(),
            required=bool(payload.get("required", False)),
            description=str(payload.get("description") or ""),
            naming_rule=str(payload.get("naming_rule") or ""),
            storage_policy=str(payload.get("storage_policy") or "artifact_ref").strip() or "artifact_ref",
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AcceptanceRule:
    rule_id: str
    title_zh: str
    rule_type: str = "required_field_present"
    severity: str = "error"
    target_field: str = ""
    criteria: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AcceptanceRule":
        return cls(
            rule_id=str(payload.get("rule_id") or "").strip(),
            title_zh=str(payload.get("title_zh") or "").strip(),
            rule_type=str(payload.get("rule_type") or "required_field_present").strip() or "required_field_present",
            severity=str(payload.get("severity") or "error").strip() or "error",
            target_field=str(payload.get("target_field") or ""),
            criteria=str(payload.get("criteria") or ""),
            config=dict(payload.get("config") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeRequirement:
    requirement_id: str
    title_zh: str
    requirement_type: str = "capability"
    required: bool = False
    value: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeRequirement":
        return cls(
            requirement_id=str(payload.get("requirement_id") or "").strip(),
            title_zh=str(payload.get("title_zh") or "").strip(),
            requirement_type=str(payload.get("requirement_type") or "capability").strip() or "capability",
            required=bool(payload.get("required", False)),
            value=str(payload.get("value") or ""),
            config=dict(payload.get("config") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextVisibilityPolicy:
    main_session_history: str = "summary"
    upstream_outputs: str = "summary"
    sibling_nodes: str = "status_only"
    artifact_access: str = "refs_only"
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ContextVisibilityPolicy":
        payload = dict(payload or {})
        return cls(
            main_session_history=str(payload.get("main_session_history") or "summary").strip() or "summary",
            upstream_outputs=str(payload.get("upstream_outputs") or "summary").strip() or "summary",
            sibling_nodes=str(payload.get("sibling_nodes") or "status_only").strip() or "status_only",
            artifact_access=str(payload.get("artifact_access") or "refs_only").strip() or "refs_only",
            notes=str(payload.get("notes") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HandoffPolicy:
    handoff_mode: str = "structured_packet"
    include_artifact_refs: bool = True
    include_raw_messages: bool = False
    ack_required: bool = True
    timeout_policy: str = "fail_closed"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "HandoffPolicy":
        payload = dict(payload or {})
        return cls(
            handoff_mode=str(payload.get("handoff_mode") or "structured_packet").strip() or "structured_packet",
            include_artifact_refs=bool(payload.get("include_artifact_refs", True)),
            include_raw_messages=bool(payload.get("include_raw_messages", False)),
            ack_required=bool(payload.get("ack_required", True)),
            timeout_policy=str(payload.get("timeout_policy") or "fail_closed").strip() or "fail_closed",
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    failure_mode: str = "fail_closed"
    retry_allowed: bool = False
    retry_limit: int = 0
    escalate_to: str = "coordinator"
    fallback_contract_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "FailurePolicy":
        payload = dict(payload or {})
        return cls(
            failure_mode=str(payload.get("failure_mode") or "fail_closed").strip() or "fail_closed",
            retry_allowed=bool(payload.get("retry_allowed", False)),
            retry_limit=int(payload.get("retry_limit") or 0),
            escalate_to=str(payload.get("escalate_to") or "coordinator").strip() or "coordinator",
            fallback_contract_id=str(payload.get("fallback_contract_id") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HumanGatePolicy:
    required: bool = False
    gate_type: str = "none"
    reviewer_role: str = ""
    decision_contract_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "HumanGatePolicy":
        payload = dict(payload or {})
        return cls(
            required=bool(payload.get("required", False)),
            gate_type=str(payload.get("gate_type") or "none").strip() or "none",
            reviewer_role=str(payload.get("reviewer_role") or ""),
            decision_contract_id=str(payload.get("decision_contract_id") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContractValidationIssue:
    contract_id: str
    field: str
    reason: str
    severity: str = "error"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContractSpec:
    contract_id: str
    title_zh: str
    title_en: str = ""
    contract_kind: str = "workflow"
    description: str = ""
    input_fields: tuple[ContractField, ...] = ()
    output_fields: tuple[ContractField, ...] = ()
    artifact_requirements: tuple[ArtifactRequirement, ...] = ()
    acceptance_rules: tuple[AcceptanceRule, ...] = ()
    runtime_requirements: tuple[RuntimeRequirement, ...] = ()
    context_visibility_policy: ContextVisibilityPolicy = field(default_factory=ContextVisibilityPolicy)
    handoff_policy: HandoffPolicy = field(default_factory=HandoffPolicy)
    failure_policy: FailurePolicy = field(default_factory=FailurePolicy)
    human_gate_policy: HumanGatePolicy = field(default_factory=HumanGatePolicy)
    allowed_agent_kinds: tuple[str, ...] = ()
    allowed_runtime_lanes: tuple[str, ...] = ()
    version: str = "1.0.0"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ContractSpec":
        return cls(
            contract_id=str(payload.get("contract_id") or "").strip(),
            title_zh=str(payload.get("title_zh") or "").strip(),
            title_en=str(payload.get("title_en") or "").strip(),
            contract_kind=str(payload.get("contract_kind") or "workflow").strip() or "workflow",
            description=str(payload.get("description") or ""),
            input_fields=tuple(ContractField.from_dict(item) for item in _tuple_of_dicts(payload.get("input_fields"))),
            output_fields=tuple(ContractField.from_dict(item) for item in _tuple_of_dicts(payload.get("output_fields"))),
            artifact_requirements=tuple(
                ArtifactRequirement.from_dict(item) for item in _tuple_of_dicts(payload.get("artifact_requirements"))
            ),
            acceptance_rules=tuple(
                AcceptanceRule.from_dict(item) for item in _tuple_of_dicts(payload.get("acceptance_rules"))
            ),
            runtime_requirements=tuple(
                RuntimeRequirement.from_dict(item) for item in _tuple_of_dicts(payload.get("runtime_requirements"))
            ),
            context_visibility_policy=ContextVisibilityPolicy.from_dict(payload.get("context_visibility_policy")),
            handoff_policy=HandoffPolicy.from_dict(payload.get("handoff_policy")),
            failure_policy=FailurePolicy.from_dict(payload.get("failure_policy")),
            human_gate_policy=HumanGatePolicy.from_dict(payload.get("human_gate_policy")),
            allowed_agent_kinds=_tuple_of_strings(payload.get("allowed_agent_kinds")),
            allowed_runtime_lanes=_tuple_of_strings(payload.get("allowed_runtime_lanes")),
            version=str(payload.get("version") or "1.0.0").strip() or "1.0.0",
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "title_zh": self.title_zh,
            "title_en": self.title_en,
            "contract_kind": self.contract_kind,
            "description": self.description,
            "input_fields": [item.to_dict() for item in self.input_fields],
            "output_fields": [item.to_dict() for item in self.output_fields],
            "artifact_requirements": [item.to_dict() for item in self.artifact_requirements],
            "acceptance_rules": [item.to_dict() for item in self.acceptance_rules],
            "runtime_requirements": [item.to_dict() for item in self.runtime_requirements],
            "context_visibility_policy": self.context_visibility_policy.to_dict(),
            "handoff_policy": self.handoff_policy.to_dict(),
            "failure_policy": self.failure_policy.to_dict(),
            "human_gate_policy": self.human_gate_policy.to_dict(),
            "allowed_agent_kinds": list(self.allowed_agent_kinds),
            "allowed_runtime_lanes": list(self.allowed_runtime_lanes),
            "version": self.version,
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
        }


