from __future__ import annotations

from .models import (
    ArtifactPolicy,
    EnvironmentPrompt,
    ExecutionPolicy,
    FileManagementBinding,
    MemorySpace,
    ResourceSpace,
    RiskPolicy,
    SandboxPolicy,
    TaskEnvironmentDefinition,
    TaskEnvironmentGroup,
    TaskEnvironmentRecord,
    TaskEnvironmentSpec,
)


def default_task_environment_groups() -> tuple[TaskEnvironmentGroup, ...]:
    return (
        TaskEnvironmentGroup(
            group_id="environment_group.coding",
            title="Coding",
            description="Dedicated coding task environments with project file state, sandbox execution, git visibility, and verification artifacts.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.development",
            title="Development",
            description="General development environment for implementation and command-based verification without binding to a specific coding workspace profile.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.creation",
            title="Creation",
            description="Creative work environment for writing, research, draft management, and review-ready outputs.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.general",
            title="General",
            description="General-purpose work environment for broad tasks that should not narrow the agent profile.",
        ),
    )


def default_task_environments() -> tuple[TaskEnvironmentDefinition, ...]:
    return (
        coding_vibe_workspace_environment(),
        development_sandbox_environment(),
        creation_writing_environment(),
        general_workspace_environment(),
    )


def coding_vibe_workspace_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.coding.vibe_workspace",
        title="Vibe 编码工作区",
        description="Dedicated coding task environment for project inspection, implementation, file-state-aware iteration, command verification, and delivery evidence.",
        group_id="environment_group.coding",
        environment_kind="coding",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.coding.vibe_workspace.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.coding.vibe_workspace.orientation.v1",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.coding_workspace.v1",
                prompt_kind="boundary_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.codebase_inspection.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.large_scope_exploration.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.editing.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.verification.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.git_safety.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.windows_shell.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.task_progress.v1",
                prompt_kind="coding_rule",
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=True,
            sandbox_mode="workspace_overlay",
            workspace_access="project_read_sandbox_write",
            write_policy="sandbox_or_task_granted",
            shell_policy="sandboxed",
            browser_policy="sandboxed",
            network_policy="task_decided",
            side_effect_policy="sandbox_boundary",
            side_effect_operations=(
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.browser_control",
                "op.image_generate",
                "op.git_branch_create",
                "op.git_stage",
                "op.git_unstage",
                "op.git_commit",
                "op.git_restore",
                "op.git_push",
            ),
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.managed_project_workspace",),
            required_repository_kinds=("project_workspace", "sandbox_workspace", "git_worktree_view", "test_artifacts"),
            canonical_write_policy="sandbox_write_real_workspace_requires_task_grant",
            constraints={
                "project_workspace_read": "allowed",
                "project_workspace_write": "task_granted",
                "sandbox_workspace_write": "allowed",
                "git_worktree_view": "read_only",
                "default_read_repository": "repo.managed_project.sandbox_workspace",
                "default_search_repository": "repo.managed_project.sandbox_workspace",
                "default_write_repository": "repo.managed_project.sandbox_workspace",
                "default_edit_repository": "repo.managed_project.sandbox_workspace",
            },
        ),
        resource_space=ResourceSpace(
            workspace_policy="project_workspace",
            storage_namespace="coding/vibe-workspace",
            material_mount_policy="sandbox_material_mounts",
            project_file_policy="file_profile.managed_project_workspace",
            managed_file_environment_policy="file_profile.managed_project_workspace",
            browser_environment_policy="local_browser",
            artifact_root_policy="environment_scoped_artifacts",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("project_architecture_notes", "prior_runtime_findings"),
            project_knowledge_refs=("project_docs",),
            retrieval_index_refs=("code_search_index",),
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=True,
            sandbox_mode="workspace_overlay",
            real_workspace_access="read_only_or_task_granted",
            write_scope_policy="sandbox_or_file_access_table",
            shell_execution_policy="sandboxed",
            browser_execution_policy="sandboxed",
            network_execution_policy="task_decided",
            side_effect_policy="sandbox_boundary",
        ),
        risk_policy=RiskPolicy(
            default_permission_mode="environment_boundary",
            approval_required_risk_levels=("real_workspace_write", "external_write"),
            auto_denied_risk_levels=("destructive_unbounded",),
        ),
        artifact_policy=ArtifactPolicy(
            artifact_root="environment_scoped_artifacts",
            publish_policy="verification_required",
        ),
        observability_policy={
            "file_state_authority": "runtime.memory.file_state_authority",
            "file_state_projection": "enabled",
            "tool_result_envelope_events": "enabled",
        },
        lifecycle_policy={
            "coding_task_environment": True,
            "graph_entry_policy": "fixed_entry_not_scheduled_by_environment",
        },
        metadata={
            "dedicated_task_environment": "coding",
            "managed_project_workspace_profile": "file_profile.managed_project_workspace",
            "file_management_scope": "generic_runtime_authority",
        },
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def development_sandbox_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.development.sandbox",
        title="开发沙盒",
        description="General development sandbox for implementation, command-based verification, and delivery evidence.",
        group_id="environment_group.development",
        environment_kind="development",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.development.sandbox.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.development.sandbox.orientation.v1",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.development_sandbox.v1",
                prompt_kind="boundary_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.codebase_inspection.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.large_scope_exploration.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.editing.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.verification.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.git_safety.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.windows_shell.v1",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.task_progress.v1",
                prompt_kind="coding_rule",
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=True,
            sandbox_mode="workspace_overlay",
            workspace_access="project_read_sandbox_write",
            write_policy="sandbox_or_task_granted",
            shell_policy="sandboxed",
            browser_policy="sandboxed",
            network_policy="task_decided",
            side_effect_policy="sandbox_boundary",
            side_effect_operations=(
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.browser_control",
                "op.image_generate",
                "op.git_branch_create",
                "op.git_stage",
                "op.git_unstage",
                "op.git_commit",
                "op.git_restore",
                "op.git_push",
            ),
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.base_workspace",),
            required_repository_kinds=("project_workspace",),
            canonical_write_policy="sandbox_write_real_workspace_requires_task_grant",
            constraints={
                "project_workspace_read": "allowed",
                "project_workspace_write": "task_granted",
                "default_read_repository": "repo.base.project_workspace",
                "default_search_repository": "repo.base.project_workspace",
            },
        ),
        resource_space=ResourceSpace(
            workspace_policy="project_workspace",
            storage_namespace="development/sandbox",
            material_mount_policy="sandbox_material_mounts",
            project_file_policy="file_profile.base_workspace",
            managed_file_environment_policy="file_profile.base_workspace",
            browser_environment_policy="local_browser",
            artifact_root_policy="environment_scoped_artifacts",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("project_architecture_notes", "prior_runtime_findings"),
            project_knowledge_refs=("project_docs",),
            retrieval_index_refs=("code_search_index",),
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=True,
            sandbox_mode="workspace_overlay",
            real_workspace_access="read_only_or_task_granted",
            write_scope_policy="sandbox_or_file_access_table",
            shell_execution_policy="sandboxed",
            browser_execution_policy="sandboxed",
            network_execution_policy="task_decided",
            side_effect_policy="sandbox_boundary",
        ),
        risk_policy=RiskPolicy(
            default_permission_mode="environment_boundary",
            approval_required_risk_levels=("real_workspace_write", "external_write"),
            auto_denied_risk_levels=("destructive_unbounded",),
        ),
        artifact_policy=ArtifactPolicy(
            artifact_root="environment_scoped_artifacts",
            publish_policy="verification_required",
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def creation_writing_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.creation.writing",
        title="创意写作",
        description="Creative work environment for writing projects, source material, drafts, and reviewable creative outputs.",
        group_id="environment_group.creation",
        environment_kind="creation",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.creation.writing.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.creation.writing.orientation.v1",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.writing_workspace.v1",
                prompt_kind="boundary_rule",
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="managed_files",
            workspace_access="managed_writing_files",
            write_policy="draft_artifacts_allowed",
            shell_policy="denied",
            browser_policy="denied",
            network_policy="allowed",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.writing_manuscript",),
            required_repository_kinds=("official_work", "draft_workspace", "artifact_repository", "memory_repository"),
            canonical_write_policy="review_receipt_and_commit_gate_required",
            constraints={
                "official_work_open": "allowed",
                "official_work_canonical_write": "ask",
                "draft_write": "allowed",
                "artifact_projection_owner": "file_management",
                "memory_projection_owner": "file_management",
            },
        ),
        resource_space=ResourceSpace(
            storage_namespace="creation/writing",
            material_mount_policy="task_decided",
            managed_file_environment_policy="file_profile.writing_manuscript",
            artifact_root_policy="file_profile_projection",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("world_bible", "character_cards", "chapter_summaries"),
            project_knowledge_refs=("writing.project_knowledge",),
            retrieval_index_refs=("writing.memory_index",),
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="none",
            write_scope_policy="managed_writing_files_only",
            shell_execution_policy="denied",
            browser_execution_policy="denied",
            network_execution_policy="allowed",
        ),
        artifact_policy=ArtifactPolicy(
            artifact_root="repo.writing.artifact_repository",
            publish_policy="review_commit_required",
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def general_workspace_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.general.workspace",
        title="通用工作区",
        description="General-purpose work environment for broad tasks and mixed workflows.",
        group_id="environment_group.general",
        environment_kind="general",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.general.workspace.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.general.workspace.orientation.v1",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.general_workspace.v1",
                prompt_kind="boundary_rule",
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="task_decided",
            workspace_access="task_decided",
            write_policy="task_decided",
            shell_policy="task_decided",
            browser_policy="task_decided",
            network_policy="task_decided",
            side_effect_policy="permission_context",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.general_workspace",),
            required_repository_kinds=("conversation_artifacts",),
            canonical_write_policy="task_decided",
        ),
        resource_space=ResourceSpace(
            workspace_policy="task_decided",
            storage_namespace="general/workspace",
            material_mount_policy="task_decided",
            project_file_policy="task_decided",
            managed_file_environment_policy="file_profile.general_workspace",
            artifact_root_policy="conversation_artifacts",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("conversation_context",),
            retrieval_index_refs=("conversation_index",),
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="task_decided",
            write_scope_policy="task_decided",
            shell_execution_policy="task_decided",
            browser_execution_policy="task_decided",
            network_execution_policy="task_decided",
            side_effect_policy="permission_context",
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)
