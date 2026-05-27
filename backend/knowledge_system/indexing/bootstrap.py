from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from knowledge_system.conversion import DocumentCacheLayout, DoclingConverter, discover_source_files
from knowledge_system.conversion.models import STRUCTURE_CONTRACT_VERSION, build_conversion_doc_id
from config import get_settings
from knowledge_system.ingestion import ChunkingPolicy, NormalizedDocumentBuilder, build_cleaning_manifest, build_indexable_units
from capability_system.units.mcp.local.retrieval.collections import CollectionConfig
from knowledge_system.indexing.llamaindex_backend import LlamaIndexRetrievalBackend


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
    quality_report: dict[str, Any] = field(default_factory=dict)
    parser_backends: list[str] = field(default_factory=list)
    index_payload: dict[str, Any] = field(default_factory=dict)


class RetrievalBootstrapper:
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
        self.cache = DocumentCacheLayout(base_dir)
        self.builder = NormalizedDocumentBuilder()
        self.settings = get_settings()

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
            chunking_policy = ChunkingPolicy.from_settings(self.settings)
            units = build_indexable_units(document, blocks, object_refs, chunking_policy=chunking_policy)
            quality_report = build_index_quality_report(units, chunking_policy=chunking_policy)
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
                index_quality_report=quality_report,
            )

            all_units.extend(units)
            result.converted_documents += 1
            result.normalized_blocks += len(blocks)
            result.eligible_blocks += int(cleaning_manifest.get("eligible_block_count", 0) or 0)
            result.dropped_blocks += int(cleaning_manifest.get("dropped_block_count", 0) or 0)
            result.normalized_objects += len(object_refs)
            result.indexable_units += len(units)
            result.page_summary_units += page_summary_count
            result.quality_report = merge_index_quality_reports(result.quality_report, quality_report)
            if conversion.parser_backend not in parser_backends:
                parser_backends.append(conversion.parser_backend)

        result.parser_backends = parser_backends
        collection_quality_report = build_index_quality_report(
            all_units,
            chunking_policy=ChunkingPolicy.from_settings(self.settings),
        )
        result.quality_report = collection_quality_report
        result.index_payload = self.backend.build_collection(
            config.name,
            all_units,
            embed_model=embed_model,
        )
        result.index_payload["index_quality_report"] = collection_quality_report
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
            if (
                manifest.get("version_digest") == record.version_digest
                and manifest.get("structure_contract_version") == STRUCTURE_CONTRACT_VERSION
            ):
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


def build_index_quality_report(units: list[Any], *, chunking_policy: ChunkingPolicy) -> dict[str, Any]:
    token_counts = [_unit_token_count(unit) for unit in units]
    unit_type_counts: dict[str, int] = {}
    for unit in units:
        unit_type = str(getattr(unit, "unit_type", "") or "unknown")
        unit_type_counts[unit_type] = unit_type_counts.get(unit_type, 0) + 1
    parent_links = sum(1 for unit in units if str(getattr(unit, "parent_unit_id", "") or "").strip())
    child_links = 0
    for unit in units:
        metadata = dict(getattr(unit, "metadata", {}) or {})
        child_links += len(list(metadata.get("child_unit_ids", []) or []))
    report = {
        "chunking_policy": chunking_policy.to_dict(),
        "chunk_count": len(units),
        "avg_tokens": round(mean(token_counts), 2) if token_counts else 0,
        "p95_tokens": _percentile(token_counts, 95),
        "max_tokens": max(token_counts) if token_counts else 0,
        "overlong_chunk_count": sum(1 for value in token_counts if value > chunking_policy.hard_max_tokens),
        "tiny_chunk_count": sum(1 for value in token_counts if 0 < value < chunking_policy.min_tokens),
        "missing_page_count": sum(1 for unit in units if getattr(unit, "page", None) is None),
        "table_unit_count": sum(1 for unit in units if str(getattr(unit, "modality", "") or "") == "table"),
        "table_row_window_count": unit_type_counts.get("table_row_window", 0),
        "page_summary_count": unit_type_counts.get("page_summary", 0),
        "parent_section_count": unit_type_counts.get("parent_section", 0),
        "document_summary_count": unit_type_counts.get("document_summary", 0),
        "parent_child_link_count": parent_links + child_links,
        "unit_type_counts": unit_type_counts,
    }
    return report


def merge_index_quality_reports(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not left:
        return dict(right)
    if not right:
        return dict(left)
    chunk_count = int(left.get("chunk_count", 0) or 0) + int(right.get("chunk_count", 0) or 0)
    left_avg = float(left.get("avg_tokens", 0) or 0)
    right_avg = float(right.get("avg_tokens", 0) or 0)
    left_count = int(left.get("chunk_count", 0) or 0)
    right_count = int(right.get("chunk_count", 0) or 0)
    merged_types = dict(left.get("unit_type_counts", {}) or {})
    for key, value in dict(right.get("unit_type_counts", {}) or {}).items():
        merged_types[str(key)] = int(merged_types.get(str(key), 0) or 0) + int(value or 0)
    return {
        **dict(right),
        "chunk_count": chunk_count,
        "avg_tokens": round(((left_avg * left_count) + (right_avg * right_count)) / max(chunk_count, 1), 2),
        "p95_tokens": max(int(left.get("p95_tokens", 0) or 0), int(right.get("p95_tokens", 0) or 0)),
        "max_tokens": max(int(left.get("max_tokens", 0) or 0), int(right.get("max_tokens", 0) or 0)),
        "overlong_chunk_count": int(left.get("overlong_chunk_count", 0) or 0) + int(right.get("overlong_chunk_count", 0) or 0),
        "tiny_chunk_count": int(left.get("tiny_chunk_count", 0) or 0) + int(right.get("tiny_chunk_count", 0) or 0),
        "missing_page_count": int(left.get("missing_page_count", 0) or 0) + int(right.get("missing_page_count", 0) or 0),
        "table_unit_count": int(left.get("table_unit_count", 0) or 0) + int(right.get("table_unit_count", 0) or 0),
        "table_row_window_count": int(left.get("table_row_window_count", 0) or 0) + int(right.get("table_row_window_count", 0) or 0),
        "page_summary_count": int(left.get("page_summary_count", 0) or 0) + int(right.get("page_summary_count", 0) or 0),
        "parent_section_count": int(left.get("parent_section_count", 0) or 0) + int(right.get("parent_section_count", 0) or 0),
        "document_summary_count": int(left.get("document_summary_count", 0) or 0) + int(right.get("document_summary_count", 0) or 0),
        "parent_child_link_count": int(left.get("parent_child_link_count", 0) or 0) + int(right.get("parent_child_link_count", 0) or 0),
        "unit_type_counts": merged_types,
    }


def _unit_token_count(unit: Any) -> int:
    metadata = dict(getattr(unit, "metadata", {}) or {})
    try:
        value = int(metadata.get("token_count", 0) or 0)
    except (TypeError, ValueError):
        value = 0
    if value > 0:
        return value
    text = str(getattr(unit, "text", "") or "")
    return len(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text))


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((max(min(percentile, 100), 0) / 100) * (len(ordered) - 1)))
    return int(ordered[index])


