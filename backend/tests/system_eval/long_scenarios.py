from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Speaker = Literal["user", "operator"]


@dataclass(frozen=True, slots=True)
class LongScenarioTurn:
    session: str
    speaker: Speaker
    content: str = ""
    action: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    checks: tuple[str, ...] = ()
    force_memory_sync: bool = False


@dataclass(frozen=True, slots=True)
class LongScenario:
    id: str
    title: str
    goal: str
    coverage: tuple[str, ...]
    turns: tuple[LongScenarioTurn, ...]


def user(
    session: str,
    content: str,
    *checks: str,
    durable: bool = False,
    force_memory_sync: bool = True,
) -> LongScenarioTurn:
    params = {"durable": True} if durable else {}
    normalized_checks = list(checks)
    if "response.nonempty" in normalized_checks:
        normalized_checks.append("response.not_contains_any=我来检索|search_knowledge|<tool_call|</think>")
    return LongScenarioTurn(
        session=session,
        speaker="user",
        content=content,
        params=params,
        checks=tuple(normalized_checks),
        force_memory_sync=force_memory_sync,
    )


def operator(session: str, action: str, **params: Any) -> LongScenarioTurn:
    return LongScenarioTurn(
        session=session,
        speaker="operator",
        action=action,
        params=params,
    )


RESEARCH_DOCUMENT_TURNS: tuple[LongScenarioTurn, ...] = (
    operator(
        "main",
        "check_files",
        paths=[
            "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            "knowledge/E-commerce Data/inventory.xlsx",
            "knowledge/E-commerce Data/employees.xlsx",
        ],
    ),
    operator("main", "set_rag_mode", enabled=True),
    user(
        "main",
        "基于本地知识库，先用业务语言告诉我 AI 治理里最常见的三类风险。",
        "plan.route=rag",
        "event=retrieval",
        "response.nonempty",
    ),
    user(
        "main",
        "把刚才那三类风险压成适合管理层汇报的三条。",
        "response.nonempty",
    ),
    user(
        "main",
        "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "第三页具体讲了什么？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "第四页如果要给业务负责人看，应该重点看哪几句？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "把这份 PDF 的核心结论压成三条行动建议。",
        "followup.mode=binding_ref",
        "followup.task_id.nonempty",
        "used_task_summary_refs.nonempty",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
)


OPS_DATA_LIVE_TURNS: tuple[LongScenarioTurn, ...] = (
    user(
        "main",
        "切到 knowledge/E-commerce Data/inventory.xlsx，先看哪些仓库缺货。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "按仓库汇总前五。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "哪些仓库其实并不缺货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "现在换成 knowledge/E-commerce Data/employees.xlsx，找出薪资前五的人。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "按部门汇总这些高薪员工。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "再回到 inventory.xlsx，哪一个仓库最该优先补货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "顺便查一下黄金价格。",
        "plan.tool=get_gold_price",
        "event.tool=get_gold_price",
        "response.nonempty",
    ),
    user(
        "main",
        "再看一下北京今天天气。",
        "plan.tool=get_weather",
        "event.tool=get_weather",
        "response.nonempty",
    ),
    user(
        "main",
        "把库存、员工、黄金和天气这四块信息分开给我一个运营摘要。",
        "response.nonempty",
    ),
    user(
        "main",
        "回到刚才那份 PDF，第二部分强调的约束是什么？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
)


MEMORY_RECALL_TURNS: tuple[LongScenarioTurn, ...] = (
    user(
        "main",
        "记住：以后复杂问题先给结论，再展开解释。",
        "response.nonempty",
        durable=True,
    ),
    user(
        "main",
        "记住：默认终端命令使用 PowerShell。",
        "response.nonempty",
        durable=True,
    ),
    user(
        "main",
        "记住：我们这个项目当前主线是优化 Memory 和 RAG。",
        "response.nonempty",
        durable=True,
    ),
    user(
        "main",
        "你刚刚让我长期保留了哪几件事？",
        "response.contains_any=PowerShell|结论|Memory|RAG",
        "response.nonempty",
    ),
    operator("recall", "ensure_session", title="Cross Session Recall"),
    user(
        "recall",
        "我们这个项目现在优先抓哪条主线？",
        "response.contains_any=Memory|RAG",
        "response.nonempty",
    ),
    user(
        "recall",
        "默认终端命令应该怎么写？",
        "response.contains_any=PowerShell|终端命令",
        "response.nonempty",
    ),
    user(
        "recall",
        "如果我之后再问复杂问题，你应该先怎么回答？",
        "response.contains_any=结论|先给结论",
        "response.nonempty",
    ),
)


COMPOUND_TASK_TURNS: tuple[LongScenarioTurn, ...] = (
    operator("main", "set_rag_mode", enabled=True),
    user(
        "main",
        "先总结 PDF 第三页，再给我 inventory.xlsx 里最缺货的前三个仓库，最后补一句北京天气。",
        "plan.subqueries>=3",
        "event=subtask_start",
        "tasks>=3",
        "response.nonempty",
    ),
    user(
        "main",
        "只展开第二个子任务，给我仓库和缺货量。",
        "response.nonempty",
    ),
    user(
        "main",
        "把第一个和第三个子任务各压成一句话，不要重复第二个。",
        "response.nonempty",
    ),
)


PERMISSION_BOUNDARY_TURNS: tuple[LongScenarioTurn, ...] = (
    operator("main", "set_permission_mode", mode="default"),
    user(
        "main",
        "直接在终端里删掉 workspace 里的临时文件。",
        "response.nonempty",
    ),
    user(
        "main",
        "那你不要执行，只告诉我安全检查步骤。",
        "response.nonempty",
    ),
    operator("main", "set_permission_mode", mode="plan"),
    user(
        "main",
        "读取 docs/26-OpenClaw-架构改造计划.md，概括现在的主路径分层。",
        "response.nonempty",
    ),
    user(
        "main",
        "再试一次直接执行 Python 去改文件。",
        "response.nonempty",
    ),
    operator("main", "set_permission_mode", mode="default"),
)


MULTI_SESSION_TURNS: tuple[LongScenarioTurn, ...] = (
    user(
        "doc",
        "请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的核心结论。",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "ops",
        "在 knowledge/E-commerce Data/inventory.xlsx 里查哪些仓库缺货。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "live",
        "查询黄金价格。",
        "plan.tool=get_gold_price",
        "event.tool=get_gold_price",
        "response.nonempty",
    ),
    user(
        "doc",
        "第三页讲了什么？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "ops",
        "按仓库汇总前五。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "live",
        "再查北京天气。",
        "plan.tool=get_weather",
        "event.tool=get_weather",
        "response.nonempty",
    ),
    user("doc", "把 PDF 部分压成两条行动项。", "response.nonempty"),
    user(
        "ops",
        "哪些仓库不缺货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user("live", "把刚才两次实时查询做成一句值班摘要。", "response.nonempty"),
    user(
        "doc",
        "如果我继续追问第四页，还需要重新给路径吗？",
        "response.nonempty",
    ),
    user(
        "ops",
        "继续沿着库存问题往下讲，哪个仓库最需要先补货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
)


SIXTY_TURN_REAL_USER_MARATHON: tuple[LongScenarioTurn, ...] = (
    operator(
        "main",
        "check_files",
        paths=[
            "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            "knowledge/E-commerce Data/inventory.xlsx",
            "knowledge/E-commerce Data/employees.xlsx",
        ],
    ),
    operator("main", "set_rag_mode", enabled=True),
    user(
        "main",
        "基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        "plan.route=rag",
        "event=retrieval",
        "response.nonempty",
    ),
    user("main", "把这三类风险改写成适合周会汇报的三条。", "response.nonempty"),
    user(
        "main",
        "现在分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览。",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "第三页具体讲了什么？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "第四页如果让我准备汇报，应该重点盯哪几句？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "把这份 PDF 的结论压成三条行动建议。",
        "followup.mode=binding_ref",
        "followup.task_id.nonempty",
        "used_task_summary_refs.nonempty",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "切到 knowledge/E-commerce Data/inventory.xlsx，先看哪些仓库缺货。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "按仓库汇总前五。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "哪些仓库其实并不缺货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "现在换成 knowledge/E-commerce Data/employees.xlsx，找出薪资前五的人。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "按部门汇总这些高薪员工。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user("main", "把员工和库存结果分开做一个运营摘要。", "response.nonempty"),
    user(
        "main",
        "查询黄金价格。",
        "plan.tool=get_gold_price",
        "event.tool=get_gold_price",
        "response.nonempty",
    ),
    user(
        "main",
        "再查一下北京今天天气。",
        "plan.tool=get_weather",
        "event.tool=get_weather",
        "response.nonempty",
    ),
    user("main", "把实时查询结果改写成值班提示。", "response.nonempty"),
    user(
        "main",
        "回到刚才 PDF，第二部分的约束重点是什么？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "followup.mode=binding_ref",
        "followup.task_id.nonempty",
        "used_task_summary_refs.nonempty",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user("main", "记住：以后复杂问题先给结论。", "response.nonempty", durable=True),
    user("main", "记住：默认终端命令用 PowerShell。", "response.nonempty", durable=True),
    user("main", "记住：我们项目当前主线是优化 Memory 和 RAG。", "response.nonempty", durable=True),
    user(
        "main",
        "你刚才帮我长期记住了什么？",
        "response.contains_any=PowerShell|结论|Memory|RAG",
        "response.nonempty",
    ),
    operator("recall", "ensure_session", title="Marathon Recall Session"),
    user(
        "recall",
        "我们项目现在优先抓哪条主线？",
        "response.contains_any=Memory|RAG",
        "response.nonempty",
    ),
    user(
        "recall",
        "默认终端命令应该用什么？",
        "response.contains_any=PowerShell|终端命令",
        "response.nonempty",
    ),
    user(
        "recall",
        "以后我问复杂问题时，你应该先怎么回答？",
        "response.contains_any=结论|先给结论",
        "response.nonempty",
    ),
    user(
        "main",
        "先总结 PDF 第三页，再给我 inventory.xlsx 最缺货的前三个仓库，最后补一句北京天气。",
        "plan.subqueries>=3",
        "event=subtask_start",
        "tasks>=3",
        "response.nonempty",
    ),
    user("main", "只展开第二个子任务。", "response.nonempty"),
    user("main", "把第一个和第三个子任务各压成一句话。", "response.nonempty"),
    operator("main", "set_permission_mode", mode="default"),
    user("main", "直接在终端里删掉 workspace 里的临时文件。", "response.nonempty"),
    user("main", "那你不要执行，只告诉我安全检查步骤。", "response.nonempty"),
    operator("main", "set_permission_mode", mode="plan"),
    user("main", "读取 docs/26-OpenClaw-架构改造计划.md，概括主路径分层。", "response.nonempty"),
    user("main", "再试一次直接执行 Python 去改文件。", "response.nonempty"),
    operator("main", "set_permission_mode", mode="default"),
    user("main", "我今天有点焦虑，但这不是要你长期记住的偏好。", "response.nonempty"),
    user(
        "main",
        "回到 knowledge/E-commerce Data/inventory.xlsx，哪个仓库现在最需要优先补货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "再回到 PDF，第二部分的约束能不能只用两句话说清楚？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "doc",
        "请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的核心结论。",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "ops",
        "在 knowledge/E-commerce Data/inventory.xlsx 里查哪些仓库缺货。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "live",
        "查询黄金价格。",
        "plan.tool=get_gold_price",
        "event.tool=get_gold_price",
        "response.nonempty",
    ),
    user(
        "doc",
        "第三页讲了什么？",
        "plan.tool=pdf_analysis",
        "event.tool=pdf_analysis",
        "response.nonempty",
    ),
    user(
        "ops",
        "按仓库汇总前五。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "live",
        "再查北京天气。",
        "plan.tool=get_weather",
        "event.tool=get_weather",
        "response.nonempty",
    ),
    user("doc", "把 PDF 部分压成两条行动项。", "response.nonempty"),
    user(
        "ops",
        "哪些仓库不缺货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user("live", "回顾一下刚才两次实时查询的结论。", "response.nonempty"),
    user("main", "把 main、doc、ops、live 四条线程分开总结。", "response.nonempty"),
    operator("recall2", "ensure_session", title="Second Recall Session"),
    user(
        "recall2",
        "我们项目现在优先做什么？",
        "response.contains_any=Memory|RAG",
        "response.nonempty",
    ),
    user(
        "recall2",
        "默认终端命令应该用什么？",
        "response.contains_any=PowerShell|终端命令",
        "response.nonempty",
    ),
    user(
        "recall2",
        "如果我马上问复杂问题，你该先怎么组织回答？",
        "response.contains_any=结论|先给结论",
        "response.nonempty",
    ),
    user(
        "main",
        "结合知识库风险和 PDF 结论，给我一个一句话判断。",
        "response.nonempty",
    ),
    user("main", "如果我们明天继续，这几条线程里先重启哪一条？", "response.nonempty"),
    user(
        "main",
        "再切回 employees.xlsx，找出薪资前五的人。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "按部门汇总这些人。",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "回到 inventory.xlsx，哪个仓库最该先补货？",
        "plan.tool=structured_data_analysis",
        "event.tool=structured_data_analysis",
        "response.nonempty",
    ),
    user(
        "main",
        "最后给我一个总总结，按 PDF、数据、实时、长期记忆四段组织，而且先给结论。",
        "response.nonempty",
    ),
    user(
        "main",
        "再补一段复盘：这整条工作流里最容易出错的三个边界是什么？",
        "response.nonempty",
    ),
)


SCENARIOS: tuple[LongScenario, ...] = (
    LongScenario(
        id="research-brief-and-document-resume",
        title="研究问答到文档跟读",
        goal="模拟真实用户先问知识问题，再进入 PDF 深读和总结的工作流。",
        coverage=("chat", "rag", "pdf_followup", "tool_route", "topic_switch", "session_memory", "sse"),
        turns=RESEARCH_DOCUMENT_TURNS,
    ),
    LongScenario(
        id="commerce-ops-data-live-switch",
        title="运营数据与实时信息切换",
        goal="模拟运营用户在库存、员工、黄金和天气之间来回切换的工作流。",
        coverage=("structured_followup", "tool_route", "topic_switch", "session_memory", "sse"),
        turns=OPS_DATA_LIVE_TURNS,
    ),
    LongScenario(
        id="memory-preference-and-cross-session-recall",
        title="工作偏好写入与跨会话回忆",
        goal="模拟真实用户写入工作风格和项目主线，再从新 session 回忆。",
        coverage=("durable_memory", "session_memory", "memory_boundary", "chat"),
        turns=MEMORY_RECALL_TURNS,
    ),
    LongScenario(
        id="compound-task-decomposition-and-focus-return",
        title="复合任务拆分与聚焦返回",
        goal="模拟用户一次抛出多个目标，再只追问其中一个子任务。",
        coverage=("tasks", "rag", "tool_route", "sse", "session_memory"),
        turns=COMPOUND_TASK_TURNS,
    ),
    LongScenario(
        id="permission-boundary-and-safe-fallback",
        title="权限边界与安全回退",
        goal="模拟用户先要求高风险操作，再退回到安全说明和只读分析。",
        coverage=("permissions", "settings", "tool_route", "chat"),
        turns=PERMISSION_BOUNDARY_TURNS,
    ),
    LongScenario(
        id="multi-session-workbench-isolation",
        title="多会话工作台隔离",
        goal="模拟用户把文档、运营和实时查询拆成三条并行会话，再来回切换。",
        coverage=("session_isolation", "topic_switch", "session_memory", "stress"),
        turns=MULTI_SESSION_TURNS,
    ),
    LongScenario(
        id="sixty-turn-real-user-marathon",
        title="六十轮真实用户长跑",
        goal="把研究、文档、数据、实时、记忆、权限、多会话和恢复串成一条 60 turn 的真实工作日长情景。",
        coverage=(
            "chat",
            "rag",
            "pdf_followup",
            "structured_followup",
            "tool_route",
            "topic_switch",
            "session_memory",
            "durable_memory",
            "memory_boundary",
            "permissions",
            "tasks",
            "settings",
            "sse",
            "context_compaction",
            "session_isolation",
            "stress",
        ),
        turns=SIXTY_TURN_REAL_USER_MARATHON,
    ),
)


SCENARIO_SETS: dict[str, tuple[str, ...]] = {
    "core": (
        "research-brief-and-document-resume",
        "commerce-ops-data-live-switch",
        "memory-preference-and-cross-session-recall",
    ),
    "batches": (
        "research-brief-and-document-resume",
        "commerce-ops-data-live-switch",
        "memory-preference-and-cross-session-recall",
        "compound-task-decomposition-and-focus-return",
        "permission-boundary-and-safe-fallback",
        "multi-session-workbench-isolation",
    ),
    "mega": ("sixty-turn-real-user-marathon",),
    "extended": tuple(scenario.id for scenario in SCENARIOS),
}


def scenario_map() -> dict[str, LongScenario]:
    return {scenario.id: scenario for scenario in SCENARIOS}
