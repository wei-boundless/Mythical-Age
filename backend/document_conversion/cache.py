from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from document_conversion.models import ConversionBlock, ConversionPage, ConversionResult
from project_layout import ProjectLayout


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    return value


class DocumentCacheLayout:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.root = ProjectLayout.from_backend_dir(base_dir).document_cache_dir
        self.conversion_dir = self.root / "conversion"
        self.normalized_dir = self.root / "normalized"
        self.manifests_dir = self.root / "manifests"

    def ensure(self) -> None:
        self.conversion_dir.mkdir(parents=True, exist_ok=True)
        self.normalized_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def conversion_path(self, doc_id: str) -> Path:
        return self.conversion_dir / f"{doc_id}.json"

    def conversion_manifest_path(self, doc_id: str) -> Path:
        return self.manifests_dir / f"{doc_id}.conversion_manifest.json"

    def normalized_manifest_path(self, doc_id: str) -> Path:
        return self.manifests_dir / f"{doc_id}.normalized_manifest.json"

    def write_conversion_result(self, result: ConversionResult) -> Path:
        self.ensure()
        payload = _json_ready(result)
        path = self.conversion_path(result.doc_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.conversion_manifest_path(result.doc_id).write_text(
            json.dumps(
                {
                    "doc_id": result.doc_id,
                    "source_path": result.source_path,
                    "version_digest": result.version_digest,
                    "parser_backend": result.parser_backend,
                    "quality_flags": list(result.quality_flags),
                    "page_count": len(result.pages) or int(result.page_count or 0),
                    "block_count": len(result.blocks),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def read_conversion_result(self, doc_id: str) -> ConversionResult | None:
        path = self.conversion_path(doc_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        blocks = tuple(
            ConversionBlock(
                block_id=str(block.get("block_id", "")),
                block_type=str(block.get("block_type", "paragraph")),
                text=str(block.get("text", "")),
                modality=str(block.get("modality", "text")),
                section_label=str(block.get("section_label", "") or ""),
                structure_role=str(block.get("structure_role", "content") or "content"),
                page=block.get("page"),
                section_path=tuple(block.get("section_path", []) or ()),
                reading_order=int(block.get("reading_order", 0) or 0),
                bbox=tuple(block.get("bbox", [])) if block.get("bbox") is not None else None,
                metadata=dict(block.get("metadata", {}) or {}),
            )
            for block in payload.get("blocks", []) or []
        )
        pages = tuple(
            ConversionPage(
                page_number=int(page.get("page_number", 0) or 0),
                raw_text=str(page.get("raw_text", "") or ""),
                text_block_count=int(page.get("text_block_count", 0) or 0),
                table_block_count=int(page.get("table_block_count", 0) or 0),
                image_block_count=int(page.get("image_block_count", 0) or 0),
                diagnostic_block_count=int(page.get("diagnostic_block_count", 0) or 0),
                has_text=bool(page.get("has_text", False)),
                has_usable_text=bool(page.get("has_usable_text", False)),
                page_state=str(page.get("page_state", "") or ""),
                state_confidence=float(page.get("state_confidence", 0.0) or 0.0),
                metadata=dict(page.get("metadata", {}) or {}),
            )
            for page in payload.get("pages", []) or []
            if int(page.get("page_number", 0) or 0) > 0
        )
        return ConversionResult(
            doc_id=str(payload.get("doc_id", "")),
            collection=str(payload.get("collection", "")),
            source_path=str(payload.get("source_path", "")),
            source_type=str(payload.get("source_type", "")),
            version_digest=str(payload.get("version_digest", "")),
            parser_backend=str(payload.get("parser_backend", "")),
            title=str(payload.get("title", "")),
            language=payload.get("language"),
            page_count=int(payload.get("page_count", 0) or 0),
            structure_contract_version=str(payload.get("structure_contract_version", "") or ""),
            parser_route=tuple(payload.get("parser_route", []) or ()),
            fallback_used=bool(payload.get("fallback_used", False)),
            quality_flags=tuple(payload.get("quality_flags", []) or ()),
            pages=pages,
            blocks=blocks,
            metadata=dict(payload.get("metadata", {}) or {}),
        )

    def read_conversion_manifest(self, doc_id: str) -> dict[str, Any]:
        path = self.conversion_manifest_path(doc_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def write_normalized_manifest(
        self,
        *,
        doc_id: str,
        block_count: int,
        object_count: int,
        page_summary_count: int,
        eligible_block_count: int = 0,
        dropped_block_count: int = 0,
        eligibility_breakdown: dict[str, int] | None = None,
        index_profile_counts: dict[str, int] | None = None,
        drop_reason_counts: dict[str, int] | None = None,
        cleaning_flag_counts: dict[str, int] | None = None,
        index_quality_report: dict[str, Any] | None = None,
    ) -> Path:
        self.ensure()
        path = self.normalized_manifest_path(doc_id)
        path.write_text(
            json.dumps(
                {
                    "doc_id": doc_id,
                    "block_count": block_count,
                    "object_count": object_count,
                    "page_summary_count": page_summary_count,
                    "eligible_block_count": eligible_block_count,
                    "dropped_block_count": dropped_block_count,
                    "eligibility_breakdown": dict(eligibility_breakdown or {}),
                    "index_profile_counts": dict(index_profile_counts or {}),
                    "drop_reason_counts": dict(drop_reason_counts or {}),
                    "cleaning_flag_counts": dict(cleaning_flag_counts or {}),
                    "index_quality_report": dict(index_quality_report or {}),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path
