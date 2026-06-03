from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from permissions.policy import normalize_permission_mode

from .tool_scheduling import evaluate_environment_operation


@dataclass(frozen=True, slots=True)
class OperationAuthorizationDecision:
    operation_id: str
    agent_allowed: bool
    agent_blocked: bool
    task_requested: bool
    final_decision: str
    reason: str
    constraint_channel: str = ""
    environment_constraint: str = ""
    authority: str = "harness.runtime.operation_authorization"

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "agent_allowed": self.agent_allowed,
            "agent_blocked": self.agent_blocked,
            "task_requested": self.task_requested,
            "final_decision": self.final_decision,
            "reason": self.reason,
            "constraint_channel": self.constraint_channel,
            "environment_constraint": self.environment_constraint,
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
    environment_payload: dict[str, Any],
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
    ceiling = _operation_set(operation_ceiling or ()) if operation_ceiling is not None else set()
    full_access_mode = mode in {"full_access", "bypass"}
    full_access_candidates = known_operations | agent_allowed | task_requested
    if operation_ceiling is not None:
        full_access_candidates = {operation for operation in full_access_candidates if operation in ceiling}
    candidate_operations = sorted(known_operations | agent_allowed | agent_blocked | task_requested)
    decisions: list[OperationAuthorizationDecision] = []
    for operation_id in candidate_operations:
        if not operation_id:
            continue
        allowed_by_full_access = full_access_mode and operation_id in full_access_candidates
        allowed_by_agent = operation_id in agent_allowed or allowed_by_full_access
        blocked_by_agent = operation_id in agent_blocked and not allowed_by_full_access
        environment_decision = evaluate_environment_operation(
            operation_id,
            environment_payload=environment_payload,
            task_requested_operations=task_requested,
        )
        constraint_channel = environment_decision.constraint_channel
        environment_constraint = environment_decision.environment_constraint
        if not allowed_by_agent:
            final_decision = "deny"
            reason = "agent_permission_missing"
        elif blocked_by_agent:
            final_decision = "deny"
            reason = "agent_blocked_operation"
        elif not environment_decision.allowed:
            final_decision = "deny"
            reason = environment_decision.reason
        else:
            final_decision = "allow"
            if allowed_by_full_access and operation_id in agent_blocked:
                reason = "permission_mode_full_access_overrides_profile_block"
            elif allowed_by_full_access and operation_id not in agent_allowed:
                reason = "permission_mode_full_access_expanded_capability"
            else:
                reason = "permission_mode_full_access" if full_access_mode else (environment_decision.reason if environment_decision.reason else "agent_allowed")
        decisions.append(
            OperationAuthorizationDecision(
                operation_id=operation_id,
                agent_allowed=allowed_by_agent,
                agent_blocked=blocked_by_agent,
                task_requested=operation_id in task_requested,
                final_decision=final_decision,
                reason=reason,
                constraint_channel=constraint_channel,
                environment_constraint=environment_constraint,
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
