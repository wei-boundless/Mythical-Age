from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
) -> OperationAuthorizationProjection:
    definitions = dict(definitions_by_name or {})
    known_operations = {
        str(getattr(definition, "operation_id", "") or "").strip()
        for definition in definitions.values()
        if str(getattr(definition, "operation_id", "") or "").strip()
    }
    agent_allowed = _operation_set(agent_allowed_operations)
    agent_blocked = _operation_set(agent_blocked_operations)
    task_requested = _operation_set(task_requested_operations)
    candidate_operations = sorted(known_operations | agent_allowed | agent_blocked | task_requested)
    decisions: list[OperationAuthorizationDecision] = []
    for operation_id in candidate_operations:
        if not operation_id:
            continue
        allowed_by_agent = operation_id in agent_allowed
        blocked_by_agent = operation_id in agent_blocked
        constraint_channel, environment_constraint = _environment_constraint(
            operation_id,
            environment_payload=environment_payload,
        )
        if not allowed_by_agent:
            final_decision = "deny"
            reason = "agent_permission_missing"
        elif blocked_by_agent:
            final_decision = "deny"
            reason = "agent_blocked_operation"
        else:
            final_decision = "allow"
            reason = "agent_allowed"
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


def _environment_constraint(
    operation_id: str,
    *,
    environment_payload: dict[str, Any],
) -> tuple[str, str]:
    execution_policy = dict(environment_payload.get("execution_policy") or {})
    sandbox_policy = dict(environment_payload.get("sandbox_policy") or {})
    channel = _operation_channel(operation_id)
    if channel == "shell":
        policy = str(execution_policy.get("shell_execution_policy") or sandbox_policy.get("shell_policy") or "denied")
        return channel, policy
    if channel == "browser":
        policy = str(execution_policy.get("browser_execution_policy") or sandbox_policy.get("browser_policy") or "denied")
        return channel, policy
    if channel == "network":
        policy = str(execution_policy.get("network_execution_policy") or sandbox_policy.get("network_policy") or "denied")
        return channel, policy
    if channel == "file_write":
        write_scope = str(execution_policy.get("write_scope_policy") or sandbox_policy.get("write_policy") or "none")
        return channel, write_scope
    return channel, "not_restricted"


def _operation_channel(operation_id: str) -> str:
    item = str(operation_id or "").strip()
    if item in {"op.shell", "op.python_repl"}:
        return "shell"
    if item == "op.browser_control":
        return "browser"
    if item in {"op.web_search", "op.fetch_url"}:
        return "network"
    if item in {"op.write_file", "op.edit_file"}:
        return "file_write"
    return "other"


def _operation_set(value: tuple[str, ...] | list[str]) -> set[str]:
    return {str(item).strip() for item in list(value or []) if str(item).strip()}
