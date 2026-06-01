# 系统级 ToolInvocation 控制与生图工具修复计划

日期：2026-06-02

## 背景

当前 agent 生图工具的主要问题不是单个超时参数，而是工具调用生命周期被临时挂到了 TaskRun 执行控制上。生图这类工具可能耗时 100 秒左右，但它仍然是当前 agent turn 需要等待的前台工具调用，不应该因为耗时长就强制开 TaskRun。

对照 Codex 和 Claude Code 的成熟 agent 结构，工具调用应有独立的调用身份和取消通道：

- Codex 使用 `call_id` 配对工具 item 的 started/completed，并把 pending tool response 挂在 turn state 上。
- Claude Code 使用 `ToolUseContext` 和 `AbortController` 将取消信号传入工具；普通工具调用在当前 agent loop 内等待结果，只有后台工作才任务化。

## 目标架构

```text
Agent Turn / TaskRun / GraphNode / Direct Route
-> ToolInvocationRequest
-> ToolInvocationControlRegistry
-> ToolRuntimeExecutor
-> ToolResultEnvelope
-> Observation / Monitor
```

职责边界：

- `ToolInvocation` 是系统级工具调用单位。
- `TaskRun` 是工具调用方之一，只保存 `tool_invocation_ref`，不拥有工具任务。
- `ToolRuntimeExecutor` 只依赖 runtime/tool_runtime 层，不反向 import harness TaskRun 控制。
- direct route 是用户手动调用通道，不纳入 agent tool control。
- 生图成功必须等图片文件真实落地并产生 artifact ref 后再返回。

## 数据模型

`ToolInvocationRecord`：

```text
tool_invocation_id
caller_kind: agent_turn | task_run | graph_node | direct_route
caller_ref
session_id
turn_id
task_run_id
tool_name
tool_args
status: queued | running | completed | failed | cancelled
idempotency_key
started_at
completed_at
artifact_refs
structured_error
result_ref
```

`ToolInvocationContext`：

```text
tool_invocation_id
caller_kind
caller_ref
session_id
turn_id
task_run_id
tool_call_id
idempotency_key
control_signal
```

## 实施阶段

### 阶段 1：修复现有错误行为

1. 修复工具执行前 pause/replan 被误包装成 stop 的问题。
2. 统一结构化错误字段：`provider_retryable`、`agent_auto_retry_allowed`、`agent_retry_policy`、`attempts`。
3. 修复 JSON 字符串工具结果的结构化解析，避免错误字段丢失。
4. 保证 image tool 成功返回前检查文件存在且 size 大于 0。

### 阶段 2：建立系统级 ToolInvocation 控制

1. 新增 `backend/runtime/tool_runtime/tool_invocation_control.py`。
2. runtime host 持有 `ToolInvocationControlRegistry`。
3. `ToolRuntimeExecutor` 接收 `ToolInvocationContext`。
4. 移除 `ToolRuntimeExecutor` 对 `harness.loop.task_run_execution_control` 的依赖。
5. TaskRun stop/pause/replan 通过 invocation registry 取消正在运行的工具。

### 阶段 3：支持 agent 顶层工具调用

1. `run_single_agent_turn()` 支持 `action_type == "tool_call"`。
2. 单次工具调用创建 `ToolInvocationRecord`，不创建 TaskRun。
3. 工具完成后将 observation 注入当前 turn，让 agent 基于真实结果继续回答。
4. 当前 turn 被中断时取消关联 tool invocation。

### 阶段 4：生图专项

1. `image_generate` 默认 `target_id` 从 `tool_invocation_id` 派生。
2. 同一 invocation replay 复用已有成功结果，不重复请求 provider。
3. 默认 `overwrite=false`。
4. provider 504/timeout 时返回失败 observation，但 `agent_auto_retry_allowed=false`。

## 不做事项

- 不改 direct route。
- 不把所有长耗时工具强制 TaskRun 化。
- 不保留 `TaskRun -> tool_task` 作为长期控制链。
- 不用工具内部 `uuid4()` 作为幂等主机制。
- 不靠 prompt 控制 agent 不重试，必须由 executor policy 和结构化错误控制。

## 验收标准

1. 单轮 agent 调 `image_generate` 不创建 TaskRun。
2. 生图期间 stop 可以取消 tool invocation。
3. TaskRun 内调工具时，stop/pause/replan 通过 invocation registry 生效。
4. direct route 生图不受 ToolInvocationControl 影响。
5. provider 504 后 agent 不自动重试。
6. 同一 `tool_invocation_id` replay 不重复请求 provider。
7. 大图生成成功必须等文件存在且非空。
8. 动态上下文保留 `provider_retryable=true` 与 `agent_auto_retry_allowed=false`。
9. monitor 可观察 tool invocation started/completed。
