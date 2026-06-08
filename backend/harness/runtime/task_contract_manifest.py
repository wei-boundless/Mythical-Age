from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskContractManifest:
    manifest_id: str
    invocation_kind: str
    source_ref: str
    contract_hash: str
    planning_protocol_hash: str
    contract_kind: str = "task_contract"
    task_run_goal: str = ""
    completion_criteria_count: int = 0
    model_visible_contract: dict[str, Any] = field(default_factory=dict)
    planning_protocol: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.task_contract_manifest"

    def to_model_visible_payload(self) -> dict[str, Any]:
        return {
            "task_contract": _deepcopy_json_dict(self.model_visible_contract),
            "planning_protocol": _deepcopy_json_dict(self.planning_protocol),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_visible_contract"] = _deepcopy_json_dict(self.model_visible_contract)
        payload["planning_protocol"] = _deepcopy_json_dict(self.planning_protocol)
        return payload


def build_task_contract_manifest(
    *,
    invocation_kind: str,
    model_visible_contract: dict[str, Any],
    planning_protocol: dict[str, Any],
    source_ref: str,
) -> TaskContractManifest:
    contract_payload = _deepcopy_json_dict(model_visible_contract)
    planning_payload = _deepcopy_json_dict(planning_protocol)
    contract_hash = _stable_json_hash(contract_payload)
    planning_hash = _stable_json_hash(planning_payload)
    completion_criteria = list(contract_payload.get("completion_criteria") or [])
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "source_ref": str(source_ref or ""),
        "contract_hash": contract_hash,
        "planning_protocol_hash": planning_hash,
    }
    return TaskContractManifest(
        manifest_id="taskcontract:" + _digest(seed),
        invocation_kind=str(invocation_kind or ""),
        source_ref=str(source_ref or ""),
        contract_hash=contract_hash,
        planning_protocol_hash=planning_hash,
        contract_kind=_contract_kind(contract_payload),
        task_run_goal=str(contract_payload.get("task_run_goal") or ""),
        completion_criteria_count=len(completion_criteria),
        model_visible_contract=contract_payload,
        planning_protocol=planning_payload,
    )


def _contract_kind(contract_payload: dict[str, Any]) -> str:
    authority = str(contract_payload.get("authority") or "")
    if "graph_node_contract" in authority or contract_payload.get("graph_node_context"):
        return "graph_node_contract"
    return "task_contract"


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _deepcopy_json_dict(value: dict[str, Any]) -> dict[str, Any]:
    return dict(_json_stable(dict(value or {})))
