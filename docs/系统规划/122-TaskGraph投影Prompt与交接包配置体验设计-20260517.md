# TaskGraph 投影 Prompt 与交接包配置体验设计

## 0. 定位

本文不是 120 计划的核心实施项，也不是当前通用编辑器的重心。

它的作用是作为后续任务配置体验的设计参考：当后端已经具备 `TimelinePoint / ArtifactContextPacket / RevisionPacket / MemorySnapshot / Receipt` 之后，前端如何让用户清楚地配置“节点收到什么、如何理解、必须产出什么、交给谁”。

核心目标：

```text
上下文包解决“给节点什么”
投影 Prompt 解决“节点如何理解和使用这些东西”
输出契约解决“节点必须交付什么”
```

这三者必须配套，否则 Agent 会靠猜。

## 1. 当前代码事实

### 1.1 前端已有职责与交接页

相关文件：

- `frontend/src/components/workspace/views/task-system/TaskGraphResponsibilityPage.tsx`
- `frontend/src/components/workspace/views/task-system/NodeResponsibilityCard.tsx`
- `frontend/src/components/workspace/views/task-system/EdgeHandoffCard.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphLayerNav.tsx`

当前已经具备：

- TaskGraph Studio 已有层级页：
  - 任务蓝图
  - Agent 编组
  - 拓扑编排
  - 职责与交接
  - 时序与循环
  - 记忆与产物
  - 契约与质量门
  - 预检与运行
- `NodeResponsibilityCard` 能配置：
  - `projection_id`
  - `role_identity`
  - `responsibility_scope`
  - `responsibility_exclusions`
  - `definition_of_done`
  - 生成并绑定投影
- `EdgeHandoffCard` 能配置：
  - `payload_contract_id`
  - `wait_policy`
  - `failure_propagation_policy`
  - `result_delivery_policy`
  - `working_memory_handoff_policy`

当前不足：

- 节点身份 prompt 与输入包没有明确绑定。
- 用户不知道某个节点实际会收到哪些 packet / snapshot。
- 输出契约和下游交接没有在同一个配置视角里闭环。
- 现在更像“职责字段 + 交接字段”并排编辑，还不是“节点执行认知包”的配置体验。

### 1.2 后端已有投影快照概念

相关文件：

- `backend/orchestration/runtime_loop/stage_projection.py`
- `backend/orchestration/runtime_loop/runtime_assembly_builder.py`
- `backend/orchestration/runtime_loop/stage_execution_request.py`

当前已经具备：

- `StageProjectionSnapshot`
- `projection_ref`
- `prompt_manifest_ref`
- `soul_runtime_view`
- `visible_tool_ids`
- `visible_skill_ids`
- Runtime Assembly 的 `context_sections`

当前不足：

- `StageExecutionRequest` 还没有把未来的 `ArtifactContextPacket / RevisionPacket / MemorySnapshot` 与投影 prompt 组织成一个清晰的模型可见结构。
- 前端还不能预览“节点最终看到的任务说明 + 输入包 + 输出要求”。

## 2. 设计原则

### 2.1 TaskGraph 不保存长 prompt 正文

TaskGraph 只保存引用：

```text
projection_id
projection_overlay_id
input packet refs / edge refs
output_contract_id
payload_contract_id
```

长 prompt 正文、角色语言、任务流程说明，属于投影系统和编排系统。

### 2.2 节点配置要围绕“执行认知包”

用户配置节点时，真正想确认的是：

```text
这个节点是谁？
它这次要做什么？
它会收到什么？
它应该如何使用收到的内容？
它必须产出什么？
它的产物交给谁？
```

前端页面应该围绕这六个问题组织，而不是把字段散在多个卡片里让用户自己拼。

### 2.3 Prompt 必须是 Agent 可理解语言

不能写成：

```text
这是 runtime 节点。
根据任务图执行 world_review。
这个节点用于校验资产。
```

应该写成：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你必须基于本次送审稿和基准设定给出通过或返修裁决。
```

### 2.4 Packet 和 Prompt 必须一一配套

如果节点收到 `ArtifactContextPacket`，prompt 必须告诉它：

- 这是当前送审稿，不能去猜其它版本。
- 是否可以全文引用。
- 是否只允许审核，不允许重写。

如果节点收到 `RevisionPacket`，prompt 必须告诉它：

- 被审原稿在哪里。
- 审核意见在哪里。
- 当前是第几轮返修。
- 应该保留哪些已通过部分。

如果节点收到 `MemorySnapshot`，prompt 必须告诉它：

- 哪些是只读基准。
- 哪些是可变状态。
- 哪些只能作为参考，不能改写。

## 3. 推荐的前端信息架构

### 3.1 不新增主层级，先强化“职责与交接”页

当前 TaskGraph Studio 已有 `职责与交接` 层级。后续不应该新增一个平行的“Prompt 配置”主页面，避免层级过多。

建议把 `职责与交接` 页升级为：

```text
职责与交接
  左侧：节点列表 / 边列表 / 问题状态
  中间：所选节点的执行认知包
  右侧：预览与校验
```

不同层级仍然分开：

- 拓扑结构在“拓扑编排”。
- 时间、循环、返修路由在“时序与循环”。
- 记忆仓库和产物边在“记忆与产物”。
- 输入输出 schema 在“契约与质量门”。
- 本页只负责把这些引用组织成 Agent 可理解的执行说明。

### 3.2 节点执行认知包页面结构

选中节点后，页面展示四个区块：

```text
1. 身份投影
2. 本次任务说明
3. 可用输入包
4. 输出与交接
```

#### 身份投影

展示和配置：

- 当前 `projection_id`
- 角色身份
- 职责边界
- 不负责事项
- 完成标准
- 可见工具 / 技能摘要

用户动作：

- 选择已有投影。
- 从职责字段生成投影。
- 跳转到投影系统精修。
- 预览模型可见身份 prompt。

#### 本次任务说明

展示：

- 当前节点绑定的 `task_id`
- 当前节点在图中的 phase / sequence / loop frame
- 这个节点本轮运行时的目标模板
- 与当前 `TimelinePoint` 的关系

这里不是让用户写业务 prompt，而是定义任务说明模板：

```text
你本轮处于 {phase_title} 的第 {sequence_index} 步。
你正在处理 {timeline_point_label}。
你必须完成 {node_goal}。
```

#### 可用输入包

按来源分组：

```text
ArtifactContextPacket
RevisionPacket
MemorySnapshot
StaticResources
UserInputs
```

每个输入包要显示：

- 来源边 / 资源节点。
- 是否必需。
- 缺失时行为：block / warn / empty。
- 是否模型可见。
- 展开策略：refs only / summary / full text / max chars。
- prompt 中如何称呼它。

重点字段：

```text
input_alias
model_visible_label
usage_instruction
must_use
may_ignore
forbidden_use
```

示例：

```text
input_alias: 当前送审稿
usage_instruction: 你必须只审核这份稿件，不得引用其它候选稿版本。
must_use: true
forbidden_use: 不得把它当作最终稿发布。
```

#### 输出与交接

展示：

- `output_contract_id`
- artifact targets
- memory write candidates
- review verdict
- downstream packet 生成规则
- receipt 生效规则

用户应能看到：

```text
你输出的 artifact 会交给哪些节点？
你输出的审核意见会进入哪个 RevisionPacket？
你写入的记忆候选需要谁提交？
```

## 4. Prompt 生成结构

后续前端可以提供“模型可见 prompt 预览”，但不直接把预览写死到 TaskGraph。

推荐生成结构：

```text
【身份】
你是一名……
你只负责……
你不负责……

【本轮任务】
你现在处于……
你本轮必须……

【你收到的上下文】
1. 当前送审稿：来自 ArtifactContextPacket(...)
   使用要求：……
2. 基准记忆：来自 MemorySnapshot(...)
   使用要求：……
3. 返修要求：来自 RevisionPacket(...)
   使用要求：……

【工作流程】
你应按以下步骤处理：
1. 先检查……
2. 再判断……
3. 最后输出……

【输出要求】
你必须输出……
你不得输出……
```

这个结构由投影系统、上下文包 resolver、契约系统共同生成。

## 5. 配置对象关系

### 5.1 节点侧

```text
TaskGraphNode
  projection_id
  task_id
  phase_id
  sequence_index
  loop_policy
  output_contract_id
  artifact_policy_ref
```

### 5.2 边侧

```text
TaskGraphEdge
  edge_type
  payload_contract_id
  artifact_context_policy
  revision_carry_policy
  memory_read/write policy
  result_delivery_policy
```

### 5.3 投影侧

```text
Projection
  role_identity
  responsibility_scope
  responsibility_exclusions
  workflow_instruction_template
  context_usage_rules
  output_behavior_rules
```

### 5.4 运行侧

```text
StageExecutionRequest
  timeline_context
  stage_projection_snapshot
  artifact_context_packet
  revision_packet
  memory_snapshot
  output_contract
```

## 6. 页面交互建议

### 6.1 从节点出发的配置流

用户点击节点后：

1. 选择身份投影。
2. 查看该节点会收到哪些输入包。
3. 为每个输入包配置“如何称呼”和“如何使用”。
4. 查看输出契约。
5. 查看下游交接。
6. 点击“预览模型看到的执行说明”。

这条路径符合用户思维：先看这个节点是谁，再看它拿到什么，再看它产出什么。

### 6.2 从边出发的配置流

用户点击边后：

1. 选择交接类型：
   - 直接产物上下文
   - 记忆读取
   - 返修请求
   - 提交通知
2. 配置 packet 类型。
3. 配置 target 节点如何称呼这份输入。
4. 配置缺失行为。
5. 预览 target 节点收到的上下文段落。

### 6.3 预览必须显示真实组合结果

预览不应该只是 prompt 草稿。

应显示：

```text
身份 prompt
本轮任务说明
输入包摘要
输出契约摘要
禁止事项
```

并标注来源：

```text
来自 Projection
来自 TimelinePoint
来自 ArtifactContextPacket
来自 MemorySnapshot
来自 OutputContract
```

这样用户能判断配置是否真的闭环。

## 7. 体验上的关键防错

### 7.1 缺 packet 使用说明时预警

如果节点会收到 `ArtifactContextPacket`，但 projection 没有说明如何使用，应警告：

```text
当前节点会收到产物上下文，但没有配置使用说明。节点可能不知道这是草稿、审核稿还是最终稿。
```

### 7.2 审核节点缺裁决输出时阻断

如果节点类型是 `review_gate`，但输出契约没有 verdict，应阻断发布。

### 7.3 返修边缺 carry 规则时阻断

如果存在 revision edge，但没有携带被审原稿和审核意见，应阻断发布。

### 7.4 只读记忆被配置为可写时阻断

如果输入包来自只读 repository，而节点配置了 memory write 权限，应阻断发布。

### 7.5 Prompt 里出现开发说明式语言时提醒

检测类似：

```text
runtime 节点
执行 task id
根据配置
```

提醒用户改成角色语言。

## 8. 对现有页面的低风险演进

### 阶段 A：增强现有职责与交接页

改造范围：

- `NodeResponsibilityCard.tsx`
- `EdgeHandoffCard.tsx`
- `TaskGraphResponsibilityPage.tsx`

新增内容：

- 节点输入包摘要。
- 输出契约摘要。
- 模型可见 prompt 预览。
- packet 使用说明字段。

不新增主导航层级。

### 阶段 B：接入后端真实 StageExecutionRequest 预览

等 120 计划中的 `StageExecutionRequest` 带上真实 packet / snapshot 后，前端增加：

```text
Preview Stage Request
```

让用户看到某个节点运行时真实会收到什么。

### 阶段 C：投影系统深度编辑入口

节点页只保留轻量编辑：

- 选择投影。
- 快速生成投影。
- 查看摘要。

复杂编辑跳转到投影系统：

- prompt manifest
- section visibility
- context usage rules
- tool/skill visibility

这样 TaskGraph 编辑器不会变成投影编辑器。

## 9. 不纳入当前重心的原因

这个设计重要，但现在不能抢 120 的主线。

原因：

- 后端还没有完整 `TimelinePoint / Packet / Snapshot`，前端做得再好也只能是空预览。
- 当前首要问题是确保运行链路读写正确。
- 投影配置体验应建立在真实 StageExecutionRequest 之上。

所以当前只保留为后续 UI 规划，不进入最近一轮后端核心实施。

## 10. 验收标准

后续实现这个配置体验时，必须满足：

1. 用户能从节点看到身份、任务、输入包、输出契约、下游交接。
2. 用户能从边看到交接类型、packet 类型、目标节点称呼、缺失行为。
3. 模型可见 prompt 预览使用 Agent 可理解语言。
4. 预览能标注每段内容来源。
5. TaskGraph 只保存引用，不保存长 prompt 正文。
6. 页面不写作特化。
7. 审核 / 返修 / 记忆读取都能通过通用 packet/snapshot 表达。

