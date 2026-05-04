from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}, text
    data = yaml.safe_load(match.group(1)) or {}
    meta = data if isinstance(data, dict) else {}
    return meta, text[match.end() :]


def write_skill_frontmatter(path: Path, meta: dict[str, Any], body: str) -> None:
    frontmatter = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{frontmatter}\n---\n\n{body.lstrip()}", encoding="utf-8")


def normalize_tool_names(tool_names: list[str], known_tools: set[str]) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for value in tool_names:
        name = str(value or "").strip()
        if not name or name in seen or name not in known_tools:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def set_skill_allowed_tools(path: Path, allowed_tools: list[str], known_tools: set[str]) -> list[str]:
    text = read_text(path)
    meta, body = parse_frontmatter(text)
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    metadata["allowed_tools"] = normalize_tool_names(allowed_tools, known_tools)
    meta["metadata"] = metadata
    write_skill_frontmatter(path, meta, body)
    return list(metadata["allowed_tools"])


def set_skill_prompt_view(path: Path, prompt_view: dict[str, str]) -> dict[str, str]:
    text = read_text(path)
    meta, body = parse_frontmatter(text)
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    existing = meta.get("prompt") if isinstance(meta.get("prompt"), dict) else meta.get("prompt_view")
    if not isinstance(existing, dict):
        existing = {}
    next_prompt = {
        "name": str(prompt_view.get("name") or existing.get("name") or meta.get("name") or "").strip(),
        "title": str(prompt_view.get("title") or existing.get("title") or metadata.get("display_name") or meta.get("name") or "").strip(),
        "capability": str(prompt_view.get("capability") or existing.get("capability") or meta.get("description") or "").strip(),
        "use_when": str(prompt_view.get("use_when") if prompt_view.get("use_when") is not None else existing.get("use_when") or "").strip(),
        "output_rule": str(prompt_view.get("output_rule") or existing.get("output_rule") or "").strip(),
    }
    meta.pop("prompt_view", None)
    meta["prompt"] = next_prompt
    write_skill_frontmatter(path, meta, body)
    return next_prompt

