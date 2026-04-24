---
name: structured-data-analysis
metadata:
  display_name: 结构化数据分析
  allowed_tools:
    - structured_data_analysis
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
  preferred_route: tool
  activation_policy: model_visible
  context_mode: isolated
  route_authority: candidate_only
  forbidden_routes:
    - rag
  routing_hints:
    - 表格
    - Excel
    - CSV
    - 前五
    - 排名
    - 汇总
    - 缺货
    - 库存
  examples:
    - 销售前五的有哪些
    - 薪水最高的员工是谁
    - 按地区汇总订单总额
    - 从我的数据库中查询哪些商品库存不足
description: 用于本地 Excel、CSV、JSON 等结构化数据文件的通用分析场景，如统计、排序、分组汇总、Top N 和记录查询。
---

# 结构化数据分析 Skill

## 角色

这是一个数据任务工作流契约。它负责承接“可计算的数据问题”，并把执行交给 `structured_data_analysis`。

## 服务的任务

- `dataset_schema_inspect`
- `dataset_row_count`
- `dataset_filter`
- `dataset_summary`
- `dataset_top_n`
- `dataset_extreme_record`
- `dataset_group_summary`
- `dataset_inspect`

## 服务的数据源

- `dataset`

## 使用原则

1. 表格、Excel、CSV、JSON 分析问题优先走 `structured_data_analysis`。
2. 先识别任务类型，再让工具自动定位数据集。
3. 输出时先给结论，再给关键依据和数据源。

## 辅助资料

- `references/excel_reading.md`
- `references/excel_analysis.md`

## 不要这样做

- 不要把表格问题交给普通 RAG。
- 不要在已有专用工具时临时用 `python_repl` 代替。
- 不要把预览前几行误当成完整数据集。
