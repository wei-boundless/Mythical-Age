from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProfessionalRunSession:
    session_id: str
    task_run_id: str
    interaction_mode: str = "professional_mode"
    state_ref: str = ""
    tool_observation_ledger_ref: str = ""
    resume_decision: dict[str, Any] = field(default_factory=dict)
    execution_obligation: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.professional_run_session"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_professional_run_session(
    *,
    session_id: str,
    task_run_id: str,
    interaction_mode: str,
    state_ref: str = "",
    tool_observation_ledger_ref: str = "",
    resume_decision: dict[str, Any] | None = None,
    execution_obligation: dict[str, Any] | None = None,
) -> ProfessionalRunSession:
    return ProfessionalRunSession(
        session_id=str(session_id or ""),
        task_run_id=str(task_run_id or ""),
        interaction_mode=str(interaction_mode or "professional_mode"),
        state_ref=str(state_ref or ""),
        tool_observation_ledger_ref=str(tool_observation_ledger_ref or ""),
        resume_decision=dict(resume_decision or {}),
        execution_obligation=dict(execution_obligation or {}),
    )
