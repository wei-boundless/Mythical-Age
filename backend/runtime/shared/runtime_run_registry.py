from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal


RuntimeRunStatus = Literal["starting", "running", "waiting", "completed", "failed", "stopped", "orphaned"]


@dataclass(frozen=True, slots=True)
class RuntimeRun:
    stream_run_id: str
    session_id: str
    event_log_id: str
    root_request_ref: str
    status: RuntimeRunStatus
    created_at: float
    updated_at: float
    latest_event_offset: int = -1
    latest_checkpoint_ref: str = ""
    reconnectable_until: float = 0.0
    terminal_event: str = ""
    owner_process_id: int = 0
    owner_instance_id: str = ""
    diagnostics: dict[str, Any] | None = None
    authority: str = "runtime.run_registry"

    def __post_init__(self) -> None:
        if self.authority != "runtime.run_registry":
            raise ValueError("RuntimeRun authority must be runtime.run_registry")
        if not self.stream_run_id:
            raise ValueError("RuntimeRun requires stream_run_id")
        if not self.session_id:
            raise ValueError("RuntimeRun requires session_id")
        if not self.event_log_id:
            raise ValueError("RuntimeRun requires event_log_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


class RuntimeRunRegistry:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.run_dir = self.root_dir / "runs"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create_run(
        self,
        *,
        session_id: str,
        root_request_ref: str = "",
        reconnect_ttl_seconds: float = 6 * 60 * 60,
        diagnostics: dict[str, Any] | None = None,
        owner_process_id: int | None = None,
        owner_instance_id: str = "",
    ) -> RuntimeRun:
        now = time.time()
        stream_run_id = f"strun:{uuid.uuid4().hex}"
        run = RuntimeRun(
            stream_run_id=stream_run_id,
            session_id=str(session_id or "").strip(),
            event_log_id=f"chatrun:{_safe_id(stream_run_id)}",
            root_request_ref=str(root_request_ref or f"chatreq:{uuid.uuid4().hex}"),
            status="starting",
            created_at=now,
            updated_at=now,
            reconnectable_until=now + max(60.0, float(reconnect_ttl_seconds or 0)),
            owner_process_id=int(owner_process_id or os.getpid()),
            owner_instance_id=str(owner_instance_id or ""),
            diagnostics=dict(diagnostics or {}),
        )
        return self.upsert(run)

    def get_run(self, stream_run_id: str) -> RuntimeRun | None:
        path = self._run_path(stream_run_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        payload["event_log_id"] = str(payload.get("event_log_id") or payload.get("task_run_id") or "").strip()
        payload.pop("task_run_id", None)
        try:
            return RuntimeRun(**payload)
        except (TypeError, ValueError):
            return None

    def list_session_runs(self, session_id: str) -> list[RuntimeRun]:
        normalized = str(session_id or "").strip()
        runs = [run for run in self.list_runs() if run.session_id == normalized]
        return sorted(runs, key=lambda item: item.updated_at, reverse=True)

    def list_runs(self) -> list[RuntimeRun]:
        runs: list[RuntimeRun] = []
        for path in self.run_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            payload["event_log_id"] = str(payload.get("event_log_id") or payload.get("task_run_id") or "").strip()
            payload.pop("task_run_id", None)
            try:
                runs.append(RuntimeRun(**payload))
            except (TypeError, ValueError):
                continue
        return sorted(runs, key=lambda item: item.updated_at, reverse=True)

    def latest_session_run(self, session_id: str) -> RuntimeRun | None:
        runs = self.list_session_runs(session_id)
        return runs[0] if runs else None

    def delete_session_runs(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            return {
                "authority": "runtime.run_registry.delete_session_runs",
                "session_id": "",
                "deleted_stream_run_ids": [],
                "detached_event_log_ids": [],
            }
        deleted_stream_run_ids: list[str] = []
        detached_event_log_ids: list[str] = []
        with self._lock:
            for run in self.list_session_runs(normalized):
                path = self._run_path(run.stream_run_id)
                if not path.exists():
                    continue
                try:
                    path.unlink()
                except OSError:
                    continue
                deleted_stream_run_ids.append(run.stream_run_id)
                if run.event_log_id:
                    detached_event_log_ids.append(run.event_log_id)
        return {
            "authority": "runtime.run_registry.delete_session_runs",
            "session_id": normalized,
            "deleted_stream_run_ids": deleted_stream_run_ids,
            "detached_event_log_ids": detached_event_log_ids,
        }

    def mark_running(self, run: RuntimeRun) -> RuntimeRun:
        return self.update_run(run.stream_run_id, status="running")

    def mark_event(
        self,
        run: RuntimeRun,
        *,
        latest_event_offset: int,
        status: RuntimeRunStatus | None = None,
        terminal_event: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> RuntimeRun:
        return self.update_run(
            run.stream_run_id,
            latest_event_offset=int(latest_event_offset),
            status=status,
            terminal_event=terminal_event,
            diagnostics=diagnostics,
        )

    def update_run(
        self,
        stream_run_id: str,
        *,
        status: RuntimeRunStatus | None = None,
        latest_event_offset: int | None = None,
        latest_checkpoint_ref: str | None = None,
        terminal_event: str | None = None,
        owner_process_id: int | None = None,
        owner_instance_id: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> RuntimeRun:
        current = self.get_run(stream_run_id)
        if current is None:
            raise KeyError(f"RuntimeRun not found: {stream_run_id}")
        merged_diagnostics = dict(current.diagnostics or {})
        if diagnostics:
            merged_diagnostics.update(dict(diagnostics))
        return self.upsert(
            replace(
                current,
                status=status or current.status,
                latest_event_offset=current.latest_event_offset if latest_event_offset is None else int(latest_event_offset),
                latest_checkpoint_ref=current.latest_checkpoint_ref if latest_checkpoint_ref is None else str(latest_checkpoint_ref or ""),
                terminal_event=current.terminal_event if terminal_event is None else str(terminal_event or ""),
                owner_process_id=current.owner_process_id if owner_process_id is None else int(owner_process_id or 0),
                owner_instance_id=current.owner_instance_id if owner_instance_id is None else str(owner_instance_id or ""),
                diagnostics=merged_diagnostics,
                updated_at=time.time(),
            )
        )

    def upsert(self, run: RuntimeRun) -> RuntimeRun:
        with self._lock:
            path = self._run_path(run.stream_run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        return run

    def _run_path(self, stream_run_id: str) -> Path:
        return self.run_dir / f"{_safe_id(stream_run_id)}.json"


def _safe_id(value: str, *, limit: int = 180) -> str:
    raw = str(value or "")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_")
    if not safe:
        return "runtime-run"
    return safe[:limit]
