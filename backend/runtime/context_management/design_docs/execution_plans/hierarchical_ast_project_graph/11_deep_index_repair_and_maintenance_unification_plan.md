# 项目网络深度索引修复与同源维护统一计划

状态：设计锁定稿，待确认实施  
日期：2026-07-03

## 1. 问题定义

这次不是“搜索结果不够准”的小问题，而是项目控制系统缺了一条完整闭环：

```text
语义网络已经生成
!=
agent 已经拥有稳定的深度定位能力
!=
系统已经能在断点出现时自动发起补网和维护
```

当前实测暴露出的真实失败模式有三类：

### 1.1 入口检索失真

当前 `locate` 只是对 `semantic_coordinates.json` 做浅层 token 匹配。

源码依据：

- `backend/capability_system/tools/tool_units/project_network_tool.py`
  - `_locate_from_artifacts(...)`
  - `_tokens(...)`
  - `_match_score(...)`

当前行为：

- 中文意图几乎不能稳定命中。
- `provider page` 这类查询会被 unrelated `Provider` 类和 web search provider 干扰。
- `终止任务`、`模型创建工厂` 这类真实工程意图会退化成弱匹配。

系统属性上，坏掉的是：

```text
“语义网络存在” 和 “agent 能把意图映射到正确控制落点”
之间没有建立成熟的入口检索层。
```

### 1.2 控制桥断线

实测中，语义网络能落到文件、目录、部分符号，但跨边界控制链没有织通。

典型断点：

```text
providerPage.vue
-> window.api.createLlmProvider / getLlmProviders / updateLlmProvider
-> preload index.js
-> ipc ai_configuration.js
-> MEMORY user_record.py
```

```text
taskCard.vue handleTerminate
-> taskPage.vue handleTerminate
-> window.api.terminateAiTask
-> preload index.js
-> AGENT routers/infomation.py stop_task
```

真实代码存在这些链路，但当前项目网络没有把它们自动归纳为可追踪的控制桥。

系统属性上，坏掉的是：

```text
物理落点已存在
但跨 renderer / preload / ipc / http / backend 的控制神经线没有形成稳定桥接。
```

### 1.3 维护系统与补网系统是断开的

当前维护只有一条来源：

- `backend/file_management/project_structure/maintenance_service.py`
  - `collect_git_change_set(...)`
  - `create_repair_work_items(...)`

它能做的是：

- 根据 git working tree 变化找到 touched skeleton nodes/edges
- 标记旧 semantic refs stale
- 生成 `SemanticRepairWorkItemRecord`

但它还做不到：

- 根据 `link_signal_audit.json` 的断点生成 repair
- 根据 `locate` 未命中或误命中生成 repair
- 根据跨边界桥缺失生成 repair
- 根据文件审查输入截断或 AST 缺失生成 repair

系统属性上，坏掉的是：

```text
维护系统只认识“文件变了”
不认识“网络断了”
```

## 2. 当前源码结论

### 2.1 已经存在、值得复用的能力

#### A. repair / audit 模式已经在 contract 上预留

- `backend/task_system/project_network/build_contract_models.py`
  - `ProjectNetworkBuildMode = Literal["bootstrap", "incremental", "repair", "audit"]`

这说明体系方向是对的，缺的是落地链路，不是缺概念。

#### B. 维护工单和维护运行记录已经存在

- `backend/file_management/project_structure/semantic_models.py`
  - `NetworkMaintenanceRunRecord`
  - `SemanticRepairWorkItemRecord`
  - `SemanticRepairDecisionRecord`

这意味着我们不需要另起一套“补网任务系统”。

#### C. 产物审计已经存在，但还是终态报告，不是 repair 输入

- `backend/task_system/project_network/semantic_artifact_materializer.py`
  - `_build_link_signal_audit(...)`

它已经能产出：

- `unresolved_route_ref`
- `accepted_edge_missing_evidence`
- `accepted_edge_missing_anchor`
- `candidate_relation_needs_resolution`
- `conflict_signal_present`

但这些 signal 现在只留在报告里，没有进入 repair queue。

#### D. review agent 契约体系已经可以承载 repair 审查

- `backend/task_system/project_network/template_catalog.py`
  - `project_network.module_index`
  - `project_network.relation_trace`
  - `project_network.directory_aggregate`

这说明我们不用新写平行调度器。repair 也应该走同一类 graph build / tree reduce / typed work product 链路。

### 2.2 当前结构性缺口

#### A. `locate` 只有单层浅匹配，没有多路召回

当前 `locate` 的入口层缺：

- 中文/英文统一归一化
- identifier tokenization
- alias expansion
- route / channel / tag / symbol / path 的多路召回
- bridge-aware ranking

#### B. 控制桥没有系统级 extractor

当前系统没有确定性抽取这些桥：

- `window.api.* -> preload method`
- `preload ipcRenderer.invoke(channel) -> ipcMain.handle(channel)`
- `Vue emit -> parent handler`
- `router decorator / path -> frontend invoke target`
- `config key / registry key / tool key -> consumer`

agent 可以判断关系是否成立，但不应该自己盲铺这些硬桥。

#### C. repair 工单模型被 `change_set_id` 绑定死了

当前 `SemanticRepairWorkItemRecord` 默认把 repair 触发器理解为 git change set。

这不适合承载：

- audit-driven repair
- locate-miss repair
- bridge-gap repair
- coverage-gap repair

所以必须把“维护来源”从 `git only` 提升为 `signal source`。

## 3. 设计裁决

## 3.0 统一网络裁决

这里必须明确纠正一个容易把实现带偏的表述：

```text
不是“物理网络 + 语义网络”两张并排的网
而是“一张统一项目控制网络”
```

这张统一网络里：

```text
物理层
  是同一节点/边的骨架字段、真实落点和硬证据。

语义层
  是附着在同一节点/边上的职责、标签、控制角色、路由意义和审查判断。

神经控制层
  是 agent 使用这张统一网络进行 locate / jump / trace / repair 的控制视图。
```

也就是说：

- 对 agent 和工具表面来说，只存在一张统一网络。
- `stable_ref / node_id / edge_id` 是统一身份，不允许物理一套、语义一套各自漂移。
- 物理节点、语义坐标、控制桥、信号链都必须回收到同一图实体空间中。
- 可以分层生产，不能分图使用。

允许分开的只有：

- 抽取职责
- 校验职责
- 物化报告
- 维护来源

不允许分开的包括：

- 导航入口
- 节点身份
- 边身份
- repair 回写目标
- generation 发布目标

## 3.1 修复机制必须与维护同源，但不等于继续把一切塞进物理维护层

本次裁决：

```text
物理维护来源
  owner: file_management.project_structure
  负责：git / skeleton / AST / physical delta

项目网络维护编排
  owner: task_system.project_network
  负责：把 git signal、audit signal、locate signal、bridge signal
  统一编排成 repair work item，并驱动 repair graph
```

也就是说：

- `ProjectStructureMaintenanceService` 保留为物理事实维护来源。
- 新的 repair 编排权威放到 `task_system.project_network`。
- 维护是否由 git 触发，只是 signal source 不同，不再代表不同系统。

这是“同源维护”的正确工程化方式。

## 3.2 系统抽硬桥，agent 判语义，curator 决发布

固定边界：

```text
系统
  只抽硬事实和硬候选：
  file tree / AST / import / invoke / ipc channel / emit binding / route path / registry key

agent
  只判断：
  这个候选桥是不是项目控制上有意义的 accepted edge / candidate edge / conflict

curator
  只负责：
  证据门禁、冲突裁决、generation 发布
```

禁止事项：

- 禁止 agent 直接伪造物理桥。
- 禁止系统直接把语义猜测写成 accepted edge。
- 禁止 `locate` 失败时直接全量重建整张网。

## 3.3 维护来源统一为 Maintenance Signal

新增统一抽象：

```text
Maintenance Signal
```

它表示“哪里坏了，为什么坏了，应该补哪一层”。

来源至少有五类：

```text
git_delta
artifact_audit
locate_failure
bridge_gap
coverage_gap
```

推荐数据形态：

```text
signal_id
build_id
signal_source
signal_code
severity
stable_ref
anchor_ref
scope_refs
evidence_refs
requested_layers
payload
status
```

## 3.4 Repair Work Item 继续复用同一维护队列，但触发器要泛化

当前 `SemanticRepairWorkItemRecord` 不够用，应该扩展为“维护触发器无关”的 repair item。

建议扩展字段：

```text
trigger_kind          git_change | audit_signal | locate_failure | bridge_gap | coverage_gap
trigger_ref           change_set_id 或 signal_id
repair_scope_kind     file_module | directory | route_bridge | relation_slice | audit_slice
requested_layers      semantic_file_module | relation_route | generation
reason_codes          unresolved_route_ref / missing_ipc_bridge / locate_miss / ...
```

`change_set_id` 不再是 repair 的唯一入口，而只是 `trigger_kind=git_change` 的一种实例。

## 4. 目标架构

## 4.0 统一项目控制网络模型

目标不是维护两套网络，而是维护一套统一图模型：

```text
UnifiedProjectControlGraph
  nodes:
    identity:
      stable_ref / node_id / physical_ref
    physical_facts:
      path / kind / ast anchor / registry binding / file hash / physical validation
    semantic_facets:
      label / summary / tags / control_role / confidence / coverage / limitations
    control_surface:
      recommended_next_action / jump hints / repair status / audit signals

  edges:
    identity:
      edge_id / source_ref / target_ref
    physical_facts:
      contains / imports / invokes / ipc_channel_match / emit_binding / route_binding
    semantic_facets:
      edge_kind / purpose / accepted|candidate|conflict / evidence / review_focus
    control_surface:
      trace priority / repair needed / unresolved target
```

工程裁决：

- 存储上可以拆字段、拆表、拆产物。
- 但逻辑上必须汇合成同一图实体模型。
- `locate`、`jump`、`trace`、`repair` 都以同一图实体为入口，不允许先选“物理图”再跳“语义图”。

## 4.1 深度索引入口层

`locate` 必须从单一 substring 匹配升级为多层召回。

目标结构：

```text
query normalization
-> alias expansion
-> multi-channel retrieval
-> weighted ranking
-> grouped answer projection
```

### A. query normalization

必须同时支持：

- 中文连续词块
- 英文短语
- camelCase / snake_case / kebab-case
- 路径片段
- channel 名
- route path

最低要求：

- 不再只按 ASCII token split
- 中英文混合 query 不丢失中文
- `getLlmProviders` 要能拆成 `get llm providers`
- `api:create_llm_provider` 要能拆出 channel / action / provider

### B. multi-channel retrieval

至少五路：

```text
physical channel     path / stable_ref / physical_validation.fragment / ast anchor
semantic channel     label / summary / tags / control_role
symbol channel       function / class / handler / endpoint / config key
bridge channel       window.api / ipc channel / emit / router path
chain channel        accepted source/target/edge_kind / high confidence candidates
```

### C. ranking

排序不能再只看“token 是否出现”，而要看：

- 精确层级命中
- bridge 命中
- accepted edge 邻近度
- file/module/symbol 权重
- evidence / anchor 完整度

### D. 输出投影

`locate` 返回结果必须分组，但分组仍然来自同一统一网络实体：

```text
primary_landings
bridge_landings
chain_anchors
fallback_candidates
```

这样 agent 才知道“先去哪里”与“顺着哪里推链路”不是一回事，但它面对的仍然是一张统一图，而不是两张图切换。

## 4.2 控制桥确定性抽取层

新增系统 extractor，抽取以下桥接候选，并直接写入统一图的 physical bridge candidate plane：

### A. Renderer / Preload / IPC 桥

```text
window.api.someCall
-> preload api.someCall
-> ipcRenderer.invoke("channel")
-> ipcMain.handle("channel")
```

### B. Vue emit / parent handler 桥

```text
child emit("terminate")
-> parent @terminate="handleTerminate"
-> parent handler body
```

### C. HTTP / endpoint 桥

```text
frontend invoke / fetch / axios path
-> backend router.post("/path")
```

### D. Registry / config / tool 桥

```text
registry key
-> provider / tool / prompt / runtime consumer
```

这些都属于：

```text
系统抽 candidate bridge
agent 判 accepted/control significance
```

## 4.3 Repair Loop

统一 repair 闭环：

```text
detector emits maintenance signal
-> signal normalizer groups scope
-> repair work item planner
-> repair graph materialization
-> review / trace / aggregate agents
-> curator validation
-> publish generation
-> re-materialize artifacts
-> close signal / mark superseded
```

Git 只是其中一条 detector。repair 最终更新的也是同一张统一图，而不是单独的“语义补丁库”。

## 4.4 维护与修复的同源原则

必须锁死以下工程原则：

1. repair 不单独造系统，走 maintenance 主链。  
2. repair 更新统一项目控制网络中的语义 facet、bridge judgement 和 control surface，不伪造物理骨架真相。  
3. signal source 决定为什么修，不决定走哪套流程。  
4. 系统只抽候选硬桥，agent 只做语义裁决。  
5. 同一 stable_ref / edge_id 的补网、维护、重审必须写回同一 graph generation。  

## 5. 实施方案

## Phase 1 维护信号统一化

目标：

- 把 `git only` 维护升级为多来源维护信号。

主要改动：

- 新增 `ProjectNetworkMaintenanceSignalRecord`
- 新增 signal normalizer / planner
- 扩展 repair work item schema
- 让 `artifact_audit`、`locate_failure`、`bridge_gap` 可入队

受影响模块：

- `backend/task_system/project_network/store_models.py`
- `backend/task_system/project_network/repository.py`
- `backend/task_system/project_network/service.py`
- `backend/file_management/project_structure/maintenance_service.py`

完成标准：

- git signal 和 audit signal 能写入同一 repair planning 流程
- work item 不再强依赖 `change_set_id`

## Phase 2 深度索引入口修复

目标：

- 重写 `locate`，让它成为真实导航入口。

主要改动：

- 改造 `_tokens(...)`
- 新增 query normalizer / alias expansion / multi-channel retrieval / weighted ranking
- 输出 grouped landings 而不是单平面 matches

受影响模块：

- `backend/capability_system/tools/tool_units/project_network_tool.py`
- `backend/task_system/project_network/semantic_artifact_materializer.py`

完成标准：

- 中文 query 不再系统性失效
- `provider management`、`终止任务`、`websocket ipc`、`llm factory` 四类查询都能稳定落对第一跳

## Phase 3 控制桥抽取器

目标：

- 让系统确定性建立 renderer-preload-ipc-http 及 emit-parent 桥候选。

主要改动：

- 新增 bridge extractors
- 把 bridge candidates 接入 signal chain candidate plane
- 缺桥时生成 audit / repair signal

受影响模块：

- `backend/task_system/project_network/semantic_artifact_materializer.py`
- `backend/task_system/project_network/work_product_extractor.py`
- `backend/task_system/project_network/template_catalog.py`

完成标准：

- `providerPage -> preload -> ipc -> backend`
- `taskPage -> preload -> backend stop_task`
- `wsClient registerWebsocketIpc`

这三类链路至少能以 candidate + evidence 形式自动建线。

## Phase 4 Repair Graph 与契约

目标：

- repair 不靠人工重跑 build，而是系统按 signal scope 调 agent 补网。

主要改动：

- 新增 repair materialization package
- repair graph 使用 `build_mode=repair`
- 为 `module repair` / `relation bridge repair` / `audit slice repair` 固定 prompt contract

受影响模块：

- `backend/task_system/project_network/graph_builder.py`
- `backend/task_system/project_network/template_catalog.py`
- `backend/graph_system/runtime_algorithm_adapters.py`
- `backend/agent_system/profiles/runtime_profile_registry.py`

完成标准：

- 指定 signal_ref 或 stable_ref 能生成 localized repair graph
- repair graph 只审相关 scope，不做全量重建

## Phase 5 工具层闭环

目标：

- 让 agent 既能读网络，也能发起 repair，而不需要知道底层表结构。

建议工具动作：

```text
locate
jump
trace
summarize_chain
read_audit
queue_repair
read_repairs
```

说明：

- `queue_repair(signal_ref | stable_ref | audit_code)` 只负责发起 repair
- 是否真正修复，由 maintenance / repair graph / curator 决定

受影响模块：

- `backend/capability_system/tools/tool_units/project_network_tool.py`

完成标准：

- agent 遇到断点时，能在工具层发起 repair，而不是只停在“发现问题”

## 6. 文件级执行清单

| 文件 | 角色 | 必做改动 |
| --- | --- | --- |
| `backend/capability_system/tools/tool_units/project_network_tool.py` | 深度索引工具入口 | 重写 `locate` 检索栈，补 `queue_repair` / `read_repairs` |
| `backend/task_system/project_network/semantic_artifact_materializer.py` | 产物与审计生成 | 增加 bridge audit、signal 输出标准化、repair signal 种子 |
| `backend/task_system/project_network/store_models.py` | 项目网络 store 模型 | 新增 maintenance signal 记录，扩展 repair item |
| `backend/task_system/project_network/repository.py` | 存储层 | 持久化 signal / repair 触发器 / 状态 |
| `backend/task_system/project_network/service.py` | 编排入口 | 接入 signal normalize、repair planning、artifact rematerialize |
| `backend/task_system/project_network/template_catalog.py` | 审查契约 | 新增 repair posture 契约，限制 repair agent 只补相关 scope |
| `backend/task_system/project_network/graph_builder.py` | repair graph 物化 | 支持 `build_mode=repair` 的 localized graph |
| `backend/file_management/project_structure/maintenance_service.py` | 物理维护来源 | 保持 git/source 权威，并输出统一 maintenance signal 输入 |
| `backend/graph_system/runtime_algorithm_adapters.py` | 图算法门禁 | 识别 repair graph 的 typed work product 和失败反馈 |
| `backend/agent_system/profiles/runtime_profile_registry.py` | repair agent runtime profile | 配置低负载、无多余工具、只消费 repair packet |

## 7. 验证标准

真实验证必须以完整项目 probe 为准，不能用伪造数据。

推荐固定用例：

### 用例 A：供应商管理

查询：

```text
LLM供应商管理
provider management
create_llm_provider
```

通过标准：

- locate 第一跳能落到 `providerPage.vue`、IPC handler 或 backend endpoint 中至少一个高相关落点
- trace 能给出跨边界桥候选
- queue_repair 后能生成 relation / bridge repair item

### 用例 B：任务终止

查询：

```text
终止任务
stop task
terminate task
```

通过标准：

- 能落到 `taskCard.vue` / `taskPage.vue` / `stop_task`
- 能看见 emit / preload / backend 三段链

### 用例 C：WebSocket 初始化

查询：

```text
websocket register ipc
init websocket
```

通过标准：

- 能稳定落到 `wsClient.js#registerWebsocketIpc`
- jump 能给出 `initWS` / `closeWS` / reconnect 邻点

### 用例 D：LLM 工厂

查询：

```text
llm factory
get_llm_node
模型创建工厂
```

通过标准：

- 中文和英文都能稳定命中
- 能给出 `llm_factory.py -> llm_creator.py` 控制链

## 8. 风险控制

### 8.1 不能做的事

- 不能为了提高命中率把 candidate 当 accepted。
- 不能让 locate miss 直接触发全量 rebuild。
- 不能让 repair agent 读取整个项目重新审一次。
- 不能把 query telemetry 直接塞进长期记忆或上下文主槽。

### 8.2 必须保留的边界

- 物理网真相只由系统抽取层维护。
- repair 只更新 project network 语义层和控制桥层。
- curator 是 generation 发布门禁。

## 9. 最终裁决

本次修复不应被理解为：

```text
优化一下搜索算法
```

而应被理解为：

```text
把“深度索引 -> 断点检测 -> repair 发起 -> agent 补网 -> generation 回写”
建成项目控制系统的标准维护闭环
```

最终目标不是让 agent “搜得到更多东西”，而是让它：

```text
找得到
跳得准
看得懂
链得起
断了还能自己发起补网
```

这才符合成熟 agent 的项目控制标准。

## 10. 2026-07-03 实施补充：统一图物化与 repair 队列入口

本轮实施把“物理网络和语义网络合成同一项目控制网络”的原则落到产物层：

1. `semantic_artifact_materializer` 物化时必须生成 `unified_control_graph.json`，并额外输出 `PROJECT_UNIFIED_CONTROL_GRAPH.md`。
2. 系统从文件路径确定性补充 `folder://.`、目录节点、文件节点，以及 `contains_directory` / `contains_file` 物理结构边。
3. 每个统一图节点必须同时包含：
   - `identity`: `stable_ref`、`physical_ref`、`node_kind`
   - `physical_facts`: 物理校验、证据、锚点
   - `semantic_facets`: `layer`、标签、摘要、控制角色、置信度
   - `control_surface`: 推荐动作和审计信号
4. 人类报告分为四类：
   - 根目录总览：`PROJECT_NETWORK_REVIEW.md`
   - 根目录统一图：`PROJECT_UNIFIED_CONTROL_GRAPH.md`
   - 根目录坐标摘要：`PROJECT_SEMANTIC_COORDINATES.md`
   - 根目录链路审计：`PROJECT_SIGNAL_CHAIN_REVIEW.md`
5. 详细报告放在 `PROJECT_NETWORK_REPORTS/`：
   - `README.md`: 报告索引
   - `layers/`: system / directory / file / symbol 等层级报告
   - `directories/`: 目录汇总报告
   - `files/`: 单文件审查报告
6. `project_network` 工具新增 `queue_audit_repairs` 动作：
   - 默认只把 `warning/error` 审计信号转入 repair 队列。
   - 指定 `signal_ref` 或 `signal_code` 时执行精确入队。
   - 入队只创建 maintenance signal 和 repair work item，不直接修改统一图，也不绕过 curator 发布门禁。

这次补充后的核心标准是：

```text
系统建物理骨架和硬边
agent 审查并赋语义 facet
工具只暴露统一图入口
audit 信号进入 repair 队列
repair graph 再回到同一 generation
```
