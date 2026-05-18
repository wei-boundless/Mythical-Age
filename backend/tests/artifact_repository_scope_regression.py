from __future__ import annotations

from artifact_system import ArtifactRepositoryService


def test_artifact_repository_defaults_to_task_run_isolation(tmp_path) -> None:
    service = ArtifactRepositoryService(tmp_path)
    service.record_materialization(
        task_run_id="taskrun:one",
        repository_id="artifact.project.manuscript",
        collection_id="chapters",
        stage_id="chapter_draft",
        node_run_id="taskrun:one:chapter_draft",
        artifact_refs=["artifact:output/run-one/chapter.md"],
        created_files=["chapter.md"],
        status="accepted",
    )

    run_one = service.overview(task_run_id="taskrun:one", repository_id="artifact.project.manuscript")
    run_two = service.overview(task_run_id="taskrun:two", repository_id="artifact.project.manuscript")

    assert run_one["artifact_count"] == 1
    assert run_one["artifacts"][0]["task_run_id"] == "taskrun:one"
    assert run_two["artifact_count"] == 0
