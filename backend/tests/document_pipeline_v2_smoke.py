from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from document_conversion import DocumentCacheV2Layout, DoclingConverter, SourceFileRecord
from normalized_ingestion import NormalizedDocumentBuilder, build_indexable_units
from retrieval_core import RetrievalV2Layout, to_retrieval_hit


def test_document_pipeline_v2_scaffold_can_build_minimal_artifacts(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    knowledge_dir = backend_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    sample = knowledge_dir / "sample.md"
    sample.write_text("# Title\n\nA short sample paragraph for phase zero.", encoding="utf-8")

    record = SourceFileRecord.from_path(sample, collection="knowledge", root_dir=backend_dir)
    converter = DoclingConverter(enabled=False)
    result = converter.convert(record)

    builder = NormalizedDocumentBuilder()
    document, blocks, object_refs = builder.build(result)
    units = build_indexable_units(document, blocks, object_refs)

    cache = DocumentCacheV2Layout(backend_dir)
    cache.write_conversion_result(result)
    cache.write_normalized_manifest(
        doc_id=document.doc_id,
        block_count=len(blocks),
        object_count=len(object_refs),
        page_summary_count=len([unit for unit in units if unit.unit_type == "page_summary"]),
    )

    index_layout = RetrievalV2Layout(backend_dir)
    index_layout.ensure(collections=("knowledge",))

    assert document.doc_id
    assert blocks
    assert units
    assert cache.conversion_path(document.doc_id).exists()
    assert cache.normalized_manifest_path(document.doc_id).exists()
    assert index_layout.collection_dir("knowledge").exists()

    hit = to_retrieval_hit(units[0], score=0.9, retrieval_modes=("dense",), parser_backend=result.parser_backend)
    assert hit.doc_id == document.doc_id
    assert hit.block_type
    assert hit.retrieval_modes == ("dense",)
