from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutorSequence:
    task_run_id: str
    executor_epoch: int
    next_invocation_index: int
    last_completed_invocation_index: int
    active_packet_ref: str = ""
    authority: str = "harness.loop.executor_sequence"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def claim_executor_sequence(runtime_host: Any, task_run: Any) -> ExecutorSequence:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    previous_epoch = int(diagnostics.get("executor_epoch") or 0)
    return ExecutorSequence(
        task_run_id=task_run_id,
        executor_epoch=previous_epoch + 1,
        next_invocation_index=_next_invocation_index(runtime_host, task_run_id),
        last_completed_invocation_index=_last_invocation_index(runtime_host, task_run_id),
    )


def next_model_action_request_id(*, task_run_id: str, executor_epoch: int, invocation_index: int, suffix: str) -> str:
    clean_suffix = str(suffix or "").strip() or "auto"
    return f"model-action:{task_run_id}:epoch:{executor_epoch}:invocation:{invocation_index}:{clean_suffix}"


def next_runtime_packet_id(*, task_run_id: str, invocation_kind: str, executor_epoch: int, invocation_index: int) -> str:
    return f"rtpacket:{task_run_id}:{invocation_kind}:{executor_epoch}:{invocation_index}"


def _next_invocation_index(runtime_host: Any, task_run_id: str) -> int:
    task_run = _task_run(runtime_host, task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {}) if task_run is not None else {}
    try:
        next_index = int(diagnostics.get("next_invocation_index") or 0)
    except (TypeError, ValueError):
        next_index = 0
    if next_index > 0:
        return next_index
    return max(1, _last_invocation_index(runtime_host, task_run_id) + 1)


def _last_invocation_index(runtime_host: Any, task_run_id: str) -> int:
    task_run = _task_run(runtime_host, task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {}) if task_run is not None else {}
    for key in ("last_completed_invocation_index", "next_invocation_index"):
        try:
            value = int(diagnostics.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if key == "next_invocation_index" and value > 1:
            return value - 1
        if key == "last_completed_invocation_index" and value > 0:
            return value
    last = 0
    try:
        events = runtime_host.event_log.list_events(task_run_id)
    except Exception:
        events = []
    for event in events:
        payload = dict(getattr(event, "payload", {}) or {})
        refs = dict(getattr(event, "refs", {}) or {})
        packet = dict(payload.get("packet") or {})
        for value in (
            packet.get("invocation_index"),
            payload.get("invocation_index"),
            dict(payload.get("sequence") or {}).get("invocation_index"),
            refs.get("invocation_index"),
        ):
            try:
                last = max(last, int(value or 0))
            except (TypeError, ValueError):
                pass
    return last


def _task_run(runtime_host: Any, task_run_id: str) -> Any | None:
    try:
        return runtime_host.state_index.get_task_run(task_run_id)
    except Exception:
        return None
