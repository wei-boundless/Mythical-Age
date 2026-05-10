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
        normalized_checks.append(
            "response.not_contains_any="
            "我来检索|search_knowledge|langchain_agent_search_knowledge|"
            "langchain_agent_analyze_pdf|langchain_agent_analyze_structured_data|"
            "local-mcp://|skill://|<tool_call|</think>"
        )
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
        "把刚才那三类风险改写成适合管理层周会汇报的三条判断，每条一句话。",
        "response.nonempty",
    ),
    user(
        "main",
        "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "继续沿着这份 PDF 往下看。如果第三页是目录页或过渡页，请直接说明它在全文里的作用，不要假装它有正文观点。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.contains_any=目录|结构|章节|导航|过渡",
        "response.nonempty",
    ),
    user(
        "main",
        "如果我要把这份报告讲给业务负责人听，第四页最值得摘出来的两到三句是什么？请直接给我摘读重点和原因。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "把这份 PDF 的核心结论压成三条行动建议，每条都要带一个行动动词。",
        "main.active_pdf.nonempty",
        "response.contains_any=建立|收紧|推进|统一|评估|补齐",
        "response.nonempty",
    ),
)


OPS_DATA_LIVE_TURNS: tuple[LongScenarioTurn, ...] = (
    user(
        "main",
        "切到 knowledge/E-commerce Data/inventory.xlsx。先告诉我这个表里是否存在库存缺口，并按仓库给我缺口概览。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "继续沿着 inventory.xlsx，只按缺口总量汇总仓库，并给我缺口最高的前三个仓库。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "再补一句：是否存在完全没有缺口的仓库？如果没有，直接说没有。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.contains_any=没有|存在|仓库",
        "response.nonempty",
    ),
    user(
        "main",
        "现在切到 knowledge/E-commerce Data/employees.xlsx。找出薪资最高的前五名员工，并带上姓名、部门、薪资。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "只基于刚才那前五名员工，按部门做一个归类总结，不要回到全表重算。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "再回到 inventory.xlsx。告诉我当前最该优先处理的是哪个仓库，并说清你依据的是缺口、SKU 还是别的口径。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "顺便查一下黄金价格，直接给结论和时间口径，不要反问我要不要查。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.not_contains_any=要我现在查吗|要我现在直接拉|可以马上帮你拉",
        "response.nonempty",
    ),
    user(
        "main",
        "再看一下北京今天天气，直接给天气结论和温度范围。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.contains_any=北京|天气|温度|°C",
        "response.nonempty",
    ),
    user(
        "main",
        "把库存、员工、黄金和天气这四块信息分开给我一个运营摘要，每块只写一到两句。",
        "response.nonempty",
    ),
    user(
        "main",
        "现在回到刚才那份 PDF。第二部分真正强调的约束是什么？如果是延续前文结论，请直接承接前文，不要重新从头讲全文。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
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
        "记住：回答我时可以直接称呼我岩。",
        "response.nonempty",
        durable=True,
    ),
    user(
        "main",
        "记住：如果信息不足，先明确告诉我缺什么，不要直接猜。",
        "response.nonempty",
        durable=True,
    ),
    user(
        "main",
        "你刚刚让我长期保留了哪几件事？",
        "response.contains_any=岩|结论|缺什么",
        "response.nonempty",
    ),
    operator("recall", "ensure_session", title="Cross Session Recall"),
    user(
        "recall",
        "如果我之后再问复杂问题，你应该先怎么回答？",
        "response.contains_any=结论|先给结论",
        "response.nonempty",
    ),
    user(
        "recall",
        "你之后应该怎么称呼我？",
        "response.contains_any=岩",
        "response.nonempty",
    ),
    user(
        "recall",
        "如果信息不足，你应该怎么处理？",
        "response.contains_any=缺什么|先明确|不要直接猜|承认不足|澄清边界",
        "response.nonempty",
    ),
)


COMPOUND_TASK_TURNS: tuple[LongScenarioTurn, ...] = (
    operator("main", "set_rag_mode", enabled=True),
    user(
        "main",
        "先总结 PDF 第三页，再给我 inventory.xlsx 里最缺货的前三个仓库，最后补一句北京天气。",
        "plan.execution_mode=bundle_execution",
        "plan.bundle_items=3",
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


TASK_SYSTEM_LIGHT_WEB_GAME_ACCEPTANCE_TURNS: tuple[LongScenarioTurn, ...] = (
    LongScenarioTurn(
        session="main",
        speaker="user",
        content="请在 frontend/public/games 下生成一个简单可运行的网页贪吃蛇小游戏，并告诉我产物路径与验证情况。",
        checks=(
            "response.nonempty",
            "task_run.nonempty",
            "trace.agent_run_results.nonempty",
            "trace.artifact.contains=frontend/public/games",
        ),
        params={"task_selection": {"selected_task_id": "task.dev.light_web_game"}},
        force_memory_sync=False,
    ),
)


TASK_SYSTEM_SHORT_STORY_COORDINATION_ACCEPTANCE_TURNS: tuple[LongScenarioTurn, ...] = (
    LongScenarioTurn(
        session="main",
        speaker="user",
        content="请用多 Agent 协调模式完成一个短篇小说协作流程：先提出创意并审核，通过后正式编写，再做内容纠察与验收，如未通过则进入一次修正循环，最终给我验收通过的短篇小说结果。",
        checks=(
            "response.nonempty",
            "task_run.nonempty",
        ),
        force_memory_sync=False,
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
        "请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的核心结论，按治理变化、产业压力、行动建议三块组织。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "ops",
        "在 knowledge/E-commerce Data/inventory.xlsx 里查哪些仓库有库存缺口，并先按仓库给我概览。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "live",
        "查询黄金价格，直接报结果，不要进入确认式回复。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.not_contains_any=要我现在查吗|要我现在直接拉|可以马上帮你拉",
        "response.nonempty",
    ),
    user(
        "doc",
        "继续 doc 线程。如果第三页是目录或过渡页，请直接说它承担什么作用。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "ops",
        "继续 ops 线程。只按缺口总量汇总仓库，并给我缺口最高的前三个。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "live",
        "再查北京天气，直接给天气和温度范围。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.contains_any=北京|天气|温度|°C",
        "response.nonempty",
    ),
    user("doc", "把 PDF 部分压成两条行动项，每条一句话。", "response.nonempty"),
    user(
        "ops",
        "哪些仓库完全没有缺口？如果没有就直接说没有。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.contains_any=没有|存在|仓库",
        "response.nonempty",
    ),
    user("live", "把刚才两次实时查询做成一句值班摘要，必须同时提到黄金和北京天气。", "response.contains_all=黄金|北京", "response.nonempty"),
    user(
        "doc",
        "如果我继续追问第四页，还需要重新给 PDF 路径吗？请按当前 doc 线程直接回答。",
        "response.nonempty",
    ),
    user(
        "ops",
        "继续沿着库存问题往下讲，哪个仓库最需要先补货？请保持在 ops 线程里回答。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
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
        "基于本地知识库，先告诉我 AI 治理里最常见的三类风险，用业务能听懂的话说。",
        "plan.route=rag",
        "event=retrieval",
        "response.nonempty",
    ),
    user("main", "把这三类风险改写成适合周会汇报的三条，每条只写一句。", "response.nonempty"),
    user(
        "main",
        "现在分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览，按主题而不是按页数讲。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "继续沿着这份 PDF。如果第三页是目录页或过渡页，请直接说它在全文里的作用，不要假装它有正文观点。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.contains_any=目录|结构|章节|导航|过渡",
        "response.nonempty",
    ),
    user(
        "main",
        "第四页如果我要拿去给业务负责人汇报，最值得摘出来的两到三句是什么？",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "把这份 PDF 的结论压成三条行动建议，每条都要带行动动词。",
        "main.active_pdf.nonempty",
        "response.contains_any=建立|推进|统一|收紧|评估|补齐",
        "response.nonempty",
    ),
    user(
        "main",
        "切到 knowledge/E-commerce Data/inventory.xlsx。先告诉我这个表里是否存在库存缺口，并按仓库给我概览。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "继续沿着 inventory.xlsx，只按缺口总量汇总仓库，并给我缺口最高的前三个仓库。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "再补一句：是否存在完全没有缺口的仓库？如果没有，直接说没有。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.contains_any=没有|存在|仓库",
        "response.nonempty",
    ),
    user(
        "main",
        "现在切到 knowledge/E-commerce Data/employees.xlsx。找出薪资最高的前五名员工，并带上姓名、部门、薪资。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "只基于刚才这前五名员工，按部门做一个归类总结，不要回到全表重算。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user("main", "把员工和库存结果分开做一个运营摘要，每块只写一到两句。", "response.nonempty"),
    user(
        "main",
        "查询黄金价格，直接给结论和时间口径，不要反问我要不要查。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.not_contains_any=要我现在查吗|要我现在直接拉|可以马上帮你拉",
        "response.nonempty",
    ),
    user(
        "main",
        "再查一下北京今天天气，直接给天气结论和温度范围。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.contains_any=北京|天气|温度|°C",
        "response.not_contains_any=要我现在查吗|要我现在直接拉|可以马上帮你拉",
        "response.nonempty",
    ),
    user("main", "把实时查询结果改写成值班提示，至少要同时提到黄金和北京天气。", "response.contains_all=黄金|北京", "response.nonempty"),
    user(
        "main",
        "回到刚才 PDF。第二部分真正强调的约束重点是什么？如果是承接前文，请直接承接，不要从头重讲全文。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user("main", "记住：以后复杂问题先给结论。", "response.nonempty", durable=True),
    user("main", "记住：回答我时可以直接称呼我岩。", "response.nonempty", durable=True),
    user("main", "记住：如果信息不足，先明确告诉我缺什么，不要直接猜。", "response.nonempty", durable=True),
    user(
        "main",
        "你刚才帮我长期记住了什么？",
        "response.contains_any=岩|结论|缺什么",
        "response.nonempty",
    ),
    operator("recall", "ensure_session", title="Marathon Recall Session"),
    user(
        "recall",
        "如果我之后再问复杂问题，你应该先怎么回答？",
        "response.contains_any=结论|先给结论",
        "response.nonempty",
    ),
    user(
        "recall",
        "你之后应该怎么称呼我？",
        "response.contains_any=岩",
        "response.nonempty",
    ),
    user(
        "recall",
        "如果信息不足，你应该怎么处理？",
        "response.contains_any=缺什么|先明确|不要直接猜|承认不足|澄清边界",
        "response.nonempty",
    ),
    user(
        "main",
        "先给我三段结果：第一段概括刚才 PDF 的当前页面作用，第二段给 inventory.xlsx 的缺口最高仓库，第三段补一句北京天气。",
        "plan.execution_mode=bundle_execution",
        "plan.bundle_items=3",
        "response.contains_all=北京|仓库",
        "response.nonempty",
    ),
    user(
        "main",
        "只展开第二个子任务，给我仓库和缺口依据，不要重复 PDF 和天气。",
        "response.not_contains_any=天气|PDF",
        "response.nonempty",
    ),
    user(
        "main",
        "把第一个和第三个子任务各压成一句话，不要再提第二个。",
        "response.contains_any=北京|目录|章节|导航|过渡",
        "response.nonempty",
    ),
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
        "回到 knowledge/E-commerce Data/inventory.xlsx。哪个仓库现在最需要优先处理？请说清你依据的是仓库缺口还是单个 SKU 缺口。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "再回到 PDF，第二部分的约束能不能只用两句话说清楚？",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "doc",
        "请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的核心结论，按治理变化、产业压力、行动建议三块组织。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "ops",
        "在 knowledge/E-commerce Data/inventory.xlsx 里查哪些仓库有库存缺口，并先按仓库给我概览。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "live",
        "查询黄金价格，直接报结果，不要进入确认式回复。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.not_contains_any=要我现在查吗|要我现在直接拉|可以马上帮你拉",
        "response.nonempty",
    ),
    user(
        "doc",
        "继续 doc 线程。如果第三页是目录或过渡页，请直接说它承担什么作用。",
        "plan.tool=mcp_pdf",
        "event.mcp=pdf",
        "main.active_pdf.nonempty",
        "response.nonempty",
    ),
    user(
        "ops",
        "继续 ops 线程。只按缺口总量汇总仓库，并给我缺口最高的前三个。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "live",
        "再查北京天气，直接给天气和温度范围。",
        "plan.tool=web_search",
        "event.tool=web_search",
        "response.contains_any=北京|天气|温度|°C",
        "response.nonempty",
    ),
    user("doc", "把 PDF 部分压成两条行动项，每条一句话。", "response.nonempty"),
    user(
        "ops",
        "哪些仓库完全没有缺口？如果没有就直接说没有。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.contains_any=没有|存在|仓库",
        "response.nonempty",
    ),
    user(
        "live",
        "回顾一下刚才两次实时查询的结论，必须同时提到黄金和北京。",
        "response.contains_all=黄金|北京",
        "response.not_contains_any=没有查询结论|未拉数据|只到了确认环节",
        "response.nonempty",
    ),
    user("main", "把 main、doc、ops、live 四条线程分开总结。", "response.nonempty"),
    operator("recall2", "ensure_session", title="Second Recall Session"),
    user(
        "recall2",
        "如果我之后再问复杂问题，你应该先怎么回答？",
        "response.contains_any=结论|先给结论",
        "response.nonempty",
    ),
    user(
        "recall2",
        "你之后应该怎么称呼我？",
        "response.contains_any=岩",
        "response.nonempty",
    ),
    user(
        "recall2",
        "如果信息不够，你该先怎么处理？",
        "response.contains_any=缺什么|先明确|不要直接猜|承认不足|澄清边界",
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
        "再切回 employees.xlsx，找出薪资前五的人，并带上姓名、部门、薪资。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "按部门汇总这些人，只总结这前五名，不要扩展回全表。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "回到 inventory.xlsx，哪个仓库最该先补货？请明确你的判断口径。",
        "plan.tool=mcp_structured_data",
        "event.mcp=structured_data",
        "main.active_dataset.nonempty",
        "response.nonempty",
    ),
    user(
        "main",
        "最后给我一个总总结，按 PDF、数据、实时、长期记忆四段组织，而且先给结论。",
        "response.contains_all=PDF|数据|实时|长期记忆|岩",
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
        goal="模拟真实用户写入稳定回答偏好，再从新 session 回忆。",
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
        id="task-system-light-web-game-acceptance",
        title="任务系统主 Agent 小游戏开发验收",
        goal="验证主 Agent 能以正式任务装配完成轻量网页小游戏开发，并留下真实产物与执行痕迹。",
        coverage=("tasks", "tool_route", "sse"),
        turns=TASK_SYSTEM_LIGHT_WEB_GAME_ACCEPTANCE_TURNS,
    ),
    LongScenario(
        id="task-system-short-story-coordination-acceptance",
        title="任务系统多 Agent 小说协作验收",
        goal="验证多 Agent 协调任务能跑通创意、审核、编写、纠察、验收与修正循环。",
        coverage=("tasks", "sse", "stress"),
        turns=TASK_SYSTEM_SHORT_STORY_COORDINATION_ACCEPTANCE_TURNS,
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
        "task-system-light-web-game-acceptance",
        "permission-boundary-and-safe-fallback",
        "multi-session-workbench-isolation",
    ),
    "task_acceptance": (
        "task-system-light-web-game-acceptance",
        "task-system-short-story-coordination-acceptance",
    ),
    "mega": ("sixty-turn-real-user-marathon",),
    "extended": tuple(scenario.id for scenario in SCENARIOS),
}


def scenario_map() -> dict[str, LongScenario]:
    return {scenario.id: scenario for scenario in SCENARIOS}
