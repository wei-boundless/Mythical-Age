from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeMCPPaths:
    base_dir: Path
    code_dir: Path
    external_servers_path: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | Path) -> "RuntimeMCPPaths":
        resolved_base_dir = Path(base_dir).resolve()
        return cls(
            base_dir=resolved_base_dir,
            code_dir=resolved_base_dir / "runtime" / "mcp",
            external_servers_path=resolved_base_dir / "mcp_external_servers.json",
        )

    def ensure(self) -> None:
        self.external_servers_path.parent.mkdir(parents=True, exist_ok=True)
