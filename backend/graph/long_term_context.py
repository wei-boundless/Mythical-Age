from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


STATIC_CONSTITUTION_COMPONENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Soul", ("context_profile/constitution/SOUL.md",)),
    ("Identity", ("context_profile/constitution/IDENTITY.md",)),
)

STATIC_PROFILE_COMPONENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("User Profile", ("context_profile/profile/USER.md",)),
    ("Agents Guide", ("context_profile/profile/AGENTS.md",)),
)


@dataclass(slots=True)
class LongTermContextBundle:
    constitution_sections: list[tuple[str, str]]
    profile_sections: list[tuple[str, str]]
    memory_block: str

    def render(
        self,
        *,
        truncate: Callable[[str, int], str],
        limit: int,
        include_memory_block: bool = True,
    ) -> str:
        sections: list[str] = []

        if self.constitution_sections:
            sections.append("## Constitution")
            for label, content in self.constitution_sections:
                sections.extend(["", f"### {label}", truncate(content, limit)])

        if self.profile_sections:
            sections.append("")
            sections.append("## Profile")
            for label, content in self.profile_sections:
                sections.extend(["", f"### {label}", truncate(content, limit)])

        if include_memory_block and self.memory_block.strip():
            sections.extend(["", "## Dynamic Long-Term Memory", truncate(self.memory_block.strip(), limit)])

        return "\n".join(section for section in sections if section is not None).strip()


def _read_component(base_dir: Path, relative_paths: str | tuple[str, ...]) -> str:
    if isinstance(relative_paths, str):
        relative_paths = (relative_paths,)
    for relative_path in relative_paths:
        path = base_dir / relative_path
        if path.exists():
            return path.read_text(encoding="utf-8")
    return f"[missing component: {relative_paths[0]}]"


def build_long_term_context_bundle(
    base_dir: Path,
    *,
    persistent_memory: str | None = None,
) -> LongTermContextBundle:
    constitution_sections = [
        (label, _read_component(base_dir, relative_path))
        for label, relative_path in STATIC_CONSTITUTION_COMPONENTS
    ]
    profile_sections = [
        (label, _read_component(base_dir, relative_path))
        for label, relative_path in STATIC_PROFILE_COMPONENTS
    ]
    if persistent_memory is not None:
        memory_block = persistent_memory
    else:
        memory_block = _read_component(base_dir, "durable_memory/MEMORY.md")

    return LongTermContextBundle(
        constitution_sections=constitution_sections,
        profile_sections=profile_sections,
        memory_block=memory_block,
    )
