from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "ConversionBlock",
    "ConversionResult",
    "DocumentCacheV2Layout",
    "DoclingConverter",
    "SourceFileRecord",
    "build_markdown_blocks",
    "build_markdown_conversion_result",
    "discover_source_files",
    "infer_quality_flags",
]

_EXPORTS = {
    "ConversionBlock": ("document_conversion.models", "ConversionBlock"),
    "ConversionResult": ("document_conversion.models", "ConversionResult"),
    "DocumentCacheV2Layout": ("document_conversion.cache", "DocumentCacheV2Layout"),
    "DoclingConverter": ("document_conversion.docling_converter", "DoclingConverter"),
    "SourceFileRecord": ("document_conversion.models", "SourceFileRecord"),
    "build_markdown_blocks": ("document_conversion.structured_text", "build_markdown_blocks"),
    "build_markdown_conversion_result": ("document_conversion.structured_text", "build_markdown_conversion_result"),
    "discover_source_files": ("document_conversion.discovery", "discover_source_files"),
    "infer_quality_flags": ("document_conversion.quality", "infer_quality_flags"),
}

if TYPE_CHECKING:
    from document_conversion.cache import DocumentCacheV2Layout
    from document_conversion.discovery import discover_source_files
    from document_conversion.docling_converter import DoclingConverter
    from document_conversion.models import ConversionBlock, ConversionResult, SourceFileRecord
    from document_conversion.quality import infer_quality_flags
    from document_conversion.structured_text import build_markdown_blocks, build_markdown_conversion_result


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
