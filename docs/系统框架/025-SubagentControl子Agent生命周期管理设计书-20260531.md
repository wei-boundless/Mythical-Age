# SubagentControl 子 Agent 生命周期管理设计书

日期：2026-05-31

## 1. 问题定义

当前单 agent harness 主链已经回到 `harness/runtime` 装配和 `harness/loop` 执行，但子 agent 调用仍有旧结构残留：

- `RuntimeAssemblyProfile.subagent_policy` 已存在，但 `backend/harness/runtime/assembly.py` 里被硬编码为禁用，并输出 `agent_control_runtime_not_configured`。
- `AgentRuntimeProfile` 仍使用 `can_delegate_to_agents`、`allowed_delegate_agent_ids`、`max_delegate_calls_per_turn` 等旧 delegation 字段。
- `backend/harness/execution/agent_delegation_executor.py` 是旧的直接委派执行器，包含超时式阻塞、委派类型匹配和父进程直接收结果等逻辑，不符合新 harness 的通用运行时设计。
- `runtime.shared.models.AgentRun` 已经具备 `parent_agent_run_ref`、`spawn_mode`、`context_scope` 和 `execution_runtime_kind`，可以承载真实父子 agent run 关系。

正确目标不是恢复 `delegate_to_agent`，而是建立一个成熟 agent 风格的 SubagentControl：父 agent 通过可授权生命周期工具启动、通信、等待、查看、关闭子 agent；系统记录真实 `AgentRun`、状态和邮箱事件；父 agent 只接收 observation、状态摘要和引用，不读取或伪造子 agent 的隐藏执行过程。

## 2. 成熟架构对照原则

参考成熟 coding agent 的外显工程形态，子 agent 不是一次函数调用，也不是关键词委派：

1. 子 agent 是真实运行实体：有独立 run、状态、消息、工具边界、结果和 artifact 引用。
2. 父子关系由系统记录：父 agent 不关心内部 task id，但 runtime 必须能追踪 parent-child edge。
3. 调用是生命周期工具，而不是隐藏路由：`spawn`、`send_message`、`wait/list`、`close` 都是普通 tool call，受同一权限系统监督。
4. 等待是邮箱/状态观察，不是阻塞式同步返回：`wait_subagent` 返回新消息、状态或无更新，不强制固定超时杀死。
5. 权限只能收窄不能扩张：父 agent 可请求目标 agent 和范围，系统按父 profile、目标 profile、任务环境边界和操作 gate 裁决。
6. 不做意图识别、关键词启发式或自动代替 agent 决定是否调用子 agent。系统只装配可见能力和规则。

## 3. 权责边界

### Agent 负责

- 判断当前任务是否需要子 agent。
- 选择可见子 agent，并写清楚目标、输入材料、期望输出和验收标准。
- 根据 `wait_subagent` 的 observation 调整计划、继续询问、关闭子 agent 或纳入结果。
- 最终交付时只引用真实产物、真实 observation 和真实子 agent 结果。

### Runtime 装配负责

- 根据 agent profile 和 runtime mode 生成 `subagent_policy`。
- 将允许的子 agent 目录、生命周期工具和规则投影给模型。
- 不根据用户语句做隐式任务识别或隐式委派。

### Permission / Gate 负责

- 生命周期工具按 operation 进入统一授权。
- 父 profile 决定是否可 spawn、可 spawn 哪些 agent、并发/总数预算。
- 子 agent profile 决定子 agent 自己可见工具和权限。
- 任务环境只提供系统环境、沙盒、存储和 artifact 边界，不授予 agent 额外工具能力。

### SubagentControl 负责

- 创建、记录、更新、查询子 agent run。
- 维护父子 mailbox / observation。
- 对 spawn/send/wait/list/close 做结构化输入校验和状态迁移。
- 不做语义意图识别，不替模型选择目标 agent。

### Loop 负责

- 将子 agent 生命周期工具作为普通 tool call 执行。
- 将 SubagentControl 返回值写成 runtime observation。
- 遇到失败返回可恢复 observation，让父 agent 决定下一步。

## 4. 固定生命周期协议

### 4.1 `spawn_subagent`

输入：

- `target_agent_id`：必须是 runtime 可见的子 agent。
- `goal`：子 agent 要完成的明确目标。
- `instructions`：可执行要求、边界和输出格式。
- `context_refs`：父 agent 明确传入的上下文引用。
- `expected_outputs`：期望摘要、证据、artifact 或 verdict。

系统行为：

1. 校验父 `subagent_policy.enabled`。
2. 校验 `target_agent_id` 在 `allowed_subagent_ids` 内。
3. 校验预算：单任务最多 spawn 数、活跃子 agent 数。
4. 读取目标 agent profile，生成子 `AgentRun`。
5. 写入 spawn mailbox 事件和 task event log。
6. 返回 `subagent_run_ref`、状态、可等待提示，不伪造执行结果。

### 4.2 `send_subagent_message`

输入：

- `subagent_run_ref`
- `message`
- `context_refs`

系统行为：

1. 校验 run 属于当前父 agent / 当前 task。
2. 校验 run 未关闭。
3. 写入父到子的 mailbox 消息。
4. 返回 message ref 和状态。

### 4.3 `wait_subagent`

输入：

- `subagent_run_ref`
- `since_message_ref`

系统行为：

1. 返回该子 agent 的新 mailbox 事件、状态和结果引用。
2. 如果没有新消息，返回 `status=running` 和 `no_update=true`。
3. 不做 busy loop，不设置固定工具超时；系统级执行预算由 loop 管控。

### 4.4 `list_subagents`

输入：

- 可选 `status`

系统行为：

- 返回当前 task 下属于当前父 agent 的子 agent run 摘要。

### 4.5 `close_subagent`

输入：

- `subagent_run_ref`
- `reason`

系统行为：

1. 将子 run 标记为 `completed` 或 `killed`。
2. 写入 close mailbox 事件。
3. 返回最终状态和已有 result refs。

## 5. 数据结构

### 5.1 AgentRuntimeProfile

正式字段：

```text
subagent_policy = {
  enabled: bool,
  allowed_subagent_ids: list[str],
  max_subagent_runs_per_task: int,
  max_active_subagents: int,
  context_policy: "summary_and_refs_only",
  result_policy: "observation_refs_only",
  allow_nested_subagents: bool
}
```

旧字段 `can_delegate_to_agents`、`allowed_delegate_agent_ids`、`max_delegate_calls_per_turn`、`delegate_context_policy` 不再作为 runtime 权威。

### 5.2 AgentRun

复用现有结构：

- `spawn_mode="subagent"`
- `context_scope="subagent_scoped"`
- `execution_runtime_kind="subagent_task"`
- `parent_agent_run_ref=<parent agent run id>`
- `diagnostics.subagent_control`

### 5.3 Subagent mailbox

新增轻量结构，存入 state index：

```text
SubagentMessage {
  message_id,
  task_run_id,
  parent_agent_run_ref,
  subagent_run_ref,
  direction,
  message_type,
  content,
  refs,
  created_at,
  authority
}
```

mailbox 是父子 agent 之间的可追踪通信层，不是隐藏推理暴露层。

## 6. 和现有代码的对接点

- `backend/agent_system/profiles/runtime_profile_models.py`
  - 引入正式 `SubagentPolicy`。
  - `AgentRuntimeProfile` 持有 `subagent_policy`。
- `backend/agent_system/profiles/runtime_profile_registry.py`
  - 默认主 agent 配置允许的 specialist 子 agent。
  - specialist profile 不默认允许嵌套 spawn。
  - 加载旧存储时只做一次迁移到 `subagent_policy`，写回后旧字段消失。
- `backend/harness/runtime/assembly.py`
  - `_subagent_policy()` 从 profile 和 mode policy 装配，不再硬禁用。
  - `available_subagents` 只作为可见目录输出，不授予额外权限。
- `backend/harness/agent_control/`
  - 新增 SubagentControl 模块。
  - 不引用 `harness.execution.agent_delegation_executor`。
- `backend/capability_system/operation_registry.py`
  - 新增 `op.subagent_spawn`、`op.subagent_message`、`op.subagent_wait`、`op.subagent_list`、`op.subagent_close`。
- `backend/capability_system/tool_definitions.py`
  - 新增五个生命周期工具定义。
- `backend/harness/loop/task_executor.py`
  - 在普通 tool call 路径中识别 lifecycle tool，并交给 SubagentControl。
  - observation 仍由 loop 统一记录。

## 7. 遗漏与矛盾检查结论

已检查的潜在矛盾：

- 与“无意图识别层”不冲突：子 agent 是否调用由父 agent 通过工具决定，系统不做语义分类。
- 与“任务环境只负责环境”不冲突：环境提供沙盒和存储边界，子 agent 工具能力由目标 agent profile 决定。
- 与“任务开启后不断装配 runtime”不冲突：子 agent run 创建后也应独立进行 runtime 装配。
- 与“不能有阻塞逻辑”不冲突：wait 是一次观察，不做无限等待或固定超时 kill。
- 与“旧链路清理”一致：旧 `AgentDelegationExecutor` 不接入新路径，后续按引用清理。

当前第一阶段允许的工程折中：

- 可以先实现生命周期记录、状态、mailbox 和 observation，子 agent 的真实后台执行调度作为下一阶段接入。但系统不能伪造子 agent 已完成结果。
- 可以在 profile 加载时迁移旧字段到新字段，但迁移后 runtime 权威只能读 `subagent_policy`。

## 8. 实施计划

### 阶段一：Profile 与 Runtime 装配

完成标准：

- `RuntimeAssembly.profile.subagent_policy.enabled` 能由 profile 配置决定。
- 主 agent 默认可见 specialist 子 agent。
- 不再出现 `agent_control_runtime_not_configured` 作为硬编码禁用原因。

### 阶段二：SubagentControl 状态层

完成标准：

- 可创建子 `AgentRun`。
- 可写入和读取 Subagent mailbox。
- spawn/list/close 在不执行真实子模型的情况下也能稳定返回真实状态。

### 阶段三：生命周期工具接入

完成标准：

- 五个工具进入 capability registry。
- 工具只在 agent operation 权限允许时可见。
- task executor 能执行 lifecycle tool，并返回 observation。

### 阶段四：真实子运行调度

完成标准：

- 子 agent run 有独立 runtime packet、模型调用、工具边界和 result。
- 父 agent 通过 wait/list 获取结果摘要和 refs。
- 失败恢复不阻塞主 loop。

### 阶段五：旧链路清理

完成标准：

- 删除或隔离 `agent_delegation_executor` 及旧 delegation tests。
- `delegate_to_agent` 不再作为主链可达工具。
- `delegation_kind` 仅在旧资产迁移期出现，不能作为 runtime 控制权威。

## 9. 验证矩阵

- profile 装配：主 agent 生成 enabled subagent policy。
- 权限拒绝：无权限 agent 调用 spawn 被拒绝。
- 目标拒绝：不在 allowed list 的 target 被拒绝。
- 状态记录：spawn 后 state index 能查到子 `AgentRun`。
- mailbox：send/wait/list 能返回真实消息和状态。
- loop observation：工具调用结果进入 task event log，父 agent 能看到观察。
- 旧链路：新路径不 import `AgentDelegationExecutor`。

