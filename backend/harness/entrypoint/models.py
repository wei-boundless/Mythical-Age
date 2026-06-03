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
    search_policy: list[str] | None = None
    runtime_profile: dict[str, Any] = field(default_factory=dict)
    task_selection: dict[str, Any] = field(default_factory=dict)
    model_selection: dict[str, Any] = field(default_factory=dict)
    image_generation: dict[str, Any] = field(default_factory=dict)
    permission_mode: str = "default"
    expected_active_turn_id: str = ""
    active_turn_input_policy: str = "auto"


@dataclass(slots=True)
class HarnessRuntimeResult:
    content: str
    segments: list[dict[str, Any]] = field(default_factory=list)



