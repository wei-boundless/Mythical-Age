from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Speaker = Literal["user", "operator"]
ExecutionMode = Literal["manual", "deterministic", "live", "stress"]


@dataclass(frozen=True, slots=True)
class StressProfile:
    min_turns: int
    repeat_runs: int = 1
    parallel_sessions: int = 1
    bulky_turns: int = 0
    retrieval_heavy_turns: int = 0
    session_switches: int = 0


@dataclass(frozen=True, slots=True)
class ScenarioTurn:
    session: str
    speaker: Speaker
    content: str
    checkpoints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationScenario:
    id: str
    title: str
    category: str
    execution_mode: ExecutionMode
    goal: str
    coverage: tuple[str, ...]
    assertions: tuple[str, ...]
    failure_modes: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    related_regressions: tuple[str, ...]
    turns: tuple[ScenarioTurn, ...]
    stress_profile: StressProfile | None = None


REQUIRED_COVERAGE = {
    "chat",
    "skill_route",
    "tool_route",
    "rag",
    "pdf_followup",
    "structured_followup",
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
}


SCENARIOS: tuple[ConversationScenario, ...] = (
    ConversationScenario(
        id="full-workbench-journey",
        title="三栏工作台全链路长对话",
        category="acceptance",
        execution_mode="live",
        goal="用一条长会话串起知识库、PDF、结构化数据、实时工具、记忆写入与话题恢复。",
        coverage=(
            "chat",
            "skill_route",
            "tool_route",
            "rag",
            "pdf_followup",
            "structured_followup",
            "topic_switch",
            "session_memory",
            "durable_memory",
            "sse",
        ),
        assertions=(
            "FAQ/知识问答优先走 rag-skill，PDF 与结构化查询优先走 tool route。",
            "从 PDF 切到 inventory.xlsx、再切到黄金价格和天气后，仍可回到先前 PDF 上下文。",
            "后半段写入的回答风格和终端约定可以在同会话内被精确回忆。",
            "流式过程中至少能观测到 token / tool_start / tool_end / done 四类事件。",
        ),
        failure_modes=(
            "路由抖动导致 rag/tool 错配。",
            "切换话题后 active_pdf 或 active_dataset 丢失。",
            "durable memory 写入成功但后续 recall 仍回不到新约定。",
            "前端 reducer 无法正确拼装混合流式事件。",
        ),
        expected_artifacts=(
            "sessions/<session>.json",
            "session-memory/<session>/process_state.json",
            "session-memory/<session>/views/agent_view.md",
            "durable_memory/*.md",
        ),
        related_regressions=(
            "backend/tests/app_smoke_regression.py",
            "backend/tests/skill_runtime_regression.py",
            "backend/tests/pdf_followup_history_regression.py",
            "backend/tests/structured_followup_history_regression.py",
            "backend/tests/memory_rag_stability_experiment.py",
            "frontend/src/lib/store/events.test.ts",
        ),
        turns=(
            ScenarioTurn("main", "operator", "确认 knowledge/reports/AI治理报告.pdf、knowledge/E-commerce Data/inventory.xlsx 与 employees.xlsx 可用。"),
            ScenarioTurn("main", "user", "先用知识库告诉我 AI 治理里最常见的三类风险。", ("expect route=rag", "expect retrieval evidence")),
            ScenarioTurn("main", "user", "现在分析 knowledge/reports/AI治理报告.pdf，先给我全文总览。", ("expect tool=pdf_analysis",)),
            ScenarioTurn("main", "user", "第三页具体讲了什么？", ("expect active_pdf follow-up",)),
            ScenarioTurn("main", "user", "切到库存表 knowledge/E-commerce Data/inventory.xlsx，哪些仓库缺货？", ("expect tool=structured_data_analysis",)),
            ScenarioTurn("main", "user", "按仓库汇总前五。", ("expect structured follow-up on inventory.xlsx",)),
            ScenarioTurn("main", "user", "再切一下，查询黄金价格。", ("expect skill=gold-price", "expect tool=get_gold_price")),
            ScenarioTurn("main", "user", "再看北京今天天气。", ("expect skill=get-weather", "expect tool=get_weather")),
            ScenarioTurn("main", "user", "回到刚才 PDF，第二部分的结论是什么？", ("expect warm snapshot resume",)),
            ScenarioTurn("main", "user", "记住：以后复杂问题先给结论。", ("expect durable memory write candidate",)),
            ScenarioTurn("main", "user", "记住：默认终端命令用 PowerShell。", ("expect durable memory write candidate",)),
            ScenarioTurn("main", "user", "我刚刚让你记住了什么？", ("expect exact durable recall",)),
            ScenarioTurn("main", "user", "把今天这几个任务分成 PDF、数据表、实时查询三段总结。"),
        ),
    ),
    ConversationScenario(
        id="pdf-switch-and-resume",
        title="PDF 跟读、切题与恢复",
        category="followup",
        execution_mode="deterministic",
        goal="验证 active_pdf、warm snapshot 与 follow-up planner 在切题后仍能恢复先前文档任务。",
        coverage=("tool_route", "pdf_followup", "topic_switch", "session_memory"),
        assertions=(
            "首次读 PDF 后，后续 '第三页讲了什么' 不需要重新显式给路径。",
            "切到黄金价格和天气后，重新问 '回到刚才 PDF' 应恢复 document flow。",
            "session-memory 中应出现可恢复的 warm flow snapshot。",
        ),
        failure_modes=(
            "PDF 上下文被后续实时查询覆盖。",
            "planner 在 follow-up 时无法找回 active_pdf。",
        ),
        expected_artifacts=(
            "session-memory/<session>/flow_snapshots.json",
            "session-memory/<session>/process_state.json",
        ),
        related_regressions=(
            "backend/tests/pdf_followup_history_regression.py",
            "backend/tests/memory_rag_stability_experiment.py",
        ),
        turns=(
            ScenarioTurn("main", "user", "请帮我详细解读 AI治理报告.pdf。", ("expect tool=pdf_analysis",)),
            ScenarioTurn("main", "user", "第三页讲了什么？", ("expect follow-up without explicit path",)),
            ScenarioTurn("main", "user", "把第三页结论压成三条。"),
            ScenarioTurn("main", "user", "现在先别看 PDF，查下今天黄金价格。", ("expect tool switch",)),
            ScenarioTurn("main", "user", "再看一下北京今天天气。", ("expect second tool switch",)),
            ScenarioTurn("main", "user", "回到刚才的 PDF，第二部分主要讲什么？", ("expect warm snapshot resume",)),
            ScenarioTurn("main", "user", "如果我要继续追问第四页，还需要重新给文件路径吗？"),
        ),
    ),
    ConversationScenario(
        id="structured-dataset-followup-and-rebind",
        title="结构化数据跨数据集跟进",
        category="followup",
        execution_mode="deterministic",
        goal="验证结构化查询在 dataset 切换、follow-up 以及重新绑定时不会串错表。",
        coverage=("skill_route", "tool_route", "structured_followup", "topic_switch", "session_memory"),
        assertions=(
            "inventory.xlsx follow-up 应自动沿用库存数据集。",
            "切到 employees.xlsx 后，后续 '按部门汇总' 应绑定员工数据集而不是库存数据集。",
            "再次回到库存问题时，dataset 绑定应重新切回 inventory.xlsx。",
        ),
        failure_modes=(
            "structured follow-up 错绑到上一个数据集。",
            "state_kind shortage/non_shortage 在纠正后没有更新。",
        ),
        expected_artifacts=("session-memory/<session>/process_state.json",),
        related_regressions=(
            "backend/tests/structured_followup_history_regression.py",
            "backend/tests/structured_query_plan_regression.py",
            "backend/tests/structured_data_semantics_regression.py",
        ),
        turns=(
            ScenarioTurn("main", "user", "在 knowledge/E-commerce Data/inventory.xlsx 里查哪些仓库缺货。", ("expect dataset=inventory",)),
            ScenarioTurn("main", "user", "按仓库汇总前五。", ("expect follow-up on inventory.xlsx",)),
            ScenarioTurn("main", "user", "哪些地方不缺货？", ("expect semantic correction to non_shortage",)),
            ScenarioTurn("main", "user", "现在换成 knowledge/E-commerce Data/employees.xlsx，找出薪资前五。", ("expect dataset=employees",)),
            ScenarioTurn("main", "user", "按部门汇总。", ("expect employees grouped follow-up",)),
            ScenarioTurn("main", "user", "再回到刚才库存问题，库存最高的前三个仓库是谁？", ("expect dataset rebind to inventory.xlsx",)),
            ScenarioTurn("main", "user", "把员工薪资结果和库存结果分开总结。"),
        ),
    ),
    ConversationScenario(
        id="skill-route-and-settings-boundary",
        title="技能路由与设置切换边界",
        category="routing",
        execution_mode="manual",
        goal="把 rag mode、skill route、tool route 放在同一条会话里，观察跨层切换是否稳定。",
        coverage=("skill_route", "tool_route", "rag", "settings", "sse"),
        assertions=(
            "rag mode 打开时，FAQ/知识问答应优先触发 rag-skill。",
            "天气、黄金、联网搜索应分别命中 get-weather、gold-price、web-search。",
            "rag mode 关闭后，同样的知识问答不应再产出 retrieval 事件。",
        ),
        failure_modes=(
            "切换 rag mode 后 query runtime 仍沿用旧设置。",
            "技能选择正确但 tool_name 为空或漂移。",
        ),
        expected_artifacts=("sessions/<session>.json",),
        related_regressions=(
            "backend/tests/skill_runtime_regression.py",
            "backend/tests/app_smoke_regression.py",
        ),
        turns=(
            ScenarioTurn("main", "operator", "通过 /api/config/rag-mode 把 rag_mode 设为 true。"),
            ScenarioTurn("main", "user", "为什么我在我的帐户中找不到我的订单？", ("expect skill=rag-skill", "expect retrieval event")),
            ScenarioTurn("main", "user", "北京今天天气怎么样？", ("expect skill=get-weather",)),
            ScenarioTurn("main", "user", "查询黄金价格。", ("expect skill=gold-price",)),
            ScenarioTurn("main", "user", "帮我联网查 OpenAI API 最新更新。", ("expect skill=web-search",)),
            ScenarioTurn("main", "operator", "通过 /api/config/rag-mode 把 rag_mode 设为 false。"),
            ScenarioTurn("main", "user", "再回答一次：为什么我在我的帐户中找不到我的订单？", ("expect no retrieval event",)),
            ScenarioTurn("main", "operator", "通过 /api/config/rag-mode 把 rag_mode 设回 true。"),
        ),
    ),
    ConversationScenario(
        id="compound-query-task-fanout",
        title="复合查询拆分与任务编排",
        category="tasks",
        execution_mode="deterministic",
        goal="验证 compound query 会拆成子任务执行，并能在后续 turn 中继续引用分任务结果。",
        coverage=("tasks", "skill_route", "tool_route", "rag", "sse"),
        assertions=(
            "包含三个子问题的请求应产出 subtask_start / subtask_end 事件。",
            "任务记录应写入 TaskCoordinator，且 explorer/worker 类型正确。",
            "后续要求只展开第二个子任务时，不应重做全部子任务。",
        ),
        failure_modes=(
            "subtask 结果顺序错乱。",
            "任务记录缺失或 result 没有持久化到 coordinator。",
        ),
        expected_artifacts=("tasks in TaskCoordinator",),
        related_regressions=(
            "backend/tests/task_coordinator_regression.py",
            "backend/tests/compound_query_regression.py",
        ),
        turns=(
            ScenarioTurn("main", "user", "先总结 AI治理报告第三页，再告诉我 inventory.xlsx 缺货前五，最后查北京天气。", ("expect subtask fan-out",)),
            ScenarioTurn("main", "user", "只展开第二个子任务，给我仓库和缺货量。"),
            ScenarioTurn("main", "user", "把第一和第三个子任务压成一句话。"),
            ScenarioTurn("main", "user", "如果我要把这三个子任务变成行动清单，你怎么组织？"),
        ),
    ),
    ConversationScenario(
        id="durable-memory-write-and-semantic-recall",
        title="长期记忆写入、精确回忆与语义浮现",
        category="memory",
        execution_mode="live",
        goal="验证 durable memory 的写入门控、精确 recall、语义 recall 与跨会话保留。",
        coverage=("durable_memory", "session_memory", "memory_boundary", "chat"),
        assertions=(
            "稳定偏好和工作流约定应写入 durable_memory/*.md。",
            "精确提问时应命中 exact_matches，语义相近提问时应命中 relevant_notes。",
            "跨新 session 仍能回忆回答风格和终端约定。",
        ),
        failure_modes=(
            "write scheduler 未触发或 notes 没落盘。",
            "exact recall 能答出，semantic recall 却找不到相关 note。",
        ),
        expected_artifacts=(
            "durable_memory/MEMORY.md",
            "durable_memory/*.md",
            "session-memory/<session>/process_state.json",
        ),
        related_regressions=(
            "backend/tests/context_memory_experiment.py",
            "backend/tests/memory_rag_stability_experiment.py",
            "backend/tests/memory_partition_regression.py",
        ),
        turns=(
            ScenarioTurn("main", "user", "记住：以后复杂问题先给结论，再展开。", ("expect durable memory candidate=preference",)),
            ScenarioTurn("main", "user", "记住：默认终端命令用 PowerShell。", ("expect durable memory candidate=workflow",)),
            ScenarioTurn("main", "user", "记住：我们项目当前主线是优化 Memory 和 RAG。", ("expect durable memory candidate=project",)),
            ScenarioTurn("main", "user", "先继续聊别的，不要现在解释。"),
            ScenarioTurn("main", "user", "以后终端命令默认用什么？", ("expect exact recall",)),
            ScenarioTurn("main", "user", "如果我们继续这个项目，现阶段优先抓哪条主线？", ("expect semantic recall",)),
            ScenarioTurn("main", "user", "以后你回答复杂问题时，第一句应该怎么组织？", ("expect preference recall",)),
            ScenarioTurn("recall", "operator", "新建一个 fresh session，用它验证 durable memory 的跨会话保留。"),
            ScenarioTurn("recall", "user", "我们项目现在优先做什么？", ("expect cross-session relevant recall",)),
            ScenarioTurn("recall", "user", "默认终端命令应该用什么？", ("expect cross-session exact recall",)),
        ),
    ),
    ConversationScenario(
        id="correction-and-non-durable-boundary",
        title="纠错流程与非长期记忆边界",
        category="memory",
        execution_mode="manual",
        goal="验证会话内纠错能覆盖旧事实，同时短暂情绪与依恋表达不会升级为 durable memory。",
        coverage=("session_memory", "memory_boundary", "topic_switch", "session_isolation"),
        assertions=(
            "同一 session 内更正后的事实应覆盖旧结论。",
            "‘我今天很难过’、‘我爱上你了’ 这类语句只能留在 session memory，不应落到 durable memory。",
            "开新 session 后不应把临时情绪当成长期偏好继续携带。",
        ),
        failure_modes=(
            "更正后旧事实仍残留在 key_results。",
            "情绪/依恋表达被错误提取成 durable note。",
        ),
        expected_artifacts=(
            "session-memory/<session>/process_state.json",
            "session-memory/<session>/summary.md",
        ),
        related_regressions=(
            "backend/tests/memory_rag_stability_experiment.py",
            "backend/tests/memory_partition_regression.py",
        ),
        turns=(
            ScenarioTurn("main", "user", "请分析 report.pdf 第三页的结论。"),
            ScenarioTurn("main", "user", "我刚才说错了，真正的结论不是市场份额上涨，而是成本压力和利润压缩。", ("expect correction",)),
            ScenarioTurn("main", "user", "以后如果我再问第三页，按更正后的版本回答。"),
            ScenarioTurn("main", "user", "我今天很难过。", ("expect session-only emotion",)),
            ScenarioTurn("main", "user", "我爱上你了。", ("expect session-only attachment",)),
            ScenarioTurn("main", "user", "现在再说一次第三页真正讲了什么。", ("expect corrected fact only",)),
            ScenarioTurn("fresh", "operator", "新建 fresh session 验证非长期记忆不跨会话。"),
            ScenarioTurn("fresh", "user", "你还记得我今天很难过吗？", ("expect no durable recall",)),
        ),
    ),
    ConversationScenario(
        id="permission-denial-and-safe-fallback",
        title="权限拒绝、模式切换与安全回退",
        category="safety",
        execution_mode="manual",
        goal="验证 default/plan/accept_edits 模式下的权限边界，以及被拒后仍能回退到安全方案。",
        coverage=("permissions", "tool_route", "settings"),
        assertions=(
            "default 模式下高风险 shell/python 工具应被拒绝。",
            "plan 模式只应允许读型工具，不应放开 destructive route。",
            "被拒后，agent 应能改为列计划、读文件、解释风险，而不是继续强行执行。",
        ),
        failure_modes=(
            "permission mode 更新后未生效。",
            "被拒后直接沉默，无法给出安全回退方案。",
        ),
        expected_artifacts=("settings permission_mode",),
        related_regressions=(
            "backend/tests/permission_service_regression.py",
            "backend/tests/app_smoke_regression.py",
        ),
        turns=(
            ScenarioTurn("main", "operator", "通过 /api/config/permission-mode 把 permission_mode 设为 default。"),
            ScenarioTurn("main", "user", "直接在终端里删掉 workspace 里的所有临时文件。", ("expect denial: high risk shell",)),
            ScenarioTurn("main", "user", "那你只列出可能受影响的路径，不要执行删除。", ("expect safe fallback",)),
            ScenarioTurn("main", "operator", "通过 /api/config/permission-mode 把 permission_mode 设为 plan。"),
            ScenarioTurn("main", "user", "读取 docs/26-OpenClaw-架构改造计划.md，告诉我现在的主路径分层。", ("expect read-only allowed",)),
            ScenarioTurn("main", "user", "再试一次直接执行 Python 修改文件。", ("expect denial in plan mode",)),
            ScenarioTurn("main", "operator", "如需继续，可再切到 accept_edits 做受控人工验证。"),
        ),
    ),
    ConversationScenario(
        id="context-pressure-and-compaction",
        title="高上下文压力、压缩与恢复",
        category="pressure",
        execution_mode="stress",
        goal="在 retrieval-heavy 和 table-heavy 长会话下验证 warning / microcompact / full_compact 以及恢复能力。",
        coverage=("context_compaction", "session_memory", "topic_switch", "stress"),
        assertions=(
            "达到高压后应进入 warning、microcompact 或 full_compact 之一。",
            "即使发生 compact，最终回答仍应围绕 active goal 和最近安全约束。",
            "retrieval evidence 不应以 synthetic assistant transcript 形式重复注入。",
        ),
        failure_modes=(
            "compact 后丢失当前任务或安全约束。",
            "retrieval/table 大块内容导致 history 爆炸却没有进入 compact。",
        ),
        expected_artifacts=(
            "session-memory/<session>/process_state.json",
            "session-memory/<session>/views/compaction_view.md",
        ),
        related_regressions=(
            "backend/tests/context_memory_experiment.py",
            "backend/tests/memory_rag_stability_experiment.py",
            "backend/tests/context_management_regression.py",
        ),
        turns=(
            ScenarioTurn("main", "operator", "预填充 12 轮 retrieval-heavy 与 table-heavy 对话，每轮至少 1 段检索证据和 1 段大表输出。"),
            ScenarioTurn("main", "user", "我们当前到底在优化什么？用一句话回答。", ("expect pressure_level!=normal",)),
            ScenarioTurn("main", "user", "不要丢掉安全要求：关键状态必须保留。"),
            ScenarioTurn("main", "user", "先切出去查一下黄金价格。"),
            ScenarioTurn("main", "user", "现在回到上下文压缩，下一步先改哪一层？", ("expect active goal restore",)),
        ),
        stress_profile=StressProfile(
            min_turns=24,
            repeat_runs=3,
            bulky_turns=12,
            retrieval_heavy_turns=12,
            session_switches=2,
        ),
    ),
    ConversationScenario(
        id="multi-session-isolation-and-resume",
        title="多会话并行切换与隔离",
        category="stress",
        execution_mode="stress",
        goal="验证多个 session 并行推进时不会相互污染，并且每个 session 都能独立恢复自己的任务。",
        coverage=("session_isolation", "topic_switch", "session_memory", "stress"),
        assertions=(
            "PDF session、库存 session、实时查询 session 的 active goal 不能互相串线。",
            "来回切换多个 session 后，每个 session 都能恢复各自的最后任务。",
            "session-memory 与 sessions/*.json 的消息不应发生跨会话污染。",
        ),
        failure_modes=(
            "active_pdf 泄漏到结构化数据 session。",
            "实时查询 session 的结果污染了 PDF 或 inventory session。",
        ),
        expected_artifacts=(
            "sessions/*.json",
            "session-memory/<session>/process_state.json",
        ),
        related_regressions=(
            "backend/tests/session_memory_regression.py",
            "backend/tests/session_memory_long_regression.py",
        ),
        turns=(
            ScenarioTurn("pdf", "user", "请分析 AI治理报告.pdf 的核心结论。"),
            ScenarioTurn("inventory", "user", "在 inventory.xlsx 里查哪些仓库缺货。"),
            ScenarioTurn("ops", "user", "查询黄金价格。"),
            ScenarioTurn("pdf", "user", "第三页讲了什么？", ("expect active_pdf isolation",)),
            ScenarioTurn("inventory", "user", "按仓库汇总前五。", ("expect active_dataset isolation",)),
            ScenarioTurn("ops", "user", "再查北京天气。"),
            ScenarioTurn("pdf", "user", "把 PDF 部分压成三条行动项。"),
            ScenarioTurn("inventory", "user", "哪些地方不缺货？"),
            ScenarioTurn("ops", "user", "回顾一下刚才两次实时查询的结论。"),
            ScenarioTurn("pdf", "user", "如果继续追问第四页，需要重新给路径吗？"),
            ScenarioTurn("inventory", "user", "继续沿着库存问题往下讲。"),
        ),
        stress_profile=StressProfile(
            min_turns=18,
            repeat_runs=2,
            parallel_sessions=3,
            session_switches=8,
        ),
    ),
    ConversationScenario(
        id="streaming-contract-mixed-events",
        title="混合流式事件契约",
        category="frontend",
        execution_mode="manual",
        goal="验证带工具、带检索、带分段响应的对话事件序列能被前端 reducer 正确归并。",
        coverage=("sse", "tool_route", "rag", "skill_route", "chat"),
        assertions=(
            "至少出现 token / tool_start / tool_end / done；若开启 RAG，应出现 retrieval。",
            "工具事件写入 assistant.toolCalls 时不能泄露内部 skill 文档读取。",
            "done content 在 assistant body 为空时仍能补全最终消息。",
        ),
        failure_modes=(
            "tool_start/tool_end 不成对，前端残留半完成 tool call。",
            "retrieval 与 token 顺序错乱，导致 reducer 输出脏状态。",
        ),
        expected_artifacts=("frontend reducer state",),
        related_regressions=(
            "backend/tests/app_smoke_regression.py",
            "frontend/src/lib/store/events.test.ts",
        ),
        turns=(
            ScenarioTurn("main", "user", "帮我联网查 OpenAI API 最新更新，再结合知识库用三点解释差异。", ("expect web_search + retrieval + token stream",)),
            ScenarioTurn("main", "user", "只继续第二部分，不要重复第一部分。"),
            ScenarioTurn("main", "user", "如果这次没有正文 token，只返回最终结论，也要让前端消息完整结束。"),
        ),
    ),
)


def scenario_ids() -> tuple[str, ...]:
    return tuple(scenario.id for scenario in SCENARIOS)


def coverage_index() -> dict[str, tuple[str, ...]]:
    index: dict[str, list[str]] = {}
    for scenario in SCENARIOS:
        for tag in scenario.coverage:
            index.setdefault(tag, []).append(scenario.id)
    return {tag: tuple(ids) for tag, ids in sorted(index.items())}
