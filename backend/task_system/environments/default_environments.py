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
            group_id="environment_group.office",
            title="Office",
            description="Office document processing environments with Word, Excel, PowerPoint, PDF, local search, source lookup, artifact creation, and verification resources.",
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
                "op.workspace_write",
                "op.workspace_edit",
                "op.shell",
                "op.shell",
                "op.browser_control",
                "op.image_generate",
                "op.git_write",
                "op.git_write",
                "op.git_write",
                "op.git_write",
                "op.git_write",
                "op.git_remote",
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
            default_permission_mode="agent_profile_only",
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


def office_file_search_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.office.file_search",
        title="办公文档处理环境",
        description="Office environment for Word, Excel, PowerPoint, PDF reading, extraction, creation, editing, conversion, verification, local search, and source lookup without shell, browser automation, git, code execution, or image generation.",
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
            side_effect_operations=("op.workspace_write", "op.workspace_edit", "op.office_document"),
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.base_workspace", "file_profile.document_processing"),
            required_repository_kinds=("project_workspace", "material_mount", "sandbox_workspace", "artifact_repository"),
            canonical_write_policy="task_decided",
            constraints={
                "project_workspace_read": "allowed",
                "project_workspace_search": "allowed",
                "project_workspace_write": "task_granted",
                "source_document_read": "allowed",
                "source_document_search": "allowed",
                "source_document_write": "denied",
                "extraction_workspace_read": "allowed",
                "extraction_workspace_search": "allowed",
                "extraction_workspace_write": "allowed",
                "extraction_workspace_edit": "allowed",
                "document_artifact_read": "allowed",
                "document_artifact_search": "allowed",
                "document_artifact_write": "allowed",
                "document_artifact_edit": "allowed",
                "default_read_repository": "repo.document.document_repository",
                "default_search_repository": "repo.document.document_repository",
                "default_write_repository": "repo.document.artifact_repository",
                "default_edit_repository": "repo.document.extraction_workspace",
                "default_artifact_repository": "repo.document.artifact_repository",
                "workspace_reference_repository": "repo.base.project_workspace",
                "office_runtime_operation": "op.office_document",
            },
        ),
        resource_space=ResourceSpace(
            workspace_policy="project_workspace",
            storage_namespace="office/document-processing",
            material_mount_policy="document_processing_source_mounts",
            project_file_policy="file_profile.base_workspace",
            managed_file_environment_policy="file_profile.document_processing",
            external_service_policy="source_lookup_allowed",
            browser_environment_policy="none",
            mcp_environment_policy="local_document_processing_resources",
            artifact_root_policy="document_processing_artifacts",
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
            default_permission_mode="agent_profile_only",
            approval_required_risk_levels=("real_workspace_write", "external_write"),
            auto_denied_risk_levels=("destructive_unbounded",),
        ),
        artifact_policy=ArtifactPolicy(
            artifact_root="document_processing_artifacts",
            publish_policy="verification_required",
        ),
        lifecycle_policy={
            "office_task_environment": True,
            "environment_resource_model": "document_processing",
            "office_document_runtime_required_for_write": True,
        },
        metadata={
            "dedicated_task_environment": "office_document_processing",
            "environment_resource_authority": "task_system.task_environment",
            "file_management_scope": "document_processing_resources",
            "bound_capability_resources": [
                "document_processing_kernel",
                "office_document_runtime",
                "pdf_analysis",
                "structured_data_analysis",
                "rag_projection",
            ],
            "tool_package_refs": ["pkg.office.document", "pkg.mcp.local"],
            "operation_refs": [
                "op.office_document",
                "op.mcp_pdf",
                "op.mcp_retrieval",
                "op.mcp_structured_data",
            ],
            "mcp_resource_refs": [
                "local_mcp:office_document",
                "local_mcp:pdf",
                "local_mcp:structured_data",
                "local_mcp:retrieval",
            ],
            "resource_prompt_refs": [
                "environment.resource.base_workspace.orientation",
                "environment.resource.document_processing.orientation",
                "environment.office.file_search.orientation",
            ],
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
            "task_lifecycle_prompts": "disabled",
        },
        metadata={
            "conversation_mode": "role_atmosphere",
            "default_task_execution": "disabled",
        },
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)
