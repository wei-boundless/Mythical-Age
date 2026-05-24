from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .port_guard import check_fixed_project_ports
from .runtime_environment import RuntimeEnvironment


@dataclass(frozen=True, slots=True)
class RuntimeConnectionHealth:
    ok: bool
    environment: dict[str, Any] = field(default_factory=dict)
    ports: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_runtime_connection_health(environment: RuntimeEnvironment) -> RuntimeConnectionHealth:
    port_guard = check_fixed_project_ports()
    snapshot = environment.snapshot()
    expected_api_base = "http://127.0.0.1:8003/api"
    api_base_ok = snapshot.get("api_base") == expected_api_base
    ok = bool(port_guard.ok and api_base_ok)
    return RuntimeConnectionHealth(
        ok=ok,
        environment=snapshot,
        ports=port_guard.to_dict(),
        diagnostics={
            "api_base_expected": expected_api_base,
            "api_base_actual": snapshot.get("api_base"),
            "api_base_ok": api_base_ok,
            "sse_status": "not_checked",
        },
        error="" if ok else "runtime_environment_error",
    )
