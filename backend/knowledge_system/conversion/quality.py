from __future__ import annotations

from knowledge_system.conversion.models import ConversionBlock


def infer_quality_flags(
    blocks: tuple[ConversionBlock, ...] | list[ConversionBlock],
    *,
    parser_backend: str,
) -> tuple[str, ...]:
    flags: list[str] = []
    if not blocks:
        flags.append("empty_conversion")
    if any(block.block_type == "table" for block in blocks):
        flags.append("table_dense")
    if any(block.modality == "image" for block in blocks):
        flags.append("image_heavy")
    if len({block.page for block in blocks if block.page is not None}) >= 10:
        flags.append("multi_page")
    if parser_backend != "docling":
        flags.append("fallback_parser")
    return tuple(dict.fromkeys(flags))


