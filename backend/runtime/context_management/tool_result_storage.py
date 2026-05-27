from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .budget import estimate_json_bytes


PERSISTED_OUTPUT_TAG = "<persisted-output>"
DEFAULT_PREVIEW_SIZE_BYTES = 2000
DEFAULT_FIELD_SIZE_LIMIT_BYTES = 6000
DEFAULT_PAYLOAD_BUDGET_BYTES = 24000
TOOL_RESULTS_SUBDIR = "tool-results"


@dataclass(frozen=True, slots=True)
class ContentReplacement:
    replacement_id: str
    path: str
    json_path: str
    original_size_bytes: int
    preview_size_bytes: int
    has_more: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "replacement_id": self.replacement_id,
            "path": self.path,
            "json_path": self.json_path,
            "original_size_bytes": self.original_size_bytes,
            "preview_size_bytes": self.preview_size_bytes,
            "has_more": self.has_more,
        }


class ToolResultStore:
    def __init__(self, root_dir: Path, *, run_id: str = "", namespace: str = "runtime_context") -> None:
        self.root_dir = Path(root_dir)
        safe_run = _safe_path_part(run_id or "default")
        safe_namespace = _safe_path_part(namespace or "runtime_context")
        self.base_dir = self.root_dir / "storage" / safe_namespace / TOOL_RESULTS_SUBDIR / safe_run

    def apply_budget(
        self,
        payload: dict[str, Any],
        *,
        field_limit_bytes: int = DEFAULT_FIELD_SIZE_LIMIT_BYTES,
        preview_size_bytes: int = DEFAULT_PREVIEW_SIZE_BYTES,
        payload_budget_bytes: int = DEFAULT_PAYLOAD_BUDGET_BYTES,
    ) -> tuple[dict[str, Any], tuple[ContentReplacement, ...]]:
        cloned = _json_clone(payload)
        replacements: list[ContentReplacement] = []
        for json_path, value in _walk_strings(cloned):
            if not _is_budgeted_field(json_path):
                continue
            size = len(value.encode("utf-8", errors="replace"))
            if size <= field_limit_bytes and estimate_json_bytes(cloned) <= payload_budget_bytes:
                continue
            replacement = self._persist(
                content=value,
                json_path=json_path,
                preview_size_bytes=preview_size_bytes,
            )
            _set_json_path(cloned, json_path, replacement_text(value, replacement, preview_size_bytes=preview_size_bytes))
            replacements.append(replacement)
        return cloned, tuple(replacements)

    def _persist(self, *, content: str, json_path: str, preview_size_bytes: int) -> ContentReplacement:
        encoded = content.encode("utf-8", errors="replace")
        digest = hashlib.sha1((json_path + "\n" + content[:4096]).encode("utf-8", errors="replace")).hexdigest()[:16]
        filename = f"{_safe_path_part(json_path)}-{digest}.txt"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self.base_dir / filename
        path.write_text(content, encoding="utf-8")
        preview_size = min(len(encoded), max(1, int(preview_size_bytes or DEFAULT_PREVIEW_SIZE_BYTES)))
        return ContentReplacement(
            replacement_id=f"tool_result:{digest}",
            path=str(path),
            json_path=json_path,
            original_size_bytes=len(encoded),
            preview_size_bytes=preview_size,
            has_more=len(encoded) > preview_size,
        )

    def resolve(self, replacement_id_or_path: str) -> str:
        target = str(replacement_id_or_path or "").strip()
        if not target:
            raise ValueError("replacement id or path is required")
        if target.startswith("tool_result:"):
            digest = target.split(":", 1)[1]
            matches = sorted(self.base_dir.glob(f"*-{digest}.txt"))
            if not matches:
                raise FileNotFoundError(target)
            return matches[0].read_text(encoding="utf-8")
        path = Path(target)
        if not path.is_absolute():
            path = self.base_dir / target
        resolved = path.resolve()
        base = self.base_dir.resolve()
        if base not in [resolved, *resolved.parents]:
            raise ValueError("replacement path is outside tool result store")
        return resolved.read_text(encoding="utf-8")


def replacement_text(content: str, replacement: ContentReplacement, *, preview_size_bytes: int) -> str:
    preview = _preview_bytes(content, preview_size_bytes)
    more = "\n[Full output persisted; read the referenced file if more evidence is required.]" if replacement.has_more else ""
    return (
        f"{PERSISTED_OUTPUT_TAG}\n"
        f"Path: {replacement.path}\n"
        f"Original bytes: {replacement.original_size_bytes}\n"
        f"Preview bytes: {replacement.preview_size_bytes}\n"
        f"Preview:\n{preview}{more}"
    ).strip()


def _preview_bytes(content: str, limit: int) -> str:
    encoded = content.encode("utf-8", errors="replace")
    clipped = encoded[: max(1, int(limit or DEFAULT_PREVIEW_SIZE_BYTES))]
    return clipped.decode("utf-8", errors="ignore").strip()


def _json_clone(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _walk_strings(value: Any, prefix: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_walk_strings(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_strings(child, f"{prefix}[{index}]"))
    elif isinstance(value, str):
        found.append((prefix, value))
    return found


def _set_json_path(root: Any, json_path: str, value: str) -> None:
    target = root
    parts = _parse_json_path(json_path)
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _parse_json_path(path: str) -> list[Any]:
    text = path[2:] if path.startswith("$.") else path
    parts: list[Any] = []
    buffer = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == ".":
            if buffer:
                parts.append(buffer)
                buffer = ""
            index += 1
            continue
        if char == "[":
            if buffer:
                parts.append(buffer)
                buffer = ""
            end = text.index("]", index)
            parts.append(int(text[index + 1 : end]))
            index = end + 1
            continue
        buffer += char
        index += 1
    if buffer:
        parts.append(buffer)
    return parts


def _is_budgeted_field(json_path: str) -> bool:
    lowered = json_path.lower()
    return any(
        token in lowered
        for token in (
            ".answer",
            ".answer_candidate",
            ".canonical_answer",
            ".content",
            ".raw_content",
            ".clean_text",
            ".diagnostics",
            ".html",
            ".markdown",
            ".summary",
            ".text",
            ".visible_text",
            ".web_payload",
        )
    )


def _safe_path_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or ""))
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")[:120] or "payload"


