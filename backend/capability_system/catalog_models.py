from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentCapability:
    agent_id: str
    name: str
    kind: str
    description: str
    bound_tools: list[str] = field(default_factory=list)
    protocol_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MCPCapability:
    mcp_id: str
    unit_id: str
    route: str
    name: str
    description: str
    operation_id: str
    transport: str
    model_visibility: str
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityBindingEdge:
    from_id: str
    from_label: str
    to_id: str
    to_label: str
    relation: str

    def to_operation_edge(self) -> dict[str, str]:
        return {
            "from": self.from_id,
            "from_label": self.from_label,
            "to": self.to_id,
            "to_label": self.to_label,
            "relation": self.relation,
        }


@dataclass(frozen=True, slots=True)
class CapabilityBindingGraph:
    agent_nodes: list[AgentCapability] = field(default_factory=list)
    mcp_nodes: list[MCPCapability] = field(default_factory=list)
    agent_tool_edges: list[CapabilityBindingEdge] = field(default_factory=list)
    mcp_operation_edges: list[CapabilityBindingEdge] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_operation_payload(self) -> dict[str, Any]:
        return {
            "agent_nodes": [node.to_dict() for node in self.agent_nodes],
            "mcp_nodes": [node.to_dict() for node in self.mcp_nodes],
            "agent_tool_edges": [edge.to_operation_edge() for edge in self.agent_tool_edges],
            "mcp_operation_edges": [edge.to_operation_edge() for edge in self.mcp_operation_edges],
            "recommendations": list(self.recommendations),
        }


@dataclass(frozen=True, slots=True)
class CapabilityValidationIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityHealth:
    status: str = "active"
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityPermissionView:
    capability_id: str
    operation_ids: tuple[str, ...] = ()
    profile_state: str = "unknown"
    adoption_state: str = "not_checked"
    gate_state: str = "not_checked"
    approval_state: str = "not_required"
    sandbox_state: str = "none"
    reasons: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_ids"] = list(self.operation_ids)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True, slots=True)
class CapabilityDependency:
    from_id: str
    to_id: str
    relation: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityUnit:
    capability_id: str
    kind: str
    title: str
    summary: str
    operation_ids: tuple[str, ...]
    provider: str
    provider_kind: str
    transport: str = ""
    runtime_visibility: str = ""
    model_visibility: str = ""
    risk: tuple[str, ...] = ()
    resource_policy: str = ""
    status: str = "active"
    source_ref: str = ""
    dependencies: tuple[CapabilityDependency, ...] = ()
    health: CapabilityHealth = field(default_factory=CapabilityHealth)
    permission_view: CapabilityPermissionView | None = None
    display_facets: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_ids"] = list(self.operation_ids)
        payload["risk"] = list(self.risk)
        payload["dependencies"] = [dependency.to_dict() for dependency in self.dependencies]
        payload["health"] = self.health.to_dict()
        payload["permission_view"] = self.permission_view.to_dict() if self.permission_view is not None else None
        return payload


@dataclass(frozen=True, slots=True)
class CapabilitySupplyToolRef:
    tool_name: str
    operation_id: str
    tool_type: str
    runtime_visibility: str
    prompt_exposure_policy: str
    risk_level: str
    source_class: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilitySupplySkillRef:
    skill_name: str
    title: str
    activation_policy: str
    context_mode: str
    preferred_route: str = ""
    capability_tags: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capability_tags"] = list(self.capability_tags)
        payload["operation_ids"] = list(self.operation_ids)
        payload["capability_ids"] = list(self.capability_ids)
        return payload


@dataclass(frozen=True, slots=True)
class CapabilitySupplyMCPRef:
    mcp_id: str
    operation_id: str
    route: str
    unit_id: str
    transport: str
    model_visibility: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilitySupplyPackage:
    package_id: str
    task_id: str
    agent_id: str
    tool_refs: list[CapabilitySupplyToolRef] = field(default_factory=list)
    skill_refs: list[CapabilitySupplySkillRef] = field(default_factory=list)
    mcp_refs: list[CapabilitySupplyMCPRef] = field(default_factory=list)
    capability_constraints: dict[str, Any] = field(default_factory=dict)
    visibility_rules: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "capability_system.supply_package"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tool_refs"] = [item.to_dict() for item in self.tool_refs]
        payload["skill_refs"] = [item.to_dict() for item in self.skill_refs]
        payload["mcp_refs"] = [item.to_dict() for item in self.mcp_refs]
        return payload


