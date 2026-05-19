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
        "contract.writing.simple_novel.memory_commit_world:artifact_refs",
    }

    keyed_items = {str(item.get("input_key") or ""): item for item in items}
    assert required_keys <= set(keyed_items)
    for key in required_keys:
        assert keyed_items[key]["required"] is True


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


def test_volume_plan_memory_policy_reads_outline_spine_and_forbids_rewrite() -> None:
    config = _load_config_module()

    policy = config.memory_read_policy("creator", "volume_plan")

    assert "baseline_outline_spine" in policy["required_topics"]
    assert "foreshadow_spine" in policy["required_topics"]
    assert "outline_review_ref" in policy["required_topics"]
    assert "rewrite_frozen_volume_blueprint" in policy["forbidden_topics"]
    assert "generic_genre_template" in policy["forbidden_topics"]
