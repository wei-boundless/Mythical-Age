from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGURE_SCRIPT = REPO_ROOT / "scripts" / "configure_writing_simple_novel.py"


def _load_config_module():
    spec = importlib.util.spec_from_file_location("configure_writing_simple_novel", CONFIGURE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_volume_plan_requires_grounded_baseline_outline_context() -> None:
    config = _load_config_module()

    policy = config.artifact_context_policy("volume_plan")
    items = list(policy["items"])
    required_keys = {
        "contract.writing.simple_novel.baseline_memory_commit:artifact_refs",
        "contract.writing.simple_novel.outline_design:artifact_refs",
        "contract.writing.simple_novel.outline_review:artifact_refs",
    }

    keyed_items = {str(item.get("input_key") or ""): item for item in items}
    assert set(keyed_items) == required_keys
    for key in required_keys:
        assert keyed_items[key]["required"] is True
    assert policy["max_items"] == 3
    assert keyed_items["contract.writing.simple_novel.baseline_memory_commit:artifact_refs"]["max_chars"] <= 18000
    assert keyed_items["contract.writing.simple_novel.outline_design:artifact_refs"]["max_chars"] <= 16000
    assert keyed_items["contract.writing.simple_novel.outline_review:artifact_refs"]["max_chars"] <= 6000


def test_volume_plan_prompt_forbids_generic_template_rewrite() -> None:
    config = _load_config_module()

    card = next(
        item
        for item in config.projection_cards()
        if item["projection_id"] == "projection.writing.simple_novel.volume_planner"
    )
    prompt = card["projection_nodes"][0]["content"]

    assert "只读基准库" in prompt
    assert "已审核全书大纲" in prompt
    assert "不是重新设计故事" in prompt
    assert "【输入继承证据表】" in prompt
    assert "【伏笔与回收窗口承接表】" in prompt
    assert "泛化分卷模板" in prompt
    assert "4500 个中文字符以内" in prompt
    assert "每个章节接口只写 2-4 条要点" in prompt


def test_volume_plan_memory_policy_reads_outline_spine_and_forbids_rewrite() -> None:
    config = _load_config_module()

    policy = config.memory_read_policy("creator", "volume_plan")

    assert "baseline_outline_spine" in policy["required_topics"]
    assert "foreshadow_spine" in policy["required_topics"]
    assert "outline_review_ref" in policy["required_topics"]
    assert "rewrite_frozen_volume_blueprint" in policy["forbidden_topics"]
    assert "generic_genre_template" in policy["forbidden_topics"]


def test_long_writing_nodes_have_bounded_runtime_limits() -> None:
    config = _load_config_module()

    volume_plan = config.graph_node(
        ("volume_plan", "分卷规划", "agent:writing_simple_worker", "projection.writing.simple_novel.volume_planner", "in", "out", "phase.volume_plan", 100, "volume_plan/volume_plan.md", "creator")
    )
    chapter_draft = config.graph_node(
        ("chapter_draft", "当前批次正文候选", "agent:writing_simple_worker", "projection.writing.simple_novel.chapter_writer", "in", "out", "phase.chapter_loop", 130, "draft.md", "creator")
    )

    assert volume_plan["runtime_limits"]["max_runtime_seconds"] >= 720
    assert volume_plan["stream_policy"]["non_stream_fallback_timeout_seconds"] >= 240
    assert volume_plan["stream_policy"]["stream_recovery_timeout_seconds"] >= 240
    assert volume_plan["metadata"]["stream_policy"]["non_stream_fallback_timeout_seconds"] >= 240
    assert volume_plan["metadata"]["stream_policy"]["stream_recovery_timeout_seconds"] >= 240
    assert chapter_draft["runtime_limits"]["max_runtime_seconds"] >= 900


def test_chapter_loop_uses_bounded_five_chapter_batches() -> None:
    config = _load_config_module()

    assert config.CHAPTERS_PER_ROUND == 5

    inputs = config.initial_runtime_loop_inputs()
    assert inputs["chapters_per_round"] == 5
    assert inputs["chapter_batch_size"] == 5

    derived = {item["key"]: item for item in config.loop_derived_fields()}
    assert derived["batch_end_index"]["value"] == 4
    assert derived["batch_index"]["size"] == 5
    assert derived["batch_target_words"]["value"] == 5


def test_chapter_draft_quality_policy_reports_unit_level_deficits() -> None:
    config = _load_config_module()

    policy = config.quality_retry_policy("chapter_draft")

    assert policy["minimum_metric_per_unit"] == 1200
    assert "insufficient_unit_metric:" in policy["recoverable_issue_prefixes"]
    assert "unexpected_unit_indexes:" in policy["recoverable_issue_prefixes"]
    assert policy["forbid_unexpected_unit_indexes"] is True
    assert policy["forbid_unexpected_unit_ranges"] is True
    assert policy["metric_section_keys"] == ["章节正文候选"]
    assert "承接说明" in policy["metric_stop_section_keys"]
    assert "公开摘要" in policy["metric_stop_section_keys"]
    assert "{unit_metric_summary}" in policy["requirements_template"]
    assert "previous_candidate_ref" in policy["requirements_template"]


def test_chapter_outline_quality_policy_rejects_batch_boundary_contamination() -> None:
    config = _load_config_module()

    policy = config.quality_retry_policy("chapter_outline")

    assert policy["enabled"] is True
    assert policy["retry_stage_id"] == "chapter_outline"
    assert "sectioned_text_batch_quality" in policy["acceptance_policies"]
    assert policy["forbid_unexpected_unit_indexes"] is True
    assert policy["forbid_unexpected_unit_ranges"] is True
    assert "unexpected_unit_indexes:" in policy["recoverable_issue_prefixes"]
    assert "unexpected_unit_range:" in policy["recoverable_issue_prefixes"]
    assert "batch_chapter_list" in policy["requirements_template"]


def test_volume_plan_handoff_uses_bounded_artifact_window() -> None:
    config = _load_config_module()

    edge = config.edge(
        "edge.baseline_memory.volume_plan",
        "baseline_memory_seed",
        "volume_plan",
        "contract.writing.simple_novel.baseline_memory_commit",
    )

    assert edge["artifact_ref_policy"]["max_chars"] <= 12000
    assert edge["artifact_ref_policy"]["prefer_refs_over_text"] is True


def test_chapter_outline_requires_grounded_canon_context() -> None:
    config = _load_config_module()

    policy = config.artifact_context_policy("chapter_outline")
    keyed_items = {str(item.get("input_key") or ""): item for item in policy["items"]}

    required_keys = {
        "contract.writing.simple_novel.baseline_memory_commit:artifact_refs",
        "contract.writing.simple_novel.outline_design:artifact_refs",
        "contract.writing.simple_novel.outline_review:artifact_refs",
        "contract.writing.simple_novel.volume_plan_commit:artifact_refs",
    }
    assert set(keyed_items) == required_keys
    assert policy["max_items"] == 4
    for key in required_keys:
        assert keyed_items[key]["required"] is True
    assert keyed_items["contract.writing.simple_novel.baseline_memory_commit:artifact_refs"]["max_chars"] <= 18000
    assert keyed_items["contract.writing.simple_novel.outline_design:artifact_refs"]["max_chars"] <= 14000
    assert keyed_items["contract.writing.simple_novel.outline_review:artifact_refs"]["max_chars"] <= 5000
    assert keyed_items["contract.writing.simple_novel.volume_plan_commit:artifact_refs"]["max_chars"] <= 12000


def test_chapter_outline_prompt_forbids_generic_template_drift() -> None:
    config = _load_config_module()

    card = next(
        item
        for item in config.projection_cards()
        if item["projection_id"] == "projection.writing.simple_novel.chapter_outliner"
    )
    prompt = card["projection_nodes"][0]["content"]

    assert "当前批次基准库" in prompt
    assert "全书大纲主干" in prompt
    assert "当前卷计划与当前批次接口" in prompt
    assert "batch_chapter_list 是最高优先级边界" in prompt
    assert "【输入继承证据表】" in prompt
    assert "大泽·沉碑" in prompt
    assert "泽、黎、漪、烬" in prompt
    assert "混沌初开" in prompt
    assert "姜衍" in prompt
    assert "通用洪荒模板" in prompt
    assert "让本批 5 章形成连续推进链" in prompt
    assert "让十章形成连续推进链" not in prompt


def test_chapter_writer_prompt_uses_per_chapter_budget_and_repair_rules() -> None:
    config = _load_config_module()

    card = next(
        item
        for item in config.projection_cards()
        if item["projection_id"] == "projection.writing.simple_novel.chapter_writer"
    )
    prompt = card["projection_nodes"][0]["content"]

    assert "连续完成 5 章正文" in prompt
    assert "batch_chapter_list 为最高优先级" in prompt
    assert "每章正文不得低于 1200" in prompt
    assert "逐章统计" in prompt
    assert "优先扩写低于下限的章节" in prompt
    assert "不得用摘要、提纲、解释、自检或重复句补字数" in prompt
    assert "第6章及以后绝对不能出现" not in prompt


def test_chapter_outline_handoff_uses_bounded_grounded_artifact_window() -> None:
    config = _load_config_module()

    edge = config.edge(
        "edge.volume_plan.outline",
        "volume_plan",
        "chapter_outline",
        "contract.writing.simple_novel.volume_plan_commit",
    )

    assert "outline_design_ref" in edge["metadata"]["required_refs"]
    assert "outline_review_ref" in edge["metadata"]["required_refs"]
    assert "通用洪荒开篇模板" in edge["metadata"]["memory_expectation"]
    assert edge["artifact_ref_policy"]["max_chars"] <= 12000
    assert edge["artifact_ref_policy"]["prefer_refs_over_text"] is True
