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
    assert large_text not in json.dumps(projection, ensure_ascii=False)

    plan = projection["rehydration_plan"]
    assert plan["authority"] == "harness.runtime.dynamic_context.rehydration_plan"
    assert plan["prompt_status"] == "preview_only"
    assert plan["replacement_ref"] == record["replacement_key"]
    assert record["rehydration_plan"] == plan
    persisted = plan["capabilities"][0]
    assert persisted["capability"] == "read_persisted_tool_result"
    assert persisted["content_replacements"][0]["path"] == projection["content_replacements"][0]["path"]
    assert "preview" in plan["instruction"]


def test_tool_result_projector_emits_read_file_rehydration_plan_for_partial_window(tmp_path: Path) -> None:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))

    projection, _ = projector.project(
        {
            "result_envelope": {
                "envelope_id": "tool-result:read-window",
                "tool_name": "read_file",
                "status": "ok",
                "text": "1 | first\n2 | second",
                "observed_paths": ["docs/long.md"],
                "structured_payload": {
                    "tool_result": {
                        "kind": "text_file",
                        "path": "docs/long.md",
                        "start_line": 1,
                        "end_line": 2,
                        "returned_lines": 2,
                        "line_count": 2,
                        "total_lines": 8,
                        "next_start_line": 3,
                        "has_more": True,
                        "truncated": True,
                        "content_sha256": "sha256:long-md",
                    }
                },
            }
        },
        task_run_id="taskrun:read-window",
        projection_policy={"tool_result_preview_chars": 300},
    )

    plan = projection["rehydration_plan"]
    assert plan["prompt_status"] == "file_window_only"
    range_capability = plan["capabilities"][0]
    assert range_capability["capability"] == "read_file_range"
    assert range_capability["content_range"]["content_sha256"] == "sha256:long-md"
    assert range_capability["next_request"] == {
        "tool_name": "read_file",
        "args": {"path": "docs/long.md", "start_line": 3, "line_count": 2},
    }
    assert "not proof that the whole file is in prompt" in range_capability["instruction"]


def test_tool_result_projector_projects_code_structure_as_locator_only(tmp_path: Path) -> None:
    projector = ToolResultProjector(root_dir=tmp_path, replacement_store=ReplacementStore(tmp_path))

    projection, _ = projector.project(
        {
            "tool_result_ref": "obs:codebase-search",
            "tool_name": "codebase_search",
            "result": json.dumps(
                {
                    "status": "completed",
                    "answer_candidate": "Found runtime.py",
                    "code_structure": {
                        "authority": "capability.codebase_search.code_structure_map",
                        "source_kind": "codebase_search",
                        "candidate_only": True,
                        "source_authority": "locator_only",
                        "instruction": "Use read_file next; do not treat snippets as complete source.",
                        "files": [
                            {
                                "path": "backend/capability_system/capabilities/codebase_search/runtime.py",
                                "candidate_only": True,
                                "must_read_source_before_edit": True,
                                "evidence_refs": ["backend/capability_system/capabilities/codebase_search/runtime.py:14"],
                                "slices": [
                                    {
                                        "evidence_ref": "backend/capability_system/capabilities/codebase_search/runtime.py:14",
                                        "matched_line": 14,
                                        "start_line": 10,
                                        "end_line": 30,
                                        "symbol": "CodebaseSearchCapability",
                                        "evidence_kind": "definition",
                                        "score": 0.95,
                                        "read_request": {
                                            "tool_name": "read_file",
                                            "args": {
                                                "path": "backend/capability_system/capabilities/codebase_search/runtime.py",
                                                "start_line": 10,
                                                "line_count": 21,
                                            },
                                        },
                                        "snippet": "class CodebaseSearchCapability:",
                                    }
                                ],
                            }
                        ],
                        "limitations": ["not_full_source"],
                    },
                }
            ),
        },
        task_run_id="taskrun:codebase-search",
        projection_policy={"tool_result_preview_chars": 300},
    )

    structure = projection["code_structure"]
    assert structure["candidate_only"] is True
    assert structure["source_authority"] == "locator_only"
    assert structure["files"][0]["must_read_source_before_edit"] is True
    assert structure["files"][0]["slices"][0]["read_request"]["tool_name"] == "read_file"
    assert "snippet" not in structure["files"][0]["slices"][0]


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
                    "retryable": True,
                    "origin": "image_provider",
                    "provider_retryable": True,
                    "agent_auto_retry_allowed": True,
                    "agent_retry_policy": "bounded_retry_with_backoff",
                    "max_agent_retry_attempts": 2,
                    "suggested_retry_delay_seconds": 15,
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
    assert structured_error["agent_auto_retry_allowed"] is True
    assert structured_error["agent_retry_policy"] == "bounded_retry_with_backoff"
    assert structured_error["max_agent_retry_attempts"] == 2
    assert structured_error["suggested_retry_delay_seconds"] == 15
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
                        "retryable": True,
                        "origin": "image_provider",
                        "provider_retryable": True,
                        "agent_auto_retry_allowed": True,
                        "agent_retry_policy": "bounded_retry_with_backoff",
                        "max_agent_retry_attempts": 2,
                        "suggested_retry_delay_seconds": 15,
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
    assert structured_error["agent_auto_retry_allowed"] is True
    assert structured_error["agent_retry_policy"] == "bounded_retry_with_backoff"
    assert structured_error["max_agent_retry_attempts"] == 2
    assert structured_error["attempts"][0]["http_status"] == 504
