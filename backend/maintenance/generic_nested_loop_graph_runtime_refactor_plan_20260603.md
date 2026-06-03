# Generic Nested Loop Graph Runtime Refactor Plan

## 背景

写作图连续出现章节正文越写越短的问题，表面上是 prompt 和模型执行稳定性问题，实际暴露的是图系统权力边界错误。

上一次方案 `backend/maintenance/writing_chapter_unit_runtime_plan_20260603.md` 把“单章循环执行”塞进 `GraphNodeWorkOrderExecutor`，并引入 `chapter_workflow_policy`、`chapter_unit_execution_policy` 等写作专用运行键。这个方向应废弃：executor 被赋予了拆分章节、循环推进、修稿汇总和质量判断的业务权力，破坏了通用图运行架构。

目标修正为：

- 图 runtime 只提供通用运行基础设施。
- loop 只提供通用运行控制、迭代推进、重置和恢复。
- 业务结构由编辑器和任务图显式表达。
- 写作图可以画出“一章到十章、十章到一卷、一卷到全文”的嵌套循环，但 runtime 不认识“章节”“卷”“正文”等业务概念。

## 当前结构理解

| 层级 | 现有文件 | 正确职责 |
| --- | --- | --- |
| 编辑器 / TaskGraph | `backend/task_system/graphs/task_graph_standard_models.py` | 保存用户画出来的节点、边、loop frame、节点契约和业务结构 |
| 归一化 / 发布 | `backend/task_system/compiler/layered_graph_normalizer.py`, `backend/task_system/compiler/graph_harness_config_publisher.py` | 把 TaskGraph 编译成 GraphHarnessConfig，保留结构语义，不新增业务推断 |
| Runtime | `backend/harness/graph/runtime.py`, `backend/harness/graph_harness.py` | 启动 graph run、锁定 config、创建 envelope、隔离运行实例 |
| Loop | `backend/harness/graph/loop.py`, `backend/harness/graph/loop_engine.py`, `backend/harness/graph/resume.py` | 调度 ready 节点、接收结果、执行 route policy、维护 loop state、checkpoint、requeue、resume |
| ContextMaterializer | `backend/harness/graph/context_materializer.py` | 只根据当前节点和当前 loop state 装配输入包与 prompt |
| WorkOrderExecutor | `backend/harness/graph/work_order_executor.py` | 执行一个已调度 work order，并把 agent/tool/human 结果归一成 NodeResultEnvelope |
| Agent Runtime | 项目 agent 执行回调 | 完成一次模型 turn，不决定图结构推进 |

## 已发现问题

### 1. Executor 混入写作业务循环

`backend/harness/graph/work_order_executor.py` 当前存在 `_chapter_unit_execution_policy`、`_execute_chapter_unit_loop`、`_chapter_unit_work_order`、`_chapter_unit_quality_acceptance` 等逻辑。

问题：

- executor 私自创建伪 work order，绕开 GraphLoop 的调度、checkpoint、resume、active work order 记录。
- 子 work order 不是编辑器画出来的节点，任务图不可见，运行监控不可追踪。
- 子任务继承父节点 prompt，必须在 executor 里临时改 `agent_instruction`，这会造成 prompt 权力混乱。
- 章节循环、修复、汇总成为 executor 的隐藏业务能力，后续任何业务都可能继续往 executor 塞特化逻辑。

处理：删除这条写作专用 executor 链路。

### 2. Runtime contract 出现写作专用键

`backend/task_system/graphs/task_graph_models.py` 和 `scripts/configure_writing_modular_novel_graph.py` 中出现：

- `chapter_workflow_policy`
- `chapter_unit_execution_policy`

问题：

- 这些键不是通用 runtime contract，而是写作图业务结构。
- 它们让“节点配置”和“图运行控制”重新耦合。
- 以后换成别的业务循环时会重复制造 `xxx_unit_execution_policy`。

处理：从通用 runtime key 白名单和写作配置中移除。需要循环时使用通用 loop frame 和 route policy。

### 3. Loop 已有能力但缺少一等迭代身份

当前 `GraphLoop` 已经可以：

- 读取 `graph_config.loop_frames`
- 基于 `route_policy` 决定 continue / exit
- reset scope 内节点状态
- 更新 `initial_inputs`

但它缺少：

- 明确的父子 loop frame 关系。
- 当前迭代身份和迭代游标。
- 重复执行同一节点时的结果索引策略。
- 迭代级上下文注入。
- scope reset 是否保留历史结果的显式策略。

这会导致“一组节点重复运行”时只能依赖覆盖 `result_index[node_id]` 和隐式 `initial_inputs`，不适合章节、批次、卷这类嵌套循环。

### 4. Progress receipt 路由混入章节字段

`backend/harness/graph/loop.py` 的 `_evaluate_progress_receipt_route` 当前直接写入：

- `chapter_index`
- `active_chapter_start_index`
- `active_chapter_end_index`
- `batch_start_index`
- `batch_end_index`
- `active_chapter_range`
- `units_per_batch`

问题：

- `progress_receipt` 模式本身可以通用，但字段推进不应写死成章节语义。
- 正确做法是由 route policy 声明 receipt 字段到 input 字段的映射、增量、范围和 completion 条件。

处理：把 progress receipt route 改成配置驱动；写作图只是在配置中使用章节字段名。

## 目标设计

### 权力链

```text
TaskGraph(editor drawn structure)
-> Publisher(normalized GraphHarnessConfig)
-> Runtime(graph run start packet)
-> GraphLoop(generic schedule, route, iteration state)
-> ContextMaterializer(current node input package)
-> WorkOrderExecutor(single work order execution)
-> Agent Runtime(single model turn)
-> GraphLoop(accept result and continue / exit)
```

任何层级不得越权：

- Runtime 不识别写作、章节、审核。
- Loop 不识别写作业务，只识别 frame、cursor、route、receipt、scope。
- Executor 不拆图、不建隐藏循环、不决定下一节点。
- Prompt 只描述 agent 的角色、职责、输入、输出和裁决标准，不描述开发式节点用途。

### 通用 loop frame contract

在 `GraphHarnessConfig.loop_frames` 中扩展并标准化如下字段：

| 字段 | 含义 |
| --- | --- |
| `frame_id` | loop frame 唯一 ID |
| `scope_id` | loop 作用域 |
| `parent_scope_id` | 父 loop scope，可为空 |
| `entry_node_id` | 当前 loop 首个执行节点 |
| `router_node_id` | 决定 continue / exit 的节点 |
| `continue_node_id` | continue 时重新激活的节点 |
| `exit_node_id` | exit 后激活的节点 |
| `scope_node_ids` | 本 loop reset 覆盖的节点集合 |
| `cursor_key` | 当前迭代游标字段 |
| `start_key` | 起始游标字段 |
| `end_key` | 结束游标字段 |
| `step` | 每次推进步长 |
| `iteration_index_key` | 迭代序号字段 |
| `iteration_identity_template` | 迭代身份模板，例如 `{scope_id}:{cursor}` |
| `progress_receipt_key` | 可选，路由读取的收据键 |
| `reset_scope_on_continue` | continue 时是否重置 scope 内节点状态 |
| `preserve_iteration_results` | 是否保留历史迭代结果 |
| `aggregate_policy` | 迭代结果聚合策略 |

### 通用 route policy

保留 `metric_target` 和 `progress_receipt` 两类路由，但禁止写死业务字段。

`metric_target`：

- 从 result / diagnostics / structured_output 读取 metric。
- 应用 `patch_rules` / `derived_fields`。
- 比较 `current_key` 与 `target_key`。

`progress_receipt`：

- 从指定节点结果或当前结果读取 `progress_receipt_key`。
- 根据配置读取 completion 字段。
- 根据配置应用 receipt 到 inputs 的映射。
- 根据 `continue_node_id` / `exit_node_id` 推进。

建议新增通用字段：

| 字段 | 含义 |
| --- | --- |
| `receipt_complete_key` | receipt 中表示本 frame 完成的字段 |
| `receipt_metric_key` | receipt 中表示本轮增量的字段 |
| `receipt_to_input_mappings` | 把 receipt 字段写入 initial_inputs |
| `input_patch_rules` | 对 initial_inputs 执行通用 patch |
| `derived_fields` | 派生字段，如范围字符串 |

### 迭代状态

`GraphLoopState.loop_state.frames[frame_id]` 应记录：

```text
status
iteration_index
cursor
start
end
step
active_iteration_id
parent_scope_id
last_decision
history
```

同时增加迭代结果索引：

```text
loop_state.iteration_results[frame_id][iteration_id][node_id] = result_ref
```

这样同一个节点重复执行时：

- `result_index[node_id]` 仍表示当前迭代的最新结果，供调度和下游读取。
- `iteration_results` 保存历史迭代结果，供汇总节点读取。
- resume/requeue 可以知道当前 frame 停在哪一轮。

### ContextMaterializer 注入迭代上下文

每个 work order 输入包增加通用 loop 上下文：

```text
loop_context:
  active_frames
  current_scope_id
  current_frame_id
  iteration_index
  iteration_id
  cursor_key
  cursor_value
  parent_iterations
```

写作图中，单章写手通过 graph 配置把 `cursor_key=chapter_index` 注入到 prompt 输入；ContextMaterializer 不知道这是章节，只提供当前迭代事实。

### 写作图结构表达

写作图应该由编辑器显式画出以下节点，而不是 executor 内部伪造：

```text
chapter_outline_self_repair
-> chapter_write_unit
-> chapter_unit_self_repair
-> chapter_unit_router
   continue -> chapter_write_unit
   exit -> chapter_batch_assemble
-> chapter_batch_review
-> memory_commit_chapter
-> chapter_batch_router
```

对应 loop frame：

```text
frame_id: loop.chapter_unit
scope_id: loop.chapter_unit
entry_node_id: chapter_write_unit
router_node_id: chapter_unit_router
continue_node_id: chapter_write_unit
exit_node_id: chapter_batch_assemble
scope_node_ids:
  - chapter_write_unit
  - chapter_unit_self_repair
  - chapter_unit_router
cursor_key: chapter_index
start_key: batch_start_index
end_key: batch_end_index
step: 1
iteration_identity_template: "{scope_id}:chapter-{cursor}"
reset_scope_on_continue: true
preserve_iteration_results: true
```

十章到一卷、一卷到全文也用同一套结构，只是 cursor、scope 和节点不同。

## 实施计划

### 阶段 1：删除写作专用 executor 链路

文件：

- `backend/harness/graph/work_order_executor.py`
- `backend/task_system/graphs/task_graph_models.py`
- `scripts/configure_writing_modular_novel_graph.py`
- `backend/tests/writing_chapter_loop_progress_regression.py`

动作：

- 删除 `_execute_chapter_unit_loop` 及所有 `_chapter_unit_*` executor helper。
- 删除 `chapter_workflow_policy`、`chapter_unit_execution_policy` runtime key。
- 写作配置不再通过 runtime binding 下发隐藏章节循环。
- 删除或重写保护旧 executor 伪循环的测试。

完成标准：

- `rg "chapter_unit_execution_policy|chapter_workflow_policy|_execute_chapter_unit_loop"` 不再命中通用 runtime/executor。

### 阶段 2：扩展 loop frame normalization 与预览

文件：

- `backend/task_system/compiler/layered_graph_normalizer.py`
- `backend/task_system/compiler/graph_harness_config_publisher.py`
- `backend/task_system/compiler/loop_plan_preview.py`

动作：

- 支持 `parent_scope_id`、`scope_node_ids`、cursor、start/end、step、iteration identity、结果保留等通用字段。
- module expansion 时正确 scope 节点 ID 和 frame ID。
- loop preview 增加缺失字段检查，尤其 entry/router/continue/exit/cursor。

完成标准：

- 编辑器或脚本生成的 loop frame 能完整发布到 GraphHarnessConfig。
- preview 能发现 loop frame 缺关键节点或游标字段。

### 阶段 3：增强 GraphLoop 迭代状态

文件：

- `backend/harness/graph/models.py`
- `backend/harness/graph/loop.py`
- `backend/harness/graph/resume.py`

动作：

- 初始化 frame cursor 和 iteration identity。
- continue 时推进 cursor 和 iteration_index。
- reset scope 时只重置当前 frame 节点，保留或清除历史结果由 `preserve_iteration_results` 决定。
- `result_index` 保持当前迭代语义，历史写入 `loop_state.iteration_results`。
- requeue/resume 保留 frame 当前游标，不回退到业务上游。

完成标准：

- 同一节点可以在同一个 graph run 中被通用 loop 多次执行。
- 每轮结果都能通过 iteration identity 查询。
- 断点恢复后不会丢失当前 loop 位置。

### 阶段 4：通用化 progress receipt route

文件：

- `backend/harness/graph/loop.py`
- `backend/task_system/runtime_semantics/chapter_progress.py`（仅限写作收据归一化保留）
- `backend/task_system/compiler/graph_harness_config_publisher.py`

动作：

- `_evaluate_progress_receipt_route` 去掉写死的章节字段推进。
- 使用 `receipt_metric_key`、`receipt_complete_key`、`receipt_to_input_mappings`、`patch_rules`、`derived_fields` 推进。
- 写作章节进度收据仍可作为业务收据存在，但只能由写作节点或写作质量门产生，Loop 只按配置读取。

完成标准：

- 通用 graph 测试能用任意字段名跑 progress receipt route。
- 写作图通过配置声明章节字段映射后仍能推进。

### 阶段 5：ContextMaterializer 注入 loop context

文件：

- `backend/harness/graph/context_materializer.py`
- `backend/harness/graph/flow_packet.py`（如输入包 schema 需要同步）

动作：

- 在 work order `input_package` 和 `dispatch_context` 中加入当前 active loop frames、iteration id、cursor value。
- 不在 materializer 内生成写作特定提示词。
- 确保 agent prompt 可以读取“当前迭代事实”，而不是自己推断章节范围。

完成标准：

- 写手节点收到的输入里有当前章节索引，但字段来自 loop config。
- 非写作图也能获得相同的通用 loop context。

### 阶段 6：改写写作图为显式 loop 结构

文件：

- `scripts/configure_writing_modular_novel_graph.py`
- 相关写作 prompt 配置文件

动作：

- 画出单章写作、单章自修、单章路由、十章汇总、批次审核、记忆提交、批次路由节点。
- 单章写手 prompt 只写当前迭代章节。
- 单章自修只修当前章节。
- 汇总节点只聚合当前 batch 的 iteration results，不扩写、不改事实。
- 审核补充连续性检查：不允许明显矛盾、跳章、人物状态前后冲突。

完成标准：

- 图结构能在编辑台看到，不再依赖隐藏 runtime policy。
- 章节生产粒度由 loop 控制，不靠 prompt 假装拆任务。

### 阶段 7：测试与真实运行

测试：

```powershell
pytest backend/tests/graph_harness_api_regression.py backend/tests/graph_task_runtime_facade_regression.py backend/tests/writing_graph_language_preservation_regression.py backend/tests/writing_chapter_loop_progress_regression.py -q
```

新增或重写测试：

- 通用 loop frame 重复执行同一组节点。
- 嵌套 loop frame 的 parent/child cursor 独立推进。
- continue reset scope 后当前迭代结果覆盖，历史 iteration result 保留。
- progress receipt route 使用任意字段映射，不依赖章节字段。
- requeue/resume 不跨 loop continuation 回退到上游结构节点。
- 写作图生成的 chapter unit loop 不包含写作专用 runtime key。

真实运行：

- 固定后端 `http://127.0.0.1:8003`。
- 固定前端 `http://127.0.0.1:3000`。
- 发布写作图。
- 从当前大纲后重跑 01-10 章或指定批次。
- 检查每章字数、十章汇总、审核连续性、记忆提交结果。

## 清理范围

必须清理：

- executor 内写作专用 unit loop。
- runtime key 白名单中的写作执行策略。
- 写作脚本中的隐藏章节 workflow policy。
- 保护旧 executor 伪循环的测试。
- 废弃计划对后续实现的误导，应在该旧文档顶部标记为 obsolete。

暂不清理：

- `chapter_progress.py` 中写作收据归一化逻辑。它属于写作业务收据处理，可保留，但 Loop 不能写死调用它作为唯一 progress receipt 模式。
- 写作 prompt library 中与角色职责、输出格式、质量标准相关的改动。除非实施阶段发现它们仍在要求 agent 假装执行隐藏子任务。

## 风险

- 改动跨 compiler、loop、executor、写作配置和测试，必须按阶段实施，不能只改 prompt。
- 结果索引变化可能影响现有下游读取当前节点结果的路径，需保证 `result_index[node_id]` 的当前迭代语义不变。
- progress receipt 通用化后，写作配置必须补齐字段映射，否则章节推进会阻塞。这是合理的 fail-closed。
- 嵌套 loop 的 requeue/resume 是高风险点，必须有回归测试。

## 审查结论

这次修正不应继续在单 agent 执行链路里加能力。单 agent 链路只执行 work order，不负责循环拆分。需要改的是 GraphLoop 的通用 loop frame 能力，以及写作图的显式结构。

如果按本计划实施，图系统会回到正确边界：

- 编辑器画结构。
- Publisher 发布结构。
- Loop 推进结构。
- Executor 执行节点。
- Agent 做当前节点职责。

