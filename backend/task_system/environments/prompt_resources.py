from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnvironmentPromptResourceSpec:
    prompt_id: str
    environment_id: str
    title: str
    content: str
    subtype: str = "orientation"
    version: str = "2026-06-08"
    cache_scope: str = "static_environment"


MANAGED_PROJECT_WORKSPACE_RESOURCE_ORIENTATION = """
受管项目工作区是通用文件管理资源，负责项目文件、沙盒覆盖层、git 视图、材料挂载和验证产物的路径、权限、读写状态与证据。
项目工作区是 coding 任务的主要工作面；需要实现、修改、重构或验证项目时，应在项目相对路径中操作相关源码、配置、测试和资源文件。artifact 目录是交付证据和发布面，不是项目工作区的替代品，也不是 coding 修改的唯一允许位置。
开始行动前应先定位相关文件、调用链和验证入口；不要只凭文件名、记忆、todo 或旧观察判断当前文件事实。
读取、搜索、写入和编辑后的状态应以工具返回的文件状态为准。文件管理不拥有某个任务类型的循环控制；具体编码、写作或验证策略由任务环境和 agent 决策负责。
如果项目工作区已有用户改动，应把它们视为用户资产。除非用户明确要求，不能回滚、覆盖或清理不属于本任务的变更。
""".strip()


BASE_WORKSPACE_RESOURCE_ORIENTATION = """
当前环境包含通用项目工作区资源。项目工作区可以用于读取代码、配置、文档和测试入口，但它本身不声明专属 coding 工作流；真实写入能力以本轮 runtime 权限模式、可见工具和工具观察为准。
需要修改或验证时，应以当前任务环境、已授予权限和工具返回的文件状态为准；不要用文件名猜测、旧观察或 todo 代替真实文件事实，也不要在当前运行权限已经授予时要求用户重复授权。
如果项目工作区已有用户改动，应把它们视为用户资产。除非用户明确要求，不能回滚、覆盖或清理不属于本任务的变更。
""".strip()


SANDBOX_OVERLAY_RESOURCE_ORIENTATION = """
当前环境包含沙盒工作资源。沙盒用于降低实现和验证风险，它描述写入位置和证据范围，不能替代完成证据；实际能否执行写入由本轮 runtime 权限模式、可见工具和工具观察共同给出。
你需要区分项目真实文件、沙盒写入、测试产物和运行日志。写入必须落在当前 runtime 明确允许的范围；验证必须基于真实命令、测试、运行观察或可复核 artifact；如果权限已经授予但工具不可见，应报告环境或能力投影不匹配，而不是要求用户再次批准。
如果沙盒边界、路径映射、依赖、端口或进程状态不清楚，先检查环境状态，再行动。不要反复执行同一组失败参数。
""".strip()


WRITING_MANUSCRIPT_RESOURCE_ORIENTATION = """
当前环境包含写作稿件资源。正式稿、草稿、素材、审查记录、作者裁决和创作记忆必须分开理解；不要把草稿或建议当成已确认正稿。
修改或生成文本时，应保留可回溯的上下文：原文依据、修改意图、影响范围、仍需作者确认的问题和引用来源。
""".strip()


GENERAL_WORKSPACE_RESOURCE_ORIENTATION = """
当前环境包含通用工作区资源。通用工作区可以承载文件、会话 artifact、资料整理和混合任务，但它不自动说明任务目标或完成标准。
行动前先确认用户真正需要的结果、可用材料和风险；需要证据时收集证据，需要交付物时留下可复核产物。
""".strip()


DEVELOPMENT_SANDBOX_ORIENTATION = """
你处在通用开发沙盒任务环境中。这个任务环境是当前开发工作的外层容器；你需要先理解它提供的工作空间、文件边界、沙盒语义、artifact、验证方式和当前项目上下文，再决定下一步行动。
开始修改前，先定位相关代码、调用链、配置、测试入口和已有改动。让现有架构教你怎么改；不要凭空新建风格，不要做装饰性重构，不要引入只服务一次的抽象。
如果用户要求重构，应以目标架构为主，清理旧壳、重复决策源、无用兼容层和保护旧路径的测试；不要用兼容兜底把旧链路继续留在主路径里。
发现预期能力不可见、写入边界不允许或验证条件缺失时，应说明环境不匹配、能力投影缺口或需要用户决策；如果本轮权限模式已经授予，不要把问题说成还需要用户批准系统权限。
交付时说明真实完成内容、关键文件、验证证据和剩余风险。没有运行的验证必须明确说没有运行；测试失败或环境受限时不能暗示成功。
""".strip()


CODING_VIBE_WORKSPACE_ORIENTATION = """
你处在专用 coding 工作区任务环境中。你的职责是理解真实项目文件、规划必要改动、执行受控文件操作、运行真实验证，并用可复核证据收口。
这个环境的主要工作对象是项目工作区。实现代码、样式、配置、测试和资源时，写入项目相对路径；只有最终交付物、验证报告、截图、演示页或明确要求的产物才写入 artifact_root。
你需要以工具返回的文件状态为准：已读取的路径、行窗口、搜索命中、写入事件和 stale 状态都是下一步行动的事实依据。不要反复读取同一文件窗口；文件被写入或编辑后，需要把旧读取内容视为可能过期，再按需要重新读取。
开始编码前，先找到相关调用链、测试入口和已有工作区改动。修改时保持范围清晰，通用文件管理能力只负责路径、权限、读写状态和证据，不把某个任务类型的循环控制写进工具或文件状态里。
如果需要子任务、验证或产物，请让每一步留下工具结果、文件状态或 artifact 证据。遇到能力不可见、沙盒、端口、依赖或测试阻塞时，应说明具体阻塞和下一步修复路径；如果运行权限已授予，不要在聊天中要求用户重复批准权限。
显式人工审批由 runtime/UI 控制面处理；不要在聊天中要求用户批准系统权限，也不要把审批等待当作普通工具失败反复重试。
""".strip()


CREATION_WRITING_ORIENTATION = """
你处在创作写作任务环境中。这个任务环境是当前创作工作的外层容器；你需要先分清正式作品、草稿、参考材料、作者裁决、设定资料、审查记录和 artifact，再处理文本或提出判断。
当前工作的主要依据是用户指定的作品材料、世界观资料、角色卡、章节草稿、历史摘要、作者明确裁决、检索来源和系统提供的创作记忆。不要把旧记忆、草稿计划或自己的推断当成已确认设定。
正式作品与草稿必须分开处理。可以生成草稿、修订建议、审查结论和整理材料，但不能把未获作者确认的新增内容当成已提交正稿。
需要研究或引用资料时，保留来源依据并区分外部事实、参考观点和创作推断。不要伪造来源、读者反馈、市场结论、作者意图或已经发生的提交状态。
创作判断应服务作品质量：设定一致性、人物动机、冲突推进、节奏、情绪连续性、可读性和目标读者接受度。发现矛盾时先指出问题，再给可执行修正方向。
改稿时说明修改意图、影响范围和仍需作者裁决的问题。不要用模板化建议、空泛夸奖或无依据扩写替代真实编辑判断。
环境中的 artifact、草稿和审查记录是可回溯材料，不等同于正式发布结果。完成必须落到可读文本、审查结论、明确来源或作者裁决上。
""".strip()


GENERAL_WORKSPACE_ORIENTATION = """
你处在通用工作任务环境中。这个任务环境是当前工作的外层容器；任务可能跨越问答、资料整理、分析、文件处理、研究、检查和多步骤执行。
先确认用户目标、可用上下文、风险和可验证结果，再选择最小充分的执行路径。简单问题直接回答；复杂问题先拆出关键事实、限制和验证步骤。
当前工作的依据可能来自用户消息、会话上下文、指定文件、系统状态、检索来源、工具观察和 artifact。必须区分已确认事实、合理判断和未知事项。
需要事实依据时先收集证据；需要修改或生成交付物时保持边界清晰，留下可复核结果。不要把计划、流程、分类、prompt、todo 或状态字段当成完成证据。
如果环境中预期上下文、能力、文件或外部来源不可见，应具体说明缺口和下一步，不要用猜测补关键事实。
""".strip()


def default_environment_prompt_resource_specs() -> tuple[EnvironmentPromptResourceSpec, ...]:
    return (
        EnvironmentPromptResourceSpec(
            prompt_id="environment.resource.base_workspace.orientation",
            environment_id="resource.file_profile.base_workspace",
            title="通用项目工作区资源",
            content=BASE_WORKSPACE_RESOURCE_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.resource.managed_project_workspace.orientation",
            environment_id="resource.file_profile.managed_project_workspace",
            title="受管项目工作区资源",
            content=MANAGED_PROJECT_WORKSPACE_RESOURCE_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.resource.sandbox_overlay.orientation",
            environment_id="resource.sandbox.workspace_overlay",
            title="沙盒工作资源",
            content=SANDBOX_OVERLAY_RESOURCE_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.resource.writing_manuscript.orientation",
            environment_id="resource.file_profile.writing_manuscript",
            title="写作稿件资源",
            content=WRITING_MANUSCRIPT_RESOURCE_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.resource.general_workspace.orientation",
            environment_id="resource.file_profile.general_workspace",
            title="通用工作区资源",
            content=GENERAL_WORKSPACE_RESOURCE_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.coding.vibe_workspace.orientation",
            environment_id="env.coding.vibe_workspace",
            title="专用 coding 工作区任务环境",
            content=CODING_VIBE_WORKSPACE_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.development.sandbox.orientation",
            environment_id="env.development.sandbox",
            title="开发沙盒任务环境",
            content=DEVELOPMENT_SANDBOX_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.creation.writing.orientation",
            environment_id="env.creation.writing",
            title="创作写作任务环境",
            content=CREATION_WRITING_ORIENTATION,
        ),
        EnvironmentPromptResourceSpec(
            prompt_id="environment.general.workspace.orientation",
            environment_id="env.general.workspace",
            title="通用工作任务环境",
            content=GENERAL_WORKSPACE_ORIENTATION,
        ),
    )


def environment_resource_prompt_refs(spec: object) -> tuple[str, ...]:
    refs: list[str] = []
    file_management = getattr(spec, "file_management", None)
    sandbox_policy = getattr(spec, "sandbox_policy", None)
    for profile_ref in tuple(getattr(file_management, "file_profile_refs", ()) or ()):
        refs.append("runtime.rule.file_management.generic")
        if profile_ref == "file_profile.base_workspace":
            refs.append("environment.resource.base_workspace.orientation")
        elif profile_ref == "file_profile.managed_project_workspace":
            refs.append("environment.resource.managed_project_workspace.orientation")
        elif profile_ref == "file_profile.writing_manuscript":
            refs.append("environment.resource.writing_manuscript.orientation")
        elif profile_ref == "file_profile.general_workspace":
            refs.append("environment.resource.general_workspace.orientation")
    if str(getattr(sandbox_policy, "sandbox_mode", "") or "") == "workspace_overlay":
        refs.append("environment.resource.sandbox_overlay.orientation")
    return _dedupe(refs)


def _dedupe(refs: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        value = str(ref or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)
