from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CapabilitySystemPaths:
    base_dir: Path
    code_dir: Path
    units_dir: Path
    skills_dir: Path
    mcp_dir: Path
    registries_dir: Path
    skills_snapshot_path: Path
    skills_registry_path: Path
    tools_registry_path: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | Path) -> "CapabilitySystemPaths":
        resolved_base_dir = Path(base_dir).resolve()
        code_dir = resolved_base_dir / "capability_system"
        units_dir = code_dir / "units"
        registries_dir = units_dir / "registries"
        return cls(
            base_dir=resolved_base_dir,
            code_dir=code_dir,
            units_dir=units_dir,
            skills_dir=units_dir / "skills",
            mcp_dir=units_dir / "mcp",
            registries_dir=registries_dir,
            skills_snapshot_path=registries_dir / "SKILLS_SNAPSHOT.md",
            skills_registry_path=registries_dir / "SKILLS_REGISTRY.json",
            tools_registry_path=registries_dir / "TOOLS_REGISTRY.json",
        )

    def ensure(self) -> None:
        for path in (
            self.units_dir,
            self.skills_dir,
            self.mcp_dir,
            self.registries_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def to_relative_path(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.base_dir)).replace("\\", "/")

