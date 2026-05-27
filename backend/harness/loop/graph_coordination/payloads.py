from __future__ import annotations

import time
from dataclasses import fields as dataclass_fields
from typing import Any

from task_system.compiler.coordination_graph_models import TaskGraphRuntimeEdge, TaskGraphRuntimeNode, TaskGraphRuntimeSpec

from runtime.contracts.compiler_models import (
    CompiledAcceptanceContract,
    CompiledEdgeHandoffContract,
    CompiledGlobalContract,
    CompiledGraphModuleHandoffContract,
    CompiledNodeContract,
    CompiledRuntimeContract,
    ContractCompileIssue,
    ContractManifest,
)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_id(value: Any) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", ":"} else "_" for ch in str(value or ""))[:180]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


def _graph_id_from_state(state: dict[str, Any]) -> str:
    diagnostics = dict(state.get("diagnostics") or {})
    graph_spec = dict(diagnostics.get("coordination_graph_spec") or {})
    return str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or diagnostics.get("graph_ref") or "")


def _runtime_node_payload(state: dict[str, Any], node_id: str) -> dict[str, Any]:
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    for item in list(graph_spec.get("nodes") or []):
        node = dict(item or {})
        if str(node.get("node_id") or "") == str(node_id or ""):
            return node
    return {}


def _runtime_node_value(state: dict[str, Any], node_id: str, key: str) -> Any:
    return _runtime_node_payload(state, node_id).get(key)


def _runtime_spec_from_state(state: dict[str, Any]) -> TaskGraphRuntimeSpec | None:
    payload = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    return _runtime_spec_from_payload(payload)


def _edge_handoff_index_from_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for raw in list(state.get("handoff_envelopes") or []):
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        diagnostics = dict(payload.get("diagnostics") or {})
        edge_id = str(payload.get("edge_id") or diagnostics.get("edge_id") or "").strip()
        source = str(payload.get("source_node_id") or diagnostics.get("source_node_id") or diagnostics.get("source_stage_id") or "").strip()
        target = str(payload.get("target_node_id") or diagnostics.get("target_node_id") or diagnostics.get("target_stage_id") or "").strip()
        keys = [edge_id, f"{source}->{target}" if source and target else "", f"{source}:{target}" if source and target else ""]
        for key in keys:
            if key:
                index[key] = payload
    return index


def _runtime_spec_from_payload(payload: dict[str, Any]) -> TaskGraphRuntimeSpec | None:
    if not payload:
        return None
    try:
        return TaskGraphRuntimeSpec(
            graph_id=str(payload.get("graph_id") or ""),
            domain_id=str(payload.get("domain_id") or ""),
            coordinator_agent_id=str(payload.get("coordinator_agent_id") or ""),
            graph_ref=str(payload.get("graph_ref") or payload.get("graph_id") or ""),
            agent_group_id=str(payload.get("agent_group_id") or ""),
            nodes=tuple(
                _dataclass_from_payload(TaskGraphRuntimeNode, item)
                for item in list(payload.get("nodes") or [])
                if isinstance(item, dict)
            ),
            edges=tuple(
                _dataclass_from_payload(TaskGraphRuntimeEdge, item)
                for item in list(payload.get("edges") or [])
                if isinstance(item, dict)
            ),
            subtask_refs=tuple(str(item) for item in list(payload.get("subtask_refs") or []) if str(item)),
            communication_modes=tuple(str(item) for item in list(payload.get("communication_modes") or []) if str(item)),
            start_node_ids=tuple(str(item) for item in list(payload.get("start_node_ids") or []) if str(item)),
            terminal_node_ids=tuple(str(item) for item in list(payload.get("terminal_node_ids") or []) if str(item)),
            resource_nodes=_dict_tuple(payload.get("resource_nodes")),
            temporal_edges=_dict_tuple(payload.get("temporal_edges")),
            memory_edges=_dict_tuple(payload.get("memory_edges")),
            artifact_context_edges=_dict_tuple(payload.get("artifact_context_edges")),
            revision_edges=_dict_tuple(payload.get("revision_edges")),
            loop_frames=_dict_tuple(payload.get("loop_frames")),
            memory_matrix=dict(payload.get("memory_matrix") or {}),
            issues=(),
            diagnostics=dict(payload.get("diagnostics") or {}),
        )
    except (TypeError, ValueError):
        return None


def _dataclass_from_payload(model_type: Any, payload: dict[str, Any]) -> Any:
    allowed = {item.name for item in dataclass_fields(model_type)}
    return model_type(**{key: value for key, value in dict(payload or {}).items() if key in allowed})


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def _initial_contract_status(manifest: dict[str, Any]) -> dict[str, Any]:
    node_status = {
        str(item.get("node_id") or ""): {
            "status": "pending",
            "contract_refs": list(item.get("contract_refs") or []),
            "missing_required_inputs": [],
            "accepted": False,
        }
        for item in list(manifest.get("node_contracts") or [])
        if str(item.get("node_id") or "")
    }
    edge_status = {
        str(item.get("edge_id") or ""): {
            "status": "pending",
            "contract_refs": list(item.get("contract_refs") or []),
            "source_node_id": str(item.get("source_node_id") or ""),
            "target_node_id": str(item.get("target_node_id") or ""),
        }
        for item in list(manifest.get("edge_handoff_contracts") or [])
        if str(item.get("edge_id") or "")
    }
    return {
        "authority": "task_system.contract_status",
        "manifest_ref": str(manifest.get("manifest_id") or ""),
        "valid": bool(manifest.get("valid") is True),
        "issues": list(manifest.get("issues") or []),
        "node_status": node_status,
        "edge_status": edge_status,
        "acceptance_results": {},
    }


def _set_contract_node_status(
    contract_status: dict[str, Any],
    *,
    stage_id: str,
    node_status_value: str,
    accepted: bool,
    task_result_ref: str,
    artifact_refs: list[str],
    missing_required_inputs: list[str],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    next_status = dict(contract_status or {})
    node_status = {
        str(key): dict(value)
        for key, value in dict(next_status.get("node_status") or {}).items()
        if str(key) and isinstance(value, dict)
    }
    acceptance_results = {
        str(stage): dict(value)
        for stage, value in dict(next_status.get("acceptance_results") or {}).items()
        if str(stage) and isinstance(value, dict)
    }
    node_payload = dict(node_status.get(stage_id) or {})
    node_payload.update(
        {
            "status": node_status_value,
            "accepted": accepted,
            "task_result_ref": task_result_ref,
            "artifact_refs": list(artifact_refs),
            "missing_required_inputs": list(missing_required_inputs),
            "updated_at": time.time(),
            "diagnostics": dict(diagnostics or {}),
        }
    )
    node_status[stage_id] = node_payload
    existing_acceptance = dict(acceptance_results.get(stage_id) or {})
    if existing_acceptance.get("artifact_refs") and not artifact_refs:
        artifact_refs = list(existing_acceptance.get("artifact_refs") or [])
    acceptance_results[stage_id] = {
        "accepted": accepted,
        "status": node_status_value,
        "task_result_ref": task_result_ref,
        "artifact_refs": list(artifact_refs),
        "missing_required_inputs": list(missing_required_inputs),
        "diagnostics": dict(diagnostics or {}),
    }
    next_status["node_status"] = node_status
    next_status["acceptance_results"] = acceptance_results
    return next_status


def _accept_contract_status(
    status: dict[str, Any],
    *,
    stage_id: str,
    accepted: bool,
    task_result_ref: str,
    artifact_refs: list[str],
    missing_required_inputs: list[str],
) -> dict[str, Any]:
    next_status = dict(status or {})
    node_status = {
        str(key): dict(value)
        for key, value in dict(next_status.get("node_status") or {}).items()
    }
    node_payload = dict(node_status.get(stage_id) or {})
    node_payload.update(
        {
            "status": "satisfied" if accepted else "failed",
            "accepted": accepted,
            "task_result_ref": task_result_ref,
            "artifact_refs": list(artifact_refs),
            "missing_required_inputs": list(missing_required_inputs),
            "updated_at": time.time(),
        }
    )
    node_status[stage_id] = node_payload
    acceptance_results = dict(next_status.get("acceptance_results") or {})
    acceptance_results[stage_id] = {
        "accepted": accepted,
        "task_result_ref": task_result_ref,
        "artifact_refs": list(artifact_refs),
        "missing_required_inputs": list(missing_required_inputs),
    }
    next_status["node_status"] = node_status
    next_status["acceptance_results"] = acceptance_results
    return next_status


def _manifest_from_payload(payload: dict[str, Any]) -> ContractManifest | None:
    if not payload:
        return None
    return ContractManifest(
        manifest_id=str(payload.get("manifest_id") or ""),
        manifest_kind=str(payload.get("manifest_kind") or ""),
        task_ref=str(payload.get("task_ref") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
        graph_id=str(payload.get("graph_id") or payload.get("graph_ref") or ""),
        graph_ref=str(payload.get("graph_ref") or payload.get("graph_id") or ""),
        global_contracts=tuple(_global_contract_from_payload(item) for item in list(payload.get("global_contracts") or []) if isinstance(item, dict)),
        node_contracts=tuple(_node_contract_from_payload(item) for item in list(payload.get("node_contracts") or []) if isinstance(item, dict)),
        edge_handoff_contracts=tuple(_edge_contract_from_payload(item) for item in list(payload.get("edge_handoff_contracts") or []) if isinstance(item, dict)),
        graph_module_handoff_contracts=tuple(
            _graph_module_contract_from_payload(item)
            for item in list(payload.get("graph_module_handoff_contracts") or [])
            if isinstance(item, dict)
        ),
        runtime_contracts=tuple(_runtime_contract_from_payload(item) for item in list(payload.get("runtime_contracts") or []) if isinstance(item, dict)),
        acceptance_contracts=tuple(_acceptance_contract_from_payload(item) for item in list(payload.get("acceptance_contracts") or []) if isinstance(item, dict)),
        issues=tuple(_compile_issue_from_payload(item) for item in list(payload.get("issues") or []) if isinstance(item, dict)),
        graph_contract_bindings=dict(payload.get("graph_contract_bindings") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _global_contract_from_payload(payload: dict[str, Any]) -> CompiledGlobalContract:
    return CompiledGlobalContract(
        contract_id=str(payload.get("contract_id") or ""),
        title_zh=str(payload.get("title_zh") or ""),
        contract_kind=str(payload.get("contract_kind") or ""),
        source_ref=str(payload.get("source_ref") or ""),
        input_fields=tuple(dict(item) for item in list(payload.get("input_fields") or []) if isinstance(item, dict)),
        output_fields=tuple(dict(item) for item in list(payload.get("output_fields") or []) if isinstance(item, dict)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _node_contract_from_payload(payload: dict[str, Any]) -> CompiledNodeContract:
    return CompiledNodeContract(
        node_id=str(payload.get("node_id") or ""),
        title=str(payload.get("title") or ""),
        node_type=str(payload.get("node_type") or ""),
        task_id=str(payload.get("task_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        contract_refs=tuple(str(item) for item in list(payload.get("contract_refs") or []) if str(item)),
        source_refs=tuple(str(item) for item in list(payload.get("source_refs") or []) if str(item)),
        schema_bindings=dict(payload.get("schema_bindings") or {}),
        execution_bindings=dict(payload.get("execution_bindings") or {}),
        artifact_bindings=dict(payload.get("artifact_bindings") or {}),
        memory_bindings=dict(payload.get("memory_bindings") or {}),
        acceptance_bindings=dict(payload.get("acceptance_bindings") or {}),
        runtime_bindings=dict(payload.get("runtime_bindings") or {}),
        unit_batch_bindings=dict(payload.get("unit_batch_bindings") or {}),
        governance_bindings=dict(payload.get("governance_bindings") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _edge_contract_from_payload(payload: dict[str, Any]) -> CompiledEdgeHandoffContract:
    return CompiledEdgeHandoffContract(
        edge_id=str(payload.get("edge_id") or ""),
        source_node_id=str(payload.get("source_node_id") or ""),
        target_node_id=str(payload.get("target_node_id") or ""),
        message_type=str(payload.get("message_type") or ""),
        contract_refs=tuple(str(item) for item in list(payload.get("contract_refs") or []) if str(item)),
        handoff_policy=str(payload.get("handoff_policy") or "structured_packet"),
        schema_bindings=dict(payload.get("schema_bindings") or {}),
        handoff_bindings=dict(payload.get("handoff_bindings") or {}),
        temporal_bindings=dict(payload.get("temporal_bindings") or {}),
        memory_bindings=dict(payload.get("memory_bindings") or {}),
        artifact_bindings=dict(payload.get("artifact_bindings") or {}),
        governance_bindings=dict(payload.get("governance_bindings") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _graph_module_contract_from_payload(payload: dict[str, Any]) -> CompiledGraphModuleHandoffContract:
    return CompiledGraphModuleHandoffContract(
        plan_id=str(payload.get("plan_id") or ""),
        importing_graph_id=str(payload.get("importing_graph_id") or ""),
        runtime_node_id=str(payload.get("runtime_node_id") or ""),
        unit_id=str(payload.get("unit_id") or ""),
        linked_graph_id=str(payload.get("linked_graph_id") or ""),
        handoff_contract_id=str(payload.get("handoff_contract_id") or ""),
        contract_refs=tuple(str(item) for item in list(payload.get("contract_refs") or []) if str(item)),
        version_ref=str(payload.get("version_ref") or ""),
        input_port_id=str(payload.get("input_port_id") or "input.default") or "input.default",
        output_port_id=str(payload.get("output_port_id") or "output.default") or "output.default",
        handoff_policy=str(payload.get("handoff_policy") or "graph_module_commit_packet"),
        source_refs=tuple(str(item) for item in list(payload.get("source_refs") or []) if str(item)),
        handoff_bindings=dict(payload.get("handoff_bindings") or {}),
        runtime_bindings=dict(payload.get("runtime_bindings") or {}),
        governance_bindings=dict(payload.get("governance_bindings") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _runtime_contract_from_payload(payload: dict[str, Any]) -> CompiledRuntimeContract:
    return CompiledRuntimeContract(
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        allowed_runtime_lanes=tuple(str(item) for item in list(payload.get("allowed_runtime_lanes") or []) if str(item)),
        allowed_operations=tuple(str(item) for item in list(payload.get("allowed_operations") or []) if str(item)),
        allowed_memory_scopes=tuple(str(item) for item in list(payload.get("allowed_memory_scopes") or []) if str(item)),
        validation_state=str(payload.get("validation_state") or "unchecked"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _acceptance_contract_from_payload(payload: dict[str, Any]) -> CompiledAcceptanceContract:
    return CompiledAcceptanceContract(
        contract_id=str(payload.get("contract_id") or ""),
        rule_count=int(payload.get("rule_count") or 0),
        rule_refs=tuple(str(item) for item in list(payload.get("rule_refs") or []) if str(item)),
        source_ref=str(payload.get("source_ref") or ""),
    )


def _compile_issue_from_payload(payload: dict[str, Any]) -> ContractCompileIssue:
    return ContractCompileIssue(
        code=str(payload.get("code") or ""),
        message=str(payload.get("message") or ""),
        severity=str(payload.get("severity") or "error"),
        source_ref=str(payload.get("source_ref") or ""),
        contract_id=str(payload.get("contract_id") or ""),
        node_id=str(payload.get("node_id") or ""),
        edge_id=str(payload.get("edge_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
    )

