from __future__ import annotations

import socket
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout


FIXED_FRONTEND_PORT = 3000
FIXED_BACKEND_PORT = 8003


@dataclass(frozen=True, slots=True)
class PortGuardResult:
    ok: bool
    frontend_port: int = FIXED_FRONTEND_PORT
    backend_port: int = FIXED_BACKEND_PORT
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_fixed_project_ports() -> PortGuardResult:
    project_root = Path(__file__).resolve().parents[3]
    process_root = ProjectLayout.from_runtime_root(project_root).runtime_state_dir / "runtime_process"
    diagnostics = {
        "frontend": _port_probe(
            FIXED_FRONTEND_PORT,
            project_root=project_root,
            expected_command_markers=("next",),
            pid_file=process_root / "frontend-fixed-3000.pid",
        ),
        "backend": _port_probe(
            FIXED_BACKEND_PORT,
            project_root=project_root,
            expected_command_markers=("run_uvicorn.py",),
            pid_file=process_root / "backend-fixed-8003.pid",
        ),
        "policy": "fixed_project_ports",
    }
    ok = all(bool(dict(item).get("ok")) for item in (diagnostics["frontend"], diagnostics["backend"]))
    error = "" if ok else "fixed_project_port_error"
    return PortGuardResult(ok=ok, diagnostics=diagnostics, error=error)


def _port_probe(
    port: int,
    *,
    project_root: Path,
    expected_command_markers: tuple[str, ...],
    pid_file: Path,
) -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        result = sock.connect_ex(("127.0.0.1", int(port)))
    listening = result == 0
    process = _listener_process(port) if listening else {}
    owner_status = (
        _owner_status(
            process,
            project_root=project_root,
            expected_command_markers=expected_command_markers,
            pid_file=pid_file,
        )
        if listening
        else "not_listening"
    )
    ok = listening and owner_status in {"expected_project_process", "unknown_process_owner"}
    return {
        "port": int(port),
        "listening": listening,
        "ok": ok,
        "status": owner_status,
        "process": process,
        "summary": _port_summary(port=port, listening=listening, owner_status=owner_status, process=process),
    }


def _listener_process(port: int) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    f"$items = @(Get-NetTCPConnection -LocalPort {int(port)} "
                    "-State Listen -ErrorAction SilentlyContinue); "
                    "$c = $items | Where-Object { $_.LocalAddress -eq '127.0.0.1' } | Select-Object -First 1; "
                    "if ($null -eq $c) { $c = $items | Select-Object -First 1 }; "
                    "if ($null -ne $c) { "
                    "$p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; "
                    "$w = Get-CimInstance Win32_Process -Filter \"ProcessId=$($c.OwningProcess)\" -ErrorAction SilentlyContinue; "
                    "[pscustomobject]@{ pid=$c.OwningProcess; process_name=$p.ProcessName; path=$p.Path; command_line=$w.CommandLine } | ConvertTo-Json -Compress "
                    "}"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except Exception:
        return {"pid": 0, "process_name": "", "path": "", "owner_lookup": "failed"}
    output = str(result.stdout or "").strip()
    if not output:
        return {"pid": 0, "process_name": "", "path": "", "owner_lookup": "unavailable"}
    try:
        import json

        payload = json.loads(output)
    except Exception:
        return {"pid": 0, "process_name": "", "path": "", "owner_lookup": "parse_failed"}
    return {
        "pid": int(payload.get("pid") or 0),
        "process_name": str(payload.get("process_name") or ""),
        "path": str(payload.get("path") or ""),
        "command_line": str(payload.get("command_line") or ""),
        "owner_lookup": "ok",
    }


def _owner_status(
    process: dict[str, Any],
    *,
    project_root: Path,
    expected_command_markers: tuple[str, ...],
    pid_file: Path,
) -> str:
    if str(process.get("owner_lookup") or "") != "ok":
        return "unknown_process_owner"
    pid = int(process.get("pid") or 0)
    managed_pid = _read_pid_file(pid_file)
    if managed_pid and pid == managed_pid:
        return "expected_project_process"
    command_line = str(process.get("command_line") or "").lower()
    project_marker = str(project_root).lower()
    if project_marker in command_line and all(marker.lower() in command_line for marker in expected_command_markers):
        return "expected_project_process"
    if all(marker.lower() in command_line for marker in expected_command_markers) and _fixed_port_command_marker(command_line):
        return "expected_project_process"
    return "wrong_process_on_fixed_port"


def _fixed_port_command_marker(command_line: str) -> bool:
    normalized = " ".join(str(command_line or "").lower().split())
    return "--port 8003" in normalized or "-p 3000" in normalized


def _read_pid_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def _port_summary(*, port: int, listening: bool, owner_status: str, process: dict[str, Any]) -> str:
    if not listening:
        return f"Fixed port {port} is not listening."
    if owner_status == "wrong_process_on_fixed_port":
        return f"Fixed port {port} is occupied by non-project process {process.get('process_name') or process.get('pid') or 'unknown'}."
    if owner_status == "unknown_process_owner":
        return f"Fixed port {port} is listening, but process ownership could not be confirmed."
    return f"Fixed port {port} is listening with expected process ownership."



