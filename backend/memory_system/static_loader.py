from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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


def load_static_context(_base_dir: Path) -> StaticContextBundle:
    return StaticContextBundle()


