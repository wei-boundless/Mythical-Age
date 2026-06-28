from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "DOCUMENT_KERNEL_VERSION",
    "DetectedDocumentFormat",
    "DocumentDiagnostic",
    "DocumentProcessingBundle",
    "DocumentProcessingKernel",
    "DocumentFormatDetector",
    "DocumentConversionResource",
    "EvidenceProjection",
    "DocumentParserChunk",
    "OfficeDocumentIR",
    "OfficeProjection",
    "LocalDocumentParser",
    "ParsedContentCleaner",
    "RagProjection",
]

_EXPORTS = {
    "DOCUMENT_KERNEL_VERSION": ("capability_system.capabilities.document_processing.models", "DOCUMENT_KERNEL_VERSION"),
    "DetectedDocumentFormat": ("capability_system.capabilities.document_processing.models", "DetectedDocumentFormat"),
    "DocumentDiagnostic": ("capability_system.capabilities.document_processing.models", "DocumentDiagnostic"),
    "DocumentProcessingBundle": ("capability_system.capabilities.document_processing.models", "DocumentProcessingBundle"),
    "DocumentParserChunk": ("capability_system.capabilities.document_processing.models", "DocumentParserChunk"),
    "EvidenceProjection": ("capability_system.capabilities.document_processing.models", "EvidenceProjection"),
    "OfficeDocumentIR": ("capability_system.capabilities.document_processing.models", "OfficeDocumentIR"),
    "OfficeProjection": ("capability_system.capabilities.document_processing.models", "OfficeProjection"),
    "RagProjection": ("capability_system.capabilities.document_processing.models", "RagProjection"),
    "DocumentFormatDetector": ("capability_system.capabilities.document_processing.format_detector", "DocumentFormatDetector"),
    "DocumentProcessingKernel": ("capability_system.capabilities.document_processing.kernel", "DocumentProcessingKernel"),
    "DocumentConversionResource": (
        "capability_system.capabilities.document_processing.adapters.conversion_resource",
        "DocumentConversionResource",
    ),
    "LocalDocumentParser": ("capability_system.capabilities.document_processing.adapters.local_parser", "LocalDocumentParser"),
    "ParsedContentCleaner": ("capability_system.capabilities.document_processing.content_cleaner", "ParsedContentCleaner"),
}

if TYPE_CHECKING:
    from capability_system.capabilities.document_processing.format_detector import DocumentFormatDetector
    from capability_system.capabilities.document_processing.kernel import DocumentProcessingKernel
    from capability_system.capabilities.document_processing.models import (
        DOCUMENT_KERNEL_VERSION,
        DetectedDocumentFormat,
        DocumentDiagnostic,
        DocumentParserChunk,
        DocumentProcessingBundle,
        EvidenceProjection,
        OfficeDocumentIR,
        OfficeProjection,
        RagProjection,
    )
    from capability_system.capabilities.document_processing.adapters.conversion_resource import DocumentConversionResource
    from capability_system.capabilities.document_processing.adapters.local_parser import LocalDocumentParser
    from capability_system.capabilities.document_processing.content_cleaner import ParsedContentCleaner


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
