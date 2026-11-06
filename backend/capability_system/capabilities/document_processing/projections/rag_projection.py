from __future__ import annotations

from dataclasses import replace

from knowledge_system.conversion.models import ConversionBlock, ConversionPage, ConversionResult, SourceFileRecord

from capability_system.capabilities.document_processing.models import (
    DOCUMENT_KERNEL_VERSION,
    DetectedDocumentFormat,
    DocumentDiagnostic,
    RagProjection,
    stable_document_id,
)


class RagProjectionBuilder:
    def build(
        self,
        *,
        bundle_id: str,
        record: SourceFileRecord,
        detected_format: DetectedDocumentFormat,
        conversion: ConversionResult,
        diagnostics: tuple[DocumentDiagnostic, ...],
    ) -> RagProjection:
        parser_route = self._kernel_parser_route(detected_format, conversion)
        lineage_metadata = self._lineage_metadata(
            bundle_id=bundle_id,
            detected_format=detected_format,
            conversion=conversion,
            diagnostics=diagnostics,
            parser_route=parser_route,
        )
        blocks = tuple(
            self._annotate_block(
                bundle_id=bundle_id,
                block=block,
                detected_format=detected_format,
                lineage_metadata=lineage_metadata,
            )
            for block in conversion.blocks
        )
        pages = tuple(self._annotate_page(page, lineage_metadata) for page in conversion.pages)
        quality_flags = tuple(dict.fromkeys(tuple(conversion.quality_flags) + self._projection_quality_flags(detected_format, conversion)))
        result = replace(
            conversion,
            parser_backend="document_kernel",
            parser_route=parser_route,
            quality_flags=quality_flags,
            pages=pages,
            blocks=blocks,
            metadata={
                **dict(conversion.metadata),
                **lineage_metadata,
            },
        )
        return RagProjection(
            conversion_result=result,
            normalized_document_hint={
                "document_bundle_id": bundle_id,
                "detected_family": detected_format.family,
                "detected_container": detected_format.container,
                "source_parser_backend": conversion.parser_backend,
            },
            index_quality_hints={
                "source_block_count": len(conversion.blocks),
                "source_page_count": len(conversion.pages) or int(conversion.page_count or 0),
                "fallback_used": conversion.fallback_used,
                "quality_flags": list(quality_flags),
            },
        )

    def _kernel_parser_route(self, detected_format: DetectedDocumentFormat, conversion: ConversionResult) -> tuple[str, ...]:
        route = ["document_kernel", f"detect:{detected_format.family}/{detected_format.container}"]
        route.extend(str(item) for item in (conversion.parser_route or (conversion.parser_backend,)) if str(item).strip())
        return tuple(route)

    def _lineage_metadata(
        self,
        *,
        bundle_id: str,
        detected_format: DetectedDocumentFormat,
        conversion: ConversionResult,
        diagnostics: tuple[DocumentDiagnostic, ...],
        parser_route: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "document_kernel_version": DOCUMENT_KERNEL_VERSION,
            "document_bundle_id": bundle_id,
            "document_processing_route": list(parser_route),
            "source_parser_backend": conversion.parser_backend,
            "source_parser_route": list(conversion.parser_route or (conversion.parser_backend,)),
            "parser_route": list(parser_route),
            "fallback_used": conversion.fallback_used,
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
            **detected_format.to_metadata(),
        }

    def _projection_quality_flags(
        self,
        detected_format: DetectedDocumentFormat,
        conversion: ConversionResult,
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if detected_format.confidence < 0.7:
            flags.append("format_detection_low_confidence")
        if detected_format.limitations:
            flags.append("format_detection_limited")
        if not conversion.blocks:
            flags.append("empty_rag_projection")
        if conversion.fallback_used:
            flags.append("parser_resource_fallback_used")
        return tuple(flags)

    def _annotate_block(
        self,
        *,
        bundle_id: str,
        block: ConversionBlock,
        detected_format: DetectedDocumentFormat,
        lineage_metadata: dict[str, object],
    ) -> ConversionBlock:
        ir_block_id = self._ir_block_id(bundle_id, block)
        anchor_id = self._anchor_id(bundle_id, block)
        metadata = {
            **dict(block.metadata),
            **self._lineage_fields(lineage_metadata),
            "ir_part_id": self._part_id(bundle_id, detected_format, block),
            "ir_block_id": ir_block_id,
            "anchor_id": anchor_id,
            "source_object_id": self._source_object_id(bundle_id, block),
        }
        return replace(block, metadata=metadata)

    def _annotate_page(self, page: ConversionPage, lineage_metadata: dict[str, object]) -> ConversionPage:
        metadata = {
            **dict(page.metadata),
            **self._lineage_fields(lineage_metadata),
        }
        return replace(page, metadata=metadata)

    def _lineage_fields(self, lineage_metadata: dict[str, object]) -> dict[str, object]:
        keys = (
            "document_kernel_version",
            "document_bundle_id",
            "detected_family",
            "detected_container",
            "detected_extension",
            "detected_confidence",
            "source_parser_backend",
            "source_parser_route",
            "document_processing_route",
        )
        return {key: lineage_metadata[key] for key in keys if key in lineage_metadata}

    def _part_id(self, bundle_id: str, detected_format: DetectedDocumentFormat, block: ConversionBlock) -> str:
        if block.page is not None:
            return f"{bundle_id}:part:page:{int(block.page)}"
        if detected_format.family == "excel":
            return f"{bundle_id}:part:sheet:unknown"
        if detected_format.family == "powerpoint":
            return f"{bundle_id}:part:slide:unknown"
        return f"{bundle_id}:part:document"

    def _ir_block_id(self, bundle_id: str, block: ConversionBlock) -> str:
        return f"{bundle_id}:block:{stable_document_id(block.block_id, str(block.reading_order))[:16]}"

    def _anchor_id(self, bundle_id: str, block: ConversionBlock) -> str:
        seed = f"{block.block_id}:{block.page}:{block.reading_order}:{block.text[:160]}"
        return f"{bundle_id}:anchor:{stable_document_id(seed)[:16]}"

    def _source_object_id(self, bundle_id: str, block: ConversionBlock) -> str:
        if block.block_type in {"table", "figure", "sheet_region", "json_field_group"} or block.modality in {"table", "image"}:
            return f"{bundle_id}:object:{stable_document_id(block.block_id, block.block_type, block.modality)[:16]}"
        return ""
