from __future__ import annotations

from contextlib import contextmanager
import json
import msvcrt
import os
import tempfile
import time
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from core.project_layout import ProjectLayout


class RunMonitorRetentionStore:
    authority = "harness.run_monitor.retention_store"

    def __init__(self, *, backend_dir: str | Path | None) -> None:
        layout = ProjectLayout.from_backend_dir(backend_dir or Path.cwd())
        self.store_dir = layout.runtime_state_dir / "harness_run_monitor"
        self.hidden_path = self.store_dir / "hidden_signals.jsonl"

    def hidden_index(self, *, now: float | None = None) -> dict[str, dict[str, Any]]:
        current_time = time.time() if now is None else float(now)
        rows = [
            row
            for row in self._read_rows()
            if not _is_expired(row, now=current_time)
        ]
        latest: dict[str, dict[str, Any]] = {}
        cleared: set[str] = set()
        for row in rows:
            signal_id = str(row.get("signal_id") or "").strip()
            if not signal_id:
                continue
            action = str(row.get("action") or "hide").strip()
            if action == "unhide":
                cleared.add(signal_id)
                latest.pop(signal_id, None)
                continue
            if signal_id in cleared:
                cleared.remove(signal_id)
            latest[signal_id] = row
        return latest

    def hide_signal(
        self,
        *,
        signal_id: str,
        task_run_id: str = "",
        graph_run_id: str = "",
        reason: str = "user_cleared",
        hidden_by: str = "user",
        source_revision: str = "",
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        current_time = time.time() if now is None else float(now)
        normalized_signal_id = str(signal_id or "").strip()
        if not normalized_signal_id:
            raise ValueError("signal_id is required")
        row = {
            "authority": self.authority,
            "action": "hide",
            "signal_id": normalized_signal_id,
            "task_run_id": str(task_run_id or "").strip(),
            "graph_run_id": str(graph_run_id or "").strip(),
            "hidden_reason": str(reason or "user_cleared").strip() or "user_cleared",
            "hidden_by": str(hidden_by or "user").strip() or "user",
            "hidden_at": current_time,
            "expires_at": current_time + float(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else 0.0,
            "source_revision": str(source_revision or "").strip(),
        }
        self._append_row(row)
        return row

    def unhide_signal(self, *, signal_id: str, reason: str = "user_restored", now: float | None = None) -> dict[str, Any]:
        current_time = time.time() if now is None else float(now)
        normalized_signal_id = str(signal_id or "").strip()
        if not normalized_signal_id:
            raise ValueError("signal_id is required")
        row = {
            "authority": self.authority,
            "action": "unhide",
            "signal_id": normalized_signal_id,
            "hidden_reason": str(reason or "user_restored").strip() or "user_restored",
            "hidden_by": "user",
            "hidden_at": current_time,
            "expires_at": 0.0,
            "source_revision": "",
        }
        self._append_row(row)
        return row

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.hidden_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = self.hidden_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _append_row(self, row: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with self._jsonl_lock(self.hidden_path):
            with self.hidden_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        self._compact_if_needed()

    def _compact_if_needed(self) -> None:
        if not self.hidden_path.exists():
            return
        try:
            if self.hidden_path.stat().st_size < 256 * 1024:
                return
        except OSError:
            return
        rows = list(self.hidden_index().values())
        content = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        if content:
            content += "\n"
        self._atomic_write_text(self.hidden_path, content)

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp") as handle:
                handle.write(content)
                tmp_path = Path(handle.name)
            tmp_path.replace(path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @contextmanager
    def _jsonl_lock(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.lock")
        with lock_path.open("a+b") as handle:
            _lock_handle(handle)
            try:
                yield
            finally:
                _unlock_handle(handle)


def _is_expired(row: dict[str, Any], *, now: float) -> bool:
    expires_at = float(row.get("expires_at") or 0.0)
    return bool(expires_at and expires_at <= now)


def _lock_handle(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


