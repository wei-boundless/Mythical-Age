# Agent 装配页面重构计划

## 背景

编排系统的 Agent Runtime Studio 同时承担 Agent 名册、运行档案、模型配置、上下文记忆、协作资格和 Agent 组管理。旧页面已经接入后端 catalog，但目录层级和详情层级混在一起：自定义 Agent 组、无组 Agent、Agent 配置 tab、分组成员管理共用一套上下文，用户很难判断当前是在配置 Agent 本体还是配置 Agent 组。

## 后端事实源

- `/orchestration/agents` 返回 Agent 主数据、`runtime_profile`、`agent_groups` 和运行选项。
- Agent 分类来自 `agent_category`：`main_agent`、`builtin_agent`、`custom_agent`。
- Agent 组来自 `agent_groups`，成员字段是 `member_agent_ids`。
- 运行配置落在 `AgentRuntimeProfile`，包括运行场景、操作准入、上下文、记忆、模型、协作白名单。
- 分组只维护组身份、协调 Agent 和成员关系，不直接承载单个 Agent 的运行权限。

## 目标结构

1. 左侧目录保留三类 Agent：
   - 主 Agent：主会话入口与最终整合。
   - 内置 Agent：系统内置专业/管理 Agent。
   - 子 Agent：自定义/worker Agent。
2. 子 Agent 保持 Agent 分组：
   - 分组视图显示组列表和组内成员。
   - 未分组视图显示尚未进入任何组的子 Agent。
3. 右侧工作区分清层级：
   - 选择 Agent 时，只显示 Agent 装配层：身份、运行权限、模型、上下文记忆、协作、总览、诊断。
   - 选择 Agent 组时，只显示组装配层：组身份、协调者、成员加入/移除。
4. 配置字段按后端实际结构调整：
   - Agent 身份：`AgentDescriptor` 字段。
   - 运行档案：`AgentRuntimeProfile` 字段。
   - 模型运行：`runtime_profile.model_profile`。
   - 分组：`AgentGroup` 字段。

## 实施步骤

1. 引入明确的装配选择状态，区分 `agent` 与 `group`。
2. 重构 `OrchestrationDirectoryRail`，输出分类、分组、成员和未分组子 Agent 的稳定层级。
3. 调整 `OrchestrationView` 的选择逻辑，使分类切换、组切换、Agent 切换不会互相污染。
4. 增强右侧顶部摘要，展示当前装配对象类型、保存状态、运行档案和成员概况。
5. 补齐 CSS，保持 console 密度，按钮/卡片半径不超过 8px，确保小屏折叠可用。
6. 跑测试与构建，并实际打开页面检查布局。
