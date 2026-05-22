# Agent Runtime Mode Config Plan 2026-05-23

## 目标

把编排系统里原本暴露给用户的 `allowed_runtime_lanes` 清单收敛成固定的 Agent 运行模式配置：

- role：角色模式
- standard：标准模式
- professional：专家模式
- custom：自定义模式，只承载当前手工运行 lane；不保存为新模式，不生成模式库，不生成默认 prompt

系统模式只代表运行配置集合，不默认生成 prompt。Agent 的 prompt 仍来自 Agent 身份、任务图节点、专业节点配置或具体任务契约。

## 问题依据

- 前端主会话已经有三种模式投影，但编排配置页仍直接展示运行场景白名单，用户会看到一堆 lane，难以理解。
- 后端 `AgentRuntimeProfile` 过去主要保存 `allowed_runtime_lanes`，和前端三模式配置存在重复表达。
- `allowed_runtime_lanes` 是运行准入字段，`blocked_operations` 是具体操作拦截字段；直接让用户维护 lane 清单容易和模式配置打架。

## 实施步骤

1. 在后端建立固定四模式归一化工具：由 `enabled_runtime_modes/default_runtime_mode` 派生 runtime lane、interaction mode、recipe、execution strategy。
2. 扩展 `AgentRuntimeProfile` 与 API payload，保存模式配置，同时继续输出兼容的 `allowed_runtime_lanes` 供现有运行准入使用。
3. 改造前端编排配置页，把“可承接运行场景权限”改成“运行模式配置”，系统模式直接选择并二次确认，自定义模式才显示手工 lane。
4. 同步前端类型、摘要、诊断文案和保存 payload，避免 mode/lane 两套事实源互相覆盖。
5. 增加/调整回归测试，确认固定四模式不会生成默认 prompt，且模式与 lane 派生一致。
