from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .control_events import RuntimeSignalScope


@dataclass(frozen=True, slots=True)
class RuntimePacketModelActionSurface:
    allowed_action_types: tuple[str, ...]
    source_authority: str = "harness.runtime.packet_assembler.model_action_surface"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_action_types"] = list(self.allowed_action_types)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class RuntimePacketContext:
    invocation_kind: str
    session_id: str
    turn_id: str = ""
    task_run_id: str = ""
    agent_invocation_id: str = ""
    user_message: str = ""
    history: tuple[dict[str, Any], ...] = ()
    session_context: dict[str, Any] = field(default_factory=dict)
    active_work_context: dict[str, Any] = field(default_factory=dict)
    current_work_boundary_receipt: dict[str, Any] = field(default_factory=dict)
    memory_context: dict[str, Any] = field(default_factory=dict)
    model_selection: dict[str, Any] = field(default_factory=dict)
    runtime_assembly: dict[str, Any] = field(default_factory=dict)
    profile_payload: dict[str, Any] = field(default_factory=dict)
    environment_payload: dict[str, Any] = field(default_factory=dict)
    control_capabilities: dict[str, Any] = field(default_factory=dict)
    effective_control_capabilities: dict[str, Any] = field(default_factory=dict)
    operation_availability: dict[str, Any] = field(default_factory=dict)
    file_evidence_scope: dict[str, Any] = field(default_factory=dict)
    file_state: tuple[dict[str, Any], ...] = ()
    projection_policy: dict[str, Any] = field(default_factory=dict)
    read_evidence_payload: dict[str, Any] = field(default_factory=dict)
    evidence_projection: dict[str, Any] = field(default_factory=dict)
    approval_projection: dict[str, Any] = field(default_factory=dict)
    control_signal_projection: dict[str, Any] = field(default_factory=dict)
    agent_scope: dict[str, Any] = field(default_factory=dict)
    agent_profile_ref: str = "main_interactive_agent"
    task_environment_ref: str = "env.general.workspace"
    permission_mode: str = "default"
    prompt_pack_refs: tuple[str, ...] = ()
    model_action_surface: RuntimePacketModelActionSurface = field(
        default_factory=lambda: RuntimePacketModelActionSurface(allowed_action_types=("respond", "ask_user", "block"))
    )
    tool_plan: Any = None
    model_visible_tools: tuple[dict[str, Any], ...] = ()
    packet_id: str = ""
    authority: str = "harness.runtime.packet_context"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.packet_context":
            raise ValueError("RuntimePacketContext authority must be harness.runtime.packet_context")
        if self.invocation_kind not in {"single_agent_turn", "task_execution", "recovery"}:
            raise ValueError(f"Unsupported RuntimePacketContext invocation kind: {self.invocation_kind}")
        if not self.session_id:
            raise ValueError("RuntimePacketContext requires session_id")
        if self.invocation_kind == "single_agent_turn" and not self.turn_id:
            raise ValueError("Single-turn RuntimePacketContext requires turn_id")
        if self.invocation_kind == "task_execution" and not self.task_run_id:
            raise ValueError("Task-execution RuntimePacketContext requires task_run_id")

    @property
    def allowed_action_types(self) -> tuple[str, ...]:
        return self.model_action_surface.allowed_action_types

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["history"] = [dict(item) for item in self.history]
        payload["prompt_pack_refs"] = list(self.prompt_pack_refs)
        payload["model_action_surface"] = self.model_action_surface.to_dict()
        payload["model_visible_tools"] = [dict(item) for item in self.model_visible_tools]
        payload["file_state"] = [dict(item) for item in self.file_state]
        payload["read_evidence_payload"] = _read_evidence_payload_diagnostics(self.read_evidence_payload)
        payload["agent_scope"] = dict(self.agent_scope or {})
        if hasattr(self.tool_plan, "to_dict"):
            payload["tool_plan"] = self.tool_plan.to_dict()
        elif isinstance(self.tool_plan, dict):
            payload["tool_plan"] = dict(self.tool_plan)
        else:
            payload["tool_plan"] = {}
        return payload


def runtime_packet_evidence_projection_ref(packet_context: RuntimePacketContext | dict[str, Any]) -> str:
    payload = packet_context.to_dict() if isinstance(packet_context, RuntimePacketContext) else dict(packet_context or {})
    identity = {
        "packet_id": str(payload.get("packet_id") or ""),
        "invocation_kind": str(payload.get("invocation_kind") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "turn_id": str(payload.get("turn_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "file_evidence_scope": dict(payload.get("file_evidence_scope") or {}),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return f"rtevidence:{digest}"


def runtime_packet_evidence_projection_event_payload(
    packet_context: RuntimePacketContext | dict[str, Any],
) -> dict[str, Any]:
    payload = packet_context.to_dict() if isinstance(packet_context, RuntimePacketContext) else dict(packet_context or {})
    read_evidence_payload = dict(payload.get("read_evidence_payload") or {})
    return {
        "authority": "harness.runtime.packet_context.evidence_projection_event",
        "packet_id": str(payload.get("packet_id") or ""),
        "invocation_kind": str(payload.get("invocation_kind") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "turn_id": str(payload.get("turn_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "agent_scope": dict(payload.get("agent_scope") or {}),
        "file_evidence_scope": dict(payload.get("file_evidence_scope") or {}),
        "evidence_projection": dict(payload.get("evidence_projection") or {}),
        "file_state_summary": _file_state_event_summary(payload.get("file_state")),
        "read_evidence_payload": _read_evidence_payload_diagnostics(read_evidence_payload),
    }


def runtime_packet_evidence_signal_scope(packet_context: RuntimePacketContext | dict[str, Any]) -> RuntimeSignalScope:
    payload = packet_context.to_dict() if isinstance(packet_context, RuntimePacketContext) else dict(packet_context or {})
    agent_scope = dict(payload.get("agent_scope") or {})
    return RuntimeSignalScope(
        session_id=str(agent_scope.get("session_id") or payload.get("session_id") or ""),
        agent_run_id=str(agent_scope.get("agent_run_id") or ""),
        run_cell_id=str(agent_scope.get("run_cell_id") or ""),
        turn_id=str(agent_scope.get("turn_id") or payload.get("turn_id") or ""),
        turn_run_id=str(agent_scope.get("turn_run_id") or ""),
        task_run_id=str(agent_scope.get("task_run_id") or payload.get("task_run_id") or ""),
    )


def _read_evidence_payload_diagnostics(payload: dict[str, Any] | None) -> dict[str, Any]:
    item = dict(payload or {})
    if not item:
        return {}
    diagnostics = {
        key: value
        for key, value in item.items()
        if key not in {"read_evidence_injections"}
    }
    if item.get("read_evidence_injections"):
        diagnostics["read_evidence_injection_count"] = len(
            [entry for entry in list(item.get("read_evidence_injections") or []) if isinstance(entry, dict)]
        )
        diagnostics["read_evidence_injections_redacted"] = True
    return diagnostics


def _file_state_event_summary(value: Any) -> dict[str, Any]:
    files = [dict(item) for item in list(value or []) if isinstance(item, dict)]
    summarized: list[dict[str, Any]] = []
    for item in files[:12]:
        read_ranges = [dict(entry) for entry in list(item.get("read_ranges") or []) if isinstance(entry, dict)]
        summarized.append(
            {
                "path": str(item.get("path") or ""),
                "status": str(item.get("status") or ""),
                "read_window_count": len(read_ranges),
                "current_read_window_count": len([entry for entry in read_ranges if entry.get("stale") is not True]),
                "stale_read_window_count": len([entry for entry in read_ranges if entry.get("stale") is True]),
                "evidence_refs": [
                    str(ref)
                    for ref in list(item.get("evidence_refs") or [])[:8]
                    if str(ref).strip()
                ],
            }
        )
    return {
        "file_count": len(files),
        "files": summarized,
        "truncated": len(files) > len(summarized),
    }
