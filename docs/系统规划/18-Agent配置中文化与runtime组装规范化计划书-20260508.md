# Agent 配置中文化与 Runtime 组装规范化计划书

日期：2026-05-08

## 目标

将编排系统中的 Agent 配置从“直接编辑英文 id / operation id”调整为：

- 后端保留稳定 id，负责运行时解析。
- 后端同时提供中文名称和说明，作为前端展示与选择依据。
- 前端选择配置项时显示中文，写回时仍保存稳定 id。
- 能力权限与 runtime 组装都走同一套 option 结构，避免每个页面各自翻译。

## 范围

首轮覆盖编排系统 Agent 配置页：

- 能力权限：允许操作、阻断操作。
- Runtime 组装：任务模式、运行通道、审批策略、追踪策略。
- 上下文边界：记忆范围、上下文段、输出契约。

## 后端规则

`/orchestration/agents` 在保留旧字段的同时增加结构化 option 字段：

- `operation_options`
- `task_mode_options`
- `runtime_lane_options`
- `memory_scope_options`
- `context_section_options`
- `output_contract_options`
- `approval_policy_options`
- `trace_policy_options`

每个 option 统一包含：

- `id`
- `value`
- `label`
- `description`

## 前端规则

- 文本存储仍使用 id。
- chip / select / 摘要展示使用 `label`。
- 用户点击中文 option 时，写入对应 id。

## 验收

- `npm run build` 通过。
- 后端相关文件 `py_compile` 通过。
- 编排系统的 runtime 和权限选择区不再直接暴露裸 `op.xxx` 作为首要选择文案。
