from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


PREVIEW_LIMIT = 360
PROMPT_ID_HASH_ALGORITHM = "sha256"
PROMPT_ID_DIGEST_CHARS = 20
PROMPT_SECTION_HASH_ALGORITHM = "sha256"


@dataclass(slots=True)
class PromptSection:
    id: str
    title: str
    layer: str
    source: str
    model_visible: bool
    chars: int
    original_chars: int
    injected_chars: int
    content_hash: str
    hash_algorithm: str
    truncated: bool
    truncation_limit: int
    preview: str
    order: int
    cache: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PromptManifest:
    prompt_id: str
    session_id: str
    turn_id: str
    assembly_order: list[str]
    total_chars: int
    total_sections: int
    sections: list[PromptSection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sections"] = [section.to_dict() for section in self.sections]
        return payload


def make_prompt_id(*, session_id: str = "", turn_id: str = "", prompt_text: str = "") -> str:
    digest = hashlib.sha256(prompt_text.encode("utf-8", errors="ignore")).hexdigest()[:PROMPT_ID_DIGEST_CHARS]
    prefix = ":".join(part for part in [session_id, turn_id] if part)
    return f"{prefix}:{digest}" if prefix else digest


def prompt_section_content_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def prompt_section(
    *,
    section_id: str,
    title: str,
    layer: str,
    source: str,
    content: str | None,
    order: int,
    model_visible: bool = True,
    cache: dict[str, Any] | None = None,
    original_content: str | None = None,
    truncated: bool = False,
    truncation_limit: int = 0,
) -> PromptSection:
    text = str(content or "").strip()
    original_text = str(content if original_content is None else original_content or "").strip()
    return PromptSection(
        id=section_id,
        title=title,
        layer=layer,
        source=source,
        model_visible=model_visible,
        chars=len(text),
        original_chars=len(original_text),
        injected_chars=len(text),
        content_hash=prompt_section_content_hash(text),
        hash_algorithm=PROMPT_SECTION_HASH_ALGORITHM,
        truncated=bool(truncated),
        truncation_limit=max(0, int(truncation_limit or 0)),
        preview=_preview(text),
        order=order,
        cache=dict(cache or {}),
    )


def build_prompt_manifest(
    *,
    prompt_text: str,
    sections: list[PromptSection],
    session_id: str = "",
    turn_id: str = "",
    assembly_order: list[str] | tuple[str, ...],
) -> PromptManifest:
    visible_sections = [section for section in sections if section.chars > 0 or section.model_visible]
    return PromptManifest(
        prompt_id=make_prompt_id(session_id=session_id, turn_id=turn_id, prompt_text=prompt_text),
        session_id=session_id,
        turn_id=turn_id,
        assembly_order=list(assembly_order),
        total_chars=len(str(prompt_text or "")),
        total_sections=len(visible_sections),
        sections=visible_sections,
    )


def compact_prompt_manifest(manifest: PromptManifest | dict[str, Any] | None) -> dict[str, Any]:
    if manifest is None:
        return {}
    payload = manifest.to_dict() if isinstance(manifest, PromptManifest) else dict(manifest)
    sections = []
    for raw in list(payload.get("sections") or []):
        if not isinstance(raw, dict):
            continue
        sections.append(
            {
                "id": str(raw.get("id") or ""),
                "title": str(raw.get("title") or ""),
                "layer": str(raw.get("layer") or ""),
                "source": str(raw.get("source") or ""),
                "model_visible": bool(raw.get("model_visible", True)),
                "chars": int(raw.get("chars") or 0),
                "original_chars": int(raw.get("original_chars") or raw.get("chars") or 0),
                "injected_chars": int(raw.get("injected_chars") or raw.get("chars") or 0),
                "content_hash": str(raw.get("content_hash") or ""),
                "hash_algorithm": str(raw.get("hash_algorithm") or PROMPT_SECTION_HASH_ALGORITHM),
                "truncated": bool(raw.get("truncated") is True),
                "truncation_limit": int(raw.get("truncation_limit") or 0),
                "preview": _preview(str(raw.get("preview") or "")),
                "order": int(raw.get("order") or 0),
                "cache": dict(raw.get("cache") or {}) if isinstance(raw.get("cache"), dict) else {},
            }
        )
    return {
        "prompt_id": str(payload.get("prompt_id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "turn_id": str(payload.get("turn_id") or ""),
        "assembly_order": list(payload.get("assembly_order") or []),
        "total_chars": int(payload.get("total_chars") or 0),
        "total_sections": int(payload.get("total_sections") or len(sections)),
        "sections": sections,
    }


def _preview(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= PREVIEW_LIMIT:
        return normalized
    return normalized[: PREVIEW_LIMIT - 1].rstrip() + "…"


