# 权限系统技术报告

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [核心数据模型](#2-核心数据模型)
3. [操作注册体系（OperationRegistry）](#3-操作注册体系operationregistry)
4. [权限模式与策略（Policy）](#4-权限模式与策略policy)
5. [决策管线（Decision Pipeline）](#5-决策管线decision-pipeline)
6. [操作门系统（OperationGate）](#6-操作门系统operationgate)
7. [资源策略（ResourcePolicy）](#7-资源策略resourcepolicy)
8. [构建器体系](#8-构建器体系)
9. [工具作用域（ToolScope）](#9-工具作用域toolscope)
10. [工具包体系（ToolPackage）](#10-工具包体系toolpackage)
11. [服务层（PermissionService）](#11-服务层permissionservice)
12. [能力权限投影](#12-能力权限投影)
13. [完整数据流](#13-完整数据流)
14. [文件索引](#14-文件索引)
15. [技术细节汇总](#15-技术细节汇总)

---

## 1. 整体架构概览

权限系统是整个 Harness Runtime 的安全边界层，负责所有工具调用、操作执行和策略判断的权限裁决。系统采用 **四层过滤 + 门控 + 策略引擎** 的架构：

```
操作请求 → 权限模式过滤 → Agent Profile 过滤 → 资源策略过滤 → OperationGate → 最终许可
```

### 核心层次

| 层次 | 职责 | 对应模块 |
|------|------|---------|
| **操作注册层** | 定义所有可注册的操作及其元数据（风险标签、读写类型、安全校验器） | `operations.py` |
| **权限策略层** | 定义 5 种权限模式及工具准入规则 | `policy.py` |
| **作用域层** | 定义工具可见性边界（全局/Skill/Agent/会话/用户显式） | `tool_scope.py` |
| **决策管线层** | 工具级别权限裁决：scope → policy → 本地校验 | `decision_pipeline.py` |
| **资源策略层** | 操作级别 ResourcePolicy：允许/拒绝/需审批/不可执行 | `resource_policy.py` |
| **策略构建器层** | 候选策略和运行时准入策略的构建 | `resource_policy_builder.py`, `runtime_policy_builder.py` |
| **OperationGate** | 执行时刻的最终门控，集成资源策略、审批令牌、危险规则剥离、安全校验器 | `operation_gate.py` |
| **工具包层** | 按风险等级分组的操作包定义 | `operation_packages.py` |
| **能力目录投影** | 将权限状态附着到能力目录单元 | `capability_system/permission_projection.py` |
| **服务层** | 向外部提供统一权限查询接口 | `service.py` |

### 核心数据流

```
Task 任务合同 / Agent Profile
        │
        ▼
  resource_policy_builder.py ──→ ResourcePolicy (candidate)
        │
        ▼
  runtime_policy_builder.py ──→ ResourcePolicy (adopted, executable)
                                     + RuntimeDirective
        │
        ▼
  OperationGate.check() ──→ allow / deny / requires_approval
        │
        ▼
  ToolDispatcher / AuthorizedToolSet 执行或拒绝
```

---

## 2. 核心数据模型

### 2.1 PermissionDecision（`decision_models.py`）

**5 种裁决行为：**

| 行为 | 含义 | 用途 |
|------|------|------|
| `allow` | 允许执行 | 操作通过所有检查 |
| `deny` | 拒绝执行 | 操作被策略/Profile/未知拒绝 |
| `ask` | 需用户审批 | 高风险操作需人工授权 |
| `sandbox` | 沙盒中允许 | 在沙盒边界内写入/执行 |
| `repair` | 允许修复 | 系统内部修复操作 |

**5 级风险级别：** `none` / `low` / `medium` / `high` / `critical`

**关键字段：**
- `behavior: PermissionBehavior` — 裁决行为
- `operation_id: str` — 操作 ID
- `tool_name: str` — 关联工具名
- `reason: str` — 裁决理由
- `risk_level: PermissionRiskLevel` — 风险级别
- `approval_fingerprint: str` — 审批指纹
- `normalized_args: dict` — 规范化后的入参
- `diagnostics: dict` — 诊断信息
- `authority: str` — 裁决权威来源

**属性方法：**
- `allowed → bool` — `allow` 或 `sandbox`
- `requires_approval → bool` — `ask`
- `denied → bool` — `deny`

**工厂方法：** `allow()` / `deny()` / `ask()` / `sandbox()` / `repair()`

### 2.2 旧版 PermissionDecision（`models.py`）

简化版本（5 字段），用于 `decision_pipeline.py` 的工具级别裁决：

```python
@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason: str
    allowed_tools: list[str]
    tool_name: str | None
    mode: str
    checks: list[str]
    risk_tags: list[str]
```

### 2.3 PermissionContext（`context_models.py`）

权限上下文快照，包含 20+ 字段：
- `context_id` / `task_run_id` / `agent_run_id` / `environment_id`
- `tool_capability_table_id` / `file_access_table_ids`
- `session_approval_refs`
- `risk_policy_ref` / `execution_policy_ref`
- `permission_mode` — 当前权限模式
- `approval_state` / `sandbox_policy` / `file_management_policy`

### 2.4 PermissionReceipt（`receipt_models.py`）

权限裁决收据，不可变记录，通过 SHA256 生成唯一 `receipt_id`：
- 包含 `receipt_id` / `task_run_id` / `agent_run_id` / `tool_call_id`
- `behavior` / `approval_fingerprint` / `risk_level`
- 工厂方法 `from_decision()` 从 PermissionDecision 构造

### 2.5 ResourceDecision（`resource_policy.py`）

```python
ResourceDecisionKind = Literal["allow", "deny", "requires_approval", "not_executable", "unknown"]
```

### 2.6 ResourcePolicy（`resource_policy.py`）

**16 个关键字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `policy_id` | str | 策略 ID |
| `task_id` | str | 关联任务 ID |
| `allowed_operations` | tuple[str] | 允许的操作 |
| `denied_operations` | tuple[str] | 拒绝的操作 |
| `requires_approval_operations` | tuple[str] | 需审批的操作 |
| `not_executable_operations` | tuple[str] | 不可执行的操作 |
| `allowed_tools` / `denied_tools` | tuple[str] | 工具白名单/黑名单 |
| `allowed_mcps` / `denied_mcps` | tuple[str] | MCP 路由白名单/黑名单 |
| `allowed_agents` / `denied_agents` | tuple[str] | Agent ID 白名单/黑名单 |
| `memory_read_scope` / `memory_write_scope` | str | 记忆读写范围 |
| `filesystem_scope` / `network_scope` / `shell_scope` | dict | 各维度作用域 |
| `approval_policy` | str | 审批策略 |
| `runtime_view_only` / `adopted` / `runtime_executable` | bool | 运行时状态标志 |
| `decisions` | tuple[ResourceDecision] | 各操作的具体决策明细 |

---

## 3. 操作注册体系（OperationRegistry）

### 3.1 OperationDescriptor（`operations.py`）

**28 个元数据字段**描述每个操作：

| 类别 | 字段 | 示例值 |
|------|------|--------|
| 标识 | `operation_id`, `aliases` | `"op.read_file"`, `["read_file"]` |
| 分类 | `operation_type` | filesystem / network / vcs / shell / mcp / memory / agent / session / artifact / code_intelligence / browser / multimodal / analysis |
| 描述 | `title`, `capability_summary` | "Read file", "Read task-relevant local workspace files." |
| 来源 | `provider` | "builtin" |
| 契约 | `input_contract`, `output_contract`, `input_contract_ref`, `output_contract_ref` | `{"contract_ref": "op.read_file.input"}` |
| 风险 | `risk_tags` | `("read_only", "local_read")` |
| 行为 | `read_only`, `destructive`, `idempotent`, `open_world`, `concurrency_safe` | bool |
| 约束 | `requires_user_interaction`, `requires_approval_by_default` | bool |
| 容量 | `max_result_size_chars` | 5000~120000 |
| 中断 | `interrupt_behavior` | abort_safe / defer / checkpoint_then_abort / terminate_process |
| 加载 | `deferred_loading`, `always_load` | bool |
| 安全 | `safety_validator_ref` | `"filesystem_path"`, `"shell_read_only"` |
| 扩展 | `metadata` | 含 agent_id, required_operations, source_class, model_visible_tools 等 |

### 3.2 OperationRegistry（`operations.py`）

**核心方法：**
- `register(operation)` — 注册操作（含别名映射）
- `normalize_id(operation_id)` — 别名规范化
- `get_operation(operation_id)` — 获取操作描述
- `list_operations()` — 列出所有操作
- `export_manifest()` — 导出完整清单

### 3.3 内置操作清单

`default_operation_descriptors()` 返回约 **50 个**内置操作描述，覆盖以下分类：

**模型层：**
- `op.model_response` — 模型响应，always_load

**文件系统（只读）：**
- `op.read_file` — 文件读取（120KB）
- `op.search_files` / `op.search_text` — 搜索（80KB/120KB）
- `op.list_dir` / `op.stat_path` / `op.path_exists` — 目录/路径
- `op.glob_paths` — Glob 匹配
- `op.read_structured_file` — 结构化文件读取
- `op.read_persisted_tool_result` — 持久化工具结果恢复

**代码智能（只读，基于 Python ast）：**
- `op.python_code_outline` / `op.python_parse_check` / `op.python_symbol_search`

**Agent 能力（只读，子 Agent 专用）：**
- `op.codebase_search` → agent:codebase_searcher
- `op.search_agent` → agent:web_researcher（DeepSearch）

**网络：**
- `op.web_search` — 网络搜索（open_world）
- `op.fetch_url` — URL 抓取（open_world）
- `op.browser_control` — 浏览器控制（需审批）

**多模态：**
- `op.image_generate` — 图像生成

**版本控制（只读）：**
- `op.git_status` / `op.git_diff` / `op.git_log` / `op.git_show` / `op.git_branch_list`

**版本控制（写入，需审批）：**
- `op.git_branch_create` / `op.git_stage` / `op.git_unstage` / `op.git_commit`
- `op.git_restore` — 标记为 destructive
- `op.git_push` — 风险: git_write + remote_write + network

**文件系统（写入，需审批）：**
- `op.write_file` / `op.edit_file`

**Shell 执行（高风险）：**
- `op.shell` — destructive, shell_execution
- `op.python_repl` — destructive, python_execution

**记忆系统：**
- `op.memory_read` — 记忆读取
- `op.memory_write_candidate` — 记忆写入候选（需审批）

**MCP 本地能力：**
- `op.mcp_retrieval` — 知识检索
- `op.mcp_pdf` — PDF 分析
- `op.mcp_structured_data` — 结构化数据分析
- `op.mcp_image_ocr` — 图片 OCR

**会话/状态管理：**
- `op.agent_todo` — 任务待办
- `op.session_message_candidate` — 会话消息候选
- `op.artifact_result_ref` — 产物引用

**子 Agent 生命周期：**
- `op.subagent_spawn` / `op.subagent_message` / `op.subagent_wait` / `op.subagent_list` / `op.subagent_close`

**Agent 能力：**
- `op.agent_bounded` — 有界 Agent

---

## 4. 权限模式与策略（Policy）

### 4.1 五种权限模式

定义在 `policy.py`：

| 模式 | 策略行为 | 限制 |
|------|---------|------|
| `default` | 阻止 shell 和 destructive 标签的工具 | 默认模式 |
| `plan` | 仅允许只读工具，禁止 write/shell/destructive | 计划模式 |
| `accept_edits` | 仅阻止 destructive 标签的工具 | 接受编辑模式 |
| `full_access` | 允许所有工具 | 完全访问 |
| `bypass` | 无限制允许所有工具 | 绕过模式 |

### 4.2 mode_allows_tool 判断规则

```python
def mode_allows_tool(definition: ToolDefinition, *, mode: str) -> tuple[bool, str]:
    # bypass → 无条件允许
    # full_access → 无条件允许
    # plan → 只允许 read_only 且无 write/shell/destructive 标签
    # default → 阻止 shell 和 destructive
    # accept_edits → 仅阻止 destructive
```

### 4.3 模型可见操作控制

定义在 `model_visible_operations.py`：

```python
MODEL_VISIBLE_AGENT_OPERATIONS = frozenset()        # 当前无模型可见的 Agent 操作
MODEL_VISIBLE_STATE_OPERATIONS = frozenset({"op.agent_todo"})  # 仅 agent_todo 可见
```

---

## 5. 决策管线（Decision Pipeline）

### 5.1 工具权限决策 `decide_tool_permission()`

这是工具级别的权限裁决入口，管线顺序：

```
1. 规范化权限模式
2. 路由可用性检查（direct_route 时，仅 safe_for_auto_route 的 read_file 通过）
3. 作用域检查（ToolScope.allows）
4. 策略检查（mode_allows_tool）
5. 本地输入校验（工具实例的 validate_permission / validate_input）
6. 全部通过 → PermissionDecision(allowed=True)
7. 任何一步失败 → PermissionDecision(allowed=False, reason=...)
```

### 5.2 自动路由白名单

`_allows_explicit_read_only_direct_route()` 仅对 `read_file` 操作且 `read` 标签存在时放行。

### 5.3 工具列表过滤 `list_allowed_tool_names()`

根据权限模式和工具作用域，从 ToolDefinition 列表中筛选允许的工具名。

---

## 6. 操作门系统（OperationGate）

### 6.1 OperationGate（`operation_gate.py`）

执行时刻的最终门控，操作级权限裁决。

**门控管线（`_check_pipeline`）：**

```
1. 操作是否存在 → 不存则 deny (fail_closed)
2. directive_ref 是否存在 → 缺失则 deny
3. ResourcePolicy 是否存在 → 缺失则 deny
4. ResourcePolicy 是否已采纳且可执行 → 否则 deny
5. 拒绝追踪是否触发（连续3次/累计20次）→ 触发则 deny（断路器模式）
6. 操作是否在资源策略的拒绝列表 → 是则 deny
7. 操作是否在需审批列表 → 检查审批令牌
8. 操作是否在允许列表 → 不在则 deny
9. 危险允许规则剥离（auto 模式下阻止 destructive/shell/write 等）
10. 操作安全校验器（safety_validator_ref）
11. 全部通过 → allow
```

### 6.2 审批系统

**ApprovalToken：** 已授予的审批令牌，包含 `token_id` / `operation_id` / `directive_ref` / `granted` / `source` / `risk_fingerprint`

**ApprovalState：** 可序列化的审批快照，`find_granted_token()` 按 operation_id + directive_ref + risk_fingerprint 匹配

**审批裁决规则：**
- full_access / bypass 模式跳过审批
- dont_ask / headless 模式下不可用审批时直接 deny
- 审批令牌不匹配时 deny
- 交互式 UI 可用时返回 requires_approval

### 6.3 拒绝追踪（断路器）

```python
class DenialTrackingState:
    max_consecutive_denials = 3    # 连续拒绝上限
    max_total_denials = 20         # 累计拒绝上限
    tripped → 任一条件达到即触发
```

### 6.4 危险允许规则剥离

在 `auto` 权限模式下，自动移除带有 `shell_execution` / `python_execution` / `local_write` / `destructive` / `network_open_world` 标签的操作的允许资格。

### 6.5 操作安全校验器

通过 `safety_validator_ref` 从上下文中获取校验器实例，对操作输入进行安全检查：
- `filesystem_path` — 文件系统路径安全校验
- `shell_read_only` — Shell 只读安全校验
- 校验器不可用时 fail_closed（deny）

---

## 7. 资源策略（ResourcePolicy）

### 7.1 三类状态标志

| 标志 | 含义 |
|------|------|
| `runtime_view_only` | 仅运行时视图，不可执行 |
| `adopted` | 已被运行时采纳 |
| `runtime_executable` | 可在运行时执行 |

只有 `adopted=True` 且 `runtime_executable=True` 的策略才能通过 OperationGate。

### 7.2 操作到资源作用域的映射

`resource_scope_mapping.py` 中的 `map_operations_to_resource_scopes()` 将操作 ID 映射到：

| 资源类型 | 映射目标 | 示例 |
|---------|---------|------|
| tool | 工具名 | `op.read_file` → `read_file` |
| mcp | MCP 路由 | `op.mcp_pdf` → `pdf://local` |
| agent | Agent ID | `op.codebase_search` → `agent:codebase_searcher` |
| unmapped | 未映射操作 | 未识别的操作 ID |

内置操作-工具映射表 `_BUILTIN_OPERATION_TO_TOOL` 覆盖约 40 个映射关系。

---

## 8. 构建器体系

### 8.1 候选资源策略构建（`resource_policy_builder.py`）

`build_resource_policy_candidate()` 从 `OperationRequirement` 构建候选 `ResourcePolicy`：

**决策链：**

```
OperationRequirement
    │
    ├─ required_operations → 逐个裁决
    ├─ optional_operations → 逐个裁决
    └─ denied_operations → 强制拒绝
```

**对每个操作的裁决逻辑（`_decide_operation`）：**

```
1. 操作是否注册 → 未知则 deny
2. 是否显式拒绝 → deny
3. 是否带默认拒绝风险标签（memory_write_candidate 等）→ deny（模型可见状态操作除外）
4. auto 审批策略下是否带危险自动风险标签 → deny
5. 是否模型可见 Agent 操作 → allow
6. 操作类型是否 mcp/agent → not_executable
7. 审批策略是否要求人工门控 → requires_approval / deny（headless）
8. 审批策略是否拒绝 destructive → deny
9. 默认需审批且 headless → deny
10. 默认 → allow（candidate）
```

**审批渠道决议：**
- interactive_ui_available → "ui_approval"
- approval_hook_available → "approval_hook"
- bubble_to_parent_allowed → "parent_approval"
- headless_mode → "deny"

### 8.2 运行时准入策略构建（`runtime_policy_builder.py`）

`build_model_response_runtime_admission()` 将候选策略转为运行时可执行策略 + RuntimeDirective：

**输入：**
- `task_operation` — 任务操作需求（含 task_contract, execution_permit 等）
- `operation_registry` — 操作注册表
- `agent_runtime_profile` — Agent 运行时 Profile
- `approval_context` — 审批上下文
- `sandbox_policy` — 沙盒策略
- `permission_mode` — 权限模式

**输出：**
- `RuntimeDirective` — 运行时指令（含 adopted_resource_policy_ref）
- `ResourcePolicy` — 已采纳的、可执行的资源策略

**运行时决策（`_decide_runtime_operation`）：**

```
1. 操作在 profile blocked 中 → deny
2. 操作不在 profile allowed 中（且非模型可见状态操作）→ deny
3. 操作未注册 → deny
4. 模型可见 Agent 操作 → allow
5. 模型可见状态操作 → allow
6. mcp/agent 类型 → not_executable
7. full_access / bypass 模式 → allow
8. task_bounded_write 审批策略 + write_file/edit_file → allow
9. 沙盒允许副作用 → allow
10. 显式人工审批 → requires_approval / deny（headless）
11. destructive 被审批策略拒绝 → deny
12. 默认 → allow
```

### 8.3 运行时能力状态构建

`build_runtime_capability_state()` 构建一个能力层描述对象，包含：
- 当前轮次请求 / 已准入的操作
- Profile 允许 / 阻止的操作
- 需要审批的操作
- 文件写入能力状态
- 沙盒策略快照

---

## 9. 工具作用域（ToolScope）

### 9.1 ToolScope（`tool_scope.py`）

**作用域来源 5 种：**

```python
ToolScopeSource = Literal["global", "skill", "agent", "session", "explicit_user"]
```

**信任级别 5 级：**

```python
ToolScopeTrustLevel = Literal["system", "project", "user", "external", "unknown"]
```

**核心字段：**
- `allowed_tools` — 允许的工具白名单（空=不限制）
- `denied_tools` — 拒绝的工具黑名单
- `capability_constraints` — 能力约束
- `has_allowed_filter → bool` — 是否有白名单过滤

**裁决方法 `allows(tool_name)`：**
1. 工具在黑名单中 → False
2. 有白名单且工具不在白名单中 → False
3. 其余 → True

### 9.2 SkillToolScope

继承 ToolScope，额外字段：
- `skill_name` — 关联 Skill 名称
- `activation_policy` — 激活策略（默认 `model_visible`）
- `context_mode` — 上下文模式（默认 `inline`）

---

## 10. 工具包体系（ToolPackage）

### 10.1 ToolPackageDefinition（`operation_packages.py`）

内置 **16 个工具包**，覆盖所有操作风险等级：

| 包 ID | 标题 | 风险等级 | 默认启用 | 包含的操作 |
|-------|------|---------|---------|-----------|
| `pkg.filesystem.read` | 文件只读 | 低 | ✅ | read_file, list_dir, glob_paths 等 7 个 |
| `pkg.filesystem.write` | 文件写入 | 高 | ✅ | write_file, edit_file |
| `pkg.search.local` | 本地搜索 | 低 | ✅ | search_files, search_text |
| `pkg.development.python` | Python 开发工具 | 低 | ✅ | codebase_search, python_code_outline 等 8 个 |
| `pkg.git.read` | Git 只读 | 低 | ✅ | git_status, git_diff, git_log, git_show, git_branch_list |
| `pkg.git.write` | Git 写入 | 高 | ✅ | git_branch_create, git_stage, git_unstage, git_commit, git_restore |
| `pkg.git.remote` | Git 远端 | 极高 | ❌ | git_push |
| `pkg.web` | 网络查询 | 中 | ✅ | web_search, fetch_url |
| `pkg.memory` | 记忆读取 | 低 | ✅ | memory_read |
| `pkg.agent` | Agent 状态 | 低 | ✅ | agent_todo |
| `pkg.subagent.lifecycle` | 子 Agent 生命周期 | 高 | ❌ | spawn_subagent 等 5 个 |
| `pkg.execution` | 本地执行 | 极高 | ❌ | shell, python_repl |
| `pkg.multimodal` | 多模态生成 | 高 | ✅ | image_generate |
| `pkg.mcp.local` | 本地能力端点 | 中 | ✅ | mcp_retrieval, mcp_pdf, mcp_structured_data, mcp_image_ocr |

### 10.2 工具包选择机制

**ToolPackageSelection：** 包含 `package_id` / `enabled` / `include_operations` / `exclude_operations`

**核心函数：**
- `parse_tool_package_selection()` — 从字符串或字典解析选择
- `resolve_tool_package_operations()` — 根据选择解析出最终的操作列表
- `default_tool_package_map()` — 获取包 ID 到定义映射

---

## 11. 服务层（PermissionService）

### 11.1 PermissionService（`service.py`）

单一对外服务类，集成 `decision_pipeline` 和 `ToolRuntime`：

**方法：**
- `current_mode() → str` — 获取当前权限模式（从配置服务）
- `supported_modes() → list[str]` — 支持的模式列表
- `allowed_tool_names(allowed_tools) → list[str]` — 在权限模式下允许的工具名
- `can_invoke_tool(tool_name, ...) → PermissionDecision` — 工具调用权限裁决

---

## 12. 能力权限投影

### 12.1 能力权限视图（`capability_system/permission_projection.py`）

将权限状态附着到能力目录单元：

`build_capability_permission_views(units)` 为每个能力单元构建 `CapabilityPermissionView`：

| 视图字段 | 说明 |
|---------|------|
| `profile_state` | Profile 状态（not_checked / allowed / blocked） |
| `adoption_state` | 采纳状态 |
| `gate_state` | 门控状态 |
| `approval_state` | 审批状态：`not_required` / `policy_dependent` |
| `sandbox_state` | 沙盒状态 |
| `reasons` | 决策原因集合 |

**自动判断规则：**
- 风险包含 `local_write` / `shell_execution` / `python_execution` / `destructive` / `network_open_world` 时 → `policy_dependent`
- 否则 → `not_required`

---

## 13. 完整数据流

### 13.1 工具调用权限流

```
用户/模型请求调用工具
        │
        ▼
PermissionService.can_invoke_tool()
        │
        ├─ 工具名存在性检查
        │
        ▼
decide_tool_permission()  ── 工具级别
        │
        ├─ 路由可用性 (direct_route)
        ├─ 作用域检查 (ToolScope)
        ├─ 模式策略 (mode_allows_tool)
        └─ 本地输入校验 (tool.validate_permission)
        │
        ▼
PermissionDecision (allowed=True/False)
```

### 13.2 操作执行权限流

```
运行时调度操作
        │
        ▼
OperationGate.check()
        │
        ├─ 操作存在性
        ├─ directive_ref
        ├─ ResourcePolicy 存在 + 已采纳 + 可执行
        ├─ 拒绝追踪断路器
        ├─ 拒绝列表检查
        ├─ 审批令牌检查
        ├─ 允许列表检查
        ├─ 危险允许规则剥离（auto 模式）
        └─ 操作安全校验器
        │
        ▼
OperationGateResult (allow/deny/requires_approval)
```

### 13.3 运行时准入流

```
Task 启动 / Agent 轮次开始
        │
        ▼
build_model_response_runtime_admission()
        │
        ├─ 聚合 task_contract / execution_permit / agent_runtime_profile
        ├─ 逐个操作裁决 (_decide_runtime_operation)
        ├─ 映射操作到资源作用域
        └─ 产出 RuntimeDirective + ResourcePolicy
        │
        ▼
运行时通过 OperationGate 消费 ResourcePolicy
```

### 13.4 资源策略候选构建流

```
OperationRequirement (来自 Skill/Task 合同)
        │
        ▼
build_resource_policy_candidate()
        │
        ├─ required_operations → 裁决
        ├─ optional_operations → 裁决
        ├─ denied_operations → 强制拒绝
        ├─ 审批策略判断
        └─ 映射操作到资源作用域
        │
        ▼
ResourcePolicy (candidate, runtime_view_only=True)
```

---

## 14. 文件索引

| 文件 | 大小 | 核心类/函数 |
|------|------|------------|
| `__init__.py` | 3.2 KB | 模块导出清单（28 项） + `__getattr__` 惰性导入 |
| `models.py` | 418 B | `PermissionDecision`（旧版） |
| `decision_models.py` | 4.2 KB | `PermissionDecision`（新版，5 行为） |
| `decision_pipeline.py` | 5.0 KB | `decide_tool_permission()`, `list_allowed_tool_names()` |
| `context_models.py` | 1.3 KB | `PermissionContext` |
| `receipt_models.py` | 2.5 KB | `PermissionReceipt` |
| `policy.py` | 1.4 KB | 5 种权限模式, `mode_allows_tool()`, `normalize_permission_mode()` |
| `operations.py` | 29.6 KB | `OperationDescriptor`（28 字段）, `OperationRegistry`, `default_operation_descriptors()`（~50 操作） |
| `operation_gate.py` | 15.7 KB | `OperationGate`（门控管线）, `ApprovalToken`, `ApprovalState`, `DenialTrackingState`, `OperationGatePipelineContext` |
| `operation_packages.py` | 11.1 KB | `ToolPackageDefinition`（16 包）, `ToolPackageSelection`, `resolve_tool_package_operations()` |
| `resource_policy.py` | 1.8 KB | `ResourceDecision`, `ResourcePolicy`（16 字段） |
| `resource_policy_builder.py` | 11.1 KB | `build_resource_policy_candidate()`, `RuntimeApprovalContext` |
| `resource_scope_mapping.py` | 4.6 KB | `ResourceScopeMapping`, `map_operations_to_resource_scopes()` |
| `runtime_policy_builder.py` | 21.9 KB | `build_model_response_runtime_admission()`, `build_runtime_capability_state()`, `_decide_runtime_operation()` |
| `service.py` | 2.0 KB | `PermissionService` |
| `tool_scope.py` | 2.5 KB | `ToolScope`, `SkillToolScope`, `coerce_tool_scope()` |
| `model_visible_operations.py` | 451 B | `is_model_visible_agent_operation()`, `is_model_visible_state_operation()` |
| `capability_system/permission_projection.py` | 3.3 KB | `build_capability_permission_views()`, `attach_capability_permission_views()` |

---

## 15. 技术细节汇总

### 代码规模

| 度量 | 数值 |
|------|------|
| 总源文件数 | 17（权限系统） + 3（能力权限投影） |
| 核心模块代码量 | ~115 KB |
| 最大文件 | `operations.py`（29.6 KB / 786 行） |
| 内置操作数量 | ~50 个操作描述符 |
| 内置工具包数量 | 16 个 |

### 权限模式

| 模式 | 数量 | 行为 |
|------|------|------|
| 标准模式 | `default`, `plan`, `accept_edits`, `full_access`, `bypass` | 5 种 |
| 扩展模式 | `dont_ask`, `headless`（OperationGate 专用） | 2 种 |

### 裁决行为体系

| 层 | 裁决类型 | 数量 |
|----|---------|------|
| OperationGate 最终裁决 | allow / deny / requires_approval | 3 种 |
| PermissionDecision（新版） | allow / deny / ask / sandbox / repair | 5 种 |
| ResourceDecision | allow / deny / requires_approval / not_executable / unknown | 5 种 |

### 安全机制

| 机制 | 说明 |
|------|------|
| **fails-closed** | 操作不存在 / 策略缺失 / 校验器不可用时默认拒绝 |
| **断路器** | 连续 3 次或累计 20 次拒绝后触发熔断 |
| **输入校验** | 工具实例的 `validate_permission()` / `validate_input()` 方法 |
| **安全校验器** | 通过 `safety_validator_ref` 引用路径/Shell 校验器 |
| **危险规则剥离** | auto 模式下禁止所有高风险操作 |
| **审批指纹** | 操作指纹匹配确保审批不能跨操作复用 |
| **作用域隔离** | 5 种来源 + 5 级信任 + 白名单/黑名单 |

### 审批体系

| 审批项 | 配置方式 |
|--------|---------|
| 工具包级 | `requires_approval_by_default` |
| Task 级 | `approval_policy` 字段 |
| Profile 级 | `agent_runtime_profile.approval_policy` |
| 运行时上下文 | `RuntimeApprovalContext`（交互式/headless/hook） |

### 资源映射关系

| 操作类型 | 映射目标 | 示例 |
|---------|---------|------|
| filesystem / vcs / network / shell / state | 工具名 | `read_file`, `git_status` |
| mcp / external_mcp | MCP 路由 | `local_mcp_pdf` |
| agent / agent_capability | Agent ID | `agent:codebase_searcher` |
| model | 模型响应 | 直接放行 |
| session / artifact | 候选操作 | 拒绝或需审批 |
| code_intelligence / browser / multimodal / analysis | 工具名 | `python_code_outline`, `image_generate` |

### 审计与可追溯性

| 机制 | 说明 |
|------|------|
| **PermissionReceipt** | 每次工具调用的权限裁决收据，含 SHA256 指纹 |
| **DenialTrackingState** | 拒绝历史追踪（连续 + 累计） |
| **ApprovalState** | 可序列化的审批快照，支持 HarnessCheckpoint 持久化 |
| **diagnostics** | 每个裁决都携带诊断上下文，包含 fail_closed 状态和详细原因 |
| **决策明细** | ResourcePolicy 的 `decisions` 字段记录每个操作的完整裁决链 |
