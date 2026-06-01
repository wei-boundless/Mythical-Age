# CapabilitySystem 旁路重写与控制系统能力边界重构计划

日期：2026-06-02

## 1. 结论

`backend/capability_system` 当前不适合继续在原目录内修补。它已经同时承载：

- 能力目录和管理 API projection。
- operation 权限事实。
- tool definition 和 tool instance 工厂。
- skill 文件扫描、skill registry、skill prompt 编辑。
- MCP client/server/management。
- PDF、RAG、结构化数据、本地检索等领域执行器。
- deepsearch、codebase_search 等 agent capability runtime。
- permission view、search policy、skill policy 等控制推断或展示逻辑。

这不是单纯文件数量问题，而是权责混杂。控制系统真正需要的是少量稳定边界：

1. `permissions` 提供 operation 权限事实和 operation gate。
2. `runtime/tool_runtime` 提供工具定义、工具实例、工具执行和沙箱控制。
3. `agent_system` 提供 skill registry、skill prompt view 和 agent/profile 可见 skill。
4. `knowledge_system` / `evidence` 提供 PDF、RAG、结构化数据等领域能力执行。
5. `capability_system` 只保留管理 API 所需的 catalog projection，不再拥有执行、授权、路由和意图推断。

因此本次采用旁路重写：旧目录短期改名打包，重建目标结构，再清除旧目录和归档，不保留兼容壳。

## 2. 控制系统实际利用链路

### 2.1 启动层

`backend/bootstrap/app_runtime.py`

当前使用：

- `CapabilitySystemPaths.ensure()`
- `refresh_snapshot(base_dir)`
- `refresh_tool_registry(base_dir)`
- `SkillRegistry(base_dir)`
- `ToolRuntime(base_dir)`

目标：

- 启动层只初始化 `AgentSkillRegistry`、`NativeToolRuntime` 和必要的 catalog index。
- 不再从 `capability_system` 初始化工具执行器或权限事实。

### 2.2 Harness Runtime Facade

`backend/harness/entrypoint/runtime_facade.py`

当前使用：

- `build_tool_authorization_index(tool_runtime.definitions)`
- `ToolRuntimeExecutor(tool_runtime=tool_runtime)`
- `tool_runtime.definitions`
- `tool_runtime.instances`

目标：

- `build_tool_authorization_index` 迁到 `runtime/tool_runtime/authorization_index.py`。
- `ToolRuntimeExecutor` 继续归 `runtime/tool_runtime`。
- facade 只消费 `NativeToolRuntime.definitions/instances`，不 import capability package。

### 2.3 Runtime Assembly

`backend/harness/runtime/assembly.py`

当前使用：

- `SkillRegistry`
- `build_authorized_tool_set`
- `SkillRuntimeView`
- `skill_runtime_view_from_skill_definition`

目标：

- `SkillRegistry` 迁到 `agent_system/skills/registry.py`。
- `build_authorized_tool_set` 迁到 `runtime/tool_runtime/authorization.py`。
- assembly 只根据 agent profile、task environment、allowed operations 投影可用工具，不读取 capability 管理目录。

### 2.4 Permission Gate

`backend/permissions/operation_gate.py`

当前从 `capability_system.operation_registry` 读取：

- `OperationDescriptor`
- `OperationRegistry`

目标：

- `OperationDescriptor`、`OperationRegistry`、`default_operation_descriptors()` 迁到 `permissions/operations.py`。
- operation 风险、审批、只读、destructive、validator ref 只能以 `permissions.operations` 为唯一事实源。

### 2.5 Capability API

`backend/api/capability_system.py`

当前混合：

- catalog projection。
- skill 创建/编辑。
- resource policy candidate。
- capability supply package。
- agent enable/disable。

目标：

- API 路径 `/api/capability-system/*` 可以保留，作为管理界面兼容入口。
- API 内部改为调用新域服务：
  - catalog projection：`capability_system/catalog_projection.py`
  - skill 编辑：`agent_system/skills/authoring.py`
  - resource policy candidate：`permissions/resource_policy_builder.py`
  - supply package：`harness/runtime/capability_supply.py`
  - agent 管理：`agent_system/registry`

API 名称保留不等于后端旧包保留。

## 3. 旁路重写策略

### 3.1 旧目录处理

实施第一步：

1. 将 `backend/capability_system` 移出可导入路径。
2. 打包为短期归档，例如：
   - `archives/refactor/capability_system_legacy_20260602.zip`
3. 归档只用于实施期对照和回滚，不能被 import，不能在测试或运行中依赖。
4. 新结构测试通过后删除归档。

禁止：

- 不允许在新 `backend/capability_system/__init__.py` 中 re-export 旧模块。
- 不允许保留 `legacy_capability_system` 包给生产代码 import。
- 不允许以“兼容”为理由保留旧 skill policy、search policy、permission view 逻辑。

### 3.2 新包最小重建

重新创建 `backend/capability_system`，只保留管理 projection：

```text
backend/capability_system/
  __init__.py
  catalog_projection.py
  catalog_models.py
  endpoint_projection.py
  supply_projection.py
  validation.py
  capability_api_facade.py
```

职责：

- 聚合 operation facts、tool facts、skill facts、MCP provider facts，生成管理界面 catalog。
- 不创建工具实例。
- 不执行工具。
- 不决定权限。
- 不决定 skill 是否激活。
- 不根据用户任务推断 route/source/intent。

不保留：

- `CapabilitySystemPaths`。skill、tool、MCP 资产路径分别迁到各自系统。
- `tool_packages`。operation bundle 不属于 capability projection。
- `permission_views`。权限状态由 `permissions` 投影。
- `capability_units` 中的权限推断。若保留 unit projection，只能聚合外部事实。

## 4. 目标目录迁移清单

### 4.1 权限和 Operation

迁移：

- `backend/capability_system/operation_registry.py`
  -> `backend/permissions/operations.py`

修正：

- `OperationDescriptor.destructive/read_only/concurrency_safe/requires_approval_by_default` 成为唯一风险事实源。
- `tool_definitions` 不再重复维护 `is_destructive/is_read_only/is_concurrency_safe`，这些字段从 operation descriptor 派生。
- `python_repl` 风险冲突必须消失。

更新调用：

- `permissions/operation_gate.py`
- `permissions/runtime_policy_builder.py`
- `permissions/resource_policy_builder.py`
- `harness/runtime/single_agent_host.py`
- `runtime/tool_runtime/tool_control_plane.py`
- 测试中所有 `capability_system.operation_registry` import。

### 4.2 工具定义、工具实例和工具合同

迁移：

- `backend/capability_system/tool_definitions.py`
  -> `backend/runtime/tool_runtime/native_tool_catalog.py`
- `backend/capability_system/tool_runtime.py`
  -> `backend/runtime/tool_runtime/native_tool_runtime.py`
- `backend/capability_system/tool_authorization.py`
  -> `backend/runtime/tool_runtime/authorization.py`
- `backend/capability_system/tool_contracts.py`
  拆分为：
  - `backend/runtime/tool_runtime/contracts.py`
  - `backend/permissions/tool_scope.py`
- `backend/capability_system/validators/*`
  -> `backend/runtime/tool_runtime/validators/*`
- `backend/capability_system/units/tools/*`
  -> `backend/runtime/tool_runtime/native_tools/*`
- `backend/capability_system/workspace_file_service.py`
  -> `backend/runtime/tool_runtime/workspace_file_service.py`

保留规则：

- `RuntimeToolExecutor` 仍在 `backend/runtime/tool_runtime/tool_executor.py`。
- 新工具 catalog 只声明工具和工厂，不做权限裁决。
- 权限裁决只走 `permissions.OperationGate` 和 resource policy。

### 4.3 Skill Registry 和 Skill 资产

迁移：

- `backend/capability_system/skill_registry.py`
  -> `backend/agent_system/skills/registry.py`
- `backend/capability_system/skill_scanner.py`
  -> `backend/agent_system/skills/scanner.py`
- `backend/capability_system/skill_contracts.py`
  -> `backend/agent_system/skills/contracts.py`
- `backend/capability_system/skill_authoring.py`
  -> `backend/agent_system/skills/authoring.py`
- `backend/capability_system/skill_routes.py`
  -> 删除或迁到 `agent_system/skills/operation_requirements.py`
- `backend/capability_system/units/skills/*`
  -> `backend/agent_system/skills/builtin/*`
- `backend/capability_system/units/registries/SKILLS_*`
  -> `backend/agent_system/skills/registries/*`

删除：

- `backend/capability_system/skill_policy.py`

理由：

- 当前生产代码无引用。
- 它从 `request_intent` 读取 task frame 并推断 source kind，属于旧意图/路由权力，不属于 capability。

### 4.4 MCP 管理和本地 MCP 服务

迁移：

- `backend/capability_system/mcp/*`
  -> `backend/runtime/mcp/*`
- `backend/capability_system/mcp_registry.py`
  -> `backend/runtime/mcp/registry.py`
- `backend/capability_system/mcp_adapter.py`
  -> `backend/runtime/mcp/tool_adapter.py`
- `backend/capability_system/local_mcp_registry.py`
  -> `backend/runtime/mcp/local_registry.py`

边界：

- MCP provider/server/client 是运行时集成，不属于 capability projection。
- capability catalog 可以读取 MCP provider manifest，但不能启动 MCP server 或执行 MCP tool。

### 4.5 PDF、RAG、结构化数据领域实现

迁移：

- `backend/capability_system/units/mcp/local/pdf/*`
  -> `backend/knowledge_system/document_processing/pdf/*`
- `backend/capability_system/units/mcp/local/retrieval/*`
  -> `backend/knowledge_system/retrieval/*`
- `backend/capability_system/units/mcp/local/structured_data/*`
  -> `backend/knowledge_system/structured_data/*`

同步更新：

- `backend/evidence/pdf_worker.py`
- `backend/evidence/structured_data_worker.py`
- `backend/knowledge_system/conversion/*`
- `backend/knowledge_system/indexing/*`
- retrieval 相关测试。

理由：

- 这些是领域执行器，不是 capability catalog。
- 保留在 capability_system 会让能力目录变成执行系统。

### 4.6 Agent Capability Runtime

迁移：

- `backend/capability_system/agent_capabilities/deepsearch/*`
  -> `backend/knowledge_system/deepsearch/*`
- `backend/capability_system/agent_capabilities/codebase_search/*`
  -> `backend/knowledge_system/codebase_search/*`

边界：

- 如果这些能力由 agent runtime 调用，则应作为 knowledge service 注入 runtime。
- capability catalog 只展示它们的 manifest 和 operation dependency。

### 4.7 Search Policy

迁移或删除：

- `backend/capability_system/search_policy.py`
  -> `backend/runtime/context_management/search_policy.py`

修复：

- 当前 `operation_allowed_by_search_policy()` 对未知 operation fail-open。
- 新策略必须从 `permissions.operations.OperationDescriptor.metadata/source_class` 派生。
- 未知 operation 在策略过滤场景中默认 fail-closed，除非显式声明 `source_class="general"`。

### 4.8 Permission View

删除：

- `backend/capability_system/permission_views.py`

替代：

- 管理 API 需要展示权限状态时，调用 `permissions` 提供的只读 projection。
- capability projection 不自己推断 `approval_state`。

### 4.9 Paths、Tool Packages、Supply 和 Projection 模型

补充迁移：

- `backend/capability_system/paths.py`
  拆分删除：
  - skill 路径 -> `backend/agent_system/skills/paths.py`
  - tool registry 路径 -> `backend/runtime/tool_runtime/paths.py`
  - MCP 资产路径 -> `backend/runtime/mcp/paths.py`
  - capability projection 不再拥有资产目录。
- `backend/capability_system/tool_packages.py`
  -> `backend/permissions/operation_packages.py`
- `ToolPackageSelection`
  由 `agent_system/profiles/runtime_profile_models.py` 从 `permissions.operation_packages` 引用，作为 agent profile 的 operation bundle 配置。
- `backend/capability_system/supply.py`
  -> `backend/harness/runtime/capability_supply.py`
- `backend/capability_system/capability_units.py`
  -> `backend/capability_system/unit_projection.py`，仅保留管理台 projection，不再计算权限状态。
- `backend/capability_system/endpoints.py`
  -> `backend/capability_system/endpoint_projection.py`
- `backend/capability_system/models.py`
  拆分：
  - projection 模型留在 `capability_system/catalog_models.py`
  - runtime supply 模型迁到 `harness/runtime/capability_supply.py`
- `backend/capability_system/validation.py`
  可留在 `capability_system/validation.py`，但只校验 catalog projection 结构，不引用旧 runtime 或 permissions 推断。

同步更新：

- `backend/agent_system/profiles/runtime_profile_models.py`
- `backend/agent_system/profiles/runtime_profile_registry.py`
- `backend/api/orchestration_catalog.py`
- `backend/runtime/tooling/capability_table_builder.py`
- `backend/api/files.py`
- `backend/bootstrap/app_runtime.py`

## 5. 重写后的目标权责链

```text
Agent/Profile/Task facts
-> permissions.operations.OperationRegistry
-> permissions.ResourcePolicy / OperationGate
-> runtime.tool_runtime.NativeToolRuntime definitions/instances
-> harness.runtime.assembly authorized tool projection
-> runtime.tool_runtime.ToolRuntimeExecutor
-> evidence/knowledge/domain workers
-> capability_system.catalog_projection management view
```

关键约束：

- `capability_system` 位于链路末端，只做展示聚合。
- `permissions` 是审批和风险事实权威。
- `runtime/tool_runtime` 是工具实例和执行权威。
- `harness/runtime/assembly` 是当前 turn 工具可见性投影权威。
- `knowledge_system/evidence` 是领域能力执行权威。

## 6. 实施阶段

### Phase 0：冻结基线和短期归档

动作：

1. 记录当前相关测试基线。
2. 打包旧目录到 `archives/refactor/capability_system_legacy_20260602.zip`。
3. 将旧 `backend/capability_system` 改名移出 import 路径。
4. 创建空的新 `backend/capability_system`，只放最小 `__init__.py`。

验证：

```powershell
python -m compileall -q backend
```

预期：

- 编译失败，暴露所有旧 import。
- 这一步只作为断点清单，不作为阶段交付结果。
- 后续 Phase 1-5 必须在同一实施轮次内逐步修复到编译通过。
- 不允许为了让 Phase 0 通过而添加兼容 re-export。

### Phase 1：迁移 operation 权威

动作：

1. 新建 `backend/permissions/operations.py`。
2. 更新 `OperationGate`、runtime host、resource policy builder、tool control plane。
3. 删除 `capability_system.operation_registry` 旧 import。
4. 新增风险一致性测试。

新增测试：

```text
backend/tests/operation_registry_authority_regression.py
```

断言：

- 所有 tool definition 的 operation_id 都存在。
- 工具只读/destructive/concurrency 从 operation descriptor 派生。
- `python_repl` destructive 只有一个事实源。
- unknown operation 在 permission gate 中 fail-closed。

### Phase 2：迁移 tool runtime 声明和实例

动作：

1. 迁移 native tool catalog、tool runtime、authorization、contracts、validators、workspace file service。
2. 更新 `bootstrap/app_runtime.py`。
3. 更新 `harness/entrypoint/runtime_facade.py`。
4. 更新 `harness/runtime/assembly.py`。
5. 更新 `permissions/service.py`。
6. 更新 runtime executor 中对 tool contracts 的 import。
7. 更新 `runtime/shared/safety.py` 和 `runtime/tool_runtime/native_tools.py` 对 workspace file service、validators 的引用。
8. 更新 `runtime/tooling/capability_table_builder.py`，不再从 capability 包读取 tool definitions。

删除条件：

- `rg "capability_system.tool_" backend -g "*.py"` 无生产命中。

验证：

```powershell
python -m pytest backend/tests/base_toolset_regression.py backend/tests/tool_invocation_validation_regression.py backend/tests/sandbox_tool_runtime_regression.py backend/tests/runtime_tool_control_plane_regression.py -q
```

### Phase 3：迁移 skill registry 和 skill 资产

动作：

1. 迁移 skill registry/scanner/contracts/authoring。
2. 删除 `CapabilitySystemPaths` 对 skill 路径的职责，改为 `agent_system.skills.paths.AgentSkillPaths`。
3. 更新 `api/files.py` 对 skill 文件的允许路径。
4. 删除 `skill_policy.py`。
5. 删除旧 `skill_routes.py`，只保留 operation requirement 映射到新 skill contracts。
6. 更新 `bootstrap/app_runtime.py::refresh_indexes_for_path()`，不再监听 `capability_system/units/skills/`。

删除条件：

- `rg "capability_system.skill" backend -g "*.py"` 无生产命中。
- `rg "SkillPolicyResolver|skill_policy" backend -g "*.py"` 无命中。

验证：

```powershell
python -m pytest backend/tests/skills_registry_regression.py backend/tests/skill_contract_regression.py backend/tests/skill_route_mapping_regression.py backend/tests/capability_system_api_regression.py -q
```

### Phase 4：迁移 MCP 和领域执行器

动作：

1. 迁移 MCP client/server/management 到 `runtime/mcp`。
2. 迁移 local MCP registry。
3. 迁移 PDF/RAG/structured data 领域实现到 `knowledge_system`。
4. 更新 evidence workers 和 knowledge conversion/indexing imports。
5. 迁移 deepsearch/codebase_search。
6. 更新 `backend/api/mcp_system.py`，改从 `runtime.mcp` 读取 external MCP config 和 management service。
7. 更新 `backend/evidence/mcp_models.py`、`backend/evidence/orchestrator.py`、`backend/task_system/services/assembly_support.py` 对 local MCP registry 的引用。

删除条件：

- `rg "capability_system.units.mcp|capability_system.agent_capabilities" backend -g "*.py"` 无生产命中。

验证：

```powershell
python -m pytest backend/tests/pdf_local_first_regression.py backend/tests/pdf_page_state_regression.py backend/tests/retrieval_rebuild_regression.py backend/tests/retrieval_filter_execution_regression.py backend/tests/document_conversion_discovery_regression.py backend/tests/search_specialist_split_regression.py backend/tests/codebase_search_capability_regression.py -q
```

### Phase 5：重建 capability catalog projection

动作：

1. 新建最小 `capability_system/catalog_projection.py`。
2. 从以下来源只读聚合：
   - `permissions.operations`
   - `runtime.tool_runtime.native_tool_catalog`
   - `agent_system.skills.registry`
   - `runtime.mcp.registry`
   - `agent_system.registry`
3. 更新 `api/capability_system.py`。
4. 删除 `permission_views.py` 的推断逻辑，改由 permissions projection 提供。
5. 迁移 `capability_system/supply.py` 到 `harness/runtime/capability_supply.py`，API 只调用该 runtime supply projection。
6. 迁移 `capability_system/tool_packages.py` 到 `permissions/operation_packages.py`，并更新 agent profiles 和 orchestration catalog。
7. 新增 `agent_system.skills.paths`、`runtime.tool_runtime.paths`、`runtime.mcp.paths`，替代旧 `CapabilitySystemPaths`。

验证：

```powershell
python -m pytest backend/tests/capability_system_api_regression.py backend/tests/capability_endpoints_regression.py backend/tests/worker_operation_catalog_regression.py -q
```

### Phase 6：清除旧目录和归档

动作：

1. 删除短期旧目录归档。
2. 删除所有临时迁移脚本。
3. 删除旧测试中只保护旧目录形状的用例。
4. 全量扫描旧路径。

验证：

```powershell
rg -n "capability_system\\.(operation_registry|tool_definitions|tool_runtime|tool_authorization|tool_contracts|skill_registry|skill_scanner|skill_policy|search_policy|permission_views|local_mcp_registry|mcp_registry|mcp_adapter)|capability_system\\.units|capability_system\\.agent_capabilities" backend -g "*.py" -g "!**/__pycache__/**"
python -m compileall -q backend
```

预期：

- 扫描无命中。
- 编译通过。

## 7. 重点测试矩阵

### 控制系统主链路

```powershell
python -m pytest backend/tests/harness_runtime_facade_regression.py backend/tests/runtime_capability_state_regression.py backend/tests/task_environment_registry_regression.py backend/tests/graph_task_runtime_facade_regression.py -q
```

覆盖：

- harness runtime 仍能装配工具。
- allowed operations 正确限制工具可见性。
- graph node work order 不绕过 operation projection。
- runtime capability state 不依赖旧 capability package。

### 权限和工具执行

```powershell
python -m pytest backend/tests/permission_service_regression.py backend/tests/tool_scope_contract_regression.py backend/tests/tool_invocation_validation_regression.py backend/tests/runtime_tool_control_plane_regression.py backend/tests/sandbox_tool_runtime_regression.py -q
```

覆盖：

- operation gate fail-closed。
- 工具合同校验有效。
- sandbox side effect 仍受控。
- hidden/debug tools 不泄漏给 prompt。

### 能力管理 API

```powershell
python -m pytest backend/tests/capability_system_api_regression.py backend/tests/capability_endpoints_regression.py backend/tests/capability_system_preview_regression.py -q
```

覆盖：

- 管理页面 catalog 可用。
- skill 创建/保存/刷新走新路径。
- resource policy candidate 仍由 permissions 生成。

### 领域能力

```powershell
python -m pytest backend/tests/pdf_local_first_regression.py backend/tests/retrieval_rebuild_regression.py backend/tests/document_processing_policy_regression.py backend/tests/document_conversion_discovery_regression.py backend/tests/search_specialist_split_regression.py backend/tests/codebase_search_capability_regression.py -q
```

覆盖：

- PDF/RAG/结构化数据迁移后行为不变。
- deepsearch/codebase_search 不依赖旧 capability 包。

## 8. 不允许的实现方式

- 不允许在新 `capability_system` 中导入旧归档。
- 不允许用 `try/except ImportError` 兼容旧路径。
- 不允许降低测试断言来适配迁移。
- 不允许把权限审批事实继续复制在 tool definition、catalog projection 和 permission view 三处。
- 不允许让 capability catalog 决定当前 turn 的工具可见性。
- 不允许让 capability catalog 决定 search policy 是否放行。
- 不允许保留 `skill_policy.py` 作为“以后可能用”的旧路由。

## 9. 完成标准

必须同时满足：

1. `backend/capability_system` 只剩 catalog projection 和 API facade 所需模型。
2. `backend/capability_system` 不再包含 `units/`、`agent_capabilities/`、`mcp/`、`validators/`。
3. 生产代码不再 import：
   - `capability_system.operation_registry`
   - `capability_system.tool_definitions`
   - `capability_system.tool_runtime`
   - `capability_system.tool_authorization`
   - `capability_system.tool_contracts`
   - `capability_system.tool_packages`
   - `capability_system.skill_registry`
   - `capability_system.skill_scanner`
   - `capability_system.skill_policy`
   - `capability_system.search_policy`
   - `capability_system.permission_views`
   - `capability_system.paths`
   - `capability_system.units.*`
   - `capability_system.agent_capabilities.*`
4. `permissions.operations` 是 operation 风险和审批唯一事实源。
5. `runtime/tool_runtime` 是 tool definition、tool instance、tool execution 唯一事实源。
6. `agent_system/skills` 是 skill registry 和 skill asset 唯一事实源。
7. `knowledge_system/evidence` 是 PDF/RAG/structured data 执行唯一事实源。
8. 短期 legacy 归档已删除。
9. 迁移测试矩阵通过。
