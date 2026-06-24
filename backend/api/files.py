from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system.skills.paths import CapabilitySkillPaths
from capability_system.skills.scanner import scan_skills
from capability_system.tools.paths import CapabilityToolPaths
from code_environment.workspace_tree import _is_excluded_relative_path
from memory_system.storage_layout import MemoryStorageLayout
from core.project_layout import ProjectLayout
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query

router = APIRouter()

READABLE_PREFIXES = (
    "durable_memory/",
    "session-memory/",
    "sessions/",
    "knowledge/",
    "capability_system/skills/builtin/",
    "capability_system/skills/registries/",
    "capability_system/tools/registries/",
    "backend/",
    "frontend/",
    "docs/",
    "scripts/",
)

EDITABLE_PREFIXES = (
    "durable_memory/",
    "session-memory/",
    "sessions/",
    "knowledge/",
    "capability_system/skills/builtin/",
)

READABLE_PROJECT_FILES = frozenset(
    {
        ".gitignore",
        "AGENTS.md",
        "README.md",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "pytest.ini",
        "requirements.txt",
        "tsconfig.json",
        "vitest.config.ts",
    }
)

PROJECT_READABLE_PREFIXES = (
    "backend/",
    "frontend/",
    "docs/",
    "scripts/",
)

SENSITIVE_PROJECT_FILE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)

SENSITIVE_PROJECT_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)

NON_TEXT_FILE_SUFFIXES = (
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".webp",
    ".zip",
)


class SaveFileRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str


@router.get("/workspace/context")
async def get_workspace_context() -> dict[str, Any]:
    runtime = require_runtime()
    layout = ProjectLayout.from_backend_dir(runtime.base_dir)
    return {
        "project_name": layout.project_root.name,
        "project_root": str(layout.project_root),
        "backend_root": str(layout.backend_dir),
        "storage_root": str(layout.storage_root),
        "editable_prefixes": list(EDITABLE_PREFIXES),
        "readable_prefixes": list(READABLE_PREFIXES),
    }


def _read_text_with_fallback(file_path: Path) -> str:
    if file_path.suffix.lower() in NON_TEXT_FILE_SUFFIXES:
        raise HTTPException(status_code=415, detail="File is not a supported text file")
    try:
        sample = file_path.read_bytes()[:4096]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if b"\x00" in sample:
        raise HTTPException(status_code=415, detail="File is not a supported text file")
    encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk")
    for encoding in encodings:
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _resolve_path(
    relative_path: str,
    *,
    for_write: bool = False,
    session_id: str | None = None,
    workspace_view: str | None = None,
    task_environment_id: str | None = None,
    project_id: str | None = None,
) -> Path:
    runtime = require_runtime()
    layout = ProjectLayout.from_backend_dir(runtime.base_dir)
    memory_layout = MemoryStorageLayout.from_project_layout(layout)
    skill_paths = CapabilitySkillPaths.from_base_dir(runtime.base_dir)
    tool_paths = CapabilityToolPaths.from_base_dir(runtime.base_dir)
    project_root = _session_project_root(
        runtime,
        session_id=session_id,
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    ) or layout.project_root.resolve()

    normalized = relative_path.replace("\\", "/").strip("/")
    if for_write and not _is_allowed_workspace_path(normalized, for_write=True):
        raise HTTPException(status_code=400, detail="Path is not in the editable whitelist")

    if normalized.startswith("durable_memory/"):
        durable_ref = normalized.removeprefix("durable_memory/")
        if durable_ref.startswith("environments/"):
            candidate = (memory_layout.durable_root / durable_ref).resolve()
        else:
            candidate = (memory_layout.durable_global_root / durable_ref).resolve()
        allowed_root = memory_layout.durable_root.resolve()
    elif normalized.startswith("session-memory/"):
        candidate = (memory_layout.session_root / normalized.removeprefix("session-memory/")).resolve()
        allowed_root = memory_layout.session_root.resolve()
    elif normalized.startswith("sessions/"):
        candidate = (layout.sessions_dir / normalized.removeprefix("sessions/")).resolve()
        allowed_root = layout.sessions_dir.resolve()
    elif normalized.startswith("knowledge/"):
        candidate = (layout.knowledge_storage_dir / normalized.removeprefix("knowledge/")).resolve()
        allowed_root = layout.knowledge_storage_dir.resolve()
    elif normalized.startswith("capability_system/skills/"):
        candidate = (skill_paths.code_dir / normalized.removeprefix("capability_system/skills/")).resolve()
        allowed_root = skill_paths.code_dir.resolve()
    elif normalized.startswith("capability_system/tools/registries/"):
        candidate = (tool_paths.registries_dir / normalized.removeprefix("capability_system/tools/registries/")).resolve()
        allowed_root = tool_paths.registries_dir.resolve()
    elif not for_write:
        candidate = (project_root / normalized).resolve()
        allowed_root = project_root
    else:
        candidate = (runtime.base_dir / normalized).resolve()
        allowed_root = runtime.base_dir.resolve()
    if allowed_root not in candidate.parents and candidate != allowed_root:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    if not for_write and not _is_readable_project_path(normalized, candidate, project_root):
        raise HTTPException(status_code=400, detail="Path is not visible in the project file tree")
    return candidate


def _is_allowed_workspace_path(normalized: str, *, for_write: bool) -> bool:
    if for_write:
        return normalized.startswith(EDITABLE_PREFIXES)
    return normalized in READABLE_PROJECT_FILES or normalized.startswith(READABLE_PREFIXES)


def _is_readable_project_path(normalized: str, candidate: Path, project_root: Path) -> bool:
    if normalized in READABLE_PROJECT_FILES or normalized.startswith(READABLE_PREFIXES):
        return True
    if _is_excluded_relative_path(normalized):
        return False
    name = candidate.name.lower()
    if name in SENSITIVE_PROJECT_FILE_NAMES:
        return False
    if any(name.endswith(suffix) for suffix in SENSITIVE_PROJECT_SUFFIXES):
        return False
    if project_root not in candidate.parents and candidate != project_root:
        return False
    return True


@router.get("/files")
async def read_file(
    path: str = Query(..., min_length=1),
    session_id: str | None = Query(default=None, max_length=200),
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, str]:
    return await asyncio.to_thread(
        _read_file_payload,
        path=path,
        session_id=session_id,
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )


@router.post("/files")
async def save_file(
    payload: SaveFileRequest,
    session_id: str | None = Query(default=None, max_length=200),
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    file_path = _resolve_path(
        payload.path,
        for_write=True,
        session_id=session_id,
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(payload.content, encoding="utf-8")

    normalized = payload.path.replace("\\", "/")
    runtime.refresh_indexes_for_path(normalized)

    return {"ok": True, "path": normalized}


def _session_project_root(
    runtime: Any,
    *,
    session_id: str | None,
    workspace_view: str | None,
    task_environment_id: str | None,
    project_id: str | None,
) -> Path | None:
    if not session_id:
        return None
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    binding = runtime.session_manager.get_project_binding(session_id)
    workspace_root = str(binding.get("workspace_root") or "").strip()
    if not workspace_root:
        raise HTTPException(status_code=409, detail="session has no project binding")
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Session project binding root not found")
    return root


@router.get("/skills")
async def list_skills() -> list[dict[str, Any]]:
    runtime = require_runtime()
    return await asyncio.to_thread(_list_skills_payload, runtime)


def _read_file_payload(
    *,
    path: str,
    session_id: str | None,
    workspace_view: str | None,
    task_environment_id: str | None,
    project_id: str | None,
) -> dict[str, str]:
    file_path = _resolve_path(
        path,
        for_write=False,
        session_id=session_id,
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    return {
        "path": path.replace("\\", "/"),
        "content": _read_text_with_fallback(file_path),
    }


def _list_skills_payload(runtime: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": skill.runtime.name,
            "title": skill.runtime.title,
            "description": skill.runtime.description,
            "path": skill.runtime.path,
        }
        for skill in scan_skills(runtime.base_dir)
    ]



