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
    a2a_payload: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    artifact_root: str = ""
    expected_outputs: tuple[dict[str, Any], ...] = ()
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
            object.__setattr__(
                self,
                "request_id",
                f"stageexec:{_safe_id(self.coordination_run_id)}:{_safe_id(self.stage_id)}:{_stable_hash(self.explicit_inputs)[:8]}",
            )
        if not self.idempotency_key:
            object.__setattr__(
                self,
                "idempotency_key",
                build_stage_execution_idempotency_key(
                    coordination_run_id=self.coordination_run_id,
                    stage_id=self.stage_id,
                    explicit_inputs=self.explicit_inputs,
                ),
            )
        if not self.message:
            object.__setattr__(self, "message", f"继续执行协调任务阶段：{self.stage_id}。")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_outputs"] = [dict(item) for item in self.expected_outputs]
        payload["a2a_payload"] = dict(self.a2a_payload)
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
            a2a_payload=dict(payload.get("a2a_payload") or {}),
            message=str(payload.get("message") or ""),
            artifact_root=str(payload.get("artifact_root") or ""),
            expected_outputs=tuple(dict(item) for item in list(payload.get("expected_outputs") or []) if isinstance(item, dict)),
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
) -> str:
    return f"{coordination_run_id}:{stage_id}:{_stable_hash(explicit_inputs)}"


def _stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))[:120]
