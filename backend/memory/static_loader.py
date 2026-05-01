from __future__ import annotations

from pathlib import Path

from memory.models import StaticContextBundle, StaticContextEntry, StaticContextSection


STATIC_SOUL_COMPONENTS: tuple[StaticContextSection, ...] = (
    StaticContextSection(
        key="agent_core",
        label="Common Contract",
        prompt_heading="共同契约",
        relative_paths=("soul/agent_core/CORE.md",),
        injection_order=20,
    ),
    StaticContextSection(
        key="active_soul_seed",
        label="Active Soul Seed",
        prompt_heading="当前风格",
        relative_paths=("soul/agent_core/ACTIVE_SEED.md",),
        injection_order=10,
    ),
)

def _read_component(base_dir: Path, relative_paths: tuple[str, ...]) -> tuple[str, str]:
    for relative_path in relative_paths:
        path = base_dir / relative_path
        if path.exists():
            return relative_path, path.read_text(encoding="utf-8")
    return relative_paths[0], f"[missing component: {relative_paths[0]}]"


def load_static_context(base_dir: Path) -> StaticContextBundle:
    entries: list[StaticContextEntry] = []
    for section in STATIC_SOUL_COMPONENTS:
        relative_path, content = _read_component(base_dir, section.relative_paths)
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
