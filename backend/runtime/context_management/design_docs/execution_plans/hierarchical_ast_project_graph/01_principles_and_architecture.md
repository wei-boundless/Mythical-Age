# 原则、原理与总体架构设计

状态：设计稿，待审阅后实施  
日期：2026-07-01

## 1. 要解决的问题

现有常态搜索链路：

```text
search_text / rg-like locator
-> recommended_read_window
-> read_file exact evidence
-> answer / edit / refine
```

这条路径适合高频定位，但不能长期承担跨模块关系、影响面、架构审查和项目管理。核心缺口不是搜索算法不够复杂，而是缺少一个可持久化、可审查、可增量维护的项目语义空间。

正确目标：

- agent 不需要每回合靠宽泛搜索重新推断项目结构。
- 稳定代码事实不进入记忆反复污染上下文。
- 系统提供可查询的项目语义网络，但最终事实仍由 AST hard facts 和 `read_file` 裁决。
- agent 与系统交互的基本读取单位是有语义的单文件模块。

## 2. 成熟 Agent 对齐原则

参考 Codex / Claude Code / Aider Repo Map 以及 Glean、Kythe、SCIP、LSP/LSIF、CodeQL、Joern 的共同原则：

- 硬事实来自解析器、索引器、语言服务或确定性注册表。
- 模型可以辅助命名、归纳和解释，但不能拥有硬事实权威。
- agent 不应读全图，而是按 query、symbol、module、route、read window 分辨率展开。
- 索引只能定位，exact read 才能作为当前代码事实。
- 当前任务状态属于 current context / dynamic control，不属于长期 memory。
- 工具面要精简，内部算法可以复杂，但 agent 可见心智必须轻。

## 3. 总体架构

```text
WorkspaceFileService
-> File Fingerprint Index
-> Deep AST Extractors
-> Symbol / Binding / Call / Dataflow Index
-> Semantic File Module Builder
-> Deterministic Domain Extractors
-> Project Semantic Space Store
-> AST Control Query Engine
-> Project Network Build Capability
-> Graph Task Review Network
-> Tool/API Adapter
-> Dynamic Context Projector
-> Frontend Control Trace
```

核心层级：

```text
project
-> functional_system
-> subsystem / domain
-> owned_folder
-> semantic_file_module
-> deep_ast_tree
-> class / function / parameter / call_site
-> required_read_window
-> read_file exact evidence
```

## 4. 关键身份裁决

```text
Deep AST Spine:
  结构骨架、硬事实来源、审查权威。

Semantic File Module:
  agent 与系统对齐的基本读取单位。一个模块只对应一个真实源码文件。

Semantic Control Graph:
  控制神经系统。负责把用户意图和 agent 任务路由到模块与 AST 末梢。

Control Endpoint:
  class / function / parameter / call_site / attribute / route / tool / prompt_slot 等可操作末梢。

Project Network Build Capability:
  图任务系统承载项目网络建立的通用能力。它负责层级计划、语义分片、work product、资源平面、汇聚、校验、generation 生命周期和状态投影。它不是审查专用系统。

Graph Task Review Network:
  利用 Project Network Build Capability、现有 TaskGraphDefinition、ExecutableGraphConfig、GraphLoop、WorkOrder 和多 coding agent 审查构建语义网络的业务实例。

Layer Summary Memory:
  保存图任务每一层汇总节点形成的阶段性共识，用于下一层分片和审查输入；它不是最终语义图事实。
```

## 5. 上下文与记忆边界

稳定代码事实：

```text
project semantic space store
```

当前 exact read：

```text
read observation artifact / current evidence scope
```

当前控制路标：

```text
dynamic context
```

图任务过程态：

```text
Proposal Memory / Layer Summary Memory
```

长期记忆：

```text
用户偏好 / 已审定设计裁决 / 跨回合不可重建工作结论
```

禁止进入动态尾：

- 全量 overview。
- 大量 node/edge 列表。
- 稳定函数签名。
- schema 文档。
- 模型 annotation 原文。
- 已可从语义空间重建的稳定代码事实。

动态尾只允许保留：

```text
control_session_id
control_state
active_semantic_file_modules
active_endpoint_refs
required_read_windows
evidence_receipt_summary
next_action_hint
freshness / limitations
```

## 6. 工具面原则

日常 agent 只需要三个高层入口：

```text
project_graph:
  日常只读控制工具。启动 control session，返回 Semantic File Module、endpoint bundle、required read windows 和 next_actions。

project_graph_refresh:
  刷新 runtime index。写 runtime storage，不写源码。

project_graph_build:
  启动或观察图任务语义构建。默认只产出 draft proposal，不自动发布。
```

底层 API 可以细分，但 agent-visible 工具不能膨胀成十几个命令。

## 7. 实施阶段总览

```text
Phase 1 Deep AST Spine MVP
Phase 2 Semantic File Module Builder
Phase 3 AST Control Command Plane
Phase 4 Coding Agent 适配
Phase 5 Graph Task Semantic Build
Phase 6 Domain Extractors
Phase 7 Lifecycle / Context Projection
Phase 8 Model Annotation / Review Agents
Phase 9 Frontend Control Trace
Phase 10 验证与清理
```

核心验收：

- 跨模块任务能从系统层进入 Semantic File Module。
- 修改前必须形成 evidence receipt。
- 图任务能分片派发给多个 coding agent。
- 任何语义 proposal 都不能绕过 AST Control Curator。
