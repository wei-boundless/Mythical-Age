# 77-TaskGraphStudio实施上下文快照

## 0. 目的

本文是 76 号计划实施过程中的上下文压缩快照，用于在会话压缩或中断后快速恢复当前状态。

## 0.1 2026-05-13 后续接入进展

已新增计划书：

- `docs/系统规划/78-TaskGraph接入投影系统与编排系统主数据修复计划-20260513.md`

本轮已确认的新架构判断：

```text
TaskGraph Studio 不应自建 Agent/Prompt 替代表。
Agent 主数据归编排系统。
Projection/Prompt 主数据归投影系统。
TaskGraph 只保存引用、绑定关系和必要覆盖策略。
```

本轮已完成的主数据接入：

- `TaskSystemView.tsx` 已拉取 `getOrchestrationAgents()`，并把正式编排 Agent Catalog 传入 TaskGraph Studio。
- `taskGraphTypes.ts` 已为 Studio 增加 `orchestrationAgentCatalog`。
- `TaskGraphWorkbench.tsx` 已把正式编排目录传给 Agent 编组页。
- `TaskGraphAgentRosterPage.tsx` 已优先使用 `/orchestration/agents` 的 `agents / agent_groups / profiles`：
  - Agent 下拉不再只依赖 A2A `agent_cards`。
  - Agent Group 从正式 `agent_groups` 下拉选择，不再只是自由输入。
  - 节点卡显示对应 Runtime Profile 摘要。
- `NodeResponsibilityCard.tsx` 已接入投影系统 Projection 选择：
  - 节点可绑定 `projection_id / projection_overlay_id`。
  - 职责字段仍可编辑，Prompt 草稿只作为生成 ProjectionCard 的临时输入。
  - 点击“生成并绑定投影”会调用投影系统创建 ProjectionCard，TaskGraph 只保存 `projection_id / projection_overlay_id` 引用。
  - 旧 `metadata.role_prompt` 显示为 legacy 迁移来源，但用户仍可把它写入投影系统。
- `TaskGraphResponsibilityPage.tsx` 与 `TaskGraphWorkbench.tsx` 已传递 `projectionCards`。
- `taskGraphPreflight.ts` 已新增 projection migration 提示：
  - 如果节点已有 legacy prompt 但没有 projection binding，会产生 `frontend.preflight.projection_binding` warning。
- `backend/api/tasks.py` 已在 TaskGraph 保存入口接入 legacy prompt 迁移：
  - 保存时把 `metadata.role_prompt` / 职责字段迁移为投影系统 `ProjectionCard`。
  - TaskGraph 节点保存为 `projection_id` 引用。
  - 旧字段进入 `metadata.legacy_prompt_migration`，不再作为主数据。
- `runtime_assembly_builder.py` 已补充 Agent/Profile/Projection 解析来源 diagnostics。

验证：

- `frontend`: `npm run lint` 通过。
- `frontend`: `npx tsc --noEmit` 通过。
- `frontend`: `npm test -- --run` 通过，5 files / 20 tests。
- `backend`: `pytest backend/tests/runtime_assembly_builder_test.py backend/tests/task_system_api_regression.py -q` 通过，26 passed。

尚未完成：

- 需要在真实 Edge 页面再走一轮“生成并绑定投影 -> 保存 -> 发布页预检”的浏览器冒烟。

当前目标仍是：

```text
让 TaskGraphDefinition 成为多 Agent 持续任务编排平台的主模型，
并逐步让编辑、保存、预检、发布、运行装配都消费同一套 TaskGraph 规范。
```

## 0.2 2026-05-14 运行时预算与收口修复进展

已新增计划书：

- `docs/系统规划/79-主Agent预算耗尽与子Agent回收后收口失效结构修复计划-20260513.md`

本轮已完成的运行时修复：

- `task_run_loop.py`
  - 子 Agent / 工具结果回收后，增加优先收口分支。
  - 预算超限时优先基于已有证据强制收口，不再直接把预算耗尽文案暴露给用户。
  - `delegate_to_agent` 结果观测现在附带当前用户问题，用于后续对齐判断。
  - 对齐的委派结果可沉淀为 `task_summary_refs`，供主 Agent 直接收口。
- `agent_delegation_executor.py`
  - 委派额度计数不再把明显偏题的旧委派与缺对象句柄后的修正重试一并算进预算。
- `context_manager.py`
  - “委派被限流”“下一轮我会优先调用”“预算达到上限”等失败性运行摘要已降级，不再进入主决策上下文。
- `long_runner.py`
  - `runtime_budget_exhausted` 和内部预算/限流暴露已升级为关键质量失败，不再只是普通 warning。

新增回归测试：

- `backend/tests/runtime_loop_budget_regression.py`
- `backend/tests/system_eval/long_runner_warning_regression.py` 已补充关键失败断言

验证结果：

- `pytest backend/tests/runtime_loop_budget_regression.py backend/tests/system_eval/long_runner_warning_regression.py backend/tests/runtime_commit_gate_regression.py -q`
  - `13 passed`
- `python -m py_compile ...`
  - 通过
- 重新执行 60 轮长测：
  - 输出目录：`output/test_runs/20260514-main-agent-60round-after-budget-fix`
  - 总结：`53/53 user turns passed; warnings=2 turns`

本轮长测相较前一版的关键改善：

- `本轮运行预算达到上限`：从 3 次降为 0 次
- `本轮运行时间达到上限`：从 1 次降为 0 次
- `委派被限流` / `本轮委派全部被限流`：从大量出现降为 0 次

仍待继续深追的剩余问题：

- 个别 PDF 页在 OCR/正文抽取不稳定时仍会出现“没有稳定可提取的正文”类 warning。
- `missing_object_handle` 仍有零星残留，说明对象绑定链路已改善但尚未完全收敛。

## 1. 当前已完成

### 1.1 前端主链路

- 新增 `taskGraphDraftV2.ts`。
- 新增 `taskGraphSaveMapper.ts`。
- 新增 `legacyStackToTaskGraphDraftV2()`，迁移期可把旧三件套适配成 TaskGraphDraftV2，供 Studio 页面优先读取主模型语义。
- `TaskGraphRecord` 类型补齐：
  - `working_memory_policy_profile_id`
  - `working_memory_policy`
- 保存 mapper 已把以下配置写入 TaskGraph 一等字段：
  - `runtime_policy`
  - `context_policy`
  - `working_memory_policy_profile_id`
  - `working_memory_policy`
  - `entry_node_id`
  - `output_node_id`
  - `graph_contract_id`
- 已有前端测试 `taskGraphSaveMapper.test.ts`，覆盖：
  - entry/output 不依赖节点数组顺序
  - runtime/context/working-memory 保存和反读
  - graph contract 一等字段保存
  - legacy editor stack 可适配为 V2 draft，保留入口/出口、runtime/context/working-memory 语义

### 1.2 TaskGraph Studio 壳

已新增并接入：

- `TaskGraphStudioShell.tsx`
- `TaskGraphLayerNav.tsx`
- `TaskGraphTopBar.tsx`
- `TaskGraphIssueBar.tsx`

`TaskGraphWorkbench.tsx` 已经从纯旧 wrapper 改为 Studio shell，左侧有八层卡片导航。

当前继续推进 V2 主写入迁移：

- `TaskSystemView` 已生成 `taskGraphDraftV2` 并传入 Studio。
- Studio 顶层标题、图 ID、协调者、发布态已优先读取 `taskGraphDraftV2`。
- `TaskGraphBlueprintPage` 已改为读取 `taskGraphDraftV2`，并通过图级、runtime、context 三个显式 patch 通道回写。
- 蓝图页入口/出口、图类型、协作模式、Agent 组、上下文策略、记忆共享策略、交接策略不再直接把 legacy coordination draft 当作页面模型。
- `TaskGraphMemoryArtifactPage` 已改为读取 `taskGraphDraftV2`：
  - 图级 working memory policy 读取 V2 一等字段 `working_memory_policy`。
  - shared context / memory sharing 读取 V2 `context_policy`。
  - artifact policy 仍作为 V2 metadata 策略块读取和回写。
- `TaskGraphContractQualityPage` 已改为读取 `taskGraphDraftV2.graph_contract_id`，图级契约不再直接从 legacy metadata 取值。
- 迁移期仍会把这些字段镜像回 legacy coordination draft，保证现有保存、拓扑和发布链路不断。

### 1.3 八个 Studio 页面

已新增并可切换：

- `TaskGraphBlueprintPage.tsx`
- `TaskGraphAgentRosterPage.tsx`
- `TaskGraphResponsibilityPage.tsx`
- `TaskGraphTimelinePage.tsx`
- `TaskGraphMemoryArtifactPage.tsx`
- `TaskGraphContractQualityPage.tsx`
- `TaskGraphPublishRunPage.tsx`
- 拓扑层暂时仍复用 `CoordinationEditorWorkbench`

这些页面已有部分真实落点，但还没有完全替代旧大组件。

### 1.4 后端直接编译链路

已实现并通过定向测试：

- `compile_task_graph_definition_runtime_spec()`
- `/tasks/runtime-specs/task-graphs/{graph_id}`
- `TaskGraphRuntimeNode` 扩展字段：
  - execution/wait/join
  - phase/sequence/timeline
  - context/memory/artifact
  - review gate/loop
- `TaskGraphRuntimeEdge` 扩展字段：
  - payload contract
  - A2A message type
  - ack/wait/failure/result delivery
  - memory/artifact/context handoff

前端 `TaskGraphPublishRunPage` 已接入 `compileTaskSystemTaskGraphRuntimeSpec()`。

### 1.5 前端结构化预检

已新增：

- `taskGraphPreflight.ts`
- `taskGraphPreflight.test.ts`

当前预检报告会统一收敛：

- 图级结构问题
- 节点身份和 Agent 绑定问题
- 节点职责 Prompt 缺失提示
- 必需产物路径问题
- 边端点和载荷契约问题
- 后端 runtime spec issues

`TaskGraphPublishRunPage` 已接入该报告，发布按钮会根据结构化报告阻塞。

发布页 runtime spec 展示已增强：

- 起点/终点
- 通信模式
- 后端 issues
- diagnostics JSON

### 1.6 模板向导与新图入口

已新增：

- `taskGraphTemplates.ts`
- `TaskGraphSetupWizard.tsx`
- `taskGraphTemplates.test.ts`

当前新图默认从 `blueprint` 层进入模板向导，不再直接进入空画布。模板覆盖：

- 单 Agent 长任务
- 管线式多 Agent
- 并行审查 + 协调者汇总
- 审核门 + 返修循环
- RAG + 资料分析 + 写作
- PDF 分析 + 表格分析 + 汇总
- 长期项目循环执行

模板生成会写入真实节点、边、入口、出口、参与 Agent、阶段定义、timeline frame 和职责语言 Prompt。Prompt 使用“你是一名... / 你只负责... / 你不负责... / 你必须...”结构，避免把开发字段说明发给 Agent。

`TaskSystemView.applyCoordinationGraphTemplate()` 已改为消费统一模板生成器，并把模板生成的阶段、入口出口和模板 ID 写入 coordination metadata。

### 1.7 配置优先级与问题定位

已新增：

- `taskGraphEffectivePolicy.ts`
- `taskGraphEffectivePolicy.test.ts`

当前解析优先级为：

```text
节点显式配置
  -> 边显式配置
  -> 阶段显式配置
  -> 图级默认策略
  -> Agent 角色预设
  -> Agent Profile 默认能力
  -> 系统默认值
```

`TaskGraphAgentRosterPage.tsx` 已接入有效策略显示，节点卡片会显示：

- 有效 Agent
- Agent 来源
- Prompt 来源

`TaskGraphPublishRunPage.tsx` 的预检问题行已变成可点击定位入口。当前定位规则：

- node 问题：选中节点并跳转到 Agent 编组或职责与交接。
- edge 问题：选中边并跳转到职责与交接。
- graph 问题：跳转到任务蓝图或契约质量层。
- runtime 问题：停留在预检与运行层。

### 1.8 记忆与产物分层

已新增：

- `WorkingMemoryPolicyEditor.tsx`
- `ArtifactPolicyEditor.tsx`

`TaskGraphMemoryArtifactPage.tsx` 已从单页泛表单升级为三层策略视图：

- 图级上下文与工作记忆默认策略。
- 图级产物落盘、物化器、晋升和 manifest 策略。
- 节点级记忆读取、写回和产物目标。
- 边级工作记忆交接，明确携带 Kind、Scope、refs 或摘要策略。

`taskGraphPreflight.ts` 已新增边级工作记忆交接预检：当 edge 配置了 `working_memory_handoff_policy`，但没有 `carry_kinds`、`carry_scopes`、`working_memory_refs` 或 `summary_only` 时，会产生 `frontend.preflight.memory_handoff` warning。

### 1.9 职责与交接卡片化

已新增：

- `NodeResponsibilityCard.tsx`
- `EdgeHandoffCard.tsx`
- `NodeResponsibilityCard.test.ts`

`TaskGraphResponsibilityPage.tsx` 已拆为两张职责卡：

- 节点职责卡：编辑角色身份、只负责、不负责、完成标准和职责 Prompt。
- 边交接卡：编辑载荷契约、等待策略、失败传播、结果投递、ack、工作记忆携带 Kind/Scope 和摘要策略。

节点职责卡新增“生成职责 Prompt”动作，会把职责字段合成为 Agent 可理解的自然语言：

```text
你是一名...
你只负责...
你不负责...
你必须...
```

模板图进入职责页时，如果用户未显式选中边，会用第一条边作为边交接卡的默认目标，避免新图生成后交接配置为空态。

### 1.10 时序、循环与审核门一等化

已新增：

- `PhaseLifecycleEditor.tsx`

`TaskGraphTimelinePage.tsx` 已从节点时序表继续升级：

- 增加阶段生命周期卡。
- 每个阶段可编辑标题、入口节点、出口节点、审核门节点、阶段退出策略、最大循环次数、循环退出条件。
- 阶段卡显示节点数、步骤数、审核门和阶段级问题数量。

`TaskGraphPublishRunPage.tsx` 的统一预检已传入 coordination metadata。

`taskGraphPreflight.ts` 已合并 `buildTimelinePreflightIssues()`，把 timeline/phase/frame/review/loop 问题统一进入发布页阻塞列表，来源为 `frontend.preflight.timeline`。

### 1.11 拓扑层迁移边界

已新增：

- `TaskGraphTopologyPage.tsx`

`TaskGraphWorkbench.tsx` 不再直接 import `CoordinationEditorWorkbench`，旧画布已被降级为拓扑层内部迁移承载组件。

已继续收敛旧拓扑层入口：

- `CoordinationEditorWorkbench` 的机制控制台只暴露通信控制台。
- `CoordinationMechanismDrawer` 已从旧多类型配置抽屉收缩为通信抽屉，只处理图级协议与边级通信交接。
- 节点检查器不再暴露 Agent、契约、时序、审核循环、记忆、运行、产物配置入口。
- 图检查器不再暴露时序、契约、记忆、产物、预检配置入口。
- 边检查器保留通信交接和 A2A 预览，移除运行策略入口。
- 旧拓扑画布右侧的时序 Frame 创建面板已替换为结构选择面板。
- 右键菜单不再提供构建阶段、时序点、并行组、循环、审核门入口。
- `CoordinationMechanismConsole` 内部也已收缩为通信控制台，不再保留不可达的时序/审核/循环/记忆/产物/预检/运行 tab 分支。
- 旧拓扑画布中的时序 Frame 创建、应用、删除、选择集写回等 mutation 函数已删除；拓扑层只保留已有 frame 的只读展示与范围选择。

当前边界为：拓扑层负责节点、边、连线、结构选择和通信；生命周期、记忆、产物、质量门和发布预检交由 Studio 分层页面承担。

## 2. 当前未完成

- `CoordinationEditorWorkbench` 仍在拓扑层内部被复用，入口和旧写入能力已大幅收敛；仍需继续检查是否存在可删除的旧常量、旧导入、旧 CSS 和只读 overlay 之外的残留。
- Studio 页面结构已经成型，但多数页面仍通过 `legacyDrafts.coordinationDraft` 和 `coordinationDraft.metadata` 写入；尚未真正把编辑态主写入切到 `TaskGraphDraftV2`。
- 模板向导已有首版，但还缺少模板参数表单、Agent 权限/能力装载选择、内置专业 Agent 候选绑定。
- 预检问题已能点击跳层，但还没有精确滚动/聚焦到具体字段，也没有把修复动作直接挂到 issue 上。
- 运行闭环只到 direct runtime spec 编译，尚未完成 TaskRun / CoordinationRun / Trace / Checkpoint / Resume 页面闭环。
- 旧 metadata 到 TaskGraph 一等字段的长期兜底逻辑还未清理；需要明确 shadow 阶段和 cutover 阶段的删除点。

## 3. 已验证

前端已跑过：

- `npm test`
- `npx tsc --noEmit`
- `npm run lint`
- 本地 Edge 点击验证八个 Studio 层级可切换

已于当前轮确认：

- `pytest backend/tests/task_graph_registry_test.py backend/tests/task_system_api_regression.py -q` 通过，21 passed。
- `npm test` 通过，当前 5 个测试文件、15 个测试。
- `npx tsc --noEmit` 通过。
- `npm run lint` 通过，但仍有历史 warning。
- Edge 验证发布页存在、预检行存在、运行规范按钮存在，移动端 shell 存在。
- Edge 再验证八个 Studio 层级均可点击打开。
- Edge 确认拓扑层不再出现旧时序 Frame 面板文案：`时序框`、`创建 Frame`、`右键选择集构建时序`。
- Edge 确认拓扑层仍保留通信控制台和结构选择面板。
- Edge 二次验证：八个 Studio 层级均可打开，拓扑层 `topologyClean=true` 且 `topologyCore=true`。
- Edge 验证新图进入模板向导，选择 `PDF 分析 + 表格分析 + 汇总` 后可生成 PDF 分析员、表格分析员、综合汇总员和通信拓扑。
- Edge 验证 Agent 编组页可显示 `有效 Agent`、`Prompt 来源`、`节点显式配置`。
- Edge 验证预检问题行可点击，并能跳转到对应 Studio 层级。
- Edge 验证记忆与产物页可显示图级工作记忆、图级产物、节点策略、边级交接三层边界。
- Edge 验证职责与交接页可显示节点职责卡、边交接卡和职责语言字段。
- Edge 验证时序与循环页可显示阶段生命周期卡、阶段退出、审核门节点、循环字段。
- Edge 验证发布页可显示 timeline 预检来源。
- `npm test` 通过，当前 5 个测试文件、15 个测试。
- 当前轮继续清理后：
  - `npx tsc --noEmit` 通过。
  - `npm run lint` 通过，仍只有 3 条历史 Hook warning。
  - `npm test` 通过，当前 5 个测试文件、15 个测试。
  - 本地 Edge 冒烟验证可进入任务图编辑器，Studio 分层导航存在，通信/结构选择入口存在，旧 `创建 Frame` / `右键选择集构建时序` 文案未出现。
- V2 蓝图链路迁移后：
  - `npx tsc --noEmit` 通过。
  - `npm test` 通过，当前 5 个测试文件、16 个测试。
  - `npm run lint` 通过，仍只有 3 条历史 Hook warning。
  - 本地 Edge 冒烟验证：生成单 Agent 模板后可进入任务蓝图页，V2 入口/出口一等字段文案和图标题字段可见；页面错误仍为 8002 后端未监听导致的 fetch 失败。
- V2 记忆/产物/契约页迁移后：
  - `npx tsc --noEmit` 通过。
  - `npm test` 通过，当前 5 个测试文件、16 个测试。
  - `npm run lint` 通过，仍只有 3 条历史 Hook warning。
  - 本地 Edge 冒烟验证：生成 `PDF 分析 + 表格分析 + 汇总` 模板后，记忆与产物页、契约与质量门页均可打开并显示图级策略；页面错误仍为 8002 后端未监听导致的 fetch 失败。

Edge 验证仍捕获到两个 `Failed to fetch` 页面错误，需后续追踪来源。

已追踪来源：

- `http://127.0.0.1:8002/api/sessions`
- `http://127.0.0.1:8002/api/skills`
- `http://127.0.0.1:8002/api/config/rag-mode`
- `http://127.0.0.1:8002/api/files?...`

根因是本地 Edge 验证时后端 API 端口 `8002` 未监听，属于运行环境问题，不是 TaskGraph Studio 新页面渲染崩溃。

## 4. 剩余收尾执行清单

下面清单用于一次性收尾 76 号计划。除非发现结构性问题，否则后续推进按此顺序执行，并在每项完成后更新本节状态。

### A. `TaskGraphDraftV2` 主写入收口

- [x] A1. 图级/runtime/context 主读写接入 V2。
  - 已完成：蓝图页、Studio 顶栏、发布页图 ID/标题/协调者/发布态优先读取 V2。
  - 验收：`npx tsc --noEmit`、`npm test`、Edge 蓝图页冒烟通过。

- [x] A2. 图级 working memory、artifact、graph contract 接入 V2。
  - 已完成：记忆与产物页读取 V2 `working_memory_policy` / `context_policy`；契约页读取 V2 `graph_contract_id`；artifact policy 作为 V2 metadata 策略块保留。
  - 验收：`npx tsc --noEmit`、`npm test`、Edge 记忆与产物/契约页冒烟通过。

- [x] A3. 节点字段主写入接口迁移。
  - 范围：Agent 编组页、职责页、记忆与产物页、契约页中的节点级字段。
  - 目标：页面不直接依赖 legacy coordination/topology 作为主模型；通过统一 `updateTaskGraphNodeV2(node_id, patch)` 写入，再镜像到 legacy。
  - 重点字段：`agent_id`、`role`、`work_posture`、`responsibility_contract`、`prompt_source`、`memory_read_policy`、`memory_writeback_policy`、`artifact_policy`、`node_contract_id`、`input_contract_id`、`output_contract_id`。
  - 已完成：节点 patch 同步写入 topology 编辑态和 legacy mirror；保存 mapper 优先使用 topology/V2 编辑态，避免旧 coordination 节点覆盖新编辑。
  - 验收：节点字段编辑后保存 payload 的 `nodes[]` 字段真实变化；`taskGraphSaveMapper.test.ts` 已覆盖 topology 编辑态优先于 stale coordination mirror。

- [x] A4. 边字段主写入接口迁移。
  - 范围：职责与交接页、记忆与产物页、契约页、拓扑通信抽屉。
  - 目标：通过统一 `updateTaskGraphEdgeV2(edge_id, patch)` 写入，再镜像到 legacy。
  - 重点字段：`payload_contract_id`、`wait_policy`、`ack_policy`、`failure_propagation_policy`、`result_delivery_policy`、`working_memory_handoff_policy`、`context_handoff_policy`。
  - 已完成：边 patch 同步写入 topology 编辑态和 legacy mirror；保存 mapper 优先使用 topology/V2 编辑态。
  - 验收：边字段编辑后保存 payload 的 `edges[]` 字段真实变化；`taskGraphSaveMapper.test.ts` 已覆盖 payload contract 从 topology 编辑态保存。

- [x] A5. 阶段/timeline 字段主写入接口迁移。
  - 范围：时序与循环页。
  - 目标：阶段定义、frame、review gate、loop policy 通过统一 V2 metadata/timeline patch 写入，再镜像到 legacy。
  - 重点字段：`phase_definitions`、`timeline_frames`、`entry_node_id`、`exit_node_id`、`review_gate_node_id`、`loop_policy`、`exit_policy`。
  - 已完成：时序页读取 `taskGraphDraftV2.metadata`，阶段定义和 timeline policy 通过统一 metadata patch 写入，再镜像 legacy。
  - 验收：阶段生命周期编辑后，发布页 timeline 预检读取最新数据；Edge 验证时序页可打开，拓扑层保持只读 overlay。

- [x] A6. legacy shadow/cutover 清理。
  - 范围：`TaskGraphWorkbench`、`TaskSystemView`、`taskGraphSaveMapper`。
  - 已完成：保存主链路已切到 `TaskGraphDraftV2 -> buildTaskGraphUpsertPayload(...)`；`taskGraphSaveMapper` 不再以 legacy stack 作为一等 payload 来源。
  - 已完成：`taskGraphDraftV2` / `taskGraphRecordToDraftV2` 已剔除 `entry_node_id`、`output_node_id`、`graph_contract_id`、`runtime_policy`、`context_policy`、`working_memory_policy`、`working_memory_policy_profile_id` 等旧 metadata 影子字段。
  - 验收：保存 payload 不依赖旧 metadata 的 runtime/context/working-memory/graph-contract 兜底；legacy drafts 仅保留协议、拓扑模板和镜像写回承载角色。

### B. 模板向导与 Agent 装载

- [x] B1. 模板参数表单。
  - 字段：任务意图、输入资料类型、主要产物类型、审核强度、循环次数、是否需要人工确认。
  - 已完成：向导新增任务意图、资料类型、产物类型、审核强度、循环次数、人工确认参数。
  - 验收：参数会写入 template metadata、节点职责 Prompt、artifact/review/loop policy；测试覆盖。

- [x] B2. 专业 Agent 候选绑定。
  - 范围：RAG、PDF、表格分析、资料分析、写作、审核、协调汇总。
  - 目标：模板生成时可以显式选择内置 Agent 候选；生成结果在 Agent 编组页解释来源。
  - 已完成：向导提供 PDF、表格、RAG Agent 候选输入；模板生成支持 agent binding override，并写入 `agent_binding_source`。
  - 验收：PDF/表格模板生成后，PDF 分析员、表格分析员、汇总员有可解释的 agent binding/source；测试覆盖自定义 PDF/表格 Agent。

- [x] B3. 模板生成语义 prompt 加固。
  - 目标：生成 prompt 必须是 Agent 能理解的角色语言，不写开发字段说明。
  - 已完成：模板参数会追加为 Agent 可理解的职责上下文，不使用开发字段说明。
  - 验收：模板测试覆盖职责 Prompt 结构和参数进入 Prompt。

### C. 预检定位与修复动作

- [x] C1. issue 精确定位。
  - 目标：issue 点击后不仅跳层，还能选中具体节点/边/阶段，并滚动或聚焦到具体卡片。
  - 已完成：预检 scope 扩展 `phase`；node/edge/phase/graph issue 点击跳转到对应层并选中对象。
  - 验收：timeline phase issue 测试覆盖 `scope=phase`；Edge 冒烟覆盖预检页存在。

- [x] C2. 常见问题一键修复。
  - 动作：生成职责 Prompt、补默认 payload contract、补默认 working memory handoff、补 phase definition、补 entry/output。
  - 已完成：发布页为常见问题显示修复按钮，支持生成职责 Prompt、补默认 payload contract、补摘要 memory handoff、补 phase definition。
  - 验收：修复动作调用真实节点/边/metadata patch，保存 payload 会随编辑态变化。

- [x] C3. 预检质量门分级。
  - 目标：blocking / warning / info 分级清晰；发布按钮只被 blocking 阻塞。
  - 已完成：error 阻塞发布，warning/info 不阻塞；发布页显示阻塞/警告/提示数量。
  - 验收：测试覆盖 warning 不阻塞、blocking 阻塞。

### D. 运行闭环

- [x] D1. 发布页创建 TaskRun / CoordinationRun。
  - 目标：从已通过预检的 TaskGraph 创建运行实例。
  - 已完成：新增 `POST /orchestration/runtime-loop/task-graphs/{graph_id}/start`，从已发布 TaskGraph 直接编译 runtime spec，并创建真实 TaskRun、CoordinationRun、checkpoint、trace。
  - 已完成：`TaskRunLoop.start_task_graph_run()` 使用 TaskGraph runtime spec 生成真实 dispatch plan，避免多 Agent 运行首个 checkpoint 中出现空图调度计划。
  - 已完成：发布页新增“创建运行 / 创建新运行”动作，成功后自动填入 TaskRun ID，并复用真实 trace/checkpoint/resume 通道。
  - 验收：新增后端回归覆盖 TaskGraph 创建运行后 dispatch plan 包含真实节点、ready/blocked 状态和 coordination run trace；前端类型检查通过。

- [x] D2. Trace / Checkpoint / Resume 展示。
  - 目标：发布页或运行页显示节点执行轨迹、检查点、可续跑状态。
  - 已完成：发布页新增 TaskRun ID 输入，可调用真实 runtime-loop trace API；展示 task_run、coordination_runs、latest_checkpoint；可调用真实 coordination resume API。
  - 验收：前端类型检查通过；Edge 冒烟可见 Trace / Checkpoint / Resume 区域。

- [x] D3. 多 Agent 连续任务运行视图。
  - 目标：能看到当前阶段、当前节点、阻塞原因、下一步可执行动作。
  - 已完成：发布页显示运行状态、协调运行数量、事件数量、checkpoint 状态和 Trace JSON。
  - 已完成：前端发布态已从单一 `published:boolean` 收束为显式 `publish_state` 语义，区分 `draft / saved / published / run_bound`；发布页、Studio 顶栏、底栏状态条统一显示图状态与运行绑定状态。
  - 验收：Edge 冒烟可看到运行追踪与续跑区域；真实刷新/续跑依赖已有 TaskRun ID 和后端 8002 可用。

### E. 旧代码与验证收尾

- [x] E1. 旧拓扑承载组件最终清理。
  - 范围：旧 CSS、旧常量、只读 overlay 之外的旧 helper。
  - 已完成：`CoordinationEditorWorkbench` 的 drawer type 收紧为 `communication`；旧 Agent/contract/timeline/review/loop/memory/artifact/preflight/runtime 抽屉类型和标题残留删除；旧 preflight row button CSS 删除。
  - 验收：`CoordinationEditorWorkbench` 只保留拓扑、连线、节点/边基础编辑、通信交接；`npx tsc --noEmit`、`npm test`、`npm run lint` 通过。

- [x] E2. 全量验证。
  - 前端：`npx tsc --noEmit`、`npm test`、`npm run lint`。
  - 后端：`pytest backend/tests/task_graph_registry_test.py backend/tests/task_system_api_regression.py -q`。
  - 浏览器：本地 Edge 验证模板生成、八层切换、节点/边/阶段编辑、预检修复、发布/运行入口。
  - 已完成：
    - 前端 `npx tsc --noEmit` 通过。
    - 前端 `npm test` 通过，5 个测试文件、19 个测试。
    - 前端 `npm run lint` 通过，当前已无 lint warning。
    - 后端定向测试通过，33 passed。
    - 本地 Edge 验证 PDF/表格模板参数、六个主要 Studio 页面、预检与运行入口均可打开。
    - 本地 Edge 验证发布页已出现真实“创建运行 / 创建新运行”和 Session ID；旧“运行创建接口待接入”文案已消失。
    - 当前轮再次验证：前端 `npx tsc --noEmit` 通过、`npm test` 通过；后端 `pytest backend/tests/runtime_assembly_builder_test.py backend/tests/task_system_api_regression.py -q` 通过，25 passed。
    - 当前轮再次验证：本地 Edge 在最新前端实例上可进入 TaskGraph Studio，模板生成、八层切换、“创建运行”按钮文案、发布状态文案、旧“运行创建接口待接入”文案消失均已确认。

- [x] E3. 文档收口。
  - 更新 76/77：标记实际完成范围、剩余风险、后续运行闭环计划。
  - 如果仍有 8002 未监听 fetch 错误，明确归类为本地运行环境问题，并给出启动/配置方式。
  - 已完成：77 快照清单已标记当前完成项；D1/A6 已更新为真实完成状态；8002 fetch 错误仍归类为本地后端未监听。
  - 已修复：任务系统管理层加载停留在“加载中 / 0 个任务”的问题已定位为前端加载触发不稳定与目录请求重复触发叠加。`TaskSystemView` 已改为只在进入 `task-system` 视图时触发主数据加载，`applyOverview` 不再因 `selectedDomainId` 状态变化重建 `load`，投影目录与编排 Agent 目录增加 in-flight 去重，并移除投影目录 8 秒本地 race。
  - 当前验证：本地 Edge 打开 `http://127.0.0.1:3000/?view=task-system`，稳定发起 1 次 `/api/tasks/overview`、1 次 `/api/soul/projections`、1 次 `/api/orchestration/agents`，三者均 200；页面显示真实 `TaskGraph 收尾验证任务`，不再停留在主加载或投影加载提示。

## 5. 78 号主数据接入收口进展

- [x] 前端 Agent 选择接入编排系统：`TaskSystemView` 拉取 `getOrchestrationAgents()`，`TaskGraphAgentRosterPage` 使用正式 `agents / agent_groups / profiles`。
- [x] 前端 Projection 创建接入投影系统：职责页“生成并绑定投影”调用 `createSoulProjectionCard()`，节点保存 `projection_id / projection_overlay_id`。
- [x] 前端旧 Prompt 主写入口已清理：Agent 页不再编辑图级/节点级 Prompt；模板不再生成 `metadata.role_prompt`；发布页修复动作改为补职责字段或迁移投影。
- [x] 后端保存期迁移已接入：TaskGraph 保存时 legacy prompt/职责字段会迁到 ProjectionCard，TaskGraph 节点不再保存这些字段作为主数据。
- [x] ProjectionCard 已标记任务系统来源：新增 `projection_kind / owner_system / source_task_graph_refs`，用于把任务图沉淀出的节点职责作为投影静态资产管理。
- [x] 当前验证：前端 `npm run lint`、`npx tsc --noEmit`、`npm test -- --run` 通过；后端 `pytest backend/tests/task_system_api_regression.py -q` 通过，14 passed。
- [x] Runtime Assembly 解析来源 trace 已补充并测试覆盖。
- [x] 最后一轮旧残留扫描已完成：旧 `role_prompt` 只剩迁移兼容读取和测试；A2A 卡片只用于通信预览，不再作为 Agent 主数据源。
- [x] 真实 Edge 冒烟已完成：在临时新后端 `8012` + 新前端 `3021` 上，任务页可加载 `/tasks/overview`，投影目录和编排 Agent 目录可加载，职责页点击“生成并绑定投影”后真实触发 `POST /api/soul/projections`，页面节点投影更新为 `projection.taskgraph.graph_000001.intake`。
- [x] 当前轮加载修复验证：前端 `npm run lint`、`npx tsc --noEmit`、`npm test -- --run` 通过；本地 Edge 复测任务管理页不再重复请求目录，也不再停留在“加载中 / 0 个任务”。
- [x] 专业内置 Agent 收口：RAG / PDF / 表格分析三个专业 Agent 已确认注册为编排系统内置 Agent，正式 ID 为 `agent:rag_analyst`、`agent:pdf_reader`、`agent:table_analyst`；任务图模板和 Setup Wizard 默认绑定已改用正式 ID，旧模板别名 `agent.rag_retriever`、`agent.pdf_analyst`、`agent.table_analyst` 会归一到正式 ID。
- [x] 子 Agent 调用权限检查与前端修复：后端已有 `can_delegate_to_agents`、`allowed_delegate_agent_ids`、`allowed_delegate_agent_categories`、`max_delegate_calls_per_turn` 和 `delegate_context_policy`；当前配置为主 Agent 可调用 RAG/PDF/表格三个专业子 Agent，三个专业子 Agent 自身不可继续调用子 Agent。已修复前端运行档案保存时遗漏这些字段的问题，并在编排系统运行页补充可编辑的“子 Agent 调用授权”配置区。
- [ ] 后续可单独优化：目录接口冷加载仍偏重，当前前端已把 `/tasks/overview`、`/soul/projections`、`/orchestration/agents` 超时放宽到 30 秒；后续建议拆轻量 catalog API 或分页。
