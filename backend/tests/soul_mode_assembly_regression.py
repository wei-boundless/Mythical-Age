from __future__ import annotations

from pathlib import Path

from soul.facade import SoulFacade


def _section_ids(payload: dict) -> set[str]:
    return {str(item["section_id"]) for item in payload["sections"]}


def test_work_mode_uses_work_prompt_without_world_or_story() -> None:
    preview = SoulFacade(Path("backend")).preview_mode(
        mode="work_mode",
        soul_id="hebo",
        task_contract="完成当前任务并给出验收结果。",
    )

    ids = _section_ids(preview)
    assert "protected_system_rules" in ids
    assert "shared_common_contract" in ids
    assert "task_contract" in ids
    assert "work_prompt" in ids
    assert "world" not in ids
    assert "story" not in ids
    assert preview["work_prompt_id"] == "work_prompt.default"
    assert preview["trace"]["includes_world"] == "false"
    assert preview["trace"]["includes_story"] == "false"


def test_role_mode_includes_world_and_story_without_projection() -> None:
    preview = SoulFacade(Path("backend")).preview_mode(
        mode="role_mode",
        soul_id="hebo",
    )

    ids = _section_ids(preview)
    assert "protected_system_rules" in ids
    assert "shared_common_contract" in ids
    assert "world" in ids
    assert "story" in ids
    assert "projection" not in ids
    assert preview["work_prompt_id"] == ""
    assert preview["trace"]["includes_world"] == "true"
    assert preview["trace"]["includes_story"] == "true"


def test_standard_mode_keeps_story_without_world() -> None:
    preview = SoulFacade(Path("backend")).preview_mode(
        mode="standard_mode",
        soul_id="hebo",
    )

    ids = _section_ids(preview)
    assert "story" in ids
    assert "projection" not in ids
    assert "world" not in ids
    assert preview["trace"]["includes_world"] == "false"
    assert preview["trace"]["includes_story"] == "true"


