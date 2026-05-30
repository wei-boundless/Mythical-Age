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
            group_id="environment_group.development",
            title="Development",
            description="Project workspace resource boundaries with sandbox overlay, verification channels, and artifact publication constraints.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.creation",
            title="Creation",
            description="Creative work resource boundaries with official work, draft space, memory repositories, artifacts, and review gates.",
        ),
        TaskEnvironmentGroup(
            group_id="environment_group.general",
            title="General",
            description="General resource boundaries for conversation materials, external evidence, document materials, lightweight artifacts, and constrained channels.",
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
        description="Project workspace boundary with read access to real project materials, sandbox overlay writes, verification channels, and artifact publication.",
        group_id="environment_group.development",
        environment_kind="development",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.development.sandbox.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.development.sandbox.v1",
                content=(
                    "你处在开发沙盒资源边界中。这个环境把真实项目工作区作为主要读取来源，"
                    "把任务写入、命令验证、浏览器验证和交付物发布约束在 sandbox overlay 与任务授权范围内。"
                    "你只能使用 runtime packet 中实际装配给你的工具；环境本身不授予工具，只声明资源边界和运行约束。"
                    "所有写入、命令和浏览器动作都必须服务于当前任务目标，失败结果必须作为真实观察处理，不能伪报成功。"
                    "\n在这个环境中定位代码、文件或文本时，应优先使用 search_text、search_files、glob_paths、read_file、list_dir "
                    "等专用搜索和读取工具；只有在需要运行验证、执行脚本、批量处理或专用工具无法表达时，才使用 terminal。"
                    "不要反复读取整文件来代替搜索；如果已经知道目标函数、错误消息或关键词，应先精确搜索，再读取必要片段。"
                    "\n处理 Python 开发任务时，如果 runtime packet 提供了 python_symbol_search、python_code_outline 或 python_parse_check，"
                    "你应把它们作为代码理解和语法验证的优先工具。已知符号名但不知道文件时，先用 python_symbol_search 定位定义或引用；"
                    "已知文件但不了解结构时，先用 python_code_outline 查看类、函数和行号；修改 Python 文件后，优先用 python_parse_check 做语法检查，"
                    "再运行更重的测试。AST 工具只用于只读代码智能，不能替代 edit_file、write_file 或测试命令。"
                    "不要在文件没有变化、假设没有变化时重复调用同一个 outline 或 symbol search；一旦已经定位到具体缺陷并具备写权限，应进入最小范围编辑和验证。"
                    "\n如果一次查找跨越多个文件、模块关系或历史上下文，并且 runtime packet 装配了可委派子 agent，"
                    "可以委派搜索或代码理解型子 agent；主 agent 仍负责最终判断、编辑和验收。"
                    "\n当 edit_file 返回 old_text not found、write_file 被拒绝、命令语法错误或路径不存在时，"
                    "下一步必须基于失败观察修正方法：先读取目标局部的当前真实文本或重新确认路径，"
                    "再用当前事实做最小范围编辑。不要在同一个失败原因没有被修正前重复执行昂贵工具或转向无关探索。"
                    "\n当前环境使用 sandbox overlay：你看到和修改的是任务沙盒工作副本；真实项目通常作为只读来源被材料化进沙盒。"
                    "不要因为沙盒中某个目录暂时不可见就断定真实项目缺失；应使用搜索/读取工具或检查已材料化的合同目录确认。"
                    "写入默认进入沙盒或环境 artifact/storage 范围；真实工作区写入只有在任务合同或权限上下文明确授权时才允许。"
                    "最终交付必须引用真实可验证的 artifact 路径，并通过读取、搜索、测试、浏览器或自审完成验证。"
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
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def development_readonly_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.development.readonly",
        title="Development Readonly",
        description="Read-only project workspace boundary for inspection, search, review, and planning without workspace side effects.",
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
                    "你处在开发只读资源边界中。这个环境允许围绕项目工作区、git/worktree 视图和相关材料做读取、搜索、审查和方案评估。"
                    "约束是不能写入项目、不能执行 shell、不能控制浏览器；实际可用工具仍以 runtime packet 为准。"
                    "检查 Python 代码时，如果 runtime packet 提供 python_symbol_search、python_code_outline 或 python_parse_check，"
                    "应优先用它们定位符号、理解文件结构和确认语法，而不是反复读取整文件。"
                    "这些 AST 工具是只读代码智能工具；在只读边界内只能产出诊断、证据和修改建议，不能声称已经完成代码修改。"
                    "如果任务需要修改、运行命令或生成正式 artifact，应请求进入具备相应资源边界的任务生命周期，而不是在只读边界内伪造执行。"
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
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def creation_writing_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.creation.writing",
        title="Creative Writing",
        description="Creative work boundary with official work, draft workspace, memory material, review receipts, and artifact repositories.",
        group_id="environment_group.creation",
        environment_kind="creation",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.creation.writing.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.creation.writing.v1",
                content=(
                    "你处在创作资源边界中。这个环境区分正式作品库、草稿工作区、创作 artifact、记忆材料和审查记录。"
                    "正式作品写入受 review receipt 和 commit gate 约束；草稿和任务 artifact 可以在环境允许范围内生成。"
                    "环境不替你选择写作工具或技能；实际可用能力由 agent 配置和 runtime packet 装配。"
                    "如果需要改动正式作品，应明确产出审查依据和提交意图，不能把草稿写入冒充正式发布。"
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
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def research_web_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.research.web",
        title="Web Research",
        description="General evidence boundary with network access, evidence archive, download cache, and citation snapshot repositories.",
        group_id="environment_group.general",
        environment_kind="general",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.research.web.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.research.web.v1",
                content=(
                    "你处在通用环境下的网络证据资源边界中。这个环境提供外部来源访问边界、证据归档、引用快照和下载缓存。"
                    "网络通道可以按任务需要使用，但写入应落在 evidence archive、download cache 或 citation snapshot repository。"
                    "环境不直接授予搜索或浏览器工具；实际可用工具由 agent 配置和 runtime packet 决定。"
                    "研究结论必须能回溯到证据记录，不能把未保存来源或不可复核内容当作已归档事实。"
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
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def document_processing_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.document.processing",
        title="Document Processing",
        description="General document boundary with input document repositories, extraction workspace, and versioned document artifacts.",
        group_id="environment_group.general",
        environment_kind="general",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.document.processing.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.document.processing.v1",
                content=(
                    "你处在通用环境下的文档处理资源边界中。这个环境区分输入文档库、抽取工作区和生成文档 artifact。"
                    "写入只能落在文档 artifact 或抽取工作区允许范围内；不能改写原始文档库，除非任务合同和权限上下文明确授权。"
                    "环境不直接选择文档技能或工具；实际能力由 agent 装配。"
                    "处理结果需要保留来源路径、抽取依据和版本化输出，不能用未验证的中间内容替代最终 artifact。"
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
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)


def general_workspace_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.general.workspace",
        title="General Workspace",
        description="Read-mostly general boundary for conversation materials, lightweight context, and bounded artifacts.",
        group_id="environment_group.general",
        environment_kind="general",
    )
    spec = TaskEnvironmentSpec(
        spec_id="envspec.general.workspace.default",
        environment_id=record.environment_id,
        environment_prompts=(
            EnvironmentPrompt(
                prompt_id="environment.general.workspace.v1",
                content=(
                    "你处在通用资源边界中。这个环境适合对话材料、轻量只读上下文和 bounded artifacts。"
                    "默认约束是 read-mostly、artifact-only 写入、无 shell、无浏览器、无网络。"
                    "环境不授予工具；实际可用工具以 runtime packet 为准。"
                    "如果任务需要项目写入、正式作品库、外部网络、文档处理或沙盒执行，应由系统切换到相应资源边界或在任务合同中显式声明。"
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
    )
    return TaskEnvironmentDefinition(record=record, spec=spec)
