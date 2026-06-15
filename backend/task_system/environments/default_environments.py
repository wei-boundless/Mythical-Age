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


_LIFECYCLE_PROMPT_SLOTS = (
    "context_intake",
    "request_judgment",
    "work_relation",
    "environment_capability_alignment",
    "plan_gate",
    "action_selection",
    "active_work_control",
    "task_run_handoff",
    "user_steer_contract_revision",
    "tool_dispatch",
    "tool_observation_recovery",
    "subagent_delegation",
    "subagent_result_integration",
    "verification_gate",
    "memory_read_context",
    "memory_write_handoff",
    "compaction_handoff",
    "finalization",
)


def _lifecycle_prompt_defaults(environment_prompt_prefix: str) -> dict[str, str]:
    return {
        slot: f"environment.{environment_prompt_prefix}.lifecycle.{slot}"
        for slot in _LIFECYCLE_PROMPT_SLOTS
    }


def default_task_environment_groups() -> tuple[TaskEnvironmentGroup, ...]:
    return (
        TaskEnvironmentGroup(
            group_id="environment_group.coding",
            title="Coding",
            description="Dedicated coding task environments with project file state, sandbox execution, git visibility, and verification artifacts.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.office",
            title="Office",
            description="Lightweight office environment for file handling, local search, and source-backed information lookup without development execution tools.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.general",
            title="General",
            description="General-purpose work environment for broad tasks that should not narrow the agent profile.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.chat",
            title="Chat",
            description="Pure conversation environments for role atmosphere, relationship continuity, and natural dialogue without task execution tooling.",
        ),
    )


def default_task_environments() -> tuple[TaskEnvironmentDefinition, ...]:
    return (
        coding_vibe_workspace_environment(),
        office_file_search_environment(),
        general_workspace_environment(),
        chat_role_conversation_environment(),
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
                prompt_id="environment.coding.vibe_workspace.orientation",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.coding_workspace",
                prompt_kind="boundary_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.core_work_protocol",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.codebase_inspection",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.large_scope_exploration",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.editing",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.verification",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.debug_discipline",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.git_safety",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.windows_shell",
                prompt_kind="coding_rule",
            ),
            EnvironmentPrompt(
                prompt_id="coding.rule.task_progress",
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
            required_repository_kinds=(
                "project_workspace",
                "sandbox_workspace",
                "artifact_repository",
                "git_worktree_view",
                "test_artifacts",
            ),
            canonical_write_policy="sandbox_write_real_workspace_requires_task_grant",
            constraints={
                "project_workspace_read": "allowed",
                "project_workspace_search": "allowed",
                "project_workspace_write": "task_granted",
                "project_workspace_edit": "task_granted",
                "sandbox_workspace_read": "allowed",
                "sandbox_workspace_search": "allowed",
                "sandbox_workspace_write": "allowed",
                "sandbox_workspace_edit": "allowed",
                "artifact_repository_read": "allowed",
                "artifact_repository_search": "allowed",
                "artifact_repository_write": "allowed",
                "artifact_repository_edit": "allowed",
                "git_worktree_view": "read_only",
                "default_read_repository": "repo.managed_project.sandbox_workspace",
                "default_search_repository": "repo.managed_project.sandbox_workspace",
                "default_write_repository": "repo.managed_project.sandbox_workspace",
                "default_edit_repository": "repo.managed_project.sandbox_workspace",
                "default_artifact_repository": "repo.managed_project.artifacts",
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
            "lifecycle_prompt_defaults": _lifecycle_prompt_defaults("coding"),
        },
        metadata={
            "dedicated_task_environment": "coding",
            "managed_project_workspace_profile": "file_profile.managed_project_workspace",
            "file_management_scope": "generic_runtime_authority",
        },
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def office_file_search_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.office.file_search",
        title="轻量办公文件检索",
        description="Lightweight office environment for file reading, file artifact handling, local search, and web/source lookup without shell, browser automation, git, code execution, or image generation.",
        group_id="environment_group.office",
        environment_kind="office",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.office.file_search.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.office.file_search.orientation",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.office_file_search",
                prompt_kind="boundary_rule",
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="managed_files",
            workspace_access="project_read_task_write",
            write_policy="task_decided",
            shell_policy="denied",
            browser_policy="denied",
            network_policy="allowed",
            side_effect_policy="permission_context",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.base_workspace",),
            required_repository_kinds=("project_workspace", "conversation_artifacts"),
            canonical_write_policy="task_decided",
            constraints={
                "project_workspace_read": "allowed",
                "project_workspace_search": "allowed",
                "project_workspace_write": "task_granted",
                "artifact_write": "allowed",
                "default_read_repository": "repo.base.project_workspace",
                "default_search_repository": "repo.base.project_workspace",
                "default_artifact_repository": "repo.office.artifacts",
            },
        ),
        resource_space=ResourceSpace(
            workspace_policy="project_workspace",
            storage_namespace="office/file-search",
            material_mount_policy="task_decided",
            project_file_policy="file_profile.base_workspace",
            managed_file_environment_policy="file_profile.base_workspace",
            browser_environment_policy="none",
            artifact_root_policy="conversation_artifacts",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("conversation_context",),
            retrieval_index_refs=("conversation_index",),
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="read_only_or_task_granted",
            write_scope_policy="task_decided",
            shell_execution_policy="denied",
            browser_execution_policy="denied",
            network_execution_policy="allowed",
            side_effect_policy="permission_context",
        ),
        risk_policy=RiskPolicy(
            default_permission_mode="environment_boundary",
            approval_required_risk_levels=("real_workspace_write", "external_write"),
            auto_denied_risk_levels=("destructive_unbounded",),
        ),
        artifact_policy=ArtifactPolicy(
            artifact_root="conversation_artifacts",
            publish_policy="task_evidence_required",
        ),
        lifecycle_policy={
            "office_task_environment": True,
            "lifecycle_prompt_defaults": _lifecycle_prompt_defaults("office"),
        },
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
                prompt_id="environment.general.workspace.orientation",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.general_workspace",
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
        lifecycle_policy={
            "general_task_environment": True,
            "lifecycle_prompt_defaults": _lifecycle_prompt_defaults("general"),
        },
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def chat_role_conversation_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.chat.role_conversation",
        title="角色氛围聊天",
        description="Pure chat environment for role atmosphere, relationship continuity, personality prompts, and natural conversation without task execution workflows.",
        group_id="environment_group.chat",
        environment_kind="chat",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.chat.role_conversation.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.chat.role_conversation.orientation",
            ),
            EnvironmentPrompt(
                prompt_id="environment.rule.chat_role_conversation",
                prompt_kind="boundary_rule",
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="none",
            workspace_access="none",
            write_policy="denied",
            shell_policy="denied",
            browser_policy="denied",
            network_policy="denied",
            side_effect_policy="conversation_boundary",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=(),
            required_repository_kinds=(),
            canonical_write_policy="denied",
            constraints={
                "project_workspace_read": "denied",
                "project_workspace_search": "denied",
                "project_workspace_write": "denied",
                "artifact_write": "denied",
            },
        ),
        resource_space=ResourceSpace(
            workspace_policy="none",
            storage_namespace="chat/role-conversation",
            material_mount_policy="none",
            project_file_policy="none",
            managed_file_environment_policy="none",
            browser_environment_policy="none",
            artifact_root_policy="none",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("conversation_context", "role_relationship_memory"),
            retrieval_index_refs=(),
            read_policy="conversation_projection",
            write_policy="role_memory_policy",
            projection_policy="conversation_boundary",
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            sandbox_mode="none",
            real_workspace_access="none",
            write_scope_policy="denied",
            shell_execution_policy="denied",
            browser_execution_policy="denied",
            network_execution_policy="denied",
            side_effect_policy="conversation_boundary",
        ),
        risk_policy=RiskPolicy(
            default_permission_mode="deny_by_default",
            approval_required_risk_levels=(),
            auto_denied_risk_levels=("tool_execution", "file_write", "external_write", "destructive_unbounded"),
        ),
        artifact_policy=ArtifactPolicy(
            artifact_root="none",
            publish_policy="conversation_only",
        ),
        lifecycle_policy={
            "chat_conversation_environment": True,
            "request_task_run": False,
            "active_work_control": False,
            "subagent_delegation": False,
            "task_lifecycle_prompts": "disabled",
        },
        metadata={
            "conversation_mode": "role_atmosphere",
            "default_task_execution": "disabled",
        },
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)
