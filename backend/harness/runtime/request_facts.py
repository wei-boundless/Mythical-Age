from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TurnInputFacts:
    """Observable request facts for a model turn.

    This object records candidates and constraints only. It does not classify
    intent, choose tools, grant permissions, or decide whether active work
    should be controlled.
    """

    session_id: str
    turn_id: str
    user_message: str
    expected_active_turn_id: str = ""
    active_turn: dict[str, Any] = field(default_factory=dict)
    active_work_candidate: dict[str, Any] = field(default_factory=dict)
    recent_work_outcome_candidate: dict[str, Any] = field(default_factory=dict)
    task_selection: dict[str, Any] = field(default_factory=dict)
    runtime_profile: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.turn_input_facts"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.turn_input_facts":
            raise ValueError("TurnInputFacts authority must be harness.runtime.turn_input_facts")
        if not str(self.session_id or "").strip():
            raise ValueError("TurnInputFacts requires session_id")
        if not str(self.turn_id or "").strip():
            raise ValueError("TurnInputFacts requires turn_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def has_active_work_candidate(self) -> bool:
        return bool(self.active_work_candidate)


def build_turn_input_facts(
    *,
    session_id: str,
    turn_id: str,
    user_message: str,
    expected_active_turn_id: str = "",
    active_turn: Any | None = None,
    active_work_candidate: Any | None = None,
    recent_work_outcome_candidate: dict[str, Any] | None = None,
    task_selection: dict[str, Any] | None = None,
    runtime_profile: dict[str, Any] | None = None,
) -> TurnInputFacts:
    return TurnInputFacts(
        session_id=str(session_id or "").strip(),
        turn_id=str(turn_id or "").strip(),
        user_message=str(user_message or ""),
        expected_active_turn_id=str(expected_active_turn_id or "").strip(),
        active_turn=_payload_from_object(active_turn),
        active_work_candidate=_payload_from_object(active_work_candidate),
        recent_work_outcome_candidate=dict(recent_work_outcome_candidate or {}),
        task_selection=dict(task_selection or {}),
        runtime_profile=dict(runtime_profile or {}),
    )


def _payload_from_object(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}
