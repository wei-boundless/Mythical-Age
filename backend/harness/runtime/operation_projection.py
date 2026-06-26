from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from permissions.policy import normalize_permission_mode


@dataclass(frozen=True, slots=True)
class OperationAuthorizationDecision:
    operation_id: str
    agent_allowed: bool
    agent_blocked: bool
    task_requested: bool
    final_decision: str
    reason: str
    authority: str = "harness.runtime.operation_authorization"

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "agent_allowed": self.agent_allowed,
            "agent_blocked": self.agent_blocked,
            "task_requested": self.task_requested,
            "final_decision": self.final_decision,
            "reason": self.reason,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class OperationAuthorizationProjection:
    decisions: tuple[OperationAuthorizationDecision, ...]
    allowed_operations: tuple[str, ...]
    denied_operations: tuple[str, ...]
    authority: str = "harness.runtime.operation_authorization_projection"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [item.to_dict() for item in self.decisions],
            "allowed_operations": list(self.allowed_operations),
            "denied_operations": list(self.denied_operations),
            "authority": self.authority,
        }


def project_operation_authorization(
    *,
    agent_allowed_operations: tuple[str, ...] | list[str],
    agent_blocked_operations: tuple[str, ...] | list[str] = (),
    task_requested_operations: tuple[str, ...] | list[str] = (),
    definitions_by_name: dict[str, Any] | None = None,
    permission_mode: str = "default",
    operation_ceiling: tuple[str, ...] | list[str] | None = None,
) -> OperationAuthorizationProjection:
    definitions = dict(definitions_by_name or {})
    mode = normalize_permission_mode(permission_mode)
    known_operations = {
        str(getattr(definition, "operation_id", "") or "").strip()
        for definition in definitions.values()
        if str(getattr(definition, "operation_id", "") or "").strip()
    }
    agent_allowed = _operation_set(agent_allowed_operations)
    agent_blocked = _operation_set(agent_blocked_operations)
    task_requested = _operation_set(task_requested_operations)
    full_access_mode = mode in {"full_access", "bypass"}
    candidate_operations = sorted(known_operations | agent_allowed | agent_blocked | task_requested)
    decisions: list[OperationAuthorizationDecision] = []
    for operation_id in candidate_operations:
        if not operation_id:
            continue
        allowed_by_agent = operation_id in agent_allowed
        blocked_by_agent = operation_id in agent_blocked
        if not allowed_by_agent:
            final_decision = "deny"
            reason = "agent_permission_missing"
        elif blocked_by_agent:
            final_decision = "deny"
            reason = "agent_blocked_operation"
        else:
            final_decision = "allow"
            reason = "permission_mode_full_access" if full_access_mode else "agent_allowed"
        decisions.append(
            OperationAuthorizationDecision(
                operation_id=operation_id,
                agent_allowed=allowed_by_agent,
                agent_blocked=blocked_by_agent,
                task_requested=operation_id in task_requested,
                final_decision=final_decision,
                reason=reason,
            )
        )
    allowed = tuple(item.operation_id for item in decisions if item.final_decision == "allow")
    denied = tuple(item.operation_id for item in decisions if item.final_decision != "allow")
    return OperationAuthorizationProjection(
        decisions=tuple(decisions),
        allowed_operations=allowed,
        denied_operations=denied,
    )


def _operation_set(value: tuple[str, ...] | list[str]) -> set[str]:
    return {str(item).strip() for item in list(value or []) if str(item).strip()}
