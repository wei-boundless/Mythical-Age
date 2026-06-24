from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout


class FileChangeConflict(RuntimeError):
    pass


class FileChangeMissing(FileNotFoundError):
    pass


class FileChangeTracker:
    """Records text file changes with before/after snapshots for diff and rollback."""

    def __init__(self, base_dir: str | Path) -> None:
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.project_root = layout.project_root.resolve()
        self.root_dir = layout.storage_root / "file_changes"
        self.records_dir = self.root_dir / "records"
        self.snapshots_dir = self.root_dir / "snapshots"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def record_text_change(
        self,
        *,
        session_id: str,
        task_run_id: str,
        agent_run_id: str,
        tool_call_id: str,
        tool_name: str,
        operation_id: str,
        workspace_root: str | Path,
        logical_path: str,
        absolute_path: str | Path,
        before_content: str | None,
        after_content: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = Path(absolute_path).resolve()
        root = Path(workspace_root).resolve()
        if not _is_inside(target, root):
            raise ValueError("file change target must be inside workspace_root")
        record_id = f"filechange-{uuid.uuid4().hex}"
        snapshot_dir = self.snapshots_dir / record_id
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        before_path = snapshot_dir / "before.txt"
        after_path = snapshot_dir / "after.txt"
        before_text = "" if before_content is None else str(before_content)
        after_text = "" if after_content is None else str(after_content)
        after_exists = after_content is not None
        _atomic_write_text(before_path, before_text)
        _atomic_write_text(after_path, after_text)
        now = time.time()
        record = {
            "record_id": record_id,
            "session_id": str(session_id or ""),
            "task_run_id": str(task_run_id or ""),
            "agent_run_id": str(agent_run_id or ""),
            "tool_call_id": str(tool_call_id or ""),
            "tool_name": str(tool_name or ""),
            "operation_id": str(operation_id or ""),
            "workspace_root": str(root),
            "logical_path": str(logical_path or ""),
            "absolute_path": str(target),
            "before_exists": before_content is not None,
            "after_exists": after_exists,
            "before_sha256": _sha256_text(before_text) if before_content is not None else "",
            "after_sha256": _sha256_text(after_text) if after_exists else "",
            "before_snapshot_path": str(before_path),
            "after_snapshot_path": str(after_path),
            "before_uri": before_path.resolve().as_uri(),
            "after_uri": after_path.resolve().as_uri(),
            "status": "active",
            "created_at": now,
            "rolled_back_at": 0.0,
            "rollback_error": "",
            "metadata": dict(metadata or {}),
            "authority": "runtime.file_changes.record",
        }
        self._write_record(record)
        return dict(record)

    def list_records(
        self,
        *,
        session_id: str = "",
        task_run_id: str = "",
        status: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        records = [self._read_record_path(path) for path in self.records_dir.glob("*.json")]
        filtered = []
        for record in records:
            if session_id and str(record.get("session_id") or "") != session_id:
                continue
            if task_run_id and str(record.get("task_run_id") or "") != task_run_id:
                continue
            if status and str(record.get("status") or "") != status:
                continue
            filtered.append(record)
        return sorted(filtered, key=lambda item: float(item.get("created_at") or 0), reverse=True)[: max(1, int(limit or 100))]

    def require_record(self, record_id: str) -> dict[str, Any]:
        safe_id = _safe_record_id(record_id)
        if not safe_id:
            raise FileChangeMissing("file change record not found")
        path = self.records_dir / f"{safe_id}.json"
        if not path.exists():
            raise FileChangeMissing("file change record not found")
        return self._read_record_path(path)

    def diff_entries(self, record_ids: list[str]) -> list[dict[str, Any]]:
        entries = []
        for record_id in record_ids:
            record = self.require_record(record_id)
            before_uri = str(record.get("before_uri") or "")
            after_uri = str(record.get("after_uri") or "")
            if not before_uri or not after_uri:
                continue
            entries.append(
                {
                    "entry_id": str(record.get("record_id") or ""),
                    "logical_path": str(record.get("logical_path") or ""),
                    "left_uri": before_uri,
                    "right_uri": after_uri,
                    "title": str(record.get("logical_path") or record.get("record_id") or "File change"),
                }
            )
        return entries

    def rollback(self, record_id: str, *, force: bool = False) -> dict[str, Any]:
        record = self.require_record(record_id)
        if str(record.get("status") or "") == "rolled_back":
            return dict(record)
        target = Path(str(record.get("absolute_path") or "")).resolve()
        root = Path(str(record.get("workspace_root") or "")).resolve()
        if not _is_inside(target, root):
            raise FileChangeConflict("file change target is outside recorded workspace_root")
        expected_after = str(record.get("after_sha256") or "")
        if target.exists() and target.is_dir():
            raise FileChangeConflict("rollback target is a directory")
        if target.exists():
            current_hash = _sha256_text(target.read_text(encoding="utf-8", errors="replace"))
        else:
            current_hash = ""
        if not force and current_hash != expected_after:
            raise FileChangeConflict("target changed after this file change record; rollback requires force")
        before_exists = bool(record.get("before_exists"))
        if before_exists:
            before_path = Path(str(record.get("before_snapshot_path") or "")).resolve()
            if not before_path.exists():
                raise FileChangeMissing("before snapshot not found")
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(target, before_path.read_text(encoding="utf-8"))
        elif target.exists():
            target.unlink()
        updated = {
            **record,
            "status": "rolled_back",
            "rolled_back_at": time.time(),
            "rollback_error": "",
            "authority": "runtime.file_changes.record",
        }
        self._write_record(updated)
        return updated

    def _write_record(self, record: dict[str, Any]) -> None:
        record_id = _safe_record_id(str(record.get("record_id") or ""))
        if not record_id:
            raise ValueError("record_id is required")
        _atomic_write_json(self.records_dir / f"{record_id}.json", record)

    @staticmethod
    def _read_record_path(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))


def _safe_record_id(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("filechange-"):
        return ""
    safe = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "_"})
    return safe if safe == text else ""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _is_inside(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write_text(path, text + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(str(content or ""), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

