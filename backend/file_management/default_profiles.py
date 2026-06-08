from __future__ import annotations

from .models import (
    CommitPolicy,
    FileAccessRule,
    ManagedFileEnvironmentProfile,
    ManagedFileRepositorySpec,
    VersioningPolicy,
)


def default_file_environment_profiles() -> tuple[ManagedFileEnvironmentProfile, ...]:
    return (
        base_workspace_profile(),
        writing_manuscript_profile(),
        managed_project_workspace_profile(),
        web_research_evidence_profile(),
        data_analysis_workspace_profile(),
        document_processing_profile(),
        general_workspace_profile(),
    )


def base_workspace_profile() -> ManagedFileEnvironmentProfile:
    return ManagedFileEnvironmentProfile(
        profile_id="file_profile.base_workspace",
        title="Base Workspace",
        description="Shared managed workspace profile for generic local file access.",
        repository_specs=(
            ManagedFileRepositorySpec(
                repository_id="repo.base.project_workspace",
                repository_kind="project_workspace",
                storage_adapter="fsspec_local",
                scope_kind="project_scoped",
                root_ref="workspace://project",
                title="Project workspace",
                readable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="base workspace read grant"),
                    FileAccessRule(action="search", behavior="allow", reason="base workspace search grant"),
                    FileAccessRule(action="write", behavior="deny", reason="base workspace write requires task-specific grant"),
                    FileAccessRule(action="edit", behavior="deny", reason="base workspace edit requires task-specific grant"),
                ),
            ),
        ),
    )


def writing_manuscript_profile() -> ManagedFileEnvironmentProfile:
    versioning = VersioningPolicy(
        enabled=True,
        backend="dulwich_git",
        content_addressed=True,
        require_content_hash=True,
    )
    canonical_commit = CommitPolicy(
        required_for_canonical_write=True,
        requires_review_receipt=True,
        requires_approval=True,
        allowed_commit_sources=("review_gate", "human_gate", "task_graph_commit_node"),
    )
    return ManagedFileEnvironmentProfile(
        profile_id="file_profile.writing_manuscript",
        title="Writing Manuscript File Environment",
        description="Managed writing files for formal works, drafts, artifacts, memory indexes, and assets.",
        repository_specs=(
            ManagedFileRepositorySpec(
                repository_id="repo.writing.official_work",
                repository_kind="official_work",
                storage_adapter="dulwich_git",
                scope_kind="project_scoped",
                root_ref="writing://official",
                title="Official work repository",
                readable=True,
                searchable=True,
                versioned=True,
                canonical=True,
                commit_required=True,
                rollback_supported=True,
                versioning_policy=versioning,
                commit_policy=canonical_commit,
                access_rules=(
                    FileAccessRule(action="open", behavior="allow", reason="formal work can be opened for context"),
                    FileAccessRule(action="read", behavior="allow", reason="canonical manuscript can be read"),
                    FileAccessRule(action="search", behavior="allow", reason="canonical manuscript can be searched"),
                    FileAccessRule(
                        action="write",
                        behavior="ask",
                        reason="canonical write requires review receipt and commit gate",
                        requires_review_receipt=True,
                        requires_commit_gate=True,
                    ),
                    FileAccessRule(
                        action="commit",
                        behavior="ask",
                        reason="official work commit is gated",
                        requires_review_receipt=True,
                        requires_commit_gate=True,
                    ),
                    FileAccessRule(action="rollback", behavior="ask", reason="rollback is platform-audited"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.writing.draft_workspace",
                repository_kind="draft_workspace",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="writing://drafts",
                title="Writing draft workspace",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                versioning_policy=versioning,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="drafts are task-readable"),
                    FileAccessRule(action="search", behavior="allow", reason="drafts are task-searchable"),
                    FileAccessRule(action="write", behavior="allow", reason="candidate drafts are writable"),
                    FileAccessRule(action="edit", behavior="allow", reason="candidate drafts are editable"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.writing.review_workspace",
                repository_kind="review_workspace",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="writing://reviews",
                title="Writing review workspace",
                readable=True,
                writable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="reviews are task-readable"),
                    FileAccessRule(action="write", behavior="allow", reason="review receipts are writable"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.writing.artifact_repository",
                repository_kind="artifact_repository",
                storage_adapter="artifact_repository",
                scope_kind="project_scoped",
                root_ref="artifact://writing/manuscript",
                title="Writing artifact repository",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                versioning_policy=versioning,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="writing artifacts are readable"),
                    FileAccessRule(action="search", behavior="allow", reason="artifact refs are searchable"),
                    FileAccessRule(action="write", behavior="allow", reason="task artifacts can be materialized"),
                ),
                metadata={"projection_owner": "artifact_policy"},
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.writing.memory_repository",
                repository_kind="memory_repository",
                storage_adapter="formal_memory",
                scope_kind="project_scoped",
                root_ref="memory://writing/formal",
                title="Writing memory repository",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                commit_required=True,
                versioning_policy=versioning,
                commit_policy=CommitPolicy(
                    required_for_canonical_write=True,
                    requires_review_receipt=True,
                    allowed_commit_sources=("memory_commit_node", "human_gate"),
                ),
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="writing memory can be read"),
                    FileAccessRule(action="search", behavior="allow", reason="writing memory can be searched"),
                    FileAccessRule(action="write", behavior="allow", reason="memory candidates can be written"),
                    FileAccessRule(
                        action="commit",
                        behavior="ask",
                        reason="formal memory commit requires review or commit node",
                        requires_review_receipt=True,
                        requires_commit_gate=True,
                    ),
                ),
                metadata={"projection_owner": "memory_space"},
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.writing.assets",
                repository_kind="asset_repository",
                storage_adapter="fsspec_local",
                scope_kind="project_scoped",
                root_ref="writing://assets",
                title="Writing asset repository",
                readable=True,
                writable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="assets are readable"),
                    FileAccessRule(action="write", behavior="allow", reason="task assets can be saved"),
                ),
            ),
        ),
        default_access_policy={"canonical_write": "review_commit_required"},
        default_version_policy={"backend": "dulwich_git", "content_addressed": True},
        default_commit_policy={"official_work": "review_receipt_and_commit_gate"},
        default_projection_policy={
            "artifact_policy": "repo.writing.artifact_repository",
            "memory_space": "repo.writing.memory_repository",
        },
    )


def managed_project_workspace_profile() -> ManagedFileEnvironmentProfile:
    return ManagedFileEnvironmentProfile(
        profile_id="file_profile.managed_project_workspace",
        title="Managed Project Workspace File Environment",
        description="Generic managed project workspace with sandbox overlay, git view, material mounts, and runtime artifacts.",
        repository_specs=(
            ManagedFileRepositorySpec(
                repository_id="repo.managed_project.project_workspace",
                repository_kind="project_workspace",
                storage_adapter="fsspec_local",
                scope_kind="project_scoped",
                root_ref="workspace://project",
                title="Project workspace",
                readable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="project workspace read grant"),
                    FileAccessRule(action="search", behavior="allow", reason="project workspace search grant"),
                    FileAccessRule(action="write", behavior="ask", reason="real workspace write requires task grant and approval"),
                    FileAccessRule(action="edit", behavior="ask", reason="real workspace edit requires task grant and approval"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.managed_project.sandbox_workspace",
                repository_kind="sandbox_workspace",
                storage_adapter="sandbox_overlay",
                scope_kind="run_scoped",
                root_ref="sandbox://workspace",
                title="Sandbox workspace",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="sandbox read grant"),
                    FileAccessRule(action="search", behavior="allow", reason="sandbox search grant"),
                    FileAccessRule(action="write", behavior="allow", reason="sandbox write grant"),
                    FileAccessRule(action="edit", behavior="allow", reason="sandbox edit grant"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.managed_project.artifacts",
                repository_kind="artifact_repository",
                storage_adapter="artifact_repository",
                scope_kind="run_scoped",
                root_ref="artifact://managed-project/artifacts",
                title="Managed project artifacts",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="managed artifacts are readable"),
                    FileAccessRule(action="search", behavior="allow", reason="managed artifacts are searchable"),
                    FileAccessRule(action="write", behavior="allow", reason="managed artifacts are writable"),
                    FileAccessRule(action="edit", behavior="allow", reason="managed artifacts are editable"),
                ),
                metadata={"projection_owner": "artifact_policy"},
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.managed_project.git_worktree_view",
                repository_kind="git_worktree_view",
                storage_adapter="git_worktree",
                scope_kind="project_scoped",
                root_ref="git://worktree",
                title="Git worktree view",
                readable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="git status and diff are read-only projections"),
                    FileAccessRule(action="search", behavior="allow", reason="git history can be searched by projection"),
                    FileAccessRule(action="write", behavior="deny", reason="git mutations are not file writes"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.managed_project.material_mounts",
                repository_kind="material_mount",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="sandbox://materials",
                title="Material mounts",
                readable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="mounted materials are read-only"),
                    FileAccessRule(action="search", behavior="allow", reason="mounted materials are searchable"),
                    FileAccessRule(action="write", behavior="deny", reason="mounted source materials are immutable"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.managed_project.test_artifacts",
                repository_kind="test_artifacts",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="runtime://test_artifacts",
                title="Test artifacts",
                readable=True,
                writable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="test artifacts are readable"),
                    FileAccessRule(action="write", behavior="allow", reason="test artifacts are writable"),
                ),
            ),
        ),
        default_access_policy={
            "real_workspace_write": "task_grant_required",
            "sandbox_write": "allowed",
            "artifact_write": "allowed",
        },
        default_projection_policy={"artifact_policy": "repo.managed_project.artifacts"},
    )


def web_research_evidence_profile() -> ManagedFileEnvironmentProfile:
    return ManagedFileEnvironmentProfile(
        profile_id="file_profile.web_research_evidence",
        title="Web Research Evidence File Environment",
        description="Managed evidence captures, download cache, and citation snapshots.",
        repository_specs=(
            ManagedFileRepositorySpec(
                repository_id="repo.research.evidence_archive",
                repository_kind="evidence_archive",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="research://evidence",
                title="Evidence archive",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="evidence archive is readable"),
                    FileAccessRule(action="search", behavior="allow", reason="evidence archive is searchable"),
                    FileAccessRule(action="write", behavior="allow", reason="evidence snapshots can be saved"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.research.download_cache",
                repository_kind="download_cache",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="research://downloads",
                title="Download cache",
                readable=True,
                writable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="download cache is readable"),
                    FileAccessRule(action="write", behavior="allow", reason="download cache can store fetched materials"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.research.citation_snapshots",
                repository_kind="citation_snapshot_repository",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="research://citations",
                title="Citation snapshot repository",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="citation snapshots are readable"),
                    FileAccessRule(action="write", behavior="allow", reason="citation snapshots can be saved"),
                ),
            ),
        ),
        default_access_policy={"external_write": "denied", "evidence_capture": "allowed"},
    )


def data_analysis_workspace_profile() -> ManagedFileEnvironmentProfile:
    return ManagedFileEnvironmentProfile(
        profile_id="file_profile.data_analysis_workspace",
        title="Data Analysis File Environment",
        description="Managed datasets, analysis workspace, and analysis artifacts.",
        repository_specs=(
            ManagedFileRepositorySpec(
                repository_id="repo.data.dataset_repository",
                repository_kind="material_mount",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="data://datasets",
                title="Dataset repository",
                readable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="datasets are readable"),
                    FileAccessRule(action="search", behavior="allow", reason="datasets are searchable"),
                    FileAccessRule(action="write", behavior="deny", reason="source datasets are immutable"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.data.analysis_workspace",
                repository_kind="sandbox_workspace",
                storage_adapter="sandbox_overlay",
                scope_kind="run_scoped",
                root_ref="data://analysis_workspace",
                title="Analysis workspace",
                readable=True,
                writable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="analysis workspace is readable"),
                    FileAccessRule(action="search", behavior="allow", reason="analysis workspace is searchable"),
                    FileAccessRule(action="write", behavior="allow", reason="analysis artifacts are writable"),
                    FileAccessRule(action="edit", behavior="allow", reason="analysis artifacts are editable"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.data.artifact_repository",
                repository_kind="artifact_repository",
                storage_adapter="artifact_repository",
                scope_kind="run_scoped",
                root_ref="artifact://data_analysis",
                title="Data analysis artifact repository",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="analysis artifacts are readable"),
                    FileAccessRule(action="write", behavior="allow", reason="analysis artifacts can be saved"),
                ),
            ),
        ),
        default_access_policy={"source_dataset_write": "denied", "analysis_artifact_write": "allowed"},
    )


def document_processing_profile() -> ManagedFileEnvironmentProfile:
    return ManagedFileEnvironmentProfile(
        profile_id="file_profile.document_processing",
        title="Document Processing File Environment",
        description="Managed document repository, extraction workspace, and document artifacts.",
        repository_specs=(
            ManagedFileRepositorySpec(
                repository_id="repo.document.document_repository",
                repository_kind="material_mount",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="document://source",
                title="Document repository",
                readable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="source documents are readable"),
                    FileAccessRule(action="search", behavior="allow", reason="source documents are searchable"),
                    FileAccessRule(action="write", behavior="deny", reason="source documents are immutable"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.document.extraction_workspace",
                repository_kind="sandbox_workspace",
                storage_adapter="fsspec_local",
                scope_kind="run_scoped",
                root_ref="document://extraction_workspace",
                title="Document extraction workspace",
                readable=True,
                writable=True,
                searchable=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="extractions are readable"),
                    FileAccessRule(action="search", behavior="allow", reason="extractions are searchable"),
                    FileAccessRule(action="write", behavior="allow", reason="extractions can be written"),
                    FileAccessRule(action="edit", behavior="allow", reason="extractions can be edited"),
                ),
            ),
            ManagedFileRepositorySpec(
                repository_id="repo.document.artifact_repository",
                repository_kind="artifact_repository",
                storage_adapter="artifact_repository",
                scope_kind="run_scoped",
                root_ref="artifact://document_processing",
                title="Document artifact repository",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="document artifacts are readable"),
                    FileAccessRule(action="write", behavior="allow", reason="document artifacts can be saved"),
                ),
            ),
        ),
        default_access_policy={"source_document_write": "denied", "document_artifact_write": "allowed"},
    )


def general_workspace_profile() -> ManagedFileEnvironmentProfile:
    return ManagedFileEnvironmentProfile(
        profile_id="file_profile.general_workspace",
        title="General Workspace File Environment",
        description="Read-mostly general workspace for lightweight conversation-scoped artifacts.",
        repository_specs=(
            ManagedFileRepositorySpec(
                repository_id="repo.general.conversation_artifacts",
                repository_kind="artifact_repository",
                storage_adapter="artifact_repository",
                scope_kind="session_scoped",
                root_ref="artifact://general_workspace",
                title="Conversation artifact repository",
                readable=True,
                writable=True,
                searchable=True,
                versioned=True,
                access_rules=(
                    FileAccessRule(action="read", behavior="allow", reason="conversation artifacts are readable"),
                    FileAccessRule(action="search", behavior="allow", reason="conversation artifacts are searchable"),
                    FileAccessRule(action="write", behavior="allow", reason="conversation artifacts can be saved"),
                    FileAccessRule(action="edit", behavior="ask", reason="artifact edits require task grant"),
                ),
            ),
        ),
        default_access_policy={"workspace_write": "denied", "artifact_write": "allowed"},
    )


