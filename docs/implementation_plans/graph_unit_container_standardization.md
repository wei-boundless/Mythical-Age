# GraphUnit Container Standardization

## Goal

把父图中的 `graph_unit` 统一修成可复用子图的时序占位节点。父节点只负责在父图时间线上占据一个可等待、可交接、可追踪的运行点，并通过 `linked_graph_id` 启动内部子图；它不是 agent，也不拥有 prompt、projection、model requirement 或 agent profile 语义。

## Design Rules

1. `graph_unit` 父节点是图容器引用，不是执行 agent。
2. 父节点允许保留：`linked_graph_id`、版本锚点、输入输出端口、隔离策略、可见性策略、handoff 契约、嵌套运行计划、时序/phase 信息、执行器策略。
3. 父节点禁止携带：`agent_id`、`agent_group_id`、`work_posture`、`projection_id`、`projection_overlay_id`、`role_prompt`、`model_requirement`。
4. 总任务图自身是编排容器，不携带图级 `model_requirement`。
5. 子图内部节点才是 agent/runtime/projection/prompt 的真实承载者。
6. wrapper 任务资产不再为 `task.writing.modular_novel.master/design_init/chapter_cycle/finalize` 生成 workflow、flow、assignment、projection binding、adoption plan、memory request profile；这些旧残留要清理。
7. 运行期编译器必须把显式 `graph_unit` 节点编译为 `role=nested_graph`、空 agent/projection/runtime model，并保留其嵌套图 handle。
8. 回归测试必须覆盖配置源、runtime spec、contract manifest、execution package 四层。
9. 资源节点从执行链剥离后仍属于控制面输入。`memory_repository` 等资源节点不得进入执行队列，但正式记忆注册、记忆边解析、读写/提交链路必须同时消费 `nodes` 与 `resource_nodes`。
10. 记忆边可以只指向资源节点而不重复声明仓库 id；运行期必须能通过 `repository_node_id` 或 memory edge 的 target/source resource node 解析出逻辑仓库。

## Implementation Steps

1. 修改写作图生成器：
   - 删除 wrapper task asset 生成。
   - 清理已有 wrapper task asset 残留。
   - 让 `_graph_unit_node` 输出纯容器字段。
   - 删除 master graph 的图级 `model_requirement`。
2. 修改 runtime compiler：
   - 对 `node_type == "graph_unit"` 使用 graph-unit 专用编译路径。
   - 禁止 graph-unit 从父图 coordinator 或 agent group 继承 agent 语义。
   - 合并显式 graph-unit 与 timeline-derived runtime plan 时，保持 nested runtime 信息，但清空 agent/projection/model。
3. 修改 contract/compiler 或装配相关检查：
   - graph-unit 的 node contract 可以存在用于父图追踪，但不触发 runtime profile 校验。
   - graph-unit 不参与 node runtime assembly。
4. 修改正式记忆控制面：
   - `FormalMemoryService.sync_graph_spec` 同时读取 `nodes` 与 `resource_nodes`，资源节点不执行但仍注册仓库与 collection。
   - runtime memory edge descriptor 同时用 `nodes` 与 `resource_nodes` 建立节点索引，允许从资源端反查 repository id。
5. 补充测试：
   - 写作配置回归测试确认 master graph 和 graph-unit 节点无 agent/projection/model/prompt 污染。
   - 标准视图测试确认显式 graph-unit 即使输入里带 agent 字段，编译后也归一成纯容器。
   - 确认 wrapper task asset 残留被删除。
   - 正式记忆测试确认资源节点被移出执行节点后，write_candidate、commit、read 仍能通过 `resource_nodes` 完成。
6. 重新生成存储配置并运行 focused tests。

## Verification

至少运行：

```powershell
python -m pytest backend/tests/writing_modular_novel_graph_config_regression.py backend/tests/task_graph_standard_models_test.py -q
```

如改动触及执行包或 runtime manifest，补跑：

```powershell
python -m pytest backend/tests/task_system_api_regression.py backend/tests/langgraph_coordination_runtime_regression.py -q
```
