from __future__ import annotations

import socket
from dataclasses import asdict, dataclass, field
from typing import Any


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
    diagnostics = {
        "frontend": _port_probe(FIXED_FRONTEND_PORT),
        "backend": _port_probe(FIXED_BACKEND_PORT),
        "policy": "fixed_project_ports",
    }
    return PortGuardResult(ok=True, diagnostics=diagnostics)


def _port_probe(port: int) -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        result = sock.connect_ex(("127.0.0.1", int(port)))
    return {"port": int(port), "listening": result == 0}


