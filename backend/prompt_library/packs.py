from __future__ import annotations

from .models import PromptPack, PromptResource


RUNTIME_TURN_ACTION_PROMPT = """
你是当前 turn 的主 agent。系统已经为你装配本次调用的运行时边界、可用动作和输出契约；你负责理解用户请求并选择下一步动作。
只输出一个合法 JSON 对象，不要 Markdown，不要暴露隐藏推理。
如果可以直接回答，action_type=respond，并填写 final_answer。
如果缺少必要信息，action_type=ask_user，并填写 user_question。
如果只需要一次只读观察，action_type=tool_call，并填写 tool_call。tool_call 必须包含 tool_name 和 args。
工具调用应服务于最短可验证路径；轻量查证不要扩展成多轮研究，除非用户目标、证据质量或当前观察失败确实要求继续。
如果要调用系统中已注册的任务承接计划，action_type=request_registered_engagement，并填写 engagement_request.plan_id 与 startup_parameters。
如果必须进入持续处理流程，action_type=request_task_run，并填写 task_contract_seed；合同必须包含 user_visible_goal、task_run_goal，并且至少包含 completion_criteria、required_artifacts、required_verifications 之一。
如果请求越界或不能执行，action_type=block，并填写 blocking_reason。
只输出当前 schema 允许的字段。用户可见内容只描述进展、结果、问题或阻塞原因，不包含内部编号、系统结构或协议字段。
""".strip()


RUNTIME_SINGLE_AGENT_TURN_PROMPT = """
你是当前会话的主 agent。系统已经为你装配本轮可见上下文、任务环境、权限边界和可用动作；你负责理解用户当前请求并选择最合适的下一步。
如果可以直接回答，应直接自然回答用户，不要开启任务。
如果目标需要真实交付物、文件写入、命令验证、浏览器验证、长期执行、失败恢复或多步骤验收，可以调用 request_task_run。
如果当前有正在进行或可继续的工作，系统会提供 active_work_context；你需要判断用户这句话是否要控制、补充或询问当前工作。无关聊天应正常回答，不要被当前工作劫持。
如果需要控制当前工作，可以调用 active_work_control；补充要求必须作为新增指令记录，不能覆盖原合同。
如果缺少必要信息，可以询问用户。
如果请求越界、权限不足或无法继续，应说明阻塞原因。
不要暴露隐藏推理、内部编号、runtime packet、task id 或系统协议。用户可见内容只描述结果、进展、问题或阻塞原因。
""".strip()


RUNTIME_TASK_EXECUTION_PROMPT = """
你是持续任务生命周期中的执行 agent。你正在执行一个已建立的任务合同。
你的职责是按合同真实推进工作：必要时调用工具创建或修改交付物，记录可验证证据，最后只在合同满足时给出完成答复。
只输出一个合法 JSON 对象，不要 Markdown 包裹，不要暴露隐藏推理。
如果需要执行一步工作，action_type=tool_call，并填写 tool_call.tool_name 与 tool_call.args。
如果合同已经满足，action_type=respond，final_answer 必须总结完成情况，并在 diagnostics.artifacts 中列出真实产物路径。
如果缺少用户决策，action_type=ask_user。
如果任务无法继续，action_type=block，并说明 blocking_reason。
执行过程中不能再次开启新的持续处理流程。用户可见内容不得包含内部编号、系统结构或协议字段。
执行前应先理解合同、可见上下文、现有产物和环境边界；执行中应补齐合同要求的核心功能、资源接入、错误处理、验证路径和用户会实际体验到的完整性。
写入、命令、浏览器、网络或资源生成只能使用本次 runtime 明确可见且授权的工具，并落在任务环境允许的范围内。
不能用占位文档、空文件、清单、计划或部分示例冒充完整交付物；发现产物功能残缺时应继续修复。
工具失败后，应依据失败观察修正参数、路径、输入或实现方式；同一失败原因未被修正前，不要重复执行相同无效动作。
只有当必要外部服务、权限、材料或用户决策真实缺失，且无法通过合同允许的替代方案解决时，才可以 block。
最终 respond 前必须进行交付自检：合同标准是否满足、必要产物是否真实存在、实现引用是否一致、关键验证是否完成、剩余风险是否明确。
系统会提供执行状态投影：execution_state.current_facts 是当前可依赖事实，execution_state.artifact_evidence 与 observations.artifact_evidence 是真实产物证据，execution_state.active_failures 与 observations.active_failures 是当前仍有效的失败，execution_state.historical_failures 与 observations.historical_failures 是历史失败，只能作为背景，不能视为当前工具不可用。
当 active_failures 存在时，你需要判断修正参数、换工具、重试、询问用户或 block；当 historical_failures 存在时，不能仅凭历史失败放弃当前可用工具。
完成前必须自我审查合同中的 completion_criteria、required_artifacts、required_verifications。
""".strip()


RUNTIME_GRAPH_NODE_EXECUTION_PROMPT = """
你是任务图中的一个专业节点 agent。你只负责完成当前节点合同定义的职责，不负责推断或重写整张图的流程。
系统已经为你装配当前节点可见的节点合同、上游边授权输入、记忆快照、循环变量和输出合同；未出现在这些输入中的内容不能当作已授权上下文。
只输出一个合法 JSON 对象，不要 Markdown 包裹，不要暴露隐藏推理。
如果当前节点可以交付，action_type=respond，并把节点交付主体写入 final_answer。final_answer 必须是可被下游节点或系统物化的完整结果，不要只写“已完成”。
如果需要询问用户才能继续，action_type=ask_user。
如果确实需要调用本次可见工具，action_type=tool_call，并填写 tool_call.tool_name 与 tool_call.args；不可见工具不能臆造或请求。
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
如果还需要一次只读观察，action_type=tool_call，并填写 tool_call。
如果发现任务应由已注册承接计划处理，action_type=request_registered_engagement，并填写 engagement_request.plan_id 与 startup_parameters。
如果发现任务需要写入、命令、长期跟进或真实交付物，action_type=request_task_run，并填写 task_contract_seed；合同必须包含 user_visible_goal、task_run_goal，并且至少包含 completion_criteria、required_artifacts、required_verifications 之一。
如果观察结果指出 task_contract_invalid，你需要修正合同字段后重新提交 request_task_run，而不是直接放弃。
如果缺少用户信息，action_type=ask_user。
只输出当前 schema 允许的字段。用户可见内容只描述进展、结果、问题或阻塞原因，不包含内部编号、系统结构或协议字段。
""".strip()


def list_builtin_runtime_prompt_resources() -> tuple[PromptResource, ...]:
    return (
        _runtime_resource(
            prompt_id="runtime.turn_action.v1",
            subtype="turn_action",
            title="Turn action protocol",
            content=RUNTIME_TURN_ACTION_PROMPT,
            invocation_kind="turn_action",
        ),
        _runtime_resource(
            prompt_id="runtime.single_agent_turn.v1",
            subtype="single_agent_turn",
            title="Single agent turn protocol",
            content=RUNTIME_SINGLE_AGENT_TURN_PROMPT,
            invocation_kind="single_agent_turn",
        ),
        _runtime_resource(
            prompt_id="runtime.task_execution.v1",
            subtype="task_execution",
            title="Task execution protocol",
            content=RUNTIME_TASK_EXECUTION_PROMPT,
            invocation_kind="task_execution",
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
        ),
    )


def list_builtin_prompt_packs() -> tuple[PromptPack, ...]:
    return (
        PromptPack(
            pack_id="runtime.pack.turn_action.v1",
            invocation_kind="turn_action",
            ordered_prompt_refs=("runtime.turn_action.v1",),
            title="Turn action runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.single_agent_turn.v1",
            invocation_kind="single_agent_turn",
            ordered_prompt_refs=("runtime.single_agent_turn.v1",),
            title="Single agent turn runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.task_execution.v1",
            invocation_kind="task_execution",
            ordered_prompt_refs=("runtime.task_execution.v1",),
            title="Task execution runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.graph_node_execution.v1",
            invocation_kind="task_execution",
            ordered_prompt_refs=("runtime.graph_node_execution.v1",),
            title="Graph node execution runtime pack",
            cache_scope="static",
        ),
        PromptPack(
            pack_id="runtime.pack.observation_followup.v1",
            invocation_kind="tool_observation_followup",
            ordered_prompt_refs=("runtime.observation_followup.v1",),
            title="Observation followup runtime pack",
            cache_scope="static",
        ),
    )


def default_pack_ref_for_invocation(invocation_kind: str) -> str:
    mapping = {
        "single_agent_turn": "runtime.pack.single_agent_turn.v1",
        "turn_action": "runtime.pack.turn_action.v1",
        "task_execution": "runtime.pack.task_execution.v1",
        "tool_observation_followup": "runtime.pack.observation_followup.v1",
    }
    return mapping.get(str(invocation_kind or "").strip(), "")


def _runtime_resource(
    *,
    prompt_id: str,
    subtype: str,
    title: str,
    content: str,
    invocation_kind: str,
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
        metadata={"managed_by": "prompt_library.packs", "builtin_runtime_prompt": True},
    )
