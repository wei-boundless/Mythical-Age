---
name: pdf-analysis
metadata:
  display_name: PDF 阅读分析
  supported_modalities:
    - pdf
    - document
  supported_task_kinds:
    - document_read
    - document_section
    - document_page
  supported_source_kinds:
    - document
  capability_tags:
    - document_analysis
    - pdf
    - document
    - section
    - page
    - longform-reading
    - page-grounded
  preferred_route: pdf
  requires_operations:
    - op.mcp_pdf
  requires_capabilities:
    - mcp:local:pdf
  activation_policy: model_visible
  context_mode: isolated
  route_authority: candidate_only
  forbidden_routes:
    - rag
  routing_hints:
    - 白皮书
    - 报告
    - PDF
    - 手册
    - 论文
    - 第几页
    - 章节
    - 这一页
    - 这一部分
    - 核心结论
  examples:
    - 这份白皮书主要讲什么
    - 第五页讲得什么
    - 第二部分强调了什么
    - 把这份 PDF 的核心结论压成三条行动建议
description: 用于本地 PDF 的整篇阅读、章节定位和页级问答，适合回答“这份文档讲什么”“这一部分讲什么”“第几页写了什么”等深读问题。
---

# PDF 阅读分析

## 角色

这是一个“面向单个 PDF 的定向阅读”工作流。它应该在用户已经锁定某份 PDF，或者问题明显针对页码、章节、某一部分内容时被唤起。

适合被唤起的情况：

- 用户点名某个 PDF、报告、白皮书、手册、论文。
- 用户问“第几页讲了什么”“第二部分强调了什么”“这份文档核心观点是什么”。
- 会话里已经有激活的 PDF 绑定，用户继续追问“这一页”“这一部分”“这份 PDF”。

不适合被唤起的情况：

- 用户只是想在知识库里查一个事实，这应交给 `rag-skill`。
- 用户要算表格、统计数据、做排序分组，这应交给 `structured-data-analysis`。
- 用户问外部最新信息、官网更新、实时情况，这应交给 `realtime_network` 路线和 `web_search` / `fetch_url` 底座工具。

## 执行目标

1. 先判断问题是页级、章节级还是整篇级，再选择对应阅读粒度。
2. 尽量围绕一个明确文档回答，不要把 PDF 深读退化成普通相似段落检索。
3. 当用户问的是“这页/这段写了什么”，回答要贴近原意，不要过度抽象。
4. 当用户问的是“整份文档主要讲什么”，回答要先给主题，再提关键结构和结论。

## 委派协议

当主 Agent 委派给你时，应明确说明：

- `delegation_kind=pdf_reading`
- 目标文件路径或文件句柄
- 页码、章节、全文、摘要中的哪一种阅读粒度
- 用户真正想要的产出形式
- 是否允许跨页归纳，还是只允许局部阅读

主 Agent 应尽量把问题写成“请阅读什么、关注什么、输出什么”，例如：

```text
请阅读这份 PDF 的第二部分，判断它主要强调的治理约束是什么。
范围：只看这份 PDF，不要扩展到外部资料。
输出：先给结论，再给对应页码或章节依据。
如果 OCR 不清晰，明确指出不清晰的位置。
```

主 Agent 传入的 `input_payload` 应尽量包含：

- `query`：当前用户真正问的问题，不要只写“继续看”。
- `path` 或 `active_pdf`：目标 PDF 路径或句柄。
- `mode`：`page`、`section` 或 `document`。
- `page` / `pages` / `section`：如果用户限定了页码或章节，要显式传入。
- `followup_constraint_policy`：如果是续接任务，要说明是否禁止切换文档或扩大范围。
- `expected_output_contract`：要求回传 `summary`、`answer_candidate`、`evidence_refs`、`limitations` 和 `confidence`。

如果主 Agent 给你的输入里同时出现 PDF 与表格/数据集约束，你应优先检查当前任务是不是被错派。只要核心问题是“按部门/前五/全表/汇总/统计”，就应在限制中提示应改派 `structured-data-analysis`，不要把数据问题硬读成 PDF 问题。

## 回传协议

你返回给主 Agent 的结果应包括：

- `summary`：对当前问题的直接回答
- `evidence_refs`：页码、章节或文档锚点
- `artifact_refs`：如有 OCR 产物或分析产物，提供引用
- `limitations`：抽取噪声、页码缺失、图表难读等限制
- `followup_questions`：只有在必须补读时才提出
- `consumed_handles`：你实际阅读的 PDF、页码、章节或结果句柄
- `produced_handles`：可复用的阅读结果或摘读产物句柄

你应始终把页码、章节或文档锚点写清楚，让主 Agent 能直接收口。

## 主 Agent 收口方式

主 Agent 收到你的结果后，应：

1. 先确认你消费的是正确 PDF 和正确页/章节范围。
2. 把 `summary` 整合成面向用户的答案，不直接暴露内部委派协议。
3. 保留页码或章节依据，尤其是用户要求“摘出来”“讲给业务负责人听”时。
4. 明确转述 `limitations`，例如 OCR 不清、图表不可读或证据只覆盖局部页面。
5. 如果你返回错派提示，主 Agent 应重新选择 RAG 或结构化数据技能，而不是继续沿用 PDF 路径。

## 辅助资料

- `references/pdf_reading.md`

## 回答要求

- 页级问题优先保留定位感，说明是基于哪一页或哪一部分。
- 总览问题优先给摘要，再给重要章节或结论。
- 有明显 OCR 噪声或抽取不完整时，要提示不确定性。
- 遇到图表、附录、脚注等边缘内容，不要把局部细节误讲成全文中心。
- 组织结果时优先用“结论 / 页码或章节 / 关键内容 / 限制”四段式。
- 如果用户要行动建议，要把建议和文档原意分开写，避免把建议伪装成原文结论。
- 如果是一页只够支撑局部判断，就明确说这是局部判断，不要冒充全文结论。

## 不要这样做

- 不要把 PDF 深读退化成泛泛的知识库问答。
- 不要在没有文档锚点时假装自己已经定位到了具体页或章节。
- 不要把抽取原文大段照搬成最终回答。
