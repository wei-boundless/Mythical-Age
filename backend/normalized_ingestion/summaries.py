from __future__ import annotations

import re

from normalized_ingestion.models import NormalizedBlock


def summarize_text_fragments(
    texts: list[str],
    *,
    max_chars: int = 720,
    max_fragments: int = 4,
) -> str:
    snippets: list[str] = []
    total_chars = 0
    seen: set[str] = set()
    for text in texts:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        snippets.append(normalized)
        total_chars += len(normalized)
        if len(snippets) >= max_fragments or total_chars >= max_chars:
            break
    merged = "\n\n".join(snippets).strip()
    if len(merged) <= max_chars:
        return merged
    return merged[: max_chars - 3].rstrip() + "..."


def summarize_page_blocks(
    page: int,
    blocks: list[NormalizedBlock],
    *,
    max_chars: int = 480,
) -> str:
    page_blocks = [
        block
        for block in blocks
        if block.page == page
        and block.clean_text
        and "page_summary_source" in block.index_profiles
        and block.eligibility != "drop"
    ]
    page_blocks.sort(key=lambda item: item.reading_order)
    if not page_blocks:
        return ""
    if len(page_blocks) < 2:
        return ""
    joined = " ".join(block.clean_text for block in page_blocks).strip()
    if len(joined) <= max_chars:
        return joined
    return joined[: max_chars - 3].rstrip() + "..."
