from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json


@dataclass(frozen=True, slots=True)
class StaticContextSection:
    key: str
    label: str
    prompt_heading: str
    relative_paths: tuple[str, ...]
    injection_order: int


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


STATIC_SOUL_COMPONENTS: tuple[StaticContextSection, ...] = (
    StaticContextSection(
        key="protected_system_contract",
        label="Protected System Contract",
        prompt_heading="系统硬契约",
        relative_paths=("soul/agent_core/CORE.md",),
        injection_order=20,
    ),
    StaticContextSection(
        key="shared_common_contract",
        label="Shared Common Contract",
        prompt_heading="用户共同契约",
        relative_paths=("soul/common_contracts/catalog.json",),
        injection_order=30,
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
            content = path.read_text(encoding="utf-8")
            if relative_path.endswith("common_contracts/catalog.json"):
                content = _common_contract_catalog_content(content)
            return relative_path, content
    return relative_paths[0], f"[missing component: {relative_paths[0]}]"


def _common_contract_catalog_content(raw_content: str) -> str:
    try:
        payload = json.loads(raw_content or "{}")
    except json.JSONDecodeError:
        return raw_content
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return ""
    chunks: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            chunks.append(content)
    return "\n\n".join(chunks)


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
