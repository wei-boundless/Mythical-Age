from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from memory.static_loader import load_static_context
from memory_layout import DurableMemoryLayout


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

def build_long_term_context_bundle(
    base_dir: Path,
    *,
    persistent_memory: str | None = None,
) -> LongTermContextBundle:
    static_context = load_static_context(base_dir)
    if persistent_memory is not None:
        memory_block = persistent_memory
    else:
        layout = DurableMemoryLayout(base_dir / "durable_memory")
        if layout.index_path.exists():
            memory_block = layout.index_path.read_text(encoding="utf-8")
        else:
            memory_block = "[missing component: durable_memory/index/MEMORY.md]"

    return LongTermContextBundle(
        constitution_sections=list(static_context.constitution_sections),
        profile_sections=list(static_context.profile_sections),
        memory_block=memory_block,
    )
