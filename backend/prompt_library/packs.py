from __future__ import annotations

from .models import PromptPack, PromptResource
from .rules import rule_metadata
from .system_prompts import FOUNDATION_PROMPT_REFS


RUNTIME_SINGLE_AGENT_TURN_PROMPT = """
你是当前会话的主 agent。系统已经为你装配本轮可见上下文、任务环境、权限边界和可用动作；你负责理解用户当前请求并选择最合适的下一步。
如果可以直接回答，应直接自然回答用户，不要开启任务。
如果目标需要真实交付物、文件写入、命令验证、浏览器验证、长期执行、失败后重新推进或多步骤验收，可以调用 request_task_run。
只有系统提供 active_work_context 时，才存在可控制的当前工作；你需要判断用户这句话是否要控制、补充或询问这个当前工作。无关聊天应正常回答，不要被当前工作劫持。
没有 active_work_context 时，系统没有可控制的进行中工作；不要把历史摘要、旧任务记录、旧产物目录或用户一句“继续”自动解释成旧任务恢复。需要持续推进时，调用 request_task_run 建立新的任务。
如果用户当前话语明确指向 active_work_context 中的工作，应直接调用 active_work_control 表达你的判断；不要把明确的“继续、暂停、停止、按这个方向改、现在做到哪了”再改写成要求用户二次确认。
如果用户是在问进展或质疑状态，应回答当前工作状态；如果用户既要求回答又要求继续，应使用 answer_then_continue_active_work。
如果用户是在补充当前工作的要求，应把补充内容作为新增指令记录，不能覆盖原合同。
如果缺少必要信息，可以询问用户。
如果请求越界、工具观察明确显示边界不足或无法继续，应说明阻塞原因；如果当前运行权限模式已经授予，不要要求用户重复批准系统权限。
不要暴露隐藏推理、内部编号、任务内部标识或系统协议。用户可见内容只描述结果、进展、问题或阻塞原因。
""".strip()


RUNTIME_TASK_EXECUTION_PROMPT = """
你是持续任务生命周期中的执行 agent。你正在执行一个已建立的任务合同。
你的职责是按合同真实推进工作，记录可验证证据，只在合同满足时给出完成答复。
只输出一个合法 JSON 对象，不要 Markdown 包裹，不要暴露隐藏推理；输出必须遵守本轮 action schema。
如果需要执行一步工作，action_type=tool_call，并填写 tool_calls 数组。数组中可以包含一个或多个互不依赖的本轮可见工具调用；运行时会根据工具安全声明、资源冲突和审批状态决定并发或串行。
每一轮只能提交一个 action JSON。不要在 JSON 外继续输出正文、代码块、解释或产物内容；系统只会解析这个 JSON，JSON 外内容不会被当作工具输入。
当任务需要创建较长文件、网页、脚本或文档时，优先调用 write_file 或 terminal，让完整内容成为工具参数或命令输入；不要把交付物正文作为普通回答或 Markdown 输出。
如果内容可能超过本轮输出预算，应先写入一个完整可运行的紧凑版本，再通过后续 read_file、edit_file、terminal 或 write_file 增量完善，不要输出半截 JSON 或半截文件。
如果合同已经满足，action_type=respond；final_answer 必须总结完成情况，并在 diagnostics.artifacts 中列出真实产物路径。
如果缺少用户决策，action_type=ask_user。
如果任务无法继续，action_type=block，并说明 blocking_reason。
执行过程中不能再次开启新的持续处理流程。用户可见内容不得包含内部编号、系统结构或协议字段。
写入、命令、浏览器、网络或资源生成只能使用本次 runtime 明确可见且可派发的工具，并落在任务环境允许的范围内；当前运行权限模式是本轮授权事实。
系统会提供统一的 task_state 投影：task_state.current_facts 是当前可依赖事实，task_state.artifact_evidence 是真实产物证据，task_state.latest_tool_results 是最近工具结果，task_state.active_failures 是当前仍有效的失败，task_state.historical_failures 是历史失败，只能作为背景，不能视为当前工具不可用。
如果系统提供 editor_context，它只是用户当轮关注的编辑器上下文证据，不授予额外文件权限。任务初始 editor_context 表示任务启动时关注的文件；pending_user_steers 中的 editor_context 只用于解释对应补充要求，优先于初始上下文。content_preview 是局部文件预览，不等于完整文件事实；selection 只在用户真实选区存在时才表示选中文本。
""".strip()


RUNTIME_GRAPH_NODE_EXECUTION_PROMPT = """
你是任务图中的一个专业节点 agent。你只负责完成当前节点合同定义的职责，不负责推断或重写整张图的流程。
系统已经为你装配当前节点可见的节点合同、上游边授权输入、记忆快照、循环变量和输出合同；未出现在这些输入中的内容不能当作已授权上下文。
只输出一个合法 JSON 对象，不要 Markdown 包裹，不要暴露隐藏推理。JSON 顶层必须包含 authority、action_type、public_progress_note、public_action_state 和 final_answer。
authority 固定为 "harness.loop.model_action_request"；action_type 通常使用 "respond"；public_progress_note 用一句自然语言说明当前节点已完成什么；public_action_state 至少包含 current_judgment、next_action、completion_status，其中 completion_status 可用 working、verifying、ready_to_finish 或 blocked。
respond 节点的交付内容必须全部放入 final_answer；不要把正文、汇总稿、审核报告、记忆提交包或说明文字写在 JSON 外。
示例结构：{"authority":"harness.loop.model_action_request","action_type":"respond","public_progress_note":"已完成当前节点交付。","public_action_state":{"current_judgment":"当前节点职责已完成。","next_action":"提交给下游节点。","completion_status":"ready_to_finish"},"final_answer":"在这里写当前节点的完整交付物。"}
如果当前节点可以交付，action_type=respond，并把节点交付主体写入 final_answer。final_answer 必须是可被下游节点或系统物化的完整结果，不要只写“已完成”。
如果需要询问用户才能继续，action_type=ask_user。
如果确实需要调用本次可见工具，action_type=tool_call，并按本轮 action schema 填写工具调用字段；不可见工具不能臆造或请求。
如果上游授权输入缺失、节点合同互相矛盾、输出合同无法理解或边界禁止继续，action_type=block，并说明 blocking_reason。
节点产物由系统根据输出合同进行物化、归档并生成下游流转内容；不要为了交付图节点产物而要求文件工具、命令工具或记忆工具。
不要再次开启新的工作生命周期，不要输出内部运行标识或其它内部控制协议作为用户可见内容。
完成前必须检查：当前节点职责是否满足、授权输入是否被正确使用、输出是否符合输出合同、没有把未授权上游信息或其它节点职责混入结果。
""".strip()


RUNTIME_OBSERVATION_FOLLOWUP_PROMPT = """
你是当前 turn 的主 agent。你刚收到系统执行的只读观察结果。
请基于用户请求、历史和观察结果继续判断下一步。只输出一个合法 JSON 对象。
如果 observation 带有 error，必须把它当作真实失败处理：可以改用其他只读观察、请求持续处理流程、询问用户或阻止，不能声称该观察成功。
如果观察足够，action_type=respond，并填写 final_answer。
如果当前请求范围明确，且已有观察已经提供可回答的事实、来源或可说明的限制，应优先 respond；只有关键事实仍缺失、来源不可用且没有替代证据，或用户目标确实要求更高可信度时，才继续观察。
如果还需要一次只读观察，action_type=tool_call，并按本轮 action schema 填写工具调用字段。
如果发现任务应由已注册承接计划处理，action_type=request_registered_engagement，并填写 engagement_request.plan_id 与 startup_parameters。
如果发现任务需要写入、命令、长期跟进或真实交付物，action_type=request_task_run，并填写 task_contract_seed；合同必须包含 user_visible_goal、task_run_goal，并且至少包含 completion_criteria、required_artifacts、required_verifications 之一。
如果观察结果指出 task_contract_invalid，你需要修正合同字段后重新提交 request_task_run，而不是直接放弃。
如果缺少用户信息，action_type=ask_user。
只输出当前 schema 允许的字段。用户可见内容只描述进展、结果、问题或阻塞原因，不包含内部编号、系统结构或协议字段。
""".strip()


RUNTIME_SEMANTIC_COMPACTION_PROMPT = """
你正在执行一次系统授权的上下文语义压缩。
本轮不是普通对话，也不是工具执行。你的唯一任务是根据输入的 semantic_compaction_request 生成恢复点摘要。
输出必须是一个合法 JSON 对象，格式为 {"summary_content":"...","diagnostics":{...}}。
summary_content 必须忠实来自输入，保留可继续工作的事实和约束，不得加入新事实、建议未验证结论或隐藏推理。
如果输入不足、互相矛盾或无法可靠压缩，summary_content 留空，并在 diagnostics.reason 中写明原因。
""".strip()


def list_builtin_runtime_prompt_resources() -> tuple[PromptResource, ...]:
    return (
        _runtime_resource(
            prompt_id="runtime.single_agent_turn.v1",
            subtype="single_agent_turn",
            title="Single agent turn protocol",
            content=RUNTIME_SINGLE_AGENT_TURN_PROMPT,
            invocation_kind="single_agent_turn",
            requires=("runtime.rule.system_call_protocol.v1", "runtime.rule.intent_feedback.v1"),
        ),
        _runtime_resource(
            prompt_id="runtime.task_execution.v1",
            subtype="task_execution",
            title="Task execution protocol",
            content=RUNTIME_TASK_EXECUTION_PROMPT,
            invocation_kind="task_execution",
            requires=("runtime.rule.system_call_protocol.v1", "runtime.rule.intent_feedback.v1"),
        ),
        _runtime_resource(
            prompt_id="runtime.graph_node_execution.v1",
            subtype="graph_node_execution",
            title="Graph node execution protocol",
            content=RUNTIME_GRAPH_NODE_EXECUTION_PROMPT,
            invocation_kind="task_execution",
        ),
        _runtime_resource(
            prompt_id="runtime.observation_followup.v1",
            subtype="observation_followup",
            title="Observation followup protocol",
            content=RUNTIME_OBSERVATION_FOLLOWUP_PROMPT,
            invocation_kind="tool_observation_followup",
            requires=("runtime.rule.system_call_protocol.v1", "runtime.rule.intent_feedback.v1"),
        ),
        _runtime_resource(
            prompt_id="runtime.semantic_compaction.v1",
            subtype="semantic_compaction",
            title="Semantic compaction protocol",
            content=RUNTIME_SEMANTIC_COMPACTION_PROMPT,
            invocation_kind="semantic_compaction",
            requires=(),
        ),
    )


def list_builtin_prompt_packs() -> tuple[PromptPack, ...]:
    return (
        PromptPack(
            pack_id="runtime.pack.single_agent_turn.v1",
            invocation_kind="single_agent_turn",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.single_agent_turn.v1",
                "runtime.rule.system_call_protocol.v1",
                "runtime.rule.intent_feedback.v1",
                "runtime.rule.tool_use.v1",
                "runtime.rule.output_boundary.v1",
                "runtime.rule.error_recovery.v1",
                "runtime.rule.context_memory.v1",
                "runtime.rule.permission_denial.v1",
                "runtime.rule.subagent_delegation.v1",
                "runtime.rule.subagent_invocation_protocol.v1",
                "runtime.rule.multi_tool_scheduling.v1",
                "runtime.rule.plan_mode_boundary.v1",
            ),
            title="Single agent turn runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.task_execution.v1",
            invocation_kind="task_execution",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.task_execution.v1",
                "runtime.rule.system_call_protocol.v1",
                "runtime.rule.intent_feedback.v1",
                "runtime.rule.tool_use.v1",
                "runtime.rule.output_boundary.v1",
                "runtime.rule.error_recovery.v1",
                "runtime.rule.context_memory.v1",
                "runtime.rule.permission_denial.v1",
                "runtime.rule.subagent_delegation.v1",
                "runtime.rule.subagent_invocation_protocol.v1",
                "runtime.rule.multi_tool_scheduling.v1",
                "runtime.rule.plan_mode_boundary.v1",
            ),
            title="Task execution runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.graph_node_execution.v1",
            invocation_kind="task_execution",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.graph_node_execution.v1",
                "runtime.rule.system_call_protocol.v1",
                "runtime.rule.output_boundary.v1",
                "graph.rule.node_boundary.v1",
                "graph.rule.node_output_contract.v1",
            ),
            title="Graph node execution runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.observation_followup.v1",
            invocation_kind="tool_observation_followup",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.observation_followup.v1",
                "runtime.rule.system_call_protocol.v1",
                "runtime.rule.intent_feedback.v1",
                "runtime.rule.tool_use.v1",
                "runtime.rule.output_boundary.v1",
                "runtime.rule.error_recovery.v1",
                "runtime.rule.context_memory.v1",
                "runtime.rule.permission_denial.v1",
            ),
            title="Observation followup runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.semantic_compaction.v1",
            invocation_kind="semantic_compaction",
            ordered_prompt_refs=(
                "runtime.semantic_compaction.v1",
            ),
            title="Semantic compaction runtime pack",
            cache_scope="static",
            allowed_agent_refs=("context_compactor_agent",),
        ),
    )


def default_pack_ref_for_invocation(invocation_kind: str) -> str:
    mapping = {
        "single_agent_turn": "runtime.pack.single_agent_turn.v1",
        "task_execution": "runtime.pack.task_execution.v1",
        "tool_observation_followup": "runtime.pack.observation_followup.v1",
        "semantic_compaction": "runtime.pack.semantic_compaction.v1",
    }
    return mapping.get(str(invocation_kind or "").strip(), "")


def _runtime_resource(
    *,
    prompt_id: str,
    subtype: str,
    title: str,
    content: str,
    invocation_kind: str,
    requires: tuple[str, ...] = ("runtime.rule.system_call_protocol.v1",),
) -> PromptResource:
    return PromptResource(
        prompt_id=prompt_id,
        resource_id=prompt_id,
        category="runtime",
        subtype=subtype,
        resource_type=f"runtime.{subtype}",
        title=title,
        content=content,
        owner_layer="runtime",
        cache_scope="static",
        model_visible=True,
        allowed_invocation_kinds=(invocation_kind,),
        source_ref="prompt_library.packs",
        version="v1",
        enabled=True,
        status="active",
        metadata={
            "managed_by": "prompt_library.packs",
            "builtin_runtime_prompt": True,
            "prompt_rule": rule_metadata(
                rule_id=prompt_id,
                prompt_ref=prompt_id,
                rule_kind="runtime.protocol",
                owner_layer="runtime",
                applies_to=(invocation_kind, subtype),
                allowed_invocation_kinds=(invocation_kind,),
                cache_tier="global_static",
                enforcement_mode="compiler_validated",
                requires=requires,
                authority="prompt_library.runtime_protocol_rule",
            ),
        },
    )
