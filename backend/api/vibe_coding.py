from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from project_layout import ProjectLayout
from vibe_coding.models import (
    PiSidecarCommandRequest,
    PiSidecarCommandResponse,
    PiSidecarLifecycleResponse,
    VibeCodingEnvironmentResponse,
)
from vibe_coding.pi_environment import build_vibe_coding_environment_status
from vibe_coding.pi_rpc_process import PI_SIDECAR_MANAGER

router = APIRouter()


@router.get("/vibe-coding/environment")
async def vibe_coding_environment(
    host_mode: str = Query(default="web"),
    local_runtime_available: bool = Query(default=False),
    vibe_coding_host_available: bool = Query(default=False),
) -> VibeCodingEnvironmentResponse:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    return build_vibe_coding_environment_status(
        project_root=layout.project_root,
        host_mode=host_mode,
        local_runtime_available=local_runtime_available,
        vibe_coding_host_available=vibe_coding_host_available,
    )


@router.get("/vibe-coding/sidecar/status")
async def vibe_coding_sidecar_status() -> PiSidecarLifecycleResponse:
    return PiSidecarLifecycleResponse(status=PI_SIDECAR_MANAGER.status())


@router.post("/vibe-coding/sidecar/start")
async def start_vibe_coding_sidecar() -> PiSidecarLifecycleResponse:
    layout = ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1])
    environment = build_vibe_coding_environment_status(project_root=layout.project_root)
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


@router.post("/vibe-coding/sidecar/stop")
async def stop_vibe_coding_sidecar() -> PiSidecarLifecycleResponse:
    return PiSidecarLifecycleResponse(status=PI_SIDECAR_MANAGER.stop())


@router.post("/vibe-coding/sidecar/read-only-command")
async def vibe_coding_sidecar_readonly_command(payload: PiSidecarCommandRequest) -> PiSidecarCommandResponse:
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
