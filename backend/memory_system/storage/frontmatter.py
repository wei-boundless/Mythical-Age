from __future__ import annotations

from collections.abc import Iterable


def parse_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}, markdown
    raw = markdown[4:end]
    body = markdown[end + 5 :]
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data, body


def format_frontmatter(values: dict[str, str | Iterable[str]]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, str):
            rendered = value
        else:
            rendered = "[" + ", ".join(value) + "]"
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines)


