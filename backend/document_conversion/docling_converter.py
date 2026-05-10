from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from document_conversion.models import ConversionBlock, ConversionResult, SourceFileRecord
from document_conversion.quality import infer_quality_flags
from document_conversion.structured_text import build_markdown_conversion_result
from capability_system.units.mcp.local.pdf.analysis.parser import PdfSegment, PdfTextParser

if TYPE_CHECKING:
    from capability_system.units.mcp.local.retrieval.models import ParsedChunk
    from capability_system.units.mcp.local.retrieval.parser_adapter import MultimodalParserAdapter


class DoclingConverter:
    def __init__(
        self,
        *,
        enabled: bool = True,
        prefer_ocr: bool = False,
        repo_root: Path | None = None,
        ocr_language: str = "eng",
        pdf_parser: PdfTextParser | None = None,
    ) -> None:
        self.enabled = enabled
        self.prefer_ocr = prefer_ocr
        self.repo_root = repo_root
        self.ocr_language = ocr_language
        self._pdf_parser = pdf_parser or PdfTextParser(root_dir=self._backend_root())
        self._legacy_adapter: MultimodalParserAdapter | None = None

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401
        except Exception:
            return False
        return True

    def convert(self, record: SourceFileRecord) -> ConversionResult:
        if record.source_type == "pdf":
            converted = self._convert_pdf_with_parser(record)
            if converted is not None:
                return converted
        if self.available():
            converted = self._convert_with_docling(record)
            if self._conversion_result_usable(record, converted):
                return converted
        return self._convert_with_fallback(record)

    def _convert_with_docling(self, record: SourceFileRecord) -> ConversionResult | None:
        try:
            from docling.document_converter import DocumentConverter
            converter = DocumentConverter()
            result = converter.convert(str(record.absolute_path))
            document = getattr(result, "document", None)
            if document is None:
                return None
            markdown = self._export_markdown(document)
            return build_markdown_conversion_result(
                record,
                markdown,
                parser_backend="docling",
                title=Path(record.source_path).stem,
                parser_route=("docling",),
                fallback_used=False,
                metadata={
                    "prefer_ocr": self.prefer_ocr,
                    "source_type": record.source_type,
                    "source_path": record.source_path,
                    "fallback_used": False,
                },
            )
        except Exception:
            return None

    def _convert_pdf_with_parser(self, record: SourceFileRecord) -> ConversionResult | None:
        try:
            segments = self._pdf_parser.extract_segments(record.absolute_path)
        except Exception:
            return None
        blocks = self._blocks_from_pdf_segments(record, segments)
        if not blocks:
            return None
        flags = infer_quality_flags(tuple(blocks), parser_backend="mineru_pdf")
        return ConversionResult(
            doc_id=ConversionResult.empty(record, parser_backend="mineru_pdf").doc_id,
            collection=record.collection,
            source_path=record.source_path,
            source_type=record.source_type,
            version_digest=record.version_digest,
            parser_backend="mineru_pdf",
            title=record.absolute_path.stem,
            page_count=len({block.page for block in blocks if block.page is not None}),
            structure_contract_version=ConversionResult.empty(record, parser_backend="mineru_pdf").structure_contract_version,
            parser_route=("mineru_pdf",),
            fallback_used=False,
            quality_flags=flags,
            blocks=tuple(blocks),
            metadata={
                "prefer_ocr": self.prefer_ocr,
                "pdf_parser": "page_aware_first",
                "source_type": record.source_type,
                "source_path": record.source_path,
                "fallback_used": False,
                "page_aware": True,
            },
        )

    def _convert_with_fallback(self, record: SourceFileRecord) -> ConversionResult:
        fallback_blocks = self._convert_with_legacy_adapter(record)
        if not fallback_blocks:
            return ConversionResult.empty(
                record,
                parser_backend="legacy_fallback",
                quality_flags=("empty_conversion", "fallback_parser"),
            )
        flags = infer_quality_flags(tuple(fallback_blocks), parser_backend="legacy_fallback")
        return ConversionResult(
            doc_id=ConversionResult.empty(record, parser_backend="legacy_fallback").doc_id,
            collection=record.collection,
            source_path=record.source_path,
            source_type=record.source_type,
            version_digest=record.version_digest,
            parser_backend="legacy_fallback",
            title=record.absolute_path.stem,
            structure_contract_version=ConversionResult.empty(record, parser_backend="legacy_fallback").structure_contract_version,
            parser_route=("docling", "legacy_fallback"),
            fallback_used=True,
            quality_flags=flags,
            blocks=tuple(fallback_blocks),
            metadata={
                "source_type": record.source_type,
                "source_path": record.source_path,
                "fallback_used": True,
            },
        )

    def _export_markdown(self, document: object) -> str:
        if hasattr(document, "export_to_markdown"):
            try:
                return str(document.export_to_markdown() or "").strip()
            except TypeError:
                return str(document.export_to_markdown).strip()
        if hasattr(document, "export_to_text"):
            return str(document.export_to_text() or "").strip()
        return str(document).strip()

    def _blocks_from_pdf_segments(
        self,
        record: SourceFileRecord,
        segments: list[PdfSegment],
    ) -> list[ConversionBlock]:
        blocks: list[ConversionBlock] = []
        for idx, segment in enumerate(segments):
            text = str(segment.text or "").strip()
            if not text:
                continue
            modality = str(segment.modality or "text")
            block_type = "paragraph"
            if modality == "table":
                block_type = "table"
            elif modality == "image":
                block_type = "figure"
            elif segment.section:
                block_type = "section_block"
            section_label = str(segment.section or "").strip()
            blocks.append(
                ConversionBlock(
                    block_id=f"{record.version_digest}:pdf:{idx}",
                    block_type=block_type,
                    text=text,
                    modality=modality,
                    section_label=section_label,
                    structure_role="object" if modality in {"table", "image"} else "section" if segment.section else "content",
                    page=segment.page,
                    section_path=(section_label,) if section_label else (),
                    reading_order=idx,
                    metadata={
                        **dict(segment.metadata),
                        "source_type": record.source_type,
                        "source_path": record.source_path,
                    },
                )
            )
        return blocks

    def _legacy_parser(self) -> MultimodalParserAdapter | None:
        if self.repo_root is None:
            return None
        if self._legacy_adapter is None:
            from capability_system.units.mcp.local.retrieval.parser_adapter import MultimodalParserAdapter

            self._legacy_adapter = MultimodalParserAdapter(
                repo_root=self.repo_root,
                ocr_language=self.ocr_language,
            )
        return self._legacy_adapter

    def _convert_with_legacy_adapter(self, record: SourceFileRecord) -> list[ConversionBlock]:
        adapter = self._legacy_parser()
        if adapter is None or not adapter.is_supported_file(record.absolute_path):
            text = self._read_basic_text(record.absolute_path)
            if not text:
                return []
            return [
                ConversionBlock(
                    block_id=f"{record.version_digest}:0",
                    block_type="paragraph",
                    text=text,
                    structure_role="content",
                    reading_order=0,
                    metadata={
                        "source_type": record.source_type,
                        "source_path": record.source_path,
                    },
                )
            ]

        try:
            chunks = adapter.parse_file(record.absolute_path)
        except Exception:
            return []
        return self._blocks_from_parsed_chunks(record, chunks)

    def _blocks_from_parsed_chunks(
        self,
        record: SourceFileRecord,
        chunks: list[ParsedChunk],
    ) -> list[ConversionBlock]:
        blocks: list[ConversionBlock] = []
        for idx, chunk in enumerate(chunks):
            block_type = self._infer_block_type(chunk)
            section_path = (chunk.section,) if chunk.section else ()
            blocks.append(
                ConversionBlock(
                    block_id=f"{record.version_digest}:{idx}",
                    block_type=block_type,
                    text=(chunk.text or "").strip(),
                    modality=chunk.modality,
                    section_label=str(chunk.section or "").strip(),
                    structure_role="object" if block_type in {"table", "figure"} else "section" if chunk.section else "content",
                    page=chunk.page,
                    section_path=section_path,
                    reading_order=idx,
                    metadata={
                        **dict(chunk.metadata),
                        "source_type": record.source_type,
                        "source_path": record.source_path,
                    },
                )
            )
        return [block for block in blocks if block.text]

    def _infer_block_type(self, chunk: ParsedChunk) -> str:
        modality = (chunk.modality or "text").lower()
        if modality == "table":
            return "table"
        if modality == "image":
            return "figure"
        if chunk.section:
            return "section_block"
        return "paragraph"

    def _read_basic_text(self, path: Path) -> str:
        if path.suffix.lower() not in {".txt", ".md", ".json", ".csv"}:
            return ""
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                return path.read_text(encoding=encoding).strip()
            except UnicodeDecodeError:
                continue
            except OSError:
                return ""
        return path.read_text(encoding="utf-8", errors="ignore").strip()

    def _conversion_result_usable(
        self,
        record: SourceFileRecord,
        result: ConversionResult | None,
    ) -> bool:
        if result is None or not result.blocks:
            return False
        if record.source_type != "pdf":
            return True
        joined = " ".join(block.text.strip() for block in result.blocks if block.text.strip()).strip()
        if not joined:
            return False
        return not self._pdf_parser.looks_unusable_text(joined)

    def _backend_root(self) -> Path | None:
        if self.repo_root is None:
            return None
        return (self.repo_root / "backend").resolve()
