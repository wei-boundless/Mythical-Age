# 项目图语义模型设计方案

状态：设计稿，待审阅后实施  
日期：2026-07-01

## 1. 核心裁决

项目图不是硬事实权威。它是 Deep AST 上方的语义控制网络：

```text
Deep AST Spine = 结构骨架
Semantic File Module = 基本读取单位
Semantic Control Graph = 控制神经系统
Class / Function / Parameter / Call Site = 控制末梢
```

agent 的默认进入路径：

```text
Functional System
-> Semantic File Module
-> Module Outline
-> Endpoint Bundle
-> Required Read Windows
-> read_file exact evidence
```

## 2. Semantic File Module

读取的基本单位必须是有语义的单文件模块，而不是裸文件、散乱行窗口或孤立函数。

```text
Semantic File Module =
  一个源码文件
  + 所属功能系统
  + 文件职责
  + public/internal symbols
  + imports / downstream edges
  + class/function/parameter/call-site endpoints
  + module-level read profile
  + required exact evidence windows
```

硬规则：

- 一个 `Semantic File Module` 只能代表一个真实源码文件。
- 模块摘要可以由模型辅助，但 public symbols、endpoint refs、line ranges、hash 必须来自 AST/registry hard facts。
- agent 进入编辑前必须先确认相关模块，再读取 required windows。
- 大文件不能强迫 agent 读全文；模块 read profile 决定先给 outline、public surface 和 required windows。

模块 envelope：

```text
module_ref
path
owned_by_systems
functional_role
file_kind
module_summary
imports_summary
public_surface
internal_endpoint_summary
upstream/downstream edges
required_read_windows
optional_read_windows
freshness/confidence/limitations
next_actions
```

## 3. 语义系统层

系统层是 agent 的入口视图，但不是结构权威。

```text
Project
-> Functional System
-> Subsystem / Domain
-> Responsibility
-> Owned Folders
-> Semantic File Modules
-> Runtime Relations
```

系统边界来源按权威排序：

1. 显式项目配置 / graph template / architecture manifest。
2. 目录命名、包结构、router、registry、tool catalog、prompt registry。
3. AST 和 import/call/reference hard facts。
4. git history / README / design docs 辅助信号。
5. 模型从 bounded evidence pack 中给出的 semantic annotation。

模型可以帮助命名系统、归纳职责、提出 ownership 候选，但不能单独决定系统边界。

## 4. Endpoint 与 Route

`control_endpoints` 保存可被 agent 控制的末梢：

```text
endpoint_kind:
  class | function | parameter | call_site | attribute | route | tool | prompt_slot

anchor_ref:
  ast_node_id / function_ref / parameter_ref / call_site_ref / registry_ref

module_ref:
  末梢所属 Semantic File Module
```

`control_routes` 保存从系统/模块/用户意图到末梢的控制路径：

```text
route_kind:
  locate | inspect | impact | edit_scope | verify_scope
```

控制规则：

- route 不能只停在系统节点，必须至少落到一个 endpoint。
- edit_scope 必须包含 required read windows。
- verify_scope 必须包含 endpoint、changed paths、命令或 API/route/prompt/tool 关系。
- 如果路径无法落到模块和 AST 末梢，只能作为 architecture note，不能作为可执行控制计划。

## 5. Control Session

日常 agent 使用 `project_graph` 启动 control session：

```text
started
-> routed
-> module_selected
-> awaiting_read
-> read_confirmed
-> edit_scoped
-> verifying
-> completed
```

输出 `ControlResultEnvelope`：

```text
summary
control_session
semantic_file_modules
selected_routes
endpoint_bundle
required_read_windows
evidence_requirements
scope
freshness / limitations
next_actions
```

`next_actions` 是核心交互字段。它告诉 agent 下一步应该 read_file、expand endpoint、提交 evidence_ack、进入 edit_scope、刷新 changed paths、退回 search_text/read_file，还是提交 correction proposal。

## 6. Evidence Receipt

`read_file` 对图候选窗口的确认结果必须形成 evidence receipt：

```text
receipt_id
session_id
module_ref
candidate_ref
path
start_line
line_count
content_hash
read_observation_ref
coverage_kind: confirms | updates | contradicts | insufficient
```

没有 evidence receipt 的候选只能用于定位，不能支撑修改裁决。

## 7. 工具与 API

agent-visible 工具：

```text
project_graph:
  action=start|continue|overview|search|expand|trace|read_windows|evidence_ack|impact_scope|edit_scope|verify_scope|correction|status

project_graph_refresh:
  mode=incremental|full

project_graph_build:
  action=plan|start|status|review|publish|cancel
```

后端 API：

```text
GET  /api/project-graph/status
POST /api/project-graph/control/start
POST /api/project-graph/control/continue
POST /api/project-graph/evidence/ack
POST /api/project-graph/scope/impact
POST /api/project-graph/scope/edit
POST /api/project-graph/scope/verify
POST /api/project-graph/correction
POST /api/project-graph/refresh
```

## 8. 前端展示

前端不展示全图，只展示当前 control session：

```text
Control mode / state
Selected route
Semantic File Modules
Endpoint bundle
Required read windows
Evidence receipts / read coverage
Impact scope / edit scope / verify scope
Freshness / confidence / limitations
Next actions
```

locator-only 不能显示成已确认事实。exact-read-confirmed 必须单独标识。

