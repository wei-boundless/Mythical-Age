from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .events import RuntimeEvent


DEFAULT_TAIL_LIMIT = 240


@dataclass(slots=True)
class RuntimeEventCursor:
    run_id: str
    next_offset: int = 0
    physical_line_count: int = 0
    file_size_bytes: int = 0
    mtime: float = 0.0
    updated_at: float = field(default_factory=time.time)
    authority: str = "orchestration.runtime_event_cursor"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "next_offset": self.next_offset,
            "physical_line_count": self.physical_line_count,
            "file_size_bytes": self.file_size_bytes,
            "mtime": self.mtime,
            "updated_at": self.updated_at,
            "authority": self.authority,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, run_id: str) -> "RuntimeEventCursor":
        return cls(
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or run_id),
            next_offset=max(0, int(payload.get("next_offset") or 0)),
            physical_line_count=max(0, int(payload.get("physical_line_count") or 0)),
            file_size_bytes=max(0, int(payload.get("file_size_bytes") or 0)),
            mtime=float(payload.get("mtime") or 0.0),
            updated_at=float(payload.get("updated_at") or time.time()),
        )


class RuntimeEventIndex:
    """Sidecar cursor and tail index for append-only runtime JSONL files."""

    authority = "orchestration.runtime_event_index"

    def __init__(self, root_dir: Path, *, tail_limit: int = DEFAULT_TAIL_LIMIT) -> None:
        self.root_dir = Path(root_dir)
        self.index_dir = self.root_dir / "event_index"
        self.cursor_dir = self.index_dir / "cursors"
        self.tail_dir = self.index_dir / "tails"
        self.cursor_dir.mkdir(parents=True, exist_ok=True)
        self.tail_dir.mkdir(parents=True, exist_ok=True)
        self.tail_limit = max(1, int(tail_limit or DEFAULT_TAIL_LIMIT))
        self._lock = threading.RLock()

    def next_offset(self, *, run_id: str, event_path: Path) -> int:
        with self._lock:
            cursor = self._load_cursor(run_id)
            stat = _safe_stat(event_path)
            if stat is None:
                cursor = RuntimeEventCursor(run_id=run_id)
                self._write_cursor(cursor)
                self._write_tail(run_id, [])
                return 0
            if self._cursor_matches(cursor, stat):
                return cursor.next_offset
            rebuilt_cursor, tail = rebuild_event_index(
                run_id=run_id,
                event_path=event_path,
                tail_limit=self.tail_limit,
            )
            self._write_cursor(rebuilt_cursor)
            self._write_tail(run_id, [compact_event_for_tail(item) for item in tail])
            return rebuilt_cursor.next_offset

    def record_append(self, event: RuntimeEvent, *, event_path: Path) -> None:
        with self._lock:
            stat = _safe_stat(event_path)
            cursor = self._load_cursor(event.run_id)
            next_offset = max(cursor.next_offset, int(event.offset) + 1)
            physical_line_count = max(cursor.physical_line_count + 1, next_offset)
            if stat is not None:
                cursor = RuntimeEventCursor(
                    run_id=event.run_id,
                    next_offset=next_offset,
                    physical_line_count=physical_line_count,
                    file_size_bytes=int(stat.st_size),
                    mtime=float(stat.st_mtime),
                )
            else:
                cursor = RuntimeEventCursor(
                    run_id=event.run_id,
                    next_offset=next_offset,
                    physical_line_count=physical_line_count,
                )
            self._write_cursor(cursor)
            tail = self._load_tail(event.run_id)
            tail.append(compact_event_for_tail(event.to_dict()))
            self._write_tail(event.run_id, tail[-self.tail_limit :])

    def list_recent_events(self, run_id: str, *, limit: int = 160, event_path: Path | None = None) -> list[RuntimeEvent]:
        requested = max(1, int(limit or 160))
        rows = self._load_tail(run_id)[-requested:]
        if not rows and event_path is not None:
            rows = read_event_tail(event_path, tail_limit=requested)
        return [_event_from_payload(compact_event_for_tail(item), run_id=run_id) for item in rows]

    def event_count(self, run_id: str, *, event_path: Path) -> int:
        cursor = self._load_cursor(run_id)
        stat = _safe_stat(event_path)
        if stat is not None and self._cursor_matches(cursor, stat):
            return max(cursor.physical_line_count, cursor.next_offset)
        return self.next_offset(run_id=run_id, event_path=event_path)

    def estimated_event_count(self, run_id: str, *, event_path: Path) -> int:
        cursor = self._load_cursor(run_id)
        if max(cursor.physical_line_count, cursor.next_offset) > 0:
            return max(cursor.physical_line_count, cursor.next_offset)
        rows = self._load_tail(run_id)
        if not rows:
            rows = read_event_tail(event_path, tail_limit=1)
        if not rows:
            return 0
        try:
            return max(0, int(rows[-1].get("offset") or 0) + 1)
        except (TypeError, ValueError):
            return len(rows)

    def delete_index(self, run_id: str) -> None:
        self._cursor_path(run_id).unlink(missing_ok=True)
        self._tail_path(run_id).unlink(missing_ok=True)

    def _cursor_matches(self, cursor: RuntimeEventCursor, stat: os.stat_result) -> bool:
        return (
            int(cursor.file_size_bytes) == int(stat.st_size)
            and abs(float(cursor.mtime) - float(stat.st_mtime)) < 0.000001
        )

    def _load_cursor(self, run_id: str) -> RuntimeEventCursor:
        path = self._cursor_path(run_id)
        if not path.exists():
            return RuntimeEventCursor(run_id=run_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return RuntimeEventCursor(run_id=run_id)
        return RuntimeEventCursor.from_dict(payload if isinstance(payload, dict) else {}, run_id=run_id)

    def _write_cursor(self, cursor: RuntimeEventCursor) -> None:
        _atomic_write_json(self._cursor_path(cursor.run_id), cursor.to_dict())

    def _load_tail(self, run_id: str) -> list[dict[str, Any]]:
        path = self._tail_path(run_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        rows = payload.get("events") if isinstance(payload, dict) else payload
        return [dict(item) for item in list(rows or []) if isinstance(item, dict)]

    def _write_tail(self, run_id: str, events: list[dict[str, Any]]) -> None:
        _atomic_write_json(
            self._tail_path(run_id),
            {
                "run_id": run_id,
                "tail_limit": self.tail_limit,
                "event_count": len(events),
                "events": list(events[-self.tail_limit :]),
                "updated_at": time.time(),
                "authority": "orchestration.runtime_event_tail_index",
            },
        )

    def _cursor_path(self, run_id: str) -> Path:
        return self.cursor_dir / f"{_safe_id(run_id)}.json"

    def _tail_path(self, run_id: str) -> Path:
        return self.tail_dir / f"{_safe_id(run_id)}.json"


def rebuild_event_index(*, run_id: str, event_path: Path, tail_limit: int = DEFAULT_TAIL_LIMIT) -> tuple[RuntimeEventCursor, list[dict[str, Any]]]:
    physical_line_count = 0
    max_seen_offset = -1
    tail: list[dict[str, Any]] = []
    if event_path.exists():
        with event_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                stripped = line.strip()
                if not stripped:
                    continue
                physical_line_count += 1
                try:
                    payload = json.loads(stripped)
                except JSONDecodeError:
                    continue
                try:
                    max_seen_offset = max(max_seen_offset, int(payload.get("offset") or 0))
                except (TypeError, ValueError):
                    pass
                try:
                    tail.append(compact_event_for_tail(payload if isinstance(payload, dict) else {}))
                    if len(tail) > max(1, int(tail_limit or DEFAULT_TAIL_LIMIT)):
                        tail = tail[-max(1, int(tail_limit or DEFAULT_TAIL_LIMIT)) :]
                except Exception:
                    continue
    stat = _safe_stat(event_path)
    cursor = RuntimeEventCursor(
        run_id=run_id,
        next_offset=max(physical_line_count, max_seen_offset + 1),
        physical_line_count=physical_line_count,
        file_size_bytes=int(stat.st_size) if stat is not None else 0,
        mtime=float(stat.st_mtime) if stat is not None else 0.0,
    )
    return cursor, tail


def read_event_tail(event_path: Path, *, tail_limit: int = DEFAULT_TAIL_LIMIT, max_bytes: int = 8 * 1024 * 1024) -> list[dict[str, Any]]:
    return [compact_event_for_tail(item) for item in read_event_tail_raw(event_path, tail_limit=tail_limit, max_bytes=max_bytes)]


def read_event_tail_raw(event_path: Path, *, tail_limit: int = DEFAULT_TAIL_LIMIT, max_bytes: int = 8 * 1024 * 1024) -> list[dict[str, Any]]:
    requested = max(1, int(tail_limit or DEFAULT_TAIL_LIMIT))
    path = Path(event_path)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        read_size = min(size, max(64 * 1024, int(max_bytes)))
        with path.open("rb") as stream:
            stream.seek(max(0, size - read_size))
            data = stream.read(read_size)
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    lines = data.splitlines()
    if size > read_size and lines:
        lines = lines[1:]
    for raw_line in lines[-requested:]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows[-requested:]


def _event_from_payload(payload: dict[str, Any], *, run_id: str) -> RuntimeEvent:
    return RuntimeEvent(
        event_id=str(payload.get("event_id") or ""),
        run_id=str(payload.get("run_id") or payload.get("task_run_id") or run_id),
        event_type=payload.get("event_type", "loop_error"),
        offset=int(payload.get("offset") or 0),
        created_at=float(payload.get("created_at") or 0.0),
        payload=dict(payload.get("payload") or {}),
        refs=dict(payload.get("refs") or {}),
    )


def compact_event_for_tail(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event.get("payload") or {})
    compact_payload: dict[str, Any] = {}
    for key in (
        "step",
        "status",
        "summary",
        "public_progress_note",
        "agent_brief_output",
        "public_action_state",
        "current_judgment",
        "next_action",
        "completion_status",
        "presentation_source",
        "terminal_reason",
        "error",
        "reason",
        "payload_externalized",
        "payload_ref",
        "payload_size_bytes",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            compact_payload[key] = _compact_value(value)
    observation = payload.get("observation")
    if isinstance(observation, dict):
        compact_payload["observation"] = {
            key: _compact_value(observation.get(key))
            for key in ("source", "summary", "observation_type")
            if observation.get(key) not in (None, "")
        }
    return {
        "event_id": str(event.get("event_id") or ""),
        "run_id": str(event.get("run_id") or event.get("task_run_id") or ""),
        "event_type": str(event.get("event_type") or "loop_error"),
        "offset": int(event.get("offset") or 0),
        "created_at": float(event.get("created_at") or 0.0),
        "payload": compact_payload,
        "refs": _compact_refs(dict(event.get("refs") or {})),
        "authority": "orchestration.runtime_event",
    }


def _compact_refs(refs: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in refs.items():
        if value not in (None, "", [], {}):
            result[str(key)] = _compact_value(value, limit=240)
    return result


def _compact_value(value: Any, *, limit: int = 600) -> Any:
    if isinstance(value, str):
        text = value.strip()
        return text if len(text) <= limit else f"{text[: limit - 3]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _compact_value(item, limit=limit) for key, item in list(value.items())[:12]}
    if isinstance(value, (list, tuple)):
        return [_compact_value(item, limit=limit) for item in list(value)[:8]]
    return _compact_value(str(value), limit=limit)


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return Path(path).stat()
    except OSError:
        return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(text, encoding="utf-8")
    last_error: OSError | None = None
    for attempt in range(16):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(min(0.75, 0.05 * (attempt + 1)))
    try:
        path.write_text(text, encoding="utf-8")
        tmp.unlink(missing_ok=True)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        if last_error is not None:
            raise last_error from exc
        raise


def _safe_id(value: str, *, limit: int = 180) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "")).strip("_")
    return (safe or "runtime")[:limit]
