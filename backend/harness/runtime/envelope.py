from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RuntimeEnvelopeScope = Literal["turn", "task_run", "step", "delegate", "recovery"]


@dataclass(frozen=True, slots=True)
class RuntimeEnvelope:
    envelope_id: str
    scope_kind: RuntimeEnvelopeScope
    session_id: str
    turn_id: str = ""
    task_run_id: str = ""
    step_id: str = ""
    agent_profile_ref: str = ""
    task_environment_ref: str = "single_agent"
    mode_policy: dict[str, Any] = field(default_factory=dict)
    tool_policy: dict[str, Any] = field(default_factory=dict)
    permission_policy: dict[str, Any] = field(default_factory=dict)
    sandbox_policy: dict[str, Any] = field(default_factory=dict)
    file_policy: dict[str, Any] = field(default_factory=dict)
    memory_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    prompt_policy: dict[str, Any] = field(default_factory=dict)
    output_policy: dict[str, Any] = field(default_factory=dict)
    budget_policy: dict[str, Any] = field(default_factory=dict)
    approval_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    graph_slot: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.envelope"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.envelope":
            raise ValueError("RuntimeEnvelope authority must be harness.runtime.envelope")
        if not self.envelope_id:
            raise ValueError("RuntimeEnvelope requires envelope_id")
        if self.scope_kind not in {"turn", "task_run", "step", "delegate", "recovery"}:
            raise ValueError(f"Unsupported RuntimeEnvelope scope_kind: {self.scope_kind}")
        if not self.session_id:
            raise ValueError("RuntimeEnvelope requires session_id")
        if self.scope_kind == "turn" and not self.turn_id:
            raise ValueError("Turn RuntimeEnvelope requires turn_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

