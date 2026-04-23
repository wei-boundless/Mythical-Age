from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


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
        skill_allowed_tools: list[str] | None = None,
        binding_context: dict[str, Any] | None = None,
    ) -> ToolContractDecision:
        normalized_input = dict(tool_input or {})
        normalized_bindings = dict(binding_context or {})
        normalized_mode = (self.mode or "shadow").strip().lower() or "shadow"
        allowed_scope = [item.strip() for item in (skill_allowed_tools or []) if str(item).strip()]
        if allowed_scope and tool_name not in allowed_scope:
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
