from __future__ import annotations

from typing import Any

from harness.graph.scheduler_view import is_executable_node


def build_node_contract_index(
    *,
    nodes: list[dict[str, Any]],
    graph_environment: dict[str, Any],
    graph_binding_contract: dict[str, Any],
    graph_permissions: dict[str, Any],
    graph_tools: dict[str, Any],
    node_protocol_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(node.get("node_id") or ""): build_node_contract(
            node=node,
            graph_environment=graph_environment,
            graph_binding_contract=graph_binding_contract,
            graph_permissions=graph_permissions,
            graph_tools=graph_tools,
            node_protocol=dict(node_protocol_index.get(str(node.get("node_id") or "")) or {}),
        )
        for node in nodes
        if str(node.get("node_id") or "")
    }


def build_node_contract(
    *,
    node: dict[str, Any],
    graph_environment: dict[str, Any],
    graph_binding_contract: dict[str, Any],
    graph_permissions: dict[str, Any],
    graph_tools: dict[str, Any],
    node_protocol: dict[str, Any],
) -> dict[str, Any]:
    node_id = str(node.get("node_id") or "").strip()
    contracts = dict(node.get("contracts") or {})
    bindings = dict(contracts.get("contract_bindings") or {})
    runtime_bindings = dict(bindings.get("runtime") or {})
    prompt_contract = dict(node.get("prompt") or {})
    metadata = dict(node.get("metadata") or {})
    runtime_profile = dict(metadata.get("runtime_profile") or metadata.get("runtime") or {})
    node_runtime_policy = dict(node.get("runtime_policy") or node.get("execution_policy") or {})
    if node_runtime_policy:
        runtime_profile["runtime_policy"] = _merge_runtime_policy_dicts(
            dict(runtime_profile.get("runtime_policy") or runtime_profile.get("execution_policy") or {}),
            node_runtime_policy,
        )
    environment_lock = _environment_lock(
        node=node,
        graph_environment=graph_environment,
        runtime_profile=runtime_profile,
        runtime_bindings=runtime_bindings,
    )
    session_policy = _node_session_policy(
        node=node,
        runtime_profile=runtime_profile,
        environment_lock=environment_lock,
        graph_binding_contract=graph_binding_contract,
    )
    executor = dict(node.get("executor") or {})
    return _drop_empty(
        {
            "contract_id": str(contracts.get("node_contract_id") or f"node-contract:{node_id}"),
            "node_id": node_id,
            "node_kind": _node_kind(node),
            "node_class": str(node.get("node_class") or ("executable" if is_executable_node(node) else "resource")),
            "executor": executor,
            "agent": _drop_empty(
                {
                    "agent_id": str(node.get("agent_id") or ""),
                    "agent_profile_id": str(node.get("agent_profile_id") or ""),
                    "agent_selection_policy": str(metadata.get("agent_selection_policy") or ""),
                }
            ),
            "input_contract": _drop_empty(
                {
                    "input_contract_id": str(contracts.get("input_contract_id") or ""),
                    "accepted_payload_contract_ids": list(node_protocol.get("accepted_payload_contract_ids") or []),
                    "input_keys": list(node_protocol.get("input_keys") or []),
                }
            ),
            "output_contract": _drop_empty(
                {
                    "output_contract_id": str(contracts.get("output_contract_id") or ""),
                    "produced_payload_contract_ids": list(node_protocol.get("produced_payload_contract_ids") or []),
                    "output_keys": list(node_protocol.get("output_keys") or []),
                    "artifact_output_keys": list(node_protocol.get("artifact_output_keys") or []),
                }
            ),
            "prompt_contract": prompt_contract,
            "runtime_policy": dict(runtime_profile.get("runtime_policy") or runtime_profile.get("execution_policy") or {}),
            "environment_lock": environment_lock,
            "project_binding": _node_project_binding(
                node=node,
                graph_binding_contract=graph_binding_contract,
            ),
            "session_policy": session_policy,
            "permission_ceiling": dict(node.get("permissions") or graph_permissions or {}),
            "tool_contract": dict(node.get("tools") or graph_tools or {}),
            "memory_contract": dict(node.get("memory") or {}),
            "artifact_contract": dict(node.get("artifacts") or {}),
            "state_policy": {
                "checkpoint_scope": "node_work_order",
                "resume_policy": "config_hash_locked",
            },
            "trace_policy": {
                "trace_node_execution": True,
                "receipt_required": True,
            },
            "authority": "task_system.compiled_node_contract",
        }
    )


def _environment_lock(
    *,
    node: dict[str, Any],
    graph_environment: dict[str, Any],
    runtime_profile: dict[str, Any],
    runtime_bindings: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    graph_environment_id = str(
        graph_environment.get("task_environment_id")
        or graph_environment.get("environment_id")
        or ""
    ).strip()
    node_environment_id = str(
        metadata.get("task_environment_id")
        or metadata.get("environment_id")
        or runtime_profile.get("task_environment_id")
        or runtime_profile.get("environment_id")
        or runtime_bindings.get("task_environment_id")
        or runtime_bindings.get("environment_id")
        or graph_environment_id
        or ""
    ).strip()
    return _drop_empty(
        {
            "task_environment_id": node_environment_id,
            "environment_id": node_environment_id,
            "graph_control_environment_id": graph_environment_id,
            "source": "node_override" if node_environment_id and node_environment_id != graph_environment_id else "graph_control_environment",
            "locked": bool(node_environment_id),
            "authority": "task_system.node_effective_environment_lock",
        }
    )


def _node_project_binding(*, node: dict[str, Any], graph_binding_contract: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    project_id = str(metadata.get("project_id") or graph_binding_contract.get("project_id") or "").strip()
    return _drop_empty(
        {
            "binding_mode": str(graph_binding_contract.get("binding_mode") or "project_scoped"),
            "project_id": project_id,
            "graph_binding_contract_id": str(graph_binding_contract.get("contract_id") or ""),
            "authority": "task_system.node_project_binding",
        }
    )


def _node_session_policy(
    *,
    node: dict[str, Any],
    runtime_profile: dict[str, Any],
    environment_lock: dict[str, Any],
    graph_binding_contract: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    configured = dict(metadata.get("session_policy") or runtime_profile.get("session_policy") or {})
    mode = str(configured.get("mode") or "per_node_run_session").strip() or "per_node_run_session"
    return _drop_empty(
        {
            "mode": mode,
            "session_id_template": str(configured.get("session_id_template") or "gsess-{graph_run_id}-{node_id}-{dispatch_seq}"),
            "history_policy": str(configured.get("history_policy") or "isolated_from_root_conversation"),
            "bind_project": True,
            "project_id": str(configured.get("project_id") or graph_binding_contract.get("project_id") or ""),
            "task_environment_id": str(configured.get("task_environment_id") or environment_lock.get("task_environment_id") or ""),
            "can_create_session": True,
            "authority": "task_system.node_session_policy",
        }
    )


def _node_kind(node: dict[str, Any]) -> str:
    if str(node.get("node_class") or "") == "resource":
        return "ResourceNode"
    node_type = str(node.get("node_type") or "").strip()
    if node_type in {"router", "barrier", "join", "human_gate", "review_gate", "manual_gate", "safety_gate"}:
        return "ControlNode"
    return "ExecutableNode"


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }


def _merge_runtime_policy_dicts(*values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        for key, item in dict(value or {}).items():
            if isinstance(result.get(key), dict) and isinstance(item, dict):
                result[key] = _merge_runtime_policy_dicts(dict(result[key]), item)
            else:
                result[key] = item
    return result
