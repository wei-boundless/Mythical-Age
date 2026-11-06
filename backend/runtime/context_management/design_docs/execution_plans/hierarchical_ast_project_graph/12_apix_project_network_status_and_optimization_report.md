# Apix 项目网络实测状态与优化技术报告

状态：Apix 大项目实测后报告  
日期：2026-07-03  
实测项目：`D:\AI应用\Apix-Version_2.1`  
实测 build：`apix_v2_1_project_network_probe_20260702_092845`

## 1. 报告结论

当前项目网络已经具备“项目级深度索引”的基本能力：系统可以从物理文件树、目录层级、文件模块和符号节点生成统一控制图，agent 可以通过 `project_network.locate / jump / trace / start_navigation` 找到项目落脚点，并在 Apix 这种中等偏大的项目中快速定位主要系统和功能节点。

但它还没有达到完整“项目控制系统”的成熟标准。现在强的是“找点”和“局部下钻”，弱的是“跨系统信号链路贯通”和“候选关系自动修复”。也就是说：

```text
物理骨架：可用
语义路标：初步可用
功能级定位：可用
架构总览入口：已修正为可用
信号链路归纳：局部可用，但跨系统桥接不足
维护闭环：有工具入口，但还需要按 git/改动影响面做自动修复流
```

如果目标是让 agent 像成熟 coding agent 一样掌控项目，下一阶段不应该继续堆搜索算法，而应该强化三件事：

1. 用系统抽取器建立可靠物理线和代码线。
2. 用 agent 审查和语义 overlay 给物理线赋予职责、意图和控制提示。
3. 用控制工具把“定位、下钻、追链、修复、发布 generation”连成闭环。

## 2. 当前功能现状

### 2.1 已物化的 Apix 网络产物

Apix 项目根目录已经生成以下人类和 agent 可读产物：

- `PROJECT_ARCHITECTURE_OVERVIEW.md`
- `PROJECT_NETWORK_REVIEW.md`
- `PROJECT_SEMANTIC_COORDINATES.md`
- `PROJECT_SIGNAL_CHAIN_REVIEW.md`
- `PROJECT_UNIFIED_CONTROL_GRAPH.md`
- `PROJECT_NETWORK_REPORTS/README.md`
- `PROJECT_NETWORK_REPORTS/directories/*.summary.md`
- `PROJECT_NETWORK_REPORTS/files/*.review.md`
- `PROJECT_NETWORK_REPORTS/layers/*.md`
- `storage/tasks/project_network_artifacts/<build_id>/unified_control_graph.json`

本次重新物化后的核心规模：

| 指标 | 数量 |
| --- | ---: |
| source work products | 351 |
| unified graph nodes | 919 |
| unified graph edges | 1415 |
| accepted edges | 913 |
| candidate edges | 502 |
| audit signals | 945 |
| file reports | 253 |
| directory reports | 98 |
| layer reports | 5 |
| bad empty edges | 0 |

### 2.2 已经可用的能力

**一级系统架构识别**

`PROJECT_ARCHITECTURE_OVERVIEW.md` 能清楚显示 Apix 的一级系统：

- `AGENT`：Agent 服务与核心运行时。
- `CLIENT`：Electron/Vue 桌面端。
- `TASK`：任务流服务。
- `MEMORY`：记忆服务。
- `FILE`：文件/RAG/向量服务。
- `README`：项目文档入口。
- `mythical-agent`：空目录或预留目录。

**项目级查询入口**

`project_network.locate("整体架构")` 和 `project_network.locate("系统架构")` 已经会返回：

- 推荐报告：`PROJECT_ARCHITECTURE_OVERVIEW.md`
- 根节点：`folder://.`
- 一级系统：`folder://AGENT`, `folder://CLIENT`, `folder://TASK`, `folder://MEMORY`, `folder://FILE`

这修掉了之前“整体架构”误命中普通 UI 方法的问题。

**功能级定位**

实测中以下查询都能找到合理节点：

- `agent core`
- `任务终止`
- `LLM供应商管理`
- `websocket ipc`
- `memory module`
- `file service rag`

例如：

- `任务终止` 能命中前端 `handleTerminate`、后端 `stop_task`、停止子助手工具和任务卡片组件。
- `LLM供应商管理` 能命中 `providerPage.vue`、`ProviderEditDialog.vue`、`providerCard.vue`。
- `websocket ipc` 能命中 Electron 主进程 `registerWebsocketIpc` 和后端 WebSocket endpoint。

**trace 首屏可读性**

`project_network.trace` 现在不再只返回数量，而会直接列出：

- accepted edges
- candidate edges
- conflict edges
- chain anchors
- audit codes

这对 agent 很重要，因为 agent 第一屏就能判断哪些线可信、哪些线需要 repair。

**控制层导航**

`start_navigation` 现在可以不显式传 `build_id`，工具会默认读取最新 build。架构目标下，路径候选优先展示一级系统目录，README/setup 文件不再抢占第一屏。

### 2.3 已完成的入口级修正

本次修正集中在入口和报告层，没有重写底层建图算法：

- `semantic_artifact_materializer.py`
  - 新增 `PROJECT_ARCHITECTURE_OVERVIEW.md`。
  - `PROJECT_NETWORK_REPORTS/README.md` 改为按系统分组，不再平铺 253 个文件报告。
  - 过滤缺 source 或 target 的无效边，避免 `None -> None` 污染报告。

- `project_network_tool.py`
  - 增加架构意图识别，项目级查询优先落到架构总览。
  - `trace / jump / locate` 的文本摘要显示节点、边、状态和 audit code。
  - `start_navigation` 支持默认 latest build。

- `control_service.py`
  - 优化路径候选排序。
  - 架构导航时优先系统目录，再显示 README/setup 等根文件。

## 3. 主要问题点

### 问题 1：跨系统桥接线还不够成熟

当前最大短板不是找不到文件，而是不能稳定贯通“从一个系统到另一个系统”的真实调用链。

典型例子：

```text
CLIENT providerPage.vue
-> global://getProviders
-> preload contextBridge
-> ipcRenderer.invoke(...)
-> ipcMain.handle(...)
-> 后端 settings / provider API
```

现在 `providerPage.vue -> global://getProviders` 仍是 candidate，目标是 `global://getProviders`，没有自动解析到 preload、主进程 IPC 或后端 API。

另一个例子：

```text
taskCard.vue handleTerminate
-> confirmDialog
-> window.api / websocket / http
-> AGENT routers/infomation.py stop_task
-> task_manager.stop_task
```

当前前端 `handleTerminate` 的 trace 只看到 confirm dialog 这条 candidate，没有形成完整端到端链路。

### 问题 2：candidate 边过多，可信链和待修链混在一起

当前 Apix 有 `502` 条 candidate edges，主要 audit code 包括：

- `candidate_relation_needs_resolution`
- `unknown_target_ref`
- `out_of_scope_source_ref`
- `out_of_scope_target_ref`
- `unknown_source_ref`

这说明系统已经发现了大量可疑链路，但还没有足够的 resolver 把它们升级为 accepted，或者明确降级为 rejected/noise。

成熟的控制图不能让 agent 在 candidate 海里猜。candidate 应该成为 repair queue 的输入，而不是日常导航的主路径。

### 问题 3：语义报告已有层级，但还缺“架构解释层”

现在目录报告和文件报告数量完整，但许多报告还是“局部说明”，不能完全替代架构解释。

已改善的部分：

- 有 `PROJECT_ARCHITECTURE_OVERVIEW.md`。
- 有一级系统职责。
- 有报告索引分组。

仍不足的部分：

- 系统之间的 service boundary 不够清晰。
- 每个系统的入口、出口、依赖、被依赖关系不够集中。
- 缺少“关键功能链路专题报告”，例如任务终止链、LLM provider 管理链、WebSocket IPC 链。

### 问题 4：神经控制层还偏“路径候选”，不够“目标驱动”

`start_navigation` 当前能按物理结构给出路径候选，但它还不是完整的目标规划器。

理想行为是：

```text
目标：追踪任务终止链路
系统判断：
1. 这是功能链路目标，不是纯目录浏览。
2. 入口应从 locate("任务终止") 的高分节点开始。
3. 对前端 handler、后端 endpoint、task manager 分别 trace。
4. 对断开的 candidate bridge 发起 repair。
5. 输出可信链路与缺口。
```

当前还需要 agent 自己组合 `locate -> trace -> queue_repair`，工具层没有把这个组合收敛为更高阶的控制投影。

### 问题 5：维护闭环还没有充分自动化

现在已经有 repair / audit / collect changes 的工具入口，但还没有形成成熟维护流：

```text
git diff
-> 影响节点识别
-> skeleton 局部刷新
-> semantic overlay 失效检测
-> repair work items
-> agent 补语义
-> curator 校验
-> 发布新 generation
```

这会导致一个风险：网络建立后，如果代码修改频繁，语义层和信号层会逐渐失真。

## 4. 优化原则

### 4.1 物理层是权威骨架

物理层必须由系统确定性抽取：

- git
- 文件树
- AST / Deep AST
- import/export
- function/class/symbol
- route decorator
- IPC channel
- contextBridge
- store/module registry

agent 不能凭想象铺物理线。agent 只能对物理线进行语义解释、关系判断和修复建议。

### 4.2 语义层是方向路标

语义层回答：

- 这个节点负责什么？
- 它属于哪个系统？
- 它是入口、出口、协调器、适配器、存储、UI、工具还是配置？
- 读它时应该关注什么？
- 它和哪些链路有关？

语义层必须绑定 evidence refs，不能脱离物理节点独立飘着。

### 4.3 神经控制层是 agent 操作界面

神经控制层不是又一张图，而是 agent 使用物理层和语义层的控制面：

- locate：从意图找到落脚点。
- jump：沿物理/语义邻接下钻。
- trace：追踪信号链路。
- summarize_chain：把链路压成可读摘要。
- read_audit：看不可信点。
- queue_repair：把断线交给修复流。
- start_navigation / select_path：形成可追踪控制会话。

### 4.4 accepted 和 candidate 必须严格区分

accepted 表示可作为导航依据。

candidate 表示“可能有关，但必须修复或确认”。agent 可以参考 candidate，但不能把 candidate 当作真实架构结论。

## 5. 具体技术方案

### Phase 1：稳定架构入口和报告面

目标：让人和 agent 能先看懂项目。

已完成：

- 生成 `PROJECT_ARCHITECTURE_OVERVIEW.md`。
- 根报告按系统列一级落脚点。
- report index 按系统分组。
- `locate("整体架构")` 进入架构总览。
- `trace` 展示具体边。
- 过滤空边。

下一步补强：

1. 在 `PROJECT_ARCHITECTURE_OVERVIEW.md` 增加每个系统的：
   - inbound accepted edges
   - outbound accepted edges
   - candidate bridge count
   - known entry files
   - known API/IPC endpoints

2. 增加专题链路报告：
   - `PROJECT_NETWORK_REPORTS/chains/task_termination.md`
   - `PROJECT_NETWORK_REPORTS/chains/provider_management.md`
   - `PROJECT_NETWORK_REPORTS/chains/websocket_ipc.md`

3. 给 `project_network.locate` 增加 intent kind：
   - `project_overview`
   - `system_overview`
   - `feature_entry`
   - `api_or_ipc_bridge`
   - `symbol_trace`
   - `repair_target`

### Phase 2：补桥接抽取器

目标：把 candidate bridge 尽量升级成 accepted bridge。

#### 2.1 Electron / Vue IPC 桥接抽取

需要抽取的模式：

```text
renderer Vue
-> window.api.xxx(...)
-> preload contextBridge.exposeInMainWorld("api", { xxx: ... })
-> ipcRenderer.invoke("channel", payload)
-> main ipcMain.handle("channel", handler)
-> service/module/backend
```

技术实现：

- JS/Vue AST 扫描：
  - 识别 `window.api.<method>`。
  - 识别 `const { xxx } = window.api`。
  - 识别 `this.$api`、globalProperties、Pinia/store 封装。

- Preload 抽取：
  - 识别 `contextBridge.exposeInMainWorld(name, object)`。
  - 建立 `global://<method> -> ipc://<channel>`。

- Main process 抽取：
  - 识别 `ipcMain.handle/on(channel, handler)`。
  - 建立 `ipc://<channel> -> handler://<file>#<handler>`。

- 接受规则：
  - method name 和 channel exact match：accepted。
  - method name alias 或字符串拼接：candidate。
  - 找不到 handler：unknown_target_ref。

#### 2.2 FastAPI 路由抽取

需要抽取：

```text
APIRouter(prefix="/settings")
@router.get("/providers")
app.include_router(router)
```

技术实现：

- Python AST 扫描 decorator：
  - `@router.get/post/put/delete/websocket(...)`
  - `APIRouter(prefix=...)`
  - `include_router(router, prefix=...)`

- 产出节点：
  - `api://AGENT/settings/providers#get`
  - `handler://AGENT/.../settings.py#get_providers`

- 产出边：
  - `api_route -> handler` accepted
  - `frontend ipc/http call -> api_route` accepted/candidate

#### 2.3 Store / module alias resolver

当前 `store://auth`、`store://app` 会出现 unknown/candidate。

技术实现：

- 建立 frontend alias table：
  - vite alias
  - jsconfig/tsconfig paths
  - relative imports
  - store registry
  - Pinia `defineStore`

- 产出：
  - `store://auth -> file://CLIENT/.../store/auth.js`
  - `store://app -> file://CLIENT/.../store/app.js`

#### 2.4 Python import resolver

当前 `external://apix_agent...task_manager.stop_task` 这种边应优先尝试解析到项目内文件。

技术实现：

- 从 pyproject / package root 建立 import root。
- `apix_agent.*` 映射到 `AGENT/agent_module/apix_agent/*`。
- 解析 module import、from import、attribute chain。
- exact module resolved 且目标文件存在：accepted。
- symbol 未定位但文件定位成功：candidate with resolved_file。

### Phase 3：统一链路信号模型

目标：让每条线都能被审计、修复和升级。

统一 edge schema：

```text
edge_id
source_ref
target_ref
edge_kind
status: accepted | candidate | rejected | conflict
confidence: exact | derived | inferred | agent_reviewed
evidence_refs
anchor_refs
extractor_id
resolver_id
audit_codes
repair_state
generation
```

关键规则：

- 缺 source 或 target 的边不得入图。
- accepted 必须有 evidence_refs。
- candidate 必须有 repair reason。
- rejected 不能删除历史，应保留在 repair/audit store，但不进入日常导航。
- graph report 默认显示 accepted，candidate 单独作为待修区域。

### Phase 4：建立 repair 同源维护流

目标：断线、未知 ref、候选桥都能进入同一个维护系统。

流程：

```text
read_audit
-> queue_audit_repairs
-> repair work items
-> repair agent / current coding agent
-> system resolver rerun
-> submit_overlay or publish extractor result
-> curator validation
-> new generation
```

技术实现：

- `unknown_target_ref` 自动生成 resolver repair。
- `candidate_relation_needs_resolution` 自动生成 relation review repair。
- `out_of_scope_*_ref` 自动判断是 scope 问题还是 resolver 问题。
- repair 结果必须写入同一个 Project Network store，不允许产生平行修复表。

### Phase 5：git 增量维护

目标：代码改动后网络不失真。

流程：

```text
git diff --name-status
-> changed files
-> affected file modules
-> affected symbols / routes / IPC channels
-> invalidate related semantic overlays
-> local skeleton refresh
-> local bridge resolver refresh
-> queue semantic repair if needed
-> publish new generation
```

需要新增或补强：

- file hash 到 module card 的变更检测。
- deleted file 的 edge tombstone。
- renamed file 的 stable ref migration。
- changed endpoint / IPC channel 的 downstream repair。
- agent 自己改代码后可提交 semantic overlay，但必须经过系统校验。

### Phase 6：目标驱动的神经控制投影

目标：让 agent 不只是拿到路径候选，而是拿到“下一步控制建议”。

新增控制投影：

```text
ProjectNetworkControlProjection
- intent_kind
- recommended_start_refs
- accepted_chain_candidates
- candidate_bridge_gaps
- required_reads
- suggested_repairs
- confidence
- next_actions
```

例子：

```text
goal: 追踪任务终止链路
intent_kind: feature_chain_trace
recommended_start_refs:
  - fn://CLIENT/.../taskCard.vue/handleTerminate
  - pyast://AGENT/.../infomation.py#stop_task
accepted_chain_candidates:
  - stop_task -> task_manager.stop_task
candidate_bridge_gaps:
  - handleTerminate -> backend stop_task bridge missing
next_actions:
  - trace front handler
  - resolve window.api / websocket bridge
  - queue repair for unresolved candidate
```

这会让 agent 的操作从“自己拼工具调用”升级为“系统提供可执行控制面”。

## 6. 实施顺序

推荐按风险和收益排序：

### Step 1：完成 bridge extractor MVP

优先级最高。

范围：

- preload `contextBridge`
- ipcMain handle/on
- renderer `window.api`
- FastAPI route
- Python package import resolver

验收：

- `providerPage.vue -> global://getProviders` 能解析到真实 preload/main/API 链路，至少不再停在 unknown target。
- `handleTerminate -> stop_task` 能形成跨 CLIENT/AGENT 的候选或 accepted 链。

### Step 2：建立 chain reports

范围：

- 从 locate 高分节点和 accepted/candidate edges 生成专题链路报告。
- 每份报告分为：
  - accepted route
  - candidate gaps
  - unknown refs
  - suggested repairs

验收：

- agent 问“任务终止怎么走”时，不需要手动翻 10 个报告。

### Step 3：repair queue 自动化

范围：

- audit signal 到 repair work item 的映射。
- resolver repair 和 semantic review repair 分开。
- repair 完成后重新物化。

验收：

- `unknown_target_ref` 能变成具体 repair task。
- repair 后 edge 状态能从 candidate 升级、降级或 rejected。

### Step 4：git 增量维护

范围：

- 根据 git changes 局部刷新 skeleton / bridge / semantic overlay。
- 删除、重命名、修改分别处理。

验收：

- 修改一个 Vue 文件或 FastAPI router 后，只刷新相关网络片段，不重建全项目。

### Step 5：控制投影升级

范围：

- `locate` 输出 intent kind。
- `start_navigation` 可以接收 intent refs。
- 新增目标驱动 chain projection。

验收：

- agent 可以从“目标”直接得到起点、链路、缺口和修复建议。

## 7. 成熟度判断

当前成熟度：

```text
项目物理网络：B+
语义坐标：B
架构入口：B+（本轮已修正）
功能定位：B
局部 trace：B-
跨系统链路：C
repair 维护闭环：C+
agent 神经控制层：B-
```

达到成熟项目控制系统的最低标准，需要把以下能力拉到 B+ 以上：

- 跨系统 bridge resolver。
- candidate repair 闭环。
- git 增量维护。
- 目标驱动控制投影。

## 8. 最终裁决

Apix 实测证明：这个项目网络方案方向是可行的，而且不是空想。物理层和语义层叠加后，agent 确实可以比普通 `rg + read_file` 更快建立项目落脚点，尤其适合大项目的系统级理解和功能入口定位。

但要成为真正的“深度网络项目控制系统”，下一步必须把桥接线做硬。否则它会停留在“更好的索引和报告”，而不是“能顺着项目神经网络追踪、判断、修复和维护”的控制系统。

下一阶段工程重心应明确为：

```text
bridge extractor
-> signal resolver
-> repair queue
-> git incremental maintenance
-> intent-driven control projection
```

这条线比继续扩展普通搜索算法更重要。

## 9. 补充方向：Architecture Intelligence Layer

深度网络的最终价值不应只停留在“更强的搜索”和“更清楚的报告”。它应该继续升级为 agent 的外置架构脑，帮助 agent 弥补天然的架构意识不足、局部最优倾向和复用率低的问题。

### 9.1 要解决的 agent 弱点

当前 coding agent 在复杂项目中常见问题是：

- 容易只看当前文件，顺手新写一套局部逻辑。
- 不知道项目里已经存在类似能力、服务、工具、协议、状态模块或扩展点。
- 很难稳定判断“这个需求应该属于哪个系统、哪一层、哪个入口”。
- 对影响面判断弱，改一个点时不容易意识到 API、IPC、store、runtime、prompt、tool registry 或上下文链路会被牵动。
- 对架构坏味道不敏感，例如重复实现、越层调用、职责过载、平行链路和循环依赖。

深度网络正好可以补这些能力。它不是替 agent 思考，而是给 agent 提供可验证的架构空间、复用线索和控制约束。

### 9.2 目标定位

Architecture Intelligence Layer 的目标是：

```text
让 agent 写代码前先理解架构，
实现功能前先发现可复用能力，
修改代码前先判断影响面，
完成修改后再反查架构破坏和重复造轮子。
```

它依托三层网络：

```text
物理网络：文件、目录、AST、函数、class、route、IPC、import/export
语义网络：系统职责、模块职责、能力标签、控制角色、功能入口
神经控制层：locate、jump、trace、reuse check、architecture check、repair
```

### 9.3 新增索引设计

在现有项目网络基础上，应增加三类架构智能索引。

**Capability Index**

记录项目已经具备哪些能力，以及能力对应的物理入口和语义入口。

示例：

```text
capability: LLM provider 管理
system: CLIENT / AGENT
entry_refs:
  - file://CLIENT/.../providerPage.vue
  - file://CLIENT/.../ProviderEditDialog.vue
  - api://AGENT/settings/providers
control_role:
  - UI management
  - settings API
  - provider registry
```

用途：

- 新需求进来时，先查是否已有相似能力。
- 避免 agent 新建平行模块。
- 帮 agent 找到正确扩展点。

**Reuse Candidate Index**

记录语义相近、输入输出相近、调用边相近或职责相近的模块与函数。

来源：

- 函数名 / class 名 / 文件名。
- semantic summary。
- IO surface。
- import/call edges。
- API route / IPC channel。
- tool registry / factory / adapter。

用途：

- 在新增功能前提示“这里可能已有可复用实现”。
- 在重构时发现重复逻辑。
- 在代码审查时发现低复用率结构。

**Architecture Smell Index**

记录架构风险信号。

可检测的 smell：

- 多个节点语义相似但没有复用关系。
- 同一功能在多个系统重复实现。
- UI 越层调用底层实现。
- runtime 绕过 harness / registry / authority。
- 工具绕过统一 tool catalog。
- prompt 系统耦合具体任务图。
- 某个文件同时承担入口、调度、存储、协议、UI 等过多职责。
- candidate bridge 长期未修复。
- import/call 形成环或反向依赖。

用途：

- 给 agent 修改前的风险提示。
- 给重构计划提供证据。
- 给维护 agent 生成 repair 或 refactor work item。

### 9.4 agent 写代码前的控制流程

成熟流程不应该是 agent 直接读文件然后开写，而应该是：

```text
需求理解
-> locate 所属系统
-> 查询 capability_index
-> 查询 reuse_candidate_index
-> 读取 accepted architecture path
-> 判断正确扩展点
-> 编辑代码
-> 刷新局部网络
-> 检查 architecture_smell_index
-> 输出修改影响面和复用依据
```

如果系统发现已有能力，agent 必须优先解释为什么复用或为什么不能复用。不能在没有检查复用候选的情况下直接新建平行链路。

### 9.5 架构优化工作流

Architecture Intelligence Layer 还应支持主动优化：

```text
扫描网络
-> 聚类相似能力
-> 找重复实现
-> 找越层调用
-> 找高 candidate bridge 区域
-> 找职责过载节点
-> 生成 architecture review report
-> 生成 refactor candidates
-> 由 agent 制定重构计划
-> 修改后刷新网络并复查
```

这使深度网络从“项目理解工具”升级为“架构治理工具”。

### 9.6 关键边界

这层能力必须遵守几个边界：

- 物理事实仍由系统抽取，不由 agent 想象。
- 语义判断必须绑定 evidence refs。
- candidate 只能作为提示，不能作为架构事实。
- 复用建议必须说明依据，例如相似职责、相同 IO、相同调用链或相同 registry。
- 架构 smell 不能直接等同于 bug，只能作为审查和优化信号。
- refactor 建议必须经过影响面分析，不能只凭语义相似就合并模块。

### 9.7 技术落点

后续可以在项目网络 store 中增加：

```text
project_capabilities
project_reuse_candidates
project_architecture_smells
project_architecture_reviews
```

并在 `project_network` 工具中增加或扩展动作：

```text
find_capability
find_reuse_candidates
check_architecture_smells
explain_extension_point
review_change_impact
queue_refactor_candidate
```

这些动作不应该替代 `locate / jump / trace`，而应该组合它们：

```text
find_capability = locate + semantic tags + accepted route index
find_reuse_candidates = capability similarity + IO similarity + edge similarity
check_architecture_smells = graph rules + candidate audit + dependency structure
review_change_impact = git diff + affected graph slice + trace
```

### 9.8 最终判断

这个方向可行，而且应成为深度网络的长期核心方向。

如果只做搜索，深度网络最多是更好的索引。如果继续向 Architecture Intelligence Layer 演进，它就能帮助 agent：

- 更快理解项目架构。
- 更主动发现已有能力。
- 更少重复造轮子。
- 更稳地选择扩展点。
- 更准确判断修改影响面。
- 更系统地发现架构坏味道。

因此，后续优化目标应从“让 agent 找得到代码”升级为：

```text
让 agent 在写代码前知道项目已有架构，
在写代码时遵守架构边界，
在写完代码后能反查是否破坏架构和复用原则。
```
