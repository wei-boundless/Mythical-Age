from __future__ import annotations

import json
from pathlib import Path

from artifact_system.artifact_authority import (
    ArtifactAuthority,
    artifact_materialization_ref,
    artifact_ref_value,
    artifact_refs_from_tool_result_payload,
    model_visible_artifact_refs,
)
from artifact_system.artifact_repository_service import ArtifactRepositoryService


def test_artifact_authority_merges_repository_and_runtime_refs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    published = workspace / "storage/task/artifacts/report.md"
    published.parent.mkdir(parents=True)
    published.write_text("# report", encoding="utf-8")
    sandbox = tmp_path / "sandbox" / "storage/task/artifacts/report.md"
    sandbox.parent.mkdir(parents=True)
    sandbox.write_text("# sandbox", encoding="utf-8")
    repository = ArtifactRepositoryService(tmp_path / "repo", workspace_root=workspace)
    repository.record_materialization(
        task_run_id="taskrun:artifact-authority",
        repository_id="artifact.repository.default",
        collection_id="default",
        artifact_refs=["artifact:storage/task/artifacts/report.md"],
        created_files=["report.md"],
        artifact_root="storage/task/artifacts",
        status="accepted",
    )

    view = ArtifactAuthority(
        workspace_root=workspace,
        artifact_repository=repository,
    ).task_artifact_view(
        task_run_id="taskrun:artifact-authority",
        candidate_refs=[
            {"path": "storage/task/artifacts/report.md", "absolute_path": str(sandbox), "source": "write_file"},
            {"path": "storage/task/artifacts/missing.md", "source": "write_file"},
        ],
    )

    assert view["authority"] == "artifact_system.artifact_authority"
    assert view["artifact_count"] == 1
    assert view["created_files"] == ["storage/task/artifacts/report.md"]
    assert view["artifact_refs"][0]["absolute_path"] == str(published.resolve())
    assert view["artifact_refs"][0]["exists"] is True
    assert view["artifact_refs"][0]["repository_status"] == "accepted"


def test_artifact_authority_keeps_existing_agent_result_refs_without_repository(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    artifact = workspace / "output/final.html"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("<!doctype html>", encoding="utf-8")

    view = ArtifactAuthority(workspace_root=workspace).task_artifact_view(
        task_run_id="taskrun:artifact-authority",
        candidate_refs=[
            "output/final.html",
            "output/missing.html",
        ],
    )

    assert view["artifact_count"] == 1
    assert view["created_files"] == ["output/final.html"]
    assert view["artifact_refs"][0]["exists"] is True


def test_artifact_authority_preserves_managed_repository_logical_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    logical_path = "reports/summary.md"
    artifact = workspace / ".managed-files" / "artifacts" / "managed-project" / "artifacts" / logical_path
    artifact.parent.mkdir(parents=True)
    artifact.write_text("managed artifact", encoding="utf-8")

    view = ArtifactAuthority(workspace_root=workspace).task_artifact_view(
        task_run_id="taskrun:artifact-authority-managed",
        candidate_refs=[
            {
                "path": logical_path,
                "absolute_path": str(artifact),
                "repository_id": "repo.managed_project.artifacts",
                "repository_kind": "artifact_repository",
                "source": "write_file",
            }
        ],
    )

    assert view["artifact_count"] == 1
    assert view["created_files"] == [logical_path]
    assert view["artifact_refs"][0]["path"] == logical_path
    assert view["artifact_refs"][0]["absolute_path"] == str(artifact.resolve())
    assert ".managed-files" not in view["created_files"][0]


def test_artifact_authority_extracts_tool_result_refs_from_all_payload_layers() -> None:
    refs = artifact_refs_from_tool_result_payload(
        {
            "artifact_refs": [{"path": "artifacts/top.md", "source": "payload"}],
            "result_envelope": {
                "artifact_refs": [{"path": "artifacts/envelope.md", "source": "envelope"}],
                "structured_payload": {
                    "artifact_refs": [{"path": "artifacts/structured.md", "source": "structured"}],
                    "tool_result": {
                        "artifact_refs": [{"artifact_ref": "artifact:artifacts/nested.md", "source": "tool_result"}]
                    },
                },
            },
        }
    )

    assert [item["path"] for item in refs] == [
        "artifacts/top.md",
        "artifacts/envelope.md",
        "artifacts/structured.md",
        "artifacts/nested.md",
    ]


def test_artifact_authority_extracts_image_ref_from_json_tool_result() -> None:
    refs = artifact_refs_from_tool_result_payload(
        {
            "tool_name": "image_generate",
            "result": json.dumps(
                {
                    "ok": True,
                    "image": {
                        "file_path": "storage/generated/images/hero.png",
                        "mime_type": "image/png",
                    },
                }
            ),
        }
    )

    assert refs == [
        {
            "path": "storage/generated/images/hero.png",
            "kind": "image",
            "source": "image_generate",
            "mime_type": "image/png",
        }
    ]


def test_artifact_authority_prefers_image_project_path_over_absolute_file_path(tmp_path: Path) -> None:
    absolute_path = tmp_path / "storage" / "generated" / "images" / "hero.png"
    refs = artifact_refs_from_tool_result_payload(
        {
            "tool_name": "image_generate",
            "result": json.dumps(
                {
                    "ok": True,
                    "image": {
                        "src": "/api/image-assets/files/hero.png",
                        "path": "storage/generated/images/hero.png",
                        "file_path": str(absolute_path),
                        "absolute_path": str(absolute_path),
                        "storage_authority": "image_asset_store",
                        "bypass_sandbox_publish": True,
                    },
                }
            ),
        }
    )

    assert refs == [
        {
            "path": "storage/generated/images/hero.png",
            "absolute_path": str(absolute_path),
            "src": "/api/image-assets/files/hero.png",
            "storage_authority": "image_asset_store",
            "bypass_sandbox_publish": True,
            "kind": "image",
            "source": "image_generate",
        }
    ]


def test_artifact_authority_maps_image_asset_src_to_project_store_path() -> None:
    refs = artifact_refs_from_tool_result_payload(
        {
            "tool_name": "image_generate",
            "result": json.dumps(
                {
                    "ok": True,
                    "image": {
                        "src": "/api/image-assets/files/hero.png",
                    },
                }
            ),
        }
    )

    assert refs == [
        {
            "path": "storage/generated/images/hero.png",
            "src": "/api/image-assets/files/hero.png",
            "kind": "image",
            "source": "image_generate",
        }
    ]


def test_model_visible_artifact_refs_hides_runtime_sandbox_absolute_path(tmp_path: Path) -> None:
    refs = model_visible_artifact_refs(
        [
            {
                "absolute_path": str(tmp_path / "storage" / "runtime_state" / "sandboxes" / "taskrun" / "artifact.html"),
                "sandbox_path": "storage/task_environments/coding/vibe-workspace/artifacts/artifact.html",
                "kind": "file",
            },
            {
                "path": "storage/task_environments/coding/vibe-workspace/artifacts/artifact.html",
                "absolute_path": str(tmp_path / "storage" / "runtime_state" / "sandboxes" / "taskrun" / "artifact.html"),
                "sandbox_path": "storage/task_environments/coding/vibe-workspace/artifacts/artifact.html",
                "kind": "file",
            },
        ]
    )

    assert refs == [{"path": "storage/task_environments/coding/vibe-workspace/artifacts/artifact.html", "kind": "file"}]


def test_artifact_ref_value_separates_model_path_from_materialization_ref() -> None:
    ref = {"artifact_ref": "artifact:storage/task/artifacts/report.md"}

    assert artifact_ref_value(ref) == "storage/task/artifacts/report.md"
    assert artifact_materialization_ref(ref) == "artifact:storage/task/artifacts/report.md"
