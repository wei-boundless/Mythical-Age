from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PiEnvironmentMode = Literal["web_only", "desktop_host", "sidecar_ready", "sidecar_running", "error"]


class PiEnvironmentDiagnostic(BaseModel):
    level: Literal["info", "warning", "error"] = "info"
    code: str
    message: str
    path: str | None = None


class PiEnvironmentStatus(BaseModel):
    available: bool
    mode: PiEnvironmentMode
    enabled: bool = True
    sidecar_enabled: bool = False
    sidecar_mode: str = "diagnostic_only"
    pi_source_root: str
    pi_cli_path: str
    workspace_root: str
    config_source: str = "backend.config.runtime_config"
    workspace_root_policy: str = "project_root"
    node_version: str = ""
    npm_version: str = ""
    package_name: str = ""
    coding_agent_package_name: str = ""
    cli_built: bool = False
    rpc_source_available: bool = False
    diagnostics: list[PiEnvironmentDiagnostic] = Field(default_factory=list)


class HostCapabilityStatus(BaseModel):
    mode: Literal["web", "desktop"] = "web"
    local_runtime_available: bool = False
    vibe_coding_host_available: bool = False


class VibeCodingEnvironmentResponse(BaseModel):
    authority: str = "langchain-agent.vibe_coding.environment"
    host: HostCapabilityStatus
    pi: PiEnvironmentStatus


class PiSidecarStatus(BaseModel):
    running: bool = False
    pid: int | None = None
    workspace_root: str = ""
    cli_path: str = ""
    started_at: float | None = None
    last_error: str = ""
    stderr_tail: str = ""


class PiSidecarCommandRequest(BaseModel):
    command: Literal["get_state", "get_available_models"]


class PiSidecarCommandResponse(BaseModel):
    authority: str = "langchain-agent.vibe_coding.sidecar"
    command: str
    success: bool
    response: dict = Field(default_factory=dict)
    error: str = ""


class PiSidecarLifecycleResponse(BaseModel):
    authority: str = "langchain-agent.vibe_coding.sidecar"
    status: PiSidecarStatus
