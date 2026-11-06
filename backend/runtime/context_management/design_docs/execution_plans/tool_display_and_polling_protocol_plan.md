# 工具命令展示与幂等轮询协议修复计划

## 目标

同时解决两个相关问题：

1. 前端工具调用窗口显示 `action=command`，而不是实际命令。
2. `browser wait`、端口检查、构建状态检查等需要重复执行的幂等工具，被普通重复调用检测误判为死循环。

本计划保留现有工具调用主结构。`action` 仍表示动作类型，实际命令仍由 `command` 字段承载；轮询策略作为执行元数据接入，不把轮询逻辑写进命令字符串。

## 根因判断

### 命令显示

后端的标准工具生命周期事件已经能够提供真实命令：

- `tool_name`
- `target`
- `arguments_preview`

其中命令工具的 `target` 应为实际 `command`。

问题出在部分生命周期事件字段不完整，前端时序投影仍然接受这些事件，并在字段缺失时回退到 `title`、`detail` 或 `text`。如果这些字段是参数摘要，就会把 `action=command` 当成正文显示。

另外，生命周期合并目前使用通用的非空字段覆盖规则。后续低质量事件可能覆盖前面已经得到的真实命令或参数摘要。

### 幂等轮询

现有重复调用判定以工具名和规范化参数为主要语义身份。对于等待状态的工具，相同参数本身是正常现象，但系统没有表达：

- 这是同一个轮询过程；
- 两次调用之间应该等待多久；
- 轮询什么时候截止；
- 什么结果变化代表成功或进展。

因此不能只提高重复阈值，也不能把工具永久加入豁免名单。

## 目标协议

### 命令工具的规范字段

请求和生命周期事件继续使用现有字段：

```json
{
  "tool_name": "local_execution",
  "args": {
    "action": "command",
    "command": "..."
  },
  "target": "...",
  "arguments_preview": "action=command, command=..."
}
```

字段职责固定为：

- `action`：动作类型，不参与命令正文展示；
- `command`：实际执行命令；
- `target`：命令工具面向用户的实际命令；
- `arguments_preview`：脱敏后的参数摘要；
- `commandLine`：前端从 `target` 或真实命令参数计算出的展示值。

### 轮询执行策略

在工具调用外增加可选的执行元数据：

```json
{
  "execution_policy": {
    "mode": "poll",
    "poll_id": "build-check-1",
    "interval_ms": 2000,
    "timeout_ms": 120000,
    "success_condition": "状态达到完成"
  }
}
```

约束：

- `poll_id` 是一次轮询过程的稳定身份；
- `interval_ms` 必须为正数；
- `timeout_ms` 必须为正数，且不能无限期；
- 轮询策略只适用于注册为 `polling_capable` 的工具；
- 普通工具没有轮询策略时，仍按普通重复调用处理。

### 工具能力标签

工具能力注册增加轮询相关元数据：

- `idempotent`
- `polling_capable`
- `progress_observable`
- `default_poll_interval_ms`
- `default_poll_timeout_ms`

能力标签用于准入和默认值，不作为无限豁免开关。具体调用仍必须提供轮询身份和时间边界。

## 实施步骤

### 阶段一：统一命令事件生成

涉及：

- `backend/runtime/output_stream/public_stream_compiler.py`
- `backend/runtime/tool_runtime/tool_control_plane.py`
- `backend/harness/loop/single_agent_turn.py`

工作：

1. 抽取统一的命令目标和参数摘要生成规则。
2. 保证请求、开始、完成事件都能从同一份工具参数得到 `target`。
3. 保留现有脱敏和长度限制，不把命令正文以外的敏感参数写入公共事件。
4. 对缺少真实命令的事件保留空值，不伪造 `action=command` 作为命令。

### 阶段二：修复前端生命周期合并与展示

涉及：

- `frontend/src/lib/projection/chronological/accumulator.ts`
- `frontend/src/components/chat/PublicTimelineActivity.tsx`
- `frontend/src/components/chat/ToolTrace.tsx`

工作：

1. 增加“真实命令”判定，只接受 `target` 或 `command/cmd/script/code` 参数值。
2. `action=command` 只能作为元数据，不能作为 `commandLine` 或标题目标。
3. 生命周期合并按字段质量合并：真实命令不能被动作摘要、空字段或工具名覆盖。
4. 保留后续事件的状态、输出和时间更新，不因命令字段保护而丢失生命周期状态。
5. 缺少真实命令时显示“等待命令参数”或“命令内容不可用”，不显示原始协议串。
6. 同一轮轮询事件在前端聚合为一个轮询窗口，展开后查看各次观测。

### 阶段三：接入轮询生命周期

涉及：

- 工具能力注册与能力投影
- `backend/runtime/tool_runtime/tool_control_plane.py`
- 重复调用判定相关运行时模块
- 公共事件流协议

工作：

1. 解析并校验 `execution_policy`。
2. 为轮询过程记录 `poll_id`、轮次、间隔、截止时间、状态指纹和上次结果摘要。
3. 轮询调用的语义身份使用 `tool_name + poll_id + 轮询目标`，不再把相同参数直接判定为重复错误。
4. 每次轮询都必须经过时间边界和工具能力检查。
5. 状态达到成功条件时结束轮询；超过截止时间时返回明确超时结果。
6. 没有状态变化时继续等待，但记录无进展次数和当前截止时间。
7. 普通工具继续使用原有重复调用判定。

### 阶段四：反馈与监控

公共事件增加轮询状态信息：

- `poll_id`
- `poll_iteration`
- `poll_interval_ms`
- `poll_deadline_at`
- `poll_state_fingerprint`
- `poll_status`

前端显示：

```text
检查构建状态
已轮询 4 次 · 每 2 秒一次 · 剩余 86 秒
最近状态：仍在构建
```

## 失败处理

- 非轮询工具重复调用：沿用普通重复调用反馈。
- 轮询工具缺少 `poll_id`：拒绝建立轮询过程，并返回补充字段指引。
- 工具未声明 `polling_capable`：不允许使用轮询策略。
- 超过截止时间：结束轮询并返回超时观测，不继续重试。
- 状态指纹长期不变：记录无进展，但在截止时间前不误判为死循环。
- 事件字段不完整：保留工具生命周期状态，但不暴露原始参数摘要。

## 验证方式

不新增回归测试文件。按项目规则进行代码检查和固定节点真实运行验证：

1. 检查已有命令工具事件，确认前端展示实际命令，不显示 `action=command`。
2. 真实启动固定端口后端 `8003` 和前端 `3000`。
3. 触发一次普通命令，确认只执行一次且展示完整命令。
4. 触发一次端口或构建状态轮询，确认间隔、截止时间和轮次可见。
5. 确认轮询完成后不会继续调用，超时后不会无限调用。
6. 确认普通工具的重复调用仍按原规则处理。
7. 确认前端刷新或重新连接后，轮询窗口不会重复创建。

## 交付边界

本计划会修改工具事件协议、运行时重复调用判定和前端投影展示，属于跨核心模块协议变更。执行时必须按上述阶段完成，不保留旧的命令展示降级链路，也不增加永久轮询豁免分支。
