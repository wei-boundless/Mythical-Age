from __future__ import annotations

from pathlib import Path

from memory.models import StaticContextBundle, StaticContextSection


STATIC_CONSTITUTION_COMPONENTS: tuple[StaticContextSection, ...] = (
    StaticContextSection("Soul", ("context_profile/constitution/SOUL.md",)),
    StaticContextSection("Identity", ("context_profile/constitution/IDENTITY.md",)),
)

STATIC_PROFILE_COMPONENTS: tuple[StaticContextSection, ...] = (
    StaticContextSection("User Profile", ("context_profile/profile/USER.md",)),
    StaticContextSection("Project Profile", ("context_profile/profile/PROJECT.md",)),
    StaticContextSection("Agents Guide", ("context_profile/profile/AGENTS.md",)),
)


def _read_component(base_dir: Path, relative_paths: tuple[str, ...]) -> str:
    for relative_path in relative_paths:
        path = base_dir / relative_path
        if path.exists():
            return path.read_text(encoding="utf-8")
    return f"[missing component: {relative_paths[0]}]"


def load_static_context(base_dir: Path) -> StaticContextBundle:
    return StaticContextBundle(
        constitution_sections=[
            (section.label, _read_component(base_dir, section.relative_paths))
            for section in STATIC_CONSTITUTION_COMPONENTS
        ],
        profile_sections=[
            (section.label, _read_component(base_dir, section.relative_paths))
            for section in STATIC_PROFILE_COMPONENTS
        ],
    )

