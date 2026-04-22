from __future__ import annotations

from normalized_ingestion.models import NormalizedBlock


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
