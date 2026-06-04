# 242-Agent工具权限统一与TaskRun续接门禁修复方案

状态：已实施  
日期：2026-06-02  
范围：单 agent harness、工具可见池、工具准入、TaskRun 可续接上下文、权限提示  
不在本方案范围：图像生成 provider 稳定性、Graph runtime、能力系统旁路重写

## 1. 结论

当前问题不是 `image_generate` 没注册，也不是 agent profile 没有权限。真实问题是工具权限在环境裁剪之后又被多层重复裁剪：

1. `RuntimeAssembly` 先按 profile、环境、显式 selection 生成一次操作授权。
2. `RuntimeToolPlan` 应承接这次环境裁剪结果，生成本轮模型可见工具池。
3. `RuntimeCompiler` 在普通 turn 再过滤 read-only 工具。
4. `Admission` 再按 `allowed_tool_names` 和 side-effect 策略判断。
5. `OperationGate` 执行前又按 resource policy 判断。
6. TaskRun 的 executor 可恢复状态没有进入普通 turn 的 active/recent work projection，导致模型不知道刚才任务已经启动并调用过工具。

这导致同一事实在不同层看起来互相矛盾：TaskRun 里 `image_generate` 可见且已调用；后续普通 turn 又只看到 21 个只读工具，于是 agent 误判“没有生图按钮”。

## 2. 目标原则

本次改造锁定以下原则：

1. 模型可见工具池就是本轮执行许可来源。  
   `RuntimeToolPlan.model_visible_tools` 中有多少工具，模型就可以请求多少工具；`dispatchable_tool_names` 必须与可见池一致或是其子集，不能出现隐藏放行或可见不可执行。

2. agent profile 是工具上限。  
   agent profile 决定这个 agent 理论上有哪些能力；环境不能凭空增加能力，只能收窄可见池并限制执行边界、路径、沙盒、审批和风险。

3. 环境可以裁剪模型可见工具池。  
   环境是任务入口的上游边界，用来降低路由压力、收窄工作场景、限制路径/沙盒/网络/shell/browser/image 等能力范围。裁剪后的可见池进入 `RuntimeToolPlan`，后续层不能再用 `single_agent_turn`、read-only 或另一套隐藏规则重复改写这个池子。

4. 非沙盒或高风险动作走人工确认。  
   像 Codex 一样，模型可以提出动作；是否执行由权限模式和风险策略决定。不能为了避免确认而提前把工具从模型可见池里隐藏掉。

5. 支持全权限模式。  
   full access 模式下，不绕过 agent profile 和当前环境可见池；它只让当前可见池中的工具按更宽松的执行权限进入 ToolControlPlane。OperationGate 仍负责不可逆危险动作、外部写入、审批令牌和审计记录。

6. 普通对话 turn 不再伪装成“只能读”。  
   如果当前 agent profile 允许某个副作用工具，并且当前权限模式允许或可审批，就应把工具暴露给模型。对于需要持续任务的动作，可以由 admission 要求建立 TaskRun，但不能让模型误以为工具不存在。

7. TaskRun executor 可续接状态必须进入上下文。  
   `waiting_executor` 或 runtime restart 造成的 executor 可恢复状态不是 completed/failed terminal history。它应该作为可续接工作暴露给普通 turn，允许用户用自然语言触发续跑、状态查询或停止。已经 completed/failed/aborted 的旧任务仍只作为历史事实，不做 same-run resume。

## 3. 现有链路证据

### 3.1 工具注册没有问题

- `backend/capability_system/tools/native_tool_catalog.py` 注册了 `image_generate`，operation 为 `op.image_generate`。
- `backend/agent_system/profiles/runtime_profile_registry.py` 的 `main_interactive_agent` 包含 `op.image_generate`。
- `backend/harness/runtime/tool_scheduling.py` 的 `env.development.sandbox` 包含 `op.image_generate`。

### 3.2 单轮对话强行只读

当前代码：

- `backend/harness/runtime/tool_plan.py`
  - `_visible_in_invocation()` 对 `single_agent_turn` 只返回 read-only 工具。
  - `_tool_allowed_for_runtime_plan()` 记录 `single_agent_turn_requires_read_only_tool`。
- `backend/harness/runtime/compiler.py`
  - `_single_agent_turn_tools()` 再次过滤 `read_only=True`。
  - output contract 写死 `side_effect_tool_call` forbidden。
- `backend/harness/loop/admission.py`
  - 普通 side-effect 工具在非 `runtime_authorized` 下返回 `needs_contract`。

这不是一个成熟 agent 的理想状态。成熟设计应该让模型知道工具存在，然后由 policy 决定是否直接执行、询问用户、申请审批或建立 TaskRun。

### 3.3 续接上下文丢失

当前代码：

- `backend/harness/entrypoint/runtime_facade.py`
  - `_active_work_context_from_active_turn()` 只看 `active_turn.bound_task_run_id`。
  - `_recent_work_outcome_status()` 不包含 `waiting_executor`。
- `backend/harness/loop/task_run_recovery_state.py`
  - `waiting_executor` 被判定为 `same_run_resumable=True`。

因此 TaskRun 已经处于可恢复状态，但普通 turn 看不到它，导致 agent 无法自然续接。

## 4. 目标链路

```text
AgentRuntimeProfile
-> TaskEnvironment visible-tool boundary
-> PermissionMode / UserApprovalPolicy
-> RuntimeToolPlan
   - model_visible_tools
   - dispatchable_tool_names
   - risk_annotations
   - approval_requirements
-> RuntimeCompiler
   - 将完整可见池告诉模型
   - 将需要审批/需要 TaskRun 的边界告诉模型
-> Admission
   - 只检查工具是否在 RuntimeToolPlan 中
   - side-effect 是否可直接执行、需要审批、需要 TaskRun
-> OperationGate
   - 执行前最终审批、路径、沙盒、危险动作检查
-> ToolRuntime
   - 执行并记录 receipt
```

关键不变量：

- 任何模型可见工具，admission 必须能识别。
- 任何 admission 放行工具，tool supervisor 必须能从同一个 tool plan 找到许可来源。
- 任何 tool supervisor 放行工具，必须有 receipt。
- 任何不可执行工具不能对模型展示为普通可用工具；如果展示，应标注需要审批或需要 TaskRun。
- `waiting_executor` / runtime restart executor recovery 必须作为可续接上下文进入普通 turn；completed/failed/aborted 旧任务不得恢复为同一任务。

## 5. 实施步骤

### 阶段 1：统一模型可见工具池

修改：

- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/admission.py`

动作：

1. 删除 `single_agent_turn` 只允许 read-only 的硬过滤。
2. `RuntimeToolPlan` 统一以 agent profile + task environment + explicit policy + tool registry 生成模型可见工具。
3. 环境保留可见池裁剪权；裁剪原因必须记录到 tool plan/filter issues，不能在 compiler/admission 里再用隐式规则二次删除。
4. `compiler` 不再在 `_single_agent_turn_tools()` 里二次过滤 read-only。
5. `admission` 只以 `RuntimeToolPlan.dispatchable_tool_names` 为工具存在性来源。
6. 普通 turn 中副作用工具的 admission 策略改为：
   - 沙盒内可执行：allow。
   - 非沙盒或高风险：ask_approval。
   - 需要持续任务上下文：needs_contract。

### 阶段 2：修复 TaskRun 可续接上下文

修改：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/task_run_recovery_state.py`
- `backend/harness/runtime/compiler.py`

动作：

1. 如果 active turn 没有 bound task，但 latest TaskRun 是 `waiting_executor` 或 runtime restart 造成的 executor recovery，则生成 `active_work_context` 或 `resumable_work_context`。
2. `waiting_executor` 不再被当成普通 terminal history。
3. 普通 turn prompt 必须明确告诉 agent：
   - 上一任务已经启动。
   - 已执行到哪一步。
   - 是否可 same-run resume。
   - 用户可以要求继续、停止、查看状态或追加指令。
4. 用户问“为什么不生图”时，agent 应回答真实状态：已调用生图，provider 504，任务可续跑或需要换参数/重试。

### 阶段 3：收敛权限提示和 UI 展示

修改：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/dynamic_context/runtime_delta_projector.py`
- 前端只在必要时更新状态展示，不新增卡片式复杂结构。

动作：

1. 将“当前可见工具数”改为“当前可用工具”和“需确认工具”两组。
2. 公开进展不再说“没有按钮”，而是说明真实执行状态。
3. 工具失败必须显示 provider / gate / sandbox 三类之一，避免把 504 误看成权限失败。

### 阶段 4：全权限模式

修改：

- 权限配置读取层。
- `OperationGate` 策略分支。

动作：

1. 增加 permission mode：`full_access`。
2. `full_access` 下不突破 agent profile 和 task environment；它只让当前环境可见池中的工具不再被权限模式额外隐藏。
3. `full_access` 仍记录 receipt；危险不可逆操作仍可保留硬拒绝或显式确认，避免 `git push`、无界删除这类动作失控。

## 6. 需要删除或停止使用的旧逻辑

删除/改写：

- `single_agent_turn_requires_read_only_tool` 作为普通工具隐藏规则。
- `_single_agent_turn_tools()` 的 read-only 二次过滤。
- output contract 中固定 `side_effect_tool_call` forbidden 的表达。
- 只从 `active_turn.bound_task_run_id` 获取可续接工作的单一入口。

保留但降权：

- `OperationGate`：作为最终执行安全层保留。
- 环境 allowlist：作为上游任务环境边界保留，可决定模型可见池；但不能被 compiler/admission 的 read-only 或 single-turn 规则覆盖。
- profile allowed operations：作为 agent 能力上限保留。

## 7. 验证方案

聚焦测试：

```powershell
python -m pytest backend/tests/runtime_capability_state_regression.py backend/tests/task_environment_registry_regression.py backend/tests/harness_runtime_facade_regression.py -q
```

新增/更新用例：

1. `single_agent_turn` 在 profile 允许时能看到 `image_generate`。
2. 普通 turn 中副作用工具如果需要 TaskRun，admission 返回 `needs_contract`，但模型可见池仍包含工具。
3. TaskRun execution 中 `model_visible_tools`、`dispatchable_tool_names`、OperationGate receipt 三者一致。
4. `waiting_executor` latest TaskRun 能进入 resumable context；completed/failed/aborted 旧任务不能进入 same-run resume。
5. 用户询问刚才任务状态时，模型能看到“已调用 image_generate，provider 504，可续跑”。
6. full access 模式下当前环境可见池不会再被权限模式二次隐藏。

实测：

1. 启动固定端口：
   - 前端 `127.0.0.1:3000`
   - 后端 `127.0.0.1:8003`
2. 跑五层地下塔任务。
3. 验证：
   - 普通 turn 工具池不再只有 21 个只读工具。
   - TaskRun 内生图可见、可调用。
   - provider 504 被展示为 provider 失败，不再被说成权限问题。
   - runtime restart 后用户说“继续”能续接 `waiting_executor`。

已完成的自动化验证：

```powershell
python -m pytest backend/tests/runtime_tool_control_plane_regression.py backend/tests/task_environment_registry_regression.py backend/tests/prompt_cache_prefix_tier_regression.py backend/tests/permission_service_regression.py backend/tests/runtime_capability_state_regression.py backend/tests/harness_runtime_facade_regression.py -k "waiting_executor or terminal_bound_active_turn or latest_waiting_executor or terminal_latest_task_without_active_turn or stale_running or not harness_runtime_facade_regression" -q
```

结果：`64 passed, 99 deselected`。

## 8. 风险

1. 普通 turn 暴露更多副作用工具后，prompt 必须更清楚地区分“可见”与“可执行需确认”。
2. 如果 full access 模式实现过宽，可能绕过危险操作确认；因此 full access 不能等于无审计。
3. 旧测试可能依赖普通 turn 只读工具池，需要改成验证审批/TaskRun admission，而不是验证隐藏工具。

## 9. 最终目标

修复后，agent 不应该再出现这种回答：

```text
我没有 image_generate，因为本轮只有 21 个只读工具。
```

正确行为应该是：

```text
我能看到 image_generate。这个动作会生成外部资源/写入产物。
当前任务已经调用过一次，provider 返回 504。
我可以按当前权限继续重试、换低配置参数，或在需要确认时先请求确认。
```
