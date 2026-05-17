from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class StageExecutionRequest:
    request_id: str
    coordination_run_id: str
    thread_id: str
    root_task_run_id: str
    stage_id: str
    node_id: str
    task_ref: str
    agent_id: str = ""
    agent_profile_id: str = ""
    runtime_lane: str = ""
    explicit_inputs: dict[str, Any] = field(default_factory=dict)
    runtime_assembly: dict[str, Any] = field(default_factory=dict)
    a2a_payload: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    artifact_root: str = ""
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    stream_policy: dict[str, Any] = field(default_factory=dict)
    artifact_targets: tuple[dict[str, Any], ...] = ()
    output_contract_id: str = ""
    expected_outputs: tuple[dict[str, Any], ...] = ()
    working_memory_refs: tuple[str, ...] = ()
    dispatch_context: dict[str, Any] = field(default_factory=dict)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    artifact_context_packet: dict[str, Any] = field(default_factory=dict)
    revision_packet: dict[str, Any] = field(default_factory=dict)
    handoff_packet_refs: tuple[str, ...] = ()
    execution_receipt_policy: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    authority: str = "orchestration.stage_execution_request"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.stage_execution_request":
            raise ValueError("StageExecutionRequest authority must be orchestration.stage_execution_request")
        if not self.coordination_run_id:
            raise ValueError("StageExecutionRequest requires coordination_run_id")
        if not self.thread_id:
            object.__setattr__(self, "thread_id", self.coordination_run_id)
        if not self.stage_id:
            raise ValueError("StageExecutionRequest requires stage_id")
        if not self.task_ref:
            raise ValueError("StageExecutionRequest requires task_ref")
        if not self.request_id:
            dispatch_event_id = str(self.dispatch_context.get("dispatch_event_id") or "").strip()
            dispatch_suffix = _stable_hash(dispatch_event_id or self.explicit_inputs)[:8]
            object.__setattr__(
                self,
                "request_id",
                f"stageexec:{_safe_id(self.coordination_run_id)}:{_safe_id(self.stage_id)}:{dispatch_suffix}",
            )
        if not self.idempotency_key:
            object.__setattr__(
                self,
                "idempotency_key",
                build_stage_execution_idempotency_key(
                    coordination_run_id=self.coordination_run_id,
                    stage_id=self.stage_id,
                    explicit_inputs=self.explicit_inputs,
                    dispatch_context=self.dispatch_context,
                ),
            )
        if not self.message:
            object.__setattr__(self, "message", f"继续执行协调任务阶段：{self.stage_id}。")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_outputs"] = [dict(item) for item in self.expected_outputs]
        payload["artifact_policy"] = dict(self.artifact_policy)
        payload["stream_policy"] = dict(self.stream_policy)
        payload["artifact_targets"] = [dict(item) for item in self.artifact_targets]
        payload["a2a_payload"] = dict(self.a2a_payload)
        payload["runtime_assembly"] = dict(self.runtime_assembly)
        payload["working_memory_refs"] = list(self.working_memory_refs)
        payload["dispatch_context"] = dict(self.dispatch_context)
        payload["memory_snapshot"] = dict(self.memory_snapshot)
        payload["artifact_context_packet"] = dict(self.artifact_context_packet)
        payload["revision_packet"] = dict(self.revision_packet)
        payload["handoff_packet_refs"] = list(self.handoff_packet_refs)
        payload["execution_receipt_policy"] = dict(self.execution_receipt_policy)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StageExecutionRequest":
        return cls(
            request_id=str(payload.get("request_id") or ""),
            coordination_run_id=str(payload.get("coordination_run_id") or ""),
            thread_id=str(payload.get("thread_id") or payload.get("coordination_run_id") or ""),
            root_task_run_id=str(payload.get("root_task_run_id") or ""),
            stage_id=str(payload.get("stage_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            task_ref=str(payload.get("task_ref") or payload.get("next_task_ref") or ""),
            agent_id=str(payload.get("agent_id") or ""),
            agent_profile_id=str(payload.get("agent_profile_id") or ""),
            runtime_lane=str(payload.get("runtime_lane") or ""),
            explicit_inputs=dict(payload.get("explicit_inputs") or {}),
            runtime_assembly=dict(payload.get("runtime_assembly") or {}),
            a2a_payload=dict(payload.get("a2a_payload") or {}),
            message=str(payload.get("message") or ""),
            artifact_root=str(payload.get("artifact_root") or ""),
            artifact_policy=dict(payload.get("artifact_policy") or {}),
            stream_policy=dict(payload.get("stream_policy") or {}),
            artifact_targets=tuple(dict(item) for item in list(payload.get("artifact_targets") or []) if isinstance(item, dict)),
            output_contract_id=str(payload.get("output_contract_id") or ""),
            expected_outputs=tuple(dict(item) for item in list(payload.get("expected_outputs") or []) if isinstance(item, dict)),
            working_memory_refs=tuple(str(item).strip() for item in list(payload.get("working_memory_refs") or []) if str(item).strip()),
            dispatch_context=dict(payload.get("dispatch_context") or {}),
            memory_snapshot=dict(payload.get("memory_snapshot") or {}),
            artifact_context_packet=dict(payload.get("artifact_context_packet") or {}),
            revision_packet=dict(payload.get("revision_packet") or {}),
            handoff_packet_refs=tuple(str(item).strip() for item in list(payload.get("handoff_packet_refs") or []) if str(item).strip()),
            execution_receipt_policy=dict(payload.get("execution_receipt_policy") or {}),
            idempotency_key=str(payload.get("idempotency_key") or ""),
        )


@dataclass(frozen=True, slots=True)
class TaskResultReadyEvent:
    event_type: str
    coordination_run_id: str
    task_run_id: str
    stage_id: str
    task_ref: str
    task_result_ref: str = ""
    artifact_refs: tuple[str, ...] = ()
    accepted: bool = False
    agent_run_result_ref: str = ""
    request_id: str = ""
    dispatch_event_id: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.task_result_ready_event"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.task_result_ready_event":
            raise ValueError("TaskResultReadyEvent authority must be orchestration.task_result_ready_event")
        if self.event_type != "task_result_ready":
            raise ValueError("TaskResultReadyEvent event_type must be task_result_ready")
        if not self.coordination_run_id:
            raise ValueError("TaskResultReadyEvent requires coordination_run_id")
        if not self.task_run_id:
            raise ValueError("TaskResultReadyEvent requires task_run_id")
        if not self.stage_id:
            raise ValueError("TaskResultReadyEvent requires stage_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        return payload


def build_stage_execution_idempotency_key(
    *,
    coordination_run_id: str,
    stage_id: str,
    explicit_inputs: dict[str, Any],
    dispatch_context: dict[str, Any] | None = None,
) -> str:
    context = dict(dispatch_context or {})
    dispatch_event_id = str(context.get("dispatch_event_id") or "").strip()
    if dispatch_event_id:
        return f"{coordination_run_id}:{stage_id}:dispatch:{dispatch_event_id}"
    clock_seq = str(context.get("clock_seq") or "").strip()
    scope_path = context.get("scope_path") or []
    if clock_seq:
        return f"{coordination_run_id}:{stage_id}:clock:{clock_seq}:{_stable_hash(scope_path)}"
    return f"{coordination_run_id}:{stage_id}:{_stable_hash(explicit_inputs)}"


def _stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:120]
