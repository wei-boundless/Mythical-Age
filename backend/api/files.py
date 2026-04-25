from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from tools.skills_scanner import scan_skills

router = APIRouter()

ALLOWED_PREFIXES = ("soul/", "durable_memory/", "skills/", "knowledge/")
ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md", "SKILLS_REGISTRY.json", "TOOLS_REGISTRY.json"}


class SaveFileRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str


def _read_text_with_fallback(file_path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk")
    for encoding in encodings:
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _resolve_path(relative_path: str) -> Path:
    runtime = require_runtime()

    normalized = relative_path.replace("\\", "/").strip("/")
    if normalized not in ALLOWED_ROOT_FILES and not normalized.startswith(ALLOWED_PREFIXES):
        raise HTTPException(status_code=400, detail="Path is not in the editable whitelist")

    candidate = (runtime.base_dir / normalized).resolve()
    base_dir = runtime.base_dir.resolve()
    if base_dir not in candidate.parents and candidate != base_dir:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    return candidate


@router.get("/files")
async def read_file(path: str = Query(..., min_length=1)) -> dict[str, str]:
    file_path = _resolve_path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "path": path.replace("\\", "/"),
        "content": _read_text_with_fallback(file_path),
    }


@router.post("/files")
async def save_file(payload: SaveFileRequest) -> dict[str, Any]:
    runtime = require_runtime()
    file_path = _resolve_path(payload.path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(payload.content, encoding="utf-8")

    normalized = payload.path.replace("\\", "/")
    runtime.refresh_indexes_for_path(normalized)

    return {"ok": True, "path": normalized}


@router.get("/skills")
async def list_skills() -> list[dict[str, Any]]:
    runtime = require_runtime()
    return [skill.__dict__ for skill in scan_skills(runtime.base_dir)]
