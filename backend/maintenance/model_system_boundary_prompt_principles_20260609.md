# 模型-系统边界与 Prompt 精准性原则

日期：2026-06-09

## 目标

本项目的 agent runtime 必须以成熟 coding agent 的控制边界为标准：模型负责理解、判断、调度和最终表达；系统负责提供环境、执行动作、记录观察、投影状态和做边缘控制。系统不能代替模型回答，也不能用状态、权限、校验或恢复话术阻碍 agent 继续完成任务。

## 三层输出边界

| 层级 | 权威来源 | 允许内容 | 禁止内容 |
| --- | --- | --- | --- |
| 模型正文 | 模型 | 面向用户的解释、结论、问题、阻塞说明、完成总结 | 系统伪造的用户回答、协议字段、内部运行状态 |
| 动作观察 | 系统执行层 | 工具结果、控制执行结果、失败原因、产物引用、权限/边界观察 | 伪装成 assistant 正文、要求用户重复表达明确意图 |
| 运行状态 | runtime / UI | 处理中、等待、恢复、暂停、停止、同步进度等状态 | 语义判断、最终答复、替模型解释任务 |

判断标准：任何文字如果会出现在聊天正文里，必须来自模型最终输出。系统生成的文字只能进入 observation、status、timeline 或 diagnostics。

公开状态层只能携带用户可理解的状态文案和稳定公开引用，例如 `title`、`detail`、`state`、`phase`、`runtime_event_id`。不得把完整 runtime event、observation、admission、action payload、provider protocol message 或内部 refs 透传给前端状态投影。

## Prompt 写作原则

1. 写给 agent 的 prompt 必须是“角色/任务/判断/动作”语言，而不是开发者视角的实现说明。
2. schema 字段说明可以提字段名，但必须限定为字段语义；不要把执行链路、UI 展示或内部模块写成给 agent 的任务。
3. 生命周期 prompt 应告诉模型如何判断用户意图、如何使用观察、何时提交动作；不要让模型背系统实现流程。
4. observation follow-up prompt 应强调：观察是事实输入，模型需要基于观察继续判断；系统观察不是最终用户回复。
5. prompt 中禁止出现会诱导模型把系统校验失败包装成“请重新提问”的话术，除非确实缺少用户决策。
6. prompt 中如果必须描述系统动作，应使用面向 agent 的行为语句：
   - 合格：`系统会把执行结果作为观察交还给你；观察返回后，你根据结果继续判断并回复用户。`
   - 不合格：`runtime 节点会将 active_work_control result 写入 answer_channel。`
7. 通用节点 prompt 不能把 agent 降格成“runtime 节点”。当无法预知具体专业身份时，应写成“你是当前工作流中被委派的专业执行者；具体身份和质量标准由当前节点合同决定”，再说明职责边界。

## active_work_control 目标语义

`active_work_control` 是模型提交给系统的当前工作边缘控制请求，不是最终回答。

正确生命周期：

```text
用户最新输入
-> 模型判断是否指向当前工作
-> 模型提交 active_work_control 或其它动作
-> 系统只执行/拒绝边缘控制并生成 observation/status
-> 模型读取 observation
-> 模型输出真正面向用户的最终回复或下一步动作
```

不允许的旧链路：

```text
模型提交 active_work_control
-> 系统执行/拒绝
-> 系统把执行结果 commit 成 assistant 正文
-> 本轮结束
```

异常恢复例外：如果运行进程重启、流被取消、终止事件缺失等导致观察无法再交回模型，系统可以写入一次边界恢复提示，说明本轮没有完成收口，并引导用户继续说明下一步。这只能用于不可恢复的执行流异常，不能用于普通权限拒绝、active_work_control 失败、工具失败或状态等待。

## 字段说明与 agent prompt 分层

字段说明可以这样写：

```text
response：本次控制动作的简短语义说明，供系统执行控制后作为观察上下文返回；不要把它当作最终回复。
```

agent prompt 应这样写：

```text
当前工作控制不是最终回复，而是请求系统调整当前工作的运行状态。你判断用户确实在控制当前工作时，提交 active_work_control。
系统会把执行结果作为观察交还给你。
观察返回后，你再根据结果向用户作出最终回复。
不要把动作字段、权限边界或校验失败写成要求用户重新提问的阻断话术。
```

## 审查清单

- `assistant_text` / `done.content` 是否只来自模型最终输出。
- `tool_call`、`active_work_control`、权限拒绝、恢复同步是否只进入 observation/status/timeline。
- frontend 是否根据 `answer_channel` 和 public timeline 分层展示，而不是把系统状态塞进 message content。
- `runtime_status` 是否只包含公开状态字段，没有完整 event、observation、admission 或内部 refs。
- prompt 是否用 agent 能执行的自然职责语言，而不是描述 runtime 节点用途。
- 测试是否保护目标行为，而不是保护旧的系统正文或旧 answer_channel。
- 任何“阻塞”是否真的是模型选择的 block，或不可恢复的协议错误；普通边缘控制失败必须先作为观察回到模型。

## 当前修复约束

本轮修复以 `active_work_control` 为第一优先级：

1. 系统执行 active work control 后只发 `runtime_status` 和模型可见 observation。
2. `active_work_control` 成功或失败都不能直接 commit assistant 正文。
3. observation follow-up 的最终 `respond/ask_user/block` 才能写入聊天正文。
4. prompt 中 `response` 的语义必须从“给用户看的回答”改为“控制动作语义说明”。
5. 回归测试要断言没有 `harness.single_agent_turn.active_work_control` 作为最终 answer source。
