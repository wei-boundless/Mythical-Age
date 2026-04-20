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


SCENARIOS: tuple[LongScenario, ...] = (
    LongScenario(
        id="full-workbench-journey",
        title="三栏工作台全链路长对话",
        goal="串起知识库、PDF、结构化数据、实时工具、会话记忆和长期记忆。",
        coverage=(
            "chat",
            "rag",
            "pdf_followup",
            "structured_followup",
            "tool_route",
            "topic_switch",
            "session_memory",
            "durable_memory",
            "sse",
        ),
        turns=(
            LongScenarioTurn(
                session="main",
                speaker="operator",
                action="check_files",
                params={
                    "paths": [
                        "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                        "knowledge/E-commerce Data/inventory.xlsx",
                        "knowledge/E-commerce Data/employees.xlsx",
                    ]
                },
            ),
            LongScenarioTurn(
                session="main",
                speaker="operator",
                action="set_rag_mode",
                params={"enabled": True},
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
                checks=("plan.route=rag", "event=retrieval", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，先给我全文总览。",
                checks=("plan.tool=pdf_analysis", "event.tool=pdf_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="第三页具体讲了什么？",
                checks=("plan.tool=pdf_analysis", "event.tool=pdf_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="切到 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？",
                checks=("plan.tool=structured_data_analysis", "event.tool=structured_data_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="按仓库汇总前五。",
                checks=("plan.tool=structured_data_analysis", "event.tool=structured_data_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="查询黄金价格。",
                checks=("plan.tool=get_gold_price", "event.tool=get_gold_price", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="北京今天天气怎么样？",
                checks=("plan.tool=get_weather", "event.tool=get_weather", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="回到刚才 PDF，第二部分的结论是什么？",
                checks=("plan.tool=pdf_analysis", "event.tool=pdf_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="记住：以后复杂问题先给结论。",
                checks=("response.nonempty",),
                force_memory_sync=True,
                params={"durable": True},
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="记住：默认终端命令用 PowerShell。",
                checks=("response.nonempty",),
                force_memory_sync=True,
                params={"durable": True},
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="我刚刚让你记住了什么？",
                checks=("response.contains_any=PowerShell|先给结论", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="把今天这几个任务分成 PDF、数据表、实时查询三段总结。",
                checks=("response.nonempty",),
                force_memory_sync=True,
            ),
        ),
    ),
    LongScenario(
        id="durable-memory-write-and-semantic-recall",
        title="长期记忆写入与跨会话回忆",
        goal="验证 durable memory 的写入、精确回忆和跨 session 回忆。",
        coverage=("durable_memory", "session_memory", "memory_boundary", "chat"),
        turns=(
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="记住：以后复杂问题先给结论，再展开。",
                checks=("response.nonempty",),
                force_memory_sync=True,
                params={"durable": True},
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="记住：默认终端命令用 PowerShell。",
                checks=("response.nonempty",),
                force_memory_sync=True,
                params={"durable": True},
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="记住：我们项目当前主线是优化 Memory 和 RAG。",
                checks=("response.nonempty",),
                force_memory_sync=True,
                params={"durable": True},
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="以后终端命令默认用什么？",
                checks=("response.contains_any=PowerShell|终端命令", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="如果我们继续这个项目，现阶段优先抓哪条主线？",
                checks=("response.contains_any=Memory|RAG", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="fresh",
                speaker="operator",
                action="ensure_session",
                params={"title": "Durable Memory Recall"},
            ),
            LongScenarioTurn(
                session="fresh",
                speaker="user",
                content="我们项目现在优先做什么？",
                checks=("response.contains_any=Memory|RAG", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="fresh",
                speaker="user",
                content="默认终端命令应该用什么？",
                checks=("response.contains_any=PowerShell|终端命令", "response.nonempty"),
                force_memory_sync=True,
            ),
        ),
    ),
    LongScenario(
        id="multi-session-isolation-and-resume",
        title="多会话切换与隔离恢复",
        goal="验证 PDF、结构化数据、实时查询三类 session 的隔离和恢复。",
        coverage=("session_isolation", "topic_switch", "session_memory", "stress"),
        turns=(
            LongScenarioTurn(
                session="pdf",
                speaker="user",
                content="请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的核心结论。",
                checks=("plan.tool=pdf_analysis", "event.tool=pdf_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="inventory",
                speaker="user",
                content="在 knowledge/E-commerce Data/inventory.xlsx 里查哪些仓库缺货。",
                checks=("plan.tool=structured_data_analysis", "event.tool=structured_data_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="ops",
                speaker="user",
                content="查询黄金价格。",
                checks=("plan.tool=get_gold_price", "event.tool=get_gold_price", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="pdf",
                speaker="user",
                content="第三页讲了什么？",
                checks=("plan.tool=pdf_analysis", "event.tool=pdf_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="inventory",
                speaker="user",
                content="按仓库汇总前五。",
                checks=("plan.tool=structured_data_analysis", "event.tool=structured_data_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="ops",
                speaker="user",
                content="再查北京天气。",
                checks=("plan.tool=get_weather", "event.tool=get_weather", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="pdf",
                speaker="user",
                content="把 PDF 部分压成三条行动项。",
                checks=("response.nonempty",),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="inventory",
                speaker="user",
                content="哪些地方不缺货？",
                checks=("plan.tool=structured_data_analysis", "event.tool=structured_data_analysis", "response.nonempty"),
                force_memory_sync=True,
            ),
        ),
    ),
    LongScenario(
        id="compound-query-task-fanout",
        title="复合查询拆分与任务编排",
        goal="验证 compound query 的子任务拆分、任务记录和事件序列。",
        coverage=("tasks", "tool_route", "rag", "sse"),
        turns=(
            LongScenarioTurn(
                session="main",
                speaker="operator",
                action="set_rag_mode",
                params={"enabled": True},
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="先总结 AI 治理报告第三页，再告诉我 inventory.xlsx 缺货前五，最后查北京天气。",
                checks=("plan.subqueries>=3", "event=subtask_start", "tasks>=3", "response.nonempty"),
                force_memory_sync=True,
            ),
            LongScenarioTurn(
                session="main",
                speaker="user",
                content="只展开第二个子任务，给我仓库和缺货量。",
                checks=("response.nonempty",),
                force_memory_sync=True,
            ),
        ),
    ),
)


SCENARIO_SETS: dict[str, tuple[str, ...]] = {
    "core": (
        "full-workbench-journey",
        "durable-memory-write-and-semantic-recall",
        "multi-session-isolation-and-resume",
    ),
    "extended": tuple(scenario.id for scenario in SCENARIOS),
}


def scenario_map() -> dict[str, LongScenario]:
    return {scenario.id: scenario for scenario in SCENARIOS}
