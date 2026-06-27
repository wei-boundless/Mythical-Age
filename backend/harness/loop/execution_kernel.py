from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.shared.tool_identity import canonical_action_tool_call_id, permission_decision_id
from runtime.shared.file_observation_policy import read_window_fingerprint_defaults
from runtime.tool_runtime.tool_invocation_control import build_tool_invocation_id

from .action_permit import ActionPermit, action_permit_from_admission
from .admission import AdmissionDecision, admit_model_action
from .model_action_protocol import AnyModelActionRequest

@dataclass(frozen=True, slots=True)
class ActionLifecycleDecision:
    lifecycle_id: str
    action_request_ref: str
    action_type: str
    invocation_kind: str
    permit_invocation_kind: str
    admission: AdmissionDecision
    action_permit: ActionPermit
    packet_ref: str = ""
    session_id: str = ""
    turn_id: str = ""
    task_run_id: str = ""
    allowed_action_types: tuple[str, ...] = ()
    allowed_tool_names: tuple[str, ...] = ()
    authority: str = "harness.loop.execution_kernel"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.execution_kernel":
            raise ValueError("ActionLifecycleDecision authority must be harness.loop.execution_kernel")
        if not self.lifecycle_id:
            raise ValueError("ActionLifecycleDecision requires lifecycle_id")
        if not self.action_request_ref:
            raise ValueError("ActionLifecycleDecision requires action_request_ref")

    @property
    def allowed(self) -> bool:
        return self.admission.decision == "allow" and self.action_permit.allowed

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["admission"] = self.admission.to_dict()
        payload["action_permit"] = self.action_permit.to_dict()
        payload["allowed_action_types"] = list(self.allowed_action_types)
        payload["allowed_tool_names"] = list(self.allowed_tool_names)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class ActionLifecycleEventRecord:
    event_type: str
    run_id: str
    payload: dict[str, Any]
    refs: dict[str, Any]
    authority: str = "harness.loop.execution_kernel"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.execution_kernel":
            raise ValueError("ActionLifecycleEventRecord authority must be harness.loop.execution_kernel")
        if self.event_type != "model_action_admission_checked":
            raise ValueError("ActionLifecycleEventRecord only records model_action_admission_checked")
        if not self.run_id:
            raise ValueError("ActionLifecycleEventRecord requires run_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "payload": dict(self.payload or {}),
            "refs": dict(self.refs or {}),
            "authority": self.authority,
        }


def append_action_lifecycle_event(runtime_host: Any, event_record: ActionLifecycleEventRecord) -> Any:
    event_log = getattr(runtime_host, "event_log", None)
    append = getattr(event_log, "append", None)
    if not callable(append):
        raise RuntimeError("append_action_lifecycle_event requires runtime_host.event_log.append")
    return append(
        event_record.run_id,
        event_record.event_type,
        payload=event_record.payload,
        refs=event_record.refs,
    )


@dataclass(frozen=True, slots=True)
class ToolLifecycleStartedEventRecord:
    event_type: str
    run_id: str
    payload: dict[str, Any]
    refs: dict[str, Any]
    authority: str = "harness.loop.execution_kernel"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.execution_kernel":
            raise ValueError("ToolLifecycleStartedEventRecord authority must be harness.loop.execution_kernel")
        if self.event_type != "tool_item_started":
            raise ValueError("ToolLifecycleStartedEventRecord only records tool_item_started")
        if not self.run_id:
            raise ValueError("ToolLifecycleStartedEventRecord requires run_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "payload": dict(self.payload or {}),
            "refs": dict(self.refs or {}),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class ActionAdmissionRecoveryPayload:
    status: str
    tool_name: str
    tool_args: dict[str, Any]
    error_code: str
    summary: str
    repair_instruction: str
    payload: dict[str, Any]
    source: str
    observation_type: str
    admission_denial_fingerprint: str
    model_visible_recovery_observation: bool = True
    authority: str = "harness.loop.execution_kernel"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.execution_kernel":
            raise ValueError("ActionAdmissionRecoveryPayload authority must be harness.loop.execution_kernel")
        if not self.error_code:
            raise ValueError("ActionAdmissionRecoveryPayload requires error_code")
        if not self.admission_denial_fingerprint:
            raise ValueError("ActionAdmissionRecoveryPayload requires admission_denial_fingerprint")

    @property
    def content_chars(self) -> int:
        return len(self.summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "tool_name": self.tool_name,
            "tool_args": dict(self.tool_args or {}),
            "error_code": self.error_code,
            "summary": self.summary,
            "repair_instruction": self.repair_instruction,
            "payload": dict(self.payload or {}),
            "source": self.source,
            "observation_type": self.observation_type,
            "admission_denial_fingerprint": self.admission_denial_fingerprint,
            "model_visible_recovery_observation": self.model_visible_recovery_observation,
            "content_chars": self.content_chars,
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class ActionToolInvocationIdentity:
    invocation_id: str
    caller_ref: str
    action_request_ref: str
    action_lifecycle_ref: str
    admission_ref: str
    tool_name: str
    tool_call_id: str
    tool_args: dict[str, Any]
    operation_id: str
    action_permit: dict[str, Any]
    agent_run_id: str = ""
    run_cell_id: str = ""
    authority: str = "harness.loop.execution_kernel"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.execution_kernel":
            raise ValueError("ActionToolInvocationIdentity authority must be harness.loop.execution_kernel")
        if not self.invocation_id:
            raise ValueError("ActionToolInvocationIdentity requires invocation_id")
        if not self.caller_ref:
            raise ValueError("ActionToolInvocationIdentity requires caller_ref")
        if not self.action_request_ref:
            raise ValueError("ActionToolInvocationIdentity requires action_request_ref")
        if not self.tool_name:
            raise ValueError("ActionToolInvocationIdentity requires tool_name")
        if not self.tool_call_id:
            raise ValueError("ActionToolInvocationIdentity requires tool_call_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "caller_ref": self.caller_ref,
            "action_request_ref": self.action_request_ref,
            "action_lifecycle_ref": self.action_lifecycle_ref,
            "admission_ref": self.admission_ref,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "tool_args": dict(self.tool_args or {}),
            "operation_id": self.operation_id,
            "action_permit": dict(self.action_permit or {}),
            "agent_run_id": self.agent_run_id,
            "run_cell_id": self.run_cell_id,
            "authority": self.authority,
        }


def decide_model_action_lifecycle(
    action_request: AnyModelActionRequest,
    *,
    invocation_kind: str,
    permit_invocation_kind: str = "",
    packet_ref: str = "",
    packet_allowed_action_types: tuple[str, ...] = (),
    definitions_by_name: dict[str, Any] | None = None,
    allowed_tool_names: set[str] | tuple[str, ...] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    permission_mode: str = "default",
    side_effect_policy: str = "",
    current_work_boundary_receipt: dict[str, Any] | None = None,
    session_id: str = "",
    turn_id: str = "",
    task_run_id: str = "",
    grant_scope: str = "",
    strict_review: bool | None = None,
    resource_scope: dict[str, Any] | None = None,
) -> ActionLifecycleDecision:
    admission = admit_model_action(
        action_request,
        packet_allowed_action_types=packet_allowed_action_types,
        invocation_kind=invocation_kind,
        definitions_by_name=definitions_by_name,
        allowed_tool_names=set(allowed_tool_names) if allowed_tool_names is not None else None,
        runtime_profile=runtime_profile,
        permission_mode=permission_mode,
        side_effect_policy=side_effect_policy,
        current_work_boundary_receipt=current_work_boundary_receipt,
    )
    return build_action_lifecycle_from_admission(
        action_request,
        admission,
        invocation_kind=invocation_kind,
        permit_invocation_kind=permit_invocation_kind or invocation_kind,
        packet_ref=packet_ref,
        packet_allowed_action_types=packet_allowed_action_types,
        allowed_tool_names=allowed_tool_names,
        permission_mode=permission_mode,
        side_effect_policy=side_effect_policy,
        session_id=session_id,
        turn_id=turn_id,
        task_run_id=task_run_id,
        grant_scope=grant_scope,
        strict_review=strict_review,
        resource_scope=resource_scope,
    )


def build_action_admission_recovery_payload(
    action_request: AnyModelActionRequest,
    admission: AdmissionDecision | dict[str, Any],
    *,
    runtime_fingerprint: dict[str, Any] | None = None,
    repeat_count: int = 1,
    previous_observation_refs: tuple[str, ...] | list[str] = (),
    pause_after_observation: bool = False,
) -> ActionAdmissionRecoveryPayload:
    admission_payload = _admission_payload(admission)
    decision = str(admission_payload.get("decision") or "deny")
    system_reason = str(admission_payload.get("system_reason") or decision)
    user_reason = str(admission_payload.get("user_visible_reason") or system_reason)
    action_issue = dict(admission_payload.get("action_issue") or {})
    tool_call = dict(getattr(action_request, "tool_call", {}) or {})
    action_type = str(getattr(action_request, "action_type", "") or "")
    requested_tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    requested_tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
    action_request_ref = str(getattr(action_request, "request_id", "") or "")
    action_lifecycle_ref = f"action-lifecycle:{action_request_ref}" if action_request_ref else ""
    fingerprint = action_admission_denial_fingerprint(
        action_request,
        admission_payload=admission_payload,
        runtime_fingerprint=dict(runtime_fingerprint or {}),
    )
    normalized_repeat_count = max(1, int(repeat_count or 1))
    previous_refs = tuple(str(ref) for ref in list(previous_observation_refs or ()) if str(ref or "").strip())
    if normalized_repeat_count > 1:
        message = (
            f"模型第 {normalized_repeat_count} 次请求同一个未获准动作，运行时仍未执行："
            f"准入裁决 {decision}，原因 {system_reason}。"
        )
        repair_instruction = (
            f"{message} 边界说明：{user_reason}。你必须停止原样重试，改用本轮可见且获准的工具、修改参数、"
            "询问用户、给出阻塞裁决，或在已有证据满足合同时直接收口。"
        )
        payload = {
            "tool_name": "repeated_admission_guard",
            "tool_args": {
                "rejected_action_type": action_type,
                "rejected_tool_name": requested_tool_name,
                "rejected_tool_args": _normalize_tool_call_args_for_fingerprint(requested_tool_name, requested_tool_args),
            },
            "error": message,
            "error_code": "repeated_admission_denial",
            "admission": admission_payload,
            "action_request_ref": action_request_ref,
            "action_lifecycle_ref": action_lifecycle_ref,
            "repair_instruction": repair_instruction,
            "rejected_action_request": action_request.to_dict(),
            "admission_denial_fingerprint": fingerprint,
            "admission_denial_repeat_count": normalized_repeat_count,
            "previous_observation_refs": list(previous_refs),
            "pause_after_observation": bool(pause_after_observation),
            "structured_error": {
                "code": "repeated_admission_denial",
                "message": repair_instruction,
                "retryable": True,
                "origin": "runtime_guard",
                "tool_name": requested_tool_name,
                "tool_args": requested_tool_args,
                "previous_observation_refs": list(previous_refs),
                "repair_instruction": repair_instruction,
            },
            "runtime_fingerprint": dict(runtime_fingerprint or {}),
        }
        return ActionAdmissionRecoveryPayload(
            status="error",
            tool_name="repeated_admission_guard",
            tool_args=dict(payload["tool_args"]),
            error_code="repeated_admission_denial",
            summary=repair_instruction,
            repair_instruction=repair_instruction,
            payload=payload,
            source="system:repeated_admission_guard",
            observation_type="runtime_guard",
            admission_denial_fingerprint=fingerprint,
            model_visible_recovery_observation=True,
        )

    status = _action_admission_recovery_status(admission_payload)
    issue_category = str(action_issue.get("category") or admission_payload.get("issue_category") or "runtime_boundary")
    if status == "needs_approval":
        repair_instruction = (
            f"运行边界没有执行当前动作，因为它需要可恢复的审批或人工确认。问题分类：{issue_category}；"
            f"准入裁决：{decision}；原因：{system_reason}。边界说明：{user_reason}。"
            "你需要把这条观察反馈给用户或改用本轮已开放动作：可以请求进入可恢复任务、询问用户、"
            "说明当前无法继续，或在已有事实足够时收口；不要重复同一个未获准动作。"
        )
        model_visible = True
    else:
        repair_instruction = (
            f"运行边界没有执行当前动作。准入裁决：{decision}；原因：{system_reason}。"
            f"边界说明：{user_reason}。你需要基于这条观察继续推进：改用已开放工具、补齐任务合同、询问用户，"
            "或在无法继续时给出有证据的阻塞裁决；不要重复同一个未获准动作。"
        )
        model_visible = True
    payload = {
        "tool_name": requested_tool_name or action_type,
        "tool_args": requested_tool_args,
        "error": system_reason,
        "error_code": system_reason,
        "admission": admission_payload,
        "admission_decision": decision,
        "action_request_ref": action_request_ref,
        "action_lifecycle_ref": action_lifecycle_ref,
        "action_issue": action_issue,
        "repair_instruction": repair_instruction,
        "rejected_action_request": action_request.to_dict(),
        "admission_denial_fingerprint": fingerprint,
        "admission_denial_repeat_count": 1,
        "structured_error": {
            "code": system_reason,
            "message": repair_instruction,
            "retryable": True,
            "origin": "model_action_admission",
            "repair_instruction": repair_instruction,
        },
        "runtime_fingerprint": dict(runtime_fingerprint or {}),
    }
    return ActionAdmissionRecoveryPayload(
        status=status,
        tool_name=str(payload["tool_name"]),
        tool_args=dict(requested_tool_args or {}),
        error_code=system_reason,
        summary=repair_instruction,
        repair_instruction=repair_instruction,
        payload=payload,
        source="system:model_action_admission",
        observation_type="executor_error",
        admission_denial_fingerprint=fingerprint,
        model_visible_recovery_observation=model_visible,
    )


def build_action_tool_invocation_identity(
    action_request: AnyModelActionRequest,
    *,
    caller_ref: str,
    definitions_by_name: dict[str, Any] | None = None,
    admission: AdmissionDecision | dict[str, Any] | None = None,
    action_permit: ActionPermit | dict[str, Any] | None = None,
    action_lifecycle_ref: str = "",
    tool_args_override: dict[str, Any] | None = None,
    agent_run_id: str = "",
    run_cell_id: str = "",
) -> ActionToolInvocationIdentity:
    action_request_ref = str(getattr(action_request, "request_id", "") or "").strip()
    tool_call = dict(getattr(action_request, "tool_call", {}) or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
    tool_call_id = canonical_action_tool_call_id(action_request)
    if not action_request_ref:
        raise ValueError("build_action_tool_invocation_identity requires action_request.request_id")
    if not tool_name:
        raise ValueError("build_action_tool_invocation_identity requires tool_name")
    if not tool_call_id:
        raise ValueError("build_action_tool_invocation_identity requires canonical tool_call_id")
    tool_args = dict(tool_args_override if tool_args_override is not None else (tool_call.get("args") or tool_call.get("tool_args") or {}))
    definition = dict(definitions_by_name or {}).get(tool_name)
    operation_id = str(getattr(definition, "operation_id", "") or tool_name)
    normalized_caller_ref = str(caller_ref or "").strip()
    invocation_id = build_tool_invocation_id(
        caller_ref=normalized_caller_ref,
        action_request_ref=action_request_ref,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        agent_run_id=str(agent_run_id or ""),
        run_cell_id=str(run_cell_id or ""),
    )
    permit_payload = action_permit.to_dict() if hasattr(action_permit, "to_dict") else dict(action_permit or {})
    lifecycle_ref = str(action_lifecycle_ref or permit_payload.get("action_lifecycle_ref") or f"action-lifecycle:{action_request_ref}").strip()
    return ActionToolInvocationIdentity(
        invocation_id=invocation_id,
        caller_ref=normalized_caller_ref,
        action_request_ref=action_request_ref,
        action_lifecycle_ref=lifecycle_ref,
        admission_ref=permission_decision_id(admission, tool_call_id=tool_call_id),
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args,
        operation_id=operation_id,
        action_permit=permit_payload,
        agent_run_id=str(agent_run_id or ""),
        run_cell_id=str(run_cell_id or ""),
    )


def _action_admission_recovery_status(admission: AdmissionDecision | dict[str, Any]) -> str:
    payload = _admission_payload(admission)
    decision = str(payload.get("decision") or "").strip()
    if decision == "deny":
        return "denied"
    if decision == "ask_approval":
        return "needs_approval"
    if decision in {"needs_contract", "needs_task_run"}:
        return "needs_contract"
    return "error"


def action_admission_denial_fingerprint(
    action_request: AnyModelActionRequest,
    *,
    admission_payload: dict[str, Any] | None = None,
    runtime_fingerprint: dict[str, Any] | None = None,
) -> str:
    payload = {
        "action": _model_action_admission_identity(action_request),
        "admission": {
            "decision": str(dict(admission_payload or {}).get("decision") or ""),
            "system_reason": str(dict(admission_payload or {}).get("system_reason") or ""),
        },
        "runtime": _admission_runtime_fingerprint_identity(dict(runtime_fingerprint or {})),
    }
    return "sha256:" + _stable_hash(payload)


def build_action_lifecycle_event_record(
    lifecycle: ActionLifecycleDecision,
    action_request: AnyModelActionRequest,
    *,
    run_id: str,
    packet_ref: str = "",
    session_id: str = "",
    turn_id: str = "",
    turn_run_id: str = "",
    task_run_id: str = "",
    batch_action_request_ref: str = "",
    extra_payload: dict[str, Any] | None = None,
    extra_refs: dict[str, Any] | None = None,
) -> ActionLifecycleEventRecord:
    normalized_run_id = str(run_id or "").strip()
    normalized_packet_ref = str(packet_ref or lifecycle.packet_ref or "").strip()
    normalized_session_id = str(session_id or lifecycle.session_id or "").strip()
    normalized_turn_id = str(turn_id or lifecycle.turn_id or getattr(action_request, "turn_id", "") or "").strip()
    normalized_task_run_id = str(task_run_id or lifecycle.task_run_id or "").strip()
    payload: dict[str, Any] = {
        "model_action_request": action_request.to_dict(),
        "admission": lifecycle.admission.to_dict(),
        "action_lifecycle": lifecycle.to_dict(),
        "action_lifecycle_event": {
            "authority": "harness.loop.execution_kernel",
            "event_type": "model_action_admission_checked",
        },
    }
    if normalized_session_id:
        payload["session_id"] = normalized_session_id
    if normalized_turn_id:
        payload["turn_id"] = normalized_turn_id
    if normalized_task_run_id:
        payload["task_run_id"] = normalized_task_run_id
    if batch_action_request_ref:
        payload["batch_action_request_ref"] = str(batch_action_request_ref)
    payload.update(dict(extra_payload or {}))

    refs: dict[str, Any] = {
        "action_request_ref": lifecycle.action_request_ref,
        "action_lifecycle_ref": lifecycle.lifecycle_id,
    }
    if normalized_session_id:
        refs["session_ref"] = normalized_session_id
    if normalized_turn_id:
        refs["turn_ref"] = normalized_turn_id
    if turn_run_id:
        refs["turn_run_ref"] = str(turn_run_id)
    if normalized_task_run_id:
        refs["task_run_ref"] = normalized_task_run_id
    if normalized_packet_ref:
        refs["runtime_invocation_packet_ref"] = normalized_packet_ref
    if batch_action_request_ref:
        refs["batch_action_request_ref"] = str(batch_action_request_ref)
    refs.update(dict(extra_refs or {}))

    return ActionLifecycleEventRecord(
        event_type="model_action_admission_checked",
        run_id=normalized_run_id,
        payload=payload,
        refs=refs,
    )


def build_tool_lifecycle_started_event_record(
    identity: ActionToolInvocationIdentity,
    *,
    run_id: str,
    caller_kind: str,
    session_id: str = "",
    turn_id: str = "",
    turn_run_id: str = "",
    task_run_id: str = "",
    packet_ref: str = "",
    target: str = "",
    arguments_preview: Any = None,
    state: str = "running",
    extra_payload: dict[str, Any] | None = None,
    extra_refs: dict[str, Any] | None = None,
) -> ToolLifecycleStartedEventRecord:
    normalized_run_id = str(run_id or identity.caller_ref or "").strip()
    normalized_caller_kind = str(caller_kind or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_turn_run_id = str(turn_run_id or "").strip()
    normalized_task_run_id = str(task_run_id or "").strip()
    normalized_packet_ref = str(packet_ref or "").strip()
    normalized_state = str(state or "running").strip() or "running"
    if isinstance(arguments_preview, dict):
        preview_payload: Any = dict(arguments_preview)
    elif isinstance(arguments_preview, tuple):
        preview_payload = list(arguments_preview)
    elif arguments_preview is None:
        preview_payload = ""
    else:
        preview_payload = arguments_preview
    payload: dict[str, Any] = {
        "tool_lifecycle_id": identity.invocation_id,
        "tool_invocation_id": identity.invocation_id,
        "tool_call_id": identity.tool_call_id,
        "permission_decision_id": identity.admission_ref,
        "tool_name": identity.tool_name,
        "target": str(target or ""),
        "arguments_preview": preview_payload,
        "state": normalized_state,
        "caller_kind": normalized_caller_kind,
        "caller_ref": identity.caller_ref,
        "action_request_ref": identity.action_request_ref,
        "action_lifecycle_ref": identity.action_lifecycle_ref,
        "action_lifecycle_event": {
            "authority": "harness.loop.execution_kernel",
            "event_type": "tool_item_started",
        },
    }
    if normalized_session_id:
        payload["session_id"] = normalized_session_id
    if normalized_turn_id:
        payload["turn_id"] = normalized_turn_id
    if normalized_turn_run_id:
        payload["turn_run_id"] = normalized_turn_run_id
    if normalized_task_run_id:
        payload["task_run_id"] = normalized_task_run_id
    if normalized_packet_ref:
        payload["packet_ref"] = normalized_packet_ref
    if identity.agent_run_id:
        payload["agent_run_id"] = identity.agent_run_id
    if identity.run_cell_id:
        payload["run_cell_id"] = identity.run_cell_id
    payload.update(dict(extra_payload or {}))

    refs: dict[str, Any] = {
        "action_request_ref": identity.action_request_ref,
        "action_lifecycle_ref": identity.action_lifecycle_ref,
        "tool_invocation_ref": identity.invocation_id,
    }
    if normalized_session_id:
        refs["session_ref"] = normalized_session_id
    if normalized_turn_id:
        refs["turn_ref"] = normalized_turn_id
    if normalized_turn_run_id:
        refs["turn_run_ref"] = normalized_turn_run_id
    if normalized_task_run_id:
        refs["task_run_ref"] = normalized_task_run_id
    if normalized_packet_ref:
        refs["runtime_invocation_packet_ref"] = normalized_packet_ref
    if identity.agent_run_id:
        refs["agent_run_ref"] = identity.agent_run_id
    if identity.run_cell_id:
        refs["run_cell_ref"] = identity.run_cell_id
    refs.update(dict(extra_refs or {}))

    return ToolLifecycleStartedEventRecord(
        event_type="tool_item_started",
        run_id=normalized_run_id,
        payload=payload,
        refs=refs,
    )


def _admission_payload(admission: AdmissionDecision | dict[str, Any]) -> dict[str, Any]:
    if hasattr(admission, "to_dict"):
        return dict(admission.to_dict())  # type: ignore[union-attr]
    return dict(admission or {})


def _model_action_admission_identity(action_request: AnyModelActionRequest) -> dict[str, Any]:
    action_payload = action_request.to_dict()
    action_type = str(action_payload.get("action_type") or "")
    identity: dict[str, Any] = {"action_type": action_type}
    if action_type == "tool_call":
        tool_call = dict(action_payload.get("tool_call") or {})
        tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        tool_args = dict(tool_call.get("args") or tool_call.get("tool_args") or {})
        identity["tool_name"] = tool_name
        identity["tool_args"] = _normalize_tool_call_args_for_fingerprint(tool_name, tool_args)
        return identity
    if action_type == "respond":
        identity["final_answer"] = str(action_payload.get("final_answer") or "")
    elif action_type == "ask_user":
        identity["user_question"] = str(action_payload.get("user_question") or "")
    elif action_type == "block":
        identity["blocking_reason"] = str(action_payload.get("blocking_reason") or "")
    else:
        normalized_payload = _normalize_action_value(action_payload)
        if isinstance(normalized_payload, dict):
            normalized_payload.pop("request_id", None)
            normalized_payload.pop("turn_id", None)
        identity["payload"] = normalized_payload
    return identity


def _admission_runtime_fingerprint_identity(runtime_fingerprint: dict[str, Any]) -> dict[str, str]:
    keys = (
        "runtime_assembly_id",
        "agent_profile_id",
        "runtime_profile_ref",
        "task_environment_id",
        "tool_registry_hash",
        "tool_config_hash",
        "sandbox_policy_hash",
        "permission_policy_hash",
        "backend_config_hash",
        "permission_mode",
    )
    return {key: str(dict(runtime_fingerprint or {}).get(key) or "") for key in keys}


def _normalize_tool_call_args_for_fingerprint(tool_name: str, tool_args: dict[str, Any]) -> Any:
    normalized = _normalize_action_value(tool_args)
    if str(tool_name or "").strip() != "read_file" or not isinstance(normalized, dict):
        return normalized
    defaults = read_window_fingerprint_defaults()
    if "start_line" not in normalized and not any(key in normalized for key in ("offset", "limit")):
        normalized["start_line"] = defaults["start_line"]
    if "line_count" not in normalized and not any(key in normalized for key in ("offset", "limit")):
        normalized["line_count"] = defaults["line_count"]
    return normalized


def _normalize_action_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value):
            item = value[key]
            if isinstance(item, str) and key in {"path", "target_path", "artifact_path", "output_path", "root", "roots", "paths"}:
                normalized[str(key)] = item.replace("\\", "/").strip().strip("/")
            elif isinstance(item, (dict, list)):
                normalized[str(key)] = _normalize_action_value(item)
            else:
                normalized[str(key)] = item
        return normalized
    if isinstance(value, list):
        return [_normalize_action_value(item) if isinstance(item, (dict, list)) else item.replace("\\", "/").strip().strip("/") if isinstance(item, str) else item for item in value]
    return value


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="ignore")
    return hashlib.sha256(encoded).hexdigest()


def build_action_lifecycle_from_admission(
    action_request: AnyModelActionRequest,
    admission: AdmissionDecision,
    *,
    invocation_kind: str,
    permit_invocation_kind: str = "",
    packet_ref: str = "",
    packet_allowed_action_types: tuple[str, ...] = (),
    allowed_tool_names: set[str] | tuple[str, ...] | None = None,
    permission_mode: str = "default",
    side_effect_policy: str = "",
    session_id: str = "",
    turn_id: str = "",
    task_run_id: str = "",
    grant_scope: str = "",
    strict_review: bool | None = None,
    resource_scope: dict[str, Any] | None = None,
) -> ActionLifecycleDecision:
    resolved_permit_invocation = str(permit_invocation_kind or invocation_kind or "")
    allowed_tools = tuple(sorted(str(item) for item in list(allowed_tool_names or ()) if str(item)))
    permit = action_permit_from_admission(
        action_request,
        admission,
        invocation_kind=resolved_permit_invocation,
        packet_allowed_action_types=packet_allowed_action_types,
        allowed_tool_names=allowed_tools,
        permission_mode=permission_mode,
        side_effect_policy=side_effect_policy,
        session_id=session_id,
        turn_id=turn_id,
        task_run_id=task_run_id,
        grant_scope=grant_scope,
        strict_review=strict_review,
        resource_scope=resource_scope,
    )
    action_request_ref = str(getattr(action_request, "request_id", "") or "")
    return ActionLifecycleDecision(
        lifecycle_id=f"action-lifecycle:{action_request_ref}",
        action_request_ref=action_request_ref,
        action_type=str(getattr(action_request, "action_type", "") or ""),
        invocation_kind=str(invocation_kind or ""),
        permit_invocation_kind=resolved_permit_invocation,
        admission=admission,
        action_permit=permit,
        packet_ref=str(packet_ref or ""),
        session_id=str(session_id or ""),
        turn_id=str(turn_id or ""),
        task_run_id=str(task_run_id or ""),
        allowed_action_types=tuple(str(item) for item in packet_allowed_action_types if str(item)),
        allowed_tool_names=allowed_tools,
        diagnostics={
            "admission_ref": admission.admission_id,
            "permit_ref": permit.permit_id,
            "admission_decision": admission.decision,
            "permit_decision": permit.decision,
            "single_authority_chain": "admission->action_permit",
        },
    )
