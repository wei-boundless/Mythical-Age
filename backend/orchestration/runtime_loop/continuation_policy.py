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
        }


@dataclass(frozen=True, slots=True)
class CoordinationContinuationPolicy:
    mode: str = "topology_driven"
    auto_continue: bool = True
    max_auto_steps: int = 100
    stop_on_missing_required_input: bool = True
    terminal_policy: str = "terminal_node_or_stop_condition"
    human_gate_stage_ids: tuple[str, ...] = ()
    retry_budget: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "auto_continue": self.auto_continue,
            "max_auto_steps": self.max_auto_steps,
            "stop_on_missing_required_input": self.stop_on_missing_required_input,
            "terminal_policy": self.terminal_policy,
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
            human_gate_stage_ids=tuple(str(item) for item in list(raw.get("human_gate_stage_ids") or []) if str(item)),
            retry_budget=retry_budget,
        )


def parse_stage_contracts(
    *,
    coordination_task: Any,
    topology_nodes: list[dict[str, Any]] | None = None,
) -> tuple[CoordinationStageContract, ...]:
    metadata = dict(getattr(coordination_task, "metadata", {}) or {})
    raw_contracts = metadata.get("stage_contracts")
    if not isinstance(raw_contracts, list):
        return ()
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


def _issue(code: str, message: str, stage_id: str) -> dict[str, str]:
    return {"code": code, "message": message, "stage_id": stage_id, "severity": "error"}
