from __future__ import annotations

import re
from collections import Counter

from knowledge_system.ingestion.models import NormalizedBlock

_OBJECT_BLOCK_TYPES = {"table", "figure", "sheet_region", "json_field_group"}
_CAPTION_BLOCK_TYPES = {"table_caption", "figure_caption"}
_PLACEHOLDER_TEXTS = {
    "<!-- image -->",
    "<!-- table -->",
    "<!-- formula-not-decoded -->",
}
_DECORATIVE_HEADING_RE = re.compile(r"^(第[0-9一二三四五六七八九十百千万]+[章节篇部]|[ivxlcdm]+|ai)$", re.IGNORECASE)
_PAGE_NUMBER_RE = re.compile(r"^(page\s*)?\d{1,4}$", re.IGNORECASE)


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\u3000", " ").split()).strip()


def _looks_like_short_noise(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in _PLACEHOLDER_TEXTS:
        return False
    if _PAGE_NUMBER_RE.match(stripped):
        return True
    if len(stripped) <= 1:
        return True
    if len(stripped) <= 3 and re.fullmatch(r"[A-Za-z0-9.\-_/]+", stripped):
        return True
    return False


def _looks_like_decorative_heading(text: str) -> bool:
    stripped = text.strip("# ").strip()
    if not stripped:
        return True
    if _DECORATIVE_HEADING_RE.match(stripped):
        return True
    if len(stripped) <= 4 and re.fullmatch(r"[A-Za-z0-9]+", stripped):
        return True
    return False


def _looks_like_ocr_noise(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 16:
        return False
    bad_markers = sum(stripped.count(marker) for marker in ("�", "⟆", "∥", "\ufffd"))
    if bad_markers >= 2:
        return True
    punctuation = sum(1 for char in stripped if not char.isalnum() and not char.isspace())
    if punctuation / max(len(stripped), 1) > 0.45:
        return True
    return False


def clean_block(block: NormalizedBlock) -> NormalizedBlock:
    clean_text = _normalize_text(block.normalized_text or block.text)
    cleaning_flags: list[str] = []
    drop_reasons: list[str] = []

    if clean_text != (block.normalized_text or ""):
        cleaning_flags.append("normalized_whitespace")
    if clean_text in _PLACEHOLDER_TEXTS:
        cleaning_flags.append("placeholder_block")
        drop_reasons.append("placeholder_block")
    elif not clean_text:
        drop_reasons.append("empty_after_cleaning")
    elif block.block_type in {"heading", "title"} and _looks_like_decorative_heading(clean_text):
        cleaning_flags.append("decorative_heading")
        drop_reasons.append("decorative_heading")
    elif _looks_like_short_noise(clean_text):
        cleaning_flags.append("short_noise")
        drop_reasons.append("short_noise")
    elif _looks_like_ocr_noise(clean_text):
        cleaning_flags.append("ocr_noise")
        drop_reasons.append("ocr_noise")

    eligibility = "drop"
    index_profiles: tuple[str, ...] = ()

    if not drop_reasons:
        if block.block_type in _OBJECT_BLOCK_TYPES:
            eligibility = "keep_object_only"
            index_profiles = ("object_anchor",)
        elif block.block_type in _CAPTION_BLOCK_TYPES:
            if len(clean_text) < 12:
                eligibility = "keep_object_only"
                index_profiles = ("object_anchor",)
            else:
                eligibility = "keep"
                index_profiles = ("dense_main", "lexical_main", "object_anchor", "page_summary_source")
        elif block.block_type in {"heading", "title"}:
            eligibility = "keep"
            index_profiles = ("dense_main", "lexical_main", "page_summary_source")
        elif block.block_type in {"paragraph", "list_item", "section_block"}:
            eligibility = "keep"
            index_profiles = ("dense_main", "lexical_main", "page_summary_source")
        else:
            eligibility = "keep_summary_only"
            index_profiles = ("page_summary_source",)

    return NormalizedBlock(
        block_id=block.block_id,
        doc_id=block.doc_id,
        block_type=block.block_type,
        text=block.text,
        normalized_text=block.normalized_text,
        source_type=block.source_type,
        parser_backend=block.parser_backend,
        section_label=block.section_label,
        structure_role=block.structure_role,
        quality_flags=block.quality_flags,
        clean_text=clean_text,
        cleaning_flags=tuple(dict.fromkeys(cleaning_flags)),
        eligibility=eligibility,
        drop_reasons=tuple(dict.fromkeys(drop_reasons)),
        index_profiles=index_profiles,
        page=block.page,
        section_path=block.section_path,
        reading_order=block.reading_order,
        modality=block.modality,
        bbox=block.bbox,
        parent_block_id=block.parent_block_id,
        object_ref_ids=block.object_ref_ids,
        metadata=dict(block.metadata),
    )


def build_cleaning_manifest(blocks: list[NormalizedBlock]) -> dict[str, object]:
    eligibility_counter = Counter(block.eligibility for block in blocks)
    profile_counter = Counter(profile for block in blocks for profile in block.index_profiles)
    drop_reason_counter = Counter(reason for block in blocks for reason in block.drop_reasons)
    cleaning_flag_counter = Counter(flag for block in blocks for flag in block.cleaning_flags)
    return {
        "eligible_block_count": sum(1 for block in blocks if block.eligibility != "drop"),
        "dropped_block_count": sum(1 for block in blocks if block.eligibility == "drop"),
        "eligibility_breakdown": dict(eligibility_counter),
        "index_profile_counts": dict(profile_counter),
        "drop_reason_counts": dict(drop_reason_counter),
        "cleaning_flag_counts": dict(cleaning_flag_counter),
    }


