from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from memory.static_loader import load_static_context
from memory_layout import DurableMemoryLayout


def _strip_leading_markdown_title(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return content
    if lines[0].lstrip().startswith("#"):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


@dataclass(slots=True)
class LongTermContextBundle:
    static_sections: list[tuple[str, str]]
    memory_block: str

    def render(
        self,
        *,
        truncate: Callable[[str, int], str],
        limit: int,
        include_memory_block: bool = True,
    ) -> str:
        sections: list[str] = []
        if self.static_sections:
            sections.append("## 当前延续生效的设定")
            for heading, content in self.static_sections:
                sections.extend(
                    [
                        "",
                        f"### {heading}",
                        truncate(_strip_leading_markdown_title(content), limit),
                    ]
                )

        if include_memory_block and self.memory_block.strip():
            sections.extend(
                [
                    "",
                    "## 你记得的长期事实",
                    truncate(_strip_leading_markdown_title(self.memory_block.strip()), limit),
                ]
            )

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
        static_sections=[
            (entry.prompt_heading, entry.content)
            for entry in static_context.ordered_sections()
        ],
        memory_block=memory_block,
    )
