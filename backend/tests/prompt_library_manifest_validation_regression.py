from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.manifest_validation import build_prompt_manifest_validation


def test_manifest_validation_rejects_projection_section_outside_role_mode() -> None:
    validation = build_prompt_manifest_validation(
        interaction_mode="professional_mode",
        sections=[
            {"section_id": "task_section", "content": "任务契约"},
            {"section_id": "semantic_task_section", "content": "语义任务契约"},
            {"section_id": "mode_policy_section", "content": "模式策略"},
            {"section_id": "projection_section", "content": "当前表达姿态"},
            {"section_id": "output_section", "content": "输出边界"},
        ],
    )

    assert validation["passed"] is False
    assert any("forbidden_role_or_projection_sections_outside_role_mode" in item for item in validation["issues"])


def test_manifest_validation_requires_professional_core_sections() -> None:
    validation = build_prompt_manifest_validation(
        interaction_mode="professional_mode",
        sections=[
            {"section_id": "task_section", "content": "任务契约"},
            {"section_id": "mode_policy_section", "content": "模式策略"},
        ],
    )

    assert validation["passed"] is False
    assert any("missing_required_professional_sections" in item for item in validation["issues"])


def test_manifest_validation_requires_vibe_coding_core_sections() -> None:
    validation = build_prompt_manifest_validation(
        interaction_mode="vibe_coding",
        sections=[
            {"section_id": "task_section", "content": "任务契约"},
            {"section_id": "mode_policy_section", "content": "模式策略"},
        ],
    )

    assert validation["passed"] is False
    assert any("missing_required_vibe_coding_sections" in item for item in validation["issues"])


def test_manifest_validation_detects_internal_marker_leak() -> None:
    validation = build_prompt_manifest_validation(
        interaction_mode="standard_mode",
        sections=[
            {"section_id": "task_section", "content": "不要暴露 workflow_id=workflow.test"},
            {"section_id": "output_section", "content": "输出边界"},
        ],
    )

    assert validation["passed"] is False
    assert any("internal_marker_leak" in item for item in validation["issues"])
