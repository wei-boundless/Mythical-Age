# 图任务时空 Outcome 算法修复方案

状态：修复方案，待审阅后实施  
日期：2026-07-06  
适用范围：`graph_system`、`task_system`、`harness`、写作图任务配置、后续项目网络审查图任务

## 1. 问题定义

本次两百章写作图实测暴露的问题不是单个节点失败，而是图任务算法概念没有收束干净。

当前现象：

```text
memory_commit_world 节点收到了完整授权输入
-> agent 判断候选正文仍有问题，输出“提交失败，要求返回世界观设计节点返修”
-> GraphSystem 把该结果当作 node_failed
-> 整张图进入 failed
```

从语义角度看，agent 做的是业务判断：候选内容有问题，需要回到上游。

从算法角度看，它不应该是运行失败，而应该是一次合法的控制事件：

```text
NodeExecution completed
-> OutcomeSignal(revision_requested)
-> TransitionAlgorithm 选择 revision route
-> 建立 revision frame
-> 失效相关下游状态
-> 回传返修上下文
-> 目标节点重新 ready
```

所以修复目标不是给 `memory_commit_world -> world_design` 写一条特例线，而是把图任务当作高度程序化的时空系统，建立通用 Outcome 算法。

## 2. 核心原则

### 2.1 图任务是程序化时空

图任务运行时由三类坐标构成：

```text
空间坐标：node_id / edge_id / resource_id / context_slot / artifact_ref
时间坐标：graph_clock_seq / checkpoint_id / epoch / attempt_index / frame_id
因果坐标：source_result_ref / packet_ref / dependency edge / invalidation scope
```

GraphSystem 的职责是维护这个时空，不解释领域语义。

### 2.2 Outcome 是算法输入，不是领域词

节点输出必须被归一为通用 outcome：

```text
completed
revision_requested
retry_requested
blocked
waiting_human_gate
technical_failed
aborted
```

领域词只存在于 payload：

```text
世界观返修
提交失败
散修未专属化
章节重写
审查不通过
```

算法层只看 `outcome_kind`，不看这些业务文本。

### 2.3 执行状态和业务 Outcome 必须分离

当前结构把 postprocess error 直接压成 `NodeResultEnvelope.status = failed`，这会污染图算法。

目标结构：

```text
execution_status = completed | failed | blocked
outcome_kind = completed | revision_requested | retry_requested | blocked | technical_failed
materialization_status = committed | candidate | skipped | rejected
```

示例：

```text
agent 正常完成并要求返修：
execution_status = completed
outcome_kind = revision_requested
materialization_status = candidate/skipped

工具崩溃或模型无响应：
execution_status = failed
outcome_kind = technical_failed

质量门要求同节点重试：
execution_status = completed
outcome_kind = retry_requested
```

## 3. 目标算法

### 3.1 NodeResult Outcome Normalization

新增通用归一层：

```text
RawExecutorResult
-> Artifact / Memory / Algorithm Postprocess Observation
-> OutcomeSignal[]
-> NodeResultEnvelope
```

`OutcomeSignal` 建议字段：

```python
{
    "outcome_kind": "revision_requested",
    "source": "agent_result | quality_gate | memory_precommit_guard | runtime",
    "severity": "control | recoverable | terminal",
    "target_hint": "candidate_source | same_node | explicit_node | human_gate",
    "payload_ref": "...",
    "reason_summary": "...",
    "authority": "graph_system.outcome_normalizer",
}
```

关键点：

- `OutcomeSignal` 是算法输入。
- `payload_ref` 可以指向 artifact、final answer、structured output 或 postprocess observation。
- normalizer 可以调用领域 adapter，但 adapter 只负责把领域结果映射成通用 outcome，不控制图状态。

### 3.2 Transition Algorithm

`GraphTransitionProcessor` 不应根据 `result.status == completed` 简单判断所有边。

目标逻辑：

```text
读取 NodeResult.outcome_signals
-> 按 edge.transition_policy 匹配 outcome_kind
-> 选择一组 outgoing edge
-> 为被选边生成 packet
-> 为未选边标记 skipped
-> 技术失败才标记 source_failed
```

通用边策略：

```python
transition_policy = {
    "trigger_outcomes": ["completed"],
    "excluded_outcomes": ["revision_requested"],
}

revision edge:
transition_policy = {
    "trigger_outcomes": ["revision_requested"],
    "route_role": "revision",
}

retry edge:
transition_policy = {
    "trigger_outcomes": ["retry_requested"],
    "route_role": "retry",
}
```

这样算法不关心写作、审查、项目网络，只关心 outcome 与边策略。

### 3.3 Frame Algorithm

返修不是“倒退一下节点”，而是打开一个时空 frame。

Revision frame：

```python
{
    "frame_id": "gframe:...",
    "frame_kind": "revision",
    "source_node_id": "...",
    "target_node_id": "...",
    "source_result_ref": "...",
    "opened_at_graph_clock": 17,
    "invalidation_scope": ["target_subtree"],
    "carried_context_refs": ["返修交接包"],
    "status": "active",
}
```

GraphLoop 根据 frame 做四件事：

1. 失效受影响下游节点。
2. 保留不受影响的上游结果。
3. 把返修包作为目标节点的授权输入。
4. 目标节点重新 ready。

Frame 关闭条件：

```text
目标节点重新完成
-> 下游依赖重新生成
-> 原 revision source 的修复路径被新结果覆盖
-> frame status = closed
```

### 3.4 Invalidation / Replay Algorithm

失效不是删除一切，而是按因果链清理。

通用规则：

```text
从 revision target 开始
-> 沿普通依赖边向下游遍历
-> 遇到 resource node 不删除资源，只更新引用状态
-> 遇到 revision edge 不继续扩散
-> 清理 result_ref / work_order_id / packet refs
-> 保留历史 result_history 供审计
```

这部分可以复用现有 `_revision_reset_node_ids`，但必须从“返修语义函数”升级为“frame invalidation algorithm”。

### 3.5 Materialization Algorithm

记忆提交类节点必须改成两阶段：

```text
precommit_check
-> outcome completed: durable commit
-> outcome revision_requested: 不写正式记忆，只生成 revision packet / diagnostic artifact
-> outcome technical_failed: 不写正式记忆，进入失败恢复
```

当前问题是：agent 输出提交失败时，系统仍然产生了 memory candidate / artifact，并随后用 guard 报错。目标是：

- 提交失败报告可以作为诊断 artifact。
- 不能进入正式 baseline memory。
- 不能触发下游普通业务边。
- 必须触发 revision outcome 对应的控制边。

## 4. 实例结构怎么声明

### 4.1 GraphSystem 不硬编码实例

GraphSystem 只需要理解：

```text
node
edge
outcome
transition_policy
frame
checkpoint
```

它不应该出现这些词：

```text
world_design
memory_commit_world
散修
章节
世界观
```

### 4.2 任务图实例声明 outcome 能力

写作图里的提交节点可以声明：

```python
node.outcome_policy = {
    "allowed_outcomes": ["completed", "revision_requested", "technical_failed"],
    "default_success_outcome": "completed",
    "business_rejection_outcome": "revision_requested",
    "revision_target_selector": "source_candidate_node",
}
```

这不是算法硬编码，而是图实例声明该节点可能产生什么控制 outcome。

### 4.3 图实例声明 revision edge

写作图生成器应根据节点声明生成 revision edge：

```python
{
    "edge_type": "revision_request",
    "source_node_id": "<commit_or_review_node>",
    "target_node_id": "<declared_revision_target>",
    "transition_policy": {
        "trigger_outcomes": ["revision_requested"],
        "route_role": "revision",
    },
    "artifact_ref_policy": {
        "target_input_key": "返修交接包",
        "context_mode": "refs_and_authorized_text",
    },
}
```

这里的 `<declared_revision_target>` 来自图实例配置，例如：

```python
source_candidate_node_id
review_revision_stage_id
explicit_revision_target_node_id
```

算法层不计算“应该回世界观还是回正文”，实例层声明，算法层执行。

### 4.4 写作图当前应怎样表达

对写作图而言：

```text
world_review 判返修 -> revision edge -> world_design
memory_commit_world 提交检查不通过 -> revision edge -> world_design
character_review 判返修 -> character_design
memory_commit_character 提交检查不通过 -> character_design 或 design_sync 声明目标
chapter_review 判返修 -> chapter_draft
memory_commit_chapter 发现可返修问题 -> chapter_draft 或 chapter_batch_assemble，按节点声明
```

但这些都应由配置字段生成，不写入 GraphSystem。

## 5. 工程实施方案

### Phase 1：模型层增加 OutcomeSignal

修改范围：

- `backend/graph_system/models.py`
- `backend/graph_system/work_order_executor.py`
- `backend/graph_system/runtime_algorithm_types.py`

实施内容：

- 在 `NodeResultEnvelope` 中增加 `outcome_signals`。
- 保留 `status` 作为兼容状态时，明确其只代表 executor/terminal 状态的投影。
- 增加 helper：

```python
primary_outcome(result) -> str
result_has_outcome(result, outcome_kind) -> bool
```

### Phase 2：新增 Outcome Normalizer

新增或改造：

- `backend/graph_system/outcome_normalizer.py`
- `backend/graph_system/revision_signal_registry.py` 可演进为 `outcome_signal_registry.py`

职责：

- 把 final answer、structured output、quality gate、memory precommit guard、algorithm adapter result 映射为通用 outcome。
- 不直接修改 graph state。
- 不知道写作图具体节点。

### Phase 3：改造 TransitionProcessor

修改：

- `backend/graph_system/transition_processor.py`

目标：

- 不再以 `result.status == completed` 作为唯一边选择依据。
- 使用 `edge.transition_policy.trigger_outcomes`。
- 无 policy 的普通边默认只接受 `completed`。
- revision edge 默认接受 `revision_requested`。
- technical failure 才把普通下游边标记 `source_failed`。

### Phase 4：把 revision reset 升级为 frame algorithm

修改：

- `backend/graph_system/loop.py`
- `backend/graph_system/models.py`
- `backend/graph_system/checkpoint_store.py`

目标：

- `GraphLoopState` 增加 `frames` 或 `control_frames`。
- `_state_after_revision_requeue` 更名或抽象为 `_state_after_control_frame_opened`。
- revision、retry、human reroute 都可作为 frame 的不同 kind。
- checkpoint 保存 frame 状态。

### Phase 5：提交类节点改成 precommit / commit 两阶段

修改：

- `backend/graph_system/work_order_executor.py`
- `backend/graph_system/memory_candidate_registry.py`
- `backend/task_system/writing_graphs/memory_candidate_handlers.py`

目标：

- memory commit guard 不能直接把业务拒绝压成 technical failed。
- 如果提交员输出 `revision_requested`，正式 memory commit 跳过。
- 诊断 artifact 保留，baseline memory 不写入。
- memory candidate 标记为 rejected/candidate_diagnostic，不进入可读基准库。

### Phase 6：任务图配置编译器支持 outcome / transition policy

修改：

- `backend/task_system/graphs/task_graph_models.py`
- `backend/task_system/compiler/executable_graph_config_publisher.py`
- `scripts/configure_writing_modular_novel_graph.py`

目标：

- NodeSpec 支持 `outcome_policy`。
- EdgeSpec 支持 `transition_policy`。
- 写作图生成器根据节点声明生成 revision edge。
- 生成逻辑按通用字段，不写死世界观、人设、章节。

### Phase 7：任务环境上下文回传

修改：

- `backend/graph_system/context_materializer.py`
- `backend/harness/entrypoint/graph_node_work_order_bridge.py`

目标：

- revision frame 打开的回传包成为目标节点的 `已授权输入`。
- 返修包显示为路标，不混入旧上下文。
- agent 能看到：

```text
你正在处理 revision frame
来源节点
返修原因
受影响范围
需要保留的上游事实
不得自行越权改动的边界
```

### Phase 8：真实运行验证

验证方式不用新增测试文件，走真实 CLI/API：

```text
1. compileall 变更后端文件
2. 固定 8003 重启后端
3. 重新发布写作图配置
4. 用两百章脚本启动
5. 跑到第 11 章停下
6. 人工检查：
   - revision_requested 不导致整图 failed
   - revision frame 会回到声明目标节点
   - 提交失败报告不进入 baseline memory
   - 通过后下游重新执行
   - chapter_011 产物存在
```

## 6. 当前写作图问题的修复路径

针对本次实测，不手工跳过 `memory_commit_world`，也不让 GraphSystem 硬编码 `world_design`。

正确修复后，当前链路应变成：

```text
memory_commit_world
-> execution_status = completed
-> outcome_kind = revision_requested
-> selected edge = revision_request
-> target = 图实例声明的 source_candidate_node
-> world_design ready
-> world_design 收到返修交接包
-> world_review 重跑
-> memory_commit_world 重跑
-> outcome_kind = completed
-> baseline memory commit
-> character_design / plot_design ready
```

如果后续某个项目网络审查图也需要返修，它使用同一个算法：

```text
file_review_node
-> outcome_kind = revision_requested
-> selected revision edge
-> file_semantic_builder ready
```

算法完全复用，实例只声明边和 contract。

## 7. 不做什么

严禁：

- 在 GraphSystem 写 `if node_id == "memory_commit_world"`。
- 在 TransitionProcessor 里解析“散修”“提交失败”“世界观”。
- 把业务返修继续作为 `node_failed` 终止整图。
- 让提交失败报告写入正式基准记忆。
- 用脚本手工把失败节点后面的节点置 ready。
- 靠 prompt 要求 agent “别失败”，绕过算法缺口。

允许：

- 写作图 adapter 识别写作契约里的裁决文本，并映射为通用 outcome。
- 图实例声明 revision edge。
- GraphSystem 根据 outcome 和 edge policy 执行通用状态转移。

## 8. 成熟度验收标准

这套修复完成后，图任务应具备以下能力：

| 能力 | 标准 |
| --- | --- |
| 业务返修 | agent 正常完成后可请求返修，不导致整图 technical failed |
| 时空回滚 | 系统按因果范围失效下游，不删除历史审计 |
| 重放 | 目标节点 ready 后重新执行，下游按新结果重放 |
| 提交安全 | 未通过 precommit 的内容不进入正式记忆 |
| 配置化 | 不同图实例只声明 outcome/edge/policy，算法不写领域分支 |
| 可恢复 | checkpoint 中能恢复 active frame 和 ready nodes |
| 可观测 | monitor 能看到 outcome、frame、失效范围和下一节点 |

## 9. 实施顺序裁决

先做算法底座，再修写作图实例：

```text
OutcomeSignal 模型
-> Outcome Normalizer
-> TransitionPolicy 选择边
-> ControlFrame / RevisionFrame
-> Precommit / Commit 两阶段
-> 图配置字段和编译
-> 写作图实例迁移
-> 两百章脚本真实验证
```

这样修复后，写作图、项目网络审查图、tree reduce 图、循环迭代图都能复用同一套图任务时空算法。

## 10. 当前算法层不成熟设计审查

本节是对现有 `graph_system` 算法层的补充审查。判断标准不是“当前能不能跑”，而是它是否足够承载可恢复、可解释、可复用的图任务时空系统。

结论：当前主链路已经有图运行的骨架，但算法层仍然把业务语义、执行状态、恢复策略、边选择、上下文回传和副作用提交混在一起。它能支撑简单 DAG 和部分循环任务，但不足以稳定承载写作图返修、项目网络树状审查、分布式回传、维护补线和跨 session 恢复。

| 位置 | 当前不成熟设计 | 为什么不合格 | 目标修复 |
| --- | --- | --- | --- |
| `backend/graph_system/models.py` `NodeResultEnvelope` | 只有 `status = completed / failed / blocked / waiting_human_gate`，没有 `execution_status`、`outcome_signals`、`materialization_status`。 | 一个字段同时表示模型是否正常返回、业务是否通过、质量是否通过、是否要返修、是否可恢复。下游只能猜，导致“业务返修”被当成“节点失败”。 | 增加一等 `OutcomeSignal`，并把执行状态、业务 outcome、物化状态分离。 |
| `backend/graph_system/runtime_algorithm_types.py` | `RuntimeAlgorithmPostprocessResult` 只有 `postprocess_errors / quality_acceptance / side_effects / output_patch`。 | adapter 只能通过 error 或 patch 间接影响图算法，不能明确输出“重试、返修、等待人工、跳过提交”等控制信号。 | 改为 adapter 可输出 `outcome_signals`、`materialization_intents`、`control_hints`，error 只保留技术失败。 |
| `backend/graph_system/work_order_executor.py` | 先物化 artifact / memory，再把所有 postprocess error 合并成 `failed`。 | 提交前检查、正式提交、诊断 artifact、业务拒绝没有阶段边界；一旦 agent 合法拒绝提交，就被压成技术失败。 | 引入 `precommit -> outcome normalization -> commit/materialize` 两阶段。只有 `completed` outcome 才正式写基准记忆。 |
| `backend/graph_system/work_order_executor.py` `_memory_commit_failure_guard_errors` | 通过“提交失败 / commit failed”文本生成 `memory_commit_declared_failed` error。 | 这是领域文本解析，不应该直接控制 executor status；它把合法的业务拒绝变成 graph failed。 | 改为 memory commit outcome normalizer：识别为 `revision_requested` 或 `commit_rejected` outcome，不写正式 memory，不触发普通下游边。 |
| `backend/graph_system/transition_processor.py` | 边选择核心是 `result.status == "completed"`，再叠加 review revision 特判。 | 没有真正消费 edge contract 的 `transition_policy`；配置层看似有策略，算法层仍按旧规则跑。 | TransitionProcessor 只读取 `OutcomeSignal` 与 `edge.transition_policy.trigger_outcomes`，普通边默认 `completed`，返修边默认 `revision_requested`。 |
| `backend/graph_system/transition_processor.py` | `source_result_revision_signal()` 在 transition 层直接解析审查结论。 | transition 层既做 outcome 归一，又做边选择，权责重复；后续任何业务领域都要塞特例。 | 把领域解析移动到 outcome normalizer / domain adapter；transition 层只消费归一结果。 |
| `backend/graph_system/readiness_evaluator.py` | pending revision edge 通过 edge type、semantic role、edge_id 命名规则忽略。 | readiness 依赖命名启发式，不依赖正式策略；新增 edge 类型或命名变化时会误判。 | 用 `readiness_policy.activation_outcomes / optional_until_selected / conditional_group` 描述条件边激活规则。 |
| `backend/graph_system/loop.py` `accept_node_result()` | 一个函数里同时做 side effect、节点状态、边转移、返修、loop route、质量重试、终态判断和派发。 | 决策权过度集中，顺序耦合严重；新增一种控制流就容易插分支，无法形成成熟算法栈。 | 拆成固定 pipeline：`NormalizeResult -> ApplyEffects -> TransitionPlan -> OpenFrames -> InvalidateReplay -> StatusSnapshot -> Dispatch`。 |
| `backend/graph_system/loop.py` `_ready_rejected_revision_targets()` | 返修目标依赖“ready 的 revision edge + 最新 result summary 再解析一次”。 | outcome 没有和 edge decision 绑定；恢复后可能因为 summary 截断、丢字段、重复解析而漂移。 | 在 transition plan 里持久化 `selected_outcome_ref / source_result_ref / target_node_id`，返修 frame 从 plan 建立。 |
| `backend/graph_system/loop.py` `_state_after_revision_requeue()` | 返修是直接重置节点和边，不是控制 frame。 | 缺少 `frame_id`、source、scope、invalidation 记录、关闭条件和 replay 审计；恢复时无法清楚知道“为什么回到这里”。 | 升级为 `ControlFrame(kind="revision")`，记录 source result、target、失效范围、携带上下文和关闭条件。 |
| `backend/graph_system/loop.py` `_revision_reset_node_ids()` | 失效范围沿非 revision 边全局下游遍历，跳过 resource node。 | 这是粗粒度图遍历，不区分普通依赖、物化依赖、审计边、可保留节点、跨 frame 边界；大图上容易误清或漏清。 | 建立 `InvalidationPolicy`：按 edge role、artifact/memory dependency、loop frame 边界和 materialization status 计算失效范围。 |
| `backend/graph_system/loop.py` `_quality_same_node_retry_decision()` | 质量重试是独立 blocked 分支，不与返修/重试 outcome 统一。 | retry、revision、human gate 都是控制事件，但现在分散成特殊路径，无法共享 frame、checkpoint、可观测性。 | 质量失败输出 `retry_requested` outcome，打开 `ControlFrame(kind="retry")` 或选择 retry transition。 |
| `backend/graph_system/context_materializer.py` `_self_quality_failure_contexts_for_node()` | 质量重试上下文通过虚拟 packet 拼出来，edge_id 是临时字符串。 | 反馈能送到 agent，但不是正式 transition/frame 产物；监控、恢复、审计不能统一追踪。 | 由 ControlFrame 生成正式 replay packet，作为授权输入进入目标节点。 |
| `backend/graph_system/runtime_algorithm_effects.py` | side effect request 藏在 result diagnostics 中，失败后把 result 改成 blocked。 | 副作用申请、授权、执行和回执没有进入 transition plan；required effect 会绕过 outcome 层改变状态。 | side effect 必须成为 `EffectIntent -> EffectReceipt -> OutcomeSignal` 的显式阶段，由算法 pipeline 统一裁决。 |
| `backend/graph_system/resume.py` | recoverable 判断靠 reason 字符串集合和 `resume_retryable` 标记。 | 恢复策略不是由 checkpoint/frame/outcome policy 驱动，新增失败类型时会继续堆字符串。 | checkpoint 保存 `active_frames`、`recoverability_policy`、`last_outcome`、`pending_effects`；resume 只按这些结构化策略恢复。 |
| `backend/graph_system/state_machine.py` | 终态判断看到 failed 就终止，blocked 就图 blocked。 | 对成熟图任务而言，很多 failed/blocked 是可恢复 outcome 的中间态；state machine 不应在 outcome 未归一前终止图。 | state machine 只消费算法阶段输出的 `GraphStatusIntent`，不要直接解释 node status。 |
| `backend/task_system/compiler/writing_graph_config_migrator.py` | 迁移器生成 `transition_policy/readiness_policy`，但运行时主要当 snapshot 记录。 | 配置层和运行层没有闭环，策略字段容易变成“文档化装饰”。 | 编译器输出正式 `trigger_outcomes`、`route_role`、`optional_until_selected`、`invalidation_policy`，运行时强制消费。 |
| `backend/task_system/writing_graphs/revision_signal_handlers.py` | 写作返修解析大量依赖正文、章节号、中文标题和 regex。 | 这是领域 adapter 可以存在的能力，但不应是图算法判断返修是否发生的主证据。 | 写作 adapter 只负责从写作契约中提取 `revision_payload`；是否返修由 `OutcomeSignal(revision_requested)` 明示。 |
| `backend/graph_system/background_supervisor.py` | `_state_needs_followup_submit()` 把 blocked / failed 也当作可能继续提交。 | 外层 supervisor 在补内层恢复算法缺口，容易出现重复恢复、错误续跑或失败状态反复提交。 | supervisor 只看 GraphLoop 产出的 `dispatchable / waiting / terminal / recoverable` 结构化状态。 |
| `backend/graph_system/runtime_objects.py` `node_result_summary()` | summary 保留 status、部分 outputs、error，但没有 outcome/frame/effect 索引。 | 后续 transition/revision/resume 又从 summary 反推语义，容易因截断或字段遗漏失真。 | summary 必须包含 `primary_outcome`、`outcome_refs`、`control_frame_refs`、`effect_receipt_refs`。 |

### 10.1 当前最危险的三类问题

1. **状态字段过载**

`status` 被用作所有控制语义的代理，这是本次写作图失败的直接根因。成熟图算法必须让 `status` 回到执行层，把“返修、重试、等待人工、提交拒绝”变成 outcome。

2. **策略声明和运行消费断开**

编译器已经在 edge contract 中保留 `transition_policy/readiness_policy`，但 `TransitionProcessor` 和 `ReadinessEvaluator` 没有以这些策略为主入口。这会让图编辑器、配置、文档都看似正确，而真实运行仍然按硬编码启发式走。

3. **控制流没有 frame 化**

loop frame 已经存在，但 revision / retry / human gate 还没有统一成 control frame。只要控制流不是 frame，恢复、审计、补线、重放、上下文回传都会散落在多个函数里。

### 10.2 目标权责链

目标算法层必须收束为单向链路：

```text
RawNodeExecution
-> ResultNormalizer
-> OutcomeSignal[]
-> EffectIntent / MaterializationIntent
-> TransitionPlan
-> ControlFramePlan
-> InvalidationReplayPlan
-> GraphStatusSnapshot
-> DispatchPlan
```

各层边界：

- `work_order_executor`：只产出原始执行结果、结构化输出、物化候选和技术执行错误。
- `outcome_normalizer`：唯一负责把领域 adapter、质量门、提交前检查归一为 outcome。
- `transition_processor`：唯一负责 outcome 到 edge 的选择。
- `frame_manager`：唯一负责 revision/retry/human gate 等控制 frame 的打开、关闭、checkpoint。
- `invalidation_engine`：唯一负责按因果边界清理下游状态。
- `state_machine`：只分类最终图状态，不再解析业务语义。
- `supervisor/runner`：只执行和续跑，不参与恢复语义判断。

### 10.3 修复优先级

优先级必须按底层算法推进，不按当前写作节点打补丁：

1. 模型层补 `OutcomeSignal` 和 `ControlFrame`，先让数据结构有承载空间。
2. `work_order_executor` 停止把所有 postprocess error 压成 failed，先输出结构化 outcome 候选。
3. `transition_processor` 改为消费 `trigger_outcomes`。
4. `readiness_evaluator` 改为消费 compiled readiness policy，移除 edge_id 命名启发式。
5. `loop.py` 把 `accept_node_result()` 拆成 pipeline，并把 revision / retry 统一为 frame。
6. `resume.py` 改为基于 checkpoint + frame + recoverability policy 恢复。
7. 写作图迁移：把写作领域返修文本解析降级为 adapter，不再让算法层重复解析业务文本。

### 10.4 不合格设计的清理原则

实施时要直接清理这些旧结构，不继续兼容：

- 任何在 `GraphSystem` 中解析“世界观、章节、提交失败、返修要求”等业务词的逻辑。
- 任何靠 edge_id 字符串片段判断控制边激活状态的逻辑。
- 任何把业务拒绝写成 `failed` 再靠 resume 字符串白名单救回来的逻辑。
- 任何只把 `transition_policy/readiness_policy` 记录到 snapshot，却不作为运行裁决依据的逻辑。
- 任何把 retry/revision/human gate 分别做成独立特殊分支，而不纳入 control frame 的逻辑。

保留但迁移：

- 现有 loop frame 的 cursor、iteration、route history 能力可以复用。
- 写作图 revision regex 可以作为领域 adapter 的弱证据，但不能作为算法层主证据。
- quality retry 的失败上下文可以保留，但要由正式 retry frame/packet 生成。
- background supervisor 的并发续跑机制可以保留，但恢复判断要下沉回 GraphLoop 的结构化状态。
