from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


DurableMemoryType = Literal["user", "feedback", "project", "reference"]


@dataclass(frozen=True, slots=True)
class StaticContextSection:
    label: str
    relative_paths: tuple[str, ...]


@dataclass(slots=True)
class StaticContextBundle:
    constitution_sections: list[tuple[str, str]] = field(default_factory=list)
    profile_sections: list[tuple[str, str]] = field(default_factory=list)

