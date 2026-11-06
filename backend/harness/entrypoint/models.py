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
    expected_continuation_id: str = ""
    recovery_input_policy: str = "auto"
    editor_context: dict[str, Any] = field(default_factory=dict)
    client_message_id: str = ""

    def runtime_profile_payload(self) -> dict[str, Any]:
        return _dict_payload(self.runtime_profile)

    def environment_binding_payload(self) -> dict[str, Any]:
        return _dict_payload(self.environment_binding)

    def runtime_contract_payload(self) -> dict[str, Any]:
        return _dict_payload(self.runtime_contract)

    def model_selection_payload(self) -> dict[str, Any]:
        return _dict_payload(self.model_selection)

    def image_generation_payload(self) -> dict[str, Any]:
        return _dict_payload(self.image_generation)

    def editor_context_payload(self) -> dict[str, Any]:
        return _dict_payload(self.editor_context)

    def stream_run_id(self) -> str:
        return str(self.runtime_profile_payload().get("stream_run_id") or "").strip()


@dataclass(slots=True)
class HarnessRuntimeResult:
    content: str
    segments: list[dict[str, Any]] = field(default_factory=list)


def _dict_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
