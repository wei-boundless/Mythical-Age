# 能力系统标准化重构计划

日期：2026-06-27  
范围：Capability System / MCP / Skills / Tools / 远程安装 / 运行时投影 / 权限与缓存边界  
状态：计划书，待确认后实施

## 1. 问题定义

当前项目已经存在三类能力系统：

- `Tools`：本地运行时工具，主要来自 `capability_system.tools` 和 `runtime.tool_runtime`。
- `MCP`：本地或外部 MCP 服务，主要来自 `capability_system.mcp`。
- `Skills`：可注入 agent 语义空间的能力说明和工作流知识，主要来自 `capability_system.skills`。

问题不在于没有能力系统，而是三者目前没有统一的生命周期、安装模型、能力目录、权限模型和运行时投影规则。结果是：

- Tool、MCP、Skill 各自有 registry，但缺少统一的 `Capability Registry` 作为单一事实源。
- MCP 和 Skills 可以被列入能力目录，但缺少成熟的远程安装、校验、启用、禁用、升级、卸载、回滚流程。
- Tool 是运行时可执行能力，Skill 是提示词/知识能力，MCP 是外部服务能力，但它们现在容易在展示、权限、路由、运行时投影里混成同一层。
- 当前工具契约和 capability supply 之间还没有清晰的切换点：provider-native tool sidecar、JSON tool action、MCP 工具、Skill 激活应该由同一套能力策略派生，而不是各模块自行判断。

正确终态应当是：

```text
Capability Package
-> Capability Registry
-> Capability Resolver
-> Runtime Supply Package
-> Tool Catalog / Skill Prompt / MCP Provider Surface
-> Permission Admission
-> Execution / Prompt Injection
-> Observation / Audit
```

其中 agent 只接收当前回合需要的、低污染的能力投影；系统负责安装、校验、权限、执行和审计。

## 2. 本项目现状源报告

### 2.1 统一目录已有雏形

`backend/capability_system/catalog_models.py` 已定义：

- `CapabilityUnit`
- `CapabilitySupplyPackage`
- `CapabilitySupplyToolRef`
- `CapabilitySupplySkillRef`
- `CapabilitySupplyMCPRef`
- `CapabilityPermissionView`

这说明项目已经有“能力单元”和“能力供给包”的方向，但目前它更像投影结构，不是完整的安装与生命周期事实源。

`backend/capability_system/unit_projection.py` 已经能把 Skills、Tools、MCP 投影成 `CapabilityUnit`：

- `_skill_units(...)`
- `_tool_units(...)`
- `_mcp_units(...)`

这是重构的核心保留点，应升级为标准化 registry 输出，而不是重写。

### 2.2 Tools 当前链路

关键文件：

- `backend/capability_system/tools/registry.py`
- `backend/capability_system/tools/native_tool_catalog.py`
- `backend/runtime/tool_runtime/tool_definition.py`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/tool_catalog_manifest.py`
- `backend/harness/runtime/provider_tool_schema.py`

当前 ToolRegistry 直接从 `native_tool_catalog.get_tool_definitions()` 读取内置工具；`RuntimeToolDefinition` 已经具备成熟执行契约：

- `validate_input`
- `check_permissions`
- `call`

这条链路应该作为本地工具的标准，不应被 MCP 或 Skill 安装逻辑污染。

### 2.3 MCP 当前链路

关键文件：

- `backend/capability_system/mcp/registry.py`
- `backend/capability_system/mcp/management_service.py`
- `backend/capability_system/mcp/local_registry.py`
- `backend/capability_system/mcp/external_provider.py`
- `backend/capability_system/mcp/client/config_store.py`
- `backend/capability_system/mcp/client/manager.py`

当前能力：

- 已有 local MCP catalog。
- 已有 external MCP config store。
- 支持 `stdio` 和 `streamable_http` 配置校验。
- `ExternalMCPProvider` 可以 inspect server、preview permission、call tool。

当前缺口：

- 外部 MCP 只是配置 upsert/delete，不是完整“远程安装包”。
- 没有安装来源、版本、digest、签名、授权域、启用状态、升级策略、回滚状态。
- 外部 MCP 的 transport、OAuth、token、环境变量、命令参数还没有统一治理。
- catalog 刷新和 runtime 暴露之间缺少稳定的安装状态机。

### 2.4 Skills 当前链路

关键文件：

- `backend/capability_system/skills/scanner.py`
- `backend/capability_system/skills/registry.py`
- `backend/capability_system/skills/contracts.py`
- `backend/capability_system/skills/paths.py`
- `backend/capability_system/skills/authoring.py`
- `backend/capability_system/skills/operation_requirements.py`

当前能力：

- 可以扫描 `SKILL.md`。
- 可以解析 frontmatter。
- 可以生成 `SKILLS_REGISTRY.json` 和 `SKILLS_SNAPSHOT.md`。
- Skill contract 已包含 runtime/prompt 双视图。

当前缺口：

- 只支持本地扫描，缺少远程 skill 安装。
- 没有 skill package manifest、来源证明、版本、digest、依赖、更新策略。
- Skill 的 prompt 注入、reference 文件加载、script 权限没有统一安装审计。
- 远程 Skill 必须防止 prompt 注入供应链污染，不能安装后默认全局注入。

### 2.5 Capability Supply 当前链路

关键文件：

- `backend/capability_system/supply.py`
- `backend/capability_system/catalog_projection.py`
- `backend/capability_system/endpoint_projection.py`
- `backend/api/capability_system.py`

当前 `build_capability_supply_package_from_base_dir(...)` 已经能聚合：

- Skills
- Tools
- Tool packages
- MCP catalog
- Capability endpoints

这是未来 `CapabilityResolver` 的基础，但现在还是“聚合输出”，不是“策略化选择 + 安装状态 + 权限裁剪 + 运行时挂载”。

## 3. 外部成熟架构参考

### 3.1 MCP 官方协议

MCP 官方 Tools 规范要求服务声明 `tools` capability，客户端通过 `tools/list` 发现工具，通过 `tools/call` 调用工具。每个 tool 至少有唯一 `name`、描述和 `inputSchema`，可选 `outputSchema`。MCP 还明确区分协议错误和工具执行错误，并强调输入校验、访问控制、限流、输出清洗、敏感操作确认和审计日志。

参考：

- https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization

对本项目的启发：

- MCP 不应直接等同于本地 Tool；它是外部能力 provider。
- MCP 工具应先安装/inspect，再映射为 `CapabilityUnit`，最后由权限系统决定是否暴露给 agent。
- HTTP MCP 授权要按 OAuth/资源服务器模型设计；stdio MCP 通过本地环境变量和命令配置处理凭据。

### 3.2 Claude Tool Use

Claude 工具使用模型区分 client tools 和 server tools。client tools 由应用执行，模型返回 `tool_use`，应用执行后返回 `tool_result`；server tools 由服务端基础设施执行。工具选择由模型基于工具描述和上下文决定，应用负责 schema、执行和错误反馈。

参考：

- https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview

对本项目的启发：

- 普通工具调用应优先走 provider-native，而不是要求 agent 手写 JSON。
- 权限、执行、失败反馈属于 runtime，不属于 prompt 里的格式游戏。
- Tools sidecar 有 token 成本，因此应由 `tool_transport_policy` 控制，而不是无条件进入所有回合。

### 3.3 Codex 能力组织

Codex 官方文档把 Tools、MCP、Skills、Permissions、AGENTS.md、Subagents 等作为独立配置和能力面组织。它的成熟点不是某个单独工具，而是能力系统的分层：

- 工具执行面
- MCP 扩展面
- Skills 知识/流程面
- 权限和审批面
- 项目规则面

参考：

- https://developers.openai.com/codex/cli

对本项目的启发：

- Skills 不应伪装成 tools；Skills 是 prompt/resource 能力。
- MCP 不应绕过工具权限；MCP 是远程或本地 provider。
- Tools 是执行单元；所有执行能力最终必须经过统一 permission admission。

## 4. 目标设计原则

### 4.1 三类能力的职责边界

| 类型 | 本质 | 是否直接执行 | 是否进入 prompt | 是否支持远程安装 |
|---|---|---:|---:|---:|
| Tool | 本地运行时可执行函数 | 是 | 只投影 schema/description | 暂不默认支持 |
| MCP | 外部或本地 MCP provider 的工具/资源/提示 | 通过 MCP client 执行 | 只投影被授权 tool/resource/prompt | 是 |
| Skill | 任务知识、工作流、提示词、脚本资源 | 否，除非引用工具 | 只在被选中时注入 | 是 |

注意：远程 Tool 安装不作为第一目标。外部执行能力优先通过 MCP 安装；本地 Tool 仍由代码和内置 registry 管理。这样能避免让远程代码直接进入主进程工具执行面。

### 4.2 单一能力事实源

新增目标概念：`CapabilityRegistryStore`。

它不替代现有 registry，而是把它们标准化收口：

```text
ToolRegistry
SkillRegistry
MCPManagementService
-> CapabilityRegistryStore
-> CapabilityResolver
-> CapabilitySupplyPackage
```

`CapabilityRegistryStore` 持久化所有能力安装状态：

- builtin
- local_project
- user_installed
- remote_installed
- disabled
- quarantined
- update_available
- failed_validation

### 4.3 安装不等于启用，启用不等于暴露

必须拆开：

```text
install -> validate -> register -> enable -> authorize -> project -> invoke/inject
```

- install：下载/写入/配置能力包。
- validate：校验 manifest、digest、结构、权限声明。
- register：进入统一能力目录。
- enable：用户或策略允许该能力参与候选。
- authorize：按 profile/environment/session 权限裁剪。
- project：进入当前回合 tool catalog / skill prompt / mcp surface。
- invoke/inject：真正执行工具或注入 Skill。

## 5. 标准能力包协议

### 5.1 Capability Package Manifest

新增统一 manifest，建议文件名：

- `capability.json`
- 或保留生态格式并生成内部 `capability.lock.json`

内部标准结构：

```json
{
  "schema_version": 1,
  "package_id": "skill:deep-web-research",
  "kind": "skill",
  "name": "deep-web-research",
  "version": "1.0.0",
  "title": "Deep Web Research",
  "description": "Research workflow skill",
  "source": {
    "type": "git",
    "url": "https://github.com/example/repo",
    "ref": "main",
    "subpath": "skills/deep-web-research",
    "commit": ""
  },
  "integrity": {
    "digest": "sha256:...",
    "signature": "",
    "trusted": false
  },
  "runtime": {
    "entry": "SKILL.md",
    "transport": "prompt_resource",
    "activation_policy": "manual_or_router_selected"
  },
  "permissions": {
    "requires_operations": ["op.web_search"],
    "requires_capabilities": [],
    "network": false,
    "filesystem": "read_package_only",
    "secrets": []
  },
  "install": {
    "installed_at": "",
    "installed_by": "user",
    "status": "installed"
  }
}
```

### 5.2 MCP Package Manifest

MCP 远程安装不应该只是保存一段 command。应生成标准安装记录：

```json
{
  "schema_version": 1,
  "package_id": "mcp:github",
  "kind": "mcp_server",
  "name": "github",
  "version": "1.0.0",
  "source": {
    "type": "mcp_registry",
    "url": "https://registry.example/mcp/github",
    "digest": "sha256:..."
  },
  "server": {
    "server_id": "github",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "url": "",
    "env_refs": ["GITHUB_TOKEN"]
  },
  "permissions": {
    "operation_prefix": "op.mcp.github",
    "network": true,
    "filesystem": "none",
    "secrets": ["GITHUB_TOKEN"],
    "requires_user_approval": true
  },
  "install": {
    "status": "installed",
    "enabled": false,
    "last_inspected_at": "",
    "last_tool_snapshot_hash": ""
  }
}
```

### 5.3 Skill Package Rules

远程 Skill 安装必须满足：

- 必须包含 `SKILL.md`。
- `SKILL.md` frontmatter 必须声明 name/description 或可推导。
- references/scripts/assets 只能在包目录内。
- 默认不允许安装后全局注入。
- 默认 activation_policy 为 `manual_or_router_selected`，不是 `always_on`。
- 如果 Skill 需要工具，必须声明 `requires_operations` 或 `requires_capabilities`。
- 如果包含脚本，脚本只是资源，不能自动执行；执行必须通过 Tool 权限链。

## 6. 目标模块设计

### 6.1 新增模块

建议新增：

```text
backend/capability_system/packages/
  models.py
  manifest.py
  installer.py
  source_fetcher.py
  integrity.py
  store.py
  validator.py
  resolver.py
  lifecycle.py
```

职责：

- `models.py`：统一 package、install record、source、integrity、status dataclass。
- `source_fetcher.py`：下载 git/http/local/path 包，只负责取回，不决定启用。
- `integrity.py`：digest、文件清单、可选签名。
- `validator.py`：按 kind 校验 skill/mcp 包结构。
- `store.py`：安装记录和 lock 文件持久化。
- `installer.py`：install/update/uninstall/rollback 编排。
- `resolver.py`：把安装状态合并进 `CapabilityUnit`。
- `lifecycle.py`：状态机和迁移规则。

### 6.2 改造 Skills

保留：

- `skills/scanner.py`
- `skills/registry.py`
- `skills/contracts.py`

新增：

- remote installed skills 目录。
- remote skill install record。
- scanner 读取 builtin + user/project + remote installed，但 registry 输出要标明 source kind。

建议目录：

```text
backend/capability_system/skills/builtin/
storage/runtime_state/capabilities/skills/installed/
storage/runtime_state/capabilities/skills/registry.lock.json
```

### 6.3 改造 MCP

保留：

- `mcp/management_service.py`
- `mcp/external_provider.py`
- `mcp/client/config_store.py`

新增：

- MCP remote package installer。
- MCP server install record。
- MCP inspect snapshot cache。
- MCP server enable/disable 状态。

现有 `ExternalMCPConfigStore` 只负责 server config；未来应由 package installer 写入 config store，而不是 UI/API 直接写裸配置。

### 6.4 改造 Tools

Tools 第一阶段不开放远程安装。理由：

- Tool 是主进程可执行代码。
- 远程 Tool 安装相当于远程代码执行供应链。
- 更成熟的方案是通过 MCP 承载远程工具，把执行隔离在 provider/server 边界外。

Tools 需要标准化：

- `ToolDefinition` 必须完整声明 operation_id、schema、risk、visibility、resource policy。
- ToolRegistry 输出必须进入统一 CapabilityRegistryStore。
- RuntimeToolPlan 只消费已授权 capability units，不再直接从多个 registry 拼接。

## 7. 运行时投影设计

### 7.1 Agent 可见层

Agent 可见能力分三段：

```text
Tool Capability Surface
Skill Activation Context
MCP Service Surface
```

但当前回合只投影必要部分：

- Tool：进入 provider-native tools sidecar 或 tool_index_stable。
- Skill：只有被选中的 skill 进入 prompt，不注入全量 skill registry。
- MCP：只有授权且已 inspect 的 MCP tools 进入 tool catalog；MCP server 元信息默认不进 prompt。

### 7.2 低语义污染原则

不把安装细节发给 agent：

- 不说 “这是 MCP remote package”。
- 不说 “这是从 GitHub 安装的 Skill”。
- 不暴露 command/env/token。
- 只说当前可用能力、调用边界、失败反馈。

### 7.3 与工具 transport 的关系

能力系统只决定“哪些能力可用”，不决定模型必须怎么表达工具调用。

工具 transport 由 `tool_transport_policy` 决定：

```json
{
  "selected_transport": "provider_native",
  "fallback_transport": "json_action",
  "ordinary_tool_calls": "provider_direct_tool_selection",
  "control_actions": "json_action"
}
```

## 8. 权限与安全边界

### 8.1 权限入口

所有能力都必须映射到 operation：

- Tool -> operation_id
- MCP tool -> generated operation_id
- Skill -> requires_operations / requires_capabilities

没有 operation 的能力只能安装和展示，不能执行或自动注入。

### 8.2 MCP 远程安全

MCP remote install 必须包含：

- source allowlist / trust state
- digest lock
- transport type
- secrets refs
- network boundary
- inspect snapshot
- user approval state
- enable/disable state

HTTP MCP 授权按 MCP Authorization 规范预留 OAuth metadata；stdio MCP 使用环境变量凭据，不把 secret 写入 package manifest。

### 8.3 Skill 远程安全

远程 Skill 默认：

- 不自动启用。
- 不自动注入。
- 不自动执行脚本。
- references 只读。
- 需要用户确认进入 `enabled`。
- 若声明高风险 operation，必须显示权限预览。

## 9. API 设计

建议扩展 `backend/api/capability_system.py`，不要把安装接口塞进 MCP 或 Skill 各自 API。

新增接口：

```text
GET  /api/capability-system/packages
POST /api/capability-system/packages/install-preview
POST /api/capability-system/packages/install
POST /api/capability-system/packages/{package_id}/enable
POST /api/capability-system/packages/{package_id}/disable
POST /api/capability-system/packages/{package_id}/update-preview
POST /api/capability-system/packages/{package_id}/update
POST /api/capability-system/packages/{package_id}/uninstall
POST /api/capability-system/packages/{package_id}/rollback
POST /api/capability-system/catalog/refresh
```

MCP 专属接口保留：

```text
POST /api/mcp-system/management/providers/{provider_id}/servers/{server_id}/inspect
POST /api/mcp-system/management/providers/{provider_id}/servers/{server_id}/tools/{tool_name}/preview
POST /api/mcp-system/management/providers/{provider_id}/servers/{server_id}/tools/{tool_name}/call
```

但外部 MCP 安装走 capability package API。

## 10. 存储设计

建议新增：

```text
storage/runtime_state/capabilities/
  packages.json
  package_locks/
    <package_id>.lock.json
  skills/
    installed/
      <skill_name>/
    registry.lock.json
  mcp/
    installed/
      <server_id>.json
    snapshots/
      <server_id>.tools.json
  audit/
    installs.jsonl
    updates.jsonl
    invokes.jsonl
```

原则：

- 安装包状态不写进源码目录。
- builtin 能力仍由源码目录提供。
- remote installed 能力写入 runtime_state。
- registry.lock 记录实际启用版本，便于回滚。

## 11. 分阶段实施计划

### 阶段 1：Capability Package 数据模型

目标：

- 定义统一 package/install/lock/status 模型。
- 不改变现有 runtime 行为。

涉及文件：

- 新增 `backend/capability_system/packages/models.py`
- 新增 `backend/capability_system/packages/store.py`
- 新增 `backend/capability_system/packages/manifest.py`
- 新增 `backend/capability_system/packages/validator.py`

完成标准：

- 能读取/写入 package install records。
- 能校验 skill/mcp package manifest。
- 不影响现有 Tool/MCP/Skill registry。

### 阶段 2：Skills 远程安装

目标：

- 支持从 local path / git / zip/http 安装 Skill。
- 生成 digest lock。
- scanner 合并 builtin + installed skill。

涉及文件：

- `backend/capability_system/skills/scanner.py`
- `backend/capability_system/skills/registry.py`
- `backend/capability_system/skills/paths.py`
- 新增 `backend/capability_system/packages/source_fetcher.py`
- 新增 `backend/capability_system/packages/installer.py`

完成标准：

- 安装后不会自动全局注入。
- refresh registry 后能看到 installed skill。
- 远程 Skill 缺少 `SKILL.md`、路径越界、脚本越权时失败。

### 阶段 3：MCP 远程安装

目标：

- 支持 MCP package install。
- install 后写入 external MCP config store。
- 支持 enable/disable。
- inspect 后生成 tool snapshot。

涉及文件：

- `backend/capability_system/mcp/client/config_store.py`
- `backend/capability_system/mcp/external_provider.py`
- `backend/capability_system/mcp/management_service.py`
- 新增 `backend/capability_system/packages/mcp_installer.py` 或归入 `installer.py`

完成标准：

- 未 enable 的 MCP 不进入 runtime capability supply。
- enabled 但未 inspect 的 MCP 状态为 `needs_inspection`。
- inspect 失败不会污染 active catalog。

### 阶段 4：统一 Capability Registry

目标：

- Tool、Skill、MCP 都输出到统一 capability registry。
- `build_capability_units(...)` 从 registry store 读取安装状态。
- `CapabilitySupplyPackage` 包含安装来源、启用状态、权限摘要。

涉及文件：

- `backend/capability_system/catalog_models.py`
- `backend/capability_system/unit_projection.py`
- `backend/capability_system/supply.py`
- `backend/capability_system/catalog_projection.py`

完成标准：

- 能区分 builtin/local/remote。
- 能区分 installed/enabled/disabled/quarantined。
- 能按 operation_scope 裁剪三类能力。

### 阶段 5：Runtime Resolver 接入

目标：

- RuntimeToolPlan 不再只从工具表自行判断。
- 当前回合使用 `CapabilityResolver` 产出的 supply package。
- Skill 只在 resolver 选中时注入。
- MCP tool 通过 MCP provider 映射进 Tool Catalog。

涉及文件：

- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/tool_catalog_manifest.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/packet_assembler.py`
- `backend/harness/loop/single_agent_turn.py`

完成标准：

- provider-native 工具契约仍可用。
- JSON transport 保留但不混入 provider 模式。
- MCP tool 和 builtin tool 都走同一 permission admission。

### 阶段 6：API 与前端准备

目标：

- 提供安装/启用/禁用/更新/卸载 API。
- 前端后续可以做能力市场和安装管理。

涉及文件：

- `backend/api/capability_system.py`
- `backend/api/mcp_system.py`

完成标准：

- API 返回 install preview，包括权限、来源、digest、风险。
- install 必须显式确认。
- uninstall 不删除审计记录。

### 阶段 7：验证与清理

目标：

- 清理重复 registry 输出。
- 删除旧的裸配置安装入口或改成调用 package installer。
- 真实运行验证。

验证方式：

- 不新增测试文件。
- `py_compile` 相关后端文件。
- 固定 `127.0.0.1:8003` 启动后端。
- 真实 API 验证：
  - builtin tools catalog
  - builtin skills catalog
  - remote skill install-preview
  - remote skill install
  - MCP server install-preview
  - MCP server enable
  - MCP inspect
  - runtime capability supply

## 12. 禁止事项

- 禁止让远程 Skill 安装后默认全局注入 prompt。
- 禁止把 MCP command/env/token 原样暴露给 agent。
- 禁止让外部 MCP 绕过 operation permission。
- 禁止把 Skill 当 Tool 执行。
- 禁止让 remote Tool 直接进入主进程执行面；外部可执行能力优先 MCP 化。
- 禁止保留两套互相竞争的能力事实源。
- 禁止为了兼容保留裸 external MCP config 写入路径作为并行主链路。

## 13. 最终验收标准

完成后应满足：

- `CapabilityUnit` 是统一能力展示和策略基础。
- `CapabilityPackage` 是远程安装和版本管理基础。
- Tool、MCP、Skill 三类能力边界清晰。
- MCP 和 Skill 支持远程安装、启用、禁用、更新、卸载、回滚。
- Runtime 只消费 resolver 裁剪后的 capability supply。
- Agent 只看到当前回合必要能力，不看到安装细节。
- 所有可执行能力都经过 operation permission。
- provider-native 工具调用主路径不被 JSON 动作对象污染。
- JSON transport 保留为可切换模式，而不是混合契约。

