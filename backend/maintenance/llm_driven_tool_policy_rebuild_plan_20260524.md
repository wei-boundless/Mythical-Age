# LLM 驱动工具策略改造计划书 - 2026-05-24

## 1. 技术源报告

### 1.1 当前真实问题

当前专业长任务已经具备部分正确能力：

- `ModelTurnDecision` 已由主模型真实输出，包含 `task_goal_type` 与 `resource_contract`。
- sandbox 已能把源项目挂载到 `.materials/source_projects/source_01/`。
- `agent_todo` 已作为模型可见工具进入长任务轮次。
- `ToolObservationLedger` 已能记录读、写、验证、委派观察。
- `OperationGate` 已存在，负责 operation 级 allow / deny / approval。

但当前专业任务运行时出现了结构性偏差：

```text
goal_contract
  -> required_action_queue
  -> required_next_tools
  -> 缩窄模型可见工具
  -> _contract_gate_tool_request 按 current_action 拦截工具
  -> recovery prompt 要求“下一步只能使用某工具”
```

这已经从“模型自主选择工具，runtime 做工具级校验”滑向了“runtime required-action 状态机调度模型”。

这个方向和 Claude Code 源码中的成熟制式不一致。

### 1.2 Claude Code 源码确认的执行制式

本次参考的本地源码目录：

- `D:\AI应用\claude-code-nb-main`

关键结论：

```text
Claude Code = LLM-driven ReAct loop
            + tool schema
            + tool prompt
            + validateInput
            + canUseTool / hasPermissionsToUseTool
            + Tool.checkPermissions
            + Tool.call
            + tool_result feedback
            + durable session state
```

不是：

```text
runtime required_action_queue 决定下一步只能调用某个工具。
```

源码依据：

- `hooks/useCanUseTool.tsx`
  - `useCanUseTool()` 在模型产生 tool_use 后调用 `hasPermissionsToUseTool()`。
  - 位置：`D:\AI应用\claude-code-nb-main\hooks\useCanUseTool.tsx`

- `utils/permissions/permissions.ts`
  - `hasPermissionsToUseTool()` 是权限总入口。
  - 它按 deny rule、ask rule、tool-specific check、permission mode、allow rule、classifier / prompt 等顺序决策。
  - 位置：`D:\AI应用\claude-code-nb-main\utils\permissions\permissions.ts`

- `Tool.ts`
  - Tool 接口明确区分 `validateInput()`、`checkPermissions()`、`call()`、`mapToolResultToToolResultBlockParam()`。
  - 位置：`D:\AI应用\claude-code-nb-main\Tool.ts`

- `tools/FileWriteTool/FileWriteTool.ts`
  - Write 工具有自己的路径权限检查、已读校验、mtime 防并发覆盖校验、写入后状态更新。
  - 位置：`D:\AI应用\claude-code-nb-main\tools\FileWriteTool\FileWriteTool.ts`

- `tools/TodoWriteTool/TodoWriteTool.ts`
  - Todo 是模型可调用工具，不是后端伪造计划。
  - 位置：`D:\AI应用\claude-code-nb-main\tools\TodoWriteTool\TodoWriteTool.ts`

- `tools/ExitPlanModeTool/ExitPlanModeV2Tool.ts`
  - Plan mode 是 permission mode / 用户确认机制，不是任务步骤执行图。
  - 位置：`D:\AI应用\claude-code-nb-main\tools\ExitPlanModeTool\ExitPlanModeV2Tool.ts`

### 1.3 本项目当前偏差

本项目相关文件：

- `backend/runtime/professional_runtime/tool_contract_gate.py`
- `backend/runtime/professional_runtime/required_action_queue.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/memory/tool_observation_ledger.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/permissions/operation_gate.py`
- `backend/runtime/unit_runtime/loop.py`

当前偏差不是没有 gate，而是 gate 的职责错位：

1. `required_action_queue.py` 把缺失产物编译成 `current_action`，并输出“当前强制动作”。
2. `tool_contract_gate.py` 根据 `current_action` 直接拒绝 `read_file`、`terminal`、`delegate_to_agent`。
3. `driver.py` 每轮根据 `_next_required_tools()` 缩窄 `round_model_tool_instances`。
4. recovery prompt 写成“下一步只能使用这些真实工具”。
5. `ToolObservationLedger` 与 `ToolResultEnvelope` 仍有大量从文本正则反推路径、产物、验证的逻辑。

这些设计会造成：

- runtime 过度接管模型下一步工具选择。
- 工具策略与任务进度耦合过深。
- 非推进行为被当成 required action 违规，而不是作为 progress policy 纠偏。
- 证据层仍部分依赖文本摘要、路径正则和关键词。
- 计划/进度/权限/验证边界混在一起。

## 2. 推荐设计方向

采用 Codex 与 Claude Code 共同体现的成熟 agent 工具监管制式：

```text
Model-owned next action
Runtime-owned validation
Tool-owned schema and safety
Permission-owned operation gate
Sandbox-owned execution boundary
Approval-owned escalation
Ledger-owned evidence
Progress-owned non-progress correction
Validator-owned closeout
```

目标不是把 agent 变成步骤状态机，而是建立以下链路：

```text
用户请求
  -> ModelTurnDecision
  -> runtime assembly
  -> model sees tools + prompts + history + observations
  -> model emits tool_use
  -> tool input schema validation
  -> tool-specific validate
  -> operation permission gate
  -> sandbox / approval policy
  -> progress policy check
  -> tool execution
  -> structured tool_result envelope
  -> evidence ledger append
  -> model continues or closes out
  -> deliverable validator validates real artifacts
```

精确定义：

- 主模型决定下一步调用哪个工具。
- runtime 不替模型选工具，不把 `required_action_queue` 当调度器。
- runtime 必须拒绝非法、危险、越权、越过 sandbox、缺审批、重复无推进的工具调用。
- 被拒绝的工具调用必须作为 tool_result / observation 返回模型，让模型自己纠正。
- 产物是否完成只能由工具执行结果和结构化 evidence 判断。

核心原则不是“Claude Code 化”或“Codex 化”，而是二者共同的工程不变量：

```text
下一步由模型决定。
能否执行由 runtime 决定。
风险由 permission / sandbox / approval 决定。
产物是否成立由 evidence / validator 决定。
长任务是否绕圈由 progress policy 决定。
```

## 3. 目标架构

### 3.1 ModelTurnDecision

职责：

- 理解当前用户请求。
- 给出任务目标、工作模式、资源契约、交付物、约束。
- 不输出下一步工具调用。
- 不输出 runtime required action。

保留：

- `task_goal_type`
- `action_intent`
- `work_mode`
- `completion_criteria`
- `resource_contract`

禁止：

- 代码伪造模型决策。
- 用旧正则兜底生成硬资源义务。

### 3.2 Tool Definition

每个工具必须逐步补齐成熟本地 coding agent 的工具结构：

```text
name
operation_id
description / prompt
input_schema
output_schema
validate_input()
check_permissions()
call()
map_result_to_observation()
```

当前项目已有 capability registry、operation registry 和 LangChain tool，但工具级校验还不够制度化。

目标新增一层，位置固定为：

```text
backend/runtime/tool_runtime/tool_definition.py
```

不允许再写“或在现有 tool runtime 中定义”。本项目必须采用明确分层：

```text
capability_system.tool_definitions.ToolDefinition
  = 工具注册表元数据
  = name / operation_id / schema_identity / safety_tags / factory / visibility
  = 不承担 runtime validate / permission / call 协议

runtime.tool_runtime.tool_definition.RuntimeToolDefinition
  = 工具运行时协议
  = validate_input / check_permissions / call / map_result_to_observation
  = ToolRuntimeExecutor 唯一执行入口协议

runtime.tool_runtime.tool_adapter.RuntimeToolAdapter
  = 旧 LangChain BaseTool 到 RuntimeToolDefinition 的过渡适配器
  = 只允许作为迁移桥，不允许承载新工具核心逻辑
```

新增文件必须是：

```text
backend/runtime/tool_runtime/tool_definition.py
backend/runtime/tool_runtime/tool_adapter.py
backend/runtime/tool_runtime/tool_use_context.py
```

`tool_definition.py` 必须定义以下稳定对象：

```python
@dataclass(frozen=True, slots=True)
class ToolValidationResult:
    allowed: bool
    reason: str = ""
    repair_instruction: str = ""
    normalized_args: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolPermissionResult:
    allowed: bool
    decision: str
    reason: str = ""
    requires_approval: bool = False
    approval_fingerprint: str = ""
    repair_instruction: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class RuntimeToolDefinition(Protocol):
    name: str
    operation_id: str
    input_schema: Any
    output_schema: Any

    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ToolValidationResult: ...
    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult: ...
    def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope: ...
```

`tool_adapter.py` 只解决旧工具迁移：

```text
CapabilityToolDefinition + BaseTool instance
  -> RuntimeToolAdapter
  -> RuntimeToolDefinition
```

适配器职责：

- 从 capability `ToolDefinition.contract` 读取 required inputs。
- 调用旧 BaseTool 的 args schema 做基础参数校验。
- 若旧工具没有结构化结果，生成 `status=ok/error` 的 envelope，但 hard evidence 只能来自 tool args，不得从 result 文本正则推断。
- 对 `write_file`、`edit_file`、`terminal`、`read_structured_file` 这类核心工具，适配器只作为临时桥，必须在 Phase 3 内改成原生 runtime tool。

执行边界：

- `ToolRuntimeExecutor` 只能面向 `RuntimeToolDefinition` 执行。
- `capability_system.tool_definitions.ToolDefinition.build()` 可以暂时被 adapter 调用，但不能继续作为 executor 的直接执行协议。
- 新增工具不得再只继承 LangChain `BaseTool` 后直接进入执行器。

### 3.3 OperationGate

职责：

- operation 级权限。
- resource policy allow / deny。
- approval / headless / dangerous allow stripping。
- operation-specific safety validator。
- sandbox policy 只作为执行边界输入，不替代 permission decision。

保留并强化：

- `backend/permissions/operation_gate.py`

不允许它承担：

- 判断当前任务下一步该做什么。
- 判断模型是否“应该先写 game.js”。

### 3.3.1 Sandbox / Approval Boundary

Codex 的强项是 sandbox 与 approval mode，Claude Code 的强项是工具级权限与交互式 permission flow。本项目要把这两类边界分清：

```text
PermissionGate:
  判断 operation 是否允许。

SandboxPolicy:
  判断允许的 side effect 实际落在哪个隔离工作区。

ApprovalPolicy:
  判断当前上下文是否需要用户批准，headless 时是否 fail closed。

ProgressPolicy:
  判断工具调用是否长期不推进任务。
```

禁止把这四层混成一个“任务阶段调度器”。

目标执行顺序：

```text
validate_input
  -> operation permission
  -> sandbox boundary
  -> approval fingerprint / escalation
  -> progress policy
  -> execute
```

如果 sandbox 或 approval 拒绝，返回模型可见 observation：

```json
{
  "type": "tool_policy_rejection",
  "policy": "sandbox_or_approval",
  "reason": "requested path is outside sandbox write scope",
  "repair_instruction": "请改用当前工作区内允许的相对路径，或说明需要用户批准的具体原因。"
}
```

### 3.3.2 Runtime Environment Boundary

环境不是附属问题。当前长任务反复出现掉线、超时、工具权限重复询问、前后端端口漂移，本质上会污染 agent 行为判断：模型看起来像理解错了，实际可能是 runtime 入口、SSE、sandbox、approval 或工具上下文断了。

环境层必须成为明确的 runtime boundary，而不是开发时临时经验。

固定本地节点：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api base: http://127.0.0.1:8003/api
```

禁止：

- 前端失败后临时切到 `3001`、`3002`。
- 后端失败后临时切到 `8002`、`8004`、`8007`。
- Electron、Next 代理、浏览器直开、API base 各自维护不同默认端口。
- 因 `.next` 残留或旧进程冲突而绕开固定端口。

环境启动必须变成可检查入口：

```text
clean_frontend_start
  -> stop stale frontend process on 3000
  -> remove invalid .next state when needed
  -> start Next.js on 127.0.0.1:3000
  -> verify / health page reachable

clean_backend_start
  -> stop stale backend process on 8003
  -> start FastAPI/Uvicorn on 127.0.0.1:8003
  -> verify /api health reachable

runtime_connection_check
  -> frontend API base == http://127.0.0.1:8003/api
  -> SSE endpoint connected
  -> only one listener on 3000
  -> only one listener on 8003
```

目标新增：

```text
backend/runtime/environment/runtime_environment.py
backend/runtime/environment/port_guard.py
backend/runtime/environment/connection_health.py
```

职责：

- `RuntimeEnvironment` 保存固定端口、API base、浏览器策略、sandbox root、workspace root。
- `PortGuard` 检查端口是否被本项目旧进程占用，并给出明确诊断。
- `ConnectionHealth` 检查前端、后端、SSE、API base 是否一致。

注意：

- 环境检查不替模型决定任务。
- 环境失败不能伪造成模型理解失败。
- 环境失败必须返回明确 `runtime_environment_error`，包含端口、进程、API base、SSE 状态。
- 长任务启动前必须记录一次 environment snapshot，作为后续掉线排查依据。

### 3.3.3 Sandbox Entry Contract

当前 sandbox 已经有 `LocalOverlaySandboxBackend`，但入口还不够制度化。成熟结构里，sandbox 不是工具失败后的补丁，而是工具执行前的边界合同。

目标入口：

```text
ModelTurnDecision.resource_contract
  -> RuntimeEnvironment.workspace_root
  -> SandboxPolicy
  -> SandboxMountPlan
  -> ToolUseContext
  -> Tool.call()
```

必须明确：

- 哪些路径是只读材料。
- 哪些路径是允许写入产物。
- 哪些路径是继承资产目录。
- 哪些路径禁止写入。
- sandbox overlay 最终如何提交或展示产物。

禁止：

- 用宽泛正则从用户文本里猜材料路径作为硬合同。
- 工具执行时临时发现路径不存在才补 material mount。
- write_file 自己决定能不能越过 sandbox。

目标新增或改造：

```text
backend/runtime/tool_runtime/sandbox_policy.py
backend/runtime/tool_runtime/sandbox_mount_plan.py
backend/runtime/tool_runtime/tool_use_context.py
```

`ToolUseContext` 至少包含：

```python
workspace_root: Path
sandbox_root: Path | None
read_scopes: tuple[str, ...]
write_scopes: tuple[str, ...]
material_mounts: tuple[dict[str, Any], ...]
artifact_root: str
approval_policy: str
permission_mode: str
environment_snapshot: dict[str, Any]
```

### 3.3.4 Approval and Tool Permission Entry

当前 `OperationGate` 已能处理 approval，但工具调用链里仍存在“系统名单一次、调用时又问一次”的体验问题。成熟结构不是取消二次检查，而是把两次检查分层：

```text
Tool visibility:
  本轮模型能看到哪些工具。

Tool execution permission:
  模型真的请求某个工具后，这次调用是否允许执行。
```

必须做到：

- 工具可见性只决定“模型能不能看见工具”。
- 工具执行权限只决定“这次调用能不能执行”。
- 同一条 operation 的 approval token 必须绑定 `operation_id + directive_ref + risk fingerprint`。
- 已批准且 fingerprint 未变的调用不能重复要求权限。
- fingerprint 变化、路径越界、风险升级时必须重新进入 approval。
- approval fingerprint 是 `OperationGate` 的输入，不是 `OperationGate.allow` 之后的第二套门禁。
- `OperationGate` 统一输出 `allow / deny / requires_approval`，工具层只补充工具特定风险诊断。

目标新增：

```text
backend/runtime/execution_permit/approval_fingerprint.py
backend/runtime/execution_permit/approval_cache.py
```

拒绝或等待审批时，返回模型可见 observation：

```json
{
  "type": "tool_policy_rejection",
  "policy": "approval",
  "decision": "requires_approval",
  "operation_id": "op.write_file",
  "reason": "write operation requires approval for this path",
  "repair_instruction": "请等待用户批准；如果要继续，可选择只读检查或说明阻塞原因。"
}
```

### 3.3.5 Long Task Runtime Cadence

长任务必须有阶段性可见输出，否则用户会以为 agent 掉线，runtime 也难以区分模型卡住、工具卡住、SSE 卡住还是验证卡住。

新增 long-task cadence：

```text
stage heartbeat every 30-60 seconds
  -> current phase
  -> last model action
  -> last tool result
  -> new artifacts
  -> current blockers
  -> next intended area, if known from model-visible todo/progress
```

注意：

- 阶段总结不是最终交付。
- 阶段总结不能伪造产物。
- 阶段总结只来自 event log、ledger、todo state、environment snapshot。
- 模型超时后，runtime 应生成 `runtime_timeout_observation`，让模型在下一轮继续，而不是直接丢弃任务。

目标新增：

```text
backend/runtime/professional_runtime/stage_summary.py
backend/runtime/professional_runtime/timeout_recovery.py
```

阶段总结结构：

```json
{
  "type": "stage_summary",
  "task_run_id": "...",
  "elapsed_seconds": 90,
  "completed_actions": [],
  "artifact_refs": [],
  "latest_tool": "write_file",
  "latest_result": "ok",
  "current_blocker": "",
  "environment": {
    "frontend": "127.0.0.1:3000",
    "backend": "127.0.0.1:8003",
    "sse": "connected"
  }
}
```

### 3.4 Progress Policy

新增概念：

```text
ProgressPolicy
```

职责：

- 观察模型连续工具调用是否推进当前任务。
- 不决定正常下一步。
- 只在明确非推进时拒绝继续绕圈。

示例规则：

```text
如果缺失 deliverable = game.js，
且材料读取已满足，
且最近 N 次工具调用都是 read/search/terminal/list，
且没有新增 observed_paths、artifact_refs、write_output、verification_receipt，
则下一次同类非推进调用被拒绝。
```

拒绝结果必须是可纠错 observation：

```json
{
  "type": "tool_policy_rejection",
  "policy": "non_progress",
  "requested_tool": "terminal",
  "reason": "recent tool calls did not advance missing deliverable",
  "missing_deliverables": ["frontend/public/games/arcane_dungeon_studio/game.js"],
  "repair_instruction": "请调用 write_file/edit_file 写入缺失产物；如果必须继续读取，请说明唯一缺失信息并读取唯一必要文件。"
}
```

注意：

- 这不是 required-action 锁。
- 这是 non-progress correction。
- 模型仍然可以在有理由时继续读取，但不能无限绕圈。

### 3.5 RequiredActionQueue 降级为 Progress View

`required_action_queue.py` 不再参与工具选择和强制门控。

保留用途：

- 展示缺失交付物。
- 给 progress page 展示 pending deliverables。
- 给 closeout validator 提供缺失清单。

必须改名并迁移：

```text
backend/runtime/professional_runtime/required_action_queue.py
  -> backend/runtime/professional_runtime/deliverable_progress.py

RequiredActionQueue
  -> DeliverableProgress

RequiredAction
  -> DeliverableObligation

current_action
  -> next_missing_deliverable

prompt_guidance()
  -> progress_hint()
```

禁止文案：

```text
当前强制动作：使用 write_file 写入...
下一步只能使用...
```

替换为：

```text
当前缺失交付物：...
建议优先补齐：...
```

迁移完成后必须删除 `required_action_queue.py`，不保留同名兼容 shim。

### 3.6 ToolObservationLedger

目标：

- 优先消费 `ToolResultEnvelope` 的结构化字段。
- 不再从普通文本里用宽泛正则反推产物、资产、验证。
- 文本只作为 preview，不作为主要证据来源。

保留：

- `records`
- `summary()`
- `has_read()`
- `has_write()`
- `verification_passed()`

修改：

- `build_tool_observation_record()` 如果没有 `result_envelope`，只能记录 preview 和 tool args。
- 对 `search_text` / `terminal` 的文本路径正则降级为 debug hint，不能满足硬证据。
- `write_file` / `edit_file` 必须由工具返回 `artifact_refs`。
- `terminal` 验证必须由工具返回 `command_receipt`。

### 3.7 ToolResultEnvelope

目标结构：

```json
{
  "tool_name": "write_file",
  "tool_args": {"path": "..."},
  "status": "ok",
  "text": "File written",
  "structured_payload": {},
  "observed_paths": ["..."],
  "artifact_refs": [
    {"path": "...", "kind": "file", "source": "write_file"}
  ],
  "command_receipt": {},
  "execution_receipt": {
    "operation_id": "op.write_file",
    "allowed": true,
    "sandbox_root": "...",
    "side_effect": "write"
  }
}
```

要求：

- 工具执行器必须生成 envelope。
- ledger 只信 envelope。
- validator 只信 ledger/envelope/artifact materializer。

## 4. 固定执行流程

目标流程：

```text
1. 用户输入进入 unit runtime。
2. 主模型生成 ModelTurnDecision。
3. runtime assembly 根据 ModelTurnDecision 生成 resource policy、tool visibility、sandbox policy。
4. 专业运行时启动 ReAct loop。
5. 模型看到完整工具列表、tool prompt、已有观察、todo 状态、材料挂载说明。
6. 模型自主输出 tool_use。
7. runtime 对 tool_use 执行：
   a. schema parse
   b. tool.validate_input
   c. build approval fingerprint
   d. OperationGate.check
   e. tool-specific permission/safety
   f. ProgressPolicy.check_non_progress
8. allow 则执行 tool.call。
9. deny/reject 则生成 structured tool_result observation。
10. 所有结果进入 ToolResultEnvelope。
11. ToolObservationLedger append。
12. progress page 根据 ledger 展示状态，不调度工具。
13. 模型继续下一轮。
14. 最终回答进入 deliverable validator。
15. validator 缺证据时，返回 closeout repair observation，让模型补证据。
16. 证据通过后收口。
```

## 5. 分阶段实施计划

### Phase 0 - 环境入口与运行边界制度化

目标：

- 固定前端、后端、API base、SSE、sandbox root。
- 让环境失败显式暴露，不再混入模型理解失败。
- 给长任务提供 environment snapshot 和掉线诊断依据。

新增文件：

- `backend/runtime/environment/runtime_environment.py`
- `backend/runtime/environment/port_guard.py`
- `backend/runtime/environment/connection_health.py`
- `backend/runtime/environment/__init__.py`

具体改动：

1. `RuntimeEnvironment`
   - 固定 `frontend_url=http://127.0.0.1:3000`。
   - 固定 `backend_url=http://127.0.0.1:8003`。
   - 固定 `api_base=http://127.0.0.1:8003/api`。
   - 记录 `workspace_root`、`sandbox_root`、`browser_policy=edge`。
   - 输出 `snapshot()`，供 event log、stage summary、tool context 使用。

2. `PortGuard`
   - 检查 `3000`、`8003` 是否只有一个监听进程。
   - 检查监听进程是否属于本项目。
   - 如果端口冲突，输出明确诊断，不自动换端口。
   - 端口异常时返回 `runtime_environment_error`。

3. `ConnectionHealth`
   - 检查后端 `/api` 是否可达。
   - 检查前端配置的 API base 是否等于固定值。
   - 检查 SSE 是否建立。
   - 检查 Electron / browser / Next proxy 是否指向同一后端。

4. 长任务启动前
   - `driver.py` 或任务入口记录 environment snapshot。
   - 如果 snapshot 失败，任务不伪装成模型失败，直接返回环境错误。

完成标准：

- 不再出现随机端口。
- 前端掉线时第一诊断能看到端口、进程、API base、SSE。
- 长任务日志包含 environment snapshot。
- 任何环境错误不进入 deliverable validator。

### Phase 1 - 切除 required-action 工具调度

目标：

- 停止 runtime 根据 `_next_required_tools()` 缩窄模型工具列表。
- 停止 `_tool_call_options_for_round()` 强迫特定工具。
- 停止 `_contract_gate_tool_request()` 以 current_action 拦截正常工具调用。

改动文件：

- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/professional_runtime/tool_contract_gate.py`
- `backend/runtime/professional_runtime/required_action_queue.py`

具体改动：

1. `driver.py`
   - `round_model_tool_instances` 改回完整 `model_tool_instances`。
   - `round_tool_call_options` 只保留通用并发限制，不因 `required_next_tools` 生成 forced options。
   - 删除 `_model_tools_for_required_next_step()` 调用。
   - 删除 `_contract_gate_tool_request()` 对 normal tool_use 的 required-action block。

2. `tool_contract_gate.py`
   - 删除“下一步只能使用 write_file/terminal”的逻辑。
   - 不再作为 normal tool gate。
   - closeout repair 迁移到 `backend/runtime/professional_runtime/closeout_repair.py`。

3. `required_action_queue.py`
   - 迁移为 `deliverable_progress.py`。
   - 删除旧文件，不保留兼容 shim。
   - `prompt_guidance()` 改为 `progress_hint()`，禁止“强制动作”。

4. 旧测试
   - 本阶段同步删除或重写依赖 required-action forcing 的测试。
   - 不允许等到最后再让旧测试定义旧行为。

完成标准：

- 长任务中模型仍能看到 read/search/terminal/write/edit/todo 等完整工具。
- progress page 可展示缺失产物，但不影响工具可见性。
- 不再出现“当前强制动作”“下一步只能使用”的系统提示。

### Phase 2 - 增加 ProgressPolicy 非推进纠错

目标：

- 用非推进检测替代 required-action 硬锁。
- 只在模型连续绕圈时拒绝非推进工具。

新增文件：

- `backend/runtime/professional_runtime/progress_policy.py`
- `backend/runtime/professional_runtime/policy_rejection_observation.py`

核心数据：

```python
@dataclass(frozen=True)
class ProgressPolicyDecision:
    allowed: bool
    reason: str = ""
    repair_observation: dict[str, Any] = field(default_factory=dict)
```

核心函数：

```python
def check_progress_policy(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    ledger: ToolObservationLedger,
    requested_tool_name: str,
    requested_tool_args: dict[str, Any],
    recent_observations: list[dict[str, Any]],
) -> ProgressPolicyDecision:
    ...
```

规则：

- 写入交付物缺失时，允许模型自由读取和检查。
- 如果连续 `N=3` 次非写入工具没有新增证据，则拒绝下一次同类非推进工具。
- 如果 requested tool 是 `write_file` / `edit_file`，放行给 OperationGate 和工具校验。
- 如果 requested tool 明确读取一个尚未读取且与缺失产物有关的文件，放行。
- 如果 requested tool 是 terminal 且用于真实验证，并且已有写入产物，放行。

完成标准：

- `terminal Test-Path game.js` 这种一次性确认可以允许。
- 反复确认、反复读已读文件、反复列 assets 不再无限放行。
- 被拒绝时进入模型可见 tool_result / observation，模型可以纠错。

补充要求：

- `policy_rejection_observation.py` 统一生成 `tool_result` 类型 observation。
- `ProgressPolicy` 不直接写 prompt 文案，只返回结构化 rejection reason、missing deliverables、repair instruction。
- `driver.py` 负责把 rejection observation 写入 event log 和 runtime context。

### Phase 3 - 工具级 validate / permission 标准化

目标：

- 将工具执行前链路变成标准协议。
- 把 sandbox、approval、environment snapshot 注入 `ToolUseContext`。
- 让每个工具自己产出结构化结果，而不是由 executor 从文本反推。

新增或改造：

- `backend/runtime/tool_runtime/tool_definition.py`
- `backend/runtime/tool_runtime/tool_adapter.py`
- `backend/runtime/tool_runtime/tool_use_context.py`
- `backend/runtime/tool_runtime/sandbox_policy.py`
- `backend/runtime/tool_runtime/sandbox_mount_plan.py`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/capability_system/units/tools/write_file_tool.py`
- `backend/capability_system/units/tools/agent_todo_tool.py`
- 其他核心工具：`read_file`、`edit_file`、`terminal`、`browser_control`

标准接口固定定义在 `backend/runtime/tool_runtime/tool_definition.py`：

```python
class RuntimeToolDefinition(Protocol):
    name: str
    operation_id: str
    input_schema: Any
    output_schema: Any

    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ValidationResult: ...
    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> PermissionDecision: ...
    def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope: ...
```

旧 capability 工具接入方式固定为：

```text
ToolRuntime.get_definition(tool_name)
  -> capability_system.tool_definitions.ToolDefinition
  -> RuntimeToolAdapter.from_capability_definition(...)
  -> RuntimeToolDefinition
  -> ToolRuntimeExecutor
```

Phase 3 必须完成的迁移顺序：

1. 新增 `tool_definition.py`，定义 `RuntimeToolDefinition`、`ToolValidationResult`、`ToolPermissionResult`。
2. 新增 `tool_use_context.py`，定义工具运行所需 workspace、sandbox、approval、environment snapshot。
3. 新增 `tool_adapter.py`，让旧 LangChain 工具可以被 runtime 协议包装。
4. 修改 `tool_executor.py`，执行入口从旧 `definition.build(...).ainvoke(...)` 改为 `runtime_tool.validate_input -> OperationGate -> runtime_tool.check_permissions -> runtime_tool.call`。
5. 将 `write_file`、`edit_file` 改为原生 runtime tool，不再依赖 adapter 的文本结果。
6. 将 `terminal` 改为原生 runtime tool，必须返回 `command_receipt`。
7. 将 `read_structured_file` 改为原生 runtime tool，必须返回 raw structured payload。
8. `agent_todo` 可以先通过 adapter 接入，但必须返回结构化 todo state envelope。

执行器顺序必须固定：

```text
parse tool args
  -> build ToolUseContext(environment + sandbox + permission)
  -> tool.validate_input
  -> build approval fingerprint
  -> OperationGate.check
  -> tool.check_permissions
  -> progress policy
  -> tool.call
  -> ToolResultEnvelope
  -> RuntimeObservation
```

写文件工具必须实现：

- path 在 sandbox/workspace allow scope 内。
- 更新/覆盖已有文件前，若已有文件存在且不是本轮创建，应要求已读或允许全量覆盖新产物目录。
- 返回 `artifact_refs`。

terminal 工具必须实现：

- 返回 `command_receipt`。
- 区分 inspection command 与 verification command。

完成标准：

- 每个核心工具执行后都有 envelope。
- OperationGate、tool validate、progress policy 的错误都能变成模型可见 observation。
- `ToolRuntimeExecutor` 不再直接调用旧 BaseTool。
- `capability_system.tool_definitions.ToolDefinition` 不再被误用为 runtime 执行协议。
- 计划中不再存在“或在现有模块定义”的可选路径。
- approval 不存在 `OperationGate` 后的第二套独立门禁。

### Phase 4 - 结构化 EvidenceLedger 改造

目标：

- ledger 不再靠文本反推硬证据。

改动文件：

- `backend/runtime/memory/tool_observation_ledger.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/runtime/professional_runtime/evidence_closeout.py`
- `backend/runtime/contracts/deliverable_validator.py`

具体改动：

1. `ToolResultEnvelope`
   - 去掉或降级 `_matched_paths()`、`_extract_plain_paths()` 对 hard evidence 的影响。
   - 搜索结果必须由搜索工具返回 structured matches。
   - terminal 结果必须由 terminal 工具返回 command receipt。

2. `ToolObservationLedger`
   - `has_write()` 只看 envelope artifact refs 或 write tool observed paths。
   - `verification_passed()` 只看 `command_receipt.passed`。
   - 文本正则只进入 `debug_hints`。

3. `deliverable_validator`
   - 验证真实文件存在、大小、内容结构。
   - 对游戏任务增加任务族 validator：五关、成长、Boss、assets 引用、README 覆盖。

完成标准：

- 不能通过在总结里写“Boss/成长/assets”来满足交付。
- 必须有真实文件和真实工具证据。

### Phase 5 - Closeout Repair 统一为工具结果式纠错

目标：

- 最终收口失败时，不靠系统提示硬压模型，而是返回结构化 repair observation。

改动文件：

- `backend/runtime/professional_runtime/evidence_closeout.py`
- `backend/runtime/professional_runtime/driver.py`

目标结构：

```json
{
  "type": "closeout_repair_required",
  "missing_deliverables": [],
  "missing_evidence": [],
  "allowed_next_actions": [
    {"tool": "write_file", "reason": "missing deliverable"},
    {"tool": "terminal", "reason": "missing verification"}
  ],
  "repair_instruction": "请先补齐真实工具证据，再提交最终总结。"
}
```

完成标准：

- closeout 不再用“只许某工具”的提示词。
- 模型看到缺失证据后自主选择工具补齐。
- 重复无推进仍由 ProgressPolicy 拦截。

### Phase 5.5 - 长任务阶段总结与超时续跑

目标：

- 长任务不再静默超时。
- 用户能看到阶段性进展。
- 超时、掉线、模型停止不直接丢弃任务状态。

新增或改造：

- `backend/runtime/professional_runtime/stage_summary.py`
- `backend/runtime/professional_runtime/timeout_recovery.py`
- `backend/runtime/professional_runtime/driver.py`

具体改动：

1. Stage summary
   - 每 30-60 秒从 event log、ledger、todo、environment snapshot 生成阶段总结。
   - 总结只描述真实观察，不允许写“预计已经完成”。
   - 总结展示 artifact refs、最新工具结果、阻塞原因、环境状态。

2. Timeout recovery
   - 模型超时后生成 `runtime_timeout_observation`。
   - observation 包含 last tool result、missing deliverables、todo state、environment snapshot。
   - 下一轮恢复时把它作为模型可见上下文，而不是强制指定下一工具。

3. SSE / frontend disconnect
   - disconnect 只影响用户显示，不影响 backend task run 状态。
   - 重连后可以读取 stage summary 和 event log。
   - 如果 backend task run 已失败，必须显示失败原因是 model timeout、tool rejection、environment error 还是 validator repair。

完成标准：

- 长任务运行中至少能周期性看到阶段总结。
- 超时后能续跑，而不是直接丢弃。
- 阶段总结不参与交付物验收。
- 掉线诊断能区分前端断线和后端任务失败。

### Phase 6 - 清理旧语义和旧测试

目标：

- 删除旧的 required-action 调度语义。
- 删除或重写与旧行为绑定的测试。

清理对象：

- `_model_tools_for_required_next_step`
- `_tool_call_options_for_round` 中 required tool forcing
- `_contract_gate_tool_request` 中 current_action 硬拦截
- `RequiredActionQueue.prompt_guidance()` 的强制动作文案
- 依赖“下一步只能使用 write_file”的测试
- 文本正则反推证据的测试

保留对象：

- progress page 展示。
- deliverable missing list。
- OperationGate。
- resource policy。
- sandbox mount。
- model-owned turn decision。

## 6. 文件级执行清单

### 必改

- `backend/runtime/professional_runtime/driver.py`
  - 恢复完整工具池。
  - 接入 `ProgressPolicy`。
  - 将 policy rejection 转成 ToolMessage / observation。

- `backend/runtime/professional_runtime/tool_contract_gate.py`
  - 删除 required-action 工具硬锁。
  - 不再作为 normal tool gate。
  - closeout 相关逻辑迁移到 `backend/runtime/professional_runtime/closeout_repair.py`。

- `backend/runtime/professional_runtime/required_action_queue.py`
  - 删除。
  - 由 `backend/runtime/professional_runtime/deliverable_progress.py` 取代。

- `backend/runtime/professional_runtime/deliverable_progress.py`
  - 新增。
  - 只提供缺失交付物视图，不调度工具。

- `backend/runtime/professional_runtime/closeout_repair.py`
  - 新增。
  - 统一生成 closeout repair observation。

- `backend/runtime/professional_runtime/progress_policy.py`
  - 新增。
  - 负责 non-progress detection。

- `backend/runtime/professional_runtime/policy_rejection_observation.py`
  - 新增。
  - 统一把 progress、sandbox、approval、tool validation rejection 转成模型可见 observation。

- `backend/runtime/environment/runtime_environment.py`
  - 新增。
  - 固定端口、API base、workspace、sandbox、浏览器策略。

- `backend/runtime/environment/port_guard.py`
  - 新增。
  - 检查 `3000`、`8003`，禁止端口漂移。

- `backend/runtime/environment/connection_health.py`
  - 新增。
  - 检查 API base、SSE、前后端连接一致性。

- `backend/runtime/tool_runtime/tool_use_context.py`
  - 新增。
  - 把 environment、sandbox、permission、approval 信息传给工具。

- `backend/runtime/tool_runtime/tool_definition.py`
  - 新增。
  - 唯一定义 runtime 工具协议、校验结果、权限结果。

- `backend/runtime/tool_runtime/tool_adapter.py`
  - 新增。
  - 只负责旧 capability / LangChain 工具迁移接入。
  - 不允许作为新工具的长期核心实现。

- `backend/runtime/tool_runtime/sandbox_policy.py`
  - 新增。
  - 定义 read/write/material/artifact scopes。

- `backend/runtime/tool_runtime/sandbox_mount_plan.py`
  - 新增。
  - 管理材料、继承资产、产物目录挂载。

- `backend/runtime/memory/tool_observation_ledger.py`
  - 结构化证据优先。
  - 文本路径正则降级。

- `backend/runtime/tool_runtime/tool_result_envelope.py`
  - 明确 envelope 字段。
  - 移除 hard evidence 的文本反推。

- `backend/runtime/tool_runtime/tool_executor.py`
  - 标准化 tool result envelope。
  - 标准化 validation / permission / execution 顺序。

- `backend/permissions/operation_gate.py`
  - 保留。
  - 只补 operation-specific validators，不加入任务进度判断。

### 可能需要改

- `backend/runtime/contracts/deliverable_validator.py`
- `backend/runtime/contracts/obligation_validation.py`
- `backend/runtime/professional_runtime/evidence_closeout.py`
- `backend/prompt_library/assembler.py`
- `backend/prompt_library/default_resources.py`
- `backend/capability_system/units/tools/*.py`
- 前端任务监控 / SSE 消费相关文件
- 后端任务状态查询 API

这些文件在实施时必须先 grep 确认是否仍引用旧 required-action、旧 evidence 正则或旧端口策略；如果引用存在，就从“可能需要改”升级为“必改”。

### 应删除或迁移

- 任何把 `required_action_queue.current_action` 当工具调度依据的逻辑。
- 任何“模型没按当前动作调用工具就直接算目标契约失败”的逻辑。
- 任何从普通文本里用宽泛正则满足交付物证据的逻辑。
- `required_action_queue.py`
- `_model_tools_for_required_next_step`
- `_tool_call_options_for_round` 中 required tool forcing
- `_contract_gate_tool_request` 中 current_action 硬拦截
- `RequiredActionQueue.prompt_guidance()` 的强制动作文案
- 依赖“下一步只能使用 write_file”的测试
- 文本正则反推证据的测试

## 7. 验证矩阵

### 7.1 单元测试

新增：

- `backend/tests/progress_policy_regression.py`

覆盖：

- 第一次 `terminal Test-Path game.js` 可放行。
- 连续三次无新增证据的 `terminal/read/search` 被拒绝。
- 拒绝输出包含结构化 repair observation。
- `write_file game.js` 永远不被 progress policy 拦。
- 已写入后 `terminal` 验证可放行。

新增：

- `backend/tests/tool_result_envelope_regression.py`

覆盖：

- write_file 返回 artifact refs。
- terminal 返回 command receipt。
- ledger 不从普通文本反推 hard write。
- ledger 不把总结文本当 evidence。

新增：

- `backend/tests/runtime_environment_regression.py`

覆盖：

- 固定端口为 `3000` 与 `8003`。
- API base 必须是 `http://127.0.0.1:8003/api`。
- 端口冲突时返回 environment error，不切换随机端口。
- environment snapshot 被写入长任务事件。
- SSE 断开不伪造成模型理解失败。

新增：

- `backend/tests/tool_use_context_regression.py`

覆盖：

- tool context 包含 workspace root、sandbox root、read scopes、write scopes。
- write_file 只能写入允许 scope。
- material mount 以结构化 mount plan 进入 context。
- approval fingerprint 相同不重复请求权限，风险变化必须重新审批。

### 7.2 长任务实验

继续使用：

- `professional-roguelike-campaign-delivery`

期望：

- 模型读取材料。
- 模型自主维护 todo。
- 模型写出 `index.html`、`styles.css`、`game.js`、`README.md`。
- assets 不丢失。
- 如果模型多轮绕圈，progress policy 返回纠错 observation。
- 最终必须有真实产物与验证结果。

### 7.3 回归风险测试

必须覆盖：

- 简单问答不触发 todo / progress policy。
- 只读分析不要求写文件。
- 明确规划任务不进入执行写入。
- 代码修复任务保留 read-before-write 保护。
- 权限拒绝不会被 progress policy 覆盖。
- closeout repair 不伪造产物。
- 前端断线不会导致后端任务状态丢失。
- backend 超时 observation 能被下一轮恢复消费。
- `.next` 残留或旧端口进程不会通过换端口绕过。

## 8. Cutover 规则

### 8.1 禁止双轨兼容

不保留旧 required-action 调度作为 fallback。

允许短期 shadow：

- progress view 可以同时输出旧字段名和新字段名，供日志观察。

不允许：

- 旧字段继续驱动工具选择。
- 旧字段继续生成“强制动作”提示。
- 旧 gate 在新 policy 后继续二次硬拦。

### 8.2 切换点

切换条件：

- `RuntimeEnvironment` 已接入长任务入口。
- `PortGuard` 已阻止随机端口漂移。
- `ToolUseContext` 已携带 sandbox / approval / environment snapshot。
- `driver.py` 不再调用 `_model_tools_for_required_next_step()`。
- `driver.py` 不再用 `_contract_gate_tool_request()` 做 normal tool_use 拦截。
- `required_action_queue.py` 已删除，`deliverable_progress.py` 不参与工具选择。
- `closeout_repair.py` 已接管 closeout repair。
- `ProgressPolicy` 已接入并有测试。
- ledger 证据来源以 envelope 为主。
- `ToolRuntimeExecutor` 已只执行 `RuntimeToolDefinition`。
- approval fingerprint 已作为 `OperationGate` 输入，不存在第二套 approval gate。

### 8.3 回滚原则

如果新逻辑失败，不回滚到旧 required-action 硬锁。

只能回滚到：

```text
完整工具池 + OperationGate + 工具校验
```

然后继续修 ProgressPolicy。

## 9. 明确不做

不做：

- 不把 Claude Code 误读成 required-action 状态机。
- 不把 Codex 误读成 required-action 状态机。
- 不再让 runtime 替模型猜下一步工具。
- 不再用“下一步只能使用 write_file”这种 prompt 压模型。
- 不再用文本正则作为 hard evidence。
- 不再为了跑通游戏任务写特例。
- 不再用随机端口绕过环境问题。
- 不再把前端掉线、SSE 中断、后端超时伪装成模型理解失败。

要做：

- 让模型自主推进任务。
- 让工具和权限系统变硬。
- 让非推进检测变清楚。
- 让证据收口依赖结构化执行结果。
- 让环境入口可检查、可诊断、可恢复。

## 10. 最终验收标准

改造完成后，系统应满足：

```text
1. 模型可以自主选择读、写、验证、todo、浏览器等工具。
2. 所有工具调用都经过 schema、validate、permission、sandbox、approval、progress policy。
3. 工具拒绝以 observation / tool_result 形式回到模型。
4. todo 由模型调用工具生成和更新。
5. progress view 只展示缺失，不调度工具。
6. closeout validator 只承认证据和真实产物。
7. 长任务卡住时能得到阶段性总结和可纠错阻断，而不是静默超时。
8. 游戏开发长任务能真实生成完整产物，不能靠总结或关键词通过。
9. 前后端固定运行在 `127.0.0.1:3000` 与 `127.0.0.1:8003`，不发生端口漂移。
10. sandbox / material / artifact scopes 通过 `ToolUseContext` 进入工具，而不是由工具或正则临时猜测。
11. approval token 按 operation、directive、risk fingerprint 复用，不重复骚扰，也不放过风险变化。
12. SSE 或前端断开时，后端任务状态、stage summary、event log 可恢复。
```

这份计划的核心裁决：

```text
旧 required-action 工具调度必须清理。
新结构采用 Codex / Claude Code 共同的 LLM-driven supervised tool loop。
runtime 的权力边界是校验、权限、sandbox、approval、证据、非推进纠错，不是替模型执行任务计划。
```
