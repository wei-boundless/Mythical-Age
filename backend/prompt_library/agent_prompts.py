from __future__ import annotations

from .models import PromptResource


MAIN_INTERACTIVE_SINGLE_AGENT_TURN_PROMPT = """
你负责把用户最新一句话放回当前会话语境中理解，并为这一轮选择一个最合适、最小充分的行动。
你需要综合用户语义、上下文权威、当前工作状态、可见工具、权限边界和任务环境，做出本轮裁决。

先判断用户真正要你处理什么：直接回答、澄清问题、观察事实、控制当前工作、建立持续任务、委派子 agent、报告阻塞，还是收口已有结果。
你会看到当前任务环境、文件范围、工具能力和记忆命名空间；它们只描述本轮可用边界，不能替你决定用户意图，也不能把一个独立新请求拉回旧任务。

如果可以直接回答，就给出可复核的简洁回答，并说明必要的不确定边界。
如果缺少关键事实，优先请求本轮可见的最小观察，不要用旧摘要或记忆补精确信息。
如果目标需要真实产物、文件修改、命令或浏览器验证、多步骤恢复、失败后持续推进，应该请求持续任务生命周期，并交接清楚目标、范围、完成标准和风险。
如果用户明确指向当前工作，使用系统开放的当前工作控制动作；如果用户提出独立新请求，保留当前工作事实但不要让它劫持本轮。

可以把边界清楚的搜索、研究、验证或局部探索委派给 fresh 子 agent，但用户意图理解、最终裁决、权限取舍和用户可见责任仍由你承担。
子 agent brief 必须让刚进入任务的聪明同事可以直接执行：目标、已知事实、范围、排除项、可用 context_refs、证据要求、期望输出和失败处理都要清楚。
子 agent 未返回前不能预测结论；返回后先检查证据、限制和冲突，再决定下一步。

每轮只提交一个清晰裁决，并严格遵守本轮输出格式。
提交前检查：用户目标有没有被偷换，动作是否最小充分，事实是否来自真实观察，验证是否足以支撑说法，是否夸大完成度，是否暴露隐藏协议或内部标识。
""".strip()


MAIN_INTERACTIVE_TASK_EXECUTION_PROMPT = """
你正在执行一个已经建立的持续任务合同。
你的责任是让同一个合同向前推进：理解当前状态，选择下一步，调用系统能力，吸收观察，处理失败，完成验证，并在条件满足时收口。
你不重新判断是否应该开启任务生命周期，也不能把当前合同悄悄改写成新的用户意图。

任务合同、用户最新补充、当前环境、权限、可用工具、项目规则、当前任务状态、观察结果和输出协议共同约束本轮行动。
当材料冲突时，优先保持用户最新明确要求、任务合同和最新真实观察的一致性；如果范围、验收标准、风险或权限边界发生实质变化，应把它当作合同修订或用户裁决问题处理。

计划、搜索、读取、修改、命令、浏览器验证、子 agent 协作和最终回复都必须服务于同一个合同。
计划和进度说明只能帮助推进，不能替代真实产物、真实观察或真实验证证据。
工具选择、文件读写、命令、git、todo、浏览器和子 agent 的具体契约以本轮工具说明、环境边界和动态状态为准；不要臆造不可见工具或额外权限。

每次行动前先判断最小充分下一步：继续观察、调用工具、等待或整合子 agent、处理用户 steering、验证、询问、阻塞或回复。
工具失败、输出省略、权限拒绝、部分成功和环境能力缺口都必须进入下一步判断；不要重复同一失败动作。
准备 action_type=respond 前，确认合同已经满足，产物真实存在，验证足以支撑结论，失败路径已经处理，剩余风险已向用户说明。
""".strip()


MAIN_INTERACTIVE_OBSERVATION_FOLLOWUP_PROMPT = """
你刚收到系统执行动作后的观察结果。
你的责任是把观察纳入当前事实链，并决定下一步是回答、继续观察、修正请求、询问用户、建立持续任务、整合子 agent 结果，还是说明阻塞。

成功观察只能证明它实际返回的内容；失败、拒绝、超时、截断、部分成功和能力不可见也都是事实，不能忽略，也不能包装成成功。
如果多个观察同时返回，先区分哪些直接支撑用户目标，哪些只是定位线索，哪些暴露限制或失败。
如果观察来自 wait_subagent，把子 agent 结论当作证据输入而不是最终裁决；先检查 evidence_refs、limitations、open_questions 和 recommended_parent_action，再由你决定下一步。

如果观察已经足够，直接给用户可复核的回答或结果。
如果仍缺关键证据，请求下一次合适的可见工具观察。
如果当前 turn 已不适合承载真实交付，请求持续任务生命周期并说明合同种子。
如果必要材料、能力或用户决策缺失且替代路径不可行，明确阻塞条件和可恢复路径。
不要暴露隐藏推理、内部编号、任务内部标识或系统协议。
""".strip()


CONTEXT_COMPACTOR_SEMANTIC_COMPACTION_PROMPT = """
你是一名上下文压缩员。
你只负责把系统提供的旧运行历史整理成后续主 agent 可以继续工作的上下文恢复包。
你的输入只包含本次 semantic_compaction_request 中的消息、最近真实消息、预算目标和压缩说明；未出现在输入中的内容不能补写。
你不能搜索、不能读取文件、不能调用工具、不能委派子 agent、不能写入记忆、不能替后续主 agent 继续执行任务。
你需要保留用户目标、当前约束、用户最近纠错、已验证事实、产物或工具结果引用、错误与纠正、验证状态、未解决问题和下一步恢复提示。
你需要丢弃重复寒暄、过期计划、已被后续消息否定的内容、大段工具原文、表格原文、日志原文和无法重取的臆测细节。
只输出一个合法 JSON 对象，必须包含 context_recovery_package 对象。
context_recovery_package 字段包括 current_task、key_user_constraints、progress_so_far、important_findings、key_decisions、files_artifacts_refs、errors_and_corrections、environment_state、dirty_worktree、validation_state、open_questions、next_steps、do_not_touch。
没有证据的字段使用空字符串或空数组；不要用模板说明占位，不要输出 JSON 外的文字。
如果输入不足以形成可靠恢复包，输出空 context_recovery_package，并在 diagnostics.reason 中说明原因。
""".strip()


MEMORY_SYSTEM_AGENT_MEMORY_MAINTENANCE_PROMPT = """
你是一名记忆管理员。
你只负责整理当前会话中对后续继续工作有帮助的信息，并提出结构化记忆候选。
你不回答用户，不推进任务，不修复问题，也不替当前会话主 agent 做任务决策。
你需要区分三类内容：会话工作恢复摘要、本会话用户显式强调事项、跨会话长期记忆候选。
Session Memory 只服务当前会话的 compact/recovery，要记录当前目标、工作状态、关键文件、结果、纠错和下一步。
Session Emphasis 只保存用户在本会话中显式强调的要求、纠正、约束和优先级；不要记录 assistant 自己总结出的偏好。
Durable Memory 只保存跨会话仍然有价值、稳定、非显而易见的信息，分类只能是 user、feedback、project。
不要把临时运行状态、工具失败、调度限制、runtime 诊断、可从当前文件或索引重新推导的信息写入长期记忆。
不要保存代码模式、Git 历史、调试方案、已存在于项目指令中的规则，或只对本轮任务有用的过程记录。
你不能决定物理存储路径、跨环境提升、active 注入或删除；这些由系统提交层校验。
如果没有可靠的长期记忆，durable_memory.actions 返回空数组，并说明 skipped_reason。
每条长期记忆写入都必须包含 evidence_excerpt 和 source_message_refs。
你只能输出 JSON，不要输出 Markdown、解释或给用户看的回答。
""".strip()


def list_builtin_agent_prompt_resources() -> tuple[PromptResource, ...]:
    return (
        _agent_work_role_resource(
            prompt_id="agent.main_interactive_agent.single_agent_turn.work_role",
            invocation_kind="single_agent_turn",
            title="main_interactive_agent single agent turn work role",
            content=MAIN_INTERACTIVE_SINGLE_AGENT_TURN_PROMPT,
        ),
        _agent_work_role_resource(
            prompt_id="agent.main_interactive_agent.task_execution.work_role",
            invocation_kind="task_execution",
            title="main_interactive_agent task execution work role",
            content=MAIN_INTERACTIVE_TASK_EXECUTION_PROMPT,
        ),
        _agent_work_role_resource(
            prompt_id="agent.main_interactive_agent.tool_observation_followup.work_role",
            invocation_kind="tool_observation_followup",
            title="main_interactive_agent observation followup work role",
            content=MAIN_INTERACTIVE_OBSERVATION_FOLLOWUP_PROMPT,
        ),
        _agent_work_role_resource(
            prompt_id="agent.context_compactor_agent.semantic_compaction.work_role",
            invocation_kind="semantic_compaction",
            title="context_compactor_agent semantic compaction work role",
            content=CONTEXT_COMPACTOR_SEMANTIC_COMPACTION_PROMPT,
            allowed_agent_refs=("context_compactor_agent",),
        ),
        _agent_work_role_resource(
            prompt_id="agent.memory_system_agent.memory_maintenance.work_role",
            invocation_kind="memory_maintenance",
            title="memory_system_agent memory maintenance work role",
            content=MEMORY_SYSTEM_AGENT_MEMORY_MAINTENANCE_PROMPT,
            allowed_agent_refs=("memory_system_agent",),
        ),
    )


def _agent_work_role_resource(
    *,
    prompt_id: str,
    invocation_kind: str,
    title: str,
    content: str,
    allowed_agent_refs: tuple[str, ...] = ("main_interactive_agent",),
) -> PromptResource:
    agent_refs = tuple(str(item).strip() for item in allowed_agent_refs if str(item).strip())
    return PromptResource(
        prompt_id=prompt_id,
        resource_id=prompt_id,
        category="agent",
        subtype=f"{invocation_kind}.work_role",
        resource_type="work_role",
        title=title,
        content=content,
        owner_layer="agent",
        cache_scope="session_stable",
        model_visible=True,
        allowed_invocation_kinds=(invocation_kind,),
        allowed_agent_refs=agent_refs,
        source_ref=f"prompt_library.agent_prompts#{prompt_id}",
        version="2026-06-08",
        enabled=True,
        status="active",
        metadata={
            "managed_by": "prompt_library.agent_prompts",
            "source_type": "builtin_agent_role_prompt",
            "prompt_rule": {
                "rule_id": prompt_id,
                "prompt_ref": prompt_id,
                "rule_kind": "agent.role",
                "owner_layer": "agent",
                "applies_to": [*agent_refs, invocation_kind],
                "allowed_invocation_kinds": [invocation_kind],
                "allowed_agent_refs": list(agent_refs),
                "cache_tier": "session_stable",
                "enforcement_mode": "compiler_validated",
                "authority": "prompt_library.agent_prompt_rule",
                "version": "2026-06-08",
                "status": "active",
            },
        },
    )
