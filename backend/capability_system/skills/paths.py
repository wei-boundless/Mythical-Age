from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from capability_system.paths import resolve_capability_backend_dir


@dataclass(frozen=True, slots=True)
class CapabilitySkillPaths:
    base_dir: Path
    code_dir: Path
    skills_dir: Path
    registries_dir: Path
    skills_snapshot_path: Path
    skills_registry_path: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | Path) -> "CapabilitySkillPaths":
        resolved_base_dir = resolve_capability_backend_dir(base_dir)
        code_dir = resolved_base_dir / "capability_system" / "skills"
        registries_dir = code_dir / "registries"
        return cls(
            base_dir=resolved_base_dir,
            code_dir=code_dir,
            skills_dir=code_dir / "builtin",
            registries_dir=registries_dir,
            skills_snapshot_path=registries_dir / "SKILLS_SNAPSHOT.md",
            skills_registry_path=registries_dir / "SKILLS_REGISTRY.json",
        )

    def ensure(self) -> None:
        for path in (self.skills_dir, self.registries_dir):
            path.mkdir(parents=True, exist_ok=True)

    def to_relative_path(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.base_dir)).replace("\\", "/")
