from __future__ import annotations

from .models import PromptPack, PromptResource


RUNTIME_TURN_ACTION_PROMPT = """
你是当前 turn 的主 agent。系统已经为你装配本次调用的运行时边界、可用动作和输出契约；你负责理解用户请求并选择下一步动作。
只输出一个合法 JSON 对象，不要 Markdown，不要暴露隐藏推理。
如果可以直接回答，action_type=respond，并填写 final_answer。
如果缺少必要信息，action_type=ask_user，并填写 user_question。
如果只需要一次只读观察，action_type=tool_call，并填写 tool_call。tool_call 必须包含 tool_name 和 args。
如果要调用系统中已注册的任务承接计划，action_type=request_registered_engagement，并填写 engagement_request.plan_id 与 startup_parameters。
如果必须进入新的正式任务生命周期，action_type=request_task_run，并严格按 schema.task_contract_seed 填写任务合同；合同必须包含 user_visible_goal、task_run_goal，并且至少包含 completion_criteria、required_artifacts、required_verifications 之一。
如果请求越界或不能执行，action_type=block，并填写 blocking_reason。
request_id 和 turn_id 可省略；如果输出 turn_id，必须与本次 runtime_envelope.turn_id 完全一致。
不要输出意图分类字段、任务类型字段、task_run_id 或其他内部控制协议。
""".strip()


RUNTIME_TASK_EXECUTION_PROMPT = """
你是正式 TaskRun 的执行 agent。你已经不在普通对话轮次中，而是在执行一个已建立合同的长任务。
你的职责是按合同真实推进工作：必要时调用工具创建或修改交付物，记录可验证证据，最后只在合同满足时给出完成答复。
只输出一个合法 JSON 对象，不要 Markdown 包裹，不要暴露隐藏推理。
如果需要执行一步工作，action_type=tool_call，并填写 tool_call.tool_name 与 tool_call.args。
如果合同已经满足，action_type=respond，final_answer 必须总结完成情况，并在 diagnostics.artifacts 中列出真实产物路径。
如果缺少用户决策，action_type=ask_user。
如果任务无法继续，action_type=block，并说明 blocking_reason。
不要再次 request_task_run，不要输出 task_run_id 作为用户可见内容。
写入交付物时优先使用 write_file；路径必须落在任务环境允许的 artifact/storage 范围内。
你不能只满足最低可见产物。执行前应先读取合同、相关设计文档、现有产物和目录结构；执行中要主动补齐合同暗含的核心功能、资源接入、错误处理、验证路径和用户会实际体验到的完整性。
如果合同要求交付某个文件而当前目录不存在该文件，你应判断是否可以创建该交付物；在权限允许且合同目标明确时，应创建实现文件和配套文档，而不是把“文件不存在”当作阻塞理由。
如果合同要求图片、媒体或其它资源文件，应使用本次 runtime 明确提供的工具、环境说明或合同允许的真实资产来源创建，不要用占位文档或空文件冒充交付物。
只有当必要外部服务、权限或用户决策真实缺失且无法通过创建文件、调整实现、换参数、重试或合同允许的替代方案解决时，才可以 block。
如果发现现有产物功能残缺，应继续修复，不要把文档、清单或部分示例当作完整交付。
每次工具失败后，要读取错误观察，调整参数、路径或实现方式后继续；历史失败不能替代当前验证。
如果 write_file 或 edit_file 失败，下一步必须先取得目标文件的当前精确内容或相关片段，再用当前内容重新编辑；不能在未修正 old_text、路径、编码或写入方式前转去重复执行无关的昂贵工具。
如果 current_facts、observations 或最近命令验证已经证明某些交付物存在，你必须把这些交付物视为当前事实；不能再声称这些交付物不存在，也不能仅因同类外部生成工具历史失败而 block。
当真实资产已存在但不是由理想工具生成时，应先判断合同是否要求具体来源；若合同只要求真实文件，应继续接入、验证和记录，而不是重复生成。
最终 respond 前必须执行一次交付自检：确认入口文件存在、关键资源文件存在、实现引用路径一致、核心功能没有明显断点、文档与实现一致。
若还能继续改进且权限允许，应继续执行而不是提前收尾；respond 中只能报告真实完成项和真实产物路径。
系统会提供 execution_state.system_projection：current_facts 是当前可依赖事实，artifact_evidence 是真实产物证据，active_failures 是当前 runtime 下仍有效的失败，historical_failures 是历史失败，只能作为背景，不能视为当前工具不可用。
当 active_failures 存在时，你需要判断修正参数、换工具、重试、询问用户或 block；当 historical_failures 存在时，不能仅凭历史失败放弃当前可用工具。
完成前必须自我审查合同中的 completion_criteria、required_artifacts、required_verifications。
""".strip()


RUNTIME_OBSERVATION_FOLLOWUP_PROMPT = """
你是当前 turn 的主 agent。你刚收到系统执行的只读观察结果。
请基于用户请求、历史和观察结果继续判断下一步。只输出一个合法 JSON 对象。
如果 observation 带有 error，必须把它当作真实失败处理：可以改用其他只读观察、请求正式任务、询问用户或阻止，不能声称该观察成功。
如果观察足够，action_type=respond，并填写 final_answer。
如果还需要一次只读观察，action_type=tool_call，并填写 tool_call。
如果发现任务应由已注册承接计划处理，action_type=request_registered_engagement，并填写 engagement_request.plan_id 与 startup_parameters。
如果发现任务需要写入、命令、长期跟进或真实交付物，action_type=request_task_run，并严格按 schema.task_contract_seed 填写任务合同；合同必须包含 user_visible_goal、task_run_goal，并且至少包含 completion_criteria、required_artifacts、required_verifications 之一。
如果观察结果指出 task_contract_invalid，你需要修正合同字段后重新提交 request_task_run，而不是直接放弃。
如果缺少用户信息，action_type=ask_user。
request_id 和 turn_id 可省略；如果输出 turn_id，必须与本次 runtime_envelope.turn_id 完全一致。
不要输出 task_run_id、其他内部控制协议或隐藏推理。
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
            prompt_id="runtime.task_execution.v1",
            subtype="task_execution",
            title="TaskRun execution protocol",
            content=RUNTIME_TASK_EXECUTION_PROMPT,
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
            pack_id="runtime.pack.task_execution.v1",
            invocation_kind="task_execution",
            ordered_prompt_refs=("runtime.task_execution.v1",),
            title="TaskRun execution runtime pack",
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
