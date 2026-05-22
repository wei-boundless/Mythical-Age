# 任务图节点提示词装配修复计划

## 背景

《洪荒时代》写作任务在世界观设计阶段跑出了通用模板污染内容。排查后发现任务图快照和工作流注册表里已经有新的专业 `role_prompt`，但节点运行时真正进入模型的上下文没有包含该专业提示词；同时节点运行的语义契约被当前聊天/返修文本误判为 `code_fix_execution`，导致模型看到“结构性代码修复执行员”而不是世界观架构师。

## 修复目标

1. 任务图节点运行必须以注册任务、节点工作流和节点输出契约为职责来源。
2. `task_workflows.json` 中的工作流专业提示词必须进入模型可见上下文。
3. 任务图节点执行不能因为节点输入中出现“修复、产物、提交”等词，被误判成代码修复任务。
4. 显式节点身份必须覆盖旧的上下文残留，避免 `project_brief` 这类上游节点身份污染 `world_design`。
5. 增加回归测试，确保世界观节点能看到专业提示词，且不再出现代码修复专业 profile。

## 实施步骤

1. 在任务装配阶段为 `task_graph_node_runtime` 注入稳定语义上下文：固定为任务图节点职责执行，继承注册任务的 `role_mode`/`coordination_task`，并清理当前聊天意图对语义类型的影响。
2. 在 agent invocation 合并阶段同步 `task_ref` 到 `selected_task_id/task_id/specific_task_id`，防止上一个节点身份残留。
3. 在 runtime prompt contract 中新增“节点专业职责”模型可见 section，内容来自工作流 `prompt`。
4. 在 soul runtime section 装配中渲染该新 section。
5. 调整语义提示渲染，让任务图节点显示为专业节点职责，而不是开发任务类型。
6. 添加写作图回归测试，覆盖世界观节点 prompt 可见性和 `code_fix_execution` 污染防护。

## 验收

1. 测试中世界观节点模型可见 section 包含“名家级中文商业网文世界架构师”和“套路资产污染”。
2. 同一测试中模型可见 section 不包含“结构性代码修复执行员”。
3. 任务契约的 `semantic_task_contract.task_goal_type` 不再是 `code_fix_execution`。
