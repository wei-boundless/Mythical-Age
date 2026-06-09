from __future__ import annotations

from pathlib import Path

from task_system.projects.project_instance import ProjectInstance
from task_system.projects.project_library_manifest import (
    ProjectLifecycleActionSpec,
    ProjectLibraryManifest,
    ProjectRepositoryBinding,
)
from task_system.repositories.project_instance_repository import ProjectInstanceRepository
from task_system.repositories.project_library_manifest_repository import ProjectLibraryManifestRepository


WRITING_PROJECT_ID = "project.creation.writing.honghuang"
WRITING_LIBRARY_ID = "library.project.creation.writing.honghuang"
WRITING_ENVIRONMENT_ID = "env.creation.writing"


def seed_writing_project(base_dir: Path, *, cleanup_environment_id: str = "env.office.file_search") -> None:
    ProjectInstanceRepository(base_dir).upsert(
        ProjectInstance(
            project_id=WRITING_PROJECT_ID,
            environment_id=WRITING_ENVIRONMENT_ID,
            title="Honghuang Era",
            project_kind="long_novel",
            template_id="writing.template.long_novel.commercial",
            library_id=WRITING_LIBRARY_ID,
            schema_version="writing_library.v1",
            metadata={"seed": "honghuang-era"},
        )
    )
    ProjectLibraryManifestRepository(base_dir).upsert(
        ProjectLibraryManifest(
            library_id=WRITING_LIBRARY_ID,
            project_id=WRITING_PROJECT_ID,
            environment_id=WRITING_ENVIRONMENT_ID,
            file_profile_id="file_profile.writing_manuscript",
            schema_version="writing_library.v1",
            template_id="writing.template.long_novel.commercial",
            repositories=(
                ProjectRepositoryBinding("repo.writing.official_work", "official_work", "project://official_work", "canonical", readable=True, writable=False, commit_gate="review_required"),
                ProjectRepositoryBinding("repo.writing.draft_workspace", "draft_workspace", "project://drafts", "working", readable=True, writable=True),
                ProjectRepositoryBinding("repo.writing.review_workspace", "review_workspace", "project://reviews", "review", readable=True, writable=True),
                ProjectRepositoryBinding("repo.writing.artifact_repository", "artifact_repository", "environment://artifacts", "run_output", readable=True, writable=True),
                ProjectRepositoryBinding("repo.writing.memory_repository", "project_memory", "project://memory/project", "committed_memory", readable=True, writable=True, commit_gate="review_required"),
                ProjectRepositoryBinding("repo.writing.assets", "asset_repository", "project://assets", "asset", readable=True, writable=True),
            ),
            lifecycle_actions=(
                ProjectLifecycleActionSpec(
                    action_id="cleanup_legacy_writing_tasks",
                    title="Cleanup legacy writing tasks",
                    operation="delete_task_records_by_selector",
                    description="Delete legacy writing node task records while preserving graphs and project resources.",
                    selectors={
                        "task_environment_id": cleanup_environment_id,
                        "task_id_contains": "writing.modular_novel.node.",
                        "include_assignments": True,
                        "include_specific_task_records": True,
                    },
                    safeguards={
                        "preserve_task_graphs": True,
                        "preserve_artifacts": True,
                        "preserve_project_instances": True,
                    },
                ),
            ),
            indexes={"file_index": "pending", "artifact_index": "pending", "memory_index": "pending"},
            metadata={"seed": "honghuang-era"},
        )
    )
