# 通用任务图编辑器结构审查与重构计划

日期：2026-05-22

## 1. 审查结论

当前图编辑器最大的问题不是视觉不够精致，而是结构不够干净。

它现在同时存在三套心智：

1. `TaskGraphDefinition.nodes / edges`：真正保存、编译、运行的 canonical 图定义。
2. `TaskGraphStandardView.units / port_edges / graph_module_runtime`：后端从图定义和 metadata 编译出来的标准视图。
3. `metadata.composable_graph` 覆盖层：前端“图工作台”可以写入的影子可组合图。

这三套东西都被放进了“编辑器”心智里，用户很容易以为自己在编辑同一张可运行任务图，实际可能只是在改展示坐标、影子端口边或 metadata 覆盖层。这个结构能跑一些图，但不够坚固，也不够通用。

正确方向是：

```text
一个 canonical 图编辑器
多个只读或半只读诊断视图
所有可运行编辑都必须写回 TaskGraphDefinition.nodes / edges / contract_bindings / runtime_policy
standard view / composable view 只负责解释、检查、展开、对照，不承担第二套运行图真相
```

## 2. 当前主链路

### 2.1 前端草稿与保存

入口：

- `frontend/src/components/workspace/views/TaskSystemView.tsx`

关键路径：

```text
taskGraphDraftV2
  -> syncTaskGraphTopology()
  -> updateTaskGraphNode() / updateTaskGraphEdge()
  -> saveTaskGraphStack()
  -> buildTaskGraphUpsertPayload()
  -> upsertTaskSystemTaskGraph()
```

问题：

- `syncTaskGraphTopology()` 每次更新都重新推断入口/出口，只要节点边变化就可能覆盖用户显式边界。
- `updateTaskGraphNode()`、`updateTaskGraphEdge()` 是当前真正写 canonical 图的入口，但它们分散传给多个页面，导致每个页面都像“主编辑器”。
- `saveTaskGraphStack()` 保存后又调用 `syncTaskGraphTopology()`，这会把保存后的状态再次过一遍前端推断逻辑。

### 2.2 标准视图与影子可组合图

入口：

- `backend/task_system/graphs/task_graph_standard_models.py`
- `backend/task_system/graphs/composable_graph_builder.py`
- `frontend/src/components/workspace/views/task-system/TaskGraphComposableEditorPage.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphObjectInspector.tsx`

后端已经明确说：

```text
metadata_overlay_shadow_model
read_only_shadow_model
```

这说明 composable graph 本质是标准视图/影子视图，不是 canonical 图定义。

但前端 “图工作台” 里可以新增 `metadata.composable_graph.port_edges`。这会制造一个很危险的错觉：用户看到“显式端口边”，以为它就是运行边；但运行编译器的主路径仍然主要消费 `graph.edges`、`timeline_blocks` 和 layered graph。

### 2.3 运行编译与调度

入口：

- `backend/task_system/compiler/coordination_graph_compiler.py`
- `backend/task_system/compiler/layered_graph_normalizer.py`
- `backend/runtime/graph_runtime/scheduler.py`

已经完成的正确方向：

- scheduler diagnostics 已标明 `scheduling_authority = explicit_dependency_ready_set`。
- `legacy_timing_gate_enabled = False`。
- `phase_id / sequence_index / timeline_group_id` 只作为 lifecycle/display/diagnostic 信息。

但前端还没有完全跟上这个事实，仍把旧字段作为强编辑对象展示。

## 3. 噪声清单

这些信息现在对用户搭建可运行任务图帮助很小，甚至会误导用户。

### 3.1 `sequence_index`

位置：

- `TaskGraphNodeUnitInspector.tsx`
- `TaskGraphTimelinePage.tsx`
- `TaskGraphTopologyPage.tsx`
- `taskGraphTimeline.ts`
- `TaskGraphStandardNodeSpec`

问题：

- 它不再决定 ready/blocked。
- 如果继续显示成“顺序”或 “Step”，用户会误以为编号就是执行因果。
- 需要顺序时，应该画显式 activation edge 或 blocking temporal edge。

处理：

- 从主编辑器删除。
- 可在诊断页显示为“展示排序 / 历史坐标”。
- 预检应提示：`sequence_index` 不产生运行依赖。

### 3.2 `main_chain`

位置：

- `TaskGraphNodeUnitInspector.tsx`
- `TaskGraphTopologyPage.tsx`
- `taskGraphTimeline.ts`
- `TaskGraphStandardNodeSpec`

问题：

- 它看起来像“主链权威”，但现在不是调度权威。
- 对通用图编辑器来说，“主链”不是足够通用的运行概念；真实关系应该由入口、出口、显式边、汇合策略和产物生命周期表达。

处理：

- 主编辑器不再展示。
- 历史图迁移时只作为 metadata/display 保留。
- 如果以后需要“关键路径”，应由图分析推导，不由用户手填。

### 3.3 `blocks_phase_exit`

位置：

- `TaskGraphNodeUnitInspector.tsx`
- `TaskGraphTimelinePage.tsx`
- `taskGraphTimeline.ts`
- `scheduler.py` 诊断仍会展示 blocking node ids

问题：

- 当前 scheduler ready-set 不再按 phase exit gate 默认阻塞。
- 这个字段如果被 UI 展示成强控制，会产生假安全感。

处理：

- 从主编辑器移除。
- 如果需要阶段出口控制，应转成真实边界规则：barrier node、approval edge、commit boundary、manual gate。

### 3.4 `timeline_group_id`

位置：

- 后端模型、标准视图、timeline 视图仍保留。

问题：

- 它像并发组，但不负责同步启动或汇合。
- 对用户搭并发图没有实际帮助。

处理：

- 主编辑器隐藏。
- 只在 legacy diagnostics 中显示。
- 真并发由“无互相依赖 + 共同下游 join/barrier + wait/join policy”表达。

### 3.5 `phase_id / phase_definitions / timeline_blocks`

问题不是它们完全没用，而是职责被说得过强。

可保留用途：

- 生命周期坐标。
- 图模块导入窗口。
- 诊断和监控分组。
- 长任务账本定位。

不能再承担：

- 默认阻塞链。
- 并发权威。
- 自动阶段出口。
- 运行 step。

处理：

- 页面标题从“拓扑时序控制”改成“生命周期与运行诊断”。
- 所有说明文案必须标明：生命周期坐标不是执行依赖。

### 3.6 `metadata.composable_graph.port_edges`

位置：

- `TaskGraphPortEdgeInspector.tsx`
- `taskGraphModuleComposition.ts`
- `composable_graph_builder.py`

问题：

- 当前是 metadata overlay shadow model。
- 它可以通过后端 standard view 进入 `port_edges`，但不等同于 canonical `graph.edges`。
- 如果 UI 允许用户新增“显式端口边”，必须告诉用户它是否会生成运行边。

处理：

- 短期：新增醒目标识“覆盖层，不是运行边”。
- 中期：禁止在主图编辑器里新增 overlay port edge；只能新增 canonical edge。
- 长期：如果端口边要成为运行边，必须新增 `TaskGraphEdgeDefinition.port_mapping` 或正式 `edges[].interface_binding`，不能藏在 metadata overlay。

### 3.7 “旧图结构校验”

位置：

- `taskGraphPreflight.ts`

问题：

- 文案把当前编辑器说成“旧图结构”，但它仍参与预检。
- 这会让用户不知道哪个校验才是权威。

处理：

- 改名为“编辑器结构校验”。
- source 从 `legacy.editor_graph_spec` 改成当前权威来源。
- 如果确实只是旧校验，应删除或只放在迁移诊断里。

## 4. 结构性缺陷

### 4.1 两个主编辑器在争夺图结构

当前有：

- `topology`：编辑 raw `nodes/edges`。
- `modules`：编辑 standard/composable 派生出来的 `units/port_edges`，同时又能写回部分 raw node/edge 和 metadata overlay。

这不是“多视图”，而是两个主编辑器重叠。

后果：

- 用户不知道应该在哪个页面建图。
- 拓扑页和图工作台都能改变边语义。
- standard view 刷新前后，用户看到的对象可能变化。
- overlay edge 与 canonical edge 的运行含义不一致。

修正：

- 只保留一个主结构编辑器：`Graph Builder`。
- 它只编辑 canonical `nodes/edges`。
- `modules/composable` 改为 `Compiled View`，只读展示 standard view、图模块展开、端口映射诊断。
- 任何“从诊断视图修复”的动作，都必须转换成 canonical patch。

### 4.2 默认打开 derived view 是错误导向

位置：

- `TaskGraphWorkbench.tsx`

当前默认：

```text
activeGraphNodes.length ? "modules" : "blueprint"
```

问题：

- 只要已有节点，用户就进入 derived/composable 工作台。
- 这不利于搭建可运行图，反而优先进入影子标准视图。

修正：

- 有节点时默认进入 `graph_builder`。
- standard/composable 只作为“编译视图/诊断视图”。

### 4.3 页面层级过多，且职责重叠

当前层级：

```text
blueprint
agents
topology
modules
responsibility
timeline
memory
risk
contracts
publish
```

问题：

- `agents` 和 `responsibility` 都在改节点执行身份。
- `topology` 和 `modules` 都在改结构。
- `timeline`、`memory`、`risk`、`contracts` 都在改运行语义和边界协议。
- 用户要搭一张能跑的图，必须理解十个页面的边界，这是不合格的编辑体验。

修正为五个一级层：

```text
Graph Builder        主图结构：节点、边、入口、出口、图模块导入节点
Node & Executor      节点身份、Agent、Projection、任务绑定、模型/工具配置
Edges & Contracts    边类型、激活/数据/资源/返修/失败路由、契约绑定、handoff
Resources & Memory   资源节点、记忆仓库、产物仓库、读写提交规则
Validate & Publish   标准视图、运行包、预检、发布、运行绑定
```

`Lifecycle` 不作为主编辑层，而作为 `Validate & Publish` 或 `Graph Builder` 的诊断抽屉。

### 4.4 前端和后端都在做 contract_bindings 归一化

位置：

- `taskGraphSaveMapper.ts`
- `task_graph_models.py`

问题：

- 前端保存时会 normalize graph/node/edge contract bindings。
- 后端模型导入时也会 normalize。
- 双重归一化意味着同一个字段可能有两个权威来源。

修正：

- 后端是 contract binding 归一化权威。
- 前端只负责展示、编辑和提交用户明确填写的 patch。
- 派生字段不要在前端保存时强行写入，除非它是用户显式编辑值。

### 4.5 图模块还没有被编辑器当作 canonical 节点处理

后端运行编译器已有方向：

- timeline block 可以生成 graph module runtime plan。
- explicit `graph_module` node 可与 timeline-derived graph module runtime merge。

但编辑器还把图模块来源放在 `metadata.timeline_blocks` 和 `composable_graph` 视图里。

问题：

- 图模块应该是用户能在图上看到的一个时序占位节点。
- 导入关系应该是 canonical node metadata 或 canonical graph module binding。
- 当前 timeline block 更像隐藏结构，编辑体验不直观。

修正：

- 新增/统一 `graph_module` 节点作为 canonical 图模块占位。
- `linked_graph_id`、`version_ref`、`isolation_policy`、`visibility_policy` 写入该节点的正式字段或 metadata.graph_module。
- `timeline_blocks` 只作为旧图迁移和标准视图派生来源，逐步退出主编辑。

## 5. 目标编辑器结构

### 5.1 唯一真相源

```text
TaskGraphDraftV2
  graph_id/title/domain
  entry_node_id/output_node_id
  nodes[]
  edges[]
  runtime_policy
  context_policy
  contract_bindings
  metadata 仅保存非运行主结构
```

主编辑器可写对象只允许：

- graph
- node
- edge
- resource node
- graph module node
- contract binding
- runtime policy

standard view 可读对象：

- units
- interfaces
- port_edges
- graph_module_expansions
- runtime semantics
- scheduler diagnostics
- issue list

overlay 对象：

- 不再作为默认主编辑对象。
- 如需保留，只能作为高级诊断/迁移工具。

### 5.2 节点编辑

节点只回答这些问题：

- 它是什么执行单元：agent / tool / manual_gate / resource / graph_module / monitor。
- 它绑定哪个任务、Agent、Projection、运行 profile。
- 它需要什么输入契约，产出什么输出契约。
- 它的产物生命周期和写回策略是什么。

节点不再回答：

- 它是不是主链。
- 它在第几个 step。
- 它是否阻塞阶段出口。

### 5.3 边编辑

边必须成为通用图编辑器的中心。

边类型至少分为：

```text
activation
data_handoff
validation
approval
resource_read
resource_write_candidate
resource_commit
artifact_context
revision
failure_route
manual_release
```

每条边必须明确：

- 是否参与 downstream ready。
- 传递什么 payload contract。
- 是否需要 ack。
- 是否要求 committed/accepted/candidate 状态。
- 失败如何传播。
- 是否只传 refs/summary。

这样才能真正解决并发和汇合，而不是靠“主链/阶段/顺序号”假装控制。

### 5.4 图模块

图模块的正确模型：

```text
graph_module node 占据父图一个时序点
linked_graph_id 指向被导入图
父图只看模块输入/输出/提交状态
子图内部按自己的 nodes/edges 运行
父图和子图通过 graph_module handoff contract 通信
```

编辑器要支持：

- 从图库导入图模块。
- 导入后在父图生成一个 canonical `graph_module` 节点。
- 可查看展开图，但展开图只读。
- 修改子图必须进入子图自己的编辑器。

### 5.5 预检与发布

预检必须从“字段检查”升级成“运行可消费性检查”。

必须检查：

- 所有用户可编辑可见边是否有 canonical source。
- 没有 display-only edge 被展示成 runtime edge。
- 多节点图是否存在 activation/data 边。
- join/barrier 是否有明确 upstream。
- resource read/write 是否连接真实资源节点或 repository。
- graph_module 是否有 linked_graph_id 和 handoff contract。
- lifecycle 字段是否被误用成调度字段。
- standard view 和 runtime spec 是否与 draft graph 对齐。

## 6. 实施计划

### 阶段一：清理编辑器 IA 和文案权威

目标：

- 不再让用户把 lifecycle/display 字段当运行规则。
- 默认进入 canonical 图编辑器。
- 先修认知污染，不动大协议。

文件：

- `TaskGraphWorkbench.tsx`
- `TaskGraphLayerNav.tsx`
- `TaskGraphStudioShell.tsx`
- `TaskGraphTopologyPage.tsx`
- `TaskGraphNodeUnitInspector.tsx`
- `TaskGraphTimelinePage.tsx`
- `taskGraphPreflight.ts`

动作：

1. 默认 active layer 从 `modules` 改为 `topology` 或新 `graph_builder`。
2. 将 `modules` 改名为 `compiled` 或 `standard_view`。
3. timeline 文案改为 lifecycle diagnostics。
4. 移除主编辑器中的 Step、主链、阻塞阶段出口控件。
5. `旧图结构校验` 改为 `编辑器结构校验`。
6. support/diagnostic 文案明确 lifecycle coordinate 不控制 ready。

完成标准：

- 用户第一眼看到的是可运行图结构编辑器。
- 页面不再暗示 phase/sequence/main_chain 是调度权威。

### 阶段二：合并主结构编辑面

目标：

- `topology` 和 `modules` 不再各自像一个主编辑器。
- canonical nodes/edges 是唯一可运行结构编辑入口。

文件：

- `TaskGraphTopologyPage.tsx`
- `TaskGraphComposableEditorPage.tsx`
- `TaskGraphObjectInspector.tsx`
- `TaskGraphComposableCanvas.tsx`
- `TaskGraphGraphLayerRail.tsx`
- `taskGraphModuleComposition.ts`

动作：

1. 建立 `TaskGraphBuilderPage`，以 canonical nodes/edges 为唯一写入对象。
2. 把 `TaskGraphObjectInspector` 拆成：
   - `GraphInspector`
   - `NodeInspector`
   - `EdgeInspector`
   - `ResourceInspector`
   - `GraphModuleInspector`
3. composable canvas 只读展示 standard view，不提供 overlay 新增边。
4. 所有从 compiled view 发起的修复动作必须调用 canonical patch。
5. 删除或隔离 `metadata.composable_graph.port_edges` 主编辑入口。

完成标准：

- 新增节点、连边、配置边类型、配置节点执行者都在同一个主编辑器完成。
- standard/composable view 不再制造第二套结构。

### 阶段三：图模块 canonical 化

目标：

- 图模块导入不再藏在 timeline block。
- 父图导入子图成为标准节点/边模式。

文件：

- `TaskGraphGraphModuleInspector.tsx`
- `TaskGraphObjectInspector.tsx`
- `taskGraphModuleComposition.ts`
- `backend/task_system/compiler/layered_graph_normalizer.py`
- `backend/task_system/compiler/coordination_graph_compiler.py`
- `backend/task_system/graphs/composable_graph_builder.py`
- `backend/task_system/graphs/task_graph_standard_models.py`

动作：

1. 新增图模块节点创建入口。
2. `linked_graph_id` 等导入配置绑定到 canonical graph_module node。
3. 后端优先从 explicit graph_module node 编译 runtime plan。
4. timeline_blocks 只作为 legacy/derived 来源。
5. 标准视图展示 graph_module_expansions，但展开图只读。

完成标准：

- 父图可明确看到一个 graph_module 节点。
- 子图内部拓扑不和父图编辑混在一起。
- 图库导入图可复用。

### 阶段四：预检升级

目标：

- 预检不再只是字段校验，而是证明“这张图能被 runtime 正确消费”。

文件：

- `taskGraphPreflight.ts`
- `TaskGraphPublishRunPage.tsx`
- `TaskGraphExecutionPackagePanel.tsx`
- 后端 standard view / runtime spec tests

动作：

1. 新增 canonical-vs-standard 对齐检查。
2. 检查 overlay/display-only 对象是否被误当 runtime 对象。
3. 检查 edge role 与 ready 消费关系。
4. 检查 graph_module node 与 runtime plan 对齐。
5. 检查 resource/commit/revision 边是否闭环。

完成标准：

- 发布页能回答：这张图哪些配置被 runtime 消费，哪些只是显示/诊断。
- 不能再出现“看起来配了，其实运行不认”的状态。

### 阶段五：删除残留和测试固化

目标：

- 按用户要求清理没用旧代码，不以兼容为借口保留噪声。

动作：

1. 删除不再使用的 overlay 编辑入口。
2. 删除旧 layer 文案和旧测试夹具。
3. 删除 “legacy editor graph spec” 主路径引用。
4. 将旧字段迁移测试移入 legacy migration 专区。

验证：

- 前端 TypeScript。
- task-system 前端测试。
- 后端 task graph registry / standard view / scheduler / graph module 测试。
- 手动打开 8003 端口验证编辑器主流程。

## 7. 文件级清单

### 前端

- `frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx`
  - 改默认层级。
  - 重命名/重排页面。
  - 将 compiled view 从主编辑降级。

- `frontend/src/components/workspace/views/task-system/TaskGraphLayerNav.tsx`
  - 合并十层为五层。
  - 删除重复/误导层级。

- `frontend/src/components/workspace/views/task-system/TaskGraphStudioShell.tsx`
  - 修正文案，去掉主链、阶段、循环框、并发组作为运行许可的表述。

- `frontend/src/components/workspace/views/task-system/TaskGraphTopologyPage.tsx`
  - 升级为主 Graph Builder 或迁入新页面。
  - 移除 Step/主链展示。

- `frontend/src/components/workspace/views/task-system/TaskGraphComposableEditorPage.tsx`
  - 转为 Compiled View。
  - 禁止直接新增 overlay runtime-like 边。

- `frontend/src/components/workspace/views/task-system/TaskGraphObjectInspector.tsx`
  - 拆分 inspector。
  - overlay patch 迁入诊断工具或删除。

- `frontend/src/components/workspace/views/task-system/TaskGraphPortEdgeInspector.tsx`
  - 区分 canonical edge 和 display port edge。
  - 不再把 overlay port edge 文案写成可运行边。

- `frontend/src/components/workspace/views/task-system/TaskGraphNodeUnitInspector.tsx`
  - 移除主编辑中的 `sequence_index`、`main_chain`、`blocks_phase_exit`。

- `frontend/src/components/workspace/views/task-system/taskGraphPreflight.ts`
  - 重写 source/title。
  - 新增 canonical/standard 对齐检查。

- `frontend/src/components/workspace/views/task-system/taskGraphSaveMapper.ts`
  - 减少前端派生归一化。
  - 后端作为 contract binding 权威。

### 后端

- `backend/task_system/graphs/task_graph_models.py`
  - 将 legacy lifecycle 字段标为 display/diagnostic。
  - 不再作为编辑器主协议字段推广。

- `backend/task_system/graphs/composable_graph_builder.py`
  - 保留 standard/composable 编译。
  - 明确 overlay 是 shadow model。
  - 后续删除 overlay 写入主路径。

- `backend/task_system/graphs/task_graph_standard_models.py`
  - standard view 继续作为编译诊断权威。
  - 支持 graph_module canonical node 对齐。

- `backend/task_system/compiler/coordination_graph_compiler.py`
  - 优先 explicit graph_module node。
  - support report 继续标明 lifecycle 字段 partial。

- `backend/task_system/compiler/layered_graph_normalizer.py`
  - timeline_blocks 逐步只作为 legacy/derived。

- `backend/runtime/graph_runtime/scheduler.py`
  - 保持 explicit_dependency_ready_set，不回退。

## 8. 验收矩阵

### 基础建图

- 空图能创建第一个节点。
- 多节点图必须能画 activation/data 边。
- 入口/出口不会因普通字段编辑被意外覆盖。
- 保存后刷新，节点和边保持一致。

### 并发与汇合

- 两个无互相依赖的节点可以同时 ready。
- 下游 join 节点等待所需上游。
- `sequence_index` 不会制造隐式阻塞。
- timeline/lifecycle 页面不暗示并发组能力。

### 图模块

- 从图库导入子图后，父图出现 graph_module 节点。
- 展开视图只读。
- 修改子图必须打开子图编辑器。
- graph_module runtime plan 与节点对齐。

### 资源和记忆

- memory_read 必须有 repository/collection。
- write_candidate 必须有 commit 路径或明确 candidate-only。
- commit 必须有 candidate ref 或 record key。
- 下游正式节点只能读取 committed 可见结果。

### 预检与发布

- 预检列出 runtime-consumed 与 display-only 的差异。
- overlay/display-only edge 不允许被当作 runtime edge 发布。
- standard view、runtime spec、draft graph 的对象数量和关键 ID 对齐。

## 9. 不允许的实现方式

1. 不允许为了某个写作图模板写特判。
2. 不允许把 prompt 说明当运行边界。
3. 不允许继续新增 metadata overlay 来绕过 canonical nodes/edges。
4. 不允许把 standard view 当成第二套可写图。
5. 不允许用 “兼容旧图” 保留用户看得见的噪声主入口。
6. 不允许只改文案不改真相源。
7. 不允许让 UI 展示后端不消费的强能力。

## 10. 推荐执行顺序

先做阶段一和阶段二。

理由：

- 用户当前最痛的是编辑器看不懂、容易误操作、图结构真相不清。
- 图模块 canonical 化依赖主编辑器收束，否则还会继续分裂。
- 预检升级需要先知道哪些视图可写、哪些只读。

执行完成后，编辑器会从“很多页面都能改一点字段”变成“一个主编辑器搭可运行图，多个诊断页证明它能跑”。
