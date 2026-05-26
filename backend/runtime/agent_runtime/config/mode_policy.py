from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModePolicy:
    interaction_mode: str = "standard_mode"
    prompt_profile: str = ""
    memory_scope: str = ""
    output_style: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_mode": self.interaction_mode,
            "prompt_profile": self.prompt_profile,
            "memory_scope": self.memory_scope,
            "output_style": self.output_style,
            "metadata": dict(self.metadata),
        }
