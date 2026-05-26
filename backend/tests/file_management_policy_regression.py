from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.unit_runtime.file_management_policy import prepare_runtime_file_management_policy_for_turn


def test_file_management_policy_uses_sandbox_repository_when_sandbox_is_enabled(tmp_path: Path) -> None:
    policy = prepare_runtime_file_management_policy_for_turn(
        root_dir=tmp_path / "backend",
        task_run_id="taskrun-coding",
        selected_recipe_payload={"metadata": {}},
        task_selection={"task_environment_id": "env.vibe_coding"},
        sandbox_policy={"enabled": True, "sandbox_root": str(tmp_path / "sandbox" / "workspace")},
    )

    assert policy["enabled"] is True
    assert policy["environment_id"] == "env.vibe_coding"
    assert policy["profile_id"] == "file_profile.vibe_coding_project"
    assert policy["repositories"]["read"] == "repo.coding.sandbox_workspace"
    assert policy["repositories"]["write"] == "repo.coding.sandbox_workspace"


def test_file_management_policy_survives_disabled_sandbox(tmp_path: Path) -> None:
    policy = prepare_runtime_file_management_policy_for_turn(
        root_dir=tmp_path / "backend",
        task_run_id="taskrun-writing",
        selected_recipe_payload={"metadata": {}},
        task_selection={"task_environment_id": "env.writing"},
        sandbox_policy={"enabled": False},
    )

    assert policy["enabled"] is True
    assert policy["environment_id"] == "env.writing"
    assert policy["profile_id"] == "file_profile.writing_manuscript"
    assert policy["repositories"]["read"] == "repo.writing.official_work"
    assert policy["repositories"]["write"] == "repo.writing.draft_workspace"


def test_specific_task_file_management_policy_overrides_environment_default(tmp_path: Path) -> None:
    policy = prepare_runtime_file_management_policy_for_turn(
        root_dir=tmp_path / "backend",
        task_run_id="taskrun-specific",
        selected_recipe_payload={
            "metadata": {
                "task_environment_id": "env.vibe_coding",
                "file_management_policy": {
                    "profile_id": "file_profile.vibe_coding_project",
                    "repositories": {"write": "repo.coding.project_workspace"},
                },
            }
        },
        task_selection={},
        sandbox_policy={"enabled": True, "sandbox_root": str(tmp_path / "sandbox" / "workspace")},
    )

    assert policy["enabled"] is True
    assert policy["repositories"]["read"] == "repo.coding.sandbox_workspace"
    assert policy["repositories"]["write"] == "repo.coding.project_workspace"
    assert policy["repositories"]["edit"] == "repo.coding.sandbox_workspace"
    assert policy["authority"] == "runtime.unit_runtime.file_management_policy"


def test_file_management_policy_does_not_invent_default_environment(tmp_path: Path) -> None:
    policy = prepare_runtime_file_management_policy_for_turn(
        root_dir=tmp_path / "backend",
        task_run_id="taskrun-no-environment",
        selected_recipe_payload={"metadata": {}},
        task_selection={},
        sandbox_policy={"enabled": True, "sandbox_root": str(tmp_path / "sandbox" / "workspace")},
    )

    assert policy == {}
