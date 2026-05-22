from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GraphModuleStartResult:
    imported_task_run_id: str
    imported_coordination_run_id: str
    linked_graph_id: str
    graph_module_runtime_handle_id: str = ""
    imported_stage_execution_request: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.subruntime.graph_module_start_result"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["imported_stage_execution_request"] = dict(self.imported_stage_execution_request)
        return payload


@dataclass(frozen=True, slots=True)
class GraphModuleResultPacketCandidate:
    imported_task_run_id: str
    packet: dict[str, Any]
    packet_ref: str
    task_result: dict[str, Any]
    explicit_inputs: dict[str, Any]
    artifact_root: str
    event: dict[str, Any]
    authority: str = "runtime.subruntime.graph_module_result_packet_candidate"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_run_id"] = self.imported_task_run_id
        payload["packet"] = dict(self.packet)
        payload["task_result"] = dict(self.task_result)
        payload["explicit_inputs"] = dict(self.explicit_inputs)
        payload["event"] = dict(self.event)
        return payload
