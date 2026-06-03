from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system.runtime_semantics.quality_gates import length_budget_quality_gate, sectioned_text_batch_quality_gate


def _chapter_quality_policy(**overrides) -> dict:
    policy = {
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_count_key": "chapters_per_round",
        "target_metric_key": "batch_target_words",
        "unit_target_metric_key": "chapter_target_words",
        "minimum_metric_ratio": 0.55,
        "minimum_metric_per_unit": 1200,
        "unit_summary_template": "第{index}章",
        "metric_summary_label": "字",
        "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
        "range_declaration_keywords": [
            "当前批次",
            "当前章批次",
            "本批允许范围",
            "本批允许章号",
            "允许范围",
            "批次目标",
            "批次摘要",
            "当前批次细纲",
            "当前批次正文",
        ],
        "broad_range_keywords": ["本批", "本轮"],
        "range_mention_patterns": [
            r"第\s*(?P<start>[0-9一二三四五六七八九十百零〇两]+)\s*章?\s*(?:至|到|[-—~～])\s*第?\s*(?P<end>[0-9一二三四五六七八九十百零〇两]+)\s*章"
        ],
        "future_range_keywords": [
            "下一批",
            "下批",
            "下一轮",
            "下轮",
            "后续批次",
            "后续章节",
            "后续章",
            "后续承接",
            "承接点",
            "下一阶段",
        ],
    }
    policy.update(overrides)
    return policy


def test_length_budget_allows_advisory_target_above_minimum() -> None:
    result = length_budget_quality_gate(
        "澜" * 1850,
        explicit_inputs={},
        length_budget={
            "measurement_mode": "text_units",
            "target_units": 2000,
            "min_units": 1800,
            "max_units": 4000,
            "target_enforcement": "advisory",
        },
    )

    assert result["accepted"] is True
    assert result["below_target_advisory"] is True
    assert result["issues"] == []


def test_length_budget_advisory_target_still_rejects_below_minimum() -> None:
    result = length_budget_quality_gate(
        "澜" * 1700,
        explicit_inputs={},
        length_budget={
            "measurement_mode": "text_units",
            "target_units": 2000,
            "min_units": 1800,
            "max_units": 4000,
            "target_enforcement": "advisory",
        },
    )

    assert result["accepted"] is False
    assert result["issues"] == ["insufficient_metric:1700<1800"]


def test_chapter_draft_quality_gate_reports_per_chapter_metric_deficits() -> None:
    text = "\n\n".join(
        [
            "## 第1章「起」\n" + ("泽" * 1300),
            "## 第2章「承」\n" + ("黎" * 400),
            "## 第3章「转」\n" + ("漪" * 1250),
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 3,
            "chapters_per_round": 3,
            "chapter_target_words": 2000,
            "batch_target_words": 6000,
        },
        policy=_chapter_quality_policy(),
    )

    assert result["accepted"] is False
    assert result["found_unit_indexes"] == [1, 2, 3]
    assert result["unit_metric_counts"]["1"] >= 1200
    assert result["unit_metric_counts"]["2"] < 1200
    assert result["insufficient_unit_metrics"] == [
        {
            "unit_index": 2,
            "metric_value": result["unit_metric_counts"]["2"],
            "min_required_metric": 1200,
            "deficit": 1200 - result["unit_metric_counts"]["2"],
        }
    ]
    assert any(issue.startswith("insufficient_unit_metric:2:") for issue in result["issues"])
    assert "第2章" in result["unit_metric_summary"]


def test_chapter_draft_quality_gate_accepts_complete_bounded_batch() -> None:
    text = "\n\n".join(
        [
            "## 第1章「起」\n" + ("泽" * 1300),
            "## 第2章「承」\n" + ("黎" * 1300),
            "## 第3章「转」\n" + ("漪" * 1300),
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 3,
            "chapters_per_round": 3,
            "chapter_target_words": 2000,
            "batch_target_words": 6000,
        },
        policy={
            **_chapter_quality_policy(),
        },
    )

    assert result["accepted"] is True
    assert result["issues"] == []
    assert result["insufficient_unit_metrics"] == []


def test_chapter_draft_quality_gate_accepts_partial_contiguous_prefix() -> None:
    text = "\n\n".join(
        [
            "## 第1章「起」\n" + ("泽" * 1300),
            "## 第2章「承」\n" + ("黎" * 1300),
            "## 第3章「转」\n" + ("漪" * 1300),
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 10,
            "chapters_per_round": 10,
            "chapter_target_words": 2000,
            "batch_target_words": 20000,
        },
        policy={
            **_chapter_quality_policy(allow_partial_contiguous_prefix=True),
        },
    )

    assert result["accepted"] is False
    assert result["partial_accepted"] is True
    assert result["batch_complete"] is False
    assert result["found_expected_unit_indexes"] == [1, 2, 3]
    assert result["missing_unit_indexes"] == [4, 5, 6, 7, 8, 9, 10]
    assert result["next_unit_index"] == 4
    assert not any(issue.startswith("missing_required_sections:") for issue in result["issues"])


def test_chapter_draft_quality_gate_rejects_non_contiguous_partial_prefix() -> None:
    text = "\n\n".join(
        [
            "## 第1章「起」\n" + ("泽" * 1300),
            "## 第3章「跳号」\n" + ("漪" * 1300),
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 10,
            "chapters_per_round": 10,
            "chapter_target_words": 2000,
            "batch_target_words": 20000,
        },
        policy={
            **_chapter_quality_policy(allow_partial_contiguous_prefix=True),
        },
    )

    assert result["accepted"] is False
    assert result["partial_accepted"] is False
    assert "non_contiguous_partial_sections:1,3" in result["issues"]


def test_batch_quality_gate_rejects_unexpected_chapter_headings() -> None:
    text = "\n\n".join(
        [
            "## 第1章「起」\n" + ("泽" * 1300),
            "## 第2章「承」\n" + ("黎" * 1300),
            "## 第3章「转」\n" + ("漪" * 1300),
            "## 第4章「合」\n" + ("烬" * 1300),
            "## 第5章「钩」\n" + ("碑" * 1300),
            "## 第6章「越界」\n" + ("水" * 1300),
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 5,
            "chapters_per_round": 5,
            "chapter_target_words": 2000,
            "batch_target_words": 10000,
        },
        policy={
            **_chapter_quality_policy(forbid_unexpected_unit_indexes=True),
        },
    )

    assert result["accepted"] is False
    assert result["unexpected_unit_indexes"] == [6]
    assert "unexpected_unit_indexes:6" in result["issues"]


def test_batch_quality_gate_ignores_next_batch_handoff_chapter_numbers() -> None:
    text = "\n\n".join(
        [
            "### 第1章「泽中」\n" + ("泽" * 1300),
            "### 第2章「灾异」\n" + ("黎" * 1300),
            "### 第3章「沉碑」\n" + ("漪" * 1300),
            "### 第4章「印记」\n" + ("烬" * 1300),
            "### 第5章「水镜」\n" + ("碑" * 1300),
            "\n".join(
                [
                    "后续批次承接点：",
                    "- 第6章：迷失者2出现，信息矛盾。",
                    "- 第7章：黎透露井底的光。",
                    "- 第8章：黎死亡。",
                    "- 第9章：漪与烬对抗。",
                    "- 第10章：四方感知，北风低语。",
                ]
            ),
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 5,
            "chapters_per_round": 5,
            "chapter_target_words": 2000,
            "batch_target_words": 10000,
        },
        policy={
            **_chapter_quality_policy(
                heading_match_scope="formal_heading",
                ignored_heading_parent_keywords=["后续批次承接点"],
                forbid_unexpected_unit_indexes=True,
            ),
        },
    )

    assert result["accepted"] is True
    assert result["found_unit_indexes"] == [1, 2, 3, 4, 5]
    assert result["unexpected_unit_indexes"] == []
    assert not any(issue.startswith("unexpected_unit_indexes:") for issue in result["issues"])


def test_batch_quality_gate_ignores_future_batch_range_reference() -> None:
    text = "\n".join(
        [
            "### 第1章「泽中」",
            "### 第2章「灾异」",
            "### 第3章「沉碑」",
            "### 第4章「印记」",
            "### 第5章「水镜」",
            "- 第5章：信息密度达到本批峰值，为下一批（第6-10章）的冲突升级做铺垫。",
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 5,
            "chapters_per_round": 5,
        },
        policy={
            **_chapter_quality_policy(
                minimum_metric_ratio=0.0,
                minimum_metric_per_unit=0,
                heading_match_scope="formal_heading",
                forbid_unexpected_unit_indexes=True,
                forbid_unexpected_unit_ranges=True,
            ),
        },
    )

    assert result["accepted"] is True
    assert result["unexpected_unit_ranges"] == []
    assert result["issues"] == []


def test_batch_quality_gate_rejects_stale_batch_range_declaration() -> None:
    text = "\n".join(
        [
            "【输入继承证据表】",
            "- 当前批次：第1章至第10章",
            "- 本批允许范围：第1-10章",
            "### 第1章「泽中」",
            "### 第2章「灾异」",
            "### 第3章「沉碑」",
            "### 第4章「印记」",
            "### 第5章「水镜」",
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 5,
            "chapters_per_round": 5,
        },
        policy={
            **_chapter_quality_policy(
                minimum_metric_ratio=0.0,
                minimum_metric_per_unit=0,
                forbid_unexpected_unit_ranges=True,
            ),
        },
    )

    assert result["accepted"] is False
    assert result["unexpected_unit_ranges"]
    assert any(issue.startswith("unexpected_unit_range:1-10") for issue in result["issues"])


def test_chapter_draft_quality_gate_excludes_manifest_sections_from_body_metrics() -> None:
    text = "\n\n".join(
        [
            "# 【章节正文候选】",
            "## 第1章「泽中」\n" + ("泽" * 1300),
            "## 第2章「灾异」\n" + ("黎" * 1300),
            "## 第3章「沉碑」\n" + ("漪" * 1300),
            "## 第4章「印记」\n" + ("烬" * 1300),
            "## 第5章「水镜」\n" + ("碑" * 500),
            "## 【承接说明】\n"
            + ("这些说明只能帮助下游理解正文，不能算作章节正文。" * 120),
            "## 【公开摘要】\n"
            + ("第5章之后仍需继续承接，但摘要不是正文。" * 120),
        ]
    )

    result = sectioned_text_batch_quality_gate(
        text,
        explicit_inputs={
            "batch_start_index": 1,
            "batch_end_index": 5,
            "chapters_per_round": 5,
            "chapter_target_words": 2000,
            "batch_target_words": 10000,
        },
        policy={
            **_chapter_quality_policy(
                heading_match_scope="formal_heading",
                metric_section_keys=["章节正文候选"],
                metric_stop_section_keys=[
                    "承接说明",
                    "本章目标完成说明",
                    "人物与冲突推进",
                    "商业钩子与爽点兑现",
                    "后续伏笔或待承接事项",
                    "自检风险",
                    "公开摘要",
                ],
                forbid_unexpected_unit_indexes=True,
                forbid_unexpected_unit_ranges=True,
            ),
        },
    )

    assert result["accepted"] is False
    assert result["metric_content_source"] == "section"
    assert result["raw_content_metric_total"] > result["content_metric_total"]
    assert result["unit_metric_counts"]["5"] < 1200
    assert any(issue.startswith("insufficient_unit_metric:5:") for issue in result["issues"])


