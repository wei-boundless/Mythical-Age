from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class StageExecutionReceipt:
    receipt_id: str
    request_id: str
    dispatch_event_id: str
    result_event_id: str
    clock_seq: int
    scope_path: tuple[str, ...]
    stage_id: str
    node_id: str
    status: str
    accepted: bool
    produced_artifact_refs: tuple[str, ...] = ()
    produced_trace_refs: tuple[str, ...] = ()
    memory_write_candidate_refs: tuple[str, ...] = ()
    memory_commit_refs: tuple[str, ...] = ()
    validation_result: dict[str, Any] = field(default_factory=dict)
    effective_from_clock_seq: int = 0
    effective_scope_path: tuple[str, ...] = ()
    created_at: float = 0.0
    authority: str = "task_graph.stage_execution_receipt"

    def __post_init__(self) -> None:
        if self.authority != "task_graph.stage_execution_receipt":
            raise ValueError("StageExecutionReceipt authority must be task_graph.stage_execution_receipt")
        if not self.receipt_id:
            raise ValueError("StageExecutionReceipt requires receipt_id")
        if not self.stage_id:
            raise ValueError("StageExecutionReceipt requires stage_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_path"] = list(self.scope_path)
        payload["produced_artifact_refs"] = list(self.produced_artifact_refs)
        payload["produced_trace_refs"] = list(self.produced_trace_refs)
        payload["memory_write_candidate_refs"] = list(self.memory_write_candidate_refs)
        payload["memory_commit_refs"] = list(self.memory_commit_refs)
        payload["effective_scope_path"] = list(self.effective_scope_path)
        payload["validation_result"] = dict(self.validation_result)
        return payload


def build_stage_execution_receipt(
    *,
    request_payload: dict[str, Any],
    result_event: dict[str, Any],
    stage_id: str,
    node_id: str,
    accepted: bool,
    artifact_refs: list[str] | tuple[str, ...],
    trace_refs: list[str] | tuple[str, ...] = (),
    memory_write_candidate_refs: list[str] | tuple[str, ...] = (),
    memory_commit_refs: list[str] | tuple[str, ...] = (),
    validation_result: dict[str, Any] | None = None,
) -> StageExecutionReceipt:
    dispatch_context = dict(request_payload.get("dispatch_context") or {})
    clock_seq = int(result_event.get("clock_seq") or dispatch_context.get("clock_seq") or 0)
    scope_path = tuple(
        str(item)
        for item in list(result_event.get("scope_path") or dispatch_context.get("scope_path") or ["run"])
        if str(item)
    )
    receipt_seed = {
        "request_id": str(request_payload.get("request_id") or ""),
        "result_event_id": str(result_event.get("event_id") or ""),
        "stage_id": stage_id,
        "accepted": bool(accepted),
        "artifact_refs": list(artifact_refs or []),
        "memory_write_candidate_refs": list(memory_write_candidate_refs or []),
        "memory_commit_refs": list(memory_commit_refs or []),
    }
    return StageExecutionReceipt(
        receipt_id=f"stagereceipt:{_short_hash(receipt_seed)}",
        request_id=str(request_payload.get("request_id") or ""),
        dispatch_event_id=str(dispatch_context.get("dispatch_event_id") or ""),
        result_event_id=str(result_event.get("event_id") or ""),
        clock_seq=clock_seq,
        scope_path=scope_path or ("run",),
        stage_id=stage_id,
        node_id=node_id or stage_id,
        status="accepted" if accepted else "rejected",
        accepted=bool(accepted),
        produced_artifact_refs=tuple(str(item) for item in list(artifact_refs or []) if str(item)),
        produced_trace_refs=tuple(str(item) for item in list(trace_refs or []) if str(item)),
        memory_write_candidate_refs=tuple(str(item) for item in list(memory_write_candidate_refs or []) if str(item)),
        memory_commit_refs=tuple(str(item) for item in list(memory_commit_refs or []) if str(item)),
        validation_result=dict(validation_result or {}),
        effective_from_clock_seq=clock_seq if accepted else 0,
        effective_scope_path=scope_path if accepted else (),
        created_at=time.time(),
    )


def _short_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
