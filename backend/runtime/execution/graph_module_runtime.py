from __future__ import annotations

import hashlib
import json
from typing import Any


def graph_module_stage_is_enabled(contract: dict[str, Any]) -> bool:
    metadata = dict(contract.get("metadata") or {}) if isinstance(contract.get("metadata"), dict) else {}
    return (
        str(contract.get("node_type") or "").strip() == "graph_module"
        or bool(contract.get("graph_module") is True)
        or bool(metadata.get("graph_module") is True)
        or bool(contract.get("linked_graph_id"))
        or bool(metadata.get("linked_graph_id"))
        or str(metadata.get("execution_mode") or "").strip() == "graph_module_run"
    )


def build_graph_module_runtime_handle_from_contract(
    *,
    importing_graph_id: str,
    importing_coordination_run_id: str,
    importing_root_task_run_id: str,
    stage_id: str,
    node_id: str,
    contract: dict[str, Any],
    runtime_node: dict[str, Any],
    explicit_inputs: dict[str, Any],
    dispatch_context: dict[str, Any],
    standard_input_package: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(runtime_node.get("metadata") or {})
    contract_metadata = dict(contract.get("metadata") or {}) if isinstance(contract.get("metadata"), dict) else {}
    graph_module_plan = dict(
        contract.get("graph_module_runtime_plan")
        or contract_metadata.get("graph_module_runtime_plan")
        or metadata.get("graph_module_runtime_plan")
        or {}
    )
    linked_graph_id = str(
        contract.get("linked_graph_id")
        or contract_metadata.get("linked_graph_id")
        or metadata.get("linked_graph_id")
        or graph_module_plan.get("linked_graph_id")
        or ""
    ).strip()
    graph_module_plan_id = str(
        contract.get("graph_module_runtime_plan_id")
        or contract_metadata.get("graph_module_runtime_plan_id")
        or metadata.get("graph_module_runtime_plan_id")
        or graph_module_plan.get("plan_id")
        or ""
    ).strip()
    seed = {
        "importing_coordination_run_id": importing_coordination_run_id,
        "importing_stage_id": stage_id,
        "node_id": node_id,
        "linked_graph_id": linked_graph_id,
        "dispatch_event_id": str(dispatch_context.get("dispatch_event_id") or ""),
        "scope_path": list(dispatch_context.get("scope_path") or []),
    }
    return {
        "authority": "orchestration.graph_module_runtime_handle",
        "handle_id": f"graphmodrun:{_short_hash(seed)}",
        "importing_graph_id": str(importing_graph_id or graph_module_plan.get("importing_graph_id") or ""),
        "importing_coordination_run_id": str(importing_coordination_run_id or ""),
        "importing_root_task_run_id": str(importing_root_task_run_id or ""),
        "importing_stage_id": stage_id,
        "importing_node_id": node_id,
        "linked_graph_id": linked_graph_id,
        "graph_module_runtime_plan_id": graph_module_plan_id,
        "graph_module_runtime_plan": graph_module_plan,
        "version_ref": _first_non_empty(contract.get("version_ref"), contract_metadata.get("version_ref"), metadata.get("version_ref"), graph_module_plan.get("version_ref")),
        "handoff_contract_id": _first_non_empty(contract.get("handoff_contract_id"), contract_metadata.get("handoff_contract_id"), metadata.get("handoff_contract_id"), graph_module_plan.get("handoff_contract_id")),
        "input_port_id": _first_non_empty(contract.get("input_port_id"), contract_metadata.get("input_port_id"), metadata.get("input_port_id"), graph_module_plan.get("input_port_id"), "input.default") or "input.default",
        "output_port_id": _first_non_empty(contract.get("output_port_id"), contract_metadata.get("output_port_id"), metadata.get("output_port_id"), graph_module_plan.get("output_port_id"), "output.default") or "output.default",
        "isolation_policy": _first_non_empty(contract.get("isolation_policy"), contract_metadata.get("isolation_policy"), metadata.get("isolation_policy"), graph_module_plan.get("isolation_policy"), "isolated_per_graph_module_run") or "isolated_per_graph_module_run",
        "visibility_policy": _first_non_empty(contract.get("visibility_policy"), contract_metadata.get("visibility_policy"), metadata.get("visibility_policy"), graph_module_plan.get("visibility_policy"), "committed_only") or "committed_only",
        "detach_policy": _first_non_empty(contract.get("detach_policy"), contract_metadata.get("detach_policy"), metadata.get("detach_policy"), graph_module_plan.get("detach_policy"), "preserve_version_anchor") or "preserve_version_anchor",
        "executor_policy": dict(contract.get("executor_policy") or metadata.get("executor_policy") or {}),
        "explicit_inputs": dict(explicit_inputs or {}),
        "standard_input_package": dict(standard_input_package or {}),
        "dispatch_context": dict(dispatch_context or {}),
    }


def build_graph_module_runtime_handle_from_request(request_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_assembly = dict(request_payload.get("runtime_assembly") or {})
    executor_binding = dict(request_payload.get("executor_binding") or {})
    handle = dict(
        runtime_assembly.get("graph_module_runtime_handle")
        or executor_binding.get("graph_module_runtime_handle")
        or {}
    )
    if handle:
        handle.setdefault("executor_policy", dict(executor_binding.get("executor_policy") or runtime_assembly.get("executor_policy") or {}))
        return handle
    graph_module_plan = dict(
        runtime_assembly.get("graph_module_runtime_plan")
        or executor_binding.get("graph_module_runtime_plan")
        or {}
    )
    return {
        "authority": "orchestration.graph_module_runtime_handle",
        "handle_id": str(runtime_assembly.get("handle_id") or executor_binding.get("handle_id") or ""),
        "importing_coordination_run_id": str(request_payload.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(request_payload.get("root_task_run_id") or ""),
        "importing_stage_id": str(request_payload.get("stage_id") or ""),
        "importing_node_id": str(request_payload.get("node_id") or ""),
        "linked_graph_id": str(
            runtime_assembly.get("linked_graph_id")
            or executor_binding.get("linked_graph_id")
            or executor_binding.get("imported_graph_id")
            or graph_module_plan.get("linked_graph_id")
            or ""
        ),
        "graph_module_runtime_plan_id": str(
            runtime_assembly.get("graph_module_runtime_plan_id")
            or executor_binding.get("graph_module_runtime_plan_id")
            or graph_module_plan.get("plan_id")
            or ""
        ),
        "graph_module_runtime_plan": graph_module_plan,
        "explicit_inputs": dict(request_payload.get("explicit_inputs") or {}),
        "standard_input_package": dict(request_payload.get("standard_input_package") or {}),
    }


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _short_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
