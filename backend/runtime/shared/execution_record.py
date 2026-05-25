from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from capability_system import OperationDescriptor

from .action_request import RuntimeActionRequest


ReplayPolicy = Literal[
    "replay_read",
    "reuse_completed_result",
    "deny_auto_replay",
    "manual_recovery_required",
]

OperationExecutionStatus = Literal[
    "created",
    "dispatched",
    "completed",
    "failed",
    "replay_suppressed",
    "reused_completed_result",
]

SideEffectState = Literal["not_started", "in_progress", "committed", "unknown"]


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    execution_id: str
    request_ref: str
    status: OperationExecutionStatus
    replay_decision: ReplayPolicy
    reused_previous_result: bool = False
    result_ref: str = ""
    error: str = ""
    authority: str = "orchestration.execution_receipt"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.execution_receipt":
            raise ValueError("ExecutionReceipt authority must be orchestration.execution_receipt")
        if not self.execution_id:
            raise ValueError("ExecutionReceipt requires execution_id")
        if not self.request_ref:
            raise ValueError("ExecutionReceipt requires request_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OperationExecutionRecord:
    execution_id: str
    task_run_id: str
    step_id: str
    request_ref: str
    directive_ref: str
    operation_id: str
    executor_type: str
    request_fingerprint: str
    idempotency_token: str
    replay_policy: ReplayPolicy
    status: OperationExecutionStatus = "created"
    side_effect_state: SideEffectState = "not_started"
    result_ref: str = ""
    result_payload: dict[str, Any] = field(default_factory=dict)
    attempt_count: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.operation_execution_record"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.operation_execution_record":
            raise ValueError("OperationExecutionRecord authority must be orchestration.operation_execution_record")
        if not self.execution_id:
            raise ValueError("OperationExecutionRecord requires execution_id")
        if not self.task_run_id:
            raise ValueError("OperationExecutionRecord requires task_run_id")
        if not self.request_ref:
            raise ValueError("OperationExecutionRecord requires request_ref")
        if not self.operation_id:
            raise ValueError("OperationExecutionRecord requires operation_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeExecutionStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.execution_dir = self.root_dir / "executions"
        self.execution_dir.mkdir(parents=True, exist_ok=True)

    def create_record(
        self,
        *,
        task_run_id: str,
        step_id: str,
        action_request: RuntimeActionRequest,
        directive_ref: str,
        operation_id: str,
        executor_type: str,
        replay_policy: ReplayPolicy,
        request_fingerprint: str,
        idempotency_token: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> OperationExecutionRecord:
        now = time.time()
        record = OperationExecutionRecord(
            execution_id=f"rtexec:{task_run_id}:{uuid.uuid4().hex[:8]}",
            task_run_id=task_run_id,
            step_id=str(step_id or ""),
            request_ref=action_request.request_id,
            directive_ref=str(directive_ref or ""),
            operation_id=str(operation_id or ""),
            executor_type=str(executor_type or ""),
            request_fingerprint=str(request_fingerprint or ""),
            idempotency_token=str(idempotency_token or ""),
            replay_policy=replay_policy,
            status="created",
            side_effect_state="not_started",
            created_at=now,
            updated_at=now,
            diagnostics=dict(diagnostics or {}),
        )
        self.upsert(record)
        return record

    def upsert(self, record: OperationExecutionRecord) -> OperationExecutionRecord:
        payload = self._load_payload(record.task_run_id)
        records = [OperationExecutionRecord(**item) for item in list(payload.get("records") or [])]
        replaced = False
        serialized = record.to_dict()
        for index, current in enumerate(records):
            if current.execution_id != record.execution_id:
                continue
            records[index] = record
            replaced = True
            break
        if not replaced:
            records.append(record)
        self._write_payload(
            record.task_run_id,
            {
                "task_run_id": record.task_run_id,
                "updated_at": time.time(),
                "records": [item.to_dict() for item in records],
                "latest_execution_id": serialized["execution_id"],
            },
        )
        return record

    def get(self, task_run_id: str, execution_id: str) -> OperationExecutionRecord | None:
        for item in self.list_task_run_records(task_run_id):
            if item.execution_id == execution_id:
                return item
        return None

    def list_task_run_records(self, task_run_id: str) -> list[OperationExecutionRecord]:
        payload = self._load_payload(task_run_id)
        records = []
        for item in list(payload.get("records") or []):
            if not isinstance(item, dict):
                continue
            try:
                records.append(OperationExecutionRecord(**item))
            except ValueError:
                continue
        return records

    def find_by_fingerprint(
        self,
        *,
        task_run_id: str,
        step_id: str,
        operation_id: str,
        request_fingerprint: str,
    ) -> OperationExecutionRecord | None:
        for item in reversed(self.list_task_run_records(task_run_id)):
            if item.step_id != str(step_id or ""):
                continue
            if item.operation_id != str(operation_id or ""):
                continue
            if item.request_fingerprint != str(request_fingerprint or ""):
                continue
            return item
        return None

    def mark_dispatched(
        self,
        record: OperationExecutionRecord,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> OperationExecutionRecord:
        updated = replace(
            record,
            status="dispatched",
            side_effect_state="in_progress",
            attempt_count=max(1, int(record.attempt_count or 0) + 1),
            updated_at=time.time(),
            diagnostics=_merged_dict(record.diagnostics, diagnostics),
        )
        return self.upsert(updated)

    def mark_completed(
        self,
        record: OperationExecutionRecord,
        *,
        result_ref: str,
        result_payload: dict[str, Any],
        diagnostics: dict[str, Any] | None = None,
    ) -> OperationExecutionRecord:
        updated = replace(
            record,
            status="completed",
            side_effect_state="committed",
            result_ref=str(result_ref or ""),
            result_payload=dict(result_payload or {}),
            updated_at=time.time(),
            diagnostics=_merged_dict(record.diagnostics, diagnostics),
        )
        return self.upsert(updated)

    def mark_failed(
        self,
        record: OperationExecutionRecord,
        *,
        error: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> OperationExecutionRecord:
        updated = replace(
            record,
            status="failed",
            side_effect_state="unknown",
            updated_at=time.time(),
            diagnostics=_merged_dict(record.diagnostics, {"error": str(error or ""), **dict(diagnostics or {})}),
        )
        return self.upsert(updated)

    def mark_reused(
        self,
        record: OperationExecutionRecord,
        *,
        result_ref: str = "",
        result_payload: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> OperationExecutionRecord:
        updated = replace(
            record,
            status="reused_completed_result",
            result_ref=str(result_ref or record.result_ref or ""),
            result_payload=dict(result_payload or record.result_payload or {}),
            updated_at=time.time(),
            diagnostics=_merged_dict(record.diagnostics, diagnostics),
        )
        return self.upsert(updated)

    def mark_replay_suppressed(
        self,
        record: OperationExecutionRecord,
        *,
        error: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> OperationExecutionRecord:
        updated = replace(
            record,
            status="replay_suppressed",
            updated_at=time.time(),
            diagnostics=_merged_dict(record.diagnostics, {"error": str(error or ""), **dict(diagnostics or {})}),
        )
        return self.upsert(updated)

    def build_summary(self, task_run_id: str) -> dict[str, Any]:
        records = self.list_task_run_records(task_run_id)
        return {
            "execution_count": len(records),
            "completed_count": sum(1 for item in records if item.status == "completed"),
            "failed_count": sum(1 for item in records if item.status == "failed"),
            "reused_count": sum(1 for item in records if item.status == "reused_completed_result"),
            "suppressed_count": sum(1 for item in records if item.status == "replay_suppressed"),
            "execution_refs": [item.execution_id for item in records],
            "latest_execution_id": records[-1].execution_id if records else "",
        }

    def _payload_path(self, task_run_id: str) -> Path:
        return self.execution_dir / f"{_safe_id(task_run_id)}.json"

    def _load_payload(self, task_run_id: str) -> dict[str, Any]:
        path = self._payload_path(task_run_id)
        if not path.exists():
            return {"task_run_id": task_run_id, "records": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_payload(self, task_run_id: str, payload: dict[str, Any]) -> None:
        path = self._payload_path(task_run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def derive_replay_policy(operation: OperationDescriptor | None) -> ReplayPolicy:
    if operation is None:
        return "deny_auto_replay"
    metadata = dict(operation.metadata or {})
    explicit = str(metadata.get("replay_policy") or "").strip()
    if explicit in {"replay_read", "reuse_completed_result", "deny_auto_replay", "manual_recovery_required"}:
        return explicit  # type: ignore[return-value]
    if operation.read_only:
        return "replay_read"
    if operation.idempotent and not operation.destructive:
        return "reuse_completed_result"
    if operation.requires_user_interaction and operation.destructive:
        return "manual_recovery_required"
    return "deny_auto_replay"


def build_request_fingerprint(
    *,
    step_id: str,
    operation_id: str,
    payload: dict[str, Any],
) -> str:
    normalized_payload = {
        "step_id": str(step_id or ""),
        "operation_id": str(operation_id or ""),
        "tool_name": str(payload.get("tool_name") or ""),
        "tool_args": _normalized_tool_args(dict(payload.get("tool_call") or {}).get("args") or payload.get("tool_args") or {}),
    }
    raw = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_idempotency_token(
    *,
    task_run_id: str,
    step_id: str,
    operation_id: str,
    request_fingerprint: str,
) -> str:
    raw = "::".join(
        [
            str(task_run_id or ""),
            str(step_id or ""),
            str(operation_id or ""),
            str(request_fingerprint or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_execution_receipt(
    record: OperationExecutionRecord,
    *,
    reused_previous_result: bool = False,
    error: str = "",
) -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=record.execution_id,
        request_ref=record.request_ref,
        status=record.status,
        replay_decision=record.replay_policy,
        reused_previous_result=bool(reused_previous_result),
        result_ref=record.result_ref,
        error=str(error or ""),
    )


def _normalized_tool_args(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {str(key): _normalized_tool_args(value) for key, value in sorted(payload.items(), key=lambda item: str(item[0]))}
    if isinstance(payload, list):
        return [_normalized_tool_args(item) for item in payload]
    if isinstance(payload, tuple):
        return [_normalized_tool_args(item) for item in payload]
    if isinstance(payload, (str, int, float, bool)) or payload is None:
        return payload
    return str(payload)


def _merged_dict(base: dict[str, Any], updates: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base or {})
    if updates:
        merged.update(dict(updates))
    return merged


def _safe_id(value: str, *, limit: int = 160) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    if not safe:
        return "runtime"
    if len(safe) <= limit:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    head_limit = max(1, limit - len(digest) - 1)
    return f"{safe[:head_limit].rstrip('_')}_{digest}"
