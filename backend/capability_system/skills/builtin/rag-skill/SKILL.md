---
name: rag-skill
metadata:
  display_name: 知识库问答
  supported_modalities:
    - text
    - document
    - knowledge
  supported_task_kinds:
    - knowledge_lookup
    - faq_explanation
  supported_source_kinds:
    - knowledge_base
  capability_tags:
    - knowledge_lookup
    - retrieval
    - local-knowledge
    - faq
    - grounded-answer
    - citation-aware
  preferred_route: rag
  requires_operations:
    - op.mcp_retrieval
  requires_capabilities:
    - mcp:local:retrieval
  forbidden_routes:
    - tool
  routing_hints:
    - 知识库
    - 本地资料
    - 本地文档
    - 内部资料
    - 查资料
    - 查一下
    - 根据资料
    - FAQ
    - 为什么
    - 解释一下
    - 说明一下
  examples:
    - 从本地知识库里查一下三一重工前三大股东
    - 根据内部资料解释一下这个产品的退款规则
    - 为什么我在我的帐户中找不到我的订单
    - 帮我从知识库里确认这个功能是否支持批量导出
description: 面向本地知识库、FAQ 和内部资料的检索问答工作流，适合做基于现有材料的事实确认、规则解释和可追溯回答。
---

# 知识库问答

## 角色

这是一个“基于已有资料回答”的工作流。它的任务不是自由发挥，而是优先从本地知识库、FAQ 和内部文档中找到依据，再给出可追溯的结论。

适合被唤起的情况：

- 用户明确提到知识库、本地资料、内部文档、FAQ、帮助中心、规则说明。
- 问题本质上是在确认一个事实、解释一个规则、核对一个产品能力、说明一个常见故障原因。
- 回答需要“根据现有材料来讲”，而不是依赖最新外部信息或临时计算。

不适合被唤起的情况：

- 用户要的是某个 PDF 的页级/章节级阅读，这应该交给 `pdf-analysis`。
- 用户要的是 Excel/CSV/JSON 的筛选、排序、汇总，这应该交给 `structured-data-analysis`。
- 用户问的是实时新闻、官网最新更新、当前行情、今天/今年是否还在发生，这应该交给 `realtime_network` 路线和 `web_search` / `fetch_url` 底座工具。

## 执行目标

1. 先确认问题是否真的需要“从已有资料中找答案”，再进入检索。
2. 优先召回最可能直接回答问题的条目，而不是泛化搜索大段相近内容。
3. 输出时先给结论，再给依据；如果依据不足，要明确说“不足以确认”。
4. 当问题像 FAQ 时，回答要简洁直接；当问题像规则说明时，要把适用条件一起说清楚。

## 子 Agent 交接协议

当主 Agent 需要你执行检索时，应把任务写成“可直接执行”的子 Agent 交接说明，而不是笼统地说“查一下”。

主 Agent 应传入：

- `subagent_task_kind=evidence_lookup`
- 用户原问题
- 期望回答范围
- 已知知识库锚点或文档线索
- 若有，当前绑定的资料名、主题词、路径线索或 follow-up 约束
- `expected_output_contract`：要求回传 `summary`、`answer_candidate`、`evidence_refs`、`limitations` 和 `confidence`

适合的主 Agent 指令风格：

```text
请检索本地知识库，围绕“AI 治理最常见的三类风险”找证据。
范围：只基于本地知识库与已索引材料。
要求：先找最直接的证据，再用业务语言概括。
输出：风险名称、业务解释、证据来源、如果证据不足请明确说明。
```

如果用户的问题其实是 PDF 页级阅读、表格统计或最新外部信息，你应明确回传“这不是知识库检索的最佳入口”，并提示主 Agent 改派对应技能。

## 主 Agent 收口方式

主 Agent 收到你的结果后，应把它当成证据包，而不是直接原样转发。主 Agent 需要：

1. 先判断 `limitations` 是否影响最终结论。
2. 用用户能懂的话整合 `summary` 和 `answer_candidate`。
3. 保留关键证据锚点，但不暴露内部检索工具名。
4. 如果 `evidence_refs` 为空或置信度低，应明确说“现有知识库证据不足”，不要补写成确定结论。

## 回传协议

你返回给主 Agent 的结果应保持稳定结构：

- `summary`：一句话结论
- `evidence_refs`：可引用的证据线索
- `artifact_refs`：如有，可回传产物引用
- `limitations`：证据不足、覆盖范围有限、索引不全等限制
- `followup_questions`：只有在必须补充上下文时才提出
- `consumed_handles`：你实际使用的知识库、文档或检索锚点
- `produced_handles`：如生成了可复用结果，回传结果句柄

回传内容应满足：

- 先结论，后证据
- 证据不足就直接说不足，不要编造补全
- 不暴露内部工具名、路由名、协议名
- 如果只能给出近似判断，要明确标注不确定性
- 如果判断出任务不属于知识库检索，应在 `limitations` 中写明推荐的能力域，例如 `requires_pdf_reading` 或 `requires_structured_data_analysis`

## 回答要求

- 结论优先，不要先铺陈检索过程。
- 尽量保留来源感，比如“根据知识库说明”或“从现有资料看”。
- 有冲突证据时，不要强行合并，要说明冲突点。
- 没有足够依据时，不要补齐想象内容。
- 组织结果时优先用“结论 / 依据 / 限制 / 下一步”四段式。
- 如果能给业务语言翻译，就把术语翻译成业务能懂的话，但不要丢掉证据锚点。
- 如果证据分散，先合并成一个清楚判断，再列出最关键的两三条证据，不要堆片段。

## 不要这样做

- 不要把“本地资料问答”退化成无依据的泛泛回答。
- 不要把实时外部问题硬解释成知识库问题。
- 不要把 PDF 深读、表格分析、代码阅读临时塞进这条链里兜底。
