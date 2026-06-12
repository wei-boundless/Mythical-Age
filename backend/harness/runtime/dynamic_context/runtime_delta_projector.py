from __future__ import annotations

from typing import Any

from .models import drop_empty, stable_json_hash, string_tuple


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
        operation_authorization = _operation_authorization_model_visible(
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
                "runtime_baseline_hash": stable_json_hash(
                    {
                        "agent_profile_ref": assembly.get("agent_profile_ref"),
                        "mode": profile.get("mode"),
                        "task_environment_id": environment.get("environment_id"),
                        "agent_prompt_refs": string_tuple(assembly.get("agent_prompt_refs")),
                        "agent_prompt_refs_by_invocation": _prompt_refs_by_invocation(assembly.get("agent_prompt_refs_by_invocation")),
                        "environment_prompt_refs": string_tuple(assembly.get("environment_prompt_refs")),
                    }
                ),
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
                "operation_authorization": operation_authorization,
                "authority": "harness.runtime.dynamic_context.runtime_delta_projection",
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
    if str(projection.get("invocation_kind") or "") == "task_execution":
        return _task_execution_runtime_context_projection(
            assembly_payload,
            agent_visible_runtime_projection=projection,
            prompt_policy=dict(prompt_policy or {}),
        )
    profile = dict(assembly_payload.get("profile") or {})
    environment = dict(assembly_payload.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    payload = {
        "assembly_id": str(assembly_payload.get("assembly_id") or ""),
        "agent_profile_ref": str(assembly_payload.get("agent_profile_ref") or ""),
        "runtime_profile_ref": str(profile.get("profile_ref") or ""),
        "task_environment_id": str(environment.get("environment_id") or ""),
        "storage": drop_empty(
            {
                "environment_storage_root": str(storage.get("environment_storage_root") or ""),
                "artifact_root": str(storage.get("artifact_root") or ""),
            }
        ),
        "agent_prompt_refs": string_tuple(assembly_payload.get("agent_prompt_refs")),
        "agent_prompt_refs_by_invocation": _prompt_refs_by_invocation(assembly_payload.get("agent_prompt_refs_by_invocation")),
        "environment_prompt_refs": string_tuple(assembly_payload.get("environment_prompt_refs")),
        "allowed_operation_count": len(list(dict(assembly_payload.get("operation_authorization") or {}).get("allowed_operations") or [])),
        "runtime_policy_refs": drop_empty(
            {
                "permission_scope": str(dict(profile.get("permission_policy") or {}).get("permission_scope") or ""),
                "task_lifecycle_hash": stable_json_hash(dict(profile.get("task_lifecycle_policy") or {})),
                "planning_hash": stable_json_hash(dict(profile.get("planning_policy") or {})),
                "self_review_hash": stable_json_hash(dict(profile.get("self_review_policy") or {})),
            }
        ),
        "agent_visible_runtime_projection": projection,
    }
    return drop_empty(payload)


def _task_execution_runtime_context_projection(
    assembly_payload: dict[str, Any],
    *,
    agent_visible_runtime_projection: dict[str, Any],
    prompt_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    environment = dict(assembly_payload.get("task_environment") or {})
    tool_boundary = dict(agent_visible_runtime_projection.get("tool_boundary") or {})
    permission_boundary = dict(agent_visible_runtime_projection.get("permission_boundary") or {})
    model_decision_contract = dict(agent_visible_runtime_projection.get("model_decision_contract") or {})
    service_surface = dict(agent_visible_runtime_projection.get("service_surface") or {})
    execution_boundary = dict(agent_visible_runtime_projection.get("execution_boundary") or {})
    show_environment = _prompt_policy_visible(
        dict(prompt_policy or {}),
        "runtime_environment_boundary_visibility",
        default=True,
    )
    return drop_empty(
        {
            **({"task_environment_id": str(environment.get("environment_id") or "")} if show_environment else {}),
            "model_decision_contract": model_decision_contract,
            "service_surface": service_surface,
            "execution_boundary": execution_boundary,
            "permission_scope": str(permission_boundary.get("permission_scope") or ""),
            "tool_boundary": drop_empty(
                {
                    "visible_tool_count": int(tool_boundary.get("visible_tool_count") or 0),
                    "allowed_operation_count": int(tool_boundary.get("allowed_operation_count") or 0),
                    "subagent_lifecycle_enabled": bool(tool_boundary.get("subagent_lifecycle_enabled") is True),
                    "allowed_subagent_ids": [
                        str(item)
                        for item in list(tool_boundary.get("allowed_subagent_ids") or [])
                        if str(item)
                    ],
                }
            ),
            "authority": "harness.runtime.task_execution_context.model_visible",
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


def _prompt_refs_by_invocation(value: Any) -> dict[str, tuple[str, ...]]:
    return {
        str(key): string_tuple(item)
        for key, item in dict(value or {}).items()
        if str(key).strip() and string_tuple(item)
    }


def _runtime_envelope_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    payload = dict(envelope or {})
    artifact_policy = dict(payload.get("artifact_policy") or {})
    permission_policy = dict(payload.get("permission_policy") or {})
    output_policy = dict(payload.get("output_policy") or {})
    return drop_empty(
        {
            "envelope_id": str(payload.get("envelope_id") or ""),
            "scope_kind": str(payload.get("scope_kind") or ""),
            "session_id": str(payload.get("session_id") or ""),
            "turn_id": str(payload.get("turn_id") or ""),
            "task_run_id": str(payload.get("task_run_id") or ""),
            "agent_profile_ref": str(payload.get("agent_profile_ref") or ""),
            "task_environment_ref": str(payload.get("task_environment_ref") or ""),
            "artifact_root": str(artifact_policy.get("artifact_root") or ""),
            "permission_scope": str(permission_policy.get("permission_scope") or permission_policy.get("scope") or ""),
            "output_format": str(output_policy.get("format") or ""),
            "authority": "harness.runtime.envelope.model_visible_projection",
        }
    )


def _operation_authorization_model_visible(authorization: dict[str, Any], *, profile_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(authorization or {})
    policy = dict(profile_payload.get("operation_authorization_projection") or {})
    mode = str(policy.get("model_visible") or policy.get("mode") or "summary_without_denials").strip()
    if mode == "full":
        return payload
    allowed_operations = [str(item) for item in list(payload.get("allowed_operations") or []) if str(item)]
    denied_operations = [str(item) for item in list(payload.get("denied_operations") or []) if str(item)]
    allowed_groups = set(_operation_groups(allowed_operations))
    denied_groups = set(_operation_groups(denied_operations))
    return {
        "authority": "harness.runtime.operation_authorization.model_visible_summary",
        "allowed_operation_count": len(allowed_operations),
        "denied_operation_count": len(denied_operations),
        "critical_denied_groups": sorted(denied_groups - allowed_groups),
        "omitted_denial_details": True,
        "summary_policy": "model_visible_minimal",
        "authorization_hash": stable_json_hash(payload) if payload else "",
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
