from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from capability_system.paths import resolve_capability_backend_dir


@dataclass(frozen=True, slots=True)
class CapabilityMCPPaths:
    base_dir: Path
    code_dir: Path
    external_servers_path: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | Path) -> "CapabilityMCPPaths":
        resolved_base_dir = resolve_capability_backend_dir(base_dir)
        return cls(
            base_dir=resolved_base_dir,
            code_dir=resolved_base_dir / "capability_system" / "mcp",
            external_servers_path=resolved_base_dir / "mcp_external_servers.json",
        )

    def ensure(self) -> None:
        self.external_servers_path.parent.mkdir(parents=True, exist_ok=True)
