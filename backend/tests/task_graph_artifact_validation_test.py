from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.shared.artifact_paths import validate_required_artifact_file


def test_task_graph_artifact_policy_requires_final_content(tmp_path: Path) -> None:
    validation = validate_required_artifact_file(
        root_dir=tmp_path,
        selected_recipe_payload={"validation_rules": []},
        artifact_policy={
            "enabled": True,
            "required": True,
            "artifact_target": "memory/world/world_commit.md",
            "artifacts": [
                {
                    "path": "memory/world/world_commit.md",
                    "required": True,
                    "content_source": "final_content",
                }
            ],
        },
        final_content="",
        result_refs=(),
        event_log_events=[],
    )

    assert validation["required"] is True
    assert validation["passed"] is False
    assert validation["source"] == "task_graph_artifact_policy"


def test_task_graph_artifact_policy_accepts_non_empty_materializable_content(tmp_path: Path) -> None:
    validation = validate_required_artifact_file(
        root_dir=tmp_path,
        selected_recipe_payload={"validation_rules": []},
        artifact_policy={
            "enabled": True,
            "required": True,
            "artifact_target": "memory/world/world_commit.md",
        },
        final_content="world commit receipt",
        result_refs=("output_boundary:test",),
        event_log_events=[],
    )

    assert validation["required"] is True
    assert validation["passed"] is True
    assert validation["artifact_targets"] == ["memory/world/world_commit.md"]


