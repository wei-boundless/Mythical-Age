from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from capability_system.capabilities.document_processing.adapters.conversion_resource import DocumentConversionResource
from knowledge_system.conversion.models import ConversionResult, SourceFileRecord
from knowledge_system.conversion.structured_text import build_markdown_conversion_result

from capability_system.capabilities.document_processing.format_detector import DocumentFormatDetector
from capability_system.capabilities.document_processing.ir_builder import build_office_ir_from_conversion
from capability_system.capabilities.document_processing.models import (
    DOCUMENT_KERNEL_VERSION,
    DetectedDocumentFormat,
    DocumentDiagnostic,
    DocumentProcessingBundle,
    build_document_bundle_id,
)
from capability_system.capabilities.document_processing.projections.evidence_projection import build_evidence_projection
from capability_system.capabilities.document_processing.projections.office_projection import build_office_projection
from capability_system.capabilities.document_processing.projections.rag_projection import RagProjectionBuilder


class DocumentProcessingKernel:
    def __init__(
        self,
        *,
        format_detector: DocumentFormatDetector | None = None,
        parser_resource: DocumentConversionResource | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.format_detector = format_detector or DocumentFormatDetector()
        self.parser_resource = parser_resource or DocumentConversionResource(
            enabled=True,
            repo_root=repo_root,
        )
        self.rag_projection_builder = RagProjectionBuilder()

    def parse(self, record: SourceFileRecord, *, parse_profile: str = "full") -> DocumentProcessingBundle:
        parse_profile = str(parse_profile or "full").strip().lower()
        if parse_profile not in {"full", "office_write"}:
            raise ValueError(f"unsupported_document_parse_profile:{parse_profile}")
        detected_format, diagnostics = self.format_detector.detect(record)
        bundle_id = build_document_bundle_id(record)
        parser_diagnostics = list(diagnostics)
        conversion = self._convert_record(record, detected_format, parse_profile=parse_profile)
        if conversion.parser_backend == "local_fallback" or conversion.fallback_used:
            parser_diagnostics.append(
                DocumentDiagnostic(
                    code="parser_resource_fallback_used",
                    severity="warning",
                    message="Document processing used a degraded parser resource for the RAG projection.",
                    details={
                        "source_path": record.source_path,
                        "source_parser_backend": conversion.parser_backend,
                        "source_parser_route": list(conversion.parser_route),
                    },
                )
            )
        if not conversion.blocks and parse_profile != "office_write":
            parser_diagnostics.append(
                DocumentDiagnostic(
                    code="empty_document_projection",
                    severity="warning",
                    message="Document processing produced no indexable text blocks.",
                    details={"source_path": record.source_path, "detected_family": detected_format.family},
                )
            )
        all_diagnostics = tuple(parser_diagnostics)
        rag_projection = self.rag_projection_builder.build(
            bundle_id=bundle_id,
            record=record,
            detected_format=detected_format,
            conversion=conversion,
            diagnostics=all_diagnostics,
        )
        office_ir = build_office_ir_from_conversion(
            bundle_id=bundle_id,
            record=record,
            detected_format=detected_format,
            conversion=rag_projection.conversion_result,
            diagnostics=all_diagnostics,
        )
        office_projection = build_office_projection(
            detected_format=detected_format,
            office_ir=office_ir,
        )
        evidence_projection = build_evidence_projection(
            bundle_id=bundle_id,
            record=record,
            detected_format=detected_format,
            conversion=rag_projection.conversion_result,
        )
        quality_flags = tuple(
            dict.fromkeys(
                tuple(rag_projection.conversion_result.quality_flags)
                + tuple(diagnostic.code for diagnostic in all_diagnostics if diagnostic.severity in {"warning", "error"})
            )
        )
        return DocumentProcessingBundle(
            bundle_id=bundle_id,
            source_record=record,
            detected_format=detected_format,
            office_ir=office_ir,
            rag_projection=rag_projection,
            office_projection=office_projection,
            evidence_projection=evidence_projection,
            diagnostics=all_diagnostics,
            parser_route=rag_projection.conversion_result.parser_route,
            quality_flags=quality_flags,
        )

    @property
    def version(self) -> str:
        return DOCUMENT_KERNEL_VERSION

    def _convert_record(
        self,
        record: SourceFileRecord,
        detected_format: DetectedDocumentFormat,
        *,
        parse_profile: str,
    ) -> ConversionResult:
        if parse_profile == "office_write":
            empty = ConversionResult.empty(record, parser_backend="document_kernel_office_write")
            return replace(
                empty,
                parser_route=("document_kernel_office_write",),
                fallback_used=False,
                quality_flags=(),
                metadata={
                    "source_type": record.source_type,
                    "source_path": record.source_path,
                    "parse_profile": parse_profile,
                    "detected_family": detected_format.family,
                    "detected_container": detected_format.container,
                },
            )
        if detected_format.family == "text" and detected_format.container == "text":
            text = self._read_text_resource(record.absolute_path)
            if text:
                return build_markdown_conversion_result(
                    record,
                    text,
                    parser_backend="document_kernel_text",
                    title=record.absolute_path.stem,
                    parser_route=("document_kernel_text",),
                    fallback_used=False,
                    metadata={
                        "source_type": record.source_type,
                        "source_path": record.source_path,
                        "text_adapter": "document_kernel",
                    },
                )
        return self.parser_resource.convert(record)

    def _read_text_resource(self, path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                return path.read_text(encoding=encoding).strip()
            except UnicodeDecodeError:
                continue
            except OSError:
                return ""
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return ""
