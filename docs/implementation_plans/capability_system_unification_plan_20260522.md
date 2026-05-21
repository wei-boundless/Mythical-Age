# 能力与权限系统统一优化方案

## 1. 目标

本方案用于优化当前 Agent 项目的能力系统和权限系统，把 `tools`、`skills`、本地 MCP 单元、外部 MCP 服务、运行时权限、审批和沙箱从“多套注册表并行展示、多条权限链路并行判断”收束为一套可审计、可授权、可运行、可在前端管理的能力模型。

目标不是给旧系统再套一层壳，而是明确能力、权限、执行三类边界：

- `Tool` 是通用执行能力，负责读写文件、搜索、网络、Git、本地命令等动作。
- `Skill` 是工作方法和任务协议，负责告诉 Agent 在什么场景如何组织任务，不直接替代工具权限。
- `MCP` 是统一能力端点管理层；本地能力和外部服务只是在 provider / transport 上不同，不在管理面拆成两套系统。
- `Operation` 是权限判断的最小执行单位；所有工具、Skill 依赖、MCP tool、委派和写入都必须最终映射到 operation。
- `ResourcePolicy` 是当前 turn 的执行授权快照；它来自任务需求、Agent profile、权限模式、审批策略和沙箱策略的收敛，不由 Skill 或前端展示状态直接授予。
- `OperationGate` 是运行时唯一执行闸门；任何实际调用都必须经过它，不能被本地 MCP、旧 PermissionService、catalog 展示字段或灵魂投影绕过。

正确终态是：前端看到的是一套统一能力目录和一条清晰权限链路；运行时拿到的是按任务授权后的能力包；权限系统只按 operation、资源策略、审批状态和安全 validator 判断；文件能力默认面向项目工作区，而不是被写死在某个工具目录。

最终管理面必须同时解释三层状态：

- 全局能力上限：Agent profile / provider 配置允许什么。
- 本轮授权事实：ResourcePolicy 实际采用了哪些 operations。
- 执行闸门结果：OperationGate 对每次调用的 allow / deny / requires_approval 结果和原因。

## 2. 前置架构判断

这次改造是否是优化，不能用“模型更统一”来判断。统一只是工具，真正判断标准是：Agent 是否更可靠、更可控、更好调试，同时低风险日常能力不能变慢、变重、变啰嗦。

结论：

- 这是一次有必要的优化，但优化点不是把 tools、skills、MCP、permission 全塞进同一个大壳。
- 真正的优化点是把执行权限收敛到 `OperationGate + ResourcePolicy`，把能力展示收敛到 `CapabilityUnit` 投影，把本地/外部 MCP 收敛到统一 provider 管理面。
- 如果实施时只做统一 catalog，而不先修权限权威、审批闭环和本地 MCP 自授权，那么这次改造会劣化。

### 2.1 为什么当前需要优化

当前系统的核心风险不是能力少，而是四件事混在一起：

- 能力存在：系统注册了某个 tool / skill / MCP。
- 模型可见：这项能力是否进入当前 prompt/tool schema。
- 当前授权：本轮 `ResourcePolicy` 是否允许对应 operation。
- 实际执行：这次调用是否被 `OperationGate` 放行、拒绝或转入审批。

这些状态混在一起会导致：

- 前端看到“工具可用”，但当前 turn 实际不能执行。
- Skill 被选中，但它依赖的 operation 没有被授权。
- 本地 MCP 因为 in-process 执行而绕开统一授权语义。
- `permission_mode` 看起来可切换，但主运行时不一定按它执行。
- `requires_approval` 被记录为 gate 结果，却没有稳定恢复原调用的闭环。

因此，计划必须先修“执行权威”和“状态解释”，再修“展示统一”。

### 2.2 什么算优化

满足以下条件才算优化：

- `OperationGate + ResourcePolicy` 是唯一运行时执行权威。
- `CapabilityUnit` 只是统一投影，不替代 ToolDefinition、SkillContract、MCP provider、OperationRegistry 的源码权威。
- 低风险只读能力保持顺畅，不因为重构引入无意义审批。
- 高风险能力的拒绝、审批、沙箱原因能被前端和监控面板解释。
- Skill 只声明工作方法和 operation 依赖，不直接授予工具权限。
- 本地 MCP 和外部 MCP 同面管理，但本地 MCP 不获得默认自授权特权。
- 现有 retrieval/pdf/structured_data 任务图路径继续可用。

### 2.3 什么算劣化

出现以下情况即视为劣化，应暂停当前阶段：

- 为了统一模型，把 `CapabilityUnit` 做成新的全能注册表，反而复制所有权威源。
- `read_file`、`search_text`、`list_dir`、`glob_paths` 这类只读能力频繁要求审批。
- 权限状态变成更多标签，但用户仍不知道为什么能执行或不能执行。
- 本地 MCP 取消默认自授权后，核心任务图无法稳定调用 retrieval/pdf/structured_data。
- approve/reject 只是 UI 状态，不能恢复同一个 directive。
- `permission_mode` 语义变复杂，却不能稳定影响真实 `OperationGate`。
- 为兼容保留两套管理面、两套权限判断、两套 MCP 调用入口，导致认知负担更大。

### 2.4 固定决策

本计划采用以下固定决策：

- 先收敛权限权威，再做统一 catalog。
- 先保证低风险能力不被审批污染，再做高风险审批闭环。
- 先把本地 MCP 接入统一 ResourcePolicy/Gate，再取消默认自授权。
- 先 shadow 新字段并验证一致性，再删除旧字段。
- 前端只展示后端给出的 profile ceiling、turn adoption、gate result，不自行推断执行权限。

### 2.5 挑剔审查结论

这一轮审查的判断比较直接：当前系统不是“没有能力”，而是有不少信息设计在重复包装同一件事，却没有回答最重要的问题：当前能不能执行、为什么不能执行、失败后怎么恢复。这类信息如果继续放大，会让能力系统显得丰富，但实际降低可判断性。

需要保留并强化的部分：

- `ToolDefinition`、`OperationDescriptor`、`ResourcePolicy`、`OperationGate` 是真正有工程价值的骨架。
- `rag-skill`、`pdf-analysis`、`structured-data-analysis` 的正文大体是 Agent 可执行的任务协议，不是空泛宣传文案。
- 本地 retrieval/pdf/structured_data 作为专业能力端点是有价值的，问题是管理和授权边界不清，不是能力本身无用。
- 右侧任务监控面板方向正确，但应该服务于“当前运行、审批、失败、产物”，不能变成状态字段展览。

应该降级、删除或重做的信息噪声：

- `operation_metadata.tool_type`、`tool_boundary`、`adapter_type`、`risk_level`、`visibility_label`、`runtime_policy`、`ownership_label`、`governance_hints` 目前多数是 `catalog.py` 的展示推导，不是运行时事实。它们可以作为筛选标签，但不能作为能力详情的核心信息。
- `authorized=true/false` 这类布尔值太粗，会把 allowed、requires_approval、denied、unsupported、not_checked 混成一个状态。能力管理面不应继续以它作为主状态。
- `local_mcp_units`、`mcps`、`capability_endpoints`、`binding_graph.mcp_nodes`、`mcp_tool_pool` 多处重复描述同一批本地 MCP，属于认知噪声。迁移完成后只能保留一套 canonical MCP provider view。
- `agent_tool_bindings()` 当前等价于“主 Agent 持有所有 main_runtime 工具”，更像展示假设，不是授权事实。这个图如果不接入 profile/turn/gate，就应该从主能力管理视图降级到调试诊断。
- 前端允许编辑工具类型、治理备注、LLM 调用描述，但这些字段不改变真实 `ToolDefinition`、schema、权限或执行边界。除非明确标注为“管理备注”，否则会误导用户以为改了工具能力。
- 单独的外部 MCP 页面和能力系统端点页会把“统一 MCP 管理”拆回两层。最终前端不应再用“本地能力端点 / 外部 MCP 控制面”作为两个管理入口。

Skill 的挑剔结论：

- 现有主要 Skill 正文不是最糟糕的问题；真正的问题是运行时只注入 `prompt_block`，而 `prompt_block` 来自 `skill_scanner.py` 的硬编码摘要，不是完整 `SKILL.md` 正文。也就是说，正文写得再好，实际注入给 Agent 的可能只是压缩后的通用说明。
- `skill_scanner.py` 按 skill name 硬编码 delegation/return protocol，这让 Skill 变成“写了文件但由代码替它解释”。这是表面能力，不是可扩展能力。
- `skill-creator` 的 `preferred_route: rag` 是不严谨信号。创建/审查 Skill 不是知识检索任务，不应该借用 RAG route；它需要自己的 authoring/workflow operation 或至少显式声明只影响提示与文件编辑流程。
- `activation_policy=manual/disabled` 没有在 `SkillPolicyResolver` 中真正阻止自动选择，属于配置看似存在、行为没有兑现。
- 所有 Skill 都缺少 `requires_operations` / `requires_capabilities`，所以前端无法判断一个 Skill 是否真的可执行，只能显示“可能适用”。

代码严谨性结论：

- `OperationGate._check_operation_safety()` 在 operation 声明了 `safety_validator_ref` 但 context 没有 validator 时直接放行，这是 P0 级结构漏洞。
- `LocalCapabilityMCPExecutor` 在缺少 `ResourcePolicy` 时创建 `_default_mcp_resource_policy()` 自授权，这是本地 MCP 特权通道，和统一权限模型冲突。
- 主运行时 `OperationGatePipelineContext` 没有稳定传入当前 `permission_mode`，前端切换权限模式后不一定影响真实 gate。
- 审批 token、approval state、`waiting_approval` 状态已经有雏形，但工具执行路径仍容易把 `requires_approval` 当成普通未放行结果处理，缺少“暂停、保存同一 directive、批准后恢复”的闭环。
- `ToolRuntime.get_definition()` 和 `ToolRegistry.get_by_name()` 仍回到静态 `get_tool_definition_map()`，将来引入动态 registry 会出现“列表和查询不是同一来源”的错觉。
- 文件工具已经修过 workspace root，但 `SearchFilesTool`、`GlobPathsTool`、`ReadFileTool`、`WriteFileTool`、`TextMetricTool` 仍各有路径、编码、默认根逻辑。继续这样扩展会形成一堆相似但不完全一致的文件能力。
- `terminal` 和 `python_repl` 的字符串黑名单只能算临时防护，不是 sandbox。它们必须保持 `agent_internal`，且所有执行必须由 operation gate、approval、sandbox 共同约束。

因此，本计划的第一优先级不是“让管理页看起来统一”，而是先删除噪声权威、补红线测试、修掉伪授权和伪审批。只有这些成立后，`CapabilityUnit` 才是优化；否则它只是新壳。

## 3. 当前设计缺口

### 3.1 工具层

源码依据：

- `backend/capability_system/tool_definitions.py`
- `backend/capability_system/tool_runtime.py`
- `backend/capability_system/tool_authorization.py`
- `backend/capability_system/units/tools/*`

现状：

- 内置工具已经有 `ToolDefinition`、`operation_id`、可见性、风险标签、读写属性。
- `build_authorized_tool_set()` 已经按 `operation_id` 和 `runtime_visibility` 过滤工具。
- 文件工具现在通过 `workspace_paths.py` 统一把 `backend` 初始化目录提升到项目根。

缺口：

- 文件路径能力仍散落在多个工具实现内，应该下沉为 `WorkspaceFileService`。
- `ToolDefinition` 是注册源，但 catalog/supply 又把很多展示字段临时推导，导致前端看到的是“展示聚合”，不是稳定能力模型。
- `terminal`、`python_repl` 等高风险工具已经隐藏在 `agent_internal`，但权限预览和前端说明仍不够直观。

### 3.2 Skill 层

源码依据：

- `backend/capability_system/skill_scanner.py`
- `backend/capability_system/skill_registry.py`
- `backend/capability_system/skill_policy.py`
- `backend/capability_system/skill_contracts.py`

现状：

- Skill 通过 `SKILL.md` frontmatter 扫描成 `SkillRuntimeContract` 和 `SkillPromptContract`。
- `SkillPolicyResolver` 会用 task/source/modality/capability 结构匹配，不再只靠关键词。
- Snapshot 已经强调“管理显示”和“运行时只注入被选中的 skill”。

缺口：

- `preferred_route` 仍偏字符串化，和 operation/local MCP 的映射不是一等合同。
- Skill 的能力依赖没有显式声明为 operation requirements，导致前端很难判断某个 Skill 实际需要哪些工具/MCP/资源授权。
- Skill 质量检查现在主要依赖扫描和测试，缺少“prompt 是否写成 Agent 可执行角色说明”的系统级校验。

### 3.3 本地 MCP 层

源码依据：

- `backend/capability_system/local_mcp_registry.py`
- `backend/capability_system/mcp_registry.py`
- `backend/capability_system/mcp_adapter.py`
- `backend/capability_system/units/mcp/local/*`

现状：

- 本地 MCP 单元包括 retrieval、pdf、structured_data。
- `MCPRegistryEntry` 把本地单元映射为 `op.mcp_*`，并且明确 `model_visibility=not_direct_model_tool`。
- `validate_capability_catalog()` 已经校验 MCP 不应该直接暴露给模型。

缺口：

- `LocalMCPUnitRecord` 和 `MCPRegistryEntry` 是两套模型，字段重复但权威关系不够明确。
- 本地 MCP 实际更像“内部专业能力端点”，不是需要 spawn/连接的外部服务；但管理面不应单独拆层，应作为统一 MCP provider 的 `local` 实现呈现。
- route、operation、skill_refs、resource_kinds 之间缺少统一 lifecycle 状态，也缺少和外部 MCP 共享的 inspect / catalog / call / permission preview 接口。

### 3.4 外部 MCP 层

源码依据：

- `backend/capability_system/mcp/client/models.py`
- `backend/capability_system/mcp/client/config_store.py`
- `backend/capability_system/mcp/client/manager.py`
- `backend/capability_system/mcp/client/permission.py`
- `backend/capability_system/mcp/server/tool_pool.py`

现状：

- 外部 MCP 有独立配置存储、server inspect、tool call、permission gate。
- tool permission 会根据 MCP annotations 生成 `op.external_mcp.*`。
- `stdio` 可实际调用，`streamable_http` 可配置但 manager 返回 `transport_not_enabled_yet`。

缺口：

- 配置层允许 `streamable_http`，执行层暂不支持，前端如果只看配置会误以为可用。
- 外部 MCP tool pool 是单独入口，没有进入统一 MCP provider 生命周期，也没有和本地 MCP 使用同一套 catalog/supply 投影。
- 缺少连接快照缓存、失败诊断分级、按 server/tool 的授权预览。

### 3.5 Catalog / Supply 层

源码依据：

- `backend/capability_system/catalog.py`
- `backend/capability_system/supply.py`
- `backend/capability_system/models.py`
- `backend/capability_system/validation.py`

现状：

- `build_capability_catalog()` 已能合并 skills/tools/mcps/local_mcp_units/operations。
- `build_capability_supply_package()` 已经更接近运行时能力包。
- `validate_capability_catalog()` 已经覆盖工具 operation、MCP 可见性、endpoint 映射等基本一致性。

缺口：

- catalog 是“合并后的视图”，不是“统一能力源模型”。
- supply 仍输出 `tool_refs`、`skill_refs`、`mcp_refs` 三套引用，运行时和前端仍需理解三种分支。
- 缺少一个可持久快照的 canonical `CapabilityUnit`，导致前端能力管理只能做展示，难做启用、禁用、授权预览和健康检查。

### 3.6 权限与审批层

源码依据：

- `backend/permissions/service.py`
- `backend/permissions/decision_pipeline.py`
- `backend/permissions/policy.py`
- `backend/orchestration/resource_policy.py`
- `backend/orchestration/resource_gate.py`
- `backend/runtime/shared/model_adoption.py`
- `backend/runtime/shared/tool_adoption.py`
- `backend/runtime/shared/safety.py`
- `backend/runtime/unit_runtime/loop.py`
- `backend/capability_system/mcp/client/permission.py`
- `backend/capability_system/mcp/server/local_capability_server.py`

现状：

- 新运行时已经以 `ResourcePolicy` 和 `OperationGate` 为核心执行闸门。
- 每次模型回答入口和真实工具调用前都会经过 `OperationGate`。
- `ResourcePolicy` 已区分 `allowed_operations`、`denied_operations`、`requires_approval_operations`、`not_executable_operations`。
- `OperationDescriptor` 已包含 risk tags、read_only、destructive、requires_approval_by_default、safety_validator_ref。
- 工具层的旧 `PermissionService` 仍能按 permission mode 和工具 risk tag 计算可见工具。

缺口：

- 权威源不唯一：`PermissionService` 以工具名为单位，`OperationGate` 以 operation 为单位，MCP 权限又在 client/server 层各包了一层。前端如果只看其中一层，会出现“展示已授权但运行时拒绝”或“展示隐藏但当前 turn 可用”的错觉。
- `permission_mode` 已可通过前端切换，但主运行时创建 `OperationGatePipelineContext` 时没有显式传入当前 permission mode，导致全局开关和真实执行不一致。
- `requires_approval` 缺少完整闭环：工具请求可以进入 `requires_approval_operations`，但主运行时没有稳定进入 waiting approval、生成 approval token、恢复同一 directive 的执行流程。
- `OperationGate` 对缺失 `safety_validator_ref` 的情况偏放行；主对话工具路径传了 validator，但本地 MCP 执行器没有统一传入 validator，文件类 MCP 可能只做 operation 允许判断而少了路径安全校验。
- 本地 MCP 在缺少外部传入 ResourcePolicy 时会生成默认允许策略，这和“统一 MCP 管理 + OperationGate 唯一闸门”的目标冲突。
- 前端暴露的 approval policy 名称和运行时真实识别的策略不完全一致，部分策略目前更像标签，不是严格执行策略。

## 4. 本地原则与参考模式

本项目现有设计原则文档已经给出可迁移约束：

- `docs/设计原则/09-工具系统设计.md`：工具要有统一接口、安全默认、条件注册、延迟发现。
- `docs/设计原则/15-MCP-协议实现.md`：MCP 要分配置、连接、发现、代理、权限和生命周期状态。
- `docs/设计原则/16-权限系统.md`：权限必须 fail-closed，deny 和 safety check 优先，写入/执行必须经过 operation gate。
- `docs/设计原则/24-Skill-Plugin开发实战.md`：Skill 是 Markdown + frontmatter 的工作方法入口，多来源加载后要按优先级去重。
- `docs/系统规划/212-长任务工具协议与证据闭环结构修复计划-20260521.md`：灵魂投影和运行投影不能扩张工具权限；工具调用必须形成证据闭环，不能用伪结果应付测试。

本项目应借鉴的是结构原则，而不是照搬界面或字段：

- 借鉴工具系统的 builder + fail-closed 默认。
- 借鉴 MCP 的连接状态模型、配置签名去重、连接快照和工具代理。
- 借鉴 Skill 的多来源扫描、结构化 frontmatter、只注入 active skill。
- 借鉴当前运行时的 operation-first 权限模型，把前端展示、MCP 统一管理、Skill 依赖都收敛到 operation。
- 不借鉴把大量外部工具直接塞进模型 prompt；本项目应保持 operation/supply gate 为主。
- 不借鉴把 permission mode 当成纯 UI 开关；用户看到的权限状态必须能追溯到实际 `OperationGate` 输入和输出。

## 5. 推荐设计

### 5.1 Canonical CapabilityUnit

新增统一能力模型，作为 catalog、supply、前端管理、验证的共同输入。

建议字段：

```text
capability_id        tool:read_file / skill:pdf-analysis / mcp:local:pdf / mcp:external:server:tool
kind                 tool | skill | mcp | operation
title                人类可读名称
summary              能力说明
operation_ids        该能力最终需要的 operation 列表
provider             builtin | mcp:local | mcp:external:<server_id>
provider_kind        builtin | local | external
transport            in_process | stdio | streamable_http
runtime_visibility   main_runtime | agent_internal | orchestration_internal | external_discovery
model_visibility     schema_visible | selected_skill_only | not_direct_model_tool | permission_gated
risk                 read/write/network/shell/mcp/delegation 等标准风险集
resource_policy      none | explicit_path | explicit_resource | handle_only
status               active | disabled | unsupported | failed | stale
health               last_checked_at/status/reason
source_ref           原始注册来源与路径
dependencies         skills/tools/mcps/resources 之间的结构依赖
```

权威关系：

- ToolDefinition 继续是内置工具源码权威。
- SkillContract 继续是 Skill 文件权威。
- LocalMCPUnitRecord 继续是本地专业能力权威。
- ExternalMCPServerConfig + snapshot 继续是外部 MCP 权威。
- `CapabilityUnit` 是统一投影，不反向覆盖源码权威。

### 5.1.1 信息保留与删除准则

能力管理页只能优先展示能改变判断的信息。凡是不能改变“是否可执行、为何可执行、由谁授权、失败如何恢复”的字段，默认降级为折叠诊断或删除。

必须保留在主视图的信息：

- `capability_id`、`kind`、`provider`、`source_ref`
- `operation_ids`
- `profile_state`、`adoption_state`、`gate_state`、`approval_state`
- `status`、`health.reason`
- 依赖关系：skill -> operation、tool -> operation、mcp provider -> tool -> operation
- 最近一次失败原因和可操作下一步

只允许放入次级诊断的信息：

- 展示分类，例如工具类型、中文边界标签、适配器标签。
- 风险摘要的派生文案。
- 旧字段兼容计数。
- 调试图和 raw JSON。

应该删除或停止作为主信息的信息：

- 没有真实授权含义的 `authorized` 布尔值。
- 没有 profile/turn/gate 输入的“Agent 绑定工具”。
- 由前端或 catalog 临时推导、但不被 runtime 消费的治理建议。
- 两套 MCP 列表对同一端点的重复描述。
- 只证明“系统里有这个字段”，不能帮助用户采取行动的状态徽章。

### 5.2 WorkspaceFileService

把文件路径解析、读写、结构化读取、glob/list/stat/path_exists、文本计量中的路径部分统一下沉：

```text
WorkspaceFileService
  workspace_root
  resolve(path, mode=read|write)
  read_text(path, limit)
  write_text(path, content)
  edit_text(path, old, new)
  list_dir(path)
  glob(pattern)
  stat(path)
  safe_roots(roots, defaults)
```

原则：

- 工具是通用工作区能力，不固定在 `backend/knowledge` 或某个业务目录。
- 路径安全、工作区根、显示相对路径只在 service 内决定。
- 写入授权仍由 operation gate 决定，service 不替代权限系统。

### 5.3 Skill 优化

Skill 应升级为“工作方法合同”，而不是“隐形工具”：

- frontmatter 增加 `requires_operations` 或从 `preferred_route` 显式解析出 operation。
- frontmatter 增加 `requires_capabilities`，例如 `local_mcp:pdf`、`tool:read_file`。
- `SkillPolicyResolver` 输出时带上选中理由、依赖 operation、缺失能力诊断。
- Skill prompt 质量检查加入 Agent 角色语义规则：要写成“你是一名...你负责...你不负责...你需要输出...”，不能写成开发说明。
- 运行时仍只注入 active skill，不把完整 registry 注入主 prompt。

Skill 质量分级：

- A 级：触发边界清楚；不适用场景清楚；有委派输入、回传结构、主 Agent 收口方式；声明依赖 operation/capability；正文能直接指导 Agent 处理失败和限制。
- B 级：正文可用，但依赖、失败边界或回传结构不完整；可以保留，但必须补合同字段。
- C 级：只有用途说明和标签，缺少执行步骤、边界和输出合同；不得自动触发，只能作为草稿。
- D 级：写成开发说明、节点说明、宣传文案，或声明不存在的工具/权限；必须删除或重写。

当前 Skill 初判：

- `rag-skill`：B+。正文可用，证据边界明确；缺少 `requires_operations=["op.mcp_retrieval"]`，运行时注入摘要和正文脱节。
- `pdf-analysis`：B+。文档阅读边界较清晰；缺少 `requires_operations=["op.mcp_pdf"]`，页级/OCR 失败处理需要机器可校验字段。
- `structured-data-analysis`：B+。可计算任务边界清楚；缺少 `requires_operations=["op.mcp_structured_data"]` 和结果子集依赖字段。
- `skill-creator`：B-。正文方向正确，但 `preferred_route: rag` 是错误路由信号；应改成 authoring/workflow 能力，不应伪装成知识检索。

Skill 系统的主要问题不是“文案差”，而是“正文、frontmatter、运行时注入、权限依赖”四者没有形成同一个合同。

### 5.4 MCP 统一管理优化

MCP 只保留一个管理平面，不再拆成本地 MCP 管理和外部 MCP 管理。差异只存在于 provider 适配层：

```text
MCPManagementService
  LocalMCPProvider      provider_kind=local, transport=in_process
  ExternalMCPProvider   provider_kind=external, transport=stdio | streamable_http
```

统一暴露接口：

```text
list_servers()
inspect_server(server_id)
build_catalog()
list_tools(server_id)
call_tool(server_id, tool_name, arguments)
preview_permission(server_id, tool_name, arguments)
```

执行差异：

- 本地 MCP：直接调用项目内 unit/worker，不 spawn 进程，不伪装成外部 stdio server。
- 外部 MCP：通过 MCP client 和 transport 连接真实外部服务。
- 二者都生成 MCP snapshot、MCP tool entry、operation 映射和授权预览。
- 二者都进入同一个 `CapabilityUnit(kind=mcp)` 投影。
- 本地 MCP 默认仍为 `not_direct_model_tool`，可由编排系统调用，但不直接暴露为模型工具。

统一 MCP 管理需要补齐：

- `streamable_http` 如果未实现，前端状态必须显示 `unsupported`，不能显示成可用。
- 增加统一 inspect snapshot 缓存；本地 provider 生成轻量快照，外部 provider 避免每次 catalog 请求都 spawn/连接。
- 增加 server/tool 级授权预览：允许、需审批、拒绝、原因、operation_id。
- 增加连接状态枚举：disabled、unsupported、failed、connected、not_inspected。
- 后续再实现 streamable HTTP，不在当前阶段用假可用状态掩盖。

### 5.5 Catalog / Supply / Runtime 固定流

固定执行流：

```text
1. Source registries
   ToolDefinition / SkillContract / MCPProvider snapshots / OperationRegistry

2. CapabilityUnit projection
   统一生成能力单元，保留 source_ref 和 diagnostics

3. Validation
   校验 operation 映射、风险标签、可见性、MCP 支持状态、Skill 依赖

4. Catalog
   前端展示 CapabilityUnit 列表、分组、健康、绑定关系、授权预览

5. Supply package
   按 task_id / agent_id / operation_scope 过滤 CapabilityUnit，输出运行时可用能力

6. Runtime execution
   ToolRuntime / MCPManagementService / SkillPolicyResolver 只执行已通过 operation gate 的能力

7. Observation
   记录能力调用、授权结果、错误、产物引用，供右侧监控面板显示
```

各阶段禁止事项：

- Catalog 不做运行决策，只展示和诊断。
- Skill 不直接授予工具权限，只声明任务方法和能力需求。
- MCP provider 不直接绕过统一管理服务执行。
- MCP 工具不绕过 operation gate；本地 MCP 不因 in_process 传输获得特权。
- 文件工具不把业务目录写死进工具实现。

### 5.6 权限系统统一治理

权限系统目标是把“能力可见性”和“执行授权”彻底分开：

```text
Capability visibility
  说明能力存在、状态、风险、依赖和是否适合进入模型提示。

Operation authorization
  说明当前 turn 是否可以执行某个 operation。

Execution approval
  说明某次具体 directive / action_request 是否已经获得用户或沙箱策略许可。
```

唯一权威链路：

```text
AgentRuntimeProfile
  -> OperationRequirement
  -> ResourcePolicy adoption
  -> AuthorizedToolSet / MCP provider exposure
  -> OperationGate preflight
  -> ExecutionRecord
  -> Observation / monitor
```

角色分工：

- `OperationRegistry`：所有可执行 operation 的权威 manifest。
- `AgentRuntimeProfile`：Agent 能力上限，不代表本轮已授权。
- `OperationRequirement`：当前任务请求哪些 operation。
- `ResourcePolicy`：当前 turn 最终授权快照。
- `OperationGate`：唯一执行闸门，所有 tool/MCP/delegation/model response 都必须经过。
- `PermissionService`：降级为旧工具名兼容视图和 UI 过渡适配器，不再作为运行时授权权威。
- `CapabilityUnit`：展示 operation 依赖、风险、授权预览，不直接授权。

必须修复：

- `permission_mode` 必须从 settings 进入 `OperationGatePipelineContext`，并在 gate event 中回显。
- `approval_policy` 必须整理成运行时真实识别的枚举，前端只能展示已实现策略。
- `requires_approval` 必须形成固定状态机：

```text
OperationGate -> requires_approval
  -> Runtime state = waiting_approval
  -> pending_approval_state 保存 operation_id / directive_ref / action_request_ref / tool args / risk
  -> UI approve/reject
  -> ApprovalToken(granted=True, operation_id, directive_ref)
  -> resume 同一 directive
  -> OperationGate 校验 token
  -> 执行或拒绝
```

沙箱策略：

- sandbox 可以把写入、shell、python 等 side effect 限制在 overlay 中执行。
- sandbox 不是绕过权限；它只改变 safety validator 的有效根目录和 approval decision。
- 如果 sandbox 未准备好，side effect operation 必须 fail-closed。

安全 validator 规则：

- operation 声明了 `safety_validator_ref`，但运行时 context 缺少对应 validator 时，必须 deny。
- 本地 MCP、外部 MCP、内置工具要走同一套 validator 注入方式。
- 文件路径 validator 要基于 `WorkspaceFileService` 的 workspace root 语义。

管理面展示规则：

- 前端必须显示三层权限，不再只显示 `authorized=true/false`：
  - profile ceiling：Agent profile 是否允许。
  - turn adoption：当前 ResourcePolicy 是否采用。
  - gate result：最近一次 OperationGate 判定。
- `authorized` 只能用于“当前可执行事实”，不能用于“这个能力存在”。
- `requires_approval` 要作为独立状态显示，不能混入 deny。

## 6. 数据模型变更

新增：

- `CapabilityUnit`
- `CapabilityDependency`
- `CapabilityHealth`
- `CapabilityPermissionView`
- `OperationAuthorizationView`
- `ApprovalRequestState`
- `ApprovalDecisionToken`
- `WorkspaceFileService`
- `MCPManagementService`
- `MCPProvider` / `LocalMCPProvider` / `ExternalMCPProvider`
- `MCPSnapshotCache`

保留但职责收窄：

- `CapabilitySupplyToolRef` / `CapabilitySupplySkillRef` / `CapabilitySupplyMCPRef` 作为迁移期输出。
- `build_orchestration_capability_items()` 作为前端兼容视图，后续改由 `CapabilityUnit` 派生。

后续可删除：

- 重复的 local MCP projection 字段。
- catalog 内临时拼接的风险/边界推导逻辑中可被 `CapabilityUnit` 替代的部分。
- 旧的“只为展示而存在”的分支字段。
- `PermissionService` 中被 `OperationGate` 取代的运行时授权判断，只保留兼容 API 或彻底迁移后删除。

权限模型建议：

```text
CapabilityPermissionView
  capability_id
  operation_ids
  profile_state        allowed | blocked | not_in_profile | unknown
  adoption_state       adopted | requires_approval | denied | not_requested | not_executable
  gate_state           allowed | requires_approval | denied | not_checked
  approval_state       not_required | pending | approved | rejected | unavailable
  sandbox_state        none | prepared | unavailable | blocked
  reasons[]
  diagnostics
```

这个模型只用于展示和调试，不替代 `ResourcePolicy` 与 `OperationGate`。

## 7. 分阶段实施计划

### Phase 0：红线测试与伪权威冻结

目标：先用测试锁住“不允许劣化”的底线，冻结会误导用户和运行时的伪权威字段。没有通过 Phase 0，不进入任何统一 catalog 或前端重做。

文件：

- `backend/orchestration/resource_gate.py`
- `backend/runtime/unit_runtime/loop.py`
- `backend/capability_system/mcp/server/local_capability_server.py`
- `backend/capability_system/catalog.py`
- `backend/capability_system/skill_policy.py`
- `backend/tests/*permission*`
- `backend/tests/*capability*`
- `backend/tests/*skill*`

完成标准：

- 新增 regression：operation 声明 `safety_validator_ref` 但 context 缺少 validator 时必须 deny。
- 新增 regression：本地 MCP 没有当前 `ResourcePolicy` 时不能执行真实任务调用，只能返回管理/预检状态。
- 新增 regression：主运行时 gate event 必须回显当前 `permission_mode`，且 `dont_ask/headless` 对审批 operation 生效。
- 新增 regression：`activation_policy=manual/disabled` 不会被自动 resolver 选中，显式指定 disabled skill 也必须拒绝或返回不可用诊断。
- 新增 regression：只读 `read_file/search_text/search_files/list_dir/stat_path/path_exists/glob_paths` 不因为权限收敛进入审批。
- 在 catalog 中把 `operation_metadata`、`authorized`、`binding_graph` 标为展示/兼容字段，不再让前端把它们解释成执行授权。

### Phase 1：稳住文件能力边界

目标：所有文件工具默认面向项目工作区根。

文件：

- `backend/capability_system/units/tools/workspace_paths.py`
- `backend/capability_system/units/tools/read_file_tool.py`
- `backend/capability_system/units/tools/write_file_tool.py`
- `backend/capability_system/units/tools/file_system_tools.py`
- `backend/capability_system/units/tools/structured_file_tool.py`
- `backend/capability_system/units/tools/text_metric_tool.py`
- `backend/tests/workspace_file_tools_regression.py`

完成标准：

- `ToolRuntime(backend_dir)` 读写 `knowledge/x` 时命中项目根 `knowledge/x`。
- `backend/knowledge/x` 不会被误当作默认知识库根。
- 写操作仍只在 workspace 内，路径穿越被拒绝。

### Phase 2：抽出 WorkspaceFileService

目标：移除文件工具内重复路径逻辑。

文件：

- 新增 `backend/capability_system/workspace_file_service.py`
- 更新 `units/tools/*file*`
- 更新 `validators/filesystem_path.py`

完成标准：

- 路径解析、相对显示、编码 fallback、写入目录创建都走 service。
- 文件工具只处理参数和输出格式。
- `SearchFilesTool` 的默认根不再包含过时的 `backend/knowledge` 特例；默认搜索根来自 service 的 workspace policy。
- `GlobPathsTool` 不再同时遍历 backend root 和 workspace root 造成重复候选。

### Phase 3：收敛权限权威链路

目标：把 `OperationGate + ResourcePolicy` 固定为运行时唯一授权权威，旧工具名权限只做兼容展示。

文件：

- `backend/permissions/service.py`
- `backend/permissions/decision_pipeline.py`
- `backend/orchestration/resource_gate.py`
- `backend/orchestration/resource_policy.py`
- `backend/runtime/shared/model_adoption.py`
- `backend/runtime/shared/tool_adoption.py`
- `backend/runtime/shared/safety.py`
- `backend/runtime/unit_runtime/loop.py`
- `backend/api/config_api.py`
- `backend/api/orchestration.py`
- `backend/tests/*permission*`
- `backend/tests/*resource*`

完成标准：

- 主运行时所有 `OperationGatePipelineContext` 都携带当前 `permission_mode`、headless 状态和 validator。
- `permission_mode` 前端切换后，gate event 和实际执行结果一致。
- `OperationGate` 在 operation 声明 `safety_validator_ref` 但缺少 validator 时 fail-closed。
- `PermissionService` 不再被描述为执行授权权威，只输出兼容 tool-name view。
- 前端 runtime options 只展示运行时真实实现的 approval policy。
- 只读 search/read/list/stat/glob 不因为权限收敛新增无意义审批。
- `ToolRuntime.get_definition()` 和 `ToolRegistry.get_by_name()` 只能从同一个 registry 实例读取，不能绕回静态 map。
- `terminal` / `python_repl` 的黑名单不被视为权限系统，只作为最后一层输入校验；执行授权必须来自 gate/approval/sandbox。

### Phase 4：补齐审批闭环

目标：`requires_approval` 从“被记录的 gate 结果”变成可恢复、可审计、可拒绝的运行状态。

文件：

- `backend/orchestration/resource_gate.py`
- `backend/runtime/shared/models.py`
- `backend/runtime/shared/checkpoint.py`
- `backend/runtime/shared/tool_adoption.py`
- `backend/runtime/unit_runtime/loop.py`
- `backend/runtime/graph_runtime/monitoring.py`
- `backend/api/orchestration.py`
- `frontend/src/components/chat/TaskGraphRunPanel.tsx`
- `frontend/src/lib/store/runtime.ts`

完成标准：

- 工具调用 gate 返回 `requires_approval` 时，任务进入 `waiting_approval`，不被当成普通失败。
- `pending_approval_state` 保存 operation、directive、action request、工具参数摘要、风险、沙箱状态。
- UI approve/reject 后生成或拒绝 `ApprovalToken`。
- approve 后恢复同一 directive 并再次经过 `OperationGate`；reject 后形成明确观察和监控事件。
- 审批 token 必须绑定 operation_id + directive_ref，不能跨工具调用复用。
- 审批恢复不能重新规划成另一个工具调用来掩盖原调用失败。
- 前端右侧监控面板显示 pending operation、directive、风险摘要、approve/reject 结果，不只显示“人工门控”。

### Phase 5：引入 CapabilityUnit 投影层

目标：统一 tools/skills/local MCP/external MCP 的 catalog 输入，并把权限预览作为投影字段而不是运行决策。

文件：

- `backend/capability_system/models.py`
- 新增 `backend/capability_system/capability_units.py`
- 新增 `backend/capability_system/permission_views.py`
- `backend/capability_system/catalog.py`
- `backend/capability_system/validation.py`

完成标准：

- catalog 先生成 `capability_units`。
- 原有 `skills/tools/mcps/local_mcp_units` 可作为兼容字段保留一个迁移窗口。
- validation 基于 `CapabilityUnit` 做主要一致性检查。
- 每个 capability unit 能展示 operation 依赖、profile ceiling、turn adoption、最近 gate 结果或 `not_checked`。
- catalog 不直接授予运行权限。
- 新投影不得替代源码权威；不能为了统一展示而丢失工具、Skill、MCP 的专有诊断。
- `operation_metadata` 中由前端展示偏好产生的字段迁移到 `display_facets`，和 `permission_view`、`source_ref` 分开。
- `binding_graph` 只保留真实依赖边：skill -> operation、tool -> operation、mcp tool -> operation、provider -> tool；删除“主 Agent 持有所有 main_runtime 工具”的伪绑定。

### Phase 6：重做 Supply Package

目标：运行时能力包从三套 refs 收束为一套 refs，并只承载当前 turn 已授权能力。

文件：

- `backend/capability_system/supply.py`
- `backend/capability_system/models.py`
- `backend/runtime/shared/model_adoption.py`
- `backend/runtime/unit_runtime/loop.py`
- `backend/orchestration/agent_runtime_chain.py`

完成标准：

- supply 可按 operation_scope 过滤所有能力种类。
- 输出 `capability_refs`，兼容输出旧 refs。
- Runtime 只使用通过 scope 和 gate 的能力。
- supply 中区分 `visible_to_model`、`runtime_executable`、`requires_approval`。
- Skill refs 必须带依赖 operation 状态，不能在 operation 被拒绝时仍显示为可执行技能。

### Phase 7：Skill 合同升级

目标：Skill 变成可审计工作方法，声明依赖但不授予权限。

文件：

- `backend/capability_system/skill_contracts.py`
- `backend/capability_system/skill_scanner.py`
- `backend/capability_system/skill_policy.py`
- `backend/capability_system/units/skills/*/SKILL.md`
- `backend/tests/skill_*`

完成标准：

- Skill 显式声明 operation/capability 依赖。
- Resolver 输出依赖、缺失项、匹配原因。
- `activation_policy=manual/disabled` 真正影响自动选择。
- Skill prompt 校验禁止开发说明式内容。
- Skill 选中后只影响 OperationRequirement 和提示，不直接扩大工具权限。
- 移除 `skill_scanner.py` 中按 skill name 硬编码 delegation/return protocol 的做法，协议应来自 `SKILL.md` 或结构化 frontmatter。
- `skill-creator` 不再使用 `preferred_route: rag`；改为明确的 authoring/workflow route 或显式无执行 route。
- 运行时注入的 active skill 必须可追溯：使用的是完整正文、结构化摘要，还是压缩 prompt block，不能让前端误以为完整 `SKILL.md` 已被注入。

### Phase 8：统一 MCP 管理升级

目标：本地 MCP 和外部 MCP 进入同一套管理接口、同一套快照、同一套授权预览、同一套 `CapabilityUnit(kind=mcp)` 投影。

文件：

- 新增 `backend/capability_system/mcp/providers.py`
- 新增 `backend/capability_system/mcp/local_provider.py`
- 新增 `backend/capability_system/mcp/external_provider.py`
- 新增 `backend/capability_system/mcp/management_service.py`
- `backend/capability_system/local_mcp_registry.py`
- `backend/capability_system/mcp_registry.py`
- `backend/capability_system/mcp/client/models.py`
- `backend/capability_system/mcp/client/manager.py`
- `backend/capability_system/mcp/client/config_store.py`
- `backend/capability_system/mcp/client/permission.py`
- `backend/capability_system/mcp/server/local_capability_server.py`
- `backend/capability_system/mcp/server/tool_pool.py`
- `backend/capability_system/endpoints.py`

完成标准：

- catalog 不再需要分别读取 `local_mcp_units` 和 external tool pool 才能展示 MCP。
- 本地 retrieval/pdf/structured_data 以 `provider_kind=local` 出现在统一 MCP 列表。
- 外部 stdio/streamable_http 以 `provider_kind=external` 出现在统一 MCP 列表。
- `streamable_http` 未实现时稳定显示 `unsupported`。
- inspect 有统一 snapshot/diagnostics。
- 本地 MCP 不再使用默认自授权策略；没有当前 ResourcePolicy 时只能做管理检查，不能执行真实任务调用。
- 本地/外部 MCP call 都经过同一套 `OperationGate`、permission mode、safety validator。
- 前端能看到每个 MCP tool 对应 operation、授权状态和失败原因。
- 现有任务图调用本地 retrieval/pdf/structured_data 的路径必须继续可用，不能为了统一管理牺牲核心任务执行。
- 删除或降级重复 MCP 展示源：`local_mcp_units`、`mcps`、`capability_endpoints`、`tool_pool` 最终只能由同一 provider snapshot 派生。
- 外部 MCP catalog 不能每次普通页面加载都真实 spawn/连接所有 server；必须使用 snapshot cache 和手动 inspect。

### Phase 9：前端能力与权限管理接入

目标：能力系统成为实用工作台的一个清晰管理面板。

前端结构建议：

- 能力总览：工具 / Skill / MCP 三个主入口；MCP 内部用 provider、transport、状态筛选，不再拆两个管理层。
- 工具详情：operation、风险、可见性、是否自动路由、授权要求。
- Skill 详情：适用任务、依赖能力、prompt 预览、校验问题。
- MCP 详情：provider_kind、server 状态、transport、tools、授权预览、连接诊断。
- 权限详情：profile ceiling、本轮 ResourcePolicy、最近 OperationGate、审批状态、沙箱状态。

完成标准：

- 前端不再自己推断风险和绑定关系，全部使用后端 catalog。
- 右侧监控面板显示能力调用、授权、失败诊断。
- `authorized`、`requires_approval`、`denied`、`unsupported`、`not_checked` 使用不同状态，不混在一个布尔值里。
- 删除把展示备注伪装成工具能力的交互；工具类型、治理备注、LLM 说明只能放在“管理备注”区，不进入执行事实区。
- 能力页的默认详情顺序改为：执行状态、operation、依赖、权限视图、健康诊断、源码来源，展示标签放最后。
- MCP 不再单独作为“外部 MCP 控制面”主入口；统一放进能力系统的 MCP provider 页。

## 8. 文件级清单

| 文件 | 当前职责 | 行动 | 完成条件 |
| --- | --- | --- | --- |
| `backend/capability_system/models.py` | capability/supply 数据模型 | 新增 `CapabilityUnit` 系列模型 | catalog/supply 可共享 |
| `backend/capability_system/catalog.py` | 合并展示能力目录 | 改为由 `CapabilityUnit` 派生视图 | 兼容旧字段，新增 units |
| `backend/capability_system/supply.py` | 生成运行时能力包 | 增加统一 refs | operation_scope 覆盖所有能力 |
| `backend/capability_system/validation.py` | catalog 一致性校验 | 增加 unit 级校验 | 发现重复 id、未知 operation、错误可见性 |
| `backend/capability_system/tool_definitions.py` | 内置工具权威注册 | 保持源码权威，补充必要 manifest 字段 | 每个工具 operation/risk 完整 |
| `backend/capability_system/units/tools/*` | 工具实现 | 路径逻辑迁移到 service | 工具实现变薄 |
| `backend/capability_system/skill_contracts.py` | Skill 合同 | 增加依赖字段 | Skill 能映射到 operation |
| `backend/capability_system/skill_policy.py` | Skill 匹配 | 输出依赖与诊断 | 前端/运行时知道选择原因 |
| `backend/permissions/service.py` | 旧工具名权限服务 | 降级为兼容视图 | 不再作为运行时授权权威 |
| `backend/permissions/decision_pipeline.py` | 旧 permission mode 工具判断 | 对齐 OperationGate 语义或迁移删除 | 前端展示不误导执行权限 |
| `backend/orchestration/resource_gate.py` | 运行时 operation 闸门 | 接入真实 permission mode、validator fail-closed、approval token | 所有执行路径统一闸门 |
| `backend/orchestration/resource_policy.py` | 当前 turn 授权快照 | 保持执行权威，补充展示字段只通过 view 派生 | 不被 catalog/skill 覆盖 |
| `backend/runtime/shared/model_adoption.py` | 模型响应能力采用 | 输出完整 ResourcePolicy 和 capability state | profile/turn/gate 三层清楚 |
| `backend/runtime/shared/tool_adoption.py` | 工具请求能力采用 | 支持 requires_approval 状态机 | 不把审批当普通 deny |
| `backend/runtime/shared/safety.py` | operation 安全 validator | 统一文件/MCP/sandbox validator | 缺失 validator fail-closed |
| `backend/runtime/unit_runtime/loop.py` | 主运行时执行流 | 传入 permission mode、审批恢复、gate 事件回显 | 工具/MCP/模型入口一致 |
| `backend/runtime/shared/models.py` | 运行状态模型 | 补充 pending approval 状态结构 | 可 checkpoint / resume |
| `backend/capability_system/local_mcp_registry.py` | 本地 MCP 单元 | 接入 `LocalMCPProvider` | 本地端点走统一 MCP 管理 |
| `backend/capability_system/mcp/client/*` | 外部 MCP 管理 | 接入 `ExternalMCPProvider` | 外部端点走统一 MCP 管理 |
| `backend/capability_system/mcp/server/local_capability_server.py` | 本地 MCP 执行入口 | 移除默认自授权，接入统一 ResourcePolicy/Gate/validator | 本地 MCP 不再特权放行 |
| `backend/capability_system/mcp/management_service.py` | 待新增统一 MCP 管理服务 | 聚合 local/external providers | catalog/inspect/call/permission preview 统一 |
| `backend/capability_system/permission_views.py` | 待新增权限投影视图 | 生成 `CapabilityPermissionView` | 前端按三层状态展示 |
| `backend/bootstrap/app_runtime.py` | 启动刷新 catalog | 引入 units 构建/缓存 | 启动不做慢外部连接 |
| `frontend/src/components/workspace/views/*` | 能力管理前端 | 读取统一 catalog/permission view | 不自行推断授权 |
| `frontend/src/components/chat/TaskGraphRunPanel.tsx` | 运行监控和恢复 | 显示 waiting approval 并提交 approve/reject | 审批闭环可用 |
| `backend/tests/*capability*` | 能力回归 | 增加统一 unit 测试 | 结构迁移不破坏运行 |
| `backend/tests/*permission*` | 权限回归 | 增加 permission mode/gate/approval 测试 | 无误放行、无假授权 |

## 9. 验证矩阵

- 文件工具：读、写、编辑、结构化读、glob、stat、path_exists、路径穿越。
- 工具授权：main runtime 只见 schema 工具，高风险工具需要 gate。
- 权限模式：`permission_mode` 从 config 到 `OperationGatePipelineContext` 到 gate event 全链路一致。
- 审批闭环：写文件、shell、python 触发 `requires_approval` 时进入 waiting approval；approve 后同 directive 执行，reject 后明确拒绝。
- 安全 validator：声明了 `safety_validator_ref` 但未提供 validator 时必须 deny。
- 沙箱策略：sandbox side effect 只能写入 overlay；sandbox 未准备好时 side effect fail-closed。
- Skill：扫描、snapshot、resolver、prompt 合同、依赖 operation。
- MCP 统一管理：local/external providers 都能 list、inspect、catalog、permission preview。
- 本地 MCP：operation 类型必须是 `mcp`，模型不可直接看见，不能默认自授权执行。
- 外部 MCP：disabled、unsupported、failed、connected、permission denied、requires approval、tool call ok。
- Catalog：无重复 capability_id，无未知 operation，无错误可见性。
- Supply：operation_scope 能过滤 tools/local MCP/external MCP，Skill 只随任务方法进入，不能扩大权限。
- 前端：能力分类入口、权限详情、审批状态、诊断、监控面板不自行推断后端事实。

## 10. 切换与回滚规则

迁移期保留旧输出字段：

- `skills`
- `tools`
- `mcps`
- `local_mcp_units`
- `external_mcp_tool_pool`
- `tool_refs`
- `skill_refs`
- `mcp_refs`

新增字段先 shadow：

- `capability_units`
- `capability_refs`
- `capability_health`
- `capability_permission_views`
- `operation_authorization_views`
- `approval_request_state`

切换条件：

- 新旧 catalog summary 数量一致或有明确解释。
- 所有现有能力系统测试通过。
- 前端已切换读取 `capability_units`，旧字段只做兼容。
- `permission_mode`、`approval_policy`、`requires_approval` 的运行时行为和前端状态一致。
- 本地 MCP 和外部 MCP 的 permission preview 与实际 call 前 gate 结果一致。

回滚条件：

- runtime 工具授权出现误放行。
- 本地 MCP 被错误暴露给模型。
- 本地 MCP 重新出现默认自授权执行。
- 外部 MCP 失败状态被误显示成可调用。
- local/external provider 的授权预览和实际 call 结果不一致。
- 文件工具读写脱离 workspace 根。
- `requires_approval` 被误当成 allowed 或普通 deny。
- 缺失 safety validator 的 operation 被放行。
- `permission_mode` 前端切换与 gate event 不一致。

最终清理条件：

- 前端不再读取旧字段。
- supply 消费方不再读取三套 refs。
- 测试覆盖新模型所有核心路径。
- `PermissionService` 不再参与真实执行授权，或已被删除/改名为兼容视图服务。

## 11. 禁止捷径

- 不把工具限制写死到业务文件夹里。
- 不让 Skill 直接携带工具授权。
- 不把任何 MCP tool 绕过统一 MCP 管理服务或 operation gate 直接给模型。
- 不让本地 MCP 因为是 in-process 就默认自授权执行。
- 不把 `permission_mode` 当成只影响前端展示的开关。
- 不把 `requires_approval` 简化成 deny，也不在没有 token 的情况下当作 allow。
- 不在缺失 safety validator 时继续执行有 `safety_validator_ref` 的 operation。
- 不用“兼容旧逻辑”为理由保留无调用方的旧展示分支。
- 不用假 snapshot 或假测试结果证明连接可用。
- 不把 Agent prompt 写成开发说明，要写成角色、职责、边界、输出裁决。

## 12. 预期收益

- 能力系统从“多个列表合并展示”变成“统一能力模型 + 分层权威来源”。
- 权限系统从“工具名权限、operation gate、MCP 包装权限并行”变成“OperationGate + ResourcePolicy 唯一执行权威”。
- 文件工具真正成为通用 workspace 能力，目录限制由 runtime/resource policy 管。
- Skill 和 MCP 的边界清楚：一个是工作方法，一个是统一管理的能力端点。
- 前端能力管理可以实用化：看状态、看风险、看授权、看审批、看依赖、看错误原因。
- 右侧监控面板可以解释每次能力调用为什么可执行、为什么被拒绝、为什么等待审批。
- 后续扩展新工具、新 Skill、新 MCP 时，不需要在 catalog/supply/frontend 各补一套特殊逻辑。
