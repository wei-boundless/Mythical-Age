from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeStartPacket:
    packet_id: str
    user_request: str
    request_facts: dict[str, Any]
    boundary_policy: dict[str, Any]
    context_candidates: dict[str, Any]
    model_turn_decision: dict[str, Any]
    action_permit: dict[str, Any]
    completion_criteria: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.runtime_start_packet"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["request_facts"] = dict(self.request_facts or {})
        payload["boundary_policy"] = dict(self.boundary_policy or {})
        payload["context_candidates"] = dict(self.context_candidates or {})
        payload["model_turn_decision"] = dict(self.model_turn_decision or {})
        payload["action_permit"] = dict(self.action_permit or {})
        payload["completion_criteria"] = list(self.completion_criteria)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_runtime_start_packet(
    *,
    user_request: str,
    request_facts: dict[str, Any],
    boundary_policy: dict[str, Any],
    context_candidates: dict[str, Any],
    model_turn_decision: dict[str, Any],
    action_permit: dict[str, Any],
) -> RuntimeStartPacket:
    return RuntimeStartPacket(
        packet_id=f"runtime-start:{dict(model_turn_decision or {}).get('decision_id') or 'runtime'}",
        user_request=str(user_request or ""),
        request_facts=dict(request_facts or {}),
        boundary_policy=dict(boundary_policy or {}),
        context_candidates=dict(context_candidates or {}),
        model_turn_decision=dict(model_turn_decision or {}),
        action_permit=dict(action_permit or {}),
        completion_criteria=tuple(str(item).strip() for item in list(dict(model_turn_decision or {}).get("completion_criteria") or []) if str(item).strip()),
        diagnostics={"runtime_loop_must_not_reinterpret_intent": True},
    )
