from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class PromptCacheDiagnostic:
    scope: str
    status: str
    key: str
    reason: str
    content_hash: str
    chars: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PromptCacheEntry:
    key: str
    content: str
    content_hash: str
    chars: int


class PromptSectionCache:
    def __init__(self, *, max_entries: int = 128) -> None:
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[str, PromptCacheEntry] = OrderedDict()
        self._lock = RLock()

    def get_or_render(
        self,
        *,
        scope: str,
        inputs: dict[str, Any],
        render: Callable[[], str],
    ) -> tuple[str, PromptCacheDiagnostic]:
        key = prompt_cache_key(scope=scope, inputs=inputs)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                return entry.content, PromptCacheDiagnostic(
                    scope=scope,
                    status="hit",
                    key=key,
                    reason="byte_stable_prefix_reused",
                    content_hash=entry.content_hash,
                    chars=entry.chars,
                )

        content = str(render() or "")
        entry = PromptCacheEntry(
            key=key,
            content=content,
            content_hash=stable_text_hash(content),
            chars=len(content),
        )
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return content, PromptCacheDiagnostic(
            scope=scope,
            status="miss",
            key=key,
            reason="cache_key_not_found",
            content_hash=entry.content_hash,
            chars=entry.chars,
        )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_entries": self.max_entries,
                "entry_count": len(self._entries),
                "keys": list(self._entries.keys()),
            }


STATIC_PROMPT_CACHE = PromptSectionCache()
STATIC_PROMPT_RENDERER_VERSION = "2026-05-22.v1"


def prompt_cache_key(*, scope: str, inputs: dict[str, Any]) -> str:
    payload = json.dumps(_json_stable(inputs), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:20]
    safe_scope = str(scope or "prompt").strip().replace(" ", "_")
    return f"{safe_scope}:{digest}"


def stable_text_hash(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:20]


def static_prompt_cache_inputs(
    *,
    base_dir: Path,
    rag_mode: bool,
    component_char_limit: int,
    static_sections: list[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "renderer_version": STATIC_PROMPT_RENDERER_VERSION,
        "base_dir": str(Path(base_dir).resolve()),
        "rag_mode": bool(rag_mode),
        "component_char_limit": int(component_char_limit),
        "static_sections": [
            {
                "heading": str(heading or ""),
                "content_hash": stable_text_hash(str(content or "")),
                "chars": len(str(content or "")),
            }
            for heading, content in list(static_sections or [])
        ],
    }


def uncached_prompt_diagnostic(*, scope: str, reason: str, content: str | None = None) -> PromptCacheDiagnostic:
    text = str(content or "")
    return PromptCacheDiagnostic(
        scope=scope,
        status="bypassed",
        key="",
        reason=reason,
        content_hash=stable_text_hash(text) if text else "",
        chars=len(text),
    )


def reset_prompt_caches() -> None:
    STATIC_PROMPT_CACHE.clear()


def prompt_cache_snapshot() -> dict[str, Any]:
    return {
        "static_prompt": STATIC_PROMPT_CACHE.snapshot(),
    }


def _json_stable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
