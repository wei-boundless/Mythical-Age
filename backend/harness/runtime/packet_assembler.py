from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from harness.current_work_receipt import current_work_control_availability_from_receipt
from runtime.memory.file_evidence_scope import session_file_evidence_scope
from runtime.memory.file_state_store import FileStateAuthorityStore

from .context_budget_policy import build_model_aware_context_budget_policy
from .dynamic_context import dynamic_context_storage_root
from .dynamic_context.read_evidence_projector import build_read_evidence_projection_payload
from .packet_context import RuntimePacketContext, RuntimePacketModelActionSurface
from .tool_plan import RuntimeToolPlan, build_runtime_tool_plan


def build_single_agent_turn_packet_context(
    *,
    session_id: str,
    turn_id: str,
    agent_invocation_id: str,
    user_message: str,
    history: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    session_context: dict[str, Any] | None = None,
    active_work_context: dict[str, Any] | None = None,
    current_work_boundary_receipt: dict[str, Any] | None = None,
    memory_context: dict[str, Any] | None = None,
    agent_profile_ref: str = "main_interactive_agent",
    model_selection: dict[str, Any] | None = None,
    runtime_assembly: Any | None = None,
    tool_definitions_by_name: dict[str, Any] | None = None,
    prompt_pack_refs: tuple[str, ...] = (),
    base_dir: Path | str | None = None,
) -> RuntimePacketContext:
    runtime_base_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[2]
    assembly_payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    profile_payload = dict(assembly_payload.get("profile") or {})
    environment_payload = dict(assembly_payload.get("task_environment") or {})
    control_capabilities = dict(assembly_payload.get("control_capabilities") or {})
    permission_mode = str(assembly_payload.get("permission_mode") or "default")
    resolved_agent_profile_ref = str(assembly_payload.get("agent_profile_ref") or agent_profile_ref or "main_interactive_agent")
    task_environment_ref = str(environment_payload.get("environment_id") or "env.general.workspace")
    session_context_payload = dict(session_context or {})
    active_work_payload = dict(active_work_context or {})
    current_work_receipt_payload = dict(current_work_boundary_receipt or {})
    model_selection_payload = dict(model_selection or {})
    tool_plan = _single_agent_turn_tool_plan(
        assembly_payload=assembly_payload,
        control_capabilities=control_capabilities,
        tool_definitions_by_name=tool_definitions_by_name,
    )
    model_visible_tools = tuple(dict(item) for item in tool_plan.model_visible_tools)
    surface = _single_agent_turn_model_action_surface(
        control_capabilities=control_capabilities,
        model_visible_tools=model_visible_tools,
    )
    effective_capabilities = _single_agent_turn_effective_control_capabilities(
        control_capabilities=control_capabilities,
        allowed_actions=surface.allowed_action_types,
        visible_tool_count=len(model_visible_tools),
        visible_tool_names=tuple(
            str(item.get("tool_name") or item.get("name") or "")
            for item in model_visible_tools
            if str(item.get("tool_name") or item.get("name") or "")
        ),
    )
    operation_availability = _single_agent_turn_operation_availability(
        current_work_boundary_receipt=current_work_receipt_payload,
    )
    packet_id = f"rtpacket:{turn_id}:single_agent_turn:1"
    projection_policy = build_dynamic_context_projection_policy(
        invocation_kind="single_agent_turn",
        model_selection=model_selection_payload,
        assembly_payload=assembly_payload,
        overrides={
            "operation_authorization": dict(assembly_payload.get("operation_authorization") or {}),
            "active_work_context": active_work_payload,
            "current_work_boundary_receipt": current_work_receipt_payload,
        },
    )
    session_evidence = build_session_file_evidence_projection(
        session_id=str(session_id or ""),
        base_dir=runtime_base_dir,
        runtime_assembly=assembly_payload,
        budget_policy=projection_policy,
        packet_id=packet_id,
        current_observations=(),
    )
    file_evidence_scope = dict(session_evidence.get("file_evidence_scope") or {})
    file_state = tuple(dict(item) for item in list(session_evidence.get("file_state") or []) if isinstance(item, dict))
    read_evidence_payload = dict(session_evidence.get("read_evidence_payload") or {})
    evidence_projection = dict(session_evidence.get("evidence_projection") or {})
    return RuntimePacketContext(
        invocation_kind="single_agent_turn",
        session_id=str(session_id or ""),
        turn_id=str(turn_id or ""),
        agent_invocation_id=str(agent_invocation_id or ""),
        user_message=str(user_message or ""),
        history=tuple(dict(item) for item in list(history or []) if isinstance(item, dict)),
        session_context=session_context_payload,
        active_work_context=active_work_payload,
        current_work_boundary_receipt=current_work_receipt_payload,
        memory_context=dict(memory_context or {}),
        model_selection=model_selection_payload,
        runtime_assembly=assembly_payload,
        profile_payload=profile_payload,
        environment_payload=environment_payload,
        control_capabilities=control_capabilities,
        effective_control_capabilities=effective_capabilities,
        operation_availability=operation_availability,
        file_evidence_scope=file_evidence_scope,
        file_state=file_state,
        projection_policy=projection_policy,
        read_evidence_payload=read_evidence_payload,
        evidence_projection=evidence_projection,
        agent_scope=_single_agent_turn_agent_scope(
            session_id=str(session_id or ""),
            turn_id=str(turn_id or ""),
            agent_invocation_id=str(agent_invocation_id or ""),
        ),
        agent_profile_ref=resolved_agent_profile_ref,
        task_environment_ref=task_environment_ref,
        permission_mode=permission_mode,
        prompt_pack_refs=tuple(str(item) for item in tuple(prompt_pack_refs or ()) if str(item)),
        model_action_surface=surface,
        tool_plan=tool_plan,
        model_visible_tools=model_visible_tools,
        packet_id=packet_id,
    )


def build_dynamic_context_projection_policy(
    *,
    invocation_kind: str,
    model_selection: dict[str, Any] | None,
    assembly_payload: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    budget_policy = build_model_aware_context_budget_policy(
        invocation_kind=invocation_kind,
        model_selection=model_selection,
        runtime_assembly=assembly_payload,
    ).to_projection_policy()
    return {
        **budget_policy,
        **dict(overrides or {}),
    }


def build_file_state_snapshot_for_scope(
    base_dir: Path,
    runtime_assembly: dict[str, Any],
    file_evidence_scope: dict[str, Any],
    *,
    limit: int = 20,
) -> tuple[dict[str, Any], ...]:
    scope = dict(file_evidence_scope or {})
    if not scope:
        return ()
    storage_root = dynamic_context_storage_root(base_dir, dict(runtime_assembly or {})) or base_dir
    try:
        return tuple(dict(item) for item in FileStateAuthorityStore(storage_root).snapshot_scope(scope, limit=limit))
    except Exception:
        return ()


def build_read_evidence_injection_payload(
    *,
    base_dir: Path,
    runtime_assembly: dict[str, Any],
    file_state: list[dict[str, Any]],
    file_evidence_scope: dict[str, Any],
    packet_id: str,
    budget_policy: dict[str, Any] | None = None,
    current_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    include_historical_refs: bool = True,
) -> dict[str, Any]:
    scope = dict(file_evidence_scope or {})
    if not scope:
        return {}
    storage_root = dynamic_context_storage_root(base_dir, dict(runtime_assembly or {})) or base_dir
    budget_payload = dict(runtime_assembly.get("read_evidence_policy") or {})
    budget_payload.update(dict(runtime_assembly.get("context_budget_policy") or {}))
    budget_payload.update(dict(budget_policy or {}))
    return build_read_evidence_projection_payload(
        storage_root=storage_root,
        file_state=file_state,
        packet_id=packet_id,
        budget_policy=budget_payload,
        current_observations=current_observations,
        include_historical_refs=include_historical_refs,
    )


def build_session_file_evidence_projection(
    *,
    session_id: str,
    base_dir: Path,
    runtime_assembly: dict[str, Any],
    packet_id: str,
    budget_policy: dict[str, Any] | None = None,
    current_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    include_historical_refs: bool = True,
) -> dict[str, Any]:
    file_evidence_scope = session_file_evidence_scope(str(session_id or ""))
    file_state = build_file_state_snapshot_for_scope(base_dir, runtime_assembly, file_evidence_scope)
    read_evidence_payload = build_read_evidence_injection_payload(
        base_dir=base_dir,
        runtime_assembly=runtime_assembly,
        file_state=list(file_state),
        file_evidence_scope=file_evidence_scope,
        packet_id=packet_id,
        budget_policy=budget_policy,
        current_observations=current_observations,
        include_historical_refs=include_historical_refs,
    )
    evidence_projection = _runtime_packet_evidence_projection(
        file_evidence_scope=file_evidence_scope,
        file_state=file_state,
        read_evidence_payload=read_evidence_payload,
    )
    return {
        "file_evidence_scope": dict(file_evidence_scope),
        "file_state": [dict(item) for item in file_state],
        "read_evidence_payload": dict(read_evidence_payload),
        "evidence_projection": evidence_projection,
    }


def _single_agent_turn_operation_availability(
    *,
    current_work_boundary_receipt: dict[str, Any],
) -> dict[str, Any]:
    active_work_availability = current_work_control_availability_from_receipt(current_work_boundary_receipt)
    return {
        "active_work_control": active_work_availability.available if active_work_availability.observed else None,
        "source_authority": "harness.runtime.packet_assembler.operation_availability",
        "source_ref": str(current_work_boundary_receipt.get("receipt_id") or ""),
        "active_work_control_reason": active_work_availability.reason,
    }


def _runtime_packet_evidence_projection(
    *,
    file_evidence_scope: dict[str, Any],
    file_state: tuple[dict[str, Any], ...],
    read_evidence_payload: dict[str, Any],
) -> dict[str, Any]:
    evidence_payload = dict(read_evidence_payload or {})
    return {
        "authority": "harness.runtime.packet_assembler.evidence_projection",
        "file_evidence_scope": dict(file_evidence_scope or {}),
        "file_state_source": "runtime.memory.file_state_store" if file_state else "",
        "file_state_count": len(file_state),
        "read_evidence_ref_count": len(
            [item for item in list(evidence_payload.get("read_evidence_refs") or []) if isinstance(item, dict)]
        ),
        "read_required_window_count": len(
            [item for item in list(evidence_payload.get("read_required_windows") or []) if isinstance(item, dict)]
        ),
        "visible_exact_in_packet": bool(evidence_payload.get("visible_exact_in_packet") is True),
        "read_evidence_packet_id": str(evidence_payload.get("packet_id") or ""),
    }


def _single_agent_turn_agent_scope(
    *,
    session_id: str,
    turn_id: str,
    agent_invocation_id: str,
) -> dict[str, Any]:
    return {
        "session_id": str(session_id or ""),
        "turn_id": str(turn_id or ""),
        "agent_invocation_id": str(agent_invocation_id or ""),
        "invocation_kind": "single_turn",
        "authority": "harness.runtime.packet_context.agent_scope_projection",
    }


def _stable_hash(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _single_agent_turn_model_action_surface(
    *,
    control_capabilities: dict[str, Any],
    model_visible_tools: tuple[dict[str, Any], ...],
) -> RuntimePacketModelActionSurface:
    actions: list[str] = ["respond", "ask_user", "block"]
    if bool(control_capabilities.get("may_request_task_run") is True):
        actions.append("request_task_run")
    if bool(control_capabilities.get("may_control_active_work") is True):
        actions.append("active_work_control")
    if model_visible_tools:
        actions.append("tool_call")
    allowed_action_types = tuple(dict.fromkeys(actions))
    surface_id = "turn-action-surface:" + _stable_hash(
        {
            "allowed_action_types": list(allowed_action_types),
            "may_request_task_run": bool(control_capabilities.get("may_request_task_run") is True),
            "may_control_active_work": bool(control_capabilities.get("may_control_active_work") is True),
            "visible_tool_count": len(model_visible_tools),
        }
    )[:20]
    return RuntimePacketModelActionSurface(
        allowed_action_types=allowed_action_types,
        surface_id=surface_id,
        contract_ref="turn_operating_contract.action_surface",
        diagnostics={
            "source": "runtime_capabilities_and_state_candidates",
            "may_request_task_run": bool(control_capabilities.get("may_request_task_run") is True),
            "may_control_active_work": bool(control_capabilities.get("may_control_active_work") is True),
            "visible_tool_count": len(model_visible_tools),
        },
    )


def _single_agent_turn_effective_control_capabilities(
    *,
    control_capabilities: dict[str, Any],
    allowed_actions: tuple[str, ...],
    visible_tool_count: int = 0,
    visible_tool_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    effective = dict(control_capabilities or {})
    allowed = {str(item) for item in allowed_actions if str(item)}
    supports_json_action_protocol = bool(
        effective.get("supports_json_action_protocol")
        or {"ask_user", "block", "request_task_run", "active_work_control", "tool_call"}.intersection(allowed)
    )
    effective["authority"] = "harness.runtime.single_agent_turn_control_capabilities"
    effective["may_call_tools"] = "tool_call" in allowed and visible_tool_count > 0
    effective["may_use_subagents"] = bool(
        effective.get("may_use_subagents") is True
        and set(visible_tool_names).intersection({"delegate_to_subagent", "subagent", "agent_delegate"})
    )
    effective["supports_json_action_protocol"] = supports_json_action_protocol
    effective["requires_json_action_protocol"] = bool(
        effective.get("requires_json_action_protocol") is True
        and effective.get("requires_json_action_protocol_explicit") is True
    )
    effective["visible_tool_count"] = visible_tool_count
    effective["may_request_task_run"] = "request_task_run" in allowed
    effective["may_control_active_work"] = "active_work_control" in allowed
    effective.setdefault("may_emit_assistant_message", True)
    return effective


def _single_agent_turn_tool_plan(
    *,
    assembly_payload: dict[str, Any],
    control_capabilities: dict[str, Any],
    tool_definitions_by_name: dict[str, Any] | None = None,
) -> Any:
    definitions_by_name = dict(tool_definitions_by_name or {})
    if bool(control_capabilities.get("may_call_tools") is False):
        return build_runtime_tool_plan(
            runtime_assembly={**dict(assembly_payload or {}), "available_tools": []},
            invocation_kind="single_agent_turn",
            tool_definitions_by_name=definitions_by_name,
        )
    return build_runtime_tool_plan(
        runtime_assembly=assembly_payload,
        invocation_kind="single_agent_turn",
        tool_definitions_by_name=definitions_by_name,
    )
