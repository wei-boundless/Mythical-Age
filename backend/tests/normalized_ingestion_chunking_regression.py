from __future__ import annotations

from knowledge_system.ingestion.chunking import build_indexable_units
from knowledge_system.ingestion.models import NormalizedBlock, NormalizedDocument
from knowledge_system.ingestion.policy import ChunkingPolicy


def _document() -> NormalizedDocument:
    return NormalizedDocument(
        doc_id="doc-1",
        source_path="knowledge/sample.md",
        source_type="md",
        collection="knowledge",
        version_digest="v1",
        title="Sample",
        parser_backend="test",
    )


def _block(text: str) -> NormalizedBlock:
    return NormalizedBlock(
        block_id="block-1",
        doc_id="doc-1",
        block_type="paragraph",
        text=text,
        normalized_text=text,
        clean_text=text,
        eligibility="keep",
        index_profiles=("dense_main", "lexical_main", "page_summary_source"),
        page=1,
        section_path=("section",),
        reading_order=1,
        parser_backend="test",
    )


def _content_units(text: str, policy: ChunkingPolicy):
    return [
        unit
        for unit in build_indexable_units(_document(), [_block(text)], [], chunking_policy=policy)
        if unit.unit_type == "content_block"
    ]


def test_chunking_policy_controls_long_chinese_sentence_boundaries() -> None:
    text = "第一句讲检索系统需要稳定证据。" * 20 + "第二句说明页码和章节不能丢。" * 20
    policy = ChunkingPolicy(target_tokens=32, soft_max_tokens=48, hard_max_tokens=64, overlap_tokens=8)

    units = _content_units(text, policy)

    assert len(units) > 1
    assert all(int(unit.metadata["token_count"]) <= policy.hard_max_tokens for unit in units)
    assert any("第二句" in unit.text for unit in units)


def test_chunking_policy_applies_overlap_between_chunks() -> None:
    text = "。".join(f"第{index}句包含一个稳定事实" for index in range(1, 30)) + "。"
    policy = ChunkingPolicy(target_tokens=24, soft_max_tokens=36, hard_max_tokens=48, overlap_tokens=8)

    units = _content_units(text, policy)

    assert len(units) > 2
    assert any(
        units[index].text.split("。")[0] in units[index - 1].text
        for index in range(1, len(units))
    )


def test_chunking_policy_keeps_hard_max_for_unpunctuated_text() -> None:
    text = "检索系统" * 180
    policy = ChunkingPolicy(target_tokens=32, soft_max_tokens=48, hard_max_tokens=64, overlap_tokens=8)

    units = _content_units(text, policy)

    assert len(units) > 1
    assert all(int(unit.metadata["token_count"]) <= policy.hard_max_tokens for unit in units)
