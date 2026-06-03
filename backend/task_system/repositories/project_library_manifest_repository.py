from __future__ import annotations

from pathlib import Path

from file_management import default_file_environment_registry
from task_system.environments import task_environment_registry_from_backend_dir
from task_system.projects.project_library_manifest import (
    ProjectLifecycleActionSpec,
    ProjectLibraryManifest,
    ProjectRepositoryBinding,
    project_library_manifest_from_dict,
)
from task_system.repositories.project_instance_repository import ProjectInstanceRepository
from task_system.storage import TaskSystemStorage


class ProjectLibraryManifestRepository:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = TaskSystemStorage(self.base_dir)
        self.project_repository = ProjectInstanceRepository(self.base_dir)

    def list(self) -> list[ProjectLibraryManifest]:
        defaults = [item.to_dict() for item in self._default_manifests()]
        payload = self.storage.read_object("project_library_manifests.json", {"manifests": defaults})
        manifests = [
            self._migrate_manifest(project_library_manifest_from_dict(item))
            for item in list(payload.get("manifests") or [])
            if isinstance(item, dict)
        ]
        merged = {item.project_id: item for item in self._default_manifests()}
        merged.update({item.project_id: item for item in manifests})
        normalized = [item.to_dict() for item in sorted(merged.values(), key=lambda item: item.project_id)]
        if payload.get("manifests") != normalized:
            self.storage.write_object("project_library_manifests.json", {"manifests": normalized})
        result = [project_library_manifest_from_dict(item) for item in normalized]
        for manifest in result:
            self.validate(manifest)
        return result

    def get_for_project(self, project_id: str) -> ProjectLibraryManifest | None:
        target = str(project_id or "").strip()
        return next((item for item in self.list() if item.project_id == target), None)

    def require_for_project(self, project_id: str) -> ProjectLibraryManifest:
        manifest = self.get_for_project(project_id)
        if manifest is None:
            raise KeyError(f"project library manifest not found: {project_id}")
        return manifest

    def upsert(self, manifest: ProjectLibraryManifest) -> ProjectLibraryManifest:
        self.validate(manifest)
        manifests = [item for item in self.list() if item.project_id != manifest.project_id]
        manifests.append(manifest)
        self.storage.write_object("project_library_manifests.json", {"manifests": [item.to_dict() for item in sorted(manifests, key=lambda item: item.project_id)]})
        return manifest

    def validate(self, manifest: ProjectLibraryManifest) -> None:
        project = self.project_repository.require(manifest.project_id)
        if project.environment_id != manifest.environment_id:
            raise ValueError("project library manifest environment does not match project")
        environment = task_environment_registry_from_backend_dir(self.base_dir).require(manifest.environment_id)
        allowed_profile_ids = set(environment.spec.file_management.file_profile_refs)
        if manifest.file_profile_id not in allowed_profile_ids:
            raise ValueError("project library manifest file_profile_id is not allowed by environment")
        profile = default_file_environment_registry().require_profile(manifest.file_profile_id)
        allowed_repository_ids = {repo.repository_id for repo in profile.repository_specs}
        missing = sorted({item.repository_id for item in manifest.repositories} - allowed_repository_ids)
        if missing:
            raise ValueError(f"project library manifest repository not in file profile: {', '.join(missing)}")
        allowed_operations = {"delete_task_records_by_selector"}
        invalid_operations = sorted(
            {item.operation for item in manifest.lifecycle_actions if item.operation not in allowed_operations}
        )
        if invalid_operations:
            raise ValueError(f"project lifecycle action operation is not supported: {', '.join(invalid_operations)}")

    def _migrate_manifest(self, manifest: ProjectLibraryManifest) -> ProjectLibraryManifest:
        default = next((item for item in self._default_manifests() if item.project_id == manifest.project_id), None)
        if default is None:
            return manifest
        repositories = tuple(_migrate_repository_binding(item, default) for item in manifest.repositories)
        if manifest.lifecycle_actions:
            lifecycle_actions = manifest.lifecycle_actions
        else:
            lifecycle_actions = default.lifecycle_actions
        migration_log = tuple(dict(item) for item in manifest.migration_log)
        if repositories != manifest.repositories or lifecycle_actions != manifest.lifecycle_actions:
            migration_log = (
                *migration_log,
                {
                    "migration_id": "project_library_manifest.v1.lifecycle_actions_and_roots",
                    "description": "Aligned project library roots and lifecycle actions with authoritative defaults.",
                },
            )
        return ProjectLibraryManifest(
            library_id=manifest.library_id,
            project_id=manifest.project_id,
            environment_id=manifest.environment_id,
            file_profile_id=manifest.file_profile_id,
            schema_version=manifest.schema_version,
            template_id=manifest.template_id,
            repositories=repositories,
            lifecycle_actions=lifecycle_actions,
            indexes=dict(manifest.indexes),
            migration_log=migration_log,
            metadata=dict(manifest.metadata),
            authority=manifest.authority,
        )

    def _default_manifests(self) -> tuple[ProjectLibraryManifest, ...]:
        return (
            ProjectLibraryManifest(
                library_id="library.project.creation.writing.honghuang",
                project_id="project.creation.writing.honghuang",
                environment_id="env.creation.writing",
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
                        title="清理旧节点任务",
                        operation="delete_task_records_by_selector",
                        description="清理从旧节点任务模型迁移后残留的任务记录；图定义、运行产物和项目库保留。",
                        selectors={
                            "task_environment_id": "env.creation.writing",
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
                metadata={"default_manifest": True},
            ),
            ProjectLibraryManifest(
                library_id="library.project.development.codebase.langchain_agent",
                project_id="project.development.codebase.langchain_agent",
                environment_id="env.coding.vibe_workspace",
                file_profile_id="file_profile.managed_project_workspace",
                schema_version="code_project_library.v1",
                template_id="development.template.codebase",
                repositories=(
                    ProjectRepositoryBinding("repo.managed_project.project_workspace", "project_workspace", "workspace://project", "canonical", readable=True, writable=False),
                    ProjectRepositoryBinding("repo.managed_project.sandbox_workspace", "sandbox_workspace", "sandbox://workspace", "working", readable=True, writable=True),
                    ProjectRepositoryBinding("repo.managed_project.git_worktree_view", "git_worktree_view", "git://worktree", "projection", readable=True, writable=False),
                    ProjectRepositoryBinding("repo.managed_project.material_mounts", "material_mount", "sandbox://materials", "material", readable=True, writable=False),
                    ProjectRepositoryBinding("repo.managed_project.test_artifacts", "test_artifacts", "runtime://test_artifacts", "run_output", readable=True, writable=True),
                ),
                indexes={"file_index": "pending"},
                metadata={"default_manifest": True},
            ),
        )


def _migrate_repository_binding(binding: ProjectRepositoryBinding, default: ProjectLibraryManifest) -> ProjectRepositoryBinding:
    default_binding = default.repository(binding.repository_id)
    if default_binding is None:
        return binding
    obsolete_root_refs = {
        ("repo.writing.artifact_repository", "project://artifacts"): "environment://artifacts",
    }
    migrated_root_ref = obsolete_root_refs.get((binding.repository_id, binding.root_ref))
    if migrated_root_ref is None or migrated_root_ref != default_binding.root_ref:
        return binding
    return ProjectRepositoryBinding(
        repository_id=binding.repository_id,
        role=binding.role,
        root_ref=migrated_root_ref,
        lifecycle=binding.lifecycle,
        readable=binding.readable,
        writable=binding.writable,
        searchable=binding.searchable,
        commit_gate=binding.commit_gate,
        metadata={**dict(binding.metadata), "migrated_root_ref_from": binding.root_ref},
    )
