# Project Graph 网络型深度搜索系统计划书

状态：设计稿，待审阅后实施  
日期：2026-07-01  
范围：`capability_system.capabilities.codebase_search`、`capability_system.tools`、`runtime.tool_runtime`、`runtime.context_management`、`harness.runtime`、`prompt_library`、前端工具轨迹与网络视图  
目标：把“深度搜索”建设为项目级关系网络能力，而不是一个更复杂的文本搜索工具。

## 1. 问题定义

当前常态搜索已经建立了成熟路径：

```text
search_text / rg-like locator
-> read_file exact evidence
-> 判断 / 回答 / 修改
```

这条路径适合找文件、找符号、找文本，但不适合回答跨模块关系问题，例如：

- 一个 prompt slot 如何进入 runtime message。
- 一个 tool schema 如何进入 tool executor、dynamic context、前端展示。
- 一个运行时事件从后端到前端经历哪些 projector。
- 一个 agent profile 的策略如何影响工具授权和上下文装配。

这些问题不是“搜索不到”，而是每次都要重新推断关系链。正确的系统属性应该是：

```text
项目结构和跨模块关系可被预先索引、可增量维护、可按模板遍历、可被 agent 受控使用。
```

因此目标不是替代 `rg`，而是新增一层：

```text
Project Graph Index
-> Traversal Templates
-> Graph Search Result
-> Candidate Read Windows
-> read_file exact evidence
```

## 2. 当前源码基础

已有能力：

- `backend/capability_system/tools/workspace_search_service.py`
  - 已负责 `search_text/search_files/glob_paths` 底层召回。
  - 已支持默认噪声排除、候选窗口、搜索 meta。
- `backend/capability_system/tools/tool_units/python_ast_tools.py`
  - 已使用 Python 标准库 `ast` 提取 class/function/method/import/top-level variable。
  - 当前是按请求临时扫描，不是持久索引。
- `backend/capability_system/capabilities/codebase_search/models.py`
  - 已有 `SearchCandidate`、`SearchFeedback`、`SearchLifecycleRecord`、`SearchResultEnvelope`。
  - 可作为图搜索结果 envelope 的基础。
- `backend/capability_system/capabilities/codebase_search/runtime.py`
  - 已有 path / glob / symbol / text / git history 的多层合流雏形。
  - 适合作为未来调用 Project Graph 的 orchestrator。
- `backend/runtime/tool_runtime/tool_executor.py`
  - 已统一工具 workspace root 解析。
  - 适合作为图查询工具的权限与执行边界。
- `backend/harness/runtime/dynamic_context/*`
  - 已能投影 locator facts / recommended windows。
  - 后续只应投影图搜索摘要，不应投影整张图。

缺口：

- 没有持久化项目关系图。
- AST 符号搜索不是索引服务，每次扫描成本高。
- 没有 typed edges 表达 `defines/imports/calls/registers/binds_slot/emits/projects_to/renders`。
- 没有模型辅助语义边抽取机制。
- 没有图遍历模板。
- 没有 graph result lifecycle 与 staleness 控制。
- agent 还不能通过结构化 API 沿网络查询，只能文本搜索后自己推断。

## 3. 核心设计裁决

### 3.1 大模型参与抽取，但不拥有事实权威

网络建立需要大模型能力，但大模型不能直接写入高可信事实边。

分层：

```text
Deterministic Extractor
-> hard facts / hard edges

Model Relation Extractor
-> semantic hypothesis edges

Graph Normalizer
-> typed edge + confidence + evidence_ref + freshness
```

硬事实来源：

- AST 定义、导入、类/函数位置。
- 明确注册表、manifest、operation id、prompt ref、路由表。
- 文件哈希、mtime、git status。
- 工具执行记录、read_file exact artifact。

模型负责：

- 识别“这个模块在架构中扮演什么角色”。
- 从 bounded evidence pack 中抽取语义关系。
- 把“看起来相关”归类为明确边类型或 rejected hypothesis。
- 给出 traversal template 的适用条件。

模型禁止：

- 编造不存在的文件、符号、函数。
- 在没有 evidence_ref 的情况下写入边。
- 把语义猜测标成 hard fact。
- 绕过 `read_file` 直接作为最终证据。

### 3.2 图搜索不是最终证据

图搜索返回的是关系 locator：

```text
graph_candidate
structural_evidence
recommended_read_window
staleness
confidence
limitations
```

最终裁决仍必须读取当前文件：

```text
read_file exact content
```

### 3.3 agent 通过工具 API 控制网络，不直接控制索引内部

agent 不应直接读 SQLite 表或遍历全图。应通过受控工具/API：

```text
project_graph_search
project_graph_neighbors
project_graph_explain_path
project_graph_refresh
```

工具层负责：

- 权限。
- traversal budget。
- freshness 检查。
- read window 生成。
- 输出压缩。
- lifecycle record。

## 4. 数据模型

MVP 使用 SQLite，避免一开始引入图数据库。

文件：

```text
storage/runtime_state/project_graph/project_graph.sqlite
```

### 4.1 nodes

```text
node_id TEXT PRIMARY KEY
node_kind TEXT
stable_key TEXT
display_name TEXT
path TEXT
start_line INTEGER
end_line INTEGER
symbol_kind TEXT
qualname TEXT
content_hash TEXT
index_generation TEXT
authority TEXT
metadata_json TEXT
created_at REAL
updated_at REAL
```

节点类型：

```text
file
python_module
python_symbol
prompt_resource
prompt_set
prompt_slot
tool_definition
operation
api_route
frontend_component
runtime_event
context_segment
database_table
documentation_section
```

### 4.2 edges

```text
edge_id TEXT PRIMARY KEY
src_node_id TEXT
dst_node_id TEXT
edge_kind TEXT
confidence TEXT
evidence_kind TEXT
evidence_ref TEXT
source_path TEXT
source_hash TEXT
index_generation TEXT
staleness TEXT
authority TEXT
metadata_json TEXT
created_at REAL
updated_at REAL
```

边类型：

```text
defines
imports
calls
references
registers
extends
binds_slot
uses_tool
authorizes_operation
emits_event
projects_to
renders
persists_to
reads_from
writes_to
configures
owns
depends_on
semantic_related
```

置信度：

```text
hard       # AST / manifest / registry / route / exact parser
derived    # 静态字符串、配置约定、可验证映射
hypothesis # LLM 从 evidence pack 抽取
rejected   # 已验证不成立或过期
```

### 4.3 files

```text
path TEXT PRIMARY KEY
content_hash TEXT
mtime_ns INTEGER
size_bytes INTEGER
language TEXT
parse_status TEXT
last_indexed_generation TEXT
dirty_state TEXT
diagnostics_json TEXT
```

### 4.4 graph_templates

```text
template_id TEXT PRIMARY KEY
title TEXT
intent_kind TEXT
seed_node_kinds_json TEXT
edge_sequence_json TEXT
stop_rules_json TEXT
read_window_policy_json TEXT
prompt_contract TEXT
authority TEXT
```

### 4.5 model_extraction_jobs

```text
job_id TEXT PRIMARY KEY
scope_kind TEXT
scope_ref TEXT
input_evidence_hash TEXT
model_id TEXT
status TEXT
output_hash TEXT
created_edges_json TEXT
rejected_edges_json TEXT
diagnostics_json TEXT
created_at REAL
completed_at REAL
```

## 5. 网络建立流程

### 5.1 全量构建

```text
Workspace Scan
-> File Fingerprint
-> Deterministic AST / Registry / Manifest Extractors
-> Node/Hard Edge Upsert
-> Evidence Pack Builder
-> Model Relation Extractor
-> Graph Normalizer
-> FTS / Path / Symbol Auxiliary Index
-> Publish Index Generation
```

### 5.2 增量构建

触发源：

- 文件写入工具。
- `git status` dirty files。
- 前端保存事件。
- 手动 `project_graph_refresh(paths=[...])`。
- 后端启动时发现文件 hash 变化。

流程：

```text
Dirty File Set
-> Recompute file hash
-> Delete stale nodes/edges owned by old file hash
-> Re-extract deterministic facts for changed files
-> Re-run model extraction only for affected bounded packs
-> Mark cross-file dependent edges as stale or verified
-> Publish new generation
```

原则：

- hash 不变，不重建。
- 文件级锁，不锁全库。
- LLM 抽取异步；hard graph 先可用。
- 模型抽取失败不阻塞 hard graph 查询。

## 6. 模型如何参与建图

### 6.1 Evidence Pack

模型不能直接吃全文件树。系统给模型的是 bounded evidence pack：

```text
file_path
file_hash
language
ast_outline
imports
top_symbols
selected_literals
registry_entries
nearby exact snippets
known existing nodes
candidate edge targets
```

每个 pack 控制在较小上下文，输出结构化 JSON。

### 6.2 模型输出 schema

```json
{
  "node_annotations": [
    {
      "node_ref": "python_symbol:backend/...:PromptSetResolver",
      "semantic_role": "prompt_set_inheritance_resolver",
      "confidence": "medium",
      "evidence_refs": ["backend/prompt_library/prompt_set_resolver.py:42-99"]
    }
  ],
  "edges": [
    {
      "src_ref": "python_symbol:...:PromptSetResolver.resolve",
      "dst_ref": "python_symbol:...:PromptSetResolver._visit",
      "edge_kind": "delegates_to",
      "confidence": "hypothesis",
      "evidence_refs": ["backend/prompt_library/prompt_set_resolver.py:48-53"],
      "reason": "resolve iterates refs and calls _visit"
    }
  ],
  "rejected_candidates": [
    {
      "src_ref": "...",
      "dst_ref": "...",
      "reason": "not supported by evidence pack"
    }
  ]
}
```

### 6.3 模型提示词契约

写给模型 extractor 的 prompt 必须像 agent prompt，而不是开发说明：

```text
你是一名项目关系抽取员。
你只根据收到的 evidence pack 抽取代码结构关系。
你不能发明文件、符号或调用。
你不能把不确定关系标成 hard fact。
你必须为每条关系给出 evidence_refs。
如果证据不足，你要拒绝该候选关系。
你的输出必须是指定 JSON schema。
```

## 7. 精准控制机制

### 7.1 Edge Authority

每条边都必须有：

```text
authority
evidence_kind
evidence_ref
source_hash
confidence
staleness
```

没有这些字段的边不能进入可查询图。

### 7.2 Staleness

```text
fresh       source_hash == current file hash
stale       source_hash != current file hash
unknown     外部来源或旧索引无 hash
invalid     节点或文件已删除
```

agent 可看到 stale，但工具必须提示：

```text
This graph edge is stale; use read_file before relying on it.
```

### 7.3 Traversal Budget

图搜索必须限制：

```text
max_hops
max_nodes
max_edges
allowed_edge_kinds
confidence_floor
freshness_required
template_id
```

默认不允许无边界全图遍历。

### 7.4 Read Window Policy

图搜索只返回候选窗口：

```text
path
start_line
end_line
match_line
reason
graph_path_ref
read_intent="project_graph_candidate"
```

不返回大段源码。

## 8. Agent 如何快速理解和判断

### 8.1 给 agent 的不是图，而是路线图

工具输出格式：

```text
GraphSearchResult
summary
seed_nodes
traversal_paths
important_edges
candidate_read_windows
limitations
freshness
next_allowed_actions
```

示例：

```json
{
  "summary": "PromptSet inheritance resolution is centered on PromptSetResolver._visit.",
  "seed_nodes": ["python_symbol:PromptSet"],
  "traversal_paths": [
    {
      "path_ref": "graphpath:...",
      "nodes": [
        "PromptSet",
        "PromptSetResolver.resolve",
        "PromptSetResolver._visit"
      ],
      "edges": ["referenced_by", "delegates_to"],
      "confidence": "hard+derived"
    }
  ],
  "candidate_read_windows": [
    {
      "path": "backend/prompt_library/prompt_set_resolver.py",
      "start_line": 42,
      "line_count": 70,
      "reason": "cycle detection and DFS traversal"
    }
  ],
  "next_allowed_actions": [
    "read_file candidate_read_windows before final claim"
  ]
}
```

### 8.2 判断规则

agent contract：

```text
你可以用 project_graph_search 快速建立模块关系。
图搜索结果是结构定位，不是最终证据。
如果你要引用代码、判断行为、修改文件，必须读取 candidate_read_windows。
如果图结果 stale、hypothesis 或 incomplete，你必须说明限制，或先 read_file 验证。
不要沿同一模板反复搜索；如果路径已清楚，转入 read_file。
```

## 9. API / Tool 设计

### 9.1 Tools

#### project_graph_search

用途：从自然语言/符号/路径出发，选择模板并返回关系路线。

输入：

```json
{
  "query": "PromptSet 继承解析入口",
  "intent": "architecture_trace",
  "roots": ["backend"],
  "template_id": "template.prompt_set_inheritance",
  "max_hops": 4,
  "max_results": 8,
  "confidence_floor": "derived",
  "freshness": "fresh_or_warn"
}
```

输出：

```text
GraphSearchResult envelope
```

#### project_graph_neighbors

用途：agent 已有 node_ref，要看上下游。

输入：

```json
{
  "node_ref": "python_symbol:backend/prompt_library/prompt_set_resolver.py:PromptSetResolver._visit",
  "direction": "both",
  "edge_kinds": ["calls", "references", "reads_from", "writes_to"],
  "depth": 2
}
```

#### project_graph_explain_path

用途：解释两个点之间为什么相关。

输入：

```json
{
  "source": "tool_definition:search_text",
  "target": "frontend_component:ToolTrace",
  "max_hops": 6
}
```

#### project_graph_refresh

用途：刷新索引。默认只允许只读扫描；写入索引是系统内部状态，不是项目代码修改。

输入：

```json
{
  "paths": ["backend/capability_system/tools/workspace_search_service.py"],
  "mode": "incremental",
  "include_model_extraction": false
}
```

### 9.2 Backend API

```text
POST /api/project-graph/search
POST /api/project-graph/neighbors
POST /api/project-graph/explain-path
POST /api/project-graph/refresh
GET  /api/project-graph/status
GET  /api/project-graph/templates
```

### 9.3 权限

新增 operation：

```text
op.project_graph_search
op.project_graph_refresh
```

`project_graph_search` 是只读能力。  
`project_graph_refresh` 只写 runtime storage，不写项目源码。

## 10. Traversal Templates

模板是深度搜索的关键，不是简单算法参数。

### 10.1 Prompt 系统模板

```text
seed: prompt_set | prompt_resource | prompt_slot | python_symbol
edges:
  extends
  binds_slot
  referenced_by
  assembled_by
  rendered_by
stop:
  runtime message producer
read:
  resolver / wiring / materializer / renderer
```

### 10.2 Tool 调用模板

```text
seed: tool_name | operation | native_tool_class
edges:
  defines
  authorizes_operation
  dispatches_to
  emits_event
  projects_to
  renders
stop:
  frontend trace or dynamic context projection
```

### 10.3 Runtime Event 模板

```text
seed: event_type
edges:
  emitted_by
  stored_in
  projected_by
  consumed_by
  renders
```

### 10.4 API 到前端模板

```text
seed: api_route | frontend_component
edges:
  route_handler
  calls_service
  emits_payload
  typed_by
  renders
```

## 11. 与 codebase_search 的关系

`codebase_search` 不应被废弃，应升级为 orchestrator：

```text
query_planner
-> path/text/symbol fast pass
-> project_graph_search when cross-module intent is detected
-> ranker
-> read window matrix
```

触发 `project_graph_search` 的条件：

- 用户问“链路、架构、怎么进入、怎么影响、从 A 到 B”。
- 常态搜索找到了多个模块但无法排序。
- 查询涉及 runtime / prompt / tool / frontend 多层。
- repeated rg-like search 未收敛。

不触发条件：

- 已知文件路径。
- 单个符号精确查找。
- 简单文本定位。
- 需要当前 exact 内容直接 `read_file`。

## 12. 前端展示

前端不要展示整张图。展示：

```text
Graph Summary
Selected Template
Seed Nodes
Traversal Paths
Candidate Read Windows
Freshness / Confidence
Limitations
```

UI 状态：

- hard edge：实线。
- derived edge：普通线。
- hypothesis edge：虚线。
- stale edge：警示。
- exact-read-confirmed：节点或窗口高亮。

## 13. 分阶段实施计划

### Phase 1: Deterministic Project Graph MVP

目标：

- SQLite schema。
- 文件 fingerprint。
- Python AST nodes：file/module/class/function/method/import/top-level variable。
- hard edges：defines/imports/contains。
- `project_graph_status` 与内部 refresh service。

影响文件：

```text
backend/capability_system/capabilities/project_graph/models.py
backend/capability_system/capabilities/project_graph/store.py
backend/capability_system/capabilities/project_graph/indexer.py
backend/capability_system/capabilities/project_graph/python_ast_extractor.py
backend/capability_system/tools/native_tool_catalog.py
backend/runtime/tool_runtime/native_tools.py
```

完成标准：

- 首次 refresh 能生成 nodes/edges。
- 修改单个 Python 文件后只重建该文件相关节点边。
- 不调用模型也能查 symbol/file/import 网络。

### Phase 2: Graph Query Tools

目标：

- `project_graph_search`
- `project_graph_neighbors`
- `project_graph_explain_path`
- 输出 candidate read windows。

完成标准：

- agent 可通过工具找到 `PromptSet -> PromptSetResolver._visit`。
- 图结果不包含源码全文。
- 所有最终判断仍需要 `read_file`。

### Phase 3: Model Relation Extractor

目标：

- Evidence pack builder。
- 结构化 JSON schema。
- hypothesis edge 写入。
- rejected candidates 记录。

完成标准：

- 模型只能基于 evidence pack 建边。
- 每条模型边有 evidence_ref。
- 模型边默认不能超过 `confidence=hypothesis`。

### Phase 4: Traversal Templates

目标：

- Prompt 系统模板。
- Tool 调用模板。
- Runtime event 模板。
- API/frontend 模板。

完成标准：

- codebase_search 能按 intent 调用模板。
- agent 能看到路线而不是原始图。

### Phase 5: Lifecycle Integration

目标：

- 文件写入工具触发 dirty path。
- 后端启动检查 stale index。
- graph generation / freshness 投影。
- read_file 消费后关联 exact evidence。

完成标准：

- stale edge 不再被当成可靠证据。
- read_file 后 graph candidate 可标记 consumed。
- 不把整张图放入动态尾。

### Phase 6: Frontend Graph Trace

目标：

- 展示 traversal path。
- 展示 confidence/freshness。
- 展示 read windows。

完成标准：

- UI 能区分 locator / structural / exact-read-confirmed。
- 不展示过量节点。

## 14. 文件级执行清单

新增：

```text
backend/capability_system/capabilities/project_graph/__init__.py
backend/capability_system/capabilities/project_graph/models.py
backend/capability_system/capabilities/project_graph/store.py
backend/capability_system/capabilities/project_graph/indexer.py
backend/capability_system/capabilities/project_graph/python_ast_extractor.py
backend/capability_system/capabilities/project_graph/model_relation_extractor.py
backend/capability_system/capabilities/project_graph/templates.py
backend/capability_system/capabilities/project_graph/query_engine.py
backend/capability_system/capabilities/project_graph/lifecycle.py
backend/capability_system/tools/tool_units/project_graph_tools.py
backend/api/project_graph.py
```

修改：

```text
backend/capability_system/tools/native_tool_catalog.py
backend/runtime/tool_runtime/native_tools.py
backend/runtime/tool_runtime/tool_catalog_manifest.py
backend/capability_system/capabilities/codebase_search/runtime.py
backend/capability_system/capabilities/codebase_search/models.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/task_state_projector.py
backend/prompt_library/tool_prompts.py
backend/prompt_library/worker_prompts.py
frontend/src/components/chat/ToolTrace.tsx
frontend/src/lib/api/types.ts
```

## 15. 验证策略

不新增回归测试文件。按项目规则使用编译、真实工具 smoke、CLI 主 agent 实测和前端实际检查。

后端 smoke：

```text
project_graph_refresh mode=full roots=["backend/prompt_library"]
project_graph_search query="PromptSet 继承解析入口"
project_graph_neighbors node_ref="PromptSetResolver._visit"
project_graph_explain_path source="search_text" target="ToolTrace"
```

期望：

- 搜索返回路线图和 read windows。
- 不返回源码全文。
- stale 文件会被标注。
- read_file 后才能做最终裁决。

主 agent smoke：

```text
请定位 search_text 工具从 schema 到前端展示的完整链路，只读，给出证据。
```

期望行为：

- 先使用 `project_graph_search` 或 `codebase_search` 的 graph 层。
- 然后读取候选窗口。
- 不重复宽泛 `search_text`。
- 不把 hypothesis edge 当硬证据。

## 16. 禁止事项

- 不把图搜索做成万能搜索替代品。
- 不让模型直接写 hard fact。
- 不把 stale edge 当当前事实。
- 不把整张图注入动态尾。
- 不允许无边界 traversal。
- 不允许 agent 直接读写图数据库。
- 不允许图结果绕过 `read_file`。
