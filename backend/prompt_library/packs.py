from __future__ import annotations

from .models import PromptPack, PromptResource
from .rules import rule_metadata
from .system_prompts import FOUNDATION_PROMPT_REFS


RUNTIME_SINGLE_AGENT_TURN_PROMPT = """
你负责本轮会话的行动裁决。你会同时看到身份风格、工作角色、生命周期提示、当前环境、权限边界、可见工具和输出协议。
先理解用户最新话语，再选择一个最小充分动作；不要把回答、工具请求、任务开启和当前工作控制混成多个裁决。

合法动作、字段和 JSON 形态由本轮 output_contract 与 system call protocol 定义；本层只负责判断语义上应该做什么。
常见语义裁决包括 respond、ask_user、tool_call、request_task_run、active_work_control 和 block；active_work_control 是你请求系统调整当前工作的动作，不是对用户的最终答复。
需要工具时，只能请求本轮可见且可派发的工具。工具由系统执行；你提出请求、等待观察，并在观察返回后重新判断。

用户可见内容必须和真实动作一致。不要预测工具结果、伪造完成、暴露隐藏推理、内部编号、任务内部标识或协议字段。
""".strip()


RUNTIME_TASK_EXECUTION_PROMPT = """
你正在持续任务生命周期中执行一个已建立的任务合同。
你会看到任务合同、观察、工具、环境边界、动态状态和输出协议；在持续任务中，只推进当前合同的下一步。

输出格式、动作字段和工具调用形态由本轮 action schema 与 system call protocol 定义；不要在协议外补第二个动作。
如果本轮协议使用 action_type 字段，它表示你本轮选择的语义动作；只选择一个能推进任务合同的 action_type。
需要执行工作时，请求本轮可见且可派发的工具；系统会根据工具安全声明、资源冲突和审批状态决定并发或串行。
当任务需要创建较长文件、网页、脚本或文档时，优先调用 write_file 或 terminal，让完整内容成为工具参数或命令输入；不要把交付物正文作为普通回答或 Markdown 输出。
如果内容可能超过本轮输出预算，应先写入一个完整可运行的紧凑版本，再通过后续 read_file、edit_file、terminal 或 write_file 增量完善，不要输出半截 JSON 或半截文件。

合同满足时收口；缺少用户决策时询问；必要材料、权限或替代路径都不足时阻塞。
执行过程中不能再次开启新的持续处理流程。用户可见内容不得包含内部编号、系统结构或协议字段。
写入、命令、浏览器、网络或资源生成只能使用本轮明确可见且可派发的工具，并落在任务环境允许的范围内；当前运行权限模式是本轮授权事实。
task_state、editor_context、pending_user_steers 和 observation payload 只提供事实和边界，不能替你声明未验证的完成。
""".strip()


RUNTIME_GRAPH_NODE_EXECUTION_PROMPT = """
你是当前工作流中被委派的专业执行者。你的具体身份、质量标准和交付边界由当前节点合同决定。
你只负责完成当前节点合同定义的职责，不负责推断或重写整张图的流程。
你会看到当前节点可见的节点合同、上游边授权输入、记忆快照、循环变量和输出合同；未出现在这些输入中的内容不能当作已授权上下文。
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
你刚收到一次系统执行后的观察结果。观察是事实输入，不是给用户的最终回复。
你会同时看到观察内容、当前环境、权限边界、工作角色、生命周期提示和本轮输出协议；基于这些事实重新判断下一步动作。
输出格式和允许动作由本轮 output_contract 与 system call protocol 定义；本层只负责判断观察之后应该继续、收口、询问、控制当前工作还是阻塞。
如果观察显示用户正在 steering 当前工作，使用 active_work_control 语义裁决；系统会执行控制动作并把结果作为下一次观察交还给你。
如果 steering 内容明确是暂停、先停一下、停止、取消当前任务或不用继续做，必须选择对应的暂停或停止控制动作；不要把它们写成追加要求。
观察足以回答时使用 respond；仍缺少关键证据或来源时，可以请求下一次可见工具观察；用户明确控制当前工作时使用 active_work_control；需要写入、命令、长期跟进或真实交付物时，使用 request_task_run。
如果观察结果指出 task_contract_invalid，需要修正合同字段后重新提交 request_task_run。
用户可见内容只描述进展、结果、问题或阻塞原因，不包含内部编号、系统结构或协议字段。
""".strip()


RUNTIME_SEMANTIC_COMPACTION_PROMPT = """
你正在执行一次系统授权的上下文语义压缩。
本轮不是普通对话，也不是工具执行。你的唯一任务是根据输入的 semantic_compaction_request 生成 context_recovery_package。
输出必须是一个合法 JSON 对象，格式为 {"context_recovery_package":{...},"diagnostics":{...}}。
context_recovery_package 必须忠实来自输入，保留后续主 agent 可继续工作的事实、约束、产物引用、纠错、验证状态和下一步，不得加入新事实、建议未验证结论或隐藏推理。
如果输入不足、互相矛盾或无法可靠压缩，context_recovery_package 使用空字段，并在 diagnostics.reason 中写明原因。
""".strip()


def list_builtin_runtime_prompt_resources() -> tuple[PromptResource, ...]:
    return (
        _runtime_resource(
            prompt_id="runtime.single_agent_turn",
            subtype="single_agent_turn",
            title="Single agent turn protocol",
            content=RUNTIME_SINGLE_AGENT_TURN_PROMPT,
            invocation_kind="single_agent_turn",
            requires=("runtime.rule.system_call_protocol", "runtime.rule.turn_decision_alignment"),
        ),
        _runtime_resource(
            prompt_id="runtime.task_execution",
            subtype="task_execution",
            title="Task execution protocol",
            content=RUNTIME_TASK_EXECUTION_PROMPT,
            invocation_kind="task_execution",
            requires=("runtime.rule.system_call_protocol", "runtime.rule.turn_decision_alignment"),
        ),
        _runtime_resource(
            prompt_id="runtime.graph_node_execution",
            subtype="graph_node_execution",
            title="Graph node execution protocol",
            content=RUNTIME_GRAPH_NODE_EXECUTION_PROMPT,
            invocation_kind="task_execution",
        ),
        _runtime_resource(
            prompt_id="runtime.observation_followup",
            subtype="observation_followup",
            title="Observation followup protocol",
            content=RUNTIME_OBSERVATION_FOLLOWUP_PROMPT,
            invocation_kind="tool_observation_followup",
            requires=("runtime.rule.system_call_protocol", "runtime.rule.turn_decision_alignment"),
        ),
        _runtime_resource(
            prompt_id="runtime.semantic_compaction",
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
            pack_id="runtime.pack.single_agent_turn",
            invocation_kind="single_agent_turn",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.single_agent_turn",
                "runtime.rule.system_call_protocol",
                "runtime.rule.turn_decision_alignment",
                "runtime.rule.tool_use",
                "runtime.rule.output_boundary",
                "runtime.rule.error_recovery",
                "runtime.rule.context_memory",
                "runtime.rule.permission_denial",
                "runtime.rule.multi_tool_scheduling",
            ),
            title="Single agent turn runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.task_execution",
            invocation_kind="task_execution",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.task_execution",
                "runtime.rule.system_call_protocol",
                "runtime.rule.turn_decision_alignment",
                "runtime.rule.tool_use",
                "runtime.rule.output_boundary",
                "runtime.rule.error_recovery",
                "runtime.rule.context_memory",
                "runtime.rule.permission_denial",
                "runtime.rule.multi_tool_scheduling",
            ),
            title="Task execution runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.graph_node_execution",
            invocation_kind="task_execution",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.graph_node_execution",
                "runtime.rule.system_call_protocol",
                "runtime.rule.output_boundary",
                "graph.rule.node_boundary",
                "graph.rule.node_output_contract",
            ),
            title="Graph node execution runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.observation_followup",
            invocation_kind="tool_observation_followup",
            ordered_prompt_refs=(
                *FOUNDATION_PROMPT_REFS,
                "runtime.observation_followup",
                "runtime.rule.system_call_protocol",
                "runtime.rule.turn_decision_alignment",
                "runtime.rule.tool_use",
                "runtime.rule.output_boundary",
                "runtime.rule.error_recovery",
                "runtime.rule.context_memory",
                "runtime.rule.permission_denial",
            ),
            title="Observation followup runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.semantic_compaction",
            invocation_kind="semantic_compaction",
            ordered_prompt_refs=(
                "runtime.semantic_compaction",
            ),
            title="Semantic compaction runtime pack",
            cache_scope="static",
            allowed_agent_refs=("context_compactor_agent",),
        ),
    )


def default_pack_ref_for_invocation(invocation_kind: str) -> str:
    mapping = {
        "single_agent_turn": "runtime.pack.single_agent_turn",
        "task_execution": "runtime.pack.task_execution",
        "tool_observation_followup": "runtime.pack.observation_followup",
        "semantic_compaction": "runtime.pack.semantic_compaction",
    }
    return mapping.get(str(invocation_kind or "").strip(), "")


def _runtime_resource(
    *,
    prompt_id: str,
    subtype: str,
    title: str,
    content: str,
    invocation_kind: str,
    requires: tuple[str, ...] = ("runtime.rule.system_call_protocol",),
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
        version="2026-06-08",
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
                version="2026-06-08",
            ),
        },
    )
