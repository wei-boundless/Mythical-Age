from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .environment.file_management_policy import prepare_runtime_file_management_policy_for_turn
from .environment.sandbox_policy import prepare_runtime_sandbox_policy_for_turn


@dataclass(frozen=True, slots=True)
class RuntimeEnvironmentPreflightResult:
    sandbox_policy: dict[str, Any]
    file_management_policy: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def prepare_agent_runtime_environment(
    *,
    runtime_host: Any,
    session_id: str,
    task_run_id: str,
    task_id: str,
    task_contract: dict[str, Any],
    user_message: str,
    selected_recipe_payload: dict[str, Any],
    task_selection: dict[str, Any],
    runtime_context_override: dict[str, Any],
    search_policy: list[str] | None,
    allowed_search_sources: set[str],
) -> RuntimeEnvironmentPreflightResult:
    """Prepare system-owned file, sandbox, and search environment state."""

    sandbox_policy = prepare_runtime_sandbox_policy_for_turn(
        root_dir=runtime_host.root_dir,
        session_id=session_id,
        task_run_id=task_run_id,
        task_contract=task_contract,
        user_message=user_message,
        selected_recipe_payload=selected_recipe_payload,
        task_selection={**dict(task_selection or {}), **dict(runtime_context_override or {})},
        state_index=runtime_host.state_index,
        event_log=runtime_host.event_log,
    )
    file_management_policy = prepare_runtime_file_management_policy_for_turn(
        root_dir=runtime_host.root_dir,
        task_run_id=task_run_id,
        selected_recipe_payload=selected_recipe_payload,
        task_selection={**dict(task_selection or {}), **dict(runtime_context_override or {})},
        sandbox_policy=sandbox_policy,
    )
    events: list[dict[str, Any]] = []
    if sandbox_policy.get("enabled") is True:
        sandbox_event = runtime_host.event_log.append(
            task_run_id,
            "runtime_sandbox_prepared",
            payload={
                "sandbox_policy": sandbox_policy,
                "scope": "tool_layer_side_effect_isolation",
                "real_workspace_access": str(sandbox_policy.get("real_workspace_access") or "read_only"),
            },
            refs={
                "sandbox_root_ref": str(sandbox_policy.get("sandbox_root") or ""),
                "task_contract_ref": str(task_contract.get("task_id") or task_id),
            },
        )
        events.append({"type": "runtime_loop_event", "event": sandbox_event.to_dict()})
    if file_management_policy.get("enabled") is True:
        file_management_event = runtime_host.event_log.append(
            task_run_id,
            "runtime_file_management_prepared",
            payload={
                "file_management_policy": file_management_policy,
                "scope": "system_owned_file_environment",
                "profile_id": str(file_management_policy.get("profile_id") or ""),
                "environment_id": str(file_management_policy.get("environment_id") or ""),
            },
            refs={
                "task_contract_ref": str(task_contract.get("task_id") or task_id),
                "file_profile_ref": str(file_management_policy.get("profile_id") or ""),
            },
        )
        events.append({"type": "runtime_loop_event", "event": file_management_event.to_dict()})
    search_policy_event = runtime_host.event_log.append(
        task_run_id,
        "search_policy_resolved",
        payload={
            "search_policy": list(search_policy) if search_policy is not None else None,
            "allowed_sources": sorted(allowed_search_sources),
            "sandbox_policy": sandbox_policy,
            "file_management_policy": file_management_policy,
        },
    )
    events.append({"type": "runtime_loop_event", "event": search_policy_event.to_dict()})
    return RuntimeEnvironmentPreflightResult(
        sandbox_policy=sandbox_policy,
        file_management_policy=file_management_policy,
        events=tuple(events),
    )
