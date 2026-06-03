from __future__ import annotations

from pathlib import Path

from artifact_system.artifact_authority import ArtifactAuthority
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
