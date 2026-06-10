from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from runtime.tool_runtime.tool_invocation_control import registry_for


ExecutorSignalKind = Literal["pause", "stop", "replan"]


@dataclass(frozen=True, slots=True)
class ExecutorControlSignal:
    kind: ExecutorSignalKind
    task_run_id: str
    executor_epoch: int
    reason: str
    requested_by: str
    requested_at: float
    steer_ref: str = ""


@dataclass(slots=True)
class ExecutorEpochRecord:
    task_run_id: str
    executor_epoch: int
    model_task: asyncio.Task[Any] | None = None
    signal: ExecutorControlSignal | None = None
    created_at: float = 0.0


def register_executor_epoch(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> ExecutorEpochRecord:
    registry = _registry(runtime_host)
    record = ExecutorEpochRecord(
        task_run_id=task_run_id,
        executor_epoch=int(executor_epoch or 0),
        created_at=time.time(),
    )
    registry[task_run_id] = record
    return record


def attach_model_task(runtime_host: Any, *, task_run_id: str, executor_epoch: int, model_task: asyncio.Task[Any]) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is None:
        record = register_executor_epoch(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    record.model_task = model_task
    if record.signal is not None and not model_task.done():
        model_task.cancel()


def request_executor_pause(runtime_host: Any, *, task_run_id: str, reason: str = "", requested_by: str = "user") -> bool:
    return _request_signal(runtime_host, task_run_id=task_run_id, kind="pause", reason=reason, requested_by=requested_by)


def request_executor_stop(runtime_host: Any, *, task_run_id: str, reason: str = "", requested_by: str = "user") -> bool:
    return _request_signal(runtime_host, task_run_id=task_run_id, kind="stop", reason=reason, requested_by=requested_by)


def request_executor_replan(
    runtime_host: Any,
    *,
    task_run_id: str,
    reason: str = "",
    requested_by: str = "user",
    steer_ref: str = "",
) -> bool:
    return _request_signal(
        runtime_host,
        task_run_id=task_run_id,
        kind="replan",
        reason=reason,
        requested_by=requested_by,
        steer_ref=steer_ref,
    )


def peek_executor_signal(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> ExecutorControlSignal | None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    return record.signal if record is not None else None


def clear_executor_signal(
    runtime_host: Any,
    *,
    task_run_id: str,
    executor_epoch: int,
    signal: ExecutorControlSignal | None = None,
) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is None or record.signal is None:
        return
    if signal is not None and record.signal != signal:
        return
    record.signal = None


def clear_model_task(runtime_host: Any, *, task_run_id: str, executor_epoch: int, model_task: asyncio.Task[Any]) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is not None and record.model_task is model_task:
        record.model_task = None


def clear_executor_epoch(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is not None:
        _registry(runtime_host).pop(task_run_id, None)


def executor_epoch_is_live(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> bool:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is None:
        return False
    model_live = record.model_task is not None and not record.model_task.done()
    return model_live or record.model_task is None


def _request_signal(
    runtime_host: Any,
    *,
    task_run_id: str,
    kind: ExecutorSignalKind,
    reason: str,
    requested_by: str,
    steer_ref: str = "",
) -> bool:
    record = _registry(runtime_host).get(task_run_id)
    if record is None:
        return False
    signal = ExecutorControlSignal(
        kind=kind,
        task_run_id=task_run_id,
        executor_epoch=record.executor_epoch,
        reason=reason,
        requested_by=requested_by or "user",
        requested_at=time.time(),
        steer_ref=steer_ref,
    )
    record.signal = signal
    if record.model_task is not None and not record.model_task.done():
        record.model_task.cancel()
    registry = registry_for(runtime_host)
    if registry is not None:
        registry.cancel_by_caller(
            task_run_id=task_run_id,
            kind=kind,
            reason=reason,
            requested_by=requested_by,
            steer_ref=steer_ref,
        )
    return True


def _current_record(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> ExecutorEpochRecord | None:
    record = _registry(runtime_host).get(task_run_id)
    if record is None:
        return None
    if record.executor_epoch != int(executor_epoch or 0):
        return None
    return record


def _registry(runtime_host: Any) -> dict[str, ExecutorEpochRecord]:
    registry = getattr(runtime_host, "_task_run_execution_control", None)
    if isinstance(registry, dict):
        return registry
    registry = {}
    setattr(runtime_host, "_task_run_execution_control", registry)
    return registry
