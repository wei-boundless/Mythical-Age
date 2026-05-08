# 任务系统与 FlowRegistry 风险报告

日期：2026-05-09

范围：
- `backend/tasks`
- `backend/api/tasks.py`
- `backend/orchestration/runtime_loop`
- `backend/tests/task_*`
- `backend/tests/contract_compiler_*`

## 一、结论摘要

任务系统当前已经具备较完整的任务定义、模板匹配、工作流、契约、投影绑定、任务图、协调任务和运行装配能力。

但主要风险不在能力缺失，而在“注册表过载”和“读操作隐式写盘”：

1. `TaskFlowRegistry` 单类承担过多系统职责，是任务系统最大结构风险。
2. 多个 `list_*` / `build_overview()` 读取接口会自动派生默认配置并写回磁盘。
3. JSON 配置读取失败会静默回退默认值，坏配置可能被默认配置掩盖。
4. 删除任务域和具体任务时会跨多个 JSON 文件级联写入，缺少事务、预检和 dry-run。
5. 新的 `task_execution_policy` 和旧的 `task_agent_adoption_plan` 仍并行存在。
6. 任务模板选择存在 heuristic fallback，显式配置缺失时可能退回通用对话模板。
7. 协调任务、任务图、拓扑模板、通信协议之间存在派生重叠，瘦身前必须先收口权威源。

专项测试结果：

```powershell
python -m pytest backend/tests/task_system_api_regression.py backend/tests/task_graph_registry_test.py backend/tests/task_template_registry_regression.py backend/tests/contract_compiler_workflow_test.py backend/tests/task_contract_registry_test.py backend/tests/contract_compiler_coordination_test.py backend/tests/runtime_assembly_builder_test.py -q
```

结果：

```text
1 failed, 39 passed
```

失败用例：

```text
backend/tests/task_template_registry_regression.py::test_task_system_overview_exposes_templates_and_validation_matrix
assert payload["summary"]["projection_binding_count"] == 0
E assert 4 == 0
```

这个失败不是偶然问题。它说明在空临时目录中调用 `TaskFlowRegistry(tmp_path).build_overview()` 时，概览接口会通过默认任务记录派生出 projection bindings，导致测试期望的“空存储无显式绑定”语义和实际“读取即生成默认绑定”语义冲突。

## 二、系统结构现状

### 2.1 代码规模

`backend/tasks` 共有 29 个 Python 文件，约 8214 行。

主要大文件：

| 文件 | 行数 | 角色 |
|---|---:|---|
| `backend/tasks/flow_registry.py` | 2877 | 任务系统主注册表 |
| `backend/tasks/template_registry.py` | 750 | 任务模板和模板匹配 |
| `backend/tasks/assembly_support.py` | 672 | 任务装配辅助 |
| `backend/tasks/assembly_builder.py` | 507 | 任务运行装配 |
| `backend/tasks/run_models.py` | 492 | 运行模型 |
| `backend/tasks/contract_registry.py` | 393 | 契约注册表 |
| `backend/tasks/workflow_registry.py` | 381 | 工作流注册表 |

### 2.2 当前主链路

任务系统大致链路为：

```text
Query / API
  -> TaskTemplateRegistry
      -> TaskIntentContract
      -> TemplateMatchResult
  -> TaskFlowRegistry
      -> general profiles
      -> specific task records
      -> flows
      -> projection bindings
      -> flow contract bindings
      -> task execution policy / legacy adoption plan
      -> memory request profiles
      -> coordination tasks
      -> task graphs
      -> topology templates
      -> communication protocols
  -> TaskWorkflowRegistry
  -> TaskContractRegistry
  -> assembly_builder
      -> TaskExecutionAssembly
  -> TaskRunLoop / LangGraph coordination runtime
```

这条链路功能很全，但多个层级的“定义、派生、缓存、运行装配、兼容输出”混在同一个注册表中。

## 三、主要风险

### R1. `TaskFlowRegistry` 职责过载

严重级别：高

位置：
- `backend/tasks/flow_registry.py`

现象：

`TaskFlowRegistry` 一个类同时管理：

- general task profile
- specific task record
- task flow
- task assignment
- task domain
- projection binding
- flow contract binding
- task execution policy / adoption plan
- task memory request profile
- coordination task
- task graph
- topology template
- communication protocol
- agent-task connection profile
- carrying profile
- overview / diagnostics

风险：

这些概念不是同一层级。任务域、具体任务、流程、任务图、通信协议、运行策略、记忆请求属于不同权威层。全部放在一个注册表中，会导致：

- 任一 `list_*` 都可能触发另一个 `list_*`，形成隐式依赖链。
- 删除和更新需要跨多个 JSON 文件手工同步。
- 测试很难判断结果来自显式存储、默认种子还是派生逻辑。
- 后续瘦身时无法直接删除旧结构，因为旧结构可能被某个派生接口重新生成。

证据：

- `backend/tasks/flow_registry.py:707` 定义 `TaskFlowRegistry`。
- `backend/tasks/flow_registry.py:777` 读取 flows。
- `backend/tasks/flow_registry.py:1117` 读取 specific task records。
- `backend/tasks/flow_registry.py:1514` 读取 projection bindings。
- `backend/tasks/flow_registry.py:1591` 读取 flow contract bindings。
- `backend/tasks/flow_registry.py:1657` 读取 adoption plans。
- `backend/tasks/flow_registry.py:1888` 读取 coordination tasks。
- `backend/tasks/flow_registry.py:1987` 读取 task graphs。
- `backend/tasks/flow_registry.py:2125` 读取 topology templates。
- `backend/tasks/flow_registry.py:2163` 读取 communication protocols。

建议：

拆成三个层级：

1. 定义层：task domain、specific task、flow、workflow、contract。
2. 运行策略层：projection binding、flow contract binding、execution policy、memory request profile。
3. 协调层：coordination task、task graph、topology、communication protocol。

每层提供独立 registry，`TaskSystemFacade` 只负责组合读取和跨层校验。

### R2. 读取接口会写磁盘，导致查询和迁移混在一起

严重级别：高

位置：
- `backend/tasks/flow_registry.py:777`
- `backend/tasks/flow_registry.py:1117`
- `backend/tasks/flow_registry.py:1514`
- `backend/tasks/flow_registry.py:1591`
- `backend/tasks/flow_registry.py:1888`
- `backend/tasks/flow_registry.py:1987`
- `backend/tasks/flow_registry.py:2125`
- `backend/tasks/flow_registry.py:2163`
- `backend/tasks/workflow_registry.py:282`

现象：

多个 `list_*` 方法会：

1. 读取 JSON。
2. 合并默认值或派生值。
3. 标准化成模型。
4. 如果标准化结果和原 payload 不同，就 `_write_json()` 写回。

典型例子：

- `list_flows()` 在 `backend/tasks/flow_registry.py:806` 到 `backend/tasks/flow_registry.py:808` 写回 `flows.json`。
- `list_specific_task_records()` 在 `backend/tasks/flow_registry.py:1161` 到 `backend/tasks/flow_registry.py:1168` 写回 `specific_task_records.json`。
- `list_projection_bindings()` 在 `backend/tasks/flow_registry.py:1546` 到 `backend/tasks/flow_registry.py:1548` 写回 `task_projection_bindings.json`。
- `list_coordination_tasks()` 在 `backend/tasks/flow_registry.py:1972` 到 `backend/tasks/flow_registry.py:1974` 写回 `coordination_tasks.json`。

风险：

- 只打开管理页面或调用 overview，就可能改动存储文件。
- Git diff 里会出现非用户主动修改的配置变化。
- 配置损坏和配置迁移无法区分。
- 并发读取时可能互相覆盖。
- 测试在空目录中也可能生成默认配置，造成“空存储”语义失真。

已暴露的测试失败：

- `backend/tests/task_template_registry_regression.py:111`
- `backend/tests/task_template_registry_regression.py:115`

该测试期望空目录中 `projection_binding_count == 0`，实际得到 `4`。触发链路是 `build_overview()` 在 `backend/tasks/flow_registry.py:2767` 调用 `list_projection_bindings()`，后者在 `backend/tasks/flow_registry.py:1515` 到 `backend/tasks/flow_registry.py:1518` 基于默认 general profile 和 specific task records 派生绑定。

建议：

- 所有 `list_*` 必须变成纯读取。
- 新增显式 `normalize_storage()` 或 `migrate_storage()`，由管理动作或启动迁移调用。
- `build_overview()` 区分 `explicit_count`、`derived_count`、`default_seed_count`。
- 测试中分别覆盖“空存储不写盘”和“显式迁移后写盘”。

### R3. JSON 读取失败静默回退默认值

严重级别：高

位置：
- `backend/tasks/flow_registry.py:281`
- `backend/tasks/workflow_registry.py:204`
- `backend/tasks/contract_registry.py:37`

现象：

三个注册表的 `_read_json()` 都在异常时直接返回 fallback：

```text
except Exception:
    return fallback
```

风险：

如果 `storage/tasks/*.json` 被截断、格式错误、编码错误或写入半截，系统不会报告配置损坏，而是继续使用默认值。更严重的是，后续 `list_*` 的标准化写回可能把坏配置覆盖成默认配置，导致原始错误证据消失。

影响场景：

- 用户在管理台编辑任务配置失败。
- 多进程同时写同一个 JSON 文件。
- 手动合并配置时 JSON 不完整。
- 升级字段结构后旧 payload 无法解析。

建议：

- `_read_json()` 返回结构化 `RegistryReadResult`，包含 `ok`、`source`、`error`、`used_fallback`。
- 运行态关键配置读取失败时 fail-closed。
- 管理 overview 可以展示坏配置，但不能悄悄使用默认值覆盖。
- 对 JSON 写入使用临时文件 + 原子替换，并保留 `.bak`。

### R4. 删除操作跨文件级联写入，缺少事务和预检

严重级别：高

位置：
- `backend/tasks/flow_registry.py:1008`
- `backend/tasks/flow_registry.py:1324`

现象：

`delete_task_domain()` 会一次删除或改写：

- task domains
- specific task records
- assignments
- flows
- projection bindings
- flow contract bindings
- adoption plans
- memory request profiles
- coordination tasks
- topology templates
- communication protocols
- workflows

`delete_specific_task_record()` 也会改写多个文件，并且会修改 coordination task 的 nodes、edges、subtask refs。

风险：

- 任一中途写入失败会造成半删除。
- 没有 dry-run，用户无法先看影响面。
- 删除默认派生对象和显式对象的边界不清楚。
- 工作流删除使用 `TaskWorkflowRegistry.delete_workflows()`，默认 workflow 不会删除，可能留下“看似删除完成但默认项仍可见”的状态。
- 协调任务节点被删除后，图结构可能只剩空壳，但没有完整图校验。

证据：

- `backend/tasks/flow_registry.py:1058` 到 `backend/tasks/flow_registry.py:1105` 连续写多个 JSON 文件。
- `backend/tasks/flow_registry.py:1347` 到 `backend/tasks/flow_registry.py:1424` 连续写多个 JSON 文件并重写 coordination tasks。
- `backend/tasks/workflow_registry.py:359` 到 `backend/tasks/workflow_registry.py:362` 默认 workflows 不会被删除。

建议：

- 删除前提供 `plan_delete_task_domain()`，返回完整影响面。
- 删除执行使用批处理事务模型：先写临时文件，全部成功后再替换。
- 删除结果区分 `deleted_explicit`、`hidden_default`、`kept_default`、`skipped_with_reason`。
- 删除后运行 task graph / contract / workflow 引用完整性校验。

### R5. 默认值覆盖和 tombstone 机制不一致

严重级别：中高

位置：
- `backend/tasks/flow_registry.py:897`
- `backend/tasks/flow_registry.py:1117`
- `backend/tasks/flow_registry.py:1514`
- `backend/tasks/flow_registry.py:1591`
- `backend/tasks/workflow_registry.py:282`
- `backend/tasks/contract_registry.py:267`

现象：

部分对象支持 deleted ids：

- task domain 有 `deleted_domain_ids`。
- specific task record 有 `deleted_task_ids`。

但其他默认派生对象没有一致的 tombstone：

- flows 默认 overlay。
- projection bindings 默认派生。
- flow contract bindings 默认派生。
- adoption plans 默认派生。
- memory request profiles 默认派生。
- workflows 默认 merge。
- contract specs 默认 merge。

风险：

用户删除某类对象后，后续读取可能因为默认值或派生逻辑再次出现同类对象。不同 registry 对“删除默认种子”的语义不一致，会让管理台行为不可预测。

建议：

- 统一 default seed 语义。
- 每个 registry 都明确支持三种状态：`default_visible`、`custom_override`、`hidden_by_tombstone`。
- overview 展示三种数量，不把派生对象算作显式用户配置。

### R6. 新旧运行策略协议仍并行

严重级别：中高

位置：
- `backend/tasks/flow_models.py:170`
- `backend/tasks/flow_models.py:187`
- `backend/tasks/flow_models.py:207`
- `backend/tasks/assembly_builder.py:305`
- `backend/tasks/assembly_builder.py:306`
- `backend/orchestration/runtime_loop/task_run_loop.py:538`
- `backend/orchestration/runtime_loop/task_run_loop.py:4894`

现象：

`TaskAgentAdoptionPlan` 的 `to_dict()` 会把 authority 改成 `task_system.task_execution_policy`，但对象本身和存储路径仍叫 adoption plan。

装配输出同时包含：

- `task_execution_policy`
- `task_agent_adoption_plan`

运行环也仍会读取 legacy 字段：

- `task_operation.get("task_agent_adoption_plan")`
- `task_operation.get("task_execution_policy") or task_operation.get("task_agent_adoption_plan")`

风险：

- 同一运行策略有两个名字，容易出现一边更新、一边遗漏。
- 瘦身时无法判断旧字段是否还能删。
- 新测试可能只覆盖新字段，旧 runtime 仍靠 legacy 字段运行。

建议：

- 先建立 cutover 表，列出所有 legacy 字段读写点。
- 装配结果只保留 `task_execution_policy`。
- runtime 入口保留一次性迁移适配器，但内部模型只使用新字段。
- 删除 `to_legacy_dict()` 前补回归测试，确认旧字段缺失时运行不退化。

### R7. 模板匹配 fallback 可能掩盖配置缺失

严重级别：中

位置：
- `backend/tasks/template_registry.py:437`
- `backend/tasks/template_registry.py:512`
- `backend/tasks/template_registry.py:624`

现象：

模板匹配默认 `match_source = "heuristic_fallback"`。如果没有命中显式模板、bundle、route hint、capability contract 或 source kind，最终会退回：

```text
template.general.main_conversation
```

如果传入不存在的模板 ID，`_select_existing_template_id()` 也可能退回通用模板。

风险：

- 用户或上游系统显式指定了错误模板时，可能没有硬失败。
- 任务本应进入工具执行、PDF、结构化数据或工作区修改，却退回普通对话。
- `fallback_used` 只有结果里能看见，运行链路未必把它作为阻断条件。

建议：

- 显式模板 ID 不存在时 fail-closed。
- binding contract 命中但模板缺失时 fail-closed。
- 只有无显式约束的普通对话才能 fallback 到 general template。
- `fallback_used=True` 进入运行前诊断或人工确认策略。

### R8. 任务图、协调任务、拓扑和协议存在权威源重叠

严重级别：中

位置：
- `backend/tasks/flow_registry.py:1888`
- `backend/tasks/flow_registry.py:1987`
- `backend/tasks/flow_registry.py:2068`
- `backend/tasks/flow_registry.py:2125`
- `backend/tasks/flow_registry.py:2163`

现象：

`list_coordination_tasks()` 会从 coordination task 里补齐 graph nodes、edges、subtask refs、communication modes。

`list_task_graphs()` 又会从 coordination task 派生 task graph：

```text
graph.{coordination_task_id.removeprefix("coord.")}
```

同时还有 topology templates 和 communication protocols 作为独立管理对象。

风险：

- 同一个结构可能同时存在于 coordination task、task graph、topology template。
- 用户改 task graph 后，coordination task 派生图仍可能存在。
- 删除具体任务时会修改 coordination task，但不一定同步修改已存 task graph。
- 运行态到底以哪个图为准不够清楚。

建议：

- 明确唯一权威源：建议 task graph 成为执行图权威源。
- coordination task 只保存业务语义和运行策略引用。
- topology template 只作为生成草稿的模板，不进入运行态。
- communication protocol 只通过 graph edge 或 coordination policy 引用，不自动派生。

### R9. 默认产物路径仍指向系统规划目录

严重级别：中

位置：
- `backend/tasks/assembly_support.py:202`
- `backend/tasks/assembly_support.py:218`

现象：

任务默认产物路径 fallback 为：

```text
docs/系统规划/任务系统实测记录/artifacts
```

风险：

这会把运行产物、实测记录、系统规划文档混在一起。用户已经明确要求风险报告不要写到系统规划目录，说明项目文档层级已经开始区分。任务运行产物继续默认落到系统规划下，会增加文档污染和清理成本。

建议：

- 默认产物路径迁移到 `runtime-loop-test/`、`storage/artifacts/` 或独立 `docs/运行记录/`。
- 系统规划目录只保留设计和计划，不作为运行产物默认落点。

## 四、已验证问题

### 4.1 测试失败：overview 默认派生绑定

命令：

```powershell
python -m pytest backend/tests/task_system_api_regression.py backend/tests/task_graph_registry_test.py backend/tests/task_template_registry_regression.py backend/tests/contract_compiler_workflow_test.py backend/tests/task_contract_registry_test.py backend/tests/contract_compiler_coordination_test.py backend/tests/runtime_assembly_builder_test.py -q
```

结果：

```text
1 failed, 39 passed
```

失败点：

- `backend/tests/task_template_registry_regression.py:115`

实际问题：

`TaskFlowRegistry(tmp_path).build_overview()` 在空目录中统计到 `projection_binding_count == 4`。这来自 `list_projection_bindings()` 对默认任务记录的派生，而不是用户显式写入的 projection binding。

判断：

这不是简单改测试期望就能解决的问题。它暴露的是“overview 统计口径不清”和“读取接口有派生写入副作用”的结构问题。

## 五、瘦身判断

### 可以优先收口的旧残留

1. `task_agent_adoption_plan` legacy 输出和 `to_legacy_dict()`。
2. `assignments` 作为 specific task record 的 legacy fallback。
3. coordination task 到 task graph 的兼容派生路径。
4. `legacy_builtin_tool_lane_route` 模板匹配原因。
5. 默认产物路径里的 `docs/系统规划/任务系统实测记录/artifacts`。

这些都不建议直接删。应先写 cutover 计划，确认运行链路只读新字段，再删除旧字段和旧测试。

### 不建议直接删除的内容

1. contract registry 默认契约。
2. workflow registry 默认 workflow。
3. coordination graph compiler。
4. task graph models。

这些虽然和旧协调任务有重叠，但仍可能是新执行图体系的基础。应先确定权威源，再做归并。

## 六、建议重构路径

### 阶段 1：止血

目标：让读取不再偷偷写盘。

动作：

1. 给所有 registry 增加只读读取路径。
2. `list_*` 禁止 `_write_json()`。
3. 新增显式 `normalize_*()` / `migrate_*()` 方法。
4. overview 统计拆成 explicit、derived、default_seed。
5. 修复当前失败测试，新增“空目录 overview 不落盘”回归测试。

### 阶段 2：配置可信度

目标：坏配置不能被默认值掩盖。

动作：

1. `_read_json()` 改为结构化读取结果。
2. API overview 展示配置读取错误。
3. 运行态关键配置读取失败 fail-closed。
4. 写入使用临时文件和原子替换。
5. 增加 registry health report。

### 阶段 3：权威源重组

目标：减少重复定义。

动作：

1. `TaskDefinitionRegistry`：domain、specific task、flow。
2. `TaskPolicyRegistry`：projection、contract binding、execution policy、memory request。
3. `TaskGraphRegistry`：task graph、topology template、communication protocol。
4. `TaskSystemFacade`：只做组合查询和跨层校验。

### 阶段 4：legacy 清理

目标：真正瘦身。

动作：

1. 删除 `task_agent_adoption_plan` 对外输出。
2. 删除 assignments fallback。
3. 删除 coordination task 到 task graph 的运行态兼容派生。
4. 删除 legacy route reason。
5. 清理旧测试，保留新结构回归测试。

## 七、建议下一步审查对象

任务系统和编排系统强相关，下一步建议审查：

1. `backend/api/tasks.py`：管理 API 是否把默认派生对象当作显式对象展示或删除。
2. `frontend/src/components/workspace/views/task-system`：前端任务工作台是否混合了任务定义层、运行策略层、协调图层。
3. `backend/orchestration/runtime_loop/langgraph_coordination_runtime.py`：协调运行态到底使用 coordination task 还是 task graph 作为权威源。

其中我建议优先审查 `backend/api/tasks.py` 和任务系统前端。因为如果 API 和 UI 已经把派生对象当成真实配置，后面瘦身时最容易误删或误展示。
