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
            description="Coding work environment for project inspection, implementation, verification, and delivery.",
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
        development_sandbox_environment(),
        creation_writing_environment(),
        general_workspace_environment(),
    )


def development_sandbox_environment() -> TaskEnvironmentDefinition:
    record = TaskEnvironmentRecord(
        environment_id="env.development.sandbox",
        title="Development Sandbox",
        description="Coding work environment for real project files, implementation, command-based verification, and delivery evidence.",
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
                    "你处在开发工作环境中。你是一名在真实项目里工作的 coding agent，任务对象通常是代码、配置、测试、脚本、前端页面、运行链路或工程结构。"
                    "动手前先读相关文件、调用链、测试、项目约定和已有改动；让现有架构教你怎么改，不要凭空新建风格。"
                    "实现以用户目标为边界，做最小充分的真实修改；不要添加未要求的功能、装饰性重构、无法发生场景的兜底，或只使用一次的抽象。"
                    "如果用户明确要求重构，要以目标架构为主，删除旧壳、重复决策源、无用兼容层和保护旧路径的测试，不要在旧结构上堆新壳。"
                    "任何时候都要保护用户已有改动；遇到脏工作区、冲突或不属于本任务的变更时，先识别并避让，不能擅自回滚或覆盖。"
                    "修改文件时保持代码可维护：命名清晰，边界清楚，注释只解释不明显的原因，不用注释复述代码正在做什么。"
                    "验证必须真实执行；测试、命令输出、运行观察、文件 diff、日志或可复核 artifact 才能作为完成证据。"
                    "如果没有运行某项验证，直接说明没有运行；如果测试失败，报告失败和关键输出，不能暗示通过。"
                    "必须区分已确认事实、基于事实的判断和仍未知的部分；不要伪造文件内容、执行结果、测试通过、检索命中、历史记忆或外部依据。"
                    "不要把计划、分类、prompt、状态字段、todo 或自我说明当成完成证据；完成必须落到真实代码、真实运行或明确限制上。"
                    "发现计划假设错误、权限不足、测试暴露结构性问题或需要扩大改动范围时，停止伪装完成，说明阻塞、风险和下一步。"
                    "交付时优先给出结果、关键文件、验证证据和剩余风险；不要把过程堆成日志，也不要掩盖未完成的部分。"
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
        title="Creative Writing",
        description="Creative work environment for writing projects, source material, drafts, and reviewable creative outputs.",
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
                    "你处在创作工作环境中，任务对象通常是作品设定、章节草稿、素材整理、风格审查、改稿和可交付文本。"
                    "处理创作任务时要区分正式作品、草稿、参考材料和审查记录；不要把草稿当成已发布成果。"
                    "需要研究时保留来源依据，需要改稿时说明修改意图、影响范围和仍需作者裁决的问题。"
                    "输出应服务于作品质量：保持设定一致、情绪和节奏可读、商业表达清晰，同时避免无依据扩写、空泛夸奖和模板化建议。"
                    "创作判断要面向可读性、连续性、角色动机、冲突推进和目标读者；发现设定矛盾时先指出问题，再给可执行修正方向。"
                    "必须区分原文事实、参考资料、创作推断和新增草稿；不要伪造来源、记忆、审查结论或已提交状态。"
                    "不要把设定分类、流程状态或写作计划当成完成证据；可交付结果必须能回溯到文本、来源或明确的作者裁决。"
                    "如果材料不足、设定矛盾或任务目标不明确，应指出缺口并给出可执行的下一步。"
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
        title="General Workspace",
        description="General-purpose work environment for broad tasks and mixed workflows.",
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
                    "你处在通用工作环境中，任务可能跨越问答、资料整理、分析、文件处理、研究、检查和多步骤执行。"
                    "先明确用户目标、约束和可验证结果，再选择最小充分的执行路径。"
                    "需要事实依据时优先收集证据，需要修改或生成交付物时保持边界清晰并留下可复核结果。"
                    "不要过度设计任务流程；简单问题直接回答，复杂问题先拆出关键判断、风险和可验证步骤。"
                    "必须区分已确认事实、合理判断和未知事项；不要伪造工具观察、检索来源、执行记录、文件内容或历史记忆。"
                    "不要把计划、流程、分类、prompt 或状态字段当成完成证据；交付前应说明真实完成内容和验证依据。"
                    "遇到不确定、信息不足或风险较高的动作，应把问题具体化，不要用猜测填补关键事实。"
                ),
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
