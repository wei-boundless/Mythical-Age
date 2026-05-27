from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.shared.artifact_paths import validate_required_artifact_file
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


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


def test_artifact_file_required_ignores_plain_text_write_claim(tmp_path: Path) -> None:
    validation = validate_required_artifact_file(
        root_dir=tmp_path,
        selected_recipe_payload={
            "validation_rules": [
                {
                    "rule_id": "require-real-write",
                    "validation_kind": "artifact_file_required",
                    "severity": "error",
                }
            ]
        },
        final_content="已写入 output/a.md",
        result_refs=(),
        event_log_events=[
            {
                "event_type": "executor_observation_received",
                "payload": {
                    "observation": {
                        "observation_type": "tool_result",
                        "payload": {
                            "tool_name": "write_file",
                            "tool_args": {"path": "output/a.md"},
                            "result": "Write succeeded: output/a.md",
                        },
                    }
                },
                "refs": {"observation_ref": "obs:plain"},
            }
        ],
    )

    assert validation["required"] is True
    assert validation["passed"] is False
    assert validation["existing_write_count"] == 0


def test_artifact_file_required_accepts_structured_write_envelope(tmp_path: Path) -> None:
    output_path = tmp_path / "output" / "a.md"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("real artifact\n", encoding="utf-8")
    envelope = build_tool_result_envelope(
        tool_name="write_file",
        tool_args={"path": "output/a.md"},
        result={
            "text": "Write succeeded: output/a.md",
            "structured_payload": {
                "observed_paths": ["output/a.md"],
                "artifact_refs": [{"path": "output/a.md", "kind": "file"}],
            },
        },
    )

    validation = validate_required_artifact_file(
        root_dir=tmp_path,
        selected_recipe_payload={
            "validation_rules": [
                {
                    "rule_id": "require-real-write",
                    "validation_kind": "artifact_file_required",
                    "severity": "error",
                }
            ]
        },
        final_content="交付 output/a.md",
        result_refs=(),
        event_log_events=[
            {
                "event_type": "executor_observation_received",
                "payload": {
                    "observation": {
                        "observation_type": "tool_result",
                        "payload": {
                            "tool_name": "write_file",
                            "tool_args": {"path": "output/a.md"},
                            "result": envelope.text,
                            "result_envelope": envelope.to_dict(),
                            "structured_payload": dict(envelope.structured_payload),
                        },
                    }
                },
                "refs": {"observation_ref": "obs:structured"},
            }
        ],
    )

    assert validation["required"] is True
    assert validation["passed"] is True
    assert validation["existing_write_count"] == 1


