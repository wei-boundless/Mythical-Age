from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


VALID_PROFESSIONAL_STATES = {
    "initialized",
    "mode_policy_bound",
    "obligation_bound",
    "prototype_bound",
    "plan_drafted",
    "action_dispatched",
    "tool_observed",
    "artifact_written",
    "verification_observed",
    "deliverable_validating",
    "repairing",
    "blocked",
    "paused",
    "complete",
}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "initialized": {"mode_policy_bound", "obligation_bound", "blocked", "paused"},
    "mode_policy_bound": {"obligation_bound", "prototype_bound", "plan_drafted", "blocked", "paused"},
    "obligation_bound": {"prototype_bound", "plan_drafted", "action_dispatched", "blocked", "paused"},
    "prototype_bound": {"plan_drafted", "action_dispatched", "blocked", "paused"},
    "plan_drafted": {"action_dispatched", "tool_observed", "deliverable_validating", "blocked", "paused"},
    "action_dispatched": {
        "tool_observed",
        "artifact_written",
        "verification_observed",
        "deliverable_validating",
        "blocked",
        "paused",
    },
    "tool_observed": {
        "tool_observed",
        "action_dispatched",
        "artifact_written",
        "verification_observed",
        "deliverable_validating",
        "repairing",
        "blocked",
        "paused",
    },
    "artifact_written": {
        "action_dispatched",
        "tool_observed",
        "artifact_written",
        "verification_observed",
        "deliverable_validating",
        "repairing",
        "blocked",
        "paused",
    },
    "verification_observed": {
        "action_dispatched",
        "tool_observed",
        "artifact_written",
        "verification_observed",
        "deliverable_validating",
        "repairing",
        "blocked",
        "paused",
    },
    "deliverable_validating": {
        "action_dispatched",
        "tool_observed",
        "artifact_written",
        "verification_observed",
        "complete",
        "repairing",
        "blocked",
        "paused",
    },
    "repairing": {"action_dispatched", "tool_observed", "artifact_written", "verification_observed", "deliverable_validating", "blocked", "paused"},
    "blocked": {"repairing", "action_dispatched", "paused"},
    "paused": {"action_dispatched", "repairing", "blocked"},
    "complete": set(),
}


@dataclass(frozen=True, slots=True)
class ProfessionalStateTransition:
    from_state: str
    to_state: str
    reason: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True, slots=True)
class ProfessionalRunState:
    run_state_id: str
    task_run_id: str
    state: str = "initialized"
    transitions: tuple[ProfessionalStateTransition, ...] = ()
    unsatisfied_obligations: tuple[str, ...] = ()
    blocked_reason: str = ""
    authority: str = "orchestration.professional_run_state"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def advance(
        self,
        to_state: str,
        *,
        reason: str,
        evidence_refs: tuple[str, ...] = (),
        unsatisfied_obligations: tuple[str, ...] | None = None,
        blocked_reason: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> "ProfessionalRunState":
        target = str(to_state or "").strip()
        if target not in VALID_PROFESSIONAL_STATES:
            raise ValueError(f"unsupported professional run state: {target}")
        if target not in _ALLOWED_TRANSITIONS.get(self.state, set()):
            raise ValueError(f"invalid professional run transition: {self.state} -> {target}")
        next_unsatisfied = tuple(
            self.unsatisfied_obligations if unsatisfied_obligations is None else unsatisfied_obligations
        )
        if target == "complete" and next_unsatisfied:
            raise ValueError("professional run cannot complete with unsatisfied obligations")
        transition = ProfessionalStateTransition(
            from_state=self.state,
            to_state=target,
            reason=str(reason or "").strip(),
            evidence_refs=tuple(str(item) for item in evidence_refs if str(item).strip()),
        )
        return ProfessionalRunState(
            run_state_id=self.run_state_id,
            task_run_id=self.task_run_id,
            state=target,
            transitions=(*self.transitions, transition),
            unsatisfied_obligations=next_unsatisfied,
            blocked_reason=str(blocked_reason or ""),
            diagnostics={**dict(self.diagnostics or {}), **dict(diagnostics or {})},
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["transitions"] = [transition.to_dict() for transition in self.transitions]
        payload["unsatisfied_obligations"] = list(self.unsatisfied_obligations)
        return payload


def initial_professional_run_state(task_run_id: str) -> ProfessionalRunState:
    return ProfessionalRunState(
        run_state_id=f"professional-run-state:{task_run_id}",
        task_run_id=str(task_run_id or "").strip(),
    )


def unsatisfied_obligations_from_verification(verification: dict[str, Any]) -> tuple[str, ...]:
    missing = [
        str(item).strip()
        for item in list(dict(verification or {}).get("missing_required_actions") or [])
        if str(item).strip()
    ]
    missing.extend(
        str(item).strip()
        for item in list(dict(verification or {}).get("missing_output_paths") or [])
        if str(item).strip()
    )
    missing.extend(
        str(item).strip()
        for item in list(dict(verification or {}).get("missing_response_terms") or [])
        if str(item).strip()
    )
    deliverable_validation = dict(dict(verification or {}).get("deliverable_validation") or {})
    missing.extend(
        str(item).strip()
        for item in list(deliverable_validation.get("missing_deliverables") or [])
        if str(item).strip()
    )
    missing.extend(
        str(item).strip()
        for item in list(deliverable_validation.get("unsupported_claims") or [])
        if str(item).strip()
    )
    if dict(verification or {}).get("protocol_leak_detected") is True or deliverable_validation.get("protocol_leak_detected") is True:
        missing.append("protocol_boundary")
    return tuple(dict.fromkeys(missing))
