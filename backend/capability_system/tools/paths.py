from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from capability_system.paths import resolve_capability_backend_dir


@dataclass(frozen=True, slots=True)
class CapabilityToolPaths:
    base_dir: Path
    code_dir: Path
    registries_dir: Path
    tools_registry_path: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | Path) -> "CapabilityToolPaths":
        resolved_base_dir = resolve_capability_backend_dir(base_dir)
        code_dir = resolved_base_dir / "capability_system" / "tools"
        registries_dir = code_dir / "registries"
        return cls(
            base_dir=resolved_base_dir,
            code_dir=code_dir,
            registries_dir=registries_dir,
            tools_registry_path=registries_dir / "TOOLS_REGISTRY.json",
        )

    def ensure(self) -> None:
        self.registries_dir.mkdir(parents=True, exist_ok=True)
