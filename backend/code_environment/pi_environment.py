from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.config import runtime_config
from core.project_layout import ProjectLayout
from code_environment.models import (
    CodeEnvironmentResponse,
    HostCapabilityStatus,
    PiEnvironmentDiagnostic,
    PiEnvironmentMode,
    PiEnvironmentStatus,
)

DEFAULT_PI_SOURCE_ROOT = Path("D:/AI应用/pi-main")


def build_code_environment_status(
    *,
    project_root: str | Path | None = None,
    host_mode: str = "web",
    local_runtime_available: bool = False,
    code_environment_host_available: bool = False,
) -> CodeEnvironmentResponse:
    root = Path(project_root).resolve() if project_root is not None else ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1]).project_root
    config_payload = runtime_config.get_code_environment_config()
    sidecar_config = dict(config_payload.get("pi_sidecar") or {})
    pi_root = Path(
        os.environ.get("CODE_ENVIRONMENT_PI_SOURCE_ROOT")
        or sidecar_config.get("pi_source_root")
        or DEFAULT_PI_SOURCE_ROOT
    ).resolve()
    pi_cli = Path(
        os.environ.get("CODE_ENVIRONMENT_PI_CLI_PATH")
        or sidecar_config.get("pi_cli_path")
        or pi_root / "packages" / "coding-agent" / "dist" / "cli.js"
    ).resolve()
    diagnostics: list[PiEnvironmentDiagnostic] = []
    enabled = bool(config_payload.get("enabled", True))
    sidecar_enabled = bool(sidecar_config.get("enabled", False))
    sidecar_mode = str(sidecar_config.get("mode") or "diagnostic_only").strip() or "diagnostic_only"
    workspace_root_policy = str(config_payload.get("workspace_root_policy") or "project_root").strip() or "project_root"

    def build_response(
        *,
        available: bool,
        mode: PiEnvironmentMode,
        package_payload: dict[str, Any] | None = None,
        coding_agent_package_payload: dict[str, Any] | None = None,
        node_version: str = "",
        npm_version: str = "",
        cli_built: bool = False,
        rpc_source_available: bool = False,
    ) -> CodeEnvironmentResponse:
        return CodeEnvironmentResponse(
            host=HostCapabilityStatus(
                mode="desktop" if host_mode == "desktop" else "web",
                local_runtime_available=local_runtime_available,
                code_environment_host_available=code_environment_host_available,
            ),
            pi=PiEnvironmentStatus(
                available=available,
                mode=mode,
                enabled=enabled,
                sidecar_enabled=sidecar_enabled,
                sidecar_mode=sidecar_mode,
                pi_source_root=str(pi_root),
                pi_cli_path=str(pi_cli),
                workspace_root=str(root),
                workspace_root_policy=workspace_root_policy,
                node_version=node_version,
                npm_version=npm_version,
                package_name=str((package_payload or {}).get("name") or ""),
                coding_agent_package_name=str((coding_agent_package_payload or {}).get("name") or ""),
                cli_built=cli_built,
                rpc_source_available=rpc_source_available,
                diagnostics=diagnostics,
            ),
        )

    if not enabled:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="warning",
                code="code_environment_disabled",
                message="Professional code environment diagnostics are disabled in storage/runtime_config/config.json.",
            )
        )
        return build_response(available=False, mode="web_only")

    if not sidecar_enabled:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="info",
                code="pi_sidecar_optional",
                message="Pi sidecar is disabled; professional code tasks continue through the local runtime.",
            )
        )
        return build_response(available=False, mode="web_only")

    package_payload = _read_json(pi_root / "package.json")
    coding_agent_package_payload = _read_json(pi_root / "packages" / "coding-agent" / "package.json")
    node_version = _command_version(["node", "-v"], diagnostics, "node_version")
    npm_version = _command_version(["npm", "-v"], diagnostics, "npm_version")

    if not pi_root.exists():
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="error",
                code="pi_source_root_missing",
                message="Pi source root does not exist.",
                path=str(pi_root),
            )
        )
    if package_payload is None:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="error",
                code="pi_package_missing",
                message="Pi package.json was not found or could not be parsed.",
                path=str(pi_root / "package.json"),
            )
        )
    if coding_agent_package_payload is None:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="error",
                code="pi_coding_agent_package_missing",
                message="Pi coding-agent package.json was not found or could not be parsed.",
                path=str(pi_root / "packages" / "coding-agent" / "package.json"),
            )
        )

    cli_built = pi_cli.exists()
    rpc_source_available = (pi_root / "packages" / "coding-agent" / "src" / "modes" / "rpc" / "rpc-mode.ts").exists()
    if not cli_built:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="warning",
                code="pi_cli_not_built",
                message="Pi RPC CLI build output is missing. Build Pi before starting the sidecar.",
                path=str(pi_cli),
            )
        )
    if not rpc_source_available:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="error",
                code="pi_rpc_source_missing",
                message="Pi RPC source entry was not found.",
                path=str(pi_root / "packages" / "coding-agent" / "src" / "modes" / "rpc" / "rpc-mode.ts"),
            )
        )

    available = (
        pi_root.exists()
        and package_payload is not None
        and coding_agent_package_payload is not None
        and bool(node_version)
        and rpc_source_available
    )
    mode: PiEnvironmentMode = "sidecar_ready" if available and cli_built else "web_only"
    if any(item.level == "error" for item in diagnostics):
        mode = "error"

    return build_response(
        available=available,
        mode=mode,
        package_payload=package_payload,
        coding_agent_package_payload=coding_agent_package_payload,
        node_version=node_version,
        npm_version=npm_version,
        cli_built=cli_built,
        rpc_source_available=rpc_source_available,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _command_version(command: list[str], diagnostics: list[PiEnvironmentDiagnostic], code: str) -> str:
    resolved_command = [*command]
    resolved_executable = shutil.which(command[0])
    if resolved_executable:
        resolved_command[0] = resolved_executable
    try:
        completed = subprocess.run(
            resolved_command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="error",
                code=f"{code}_unavailable",
                message=f"Command unavailable: {' '.join(command)} ({exc})",
            )
        )
        return ""
    if completed.returncode != 0:
        diagnostics.append(
            PiEnvironmentDiagnostic(
                level="error",
                code=f"{code}_failed",
                message=(completed.stderr or completed.stdout or "Version command failed.").strip(),
            )
        )
        return ""
    return completed.stdout.strip()

