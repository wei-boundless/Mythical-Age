from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

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

router = APIRouter()


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
) -> CodeEnvironmentWorkspaceTreeResponse:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    return build_workspace_tree(
        layout.project_root,
        max_depth=max_depth,
        max_entries=max_entries,
    )


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
