from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from api.deps import require_runtime
from project_layout import ProjectLayout
from code_environment.models import (
    CodeEnvironmentResponse,
    CodeEnvironmentWorkspaceTreeResponse,
    PiSidecarCommandRequest,
    PiSidecarCommandResponse,
    PiSidecarLifecycleResponse,
)
from code_environment.pi_environment import build_code_environment_status
from code_environment.pi_rpc_process import PI_SIDECAR_MANAGER
from code_environment.workspace_tree import build_workspace_tree
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query

router = APIRouter()

GIT_STATUS_CACHE_TTL_SECONDS = 15.0
_GIT_STATUS_CACHE: dict[str, tuple[float, dict[str, object]]] = {}


@router.get("/code-environment/environment")
async def code_environment(
    host_mode: str = Query(default="web"),
    local_runtime_available: bool = Query(default=False),
    code_environment_host_available: bool = Query(default=False),
) -> CodeEnvironmentResponse:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    return build_code_environment_status(
        project_root=layout.project_root,
        host_mode=host_mode,
        local_runtime_available=local_runtime_available,
        code_environment_host_available=code_environment_host_available,
    )


@router.get("/code-environment/workspace-tree")
async def code_environment_workspace_tree(
    max_depth: Annotated[int, Query(ge=1, le=12)] = 10,
    max_entries: Annotated[int, Query(ge=100, le=50000)] = 10000,
    session_id: str | None = Query(default=None, max_length=200),
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> CodeEnvironmentWorkspaceTreeResponse:
    root = _workspace_tree_root(
        session_id=session_id,
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Workspace root not found")
    return build_workspace_tree(
        root,
        max_depth=max_depth,
        max_entries=max_entries,
    )


@router.post("/code-environment/open-workspace-root")
async def open_code_environment_workspace_root() -> dict[str, object]:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    project_root = layout.project_root.resolve()
    if not project_root.is_dir():
        raise HTTPException(status_code=404, detail="Workspace root not found")
    try:
        _open_directory(project_root)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "authority": "langchain-agent.code_environment.open_workspace_root",
        "opened": True,
        "path": str(project_root),
    }


def _open_directory(path: Path) -> None:
    target = path.resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    command = ["open", str(target)] if sys.platform == "darwin" else ["xdg-open", str(target)]
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Cannot open workspace directory: {command[0]} is not available") from exc


def _workspace_tree_root(
    *,
    session_id: str | None,
    workspace_view: str | None,
    task_environment_id: str | None,
    project_id: str | None,
) -> Path:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    if not session_id:
        return layout.project_root.resolve()
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    binding = runtime.session_manager.get_project_binding(session_id)
    workspace_root = str(binding.get("workspace_root") or "").strip()
    if not workspace_root:
        raise HTTPException(status_code=409, detail="session has no project binding")
    return Path(workspace_root).expanduser().resolve()


@router.get("/code-environment/git-status")
async def code_environment_git_status(refresh: bool = Query(default=False)) -> dict[str, object]:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    return _cached_git_status(layout.project_root, refresh=refresh)


def _cached_git_status(project_root: Path, *, refresh: bool) -> dict[str, object]:
    cache_key = str(project_root.resolve())
    now = time.monotonic()
    cached = _GIT_STATUS_CACHE.get(cache_key)
    if not refresh and cached is not None:
        captured_monotonic, payload = cached
        if now - captured_monotonic <= GIT_STATUS_CACHE_TTL_SECONDS:
            response = dict(payload)
            response["cache_status"] = "cached"
            return response

    payload = _collect_git_status(project_root)
    payload["captured_at"] = time.time()
    payload["cache_status"] = "fresh"
    payload["ttl_seconds"] = GIT_STATUS_CACHE_TTL_SECONDS
    _GIT_STATUS_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload


def _collect_git_status(project_root: Path) -> dict[str, object]:
    try:
        branch_result = subprocess.run(
            ["git", "-C", str(project_root), "branch", "--show-current"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        status_result = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain=v1", "-b"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        diff_stat_result = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--numstat", "HEAD", "--"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "authority": "code_environment.git_status",
            "available": False,
            "branch": "",
            "items": [],
            "diff_stat": {"additions": 0, "deletions": 0},
            "gh_available": shutil.which("gh") is not None,
            "error": str(exc),
        }
    if status_result.returncode != 0:
        return {
            "authority": "code_environment.git_status",
            "available": False,
            "branch": branch_result.stdout.strip(),
            "items": [],
            "diff_stat": {"additions": 0, "deletions": 0},
            "gh_available": shutil.which("gh") is not None,
            "error": status_result.stderr.strip() or "git status failed",
        }
    lines = [line for line in status_result.stdout.splitlines() if line.strip()]
    items = []
    for line in lines:
        if line.startswith("##"):
            continue
        status = line[:2].strip() or "?"
        path = line[3:].strip() if len(line) > 3 else ""
        items.append({"status": status, "path": path})
    additions = 0
    deletions = 0
    if diff_stat_result.returncode == 0:
        for line in diff_stat_result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added, deleted = parts[0], parts[1]
            if added.isdigit():
                additions += int(added)
            if deleted.isdigit():
                deletions += int(deleted)
    return {
        "authority": "code_environment.git_status",
        "available": True,
        "branch": branch_result.stdout.strip(),
        "items": items,
        "changed_count": len(items),
        "diff_stat": {"additions": additions, "deletions": deletions},
        "gh_available": shutil.which("gh") is not None,
        "error": "",
    }


@router.get("/code-environment/sidecar/status")
async def code_environment_sidecar_status() -> PiSidecarLifecycleResponse:
    return PiSidecarLifecycleResponse(status=PI_SIDECAR_MANAGER.status())


@router.post("/code-environment/sidecar/start")
async def start_code_environment_sidecar() -> PiSidecarLifecycleResponse:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    environment = build_code_environment_status(project_root=layout.project_root)
    if not environment.pi.cli_built:
        raise HTTPException(status_code=409, detail="Pi CLI is not built. Build packages/coding-agent before starting the sidecar.")
    try:
        status = PI_SIDECAR_MANAGER.start(
            cli_path=environment.pi.pi_cli_path,
            workspace_root=layout.project_root,
        )
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return PiSidecarLifecycleResponse(status=status)


@router.post("/code-environment/sidecar/stop")
async def stop_code_environment_sidecar() -> PiSidecarLifecycleResponse:
    return PiSidecarLifecycleResponse(status=PI_SIDECAR_MANAGER.stop())


@router.post("/code-environment/sidecar/read-only-command")
async def code_environment_sidecar_readonly_command(payload: PiSidecarCommandRequest) -> PiSidecarCommandResponse:
    try:
        response = PI_SIDECAR_MANAGER.send_readonly_command(payload.command)
    except (RuntimeError, TimeoutError, ValueError) as exc:
        return PiSidecarCommandResponse(
            command=payload.command,
            success=False,
            error=str(exc),
        )
    return PiSidecarCommandResponse(
        command=payload.command,
        success=bool(response.get("success")),
        response=response,
        error=str(response.get("error") or ""),
    )
