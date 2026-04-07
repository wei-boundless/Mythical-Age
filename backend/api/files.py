from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from graph.agent import agent_manager
from graph.memory_indexer import memory_indexer
from tools.skills_scanner import refresh_snapshot, scan_skills
from tools.tool_registry import refresh_tool_registry

router = APIRouter()

ALLOWED_PREFIXES = ("context_profile/", "durable_memory/", "skills/", "knowledge/")
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
    if agent_manager.base_dir is None:
        raise HTTPException(status_code=503, detail="Agent manager is not initialized")

    normalized = relative_path.replace("\\", "/").strip("/")
    if normalized not in ALLOWED_ROOT_FILES and not normalized.startswith(ALLOWED_PREFIXES):
        raise HTTPException(status_code=400, detail="Path is not in the editable whitelist")

    candidate = (agent_manager.base_dir / normalized).resolve()
    base_dir = agent_manager.base_dir.resolve()
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
    file_path = _resolve_path(payload.path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(payload.content, encoding="utf-8")

    normalized = payload.path.replace("\\", "/")
    if normalized.startswith(("durable_memory/", "knowledge/", "skills/")):
        memory_indexer.rebuild_index()
    if normalized.startswith("skills/"):
        refresh_snapshot(agent_manager.base_dir)
        refresh_tool_registry(agent_manager.base_dir)
        if agent_manager.skill_registry is not None:
            agent_manager.skill_registry.reload()
        if agent_manager.tool_registry is not None:
            agent_manager.tool_registry.reload()

    return {"ok": True, "path": normalized}


@router.get("/skills")
async def list_skills() -> list[dict[str, Any]]:
    if agent_manager.base_dir is None:
        raise HTTPException(status_code=503, detail="Agent manager is not initialized")
    return [skill.__dict__ for skill in scan_skills(agent_manager.base_dir)]
