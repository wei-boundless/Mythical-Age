from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HarnessRuntimeEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.payload}


@dataclass(frozen=True, slots=True)
class HarnessRuntimeRequest:
    session_id: str
    message: str
    history: list[dict[str, Any]] | None = None
    explicit_subtasks: list[dict[str, Any]] = field(default_factory=list)
    runtime_profile: dict[str, Any] = field(default_factory=dict)
    environment_binding: dict[str, Any] = field(default_factory=dict)
    runtime_contract: dict[str, Any] = field(default_factory=dict)
    model_selection: dict[str, Any] = field(default_factory=dict)
    image_generation: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    permission_mode: str = ""
    expected_active_turn_id: str = ""
    active_turn_input_policy: str = "auto"
    expected_task_run_id: str = ""
    expected_continuation_id: str = ""
    recovery_input_policy: str = "auto"
    editor_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HarnessRuntimeResult:
    content: str
    segments: list[dict[str, Any]] = field(default_factory=list)



