# 项目控制系统三层网络与契约重写计划

状态：设计锁定稿，待实施  
日期：2026-07-02

## 1. 目的

本计划把“项目语义网络审查”从一组调试型 work product，升级为完整的项目控制系统。

目标不是生成更多索引文件，而是让 agent 真正获得三种能力：

```text
快速定位：知道应该落到哪个系统、目录、文件、函数。
快速理解：知道该节点负责什么、能控制什么、风险在哪里。
快速归纳链路：知道多个节点如何形成调用、配置、注册、运行、提示词或工具链路。
```

因此系统必须拆成三层网络：

```text
物理网络 Physical Network
  系统确定性建立，提供真实落脚点。

语义网络 Semantic Network
  agent 在物理网络上叠加理解，提供语义路标。

神经控制网络 Neural Control Network
  agent 使用物理层和语义层进行定位、跳转、链路归纳和审计反馈。
```

这三层必须叠加，但不能混成一个索引。物理层负责“能不能落地”，语义层负责“如何理解”，神经控制层负责“agent 如何用它控制项目”。

## 2. 当前问题

已有实测证明，树状图审查图已经能跑通：

```text
测试范围：backend/agent_system/models
产物：4 个 module_index，1 个 directory_summary
结果：completed=5, failed=0, blocked=0
并发：max_active_nodes=2 时能按窗口调度
聚合：directory aggregate 能等待直接文件 module_index 完成后运行
```

但当前产物不成熟，问题在结构而不只是格式：

| 问题 | 当前表现 | 真实风险 |
| --- | --- | --- |
| 把定位索引和链路归纳混在一起 | `deep_network_route_index.json` 同时承担节点、边、关系候选 | agent 无法区分“去哪”和“如何判断关系” |
| 缺少给人看的根目录报告 | md 报告只在 artifact 目录里 | 审查结果不能作为项目级可读交付物 |
| 缺少文件级报告 | 单文件审查只沉入 `module_index` | 人无法追溯每个审查 agent 的判断 |
| 语义坐标不是总结卡 | 当前更多是节点 dump | agent 不能快速用语义坐标导航 |
| 链路审计不足 | 只统计 unknown refs、candidate | 无法支撑“信号链路归纳” |
| 物理 ref 校验不足 | agent 提交的错误 ref 可能进入 route index | 定位网络会把猜测当真实路径 |
| 契约没有明确三层职责 | file / directory prompt 主要要求提交 work product | agent 不知道自己在为控制系统建哪一层网络 |

核心失败模式：

```text
从“如何物化 work product”出发，而不是从“agent 如何掌控项目”出发。
```

## 3. 源码依据

当前相关模块：

| 模块 | 当前职责 | 需要调整的方向 |
| --- | --- | --- |
| `backend/task_system/project_network/template_catalog.py` | 定义 project network 节点模板与 agent prompt contract | 重写 file / directory / root 契约，明确三层网络职责 |
| `backend/task_system/project_network/graph_builder.py` | 将目录帧物化为 tree_reduce 图 | 保持树算法骨架，不承担语义判断 |
| `backend/graph_system/loop.py` | GraphLoop 调度节点、执行 side effect、推进状态 | 保持执行权威，不写项目网络业务逻辑 |
| `backend/graph_system/runtime_algorithm_adapters.py` | 校验 tree_reduce typed work product | 增强契约门禁，但不生成语义 |
| `backend/task_system/project_network/work_product_extractor.py` | 从 node result 抽取 work product | 适配新的 typed semantic submission 字段 |
| `backend/task_system/project_network/service.py` | 摄取 work product，写入 Project Network Store | 接入新的报告和控制产物物化 |
| `backend/task_system/project_network/semantic_artifact_materializer.py` | 当前物化 route / signal / audit 产物 | 拆成报告、语义坐标、定位索引、信号链路四类产物 |
| `backend/file_management/project_structure/*` | 物理骨架、skeleton node/edge、导航 session | 作为物理网络权威，不接收 agent 伪造结构事实 |

必须保留的成熟设计原则：

```text
系统抽取硬事实，agent 只做语义判断。
GraphLoop 只执行图，不替业务层做判断。
任务图节点是单 agent 工作单元。
审查图是 tree_reduce 算法，不是审查专用调度器。
agent prompt 必须是可执行任务契约，不是开发说明。
```

## 4. 核心裁决

### 4.1 三层网络分工

```text
Physical Network
  owner: file_management.project_structure
  source: file tree, git facts, AST, imports, calls, registry/tool/prompt extractors
  answers: 真实节点在哪里，真实边是什么，哪个 ref 可落地
```

```text
Semantic Network
  owner: project_network review agents + project_network store
  source: file reviewer, directory reviewer, relation tracer, curator
  answers: 节点职责是什么，语义标签是什么，如何作为路标
```

```text
Neural Control Network
  owner: project control surface / project network tools
  source: physical route index + semantic coordinates + signal chain index + audit
  answers: agent 如何定位、跳转、归纳链路、审计缺口
```

### 4.2 深度网络与信号链路必须分离

```text
Deep Network Route Index
  只负责定位。
  它回答：我应该去哪一个物理/语义落点？
  它不负责判断链路含义。
```

```text
Signal Chain Index
  只负责关系归纳。
  它回答：这些落点之间如何形成链路，证据是什么，置信度如何？
  它不负责作为主要导航目录。
```

```text
Semantic Coordinates
  是总结性的语义路标卡。
  它回答：系统、目录、文件、函数在项目控制空间里的坐标是什么？
  它不能退化为节点 dump。
```

### 4.3 报告与机器索引分离

md 报告给人看，json 索引给 agent 和系统使用。

根目录必须有人工可读入口：

```text
PROJECT_NETWORK_REVIEW.md
PROJECT_SEMANTIC_COORDINATES.md
PROJECT_SIGNAL_CHAIN_REVIEW.md
PROJECT_NETWORK_REPORTS/
```

artifact 目录保存机器产物和可追溯快照：

```text
storage/tasks/project_network_artifacts/{build_id}/
  manifest.json
  semantic_coordinates.json
  deep_network_route_index.json
  signal_chain_index.json
  link_signal_audit.json
  reports/
  files/
  directories/
```

## 5. 目标产物模型

### 5.1 根目录人读报告

```text
PROJECT_NETWORK_REVIEW.md
```

职责：

- 给人看项目网络审查结果。
- 展示系统层、目录层、文件层的审查结论。
- 汇总覆盖率、风险、未审查范围、低置信区域。
- 链接到文件级和目录级报告。

禁止：

- 不保存原始 JSON dump。
- 不把所有节点边完整堆进去。
- 不承担 agent 的主导航索引。

### 5.2 根目录语义坐标报告

```text
PROJECT_SEMANTIC_COORDINATES.md
```

职责：

- 用简洁语义坐标说明项目主要系统、目录、文件、控制点。
- 每个坐标是路标卡，不是长摘要。
- 帮助人和 agent 快速理解项目语义空间。

坐标格式：

```text
坐标 ID
物理 ref
层级：system / directory / file / symbol
职责标签
控制能力
主要入口
主要下游
证据 refs
置信度
跳转建议
```

### 5.3 根目录信号链路报告

```text
PROJECT_SIGNAL_CHAIN_REVIEW.md
```

职责：

- 汇总调用、注册、配置、工具、prompt、runtime、state、IO 等链路。
- 区分 accepted / candidate / conflict / unresolved。
- 标出证据链、断点、低置信关系、待追踪任务。

禁止：

- 不替代 route index。
- 不把 candidate 写成 accepted。
- 不把语义相似性当作链路证据。

### 5.4 文件级报告

```text
PROJECT_NETWORK_REPORTS/files/{safe_file_ref}.review.md
storage/tasks/project_network_artifacts/{build_id}/files/{safe_file_ref}.semantic.json
```

每个 `module_index` 必须生成一份文件级报告。

文件级报告内容：

- 文件物理信息：path、file_ref、file_hash、AST/skeleton 状态。
- 文件语义坐标：职责、标签、控制能力、入口。
- 关键节点：class/function/method/config/tool/prompt/model。
- 输入输出：参数、返回、读写状态、外部依赖、side effects。
- 文件内确定链路。
- 跨文件候选链路。
- 证据、限制、未覆盖项。

### 5.5 目录级报告

```text
PROJECT_NETWORK_REPORTS/directories/{safe_folder_ref}.summary.md
storage/tasks/project_network_artifacts/{build_id}/directories/{safe_folder_ref}.semantic.json
```

每个 `directory_summary` 必须生成一份目录级报告。

目录级报告内容：

- 目录物理范围。
- 目录语义坐标。
- 子文件职责汇总。
- 子目录职责汇总。
- 目录内主链路。
- 冲突和未覆盖。
- 上交父层的 compact route card。

### 5.6 机器可读产物

```text
semantic_coordinates.json
```

职责：

- 提供总结性语义坐标。
- 每个 coordinate 必须绑定物理 ref 或标记为 unresolved。
- 供 agent 快速缩小搜索范围。

```text
deep_network_route_index.json
```

职责：

- 只保存可导航落点。
- 每个 route node 必须经过物理 ref 校验。
- 不可信节点不进入 reliable_routes，只进入 unresolved_routes。

```text
signal_chain_index.json
```

职责：

- 只保存链路归纳和证据关系。
- 按 source、target、edge_kind、confidence、status 建索引。
- 生成 relation-trace 队列建议。

```text
link_signal_audit.json
```

职责：

- 审计链路质量。
- 报告 unknown ref、missing evidence、missing anchor、duplicate edge、conflict、candidate backlog。

## 6. 契约重写方案

### 6.1 单文件审查 agent 契约

角色应改为：

```text
你是一名单文件项目控制语义审查员。
你只负责系统提供的一个物理文件。
你的任务不是总结文件，而是在该物理文件上建立可被后续 agent 使用的语义坐标和控制路标。
```

输入边界：

```text
系统提供：
  assigned_scope.file_path
  assigned_scope.file_stable_ref
  file_text
  file_hash
  file_skeleton
  ast_projection
  upstream directory/system labels

禁止：
  不读取其它文件
  不搜索项目
  不读取记忆
  不扩展目录范围
```

必须输出一个 typed submission：

```text
submission_kind=module_index
physical_binding
semantic_coordinate
module_review_report
control_nodes
io_surface
accepted_internal_edges
relation_candidates
external_stubs
coverage
limitations
uncovered_refs
```

关键要求：

- `physical_binding` 说明文件 ref、hash、AST/skeleton 可用性。
- `semantic_coordinate` 是总结性路标卡。
- `module_review_report` 是可渲染为 md 的报告数据，不是 final_answer。
- `control_nodes` 只收录对项目控制有意义的节点。
- `io_surface` 必须说明输入、输出、读写、side effects。
- `accepted_internal_edges` 只能来自当前文件可见证据。
- 跨文件关系只能进入 `relation_candidates` 或 `external_stubs`。

### 6.2 目录汇总 agent 契约

角色应改为：

```text
你是一名目录级项目控制语义汇总员。
你只消费系统提供的直接文件审查结果和子目录汇总结果。
你的任务不是重新审查代码，而是在目录物理层上汇总语义坐标、职责边界和链路信号。
```

输入边界：

```text
系统提供：
  directory_frame
  folder_stable_ref
  direct module_index products
  child directory_summary products
  child report refs

禁止：
  不读取文件
  不搜索代码
  不把自然语言摘要直接提升为 accepted graph fact
  不静默覆盖冲突
```

必须输出一个 typed submission：

```text
submission_kind=directory_summary
physical_binding
semantic_coordinate
directory_review_report
child_coordinate_summary
directory_control_routes
accepted_relation_candidates
conflicts
coverage
uncovered_refs
parent_return_payload
```

关键要求：

- `directory_review_report` 用于生成目录级 md。
- `child_coordinate_summary` 是子文件/子目录的职责归纳。
- `directory_control_routes` 只归纳目录内清晰链路。
- `parent_return_payload` 必须压缩，只给父层继续归约所需内容。

### 6.3 根级汇总 / 物化契约

根级不应只是把 directory_summary 写成 artifact。

根级物化必须执行：

```text
读取所有 accepted/current work products
校验 physical_binding
生成文件级报告
生成目录级报告
生成语义坐标
生成深度定位索引
生成信号链路索引
生成链路审计
生成根目录人读报告
写 manifest
```

根级物化不允许：

- 创造新的语义事实。
- 把 unknown physical ref 伪装成可靠 route。
- 把 candidate relation 提升为 accepted。
- 用自然语言报告反推结构化事实。

## 7. 神经控制网络设计

神经控制网络不是新的大模型推理层，而是 agent 使用项目网络的控制界面。

它应该提供四类能力：

### 7.1 定位

输入：

```text
能力名 / 文件名 / 系统名 / 标签 / 物理 ref / 语义坐标
```

输出：

```text
可落地 route candidates
每个候选的 physical ref、semantic coordinate、confidence、recommended next action
```

数据来源：

```text
Physical Network + Semantic Coordinates + Deep Network Route Index
```

### 7.2 跳转

输入：

```text
当前 ref + 目标意图
```

输出：

```text
父级、子级、相邻模块、调用链下游、注册入口、配置入口等跳转路径
```

数据来源：

```text
Physical Network edges + Semantic route cards
```

### 7.3 链路归纳

输入：

```text
起点 ref / 终点 ref / 功能主题 / edge kind
```

输出：

```text
accepted chains
candidate chains
conflicts
missing evidence
recommended relation-trace tasks
```

数据来源：

```text
Signal Chain Index + Link Signal Audit
```

### 7.4 反馈修复

输入：

```text
unknown ref
missing evidence
low confidence
conflict
stale physical ref
```

输出：

```text
repair work item
relation-trace task
file re-review task
directory re-aggregate task
```

数据来源：

```text
Link Signal Audit + git change set + skeleton freshness
```

## 8. 具体实现方法

### 8.1 系统建线方法

系统建线不使用“全图乱搜”，而使用白名单抽取器、统一规范化和模板链路构建。

固定流水线：

```text
Source Extractors
-> SkeletonFact
-> SkeletonNode / SkeletonEdge
-> ChainCandidate
-> AuditSignal
```

抽取器分层：

```text
File Tree Extractor
  生成 repo / directory / file 的层级节点和 contains 边。

Deep AST Extractor
  生成 module / class / function / method / parameter / call_site。
  生成 defines / calls / imports / inherits / decorates 等边。

Domain Extractors
  生成 tool registry、agent registry、prompt registry、graph edge、
  permission policy、runtime facade、context pipeline、API route 等领域边。
```

所有系统线统一规范化为物理边：

```text
PhysicalEdge {
  source_ref
  target_ref
  edge_kind
  evidence_refs
  anchor_refs
  extractor
  confidence
  resolution_status
  freshness
}
```

控噪分级：

```text
L0 physical_hierarchy
  文件树和 AST defines，默认可靠。

L1 resolved_code_edge
  import / call / register / route / tool / prompt，有 evidence 和 anchor 才可靠。

L2 candidate_relation
  有线索但 target 未完全解析，只进入 candidate。

L3 noisy_signal
  名字相似、文本相似、普通 helper 调用，默认不进入主网络，只进入 audit/backlog。
```

主网络只接收低噪声线：

```text
没有 source_ref / target_ref 不入库。
没有 evidence_refs 不成为 accepted edge。
无法落到 physical skeleton 的 ref 不进 reliable route。
fan-out 过大的通用工具函数降权。
低价值 private helper 默认不进控制网络，除非它控制权限、状态、工具、prompt、graph、runtime。
跨文件调用如果目标不能解析，只能是 candidate。
```

### 8.2 链路候选构建方法

系统不寻找所有可能路径，而是按控制链路模板构建候选链。

第一批链路模板：

```text
tool_call_chain
prompt_assembly_chain
graph_execution_chain
permission_gate_chain
memory_context_chain
state_persistence_chain
frontend_backend_contract_chain
```

链路构建步骤：

```text
1. 选择入口节点
   route / registry / graph node / runtime facade / prompt pack / tool entry。

2. 限制 edge kind
   每个 chain template 声明允许的 edge_kind 序列或集合。

3. 有界路径搜索
   限制 depth、fan-out、重复节点、低置信边数量。

4. edge folding
   把低层 calls/imports/registers 折叠成可读 control segment。

5. evidence aggregation
   汇总 evidence_refs、anchor_refs、extractor、freshness。

6. confidence scoring
   根据 resolved edge 比例、anchor 覆盖、stale 边、candidate 边计算。

7. audit emission
   对 unknown ref、missing evidence、ambiguous target、stale edge 生成审计信号。
```

输出：

```text
ChainCandidate {
  chain_candidate_ref
  chain_kind
  entry_ref
  terminal_ref
  node_refs
  edge_refs
  folded_segments
  evidence_refs
  gaps
  confidence
  status = candidate
}
```

系统只能输出候选链，不直接裁决链路语义。

### 8.3 agent 赋义方法

agent 不从零建物理线，只审查系统提供的节点、边和候选链。

单文件 agent 输出：

```text
ModuleSemanticSubmission {
  submission_kind = module_index
  physical_binding
  semantic_coordinate
  control_nodes
  io_surface
  accepted_internal_edges
  relation_candidates
  external_stubs
  module_review_report
  coverage
  limitations
}
```

链路审查 agent 输出：

```text
SemanticChainOverlay {
  binds_to = chain_candidate_ref
  semantic_label
  control_meaning
  control_role
  accepted_edges
  downgraded_edges
  rejected_edges
  missing_evidence
  risk_notes
  confidence
}
```

agent 判断固定回答五个问题：

```text
证据是否真实？
链路表示什么职责？
是否属于控制链路？
对定位 / 修改 / debug 是否有价值？
accepted / candidate / conflict / rejected？
```

发布规则：

```text
系统证明线存在。
agent 解释线意义。
curator 决定是否进入 published semantic network。
```

没有绑定物理 ref 或 chain_candidate_ref 的语义，不允许进入正式网络。

### 8.4 神经控制工具方法

神经控制层做成操作 API，不做全量索引倾倒。

第一批工具能力：

```text
locate(intent)
  读取 semantic_coordinates，返回候选落点。

jump(ref, direction)
  从 ref 查父级、子级、调用方、下游、注册点、配置点。

trace(ref/topic)
  查询 signal_chain_index，返回相关链路。

summarize_chain(chain_ref)
  返回压缩链路说明、证据、置信度、风险。

repair(signal_ref)
  把 unknown ref / missing evidence / stale edge 转成重审或补链任务。
```

agent 标准使用流：

```text
任务目标
-> locate 找区域
-> jump 找落点
-> trace 找链路
-> summarize_chain 理解影响面
-> audit / repair 判断是否补证据
-> rg / read_file 精确取证
```

工具响应必须是局部、压缩、可行动的，不允许一次性把所有索引塞给 agent。

### 8.5 生命周期方法

项目网络必须按 git 和 file hash 增量维护。

固定刷新流：

```text
文件变化
-> skeleton node / edge 标 stale
-> 受影响 semantic overlays 标 stale
-> 受影响 chain candidates 标 stale 或 needs_review
-> 生成 repair work items
-> 只重审受影响文件 / 目录 / 链路
```

维护 agent 只处理受影响区域，不做全项目重审。

维护任务输入：

```text
git change set
changed file refs
touched skeleton node ids
touched skeleton edge ids
previous semantic overlay refs
affected chain candidate refs
```

维护任务输出：

```text
file re-review tasks
directory re-aggregate tasks
chain re-review tasks
semantic repair decisions
```

### 8.6 代码落地模块

具体落地文件：

```text
backend/file_management/project_structure/
  skeleton_extractors/
  chain_candidate_builder.py
  semantic_models.py
  maintenance_service.py

backend/task_system/project_network/
  template_catalog.py
  work_product_extractor.py
  semantic_artifact_materializer.py
  service.py
  work_product_models.py

backend/graph_system/
  runtime_algorithm_adapters.py
  runtime_algorithm_effects.py

backend/capability_system/tools/tool_units/
  project_network_tool.py
```

实现顺序必须遵守：

```text
先物理线。
再候选链。
再 agent 语义覆盖层。
再控制产物。
再神经控制工具。
最后接增量维护。
```

## 9. 实施计划

### Phase 1：重写契约

影响文件：

```text
backend/task_system/project_network/template_catalog.py
```

工作：

- 重写 module_index prompt contract。
- 重写 directory_aggregate prompt contract。
- 增加三层网络总契约。
- 增加文件报告、目录报告、语义坐标、链路信号的字段要求。

完成标准：

- prompt 是 agent 可执行任务契约。
- contract 明确物理层、语义层、控制层边界。
- 不再只要求“提交 module_index / directory_summary”。

### Phase 2：更新 work product 抽取与门禁

影响文件：

```text
backend/task_system/project_network/work_product_extractor.py
backend/graph_system/runtime_algorithm_adapters.py
```

工作：

- 接收新的 typed submission 字段。
- 校验 `physical_binding`、`semantic_coordinate`、`module_review_report` / `directory_review_report`。
- 对缺少物理绑定、缺少语义坐标、缺少报告数据的结果返回质量反馈。

完成标准：

- agent 输出不符合新契约时不能假成功。
- 失败反馈能返回同一节点重试。

### Phase 3：重构物化器

影响文件：

```text
backend/task_system/project_network/semantic_artifact_materializer.py
backend/task_system/project_network/service.py
```

工作：

- 拆分 report materialization、coordinate materialization、route index materialization、signal chain materialization。
- 生成根目录 md。
- 生成文件级 md 和目录级 md。
- 生成 artifact 目录中的 json 快照。
- manifest 记录所有人读和机器读产物路径。

完成标准：

- 根目录有三份核心 md 报告。
- 每个 module_index 有文件级报告。
- 每个 directory_summary 有目录级报告。
- json 索引不再混用职责。

### Phase 4：物理 ref 校验

影响文件：

```text
backend/task_system/project_network/semantic_artifact_materializer.py
backend/file_management/project_structure/repository.py
```

工作：

- 使用 skeleton node/edge 校验 stable_ref。
- route index 分为 reliable_routes 和 unresolved_routes。
- unknown ref 只能进入 audit，不进入可靠定位网络。
- signal chain 可以保留 unknown/candidate，但必须标注 unresolved target。

完成标准：

- 错误路径不会成为可靠 route。
- link audit 能明确指出哪个 ref 无法落地。

### Phase 5：神经控制工具接入

影响文件：

```text
backend/capability_system/tools/tool_units/project_network_tool.py
backend/file_management/project_structure/control_service.py
backend/capability_system/tools/native_tool_catalog.py
```

工作：

- 提供读取语义坐标工具。
- 提供深度定位工具。
- 提供信号链路归纳工具。
- 提供链路审计读取工具。
- 工具说明明确“定位”和“链路归纳”不是同一能力。

完成标准：

- agent 可以先读 semantic coordinates，再按 route index 落点，再按 signal chain 归纳链路。
- 工具不会把所有索引一次性塞给 agent。

### Phase 6：真实运行验证

验证范围：

```text
backend/agent_system/models
```

验证条件：

- 通过真实 graph runtime 跑 tree_reduce。
- 不人工伪造产物。
- 不新增测试文件。
- 检查根目录 md、文件级 md、目录级 md、json 机器索引。

通过标准：

```text
PROJECT_NETWORK_REVIEW.md 存在且可读
PROJECT_SEMANTIC_COORDINATES.md 存在且是总结性坐标
PROJECT_SIGNAL_CHAIN_REVIEW.md 存在且区分 accepted/candidate/conflict
每个 module_index 有文件级报告
每个 directory_summary 有目录级报告
deep_network_route_index 只承载定位
signal_chain_index 只承载链路归纳
unknown ref 不进入 reliable routes
manifest 记录所有产物路径和 hash
```

## 10. 文件级执行清单

| 文件 | 当前角色 | 行动 |
| --- | --- | --- |
| `template_catalog.py` | agent 契约定义 | 重写 file / directory 契约，加入三层网络和报告要求 |
| `work_product_extractor.py` | 输出抽取 | 适配新 typed submission 字段 |
| `runtime_algorithm_adapters.py` | tree_reduce 门禁 | 增加 physical/semantic/report contract gate |
| `semantic_artifact_materializer.py` | 产物物化 | 拆分报告、坐标、定位、链路、审计 |
| `service.py` | work product 摄取 | 接入新 artifact set，并把根目录报告路径写入 receipt |
| `project_network_tool.py` | 项目网络工具 | 暴露 semantic coordinates / route / signal / audit 读取能力 |
| `control_service.py` | 项目网络导航控制 | 接入语义坐标作为 path candidate 的语义增强，不写语义事实 |
| `README.md` | 文档索引 | 加入本计划 |

## 11. Debug 与改代码的价值边界

本系统的价值不在于替代基础搜索，而在于为复杂项目提供 agent 的代码掌控面。

常规小任务仍应优先使用：

```text
rg / 精确搜索
-> read_file / exact evidence
-> 小范围修改
-> 真实运行验证
```

项目控制系统适用于链路型、跨模块、影响面不清楚的任务：

```text
agent runtime
tool calling
prompt assembly
memory / context
workflow graph
permission / action permit
frontend-backend contract
state projection
task graph / side effect sink
```

### 11.1 对 debug 的帮助

debug 的核心是找断点和传播路径。三层网络分别提供：

```text
物理网络
  定位函数、文件、注册点、调用方、配置点、状态读写点。

语义网络
  判断模块职责和控制意义，例如权限、调度、存储、输出、prompt、工具边界。

信号链路
  归纳 bug 可能沿哪条链传播，哪里证据确定，哪里只是 candidate。
```

debug 时 agent 应使用以下流程：

```text
失败现象 / 错误日志 / 用户描述
-> locate 语义坐标，确定系统区域
-> jump 到入口、注册点、下游或调用方
-> trace 相关 signal chain
-> audit 链路证据、stale edge、unknown ref、低置信节点
-> 读取最小 physical slice 和必要源码
-> 修改或继续追踪
```

### 11.2 对改代码的帮助

改代码前，项目控制系统应帮助 agent 回答：

```text
入口在哪里？
下游影响谁？
调用方是谁？
注册点、配置点、权限点在哪里？
哪些关系是 accepted，哪些只是 candidate？
修改后应该验证哪条链？
```

推荐改动流程：

```text
任务目标
-> semantic_coordinates 定位系统区域
-> deep_network_route_index 找可靠落点
-> signal_chain_index 查看上下游和控制流程
-> link_signal_audit 判断可信度和缺口
-> read_file / rg 精确取证
-> 修改
-> 按链路选择真实验证路径
```

### 11.3 严肃限制

本系统不能替代：

```text
agent 对代码的真实理解
运行时真实验证
人工架构判断
复杂业务语义推理
边界条件分析
```

如果物理抽取噪声高、语义审查粗糙、链路长期不维护，它会比普通搜索更危险，因为 agent 会被错误路线误导。

因此必须坚持：

```text
宁可少建线，也不能建假线。
宁可保留 candidate，也不能假装 accepted。
宁可要求补证据，也不能把语义相似当链路事实。
```

### 11.4 使用定位

最终定位：

```text
rg + read_file
  是基础搜索和最终取证工具。

project control network
  是复杂项目控制层，用于定位、跳转、链路归纳和影响面判断。
```

成熟使用方式：

```text
常态小任务：
  rg + read_file

复杂链路任务：
  project control network -> rg/read_file 精确取证
```

这套体系只有在 agent 真实使用它来减少盲搜、缩小上下文、判断影响面、选择验证路径时，才算成功。

## 12. 禁止事项

- 禁止把 `deep_network_route_index` 做成大杂烩。
- 禁止把 `signal_chain_index` 当导航主索引。
- 禁止把 agent 自然语言报告反解析为结构化事实。
- 禁止 unknown ref 进入可靠 route。
- 禁止用兼容分支长期保留旧物化语义。
- 禁止让 GraphLoop 承担项目网络业务判断。
- 禁止让文件审查 agent 读取额外文件或使用搜索工具。
- 禁止用人工写入产物来冒充实测。
- 禁止把项目控制系统当作 `rg + read_file` 的替代品。
- 禁止在没有真实验证的情况下相信语义链路结论。

## 13. 预期结果

完成后，项目控制系统应形成以下闭环：

```text
系统建立物理网络
-> tree_reduce 派发文件/目录审查
-> agent 在物理节点上写语义坐标和报告事实
-> store 保存 typed work products
-> materializer 生成报告、语义坐标、定位索引、信号链路、审计
-> agent 通过神经控制工具读取坐标、定位、链路、审计
-> git/skeleton 变化触发修复和重审
```

这样 agent 才不是靠裸搜索理解项目，而是顺着项目控制系统工作：

```text
物理层给落脚点。
语义层给方向。
信号链路给关系归纳。
神经控制层给 agent 的行动界面。
```
