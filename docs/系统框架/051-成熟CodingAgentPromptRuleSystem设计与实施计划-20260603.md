# 成熟 Coding Agent Prompt Rule System 设计与实施计划

日期：2026-06-03

状态：首轮已实施。本文主体保留 prompt library / prompt rule system 的成熟化计划；第 12 节记录 2026-06-03 的实际落地结果和验证证据。`050-成熟CodingAgent主链路审查与升级计划-20260603.md` 是本文前置基础；本文不替代 `050`，只把成熟 coding agent 所需的一系列 prompt 规则、装配顺序、冲突检测和迁移路径补齐。

## 0. 结论

当前系统已经具备 prompt library 雏形，也已经支持 `env.coding.vibe_workspace` 这类专用 coding 环境；但还没有达到 Codex / Claude Code 这类成熟 coding agent 的 prompt 工程形态。

核心问题不是“缺几句 prompt”，而是 prompt 规则还没有成为可审计、可组合、可冲突检测、可按环境隔离、可按 cache 边界稳定装配的一等系统结构。

目标是建立一条稳定计划链：

```text
PromptRule Source
-> PromptRule Registry
-> PromptRule Compiler
-> Conflict / Scope / Cache Linter
-> Runtime Prompt Assembly
-> RuntimePromptManifest Coverage
-> RuntimeCompiler Model Messages
-> ModelResponseProtocol / ActionPermit / ExecutionLoop
```

其中：

- 能由环境 prompt 解决的行为边界，优先做成环境绑定规则。
- 不能只靠 prompt 保证的硬权力，交给 controller / compiler / permit / schema 校验。
- 文件管理是通用能力，不写进 vibe coding 专属循环。
- vibe coding 专属规则只绑定 coding 环境，不能逸散到 writing / general 任务。
- 图是固定入口，不参与调度重构；图节点只需要自己的 prompt protocol 和合同边界，不改图调度语义。

## 1. Technical Source Report

### 1.1 本项目源码证据

已经存在的 prompt library 基础：

```text
backend/prompt_library/models.py
backend/prompt_library/assembly.py
backend/prompt_library/packs.py
backend/prompt_library/manifest.py
backend/prompt_library/registry.py
```

当前模型：

- `PromptResource` 已包含 `category`、`subtype`、`owner_layer`、`allowed_invocation_kinds`、`allowed_agent_refs`、`allowed_environment_refs`、`cache_scope`、`authority` 等字段。
- `PromptPack` 已支持 `ordered_prompt_refs` 和 `cache_scope`。
- `PromptAssemblyService` 已能根据 invocation、agent、environment 过滤 refs，并输出 `PromptAssemblyResult`。
- `RuntimePromptManifest` 已能记录 stable refs、contract refs、dynamic refs、volatile refs 和 cache boundary。

当前 runtime compiler 已消费 prompt assembly：

```text
backend/harness/runtime/compiler.py
```

主要装配形态：

- runtime prompt pack
- environment prompt refs
- agent prompt refs
- task / graph prompt contract
- dynamic runtime projection
- volatile current state

当前环境 prompt 来源：

```text
backend/task_system/environments/prompt_resources.py
backend/task_system/environments/default_environments.py
backend/task_system/environments/spec_resolver.py
```

已有环境：

- `env.coding.vibe_workspace`
- `env.development.sandbox`
- `env.creation.writing`
- `env.general.workspace`

当前 agent profile 中仍嵌有长 prompt：

```text
backend/agent_system/profiles/runtime_profile_registry.py
```

其中 `main_interactive_agent.metadata.work_role_prompt_by_invocation` 已经包含较成熟的 coding 行为要求，但它仍是 profile metadata 内的长字符串，不是可 lint、可冲突检测、可覆盖统计的一等 rule。

当前内置 runtime prompt pack：

```text
backend/prompt_library/packs.py
```

只有 4 个主要 protocol prompt：

- `runtime.single_agent_turn.v1`
- `runtime.task_execution.v1`
- `runtime.graph_node_execution.v1`
- `runtime.observation_followup.v1`

当前存储侧 prompt resources：

```text
storage/prompt_library/prompt_resources.json
```

存储侧目前主要是 `graph_node.role` 类型资源，不是成熟 coding agent rule library。

### 1.2 Codex 本地源码参考

本地源码位置：

```text
D:\AI应用\openai-codex
```

重点参考：

```text
D:\AI应用\openai-codex\codex-rs\core\gpt_5_2_prompt.md
D:\AI应用\openai-codex\codex-rs\core\prompt_with_apply_patch_instructions.md
D:\AI应用\openai-codex\codex-rs\core\src\context_manager\history.rs
D:\AI应用\openai-codex\codex-rs\core\src\context_manager\normalize.rs
D:\AI应用\openai-codex\codex-rs\core\src\tools\registry.rs
D:\AI应用\openai-codex\codex-rs\core\src\tools\router.rs
D:\AI应用\openai-codex\codex-rs\core\src\tools\handlers\shell.rs
D:\AI应用\openai-codex\codex-rs\core\src\tools\handlers\unified_exec\exec_command.rs
```

可借鉴不变量：

- 模型前有统一 context 规范化入口，历史和 tool call / tool output 配对不能靠模型自己修。
- prompt 指令不是零散建议，而是覆盖 AGENTS 层级、编辑方式、测试、权限、最终答复、失败处理、持续执行等完整工作行为。
- 工具注册、路由、pre / post tool use 事件和 approval policy 是控制层权力，不只靠 prompt。
- prompt 规则告诉 agent 怎么做；硬边界由 tool runtime 和 permission system 兜住。

### 1.3 Claude Code 本地源码参考

本地源码位置：

```text
D:\AI应用\claude-code-nb-main
```

辅助研究资料位置：

```text
D:\AI应用\Claude-Code-Source-Study-main
```

优先引用源码，研究资料只用于辅助理解。

重点参考：

```text
D:\AI应用\claude-code-nb-main\constants\prompts.ts
D:\AI应用\claude-code-nb-main\constants\systemPromptSections.ts
D:\AI应用\claude-code-nb-main\utils\systemPrompt.ts
D:\AI应用\claude-code-nb-main\context.ts
D:\AI应用\claude-code-nb-main\utils\messages.ts
D:\AI应用\claude-code-nb-main\utils\permissions\permissions.ts
D:\AI应用\claude-code-nb-main\tools\TodoWriteTool\TodoWriteTool.ts
D:\AI应用\claude-code-nb-main\tools\FileEditTool\FileEditTool.ts
D:\AI应用\claude-code-nb-main\tools\BashTool\prompt.ts
```

可借鉴不变量：

- system prompt 是分段数组，不是一个不可审计的大字符串。
- 有明确 dynamic boundary，用于区分全局稳定段、session 稳定段和每轮 volatile 段。
- effective system prompt 有优先级：override、coordinator、agent、自定义、默认、append。
- user context / system context 有 memoization，避免每轮重新生成破坏 cache。
- tool permission 和 prompt 指令是两层：prompt 告诉 agent 如何处理权限，permission pipeline 决定是否允许。
- Todo / plan / memory / context compaction 都是 model-visible 规则加控制层状态，而不是只靠自然语言记忆。

## 2. Current Prompt Authority Map

| 层 | 当前文件 | 当前职责 | 问题 |
| --- | --- | --- | --- |
| Runtime protocol | `backend/prompt_library/packs.py` | 定义 single turn / task / graph / observation 的输出协议 | 只有大块 protocol prompt，缺少细分 rule taxonomy |
| Prompt resource | `backend/prompt_library/models.py` | 保存 prompt 内容和基本适用范围 | 字段接近 rule，但没有 rule kind、conflicts、requires、enforcement mode |
| Prompt assembly | `backend/prompt_library/assembly.py` | 根据 invocation / agent / environment 过滤并拼装 prompt | 只能过滤适用范围，不能检测规则冲突、覆盖缺口或 cache 错层 |
| Runtime manifest | `backend/prompt_library/manifest.py` | 记录 stable / dynamic / volatile refs | 还不能报告“本轮缺少哪些成熟 agent 规则” |
| Runtime compiler | `backend/harness/runtime/compiler.py` | 把 prompt、环境、agent、task、动态状态装配成 model messages | 装配顺序分散，rule 来源不够一等化 |
| Environment prompt | `backend/task_system/environments/prompt_resources.py` | 描述 workspace、coding、writing、general 环境 | 方向正确，但只是 orientation，不是带约束元数据的 rule pack |
| Agent profile prompt | `backend/agent_system/profiles/runtime_profile_registry.py` | 主 agent 不同 invocation 的角色和工作方法 | 内容强，但嵌在 profile metadata，和 runtime/environment prompt 存在重复权力 |
| Graph prompt | `storage/prompt_library/prompt_resources.json`、graph contracts | 图节点角色和合同 | 图节点可用，但存储侧主要是 graph role，不是 coding rule library |

当前最重要的权力重复：

```text
runtime.task_execution.v1
agent.main_interactive_agent.task_execution.work_role.v1
environment.coding.vibe_workspace.orientation.v1
environment.resource.managed_project_workspace.orientation.v1
```

这些内容都在告诉 agent 如何编码、如何读文件、如何验证、如何处理失败。目标不是删除这些能力，而是把它们拆成明确层次：

- Runtime protocol：只定义输出协议和 action schema。
- Core runtime rules：定义通用工具、错误、输出、验证、上下文规则。
- File management rules：定义路径、文件状态、stale、写入证据，保持通用。
- Environment rules：定义 coding / writing / general 的环境边界和资源语义。
- Agent role rules：定义主 agent 的职责、意图反馈、何时启动任务、何时直接回答。
- Task / graph contract：定义本任务或本节点的具体目标、输入、输出和完成标准。
- Dynamic projection：本轮可用工具、权限、状态、失败、产物、观察。
- Volatile state：当前用户消息、最新工具结果、当前 task state。

## 3. Mature Reference Principles

### 3.1 Prompt 是规则系统，不是文案库

成熟 coding agent 的 prompt 不是几段“建议”。它应覆盖：

- 身份与职责。
- 工具使用边界。
- 文件读取、编辑、写入、stale 处理。
- 命令执行与 shell 语义。
- 测试、构建、浏览器验证。
- 失败恢复。
- git 安全。
- 上下文压缩和记忆。
- 用户意图反馈。
- 输出准确性。
- 权限拒绝后的行为。
- 子 agent / skill / tool discovery 的使用边界。

### 3.2 Prompt 只负责可被模型执行的行为，硬边界由控制层执行

prompt 可以要求：

- 不要重复同一失败动作。
- 修改前先读文件。
- 测试失败时如实报告。
- coding 环境中优先使用文件工具和验证工具。

prompt 不能单独保证：

- 禁止越权写入。
- 工具是否真的可见。
- action JSON 是否合法。
- tool call / tool result 是否配对。
- graph pack 是否被错误混入 task pack。
- volatile 内容是否进入 global cache 段。

这些必须由 compiler、schema、ActionPermit、tool control plane、protocol sanitizer、manifest linter 处理。

### 3.3 Cache 边界是架构边界

成熟系统不会把每轮变化的内容放进稳定 prompt 段。目标 cache tier：

| cache_tier | 内容 | 示例 |
| --- | --- | --- |
| `global_static` | 跨会话稳定规则 | runtime protocol、通用工具规则 |
| `static_environment` | 环境稳定规则 | coding workspace、writing workspace |
| `session_stable` | 会话稳定上下文 | agent role、用户配置、项目 instruction 摘要 |
| `task_stable` | 任务稳定合同 | task contract、graph node contract |
| `dynamic_projection` | 本轮动态可见状态 | 可用工具、权限、文件状态投影 |
| `volatile` | 当前请求和最新观察 | 当前 user message、latest tool results |

## 4. Target Prompt Rule System

### 4.1 新增一等 PromptRule 语义

可以通过新增 `PromptRule` dataclass，或先在 `PromptResource.metadata` 中承载 rule 字段再逐步收敛。为了后续可拓展性，推荐新增一等模型，底层仍复用 `PromptResource` 内容存储。

目标字段：

```text
rule_id
prompt_ref
rule_kind
owner_layer
applies_to
allowed_invocation_kinds
allowed_environment_refs
allowed_agent_refs
cache_tier
authority
enforcement_mode
conflicts_with
requires
supersedes
lint_tags
version
status
```

字段含义：

- `rule_kind`：协议、工具、文件、编辑、验证、恢复、git、安全、memory、intent、output、environment、agent role、task contract、graph contract。
- `owner_layer`：runtime、tool_runtime、file_management、environment、agent、task、graph_node。
- `applies_to`：可应用对象，例如 `coding_agent`、`task_execution`、`graph_node`、`writing_agent`。
- `enforcement_mode`：`prompt_only`、`compiler_validated`、`controller_enforced`、`permit_enforced`。
- `conflicts_with`：同一 assembly 中不能同时出现的 rule。
- `requires`：存在该 rule 时必须同时出现的 rule。
- `cache_tier`：禁止 volatile 规则进入 static 段。

### 4.2 新增 PromptRuleCompiler

目标职责：

```text
PromptAssemblyRequest
-> select protocol pack
-> collect rule refs from runtime / profile / environment / task / graph
-> expand rule packs
-> validate scope
-> validate conflicts
-> validate cache tier
-> validate required coverage
-> emit PromptRuleAssemblyResult
```

`PromptRuleCompiler` 不直接执行任务，也不决定用户意图。它只负责把已经被 runtime assembly 选择的 agent、environment、invocation、task contract 转换成 model-visible prompt 规则，并拒绝非法组合。

### 4.3 固定装配顺序

目标 model-visible 顺序：

```text
1. Runtime protocol
2. Core agent rules
3. Tool / file / editing / verification rules
4. Environment / resource rules
5. Agent role rules
6. Task / graph contract rules
7. Dynamic runtime facts
8. Volatile current state
```

重要约束：

- 权力优先级由 metadata 和 compiler 校验决定，不靠文本先后顺序猜。
- 文本顺序服务于 cache 和可读性。
- task / graph contract 可以更具体，但不能覆盖 runtime protocol、permission、file boundary。
- environment rule 可以限制资源语义，不能决定是否启动任务生命周期。
- agent role rule 可以判断意图和行动方式，不能绕过 ActionPermit。

### 4.4 成熟 Coding Agent Rule Pack

推荐新增以下 rule resources：

```text
runtime.rule.tool_use.v1
runtime.rule.file_management.generic.v1
runtime.rule.context_memory.v1
runtime.rule.intent_feedback.v1
runtime.rule.error_recovery.v1
runtime.rule.output_boundary.v1
runtime.rule.permission_denial.v1
runtime.rule.subagent_delegation.v1

coding.rule.codebase_inspection.v1
coding.rule.editing.v1
coding.rule.verification.v1
coding.rule.git_safety.v1
coding.rule.windows_shell.v1
coding.rule.task_progress.v1

environment.rule.coding_workspace.v1
environment.rule.development_sandbox.v1
environment.rule.writing_workspace.v1
environment.rule.general_workspace.v1

graph.rule.node_boundary.v1
graph.rule.node_output_contract.v1
```

其中 `runtime.rule.file_management.generic.v1` 必须保持通用，只描述：

- 文件事实来自工具观察。
- 读窗口、stale、写入事件、路径权限、git view、artifact evidence。
- 用户已有改动不能被回滚或覆盖。
- 文件管理不拥有 coding / writing / graph 的循环控制。

coding 专属规则放在 `coding.rule.*` 或 `environment.rule.coding_workspace.v1`，并通过 `allowed_environment_refs=("env.coding.vibe_workspace", "env.development.sandbox")` 限定。

writing 规则放在 writing 环境，不引用 coding 编辑、测试、shell、git 规则。

## 5. Rule Taxonomy

| rule_kind | owner_layer | 适用范围 | enforcement_mode |
| --- | --- | --- | --- |
| `runtime.protocol` | runtime | 每个 invocation 必须恰好一个 | `compiler_validated` |
| `runtime.tool_use` | runtime / tool_runtime | 工具调用行为 | `prompt_only` + `permit_enforced` |
| `runtime.output_boundary` | runtime | 最终答复、JSON schema、不可泄露内容 | `compiler_validated` |
| `runtime.error_recovery` | runtime | 工具失败、协议失败、blocked | `prompt_only` + `controller_enforced` |
| `runtime.context_memory` | runtime / memory | summary、refs、memory freshness、context compaction | `compiler_validated` |
| `file_management.generic` | file_management | 文件事实、stale、路径、写入证据 | `controller_enforced` |
| `coding.inspection` | environment / agent | 搜索、读取、调用链定位 | `prompt_only` |
| `coding.editing` | environment / agent | edit_file / write_file 使用边界 | `prompt_only` + `permit_enforced` |
| `coding.verification` | environment / agent | 测试、构建、浏览器/API 验证 | `prompt_only` |
| `coding.git_safety` | environment / agent | commit、push、reset、dirty tree | `permit_enforced` |
| `coding.windows_shell` | environment / agent | PowerShell / Windows 命令语义 | `prompt_only` |
| `environment.boundary` | environment | coding / writing / general 资源边界 | `compiler_validated` |
| `agent.role` | agent | 主 agent / task agent / observation followup 职责 | `compiler_validated` |
| `task.contract` | task | 当前任务目标、交付物、验收 | `compiler_validated` |
| `graph.contract` | graph_node | 固定图节点职责和输出 | `compiler_validated` |

## 6. Migration / Cutover Rules

### 6.1 迁移原则

- 不保留旧主链路兼容壳。
- 不把 profile metadata 长 prompt 和新 rule resource 长期并存。
- 不让 environment prompt 变成 task controller。
- 不把 vibe coding 规则挂到通用 file management。
- 不改图调度入口。
- 不用测试绕过真实行为。

### 6.2 阶段一：建立 rule 模型与 linter，不改 runtime 行为

目标：

- 新增 rule 元数据结构。
- 能从现有 `PromptResource` 生成 `PromptRule` 视图。
- 能输出 rule coverage report。
- 能发现重复 protocol、scope mismatch、cache tier 错误、prompt 风格错误。

完成标准：

- 现有 prompt assembly 结果不变。
- 新增 linter 测试能发现人工构造的冲突。
- `runtime.task_execution.v1` 与 `runtime.graph_node_execution.v1` 同属 `task_execution` invocation 的风险被报告出来。

### 6.3 阶段二：拆分 runtime packs

目标：

- 将 `packs.py` 中的大块 runtime prompt 拆成 protocol + rule refs。
- 每个 invocation pack 恰好包含一个 `runtime.protocol`。
- graph node pack 仍由图节点固定入口显式选择，不参与调度重构。

完成标准：

- `runtime.pack.task_execution.v1` 不会同时包含 graph protocol。
- `runtime.pack.graph_node_execution.v1` 只能在 graph node path 显式装配。
- prompt manifest 记录 protocol refs 和 rule refs。

### 6.4 阶段三：迁移 agent profile 长 prompt

目标：

- 将 `runtime_profile_registry.py` 中 `work_role_prompt_by_invocation` 的正文迁移为 prompt resources。
- profile 只保留 refs、权限、可用 operations、lifecycle 和 metadata。
- 删除旧 metadata 长 prompt 生成路径，避免双权力。

完成标准：

- registry 不再需要从 profile 长字符串同步 work_role prompt。
- agent prompt refs 可被 linter 覆盖。
- `main_interactive_agent` 三类 invocation 的角色 prompt 都有稳定 refs。

### 6.5 阶段四：绑定环境 rule packs

目标：

- `env.coding.vibe_workspace` 绑定 coding rule pack。
- `env.development.sandbox` 绑定 development rule pack。
- `env.creation.writing` 绑定 writing rule pack。
- `env.general.workspace` 绑定 general rule pack。
- file profile prompt refs 继续作为通用资源规则。

完成标准：

- coding 规则不进入 writing / general assembly。
- writing 规则不进入 coding assembly。
- file management generic rule 可以被多环境共享。

### 6.6 阶段五：RuntimeCompiler 消费 PromptRuleAssemblyResult

目标：

- `compiler.py` 不再临时拼多种 prompt 字符串。
- 每个 model message segment 都能追踪 rule refs、cache tier、owner layer。
- dynamic projection 与 volatile state 必须在 stable sections 之后。

完成标准：

- prompt manifest 中可以看到完整规则覆盖。
- cache boundary 错误会 fail closed。
- rejected refs 不被静默吞掉。

### 6.7 阶段六：删除旧残留与保护测试

目标：

- 删除被替代的长 prompt sync 旧链路。
- 删除保护旧链路的测试。
- 新测试保护目标行为，不保护内部旧形状。

完成标准：

- 没有 profile metadata 长 prompt 到 runtime prompt 的隐式同步。
- 没有重复 runtime protocol。
- 没有 coding prompt leakage。
- 文档、测试、manifest 三者一致。

## 7. File-Level Execution Checklist

### 7.1 Prompt library

```text
backend/prompt_library/models.py
```

- 新增 `PromptRule`、`PromptRuleAssemblyResult`。
- 增加 rule kind、cache tier、conflict、requires、enforcement mode 字段。
- 保持 `PromptResource` 作为内容载体，不让规则内容分散到多个存储格式。

```text
backend/prompt_library/rules.py
```

- 新增内置 mature coding agent rules。
- 将规则内容写成 agent 可执行语言，而不是开发说明。
- 区分 runtime 通用规则、coding 专属规则、writing 专属规则、graph 节点规则。

```text
backend/prompt_library/packs.py
```

- 将 runtime protocol 和 behavior rules 拆分。
- 每个 pack 明确 protocol rule 和 ordered rule refs。
- 补上 graph node pack 的显式选择限制。

```text
backend/prompt_library/assembly.py
```

- 新增 `PromptRuleCompiler` 或 `assemble_rules()`。
- 增加 conflict、scope、requires、cache tier 检查。
- rejected refs 必须带 reason，不允许静默降级。

```text
backend/prompt_library/manifest.py
```

- 扩展 manifest，记录 rule refs、rule kinds、owner layers、coverage、conflict diagnostics。

```text
backend/prompt_library/registry.py
```

- 注册 builtin rules。
- 停止从 profile metadata 长字符串隐式制造主 agent prompt，迁移完成后删除该旧同步路径。

### 7.2 Runtime compiler

```text
backend/harness/runtime/compiler.py
```

- 接入 `PromptRuleAssemblyResult`。
- 固定 8 段装配顺序。
- 保证 stable、dynamic、volatile 边界不可混乱。
- graph node path 保持固定入口，只调整 prompt pack 选择和校验。

### 7.3 Environment system

```text
backend/task_system/environments/prompt_resources.py
backend/task_system/environments/default_environments.py
backend/task_system/environments/spec_resolver.py
```

- 保留环境 orientation，但逐步转成环境 rule refs。
- `env.coding.vibe_workspace` 绑定 coding rule pack。
- `env.creation.writing` 不绑定 coding tool / shell / git 规则。
- file profile prompt refs 继续通用化。

### 7.4 Agent profile

```text
backend/agent_system/profiles/runtime_profile_registry.py
```

- profile 保留 agent id、operations、permission、memory、lifecycle。
- 移除 `work_role_prompt_by_invocation` 长 prompt 正文。
- 改为 `agent_prompt_refs_by_invocation` 一等引用。

### 7.5 Tests

建议新增或改造：

```text
backend/tests/prompt_rule_model_regression.py
backend/tests/prompt_rule_compiler_regression.py
backend/tests/prompt_rule_cache_boundary_regression.py
backend/tests/prompt_rule_conflict_regression.py
backend/tests/prompt_rule_environment_isolation_regression.py
backend/tests/prompt_rule_profile_migration_regression.py
backend/tests/prompt_rule_graph_protocol_regression.py
backend/tests/prompt_rule_manifest_coverage_regression.py
```

测试保护真实行为：

- 不允许降低断言。
- 不允许 mock 掉 core compiler。
- 不允许通过删除失败用例制造通过。
- 旧链路迁移后，旧测试应删除或改为验证新行为。

## 8. Validation Matrix

| 场景 | 预期 |
| --- | --- |
| single agent turn | 只有 `runtime.single_agent_turn` protocol，含 intent feedback、tool use、output boundary 规则 |
| task execution coding | 含 coding inspection、editing、verification、git safety、Windows shell、generic file management |
| task execution writing | 不含 coding editing、shell、git、test 规则 |
| graph node execution | 只含 graph node protocol 和 graph contract，不启动 task lifecycle，不改图调度 |
| observation followup | 只允许只读观察后续、request task run、ask user、block，不混入 task execution editing rules |
| cache boundary | global static 不含当前用户消息、最新 tool result、动态权限 |
| prompt style lint | 发现“这是 runtime 节点”这类开发说明式 prompt |
| conflict lint | 同一 assembly 中两个 runtime protocol fail closed |
| requires lint | coding editing rule 缺 file management rule 时 fail closed |
| environment isolation | `env.creation.writing` 无 coding rule refs |
| profile migration | profile 不再包含长 prompt 正文 |
| manifest coverage | 每轮 manifest 可报告 rule refs、owner layer、cache tier |

## 9. Omissions and Conflicts Self-Check

### 9.1 已覆盖项

- 覆盖 `050` 主链路之后的 prompt 规则成熟化，不和 `050` 抢主链路改造范围。
- 覆盖 Codex / Claude Code 成熟参考中的 prompt 分层、cache 边界、权限分离、工具结果规范化、上下文处理。
- 覆盖 prompt library、runtime compiler、environment system、agent profile、tests 的文件级落点。
- 覆盖用户强调的“成熟 coding 软件应有一系列 prompts 规则”。
- 覆盖系统 prompts、纠错机制、记忆系统、用户意图反馈、上下文处理、任务细节处理。
- 覆盖“环境 prompts 能解决的先用环境 prompts，不能解决的由控制器切换”。
- 覆盖“vibe coding 专属不要逸散，文件管理通用”。
- 覆盖“图不参与调度，固定入口”。
- 覆盖“不要硬编码到一套任务系统循环控制”。

### 9.2 已发现冲突与处理

冲突一：`runtime.task_execution.v1` 与 `runtime.graph_node_execution.v1` 都允许 `task_execution` invocation。

处理：

- 不立刻改图调度。
- 在 rule compiler 中要求每个 runtime packet 恰好一个 protocol。
- graph node path 必须显式选择 graph node pack。
- 普通 task execution 默认 pack 不能含 graph protocol。

冲突二：agent profile 长 prompt 和 environment prompt 都写了 coding 行为。

处理：

- profile 只保留 agent role refs。
- coding 行为拆到 coding rule pack。
- file 状态行为拆到 generic file management rule。
- environment rule 只负责环境资源和边界。

冲突三：文件管理既要通用，又要支持 vibe coding 流畅度。

处理：

- 文件事实、stale、路径、证据是通用 file management rule。
- “如何编码、如何测试、如何处理 git”是 coding rule。
- coding 环境可以引用通用 file rule，但 file rule 不引用 coding loop。

冲突四：prompt 规则可能被误当成硬权限。

处理：

- 每条 rule 必须标 `enforcement_mode`。
- 安全、写入、git、shell、network 由 ActionPermit / tool control plane / controller enforcement 兜住。
- prompt 只描述 agent 应如何选择，不替代 permit。

冲突五：cache 优化与环境特定规则可能冲突。

处理：

- global static 只放跨环境通用规则。
- environment rule 走 `static_environment`。
- task contract 走 `task_stable`。
- 当前用户消息和最新观察只进 volatile。

### 9.3 仍需实施时确认的边界

这些不是本文遗漏，而是实施时需要按源码结果最终落定的技术选择：

- `PromptRule` 是独立 dataclass，还是先作为 `PromptResource.metadata.rule` 视图落地。
- graph node 是否新增 `graph_node_execution` invocation_kind，或继续使用 `task_execution + explicit graph pack`。
- agent profile 长 prompt 删除时，是否需要一次性更新所有由 `registry.py` 自动生成的 work role refs。
- prompt linter 是纯 Python 测试工具，还是作为 registry API 的 diagnostics 暴露给前端。

推荐默认选择：

- 先新增 `PromptRule` dataclass，但不创建第二套内容存储。
- graph 暂不改 invocation_kind，只加 explicit protocol pack 校验。
- profile 长 prompt 迁移后一次性删除旧同步路径。
- linter 先做测试和 diagnostics，前端展示不是第一阶段目标。

## 10. Execution Chain

```text
阶段一：PromptRule 模型 + linter
-> 阶段二：runtime protocol / rule pack 拆分
-> 阶段三：agent profile 长 prompt 迁移
-> 阶段四：environment rule pack 绑定
-> 阶段五：RuntimeCompiler 接入 rule assembly
-> 阶段六：删除旧链路和补齐 regression tests
```

实施时每阶段必须满足：

- 有明确输入、输出、文件清单。
- 有冲突检测。
- 有回归测试。
- 有旧链路删除条件。
- 不用兼容兜底把旧路径继续留在主路径。

## 11. Final Target

完成后，系统应该具备成熟 coding agent 的 prompt rule 形态：

- 每轮 runtime manifest 能说明本轮使用了哪些 protocol、rule、environment、agent、task contract。
- 每条 rule 有 owner、scope、cache tier、enforcement mode。
- coding prompt 规则不会污染 writing / general。
- file management 成为通用事实和证据系统。
- vibe coding 通过环境和 rule pack 获得专属流畅度，不需要硬编码进统一 task loop。
- graph 固定入口保持不变，但 graph node prompt protocol 不再和普通 task execution 混淆。
- prompt 文本写给 agent 执行，不写给开发者阅读。
- prompt 解决可模型执行的行为；硬边界由 controller / permit / schema 解决。

## 12. Implementation Result

2026-06-03 首轮实施已完成：

- 新增 `PromptRule`、`PromptRuleAssemblyResult` 和 `PromptRuleCompiler`。
- 新增内置 runtime / coding / environment / graph rule resources。
- runtime pack 已由单一大 prompt 拆成 protocol + ordered rule refs。
- `main_interactive_agent` 的长 work role prompt 已迁移到 prompt library 资源，profile metadata 只保留 `agent_prompt_refs_by_invocation`。
- 删除 profile metadata 长 prompt 到 prompt resource 的旧同步路径，custom profile 不再自动合成 `agent.<profile>.work_role.v1`。
- file management rule 已成为通用环境资源规则，不绑定 vibe coding 循环。
- `env.coding.vibe_workspace` 与 `env.development.sandbox` 共享 coding 行为规则，但使用各自独立的 environment boundary rule。
- writing / general 环境只绑定各自 boundary rule，不继承 coding 编辑、测试、shell 或 git 规则。
- runtime manifest 已记录 `prompt_rules` 覆盖、rule kinds、owner layers、cache tiers、enforcement modes 和 rejected diagnostics。
- compiler 已对 rejected prompt rules fail closed，并在 merged prompt assembly 中重新计算 rule diagnostics。

已运行验证：

```text
pytest backend/tests/prompt_library_registry_regression.py backend/tests/prompt_rule_system_regression.py backend/tests/task_environment_registry_regression.py backend/tests/coding_environment_capability_isolation_regression.py backend/tests/task_environment_file_profile_isolation_regression.py backend/tests/task_environment_runtime_boundary_regression.py -q
pytest backend/tests/dynamic_prompt_context_projection_test.py backend/tests/graph_node_prompt_budget_regression.py backend/tests/prompt_cache_prefix_tier_regression.py -q
pytest backend/tests/harness_runtime_facade_regression.py backend/tests/graph_task_runtime_facade_regression.py -q
python -m compileall backend\prompt_library backend\harness\runtime backend\task_system\environments backend\agent_system\profiles
```

## 13. Implementation Result：系统调用 Prompt Rule

2026-06-03 第二轮实施补齐 prompts 的系统调用体系：

- 新增 `runtime.rule.system_call_protocol.v1`，把模型可表达的系统调用统一限定为本轮 `allowed_action_types`、JSON action schema 或 provider-native action。
- runtime protocol rule 现在显式 `requires=("runtime.rule.system_call_protocol.v1",)`；只拼 protocol、不拼系统调用规则的装配会被 `PromptRuleCompiler` 拒绝。
- `runtime.pack.single_agent_turn.v1`、`runtime.pack.task_execution.v1`、`runtime.pack.graph_node_execution.v1`、`runtime.pack.observation_followup.v1` 都显式引用系统调用规则。
- graph node pack 只新增系统调用协议规则，没有引入通用 `runtime.rule.tool_use.v1`，因此不改变图固定入口和调度语义。
- manifest coverage 新增 `has_system_call_protocol`，每轮 packet 可以审计是否真的装配了系统调用协议。
- 硬边界仍由 `ModelResponseProtocol`、`model_action_request_from_payload`、`admit_model_action`、`ActionPermit` 和 `RuntimeToolControlPlane` 执行；prompt 只负责让 agent 正确表达动作，不替代权限和工具准入。

## 14. Implementation Result：用户意图反馈 Prompt Rule

2026-06-03 第三轮实施补齐用户意图反馈规则：

- 新增 `runtime.rule.intent_feedback.v1`，要求 agent 先判断用户当前话语的真实目标，再选择回答、询问、请求任务、控制当前工作、调用工具或阻止。
- `single_agent_turn`、`task_execution`、`tool_observation_followup` 三类非图 runtime protocol 现在显式要求 `runtime.rule.intent_feedback.v1`。
- graph node protocol 不要求也不引用该规则，避免图节点获得重判用户意图或改变图调度的权力。
- manifest coverage 新增 `has_intent_feedback`，packet 可审计当前轮是否具备意图反馈规则。
- 规则文本明确旧任务记录、todo、历史摘要、工具建议、active work context 只能作为判断材料，不能劫持当前用户意图。

## 15. Implementation Result：Cache Boundary Rule Lint

2026-06-03 第四轮实施补齐 prompt rule cache 边界校验：

- `PromptRuleCompiler` 现在校验 `PromptRule.cache_tier` 与实际 `PromptSection.cache_scope` 是否匹配，错层装配会 fail closed。
- runtime/global static、environment/static_environment、agent/session_stable、task/task_stable、volatile 各自有明确边界，不再只记录在 manifest 中。
- `agent.main_interactive_agent.*.work_role.v1` 的 cache scope / cache tier 已调整为 `session_stable`，避免 agent role 被误记为全局静态规则。
- 新增错层回归测试，构造 `static_environment` 规则塞入 `static` runtime section 时必须被 compiler 拒绝。

## 16. Implementation Result：Scope / Style Rule Lint

2026-06-03 第五轮实施补齐 prompt rule 适用范围和 prompt 写法校验：

- `PromptRuleCompiler` 现在二次校验 rule 的 `allowed_invocation_kinds`，即使绕过 registry 直接提交 section，也不能把单轮规则塞进任务执行或其它 invocation。
- compiler 校验 rule owner layer 与 section category / owner layer 是否匹配，防止 environment、agent、graph 规则被放到错误层。
- 开发说明式 prompt 文本从 warning 升级为 fail-closed；包含“这是 runtime 节点”“根据任务图执行”“这个节点用于”等写法会被拒绝。
- 目标是保证 prompt 文本写给 agent 直接执行，而不是把内部节点说明暴露给 agent。
