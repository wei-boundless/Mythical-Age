# Agent 装配与 RunLoop 收敛优化实施计划书

日期：2026-05-08

关联资料：

- `docs/设计原则/12-Agent-系统.md`
- `docs/设计原则/13-内置Agent设计模式.md`
- `docs/系统规划/23-Agent编排系统定义层与运行层统一优化计划书-20260508.md`

关联代码：

- `backend/orchestration/agent_registry.py`
- `backend/orchestration/agent_runtime_registry.py`
- `backend/orchestration/agent_group_registry.py`
- `backend/orchestration/runtime_loop/runtime_assembly_builder.py`
- `backend/orchestration/runtime_loop/context_manager.py`
- `backend/orchestration/worker_agent_factory.py`
- `backend/api/orchestration.py`
- `frontend/src/components/workspace/views/OrchestrationView.tsx`
- `frontend/src/components/workspace/views/orchestration/*`

---

## 1. 当前问题定义

本次优化不是新增一个孤立功能，而是修复定义层、装配层与运行层之间的边界漂移。

当前主要断点：

1. 内置 Agent 在后端仍带 `editable=true`，`upsert_agent()` 只保护类别，不能形成真正的系统锁。
2. `agent:1`、`agent:2`、`agent:4`、`agent:5` 缺省 RuntimeProfile，导致系统管理 Agent 有名册但缺运行档案。
3. 前端新建子 Agent 仍通过扫描列表本地计算 ID，绕过 `/orchestration/agents/next-worker-id`。
4. AgentGroup 后端不校验成员身份，组可以保存不存在、内置或非 worker 成员。
5. RuntimeAssembly 会生成上下文段，但没有和 `AgentRuntimeProfile.allowed_context_sections` 做显式交集，运行层仍可能看见 profile 未允许的上下文段。
6. worker blueprint 仍只有一个通用开发原型，缺少 Explorer / Planner / Verification / Execution / Review 等可复用装配模板。

正确终态：

- Agent 身份由 `AgentRegistry` 统一治理。
- RuntimeProfile 覆盖所有内置 Agent，且是运行能力边界的硬输入。
- 子 Agent ID 只由后端分配。
- AgentGroup 只管理 worker membership，不承担生成 Agent。
- RuntimeAssembly 只输出 profile 允许的上下文段，并把被裁剪的段写入 diagnostics。
- WorkerAgentFactory 可以从角色化蓝图装配一致的名册与运行档案。

---

## 2. 本次实施范围

本次先完成 23 号计划的第一、第二、第三阶段，并补一层 runloop 装配收敛：

1. 后端锁定内置 Agent，并补齐系统管理 RuntimeProfile。
2. 前端新建 Agent ID 改为后端权威生成。
3. 后端校验 AgentGroup 的 coordinator 与 member。
4. RuntimeAssembly 按 RuntimeProfile 裁剪上下文段。
5. WorkerAgentBlueprint 扩充为角色化模板集合。
6. 增加回归测试覆盖上述行为。

暂不在本轮落地完整 `AgentDefinitionProfile` 前端编辑页；本轮先通过 metadata 与 blueprint 为后续定义层保留稳定入口，避免一次性把 UI、契约、运行时全部重开。

---

## 3. 固定执行流

### 阶段 A：定义层治理

输入：

- 默认 AgentDescriptor
- 已持久化 agents.json

动作：

- 内置 Agent 默认 `editable=false`。
- `list_agents()` 合并后强制将默认内置 Agent 的系统字段作为权威。
- `upsert_agent()` 遇到内置 Agent 时只允许无害重复保存，不允许禁用、改类别、改 ID、改系统元数据。

输出：

- `agent:0` 到 `agent:5` 固定为系统内置、启用、不可删除、不可禁用。

### 阶段 B：运行档案闭环

输入：

- `default_agent_runtime_profiles()`

动作：

- 补齐权限、记忆、健康、能力、灵魂管理 Agent 的 RuntimeProfile。
- profile 的上下文段统一包含可被 assembly 消费的显式 section key。

输出：

- 默认六个内置 Agent 均有 RuntimeProfile。

### 阶段 C：组与 ID 权威

输入：

- `/orchestration/agents/next-worker-id`
- AgentGroup 保存请求

动作：

- 前端新建 Agent 草稿异步请求后端 ID。
- AgentGroup 后端校验成员存在且为非内置 `worker_sub_agent`。
- coordinator 允许为空；不为空时必须存在且启用。
- 前端默认组清理为 `group.custom.worker_group_XX`，不再回落到具体写作业务或 `agent:20`。

输出：

- 组只负责 membership。
- 子 Agent 池与组成员边界清晰。

### 阶段 D：RunLoop 装配收敛

输入：

- ContractManifest
- AgentRuntimeProfile

动作：

- `build_single_agent_runtime_assembly()` 和 `build_node_runtime_assembly()` 为每个上下文段标注 profile section key。
- assembly 只保留 profile 允许的上下文段。
- diagnostics 写入 `context_sections_requested`、`context_sections_visible`、`context_sections_hidden_by_profile`。

输出：

- 默认隔离、显式共享由运行数据结构执行，不只停留在文档和 prompt。

---

## 4. 文件级清单

- `backend/orchestration/agent_models.py`
  - 增加 metadata 派生的 `definition_source`、`lifecycle_policy`、`mutable_fields` 输出。

- `backend/orchestration/agent_registry.py`
  - 默认内置 Agent 改为不可编辑。
  - 合并持久化数据时强制系统内置字段回归默认权威。
  - 后端 upsert 对内置 Agent fail closed。

- `backend/orchestration/agent_runtime_registry.py`
  - 补齐 `agent:1`、`agent:2`、`agent:4`、`agent:5` profile。
  - 规范默认 profile 的 context section keys。

- `backend/orchestration/agent_group_registry.py`
  - 引入 AgentRegistry 校验 coordinator/member。
  - 成员仅允许非内置 worker_sub_agent。

- `backend/orchestration/runtime_loop/runtime_assembly_builder.py`
  - 按 RuntimeProfile 裁剪上下文段。
  - 给 diagnostics 增加裁剪证据。

- `backend/orchestration/worker_agent_factory.py`
  - 扩充 worker 蓝图为 explorer/planner/verification/execution/review。

- `backend/api/orchestration.py`
  - 允许空 coordinator。
  - 捕获组保存 PermissionError。

- `frontend/src/components/workspace/views/OrchestrationView.tsx`
  - 新建 Agent 调用后端 ID 接口。
  - 清理旧业务组默认值和 `agent:20` 回退。

- `backend/tests/orchestration_agent_management_regression.py`
  - 新增定义层、组校验、runtime assembly 裁剪测试。

---

## 5. 验证策略

后端回归：

```powershell
$env:PYTHONPATH='backend'
pytest backend\tests\orchestration_agent_management_regression.py
pytest backend\tests\runtime_assembly_builder_test.py
pytest backend\tests\task_system_api_regression.py
```

前端类型检查：

```powershell
cd frontend
npx tsc --noEmit
```

验收点：

1. 默认六个内置 Agent 都不可编辑、不可禁用、不可删除。
2. 默认六个内置 Agent 都有 RuntimeProfile。
3. 新建子 Agent ID 来自后端。
4. AgentGroup 不能保存内置或不存在的成员。
5. RuntimeAssembly 不包含 profile 未允许的上下文段。
6. worker blueprint 不再只有一个通用原型。

---

## 6. 追加：任务模式注册链路清理

触发问题：

- `TaskTemplateRegistry.match_template()` 会选择 `template.chat.general_response` 等模板 ID。
- `default_task_templates()` 已被清成空集合。
- 结果是任务模式链路看似存在，运行时实际没有可装配模板，`orchestration_cutover_regression` 在 `template.chat.general_response` 处断裂。

清理原则：

1. 不保留“匹配层选旧 ID、注册层为空”的残留结构。
2. 任务模式以 `TaskTemplate` 注册表为真实来源。
3. 匹配层只能返回注册表中存在的模板。
4. 对历史入口只保留必要别名映射，不再散落硬编码 fallback。
5. 通用会话入口统一归入 `template.general.main_conversation`，旧 `template.chat.general_response` 仅作为迁移别名保留在同一个定义源里，后续前端和测试逐步切换到新 ID。

文件级动作：

- `backend/tasks/template_registry.py`
  - 恢复正式最小模板集合。
  - 增加 `_select_existing_template_id()`，所有匹配结果必须存在。
  - 清理悬空 fallback。

- `backend/tests/task_template_registry_regression.py`
  - 增加匹配结果必须都来自注册表的回归。

- `backend/tests/orchestration_cutover_regression.py`
  - 作为本链路端到端验收。
