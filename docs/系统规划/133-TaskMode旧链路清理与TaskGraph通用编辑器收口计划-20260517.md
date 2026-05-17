# 133-TaskMode旧链路清理与TaskGraph通用编辑器收口计划

日期：2026-05-17

## 1. 问题判断

当前项目的正确主线已经是 TaskGraph 通用编辑器：

- 图身份：`graph_id`
- 节点身份：`node_id` / `node_type`
- 节点职责：`task_id` / `agent_id` / `projection_id` / `runtime_lane`
- 交接关系：控制边、交接边、记忆读写边、产物上下文边、返修边
- 运行上下文：时序坐标、记忆 selector、产物 ref、revision packet、dispatch context

旧链路仍然残留在：

- `task_mode`
- `allowed_task_modes`
- 默认 `TaskTemplate`
- 默认 `TaskWorkflow`
- 默认 `TaskFlow`
- 健康系统基于 task mode 的路由
- 编排层基于 task mode 的 Prompt/RuntimeLane 推断
- 旧测试对 task mode 行为的断言

这些残留会误导设计判断，让通用编辑器退回“预设任务模式选择器”，与当前目标冲突。

## 2. 清理原则

1. TaskGraph 是唯一任务设计主线。
2. 节点不是 task mode，节点由 `node_id + node_type + task_id + agent_id + projection_id + runtime_lane` 表达。
3. 编排系统不再通过 task mode 判断 agent 能否执行任务。
4. 健康管家不再通过 task mode 选择健康任务；后续应作为 TaskGraph 节点/子图使用工具和独立会话。
5. 旧模板、旧 workflow、旧 flow 不再自动注入系统。
6. 测试不保留旧机制兼容断言，改为验证 TaskGraph 通用结构。

## 3. 保留与删除边界

### 保留

- `TaskGraphDefinition` / `TaskGraphNodeDefinition` / `TaskGraphEdgeDefinition`
- `compile_task_graph_definition_runtime_spec`
- TaskGraph 存储：`task_graphs.json`
- 拓扑模板：`topology_templates.json`
- 通信协议：`task_communication_protocols.json`
- 节点契约、边契约、记忆/产物/返修边校验
- Agent runtime profile 的 runtime lane、operation、memory scope、output contract 约束

### 删除或切断

- 默认任务模板注入
- 默认 workflow 注入
- 默认 task flow 注入
- `allowed_task_modes` 权限判断
- `runtime_task_mode_not_allowed` 诊断
- 健康系统 `_route_conversation_task_mode`
- 写作配置脚本生成 `task_mode` / `allowed_task_modes`
- 旧测试文件中围绕 `task_mode`、模板、workflow、flow 的断言

### 暂时保留但降级为存储 facade

`backend/tasks/flow_registry.py` 当前混合承载旧 flow 与新 TaskGraph 注册能力。第一轮不删除文件本身，避免误伤通用编辑器；本轮目标是切掉旧 flow/template/workflow 语义，使它成为 TaskGraph/拓扑/协议/契约绑定的注册 facade。后续可单独重命名为 `task_graph_registry.py`。

## 4. 实施步骤

### 阶段一：编排权限去 task_mode

- 移除 `AgentRuntimeProfile.allowed_task_modes`
- 清理默认 profile 和 upsert/profile payload
- 移除契约编译器中的 `runtime_task_mode_not_allowed`
- 编排 runtime lane 只由显式 `runtime_lane`、profile 允许 lane、节点配置决定

完成标准：全仓不再用 `allowed_task_modes` 参与权限判断。

### 阶段二：旧模板/旧 workflow/旧 flow 切断

- `TaskTemplateRegistry` 不再提供默认模板，不再作为 overview 的核心指标。
- `TaskWorkflowRegistry` 不再注入默认 workflow。
- `TaskFlowRegistry.list_flows()` 不再注入默认 health/dev flow。
- `SpecificTaskRecord` 去掉 `task_mode` 字段，以 `task_id/task_family/runtime_lane/metadata` 表达节点可引用任务。
- 删除 `compile_workflow_contract_manifest` 对外主路径，保留 TaskGraph coordination manifest。

完成标准：空目录不会自动出现旧模板、旧 workflow、旧 flow、旧 health/dev task。

### 阶段三：健康系统去 task_mode

- 健康管家命令与会话不再存储 task mode。
- 会话不再根据用户词汇路由 task mode。
- 健康执行以 `health_action` / `runtime_lane` / `graph_id` 表达。
- 后续自动监督应接入 TaskGraph 节点或子图，不走旧任务模式。

完成标准：健康系统不再生成 `task.health.{task_mode}` 和 `graph.health.{task_mode}`。

### 阶段四：脚本、前端、存储清理

- 写作配置脚本不再生成 `task_mode` / `allowed_task_modes`。
- 前端类型和表单删除任务模式字段。
- 旧存储 JSON 中的旧 flow/template/workflow 文件清理为空或移除。
- UI 不再展示 task mode 选择，转为节点、runtime lane、projection、memory/artifact/revision 边配置。

完成标准：通用编辑器没有 task mode 配置入口。

### 阶段五：测试收口

- 删除旧模板/workflow/flow 测试。
- 更新 TaskGraph 协调契约测试，确保不再断言 task_mode。
- 运行后端 TaskGraph/健康/编排相关测试。
- 运行前端类型检查。

完成标准：测试只覆盖 TaskGraph 通用主线和当前仍保留的注册能力。

## 5. 风险控制

- 不删除 TaskGraph 存储和运行主线。
- 不把 Prompt 写成开发说明，节点 Prompt 继续以 agent 身份和任务职责表达。
- 不为了测试伪造产出。
- 不保留旧机制兼容入口作为默认路径。

## 6. 收尾扫描

最终扫描：

```powershell
rg -n "task_mode|allowed_task_modes|default_task_templates|default_task_workflows|compile_workflow_contract_manifest" backend frontend scripts
```

允许残留仅限：

- 历史文档
- 明确标记为迁移说明的实施报告
- 已隔离且不参与运行的旧数据备份

