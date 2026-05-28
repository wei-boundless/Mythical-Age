from __future__ import annotations

from .models import (
    ArtifactPolicy,
    EnvironmentPrompt,
    ExecutionPolicy,
    FileManagementBinding,
    MemorySpace,
    ResourceSpace,
    RiskPolicy,
    RuntimePolicy,
    SandboxPolicy,
    TaskEnvironmentDefinition,
    TaskEnvironmentGroup,
    TaskEnvironmentRecord,
    TaskEnvironmentSpec,
)


def default_task_environment_groups() -> tuple[TaskEnvironmentGroup, ...]:
    return (
        TaskEnvironmentGroup(
            group_id="environment_group.development",
            title="Development",
            description="Coding and software delivery platforms with workspace, sandbox, verification, and artifact boundaries.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.creation",
            title="Creation",
            description="Writing and creative production platforms with artifact, draft, continuity, and review boundaries.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.research",
            title="Research",
            description="Evidence and web research platforms with source capture, citation, and external resource boundaries.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.document",
            title="Document",
            description="Document processing platforms for extraction, review, transformation, and generated document artifacts.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.general",
            title="General",
            description="Read-mostly general workspace platforms for lightweight tasks and conversation artifacts.",
        ),
    )


def default_task_environments() -> tuple[TaskEnvironmentDefinition, ...]:
    return (
        development_sandbox_environment(),
        development_readonly_environment(),
        creation_writing_environment(),
        research_web_environment(),
        document_processing_environment(),
        general_workspace_environment(),
    )


def development_sandbox_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.development.sandbox",
        title="Development Sandbox",
        description="Sandboxed coding environment for project inspection, edits, command verification, browser checks, and task artifacts.",
        group_id="environment_group.development",
        environment_kind="development",
        metadata={"legacy_aliases": ["env.vibe_coding"]},
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.development.sandbox.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.development.sandbox.v1",
                content=(
                    "你处在开发沙盒环境中。这个环境提供项目工作区、沙盒写入边界、命令验证边界、"
                    "浏览器验证边界和交付物记录边界。你只能使用 runtime packet 中实际装配给你的工具；"
                    "环境本身不授予工具，只说明当前执行场地和资源尺度。所有写入、命令和浏览器动作都必须服务于当前任务目标，"
                    "失败结果必须作为真实观察处理，不能伪报成功。"
                ),
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
            side_effect_operations=("op.write_file", "op.edit_file", "op.shell", "op.browser_control", "op.image_generate"),
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.vibe_coding_project",),
            required_repository_kinds=("project_workspace", "sandbox_workspace", "git_worktree_view", "test_artifacts"),
            canonical_write_policy="sandbox_write_real_workspace_requires_task_grant",
            constraints={
                "project_workspace_read": "allowed",
                "project_workspace_write": "task_granted",
                "sandbox_workspace_write": "allowed",
                "git_worktree_view": "read_only",
            },
        ),
        resource_space=ResourceSpace(
            workspace_policy="project_workspace",
            storage_namespace="development/sandbox",
            material_mount_policy="sandbox_material_mounts",
            project_file_policy="file_profile.vibe_coding_project",
            managed_file_environment_policy="file_profile.vibe_coding_project",
            browser_environment_policy="local_browser",
            artifact_root_policy="runtime_output",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("project_architecture_notes", "prior_runtime_findings"),
            project_knowledge_refs=("AGENTS.md", "project_docs"),
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
            artifact_root="runtime_output",
            publish_policy="verification_required",
        ),
        runtime_policy=RuntimePolicy(
            allowed_runtime_lanes=("single_agent", "task_graph"),
            preferred_runtime_lanes=("single_agent",),
            graph_allowed=True,
            delegation_allowed=True,
            human_gate_allowed=True,
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def development_readonly_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.development.readonly",
        title="Development Readonly",
        description="Read-only coding environment for codebase inspection, review, and planning without workspace side effects.",
        group_id="environment_group.development",
        environment_kind="development",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.development.readonly.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.development.readonly.v1",
                content=(
                    "你处在开发只读环境中。这个环境用于代码审查、结构理解、方案评估和只读验证。"
                    "环境不提供写入或命令权限；实际可用工具仍以 runtime packet 为准。"
                ),
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="none",
            workspace_access="project_read_only",
            write_policy="none",
            shell_policy="denied",
            browser_policy="denied",
            network_policy="task_decided",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.vibe_coding_project",),
            required_repository_kinds=("project_workspace", "git_worktree_view"),
            canonical_write_policy="none",
            constraints={"project_workspace_read": "allowed", "project_workspace_write": "denied"},
        ),
        resource_space=ResourceSpace(
            workspace_policy="project_workspace",
            storage_namespace="development/readonly",
            project_file_policy="read_only",
            managed_file_environment_policy="file_profile.vibe_coding_project",
            artifact_root_policy="conversation_artifacts",
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="read_only",
            write_scope_policy="none",
            shell_execution_policy="denied",
            browser_execution_policy="denied",
            network_execution_policy="task_decided",
        ),
        runtime_policy=RuntimePolicy(
            allowed_runtime_lanes=("single_agent",),
            preferred_runtime_lanes=("single_agent",),
            graph_allowed=False,
            delegation_allowed=True,
            human_gate_allowed=True,
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def creation_writing_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.creation.writing",
        title="Creative Writing",
        description="Creative writing platform for drafts, formal artifacts, continuity material, and review boundaries.",
        group_id="environment_group.creation",
        environment_kind="writing",
        metadata={"legacy_aliases": ["env.writing"]},
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.creation.writing.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.creation.writing.v1",
                content=(
                    "你处在创作环境中。这个环境提供草稿、正式作品、记忆材料、连续性审查和创作产物边界。"
                    "环境不替你选择写作工具或技能；实际可用能力由 agent 配置和 runtime packet 装配。"
                ),
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="managed_files",
            workspace_access="managed_writing_files",
            write_policy="draft_artifacts_allowed",
            shell_policy="denied",
            browser_policy="denied",
            network_policy="denied",
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
            network_execution_policy="denied",
        ),
        artifact_policy=ArtifactPolicy(
            artifact_root="repo.writing.artifact_repository",
            publish_policy="review_commit_required",
        ),
        runtime_policy=RuntimePolicy(
            allowed_runtime_lanes=("single_agent", "task_graph"),
            preferred_runtime_lanes=("task_graph",),
            graph_allowed=True,
            delegation_allowed=True,
            human_gate_allowed=True,
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def research_web_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.research.web",
        title="Web Research",
        description="Research platform for external evidence capture, citation snapshots, and network-bound materials.",
        group_id="environment_group.research",
        environment_kind="web_research",
        metadata={"legacy_aliases": ["env.web_research"]},
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.research.web.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.research.web.v1",
                content=(
                    "你处在网络研究环境中。这个环境提供外部来源访问、证据快照、引用记录和下载缓存边界。"
                    "环境不直接授予搜索或浏览器工具；实际可用工具由 agent 配置和 runtime packet 决定。"
                ),
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="evidence_archive",
            workspace_access="none",
            write_policy="evidence_archive_only",
            shell_policy="denied",
            browser_policy="task_decided",
            network_policy="allowed",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.web_research_evidence",),
            required_repository_kinds=("evidence_archive", "download_cache", "citation_snapshot_repository"),
            canonical_write_policy="evidence_snapshot_versioned",
        ),
        resource_space=ResourceSpace(
            storage_namespace="research/web",
            material_mount_policy="download_cache",
            managed_file_environment_policy="file_profile.web_research_evidence",
            browser_environment_policy="local_browser",
            artifact_root_policy="evidence_archive",
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="none",
            write_scope_policy="evidence_archive_only",
            shell_execution_policy="denied",
            browser_execution_policy="task_decided",
            network_execution_policy="allowed",
        ),
        runtime_policy=RuntimePolicy(
            allowed_runtime_lanes=("single_agent", "task_graph"),
            preferred_runtime_lanes=("single_agent",),
            graph_allowed=True,
            delegation_allowed=False,
            human_gate_allowed=True,
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def document_processing_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.document.processing",
        title="Document Processing",
        description="Document platform for extraction, OCR, generated review artifacts, and versioned outputs.",
        group_id="environment_group.document",
        environment_kind="document_processing",
        metadata={"legacy_aliases": ["env.document_processing"]},
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.document.processing.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.document.processing.v1",
                content=(
                    "你处在文档处理环境中。这个环境提供文档材料、抽取工作区、生成文档产物和版本化边界。"
                    "环境不直接选择文档技能或工具；实际能力由 agent 装配。"
                ),
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="document_workspace",
            workspace_access="document_workspace",
            write_policy="document_artifacts_only",
            shell_policy="denied",
            browser_policy="denied",
            network_policy="denied",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.document_processing",),
            required_repository_kinds=("document_repository", "extraction_workspace", "artifact_repository"),
            canonical_write_policy="versioned_document_artifacts",
        ),
        resource_space=ResourceSpace(
            workspace_policy="document_workspace",
            storage_namespace="document/processing",
            material_mount_policy="document_mounts",
            managed_file_environment_policy="file_profile.document_processing",
            artifact_root_policy="document_artifact_repository",
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="none",
            write_scope_policy="document_artifacts_only",
            shell_execution_policy="denied",
            browser_execution_policy="denied",
            network_execution_policy="denied",
        ),
        runtime_policy=RuntimePolicy(
            allowed_runtime_lanes=("single_agent", "task_graph"),
            preferred_runtime_lanes=("single_agent",),
            graph_allowed=True,
            delegation_allowed=False,
            human_gate_allowed=True,
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def general_workspace_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.general.workspace",
        title="General Workspace",
        description="Read-mostly general environment for lightweight work, conversation artifacts, and bounded context.",
        group_id="environment_group.general",
        environment_kind="general_workspace",
        metadata={"legacy_aliases": ["env.general_workspace"]},
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.general.workspace.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.general.workspace.v1",
                content=(
                    "你处在通用工作区环境中。这个环境适合轻量任务、只读上下文和对话产物。"
                    "环境不授予工具；实际可用工具以 runtime packet 为准。"
                ),
            ),
        ),
        sandbox_policy=SandboxPolicy(
            enabled=False,
            sandbox_mode="none",
            workspace_access="read_mostly",
            write_policy="artifact_only",
            shell_policy="denied",
            browser_policy="denied",
            network_policy="denied",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.general_workspace",),
            required_repository_kinds=("conversation_artifacts",),
            canonical_write_policy="read_mostly",
        ),
        resource_space=ResourceSpace(
            workspace_policy="read_mostly",
            storage_namespace="general/workspace",
            material_mount_policy="task_decided",
            project_file_policy="read_only",
            managed_file_environment_policy="file_profile.general_workspace",
            artifact_root_policy="conversation_artifacts",
        ),
        memory_space=MemorySpace(
            environment_memory_refs=("conversation_context",),
            retrieval_index_refs=("conversation_index",),
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="read_only",
            write_scope_policy="artifact_only",
            shell_execution_policy="denied",
            browser_execution_policy="denied",
            network_execution_policy="denied",
        ),
        runtime_policy=RuntimePolicy(
            allowed_runtime_lanes=("single_agent",),
            preferred_runtime_lanes=("single_agent",),
            graph_allowed=False,
            delegation_allowed=False,
            human_gate_allowed=True,
        ),
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)
