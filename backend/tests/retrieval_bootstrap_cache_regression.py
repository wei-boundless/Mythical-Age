from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from document_conversion.models import build_conversion_doc_id
from document_conversion.models import ConversionBlock, ConversionResult, SourceFileRecord
from RAG.collections import CollectionConfig
from retrieval_core import RetrievalV2Bootstrapper
from tests.retrieval_bootstrap_phase2_regression import DeterministicEmbedding


class CountingConverter:
    def __init__(self) -> None:
        self.calls = 0

    def convert(self, record: SourceFileRecord) -> ConversionResult:
        self.calls += 1
        return ConversionResult(
            doc_id=build_conversion_doc_id(
                record.collection,
                record.source_path,
                record.version_digest,
            ),
            collection=record.collection,
            source_path=record.source_path,
            source_type=record.source_type,
            version_digest=record.version_digest,
            parser_backend="counting",
            title=record.absolute_path.stem,
            quality_flags=(),
            blocks=(
                ConversionBlock(
                    block_id=f"{record.version_digest}:0",
                    block_type="paragraph",
                    text="cached content",
                    reading_order=0,
                ),
            ),
        )


def test_bootstrapper_reuses_conversion_cache_when_digest_matches(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    knowledge_dir = backend_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "alpha.md").write_text("alpha", encoding="utf-8")

    config = CollectionConfig(
        name="knowledge",
        source_dirs=(knowledge_dir,),
        storage_dir=backend_dir / "storage" / "indexes" / "knowledge",
        description="test knowledge",
        allowed_roots=(knowledge_dir,),
        file_extensions=(".md",),
    )
    converter = CountingConverter()
    bootstrapper = RetrievalV2Bootstrapper(backend_dir, converter=converter)

    bootstrapper.rebuild_collection(config, embed_model=DeterministicEmbedding(), reuse_conversion_cache=True)
    bootstrapper.rebuild_collection(config, embed_model=DeterministicEmbedding(), reuse_conversion_cache=True)

    assert converter.calls == 1
