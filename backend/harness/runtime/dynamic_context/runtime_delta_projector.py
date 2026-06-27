from __future__ import annotations

from typing import Any

from .models import drop_empty


class RuntimeDeltaProjector:
    def project(
        self,
        *,
        runtime_assembly: dict[str, Any],
        runtime_envelope: dict[str, Any],
        projection_policy: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        assembly = dict(runtime_assembly or {})
        envelope = dict(runtime_envelope or {})
        profile = dict(assembly.get("profile") or {})
        environment = dict(assembly.get("task_environment") or {})
        agent_visible_runtime_projection = dict(dict(projection_policy or {}).get("agent_visible_runtime_projection") or {})
        prompt_policy = dict(dict(projection_policy or {}).get("prompt_policy") or {})
        operation_permission_summary = _operation_permission_summary_model_visible(
            dict(assembly.get("operation_authorization") or dict(projection_policy or {}).get("operation_authorization") or {}),
            profile_payload=profile,
        )
        runtime_context = _runtime_context_projection(
            assembly,
            agent_visible_runtime_projection=agent_visible_runtime_projection,
            prompt_policy=prompt_policy,
        )
        envelope_projection = _runtime_envelope_projection(envelope)
        baseline_refs = drop_empty(
            {
                "agent_profile_ref": str(assembly.get("agent_profile_ref") or envelope_projection.get("agent_profile_ref") or ""),
                **(
                    {"task_environment_ref": str(environment.get("environment_id") or envelope_projection.get("task_environment_ref") or "")}
                    if _prompt_policy_visible(prompt_policy, "runtime_environment_boundary_visibility", default=True)
                    else {}
                ),
            }
        )
        dynamic_delta = drop_empty(
            {
                "runtime_context": runtime_context,
                "operation_permission_summary": operation_permission_summary,
            }
        )
        return baseline_refs, dynamic_delta, envelope_projection


def _runtime_context_projection(
    assembly_payload: dict[str, Any],
    *,
    agent_visible_runtime_projection: dict[str, Any] | None = None,
    prompt_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    projection = dict(agent_visible_runtime_projection or {})
    profile = dict(assembly_payload.get("profile") or {})
    return _runtime_context_cursor_projection(
        agent_visible_runtime_projection=projection,
        profile_payload=profile,
    )


def _runtime_context_cursor_projection(
    *,
    agent_visible_runtime_projection: dict[str, Any],
    profile_payload: dict[str, Any],
) -> dict[str, Any]:
    tool_boundary = dict(agent_visible_runtime_projection.get("tool_boundary") or {})
    permission_boundary = dict(agent_visible_runtime_projection.get("permission_boundary") or {})
    action_surface = dict(
        agent_visible_runtime_projection.get("action_surface")
        or agent_visible_runtime_projection.get("model_decision_contract")
        or {}
    )
    tool_call_contract = dict(agent_visible_runtime_projection.get("tool_call_contract") or {})
    execution_boundary = dict(agent_visible_runtime_projection.get("execution_boundary") or {})
    planning = dict(agent_visible_runtime_projection.get("planning") or {})
    task_lifecycle = dict(agent_visible_runtime_projection.get("task_lifecycle") or {})
    allowed_action_types = [
        str(item)
        for item in list(agent_visible_runtime_projection.get("allowed_action_types") or [])
        if str(item)
    ]
    return drop_empty(
        {
            "invocation_kind": str(agent_visible_runtime_projection.get("invocation_kind") or ""),
            "action_surface": _model_decision_contract_cursor(
                action_surface,
                allowed_action_types=allowed_action_types,
            ),
            "tool_call_contract": _tool_call_contract_cursor(tool_call_contract),
            "execution_boundary": _task_execution_boundary_cursor(execution_boundary),
            "planning": _planning_boundary_cursor(planning),
            "task_lifecycle": _task_lifecycle_boundary_cursor(task_lifecycle),
            "tool_boundary": _tool_boundary_cursor(tool_boundary),
        }
    )


def _planning_boundary_cursor(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    return drop_empty(
        {
            "plan_mode_active": payload.get("plan_mode_active") if isinstance(payload.get("plan_mode_active"), bool) else None,
            "implementation_allowed": payload.get("implementation_allowed")
            if isinstance(payload.get("implementation_allowed"), bool)
            else None,
            "specified_plan_allowed": payload.get("specified_plan_allowed")
            if isinstance(payload.get("specified_plan_allowed"), bool)
            else None,
            "todo_required_when_task_run": payload.get("todo_required_when_task_run")
            if isinstance(payload.get("todo_required_when_task_run"), bool)
            else None,
            "contract_ref": "model_turn_action",
        }
    )


def _task_lifecycle_boundary_cursor(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    return drop_empty(
        {
            "request_task_run_allowed": payload.get("request_task_run_allowed")
            if isinstance(payload.get("request_task_run_allowed"), bool)
            else None,
            "requires_completion_evidence": payload.get("requires_completion_evidence")
            if isinstance(payload.get("requires_completion_evidence"), bool)
            else None,
            "artifact_evidence_required": payload.get("artifact_evidence_required")
            if isinstance(payload.get("artifact_evidence_required"), bool)
            else None,
            "contract_ref": "model_turn_action.task_lifecycle_action_contract",
        }
    )


def _model_decision_contract_cursor(value: dict[str, Any], *, allowed_action_types: list[str]) -> dict[str, Any]:
    task_entry_rule = dict(value.get("task_entry_rule") or {})
    return drop_empty(
        {
            "protocol_ref": "action_schema_static",
            "action_contract_ref": "action_schema_static.action_type",
            "allowed_action_types": list(allowed_action_types),
            "task_run_allowed": task_entry_rule.get("request_task_run_allowed")
            if isinstance(task_entry_rule.get("request_task_run_allowed"), bool)
            else None,
            "action_object_contract_ref": "action_schema_static.action_object_shape_rules",
            "feedback_contract_ref": "action_schema_static.public_response_obligation",
        }
    )


def _task_execution_boundary_cursor(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    return drop_empty(
        {
            "permission_mode": str(payload.get("permission_mode") or ""),
            "approval_required_operation_count": payload.get("approval_required_operation_count")
            if isinstance(payload.get("approval_required_operation_count"), int)
            else None,
            "operation_gate_ref": "runtime.tooling.supervisor",
        }
    )


def _tool_call_contract_cursor(value: dict[str, Any]) -> dict[str, Any]:
    tool_action = dict(value.get("tool_action") or {})
    control_action = dict(value.get("control_action") or {})
    return drop_empty(
        {
            "contract_ref": str(value.get("contract_ref") or ""),
            "tool_action_available": tool_action.get("available")
            if isinstance(tool_action.get("available"), bool)
            else None,
            "tool_action_submission": str(tool_action.get("submission") or ""),
            "control_action_submission": str(control_action.get("submission") or ""),
        }
    )


def _tool_boundary_cursor(value: dict[str, Any]) -> dict[str, Any]:
    allowed_subagent_ids = [
        str(item)
        for item in list(value.get("allowed_subagent_ids") or [])
        if str(item)
    ]
    return drop_empty(
        {
            "visible_tool_count": int(value.get("visible_tool_count") or 0),
            "allowed_operation_count": int(value.get("allowed_operation_count") or 0),
            "tool_index_ref": "tool_index_stable.available_tools",
            "subagent_lifecycle_enabled": bool(value.get("subagent_lifecycle_enabled") is True),
            "allowed_subagent_count": len(allowed_subagent_ids),
            "subagent_registry_ref": "tool_index_stable.available_tools",
        }
    )


def _prompt_policy_visible(policy: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in dict(policy or {}):
        return default
    value = dict(policy or {}).get(key)
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"", "default", "inherit"}:
        return default
    if normalized in {"hidden", "hide", "off", "false", "0", "none", "disabled", "omit", "omitted"}:
        return False
    if normalized in {"visible", "show", "on", "true", "1", "full", "enabled"}:
        return True
    return default


def _runtime_envelope_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    payload = dict(envelope or {})
    artifact_policy = dict(payload.get("artifact_policy") or {})
    permission_policy = dict(payload.get("permission_policy") or {})
    output_policy = dict(payload.get("output_policy") or {})
    return drop_empty(
        {
            "scope_kind": str(payload.get("scope_kind") or ""),
            "permission_scope": str(permission_policy.get("permission_scope") or permission_policy.get("scope") or ""),
            "output_format": str(output_policy.get("format") or ""),
        }
    )


def _operation_permission_summary_model_visible(authorization: dict[str, Any], *, profile_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(authorization or {})
    policy = dict(profile_payload.get("operation_authorization_projection") or {})
    mode = str(policy.get("model_visible") or policy.get("mode") or "summary_without_denials").strip()
    allowed_operations = [str(item) for item in list(payload.get("allowed_operations") or []) if str(item)]
    denied_operations = [str(item) for item in list(payload.get("denied_operations") or []) if str(item)]
    if mode == "full":
        return {
            "allowed_operation_count": len(allowed_operations),
            "denied_operation_count": len(denied_operations),
            "allowed_operation_groups": _operation_groups(allowed_operations),
            "denied_operation_groups": _operation_groups(denied_operations),
            "summary_policy": "model_visible_semantic_groups",
        }
    allowed_groups = set(_operation_groups(allowed_operations))
    denied_groups = set(_operation_groups(denied_operations))
    return {
        "allowed_operation_count": len(allowed_operations),
        "denied_operation_count": len(denied_operations),
        "critical_denied_groups": sorted(denied_groups - allowed_groups),
        "omitted_denial_details": True,
        "summary_policy": "model_visible_minimal",
    }


def _operation_groups(operation_ids: list[str] | tuple[str, ...]) -> list[str]:
    groups: set[str] = set()
    for operation_id in operation_ids:
        item = str(operation_id or "").strip()
        if not item:
            continue
        if item.startswith("op.git_"):
            groups.add("git")
        elif item in {"op.shell", "op.python_repl"}:
            groups.add("command_execution")
        elif item in {"op.write_file", "op.edit_file"}:
            groups.add("file_write")
        elif item in {"op.web_search", "op.fetch_url"}:
            groups.add("network")
        elif item in {"op.browser_control"}:
            groups.add("browser")
        elif item.startswith("op.subagent_"):
            groups.add("subagent_lifecycle")
        elif item == "op.image_generate":
            groups.add("image_generation")
        elif item.startswith("op.mcp_"):
            groups.add("mcp")
        elif item in {"op.read_file", "op.search_files", "op.search_text", "op.list_dir", "op.glob_paths", "op.stat_path", "op.path_exists"}:
            groups.add("file_read")
        else:
            groups.add("other")
    return sorted(groups)
