from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_BINDING_SOURCES = {
    "current_output",
    "latest_output",
    "latest_output_by_contract",
    "inherited_input",
    "literal",
    "collect",
    "stage_output",
}


@dataclass(frozen=True, slots=True)
class CoordinationStageContract:
    stage_id: str
    task_ref: str
    node_id: str = ""
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    input_bindings: tuple[dict[str, Any], ...] = ()
    output_mappings: tuple[dict[str, Any], ...] = ()
    gate_policy: str = ""
    on_success: str = "advance"
    on_failure: str = "fail_closed"
    retry_policy: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    runtime_lane: str = ""
    role: str = ""
    title: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    projection_id: str = ""
    node_type: str = ""
    memory_read_policy: dict[str, Any] = field(default_factory=dict)
    memory_writeback_policy: dict[str, Any] = field(default_factory=dict)
    dynamic_memory_read_policy: dict[str, Any] = field(default_factory=dict)
    review_gate_policy: dict[str, Any] = field(default_factory=dict)
    human_gate_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    stream_policy: dict[str, Any] = field(default_factory=dict)
    artifact_context_policy: dict[str, Any] = field(default_factory=dict)
    revision_context_policy: dict[str, Any] = field(default_factory=dict)
    quality_retry_policy: dict[str, Any] = field(default_factory=dict)
    artifact_targets: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "task_ref": self.task_ref,
            "node_id": self.node_id,
            "required_inputs": list(self.required_inputs),
            "optional_inputs": list(self.optional_inputs),
            "input_bindings": [dict(item) for item in self.input_bindings],
            "output_mappings": [dict(item) for item in self.output_mappings],
            "gate_policy": self.gate_policy,
            "on_success": self.on_success,
            "on_failure": self.on_failure,
            "retry_policy": dict(self.retry_policy),
            "agent_id": self.agent_id,
            "runtime_lane": self.runtime_lane,
            "role": self.role,
            "title": self.title,
            "input_contract_id": self.input_contract_id,
            "output_contract_id": self.output_contract_id,
            "projection_id": self.projection_id,
            "node_type": self.node_type,
            "memory_read_policy": dict(self.memory_read_policy),
            "memory_writeback_policy": dict(self.memory_writeback_policy),
            "dynamic_memory_read_policy": dict(self.dynamic_memory_read_policy),
            "review_gate_policy": dict(self.review_gate_policy),
            "human_gate_policy": dict(self.human_gate_policy),
            "artifact_policy": dict(self.artifact_policy),
            "stream_policy": dict(self.stream_policy),
            "artifact_context_policy": dict(self.artifact_context_policy),
            "revision_context_policy": dict(self.revision_context_policy),
            "quality_retry_policy": dict(self.quality_retry_policy),
            "artifact_targets": [dict(item) for item in self.artifact_targets],
        }


@dataclass(frozen=True, slots=True)
class CoordinationContinuationPolicy:
    mode: str = "topology_driven"
    auto_continue: bool = True
    max_auto_steps: int = 100
    stop_on_missing_required_input: bool = True
    terminal_policy: str = "terminal_node_or_stop_condition"
    human_gate_mode: str = "manual_required"
    human_gate_stage_ids: tuple[str, ...] = ()
    retry_budget: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "auto_continue": self.auto_continue,
            "max_auto_steps": self.max_auto_steps,
            "stop_on_missing_required_input": self.stop_on_missing_required_input,
            "terminal_policy": self.terminal_policy,
            "human_gate_mode": self.human_gate_mode,
            "human_gate_stage_ids": list(self.human_gate_stage_ids),
            "retry_budget": dict(self.retry_budget),
        }

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> "CoordinationContinuationPolicy":
        raw = dict(metadata.get("continuation_policy") or {})
        retry_budget = {
            str(key): int(value)
            for key, value in dict(raw.get("retry_budget") or {}).items()
            if str(key)
        }
        return cls(
            mode=str(raw.get("mode") or "topology_driven"),
            auto_continue=bool(raw.get("auto_continue", True) is True),
            max_auto_steps=max(1, int(raw.get("max_auto_steps") or 100)),
            stop_on_missing_required_input=bool(raw.get("stop_on_missing_required_input", True) is True),
            terminal_policy=str(raw.get("terminal_policy") or "terminal_node_or_stop_condition"),
            human_gate_mode=str(raw.get("human_gate_mode") or raw.get("human_gate_default_mode") or "manual_required"),
            human_gate_stage_ids=tuple(str(item) for item in list(raw.get("human_gate_stage_ids") or []) if str(item)),
            retry_budget=retry_budget,
        )


def parse_stage_contracts(
    *,
    coordination_task: Any,
    topology_nodes: list[dict[str, Any]] | None = None,
    topology_edges: list[dict[str, Any]] | None = None,
) -> tuple[CoordinationStageContract, ...]:
    metadata = dict(getattr(coordination_task, "metadata", {}) or {})
    raw_contracts = metadata.get("stage_contracts")
    if not isinstance(raw_contracts, list):
        return derive_stage_contracts_from_graph(
            coordination_task=coordination_task,
            topology_nodes=topology_nodes,
            topology_edges=topology_edges,
        )
    node_by_stage = _node_by_stage_id(topology_nodes or [])
    contracts: list[CoordinationStageContract] = []
    for raw in raw_contracts:
        if not isinstance(raw, dict):
            continue
        stage_id = str(raw.get("stage_id") or "").strip()
        if not stage_id:
            continue
        node = node_by_stage.get(stage_id, {})
        task_ref = str(raw.get("task_ref") or node.get("task_ref") or node.get("task_id") or "").strip()
        contracts.append(
            CoordinationStageContract(
                stage_id=stage_id,
                task_ref=task_ref,
                node_id=str(raw.get("node_id") or node.get("node_id") or "").strip(),
                required_inputs=tuple(str(item) for item in list(raw.get("required_inputs") or []) if str(item)),
                optional_inputs=tuple(str(item) for item in list(raw.get("optional_inputs") or []) if str(item)),
                input_bindings=tuple(dict(item) for item in list(raw.get("input_bindings") or []) if isinstance(item, dict)),
                output_mappings=tuple(dict(item) for item in list(raw.get("output_mappings") or []) if isinstance(item, dict)),
                gate_policy=str(raw.get("gate_policy") or "").strip(),
                on_success=str(raw.get("on_success") or "advance").strip(),
                on_failure=str(raw.get("on_failure") or "fail_closed").strip(),
                retry_policy=dict(raw.get("retry_policy") or {}),
                agent_id=str(raw.get("agent_id") or node.get("agent_id") or "").strip(),
                runtime_lane=str(raw.get("runtime_lane") or node.get("runtime_lane") or node.get("lane") or "").strip(),
                role=str(raw.get("role") or node.get("role") or "").strip(),
                title=str(raw.get("title") or node.get("title") or stage_id).strip(),
                input_contract_id=str(raw.get("input_contract_id") or node.get("input_contract_id") or "").strip(),
                output_contract_id=str(raw.get("output_contract_id") or node.get("output_contract_id") or node.get("node_contract_id") or "").strip(),
                projection_id=str(raw.get("projection_id") or node.get("projection_id") or "").strip(),
                node_type=str(raw.get("node_type") or node.get("node_type") or "").strip(),
                memory_read_policy=dict(raw.get("memory_read_policy") or node.get("memory_read_policy") or {}),
                memory_writeback_policy=dict(raw.get("memory_writeback_policy") or node.get("memory_writeback_policy") or {}),
                dynamic_memory_read_policy=dict(raw.get("dynamic_memory_read_policy") or node.get("dynamic_memory_read_policy") or {}),
                review_gate_policy=dict(raw.get("review_gate_policy") or node.get("review_gate_policy") or {}),
                human_gate_policy=dict(raw.get("human_gate_policy") or node.get("human_gate_policy") or {}),
                artifact_policy=_artifact_policy_from_node({**node, **raw}),
                stream_policy=dict(raw.get("stream_policy") or node.get("stream_policy") or {}),
                artifact_context_policy=dict(raw.get("artifact_context_policy") or node.get("artifact_context_policy") or {}),
                revision_context_policy=dict(raw.get("revision_context_policy") or node.get("revision_context_policy") or {}),
                quality_retry_policy=dict(raw.get("quality_retry_policy") or node.get("quality_retry_policy") or {}),
                artifact_targets=tuple(_artifact_targets_from_node({**node, **raw})),
            )
        )
    return tuple(contracts)


def derive_stage_contracts_from_graph(
    *,
    coordination_task: Any,
    topology_nodes: list[dict[str, Any]] | None = None,
    topology_edges: list[dict[str, Any]] | None = None,
) -> tuple[CoordinationStageContract, ...]:
    """Build continuation contracts from TaskGraph nodes when no explicit stage contracts exist."""
    nodes = _effective_graph_nodes(coordination_task=coordination_task, topology_nodes=topology_nodes)
    if not nodes:
        return ()
    edges = _effective_graph_edges(coordination_task=coordination_task, topology_edges=topology_edges)
    node_by_id = {
        str(node.get("node_id") or node.get("id") or "").strip(): dict(node)
        for node in nodes
        if str(node.get("node_id") or node.get("id") or "").strip()
    }
    node_order = {node_id: index for index, node_id in enumerate(node_by_id.keys())}
    incoming_by_target: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = _edge_source(edge)
        target = _edge_target(edge)
        if _is_feedback_edge(edge) or _is_backward_edge(source=source, target=target, node_order=node_order):
            continue
        if source in node_by_id and target in node_by_id:
            incoming_by_target.setdefault(target, []).append(dict(edge))

    contracts: list[CoordinationStageContract] = []
    for node in nodes:
        node_id = str(node.get("node_id") or node.get("id") or "").strip()
        if not node_id:
            continue
        task_ref = str(node.get("task_id") or node.get("task_ref") or node.get("subtask_ref") or "").strip()
        if not task_ref:
            continue
        input_bindings: list[dict[str, Any]] = []
        required_inputs: list[str] = []
        for edge in incoming_by_target.get(node_id, []):
            source = _edge_source(edge)
            output_key = _stage_output_key(source, node_by_id.get(source, {}))
            input_key = _stage_input_key(source, edge)
            input_bindings.append(
                {
                    "source": "stage_output",
                    "source_stage_id": source,
                    "output_key": output_key,
                    "input_key": input_key,
                    "required": True,
                }
            )
            required_inputs.append(input_key)
        output_key = _stage_output_key(node_id, node)
        output_mappings = [{"output_key": output_key, "required": True}]
        contracts.append(
            CoordinationStageContract(
                stage_id=node_id,
                task_ref=task_ref,
                node_id=node_id,
                required_inputs=tuple(dict.fromkeys(required_inputs)),
                input_bindings=tuple(input_bindings),
                output_mappings=tuple(output_mappings),
                gate_policy=_derived_gate_policy(node),
                on_success="advance",
                on_failure=_derived_failure_policy(node),
                retry_policy=dict(node.get("retry_policy") or dict(node.get("loop_policy") or {})),
                agent_id=str(node.get("agent_id") or "").strip(),
                runtime_lane=str(node.get("runtime_lane") or node.get("lane") or "").strip(),
                role=str(node.get("role") or node.get("work_posture") or "").strip(),
                title=str(node.get("title") or node_id).strip(),
                input_contract_id=str(node.get("input_contract_id") or "").strip(),
                output_contract_id=str(node.get("output_contract_id") or node.get("node_contract_id") or "").strip(),
                projection_id=str(node.get("projection_id") or "").strip(),
                node_type=str(node.get("node_type") or "").strip(),
                memory_read_policy=dict(node.get("memory_read_policy") or {}),
                memory_writeback_policy=dict(node.get("memory_writeback_policy") or {}),
                dynamic_memory_read_policy=dict(node.get("dynamic_memory_read_policy") or {}),
                review_gate_policy=dict(node.get("review_gate_policy") or {}),
                human_gate_policy=dict(node.get("human_gate_policy") or {}),
                artifact_policy=_artifact_policy_from_node(node),
                stream_policy=dict(node.get("stream_policy") or {}),
                artifact_context_policy=dict(node.get("artifact_context_policy") or {}),
                revision_context_policy=dict(node.get("revision_context_policy") or {}),
                quality_retry_policy=dict(node.get("quality_retry_policy") or {}),
                artifact_targets=tuple(_artifact_targets_from_node(node)),
            )
        )
    return tuple(contracts)


def validate_stage_contracts(
    *,
    coordination_task: Any,
    contracts: tuple[CoordinationStageContract, ...],
    stage_sequence: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    stage_ids = {str(item.get("stage_id") or "") for item in list(stage_sequence or []) if isinstance(item, dict)}
    task_refs = {
        str(item)
        for item in (
            list(getattr(coordination_task, "subtask_refs", ()) or [])
            + [str(dict(getattr(coordination_task, "metadata", {}) or {}).get("task_id") or "")]
        )
        if str(item)
    }
    for contract in contracts:
        if contract.stage_id in seen:
            issues.append(_issue("duplicate_stage_id", f"duplicate stage contract: {contract.stage_id}", contract.stage_id))
        seen.add(contract.stage_id)
        if stage_ids and contract.stage_id not in stage_ids:
            issues.append(_issue("stage_not_declared", f"stage contract not declared in stage_sequence: {contract.stage_id}", contract.stage_id))
        if not contract.task_ref:
            issues.append(_issue("missing_task_ref", "stage contract requires task_ref", contract.stage_id))
        elif task_refs and contract.task_ref not in task_refs:
            issues.append(_issue("task_ref_not_reachable", f"task_ref is not in coordination task refs: {contract.task_ref}", contract.stage_id))
        for binding in contract.input_bindings:
            source = str(binding.get("source") or "").strip()
            if source not in ALLOWED_BINDING_SOURCES:
                issues.append(_issue("invalid_binding_source", f"invalid binding source: {source}", contract.stage_id))
            if binding.get("required") is True and not str(binding.get("input_key") or "").strip():
                issues.append(_issue("missing_binding_input_key", "required input binding needs input_key", contract.stage_id))
        for output in contract.output_mappings:
            if output.get("required") is True and not str(output.get("output_key") or "").strip():
                issues.append(_issue("missing_output_key", "required output mapping needs output_key", contract.stage_id))
    return issues


def contract_by_stage(contracts: tuple[CoordinationStageContract, ...]) -> dict[str, CoordinationStageContract]:
    return {contract.stage_id: contract for contract in contracts}


def _node_by_stage_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        stage_id = str(node.get("stage_id") or node.get("node_id") or "").strip()
        if stage_id:
            result[stage_id] = dict(node)
    return result


def _effective_graph_nodes(
    *,
    coordination_task: Any,
    topology_nodes: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    task_nodes = [dict(item) for item in list(getattr(coordination_task, "graph_nodes", ()) or []) if isinstance(item, dict)]
    template_nodes = [dict(item) for item in list(topology_nodes or []) if isinstance(item, dict)]
    if not task_nodes:
        return template_nodes
    if not template_nodes:
        return task_nodes
    by_id = {
        str(item.get("node_id") or item.get("id") or "").strip(): dict(item)
        for item in template_nodes
        if str(item.get("node_id") or item.get("id") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for node in task_nodes:
        node_id = str(node.get("node_id") or node.get("id") or "").strip()
        template_node = by_id.get(node_id, {})
        merged.append({**template_node, **node})
    known = {str(item.get("node_id") or item.get("id") or "").strip() for item in merged}
    merged.extend(item for item in template_nodes if str(item.get("node_id") or item.get("id") or "").strip() not in known)
    return merged


def _effective_graph_edges(
    *,
    coordination_task: Any,
    topology_edges: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    task_edges = [dict(item) for item in list(getattr(coordination_task, "graph_edges", ()) or []) if isinstance(item, dict)]
    return task_edges or [dict(item) for item in list(topology_edges or []) if isinstance(item, dict)]


def _edge_source(edge: dict[str, Any]) -> str:
    return str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()


def _edge_target(edge: dict[str, Any]) -> str:
    return str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()


def _is_feedback_edge(edge: dict[str, Any]) -> bool:
    metadata = dict(edge.get("metadata") or {}) if isinstance(edge.get("metadata"), dict) else {}
    edge_type = str(edge.get("edge_type") or edge.get("mode") or edge.get("policy") or "").strip()
    dependency_role = str(edge.get("dependency_role") or metadata.get("dependency_role") or "").strip()
    loop_role = str(edge.get("loop_role") or metadata.get("loop_role") or "").strip()
    return edge_type in {"review_feedback", "repair_feedback", "conditional_feedback"} or dependency_role in {
        "feedback",
        "conditional_feedback",
        "repair_feedback",
        "non_blocking_feedback",
    } or loop_role in {"repair", "feedback"}


def _is_backward_edge(*, source: str, target: str, node_order: dict[str, int]) -> bool:
    if source not in node_order or target not in node_order:
        return False
    return node_order[source] > node_order[target]


def _contract_ref_from_node(node: dict[str, Any]) -> str:
    metadata = dict(node.get("metadata") or {}) if isinstance(node.get("metadata"), dict) else {}
    return str(
        node.get("output_contract_id")
        or node.get("node_contract_id")
        or node.get("contract_id")
        or metadata.get("output_contract_id")
        or metadata.get("node_contract_id")
        or ""
    ).strip()


def _stage_output_key(node_id: str, node: dict[str, Any]) -> str:
    contract_ref = _contract_ref_from_node(node)
    if contract_ref:
        return f"{contract_ref}:artifact_refs"
    return f"{node_id}:artifact_refs"


def _stage_input_key(source_node_id: str, edge: dict[str, Any]) -> str:
    contract_ref = str(edge.get("payload_contract_id") or edge.get("contract_id") or "").strip()
    if contract_ref:
        return f"{contract_ref}:artifact_refs"
    return f"{source_node_id}:artifact_refs"


def _artifact_policy_from_node(node: dict[str, Any]) -> dict[str, Any]:
    policy = dict(node.get("artifact_policy") or {})
    target = str(node.get("artifact_target") or node.get("output_path") or policy.get("artifact_target") or "").strip()
    if target:
        policy.setdefault("enabled", True)
        policy.setdefault("required", True)
        policy.setdefault("source", "task_graph_node")
        policy["artifact_target"] = target
        policy.setdefault(
            "artifacts",
            [
                {
                    "path": target,
                    "required": True,
                    "content_source": "final_content",
                    "fallback_to_full_content": True,
                }
            ],
        )
    return policy


def _artifact_targets_from_node(node: dict[str, Any]) -> list[dict[str, Any]]:
    targets = [dict(item) for item in list(node.get("artifact_targets") or []) if isinstance(item, dict)]
    policy = _artifact_policy_from_node(node)
    target = str(policy.get("artifact_target") or "").strip()
    if target and not any(str(item.get("path") or "") == target for item in targets):
        targets.append({"path": target, "required": bool(policy.get("required", True)), "source": "task_graph_node"})
    return targets


def _derived_gate_policy(node: dict[str, Any]) -> str:
    node_type = str(node.get("node_type") or "").strip()
    review_gate = node.get("review_gate_policy")
    if node_type == "review_gate" or (isinstance(review_gate, dict) and review_gate):
        return "review_gate"
    return ""


def _derived_failure_policy(node: dict[str, Any]) -> str:
    loop_policy = dict(node.get("loop_policy") or {}) if isinstance(node.get("loop_policy"), dict) else {}
    if loop_policy:
        return "retry_once" if int(loop_policy.get("max_attempts") or 0) > 0 else "fail_closed"
    return "fail_closed"


def _issue(code: str, message: str, stage_id: str) -> dict[str, str]:
    return {"code": code, "message": message, "stage_id": stage_id, "severity": "error"}
