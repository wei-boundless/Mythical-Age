from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understanding.compound_query import split_compound_query
from understanding.task_understanding import analyze_task_understanding


def main() -> None:
    bracketed = "帮我在知识库中查询（哪些商品库存不足/三一重工前三大股东/为什么我在我的帐户中找不到我的订单？）"
    parts = split_compound_query(bracketed)
    assert parts == [
        "哪些商品库存不足",
        "三一重工前三大股东",
        "为什么我在我的帐户中找不到我的订单？",
    ]

    direct = "请查询哪些商品库存不足/三一重工前三大股东/为什么我在我的帐户中找不到我的订单？"
    direct_parts = split_compound_query(direct)
    assert direct_parts == [
        "哪些商品库存不足",
        "三一重工前三大股东",
        "为什么我在我的帐户中找不到我的订单？",
    ]

    shortage = analyze_task_understanding(parts[0])
    assert shortage.source_kind == "dataset"
    assert shortage.task_kind == "dataset_filter"
    assert shortage.preferred_skill == "structured-data-analysis"

    shareholder = analyze_task_understanding(parts[1])
    assert shareholder.source_kind == "knowledge_base"
    assert shareholder.task_kind == "knowledge_lookup"
    assert shareholder.preferred_skill == "rag-skill"

    faq = analyze_task_understanding(parts[2])
    assert faq.source_kind == "knowledge_base"
    assert faq.task_kind == "faq_explanation"
    assert faq.preferred_skill == "rag-skill"

    print("ALL PASSED (compound query regression)")


if __name__ == "__main__":
    main()
