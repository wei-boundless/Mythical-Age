from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeInvocationPacket:
    packet_id: str
    envelope_ref: str
    invocation_kind: str
    invocation_index: int
    session_id: str
    turn_id: str = ""
    task_run_id: str = ""
    step_id: str = ""
    model_messages: list[Any] = field(default_factory=list)
    segment_plan: dict[str, Any] = field(default_factory=dict)
    prompt_composition_manifest: dict[str, Any] = field(default_factory=dict)
    action_schema_manifest: dict[str, Any] = field(default_factory=dict)
    artifact_scope_manifest: dict[str, Any] = field(default_factory=dict)
    tool_catalog_manifest: dict[str, Any] = field(default_factory=dict)
    task_contract_manifest: dict[str, Any] = field(default_factory=dict)
    prompt_pack_refs: tuple[str, ...] = ()
    available_tools: tuple[dict[str, Any], ...] = ()
    allowed_action_types: tuple[str, ...] = ()
    permission_snapshot: dict[str, Any] = field(default_factory=dict)
    context_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    current_task_contract_ref: str = ""
    current_step_ref: str = ""
    current_plan_ref: str = ""
    current_repair_refs: tuple[str, ...] = ()
    output_contract: dict[str, Any] = field(default_factory=dict)
    stop_conditions: dict[str, Any] = field(default_factory=dict)
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    user_visible_status_policy: dict[str, Any] = field(default_factory=dict)
    hidden_control_refs: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.invocation_packet"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.invocation_packet":
            raise ValueError("RuntimeInvocationPacket authority must be harness.runtime.invocation_packet")
        if not self.packet_id:
            raise ValueError("RuntimeInvocationPacket requires packet_id")
        if not self.envelope_ref:
            raise ValueError("RuntimeInvocationPacket requires envelope_ref")
        if not self.invocation_kind:
            raise ValueError("RuntimeInvocationPacket requires invocation_kind")
        if not self.session_id:
            raise ValueError("RuntimeInvocationPacket requires session_id")
        if not self.model_messages:
            raise ValueError("RuntimeInvocationPacket requires model_messages")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["segment_plan"] = dict(self.segment_plan)
        payload["prompt_composition_manifest"] = dict(self.prompt_composition_manifest)
        payload["action_schema_manifest"] = dict(self.action_schema_manifest)
        payload["artifact_scope_manifest"] = dict(self.artifact_scope_manifest)
        payload["tool_catalog_manifest"] = dict(self.tool_catalog_manifest)
        payload["task_contract_manifest"] = dict(self.task_contract_manifest)
        payload["prompt_pack_refs"] = list(self.prompt_pack_refs)
        payload["available_tools"] = [dict(item) for item in self.available_tools]
        payload["allowed_action_types"] = list(self.allowed_action_types)
        payload["context_refs"] = list(self.context_refs)
        payload["observation_refs"] = list(self.observation_refs)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["current_repair_refs"] = list(self.current_repair_refs)
        return payload
