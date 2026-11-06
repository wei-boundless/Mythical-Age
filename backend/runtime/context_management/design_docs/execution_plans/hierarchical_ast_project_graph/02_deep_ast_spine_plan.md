# Deep AST 树深化方案

状态：设计稿，待审阅后实施  
日期：2026-07-01

## 1. 目标

Deep AST Spine 是项目语义空间的结构骨架和审查权威。它的职责不是保存漂亮的语义总结，而是把源码转成可查询、可验证、可刷新、可被 agent 控制的 hard facts。

```text
Source File
-> Concrete AST
-> Enriched AST
-> Scope / Symbol Binding
-> Import / Reference Index
-> Call Site Index
-> Function / Parameter / Call Cards
-> Lightweight Dataflow / Side Effect Index
-> Semantic File Module
```

### 1.1 普通 AST 与 Deep AST 的裁决

普通 AST 足够作为第一版骨架，但不够支撑“精准项目控制”。系统不能从零重写 parser，也不能把普通 AST 的 outline 伪装成项目语义网络。正确做法是在成熟 parser / 标准 AST 之上建立自己的 Deep AST 后处理与索引层。

工程裁决：

```text
普通 AST:
  提供 module / class / function / method / import / call / assignment / line range 等语法事实。

Deep AST Index:
  在普通 AST 上生成稳定 anchor、symbol binding、call site、function card、parameter card、import/reference/call relation candidate。

Semantic File Module:
  以单文件为最小审查调度单位，消费 Deep AST facts，由 agent 形成文件模块语义卡。

Project Semantic Graph:
  使用文件模块语义卡、目录索引、系统汇总和总汇总建立项目级语义空间。
```

因此第一版不能把函数作为 graph node。函数、class、参数、调用点是文件模块内的结构化索引对象；graph node 的最小调度单位是单文件模块审查。这样既能深入到文件内部，又不会让图任务节点爆炸。

职责边界：

```text
系统负责：
  解析 AST、建立 anchor、生成文件内结构索引、识别 imports/calls/references、维护 hash 与 freshness。

agent 负责：
  判断文件职责、核心函数语义、外部联系是否构成架构关系、风险点、边界问题和汇总裁决。
```

这条边界是审查图任务的前置基础：先把 Deep AST 系统做好，再让审查 agent 基于可验证事实逐层建立语义控制。

### 1.2 AST 作为 agent 环境能力扩展

普通 AST 和 Deep AST 不应硬编码在审查图任务里，也不应挂到 `TaskEnvironmentSpec` 上成为任务环境字段。任务环境负责文件边界、存储、沙箱和资源空间；AST 是 agent 运行环境中配备的代码理解能力，节点可以在自己的 runtime policy 中声明或覆盖需要的 AST 档位。

目标形态：

```text
AgentRuntimeProfile
-> runtime_policy.context_policy.code_intelligence.ast.mode = basic_ast | deep_ast | disabled
-> runtime_policy.context_policy.code_intelligence.ast.language_profiles = python | typescript | mixed
-> runtime_policy.context_policy.code_intelligence.ast.refresh_policy = on_file_hash_change | manual | scheduled
-> runtime_policy.context_policy.code_intelligence.ast.projection_policy = outline_only | file_module_index | deep_control_index

TaskGraphNodeDefinition
-> runtime_policy.context_policy.code_intelligence.ast.mode 可覆盖 agent 默认能力
-> runtime_policy.context_policy.code_intelligence.ast.required = true 时，缺失或 stale 只能降级输出，不允许发布高置信 generation
```

两档 AST agent 能力：

```text
basic_ast:
  基础语法事实层。
  提供文件 outline、imports、classes、functions、methods、line ranges。
  适合系统/文件夹层扫描、轻量搜索、单文件粗理解。

deep_ast:
  普通 AST 的升级能力。
  依赖 basic_ast 的 parse facts，再生成 stable anchors、symbol binding、call site、function card、parameter card、relation candidates。
  适合单文件模块索引、endpoint 抽取、跨文件关系追踪、审查图任务和精准项目控制。
```

配置原则：

- `basic_ast` 是低成本默认能力，可以配给 coordinator、系统层/文件夹层节点或普通代码检索 agent。
- `deep_ast` 是显式升级能力，配给 coding 主 agent、codebase_searcher、project_network_builder、curator，以及 module/endpoint/relation/validate 类节点。
- `deep_ast` 不能绕过 `basic_ast` 直接制造事实；它只能在基础 AST parse facts 上做索引增强。
- agent profile 是默认能力权威；node runtime policy 是当前节点的覆盖/收紧权威；task environment 不决定 AST 档位。
- 审查图任务节点如果声明 `required=true` 且 Deep AST 缺失或 stale，只能进入降级审查模式，不能发布高置信项目语义 generation。

这意味着 AST 能力应出现在 runtime projection / node contract 的能力表里：

```text
agent_visible_runtime_projection.code_intelligence.ast:
  enabled: true
  mode: deep_ast
  language_profiles: ["python"]
  read_units: ["file_module", "function_endpoint", "call_site", "relation_candidate"]
  freshness_policy: "file_hash_bound"
  projection_policy: "file_module_index"
  authority: "agent_runtime_profile.context_policy.code_intelligence"
```

agent 看到的是运行包投影后的能力契约：

```text
你可以读取当前文件模块的 Deep AST 索引。
你可以引用函数、类、调用点和关系候选的 anchor。
你不能把没有 AST/evidence anchor 的外部联系写成 accepted relation。
如果 Deep AST 缺失或 stale，你必须报告 coverage gap，而不是编造关系。
```

这个设计把 AST 从“工具函数”提升为“agent 运行环境能力”。审查图任务只是通过节点契约消费该能力，不拥有 AST 权威；节点可以要求更高档位，但不能替系统伪造 AST fact。

## 2. 可复用现状

本项目已有基础：

- `backend/capability_system/tools/tool_units/python_ast_tools.py`
  - 已用 Python 标准库 `ast` 提取 class/function/method/import/top-level variable。
  - 当前是临时扫描工具，缺少持久索引、参数卡片、调用边、数据流边。
- `backend/runtime/tool_runtime/native_tools.py`
  - 已统一 native tool execution、workspace root、read_file exact artifact。
- `backend/file_management` 与 workspace file service
  - 可作为文件 hash、mtime、路径归一的基础。

裁决：`python_ast_tools.py` 不应继续拥有独立全库扫描权威。它应收束为 Deep AST Index 的薄工具，或保留单文件 outline / parse check。

## 3. AST 层级

```text
Level 0 Concrete AST:
  原始语法节点、父子关系、行列范围、stable ast path、文本 digest。

Level 1 Structural AST:
  module / class / function / arguments / param / assign / call / return / name / attribute / literal。

Level 2 Symbol Spine:
  scope、definition、reference、import binding、local binding、attribute access。

Level 3 Control Endpoints:
  class、function、parameter、call_site、attribute、route/tool/prompt_slot hard refs。

Level 4 Lightweight Behavior:
  calls_text、resolved candidate、reads/writes attribute、mutates、returns、side effect note。
```

模型不能写 Level 0-3 的 hard facts。Level 4 的自然语言 side effect note 可以是 derived/hypothesis。

## 3.1 审查图任务中的读取单位

审查图任务第一版采用“自底向上建证据，自顶向下控范围”的读取单位：

```text
G0 文件树规划:
  读取目录结构，给出初始系统/文件夹边界和 file module shard 计划。

G1 文件模块审查:
  一个 graph node 审查一个文件模块。
  输入 Deep AST file index、symbol/function/call anchors、必要上层目录路标。
  输出 ModuleSemanticCard、FunctionEndpointIndex、ExternalRelationCandidates、RiskFindings、CoverageReport。

G2 文件夹聚合:
  汇总同一文件夹内的 ModuleSemanticCard，形成 FolderSemanticIndex。

G3 系统聚合:
  汇总多个文件夹，形成 SystemSemanticIndex。

G4 全项目总汇总:
  只读系统级汇总、冲突与覆盖缺口，形成 ProjectSemanticGeneration candidate。
```

文件模块审查产物必须带 AST/evidence anchor。没有 anchor 的函数关系、外部依赖和风险判断只能作为 hypothesis，不能进入可发布 generation。

文件模块标准产物首版字段：

```text
ModuleSemanticCard:
  file_ref
  file_hash
  module_role
  owned_system_candidate
  key_classes
  key_functions
  exported_capabilities
  internal_dependencies
  external_dependency_candidates
  inbound_entry_candidates
  risk_findings
  coverage
  evidence_refs
  ast_anchor_refs

FunctionEndpointIndex:
  function_anchor
  signature
  responsibility_summary
  call_sites
  external_relation_candidates
  side_effect_candidates
  confidence

ExternalRelationCandidate:
  source_file
  source_anchor
  target_file_candidate
  target_anchor_candidate
  relation_kind
  evidence_ref
  confidence
```

这使 agent 的审查动作和系统的 Deep AST 事实对齐：agent 不需要猜文件里有什么，系统先把可验证结构端出来；agent 只做语义裁决和风险判断。

## 4. 核心表

`ast_nodes`：

```text
ast_node_id TEXT PRIMARY KEY
file_ref TEXT
node_kind TEXT
parent_ast_node_id TEXT
path TEXT
start_line INTEGER
end_line INTEGER
start_col INTEGER
end_col INTEGER
stable_ast_path TEXT
text_digest TEXT
metadata_json TEXT
content_hash TEXT
freshness TEXT
```

`ast_edges`：

```text
ast_edge_id TEXT PRIMARY KEY
src_ast_node_id TEXT
dst_ast_node_id TEXT
edge_kind TEXT
evidence_ref TEXT
confidence TEXT
```

`symbol_bindings`：

```text
binding_id TEXT PRIMARY KEY
file_ref TEXT
scope_ast_node_id TEXT
symbol_name TEXT
binding_kind TEXT
definition_ast_node_id TEXT
reference_ast_node_ids_json TEXT
confidence TEXT
```

`function_cards` / `parameter_cards` / `call_sites` 从 AST spine 派生，不能由模型直接创建。

## 5. 构建流程

```text
Workspace Scan
-> File Fingerprint
-> Concrete AST Parse
-> AST Node / Parent-Child Edge Persist
-> Scope / Symbol Binding
-> Import / Reference Index
-> Call Site / Argument Index
-> Function / Parameter Cards
-> Lightweight Dataflow / Side Effect Index
-> Deep AST Generation Publish
```

AST-first 原则：

- 所有函数卡、参数卡、调用边、side effect 索引都从 AST spine 生成。
- import/reference/call resolution 可以是 derived，但必须保留 unresolved 原始文本和 AST anchor。
- 文件变更时先刷新 AST spine，再刷新 semantic overlay。
- 没有 AST/registry anchor 的语义边不能进入可用图。

## 6. Python AST 首版范围

首版只做 Python backend，覆盖：

- module/class/function/method/async function。
- arguments、positional/keyword-only/defaults/annotations。
- import/import-from。
- call expression 的 callee_text、receiver_text、args、kwargs。
- return、assign、annassign、augassign。
- attribute read/write 候选。
- docstring、top-level constants 摘要。

首版 Deep AST 还必须服务文件模块审查，因此至少要能为单文件生成：

- `FileModuleAstIndex`：文件 hash、imports、classes、functions、methods、assignments、call sites、exports、symbol anchors、line ranges。
- `FunctionEndpointIndex`：函数/方法签名、参数、decorators、return anchors、call sites、side effect candidates。
- `ModuleRelationCandidates`：import relation、call relation、registry/config relation 的候选边，保留 unresolved 原始文本。

不伪装解决：

- 动态 import。
- monkey patch。
- 运行时依赖注入。
- 高精度 interprocedural dataflow。
- 完整动态调用解析。

这些只能标成 `derived` 或 `unresolved`。

### 6.1 2026-07-01 Python 首版实现记录

已落地确定性的 Python 单文件 Deep AST 索引器：

```text
backend/capability_system/capabilities/code_intelligence/__init__.py
backend/capability_system/capabilities/code_intelligence/python_ast_indexer.py
backend/capability_system/tools/tool_units/python_ast_tools.py
backend/capability_system/capabilities/codebase_search/providers.py
```

本次实现范围：

- 新增 `FileModuleAstIndex(schema_version=python_file_module_ast_index.v1)`，以文件 hash 绑定当前源码事实。
- 生成稳定 `AstAnchor`，覆盖 module、class、function、async function、method、import、assignment、return、call_site。
- 顶层结构全部挂在 module root anchor 下，避免单文件模块的父子边断裂。
- 生成 `ast_edges`、`imports`、`classes`、`functions`、`call_sites`、`assignments`、`symbol_bindings`、`exports` 和 `limitations`。
- `FunctionEndpointCard` 暴露参数卡、decorators、return annotation、docstring、call_site anchors、return anchors、assignment anchors。
- `python_code_outline` 不再自行遍历 AST；它消费 `FileModuleAstIndex`，并在 structured payload 中暴露 `file_module_ast_index`。
- `python_symbol_search` 不再拥有独立符号抽取逻辑；它从同一索引器取 class/function/import/top-level assignment，并按 exact name / qualname 优先排序。
- `codebase_search` 的 symbol layer 继续使用现有工具入口，但诊断 authority 改为 `capability_system.capabilities.code_intelligence.python_ast_indexer`。

本次仍未做：

- 未实现持久化 AST store、file hash 增量刷新队列或 stale propagation。
- 未实现跨文件 import/call resolution；call relation 仍保留 unresolved 原始文本和 anchor。
- 未实现 TypeScript / TSX / JavaScript AST profile。
- 未把 Deep AST index 自动注入 graph node 执行输入；当前先完成 agent runtime capability 与工具权威收口。

验证结果：

```text
python -m compileall backend\capability_system\capabilities\code_intelligence backend\capability_system\tools\tool_units\python_ast_tools.py backend\capability_system\capabilities\codebase_search
  passed

python_file_module_ast_index smoke:
  schema_version=python_file_module_ast_index.v1
  module_anchor present
  top-level ast_edges present
  functions>0
  call_sites>0
  function anchors have path + line ranges

python_code_outline / python_symbol_search smoke:
  file_module_ast_index exposed
  source_authority=capability_system.capabilities.code_intelligence.python_ast_indexer
  exact class query returns class definition before related methods/imports

codebase_search symbol layer smoke:
  status=completed
  symbol authority=capability_system.capabilities.code_intelligence.python_ast_indexer
  findings produced
```

## 7. 增量刷新

```text
file hash changed
-> delete AST nodes/edges/cards owned by old file hash
-> re-extract Deep AST for changed file
-> rebuild control endpoints for module
-> mark dependent routes stale
-> refresh Semantic File Module
-> optionally queue graph task correction/review
```

刷新规则：

- hash 不变，不重建 AST。
- AST 结构不变，只变实现文本，可保留系统层语义，刷新 read windows。
- 函数签名变化，相关 call edge、parameter card、endpoint stale。
- route/tool/prompt registry 变化，触发 domain extractor。

## 8. VSCode 边界

当前 VSCode extension 主要提供 editor context：

- active file。
- visible files / selection。
- diagnostics。
- content preview。
- command bridge。

它不是 Deep AST 权威。

目标边界：

```text
Backend Project Graph Indexer = 深 AST 与持久索引权威
VSCode Extension = live editor sensor + optional LSP bridge
```

如果文件 dirty，以 VSCode dirty buffer 作为当前编辑器事实；如果已保存，以后端 hash 索引为准。VSCode LSP 结果只能作为 derived 辅助证据。

## 9. 验证

首版验收：

- 能对 `backend/prompt_library` 生成 AST nodes / function cards / parameter cards / call sites。
- 任一 function card 能回到 path + line range。
- 任一 endpoint 能回到 `semantic_file_module`。
- AST refresh 后旧 generation 不再作为当前事实。
- 不调用模型也能工作。
