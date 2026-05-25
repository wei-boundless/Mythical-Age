from __future__ import annotations

from .models import (
    ArtifactPolicy,
    ExecutionPolicy,
    FileManagementBinding,
    MemorySpace,
    PromptSpace,
    ResourceSpace,
    RiskPolicy,
    RuntimePolicy,
    SkillSpace,
    TaskEnvironmentDefinition,
    TaskEnvironmentRecord,
    TaskEnvironmentSpec,
    ToolSpace,
)


def default_task_environments() -> tuple[TaskEnvironmentDefinition, ...]:
    return (
        writing_environment(),
        vibe_coding_environment(),
        web_research_environment(),
    )


def writing_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.writing",
        title="Writing",
        description="Managed writing environment for formal works, drafts, artifacts, and writing memory.",
        environment_kind="writing",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.writing.default",
        environment_id=record.environment_id,
        prompt_space=PromptSpace(
            allowed_prompt_libraries=("prompt_library.writing",),
            allowed_prompt_packs=(
                "worldbuilding_review",
                "character_design",
                "chapter_draft",
                "continuity_review",
                "commercial_popular_fiction_review",
            ),
            default_prompt_pack_refs=("writing.role_prompts.default",),
        ),
        skill_space=SkillSpace(
            allowed_skill_refs=("outline_planning", "chapter_writing", "consistency_review", "style_rewrite"),
            skill_pack_refs=("skill_pack.writing.longform",),
        ),
        tool_space=ToolSpace(
            allowed_operation_market=(
                "op.model_response",
                "op.read_file",
                "op.search_text",
                "op.write_file",
                "op.edit_file",
                "op.text_metric",
                "op.memory_read",
            ),
            denied_operation_refs=("op.shell", "op.browser_control", "op.python_repl"),
            allowed_tool_market=("read_file", "search_text", "write_file", "edit_file", "text_metric", "memory_search"),
            denied_tool_refs=("terminal", "browser_control", "python_repl"),
            browser_policy="denied",
            shell_policy="denied",
            network_policy="denied",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.writing_manuscript",),
            required_repository_kinds=(
                "official_work",
                "draft_workspace",
                "artifact_repository",
                "memory_repository",
            ),
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
            workspace_policy="none",
            material_mount_policy="task_decided",
            project_file_policy="none",
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
        risk_policy=RiskPolicy(
            default_permission_mode="deny_by_default",
            approval_required_risk_levels=("canonical_write", "official_work_commit", "rollback"),
            auto_denied_risk_levels=("shell", "external_write"),
            reviewer_required_operations=("official_work_commit", "formal_memory_commit"),
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


def vibe_coding_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.vibe_coding",
        title="Vibe Coding",
        description="Managed coding environment for project workspace, sandbox overlay, git view, and test artifacts.",
        environment_kind="vibe_coding",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.vibe_coding.default",
        environment_id=record.environment_id,
        prompt_space=PromptSpace(
            allowed_prompt_libraries=("prompt_library.coding",),
            allowed_prompt_packs=("codebase_recon", "bug_fix", "refactor", "frontend_design", "test_verification", "code_review"),
            default_prompt_pack_refs=("coding.role_prompts.default",),
        ),
        skill_space=SkillSpace(
            allowed_skill_refs=("codebase_search", "frontend_design", "code_review", "playwright"),
            skill_pack_refs=("skill_pack.vibe_coding.default",),
        ),
        tool_space=ToolSpace(
            allowed_operation_market=(
                "op.model_response",
                "op.read_file",
                "op.search_files",
                "op.search_text",
                "op.list_dir",
                "op.stat_path",
                "op.path_exists",
                "op.glob_paths",
                "op.read_structured_file",
                "op.git_status",
                "op.git_diff",
                "op.git_log",
                "op.git_show",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.browser_control",
            ),
            allowed_tool_market=(
                "read_file",
                "search_files",
                "search_text",
                "list_dir",
                "stat_path",
                "path_exists",
                "glob_paths",
                "read_structured_file",
                "git_status",
                "git_diff",
                "git_log",
                "git_show",
                "write_file",
                "edit_file",
                "terminal",
                "browser_control",
            ),
            browser_policy="ask",
            shell_policy="ask",
            network_policy="task_decided",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.vibe_coding_project",),
            required_repository_kinds=("project_workspace", "sandbox_workspace", "git_worktree_view", "test_artifacts"),
            canonical_write_policy="real_workspace_write_requires_task_grant",
            constraints={
                "project_workspace_read": "allowed",
                "project_workspace_write": "ask",
                "sandbox_workspace_write": "allowed",
                "git_worktree_view": "read_only",
            },
        ),
        resource_space=ResourceSpace(
            workspace_policy="project_workspace",
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
            sandbox_required="task_decided",
            sandbox_mode="workspace_overlay",
            real_workspace_access="read_only_or_task_granted",
            write_scope_policy="file_access_table",
            shell_execution_policy="ask",
            browser_execution_policy="ask",
            network_execution_policy="task_decided",
        ),
        risk_policy=RiskPolicy(
            default_permission_mode="deny_by_default",
            approval_required_risk_levels=("shell", "real_workspace_write", "browser_external_write"),
            auto_denied_risk_levels=("destructive_unbounded",),
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


def web_research_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.web_research",
        title="Web Research",
        description="Managed web research environment for evidence capture and citation snapshots.",
        environment_kind="web_research",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.web_research.default",
        environment_id=record.environment_id,
        prompt_space=PromptSpace(
            allowed_prompt_libraries=("prompt_library.web_research",),
            allowed_prompt_packs=("query_planning", "source_verification", "evidence_synthesis"),
            default_prompt_pack_refs=("web_research.role_prompts.default",),
        ),
        tool_space=ToolSpace(
            allowed_operation_market=("op.model_response", "op.web_search", "op.fetch_url", "op.browser_control"),
            allowed_tool_market=("web_search", "fetch_url", "browser_control"),
            browser_policy="ask",
            shell_policy="denied",
            network_policy="allowed",
        ),
        file_management=FileManagementBinding(
            file_profile_refs=("file_profile.web_research_evidence",),
            required_repository_kinds=("evidence_archive", "download_cache", "citation_snapshot_repository"),
            canonical_write_policy="evidence_snapshot_versioned",
        ),
        resource_space=ResourceSpace(
            workspace_policy="none",
            material_mount_policy="download_cache",
            project_file_policy="none",
            managed_file_environment_policy="file_profile.web_research_evidence",
            browser_environment_policy="local_browser",
            artifact_root_policy="evidence_archive",
        ),
        execution_policy=ExecutionPolicy(
            sandbox_required=False,
            real_workspace_access="none",
            write_scope_policy="evidence_archive_only",
            shell_execution_policy="denied",
            browser_execution_policy="ask",
            network_execution_policy="allowed",
        ),
        risk_policy=RiskPolicy(
            default_permission_mode="deny_by_default",
            approval_required_risk_levels=("browser_form_submit", "external_write"),
            auto_denied_risk_levels=("shell", "local_workspace_write"),
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
