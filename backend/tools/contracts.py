from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


ToolScopeSource = Literal["global", "skill", "agent", "session", "explicit_user", "legacy"]
ToolScopeTrustLevel = Literal["system", "project", "user", "external", "unknown"]


@dataclass(frozen=True, slots=True)
class ToolScope:
    """Typed tool scope for permission/contract layers.

    A scope is a narrowing constraint, not an allow-by-itself permission.
    """

    source: ToolScopeSource = "global"
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    capability_constraints: tuple[str, ...] = ()
    trust_level: ToolScopeTrustLevel = "unknown"
    reason: str = ""

    @classmethod
    def from_allowed_tools(
        cls,
        allowed_tools: Iterable[str] | None,
        *,
        source: ToolScopeSource = "legacy",
        trust_level: ToolScopeTrustLevel = "unknown",
        reason: str = "",
    ) -> "ToolScope":
        return cls(
            source=source,
            allowed_tools=_normalize_names(allowed_tools),
            trust_level=trust_level,
            reason=reason,
        )

    @property
    def has_allowed_filter(self) -> bool:
        return bool(self.allowed_tools)

    def allows(self, tool_name: str | None) -> bool:
        normalized = str(tool_name or "").strip()
        if not normalized:
            return False
        if normalized in set(self.denied_tools):
            return False
        if self.allowed_tools and normalized not in set(self.allowed_tools):
            return False
        return True

    def to_allowed_tools(self) -> list[str]:
        return list(self.allowed_tools)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillToolScope(ToolScope):
    skill_name: str = ""
    activation_policy: str = "model_visible"
    context_mode: str = "inline"


def _normalize_names(values: Iterable[str] | None) -> tuple[str, ...]:
    names = []
    seen = set()
    for value in values or []:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return tuple(names)


def coerce_tool_scope(
    scope: ToolScope | Iterable[str] | None,
    *,
    source: ToolScopeSource = "legacy",
    trust_level: ToolScopeTrustLevel = "unknown",
    reason: str = "",
) -> ToolScope:
    if isinstance(scope, ToolScope):
        return scope
    return ToolScope.from_allowed_tools(
        scope,
        source=source,
        trust_level=trust_level,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class ToolExecutionContract:
    required_inputs: list[str] = field(default_factory=list)
    required_bindings: list[str] = field(default_factory=list)
    optional_inputs: list[str] = field(default_factory=list)
    owner_scope: str = "none"
    allow_catalog_default: bool = False
    allow_history_binding: bool = False
    missing_binding_behavior: str = "clarify"
    context_policy: str = "inline"
    result_channel: str = "canonical"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolResolutionContract:
    path_field: str = ""
    path_kind: str = ""
    binding_field: str = ""
    allow_message_extraction: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolOutputContract:
    display_mode: str = "summary_text"
    finalization_policy: str = "none"
    persistence_policy: str = "persist_canonical"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolProjectionContract:
    task_summary_policy: str = "canonical_only"
    result_ref_policy: str = "default"
    memory_projection_policy: str = "canonical_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolContractDecision:
    tool_name: str
    mode: str
    action: str
    reason: str
    missing_inputs: list[str] = field(default_factory=list)
    missing_bindings: list[str] = field(default_factory=list)
    contract: ToolExecutionContract = field(default_factory=ToolExecutionContract)

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @property
    def should_block(self) -> bool:
        return self.mode == "enforce" and not self.allowed

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed"] = self.allowed
        payload["should_block"] = self.should_block
        return payload


@dataclass(slots=True)
class ToolContractGate:
    mode: str = "shadow"

    def evaluate(
        self,
        *,
        tool_name: str,
        contract: ToolExecutionContract,
        tool_input: dict[str, Any] | None,
        tool_scope: ToolScope | Iterable[str] | None = None,
        binding_context: dict[str, Any] | None = None,
    ) -> ToolContractDecision:
        normalized_input = dict(tool_input or {})
        normalized_bindings = dict(binding_context or {})
        normalized_mode = (self.mode or "shadow").strip().lower() or "shadow"
        effective_scope = coerce_tool_scope(
            tool_scope,
            source="legacy",
            reason="tool_contract_gate",
        )
        if not effective_scope.allows(tool_name):
            return ToolContractDecision(
                tool_name=tool_name,
                mode=normalized_mode,
                action="deny",
                reason="tool_not_allowed_by_skill_contract",
                contract=contract,
            )

        missing_inputs = [
            field_name
            for field_name in contract.required_inputs
            if _is_blank(normalized_input.get(field_name))
        ]
        if missing_inputs:
            return ToolContractDecision(
                tool_name=tool_name,
                mode=normalized_mode,
                action="clarify",
                reason="missing_required_input",
                missing_inputs=missing_inputs,
                contract=contract,
            )

        missing_bindings = self._missing_bindings(
            contract=contract,
            tool_input=normalized_input,
            binding_context=normalized_bindings,
        )
        if missing_bindings:
            return ToolContractDecision(
                tool_name=tool_name,
                mode=normalized_mode,
                action=contract.missing_binding_behavior,
                reason="missing_required_binding",
                missing_bindings=missing_bindings,
                contract=contract,
            )

        return ToolContractDecision(
            tool_name=tool_name,
            mode=normalized_mode,
            action="allow",
            reason="contract_satisfied",
            contract=contract,
        )

    def _missing_bindings(
        self,
        *,
        contract: ToolExecutionContract,
        tool_input: dict[str, Any],
        binding_context: dict[str, Any],
    ) -> list[str]:
        owner_scope = (contract.owner_scope or "none").strip().lower()
        if owner_scope == "none":
            return []

        path_value = tool_input.get("path")
        explicit_path_present = not _is_blank(path_value)

        if owner_scope == "explicit_path":
            return [] if explicit_path_present else ["explicit_path"]

        if owner_scope == "active_binding":
            return [
                binding_name
                for binding_name in contract.required_bindings
                if _is_blank(binding_context.get(binding_name))
            ]

        if owner_scope == "active_binding_or_explicit_path":
            if explicit_path_present:
                return []
            return [
                binding_name
                for binding_name in contract.required_bindings
                if _is_blank(binding_context.get(binding_name))
            ]

        return []
