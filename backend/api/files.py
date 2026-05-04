from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system.paths import CapabilitySystemPaths
from capability_system.skill_scanner import scan_skills
from project_layout import ProjectLayout

router = APIRouter()

READABLE_PREFIXES = (
    "soul/",
    "durable_memory/",
    "session-memory/",
    "sessions/",
    "knowledge/",
    "capability_system/units/skills/",
    "capability_system/units/mcp/",
    "capability_system/units/registries/",
)

EDITABLE_PREFIXES = (
    "soul/",
    "durable_memory/",
    "session-memory/",
    "sessions/",
    "knowledge/",
    "capability_system/units/skills/",
    "capability_system/units/mcp/",
)


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


def _resolve_path(relative_path: str, *, for_write: bool = False) -> Path:
    runtime = require_runtime()
    layout = ProjectLayout.from_backend_dir(runtime.base_dir)
    capability_paths = CapabilitySystemPaths.from_base_dir(runtime.base_dir)

    normalized = relative_path.replace("\\", "/").strip("/")
    allowed_prefixes = EDITABLE_PREFIXES if for_write else READABLE_PREFIXES
    if not normalized.startswith(allowed_prefixes):
        detail = "Path is not in the editable whitelist" if for_write else "Path is not in the readable whitelist"
        raise HTTPException(status_code=400, detail=detail)

    if normalized.startswith("durable_memory/"):
        candidate = (layout.durable_memory_dir / normalized.removeprefix("durable_memory/")).resolve()
        allowed_root = layout.durable_memory_dir.resolve()
    elif normalized.startswith("session-memory/"):
        candidate = (layout.session_memory_dir / normalized.removeprefix("session-memory/")).resolve()
        allowed_root = layout.session_memory_dir.resolve()
    elif normalized.startswith("sessions/"):
        candidate = (layout.sessions_dir / normalized.removeprefix("sessions/")).resolve()
        allowed_root = layout.sessions_dir.resolve()
    elif normalized.startswith("capability_system/units/"):
        candidate = (runtime.base_dir / normalized).resolve()
        allowed_root = capability_paths.units_dir.resolve()
    else:
        candidate = (runtime.base_dir / normalized).resolve()
        allowed_root = runtime.base_dir.resolve()
    if allowed_root not in candidate.parents and candidate != allowed_root:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    return candidate


@router.get("/files")
async def read_file(path: str = Query(..., min_length=1)) -> dict[str, str]:
    file_path = _resolve_path(path, for_write=False)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "path": path.replace("\\", "/"),
        "content": _read_text_with_fallback(file_path),
    }


@router.post("/files")
async def save_file(payload: SaveFileRequest) -> dict[str, Any]:
    runtime = require_runtime()
    file_path = _resolve_path(payload.path, for_write=True)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(payload.content, encoding="utf-8")

    normalized = payload.path.replace("\\", "/")
    runtime.refresh_indexes_for_path(normalized)

    return {"ok": True, "path": normalized}


@router.get("/skills")
async def list_skills() -> list[dict[str, Any]]:
    runtime = require_runtime()
    return [skill.__dict__ for skill in scan_skills(runtime.base_dir)]
