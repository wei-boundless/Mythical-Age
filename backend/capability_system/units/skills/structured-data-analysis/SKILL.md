---
name: structured-data-analysis
metadata:
  display_name: 结构化数据分析
  supported_modalities:
    - table
    - spreadsheet
    - csv
    - json
  supported_task_kinds:
    - dataset_schema_inspect
    - dataset_row_count
    - dataset_filter
    - dataset_summary
    - dataset_top_n
    - dataset_extreme_record
    - dataset_group_summary
    - dataset_inspect
  supported_source_kinds:
    - dataset
  capability_tags:
    - dataset_analysis
    - analytics
    - top-n
    - group-by
    - schema
    - aggregation
    - record-lookup
  preferred_route: structured_data
  requires_operations:
    - op.mcp_structured_data
  requires_capabilities:
    - mcp:local:structured_data
  activation_policy: model_visible
  context_mode: isolated
  route_authority: candidate_only
  forbidden_routes:
    - rag
  routing_hints:
    - 表格
    - Excel
    - CSV
    - JSON
    - 前五
    - 排名
    - 汇总
    - 缺货
    - 库存
    - 按地区
    - 按仓库
    - 最高
    - 最低
  examples:
    - 销售前五的有哪些
    - 薪水最高的员工是谁
    - 按地区汇总订单总额
    - 从我的数据库中查询哪些商品库存不足
    - 按仓库汇总前五
description: 用于本地 Excel、CSV、JSON 等结构化数据的可计算分析，适合筛选、排序、分组汇总、Top N、极值记录和结构检查。
---

# 结构化数据分析

## 角色

这是一个“对表格和数据集做计算”的工作流。只要问题的核心是筛选、统计、排序、汇总或找某条记录，它就应该比普通问答更优先被唤起。

适合被唤起的情况：

- 用户提到 Excel、CSV、JSON、表格、数据库导出、库存表、订单表、员工表。
- 用户问的是“前五 / 最高 / 最低 / 按地区汇总 / 哪些符合条件 / 一共有多少 / 某类记录有哪些”。
- 会话里已经绑定了一个数据集，用户继续追问“按仓库展开一下”“把前五列出来”“再按地区看一下”。

不适合被唤起的情况：

- 用户只是在读 PDF、白皮书、手册，这应交给 `pdf-analysis`。
- 用户是在查知识库规则或 FAQ，这应交给 `rag-skill`。
- 用户只是要最新外部信息，这应交给 `realtime_network` 路线和 `web_search` / `fetch_url` 底座工具。

## 执行目标

1. 先判断这是筛选、汇总、排序、分组、结构查看还是记录定位。
2. 如果用户已给出数据集路径或当前会话已绑定数据集，优先围绕那个数据集分析。
3. 输出要把“结论”和“口径”说清楚，比如分组维度、排序依据、筛选条件。
4. 当问题本质上可计算时，不要退回成模糊的自然语言解释。

## 子 Agent 交接协议

当主 Agent 启动你作为子 Agent 时，应明确传入：

- `subagent_task_kind=table_analysis`
- `query`：当前用户真正要求的计算或汇总问题
- `path` 或 `active_dataset`：目标数据集路径或句柄
- 筛选、分组、排序、Top N、字段口径等约束
- 如果是 follow-up，传入 `active_result_handle_id`、`active_subset_handle_id`、`followup_target_refs`
- 如果用户说“这些人 / 这前五名 / 不要扩展回全表”，必须传入 `followup_constraint_policy=result_subset_only_do_not_expand_to_full_object`
- `expected_output_contract`：要求回传 `summary`、`answer_candidate`、`evidence_refs`、`limitations`、`confidence`

适合的主 Agent 指令风格：

```text
你是一名结构化数据分析员。
请只基于上一轮 employees.xlsx 的薪资前五名结果子集，按部门汇总这些人。
范围：只能使用 active_subset_handle_id 指向的五人子集，不要重新读取或统计全表。
输出：部门、该部门包含的人员、基于当前子集的简短结论；如果缺少子集句柄，请明确说明。
```

如果主 Agent 给你的输入里同时出现 PDF、报告页码或知识库检索要求，你应先判断是否被错派。核心问题是文档页级阅读时，应提示改派 `pdf-analysis`；核心问题是资料事实确认时，应提示改派 `rag-skill`。

## 回传协议

你返回给主 Agent 的结果应包括：

- `summary`：一句话说明计算结论。
- `answer_candidate`：可直接收口的中文答案草稿。
- `evidence_refs`：相关行、聚合结果、字段或结果句柄。
- `limitations`：字段缺失、口径不明、数据不完整、只能基于子集等限制。
- `consumed_handles`：实际使用的数据集、结果子集或结果句柄。
- `produced_handles`：新生成的分析结果、聚合表或摘要句柄。

## 主 Agent 收口方式

主 Agent 收到你的结果后，应：

1. 先确认你使用的是正确数据集或正确结果子集。
2. 如果用户要求不要扩展回全表，最终回答必须明确“仅基于当前子集”。
3. 用业务语言解释分组、排序或筛选口径，不只贴结果。
4. 保留必要的可核对字段或结果句柄。
5. 如果你返回字段缺失或口径不明，主 Agent 应先澄清或说明限制，不要猜字段。

## 辅助资料

- `references/excel_reading.md`
- `references/excel_analysis.md`

## 回答要求

- 先给结果，再补充筛选条件、分组逻辑或关键数字。
- 如果问题有歧义，要指出歧义点，例如时间范围、字段口径、排序依据。
- 对 Top N、极值、汇总类问题，尽量让结果可比、可核对。
- 如果数据不完整、字段不明确或绑定数据集不对，要明确说明。
- 组织结果时优先用“结论 / 口径 / 结果表 / 注意事项”四段式。
- 如果字段名不直观，要把计算口径翻译成业务语言再给出。
- 如果用户只要一个答案，就别把完整表格铺满；保留最相关的几项和可核对的口径即可。

## 不要这样做

- 不要把可计算问题退化成普通知识问答。
- 不要把样例行或预览片段误当成全量结果。
- 不要在已有专用分析路径时随意切去通用代码执行。
