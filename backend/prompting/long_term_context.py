from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from memory_system.static_loader import load_static_context


def _strip_leading_markdown_title(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return content
    first_line = lines[0].lstrip()
    if first_line.startswith("# ") and not first_line.startswith("##"):
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
    memory_block = persistent_memory if persistent_memory is not None else ""

    return LongTermContextBundle(
        static_sections=[
            (entry.prompt_heading, entry.content)
            for entry in static_context.ordered_sections()
        ],
        memory_block=memory_block,
    )


