# 93-TaskTemplate选择层拆除正式实施计划-20260515

## 0. 计划定位

本文不是问题分析，也不是概念草图。

本文用于指导 `TaskTemplate` 选择层的正式拆除实施，目标是一次性完成“模板选择层退场、执行配方接管、主链路切换”的结构改造。

本计划默认不保留无意义旧兼容，不以“先留着以后再说”为原则。

## 1. 本轮要解决的核心问题

当前任务系统把两种完全不同的职责混在了 `TaskTemplate` 体系里：

1. 执行配方职责
   - step blueprints
   - validation rules
   - required/optional operations
   - output schema
   - runtime metadata

2. 路由兼容职责
   - `match_template()`
   - template alias
   - fallback general response
   - capability -> template heuristic
   - source kind -> template fallback

真正导致系统越来越别扭的，是第 2 类职责。

所以本轮不是修补 `match_template()`，而是要让它退出主链路。

## 2. 本轮目标

本轮结束后，主链路要从：

`TaskIntentContract -> match_template -> selected_template -> assembly/runtime`

切换为：

`TaskIntentContract -> resolve_execution_shape -> build_execution_recipe -> assembly/runtime`

具体目标：

1. `assembly_builder` 不再依赖 `match_template()`
2. `runtime_loop` 不再依赖 `_task_template_from_payload()`
3. `context_management` 不再根据 `template_id` 反推 source kind
4. `local_mcp_registry` 不再以 `template_ids` 作为主映射依据
5. `TaskTemplateRegistry` 不再承担主路由职能

## 3. 本轮不做的事

本轮不做以下扩展，避免边拆边发散：

1. 不重构整个 TaskGraph 系统
2. 不改 Agent prompt 体系
3. 不重做 task definition / binding 总模型
4. 不顺手优化 unrelated projection
5. 不为了保留旧 trace 脚本去强行维持 template 兼容字段

## 4. 结构替代方案

### 4.1 新中心对象

新增：

- `ExecutionRecipe`

职责：

1. 表达本次任务实际执行方式
2. 承载 runtime 需要的步骤、校验、产物和操作要求
3. 代替 `selected_template` 进入 assembly 和 runtime

### 4.2 新判定层

新增：

- `ExecutionShapeResolver`

职责：

1. 判定任务执行类型
2. 判定 source kind
3. 判定 artifact policy
4. 判定 finalization policy
5. 生成基础 operation profile

注意：

这层不能返回 template id。

### 4.3 新构建层

新增：

- `ExecutionRecipeBuilder`

职责：

1. 根据 execution shape 产出 recipe
2. 把旧 template 中仍有价值的执行数据迁移出来
3. 支持 specific task / flow / capability 的显式覆盖

## 5. 本轮修改范围

### 5.1 必改文件

1. [backend/tasks/assembly_builder.py](D:/AI应用/langchain-agent/backend/tasks/assembly_builder.py)
2. [backend/tasks/assembly_support.py](D:/AI应用/langchain-agent/backend/tasks/assembly_support.py)
3. [backend/orchestration/runtime_loop/task_run_loop.py](D:/AI应用/langchain-agent/backend/orchestration/runtime_loop/task_run_loop.py)
4. [backend/context_management/resolver.py](D:/AI应用/langchain-agent/backend/context_management/resolver.py)
5. [backend/context_management/projection.py](D:/AI应用/langchain-agent/backend/context_management/projection.py)
6. [backend/capability_system/local_mcp_registry.py](D:/AI应用/langchain-agent/backend/capability_system/local_mcp_registry.py)
7. [backend/tasks/flow_registry.py](D:/AI应用/langchain-agent/backend/tasks/flow_registry.py)
8. [backend/tasks/template_registry.py](D:/AI应用/langchain-agent/backend/tasks/template_registry.py)

### 5.2 新增文件

建议新增：

1. `backend/tasks/execution_recipe_models.py`
2. `backend/tasks/execution_shape_resolver.py`
3. `backend/tasks/execution_recipe_builder.py`

如需减少分散，也可以把 builder / resolver 先放到 `backend/tasks/` 下，再在第二轮拆细。

## 6. 详细实施步骤

### Step 1：新增 `ExecutionRecipe` 数据模型

目标：

让 runtime 和 assembly 有一个新的稳定承载物。

最低字段：

1. `recipe_id`
2. `execution_kind`
3. `task_family`
4. `task_mode`
5. `source_kind`
6. `output_schema`
7. `required_operations`
8. `optional_operations`
9. `step_blueprints`
10. `validation_rules`
11. `artifact_policy`
12. `finalization_policy`
13. `metadata`

退出条件：

1. 该模型可序列化/反序列化
2. 可从旧 template 临时构造 recipe

### Step 2：实现 `ExecutionShapeResolver`

目标：

把 `match_template()` 里的“判定行为”迁走，但不再返回 template id。

最低输出：

1. `execution_kind`
2. `source_kind`
3. `artifact_policy`
4. `finalization_policy`
5. `operation_profile`

最低覆盖场景：

1. 普通对话
2. 搜索/实时信息
3. workspace patch
4. pdf/document analysis
5. dataset analysis
6. bundle task

退出条件：

1. `assembly_builder` 已可直接消费 resolver 结果

### Step 3：实现 `ExecutionRecipeBuilder`

目标：

用结构化输入直接生成执行 recipe。

要求：

1. 普通对话生成 conversation recipe
2. 搜索类任务生成 search recipe
3. workspace patch 生成 file-artifact aware recipe
4. pdf/dataset 生成对应 analysis recipe
5. bundle 生成 multi-step bundle recipe

退出条件：

1. 产出的 recipe 足以替代当前 `selected_template`

### Step 4：切换 `assembly_builder`

目标：

主装配入口不再调用 `match_template()`。

具体动作：

1. 保留 `build_task_intent_contract()`
2. 删除 `template_match = template_registry.match_template(...)`
3. 删除 `selected_template = template_registry.get_template(...)`
4. 改为：
   - `execution_shape = resolve_execution_shape(...)`
   - `selected_recipe = build_execution_recipe(...)`

5. 下游所有 `selected_template` 入参改名为 `selected_recipe`

退出条件：

1. `build_task_execution_assembly_bundle()` 输出中不再要求 `selected_template`
2. task spec / task assembly 能完整使用 recipe

### Step 5：切换 `assembly_support`

目标：

把支持层从 template 语义改成 recipe 语义。

重点动作：

1. 所有 `selected_template` 入参改为 `selected_recipe`
2. `_template_id_for_capability()` 删除
3. capability/source kind 逻辑改为显式字段
4. `get_local_mcp_unit_for_template()` 调用全部移除

退出条件：

1. `assembly_support` 中不再存在新的 template 路由逻辑

### Step 6：切换 `runtime_loop`

目标：

运行时只认 recipe，不再反解 template。

重点动作：

1. 删除 `_task_template_from_payload()`
2. 改为 `_recipe_from_payload()`
3. 删除 `_template_requires_model_finalize()`
4. 改为 `_recipe_requires_model_finalize()`
5. 删除 `_template_allows_tool_observation_finalization()`
6. 改为 `_recipe_allows_tool_observation_finalization()`
7. `_requires_write_file_artifact()` 改为基于 recipe 的 artifact policy

退出条件：

1. runtime terminal / finalize / artifact repair 全部依赖 recipe 运行

### Step 7：切换 `context_management`

目标：

不再通过 `template_id` 猜测 source kind。

重点动作：

1. 删除 `"structured" in template_id` 之类字符串判断
2. 从 task context / recipe payload 中直接读：
   - `source_kind`
   - `execution_kind`
   - `capability_kind`
   - `file_kind`

退出条件：

1. context projection 和 resolver 不再依赖 template 命名字符串

### Step 8：切换 `local_mcp_registry`

目标：

切断 capability system 对 template 的主索引依赖。

重点动作：

1. `template_ids` 退场
2. 新增：
   - `capability_kinds`
   - `source_kinds`

3. 删除：
   - `get_local_mcp_unit_for_template()`
   - `get_local_mcp_primary_template()`

4. 新增：
   - `get_local_mcp_unit_for_capability()`
   - `get_local_mcp_unit_for_source_kind()`

退出条件：

1. MCP unit 查找完全不依赖 template id

### Step 9：切换 `flow_registry`

目标：

specific task / flow 不再通过 template id 描述执行方式。

重点动作：

1. static task mapping 改为 recipe preset / execution kind
2. 保留 workflow / task_mode / task_family
3. 删除 specific task -> template id 绑定

退出条件：

1. flow registry 不再是 template 传递中转站

### Step 10：删除 template selection layer

在前 9 步完成后，删除：

1. `match_template()`
2. `select_template()`
3. `_intent_candidate_template_ids()`
4. `_select_existing_template_id()`
5. alias/fallback 逻辑

如 `TaskTemplate` 已无剩余运行价值，则一起删除。

## 7. 文件级动作清单

### `backend/tasks/template_registry.py`

本轮目标：

1. 最终只保留必要的 intent contract 构造能力
2. 删除模板匹配与 fallback 逻辑

### `backend/tasks/assembly_builder.py`

本轮目标：

1. 切换为 recipe 驱动
2. 删除模板选择调用

### `backend/tasks/assembly_support.py`

本轮目标：

1. 删除基于 template id 的能力推断
2. 改为 recipe/source/capability 显式决策

### `backend/orchestration/runtime_loop/task_run_loop.py`

本轮目标：

1. 删除 template payload 反序列化
2. 改为 recipe payload

### `backend/context_management/resolver.py`

本轮目标：

1. 删除 capability -> template 默认映射
2. 改为 capability/source kind 显式归类

### `backend/context_management/projection.py`

本轮目标：

1. 删除 template 字符串分类判断
2. 改为显式上下文字段

### `backend/capability_system/local_mcp_registry.py`

本轮目标：

1. 删除 `template_ids`
2. 用 capability/source 建索引

### `backend/tasks/flow_registry.py`

本轮目标：

1. 删除 template id 绑定
2. 用 recipe preset / execution kind 替代

## 8. 风险控制

### 8.1 最大风险

1. runtime finalize 行为失真
2. 写文件任务的 artifact 校验丢失
3. pdf/dataset 的 source routing 丢失
4. specific task 退化成普通对话

### 8.2 控制方法

1. 先迁 recipe，再删 template selection
2. runtime 相关逻辑必须在同一轮切换完成
3. source_kind 与 artifact_policy 必须显式入 payload
4. 不做半切换状态长期停留

## 9. 实施顺序要求

本轮必须严格按以下顺序：

1. 建 recipe model
2. 建 shape resolver
3. 建 recipe builder
4. 切 assembly builder
5. 切 assembly support
6. 切 runtime loop
7. 切 context management
8. 切 local MCP registry
9. 切 flow registry
10. 删 template selection layer

不允许先删 `match_template()` 再慢慢补。

## 10. 阶段退出标准

只有以下条件同时满足，才算本轮完成：

1. 主装配入口不再调用 `match_template()`
2. runtime 不再反序列化 `TaskTemplate`
3. context 不再通过 `template_id` 猜 source kind
4. MCP registry 不再依赖 `template_ids`
5. specific task 不再向下游传递 template id
6. template alias / fallback 已物理删除

## 11. 最终交付结果

本轮完成后，系统中应该只剩两类东西：

1. 意图理解与执行形态判定
2. 面向 runtime 的 execution recipe

不应该再存在一个位于中间、既做路由又做兼容又做执行配置的 template selection layer。

## 12. 执行结论

这不是小修。

但这是值得直接动手拆的结构性问题，而且一旦不拆，后面工具可见性、任务筛选、能力映射、实时性路由这些问题还会不断反复出现。

因此本计划建议：

按本文顺序，直接进入正式拆除实施。
