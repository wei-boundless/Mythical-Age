from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from project_layout import ProjectLayout


@dataclass(frozen=True, slots=True)
class StaticContextSection:
    key: str
    label: str
    prompt_heading: str
    relative_paths: tuple[str, ...]
    injection_order: int
    scope: str = "backend"


@dataclass(frozen=True, slots=True)
class StaticContextEntry:
    key: str
    label: str
    prompt_heading: str
    relative_path: str
    injection_order: int
    content: str


@dataclass(slots=True)
class StaticContextBundle:
    sections: list[StaticContextEntry] = field(default_factory=list)

    def ordered_sections(self) -> list[StaticContextEntry]:
        return sorted(self.sections, key=lambda item: item.injection_order)


STATIC_CONTEXT_COMPONENTS: tuple[StaticContextSection, ...] = (
    StaticContextSection(
        key="system_agents_rules",
        label="System AGENTS Rules",
        prompt_heading="系统 AGENTS 规则",
        relative_paths=("agent_context/AGENTS.md",),
        injection_order=20,
    ),
    StaticContextSection(
        key="project_agents_rules",
        label="Project AGENTS Rules",
        prompt_heading="项目 AGENTS 规则",
        relative_paths=("AGENTS.md",),
        injection_order=30,
        scope="project",
    ),
)

def _read_component(layout: ProjectLayout, section: StaticContextSection) -> tuple[str, str]:
    base_path = layout.project_root if section.scope == "project" else layout.backend_dir
    for relative_path in section.relative_paths:
        path = base_path / relative_path
        if path.exists():
            source_ref = relative_path if section.scope == "project" else f"backend/{relative_path}"
            return source_ref, path.read_text(encoding="utf-8")
    missing_ref = section.relative_paths[0] if section.scope == "project" else f"backend/{section.relative_paths[0]}"
    return missing_ref, f"[missing component: {missing_ref}]"


def load_static_context(base_dir: Path) -> StaticContextBundle:
    layout = ProjectLayout.from_backend_dir(base_dir)
    entries: list[StaticContextEntry] = []
    for section in STATIC_CONTEXT_COMPONENTS:
        relative_path, content = _read_component(layout, section)
        entries.append(
            StaticContextEntry(
                key=section.key,
                label=section.label,
                prompt_heading=section.prompt_heading,
                relative_path=relative_path,
                injection_order=section.injection_order,
                content=content,
            )
        )
    return StaticContextBundle(sections=entries)


