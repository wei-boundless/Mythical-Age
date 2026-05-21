from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "ConversionBlock",
    "ConversionResult",
    "DocumentCacheLayout",
    "DoclingConverter",
    "SourceFileRecord",
    "build_markdown_blocks",
    "build_markdown_conversion_result",
    "discover_source_files",
    "infer_quality_flags",
]

_EXPORTS = {
    "ConversionBlock": ("knowledge_system.conversion.models", "ConversionBlock"),
    "ConversionResult": ("knowledge_system.conversion.models", "ConversionResult"),
    "DocumentCacheLayout": ("knowledge_system.conversion.cache", "DocumentCacheLayout"),
    "DoclingConverter": ("knowledge_system.conversion.docling_converter", "DoclingConverter"),
    "SourceFileRecord": ("knowledge_system.conversion.models", "SourceFileRecord"),
    "build_markdown_blocks": ("knowledge_system.conversion.structured_text", "build_markdown_blocks"),
    "build_markdown_conversion_result": ("knowledge_system.conversion.structured_text", "build_markdown_conversion_result"),
    "discover_source_files": ("knowledge_system.conversion.discovery", "discover_source_files"),
    "infer_quality_flags": ("knowledge_system.conversion.quality", "infer_quality_flags"),
}

if TYPE_CHECKING:
    from knowledge_system.conversion.cache import DocumentCacheLayout
    from knowledge_system.conversion.discovery import discover_source_files
    from knowledge_system.conversion.docling_converter import DoclingConverter
    from knowledge_system.conversion.models import ConversionBlock, ConversionResult, SourceFileRecord
    from knowledge_system.conversion.quality import infer_quality_flags
    from knowledge_system.conversion.structured_text import build_markdown_blocks, build_markdown_conversion_result


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
