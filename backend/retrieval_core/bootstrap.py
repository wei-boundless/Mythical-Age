from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from document_conversion import DocumentCacheV2Layout, DoclingConverter, discover_source_files
from document_conversion.models import build_conversion_doc_id
from normalized_ingestion import NormalizedDocumentBuilder, build_cleaning_manifest, build_indexable_units
from RAG.collections import CollectionConfig
from retrieval_core.llamaindex_backend import LlamaIndexRetrievalBackend


@dataclass(slots=True)
class RebuildResult:
    collection: str
    discovered_files: int = 0
    converted_documents: int = 0
    normalized_blocks: int = 0
    eligible_blocks: int = 0
    dropped_blocks: int = 0
    normalized_objects: int = 0
    indexable_units: int = 0
    page_summary_units: int = 0
    parser_backends: list[str] = field(default_factory=list)
    index_payload: dict[str, Any] = field(default_factory=dict)


class RetrievalV2Bootstrapper:
    def __init__(
        self,
        base_dir: Path,
        *,
        converter: DoclingConverter | None = None,
        backend: LlamaIndexRetrievalBackend | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.converter = converter or DoclingConverter(
            enabled=True,
            repo_root=base_dir.parent,
        )
        self.backend = backend or LlamaIndexRetrievalBackend(base_dir)
        self.cache = DocumentCacheV2Layout(base_dir)
        self.builder = NormalizedDocumentBuilder()

    def rebuild_collection(
        self,
        config: CollectionConfig,
        *,
        embed_model: object | None = None,
        reuse_conversion_cache: bool = True,
    ) -> RebuildResult:
        records = discover_source_files(config, backend_dir=self.base_dir)
        result = RebuildResult(collection=config.name, discovered_files=len(records))
        all_units = []
        parser_backends: list[str] = []

        for record in records:
            conversion = self._load_or_convert(record, reuse_conversion_cache=reuse_conversion_cache)
            if conversion is None:
                continue

            document, blocks, object_refs = self.builder.build(conversion)
            units = build_indexable_units(document, blocks, object_refs)
            cleaning_manifest = build_cleaning_manifest(blocks)
            page_summary_count = len([unit for unit in units if unit.unit_type == "page_summary"])
            self.cache.write_normalized_manifest(
                doc_id=document.doc_id,
                block_count=len(blocks),
                object_count=len(object_refs),
                page_summary_count=page_summary_count,
                eligible_block_count=int(cleaning_manifest.get("eligible_block_count", 0) or 0),
                dropped_block_count=int(cleaning_manifest.get("dropped_block_count", 0) or 0),
                eligibility_breakdown=dict(cleaning_manifest.get("eligibility_breakdown", {}) or {}),
                index_profile_counts=dict(cleaning_manifest.get("index_profile_counts", {}) or {}),
                drop_reason_counts=dict(cleaning_manifest.get("drop_reason_counts", {}) or {}),
                cleaning_flag_counts=dict(cleaning_manifest.get("cleaning_flag_counts", {}) or {}),
            )

            all_units.extend(units)
            result.converted_documents += 1
            result.normalized_blocks += len(blocks)
            result.eligible_blocks += int(cleaning_manifest.get("eligible_block_count", 0) or 0)
            result.dropped_blocks += int(cleaning_manifest.get("dropped_block_count", 0) or 0)
            result.normalized_objects += len(object_refs)
            result.indexable_units += len(units)
            result.page_summary_units += page_summary_count
            if conversion.parser_backend not in parser_backends:
                parser_backends.append(conversion.parser_backend)

        result.parser_backends = parser_backends
        result.index_payload = self.backend.build_collection(
            config.name,
            all_units,
            embed_model=embed_model,
        )
        return result

    def _load_or_convert(
        self,
        record: Any,
        *,
        reuse_conversion_cache: bool,
    ):
        doc_id = self._doc_id_for_record(record)
        if reuse_conversion_cache:
            manifest = self.cache.read_conversion_manifest(doc_id)
            if manifest.get("version_digest") == record.version_digest:
                cached = self.cache.read_conversion_result(doc_id)
                if cached is not None:
                    return cached

        conversion = self.converter.convert(record)
        self.cache.write_conversion_result(conversion)
        return conversion

    @staticmethod
    def _doc_id_for_record(record: Any) -> str:
        return build_conversion_doc_id(
            str(record.collection),
            str(record.source_path),
            str(record.version_digest),
        )
