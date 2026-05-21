from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from knowledge_system.conversion.cache import DocumentCacheLayout
from knowledge_system.conversion.models import STRUCTURE_CONTRACT_VERSION, ConversionBlock, ConversionResult, SourceFileRecord
from knowledge_system.indexing.bootstrap import RetrievalBootstrapper


class _StubConverter:
    def __init__(self, result: ConversionResult) -> None:
        self.result = result
        self.calls = 0

    def convert(self, record: SourceFileRecord) -> ConversionResult:
        self.calls += 1
        return replace(
            self.result,
            doc_id=ConversionResult.empty(record, parser_backend=self.result.parser_backend).doc_id,
            collection=record.collection,
            source_path=record.source_path,
            source_type=record.source_type,
            version_digest=record.version_digest,
            structure_contract_version=STRUCTURE_CONTRACT_VERSION,
        )


def _record(path: Path, *, root_dir: Path) -> SourceFileRecord:
    return SourceFileRecord.from_path(path, collection="knowledge", root_dir=root_dir)


def test_bootstrap_reuses_cache_only_when_structure_contract_matches(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    pdf_path = backend_dir / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    record = _record(pdf_path, root_dir=backend_dir)

    cached_result = replace(
        ConversionResult.empty(record, parser_backend="local_fallback"),
        blocks=(
            ConversionBlock(
                block_id=f"{record.version_digest}:0",
                block_type="paragraph",
                text="old cached text",
            ),
        ),
    )
    cache = DocumentCacheLayout(backend_dir)
    cache.write_conversion_result(cached_result)

    doc_id = cached_result.doc_id
    manifest_path = cache.conversion_manifest_path(doc_id)
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            f"\"structure_contract_version\": \"{STRUCTURE_CONTRACT_VERSION}\"",
            "\"structure_contract_version\": \"structure_contract_v1\"",
        ),
        encoding="utf-8",
    )

    fresh_result = replace(
        ConversionResult.empty(record, parser_backend="mineru_pdf"),
        blocks=(
            ConversionBlock(
                block_id=f"{record.version_digest}:1",
                block_type="paragraph",
                text="fresh converted text",
            ),
        ),
    )
    converter = _StubConverter(fresh_result)

    bootstrapper = object.__new__(RetrievalBootstrapper)
    bootstrapper.cache = cache
    bootstrapper.converter = converter

    loaded = RetrievalBootstrapper._load_or_convert(
        bootstrapper,
        record,
        reuse_conversion_cache=True,
    )

    assert converter.calls == 1
    assert loaded is not None
    assert loaded.blocks[0].text == "fresh converted text"
    assert cache.read_conversion_result(doc_id).blocks[0].text == "fresh converted text"
