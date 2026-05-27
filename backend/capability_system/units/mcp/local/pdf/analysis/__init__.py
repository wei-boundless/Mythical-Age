from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "PdfAnalysisCatalog",
    "PdfTextParser",
]

_EXPORTS = {
    "PdfAnalysisCatalog": ("capability_system.units.mcp.local.pdf.analysis.catalog", "PdfAnalysisCatalog"),
    "PdfTextParser": ("capability_system.units.mcp.local.pdf.analysis.parser", "PdfTextParser"),
}

if TYPE_CHECKING:
    from .catalog import PdfAnalysisCatalog
    from .parser import PdfTextParser


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


