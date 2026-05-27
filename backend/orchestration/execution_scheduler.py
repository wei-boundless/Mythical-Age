from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

from project_layout import ProjectLayout


DispatchMode = Literal["sync", "async", "background", "parallel", "barrier", "manual_gate"]
TaskStatus = Literal["queued", "running", "succeeded", "failed", "skipped"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True, slots=True)
class ExecutionDispatchDecision:
    execution_mode: str
    dispatch_mode: DispatchMode
    wait_for_completion: bool
    background: bool = False
    lane_id: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_execution_dispatch(
    *,
    execution_mode: str,
    wait_policy: str = "",
    join_policy: str = "",
    background_policy: dict[str, Any] | None = None,
    runtime_lane: str = "",
    blocks_downstream: bool = True,
) -> ExecutionDispatchDecision:
    mode = str(execution_mode or "sync").strip() or "sync"
    wait_policy = str(wait_policy or "").strip()
    join_policy = str(join_policy or "").strip()
    runtime_lane = str(runtime_lane or "").strip()
    background_policy = dict(background_policy or {})
    background_enabled = bool(background_policy.get("enabled"))
    background_blocks_downstream = bool(background_policy.get("blocks_downstream", blocks_downstream))

    if mode == "manual_gate":
        return ExecutionDispatchDecision(
            execution_mode=mode,
            dispatch_mode="manual_gate",
            wait_for_completion=True,
            lane_id=runtime_lane,
            reason="manual_gate requires explicit approval before completion.",
            metadata={
                "wait_policy": wait_policy,
                "join_policy": join_policy,
                "background_policy": background_policy,
            },
        )
    if mode == "barrier":
        return ExecutionDispatchDecision(
            execution_mode=mode,
            dispatch_mode="barrier",
            wait_for_completion=True,
            lane_id=runtime_lane,
            reason="barrier nodes keep the current run open until the barrier resolves.",
            metadata={
                "wait_policy": wait_policy,
                "join_policy": join_policy,
                "background_policy": background_policy,
            },
        )
    if mode == "background" or (background_enabled and not background_blocks_downstream):
        return ExecutionDispatchDecision(
            execution_mode=mode,
            dispatch_mode="background",
            wait_for_completion=False,
            background=True,
            lane_id=runtime_lane,
            reason="background nodes are dispatched out of band and do not block the main turn.",
            metadata={
                "wait_policy": wait_policy,
                "join_policy": join_policy,
                "background_policy": background_policy,
            },
        )
    if mode == "async" or wait_policy == "fire_and_continue":
        return ExecutionDispatchDecision(
            execution_mode=mode,
            dispatch_mode="async",
            wait_for_completion=False,
            lane_id=runtime_lane,
            reason="async dispatch lets the main chain continue without waiting for completion.",
            metadata={
                "wait_policy": wait_policy,
                "join_policy": join_policy,
                "background_policy": background_policy,
            },
        )
    if mode == "parallel":
        return ExecutionDispatchDecision(
            execution_mode=mode,
            dispatch_mode="parallel",
            wait_for_completion=False,
            lane_id=runtime_lane,
            reason="parallel dispatch fans out work and joins through the scheduler state.",
            metadata={
                "wait_policy": wait_policy,
                "join_policy": join_policy,
                "background_policy": background_policy,
            },
        )
    return ExecutionDispatchDecision(
        execution_mode="sync",
        dispatch_mode="sync",
        wait_for_completion=True,
        lane_id=runtime_lane,
        reason="sync dispatch keeps the work on the main path.",
        metadata={
            "wait_policy": wait_policy,
            "join_policy": join_policy,
            "background_policy": background_policy,
        },
    )


@dataclass(frozen=True, slots=True)
class BackgroundTaskRecord:
    task_id: str
    task_kind: str
    status: TaskStatus = "queued"
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    source: str = ""
    session_id: str = ""
    lane_id: str = ""
    coalesce_key: str = ""
    attempts: int = 0
    queued_at: str = field(default_factory=utc_now_iso)
    started_at: str = ""
    completed_at: str = ""
    receipt_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BackgroundTaskStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.runtime_dir = ProjectLayout.from_backend_dir(self.base_dir).runtime_state_dir / "background_tasks"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record_path(self, task_id: str, task_kind: str) -> Path:
        safe_kind = self._safe_segment(task_kind)
        safe_id = self._safe_segment(task_id)
        path = self.runtime_dir / safe_kind / f"{safe_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, record: BackgroundTaskRecord) -> BackgroundTaskRecord:
        path = self.record_path(record.task_id, record.task_kind)
        payload = record.to_dict()
        payload["receipt_path"] = str(path)
        with self._lock:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return BackgroundTaskRecord(**payload)

    def load(self, task_id: str, task_kind: str) -> BackgroundTaskRecord | None:
        path = self.record_path(task_id, task_kind)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return BackgroundTaskRecord(**payload)

    def list_records(self, *, task_kind: str | None = None) -> list[BackgroundTaskRecord]:
        records: list[BackgroundTaskRecord] = []
        kind_dirs = [self.runtime_dir / self._safe_segment(task_kind)] if task_kind else [item for item in self.runtime_dir.iterdir() if item.is_dir()]
        for kind_dir in kind_dirs:
            if not kind_dir.exists():
                continue
            for path in sorted(kind_dir.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(payload, dict):
                    try:
                        records.append(BackgroundTaskRecord(**payload))
                    except Exception:
                        continue
        return records

    @staticmethod
    def _safe_segment(value: str) -> str:
        normalized = str(value or "").strip().replace("\\", "_").replace("/", "_").replace(":", "_")
        return normalized or "default"


class BackgroundTaskManager:
    def __init__(self, base_dir: Path) -> None:
        self.store = BackgroundTaskStore(base_dir)
        self._handlers: dict[str, Callable[[dict[str, Any]], Any | Awaitable[Any]]] = {}
        self._lock = threading.RLock()
        self._active_tasks: dict[str, asyncio.Future[Any]] = {}
        self._active_task_keys: dict[str, tuple[str, str]] = {}
        self._loop_ready = threading.Event()
        self._background_loop: asyncio.AbstractEventLoop | None = None
        self._background_thread = threading.Thread(target=self._run_background_loop, name="background-task-loop", daemon=True)
        self._background_thread.start()

    def register_handler(self, task_kind: str, handler: Callable[[dict[str, Any]], Any | Awaitable[Any]]) -> None:
        kind = str(task_kind or "").strip() or "default"
        self._handlers[kind] = handler
        for record in self.store.list_records(task_kind=kind):
            if record.status == "queued":
                self._schedule(record.task_id, record.task_kind, coalesce_key=record.coalesce_key)

    def enqueue(
        self,
        task_kind: str,
        *,
        payload: dict[str, Any] | None = None,
        source: str = "",
        session_id: str = "",
        lane_id: str = "",
        coalesce_key: str = "",
    ) -> BackgroundTaskRecord:
        kind = str(task_kind or "").strip() or "default"
        key = self._coalesce_key(kind, coalesce_key)
        if key:
            existing = self._load_active_coalesced_task(key)
            if existing is not None:
                return existing
        task_id = f"task:{kind}:{uuid4().hex}"
        record = BackgroundTaskRecord(
            task_id=task_id,
            task_kind=kind,
            payload=dict(payload or {}),
            source=str(source or ""),
            session_id=str(session_id or ""),
            lane_id=str(lane_id or ""),
            coalesce_key=key,
        )
        stored = self.store.write(record)
        if kind in self._handlers:
            self._schedule(stored.task_id, stored.task_kind, coalesce_key=key)
        return stored

    def load(self, task_id: str, task_kind: str) -> BackgroundTaskRecord | None:
        return self.store.load(task_id, task_kind)

    def list_records(self, *, task_kind: str | None = None) -> list[BackgroundTaskRecord]:
        return self.store.list_records(task_kind=task_kind)

    def describe_runtime_state(self) -> dict[str, Any]:
        records = self.list_records()
        return {
            "authority": "orchestration.background_task_manager",
            "task_root": str(self.store.runtime_dir),
            "record_count": len(records),
            "queued_count": len([item for item in records if item.status == "queued"]),
            "running_count": len([item for item in records if item.status == "running"]),
            "succeeded_count": len([item for item in records if item.status == "succeeded"]),
            "failed_count": len([item for item in records if item.status == "failed"]),
        }

    def _schedule(self, task_id: str, task_kind: str, *, coalesce_key: str = "") -> None:
        if not self._loop_ready.wait(timeout=1.0):
            threading.Thread(
                target=self._run_task_blocking,
                args=(task_id, task_kind, coalesce_key),
                name=f"background-task-fallback-{task_kind}",
                daemon=True,
            ).start()
            return
        loop = self._background_loop
        if loop is None:
            threading.Thread(
                target=self._run_task_blocking,
                args=(task_id, task_kind, coalesce_key),
                name=f"background-task-fallback-{task_kind}",
                daemon=True,
            ).start()
            return
        with self._lock:
            existing = self._active_tasks.get(task_id)
            if existing is not None and not existing.done():
                return
            if coalesce_key:
                coalesced_task_id = self._active_task_keys.get(coalesce_key)
                if coalesced_task_id:
                    active_task_id, _active_kind = coalesced_task_id
                    active = self._active_tasks.get(active_task_id)
                    if active is not None and not active.done():
                        return
            future = asyncio.run_coroutine_threadsafe(self._run_task(task_id=task_id, task_kind=task_kind), loop)
            self._active_tasks[task_id] = future
            if coalesce_key:
                self._active_task_keys[coalesce_key] = (task_id, task_kind)
            future.add_done_callback(lambda _future: self._active_tasks.pop(task_id, None))
            if coalesce_key:
                future.add_done_callback(lambda _future: self._active_task_keys.pop(coalesce_key, None))

    def _run_background_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._background_loop = loop
        self._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()

    def _run_task_blocking(self, task_id: str, task_kind: str, coalesce_key: str = "") -> None:
        try:
            asyncio.run(self._run_task(task_id=task_id, task_kind=task_kind))
        except RuntimeError:
            # If a caller already owns a loop, fall back to a dedicated thread.
            def _thread_target() -> None:
                asyncio.run(self._run_task(task_id=task_id, task_kind=task_kind))

            threading.Thread(target=_thread_target, name=f"background-task-retry-{task_kind}", daemon=True).start()

    async def _run_task(self, *, task_id: str, task_kind: str) -> None:
        record = self.store.load(task_id, task_kind)
        if record is None or record.status in {"succeeded", "failed", "skipped"}:
            return
        record = self.store.write(
            BackgroundTaskRecord(
                **{
                    **record.to_dict(),
                    "status": "running",
                    "attempts": int(record.attempts or 0) + 1,
                    "started_at": record.started_at or utc_now_iso(),
                }
            )
        )
        handler = self._handlers.get(task_kind)
        if handler is None:
            self.store.write(
                BackgroundTaskRecord(
                    **{
                        **record.to_dict(),
                        "status": "queued",
                        "error": "missing_background_task_handler",
                        "completed_at": "",
                    }
                )
            )
            return
        try:
            result = handler(dict(record.payload or {}))
            if inspect.isawaitable(result):
                result = await result
            normalized_result = self._normalize_result(result)
            self.store.write(
                BackgroundTaskRecord(
                    **{
                        **record.to_dict(),
                        "status": "succeeded",
                        "result": normalized_result,
                        "error": "",
                        "completed_at": utc_now_iso(),
                    }
                )
            )
        except Exception as exc:
            self.store.write(
                BackgroundTaskRecord(
                    **{
                        **record.to_dict(),
                        "status": "failed",
                        "error": str(exc),
                        "completed_at": utc_now_iso(),
                    }
                )
            )

    @staticmethod
    def _normalize_result(result: Any) -> dict[str, Any]:
        if result is None:
            return {}
        if hasattr(result, "to_dict"):
            try:
                return dict(result.to_dict())
            except Exception:
                return {"value": str(result)}
        if isinstance(result, dict):
            return dict(result)
        return {"value": result}

    def _coalesce_key(self, task_kind: str, coalesce_key: str) -> str:
        normalized = str(coalesce_key or "").strip()
        if not normalized:
            return ""
        return f"{str(task_kind or '').strip() or 'default'}::{normalized}"

    def _load_active_coalesced_task(self, coalesce_key: str) -> BackgroundTaskRecord | None:
        with self._lock:
            active = self._active_task_keys.get(coalesce_key)
        if not active:
            return self._load_persisted_coalesced_task(coalesce_key)
        task_id, kind = active
        record = self.store.load(task_id, kind)
        if record is None or record.status in {"succeeded", "failed", "skipped"}:
            persisted = self._load_persisted_coalesced_task(coalesce_key)
            if persisted is not None:
                return persisted
            return None
        return record

    def _load_persisted_coalesced_task(self, coalesce_key: str) -> BackgroundTaskRecord | None:
        if not coalesce_key:
            return None
        candidates = [
            record
            for record in self.store.list_records()
            if str(record.coalesce_key or "") == coalesce_key
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: str(item.queued_at or ""), reverse=True)[0]


