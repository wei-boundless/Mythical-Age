from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


DIAGNOSTIC_CACHE_KEY_HASH_ALGORITHM = "sha1"
DIAGNOSTIC_CACHE_KEY_DIGEST_CHARS = 20
DIAGNOSTIC_CONTENT_HASH_ALGORITHM = "sha1"
DIAGNOSTIC_CONTENT_HASH_DIGEST_CHARS = 20


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


class PromptSectionCache:
    """Prompt assembly diagnostic shim.

    Provider-side context cache is the only cache that can reduce model input
    billing. This class intentionally renders every time and only returns a
    byte-stability diagnostic so legacy callers keep their manifest shape
    without creating a second prompt-cache authority.
    """

    def __init__(self, *, max_entries: int = 128) -> None:
        self.max_entries = max(1, int(max_entries))

    def get_or_render(
        self,
        *,
        scope: str,
        inputs: dict[str, Any],
        render: Callable[[], str],
    ) -> tuple[str, PromptCacheDiagnostic]:
        key = prompt_cache_key(scope=scope, inputs=inputs)
        content = str(render() or "")
        return content, PromptCacheDiagnostic(
            scope=scope,
            status="bypassed",
            key=key,
            reason="provider_context_cache_is_authoritative",
            content_hash=stable_text_hash(content),
            chars=len(content),
        )

    def clear(self) -> None:
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_entries": self.max_entries,
            "entry_count": 0,
            "keys": [],
            "status": "diagnostic_only",
            "reason": "provider_context_cache_is_authoritative",
        }


STATIC_PROMPT_CACHE = PromptSectionCache()
STATIC_PROMPT_RENDERER_VERSION = "2026-05-22.v1"


def prompt_cache_key(*, scope: str, inputs: dict[str, Any]) -> str:
    payload = json.dumps(_json_stable(inputs), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    digest = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:DIAGNOSTIC_CACHE_KEY_DIGEST_CHARS]
    safe_scope = str(scope or "prompt").strip().replace(" ", "_")
    return f"{safe_scope}:{digest}"


def stable_text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha1(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:DIAGNOSTIC_CONTENT_HASH_DIGEST_CHARS]


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


