from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.deps import require_runtime
from project_layout import ProjectLayout
from runtime.file_changes import FileChangeConflict, FileChangeMissing, FileChangeTracker
from runtime.file_change_signals import publish_file_change_record

router = APIRouter()
MAX_DIFF_CONTENT_CHARS = 600_000


class FileChangeRollbackRequest(BaseModel):
    force: bool = False


@router.get("/file-changes")
async def list_file_changes(
    session_id: str | None = Query(default=None, max_length=200),
    task_run_id: str | None = Query(default=None, max_length=240),
    status: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    runtime = require_runtime()
    records = await asyncio.to_thread(
        _tracker(runtime).list_records,
        session_id=str(session_id or "").strip(),
        task_run_id=str(task_run_id or "").strip(),
        status=str(status or "").strip(),
        limit=limit,
    )
    return {
        "records": records,
        "summary": {"count": len(records)},
        "authority": "api.file_changes.list",
    }


@router.get("/file-changes/{record_id}")
async def get_file_change(record_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        record = await asyncio.to_thread(_tracker(runtime).require_record, record_id)
    except FileChangeMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"record": record, "authority": "api.file_changes.detail"}


@router.get("/file-changes/{record_id}/diff")
async def get_file_change_diff(record_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        record = await asyncio.to_thread(_tracker(runtime).require_record, record_id)
    except FileChangeMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await asyncio.to_thread(
        _snapshot_diff_payload,
        diff_id=record_id,
        logical_path=str(record.get("logical_path") or ""),
        before_path=Path(str(record.get("before_snapshot_path") or "")),
        after_path=Path(str(record.get("after_snapshot_path") or "")),
        before_exists=bool(record.get("before_exists")),
        after_exists=bool(record.get("after_exists")),
        metadata={"record": record},
        authority="api.file_changes.diff",
    )


@router.get("/file-changes/write-reviews/{proposal_id}/diff")
async def get_write_review_diff(proposal_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    safe_id = _safe_write_review_id(proposal_id)
    if not safe_id:
        raise HTTPException(status_code=404, detail="write review proposal not found")
    root = ProjectLayout.from_backend_dir(runtime.base_dir).storage_root / "write_reviews" / safe_id
    metadata_path = root / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="write review proposal not found")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"write review metadata unreadable: {exc}") from exc
    return await asyncio.to_thread(
        _snapshot_diff_payload,
        diff_id=safe_id,
        logical_path=str(dict(metadata or {}).get("logical_path") or safe_id),
        before_path=root / "before.txt",
        after_path=root / "after.txt",
        before_exists=bool(dict(metadata or {}).get("before_exists")),
        after_exists=bool(dict(metadata or {}).get("after_exists", True)),
        metadata={"proposal": dict(metadata or {})},
        authority="api.file_changes.write_review_diff",
    )


@router.post("/file-changes/{record_id}/rollback")
async def rollback_file_change(record_id: str, payload: FileChangeRollbackRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        record = await asyncio.to_thread(_tracker(runtime).rollback, record_id, force=payload.force)
    except FileChangeMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileChangeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    publish_file_change_record(runtime, record, action="rollback", source="api.file_changes.rollback")
    return {
        "record": record,
        "rolled_back": True,
        "authority": "api.file_changes.rollback",
    }


def _tracker(runtime: Any) -> FileChangeTracker:
    return FileChangeTracker(runtime.base_dir)


def _snapshot_diff_payload(
    *,
    diff_id: str,
    logical_path: str,
    before_path: Path,
    after_path: Path,
    before_exists: bool,
    after_exists: bool,
    metadata: dict[str, Any],
    authority: str,
) -> dict[str, Any]:
    before = _read_snapshot_text(before_path) if before_exists or before_path.exists() else {"content": "", "truncated": False}
    after = _read_snapshot_text(after_path) if after_exists or after_path.exists() else {"content": "", "truncated": False}
    return {
        "diff": {
            "diff_id": str(diff_id or ""),
            "logical_path": str(logical_path or ""),
            "before_exists": bool(before_exists),
            "after_exists": bool(after_exists),
            "before_content": str(before.get("content") or ""),
            "after_content": str(after.get("content") or ""),
            "before_sha256": _sha256_text(str(before.get("content") or "")) if before_exists else "",
            "after_sha256": _sha256_text(str(after.get("content") or "")) if after_exists else "",
            "truncated": bool(before.get("truncated") or after.get("truncated")),
            "metadata": dict(metadata or {}),
        },
        "authority": authority,
    }


def _read_snapshot_text(path: Path) -> dict[str, Any]:
    try:
        with path.resolve().open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(MAX_DIFF_CONTENT_CHARS + 1)
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"diff snapshot not found: {exc}") from exc
    truncated = len(content) > MAX_DIFF_CONTENT_CHARS
    return {"content": content[:MAX_DIFF_CONTENT_CHARS], "truncated": truncated}


def _safe_write_review_id(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("write-review-"):
        return ""
    safe = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "_"})
    return safe if safe == text else ""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
