from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.dynamic_context.replacement_store import ReplacementStore
from harness.runtime.dynamic_context.tool_result_projector import ToolResultProjector


def test_tool_result_projector_persists_large_output_and_keeps_artifact_refs(tmp_path: Path) -> None:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))
    large_text = "line\n" * 2000

    projection, record = projector.project(
        {
            "result_envelope": {
                "envelope_id": "tool-result:test",
                "tool_name": "read_file",
                "status": "ok",
                "text": large_text,
                "artifact_refs": [{"path": "artifacts/report.txt"}],
            }
        },
        task_run_id="taskrun:test",
        projection_policy={"tool_result_preview_chars": 300},
    )

    assert projection["tool_name"] == "read_file"
    assert projection["status"] == "ok"
    assert projection["artifact_refs"] == [{"path": "artifacts/report.txt"}]
    assert projection["content_replacements"]
    assert Path(projection["content_replacements"][0]["path"]).exists()
    assert projection["replacement_ref"] == record["replacement_key"]


def test_tool_result_projector_hides_runtime_sandbox_physical_artifact_paths(tmp_path: Path) -> None:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))

    projection, _ = projector.project(
        {
            "result_envelope": {
                "envelope_id": "tool-result:sandbox-path",
                "tool_name": "write_file",
                "status": "ok",
                "artifact_refs": [
                    {
                        "path": "storage/task_environments/development/sandbox/artifacts/game.html",
                        "absolute_path": str(
                            tmp_path
                            / "storage"
                            / "runtime_state"
                            / "sandboxes"
                            / "taskrun_demo"
                            / "storage"
                            / "task_environments"
                            / "development"
                            / "sandbox"
                            / "artifacts"
                            / "game.html"
                        ),
                        "sandbox_path": "storage/task_environments/development/sandbox/artifacts/game.html",
                        "kind": "file",
                        "source": "write_file",
                    }
                ],
            }
        },
        task_run_id="taskrun:sandbox-path",
        projection_policy={"tool_result_preview_chars": 300},
    )

    artifact_ref = projection["artifact_refs"][0]
    assert artifact_ref == {
        "path": "storage/task_environments/development/sandbox/artifacts/game.html",
        "kind": "file",
        "source": "write_file",
    }
    assert "absolute_path" not in artifact_ref
    assert "sandbox_path" not in artifact_ref


def test_tool_result_projector_reuses_projection_bytes_for_same_content(tmp_path: Path) -> None:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))
    payload = {
        "result_envelope": {
            "envelope_id": "tool-result:stable",
            "tool_name": "fetch_url",
            "status": "error",
            "text": "gateway timeout",
            "structured_error": {"code": "http_504", "message": "gateway timeout", "retryable": True},
        }
    }

    first, _ = projector.project(payload, task_run_id="taskrun:stable", projection_policy={"tool_result_preview_chars": 100})
    second, _ = projector.project(payload, task_run_id="taskrun:stable", projection_policy={"tool_result_preview_chars": 100})

    assert second == first
    assert first["status"] == "error"
    assert first["error"] == "gateway timeout"


def test_tool_result_projector_preserves_provider_retry_policy_fields(tmp_path: Path) -> None:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))

    projection, _ = projector.project(
        {
            "result_envelope": {
                "envelope_id": "tool-result:image-error",
                "tool_name": "image_generate",
                "status": "error",
                "structured_error": {
                    "code": "image_provider_transient_error",
                    "message": "gateway timeout",
                    "retryable": False,
                    "origin": "image_provider",
                    "provider_retryable": True,
                    "agent_retry_policy": "do_not_auto_retry",
                    "attempts": [
                        {
                            "model": "gpt-image-2",
                            "attempt_index": 1,
                            "http_status": 504,
                            "code": "image_provider_transient_error",
                            "retryable": True,
                        }
                    ],
                },
            }
        },
        task_run_id="taskrun:image-error",
        projection_policy={"tool_result_preview_chars": 300},
    )

    structured_error = projection["structured_error"]
    assert structured_error["provider_retryable"] is True
    assert structured_error["agent_retry_policy"] == "do_not_auto_retry"
    assert structured_error["attempts"][0]["http_status"] == 504


def test_tool_result_projector_extracts_structured_error_from_json_result_text(tmp_path: Path) -> None:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))

    projection, _ = projector.project(
        {
            "tool_result_ref": "obs:image",
            "tool_name": "image_generate",
            "result": json.dumps(
                {
                    "ok": False,
                    "error": "gateway timeout",
                    "structured_error": {
                        "code": "image_provider_transient_error",
                        "message": "Image API failed with status 504",
                        "retryable": False,
                        "origin": "image_provider",
                        "provider_retryable": True,
                        "agent_retry_policy": "do_not_auto_retry",
                        "attempts": [
                            {
                                "model": "gpt-image-2",
                                "attempt_index": 1,
                                "http_status": 504,
                                "code": "image_provider_transient_error",
                                "retryable": True,
                            }
                        ],
                    },
                }
            ),
        },
        task_run_id="taskrun:image-error-json",
        projection_policy={"tool_result_preview_chars": 300},
    )

    assert projection["status"] == "error"
    assert projection["error"] == "gateway timeout"
    structured_error = projection["structured_error"]
    assert structured_error["provider_retryable"] is True
    assert structured_error["agent_retry_policy"] == "do_not_auto_retry"
    assert structured_error["attempts"][0]["http_status"] == 504
