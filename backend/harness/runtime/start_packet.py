from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeStartPacket:
    """Harness runtime contract consumed by loop controllers.

    The packet is the model-visible and policy-visible control contract for one
    execution stage. Loop code may record its dict form, but must not rebuild
    control facts from task metadata, projections, or loose context fields.
    """

    packet_id: str
    user_request: str
    request_facts: dict[str, Any]
    boundary_policy: dict[str, Any]
    context_candidates: dict[str, Any]
    model_turn_decision: dict[str, Any]
    action_permit: dict[str, Any]
    completion_criteria: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.start_packet"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.start_packet":
            raise ValueError("RuntimeStartPacket authority must be harness.runtime.start_packet")
        if not str(self.packet_id or "").strip():
            raise ValueError("RuntimeStartPacket requires packet_id")

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
    decision = dict(model_turn_decision or {})
    return RuntimeStartPacket(
        packet_id=f"runtime-start:{decision.get('decision_id') or 'runtime'}",
        user_request=str(user_request or ""),
        request_facts=dict(request_facts or {}),
        boundary_policy=dict(boundary_policy or {}),
        context_candidates=dict(context_candidates or {}),
        model_turn_decision=decision,
        action_permit=dict(action_permit or {}),
        completion_criteria=tuple(
            str(item).strip()
            for item in list(decision.get("completion_criteria") or [])
            if str(item).strip()
        ),
        diagnostics={
            "runtime_loop_must_not_reinterpret_intent": True,
            "control_owner": "harness.runtime",
        },
    )


